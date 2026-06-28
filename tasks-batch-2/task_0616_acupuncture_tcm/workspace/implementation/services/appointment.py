"""Appointment lifecycle transitions and their cascades (PRD 3.5, 3.7)."""

from datetime import timedelta

from clock import clock
from common import parse_iso8601, touch
from db import db
from services import billing
from services.package import reconcile_series

GRACE_SECONDS = 10 * 60  # 10-minute grace allowance (arrival_class calc).
LATE_CANCEL_CUTOFF_SECONDS = 24 * 60 * 60  # 24-hour late-cancellation cutoff.


def void_attached_addons(appt_id):
    """Move every ATTACHED add-on of the appointment to VOIDED (its own version
    bump + updated_at)."""
    for a in db.addons.values():
        if a["appointment_id"] == appt_id and a["status"] == "ATTACHED":
            a["status"] = "VOIDED"
            touch(a)


def void_billing_artifacts(appt_id):
    """Move any OPEN Charge / ISSUED Superbill for the appointment to VOID."""
    voided_any = False
    for c in db.charges.values():
        if c["appointment_id"] == appt_id and c["status"] == "OPEN":
            c["status"] = "VOID"
            touch(c)
            voided_any = True
    for s in db.superbills.values():
        if s["appointment_id"] == appt_id and s["status"] == "ISSUED":
            s["status"] = "VOID"
            touch(s)
            voided_any = True
    return voided_any


def _series_of(appt):
    sid = appt.get("package_series_id")
    if sid is None:
        return None
    return db.package_series.get(sid)


# --------------------------------------------------------------------------
# Check-in: SCHEDULED -> CHECKED_IN
# --------------------------------------------------------------------------
def check_in(appt):
    now = clock.now()
    appt["checked_in_at"] = _to_iso(now)
    start = parse_iso8601(appt["scheduled_start"])
    delta_seconds = (now - start).total_seconds()
    # arrival_class: LATE when delta strictly > grace; ON_TIME otherwise.
    appt["arrival_class"] = "LATE" if delta_seconds > GRACE_SECONDS else "ON_TIME"
    appt["clinical_status"] = "CHECKED_IN"
    touch(appt)


# --------------------------------------------------------------------------
# Complete: CHECKED_IN -> COMPLETED
# --------------------------------------------------------------------------
def complete(appt, patient):
    appt["clinical_status"] = "COMPLETED"
    if appt["charge_source"] == "PACKAGE":
        # reserved -1, consumed +1 (net provisional unchanged; finalized -1).
        series = _series_of(appt)
        # billing_status -> BILLED (parallel dimension).
        appt["billing_status"] = "BILLED"
        touch(appt)
        if series is not None:
            reconcile_series(series)
    else:  # PER_VISIT
        if patient["payer_mode"] == "INSURANCE":
            billing.create_superbill(appt, patient)
        else:
            billing.create_visit_charge_cash(appt)
        appt["billing_status"] = "BILLED"
        touch(appt)


# --------------------------------------------------------------------------
# No-show: SCHEDULED -> NO_SHOW
# --------------------------------------------------------------------------
def no_show(appt, patient):
    prior_strikes = patient["strike_count"]
    # Record this appointment as the producing strike.
    patient["strike_count"] = prior_strikes + 1
    touch(patient)

    appt["clinical_status"] = "NO_SHOW"

    penalty = billing.compute_penalty("NO_SHOW", prior_strikes, patient["membership_status"])
    if penalty > 0:
        billing.create_penalty_charge(appt, penalty)
        appt["billing_status"] = "PENALTY_DUE"
    else:
        appt["billing_status"] = "WAIVED"

    # Void attached add-ons.
    void_attached_addons(appt["id"])

    touch(appt)

    # PACKAGE: release reservation (credit not consumed).
    if appt["charge_source"] == "PACKAGE":
        series = _series_of(appt)
        if series is not None:
            reconcile_series(series)


# --------------------------------------------------------------------------
# Cancel: {SCHEDULED, CHECKED_IN} -> CANCELLED (transitive cascade)
# --------------------------------------------------------------------------
def cancel(appt, patient):
    # HOP-1: this appointment -> CANCELLED; void add-ons; void billing artifacts.
    appt["clinical_status"] = "CANCELLED"
    void_attached_addons(appt["id"])
    voided = void_billing_artifacts(appt["id"])

    # Late-cancellation determination (measured back from scheduled_start).
    now = clock.now()
    start = parse_iso8601(appt["scheduled_start"])
    lead_seconds = (start - now).total_seconds()
    is_late = lead_seconds <= LATE_CANCEL_CUTOFF_SECONDS

    if is_late:
        prior_strikes = patient["strike_count"]
        patient["strike_count"] = prior_strikes + 1
        touch(patient)
        penalty = billing.compute_penalty(
            "LATE_CANCEL", prior_strikes, patient["membership_status"]
        )
        if penalty > 0:
            billing.create_penalty_charge(appt, penalty)
            appt["billing_status"] = "PENALTY_DUE"
        else:
            # A zero-penalty late cancel waives billing.
            appt["billing_status"] = "WAIVED"
    elif voided:
        # Cancellation voided a produced charge/superbill -> billing WAIVED.
        appt["billing_status"] = "WAIVED"
    else:
        # Outside cutoff with nothing to void: if billing had reached a billed
        # state it moves to WAIVED; otherwise it stays UNBILLED.
        if appt["billing_status"] in ("BILLED", "PENALTY_DUE"):
            appt["billing_status"] = "WAIVED"

    touch(appt)

    # HOP-2 / HOP-3: package credit release + EXHAUSTED->ACTIVE auto-eval.
    if appt["charge_source"] == "PACKAGE":
        series = _series_of(appt)
        if series is not None:
            reconcile_series(series)


def _to_iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

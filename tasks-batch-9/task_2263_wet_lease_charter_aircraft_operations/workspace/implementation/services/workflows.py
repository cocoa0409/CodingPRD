"""Shared state-machine machinery: cascades, recomputations and derived fields."""

from db import db, new_row, touch, clock_now
from services import calculations as C

LIVE_LEG_STATUSES = C.LIVE_LEG_STATUSES

PERIOD_CHARGE_FIELDS = (
    "mgh_effective_hours",
    "credited_block_minutes",
    "credited_hours",
    "shortfall_hours",
    "lessor_attributable_shortfall_hours",
    "overrun_hours",
    "base_charge_cents",
    "shortfall_credit_cents",
    "overrun_charge_cents",
    "gross_charge_cents",
    "reliability_penalty_cents",
)


# ------------------------------------------------------------------ lookups

def legs_of_lease(lease_id):
    return [leg for leg in db.flight_legs.values() if leg["lease_id"] == lease_id]


def legs_of_aircraft(aircraft_id):
    return [leg for leg in db.flight_legs.values() if leg["aircraft_id"] == aircraft_id]


def certificates_of_lease(lease_id):
    return [c for c in db.insurance_certificates.values() if c["lease_id"] == lease_id]


def approvals_of_lease(lease_id):
    return [a for a in db.regulatory_approvals.values() if a["lease_id"] == lease_id]


def qualifications_of_lease(lease_id):
    return [q for q in db.crew_qualifications.values() if q["lease_id"] == lease_id]


def periods_of_lease(lease_id):
    return [p for p in db.utilization_periods.values() if p["lease_id"] == lease_id]


def invoices_of_period(period_id):
    return [i for i in db.settlement_invoices.values() if i["period_id"] == period_id]


def aircraft_of_lease(lease_id):
    return [a for a in db.aircraft.values() if a["assigned_lease_id"] == lease_id]


def substitutions_of_lease(lease_id):
    return [s for s in db.substitutions.values() if s["lease_id"] == lease_id]


def month_legs_of_lease(lease_id, period_month):
    return [leg for leg in legs_of_lease(lease_id)
            if C.month_of(leg["_scheduled_out"]) == period_month]


def returns_of_lease(lease_id):
    return [r for r in db.return_conditions.values() if r["lease_id"] == lease_id]


def accepted_report_for(lease_id, period_month):
    rows = [r for r in db.reliability_reports.values()
            if r["lease_id"] == lease_id
            and r["period_month"] == period_month
            and r["status"] == "ACCEPTED"]
    if not rows:
        return None
    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    return rows[-1]


def period_for(lease_id, period_month):
    for period in db.utilization_periods.values():
        if period["lease_id"] == lease_id and period["period_month"] == period_month:
            return period
    return None


def open_period_for(lease_id, period_month):
    period = period_for(lease_id, period_month)
    if period is not None and period["status"] == "OPEN":
        return period
    return None


def active_certificate_covering(lease_id, instant, require_additional_insured=False):
    for cert in certificates_of_lease(lease_id):
        if cert["status"] != "ACTIVE":
            continue
        if require_additional_insured and not cert["additional_insured_lessee"]:
            continue
        if cert["_effective_from"] <= instant <= cert["_expires_at"]:
            return cert
    return None


# ------------------------------------------------------------------ crew exposure

def recompute_crew(crew_id):
    crew = db.crew_members.get(crew_id)
    if crew is None:
        return
    duty, block = C.rolling_exposure(crew_id, list(db.flight_legs.values()), clock_now())
    if crew["rolling_duty_minutes_7d"] != duty or crew["rolling_block_minutes_28d"] != block:
        crew["rolling_duty_minutes_7d"] = duty
        crew["rolling_block_minutes_28d"] = block
        touch(crew)


def recompute_all_crew():
    for crew_id in list(db.crew_members.keys()):
        recompute_crew(crew_id)


def recompute_leg_crew(leg):
    recompute_crew(leg["captain_id"])
    recompute_crew(leg["first_officer_id"])


# ------------------------------------------------------------------ periods

def compute_period(period, variant):
    lease = db.leases[period["lease_id"]]
    report = accepted_report_for(period["lease_id"], period["period_month"])
    return C.monthly_utilization_charge(
        lease, period["period_month"], legs_of_lease(period["lease_id"]), variant, report)


def apply_charge(period, variant, force_touch=False, silent=False):
    result = compute_period(period, variant)
    changed = False
    for field in PERIOD_CHARGE_FIELDS:
        if period.get(field) != result[field]:
            period[field] = result[field]
            changed = True
    target = "provisional_charge_cents" if variant == "PROVISIONAL" else "final_charge_cents"
    if period.get(target) != result["net_charge_cents"]:
        period[target] = result["net_charge_cents"]
        changed = True
    if period.get("variant_applied") != variant:
        period["variant_applied"] = variant
        changed = True
    if silent:
        return result
    if changed or force_touch:
        touch(period)
    return result


def recompute_open_period_for_leg(leg):
    period = open_period_for(leg["lease_id"], C.month_of(leg["_scheduled_out"]))
    if period is not None:
        apply_charge(period, "PROVISIONAL")


def create_period(lease, period_month):
    period = new_row()
    period.update({
        "lease_id": lease["id"],
        "period_month": period_month,
        "mgh_effective_hours": 0.0,
        "credited_block_minutes": 0,
        "credited_hours": 0.0,
        "shortfall_hours": 0.0,
        "lessor_attributable_shortfall_hours": 0.0,
        "overrun_hours": 0.0,
        "base_charge_cents": 0,
        "shortfall_credit_cents": 0,
        "overrun_charge_cents": 0,
        "gross_charge_cents": 0,
        "reliability_penalty_cents": 0,
        "provisional_charge_cents": 0,
        "final_charge_cents": 0,
        "variant_applied": "PROVISIONAL",
        "dispute_reason": None,
        "disputed_amount_cents": 0,
        "status": "OPEN",
    })
    db.utilization_periods[period["id"]] = period
    apply_charge(period, "PROVISIONAL", silent=True)
    return period


def close_period(period, open_next_month):
    lease = db.leases[period["lease_id"]]
    apply_charge(period, "FINAL", force_touch=True)
    period["status"] = "PENDING_SETTLEMENT"
    if open_next_month:
        following = C.next_month(period["period_month"])
        if (C.month_first_day(following) <= C.date_from_iso(lease["term_end_date"])
                and lease["status"] in ("ACTIVE", "SUSPENDED")
                and period_for(lease["id"], following) is None):
            create_period(lease, following)
    return period


def mark_provisionally_billed(period):
    """Preparing a PROVISIONAL invoice advances the month's legs (PRD 3.6)."""
    for leg in month_legs_of_lease(period["lease_id"], period["period_month"]):
        if leg["status"] in LIVE_LEG_STATUSES and leg["billing_state"] == "UNBILLED":
            leg["billing_state"] = "PROVISIONALLY_BILLED"
            leg["_was_provisionally_billed"] = True
            touch(leg)


def settle_period(period):
    """PRD 3.9 — settlement freezes the month's completed legs and the lifetime total."""
    lease = db.leases[period["lease_id"]]
    for leg in month_legs_of_lease(period["lease_id"], period["period_month"]):
        if leg["status"] == "COMPLETED" and \
                leg["billing_state"] in ("UNBILLED", "PROVISIONALLY_BILLED"):
            leg["_was_provisionally_billed"] = (
                leg["billing_state"] == "PROVISIONALLY_BILLED")
            leg["billing_state"] = "FINALIZED"
            touch(leg)
    lease["lifetime_credited_block_minutes"] = (
        lease["lifetime_credited_block_minutes"] + period["credited_block_minutes"])
    touch(lease)
    period["status"] = "SETTLED"
    touch(period)


def unsettle_period(period, new_status="PENDING_SETTLEMENT"):
    """The exact inverse of settle_period."""
    lease = db.leases[period["lease_id"]]
    for leg in month_legs_of_lease(period["lease_id"], period["period_month"]):
        if leg["billing_state"] == "FINALIZED":
            leg["billing_state"] = "PROVISIONALLY_BILLED" \
                if leg.get("_was_provisionally_billed") else "UNBILLED"
            touch(leg)
    lease["lifetime_credited_block_minutes"] = (
        lease["lifetime_credited_block_minutes"] - period["credited_block_minutes"])
    touch(lease)
    period["status"] = new_status
    touch(period)


# ------------------------------------------------------------------ legs

def cancel_leg(leg, cancelling_party, cancel_reason, status=None,
               requalification=False):
    leg["status"] = status or "CANCELLED_LESSOR"
    leg["cancelling_party"] = cancelling_party
    leg["cancel_reason"] = cancel_reason
    leg["billing_state"] = "CREDITED"
    if requalification:
        leg["crew_requalification_required"] = True
    touch(leg)
    recompute_leg_crew(leg)
    recompute_open_period_for_leg(leg)


# ------------------------------------------------------------------ lease cascades

def suspend_lease(lease, suspension_reason, cancel_reason, legs=None):
    """Levels two to four of a suspension cascade."""
    if lease["status"] != "ACTIVE":
        return False
    lease["status"] = "SUSPENDED"
    lease["suspension_reason"] = suspension_reason
    touch(lease)
    scope = legs_of_lease(lease["id"]) if legs is None else legs
    for leg in scope:
        if leg["status"] in ("SCHEDULED", "DISPATCHED"):
            cancel_leg(leg, "LESSOR", cancel_reason)
    return True


def insurance_lapse_cascade(lease):
    """Level two onwards of the insurance-lapse cascade."""
    if lease is None:
        return
    for cert in certificates_of_lease(lease["id"]):
        if cert["status"] == "ACTIVE":
            return
    suspend_lease(lease, "INSURANCE_LAPSED", "INSURANCE_LAPSE")


def release_airframe(lease):
    for aircraft in aircraft_of_lease(lease["id"]):
        aircraft["assigned_lease_id"] = None
        if aircraft["status"] == "ASSIGNED":
            aircraft["status"] = "AVAILABLE"
        touch(aircraft)


def revoke_qualifications(lease):
    for qual in qualifications_of_lease(lease["id"]):
        if qual["status"] != "REVOKED":
            qual["status"] = "REVOKED"
            touch(qual)


# ------------------------------------------------------------------ receivable

def lessee_balance(lessee_id):
    total = 0
    for invoice in db.settlement_invoices.values():
        if invoice["status"] != "ISSUED":
            continue
        lease = db.leases.get(invoice["lease_id"])
        if lease is not None and lease["lessee_id"] == lessee_id:
            total += invoice["amount_cents"]
    return total


def recompute_lessee_balance(lessee):
    total = lessee_balance(lessee["id"])
    if lessee["outstanding_balance_usd_cents"] != total:
        lessee["outstanding_balance_usd_cents"] = total
        touch(lessee)


def adjust_lessee_balance(lease, delta):
    lessee = db.lessees.get(lease["lessee_id"])
    if lessee is None:
        return
    lessee["outstanding_balance_usd_cents"] = \
        lessee["outstanding_balance_usd_cents"] + delta
    touch(lessee)


# ------------------------------------------------------------------ clock effects

def apply_clock_effects():
    now = clock_now()
    for cert in list(db.insurance_certificates.values()):
        if cert["status"] == "ACTIVE" and now > cert["_expires_at"]:
            cert["status"] = "EXPIRED"
            touch(cert)
            insurance_lapse_cascade(db.leases.get(cert["lease_id"]))
    today = now.date()
    for qual in list(db.crew_qualifications.values()):
        if qual["status"] == "QUALIFIED" and qual["checkride_valid_until"]:
            if today > C.date_from_iso(qual["checkride_valid_until"]):
                qual["status"] = "EXPIRED"
                touch(qual)
    recompute_all_crew()

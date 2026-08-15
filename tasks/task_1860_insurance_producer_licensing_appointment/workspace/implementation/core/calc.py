"""The calculation rules of SCAFFOLD section 1.3 (PRD section 3).

ce_compliance_determination, commission_amount_cents,
producer_ytd_issued_premium, fine_allocation, jit_filing_deadline,
renewal_window and producer_eligibility_posture.
"""

from datetime import datetime
from decimal import Decimal, ROUND_FLOOR

from . import constants as K
from .clock import add_days
from .store import db


# -- lookups ----------------------------------------------------------------

def producer_licenses(producer_id):
    return [l for l in db.licenses.values() if l["producer_id"] == producer_id]


def licenses_of_subject(subject_field, subject_id, state_code=None):
    rows = [
        l for l in db.licenses.values()
        if subject_id is not None and l[subject_field] == subject_id
    ]
    if state_code is not None:
        rows = [l for l in rows if l["state_code"] == state_code]
    return rows


def active_license_covering(subject_field, subject_id, state_code, loas):
    """The subject's ACTIVE license in state whose LOAs cover every needed line."""
    for lic in licenses_of_subject(subject_field, subject_id, state_code):
        if lic["status"] != "ACTIVE":
            continue
        if all(loa in lic["lines_of_authority"] for loa in loas):
            return lic
    return None


def active_license_in_state(subject_field, subject_id, state_code):
    for lic in licenses_of_subject(subject_field, subject_id, state_code):
        if lic["status"] == "ACTIVE":
            return lic
    return None


def appointments_of_subject(subject_field, subject_id, state_code=None):
    rows = [
        a for a in db.appointments.values()
        if subject_id is not None and a[subject_field] == subject_id
    ]
    if state_code is not None:
        rows = [a for a in rows if a["state_code"] == state_code]
    return rows


def active_appointment_covering(subject_field, subject_id, state_code, loa):
    for appt in appointments_of_subject(subject_field, subject_id, state_code):
        if appt["status"] == "ACTIVE" and loa in appt["lines_of_authority"]:
            return appt
    return None


def covering_appointment(producer, state_code, loa):
    """(appointment, via_agency) covering the line, own appointment preferred."""
    own = active_appointment_covering("producer_id", producer["id"], state_code, loa)
    if own is not None:
        return own, False
    if producer["agency_id"] is not None:
        agency_appt = active_appointment_covering(
            "agency_id", producer["agency_id"], state_code, loa
        )
        if agency_appt is not None:
            return agency_appt, True
    return None, False


def entry_for_application(application_id):
    for entry in db.commission_entries.values():
        if entry["application_id"] == application_id:
            return entry
    return None


# -- producer_ytd_issued_premium ---------------------------------------------

def producer_ytd_live(producer_id):
    """Sum of premium_cents over the producer's ISSUED applications whose
    issued_at falls in the logical clock's current calendar year
    [Jan 1 00:00:00Z, next Jan 1 00:00:00Z)."""
    now = db.now
    year_start = datetime(now.year, 1, 1)
    year_end = datetime(now.year + 1, 1, 1)
    total = 0
    for app in db.applications.values():
        if (
            app["producer_id"] == producer_id
            and app["status"] == "ISSUED"
            and app["issued_at"] is not None
            and year_start <= app["issued_at"] < year_end
        ):
            total += app["premium_cents"]
    return total


def recompute_producer_ytd(producer):
    producer["ytd_issued_premium_cents"] = producer_ytd_live(producer["id"])


def recompute_producer_held(producer_id):
    producer = db.producers.get(producer_id)
    if producer is None:
        return
    producer["commission_held_cents"] = sum(
        e["amount_cents"]
        for e in db.commission_entries.values()
        if e["producer_id"] == producer_id and e["status"] == "HELD"
    )


# -- ce_compliance_determination ----------------------------------------------

def ce_determination(lic):
    """(compliant, ce_completed_hours, ce_ethics_completed_hours).

    Input set: the license's ACCEPTED credits whose completed_on falls within
    [ce_period_start, ce_period_end], both ends inclusive.  Hour comparisons
    use >=; exact equality passes.
    """
    start = lic["ce_period_start"]
    end = lic["ce_period_end"]
    ethics = Decimal("0")
    general = Decimal("0")
    for credit in db.ce_credits.values():
        if credit["license_id"] != lic["id"] or credit["status"] != "ACCEPTED":
            continue
        completed = credit["completed_on"]
        if completed is None or not (start <= completed <= end):
            continue
        if credit["category"] == "ETHICS":
            ethics += credit["credit_hours"]
        else:
            general += credit["credit_hours"]

    required = lic["ce_required_hours"]
    ethics_required = lic["ce_ethics_required_hours"]
    ethics_display = min(ethics, ethics_required)
    if lic["license_class"] == "RESIDENT":
        # SPILLOVER: all ETHICS hours also count toward the total.
        completed_display = min(ethics + general, required)
        compliant = (ethics + general) >= required and ethics >= ethics_required
    else:
        # STRICT: ETHICS hours count only toward the ethics sub-requirement.
        completed_display = ethics_display + general
        compliant = general >= (required - ethics_required) and ethics >= ethics_required
    return compliant, completed_display, ethics_display


def recompute_license_ce(lic):
    _, completed_display, ethics_display = ce_determination(lic)
    lic["ce_completed_hours"] = completed_display
    lic["ce_ethics_completed_hours"] = ethics_display


# -- commission_amount_cents ---------------------------------------------------

def commission_amount_cents(app, producer, ytd_cents):
    """floor(premium * base_rate * volume_mult * uplift) - one terminal floor."""
    base_rate = K.LOA_BASE_RATE[app["line_of_authority"]]
    if ytd_cents < K.TIER2_THRESHOLD_CENTS:
        volume_mult = K.VOLUME_MULT_LOW
    elif ytd_cents < K.TIER3_THRESHOLD_CENTS:
        volume_mult = K.VOLUME_MULT_MID
    else:
        volume_mult = K.VOLUME_MULT_HIGH
    uplift = Decimal("1.00")
    if producer["agency_id"] is not None:
        agency_appt = active_appointment_covering(
            "agency_id", producer["agency_id"],
            app["state_code"], app["line_of_authority"],
        )
        if agency_appt is not None:
            uplift = K.AGENCY_UPLIFT
    raw = Decimal(app["premium_cents"]) * base_rate * volume_mult * uplift
    return int(raw.to_integral_value(rounding=ROUND_FLOOR))


# -- fine_allocation -------------------------------------------------------------

def compute_fine_allocations(action):
    """Waterfall allocation of a confirmed FINE over the subject producer's
    ISSUED applications in the action's state: premium_cents DESC then
    created_at ASC; per-line floor first, remainder cents one at a time in
    input-set order."""
    if action["action_type"] != "FINE" or action.get("producer_id") is None:
        return []
    apps = [
        a for a in db.applications.values()
        if a["producer_id"] == action["producer_id"]
        and a["state_code"] == action["state_code"]
        and a["status"] == "ISSUED"
    ]
    apps.sort(key=lambda a: (-a["premium_cents"], a["created_at"], a["_seq"]))
    if not apps:
        return []
    total_premium = sum(a["premium_cents"] for a in apps)
    fine = action["fine_amount_cents"]
    lines = [[a["id"], (fine * a["premium_cents"]) // total_premium] for a in apps]
    remainder = fine - sum(cents for _, cents in lines)
    index = 0
    while remainder > 0:
        lines[index][1] += 1
        remainder -= 1
        index += 1
    return [
        {"application_id": app_id, "allocated_cents": cents}
        for app_id, cents in lines
    ]


# -- jit_filing_deadline -----------------------------------------------------------

def jit_filing_deadline(submitted_at):
    return add_days(submitted_at, K.JIT_FILING_WINDOW_DAYS)


# -- producer_eligibility_posture ---------------------------------------------------

def eligibility_posture(producer, state_code, loa):
    """Fixed precedence: PRODUCER_SUSPENDED > LICENSE_GAP > APPOINTMENT_GAP."""
    result = {
        "eligibility_status": None,
        "license_id": None,
        "appointment_id": None,
        "via_agency": False,
    }
    if producer["status"] != "ACTIVE":
        result["eligibility_status"] = "PRODUCER_SUSPENDED"
        return result
    lic = active_license_covering("producer_id", producer["id"], state_code, [loa])
    if lic is None:
        result["eligibility_status"] = "LICENSE_GAP"
        return result
    result["license_id"] = lic["id"]
    appt, via_agency = covering_appointment(producer, state_code, loa)
    if appt is None:
        result["eligibility_status"] = "APPOINTMENT_GAP"
        return result
    result["appointment_id"] = appt["id"]
    result["via_agency"] = via_agency
    result["eligibility_status"] = "ELIGIBLE"
    return result

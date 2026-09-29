"""Shared domain logic: cascades, counters, eligibility and lookups."""

from datetime import timedelta
from decimal import Decimal

import db
from errors import ApiError
from services import calc

NON_TERMINAL_CASE_STATUSES = (
    "FILED", "DEFICIENT", "VERIFICATION_PENDING", "NOTIFICATION_PENDING",
    "COMMENCED", "RESPONSE_RECEIVED", "DEFAULT", "PANEL_APPOINTMENT",
    "PANEL_CONSTITUTED", "IMPLEMENTATION_WAITING", "STAYED",
)
TERMINAL_CASE_STATUSES = ("IMPLEMENTED", "ADMIN_CLOSED", "WITHDRAWN", "TERMINATED_COURT")

CASE_STATUSES = NON_TERMINAL_CASE_STATUSES + TERMINAL_CASE_STATUSES

SEATS_FOR_COUNT = {1: ("SOLE",), 3: ("PRESIDING", "CO_PANELIST_1", "CO_PANELIST_2")}
LIVE_SEAT_STATUSES = ("NOMINATED", "WAIVER_PENDING", "ACCEPTED")


# --------------------------------------------------------------------- lookups
def case_or_404(case_id):
    row = db.cases.get(case_id)
    if row is None:
        raise ApiError("ERR_CASE_NOT_FOUND")
    return row


def domain_or_404(domain_id):
    row = db.domains.get(domain_id)
    if row is None:
        raise ApiError("ERR_DOMAIN_NOT_FOUND")
    return row


def panelist_or_404(panelist_id):
    row = db.panelists.get(panelist_id)
    if row is None:
        raise ApiError("ERR_PANELIST_NOT_FOUND")
    return row


def appointment_or_404(appointment_id):
    row = db.appointments.get(appointment_id)
    if row is None:
        raise ApiError("ERR_APPOINTMENT_NOT_FOUND")
    return row


def decision_or_404(decision_id):
    row = db.decisions.get(decision_id)
    if row is None:
        raise ApiError("ERR_DECISION_NOT_FOUND")
    return row


def resource_or_404(table, row_id):
    if not isinstance(row_id, str):
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    row = table.get(row_id)
    if row is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    return row


def case_domain(case):
    return db.domains[case["domain_id"]]


def case_complainant(case):
    return db.complainants[case["complainant_id"]]


def case_registrar(case):
    return db.registrars.get(case_domain(case)["registrar_id"])


# ------------------------------------------------------------------- ownership
def ensure_case_owner(case, user_id, role):
    if role == "Complainant" and case["complainant_id"] != user_id:
        raise ApiError("ERR_NOT_OWNER")


def ensure_registrar_of_record(case, user_id):
    if case_domain(case)["registrar_id"] != user_id:
        raise ApiError("ERR_REGISTRAR_MISMATCH")


def ensure_respondent_identity(case, supplied_email):
    if case.get("verified_registrant_email") != supplied_email:
        raise ApiError("ERR_RESPONDENT_IDENTITY_MISMATCH")


# ---------------------------------------------------------------- case ledger
def case_fee_rows(case_id):
    return db.ordered(db.fees, lambda r: r["case_id"] == case_id)


def apply_ledger(case):
    """Recompute the three derived money fields from the whole ledger."""
    rows = [r for r in db.fees.values() if r["case_id"] == case["id"]]
    case["complainant_paid_cents"] = sum(r["amount_cents"] for r in rows
                                        if r["payer"] == "COMPLAINANT")
    case["respondent_paid_cents"] = sum(r["amount_cents"] for r in rows
                                       if r["payer"] == "RESPONDENT")
    case["paid_cents"] = sum(r["amount_cents"] for r in rows)


def mint_refunds(case, pct, reference):
    """Refund payer by payer in a fixed order: complainant first, respondent second."""
    for payer in ("COMPLAINANT", "RESPONDENT"):
        paid = sum(r["amount_cents"] for r in db.fees.values()
                   if r["case_id"] == case["id"] and r["payer"] == payer)
        refund = int(calc.round_half_up(Decimal(paid) * pct, 0))
        if refund > 0:
            row = db.event_row(
                case_id=case["id"],
                kind="REFUND",
                payer=payer,
                amount_cents=-refund,
                reference=reference,
                recorded_at=db.now_str(),
            )
            db.fees[row["id"]] = row
    apply_ledger(case)


# --------------------------------------------------------------- fee variants
def reprice(case, variant):
    seat_count = 1 if variant == "PROVISIONAL" else case["required_seat_count"]
    figures = calc.filing_fee_assessment(seat_count, case["expedited_requested"])
    case.update(figures)
    case["fee_variant_applied"] = variant


# ------------------------------------------------------------------- cascades
def release_lock(domain):
    if domain["lock_status"] == "LOCKED":
        domain["lock_status"] = "UNLOCKED"
        domain["locked_at"] = None
        db.touch(domain)


def discharge_accepted_seats(case):
    for row in db.ordered(db.appointments, lambda r: r["case_id"] == case["id"]):
        if row["status"] != "ACCEPTED":
            continue
        row["status"] = "DISCHARGED"
        db.touch(row)
        panelist = db.panelists.get(row["panelist_id"])
        if panelist is not None and panelist["active_case_load"] > 0:
            panelist["active_case_load"] -= 1
            db.touch(panelist)


def close_case(case, status, refund_pct=None, refund_reference=None,
               release_domain_lock=True, discharge=False):
    """The shared tail of every case closure."""
    closed_at = db.now()
    case["status"] = status
    case["closed_at"] = db.fmt(closed_at)
    case["refiling_bar_until"] = db.fmt(closed_at + timedelta(days=calc.COOLING_OFF_DAYS))
    if refund_pct is not None:
        mint_refunds(case, refund_pct, refund_reference)
    if release_domain_lock:
        release_lock(case_domain(case))
    if discharge:
        discharge_accepted_seats(case)
    complainant = db.complainants.get(case["complainant_id"])
    if complainant is not None and complainant["open_case_count"] > 0:
        complainant["open_case_count"] -= 1
        db.touch(complainant)
    db.touch(case)


def mark_verification_overdue(verification, credit_registrar=True):
    """REQUESTED -> OVERDUE, advancing both escalation counters."""
    verification["status"] = "OVERDUE"
    verification["escalation_count"] += 1
    db.touch(verification)
    if credit_registrar:
        case = db.cases.get(verification["case_id"])
        registrar = case_registrar(case) if case else None
        if registrar is not None:
            registrar["overdue_verification_count"] += 1
            db.touch(registrar)


def credit_registrar_for_overdue(case):
    registrar = case_registrar(case)
    if registrar is not None and registrar["overdue_verification_count"] > 0:
        registrar["overdue_verification_count"] -= 1
        db.touch(registrar)


# ------------------------------------------------------------ panel plumbing
def case_appointments(case_id):
    return db.ordered(db.appointments, lambda r: r["case_id"] == case_id)


def accepted_seats(case_id):
    return [r for r in case_appointments(case_id) if r["status"] == "ACCEPTED"]


def panel_fully_constituted(case):
    required = SEATS_FOR_COUNT[case["required_seat_count"]]
    held = [r["seat"] for r in accepted_seats(case["id"])]
    return sorted(held) == sorted(required)


def allocate_honoraria(case):
    allocation = calc.honoraria_allocation(case["honoraria_pool_cents"],
                                           case["required_seat_count"])
    for row in accepted_seats(case["id"]):
        amount = allocation.get(row["seat"], 0)
        if row["honoraria_cents"] != amount:
            row["honoraria_cents"] = amount
            db.touch(row)


def try_constitute(case):
    """Called after any seat becomes ACCEPTED."""
    if case["status"] != "PANEL_APPOINTMENT":
        return False
    if not panel_fully_constituted(case):
        return False
    case["status"] = "PANEL_CONSTITUTED"
    allocate_honoraria(case)
    db.touch(case)
    return True


def accept_seat(appointment, case):
    """The shared tail of direct acceptance and of a granted waiver."""
    accepted_at = db.now()
    appointment["status"] = "ACCEPTED"
    appointment["accepted_at"] = db.fmt(accepted_at)
    appointment["decision_due_at"] = db.fmt(calc.decision_due(accepted_at))
    panelist = db.panelists[appointment["panelist_id"]]
    panelist["active_case_load"] += 1
    db.touch(panelist)


# ------------------------------------------------------------- eligibility
def _dt(value):
    return db.parse_dt(value) if value else None


def non_temporal_eligible(panelist, case, appointment_id=None):
    if panelist["status"] != "AVAILABLE":
        return False
    complainant = db.complainants.get(case["complainant_id"])
    if complainant is not None and panelist["nationality_code"] == complainant["country_code"]:
        return False
    if panelist["nationality_code"] == case["mutual_jurisdiction"]:
        return False
    for row in case_appointments(case["id"]):
        if appointment_id is not None and row["id"] == appointment_id:
            continue
        if row["panelist_id"] == panelist["id"] and row["status"] in LIVE_SEAT_STATUSES:
            return False
    return True


def window_conflict(panelist, case_id, appointment_id=None):
    """Candidate window [clock, clock + 14 days), half-open on the right."""
    start = db.now()
    end = start + timedelta(days=calc.DECISION_PERIOD_DAYS)
    for row in db.appointments.values():
        if row["panelist_id"] != panelist["id"] or row["status"] != "ACCEPTED":
            continue
        if row["case_id"] == case_id:
            continue
        if appointment_id is not None and row["id"] == appointment_id:
            continue
        other_case = db.cases.get(row["case_id"])
        if other_case is None or other_case["status"] not in NON_TERMINAL_CASE_STATUSES:
            continue
        engaged_from = _dt(row["accepted_at"])
        engaged_to = _dt(row["decision_due_at"])
        if engaged_from is None or engaged_to is None:
            continue
        if start < engaged_to and engaged_from < end:
            return True
    blackout_from = _dt(panelist.get("unavailable_from"))
    blackout_to = _dt(panelist.get("unavailable_to"))
    if blackout_from is not None:
        # Closed on both ends: touching either endpoint collides.
        upper = blackout_to if blackout_to is not None else blackout_from
        if start <= upper and blackout_from <= end:
            return True
    return False


def capacity_exceeded(panelist):
    return panelist["active_case_load"] >= panelist["max_overlapping_engagements"]


def select_panelist(case, appointment_id=None):
    eligible = []
    for panelist in db.panelists.values():
        if not non_temporal_eligible(panelist, case, appointment_id):
            continue
        if window_conflict(panelist, case["id"], appointment_id):
            continue
        if capacity_exceeded(panelist):
            continue
        eligible.append(panelist)
    if not eligible:
        raise ApiError("ERR_NO_ELIGIBLE_PANELIST")
    eligible.sort(key=lambda p: (p["active_case_load"],
                                 db.parse_dt(p["roster_admitted_at"]),
                                 db.parse_dt(p["created_at"]),
                                 p["_seq"]))
    return eligible[0]


def check_named_candidate(panelist, case, appointment_id=None):
    """Named nominations report each failure family separately."""
    if not non_temporal_eligible(panelist, case, appointment_id):
        raise ApiError("ERR_PANELIST_INELIGIBLE")
    if window_conflict(panelist, case["id"], appointment_id):
        raise ApiError("ERR_PANELIST_WINDOW_CONFLICT")
    if capacity_exceeded(panelist):
        raise ApiError("ERR_PANELIST_CAPACITY_EXCEEDED")


# --------------------------------------------------------------- deadlines
def project_provisional_deadline(case, notification):
    dispatched = db.parse_dt(notification["dispatched_at"])
    due = calc.provisional_response_due(dispatched, notification["channel"])
    case["provisional_response_due_at"] = db.fmt(due)
    case["response_due_at"] = db.fmt(due)
    case["deadline_variant_applied"] = "PROVISIONAL"


def project_final_deadline(case, deemed_received_at):
    case["response_due_at"] = db.fmt(calc.final_response_due(deemed_received_at))
    case["deadline_variant_applied"] = "FINAL"


def highest_notification(case_id):
    rows = [r for r in db.notifications.values() if r["case_id"] == case_id]
    if not rows:
        return None
    return max(rows, key=lambda r: r["attempt_number"])


def case_response(case_id):
    for row in db.responses.values():
        if row["case_id"] == case_id:
            return row
    return None


# --------------------------------------------------------------- precedents
def entry_for_decision(decision_id):
    for row in db.precedents.values():
        if row["decision_id"] == decision_id:
            return row
    return None


def citation_count(decision_id):
    total = 0
    for ground in db.grounds.values():
        for cited in ground.get("cited_decision_ids") or []:
            if cited == decision_id:
                total += 1
    return total


def precedent_view(entry):
    decision = db.decisions.get(entry["decision_id"])
    count = citation_count(entry["decision_id"])
    superseded = bool(decision and decision["status"] == "VOIDED")
    citable = entry["redaction_level"] != "FULL" and not superseded
    issued_at = _dt(decision.get("issued_at")) if decision else None
    weight = (calc.precedent_weight(count, issued_at, db.now())
              if issued_at is not None else calc.round_half_up(0, 2))
    view = db.public(entry)
    view["citation_count"] = count
    view["precedent_weight"] = float(weight)
    view["citable"] = citable
    view["superseded"] = superseded
    return view


def decision_is_citable(decision_id):
    decision = db.decisions.get(decision_id)
    if decision is None:
        return False
    entry = entry_for_decision(decision_id)
    if entry is None:
        return False
    if entry["redaction_level"] == "FULL":
        return False
    return decision["status"] != "VOIDED"


# ------------------------------------------------------------------- grounds
def case_grounds(case_id):
    return db.ordered(db.grounds, lambda r: r["case_id"] == case_id)


def grade_ground(evidence_count):
    return "SUFFICIENT" if evidence_count >= calc.MIN_EVIDENCE_PER_GROUND else "DEFICIENT"

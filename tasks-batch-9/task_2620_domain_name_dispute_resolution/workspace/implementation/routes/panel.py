"""Constituting the panel: nomination, conflict screening, waiver, replacement."""

from flask import Blueprint, request

import db
import response
import validate as v
from errors import ApiError
from middleware import auth, body
from services import calc, logic

bp = Blueprint("panel", __name__)

SEATS = ("SOLE", "PRESIDING", "CO_PANELIST_1", "CO_PANELIST_2")
APPOINTMENT_STATUSES = ("NOMINATED", "WAIVER_PENDING", "ACCEPTED", "CONFLICTED",
                        "DECLINED", "REPLACED", "DISCHARGED")
NOMINATION_STATUSES = ("RESPONSE_RECEIVED", "DEFAULT", "PANEL_APPOINTMENT")


def _new_seat_row(case_id, seat, nominated_by, panelist_id, selected_by_provider):
    return db.base_row(
        case_id=case_id,
        panelist_id=panelist_id,
        seat=seat,
        nominated_by=nominated_by,
        selected_by_provider=selected_by_provider,
        disclosed_prior_representation=False,
        disclosed_same_firm=False,
        disclosed_financial_interest=False,
        prior_appointments_with_complainant=0,
        months_since_last_contact=None,
        conflict_score=None,
        conflict_factors=[],
        waiver_complainant=False,
        waiver_respondent=False,
        status="NOMINATED",
        screened_at=None,
        accepted_at=None,
        decision_due_at=None,
        honoraria_cents=0,
        replaced_by_appointment_id=None,
    )


def _pick_panelist(case, named_id, appointment_id=None):
    """Returns (panelist, selected_by_provider)."""
    if named_id is not None:
        panelist = db.panelists[named_id]
        logic.check_named_candidate(panelist, case, appointment_id)
        return panelist, False
    return logic.select_panelist(case, appointment_id), True


# ---------------------------------------------------------------- nomination
@bp.post("/udrp/cases/<case_id>/appointments")
def nominate(case_id):
    auth("CaseManager")
    case = logic.case_or_404(case_id)
    payload = body()
    named_id = None
    if v.present(payload, "panelist_id"):
        named_id = logic.resource_or_404(db.panelists, payload["panelist_id"])["id"]
    seat = v.req_enum(payload, "seat", SEATS)
    nominated_by = v.req_enum(payload, "nominated_by",
                              ("COMPLAINANT", "RESPONDENT", "PROVIDER"))
    expected_version = v.req_int(payload, "expected_case_version", 0)
    if case["status"] not in NOMINATION_STATUSES:
        raise ApiError("ERR_INVALID_CASE_STATE")
    if expected_version != case["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION")
    if seat not in logic.SEATS_FOR_COUNT[case["required_seat_count"]]:
        raise ApiError("ERR_SEAT_NOT_APPLICABLE")
    for row in logic.case_appointments(case_id):
        if row["seat"] == seat and row["status"] in logic.LIVE_SEAT_STATUSES:
            raise ApiError("ERR_SEAT_ALREADY_FILLED")
    if named_id is not None:
        logic.check_named_candidate(db.panelists[named_id], case)
    if case["paid_cents"] < case["assessed_fee_cents"]:
        raise ApiError("ERR_PANEL_SUPPLEMENT_UNPAID")
    panelist, by_provider = _pick_panelist(case, named_id)

    row = _new_seat_row(case_id, seat, nominated_by, panelist["id"], by_provider)
    db.appointments[row["id"]] = row
    if case["status"] in ("RESPONSE_RECEIVED", "DEFAULT"):
        case["status"] = "PANEL_APPOINTMENT"
    db.touch(case)
    return response.ok(db.public(row), 201)


@bp.get("/udrp/appointments")
def list_appointments():
    auth("ProviderAdmin", "CaseManager", "Panelist")
    limit, offset = v.pagination(request.args)
    case_id = request.args.get("case_id")
    panelist_id = request.args.get("panelist_id")
    status = v.query_enum(request.args, "status", APPOINTMENT_STATUSES)
    seat = v.query_enum(request.args, "seat", SEATS)
    rows = db.ordered(db.appointments)
    if case_id:
        rows = [r for r in rows if r["case_id"] == case_id]
    if panelist_id:
        rows = [r for r in rows if r["panelist_id"] == panelist_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if seat:
        rows = [r for r in rows if r["seat"] == seat]
    window, total = response.paginate(rows, limit, offset)
    return response.ok_list([db.public(r) for r in window], limit, offset, total)


@bp.get("/udrp/appointments/<appointment_id>")
def read_appointment(appointment_id):
    auth("ProviderAdmin", "CaseManager", "Panelist")
    return response.ok(db.public(logic.appointment_or_404(appointment_id)))


# --------------------------------------------------------- conflict screening
def _ensure_seat_holder(appointment, user_id):
    if appointment["panelist_id"] != user_id:
        raise ApiError("ERR_NOT_SEAT_HOLDER")


def _seat_the_neutral(appointment, case):
    """Temporal checks are re-run at the moment the seat is actually taken."""
    panelist = db.panelists[appointment["panelist_id"]]
    if logic.window_conflict(panelist, case["id"], appointment["id"]):
        raise ApiError("ERR_PANELIST_WINDOW_CONFLICT")
    if logic.capacity_exceeded(panelist):
        raise ApiError("ERR_PANELIST_CAPACITY_EXCEEDED")


@bp.post("/udrp/appointments/<appointment_id>/conflict-screening")
def screen_conflicts(appointment_id):
    user_id, _ = auth("Panelist")
    appointment = logic.appointment_or_404(appointment_id)
    _ensure_seat_holder(appointment, user_id)
    case = logic.case_or_404(appointment["case_id"])
    payload = body()
    prior_representation = v.req_bool(payload, "disclosed_prior_representation")
    same_firm = v.req_bool(payload, "disclosed_same_firm")
    financial_interest = v.req_bool(payload, "disclosed_financial_interest")
    prior_appointments = v.req_int(payload, "prior_appointments_with_complainant", 0, 50)
    months = v.opt_int(payload, "months_since_last_contact", 0, 600)
    if appointment["status"] != "NOMINATED":
        raise ApiError("ERR_INVALID_APPOINTMENT_STATE")

    score, factors = calc.conflict_score(prior_representation, same_firm,
                                         financial_interest, prior_appointments,
                                         months)
    band = calc.conflict_band(score)
    if band == "ACCEPTED":
        _seat_the_neutral(appointment, case)

    appointment["disclosed_prior_representation"] = prior_representation
    appointment["disclosed_same_firm"] = same_firm
    appointment["disclosed_financial_interest"] = financial_interest
    appointment["prior_appointments_with_complainant"] = prior_appointments
    appointment["months_since_last_contact"] = months
    appointment["conflict_score"] = float(score)
    appointment["conflict_factors"] = factors
    appointment["screened_at"] = db.now_str()
    appointment["status"] = band
    if band == "ACCEPTED":
        logic.accept_seat(appointment, case)
    db.touch(appointment)
    if band == "ACCEPTED":
        logic.try_constitute(case)
    return response.ok(db.public(appointment))


@bp.post("/udrp/appointments/<appointment_id>/waiver")
def record_waiver(appointment_id):
    auth("CaseManager")
    appointment = logic.appointment_or_404(appointment_id)
    case = logic.case_or_404(appointment["case_id"])
    payload = body()
    waiver_complainant = v.req_bool(payload, "waiver_complainant")
    waiver_respondent = v.opt_bool(payload, "waiver_respondent")
    # A waiver attempted on a disqualifying conflict is reported as such: the
    # seat's own score, not its status, is what makes the request unwaivable.
    # Screening always routes a score at or above 60 to CONFLICTED, so were the
    # state gate consulted first this refusal could never be observed.
    score = appointment["conflict_score"]
    if score is not None and score >= float(calc.CONFLICT_DISQUALIFY_THRESHOLD):
        raise ApiError("ERR_CONFLICT_NOT_WAIVABLE")
    if appointment["status"] != "WAIVER_PENDING":
        raise ApiError("ERR_INVALID_APPOINTMENT_STATE")
    _seat_the_neutral(appointment, case)
    # A defaulted respondent cannot be asked to waive anything.
    respondent_excused = bool(case["default_recorded"]) and \
        logic.case_response(case["id"]) is None
    if waiver_complainant is not True:
        raise ApiError("ERR_WAIVER_INCOMPLETE")
    if not respondent_excused and waiver_respondent is not True:
        raise ApiError("ERR_WAIVER_INCOMPLETE")

    appointment["waiver_complainant"] = waiver_complainant
    appointment["waiver_respondent"] = bool(waiver_respondent)
    appointment["status"] = "ACCEPTED"
    logic.accept_seat(appointment, case)
    db.touch(appointment)
    logic.try_constitute(case)
    return response.ok(db.public(appointment))


@bp.post("/udrp/appointments/<appointment_id>/replace")
def replace_seat(appointment_id):
    auth("CaseManager")
    predecessor = logic.appointment_or_404(appointment_id)
    case = logic.case_or_404(predecessor["case_id"])
    payload = body()
    named_id = None
    if v.present(payload, "replacement_panelist_id"):
        named_id = logic.resource_or_404(
            db.panelists, payload["replacement_panelist_id"])["id"]
    v.opt_str(payload, "reason", 1, 2000)
    if predecessor["status"] not in ("NOMINATED", "WAIVER_PENDING", "CONFLICTED",
                                     "ACCEPTED"):
        raise ApiError("ERR_INVALID_APPOINTMENT_STATE")
    panelist, by_provider = _pick_panelist(case, named_id, predecessor["id"])

    was_accepted = predecessor["status"] == "ACCEPTED"
    predecessor["status"] = "DECLINED" if predecessor["status"] in (
        "NOMINATED", "WAIVER_PENDING") else "REPLACED"
    if was_accepted:
        predecessor["honoraria_cents"] = 0
        held_by = db.panelists.get(predecessor["panelist_id"])
        if held_by is not None and held_by["active_case_load"] > 0:
            held_by["active_case_load"] -= 1
            db.touch(held_by)
        if case["status"] == "PANEL_CONSTITUTED":
            case["status"] = "PANEL_APPOINTMENT"
        for decision in db.ordered(db.decisions,
                                   lambda r: r["case_id"] == case["id"]):
            if decision["status"] == "DRAFT":
                decision["status"] = "VOIDED"
                decision["voided_at"] = db.now_str()
                db.touch(decision)

    successor = _new_seat_row(case["id"], predecessor["seat"], "PROVIDER",
                              panelist["id"], by_provider)
    db.appointments[successor["id"]] = successor
    predecessor["replaced_by_appointment_id"] = successor["id"]
    db.touch(predecessor)
    db.touch(case)
    return response.ok(db.public(predecessor))

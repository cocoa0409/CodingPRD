"""Transfer cases (PRD 3.2 - 3.8): opening, the EMTALA screening loop,
negotiation rounds, acceptance/refusal, transport lifecycle, arrival,
completion and cancellation compensation.

Every handler applies the validation ladder of PRD 2.8 in rung order:
schema (3) -> existence (4) -> entity-backed identity (5) -> OCC (6) ->
state (7) -> clinical/regulatory safety (8) -> selector (9) ->
cross-referential (10) -> temporal (11) -> payer clearance (12).
"""

from datetime import timedelta

from flask import Blueprint, g

from core import domain as D
from core import schema as S
from core.clock import floor_minutes_between
from core.envelope import object_response, list_response, paginate, filter_exact, pagination
from core.errors import fail
from core.store import db, new_row, bump, find_by

bp = Blueprint("cases", __name__)

_ONE_MINUTE = timedelta(minutes=1)

_ERR = "ERR_INVALID_REQUEST"


def _case_or_404(case_id):
    case = D.get_case(case_id)
    if case is None:
        fail("ERR_CASE_NOT_FOUND", "TransferCase id does not exist.", 404)
    return case


def _require_sending_physician(case):
    if g.user_id != case["sending_physician_id"]:
        fail("ERR_NOT_CASE_PHYSICIAN",
             "X-User-ID is not the case's sending physician.", 403)


def _require_receiving_physician(case):
    if g.user_id != case["receiving_physician_id"]:
        fail("ERR_NOT_CASE_PHYSICIAN",
             "X-User-ID is not the case's receiving physician.", 403)


# ---------------------------------------------------------------------------
# Open and read cases
# ---------------------------------------------------------------------------

@bp.post("/transfer-cases")
def create_case():
    b = S.body()
    patient_ref = S.need_str(b, "patient_ref")
    sending_facility_id = S.need_str(b, "sending_facility_id")
    sending_physician_id = S.need_str(b, "sending_physician_id")
    acuity_level = S.need_enum(b, "acuity_level", D.ACUITY_LEVELS)
    required_unit_type = S.need_enum(b, "required_unit_type", D.UNIT_TYPES)
    requires_isolation = S.opt_bool(b, "requires_isolation", False)
    required_capability = S.need_str(b, "required_capability")
    facility = D.get_facility(sending_facility_id)
    if facility is None:
        fail("ERR_FACILITY_NOT_FOUND", "Facility id does not exist.", 404)
    physician = D.get_physician(sending_physician_id)
    if physician is None:
        fail("ERR_PHYSICIAN_NOT_FOUND", "Physician id does not exist.", 404)
    if physician["facility_id"] != sending_facility_id:
        fail("ERR_PHYSICIAN_FACILITY_MISMATCH",
             "The sending physician's home facility is not the sending facility.", 422)
    row = new_row("transfer_cases", {
        "patient_ref": patient_ref,
        "sending_facility_id": sending_facility_id,
        "sending_physician_id": sending_physician_id,
        "receiving_facility_id": None,
        "receiving_physician_id": None,
        "acuity_level": acuity_level,
        "required_unit_type": required_unit_type,
        "requires_isolation": requires_isolation,
        "required_capability": required_capability,
        "status": "INTAKE",
        "emtala_obligation": "UNDETERMINED",
        "emtala_determined_at": None,
        "active_bed_hold_id": None,
        "negotiation_round": 0,
    })
    return object_response(D.serialize_case(row), 201)


@bp.get("/transfer-cases")
def list_cases():
    rows = db.ordered("transfer_cases")
    rows = filter_exact(rows, "status")
    rows = filter_exact(rows, "sending_facility_id")
    rows = filter_exact(rows, "receiving_facility_id")
    rows = filter_exact(rows, "sending_physician_id")
    rows = filter_exact(rows, "receiving_physician_id")
    return paginate(rows, D.serialize_case)


@bp.get("/transfer-cases/<id>")
def get_case(id):
    return object_response(D.serialize_case(_case_or_404(id)), 200)


# ---------------------------------------------------------------------------
# The EMTALA screening loop (PRD 3.2)
# ---------------------------------------------------------------------------

@bp.post("/transfer-cases/<id>/emtala-screening")
def create_screening(id):
    b = S.body()
    has_emc = S.need_bool(b, "has_emergency_medical_condition")
    is_stabilized = S.need_bool(b, "is_stabilized")
    benefits = S.opt_bool(b, "benefits_outweigh_risks", False)
    certification = S.opt_str(b, "physician_certification", "")
    case = _case_or_404(id)
    _require_sending_physician(case)
    if D.screening_of(id) is not None:
        fail("ERR_DUPLICATE_SCREENING", "The case already has an EmtalaScreening.", 409)
    row = new_row("emtala_screenings", {
        "transfer_case_id": id,
        "has_emergency_medical_condition": has_emc,
        "is_stabilized": is_stabilized,
        "benefits_outweigh_risks": benefits,
        "physician_certification": certification,
        "status": "DRAFT",
        "certified_at": None,
        "amendment_count": 0,
    })
    return object_response(D.serialize_screening(row), 201)


@bp.get("/transfer-cases/<id>/emtala-screening")
def get_screening(id):
    _case_or_404(id)
    screening = D.screening_of(id)
    rows = [screening] if screening is not None else []
    limit, offset = pagination()
    page = rows[offset:offset + limit]
    return list_response([D.serialize_screening(r) for r in page], limit, offset, len(rows))


@bp.post("/transfer-cases/<id>/emtala-screening/certify")
def certify_screening(id):
    case = _case_or_404(id)
    screening = D.screening_of(id)
    if screening is None:
        fail("ERR_SCREENING_NOT_FOUND", "No EmtalaScreening exists for the case.", 404)
    _require_sending_physician(case)
    if case["status"] != "INTAKE":
        fail("ERR_INVALID_STATE", "The case is not in INTAKE.", 409)
    if screening["status"] not in ("DRAFT", "AMENDED"):
        fail("ERR_INVALID_STATE", "The screening is not in DRAFT or AMENDED.", 409)
    determination = D.screening_determination(
        screening["has_emergency_medical_condition"], screening["is_stabilized"])
    if determination == "EMERGENCY_EXCEPTION":
        if (not screening["benefits_outweigh_risks"]
                or len(screening["physician_certification"]) < 30):
            fail("ERR_CERTIFICATION_INSUFFICIENT",
                 "EMERGENCY_EXCEPTION requires benefits_outweigh_risks true and a "
                 "physician_certification of at least 30 characters.", 422)
    screening["status"] = "CERTIFIED"
    screening["certified_at"] = db.now
    bump(screening)
    case["emtala_obligation"] = determination
    case["emtala_determined_at"] = db.now
    case["status"] = "EMTALA_DETERMINED"
    bump(case)
    return object_response(D.serialize_screening(screening), 200)


@bp.post("/transfer-cases/<id>/emtala-screening/amend")
def amend_screening(id):
    b = S.body()
    has_emc = S.opt_bool(b, "has_emergency_medical_condition", None)
    is_stabilized = S.opt_bool(b, "is_stabilized", None)
    benefits = S.opt_bool(b, "benefits_outweigh_risks", None)
    certification = S.opt_str(b, "physician_certification", None)
    case = _case_or_404(id)
    screening = D.screening_of(id)
    if screening is None:
        fail("ERR_SCREENING_NOT_FOUND", "No EmtalaScreening exists for the case.", 404)
    _require_sending_physician(case)
    if case["status"] == "EMTALA_DETERMINED":
        if screening["status"] != "CERTIFIED":
            fail("ERR_INVALID_STATE", "The screening is not CERTIFIED.", 409)
    elif case["status"] == "INTAKE":
        fail("ERR_INVALID_STATE", "The case is back in INTAKE.", 409)
    else:
        fail("ERR_SCREENING_LOCKED",
             "The case has advanced past EMTALA_DETERMINED; the screening is locked.", 409)
    if has_emc is not None:
        screening["has_emergency_medical_condition"] = has_emc
    if is_stabilized is not None:
        screening["is_stabilized"] = is_stabilized
    if benefits is not None:
        screening["benefits_outweigh_risks"] = benefits
    if certification is not None:
        screening["physician_certification"] = certification
    screening["status"] = "AMENDED"
    screening["amendment_count"] = screening["amendment_count"] + 1
    bump(screening)
    case["emtala_obligation"] = "UNDETERMINED"
    case["emtala_determined_at"] = None
    case["status"] = "INTAKE"
    bump(case)
    return object_response(D.serialize_screening(screening), 200)


# ---------------------------------------------------------------------------
# Negotiation: request-acceptance, re-request, accept, refuse (PRD 3.3, 3.4)
# ---------------------------------------------------------------------------

def _address_case(case, b, expected_from_state):
    """Shared rungs for request-acceptance and re-request."""
    receiving_facility_id = S.need_str(b, "receiving_facility_id")
    receiving_physician_id = S.need_str(b, "receiving_physician_id")
    contact_method = S.need_enum(b, "contact_method", D.CONTACT_METHODS)
    notes = S.opt_str(b, "notes", "")
    facility = D.get_facility(receiving_facility_id)
    if facility is None:
        fail("ERR_FACILITY_NOT_FOUND", "Facility id does not exist.", 404)
    physician = D.get_physician(receiving_physician_id)
    if physician is None:
        fail("ERR_PHYSICIAN_NOT_FOUND", "Physician id does not exist.", 404)
    if case["status"] != expected_from_state:
        fail("ERR_INVALID_STATE",
             "The case is not in %s." % expected_from_state, 409)
    if case["required_capability"] not in facility["capabilities"]:
        fail("ERR_CAPABILITY_MISMATCH",
             "The receiving facility does not list the required capability.", 422)
    if receiving_facility_id == case["sending_facility_id"]:
        fail("ERR_SAME_FACILITY_TRANSFER",
             "The receiving facility equals the sending facility.", 400)
    if physician["facility_id"] != receiving_facility_id:
        fail("ERR_PHYSICIAN_FACILITY_MISMATCH",
             "The receiving physician's home facility is not the receiving facility.", 422)
    new_row("communications", {
        "transfer_case_id": case["id"],
        "from_physician_id": case["sending_physician_id"],
        "to_physician_id": receiving_physician_id,
        "round": case["negotiation_round"] + 1,
        "contact_method": contact_method,
        "notes": notes,
        "outcome": "PENDING",
        "responded_at": None,
    }, versioned=False)
    case["receiving_facility_id"] = receiving_facility_id
    case["receiving_physician_id"] = receiving_physician_id
    case["negotiation_round"] = case["negotiation_round"] + 1
    case["status"] = "AWAITING_ACCEPTANCE"
    bump(case)
    return case


@bp.post("/transfer-cases/<id>/request-acceptance")
def request_acceptance(id):
    b = S.body()
    case = _case_or_404(id)
    _address_case(case, b, "EMTALA_DETERMINED")
    return object_response(D.serialize_case(case), 200)


@bp.post("/transfer-cases/<id>/re-request")
def re_request(id):
    b = S.body()
    case = _case_or_404(id)
    _address_case(case, b, "REFUSED")
    return object_response(D.serialize_case(case), 200)


@bp.post("/transfer-cases/<id>/accept")
def accept_case(id):
    case = _case_or_404(id)
    _require_receiving_physician(case)
    if case["status"] != "AWAITING_ACCEPTANCE":
        fail("ERR_INVALID_STATE", "The case is not AWAITING_ACCEPTANCE.", 409)
    # Safety gate: no ACTIVE diversion of the receiving facility covering the
    # required unit (ALL_UNITS, or SPECIFIC_UNIT matching required_unit_type).
    for event in find_by("diversion_events", facility_id=case["receiving_facility_id"]):
        if D.diversion_effective_status(event) != "ACTIVE":
            continue
        if event["scope"] == "ALL_UNITS" or (
                event["scope"] == "SPECIFIC_UNIT"
                and event["unit_type"] == case["required_unit_type"]):
            fail("ERR_FACILITY_ON_DIVERSION",
                 "The receiving facility is on diversion for the required unit.", 403)
    bed = D.select_bed(case)
    if bed is None:
        fail("ERR_NO_ELIGIBLE_BED", "The bed selector found no eligible bed.", 409)
    comm = D.current_round_communication(case)
    if comm is not None and comm["outcome"] == "PENDING":
        comm["outcome"] = "ACCEPTED"
        comm["responded_at"] = db.now
    bed["status"] = "HELD"
    bump(bed)
    hold = new_row("bed_holds", {
        "bed_id": bed["id"],
        "transfer_case_id": case["id"],
        "status": "ACTIVE",
        "hold_started_at": db.now,
        "hold_expires_at": db.now + D.HOLD_MINUTES[case["acuity_level"]] * _ONE_MINUTE,
        "release_reason": None,
    })
    case["active_bed_hold_id"] = hold["id"]
    case["status"] = "ACCEPTED"
    bump(case)
    D.evaluate_saturation(case["receiving_facility_id"])
    return object_response(D.serialize_case(case), 200)


@bp.post("/transfer-cases/<id>/refuse")
def refuse_case(id):
    b = S.body()
    refusal_category = S.need_enum(b, "refusal_category", D.REFUSAL_CATEGORIES)
    narrative = S.need_str(b, "narrative")
    S.need_min_length(narrative, "narrative", 50, "ERR_NARRATIVE_TOO_SHORT")
    case = _case_or_404(id)
    _require_receiving_physician(case)
    if case["status"] != "AWAITING_ACCEPTANCE":
        fail("ERR_INVALID_STATE", "The case is not AWAITING_ACCEPTANCE.", 409)
    comm = D.current_round_communication(case)
    if comm is not None and comm["outcome"] == "PENDING":
        comm["outcome"] = "REFUSED"
        comm["responded_at"] = db.now
    priors = D.refusal_count(case["id"])
    score, flag = D.refusal_risk(refusal_category, case["emtala_obligation"], priors)
    new_row("refusal_records", {
        "transfer_case_id": case["id"],
        "facility_id": case["receiving_facility_id"],
        "refusing_physician_id": case["receiving_physician_id"],
        "refusal_category": refusal_category,
        "narrative": narrative,
        "emtala_risk_score": score,
        "emtala_risk_flag": flag,
        "round": case["negotiation_round"],
    }, versioned=False)
    case["status"] = "REFUSED"
    bump(case)
    if case["emtala_obligation"] == "EMTALA_APPLIES" and not D.open_review_exists(case["id"]):
        _create_review(case["id"], "REFUSAL_RISK")
    return object_response(D.serialize_case(case), 200)


# ---------------------------------------------------------------------------
# Transport lifecycle (PRD 3.7) and arrival / completion / cancellation (3.8)
# ---------------------------------------------------------------------------

@bp.post("/transfer-cases/<id>/dispatch")
def dispatch_case(id):
    b = S.body()
    mode = S.need_enum(b, "mode", D.TRANSPORT_MODES)
    crew_capability = S.need_enum(b, "crew_capability", D.CREW_CAPABILITIES)
    distance_miles = S.need_number(b, "distance_miles")
    if not distance_miles > 0:
        fail(_ERR, "distance_miles must be greater than 0.", 400)
    case = _case_or_404(id)
    if case["status"] != "ACCEPTED":
        fail("ERR_INVALID_STATE", "The case is not ACCEPTED.", 409)
    required = D.CREW_REQUIRED[case["acuity_level"]]
    if D.CREW_ORDER[crew_capability] < D.CREW_ORDER[required]:
        fail("ERR_CREW_CAPABILITY_INSUFFICIENT",
             "crew_capability is below the acuity minimum.", 422)
    minimum = D.AIR_MINIMUM_MILES.get(mode)
    if minimum is not None and distance_miles < minimum:
        fail("ERR_AIR_DISTANCE_BELOW_MINIMUM",
             "%s requires distance_miles >= %d." % (mode, minimum), 422)
    packet = D.packet_of(id)
    if packet is None or D.overall_status(packet) != "READY":
        fail("ERR_PACKET_INCOMPLETE",
             "The case's clinical packet is not READY.", 409)
    hold = db.bed_holds.get(case["active_bed_hold_id"]) if case["active_bed_hold_id"] else None
    if hold is None or hold["status"] != "ACTIVE" or not hold["hold_expires_at"] > db.now:
        fail("ERR_BED_HOLD_EXPIRED",
             "The case has no active bed hold within its window.", 409)
    notification = D.live_notification_of(id)
    if notification is None or notification["status"] not in ("NOTIFIED", "EXCEPTION_CLAIMED"):
        fail("ERR_INSURANCE_NOT_CLEARED",
             "Dispatch requires a NOTIFIED or EXCEPTION_CLAIMED notification.", 402)
    optimistic, conservative = D.transport_estimates(
        mode, crew_capability, distance_miles, case["acuity_level"])
    row = new_row("transport_dispatches", {
        "transfer_case_id": id,
        "mode": mode,
        "crew_capability": crew_capability,
        "distance_miles": distance_miles,
        "estimated_minutes_optimistic": optimistic,
        "estimated_minutes_conservative": conservative,
        "actual_duration_minutes": None,
        "status": "DISPATCHED",
        "dispatched_at": db.now,
        "departed_at": None,
        "arrived_at": None,
    })
    case["status"] = "TRANSPORT_ARRANGED"
    bump(case)
    return object_response(D.serialize_dispatch(row), 201)


@bp.post("/transfer-cases/<id>/depart")
def depart_case(id):
    case = _case_or_404(id)
    if case["status"] != "TRANSPORT_ARRANGED":
        fail("ERR_INVALID_STATE", "The case is not TRANSPORT_ARRANGED.", 409)
    dispatch = D.latest_dispatch(id)
    if dispatch is None or dispatch["status"] != "DISPATCHED":
        fail("ERR_INVALID_STATE", "The latest dispatch is not DISPATCHED.", 409)
    dispatch["status"] = "EN_ROUTE"
    dispatch["departed_at"] = db.now
    bump(dispatch)
    case["status"] = "EN_ROUTE"
    bump(case)
    return object_response(D.serialize_case(case), 200)


@bp.post("/transfer-cases/<id>/arrive")
def arrive_case(id):
    b = S.body()
    arrival_condition = S.need_enum(b, "arrival_condition", D.ARRIVAL_CONDITIONS)
    deterioration = S.need_bool(b, "deterioration_en_route")
    confirmed = S.need_bool(b, "receiving_physician_confirmed")
    case = _case_or_404(id)
    if case["status"] != "EN_ROUTE":
        fail("ERR_INVALID_STATE", "The case is not EN_ROUTE.", 409)
    dispatch = D.latest_dispatch(id)
    if dispatch is None or dispatch["status"] != "EN_ROUTE":
        fail("ERR_INVALID_STATE", "The active dispatch is not EN_ROUTE.", 409)
    dispatch["status"] = "ARRIVED"
    dispatch["arrived_at"] = db.now
    dispatch["actual_duration_minutes"] = floor_minutes_between(
        dispatch["departed_at"], db.now)
    bump(dispatch)
    hold = db.bed_holds.get(case["active_bed_hold_id"]) if case["active_bed_hold_id"] else None
    if hold is not None and hold["status"] == "ACTIVE":
        hold["status"] = "CONFIRMED"
        hold["release_reason"] = "ARRIVAL_CONFIRMED"
        bump(hold)
        bed = D.get_bed(hold["bed_id"])
        if bed is not None and bed["status"] == "HELD":
            bed["status"] = "OCCUPIED"
            bump(bed)
        D.evaluate_saturation(D.hold_facility_id(hold))
    door_to_arrival = floor_minutes_between(case["emtala_determined_at"], db.now)
    new_row("transfer_outcomes", {
        "transfer_case_id": id,
        "arrival_condition": arrival_condition,
        "deterioration_en_route": deterioration,
        "receiving_physician_confirmed": confirmed,
        "door_to_arrival_minutes": door_to_arrival,
        "recorded_at": db.now,
    }, versioned=False)
    if deterioration and not D.open_review_exists(id):
        _create_review(id, "DETERIORATION")
    case["status"] = "ARRIVED"
    bump(case)
    return object_response(D.serialize_case(case), 200)


@bp.post("/transfer-cases/<id>/complete")
def complete_case(id):
    case = _case_or_404(id)
    if case["status"] != "ARRIVED":
        fail("ERR_INVALID_STATE", "The case is not ARRIVED.", 409)
    if not D.open_review_exists(id):
        _create_review(id, "ROUTINE")
    case["status"] = "COMPLETED"
    bump(case)
    return object_response(D.serialize_case(case), 200)


_CANCELLABLE = ("INTAKE", "EMTALA_DETERMINED", "AWAITING_ACCEPTANCE", "REFUSED",
                "ACCEPTED", "TRANSPORT_ARRANGED")


@bp.post("/transfer-cases/<id>/cancel")
def cancel_case(id):
    b = S.body()
    S.need_str(b, "cancel_reason")
    case = _case_or_404(id)
    if case["status"] not in _CANCELLABLE:
        fail("ERR_INVALID_STATE", "The case cannot be cancelled from %s." % case["status"], 409)
    hold = db.bed_holds.get(case["active_bed_hold_id"]) if case["active_bed_hold_id"] else None
    if hold is not None and hold["status"] == "ACTIVE":
        hold["status"] = "RELEASED"
        hold["release_reason"] = "CASE_CANCELLED"
        bump(hold)
        bed = D.get_bed(hold["bed_id"])
        if bed is not None and bed["status"] == "HELD":
            bed["status"] = "AVAILABLE"
            bump(bed)
        if case["active_bed_hold_id"] == hold["id"]:
            case["active_bed_hold_id"] = None
        D.evaluate_saturation(D.hold_facility_id(hold))
    for notification in find_by("insurance_notifications", transfer_case_id=id):
        if notification["status"] in ("PENDING", "NOTIFIED", "EXCEPTION_CLAIMED"):
            notification["status"] = "VOIDED"
            bump(notification)
    for dispatch in find_by("transport_dispatches", transfer_case_id=id):
        if dispatch["status"] == "DISPATCHED":
            dispatch["status"] = "CANCELLED"
            bump(dispatch)
    for comm in find_by("communications", transfer_case_id=id):
        if comm["outcome"] == "PENDING":
            comm["outcome"] = "VOIDED"
    case["status"] = "CANCELLED"
    bump(case)
    return object_response(D.serialize_case(case), 200)


@bp.get("/transfer-cases/<id>/outcome")
def get_outcome(id):
    _case_or_404(id)
    outcome = D.outcome_of(id)
    rows = [outcome] if outcome is not None else []
    limit, offset = pagination()
    page = rows[offset:offset + limit]
    return list_response([D.serialize_outcome(r) for r in page], limit, offset, len(rows))


def _create_review(case_id, trigger):
    return new_row("quality_reviews", {
        "transfer_case_id": case_id,
        "trigger": trigger,
        "status": "OPEN",
        "reviewer_physician_id": None,
        "timeliness_score": None,
        "documentation_score": None,
        "protocol_score": None,
        "composite_score": None,
        "outcome": None,
        "findings": None,
    })

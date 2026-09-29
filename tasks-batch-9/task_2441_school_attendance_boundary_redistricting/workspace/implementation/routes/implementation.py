"""Adoption records, phase-in rules, activation/rescission, transfer requests
and post-implementation variance monitoring."""

from flask import Blueprint, request

import calc
import services
from core import (
    DECISIONS,
    READ_ROLES_INTERNAL,
    READ_ROLES_PUBLIC,
    RULE_TYPES,
    TRANSFER_REASONS,
    active_schools_of_study,
    areas_of_study,
    as_enum,
    as_int,
    as_pct,
    as_str,
    assignments_of_scenario,
    authenticate,
    body_json,
    comments_of_scenario,
    db,
    dec,
    fail,
    get_adoption,
    get_area,
    get_school,
    get_scenario,
    get_study,
    get_transfer,
    get_observation,
    iso3,
    live_assignment_for_area,
    need,
    new_record,
    now,
    observations_of_adoption,
    ordered,
    paginate,
    parse_dt,
    present,
    pub,
    recompute_school_enrollment,
    recompute_study_values,
    respond,
    round_half_up,
    rules_of_adoption,
    scenarios_of_study,
    schools_of_study,
    touch,
    transfers_of_adoption,
)

bp = Blueprint("implementation", __name__)


def pre_resolve(getter, value):
    if isinstance(value, str) and value:
        return getter(value)
    return None


# ==========================================================================
# Adoption records
# ==========================================================================
@bp.post("/adoptions")
def create_adoption():
    user_id, _role = authenticate(["BoardMember"])
    body = body_json()
    raw_scenario_id = body.get("scenario_id")
    if isinstance(raw_scenario_id, str):
        probe = db.scenarios.get(raw_scenario_id)
        if probe is not None and probe["author_user_id"] == user_id:
            fail("ERR_SELF_ADOPTION_FORBIDDEN")

    pre_resolve(get_study, body.get("study_id"))
    pre_resolve(get_scenario, raw_scenario_id)

    study = get_study(as_str(need(body, "study_id"), "study_id"))
    scenario = get_scenario(as_str(need(body, "scenario_id"), "scenario_id"))
    effective_dt = parse_dt(need(body, "effective_date"))
    effective_school_year = as_int(need(body, "effective_school_year"), "effective_school_year")
    regime_years = 3
    if present(body, "regime_years"):
        regime_years = as_int(body["regime_years"], "regime_years", minimum=1)
    deadline_dt = parse_dt(need(body, "transfer_deadline_date"))
    transfer_cap_pct = round_half_up(dec("95.0"), 2)
    if present(body, "transfer_cap_pct"):
        transfer_cap_pct = round_half_up(as_pct(body["transfer_cap_pct"], "transfer_cap_pct"), 2)
    variance_tolerance_pct = round_half_up(dec("3.0"), 2)
    if present(body, "variance_tolerance_pct"):
        variance_tolerance_pct = round_half_up(as_pct(body["variance_tolerance_pct"], "variance_tolerance_pct"), 2)
    votes_for = as_int(need(body, "votes_for"), "votes_for", minimum=0)
    votes_against = as_int(need(body, "votes_against"), "votes_against", minimum=0)
    votes_abstain = 0
    if present(body, "votes_abstain"):
        votes_abstain = as_int(body["votes_abstain"], "votes_abstain", minimum=0)
    board_member_count = as_int(need(body, "board_member_count"), "board_member_count", minimum=1)

    if study["status"] != "BOARD_DECISION":
        fail("ERR_STUDY_PHASE_INVALID")
    if scenario["status"] != "BOARD_READY":
        fail("ERR_SCENARIO_NOT_BOARD_READY")
    if deadline_dt <= effective_dt or effective_school_year < study["target_school_year"]:
        fail("ERR_INVALID_DATE_WINDOW")
    if scenario["study_id"] != study["id"]:
        fail("ERR_CROSS_STUDY_REFERENCE")

    for existing in ordered(list(db.adoptions.values())):
        if existing["implementation_status"] == "RESCINDED":
            continue
        other_study = db.studies.get(existing["study_id"])
        if other_study is None or other_study["district_name"] != study["district_name"]:
            continue
        if calc.regime_conflicts(
            effective_school_year, regime_years,
            existing["effective_school_year"], existing["regime_years"],
        ):
            fail("ERR_REGIME_WINDOW_CONFLICT")

    if not calc.quorum_met(votes_for, votes_against, votes_abstain, board_member_count):
        fail("ERR_QUORUM_NOT_MET")
    needs_supermajority = calc.supermajority_required(scenario["students_reassigned_pct"])
    if not calc.majority_met(votes_for, votes_against, needs_supermajority):
        fail("ERR_MAJORITY_NOT_MET")

    adoption = new_record()
    adoption.update({
        "study_id": study["id"],
        "scenario_id": scenario["id"],
        "effective_date": iso3(effective_dt),
        "effective_school_year": effective_school_year,
        "regime_years": regime_years,
        "transfer_deadline_date": iso3(deadline_dt),
        "transfer_cap_pct": float(transfer_cap_pct),
        "variance_tolerance_pct": float(variance_tolerance_pct),
        "votes_for": votes_for,
        "votes_against": votes_against,
        "votes_abstain": votes_abstain,
        "board_member_count": board_member_count,
        "adopted_by_user_id": user_id,
        "supermajority_required": needs_supermajority,
        "implementation_status": "PENDING_EFFECTIVE",
        "transfer_window_status": "TRANSFER_WINDOW_OPEN",
        "_effective_dt": effective_dt,
        "_deadline_dt": deadline_dt,
    })
    db.adoptions[adoption["id"]] = adoption

    # Link one - the adopted scenario.
    scenario["status"] = "ADOPTED"
    touch(scenario)

    # Link two - the field is rejected, in scenario creation order.
    rejected_ids = []
    for sibling in scenarios_of_study(study["id"]):
        if sibling["id"] == scenario["id"]:
            continue
        if sibling["status"] in ("DRAFT", "UNDER_REVIEW", "REVISION", "BOARD_READY"):
            sibling["status"] = "REJECTED"
            sibling["rejection_reason"] = "SUPERSEDED_BY_ADOPTION"
            touch(sibling)
            rejected_ids.append(sibling["id"])

    # Link three - the public record on the losers, in comment creation order.
    for sibling_id in rejected_ids:
        for comment in comments_of_scenario(sibling_id):
            if comment["status"] in ("SUBMITTED", "TRIAGED"):
                comment["status"] = "DISMISSED"
                comment["dismissal_reason"] = "SCENARIO_REJECTED"
                touch(comment)

    study["status"] = "IMPLEMENTATION"
    recompute_study_values(study)
    touch(study)
    return respond(pub(adoption), 201)


@bp.get("/adoptions")
def list_adoptions():
    authenticate(READ_ROLES_PUBLIC)
    rows = ordered(list(db.adoptions.values()))
    for key in ("study_id", "scenario_id"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return paginate(rows, pub)


@bp.get("/adoptions/<adoption_id>")
def read_adoption(adoption_id):
    authenticate(READ_ROLES_PUBLIC)
    return respond(pub(get_adoption(adoption_id)))


# ==========================================================================
# Phase-in rules
# ==========================================================================
@bp.post("/adoptions/<adoption_id>/phase-in-rules")
def create_phase_in_rule(adoption_id):
    authenticate(["BoardMember"])
    adoption = get_adoption(adoption_id)
    body = body_json()
    rule_type = as_enum(need(body, "rule_type"), "rule_type", RULE_TYPES)
    grade_low = as_int(need(body, "grade_low"), "grade_low", minimum=0, maximum=12)
    grade_high = as_int(need(body, "grade_high"), "grade_high", minimum=0, maximum=12)
    if grade_low > grade_high:
        fail("ERR_INVALID_REQUEST", "grade_low may not exceed grade_high.")
    sunset = as_int(need(body, "sunset_school_year"), "sunset_school_year")

    if adoption["implementation_status"] != "PENDING_EFFECTIVE":
        fail("ERR_ADOPTION_STATE_INVALID")
    if sunset < adoption["effective_school_year"]:
        fail("ERR_INVALID_DATE_WINDOW")
    for existing in rules_of_adoption(adoption["id"]):
        if existing["rule_type"] != rule_type:
            continue
        if existing["grade_low"] <= grade_high and grade_low <= existing["grade_high"]:
            fail("ERR_PHASE_IN_BAND_OVERLAP")

    rule = new_record(mutable=False)
    rule.update({
        "adoption_id": adoption["id"],
        "rule_type": rule_type,
        "grade_low": grade_low,
        "grade_high": grade_high,
        "sunset_school_year": sunset,
        "consumes_seat_pool": rule_type == "SIBLING_LINK",
    })
    db.rules[rule["id"]] = rule
    return respond(pub(rule), 201)


@bp.get("/adoptions/<adoption_id>/phase-in-rules")
def list_phase_in_rules(adoption_id):
    authenticate(READ_ROLES_PUBLIC)
    adoption = get_adoption(adoption_id)
    rows = rules_of_adoption(adoption["id"])
    rule_type = request.args.get("rule_type")
    if rule_type:
        rows = [r for r in rows if r["rule_type"] == rule_type]
    return paginate(rows, pub)


# ==========================================================================
# Activation, rescission, window close, monitoring close
# ==========================================================================
@bp.post("/adoptions/<adoption_id>/activate")
def activate_adoption(adoption_id):
    authenticate(["TransferOfficer"])
    adoption = get_adoption(adoption_id)
    scenario = db.scenarios[adoption["scenario_id"]]
    study = db.studies[adoption["study_id"]]

    if adoption["implementation_status"] != "PENDING_EFFECTIVE":
        fail("ERR_ADOPTION_STATE_INVALID")
    if scenario["status"] != "ADOPTED":
        fail("ERR_ADOPTION_STATE_INVALID")
    if now() < adoption["_effective_dt"]:
        fail("ERR_EFFECTIVE_DATE_NOT_REACHED")

    # Link one.
    adoption["implementation_status"] = "IN_EFFECT"
    touch(adoption)

    # Link two - re-point the map of record, in PlanningArea.created_at order.
    for area in areas_of_study(study["id"]):
        assignment = live_assignment_for_area(scenario["id"], area["id"])
        if assignment is None:
            continue
        area["previous_school_id"] = area["current_school_id"]
        area["current_school_id"] = assignment["assigned_school_id"]
        touch(area)

    # Link three - recompute head counts, in School.created_at order.
    for school in schools_of_study(study["id"]):
        recompute_school_enrollment(school)
    if recompute_study_values(study):
        touch(study)

    # Link four - revisit the waitlist, in TransferRequest.created_at order.
    for candidate in transfers_of_adoption(adoption["id"]):
        if candidate["status"] != "WAITLISTED":
            continue
        school = db.schools.get(candidate["requested_school_id"])
        if school is None:
            continue
        if services.school_seat_pool(adoption, school, exclude_transfer_id=candidate["id"]) >= 1:
            candidate["status"] = "APPROVED"
            candidate["promotion_source"] = "WAITLIST_AUTO"
            candidate["decided_by_user_id"] = None
            touch(candidate)
    return respond(pub(adoption))


@bp.post("/adoptions/<adoption_id>/rescind")
def rescind_adoption(adoption_id):
    user_id, _role = authenticate(["BoardMember"])
    probe = db.adoptions.get(adoption_id)
    if probe is not None:
        scenario_probe = db.scenarios.get(probe["scenario_id"])
        if scenario_probe is not None and scenario_probe["author_user_id"] == user_id:
            fail("ERR_SELF_ADOPTION_FORBIDDEN")
    adoption = get_adoption(adoption_id)
    body = body_json()
    as_str(need(body, "rescind_reason"), "rescind_reason")
    study = db.studies[adoption["study_id"]]

    if adoption["implementation_status"] != "IN_EFFECT":
        fail("ERR_ADOPTION_STATE_INVALID")

    adoption["implementation_status"] = "RESCINDED"
    touch(adoption)

    for area in areas_of_study(study["id"]):
        if area["previous_school_id"] is None:
            continue
        area["current_school_id"] = area["previous_school_id"]
        area["previous_school_id"] = None
        touch(area)

    for school in schools_of_study(study["id"]):
        recompute_school_enrollment(school)

    for candidate in transfers_of_adoption(adoption["id"]):
        if candidate["status"] == "APPROVED" and candidate["promotion_source"] == "WAITLIST_AUTO":
            candidate["status"] = "WAITLISTED"
            candidate["promotion_source"] = None
            touch(candidate)

    study["status"] = "BOARD_DECISION"
    recompute_study_values(study)
    touch(study)
    return respond(pub(adoption))


@bp.post("/adoptions/<adoption_id>/close-transfer-window")
def close_transfer_window(adoption_id):
    authenticate(["TransferOfficer"])
    adoption = get_adoption(adoption_id)
    if adoption["transfer_window_status"] == "TRANSFER_WINDOW_CLOSED":
        fail("ERR_ADOPTION_STATE_INVALID")
    if not now() > adoption["_deadline_dt"]:
        fail("ERR_ADOPTION_STATE_INVALID")

    adoption["transfer_window_status"] = "TRANSFER_WINDOW_CLOSED"
    touch(adoption)
    for candidate in transfers_of_adoption(adoption["id"]):
        if candidate["status"] in ("SUBMITTED", "WAITLISTED"):
            candidate["status"] = "DENIED"
            candidate["decision_notes"] = "WINDOW_CLOSED"
            candidate["decided_by_user_id"] = None
            touch(candidate)
    return respond(pub(adoption))


@bp.post("/adoptions/<adoption_id>/close-monitoring")
def close_monitoring(adoption_id):
    authenticate(["TransferOfficer"])
    adoption = get_adoption(adoption_id)
    body = body_json()
    if present(body, "closure_notes"):
        as_str(body["closure_notes"], "closure_notes", min_len=0)
    study = db.studies[adoption["study_id"]]

    if adoption["implementation_status"] != "IN_EFFECT":
        fail("ERR_ADOPTION_STATE_INVALID")
    if adoption["transfer_window_status"] != "TRANSFER_WINDOW_CLOSED":
        fail("ERR_ADOPTION_STATE_INVALID")

    observations = observations_of_adoption(adoption["id"])
    latest = {}
    for observation in observations:  # creation order, so the last write wins
        latest[observation["school_id"]] = observation
    for school in active_schools_of_study(study["id"]):
        if school["id"] not in latest:
            fail("ERR_ADOPTION_STATE_INVALID")
    for observation in latest.values():
        if observation["flag"] == "CORRECTIVE_ACTION_REQUIRED":
            fail("ERR_ADOPTION_STATE_INVALID")

    adoption["implementation_status"] = "MONITORING_CLOSED"
    touch(adoption)
    study["status"] = "CLOSED"
    recompute_study_values(study)
    touch(study)
    return respond(pub(adoption))


# ==========================================================================
# Transfer requests
# ==========================================================================
@bp.post("/transfer-requests")
def create_transfer_request():
    user_id, _role = authenticate(["Guardian"])
    body = body_json()
    pre_resolve(get_adoption, body.get("adoption_id"))
    pre_resolve(get_area, body.get("area_id"))
    pre_resolve(get_school, body.get("requested_school_id"))
    pre_resolve(get_transfer, body.get("sibling_transfer_id"))

    adoption = get_adoption(as_str(need(body, "adoption_id"), "adoption_id"))
    area = get_area(as_str(need(body, "area_id"), "area_id"))
    school = get_school(as_str(need(body, "requested_school_id"), "requested_school_id"))
    student_reference = as_str(need(body, "student_reference"), "student_reference")
    student_grade = as_int(need(body, "student_grade"), "student_grade", minimum=0, maximum=12)
    reason = as_enum(need(body, "reason"), "reason", TRANSFER_REASONS)
    sibling_id = None
    if present(body, "sibling_transfer_id"):
        sibling_id = get_transfer(as_str(body["sibling_transfer_id"], "sibling_transfer_id"))["id"]

    if school["status"] != "ACTIVE":
        fail("ERR_SCHOOL_NOT_ACTIVE")
    if adoption["transfer_window_status"] == "TRANSFER_WINDOW_CLOSED":
        fail("ERR_TRANSFER_WINDOW_CLOSED")
    if now() > adoption["_deadline_dt"]:
        fail("ERR_TRANSFER_WINDOW_EXPIRED")

    if reason == "SIBLING":
        if sibling_id is None:
            fail("ERR_SIBLING_LINK_INVALID")
        sibling = db.transfers[sibling_id]
        if (
            sibling["adoption_id"] != adoption["id"]
            or sibling["status"] != "APPROVED"
            or sibling["requested_school_id"] != school["id"]
        ):
            fail("ERR_SIBLING_LINK_INVALID")

    for existing in transfers_of_adoption(adoption["id"]):
        if existing["student_reference"] == student_reference:
            fail("ERR_DUPLICATE_NAME")

    scenario = db.scenarios[adoption["scenario_id"]]
    origin = live_assignment_for_area(scenario["id"], area["id"])
    request_record = new_record()
    request_record.update({
        "adoption_id": adoption["id"],
        "area_id": area["id"],
        "origin_school_id": origin["assigned_school_id"] if origin is not None else None,
        "requested_school_id": school["id"],
        "sibling_transfer_id": sibling_id,
        "guardian_user_id": user_id,
        "student_reference": student_reference,
        "student_grade": student_grade,
        "reason": reason,
        "status": "SUBMITTED",
        "resolved_reason": "NONE",
        "consumes_seat_pool": False,
        "promotion_source": None,
        "decided_by_user_id": None,
        "decision_notes": None,
    })
    resolved, consumes = services.resolve_request_eligibility(request_record, adoption)
    request_record["resolved_reason"] = resolved
    request_record["consumes_seat_pool"] = consumes
    db.transfers[request_record["id"]] = request_record
    return respond(pub(request_record), 201)


@bp.get("/transfer-requests")
def list_transfer_requests():
    authenticate(READ_ROLES_PUBLIC)
    rows = ordered(list(db.transfers.values()))
    keys = (
        "adoption_id", "area_id", "origin_school_id", "requested_school_id",
        "sibling_transfer_id", "status", "resolved_reason",
    )
    for key in keys:
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return paginate(rows, pub)


@bp.get("/transfer-requests/<transfer_id>")
def read_transfer_request(transfer_id):
    authenticate(READ_ROLES_PUBLIC)
    return respond(pub(get_transfer(transfer_id)))


@bp.post("/transfer-requests/<transfer_id>/decide")
def decide_transfer_request(transfer_id):
    user_id, _role = authenticate(["TransferOfficer"])
    probe = db.transfers.get(transfer_id)
    if probe is not None and probe["guardian_user_id"] == user_id:
        fail("ERR_SELF_DECISION_FORBIDDEN")
    transfer = get_transfer(transfer_id)
    body = body_json()
    decision = as_enum(need(body, "decision"), "decision", DECISIONS)
    notes = None
    if present(body, "decision_notes"):
        notes = as_str(body["decision_notes"], "decision_notes", min_len=0)

    adoption = db.adoptions[transfer["adoption_id"]]
    if adoption["transfer_window_status"] != "TRANSFER_WINDOW_OPEN":
        fail("ERR_ADOPTION_STATE_INVALID")
    if transfer["status"] not in ("SUBMITTED", "WAITLISTED"):
        fail("ERR_TRANSFER_NOT_DECIDABLE")
    if decision == "WAITLIST" and transfer["status"] != "SUBMITTED":
        fail("ERR_TRANSFER_NOT_DECIDABLE")

    resolved, consumes = services.resolve_request_eligibility(transfer, adoption)
    if decision in ("APPROVE", "WAITLIST") and resolved == "NONE":
        fail("ERR_NO_ELIGIBILITY_BASIS")
    school = db.schools.get(transfer["requested_school_id"])
    if decision == "APPROVE" and consumes:
        pool = services.school_seat_pool(adoption, school, exclude_transfer_id=transfer["id"])
        if pool < 1:
            fail("ERR_NO_TRANSFER_SEATS")

    transfer["resolved_reason"] = resolved
    transfer["consumes_seat_pool"] = consumes
    if decision == "APPROVE":
        transfer["status"] = "APPROVED"
        transfer["promotion_source"] = "OFFICER_DECISION"
    elif decision == "DENY":
        transfer["status"] = "DENIED"
    else:
        transfer["status"] = "WAITLISTED"
    transfer["decided_by_user_id"] = user_id
    if notes is not None:
        transfer["decision_notes"] = notes
    touch(transfer)
    return respond(pub(transfer))


# ==========================================================================
# Variance observations
# ==========================================================================
@bp.post("/adoptions/<adoption_id>/variance-observations")
def create_observation(adoption_id):
    authenticate(["TransferOfficer"])
    adoption = get_adoption(adoption_id)
    body = body_json()
    pre_resolve(get_school, body.get("school_id"))

    school = get_school(as_str(need(body, "school_id"), "school_id"))
    observed_on = parse_dt(need(body, "observed_on"))
    observed = as_int(need(body, "observed_enrollment"), "observed_enrollment", minimum=0)
    projected = as_int(need(body, "projected_enrollment"), "projected_enrollment", minimum=0)

    if adoption["implementation_status"] != "IN_EFFECT":
        fail("ERR_ADOPTION_STATE_INVALID")
    if school["study_id"] != adoption["study_id"]:
        fail("ERR_CROSS_STUDY_REFERENCE")
    if projected == 0:
        fail("ERR_ZERO_PROJECTION_BASE")

    var_pct = calc.variance_pct(observed, projected)
    observation = new_record(mutable=False)
    observation.update({
        "adoption_id": adoption["id"],
        "school_id": school["id"],
        "observed_on": iso3(observed_on),
        "observed_enrollment": observed,
        "projected_enrollment": projected,
        "variance_pct": float(var_pct),
        "flag": calc.variance_flag(var_pct, adoption["variance_tolerance_pct"]),
    })
    db.observations[observation["id"]] = observation
    return respond(pub(observation), 201)


@bp.get("/variance-observations")
def list_observations():
    authenticate(READ_ROLES_INTERNAL)
    rows = ordered(list(db.observations.values()))
    for key in ("adoption_id", "school_id", "flag"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return paginate(rows, pub)


@bp.get("/variance-observations/<observation_id>")
def read_observation(observation_id):
    authenticate(READ_ROLES_INTERNAL)
    return respond(pub(get_observation(observation_id)))

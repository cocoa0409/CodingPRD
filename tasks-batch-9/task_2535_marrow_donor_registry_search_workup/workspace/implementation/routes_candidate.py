"""Match candidates, confirmatory typing, screening and workup opening
(PRD 3.4, 3.5, 3.6)."""

from datetime import timedelta

from flask import Blueprint

import calc
import cascades
import claims
import serializers
import validate as v
from auth import (ROLE_COORDINATOR, ROLE_DIRECTOR, ROLE_LIAISON, ROLE_OPS,
                  authenticate)
from envelope import read_pagination, success
from errors import ApiError
from guards import arg, find, render_list
from store import db, new_row, ordered, touch

bp = Blueprint("registry_candidates", __name__)

CLEARANCE_ITEM_ORDER = ("PHYSICAL_EXAM", "IDM_PANEL", "CONSENT")
OUTCOMES = ("PASS", "DEFER", "FAIL")
DEFERRAL_TYPES = ("NONE", "TEMPORARY", "PERMANENT")


def _candidate_sort(row):
    return (row["rank_position"], row["created_at"], row["_seq"])


@bp.get("/registry/match-candidates")
def list_candidates():
    authenticate(ROLE_COORDINATOR, ROLE_DIRECTOR, ROLE_OPS, ROLE_LIAISON)
    limit, offset = read_pagination()
    search_id = arg("search_request_id")
    donor_id = arg("donor_id")
    role = arg("candidate_role")
    status = arg("status")
    rows = []
    for row in db.candidates.values():
        if search_id is not None and row["search_request_id"] != search_id:
            continue
        if donor_id is not None and row["donor_id"] != donor_id:
            continue
        if role is not None and row["candidate_role"] != role:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return render_list(rows, serializers.candidate_dict, limit, offset,
                       _candidate_sort)


@bp.get("/registry/match-candidates/<cid>")
def get_candidate(cid):
    authenticate(ROLE_COORDINATOR, ROLE_DIRECTOR, ROLE_OPS, ROLE_LIAISON)
    row = find(db.candidates, cid, "ERR_MATCH_CANDIDATE_NOT_FOUND")
    return success(serializers.candidate_dict(row))


@bp.get("/registry/match-candidates/<cid>/typing-requests")
def list_typing_requests(cid):
    authenticate(ROLE_COORDINATOR, ROLE_DIRECTOR, ROLE_OPS, ROLE_LIAISON)
    limit, offset = read_pagination()
    find(db.candidates, cid, "ERR_MATCH_CANDIDATE_NOT_FOUND")
    status = arg("status")
    rows = []
    for row in db.typing_requests.values():
        if row["match_candidate_id"] != cid:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return render_list(rows, serializers.typing_request_dict, limit, offset)


@bp.get("/registry/match-candidates/<cid>/workup-cases")
def list_candidate_cases(cid):
    authenticate(ROLE_COORDINATOR, ROLE_DIRECTOR, ROLE_OPS)
    limit, offset = read_pagination()
    find(db.candidates, cid, "ERR_MATCH_CANDIDATE_NOT_FOUND")
    case_status = arg("case_status")
    rows = []
    for row in db.workup_cases.values():
        if row["match_candidate_id"] != cid:
            continue
        if case_status is not None and row["case_status"] != case_status:
            continue
        rows.append(row)
    return render_list(rows, serializers.workup_dict, limit, offset)


# ------------------------------------------------- confirmatory typing ----
@bp.post("/registry/match-candidates/<cid>/typing-requests")
def create_typing_request(cid):
    actor = authenticate(ROLE_COORDINATOR)
    body = v.read_body()
    priority = v.opt_bool(body, "priority_flag", False)

    candidate = find(db.candidates, cid, "ERR_MATCH_CANDIDATE_NOT_FOUND")
    search = cascades.search_of_candidate(candidate)
    patient = cascades.patient_of_search(search) if search else None
    if actor.is_coordinator and patient is not None and \
            patient["coordinating_user_id"] != actor.user_id:
        raise ApiError("ERR_PATIENT_NOT_OWNED")

    if search is None or search["status"] in cascades.SEARCH_BLOCKED:
        raise ApiError("ERR_SEARCH_ALREADY_TERMINAL")
    if candidate["status"] not in ("IDENTIFIED", "TYPING_EXPIRED"):
        raise ApiError("ERR_INVALID_CANDIDATE_STATE")

    donor = cascades.donor_of_candidate(candidate)
    registry = cascades.registry_of_donor(donor) if donor else None
    if registry is None or registry["cooperation_status"] != "ACTIVE":
        raise ApiError("ERR_REGISTRY_NOT_COOPERATING")

    if candidate["ct_attempt_count"] >= calc.MAX_CT_ATTEMPTS:
        raise ApiError("ERR_CT_ATTEMPTS_EXHAUSTED")

    candidate["ct_attempt_count"] += 1
    candidate["status"] = "TYPING_REQUESTED"
    touch(candidate)

    requested_at = db.now()
    row = new_row(
        match_candidate_id=candidate["id"],
        attempt_number=candidate["ct_attempt_count"],
        priority_flag=priority,
        requested_at=requested_at,
        deadline_at=calc.ct_deadline(requested_at, registry, priority),
        status="REQUESTED",
        responded_at=None,
        reported_hla_typing=None,
        reported_match_grade=None,
        donor_available_flag=None,
        expired_by_sweep_at=None,
    )
    db.typing_requests[row["id"]] = row

    if candidate["candidate_role"] == "PRIMARY" and \
            search["status"] in ("SEARCHING", "BACKUP_REQUIRED"):
        search["status"] = "PRIMARY_ENGAGED"
        touch(search)

    return success(serializers.typing_request_dict(row), 201)


@bp.post("/registry/typing-requests/<tid>/response")
def respond_typing_request(tid):
    actor = authenticate(ROLE_LIAISON)
    body = v.read_body()
    typing = v.hla_typing_any_resolution(body, "reported_hla_typing")
    available = v.req_bool(body, "donor_available_flag")

    request_row = find(db.typing_requests, tid, "ERR_TYPING_REQUEST_NOT_FOUND")
    candidate = db.candidates.get(request_row["match_candidate_id"])
    donor = cascades.donor_of_candidate(candidate) if candidate else None
    if donor is None or donor["registry_id"] != actor.user_id:
        raise ApiError("ERR_REGISTRY_SCOPE_VIOLATION")

    if request_row["status"] != "REQUESTED":
        raise ApiError("ERR_TYPING_REQUEST_NOT_OPEN")

    for locus in v.LOCI:
        for allele in typing[locus]:
            if not v.is_allele_level(allele):
                raise ApiError("ERR_CT_TYPING_NOT_ALLELE_LEVEL")

    if db.now() > request_row["deadline_at"]:
        raise ApiError("ERR_CT_DEADLINE_PASSED")

    request_row["status"] = "RESPONDED"
    request_row["responded_at"] = db.now()
    request_row["reported_hla_typing"] = typing
    request_row["donor_available_flag"] = available
    touch(request_row)

    search = cascades.search_of_candidate(candidate)
    registry = cascades.registry_of_donor(donor)
    patient = cascades.patient_of_search(search) if search else None

    if not available:
        if donor["availability_status"] == "AVAILABLE":
            donor["availability_status"] = "WITHDRAWN"
            touch(donor)
        candidate["status"] = "EXCLUDED"
        touch(candidate)
        if candidate["candidate_role"] == "PRIMARY":
            cascades.primary_lost(search, candidate)
        return success(serializers.typing_request_dict(request_row))

    matched = calc.allele_matched_alleles(patient["hla_typing"], typing)
    grade = "%d/10" % matched
    confirmed = calc.match_probability_score(patient, donor, registry, typing,
                                             (), "CONFIRMED")
    request_row["reported_match_grade"] = grade
    candidate["confirmed_score"] = confirmed
    candidate["confirmed_match_grade"] = grade
    candidate["status"] = "TYPING_RESPONDED"
    touch(candidate)

    if matched < calc.MIN_ACCEPTABLE_ALLELE_MATCHES:
        candidate["status"] = "EXCLUDED"
        touch(candidate)
        if candidate["candidate_role"] == "PRIMARY":
            cascades.primary_lost(search, candidate)

    return success(serializers.typing_request_dict(request_row))


# ------------------------------------------------------------- screening ----
@bp.post("/registry/match-candidates/<cid>/screening")
def screening(cid):
    actor = authenticate(ROLE_LIAISON)
    body = v.read_body()
    outcome = v.req_enum(body, "outcome", OUTCOMES)
    deferral_type = v.req_enum(body, "deferral_type", DEFERRAL_TYPES)
    deferral_until = v.opt_date(body, "deferral_until")
    v.opt_obj(body, "questionnaire_flags")

    candidate = find(db.candidates, cid, "ERR_MATCH_CANDIDATE_NOT_FOUND")
    donor = cascades.donor_of_candidate(candidate)
    if donor is None or donor["registry_id"] != actor.user_id:
        raise ApiError("ERR_REGISTRY_SCOPE_VIOLATION")

    if candidate["status"] not in ("TYPING_RESPONDED", "DEFERRED"):
        raise ApiError("ERR_INVALID_CANDIDATE_STATE")

    if outcome == "PASS" and donor["availability_status"] != "AVAILABLE":
        raise ApiError("ERR_DONOR_NOT_AVAILABLE")

    if outcome == "PASS":
        if deferral_type != "NONE" or deferral_until is not None:
            raise ApiError("ERR_SCREENING_OUTCOME_MISMATCH")
    elif outcome == "DEFER":
        if deferral_type != "TEMPORARY" or deferral_until is None or \
                deferral_until <= db.today():
            raise ApiError("ERR_SCREENING_OUTCOME_MISMATCH")
    else:
        if deferral_type != "PERMANENT" or deferral_until is not None:
            raise ApiError("ERR_SCREENING_OUTCOME_MISMATCH")

    search = cascades.search_of_candidate(candidate)
    was_primary = candidate["candidate_role"] == "PRIMARY"

    if outcome == "PASS":
        candidate["status"] = "SCREENING_PASSED"
        candidate["screening_outcome"] = "PASS"
        candidate["screening_deferral_type"] = "NONE"
        touch(candidate)
    elif outcome == "DEFER":
        candidate["status"] = "DEFERRED"
        candidate["screening_outcome"] = "DEFER"
        candidate["screening_deferral_type"] = "TEMPORARY"
        touch(candidate)
        if donor["availability_status"] == "AVAILABLE":
            cascades.defer_donor_temporarily(donor, deferral_until)
        if was_primary:
            cascades.primary_lost(search, candidate)
    else:
        donor["availability_status"] = "PERMANENTLY_DEFERRED"
        donor["deferral_until"] = None
        touch(donor)
        cascades.exclude_donor_candidates(donor)
        candidate["status"] = "EXCLUDED"
        candidate["screening_outcome"] = "FAIL"
        candidate["screening_deferral_type"] = "PERMANENT"
        touch(candidate)
        if was_primary:
            cascades.primary_lost(search, candidate)

    return success(serializers.candidate_dict(candidate))


# ---------------------------------------------------------- workup opening ----
@bp.post("/registry/match-candidates/<cid>/workup-cases")
def open_workup(cid):
    actor = authenticate(ROLE_COORDINATOR)
    v.read_body()

    candidate = find(db.candidates, cid, "ERR_MATCH_CANDIDATE_NOT_FOUND")
    search = cascades.search_of_candidate(candidate)
    patient = cascades.patient_of_search(search) if search else None
    if actor.is_coordinator and patient is not None and \
            patient["coordinating_user_id"] != actor.user_id:
        raise ApiError("ERR_PATIENT_NOT_OWNED")

    if search is None or search["status"] in cascades.SEARCH_BLOCKED:
        raise ApiError("ERR_SEARCH_ALREADY_TERMINAL")
    if candidate["status"] not in ("SCREENING_PASSED", "WORKUP_OPEN"):
        raise ApiError("ERR_INVALID_CANDIDATE_STATE")
    if candidate["candidate_role"] != "PRIMARY":
        raise ApiError("ERR_CANDIDATE_NOT_PRIMARY")

    for case in db.workup_cases.values():
        if case["match_candidate_id"] == candidate["id"] and \
                case["case_status"] == "OPEN":
            raise ApiError("ERR_DUPLICATE_OPEN_WORKUP")

    projected = claims.provisional_total(candidate)
    committed = calc.committed_cost_cents(patient["id"])
    if committed + projected > patient["case_budget_cents"]:
        raise ApiError("ERR_PATIENT_BUDGET_EXCEEDED")

    case = new_row(
        match_candidate_id=candidate["id"],
        case_status="OPEN",
        clearance_status="PENDING",
        logistics_status="UNSCHEDULED",
        collection_method=None,
        method_decided_by_user_id=None,
        physical_cleared_by_user_id=None,
        idm_resulted_at=None,
        opened_by_user_id=actor.user_id,
        planned_window_days=calc.PLANNED_WINDOW_DAYS_DEFAULT,
        abort_reason=None,
    )
    db.workup_cases[case["id"]] = case

    for item_type in CLEARANCE_ITEM_ORDER:
        item = new_row(
            workup_case_id=case["id"],
            item_type=item_type,
            result="PENDING",
            resulted_at=None,
            resulted_by_user_id=None,
            expires_at=None,
            note=None,
        )
        db.clearance_items[item["id"]] = item

    claims.create_provisional(case, patient, candidate)

    candidate["status"] = "WORKUP_OPEN"
    touch(candidate)
    if search["status"] != "WORKUP_ACTIVE":
        search["status"] = "WORKUP_ACTIVE"
        touch(search)

    return success(serializers.workup_dict(case), 201)

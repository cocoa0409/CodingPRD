"""Patients, the conditioning timeline and registry searches (PRD 3.3, 3.8)."""

from datetime import timedelta

from flask import Blueprint

import calc
import cascades
import serializers
import validate as v
from auth import ROLE_COORDINATOR, ROLE_DIRECTOR, ROLE_OPS, authenticate
from envelope import read_pagination, success
from errors import ApiError
from guards import find, render_list
from store import db, new_row, ordered, touch

bp = Blueprint("registry_patients", __name__)

URGENCY = ("STANDARD", "HIGH", "CRITICAL")
CMV = ("NEGATIVE", "POSITIVE")
SCOPES = ("DOMESTIC_ONLY", "DOMESTIC_AND_INTERNATIONAL")
ACTIONS = ("SCHEDULE", "START", "INFUSE", "ABORT")
SEARCH_LIVE = ("SEARCHING", "PRIMARY_ENGAGED", "WORKUP_ACTIVE", "BACKUP_REQUIRED")
CONDITIONING_LEGAL_FROM = {
    "SCHEDULE": ("NOT_SCHEDULED", "SCHEDULED"),
    "START": ("SCHEDULED",),
    "INFUSE": ("STARTED",),
    "ABORT": ("SCHEDULED", "STARTED"),
}


@bp.get("/registry/patients/<pid>")
def get_patient(pid):
    authenticate(ROLE_COORDINATOR, ROLE_DIRECTOR, ROLE_OPS)
    row = find(db.patients, pid, "ERR_PATIENT_NOT_FOUND")
    return success(serializers.patient_dict(row))


@bp.post("/registry/patients")
def create_patient():
    actor = authenticate(ROLE_COORDINATOR)
    body = v.read_body()
    mrn = v.req_str(body, "mrn", 1, 32)
    center_code = v.req_str(body, "transplant_center_code", 1, 16)
    country_code = v.req_str(body, "country_code", 2, 2, v.COUNTRY_RE)
    diagnosis_code = v.req_str(body, "diagnosis_code", 1, 16)
    urgency = v.req_enum(body, "urgency_tier", URGENCY)
    weight_kg = v.req_num(body, "weight_kg", gt=0, max_dp=1)
    cmv_status = v.req_enum(body, "cmv_status", CMV)
    typing = v.hla_typing(body, "hla_typing")
    budget = v.req_int(body, "case_budget_cents", 0)

    for existing in db.patients.values():
        if existing["mrn"] == mrn:
            raise ApiError("ERR_MRN_ALREADY_EXISTS")

    row = new_row(
        mrn=mrn,
        transplant_center_code=center_code,
        country_code=country_code,
        diagnosis_code=diagnosis_code,
        urgency_tier=urgency,
        weight_kg=weight_kg,
        cmv_status=cmv_status,
        hla_typing=typing,
        case_budget_cents=budget,
        coordinating_user_id=actor.user_id,
        conditioning_status="NOT_SCHEDULED",
        conditioning_start_date=None,
        conditioning_aborted_reason=None,
    )
    db.patients[row["id"]] = row
    return success(serializers.patient_dict(row), 201)


@bp.get("/registry/patients/<pid>/search-requests")
def list_patient_searches(pid):
    authenticate(ROLE_COORDINATOR, ROLE_DIRECTOR, ROLE_OPS)
    limit, offset = read_pagination()
    find(db.patients, pid, "ERR_PATIENT_NOT_FOUND")
    rows = [s for s in db.searches.values() if s["patient_id"] == pid]
    return render_list(rows, serializers.search_dict, limit, offset)


@bp.get("/registry/search-requests/<sid>")
def get_search(sid):
    authenticate(ROLE_COORDINATOR, ROLE_DIRECTOR, ROLE_OPS)
    row = find(db.searches, sid, "ERR_SEARCH_REQUEST_NOT_FOUND")
    return success(serializers.search_dict(row))


# --------------------------------------------------------- search opening ----
def donor_tied_up(donor_id):
    for candidate in db.candidates.values():
        if candidate["donor_id"] == donor_id and \
                candidate["status"] in ("WORKUP_OPEN", "COLLECTED"):
            return True
    return False


@bp.post("/registry/search-requests")
def create_search():
    actor = authenticate(ROLE_COORDINATOR)
    body = v.read_body()
    patient_id = v.req_str(body, "patient_id", 1)
    scope = v.req_enum(body, "search_scope", SCOPES)
    floor = v.opt_num(body, "min_preliminary_score", ge=0, le=100, max_dp=2,
                      default=calc.MIN_PRELIM_SCORE_DEFAULT)

    patient = find(db.patients, patient_id, "ERR_PATIENT_NOT_FOUND")
    if actor.is_coordinator and patient["coordinating_user_id"] != actor.user_id:
        raise ApiError("ERR_PATIENT_NOT_OWNED")

    for existing in db.searches.values():
        if existing["patient_id"] == patient_id and \
                existing["status"] in SEARCH_LIVE:
            raise ApiError("ERR_SEARCH_ALREADY_ACTIVE")

    search = new_row(
        patient_id=patient_id,
        search_scope=scope,
        min_preliminary_score=floor,
        status="SEARCHING",
        last_sweep_at=None,
    )
    db.searches[search["id"]] = search

    eligible = []
    for donor in ordered(list(db.donors.values())):
        if donor["availability_status"] != "AVAILABLE":
            continue
        registry = db.registries.get(donor["registry_id"])
        if registry is None or registry["cooperation_status"] != "ACTIVE":
            continue
        if donor["age_years"] < calc.DONOR_MIN_AGE or \
                donor["age_years"] > calc.DONOR_MAX_AGE:
            continue
        if scope == "DOMESTIC_ONLY" and not registry["is_domestic"]:
            continue
        if donor_tied_up(donor["id"]):
            continue
        preliminary = calc.match_probability_score(
            patient, donor, registry, donor["hla_typing_registry"],
            donor["ambiguous_loci"], "PRELIMINARY")
        if preliminary < floor:
            continue
        rank = calc.candidate_rank_score(donor, registry, preliminary)
        eligible.append((donor, preliminary, rank))

    eligible.sort(key=lambda entry: (-entry[2], -entry[1],
                                     entry[0]["created_at"], entry[0]["_seq"]))
    kept = eligible[:calc.MAX_CANDIDATES_MATERIALIZED]

    for index, (donor, preliminary, rank) in enumerate(kept):
        position = index + 1
        if position == 1:
            role = "PRIMARY"
        elif position <= 1 + calc.BACKUP_SLOTS:
            role = "BACKUP"
        else:
            role = "ARCHIVED_POOL"
        candidate = new_row(
            search_request_id=search["id"],
            donor_id=donor["id"],
            preliminary_score=preliminary,
            confirmed_score=None,
            confirmed_match_grade=None,
            rank_score=rank,
            rank_position=position,
            candidate_role=role,
            status="IDENTIFIED",
            ct_attempt_count=0,
            screening_outcome=None,
            screening_deferral_type=None,
            promoted_from_rank=None,
        )
        db.candidates[candidate["id"]] = candidate

    if not kept:
        search["status"] = "NO_MATCH_FOUND"

    return success(serializers.search_dict(search), 201)


# ---------------------------------------------------------- deadline sweep ----
@bp.post("/registry/search-requests/<sid>/deadline-sweep")
def deadline_sweep(sid):
    authenticate(ROLE_OPS)
    search = find(db.searches, sid, "ERR_SEARCH_REQUEST_NOT_FOUND")
    now = db.now()

    for request in cascades.search_typing_requests(search["id"]):
        if request["status"] != "REQUESTED":
            continue
        if not request["deadline_at"] < now:
            continue
        request["status"] = "EXPIRED"
        request["expired_by_sweep_at"] = now
        touch(request)
        candidate = db.candidates.get(request["match_candidate_id"])
        if candidate is None:
            continue
        if candidate["status"] == "TYPING_REQUESTED":
            candidate["status"] = "TYPING_EXPIRED"
            touch(candidate)
        if candidate["candidate_role"] == "PRIMARY" and \
                candidate["ct_attempt_count"] >= calc.MAX_CT_ATTEMPTS:
            candidate["status"] = "EXCLUDED"
            touch(candidate)
            cascades.primary_lost(search, candidate)

    search["last_sweep_at"] = now
    touch(search)
    cascades.stall_if_unpromotable(search)
    return success(serializers.search_dict(search))


# ------------------------------------------------------------ conditioning ----
def _legal_window(start_date):
    return (start_date + timedelta(days=calc.CONDITIONING_TO_COLLECTION_MIN_DAYS),
            start_date + timedelta(days=calc.CONDITIONING_TO_COLLECTION_MAX_DAYS))


@bp.post("/registry/patients/<pid>/conditioning")
def conditioning(pid):
    actor = authenticate(ROLE_COORDINATOR, ROLE_DIRECTOR)
    body = v.read_body()
    action = v.req_enum(body, "action", ACTIONS)
    expected_version = v.req_int(body, "expected_patient_version", 0)
    start_date = None
    reason = None
    if action == "SCHEDULE":
        start_date = v.req_date(body, "conditioning_start_date")
    else:
        start_date = v.opt_date(body, "conditioning_start_date")
    if action == "ABORT":
        reason = v.req_str(body, "reason", 1)
    else:
        reason = v.opt_str(body, "reason", 1)

    patient = find(db.patients, pid, "ERR_PATIENT_NOT_FOUND")
    if actor.is_coordinator and patient["coordinating_user_id"] != actor.user_id:
        raise ApiError("ERR_PATIENT_NOT_OWNED")

    current = patient["conditioning_status"]
    if current not in CONDITIONING_LEGAL_FROM[action]:
        raise ApiError("ERR_INVALID_CONDITIONING_ACTION")

    open_case = cascades.open_case_of_patient(patient["id"])

    # priority 27 -- cross-entity preconditions
    if action == "SCHEDULE":
        if current == "NOT_SCHEDULED":
            live = [s for s in db.searches.values()
                    if s["patient_id"] == patient["id"]
                    and s["status"] == "WORKUP_ACTIVE"]
            if not live:
                raise ApiError("ERR_CONDITIONING_PRECONDITION_UNMET")
        else:
            for case in cascades.cases_of_patient(patient["id"]):
                for booking in cascades.case_bookings(case["id"]):
                    if booking["status"] == "COMPLETED":
                        raise ApiError("ERR_CONDITIONING_PRECONDITION_UNMET")
    elif action == "START":
        if patient["conditioning_start_date"] is None or \
                db.today() < patient["conditioning_start_date"]:
            raise ApiError("ERR_CONDITIONING_PRECONDITION_UNMET")
        confirmed = False
        if open_case is not None:
            for booking in cascades.case_bookings(open_case["id"]):
                if booking["status"] == "CONFIRMED":
                    confirmed = True
        if not confirmed:
            raise ApiError("ERR_CONDITIONING_PRECONDITION_UNMET")

    # priority 28 -- the product must be delivered before an infusion
    delivered = None
    if action == "INFUSE":
        if open_case is not None:
            for shipment in cascades.case_shipments(open_case["id"]):
                if shipment["status"] == "DELIVERED":
                    delivered = shipment
        if delivered is None:
            raise ApiError("ERR_PRODUCT_NOT_DELIVERED")

    # priority 34 -- optimistic concurrency guard
    if expected_version != patient["version"]:
        raise ApiError("ERR_STALE_PATIENT_VERSION")

    # priority 39 then 47 -- dose adequacy precedes viability
    if action == "INFUSE":
        if delivered["dose_adequacy"] != "ADEQUATE":
            raise ApiError("ERR_PRODUCT_DOSE_INADEQUATE")
        if db.now() > delivered["must_infuse_by"]:
            raise ApiError("ERR_PRODUCT_VIABILITY_EXPIRED")

    # priority 43 -- a scheduled date may not lie in the past
    if action == "SCHEDULE" and start_date < db.today():
        raise ApiError("ERR_CONDITIONING_DATE_IN_PAST")

    if action == "SCHEDULE":
        patient["conditioning_status"] = "SCHEDULED"
        patient["conditioning_start_date"] = start_date
        touch(patient)
        if current == "SCHEDULED":
            _reschedule_bookings(patient, start_date)
    elif action == "START":
        patient["conditioning_status"] = "STARTED"
        touch(patient)
    elif action == "INFUSE":
        patient["conditioning_status"] = "INFUSED"
        touch(patient)
        _infuse(open_case)
    else:
        patient["conditioning_status"] = "ABORTED"
        patient["conditioning_aborted_reason"] = reason
        touch(patient)
        cascades.conditioning_abort_cascade(patient, reason)

    return success(serializers.patient_dict(patient))


def _reschedule_bookings(patient, start_date):
    """PRD 3.8: bookings outside the re-derived window are cancelled."""
    window_from, window_to = _legal_window(start_date)
    for case in cascades.cases_of_patient(patient["id"]):
        if case["case_status"] != "OPEN":
            continue
        for booking in cascades.case_bookings(case["id"]):
            if booking["status"] not in ("HELD", "CONFIRMED"):
                continue
            if window_from <= booking["collection_date"] <= window_to:
                continue
            cascades.cancel_booking(booking,
                                    cascades.CONDITIONING_RESCHEDULE_REASON)
        cascades.revert_logistics_when_unbooked(case)


def _infuse(case):
    if case is None:
        return
    case["case_status"] = "COMPLETED"
    touch(case)
    candidate = cascades.candidate_of(case)
    if candidate is not None:
        candidate["status"] = "CLOSED"
        touch(candidate)
        search = cascades.search_of_candidate(candidate)
        if search is not None and search["status"] not in ("NO_MATCH_FOUND",
                                                           "FULFILLED"):
            search["status"] = "FULFILLED"
            touch(search)

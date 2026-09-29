"""Conflict checks, waivers and matter declinations (PRD 3.5)."""

import cascades
import listing
import lookups as lk
import middleware as mw
import services as svc
from db import db, new_row, pub, set_fields, sorted_rows
from errors import ApiError
from flask import Blueprint
from response import object_response

bp = Blueprint("conflicts", __name__, url_prefix="/lateral-hiring")

READ_CONFLICT = ("SystemAdmin", "RecruitingCoordinator", "ConflictsCounsel",
                 "CommitteeMember", "CommitteeChair")
OPEN_QUESTIONNAIRE = ("UNDER_REVIEW", "REVISION_REQUESTED", "ACCEPTED")


@bp.post("/client-book-entries/<entry_id>/conflict-checks")
def create_check(entry_id):
    mw.authenticate(("ConflictsCounsel",))
    entry = lk.get_entry(entry_id)
    data = mw.body()
    adverse_party_name = mw.v_str(data, "adverse_party_name", 1, 120)
    affected = mw.v_str_list(data, "affected_matter_types", 1, 6, 1, 60)
    severity = mw.v_enum(data, "severity",
                         ("DIRECT_ADVERSE", "POSITIONAL", "IMPUTED"))

    questionnaire = lk.get_questionnaire(entry["questionnaire_id"])
    if entry["status"] != "ACTIVE":
        raise ApiError("ERR_QUESTIONNAIRE_INVALID_STATE",
                       "The client book entry is not ACTIVE.")
    if questionnaire["status"] not in OPEN_QUESTIONNAIRE:
        raise ApiError("ERR_QUESTIONNAIRE_INVALID_STATE")
    for matter_type in affected:
        if matter_type not in entry["matter_types"]:
            raise ApiError("ERR_MATTER_TYPE_NOT_ON_ENTRY")

    row = new_row({
        "client_book_entry_id": entry["id"],
        "adverse_party_name": adverse_party_name,
        "affected_matter_types": affected,
        "severity": severity,
        "status": "PENDING",
        "resolution_note": None,
    })
    db.conflict_checks[row["id"]] = row
    candidate = svc.candidate_of_entry(entry)
    if candidate is not None:
        svc.recompute_clearance(candidate)
    return object_response(pub(row), 201)


@bp.get("/conflict-checks/<conflict_check_id>")
def read_check(conflict_check_id):
    mw.authenticate(READ_CONFLICT)
    return object_response(pub(lk.get_conflict_check(conflict_check_id)))


@bp.get("/conflict-checks")
def list_checks():
    mw.authenticate(READ_CONFLICT)
    rows = list(db.conflict_checks.values())
    rows = listing.eq_filter(rows, "client_book_entry_id")
    rows = listing.eq_filter(rows, "status")
    rows = listing.eq_filter(rows, "severity")
    return listing.paged(rows)


@bp.post("/conflict-checks/<conflict_check_id>/clear")
def clear_check(conflict_check_id):
    mw.authenticate(("ConflictsCounsel",))
    check = lk.get_conflict_check(conflict_check_id)
    data = mw.body()
    note = mw.v_str(data, "resolution_note", 1, 500)
    if check["status"] != "PENDING":
        raise ApiError("ERR_CONFLICT_CHECK_INVALID_STATE")
    if check["severity"] == "DIRECT_ADVERSE":
        raise ApiError("ERR_DIRECT_ADVERSE_REQUIRES_WAIVER")
    set_fields(check, status="CLEAR", resolution_note=note)
    entry = db.client_book_entries.get(check["client_book_entry_id"])
    if entry is not None:
        candidate = svc.candidate_of_entry(entry)
        if candidate is not None:
            svc.recompute_clearance(candidate)
    return object_response(pub(check))


# ------------------------------------------------------------------- waivers

@bp.post("/conflict-checks/<conflict_check_id>/waivers")
def create_waiver(conflict_check_id):
    mw.authenticate(("ConflictsCounsel",))
    check = lk.get_conflict_check(conflict_check_id)
    data = mw.body()
    strategy = mw.v_enum(data, "waiver_strategy",
                         ("ADVANCE_CONSENT", "ETHICAL_WALL", "MATTER_CARVE_OUT"))
    requested_from_client = mw.v_str(data, "requested_from_client", 1, 120)
    deadline = mw.v_dt(data, "response_deadline_date")

    if check["status"] != "PENDING":
        raise ApiError("ERR_CONFLICT_CHECK_INVALID_STATE")
    if strategy == "ETHICAL_WALL" and check["severity"] == "DIRECT_ADVERSE":
        raise ApiError("ERR_DIRECT_ADVERSE_REQUIRES_WAIVER")
    if deadline <= db.clock:
        raise ApiError("ERR_LOOKBACK_WINDOW_INVALID")

    row = new_row({
        "conflict_check_id": check["id"],
        "waiver_strategy": strategy,
        "requested_from_client": requested_from_client,
        "response_deadline_date": deadline,
        "status": "REQUESTED",
        "resolution_note": None,
        "decided_at": None,
    })
    db.waivers[row["id"]] = row
    set_fields(check, status="WAIVER_PENDING")
    return object_response(pub(row), 201)


@bp.get("/conflict-waivers/<waiver_id>")
def read_waiver(waiver_id):
    mw.authenticate(READ_CONFLICT)
    return object_response(pub(lk.get_waiver(waiver_id)))


@bp.get("/conflict-waivers")
def list_waivers():
    mw.authenticate(READ_CONFLICT)
    rows = list(db.waivers.values())
    rows = listing.eq_filter(rows, "conflict_check_id")
    rows = listing.eq_filter(rows, "status")
    return listing.paged(rows)


@bp.post("/conflict-waivers/<waiver_id>/grant")
def grant_waiver(waiver_id):
    mw.authenticate(("ConflictsCounsel",))
    waiver = lk.get_waiver(waiver_id)
    data = mw.body()
    note = mw.v_str(data, "resolution_note", 1, 500)
    if waiver["status"] != "REQUESTED":
        raise ApiError("ERR_WAIVER_INVALID_STATE")
    if db.clock > waiver["response_deadline_date"]:
        raise ApiError("ERR_WAIVER_INVALID_STATE",
                       "The response deadline has already passed.")
    set_fields(waiver, status="GRANTED", resolution_note=note,
               decided_at=db.clock)
    check = db.conflict_checks.get(waiver["conflict_check_id"])
    if check is not None and check["status"] == "WAIVER_PENDING":
        set_fields(check, status="CLEAR")
        entry = db.client_book_entries.get(check["client_book_entry_id"])
        if entry is not None:
            candidate = svc.candidate_of_entry(entry)
            if candidate is not None:
                svc.recompute_clearance(candidate)
    return object_response(pub(waiver))


@bp.post("/conflict-waivers/<waiver_id>/refuse")
def refuse_waiver(waiver_id):
    mw.authenticate(("ConflictsCounsel",))
    waiver = lk.get_waiver(waiver_id)
    data = mw.body()
    note = mw.v_str(data, "resolution_note", 1, 500)
    if waiver["status"] != "REQUESTED":
        raise ApiError("ERR_WAIVER_INVALID_STATE")
    cascades.resolve_waiver_negative(waiver, "REFUSED", note=note)
    return object_response(pub(waiver))


# -------------------------------------------------------------- declinations

@bp.get("/matter-declinations/<declination_id>")
def read_declination(declination_id):
    mw.authenticate(READ_CONFLICT)
    return object_response(pub(lk.get_declination(declination_id)))


@bp.get("/matter-declinations")
def list_declinations():
    mw.authenticate(READ_CONFLICT)
    rows = list(db.declinations.values())
    rows = listing.eq_filter(rows, "conflict_check_id")
    rows = listing.eq_filter(rows, "client_book_entry_id")
    rows = listing.eq_filter(rows, "status")
    return listing.paged(rows)


@bp.post("/matter-declinations/<declination_id>/rescind")
def rescind_declination(declination_id):
    mw.authenticate(("ConflictsCounsel",))
    declination = lk.get_declination(declination_id)
    data = mw.body()
    mw.v_str(data, "rescission_note", 1, 500)
    check = db.conflict_checks.get(declination["conflict_check_id"])
    if declination["status"] != "ACTIVE":
        raise ApiError("ERR_DECLINATION_INVALID_STATE")
    if check is None or check["status"] != "BLOCKED":
        raise ApiError("ERR_CONFLICT_CHECK_INVALID_STATE")

    set_fields(declination, status="RESCINDED", rescinded_at=db.clock)

    entry = db.client_book_entries.get(declination["client_book_entry_id"])
    if entry is None:
        return object_response(pub(declination))
    remaining = [d for d in lk.declinations_of_entry(entry["id"])
                 if d["status"] == "ACTIVE"]
    if remaining:
        return object_response(pub(declination))

    set_fields(entry, portable_status="VALIDATED",
               validated_portable_amount_usd=entry["baseline_portable_amount_usd"])
    set_fields(check, status="CLEAR")
    for assessment in sorted_rows(lk.assessments_of_questionnaire(entry["questionnaire_id"])):
        if assessment["status"] in ("CURRENT", "STALE"):
            svc.recompute_assessment_totals(assessment)
    candidate = svc.candidate_of_entry(entry)
    if candidate is not None:
        svc.recompute_clearance(candidate)
    return object_response(pub(declination))

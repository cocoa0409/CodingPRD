"""Client book entries, collection records and portability assessments."""

import calculations as calc
import listing
import lookups as lk
import middleware as mw
import services as svc
from db import db, new_row, pub, set_fields, sorted_rows
from errors import ApiError
from flask import Blueprint, request
from response import object_response

bp = Blueprint("book", __name__, url_prefix="/lateral-hiring")

READ_ENTRY = mw.READ_ALL + ("Candidate",)
READ_RECORD = ("SystemAdmin", "RecruitingCoordinator", "PracticeGroupLeader",
               "CommitteeMember", "CommitteeChair")
MUTABLE_BOOK = ("DRAFT", "REVISION_REQUESTED")


@bp.post("/questionnaires/<questionnaire_id>/client-book-entries")
def create_entry(questionnaire_id):
    user_id, _role = mw.authenticate(("Candidate",))
    questionnaire = lk.get_questionnaire(questionnaire_id)
    data = mw.body()
    client_name = mw.v_str(data, "client_name", 1, 120)
    relationship_role = mw.v_enum(data, "relationship_role", calc.ROLE_FACTOR.keys())
    consent = mw.v_enum(data, "client_consent_status",
                        ("CONSENT_PENDING", "CONSENT_CONFIRMED"),
                        required=False, default="CONSENT_PENDING")
    billings = mw.v_num(data, "claimed_annual_billings_usd", minimum=0,
                        exclusive_min=True)
    portability = mw.v_num(data, "claimed_portability_pct", minimum=0, maximum=1,
                           exclusive_min=True)
    realization = mw.v_num(data, "claimed_realization_rate", minimum=0, maximum=1,
                           exclusive_min=True)
    matter_types = mw.v_str_list(data, "matter_types", 1, 6, 1, 60, distinct=True)

    if user_id != questionnaire["candidate_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if questionnaire["status"] not in MUTABLE_BOOK:
        raise ApiError("ERR_QUESTIONNAIRE_INVALID_STATE")
    for existing in lk.entries_of_questionnaire(questionnaire_id, active_only=True):
        if existing["client_name"] == client_name:
            raise ApiError("ERR_DUPLICATE_CLIENT_ENTRY")

    row = new_row({
        "questionnaire_id": questionnaire["id"],
        "client_name": client_name,
        "relationship_role": relationship_role,
        "client_consent_status": consent,
        "claimed_annual_billings_usd": billings,
        "claimed_portability_pct": portability,
        "claimed_realization_rate": realization,
        "matter_types": matter_types,
        "status": "ACTIVE",
        "portable_status": "UNVALIDATED",
        "baseline_portable_amount_usd": calc.ZERO,
        "validated_portable_amount_usd": calc.ZERO,
        "verified_record_count": 0,
    })
    db.client_book_entries[row["id"]] = row
    svc.sync_questionnaire_entry_count(questionnaire)
    svc.stale_current_assessments(questionnaire["id"])
    return object_response(pub(row), 201)


@bp.get("/client-book-entries/<entry_id>")
def read_entry(entry_id):
    mw.authenticate(READ_ENTRY)
    return object_response(pub(lk.get_entry(entry_id)))


@bp.get("/client-book-entries")
def list_entries():
    mw.authenticate(mw.READ_ALL)
    include_withdrawn = mw.query_bool("include_withdrawn", False)
    rows = list(db.client_book_entries.values())
    rows = listing.eq_filter(rows, "questionnaire_id")
    rows = listing.eq_filter(rows, "status")
    rows = listing.eq_filter(rows, "portable_status")
    if not include_withdrawn:
        rows = [r for r in rows if r["status"] != "WITHDRAWN"]
    return listing.paged(rows)


@bp.delete("/client-book-entries/<entry_id>")
def delete_entry(entry_id):
    user_id, _role = mw.authenticate(("Candidate",))
    entry = lk.get_entry(entry_id)
    questionnaire = lk.get_questionnaire(entry["questionnaire_id"])
    if user_id != questionnaire["candidate_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if questionnaire["status"] not in MUTABLE_BOOK:
        raise ApiError("ERR_QUESTIONNAIRE_INVALID_STATE")
    if entry["status"] == "WITHDRAWN":
        return object_response(pub(entry))
    set_fields(entry, status="WITHDRAWN")
    svc.sync_questionnaire_entry_count(questionnaire)
    svc.stale_current_assessments(questionnaire["id"])
    return object_response(pub(entry))


# ------------------------------------------------------------ collection records

@bp.post("/candidates/<candidate_id>/collection-records")
def create_collection_record(candidate_id):
    mw.authenticate(("SystemAdmin", "RecruitingCoordinator"))
    candidate = lk.get_candidate(candidate_id)
    data = mw.body()
    entry = None
    if isinstance(data.get("client_book_entry_id"), str):
        entry = lk.get_entry(data["client_book_entry_id"])
    record_type = mw.v_enum(data, "record_type", ("HISTORICAL", "POST_HIRE"))
    period_end_date = mw.v_dt(data, "period_end_date")
    amount = mw.v_num(data, "amount_usd", minimum=0)
    status = mw.v_enum(data, "status", ("UNVERIFIED", "VERIFIED"),
                       required=False, default="UNVERIFIED")
    source = mw.v_enum(data, "source", ("PRIOR_FIRM_STATEMENT",
                                       "CANDIDATE_ATTESTATION", "FIRM_LEDGER"))

    row = new_row({
        "candidate_id": candidate["id"],
        "client_book_entry_id": entry["id"] if entry is not None else None,
        "record_type": record_type,
        "period_end_date": period_end_date,
        "amount_usd": amount,
        "status": status,
        "source": source,
    }, versioned=False)
    db.collection_records[row["id"]] = row

    if entry is not None:
        verified = len([r for r in lk.records_of_entry(entry["id"])
                        if r["record_type"] == "HISTORICAL" and r["status"] == "VERIFIED"])
        set_fields(entry, verified_record_count=verified)
    if record_type == "HISTORICAL" and status == "VERIFIED":
        for questionnaire in sorted_rows(lk.questionnaires_of_candidate(candidate["id"])):
            svc.stale_current_assessments(questionnaire["id"])
    return object_response(pub(row), 201)


@bp.get("/collection-records/<record_id>")
def read_collection_record(record_id):
    mw.authenticate(READ_RECORD)
    return object_response(pub(lk.get_collection_record(record_id)))


@bp.get("/collection-records")
def list_collection_records():
    mw.authenticate(READ_RECORD)
    rows = list(db.collection_records.values())
    rows = listing.eq_filter(rows, "candidate_id")
    rows = listing.eq_filter(rows, "client_book_entry_id")
    rows = listing.eq_filter(rows, "record_type")
    rows = listing.eq_filter(rows, "status")
    return listing.paged(rows)


# ------------------------------------------------------- portability assessments

@bp.post("/questionnaires/<questionnaire_id>/portability-assessments")
def create_assessment(questionnaire_id):
    mw.authenticate(("RecruitingCoordinator",))
    questionnaire = lk.get_questionnaire(questionnaire_id)
    data = mw.body()
    baseline_date = mw.v_dt(data, "baseline_date")
    governing_basis = mw.v_enum(data, "governing_basis",
                                ("SELF_REPORTED", "VALIDATED"),
                                required=False, default="VALIDATED")
    expected_version = mw.v_int(data, "expected_questionnaire_version")

    if expected_version != questionnaire["version"]:
        raise ApiError("ERR_STALE_QUESTIONNAIRE_VERSION")
    if questionnaire["status"] not in ("UNDER_REVIEW", "ACCEPTED"):
        raise ApiError("ERR_QUESTIONNAIRE_INVALID_STATE")
    if baseline_date > db.clock:
        raise ApiError("ERR_LOOKBACK_WINDOW_INVALID")

    scope = svc.scope_entries(questionnaire["id"])
    if len(scope) < 1:
        raise ApiError("ERR_EMPTY_CLIENT_BOOK")
    lookback_start = svc.minus_years(baseline_date, 3)
    for entry in scope:
        records = svc.verified_historical_in_window(entry["id"], lookback_start,
                                                   baseline_date)
        if len(records) < calc.MIN_VERIFIED_RECORDS:
            raise ApiError("ERR_UNVERIFIED_COLLECTION_DATA")

    fields = svc.assessment_fields(questionnaire, baseline_date, governing_basis)
    row = new_row(fields)
    db.assessments[row["id"]] = row

    for other in sorted_rows(lk.assessments_of_questionnaire(questionnaire["id"])):
        if other["id"] == row["id"]:
            continue
        if other["status"] in ("CURRENT", "STALE"):
            set_fields(other, status="SUPERSEDED")
    set_fields(questionnaire, latest_assessment_id=row["id"])
    return object_response(pub(row), 201)


@bp.get("/portability-assessments/<assessment_id>")
def read_assessment(assessment_id):
    mw.authenticate(READ_RECORD)
    return object_response(pub(lk.get_assessment(assessment_id)))


@bp.get("/portability-assessments")
def list_assessments():
    mw.authenticate(READ_RECORD)
    rows = list(db.assessments.values())
    rows = listing.eq_filter(rows, "questionnaire_id")
    rows = listing.eq_filter(rows, "status")
    rows = listing.eq_filter(rows, "governing_basis")
    return listing.paged(rows)

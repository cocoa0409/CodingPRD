"""Trademark evidence, oral history and exhibit loans."""

from flask import Blueprint, g

from core import add_days, clock, register, sorted_rows, store, touch
from errors import ApiError
from middleware import endpoint
from response import apply_filters, collection_response, object_response
from services import calc
from services.lookup import fetch, refresh_item_last_loan_window
from validation import (
    CONDITION_GRADES,
    CONSENT_ACTIONS,
    TRANSCRIPTION_ACTIONS,
    body,
    venum,
    vid,
    vid_list,
    vinstant,
    vint,
    vstr,
)

bp = Blueprint("heritage", __name__)

PACKAGE_READERS = ("ArchivesDirector", "Archivist", "LegalCounsel")
INTERVIEW_READERS = ("ArchivesDirector", "Archivist", "AccessServicesOfficer")
LOAN_READERS = ("ArchivesDirector", "Archivist", "PreservationOfficer")


# --- trademark evidence packages ------------------------------------------


@bp.post("/trademark-evidence-packages")
@endpoint(("Archivist", "LegalCounsel"))
def create_evidence_package():
    payload = body()
    record_series_id = vid(payload, "record_series_id")
    mark_name = vstr(payload, "mark_name", 1, 120)
    claimed_first_use_year = vint(payload, "claimed_first_use_year", 1800, 2100)
    evidence_item_ids = vid_list(payload, "evidence_item_ids", 80)
    series = fetch("record_series", record_series_id)
    for item_id in evidence_item_ids:
        fetch("archival_items", item_id)
    row = register(
        store.evidence_packages,
        {
            "record_series_id": series["id"],
            "mark_name": mark_name,
            "claimed_first_use_year": claimed_first_use_year,
            "evidence_item_ids": list(evidence_item_ids),
            "status": "DRAFT",
            "qualifying_evidence_count": 0,
            "covered_year_count": 0,
            "max_gap_years": 0,
            "continuous_use_coverage_pct": 0,
            "certified_at": None,
            "rejection_code": None,
        },
    )
    return object_response(row, 201)


@bp.get("/trademark-evidence-packages")
@endpoint(PACKAGE_READERS)
def list_evidence_packages():
    rows = apply_filters(
        sorted_rows(store.evidence_packages),
        {"record_series_id": "record_series_id", "status": "status"},
    )
    return collection_response(rows)


@bp.get("/trademark-evidence-packages/<resource_id>")
@endpoint(PACKAGE_READERS)
def get_evidence_package(resource_id):
    return object_response(fetch("evidence_packages", resource_id))


@bp.post("/trademark-evidence-packages/<resource_id>/certify")
@endpoint(("LegalCounsel",))
def certify_evidence_package(resource_id):
    package = fetch("evidence_packages", resource_id)
    if package["status"] != "DRAFT":
        raise ApiError("ERR_PACKAGE_STATE_INVALID")
    coverage = calc.continuous_use_coverage(package)
    if coverage["qualifying_evidence_count"] == 0:
        raise ApiError("ERR_NO_QUALIFYING_EVIDENCE")
    package["qualifying_evidence_count"] = coverage["qualifying_evidence_count"]
    package["covered_year_count"] = coverage["covered_year_count"]
    package["max_gap_years"] = coverage["max_gap_years"]
    package["continuous_use_coverage_pct"] = coverage["continuous_use_coverage_pct"]
    if coverage["max_gap_years"] > 3:
        package["status"] = "REJECTED"
        package["rejection_code"] = "GAP_EXCEEDED"
    elif coverage["continuous_use_coverage_pct"] < 25.00:
        package["status"] = "REJECTED"
        package["rejection_code"] = "COVERAGE_BELOW_MINIMUM"
    else:
        package["status"] = "CERTIFIED"
        package["certified_at"] = clock.now()
    touch(package)
    return object_response(package)


# --- oral history interviews ----------------------------------------------


@bp.post("/oral-history-interviews")
@endpoint(("Archivist",))
def create_interview():
    payload = body()
    accession_id = vid(payload, "accession_id")
    narrator_name = vstr(payload, "narrator_name", 1, 120)
    interview_date = vinstant(payload, "interview_date")
    embargo_until = vinstant(payload, "embargo_until", required=False, default=None)
    accession = fetch("accessions", accession_id)
    row = register(
        store.interviews,
        {
            "accession_id": accession["id"],
            "narrator_name": narrator_name,
            "interview_date": interview_date,
            "embargo_until": embargo_until,
            "consent_status": "PENDING",
            "transcription_status": "NOT_STARTED",
            "release_state": "WITHHELD",
            "consent_signed_at": None,
            "withdrawal_count": 0,
        },
    )
    return object_response(row, 201)


@bp.get("/oral-history-interviews")
@endpoint(INTERVIEW_READERS)
def list_interviews():
    rows = apply_filters(
        sorted_rows(store.interviews),
        {
            "accession_id": "accession_id",
            "consent_status": "consent_status",
            "transcription_status": "transcription_status",
            "release_state": "release_state",
        },
    )
    return collection_response(rows)


@bp.get("/oral-history-interviews/<resource_id>")
@endpoint(INTERVIEW_READERS)
def get_interview(resource_id):
    return object_response(fetch("interviews", resource_id))


@bp.post("/oral-history-interviews/<resource_id>/consent")
@endpoint(("Archivist",))
def drive_consent_axis(resource_id):
    payload = body()
    action = venum(payload, "consent_action", CONSENT_ACTIONS)
    interview = fetch("interviews", resource_id)
    current = interview["consent_status"]
    if action == "SIGN":
        if current == "PENDING":
            interview["consent_status"] = "SIGNED"
            interview["consent_signed_at"] = clock.now()
        elif current == "RESTRICTED":
            # consent_signed_at records when consent *first* became signed.
            interview["consent_status"] = "SIGNED"
        else:
            raise ApiError("ERR_INTERVIEW_STATE_INVALID")
    elif action == "RESTRICT":
        if current != "SIGNED":
            raise ApiError("ERR_INTERVIEW_STATE_INVALID")
        interview["consent_status"] = "RESTRICTED"
    else:
        if current not in ("SIGNED", "RESTRICTED"):
            raise ApiError("ERR_INTERVIEW_STATE_INVALID")
        interview["consent_status"] = "WITHDRAWN"
        interview["withdrawal_count"] += 1
    interview["release_state"] = calc.interview_release_state(interview)
    touch(interview)
    return object_response(interview)


@bp.post("/oral-history-interviews/<resource_id>/transcription")
@endpoint(("Archivist",))
def drive_transcription_axis(resource_id):
    payload = body()
    action = venum(payload, "transcription_action", TRANSCRIPTION_ACTIONS)
    interview = fetch("interviews", resource_id)
    current = interview["transcription_status"]
    if action == "START_DRAFT":
        if current != "NOT_STARTED":
            raise ApiError("ERR_INTERVIEW_STATE_INVALID")
        interview["transcription_status"] = "DRAFT"
    elif action == "MARK_REVIEWED":
        if current != "DRAFT":
            raise ApiError("ERR_INTERVIEW_STATE_INVALID")
        interview["transcription_status"] = "REVIEWED"
    else:
        if current != "REVIEWED":
            raise ApiError("ERR_INTERVIEW_STATE_INVALID")
        # rung 17 sits ahead of rung 18
        if interview["consent_status"] != "SIGNED":
            raise ApiError("ERR_CONSENT_NOT_SIGNED")
        embargo = interview["embargo_until"]
        if embargo is not None and clock.now() < embargo:
            raise ApiError("ERR_EMBARGO_ACTIVE")
        interview["transcription_status"] = "APPROVED"
    interview["release_state"] = calc.interview_release_state(interview)
    touch(interview)
    return object_response(interview)


# --- exhibit loans ---------------------------------------------------------


@bp.post("/exhibit-loans")
@endpoint(("ArchivesDirector", "Archivist"))
def create_exhibit_loan():
    payload = body()
    archival_item_id = vid(payload, "archival_item_id")
    exhibit_name = vstr(payload, "exhibit_name", 1, 160)
    units = vint(payload, "units", 1, None)
    window_start = vinstant(payload, "window_start")
    window_end = vinstant(payload, "window_end")
    if window_end <= window_start:
        raise ApiError(
            "ERR_INVALID_REQUEST", "Field 'window_end' must be strictly later than 'window_start'."
        )
    item = fetch("archival_items", archival_item_id)
    # rung 31: checked before the row is created.
    if calc.exhibit_loan_window_conflict(item["id"], window_start, window_end) is not None:
        raise ApiError("ERR_LOAN_WINDOW_CONFLICT")
    row = register(
        store.exhibit_loans,
        {
            "archival_item_id": item["id"],
            "exhibit_name": exhibit_name,
            "units": units,
            "window_start": window_start,
            "window_end": window_end,
            "recovery_until": add_days(window_end, calc.LOAN_BUFFER_DAYS),
            "status": "REQUESTED",
            "returned_condition_grade": None,
            "checked_out_at": None,
            "returned_at": None,
        },
    )
    refresh_item_last_loan_window(item)
    return object_response(row, 201)


@bp.get("/exhibit-loans")
@endpoint(LOAN_READERS)
def list_exhibit_loans():
    rows = apply_filters(
        sorted_rows(store.exhibit_loans),
        {"archival_item_id": "archival_item_id", "status": "status"},
    )
    return collection_response(rows)


@bp.get("/exhibit-loans/<resource_id>")
@endpoint(LOAN_READERS)
def get_exhibit_loan(resource_id):
    return object_response(fetch("exhibit_loans", resource_id))


@bp.post("/exhibit-loans/<resource_id>/confirm")
@endpoint(("PreservationOfficer",))
def confirm_exhibit_loan(resource_id):
    loan = fetch("exhibit_loans", resource_id)
    if loan["status"] != "REQUESTED":
        raise ApiError("ERR_LOAN_STATE_INVALID")
    item = store.archival_items[loan["archival_item_id"]]
    if item["status"] != "ACCESSIONED":
        raise ApiError("ERR_ITEM_STATE_INVALID")
    # rung 28
    if item["condition_grade"] not in ("GOOD", "FAIR"):
        raise ApiError("ERR_ITEM_CONDITION_UNSUITABLE")
    # rung 30
    if item["units_on_shelf"] < loan["units"]:
        raise ApiError("ERR_INSUFFICIENT_SHELF_UNITS")
    loan["status"] = "CONFIRMED"
    touch(loan)
    return object_response(loan)


@bp.post("/exhibit-loans/<resource_id>/check-out")
@endpoint(("Archivist",))
def check_out_exhibit_loan(resource_id):
    loan = fetch("exhibit_loans", resource_id)
    if loan["status"] != "CONFIRMED":
        raise ApiError("ERR_LOAN_STATE_INVALID")
    item = store.archival_items[loan["archival_item_id"]]
    if item["status"] != "ACCESSIONED":
        raise ApiError("ERR_ITEM_STATE_INVALID")
    # rung 20 sits ahead of rung 30
    if clock.now() < loan["window_start"]:
        raise ApiError("ERR_LOAN_WINDOW_NOT_OPEN")
    if item["units_on_shelf"] < loan["units"]:
        raise ApiError("ERR_INSUFFICIENT_SHELF_UNITS")
    loan["status"] = "OUT"
    loan["checked_out_at"] = clock.now()
    touch(loan)
    item["units_on_shelf"] -= loan["units"]
    item["units_on_loan"] += loan["units"]
    item["status"] = "ON_LOAN"
    touch(item)
    refresh_item_last_loan_window(item)
    return object_response(loan)


@bp.post("/exhibit-loans/<resource_id>/return")
@endpoint(("Archivist",))
def return_exhibit_loan(resource_id):
    payload = body()
    returned_condition_grade = venum(payload, "returned_condition_grade", CONDITION_GRADES)
    loan = fetch("exhibit_loans", resource_id)
    if loan["status"] != "OUT":
        raise ApiError("ERR_LOAN_STATE_INVALID")
    item = store.archival_items[loan["archival_item_id"]]
    loan["returned_condition_grade"] = returned_condition_grade
    loan["status"] = "RETURNED"
    loan["returned_at"] = clock.now()
    touch(loan)
    item["condition_grade"] = returned_condition_grade
    item["units_on_loan"] -= loan["units"]
    item["units_on_shelf"] += loan["units"]
    item["status"] = "ACCESSIONED"
    touch(item)
    refresh_item_last_loan_window(item)
    return object_response(loan)


@bp.post("/exhibit-loans/<resource_id>/cancel")
@endpoint(("ArchivesDirector", "Archivist"))
def cancel_exhibit_loan(resource_id):
    loan = fetch("exhibit_loans", resource_id)
    if loan["status"] not in ("REQUESTED", "CONFIRMED"):
        raise ApiError("ERR_LOAN_STATE_INVALID")
    loan["status"] = "CANCELLED"
    touch(loan)
    item = store.archival_items[loan["archival_item_id"]]
    refresh_item_last_loan_window(item)
    return object_response(loan)

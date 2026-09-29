"""Resource resolution (rungs 4 and 5) and derived-field recomputation."""

from core import store, touch
from errors import ApiError
from services import calc

NOT_FOUND = {
    "retention_schedules": "ERR_RETENTION_SCHEDULE_NOT_FOUND",
    "record_series": "ERR_RECORD_SERIES_NOT_FOUND",
    "legal_holds": "ERR_LEGAL_HOLD_NOT_FOUND",
    "appraisals": "ERR_APPRAISAL_NOT_FOUND",
    "accessions": "ERR_ACCESSION_NOT_FOUND",
    "archival_items": "ERR_ARCHIVAL_ITEM_NOT_FOUND",
    "storage_zones": "ERR_STORAGE_ZONE_NOT_FOUND",
    "finding_aids": "ERR_FINDING_AID_NOT_FOUND",
    "preservation_plans": "ERR_PRESERVATION_PLAN_NOT_FOUND",
    "migration_jobs": "ERR_MIGRATION_JOB_NOT_FOUND",
    "requesters": "ERR_REQUESTER_NOT_FOUND",
    "access_requests": "ERR_ACCESS_REQUEST_NOT_FOUND",
    "screenings": "ERR_SCREENING_NOT_FOUND",
    "interviews": "ERR_INTERVIEW_NOT_FOUND",
    "evidence_packages": "ERR_EVIDENCE_PACKAGE_NOT_FOUND",
    "exhibit_loans": "ERR_EXHIBIT_LOAN_NOT_FOUND",
    "deaccession_proposals": "ERR_DEACCESSION_PROPOSAL_NOT_FOUND",
}


def fetch(collection_name, resource_id):
    collection = getattr(store, collection_name)
    row = collection.get(resource_id) if isinstance(resource_id, str) else None
    if row is None:
        raise ApiError(NOT_FOUND[collection_name])
    return row


def series_of_accession(accession):
    return store.record_series[accession["record_series_id"]]


def accession_of_item(item):
    return store.accessions[item["accession_id"]]


def series_of_item(item):
    return series_of_accession(accession_of_item(item))


def schedule_of_series(series):
    return store.retention_schedules[series["retention_schedule_id"]]


def items_of_accession(accession_id):
    return [row for row in store.archival_items.values() if row["accession_id"] == accession_id]


def accessions_of_series(series_id):
    return [row for row in store.accessions.values() if row["record_series_id"] == series_id]


def items_of_series(series_id):
    out = []
    for accession in accessions_of_series(series_id):
        out.extend(items_of_accession(accession["id"]))
    return out


def finding_aids_of_accession(accession_id):
    return [row for row in store.finding_aids.values() if row["accession_id"] == accession_id]


def access_requests_of_series(series_id):
    return [
        row for row in store.access_requests.values() if row["record_series_id"] == series_id
    ]


def screenings_of_request(request_id):
    rows = [
        row for row in store.screenings.values() if row["access_request_id"] == request_id
    ]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


# --- derived counters ------------------------------------------------------

STALE_ITEM_STATUSES = ("PENDING_DISPOSITION", "DEACCESSIONED")


def recompute_accession_counters(accession):
    processed = 0
    deaccessioned = 0
    for item in items_of_accession(accession["id"]):
        if item["status"] != "REJECTED_ITEM":
            processed += item["unit_count"]
        deaccessioned += item["units_deaccessioned"]
    if (
        accession["processed_unit_count"] != processed
        or accession["deaccessioned_unit_count"] != deaccessioned
    ):
        accession["processed_unit_count"] = processed
        accession["deaccessioned_unit_count"] = deaccessioned
        touch(accession)
    return accession


def described_item_count(accession_id):
    return len(
        [row for row in items_of_accession(accession_id) if row["status"] != "REJECTED_ITEM"]
    )


def stale_item_count(accession_id):
    return len(
        [
            row
            for row in items_of_accession(accession_id)
            if row["status"] in STALE_ITEM_STATUSES
        ]
    )


def refresh_item_last_loan_window(item):
    latest = calc.latest_loan_window_end(item["id"])
    if item["last_loan_window_end"] != latest:
        item["last_loan_window_end"] = latest
        touch(item)
    return item


def current_screening(access_request):
    """Most recently created screening in OPEN or COMPLETED, else None."""
    candidates = [
        row
        for row in screenings_of_request(access_request["id"])
        if row["status"] in ("OPEN", "COMPLETED")
    ]
    return candidates[-1] if candidates else None


def refresh_current_screening_pointer(access_request):
    screening = current_screening(access_request)
    pointer = screening["id"] if screening is not None else None
    if access_request["current_screening_id"] != pointer:
        access_request["current_screening_id"] = pointer
    return screening


def active_holds_of_series(series_id, exclude_id=None):
    out = []
    for hold in store.legal_holds.values():
        if hold["record_series_id"] != series_id:
            continue
        if exclude_id is not None and hold["id"] == exclude_id:
            continue
        if hold["status"] == "ACTIVE":
            out.append(hold)
    return out

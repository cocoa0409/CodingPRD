"""Existence resolution helpers, each raising the not-found error named in PRD 2.9 step 5."""
import store
from core import fail

_TABLES = [
    ("project", "projects", "ERR_PROJECT_NOT_FOUND"),
    ("bca", "bcas", "ERR_BCA_NOT_FOUND"),
    ("parcel", "parcels", "ERR_PARCEL_NOT_FOUND"),
    ("appraisal", "appraisals", "ERR_APPRAISAL_NOT_FOUND"),
    ("dob_record", "dob_records", "ERR_DOB_RECORD_NOT_FOUND"),
    ("offer", "offers", "ERR_OFFER_NOT_FOUND"),
    ("case", "cases", "ERR_RELOCATION_CASE_NOT_FOUND"),
    ("closing", "closings", "ERR_CLOSING_NOT_FOUND"),
    ("contractor", "contractors", "ERR_CONTRACTOR_NOT_FOUND"),
    ("work_order", "work_orders", "ERR_WORK_ORDER_NOT_FOUND"),
    ("disconnection", "disconnections", "ERR_DISCONNECTION_NOT_FOUND"),
    ("restriction", "restrictions", "ERR_DEED_RESTRICTION_NOT_FOUND"),
    ("entry", "ledger", "ERR_LEDGER_ENTRY_NOT_FOUND"),
    ("adjacency", "adjacencies", "ERR_ADJACENCY_NOT_FOUND"),
    ("inspection", "inspections", "ERR_INSPECTION_NOT_FOUND"),
]


def _make(table_name, error_id):
    def getter(record_id):
        table = getattr(store, table_name)
        record = table.get(record_id) if isinstance(record_id, str) else None
        if record is None:
            fail(error_id)
        return record
    return getter


get_project = _make("projects", "ERR_PROJECT_NOT_FOUND")
get_bca = _make("bcas", "ERR_BCA_NOT_FOUND")
get_parcel = _make("parcels", "ERR_PARCEL_NOT_FOUND")
get_appraisal = _make("appraisals", "ERR_APPRAISAL_NOT_FOUND")
get_dob_record = _make("dob_records", "ERR_DOB_RECORD_NOT_FOUND")
get_offer = _make("offers", "ERR_OFFER_NOT_FOUND")
get_case = _make("cases", "ERR_RELOCATION_CASE_NOT_FOUND")
get_closing = _make("closings", "ERR_CLOSING_NOT_FOUND")
get_contractor = _make("contractors", "ERR_CONTRACTOR_NOT_FOUND")
get_work_order = _make("work_orders", "ERR_WORK_ORDER_NOT_FOUND")
get_disconnection = _make("disconnections", "ERR_DISCONNECTION_NOT_FOUND")
get_restriction = _make("restrictions", "ERR_DEED_RESTRICTION_NOT_FOUND")
get_entry = _make("ledger", "ERR_LEDGER_ENTRY_NOT_FOUND")
get_adjacency = _make("adjacencies", "ERR_ADJACENCY_NOT_FOUND")
get_inspection = _make("inspections", "ERR_INSPECTION_NOT_FOUND")


def project_of_parcel(parcel):
    return store.projects.get(parcel["project_id"])


def project_of_appraisal(appraisal):
    parcel = store.parcels.get(appraisal["parcel_id"])
    return project_of_parcel(parcel) if parcel else None


def project_of_offer(offer):
    parcel = store.parcels.get(offer["parcel_id"])
    return project_of_parcel(parcel) if parcel else None


def project_of_closing(closing):
    parcel = store.parcels.get(closing["parcel_id"])
    return project_of_parcel(parcel) if parcel else None


def project_of_work_order(work_order):
    parcel = store.parcels.get(work_order["parcel_id"])
    return project_of_parcel(parcel) if parcel else None


def project_of_restriction(restriction):
    parcel = store.parcels.get(restriction["parcel_id"])
    return project_of_parcel(parcel) if parcel else None

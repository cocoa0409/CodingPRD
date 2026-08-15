"""TestYearEntry endpoints (PRD 3.1)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_CASE_STATE,
    ERR_INVALID_ENTRY_STATE,
    ERR_UNRESOLVED_ENTRY_ADJUSTMENTS,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_arg
from services.core import new_record, public, touch
from validate import (
    get_body,
    no_unknown_fields,
    req_enum,
    req_int,
    req_str,
    require_fk,
    require_path_resource,
)

bp = Blueprint("test_year_entries", __name__)

_EDITABLE_CASE_STATES = ("DRAFT", "DEFICIENT")


@bp.post("/test-year-entries")
def create_entry():
    body = get_body()
    no_unknown_fields(body, {"rate_case_id", "account_code", "category", "booked_amount_cents"})
    rate_case_id = req_str(body, "rate_case_id")
    account_code = req_str(body, "account_code")
    category = req_enum(body, "category", ("O_AND_M", "DEPRECIATION", "TAXES"))
    booked = req_int(body, "booked_amount_cents", non_negative=True)
    authorized(["UtilityFiler"])
    case = require_fk("rate_cases", rate_case_id, "rate_case_id")
    if case["status"] not in _EDITABLE_CASE_STATES:
        raise_error(ERR_INVALID_CASE_STATE, "entries may be added only while the case is DRAFT or DEFICIENT")
    rec = new_record("test_year_entries", {
        "rate_case_id": rate_case_id,
        "account_code": account_code,
        "category": category,
        "booked_amount_cents": booked,
        "adjusted_amount_cents": booked,
        "status": "DRAFT",
    })
    return success_object(public(rec), status=201)


@bp.get("/test-year-entries")
def list_entries():
    filters = {
        "rate_case_id": query_arg("rate_case_id"),
        "status": query_arg("status"),
    }
    return list_response("test_year_entries", filters)


@bp.get("/test-year-entries/<entry_id>")
def get_entry(entry_id):
    return get_one("test_year_entries", entry_id)


def _entry_and_case(entry_id):
    entry = require_path_resource("test_year_entries", entry_id)
    case = db["rate_cases"].get(entry["rate_case_id"])
    return entry, case


@bp.post("/test-year-entries/<entry_id>/submit")
def submit_entry(entry_id):
    body = get_body()
    no_unknown_fields(body, set())
    authorized(["UtilityFiler"])
    entry, case = _entry_and_case(entry_id)
    if entry["status"] != "DRAFT":
        raise_error(ERR_INVALID_ENTRY_STATE, "submit requires DRAFT")
    if case is None or case["status"] not in _EDITABLE_CASE_STATES:
        raise_error(ERR_INVALID_CASE_STATE, "case must be DRAFT or DEFICIENT")
    entry["status"] = "SUBMITTED"
    touch(entry)
    return success_object(public(entry))


@bp.post("/test-year-entries/<entry_id>/reopen")
def reopen_entry(entry_id):
    body = get_body()
    no_unknown_fields(body, set())
    authorized(["UtilityFiler"])
    entry, case = _entry_and_case(entry_id)
    if entry["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_ENTRY_STATE, "reopen requires SUBMITTED")
    if case is None or case["status"] not in _EDITABLE_CASE_STATES:
        raise_error(ERR_INVALID_CASE_STATE, "case must be DRAFT or DEFICIENT")
    entry["status"] = "DRAFT"
    touch(entry)
    return success_object(public(entry))


@bp.post("/test-year-entries/<entry_id>/lock")
def lock_entry(entry_id):
    body = get_body()
    no_unknown_fields(body, set())
    authorized(["UtilityFiler"])
    entry, case = _entry_and_case(entry_id)
    if entry["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_ENTRY_STATE, "lock requires SUBMITTED")
    if case is None or case["status"] not in _EDITABLE_CASE_STATES:
        raise_error(ERR_INVALID_CASE_STATE, "case must be DRAFT or DEFICIENT")
    # DISPUTED adjustments block the lock; PROPOSED do not (PRD 3.1)
    if any(
        a["test_year_entry_id"] == entry["id"] and a["status"] == "DISPUTED"
        for a in db["adjustments"].values()
    ):
        raise_error(ERR_UNRESOLVED_ENTRY_ADJUSTMENTS,
                    "a DISPUTED adjustment targets this entry")
    entry["status"] = "LOCKED"
    touch(entry)
    return success_object(public(entry))

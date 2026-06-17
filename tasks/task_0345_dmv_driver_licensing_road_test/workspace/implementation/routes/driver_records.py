"""Driver record endpoints and sub-resource discovery lists."""
from flask import Blueprint

import db
from db import db as store
from errors import err
from middleware import get_user_context, require_role
from response import success
from services import serialize
from services.common import (
    new_common, touch, get_json_body, paginate, require_fields, require_str,
    opt_bool,
)
from services.lookup import fetch

bp = Blueprint("driver_records", __name__)


@bp.post("/driver-records")
def create_driver_record():
    _, role = get_user_context()
    require_role(role, {"LicenseClerk"})
    body = get_json_body()
    require_fields(body, ["full_name", "date_of_birth", "state_code"])
    full_name = require_str(body, "full_name")
    date_of_birth = require_str(body, "date_of_birth")
    state_code = require_str(body, "state_code")
    organ_donor = opt_bool(body, "organ_donor", False)
    voter = opt_bool(body, "voter_registration_opt_in", False)

    record = new_common(
        full_name=full_name,
        date_of_birth=date_of_birth,
        state_code=state_code,
        licensing_status="UNLICENSED",
        cdl_status="NONE",
        real_id_status="NONE",
        real_id_categories_met=0,
        organ_donor=organ_donor,
        voter_registration_opt_in=voter,
    )
    store.driver_records[record["id"]] = record
    return success(serialize.driver_record(record, store), 201, "object")


@bp.get("/driver-records/<rid>")
def get_driver_record(rid):
    _, role = get_user_context()
    require_role(role, {"LicenseClerk", "AdjudicationOfficer", "Examiner", "KnowledgeProctor"})
    record = fetch(store.driver_records, rid)
    return success(serialize.driver_record(record, store), 200, "object")


@bp.post("/driver-records/<rid>/opt-in")
def opt_in(rid):
    _, role = get_user_context()
    require_role(role, {"LicenseClerk"})
    record = fetch(store.driver_records, rid)
    body = get_json_body()
    changed = False
    if "organ_donor" in body and body["organ_donor"] is not None:
        record["organ_donor"] = opt_bool(body, "organ_donor")
        changed = True
    if "voter_registration_opt_in" in body and body["voter_registration_opt_in"] is not None:
        record["voter_registration_opt_in"] = opt_bool(body, "voter_registration_opt_in")
        changed = True
    # version increments by one (PRD 3.1) on this lifecycle event.
    touch(record)
    return success(serialize.driver_record(record, store), 200, "object")


@bp.post("/driver-records/<rid>/real-id-submit")
def real_id_submit(rid):
    _, role = get_user_context()
    require_role(role, {"LicenseClerk"})
    record = fetch(store.driver_records, rid)
    body = get_json_body()
    require_fields(body, ["documents"])
    documents = body["documents"]
    if not isinstance(documents, list):
        raise err("ERR_INVALID_REQUEST", "documents must be an array")
    categories = set()
    for doc in documents:
        if not isinstance(doc, dict):
            raise err("ERR_INVALID_REQUEST", "each document must be an object")
        cat = doc.get("category")
        if cat in db.REAL_ID_CATEGORIES:
            categories.add(cat)
    record["real_id_categories_met"] = len(categories)
    record["real_id_status"] = "SUBMITTED"
    touch(record)
    return success(serialize.driver_record(record, store), 200, "object")


@bp.post("/driver-records/<rid>/real-id-adjudicate")
def real_id_adjudicate(rid):
    _, role = get_user_context()
    require_role(role, {"LicenseClerk"})
    record = fetch(store.driver_records, rid)
    body = get_json_body()
    require_fields(body, ["decision"])
    decision = body["decision"]
    if decision not in ("APPROVE", "REJECT"):
        raise err("ERR_INVALID_REQUEST", "decision must be APPROVE or REJECT")
    if decision == "APPROVE":
        if record["real_id_categories_met"] != 3:
            raise err("ERR_INSUFFICIENT_DOCUMENTS",
                      "REAL ID approval requires all 3 document categories")
        record["real_id_status"] = "APPROVED"
    else:
        record["real_id_status"] = "REJECTED"
    touch(record)
    return success(serialize.driver_record(record, store), 200, "object")


@bp.post("/driver-records/<rid>/cdl-reinstate")
def cdl_reinstate(rid):
    _, role = get_user_context()
    require_role(role, {"LicenseClerk"})
    record = fetch(store.driver_records, rid)
    if record["cdl_status"] != "MEDICALLY_DOWNGRADED":
        raise err("ERR_CDL_NOT_DOWNGRADED",
                  "cdl-reinstate requires cdl_status == MEDICALLY_DOWNGRADED")
    cur = store.current_period
    has_valid = any(
        m["driver_record_id"] == rid and m["status"] == "VALID"
        and m["valid_through_period"] >= cur
        for m in store.medical_cards.values()
    )
    if not has_valid:
        raise err("ERR_NO_VALID_MEDICAL_CARD",
                  "A VALID medical card covering current clock is required")
    record["cdl_status"] = "ACTIVE"
    for c in store.cdl_endorsements.values():
        if c["driver_record_id"] == rid and c["status"] == "SUSPENDED":
            c["status"] = "GRANTED"
            touch(c)
    touch(record)
    return success(serialize.driver_record(record, store), 200, "object")


@bp.post("/driver-records/<rid>/revoke")
def revoke(rid):
    _, role = get_user_context()
    require_role(role, {"AdjudicationOfficer"})
    record = fetch(store.driver_records, rid)
    get_json_body()  # reason is accepted but not otherwise used
    if record["licensing_status"] != "SUSPENDED":
        raise err("ERR_RECORD_NOT_SUSPENDED", "Revocation requires SUSPENDED record")
    from services import calculations as calc
    if calc.prior_suspension_count(record, store) < db.REVOCATION_PRIOR_THRESHOLD:
        raise err("ERR_REVOCATION_THRESHOLD_NOT_MET",
                  "prior_suspension_count below revocation threshold")
    record["licensing_status"] = "REVOKED"
    for l in store.licenses.values():
        if l["driver_record_id"] == rid and l["status"] == "ISSUED":
            l["status"] = "VOID"
            touch(l)
    for c in store.cdl_endorsements.values():
        if c["driver_record_id"] == rid and c["status"] in ("GRANTED", "SUSPENDED"):
            c["status"] = "WITHDRAWN"
            touch(c)
    touch(record)
    return success(serialize.driver_record(record, store), 200, "object")


# --- Sub-resource discovery lists (FK reverse-reachability) ---

def _filter_by_record(collection, rid):
    from flask import request
    status = request.args.get("status")
    items = [
        e for e in collection.values()
        if e["driver_record_id"] == rid
        and (status is None or e["status"] == status)
    ]
    return items


def _list_sub(rid, collection, serializer, allowed):
    _, role = get_user_context()
    require_role(role, allowed)
    fetch(store.driver_records, rid)
    items = _filter_by_record(collection, rid)
    data, pagination = paginate(items, serializer)
    return success(data, 200, "array", pagination)


@bp.get("/driver-records/<rid>/knowledge-tests")
def list_knowledge_tests(rid):
    return _list_sub(rid, store.knowledge_tests, serialize.knowledge_test,
                     {"LicenseClerk", "AdjudicationOfficer", "KnowledgeProctor"})


@bp.get("/driver-records/<rid>/road-test-appointments")
def list_road_tests(rid):
    return _list_sub(rid, store.road_test_appointments, serialize.road_test_appointment,
                     {"LicenseClerk", "AdjudicationOfficer", "Examiner"})


@bp.get("/driver-records/<rid>/licenses")
def list_licenses(rid):
    return _list_sub(rid, store.licenses, serialize.license_obj,
                     {"LicenseClerk", "AdjudicationOfficer", "Examiner"})


@bp.get("/driver-records/<rid>/violations")
def list_violations(rid):
    return _list_sub(rid, store.violations, serialize.violation,
                     {"AdjudicationOfficer", "LicenseClerk"})


@bp.get("/driver-records/<rid>/suspensions")
def list_suspensions(rid):
    return _list_sub(rid, store.suspensions, serialize.suspension,
                     {"AdjudicationOfficer", "LicenseClerk"})


@bp.get("/driver-records/<rid>/cdl-endorsements")
def list_cdl(rid):
    return _list_sub(rid, store.cdl_endorsements, serialize.cdl_endorsement,
                     {"LicenseClerk", "AdjudicationOfficer"})


@bp.get("/driver-records/<rid>/medical-cards")
def list_medical(rid):
    return _list_sub(rid, store.medical_cards, serialize.medical_card,
                     {"LicenseClerk", "AdjudicationOfficer"})


@bp.get("/driver-records/<rid>/fee-payments")
def list_fees(rid):
    from flask import request
    _, role = get_user_context()
    require_role(role, {"LicenseClerk", "AdjudicationOfficer"})
    fetch(store.driver_records, rid)
    status = request.args.get("status")
    purpose = request.args.get("purpose")
    items = [
        e for e in store.fee_payments.values()
        if e["driver_record_id"] == rid
        and (status is None or e["status"] == status)
        and (purpose is None or e["purpose"] == purpose)
    ]
    data, pagination = paginate(items, serialize.fee_payment)
    return success(data, 200, "array", pagination)

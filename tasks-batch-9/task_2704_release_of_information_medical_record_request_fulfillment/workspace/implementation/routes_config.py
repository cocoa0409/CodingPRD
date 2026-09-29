"""Fee schedules, facilities, patients, requesting parties and the logical clock."""

import re

from flask import Blueprint, request

import store
import validation as v
from envelope import created, ok, ok_list
from errors import ApiError
from security import STAFF, ALL_ROLES, actor

bp = Blueprint("config", __name__)

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")

MONEY_FIELDS = [
    "base_retrieval_fee_cents", "tier1_per_page_millicents", "tier2_per_page_millicents",
    "patient_access_per_page_millicents", "certification_fee_cents", "media_fee_cents",
    "postage_per_delivery_cents", "electronic_delivery_total_cap_cents",
    "total_fee_cap_cents", "penalty_per_day_cents", "penalty_cap_cents",
]


# ============================================================ state fee rules
@bp.post("/roi/state-fee-rules")
def create_state_fee_rule():
    actor(["PlatformAdmin"])
    body = v.body()

    state_code = v.req_str(body, "state_code", max_len=2, min_len=2)
    if not STATE_CODE_RE.match(state_code):
        v.bad()
    rule = store.common_fields()
    rule["state_code"] = state_code
    rule["base_retrieval_fee_cents"] = v.req_int(body, "base_retrieval_fee_cents")
    rule["tier1_page_limit"] = v.req_int(body, "tier1_page_limit", minimum=1)
    rule["tier1_per_page_millicents"] = v.req_int(body, "tier1_per_page_millicents")
    rule["tier2_per_page_millicents"] = v.req_int(body, "tier2_per_page_millicents")
    rule["patient_access_per_page_millicents"] = v.req_int(body, "patient_access_per_page_millicents")
    rule["certification_fee_cents"] = v.req_int(body, "certification_fee_cents")
    rule["media_fee_cents"] = v.req_int(body, "media_fee_cents")
    rule["postage_per_delivery_cents"] = v.req_int(body, "postage_per_delivery_cents")
    rule["electronic_delivery_total_cap_cents"] = v.req_int(body, "electronic_delivery_total_cap_cents")
    rule["total_fee_cap_cents"] = v.req_int(body, "total_fee_cap_cents")
    rule["patient_access_deadline_days"] = v.req_int(body, "patient_access_deadline_days", minimum=1)
    rule["third_party_deadline_days"] = v.req_int(body, "third_party_deadline_days", minimum=1)
    rule["extension_days"] = v.req_int(body, "extension_days")
    rule["penalty_per_day_cents"] = v.req_int(body, "penalty_per_day_cents")
    rule["penalty_cap_cents"] = v.req_int(body, "penalty_cap_cents")
    rule["fee_forfeiture_on_late"] = v.req_bool(body, "fee_forfeiture_on_late")

    for existing in store.state_fee_rules.values():
        if existing["state_code"] == state_code:
            raise ApiError("ERR_DUPLICATE_STATE_FEE_RULE")

    store.state_fee_rules[rule["id"]] = rule
    return created(store.public(rule))


@bp.get("/roi/state-fee-rules")
def list_state_fee_rules():
    actor(STAFF)
    limit, offset = v.paging()
    rows = store.ordered(list(store.state_fee_rules.values()))
    state_code = request.args.get("state_code")
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]
    data, total = v.page(rows, limit, offset)
    return ok_list(data, limit, offset, total)


# ============================================================ facilities
@bp.post("/roi/facilities")
def create_facility():
    actor(["PlatformAdmin"])
    body = v.body()

    fac = store.common_fields()
    fac["name"] = v.req_str(body, "name", max_len=120)
    fac["state_fee_rule_id"] = v.req_id(body, "state_fee_rule_id")
    fac["legacy_archive_enabled"] = v.opt_bool(body, "legacy_archive_enabled", False)
    fac["legacy_retrieval_surcharge_cents"] = v.opt_int(body, "legacy_retrieval_surcharge_cents", default=0)
    fac["legacy_gateway_job_minutes"] = v.opt_int(body, "legacy_gateway_job_minutes", minimum=1, default=30)
    fac["legacy_gateway_buffer_minutes"] = v.opt_int(body, "legacy_gateway_buffer_minutes", default=10)
    fac["sensitive_categories_requiring_specific_authorization"] = v.opt_enum_array(
        body, "sensitive_categories_requiring_specific_authorization",
        store.CATEGORIES, default=store.PROTECTED_CATEGORIES,
    )
    fac["status"] = "ACTIVE"
    fac["receivable_cents"] = 0
    fac["collected_cents"] = 0
    fac["written_off_cents"] = 0
    fac["penalty_exposure_cents"] = 0

    if fac["state_fee_rule_id"] not in store.state_fee_rules:
        raise ApiError("ERR_STATE_FEE_RULE_NOT_FOUND")

    store.facilities[fac["id"]] = fac
    return created(store.public(fac))


@bp.get("/roi/facilities/<id>")
def read_facility(id):
    actor(STAFF)
    fac = store.facilities.get(id)
    if fac is None:
        raise ApiError("ERR_FACILITY_NOT_FOUND")
    return ok(store.public(fac))


@bp.get("/roi/facilities")
def list_facilities():
    actor(STAFF)
    limit, offset = v.paging()
    rows = store.ordered(list(store.facilities.values()))
    rule_id = request.args.get("state_fee_rule_id")
    if rule_id is not None:
        rows = [r for r in rows if r["state_fee_rule_id"] == rule_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    data, total = v.page(rows, limit, offset)
    return ok_list(data, limit, offset, total)


@bp.post("/roi/facilities/<id>/status")
def set_facility_status(id):
    actor(["PlatformAdmin"])
    body = v.body()
    status = v.req_enum(body, "status", ["ACTIVE", "SUSPENDED"])
    v.opt_str(body, "reason", max_len=500)

    fac = store.facilities.get(id)
    if fac is None:
        raise ApiError("ERR_FACILITY_NOT_FOUND")

    fac["status"] = status
    store.touch(fac)
    return ok(store.public(fac))


# ============================================================ patients
@bp.post("/roi/patients")
def create_patient():
    actor(["FacilityAdmin", "PlatformAdmin"])
    body = v.body()

    pat = store.common_fields()
    pat["facility_id"] = v.req_id(body, "facility_id")
    pat["mrn"] = v.req_str(body, "mrn", max_len=32)
    pat["full_name"] = v.req_str(body, "full_name", max_len=120)
    pat["date_of_birth"] = v.req_date(body, "date_of_birth")[0]
    pat["is_minor"] = v.opt_bool(body, "is_minor", False)
    pat["deceased"] = v.opt_bool(body, "deceased", False)

    if pat["facility_id"] not in store.facilities:
        raise ApiError("ERR_FACILITY_NOT_FOUND")

    for existing in store.patients.values():
        if existing["facility_id"] == pat["facility_id"] and existing["mrn"] == pat["mrn"]:
            raise ApiError("ERR_DUPLICATE_MRN")

    store.patients[pat["id"]] = pat
    return created(store.public(pat))


@bp.get("/roi/patients/<id>")
def read_patient(id):
    actor(STAFF)
    pat = store.patients.get(id)
    if pat is None:
        raise ApiError("ERR_PATIENT_NOT_FOUND")
    return ok(store.public(pat))


@bp.get("/roi/patients")
def list_patients():
    actor(STAFF)
    limit, offset = v.paging()
    rows = store.ordered(list(store.patients.values()))
    facility_id = request.args.get("facility_id")
    if facility_id is not None:
        rows = [r for r in rows if r["facility_id"] == facility_id]
    mrn = request.args.get("mrn")
    if mrn is not None:
        rows = [r for r in rows if r["mrn"] == mrn]
    data, total = v.page(rows, limit, offset)
    return ok_list(data, limit, offset, total)


# ============================================================ requesting parties
@bp.post("/roi/requesters")
def create_requester():
    actor(["IntakeSpecialist", "PlatformAdmin"])
    body = v.body()

    req = store.common_fields()
    req["requester_type"] = v.req_enum(body, "requester_type", store.REQUESTER_TYPES)
    req["organization_name"] = v.opt_str(body, "organization_name", max_len=200)
    contact_email = v.req_str(body, "contact_email", max_len=200)
    if "@" not in contact_email:
        v.bad()
    req["contact_email"] = contact_email
    req["credential_number"] = v.opt_str(body, "credential_number", max_len=100)
    if req["requester_type"] == "PATIENT":
        req["patient_id"] = v.req_id(body, "patient_id")
    else:
        req["patient_id"] = v.opt_id(body, "patient_id")
    req["signature_on_file"] = v.opt_bool(body, "signature_on_file", False)

    if req["patient_id"] is not None and req["patient_id"] not in store.patients:
        raise ApiError("ERR_PATIENT_NOT_FOUND")

    store.requesters[req["id"]] = req
    return created(store.public(req))


@bp.get("/roi/requesters/<id>")
def read_requester(id):
    actor(ALL_ROLES)
    req = store.requesters.get(id)
    if req is None:
        raise ApiError("ERR_REQUESTER_NOT_FOUND")
    return ok(store.public(req))


@bp.get("/roi/requesters")
def list_requesters():
    actor(STAFF)
    limit, offset = v.paging()
    rows = store.ordered(list(store.requesters.values()))
    requester_type = request.args.get("requester_type")
    if requester_type is not None:
        rows = [r for r in rows if r["requester_type"] == requester_type]
    patient_id = request.args.get("patient_id")
    if patient_id is not None:
        rows = [r for r in rows if r["patient_id"] == patient_id]
    data, total = v.page(rows, limit, offset)
    return ok_list(data, limit, offset, total)


# ============================================================ logical clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    actor(["PlatformAdmin"])
    body = v.body()
    _, parsed = v.req_datetime(body, "to_iso8601")
    store.set_clock(parsed)
    return ok({"current_utc": store.fmt(parsed)})

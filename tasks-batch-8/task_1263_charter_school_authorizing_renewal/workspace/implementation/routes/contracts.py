"""Charter contracts and performance targets (PRD §3.2)."""
from flask import Blueprint, request

import db
import errors
from errors import raise_error
from middleware import (
    ALL_ROLES,
    body,
    require_field,
    require_non_empty_string,
    require_number,
    require_roles,
)
from response import success_object
from routes.common import filter_eq, get_or_404, paginate

bp = Blueprint("contracts", __name__)


@bp.post("/authorizer/schools/<id>/contracts")
def create_contract(id):
    require_roles(["AuthorizerStaff"])
    school = get_or_404("schools", id)
    data = body()
    framework_version = require_non_empty_string(data, "framework_version")
    term_start = require_non_empty_string(data, "term_start")
    term_end = require_non_empty_string(data, "term_end")
    prior_contract_id = data.get("prior_contract_id")
    if prior_contract_id is not None:
        if not isinstance(prior_contract_id, str):
            raise_error(errors.ERR_INVALID_REQUEST, "prior_contract_id must be a string or null")
        get_or_404("contracts", prior_contract_id)
    expected_school_version = require_field(data, "expected_school_version")
    if isinstance(expected_school_version, bool) or not isinstance(expected_school_version, int):
        raise_error(errors.ERR_INVALID_REQUEST, "expected_school_version must be an integer")
    # OCC layer 3.6 (§2.7)
    if expected_school_version != school["version"]:
        raise_error(errors.ERR_STALE_SCHOOL_VERSION, "expected_school_version does not match school.version")
    from clock import parse as parse_iso
    try:
        start = parse_iso(term_start)
        end = parse_iso(term_end)
    except ValueError:
        raise_error(errors.ERR_INVALID_REQUEST, "Invalid term_start/term_end")
    if start >= end:
        raise_error(errors.ERR_INVALID_REQUEST, "term_start must be earlier than term_end")
    # Closed-interval overlap with sibling DRAFT/ACTIVE terms (start == sibling
    # end IS overlap).
    for sibling in db.all_records("contracts"):
        if sibling["school_id"] != id:
            continue
        if sibling["status"] not in ("DRAFT", "ACTIVE"):
            continue
        s_start = parse_iso(sibling["term_start"])
        s_end = parse_iso(sibling["term_end"])
        if start <= s_end and s_start <= end:
            raise_error(errors.ERR_CONTRACT_TERM_OVERLAP, "Term overlaps a sibling DRAFT/ACTIVE contract")
    record = db.stamp_new({
        "school_id": id,
        "prior_contract_id": prior_contract_id,
        "framework_version": framework_version,
        "term_start": term_start,
        "term_end": term_end,
        "status": "DRAFT",
        "targets_weight_total": 0,
    })
    db.insert("contracts", record)
    # Contract create is a version-advancing write on the school (§2.7).
    db.touch(school)
    return success_object(record, 201)


@bp.get("/authorizer/contracts")
def list_contracts():
    require_roles(ALL_ROLES)
    records = db.all_records("contracts")
    records = filter_eq(records, "school_id", request.args.get("school_id"))
    records = filter_eq(records, "prior_contract_id", request.args.get("prior_contract_id"))
    records = filter_eq(records, "status", request.args.get("status"))
    return paginate(records)


@bp.get("/authorizer/contracts/<id>")
def get_contract(id):
    require_roles(ALL_ROLES)
    return success_object(get_or_404("contracts", id))


@bp.post("/authorizer/contracts/<id>/targets")
def add_target(id):
    require_roles(["AuthorizerStaff"])
    contract = get_or_404("contracts", id)
    if contract["status"] != "DRAFT":
        raise_error(errors.ERR_CONTRACT_INVALID_STATE, "Targets may be added only while DRAFT")
    data = body()
    domain = require_non_empty_string(data, "domain")
    if domain not in ("ACADEMIC", "FINANCIAL", "OPERATIONAL"):
        raise_error(errors.ERR_INVALID_REQUEST, "domain must be ACADEMIC|FINANCIAL|OPERATIONAL")
    metric_code = require_non_empty_string(data, "metric_code")
    target_value = require_number(data, "target_value")
    floor_value = require_number(data, "floor_value")
    weight = require_number(data, "weight")
    if weight <= 0 or weight > 1:
        raise_error(errors.ERR_INVALID_REQUEST, "weight must be > 0 and <= 1")
    for t in db.all_records("targets"):
        if (
            t["contract_id"] == id
            and t["domain"] == domain
            and t["metric_code"] == metric_code
        ):
            raise_error(errors.ERR_DUPLICATE_RECORD, "Duplicate (contract, domain, metric_code) target")
    record = db.stamp_new({
        "contract_id": id,
        "domain": domain,
        "metric_code": metric_code,
        "target_value": target_value,
        "floor_value": floor_value,
        "weight": weight,
    })
    db.insert("targets", record)
    # Recompute contract.targets_weight_total (running sum of targets' weights).
    total = sum(
        t["weight"] for t in db.all_records("targets") if t["contract_id"] == id
    )
    contract["targets_weight_total"] = total
    db.touch(contract)
    return success_object(record, 201)


@bp.get("/authorizer/contracts/<id>/targets")
def list_targets(id):
    require_roles(ALL_ROLES)
    get_or_404("contracts", id)
    records = [t for t in db.all_records("targets") if t["contract_id"] == id]
    return paginate(records)


@bp.post("/authorizer/contracts/<id>/activate")
def activate_contract(id):
    require_roles(["AuthorizerStaff"])
    contract = get_or_404("contracts", id)
    if contract["status"] != "DRAFT":
        raise_error(errors.ERR_CONTRACT_INVALID_STATE, "Only a DRAFT contract can activate")
    targets = [t for t in db.all_records("targets") if t["contract_id"] == id]
    domains = {t["domain"] for t in targets}
    if not {"ACADEMIC", "FINANCIAL", "OPERATIONAL"} <= domains:
        raise_error(errors.ERR_DOMAIN_TARGET_MISSING, "Each domain must carry at least one target")
    from decimal import Decimal
    total = sum(Decimal(str(t["weight"])) for t in targets)
    if total != Decimal("1.0"):
        raise_error(errors.ERR_TARGET_WEIGHT_TOTAL_INVALID, "Target weights must sum to exactly 1.0")
    school = get_or_404("schools", contract["school_id"])
    if school["status"] not in ("PRE_OPENING", "OPEN"):
        raise_error(errors.ERR_SCHOOL_NOT_OPEN, "School must be PRE_OPENING or OPEN to activate")
    # Supersede any other ACTIVE contract for the school.
    for sibling in db.all_records("contracts"):
        if sibling["school_id"] == school["id"] and sibling["status"] == "ACTIVE":
            sibling["status"] = "SUPERSEDED"
            db.touch(sibling)
    contract["status"] = "ACTIVE"
    db.touch(contract)
    school["current_contract_id"] = contract["id"]
    if school["status"] == "PRE_OPENING":
        school["status"] = "OPEN"
    db.touch(school)
    return success_object(contract)

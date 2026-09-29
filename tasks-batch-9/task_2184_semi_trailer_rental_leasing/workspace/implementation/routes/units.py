"""Contract unit lines and damage-assessment creation."""

from flask import Blueprint

import calc
import envelope
import serializers
import services
import store
import validate
from auth import ALL_ROLES, authenticate, require_owner
from errors import fail

bp = Blueprint("units", __name__)

UNIT_STATUSES = ("ALLOCATED", "OUT", "RETURNED", "SETTLED", "SWAPPED_OUT", "RELEASED")
SEVERITIES = ("MINOR", "MODERATE", "MAJOR")


@bp.get("/fleet/agreement-units/<agreement_unit_id>")
def read_unit(agreement_unit_id):
    authenticate(ALL_ROLES)
    return envelope.ok(serializers.agreement_unit(services.get_agreement_unit(agreement_unit_id)))


@bp.get("/fleet/agreement-units")
def list_units():
    authenticate(ALL_ROLES)
    limit, offset = validate.pagination()
    agreement_id = validate.query("agreement_id")
    trailer_id = validate.query("trailer_id")
    return_branch_id = validate.query("return_branch_id")
    status = validate.query_enum("status", UNIT_STATUSES)

    rows = []
    for u in store.agreement_units.values():
        if agreement_id is not None and u["agreement_id"] != agreement_id:
            continue
        if trailer_id is not None and u["trailer_id"] != trailer_id:
            continue
        if return_branch_id is not None and u.get("return_branch_id") != return_branch_id:
            continue
        if status is not None and u["status"] != status:
            continue
        rows.append(u)
    rows = store.sorted_rows(rows)
    page = validate.paginate(rows, limit, offset)
    return envelope.listing([serializers.agreement_unit(r) for r in page], limit, offset, len(rows))


@bp.post("/fleet/agreement-units/<agreement_unit_id>/return")
def return_unit(agreement_unit_id):
    caller = authenticate(["FleetAdmin", "BranchManager"])
    unit = services.get_agreement_unit(agreement_unit_id)
    payload = validate.body()
    if validate.present(payload, "return_branch_id") and isinstance(payload["return_branch_id"], str):
        services.get_branch(payload["return_branch_id"])

    return_branch_id = validate.req_string(payload, "return_branch_id")
    return_hub_miles = validate.req_int(payload, "return_hub_miles", minimum=0)
    return_date = validate.req_date(payload, "return_date")

    checkout_miles = unit.get("checkout_hub_miles")
    if checkout_miles is not None and return_hub_miles < checkout_miles:
        fail("ERR_INVALID_REQUEST", "return_hub_miles cannot be lower than checkout_hub_miles")
    checkout_date = store.parse_date(unit.get("checkout_date"))
    if checkout_date is not None and return_date <= checkout_date:
        fail("ERR_INVALID_DATE_RANGE", "return_date must be strictly after checkout_date")

    if caller.is_branch_manager:
        require_owner(caller, return_branch_id)

    if unit["status"] != "OUT":
        fail("ERR_UNIT_NOT_OUT", "Unit is not out with a customer")

    unit["status"] = "RETURNED"
    unit["return_branch_id"] = return_branch_id
    unit["return_date"] = return_date.isoformat()
    unit["return_hub_miles"] = return_hub_miles
    store.touch(unit)

    trailer = store.trailers.get(unit["trailer_id"])
    if trailer is not None:
        trailer["hub_miles"] = return_hub_miles
        trailer["current_branch_id"] = return_branch_id
        if trailer["availability_status"] in ("ON_RENT", "ON_LEASE"):
            trailer["availability_status"] = "AVAILABLE"
        store.touch(trailer)

    agreement = store.agreements.get(unit["agreement_id"])
    if agreement is not None and agreement["status"] == "ACTIVE":
        siblings = services.units_of_agreement(agreement["id"])
        still_out = [u for u in siblings if u["status"] == "OUT"]
        returned = [u for u in siblings if u["status"] == "RETURNED"]
        if not still_out and returned:
            agreement["status"] = "PENDING_SETTLEMENT"
            store.touch(agreement)

    return envelope.ok(serializers.agreement_unit(unit))


def _validate_line_items(payload):
    if not validate.present(payload, "line_items"):
        fail("ERR_INVALID_REQUEST", "line_items is required")
    items = payload["line_items"]
    if not isinstance(items, list) or len(items) == 0:
        fail("ERR_INVALID_REQUEST", "line_items must be a non-empty array")
    cleaned = []
    for item in items:
        if not isinstance(item, dict):
            fail("ERR_INVALID_REQUEST", "each line item must be an object")
        severity = validate.req_enum(item, "severity", SEVERITIES)
        quantity = validate.req_int(item, "quantity", minimum=1)
        unit_cost = validate.req_int(item, "unit_cost_cents", minimum=0)
        description = validate.opt_string(item, "description", "")
        cleaned.append({
            "severity": severity,
            "quantity": quantity,
            "unit_cost_cents": unit_cost,
            "description": description,
        })
    return cleaned


@bp.post("/fleet/agreement-units/<agreement_unit_id>/damage-assessments")
def create_assessment(agreement_unit_id):
    caller = authenticate(["Inspector"])
    unit = services.get_agreement_unit(agreement_unit_id)
    payload = validate.body()
    if validate.present(payload, "supersedes_assessment_id") and isinstance(payload["supersedes_assessment_id"], str):
        services.get_assessment(payload["supersedes_assessment_id"])

    line_items = _validate_line_items(payload)
    expected_version = validate.req_int(payload, "expected_agreement_unit_version")
    supersedes = validate.opt_string(payload, "supersedes_assessment_id")

    if expected_version != unit["version"]:
        fail("ERR_STALE_VERSION", "expected_agreement_unit_version does not match the unit version")

    rec = store.new_record()
    rec.update({
        "agreement_unit_id": unit["id"],
        "trailer_id": unit["trailer_id"],
        "supersedes_assessment_id": supersedes,
        "assessor_user_id": caller.user_id,
        "line_items": line_items,
        "status": "DRAFT",
        "assessed_amount_cents": None,
        "insured_portion_cents": None,
        "customer_liable_cents": None,
        "admin_fee_cents": None,
        "damage_points": None,
    })
    store.damage_assessments[rec["id"]] = rec
    store.touch(unit)
    return envelope.created(serializers.damage_assessment(rec))

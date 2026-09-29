"""ProductFamily, ProductVintage, FailureMode and ClaimObservation endpoints."""

from flask import Blueprint

import lookups
import store
from auth import authenticate
from errors import fail
from response import list_response, object_response
from serialize import dump, dump_many
from services import calc
from validation import Field, paginate, pagination, query_filter, validate_body

bp = Blueprint("catalog", __name__)

READ_ROLES = ("WarrantyAnalyst", "ReserveController", "QualityEngineer", "Actuary")

SEVERITIES = ("COSMETIC", "FUNCTIONAL", "SAFETY")


# ---------------------------------------------------------------------------
# ProductFamily
# ---------------------------------------------------------------------------
@bp.post("/warranty/product-families")
def create_family():
    authenticate(("WarrantyAnalyst",))
    values, _ = validate_body(
        [
            Field("family_code", "str"),
            Field("name", "str"),
            Field("launch_date", "date"),
            Field("base_warranty_months", "int", minimum=1),
            Field("standard_cost_per_claim_cents", "int", minimum=1),
            Field("reserve_cap_cents", "int", minimum=1),
            Field("engineering_estimate_rate_ppm", "int", required=False, minimum=0, nullable=True),
            Field("analog_family_id", "id", required=False, nullable=True),
        ]
    )
    if values["analog_family_id"] is not None:
        lookups.require_family(values["analog_family_id"])
    if any(f["family_code"] == values["family_code"] for f in store.all_rows("families")):
        fail("ERR_DUPLICATE_CODE")

    row = store.insert(
        "families",
        {
            "_kind": "ProductFamily",
            "family_code": values["family_code"],
            "name": values["name"],
            "launch_date": values["launch_date"],
            "base_warranty_months": values["base_warranty_months"],
            "standard_cost_per_claim_cents": values["standard_cost_per_claim_cents"],
            "engineering_estimate_rate_ppm": values["engineering_estimate_rate_ppm"],
            "analog_family_id": values["analog_family_id"],
            "reserve_cap_cents": values["reserve_cap_cents"],
            "observed_history_months": 0,
            "observed_exposure_units": 0,
            "units_sold_lifetime": 0,
            "history_maturity_status": "LIMITED",
            "warranty_reserve_balance_cents": 0,
            "reserve_posture": "NORMAL",
        },
    )
    calc.apply_history_maturity(row)
    calc.apply_balance_and_posture(row)
    return object_response(dump(row), 201)


@bp.patch("/warranty/product-families/<family_id>")
def patch_family(family_id):
    authenticate(("WarrantyAnalyst",))
    family = lookups.require_family(family_id)
    values, present = validate_body(
        [
            Field("name", "str", required=False),
            Field("base_warranty_months", "int", required=False, minimum=1),
            Field("standard_cost_per_claim_cents", "int", required=False, minimum=1),
            Field("engineering_estimate_rate_ppm", "int", required=False, minimum=0, nullable=True),
            Field("analog_family_id", "id", required=False, nullable=True),
            Field("reserve_cap_cents", "int", required=False, minimum=1),
        ]
    )
    if "analog_family_id" in present and values["analog_family_id"] is not None:
        lookups.require_family(values["analog_family_id"])
        if values["analog_family_id"] == family_id:
            fail("ERR_SELF_ANALOG_REFERENCE")

    for name in present:
        family[name] = values[name]
    calc.apply_history_maturity(family)
    calc.apply_posture_only(family)
    store.touch(family)
    return object_response(dump(family))


@bp.get("/warranty/product-families/<family_id>")
def read_family(family_id):
    authenticate(READ_ROLES)
    return object_response(dump(lookups.require_family(family_id)))


@bp.get("/warranty/product-families")
def list_families():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = store.all_rows("families")
    analog_family_id = query_filter("analog_family_id")
    if analog_family_id is not None:
        rows = [r for r in rows if r["analog_family_id"] == analog_family_id]
    maturity = query_filter("history_maturity_status")
    if maturity is not None:
        rows = [r for r in rows if r["history_maturity_status"] == maturity]
    return list_response(dump_many(paginate(rows, limit, offset)), limit, offset, len(rows))


# ---------------------------------------------------------------------------
# ProductVintage
# ---------------------------------------------------------------------------
@bp.post("/warranty/vintages")
def create_vintage():
    authenticate(("WarrantyAnalyst",))
    values, _ = validate_body(
        [
            Field("family_id", "id"),
            Field("vintage_code", "str"),
            Field("units_shipped", "int", minimum=1),
            Field("ship_period_code", "str"),
            Field("warranty_expiry_date", "date"),
        ]
    )
    family = lookups.require_family(values["family_id"])
    for existing in store.all_rows("vintages"):
        if (
            existing["family_id"] == values["family_id"]
            and existing["vintage_code"] == values["vintage_code"]
        ):
            fail("ERR_DUPLICATE_CODE")

    row = store.insert(
        "vintages",
        {
            "_kind": "ProductVintage",
            "family_id": values["family_id"],
            "vintage_code": values["vintage_code"],
            "units_shipped": values["units_shipped"],
            "ship_period_code": values["ship_period_code"],
            "warranty_expiry_date": values["warranty_expiry_date"],
            "exposure_status": "ACTIVE",
        },
    )
    calc.apply_exposure_status(row)
    if calc.apply_history_maturity(family):
        store.touch(family)
    return object_response(dump(row), 201)


@bp.get("/warranty/vintages/<vintage_id>")
def read_vintage(vintage_id):
    authenticate(READ_ROLES)
    return object_response(dump(lookups.require_vintage(vintage_id)))


@bp.get("/warranty/vintages")
def list_vintages():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = store.all_rows("vintages")
    family_id = query_filter("family_id")
    if family_id is not None:
        rows = [r for r in rows if r["family_id"] == family_id]
    exposure_status = query_filter("exposure_status")
    if exposure_status is not None:
        rows = [r for r in rows if r["exposure_status"] == exposure_status]
    return list_response(dump_many(paginate(rows, limit, offset)), limit, offset, len(rows))


# ---------------------------------------------------------------------------
# FailureMode
# ---------------------------------------------------------------------------
@bp.post("/warranty/failure-modes")
def create_failure_mode():
    authenticate(("WarrantyAnalyst",))
    values, _ = validate_body(
        [
            Field("family_id", "id"),
            Field("mode_code", "str"),
            Field("description", "str"),
            Field("severity", "enum", enum=SEVERITIES),
            Field("cost_per_claim_cents", "int", minimum=1),
            Field("supplier_id", "id", required=False, nullable=True),
        ]
    )
    lookups.require_family(values["family_id"])
    if values["supplier_id"] is not None:
        lookups.require_supplier(values["supplier_id"])
    for existing in store.all_rows("failure_modes"):
        if (
            existing["family_id"] == values["family_id"]
            and existing["mode_code"] == values["mode_code"]
        ):
            fail("ERR_DUPLICATE_CODE")

    row = store.insert(
        "failure_modes",
        {
            "_kind": "FailureMode",
            "family_id": values["family_id"],
            "mode_code": values["mode_code"],
            "description": values["description"],
            "severity": values["severity"],
            "cost_per_claim_cents": values["cost_per_claim_cents"],
            "supplier_id": values["supplier_id"],
        },
    )
    return object_response(dump(row), 201)


@bp.get("/warranty/failure-modes/<failure_mode_id>")
def read_failure_mode(failure_mode_id):
    authenticate(READ_ROLES)
    return object_response(dump(lookups.require_failure_mode(failure_mode_id)))


@bp.get("/warranty/failure-modes")
def list_failure_modes():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = store.all_rows("failure_modes")
    family_id = query_filter("family_id")
    if family_id is not None:
        rows = [r for r in rows if r["family_id"] == family_id]
    supplier_id = query_filter("supplier_id")
    if supplier_id is not None:
        rows = [r for r in rows if r["supplier_id"] == supplier_id]
    return list_response(dump_many(paginate(rows, limit, offset)), limit, offset, len(rows))


# ---------------------------------------------------------------------------
# ClaimObservation
# ---------------------------------------------------------------------------
@bp.post("/warranty/claim-observations")
def create_observation():
    authenticate(("WarrantyAnalyst",))
    values, _ = validate_body(
        [
            Field("vintage_id", "id"),
            Field("failure_mode_id", "id"),
            Field("observation_period_code", "period_code"),
            Field("months_in_service_from", "int", minimum=0),
            Field("months_in_service_to", "int"),
            Field("claim_count", "int", minimum=0),
            Field("paid_cost_cents", "int", minimum=0),
        ]
    )
    if values["months_in_service_to"] <= values["months_in_service_from"]:
        fail(
            "ERR_INVALID_REQUEST",
            "months_in_service_to must be strictly greater than months_in_service_from.",
        )

    vintage = lookups.require_vintage(values["vintage_id"])
    lookups.require_failure_mode(values["failure_mode_id"])
    period = lookups.period_by_code(values["observation_period_code"])
    if period is None:
        fail("ERR_PERIOD_NOT_FOUND")
    if period["status"] == "CLOSED":
        fail("ERR_PERIOD_CLOSED")

    # HALF-OPEN bucket geometry: adjacency is legal, any true overlap is not.
    new_from = values["months_in_service_from"]
    new_to = values["months_in_service_to"]
    for existing in store.all_rows("observations"):
        if existing["vintage_id"] != values["vintage_id"]:
            continue
        if existing["failure_mode_id"] != values["failure_mode_id"]:
            continue
        if new_from < existing["months_in_service_to"] and existing["months_in_service_from"] < new_to:
            fail("ERR_OBSERVATION_WINDOW_OVERLAP")

    row = store.insert(
        "observations",
        {
            "_kind": "ClaimObservation",
            "vintage_id": values["vintage_id"],
            "failure_mode_id": values["failure_mode_id"],
            "observation_period_code": values["observation_period_code"],
            "months_in_service_from": new_from,
            "months_in_service_to": new_to,
            "claim_count": values["claim_count"],
            "paid_cost_cents": values["paid_cost_cents"],
        },
        common_fields=False,
    )
    family = calc.family_of_vintage(vintage)
    if family is not None and calc.apply_history_maturity(family):
        store.touch(family)
    return object_response(dump(row), 201)


@bp.get("/warranty/claim-observations/<observation_id>")
def read_observation(observation_id):
    authenticate(READ_ROLES)
    return object_response(dump(lookups.require("observations", observation_id)))


@bp.get("/warranty/claim-observations")
def list_observations():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = store.all_rows("observations")
    vintage_id = query_filter("vintage_id")
    if vintage_id is not None:
        rows = [r for r in rows if r["vintage_id"] == vintage_id]
    failure_mode_id = query_filter("failure_mode_id")
    if failure_mode_id is not None:
        rows = [r for r in rows if r["failure_mode_id"] == failure_mode_id]
    return list_response(dump_many(paginate(rows, limit, offset)), limit, offset, len(rows))

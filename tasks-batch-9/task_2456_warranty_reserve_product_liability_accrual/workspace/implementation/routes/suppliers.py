"""Supplier and SupplierRecovery endpoints, including the SupplierRep portal scope."""

from flask import Blueprint

import lookups
import store
from auth import authenticate
from errors import fail
from response import list_response, object_response
from serialize import dump, dump_many
from services import calc
from validation import Field, no_body, paginate, pagination, query_filter, validate_body

bp = Blueprint("suppliers", __name__)

SUPPLIER_READ_ROLES = ("WarrantyAnalyst", "ReserveController", "Actuary")
RECOVERY_READ_ROLES = ("WarrantyAnalyst", "ReserveController", "Actuary", "SupplierRep")
CREDIT_RATINGS = ("AAA", "BBB", "CCC", "D")
OUTCOMES = ("SETTLED", "WRITTEN_OFF")


# ---------------------------------------------------------------------------
# Supplier
# ---------------------------------------------------------------------------
@bp.post("/warranty/suppliers")
def create_supplier():
    authenticate(("WarrantyAnalyst",))
    values, _ = validate_body(
        [
            Field("supplier_code", "str"),
            Field("name", "str"),
            Field("credit_rating", "enum", enum=CREDIT_RATINGS),
            Field("annual_purchase_volume_cents", "int", minimum=0),
            Field("contractual_recovery_cap_bps", "int", minimum=0, maximum=10000),
        ]
    )
    for existing in store.all_rows("suppliers"):
        if existing["supplier_code"] == values["supplier_code"]:
            fail("ERR_DUPLICATE_CODE")

    row = store.insert(
        "suppliers",
        {
            "_kind": "Supplier",
            "supplier_code": values["supplier_code"],
            "name": values["name"],
            "credit_rating": values["credit_rating"],
            "annual_purchase_volume_cents": values["annual_purchase_volume_cents"],
            "contractual_recovery_cap_bps": values["contractual_recovery_cap_bps"],
            "gross_asserted_recovery_cents": 0,
            "open_recovery_asset_cents": 0,
            "realized_recovery_cents": 0,
            "written_off_recovery_cents": 0,
            "closed_recovery_count": 0,
            "realization_bps": 10000,
            "collectability_rating": "HIGH",
        },
    )
    calc.recompute_supplier_rating(row)
    return object_response(dump(row), 201)


@bp.get("/warranty/suppliers/<supplier_id>")
def read_supplier(supplier_id):
    authenticate(SUPPLIER_READ_ROLES)
    return object_response(dump(lookups.require_supplier(supplier_id)))


# ---------------------------------------------------------------------------
# SupplierRecovery
# ---------------------------------------------------------------------------
@bp.post("/warranty/supplier-recoveries")
def create_recovery():
    authenticate(("WarrantyAnalyst",))
    values, present = validate_body(
        [
            Field("supplier_id", "id"),
            Field("failure_mode_id", "id"),
            Field("asserted_amount_cents", "int", minimum=1),
            Field("field_action_id", "id", required=False, nullable=True),
        ]
    )
    supplier = lookups.require_supplier(values["supplier_id"])
    lookups.require_failure_mode(values["failure_mode_id"])
    if values["field_action_id"] is not None:
        lookups.require_field_action(values["field_action_id"])

    row = store.insert(
        "recoveries",
        {
            "_kind": "SupplierRecovery",
            "supplier_id": values["supplier_id"],
            "failure_mode_id": values["failure_mode_id"],
            "field_action_id": values["field_action_id"],
            "asserted_amount_cents": values["asserted_amount_cents"],
            "settled_amount_cents": None,
            "valuation_variant": "EXPECTED_VALUE",
            "collectability_rating_at_valuation": supplier["collectability_rating"],
            "recognized_recovery_cents": 0,
            "status": "DRAFT",
            "assert_count": 0,
            "supplier_response_note": None,
            "settled_period_id": None,
        },
    )
    calc.value_recovery_expected_value(row, supplier)
    return object_response(dump(row), 201)


@bp.get("/warranty/supplier-recoveries/<recovery_id>")
def read_recovery(recovery_id):
    user_id, role = authenticate(RECOVERY_READ_ROLES)
    if role == "SupplierRep":
        # Rung 3 runs before rung 4, but the comparison needs a row: an unknown id
        # therefore falls through to the 404 of rung 4.
        existing = store.get("recoveries", recovery_id)
        if existing is not None and existing["supplier_id"] != user_id:
            fail("ERR_SUPPLIER_SCOPE_VIOLATION")
    return object_response(dump(lookups.require("recoveries", recovery_id)))


@bp.get("/warranty/supplier-recoveries")
def list_recoveries():
    user_id, role = authenticate(RECOVERY_READ_ROLES)
    supplier_id = query_filter("supplier_id")
    if role == "SupplierRep" and supplier_id != user_id:
        fail("ERR_SUPPLIER_SCOPE_VIOLATION")
    limit, offset = pagination()
    rows = store.all_rows("recoveries")
    if supplier_id is not None:
        rows = [r for r in rows if r["supplier_id"] == supplier_id]
    failure_mode_id = query_filter("failure_mode_id")
    if failure_mode_id is not None:
        rows = [r for r in rows if r["failure_mode_id"] == failure_mode_id]
    field_action_id = query_filter("field_action_id")
    if field_action_id is not None:
        rows = [r for r in rows if r["field_action_id"] == field_action_id]
    settled_period_id = query_filter("settled_period_id")
    if settled_period_id is not None:
        rows = [r for r in rows if r["settled_period_id"] == settled_period_id]
    status = query_filter("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(dump_many(paginate(rows, limit, offset)), limit, offset, len(rows))


@bp.post("/warranty/supplier-recoveries/<recovery_id>/assert")
def assert_recovery(recovery_id):
    authenticate(("WarrantyAnalyst",))
    recovery = lookups.require("recoveries", recovery_id)
    values, present = validate_body(
        [Field("revised_asserted_amount_cents", "int", required=False, minimum=1)]
    )
    if recovery["status"] not in ("DRAFT", "NEGOTIATION"):
        fail("ERR_INVALID_STATE_TRANSITION")
    supplier = store.get("suppliers", recovery["supplier_id"])
    if recovery["status"] == "DRAFT" and recovery["field_action_id"] is not None:
        action = store.get("field_actions", recovery["field_action_id"])
        if action is None or action["approval_state"] != "APPROVED":
            fail("ERR_FIELD_ACTION_NOT_APPROVED")
    if supplier["collectability_rating"] == "IMPAIRED":
        fail("ERR_SUPPLIER_IMPAIRED")

    if "revised_asserted_amount_cents" in present:
        recovery["asserted_amount_cents"] = values["revised_asserted_amount_cents"]
    recovery["status"] = "ASSERTED"
    recovery["assert_count"] += 1
    recovery["supplier_response_note"] = None
    calc.value_recovery_expected_value(recovery, supplier)
    store.touch(recovery)

    changed = calc.recompute_supplier_gross_asserted(supplier)
    changed = calc.recompute_supplier_open_asset(supplier) or changed
    if changed:
        store.touch(supplier)
    return object_response(dump(recovery))


@bp.post("/warranty/supplier-recoveries/<recovery_id>/respond")
def respond_recovery(recovery_id):
    user_id, _ = authenticate(("SupplierRep",))
    existing = store.get("recoveries", recovery_id)
    if existing is not None and existing["supplier_id"] != user_id:
        fail("ERR_SUPPLIER_SCOPE_VIOLATION")
    recovery = lookups.require("recoveries", recovery_id)
    values, _ = validate_body([Field("response_note", "str")])
    if recovery["status"] != "ASSERTED":
        fail("ERR_INVALID_STATE_TRANSITION")

    recovery["status"] = "NEGOTIATION"
    recovery["supplier_response_note"] = values["response_note"]
    supplier = store.get("suppliers", recovery["supplier_id"])
    calc.value_recovery_expected_value(recovery, supplier)
    store.touch(recovery)
    if calc.recompute_supplier_open_asset(supplier):
        store.touch(supplier)
    return object_response(dump(recovery))


@bp.post("/warranty/supplier-recoveries/<recovery_id>/close")
def close_recovery(recovery_id):
    authenticate(("ReserveController",))
    recovery = lookups.require("recoveries", recovery_id)
    values, present = validate_body(
        [
            Field("outcome", "enum", enum=OUTCOMES),
            Field("settled_amount_cents", "int", required=False, minimum=0),
        ]
    )
    outcome = values["outcome"]
    if outcome == "SETTLED" and "settled_amount_cents" not in present:
        fail("ERR_INVALID_REQUEST", "settled_amount_cents is required when outcome is SETTLED.")

    if recovery["status"] not in ("ASSERTED", "NEGOTIATION"):
        fail("ERR_INVALID_STATE_TRANSITION")
    period = None
    if outcome == "SETTLED":
        period = calc.booking_period()
        if period is None:
            fail("ERR_NO_OPEN_PERIOD")
        if values["settled_amount_cents"] > recovery["asserted_amount_cents"]:
            fail("ERR_SETTLEMENT_EXCEEDS_ASSERTED")

    supplier = store.get("suppliers", recovery["supplier_id"])

    # HOP 1
    if outcome == "SETTLED":
        recovery["status"] = "SETTLED"
        recovery["settled_amount_cents"] = values["settled_amount_cents"]
        recovery["settled_period_id"] = period["id"]
        calc.value_recovery_contractual_floor(recovery, supplier)
    else:
        recovery["status"] = "WRITTEN_OFF"
        recovery["settled_amount_cents"] = 0
        recovery["valuation_variant"] = "CONTRACTUAL_FLOOR"
        recovery["collectability_rating_at_valuation"] = supplier["collectability_rating"]
        recovery["recognized_recovery_cents"] = 0
    store.touch(recovery)

    # HOP 2 — the closing row leaves the open filter and enters the closed aggregates.
    supplier_changed = calc.recompute_supplier_aggregates(supplier)
    # HOP 3 — the rating is re-derived from the refreshed closed history.
    supplier_changed = calc.recompute_supplier_rating(supplier) or supplier_changed
    # HOP 4 — exactly one re-valuation pass over the remaining open rows, created_at ASC.
    for other in store.all_rows("recoveries"):
        if other["id"] == recovery["id"]:
            continue
        if other["supplier_id"] != supplier["id"]:
            continue
        if other["status"] not in ("ASSERTED", "NEGOTIATION"):
            continue
        before = (other["recognized_recovery_cents"], other["collectability_rating_at_valuation"])
        calc.value_recovery_expected_value(other, supplier)
        after = (other["recognized_recovery_cents"], other["collectability_rating_at_valuation"])
        if before != after:
            store.touch(other)
    # HOP 5 — the open asset is recomputed once more over the re-valued rows.
    supplier_changed = calc.recompute_supplier_open_asset(supplier) or supplier_changed
    if supplier_changed:
        store.touch(supplier)
    return object_response(dump(recovery))

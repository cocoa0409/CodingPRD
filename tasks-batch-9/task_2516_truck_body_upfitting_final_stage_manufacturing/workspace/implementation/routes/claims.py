"""Warranty claims and the liability ledger (PRD section 3.9)."""

from flask import Blueprint

import db
import middleware
import response
import validation as v
from errors import ApiError
from services import calc, lookup

claims_bp = Blueprint("claims", __name__, url_prefix="/upfit")


def claim_state_error(claim, expected):
    return ApiError(
        "ERR_CLAIM_INVALID_STATE",
        "The claim is %s; this operation requires %s." % (claim.get("status"), expected),
    )


@claims_bp.route("/warranty-claims", methods=["POST"])
def create_claim():
    caller = middleware.require(
        middleware.ROLE_WARRANTY_ADMINISTRATOR, middleware.ROLE_CUSTOMER
    )
    payload = v.body()
    upfit_order_id = v.req_str(payload, "upfit_order_id")
    claim_number = v.req_str(payload, "claim_number")
    failure_system = v.req_enum(payload, "failure_system", v.FAILURE_SYSTEM)
    claim_cost_cents = v.req_int(payload, "claim_cost_cents", minimum=1)

    order = lookup.upfit_order(upfit_order_id)
    middleware.enforce_order_scope(caller, order)

    for existing in db.warranty_claims.values():
        if existing["claim_number"] == claim_number:
            raise ApiError(
                "ERR_DUPLICATE_CLAIM_NUMBER",
                "Claim number '%s' is already in use." % claim_number,
            )

    row = db.insert(
        db.warranty_claims,
        {
            "upfit_order_id": order["id"],
            "claim_number": claim_number,
            "failure_system": failure_system,
            "claim_cost_cents": claim_cost_cents,
            "taint_confirmed": False,
            "split_basis": "PROVISIONAL",
            "status": "SUBMITTED",
            "dispute_round": 0,
        },
    )
    # an opening position the parties can see; deliberately outside the posted set
    calc.apply_split(row, order, "PROVISIONAL")
    return response.object_response(db.serialize(row), 201)


@claims_bp.route("/warranty-claims/<warranty_claim_id>/inspect", methods=["POST"])
def inspect_claim(warranty_claim_id):
    middleware.require(middleware.ROLE_WARRANTY_ADMINISTRATOR)
    payload = v.body()
    taint_confirmed = v.req_bool(payload, "taint_confirmed")
    claim = lookup.warranty_claim(warranty_claim_id)
    if claim["status"] not in ("SUBMITTED", "DISPUTED"):
        raise claim_state_error(claim, "SUBMITTED or DISPUTED")
    claim["taint_confirmed"] = taint_confirmed
    claim["status"] = "INSPECTED"
    db.touch(claim)
    return response.object_response(db.serialize(claim), 200)


@claims_bp.route("/warranty-claims/<warranty_claim_id>/adjudicate", methods=["POST"])
def adjudicate_claim(warranty_claim_id):
    middleware.require(middleware.ROLE_WARRANTY_ADMINISTRATOR)
    payload = v.body()
    override = v.opt_bool(payload, "override_liability_cap", default=False)
    claim = lookup.warranty_claim(warranty_claim_id)
    if claim["status"] not in ("INSPECTED", "DISPUTED"):
        raise claim_state_error(claim, "INSPECTED or DISPUTED")
    order = db.upfit_orders.get(claim["upfit_order_id"])

    projected = calc.warranty_liability_split(claim, order, "FINAL")

    # 100. the cap is checked here and nowhere else, against the order-level total
    if not override:
        ledger = calc.order_liability_ledger(
            order, ignore_claim_id=claim["id"], extra=projected
        )
        cap = int(order.get("warranty_liability_cap_cents") or 0)
        if ledger["upfitter_liability_cents"] > cap:
            raise ApiError(
                "ERR_WARRANTY_BUDGET_EXCEEDED",
                "Posting this adjudication would take the order's upfitter liability "
                "to %s cents, above the cap of %s cents."
                % (ledger["upfitter_liability_cents"], cap),
            )

    calc.apply_split(claim, order, "FINAL")
    claim["status"] = "ADJUDICATED"
    db.touch(claim)
    calc.refresh_order_ledger(order)
    db.touch(order)
    return response.object_response(db.serialize(claim), 200)


@claims_bp.route("/warranty-claims/<warranty_claim_id>/dispute", methods=["POST"])
def dispute_claim(warranty_claim_id):
    caller = middleware.require(
        middleware.ROLE_WARRANTY_ADMINISTRATOR, middleware.ROLE_CUSTOMER
    )
    payload = v.body()
    v.req_str(payload, "reason")
    claim = lookup.warranty_claim(warranty_claim_id)
    order = db.upfit_orders.get(claim["upfit_order_id"])
    middleware.enforce_order_scope(caller, order)

    if claim["status"] != "ADJUDICATED":
        raise claim_state_error(claim, "ADJUDICATED")
    # the settlement being argued about stays visible on the claim; only the
    # order-level rollup changes
    claim["status"] = "DISPUTED"
    claim["dispute_round"] = int(claim.get("dispute_round") or 0) + 1
    db.touch(claim)
    calc.refresh_order_ledger(order)
    db.touch(order)
    return response.object_response(db.serialize(claim), 200)


@claims_bp.route("/warranty-claims/<warranty_claim_id>/pay", methods=["POST"])
def pay_claim(warranty_claim_id):
    middleware.require(middleware.ROLE_WARRANTY_ADMINISTRATOR)
    claim = lookup.warranty_claim(warranty_claim_id)
    if claim["status"] != "ADJUDICATED":
        raise claim_state_error(claim, "ADJUDICATED")
    claim["status"] = "PAID"
    db.touch(claim)
    order = db.upfit_orders.get(claim["upfit_order_id"])
    if order is not None:
        calc.refresh_order_ledger(order)
        db.touch(order)
    return response.object_response(db.serialize(claim), 200)


@claims_bp.route("/warranty-claims/<warranty_claim_id>", methods=["GET"])
def get_claim(warranty_claim_id):
    caller = middleware.require(
        middleware.ROLE_PLANT_ADMIN,
        middleware.ROLE_PRODUCTION_SCHEDULER,
        middleware.ROLE_UPFIT_ENGINEER,
        middleware.ROLE_COMPLIANCE_OFFICER,
        middleware.ROLE_WARRANTY_ADMINISTRATOR,
        middleware.ROLE_CUSTOMER,
    )
    claim = lookup.warranty_claim(warranty_claim_id)
    middleware.enforce_order_scope(caller, db.upfit_orders.get(claim["upfit_order_id"]))
    return response.object_response(db.serialize(claim), 200)


@claims_bp.route("/warranty-claims", methods=["GET"])
def list_claims():
    caller = middleware.require(
        middleware.ROLE_PLANT_ADMIN,
        middleware.ROLE_PRODUCTION_SCHEDULER,
        middleware.ROLE_UPFIT_ENGINEER,
        middleware.ROLE_COMPLIANCE_OFFICER,
        middleware.ROLE_WARRANTY_ADMINISTRATOR,
        middleware.ROLE_CUSTOMER,
    )
    upfit_order_id = v.filter_str("upfit_order_id")
    failure_system = v.filter_enum("failure_system", v.FAILURE_SYSTEM)
    split_basis = v.filter_enum("split_basis", v.SPLIT_BASIS)
    status = v.filter_enum("status", v.CLAIM_STATUS)

    rows = middleware.scope_filter_by_order(caller, list(db.warranty_claims.values()))
    if upfit_order_id is not None:
        rows = [r for r in rows if r["upfit_order_id"] == upfit_order_id]
    if failure_system is not None:
        rows = [r for r in rows if r["failure_system"] == failure_system]
    if split_basis is not None:
        rows = [r for r in rows if r["split_basis"] == split_basis]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.paginate(rows)

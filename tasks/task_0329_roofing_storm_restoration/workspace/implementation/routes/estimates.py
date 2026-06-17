"""Estimate + EstimateLineItem resources."""
from flask import Blueprint, request

import errors
from errors import ApiError
from db import db, common_create_fields, touch
from middleware import require_role, get_json_body
from response import success, list_response
from services import calculations as calc
import validators as V

bp = Blueprint("estimates", __name__)

ROLE_ALL = {"FieldAdjuster", "Estimator", "ProductionManager"}
SOURCE_KINDS = {"AERIAL", "FIELD"}
TRADES = {"SHINGLE", "UNDERLAYMENT", "RIDGE_VENT", "FLASHING", "DECKING", "GUTTER"}


@bp.route("/estimates", methods=["POST"])
def create_estimate():
    require_role({"Estimator"})
    body = get_json_body()
    job_id = V.require_field(body, "job_id")
    source_kind = V.require_field(body, "source_kind")
    if not isinstance(job_id, str):
        V.missing_field("job_id")
    # FK (priority 4)
    V.resolve_fk(db.jobs, job_id)
    # enum / range (priority 6)
    V.validate_enum(source_kind, SOURCE_KINDS, "source_kind")
    aerial_pct = body.get("aerial_contingency_pct", 0.08)
    if aerial_pct is None:
        aerial_pct = 0.08
    V.validate_number(aerial_pct, "aerial_contingency_pct", ge=0, le=0.25)

    ent = common_create_fields(versioned=True)
    ent.update({
        "job_id": job_id,
        "source_kind": source_kind,
        "aerial_contingency_pct": aerial_pct,
        "status": "DRAFT",
        "line_subtotal_cents": 0,
        "final_total_cents": 0,
    })
    with db.lock:
        db.estimates[ent["id"]] = ent
    return success(ent, status=201)


@bp.route("/estimates/<entity_id>", methods=["GET"])
def get_estimate(entity_id):
    require_role(ROLE_ALL)
    ent = V.find_or_404(db.estimates, entity_id)
    return success(ent, status=200)


@bp.route("/estimates", methods=["GET"])
def list_estimates():
    require_role(ROLE_ALL)
    limit, offset = V.parse_pagination()
    items = list(db.estimates.values())
    for key in ("job_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e.get(key) == val]
    items = V.sort_by_created(items)
    page, total = V.paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


def _recompute_estimate_totals(estimate):
    lines = [li for li in db.line_items.values()
             if li["estimate_id"] == estimate["id"]]
    lines = V.sort_by_created(lines)
    subtotal = calc.line_subtotal_cents(lines)
    estimate["line_subtotal_cents"] = subtotal
    estimate["final_total_cents"] = calc.final_total_cents(
        subtotal, estimate["source_kind"], estimate["aerial_contingency_pct"]
    )


@bp.route("/estimates/<entity_id>/line-items", methods=["POST"])
def add_line_item(entity_id):
    require_role({"Estimator"})
    with db.lock:
        estimate = V.find_or_404(db.estimates, entity_id)
        body = get_json_body()
        trade = V.require_field(body, "trade")
        squares = V.require_field(body, "squares")
        unit_price_cents = V.require_field(body, "unit_price_cents")

        # enum / range (priority 6)
        V.validate_enum(trade, TRADES, "trade")
        V.validate_number(squares, "squares", gt=0)
        V.validate_int(unit_price_cents, "unit_price_cents", gt=0)
        waste = body.get("waste_factor_pct", 0.10)
        if waste is None:
            waste = 0.10
        V.validate_number(waste, "waste_factor_pct", ge=0, le=0.50)

        # state (priority 7): must be DRAFT to append
        if estimate["status"] != "DRAFT":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Estimate must be DRAFT to append line items")

        # optional estimate-version OCC (not part of Job-ledger contract).
        expected = body.get("expected_estimate_version")
        if expected is not None:
            if not V.is_int(expected):
                V.invalid_request("expected_estimate_version must be an integer")
            if expected != estimate["version"]:
                raise ApiError(errors.ERR_STALE_JOB_VERSION, 412,
                               "Stale estimate version")

        li = common_create_fields(versioned=True)
        li.update({
            "estimate_id": estimate["id"],
            "trade": trade,
            "squares": squares,
            "waste_factor_pct": waste,
            "unit_price_cents": unit_price_cents,
            "line_cost_cents": calc.line_cost_cents(squares, waste, unit_price_cents),
        })
        db.line_items[li["id"]] = li

        # recompute running totals on the DRAFT estimate; this is a mutation
        _recompute_estimate_totals(estimate)
        touch(estimate)
        return success(li, status=201)


@bp.route("/estimates/<entity_id>/line-items", methods=["GET"])
def list_line_items(entity_id):
    require_role(ROLE_ALL)
    V.find_or_404(db.estimates, entity_id)
    limit, offset = V.parse_pagination()
    items = [li for li in db.line_items.values() if li["estimate_id"] == entity_id]
    items = V.sort_by_created(items)
    page, total = V.paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/estimates/<entity_id>/finalize", methods=["POST"])
def finalize_estimate(entity_id):
    require_role({"Estimator"})
    with db.lock:
        estimate = V.find_or_404(db.estimates, entity_id)
        # state (priority 7)
        if estimate["status"] != "DRAFT":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Estimate not DRAFT")
        # must have at least one line item
        lines = [li for li in db.line_items.values()
                 if li["estimate_id"] == estimate["id"]]
        if not lines:
            raise ApiError(errors.ERR_EMPTY_ESTIMATE, 409,
                           "Estimate has no line items")
        _recompute_estimate_totals(estimate)
        estimate["status"] = "FINALIZED"
        touch(estimate)
        return success(estimate, status=200)

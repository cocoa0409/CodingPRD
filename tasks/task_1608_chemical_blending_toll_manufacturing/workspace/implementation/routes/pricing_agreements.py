"""Pricing agreement endpoints."""
from flask import Blueprint, request

import db
import errors
from middleware import require_role
from response import success_object, success_list
from services.common import (
    new_id,
    now_iso,
    pagination_params,
    paginate,
    sort_by_created_at,
    serialize_pricing_agreement,
    to_int,
    parse_iso,
)

bp = Blueprint("pricing_agreements", __name__)

PRICING_MODES = {"TOLLING_FEE", "FORMULATED_PRICE"}


def _customer_or_404(cid):
    c = db.customers.get(cid)
    if c is None:
        raise errors.not_found("customer not found")
    return c


def _agreement_or_404(customer_id, agreement_id):
    a = db.pricing_agreements.get(agreement_id)
    if a is None or a["customer_id"] != customer_id:
        raise errors.not_found("pricing agreement not found")
    return a


def _windows_overlap(a_from, a_to, b_from, b_to):
    """Half-open [from, to) overlap test."""
    return a_from < b_to and b_from < a_to


def _fully_covers(in_from, in_to, ex_from, ex_to):
    """True iff incoming window fully covers existing window."""
    return in_from <= ex_from and ex_to <= in_to


@bp.route("/toll-operations/customers/<id>/pricing-agreements", methods=["POST"])
def create_pricing_agreement(id):
    require_role({"QualityManager"})
    _customer_or_404(id)
    body = request.get_json(silent=True) or {}

    pricing_mode = body.get("pricing_mode")
    if pricing_mode not in PRICING_MODES:
        raise errors.invalid_request("pricing_mode must be TOLLING_FEE or FORMULATED_PRICE")

    tolling_base_fee_cents = to_int(body.get("tolling_base_fee_cents"), "tolling_base_fee_cents")
    tolling_per_kg_cents = to_int(body.get("tolling_per_kg_cents"), "tolling_per_kg_cents")
    formulated_price_per_kg_cents = to_int(body.get("formulated_price_per_kg_cents"), "formulated_price_per_kg_cents")
    for v, name in [
        (tolling_base_fee_cents, "tolling_base_fee_cents"),
        (tolling_per_kg_cents, "tolling_per_kg_cents"),
        (formulated_price_per_kg_cents, "formulated_price_per_kg_cents"),
    ]:
        if v < 0:
            raise errors.invalid_request(f"{name} must be >= 0")

    over_yield_split_pct = body.get("over_yield_split_pct", 50)
    over_yield_split_pct = to_int(over_yield_split_pct, "over_yield_split_pct")
    if over_yield_split_pct < 0 or over_yield_split_pct > 100:
        raise errors.invalid_request("over_yield_split_pct must be in [0,100]")

    effective_from = body.get("effective_from")
    effective_to = body.get("effective_to")
    if not effective_from or not effective_to:
        raise errors.invalid_request("effective_from and effective_to required")
    ef_dt = parse_iso(effective_from)
    et_dt = parse_iso(effective_to)
    # Per PRD §3.2: range violations fail at create. But window ordering check
    # (effective_from < effective_to) is enforced at ACTIVATE per scaffold.
    # Here we just record.
    now = now_iso()
    aid = new_id()
    agreement = {
        "id": aid,
        "customer_id": id,
        "pricing_mode": pricing_mode,
        "tolling_base_fee_cents": tolling_base_fee_cents,
        "tolling_per_kg_cents": tolling_per_kg_cents,
        "formulated_price_per_kg_cents": formulated_price_per_kg_cents,
        "over_yield_split_pct": over_yield_split_pct,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "DRAFT",
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.pricing_agreements[aid] = agreement
    return success_object(serialize_pricing_agreement(agreement), status=201)


@bp.route("/toll-operations/customers/<id>/pricing-agreements", methods=["GET"])
def list_pricing_agreements(id):
    require_role({"Any"})
    _customer_or_404(id)
    limit, offset = pagination_params()
    rows = [a for a in db.pricing_agreements.values() if a["customer_id"] == id]
    rows = sort_by_created_at(rows)
    slice_, total = paginate(rows, limit, offset)
    return success_list([serialize_pricing_agreement(a) for a in slice_], limit, offset, total)


@bp.route("/toll-operations/customers/<id>/pricing-agreements/<agreementId>", methods=["GET"])
def get_pricing_agreement(id, agreementId):
    require_role({"Any"})
    _customer_or_404(id)
    a = _agreement_or_404(id, agreementId)
    return success_object(serialize_pricing_agreement(a))


@bp.route("/toll-operations/customers/<id>/pricing-agreements/<agreementId>/activate", methods=["POST"])
def activate_pricing_agreement(id, agreementId):
    require_role({"QualityManager"})
    _customer_or_404(id)
    a = _agreement_or_404(id, agreementId)
    if a["status"] != "DRAFT":
        raise errors.invalid_state("pricing agreement not DRAFT")
    ef_dt = parse_iso(a["effective_from"])
    et_dt = parse_iso(a["effective_to"])
    if not (ef_dt < et_dt):
        raise errors.invalid_request("effective_from must be < effective_to")

    # Check overlap with other ACTIVE agreements for this customer
    for other in db.pricing_agreements.values():
        if other["id"] == a["id"]:
            continue
        if other["customer_id"] != id:
            continue
        if other["status"] != "ACTIVE":
            continue
        o_ef = parse_iso(other["effective_from"])
        o_et = parse_iso(other["effective_to"])
        if _windows_overlap(ef_dt, et_dt, o_ef, o_et):
            if _fully_covers(ef_dt, et_dt, o_ef, o_et):
                # Supersede
                other["status"] = "SUPERSEDED"
                other["version"] += 1
                other["updated_at"] = now_iso()
            else:
                raise errors.ApiError(
                    errors.ERR_AGREEMENT_WINDOW_OVERLAP,
                    409,
                    "overlapping ACTIVE agreement window",
                )

    # OCC last
    body = request.get_json(silent=True) or {}
    expected = body.get("expected_pricing_agreement_version")
    if expected is None:
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412, "expected_pricing_agreement_version required")
    try:
        expected_int = int(expected)
    except (TypeError, ValueError):
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412, "expected_pricing_agreement_version invalid")
    if expected_int != a["version"]:
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412, "stale pricing agreement version")

    a["status"] = "ACTIVE"
    a["version"] += 1
    a["updated_at"] = now_iso()
    return success_object(serialize_pricing_agreement(a))


@bp.route("/toll-operations/customers/<id>/pricing-agreements/<agreementId>/terminate", methods=["POST"])
def terminate_pricing_agreement(id, agreementId):
    require_role({"QualityManager"})
    _customer_or_404(id)
    a = _agreement_or_404(id, agreementId)
    if a["status"] != "ACTIVE":
        raise errors.invalid_state("pricing agreement not ACTIVE")
    a["status"] = "TERMINATED"
    a["version"] += 1
    a["updated_at"] = now_iso()
    return success_object(serialize_pricing_agreement(a))

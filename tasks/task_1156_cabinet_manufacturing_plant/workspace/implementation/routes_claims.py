"""Damage / replacement door program (PRD §3.8)."""
from flask import Blueprint, request

from auth import check_dealer_ownership, require_any_role, require_roles
from domain import (
    ADJUDICATION_DECISIONS,
    CLAIM_TYPES,
    CLAIM_DEALER_ERROR_CHARGE_PCT,
    CLAIM_PROVISIONAL_PCT,
    claim_credit_basis,
    claim_within_window,
)
from errors import api_error
from serializers import ser_claim
from store import db, new_id, stamp, touch
from util import Body, D, paginate, respond_list, respond_object, rhu_int, sort_records

bp = Blueprint("claims", __name__)


def _get_claim(claim_id):
    claim = db.claims.get(claim_id)
    if claim is None:
        raise api_error("ERR_CLAIM_NOT_FOUND", f"ReplacementClaim {claim_id} not found")
    return claim


@bp.post("/kcma/replacement-claims")
def create_replacement_claim():
    uid, _ = require_roles({"Dealer"})
    body = Body(request.get_json(silent=True))
    original_order_line_id = body.req_str("original_order_line_id")
    claim_type = body.req_enum("claim_type", CLAIM_TYPES)
    qty = body.req_int("qty", min_value=1)

    # priority 5: body FK exists
    line = None
    order = None
    if original_order_line_id is not None:
        line = db.order_lines.get(original_order_line_id)
        if line is None:
            raise api_error(
                "ERR_ORDER_LINE_NOT_FOUND",
                f"OrderLine {original_order_line_id} not found",
            )
        order = db.orders[line["order_id"]]
    # priority 3: ownership guards first — the original order must belong to
    # the claiming dealer
    if order is not None:
        check_dealer_ownership(uid, order["dealer_id"])
    # priority 9: strict eligibility — DOOR line, SHIPPED order, qty within
    # the original line's quantity
    if line is not None and (
        line["line_type"] != "DOOR"
        or order["status"] != "SHIPPED"
        or (qty is not None and qty > line["qty"])
    ):
        raise api_error(
            "ERR_CLAIM_LINE_NOT_ELIGIBLE",
            "Claim requires a DOOR line on a SHIPPED order owned by the claimant, "
            "with qty not exceeding the line's qty",
        )
    body.raise_field_errors()  # priority 14

    dealer = db.dealers[uid]
    basis = claim_credit_basis(line, dealer, qty)
    claim = {
        "id": new_id(),
        "dealer_id": uid,
        "original_order_line_id": line["id"],
        "claim_type": claim_type,
        "qty": qty,
        "credit_basis_cents": basis,
        # provisional variant: flat 50% of basis regardless of type or window
        "provisional_credit_cents": rhu_int(D(basis) * CLAIM_PROVISIONAL_PCT),
        "final_credit_cents": None,
        "replacement_charge_cents": None,
        "status": "SUBMITTED",
        "adjudicator_note": None,
    }
    stamp(claim)
    db.claims[claim["id"]] = claim
    return respond_object(ser_claim(claim), 201)


@bp.get("/kcma/replacement-claims")
def list_replacement_claims():
    require_any_role()
    records = list(db.claims.values())
    dealer_id = request.args.get("dealer_id")
    if dealer_id is not None:
        records = [c for c in records if c["dealer_id"] == dealer_id]
    line_id = request.args.get("original_order_line_id")
    if line_id is not None:
        records = [c for c in records if c["original_order_line_id"] == line_id]
    page, total, limit, offset = paginate(sort_records(records))
    return respond_list([ser_claim(c) for c in page], total, limit, offset)


@bp.get("/kcma/replacement-claims/<claimId>")
def get_replacement_claim(claimId):
    require_any_role()
    return respond_object(ser_claim(_get_claim(claimId)), 200)


@bp.post("/kcma/replacement-claims/<claimId>/adjudicate")
def adjudicate_claim(claimId):
    require_roles({"PlantAdmin"})
    claim = _get_claim(claimId)                                   # priority 4
    if claim["status"] != "SUBMITTED":                            # priority 6
        raise api_error(
            "ERR_CLAIM_NOT_ADJUDICATABLE",
            "Adjudication requires the claim in SUBMITTED",
        )
    body = Body(request.get_json(silent=True))
    decision = body.req_enum("decision", ADJUDICATION_DECISIONS)
    note = body.opt_str("note")

    # priority 12: warranty window for covered types, measured in whole days
    # from the original order's shipped_at against the logical clock
    if decision == "APPROVE" and claim["claim_type"] in (
        "FREIGHT_DAMAGE",
        "MANUFACTURING_DEFECT",
    ):
        line = db.order_lines[claim["original_order_line_id"]]
        order = db.orders[line["order_id"]]
        if not claim_within_window(claim, order):
            raise api_error(
                "ERR_CLAIM_WARRANTY_EXPIRED",
                "Claim is outside the warranty window for its type",
            )
    body.raise_field_errors()  # priority 14

    claim["adjudicator_note"] = note
    if decision == "DENY":
        claim["status"] = "DENIED"
        claim["final_credit_cents"] = 0
        claim["replacement_charge_cents"] = 0
    elif claim["claim_type"] == "DEALER_ERROR":
        claim["status"] = "APPROVED_CHARGED"
        claim["final_credit_cents"] = 0
        claim["replacement_charge_cents"] = rhu_int(
            D(claim["credit_basis_cents"]) * CLAIM_DEALER_ERROR_CHARGE_PCT
        )
    else:
        claim["status"] = "APPROVED_NO_CHARGE"
        claim["final_credit_cents"] = claim["credit_basis_cents"]
        claim["replacement_charge_cents"] = 0
    touch(claim)
    return respond_object(ser_claim(claim), 200)

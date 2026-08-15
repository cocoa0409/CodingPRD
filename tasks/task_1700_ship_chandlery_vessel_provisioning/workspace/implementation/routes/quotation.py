"""Quotation routes: draft, send, revise (OCC), accept (waterfall + credit +
cold gates), withdraw. Lazy expiry per PRD §3.4.

Acceptance check order (PRD §3.4, ordering matters — earlier failures mask
later ones):
  1. quotation SENT else ERR_QUOTATION_NOT_ACCEPTABLE
  2. now <= valid_until else flip EXPIRED + ERR_QUOTATION_EXPIRED
  3. VesselCall IN_PORT else ERR_VESSEL_CALL_NOT_IN_PORT
  4. credit gate else ERR_CREDIT_LIMIT_EXCEEDED
  5. stock waterfall else ERR_STOCK_INSUFFICIENT
  6. cold-chain capacity else ERR_COLD_CHAIN_CAPACITY_EXCEEDED
"""
from decimal import Decimal

from flask import Blueprint, request

import db
from db import stamp_new, touch, _parse_iso
from errors import (err_requisition_not_found, err_quotation_not_found,
                    err_catalog_item_not_found, err_invalid_request,
                    err_insufficient_permissions,
                    err_requisition_not_open_for_quotes,
                    err_quotation_not_sendable, err_quotation_not_revisable,
                    err_quotation_not_acceptable, err_quotation_not_withdrawable,
                    err_quotation_expired, err_vessel_call_not_in_port,
                    err_credit_limit_exceeded, err_stale_version,
                    err_bonded_item_not_eligible, err_substitution_not_allowed,
                    err_substitution_price_cap_exceeded)
from middleware import require_roles, require_any_authenticated
from response import success_object, success_list, parse_pagination
from services.exposure import recompute_agent_exposure
from services.money import round_half_up_cents
from services.pricing import provisional_pricing
from services.stock import run_waterfall
from services.validate import (get_body, req_lines_array, req_datetime,
                               qty_at_least_one, req_int)  # noqa: F401 (qty helper used inline)

bp = Blueprint("quotation", __name__)


# ---------------------------------------------------------------------------
# Quotation line validation: coverage, substitution admissibility, price cap
# ---------------------------------------------------------------------------

def _validate_quotation_lines(requisition, raw_lines):
    """Validate quotation lines against the requisition.

    Enforces, in priority order:
      - body shape (ERR_INVALID_REQUEST / ERR_INVALID_QTY)
      - catalog FK existence (ERR_CATALOG_ITEM_NOT_FOUND)
      - substitution admissibility (ERR_SUBSTITUTION_NOT_ALLOWED): the
        requisition line must allow substitution; substitute shares category
        and requires_cold_chain with the original; every requisition line
        covered exactly once (a substitute covers its original)
      - bonded parity (ERR_BONDED_ITEM_NOT_ELIGIBLE): may not substitute INTO
        a bonded_eligible item unless the original is also bonded_eligible
        (and not the reverse)
      - price cap (ERR_SUBSTITUTION_PRICE_CAP_EXCEEDED): substitute
        unit_price_cents <= round_half_up(original.base_price_cents * 115/100),
        boundary inclusive
    Returns the validated line list.
    """
    req_lines = requisition["lines"]
    validated = []
    for line in raw_lines:
        catalog_item_id = line.get("catalog_item_id")
        if not isinstance(catalog_item_id, str) or catalog_item_id.strip() == "":
            raise err_invalid_request("missing or invalid field: catalog_item_id")
        if catalog_item_id not in db.catalog_items:
            raise err_catalog_item_not_found()
        qty = line.get("qty")
        if isinstance(qty, bool) or not isinstance(qty, int):
            raise err_invalid_request("qty must be an integer")
        qty_at_least_one(qty)
        unit_price_cents = req_int(line, "unit_price_cents")
        if unit_price_cents < 1:
            raise err_invalid_request("unit_price_cents must be >= 1")
        is_substitution = line.get("is_substitution")
        if not isinstance(is_substitution, bool):
            raise err_invalid_request("is_substitution must be a boolean")
        substitution_of_item_id = line.get("substitution_of_item_id")
        if is_substitution:
            if not isinstance(substitution_of_item_id, str) or substitution_of_item_id.strip() == "":
                raise err_invalid_request(
                    "substitution_of_item_id required iff is_substitution")
            if substitution_of_item_id not in db.catalog_items:
                raise err_catalog_item_not_found()
        else:
            if substitution_of_item_id is not None:
                raise err_invalid_request(
                    "substitution_of_item_id must be absent unless is_substitution")
        validated.append({
            "catalog_item_id": catalog_item_id,
            "qty": qty,
            "unit_price_cents": unit_price_cents,
            "is_substitution": is_substitution,
            "substitution_of_item_id": substitution_of_item_id if is_substitution else None,
        })

    # Bonded parity FIRST (validation priority 8): a line may not substitute
    # INTO a bonded_eligible item unless the original is also bonded_eligible
    # — and the reverse (bonded original -> non-bonded substitute) is likewise
    # inadmissible ("or reverse" per SCAFFOLD §1.6). This check outranks the
    # substitution-admissibility tests (priority 15).
    for line in validated:
        if not line["is_substitution"]:
            continue
        original_item = db.catalog_items[line["substitution_of_item_id"]]
        substitute_item = db.catalog_items[line["catalog_item_id"]]
        if bool(substitute_item["bonded_eligible"]) != bool(original_item["bonded_eligible"]):
            raise err_bonded_item_not_eligible()

    # Coverage + substitution admissibility (priority 15,
    # ERR_SUBSTITUTION_NOT_ALLOWED). Map each requisition line's
    # catalog_item_id to the covering quote line:
    #   - non-substitute line covers a requisition line with the same item
    #   - substitute line covers the requisition line of substitution_of_item_id
    covered = {}  # requisition catalog_item_id -> covering validated line
    for line in validated:
        if line["is_substitution"]:
            original_id = line["substitution_of_item_id"]
            # the original item must appear among requisition lines
            req_line = next((rl for rl in req_lines
                             if rl["catalog_item_id"] == original_id), None)
            if req_line is None:
                raise err_substitution_not_allowed()
            if not req_line["allows_substitution"]:
                raise err_substitution_not_allowed()
            original_item = db.catalog_items[original_id]
            substitute_item = db.catalog_items[line["catalog_item_id"]]
            if substitute_item["category"] != original_item["category"]:
                raise err_substitution_not_allowed()
            if bool(substitute_item["requires_cold_chain"]) != bool(original_item["requires_cold_chain"]):
                raise err_substitution_not_allowed()
            if original_id in covered:
                raise err_substitution_not_allowed()  # covered more than once
            covered[original_id] = line
        else:
            item_id = line["catalog_item_id"]
            if item_id in covered:
                raise err_substitution_not_allowed()
            covered[item_id] = line

    # every requisition line must be covered exactly once
    for rl in req_lines:
        if rl["catalog_item_id"] not in covered:
            raise err_substitution_not_allowed()

    # Substitution price cap (priority 16,
    # ERR_SUBSTITUTION_PRICE_CAP_EXCEEDED), boundary inclusive.
    for line in validated:
        if not line["is_substitution"]:
            continue
        original_item = db.catalog_items[line["substitution_of_item_id"]]
        cap = round_half_up_cents(Decimal(original_item["base_price_cents"]) * 115 / 100)
        if line["unit_price_cents"] > cap:
            raise err_substitution_price_cap_exceeded()

    return validated


def _lazy_expire(quotation):
    """If now > valid_until, flip SENT quotation to EXPIRED (with requisition
    fallback) and raise ERR_QUOTATION_EXPIRED. Inclusive deadline: now ==
    valid_until is valid."""
    now = db.now_dt()
    valid_until = _parse_iso(quotation["valid_until"])
    if now > valid_until:
        was_sent = quotation["status"] == "SENT"
        quotation["status"] = "EXPIRED"
        touch(quotation)
        if was_sent:
            _requisition_fallback_after_sent_gone(quotation["requisition_id"])
        raise err_quotation_expired()


def _requisition_fallback_after_sent_gone(requisition_id):
    """When the only SENT quotation disappears (withdrawn or expired) and no
    other SENT quotation exists, the requisition falls back QUOTED -> SUBMITTED."""
    any_sent = any(q["requisition_id"] == requisition_id and q["status"] == "SENT"
                   for q in db.quotations.values())
    if any_sent:
        return
    req = db.requisitions.get(requisition_id)
    if req is not None and req["status"] == "QUOTED":
        req["status"] = "SUBMITTED"
        touch(req)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route("/chandlery/requisitions/<req_id>/quotations", methods=["POST"])
@require_roles("ChandlerSalesRep")
def create_quotation(user_id, role, req_id):
    requisition = db.requisitions.get(req_id)
    if requisition is None:
        raise err_requisition_not_found()
    if requisition["status"] not in ("SUBMITTED", "QUOTED"):
        raise err_requisition_not_open_for_quotes()
    body = get_body()
    raw_lines = req_lines_array(body, "lines", min_len=1)
    valid_until = req_datetime(body, "valid_until")
    lines = _validate_quotation_lines(requisition, raw_lines)
    vessel_call = db.vessel_calls[requisition["vessel_call_id"]]
    totals = provisional_pricing(lines, vessel_call, db.catalog_items)
    quotation = {
        "requisition_id": req_id,
        "lines": lines,
        "valid_until": body["valid_until"],
        "provisional_total_cents": totals["total_cents"],
        "provisional_subtotal_cents": totals["subtotal_cents"],
        "provisional_rebate_cents": totals["rebate_cents"],
        "revision_count": 0,
        "authored_by_user_id": user_id,
        "status": "DRAFT",
    }
    stamp_new(quotation)
    db.quotations[quotation["id"]] = quotation
    return success_object(quotation, status=201)


@bp.route("/chandlery/requisitions/<req_id>/quotations", methods=["GET"])
@require_any_authenticated
def list_quotations(user_id, role, req_id):
    if req_id not in db.requisitions:
        raise err_requisition_not_found()
    items = [q for q in db.quotations.values() if q["requisition_id"] == req_id]
    items.sort(key=lambda r: r["created_at"])
    limit, offset = parse_pagination(request.args)
    return success_list(items[offset:offset + limit], limit, offset, len(items))


@bp.route("/chandlery/quotations/<q_id>", methods=["GET"])
@require_any_authenticated
def get_quotation(user_id, role, q_id):
    q = db.quotations.get(q_id)
    if q is None:
        raise err_quotation_not_found()
    return success_object(q)


@bp.route("/chandlery/quotations/<q_id>/send", methods=["POST"])
@require_roles("ChandlerSalesRep")
def send_quotation(user_id, role, q_id):
    q = db.quotations.get(q_id)
    if q is None:
        raise err_quotation_not_found()
    if q["status"] != "DRAFT":
        # lazy expiry check applies to send attempts too — but send from a
        # non-DRAFT state is simply not sendable (EXPIRED/SENT/etc.)
        raise err_quotation_not_sendable()
    # PRD §3.4: send attempt when now > valid_until flips to EXPIRED.
    _lazy_expire(q)
    requisition = db.requisitions[q["requisition_id"]]
    if requisition["status"] not in ("SUBMITTED", "QUOTED"):
        raise err_requisition_not_open_for_quotes()
    vessel_call = db.vessel_calls[requisition["vessel_call_id"]]
    totals = provisional_pricing(q["lines"], vessel_call, db.catalog_items)
    q["provisional_total_cents"] = totals["total_cents"]
    q["provisional_subtotal_cents"] = totals["subtotal_cents"]
    q["provisional_rebate_cents"] = totals["rebate_cents"]
    q["status"] = "SENT"
    touch(q)
    # system transition: requisition SUBMITTED -> QUOTED
    if requisition["status"] == "SUBMITTED":
        requisition["status"] = "QUOTED"
        touch(requisition)
    return success_object(q)


@bp.route("/chandlery/quotations/<q_id>/revise", methods=["POST"])
@require_roles("ChandlerSalesRep")
def revise_quotation(user_id, role, q_id):
    q = db.quotations.get(q_id)
    if q is None:
        raise err_quotation_not_found()
    if q["status"] != "SENT":
        raise err_quotation_not_revisable()
    # lazy expiry before OCC so an expired quote surfaces ERR_QUOTATION_EXPIRED
    _lazy_expire(q)
    body = get_body()
    expected = req_int(body, "expected_quotation_version")
    if expected != q["version"]:
        raise err_stale_version()
    raw_lines = req_lines_array(body, "lines", min_len=1)
    valid_until = req_datetime(body, "valid_until")
    requisition = db.requisitions[q["requisition_id"]]
    lines = _validate_quotation_lines(requisition, raw_lines)
    vessel_call = db.vessel_calls[requisition["vessel_call_id"]]
    totals = provisional_pricing(lines, vessel_call, db.catalog_items)
    q["lines"] = lines
    q["valid_until"] = body["valid_until"]
    q["provisional_total_cents"] = totals["total_cents"]
    q["provisional_subtotal_cents"] = totals["subtotal_cents"]
    q["provisional_rebate_cents"] = totals["rebate_cents"]
    q["revision_count"] = q.get("revision_count", 0) + 1
    touch(q)
    return success_object(q)


@bp.route("/chandlery/quotations/<q_id>/accept", methods=["POST"])
@require_roles("VesselCateringOfficer")
def accept_quotation(user_id, role, q_id):
    q = db.quotations.get(q_id)
    if q is None:
        raise err_quotation_not_found()
    # 1. state gate
    if q["status"] != "SENT":
        raise err_quotation_not_acceptable()
    # 2. validity window (inclusive deadline); flips to EXPIRED on violation
    _lazy_expire(q)
    requisition = db.requisitions[q["requisition_id"]]
    vessel_call = db.vessel_calls[requisition["vessel_call_id"]]
    # ownership: acting officer must be this call's officer
    if user_id != vessel_call["id"]:
        raise err_insufficient_permissions()
    # 3. cross-entity gate
    if vessel_call["status"] != "IN_PORT":
        raise err_vessel_call_not_in_port()
    # 4. credit gate (committed exposure BEFORE this order; inclusive accept)
    agent = db.ship_agents[vessel_call["agent_id"]]
    recompute_agent_exposure(agent["id"])
    remaining_credit = agent["credit_limit_cents"] - agent["committed_exposure_cents"]
    order_total = q["provisional_total_cents"]
    if order_total > remaining_credit:
        raise err_credit_limit_exceeded()
    # 5 + 6. stock waterfall (incl. cold-chain capacity gate)
    window_start = db.now_dt()
    window_end = _parse_iso(vessel_call["scheduled_etd"])
    allocations = run_waterfall(q["lines"], window_start, window_end)

    # commit: quotation -> ACCEPTED, requisition -> CLOSED
    q["status"] = "ACCEPTED"
    touch(q)
    requisition["status"] = "CLOSED"
    touch(requisition)

    order_lines = []
    alloc_by_item = {a["catalog_item_id"]: a["allocations"] for a in allocations}
    for line in q["lines"]:
        order_lines.append({
            "catalog_item_id": line["catalog_item_id"],
            "qty_ordered": line["qty"],
            "qty_delivered": 0,
            "unit_price_cents": line["unit_price_cents"],
            "is_substitution": line["is_substitution"],
            "allocations": alloc_by_item.get(line["catalog_item_id"], []),
        })

    # Totals frozen from the quotation's provisional pricing snapshot
    # (PRD §3.4: subtotal_cents, rebate_cents, total_cents frozen; scaffold:
    # total_cents := provisional_total_cents).
    order = {
        "quotation_id": q["id"],
        "agent_id": vessel_call["agent_id"],
        "lines": order_lines,
        "subtotal_cents": q["provisional_subtotal_cents"],
        "rebate_cents": q["provisional_rebate_cents"],
        "total_cents": q["provisional_total_cents"],
        "accepted_at": db.now_iso(),
        "reservation_window_end": vessel_call["scheduled_etd"],
        "fulfillment_status": "OPEN",
        "payment_status": "UNINVOICED",
    }
    stamp_new(order)
    db.orders[order["id"]] = order
    recompute_agent_exposure(agent["id"])
    return success_object(order, status=201)


@bp.route("/chandlery/quotations/<q_id>/withdraw", methods=["POST"])
@require_roles("ChandlerSalesRep")
def withdraw_quotation(user_id, role, q_id):
    q = db.quotations.get(q_id)
    if q is None:
        raise err_quotation_not_found()
    if q["status"] not in ("DRAFT", "SENT"):
        raise err_quotation_not_withdrawable()
    was_sent = q["status"] == "SENT"
    q["status"] = "WITHDRAWN"
    touch(q)
    if was_sent:
        _requisition_fallback_after_sent_gone(q["requisition_id"])
    return success_object(q)


@bp.route("/chandlery/quotations/<q_id>/orders", methods=["GET"])
@require_any_authenticated
def list_quotation_orders(user_id, role, q_id):
    if q_id not in db.quotations:
        raise err_quotation_not_found()
    items = [o for o in db.orders.values() if o["quotation_id"] == q_id]
    items.sort(key=lambda r: r["created_at"])
    limit, offset = parse_pagination(request.args)
    return success_list(items[offset:offset + limit], limit, offset, len(items))

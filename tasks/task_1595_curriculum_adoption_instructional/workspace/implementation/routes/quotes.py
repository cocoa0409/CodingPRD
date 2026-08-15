"""PublisherQuote endpoints (PRD §3.5): listing, evaluation, clarification
loop (with resubmit field updates), withdrawal, and the SELECTED pin-clear
escape hatch."""

from decimal import Decimal

from flask import Blueprint, request

import serializers
from db import bump, refresh, store
from errors import invalid_state
from middleware import (ALL_ROLES, auth_context, get_body, get_or_404, opt_decimal,
                        opt_int, req_enum, require_roles)
from response import paginate, sort_created, success_object
from services.calculations import bundled_pricing_total

bp = Blueprint("quotes", __name__)


def _get_quote(quote_id):
    return get_or_404(store.quotes, quote_id, "PublisherQuote")


@bp.route("/quotes", methods=["GET"])
def list_quotes():
    user_id, role = auth_context()
    require_roles(role, ALL_ROLES)
    items = list(store.quotes.values())
    cycle_id = request.args.get("cycle_id")
    material_id = request.args.get("material_id")
    status = request.args.get("status")
    if cycle_id is not None:
        items = [q for q in items if q["cycle_id"] == cycle_id]
    if material_id is not None:
        items = [q for q in items if q["material_id"] == material_id]
    if status is not None:
        items = [q for q in items if q["status"] == status]
    return paginate(sort_created(items), serializers.quote)


@bp.route("/quotes/<quoteId>", methods=["GET"])
def get_quote(quoteId):
    user_id, role = auth_context()
    require_roles(role, ALL_ROLES)
    return success_object(serializers.quote(_get_quote(quoteId)))


def _apply_resubmit_updates(quote, body):
    """Resubmit may carry updated pricing/service fields (PRD §3.5); each
    supplied field is validated against its usual bounds."""
    if "print_unit_price" in body and body["print_unit_price"] is not None:
        quote["print_unit_price"] = opt_decimal(body, "print_unit_price",
                                                minimum=Decimal("0"))
    if "print_quantity" in body and body["print_quantity"] is not None:
        quote["print_quantity"] = opt_int(body, "print_quantity", minimum=0)
    if "digital_seat_rate" in body and body["digital_seat_rate"] is not None:
        quote["digital_seat_rate"] = opt_decimal(body, "digital_seat_rate",
                                                 minimum=Decimal("0"))
    if "digital_seat_count" in body and body["digital_seat_count"] is not None:
        quote["digital_seat_count"] = opt_int(body, "digital_seat_count", minimum=0)
    if "bundle_discount_pct" in body and body["bundle_discount_pct"] is not None:
        quote["bundle_discount_pct"] = opt_decimal(body, "bundle_discount_pct",
                                                   minimum=Decimal("0"),
                                                   maximum=Decimal("1"))
    if "training_sessions" in body and body["training_sessions"] is not None:
        quote["training_sessions"] = opt_int(body, "training_sessions", minimum=0)
    if "license_years" in body and body["license_years"] is not None:
        quote["license_years"] = opt_int(body, "license_years", minimum=0)


@bp.route("/quotes/<quoteId>/transitions", methods=["POST"])
def quote_transition(quoteId):
    user_id, role = auth_context()
    require_roles(role, ("ProcurementOfficer",))
    quote = _get_quote(quoteId)
    body = get_body()
    to_state = req_enum(body, "to_state",
                        ("UNDER_EVALUATION", "CLARIFICATION_REQUESTED", "WITHDRAWN"))

    if to_state == "UNDER_EVALUATION":
        if quote["status"] == "SUBMITTED":
            pass  # initial evaluation
        elif quote["status"] == "CLARIFICATION_REQUESTED":
            _apply_resubmit_updates(quote, body)  # resubmission
        else:
            raise invalid_state(
                "only a SUBMITTED or CLARIFICATION_REQUESTED quote may enter "
                "UNDER_EVALUATION")
        # evaluated_total computed on entry to UNDER_EVALUATION (both entries).
        quote["evaluated_total"] = bundled_pricing_total(
            quote["print_unit_price"], quote["print_quantity"],
            quote["digital_seat_rate"], quote["digital_seat_count"],
            quote.get("bundle_discount_pct") or Decimal("0"))
    elif to_state == "CLARIFICATION_REQUESTED":
        if quote["status"] not in ("UNDER_EVALUATION", "SELECTED"):
            raise invalid_state(
                "only an UNDER_EVALUATION or SELECTED quote may be sent for "
                "clarification")
        if quote["status"] == "SELECTED":
            # Escape hatch: a quote under clarification is no longer the
            # version the district agreed to buy — clear the cycle pin.
            cycle = store.cycles.get(quote["cycle_id"])
            if cycle is not None and cycle.get("pinned_quote_id") == quote["id"]:
                cycle["pinned_quote_id"] = None
                cycle["quote_version_pin"] = None
                refresh(cycle)
    elif to_state == "WITHDRAWN":
        if quote["status"] not in ("SUBMITTED", "UNDER_EVALUATION",
                                   "CLARIFICATION_REQUESTED"):
            raise invalid_state(
                "only a SUBMITTED, UNDER_EVALUATION, or CLARIFICATION_REQUESTED "
                "quote may be withdrawn")

    quote["status"] = to_state
    bump(quote)
    return success_object(serializers.quote(quote))

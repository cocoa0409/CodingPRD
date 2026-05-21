"""Invoice CRUD, factor, write-off, plus dispute-claim filing under invoice."""

from __future__ import annotations

from flask import Blueprint, g, request

from ..auth import require_auth
from ..envelope import ok_array, ok_object
from ..errors import (
    ApiError,
    ERR_CLAIM_AMOUNT_INVALID,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVOICE_HAS_OPEN_DISPUTE,
    ERR_INVOICE_NOT_DISPUTABLE_AFTER_FACTORING,
    ERR_INVOICE_NOT_FACTORABLE,
    ERR_INVOICE_NOT_FOUND,
    ERR_INVOICE_NOTHING_TO_WRITE_OFF,
    ERR_INVALID_REQUEST,
)
from ..helpers import (
    ensure_shipper_self_access,
    get_body,
    get_brokerage_or_404,
    get_scoped,
    paginate,
    parse_pagination,
    require_field,
)
from ..services.calc import factoring_haircut_cents, factoring_reserve_cents
from ..services.cascade import maybe_auto_settle
from ..store import new_id, store
from ..timeutil import iso_now


invoices_bp = Blueprint("invoices", __name__, url_prefix="/brokerages")


OPEN_CLAIM_STATES = {"OPEN", "IN_REVIEW", "COUNTER_OFFERED"}


def _has_open_dispute(invoice_id: str) -> bool:
    for cl in store.dispute_claims.values():
        if cl.get("invoice_id") == invoice_id and cl.get("status") in OPEN_CLAIM_STATES:
            return True
    return False


@invoices_bp.get("/<brokerage_id>/invoices")
@require_auth(["BrokerOps", "ShipperUser", "PlatformAdmin"])
def list_invoices(brokerage_id):
    limit, offset = parse_pagination()
    shipper_id = request.args.get("shipper_id")
    factoring_status = request.args.get("factoring_status")
    settlement_status = request.args.get("settlement_status")

    with store.lock:
        get_brokerage_or_404(brokerage_id)
        rows = [i for i in store.invoices.values() if i.get("brokerage_id") == brokerage_id]

        # ShipperUser sees only their own invoices
        if g.user_role == "ShipperUser":
            rows = [i for i in rows if i.get("shipper_id") == g.user_id]

        if shipper_id:
            rows = [i for i in rows if i.get("shipper_id") == shipper_id]
        if factoring_status:
            rows = [i for i in rows if i.get("factoring_status") == factoring_status]
        if settlement_status:
            rows = [i for i in rows if i.get("settlement_status") == settlement_status]

        page, total, has_more = paginate(rows, limit, offset)
    return ok_array(page, limit=limit, offset=offset, total_count=total, has_more=has_more)


@invoices_bp.get("/<brokerage_id>/invoices/<invoice_id>")
@require_auth(["BrokerOps", "ShipperUser", "PlatformAdmin"])
def get_invoice(brokerage_id, invoice_id):
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        inv = get_scoped(store.invoices, invoice_id, brokerage_id, ERR_INVOICE_NOT_FOUND)
        if g.user_role == "ShipperUser" and inv.get("shipper_id") != g.user_id:
            raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, 403, "ShipperUser can only view own invoices.")
    return ok_object(inv)


@invoices_bp.post("/<brokerage_id>/invoices/<invoice_id>/factor")
@require_auth(["BrokerOps"])
def factor_invoice(brokerage_id, invoice_id):
    with store.lock:
        bk = get_brokerage_or_404(brokerage_id)
        inv = get_scoped(store.invoices, invoice_id, brokerage_id, ERR_INVOICE_NOT_FOUND)

        # Factoring eligibility (priority 13) BEFORE dispute guard (priority 14
        # is for the opposite direction — POST /dispute-claims).
        if inv.get("settlement_status") != "ISSUED":
            raise ApiError(ERR_INVOICE_NOT_FACTORABLE, 409, "Invoice not in ISSUED.")
        if inv.get("factoring_status") != "NOT_FACTORED":
            raise ApiError(ERR_INVOICE_NOT_FACTORABLE, 409, "Invoice already factored or recoursed.")
        if int(inv.get("balance_due_cents", 0)) != int(inv.get("invoice_total_cents", 0)):
            raise ApiError(ERR_INVOICE_NOT_FACTORABLE, 409, "Invoice has prior payments or credits.")

        if _has_open_dispute(invoice_id):
            raise ApiError(ERR_INVOICE_HAS_OPEN_DISPUTE, 409, "Invoice has an open dispute.")

        total = int(inv["invoice_total_cents"])
        haircut = factoring_haircut_cents(total)
        reserve = factoring_reserve_cents(total, float(bk.get("factoring_reserve_pct", 0)))
        advanced = total - haircut - reserve

        fa = {
            "id": new_id(),
            "created_at": iso_now(),
            "invoice_id": invoice_id,
            "brokerage_id": brokerage_id,
            "invoice_total_at_advance_cents": total,
            "haircut_cents": int(haircut),
            "reserve_cents": int(reserve),
            "advanced_cents": int(advanced),
            "recourse_owed_cents": 0,
        }
        store.factoring_advances[fa["id"]] = fa

        inv["factoring_status"] = "FACTORED"
        inv["amount_paid_cents"] = int(inv.get("amount_paid_cents", 0)) + total
        # recompute balance
        from ..services.cascade import recompute_invoice_balance

        recompute_invoice_balance(inv)
        # Note: per PRD §3.8 the invoice stays ISSUED on the settlement axis while FACTORED.
    return ok_object(fa, status=201)


@invoices_bp.post("/<brokerage_id>/invoices/<invoice_id>/write-off")
@require_auth(["BrokerOps"])
def write_off_invoice(brokerage_id, invoice_id):
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        inv = get_scoped(store.invoices, invoice_id, brokerage_id, ERR_INVOICE_NOT_FOUND)

        balance = int(inv.get("balance_due_cents", 0))
        if balance <= 0:
            raise ApiError(ERR_INVOICE_NOTHING_TO_WRITE_OFF, 409, "Nothing to write off.")

        if _has_open_dispute(invoice_id):
            raise ApiError(ERR_INVOICE_HAS_OPEN_DISPUTE, 409, "Invoice has an open dispute.")

        # Write-off only valid when settlement_status == ISSUED
        if inv.get("settlement_status") != "ISSUED":
            raise ApiError(ERR_INVOICE_NOTHING_TO_WRITE_OFF, 409, "Invoice not in ISSUED.")

        inv["amount_credited_cents"] = int(inv.get("amount_credited_cents", 0)) + balance
        # balance now zero
        inv["balance_due_cents"] = 0
        inv["settlement_status"] = "WRITTEN_OFF"

        # Decrement shipper outstanding by original frozen invoice total
        shipper = store.shippers.get(inv.get("shipper_id"))
        if shipper is not None:
            original_total = int(inv.get("original_invoice_total_cents", inv.get("invoice_total_cents", 0)))
            new_outstanding = int(shipper.get("outstanding_invoiced_cents", 0)) - original_total
            if new_outstanding < 0:
                new_outstanding = 0
            shipper["outstanding_invoiced_cents"] = new_outstanding
            store.bump(shipper)
    return ok_object(inv)


# ---------------------------------------------------------------------------
# Dispute-claim creation (nested under invoice)
# ---------------------------------------------------------------------------
@invoices_bp.post("/<brokerage_id>/invoices/<invoice_id>/dispute-claims")
@require_auth(["ShipperUser"])
def file_dispute_claim(brokerage_id, invoice_id):
    body = get_body()
    VALID_CLAIM_TYPES = {"DAMAGE", "SHORTAGE", "OVERCHARGE", "LATE_DELIVERY"}

    claim_type = require_field(body, "claim_type", str)
    if claim_type not in VALID_CLAIM_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid claim_type.")
    if "claimed_cents" not in body or body["claimed_cents"] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing claimed_cents.")
    claimed = body["claimed_cents"]
    if isinstance(claimed, bool) or not isinstance(claimed, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, "claimed_cents must be an integer.")

    with store.lock:
        get_brokerage_or_404(brokerage_id)
        inv = get_scoped(store.invoices, invoice_id, brokerage_id, ERR_INVOICE_NOT_FOUND)
        if g.user_role == "ShipperUser" and inv.get("shipper_id") != g.user_id:
            raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, 403, "ShipperUser can only file on own invoices.")

        # Per PRD §2.7 + §3.9 the concurrency scenario "factoring wins the race"
        # requires the dispute filing to be rejected with
        # ERR_INVOICE_NOT_DISPUTABLE_AFTER_FACTORING.  Because factoring drives
        # balance_due_cents to zero, the priority-12 amount-sanity check would
        # otherwise mask this case.  We therefore check the factoring guard
        # before the amount-sanity check for any FACTORED/RECOURSED invoice.
        if inv.get("factoring_status") in ("FACTORED", "RECOURSED"):
            raise ApiError(
                ERR_INVOICE_NOT_DISPUTABLE_AFTER_FACTORING,
                409,
                "Cannot dispute a FACTORED/RECOURSED invoice.",
            )

        if int(claimed) <= 0 or int(claimed) > int(inv.get("balance_due_cents", 0)):
            raise ApiError(ERR_CLAIM_AMOUNT_INVALID, 422, "Invalid claimed amount.")

        claim = {
            "invoice_id": invoice_id,
            "brokerage_id": brokerage_id,
            "claim_type": claim_type,
            "claimed_cents": int(claimed),
            "counter_offer_cents": None,
            "settled_credit_cents": None,
            "status": "OPEN",
        }
        store.stamp_create(claim)
        store.dispute_claims[claim["id"]] = claim
    return ok_object(claim, status=201)

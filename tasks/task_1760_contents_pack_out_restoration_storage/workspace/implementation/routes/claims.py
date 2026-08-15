"""HandlingClaim endpoints: file, list by item / by invoice, transitions."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

from db import store
from errors import (
    validation,
    invalid_transition,
    item_terminal,
    sod,
)
from helpers import (
    get_body,
    require_string,
    require_enum,
    require_int,
    optional_string,
    make_common_fields,
    get_item,
    get_claim,
    get_invoice,
    touch,
    job_of_item,
    claims_of_item,
    active_placement_of_item,
)
from middleware import require_roles
from response import success_object, success
from services.cascade import release_active_placement
from services.recompute import recompute_room

bp = Blueprint("claims", __name__)

CLAIM_TYPES = {"LOSS", "DAMAGE"}
CLAIM_ACTIONS = {"SUBMIT_REVIEW", "APPROVE", "DENY", "APPEAL", "SETTLE", "VOID"}
OPEN_CLAIM_STATUSES = {"FILED", "UNDER_REVIEW", "APPROVED"}
TERMINAL_ITEM_STATUSES = {"DISPOSED", "DELIVERED", "CLAIM_SETTLED"}

DEPRECIATION_PCT_PER_YEAR = 10
MAX_DEPRECIATION_PCT = 70
FLOOR_PCT = 30
RCV_CAP_CENTS = 250000


def serialize_claim(c):
    return dict(c)


def compute_settlement(claim, item, job):
    """Compute settlement_amount_cents and settlement_variant per handling_claim_settlement."""
    variant = job["policy_coverage_type"]
    rc = claim["replacement_cost_cents"]
    if variant == "ACV":
        dep_pct = min(claim["item_age_years"] * DEPRECIATION_PCT_PER_YEAR, MAX_DEPRECIATION_PCT)
        acv = Decimal(rc) * (100 - dep_pct) / 100
        floor = Decimal(rc) * FLOOR_PCT / 100
        settlement = max(acv, floor)
        settlement = settlement.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return variant, int(settlement)
    else:  # RCV
        has_accepted = any(
            r["item_id"] == item["id"] and r["status"] == "QA_ACCEPTED"
            for r in store.referrals.values()
        )
        if has_accepted:
            return variant, rc
        return variant, min(rc, RCV_CAP_CENTS)


@bp.route("/api/items/<item_id>/handling-claims", methods=["POST"])
def create_claim(item_id):
    user_id, role = require_roles("ProjectManager", "InventoryTechnician")
    body = get_body()
    claim_type = require_enum(body, "claim_type", CLAIM_TYPES)
    description = require_string(body, "description")
    replacement_cost_cents = require_int(body, "replacement_cost_cents", min_v=0)
    item_age_years = require_int(body, "item_age_years", min_v=0)

    item = get_item(item_id)
    if item["processing_status"] in TERMINAL_ITEM_STATUSES:
        raise item_terminal()
    # one open claim per item
    for c in claims_of_item(item["id"]):
        if c["status"] in OPEN_CLAIM_STATUSES:
            raise invalid_transition("Item already has an open HandlingClaim")

    claim = make_common_fields()
    claim.update({
        "item_id": item["id"],
        "claim_type": claim_type,
        "description": description,
        "replacement_cost_cents": replacement_cost_cents,
        "item_age_years": item_age_years,
        "settlement_variant": None,
        "settlement_amount_cents": None,
        "filed_by_user_id": user_id,
        "credited_invoice_id": None,
        "status": "FILED",
    })
    store.claims[claim["id"]] = claim
    return success_object(serialize_claim(claim), status=201)


@bp.route("/api/items/<item_id>/handling-claims", methods=["GET"])
def list_claims_of_item(item_id):
    user_id, role = require_roles("ProjectManager", "InventoryTechnician", "ClaimsAdjuster")
    item = get_item(item_id)
    claims = claims_of_item(item["id"])
    claims.sort(key=lambda c: c["created_at"])
    return success([serialize_claim(c) for c in claims], status=200, response_type="array")


@bp.route("/api/carrier-invoices/<invoice_id>/handling-claims", methods=["GET"])
def list_claims_of_invoice(invoice_id):
    user_id, role = require_roles("BillingClerk", "ClaimsAdjuster", "CarrierRepresentative")
    invoice = get_invoice(invoice_id)
    claims = [c for c in store.claims.values() if c.get("credited_invoice_id") == invoice["id"]]
    claims.sort(key=lambda c: c["created_at"])
    return success([serialize_claim(c) for c in claims], status=200, response_type="array")


def _settle_claim(claim, item, job, invoice_id=None):
    """Shared settle cascade. Used by direct SETTLE and invoice SUBMIT sweep."""
    claim["status"] = "SETTLED"
    if invoice_id is not None:
        claim["credited_invoice_id"] = invoice_id
    touch(claim)
    if item is not None and item["processing_status"] not in TERMINAL_ITEM_STATUSES:
        was_in_storage = item["processing_status"] == "IN_STORAGE"
        item["processing_status"] = "CLAIM_SETTLED"
        touch(item)
        if was_in_storage:
            release_active_placement(item, "CLAIM")
        room = store.rooms.get(item["room_id"])
        if room is not None:
            recompute_room(room)
            touch(room)


@bp.route("/api/handling-claims/<claim_id>/transition", methods=["POST"])
def transition_claim(claim_id):
    user_id, role = require_roles("ClaimsAdjuster")
    body = get_body()
    action = require_enum(body, "action", CLAIM_ACTIONS)
    claim = get_claim(claim_id)
    item = store.items.get(claim["item_id"])
    job = job_of_item(item) if item is not None else None

    # SoD: APPROVE/DENY/SETTLE actor must differ from filer (priority 3, before state)
    if action in ("APPROVE", "DENY", "SETTLE") and user_id == claim["filed_by_user_id"]:
        raise sod("Approver/denier/settler must differ from filer")

    if action == "SUBMIT_REVIEW":
        if claim["status"] != "FILED":
            raise invalid_transition("Claim is not FILED")
        claim["status"] = "UNDER_REVIEW"
        touch(claim)
    elif action == "APPROVE":
        if claim["status"] != "UNDER_REVIEW":
            raise invalid_transition("Claim is not UNDER_REVIEW")
        if job is None:
            raise invalid_transition("Claim has no associated job")
        variant, amount = compute_settlement(claim, item, job)
        claim["settlement_variant"] = variant
        claim["settlement_amount_cents"] = amount
        claim["status"] = "APPROVED"
        touch(claim)
    elif action == "DENY":
        if claim["status"] != "UNDER_REVIEW":
            raise invalid_transition("Claim is not UNDER_REVIEW")
        claim["status"] = "DENIED"
        touch(claim)
    elif action == "APPEAL":
        if claim["status"] != "DENIED":
            raise invalid_transition("Claim is not DENIED")
        claim["status"] = "UNDER_REVIEW"
        touch(claim)
    elif action == "SETTLE":
        if claim["status"] != "APPROVED":
            raise invalid_transition("Claim is not APPROVED")
        _settle_claim(claim, item, job, invoice_id=None)
    elif action == "VOID":
        if claim["status"] != "APPROVED":
            raise invalid_transition("Claim is not APPROVED")
        if claim.get("credited_invoice_id") is not None:
            raise invalid_transition("Claim already swept into an invoice")
        claim["status"] = "VOIDED"
        touch(claim)
    return success_object(serialize_claim(claim))

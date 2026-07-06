"""All HTTP routes."""
from datetime import timedelta
from flask import Blueprint, request

import db
import services as svc
from middleware import require_role
from response import success, success_list
from errors import (
    APIError, raise_err,
    ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE,
    ERR_ACCOUNT_NOT_FOUND, ERR_ORDER_NOT_FOUND, ERR_RECIPIENT_NOT_FOUND,
    ERR_TEMPLATE_NOT_FOUND, ERR_BRANDING_PROFILE_NOT_FOUND, ERR_SKU_NOT_FOUND,
    ERR_FULFILLMENT_REF_NOT_FOUND, ERR_SUBRESOURCE_NOT_FOUND,
    ERR_INVALID_ORDER_STATE, ERR_INVALID_DECISION_STATE, ERR_INVALID_FULFILLMENT_STATE,
    ERR_ORDER_ALREADY_TERMINAL, ERR_INVALID_SERIES_STATE,
    ERR_PERISHABLE_SAFETY_VIOLATION, ERR_INSUFFICIENT_INVENTORY_CHRONOLOGICAL,
    ERR_BRANDING_PROFILE_NOT_APPROVED, ERR_MESSAGE_PROOF_NOT_LOCKED,
    ERR_SELF_APPROVAL_FORBIDDEN, ERR_SELF_PROOF_APPROVAL_FORBIDDEN,
    ERR_EMPTY_RECIPIENT_LIST, ERR_IMPORT_BATCH_ALL_ROWS_REJECTED,
    ERR_DUPLICATE_RECIPIENT_EMAIL, ERR_INSUFFICIENT_INVENTORY_FORWARD,
    ERR_ASSEMBLY_CAPACITY_EXCEEDED, ERR_SCHEDULED_SEND_IN_PAST,
    ERR_SHIPPING_BLACKOUT_CONFLICT, ERR_BUDGET_EXCEEDED, ERR_STALE_VERSION,
    ERR_BAD_REQUEST,
)

bp = Blueprint("api", __name__)


# ------------- Helpers -------------

def _body():
    b = request.get_json(silent=True)
    if b is None:
        b = {}
    if not isinstance(b, dict):
        raise_err(ERR_BAD_REQUEST, "body must be an object")
    return b


def _pagination():
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise_err(ERR_BAD_REQUEST, "bad pagination")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _paginated(items):
    items_sorted = sorted(items, key=lambda x: x.get("created_at", ""))
    limit, offset = _pagination()
    total = len(items_sorted)
    slice_ = items_sorted[offset:offset + limit]
    return success_list(slice_, limit, offset, total)


def _require_fields(body, fields):
    for f in fields:
        if f not in body:
            raise_err(ERR_BAD_REQUEST, f"missing field: {f}")


# =============================================================================
# Catalog & config (PlatformAdmin)
# =============================================================================

@bp.post("/gift-basket-templates")
def create_template():
    require_role(["PlatformAdmin"])
    b = _body()
    _require_fields(b, ["name", "category", "base_price_cents", "is_perishable", "components"])
    # validate SKU refs
    for c in b["components"]:
        svc.get_sku_or_404(c["sku_id"])
    tid = db.new_id()
    t = {
        "id": tid,
        "name": b["name"],
        "category": b["category"],
        "base_price_cents": b["base_price_cents"],
        "is_perishable": bool(b["is_perishable"]),
        "shelf_life_days": b.get("shelf_life_days"),
        "components": b["components"],
        "active": b.get("active", True),
    }
    db.touch_common_fields(t, is_create=True)
    db.gift_basket_templates[tid] = t
    return success(t, status=201)


@bp.patch("/gift-basket-templates/<tid>")
def patch_template(tid):
    require_role(["PlatformAdmin"])
    t = db.gift_basket_templates.get(tid)
    if not t:
        raise_err(ERR_TEMPLATE_NOT_FOUND)
    b = _body()
    if "base_price_cents" in b:
        t["base_price_cents"] = b["base_price_cents"]
    if "active" in b:
        t["active"] = bool(b["active"])
    if "components" in b:
        for c in b["components"]:
            svc.get_sku_or_404(c["sku_id"])
        t["components"] = b["components"]
    db.touch_common_fields(t, is_create=False)
    return success(t, status=200)


@bp.post("/component-skus")
def create_sku():
    require_role(["PlatformAdmin"])
    b = _body()
    _require_fields(b, ["name", "unit_cost_cents", "is_perishable"])
    sid = db.new_id()
    s = {
        "id": sid,
        "name": b["name"],
        "unit_cost_cents": b["unit_cost_cents"],
        "is_perishable": bool(b["is_perishable"]),
        "shelf_life_days": b.get("shelf_life_days"),
        "on_hand_qty": b.get("on_hand_qty", 0),
    }
    db.touch_common_fields(s, is_create=True)
    db.component_skus[sid] = s
    return success(s, status=201)


@bp.post("/shipping-zones")
def create_zone():
    require_role(["PlatformAdmin"])
    b = _body()
    _require_fields(b, ["zone_code", "country_codes", "carrier", "base_rate_cents",
                        "per_kg_rate_cents", "transit_days_min", "transit_days_max"])
    zid = db.new_id()
    z = {
        "id": zid,
        "zone_code": b["zone_code"],
        "country_codes": b["country_codes"],
        "carrier": b["carrier"],
        "base_rate_cents": b["base_rate_cents"],
        "per_kg_rate_cents": b["per_kg_rate_cents"],
        "transit_days_min": b["transit_days_min"],
        "transit_days_max": b["transit_days_max"],
        "blackout_dates": b.get("blackout_dates", []),
        "created_at": db.now_iso(),
    }
    db.shipping_zones[zid] = z
    return success(z, status=201)


@bp.post("/assembly-stations")
def create_station():
    require_role(["PlatformAdmin"])
    b = _body()
    _require_fields(b, ["name", "daily_capacity"])
    sid = db.new_id()
    s = {
        "id": sid,
        "name": b["name"],
        "daily_capacity": b["daily_capacity"],
        "created_at": db.now_iso(),
    }
    db.assembly_stations[sid] = s
    return success(s, status=201)


# =============================================================================
# CorporateAccount
# =============================================================================

@bp.post("/corporate-accounts")
def create_account():
    require_role(["PlatformAdmin"])
    b = _body()
    _require_fields(b, ["name", "billing_email", "monthly_budget_cents", "approval_threshold_cents"])
    aid = db.new_id()
    a = {
        "id": aid,
        "name": b["name"],
        "billing_email": b["billing_email"],
        "monthly_budget_cents": b["monthly_budget_cents"],
        "approval_threshold_cents": b["approval_threshold_cents"],
        "ytd_spend_cents": 0,
        "status": "ACTIVE",
    }
    db.touch_common_fields(a, is_create=True)
    db.corporate_accounts[aid] = a
    return success(a, status=201)


@bp.get("/corporate-accounts/<aid>")
def get_account(aid):
    require_role(["PlatformAdmin", "AccountManager", "FinanceApprover"])
    a = svc.get_account_or_404(aid)
    return success(a, status=200)


@bp.patch("/corporate-accounts/<aid>/budget")
def patch_account_budget(aid):
    require_role(["PlatformAdmin"])
    a = svc.get_account_or_404(aid)
    b = _body()
    if "monthly_budget_cents" in b:
        a["monthly_budget_cents"] = b["monthly_budget_cents"]
    if "approval_threshold_cents" in b:
        a["approval_threshold_cents"] = b["approval_threshold_cents"]
    db.touch_common_fields(a, is_create=False)
    return success(a, status=200)


# =============================================================================
# BrandingProfile
# =============================================================================

@bp.post("/corporate-accounts/<aid>/branding-profiles")
def create_branding(aid):
    require_role(["AccountManager"])
    a = svc.get_account_or_404(aid)
    b = _body()
    _require_fields(b, ["name", "logo_url", "accent_color", "card_stock",
                        "expected_corporate_account_version"])
    if b["expected_corporate_account_version"] != a["version"]:
        raise_err(ERR_STALE_VERSION)
    bpid = db.new_id()
    bp_row = {
        "id": bpid,
        "corporate_account_id": aid,
        "name": b["name"],
        "logo_url": b["logo_url"],
        "accent_color": b["accent_color"],
        "card_stock": b["card_stock"],
        "approved": False,
    }
    db.touch_common_fields(bp_row, is_create=True)
    db.branding_profiles[bpid] = bp_row
    db.touch_common_fields(a, is_create=False)  # increments account.version
    return success(bp_row, status=201)


@bp.get("/corporate-accounts/<aid>/branding-profiles")
def list_branding(aid):
    require_role(["AccountManager", "PlatformAdmin"])
    svc.get_account_or_404(aid)
    items = [b for b in db.branding_profiles.values() if b["corporate_account_id"] == aid]
    return _paginated(items)


@bp.post("/branding-profiles/<bpid>/approve")
def approve_branding(bpid):
    require_role(["PlatformAdmin"])
    bp_row = db.branding_profiles.get(bpid)
    if not bp_row:
        # Not enumerated in path-validation aliases; use SUBRESOURCE not-found for consistency
        raise_err(ERR_BRANDING_PROFILE_NOT_FOUND)
    bp_row["approved"] = True
    db.touch_common_fields(bp_row, is_create=False)
    return success(bp_row, status=200)


# =============================================================================
# CorporateOrder
# =============================================================================

@bp.post("/corporate-accounts/<aid>/orders")
def create_order(aid):
    require_role(["AccountManager"])
    a = svc.get_account_or_404(aid)
    b = _body()
    _require_fields(b, ["template_id", "occasion", "expected_corporate_account_version"])
    t = svc.get_template_or_404_active_required(b["template_id"])
    branding_id = b.get("branding_profile_id")
    if branding_id is not None:
        svc.get_branding_or_404(branding_id, account_id=aid)
    # scheduled_send_date temporal check (strictly > now)
    sched_iso = b.get("scheduled_send_date")
    if sched_iso is not None:
        try:
            sched_dt = db.parse_iso(sched_iso)
        except Exception:
            raise_err(ERR_BAD_REQUEST, "bad scheduled_send_date")
        if not (sched_dt > db.clock_now()):
            raise_err(ERR_SCHEDULED_SEND_IN_PAST)
    if b["expected_corporate_account_version"] != a["version"]:
        raise_err(ERR_STALE_VERSION)
    oid = db.new_id()
    o = {
        "id": oid,
        "corporate_account_id": aid,
        "template_id": b["template_id"],
        "branding_profile_id": branding_id,
        "occasion": b["occasion"],
        "scheduled_send_date": sched_iso,
        "approval_status": "DRAFT",
        "production_status": "DRAFT",
        "locked_template_version": None,
        "locked_branding_version": None,
        "subtotal_cents": 0,
        "total_cost_cents": 0,
        "requires_approval": False,
    }
    db.touch_common_fields(o, is_create=True)
    db.corporate_orders[oid] = o
    db.touch_common_fields(a, is_create=False)
    return success(o, status=201)


@bp.get("/orders")
def list_orders():
    require_role(["AccountManager", "FinanceApprover", "PlatformAdmin"])
    q = request.args
    items = list(db.corporate_orders.values())
    if "corporate_account_id" in q:
        items = [o for o in items if o["corporate_account_id"] == q["corporate_account_id"]]
    if "template_id" in q:
        items = [o for o in items if o["template_id"] == q["template_id"]]
    if "branding_profile_id" in q:
        items = [o for o in items if o.get("branding_profile_id") == q["branding_profile_id"]]
    if "approval_status" in q:
        items = [o for o in items if o["approval_status"] == q["approval_status"]]
    if "production_status" in q:
        items = [o for o in items if o["production_status"] == q["production_status"]]
    return _paginated(items)


@bp.get("/orders/<oid>")
def get_order(oid):
    require_role(["AccountManager", "FinanceApprover", "WarehouseOps", "ShippingOps", "PlatformAdmin"])
    o = svc.get_order_or_404(oid)
    return success(o, status=200)


@bp.post("/orders/<oid>/recipients/import")
def import_recipients(oid):
    require_role(["AccountManager"])
    o = svc.get_order_or_404(oid)
    b = _body()
    _require_fields(b, ["rows"])
    rows = b["rows"]
    if not isinstance(rows, list):
        raise_err(ERR_BAD_REQUEST, "rows must be array")
    template = db.gift_basket_templates.get(o["template_id"])
    projection_dt = (
        db.parse_iso(o["scheduled_send_date"]) if o.get("scheduled_send_date")
        else db.clock_now()
    )
    # Track ACCEPTED emails as we go (batch + existing).
    accepted_emails = {
        r["email"] for r in db.recipients.values()
        if r["corporate_order_id"] == oid and r["import_row_status"] == "ACCEPTED"
    }
    created_records = []
    accepted_count = 0
    for row in rows:
        # Build recipient shell.
        rid = db.new_id()
        rec = {
            "id": rid,
            "corporate_order_id": oid,
            "full_name": row.get("full_name"),
            "email": row.get("email"),
            "shipping_address_line1": row.get("shipping_address_line1"),
            "city": row.get("city"),
            "state_code": row.get("state_code"),
            "postal_code": row.get("postal_code"),
            "country_code": row.get("country_code"),
            "quantity": row.get("quantity", 1),
            "import_row_status": "ACCEPTED",
        }
        # Per-row check 1: duplicate email
        email = rec.get("email")
        if email is None or email in accepted_emails:
            rec["import_row_status"] = "REJECTED"
        else:
            # Per-row check 2: forward-looking inventory
            insufficient = False
            for comp in template.get("components", []):
                need = comp["quantity"] * rec["quantity"]
                avail = svc.component_available_qty_forward_looking(comp["sku_id"], projection_dt)
                if avail < need:
                    insufficient = True
                    break
            if insufficient:
                rec["import_row_status"] = "REJECTED"
            else:
                # Accepted — create InventoryReservation per SKU.
                accepted_emails.add(email)
        db.touch_common_fields(rec, is_create=True)
        db.recipients[rid] = rec
        if rec["import_row_status"] == "ACCEPTED":
            accepted_count += 1
            for comp in template.get("components", []):
                sku = db.component_skus[comp["sku_id"]]
                irid = db.new_id()
                expires_at = None
                if sku.get("is_perishable"):
                    exp = db.clock_now() + timedelta(days=sku["shelf_life_days"])
                    expires_at = db.format_iso(exp)
                res = {
                    "id": irid,
                    "recipient_id": rid,
                    "sku_id": sku["id"],
                    "reserved_qty": comp["quantity"] * rec["quantity"],
                    "status": "RESERVED",
                    "expires_at": expires_at,
                }
                db.touch_common_fields(res, is_create=True)
                db.inventory_reservations[irid] = res
        created_records.append(rec)
    if accepted_count == 0:
        # Roll back: remove any recipients created this call.
        for rec in created_records:
            db.recipients.pop(rec["id"], None)
        raise_err(ERR_IMPORT_BATCH_ALL_ROWS_REJECTED)
    return success(created_records, status=201, response_type="array")


@bp.get("/orders/<oid>/recipients")
def list_order_recipients(oid):
    require_role(["AccountManager", "WarehouseOps", "ShippingOps", "PlatformAdmin"])
    svc.get_order_or_404(oid)
    items = [r for r in db.recipients.values() if r["corporate_order_id"] == oid]
    return _paginated(items)


@bp.post("/orders/<oid>/submit-for-approval")
def submit_for_approval(oid):
    require_role(["AccountManager"])
    o = svc.get_order_or_404(oid)
    b = _body()
    _require_fields(b, ["requested_by_user_id"])
    # p11: order state
    if o["approval_status"] not in ("DRAFT", "REJECTED") or o["production_status"] == "CANCELLED":
        raise_err(ERR_INVALID_ORDER_STATE)
    # p22: at least one ACCEPTED recipient
    accepted = svc._order_recipients(oid, only_accepted=True)
    if len(accepted) < 1:
        raise_err(ERR_EMPTY_RECIPIENT_LIST)
    # p27: scheduled_send_date strictly > now
    if o.get("scheduled_send_date") is not None:
        sched_dt = db.parse_iso(o["scheduled_send_date"])
        if not (sched_dt > db.clock_now()):
            raise_err(ERR_SCHEDULED_SEND_IN_PAST)
    account = db.corporate_accounts[o["corporate_account_id"]]
    # Run provisional pricing.
    computed = svc.compute_order_pricing(o, account)
    requires_approval = computed["requires_approval"]

    if requires_approval:
        # Human approval path: apply pricing, create/reset BudgetApproval, move to PENDING_APPROVAL.
        svc.apply_order_pricing(o, computed)
        ba = svc._find_budget_approval(oid)
        if ba is None:
            ba_id = db.new_id()
            ba = {
                "id": ba_id,
                "corporate_order_id": oid,
                "requested_by_user_id": b["requested_by_user_id"],
                "approver_user_id": None,
                "decision": "PENDING",
                "decision_reason": None,
                "decided_at": None,
            }
            db.touch_common_fields(ba, is_create=True)
            db.budget_approvals[ba_id] = ba
        else:
            ba["requested_by_user_id"] = b["requested_by_user_id"]
            ba["approver_user_id"] = None
            ba["decision"] = "PENDING"
            ba["decided_at"] = None
            db.touch_common_fields(ba, is_create=False)
        o["approval_status"] = "PENDING_APPROVAL"
        db.touch_common_fields(o, is_create=False)
        return success(o, status=200)

    # Auto-approval path — atomic: no BudgetApproval row persists on failure.
    station_id = b.get("station_id")
    scheduled_date = b.get("scheduled_date")
    if station_id is None or scheduled_date is None:
        raise_err(ERR_FULFILLMENT_REF_NOT_FOUND)  # can't auto-approve without station+date
    if station_id not in db.assembly_stations:
        raise_err(ERR_FULFILLMENT_REF_NOT_FOUND)
    try:
        sched_dt_for_prod = db.parse_iso(scheduled_date)
    except Exception:
        raise_err(ERR_BAD_REQUEST, "bad scheduled_date")

    # Validation priority order for auto-approval path (same as budget-decision APPROVE).
    # All checks run BEFORE any mutation is committed to the order, so a failure
    # leaves the order exactly as it was (still DRAFT) with no BudgetApproval row.
    # 16 perishable safety
    svc.check_perishable_safety(o, sched_dt_for_prod)
    # For chronological inventory we need reservations to exist (they do — created at import).
    svc.check_chronological_availability_for_order(o)
    # 18 branding approved
    if o.get("branding_profile_id"):
        bpp = db.branding_profiles[o["branding_profile_id"]]
        if not bpp.get("approved"):
            raise_err(ERR_BRANDING_PROFILE_NOT_APPROVED)
    # 26 assembly capacity
    total_qty = sum(r["quantity"] for r in accepted)
    svc.check_assembly_capacity(station_id, sched_dt_for_prod, oid, total_qty)
    # 29 budget hard cap (uses computed total_cost_cents from provisional pricing)
    if account["ytd_spend_cents"] + computed["total_cost_cents"] > account["monthly_budget_cents"]:
        raise_err(ERR_BUDGET_EXCEEDED)
    # All checks pass — now commit pricing.
    svc.apply_order_pricing(o, computed)

    # All checks pass — persist BudgetApproval (as APPROVED), fire cascade.
    ba_id = db.new_id()
    ba = {
        "id": ba_id,
        "corporate_order_id": oid,
        "requested_by_user_id": b["requested_by_user_id"],
        "approver_user_id": None,
        "decision": "APPROVED",
        "decision_reason": None,
        "decided_at": db.now_iso(),
    }
    db.touch_common_fields(ba, is_create=True)
    db.budget_approvals[ba_id] = ba
    # move approval_status to PENDING_APPROVAL first (per state machine), then APPROVE cascade
    o["approval_status"] = "PENDING_APPROVAL"
    svc.do_approve_cascade(o, account, approver_user_id=None,
                           station_id=station_id, scheduled_dt=sched_dt_for_prod,
                           scheduled_date_raw=scheduled_date)
    return success(o, status=200)


@bp.post("/orders/<oid>/budget-decision")
def budget_decision(oid):
    require_role(["FinanceApprover"])
    o = svc.get_order_or_404(oid)
    b = _body()
    _require_fields(b, ["decision", "approver_user_id"])
    decision = b["decision"]
    if decision not in ("APPROVE", "REJECT"):
        raise_err(ERR_BAD_REQUEST, "bad decision")
    # priority ordering:
    # 4 order not found done. 9 fulfillment ref (only for APPROVE)
    # 12 decision state.
    ba = svc._find_budget_approval(oid)
    if not ba or ba["decision"] != "PENDING":
        # 9 must come first per PRD: "the fulfillment-reference existence check firing first,
        # then the decision-state check"
        if decision == "APPROVE":
            station_id = b.get("station_id")
            if station_id is None or station_id not in db.assembly_stations:
                raise_err(ERR_FULFILLMENT_REF_NOT_FOUND)
        raise_err(ERR_INVALID_DECISION_STATE)
    if decision == "APPROVE":
        # 9 fulfillment_ref
        station_id = b.get("station_id")
        scheduled_date = b.get("scheduled_date")
        if station_id is None or station_id not in db.assembly_stations:
            raise_err(ERR_FULFILLMENT_REF_NOT_FOUND)
        if scheduled_date is None:
            raise_err(ERR_BAD_REQUEST, "missing scheduled_date")
        try:
            sched_dt_for_prod = db.parse_iso(scheduled_date)
        except Exception:
            raise_err(ERR_BAD_REQUEST, "bad scheduled_date")
        account = db.corporate_accounts[o["corporate_account_id"]]
        # 16 perishable safety
        svc.check_perishable_safety(o, sched_dt_for_prod)
        # 17 chronological inventory
        svc.check_chronological_availability_for_order(o)
        # 18 branding approved
        if o.get("branding_profile_id"):
            bpp = db.branding_profiles[o["branding_profile_id"]]
            if not bpp.get("approved"):
                raise_err(ERR_BRANDING_PROFILE_NOT_APPROVED)
        # 20 self-approval segregation
        if b["approver_user_id"] == ba["requested_by_user_id"]:
            raise_err(ERR_SELF_APPROVAL_FORBIDDEN)
        # 26 assembly capacity
        accepted = svc._order_recipients(oid, only_accepted=True)
        total_qty = sum(r["quantity"] for r in accepted)
        svc.check_assembly_capacity(station_id, sched_dt_for_prod, oid, total_qty)
        # need total_cost for 29 — compute final and apply now (pin moment).
        # 29 budget hard cap (uses total_cost_cents recomputed final)
        computed_final = svc.compute_order_pricing(o, account)
        if account["ytd_spend_cents"] + computed_final["total_cost_cents"] > account["monthly_budget_cents"]:
            raise_err(ERR_BUDGET_EXCEEDED)
        # All checks pass — fire cascade.
        svc.do_approve_cascade(o, account, approver_user_id=b["approver_user_id"],
                               station_id=station_id, scheduled_dt=sched_dt_for_prod,
                               scheduled_date_raw=scheduled_date)
        return success(o, status=200)
    else:
        # REJECT: 20 self-approval segregation still applies
        if b["approver_user_id"] == ba["requested_by_user_id"]:
            raise_err(ERR_SELF_APPROVAL_FORBIDDEN)
        ba["decision"] = "REJECTED"
        ba["approver_user_id"] = b["approver_user_id"]
        ba["decision_reason"] = b.get("decision_reason")
        ba["decided_at"] = db.now_iso()
        db.touch_common_fields(ba, is_create=False)
        o["approval_status"] = "REJECTED"
        db.touch_common_fields(o, is_create=False)
        return success(o, status=200)


@bp.post("/orders/<oid>/cancel")
def cancel_order(oid):
    require_role(["AccountManager", "PlatformAdmin"])
    o = svc.get_order_or_404(oid)
    if o["production_status"] not in ("DRAFT", "ASSEMBLING"):
        raise_err(ERR_ORDER_ALREADY_TERMINAL)
    svc.cancel_order(o)
    return success(o, status=200)


@bp.get("/orders/<oid>/budget-approvals")
def list_budget_approvals(oid):
    require_role(["AccountManager", "FinanceApprover", "PlatformAdmin"])
    svc.get_order_or_404(oid)
    items = [ba for ba in db.budget_approvals.values() if ba["corporate_order_id"] == oid]
    return _paginated(items)


@bp.get("/recipients/<rid>")
def get_recipient(rid):
    require_role(["AccountManager", "WarehouseOps", "ShippingOps", "PlatformAdmin"])
    r = svc.get_recipient_or_404(rid)
    return success(r, status=200)


# =============================================================================
# MessageProof
# =============================================================================

@bp.post("/recipients/<rid>/message-proof")
def create_message_proof(rid):
    require_role(["AccountManager"])
    r = svc.get_recipient_or_404(rid)
    b = _body()
    _require_fields(b, ["message_text", "submitted_by_user_id"])
    # find existing MessageProof for this recipient (0 or 1)
    mp = None
    for m in db.message_proofs.values():
        if m["recipient_id"] == rid:
            mp = m
            break
    if mp is None:
        mp_id = db.new_id()
        mp = {
            "id": mp_id,
            "recipient_id": rid,
            "message_text": b["message_text"],
            "proof_status": "SUBMITTED",
            "revision_count": 0,
            "submitted_by_user_id": b["submitted_by_user_id"],
            "decided_by_user_id": None,
        }
        db.touch_common_fields(mp, is_create=True)
        db.message_proofs[mp_id] = mp
        return success(mp, status=201)
    else:
        if mp["proof_status"] not in ("DRAFT", "REVISION_REQUESTED"):
            raise_err(ERR_INVALID_DECISION_STATE)
        mp["message_text"] = b["message_text"]
        mp["submitted_by_user_id"] = b["submitted_by_user_id"]
        mp["proof_status"] = "SUBMITTED"
        db.touch_common_fields(mp, is_create=False)
        return success(mp, status=201)


@bp.get("/recipients/<rid>/message-proof")
def get_message_proof(rid):
    require_role(["AccountManager", "ProofApprover"])
    svc.get_recipient_or_404(rid)
    items = [m for m in db.message_proofs.values() if m["recipient_id"] == rid]
    return _paginated(items)


@bp.post("/message-proofs/<mpid>/decision")
def decide_message_proof(mpid):
    require_role(["ProofApprover"])
    mp = db.message_proofs.get(mpid)
    if not mp:
        raise_err(ERR_SUBRESOURCE_NOT_FOUND)
    b = _body()
    _require_fields(b, ["decision", "decided_by_user_id"])
    decision = b["decision"]
    if decision not in ("APPROVE", "REQUEST_REVISION"):
        raise_err(ERR_BAD_REQUEST, "bad decision")
    if mp["proof_status"] != "SUBMITTED":
        raise_err(ERR_INVALID_DECISION_STATE)
    # p21 SoD
    if b["decided_by_user_id"] == mp["submitted_by_user_id"]:
        raise_err(ERR_SELF_PROOF_APPROVAL_FORBIDDEN)
    if decision == "APPROVE":
        mp["proof_status"] = "APPROVED"
        mp["decided_by_user_id"] = b["decided_by_user_id"]
        # Immediately advance to LOCKED
        mp["proof_status"] = "LOCKED"
        db.touch_common_fields(mp, is_create=False)
    else:
        mp["proof_status"] = "REVISION_REQUESTED"
        mp["decided_by_user_id"] = b["decided_by_user_id"]
        mp["revision_count"] = mp.get("revision_count", 0) + 1
        # Immediately advance to DRAFT
        mp["proof_status"] = "DRAFT"
        db.touch_common_fields(mp, is_create=False)
    return success(mp, status=200)


# =============================================================================
# Inventory & Assembly
# =============================================================================

@bp.get("/inventory-reservations")
def list_reservations():
    require_role(["WarehouseOps", "AccountManager"])
    q = request.args
    items = list(db.inventory_reservations.values())
    if "recipient_id" in q:
        items = [r for r in items if r["recipient_id"] == q["recipient_id"]]
    if "sku_id" in q:
        items = [r for r in items if r["sku_id"] == q["sku_id"]]
    if "status" in q:
        items = [r for r in items if r["status"] == q["status"]]
    return _paginated(items)


@bp.get("/inventory-reservations/<rid>")
def get_reservation(rid):
    require_role(["WarehouseOps", "AccountManager"])
    r = db.inventory_reservations.get(rid)
    if not r:
        raise_err(ERR_SUBRESOURCE_NOT_FOUND)
    return success(r, status=200)


@bp.get("/assembly-tasks")
def list_assembly_tasks():
    require_role(["WarehouseOps"])
    q = request.args
    items = list(db.assembly_tasks.values())
    if "recipient_id" in q:
        items = [t for t in items if t["recipient_id"] == q["recipient_id"]]
    if "station_id" in q:
        items = [t for t in items if t["station_id"] == q["station_id"]]
    if "status" in q:
        items = [t for t in items if t["status"] == q["status"]]
    return _paginated(items)


@bp.get("/assembly-tasks/<tid>")
def get_assembly_task(tid):
    require_role(["WarehouseOps"])
    t = db.assembly_tasks.get(tid)
    if not t:
        raise_err(ERR_SUBRESOURCE_NOT_FOUND)
    return success(t, status=200)


@bp.post("/assembly-tasks/<tid>/advance")
def advance_assembly_task(tid):
    require_role(["WarehouseOps"])
    t = db.assembly_tasks.get(tid)
    if not t:
        raise_err(ERR_SUBRESOURCE_NOT_FOUND)
    b = _body()
    _require_fields(b, ["target_status"])
    target = b["target_status"]
    cur = t["status"]
    legal = False
    if target == "IN_PROGRESS" and cur == "QUEUED":
        legal = True
    elif target == "COMPLETE" and cur == "IN_PROGRESS":
        legal = True
    elif target == "FAILED" and cur in ("QUEUED", "IN_PROGRESS"):
        legal = True
    if not legal:
        raise_err(ERR_INVALID_FULFILLMENT_STATE)
    t["status"] = target
    db.touch_common_fields(t, is_create=False)
    if target == "COMPLETE":
        # Decrement on_hand_qty for every SKU in the recipient's basket composition.
        recipient = db.recipients.get(t["recipient_id"])
        if recipient:
            for res in db.inventory_reservations.values():
                if res["recipient_id"] == recipient["id"]:
                    sku = db.component_skus.get(res["sku_id"])
                    if sku:
                        sku["on_hand_qty"] = max(0, sku["on_hand_qty"] - res["reserved_qty"])
                        db.touch_common_fields(sku, is_create=False)
        svc.maybe_advance_after_assembly_task_change(t)
    return success(t, status=200)


# =============================================================================
# Shipment
# =============================================================================

@bp.get("/shipments")
def list_shipments():
    require_role(["ShippingOps", "AccountManager"])
    q = request.args
    items = list(db.shipments.values())
    if "recipient_id" in q:
        items = [s for s in items if s["recipient_id"] == q["recipient_id"]]
    if "zone_id" in q:
        items = [s for s in items if s["zone_id"] == q["zone_id"]]
    if "status" in q:
        items = [s for s in items if s["status"] == q["status"]]
    return _paginated(items)


@bp.get("/shipments/<sid>")
def get_shipment(sid):
    require_role(["ShippingOps", "AccountManager"])
    s = db.shipments.get(sid)
    if not s:
        raise_err(ERR_SUBRESOURCE_NOT_FOUND)
    return success(s, status=200)


@bp.post("/recipients/<rid>/shipments")
def create_shipment(rid):
    require_role(["ShippingOps"])
    r = svc.get_recipient_or_404(rid)
    b = _body()
    _require_fields(b, ["zone_id", "ship_date"])
    zone_id = b["zone_id"]
    if zone_id not in db.shipping_zones:
        raise_err(ERR_FULFILLMENT_REF_NOT_FOUND)
    # p19: MessageProof must be LOCKED
    mp = None
    for m in db.message_proofs.values():
        if m["recipient_id"] == rid:
            mp = m
            break
    if mp is None or mp["proof_status"] != "LOCKED":
        raise_err(ERR_MESSAGE_PROOF_NOT_LOCKED)
    zone = db.shipping_zones[zone_id]
    try:
        ship_dt = db.parse_iso(b["ship_date"])
    except Exception:
        raise_err(ERR_BAD_REQUEST, "bad ship_date")
    # blackout / transit check (p28)
    # half-open [ship_date, ship_date + transit_days_min) contains no blackout date
    black = set(zone.get("blackout_dates", []))
    for d_offset in range(zone["transit_days_min"]):
        day = (ship_dt + timedelta(days=d_offset)).date().isoformat()
        if day in black:
            raise_err(ERR_SHIPPING_BLACKOUT_CONFLICT)
    # ship_date + transit_days_max <= scheduled_send_date when set
    order = db.corporate_orders.get(r["corporate_order_id"])
    if order and order.get("scheduled_send_date"):
        latest_arrival = ship_dt + timedelta(days=zone["transit_days_max"])
        sched = db.parse_iso(order["scheduled_send_date"])
        if latest_arrival > sched:
            raise_err(ERR_SHIPPING_BLACKOUT_CONFLICT)
    # cost calc
    from decimal import Decimal
    est_weight = svc.TEMPLATE_BASE_WEIGHT_KG * Decimal(r["quantity"])
    per_shipment = svc.round_half_up_int(
        Decimal(zone["base_rate_cents"]) + Decimal(zone["per_kg_rate_cents"]) * est_weight
    )
    sid = db.new_id()
    s = {
        "id": sid,
        "recipient_id": rid,
        "zone_id": zone_id,
        "ship_date": b["ship_date"],
        "tracking_number": None,
        "status": "CREATED",
        "shipping_cost_cents": per_shipment,
        "delivered_at": None,
    }
    db.touch_common_fields(s, is_create=True)
    db.shipments[sid] = s
    return success(s, status=201)


@bp.post("/shipments/<sid>/advance")
def advance_shipment(sid):
    require_role(["ShippingOps"])
    s = db.shipments.get(sid)
    if not s:
        raise_err(ERR_SUBRESOURCE_NOT_FOUND)
    b = _body()
    _require_fields(b, ["target_status"])
    target = b["target_status"]
    cur = s["status"]
    legal = False
    if target == "LABEL_GENERATED" and cur == "CREATED":
        legal = True
    elif target == "IN_TRANSIT" and cur == "LABEL_GENERATED":
        legal = True
    elif target == "DELIVERED" and cur == "IN_TRANSIT":
        legal = True
    elif target == "EXCEPTION" and cur in ("LABEL_GENERATED", "IN_TRANSIT"):
        legal = True
    elif target == "RETURNED" and cur == "EXCEPTION":
        legal = True
    if not legal:
        raise_err(ERR_INVALID_FULFILLMENT_STATE)
    s["status"] = target
    if target == "LABEL_GENERATED":
        s["tracking_number"] = "TRK-" + db.new_id().replace("-", "")[:12].upper()
    if target == "DELIVERED":
        s["delivered_at"] = db.now_iso()
    db.touch_common_fields(s, is_create=False)
    svc.maybe_advance_after_shipment_change(s)
    return success(s, status=200)


# =============================================================================
# RecurringOrderSeries
# =============================================================================

@bp.post("/corporate-accounts/<aid>/recurring-series")
def create_recurring(aid):
    require_role(["AccountManager"])
    svc.get_account_or_404(aid)
    b = _body()
    _require_fields(b, ["source_order_id", "interval_days"])
    # source_order_id: validate it exists as a CorporateOrder; treat missing as SUBRESOURCE_NOT_FOUND
    src = db.corporate_orders.get(b["source_order_id"])
    if not src:
        raise_err(ERR_ORDER_NOT_FOUND)
    interval = b["interval_days"]
    next_run = db.clock_now() + timedelta(days=interval)
    sid = db.new_id()
    s = {
        "id": sid,
        "corporate_account_id": aid,
        "source_order_id": b["source_order_id"],
        "interval_days": interval,
        "next_run_date": db.format_iso(next_run),
        "active": True,
        "last_generated_order_id": None,
    }
    db.touch_common_fields(s, is_create=True)
    db.recurring_series[sid] = s
    return success(s, status=201)


@bp.get("/recurring-series")
def list_recurring():
    require_role(["AccountManager", "PlatformAdmin"])
    q = request.args
    items = list(db.recurring_series.values())
    if "corporate_account_id" in q:
        items = [s for s in items if s["corporate_account_id"] == q["corporate_account_id"]]
    return _paginated(items)


@bp.get("/recurring-series/<sid>")
def get_recurring(sid):
    require_role(["AccountManager", "PlatformAdmin"])
    s = db.recurring_series.get(sid)
    if not s:
        raise_err(ERR_SUBRESOURCE_NOT_FOUND)
    return success(s, status=200)


@bp.patch("/recurring-series/<sid>")
def patch_recurring(sid):
    require_role(["AccountManager"])
    s = db.recurring_series.get(sid)
    if not s:
        raise_err(ERR_SUBRESOURCE_NOT_FOUND)
    b = _body()
    _require_fields(b, ["active"])
    target_active = bool(b["active"])
    if s["active"] == target_active:
        raise_err(ERR_INVALID_SERIES_STATE)
    s["active"] = target_active
    if target_active is True:
        # resume: recompute next_run_date
        next_run = db.clock_now() + timedelta(days=s["interval_days"])
        s["next_run_date"] = db.format_iso(next_run)
    db.touch_common_fields(s, is_create=False)
    return success(s, status=200)


# =============================================================================
# Clock
# =============================================================================

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_role(["PlatformAdmin"])
    b = _body()
    _require_fields(b, ["to_iso8601"])
    try:
        target = db.parse_iso(b["to_iso8601"])
    except Exception:
        raise_err(ERR_BAD_REQUEST, "bad to_iso8601")
    db.clock_set(target)
    db.maybe_reset_ytd_on_mutation()
    svc.sweep_after_clock_advance()
    return success({}, status=200)

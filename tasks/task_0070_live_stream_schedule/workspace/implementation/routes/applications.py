"""ScheduleApplication endpoints — create/read/list + state transitions.

All transitions enforce preconditions in the priority order defined by the
SCAFFOLD's `validations` section.
"""

from datetime import timedelta

from flask import Blueprint, request

import db
import clock
from errors import (
    ERR_DEPOSIT_UNPAID,
    ERR_FORBIDDEN,
    ERR_INVALID_INTERVAL,
    ERR_INVALID_STATE,
    ERR_LIVE_ASSOCIATION_DENIED,
    ERR_NOT_FOUND,
    ERR_OUT_OF_AVAILABLE_WINDOW,
    ERR_QUALIFICATION_MISSING,
    ERR_REASON_REQUIRED,
    ERR_STOCK_INSUFFICIENT,
    ERR_STREAMER_BLOCKED,
    ERR_STREAMER_NOT_ACTIVE,
    ERR_STUDIO_INTERVAL_CONFLICT,
    ERR_TOO_LATE_TO_CANCEL,
    ERR_VALIDATION_FAILED,
    raise_err,
)
from middleware import (
    occ_check, paginate, parse_pagination, require_auth, require_role,
)
from response import success
from services import audit
from services.calculations import (
    calc_commission_provisional, calc_refund, calc_slot_fee, deposit_for_total,
)
from services.intervals import (
    interval_fully_available, studio_interval_conflict,
)
from services.product_associations import (
    eligibility_error, release_all_for_application,
)
from services.streamer_service import apply_cascade


bp = Blueprint("applications", __name__, url_prefix="/live-schedule/applications")


_VALID_PACKAGES = {"STANDARD", "COMBO_HALF_DAY", "COMBO_FULL_DAY", "PEAK_BUNDLE"}
MAX_ASSOCIATIONS = 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_application_or_404(app_id: str) -> dict:
    app = db.raw_get("applications", app_id)
    if app is None:
        raise_err(ERR_NOT_FOUND, "Application not found")
    return app


def _check_streamer_ownership(role: str, user_id: str, app: dict) -> None:
    if role == "Streamer" and app.get("streamer_id") != user_id:
        raise_err(ERR_FORBIDDEN, "Streamer does not own this application")


def _slot_fee_for(app: dict, tier: str) -> dict:
    studio = db.raw_get("studios", app["studio_id"])
    return calc_slot_fee(
        base_hour_price_cents=studio["base_hour_price_cents"],
        starts_at=clock.parse_iso(app["starts_at"]),
        ends_at=clock.parse_iso(app["ends_at"]),
        tier=tier,
        package_code=app["package_code"],
    )


# ---------------------------------------------------------------------------
# Create draft application
# ---------------------------------------------------------------------------

@bp.post("")
def create_application():
    user_id, role = require_auth()
    require_role(role, ["Streamer"])
    body = request.get_json(silent=True) or {}

    for key in ("streamer_id", "studio_id", "starts_at", "ends_at",
                "declared_content_categories", "declared_product_categories"):
        if key not in body:
            raise_err(ERR_VALIDATION_FAILED, f"Missing field: {key}")

    if body["streamer_id"] != user_id:
        raise_err(ERR_FORBIDDEN, "streamer_id must equal X-User-ID")

    streamer = db.raw_get("streamers", body["streamer_id"])
    if streamer is None:
        raise_err(ERR_NOT_FOUND, "Streamer not found")
    studio = db.raw_get("studios", body["studio_id"])
    if studio is None:
        raise_err(ERR_NOT_FOUND, "Studio not found")

    # Streamer must be ACTIVE for creation (streamer-initiated mutation).
    if streamer.get("status") != "ACTIVE":
        raise_err(ERR_STREAMER_NOT_ACTIVE, "Streamer is not ACTIVE")

    package_code = body.get("package_code", "STANDARD") or "STANDARD"
    if package_code not in _VALID_PACKAGES:
        raise_err(ERR_VALIDATION_FAILED, "Invalid package_code")

    starts_at = clock.parse_iso(body["starts_at"])
    ends_at = clock.parse_iso(body["ends_at"])
    if ends_at <= starts_at:
        raise_err(ERR_INVALID_INTERVAL, "ends_at must be > starts_at")
    duration = (ends_at - starts_at).total_seconds()
    if duration < 30 * 60 or duration > 8 * 3600:
        raise_err(ERR_INVALID_INTERVAL, "Duration must be in [30min, 8h]")

    payload = {
        "streamer_id": body["streamer_id"],
        "studio_id": body["studio_id"],
        "starts_at": body["starts_at"],
        "ends_at": body["ends_at"],
        "declared_content_categories": list(body["declared_content_categories"]),
        "declared_product_categories": list(body["declared_product_categories"]),
        "package_code": package_code,
        "review_status": "DRAFT",
        "operational_status": "NOT_SCHEDULED",
        "provisional_fee_cents": 0,
        "final_fee_cents": 0,
        "deposit_cents": 0,
        "deposit_paid": False,
        "pinned_streamer_tier": None,
        "gmv_cents": 0,
        "gross_commission_cents": 0,
        "net_payout_cents": 0,
    }
    app = db.create_entity("applications", payload)
    audit.log(
        subject_kind="SCHEDULE_APPLICATION",
        subject_id=app["id"],
        action="CREATE",
        actor_role=role,
        actor_id=user_id,
        from_state=None,
        to_state="DRAFT",
        payload_snapshot={"studio_id": app["studio_id"]},
    )
    return success(app, http_status=201)


# ---------------------------------------------------------------------------
# Read / list
# ---------------------------------------------------------------------------

@bp.get("/<app_id>")
def read_application(app_id):
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "OperationsReviewer",
                        "ComplianceReviewer", "Streamer"])
    app = _get_application_or_404(app_id)
    _check_streamer_ownership(role, user_id, app)
    return success(db.get_entity("applications", app_id))


@bp.get("")
def list_applications():
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "OperationsReviewer",
                        "ComplianceReviewer", "Streamer"])
    limit, offset = parse_pagination()
    streamer_id = request.args.get("streamer_id")
    studio_id = request.args.get("studio_id")
    review_status = request.args.get("review_status")
    operational_status = request.args.get("operational_status")

    def predicate(a):
        if streamer_id and a.get("streamer_id") != streamer_id:
            return False
        if studio_id and a.get("studio_id") != studio_id:
            return False
        if review_status and a.get("review_status") != review_status:
            return False
        if operational_status and a.get("operational_status") != operational_status:
            return False
        if role == "Streamer" and a.get("streamer_id") != user_id:
            return False
        return True

    items = db.list_entities("applications", predicate=predicate)
    window, pagination = paginate(items, limit, offset)
    return success(window, pagination=pagination, response_type="array")


# ---------------------------------------------------------------------------
# Product association — POST /applications/{id}/products
# ---------------------------------------------------------------------------

@bp.post("/<app_id>/products")
def associate_product(app_id):
    user_id, role = require_auth()
    require_role(role, ["Streamer"])
    app = _get_application_or_404(app_id)
    _check_streamer_ownership(role, user_id, app)

    body = request.get_json(silent=True) or {}
    for key in ("product_id", "reserved_quantity"):
        if key not in body:
            raise_err(ERR_VALIDATION_FAILED, f"Missing field: {key}")
    product = db.raw_get("products", body["product_id"])
    if product is None:
        raise_err(ERR_NOT_FOUND, "Product not found")
    streamer = db.raw_get("streamers", app["streamer_id"])
    if streamer is None:
        raise_err(ERR_NOT_FOUND, "Streamer not found")
    if streamer.get("status") != "ACTIVE":
        raise_err(ERR_STREAMER_NOT_ACTIVE, "Streamer is not ACTIVE")

    qty = body["reserved_quantity"]
    if not isinstance(qty, int) or qty < 1:
        raise_err(ERR_VALIDATION_FAILED, "reserved_quantity must be >=1")

    review = app.get("review_status")
    op = app.get("operational_status")

    # Determine association_phase
    pre_phases = {"DRAFT", "OPS_PENDING", "COMPLIANCE_PENDING"}
    if review in pre_phases:
        phase = "PRE_APPROVAL"
    elif op == "LIVE":
        phase = "DURING_BROADCAST"
    else:
        raise_err(ERR_INVALID_STATE,
                  "Cannot associate product in this application state")

    # During-broadcast extra gate: cap on associations and required category
    if phase == "DURING_BROADCAST":
        existing_count = sum(
            1 for a in db.raw_all("product_associations")
            if a.get("application_id") == app_id
        )
        if existing_count >= MAX_ASSOCIATIONS:
            raise_err(ERR_LIVE_ASSOCIATION_DENIED,
                      "Application already has 20 product associations")
        if product.get("category") not in (app.get("declared_product_categories") or []):
            raise_err(ERR_LIVE_ASSOCIATION_DENIED,
                      "Live association: product category not declared")

    # Pre-decrement stock (PRD §3.3 first paragraph)
    def m_pre(p, qty=qty):
        p["available_stock"] = p.get("available_stock", 0) - qty
        p["reserved_stock"] = p.get("reserved_stock", 0) + qty
    # Check stock availability before mutating — this preserves the
    # ERR_STOCK_INSUFFICIENT semantics rather than allowing negative stock.
    if qty > product.get("available_stock", 0):
        # The eligibility ladder still runs in strict order — we still need
        # to surface the EARLIER-failing rule first if applicable.
        err, reason = eligibility_error(
            product=product, streamer=streamer, application=app,
            reserved_quantity=qty,
        )
        raise_err(err, reason)
    db.update_entity("products", product["id"], m_pre)
    product = db.raw_get("products", product["id"])

    err, reject_reason = eligibility_error(
        product=product, streamer=streamer, application=app,
        reserved_quantity=qty,
    )
    if err is not None:
        # Re-release the stock we pre-decremented and persist a REJECTED row.
        def m_undo(p, qty=qty):
            p["available_stock"] = p.get("available_stock", 0) + qty
            p["reserved_stock"] = max(0, p.get("reserved_stock", 0) - qty)
        db.update_entity("products", product["id"], m_undo)
        # Per PRD §3.3, raise the corresponding error code immediately.
        raise_err(err, reject_reason)

    assoc_payload = {
        "application_id": app_id,
        "product_id": product["id"],
        "reserved_quantity": qty,
        "association_phase": phase,
        "status": "APPROVED",
        "reject_reason": None,
    }
    assoc = db.create_entity("product_associations", assoc_payload)
    return success(assoc, http_status=201)


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

@bp.post("/<app_id>/submit")
def submit(app_id):
    user_id, role = require_auth()
    require_role(role, ["Streamer"])
    app = _get_application_or_404(app_id)
    _check_streamer_ownership(role, user_id, app)
    streamer = db.raw_get("streamers", app["streamer_id"])

    if streamer.get("status") != "ACTIVE":
        raise_err(ERR_STREAMER_NOT_ACTIVE, "Streamer is not ACTIVE")

    if app.get("review_status") != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Application is not in DRAFT state")

    # Qualification check
    health_expiry = clock.parse_iso(streamer["health_cert_expires_at"])
    ends_at = clock.parse_iso(app["ends_at"])
    if not streamer.get("real_name_verified") or health_expiry <= ends_at:
        raise_err(ERR_QUALIFICATION_MISSING,
                  "real_name_verified must be true and health certificate must"
                  " expire strictly after the application's ends_at")

    studio = db.raw_get("studios", app["studio_id"])
    if studio is None:
        raise_err(ERR_NOT_FOUND, "Studio not found")
    if studio.get("status") != "OPEN":
        raise_err(ERR_INVALID_STATE, "Studio is not OPEN")

    starts_at = clock.parse_iso(app["starts_at"])
    if not interval_fully_available(studio["id"], starts_at, ends_at):
        raise_err(ERR_OUT_OF_AVAILABLE_WINDOW,
                  "Interval not covered by AVAILABLE windows or overlaps MAINTENANCE")

    if studio_interval_conflict(studio["id"], starts_at, ends_at,
                                exclude_application_id=app_id):
        raise_err(ERR_STUDIO_INTERVAL_CONFLICT,
                  "Interval conflicts with an existing approved/scheduled/live application")

    fee_breakdown = _slot_fee_for(app, streamer["tier"])

    def mutate(a):
        a["review_status"] = "OPS_PENDING"
        a["provisional_fee_cents"] = fee_breakdown["total_cents"]
    updated = db.update_entity("applications", app_id, mutate)

    audit.log(
        subject_kind="SCHEDULE_APPLICATION",
        subject_id=app_id,
        action="SUBMIT",
        actor_role=role,
        actor_id=user_id,
        from_state="DRAFT",
        to_state="OPS_PENDING",
        payload_snapshot={"provisional_fee_cents": fee_breakdown["total_cents"]},
    )
    return success(updated)


# ---------------------------------------------------------------------------
# Ops approve / reject
# ---------------------------------------------------------------------------

@bp.post("/<app_id>/ops-approve")
def ops_decision(app_id):
    user_id, role = require_auth()
    require_role(role, ["OperationsReviewer"])
    app = _get_application_or_404(app_id)
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise_err(ERR_VALIDATION_FAILED, "decision must be APPROVE or REJECT")

    if app.get("review_status") != "OPS_PENDING":
        raise_err(ERR_INVALID_STATE, "Application is not OPS_PENDING")

    # OCC check (optional version)
    occ_check(app, body)

    streamer = db.raw_get("streamers", app["streamer_id"])

    if decision == "APPROVE":
        # Re-run eligibility ladder against current product state
        assocs = [a for a in db.raw_all("product_associations")
                  if a.get("application_id") == app_id]
        # Only ever consider APPROVED rows — REJECTED and RELEASED are excluded.
        active_assocs = [a for a in assocs if a.get("status") == "APPROVED"]
        if not active_assocs:
            # No APPROVED associations means cannot promote
            raise_err(ERR_INVALID_STATE,
                      "Application has no APPROVED product associations")
        for assoc in active_assocs:
            product = db.raw_get("products", assoc["product_id"])
            if product is None:
                raise_err(ERR_NOT_FOUND, "Product not found")
            err, _ = eligibility_error(
                product=product, streamer=streamer, application=app,
                reserved_quantity=assoc["reserved_quantity"],
            )
            if err is not None:
                raise_err(err, "Product re-check failed during ops-approve")

        snapshot = {
            "snapshot_streamer_tier": streamer["tier"],
            "snapshot_provisional_fee_cents": app["provisional_fee_cents"],
        }
        record_payload = {
            "application_id": app_id,
            "level": "OPS",
            "decision": "APPROVE",
            "reviewer_role": role,
            "reviewer_id": user_id,
            "reason": body.get("reason"),
            **snapshot,
        }
        db.create_entity("approvals", record_payload)

        def mutate(a):
            a["review_status"] = "COMPLIANCE_PENDING"
        updated = db.update_entity("applications", app_id, mutate)
        audit.log(
            subject_kind="SCHEDULE_APPLICATION",
            subject_id=app_id,
            action="OPS_APPROVE",
            actor_role=role,
            actor_id=user_id,
            from_state="OPS_PENDING",
            to_state="COMPLIANCE_PENDING",
        )
        return success(updated)

    # REJECT branch
    reason = body.get("reason")
    if not reason or not str(reason).strip():
        raise_err(ERR_REASON_REQUIRED, "reason is required for REJECT")
    snapshot = {
        "snapshot_streamer_tier": streamer["tier"] if streamer else None,
        "snapshot_provisional_fee_cents": app["provisional_fee_cents"],
    }
    db.create_entity("approvals", {
        "application_id": app_id,
        "level": "OPS",
        "decision": "REJECT",
        "reviewer_role": role,
        "reviewer_id": user_id,
        "reason": reason,
        **snapshot,
    })

    def mutate_rej(a):
        a["review_status"] = "REJECTED"
        a["provisional_fee_cents"] = 0
    updated = db.update_entity("applications", app_id, mutate_rej)
    release_all_for_application(app_id)
    audit.log(
        subject_kind="SCHEDULE_APPLICATION",
        subject_id=app_id,
        action="REJECT",
        actor_role=role,
        actor_id=user_id,
        from_state="OPS_PENDING",
        to_state="REJECTED",
        payload_snapshot={"reason": reason},
    )
    return success(updated)


# ---------------------------------------------------------------------------
# Compliance approve / reject
# ---------------------------------------------------------------------------

@bp.post("/<app_id>/compliance-approve")
def compliance_decision(app_id):
    user_id, role = require_auth()
    require_role(role, ["ComplianceReviewer"])
    app = _get_application_or_404(app_id)
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise_err(ERR_VALIDATION_FAILED, "decision must be APPROVE or REJECT")

    if app.get("review_status") != "COMPLIANCE_PENDING":
        raise_err(ERR_INVALID_STATE, "Application is not COMPLIANCE_PENDING")

    occ_check(app, body)

    streamer = db.raw_get("streamers", app["streamer_id"])
    if streamer is None:
        raise_err(ERR_NOT_FOUND, "Streamer not found")

    if decision == "APPROVE":
        # Re-check studio interval conflict
        starts_at = clock.parse_iso(app["starts_at"])
        ends_at = clock.parse_iso(app["ends_at"])
        if studio_interval_conflict(app["studio_id"], starts_at, ends_at,
                                    exclude_application_id=app_id):
            raise_err(ERR_STUDIO_INTERVAL_CONFLICT,
                      "Interval conflicts with another approved/scheduled/live"
                      " application")
        if streamer.get("status") != "ACTIVE":
            raise_err(ERR_STREAMER_NOT_ACTIVE, "Streamer is not ACTIVE")
        if streamer.get("violation_score", 0) >= 100:
            raise_err(ERR_STREAMER_BLOCKED,
                      "Streamer.violation_score >= 100")

        pinned_tier = streamer["tier"]
        fee = _slot_fee_for(app, pinned_tier)
        total = fee["total_cents"]
        deposit = deposit_for_total(total)

        def mutate(a):
            a["review_status"] = "APPROVED"
            a["operational_status"] = "SCHEDULED"
            a["pinned_streamer_tier"] = pinned_tier
            a["final_fee_cents"] = total
            a["deposit_cents"] = deposit
        updated = db.update_entity("applications", app_id, mutate)

        invoice_payload = {
            "application_id": app_id,
            "subtotal_cents": fee["subtotal_cents"],
            "peak_surcharge_cents": fee["peak_surcharge_cents"],
            "package_discount_cents": fee["package_discount_cents"],
            "total_cents": total,
            "deposit_due_cents": deposit,
            "status": "ISSUED",
            "refund_cents": 0,
        }
        invoice = db.create_entity("invoices", invoice_payload)

        db.create_entity("approvals", {
            "application_id": app_id,
            "level": "COMPLIANCE",
            "decision": "APPROVE",
            "reviewer_role": role,
            "reviewer_id": user_id,
            "reason": body.get("reason"),
            "snapshot_streamer_tier": pinned_tier,
            "snapshot_provisional_fee_cents": app.get("provisional_fee_cents", 0),
        })
        audit.log(
            subject_kind="SCHEDULE_APPLICATION",
            subject_id=app_id,
            action="COMPLIANCE_APPROVE",
            actor_role=role,
            actor_id=user_id,
            from_state="COMPLIANCE_PENDING",
            to_state="APPROVED",
            payload_snapshot={"invoice_id": invoice["id"],
                              "final_fee_cents": total},
        )
        return success(updated)

    # REJECT branch
    reason = body.get("reason")
    if not reason or not str(reason).strip():
        raise_err(ERR_REASON_REQUIRED, "reason is required for REJECT")
    db.create_entity("approvals", {
        "application_id": app_id,
        "level": "COMPLIANCE",
        "decision": "REJECT",
        "reviewer_role": role,
        "reviewer_id": user_id,
        "reason": reason,
        "snapshot_streamer_tier": streamer["tier"],
        "snapshot_provisional_fee_cents": app.get("provisional_fee_cents", 0),
    })

    def mutate_rej(a):
        a["review_status"] = "REJECTED"
    updated = db.update_entity("applications", app_id, mutate_rej)
    release_all_for_application(app_id)
    audit.log(
        subject_kind="SCHEDULE_APPLICATION",
        subject_id=app_id,
        action="REJECT",
        actor_role=role,
        actor_id=user_id,
        from_state="COMPLIANCE_PENDING",
        to_state="REJECTED",
        payload_snapshot={"reason": reason},
    )
    return success(updated)


# ---------------------------------------------------------------------------
# Withdraw
# ---------------------------------------------------------------------------

@bp.post("/<app_id>/withdraw")
def withdraw(app_id):
    user_id, role = require_auth()
    require_role(role, ["Streamer"])
    app = _get_application_or_404(app_id)
    _check_streamer_ownership(role, user_id, app)

    if app.get("review_status") not in ("DRAFT", "OPS_PENDING"):
        raise_err(ERR_INVALID_STATE,
                  "Withdraw allowed only from DRAFT or OPS_PENDING")

    from_state = app["review_status"]

    def mutate(a):
        a["review_status"] = "WITHDRAWN"
    updated = db.update_entity("applications", app_id, mutate)
    release_all_for_application(app_id)
    audit.log(
        subject_kind="SCHEDULE_APPLICATION",
        subject_id=app_id,
        action="WITHDRAW",
        actor_role=role,
        actor_id=user_id,
        from_state=from_state,
        to_state="WITHDRAWN",
    )
    return success(updated)


# ---------------------------------------------------------------------------
# Start / end live
# ---------------------------------------------------------------------------

@bp.post("/<app_id>/start-live")
def start_live(app_id):
    user_id, role = require_auth()
    require_role(role, ["Streamer"])
    app = _get_application_or_404(app_id)
    _check_streamer_ownership(role, user_id, app)
    streamer = db.raw_get("streamers", app["streamer_id"])

    if streamer.get("status") != "ACTIVE":
        raise_err(ERR_STREAMER_NOT_ACTIVE, "Streamer is not ACTIVE")

    if app.get("operational_status") != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Application is not SCHEDULED")

    if not app.get("deposit_paid"):
        raise_err(ERR_DEPOSIT_UNPAID, "Deposit not paid")

    now = clock.now()
    starts_at = clock.parse_iso(app["starts_at"])
    ends_at = clock.parse_iso(app["ends_at"])
    if now < starts_at or now >= ends_at:
        raise_err(ERR_INVALID_STATE,
                  "Now must be within [starts_at, ends_at)")

    def mutate(a):
        a["operational_status"] = "LIVE"
    updated = db.update_entity("applications", app_id, mutate)
    audit.log(
        subject_kind="SCHEDULE_APPLICATION",
        subject_id=app_id,
        action="GO_LIVE",
        actor_role=role,
        actor_id=user_id,
        from_state="SCHEDULED",
        to_state="LIVE",
    )
    return success(updated)


@bp.post("/<app_id>/end-live")
def end_live(app_id):
    user_id, role = require_auth()
    require_role(role, ["Streamer"])
    app = _get_application_or_404(app_id)
    _check_streamer_ownership(role, user_id, app)

    if app.get("operational_status") != "LIVE":
        raise_err(ERR_INVALID_STATE, "Application is not LIVE")

    starts_at = clock.parse_iso(app["starts_at"])
    if clock.now() < starts_at:
        raise_err(ERR_INVALID_STATE, "Cannot end before starts_at")

    streamer = db.raw_get("streamers", app["streamer_id"])

    # Aggregate any pre-existing GMV events on the application
    gross = 0
    for ev in db.raw_all("external_events"):
        if (ev.get("source") == "ECOMMERCE"
                and ev.get("kind") == "BROADCAST_GMV"
                and ev.get("application_id") == app_id):
            gross += int(ev.get("amount_cents", 0) or 0)

    # Initialize the settlement
    return_window_ends = clock.parse_iso(app["ends_at"]) + timedelta(days=7)
    provisional = calc_commission_provisional(
        pinned_tier=app["pinned_streamer_tier"],
        gross_sales_cents=gross,
    )
    settlement_payload = {
        "application_id": app_id,
        "gross_sales_cents": gross,
        "returned_sales_cents": 0,
        "commission_rate_bp": provisional["commission_rate_bp"],
        "tier_bonus_cents": provisional["tier_bonus_cents"],
        "tax_withholding_cents": 0,
        "return_window_ends_at": clock.format_iso(return_window_ends),
        "status": "WINDOW_OPEN",
        "provisional_payout_cents": provisional["provisional_payout_cents"],
        "final_payout_cents": 0,
    }
    db.create_entity("settlements", settlement_payload)

    # Application update — operational_status, gmv, gross_commission
    def mutate(a):
        a["operational_status"] = "COMPLETED"
        a["gmv_cents"] = gross
        a["gross_commission_cents"] = provisional["gross_commission_cents"]
    updated = db.update_entity("applications", app_id, mutate)

    # Invoice auto-transitions from DEPOSIT_PAID -> SETTLED
    invoice = _find_invoice_by_app(app_id)
    if invoice is not None and invoice.get("status") == "DEPOSIT_PAID":
        db.update_entity("invoices", invoice["id"],
                         lambda inv: inv.__setitem__("status", "SETTLED"))

    # Streamer cascade — completed_broadcast_count + tier recompute
    def m_streamer(s):
        s["completed_broadcast_count"] = s.get("completed_broadcast_count", 0) + 1
    db.update_entity("streamers", streamer["id"], m_streamer)
    apply_cascade(streamer["id"])

    audit.log(
        subject_kind="SCHEDULE_APPLICATION",
        subject_id=app_id,
        action="COMPLETE",
        actor_role=role,
        actor_id=user_id,
        from_state="LIVE",
        to_state="COMPLETED",
    )
    return success(updated)


# ---------------------------------------------------------------------------
# Cancel / force-cancel
# ---------------------------------------------------------------------------

def _find_invoice_by_app(app_id: str):
    for inv in db.raw_all("invoices"):
        if inv.get("application_id") == app_id:
            return inv
    return None


def _apply_cancel_refund_cascade(app_id: str):
    """Run the SCHEDULED→CANCELLED refund cascade on the invoice."""
    app = db.raw_get("applications", app_id)
    if app is None:
        return
    invoice = _find_invoice_by_app(app_id)
    if invoice is None:
        return

    starts_at = clock.parse_iso(app["starts_at"])
    deposit_due = int(invoice.get("deposit_due_cents", 0))

    if invoice.get("status") == "ISSUED":
        # Deposit not yet paid — full refund (of 0 cents).
        def m(inv):
            inv["status"] = "REFUNDED_FULL"
            inv["refund_cents"] = 0
        db.update_entity("invoices", invoice["id"], m)
        return

    refund_cents = calc_refund(starts_at=starts_at,
                               deposit_due_cents=deposit_due)
    if refund_cents >= deposit_due:
        new_status = "REFUNDED_FULL"
        refund_cents = deposit_due
    elif refund_cents > 0:
        new_status = "REFUNDED_PARTIAL"
    else:
        # Zero refund but deposit was paid — mark partial with refund=0.
        new_status = "REFUNDED_PARTIAL"

    def m(inv):
        inv["refund_cents"] = refund_cents
        inv["status"] = new_status
    db.update_entity("invoices", invoice["id"], m)


@bp.post("/<app_id>/cancel")
def cancel(app_id):
    user_id, role = require_auth()
    require_role(role, ["Streamer", "OperationsReviewer"])
    app = _get_application_or_404(app_id)
    if role == "Streamer":
        _check_streamer_ownership(role, user_id, app)
    body = request.get_json(silent=True) or {}
    reason = body.get("reason")

    if app.get("operational_status") != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Application is not SCHEDULED")

    if not reason or not str(reason).strip():
        raise_err(ERR_REASON_REQUIRED, "reason is required for cancel")

    starts_at = clock.parse_iso(app["starts_at"])
    if clock.now() >= starts_at:
        raise_err(ERR_TOO_LATE_TO_CANCEL,
                  "Cannot cancel at or after starts_at")

    def mutate(a):
        a["operational_status"] = "CANCELLED"
    updated = db.update_entity("applications", app_id, mutate)
    _apply_cancel_refund_cascade(app_id)
    release_all_for_application(app_id)
    audit.log(
        subject_kind="SCHEDULE_APPLICATION",
        subject_id=app_id,
        action="CANCEL",
        actor_role=role,
        actor_id=user_id,
        from_state="SCHEDULED",
        to_state="CANCELLED",
        payload_snapshot={"reason": reason},
    )
    return success(updated)


@bp.post("/<app_id>/force-cancel")
def force_cancel(app_id):
    user_id, role = require_auth()
    require_role(role, ["OperationsReviewer"])
    app = _get_application_or_404(app_id)
    body = request.get_json(silent=True) or {}
    reason = body.get("reason")

    if app.get("operational_status") != "LIVE":
        raise_err(ERR_INVALID_STATE, "Application is not LIVE")

    if not reason or not str(reason).strip():
        raise_err(ERR_REASON_REQUIRED, "reason is required for force-cancel")

    def mutate(a):
        a["operational_status"] = "CANCELLED"
    updated = db.update_entity("applications", app_id, mutate)

    invoice = _find_invoice_by_app(app_id)
    if invoice is not None:
        def m(inv):
            inv["refund_cents"] = 0
        db.update_entity("invoices", invoice["id"], m)

    release_all_for_application(app_id)
    audit.log(
        subject_kind="SCHEDULE_APPLICATION",
        subject_id=app_id,
        action="FORCE_CANCEL",
        actor_role=role,
        actor_id=user_id,
        from_state="LIVE",
        to_state="CANCELLED",
        payload_snapshot={"reason": reason},
    )
    return success(updated)


# ---------------------------------------------------------------------------
# Nested reads
# ---------------------------------------------------------------------------

@bp.get("/<app_id>/approvals")
def list_approvals(app_id):
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "OperationsReviewer",
                        "ComplianceReviewer", "Streamer"])
    app = _get_application_or_404(app_id)
    _check_streamer_ownership(role, user_id, app)
    limit, offset = parse_pagination()
    items = db.list_entities(
        "approvals",
        predicate=lambda a: a.get("application_id") == app_id,
    )
    window, pagination = paginate(items, limit, offset)
    return success(window, pagination=pagination, response_type="array")


@bp.get("/<app_id>/invoice")
def read_invoice(app_id):
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "OperationsReviewer",
                        "ComplianceReviewer", "Streamer"])
    app = _get_application_or_404(app_id)
    _check_streamer_ownership(role, user_id, app)
    invoice = _find_invoice_by_app(app_id)
    if invoice is None:
        raise_err(ERR_NOT_FOUND, "Invoice not found")
    return success(db.get_entity("invoices", invoice["id"]))


@bp.get("/<app_id>/settlement")
def read_settlement(app_id):
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "OperationsReviewer",
                        "ComplianceReviewer", "Streamer"])
    app = _get_application_or_404(app_id)
    _check_streamer_ownership(role, user_id, app)
    for s in db.raw_all("settlements"):
        if s.get("application_id") == app_id:
            return success(db.get_entity("settlements", s["id"]))
    raise_err(ERR_NOT_FOUND, "Settlement not found")

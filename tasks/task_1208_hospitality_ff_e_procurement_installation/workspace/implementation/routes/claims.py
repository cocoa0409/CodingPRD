"""DamageClaim endpoints (PRD 3.6)."""
from flask import Blueprint

import db
import services as svc
from errors import ApiError
from middleware import auth, require_role, body, req_int, req_enum
from response import ok

bp = Blueprint("claims", __name__)
S = db.STORE

CLAIM_TYPES = ("DAMAGE", "SHORTAGE")
CLAIM_STATUSES = ("OPEN", "SUBMITTED", "DISPUTED", "RESOLVED_CREDIT",
                  "RESOLVED_REPLACEMENT", "DENIED", "VOID")

# Per-target role rules (PRD 2.1): PurchasingAgent drives submission and all
# three resolutions; Vendor may only dispute.
CLAIM_TARGETS = {
    "PurchasingAgent": ("SUBMITTED", "RESOLVED_CREDIT", "RESOLVED_REPLACEMENT", "DENIED"),
    "Vendor": ("DISPUTED",),
}


def _residual(line, claim_type):
    open_qty = sum(c["quantity"] for c in S["damage_claims"].values()
                   if c["po_line_id"] == line["id"]
                   and c["claim_type"] == claim_type
                   and c["status"] in svc.NON_TERMINAL_CLAIM_STATES)
    base = line["qty_damaged_unresolved"] if claim_type == "DAMAGE" else line["qty_short"]
    return base - open_qty


@bp.route("/api/damage-claims", methods=["POST"])
def create_claim():
    auth_user, role = auth()
    require_role(role, ("PurchasingAgent",))
    b = body()
    po_line_id = b.get("po_line_id")
    if not isinstance(po_line_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Missing or invalid field: po_line_id")
    claim_type = req_enum(b, "claim_type", CLAIM_TYPES)
    quantity = req_int(b, "quantity", 1)
    claimed_credit = req_int(b, "claimed_credit_cents", 0)
    line = svc.get_line(po_line_id)
    if quantity > _residual(line, claim_type):
        raise ApiError("ERR_CLAIM_QTY_EXCEEDS_RESIDUAL",
                       "Claim quantity exceeds the type-specific residual")
    claim = db.create("damage_claims", {
        "po_line_id": po_line_id,
        "claim_type": claim_type,
        "quantity": quantity,
        "claimed_credit_cents": claimed_credit,
        "approved_credit_cents": None,
        "status": "OPEN",
    })
    return ok(db.pub(claim), 201)


@bp.route("/api/damage-claims/<damageClaimId>", methods=["GET"])
def get_claim(damageClaimId):
    from routes.projects import ANY
    auth_user, role = auth()
    require_role(role, ANY)
    return ok(db.pub(svc.get_claim(damageClaimId)))


@bp.route("/api/damage-claims/<damageClaimId>/transitions", methods=["POST"])
def claim_transition(damageClaimId):
    auth_user, role = auth()
    require_role(role, ("PurchasingAgent", "Vendor"))
    b = body()
    to_status = b.get("to_status")
    # per-target role authorization (stage 2) before path existence
    if isinstance(to_status, str) and to_status in CLAIM_STATUSES:
        if to_status not in CLAIM_TARGETS.get(role, ()):
            raise ApiError("ERR_UNAUTHORIZED_ROLE",
                           f"Role {role} may not move a claim to {to_status}")
    claim = svc.get_claim(damageClaimId)
    to_status = req_enum(b, "to_status", CLAIM_STATUSES)
    cur = claim["status"]

    if to_status == "SUBMITTED":
        if cur not in ("OPEN", "DISPUTED"):
            raise ApiError("ERR_INVALID_CLAIM_TRANSITION",
                           "SUBMITTED requires the claim OPEN or DISPUTED")
        claim["status"] = "SUBMITTED"
    elif to_status == "DISPUTED":
        if cur != "SUBMITTED":
            raise ApiError("ERR_INVALID_CLAIM_TRANSITION",
                           "DISPUTED requires the claim SUBMITTED")
        claim["status"] = "DISPUTED"
    elif to_status == "RESOLVED_CREDIT":
        if cur != "SUBMITTED":
            raise ApiError("ERR_INVALID_CLAIM_TRANSITION",
                           "RESOLVED_CREDIT requires the claim SUBMITTED")
        approved = b.get("approved_credit_cents")
        if (not isinstance(approved, int) or isinstance(approved, bool)
                or approved < 0):
            raise ApiError("ERR_INVALID_REQUEST",
                           "approved_credit_cents must be provided and >= 0")
        _resolve_credit(claim, approved)
    elif to_status == "RESOLVED_REPLACEMENT":
        if cur != "SUBMITTED":
            raise ApiError("ERR_INVALID_CLAIM_TRANSITION",
                           "RESOLVED_REPLACEMENT requires the claim SUBMITTED")
        if claim["claim_type"] == "DAMAGE":
            line = svc.get_line(claim["po_line_id"])
            line["qty_damaged_unresolved"] -= claim["quantity"]
            line["qty_damaged_credited"] += claim["quantity"]
            db.touch(line)
        claim["status"] = "RESOLVED_REPLACEMENT"
    elif to_status == "DENIED":
        if cur != "SUBMITTED":
            raise ApiError("ERR_INVALID_CLAIM_TRANSITION",
                           "DENIED requires the claim SUBMITTED")
        claim["status"] = "DENIED"
    else:  # VOID is system-driven only
        raise ApiError("ERR_INVALID_CLAIM_TRANSITION",
                       f"{cur} -> {to_status} is not a legal claim transition")
    db.touch(claim)
    return ok(db.pub(claim))


def _resolve_credit(claim, approved):
    """Three-link credit cascade (PRD 3.6)."""
    line = svc.get_line(claim["po_line_id"])
    claim["approved_credit_cents"] = approved
    line["damage_credit_cents"] += approved
    if claim["claim_type"] == "DAMAGE":
        line["qty_damaged_unresolved"] -= claim["quantity"]
        line["qty_damaged_credited"] += claim["quantity"]
    db.touch(line)
    svc.recompute_landed(line)
    claim["status"] = "RESOLVED_CREDIT"
    svc.recompute_project_financials(svc.po_of_line(line)["project_id"])

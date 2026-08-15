"""Routes: logical clock, membership tiers, members, dues invoices, dues payments."""
from flask import Blueprint

import domain as D
from helpers import (ApiError, actor, as_enum, as_int, as_bool, as_str, body,
                     field, fk, fmt_dt, list_response, parse_dt, sorted_items,
                     success)
from store import DB
import views

core_bp = Blueprint("core", __name__)

ALL_ROLES = ("ClubOfficer", "Member", "EventCoordinator", "EquipmentChair")


def _get_or_404(table, rid):
    ent = table.get(rid)
    if ent is None:
        raise ApiError(404, "ERR_NOT_FOUND", "Resource not found: %s" % rid)
    return ent


# ----- logical clock -----

@core_bp.post("/club/_clock/set_current_utc")
def set_clock():
    actor(["ClubOfficer"])
    data = body()
    to = parse_dt(field(data, "to_iso8601"), "to_iso8601")
    DB.clock = to
    D.fire_time_transitions(DB)
    return success({"current_utc": fmt_dt(DB.clock)}, 200)


# ----- membership tiers -----

@core_bp.post("/club/membership-tiers")
def create_tier():
    actor(["ClubOfficer"])
    data = body()
    code = as_enum(field(data, "code"), "code", D.TIER_CODES)
    annual = as_int(field(data, "annual_dues_cents"), "annual_dues_cents")
    if annual < 0:
        raise ApiError(400, "ERR_INVALID_REQUEST", "annual_dues_cents must be >= 0")
    level = as_int(field(data, "observatory_access_level"), "observatory_access_level")
    if level < 1 or level > 3:
        raise ApiError(400, "ERR_INVALID_REQUEST",
                       "observatory_access_level must be between 1 and 3")
    loan_priv = as_bool(field(data, "loan_privilege"), "loan_privilege")
    max_loans = as_int(field(data, "max_concurrent_loans"), "max_concurrent_loans")
    if max_loans < 0:
        raise ApiError(400, "ERR_INVALID_REQUEST", "max_concurrent_loans must be >= 0")
    t = D.mint(DB)
    t.update({
        "code": code,
        "annual_dues_cents": annual,
        "observatory_access_level": level,
        "loan_privilege": loan_priv,
        "max_concurrent_loans": max_loans,
    })
    DB.tiers[t["id"]] = t
    return success(views.tier_view(DB, t), 201)


@core_bp.get("/club/membership-tiers/<tier_id>")
def get_tier(tier_id):
    actor(ALL_ROLES)
    return success(views.tier_view(DB, _get_or_404(DB.tiers, tier_id)), 200)


@core_bp.get("/club/membership-tiers")
def list_tiers():
    actor(ALL_ROLES)
    return list_response(sorted_items(DB.tiers), lambda t: views.tier_view(DB, t))


# ----- members -----

@core_bp.post("/club/members")
def create_member():
    actor(["ClubOfficer"])
    data = body()
    tier = fk(data, "tier_id", DB.tiers)  # body-id existence before shape
    full_name = as_str(field(data, "full_name"), "full_name")
    email = as_str(field(data, "email"), "email")
    as_str(field(data, "tier_id"), "tier_id")
    if any(m["email"] == email for m in DB.members.values()):
        raise ApiError(400, "ERR_INVALID_REQUEST", "email must be unique across members")
    m = D.mint(DB)
    m.update({
        "full_name": full_name,
        "email": email,
        "tier_id": tier["id"],
        "status": "ACTIVE",
        "joined_at": DB.clock,
        "dues_paid_through": DB.clock,  # joined_at + 0 days: first invoice due immediately
        "effective_access_level": tier["observatory_access_level"],
        "no_show_strikes": 0,
        "_credit_balance_cents": 0,
    })
    DB.members[m["id"]] = m
    return success(views.member_view(DB, m), 201)


@core_bp.get("/club/members/<member_id>")
def get_member(member_id):
    actor(ALL_ROLES)
    return success(views.member_view(DB, _get_or_404(DB.members, member_id)), 200)


@core_bp.get("/club/members")
def list_members():
    actor(["ClubOfficer", "EventCoordinator", "EquipmentChair"])
    from flask import request
    items = sorted_items(DB.members)
    status = request.args.get("status")
    tier_id = request.args.get("tier_id")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    if tier_id is not None:
        items = [m for m in items if m["tier_id"] == tier_id]
    return list_response(items, lambda m: views.member_view(DB, m))


@core_bp.post("/club/members/<member_id>/reinstate")
def reinstate_member(member_id):
    actor(["ClubOfficer"])
    m = _get_or_404(DB.members, member_id)
    if m["status"] != "SUSPENDED":
        raise ApiError(409, "ERR_INVALID_STATE", "Member is not SUSPENDED")
    if not (DB.clock < m["dues_paid_through"]):
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Dues are not current; dues_paid_through has not passed the clock")
    m["status"] = "ACTIVE"
    m["effective_access_level"] = DB.tiers[m["tier_id"]]["observatory_access_level"]
    D.stamp(DB, m)
    return success(views.member_view(DB, m), 200)


@core_bp.post("/club/members/<member_id>/resign")
def resign_member(member_id):
    uid, role = actor(["Member", "ClubOfficer"])
    m = _get_or_404(DB.members, member_id)
    if role == "Member" and uid != m["id"]:
        raise ApiError(403, "ERR_FORBIDDEN", "A Member may only resign itself")
    if m["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Only ACTIVE or SUSPENDED members may resign")
    if any(l["member_id"] == m["id"] and l["status"] in ("CHECKED_OUT", "OVERDUE")
           for l in DB.loans.values()):
        raise ApiError(422, "ERR_LOANS_OUTSTANDING",
                       "Member holds CHECKED_OUT or OVERDUE loans")
    was_active = m["status"] == "ACTIVE"
    m["status"] = "RESIGNED"
    m["effective_access_level"] = 0
    D.stamp(DB, m)
    if was_active:
        # Resigning from SUSPENDED carries no cascades; suspension already applied them.
        D.cancel_reserved_loans_of(DB, m["id"])
        D.withdraw_assignments_of(DB, m["id"])
    return success(views.member_view(DB, m), 200)


# ----- dues invoices -----

@core_bp.post("/club/dues-invoices")
def create_invoice():
    actor(["ClubOfficer"])
    data = body()
    member = fk(data, "member_id", DB.members)
    as_str(field(data, "member_id"), "member_id")
    period_start = parse_dt(field(data, "period_start"), "period_start")
    period_end = parse_dt(field(data, "period_end"), "period_end")
    if not (period_start < period_end):
        raise ApiError(422, "ERR_INVALID_WINDOW",
                       "period_start must be strictly before period_end")
    tier = DB.tiers[member["tier_id"]]
    amount = D.prorate_amount(tier["annual_dues_cents"], period_start, period_end)
    inv = D.mint(DB)
    inv.update({
        "member_id": member["id"],
        "period_start": period_start,
        "period_end": period_end,
        "amount_cents": amount,
        "status": "OPEN",
    })
    DB.invoices[inv["id"]] = inv
    return success(views.invoice_view(DB, inv), 201)


@core_bp.get("/club/dues-invoices/<invoice_id>")
def get_invoice(invoice_id):
    actor(["ClubOfficer", "Member"])
    return success(views.invoice_view(DB, _get_or_404(DB.invoices, invoice_id)), 200)


@core_bp.get("/club/dues-invoices")
def list_invoices():
    actor(["ClubOfficer", "Member"])
    from flask import request
    items = sorted_items(DB.invoices)
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    if member_id is not None:
        items = [i for i in items if i["member_id"] == member_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return list_response(items, lambda i: views.invoice_view(DB, i))


@core_bp.post("/club/dues-invoices/<invoice_id>/void")
def void_invoice(invoice_id):
    actor(["ClubOfficer"])
    inv = _get_or_404(DB.invoices, invoice_id)
    if inv["status"] != "OPEN":
        raise ApiError(409, "ERR_INVALID_STATE", "Only an OPEN invoice may be voided")
    inv["status"] = "VOID"
    D.stamp(DB, inv)
    return success(views.invoice_view(DB, inv), 200)


# ----- dues payments -----

@core_bp.post("/club/dues-payments")
def create_payment():
    uid, role = actor(["Member", "ClubOfficer"])
    data = body()
    inv = fk(data, "invoice_id", DB.invoices)
    payer = fk(data, "member_id", DB.members)
    if role == "Member" and isinstance(data.get("member_id"), str) \
            and data["member_id"] != uid:
        raise ApiError(403, "ERR_FORBIDDEN",
                       "A Member may only post payments for itself")
    invoice_id = as_str(field(data, "invoice_id"), "invoice_id")
    member_id = as_str(field(data, "member_id"), "member_id")
    amount = as_int(field(data, "amount_cents"), "amount_cents")
    if amount < 0:
        raise ApiError(400, "ERR_INVALID_REQUEST", "amount_cents must be >= 0")
    if inv["member_id"] != member_id:
        raise ApiError(400, "ERR_INVALID_REQUEST",
                       "member_id must match the invoice's member")
    if inv["status"] != "OPEN":
        raise ApiError(409, "ERR_INVALID_STATE", "Invoice is not OPEN")
    credit = payer["_credit_balance_cents"]
    if amount + credit < inv["amount_cents"]:
        raise ApiError(422, "ERR_PAYMENT_INSUFFICIENT",
                       "Payment plus available member credit is below the invoice amount")
    credit_used = min(credit, inv["amount_cents"] - amount) \
        if inv["amount_cents"] > amount else 0
    excess = amount + credit_used - inv["amount_cents"]
    payer["_credit_balance_cents"] = credit - credit_used + excess

    inv["status"] = "PAID"
    D.stamp(DB, inv)
    if inv["period_end"] > payer["dues_paid_through"]:
        payer["dues_paid_through"] = inv["period_end"]
    if payer["status"] == "LAPSED" and inv["period_end"] > DB.clock:
        payer["status"] = "ACTIVE"
        payer["effective_access_level"] = \
            DB.tiers[payer["tier_id"]]["observatory_access_level"]
    D.stamp(DB, payer)

    p = {
        "id": D.new_id(),
        "created_at": DB.clock,
        "_seq": DB.next_seq(),
        "invoice_id": invoice_id,
        "member_id": member_id,
        "amount_cents": amount,
        "posted_at": DB.clock,
        "credit_applied_cents": credit_used,
    }
    DB.payments[p["id"]] = p
    return success(views.payment_view(DB, p), 201)


@core_bp.get("/club/dues-payments")
def list_payments():
    actor(["ClubOfficer", "Member"])
    from flask import request
    items = sorted_items(DB.payments)
    member_id = request.args.get("member_id")
    invoice_id = request.args.get("invoice_id")
    if member_id is not None:
        items = [p for p in items if p["member_id"] == member_id]
    if invoice_id is not None:
        items = [p for p in items if p["invoice_id"] == invoice_id]
    return list_response(items, lambda p: views.payment_view(DB, p))


@core_bp.get("/club/dues-payments/<payment_id>")
def get_payment(payment_id):
    actor(["ClubOfficer", "Member"])
    return success(views.payment_view(DB, _get_or_404(DB.payments, payment_id)), 200)

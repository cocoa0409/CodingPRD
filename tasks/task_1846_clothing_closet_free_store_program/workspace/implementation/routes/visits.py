"""Shopping visits: check-in (with voucher redemption), checkout, void (PRD 3.2)."""
from flask import Blueprint, g

import db
import services as svc
from db import stamp_new, store, touch
from errors import ApiError, forbidden, invalid_state, not_found
from middleware import require_roles
from response import ok, ok_list
from routes.clients import get_client_or_404
from util import (
    get_body, opt_enum_filter, page_params, paginate, v_str,
)

bp = Blueprint("visits", __name__)

VISIT_STATUSES = {"CHECKED_IN", "CHECKED_OUT", "VOIDED"}


def get_visit_or_404(visit_id):
    v = store.visits.get(visit_id)
    if v is None:
        raise not_found("Visit not found")
    return v


@bp.post("/closet/clients/<cid>/visits")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def check_in(cid):
    client = get_client_or_404(cid)
    data = get_body()
    voucher = None
    voucher_id = data.get("voucher_id")
    if voucher_id is not None:
        if not isinstance(voucher_id, str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "voucher_id must be a string")
        voucher = store.vouchers.get(voucher_id)
        if voucher is None:
            raise not_found("Voucher not found")

    # Check-in rule order (PRD 3.2): client ACTIVE, cooldown, rolling visit
    # cap, then the four voucher checks.
    if client["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_NOT_ACTIVE", 409, "Client is not ACTIVE")
    if not svc.cooldown_ok(client, voucher):
        raise ApiError(
            "ERR_VISIT_COOLDOWN_ACTIVE", 409,
            "Fewer than 14 days since the client's last checkout",
        )
    visits_30d, _ = svc.visit_window_stats(client["id"])
    if visits_30d >= svc.MAX_VISITS_PER_30D:
        raise ApiError(
            "ERR_VISIT_LIMIT_REACHED", 409,
            "Client has reached 3 checkouts in the trailing 30 days",
        )
    if voucher is not None:
        svc.refresh_voucher(voucher)
        if db.now() >= voucher["expires_at"]:
            raise ApiError("ERR_VOUCHER_EXPIRED", 409, "Voucher has expired")
        if voucher["status"] != "ISSUED":
            raise ApiError(
                "ERR_VOUCHER_NOT_REDEEMABLE", 409,
                "Voucher is not in ISSUED status",
            )
        if voucher["client_id"] != client["id"]:
            raise ApiError(
                "ERR_VOUCHER_CLIENT_MISMATCH", 409,
                "Voucher was issued to a different client",
            )
        partner = store.partners.get(voucher["partner_id"])
        if partner is None or partner["status"] != "ACTIVE":
            raise ApiError(
                "ERR_PARTNER_SUSPENDED", 409,
                "The voucher's issuing partner is suspended",
            )

    # Allowance snapshot; drive pools advance lazily at check-in evaluation.
    svc.refresh_all_drives()
    general_allowance, bonus = svc.compute_allowance(client, voucher)
    visit = stamp_new({
        "client_id": client["id"],
        "voucher_id": voucher["id"] if voucher else None,
        "status": "CHECKED_IN",
        "checked_in_at": db.now(),
        "checked_out_at": None,
        "general_allowance": general_allowance,
        "voucher_bonus_applied": bonus,
    })
    store.visits[visit["id"]] = visit
    if voucher is not None:
        voucher["status"] = "REDEEMED"
        voucher["redeemed_at"] = db.now()
        touch(voucher)
    return ok(svc.serialize_visit(visit), 201)


@bp.get("/closet/clients/<cid>/visits")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer", "Client")
def list_client_visits(cid):
    if g.user_role == "Client" and g.user_id != cid:
        raise forbidden("Clients may only read their own visits")
    get_client_or_404(cid)
    status = opt_enum_filter("status", VISIT_STATUSES)
    limit, offset = page_params()
    rows = [v for v in store.visits.values() if v["client_id"] == cid]
    if status is not None:
        rows = [v for v in rows if v["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([svc.serialize_visit(v) for v in page], total, limit, offset)


@bp.get("/closet/visits/<vid>")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer", "Client")
def get_visit(vid):
    v = get_visit_or_404(vid)
    if g.user_role == "Client" and v["client_id"] != g.user_id:
        raise forbidden("Clients may only read their own visits")
    return ok(svc.serialize_visit(v))


@bp.post("/closet/visits/<vid>/checkout")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def checkout(vid):
    visit = get_visit_or_404(vid)
    if visit["status"] != "CHECKED_IN":
        raise invalid_state("Only a CHECKED_IN visit can be checked out")
    active = [
        ln for ln in store.lines.values()
        if ln["visit_id"] == vid and ln["status"] == "ACTIVE"
    ]
    if not active:
        raise ApiError(
            "ERR_EMPTY_VISIT_CHECKOUT", 409,
            "Checkout requires at least one ACTIVE line",
        )
    now = db.now()
    for ln in sorted(active, key=lambda l: l["_seq"]):
        ln["status"] = "DISTRIBUTED"
        touch(ln)
        item = store.items[ln["item_id"]]
        zone = store.zones.get(item["storage_zone_id"])
        item["status"] = "DISTRIBUTED"
        item["distributed_at"] = now
        item["distributed_from_zone_id"] = item["storage_zone_id"]
        item["storage_zone_id"] = None
        item["reserved_visit_id"] = None
        touch(item)
        if zone is not None:
            zone["current_stock"] -= 1
            touch(zone)
    visit["status"] = "CHECKED_OUT"
    visit["checked_out_at"] = now
    touch(visit)
    client = store.clients[visit["client_id"]]
    client["last_checkout_at"] = now
    touch(client)
    return ok(svc.serialize_visit(visit))


@bp.post("/closet/visits/<vid>/void")
@require_roles("ProgramAdmin", "VolunteerLead")
def void_visit(vid):
    visit = get_visit_or_404(vid)
    if visit["status"] != "CHECKED_IN":
        raise invalid_state("Only a CHECKED_IN visit can be voided")
    for ln in sorted(
        (l for l in store.lines.values()
         if l["visit_id"] == vid and l["status"] == "ACTIVE"),
        key=lambda l: l["_seq"],
    ):
        ln["status"] = "RELEASED"
        touch(ln)
        item = store.items[ln["item_id"]]
        if item["status"] == "RESERVED":
            item["status"] = "STOCKED"
            item["reserved_visit_id"] = None
            touch(item)
    # A voucher redeemed on a voided visit stays REDEEMED (no un-redemption).
    visit["status"] = "VOIDED"
    touch(visit)
    return ok(svc.serialize_visit(visit))


@bp.get("/closet/vouchers/<vid>/visits")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def list_voucher_visits(vid):
    voucher = store.vouchers.get(vid)
    if voucher is None:
        raise not_found("Voucher not found")
    svc.refresh_voucher(voucher)
    limit, offset = page_params()
    rows = [v for v in store.visits.values() if v["voucher_id"] == vid]
    page, total = paginate(rows, limit, offset)
    return ok_list([svc.serialize_visit(v) for v in page], total, limit, offset)

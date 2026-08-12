"""Member-scoped routes: register, read, close, children, wallet, reserved
copies, member-level subscriptions and wishlist entries."""
from datetime import datetime, timezone

from flask import Blueprint

import domain
from domain import (
    OPEN_BOX_STATES,
    base_fields,
    by_seq,
    cancel_member_wishlist,
    ledger_append,
    touch,
)
from envelope import ok_list, ok_object
from errors import (
    domain as derr,
    invalid_state,
    not_found,
    validation,
)
from serializers import (
    serialize_child,
    serialize_copy,
    serialize_ledger_entry,
    serialize_member,
    serialize_subscription,
    serialize_wishlist_entry,
)
from store import DB, clock_date
from timestamps import parse_date
from validate import (
    F,
    authenticate,
    authorize,
    body,
    finalize_shape,
    paginate,
    parse_fields,
    query_filter,
    require_ownership,
)

bp = Blueprint("members", __name__)


def _get_member(mid):
    m = DB.members.get(mid)
    if m is None:
        raise not_found("ERR_MEMBER_NOT_FOUND", "Member id does not exist.")
    return m


@bp.post("/toy-rental/members/register")
def register():
    uid, role = authenticate()
    authorize(role, {"Anonymous"})
    data = body()
    shape = parse_fields(data, [
        F("email", True, "str"),
        F("full_name", True, "str"),
        F("password", True, "str"),
    ])
    # Uniqueness (priority 8) precedes body shape (priority 11).
    email = shape.values.get("email")
    if isinstance(email, str):
        for m in DB.members.values():
            if m["email"] == email:
                raise derr("ERR_EMAIL_TAKEN", 409, "Email address is already registered.")
    finalize_shape(shape)
    m = base_fields()
    m.update({
        "email": email,
        "full_name": shape.values["full_name"],
        "password": shape.values["password"],
        "status": "ACTIVE",
    })
    DB.members[m["id"]] = m
    return ok_object(serialize_member(m), status=201)


@bp.get("/toy-rental/members/<mid>")
def get_member(mid):
    uid, role = authenticate()
    authorize(role, {"Member", "CustomerService", "PlatformAdmin"})
    m = _get_member(mid)
    require_ownership(role, uid, m["id"])
    return ok_object(serialize_member(m))


@bp.post("/toy-rental/members/<mid>/close")
def close_member(mid):
    uid, role = authenticate()
    authorize(role, {"CustomerService"})
    m = _get_member(mid)
    if m["status"] == "CLOSED":
        raise invalid_state("Member is already CLOSED.")
    sub_ids = {s["id"] for s in DB.subscriptions.values() if s["member_id"] == mid}
    for b in DB.boxes.values():
        if b["subscription_id"] in sub_ids and b["status"] in OPEN_BOX_STATES:
            raise derr("ERR_MEMBER_HAS_OPEN_BOX", 409,
                       "Member has a rotation box still open.")
    for f in DB.fees.values():
        if f["subscription_id"] in sub_ids and f["status"] in ("INVOICED", "DISPUTED"):
            raise derr("ERR_FEES_OUTSTANDING", 422,
                       "Member has fees still outstanding.")
    cancel_member_wishlist(mid, released=None)
    m["status"] = "CLOSED"
    touch(m)
    return ok_object(serialize_member(m))


@bp.post("/toy-rental/members/<mid>/children")
def create_child(mid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    m = _get_member(mid)
    require_ownership(role, uid, m["id"])
    data = body()
    shape = parse_fields(data, [
        F("name", True, "str"),
        F("birthdate", True, "date"),
    ])
    if "birthdate" in shape.values:
        bd = parse_date(shape.values["birthdate"])
        if bd > clock_date():
            shape.ok = False
    finalize_shape(shape)
    c = base_fields()
    c.update({
        "member_id": mid,
        "name": shape.values["name"],
        "birthdate": parse_date(shape.values["birthdate"]),
    })
    DB.children[c["id"]] = c
    return ok_object(serialize_child(c), status=201)


@bp.get("/toy-rental/members/<mid>/children")
def list_children(mid):
    uid, role = authenticate()
    authorize(role, {"Member", "CustomerService"})
    m = _get_member(mid)
    require_ownership(role, uid, m["id"])
    kids = by_seq([c for c in DB.children.values() if c["member_id"] == mid])
    page, meta = paginate(kids)
    return ok_list([serialize_child(c) for c in page], meta)


@bp.post("/toy-rental/members/<mid>/wallet/adjustments")
def wallet_adjustment(mid):
    uid, role = authenticate()
    authorize(role, {"CustomerService"})
    m = _get_member(mid)
    data = body()
    shape = parse_fields(data, [
        F("amount_cents", True, "int", nonzero=True),
        F("reason", True, "enum", values={"PROMO_CREDIT", "SUPPORT_ADJUSTMENT"}),
        F("note", False, "str"),
    ])
    finalize_shape(shape)
    entry = ledger_append(
        mid,
        shape.values["amount_cents"],
        shape.values["reason"],
        shape.values.get("note", ""),
    )
    return ok_object(serialize_ledger_entry(entry), status=201)


@bp.get("/toy-rental/members/<mid>/wallet/ledger")
def wallet_ledger(mid):
    uid, role = authenticate()
    authorize(role, {"Member", "CustomerService"})
    m = _get_member(mid)
    require_ownership(role, uid, m["id"])
    entries = by_seq([e for e in DB.ledger.values() if e["member_id"] == mid])
    page, meta = paginate(entries)
    return ok_list([serialize_ledger_entry(e) for e in page], meta)


@bp.get("/toy-rental/members/<mid>/reserved-copies")
def reserved_copies(mid):
    uid, role = authenticate()
    authorize(role, {"Member", "OperationsManager"})
    m = _get_member(mid)
    require_ownership(role, uid, m["id"])
    copies = by_seq([
        c for c in DB.copies.values()
        if c["status"] == "RESERVED" and c["reserved_member_id"] == mid
    ])
    page, meta = paginate(copies)
    return ok_list([serialize_copy(c) for c in page], meta)


@bp.post("/toy-rental/members/<mid>/subscriptions")
def create_subscription(mid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    m = _get_member(mid)
    data = body()
    shape = parse_fields(data, [F("plan_id", True, "str")])
    # Body-referenced plan existence (priority 3).
    plan_id = shape.values.get("plan_id")
    if isinstance(plan_id, str) and plan_id not in DB.plans:
        raise not_found("ERR_PLAN_NOT_FOUND", "SubscriptionPlan id does not exist.")
    require_ownership(role, uid, m["id"])
    for s in DB.subscriptions.values():
        if s["member_id"] == mid and s["status"] != "CANCELLED":
            raise derr("ERR_SUBSCRIPTION_ACTIVE_EXISTS", 409,
                       "Member already has a non-CANCELLED subscription.")
    finalize_shape(shape)
    s = base_fields()
    s.update({
        "member_id": mid,
        "plan_id": plan_id,
        "status": "ACTIVE",
        "next_cycle_due_at": datetime.fromisoformat(
            s["created_at"].replace("Z", "+00:00")),
        "pause_windows": [],
        "current_pause_end": None,
        "cancel_reason": None,
    })
    DB.subscriptions[s["id"]] = s
    return ok_object(serialize_subscription(s), status=201)


@bp.get("/toy-rental/members/<mid>/subscriptions")
def list_subscriptions(mid):
    uid, role = authenticate()
    authorize(role, {"Member", "CustomerService"})
    m = _get_member(mid)
    require_ownership(role, uid, m["id"])
    subs = by_seq([s for s in DB.subscriptions.values() if s["member_id"] == mid])
    page, meta = paginate(subs)
    return ok_list([serialize_subscription(s) for s in page], meta)


@bp.post("/toy-rental/members/<mid>/wishlist-entries")
def create_wishlist_entry(mid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    m = _get_member(mid)
    data = body()
    shape = parse_fields(data, [
        F("catalog_item_id", True, "str"),
        F("rank", True, "int"),
    ])
    cat_id = shape.values.get("catalog_item_id")
    cat = DB.catalog_items.get(cat_id) if isinstance(cat_id, str) else None
    if isinstance(cat_id, str) and cat is None:
        raise not_found("ERR_CATALOG_ITEM_NOT_FOUND", "CatalogItem id does not exist.")
    require_ownership(role, uid, m["id"])
    if m["status"] == "SUSPENDED":
        raise derr("ERR_MEMBER_SUSPENDED", 409, "Member is SUSPENDED.")
    for e in DB.wishlist_entries.values():
        if (
            e["member_id"] == mid
            and e["catalog_item_id"] == cat_id
            and e["status"] in ("WAITING", "HELD")
        ):
            raise derr("ERR_WISHLIST_DUPLICATE", 409,
                       "An open wishlist entry for this catalog item already exists.")
    if cat is not None and cat["status"] == "RETIRED":
        raise derr("ERR_CATALOG_ITEM_RETIRED", 422,
                   "Catalog item is RETIRED.")
    finalize_shape(shape)
    e = base_fields()
    e.update({
        "member_id": mid,
        "catalog_item_id": cat_id,
        "rank": shape.values["rank"],
        "status": "WAITING",
        "held_copy_id": None,
        "hold_expires_at": None,
    })
    DB.wishlist_entries[e["id"]] = e
    return ok_object(serialize_wishlist_entry(e), status=201)


@bp.get("/toy-rental/members/<mid>/wishlist-entries")
def list_wishlist_entries(mid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    m = _get_member(mid)
    require_ownership(role, uid, m["id"])
    status = query_filter("status")
    entries = [e for e in DB.wishlist_entries.values() if e["member_id"] == mid]
    if status is not None:
        entries = [e for e in entries if e["status"] == status]
    entries = by_seq(entries)
    page, meta = paginate(entries)
    return ok_list([serialize_wishlist_entry(e) for e in page], meta)

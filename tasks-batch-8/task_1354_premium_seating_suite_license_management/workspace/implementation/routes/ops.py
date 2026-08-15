"""Routes: catering orders, access credentials, single-event rentals."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g, request

import db
import errors
import domain
from auth import require_roles, get_or_404, resolve_fk, check_scope, is_holder, ALL_ROLES
from domain import pub_catering, pub_credential, pub_rental, now
from response import success, success_list
from util import body, req_str, req_int, req_enum, paginate, rhu, dec, req_present

bp = Blueprint("ops", __name__)

PACKAGE_TIERS = ("STANDARD", "PREMIUM", "LUXE")
CREDENTIAL_TYPES = ("HOLDER", "GUEST", "VIP")


# ---------------------------------------------------------------- shared context resolution
def _resolve_order_context(data, event, suite):
    """Exactly one of agreement_id / rental_id; references must agree with body suite/event;
    agreement context requires a license-covered event. Returns (kind, agreement, rental, account)."""
    agreement_id = data.get("agreement_id")
    rental_id = data.get("rental_id")
    if (agreement_id is None) == (rental_id is None):
        raise errors.err_invalid_request("exactly one of agreement_id / rental_id is required")
    agr = db.get("agreements", agreement_id) if agreement_id else None
    if agreement_id is not None and agr is None:
        raise errors.err_not_found("referenced agreements resource not found")
    rnt = db.get("rentals", rental_id) if rental_id else None
    if rental_id is not None and rnt is None:
        raise errors.err_not_found("referenced rentals resource not found")
    if agr is not None:
        if agr["suite_id"] != suite["id"]:
            raise errors.err_invalid_request("agreement's suite does not match suite_id")
        if not domain.event_license_covered(event, agr):
            raise errors.err_invalid_request("event is not license-covered for this agreement")
        acc = db.get("accounts", agr["account_id"])
        return "agreement", agr, None, acc
    if rnt["suite_id"] != suite["id"] or rnt["event_id"] != event["id"]:
        raise errors.err_invalid_request("rental's suite/event do not match suite_id/event_id")
    acc = db.get("accounts", rnt["account_id"])
    return "rental", None, rnt, acc


def _context_owner_id(order_or_cred):
    if order_or_cred.get("agreement_id"):
        agr = db.get("agreements", order_or_cred["agreement_id"])
        return agr["account_id"] if agr else None
    rnt = db.get("rentals", order_or_cred.get("rental_id"))
    return rnt["account_id"] if rnt else None


def _guard_place_or_issue(kind, agr, rnt, acc, event, check_cutoff):
    """Gate 8 sub-order then gate 10 cutoff for catering placement."""
    if acc is not None and acc["status"] == "SUSPENDED":
        raise errors.err_account_suspended()
    if event["status"] != "SCHEDULED":
        raise errors.err_event_not_scheduled()
    if kind == "agreement":
        if agr["status"] != "ACTIVE":
            raise errors.err_agreement_not_active()
    else:
        if rnt["status"] != "CONFIRMED":
            raise errors.err_invalid_state("rental context requires a CONFIRMED rental")
    if check_cutoff:
        if now() > domain.catering_cutoff_instant(event):
            raise errors.err_cutoff()


# ---------------------------------------------------------------- catering
def _compute_catering_totals(lines):
    """catering_order_total: per-line round_half_up, then sum; 18% service fee."""
    subtotal = 0
    for ln in lines:
        discount = dec(ln.get("discount_pct", 0))
        line_cents = rhu(Decimal(ln["quantity"]) * Decimal(ln["unit_price_cents"]) * (Decimal(1) - discount))
        subtotal += line_cents
    service_fee = rhu(Decimal(subtotal) * domain.SERVICE_FEE_RATE)
    return subtotal, service_fee, subtotal + service_fee


def _validate_catering_lines(lines):
    if not isinstance(lines, list) or not lines:
        raise errors.err_invalid_request("lines must be a non-empty list")
    for ln in lines:
        if not isinstance(ln, dict):
            raise errors.err_invalid_request("each line must be an object")
        if not isinstance(ln.get("item_code"), str) or not isinstance(ln.get("description"), str):
            raise errors.err_invalid_request("line item_code and description are required")
        q = ln.get("quantity")
        if not isinstance(q, int) or isinstance(q, bool) or q <= 0:
            raise errors.err_invalid_request("line quantity must be a positive integer")
        p = ln.get("unit_price_cents")
        if not isinstance(p, int) or isinstance(p, bool) or p < 0:
            raise errors.err_invalid_request("line unit_price_cents must be a non-negative integer")
        d = ln.get("discount_pct", 0)
        if not isinstance(d, (int, float)) or isinstance(d, bool) or d < 0 or d > 1:
            raise errors.err_invalid_request("line discount_pct must be within [0, 1]")


@bp.post("/api/catering-orders")
@require_roles("AccountHolder", "EventServicesManager", "StadiumAdmin")
def create_catering_order():
    data = body()
    event = resolve_fk("events", data.get("event_id"))
    suite = resolve_fk("suites", data.get("suite_id"))
    kind, agr, rnt, acc = _resolve_order_context(data, event, suite)
    check_scope(acc["id"] if acc else None)
    package_tier = req_enum(data, "package_tier", PACKAGE_TIERS)
    guest_count = req_int(data, "guest_count", minimum=1)
    if guest_count > suite["capacity_seats"]:
        raise errors.err_invalid_request("guest_count exceeds suite capacity_seats")
    lines = req_present(data, "lines")
    _validate_catering_lines(lines)
    _guard_place_or_issue(kind, agr, rnt, acc, event, check_cutoff=True)
    subtotal, service_fee, total = _compute_catering_totals(lines)
    order = db.new_entity({
        "event_id": event["id"],
        "suite_id": suite["id"],
        "agreement_id": agr["id"] if agr else None,
        "rental_id": rnt["id"] if rnt else None,
        "package_tier": package_tier,
        "guest_count": guest_count,
        "lines": lines,
        "subtotal_cents": subtotal,
        "service_fee_cents": service_fee,
        "total_cents": total,
        "accrual_cents": 0,
        "cancel_fee_cents": 0,
        "status": "PLACED",
    })
    db.insert("catering_orders", order)
    return success(pub_catering(order), status=201)


def _get_order_scoped(oid):
    order = get_or_404("catering_orders", oid)
    check_scope(_context_owner_id(order))
    return order


@bp.get("/api/catering-orders/<oid>")
@require_roles(*ALL_ROLES)
def get_catering_order(oid):
    return success(pub_catering(_get_order_scoped(oid)))


@bp.get("/api/catering-orders")
@require_roles(*ALL_ROLES)
def list_catering_orders():
    items = list(db.all_of("catering_orders"))
    if is_holder():
        items = [o for o in items if _context_owner_id(o) == g.user_id]
    for param in ("event_id", "suite_id", "agreement_id", "rental_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [o for o in items if o.get(param) == v]
    page, meta = paginate(items, pub_catering)
    return success_list(page, meta)


@bp.patch("/api/catering-orders/<oid>")
@require_roles("AccountHolder", "EventServicesManager", "StadiumAdmin")
def patch_catering_order(oid):
    order = get_or_404("catering_orders", oid)
    check_scope(_context_owner_id(order))
    data = body()
    expected = data.get("expected_catering_order_version")
    if expected is None:
        raise errors.err_invalid_request("expected_catering_order_version is required")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.err_invalid_request("expected_catering_order_version must be an integer")
    new_lines = data.get("lines")
    if new_lines is not None:
        _validate_catering_lines(new_lines)
    new_guests = data.get("guest_count")
    suite = db.get("suites", order["suite_id"])
    if new_guests is not None:
        if not isinstance(new_guests, int) or isinstance(new_guests, bool) or new_guests <= 0:
            raise errors.err_invalid_request("guest_count must be a positive integer")
        if suite is not None and new_guests > suite["capacity_seats"]:
            raise errors.err_invalid_request("guest_count exceeds suite capacity_seats")
    new_tier = data.get("package_tier")
    if new_tier is not None and new_tier not in PACKAGE_TIERS:
        raise errors.err_invalid_request("package_tier must be STANDARD, PREMIUM, or LUXE")
    if order["status"] != "PLACED":
        raise errors.err_invalid_state("only PLACED orders may be amended")
    if expected != order["version"]:
        raise errors.err_stale_version()
    if new_lines is not None:
        order["lines"] = new_lines
    if new_guests is not None:
        order["guest_count"] = new_guests
    if new_tier is not None:
        order["package_tier"] = new_tier
    subtotal, service_fee, total = _compute_catering_totals(order["lines"])
    order["subtotal_cents"] = subtotal
    order["service_fee_cents"] = service_fee
    order["total_cents"] = total
    db.touch(order)
    return success(pub_catering(order))


@bp.post("/api/catering-orders/<oid>/set_status")
@require_roles("AccountHolder", "EventServicesManager", "StadiumAdmin")
def catering_set_status(oid):
    order = get_or_404("catering_orders", oid)
    data = body()
    target = data.get("target_status")
    if target not in ("PLACED", "CONFIRMED", "FULFILLED", "CANCELLED", "CANCELLED_LATE"):
        raise errors.err_invalid_request("target_status must be a catering order status")
    event = db.get("events", order["event_id"])
    cur = order["status"]

    if target == "CONFIRMED":
        if g.role == "AccountHolder":
            raise errors.err_forbidden("confirmation is reserved to event services staff")
        if cur != "PLACED":
            raise errors.err_invalid_state()
        agr = db.get("agreements", order["agreement_id"]) if order.get("agreement_id") else None
        rnt = db.get("rentals", order["rental_id"]) if order.get("rental_id") else None
        if event is None or event["status"] != "SCHEDULED":
            raise errors.err_event_not_scheduled()
        if agr is not None and agr["status"] != "ACTIVE":
            raise errors.err_agreement_not_active()
        if rnt is not None and rnt["status"] != "CONFIRMED":
            raise errors.err_invalid_state("rental context requires a CONFIRMED rental")
        if now() > domain.catering_cutoff_instant(event):
            raise errors.err_cutoff()
        order["status"] = "CONFIRMED"
        order["accrual_cents"] = order["subtotal_cents"]
        db.touch(order)
        if agr is not None:
            db.touch(agr)  # accrual grew (derived field changed)
        return success(pub_catering(order))

    if target == "FULFILLED":
        if g.role == "AccountHolder":
            raise errors.err_forbidden("fulfilment is reserved to event services staff")
        if cur != "CONFIRMED":
            raise errors.err_invalid_state()
        if event is None or now() < event["starts_at"]:
            raise errors.err_invalid_state("order can only be fulfilled at/after event start")
        order["status"] = "FULFILLED"
        db.touch(order)
        return success(pub_catering(order))

    if target == "CANCELLED":
        check_scope(_context_owner_id(order))
        if cur == "PLACED":
            order["status"] = "CANCELLED"
            order["cancel_fee_cents"] = 0
            order["accrual_cents"] = 0
            db.touch(order)
            return success(pub_catering(order))
        if cur != "CONFIRMED":
            raise errors.err_invalid_state()
        if event is not None and now() >= event["starts_at"]:
            raise errors.err_invalid_state("order can no longer be cancelled at/after event start")
        agr = db.get("agreements", order["agreement_id"]) if order.get("agreement_id") else None
        if event is not None and now() <= domain.catering_cutoff_instant(event):
            # free cancellation: accrual removed (confirm + free-cancel nets to zero)
            order["status"] = "CANCELLED"
            order["cancel_fee_cents"] = 0
            order["accrual_cents"] = 0
        else:
            # late cancellation: half the total, accrual switches to the fee
            fee = rhu(Decimal("0.5") * order["total_cents"])
            order["status"] = "CANCELLED_LATE"
            order["cancel_fee_cents"] = fee
            order["accrual_cents"] = fee
        db.touch(order)
        if agr is not None:
            db.touch(agr)
        return success(pub_catering(order))

    # PLACED / CANCELLED_LATE are never direct targets
    raise errors.err_invalid_state()


# ---------------------------------------------------------------- credentials
@bp.post("/api/credentials")
@require_roles("AccountHolder", "EventServicesManager", "StadiumAdmin")
def create_credential():
    data = body()
    event = resolve_fk("events", data.get("event_id"))
    suite = resolve_fk("suites", data.get("suite_id"))
    kind, agr, rnt, acc = _resolve_order_context(data, event, suite)
    check_scope(acc["id"] if acc else None)
    guest_name = req_str(data, "guest_name")
    guest_email = req_str(data, "guest_email")
    cred_type = req_enum(data, "credential_type", CREDENTIAL_TYPES)
    _guard_place_or_issue(kind, agr, rnt, acc, event, check_cutoff=False)
    active_count = sum(1 for c in db.all_of("credentials")
                       if c["event_id"] == event["id"] and c["suite_id"] == suite["id"]
                       and c["status"] in ("ISSUED", "ACTIVATED"))
    if active_count >= suite["capacity_seats"]:
        raise errors.err_credential_capacity()
    for c in db.all_of("credentials"):
        if c["event_id"] == event["id"] and c["suite_id"] == suite["id"] \
                and c["status"] not in ("REVOKED", "EXPIRED") and c["guest_email"] == guest_email:
            raise errors.err_duplicate_guest()
    cred = db.new_entity({
        "event_id": event["id"],
        "suite_id": suite["id"],
        "agreement_id": agr["id"] if agr else None,
        "rental_id": rnt["id"] if rnt else None,
        "guest_name": guest_name,
        "guest_email": guest_email,
        "credential_type": cred_type,
        "barcode": db.mint_id().replace("-", ""),
        "status": "ISSUED",
    })
    db.insert("credentials", cred)
    return success(pub_credential(cred), status=201)


def _get_credential_scoped(cid):
    cred = get_or_404("credentials", cid)
    check_scope(_context_owner_id(cred))
    return cred


@bp.get("/api/credentials/<cid>")
@require_roles(*ALL_ROLES)
def get_credential(cid):
    return success(pub_credential(_get_credential_scoped(cid)))


@bp.get("/api/credentials")
@require_roles(*ALL_ROLES)
def list_credentials():
    items = list(db.all_of("credentials"))
    if is_holder():
        items = [c for c in items if _context_owner_id(c) == g.user_id]
    for param in ("event_id", "suite_id", "agreement_id", "rental_id", "guest_email", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c.get(param) == v]
    page, meta = paginate(items, pub_credential)
    return success_list(page, meta)


@bp.post("/api/credentials/<cid>/set_status")
@require_roles("AccountHolder", "EventServicesManager", "StadiumAdmin")
def credential_set_status(cid):
    cred = get_or_404("credentials", cid)
    data = body()
    target = data.get("target_status")
    if target not in ("ISSUED", "ACTIVATED", "REVOKED", "EXPIRED"):
        raise errors.err_invalid_request("target_status must be a credential status")
    if target == "ACTIVATED":
        if g.role == "AccountHolder":
            raise errors.err_forbidden("activation is reserved to event services staff")
        if cred["status"] != "ISSUED":
            raise errors.err_invalid_state()
        event = db.get("events", cred["event_id"])
        if event is None or event["status"] != "SCHEDULED":
            raise errors.err_event_not_scheduled()
        clock = now()
        window_start = event["starts_at"] - timedelta(hours=4)
        window_end = event["starts_at"] + timedelta(hours=event.get("duration_hours", 4))
        if not (window_start <= clock <= window_end):
            raise errors.err_credential_window()
        cred["status"] = "ACTIVATED"
        db.touch(cred)
        return success(pub_credential(cred))
    if target == "REVOKED":
        check_scope(_context_owner_id(cred))
        if cred["status"] != "ISSUED":
            raise errors.err_invalid_state()
        cred["status"] = "REVOKED"
        db.touch(cred)
        return success(pub_credential(cred))
    # ISSUED / EXPIRED are not direct targets
    raise errors.err_invalid_state()


# ---------------------------------------------------------------- rentals
def _rental_quote(suite, event, guest_count):
    """rental_price_quote: tier multiplier + per-guest overage, playoff multiplier,
    single rounding at the end; deposit rounds separately."""
    mult = domain.TIER_MULTIPLIER[suite["tier"]]
    overage = max(0, guest_count - suite["capacity_seats"]) * domain.PER_GUEST_OVERAGE_CENTS
    playoff = domain.PLAYOFF_MULT if event["event_type"] == "PLAYOFF" else Decimal("1.00")
    quoted = rhu((Decimal(event["rental_base_price_cents"]) * mult + Decimal(overage)) * playoff)
    deposit = rhu(Decimal(quoted) * domain.DEPOSIT_RATE)
    return quoted, deposit


@bp.post("/api/rentals")
@require_roles("PremiumSalesRep", "AccountHolder", "StadiumAdmin")
def create_rental():
    data = body()
    event = resolve_fk("events", data.get("event_id"))
    suite = resolve_fk("suites", data.get("suite_id"))
    acc = resolve_fk("accounts", data.get("account_id"))
    check_scope(acc["id"])
    guest_count = req_int(data, "guest_count", minimum=1)
    if not domain.rental_availability_ok(suite, event):
        raise errors.err_suite_not_available()
    quoted, deposit = _rental_quote(suite, event, guest_count)
    rental = db.new_entity({
        "event_id": event["id"],
        "suite_id": suite["id"],
        "account_id": acc["id"],
        "guest_count": guest_count,
        "quoted_price_cents": quoted,
        "deposit_cents": deposit,
        "hold_expires_at": None,
        "cancel_fee_cents": 0,
        "status": "QUOTED",
        "_rental_invoice_id": None,
    })
    db.insert("rentals", rental)
    return success(pub_rental(rental), status=201)


def _get_rental_scoped(rid):
    r = get_or_404("rentals", rid)
    check_scope(r["account_id"])
    return r


@bp.get("/api/rentals/<rid>")
@require_roles(*ALL_ROLES)
def get_rental(rid):
    return success(pub_rental(_get_rental_scoped(rid)))


@bp.get("/api/rentals")
@require_roles(*ALL_ROLES)
def list_rentals():
    items = list(db.all_of("rentals"))
    if is_holder():
        items = [r for r in items if r["account_id"] == g.user_id]
    for param in ("event_id", "suite_id", "account_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(param) == v]
    page, meta = paginate(items, pub_rental)
    return success_list(page, meta)


@bp.post("/api/rentals/<rid>/set_status")
@require_roles("PremiumSalesRep", "AccountHolder", "StadiumAdmin")
def rental_set_status(rid):
    rental = get_or_404("rentals", rid)
    data = body()
    target = data.get("target_status")
    if target not in ("QUOTED", "HELD", "CONFIRMED", "SETTLED", "CANCELLED", "EXPIRED"):
        raise errors.err_invalid_request("target_status must be a rental status")
    cur = rental["status"]
    clock = now()
    event = db.get("events", rental["event_id"])
    suite = db.get("suites", rental["suite_id"])
    acc = db.get("accounts", rental["account_id"])

    if target == "HELD":
        check_scope(rental["account_id"])
        if cur != "QUOTED":
            raise errors.err_invalid_state()
        if acc is not None and acc["status"] == "SUSPENDED":
            raise errors.err_account_suspended()
        if not domain.rental_availability_ok(suite, event, exclude_rental_id=rid):
            raise errors.err_suite_not_available()
        rental["status"] = "HELD"
        rental["hold_expires_at"] = clock + timedelta(hours=48)
        db.touch(rental)
        return success(pub_rental(rental))

    if target == "CONFIRMED":
        if g.role == "AccountHolder":
            raise errors.err_forbidden("confirmation is reserved to PremiumSalesRep or StadiumAdmin")
        if cur != "HELD":
            raise errors.err_invalid_state()
        if not clock <= rental["hold_expires_at"]:
            raise errors.err_hold_expired()
        if not domain.rental_availability_ok(suite, event, exclude_rental_id=rid):
            raise errors.err_suite_not_available()
        if domain.account_credit_standing(rental["account_id"]) == "HOLD":
            raise errors.err_credit_hold()
        inv = domain.create_auto_invoice(
            account_id=rental["account_id"], invoice_type="RENTAL",
            amount_cents=rental["quoted_price_cents"], description="Single-event rental",
            due_on=event["starts_at"] - timedelta(days=7), rental_id=rid)
        rental["_rental_invoice_id"] = inv["id"]
        rental["status"] = "CONFIRMED"
        db.touch(rental)
        return success(pub_rental(rental))

    if target == "CANCELLED":
        check_scope(rental["account_id"])
        if cur in ("QUOTED", "HELD"):
            rental["status"] = "CANCELLED"
            rental["cancel_fee_cents"] = 0
            db.touch(rental)
            return success(pub_rental(rental))
        if cur != "CONFIRMED":
            raise errors.err_invalid_state()
        inv = db.get("invoices", rental.get("_rental_invoice_id")) if rental.get("_rental_invoice_id") else None
        if inv is not None and inv["status"] != "ISSUED":
            raise errors.err_rental_settlement()
        if not clock < event["starts_at"]:
            raise errors.err_invalid_state("confirmed rental can only be cancelled before event start")
        days = int((event["starts_at"] - clock).total_seconds() // 86400)
        if days >= 14:
            pct = Decimal("0.10")
        elif days >= 7:
            pct = Decimal("0.30")
        elif days >= 3:
            pct = Decimal("0.50")
        else:
            pct = Decimal("1.00")
        fee = rhu(pct * rental["quoted_price_cents"])
        if inv is not None:
            inv["status"] = "VOID"
            db.touch(inv)
            db.touch(acc)
        if fee > 0:
            domain.create_auto_invoice(
                account_id=rental["account_id"], invoice_type="RENTAL", amount_cents=fee,
                description="cancellation fee", due_on=clock + timedelta(days=14),
                rental_id=rid)
        rental["status"] = "CANCELLED"
        rental["cancel_fee_cents"] = fee
        db.touch(rental)
        return success(pub_rental(rental))

    if target == "EXPIRED":
        if g.role != "StadiumAdmin":
            raise errors.err_forbidden("rental expiry is reserved to StadiumAdmin")
        if cur == "QUOTED":
            rental["status"] = "EXPIRED"
            db.touch(rental)
            return success(pub_rental(rental))
        if cur != "HELD":
            raise errors.err_invalid_state()
        if not clock > rental["hold_expires_at"]:
            raise errors.err_hold_not_expired()
        rental["status"] = "EXPIRED"
        db.touch(rental)
        return success(pub_rental(rental))

    # QUOTED / SETTLED are not direct targets
    raise errors.err_invalid_state()

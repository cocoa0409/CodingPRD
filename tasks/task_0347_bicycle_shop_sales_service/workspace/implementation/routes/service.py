"""Service tickets, labor lines, service bays, bay bookings (PRD §3.2-§3.4)."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import authenticate, require_roles
from response import ok, created, list_ok
import helpers as h
import services as svc

bp = Blueprint("service", __name__)


# ---------------- ServiceTicket ----------------
@bp.route("/shop/service-tickets", methods=["POST"])
def create_ticket():
    _, role = authenticate()
    require_roles(role, ["ServiceAdvisor"])
    body = h.get_body()
    with db.LOCK:
        customer_id = h.require_str(body, "customer_id")
        tier_id = h.require_str(body, "tier_id")
        is_rush = h.require_bool(body, "is_rush", default=False)
        warranty_claim_id = h.optional_str(body, "warranty_claim_id", default=None)
        # existence, left to right
        h.must_exist(db.customers, customer_id)
        h.must_exist(db.tune_up_tiers, tier_id)
        if warranty_claim_id is not None:
            h.must_exist(db.warranty_claims, warranty_claim_id)
        rec = {
            "customer_id": customer_id,
            "tier_id": tier_id,
            "warranty_claim_id": warranty_claim_id,
            "status": "INTAKE",
            "is_rush": is_rush,
            "promised_ready_at": None,
            "labor_subtotal_cents": 0,
            "revision_count": 0,
            "customer_owes_cents": 0,
        }
        h.stamp_create(rec)
        db.service_tickets[rec["id"]] = rec
        return created(h.public(rec))


@bp.route("/shop/service-tickets/<tid>", methods=["GET"])
def read_ticket(tid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager", "Customer"])
    with db.LOCK:
        rec = h.must_exist(db.service_tickets, tid)
        return ok(h.public(rec))


@bp.route("/shop/service-tickets", methods=["GET"])
def list_tickets():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager"])
    with db.LOCK:
        recs = list(db.service_tickets.values())
        for f in ("customer_id", "tier_id", "warranty_claim_id"):
            v = request.args.get(f)
            if v is not None:
                recs = [r for r in recs if r[f] == v]
        items, limit, offset, total = h.paginate(recs)
        return list_ok(items, limit, offset, total)


@bp.route("/shop/service-tickets/<tid>/quote", methods=["POST"])
def quote_ticket(tid):
    _, role = authenticate()
    require_roles(role, ["ServiceAdvisor"])
    with db.LOCK:
        rec = h.must_exist(db.service_tickets, tid)
        if rec["status"] != "INTAKE":
            raise ApiError("ERR_INVALID_STATE", "Quote requires INTAKE.")
        # tier existence already guaranteed at create, but re-check per scaffold
        h.must_exist(db.tune_up_tiers, rec["tier_id"])
        svc.compute_ticket_quote(rec)
        rec["status"] = "AWAITING_APPROVAL"
        h.touch(rec)
        return ok(h.public(rec))


@bp.route("/shop/service-tickets/<tid>/approve", methods=["POST"])
def approve_ticket(tid):
    user_id, role = authenticate()
    require_roles(role, ["Customer"])
    with db.LOCK:
        rec = h.must_exist(db.service_tickets, tid)
        # priority 3: ownership — unless ticket is a warranty execution.
        # PRD §2.1/§3.2: a warranty ticket relaxes the customer-ownership requirement.
        if rec["warranty_claim_id"] is None:
            if rec["customer_id"] != user_id:
                raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the ticket owner.")
        if rec["status"] != "AWAITING_APPROVAL":
            raise ApiError("ERR_INVALID_STATE", "Approve requires AWAITING_APPROVAL.")
        rec["status"] = "IN_PROGRESS"
        h.touch(rec)
        return ok(h.public(rec))


@bp.route("/shop/service-tickets/<tid>/complete", methods=["POST"])
def complete_ticket(tid):
    _, role = authenticate()
    require_roles(role, ["ServiceAdvisor"])
    with db.LOCK:
        rec = h.must_exist(db.service_tickets, tid)
        if rec["status"] != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_STATE", "Complete requires IN_PROGRESS.")
        rec["status"] = "READY_FOR_PICKUP"
        h.touch(rec)
        return ok(h.public(rec))


@bp.route("/shop/service-tickets/<tid>/close", methods=["POST"])
def close_ticket(tid):
    _, role = authenticate()
    require_roles(role, ["ServiceAdvisor"])
    with db.LOCK:
        rec = h.must_exist(db.service_tickets, tid)
        if rec["status"] != "READY_FOR_PICKUP":
            raise ApiError("ERR_INVALID_STATE", "Close requires READY_FOR_PICKUP.")
        # cross-entity guard: linked claim must be APPROVED_REPAIR (PRD §3.2)
        if rec["warranty_claim_id"] is not None:
            claim = db.warranty_claims.get(rec["warranty_claim_id"])
            if claim is None or claim["status"] != "APPROVED_REPAIR":
                raise ApiError("ERR_INVALID_STATE",
                               "Linked warranty claim is not APPROVED_REPAIR.")
            claim["status"] = "RESOLVED"
            h.touch(claim)
        rec["status"] = "CLOSED"
        h.touch(rec)
        return ok(h.public(rec))


@bp.route("/shop/service-tickets/<tid>/cancel", methods=["POST"])
def cancel_ticket(tid):
    _, role = authenticate()
    require_roles(role, ["ServiceAdvisor"])
    with db.LOCK:
        rec = h.must_exist(db.service_tickets, tid)
        if rec["status"] not in ("INTAKE", "AWAITING_APPROVAL"):
            raise ApiError("ERR_INVALID_STATE", "Cancel requires INTAKE or AWAITING_APPROVAL.")
        rec["status"] = "CANCELLED"
        h.touch(rec)
        return ok(h.public(rec))


# ---------------- LaborLine ----------------
@bp.route("/shop/labor-lines", methods=["POST"])
def create_labor_line():
    _, role = authenticate()
    require_roles(role, ["ServiceAdvisor"])
    body = h.get_body()
    with db.LOCK:
        ticket_id = h.require_str(body, "ticket_id")
        menu_code = h.require_str(body, "menu_code")
        labor_cents = h.require_int(body, "labor_cents", minimum=0)
        ticket = h.must_exist(db.service_tickets, ticket_id)
        added_after_approval = False
        rec = {
            "ticket_id": ticket_id,
            "menu_code": menu_code,
            "labor_cents": labor_cents,
            "added_after_approval": False,
        }
        h.stamp_create(rec)
        # IN_PROGRESS revision loop (PRD §3.2/§3.3); warranty repairs exempt.
        if ticket["status"] == "IN_PROGRESS" and ticket["warranty_claim_id"] is None:
            rec["added_after_approval"] = True
            db.labor_lines[rec["id"]] = rec
            ticket["status"] = "AWAITING_APPROVAL"
            ticket["revision_count"] += 1
            svc.compute_ticket_quote(ticket)
            h.touch(ticket)
        else:
            db.labor_lines[rec["id"]] = rec
            # recompute quote so labor_subtotal reflects the new line
            svc.compute_ticket_quote(ticket)
            h.touch(ticket)
        return created(h.public(rec))


@bp.route("/shop/labor-lines/<lid>", methods=["GET"])
def read_labor_line(lid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager"])
    with db.LOCK:
        rec = h.must_exist(db.labor_lines, lid)
        return ok(h.public(rec))


@bp.route("/shop/labor-lines", methods=["GET"])
def list_labor_lines():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager"])
    with db.LOCK:
        recs = list(db.labor_lines.values())
        v = request.args.get("ticket_id")
        if v is not None:
            recs = [r for r in recs if r["ticket_id"] == v]
        items, limit, offset, total = h.paginate(recs)
        return list_ok(items, limit, offset, total)


# ---------------- ServiceBay ----------------
@bp.route("/shop/service-bays", methods=["POST"])
def create_bay():
    _, role = authenticate()
    require_roles(role, ["ShopManager"])
    body = h.get_body()
    with db.LOCK:
        name = h.require_str(body, "name")
        is_active = h.require_bool(body, "is_active", default=True)
        rec = {"name": name, "is_active": is_active}
        h.stamp_create(rec)
        db.service_bays[rec["id"]] = rec
        return created(h.public(rec))


@bp.route("/shop/service-bays/<bid>", methods=["GET"])
def read_bay(bid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager"])
    with db.LOCK:
        rec = h.must_exist(db.service_bays, bid)
        return ok(h.public(rec))


@bp.route("/shop/service-bays", methods=["GET"])
def list_bays():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager"])
    with db.LOCK:
        items, limit, offset, total = h.paginate(list(db.service_bays.values()))
        return list_ok(items, limit, offset, total)


@bp.route("/shop/service-bays/<bid>/bookings", methods=["GET"])
def list_bay_bookings_for_bay(bid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager"])
    with db.LOCK:
        h.must_exist(db.service_bays, bid)
        status = request.args.get("status")
        recs = [r for r in db.bay_bookings.values() if r["bay_id"] == bid]
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        items, limit, offset, total = h.paginate(recs)
        return list_ok(items, limit, offset, total)


# ---------------- BayBooking ----------------
@bp.route("/shop/bay-bookings", methods=["POST"])
def create_bay_booking():
    _, role = authenticate()
    require_roles(role, ["ServiceAdvisor"])
    body = h.get_body()
    with db.LOCK:
        bay_id = h.require_str(body, "bay_id")
        ticket_id = h.require_str(body, "ticket_id")
        start_at = h.require_datetime(body, "start_at")
        end_at = h.require_datetime(body, "end_at")
        h.must_exist(db.service_bays, bay_id)
        h.must_exist(db.service_tickets, ticket_id)
        # priority 20: end_at strictly after start_at; no overlap with BOOKED.
        if end_at <= start_at:
            raise ApiError("ERR_BAY_DOUBLE_BOOKED", "end_at must be strictly after start_at.")
        for r in db.bay_bookings.values():
            if r["bay_id"] == bay_id and r["status"] == "BOOKED":
                ex_start = db._parse_iso(r["start_at"])
                ex_end = db._parse_iso(r["end_at"])
                # half-open overlap: ex_start < new_end AND new_start < ex_end
                if ex_start < end_at and start_at < ex_end:
                    raise ApiError("ERR_BAY_DOUBLE_BOOKED", "Overlaps an existing booking.")
        rec = {
            "bay_id": bay_id,
            "ticket_id": ticket_id,
            "start_at": db.format_dt(start_at),
            "end_at": db.format_dt(end_at),
            "status": "BOOKED",
        }
        h.stamp_create(rec)
        db.bay_bookings[rec["id"]] = rec
        return created(h.public(rec))


@bp.route("/shop/bay-bookings/<bid>", methods=["GET"])
def read_bay_booking(bid):
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager"])
    with db.LOCK:
        rec = h.must_exist(db.bay_bookings, bid)
        return ok(h.public(rec))


@bp.route("/shop/bay-bookings", methods=["GET"])
def list_bay_bookings():
    _, role = authenticate()
    require_roles(role, ["SalesAssociate", "ServiceAdvisor", "ShopManager"])
    with db.LOCK:
        recs = list(db.bay_bookings.values())
        for f in ("bay_id", "ticket_id", "status"):
            v = request.args.get(f)
            if v is not None:
                recs = [r for r in recs if r[f] == v]
        items, limit, offset, total = h.paginate(recs)
        return list_ok(items, limit, offset, total)


@bp.route("/shop/bay-bookings/<bid>/release", methods=["POST"])
def release_bay_booking(bid):
    _, role = authenticate()
    require_roles(role, ["ServiceAdvisor"])
    with db.LOCK:
        rec = h.must_exist(db.bay_bookings, bid)
        if rec["status"] != "BOOKED":
            raise ApiError("ERR_INVALID_STATE", "Release requires BOOKED.")
        rec["status"] = "RELEASED"
        h.touch(rec)
        return ok(h.public(rec))

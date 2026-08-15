"""Routes: telescopes, maintenance tickets, training certifications, loan reservations."""
from datetime import timedelta

from flask import Blueprint, request

import domain as D
from helpers import (ApiError, actor, as_bool, as_enum, as_int, as_str, body,
                     field, fk, list_response, parse_dt, sorted_items, success)
from store import DB
import views

equip_bp = Blueprint("equipment", __name__)

ALL_ROLES = ("ClubOfficer", "Member", "EventCoordinator", "EquipmentChair")


def _get_or_404(table, rid):
    ent = table.get(rid)
    if ent is None:
        raise ApiError(404, "ERR_NOT_FOUND", "Resource not found: %s" % rid)
    return ent


# ----- telescopes -----

@equip_bp.post("/club/telescopes")
def create_telescope():
    actor(["EquipmentChair"])
    data = body()
    name = as_str(field(data, "name"), "name")
    eclass = as_enum(field(data, "equipment_class"), "equipment_class",
                     D.EQUIPMENT_CLASSES)
    t = D.mint(DB)
    t.update({
        "name": name,
        "equipment_class": eclass,
        "status": "AVAILABLE",
        # New inventory is assumed freshly collimated.
        "collimation_due_at": DB.clock + timedelta(days=D.COLLIMATION_INTERVAL_DAYS),
        "condition_score": 100,
    })
    DB.telescopes[t["id"]] = t
    return success(views.telescope_view(DB, t), 201)


@equip_bp.get("/club/telescopes/<telescope_id>")
def get_telescope(telescope_id):
    actor(ALL_ROLES)
    return success(views.telescope_view(DB, _get_or_404(DB.telescopes, telescope_id)), 200)


@equip_bp.get("/club/telescopes")
def list_telescopes():
    actor(ALL_ROLES)
    items = sorted_items(DB.telescopes)
    status = request.args.get("status")
    eclass = request.args.get("equipment_class")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    if eclass is not None:
        items = [t for t in items if t["equipment_class"] == eclass]
    return list_response(items, lambda t: views.telescope_view(DB, t))


@equip_bp.put("/club/telescopes/<telescope_id>")
def update_telescope(telescope_id):
    actor(["EquipmentChair"])
    t = _get_or_404(DB.telescopes, telescope_id)
    data = body()
    name = as_str(field(data, "name"), "name")
    expected = as_int(field(data, "expected_telescope_version"),
                      "expected_telescope_version")
    if expected != t["version"]:
        raise ApiError(412, "ERR_STALE_VERSION",
                       "expected_telescope_version does not match the telescope's version")
    t["name"] = name
    D.stamp(DB, t)
    return success(views.telescope_view(DB, t), 200)


@equip_bp.post("/club/telescopes/<telescope_id>/retire")
def retire_telescope(telescope_id):
    actor(["EquipmentChair"])
    t = _get_or_404(DB.telescopes, telescope_id)
    if t["status"] not in ("AVAILABLE", "MAINTENANCE"):
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Only AVAILABLE or MAINTENANCE telescopes may be retired")
    live = [l for l in DB.loans.values() if l["telescope_id"] == t["id"]]
    if t["status"] == "AVAILABLE":
        blocked = any(l["status"] in ("RESERVED", "CHECKED_OUT", "OVERDUE") for l in live)
    else:
        blocked = any(l["status"] in ("CHECKED_OUT", "OVERDUE") for l in live)
    if blocked:
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Telescope has loan reservations blocking retirement")
    if t["status"] == "MAINTENANCE":
        # Write-off path: force-close all non-CLOSED tickets, applying their deltas.
        for tk in DB.tickets.values():
            if tk["telescope_id"] == t["id"] and tk["status"] != "CLOSED":
                tk["status"] = "CLOSED"
                tk["closed_at"] = DB.clock
                D.stamp(DB, tk)
        D.recompute_condition(DB, t)
    t["status"] = "RETIRED"
    D.stamp(DB, t)
    return success(views.telescope_view(DB, t), 200)


# ----- maintenance tickets -----

@equip_bp.post("/club/maintenance-tickets")
def create_ticket():
    actor(["EquipmentChair"])
    data = body()
    tele = fk(data, "telescope_id", DB.telescopes)
    as_str(field(data, "telescope_id"), "telescope_id")
    kind = as_enum(field(data, "kind"), "kind", D.TICKET_KINDS)
    severity = as_enum(field(data, "severity"), "severity", D.TICKET_SEVERITIES)
    delta = as_int(field(data, "condition_delta"), "condition_delta")
    tk = D.mint(DB)
    tk.update({
        "telescope_id": tele["id"],
        "kind": kind,
        "severity": severity,
        "status": "OPEN",
        "opened_at": DB.clock,
        "closed_at": None,
        "condition_delta": delta,
    })
    DB.tickets[tk["id"]] = tk
    if tele["status"] == "AVAILABLE":
        tele["status"] = "MAINTENANCE"
        D.stamp(DB, tele)
    return success(views.ticket_view(DB, tk), 201)


@equip_bp.get("/club/maintenance-tickets/<ticket_id>")
def get_ticket(ticket_id):
    actor(["ClubOfficer", "EquipmentChair"])
    return success(views.ticket_view(DB, _get_or_404(DB.tickets, ticket_id)), 200)


@equip_bp.get("/club/maintenance-tickets")
def list_tickets():
    actor(["ClubOfficer", "EquipmentChair"])
    items = sorted_items(DB.tickets)
    telescope_id = request.args.get("telescope_id")
    status = request.args.get("status")
    if telescope_id is not None:
        items = [t for t in items if t["telescope_id"] == telescope_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    return list_response(items, lambda t: views.ticket_view(DB, t))


def _ticket_transition(ticket_id, from_status, to_status):
    actor(["EquipmentChair"])
    tk = _get_or_404(DB.tickets, ticket_id)
    if tk["status"] != from_status:
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Ticket is %s, not %s" % (tk["status"], from_status))
    tk["status"] = to_status
    D.stamp(DB, tk)
    return tk


@equip_bp.post("/club/maintenance-tickets/<ticket_id>/start")
def start_ticket(ticket_id):
    tk = _ticket_transition(ticket_id, "OPEN", "IN_PROGRESS")
    return success(views.ticket_view(DB, tk), 200)


@equip_bp.post("/club/maintenance-tickets/<ticket_id>/submit-verification")
def submit_verification(ticket_id):
    tk = _ticket_transition(ticket_id, "IN_PROGRESS", "VERIFICATION")
    return success(views.ticket_view(DB, tk), 200)


@equip_bp.post("/club/maintenance-tickets/<ticket_id>/reopen")
def reopen_ticket(ticket_id):
    tk = _ticket_transition(ticket_id, "VERIFICATION", "IN_PROGRESS")
    return success(views.ticket_view(DB, tk), 200)


@equip_bp.post("/club/maintenance-tickets/<ticket_id>/close")
def close_ticket(ticket_id):
    actor(["EquipmentChair"])
    tk = _get_or_404(DB.tickets, ticket_id)
    if tk["status"] != "VERIFICATION":
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Only a VERIFICATION ticket may be closed")
    tk["status"] = "CLOSED"
    tk["closed_at"] = DB.clock
    D.stamp(DB, tk)
    tele = DB.telescopes[tk["telescope_id"]]
    D.recompute_condition(DB, tele)
    if tk["kind"] == "COLLIMATION":
        tele["collimation_due_at"] = DB.clock + timedelta(days=D.COLLIMATION_INTERVAL_DAYS)
    remaining = any(o["telescope_id"] == tele["id"] and o["status"] != "CLOSED"
                    for o in DB.tickets.values())
    if not remaining and tele["status"] == "MAINTENANCE":
        tele["status"] = "AVAILABLE"
    D.stamp(DB, tele)
    return success(views.ticket_view(DB, tk), 200)


# ----- training certifications -----

@equip_bp.post("/club/training-certifications")
def create_cert():
    actor(["EquipmentChair"])
    data = body()
    member = fk(data, "member_id", DB.members)
    as_str(field(data, "member_id"), "member_id")
    eclass = as_enum(field(data, "equipment_class"), "equipment_class",
                     D.EQUIPMENT_CLASSES)
    expires = parse_dt(field(data, "expires_at"), "expires_at")
    c = D.mint(DB)
    c.update({
        "member_id": member["id"],
        "equipment_class": eclass,
        "issued_at": DB.clock,
        "expires_at": expires,
        "status": "ACTIVE",
    })
    DB.certs[c["id"]] = c
    return success(views.cert_view(DB, c), 201)


@equip_bp.get("/club/training-certifications/<cert_id>")
def get_cert(cert_id):
    actor(ALL_ROLES)
    return success(views.cert_view(DB, _get_or_404(DB.certs, cert_id)), 200)


@equip_bp.get("/club/training-certifications")
def list_certs():
    actor(ALL_ROLES)
    items = sorted_items(DB.certs)
    member_id = request.args.get("member_id")
    eclass = request.args.get("equipment_class")
    status = request.args.get("status")
    if member_id is not None:
        items = [c for c in items if c["member_id"] == member_id]
    if eclass is not None:
        items = [c for c in items if c["equipment_class"] == eclass]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items, lambda c: views.cert_view(DB, c))


@equip_bp.post("/club/training-certifications/<cert_id>/revoke")
def revoke_cert(cert_id):
    actor(["EquipmentChair"])
    c = _get_or_404(DB.certs, cert_id)
    if c["status"] != "ACTIVE":
        raise ApiError(409, "ERR_INVALID_STATE", "Only an ACTIVE certification may be revoked")
    c["status"] = "REVOKED"
    D.stamp(DB, c)
    # Cascade: cancel this member's RESERVED loans whose telescope class matches.
    for l in DB.loans.values():
        if l["member_id"] != c["member_id"] or l["status"] != "RESERVED":
            continue
        tele = DB.telescopes.get(l["telescope_id"])
        if tele is not None and tele["equipment_class"] == c["equipment_class"]:
            D.cancel_loan(DB, l)
    return success(views.cert_view(DB, c), 200)


# ----- loan reservations -----

@equip_bp.post("/club/loan-reservations")
def create_loan():
    uid, role = actor(["Member", "EquipmentChair"])
    data = body()
    member = fk(data, "member_id", DB.members)
    tele = fk(data, "telescope_id", DB.telescopes)
    if role == "Member" and isinstance(data.get("member_id"), str) \
            and data["member_id"] != uid:
        raise ApiError(403, "ERR_FORBIDDEN",
                       "A Member may only reserve loans for itself")
    as_str(field(data, "member_id"), "member_id")
    as_str(field(data, "telescope_id"), "telescope_id")
    ws = parse_dt(field(data, "window_start"), "window_start")
    we = parse_dt(field(data, "window_end"), "window_end")
    if not (ws < we):
        raise ApiError(422, "ERR_INVALID_WINDOW",
                       "window_start must be strictly before window_end")
    # Ordered battery per PRD 3.4: cert -> standing -> reservable -> conflict -> cap.
    if not D.has_active_cert(DB, member["id"], tele["equipment_class"]):
        raise ApiError(422, "ERR_CERTIFICATION_REQUIRED",
                       "Member lacks an ACTIVE certification for the telescope's class")
    tier = DB.tiers[member["tier_id"]]
    if member["status"] != "ACTIVE" or not tier["loan_privilege"]:
        raise ApiError(422, "ERR_MEMBER_NOT_IN_GOOD_STANDING",
                       "Member is not ACTIVE or the tier lacks loan_privilege")
    if tele["status"] != "AVAILABLE" or not (tele["collimation_due_at"] > DB.clock):
        raise ApiError(409, "ERR_TELESCOPE_NOT_RESERVABLE",
                       "Telescope is not AVAILABLE or is due for collimation")
    for other in DB.loans.values():
        if other["member_id"] != member["id"]:
            continue
        if other["status"] not in D.NON_TERMINAL_LOAN:
            continue
        # Half-open intersection; touching windows (ws == other.we) do not intersect.
        if other["window_start"] < we and ws < other["window_end"]:
            raise ApiError(409, "ERR_LOAN_WINDOW_CONFLICT",
                           "New window intersects an existing reservation of this member")
    held = sum(1 for l in DB.loans.values()
               if l["member_id"] == member["id"] and l["status"] in D.NON_TERMINAL_LOAN)
    if held >= tier["max_concurrent_loans"]:
        raise ApiError(422, "ERR_LOAN_CAP_REACHED",
                       "Member already holds the tier's maximum concurrent loans")
    l = D.mint(DB)
    l.update({
        "member_id": member["id"],
        "telescope_id": tele["id"],
        "window_start": ws,
        "window_end": we,
        "status": "RESERVED",
        "checkout_at": None,
        "returned_at": None,
        "overdue_fees_cents": 0,
    })
    DB.loans[l["id"]] = l
    tele["status"] = "RESERVED"
    D.stamp(DB, tele)
    return success(views.loan_view(DB, l), 201)


@equip_bp.get("/club/loan-reservations/<loan_id>")
def get_loan(loan_id):
    actor(["ClubOfficer", "Member", "EquipmentChair"])
    return success(views.loan_view(DB, _get_or_404(DB.loans, loan_id)), 200)


@equip_bp.get("/club/loan-reservations")
def list_loans():
    actor(["ClubOfficer", "Member", "EquipmentChair"])
    items = sorted_items(DB.loans)
    member_id = request.args.get("member_id")
    telescope_id = request.args.get("telescope_id")
    status = request.args.get("status")
    if member_id is not None:
        items = [l for l in items if l["member_id"] == member_id]
    if telescope_id is not None:
        items = [l for l in items if l["telescope_id"] == telescope_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    return list_response(items, lambda l: views.loan_view(DB, l))


@equip_bp.post("/club/loan-reservations/<loan_id>/checkout")
def checkout_loan(loan_id):
    actor(["EquipmentChair"])
    l = _get_or_404(DB.loans, loan_id)
    if l["status"] != "RESERVED":
        raise ApiError(409, "ERR_INVALID_STATE", "Only a RESERVED loan may be checked out")
    if not (DB.clock >= l["window_start"] and DB.clock < l["window_end"]):
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Logical clock is outside the loan window")
    member = DB.members[l["member_id"]]
    if member["status"] != "ACTIVE":
        raise ApiError(422, "ERR_MEMBER_NOT_IN_GOOD_STANDING",
                       "Member is not ACTIVE")
    tele = DB.telescopes[l["telescope_id"]]
    if tele["status"] != "RESERVED":
        raise ApiError(409, "ERR_INVALID_STATE", "Telescope is not RESERVED")
    l["status"] = "CHECKED_OUT"
    l["checkout_at"] = DB.clock
    D.stamp(DB, l)
    tele["status"] = "ON_LOAN"
    D.stamp(DB, tele)
    return success(views.loan_view(DB, l), 200)


@equip_bp.post("/club/loan-reservations/<loan_id>/return")
def return_loan(loan_id):
    actor(["EquipmentChair"])
    l = _get_or_404(DB.loans, loan_id)
    data = body()
    damage = data.get("damage_reported", False)
    if not isinstance(damage, bool):
        raise ApiError(400, "ERR_INVALID_REQUEST", "damage_reported must be a boolean")
    if l["status"] not in ("CHECKED_OUT", "OVERDUE"):
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Only a CHECKED_OUT or OVERDUE loan may be returned")
    if l["status"] == "OVERDUE":
        # Final variant: computed against returned_at, capped, persisted.
        l["overdue_fees_cents"] = min(D.overdue_fee_cents(l, DB.clock), D.FEE_CAP_CENTS)
    l["status"] = "RETURNED"
    l["returned_at"] = DB.clock
    D.stamp(DB, l)
    tele = DB.telescopes[l["telescope_id"]]
    if damage:
        tele["status"] = "MAINTENANCE"
        D.stamp(DB, tele)
        tk = D.mint(DB)
        tk.update({
            "telescope_id": tele["id"],
            "kind": "REPAIR",
            "severity": "MEDIUM",
            "status": "OPEN",
            "opened_at": DB.clock,
            "closed_at": None,
            "condition_delta": 0,
        })
        DB.tickets[tk["id"]] = tk
    else:
        tele["status"] = "AVAILABLE"
        D.stamp(DB, tele)
    return success(views.loan_view(DB, l), 200)


@equip_bp.post("/club/loan-reservations/<loan_id>/cancel")
def cancel_loan(loan_id):
    uid, role = actor(["Member", "EquipmentChair"])
    l = _get_or_404(DB.loans, loan_id)
    if role == "Member" and l["member_id"] != uid:
        raise ApiError(403, "ERR_FORBIDDEN",
                       "A Member may only cancel its own loans")
    if l["status"] != "RESERVED":
        raise ApiError(409, "ERR_INVALID_STATE", "Only a RESERVED loan may be cancelled")
    D.cancel_loan(DB, l)
    return success(views.loan_view(DB, l), 200)

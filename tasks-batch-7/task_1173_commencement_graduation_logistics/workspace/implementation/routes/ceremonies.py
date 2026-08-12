"""Ceremony lifecycle routes."""
from flask import request

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_CEREMONY_POSTURE_FORBIDS,
    ERR_RAIN_VENUE_MISSING,
    ERR_ACCESSIBLE_CAPACITY_EXCEEDED,
)
from middleware import get_caller, require_role, get_json_body
from response import success, success_list, parse_pagination, paginate
from services.common import (
    get_ceremony_or_404,
    get_venue_or_404,
    require_body_fields,
    require_string,
    require_int,
    require_number,
    is_number,
    is_int,
    occ_check,
    ELIGIBLE_FAMILY,
)
from services.honor import recompute_honor, HONOR_RANK
from services.pools import (
    recompute_ceremony_pools,
    run_waterfall_final,
    run_promotion_scan,
    effective_venue,
)
from services.serialize import (
    ceremony_out,
    graduate_out,
    allocation_out,
    seat_out,
    accommodation_out,
    vendor_out,
    batch_out,
    session_out,
)


def _row_desc_key(row_label):
    """Key component so higher row labels sort first. Numeric labels: numeric DESC; else lexicographic DESC."""
    try:
        return (0, -int(row_label), "")
    except (TypeError, ValueError):
        # invert string: map chars so reverse lexicographic works with ascending sort
        inv = "".join(chr(0x10FFFF - ord(ch)) for ch in str(row_label))
        return (1, 0, inv)


def _str_desc(s):
    return "".join(chr(0x10FFFF - ord(ch)) for ch in str(s))


def register(bp):
    @bp.route("/ceremonies", methods=["POST"])
    def create_ceremony():
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair"])
        body = get_json_body()
        require_body_fields(body, [
            "name", "ceremony_date", "venue_id", "ticket_ratio",
            "guest_ticket_base_cap", "honor_bonus_tickets",
            "pronunciation_deadline", "ticket_request_deadline", "regalia_order_deadline",
        ])
        require_string(body, "name")
        require_string(body, "ceremony_date")
        require_string(body, "venue_id")
        require_number(body, "ticket_ratio")
        if body["ticket_ratio"] <= 0:
            raise_err(ERR_INVALID_REQUEST, "ticket_ratio must be > 0")
        require_int(body, "guest_ticket_base_cap", 0)
        require_int(body, "honor_bonus_tickets", 0)
        for f in ("pronunciation_deadline", "ticket_request_deadline", "regalia_order_deadline"):
            require_string(body, f)
        get_venue_or_404(body["venue_id"])
        rain_venue_id = body.get("rain_venue_id")
        if rain_venue_id is not None:
            if not isinstance(rain_venue_id, str):
                raise_err(ERR_INVALID_REQUEST, "rain_venue_id must be a string")
            get_venue_or_404(rain_venue_id)
        rehearsal_required = body.get("rehearsal_required", True)
        if not isinstance(rehearsal_required, bool):
            raise_err(ERR_INVALID_REQUEST, "rehearsal_required must be a boolean")

        now = db.now_iso()
        cid = db.new_id()
        ceremony = {
            "id": cid,
            "name": body["name"],
            "ceremony_date": body["ceremony_date"],
            "venue_id": body["venue_id"],
            "rain_venue_id": rain_venue_id,
            "readiness_posture": "PLANNING",
            "weather_mode": "FAIR",
            "ticket_ratio": body["ticket_ratio"],
            "guest_ticket_base_cap": body["guest_ticket_base_cap"],
            "honor_bonus_tickets": body["honor_bonus_tickets"],
            "rehearsal_required": rehearsal_required,
            "pronunciation_deadline": body["pronunciation_deadline"],
            "ticket_request_deadline": body["ticket_request_deadline"],
            "regalia_order_deadline": body["regalia_order_deadline"],
            "effective_capacity": 0,
            "ticket_pool_total": 0,
            "ticket_pool_remaining": 0,
            "open_seat_count": 0,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.ceremonies[cid] = ceremony
        recompute_ceremony_pools(ceremony)
        return success(ceremony_out(ceremony), status=201)

    @bp.route("/ceremonies/<cid>", methods=["GET"])
    def get_ceremony(cid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator", "Graduate", "Vendor"])
        c = get_ceremony_or_404(cid)
        return success(ceremony_out(c))

    @bp.route("/ceremonies/<cid>", methods=["PATCH"])
    def patch_ceremony(cid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair"])
        c = get_ceremony_or_404(cid)
        body = get_json_body()
        occ_check(c, body.get("expected_ceremony_version"))

        if "name" in body and body["name"] is not None:
            if not isinstance(body["name"], str):
                raise_err(ERR_INVALID_REQUEST, "name must be a string")
            c["name"] = body["name"]
        if "ticket_ratio" in body and body["ticket_ratio"] is not None:
            if not is_number(body["ticket_ratio"]) or body["ticket_ratio"] <= 0:
                raise_err(ERR_INVALID_REQUEST, "ticket_ratio must be > 0")
            c["ticket_ratio"] = body["ticket_ratio"]
        if "guest_ticket_base_cap" in body and body["guest_ticket_base_cap"] is not None:
            if not is_int(body["guest_ticket_base_cap"]) or body["guest_ticket_base_cap"] < 0:
                raise_err(ERR_INVALID_REQUEST, "guest_ticket_base_cap must be >= 0")
            c["guest_ticket_base_cap"] = body["guest_ticket_base_cap"]
        if "honor_bonus_tickets" in body and body["honor_bonus_tickets"] is not None:
            if not is_int(body["honor_bonus_tickets"]) or body["honor_bonus_tickets"] < 0:
                raise_err(ERR_INVALID_REQUEST, "honor_bonus_tickets must be >= 0")
            c["honor_bonus_tickets"] = body["honor_bonus_tickets"]
        for f in ("pronunciation_deadline", "ticket_request_deadline", "regalia_order_deadline"):
            if f in body and body[f] is not None:
                if not isinstance(body[f], str):
                    raise_err(ERR_INVALID_REQUEST, f"{f} must be a string")
                c[f] = body[f]
        if "rain_venue_id" in body:
            rv = body["rain_venue_id"]
            if rv is not None:
                if not isinstance(rv, str):
                    raise_err(ERR_INVALID_REQUEST, "rain_venue_id must be a string")
                get_venue_or_404(rv)
            c["rain_venue_id"] = rv

        c["version"] += 1
        recompute_ceremony_pools(c)
        db.touch(c)
        return success(ceremony_out(c))

    @bp.route("/ceremonies/<cid>/open-audit", methods=["POST"])
    def open_audit(cid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair"])
        c = get_ceremony_or_404(cid)
        if c["readiness_posture"] != "PLANNING":
            raise_err(ERR_INVALID_STATE, "Ceremony is not PLANNING")
        c["readiness_posture"] = "AUDIT_OPEN"
        c["version"] += 1
        db.touch(c)
        return success(ceremony_out(c))

    @bp.route("/ceremonies/<cid>/lock-audit", methods=["POST"])
    def lock_audit(cid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair"])
        c = get_ceremony_or_404(cid)
        if c["readiness_posture"] != "AUDIT_OPEN":
            raise_err(ERR_INVALID_STATE, "Ceremony is not AUDIT_OPEN")
        for g in db.graduates.values():
            if g["ceremony_id"] == cid and g["status"] in ELIGIBLE_FAMILY:
                recompute_honor(g, "INSTITUTIONAL")
                g["version"] += 1
                db.touch(g)
        c["readiness_posture"] = "AUDIT_LOCKED"
        c["version"] += 1
        db.touch(c)
        return success(ceremony_out(c))

    @bp.route("/ceremonies/<cid>/reopen-audit", methods=["POST"])
    def reopen_audit(cid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair"])
        c = get_ceremony_or_404(cid)
        if c["readiness_posture"] != "AUDIT_LOCKED":
            raise_err(ERR_INVALID_STATE, "Ceremony is not AUDIT_LOCKED")
        for b in db.print_batches.values():
            if b["ceremony_id"] == cid and b["status"] in {"RELEASED", "PRINTED"}:
                raise_err(ERR_INVALID_STATE, "A print batch is already RELEASED or PRINTED")
        for g in db.graduates.values():
            if g["ceremony_id"] == cid and g["status"] in ELIGIBLE_FAMILY:
                recompute_honor(g, "COMBINED")
                g["version"] += 1
                db.touch(g)
        c["readiness_posture"] = "AUDIT_OPEN"
        c["version"] += 1
        db.touch(c)
        return success(ceremony_out(c))

    @bp.route("/ceremonies/<cid>/mark-ready", methods=["POST"])
    def mark_ready(cid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair"])
        c = get_ceremony_or_404(cid)
        if c["readiness_posture"] != "AUDIT_LOCKED":
            raise_err(ERR_INVALID_STATE, "Ceremony is not AUDIT_LOCKED")
        for g in db.graduates.values():
            if g["ceremony_id"] == cid and g["status"] != "WITHDRAWN":
                if g["status"] in {"PENDING_AUDIT", "APPEALING"}:
                    raise_err(ERR_CEREMONY_POSTURE_FORBIDS, "Outstanding audits or appeals remain")
                if g["status"] in ELIGIBLE_FAMILY:
                    card = next(
                        (r for r in db.reader_cards.values()
                         if r["graduate_id"] == g["id"] and r["status"] in {"SUBMITTED", "APPROVED"}),
                        None,
                    )
                    if card is None:
                        raise_err(ERR_CEREMONY_POSTURE_FORBIDS, "Eligible graduate lacks a reader card")
        for r in db.reader_cards.values():
            g = db.graduates.get(r["graduate_id"])
            if g and g["ceremony_id"] == cid and r["status"] in {"SUBMITTED", "APPROVED"}:
                r["status"] = "LOCKED"
                r["version"] += 1
                db.touch(r)
        c["readiness_posture"] = "READY"
        c["version"] += 1
        db.touch(c)
        return success(ceremony_out(c))

    @bp.route("/ceremonies/<cid>/activate-rain-plan", methods=["POST"])
    def activate_rain_plan(cid):
        user_id, role = get_caller()
        require_role(role, ["VenueCoordinator"])
        c = get_ceremony_or_404(cid)
        if c["weather_mode"] != "FAIR":
            raise_err(ERR_INVALID_STATE, "Weather mode is not FAIR")
        if c["readiness_posture"] not in {"AUDIT_LOCKED", "READY"}:
            raise_err(ERR_CEREMONY_POSTURE_FORBIDS, "Posture forbids rain-plan activation")
        # per §2.11 order: accessible-pool check (priority 19) before rain-venue check (priority 25)
        rain_venue = db.venues.get(c["rain_venue_id"]) if c.get("rain_venue_id") else None
        reserved = sum(
            1 for r in db.accommodation_requests.values()
            if r["ceremony_id"] == cid
            and r["request_type"] == "WHEELCHAIR_SEAT"
            and r["status"] in {"APPROVED", "FULFILLED"}
        )
        if rain_venue is not None and reserved > rain_venue["accessible_capacity"]:
            raise_err(ERR_ACCESSIBLE_CAPACITY_EXCEEDED, "Reserved accessible seats exceed rain venue accessible capacity")
        if c.get("rain_venue_id") is None or rain_venue is None:
            raise_err(ERR_RAIN_VENUE_MISSING, "No rain venue designated")

        c["weather_mode"] = "RAIN_PLAN_ACTIVE"
        recompute_ceremony_pools(c)
        # seat eviction cascade while ASSIGNED > effective_capacity
        while True:
            assigned = [
                s for s in db.seat_assignments.values()
                if s["ceremony_id"] == cid and s["status"] == "ASSIGNED"
            ]
            if len(assigned) <= c["effective_capacity"]:
                break
            # selector: accessible ASC first (non-accessible first), row_label DESC,
            # seat_number DESC, created_at DESC
            assigned.sort(key=lambda s: (
                1 if s["accessible"] else 0,
                _row_desc_key(s["row_label"]),
                -s["seat_number"],
                _str_desc(s["created_at"]),
            ))
            victim = assigned[0]
            victim["status"] = "EVICTED"
            victim["evicted_reason"] = "RAIN_SHRINK"
            victim["version"] += 1
            db.touch(victim)
            recompute_ceremony_pools(c)
        # FINAL waterfall re-run
        run_waterfall_final(c)
        recompute_ceremony_pools(c)
        c["version"] += 1
        db.touch(c)
        return success(ceremony_out(c))

    @bp.route("/ceremonies/<cid>/deactivate-rain-plan", methods=["POST"])
    def deactivate_rain_plan(cid):
        user_id, role = get_caller()
        require_role(role, ["VenueCoordinator"])
        c = get_ceremony_or_404(cid)
        if c["weather_mode"] != "RAIN_PLAN_ACTIVE":
            raise_err(ERR_INVALID_STATE, "Weather mode is not RAIN_PLAN_ACTIVE")
        if c["readiness_posture"] not in {"AUDIT_LOCKED", "READY"}:
            raise_err(ERR_CEREMONY_POSTURE_FORBIDS, "Posture forbids rain-plan deactivation")
        c["weather_mode"] = "FAIR"
        recompute_ceremony_pools(c)
        # FINAL waterfall re-run + promotion scan (pool grew)
        run_waterfall_final(c)
        run_promotion_scan(c)
        recompute_ceremony_pools(c)
        c["version"] += 1
        db.touch(c)
        return success(ceremony_out(c))

    @bp.route("/ceremonies/<cid>/commence", methods=["POST"])
    def commence(cid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair"])
        c = get_ceremony_or_404(cid)
        if c["readiness_posture"] != "READY":
            raise_err(ERR_INVALID_STATE, "Ceremony is not READY")
        c["readiness_posture"] = "COMMENCED"
        c["version"] += 1
        db.touch(c)
        return success(ceremony_out(c))

    @bp.route("/ceremonies/<cid>/complete", methods=["POST"])
    def complete(cid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair"])
        c = get_ceremony_or_404(cid)
        if c["readiness_posture"] != "COMMENCED":
            raise_err(ERR_INVALID_STATE, "Ceremony is not COMMENCED")
        for a in db.ticket_allocations.values():
            if a["ceremony_id"] == cid and a["status"] in {"PENDING", "WAITLISTED"}:
                a["status"] = "EXPIRED"
                a["granted_count"] = 0
                a["waitlist_position"] = None
                a["version"] += 1
                db.touch(a)
        c["readiness_posture"] = "COMPLETED"
        recompute_ceremony_pools(c)
        c["version"] += 1
        db.touch(c)
        return success(ceremony_out(c))

    @bp.route("/ceremonies/<cid>/run-ticket-waterfall", methods=["POST"])
    def run_ticket_waterfall(cid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair"])
        c = get_ceremony_or_404(cid)
        processed, granted_total, waitlisted = run_waterfall_final(c)
        recompute_ceremony_pools(c)
        return success({
            "processed_count": processed,
            "granted_total": granted_total,
            "waitlisted_count": waitlisted,
            "pool_remaining": c["ticket_pool_remaining"],
        })

    @bp.route("/ceremonies/<cid>/run-seating", methods=["POST"])
    def run_seating(cid):
        user_id, role = get_caller()
        require_role(role, ["VenueCoordinator"])
        c = get_ceremony_or_404(cid)
        venue = effective_venue(c)
        if venue is None:
            raise_err(ERR_INVALID_STATE, "Ceremony has no effective venue")

        candidates = [
            g for g in db.graduates.values()
            if g["ceremony_id"] == cid and g["status"] in ELIGIBLE_FAMILY
            and not any(
                s for s in db.seat_assignments.values()
                if s["ceremony_id"] == cid and s["graduate_id"] == g["id"] and s["status"] == "ASSIGNED"
            )
        ]
        candidates.sort(key=lambda g: (-HONOR_RANK.get(g["honor_tier"], 0), g["created_at"]))

        SEATS_PER_ROW = 4
        assigned_count = 0
        skipped_count = 0
        for g in candidates:
            recompute_ceremony_pools(c)
            if c["open_seat_count"] <= 0:
                skipped_count += 1
                continue
            has_wheelchair = any(
                r for r in db.accommodation_requests.values()
                if r["graduate_id"] == g["id"] and r["ceremony_id"] == cid
                and r["request_type"] == "WHEELCHAIR_SEAT"
                and r["status"] in {"APPROVED", "FULFILLED"}
            )
            if has_wheelchair:
                accessible_assigned = sum(
                    1 for s in db.seat_assignments.values()
                    if s["ceremony_id"] == cid and s["status"] == "ASSIGNED" and s["accessible"]
                )
                if accessible_assigned >= venue["accessible_capacity"]:
                    skipped_count += 1
                    continue
            occupied = {
                (s["section"], s["row_label"], s["seat_number"])
                for s in db.seat_assignments.values()
                if s["ceremony_id"] == cid and s["status"] == "ASSIGNED"
            }
            placed = False
            row = 1
            while not placed:
                for seat_num in range(1, SEATS_PER_ROW + 1):
                    key = ("A", str(row), seat_num)
                    if key not in occupied:
                        sid = db.new_id()
                        now = db.now_iso()
                        seat = {
                            "id": sid,
                            "ceremony_id": cid,
                            "graduate_id": g["id"],
                            "section": "A",
                            "row_label": str(row),
                            "seat_number": seat_num,
                            "accessible": bool(has_wheelchair),
                            "status": "ASSIGNED",
                            "evicted_reason": None,
                            "created_at": now,
                            "updated_at": now,
                            "version": 1,
                        }
                        db.seat_assignments[sid] = seat
                        assigned_count += 1
                        placed = True
                        break
                if not placed:
                    row += 1
        recompute_ceremony_pools(c)
        return success({
            "assigned_count": assigned_count,
            "skipped_count": skipped_count,
            "open_seat_count": c["open_seat_count"],
        })

    # ------- ceremony-scoped sub-resource lists -------

    @bp.route("/ceremonies/<cid>/graduates", methods=["GET"])
    def list_ceremony_graduates(cid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator"])
        get_ceremony_or_404(cid)
        limit, offset = parse_pagination(request.args)
        items = [g for g in db.graduates.values() if g["ceremony_id"] == cid]
        status_f = request.args.get("status")
        honor_f = request.args.get("honor_tier")
        if status_f:
            items = [g for g in items if g["status"] == status_f]
        if honor_f:
            items = [g for g in items if g["honor_tier"] == honor_f]
        items.sort(key=lambda g: g["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([graduate_out(g) for g in page], limit, offset, total)

    @bp.route("/ceremonies/<cid>/ticket-allocations", methods=["GET"])
    def list_ceremony_allocations(cid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator"])
        get_ceremony_or_404(cid)
        limit, offset = parse_pagination(request.args)
        items = [a for a in db.ticket_allocations.values() if a["ceremony_id"] == cid]
        status_f = request.args.get("status")
        if status_f:
            items = [a for a in items if a["status"] == status_f]
        items.sort(key=lambda a: a["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([allocation_out(a) for a in page], limit, offset, total)

    @bp.route("/ceremonies/<cid>/seat-assignments", methods=["GET"])
    def list_ceremony_seats(cid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator"])
        get_ceremony_or_404(cid)
        limit, offset = parse_pagination(request.args)
        items = [s for s in db.seat_assignments.values() if s["ceremony_id"] == cid]
        status_f = request.args.get("status")
        if status_f:
            items = [s for s in items if s["status"] == status_f]
        items.sort(key=lambda s: s["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([seat_out(s) for s in page], limit, offset, total)

    @bp.route("/ceremonies/<cid>/accommodation-requests", methods=["GET"])
    def list_ceremony_accommodations(cid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator"])
        get_ceremony_or_404(cid)
        limit, offset = parse_pagination(request.args)
        items = [r for r in db.accommodation_requests.values() if r["ceremony_id"] == cid]
        status_f = request.args.get("status")
        type_f = request.args.get("request_type")
        if status_f:
            items = [r for r in items if r["status"] == status_f]
        if type_f:
            items = [r for r in items if r["request_type"] == type_f]
        items.sort(key=lambda r: r["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([accommodation_out(r) for r in page], limit, offset, total)

    @bp.route("/ceremonies/<cid>/vendor-contracts", methods=["GET"])
    def list_ceremony_vendor_contracts(cid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "VenueCoordinator"])
        get_ceremony_or_404(cid)
        limit, offset = parse_pagination(request.args)
        items = [c for c in db.vendor_contracts.values() if c["ceremony_id"] == cid]
        status_f = request.args.get("status")
        type_f = request.args.get("vendor_type")
        if status_f:
            items = [c for c in items if c["status"] == status_f]
        if type_f:
            items = [c for c in items if c["vendor_type"] == type_f]
        items.sort(key=lambda c: c["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([vendor_out(c) for c in page], limit, offset, total)

    @bp.route("/ceremonies/<cid>/print-batches", methods=["GET"])
    def list_ceremony_print_batches(cid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer"])
        get_ceremony_or_404(cid)
        limit, offset = parse_pagination(request.args)
        items = [b for b in db.print_batches.values() if b["ceremony_id"] == cid]
        status_f = request.args.get("status")
        if status_f:
            items = [b for b in items if b["status"] == status_f]
        items.sort(key=lambda b: b["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([batch_out(b) for b in page], limit, offset, total)

    @bp.route("/ceremonies/<cid>/rehearsal-sessions", methods=["GET"])
    def list_ceremony_rehearsal_sessions(cid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator", "Graduate"])
        get_ceremony_or_404(cid)
        limit, offset = parse_pagination(request.args)
        items = [s for s in db.rehearsal_sessions.values() if s["ceremony_id"] == cid]
        items.sort(key=lambda s: s["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([session_out(s) for s in page], limit, offset, total)

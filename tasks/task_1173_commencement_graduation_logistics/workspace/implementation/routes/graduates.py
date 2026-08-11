"""Graduate, eligibility audit, appeal, reader card, regalia, accommodation routes."""
from datetime import timedelta

from flask import request

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_CEREMONY_POSTURE_FORBIDS,
    ERR_GRADUATE_NOT_ELIGIBLE,
    ERR_REQUEST_WINDOW_CLOSED,
    ERR_PRONUNCIATION_DEADLINE_PASSED,
    ERR_APPEAL_WINDOW_CLOSED,
    ERR_TICKET_CAP_EXCEEDED,
    ERR_READER_CARD_EXISTS,
    ERR_PAYMENT_AMOUNT_MISMATCH,
    ERR_WALK_PRIVILEGE_REVOKED,
)
from middleware import (
    get_caller,
    require_role,
    get_json_body,
    require_graduate_ownership,
)
from response import success, success_list, parse_pagination, paginate
from services.common import (
    get_ceremony_or_404,
    get_graduate_or_404,
    get_audit_or_404,
    get_allocation_or_404,
    get_regalia_or_404,
    get_reader_card_or_404,
    get_accommodation_or_404,
    require_body_fields,
    require_string,
    require_int,
    require_number,
    require_enum,
    is_number,
    is_int,
    occ_check,
    posture_gate,
    graduate_eligible_gate,
    ELIGIBLE_FAMILY,
)
from services.honor import recompute_honor, honor_tier_combined
from services.pools import (
    recompute_ceremony_pools,
    run_promotion_scan,
    provisional_estimate,
    entitlement_for,
)
from services.pricing import price_regalia_order
from services.serialize import (
    graduate_out,
    audit_out,
    allocation_out,
    regalia_out,
    seat_out,
    diploma_out,
    accommodation_out,
    attendance_out,
    reader_card_out,
)

APPEAL_WINDOW_DAYS = 14


def _auto_touch_graduate(g):
    g["version"] += 1
    db.touch(g)


def register(bp):
    # ---------- Graduate import & reads ----------

    @bp.route("/graduates", methods=["POST"])
    def create_graduate():
        user_id, role = get_caller()
        require_role(role, ["RegistrarOfficer"])
        body = get_json_body()
        require_body_fields(body, [
            "ceremony_id", "full_name", "email",
            "institutional_gpa_credits", "institutional_quality_points",
            "credits_completed", "credits_required",
        ])
        get_ceremony_or_404(body["ceremony_id"])
        require_string(body, "full_name")
        require_string(body, "email")
        for f in ("institutional_gpa_credits", "institutional_quality_points", "credits_completed"):
            require_number(body, f, 0)
        require_number(body, "credits_required")
        if body["credits_required"] < 1:
            raise_err(ERR_INVALID_REQUEST, "credits_required must be >= 1")
        tg_credits = body.get("transfer_gpa_credits", 0)
        tg_points = body.get("transfer_quality_points", 0)
        holds = body.get("outstanding_hold_count", 0)
        for f, v in (("transfer_gpa_credits", tg_credits), ("transfer_quality_points", tg_points)):
            if not is_number(v) or v < 0:
                raise_err(ERR_INVALID_REQUEST, f"{f} must be a number >= 0")
        if not is_int(holds) or holds < 0:
            raise_err(ERR_INVALID_REQUEST, "outstanding_hold_count must be an integer >= 0")

        now = db.now_iso()
        gid = db.new_id()
        grad = {
            "id": gid,
            "ceremony_id": body["ceremony_id"],
            "full_name": body["full_name"],
            "email": body["email"],
            "institutional_gpa_credits": body["institutional_gpa_credits"],
            "institutional_quality_points": body["institutional_quality_points"],
            "transfer_gpa_credits": tg_credits,
            "transfer_quality_points": tg_points,
            "credits_completed": body["credits_completed"],
            "credits_required": body["credits_required"],
            "outstanding_hold_count": holds,
            "status": "PENDING_AUDIT",
            "honor_tier": "NONE",
            "honor_basis": "NONE",
            "conduct_strike_count": 0,
            "walk_privilege_revoked": False,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.graduates[gid] = grad
        # auto-create PENDING ticket allocation with requested_count 0
        aid = db.new_id()
        alloc = {
            "id": aid,
            "graduate_id": gid,
            "ceremony_id": body["ceremony_id"],
            "requested_count": 0,
            "entitlement_count": 0,
            "provisional_granted_count": 0,
            "granted_count": 0,
            "waitlist_position": None,
            "status": "PENDING",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.ticket_allocations[aid] = alloc
        return success(graduate_out(grad), status=201)

    @bp.route("/graduates/<gid>", methods=["GET"])
    def get_graduate(gid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator", "Graduate"])
        g = get_graduate_or_404(gid)
        require_graduate_ownership(user_id, role, g["id"])
        return success(graduate_out(g))

    @bp.route("/graduates/<gid>/withdraw", methods=["POST"])
    def withdraw_graduate(gid):
        user_id, role = get_caller()
        require_role(role, ["RegistrarOfficer", "Graduate"])
        g = get_graduate_or_404(gid)
        require_graduate_ownership(user_id, role, g["id"])
        if g["status"] == "WITHDRAWN":
            raise_err(ERR_INVALID_STATE, "Graduate is already WITHDRAWN")
        ceremony = get_ceremony_or_404(g["ceremony_id"])
        if ceremony["readiness_posture"] == "COMPLETED":
            raise_err(ERR_CEREMONY_POSTURE_FORBIDS, "Ceremony is COMPLETED")

        # Ticket allocation release + promotion scan
        alloc = next(
            (a for a in db.ticket_allocations.values() if a["graduate_id"] == gid),
            None,
        )
        if alloc is not None and alloc["status"] not in {"RELEASED", "EXPIRED"}:
            alloc["status"] = "RELEASED"
            alloc["granted_count"] = 0
            alloc["waitlist_position"] = None
            alloc["version"] += 1
            db.touch(alloc)
            recompute_ceremony_pools(ceremony)
            run_promotion_scan(ceremony)
            recompute_ceremony_pools(ceremony)
        # Seat eviction
        for s in db.seat_assignments.values():
            if s["graduate_id"] == gid and s["ceremony_id"] == ceremony["id"] and s["status"] == "ASSIGNED":
                s["status"] = "EVICTED"
                s["evicted_reason"] = "WITHDRAWN"
                s["version"] += 1
                db.touch(s)
        recompute_ceremony_pools(ceremony)
        # Regalia cancel SUBMITTED
        for o in db.regalia_orders.values():
            if o["graduate_id"] == gid and o["status"] == "SUBMITTED":
                o["status"] = "CANCELLED"
                o["version"] += 1
                db.touch(o)
        # Rehearsal REGISTERED -> CANCELLED
        for a in db.rehearsal_attendances.values():
            if a["graduate_id"] == gid and a["status"] == "REGISTERED":
                a["status"] = "CANCELLED"
                a["version"] += 1
                db.touch(a)
        # Diploma QUEUED|REPRINT_QUEUED -> ARCHIVED
        for d in db.diplomas.values():
            if d["graduate_id"] == gid and d["status"] in {"QUEUED", "REPRINT_QUEUED"}:
                d["status"] = "ARCHIVED"
                d["version"] += 1
                db.touch(d)

        g["status"] = "WITHDRAWN"
        _auto_touch_graduate(g)
        return success(graduate_out(g))

    @bp.route("/graduates/<gid>/confirm", methods=["POST"])
    def confirm_graduate(gid):
        user_id, role = get_caller()
        require_role(role, ["Graduate"])
        g = get_graduate_or_404(gid)
        require_graduate_ownership(user_id, role, g["id"])
        ceremony = get_ceremony_or_404(g["ceremony_id"])
        if ceremony["readiness_posture"] == "COMPLETED":
            raise_err(ERR_CEREMONY_POSTURE_FORBIDS, "Ceremony is COMPLETED")
        if g["status"] not in {"ELIGIBLE", "ELIGIBLE_ON_APPEAL"}:
            raise_err(ERR_INVALID_STATE, "Graduate cannot confirm from current status")
        g["status"] = "CONFIRMED"
        _auto_touch_graduate(g)
        return success(graduate_out(g))

    @bp.route("/graduates/<gid>/grade-revision", methods=["POST"])
    def grade_revision(gid):
        user_id, role = get_caller()
        require_role(role, ["RegistrarOfficer"])
        g = get_graduate_or_404(gid)
        ceremony = get_ceremony_or_404(g["ceremony_id"])
        body = get_json_body()
        posture_gate(ceremony, {"AUDIT_LOCKED"})
        for f in ("institutional_gpa_credits", "institutional_quality_points",
                  "transfer_gpa_credits", "transfer_quality_points"):
            if f in body and body[f] is not None:
                if not is_number(body[f]) or body[f] < 0:
                    raise_err(ERR_INVALID_REQUEST, f"{f} must be a number >= 0")
                g[f] = body[f]
        if g["status"] in ELIGIBLE_FAMILY:
            recompute_honor(g, "INSTITUTIONAL")
        _auto_touch_graduate(g)
        return success(graduate_out(g))

    # ---------- Eligibility audits & appeals ----------

    @bp.route("/graduates/<gid>/audits", methods=["POST"])
    def run_audit(gid):
        user_id, role = get_caller()
        require_role(role, ["RegistrarOfficer"])
        g = get_graduate_or_404(gid)
        body = get_json_body(required=False)
        ceremony = get_ceremony_or_404(g["ceremony_id"])
        if g["status"] != "PENDING_AUDIT":
            raise_err(ERR_INVALID_STATE, "Graduate is not PENDING_AUDIT")
        posture_gate(ceremony, {"AUDIT_OPEN"})

        fail_reasons = []
        if g["credits_completed"] < g["credits_required"]:
            fail_reasons.append("INSUFFICIENT_CREDITS")
        if g["outstanding_hold_count"] != 0:
            fail_reasons.append("OUTSTANDING_HOLD")
        if g["institutional_gpa_credits"] <= 0:
            fail_reasons.append("NO_INSTITUTIONAL_CREDITS")
        result = "PASS" if not fail_reasons else "FAIL"

        provisional_tier = "NONE"
        if result == "PASS":
            provisional_tier = honor_tier_combined(g)
            g["status"] = "ELIGIBLE"
            g["honor_tier"] = provisional_tier
            g["honor_basis"] = "COMBINED"
        else:
            g["status"] = "INELIGIBLE"

        now = db.now_iso()
        aid = db.new_id()
        audit = {
            "id": aid,
            "graduate_id": gid,
            "result": result,
            "fail_reasons": fail_reasons,
            "provisional_honor_tier": provisional_tier,
            "appeal_status": "NONE",
            "audited_by_user_id": user_id,
            "decided_by_user_id": None,
            "notes": body.get("notes", "") if isinstance(body.get("notes", ""), str) else "",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.eligibility_audits[aid] = audit
        _auto_touch_graduate(g)
        return success(audit_out(audit), status=201)

    @bp.route("/graduates/<gid>/audits", methods=["GET"])
    def list_graduate_audits(gid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator", "Graduate"])
        g = get_graduate_or_404(gid)
        require_graduate_ownership(user_id, role, g["id"])
        limit, offset = parse_pagination(request.args)
        items = [a for a in db.eligibility_audits.values() if a["graduate_id"] == gid]
        items.sort(key=lambda a: a["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([audit_out(a) for a in page], limit, offset, total)

    @bp.route("/eligibility-audits/<aid>/appeal", methods=["POST"])
    def appeal_audit(aid):
        user_id, role = get_caller()
        require_role(role, ["Graduate"])
        audit = get_audit_or_404(aid)
        g = get_graduate_or_404(audit["graduate_id"])
        require_graduate_ownership(user_id, role, g["id"])
        # latest audit check
        audits_for_g = [a for a in db.eligibility_audits.values() if a["graduate_id"] == g["id"]]
        latest_audit = max(audits_for_g, key=lambda a: a["created_at"]) if audits_for_g else None
        if g["status"] != "INELIGIBLE" or latest_audit is None or latest_audit["id"] != audit["id"]:
            raise_err(ERR_INVALID_STATE, "Only the latest FAIL audit of an INELIGIBLE graduate can be appealed")
        now = db.now_dt()
        if now > db.parse_dt(audit["created_at"]) + timedelta(days=APPEAL_WINDOW_DAYS):
            raise_err(ERR_APPEAL_WINDOW_CLOSED, "Appeal window closed")
        if audit["appeal_status"] != "NONE":
            raise_err(ERR_INVALID_STATE, "Audit already has an appeal")
        audit["appeal_status"] = "SUBMITTED"
        audit["version"] += 1
        db.touch(audit)
        g["status"] = "APPEALING"
        _auto_touch_graduate(g)
        return success(audit_out(audit))

    @bp.route("/eligibility-audits/<aid>/appeal-decision", methods=["POST"])
    def appeal_decision(aid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair"])
        audit = get_audit_or_404(aid)
        g = get_graduate_or_404(audit["graduate_id"])
        body = get_json_body()
        require_enum(body, "decision", {"APPROVED", "DENIED"})
        if g["status"] != "APPEALING" or audit["appeal_status"] != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, "No submitted appeal to decide")
        if body["decision"] == "APPROVED":
            audit["appeal_status"] = "APPROVED"
            audit["decided_by_user_id"] = user_id
            g["status"] = "ELIGIBLE_ON_APPEAL"
            recompute_honor(g, "COMBINED")
        else:
            audit["appeal_status"] = "DENIED"
            audit["decided_by_user_id"] = user_id
            g["status"] = "INELIGIBLE"
        audit["version"] += 1
        db.touch(audit)
        _auto_touch_graduate(g)
        return success(audit_out(audit))

    # ---------- Ticket allocation requests ----------

    @bp.route("/ticket-allocations/<aid>/request", methods=["POST"])
    def request_tickets(aid):
        user_id, role = get_caller()
        require_role(role, ["Graduate"])
        alloc = get_allocation_or_404(aid)
        g = get_graduate_or_404(alloc["graduate_id"])
        require_graduate_ownership(user_id, role, g["id"])
        body = get_json_body()
        # schema (priority 4) before OCC/state gates
        if "requested_count" not in body or not is_int(body["requested_count"]):
            raise_err(ERR_INVALID_REQUEST, "requested_count must be an integer")
        if body["requested_count"] < 1:
            raise_err(ERR_INVALID_REQUEST, "requested_count must be >= 1")
        occ_check(alloc, body.get("expected_ticket_allocation_version"))
        if alloc["status"] not in {"PENDING", "ALLOCATED", "PARTIAL", "WAITLISTED"}:
            raise_err(ERR_INVALID_STATE, "Allocation cannot accept a new request from its current status")
        ceremony = get_ceremony_or_404(alloc["ceremony_id"])
        posture_gate(ceremony, {"AUDIT_OPEN"})
        graduate_eligible_gate(g)
        if db.now_dt() > db.parse_dt(ceremony["ticket_request_deadline"]):
            raise_err(ERR_REQUEST_WINDOW_CLOSED, "Ticket request window closed")
        entitlement = entitlement_for(ceremony, g)
        if body["requested_count"] > entitlement:
            raise_err(ERR_TICKET_CAP_EXCEEDED, "Requested count exceeds entitlement")

        alloc["requested_count"] = body["requested_count"]
        alloc["provisional_granted_count"] = provisional_estimate(ceremony, g, body["requested_count"])
        alloc["version"] += 1
        db.touch(alloc)
        return success(allocation_out(alloc))

    @bp.route("/ticket-allocations/<aid>/release", methods=["POST"])
    def release_tickets(aid):
        user_id, role = get_caller()
        require_role(role, ["Graduate"])
        alloc = get_allocation_or_404(aid)
        g = get_graduate_or_404(alloc["graduate_id"])
        require_graduate_ownership(user_id, role, g["id"])
        if alloc["status"] not in {"PENDING", "ALLOCATED", "PARTIAL", "WAITLISTED"}:
            raise_err(ERR_INVALID_STATE, "Allocation cannot be released from its current status")
        ceremony = get_ceremony_or_404(alloc["ceremony_id"])
        alloc["status"] = "RELEASED"
        alloc["granted_count"] = 0
        alloc["waitlist_position"] = None
        alloc["version"] += 1
        db.touch(alloc)
        recompute_ceremony_pools(ceremony)
        run_promotion_scan(ceremony)
        recompute_ceremony_pools(ceremony)
        return success(allocation_out(alloc))

    # ---------- Regalia ----------

    @bp.route("/graduates/<gid>/regalia-orders", methods=["POST"])
    def create_regalia_order(gid):
        user_id, role = get_caller()
        require_role(role, ["Graduate"])
        g = get_graduate_or_404(gid)
        require_graduate_ownership(user_id, role, g["id"])
        body = get_json_body()
        if "items" not in body or not isinstance(body["items"], list) or len(body["items"]) == 0:
            raise_err(ERR_INVALID_REQUEST, "items must be a non-empty array")
        for line in body["items"]:
            if not isinstance(line, dict):
                raise_err(ERR_INVALID_REQUEST, "each item must be an object")
            for f in ("item_type", "size", "quantity", "unit_price_cents"):
                if f not in line:
                    raise_err(ERR_INVALID_REQUEST, f"item missing field {f}")
            if not isinstance(line["item_type"], str) or not isinstance(line["size"], str):
                raise_err(ERR_INVALID_REQUEST, "item_type and size must be strings")
            if not is_int(line["quantity"]) or line["quantity"] < 1:
                raise_err(ERR_INVALID_REQUEST, "quantity must be an integer >= 1")
            if not is_int(line["unit_price_cents"]) or line["unit_price_cents"] < 0:
                raise_err(ERR_INVALID_REQUEST, "unit_price_cents must be an integer >= 0")
        ceremony = get_ceremony_or_404(g["ceremony_id"])
        subtotal, discount, late_fee, total = price_regalia_order(body["items"], ceremony)
        now = db.now_iso()
        oid = db.new_id()
        order = {
            "id": oid,
            "graduate_id": gid,
            "items": body["items"],
            "subtotal_cents": subtotal,
            "discount_cents": discount,
            "late_fee_cents": late_fee,
            "total_cents": total,
            "status": "SUBMITTED",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.regalia_orders[oid] = order
        return success(regalia_out(order), status=201)

    @bp.route("/regalia-orders/<oid>", methods=["GET"])
    def get_regalia_order(oid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator", "Graduate"])
        o = get_regalia_or_404(oid)
        require_graduate_ownership(user_id, role, o["graduate_id"])
        return success(regalia_out(o))

    @bp.route("/regalia-orders/<oid>/pay", methods=["POST"])
    def pay_regalia_order(oid):
        user_id, role = get_caller()
        require_role(role, ["Graduate"])
        o = get_regalia_or_404(oid)
        require_graduate_ownership(user_id, role, o["graduate_id"])
        body = get_json_body()
        if "amount_cents" not in body or not is_int(body["amount_cents"]) or body["amount_cents"] < 0:
            raise_err(ERR_INVALID_REQUEST, "amount_cents must be an integer >= 0")
        if o["status"] != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, "Order is not SUBMITTED")
        if body["amount_cents"] != o["total_cents"]:
            raise_err(ERR_PAYMENT_AMOUNT_MISMATCH, "Payment amount does not match total")
        o["status"] = "PAID"
        o["version"] += 1
        db.touch(o)
        return success(regalia_out(o))

    @bp.route("/regalia-orders/<oid>/fulfill", methods=["POST"])
    def fulfill_regalia_order(oid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair"])
        o = get_regalia_or_404(oid)
        g = get_graduate_or_404(o["graduate_id"])
        if o["status"] not in {"PAID", "EXCHANGE_REQUESTED"}:
            raise_err(ERR_INVALID_STATE, "Order is not PAID or EXCHANGE_REQUESTED")
        if g["walk_privilege_revoked"]:
            raise_err(ERR_WALK_PRIVILEGE_REVOKED, "Graduate walk privilege revoked")
        o["status"] = "FULFILLED"
        o["version"] += 1
        db.touch(o)
        return success(regalia_out(o))

    @bp.route("/regalia-orders/<oid>/request-exchange", methods=["POST"])
    def request_exchange(oid):
        user_id, role = get_caller()
        require_role(role, ["Graduate"])
        o = get_regalia_or_404(oid)
        require_graduate_ownership(user_id, role, o["graduate_id"])
        if o["status"] != "FULFILLED":
            raise_err(ERR_INVALID_STATE, "Order is not FULFILLED")
        o["status"] = "EXCHANGE_REQUESTED"
        o["version"] += 1
        db.touch(o)
        return success(regalia_out(o))

    @bp.route("/regalia-orders/<oid>/cancel", methods=["POST"])
    def cancel_regalia_order(oid):
        user_id, role = get_caller()
        require_role(role, ["Graduate"])
        o = get_regalia_or_404(oid)
        require_graduate_ownership(user_id, role, o["graduate_id"])
        if o["status"] != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, "Only SUBMITTED orders can be cancelled")
        o["status"] = "CANCELLED"
        o["version"] += 1
        db.touch(o)
        return success(regalia_out(o))

    # ---------- Reader cards ----------

    @bp.route("/graduates/<gid>/reader-card", methods=["POST"])
    def create_reader_card(gid):
        user_id, role = get_caller()
        require_role(role, ["Graduate"])
        g = get_graduate_or_404(gid)
        require_graduate_ownership(user_id, role, g["id"])
        body = get_json_body()
        require_string(body, "phonetic_spelling")
        ceremony = get_ceremony_or_404(g["ceremony_id"])
        graduate_eligible_gate(g)
        if db.now_dt() > db.parse_dt(ceremony["pronunciation_deadline"]):
            raise_err(ERR_PRONUNCIATION_DEADLINE_PASSED, "Pronunciation deadline passed")
        existing = next((r for r in db.reader_cards.values() if r["graduate_id"] == gid), None)
        if existing is not None:
            raise_err(ERR_READER_CARD_EXISTS, "Graduate already has a reader card")
        now = db.now_iso()
        rid = db.new_id()
        card = {
            "id": rid,
            "graduate_id": gid,
            "phonetic_spelling": body["phonetic_spelling"],
            "status": "SUBMITTED",
            "approved_by_user_id": None,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.reader_cards[rid] = card
        return success(reader_card_out(card), status=201)

    @bp.route("/reader-cards/<rid>", methods=["PATCH"])
    def patch_reader_card(rid):
        user_id, role = get_caller()
        require_role(role, ["Graduate"])
        card = get_reader_card_or_404(rid)
        require_graduate_ownership(user_id, role, card["graduate_id"])
        body = get_json_body()
        require_string(body, "phonetic_spelling")
        if card["status"] != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, "Card is not SUBMITTED")
        card["phonetic_spelling"] = body["phonetic_spelling"]
        card["version"] += 1
        db.touch(card)
        return success(reader_card_out(card))

    @bp.route("/reader-cards/<rid>/approve", methods=["POST"])
    def approve_reader_card(rid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair"])
        card = get_reader_card_or_404(rid)
        if card["status"] != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, "Card is not SUBMITTED")
        card["status"] = "APPROVED"
        card["approved_by_user_id"] = user_id
        card["version"] += 1
        db.touch(card)
        return success(reader_card_out(card))

    # ---------- Accommodation requests ----------

    @bp.route("/graduates/<gid>/accommodation-requests", methods=["POST"])
    def create_accommodation(gid):
        user_id, role = get_caller()
        require_role(role, ["Graduate"])
        g = get_graduate_or_404(gid)
        require_graduate_ownership(user_id, role, g["id"])
        body = get_json_body()
        require_body_fields(body, ["ceremony_id", "request_type"])
        get_ceremony_or_404(body["ceremony_id"])
        require_enum(body, "request_type",
                     {"WHEELCHAIR_SEAT", "SIGN_INTERPRETER", "ASSISTIVE_LISTENING", "SERVICE_ANIMAL"})
        notes = body.get("notes", "")
        if notes is not None and not isinstance(notes, str):
            raise_err(ERR_INVALID_REQUEST, "notes must be a string")
        now = db.now_iso()
        rid = db.new_id()
        req = {
            "id": rid,
            "graduate_id": gid,
            "ceremony_id": body["ceremony_id"],
            "request_type": body["request_type"],
            "notes": notes or "",
            "status": "SUBMITTED",
            "approved_by_user_id": None,
            "fulfilled_by_user_id": None,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.accommodation_requests[rid] = req
        return success(accommodation_out(req), status=201)

    # ---------- Graduate-scoped lists ----------

    @bp.route("/graduates/<gid>/ticket-allocations", methods=["GET"])
    def list_graduate_allocations(gid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator", "Graduate"])
        g = get_graduate_or_404(gid)
        require_graduate_ownership(user_id, role, g["id"])
        limit, offset = parse_pagination(request.args)
        items = [a for a in db.ticket_allocations.values() if a["graduate_id"] == gid]
        items.sort(key=lambda a: a["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([allocation_out(a) for a in page], limit, offset, total)

    @bp.route("/graduates/<gid>/regalia-orders", methods=["GET"])
    def list_graduate_regalia(gid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator", "Graduate"])
        g = get_graduate_or_404(gid)
        require_graduate_ownership(user_id, role, g["id"])
        limit, offset = parse_pagination(request.args)
        items = [o for o in db.regalia_orders.values() if o["graduate_id"] == gid]
        status_f = request.args.get("status")
        if status_f:
            items = [o for o in items if o["status"] == status_f]
        items.sort(key=lambda o: o["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([regalia_out(o) for o in page], limit, offset, total)

    @bp.route("/graduates/<gid>/seat-assignments", methods=["GET"])
    def list_graduate_seats(gid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator", "Graduate"])
        g = get_graduate_or_404(gid)
        require_graduate_ownership(user_id, role, g["id"])
        limit, offset = parse_pagination(request.args)
        items = [s for s in db.seat_assignments.values() if s["graduate_id"] == gid]
        items.sort(key=lambda s: s["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([seat_out(s) for s in page], limit, offset, total)

    @bp.route("/graduates/<gid>/diplomas", methods=["GET"])
    def list_graduate_diplomas(gid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator", "Graduate"])
        g = get_graduate_or_404(gid)
        require_graduate_ownership(user_id, role, g["id"])
        limit, offset = parse_pagination(request.args)
        items = [d for d in db.diplomas.values() if d["graduate_id"] == gid]
        items.sort(key=lambda d: d["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([diploma_out(d) for d in page], limit, offset, total)

    @bp.route("/graduates/<gid>/accommodation-requests", methods=["GET"])
    def list_graduate_accommodations(gid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator", "Graduate"])
        g = get_graduate_or_404(gid)
        require_graduate_ownership(user_id, role, g["id"])
        limit, offset = parse_pagination(request.args)
        items = [r for r in db.accommodation_requests.values() if r["graduate_id"] == gid]
        items.sort(key=lambda r: r["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([accommodation_out(r) for r in page], limit, offset, total)

    @bp.route("/graduates/<gid>/rehearsal-attendances", methods=["GET"])
    def list_graduate_attendances(gid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator", "Graduate"])
        g = get_graduate_or_404(gid)
        require_graduate_ownership(user_id, role, g["id"])
        limit, offset = parse_pagination(request.args)
        items = [a for a in db.rehearsal_attendances.values() if a["graduate_id"] == gid]
        items.sort(key=lambda a: a["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([attendance_out(a) for a in page], limit, offset, total)

    @bp.route("/graduates/<gid>/reader-cards", methods=["GET"])
    def list_graduate_reader_cards(gid):
        user_id, role = get_caller()
        require_role(role, ["CommitteeChair", "RegistrarOfficer", "VenueCoordinator", "Graduate"])
        g = get_graduate_or_404(gid)
        require_graduate_ownership(user_id, role, g["id"])
        limit, offset = parse_pagination(request.args)
        items = [r for r in db.reader_cards.values() if r["graduate_id"] == gid]
        items.sort(key=lambda r: r["created_at"])
        page, total = paginate(items, limit, offset)
        return success_list([reader_card_out(r) for r in page], limit, offset, total)

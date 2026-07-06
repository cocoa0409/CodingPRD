"""Escalation + VA replacement cascade (PRD §3.7)."""
from flask import request


def register_escalation_routes(ctx):
    app = ctx["app"]
    P = ctx["PREFIX"]
    db = ctx["db"]
    stamp_create = ctx["stamp_create"]
    touch = ctx["touch"]
    err = ctx["err"]
    ok = ctx["ok"]
    auth = ctx["auth"]
    require_role = ctx["require_role"]
    get_json = ctx["get_json"]
    require_fields = ctx["require_fields"]
    S = ctx["S"]
    svc = ctx["svc"]
    own = ctx["own"]
    fk = ctx["fk"]
    list_response = ctx["list_response"]
    get_escalation = ctx["get_escalation"]

    REASONS = ("SLA_BREACH", "QUALITY", "AVAILABILITY", "OTHER")

    @app.post(f"{P}/escalations")
    def escalation_create():
        role, uid = auth()
        require_role(role, {"Client", "StaffingManager"})
        body = get_json(request)
        require_fields(body, ["client_id", "reason"])
        client_id = body["client_id"]
        client = fk(db.clients, client_id, "client_id")
        own.require_client_owner(role, uid, client_id)
        reason = body["reason"]
        if reason not in REASONS:
            raise err("ERR_INVALID_REQUEST", "reason must be SLA_BREACH|QUALITY|AVAILABILITY|OTHER")
        rec = {
            "engagement_id": client.get("active_engagement_id"),
            "client_id": client_id,
            "reason": reason,
            "status": "OPEN",
            "replacement_engagement_id": None,
        }
        stamp_create(rec)
        db.escalations[rec["id"]] = rec
        return ok(S.escalation(rec), 201)

    @app.get(f"{P}/escalations/<escalation_id>")
    def escalation_get(escalation_id):
        role, uid = auth()
        require_role(role, {"StaffingManager", "Client"})
        rec = get_escalation(escalation_id)
        own.require_client_owner(role, uid, rec["client_id"])
        return ok(S.escalation(rec))

    @app.get(f"{P}/escalations")
    def escalation_list():
        role, uid = auth()
        require_role(role, {"StaffingManager", "Client"})
        recs = list(db.escalations.values())
        cid = request.args.get("client_id")
        if cid is not None:
            recs = [r for r in recs if r["client_id"] == cid]
        eid = request.args.get("engagement_id")
        if eid is not None:
            recs = [r for r in recs if r.get("engagement_id") == eid]
        status = request.args.get("status")
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        if role == "Client":
            recs = [r for r in recs if r["client_id"] == uid]
        return list_response(recs, S.escalation)

    @app.post(f"{P}/escalations/<escalation_id>/resolve")
    def escalation_resolve(escalation_id):
        role, _uid = auth()
        require_role(role, {"StaffingManager"})
        rec = get_escalation(escalation_id)
        if rec["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "escalation is not OPEN")
        rec["status"] = "RESOLVED"
        touch(rec)
        return ok(S.escalation(rec))

    @app.post(f"{P}/escalations/<escalation_id>/replace")
    def escalation_replace(escalation_id):
        role, _uid = auth()
        require_role(role, {"StaffingManager"})
        rec = get_escalation(escalation_id)
        body = get_json(request)
        require_fields(body, ["va_id"])
        new_va_id = body["va_id"]
        # FK existence (priority 4).
        new_va = fk(db.virtual_assistants, new_va_id, "va_id")
        # State (priority 8): OPEN -> REPLACED.
        if rec["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "escalation is not OPEN")
        original = db.engagements.get(rec.get("engagement_id"))
        # Priority 21: replacement VA not BENCHED AND original engagement ACTIVE.
        if new_va["status"] == "BENCHED":
            raise err("ERR_REPLACEMENT_INELIGIBLE", "replacement VA is BENCHED")
        if original is None or original["status"] != "ACTIVE":
            raise err("ERR_REPLACEMENT_INELIGIBLE", "original engagement is not ACTIVE")
        client = db.clients.get(rec["client_id"])
        # Hop 1: mint new ACTIVE engagement with replacement VA.
        new_eng = {
            "client_id": rec["client_id"],
            "va_id": new_va_id,
            "status": "ACTIVE",
            "match_score": None,
            "superseded_by_engagement_id": None,
            "onboarding_checklist_done": True,
        }
        stamp_create(new_eng)
        db.engagements[new_eng["id"]] = new_eng
        if client is not None:
            client["active_engagement_id"] = new_eng["id"]
            touch(client)
        touch(new_va)  # active_engagement_count computed; version bump
        # Hop 2+3: original -> ENDED, re-point its non-terminal tasks to new eng.
        original["superseded_by_engagement_id"] = new_eng["id"]
        svc.end_engagement(original, repoint_to=new_eng["id"])
        # Escalation -> REPLACED.
        rec["replacement_engagement_id"] = new_eng["id"]
        rec["status"] = "REPLACED"
        touch(rec)
        return ok(S.escalation(rec))

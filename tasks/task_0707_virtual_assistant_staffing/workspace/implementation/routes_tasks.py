"""Task queue, SLA clock, work lifecycle (PRD §3.4)."""
from flask import request


def register_task_routes(ctx):
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
    sla_mod = ctx["sla_mod"]
    fk = ctx["fk"]
    list_response = ctx["list_response"]
    get_task = ctx["get_task"]

    @app.post(f"{P}/tasks")
    def task_create():
        role, uid = auth()
        require_role(role, {"Client", "StaffingManager"})
        body = get_json(request)
        require_fields(body, ["client_id", "title"])
        client_id = body["client_id"]
        client = fk(db.clients, client_id, "client_id")
        # Ownership: Client may only create tasks for its own client tree.
        own.require_client_owner(role, uid, client_id)
        title = body["title"]
        if not isinstance(title, str):
            raise err("ERR_INVALID_REQUEST", "title must be a string")
        priority = body.get("priority", "STANDARD")
        if priority not in ("STANDARD", "PRIORITY", "URGENT"):
            raise err("ERR_INVALID_REQUEST", "priority must be STANDARD|PRIORITY|URGENT")
        required_skill_tag_id = body.get("required_skill_tag_id")
        if required_skill_tag_id is not None:
            fk(db.skill_tags, required_skill_tag_id, "required_skill_tag_id")
        estimated_hours = body.get("estimated_hours", 0)
        if estimated_hours is None:
            estimated_hours = 0
        if isinstance(estimated_hours, bool) or not isinstance(estimated_hours, (int, float)):
            raise err("ERR_INVALID_REQUEST", "estimated_hours must be a number")
        if estimated_hours < 0:
            raise err("ERR_INVALID_REQUEST", "estimated_hours must be >= 0")
        rec = {
            "client_id": client_id,
            "engagement_id": None,
            "title": title,
            "priority": priority,
            "required_skill_tag_id": required_skill_tag_id,
            "status": "QUEUED",
            "estimated_hours": estimated_hours,
            "assigned_at_iso": None,
            "first_action_at_iso": None,
            "completed_at_iso": None,
            "response_due_iso": None,
            "resolution_due_iso": None,
            "blocked_reason": None,
        }
        stamp_create(rec)
        db.tasks[rec["id"]] = rec
        return ok(S.task(rec), 201)

    @app.get(f"{P}/tasks/<task_id>")
    def task_get(task_id):
        role, uid = auth()
        require_role(role, {"StaffingManager", "Client", "VA"})
        rec = get_task(task_id)
        if role == "Client":
            own.require_client_owner(role, uid, rec["client_id"])
        elif role == "VA":
            own.require_va_owner(role, uid, own.va_of_task(rec))
        return ok(S.task(rec))

    @app.get(f"{P}/tasks")
    def task_list():
        role, uid = auth()
        require_role(role, {"StaffingManager", "Client", "VA"})
        recs = list(db.tasks.values())
        cid = request.args.get("client_id")
        if cid is not None:
            recs = [r for r in recs if r["client_id"] == cid]
        eid = request.args.get("engagement_id")
        if eid is not None:
            recs = [r for r in recs if r.get("engagement_id") == eid]
        rsid = request.args.get("required_skill_tag_id")
        if rsid is not None:
            recs = [r for r in recs if r.get("required_skill_tag_id") == rsid]
        status = request.args.get("status")
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        priority = request.args.get("priority")
        if priority is not None:
            recs = [r for r in recs if r["priority"] == priority]
        if role == "Client":
            recs = [r for r in recs if r["client_id"] == uid]
        elif role == "VA":
            recs = [r for r in recs if own.va_of_task(r) == uid]
        return list_response(recs, S.task)

    @app.post(f"{P}/tasks/<task_id>/assign")
    def task_assign(task_id):
        role, _uid = auth()
        require_role(role, {"StaffingManager"})
        rec = get_task(task_id)
        # State (priority 8): QUEUED -> ASSIGNED.
        if rec["status"] != "QUEUED":
            raise err("ERR_INVALID_STATE", "task is not QUEUED")
        client = db.clients.get(rec["client_id"])
        # Priority 9: client ACTIVE + active_engagement_id set.
        if client is None or client["status"] != "ACTIVE" or not client.get("active_engagement_id"):
            raise err("ERR_CLIENT_NOT_ACTIVE", "client not active or no active engagement")
        # Priority 10: SlaPolicy exists for the priority tier.
        if sla_mod.sla_policy_for(rec["priority"]) is None:
            raise err("ERR_SLA_POLICY_MISSING", "no SLA policy for tier")
        # Priority 11: specialized-skill add-on gate.
        rsid = rec.get("required_skill_tag_id")
        if rsid is not None:
            skill = db.skill_tags.get(rsid)
            if skill is not None and skill["is_specialized"]:
                eng_id = client["active_engagement_id"]
                has_active_addon = any(
                    a["engagement_id"] == eng_id and a["skill_tag_id"] == rsid
                    and a["status"] == "ACTIVE"
                    for a in db.addons.values()
                )
                if not has_active_addon:
                    raise err("ERR_ADDON_REQUIRED", "active add-on required for specialized skill")
        rec["engagement_id"] = client["active_engagement_id"]
        rec["assigned_at_iso"] = db.clock_iso_logical()
        resp, res = sla_mod.compute_due(rec["assigned_at_iso"], rec["priority"])
        rec["response_due_iso"] = resp
        rec["resolution_due_iso"] = res
        rec["status"] = "ASSIGNED"
        touch(rec)
        return ok(S.task(rec))

    def _require_engagement_va(rec, role, uid):
        own.require_va_owner(role, uid, own.va_of_task(rec))

    @app.post(f"{P}/tasks/<task_id>/start")
    def task_start(task_id):
        role, uid = auth()
        require_role(role, {"VA"})
        rec = get_task(task_id)
        _require_engagement_va(rec, role, uid)
        if rec["status"] != "ASSIGNED":
            raise err("ERR_INVALID_STATE", "task is not ASSIGNED")
        rec["status"] = "IN_PROGRESS"
        if rec.get("first_action_at_iso") is None:
            rec["first_action_at_iso"] = db.clock_iso_logical()
        touch(rec)
        return ok(S.task(rec))

    @app.post(f"{P}/tasks/<task_id>/block")
    def task_block(task_id):
        role, uid = auth()
        require_role(role, {"VA"})
        rec = get_task(task_id)
        _require_engagement_va(rec, role, uid)
        body = get_json(request)
        require_fields(body, ["blocked_reason"])
        reason = body["blocked_reason"]
        if not isinstance(reason, str):
            raise err("ERR_INVALID_REQUEST", "blocked_reason must be a string")
        if rec["status"] not in ("ASSIGNED", "IN_PROGRESS"):
            raise err("ERR_INVALID_STATE", "task is not ASSIGNED or IN_PROGRESS")
        rec["blocked_reason"] = reason
        rec["status"] = "BLOCKED"
        if rec.get("first_action_at_iso") is None:
            rec["first_action_at_iso"] = db.clock_iso_logical()
        touch(rec)
        return ok(S.task(rec))

    @app.post(f"{P}/tasks/<task_id>/unblock")
    def task_unblock(task_id):
        role, uid = auth()
        require_role(role, {"VA"})
        rec = get_task(task_id)
        _require_engagement_va(rec, role, uid)
        if rec["status"] != "BLOCKED":
            raise err("ERR_INVALID_STATE", "task is not BLOCKED")
        client = db.clients.get(rec["client_id"])
        if client is None or client["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "client is not ACTIVE")
        rec["blocked_reason"] = None
        rec["status"] = "IN_PROGRESS"
        touch(rec)
        return ok(S.task(rec))

    @app.post(f"{P}/tasks/<task_id>/complete")
    def task_complete(task_id):
        role, uid = auth()
        require_role(role, {"VA"})
        rec = get_task(task_id)
        _require_engagement_va(rec, role, uid)
        if rec["status"] != "IN_PROGRESS":
            raise err("ERR_INVALID_STATE", "task is not IN_PROGRESS")
        has_approved = any(
            te["task_id"] == rec["id"] and te["status"] == "APPROVED"
            for te in db.time_entries.values()
        )
        if not has_approved:
            raise err("ERR_NO_APPROVED_TIME", "no approved time entry on task")
        rec["status"] = "DONE"
        rec["completed_at_iso"] = db.clock_iso_logical()
        touch(rec)
        return ok(S.task(rec))

    @app.post(f"{P}/tasks/<task_id>/cancel")
    def task_cancel(task_id):
        role, uid = auth()
        require_role(role, {"Client", "StaffingManager"})
        rec = get_task(task_id)
        if role == "Client":
            own.require_client_owner(role, uid, rec["client_id"])
        if rec["status"] in ("DONE", "CANCELLED"):
            raise err("ERR_INVALID_STATE", "task already terminal")
        svc.cancel_task_cascade(rec)
        return ok(S.task(rec))

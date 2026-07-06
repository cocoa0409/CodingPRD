"""Client intake, scoping, suspension cycle, close cascade (PRD §3.2)."""
from flask import request


def register_client_routes(ctx):
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
    range_check = ctx["range_check"]
    list_response = ctx["list_response"]
    get_client = ctx["get_client"]

    NON_TERMINAL_TASK = svc.NON_TERMINAL_TASK

    @app.post(f"{P}/clients")
    def client_create():
        role, _uid = auth()
        require_role(role, {"StaffingManager", "Client"})
        body = get_json(request)
        require_fields(body, ["company_name", "contact_email"])
        company_name = body["company_name"]
        contact_email = body["contact_email"]
        if not isinstance(company_name, str) or not isinstance(contact_email, str):
            raise err("ERR_INVALID_REQUEST", "company_name and contact_email must be strings")
        for c in db.clients.values():
            if c["contact_email"] == contact_email:
                raise err("ERR_DUPLICATE", "contact_email already exists")
        rec = {
            "company_name": company_name,
            "contact_email": contact_email,
            "status": "PENDING",
            "scope_summary": None,
            "required_skill_tag_ids": [],
            "monthly_retainer_hours": None,
            "base_rate_cents": None,
            "overage_rate_cents": None,
            "rollover_cap_hours": 0,
            "active_engagement_id": None,
        }
        stamp_create(rec)
        db.clients[rec["id"]] = rec
        return ok(S.client(rec), 201)

    @app.get(f"{P}/clients/<client_id>")
    def client_get(client_id):
        role, uid = auth()
        require_role(role, {"StaffingManager", "Client"})
        rec = get_client(client_id)
        own.require_client_owner(role, uid, rec["id"])
        return ok(S.client(rec))

    @app.get(f"{P}/clients")
    def client_list():
        role, _uid = auth()
        require_role(role, {"StaffingManager"})
        recs = list(db.clients.values())
        status = request.args.get("status")
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        return list_response(recs, S.client)

    @app.patch(f"{P}/clients/<client_id>/scope")
    def client_scope(client_id):
        role, uid = auth()
        require_role(role, {"Client"})
        rec = get_client(client_id)
        own.require_client_owner(role, uid, rec["id"])
        body = get_json(request)
        # FK existence (priority 4): required_skill_tag_ids elements.
        skill_ids = body.get("required_skill_tag_ids", [])
        if skill_ids is None:
            skill_ids = []
        if not isinstance(skill_ids, list):
            raise err("ERR_INVALID_REQUEST", "required_skill_tag_ids must be an array")
        for sid in skill_ids:
            fk(db.skill_tags, sid, "required_skill_tag_id")
        # Well-formedness (priority 5).
        require_fields(body, ["monthly_retainer_hours", "base_rate_cents", "overage_rate_cents"])
        mrh = body["monthly_retainer_hours"]
        brc = body["base_rate_cents"]
        orc = body["overage_rate_cents"]
        if isinstance(mrh, bool) or not isinstance(mrh, (int, float)):
            raise err("ERR_INVALID_REQUEST", "monthly_retainer_hours must be a number")
        if isinstance(brc, bool) or not isinstance(brc, int) or brc < 0:
            raise err("ERR_INVALID_REQUEST", "base_rate_cents must be int >= 0")
        if isinstance(orc, bool) or not isinstance(orc, int) or orc < 0:
            raise err("ERR_INVALID_REQUEST", "overage_rate_cents must be int >= 0")
        rch = body.get("rollover_cap_hours", 0)
        if rch is None:
            rch = 0
        if isinstance(rch, bool) or not isinstance(rch, (int, float)):
            raise err("ERR_INVALID_REQUEST", "rollover_cap_hours must be a number")
        scope_summary = body.get("scope_summary")
        if scope_summary is not None and not isinstance(scope_summary, str):
            raise err("ERR_INVALID_REQUEST", "scope_summary must be a string")
        # Range guards (priority 6).
        range_check(mrh >= 1.0, "monthly_retainer_hours must be >= 1.0")
        range_check(rch >= 0, "rollover_cap_hours must be >= 0")
        # State (priority 8): PENDING -> SCOPED.
        if rec["status"] != "PENDING":
            raise err("ERR_INVALID_STATE", "client is not PENDING")
        rec["scope_summary"] = scope_summary
        rec["required_skill_tag_ids"] = list(skill_ids)
        rec["monthly_retainer_hours"] = mrh
        rec["base_rate_cents"] = brc
        rec["overage_rate_cents"] = orc
        rec["rollover_cap_hours"] = rch
        rec["status"] = "SCOPED"
        touch(rec)
        return ok(S.client(rec))

    @app.post(f"{P}/clients/<client_id>/suspend")
    def client_suspend(client_id):
        role, _uid = auth()
        require_role(role, {"StaffingManager"})
        rec = get_client(client_id)
        if rec["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "client is not ACTIVE")
        rec["status"] = "SUSPENDED"
        for t in db.tasks.values():
            if t["client_id"] == rec["id"] and t["status"] in ("QUEUED", "ASSIGNED"):
                t["blocked_reason"] = "CLIENT_SUSPENDED"
                t["_pre_suspend_status"] = t["status"]
                t["status"] = "BLOCKED"
                touch(t)
        touch(rec)
        return ok(S.client(rec))

    @app.post(f"{P}/clients/<client_id>/resume")
    def client_resume(client_id):
        role, _uid = auth()
        require_role(role, {"StaffingManager"})
        rec = get_client(client_id)
        if rec["status"] != "SUSPENDED":
            raise err("ERR_INVALID_STATE", "client is not SUSPENDED")
        rec["status"] = "ACTIVE"
        for t in db.tasks.values():
            if (t["client_id"] == rec["id"] and t["status"] == "BLOCKED"
                    and t.get("blocked_reason") == "CLIENT_SUSPENDED"):
                pre = t.pop("_pre_suspend_status", None)
                # Previously assigned -> ASSIGNED; never-assigned -> QUEUED.
                if pre == "ASSIGNED" or t.get("assigned_at_iso") is not None:
                    t["status"] = "ASSIGNED"
                else:
                    t["status"] = "QUEUED"
                t["blocked_reason"] = None
                touch(t)
        touch(rec)
        return ok(S.client(rec))

    @app.post(f"{P}/clients/<client_id>/close")
    def client_close(client_id):
        role, _uid = auth()
        require_role(role, {"StaffingManager"})
        rec = get_client(client_id)
        # State (priority 8): closable from SCOPED/ACTIVE/SUSPENDED.
        if rec["status"] not in ("SCOPED", "ACTIVE", "SUSPENDED"):
            raise err("ERR_INVALID_STATE", "client is not closable")
        # Precondition: no Task in IN_PROGRESS.
        for t in db.tasks.values():
            if t["client_id"] == rec["id"] and t["status"] == "IN_PROGRESS":
                raise err("ERR_INVALID_STATE", "a task is IN_PROGRESS")
        rec["status"] = "CLOSED"
        # Hop 1+2: non-terminal tasks -> CANCELLED; their LOGGED entries -> REJECTED.
        for t in db.tasks.values():
            if t["client_id"] == rec["id"] and t["status"] in NON_TERMINAL_TASK:
                svc.cancel_task_cascade(t)
        # Hop 3: OPEN cycle -> CLOSED (no successor minted).
        cyc = svc.open_cycle_for_client(rec["id"])
        if cyc is not None:
            cyc["status"] = "CLOSED"
            cyc["closed_at_iso"] = db.clock_iso_logical()
            touch(cyc)
        # Final: ACTIVE engagement -> ENDED (VA count dec, -> AVAILABLE if 0).
        if rec.get("active_engagement_id"):
            eng = db.engagements.get(rec["active_engagement_id"])
            if eng is not None and eng["status"] == "ACTIVE":
                svc.end_engagement(eng, repoint_to=None)
        rec["active_engagement_id"] = None
        touch(rec)
        return ok(S.client(rec))

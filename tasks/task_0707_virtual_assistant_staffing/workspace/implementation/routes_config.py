"""Config + pool routes: clock, skill-tags, sla-policies, virtual-assistants."""
from flask import request


def register_config_routes(ctx):
    app = ctx["app"]
    P = ctx["PREFIX"]
    db = ctx["db"]
    stamp_create = ctx["stamp_create"]
    err = ctx["err"]
    ok = ctx["ok"]
    auth = ctx["auth"]
    require_role = ctx["require_role"]
    get_json = ctx["get_json"]
    require_fields = ctx["require_fields"]
    S = ctx["S"]
    fk = ctx["fk"]
    range_check = ctx["range_check"]
    list_response = ctx["list_response"]
    parse_iso = ctx["parse_iso"]
    get_skill_tag = ctx["get_skill_tag"]
    get_sla_policy = ctx["get_sla_policy"]
    get_va = ctx["get_va"]

    # ---- Logical clock -----------------------------------------------------
    @app.post(f"{P}/_clock/set_current_utc")
    def clock_set():
        role, _uid = auth()
        require_role(role, {"StaffingManager"})
        body = get_json(request)
        require_fields(body, ["to_iso8601"])
        raw = body["to_iso8601"]
        try:
            dt = parse_iso(raw)
        except Exception:
            raise err("ERR_INVALID_REQUEST", "to_iso8601 must be ISO8601")
        db.clock.set(dt)
        return ok(S.clock_view())

    @app.get(f"{P}/_clock")
    def clock_get():
        role, _uid = auth()
        require_role(role, {"StaffingManager", "Client", "VA"})
        return ok(S.clock_view())

    # ---- SkillTag ----------------------------------------------------------
    @app.post(f"{P}/skill-tags")
    def skill_tag_create():
        role, _uid = auth()
        require_role(role, {"StaffingManager"})
        body = get_json(request)
        require_fields(body, ["code", "name"])
        code = body["code"]
        name = body["name"]
        if not isinstance(code, str) or not isinstance(name, str):
            raise err("ERR_INVALID_REQUEST", "code and name must be strings")
        is_specialized = body.get("is_specialized", False)
        if not isinstance(is_specialized, bool):
            raise err("ERR_INVALID_REQUEST", "is_specialized must be boolean")
        # Uniqueness (priority 22) — checked after well-formedness.
        for t in db.skill_tags.values():
            if t["code"] == code:
                raise err("ERR_DUPLICATE", "skill tag code already exists")
        rec = {"code": code, "name": name, "is_specialized": is_specialized}
        stamp_create(rec, full_lifecycle=False)
        db.skill_tags[rec["id"]] = rec
        return ok(S.skill_tag(rec), 201)

    @app.get(f"{P}/skill-tags/<skill_tag_id>")
    def skill_tag_get(skill_tag_id):
        role, _uid = auth()
        require_role(role, {"StaffingManager", "Client", "VA"})
        rec = get_skill_tag(skill_tag_id)
        return ok(S.skill_tag(rec))

    @app.get(f"{P}/skill-tags")
    def skill_tag_list():
        role, _uid = auth()
        require_role(role, {"StaffingManager", "Client", "VA"})
        recs = list(db.skill_tags.values())
        spec = request.args.get("is_specialized")
        if spec is not None:
            want = spec.lower() == "true"
            recs = [r for r in recs if r["is_specialized"] == want]
        return list_response(recs, S.skill_tag)

    # ---- SlaPolicy ---------------------------------------------------------
    @app.post(f"{P}/sla-policies")
    def sla_policy_create():
        role, _uid = auth()
        require_role(role, {"StaffingManager"})
        body = get_json(request)
        require_fields(body, ["tier", "response_minutes", "resolution_hours", "breach_penalty_pct"])
        tier = body["tier"]
        if tier not in ("STANDARD", "PRIORITY", "URGENT"):
            raise err("ERR_INVALID_REQUEST", "tier must be STANDARD|PRIORITY|URGENT")
        rm = body["response_minutes"]
        rh = body["resolution_hours"]
        bp = body["breach_penalty_pct"]
        if isinstance(rm, bool) or not isinstance(rm, int) or rm < 1:
            raise err("ERR_INVALID_REQUEST", "response_minutes must be int >= 1")
        if isinstance(rh, bool) or not isinstance(rh, int) or rh < 1:
            raise err("ERR_INVALID_REQUEST", "resolution_hours must be int >= 1")
        if isinstance(bp, bool) or not isinstance(bp, (int, float)):
            raise err("ERR_INVALID_REQUEST", "breach_penalty_pct must be a number")
        # Range guard (priority 6).
        range_check(0.0 <= bp <= 1.0, "breach_penalty_pct must be in [0,1]")
        # Uniqueness (priority 22).
        for p in db.sla_policies.values():
            if p["tier"] == tier:
                raise err("ERR_DUPLICATE", "sla policy tier already exists")
        rec = {
            "tier": tier,
            "response_minutes": rm,
            "resolution_hours": rh,
            "breach_penalty_pct": bp,
        }
        stamp_create(rec, full_lifecycle=False)
        db.sla_policies[rec["id"]] = rec
        return ok(S.sla_policy(rec), 201)

    @app.get(f"{P}/sla-policies/<sla_policy_id>")
    def sla_policy_get(sla_policy_id):
        role, _uid = auth()
        require_role(role, {"StaffingManager", "Client", "VA"})
        rec = get_sla_policy(sla_policy_id)
        return ok(S.sla_policy(rec))

    @app.get(f"{P}/sla-policies")
    def sla_policy_list():
        role, _uid = auth()
        require_role(role, {"StaffingManager", "Client", "VA"})
        recs = list(db.sla_policies.values())
        tier = request.args.get("tier")
        if tier is not None:
            recs = [r for r in recs if r["tier"] == tier]
        return list_response(recs, S.sla_policy)

    # ---- VirtualAssistant --------------------------------------------------
    @app.post(f"{P}/virtual-assistants")
    def va_create():
        role, _uid = auth()
        require_role(role, {"StaffingManager"})
        body = get_json(request)
        require_fields(body, ["full_name", "email", "weekly_capacity_hours"])
        full_name = body["full_name"]
        email = body["email"]
        if not isinstance(full_name, str) or not isinstance(email, str):
            raise err("ERR_INVALID_REQUEST", "full_name and email must be strings")
        wch = body["weekly_capacity_hours"]
        if isinstance(wch, bool) or not isinstance(wch, (int, float)):
            raise err("ERR_INVALID_REQUEST", "weekly_capacity_hours must be a number")
        skill_tag_ids = body.get("skill_tag_ids", [])
        if not isinstance(skill_tag_ids, list):
            raise err("ERR_INVALID_REQUEST", "skill_tag_ids must be an array")
        rating = body.get("rating", 3.0)
        if isinstance(rating, bool) or not isinstance(rating, (int, float)):
            raise err("ERR_INVALID_REQUEST", "rating must be a number")
        # FK existence for skill_tag_ids (priority 4).
        for sid in skill_tag_ids:
            fk(db.skill_tags, sid, "skill_tag_id")
        # Range guards (priority 6).
        range_check(wch >= 1.0, "weekly_capacity_hours must be >= 1.0")
        range_check(0.0 <= rating <= 5.0, "rating must be in [0,5]")
        # Uniqueness (priority 22).
        for v in db.virtual_assistants.values():
            if v["email"] == email:
                raise err("ERR_DUPLICATE", "VA email already exists")
        rec = {
            "full_name": full_name,
            "email": email,
            "status": "AVAILABLE",
            "skill_tag_ids": list(skill_tag_ids),
            "weekly_capacity_hours": wch,
            "rating": rating,
        }
        stamp_create(rec)
        db.virtual_assistants[rec["id"]] = rec
        return ok(S.virtual_assistant(rec), 201)

    @app.get(f"{P}/virtual-assistants/<va_id>")
    def va_get(va_id):
        role, _uid = auth()
        require_role(role, {"StaffingManager", "Client", "VA"})
        rec = get_va(va_id)
        return ok(S.virtual_assistant(rec))

    @app.get(f"{P}/virtual-assistants")
    def va_list():
        role, _uid = auth()
        require_role(role, {"StaffingManager", "Client"})
        recs = list(db.virtual_assistants.values())
        skill = request.args.get("skill_tag_id")
        if skill is not None:
            recs = [r for r in recs if skill in r["skill_tag_ids"]]
        status = request.args.get("status")
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        return list_response(recs, S.virtual_assistant)

"""Engagement matching/onboarding + AddOn routes (PRD §3.3, §3.6)."""
from flask import request


def register_engagement_routes(ctx):
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
    calc = ctx["calc"]
    fk = ctx["fk"]
    list_response = ctx["list_response"]
    get_engagement = ctx["get_engagement"]
    get_addon = ctx["get_addon"]

    # ---- Engagement create (auto-match if va_id omitted) -------------------
    @app.post(f"{P}/engagements")
    def engagement_create():
        role, _uid = auth()
        require_role(role, {"StaffingManager"})
        body = get_json(request)
        require_fields(body, ["client_id"])
        client_id = body["client_id"]
        client = fk(db.clients, client_id, "client_id")
        va_id = body.get("va_id")
        match_score = None
        if va_id is not None:
            va = fk(db.virtual_assistants, va_id, "va_id")
        else:
            # Auto-match (calc va_match_score).
            required = client.get("required_skill_tag_ids") or []
            req_count = len(required)
            candidates = []
            for v in db.virtual_assistants.values():
                if v["status"] not in ("AVAILABLE", "ENGAGED"):
                    continue
                covered = sum(1 for sid in required if sid in v["skill_tag_ids"])
                if covered < req_count:  # full coverage required (no partial)
                    continue
                score = calc.va_match_score(req_count, covered, v["rating"], v["weekly_capacity_hours"])
                candidates.append((score, v))
            if not candidates:
                raise err("ERR_NO_ELIGIBLE_VA", "no eligible VA")
            # Select MAX score; tie-break created_at ASC (earliest registered),
            # via hidden _seq; id never consulted.
            best = max(candidates, key=lambda sv: (sv[0], -sv[1]["_seq"]))
            match_score = best[0]
            va_id = best[1]["id"]
        rec = {
            "client_id": client_id,
            "va_id": va_id,
            "status": "PROPOSED",
            "match_score": match_score,
            "superseded_by_engagement_id": None,
            "onboarding_checklist_done": False,
        }
        stamp_create(rec)
        db.engagements[rec["id"]] = rec
        return ok(S.engagement(rec), 201)

    @app.get(f"{P}/engagements/<engagement_id>")
    def engagement_get(engagement_id):
        role, uid = auth()
        require_role(role, {"StaffingManager", "Client"})
        rec = get_engagement(engagement_id)
        own.require_client_owner(role, uid, own.client_of_engagement(rec))
        return ok(S.engagement(rec))

    @app.get(f"{P}/engagements")
    def engagement_list():
        role, uid = auth()
        require_role(role, {"StaffingManager", "Client"})
        recs = list(db.engagements.values())
        cid = request.args.get("client_id")
        if cid is not None:
            recs = [r for r in recs if r["client_id"] == cid]
        vid = request.args.get("va_id")
        if vid is not None:
            recs = [r for r in recs if r["va_id"] == vid]
        status = request.args.get("status")
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        if role == "Client":
            recs = [r for r in recs if r["client_id"] == uid]
        return list_response(recs, S.engagement)

    @app.post(f"{P}/engagements/<engagement_id>/accept")
    def engagement_accept(engagement_id):
        role, uid = auth()
        require_role(role, {"Client"})
        rec = get_engagement(engagement_id)
        own.require_client_owner(role, uid, own.client_of_engagement(rec))
        if rec["status"] != "PROPOSED":
            raise err("ERR_INVALID_STATE", "engagement is not PROPOSED")
        va = db.virtual_assistants.get(rec["va_id"])
        if va is None or va["status"] == "BENCHED":
            raise err("ERR_INVALID_STATE", "VA not available for onboarding")
        rec["status"] = "ONBOARDING"
        va["status"] = "ENGAGED"
        touch(va)
        touch(rec)
        return ok(S.engagement(rec))

    @app.post(f"{P}/engagements/<engagement_id>/reject")
    def engagement_reject(engagement_id):
        role, uid = auth()
        require_role(role, {"Client"})
        rec = get_engagement(engagement_id)
        own.require_client_owner(role, uid, own.client_of_engagement(rec))
        if rec["status"] != "PROPOSED":
            raise err("ERR_INVALID_STATE", "engagement is not PROPOSED")
        rec["status"] = "REJECTED"
        touch(rec)
        return ok(S.engagement(rec))

    @app.post(f"{P}/engagements/<engagement_id>/return-to-proposed")
    def engagement_return(engagement_id):
        role, _uid = auth()
        require_role(role, {"StaffingManager"})
        rec = get_engagement(engagement_id)
        if rec["status"] != "ONBOARDING":
            raise err("ERR_INVALID_STATE", "engagement is not ONBOARDING")
        if rec["onboarding_checklist_done"]:
            raise err("ERR_INVALID_STATE", "onboarding_checklist_done is true")
        rec["status"] = "PROPOSED"
        touch(rec)
        # VA -> AVAILABLE if no other ACTIVE engagement holds it.
        svc.refresh_va_availability(rec["va_id"])
        return ok(S.engagement(rec))

    @app.post(f"{P}/engagements/<engagement_id>/activate")
    def engagement_activate(engagement_id):
        role, _uid = auth()
        require_role(role, {"StaffingManager"})
        rec = get_engagement(engagement_id)
        body = get_json(request)
        require_fields(body, ["onboarding_checklist_done"])
        done = body["onboarding_checklist_done"]
        if not isinstance(done, bool):
            raise err("ERR_INVALID_REQUEST", "onboarding_checklist_done must be boolean")
        if rec["status"] != "ONBOARDING":
            raise err("ERR_INVALID_STATE", "engagement is not ONBOARDING")
        if done is not True:
            raise err("ERR_INVALID_STATE", "onboarding_checklist_done must be true to activate")
        client = db.clients.get(rec["client_id"])
        if client is None or client["status"] not in ("SCOPED", "ACTIVE"):
            raise err("ERR_INVALID_STATE", "client must be SCOPED or ACTIVE")
        rec["onboarding_checklist_done"] = True
        rec["status"] = "ACTIVE"
        client["active_engagement_id"] = rec["id"]
        va = db.virtual_assistants.get(rec["va_id"])
        if va is not None:
            touch(va)  # active_engagement_count is computed; bump version on change
        # If client was SCOPED, drive to ACTIVE + open cycle #1.
        if client["status"] == "SCOPED":
            svc.client_to_active_via_engagement(client, rec)
        else:
            touch(client)
        touch(rec)
        return ok(S.engagement(rec))

    @app.post(f"{P}/engagements/<engagement_id>/end")
    def engagement_end(engagement_id):
        role, _uid = auth()
        require_role(role, {"StaffingManager"})
        rec = get_engagement(engagement_id)
        if rec["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "engagement is not ACTIVE")
        svc.end_engagement(rec, repoint_to=None)
        return ok(S.engagement(rec))

    # ---- AddOn -------------------------------------------------------------
    @app.post(f"{P}/addons")
    def addon_create():
        role, uid = auth()
        require_role(role, {"Client"})
        body = get_json(request)
        require_fields(body, ["engagement_id", "skill_tag_id", "surcharge_rate_cents"])
        engagement_id = body["engagement_id"]
        skill_tag_id = body["skill_tag_id"]
        eng = fk(db.engagements, engagement_id, "engagement_id")
        skill = fk(db.skill_tags, skill_tag_id, "skill_tag_id")
        # Ownership: client of the engagement.
        own.require_client_owner(role, uid, eng["client_id"])
        src = body["surcharge_rate_cents"]
        if isinstance(src, bool) or not isinstance(src, int) or src < 0:
            raise err("ERR_INVALID_REQUEST", "surcharge_rate_cents must be int >= 0")
        # Specialized gate (priority 12).
        if not skill["is_specialized"]:
            raise err("ERR_NOT_SPECIALIZED", "skill tag is not specialized")
        rec = {
            "engagement_id": engagement_id,
            "skill_tag_id": skill_tag_id,
            "status": "REQUESTED",
            "surcharge_rate_cents": src,
        }
        stamp_create(rec)
        db.addons[rec["id"]] = rec
        return ok(S.addon(rec), 201)

    @app.get(f"{P}/addons/<addon_id>")
    def addon_get(addon_id):
        role, uid = auth()
        require_role(role, {"StaffingManager", "Client"})
        rec = get_addon(addon_id)
        own.require_client_owner(role, uid, own.client_of_addon(rec))
        return ok(S.addon(rec))

    @app.get(f"{P}/addons")
    def addon_list():
        role, uid = auth()
        require_role(role, {"StaffingManager", "Client"})
        recs = list(db.addons.values())
        eid = request.args.get("engagement_id")
        if eid is not None:
            recs = [r for r in recs if r["engagement_id"] == eid]
        sid = request.args.get("skill_tag_id")
        if sid is not None:
            recs = [r for r in recs if r["skill_tag_id"] == sid]
        status = request.args.get("status")
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        if role == "Client":
            recs = [r for r in recs if own.client_of_addon(r) == uid]
        return list_response(recs, S.addon)

    @app.post(f"{P}/addons/<addon_id>/activate")
    def addon_activate(addon_id):
        role, _uid = auth()
        require_role(role, {"StaffingManager"})
        rec = get_addon(addon_id)
        if rec["status"] != "REQUESTED":
            raise err("ERR_INVALID_STATE", "addon is not REQUESTED")
        rec["status"] = "ACTIVE"
        touch(rec)
        return ok(S.addon(rec))

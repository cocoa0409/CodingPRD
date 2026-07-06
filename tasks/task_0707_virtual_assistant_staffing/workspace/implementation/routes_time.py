"""TimeEntry logging, approval, rejection (PRD §3.5)."""
from flask import request


def register_time_routes(ctx):
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
    get_entry = ctx["get_entry"]

    @app.post(f"{P}/time-entries")
    def time_entry_create():
        role, uid = auth()
        require_role(role, {"VA"})
        body = get_json(request)
        require_fields(body, ["task_id", "raw_minutes"])
        task_id = body["task_id"]
        task = fk(db.tasks, task_id, "task_id")
        raw_minutes = body["raw_minutes"]
        if isinstance(raw_minutes, bool) or not isinstance(raw_minutes, int) or raw_minutes < 1:
            raise err("ERR_INVALID_REQUEST", "raw_minutes must be int >= 1")
        note = body.get("note")
        if note is not None and not isinstance(note, str):
            raise err("ERR_INVALID_REQUEST", "note must be a string")
        # Priority 14: task in {ASSIGNED, IN_PROGRESS} AND acting VA is the
        # engagement VA. Else ERR_TASK_NOT_WORKABLE.
        if task["status"] not in ("ASSIGNED", "IN_PROGRESS"):
            raise err("ERR_TASK_NOT_WORKABLE", "task not in a workable state")
        eng_va = own.va_of_task(task)
        if eng_va is None or eng_va != uid:
            raise err("ERR_TASK_NOT_WORKABLE", "VA is not the engagement VA")
        # Priority 15: client must have an OPEN cycle to pin.
        cyc = svc.open_cycle_for_client(task["client_id"])
        if cyc is None:
            raise err("ERR_CYCLE_NOT_OPEN", "client has no OPEN cycle")
        rec = {
            "task_id": task_id,
            "cycle_id": cyc["id"],
            "va_id": eng_va,
            "status": "LOGGED",
            "raw_minutes": raw_minutes,
            "billable_hours": calc.billable_hours(raw_minutes),
            "note": note,
            "approved_at_iso": None,
        }
        stamp_create(rec)
        db.time_entries[rec["id"]] = rec
        return ok(S.time_entry(rec), 201)

    @app.get(f"{P}/time-entries/<entry_id>")
    def time_entry_get(entry_id):
        role, uid = auth()
        require_role(role, {"StaffingManager", "Client", "VA"})
        rec = get_entry(entry_id)
        if role == "Client":
            own.require_client_owner(role, uid, own.client_of_time_entry(rec))
        elif role == "VA":
            own.require_va_owner(role, uid, own.va_of_time_entry(rec))
        return ok(S.time_entry(rec))

    @app.get(f"{P}/time-entries")
    def time_entry_list():
        role, uid = auth()
        require_role(role, {"StaffingManager", "Client", "VA"})
        recs = list(db.time_entries.values())
        tid = request.args.get("task_id")
        if tid is not None:
            recs = [r for r in recs if r["task_id"] == tid]
        cid = request.args.get("cycle_id")
        if cid is not None:
            recs = [r for r in recs if r.get("cycle_id") == cid]
        vid = request.args.get("va_id")
        if vid is not None:
            recs = [r for r in recs if r.get("va_id") == vid]
        status = request.args.get("status")
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        if role == "Client":
            recs = [r for r in recs if own.client_of_time_entry(r) == uid]
        elif role == "VA":
            recs = [r for r in recs if own.va_of_time_entry(r) == uid]
        return list_response(recs, S.time_entry)

    @app.post(f"{P}/time-entries/<entry_id>/approve")
    def time_entry_approve(entry_id):
        role, uid = auth()
        require_role(role, {"Client"})
        rec = get_entry(entry_id)
        # Ownership: the acting client owns the task.
        own.require_client_owner(role, uid, own.client_of_time_entry(rec))
        # State (priority 8): LOGGED -> APPROVED.
        if rec["status"] != "LOGGED":
            raise err("ERR_INVALID_STATE", "entry is not LOGGED")
        task = db.tasks.get(rec["task_id"])
        client_id = task["client_id"] if task else None
        # Priority 16: client must have an OPEN cycle.
        cyc = svc.open_cycle_for_client(client_id)
        if cyc is None:
            raise err("ERR_NO_OPEN_CYCLE", "client has no OPEN cycle")
        rec["status"] = "APPROVED"
        rec["approved_at_iso"] = db.clock_iso_logical()
        rec["cycle_id"] = cyc["id"]  # re-pin to current OPEN cycle
        touch(rec)
        # Cycle balances are computed at read; bump cycle.version (§2.9).
        touch(cyc)
        return ok(S.time_entry(rec))

    @app.post(f"{P}/time-entries/<entry_id>/reject")
    def time_entry_reject(entry_id):
        role, uid = auth()
        require_role(role, {"Client"})
        rec = get_entry(entry_id)
        own.require_client_owner(role, uid, own.client_of_time_entry(rec))
        if rec["status"] != "LOGGED":
            raise err("ERR_INVALID_STATE", "entry is not LOGGED")
        rec["status"] = "REJECTED"
        touch(rec)
        return ok(S.time_entry(rec))

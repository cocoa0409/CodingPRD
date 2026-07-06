"""RetainerCycle read + close (OCC, rollover, successor minting) (PRD §3.8)."""
from flask import request


def register_cycle_routes(ctx):
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
    list_response = ctx["list_response"]
    get_cycle = ctx["get_cycle"]

    @app.get(f"{P}/cycles/<cycle_id>")
    def cycle_get(cycle_id):
        role, uid = auth()
        require_role(role, {"StaffingManager", "Client"})
        rec = get_cycle(cycle_id)
        own.require_client_owner(role, uid, rec["client_id"])
        return ok(S.retainer_cycle(rec))

    @app.get(f"{P}/cycles")
    def cycle_list():
        role, uid = auth()
        require_role(role, {"StaffingManager", "Client"})
        recs = list(db.retainer_cycles.values())
        cid = request.args.get("client_id")
        if cid is not None:
            recs = [r for r in recs if r["client_id"] == cid]
        status = request.args.get("status")
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        if role == "Client":
            recs = [r for r in recs if r["client_id"] == uid]
        return list_response(recs, S.retainer_cycle)

    @app.post(f"{P}/cycles/<cycle_id>/close")
    def cycle_close(cycle_id):
        role, _uid = auth()
        require_role(role, {"StaffingManager"})
        rec = get_cycle(cycle_id)
        body = get_json(request)
        require_fields(body, ["expected_cycle_version"])
        ecv = body["expected_cycle_version"]
        if isinstance(ecv, bool) or not isinstance(ecv, int):
            raise err("ERR_INVALID_REQUEST", "expected_cycle_version must be an integer")
        # State (priority 8): OPEN -> CLOSED.
        if rec["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "cycle is not OPEN")
        # Priority 17: no LOGGED (un-approved) entry may charge this cycle.
        has_pending = any(
            te.get("cycle_id") == rec["id"] and te["status"] == "LOGGED"
            for te in db.time_entries.values()
        )
        if has_pending:
            raise err("ERR_CYCLE_HAS_PENDING_ENTRIES", "cycle has pending LOGGED entries")
        # Priority 18: OCC on version (§2.9).
        if ecv != rec["version"]:
            raise err("ERR_STALE_CYCLE_VERSION", "expected_cycle_version does not match")
        # Snapshot consumed (APPROVED only) for rollover before sealing.
        consumed = S.cycle_consumed_hours(rec)
        rec["status"] = "CLOSED"
        rec["closed_at_iso"] = db.clock_iso_logical()
        touch(rec)  # version += 1
        # Mint successor unless client is CLOSED.
        client = db.clients.get(rec["client_id"])
        if client is not None and client["status"] != "CLOSED":
            carry = calc.rollover_carry(
                rec["granted_hours"], rec["rolled_in_hours"], consumed,
                client.get("rollover_cap_hours", 0) or 0,
            )
            successor = {
                "client_id": rec["client_id"],
                "sequence_no": rec["sequence_no"] + 1,
                "status": "OPEN",
                "granted_hours": client["monthly_retainer_hours"],
                "rolled_in_hours": carry,
                "opened_at_iso": db.clock_iso_logical(),
                "closed_at_iso": None,
            }
            stamp_create(successor)
            db.retainer_cycles[successor["id"]] = successor
        return ok(S.retainer_cycle(rec))

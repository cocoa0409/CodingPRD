"""Fee schedule endpoints (PRD 3.1): half-open windows, OCC on Client.version."""

from flask import request

import webbase as base
import services
import store
from errors import ApiError
from timeutil import parse_instant

from datetime import datetime, timezone

_FAR = datetime(9999, 12, 31, tzinfo=timezone.utc)


def register(app):
    @app.route("/appraisal/fee-schedules", methods=["POST"])
    def create_fee_schedule():
        base.auth.require_roles("FirmAdmin")
        body = base.read_body()
        services.require_fields(
            body,
            ["client_id", "complexity_tier", "base_fee_cents", "rush_multiplier_bps",
             "revision_fee_cents", "effective_from", "expected_client_version"],
        )
        tier = services.require_enum(body, "complexity_tier", services.TIERS)
        base_fee = services.require_int(body, "base_fee_cents", strictly_positive=True)
        rush_bps = services.require_int(body, "rush_multiplier_bps", minimum=0, maximum=10000)
        revision_fee = services.require_int(body, "revision_fee_cents", minimum=0)
        effective_from_raw = services.require_instant(body, "effective_from")
        effective_to_raw = None
        if "effective_to" in body and body["effective_to"] is not None:
            effective_to_raw = services.require_instant(body, "effective_to")
        expected_version = body.get("expected_client_version")
        if not isinstance(expected_version, int) or isinstance(expected_version, bool):
            raise ApiError("ERR_VALIDATION", "expected_client_version must be an integer.")

        client = services.get_client(body["client_id"])

        # Ladder rung 5 (state): new fee schedules for a non-ACTIVE client are
        # rejected (PRD 3.1 suspension/termination side effects).
        if client["status"] != "ACTIVE":
            raise ApiError("ERR_CLIENT_NOT_ACTIVE")

        # Ladder rung 6 (OCC, PRD 2.8).
        if expected_version != client["version"]:
            raise ApiError("ERR_STALE_CLIENT_VERSION")

        from_dt = parse_instant(effective_from_raw)
        to_dt = parse_instant(effective_to_raw) if effective_to_raw is not None else None
        if to_dt is not None and not (to_dt > from_dt):
            raise ApiError("ERR_VALIDATION", "effective_to must be after effective_from.")

        # Half-open [from, to) windows per (client, tier) must never overlap
        # (ERR_SCHEDULE_WINDOW_OVERLAP).  The one sanctioned exception is the
        # open-ended prior row: "creating a new row closes the open-ended prior
        # row at the new effective_from" (PRD 3.1), which requires the new
        # effective_from to be strictly after that prior row's start.
        prior_open = None
        for sched in store.fee_schedules.values():
            if sched["client_id"] != client["id"] or sched["complexity_tier"] != tier:
                continue
            s_from = sched["_effective_from_dt"]
            s_to = sched["_effective_to_dt"]
            if s_to is None and from_dt > s_from:
                prior_open = sched
                continue
            # Generic half-open intersection: [from,to) x [s_from,s_to).
            if from_dt < (s_to if s_to is not None else _FAR) and s_from < (to_dt if to_dt is not None else _FAR):
                raise ApiError("ERR_SCHEDULE_WINDOW_OVERLAP")

        if prior_open is not None:
            prior_open["effective_to"] = effective_from_raw
            prior_open["_effective_to_dt"] = from_dt
            store.touch(prior_open)

        row = store.new_row(
            store.fee_schedules,
            client_id=client["id"],
            complexity_tier=tier,
            base_fee_cents=base_fee,
            rush_multiplier_bps=rush_bps,
            revision_fee_cents=revision_fee,
            effective_from=effective_from_raw,
            effective_to=effective_to_raw,
            _effective_from_dt=from_dt,
            _effective_to_dt=to_dt,
        )
        # Creating a schedule mutates the client record: version advances by 1.
        store.touch(client)
        return base.obj(row, 201)

    @app.route("/appraisal/fee-schedules/<schedule_id>", methods=["GET"])
    def get_fee_schedule(schedule_id):
        base.auth.require_roles("FirmAdmin")
        return base.obj(services.get_fee_schedule(schedule_id))

    @app.route("/appraisal/fee-schedules", methods=["GET"])
    def list_fee_schedules():
        base.auth.require_roles("FirmAdmin")
        client_id = request.args.get("client_id")
        tier = request.args.get("complexity_tier")
        rows = store.fee_schedules.values()
        if client_id is not None:
            rows = [r for r in rows if r["client_id"] == client_id]
        if tier is not None:
            rows = [r for r in rows if r["complexity_tier"] == tier]
        return base.listing(rows, request.args)

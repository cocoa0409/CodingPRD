"""IndexObservation endpoints (PRD §3.3) — append-only log, detection, annulment."""

from datetime import date

from flask import Blueprint, request

import db
from errors import (
    err, ERR_INVALID_REQUEST, ERR_PROGRAM_NOT_ACTIVE, ERR_INDEX_SUSPENDED,
    ERR_STATION_OFFLINE, ERR_CROSS_REFERENCE_INVALID, ERR_WINDOW_OUT_OF_COVERAGE,
    ERR_DUPLICATE_OBSERVATION, ERR_OBSERVATION_NOT_FOUND,
    ERR_SUPERSESSION_CHAIN_BROKEN,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from routes.common import (
    body, require_fields, pagination_params, paginate, sorted_by_created,
    get_program, get_index_in_program,
)
from services import domain, calc

bp = Blueprint("observations", __name__)


def _apply_post_ingestion_consequences(index: dict, window_end_date: str):
    """After an accepted ingestion, recompute the blend for the window and apply
    the automatic consequences (PRD §3.3):
      - breach >= tier 1 and no event exists for (index, window) -> create DETECTED event
      - VERIFIED event exists and recomputed max_tier drops to 0 -> ANNULLED +
        compensation cascade on GENERATED/ADJUSTED claims (PRD §3.6)
    Also handles a DETECTED event whose blend changed (values are recomputed at
    verify time, so no mutation needed here beyond creation/annulment).
    """
    blended, method = calc.compute_blend(index, window_end_date)
    max_tier = calc.compute_max_tier(index, blended)

    existing = [e for e in db.trigger_events.values()
                if e["index_definition_id"] == index["id"]
                and e["window_end_date"] == window_end_date]

    if not existing:
        if max_tier >= 1:
            ev = domain.stamp_new({
                "index_definition_id": index["id"],
                "program_id": index["program_id"],
                "window_end_date": window_end_date,
                "blended_index_value": blended,
                "max_tier_breached": max_tier,
                "verification_method": method,
                "status": "DETECTED",
            })
            db.trigger_events[ev["id"]] = ev
        return

    for ev in existing:
        if ev["status"] == "VERIFIED" and max_tier == 0:
            # Annulment cascade (PRD §3.6)
            ev["status"] = "ANNULLED"
            ev["blended_index_value"] = blended
            ev["max_tier_breached"] = 0
            domain.touch(ev)
            affected_policies = set()
            for c in db.claims.values():
                if c["trigger_event_id"] == ev["id"] and c["status"] in ("GENERATED", "ADJUSTED"):
                    c["status"] = "DECLINED"
                    domain.touch(c)
                    affected_policies.add(c["policy_id"])
            for pid in affected_policies:
                pol = db.policies.get(pid)
                if pol:
                    domain.reevaluate_policy_posture(pol)
        elif ev["status"] in ("DETECTED", "UNDER_REVIEW"):
            # Keep stored blend/tier fresh for reads; verify recomputes anyway.
            if blended is not None:
                ev["blended_index_value"] = blended
                ev["max_tier_breached"] = max_tier
                ev["verification_method"] = method
                domain.touch(ev)


@bp.post("/programs/<programId>/index-definitions/<indexId>/observations")
def ingest_observation(programId, indexId):
    require_roles("DataOperations")
    prog = get_program(programId)
    idx = get_index_in_program(prog, indexId)
    data = body()
    require_fields(data, ["station_id", "window_end_date", "measured_value"])

    # Priority 4: program must be ACTIVE
    if prog["status"] != "ACTIVE":
        raise err(ERR_PROGRAM_NOT_ACTIVE, 409, "Operation requires program status ACTIVE")
    # Index state guard
    if idx["status"] in ("SUSPENDED", "DECOMMISSIONED"):
        raise err(ERR_INDEX_SUSPENDED, 409,
                  "Observation rejected: index is SUSPENDED or DECOMMISSIONED")

    station_id = data["station_id"]
    station = db.stations.get(station_id)
    # Cross-reference: station must exist and belong to the program (priority 7)
    if not station or station["program_id"] != prog["id"]:
        raise err(ERR_CROSS_REFERENCE_INVALID, 422,
                  "Referenced station belongs to a different program")
    # Station state guard
    if station["status"] in ("OFFLINE", "DECOMMISSIONED"):
        raise err(ERR_STATION_OFFLINE, 409,
                  "Observation rejected: station is OFFLINE or DECOMMISSIONED")

    window_end_date = data["window_end_date"]
    if not isinstance(window_end_date, str):
        raise err(ERR_INVALID_REQUEST, 400, "window_end_date must be a YYYY-MM-DD string")
    try:
        wed = date.fromisoformat(window_end_date)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, 400, "window_end_date must be YYYY-MM-DD")
    # Priority 8: temporal — window must not lie in the future vs logical clock
    if wed > db.get_logical_clock().date():
        raise err(ERR_WINDOW_OUT_OF_COVERAGE, 422,
                  "Observation window in the future")

    measured_value = data["measured_value"]
    if not isinstance(measured_value, (int, float)):
        raise err(ERR_INVALID_REQUEST, 400, "measured_value must be a number")

    supersedes_id = data.get("supersedes_observation_id")

    # Dedupe/revision rules (priority 9)
    existing_for_pair = [o for o in db.observations.values()
                         if o["index_definition_id"] == idx["id"]
                         and o["station_id"] == station_id
                         and o["window_end_date"] == window_end_date]
    current_effective = next((o for o in existing_for_pair if o["is_effective"]), None)

    if supersedes_id is None:
        if existing_for_pair:
            raise err(ERR_DUPLICATE_OBSERVATION, 409,
                      "Observation for (station_id, window_end_date) already exists and supersedes_observation_id not provided")
    else:
        target = db.observations.get(supersedes_id)
        if not target:
            raise err(ERR_OBSERVATION_NOT_FOUND, 404,
                      "supersedes_observation_id does not reference an existing observation")
        if not current_effective or current_effective["id"] != supersedes_id:
            raise err(ERR_SUPERSESSION_CHAIN_BROKEN, 409,
                      "supersedes_observation_id does not point at the currently-effective observation for (station_id, window_end_date)")

    # Create the observation (append-only: id + created_at only, PRD §2.5)
    obs = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "index_definition_id": idx["id"],
        "station_id": station_id,
        "window_end_date": window_end_date,
        "measured_value": measured_value,
        "sequence_no": db.next_observation_seq(idx["id"]),
        "supersedes_observation_id": supersedes_id,
        "is_effective": True,
    }
    db.observations[obs["id"]] = obs
    if supersedes_id is not None:
        # Flip the superseded row's effectiveness (the log row itself is not
        # versioned; is_effective is a computed view flag).
        db.observations[supersedes_id]["is_effective"] = False

    _apply_post_ingestion_consequences(idx, window_end_date)
    return success_object(domain.serialize(obs), 201)


@bp.get("/programs/<programId>/index-definitions/<indexId>/observations")
def list_observations(programId, indexId):
    require_roles(*ALL_ROLES)
    prog = get_program(programId)
    idx = get_index_in_program(prog, indexId)
    limit, offset = pagination_params()
    wed = request.args.get("window_end_date")
    sid = request.args.get("station_id")
    items = [o for o in db.observations.values() if o["index_definition_id"] == idx["id"]]
    if wed is not None:
        items = [o for o in items if o["window_end_date"] == wed]
    if sid is not None:
        items = [o for o in items if o["station_id"] == sid]
    items = sorted(items, key=lambda o: (o["sequence_no"], o["created_at"]))
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


@bp.get("/programs/observations")
def list_observations_flat():
    require_roles(*ALL_ROLES)
    limit, offset = pagination_params()
    index_id = request.args.get("index_definition_id")
    station_id = request.args.get("station_id")
    wed = request.args.get("window_end_date")
    items = list(db.observations.values())
    if index_id is not None:
        items = [o for o in items if o["index_definition_id"] == index_id]
    if station_id is not None:
        items = [o for o in items if o["station_id"] == station_id]
    if wed is not None:
        items = [o for o in items if o["window_end_date"] == wed]
    items = sorted(items, key=lambda o: (o["created_at"], o["id"]))
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


@bp.get("/programs/observations/<observationId>")
def get_observation_flat(observationId):
    require_roles(*ALL_ROLES)
    obs = db.observations.get(observationId)
    if not obs:
        raise err(ERR_OBSERVATION_NOT_FOUND, 404, "Observation id does not exist")
    return success_object(domain.serialize(obs))

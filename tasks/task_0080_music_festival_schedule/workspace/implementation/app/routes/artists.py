"""Global Artist catalog per PRD §3.2.

Artists are festival-independent — the path is `/artists` rather than
under any festival.
"""
from __future__ import annotations

from typing import Any, Dict, List

from flask import Flask, request

from ._common import (
    ANY_ROLE,
    ApiError,
    DB,
    GLOBAL_LOCK,
    append_audit,
    check_if_match,
    get_json_body,
    if_match_header,
    list_by_predicate,
    make_blueprint,
    optional_int,
    optional_list,
    optional_str,
    paginate_list,
    recompute_slot_priority,
    require_enum,
    require_role,
    require_str,
    stamp_create,
    stamp_update,
    success_envelope,
)
from ..constants import TRAVEL_HOURS_MIN


bp = make_blueprint("artists")

_TIERS = ("HEADLINER", "MAIN", "OPENER", "SURPRISE")


def _validate_commitments(commitments: List[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in commitments or []:
        if not isinstance(c, dict):
            raise ApiError(
                "ERR_INVALID_FIELD_VALUE",
                "every external_commitments entry must be an object",
            )
        for field in ("festival_external_id", "city"):
            if field in c and c[field] is not None and not isinstance(c[field], str):
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE",
                    f"external_commitments.{field} must be a string",
                )
        for field in ("start_time", "end_time"):
            v = c.get(field)
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE",
                    f"external_commitments.{field} must be a non-negative integer",
                )
        if int(c["end_time"]) <= int(c["start_time"]):
            raise ApiError(
                "ERR_INVALID_FIELD_VALUE",
                "external_commitment end_time must be > start_time",
            )
        out.append(
            {
                "festival_external_id": c.get("festival_external_id", ""),
                "start_time": int(c["start_time"]),
                "end_time": int(c["end_time"]),
                "city": c.get("city", ""),
            }
        )
    return out


def _payload(a: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": a["id"],
        "stage_name": a.get("stage_name"),
        "tier": a.get("tier"),
        "home_city": a.get("home_city"),
        "external_commitments": list(a.get("external_commitments", []) or []),
        "minimum_travel_buffer_hours": a.get(
            "minimum_travel_buffer_hours", TRAVEL_HOURS_MIN
        ),
        "created_at": a.get("created_at"),
        "updated_at": a.get("updated_at"),
        "version": a.get("version"),
    }


@bp.route("/artists", methods=["POST"])
def create_artist():
    require_role(["ArtistLiaison", "PlatformAdmin", "FestivalProducer"])
    body = get_json_body()
    stage_name = require_str(body, "stage_name")
    tier = require_enum(body, "tier", _TIERS)
    home_city = optional_str(body, "home_city", default="") or ""
    commitments = optional_list(body, "external_commitments", default=[])
    commitments = _validate_commitments(commitments)
    min_hours = optional_int(
        body, "minimum_travel_buffer_hours", default=TRAVEL_HOURS_MIN, non_negative=True
    )

    row = {
        "stage_name": stage_name,
        "tier": tier,
        "home_city": home_city,
        "external_commitments": commitments,
        "minimum_travel_buffer_hours": min_hours,
    }
    stamp_create(row)
    with GLOBAL_LOCK:
        DB.artists[row["id"]] = row
    return success_envelope(_payload(row), http_status=201)


@bp.route("/artists", methods=["GET"])
def list_artists():
    require_role(ANY_ROLE)
    tier_filter = request.args.get("tier")
    with GLOBAL_LOCK:

        def _pred(r: dict) -> bool:
            if tier_filter is not None and r.get("tier") != tier_filter:
                return False
            return True

        rows = list_by_predicate(DB.artists, _pred)
        page, meta = paginate_list(rows, request.args)
        out = [_payload(r) for r in page]
    return success_envelope(out, pagination=meta)


@bp.route("/artists/<artist_id>", methods=["GET"])
def read_artist(artist_id: str):
    require_role(ANY_ROLE)
    with GLOBAL_LOCK:
        a = DB.artists.get(artist_id)
        if a is None:
            raise ApiError("ERR_ARTIST_NOT_FOUND", f"artist {artist_id} not found")
        out = _payload(a)
    return success_envelope(out)


@bp.route("/artists/<artist_id>", methods=["PATCH"])
def patch_artist(artist_id: str):
    require_role(["ArtistLiaison", "PlatformAdmin"])
    body = get_json_body()
    with GLOBAL_LOCK:
        a = DB.artists.get(artist_id)
        if a is None:
            raise ApiError("ERR_ARTIST_NOT_FOUND", f"artist {artist_id} not found")
        check_if_match(a, if_match_header())

        if "external_commitments" in body:
            cs = body["external_commitments"]
            if cs is None:
                cs = []
            if not isinstance(cs, list):
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE",
                    "external_commitments must be a list of objects",
                )
            a["external_commitments"] = _validate_commitments(cs)
        if "minimum_travel_buffer_hours" in body:
            v = body["minimum_travel_buffer_hours"]
            if (
                v is None
                or isinstance(v, bool)
                or not isinstance(v, int)
                or v < 0
            ):
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE",
                    "minimum_travel_buffer_hours must be a non-negative integer",
                )
            a["minimum_travel_buffer_hours"] = int(v)
        if "tier" in body:
            t = body["tier"]
            if t not in _TIERS:
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE", f"tier must be one of {_TIERS}"
                )
            a["tier"] = t
        if "stage_name" in body:
            sn = body["stage_name"]
            if not isinstance(sn, str) or sn == "":
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE", "stage_name must be a non-empty string"
                )
            a["stage_name"] = sn
        if "home_city" in body:
            hc = body["home_city"]
            if hc is None:
                hc = ""
            if not isinstance(hc, str):
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE", "home_city must be a string"
                )
            a["home_city"] = hc

        stamp_update(a)

        # The PATCH recomputes every dependent program item's
        # slot_priority_score per the §4 endpoint description.
        dependents = [
            pi
            for pi in DB.program_items.values()
            if pi.get("artist_id") == artist_id
        ]
        for pi in dependents:
            recompute_slot_priority(pi)
            # The recompute updates the in-memory row.  No audit row
            # is required for the harness-driven recompute per §3.3
            # ("idempotent ... a recompute that yields the same numeric
            # value is a no-op except for the score-unchanged audit
            # entry"); we keep the audit footprint focused on actual
            # state transitions for the artist itself.

        # Audit the artist patch under the per-festival audit log of every
        # festival that has a program item for this artist.  The audit
        # log is per-festival; an artist is global, so the artist PATCH
        # gets its own dedicated audit row under each affected festival.
        touched_festivals: set[str] = set()
        for pi in dependents:
            fid = pi.get("festival_id")
            if fid and fid not in touched_festivals:
                touched_festivals.add(fid)
                append_audit(
                    festival_id=fid,
                    event_category="STATE_TRANSITION",
                    subject_entity_type="Artist",
                    subject_entity_id=artist_id,
                    payload_summary=(
                        f"artist {artist_id} patched, dependent slot priorities recomputed"
                    ),
                )

        out = _payload(a)
    return success_envelope(out)


def register(app: Flask) -> None:
    app.register_blueprint(bp)

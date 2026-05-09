"""Actor scheduling conflict detection (within and across productions)."""
from datetime import timedelta

from db import store
from clock import parse_iso8601


SAME_ZONE_BUFFER_MIN = 60
CROSS_ZONE_BUFFER_MIN = 240


def _required_buffer(prior_zone, next_zone) -> int:
    return SAME_ZONE_BUFFER_MIN if prior_zone == next_zone else CROSS_ZONE_BUFFER_MIN


def _intervals_conflict(a_start, a_end, a_zone, b_start, b_end, b_zone) -> bool:
    """Return True if reservations conflict.

    Conflict iff next.start_at < prior.end_at + required_buffer (after sorting).
    Overlap is implicit in this rule because a_start < a_end.
    """
    # Order so 'a' is the earlier-starting reservation
    if a_start <= b_start:
        prior_start, prior_end, prior_zone = a_start, a_end, a_zone
        next_start, next_end, next_zone = b_start, b_end, b_zone
    else:
        prior_start, prior_end, prior_zone = b_start, b_end, b_zone
        next_start, next_end, next_zone = a_start, a_end, a_zone

    buf = _required_buffer(prior_zone, next_zone)
    threshold = prior_end + timedelta(minutes=buf)
    return next_start < threshold


def actor_signed_role_ids_for_production(actor_id, production_id):
    """List of role ids for which this actor is signed within a production."""
    out = []
    for r in store.roles.values():
        if (
            r.get("production_id") == production_id
            and r.get("casting_status") == "SIGNED"
            and r.get("signed_actor_id") == actor_id
        ):
            out.append(r["id"])
    return out


def actor_signed_role_ids_all(actor_id):
    """List of (role_id, production_id) where the actor is currently SIGNED."""
    out = []
    for r in store.roles.values():
        if r.get("casting_status") == "SIGNED" and r.get("signed_actor_id") == actor_id:
            out.append((r["id"], r["production_id"]))
    return out


def _scenes_with_role(production_id, role_id, exclude_scene_id=None):
    out = []
    for s in store.scenes.values():
        if s["production_id"] != production_id:
            continue
        if exclude_scene_id is not None and s["id"] == exclude_scene_id:
            continue
        if role_id in (s.get("required_actor_role_ids") or []):
            out.append(s)
    return out


def _reservation_for_scene(scene):
    """Return the active LocationReservation linked to a scene, if any.

    A scene becomes attached to a reservation through the reserve.scene_id
    pointer. We also check status to be HELD/CONFIRMED/RESCHEDULING (active).
    """
    for r in store.location_reservations.values():
        if r.get("scene_id") == scene["id"] and r.get("status") in {"HELD", "CONFIRMED", "RESCHEDULING"}:
            return r
    return None


def _location_zone(location_id):
    loc = store.locations.get(location_id)
    return loc["zone"] if loc else None


def check_actor_callsheet_conflict_within_production(
    production_id, scene, candidate_reservation
):
    """For every signed role in this scene's required_actor_role_ids, ensure
    no other scene of THE SAME production featuring the same signed actor
    overlaps or violates the travel buffer with candidate_reservation."""
    # Build map: signed actor -> [other reservations in this production]
    cand_start = parse_iso8601(candidate_reservation["start_at"])
    cand_end = parse_iso8601(candidate_reservation["end_at"])
    cand_zone = _location_zone(candidate_reservation["location_id"])
    role_ids = scene.get("required_actor_role_ids") or []

    for rid in role_ids:
        role = store.roles.get(rid)
        if not role or role.get("casting_status") != "SIGNED":
            continue
        signed_actor_id = role.get("signed_actor_id")
        if not signed_actor_id:
            continue
        # Find every other scene in this production that features this actor (any of
        # this actor's signed roles)
        actor_role_ids = actor_signed_role_ids_for_production(signed_actor_id, production_id)
        for arole_id in actor_role_ids:
            other_scenes = _scenes_with_role(production_id, arole_id, exclude_scene_id=scene["id"])
            for os in other_scenes:
                # Skip terminal scenes
                if os.get("status") in {"OMITTED"}:
                    continue
                other_res = _reservation_for_scene(os)
                if not other_res:
                    continue
                if other_res["id"] == candidate_reservation["id"]:
                    continue
                other_start = parse_iso8601(other_res["start_at"])
                other_end = parse_iso8601(other_res["end_at"])
                other_zone = _location_zone(other_res["location_id"])
                if _intervals_conflict(
                    cand_start, cand_end, cand_zone, other_start, other_end, other_zone
                ):
                    return True
    return False


def check_actor_cross_project_conflict(actor_id, candidate_reservation, *,
                                       exclude_production_id=None,
                                       exclude_scene_id=None):
    """Check whether the actor (signed elsewhere) has any conflicting
    reservations across other ACTIVE productions."""
    cand_start = parse_iso8601(candidate_reservation["start_at"])
    cand_end = parse_iso8601(candidate_reservation["end_at"])
    cand_zone = _location_zone(candidate_reservation["location_id"])

    for r in store.roles.values():
        if r.get("casting_status") != "SIGNED":
            continue
        if r.get("signed_actor_id") != actor_id:
            continue
        prod = store.productions.get(r["production_id"])
        if not prod:
            continue
        if prod["status"] not in {"PLANNING", "IN_PRODUCTION"}:
            continue
        if exclude_production_id is not None and r["production_id"] == exclude_production_id:
            continue
        # For every scene in this other production featuring this role, check overlap
        for os in store.scenes.values():
            if os["production_id"] != r["production_id"]:
                continue
            if exclude_scene_id is not None and os["id"] == exclude_scene_id:
                continue
            if r["id"] not in (os.get("required_actor_role_ids") or []):
                continue
            if os.get("status") in {"OMITTED"}:
                continue
            other_res = _reservation_for_scene(os)
            if not other_res:
                continue
            if other_res["id"] == candidate_reservation["id"]:
                continue
            other_start = parse_iso8601(other_res["start_at"])
            other_end = parse_iso8601(other_res["end_at"])
            other_zone = _location_zone(other_res["location_id"])
            if _intervals_conflict(
                cand_start, cand_end, cand_zone, other_start, other_end, other_zone
            ):
                return True
    return False


def check_cross_project_conflict_for_role_sign(production_id, role, signed_actor_id):
    """At role-sign time: for every scene of this production that features the
    role and has an active reservation, ensure the candidate actor has no
    cross-project conflicts."""
    role_id = role["id"]
    for s in store.scenes.values():
        if s["production_id"] != production_id:
            continue
        if role_id not in (s.get("required_actor_role_ids") or []):
            continue
        if s.get("status") in {"OMITTED"}:
            continue
        res = _reservation_for_scene(s)
        if not res:
            continue
        if check_actor_cross_project_conflict(
            signed_actor_id, res, exclude_production_id=production_id
        ):
            return True
    # Also check same-production conflict between scene reservations of this role:
    # if signing this actor would conflict with another already-signed scene of
    # the actor in the same production, that's an ERR_ACTOR_CALLSHEET_CONFLICT.
    return False


def check_callsheet_conflict_for_role_sign(production_id, role, signed_actor_id):
    """At role-sign time: ensure that signing this actor doesn't create a
    same-production conflict between the scenes featuring this role and other
    scenes of any other roles where the same actor is already signed."""
    role_id = role["id"]
    other_role_ids = actor_signed_role_ids_for_production(signed_actor_id, production_id)
    if role_id in other_role_ids:
        other_role_ids.remove(role_id)
    if not other_role_ids:
        return False
    for s in store.scenes.values():
        if s["production_id"] != production_id:
            continue
        if role_id not in (s.get("required_actor_role_ids") or []):
            continue
        if s.get("status") in {"OMITTED"}:
            continue
        res = _reservation_for_scene(s)
        if not res:
            continue
        cand_start = parse_iso8601(res["start_at"])
        cand_end = parse_iso8601(res["end_at"])
        cand_zone = _location_zone(res["location_id"])
        # Check against every scene of any of the other_role_ids
        for orid in other_role_ids:
            for os in store.scenes.values():
                if os["production_id"] != production_id:
                    continue
                if os["id"] == s["id"]:
                    continue
                if orid not in (os.get("required_actor_role_ids") or []):
                    continue
                if os.get("status") in {"OMITTED"}:
                    continue
                ores = _reservation_for_scene(os)
                if not ores:
                    continue
                ostart = parse_iso8601(ores["start_at"])
                oend = parse_iso8601(ores["end_at"])
                ozone = _location_zone(ores["location_id"])
                if _intervals_conflict(cand_start, cand_end, cand_zone, ostart, oend, ozone):
                    return True
    return False

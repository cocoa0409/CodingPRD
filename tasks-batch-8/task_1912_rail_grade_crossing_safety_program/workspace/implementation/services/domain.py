"""Store-dependent derived-field recomputation and cascade side effects.

Version discipline (SCAFFOLD conventions / PRD §2.6): recomputes cascading from
other entities' actions refresh updated_at but NEVER increment version.
"""
from db import now_iso, store
from services import calcs

COUNTED_INCIDENT_STATUSES = ("FINDINGS_ISSUED", "FRA_SUBMITTED", "CLOSED")


def _five_years_before(dt):
    try:
        return dt.replace(year=dt.year - 5)
    except ValueError:
        # Feb 29 -> Feb 28
        return dt.replace(year=dt.year - 5, day=28)


def live_incident_count_5yr(crossing_id):
    """calculations.incident_count_5yr: status-filtered, 5-year trailing window
    against the logical clock, both bounds inclusive."""
    lower = _five_years_before(store.clock)
    now = store.clock
    count = 0
    for inc in store.incidents.values():
        if inc["crossing_id"] != crossing_id:
            continue
        if inc["status"] not in COUNTED_INCIDENT_STATUSES:
            continue
        occurred = inc["_occurred_dt"]
        if lower <= occurred <= now:
            count += 1
    return count


def recompute_crossing_risk(crossing):
    """Recompute exposure, projected exposure, hazard, review-due on a crossing.

    Returns (old_hazard, new_hazard) so callers can run the staleness cascade
    only when the live hazard actually changed.
    """
    old_hazard = crossing["hazard_score"]
    crossing["exposure_index"] = calcs.exposure_snapshot(
        crossing["annual_train_count"], crossing["aadt"]
    )
    crossing["projected_exposure_index"] = calcs.exposure_projected(
        crossing["annual_train_count"], crossing["aadt"]
    )
    crossing["hazard_score"] = calcs.hazard_score(
        crossing["exposure_index"],
        live_incident_count_5yr(crossing["id"]),
        crossing["school_bus_count"],
        crossing["sight_distance_rating"],
        crossing["warning_device_class"],
    )
    crossing["diagnostic_review_due"] = _compute_review_due(crossing)
    return old_hazard, crossing["hazard_score"]


def _compute_review_due(crossing):
    if crossing["exposure_index"] >= calcs.EXPOSURE_REVIEW_THRESHOLD:
        return True
    for inc in store.incidents.values():
        if (
            inc["crossing_id"] == crossing["id"]
            and inc["investigation_track"] == "FIELD_INVESTIGATION"
        ):
            return True
    return False


def recompute_eligible_demand(program):
    """eligible_demand_cents = sum of estimated_cost_cents over ELIGIBLE projects.

    Derived recompute: refreshes updated_at on change, never bumps version.
    """
    total = sum(
        p["estimated_cost_cents"]
        for p in store.projects.values()
        if p["program_id"] == program["id"] and p["status"] == "ELIGIBLE"
    )
    if program["eligible_demand_cents"] != total:
        program["eligible_demand_cents"] = total
        program["updated_at"] = now_iso()


def run_hazard_staleness_cascade(crossing, old_hazard):
    """PRD §3.4: any hazard recompute that changes the value reverts the
    crossing's ELIGIBLE projects to PROPOSED with score_stale set, and each
    affected program's eligible_demand_cents recomputes."""
    if crossing["hazard_score"] == old_hazard:
        return
    for project in store.projects.values():
        if project["crossing_id"] == crossing["id"] and project["status"] == "ELIGIBLE":
            project["status"] = "PROPOSED"
            project["score_stale"] = True
            project["updated_at"] = now_iso()
            program = store.programs.get(project["program_id"])
            if program is not None:
                recompute_eligible_demand(program)


def compute_zone_riwh(zone):
    """Live riwh (pre, post) over the zone's current MEMBER rows, or None when
    no members remain."""
    members = [
        m
        for m in store.qz_members.values()
        if m["quiet_zone_application_id"] == zone["id"] and m["membership_status"] == "MEMBER"
    ]
    if not members:
        return None
    pairs = []
    for m in members:
        crossing = store.crossings.get(m["crossing_id"])
        if crossing is None:
            continue
        pairs.append((crossing["hazard_score"], m["ssm_codes"]))
    if not pairs:
        return None
    return calcs.riwh_indices(pairs)


def closure_cascade(crossing):
    """PRD §3.5 closure cascade after a crossing reaches CLOSED.

    - QuietZoneCrossing MEMBER rows for the crossing -> REMOVED
    - each affected zone recomputes riwh_post_ssm over remaining MEMBER rows;
      EFFECTIVE zones suspend when no members remain or riwh_post_ssm > NSRT
    - non-terminal work orders (PLANNED | FLAGGING_CONFIRMED) -> CANCELLED
    - interconnections in DRAFT | TIMING_VERIFIED | COMMISSIONED -> DECOMMISSIONED
    """
    affected_zone_ids = []
    for member in store.qz_members.values():
        if member["crossing_id"] == crossing["id"] and member["membership_status"] == "MEMBER":
            member["membership_status"] = "REMOVED"
            affected_zone_ids.append(member["quiet_zone_application_id"])

    for zone_id in dict.fromkeys(affected_zone_ids):
        zone = store.qz_applications.get(zone_id)
        if zone is None:
            continue
        recomputed = compute_zone_riwh(zone)
        if recomputed is not None:
            zone["riwh_post_ssm"] = recomputed[1]
        if zone["status"] == "EFFECTIVE":
            if recomputed is None or recomputed[1] > calcs.NSRT:
                zone["status"] = "SUSPENDED"
        zone["updated_at"] = now_iso()

    for order in store.work_orders.values():
        if order["crossing_id"] == crossing["id"] and order["status"] in ("PLANNED", "FLAGGING_CONFIRMED"):
            order["status"] = "CANCELLED"
            order["updated_at"] = now_iso()

    for ic in store.interconnections.values():
        if ic["crossing_id"] == crossing["id"] and ic["status"] in ("DRAFT", "TIMING_VERIFIED", "COMMISSIONED"):
            ic["status"] = "DECOMMISSIONED"
            ic["updated_at"] = now_iso()

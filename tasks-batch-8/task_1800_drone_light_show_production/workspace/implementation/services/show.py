"""Show aggregate helpers: serialization, posture, cascades."""

from datetime import timedelta

from db import DB, parse_dt, wall_created_at, clock_now
from services import calc


# --------------------------------------------------------------------------
# serialization

def touch(entity):
    entity["updated_at"] = wall_created_at()
    entity["version"] = entity.get("version", 1) + 1


def serialize_site(s):
    return {
        "id": s["id"], "name": s["name"], "latitude": s["latitude"],
        "longitude": s["longitude"], "ground_length_m": s["ground_length_m"],
        "ground_width_m": s["ground_width_m"],
        "site_max_wind_kt": s["site_max_wind_kt"],
        "site_max_gust_kt": s["site_max_gust_kt"],
        "site_max_altitude_ft": s["site_max_altitude_ft"],
        "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_show(s):
    return {
        "id": s["id"], "site_id": s["site_id"], "name": s["name"],
        "window_start": s["window_start"], "window_end": s["window_end"],
        "drone_count_planned": s["drone_count_planned"],
        "backup_window_start": s["backup_window_start"],
        "backup_window_end": s["backup_window_end"],
        "backup_consumed": s["backup_consumed"],
        "lifecycle_status": s["lifecycle_status"],
        "payment_status": s["payment_status"],
        "contract_value_cents": s["contract_value_cents"],
        "deposit_cents": s["deposit_cents"],
        "balance_cents": s["balance_cents"],
        "paid_total_cents": s["paid_total_cents"],
        "refunded_total_cents": s["refunded_total_cents"],
        "cancellation_status": s["cancellation_status"],
        "cancelled_at": s["cancelled_at"],
        "cancellation_tier": s["cancellation_tier"],
        "refund_due_cents": s["refund_due_cents"],
        "pinned_design_id": s["pinned_design_id"],
        "pinned_safety_config_id": s["pinned_safety_config_id"],
        "pinned_authorization_id": s["pinned_authorization_id"],
        "assigned_count": s["assigned_count"],
        "readiness_posture": s["readiness_posture"],
        "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_authorization(a):
    return {
        "id": a["id"], "show_event_id": a["show_event_id"],
        "window_start": a["window_start"], "window_end": a["window_end"],
        "altitude_ceiling_ft": a["altitude_ceiling_ft"],
        "waiver_types": a["waiver_types"],
        "status": a["status"],
        "decided_at": a["decided_at"], "decided_by": a["decided_by"],
        "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_design(d):
    return {
        "id": d["id"], "show_event_id": d["show_event_id"],
        "design_version_no": d["design_version_no"],
        "drone_count": d["drone_count"],
        "max_altitude_ft": d["max_altitude_ft"],
        "duration_sec": d["duration_sec"],
        "min_separation_m": d["min_separation_m"],
        "status": d["status"],
        "created_at": d["created_at"], "updated_at": d["updated_at"],
        "version": d["version"],
    }


def serialize_simulation_run(r):
    return {
        "id": r["id"], "show_design_id": r["show_design_id"],
        "min_separation_observed_m": r["min_separation_observed_m"],
        "battery_draw_pct": r["battery_draw_pct"],
        "max_speed_mps": r["max_speed_mps"],
        "verdict": r["verdict"],
        "created_at": r["created_at"],
    }


def serialize_safety_config(c):
    return {
        "id": c["id"], "show_event_id": c["show_event_id"],
        "geofence_radius_m": c["geofence_radius_m"],
        "altitude_hard_ceiling_ft": c["altitude_hard_ceiling_ft"],
        "lost_link_action": c["lost_link_action"],
        "geofence_breach_action": c["geofence_breach_action"],
        "battery_rtl_threshold_pct": c["battery_rtl_threshold_pct"],
        "status": c["status"],
        "created_by_user_id": c["created_by_user_id"],
        "approved_by_user_id": c["approved_by_user_id"],
        "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_drone(d):
    return {
        "id": d["id"], "serial_number": d["serial_number"],
        "model": d["model"], "charge_pct": d["charge_pct"],
        "battery_cycle_count": d["battery_cycle_count"],
        "status": d["status"],
        "created_at": d["created_at"], "updated_at": d["updated_at"],
        "version": d["version"],
    }


def serialize_charge_bay(b):
    return {
        "id": b["id"], "site_id": b["site_id"],
        "bay_code": b["bay_code"], "port_count": b["port_count"],
        "created_at": b["created_at"], "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_charge_session(s):
    return {
        "id": s["id"], "drone_id": s["drone_id"],
        "charge_bay_id": s["charge_bay_id"],
        "charge_from_pct": s["charge_from_pct"],
        "charge_to_pct": s["charge_to_pct"],
        "started_at": s["started_at"], "ended_at": s["ended_at"],
        "status": s["status"],
        "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_assignment(a):
    return {
        "id": a["id"], "show_event_id": a["show_event_id"],
        "drone_id": a["drone_id"],
        "grid_row": a["grid_row"], "grid_col": a["grid_col"],
        "status": a["status"],
        "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_weather_reading(r):
    return {
        "id": r["id"], "site_id": r["site_id"],
        "recorded_at": r["recorded_at"],
        "wind_speed_kt": r["wind_speed_kt"], "gust_kt": r["gust_kt"],
        "precip_mm_hr": r["precip_mm_hr"], "temperature_c": r["temperature_c"],
        "created_at": r["created_at"],
    }


def serialize_evaluation(e):
    return {
        "id": e["id"], "show_event_id": e["show_event_id"],
        "evaluated_at": e["evaluated_at"],
        "verdict": e["verdict"], "reason_codes": e["reason_codes"],
        "effective_wind_limit_kt": e["effective_wind_limit_kt"],
        "effective_gust_limit_kt": e["effective_gust_limit_kt"],
        "status": e["status"],
        "certified_at": e["certified_at"],
        "certified_by_user_id": e["certified_by_user_id"],
        "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_incident(r):
    return {
        "id": r["id"], "show_event_id": r["show_event_id"],
        "drone_id": r["drone_id"],
        "severity": r["severity"], "description": r["description"],
        "source": r["source"], "status": r["status"],
        "filed_by_user_id": r["filed_by_user_id"],
        "closed_by_user_id": r["closed_by_user_id"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_flight_log(f):
    return {
        "id": f["id"], "show_event_id": f["show_event_id"],
        "drone_id": f["drone_id"],
        "battery_consumed_pct": f["battery_consumed_pct"],
        "max_altitude_reached_ft": f["max_altitude_reached_ft"],
        "max_deviation_m": f["max_deviation_m"],
        "flag_status": f["flag_status"],
        "created_at": f["created_at"],
    }


# --------------------------------------------------------------------------
# posture

def latest_simulation_for_design(design_id):
    """Most recent SimulationRun by created_at; ties broken by creation order
    (later-created wins). With a frozen logical clock, created_at ties are
    common, so the insertion index is the operative tie-break."""
    best = None
    best_idx = -1
    for idx, rid in enumerate(DB.insertion_order["simulation_runs"]):
        r = DB.simulation_runs[rid]
        if r["show_design_id"] != design_id:
            continue
        if best is None:
            best, best_idx = r, idx
            continue
        if (parse_dt(r["created_at"]), idx) >= (parse_dt(best["created_at"]), best_idx):
            best, best_idx = r, idx
    return best


def auth_covers_show(auth, show):
    a_start = parse_dt(auth["window_start"])
    a_end = parse_dt(auth["window_end"])
    s_start = parse_dt(show["window_start"])
    s_end = parse_dt(show["window_end"])
    if not (a_start <= s_start and a_end >= s_end):
        return False
    if (not show["backup_consumed"]) and show["backup_window_start"] and show["backup_window_end"]:
        b_start = parse_dt(show["backup_window_start"])
        b_end = parse_dt(show["backup_window_end"])
        if not (a_start <= b_start and a_end >= b_end):
            return False
    return True


def perimeter_containment_planned(show):
    """Return containment string using pinned design, or None when no pinned design."""
    design_id = show.get("pinned_design_id")
    if not design_id:
        return None
    design = DB.designs.get(design_id)
    if design is None:
        return None
    site = DB.sites.get(show["site_id"])
    if site is None:
        return None
    _, containment = calc.crowd_containment(site, design["max_altitude_ft"], design["drone_count"])
    return containment


def certified_go_evaluation_fresh(show_id):
    now = clock_now()
    for eid in DB.insertion_order["evaluations"]:
        e = DB.evaluations[eid]
        if e["show_event_id"] != show_id:
            continue
        if e["status"] == "CERTIFIED" and e["verdict"] == "GO" and e["certified_at"]:
            gap = now - parse_dt(e["certified_at"])
            if gap <= timedelta(minutes=calc.GO_VALIDITY_MINUTES):
                return True
    return False


def readiness_gates(show):
    """Compute g1..g6 for the show. Returns dict of booleans."""
    g1 = g2 = g3 = g4 = g5 = g6 = False
    design = DB.designs.get(show.get("pinned_design_id") or "")
    if design is not None and design["status"] == "LOCKED":
        sim = latest_simulation_for_design(design["id"])
        g1 = sim is not None and sim["verdict"] == "PASS"
    config = DB.safety_configs.get(show.get("pinned_safety_config_id") or "")
    g2 = config is not None and config["status"] == "APPROVED"
    auth = DB.authorizations.get(show.get("pinned_authorization_id") or "")
    g3 = auth is not None and auth["status"] == "APPROVED" and auth_covers_show(auth, show)
    containment = perimeter_containment_planned(show)
    g4 = containment == "VALID"
    if design is not None:
        g5 = show["assigned_count"] == design["drone_count"]
    g6 = certified_go_evaluation_fresh(show["id"])
    return {"g1": g1, "g2": g2, "g3": g3, "g4": g4, "g5": g5, "g6": g6}


def compute_posture(show):
    gates = readiness_gates(show)
    if all(gates[k] for k in ("g1", "g2", "g3", "g4", "g5", "g6")):
        return "GO"
    if all(gates[k] for k in ("g1", "g2", "g3", "g4", "g5")):
        return "CLEARED"
    return "NOT_READY"


def recompute_posture(show):
    show["readiness_posture"] = compute_posture(show)


# --------------------------------------------------------------------------
# cascades

def drone_release_if_unassigned(drone):
    """RESERVED -> AVAILABLE only when the drone holds no other ASSIGNED slot
    (a drone may serve multiple non-overlapping shows)."""
    if drone["status"] != "RESERVED":
        return
    for aid in DB.insertion_order["assignments"]:
        a = DB.assignments[aid]
        if a["drone_id"] == drone["id"] and a["status"] == "ASSIGNED":
            return
    drone["status"] = "AVAILABLE"
    touch(drone)

def downgrade_show_to_planning(show):
    """Pin invalidation: DESIGN_LOCKED/AUTHORIZED/READY/GO_CERTIFIED -> PLANNING."""
    if show["lifecycle_status"] in ("DESIGN_LOCKED", "AUTHORIZED", "READY", "GO_CERTIFIED"):
        show["lifecycle_status"] = "PLANNING"
        show["readiness_posture"] = "NOT_READY"
        touch(show)


def ready_to_authorized_if_incomplete(show):
    """READY -> AUTHORIZED when grid incomplete."""
    if show["lifecycle_status"] == "READY":
        design = DB.designs.get(show.get("pinned_design_id") or "")
        needed = design["drone_count"] if design else None
        if needed is None or show["assigned_count"] < needed:
            show["lifecycle_status"] = "AUTHORIZED"
            recompute_posture(show)
            touch(show)


def void_assignment(assignment, release_drone=True):
    """ASSIGNED -> VOIDED with drone release + show count downgrade cascade."""
    if assignment["status"] != "ASSIGNED":
        return
    assignment["status"] = "VOIDED"
    touch(assignment)
    if release_drone:
        drone = DB.drones.get(assignment["drone_id"])
        if drone is not None:
            drone_release_if_unassigned(drone)
    show = DB.show_events.get(assignment["show_event_id"])
    if show is not None:
        show["assigned_count"] = max(0, show["assigned_count"] - 1)
        recompute_posture(show)
        if show["lifecycle_status"] == "READY":
            design = DB.designs.get(show.get("pinned_design_id") or "")
            needed = design["drone_count"] if design else None
            if needed is None or show["assigned_count"] < needed:
                show["lifecycle_status"] = "AUTHORIZED"
                recompute_posture(show)
        touch(show)


def ground_drone_cascade(drone):
    """Void every ASSIGNED assignment the drone holds (on any show)."""
    for aid in DB.insertion_order["assignments"]:
        a = DB.assignments[aid]
        if a["drone_id"] == drone["id"] and a["status"] == "ASSIGNED":
            # drone is no longer RESERVED-eligible; release handled by ground itself
            a["status"] = "VOIDED"
            touch(a)
            show = DB.show_events.get(a["show_event_id"])
            if show is not None:
                show["assigned_count"] = max(0, show["assigned_count"] - 1)
                recompute_posture(show)
                if show["lifecycle_status"] == "READY":
                    design = DB.designs.get(show.get("pinned_design_id") or "")
                    needed = design["drone_count"] if design else None
                    if needed is None or show["assigned_count"] < needed:
                        show["lifecycle_status"] = "AUTHORIZED"
                        recompute_posture(show)
                touch(show)


def revoke_authorization_cascade(auth):
    """Shows pinning this authorization drop to PLANNING."""
    for sid in DB.insertion_order["show_events"]:
        s = DB.show_events[sid]
        if s.get("pinned_authorization_id") == auth["id"]:
            downgrade_show_to_planning(s)

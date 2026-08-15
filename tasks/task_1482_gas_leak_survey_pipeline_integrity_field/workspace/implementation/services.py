"""Business logic: calculations (PRD §3), cascades, sweeps, serializers."""
import hashlib
import json
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, now, touch
from errors import not_found

# --- constants ------------------------------------------------------------
MATERIAL_FACTOR = {"STEEL": 0.8, "CAST_IRON": 1.0, "PLASTIC_PE": 0.2,
                   "PLASTIC_PVC": 0.3, "COPPER": 0.5}
REPAIR_DAYS = {"G1": 1, "G2": 30, "G3": 365}
PRIORITY_BY_GRADE = {"G1": "P1_EMERGENCY", "G2": "P2_URGENT", "G3": "P3_ROUTINE"}
CAL_INTERVAL_DAYS = {"FLAME_IONIZATION": 90, "CGI": 60, "OMD": 90,
                     "AERIAL_LIDAR": 180, "CP_VOLTMETER": 365}
MAX_DRIFT_PCT = 5.0
MIN_COVERAGE_PCT = 95.0
MAX_REGRADE_COUNT = 3
HIGH_RISK_THRESHOLD = 70.0
CP_ANOMALY_THRESHOLD_MV = -850
EXCAVATION_METHODS = ("CUT_AND_REPLACE", "ABANDON_SEGMENT")
OPEN_LEAK_STATUSES = ("OPEN", "REPAIR_SCHEDULED", "UNDER_REPAIR",
                      "REPAIRED_PENDING_VERIFICATION")

W_AGE, W_MATERIAL, W_LEAK, W_CP = 0.20, 0.15, 0.30, 0.20
HCA_MULTIPLIER = 1.5

# --- entity field layouts (serialization order) ---------------------------
FIELDS = {
    "pipe_segments": ["id", "segment_code", "install_year", "material",
                      "diameter_inches", "length_feet", "operating_pressure_psi",
                      "pressure_class", "is_high_consequence_area", "region_hint",
                      "risk_score", "open_grade1_count", "open_grade2_count",
                      "open_grade3_count", "posture", "last_surveyed_at",
                      "next_survey_due_at", "status", "created_at", "updated_at",
                      "version"],
    "instruments": ["id", "serial_number", "instrument_type", "calibrated_at",
                    "calibration_due_at", "status", "created_at", "updated_at",
                    "version"],
    "calibrations": ["id", "instrument_id", "performed_by_user_id",
                     "reference_gas_ppm", "observed_ppm", "drift_pct", "outcome",
                     "created_at", "updated_at", "version"],
    "survey_routes": ["id", "route_code", "survey_method",
                      "scheduled_window_start", "scheduled_window_end", "status",
                      "created_at", "updated_at", "version"],
    "route_segment_assignments": ["id", "route_id", "segment_id",
                                  "sequence_index", "status", "created_at",
                                  "updated_at", "version"],
    "survey_runs": ["id", "route_id", "instrument_id", "technician_id",
                    "started_at", "ended_at", "distance_covered_feet",
                    "coverage_pct", "status", "created_at", "updated_at",
                    "version"],
    "leaks": ["id", "segment_id", "survey_run_id", "discovered_at",
              "concentration_ppm", "distance_to_building_feet",
              "bar_hole_reading_pct_lel", "is_migration_evidence", "grade",
              "repair_due_at", "regrade_count", "status", "created_at",
              "updated_at", "version"],
    "repair_orders": ["id", "leak_id", "priority", "crew_id", "dispatched_at",
                      "repair_method", "dispatch_status",
                      "excavation_permit_status", "completed_at",
                      "verified_by_officer_id", "created_at", "updated_at",
                      "version"],
    "excavation_permits": ["id", "repair_order_id", "permit_number",
                           "jurisdiction", "applied_at", "granted_at",
                           "expires_at", "status", "created_at", "updated_at",
                           "version"],
    "repair_crews": ["id", "crew_code", "home_region",
                     "is_qualified_excavation", "max_concurrent_orders",
                     "open_order_count", "status", "created_at", "updated_at",
                     "version"],
    "cp_readings": ["id", "segment_id", "test_point_id", "recorded_at",
                    "pipe_to_soil_potential_mv", "instant_off_potential_mv",
                    "is_anomalous", "anomaly_status", "created_at", "updated_at",
                    "version"],
    "compliance_reports": ["id", "reporting_period_start", "reporting_period_end",
                           "regulator", "report_payload_uri",
                           "leak_section_snapshot_id", "cp_section_snapshot_id",
                           "submitted_at", "status", "created_at", "updated_at",
                           "version"],
    "risk_model_snapshots": ["id", "snapshot_label", "snapshot_kind",
                             "input_set_hash", "total_segments_scored",
                             "high_risk_segment_ids", "generated_at", "status",
                             "created_at", "updated_at", "version"],
    "regrade_events": ["id", "leak_id", "previous_grade", "new_grade", "reason",
                       "performed_by_user_id", "triggered_at", "created_at",
                       "updated_at", "version"],
    "field_technicians": ["id", "employee_code", "full_name",
                          "qualified_methods", "home_region", "status",
                          "created_at", "updated_at", "version"],
    "compliance_officers": ["id", "employee_code", "full_name",
                            "jurisdiction_scope", "status", "created_at",
                            "updated_at", "version"],
    "calibration_techs": ["id", "employee_code", "full_name", "status",
                          "created_at", "updated_at", "version"],
    "dispatch_coordinators": ["id", "employee_code", "full_name", "status",
                              "created_at", "updated_at", "version"],
    "integrity_analysts": ["id", "employee_code", "full_name", "status",
                           "created_at", "updated_at", "version"],
}


def get_or_404(collection, entity_id):
    ent = STORE[collection].get(entity_id)
    if ent is None:
        raise not_found(f"{collection[:-1]} {entity_id} does not exist")
    return ent


def sorted_all(collection):
    return sorted(STORE[collection].values(),
                  key=lambda e: (e["created_at"], e["_seq"]))


# --- snapshot staleness ----------------------------------------------------
def stale_current_snapshots():
    for s in STORE["risk_model_snapshots"].values():
        if s["status"] == "CURRENT":
            s["status"] = "STALE"
            touch(s)


# --- posture / counters / risk (PRD §2.8, §3.8) ----------------------------
def open_cp_anomaly_count(segment_id):
    return sum(1 for r in STORE["cp_readings"].values()
               if r["segment_id"] == segment_id
               and r["anomaly_status"] in ("OPEN", "ACKNOWLEDGED"))


def recompute_counters(seg):
    if seg["status"] != "ACTIVE":
        seg["open_grade1_count"] = 0
        seg["open_grade2_count"] = 0
        seg["open_grade3_count"] = 0
        return
    g1 = g2 = g3 = 0
    for lk in STORE["leaks"].values():
        if lk["segment_id"] == seg["id"] and lk["status"] in OPEN_LEAK_STATUSES:
            if lk["grade"] == "G1":
                g1 += 1
            elif lk["grade"] == "G2":
                g2 += 1
            else:
                g3 += 1
    seg["open_grade1_count"] = g1
    seg["open_grade2_count"] = g2
    seg["open_grade3_count"] = g3


def derive_posture(seg):
    if seg["status"] != "ACTIVE":
        return "NORMAL"
    if seg["open_grade1_count"] >= 1:
        return "CRITICAL"
    if seg["open_grade2_count"] >= 2:
        return "CRITICAL"
    if seg["open_grade2_count"] == 1 or open_cp_anomaly_count(seg["id"]) >= 1:
        return "ELEVATED"
    if seg["open_grade3_count"] >= 3:
        return "ELEVATED"
    return "NORMAL"


def _round(value, places):
    q = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


def compute_risk_score(seg):
    age_years = now().year - seg["install_year"]
    age_score = min(age_years / 50.0, 1.0) * W_AGE
    material_score = MATERIAL_FACTOR[seg["material"]] * W_MATERIAL
    leak_raw = (seg["open_grade1_count"] * 3.0 + seg["open_grade2_count"] * 1.5
                + seg["open_grade3_count"] * 0.5)
    leak_score = min(leak_raw, 1.0) * W_LEAK
    cp_score = min(open_cp_anomaly_count(seg["id"]) / 3.0, 1.0) * W_CP
    base = age_score + material_score + leak_score + cp_score
    if seg["is_high_consequence_area"]:
        base *= HCA_MULTIPLIER
    score = _round(base * 100, 2)
    return min(score, 100.0)


def refresh_segment(seg, recompute_risk=False):
    """Recompute counters + posture (+risk at the §3.8 trigger points)."""
    before = (seg["open_grade1_count"], seg["open_grade2_count"],
              seg["open_grade3_count"], seg["posture"], seg.get("risk_score"))
    recompute_counters(seg)
    new_posture = derive_posture(seg)
    if new_posture != seg["posture"]:
        seg["posture"] = new_posture
        stale_current_snapshots()  # posture shift stales snapshots
        recompute_risk = True
    if recompute_risk:
        seg["risk_score"] = compute_risk_score(seg)
    after = (seg["open_grade1_count"], seg["open_grade2_count"],
             seg["open_grade3_count"], seg["posture"], seg.get("risk_score"))
    if after != before:
        touch(seg)


# --- leak grading (PRD §3.5) ------------------------------------------------
def compute_grade(concentration_ppm, distance_to_building_feet,
                  bar_hole_reading_pct_lel, is_migration_evidence, is_hca):
    dist = distance_to_building_feet
    lel = bar_hole_reading_pct_lel
    if lel >= 25 or (is_migration_evidence and dist is not None and dist <= 20):
        grade = "G1"
    elif (concentration_ppm >= 10000
          or (dist is not None and dist <= 50)
          or lel >= 5):
        grade = "G2"
    else:
        grade = "G3"
    if is_hca:
        on_boundary = (lel == 25 or lel == 5 or concentration_ppm == 10000
                       or (dist is not None and dist == 50)
                       or (is_migration_evidence and dist is not None
                           and dist == 20))
        if on_boundary:
            if grade == "G3":
                grade = "G2"
            elif grade == "G2":
                grade = "G1"
    return grade


def repair_due(discovered_at, grade):
    return discovered_at + timedelta(days=REPAIR_DAYS[grade])


# --- re-survey interval (PRD §3.9) ------------------------------------------
def _base_interval_days(seg):
    pc = seg["pressure_class"]
    hca = seg["is_high_consequence_area"]
    if pc == "TRANSMISSION":
        return 90 if hca else 180
    if pc == "DISTRIBUTION":
        return 180 if hca else 365
    return 365 if hca else 730  # SERVICE


def compute_interval_days(seg):
    factor = 1.0
    if seg["open_grade1_count"] > 0:
        factor = min(factor, 0.25)
    elif seg["open_grade2_count"] > 0:
        factor = min(factor, 0.5)
    if any(r["segment_id"] == seg["id"]
           and r["anomaly_status"] in ("OPEN", "ACKNOWLEDGED")
           for r in STORE["cp_readings"].values()):
        factor *= 0.5
    return math.floor(_base_interval_days(seg) * factor)


# --- survey run coverage ------------------------------------------------------
def compute_coverage(run):
    """Prefix model: walk assignments in sequence order; a segment is covered
    while its length fits within distance_covered_feet."""
    assignments = sorted(
        [a for a in STORE["route_segment_assignments"].values()
         if a["route_id"] == run["route_id"]],
        key=lambda a: (a["sequence_index"], a["_seq"]))
    total = 0.0
    for a in assignments:
        seg = STORE["pipe_segments"].get(a["segment_id"])
        if seg is not None:
            total += seg["length_feet"]
    remaining = run["distance_covered_feet"]
    covered_ids = []
    covered_len = 0.0
    for a in assignments:
        seg = STORE["pipe_segments"].get(a["segment_id"])
        if seg is None:
            continue
        if remaining + 1e-9 >= seg["length_feet"]:
            covered_ids.append(a["id"])
            covered_len += seg["length_feet"]
            remaining -= seg["length_feet"]
        else:
            break
    pct = (covered_len / total * 100.0) if total > 0 else 0.0
    return covered_ids, pct


# --- crews --------------------------------------------------------------------
def recompute_crew_status(crew):
    if crew["status"] == "OFF_DUTY":
        return
    crew["status"] = ("AT_CAPACITY"
                      if crew["open_order_count"] >= crew["max_concurrent_orders"]
                      else "AVAILABLE")


def crew_dispatch_score(crew, seg):
    util = (crew["open_order_count"] / crew["max_concurrent_orders"]
            if crew["max_concurrent_orders"] else 1.0)
    hint = seg.get("region_hint")
    region = 1 if (hint is not None and crew["home_region"] == hint) else 0
    return _round((1 - util) * 0.7 + region * 0.3, 4)


def has_valid_permit(order):
    n = now()
    return any(p["repair_order_id"] == order["id"] and p["status"] == "GRANTED"
               and p["expires_at"] is not None and p["expires_at"] > n
               for p in STORE["excavation_permits"].values())


# --- risk model snapshot generation -------------------------------------------
def generate_snapshot_fields(kind):
    active = [s for s in sorted_all("pipe_segments") if s["status"] == "ACTIVE"]
    high_risk = []
    for seg in active:
        score = compute_risk_score(seg)
        if seg.get("risk_score") != score:
            seg["risk_score"] = score
            touch(seg)
        if score >= HIGH_RISK_THRESHOLD:
            high_risk.append(seg["id"])
    seg_ids = sorted(s["id"] for s in active)
    leak_ids = sorted(l["id"] for l in STORE["leaks"].values()
                      if l["segment_id"] in set(seg_ids))
    cp_ids = sorted(r["id"] for r in STORE["cp_readings"].values()
                    if r["segment_id"] in set(seg_ids))
    digest = hashlib.sha256(json.dumps(
        {"segments": seg_ids, "leaks": leak_ids, "cp_readings": cp_ids},
        sort_keys=True).encode()).hexdigest()
    return {
        "input_set_hash": digest,
        "total_segments_scored": len(active),
        "high_risk_segment_ids": high_risk,
    }


# --- compliance report payload (PRD §3.11) --------------------------------------
def build_report_payload(report):
    start = report["reporting_period_start"]
    end = report["reporting_period_end"]
    leaks_opened = [l for l in STORE["leaks"].values()
                    if start <= l["discovered_at"] < end]
    cleared = [l for l in STORE["leaks"].values()
               if l.get("_verified_at") is not None
               and start <= l["_verified_at"] < end]
    on_time = [l for l in cleared if l["_verified_at"] <= l["repair_due_at"]]
    on_time_rate = _round(len(on_time) / max(len(cleared), 1), 4)
    readings = [r for r in STORE["cp_readings"].values()
                if start <= r["recorded_at"] < end]
    anomalies = [r for r in readings if r["is_anomalous"]]
    resolved = [r for r in readings if r["anomaly_status"] == "RESOLVED"]
    cp_anomaly_rate = _round(len(anomalies) / max(len(readings), 1), 4)
    return {
        "leak_section": {
            "leaks_opened_by_grade": {
                "G1": sum(1 for l in leaks_opened if l["grade"] == "G1"),
                "G2": sum(1 for l in leaks_opened if l["grade"] == "G2"),
                "G3": sum(1 for l in leaks_opened if l["grade"] == "G3"),
            },
            "leaks_verified_cleared": len(cleared),
            "on_time_repair_rate": on_time_rate,
        },
        "cp_section": {
            "readings_taken": len(readings),
            "anomalies_opened": len(anomalies),
            "anomalies_resolved": len(resolved),
            "cp_anomaly_rate": cp_anomaly_rate,
        },
    }


# --- time-based automatic transitions (PRD §2.4, §2.6, §3.6) -------------------
def process_time_based_events():
    n = now()
    for inst in STORE["instruments"].values():
        if (inst["status"] == "IN_SERVICE"
                and inst["calibration_due_at"] is not None
                and n > inst["calibration_due_at"]):
            inst["status"] = "OUT_OF_CALIBRATION"
            touch(inst)
    for permit in STORE["excavation_permits"].values():
        if permit["status"] != "GRANTED":
            continue
        if permit["expires_at"] is None or n <= permit["expires_at"]:
            continue
        order = STORE["repair_orders"].get(permit["repair_order_id"])
        if order is None or order["dispatch_status"] == "WORK_COMPLETE":
            continue
        permit["status"] = "EXPIRED"
        touch(permit)
        prev = order["dispatch_status"]
        order["excavation_permit_status"] = "PERMIT_EXPIRED"
        if prev in ("DISPATCHED", "ON_SITE"):
            crew = (STORE["repair_crews"].get(order["crew_id"])
                    if order.get("crew_id") else None)
            if crew is not None:
                crew["open_order_count"] = max(0, crew["open_order_count"] - 1)
                recompute_crew_status(crew)
                touch(crew)
            order["dispatch_status"] = "PENDING_DISPATCH"
            order["crew_id"] = None
            order["dispatched_at"] = None
            leak = STORE["leaks"].get(order["leak_id"])
            if leak is not None and leak["status"] == "UNDER_REPAIR":
                leak["status"] = "REPAIR_SCHEDULED"
                touch(leak)
        touch(order)

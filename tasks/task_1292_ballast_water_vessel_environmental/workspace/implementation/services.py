"""Business logic: entity factories, serializers, path resolution, the
exchange-vs-treatment determination, posture rollup, severity scoring, and
time-driven transitions (PRD sections 2.8, 3.3, 3.10, 3.12)."""

import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import now, store
from errors import ApiError, ERR_NOT_FOUND
from utils import fmt_dt

OPEN_OCEAN_MIN_NM = 200
ORGANISM_LIMIT = 10.0
TSS_LIMIT = 50.0
INTERNAL_ORGANISM_LIMIT = 5.0
INTERNAL_TSS_LIMIT = 25.0
ECA_LIMIT = Decimal("0.10")
GLOBAL_LIMIT = Decimal("0.50")
CRITICAL_RECENCY_DAYS = 180

SEVERITY_SCORES = {
    "SAMPLING_EXCEEDANCE": 40,
    "PSC_DEFICIENCY": 30,
    "DETERMINATION_NONCOMPLIANT": 25,
    "REPORT_OVERDUE": 10,
    "MISSING_METHOD": 15,
}

DRILL_RECURRENCE_DAYS = {
    "BWMS_OPERATION": 90,
    "EMERGENCY_BALLAST_EXCHANGE": 180,
    "OIL_SPILL_RESPONSE": 90,
    "SEWAGE_SYSTEM": 180,
    "GARBAGE_MANAGEMENT": 180,
    "MARPOL_AWARENESS": 365,
}


def round3(value):
    """3 decimal places, round half up, emitted as a JSON number."""
    return float(Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Entity factory / mutation
# ---------------------------------------------------------------------------

def mint(fields, ledger=False):
    """Create an entity dict. Ledger entities (BallastWaterEvent,
    RecordBookEntry) carry only id + created_at; all others also carry
    updated_at and version (PRD 2.4)."""
    entity = dict(fields)
    entity["id"] = str(uuid.uuid4())
    entity["created_at"] = now()
    entity["_seq"] = store.next_seq()
    if not ledger:
        entity["updated_at"] = now()
        entity["version"] = 1
    return entity


def touch(entity):
    entity["updated_at"] = now()
    entity["version"] += 1


# ---------------------------------------------------------------------------
# Path resolution (PRD 2.5): left-to-right, child must belong to ancestor.
# ---------------------------------------------------------------------------

def _resolve(collection, entity_id, parent_key, parent_id, label):
    entity = store.__getattribute__(collection).get(entity_id)
    if entity is None or (parent_key is not None and entity.get(parent_key) != parent_id):
        raise ApiError(ERR_NOT_FOUND, 404, "%s not found" % label)
    return entity


def get_vessel(vessel_id):
    return _resolve("vessels", vessel_id, None, None, "vessel")


def get_plan(vessel, plan_id):
    return _resolve("plans", plan_id, "vessel_id", vessel["id"], "plan")


def get_voyage(vessel, voyage_id):
    return _resolve("voyages", voyage_id, "vessel_id", vessel["id"], "voyage")


def get_report(voyage, report_id):
    return _resolve("reports", report_id, "voyage_id", voyage["id"], "report")


def get_inspection(voyage, inspection_id):
    return _resolve("inspections", inspection_id, "voyage_id", voyage["id"], "inspection")


def get_noncompliance(voyage, record_id):
    return _resolve("noncompliance", record_id, "voyage_id", voyage["id"], "noncompliance record")


def get_deficiency(vessel, deficiency_id):
    return _resolve("deficiencies", deficiency_id, "vessel_id", vessel["id"], "deficiency")


def get_book(vessel, book_id):
    return _resolve("record_books", book_id, "vessel_id", vessel["id"], "record book")


def get_emission(voyage, record_id):
    return _resolve("emissions", record_id, "voyage_id", voyage["id"], "emissions record")


def get_drill(vessel, drill_id):
    return _resolve("drills", drill_id, "vessel_id", vessel["id"], "drill")


def get_case(vessel, case_id):
    return _resolve("enforcement_cases", case_id, "vessel_id", vessel["id"], "enforcement case")


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def vessel_json(v):
    return {
        "id": v["id"],
        "imo_number": v["imo_number"],
        "vessel_name": v["vessel_name"],
        "flag_state": v["flag_state"],
        "bwms_type": v["bwms_type"],
        "bwms_installation_date": fmt_dt(v["bwms_installation_date"]),
        "gross_tonnage": v["gross_tonnage"],
        "keel_laid_date": fmt_dt(v["keel_laid_date"]),
        "ballast_capacity_m3": v["ballast_capacity_m3"],
        "compliance_posture": v["compliance_posture"],
        "active_enforcement_case_id": v["active_enforcement_case_id"],
        "last_psc_inspection_at": fmt_dt(v["last_psc_inspection_at"]),
        "created_at": fmt_dt(v["created_at"]),
        "updated_at": fmt_dt(v["updated_at"]),
        "version": v["version"],
    }


def plan_json(p):
    return {
        "id": p["id"],
        "vessel_id": p["vessel_id"],
        "plan_revision": p["plan_revision"],
        "approval_authority": p["approval_authority"],
        "approved_at": fmt_dt(p["approved_at"]),
        "status": p["status"],
        "exchange_distance_nm": p["exchange_distance_nm"],
        "sediment_management_included": p["sediment_management_included"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def voyage_json(v):
    return {
        "id": v["id"],
        "vessel_id": v["vessel_id"],
        "voyage_number": v["voyage_number"],
        "departure_port": v["departure_port"],
        "arrival_port": v["arrival_port"],
        "departed_at": fmt_dt(v["departed_at"]),
        "arrived_at": fmt_dt(v["arrived_at"]),
        "crosses_captain_of_port_zones": v["crosses_captain_of_port_zones"],
        "enters_us_eez": v["enters_us_eez"],
        "compliance_status": v["compliance_status"],
        "reporting_status": v["reporting_status"],
        "determination_id": v["determination_id"],
        "bw_record_book_id": v["bw_record_book_id"],
        "created_at": fmt_dt(v["created_at"]),
        "updated_at": fmt_dt(v["updated_at"]),
        "version": v["version"],
    }


def event_json(e):
    return {
        "id": e["id"],
        "voyage_id": e["voyage_id"],
        "event_kind": e["event_kind"],
        "occurred_at": fmt_dt(e["occurred_at"]),
        "tank_id": e["tank_id"],
        "volume_m3": e["volume_m3"],
        "latitude": e["latitude"],
        "longitude": e["longitude"],
        "distance_from_shore_nm": e["distance_from_shore_nm"],
        "salinity_ppt": e["salinity_ppt"],
        "source_port_locode": e["source_port_locode"],
        "created_at": fmt_dt(e["created_at"]),
    }


def determination_json(d):
    return {
        "id": d["id"],
        "voyage_id": d["voyage_id"],
        "determination_basis": d["determination_basis"],
        "exchange_compliant_volume_m3": d["exchange_compliant_volume_m3"],
        "treatment_compliant_volume_m3": d["treatment_compliant_volume_m3"],
        "noncompliant_volume_m3": d["noncompliant_volume_m3"],
        "total_discharged_volume_m3": d["total_discharged_volume_m3"],
        "computed_at": fmt_dt(d["computed_at"]),
        "is_current": d["is_current"],
        "trigger_reason": d["trigger_reason"],
        "created_at": fmt_dt(d["created_at"]),
        "updated_at": fmt_dt(d["updated_at"]),
        "version": d["version"],
    }


def report_json(r):
    is_overdue = (
        r["status"] == "DRAFT" and r["due_at"] is not None and now() > r["due_at"]
    )
    return {
        "id": r["id"],
        "voyage_id": r["voyage_id"],
        "report_type": r["report_type"],
        "due_at": fmt_dt(r["due_at"]),
        "submitted_at": fmt_dt(r["submitted_at"]),
        "status": r["status"],
        "payload_summary": r["payload_summary"],
        "rejection_reason": r["rejection_reason"],
        "is_overdue": is_overdue,
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def inspection_json(i):
    return {
        "id": i["id"],
        "voyage_id": i["voyage_id"],
        "inspection_kind": i["inspection_kind"],
        "sampled_at": fmt_dt(i["sampled_at"]),
        "sampled_by_role": i["sampled_by_role"],
        "indicator_organism_concentration": i["indicator_organism_concentration"],
        "tss_mg_per_l": i["tss_mg_per_l"],
        "findings": i["findings"],
        "status": i["status"],
        "exceeded": i["exceeded"],
        "created_at": fmt_dt(i["created_at"]),
        "updated_at": fmt_dt(i["updated_at"]),
        "version": i["version"],
    }


def noncompliance_json(r):
    return {
        "id": r["id"],
        "voyage_id": r["voyage_id"],
        "source_type": r["source_type"],
        "source_id": r["source_id"],
        "severity": r["severity"],
        "detected_at": fmt_dt(r["detected_at"]),
        "response_status": r["response_status"],
        "response_due_at": fmt_dt(r["response_due_at"]),
        "escalated_to_case_id": r["escalated_to_case_id"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def deficiency_json(d):
    return {
        "id": d["id"],
        "vessel_id": d["vessel_id"],
        "voyage_id": d["voyage_id"],
        "psc_inspection_id": d["psc_inspection_id"],
        "deficiency_code": d["deficiency_code"],
        "action_code": d["action_code"],
        "rectification_deadline": fmt_dt(d["rectification_deadline"]),
        "identified_at": fmt_dt(d["identified_at"]),
        "rectification_status": d["rectification_status"],
        "rectified_at": fmt_dt(d["rectified_at"]),
        "verified_at": fmt_dt(d["verified_at"]),
        "is_priority_one": d["is_priority_one"],
        "created_at": fmt_dt(d["created_at"]),
        "updated_at": fmt_dt(d["updated_at"]),
        "version": d["version"],
    }


def book_json(b):
    return {
        "id": b["id"],
        "vessel_id": b["vessel_id"],
        "book_kind": b["book_kind"],
        "voyage_id": b["voyage_id"],
        "status": b["status"],
        "created_at": fmt_dt(b["created_at"]),
        "updated_at": fmt_dt(b["updated_at"]),
        "version": b["version"],
    }


def entry_json(e):
    return {
        "id": e["id"],
        "record_book_id": e["record_book_id"],
        "entry_kind": e["entry_kind"],
        "occurred_at": fmt_dt(e["occurred_at"]),
        "quantity": e["quantity"],
        "position_lat": e["position_lat"],
        "position_lon": e["position_lon"],
        "distance_from_shore_nm": e["distance_from_shore_nm"],
        "signed_by": e["signed_by"],
        "countersigned_by": e["countersigned_by"],
        "created_at": fmt_dt(e["created_at"]),
    }


def emission_json(e):
    return {
        "id": e["id"],
        "voyage_id": e["voyage_id"],
        "fuel_type": e["fuel_type"],
        "sulfur_content_pct": e["sulfur_content_pct"],
        "consumed_volume_mt": e["consumed_volume_mt"],
        "inside_eca_hours": e["inside_eca_hours"],
        "outside_eca_hours": e["outside_eca_hours"],
        "compliance_status": e["compliance_status"],
        "scrubber_installed": e["scrubber_installed"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def drill_json(d):
    return {
        "id": d["id"],
        "vessel_id": d["vessel_id"],
        "drill_kind": d["drill_kind"],
        "scheduled_for": fmt_dt(d["scheduled_for"]),
        "completed_at": fmt_dt(d["completed_at"]),
        "completion_status": d["completion_status"],
        "attendees": d["attendees"],
        "officer_present": d["officer_present"],
        "next_due_at": fmt_dt(d["next_due_at"]),
        "created_at": fmt_dt(d["created_at"]),
        "updated_at": fmt_dt(d["updated_at"]),
        "version": d["version"],
    }


def case_json(c):
    return {
        "id": c["id"],
        "vessel_id": c["vessel_id"],
        "opened_at": fmt_dt(c["opened_at"]),
        "opened_reason": c["opened_reason"],
        "severity": c["severity"],
        "status": c["status"],
        "hold_flag": c["hold_flag"],
        "linked_noncompliance_ids": c["linked_noncompliance_ids"],
        "closed_at": fmt_dt(c["closed_at"]),
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


# ---------------------------------------------------------------------------
# Exchange-vs-treatment determination (PRD 3.3)
# ---------------------------------------------------------------------------

def governing_plan(vessel_id):
    approved = [p for p in store.plans.values()
                if p["vessel_id"] == vessel_id and p["status"] == "APPROVED"]
    if not approved:
        return None
    return max(approved, key=lambda p: (p["plan_revision"], p["_seq"]))


def voyage_events(voyage_id):
    events = [e for e in store.ballast_events.values() if e["voyage_id"] == voyage_id]
    events.sort(key=lambda e: (e["occurred_at"], e["_seq"]))
    return events


def compute_determination(vessel, voyage, trigger_reason):
    """Run the determination algorithm and persist a new current row."""
    for d in store.determinations.values():
        if d["voyage_id"] == voyage["id"] and d["is_current"]:
            d["is_current"] = False
            touch(d)

    plan = governing_plan(vessel["id"])
    events = voyage_events(voyage["id"])
    discharges = [e for e in events if e["event_kind"] == "DISCHARGE"]
    uptakes = [e for e in events if e["event_kind"] == "UPTAKE"]
    exchanges = [e for e in events if e["event_kind"] == "EXCHANGE_COMPLETE"]
    treatments = [e for e in events if e["event_kind"] == "TREATMENT_COMPLETE"]

    total_discharged = sum(e["volume_m3"] for e in discharges)
    exchange_ok_volume = 0.0
    treatment_ok_volume = 0.0
    noncompliant_volume = 0.0

    if voyage["enters_us_eez"] is False:
        basis = "EXEMPT_NO_US_EEZ"
    elif voyage["crosses_captain_of_port_zones"] is False:
        # A voyage that does not cross COTP zones stays within a single zone,
        # so the uptake port and discharge port are in the same zone.
        basis = "EXEMPT_SAME_COTP"
    else:
        for d in discharges:
            source = None
            for u in uptakes:
                if u["tank_id"] == d["tank_id"] and u["occurred_at"] <= d["occurred_at"]:
                    if source is None or (u["occurred_at"], u["_seq"]) > (
                            source["occurred_at"], source["_seq"]):
                        source = u
            if source is None:
                noncompliant_volume += d["volume_m3"]
                continue
            treatment_ok = any(
                tc["tank_id"] == d["tank_id"]
                and source["occurred_at"] <= tc["occurred_at"] <= d["occurred_at"]
                for tc in treatments
            )
            exchange_ok = False
            if plan is not None:
                exchange_ok = any(
                    xc["tank_id"] == d["tank_id"]
                    and source["occurred_at"] <= xc["occurred_at"] <= d["occurred_at"]
                    and xc["distance_from_shore_nm"] is not None
                    and xc["distance_from_shore_nm"] >= plan["exchange_distance_nm"]
                    and xc["distance_from_shore_nm"] >= OPEN_OCEAN_MIN_NM
                    for xc in exchanges
                )
            if treatment_ok:
                # Treatment preferred when both paths are satisfied.
                treatment_ok_volume += d["volume_m3"]
            elif exchange_ok:
                exchange_ok_volume += d["volume_m3"]
            else:
                noncompliant_volume += d["volume_m3"]

        if noncompliant_volume == 0 and treatment_ok_volume > 0:
            basis = "TREATMENT_COMPLIANT"
        elif noncompliant_volume == 0 and exchange_ok_volume > 0:
            basis = "EXCHANGE_COMPLIANT"
        elif noncompliant_volume > 0 and (exchange_ok_volume > 0 or treatment_ok_volume > 0):
            basis = "NONCOMPLIANT_MIXED"
        elif noncompliant_volume > 0:
            basis = "NONCOMPLIANT_NO_METHOD"
        else:
            basis = "INSUFFICIENT_DATA"

    det = mint({
        "voyage_id": voyage["id"],
        "determination_basis": basis,
        "exchange_compliant_volume_m3": round3(exchange_ok_volume),
        "treatment_compliant_volume_m3": round3(treatment_ok_volume),
        "noncompliant_volume_m3": round3(noncompliant_volume),
        "total_discharged_volume_m3": round3(total_discharged),
        "computed_at": now(),
        "is_current": True,
        "trigger_reason": trigger_reason,
    })
    store.determinations[det["id"]] = det
    voyage["determination_id"] = det["id"]
    return det


# ---------------------------------------------------------------------------
# Vessel compliance posture rollup (PRD 2.8, 3.10)
# ---------------------------------------------------------------------------

def recompute_posture(vessel):
    case = None
    if vessel["active_enforcement_case_id"]:
        case = store.enforcement_cases.get(vessel["active_enforcement_case_id"])

    if case is not None and case["hold_flag"]:
        posture = "FROZEN"
    else:
        p1_open = any(
            d for d in store.deficiencies.values()
            if d["vessel_id"] == vessel["id"] and d["is_priority_one"]
            and d["rectification_status"] in ("OPEN", "RECTIFYING", "RECTIFIED", "REOPENED")
        )
        cutoff = now() - timedelta(days=CRITICAL_RECENCY_DAYS)
        critical_recent = any(
            r for r in store.noncompliance.values()
            if r["_vessel_id"] == vessel["id"] and r["severity"] == "CRITICAL"
            and r["detected_at"] >= cutoff and r["response_status"] != "CLOSED"
        )
        # An active enforcement case holds the vessel at RESTRICTED until the
        # case is closed or withdrawn (PRD 3.10).
        if case is not None or p1_open or critical_recent:
            posture = "RESTRICTED"
        else:
            posture = "OPEN"

    vessel["compliance_posture"] = posture


# ---------------------------------------------------------------------------
# Noncompliance records: severity derivation (PRD 3.10) and escalation
# ---------------------------------------------------------------------------

def create_noncompliance(vessel, voyage_id, source_type, source_id):
    score = SEVERITY_SCORES[source_type]
    if voyage_id is not None and any(
            r for r in store.noncompliance.values()
            if r["voyage_id"] == voyage_id and r["response_status"] == "ESCALATED"):
        score += 25
    if vessel["compliance_posture"] == "RESTRICTED":
        score += 15
    if score >= 70:
        severity = "CRITICAL"
    elif score >= 40:
        severity = "MAJOR"
    else:
        severity = "MINOR"
    detected = now()
    if severity == "MINOR":
        due = detected + timedelta(days=30)
    elif severity == "MAJOR":
        due = detected + timedelta(days=14)
    else:
        due = detected + timedelta(hours=72)
    rec = mint({
        "voyage_id": voyage_id,
        "source_type": source_type,
        "source_id": source_id,
        "severity": severity,
        "detected_at": detected,
        "response_status": "OPEN",
        "response_due_at": due,
        "escalated_to_case_id": None,
    })
    rec["_vessel_id"] = vessel["id"]
    store.noncompliance[rec["id"]] = rec
    return rec


def escalate_record(rec):
    vessel = store.vessels.get(rec["_vessel_id"])
    if vessel is None:
        return
    case = None
    if vessel["active_enforcement_case_id"]:
        case = store.enforcement_cases.get(vessel["active_enforcement_case_id"])
    if case is None:
        case = mint({
            "vessel_id": vessel["id"],
            "opened_at": now(),
            "opened_reason": "Escalation of noncompliance record %s" % rec["id"],
            "severity": "NOTICE_OF_VIOLATION",
            "status": "ACTIVE",
            "hold_flag": False,
            "linked_noncompliance_ids": [],
            "closed_at": None,
        })
        store.enforcement_cases[case["id"]] = case
        vessel["active_enforcement_case_id"] = case["id"]
    if rec["id"] not in case["linked_noncompliance_ids"]:
        case["linked_noncompliance_ids"].append(rec["id"])
        touch(case)
    rec["response_status"] = "ESCALATED"
    rec["escalated_to_case_id"] = case["id"]
    touch(rec)
    recompute_posture(vessel)


# ---------------------------------------------------------------------------
# Time-driven transitions, re-evaluated whenever the logical clock moves
# (PRD 3.12)
# ---------------------------------------------------------------------------

def reevaluate_time_transitions():
    current = now()

    # DRAFT reports past their deadline flip the voyage to OVERDUE and spawn a
    # REPORT_OVERDUE noncompliance record (once per report).
    for report in list(store.reports.values()):
        if report["status"] != "DRAFT" or report["due_at"] is None:
            continue
        if current <= report["due_at"]:
            continue
        voyage = store.voyages.get(report["voyage_id"])
        if voyage is None:
            continue
        vessel = store.vessels.get(voyage["vessel_id"])
        if vessel is None:
            continue
        if voyage["reporting_status"] == "DUE":
            voyage["reporting_status"] = "OVERDUE"
            touch(voyage)
        already = any(
            r for r in store.noncompliance.values()
            if r["source_type"] == "REPORT_OVERDUE" and r["source_id"] == report["id"])
        if not already:
            create_noncompliance(vessel, voyage["id"], "REPORT_OVERDUE", report["id"])

    # Drills still SCHEDULED more than 30 days past schedule flip to OVERDUE.
    for drill in list(store.drills.values()):
        if drill["completion_status"] != "SCHEDULED":
            continue
        if current <= drill["scheduled_for"] + timedelta(days=30):
            continue
        drill["completion_status"] = "OVERDUE"
        touch(drill)
        if drill["drill_kind"] in ("BWMS_OPERATION", "OIL_SPILL_RESPONSE"):
            vessel = store.vessels.get(drill["vessel_id"])
            already = any(
                r for r in store.noncompliance.values()
                if r["source_type"] == "MISSING_METHOD" and r["source_id"] == drill["id"])
            if vessel is not None and not already:
                create_noncompliance(vessel, None, "MISSING_METHOD", drill["id"])

    # OPEN noncompliance records past their escalation threshold escalate.
    for rec in list(store.noncompliance.values()):
        if rec["response_status"] != "OPEN":
            continue
        overdue_escalation = current > rec["response_due_at"] + timedelta(days=7)
        critical_escalation = (
            rec["severity"] == "CRITICAL"
            and current > rec["detected_at"] + timedelta(hours=24)
        )
        if overdue_escalation or critical_escalation:
            escalate_record(rec)

"""Domain constants, derived-field calculations, cascades, and serializers."""

from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from db import clock, store
from envelope import success
from errors import ApiError
from util import fmt_dt, pagination_args

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

DEPARTMENTS = ["EMERGENCY", "ICU", "SURGERY", "NURSING", "PHARMACY", "LOGISTICS",
               "ADMINISTRATION"]
COMMAND_ROLES = ["INCIDENT_COMMANDER", "PLANNING_CHIEF", "LOGISTICS_CHIEF",
                 "PUBLIC_INFORMATION_OFFICER", "LIAISON_OFFICER", "SAFETY_OFFICER",
                 "MEDICAL_BRANCH_DIRECTOR"]
SCORING_MODELS = ["TWO_FACTOR", "THREE_FACTOR_MITIGATION"]
HAZARD_CATEGORIES = ["NATURAL", "TECHNOLOGICAL", "HUMAN", "HAZMAT"]
INCIDENT_TYPES = ["NATURAL", "TECHNOLOGICAL", "HUMAN", "HAZMAT", "INFECTIOUS"]
EXERCISE_TYPES = ["TABLETOP", "FUNCTIONAL", "FULL_SCALE"]
SUBJECT_TYPES = ["EXERCISE", "INCIDENT"]
TASK_PRIORITIES = ["HIGH", "MEDIUM", "LOW"]
TASK_STATUSES = ["OPEN", "IN_PROGRESS", "OVERDUE", "VERIFIED_COMPLETE"]
TRANSACTION_TYPES = ["RECEIVE", "ISSUE", "RETURN", "ADJUST"]
SUPPLY_CATEGORIES = ["PPE", "MEDICATION", "OXYGEN", "OTHER_SUPPLY"]
TRIAGE_CATEGORIES = ["IMMEDIATE", "DELAYED", "MINOR", "EXPECTANT"]
AUDIENCES = ["REGIONAL_COALITION", "STATE_DOH", "CMS", "LOCAL_EMA"]
REPORT_TYPES = ["SITREP", "SURGE_CAPACITY", "AAR_SUMMARY", "RESOURCE_REQUEST"]
CALLBACK_OUTCOMES = ["ACCEPT", "DECLINE"]

PLAN_REVIEW_TRIGGER_SCORE = 6

TIER_MULTIPLIERS = {
    "GREEN": Decimal("1.0"),
    "YELLOW": Decimal("1.25"),
    "ORANGE": Decimal("1.5"),
    "RED": Decimal("2.0"),
}

REPORT_DUE_OFFSET_HOURS = {
    "SITREP": 24,
    "RESOURCE_REQUEST": 24,
    "SURGE_CAPACITY": 72,
    "AAR_SUMMARY": 720,
}

BURN_WINDOW = timedelta(hours=168)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_or_404(collection, entity_id):
    entity = store[collection].get(entity_id)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", 404, "resource %s not found" % entity_id)
    return entity


def active_incident():
    for inc in store["incidents"].values():
        if inc["status"] == "ACTIVATED":
            return inc
    return None


# ---------------------------------------------------------------------------
# Calculation: hva_risk_score
# ---------------------------------------------------------------------------

def compute_entry_risk_score(entry, scoring_model):
    if scoring_model == "TWO_FACTOR":
        return entry["probability"] * entry["severity"]
    # THREE_FACTOR_MITIGATION
    return entry["probability"] * (entry["severity"] + (3 - entry["preparedness"]))


def rescore_hva(hva):
    for entry in hva["hazard_entries"]:
        entry["risk_score"] = compute_entry_risk_score(entry, hva["scoring_model"])
    hva["max_risk_score"] = max((e["risk_score"] for e in hva["hazard_entries"]), default=0)


# ---------------------------------------------------------------------------
# Calculation: surge_capacity_and_tier
# ---------------------------------------------------------------------------

def derive_tier(projected_census, operational_capacity):
    P = projected_census
    C = operational_capacity
    if C == 0:
        return "RED" if P > 0 else "GREEN"
    if 100 * P < 85 * C:
        return "GREEN"
    if 100 * P < 100 * C:
        return "YELLOW"
    if 100 * P < 115 * C:
        return "ORANGE"
    return "RED"


def recompute_incident_surge(incident):
    """Re-derive licensed/operational capacity and the surge tier. No-op (nulls)
    until the first assessment has written staffed_bed_count/projected_census."""
    if incident["staffed_bed_count"] is None:
        incident["licensed_surge_capacity"] = None
        incident["operational_surge_capacity"] = None
        incident["current_surge_tier"] = None
        return
    operational = incident["staffed_bed_count"] + sum(
        s["bed_capacity"] for s in store["sites"].values()
        if s["status"] == "ACTIVATED" and s["activated_incident_id"] == incident["id"]
    )
    incident["licensed_surge_capacity"] = incident["staffed_bed_count"]
    incident["operational_surge_capacity"] = operational
    incident["current_surge_tier"] = derive_tier(incident["projected_census"], operational)


# ---------------------------------------------------------------------------
# Calculation: ppe_burn_rate
# ---------------------------------------------------------------------------

def current_surge_multiplier():
    inc = active_incident()
    if inc is None:
        return Decimal("1.0")
    tier = inc["current_surge_tier"]
    if tier is None:
        return Decimal("1.0")
    return TIER_MULTIPLIERS[tier]


def recompute_item(item):
    now = clock.now()
    window_start = now - BURN_WINDOW
    net = 0
    for t in store["stock_transactions"].values():
        if t["supply_item_id"] != item["id"]:
            continue
        occurred = t["occurred_at"]
        if window_start <= occurred < now:
            if t["transaction_type"] == "ISSUE":
                net += t["quantity"]
            elif t["transaction_type"] == "RETURN":
                net -= t["quantity"]
    observed = (Decimal(net) / Decimal(7)).quantize(Decimal("0.0001"),
                                                    rounding=ROUND_HALF_UP)
    item["observed_daily_burn_rate"] = observed
    projected = (observed * current_surge_multiplier()).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP)
    item["projected_daily_burn_rate"] = projected
    if projected > 0:
        days = int((Decimal(item["quantity_on_hand"]) / projected)
                   .to_integral_value(rounding=ROUND_FLOOR))
        item["days_of_supply"] = days
        item["below_reorder_level"] = days < item["reorder_min_days"]
    else:
        item["days_of_supply"] = None
        item["below_reorder_level"] = False


def recompute_all_items():
    for item in store["supply_items"].values():
        recompute_item(item)


# ---------------------------------------------------------------------------
# Aggregations
# ---------------------------------------------------------------------------

def committed_staff_count(incident_id):
    return sum(1 for cb in store["callback_requests"].values()
               if cb["incident_id"] == incident_id and cb["status"] == "ACCEPTED")


def site_census(site_id):
    return sum(1 for p in store["patients"].values()
               if p["transfer_site_id"] == site_id and p["status"] == "TRANSFERRED")


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_staff(s):
    return {
        "id": s["id"],
        "full_name": s["full_name"],
        "badge_number": s["badge_number"],
        "department": s["department"],
        "role_qualifications": list(s["role_qualifications"]),
        "is_active": s["is_active"],
        "callback_eligible": s["callback_eligible"],
        "callback_seniority_score": s["callback_seniority_score"],
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def ser_hva(h):
    return {
        "id": h["id"],
        "fiscal_year": h["fiscal_year"],
        "scoring_model": h["scoring_model"],
        "hazard_entries": [dict(e) for e in h["hazard_entries"]],
        "max_risk_score": h["max_risk_score"],
        "plan_review_triggered": h["plan_review_triggered"],
        "status": h["status"],
        "created_at": fmt_dt(h["created_at"]),
        "updated_at": fmt_dt(h["updated_at"]),
        "version": h["version"],
    }


def ser_plan(p):
    return {
        "id": p["id"],
        "revision_label": p["revision_label"],
        "change_summary": p["change_summary"],
        "effective_date": fmt_dt(p["effective_date"]),
        "supersedes_revision_id": p["supersedes_revision_id"],
        "source_hva_id": p["source_hva_id"],
        "status": p["status"],
        "created_by_id": p["created_by_id"],
        "approved_by_id": p["approved_by_id"],
        "approved_at": fmt_dt(p["approved_at"]),
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def ser_exercise(e):
    return {
        "id": e["id"],
        "exercise_name": e["exercise_name"],
        "exercise_type": e["exercise_type"],
        "scenario_category": e["scenario_category"],
        "scheduled_start": fmt_dt(e["scheduled_start"]),
        "scheduled_end": fmt_dt(e["scheduled_end"]),
        "plan_revision_id": e["plan_revision_id"],
        "status": e["status"],
        "started_at": fmt_dt(e["started_at"]),
        "completed_at": fmt_dt(e["completed_at"]),
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_aar(a):
    return {
        "id": a["id"],
        "subject_type": a["subject_type"],
        "subject_id": a["subject_id"],
        "summary": a["summary"],
        "status": a["status"],
        "created_by_id": a["created_by_id"],
        "submitted_at": fmt_dt(a["submitted_at"]),
        "approved_by_id": a["approved_by_id"],
        "approved_at": fmt_dt(a["approved_at"]),
        "created_at": fmt_dt(a["created_at"]),
        "updated_at": fmt_dt(a["updated_at"]),
        "version": a["version"],
    }


def ser_task(t):
    return {
        "id": t["id"],
        "after_action_report_id": t["after_action_report_id"],
        "description": t["description"],
        "priority": t["priority"],
        "due_date": fmt_dt(t["due_date"]),
        "assigned_department": t["assigned_department"],
        "status": t["status"],
        "created_at": fmt_dt(t["created_at"]),
        "updated_at": fmt_dt(t["updated_at"]),
        "version": t["version"],
    }


def ser_incident(i):
    recompute_incident_surge(i)
    return {
        "id": i["id"],
        "incident_name": i["incident_name"],
        "incident_type": i["incident_type"],
        "declared_at": fmt_dt(i["declared_at"]),
        "status": i["status"],
        "activation_count": i["activation_count"],
        "activated_at": fmt_dt(i["activated_at"]),
        "deactivated_at": fmt_dt(i["deactivated_at"]),
        "staffed_bed_count": i["staffed_bed_count"],
        "projected_census": i["projected_census"],
        "licensed_surge_capacity": i["licensed_surge_capacity"],
        "operational_surge_capacity": i["operational_surge_capacity"],
        "current_surge_tier": i["current_surge_tier"],
        "committed_staff_count": committed_staff_count(i["id"]),
        "created_at": fmt_dt(i["created_at"]),
        "updated_at": fmt_dt(i["updated_at"]),
        "version": i["version"],
    }


def ser_assignment(a):
    return {
        "id": a["id"],
        "incident_id": a["incident_id"],
        "staff_member_id": a["staff_member_id"],
        "command_role": a["command_role"],
        "status": a["status"],
        "assigned_at": fmt_dt(a["assigned_at"]),
        "created_at": fmt_dt(a["created_at"]),
        "updated_at": fmt_dt(a["updated_at"]),
        "version": a["version"],
    }


def ser_callback(c):
    return {
        "id": c["id"],
        "incident_id": c["incident_id"],
        "staff_member_id": c["staff_member_id"],
        "response_window_hours": c["response_window_hours"],
        "status": c["status"],
        "expires_at": fmt_dt(c["expires_at"]),
        "responded_at": fmt_dt(c["responded_at"]),
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def ser_supply_item(item):
    recompute_item(item)
    return {
        "id": item["id"],
        "item_name": item["item_name"],
        "category": item["category"],
        "unit": item["unit"],
        "reorder_min_days": item["reorder_min_days"],
        "quantity_on_hand": item["quantity_on_hand"],
        "observed_daily_burn_rate": float(item["observed_daily_burn_rate"]),
        "projected_daily_burn_rate": float(item["projected_daily_burn_rate"]),
        "days_of_supply": item["days_of_supply"],
        "below_reorder_level": item["below_reorder_level"],
        "created_at": fmt_dt(item["created_at"]),
        "updated_at": fmt_dt(item["updated_at"]),
        "version": item["version"],
    }


def ser_stock_transaction(t):
    # Append-only ledger: id + created_at only; no updated_at / version.
    return {
        "id": t["id"],
        "supply_item_id": t["supply_item_id"],
        "transaction_type": t["transaction_type"],
        "quantity": t["quantity"],
        "occurred_at": fmt_dt(t["occurred_at"]),
        "incident_id": t["incident_id"],
        "note": t["note"],
        "created_at": fmt_dt(t["created_at"]),
    }


def ser_site(s):
    return {
        "id": s["id"],
        "site_name": s["site_name"],
        "address": s["address"],
        "bed_capacity": s["bed_capacity"],
        "status": s["status"],
        "commitments": [
            {
                "incident_id": c["incident_id"],
                "window_start": fmt_dt(c["window_start"]),
                "window_end": fmt_dt(c["window_end"]),
            }
            for c in s["commitments"]
        ],
        "activated_incident_id": s["activated_incident_id"],
        "current_census": site_census(s["id"]),
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def ser_patient(p):
    return {
        "id": p["id"],
        "incident_id": p["incident_id"],
        "patient_ref": p["patient_ref"],
        "triage_category": p["triage_category"],
        "arrival_at": fmt_dt(p["arrival_at"]),
        "status": p["status"],
        "transfer_site_id": p["transfer_site_id"],
        "transferred_at": fmt_dt(p["transferred_at"]),
        "discharged_at": fmt_dt(p["discharged_at"]),
        "reunified": p["reunified"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def ser_inquiry(q):
    return {
        "id": q["id"],
        "incident_id": q["incident_id"],
        "inquirer_name": q["inquirer_name"],
        "inquirer_phone": q["inquirer_phone"],
        "sought_patient_ref": q["sought_patient_ref"],
        "status": q["status"],
        "matched_patient_record_id": q["matched_patient_record_id"],
        "matched_at": fmt_dt(q["matched_at"]),
        "reunited_at": fmt_dt(q["reunited_at"]),
        "created_at": fmt_dt(q["created_at"]),
        "updated_at": fmt_dt(q["updated_at"]),
        "version": q["version"],
    }


def ser_report(r):
    return {
        "id": r["id"],
        "audience": r["audience"],
        "report_type": r["report_type"],
        "incident_id": r["incident_id"],
        "period_start": fmt_dt(r["period_start"]),
        "period_end": fmt_dt(r["period_end"]),
        "body_summary": r["body_summary"],
        "due_at": fmt_dt(r["due_at"]),
        "status": r["status"],
        "created_by_id": r["created_by_id"],
        "submitted_at": fmt_dt(r["submitted_at"]),
        "submitted_late": r["submitted_late"],
        "hours_late": (float(r["hours_late"]) if r["hours_late"] is not None else None),
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


# ---------------------------------------------------------------------------
# List helper: sort by created_at ascending (insertion order breaks ties,
# dicts preserve insertion order and Python's sort is stable), then paginate.
# ---------------------------------------------------------------------------

def list_response(collection, serializer, predicate=None):
    limit, offset = pagination_args()
    items = sorted(store[collection].values(), key=lambda e: e["created_at"])
    if predicate is not None:
        items = [e for e in items if predicate(e)]
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return success([serializer(e) for e in page], "array", 200, meta)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def demobilize_site(site):
    """AlternateCareSite ACTIVATED -> DEMOBILIZED cascade (links 2-4)."""
    served_incident_id = site["activated_incident_id"]
    site["status"] = "DEMOBILIZED"
    site["activated_incident_id"] = None
    from util import touch
    touch(site)
    if served_incident_id is not None:
        incident = store["incidents"].get(served_incident_id)
        if incident is not None:
            recompute_incident_surge(incident)
    recompute_all_items()

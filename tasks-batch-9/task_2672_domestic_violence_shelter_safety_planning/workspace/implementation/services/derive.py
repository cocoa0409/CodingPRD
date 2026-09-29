"""Immediate re-derivation of every derived field (PRD 2.10).

No background job exists: each helper here runs inside the request that mutated a
row it depends on, and each mutates (and therefore versions) the row it lands on.
"""

from datetime import date, datetime, timezone

from db import clock_date, clock_iso, db, touch
from services import calc

# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def as_date(value):
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value)[:10])


def as_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def rows(collection):
    return list(getattr(db, collection).values())


def where(collection, **conditions):
    out = []
    for row in getattr(db, collection).values():
        if all(row.get(key) == value for key, value in conditions.items()):
            out.append(row)
    return out


def newest(candidates):
    """Latest by created_at, with the internal insertion sequence as tie-break."""
    if not candidates:
        return None
    return max(candidates, key=lambda r: (r["created_at"], r["_seq"]))


# --------------------------------------------------------------------------
# unit_bed_ledger and the shelter roll-up
# --------------------------------------------------------------------------

def unit_ledger(unit, cascade=True):
    if unit is None:
        return
    admissions = where("shelter_admissions", shelter_unit_id=unit["id"])
    reserved = sum(a["household_size"] for a in admissions
                   if a["occupancy_status"] == "RESERVED")
    occupied = sum(a["household_size"] for a in admissions
                   if a["occupancy_status"] == "CHECKED_IN")
    available = unit["bed_capacity"] - reserved - occupied
    status = calc.unit_status_of(reserved, occupied)
    changed = (unit["reserved_beds"] != reserved or unit["occupied_beds"] != occupied
               or unit["available_beds"] != available or unit["status"] != status)
    unit["reserved_beds"] = reserved
    unit["occupied_beds"] = occupied
    unit["available_beds"] = available
    unit["status"] = status
    if changed:
        touch(unit)
    if cascade:
        shelter_rollup(db.shelters.get(unit["shelter_id"]))


def shelter_rollup(shelter):
    if shelter is None:
        return
    units = where("shelter_units", shelter_id=shelter["id"])
    total = sum(u["bed_capacity"] for u in units)
    available = sum(u["available_beds"] for u in units)
    posture = calc.capacity_posture_of(available, total)
    changed = (shelter["total_bed_capacity"] != total
               or shelter["available_beds"] != available
               or shelter["capacity_posture"] != posture)
    shelter["total_bed_capacity"] = total
    shelter["available_beds"] = available
    shelter["capacity_posture"] = posture
    if changed:
        touch(shelter)


def shelter_revenue(shelter):
    """settled_revenue_cents is the running total of the EXITED admissions' settled cost."""
    if shelter is None:
        return
    total = 0
    for admission in where("shelter_admissions", shelter_id=shelter["id"],
                           occupancy_status="EXITED"):
        total += admission.get("settled_stay_cost_cents") or 0
    if shelter["settled_revenue_cents"] != total:
        shelter["settled_revenue_cents"] = total
        touch(shelter)


# --------------------------------------------------------------------------
# client_confidentiality_posture and the client's risk mirror
# --------------------------------------------------------------------------

def client_assessments(client_id):
    call_ids = {c["id"] for c in where("hotline_calls", client_id=client_id)}
    return [a for a in rows("risk_assessments") if a["hotline_call_id"] in call_ids]


def refresh_client_risk(client):
    """Mirror the latest-by-created_at assessment onto the client, then re-derive posture."""
    latest = newest(client_assessments(client["id"]))
    score = latest["danger_score"] if latest else None
    band = latest["risk_band"] if latest else None
    if client["current_danger_score"] != score or client["current_risk_band"] != band:
        client["current_danger_score"] = score
        client["current_risk_band"] = band
        touch(client)
    recompute_client_posture(client)


def refresh_protective_order_active(client):
    active = any(c["status"] in ("FILED", "GRANTED")
                 for c in where("protective_order_cases", client_id=client["id"]))
    if client["protective_order_active"] != active:
        client["protective_order_active"] = active
        touch(client)


def refresh_resource_referral_count(client):
    count = len(where("hotline_calls", client_id=client["id"], status="RESOURCE_REFERRED"))
    if client["resource_referral_count"] != count:
        client["resource_referral_count"] = count
        touch(client)


def recompute_client_posture(client):
    if client is None:
        return
    sealed = any(a["location_security_status"] == "COMPROMISED"
                 for a in where("shelter_admissions", client_id=client["id"]))
    if not sealed:
        sealed = any(e["kind"] == "HMIS_EXPORT" and e["status"] == "DENIED"
                     for e in where("disclosure_events", client_id=client["id"]))
    if sealed:
        posture = "SEALED"
    elif client["current_risk_band"] == "IMMINENT" or client["protective_order_active"]:
        posture = "HEIGHTENED"
    else:
        posture = "NORMAL"
    if client["confidentiality_posture"] != posture:
        client["confidentiality_posture"] = posture
        touch(client)


# --------------------------------------------------------------------------
# safety_plan_coverage_score
# --------------------------------------------------------------------------

def plan_components(plan_id):
    return sorted(where("plan_components", safety_plan_id=plan_id),
                  key=lambda r: (r["created_at"], r["_seq"]))


def recompute_plan_coverage(plan):
    if plan is None:
        return
    client = db.clients.get(plan["client_id"])
    band = client["current_risk_band"] if client else None
    subscores = []
    for component in plan_components(plan["id"]):
        weight = calc.component_weight_effective(component["component_type"], band)
        subscore = calc.component_subscore(weight, component["status"])
        weight_out = float(weight)
        subscore_out = float(subscore)
        if (component["weight_effective"] != weight_out
                or component["subscore"] != subscore_out):
            component["weight_effective"] = weight_out
            component["subscore"] = subscore_out
            touch(component)
        subscores.append(subscore)
    total = float(calc.coverage_total(subscores))
    if plan["coverage_score"] != total:
        plan["coverage_score"] = total
        touch(plan)


# --------------------------------------------------------------------------
# staff_caseload_and_trauma_index
# --------------------------------------------------------------------------

def active_caseload_count(staff_id):
    count = 0
    for request in where("screening_requests", assigned_advocate_id=staff_id):
        if request["status"] not in ("APPROVED", "ADMITTED"):
            continue
        exited = any(a["occupancy_status"] == "EXITED"
                     for a in where("shelter_admissions", screening_request_id=request["id"]))
        if exited:
            continue
        count += 1
    return count


def recompute_staff(staff, force=False):
    """Return True when wellness_posture actually changed value."""
    if staff is None:
        return False
    checks = where("wellness_checks", staff_member_id=staff["id"])
    today = clock_date()
    terms = []
    latest_check_at = None
    for check in checks:
        checked_on = as_datetime(check["checked_on_utc"])
        days_since = (today - checked_on.date()).days
        terms.append((check["contribution_points"], days_since))
        if latest_check_at is None or check["checked_on_utc"] > latest_check_at:
            latest_check_at = check["checked_on_utc"]
    caseload = active_caseload_count(staff["id"])
    index = calc.trauma_index(terms, caseload)
    posture = calc.wellness_posture_of(index)
    posture_changed = staff["wellness_posture"] != posture
    changed = (staff["active_caseload_count"] != caseload
               or staff["secondary_trauma_index"] != index
               or posture_changed
               or staff["last_wellness_check_at"] != latest_check_at)
    staff["active_caseload_count"] = caseload
    staff["secondary_trauma_index"] = index
    staff["wellness_posture"] = posture
    staff["last_wellness_check_at"] = latest_check_at
    if changed or force:
        touch(staff)
    return posture_changed


# --------------------------------------------------------------------------
# landlord_engagement_incentive ledger
# --------------------------------------------------------------------------

def recompute_partner(partner, force=True):
    if partner is None:
        return
    committed = 0
    accrued = 0
    for referral in where("housing_referrals", landlord_partner_id=partner["id"]):
        if referral["status"] in ("MATCHED", "LEASED"):
            committed += 1
            accrued += referral.get("incentive_fee_cents") or 0
    available = partner["units_pledged"] - committed
    score = float(calc.engagement_score_of(committed, partner["units_pledged"]))
    tier = calc.incentive_tier_of(score)
    changed = (partner["units_committed"] != committed
               or partner["units_available"] != available
               or partner["incentive_accrued_cents"] != accrued
               or partner["engagement_score"] != score
               or partner["incentive_tier"] != tier)
    partner["units_committed"] = committed
    partner["units_available"] = available
    partner["incentive_accrued_cents"] = accrued
    partner["engagement_score"] = score
    partner["incentive_tier"] = tier
    if changed or force:
        touch(partner)


# --------------------------------------------------------------------------
# stay-window arithmetic
# --------------------------------------------------------------------------

def window_load(unit_id, entry, planned_exit, exclude_admission_id=None):
    """SUM(household_size) of the RESERVED/CHECKED_IN admissions whose half-open
    stay window overlaps [entry, planned_exit)."""
    total = 0
    for admission in where("shelter_admissions", shelter_unit_id=unit_id):
        if admission["id"] == exclude_admission_id:
            continue
        if admission["occupancy_status"] not in ("RESERVED", "CHECKED_IN"):
            continue
        other_start = as_date(admission["entry_date"])
        other_end = as_date(admission["planned_exit_date"])
        if other_start < planned_exit and entry < other_end:
            total += admission["household_size"]
    return total

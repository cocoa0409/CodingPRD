"""Derived columns, the twin cost ledgers and resource serialization.

Recomputing a derived column to answer a read is not a mutation (PRD 2.4), so
nothing in this module advances ``version`` or ``updated_at``.
"""

import calc
from store import add_days, clock_now, db, iso, parse_instant


# --------------------------------------------------------------------------
# Child collections reachable from a project
# --------------------------------------------------------------------------
def project_budget_lines(project_id):
    return [r for r in db["budget_lines"].values() if r["project_id"] == project_id]


def project_deliverables(project_id):
    return [r for r in db["deliverables"].values() if r["project_id"] == project_id]


def project_engagements(project_id):
    return [r for r in db["talent_engagements"].values() if r["project_id"] == project_id]


def project_shoot_days(project_id):
    return [r for r in db["shoot_days"].values() if r["project_id"] == project_id]


def project_certs(project_id):
    return [r for r in db["compliance_certs"].values() if r["project_id"] == project_id]


def shoot_day_bookings(shoot_day_id):
    return [r for r in db["crew_bookings"].values() if r["shoot_day_id"] == shoot_day_id]


def shoot_day_reservations(shoot_day_id):
    return [r for r in db["equipment_reservations"].values()
            if r["shoot_day_id"] == shoot_day_id]


def deliverable_versions(deliverable_id):
    return [r for r in db["deliverable_versions"].values()
            if r["deliverable_id"] == deliverable_id]


def deliverable_change_orders(deliverable_id):
    return [r for r in db["change_orders"].values()
            if r["deliverable_id"] == deliverable_id]


def project_bookings(project_id):
    day_ids = {d["id"] for d in project_shoot_days(project_id)}
    return [r for r in db["crew_bookings"].values() if r["shoot_day_id"] in day_ids]


def project_reservations(project_id):
    day_ids = {d["id"] for d in project_shoot_days(project_id)}
    return [r for r in db["equipment_reservations"].values() if r["shoot_day_id"] in day_ids]


def project_change_orders(project_id):
    deliverable_ids = {d["id"] for d in project_deliverables(project_id)}
    return [r for r in db["change_orders"].values()
            if r["deliverable_id"] in deliverable_ids]


def location_shoot_days(location_id):
    return [r for r in db["shoot_days"].values() if r["location_id"] == location_id]


def project_of_shoot_day(shoot_day):
    return db["projects"].get(shoot_day["project_id"])


def project_of_deliverable(deliverable):
    return db["projects"].get(deliverable["project_id"])


def deliverable_of_version(version):
    return db["deliverables"].get(version["deliverable_id"])


def project_of_change_order(change_order):
    deliverable = db["deliverables"].get(change_order["deliverable_id"])
    if deliverable is None:
        return None
    return project_of_deliverable(deliverable)


# --------------------------------------------------------------------------
# The twin cost ledgers (PRD 2.7)
# --------------------------------------------------------------------------
def provisional_cost_cents(project):
    pid = project["id"]
    total = 0
    for row in project_budget_lines(pid):
        if row["status"] in ("PLANNED", "COMMITTED"):
            total += row["extended_cents"]
    for row in project_engagements(pid):
        if row["status"] in ("DRAFT", "CONFIRMED", "COMPLETED"):
            total += row["total_comp_cents"]
    for row in project_bookings(pid):
        if row["status"] in ("HELD", "CONFIRMED", "COMPLETED"):
            total += row["cost_cents"]
    for row in project_reservations(pid):
        if row["status"] in ("RESERVED", "RETURNED"):
            total += row["total_cost_cents"]
    for row in project_change_orders(pid):
        if row["status"] in ("PENDING_APPROVAL", "APPROVED"):
            total += row["amount_cents"]
    return total


def committed_cost_cents(project):
    pid = project["id"]
    total = 0
    for row in project_budget_lines(pid):
        if row["status"] == "COMMITTED":
            total += row["extended_cents"]
    for row in project_engagements(pid):
        if row["status"] in ("CONFIRMED", "COMPLETED"):
            total += row["total_comp_cents"]
    for row in project_bookings(pid):
        if row["status"] in ("CONFIRMED", "COMPLETED"):
            total += row["cost_cents"]
    for row in project_reservations(pid):
        if row["status"] in ("RESERVED", "RETURNED"):
            total += row["total_cost_cents"]
    for row in project_change_orders(pid):
        if row["status"] == "APPROVED":
            total += row["amount_cents"]
    return total


def budget_variance_cents(project):
    if project["approved_budget_cents"] is None:
        return 0
    return provisional_cost_cents(project) - project["approved_budget_cents"]


def ledger_snapshot(project):
    if project is None:
        return None
    return (provisional_cost_cents(project), committed_cost_cents(project))


# --------------------------------------------------------------------------
# Round entitlement economy (PRD 3.8)
# --------------------------------------------------------------------------
def consumed_review_rounds(deliverable_id):
    return sum(1 for entry in db["review_decisions"]
               if entry["deliverable_id"] == deliverable_id
               and entry["decision"] == "REQUEST_CHANGES")


def granted_extra_rounds(deliverable_id):
    return sum(row["additional_rounds_granted"]
               for row in deliverable_change_orders(deliverable_id)
               if row["status"] == "APPROVED")


def round_entitlement(deliverable):
    project = project_of_deliverable(deliverable)
    contracted = project["contracted_revision_rounds"] if project else 0
    return contracted + granted_extra_rounds(deliverable["id"])


def round_entitlement_balance(project):
    pid = project["id"]
    total = project["contracted_revision_rounds"]
    for row in project_change_orders(pid):
        if row["status"] == "APPROVED":
            total += row["additional_rounds_granted"]
    for deliverable in project_deliverables(pid):
        total -= consumed_review_rounds(deliverable["id"])
    return total


def review_gate(project):
    for row in project_change_orders(project["id"]):
        if row["status"] == "PENDING_APPROVAL":
            return "CHANGE_ORDER_PENDING"
    return "OPEN"


# --------------------------------------------------------------------------
# Archive / retention (PRD 3.10)
# --------------------------------------------------------------------------
def retention_expires_at(project):
    if project["handover_at"] is None:
        return None
    handover = parse_instant(project["handover_at"])
    return add_days(handover, project["raw_footage_retention_months"] * calc.RETENTION_MONTH_DAYS)


def archive_status(project):
    if project["handover_at"] is None:
        return "NOT_PACKAGED"
    expires = retention_expires_at(project)
    if expires is not None and clock_now() > expires:
        return "RETENTION_EXPIRED"
    return "HANDED_OVER"


# --------------------------------------------------------------------------
# Location derivations (PRD 3.4)
# --------------------------------------------------------------------------
def scheduled_shoot_day_count(location_id):
    return sum(1 for row in location_shoot_days(location_id)
               if row["status"] in ("PLANNED", "CONFIRMED"))


def scouting_status(location_id):
    days = location_shoot_days(location_id)
    if any(row["status"] == "CONFIRMED" for row in days):
        return "CONFIRMED"
    if any(row["status"] == "PLANNED" for row in days):
        return "HOLD"
    return "SCOUTED"


# --------------------------------------------------------------------------
# Compliance certificate derivations (PRD 3.5)
# --------------------------------------------------------------------------
def effective_status(cert):
    if cert["status"] == "ISSUED":
        effective_to = parse_instant(cert["effective_to"])
        if effective_to is not None and clock_now() > effective_to:
            return "EXPIRED"
    return cert["status"]


# --------------------------------------------------------------------------
# Shoot-day derivations (PRD 3.5, 3.6)
# --------------------------------------------------------------------------
def permit_ok(shoot_day):
    call_time = parse_instant(shoot_day["call_time"])
    wrap_time = parse_instant(shoot_day["wrap_time"])
    now = clock_now()
    for cert in db["compliance_certs"].values():
        if cert["shoot_day_id"] != shoot_day["id"]:
            continue
        if cert["cert_type"] != "FILM_PERMIT" or cert["status"] != "ISSUED":
            continue
        eff_from = parse_instant(cert["effective_from"])
        eff_to = parse_instant(cert["effective_to"])
        if eff_from <= call_time and eff_to >= wrap_time and now <= eff_to:
            return True
    return False


def coi_ok(shoot_day):
    location = db["locations"].get(shoot_day["location_id"])
    minimum = location["insurance_minimum_cents"] if location else 0
    call_time = parse_instant(shoot_day["call_time"])
    wrap_time = parse_instant(shoot_day["wrap_time"])
    now = clock_now()
    for cert in project_certs(shoot_day["project_id"]):
        if cert["cert_type"] != "LIABILITY_COI" or cert["status"] != "ISSUED":
            continue
        if cert["coverage_amount_cents"] < minimum:
            continue
        eff_from = parse_instant(cert["effective_from"])
        eff_to = parse_instant(cert["effective_to"])
        if eff_from <= call_time and eff_to >= wrap_time and now <= eff_to:
            return True
    return False


def confirmed_crew_count(shoot_day_id):
    return sum(1 for row in shoot_day_bookings(shoot_day_id)
               if row["status"] in ("CONFIRMED", "COMPLETED"))


def compliance_posture(shoot_day):
    if not (permit_ok(shoot_day) and coi_ok(shoot_day)):
        return "BLOCKED"
    if confirmed_crew_count(shoot_day["id"]) < calc.MIN_CONFIRMED_CREW_FOR_CALL_SHEET:
        return "RESTRICTED"
    return "OPEN"


def day_cost_cents(shoot_day):
    location = db["locations"].get(shoot_day["location_id"])
    total = location["daily_fee_cents"] if location else 0
    for row in shoot_day_bookings(shoot_day["id"]):
        if row["status"] in ("CONFIRMED", "COMPLETED"):
            total += row["cost_cents"]
    for row in shoot_day_reservations(shoot_day["id"]):
        if row["status"] in ("RESERVED", "RETURNED"):
            total += row["total_cost_cents"]
    return total


# --------------------------------------------------------------------------
# Serialization -- declared fields only, in scaffold order, plus the four
# system-managed common fields every resource carries (PRD 2.4).
# --------------------------------------------------------------------------
def _common(row, payload):
    payload["created_at"] = row["created_at"]
    payload["updated_at"] = row["updated_at"]
    payload["version"] = row["version"]
    return payload


def project_out(row):
    return _common(row, {
        "id": row["id"],
        "client_name": row["client_name"],
        "campaign_title": row["campaign_title"],
        "creative_brief_summary": row["creative_brief_summary"],
        "channel_scope": list(row["channel_scope"]),
        "usage_term_months": row["usage_term_months"],
        "contracted_revision_rounds": row["contracted_revision_rounds"],
        "budget_ceiling_cents": row["budget_ceiling_cents"],
        "raw_footage_retention_months": row["raw_footage_retention_months"],
        "raw_footage_terabytes": row["raw_footage_terabytes"],
        "status": row["status"],
        "provisional_cost_cents": provisional_cost_cents(row),
        "committed_cost_cents": committed_cost_cents(row),
        "approved_budget_cents": row["approved_budget_cents"],
        "budget_variance_cents": budget_variance_cents(row),
        "round_entitlement_balance": round_entitlement_balance(row),
        "review_gate": review_gate(row),
        "archive_status": archive_status(row),
        "handover_at": row["handover_at"],
        "handover_recipient": row["handover_recipient"],
        "retention_expires_at": iso(retention_expires_at(row)),
    })


def budget_line_out(row):
    return _common(row, {
        "id": row["id"],
        "project_id": row["project_id"],
        "category": row["category"],
        "description": row["description"],
        "quantity": row["quantity"],
        "unit_rate_cents": row["unit_rate_cents"],
        "markup_pct": row["markup_pct"],
        "extended_cents": row["extended_cents"],
        "status": row["status"],
    })


def deliverable_out(row):
    return _common(row, {
        "id": row["id"],
        "project_id": row["project_id"],
        "title": row["title"],
        "channel": row["channel"],
        "aspect_ratio": row["aspect_ratio"],
        "target_duration_seconds": row["target_duration_seconds"],
        "caption_requirement": row["caption_requirement"],
        "usage_rights_months": row["usage_rights_months"],
        "air_date": row["air_date"],
        "status": row["status"],
        "consumed_review_rounds": consumed_review_rounds(row["id"]),
        "granted_extra_rounds": granted_extra_rounds(row["id"]),
        "round_entitlement": round_entitlement(row),
        "version_count": len(deliverable_versions(row["id"])),
    })


def deliverable_version_out(row):
    return _common(row, {
        "id": row["id"],
        "deliverable_id": row["deliverable_id"],
        "supersedes_version_id": row["supersedes_version_id"],
        "cut_label": row["cut_label"],
        "round_index": row["round_index"],
        "aspect_ratio": row["aspect_ratio"],
        "duration_seconds": row["duration_seconds"],
        "has_captions": row["has_captions"],
        "caption_format": row["caption_format"],
        "file_size_gb": row["file_size_gb"],
        "review_status": row["review_status"],
        "technical_status": row["technical_status"],
        "qc_failure_reasons": list(row["qc_failure_reasons"]),
        "submitted_by_user_id": row["submitted_by_user_id"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "submitted_at": row["submitted_at"],
        "decided_at": row["decided_at"],
    })


def change_order_out(row):
    return _common(row, {
        "id": row["id"],
        "deliverable_id": row["deliverable_id"],
        "trigger_reason": row["trigger_reason"],
        "additional_rounds_granted": row["additional_rounds_granted"],
        "labor_cents": row["labor_cents"],
        "rush_pct": row["rush_pct"],
        "rush_cents": row["rush_cents"],
        "subtotal_cents": row["subtotal_cents"],
        "producer_fee_pct": row["producer_fee_pct"],
        "producer_fee_cents": row["producer_fee_cents"],
        "amount_cents": row["amount_cents"],
        "requested_by_user_id": row["requested_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
        "status": row["status"],
    })


def talent_engagement_out(row):
    return _common(row, {
        "id": row["id"],
        "project_id": row["project_id"],
        "talent_name": row["talent_name"],
        "union_affiliation": row["union_affiliation"],
        "compensation_model": row["compensation_model"],
        "session_fee_cents": row["session_fee_cents"],
        "session_days": row["session_days"],
        "channel_basis_count": row["channel_basis_count"],
        "term_basis_months": row["term_basis_months"],
        "reuse_cycles": row["reuse_cycles"],
        "base_fee_cents": row["base_fee_cents"],
        "usage_load_cents": row["usage_load_cents"],
        "reuse_fee_cents": row["reuse_fee_cents"],
        "pension_health_cents": row["pension_health_cents"],
        "agent_fee_cents": row["agent_fee_cents"],
        "total_comp_cents": row["total_comp_cents"],
        "comp_basis": row["comp_basis"],
        "status": row["status"],
    })


def location_out(row):
    return _common(row, {
        "id": row["id"],
        "name": row["name"],
        "address": row["address"],
        "stage_count": row["stage_count"],
        "daily_fee_cents": row["daily_fee_cents"],
        "insurance_minimum_cents": row["insurance_minimum_cents"],
        "permit_authority": row["permit_authority"],
        "scheduled_shoot_day_count": scheduled_shoot_day_count(row["id"]),
        "scouting_status": scouting_status(row["id"]),
    })


def shoot_day_out(row):
    return _common(row, {
        "id": row["id"],
        "project_id": row["project_id"],
        "location_id": row["location_id"],
        "shoot_date": row["shoot_date"],
        "call_time": row["call_time"],
        "wrap_time": row["wrap_time"],
        "status": row["status"],
        "compliance_posture": compliance_posture(row),
        "confirmed_crew_count": confirmed_crew_count(row["id"]),
        "call_sheet_status": row["call_sheet_status"],
        "call_sheet_published_at": row["call_sheet_published_at"],
        "day_cost_cents": day_cost_cents(row),
        "cancellation_reason": row["cancellation_reason"],
    })


def compliance_cert_out(row):
    return _common(row, {
        "id": row["id"],
        "project_id": row["project_id"],
        "shoot_day_id": row["shoot_day_id"],
        "cert_type": row["cert_type"],
        "carrier_or_authority": row["carrier_or_authority"],
        "reference_code": row["reference_code"],
        "coverage_amount_cents": row["coverage_amount_cents"],
        "fee_cents": row["fee_cents"],
        "effective_from": row["effective_from"],
        "effective_to": row["effective_to"],
        "status": row["status"],
        "effective_status": effective_status(row),
        "decision_note": row["decision_note"],
        "decided_at": row["decided_at"],
    })


def crew_member_out(row):
    return _common(row, {
        "id": row["id"],
        "full_name": row["full_name"],
        "department": row["department"],
        "hourly_rate_cents": row["hourly_rate_cents"],
        "min_turnaround_hours": row["min_turnaround_hours"],
        "union_local": row["union_local"],
    })


def crew_booking_out(row):
    return _common(row, {
        "id": row["id"],
        "shoot_day_id": row["shoot_day_id"],
        "crew_member_id": row["crew_member_id"],
        "department_role": row["department_role"],
        "call_time": row["call_time"],
        "wrap_time": row["wrap_time"],
        "scheduled_hours": row["scheduled_hours"],
        "straight_time_cents": row["straight_time_cents"],
        "overtime_tier1_cents": row["overtime_tier1_cents"],
        "overtime_tier2_cents": row["overtime_tier2_cents"],
        "cost_cents": row["cost_cents"],
        "status": row["status"],
    })


def equipment_reservation_out(row):
    return _common(row, {
        "id": row["id"],
        "shoot_day_id": row["shoot_day_id"],
        "vendor_name": row["vendor_name"],
        "kit_label": row["kit_label"],
        "unit_count": row["unit_count"],
        "daily_rate_cents": row["daily_rate_cents"],
        "pickup_at": row["pickup_at"],
        "return_at": row["return_at"],
        "rental_days": row["rental_days"],
        "total_cost_cents": row["total_cost_cents"],
        "status": row["status"],
    })

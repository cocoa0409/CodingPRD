"""Derived values, calculation rules, cascade chains and serializers.

Everything in this module implements PRD.md section 2.6 - 2.8 and section 3
verbatim: the ordering of each chain is normative, not incidental.
"""

from datetime import timedelta
from decimal import Decimal

from core import (
    ApiError, db, dec, dec_round2, round2, round4, ceil_int, floor_int,
    round_half_up_int, iso_ms, new_row, touch, parse_date, parse_datetime,
    by_created_at, fail,
)

# ---------------------------------------------------------------------------
# Evidence constants (PRD 3.2)
# ---------------------------------------------------------------------------
TIER_RANK = {
    "HISTORIC_RECORD": 1,
    "PREDICTIVE_MODEL": 2,
    "WATER_SAMPLING": 3,
    "VISUAL_INSPECTION": 4,
    "POTHOLE": 5,
}
CONFIDENCE_WEIGHT = {
    "HISTORIC_RECORD": 0.40,
    "PREDICTIVE_MODEL": 0.55,
    "WATER_SAMPLING": 0.70,
    "VISUAL_INSPECTION": 0.85,
    "POTHOLE": 1.00,
}
RECORDS_SOURCE_TYPES = ("HISTORIC_RECORD", "PREDICTIVE_MODEL")
FIELD_SOURCE_TYPES = ("HISTORIC_RECORD", "PREDICTIVE_MODEL", "WATER_SAMPLING",
                      "VISUAL_INSPECTION", "POTHOLE")
FIELD_EVIDENCE_TYPES = ("VISUAL_INSPECTION", "POTHOLE")

MATERIALS = ("LEAD", "GRR", "COPPER", "PLASTIC", "UNKNOWN")
SIDES = ("UTILITY", "CUSTOMER")

PI = Decimal("3.141592653589793")


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------
def lines_of_system(water_system_id):
    return by_created_at([l for l in db.service_lines.values()
                          if l["water_system_id"] == water_system_id])


def evidence_of_line(service_line_id):
    return by_created_at([e for e in db.evidence_items.values()
                          if e["service_line_id"] == service_line_id])


def appointments_of_crew(crew_id):
    return by_created_at([a for a in db.appointments.values()
                          if a["crew_id"] == crew_id])


def batches_of_system(water_system_id):
    return by_created_at([b for b in db.batches.values()
                          if b["water_system_id"] == water_system_id])


def publications_of_system(water_system_id):
    return by_created_at([p for p in db.publications.values()
                          if p["water_system_id"] == water_system_id])


def funding_sources_of_system(water_system_id):
    return by_created_at([s for s in db.funding_sources.values()
                          if s["water_system_id"] == water_system_id])


def orders_of_line(service_line_id):
    return by_created_at([o for o in db.orders.values()
                          if o["service_line_id"] == service_line_id])


def orders_of_system(water_system_id):
    out = []
    for order in db.orders.values():
        line = db.service_lines.get(order["service_line_id"])
        if line is not None and line["water_system_id"] == water_system_id:
            out.append(order)
    return by_created_at(out)


def notifications_of_system(water_system_id):
    out = []
    for note in db.notifications.values():
        line = db.service_lines.get(note["service_line_id"])
        if line is not None and line["water_system_id"] == water_system_id:
            out.append(note)
    return by_created_at(out)


def reports_of_system(water_system_id):
    return by_created_at([r for r in db.progress_reports.values()
                          if r["water_system_id"] == water_system_id])


# ---------------------------------------------------------------------------
# WaterSystem counters (PRD 3.1)
# ---------------------------------------------------------------------------
def system_counts(ws):
    lines = lines_of_system(ws["id"])
    total = len(lines)
    lead = sum(1 for l in lines if l["classification"] == "LEAD")
    grr = sum(1 for l in lines if l["classification"] == "GRR")
    non_lead = sum(1 for l in lines if l["classification"] == "NON_LEAD")
    unknown = sum(1 for l in lines if l["classification"] == "UNKNOWN")
    if total == 0:
        share = 0.00
    else:
        share = round2(dec(100) * dec(unknown) / dec(total))
    return {
        "total_service_line_count": total,
        "lead_count": lead,
        "grr_count": grr,
        "non_lead_count": non_lead,
        "unknown_count": unknown,
        "unknown_share_pct": share,
    }


def outstanding_notification_count(ws):
    return sum(1 for n in notifications_of_system(ws["id"])
               if n["state"] in ("PENDING", "RETURNED"))


# ---------------------------------------------------------------------------
# FundingSource ledger (PRD 3.6)
# ---------------------------------------------------------------------------
def _allocation_rows_for_source(source_id, extra_rows=None):
    """Yield (allocation, order) pairs naming this funding source.

    `extra_rows` is a list of (row, order) tuples describing a not-yet-committed
    apportionment, used to evaluate the equity gate before the commit lands.
    """
    for order in db.orders.values():
        for row in order["funding_allocations"]:
            if row["funding_source_id"] == source_id:
                yield row, order
    if extra_rows:
        for row, order in extra_rows:
            if row["funding_source_id"] == source_id:
                yield row, order


def source_ledger(source, extra_rows=None):
    committed = 0
    drawn = 0
    disadvantaged = 0
    for row, order in _allocation_rows_for_source(source["id"], extra_rows):
        state = row["state"]
        if state == "COMMITTED":
            committed += row["allocated_cents"]
        elif state == "DRAWN":
            drawn += row["allocated_cents"]
        else:
            continue
        line = db.service_lines.get(order["service_line_id"])
        if line is not None and line["disadvantaged_status"]:
            disadvantaged += row["allocated_cents"]
    available = source["authorized_cents"] - committed - drawn
    base = committed + drawn
    if base == 0:
        share = 0.00
    else:
        share = round2(dec(100) * dec(disadvantaged) / dec(base))
    required = ceil_int(dec(base) * dec(source["equity_required_pct"]) / dec(100))
    shortfall = required - disadvantaged
    if shortfall < 0:
        shortfall = 0
    return {
        "committed_cents": committed,
        "drawn_cents": drawn,
        "available_cents": available,
        "disadvantaged_committed_cents": disadvantaged,
        "disadvantaged_share_pct": share,
        "equity_shortfall_cents": shortfall,
    }


# ---------------------------------------------------------------------------
# StreetProject / VerificationCrew counters
# ---------------------------------------------------------------------------
def active_excavation_order_count(project):
    return sum(1 for o in db.orders.values()
               if o["street_project_id"] == project["id"]
               and o["fulfillment_state"] in ("SCHEDULED", "IN_PROGRESS"))


def scheduled_appointment_count(crew):
    return sum(1 for a in db.appointments.values()
               if a["crew_id"] == crew["id"] and a["state"] in ("SCHEDULED", "ON_SITE"))


# ---------------------------------------------------------------------------
# program_posture (PRD 2.7) -- first matching clause wins
# ---------------------------------------------------------------------------
def program_posture(ws):
    if ws["inventory_status"] == "DRAFT":
        return "FROZEN"
    counts = system_counts(ws)
    deadline = parse_date(ws["compliance_deadline_date"])
    if counts["unknown_count"] > 0 and deadline is not None \
            and db.clock.date() > deadline:
        return "FROZEN"
    if ws["inventory_status"] == "AMENDMENT_PENDING":
        return "RESTRICTED"
    if outstanding_notification_count(ws) > 0:
        return "RESTRICTED"
    for source in funding_sources_of_system(ws["id"]):
        if source["status"] == "ACTIVE" \
                and source_ledger(source)["equity_shortfall_cents"] > 0:
            return "RESTRICTED"
    if dec(counts["unknown_share_pct"]) > dec("10.00"):
        return "RESTRICTED"
    return "OPEN"


# ---------------------------------------------------------------------------
# CustomerNotification.overdue (PRD 3.5)
# ---------------------------------------------------------------------------
def notification_overdue(note):
    if note["state"] not in ("PENDING", "RETURNED"):
        return False
    due = parse_datetime(note["due_at"]) if note["due_at"] else None
    if due is None:
        return False
    return db.clock > due


# ---------------------------------------------------------------------------
# governing_evidence_selection (scaffold 1.3)
# ---------------------------------------------------------------------------
def governing_evidence(line, side, basis):
    allowed = RECORDS_SOURCE_TYPES if basis == "RECORDS_BASIS" else FIELD_SOURCE_TYPES
    pool = [e for e in db.evidence_items.values()
            if e["service_line_id"] == line["id"]
            and e["side"] == side
            and not e["retracted"]
            and e["source_type"] in allowed]
    if not pool:
        return None
    pool.sort(key=lambda e: (e["tier_rank"], e["_observed_at"], e["_seq"]),
              reverse=True)
    return pool[0]


def has_both_sides_field_evidence(line):
    utility = False
    customer = False
    for e in db.evidence_items.values():
        if e["service_line_id"] != line["id"] or e["retracted"]:
            continue
        if e["source_type"] not in FIELD_EVIDENCE_TYPES:
            continue
        if e["side"] == "UTILITY":
            utility = True
        elif e["side"] == "CUSTOMER":
            customer = True
    return utility and customer


def has_any_evidence(line):
    for e in db.evidence_items.values():
        if e["service_line_id"] == line["id"] and not e["retracted"]:
            return True
    return False


# ---------------------------------------------------------------------------
# service_line_classification + service_line_certainty_score (PRD 3.2)
# ---------------------------------------------------------------------------
def _side_certainty(line, side, basis):
    governing = governing_evidence(line, side, basis)
    if governing is None:
        return dec(0)
    if governing["observed_material"] == "UNKNOWN":
        return dec(0)
    return dec(CONFIDENCE_WEIGHT[governing["source_type"]])


def recompute_materials(line):
    """Re-select governing evidence per side and rewrite the derived material
    picture, disadvantaged_status and certainty_score."""
    basis = line["certainty_basis"]
    utility = governing_evidence(line, "UTILITY", basis)
    customer = governing_evidence(line, "CUSTOMER", basis)
    line["utility_side_material"] = utility["observed_material"] if utility else "UNKNOWN"
    line["customer_side_material"] = customer["observed_material"] if customer else "UNKNOWN"
    materials = [line["utility_side_material"], line["customer_side_material"]]
    if "LEAD" in materials:
        line["classification"] = "LEAD"
    elif "GRR" in materials:
        line["classification"] = "GRR"
    elif "UNKNOWN" in materials:
        line["classification"] = "UNKNOWN"
    else:
        line["classification"] = "NON_LEAD"

    ws = db.water_systems.get(line["water_system_id"])
    tracts = ws["disadvantaged_tract_codes"] if ws else []
    line["disadvantaged_status"] = line["census_tract_code"] in tracts

    weak = _side_certainty(line, "UTILITY", basis)
    strong = _side_certainty(line, "CUSTOMER", basis)
    low = min(weak, strong)
    high = max(weak, strong)
    line["certainty_score"] = round2(dec(100) * (dec("0.60") * low + dec("0.40") * high))


# ---------------------------------------------------------------------------
# replacement_priority_score (PRD 3.6) -- eleven normative steps
# ---------------------------------------------------------------------------
def recompute_priority(line):
    classification = line["classification"]
    if classification == "LEAD":
        material_points = dec("50.00")
    elif classification == "GRR":
        material_points = dec("35.00")
    elif classification == "UNKNOWN":
        material_points = dec_round2(
            dec(40) * (dec(1) - dec(line["certainty_score"]) / dec(100)))
    else:
        material_points = dec("0.00")

    certainty_bonus = dec("15.00") if line["inventory_state"] == "CLASSIFIED_VERIFIED" \
        else dec("0.00")
    equity_points = dec("25.00") if line["disadvantaged_status"] else dec("0.00")

    coordination_points = dec("0.00")
    project_id = line.get("street_project_id")
    project = db.street_projects.get(project_id) if project_id else None
    if project is not None:
        paving = parse_date(project["paving_start_date"])
        if paving is not None:
            days = (paving - db.clock.date()).days
            if days < 0:
                coordination_points = dec("0.00")
            elif days <= 90:
                coordination_points = dec("20.00")
            elif days <= 180:
                coordination_points = dec("12.00")
            elif days <= 365:
                coordination_points = dec("5.00")
            else:
                coordination_points = dec("0.00")

    sensitive_points = dec("10.00") if line["serves_sensitive_population"] \
        else dec("0.00")

    raw = (material_points + certainty_bonus + equity_points
           + coordination_points + sensitive_points)
    capped = min(dec("100.00"), max(dec("0.00"), raw))
    barrier_penalty = dec("8.00") if line["consent_barrier_flag"] else dec("0.00")
    penalized = dec_round2(capped - barrier_penalty)
    if line["disadvantaged_status"] and classification in ("LEAD", "GRR"):
        equity_floor = dec("65.00")
    else:
        equity_floor = dec("0.00")
    line["replacement_priority_score"] = round2(max(penalized, equity_floor))


# ---------------------------------------------------------------------------
# consent_barrier_flag (PRD 3.6 / 3.7)
# ---------------------------------------------------------------------------
def compute_consent_barrier(line):
    candidates = [o for o in orders_of_line(line["id"])
                  if o["fulfillment_state"] != "CANCELLED"]
    if not candidates:
        return False
    latest = candidates[-1]
    return latest["consent_state"] in ("DENIED", "NO_RESPONSE")


def sync_consent_barrier(line):
    """Re-derive consent_barrier_flag; when it moves, recompute the priority
    score and advance the line's version by one."""
    new_flag = compute_consent_barrier(line)
    if new_flag == line["consent_barrier_flag"]:
        before = line["replacement_priority_score"]
        recompute_priority(line)
        if line["replacement_priority_score"] != before:
            touch(line)
        return False
    line["consent_barrier_flag"] = new_flag
    recompute_priority(line)
    touch(line)
    return True


# ---------------------------------------------------------------------------
# The classification recompute chain (PRD 2.8)
# ---------------------------------------------------------------------------
def classification_recompute(line):
    """Bottom-up chain: governing evidence -> derived fields -> classification
    axis -> priority -> replacement axis -> water-system counters -> posture ->
    amendment edge."""
    ws = db.water_systems.get(line["water_system_id"])
    previous_classification = line["classification"]

    both_sides = has_both_sides_field_evidence(line)
    state = line["inventory_state"]

    if state == "UNCLASSIFIED":
        if has_any_evidence(line):
            line["inventory_state"] = "CLASSIFIED_PROVISIONAL"
            line["certainty_basis"] = "RECORDS_BASIS"
    elif state == "CLASSIFIED_PROVISIONAL":
        if both_sides:
            line["inventory_state"] = "CLASSIFIED_VERIFIED"
            line["certainty_basis"] = "FIELD_BASIS"
    elif state == "CLASSIFIED_VERIFIED":
        if not both_sides:
            line["inventory_state"] = "CLASSIFIED_PROVISIONAL"
            line["certainty_basis"] = "RECORDS_BASIS"

    # A freshly-created UNCLASSIFIED line with both-sides field evidence lands
    # on CLASSIFIED_PROVISIONAL first, then immediately verifies.
    if line["inventory_state"] == "CLASSIFIED_PROVISIONAL" and both_sides \
            and state == "UNCLASSIFIED":
        line["inventory_state"] = "CLASSIFIED_VERIFIED"
        line["certainty_basis"] = "FIELD_BASIS"

    recompute_materials(line)
    recompute_priority(line)
    touch(line)

    # replacement axis, driven by the settled classification
    if line["classification"] in ("LEAD", "GRR", "UNKNOWN") \
            and line["replacement_state"] == "NOT_REQUIRED":
        line["replacement_state"] = "ELIGIBLE"
        recompute_priority(line)
        touch(line)
    elif line["classification"] == "NON_LEAD" \
            and line["replacement_state"] == "ELIGIBLE":
        line["replacement_state"] = "NOT_REQUIRED"
        line["replacement_priority_score"] = 0.00
        touch(line)

    # counters and posture are derived on read; the amendment edge is the last
    # link of the chain and only fires after the counters have settled.
    if ws is not None and ws["inventory_status"] == "PUBLISHED" \
            and line["classification"] != previous_classification:
        ws["inventory_status"] = "AMENDMENT_PENDING"
        touch(ws)


def create_evidence_item(service_line_id, source_type, side, observed_material,
                         observed_at_raw, notes=None, origin="MANUAL"):
    row = new_row()
    row.update({
        "service_line_id": service_line_id,
        "source_type": source_type,
        "side": side,
        "observed_material": observed_material,
        "observed_at": observed_at_raw,
        "_observed_at": parse_datetime(observed_at_raw),
        "notes": notes,
        "tier_rank": TIER_RANK[source_type],
        "confidence_weight": CONFIDENCE_WEIGHT[source_type],
        "origin": origin,
        "retracted": False,
        "retraction_reason": None,
    })
    db.evidence_items[row["id"]] = row
    return row


# ---------------------------------------------------------------------------
# sampling_statistical_validation (PRD 3.4)
# ---------------------------------------------------------------------------
ACTION_LEVEL_PPB = dec("15.0")
CONFIDENCE_FLOOR = dec("0.8000")


def required_sample_count(stratum_line_count):
    return max(5, ceil_int(dec(stratum_line_count) * dec("0.05")))


def valid_samples(batch):
    return [s for s in batch["samples"] if not s["invalidated"]]


def sampling_statistics(batch):
    valid = valid_samples(batch)
    valid = sorted(valid, key=lambda s: (dec(s["lead_ppb"]), s["_collected_at"],
                                         s["sample_seq"]))
    n = len(valid)
    rank = ceil_int(dec("0.90") * dec(n))
    if rank < 1:
        rank = 1
    percentile = valid[rank - 1]["lead_ppb"]
    exceedance_count = sum(1 for s in valid if dec(s["lead_ppb"]) > ACTION_LEVEL_PPB)
    exceedance = dec(percentile) > ACTION_LEVEL_PPB
    confidence = round4(dec(1) - dec(exceedance_count) / dec(n))
    return {
        "percentile_90_ppb": percentile,
        "exceedance_count": exceedance_count,
        "exceedance": exceedance,
        "classification_confidence": confidence,
    }


# ---------------------------------------------------------------------------
# funding_apportionment (PRD 3.7)
# ---------------------------------------------------------------------------
def funding_candidates(water_system_id):
    pool = [s for s in db.funding_sources.values()
            if s["water_system_id"] == water_system_id
            and s["status"] == "ACTIVE"
            and source_ledger(s)["available_cents"] > 0]
    pool.sort(key=lambda s: (s["priority_rank"], s["_seq"]))
    return pool


def plan_allocations(order, mode, candidates):
    """Return (rows, uncovered_cents) without mutating anything."""
    total = order["estimated_cost_cents"]
    if not candidates:
        return [], total

    if mode == "WATERFALL":
        remaining = total
        rows = []
        for source in candidates:
            available = source_ledger(source)["available_cents"]
            cap = floor_int(dec(total) * dec(source["max_share_pct"]) / dec(100))
            alloc = min(remaining, available, cap)
            if alloc > 0:
                rows.append({
                    "funding_source_id": source["id"],
                    "allocated_cents": alloc,
                    "priority_rank": source["priority_rank"],
                    "state": "COMMITTED",
                })
            remaining -= alloc
        return rows, max(0, remaining)

    # PRO_RATA
    pool = sum(source_ledger(s)["available_cents"] for s in candidates)
    if pool < total:
        return [], total - pool
    rows = []
    for source in candidates:
        available = source_ledger(source)["available_cents"]
        allocated = round_half_up_int(dec(total) * dec(available) / dec(pool))
        rows.append({
            "funding_source_id": source["id"],
            "allocated_cents": allocated,
            "priority_rank": source["priority_rank"],
            "state": "COMMITTED",
        })
    remainder = total - sum(r["allocated_cents"] for r in rows)
    rows[0]["allocated_cents"] += remainder
    return rows, 0


# ---------------------------------------------------------------------------
# post_replacement_flushing_guidance (PRD 3.7)
# ---------------------------------------------------------------------------
def flushing_duration_minutes(line, order, ws):
    radius = dec(line["interior_diameter_mm"]) / dec(2000)
    pipe_volume = dec_round2(PI * radius * radius * dec(line["total_length_m"]) * dec(1000))
    volume_minutes = ceil_int(pipe_volume * dec(3) / dec("20.0"))
    partial_penalty = 15 if order["scope"] == "PARTIAL" else 0
    multiplier = dec("1.5") if ws["cct_optimization_status"] == "PENDING_REOPTIMIZATION" \
        else dec("1.0")
    return ceil_int((dec(30) + dec(volume_minutes) + dec(partial_penalty)) * multiplier)


# ---------------------------------------------------------------------------
# compliance_credit + inventory_progress_rate (PRD 3.8)
# ---------------------------------------------------------------------------
def build_progress_report(ws, period_start, period_end):
    population = []
    for order in orders_of_system(ws["id"]):
        if order["fulfillment_state"] != "COMPLETED":
            continue
        completed = order.get("_completed_at")
        if completed is None:
            continue
        if period_start <= completed.date() <= period_end:
            population.append(order)

    full_orders = [o for o in population if o["scope"] == "FULL"]
    partial_orders = [o for o in population if o["scope"] == "PARTIAL"]
    full_count = len(full_orders)
    partial_count = len(partial_orders)
    disadvantaged_full = 0
    for order in full_orders:
        line = db.service_lines.get(order["service_line_id"])
        if line is not None and line["disadvantaged_status"]:
            disadvantaged_full += 1

    base_credit = dec(full_count) + dec_round2(dec("0.5") * dec(partial_count))
    base_credit_out = round2(base_credit)

    share = dec_round2(dec(100) * dec(disadvantaged_full) / dec(max(1, full_count)))
    if share >= dec("60.00"):
        tier, multiplier = "TIER_A", dec("1.20")
    elif share >= dec("40.00"):
        tier, multiplier = "TIER_B", dec("1.10")
    elif share >= dec("20.00"):
        tier, multiplier = "TIER_C", dec("1.00")
    else:
        tier, multiplier = "TIER_D", dec("0.90")

    total_credit = dec_round2(base_credit * multiplier)
    mandated = ceil_int(dec(ws["baseline_lead_and_grr_count"]) * dec("0.10"))
    if total_credit >= dec(20):
        deferral = 3
    elif total_credit >= dec(10):
        deferral = 2
    else:
        deferral = 1
    shortfall = dec_round2(max(dec(0), dec(mandated) - dec(deferral) - total_credit))
    compliance_status = "ON_TRACK" if shortfall == dec("0.00") else "BEHIND"

    lines = lines_of_system(ws["id"])
    replaced_count = sum(1 for l in lines
                         if l["replacement_state"] in ("REPLACED_FULL",
                                                       "REPLACED_PARTIAL"))
    counts = system_counts(ws)
    baseline_denominator = (counts["lead_count"] + counts["grr_count"]
                            + counts["unknown_count"] + replaced_count)
    if baseline_denominator == 0:
        progress_pct = 100.00
    else:
        progress_pct = round2(dec(100) * dec(replaced_count) / dec(baseline_denominator))

    return {
        "full_replacement_count": full_count,
        "partial_replacement_count": partial_count,
        "disadvantaged_full_count": disadvantaged_full,
        "base_credit": base_credit_out,
        "disadvantaged_share_pct": float(share),
        "equity_tier": tier,
        "equity_multiplier": float(multiplier),
        "total_credit": float(total_credit),
        "mandated_annual_credit": mandated,
        "deferral_allowance": deferral,
        "shortfall_credit": float(shortfall),
        "compliance_status": compliance_status,
        "replaced_count": replaced_count,
        "baseline_denominator": baseline_denominator,
        "replacement_progress_pct": progress_pct,
    }


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def serialize_water_system(ws):
    out = _common(ws)
    out.update({
        "pwsid": ws["pwsid"],
        "system_name": ws["system_name"],
        "compliance_deadline_date": ws["compliance_deadline_date"],
        "baseline_lead_and_grr_count": ws["baseline_lead_and_grr_count"],
        "disadvantaged_tract_codes": list(ws["disadvantaged_tract_codes"]),
        "funding_mode": ws["funding_mode"],
        "cct_optimization_status": ws["cct_optimization_status"],
        "cct_orthophosphate_mg_l": ws["cct_orthophosphate_mg_l"],
        "cct_target_ph": ws["cct_target_ph"],
        "inventory_status": ws["inventory_status"],
        "outstanding_notification_count": outstanding_notification_count(ws),
        "program_posture": program_posture(ws),
    })
    out.update(system_counts(ws))
    return out


def serialize_service_line(line):
    out = _common(line)
    out.update({
        "water_system_id": line["water_system_id"],
        "street_project_id": line["street_project_id"],
        "address_label": line["address_label"],
        "census_tract_code": line["census_tract_code"],
        "serves_sensitive_population": line["serves_sensitive_population"],
        "interior_diameter_mm": line["interior_diameter_mm"],
        "total_length_m": line["total_length_m"],
        "disadvantaged_status": line["disadvantaged_status"],
        "utility_side_material": line["utility_side_material"],
        "customer_side_material": line["customer_side_material"],
        "classification": line["classification"],
        "certainty_basis": line["certainty_basis"],
        "certainty_score": line["certainty_score"],
        "replacement_priority_score": line["replacement_priority_score"],
        "consent_barrier_flag": line["consent_barrier_flag"],
        "inventory_state": line["inventory_state"],
        "replacement_state": line["replacement_state"],
    })
    return out


def serialize_evidence_item(item):
    out = _common(item)
    out.update({
        "service_line_id": item["service_line_id"],
        "source_type": item["source_type"],
        "side": item["side"],
        "observed_material": item["observed_material"],
        "observed_at": item["observed_at"],
        "notes": item["notes"],
        "tier_rank": item["tier_rank"],
        "confidence_weight": item["confidence_weight"],
        "origin": item["origin"],
        "retracted": item["retracted"],
        "retraction_reason": item["retraction_reason"],
    })
    return out


def serialize_crew(crew):
    out = _common(crew)
    out.update({
        "water_system_id": crew["water_system_id"],
        "crew_name": crew["crew_name"],
        "shift_start_utc_time": crew["shift_start_utc_time"],
        "shift_end_utc_time": crew["shift_end_utc_time"],
        "daily_appointment_capacity": crew["daily_appointment_capacity"],
        "certified_methods": list(crew["certified_methods"]),
        "status": crew["status"],
        "scheduled_appointment_count": scheduled_appointment_count(crew),
    })
    return out


def serialize_appointment(appt):
    out = _common(appt)
    out.update({
        "service_line_id": appt["service_line_id"],
        "crew_id": appt["crew_id"],
        "method": appt["method"],
        "window_start_utc": appt["window_start_utc"],
        "window_end_utc": appt["window_end_utc"],
        "state": appt["state"],
        "attempt_count": appt["attempt_count"],
        "barrier_reason": appt["barrier_reason"],
        "observed_material": appt["observed_material"],
        "observed_side": appt["observed_side"],
        "emitted_evidence_item_id": appt["emitted_evidence_item_id"],
    })
    return out


def serialize_sample(sample):
    return {
        "sample_seq": sample["sample_seq"],
        "service_line_id": sample["service_line_id"],
        "lead_ppb": sample["lead_ppb"],
        "collected_at": sample["collected_at"],
        "sample_type": sample["sample_type"],
        "invalidated": sample["invalidated"],
        "invalidation_reason": sample["invalidation_reason"],
    }


def serialize_batch(batch):
    out = _common(batch)
    out.update({
        "water_system_id": batch["water_system_id"],
        "stratum_code": batch["stratum_code"],
        "stratum_line_count": batch["stratum_line_count"],
        "samples": [serialize_sample(s) for s in batch["samples"]],
        "required_sample_count": required_sample_count(batch["stratum_line_count"]),
        "valid_sample_count": len(valid_samples(batch)),
        "percentile_90_ppb": batch["percentile_90_ppb"],
        "exceedance_count": batch["exceedance_count"],
        "exceedance": batch["exceedance"],
        "classification_confidence": batch["classification_confidence"],
        "state": batch["state"],
        "reopen_count": batch["reopen_count"],
        "rejection_reason": batch["rejection_reason"],
    })
    return out


def serialize_publication(pub):
    out = _common(pub)
    out.update({
        "water_system_id": pub["water_system_id"],
        "basis": pub["basis"],
        "reporting_period_label": pub["reporting_period_label"],
        "drafted_by_user_id": pub["drafted_by_user_id"],
        "certified_by_user_id": pub["certified_by_user_id"],
        "state": pub["state"],
        "pinned_lead_count": pub["pinned_lead_count"],
        "pinned_grr_count": pub["pinned_grr_count"],
        "pinned_unknown_count": pub["pinned_unknown_count"],
        "pinned_non_lead_count": pub["pinned_non_lead_count"],
        "notifiable_line_count": pub["notifiable_line_count"],
        "published_at": pub["published_at"],
        "notification_due_at": pub["notification_due_at"],
        "supersede_reason": pub["supersede_reason"],
    })
    return out


def serialize_notification(note):
    out = _common(note)
    out.update({
        "service_line_id": note["service_line_id"],
        "inventory_publication_id": note["inventory_publication_id"],
        "notified_classification": note["notified_classification"],
        "state": note["state"],
        "delivery_channel": note["delivery_channel"],
        "delivered_at": note["delivered_at"],
        "acknowledged_at": note["acknowledged_at"],
        "return_reason": note["return_reason"],
        "delivery_attempt_count": note["delivery_attempt_count"],
        "due_at": note["due_at"],
        "overdue": notification_overdue(note),
    })
    return out


def serialize_order(order):
    out = _common(order)
    allocated_total = sum(r["allocated_cents"] for r in order["funding_allocations"]
                          if r["state"] in ("COMMITTED", "DRAWN"))
    out.update({
        "service_line_id": order["service_line_id"],
        "street_project_id": order["street_project_id"],
        "estimated_cost_cents": order["estimated_cost_cents"],
        "excavation_start_date": order["excavation_start_date"],
        "excavation_end_date": order["excavation_end_date"],
        "fulfillment_state": order["fulfillment_state"],
        "consent_state": order["consent_state"],
        "scope": order["scope"],
        "consent_barrier_reason": order["consent_barrier_reason"],
        "funding_allocations": [dict(r) for r in order["funding_allocations"]],
        "funding_mode_applied": order["funding_mode_applied"],
        "allocated_total_cents": allocated_total,
        "flushing_duration_minutes": order["flushing_duration_minutes"],
        "replaced_sides": list(order["replaced_sides"]),
        "completed_at": order["completed_at"],
        "cancellation_reason": order["cancellation_reason"],
    })
    return out


def serialize_street_project(project):
    out = _common(project)
    out.update({
        "water_system_id": project["water_system_id"],
        "project_name": project["project_name"],
        "moratorium_start_date": project["moratorium_start_date"],
        "moratorium_end_date": project["moratorium_end_date"],
        "paving_start_date": project["paving_start_date"],
        "max_concurrent_excavations": project["max_concurrent_excavations"],
        "active_excavation_order_count": active_excavation_order_count(project),
    })
    return out


def serialize_funding_source(source):
    out = _common(source)
    out.update({
        "water_system_id": source["water_system_id"],
        "source_kind": source["source_kind"],
        "authorized_cents": source["authorized_cents"],
        "priority_rank": source["priority_rank"],
        "max_share_pct": source["max_share_pct"],
        "equity_required_pct": source["equity_required_pct"],
        "status": source["status"],
    })
    out.update(source_ledger(source))
    return out


def serialize_progress_report(report):
    out = {"id": report["id"], "created_at": report["created_at"]}
    for key in ("water_system_id", "period_start_date", "period_end_date",
                "full_replacement_count", "partial_replacement_count",
                "disadvantaged_full_count", "base_credit",
                "disadvantaged_share_pct", "equity_tier", "equity_multiplier",
                "total_credit", "mandated_annual_credit", "deferral_allowance",
                "shortfall_credit", "compliance_status", "replaced_count",
                "baseline_denominator", "replacement_progress_pct"):
        out[key] = report[key]
    return out

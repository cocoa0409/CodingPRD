"""Derivation of every `computed` rollup, plus the per-entity serialisers.

Rollups are recomputed from the surviving rows on every read rather than
adjusted by deltas, which is what makes a dispute restore exactly the state
that preceded the grading (PRD 2.10).
"""
from decimal import Decimal

import calc
from common import CLOCK, DB, D, iso_clock, iso_ms, q1, q3, utc_year

ZERO3 = Decimal("0.000")
ACCEPTED_SET = ("ACCEPTED", "PARTIALLY_ACCEPTED")
REJECTED_SET = ("REJECTED_QUALITY", "REJECTED_OVER_CAP")
LIVE_LINE = ("PROVISIONAL", "FINAL")
LANE_BUSY = ("SCHEDULED", "ARRIVED")


def vintage():
    return utc_year(CLOCK.now)


def by_seq(items):
    """Deterministic iteration order: insertion sequence ascending."""
    return sorted(items, key=lambda r: r["_seq"])


# --------------------------------------------------------------------------
# graph walks
# --------------------------------------------------------------------------
def contract_of_appointment(appointment):
    call = DB["pick_calls"].get(appointment["pick_call_id"])
    if call is None:
        return None
    return DB["contracts"].get(call["contract_id"])


def contract_of_tag(tag):
    appointment = DB["appointments"].get(tag["appointment_id"])
    if appointment is None:
        return None
    return contract_of_appointment(appointment)


def contracts_of_grower(grower_id):
    return [c for c in DB["contracts"].values() if c["grower_id"] == grower_id]


def tags_of_contract(contract_id):
    out = []
    for tag in DB["weigh_tags"].values():
        contract = contract_of_tag(tag)
        if contract is not None and contract["id"] == contract_id:
            out.append(tag)
    return out


def tags_of_grower(grower_id):
    ids = set(c["id"] for c in contracts_of_grower(grower_id))
    out = []
    for tag in DB["weigh_tags"].values():
        contract = contract_of_tag(tag)
        if contract is not None and contract["id"] in ids:
            out.append(tag)
    return out


def pick_calls_of_contract(contract_id):
    return [p for p in DB["pick_calls"].values() if p["contract_id"] == contract_id]


def appointments_of_pick_call(pick_call_id):
    return [a for a in DB["appointments"].values() if a["pick_call_id"] == pick_call_id]


def tags_of_appointment(appointment_id):
    return [t for t in DB["weigh_tags"].values() if t["appointment_id"] == appointment_id]


def lines_of_contract(contract_id):
    return [l for l in DB["lines"].values() if l["contract_id"] == contract_id]


def lines_of_tag(weigh_tag_id):
    return [l for l in DB["lines"].values() if l["weigh_tag_id"] == weigh_tag_id]


def grades_of_tag(weigh_tag_id):
    return [g for g in DB["grades"].values() if g["weigh_tag_id"] == weigh_tag_id]


def active_grade(weigh_tag_id):
    for grade in grades_of_tag(weigh_tag_id):
        if grade.get("superseded_at") is None:
            return grade
    return None


def installments_of_contract(contract_id):
    return [i for i in DB["installments"].values() if i["contract_id"] == contract_id]


def allocation_for(contract_id, block_id):
    for allocation in DB["allocations"].values():
        if allocation["contract_id"] == contract_id and allocation["block_id"] == block_id:
            return allocation
    return None


def allocations_of_contract(contract_id):
    return [a for a in DB["allocations"].values() if a["contract_id"] == contract_id]


# --------------------------------------------------------------------------
# Grower
# --------------------------------------------------------------------------
def grower_counters(grower_id):
    """Penalty rows bucketed by their own created_at UTC calendar year."""
    current = vintage()
    rejected_now = expired_now = no_show_now = 0
    prior = {}

    for tag in tags_of_grower(grower_id):
        if tag["disposition"] in REJECTED_SET:
            year = utc_year(tag["created_at"])
            if year == current:
                rejected_now += 1
            else:
                prior.setdefault(year, [0, 0, 0])[0] += 1

    contract_ids = set(c["id"] for c in contracts_of_grower(grower_id))
    for call in DB["pick_calls"].values():
        if call["contract_id"] in contract_ids and call["status"] == "EXPIRED":
            year = utc_year(call["created_at"])
            if year == current:
                expired_now += 1
            else:
                prior.setdefault(year, [0, 0, 0])[1] += 1

    for appointment in DB["appointments"].values():
        if appointment["status"] != "NO_SHOW":
            continue
        call = DB["pick_calls"].get(appointment["pick_call_id"])
        if call is None or call["contract_id"] not in contract_ids:
            continue
        year = utc_year(appointment["created_at"])
        if year == current:
            no_show_now += 1
        else:
            prior.setdefault(year, [0, 0, 0])[2] += 1

    prior_units = 0
    for year, slot in prior.items():
        if year < current:
            prior_units += calc.penalty_units(slot[0], slot[1], slot[2])

    current_units = calc.penalty_units(rejected_now, expired_now, no_show_now)
    return {
        "rejected_load_count_vintage": rejected_now,
        "expired_pick_call_count_vintage": expired_now,
        "no_show_appointment_count_vintage": no_show_now,
        "prior_vintage_penalty_units": prior_units,
        "reliability_score_vintage": calc.reliability_vintage(current_units),
        "reliability_score_lifetime": calc.reliability_lifetime(current_units, prior_units),
    }


def outstanding_lien_balance_cents(grower_id):
    total = 0
    contract_ids = set(c["id"] for c in contracts_of_grower(grower_id))
    for installment in DB["installments"].values():
        if installment["contract_id"] not in contract_ids:
            continue
        if not installment["lien_protected"]:
            continue
        if installment["status"] not in ("SCHEDULED", "PARTIALLY_PAID", "DELINQUENT"):
            continue
        total += int(installment["planned_amount_cents"]) - int(installment["paid_amount_cents"])
    return total


def grower_json(row):
    out = {
        "id": row["id"],
        "name": row["name"],
        "license_number": row["license_number"],
        "region_code": row["region_code"],
        "status": row["status"],
    }
    out.update(grower_counters(row["id"]))
    out["outstanding_lien_balance_cents"] = outstanding_lien_balance_cents(row["id"])
    _stamp(out, row)
    return out


# --------------------------------------------------------------------------
# VineyardBlock
# --------------------------------------------------------------------------
def latest_completed_visit(block_id):
    candidates = [v for v in DB["visits"].values()
                  if v["block_id"] == block_id and v["status"] == "COMPLETED"
                  and v.get("sampled_at") is not None]
    if not candidates:
        return None
    candidates.sort(key=lambda v: (v["sampled_at"], -v["_seq"]))
    best = candidates[-1]
    top = [v for v in candidates if v["sampled_at"] == best["sampled_at"]]
    top.sort(key=lambda v: (v["created_at"], v["_seq"]))
    return top[0]


def block_delivered_net_tons_vintage(block_id):
    current = vintage()
    total = ZERO3
    for tag in DB["weigh_tags"].values():
        if tag["block_id"] != block_id:
            continue
        if tag["weigh_status"] != "NET_FINAL":
            continue
        if tag["disposition"] not in ACCEPTED_SET:
            continue
        if utc_year(tag["created_at"]) != current:
            continue
        total += D(tag["net_tons"] or 0)
    return q3(total)


def block_json(row):
    visit = latest_completed_visit(row["id"])
    out = {
        "id": row["id"],
        "grower_id": row["grower_id"],
        "block_code": row["block_code"],
        "varietal": row["varietal"],
        "acres": row["acres"],
        "expected_yield_tons_per_acre": row["expected_yield_tons_per_acre"],
        "ava_code": row["ava_code"],
        "status": row["status"],
        "latest_sampling_brix": visit["measured_brix"] if visit else None,
        "latest_sampling_rot_pct": visit["measured_rot_pct"] if visit else None,
        "delivered_net_tons_vintage": block_delivered_net_tons_vintage(row["id"]),
    }
    _stamp(out, row)
    return out


# --------------------------------------------------------------------------
# QualitySpec
# --------------------------------------------------------------------------
SPEC_FIELDS = (
    "spec_code", "min_brix_pick_call", "min_brix_accept", "brix_bonus_start",
    "brix_penalty_start", "brix_step", "brix_bonus_pct_per_step",
    "brix_penalty_pct_per_step", "ta_min_gl", "ta_max_gl",
    "acid_out_of_spec_penalty_pct", "rot_free_pct", "rot_penalty_pct_per_point",
    "rot_rejection_pct", "mog_max_pct", "mog_penalty_pct",
    "max_total_bonus_pct", "max_total_penalty_pct",
)


def spec_json(row):
    out = {"id": row["id"]}
    for field in SPEC_FIELDS:
        out[field] = row[field]
    _stamp(out, row)
    return out


def _stamp(out, row):
    out["created_at"] = iso_ms(row["created_at"])
    if "updated_at" in row:
        out["updated_at"] = iso_ms(row["updated_at"])
    if "version" in row:
        out["version"] = row["version"]
    return out


# --------------------------------------------------------------------------
# GrapeContract
# --------------------------------------------------------------------------
def bucket_tons(contract_id, bucket):
    total = ZERO3
    for line in lines_of_contract(contract_id):
        if line["bucket"] == bucket and line["status"] in LIVE_LINE:
            total += D(line["tons"])
    return q3(total)


def contract_rejected_tons(contract_id):
    total = ZERO3
    for tag in tags_of_contract(contract_id):
        total += D(tag["over_rejected_tons"]) + D(tag["excess_rejected_tons"])
        if tag["disposition"] in REJECTED_SET:
            total += D(tag["net_tons"] or 0)
    return q3(total)


def contract_tonnage_status(contract):
    """OPEN / CAP_REACHED / HARD_CAP_REACHED, re-derived from the surviving lines."""
    if contract.get("contract_cap_tons") is None:
        return "OPEN"
    delivered_contract = bucket_tons(contract["id"], "CONTRACT")
    delivered_over = bucket_tons(contract["id"], "OVER_DELIVERY")
    if delivered_contract + delivered_over >= D(contract["hard_cap_tons"]):
        return "HARD_CAP_REACHED"
    if delivered_contract >= D(contract["contract_cap_tons"]):
        return "CAP_REACHED"
    return "OPEN"


def contract_provisional_cents(contract_id):
    total = 0
    for line in lines_of_contract(contract_id):
        if line["status"] == "PROVISIONAL":
            total += int(line["provisional_amount_cents"])
    return total


def contract_final_cents(contract_id):
    total = 0
    for line in lines_of_contract(contract_id):
        if line["status"] == "FINAL" and line["final_amount_cents"] is not None:
            total += int(line["final_amount_cents"])
    return total


CONTRACT_INPUT_FIELDS = (
    "grower_id", "quality_spec_id", "contract_code", "contract_basis",
    "base_price_per_ton_cents", "committed_tons", "contracted_yield_tons_per_acre",
    "over_delivery_policy", "spot_price_pct", "over_delivery_tolerance_pct",
    "settlement_basis", "provisional_payment_pct", "lien_holdback_pct",
    "min_pick_notice_hours", "pick_call_ack_window_hours", "term_start_vintage",
    "term_end_vintage", "evergreen_flag", "evergreen_term_years",
    "termination_notice_days", "installment_plan",
)


def contract_json(row):
    out = {"id": row["id"]}
    for field in CONTRACT_INPUT_FIELDS:
        out[field] = row[field]
    out["lifecycle_status"] = row["lifecycle_status"]
    out["renewal_status"] = row["renewal_status"]
    out["offer_round"] = row["offer_round"]
    out["countered_price_per_ton_cents"] = row["countered_price_per_ton_cents"]
    out["contract_cap_tons"] = row["contract_cap_tons"]
    out["hard_cap_tons"] = row["hard_cap_tons"]
    out["cap_scope"] = row["cap_scope"]
    out["delivered_contract_tons"] = bucket_tons(row["id"], "CONTRACT")
    out["delivered_over_tons"] = bucket_tons(row["id"], "OVER_DELIVERY")
    out["rejected_tons"] = contract_rejected_tons(row["id"])
    out["tonnage_status"] = contract_tonnage_status(row)
    out["provisional_settlement_cents"] = contract_provisional_cents(row["id"])
    out["final_settlement_cents"] = contract_final_cents(row["id"])
    out["prompt_pay_credit_cents"] = row["prompt_pay_credit_cents"]
    out["lien_holdback_cents"] = row["lien_holdback_cents"]
    out["net_payable_cents"] = row["net_payable_cents"]
    out["settlement_closed_at"] = iso_clock(row["settlement_closed_at"])
    out["renewal_window_opens_at"] = iso_clock(row["renewal_window_opens_at"])
    out["renewal_window_closes_at"] = iso_clock(row["renewal_window_closes_at"])
    out["termination_effective_at"] = iso_clock(row["termination_effective_at"])
    out["lien_released_at"] = iso_clock(row["lien_released_at"])
    _stamp(out, row)
    return out


def settlement_summary(contract):
    planned = 0
    paid = 0
    for installment in installments_of_contract(contract["id"]):
        planned += int(installment["planned_amount_cents"])
        paid += int(installment["paid_amount_cents"])
    return {
        "contract_cap_tons": contract["contract_cap_tons"],
        "hard_cap_tons": contract["hard_cap_tons"],
        "cap_scope": contract["cap_scope"],
        "delivered_contract_tons": bucket_tons(contract["id"], "CONTRACT"),
        "delivered_over_tons": bucket_tons(contract["id"], "OVER_DELIVERY"),
        "rejected_tons": contract_rejected_tons(contract["id"]),
        "tonnage_status": contract_tonnage_status(contract),
        "settlement_basis": contract["settlement_basis"],
        "provisional_settlement_cents": contract_provisional_cents(contract["id"]),
        "final_settlement_cents": contract_final_cents(contract["id"]),
        "prompt_pay_credit_cents": contract["prompt_pay_credit_cents"],
        "lien_holdback_cents": contract["lien_holdback_cents"],
        "net_payable_cents": contract["net_payable_cents"],
        "installment_planned_total_cents": planned,
        "installment_paid_total_cents": paid,
        "outstanding_lien_balance_cents": outstanding_lien_balance_cents(contract["grower_id"]),
    }


# --------------------------------------------------------------------------
# ContractBlockAllocation
# --------------------------------------------------------------------------
def allocation_delivered_net_tons(allocation):
    total = ZERO3
    for line in lines_of_contract(allocation["contract_id"]):
        if line["status"] not in LIVE_LINE:
            continue
        tag = DB["weigh_tags"].get(line["weigh_tag_id"])
        if tag is None or tag["block_id"] != allocation["block_id"]:
            continue
        total += D(line["tons"])
    return q3(total)


def allocation_bucket_tons(allocation, buckets):
    total = ZERO3
    for line in lines_of_contract(allocation["contract_id"]):
        if line["status"] not in LIVE_LINE:
            continue
        if line["bucket"] not in buckets:
            continue
        tag = DB["weigh_tags"].get(line["weigh_tag_id"])
        if tag is None or tag["block_id"] != allocation["block_id"]:
            continue
        total += D(line["tons"])
    return q3(total)


def allocation_json(row):
    delivered = allocation_delivered_net_tons(row)
    out = {
        "id": row["id"],
        "contract_id": row["contract_id"],
        "block_id": row["block_id"],
        "allocated_acres": row["allocated_acres"],
        "block_cap_tons": row["block_cap_tons"],
        "block_hard_cap_tons": row["block_hard_cap_tons"],
        "delivered_net_tons": delivered,
        "delivered_tons": delivered,
    }
    _stamp(out, row)
    return out


# --------------------------------------------------------------------------
# CrushPadLane
# --------------------------------------------------------------------------
def lane_appointments(lane_id):
    return [a for a in DB["appointments"].values()
            if a["lane_id"] == lane_id and a["status"] in LANE_BUSY]


def lane_json(row):
    busy = lane_appointments(row["id"])
    committed = ZERO3
    for appointment in busy:
        committed += D(appointment["planned_tons"])
    out = {
        "id": row["id"],
        "lane_code": row["lane_code"],
        "daily_capacity_tons": row["daily_capacity_tons"],
        "turnaround_buffer_minutes": row["turnaround_buffer_minutes"],
        "max_load_tons": row["max_load_tons"],
        "status": row["status"],
        "committed_tons": q3(committed),
        "scheduled_appointment_count": len(busy),
    }
    _stamp(out, row)
    return out


# --------------------------------------------------------------------------
# SamplingCrew
# --------------------------------------------------------------------------
def crew_scheduled_visit_count(crew_id):
    return len([v for v in DB["visits"].values()
                if v["crew_id"] == crew_id and v["status"] in ("SCHEDULED", "COMPLETED")])


def crew_json(row):
    out = {
        "id": row["id"],
        "crew_code": row["crew_code"],
        "region_code": row["region_code"],
        "max_concurrent_visits": row["max_concurrent_visits"],
        "scheduled_visit_count": crew_scheduled_visit_count(row["id"]),
    }
    _stamp(out, row)
    return out


# --------------------------------------------------------------------------
# SamplingVisit
# --------------------------------------------------------------------------
def visit_json(row):
    out = {
        "id": row["id"],
        "contract_id": row["contract_id"],
        "block_id": row["block_id"],
        "crew_id": row["crew_id"],
        "window_start": iso_clock(row["window_start"]),
        "window_end": iso_clock(row["window_end"]),
        "status": row["status"],
        "measured_brix": row["measured_brix"],
        "measured_ta_gl": row["measured_ta_gl"],
        "measured_ph": row["measured_ph"],
        "measured_rot_pct": row["measured_rot_pct"],
        "sampled_at": iso_clock(row["sampled_at"]),
        "maturity_flag": row["maturity_flag"],
    }
    _stamp(out, row)
    return out


# --------------------------------------------------------------------------
# PickCall
# --------------------------------------------------------------------------
def pick_call_appointed_tons(pick_call_id):
    total = ZERO3
    for appointment in appointments_of_pick_call(pick_call_id):
        if appointment["status"] in LANE_BUSY:
            total += D(appointment["planned_tons"])
    return q3(total)


def pick_call_delivered_net_tons(pick_call_id):
    total = ZERO3
    for appointment in appointments_of_pick_call(pick_call_id):
        for tag in tags_of_appointment(appointment["id"]):
            if tag["weigh_status"] != "NET_FINAL":
                continue
            if tag["disposition"] not in ACCEPTED_SET:
                continue
            total += D(tag["net_tons"] or 0)
    return q3(total)


def pick_call_fulfillment_pct(row):
    delivered = pick_call_delivered_net_tons(row["id"])
    estimated = D(row["estimated_tons"])
    if estimated == 0:
        return q1(Decimal("0"))
    return q1(delivered / estimated * D(100))


def pick_call_json(row):
    out = {
        "id": row["id"],
        "contract_id": row["contract_id"],
        "block_id": row["block_id"],
        "target_pick_at": iso_clock(row["target_pick_at"]),
        "estimated_tons": row["estimated_tons"],
        "issued_at": iso_clock(row["issued_at"]),
        "notice_hours": row["notice_hours"],
        "ack_deadline_at": iso_clock(row["ack_deadline_at"]),
        "acknowledged_at": iso_clock(row["acknowledged_at"]),
        "revision_count": row["revision_count"],
        "status": row["status"],
        "appointed_tons": pick_call_appointed_tons(row["id"]),
        "delivered_net_tons": pick_call_delivered_net_tons(row["id"]),
        "fulfillment_pct": pick_call_fulfillment_pct(row),
    }
    _stamp(out, row)
    return out


# --------------------------------------------------------------------------
# DeliveryAppointment
# --------------------------------------------------------------------------
def appointment_captured_net_tons(appointment_id):
    total = ZERO3
    for tag in tags_of_appointment(appointment_id):
        if tag["weigh_status"] == "NET_FINAL":
            total += D(tag["net_tons"] or 0)
    return q3(total)


def appointment_json(row):
    out = {
        "id": row["id"],
        "pick_call_id": row["pick_call_id"],
        "lane_id": row["lane_id"],
        "window_start": iso_clock(row["window_start"]),
        "window_end": iso_clock(row["window_end"]),
        "planned_tons": row["planned_tons"],
        "status": row["status"],
        "captured_net_tons": appointment_captured_net_tons(row["id"]),
        "weigh_tag_count": len(tags_of_appointment(row["id"])),
    }
    _stamp(out, row)
    return out


# --------------------------------------------------------------------------
# WeighTag
# --------------------------------------------------------------------------
def tag_json(row):
    grade = active_grade(row["id"])
    out = {
        "id": row["id"],
        "appointment_id": row["appointment_id"],
        "block_id": row["block_id"],
        "gross_weight_lbs": row["gross_weight_lbs"],
        "tare_weight_lbs": row["tare_weight_lbs"],
        "net_weight_lbs": row["net_weight_lbs"],
        "net_tons": row["net_tons"],
        "weigh_status": row["weigh_status"],
        "disposition": row["disposition"],
        "captured_by_user_id": row["captured_by_user_id"],
        "grade_count": len(grades_of_tag(row["id"])),
        "active_adjustment_pct": grade["adjustment_pct"] if grade else None,
        "contract_slice_tons": row["contract_slice_tons"],
        "over_slice_tons": row["over_slice_tons"],
        "over_rejected_tons": row["over_rejected_tons"],
        "excess_rejected_tons": row["excess_rejected_tons"],
        "dispute_deadline_at": iso_clock(row["dispute_deadline_at"]),
    }
    _stamp(out, row)
    return out


# --------------------------------------------------------------------------
# QualityGrade -- id and created_at only, no updated_at and no version
# --------------------------------------------------------------------------
def grade_json(row):
    return {
        "id": row["id"],
        "weigh_tag_id": row["weigh_tag_id"],
        "brix": row["brix"],
        "ta_gl": row["ta_gl"],
        "ph": row["ph"],
        "rot_pct": row["rot_pct"],
        "mog_pct": row["mog_pct"],
        "graded_by_user_id": row["graded_by_user_id"],
        "brix_component_pct": row["brix_component_pct"],
        "acid_component_pct": row["acid_component_pct"],
        "rot_component_pct": row["rot_component_pct"],
        "mog_component_pct": row["mog_component_pct"],
        "raw_adjustment_pct": row["raw_adjustment_pct"],
        "adjustment_pct": row["adjustment_pct"],
        "recommended_disposition": row["recommended_disposition"],
        "superseded_at": iso_clock(row["superseded_at"]),
        "created_at": iso_ms(row["created_at"]),
    }


# --------------------------------------------------------------------------
# SettlementLine
# --------------------------------------------------------------------------
def line_json(row):
    out = {
        "id": row["id"],
        "weigh_tag_id": row["weigh_tag_id"],
        "contract_id": row["contract_id"],
        "bucket": row["bucket"],
        "tons": row["tons"],
        "adjustment_pct_applied": row["adjustment_pct_applied"],
        "applied_adjustment_pct": row["adjustment_pct_applied"],
        "price_per_ton_cents": row["price_per_ton_cents"],
        "gross_amount_cents": row["gross_amount_cents"],
        "provisional_amount_cents": row["provisional_amount_cents"],
        "final_amount_cents": row["final_amount_cents"],
        "status": row["status"],
        "voided_at": iso_clock(row["voided_at"]),
    }
    _stamp(out, row)
    return out


# --------------------------------------------------------------------------
# PaymentInstallment
# --------------------------------------------------------------------------
def installment_json(row):
    out = {
        "id": row["id"],
        "contract_id": row["contract_id"],
        "installment_no": row["installment_no"],
        "pct_of_settlement": row["pct_of_settlement"],
        "due_offset_days": row["due_offset_days"],
        "lien_protected": row["lien_protected"],
        "planned_amount_cents": row["planned_amount_cents"],
        "paid_amount_cents": row["paid_amount_cents"],
        "due_at": iso_clock(row["due_at"]),
        "status": row["status"],
    }
    _stamp(out, row)
    return out

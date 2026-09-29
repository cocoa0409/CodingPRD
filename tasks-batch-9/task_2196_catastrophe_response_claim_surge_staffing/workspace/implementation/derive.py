"""Derived roll-ups, event posture, and resource serialization."""
from decimal import Decimal

import calc
import store
from store import (clock_now, dec, money, out_money, fmt_dt, sorted_rows,
                   whole_days_between, hours_between)


# --------------------------------------------------------------------------
# Simple selectors
# --------------------------------------------------------------------------
def rows(coll, **filters):
    out = []
    for rec in coll.values():
        keep = True
        for key, val in filters.items():
            if rec.get(key) != val:
                keep = False
                break
        if keep:
            out.append(rec)
    return out


def entries_for_event(event_id):
    return [e for e in store.reserve_entries.values() if e["event_id"] == event_id]


def entries_for_claim(claim_id):
    return [e for e in store.reserve_entries.values() if e["claim_id"] == claim_id]


def next_sequence_no(event_id):
    high = 0
    for e in entries_for_event(event_id):
        if e["sequence_no"] > high:
            high = e["sequence_no"]
    return high + 1


def sequence_high_water(event_id):
    high = 0
    for e in entries_for_event(event_id):
        if e["sequence_no"] > high:
            high = e["sequence_no"]
    return high


# --------------------------------------------------------------------------
# Claim roll-ups
# --------------------------------------------------------------------------
def claim_case_reserve(claim_id):
    total = Decimal(0)
    for e in entries_for_claim(claim_id):
        total += dec(e["delta_case_reserve"])
    return money(total)


def claim_paid_amount(claim_id):
    total = Decimal(0)
    for e in entries_for_claim(claim_id):
        total += dec(e["delta_paid"])
    return money(total)


def claim_advance_paid_total(claim_id):
    total = Decimal(0)
    for a in store.advances.values():
        if a["claim_id"] == claim_id and a["status"] == "ISSUED":
            total += dec(a["amount"])
    return money(total)


def governing_mandate_pct(event_id):
    """Greatest mandated_advance_pct in force; ties broken by earliest created_at."""
    if event_id is None:
        return None
    best = None
    for b in sorted_rows(effective_bulletins(event_id, "ADVANCE_PAYMENT_MANDATE")):
        pct = dec(b["mandated_advance_pct"])
        if best is None or pct > best:
            best = pct
    return best


def claim_advance_cap(claim):
    """Step 5 of advance_payment_amount; 0.00 until a tier has been stamped."""
    if claim.get("triage_tier") is None:
        return money(0)
    return calc.advance_cap(claim, governing_mandate_pct(claim["event_id"]))


def claim_verified_damage(claim_id):
    best = None
    for a in store.assignments.values():
        if a["claim_id"] != claim_id or a["status"] != "COMPLETED":
            continue
        if a.get("report_submitted_at_utc") is None:
            continue
        key = (a["report_submitted_at_utc"], -a["_seq"])
        if best is None or key > best[0]:
            best = (key, a)
    if best is None:
        return None
    return best[1].get("verified_damage_amount")


# --------------------------------------------------------------------------
# Event roll-ups
# --------------------------------------------------------------------------
def event_case_reserve_total(event_id):
    total = Decimal(0)
    for e in entries_for_event(event_id):
        total += dec(e["delta_case_reserve"])
    return money(total)


def event_paid_total(event_id):
    total = Decimal(0)
    for e in entries_for_event(event_id):
        total += dec(e["delta_paid"])
    return money(total)


def event_incurred_total(event_id):
    return money(event_case_reserve_total(event_id) + event_paid_total(event_id))


def event_open_claim_count(event_id):
    return len([c for c in store.claims.values()
                if c["event_id"] == event_id
                and c["handling_status"] not in ("CLOSED", "TRANSFERRED")])


def event_surge_adjuster_count(event_id):
    return len([d for d in store.deployments.values()
                if d["event_id"] == event_id
                and d["status"] in ("CONFIRMED", "ON_SITE")])


def block_night_count(block):
    return whole_days_between(block["block_start_date"], block["block_end_date"])


def event_housing_committed_cost(event_id):
    total = Decimal(0)
    for b in store.housing_blocks.values():
        if b["event_id"] == event_id and b["status"] in ("PENDING", "ACTIVE", "EXHAUSTED"):
            total += dec(b["nightly_rate"]) * Decimal(int(b["rooms_total"])) \
                * Decimal(block_night_count(b))
    return money(total)


def event_deployment_settled_cost(event_id):
    total = Decimal(0)
    for d in store.deployments.values():
        if d["event_id"] == event_id and d["status"] == "DEMOBILIZED":
            total += dec(d["final_settled_cost"])
    return money(total)


def snapshot_stale(snap):
    return sequence_high_water(snap["event_id"]) > snap["input_reserve_sequence_high_water"]


def latest_snapshot(event_id):
    best = None
    for s in store.loss_estimates.values():
        if s["event_id"] != event_id:
            continue
        key = (s["computed_at_utc"], -s["_seq"])
        if best is None or key > best[0]:
            best = (key, s)
    return best[1] if best else None


def event_gross_loss_estimate(event_id):
    snap = latest_snapshot(event_id)
    if snap is None:
        return money(0)
    return money(snap["gross_estimate"])


def bulletin_in_force(bulletin, now=None):
    now = now or clock_now()
    return (bulletin["status"] == "EFFECTIVE"
            and bulletin["effective_from"] <= now < bulletin["effective_to"])


def effective_bulletins(event_id, bulletin_type):
    now = clock_now()
    return [b for b in store.bulletins.values()
            if b["event_id"] == event_id and b["bulletin_type"] == bulletin_type
            and bulletin_in_force(b, now)]


def event_moratorium_active(event_id):
    return len(effective_bulletins(event_id, "CANCELLATION_MORATORIUM")) > 0


def event_posture(event):
    status = event["status"]
    if status == "CLOSED":
        floor = "FROZEN"
    elif status == "DEMOBILIZING":
        floor = "RESTRICTED"
    else:
        floor = "OPEN"
    unassigned_severe = len([c for c in store.claims.values()
                             if c["event_id"] == event["id"]
                             and c.get("triage_tier") in ("COMPLEX", "CAT_SEVERE")
                             and c["handling_status"] in ("TRIAGED", "REOPENED")])
    snap = latest_snapshot(event["id"])
    stale_flag = 1 if (snap is not None and snapshot_stale(snap)) else 0
    moratorium_flag = 1 if event_moratorium_active(event["id"]) else 0
    strain = unassigned_severe + (3 * stale_flag) + (4 * moratorium_flag)
    if strain >= calc.FROZEN_STRAIN_THRESHOLD:
        band = "FROZEN"
    elif strain >= calc.RESTRICTED_STRAIN_THRESHOLD:
        band = "RESTRICTED"
    else:
        band = "OPEN"
    return calc.stricter(floor, band)


# --------------------------------------------------------------------------
# Adjuster roll-ups
# --------------------------------------------------------------------------
def adjuster_open_assignment_count(adjuster_id):
    return len([a for a in store.assignments.values()
                if a["adjuster_id"] == adjuster_id
                and a["status"] in ("SCHEDULED", "IN_PROGRESS")])


def adjuster_cumulative_hours(adjuster_id):
    total = Decimal(0)
    for d in store.deployments.values():
        if d["adjuster_id"] == adjuster_id and d["status"] in ("ON_SITE", "DEMOBILIZED"):
            total += hours_between(d["window_start_utc"], d["window_end_utc"])
    return money(total)


def adjuster_score(adjuster):
    return calc.surge_capacity_score(
        adjuster,
        adjuster_open_assignment_count(adjuster["id"]),
        adjuster_cumulative_hours(adjuster["id"]))


def block_rooms_occupied(block_id):
    total = 0
    for d in store.deployments.values():
        if d.get("housing_block_id") == block_id and d["status"] in ("CONFIRMED", "ON_SITE"):
            total += int(d["rooms_reserved"])
    return total


def firm_open_job_count(firm_id):
    return len([v for v in store.vendor_assignments.values()
                if v["vendor_firm_id"] == firm_id
                and v["status"] in ("DISPATCHED", "ACCEPTED")])


def batch_claim_count(batch_id):
    return len([c for c in store.claims.values() if c.get("transfer_batch_id") == batch_id])


def batch_blocking_claim_count(batch_id):
    total = 0
    for c in store.claims.values():
        if c.get("transfer_batch_id") != batch_id:
            continue
        if c["payment_status"] == "ADVANCE_ISSUED" \
                or claim_case_reserve(c["id"]) == money(0):
            total += 1
    return total


# --------------------------------------------------------------------------
# Serialization
# --------------------------------------------------------------------------
def _common(rec, out):
    out["id"] = rec["id"]
    out["created_at"] = fmt_dt(rec["created_at"])
    if "updated_at" in rec:
        out["updated_at"] = fmt_dt(rec["updated_at"])
    if "version" in rec:
        out["version"] = rec["version"]
    return out


def event_out(rec):
    out = {
        "cat_code": rec["cat_code"],
        "peril_type": rec["peril_type"],
        "jurisdiction_state": rec["jurisdiction_state"],
        "event_start_utc": fmt_dt(rec["event_start_utc"]),
        "exposure_count": rec["exposure_count"],
        "avg_insured_value": float(dec(rec["avg_insured_value"])),
        "expected_severity_index": float(dec(rec["expected_severity_index"])),
        "status": rec["status"],
        "posture": event_posture(rec),
        "declared_at_utc": fmt_dt(rec["declared_at_utc"]),
        "open_claim_count": event_open_claim_count(rec["id"]),
        "case_reserve_total": out_money(event_case_reserve_total(rec["id"])),
        "paid_total": out_money(event_paid_total(rec["id"])),
        "incurred_total": out_money(event_incurred_total(rec["id"])),
        "housing_committed_cost": out_money(event_housing_committed_cost(rec["id"])),
        "deployment_settled_cost": out_money(event_deployment_settled_cost(rec["id"])),
        "gross_loss_estimate": out_money(event_gross_loss_estimate(rec["id"])),
        "moratorium_active": event_moratorium_active(rec["id"]),
        "surge_adjuster_count": event_surge_adjuster_count(rec["id"]),
    }
    return _common(rec, out)


def bulletin_out(rec):
    out = {
        "event_id": rec["event_id"],
        "bulletin_number": rec["bulletin_number"],
        "jurisdiction_state": rec["jurisdiction_state"],
        "bulletin_type": rec["bulletin_type"],
        "status": rec["status"],
        "effective_from": fmt_dt(rec["effective_from"]),
        "effective_to": fmt_dt(rec["effective_to"]),
        "mandated_advance_pct": float(dec(rec["mandated_advance_pct"])),
        "deadline_extension_days": rec["deadline_extension_days"],
        "activated_at_utc": fmt_dt(rec["activated_at_utc"]),
    }
    return _common(rec, out)


def adjuster_out(rec):
    out = {
        "full_name": rec["full_name"],
        "employment_type": rec["employment_type"],
        "home_state": rec["home_state"],
        "licensed_states": list(rec["licensed_states"]),
        "license_expiry_utc": fmt_dt(rec["license_expiry_utc"]),
        "credential_status": rec["credential_status"],
        "deployment_status": rec["deployment_status"],
        "desk_certified": rec["desk_certified"],
        "aerial_certified": rec["aerial_certified"],
        "max_open_claims": rec["max_open_claims"],
        "open_assignment_count": adjuster_open_assignment_count(rec["id"]),
        "daily_rate": float(dec(rec["daily_rate"])),
        "per_diem_rate": float(dec(rec["per_diem_rate"])),
        "surge_capacity_score": out_money(adjuster_score(rec)),
        "cumulative_deployed_hours": out_money(adjuster_cumulative_hours(rec["id"])),
        "last_demobilized_at_utc": fmt_dt(rec["last_demobilized_at_utc"]),
    }
    return _common(rec, out)


def housing_block_out(rec):
    occupied = block_rooms_occupied(rec["id"])
    out = {
        "event_id": rec["event_id"],
        "hotel_name": rec["hotel_name"],
        "city": rec["city"],
        "rooms_total": rec["rooms_total"],
        "rooms_occupied": occupied,
        "rooms_available": rec["rooms_total"] - occupied,
        "nightly_rate": float(dec(rec["nightly_rate"])),
        "block_start_date": fmt_dt(rec["block_start_date"]),
        "block_end_date": fmt_dt(rec["block_end_date"]),
        "block_night_count": block_night_count(rec),
        "status": rec["status"],
    }
    return _common(rec, out)


def deployment_out(rec):
    out = {
        "event_id": rec["event_id"],
        "adjuster_id": rec["adjuster_id"],
        "housing_block_id": rec["housing_block_id"],
        "role_type": rec["role_type"],
        "window_start_utc": fmt_dt(rec["window_start_utc"]),
        "window_end_utc": fmt_dt(rec["window_end_utc"]),
        "rooms_reserved": rec["rooms_reserved"],
        "status": rec["status"],
        "selection_reason": rec["selection_reason"],
        "provisional_cost": out_money(rec["provisional_cost"]),
        "final_settled_cost": out_money(rec["final_settled_cost"]),
        "surge_premium_tier": rec["surge_premium_tier"],
        "demobilized_at_utc": fmt_dt(rec["demobilized_at_utc"]),
    }
    return _common(rec, out)


def claim_out(rec):
    verified = claim_verified_damage(rec["id"])
    out = {
        "event_id": rec["event_id"],
        "policy_number": rec["policy_number"],
        "loss_state": rec["loss_state"],
        "loss_date_utc": fmt_dt(rec["loss_date_utc"]),
        "reported_at_utc": fmt_dt(rec["reported_at_utc"]),
        "reported_loss_amount": float(dec(rec["reported_loss_amount"])),
        "coverage_lines": [dict(l) for l in rec["coverage_lines"]],
        "access_status": rec["access_status"],
        "handling_status": rec["handling_status"],
        "payment_status": rec["payment_status"],
        "severity_score": out_money(rec["severity_score"]),
        "triage_tier": rec["triage_tier"],
        "inspection_mode": rec["inspection_mode"],
        "advance_cap": out_money(claim_advance_cap(rec)),
        "advance_paid_total": out_money(claim_advance_paid_total(rec["id"])),
        "case_reserve": out_money(claim_case_reserve(rec["id"])),
        "paid_amount": out_money(claim_paid_amount(rec["id"])),
        "verified_damage_amount": None if verified is None else out_money(verified),
        "deadline_utc": fmt_dt(rec["deadline_utc"]),
        "reopen_count": rec["reopen_count"],
        "closing_examiner_user_id": rec["closing_examiner_user_id"],
        "advance_issuing_examiner_user_id": rec["advance_issuing_examiner_user_id"],
        "transfer_batch_id": rec["transfer_batch_id"],
    }
    return _common(rec, out)


def assignment_out(rec):
    verified = rec.get("verified_damage_amount")
    out = {
        "claim_id": rec["claim_id"],
        "adjuster_id": rec["adjuster_id"],
        "deployment_id": rec["deployment_id"],
        "mode": rec["mode"],
        "window_start_utc": fmt_dt(rec["window_start_utc"]),
        "window_end_utc": fmt_dt(rec["window_end_utc"]),
        "status": rec["status"],
        "verified_damage_amount": None if verified is None else out_money(verified),
        "report_submitted_at_utc": fmt_dt(rec["report_submitted_at_utc"]),
        "selection_reason": rec["selection_reason"],
    }
    return _common(rec, out)


def advance_out(rec):
    out = {
        "claim_id": rec["claim_id"],
        "reserve_entry_id": rec["reserve_entry_id"],
        "requested_amount": float(dec(rec["requested_amount"])),
        "amount": out_money(rec["amount"]),
        "basis": rec["basis"],
        "status": rec["status"],
        "void_reason": rec["void_reason"],
        "voided_at_utc": fmt_dt(rec["voided_at_utc"]),
    }
    return _common(rec, out)


def reserve_entry_out(rec):
    # Ledger rows are immutable: id and created_at only, no updated_at/version.
    return {
        "id": rec["id"],
        "created_at": fmt_dt(rec["created_at"]),
        "event_id": rec["event_id"],
        "claim_id": rec["claim_id"],
        "reverses_entry_id": rec["reverses_entry_id"],
        "entry_type": rec["entry_type"],
        "delta_case_reserve": out_money(rec["delta_case_reserve"]),
        "delta_paid": out_money(rec["delta_paid"]),
        "sequence_no": rec["sequence_no"],
        "effective_utc": fmt_dt(rec["effective_utc"]),
        "memo": rec["memo"],
    }


def vendor_firm_out(rec):
    out = {
        "firm_name": rec["firm_name"],
        "vendor_type": rec["vendor_type"],
        "service_states": list(rec["service_states"]),
        "status": rec["status"],
        "activated_for_event_id": rec["activated_for_event_id"],
        "max_concurrent_jobs": rec["max_concurrent_jobs"],
        "open_job_count": firm_open_job_count(rec["id"]),
        "performance_score": out_money(rec["performance_score"]),
    }
    return _common(rec, out)


def vendor_assignment_out(rec):
    out = {
        "claim_id": rec["claim_id"],
        "vendor_firm_id": rec["vendor_firm_id"],
        "scope_amount": float(dec(rec["scope_amount"])),
        "required_vendor_type": rec["required_vendor_type"],
        "status": rec["status"],
        "dispatched_at_utc": fmt_dt(rec["dispatched_at_utc"]),
        "selection_reason": rec["selection_reason"],
    }
    return _common(rec, out)


def loss_estimate_out(rec):
    # Snapshots are immutable: id and created_at only, no updated_at/version.
    return {
        "id": rec["id"],
        "created_at": fmt_dt(rec["created_at"]),
        "event_id": rec["event_id"],
        "method": rec["method"],
        "gross_estimate": out_money(rec["gross_estimate"]),
        "ibnr_component": out_money(rec["ibnr_component"]),
        "reported_component": out_money(rec["reported_component"]),
        "input_reserve_sequence_high_water": rec["input_reserve_sequence_high_water"],
        "stale": snapshot_stale(rec),
        "computed_at_utc": fmt_dt(rec["computed_at_utc"]),
    }


def batch_out(rec):
    out = {
        "event_id": rec["event_id"],
        "target_unit": rec["target_unit"],
        "status": rec["status"],
        "claim_count": batch_claim_count(rec["id"]),
        "blocking_claim_count": batch_blocking_claim_count(rec["id"]),
        "submitted_at_utc": fmt_dt(rec["submitted_at_utc"]),
        "rejection_reason": rec["rejection_reason"],
    }
    return _common(rec, out)

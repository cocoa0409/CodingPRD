"""Business logic: sweeps, cascades, and calculation rules.

Calculation rules implemented per SCAFFOLD.yaml Table 3:
- demurrage_charge (PROVISIONAL / FINAL variants)
- storage_charge (pinned rounding order)
- construction_cost_share (ESTIMATED / FINAL / SETTLE)
- liability_allocation (capped)
- inspection_cadence_scheduling
- removal_penalty
- renewal_extension
"""
from datetime import date
from decimal import Decimal

from db import DB, LOGICAL_CLOCK, new_id, now_iso
from errors import ApiError
from util import (
    add_days,
    add_months,
    date_to_str,
    format_iso,
    logical_now_dt,
    logical_today,
    parse_dt,
    parse_ymd,
    round_half_up_2dp,
    round_half_up_int,
    whole_days_between,
)


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------

def touch(entity):
    """Increment version and refresh updated_at on an entity."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = now_iso()


def mint_common_fields(entity):
    entity["id"] = new_id()
    ts = now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1


# ---------------------------------------------------------------------------
# Agreement helpers and sweeps
# ---------------------------------------------------------------------------

def get_agreement_or_404(agreement_id):
    a = DB["agreements"].get(agreement_id)
    if a is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND", 404, "TrackAgreement not found")
    return a


def apply_expiry_sweep_to_agreement(agreement):
    """ACTIVE/RENEWAL_OFFERED -> EXPIRED when current logical date > term_end_date."""
    if agreement.get("status") in ("ACTIVE", "RENEWAL_OFFERED"):
        end = parse_ymd(agreement["term_end_date"])
        if logical_today() > end:
            agreement["status"] = "EXPIRED"
            touch(agreement)


def apply_overdue_sweep_to_inspection(insp):
    """SCHEDULED -> OVERDUE when current logical date > due_date."""
    if insp.get("status") == "SCHEDULED":
        due = parse_ymd(insp["due_date"])
        if logical_today() > due:
            insp["status"] = "OVERDUE"
            touch(insp)


def run_global_sweeps():
    """Run both sweeps across all rows (invoked on clock-set)."""
    for a in DB["agreements"].values():
        apply_expiry_sweep_to_agreement(a)
    for insp in DB["inspections"].values():
        apply_overdue_sweep_to_inspection(insp)


def accepted_claims_liability_sum(agreement_id):
    total = 0
    for c in DB["liability_claims"].values():
        if c.get("agreement_id") == agreement_id and c.get("status") == "ACCEPTED":
            total += c.get("shipper_liability_cents") or 0
    return total


def has_open_claims(agreement_id):
    for c in DB["liability_claims"].values():
        if c.get("agreement_id") == agreement_id and c.get("status") in (
            "FILED",
            "APPORTIONED",
            "DISPUTED",
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def compute_demurrage(dwell, agreement, variant, released_at_dt=None):
    """Return (dwell_minutes, chargeable_days, amount_cents).

    variant: 'PROVISIONAL' (uses logical clock) or 'FINAL' (uses released_at_dt).
    """
    placed_at = parse_dt(dwell["placed_at"])
    if variant == "FINAL":
        effective_to = released_at_dt
    else:
        effective_to = logical_now_dt()
    total_seconds = int((effective_to - placed_at).total_seconds())
    total_minutes = total_seconds // 60
    free_minutes = int(agreement["free_time_hours"]) * 60
    if dwell["car_ownership"] == "PRIVATE":
        free_minutes = free_minutes * 2
    chargeable_minutes = total_minutes - free_minutes
    if chargeable_minutes <= 0:
        return total_minutes, 0, 0
    chargeable_days = (chargeable_minutes + 1439) // 1440  # ceil
    tier1_days = min(chargeable_days, 2)
    tier2_days = chargeable_days - tier1_days
    amount = (
        tier1_days * int(agreement["demurrage_base_rate_cents"])
        + tier2_days * int(agreement["demurrage_escalated_rate_cents"])
    )
    return total_minutes, chargeable_days, amount


def refresh_provisional_demurrage(dwell):
    """Recompute accrued_demurrage_cents for SPOTTED dwells (read-time)."""
    if dwell.get("status") != "SPOTTED":
        return
    agreement = DB["agreements"].get(dwell["agreement_id"])
    if agreement is None:
        return
    minutes, _days, amount = compute_demurrage(dwell, agreement, "PROVISIONAL")
    dwell["dwell_minutes"] = minutes
    dwell["accrued_demurrage_cents"] = amount


def compute_storage_charge(placement, agreement, effective_release_date):
    """Return (days_charged, final_storage_charge_cents). Pinned rounding order."""
    placed_date = parse_ymd(placement["placed_date"])
    days = whole_days_between(placed_date, effective_release_date)
    days_charged = max(1, days)
    monthly = Decimal(int(agreement["storage_rate_per_car_month_cents"]))
    daily_rate = round_half_up_2dp(monthly / Decimal(30))
    per_car = round_half_up_int(daily_rate * Decimal(days_charged))
    return days_charged, per_car


def refresh_provisional_storage_charge(placement):
    """Recompute accrued_storage_charge_cents for STORED placements (read-time)."""
    if placement.get("status") != "STORED":
        return
    segment = DB["segments"].get(placement["segment_id"])
    if segment is None:
        return
    agreement = DB["agreements"].get(segment["agreement_id"])
    if agreement is None:
        return
    today = logical_today()
    days_charged, per_car = compute_storage_charge(placement, agreement, today)
    placement["accrued_storage_charge_cents"] = per_car


def recompute_segment_storage_ledger(segment):
    """stored_car_count = count of STORED; accrued_storage_cents = sum over RELEASED/FORCE_RELEASED."""
    stored = 0
    accrued = 0
    for p in DB["storage_placements"].values():
        if p.get("segment_id") != segment["id"]:
            continue
        if p.get("status") == "STORED":
            stored += 1
        elif p.get("status") in ("RELEASED", "FORCE_RELEASED"):
            accrued += p.get("final_storage_charge_cents") or 0
    segment["stored_car_count"] = stored
    segment["accrued_storage_cents"] = accrued


def compute_cost_share(amount_cents, pct):
    """round_half_up(amount_cents * pct / 100, 0) as integer cents."""
    amount = Decimal(int(amount_cents))
    pct_d = Decimal(str(pct))
    return round_half_up_int(amount * pct_d / Decimal(100))


def compute_liability_allocation(claim, agreement, fault_pct):
    """Return (shipper_liability_cents, railroad_liability_cents)."""
    raw = compute_cost_share(claim["claim_amount_cents"], fault_pct)
    accepted_sum = accepted_claims_liability_sum(agreement["id"])
    cap_remaining = int(agreement["liability_cap_cents"]) - accepted_sum
    shipper = min(raw, cap_remaining)
    if shipper < 0:
        shipper = 0
    railroad = int(claim["claim_amount_cents"]) - shipper
    return shipper, railroad


def compute_removal_penalty(agreement, removal_verified_date):
    """max(0, verified - deadline in days) * per-day penalty."""
    deadline = parse_ymd(agreement["removal_deadline_date"])
    days_late = whole_days_between(deadline, removal_verified_date)
    if days_late < 0:
        days_late = 0
    return days_late * int(agreement["removal_penalty_per_day_cents"])


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def cascade_terminate(agreement):
    """ACTIVE -> TERMINATED side effects: cancel REQUESTED orders, supersede PENDING amendments."""
    for so in DB["service_orders"].values():
        if so.get("agreement_id") == agreement["id"] and so.get("status") == "REQUESTED":
            so["status"] = "CANCELLED"
            touch(so)
    for am in DB["amendments"].values():
        if am.get("agreement_id") == agreement["id"] and am.get("status") == "PENDING":
            am["status"] = "SUPERSEDED"
            touch(am)


def cascade_file_abandonment(agreement, notice_date):
    """TERMINATED/EXPIRED -> ABANDONMENT_IN_PROGRESS cascade chain.

    Link 1: segments IN_SERVICE -> OUT_OF_SERVICE
    Link 2 (per segment): STORED placements -> FORCE_RELEASED, REQUESTED orders -> CANCELLED
    Link 3 (per placement): segment ledger recompute
    """
    notice_d = parse_ymd(notice_date)
    agreement["abandonment_notice_date"] = notice_date
    agreement["removal_deadline_date"] = date_to_str(
        add_days(notice_d, int(agreement["removal_period_days"]))
    )
    for seg in DB["segments"].values():
        if seg.get("agreement_id") != agreement["id"]:
            continue
        if seg.get("status") != "IN_SERVICE":
            continue
        seg["status"] = "OUT_OF_SERVICE"
        touch(seg)
        # Link 2: placements and orders on this segment
        for p in DB["storage_placements"].values():
            if p.get("segment_id") == seg["id"] and p.get("status") == "STORED":
                p["status"] = "FORCE_RELEASED"
                p["released_date"] = notice_date
                days_charged, charge = compute_storage_charge(p, agreement, notice_d)
                p["days_charged"] = days_charged
                p["final_storage_charge_cents"] = charge
                touch(p)
        for so in DB["service_orders"].values():
            if so.get("segment_id") == seg["id"] and so.get("status") == "REQUESTED":
                so["status"] = "CANCELLED"
                touch(so)
        # Link 3: recompute the segment ledger
        before_count = seg.get("stored_car_count")
        before_accrued = seg.get("accrued_storage_cents")
        recompute_segment_storage_ledger(seg)
        if (
            seg.get("stored_car_count") != before_count
            or seg.get("accrued_storage_cents") != before_accrued
        ):
            touch(seg)


def cascade_verify_removal(agreement, removal_verified_date):
    """ABANDONMENT_IN_PROGRESS -> CLOSED side effects."""
    verified_d = parse_ymd(removal_verified_date)
    agreement["removal_penalty_cents"] = compute_removal_penalty(agreement, verified_d)
    for seg in DB["segments"].values():
        if seg.get("agreement_id") == agreement["id"] and seg.get("status") == "OUT_OF_SERVICE":
            seg["status"] = "REMOVED"
            touch(seg)


def cascade_inspection_result(inspection, result, cited_ids):
    """Device + segment safety_suspended cascades; auto-schedule next inspection.

    PASS: cited NON_COMPLIANT -> INSTALLED; if none on segment remain NON_COMPLIANT,
          segment.safety_suspended := false
    FAIL: cited INSTALLED -> NON_COMPLIANT; if any on segment now NON_COMPLIANT,
          segment.safety_suspended := true
    """
    segment = DB["segments"].get(inspection["segment_id"])
    if segment is None:
        return
    agreement = DB["agreements"].get(inspection["agreement_id"])
    for dev_id in cited_ids:
        dev = DB["derail_devices"].get(dev_id)
        if dev is None:
            continue
        if result == "PASS" and dev.get("status") == "NON_COMPLIANT":
            dev["status"] = "INSTALLED"
            touch(dev)
        elif result == "FAIL" and dev.get("status") == "INSTALLED":
            dev["status"] = "NON_COMPLIANT"
            touch(dev)
    # Recompute segment safety_suspended
    any_non_compliant = False
    for dev in DB["derail_devices"].values():
        if dev.get("segment_id") == segment["id"] and dev.get("status") == "NON_COMPLIANT":
            any_non_compliant = True
            break
    new_suspended = any_non_compliant
    if segment.get("safety_suspended") != new_suspended:
        segment["safety_suspended"] = new_suspended
        touch(segment)
    # Auto-schedule next inspection
    if agreement is not None:
        next_insp = {
            "agreement_id": inspection["agreement_id"],
            "segment_id": inspection["segment_id"],
            "scheduled_date": date_to_str(
                add_days(
                    parse_ymd(inspection["completed_date"]),
                    int(agreement["inspection_cadence_days"]),
                )
            ),
            "result": None,
            "completed_date": None,
            "cited_device_ids": [],
            "status": "SCHEDULED",
        }
        next_insp["due_date"] = next_insp["scheduled_date"]
        mint_common_fields(next_insp)
        DB["inspections"][next_insp["id"]] = next_insp


def supersede_pending_amendments(agreement_id):
    """Move all PENDING amendments on this agreement to SUPERSEDED."""
    for am in DB["amendments"].values():
        if am.get("agreement_id") == agreement_id and am.get("status") == "PENDING":
            am["status"] = "SUPERSEDED"
            touch(am)


def apply_amendment_to_agreement(amendment, agreement):
    """Apply amendment new_* fields to the agreement per amendment_type."""
    t = amendment["amendment_type"]
    if t == "COST_SHARE":
        agreement["shipper_cost_share_pct"] = amendment["new_shipper_cost_share_pct"]
    elif t == "LIABILITY_CAP":
        agreement["liability_cap_cents"] = amendment["new_liability_cap_cents"]
    elif t == "STORAGE_RATE":
        agreement["storage_rate_per_car_month_cents"] = amendment[
            "new_storage_rate_per_car_month_cents"
        ]
    elif t == "DEMURRAGE_RATES":
        agreement["demurrage_base_rate_cents"] = amendment[
            "new_demurrage_base_rate_cents"
        ]
        agreement["demurrage_escalated_rate_cents"] = amendment[
            "new_demurrage_escalated_rate_cents"
        ]
    elif t == "TERM":
        agreement["term_end_date"] = amendment["new_term_end_date"]


def extend_agreement_term(agreement):
    """renewal_extension: term_end_date += renewal_term_months, day-of-month preserved."""
    end = parse_ymd(agreement["term_end_date"])
    new_end = add_months(end, int(agreement["renewal_term_months"]))
    agreement["term_end_date"] = date_to_str(new_end)

"""Adequacy evaluation finalize: 4-link cascade (PRD §3.7)."""

import math
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import db
import helpers

# Penalty constants (scaffold §1.3)
BASE_DAILY_PENALTY_CENTS = 9999
PENALTY_CAP_CENTS = 5000000
TIER1_MEMBER_THRESHOLD = 10000
TIER2_MEMBER_THRESHOLD = 50000
REPEAT_STEP = Decimal("0.5")
REPEAT_CAP = 3
PER_ERROR_PENALTY_CENTS = 25000
LATE_CORRECTION_PENALTY_CENTS = 50000


def _find_standard(specialty, geo_class):
    for s in db.standards.values():
        if s["specialty"] == specialty and s["geo_class"] == geo_class:
            return s
    return None


def _counted_listings(region_id, specialty):
    """LISTED listings of this specialty, on OPEN-panel locations in this region,
    owned by EFFECTIVE providers."""
    out = []
    for lst in db.listings.values():
        if lst["status"] != "LISTED":
            continue
        if lst["specialty"] != specialty:
            continue
        loc = db.locations.get(lst["location_id"])
        if loc is None or loc["region_id"] != region_id:
            continue
        if loc["panel_status"] != "OPEN":
            continue
        prov = db.providers.get(lst["provider_id"])
        if prov is None or prov["status"] != "EFFECTIVE":
            continue
        out.append(lst)
    return out


def _round2(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _period_bounds(evaluation):
    start = helpers.parse_date(evaluation["period_start_date"], "period_start_date")
    end = helpers.parse_date(evaluation["period_end_date"], "period_end_date")
    return start, end


def _ts_within(ts_iso, start: date, end: date) -> bool:
    """Timestamp (ISO) date within closed [start, end]."""
    if ts_iso is None:
        return False
    d = helpers.parse_iso_datetime(ts_iso).date()
    return start <= d <= end


def _approved_excuse_covers(region_id, specialty, period_end: date):
    """An APPROVED AccessPlanRequest for a deficiency of this (region, specialty)
    whose excuse_through_date >= period_end_date."""
    for apr in db.access_plan_requests.values():
        if apr["status"] != "APPROVED":
            continue
        d = db.deficiencies.get(apr["deficiency_id"])
        if d is None:
            continue
        if d["region_id"] != region_id or d["specialty"] != specialty:
            continue
        through = helpers.parse_date(apr["excuse_through_date"], "excuse_through_date")
        if through >= period_end:
            return True
    return False


def _compute_result_row(evaluation, region, specialty, standard, period_start, period_end):
    counted = _counted_listings(region["id"], specialty)
    provider_ids = {lst["provider_id"] for lst in counted}
    provider_count = len(provider_ids)
    listing_count = len(counted)
    member_count = region["enrolled_member_count"]

    # ratio
    if provider_count > 0:
        ratio = _round2(Decimal(member_count) / Decimal(provider_count))
        ratio_ok = member_count <= standard["max_members_per_provider"] * provider_count
    else:
        ratio = None
        ratio_ok = (member_count == 0)

    # time/distance
    counted_loc_ids = {lst["location_id"] for lst in counted}
    counted_location_count = len(counted_loc_ids)
    compliant_location_count = 0
    for loc_id in counted_loc_ids:
        loc = db.locations[loc_id]
        if (loc["avg_travel_minutes"] <= standard["max_travel_minutes"]
                and loc["avg_travel_miles"] <= standard["max_travel_miles"]):
            compliant_location_count += 1
    if counted_location_count > 0:
        time_distance_compliant = (10 * compliant_location_count) >= (9 * counted_location_count)
    else:
        time_distance_compliant = (member_count == 0)

    # wait time — RECORDED ROUTINE probes on counted listings, recorded_at date in
    # period, days_to_appointment non-null
    counted_listing_ids = {lst["id"] for lst in counted}
    days_list = []
    for p in db.probes.values():
        if p["status"] != "RECORDED":
            continue
        if p["listing_id"] not in counted_listing_ids:
            continue
        if p["probe_type"] != "ROUTINE":
            continue
        if p["days_to_appointment"] is None:
            continue
        if not _ts_within(p["recorded_at"], period_start, period_end):
            continue
        days_list.append(p["days_to_appointment"])
    probed_listing_count = len(days_list)
    if days_list:
        mean_raw = Decimal(sum(days_list)) / Decimal(len(days_list))
        mean_wait = _round2(mean_raw)
        sorted_days = sorted(days_list)
        idx = math.ceil(0.9 * len(sorted_days))  # 1-based index
        p90_wait = sorted_days[idx - 1]
        # official gate: rounded mean_wait_days vs routine ceiling (inclusive)
        wait_time_compliant = mean_raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) <= Decimal(
            standard["max_wait_days_routine"])
    else:
        mean_wait = None
        p90_wait = None
        wait_time_compliant = True

    # overall
    if member_count == 0 or (ratio_ok and time_distance_compliant and wait_time_compliant):
        overall = "COMPLIANT"
    else:
        if _approved_excuse_covers(region["id"], specialty, period_end):
            overall = "EXCUSED"
        else:
            overall = "DEFICIENT"

    row = {
        "evaluation_id": evaluation["id"],
        "region_id": region["id"],
        "specialty": specialty,
        "member_count": member_count,
        "provider_count": provider_count,
        "listing_count": listing_count,
        "ratio_members_per_provider": ratio,
        "ratio_ok": ratio_ok,
        "counted_location_count": counted_location_count,
        "compliant_location_count": compliant_location_count,
        "time_distance_compliant": time_distance_compliant,
        "probed_listing_count": probed_listing_count,
        "mean_wait_days": mean_wait,
        "p90_wait_days": p90_wait,
        "wait_time_compliant": wait_time_compliant,
        "overall_status": overall,
    }
    helpers.stamp_new(row, with_version=False)
    return row


def _active_deficiency(region_id, specialty):
    """Existing OPEN or EXCUSED deficiency for the pair, if any."""
    for d in db.deficiencies.values():
        if d["region_id"] == region_id and d["specialty"] == specialty and d["status"] in ("OPEN", "EXCUSED"):
            return d
    return None


def _approved_window_through(deficiency_id):
    """Latest excuse_through_date among APPROVED requests of this deficiency (None if none)."""
    best = None
    for apr in db.access_plan_requests.values():
        if apr["deficiency_id"] == deficiency_id and apr["status"] == "APPROVED":
            through = helpers.parse_date(apr["excuse_through_date"], "excuse_through_date")
            if best is None or through > best:
                best = through
    return best


def _accrue(deficiency, region, window_start: date, window_end: date, evaluation):
    """Tiered penalty accrual for one accrual event (§3.7 link 3)."""
    members = region["enrolled_member_count"]
    if members >= TIER2_MEMBER_THRESHOLD:
        tier_mult = Decimal("2.0")
    elif members >= TIER1_MEMBER_THRESHOLD:
        tier_mult = Decimal("1.5")
    else:
        tier_mult = Decimal("1.0")
    repeat_mult = Decimal(1) + REPEAT_STEP * min(deficiency["prior_closure_count"], REPEAT_CAP)
    days = (window_end - window_start).days
    raw = Decimal(BASE_DAILY_PENALTY_CENTS) * Decimal(days) * tier_mult * repeat_mult
    accrual = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    accrual = min(PENALTY_CAP_CENTS, accrual)
    deficiency["accrual_window_start"] = window_start.isoformat()
    deficiency["accrual_window_end"] = window_end.isoformat()
    deficiency["last_accrual_cents"] = accrual
    deficiency["accrued_penalty_cents"] += accrual
    return accrual


def finalize_evaluation(evaluation):
    """Run the 4-link finalize cascade. Assumes preconditions already checked."""
    from services.cascades import recompute_cycle_counters  # noqa: F401 (kept for parity)

    period_start, period_end = _period_bounds(evaluation)

    # Link 1: result rows for every region x specialty with an applicable standard
    new_rows = []
    for region in db.regions.values():
        for specialty in sorted(helpers.SPECIALTIES):
            standard = _find_standard(specialty, region["geo_class"])
            if standard is None:
                continue
            row = _compute_result_row(evaluation, region, specialty, standard, period_start, period_end)
            db.results[row["id"]] = row
            new_rows.append((row, standard))

    # Link 2 + 3: reconcile deficiencies and accrue penalties
    accrual_events = []  # (deficiency_id, accrual_cents) for this evaluation's rollup
    for row, _standard in new_rows:
        region = db.regions[row["region_id"]]
        pair = (row["region_id"], row["specialty"])
        if row["overall_status"] == "DEFICIENT":
            d = _active_deficiency(*pair)
            if d is None:
                prior_closures = sum(
                    1 for x in db.deficiencies.values()
                    if x["region_id"] == pair[0] and x["specialty"] == pair[1] and x["status"] == "CLOSED"
                )
                d = {
                    "evaluation_id": evaluation["id"],
                    "region_id": pair[0],
                    "specialty": pair[1],
                    "status": "OPEN",
                    "opened_date": evaluation["period_start_date"],
                    "closed_date": None,
                    "prior_closure_count": prior_closures,
                    "accrual_window_start": None,
                    "accrual_window_end": None,
                    "last_accrual_cents": 0,
                    "accrued_penalty_cents": 0,
                    "reversed_penalty_cents": 0,
                }
                helpers.stamp_new(d)
                db.deficiencies[d["id"]] = d
                accrual = _accrue(d, region, period_start, period_end, evaluation)
                helpers.touch(d)
                accrual_events.append((d["id"], accrual))
            elif d["status"] == "OPEN":
                # extend: new accrual window for this period
                accrual = _accrue(d, region, period_start, period_end, evaluation)
                helpers.touch(d)
                accrual_events.append((d["id"], accrual))
            elif d["status"] == "EXCUSED":
                through = _approved_window_through(d["id"])
                if through is not None and through < period_end:
                    # excuse lapsed: reopen, accrue uncovered tail
                    d["status"] = "OPEN"
                    d["evaluation_id"] = evaluation["id"]
                    window_start = max(period_start, through)
                    accrual = _accrue(d, region, window_start, period_end, evaluation)
                    helpers.touch(d)
                    accrual_events.append((d["id"], accrual))
                # else: excuse covers period end -> accrues nothing
        elif row["overall_status"] == "COMPLIANT":
            d = _active_deficiency(*pair)
            if d is not None:
                d["status"] = "CLOSED"
                d["closed_date"] = evaluation["period_end_date"]
                helpers.touch(d)

    # Link 4: rollup
    deficiency_total = sum(a for _, a in accrual_events)
    error_total = 0
    for c in db.complaints.values():
        if c["status"] not in ("CONFIRMED_ERROR", "CLOSED"):
            continue
        if not _ts_within(c["confirmed_at"], period_start, period_end):
            continue
        error_total += PER_ERROR_PENALTY_CENTS
    late_total = 0
    for corr in db.corrections.values():
        if corr["status"] != "VERIFIED":
            continue
        if not corr["is_late"]:
            continue
        if not _ts_within(corr["verified_at"], period_start, period_end):
            continue
        late_total += LATE_CORRECTION_PENALTY_CENTS

    evaluation["deficiency_penalties_cents"] = deficiency_total
    evaluation["error_penalties_cents"] = error_total
    evaluation["late_correction_penalties_cents"] = late_total
    evaluation["accrual_events"] = [
        {"deficiency_id": did, "accrual_cents": amt} for did, amt in accrual_events
    ]
    evaluation["total_penalty_cents"] = deficiency_total + error_total + late_total
    evaluation["finalized_at"] = helpers.now_iso()
    evaluation["status"] = "FINALIZED"
    helpers.touch(evaluation)
    return accrual_events

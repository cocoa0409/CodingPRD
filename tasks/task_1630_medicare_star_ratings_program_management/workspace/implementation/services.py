"""Business logic: star banding, weighted scoring, improvement pseudo-measure,
rebate tiers, payout amounts, and cross-entity cascades.

Implements SCAFFOLD.yaml Table 3 calculations with PRD-pinned semantics:
- measure_star_banding (published_star / draft_star variants; round raw first)
- weighted_overall_stars (half-star grid; improvement pseudo-measure weight 5)
- improvement_measure (4dp score, inclusive band boundaries)
- rebate_projection (tiered rate on ENROLLED member-months)
- incentive_payout_amount (ATTAINMENT / GAP_CLOSURE variants, fiscal gate)
- survey_response_rate (4dp; sufficient at >= 0.40 on the rounded rate)
- complaint_timeliness (strictly > 30 days)
"""
from datetime import timedelta
from decimal import Decimal

from db import DB, new_id, next_seq, now_iso
from errors import ApiError
from util import D, half_star, parse_dt, round2f, round4f


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------

def touch(entity):
    """Increment version and refresh updated_at on an entity."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = now_iso()


def refresh(entity):
    """Refresh updated_at without a version bump (cascade-mutated entities)."""
    entity["updated_at"] = now_iso()


def mint_common_fields(entity):
    entity["id"] = new_id()
    ts = now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()


def serialize(entity):
    """Public view of an entity: internal keys (underscore-prefixed) stripped."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def sorted_rows(rows):
    """Default list ordering: created_at ascending, insertion order as tiebreak."""
    return sorted(rows, key=lambda e: (e.get("created_at", ""), e.get("_seq", 0)))


# ---------------------------------------------------------------------------
# Entity getters (existence validation, entity-specific 404s)
# ---------------------------------------------------------------------------

def get_cycle_or_404(cycle_id):
    e = DB["rating_cycles"].get(cycle_id)
    if e is None:
        raise ApiError("ERR_CYCLE_NOT_FOUND", 404, "RatingCycle not found")
    return e


def get_measure_or_404(measure_id):
    e = DB["measures"].get(measure_id)
    if e is None:
        raise ApiError("ERR_MEASURE_NOT_FOUND", 404, "Measure not found")
    return e


def get_set_or_404(set_id):
    e = DB["cutpoint_sets"].get(set_id)
    if e is None:
        raise ApiError("ERR_CUTPOINT_SET_NOT_FOUND", 404, "CutPointSet not found")
    return e


def get_perf_or_404(perf_id):
    e = DB["measure_performances"].get(perf_id)
    if e is None:
        raise ApiError("ERR_PERFORMANCE_NOT_FOUND", 404, "MeasurePerformance not found")
    return e


def get_member_or_404(member_id):
    e = DB["members"].get(member_id)
    if e is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "Member not found")
    return e


def get_gap_or_404(gap_id):
    e = DB["care_gaps"].get(gap_id)
    if e is None:
        raise ApiError("ERR_CARE_GAP_NOT_FOUND", 404, "CareGap not found")
    return e


def get_group_or_404(group_id):
    e = DB["provider_groups"].get(group_id)
    if e is None:
        raise ApiError("ERR_PROVIDER_GROUP_NOT_FOUND", 404, "ProviderGroup not found")
    return e


def get_payout_or_404(payout_id):
    e = DB["incentive_payouts"].get(payout_id)
    if e is None:
        raise ApiError("ERR_PAYOUT_NOT_FOUND", 404, "IncentivePayout not found")
    return e


def get_vendor_or_404(vendor_id):
    e = DB["survey_vendors"].get(vendor_id)
    if e is None:
        raise ApiError("ERR_VENDOR_NOT_FOUND", 404, "SurveyVendor not found")
    return e


def get_wave_or_404(wave_id):
    e = DB["survey_waves"].get(wave_id)
    if e is None:
        raise ApiError("ERR_WAVE_NOT_FOUND", 404, "SurveyWave not found")
    return e


def get_case_or_404(case_id):
    e = DB["complaint_cases"].get(case_id)
    if e is None:
        raise ApiError("ERR_COMPLAINT_NOT_FOUND", 404, "ComplaintCase not found")
    return e


def get_forecast_or_404(forecast_id):
    e = DB["rating_forecasts"].get(forecast_id)
    if e is None:
        raise ApiError("ERR_FORECAST_NOT_FOUND", 404, "RatingForecast not found")
    return e


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def perf_for_measure(measure_id):
    """The (unique per measure+cycle) performance for a measure, or None."""
    for p in DB["measure_performances"].values():
        if p["measure_id"] == measure_id:
            return p
    return None


def perfs_of_cycle(cycle_id):
    return [
        p
        for p in sorted_rows(DB["measure_performances"].values())
        if p["rating_cycle_id"] == cycle_id
    ]


def measures_of_cycle(cycle_id):
    return [
        m
        for m in sorted_rows(DB["measures"].values())
        if m["rating_cycle_id"] == cycle_id
    ]


def published_set_for_cycle(cycle):
    """The cycle's currently PUBLISHED set (via the back-pointer), or None."""
    set_id = cycle.get("published_cutpoint_set_id")
    if not set_id:
        return None
    s = DB["cutpoint_sets"].get(set_id)
    if s is None or s["status"] != "PUBLISHED":
        return None
    return s


def draft_set_for_cycle(cycle_id):
    """Most recently created CutPointSet of the cycle currently in DRAFT status."""
    drafts = [
        s
        for s in DB["cutpoint_sets"].values()
        if s["rating_cycle_id"] == cycle_id and s["status"] == "DRAFT"
    ]
    if not drafts:
        return None
    return sorted_rows(drafts)[-1]


# ---------------------------------------------------------------------------
# Calculation: measure_star_banding
# ---------------------------------------------------------------------------

def band_star(raw_value, direction, cutpoint_set, measure_id):
    """Star 1-5 banded from the ROUNDED raw_value against the set's row floors."""
    if raw_value is None or cutpoint_set is None:
        return None
    row = None
    for r in cutpoint_set.get("rows", []):
        if r.get("measure_id") == measure_id:
            row = r  # last row wins if duplicated
    if row is None:
        return None
    rv = D(str(raw_value))
    floors = [
        D(str(row["band_2_floor"])),
        D(str(row["band_3_floor"])),
        D(str(row["band_4_floor"])),
        D(str(row["band_5_floor"])),
    ]
    if direction == "HIGHER_BETTER":
        return 1 + sum(1 for f in floors if rv >= f)
    return 1 + sum(1 for f in floors if rv <= f)


def recompute_performance(perf):
    """Recompute raw_value + both stars, then refresh the cycle's live stars.

    Banding applies to the rounded raw_value (2dp, half-up), never the ratio.
    published_star bands against the cycle's PUBLISHED set; draft_star against
    the most recently created DRAFT set; either is null without its basis set.
    """
    cycle = DB["rating_cycles"].get(perf["rating_cycle_id"])
    measure = DB["measures"].get(perf["measure_id"])
    den = perf["denominator"]
    if den == 0:
        perf["raw_value"] = None
    else:
        perf["raw_value"] = round2f(D(perf["numerator"]) / D(den))
    pub_set = published_set_for_cycle(cycle) if cycle else None
    dr_set = draft_set_for_cycle(perf["rating_cycle_id"])
    direction = measure["direction"] if measure else "HIGHER_BETTER"
    perf["published_star"] = band_star(
        perf["raw_value"], direction, pub_set, perf["measure_id"]
    )
    perf["draft_star"] = band_star(
        perf["raw_value"], direction, dr_set, perf["measure_id"]
    )
    refresh(perf)
    if cycle is not None:
        refresh_live_stars(cycle)


# ---------------------------------------------------------------------------
# Calculations: improvement_measure + weighted_overall_stars
# ---------------------------------------------------------------------------

def improvement_stats(cycle, basis_field, status_filter):
    """Improvement pseudo-measure over the caller's basis and status filter.

    Returns dict(score, star, eligible, improved, declined). Empty eligible set
    yields score None / star None (pseudo-measure excluded entirely).
    """
    eligible = []
    for m in measures_of_cycle(cycle["id"]):
        if m["status"] != "ACTIVE":
            continue
        if not m.get("improvement_eligible"):
            continue
        if m.get("prior_cycle_star") is None:
            continue
        perf = perf_for_measure(m["id"])
        if perf is None or perf["status"] not in status_filter:
            continue
        star = perf.get(basis_field)
        if star is None:
            continue
        eligible.append((star, m["prior_cycle_star"]))
    n = len(eligible)
    if n == 0:
        return {"score": None, "star": None, "eligible": 0, "improved": 0, "declined": 0}
    improved = sum(1 for s, p in eligible if s > p)
    declined = sum(1 for s, p in eligible if s < p)
    score = round4f(D(improved - declined) / D(n))
    sd = D(str(score))
    if sd >= D("0.20"):
        star = 5
    elif sd >= D("0.08"):
        star = 4
    elif sd > D("-0.08"):
        star = 3
    elif sd > D("-0.20"):
        star = 2
    else:
        star = 1
    return {
        "score": score,
        "star": star,
        "eligible": n,
        "improved": improved,
        "declined": declined,
    }


def included_measures(cycle, basis_field, status_filter):
    """(measure, basis_star) pairs entering a weighted average."""
    pairs = []
    for m in measures_of_cycle(cycle["id"]):
        if m["status"] != "ACTIVE":
            continue
        perf = perf_for_measure(m["id"])
        if perf is None or perf["status"] not in status_filter:
            continue
        star = perf.get(basis_field)
        if star is None:
            continue
        pairs.append((m, star))
    return pairs


def weighted_stars(cycle, basis_field, status_filter):
    """Half-star rounded weighted mean incl. improvement pseudo-measure (wt 5)."""
    pairs = included_measures(cycle, basis_field, status_filter)
    imp = improvement_stats(cycle, basis_field, status_filter)
    num = sum(D(m["weight"]) * D(star) for m, star in pairs)
    den = sum(D(m["weight"]) for m, _ in pairs)
    if imp["star"] is not None:
        num += D(5) * D(imp["star"])
        den += D(5)
    if den == 0:
        return None
    return half_star(num / den)


def refresh_live_stars(cycle):
    """Best-available basis: published_star when a PUBLISHED set exists, else
    draft_star; input filter VALIDATED-or-LOCKED. Silent field update (no
    version bump — the refresh is a side effect, not a cycle mutation)."""
    basis = "published_star" if cycle.get("published_cutpoint_set_id") else "draft_star"
    cycle["live_weighted_stars"] = weighted_stars(cycle, basis, {"VALIDATED", "LOCKED"})


# ---------------------------------------------------------------------------
# Calculation: rebate_projection
# ---------------------------------------------------------------------------

def member_months_pool():
    """Sum of enrolled_months over members ENROLLED at call time."""
    return sum(
        m["enrolled_months"]
        for m in DB["members"].values()
        if m["status"] == "ENROLLED"
    )


def rebate_tier_rate(stars):
    """Tier rate keyed on overall stars; 0.0 when stars < 3.5 or null."""
    if stars is None or stars < 3.5:
        return 0.0
    if stars < 4.0:
        return 0.035
    if stars < 4.5:
        return 0.040
    if stars < 5.0:
        return 0.045
    return 0.050


def rebate_amount(member_months, benchmark_pmpm, stars):
    """stars -> tier lookup -> multiply -> single final 2dp half-up rounding."""
    rate = rebate_tier_rate(stars)
    return round2f(D(member_months) * D(str(benchmark_pmpm)) * D(str(rate)))


# ---------------------------------------------------------------------------
# Calculation: incentive_payout_amount
# ---------------------------------------------------------------------------

def compute_payout_amount(group):
    """Compute the payout amount by the group's program_type variant.

    Returns (amount, basis_snapshot). Raises ERR_PERFORMANCE_NOT_BANDED (409)
    for ATTAINMENT when the linked measure's published_star is null.
    """
    measure = DB["measures"].get(group["linked_measure_id"])
    perf = perf_for_measure(group["linked_measure_id"]) if measure else None
    published_star = perf.get("published_star") if perf else None
    closed_gap_count = sum(
        1
        for g in DB["care_gaps"].values()
        if g["measure_id"] == group["linked_measure_id"] and g["status"] == "CLOSED"
    )
    snapshot = {
        "program_type": group["program_type"],
        "published_star": published_star,
        "target_star": group["target_star"],
        "closed_gap_count": closed_gap_count,
        "unit_reward_per_gap": group["unit_reward_per_gap"],
        "max_pool_amount": group["max_pool_amount"],
    }
    if group["program_type"] == "ATTAINMENT":
        if published_star is None:
            raise ApiError(
                "ERR_PERFORMANCE_NOT_BANDED",
                409,
                "ATTAINMENT payout requires the linked measure's performance "
                "to have a non-null published_star",
            )
        pct = min(D(1), D(published_star) / D(group["target_star"]))
        amount = round2f(D(str(group["max_pool_amount"])) * pct)
    else:  # GAP_CLOSURE
        raw = round2f(D(str(group["unit_reward_per_gap"])) * D(closed_gap_count))
        amount = float(min(D(str(group["max_pool_amount"])), D(str(raw))))
    return amount, snapshot


def pool_move(group, paid_delta=0, reserved_delta=0, remaining_delta=0):
    """Apply pool movements with Decimal arithmetic; stores floats."""
    group["paid_total"] = float(D(str(group["paid_total"])) + D(str(paid_delta)))
    group["reserved_total"] = float(
        D(str(group["reserved_total"])) + D(str(reserved_delta))
    )
    group["remaining_amount"] = float(
        D(str(group["remaining_amount"])) + D(str(remaining_delta))
    )


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def gap_cycle(gap):
    """The cycle owning a gap, via its measure."""
    measure = DB["measures"].get(gap["measure_id"])
    if measure is None:
        return None
    return DB["rating_cycles"].get(measure["rating_cycle_id"])


def credit_gap_open(gap):
    """Gap opened: linked performance denominator += 1 (unless LOCKED/missing)."""
    perf = perf_for_measure(gap["measure_id"])
    if perf is not None and perf["status"] != "LOCKED":
        perf["denominator"] += 1
        recompute_performance(perf)


def credit_gap_close(gap):
    perf = perf_for_measure(gap["measure_id"])
    perf["numerator"] += 1
    recompute_performance(perf)


def credit_gap_reopen(gap):
    perf = perf_for_measure(gap["measure_id"])
    if perf is not None and perf["status"] != "LOCKED":
        perf["numerator"] -= 1
        recompute_performance(perf)


def credit_gap_exclude(gap):
    perf = perf_for_measure(gap["measure_id"])
    if perf is not None and perf["status"] != "LOCKED":
        perf["denominator"] -= 1
        recompute_performance(perf)


def cascade_disenroll(member):
    """Member disenrollment cascade (PRD 3.4): OPEN/REOPENED gaps -> EXCLUDED,
    each exclusion decrements the linked denominator (unless LOCKED) and
    recomputes raw/stars; each recompute refreshes live stars."""
    for gap in sorted_rows(DB["care_gaps"].values()):
        if gap["member_id"] != member["id"]:
            continue
        if gap["status"] not in ("OPEN", "REOPENED"):
            continue
        gap["status"] = "EXCLUDED"
        touch(gap)  # gap exclusion bumps CareGap.version by 1
        credit_gap_exclude(gap)


def publish_cutpoint_set(cps):
    """Publish cascade (PRD 3.3): supersede prior PUBLISHED set, re-point the
    cycle, recompute every performance's stars against the new bases, refresh
    live stars. Cycle version +1 (single logical mutation); set version +1.
    The superseded set mutates status only (no version bump per PRD 3.3)."""
    cycle = get_cycle_or_404(cps["rating_cycle_id"])
    for other in DB["cutpoint_sets"].values():
        if (
            other["rating_cycle_id"] == cycle["id"]
            and other["id"] != cps["id"]
            and other["status"] == "PUBLISHED"
        ):
            other["status"] = "SUPERSEDED"
            refresh(other)
    cps["status"] = "PUBLISHED"
    touch(cps)
    cycle["published_cutpoint_set_id"] = cps["id"]
    for perf in perfs_of_cycle(cycle["id"]):
        recompute_performance(perf)
    touch(cycle)
    return cycle


def complaints_perf_for_cycle(cycle_id):
    """The cycle's performance whose measure has data_source == COMPLAINTS."""
    for m in measures_of_cycle(cycle_id):
        if m["data_source"] != "COMPLAINTS":
            continue
        perf = perf_for_measure(m["id"])
        if perf is not None:
            return perf
    return None


# ---------------------------------------------------------------------------
# Calculation: complaint_timeliness
# ---------------------------------------------------------------------------

def compute_late_resolution(filed_at, resolved_at_dt):
    """True iff elapsed time from filed_at to resolved_at is strictly > 30 days
    (a resolution at exactly 30 days is not late)."""
    return (resolved_at_dt - parse_dt(filed_at)) > timedelta(days=30)


# ---------------------------------------------------------------------------
# Survey window helpers (half-open intervals; adjacency allowed)
# ---------------------------------------------------------------------------

NON_TERMINAL_WAVE_STATES = ("PLANNED", "FIELDING", "CLOSED_FIELD")


def windows_intersect(s1, e1, s2, e2):
    """Half-open [s1, e1) vs [s2, e2) any-intersection test (adjacency excluded)."""
    return s1 < e2 and s2 < e1

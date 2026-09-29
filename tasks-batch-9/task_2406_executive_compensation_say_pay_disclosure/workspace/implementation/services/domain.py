"""Shared derivations and the ordered cascade chains (PRD §2.8, §3.1-§3.9)."""

import calc
from db import apply_changes, now, ordered, store, touch

# Program fields the proxy advisors care about (PRD §2.8): when any of them is
# recomputed to a new value every SCREENED screen of the program goes STALE.
WATCHED_PROGRAM_FIELDS = (
    "realized_pay_total_usd",
    "realizable_pay_total_usd",
    "pay_percentile_rank",
    "degree_of_alignment",
    "alignment_status",
    "target_tdc_usd",
    "performance_based_pct",
    "outreach_coverage_pct",
    "vote_status",
)


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------
def group_members(group_id, accepted_only=False):
    rows = [
        m
        for m in store.peer_group_members.values()
        if m["peer_group_id"] == group_id
        and (not accepted_only or m["status"] == "ACCEPTED")
    ]
    return ordered(rows)


def group_programs(group_id):
    return ordered(
        [p for p in store.pay_programs.values() if p["peer_group_id"] == group_id]
    )


def program_metrics(program_id, vehicle=None):
    rows = [
        m
        for m in store.incentive_metrics.values()
        if m["pay_program_id"] == program_id and (vehicle is None or m["vehicle"] == vehicle)
    ]
    return ordered(rows)


def program_awards(program_id, vehicle=None):
    rows = [
        a
        for a in store.payout_awards.values()
        if a["pay_program_id"] == program_id and (vehicle is None or a["vehicle"] == vehicle)
    ]
    return ordered(rows)


def program_screens(program_id, advisor=None):
    rows = [
        s
        for s in store.proxy_advisor_screens.values()
        if s["pay_program_id"] == program_id and (advisor is None or s["advisor"] == advisor)
    ]
    return ordered(rows)


def program_drafts(program_id):
    return ordered(
        [d for d in store.cda_drafts.values() if d["pay_program_id"] == program_id]
    )


def program_engagements(program_id):
    return ordered(
        [e for e in store.outreach_engagements.values() if e["pay_program_id"] == program_id]
    )


def company_events(company_id):
    return ordered(
        [
            e
            for e in store.restatement_events.values()
            if e["company_id"] == company_id
        ]
    )


def event_determinations(event_id):
    return ordered(
        [
            d
            for d in store.clawback_determinations.values()
            if d["restatement_event_id"] == event_id
        ]
    )


def issuer_of(program):
    return store.companies[program["issuer_company_id"]]


def peer_ceo_tdc_values(group_id):
    values = []
    for member in group_members(group_id, accepted_only=True):
        peer = store.companies.get(member["peer_company_id"])
        if peer is not None:
            values.append(peer["ceo_tdc_usd"])
    return values


def adjusted_metric_count(program_id):
    return sum(
        1
        for m in program_metrics(program_id)
        if m["status"] == "ADJUSTED" or m["goal_adjustment_pct"] is not None
    )


# ---------------------------------------------------------------------------
# screen freshness cascade (the tail shared by nearly every write)
# ---------------------------------------------------------------------------
def bounce_legal_cleared(program):
    """LEGAL_CLEARED -> DRAFTING for every section of the program."""
    for draft in program_drafts(program["id"]):
        if draft["status"] == "LEGAL_CLEARED":
            apply_changes(
                draft,
                {
                    "status": "DRAFTING",
                    "revision_round": draft["revision_round"] + 1,
                    "cleared_by_user_id": None,
                },
            )


def mark_screens_stale(program):
    """SCREENED -> STALE, and through it LEGAL_CLEARED sections back to DRAFTING."""
    staled = False
    for screen in program_screens(program["id"]):
        if screen["status"] == "SCREENED":
            apply_changes(screen, {"status": "STALE"})
            staled = True
    if staled:
        bounce_legal_cleared(program)
    return staled


def watched(program):
    return {field: program[field] for field in WATCHED_PROGRAM_FIELDS}


def stale_if_watched_changed(program, before):
    if any(program[field] != before[field] for field in WATCHED_PROGRAM_FIELDS):
        return mark_screens_stale(program)
    return False


# ---------------------------------------------------------------------------
# awards
# ---------------------------------------------------------------------------
def recompute_award_values(award):
    program = store.pay_programs[award["pay_program_id"]]
    issuer = issuer_of(program)
    realized, realizable = calc.award_values(award, issuer["share_price_usd"])
    return apply_changes(
        award,
        {"realized_value_usd": realized, "realizable_value_usd": realizable},
    )


def recompute_award_factor(award):
    """certified_factor_pct / earned_amount_usd from the vehicle's metric set."""
    program = store.pay_programs[award["pay_program_id"]]
    metrics = program_metrics(program["id"], award["vehicle"])
    factor = calc.certified_vehicle_factor(metrics)
    earned = None
    if factor is not None and award["vehicle"] == "ANNUAL_INCENTIVE":
        earned = calc.annual_incentive_earned(
            award["target_amount_usd"], factor, program["sti_max_multiple"]
        )
    apply_changes(
        award, {"certified_factor_pct": factor, "earned_amount_usd": earned}
    )
    recompute_award_values(award)


def recompute_vehicle_awards(program, vehicle):
    for award in program_awards(program["id"], vehicle):
        recompute_award_factor(award)


# ---------------------------------------------------------------------------
# program aggregates
# ---------------------------------------------------------------------------
def _counted_awards(program):
    return [
        a
        for a in program_awards(program["id"])
        if a["status"] in calc.COUNTED_AWARD_STATUSES
    ]


def recompute_program_alignment(program, totals_only=False):
    values = calc.alignment(
        program,
        _counted_awards(program),
        peer_ceo_tdc_values(program["peer_group_id"]),
    )
    if totals_only:
        values = {
            "realized_pay_total_usd": values["realized_pay_total_usd"],
            "realizable_pay_total_usd": values["realizable_pay_total_usd"],
        }
    return apply_changes(program, values)


def recompute_program_target(program):
    executive = store.executives[program["ceo_executive_id"]]
    group = store.peer_groups[program["peer_group_id"]]
    values = calc.target_direct_comp(program, executive, group["benchmark_target_tdc_usd"])
    return apply_changes(program, values)


def clear_program_benchmark(program):
    return apply_changes(
        program,
        {
            "benchmark_ratio": None,
            "lti_multiple": None,
            "lti_target_usd": None,
            "target_tdc_usd": None,
            "benchmark_posture": "UNBENCHMARKED",
        },
    )


def recompute_program_coverage(program):
    held = [
        e for e in program_engagements(program["id"]) if e["engagement_status"] == "HELD"
    ]
    return apply_changes(
        program, {"outreach_coverage_pct": calc.outreach_coverage(held)}
    )


# ---------------------------------------------------------------------------
# peer group
# ---------------------------------------------------------------------------
def recompute_member_fit(member):
    group = store.peer_groups[member["peer_group_id"]]
    issuer = store.companies[group["issuer_company_id"]]
    peer = store.companies[member["peer_company_id"]]
    revenue_ratio, market_cap_ratio, in_band = calc.size_band_fit(issuer, peer)
    apply_changes(
        member,
        {
            "revenue_ratio": revenue_ratio,
            "market_cap_ratio": market_cap_ratio,
            "in_size_band": in_band,
        },
    )
    return in_band


def recompute_accepted_member_count(group):
    return apply_changes(
        group,
        {"accepted_member_count": len(group_members(group["id"], accepted_only=True))},
    )


def revert_group_to_draft(group):
    """SCREENED -> DRAFT, clearing medians, size fit and both benchmark variants."""
    return apply_changes(
        group,
        {
            "status": "DRAFT",
            "median_revenue_usd": None,
            "median_market_cap_usd": None,
            "size_fit_score": None,
            "screened_at": None,
            "benchmark_target_tdc_raw_usd": None,
            "benchmark_target_tdc_adjusted_usd": None,
            "benchmark_target_tdc_usd": None,
        },
    )


def clear_dependent_draft_programs(group):
    """Every DRAFT program of the group loses its benchmark-derived fields."""
    for program in group_programs(group["id"]):
        if program["design_status"] != "DRAFT":
            continue
        before = watched(program)
        clear_program_benchmark(program)
        stale_if_watched_changed(program, before)


def screen_group(group):
    """Medians, size-fit score and both benchmark variants (PRD §3.2)."""
    issuer = store.companies[group["issuer_company_id"]]
    members = group_members(group["id"], accepted_only=True)
    peers = [store.companies[m["peer_company_id"]] for m in members]

    median_revenue = calc.mean_of_middles_median([p["revenue_usd"] for p in peers])
    median_market_cap = calc.mean_of_middles_median([p["market_cap_usd"] for p in peers])
    raw_values = [calc.dec(p["ceo_tdc_usd"]) for p in peers]
    adjusted_values = [
        calc.size_adjusted_value(issuer["revenue_usd"], p["revenue_usd"], p["ceo_tdc_usd"])
        for p in peers
    ]
    raw_benchmark = calc.nearest_rank_p50(raw_values)
    adjusted_benchmark = calc.nearest_rank_p50(adjusted_values)
    selected = (
        raw_benchmark if group["benchmark_basis"] == "RAW_MEDIAN" else adjusted_benchmark
    )
    apply_changes(
        group,
        {
            "median_revenue_usd": median_revenue,
            "median_market_cap_usd": median_market_cap,
            "size_fit_score": calc.size_fit_score(median_revenue, issuer["revenue_usd"]),
            "benchmark_target_tdc_raw_usd": raw_benchmark,
            "benchmark_target_tdc_adjusted_usd": adjusted_benchmark,
            "benchmark_target_tdc_usd": selected,
            "status": "SCREENED",
            "screened_at": now(),
        },
    )
    touch(group)


def push_group_benchmark(group):
    """Peer-group approval cascade levels 1-3 (PRD §3.2)."""
    for program in group_programs(group["id"]):
        if program["design_status"] != "DRAFT":
            continue
        before = watched(program)
        recompute_program_target(program)
        if program["pay_percentile_rank"] is not None:
            recompute_program_alignment(program)
        stale_if_watched_changed(program, before)


# ---------------------------------------------------------------------------
# proxy advisor screens
# ---------------------------------------------------------------------------
def screen_values(program, advisor):
    return calc.concern_components(
        advisor, program, adjusted_metric_count(program["id"])
    )

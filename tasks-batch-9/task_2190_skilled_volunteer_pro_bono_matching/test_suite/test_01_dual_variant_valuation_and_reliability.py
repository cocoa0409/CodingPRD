"""Dual-variant arithmetic: the two valuation methods and the two reliability figures."""
import pytest

from test_helpers import (
    api_client,
    current_engagement_version,
    get_success_data,
    read_engagement,
    read_volunteer,
    setup_held_milestone_engagement,
    setup_engagement,
    add_scoped_request,
    set_clock,
    validate_success,
)

SINGLE_DELIVERABLE = [
    {
        "title": "Redlined lease set",
        "sequence_no": 1,
        "weight_pct": 100.00,
        "hours_estimate": 40.00,
        "acceptance_criteria": "All 12 leases redlined and risk-ranked",
    }
]

MIXED_CLASS_LOGS = [
    {"work_date": "2026-08-12T00:00:00Z", "hours": 7.25, "activity_class": "DELIVERY"},
    {"work_date": "2026-08-13T00:00:00Z", "hours": 3.50, "activity_class": "ADMIN"},
    {"work_date": "2026-08-14T00:00:00Z", "hours": 2.00, "activity_class": "TRAVEL"},
]


def _engagement_with_mixed_class_logs():
    """A live engagement carrying three approved logs — 7.25 DELIVERY, 3.50 ADMIN and
    2.00 TRAVEL — each snapshotting a 150.00 professional rate for a SENIOR volunteer."""
    return setup_held_milestone_engagement(
        skill_code="LEGAL_CONTRACTS",
        deliverables=SINGLE_DELIVERABLE,
        time_logs=MIXED_CLASS_LOGS,
        reported_cumulative_hours=12.75,
        volunteer_seniority="SENIOR",
        volunteer_rate=150.00,
    )


def _post_valuation(world, method):
    version = current_engagement_version(world)
    return validate_success(
        api_client.create_valuation(
            world["engagement"]["id"],
            {"expected_engagement_version": version, "method": method},
            world["pm_headers"],
        ),
        expected_status=201,
    )


def test_market_rate_valuation_drops_travel_and_halves_admin_per_line(api):
    """PRD §3.9: "It admits only logs whose `activity_class` is `DELIVERY` or `ADMIN`,
    dropping every `TRAVEL` log from both the hours and the money."
    PRD §3.9: "For each admitted log it multiplies the log's `hours` by the lesser of
    that log's `rate_basis_usd` and the seniority ceiling, then by a class factor of
    1.00 for `DELIVERY` and 0.50 for `ADMIN` — travel's factor is 0.00, which is why
    excluding it changes nothing about the money but does change the hours — and rounds
    that line to two decimals."
    PRD §3.9: "`hours_included` is the sum of `hours` over the admitted logs, rounded to
    two decimals, and `rate_applied_usd` is the lesser of the volunteer's
    `professional_rate_usd_per_hour` and the seniority ceiling."

    Design: Difficulty/dual_variant_calc/valuation_market_rate_vs_independent_sector
    """
    world = _engagement_with_mixed_class_logs()

    record = _post_valuation(world, "MARKET_RATE")

    assert record["method"] == "MARKET_RATE", f"Expected MARKET_RATE, got {record['method']}"
    assert record["hours_included"] == pytest.approx(10.75, abs=0.01), (
        f"Expected hours_included 10.75 with the TRAVEL log dropped, got "
        f"{record['hours_included']}"
    )
    assert record["rate_applied_usd"] == pytest.approx(150.00, abs=0.01), (
        f"Expected rate_applied_usd 150.00, got {record['rate_applied_usd']}"
    )
    assert record["base_amount_usd"] == pytest.approx(1350.00, abs=0.01), (
        f"Expected base_amount_usd 1350.00, got {record['base_amount_usd']}"
    )
    assert record["variant_label"] == "PROVISIONAL", (
        f"Expected variant_label PROVISIONAL, got {record['variant_label']}"
    )
    assert record["superseded_at"] is None, "A first record of its method is not superseded"


def test_market_rate_overhead_tier_reads_the_base_and_totals_1512(api):
    """PRD §3.9: "Second, the overhead tier is selected from `base_amount_usd` and never
    from the total: a base below 2500.00 takes a rate of 0.12, a base from 2500.00 up to
    but not including 10000.00 takes 0.09, and a base of 10000.00 or more takes 0.06."
    PRD §3.9: "Third, `admin_overhead_usd` is the greater of a 45.00-dollar floor and the
    base multiplied by that tier rate rounded to two decimals — so even a base of 0.00
    still carries 45.00 of overhead."
    PRD §3.9: "Fourth, `total_amount_usd` is the base plus the overhead, rounded to two
    decimals."

    Design: Difficulty/dual_variant_calc/valuation_market_rate_vs_independent_sector
    """
    world = _engagement_with_mixed_class_logs()

    record = _post_valuation(world, "MARKET_RATE")

    assert record["base_amount_usd"] == pytest.approx(1350.00, abs=0.01), (
        f"Expected base_amount_usd 1350.00, got {record['base_amount_usd']}"
    )
    assert record["admin_overhead_usd"] == pytest.approx(162.00, abs=0.01), (
        f"Expected admin_overhead_usd 162.00 at the 0.12 tier, got "
        f"{record['admin_overhead_usd']}"
    )
    assert record["total_amount_usd"] == pytest.approx(1512.00, abs=0.01), (
        f"Expected total_amount_usd 1512.00, got {record['total_amount_usd']}"
    )


def test_independent_sector_valuation_admits_every_class_at_the_flat_rate(api):
    """PRD §3.9: "It admits every approved log regardless of class — `DELIVERY`, `ADMIN`
    and `TRAVEL` alike — sets `hours_included` to the sum of their `hours` rounded to two
    decimals, sets `rate_applied_usd` to the flat national rate of 34.79 dollars an hour,
    and sets `base_amount_usd` to those hours multiplied by that rate, rounded once at the
    end."
    PRD §3.9: "Seniority ceilings and personal rates play no part."

    Design: Difficulty/dual_variant_calc/valuation_market_rate_vs_independent_sector
    """
    world = _engagement_with_mixed_class_logs()

    record = _post_valuation(world, "INDEPENDENT_SECTOR")

    assert record["method"] == "INDEPENDENT_SECTOR", (
        f"Expected INDEPENDENT_SECTOR, got {record['method']}"
    )
    assert record["hours_included"] == pytest.approx(12.75, abs=0.01), (
        f"Expected hours_included 12.75 across all three classes, got "
        f"{record['hours_included']}"
    )
    assert record["rate_applied_usd"] == pytest.approx(34.79, abs=0.01), (
        f"Expected rate_applied_usd 34.79, got {record['rate_applied_usd']}"
    )
    assert record["base_amount_usd"] == pytest.approx(443.57, abs=0.01), (
        f"Expected base_amount_usd 443.57, got {record['base_amount_usd']}"
    )
    assert record["admin_overhead_usd"] == pytest.approx(53.23, abs=0.01), (
        f"Expected admin_overhead_usd 53.23, got {record['admin_overhead_usd']}"
    )
    assert record["total_amount_usd"] == pytest.approx(496.80, abs=0.01), (
        f"Expected total_amount_usd 496.80, got {record['total_amount_usd']}"
    )


def test_two_methods_disagree_on_hours_and_only_independent_sector_feeds_lifetime(api):
    """PRD §3.9: "`valuation_status` advances on its own operations and neither dimension's
    transitions constrain the other beyond the preconditions stated here."
    PRD §2.10: "A volunteer's `lifetime_valued_usd` equals the sum of `total_amount_usd`
    over that volunteer's valuation records whose `method` is `INDEPENDENT_SECTOR` and
    whose `superseded_at` is still null, rounded to two decimals; records of the
    `MARKET_RATE` method never enter this total, and superseded records leave it the moment
    they are stamped."

    Design: Difficulty/dual_variant_calc/valuation_market_rate_vs_independent_sector
    """
    world = _engagement_with_mixed_class_logs()

    market_rate = _post_valuation(world, "MARKET_RATE")
    independent_sector = _post_valuation(world, "INDEPENDENT_SECTOR")

    assert market_rate["hours_included"] != independent_sector["hours_included"], (
        "The two variants must disagree on hours_included from identical logs, got "
        f"{market_rate['hours_included']} and {independent_sector['hours_included']}"
    )
    volunteer = read_volunteer(world)
    assert volunteer["lifetime_valued_usd"] == pytest.approx(496.80, abs=0.01), (
        "lifetime_valued_usd must count only the INDEPENDENT_SECTOR total, got "
        f"{volunteer['lifetime_valued_usd']}"
    )
    engagement = read_engagement(world)
    assert engagement["valuation_status"] == "PROVISIONAL", (
        f"Expected valuation_status PROVISIONAL, got {engagement['valuation_status']}"
    )


# ---------------------------------------------------------------------------
# Reliability: the decay-weighted gate versus the lifetime report
# ---------------------------------------------------------------------------
def _volunteer_with_two_terminal_engagements():
    """One volunteer with two terminal engagements: the older voided out of its agreement
    (0.60 points) and the newer terminated for ADMIN (0.25 points)."""
    world = setup_engagement(skill_code="LEGAL_CONTRACTS", deliverables=SINGLE_DELIVERABLE)
    second = add_scoped_request(
        world,
        skill_code="LEGAL_CONTRACTS",
        deliverables=SINGLE_DELIVERABLE,
        title="Lease review B",
    )
    offer_b = get_success_data(
        api_client.match_project_request(second["request"]["id"], world["spec_headers"])
    )
    engagement_b = get_success_data(
        api_client.accept_match_offer(offer_b["id"], world["volunteer_headers"])
    )

    agreement_a = get_success_data(
        api_client.create_agreement(
            world["engagement"]["id"],
            {
                "expected_engagement_version": current_engagement_version(world),
                "ip_disposition": "ASSIGN_TO_PARTNER",
                "confidentiality_tier": "STANDARD",
                "indemnity_cap_usd": 10000.00,
            },
            world["pm_headers"],
        )
    )
    get_success_data(api_client.send_agreement(agreement_a["id"], world["pm_headers"]))

    set_clock("2026-08-10T00:00:00Z", world["pm_headers"])
    validate_success(
        api_client.void_agreement(
            agreement_a["id"], world["pm_headers"], {"void_reason": "TERMS_REJECTED"}
        )
    )
    set_clock("2026-08-12T00:00:00Z", world["pm_headers"])
    validate_success(
        api_client.terminate_engagement(
            engagement_b["id"], world["pm_headers"], {"termination_reason": "ADMIN"}
        )
    )
    world["engagement_b"] = engagement_b
    return world


def test_reliability_score_uses_the_decay_weighted_variant(api):
    """PRD §3.2: "The gating figure, `reliability_score`, uses the decay-weighted variant:
    it takes only the eight most recent terminal engagements in that order (or all of them
    when the volunteer has fewer), gives the engagement at rank zero a weight of 1, the
    next a weight of 0.85, the next 0.85 multiplied by itself, and so on — each rank's
    weight is 0.85 raised to that zero-based rank and rounded to six decimals — then
    divides the weighted sum of point values by the sum of the weights actually used and
    rounds to four decimals."
    PRD §3.2: "Engagements are ordered most-recent-first by the instant they went terminal,
    which is the engagement's `handoff_at` when present and otherwise its `terminated_at`,
    with the engagement's own `created_at` descending as the tie-break; row identifiers
    never participate in the ordering."

    Design: Difficulty/dual_variant_calc/reliability_decay_weighted_vs_lifetime_average
    """
    world = _volunteer_with_two_terminal_engagements()

    volunteer = read_volunteer(world)
    assert volunteer["reliability_score"] == pytest.approx(0.4108, abs=1e-4), (
        f"Expected decay-weighted reliability_score 0.4108, got "
        f"{volunteer['reliability_score']}"
    )


def test_reliability_score_lifetime_averages_every_terminal_engagement(api):
    """PRD §3.2: "The reporting figure, `reliability_score_lifetime`, uses the unweighted
    lifetime variant: it averages the point values of every terminal engagement ever,
    however many there are, and rounds to four decimals."
    PRD §3.2: "The two fields therefore diverge as soon as a volunteer has more than one
    terminal engagement with differing outcomes."

    Design: Difficulty/dual_variant_calc/reliability_decay_weighted_vs_lifetime_average
    """
    world = _volunteer_with_two_terminal_engagements()

    volunteer = read_volunteer(world)
    assert volunteer["reliability_score_lifetime"] == pytest.approx(0.4250, abs=1e-4), (
        f"Expected lifetime reliability 0.4250, got "
        f"{volunteer['reliability_score_lifetime']}"
    )
    assert volunteer["reliability_score"] != volunteer["reliability_score_lifetime"], (
        "The gating and reporting reliability figures must diverge on these two outcomes"
    )


def test_reliability_just_above_the_floor_leaves_the_volunteer_active(api):
    """PRD §3.2: "One threshold consequence hangs off the decay-weighted figure alone: if
    `reliability_score` falls strictly below 0.4000 while the volunteer's `status` is
    `ACTIVE`, the volunteer moves to `PAUSED` with `pause_reason` `RELIABILITY_FLOOR`,
    dragging the offer-withdrawal cascade above with it."
    PRD §3.2: "the terminal count covers engagements whose `work_status` is `HANDED_OFF`
    or `TERMINATED`, and the open count covers those in `NOT_STARTED`, `IN_PROGRESS` or
    `SUBMITTED`."

    Design: Difficulty/dual_variant_calc/reliability_decay_weighted_vs_lifetime_average
    """
    world = _volunteer_with_two_terminal_engagements()

    volunteer = read_volunteer(world)
    assert volunteer["terminal_engagement_count"] == 2, (
        f"Expected terminal_engagement_count 2, got {volunteer['terminal_engagement_count']}"
    )
    assert volunteer["open_engagement_count"] == 0, (
        f"Expected open_engagement_count 0, got {volunteer['open_engagement_count']}"
    )
    assert volunteer["status"] == "ACTIVE", (
        f"A reliability of 0.4108 is not strictly below 0.4000, so the volunteer stays "
        f"ACTIVE; got {volunteer['status']}"
    )
    assert volunteer["pause_reason"] is None, (
        f"Expected a null pause_reason, got {volunteer['pause_reason']}"
    )


def test_agreement_void_and_direct_terminate_record_their_own_reasons(api):
    """PRD §3.6: "A direct void records `void_reason` `TERMS_REJECTED` and terminates the
    engagement it governed with `termination_reason` `AGREEMENT_VOIDED`; a void that
    arrives as a cascade from an engagement termination records `void_reason`
    `ENGAGEMENT_TERMINATED` instead and terminates nothing further, since the engagement is
    already gone."
    PRD §3.9: "`terminated_at` and `termination_reason` are stamped."

    Design: Difficulty/dual_variant_calc/reliability_decay_weighted_vs_lifetime_average
    """
    world = _volunteer_with_two_terminal_engagements()

    engagement_a = read_engagement(world)
    assert engagement_a["work_status"] == "TERMINATED", (
        f"Expected the voided engagement to be TERMINATED, got {engagement_a['work_status']}"
    )
    assert engagement_a["termination_reason"] == "AGREEMENT_VOIDED", (
        f"Expected termination_reason AGREEMENT_VOIDED, got "
        f"{engagement_a['termination_reason']}"
    )
    engagement_b = get_success_data(
        api_client.get_engagement(world["engagement_b"]["id"], world["pm_headers"])
    )
    assert engagement_b["work_status"] == "TERMINATED", (
        f"Expected the directly terminated engagement to be TERMINATED, got "
        f"{engagement_b['work_status']}"
    )
    assert engagement_b["termination_reason"] == "ADMIN", (
        f"Expected termination_reason ADMIN, got {engagement_b['termination_reason']}"
    )

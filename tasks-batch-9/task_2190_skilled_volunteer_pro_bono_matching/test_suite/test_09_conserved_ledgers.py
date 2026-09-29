"""Conserved ledgers: slots, window hours and reported value, each followed through a forward
action and its compensating action until the books read exactly what they read before."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_scoped_request,
    api_client,
    drive_review_to_outcome,
    post_valuation,
    read_cycle,
    read_engagement,
    read_offer,
    read_valuation_records,
    read_volunteer,
    read_window,
    scope_change_request_payload,
    setup_held_milestone_engagement,
    setup_in_progress_engagement,
    setup_offer,
    validate_error,
    validate_success,
)

ADMIN_TERMINATION = {"termination_reason": "ADMIN"}

SINGLE_DELIVERABLE = [
    {
        "title": "Lease schedule",
        "sequence_no": 1,
        "weight_pct": 100.00,
        "hours_estimate": 40.00,
        "acceptance_criteria": "Schedule signed off by counsel",
    }
]

# 34.50 DELIVERY + 3.50 ADMIN + 2.00 TRAVEL = 40.00 approved hours, split so that no
# single line breaks the 12.00-hour ceiling on one log.
FORTY_MIXED_HOURS = [
    {"work_date": "2026-08-12T00:00:00Z", "hours": 12.00, "activity_class": "DELIVERY"},
    {"work_date": "2026-08-12T00:00:00Z", "hours": 12.00, "activity_class": "DELIVERY"},
    {"work_date": "2026-08-13T00:00:00Z", "hours": 10.50, "activity_class": "DELIVERY"},
    {"work_date": "2026-08-13T00:00:00Z", "hours": 3.50, "activity_class": "ADMIN"},
    {"work_date": "2026-08-14T00:00:00Z", "hours": 2.00, "activity_class": "TRAVEL"},
]

TWELVE_MORE_HOURS = scope_change_request_payload(
    additional_hours=12.00,
    additional_deliverable_count=0,
    justification="Two further lease schedules surfaced during diligence.",
)


def _slot_figures(world):
    cycle = read_cycle(world)
    return (
        cycle["slots_committed"],
        cycle["slots_reserved"],
        cycle["slots_available"],
    )


def _terminate(world, engagement_id=None):
    return api_client.terminate_engagement(
        engagement_id or world["engagement"]["id"],
        world["pm_headers"],
        ADMIN_TERMINATION,
    )


# ---------------------------------------------------------------------------
# The slot ledger: one unit, taken and given back
# ---------------------------------------------------------------------------
def test_01_acceptance_moves_one_slot_from_reserved_to_committed(api):
    """PRD §2.8: "Acceptance of an offer moves one unit from `slots_reserved` to
    `slots_committed`; terminating the resulting engagement removes that unit from
    `slots_committed`."
    PRD §3.1: "The cycle then maintains five derived figures continuously:
    `slots_committed`, `slots_reserved` and `slots_available` as defined in §2.8, a
    `utilization_ratio` equal to the sum of committed and reserved slots divided by
    `capacity_slot_total` and rounded to four decimals, and a `posture` that gates every child
    operation."

    Design: Difficulty/compensating_invariant/cycle_slot_released_exactly_on_termination
    """
    world = setup_offer(skill_code="LEGAL_CONTRACTS", deliverables=SINGLE_DELIVERABLE)

    offered = read_cycle(world)
    assert (
        offered["slots_committed"],
        offered["slots_reserved"],
        offered["slots_available"],
    ) == (0, 1, 9), (
        f"Expected the offer to hold one reserved slot, got committed "
        f"{offered['slots_committed']}, reserved {offered['slots_reserved']}, available "
        f"{offered['slots_available']}"
    )
    assert offered["utilization_ratio"] == pytest.approx(0.1000, abs=1e-4), (
        f"Expected utilization_ratio 0.1000, got {offered['utilization_ratio']}"
    )

    validate_success(
        api_client.accept_match_offer(
            world["offer"]["id"], world["volunteer_headers"]
        ),
        201,
    )

    committed = read_cycle(world)
    assert (
        committed["slots_committed"],
        committed["slots_reserved"],
        committed["slots_available"],
    ) == (1, 0, 9), (
        f"Expected the hold to migrate to one committed slot, got committed "
        f"{committed['slots_committed']}, reserved {committed['slots_reserved']}, available "
        f"{committed['slots_available']}"
    )
    assert committed["utilization_ratio"] == pytest.approx(0.1000, abs=1e-4), (
        f"Expected utilization_ratio still 0.1000, got {committed['utilization_ratio']}"
    )
    assert committed["posture"] == "OPEN", (
        f"Expected posture OPEN, got {committed['posture']}"
    )


def test_02_termination_returns_the_slot_and_restores_the_opening_ledger(api):
    """PRD §2.8: "The conservation requirement is behavioural, not merely arithmetical: after
    a forward action and its compensating action, the ledger must read exactly what it read
    before."
    PRD §2.8: "For every program cycle, `slots_committed` plus `slots_reserved` plus
    `slots_available` always equals `capacity_slot_total`."

    Design: Difficulty/compensating_invariant/cycle_slot_released_exactly_on_termination
    """
    world = setup_in_progress_engagement(
        skill_code="LEGAL_CONTRACTS",
        deliverables=SINGLE_DELIVERABLE,
        title="Lease portfolio diligence",
    )
    assert _slot_figures(world) == (1, 0, 9), (
        f"Setup expected the sole engagement to hold one slot, got {_slot_figures(world)}"
    )

    engagement = validate_success(_terminate(world))

    assert engagement["work_status"] == "TERMINATED", (
        f"Expected work_status TERMINATED, got {engagement['work_status']}"
    )
    assert engagement["termination_reason"] == "ADMIN", (
        f"Expected termination_reason ADMIN, got {engagement['termination_reason']}"
    )
    cycle = read_cycle(world)
    assert (
        cycle["slots_committed"],
        cycle["slots_reserved"],
        cycle["slots_available"],
    ) == (0, 0, 10), (
        f"Expected the ledger back at 0 / 0 / 10, got committed "
        f"{cycle['slots_committed']}, reserved {cycle['slots_reserved']}, available "
        f"{cycle['slots_available']}"
    )
    assert (
        cycle["slots_committed"] + cycle["slots_reserved"] + cycle["slots_available"]
        == cycle["capacity_slot_total"]
    ), (
        f"Conservation broken: {cycle['slots_committed']} + {cycle['slots_reserved']} + "
        f"{cycle['slots_available']} against capacity {cycle['capacity_slot_total']}"
    )
    assert cycle["slots_committed"] <= cycle["capacity_slot_total"], (
        f"slots_committed {cycle['slots_committed']} exceeds capacity "
        f"{cycle['capacity_slot_total']}"
    )
    assert cycle["utilization_ratio"] == pytest.approx(0.0000, abs=1e-4), (
        f"Expected utilization_ratio 0.0000, got {cycle['utilization_ratio']}"
    )
    assert cycle["posture"] == "OPEN", (
        f"Expected posture OPEN, got {cycle['posture']}"
    )

    reread = read_cycle(world)
    assert (
        reread["slots_committed"],
        reread["slots_reserved"],
        reread["slots_available"],
        reread["utilization_ratio"],
    ) == (0, 0, 10, cycle["utilization_ratio"]), (
        f"A second read must agree with the first, got {reread}"
    )


# ---------------------------------------------------------------------------
# The hour ledger: the release must be the grown figure
# ---------------------------------------------------------------------------
def _grown_engagement():
    """A live engagement whose commitment has grown from 40.00 to 52.00 hours through an
    automatically approved scope change."""
    world = setup_in_progress_engagement(
        skill_code="LEGAL_CONTRACTS",
        deliverables=SINGLE_DELIVERABLE,
        title="Lease portfolio diligence",
    )
    world["change"] = validate_success(
        api_client.create_scope_change_request(
            world["engagement"]["id"], TWELVE_MORE_HOURS, world["volunteer_headers"]
        ),
        201,
    )
    return world


def test_03_an_auto_approved_change_grows_both_the_engagement_and_the_window(api):
    """PRD §3.7: "Before the row is persisted the program projects its effect: take the
    engagement's `approved_hours`, add the sum of `additional_hours` over sibling change
    requests whose `status` is `PENDING` or `ESCALATED` — excluding the incoming row — add the
    incoming row's own `additional_hours`, subtract the engagement's `committed_hours`
    baseline, divide by that baseline and round to four decimals."
    PRD §3.7: "An `AUTO_APPROVABLE` change is applied at once, moving `PENDING → APPROVED` in
    the same operation: the engagement's `committed_hours` rises by `additional_hours` and the
    holding window's `hours_committed` rises by the same amount, after which the creep
    calculation reruns against the *new* baseline and therefore normally reads a lower
    `creep_escalation_level` than before."

    Design: Difficulty/compensating_invariant/window_hours_release_matches_grown_commitment
    """
    world = _grown_engagement()
    change = world["change"]

    assert change["projected_creep_pct"] == pytest.approx(-0.7000, abs=1e-4), (
        f"Expected projected_creep_pct -0.7000, got {change['projected_creep_pct']}"
    )
    assert change["decision_tier"] == "AUTO_APPROVABLE", (
        f"Expected decision_tier AUTO_APPROVABLE, got {change['decision_tier']}"
    )
    assert change["status"] == "APPROVED", (
        f"Expected status APPROVED in the same operation, got {change['status']}"
    )
    engagement = read_engagement(world)
    assert engagement["committed_hours"] == pytest.approx(52.00, abs=0.01), (
        f"Expected committed_hours 52.00, got {engagement['committed_hours']}"
    )
    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(52.00, abs=0.01), (
        f"Expected hours_committed 52.00, got {window['hours_committed']}"
    )
    assert window["hours_remaining"] == pytest.approx(248.00, abs=0.01), (
        f"Expected hours_remaining 248.00, got {window['hours_remaining']}"
    )


def test_04_termination_releases_the_grown_figure_and_not_the_reservation(api):
    """PRD §2.9: "An engagement whose `committed_hours` grew from 40.00 to 52.00 through an
    approved change releases 52.00 when it terminates or hands off, never the original 40.00."
    PRD §3.9: "The holding window's `hours_committed` falls by the engagement's full current
    `committed_hours` — the grown figure, not the originally reserved one."

    Design: Difficulty/compensating_invariant/window_hours_release_matches_grown_commitment
    """
    world = _grown_engagement()

    engagement = validate_success(_terminate(world))

    assert engagement["work_status"] == "TERMINATED", (
        f"Expected work_status TERMINATED, got {engagement['work_status']}"
    )
    assert engagement["committed_hours"] == pytest.approx(52.00, abs=0.01), (
        f"Expected the released figure to remain 52.00 on the engagement, got "
        f"{engagement['committed_hours']}"
    )
    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(0.00, abs=0.001), (
        f"Expected hours_committed exactly 0.00, got {window['hours_committed']}"
    )
    assert window["hours_remaining"] == pytest.approx(300.00, abs=0.001), (
        f"Expected hours_remaining exactly 300.00, got {window['hours_remaining']}"
    )
    assert window["hours_committed"] + window["hours_remaining"] == pytest.approx(
        window["hours_offered"], abs=0.001
    ), (
        f"Custody broken: {window['hours_committed']} + {window['hours_remaining']} "
        f"against hours_offered {window['hours_offered']}"
    )
    assert window["hours_committed"] >= 0.00, (
        f"hours_committed must never read negative, got {window['hours_committed']}"
    )
    assert read_cycle(world)["slots_committed"] == 0, (
        f"Expected slots_committed 0, got {read_cycle(world)['slots_committed']}"
    )


# ---------------------------------------------------------------------------
# The value ledger: restated, not released, and never double-counted
# ---------------------------------------------------------------------------
def _valued_and_failed():
    """A submitted engagement carrying one PROVISIONAL INDEPENDENT_SECTOR record of 1558.59
    and a review scored at 2 on its sole deliverable, so its outcome is FAIL."""
    world = setup_held_milestone_engagement(
        skill_code="LEGAL_CONTRACTS",
        deliverables=SINGLE_DELIVERABLE,
        time_logs=FORTY_MIXED_HOURS,
        reported_cumulative_hours=40.00,
        title="Lease portfolio diligence",
    )
    world["valuation"] = validate_success(post_valuation(world), 201)
    world["engagement"] = validate_success(
        api_client.submit_engagement(
            world["engagement"]["id"], world["volunteer_headers"]
        )
    )
    world["review"] = drive_review_to_outcome(
        world, {world["deliverables"][0]["id"]: 2}
    )
    return world


def test_05_the_provisional_record_sets_the_lifetime_total(api):
    """PRD §3.9: "It admits every approved log regardless of class — `DELIVERY`, `ADMIN` and
    `TRAVEL` alike — sets `hours_included` to the sum of their `hours` rounded to two decimals,
    sets `rate_applied_usd` to the flat national rate of 34.79 dollars an hour, and sets
    `base_amount_usd` to those hours multiplied by that rate, rounded once at the end."
    PRD §2.10: "A volunteer's `lifetime_valued_usd` equals the sum of `total_amount_usd` over
    that volunteer's valuation records whose `method` is `INDEPENDENT_SECTOR` and whose
    `superseded_at` is still null, rounded to two decimals; records of the `MARKET_RATE` method
    never enter this total, and superseded records leave it the moment they are stamped."

    Design: Difficulty/compensating_invariant/valuation_restatement_conserves_lifetime_total
    """
    world = setup_held_milestone_engagement(
        skill_code="LEGAL_CONTRACTS",
        deliverables=SINGLE_DELIVERABLE,
        time_logs=FORTY_MIXED_HOURS,
        reported_cumulative_hours=40.00,
        title="Lease portfolio diligence",
    )

    record = validate_success(post_valuation(world), 201)

    assert record["variant_label"] == "PROVISIONAL", (
        f"Expected variant_label PROVISIONAL, got {record['variant_label']}"
    )
    assert record["hours_included"] == pytest.approx(40.00, abs=0.01), (
        f"Expected hours_included 40.00, got {record['hours_included']}"
    )
    assert record["rate_applied_usd"] == pytest.approx(34.79, abs=0.01), (
        f"Expected rate_applied_usd 34.79, got {record['rate_applied_usd']}"
    )
    assert record["base_amount_usd"] == pytest.approx(1391.60, abs=0.01), (
        f"Expected base_amount_usd 1391.60, got {record['base_amount_usd']}"
    )
    assert record["admin_overhead_usd"] == pytest.approx(166.99, abs=0.01), (
        f"Expected admin_overhead_usd 166.99, got {record['admin_overhead_usd']}"
    )
    assert record["total_amount_usd"] == pytest.approx(1558.59, abs=0.01), (
        f"Expected total_amount_usd 1558.59, got {record['total_amount_usd']}"
    )
    assert read_volunteer(world)["lifetime_valued_usd"] == pytest.approx(
        1558.59, abs=0.01
    ), (
        f"Expected lifetime_valued_usd 1558.59, got "
        f"{read_volunteer(world)['lifetime_valued_usd']}"
    )
    assert read_engagement(world)["valuation_status"] == "PROVISIONAL", (
        f"Expected valuation_status PROVISIONAL, got "
        f"{read_engagement(world)['valuation_status']}"
    )


def test_06_a_failed_review_restates_the_valuation_while_ending_the_work(api):
    """PRD §3.8: "For each deliverable in the pinned order, divide its `weight_pct` by that
    active total and round to six decimals, then multiply that normalised weight by the
    deliverable's `review_score` and by a scale factor of 20, rounding each deliverable's
    contribution to two decimals *before* summing."
    PRD §3.8: "because the engagement terminated while holding a posted valuation, its
    `valuation_status` moves from `FINAL` or `PROVISIONAL` to `RESTATED`, a compensating
    `INDEPENDENT_SECTOR` valuation record carrying `variant_label` `RESTATED` is posted, and
    the prior record's `superseded_at` is stamped."

    Design: Difficulty/compensating_invariant/valuation_restatement_conserves_lifetime_total
    """
    world = _valued_and_failed()
    assert world["review"]["weighted_score"] == pytest.approx(40.00, abs=0.01), (
        f"Expected weighted_score 40.00, got {world['review']['weighted_score']}"
    )
    assert world["review"]["outcome"] == "FAIL", (
        f"Expected outcome FAIL, got {world['review']['outcome']}"
    )

    validate_success(
        api_client.decide_quality_review(
            world["review"]["id"], world["reviewer_headers"]
        )
    )

    engagement = read_engagement(world)
    assert engagement["work_status"] == "TERMINATED", (
        f"Expected work_status TERMINATED, got {engagement['work_status']}"
    )
    assert engagement["termination_reason"] == "QUALITY_FAILURE", (
        f"Expected termination_reason QUALITY_FAILURE, got "
        f"{engagement['termination_reason']}"
    )
    assert engagement["quality_gate"] == "FAILED", (
        f"Expected quality_gate FAILED, got {engagement['quality_gate']}"
    )
    assert engagement["valuation_status"] == "RESTATED", (
        f"Expected valuation_status RESTATED, got {engagement['valuation_status']}"
    )
    assert read_cycle(world)["slots_committed"] == 0, (
        f"Expected slots_committed 0, got {read_cycle(world)['slots_committed']}"
    )
    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(0.00, abs=0.001), (
        f"Expected hours_committed 0.00, got {window['hours_committed']}"
    )
    assert window["hours_remaining"] == pytest.approx(300.00, abs=0.001), (
        f"Expected hours_remaining 300.00, got {window['hours_remaining']}"
    )


def test_07_the_restatement_leaves_exactly_one_record_in_the_lifetime_total(api):
    """PRD §2.10: "After a post followed by its restatement, `lifetime_valued_usd` must equal
    the sum over non-superseded `INDEPENDENT_SECTOR` records only — the superseded amount must
    not remain double-counted, and the restated record must not be omitted."
    PRD §3.9: "The system also posts records itself: on termination, `PROVISIONAL → RESTATED`
    and `FINAL → RESTATED` both fire when at least one non-superseded record exists, each
    supersedeing the prior record and posting a compensating `INDEPENDENT_SECTOR` record with
    `variant_label` `RESTATED` computed from the same approved hours."

    Design: Difficulty/compensating_invariant/valuation_restatement_conserves_lifetime_total
    """
    world = _valued_and_failed()
    provisional_id = world["valuation"]["id"]

    validate_success(
        api_client.decide_quality_review(
            world["review"]["id"], world["reviewer_headers"]
        )
    )

    records = read_valuation_records(world)
    assert len(records) == 2, (
        f"Expected exactly two valuation records, got {len(records)}"
    )
    prior = [row for row in records if row["id"] == provisional_id]
    assert len(prior) == 1, f"The original record must still be listed, got {prior}"
    assert prior[0]["variant_label"] == "PROVISIONAL", (
        f"Expected the original variant_label PROVISIONAL, got "
        f"{prior[0]['variant_label']}"
    )
    assert prior[0]["total_amount_usd"] == pytest.approx(1558.59, abs=0.01), (
        f"Expected the original total_amount_usd 1558.59, got "
        f"{prior[0]['total_amount_usd']}"
    )
    assert prior[0]["superseded_at"] is not None, (
        "The original record must carry a stamped superseded_at"
    )

    surviving = [row for row in records if row["superseded_at"] is None]
    assert len(surviving) == 1, (
        f"Expected exactly one non-superseded record, got {len(surviving)}"
    )
    restated = surviving[0]
    assert restated["variant_label"] == "RESTATED", (
        f"Expected variant_label RESTATED, got {restated['variant_label']}"
    )
    assert restated["method"] == "INDEPENDENT_SECTOR", (
        f"Expected method INDEPENDENT_SECTOR, got {restated['method']}"
    )
    assert restated["hours_included"] == pytest.approx(40.00, abs=0.01), (
        f"Expected hours_included 40.00, got {restated['hours_included']}"
    )
    assert restated["rate_applied_usd"] == pytest.approx(34.79, abs=0.01), (
        f"Expected rate_applied_usd 34.79, got {restated['rate_applied_usd']}"
    )
    assert restated["base_amount_usd"] == pytest.approx(1391.60, abs=0.01), (
        f"Expected base_amount_usd 1391.60, got {restated['base_amount_usd']}"
    )
    assert restated["admin_overhead_usd"] == pytest.approx(166.99, abs=0.01), (
        f"Expected admin_overhead_usd 166.99, got {restated['admin_overhead_usd']}"
    )
    assert restated["total_amount_usd"] == pytest.approx(1558.59, abs=0.01), (
        f"Expected total_amount_usd 1558.59, got {restated['total_amount_usd']}"
    )

    volunteer = read_volunteer(world)
    assert volunteer["lifetime_valued_usd"] == pytest.approx(1558.59, abs=0.01), (
        f"Expected lifetime_valued_usd 1558.59, neither 3117.18 nor 0.00, got "
        f"{volunteer['lifetime_valued_usd']}"
    )
    assert volunteer["reliability_score"] == pytest.approx(0.0000, abs=1e-4), (
        f"Expected reliability_score 0.0000, got {volunteer['reliability_score']}"
    )
    assert volunteer["status"] == "PAUSED", (
        f"Expected the volunteer PAUSED, got {volunteer['status']}"
    )


# ---------------------------------------------------------------------------
# The release happens at most once
# ---------------------------------------------------------------------------
def _terminated_world():
    world = setup_in_progress_engagement(
        skill_code="LEGAL_CONTRACTS",
        deliverables=SINGLE_DELIVERABLE,
        title="Lease portfolio diligence",
    )
    world["engagement"] = validate_success(_terminate(world))
    return world


def test_08_terminating_an_already_terminated_engagement_is_refused(api):
    """PRD §3.9: "Terminating from `ACCEPTED` additionally requires `handoff_at` to still be
    null, and terminating an engagement already in `HANDED_OFF` or `TERMINATED` is refused with
    `ERR_INVALID_WORK_STATE`."

    Design: Difficulty/compensating_invariant/repeated_termination_does_not_release_twice
    """
    world = _terminated_world()
    assert world["engagement"]["work_status"] == "TERMINATED", (
        f"Setup expected a terminated engagement, got "
        f"{world['engagement']['work_status']}"
    )

    replay = _terminate(world)

    validate_error(replay, ApiErrorId.ERR_INVALID_WORK_STATE)
    assert read_engagement(world)["work_status"] == "TERMINATED", (
        f"Expected work_status still TERMINATED, got "
        f"{read_engagement(world)['work_status']}"
    )


def test_09_the_refused_replay_moves_no_counter_in_either_ledger(api):
    """PRD §2.8: "No slot may be stranded by the cascades that ride along — sibling offer
    withdrawals, posture recomputation, milestone waivers — and no slot may be double-released."
    PRD §2.9: "Every release path must subtract exactly the amount that was added — including
    hours added later by an approved scope change."

    Design: Difficulty/compensating_invariant/repeated_termination_does_not_release_twice
    """
    world = _terminated_world()

    _terminate(world)

    engagement = read_engagement(world)
    assert engagement["committed_hours"] == pytest.approx(40.00, abs=0.01), (
        f"Expected committed_hours 40.00, got {engagement['committed_hours']}"
    )
    cycle = read_cycle(world)
    assert (
        cycle["slots_committed"],
        cycle["slots_reserved"],
        cycle["slots_available"],
    ) == (0, 0, 10), (
        f"Expected the ledger untouched at 0 / 0 / 10, got committed "
        f"{cycle['slots_committed']}, reserved {cycle['slots_reserved']}, available "
        f"{cycle['slots_available']}"
    )
    assert cycle["slots_available"] <= cycle["capacity_slot_total"], (
        f"slots_available {cycle['slots_available']} exceeds capacity "
        f"{cycle['capacity_slot_total']}"
    )
    assert cycle["utilization_ratio"] == pytest.approx(0.0000, abs=1e-4), (
        f"Expected utilization_ratio 0.0000, got {cycle['utilization_ratio']}"
    )
    assert cycle["posture"] == "OPEN", (
        f"Expected posture OPEN, got {cycle['posture']}"
    )
    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(0.00, abs=0.001), (
        f"Expected hours_committed 0.00 and never negative, got "
        f"{window['hours_committed']}"
    )
    assert window["hours_remaining"] == pytest.approx(300.00, abs=0.001), (
        f"Expected hours_remaining 300.00 and never 340.00, got "
        f"{window['hours_remaining']}"
    )


def test_10_the_replay_does_not_count_a_second_terminal_engagement(api):
    """PRD §3.9: "And because the engagement has now reached a terminal `work_status`, the
    volunteer's `terminal_engagement_count` rises by one and both reliability variants rerun —
    which may itself pause the volunteer and withdraw her open offers."
    PRD §3.2: "Each terminal engagement earns a point value before penalties: 1.00 when it was
    `HANDED_OFF` with a `quality_gate` of `PASSED`; 0.70 when it was `HANDED_OFF` with a
    `quality_gate` of `CONDITIONAL`; 0.00 when it was `TERMINATED` for `QUALITY_FAILURE`; 0.25
    when it was `TERMINATED` for `SCOPE_BREACH` or `ADMIN`; and 0.60 when it was `TERMINATED`
    for `AGREEMENT_VOIDED` or `PARTNER_SUSPENDED`."

    Design: Difficulty/compensating_invariant/repeated_termination_does_not_release_twice
    """
    world = _terminated_world()

    _terminate(world)

    volunteer = read_volunteer(world)
    assert volunteer["terminal_engagement_count"] == 1, (
        f"Expected terminal_engagement_count 1, got "
        f"{volunteer['terminal_engagement_count']}"
    )
    assert volunteer["reliability_score"] == pytest.approx(0.2500, abs=1e-4), (
        f"Expected reliability_score 0.2500, got {volunteer['reliability_score']}"
    )
    assert volunteer["reliability_score_lifetime"] == pytest.approx(0.2500, abs=1e-4), (
        f"Expected reliability_score_lifetime 0.2500, got "
        f"{volunteer['reliability_score_lifetime']}"
    )


# ---------------------------------------------------------------------------
# Two consumers on one window: the release is a subtraction, not a reset
# ---------------------------------------------------------------------------
def _two_engagements_one_window():
    """One volunteer, one window and one cycle carrying two live engagements: A is
    IN_PROGRESS and B sits at NOT_STARTED."""
    world = setup_in_progress_engagement(
        skill_code="LEGAL_CONTRACTS",
        deliverables=SINGLE_DELIVERABLE,
        title="Lease portfolio diligence",
    )
    world["second"] = add_scoped_request(
        world, skill_code="LEGAL_CONTRACTS", title="Vendor terms refresh"
    )
    world["offer_b"] = validate_success(
        api_client.match_project_request(
            world["second"]["request"]["id"], world["spec_headers"]
        ),
        201,
    )
    world["engagement_b"] = validate_success(
        api_client.accept_match_offer(
            world["offer_b"]["id"], world["volunteer_headers"]
        ),
        201,
    )
    return world


def test_11_two_live_engagements_share_one_window_and_one_cycle(api):
    """PRD §2.9: "For every availability window, `hours_committed` equals the sum of
    `reserved_hours` over the match offers still in `OFFERED` status that are held against that
    window, plus the sum of `committed_hours` over the engagements held against that window
    whose `work_status` is `NOT_STARTED`, `IN_PROGRESS`, `SUBMITTED` or `ACCEPTED`, the total
    rounded to two decimals; and `hours_remaining` equals `hours_offered` less
    `hours_committed`, also to two decimals."
    PRD §3.5: "Her `open_engagement_count` must be strictly below 2, the program-wide ceiling
    on concurrent engagements per volunteer."

    Design: Difficulty/compensating_invariant/shared_window_releases_only_terminated_engagement_share
    """
    world = _two_engagements_one_window()

    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(80.00, abs=0.01), (
        f"Expected hours_committed 80.00 across both engagements, got "
        f"{window['hours_committed']}"
    )
    assert window["hours_remaining"] == pytest.approx(220.00, abs=0.01), (
        f"Expected hours_remaining 220.00, got {window['hours_remaining']}"
    )
    cycle = read_cycle(world)
    assert (
        cycle["slots_committed"],
        cycle["slots_reserved"],
        cycle["slots_available"],
    ) == (2, 0, 8), (
        f"Expected the ledger at 2 / 0 / 8, got committed {cycle['slots_committed']}, "
        f"reserved {cycle['slots_reserved']}, available {cycle['slots_available']}"
    )
    assert cycle["utilization_ratio"] == pytest.approx(0.2000, abs=1e-4), (
        f"Expected utilization_ratio 0.2000, got {cycle['utilization_ratio']}"
    )
    assert cycle["posture"] == "OPEN", (
        f"Expected posture OPEN, got {cycle['posture']}"
    )


def test_12_terminating_one_engagement_releases_only_its_own_share(api):
    """PRD §2.9: "Every release path must subtract exactly the amount that was added —
    including hours added later by an approved scope change."
    PRD §3.9: "The cycle's `slots_committed` falls by one and the posture recomputes."

    Design: Difficulty/compensating_invariant/shared_window_releases_only_terminated_engagement_share
    """
    world = _two_engagements_one_window()

    terminated = validate_success(_terminate(world))

    assert terminated["work_status"] == "TERMINATED", (
        f"Expected work_status TERMINATED, got {terminated['work_status']}"
    )
    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(40.00, abs=0.01), (
        f"Expected hours_committed 40.00 rather than a reset to 0.00, got "
        f"{window['hours_committed']}"
    )
    assert window["hours_remaining"] == pytest.approx(260.00, abs=0.01), (
        f"Expected hours_remaining 260.00, got {window['hours_remaining']}"
    )
    assert window["hours_committed"] + window["hours_remaining"] == pytest.approx(
        300.00, abs=0.001
    ), (
        f"Custody broken: {window['hours_committed']} + {window['hours_remaining']}"
    )
    cycle = read_cycle(world)
    assert (
        cycle["slots_committed"],
        cycle["slots_reserved"],
        cycle["slots_available"],
    ) == (1, 0, 9), (
        f"Expected the ledger at 1 / 0 / 9, got committed {cycle['slots_committed']}, "
        f"reserved {cycle['slots_reserved']}, available {cycle['slots_available']}"
    )
    assert cycle["utilization_ratio"] == pytest.approx(0.1000, abs=1e-4), (
        f"Expected utilization_ratio 0.1000, got {cycle['utilization_ratio']}"
    )
    assert cycle["posture"] == "OPEN", (
        f"Expected posture OPEN, got {cycle['posture']}"
    )


def test_13_the_surviving_engagement_and_its_accepted_offer_are_untouched(api):
    """PRD §3.2: "Any move into `PAUSED` or `DEACTIVATED` immediately withdraws every match
    offer that volunteer still holds in `OFFERED` status, each withdrawal carrying
    `withdraw_reason` `VOLUNTEER_PAUSED` and releasing both the window hours and the cycle slot
    it was holding."
    PRD §3.2: "One threshold consequence hangs off the decay-weighted figure alone: if
    `reliability_score` falls strictly below 0.4000 while the volunteer's `status` is `ACTIVE`,
    the volunteer moves to `PAUSED` with `pause_reason` `RELIABILITY_FLOOR`, dragging the
    offer-withdrawal cascade above with it."

    Design: Difficulty/compensating_invariant/shared_window_releases_only_terminated_engagement_share
    """
    world = _two_engagements_one_window()

    validate_success(_terminate(world))

    volunteer = read_volunteer(world)
    assert volunteer["status"] == "PAUSED", (
        f"Expected the volunteer PAUSED, got {volunteer['status']}"
    )
    assert volunteer["reliability_score"] == pytest.approx(0.2500, abs=1e-4), (
        f"Expected reliability_score 0.2500, got {volunteer['reliability_score']}"
    )
    surviving = validate_success(
        api_client.get_engagement(
            world["engagement_b"]["id"], world["pm_headers"]
        )
    )
    assert surviving["work_status"] == "NOT_STARTED", (
        f"The pause must not disturb a live engagement, got "
        f"{surviving['work_status']}"
    )
    assert surviving["committed_hours"] == pytest.approx(40.00, abs=0.01), (
        f"Expected committed_hours 40.00 still held, got {surviving['committed_hours']}"
    )
    offer_b = read_offer(world, world["offer_b"]["id"])
    assert offer_b["status"] == "ACCEPTED", (
        f"An already-accepted offer holds nothing to withdraw, got {offer_b['status']}"
    )

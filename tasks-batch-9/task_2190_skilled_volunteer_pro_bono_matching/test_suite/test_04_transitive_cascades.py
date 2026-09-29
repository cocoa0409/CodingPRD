"""Deep cascades: a failed review, a partner suspension and a forced re-scope, each
reaching four or five hops away from the operation that started it."""
import pytest

from test_helpers import (
    add_scoped_request,
    api_client,
    current_engagement_version,
    drive_review_to_outcome,
    get_success_data,
    read_agreement,
    read_cycle,
    read_engagement,
    read_milestones,
    read_offer,
    read_partner,
    read_request,
    read_scope_changes,
    read_valuation_records,
    read_volunteer,
    read_window,
    set_clock,
    setup_in_progress_engagement,
    setup_submitted_engagement,
    validate_success,
)

TWO_HALVES = [
    {
        "title": "Grant template",
        "sequence_no": 1,
        "weight_pct": 50.00,
        "hours_estimate": 20.00,
        "acceptance_criteria": "Template adopted",
    },
    {
        "title": "Subaward rider",
        "sequence_no": 2,
        "weight_pct": 50.00,
        "hours_estimate": 20.00,
        "acceptance_criteria": "Rider adopted",
    },
]

TWELVE_HOURS_TWO_CLASSES = [
    {"work_date": "2026-08-12T00:00:00Z", "hours": 10.00, "activity_class": "DELIVERY"},
    {"work_date": "2026-08-13T00:00:00Z", "hours": 2.00, "activity_class": "ADMIN"},
]

MINUTE_BOOK = [
    {
        "title": "Minute book",
        "sequence_no": 1,
        "weight_pct": 100.00,
        "hours_estimate": 20.00,
        "acceptance_criteria": "Minute book restored",
    }
]

MEMO_A = [
    {
        "title": "Memo A",
        "sequence_no": 1,
        "weight_pct": 100.00,
        "hours_estimate": 40.00,
        "acceptance_criteria": "Memo A accepted",
    }
]

MEMO_B = [
    {
        "title": "Memo B",
        "sequence_no": 1,
        "weight_pct": 100.00,
        "hours_estimate": 20.00,
        "acceptance_criteria": "Memo B accepted",
    }
]

MEMO_C = [
    {
        "title": "Memo C",
        "sequence_no": 1,
        "weight_pct": 100.00,
        "hours_estimate": 10.00,
        "acceptance_criteria": "Memo C accepted",
    }
]

DILIGENCE_REPORT = [
    {
        "title": "Diligence report",
        "sequence_no": 1,
        "weight_pct": 100.00,
        "hours_estimate": 40.00,
        "acceptance_criteria": "Report accepted",
    }
]


# ---------------------------------------------------------------------------
# A FAIL decision, four hops deep
# ---------------------------------------------------------------------------
def _failed_review_world():
    """A SUBMITTED engagement carrying a PROVISIONAL MARKET_RATE valuation over 12.00
    approved hours, plus a second OFFERED offer to the same volunteer, with round one
    of its review scored 2 / 2 for a FAIL outcome."""
    world = setup_submitted_engagement(
        skill_code="LEGAL_CONTRACTS",
        volunteer_seniority="SENIOR",
        volunteer_rate=150.00,
        deliverables=TWO_HALVES,
        time_logs=TWELVE_HOURS_TWO_CLASSES,
        reported_cumulative_hours=12.00,
        title="Grant agreements",
    )
    world["market_rate_record"] = validate_success(
        api_client.create_valuation(
            world["engagement"]["id"],
            {
                "expected_engagement_version": current_engagement_version(world),
                "method": "MARKET_RATE",
            },
            world["pm_headers"],
        ),
        expected_status=201,
    )
    world["second"] = add_scoped_request(
        world,
        skill_code="LEGAL_CONTRACTS",
        estimated_hours=20.00,
        deliverables=MINUTE_BOOK,
        title="Board minutes cleanup",
    )
    world["second_offer"] = get_success_data(
        api_client.match_project_request(
            world["second"]["request"]["id"], world["spec_headers"]
        )
    )
    first, second = world["deliverables"]
    world["review"] = drive_review_to_outcome(world, {first["id"]: 2, second["id"]: 2})
    return world


def _decide(world):
    return validate_success(
        api_client.decide_quality_review(
            world["review"]["id"], world["reviewer_headers"]
        )
    )


def test_failed_review_terminates_the_engagement_it_judged(api):
    """PRD §3.8: "**Step one:** the engagement's `quality_gate` becomes `FAILED` and its
    `work_status` moves `SUBMITTED → TERMINATED` with `termination_reason`
    `QUALITY_FAILURE`, releasing the cycle slot and the window hours exactly as any
    termination does."
    PRD §3.8: "The `outcome` follows from the score: `PASS` at 78.00 and above,
    `CONDITIONAL` from 60.00 up to but not including 78.00, and `FAIL` below 60.00."

    Design: Difficulty/transitive_cascade/cascade_b_quality_fail_depth_four
    """
    world = _failed_review_world()

    decided = _decide(world)

    assert decided["weighted_score"] == pytest.approx(40.00, abs=0.01), (
        f"Expected weighted_score 40.00 from 20.00 + 20.00, got {decided['weighted_score']}"
    )
    assert decided["outcome"] == "FAIL", f"Expected outcome FAIL, got {decided['outcome']}"
    assert decided["status"] == "DECIDED", f"Expected DECIDED, got {decided['status']}"
    engagement = read_engagement(world)
    assert engagement["quality_gate"] == "FAILED", (
        f"Expected quality_gate FAILED, got {engagement['quality_gate']}"
    )
    assert engagement["work_status"] == "TERMINATED", (
        f"Expected work_status TERMINATED, got {engagement['work_status']}"
    )
    assert engagement["termination_reason"] == "QUALITY_FAILURE", (
        f"Expected termination_reason QUALITY_FAILURE, got "
        f"{engagement['termination_reason']}"
    )


def test_failed_review_restates_the_provisional_valuation_from_the_same_hours(api):
    """PRD §3.8: "**Step two:** because the engagement terminated while holding a posted
    valuation, its `valuation_status` moves from `FINAL` or `PROVISIONAL` to `RESTATED`, a
    compensating `INDEPENDENT_SECTOR` valuation record carrying `variant_label` `RESTATED`
    is posted, and the prior record's `superseded_at` is stamped."
    PRD §3.9: "It admits every approved log regardless of class — `DELIVERY`, `ADMIN` and
    `TRAVEL` alike — sets `hours_included` to the sum of their `hours` rounded to two
    decimals, sets `rate_applied_usd` to the flat national rate of 34.79 dollars an hour,
    and sets `base_amount_usd` to those hours multiplied by that rate, rounded once at the
    end."

    Design: Difficulty/transitive_cascade/cascade_b_quality_fail_depth_four
    """
    world = _failed_review_world()
    assert world["market_rate_record"]["total_amount_usd"] == pytest.approx(
        1848.00, abs=0.01
    ), (
        f"Setup expected a 1848.00 MARKET_RATE total, got "
        f"{world['market_rate_record']['total_amount_usd']}"
    )

    _decide(world)

    engagement = read_engagement(world)
    assert engagement["valuation_status"] == "RESTATED", (
        f"Expected valuation_status RESTATED, got {engagement['valuation_status']}"
    )
    records = read_valuation_records(world)
    prior = [r for r in records if r["id"] == world["market_rate_record"]["id"]][0]
    assert prior["superseded_at"] is not None, (
        "The restatement must stamp superseded_at on the prior record"
    )
    restated = [r for r in records if r["variant_label"] == "RESTATED"]
    assert len(restated) == 1, (
        f"Expected exactly one RESTATED record, got {len(restated)}"
    )
    compensating = restated[0]
    assert compensating["method"] == "INDEPENDENT_SECTOR", (
        f"The compensating record must be INDEPENDENT_SECTOR, got "
        f"{compensating['method']}"
    )
    assert compensating["hours_included"] == pytest.approx(12.00, abs=0.01), (
        f"Expected the same 12.00 approved hours, got {compensating['hours_included']}"
    )
    assert compensating["rate_applied_usd"] == pytest.approx(34.79, abs=0.01), (
        f"Expected rate_applied_usd 34.79, got {compensating['rate_applied_usd']}"
    )
    assert compensating["base_amount_usd"] == pytest.approx(417.48, abs=0.01), (
        f"Expected base_amount_usd 417.48, got {compensating['base_amount_usd']}"
    )
    assert compensating["admin_overhead_usd"] == pytest.approx(50.10, abs=0.01), (
        f"Expected admin_overhead_usd 50.10, got {compensating['admin_overhead_usd']}"
    )
    assert compensating["total_amount_usd"] == pytest.approx(467.58, abs=0.01), (
        f"Expected total_amount_usd 467.58, got {compensating['total_amount_usd']}"
    )


def test_failed_review_collapses_reliability_and_pauses_the_volunteer(api):
    """PRD §3.8: "**Step three:** because a restated record was posted, the volunteer's
    `lifetime_valued_usd` is recomputed from her non-superseded `INDEPENDENT_SECTOR` records
    and both reliability variants rerun."
    PRD §3.8: "**Step four:** because the decay-weighted `reliability_score` has now fallen
    strictly below 0.4000, the volunteer moves `ACTIVE → PAUSED` with `pause_reason`
    `RELIABILITY_FLOOR`, and every match offer she still holds in `OFFERED` moves to
    `WITHDRAWN` with `withdraw_reason` `VOLUNTEER_PAUSED`, releasing their reserved hours
    and their cycle slots in turn."

    Design: Difficulty/transitive_cascade/cascade_b_quality_fail_depth_four
    """
    world = _failed_review_world()

    _decide(world)

    volunteer = read_volunteer(world)
    assert volunteer["lifetime_valued_usd"] == pytest.approx(467.58, abs=0.01), (
        f"Expected lifetime_valued_usd 467.58 from the restated record alone, got "
        f"{volunteer['lifetime_valued_usd']}"
    )
    assert volunteer["terminal_engagement_count"] == 1, (
        f"Expected terminal_engagement_count 1, got "
        f"{volunteer['terminal_engagement_count']}"
    )
    assert volunteer["reliability_score"] == pytest.approx(0.0000, abs=1e-4), (
        f"A QUALITY_FAILURE terminal is worth 0.00 points, got "
        f"{volunteer['reliability_score']}"
    )
    assert volunteer["reliability_score_lifetime"] == pytest.approx(0.0000, abs=1e-4), (
        f"Expected reliability_score_lifetime 0.0000, got "
        f"{volunteer['reliability_score_lifetime']}"
    )
    assert volunteer["status"] == "PAUSED", (
        f"Expected the volunteer PAUSED below the 0.4000 floor, got {volunteer['status']}"
    )
    assert volunteer["pause_reason"] == "RELIABILITY_FLOOR", (
        f"Expected pause_reason RELIABILITY_FLOOR, got {volunteer['pause_reason']}"
    )
    offer = read_offer(world, world["second_offer"]["id"])
    assert offer["status"] == "WITHDRAWN", (
        f"The unrelated open offer must be withdrawn, got {offer['status']}"
    )
    assert offer["withdraw_reason"] == "VOLUNTEER_PAUSED", (
        f"Expected withdraw_reason VOLUNTEER_PAUSED, got {offer['withdraw_reason']}"
    )
    second_request = read_request(world, world["second"]["request"]["id"])
    assert second_request["status"] == "SCOPED", (
        f"Expected the untouched request back at SCOPED, got {second_request['status']}"
    )
    assert second_request["failed_match_rounds"] == 1, (
        f"A VOLUNTEER_PAUSED withdrawal charges a failed round, got "
        f"{second_request['failed_match_rounds']}"
    )


def test_failed_review_returns_every_hour_and_slot_across_both_requests(api):
    """PRD §2.8: "For every program cycle, `slots_committed` plus `slots_reserved` plus
    `slots_available` always equals `capacity_slot_total`."
    PRD §2.8: "No slot may be stranded by the cascades that ride along — sibling offer
    withdrawals, posture recomputation, milestone waivers — and no slot may be
    double-released."
    PRD §2.9: "Declining an offer, the expiry sweep, termination and handoff are all release
    paths, and each subtracts the current held amount rather than a remembered one."

    Design: Difficulty/transitive_cascade/cascade_b_quality_fail_depth_four
    """
    world = _failed_review_world()

    _decide(world)

    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(0.00, abs=0.01), (
        f"Expected hours_committed 0.00 after both releases, got "
        f"{window['hours_committed']}"
    )
    assert window["hours_remaining"] == pytest.approx(300.00, abs=0.01), (
        f"Expected hours_remaining 300.00, got {window['hours_remaining']}"
    )
    cycle = read_cycle(world)
    assert cycle["slots_committed"] == 0, (
        f"Expected slots_committed 0, got {cycle['slots_committed']}"
    )
    assert cycle["slots_reserved"] == 0, (
        f"Expected slots_reserved 0, got {cycle['slots_reserved']}"
    )
    assert cycle["slots_available"] == 10, (
        f"Expected slots_available 10, got {cycle['slots_available']}"
    )
    assert cycle["utilization_ratio"] == pytest.approx(0.0000, abs=1e-4), (
        f"Expected utilization_ratio 0.0000, got {cycle['utilization_ratio']}"
    )
    assert cycle["posture"] == "OPEN", f"Expected posture OPEN, got {cycle['posture']}"


# ---------------------------------------------------------------------------
# A partner suspension, five hops deep across four entity families
# ---------------------------------------------------------------------------
def _suspension_world():
    """A partner holding one IN_PROGRESS engagement with a SCHEDULED milestone, one
    MATCHING request with an OFFERED offer, and one SCOPED request never matched."""
    world = setup_in_progress_engagement(
        skill_code="LEGAL_CONTRACTS",
        deliverables=MEMO_A,
        title="Request A",
    )
    world["milestone"] = get_success_data(
        api_client.create_milestone(
            world["engagement"]["id"],
            {"due_at": "2026-08-25T00:00:00Z"},
            world["pm_headers"],
        )
    )
    world["request_b"] = add_scoped_request(
        world,
        skill_code="LEGAL_CONTRACTS",
        estimated_hours=20.00,
        deliverables=MEMO_B,
        title="Request B",
    )
    world["offer_b"] = get_success_data(
        api_client.match_project_request(
            world["request_b"]["request"]["id"], world["spec_headers"]
        )
    )
    world["request_c"] = add_scoped_request(
        world,
        skill_code="LEGAL_CONTRACTS",
        estimated_hours=10.00,
        deliverables=MEMO_C,
        title="Request C",
    )
    set_clock("2026-08-10T00:00:00Z", world["pm_headers"])
    return world


def _suspend(world):
    return validate_success(
        api_client.patch_partner_org_status(
            world["partner"]["id"], {"to_status": "SUSPENDED"}, world["pm_headers"]
        )
    )


def test_suspension_abandons_every_in_flight_request_and_withdraws_its_offer(api):
    """PRD §3.1: "The transition stamps `suspended_at` from the logical clock; every project
    request of that partner sitting in `DRAFT`, `SCOPING`, `SCOPED`, `MATCHING` or
    `RESCOPING` moves to `ABANDONED`; each abandoned request in turn moves its `OFFERED`
    match offers to `WITHDRAWN` with `withdraw_reason` set to `PARTNER_SUSPENDED`; each such
    withdrawal subtracts that offer's `reserved_hours` from the holding window's
    `hours_committed` and forces the cycle's `slots_reserved` to be recomputed; and every
    engagement of that partner whose `work_status` is `NOT_STARTED`, `IN_PROGRESS`,
    `SUBMITTED` or `ACCEPTED` moves to `TERMINATED` with `termination_reason` set to
    `PARTNER_SUSPENDED`."

    Design: Difficulty/transitive_cascade/partner_suspension_depth_five
    """
    world = _suspension_world()

    partner = _suspend(world)

    assert partner["status"] == "SUSPENDED", (
        f"Expected status SUSPENDED, got {partner['status']}"
    )
    assert partner["suspended_at"].startswith("2026-08-10T00:00:00"), (
        f"Expected suspended_at stamped from the clock, got {partner['suspended_at']}"
    )
    request_b = read_request(world, world["request_b"]["request"]["id"])
    assert request_b["status"] == "ABANDONED", (
        f"Expected the MATCHING request ABANDONED, got {request_b['status']}"
    )
    request_c = read_request(world, world["request_c"]["request"]["id"])
    assert request_c["status"] == "ABANDONED", (
        f"Expected the SCOPED request ABANDONED, got {request_c['status']}"
    )
    offer_b = read_offer(world, world["offer_b"]["id"])
    assert offer_b["status"] == "WITHDRAWN", (
        f"Expected the open offer WITHDRAWN, got {offer_b['status']}"
    )
    assert offer_b["withdraw_reason"] == "PARTNER_SUSPENDED", (
        f"Expected withdraw_reason PARTNER_SUSPENDED, got {offer_b['withdraw_reason']}"
    )
    assert read_partner(world)["open_engagement_count"] == 0, (
        "A suspended partner must hold no open engagement"
    )


def test_suspension_terminates_the_live_engagement_and_waives_its_milestone(api):
    """PRD §3.9: "Every child milestone still `SCHEDULED` moves to `WAIVED` with
    `waiver_reason` `ENGAGEMENT_TERMINATED`."
    PRD §3.9: "The governing agreement, unless it had already reached `EXECUTED`, moves to
    `VOIDED` with `void_reason` `ENGAGEMENT_TERMINATED`."

    Design: Difficulty/transitive_cascade/partner_suspension_depth_five
    """
    world = _suspension_world()

    _suspend(world)

    engagement = read_engagement(world)
    assert engagement["work_status"] == "TERMINATED", (
        f"Expected the live engagement TERMINATED, got {engagement['work_status']}"
    )
    assert engagement["termination_reason"] == "PARTNER_SUSPENDED", (
        f"Expected termination_reason PARTNER_SUSPENDED, got "
        f"{engagement['termination_reason']}"
    )
    assert engagement["terminated_at"].startswith("2026-08-10T00:00:00"), (
        f"Expected terminated_at stamped from the clock, got {engagement['terminated_at']}"
    )
    milestones = {m["id"]: m for m in read_milestones(world)}
    waived = milestones[world["milestone"]["id"]]
    assert waived["checkin_status"] == "WAIVED", (
        f"Expected the SCHEDULED milestone WAIVED, got {waived['checkin_status']}"
    )
    assert waived["waiver_reason"] == "ENGAGEMENT_TERMINATED", (
        f"Expected waiver_reason ENGAGEMENT_TERMINATED, got {waived['waiver_reason']}"
    )
    agreement = read_agreement(world)
    assert agreement["status"] == "EXECUTED", (
        f"An already EXECUTED agreement survives the termination, got "
        f"{agreement['status']}"
    )


def test_suspension_terminal_scores_point_six_and_leaves_the_volunteer_active(api):
    """PRD §3.2: "Each terminal engagement earns a point value before penalties: 1.00 when
    it was `HANDED_OFF` with a `quality_gate` of `PASSED`; 0.70 when it was `HANDED_OFF`
    with a `quality_gate` of `CONDITIONAL`; 0.00 when it was `TERMINATED` for
    `QUALITY_FAILURE`; 0.25 when it was `TERMINATED` for `SCOPE_BREACH` or `ADMIN`; and 0.60
    when it was `TERMINATED` for `AGREEMENT_VOIDED` or `PARTNER_SUSPENDED`."
    PRD §2.9: "Every release path must subtract exactly the amount that was added —
    including hours added later by an approved scope change."

    Design: Difficulty/transitive_cascade/partner_suspension_depth_five
    """
    world = _suspension_world()

    _suspend(world)

    volunteer = read_volunteer(world)
    assert volunteer["terminal_engagement_count"] == 1, (
        f"Expected terminal_engagement_count 1, got "
        f"{volunteer['terminal_engagement_count']}"
    )
    assert volunteer["reliability_score"] == pytest.approx(0.6000, abs=1e-4), (
        f"Expected reliability_score 0.6000, got {volunteer['reliability_score']}"
    )
    assert volunteer["reliability_score_lifetime"] == pytest.approx(0.6000, abs=1e-4), (
        f"Expected reliability_score_lifetime 0.6000, got "
        f"{volunteer['reliability_score_lifetime']}"
    )
    assert volunteer["status"] == "ACTIVE", (
        f"0.6000 sits above the 0.4000 floor, so the volunteer stays ACTIVE; got "
        f"{volunteer['status']}"
    )
    assert volunteer["pause_reason"] is None, (
        f"Expected a null pause_reason, got {volunteer['pause_reason']}"
    )
    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(0.00, abs=0.01), (
        f"Expected hours_committed 0.00 after 40.00 and 20.00 released, got "
        f"{window['hours_committed']}"
    )
    assert window["hours_remaining"] == pytest.approx(300.00, abs=0.01), (
        f"Expected hours_remaining 300.00, got {window['hours_remaining']}"
    )
    cycle = read_cycle(world)
    assert cycle["slots_committed"] == 0, (
        f"Expected slots_committed 0, got {cycle['slots_committed']}"
    )
    assert cycle["slots_reserved"] == 0, (
        f"Expected slots_reserved 0, got {cycle['slots_reserved']}"
    )
    assert cycle["slots_available"] == 10, (
        f"Expected slots_available 10, got {cycle['slots_available']}"
    )
    assert cycle["posture"] == "OPEN", f"Expected posture OPEN, got {cycle['posture']}"


# ---------------------------------------------------------------------------
# A forced re-scope, five hops deep, started by a calculation
# ---------------------------------------------------------------------------
def _engagement_ready_for_a_half_creep_request():
    """An IN_PROGRESS engagement with 12.00 approved hours against a 40.00-hour baseline,
    a HELD first milestone and a still-SCHEDULED second one."""
    world = setup_in_progress_engagement(
        skill_code="LEGAL_CONTRACTS",
        deliverables=DILIGENCE_REPORT,
        title="Merger due diligence",
    )
    world["milestone_one"] = get_success_data(
        api_client.create_milestone(
            world["engagement"]["id"],
            {"due_at": "2026-08-20T00:00:00Z"},
            world["pm_headers"],
        )
    )
    world["milestone_two"] = get_success_data(
        api_client.create_milestone(
            world["engagement"]["id"],
            {"due_at": "2026-08-24T00:00:00Z"},
            world["pm_headers"],
        )
    )
    get_success_data(
        api_client.create_time_log(
            world["engagement"]["id"],
            {
                "work_date": "2026-08-12T00:00:00Z",
                "hours": 12.00,
                "activity_class": "DELIVERY",
            },
            world["volunteer_headers"],
        )
    )
    set_clock("2026-08-19T00:00:00Z", world["pm_headers"])
    get_success_data(
        api_client.hold_milestone(
            world["milestone_one"]["id"],
            {"reported_cumulative_hours": 12.00},
            world["pm_headers"],
        )
    )
    return world


def _request_forty_eight_more_hours(world):
    return validate_success(
        api_client.create_scope_change_request(
            world["engagement"]["id"],
            {
                "additional_hours": 48.00,
                "additional_deliverable_count": 0,
                "justification": "Target added two subsidiaries mid-review",
            },
            world["partner_headers"],
        ),
        expected_status=201,
    )


def test_projection_at_exactly_the_rescope_floor_escalates_the_change_request(api):
    """PRD §3.7: "Before the row is persisted the program projects its effect: take the
    engagement's `approved_hours`, add the sum of `additional_hours` over sibling change
    requests whose `status` is `PENDING` or `ESCALATED` — excluding the incoming row — add
    the incoming row's own `additional_hours`, subtract the engagement's `committed_hours`
    baseline, divide by that baseline and round to four decimals."
    PRD §3.7: "That figure is stored as `projected_creep_pct`, and the `decision_tier` is
    chosen from it by tests applied in exactly this order: a projection at or above 0.5000
    is `RESCOPE_REQUIRED`; otherwise a projection strictly below 0.1500 that also carries an
    `additional_deliverable_count` of exactly zero is `AUTO_APPROVABLE`; everything else is
    `MANAGER_REVIEW`."

    Design: Difficulty/transitive_cascade/rescope_required_scope_change_depth_five
    """
    world = _engagement_ready_for_a_half_creep_request()
    before = read_engagement(world)
    assert before["approved_hours"] == pytest.approx(12.00, abs=0.01), (
        f"Setup expected approved_hours 12.00, got {before['approved_hours']}"
    )
    assert before["committed_hours"] == pytest.approx(40.00, abs=0.01), (
        f"Setup expected committed_hours 40.00, got {before['committed_hours']}"
    )

    change = _request_forty_eight_more_hours(world)

    assert change["projected_creep_pct"] == pytest.approx(0.5000, abs=1e-4), (
        f"Expected projected_creep_pct 0.5000 from (12.00 + 48.00 - 40.00) / 40.00, got "
        f"{change['projected_creep_pct']}"
    )
    assert change["decision_tier"] == "RESCOPE_REQUIRED", (
        f"Exactly 0.5000 is at the inclusive floor, so the tier must be RESCOPE_REQUIRED; "
        f"got {change['decision_tier']}"
    )
    assert change["requested_by"] == "PARTNER", (
        f"Expected requested_by derived as PARTNER, got {change['requested_by']}"
    )


def test_rescope_required_terminates_the_engagement_and_rescopes_the_request(api):
    """PRD §3.7: "A `RESCOPE_REQUIRED` change moves `PENDING → ESCALATED` in the same
    operation and is not a request for hours at all but a declaration that the engagement
    has outgrown its scope: the engagement is terminated with `termination_reason`
    `SCOPE_BREACH`, running the full release chain, the parent request moves
    `IN_DELIVERY → RESCOPING`, and the request's `rescope_count` rises by one — the
    escalation route requires `rescope_count` to still be below 3."
    PRD §3.9: "Every child scope change request in `PENDING` or `ESCALATED` moves to
    `VOIDED`."

    Design: Difficulty/transitive_cascade/rescope_required_scope_change_depth_five
    """
    world = _engagement_ready_for_a_half_creep_request()

    change = _request_forty_eight_more_hours(world)

    engagement = read_engagement(world)
    assert engagement["work_status"] == "TERMINATED", (
        f"Expected work_status TERMINATED, got {engagement['work_status']}"
    )
    assert engagement["termination_reason"] == "SCOPE_BREACH", (
        f"Expected termination_reason SCOPE_BREACH, got "
        f"{engagement['termination_reason']}"
    )
    assert engagement["committed_hours"] == pytest.approx(40.00, abs=0.01), (
        f"An escalation is not a request for hours, so the baseline must be unchanged at "
        f"40.00; got {engagement['committed_hours']}"
    )
    request = read_request(world)
    assert request["status"] == "RESCOPING", (
        f"Expected the request at RESCOPING, got {request['status']}"
    )
    assert request["rescope_count"] == 1, (
        f"Expected rescope_count 1, got {request['rescope_count']}"
    )
    stored = {row["id"]: row for row in read_scope_changes(world)}[change["id"]]
    assert stored["status"] == "VOIDED", (
        f"The escalated row is voided by the very termination it caused, got "
        f"{stored['status']}"
    )


def test_scope_breach_termination_waives_the_open_milestone_and_pauses_the_volunteer(api):
    """PRD §3.7: "The third outcome, `SCHEDULED → WAIVED`, arrives only as a cascade — from
    a request entering `RESCOPING`, where `waiver_reason` is `RESCOPED`, or from an
    engagement termination, where it is `ENGAGEMENT_TERMINATED` — and a waived check-in never
    touches reliability."
    PRD §3.2: "One threshold consequence hangs off the decay-weighted figure alone: if
    `reliability_score` falls strictly below 0.4000 while the volunteer's `status` is
    `ACTIVE`, the volunteer moves to `PAUSED` with `pause_reason` `RELIABILITY_FLOOR`,
    dragging the offer-withdrawal cascade above with it."

    Design: Difficulty/transitive_cascade/rescope_required_scope_change_depth_five
    """
    world = _engagement_ready_for_a_half_creep_request()

    _request_forty_eight_more_hours(world)

    milestones = {m["id"]: m for m in read_milestones(world)}
    assert milestones[world["milestone_one"]["id"]]["checkin_status"] == "HELD", (
        f"The already-held check-in must stay HELD, got "
        f"{milestones[world['milestone_one']['id']]['checkin_status']}"
    )
    second = milestones[world["milestone_two"]["id"]]
    assert second["checkin_status"] == "WAIVED", (
        f"Expected the SCHEDULED check-in WAIVED, got {second['checkin_status']}"
    )
    assert second["waiver_reason"] == "ENGAGEMENT_TERMINATED", (
        f"Expected waiver_reason ENGAGEMENT_TERMINATED, got {second['waiver_reason']}"
    )
    volunteer = read_volunteer(world)
    assert volunteer["terminal_engagement_count"] == 1, (
        f"Expected terminal_engagement_count 1, got "
        f"{volunteer['terminal_engagement_count']}"
    )
    assert volunteer["reliability_score"] == pytest.approx(0.2500, abs=1e-4), (
        f"A SCOPE_BREACH terminal is worth 0.25 points, got "
        f"{volunteer['reliability_score']}"
    )
    assert volunteer["status"] == "PAUSED", (
        f"0.2500 is strictly below the 0.4000 floor, so the volunteer must be PAUSED; got "
        f"{volunteer['status']}"
    )
    assert volunteer["pause_reason"] == "RELIABILITY_FLOOR", (
        f"Expected pause_reason RELIABILITY_FLOOR, got {volunteer['pause_reason']}"
    )
    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(0.00, abs=0.01), (
        f"Expected hours_committed 0.00 after the release, got "
        f"{window['hours_committed']}"
    )
    cycle = read_cycle(world)
    assert cycle["slots_committed"] == 0, (
        f"Expected slots_committed 0, got {cycle['slots_committed']}"
    )
    assert cycle["posture"] == "OPEN", f"Expected posture OPEN, got {cycle['posture']}"

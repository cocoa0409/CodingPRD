"""Bounded negotiation cycles, the revision loop and the production board's postures."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_issue_dimensions,
    assert_version_unchanged,
    factories,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_creator_headers

EIC = TEST_USERS["editor_in_chief_headers"]
ME = TEST_USERS["managing_editor_headers"]

# The two completed rounds of the bounded negotiation cycle: each pair is the
# creator's counter followed by the editor's reproposal of revised terms.
NEGOTIATION_ROUNDS = (
    (
        {"counter_page_rate_cents": 14000, "counter_royalty_share_bps": 5500},
        {"page_rate_cents": 12500, "royalty_share_bps": 5100},
    ),
    (
        {"counter_page_rate_cents": 13800, "counter_royalty_share_bps": 5400},
        {"page_rate_cents": 13000, "royalty_share_bps": 5200},
    ),
)

THIRD_COUNTER = {"counter_page_rate_cents": 13600, "counter_royalty_share_bps": 5300}


def _proposed_script_assignment() -> dict:
    """A greenlit title carrying one `PROPOSED` `SCRIPT` offer at round 1."""
    return fixtures.setup_greenlit_title_with_script_assignment(
        accept=False, assignment_overrides={"booking_end_date": "2026-12-01"}
    )


def _negotiation_at_the_third_counter() -> dict:
    """The cycle traversed twice, then countered a third time: round 3, `COUNTERED`."""
    state = _proposed_script_assignment()
    assignment_id = state["assignment"]["id"]
    creator_id = state["creator"]["id"]
    for counter, repropose in NEGOTIATION_ROUNDS:
        fixtures.counter_assignment(assignment_id, creator_id, **counter)
        fixtures.repropose_assignment(assignment_id, **repropose)
    state["assignment"] = fixtures.counter_assignment(
        assignment_id, creator_id, **THIRD_COUNTER
    )
    return state


def _issue_with_kicked_back_script_stage() -> dict:
    """An issue whose `SCRIPT` stage was delivered seven days late and kicked back.

    A second `PENCILS` stage sits `NOT_STARTED` on an adjacent half-open booking,
    so a later delivery of its own can be added to the issue's recomputed total.
    """
    fixtures.set_clock()
    creator = fixtures.register_creator(
        full_name="Ada Allrounder",
        crafts=["SCRIPT", "PENCILS"],
        default_page_rate_cents=10000,
    )
    title = fixtures.pitch_and_greenlight_title()
    script_assignment = fixtures.offer_and_accept_assignment(
        title["id"],
        creator["id"],
        "SCRIPT",
        page_rate_cents=10000,
        royalty_share_bps=4000,
        booking_start_date="2026-08-01",
        booking_end_date="2026-09-01",
    )
    pencils_assignment = fixtures.offer_and_accept_assignment(
        title["id"],
        creator["id"],
        "PENCILS",
        page_rate_cents=9000,
        royalty_share_bps=3000,
        booking_start_date="2026-09-01",
        booking_end_date="2026-10-01",
    )
    issue = fixtures.schedule_issue(title["id"], target_on_sale_date="2026-12-02")
    script_stage = fixtures.book_stage(
        issue["id"],
        script_assignment["id"],
        "SCRIPT",
        planned_start_date="2026-08-01",
        planned_due_date="2026-08-20",
    )
    pencils_stage = fixtures.book_stage(
        issue["id"],
        pencils_assignment["id"],
        "PENCILS",
        planned_start_date="2026-08-21",
        planned_due_date="2026-09-10",
    )
    fixtures.start_stage(script_stage["id"], creator["id"])

    # Seven days past the 2026-08-20 due date, then rejected for a rewrite.
    fixtures.set_clock("2026-08-27T00:00:00Z")
    fixtures.deliver_stage(script_stage["id"], creator["id"])
    script_stage = fixtures.kick_back_stage(script_stage["id"])

    return {
        "creator": creator,
        "title": title,
        "script_assignment": script_assignment,
        "pencils_assignment": pencils_assignment,
        "issue": fixtures.read_issue(issue["id"]),
        "script_stage": script_stage,
        "pencils_stage": pencils_stage,
    }


def _issue_in_art_with_a_spare_script_assignment() -> dict:
    """An issue in `ART`: its `SCRIPT` stage is `APPROVED`, its `PENCILS` stage is running.

    A third creator holds a further `ACCEPTED` `SCRIPT` assignment that has not
    been booked onto the board yet.
    """
    fixtures.set_clock()
    writer = fixtures.register_creator(
        full_name="Wanda Writer", crafts=["SCRIPT"], default_page_rate_cents=12000
    )
    cowriter = fixtures.register_creator(
        full_name="Cody Cowriter", crafts=["SCRIPT"], default_page_rate_cents=8000
    )
    penciller = fixtures.register_creator(
        full_name="Pablo Penciller", crafts=["PENCILS"], default_page_rate_cents=9000
    )
    title = fixtures.pitch_and_greenlight_title()
    writer_assignment = fixtures.offer_and_accept_assignment(
        title["id"],
        writer["id"],
        "SCRIPT",
        page_rate_cents=12000,
        royalty_share_bps=4000,
        booking_start_date="2026-08-01",
        booking_end_date="2026-12-01",
    )
    pencils_assignment = fixtures.offer_and_accept_assignment(
        title["id"],
        penciller["id"],
        "PENCILS",
        page_rate_cents=9000,
        royalty_share_bps=3000,
        booking_start_date="2026-08-01",
        booking_end_date="2026-12-01",
    )
    cowriter_assignment = fixtures.offer_and_accept_assignment(
        title["id"],
        cowriter["id"],
        "SCRIPT",
        page_rate_cents=8000,
        royalty_share_bps=1000,
        booking_start_date="2026-08-01",
        booking_end_date="2026-12-01",
    )
    issue = fixtures.schedule_issue(title["id"], target_on_sale_date="2026-12-02")
    script_stage = fixtures.run_stage_to_approved(
        issue["id"],
        writer_assignment["id"],
        writer["id"],
        craft="SCRIPT",
        delivered_pages=22,
        planned_start_date="2026-08-01",
        planned_due_date="2026-08-20",
    )
    pencils_stage = fixtures.book_stage(
        issue["id"],
        pencils_assignment["id"],
        "PENCILS",
        planned_start_date="2026-08-21",
        planned_due_date="2026-09-10",
    )
    pencils_stage = fixtures.start_stage(pencils_stage["id"], penciller["id"])

    return {
        "writer": writer,
        "cowriter": cowriter,
        "penciller": penciller,
        "title": title,
        "writer_assignment": writer_assignment,
        "cowriter_assignment": cowriter_assignment,
        "pencils_assignment": pencils_assignment,
        "issue": fixtures.read_issue(issue["id"]),
        "script_stage": script_stage,
        "pencils_stage": pencils_stage,
    }


def _two_issues_each_with_one_running_script_stage() -> dict:
    """Two issues twenty-one days apart, each carrying its own `IN_PROGRESS` stage.

    Both stages are due 2026-08-20, and because each issue aggregates only its
    own stages the two slip totals never mix.
    """
    fixtures.set_clock()
    creator = fixtures.register_creator(
        full_name="Wanda Writer", crafts=["SCRIPT"], default_page_rate_cents=12000
    )
    title = fixtures.pitch_and_greenlight_title()
    assignment = fixtures.offer_and_accept_assignment(
        title["id"],
        creator["id"],
        "SCRIPT",
        page_rate_cents=12000,
        royalty_share_bps=4000,
        booking_start_date="2026-08-01",
        booking_end_date="2026-12-01",
    )
    issues, stages = [], []
    for issue_number, on_sale in ((1, "2026-10-14"), (2, "2026-11-04")):
        issue = fixtures.schedule_issue(
            title["id"], issue_number=issue_number, target_on_sale_date=on_sale
        )
        stage = fixtures.book_stage(
            issue["id"],
            assignment["id"],
            "SCRIPT",
            planned_start_date="2026-08-01",
            planned_due_date="2026-08-20",
        )
        fixtures.start_stage(stage["id"], creator["id"])
        issues.append(issue)
        stages.append(stage)
    return {
        "creator": creator,
        "title": title,
        "assignment": assignment,
        "issues": issues,
        "stages": stages,
    }


# ─── Negotiation cycle ────────────────────────────────

def test_reproposal_returns_the_assignment_to_proposed_and_clears_both_counter_fields():
    """One traversal of the cycle lands back on `PROPOSED` with the round ratcheted to 2.

    PRD: "The `EditorInChief` may then repropose, which moves it `COUNTERED → PROPOSED`, overwrites `page_rate_cents` and `royalty_share_bps` with the reproposed terms, clears both counter fields back to null, and increments `negotiation_round` by one."

    Design: Difficulty/non_linear_state_machine/negotiation_cycle_returns_to_proposed_and_exhausts_on_the_third_round
    """
    state = _proposed_script_assignment()
    assignment = state["assignment"]
    assert assignment["status"] == "PROPOSED"
    assert assignment["negotiation_round"] == 1
    assert assignment["counter_page_rate_cents"] is None

    countered = validate_success(
        api_client.counter_creative_assignment(
            assignment["id"],
            factories.counter_payload(
                counter_page_rate_cents=14000, counter_royalty_share_bps=5500
            ),
            make_creator_headers(state["creator"]["id"]),
        )
    )
    assert countered["status"] == "COUNTERED"
    assert countered["counter_page_rate_cents"] == 14000
    assert countered["counter_royalty_share_bps"] == 5500
    # Countering does not close a round; only the reproposal does.
    assert countered["negotiation_round"] == 1
    assert countered["page_rate_cents"] == 12000

    reproposed = validate_success(
        api_client.repropose_creative_assignment(
            assignment["id"],
            factories.repropose_payload(page_rate_cents=12500, royalty_share_bps=5100),
            EIC,
        )
    )
    assert reproposed["status"] == "PROPOSED"
    assert reproposed["negotiation_round"] == 2
    assert reproposed["page_rate_cents"] == 12500
    assert reproposed["royalty_share_bps"] == 5100
    assert reproposed["counter_page_rate_cents"] is None
    assert reproposed["counter_royalty_share_bps"] is None


def test_a_fourth_reproposal_is_refused_once_the_third_round_has_been_reached():
    """The loop is bounded by `negotiation_round`, not by the state graph.

    PRD: "At most three rounds are permitted: a reproposal is refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` once `negotiation_round` has already reached 3, so the third counter is the creator's last word."

    Design: Difficulty/non_linear_state_machine/negotiation_cycle_returns_to_proposed_and_exhausts_on_the_third_round
    """
    state = _proposed_script_assignment()
    assignment_id = state["assignment"]["id"]
    creator_id = state["creator"]["id"]

    fixtures.counter_assignment(
        assignment_id, creator_id, counter_page_rate_cents=14000,
        counter_royalty_share_bps=5500,
    )
    first_return = fixtures.repropose_assignment(
        assignment_id, page_rate_cents=12500, royalty_share_bps=5100
    )
    assert first_return["status"] == "PROPOSED"
    assert first_return["negotiation_round"] == 2

    fixtures.counter_assignment(
        assignment_id, creator_id, counter_page_rate_cents=13800,
        counter_royalty_share_bps=5400,
    )
    second_return = fixtures.repropose_assignment(
        assignment_id, page_rate_cents=13000, royalty_share_bps=5200
    )
    assert second_return["status"] == "PROPOSED"
    assert second_return["negotiation_round"] == 3
    assert second_return["page_rate_cents"] == 13000

    third_counter = fixtures.counter_assignment(
        assignment_id, creator_id, **THIRD_COUNTER
    )

    response = api_client.repropose_creative_assignment(
        assignment_id,
        factories.repropose_payload(page_rate_cents=13400, royalty_share_bps=5250),
        EIC,
    )
    validate_error(response, ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED.value)

    # The refusal writes nothing: the row is exactly where the third counter left it.
    stored = fixtures.read_assignment(assignment_id)
    assert stored["status"] == "COUNTERED"
    assert stored["negotiation_round"] == 3
    assert stored["page_rate_cents"] == 13000
    assert stored["royalty_share_bps"] == 5200
    assert stored["counter_page_rate_cents"] == 13600
    assert stored["counter_royalty_share_bps"] == 5300
    assert_version_unchanged(third_counter, stored)


def test_an_exhausted_negotiation_cannot_be_accepted_from_countered():
    """Acceptance has no edge out of `COUNTERED`, so the bounded loop cannot be closed by the creator.

    PRD: "It is legal only from `PROPOSED`, only by the creator named on the assignment, and only while the title is `GREENLIT`, `IN_PRODUCTION` or `PUBLISHING`."

    Design: Difficulty/non_linear_state_machine/negotiation_cycle_returns_to_proposed_and_exhausts_on_the_third_round
    """
    state = _negotiation_at_the_third_counter()
    assignment = state["assignment"]
    assert assignment["status"] == "COUNTERED"
    assert assignment["negotiation_round"] == 3

    response = api_client.accept_creative_assignment(
        assignment["id"], make_creator_headers(state["creator"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    stored = fixtures.read_assignment(assignment["id"])
    assert stored["status"] == "COUNTERED"
    assert fixtures.read_title(state["title"]["id"])["committed_share_bps"] == 0


def test_terminating_the_exhausted_offer_leaves_the_committed_royalty_share_at_zero():
    """The only exit from an exhausted cycle is termination, which commits nothing.

    PRD: "An offer that will not be agreed can be terminated by the `EditorInChief` from `PROPOSED`, `COUNTERED`, `ACCEPTED` or `ACTIVE`, provided no production stage of that assignment is currently `IN_PROGRESS` or `DELIVERED` — work in flight must be resolved first."

    Design: Difficulty/non_linear_state_machine/negotiation_cycle_returns_to_proposed_and_exhausts_on_the_third_round
    """
    state = _negotiation_at_the_third_counter()

    terminated = validate_success(
        api_client.terminate_creative_assignment(
            state["assignment"]["id"], factories.terminate_payload(), EIC
        )
    )
    assert terminated["status"] == "TERMINATED"
    assert terminated["terminated_reason"] is not None
    assert terminated["negotiation_round"] == 3

    assert fixtures.read_title(state["title"]["id"])["committed_share_bps"] == 0
    assert fixtures.read_creator(state["creator"]["id"])["active_assignment_count"] == 0


# ─── Revision loop and slip recomputation ─────────────

def test_redelivery_after_a_kick_back_overwrites_the_earlier_slip_rather_than_adding_to_it():
    """The second delivery scores 28 days of slip, not 7 + 28.

    PRD: "Each redelivery after a kick-back overwrites the previous value outright; the earlier round's lateness is discarded, which means an issue's total slip can genuinely **decrease** when a second delivery lands closer to the planned due date than the first did."

    Design: Difficulty/non_linear_state_machine/stage_revision_loop_recomputes_slip_instead_of_accumulating_it
    """
    state = _issue_with_kicked_back_script_stage()
    stage = state["script_stage"]
    creator_id = state["creator"]["id"]
    assert stage["slip_days"] == 7

    fixtures.start_stage(stage["id"], creator_id)
    fixtures.set_clock("2026-09-17T00:00:00Z")
    redelivered = validate_success(
        api_client.deliver_production_stage(
            stage["id"],
            factories.deliver_payload(delivered_pages=22),
            make_creator_headers(creator_id),
        )
    )

    # 2026-08-20 to 2026-09-17 is 28 whole calendar days; the earlier 7 is discarded.
    assert redelivered["status"] == "DELIVERED"
    assert redelivered["slip_days"] == 28
    assert redelivered["slip_days"] != 35

    issue = fixtures.read_issue(state["issue"]["id"])
    assert issue["total_slip_days"] == 28
    assert_issue_dimensions(issue, schedule_health="SLIPPED")


def test_a_kicked_back_stage_keeps_the_rejected_rounds_slip_until_its_next_delivery():
    """Re-entering `IN_PROGRESS` neither zeroes the stage's slip nor the issue's total.

    PRD: "The issue's `total_slip_days` is then re-summed from scratch as the sum of `slip_days` over that issue's stages whose status is `DELIVERED`, `KICKED_BACK` or `APPROVED`; stages that are `NOT_STARTED`, `IN_PROGRESS` or `CANCELLED` contribute nothing, and a `KICKED_BACK` stage keeps the slip of the rejected delivery until its next delivery overwrites it."

    Design: Difficulty/non_linear_state_machine/stage_revision_loop_recomputes_slip_instead_of_accumulating_it
    """
    state = _issue_with_kicked_back_script_stage()
    stage = state["script_stage"]
    assert stage["status"] == "KICKED_BACK"
    assert stage["kickback_count"] == 1
    assert stage["slip_days"] == 7

    # The kicked-back round still counts, and the untouched PENCILS stage does not.
    kicked_back_issue = fixtures.read_issue(state["issue"]["id"])
    assert kicked_back_issue["total_slip_days"] == 7
    assert_issue_dimensions(
        kicked_back_issue, production_status="SCRIPTING", schedule_health="ON_TRACK"
    )
    assert fixtures.read_stage(state["pencils_stage"]["id"])["slip_days"] == 0

    restarted = validate_success(
        api_client.start_production_stage(
            stage["id"], make_creator_headers(state["creator"]["id"])
        )
    )
    assert restarted["status"] == "IN_PROGRESS"
    assert restarted["slip_days"] == 7

    # Only a delivery re-sums the aggregate, so the restart leaves it at seven.
    restarted_issue = fixtures.read_issue(state["issue"]["id"])
    assert restarted_issue["total_slip_days"] == 7
    assert_issue_dimensions(restarted_issue, schedule_health="ON_TRACK")


def test_a_second_stages_delivery_adds_its_own_slip_to_the_recomputed_issue_total():
    """The issue total is the sum over its stages: 28 from the rewritten script plus 7 from pencils.

    PRD: "The stage's `slip_days` becomes the number of whole calendar days by which the delivery instant's UTC date falls after the `planned_due_date`'s UTC date, floored at 0 so an early or on-time delivery scores no slip at all."

    Design: Difficulty/non_linear_state_machine/stage_revision_loop_recomputes_slip_instead_of_accumulating_it
    """
    state = _issue_with_kicked_back_script_stage()
    creator_id = state["creator"]["id"]
    script_stage_id = state["script_stage"]["id"]
    pencils_stage_id = state["pencils_stage"]["id"]

    fixtures.start_stage(script_stage_id, creator_id)
    fixtures.set_clock("2026-09-17T00:00:00Z")
    fixtures.deliver_stage(script_stage_id, creator_id, 22)

    fixtures.start_stage(pencils_stage_id, creator_id)
    pencils = validate_success(
        api_client.deliver_production_stage(
            pencils_stage_id,
            factories.deliver_payload(delivered_pages=22),
            make_creator_headers(creator_id),
        )
    )
    # The pencils stage was due 2026-09-10 and landed on 2026-09-17.
    assert pencils["slip_days"] == 7

    issue = fixtures.read_issue(state["issue"]["id"])
    assert issue["total_slip_days"] == 35
    assert_issue_dimensions(issue, schedule_health="SLIPPED")

    script_stage = fixtures.read_stage(script_stage_id)
    assert script_stage["slip_days"] == 28
    # The loop was traversed exactly once and no fee is frozen without an approval.
    assert script_stage["kickback_count"] == 1
    assert script_stage["page_fee_cents"] == 0
    assert (
        fixtures.read_assignment(state["script_assignment"]["id"])["status"] == "ACTIVE"
    )


# ─── Backwards edge on the production dimension ───────

def test_booking_a_late_co_writer_script_stage_regresses_the_issue_from_art_to_scripting():
    """The parent dimension crosses a craft boundary backwards although no child regressed.

    PRD: "It regresses `ART → SCRIPTING` when a further `SCRIPT` stage is booked onto an issue already in `ART`: the new stage arrives `NOT_STARTED`, so "every `SCRIPT` stage is approved" stops holding while at least one `PENCILS`, `INKS` or `COLORS` stage is still unapproved."

    Design: Difficulty/non_linear_state_machine/production_status_regresses_from_art_to_scripting_when_a_late_script_stage_is_booked
    """
    state = _issue_in_art_with_a_spare_script_assignment()
    before = fixtures.read_issue(state["issue"]["id"])
    assert_issue_dimensions(before, production_status="ART")

    late_stage = validate_success(
        api_client.create_production_stage(
            before["id"],
            factories.stage_payload(
                state["cowriter_assignment"]["id"],
                craft="SCRIPT",
                planned_start_date="2026-08-21",
                planned_due_date="2026-09-05",
            ),
            ME,
        ),
        expected_status=201,
    )
    assert late_stage["status"] == "NOT_STARTED"

    after = fixtures.read_issue(before["id"])
    assert_issue_dimensions(after, production_status="SCRIPTING")
    assert after["version"] == before["version"] + 1

    # No child moved backwards; only the child set grew.
    assert fixtures.read_stage(state["script_stage"]["id"])["status"] == "APPROVED"
    assert fixtures.read_stage(state["pencils_stage"]["id"])["status"] == "IN_PROGRESS"


def test_approving_the_late_co_writer_stage_advances_the_issue_back_to_art():
    """The same edge is traversed in the opposite direction once every script stage is approved.

    PRD: "It advances `SCRIPTING → ART` once every `SCRIPT` stage of the issue is `APPROVED` while at least one stage whose craft is `PENCILS`, `INKS` or `COLORS` is not yet `APPROVED`."

    Design: Difficulty/non_linear_state_machine/production_status_regresses_from_art_to_scripting_when_a_late_script_stage_is_booked
    """
    state = _issue_in_art_with_a_spare_script_assignment()
    issue_id = state["issue"]["id"]

    late_stage = fixtures.book_stage(
        issue_id,
        state["cowriter_assignment"]["id"],
        "SCRIPT",
        planned_start_date="2026-08-21",
        planned_due_date="2026-09-05",
    )
    assert_issue_dimensions(
        fixtures.read_issue(issue_id), production_status="SCRIPTING"
    )

    fixtures.start_stage(late_stage["id"], state["cowriter"]["id"])
    fixtures.deliver_stage(late_stage["id"], state["cowriter"]["id"], 6)
    approved = validate_success(
        api_client.approve_production_stage(late_stage["id"], ME)
    )
    assert approved["status"] == "APPROVED"
    assert approved["page_fee_cents"] == 8000 * 6

    assert_issue_dimensions(fixtures.read_issue(issue_id), production_status="ART")
    # 12000 * 22 from the original script plus 8000 * 6 from the co-writer.
    assert fixtures.read_title(state["title"]["id"])["production_cost_cents"] == 312000


def test_the_production_regression_leaves_the_commercial_dimension_untouched():
    """The board's backwards edge never moves the commercial dimension or the posture.

    PRD: "The two run independently, and exactly one operation in the entire system reads both dimensions of the same row: putting the issue on sale."

    Design: Difficulty/non_linear_state_machine/production_status_regresses_from_art_to_scripting_when_a_late_script_stage_is_booked
    """
    state = _issue_in_art_with_a_spare_script_assignment()
    issue_id = state["issue"]["id"]
    assert_issue_dimensions(
        fixtures.read_issue(issue_id),
        production_status="ART",
        commercial_status="UNSOLICITED",
        schedule_health="ON_TRACK",
    )

    late_stage = fixtures.book_stage(
        issue_id,
        state["cowriter_assignment"]["id"],
        "SCRIPT",
        planned_start_date="2026-08-21",
        planned_due_date="2026-09-05",
    )
    assert_issue_dimensions(
        fixtures.read_issue(issue_id),
        production_status="SCRIPTING",
        commercial_status="UNSOLICITED",
        schedule_health="ON_TRACK",
    )

    fixtures.start_stage(late_stage["id"], state["cowriter"]["id"])
    fixtures.deliver_stage(late_stage["id"], state["cowriter"]["id"], 6)
    fixtures.approve_stage(late_stage["id"])

    final = fixtures.read_issue(issue_id)
    assert_issue_dimensions(
        final,
        production_status="ART",
        commercial_status="UNSOLICITED",
        schedule_health="ON_TRACK",
    )
    # Both deliveries landed before their due dates, so nothing slipped at all.
    assert final["total_slip_days"] == 0


# ─── Slip posture boundary ────────────────────────────

def test_twenty_one_days_of_slip_is_still_at_risk_rather_than_slipped():
    """Twenty-one days sits on the inclusive upper bound of `AT_RISK`.

    PRD: "So twenty-one days of accumulated slip is still `AT_RISK`, and twenty-two days is the first value that is `SLIPPED`."

    Design: Difficulty/boundary_precision_check/slip_posture_boundary_21_days_at_risk_versus_22_days_slipped
    """
    state = _two_issues_each_with_one_running_script_stage()
    issue = state["issues"][0]
    stage = state["stages"][0]

    # 2026-08-20 to 2026-09-10 is exactly twenty-one whole calendar days.
    fixtures.set_clock("2026-09-10T00:00:00Z")
    delivered = validate_success(
        api_client.deliver_production_stage(
            stage["id"],
            factories.deliver_payload(delivered_pages=22),
            make_creator_headers(state["creator"]["id"]),
        )
    )
    assert delivered["slip_days"] == 21

    read_issue = fixtures.read_issue(issue["id"])
    assert read_issue["total_slip_days"] == 21
    assert_issue_dimensions(
        read_issue, schedule_health="AT_RISK", commercial_status="UNSOLICITED"
    )


def test_twenty_two_days_of_slip_is_the_first_value_that_is_slipped():
    """One further day past the bound flips the posture, and the sibling issue is unaffected.

    PRD: "From that single number the issue's `schedule_health` posture is derived, with both thresholds inclusive upper bounds: a total of no more than one week of slip — seven days or fewer — is `ON_TRACK`; more than seven days but no more than three weeks, twenty-one days, is `AT_RISK`; and anything beyond twenty-one days is `SLIPPED`."

    Design: Difficulty/boundary_precision_check/slip_posture_boundary_21_days_at_risk_versus_22_days_slipped
    """
    state = _two_issues_each_with_one_running_script_stage()
    creator_id = state["creator"]["id"]

    fixtures.set_clock("2026-09-10T00:00:00Z")
    fixtures.deliver_stage(state["stages"][0]["id"], creator_id, 22)

    fixtures.set_clock("2026-09-11T00:00:00Z")
    delivered = validate_success(
        api_client.deliver_production_stage(
            state["stages"][1]["id"],
            factories.deliver_payload(delivered_pages=22),
            make_creator_headers(creator_id),
        )
    )
    assert delivered["slip_days"] == 22

    slipped_issue = fixtures.read_issue(state["issues"][1]["id"])
    assert slipped_issue["total_slip_days"] == 22
    assert_issue_dimensions(
        slipped_issue, schedule_health="SLIPPED", commercial_status="UNSOLICITED"
    )

    # Each issue aggregates only its own stages, so the 21-day book stays AT_RISK.
    at_risk_issue = fixtures.read_issue(state["issues"][0]["id"])
    assert at_risk_issue["total_slip_days"] == 21
    assert_issue_dimensions(at_risk_issue, schedule_health="AT_RISK")


def test_seven_days_of_slip_is_on_track_while_eight_days_is_at_risk():
    """The lower posture bound is inclusive too: a week of lateness is still on track.

    PRD: "From that single number the issue's `schedule_health` posture is derived, with both thresholds inclusive upper bounds: a total of no more than one week of slip — seven days or fewer — is `ON_TRACK`; more than seven days but no more than three weeks, twenty-one days, is `AT_RISK`; and anything beyond twenty-one days is `SLIPPED`."

    Design: Difficulty/boundary_precision_check/slip_posture_boundary_21_days_at_risk_versus_22_days_slipped
    """
    state = _two_issues_each_with_one_running_script_stage()
    creator_id = state["creator"]["id"]

    # Exactly one week past the 2026-08-20 due date.
    fixtures.set_clock("2026-08-27T00:00:00Z")
    on_track_stage = fixtures.deliver_stage(state["stages"][0]["id"], creator_id, 22)
    assert on_track_stage["slip_days"] == 7

    fixtures.set_clock("2026-08-28T00:00:00Z")
    at_risk_stage = validate_success(
        api_client.deliver_production_stage(
            state["stages"][1]["id"],
            factories.deliver_payload(delivered_pages=22),
            make_creator_headers(creator_id),
        )
    )
    assert at_risk_stage["slip_days"] == 8

    on_track_issue = fixtures.read_issue(state["issues"][0]["id"])
    assert on_track_issue["total_slip_days"] == 7
    assert_issue_dimensions(on_track_issue, schedule_health="ON_TRACK")

    at_risk_issue = fixtures.read_issue(state["issues"][1]["id"])
    assert at_risk_issue["total_slip_days"] == 8
    assert_issue_dimensions(at_risk_issue, schedule_health="AT_RISK")

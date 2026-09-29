"""States reached by paths that are not a straight line forward.

One case walks its money axis to the end while its casework axis stands still; one
presentation goes round the deferral cycle until the cycle's own ceiling stops it.
"""

from typing import Any, Dict

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    approve_disbursement,
    assert_case_money_invariants,
    assert_case_presentation,
    assert_funding_source_conservation,
    assert_recovery_case,
    assert_version_unchanged,
    create_funding_source,
    create_project,
    decide,
    deliberate,
    pay_disbursement,
    permit_project,
    present,
    read_case,
    read_funding_source,
    read_presentation,
    request_disbursement,
    setup_awarded_case,
    setup_deliberating_presentation,
    validate_error,
    validate_success,
)

CHAIR = TEST_USERS["unmet_needs_chair_headers"]
CASE_MANAGER = TEST_USERS["case_manager_headers"]


def _setup_half_paid_structure_case() -> Dict[str, Any]:
    """A fully committed 1000000 case with 400000 of it already paid.

    The single restricted grant holds exactly 1035000 cents, which is 1000000 of net
    plus the retention that net attracts, so the two payments together consume it to
    the cent.
    """
    scenario = setup_awarded_case(
        damage=[("STRUCTURE", 1_000_000)],
        orgs=[{"org_name": "Harbor Lutheran Fund", "annual_pledge_cap_cents": 5_000_000}],
        pledges=[(0, 1_000_000, "STRUCTURE_REPAIR")],
    )
    scenario["source"] = create_funding_source(
        label="Structure rebuild grant",
        source_type="FOUNDATION_GRANT",
        restriction_code="STRUCTURE_REPAIR_ONLY",
        total_cents=1_035_000,
        expires_on="2026-12-31",
        admin_retention_allowed=True,
    )
    project = create_project(scenario["case"]["id"], required_trade_hours={"FRAMING": 240})
    permit_project(project["id"], "PB-3306")
    scenario["project"] = project
    first = request_disbursement(
        scenario["case"]["id"], "STRUCTURE_REPAIR", 400_000, project_id=project["id"]
    )
    approve_disbursement(first["id"], "First draw approved")
    pay_disbursement(first["id"], "CHK-3306-A")
    scenario["first_disbursement"] = first
    scenario["case"] = read_case(scenario["case"]["id"])
    return scenario


def test_the_second_payment_carries_funding_status_from_disbursing_to_satisfied(api):
    """PRD §2.5: "Paying a disbursement drives `PARTIALLY_COMMITTED → DISBURSING` or
    `FULLY_COMMITTED → DISBURSING` while the paid net remains above zero and below the
    committed total, and drives `FULLY_COMMITTED → SATISFIED` or `DISBURSING →
    SATISFIED` once the paid net reaches the committed total."

    Design: Difficulty/non_linear_state_machine/case_funding_status_reaches_satisfied_while_case_status_holds_active_recovery
    """
    scenario = _setup_half_paid_structure_case()
    assert scenario["case"]["funding_status"] == "DISBURSING"
    assert scenario["case"]["total_net_disbursed_cents"] == 400_000

    second = request_disbursement(
        scenario["case"]["id"],
        "STRUCTURE_REPAIR",
        600_000,
        project_id=scenario["project"]["id"],
    )
    approve_disbursement(second["id"], "Final draw approved")
    paid = validate_success(
        api.pay_disbursement(
            second["id"],
            {"payment_reference": "CHK-3306-B"},
            TEST_USERS["disbursement_officer_headers"],
        )
    )

    assert paid["status"] == "PAID"
    assert paid["net_cents"] == 600_000
    assert paid["admin_retained_cents"] == 21_000
    assert paid["gross_cents"] == 621_000
    case = read_case(scenario["case"]["id"])
    assert_recovery_case(case)
    assert case["total_net_disbursed_cents"] == 1_000_000
    assert case["total_committed_cents"] == 1_000_000
    assert case["funding_status"] == "SATISFIED"


def test_the_casework_axis_holds_still_while_the_money_axis_runs_to_satisfied(api):
    """PRD §2.5: "Neither axis gates the other. A case may sit in `ACTIVE_RECOVERY`
    while its `funding_status` is still `PARTIALLY_COMMITTED`, and `funding_status` may
    move `FULLY_COMMITTED → DISBURSING` with no change to `case_status` at all."

    Design: Difficulty/non_linear_state_machine/case_funding_status_reaches_satisfied_while_case_status_holds_active_recovery
    """
    scenario = _setup_half_paid_structure_case()
    assert scenario["case"]["case_status"] == "ACTIVE_RECOVERY"

    second = request_disbursement(
        scenario["case"]["id"],
        "STRUCTURE_REPAIR",
        600_000,
        project_id=scenario["project"]["id"],
    )
    approve_disbursement(second["id"], "Final draw approved")
    pay_disbursement(second["id"], "CHK-3306-B")

    case = read_case(scenario["case"]["id"])
    assert case["funding_status"] == "SATISFIED"
    # SATISFIED does not itself move the case onto the closure runway.
    assert case["case_status"] == "ACTIVE_RECOVERY"
    assert case["residual_unmet_cents"] == 0
    assert_case_money_invariants(case)


def test_payment_moves_gross_out_of_committed_without_changing_availability(api):
    """PRD §3.6: "For every allocation line the funding source's `committed_cents`
    decreases by that line's gross while its `disbursed_cents` increases by the line's
    net and its `admin_retained_cents` increases by the line's retention — so
    `available_cents` is unchanged, exactly as §2.9 requires."

    Design: Difficulty/non_linear_state_machine/case_funding_status_reaches_satisfied_while_case_status_holds_active_recovery
    """
    scenario = _setup_half_paid_structure_case()
    after_first = read_funding_source(scenario["source"]["id"])
    assert after_first["committed_cents"] == 0
    assert after_first["disbursed_cents"] == 400_000
    assert after_first["admin_retained_cents"] == 14_000
    assert after_first["available_cents"] == 621_000
    assert_funding_source_conservation(after_first)

    second = request_disbursement(
        scenario["case"]["id"],
        "STRUCTURE_REPAIR",
        600_000,
        project_id=scenario["project"]["id"],
    )
    approve_disbursement(second["id"], "Final draw approved")
    after_approval = read_funding_source(scenario["source"]["id"])
    assert after_approval["committed_cents"] == 621_000
    assert after_approval["available_cents"] == 0
    assert after_approval["status"] == "EXHAUSTED"

    pay_disbursement(second["id"], "CHK-3306-B")

    after_payment = read_funding_source(scenario["source"]["id"])
    assert after_payment["committed_cents"] == 0
    assert after_payment["disbursed_cents"] == 1_000_000
    assert after_payment["admin_retained_cents"] == 35_000
    assert after_payment["available_cents"] == 0
    assert after_payment["status"] == "EXHAUSTED"
    assert_funding_source_conservation(after_payment)


def _requeue(presentation_id: str, session_id: str):
    """Send the requeue request as the case's own case manager."""
    return api_client.requeue_case_presentation(
        presentation_id, {"new_session_id": session_id}, CASE_MANAGER
    )


def _setup_presentation_at_the_deferral_ceiling() -> Dict[str, Any]:
    """A presentation that has been round the deferral cycle three times.

    Each lap is present, deliberate, defer, requeue onto the same still-open meeting;
    after the third lap the presentation is called and deliberated once more, so it is
    sitting in DELIBERATING with a deferral count of exactly 3.
    """
    scenario = setup_deliberating_presentation(
        damage=[("STRUCTURE", 800_000)],
        orgs=[{"org_name": "Riverside Civic Club", "annual_pledge_cap_cents": 900_000}],
        quorum_min_member_orgs=1,
        session_overrides={"session_label": "UNT 2026-09-10 evening"},
    )
    presentation_id = scenario["presentation"]["id"]
    counts = []
    for lap in range(3):
        deferred = decide(presentation_id, "DEFER", f"Deferred on lap {lap + 1}")
        counts.append(deferred["deferral_count"])
        requeued = validate_success(_requeue(presentation_id, scenario["session"]["id"]))
        assert requeued["status"] == "QUEUED"
        present(presentation_id)
        deliberate(presentation_id)
    scenario["deferral_counts"] = counts
    scenario["presentation"] = read_presentation(presentation_id)
    return scenario


def test_each_deferral_only_bumps_the_counter_and_leaves_the_case_alone(api):
    """PRD §3.5: "It increments `deferral_count` by 1 and leaves every commitment on
    the presentation in `PLEDGED`, so the pledges survive to the next meeting. It does
    not change the case's `case_status`, its `funding_status` or its
    `total_committed_cents`, and it consumes no organization capacity beyond the hold the
    existing `PLEDGED` commitments already represent."

    Design: Difficulty/non_linear_state_machine/presentation_defers_three_times_then_fourth_defer_is_refused
    """
    scenario = _setup_presentation_at_the_deferral_ceiling()

    assert scenario["deferral_counts"] == [1, 2, 3]
    presentation = scenario["presentation"]
    assert_case_presentation(presentation)
    assert presentation["status"] == "DELIBERATING"
    assert presentation["deferral_count"] == 3
    case = read_case(scenario["case"]["id"])
    assert case["case_status"] == "PRESENTED"
    assert case["funding_status"] == "UNFUNDED"
    assert case["total_committed_cents"] == 0


def test_requeueing_is_deliberately_unguarded_by_the_deferral_ceiling(api):
    """PRD §3.5: "Requeueing moves it `DEFERRED → QUEUED`, and this leg is deliberately
    *unguarded* by `deferral_count` — the ceiling lives on the deferral leg, not here."

    Design: Difficulty/non_linear_state_machine/presentation_defers_three_times_then_fourth_defer_is_refused
    """
    scenario = setup_deliberating_presentation(
        damage=[("STRUCTURE", 800_000)],
        orgs=[{"org_name": "Riverside Civic Club", "annual_pledge_cap_cents": 900_000}],
        quorum_min_member_orgs=1,
    )
    presentation_id = scenario["presentation"]["id"]
    for lap in range(3):
        decide(presentation_id, "DEFER", f"Deferred on lap {lap + 1}")
        if lap < 2:
            validate_success(_requeue(presentation_id, scenario["session"]["id"]))
            present(presentation_id)
            deliberate(presentation_id)

    at_ceiling = read_presentation(presentation_id)
    assert at_ceiling["deferral_count"] == 3
    assert at_ceiling["status"] == "DEFERRED"

    requeued = validate_success(_requeue(presentation_id, scenario["session"]["id"]))

    assert requeued["status"] == "QUEUED"
    assert requeued["queue_position"] == 1
    # The ceiling did not bite on this leg; the counter is carried over untouched.
    assert requeued["deferral_count"] == 3


def test_the_fourth_deferral_is_refused_and_the_presentation_stays_deliberating(api):
    """PRD §3.5: "Deferral is bounded: the branch is refused with
    `ERR_MAX_DEFERRALS_REACHED` once `deferral_count` has already reached 3. This is
    the guard that terminates the deferral cycle — the fourth attempt to defer fails
    and the presentation stays in `DELIBERATING` for the chair to award or deny
    instead."

    Design: Difficulty/non_linear_state_machine/presentation_defers_three_times_then_fourth_defer_is_refused
    """
    scenario = _setup_presentation_at_the_deferral_ceiling()
    before = scenario["presentation"]

    response = api.decide_case_presentation(
        before["id"], {"decision": "DEFER", "decision_note": "Fourth deferral attempt"}, CHAIR
    )

    validate_error(response, ApiErrorId.ERR_MAX_DEFERRALS_REACHED.value)
    after = read_presentation(before["id"])
    assert after["status"] == "DELIBERATING"
    assert after["deferral_count"] == 3
    assert_version_unchanged(before, after)
    case = read_case(scenario["case"]["id"])
    assert case["case_status"] == "PRESENTED"
    assert case["funding_status"] == "UNFUNDED"

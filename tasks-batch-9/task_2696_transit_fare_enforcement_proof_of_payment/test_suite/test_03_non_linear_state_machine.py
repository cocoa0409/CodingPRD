"""
State graphs that are not simple chains: two independent dimensions on one
record, a guarded cycle, and a status graph that returns to a state it left.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import ERR_APPEAL_STATUS_INVALID
from test_helpers.assertions import (
    assert_instant_equals,
    assert_citation_money_identity,
    assert_rate_equals,
)
from test_helpers.constants import (
    ADJUDICATION_REDUCED,
    ADJUDICATION_UPHELD,
    APPEAL_STATUS_SUBMITTED,
    APPEAL_STATUS_SUPPLEMENT_REQUESTED,
    DECISION_REDUCE,
    GROUNDS_PROCEDURAL_DEFECT,
    HEARING_STATUS_HELD,
    SETTLEMENT_OUTSTANDING,
    SETTLEMENT_PLAN_ACTIVE,
    SUSPENSION_REASON_ADMINISTRATIVE_HOLD,
    ZONE_STATUS_DESIGNATED,
    ZONE_STATUS_PENDING_SIGNAGE,
    ZONE_STATUS_SUSPENDED,
)
from test_helpers.test_users import (
    BOARD_MEMBER_HEADERS,
    HEARING_OFFICER_HEADERS,
    HEARING_OFFICER_USER_ID,
    PLANNER_HEADERS,
    make_rider_headers,
)


# ── Two dimensions on one citation ───────────────────────────────────

def _contested_second_offence(api):
    """A second-offence citation of 20160, contested and awaiting a decision."""
    env = fixtures.build_environment(api)
    deployment = fixtures.build_active_deployment(api, env)
    inspector_id = env["inspector"]["id"]
    warned = fixtures.build_pending_encounter(
        api, env, deployment, occurred_at="2026-08-05T07:00:00Z"
    )
    fixtures.resolve(api, warned["id"], inspector_id, "WARNING_ISSUED")
    cited = fixtures.build_pending_encounter(
        api, env, deployment, occurred_at="2026-08-05T08:00:00Z"
    )
    citation = fixtures.issue_citation(api, cited["id"], inspector_id)
    fixtures.move_clock(api, "2026-08-06T00:00:00Z")
    hearing = fixtures.contest(api, citation["id"], env["rider"]["id"])
    return env, citation, hearing


def test_a_reduction_rebands_the_fee_and_leaves_the_settlement_dimension_alone(api):
    """
    The `REDUCE` branch moves the citation to `REDUCED` and re-derives
    `admin_fee_cents` from scratch by re-banding on the new pre-fee penalty, so a
    reduction to 12000 carries a fee of 1440 and a total of 13440 while the
    settlement dimension is still `OUTSTANDING`.

    Design: Difficulty/non_linear_state_machine/citation_adjudication_and_settlement_dimensions_advance_independently
    """
    _env, citation, hearing = _contested_second_offence(api)

    decided = validate_success(
        api.decide_hearing(
            hearing["id"],
            factories.hearing_decision_payload(DECISION_REDUCE, reduced_penalty_cents=12000),
            HEARING_OFFICER_HEADERS,
        ),
        200,
    )

    assert decided["status"] == HEARING_STATUS_HELD
    assert decided["decision"] == DECISION_REDUCE
    assert decided["reduced_penalty_cents"] == 12000
    assert decided["hearing_officer_user_id"] == HEARING_OFFICER_USER_ID

    reduced = fixtures.read_citation(api, citation["id"])
    assert reduced["adjudication_status"] == ADJUDICATION_REDUCED
    assert reduced["settlement_status"] == SETTLEMENT_OUTSTANDING
    assert reduced["assessed_penalty_cents"] == 12000
    assert reduced["admin_fee_cents"] == 1440
    assert reduced["total_due_cents"] == 13440
    assert reduced["reduction_floor_cents"] == 9000
    assert_citation_money_identity(reduced)


def test_the_settlement_dimension_advances_without_disturbing_the_adjudication(api):
    """
    Opening a plan moves `settlement_status` to `PLAN_ACTIVE` from `OUTSTANDING`
    and leaves `adjudication_status` exactly where the hearing left it, so one
    citation holds `REDUCED` and `PLAN_ACTIVE` at the same time.

    Design: Difficulty/non_linear_state_machine/citation_adjudication_and_settlement_dimensions_advance_independently
    """
    env, citation, hearing = _contested_second_offence(api)
    fixtures.decide_hearing(api, hearing["id"], DECISION_REDUCE, reduced_penalty_cents=12000)

    reduced = fixtures.read_citation(api, citation["id"])
    plan = fixtures.get_success_data(
        api.create_payment_plan(
            factories.payment_plan_payload(
                citation_id=citation["id"],
                installment_count=2,
                down_payment_cents=1440,
                expected_citation_version=reduced["version"],
            ),
            make_rider_headers(env["rider"]["id"]),
        )
    )

    assert plan["financed_cents"] == 12000
    assert plan["base_installment_cents"] == 6000
    assert plan["final_installment_cents"] == 6000

    financed = fixtures.read_citation(api, citation["id"])
    assert financed["adjudication_status"] == ADJUDICATION_REDUCED
    assert financed["settlement_status"] == SETTLEMENT_PLAN_ACTIVE
    assert financed["amount_paid_cents"] == 1440
    assert financed["outstanding_balance_cents"] == 12000
    assert financed["reduction_floor_cents"] == 9000


# ── The guarded supplement cycle ─────────────────────────────────────

def _appeal_awaiting_supplement(api):
    """A submitted appeal against an upheld first-offence citation."""
    chain = fixtures.build_upheld_citation_chain(
        api, contest_at="2026-08-06T00:00:00Z", decided_at="2026-08-06T00:00:00Z"
    )
    fixtures.move_clock(api, "2026-08-07T00:00:00Z")
    appeal = fixtures.file_appeal(
        api,
        chain["citation"]["id"],
        chain["hearing"]["id"],
        chain["rider"]["id"],
        GROUNDS_PROCEDURAL_DEFECT,
        statement="The inspector did not present a badge before requesting proof of payment.",
    )
    return chain, appeal


def test_the_supplement_cycle_returns_to_submitted_and_raises_the_round_index(api):
    """
    A board member moves a `SUBMITTED` appeal to `SUPPLEMENT_REQUESTED` and sets
    `supplement_deadline_at` to the logical clock plus 14 days; the appellant then
    resupplies, moving it back to `SUBMITTED` with `round_index` raised by 1 and
    `supplement_deadline_at` cleared.

    Design: Difficulty/non_linear_state_machine/appeal_supplement_cycle_returns_to_submitted_with_round_index_two
    """
    chain, appeal = _appeal_awaiting_supplement(api)

    requested = validate_success(
        api.request_appeal_supplement(appeal["id"], BOARD_MEMBER_HEADERS), 200
    )
    assert requested["status"] == APPEAL_STATUS_SUPPLEMENT_REQUESTED
    assert_instant_equals(requested["supplement_deadline_at"], "2026-08-21T00:00:00Z", "requested.supplement_deadline_at")

    resubmitted = validate_success(
        api.resubmit_appeal(
            appeal["id"],
            factories.appeal_resubmit_payload(
                "Attaching the platform CCTV timestamp that shows no badge was displayed."
            ),
            make_rider_headers(chain["rider"]["id"]),
        ),
        200,
    )
    assert resubmitted["status"] == APPEAL_STATUS_SUBMITTED
    assert resubmitted["round_index"] == 2
    assert not resubmitted["supplement_deadline_at"]


def test_re_entering_the_cycle_from_the_wrong_node_is_refused(api):
    """
    A resubmission against an appeal whose `status` is not
    `SUPPLEMENT_REQUESTED` is refused with `ERR_APPEAL_STATUS_INVALID`, so a
    second resubmission straight after the first leaves the appeal on round 2 and
    the citation still upheld.

    Design: Difficulty/non_linear_state_machine/appeal_supplement_cycle_returns_to_submitted_with_round_index_two
    """
    chain, appeal = _appeal_awaiting_supplement(api)
    fixtures.request_supplement(api, appeal["id"])
    fixtures.get_success_data(
        api.resubmit_appeal(
            appeal["id"],
            factories.appeal_resubmit_payload("First resubmission with the requested material."),
            make_rider_headers(chain["rider"]["id"]),
        )
    )

    response = api.resubmit_appeal(
        appeal["id"],
        factories.appeal_resubmit_payload(
            "Second attempt to resubmit while the appeal is already SUBMITTED."
        ),
        make_rider_headers(chain["rider"]["id"]),
    )
    validate_error(response, ERR_APPEAL_STATUS_INVALID, 409)

    unchanged = fixtures.read_appeal(api, appeal["id"])
    assert unchanged["status"] == APPEAL_STATUS_SUBMITTED
    assert unchanged["round_index"] == 2
    assert (
        fixtures.read_citation(api, chain["citation"]["id"])["adjudication_status"]
        == ADJUDICATION_UPHELD
    )


# ── A zone returns to designation the long way round ─────────────────

def _designated_zone_at_two_oclock(api):
    """A zone designated with a full signage count, with the clock a day later."""
    fixtures.move_clock(api, "2026-08-01T02:00:00Z")
    zone = fixtures.register_zone(api)
    line = fixtures.register_line(api)
    fixtures.assign_line(api, zone["id"], line["id"])
    fixtures.sign_and_designate_zone(api, zone["id"])
    fixtures.move_clock(api, "2026-08-02T00:00:00Z")
    return zone


def test_suspension_then_resubmission_clears_the_suspension_reason(api):
    """
    A deliberate suspension sets `suspension_reason` to `ADMINISTRATIVE_HOLD`,
    and moving the suspended zone back into `PENDING_SIGNAGE` is not a no-op: the
    reason it was suspended for is cleared on the way through.

    Design: Difficulty/non_linear_state_machine/fare_zone_returns_from_suspended_to_designated_through_pending_signage
    """
    zone = _designated_zone_at_two_oclock(api)

    suspended = validate_success(api.suspend_zone(zone["id"], PLANNER_HEADERS), 200)
    assert suspended["designation_status"] == ZONE_STATUS_SUSPENDED
    assert suspended["suspension_reason"] == SUSPENSION_REASON_ADMINISTRATIVE_HOLD

    resubmitted = validate_success(
        api.submit_zone_for_signage(zone["id"], PLANNER_HEADERS), 200
    )
    assert resubmitted["designation_status"] == ZONE_STATUS_PENDING_SIGNAGE
    assert not resubmitted["suspension_reason"]


def test_redesignation_restamps_the_designation_instant(api):
    """
    Designating the zone again stamps `designated_at` from the logical clock at
    that later designation, and the recomputed compliance figure is read from the
    newest authoritative audit.

    Design: Difficulty/non_linear_state_machine/fare_zone_returns_from_suspended_to_designated_through_pending_signage
    """
    zone = _designated_zone_at_two_oclock(api)
    fixtures.get_success_data(api.suspend_zone(zone["id"], PLANNER_HEADERS))
    fixtures.get_success_data(api.submit_zone_for_signage(zone["id"], PLANNER_HEADERS))
    fixtures.file_audit(
        api,
        zone["id"],
        signs_verified_count=10,
        audited_at="2026-08-03T00:00:00Z",
        deficiency_note="Re-verification after administrative hold; all 10 signs present.",
    )
    fixtures.move_clock(api, "2026-08-04T00:00:00Z")

    redesignated = validate_success(api.designate_zone(zone["id"], PLANNER_HEADERS), 200)

    assert redesignated["designation_status"] == ZONE_STATUS_DESIGNATED
    assert_instant_equals(redesignated["designated_at"], "2026-08-04T00:00:00Z", "redesignated.designated_at")
    assert redesignated["verified_sign_count"] == 10
    assert_rate_equals(redesignated["signage_compliance_pct"], 1.0000, "signage_compliance_pct")
    assert not redesignated["suspension_reason"]

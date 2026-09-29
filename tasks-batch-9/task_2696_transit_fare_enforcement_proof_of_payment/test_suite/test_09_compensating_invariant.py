"""
Quantities that must be conserved across a compensating action: the money
identity on a citation, and the partition of a deployment's encounters.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures
from test_helpers.assertions import (
    assert_instant_equals,
    assert_citation_money_identity,
    assert_rate_equals,
    ledger_sources,
    sole_row_with_source,
)
from test_helpers.constants import (
    ADJUDICATION_DISMISSED,
    DECISION_DISMISS,
    DEPLOYMENT_STATUS_VOIDED,
    DISMISSAL_REASON_FIRST_OFFENSE_DIVERSION,
    IDENTITY_SELF_REPORTED,
    MEDIA_SMARTCARD,
    OUTCOME_COMPLIANT,
    OUTCOME_VOIDED,
    PAYMENT_SOURCE_DIRECT,
    PAYMENT_SOURCE_DISMISSAL_REVERSAL,
    PAYMENT_SOURCE_SERVICE_CREDIT,
    SERVICE_STATUS_ACTIVE,
    SERVICE_STATUS_CANCELLED,
    SETTLEMENT_WRITTEN_OFF,
    VOID_REASON_PLANNER_CANCELLED,
)
from test_helpers.test_users import (
    HEARING_OFFICER_HEADERS,
    PLANNER_HEADERS,
    make_rider_headers,
)

DISMISSED_AT = "2026-08-06T00:00:00Z"


# ── Money conserved across a dismissal reversal ──────────────────────

def _citation_part_paid_and_part_worked_off(api):
    """
    A 9720 citation against which the rider paid 2000 in cash and then worked off
    two hours of community service, leaving 4720 outstanding.
    """
    chain = fixtures.build_citation_chain(api)
    citation_id = chain["citation"]["id"]
    rider_id = chain["rider"]["id"]
    rider_headers = make_rider_headers(rider_id)

    fixtures.pay_direct(api, citation_id, 2000, rider_id)
    part_paid = fixtures.read_citation(api, citation_id)
    assignment = fixtures.get_success_data(
        api.create_service_assignment(
            factories.service_assignment_payload(
                citation_id=citation_id,
                partner_org_name="Riverside Community Kitchen",
                expected_citation_version=part_paid["version"],
            ),
            rider_headers,
        )
    )
    fixtures.get_success_data(
        api.log_service_hours(
            assignment["id"], factories.log_hours_payload(2), PLANNER_HEADERS
        )
    )
    fixtures.move_clock(api, DISMISSED_AT)
    chain["assignment"] = assignment
    return chain


def test_the_identity_holds_before_the_compensating_action(api):
    """
    `outstanding_balance_cents` is `total_due_cents` less `amount_paid_cents` less
    `service_credit_cents`, so a citation carrying 2000 in cash and 3000 of
    service credit stands at 4720 with its assignment still `ACTIVE`.

    Design: Difficulty/compensating_invariant/citation_money_identity_survives_direct_payment_service_credit_and_dismissal_reversal
    """
    chain = _citation_part_paid_and_part_worked_off(api)

    citation = fixtures.read_citation(api, chain["citation"]["id"])
    assert citation["total_due_cents"] == 9720
    assert citation["amount_paid_cents"] == 2000
    assert citation["service_credit_cents"] == 3000
    assert citation["outstanding_balance_cents"] == 4720
    assert_citation_money_identity(citation)

    assignment = fixtures.read_service_assignment(api, chain["assignment"]["id"])
    assert assignment["required_hours"] == 6
    assert assignment["hours_completed"] == 2
    assert assignment["credited_cents"] == 3000
    assert assignment["status"] == SERVICE_STATUS_ACTIVE


def _dismiss_at_hearing(api, chain):
    hearing = fixtures.contest(api, chain["citation"]["id"], chain["rider"]["id"])
    return validate_success(
        api.decide_hearing(
            hearing["id"],
            factories.hearing_decision_payload(
                DECISION_DISMISS,
                dismissal_reason_code=DISMISSAL_REASON_FIRST_OFFENSE_DIVERSION,
            ),
            HEARING_OFFICER_HEADERS,
        ),
        200,
    )


def test_the_reversal_nets_the_cash_but_leaves_the_service_credit_standing(api):
    """
    Service credit already earned is not reversed — only cash is — so after the
    dismissal `amount_paid_cents` is 0 while `service_credit_cents` still reads
    3000 and the citation is `WRITTEN_OFF` owing nothing.

    Design: Difficulty/compensating_invariant/citation_money_identity_survives_direct_payment_service_credit_and_dismissal_reversal
    """
    chain = _citation_part_paid_and_part_worked_off(api)
    _dismiss_at_hearing(api, chain)

    citation = fixtures.read_citation(api, chain["citation"]["id"])
    assert citation["adjudication_status"] == ADJUDICATION_DISMISSED
    assert citation["dismissal_reason_code"] == DISMISSAL_REASON_FIRST_OFFENSE_DIVERSION
    assert_instant_equals(citation["dismissed_at"], DISMISSED_AT, "citation.dismissed_at")
    assert citation["settlement_status"] == SETTLEMENT_WRITTEN_OFF
    assert citation["outstanding_balance_cents"] == 0
    assert citation["amount_paid_cents"] == 0
    assert citation["service_credit_cents"] == 3000
    assert citation["total_due_cents"] == 9720
    assert citation["assessed_penalty_cents"] == 9000


def test_the_compensation_appends_a_row_rather_than_editing_the_old_one(api):
    """
    No row is ever amended or deleted, so the original `DIRECT` row still carries
    its 2000 beside the `SERVICE_CREDIT` row that recorded the hours and the
    `DISMISSAL_REVERSAL` row that cancelled the cash.

    Design: Difficulty/compensating_invariant/citation_money_identity_survives_direct_payment_service_credit_and_dismissal_reversal
    """
    chain = _citation_part_paid_and_part_worked_off(api)
    citation_id = chain["citation"]["id"]
    original_direct = sole_row_with_source(
        fixtures.citation_ledger(api, citation_id), PAYMENT_SOURCE_DIRECT
    )
    _dismiss_at_hearing(api, chain)

    rows = fixtures.citation_ledger(api, citation_id)
    assert len(rows) == 3, f"expected three ledger rows, got {ledger_sources(rows)}"

    direct = sole_row_with_source(rows, PAYMENT_SOURCE_DIRECT)
    assert direct["id"] == original_direct["id"]
    assert direct["amount_cents"] == 2000

    credit = sole_row_with_source(rows, PAYMENT_SOURCE_SERVICE_CREDIT)
    assert credit["amount_cents"] == 3000
    assert credit["hours_credited"] == 2

    reversal = sole_row_with_source(rows, PAYMENT_SOURCE_DISMISSAL_REVERSAL)
    assert reversal["amount_cents"] == 2000
    assert not reversal["plan_id"]


def test_the_cancelled_assignment_keeps_the_hours_it_recorded(api):
    """
    The dismissal cascade moves the `ACTIVE` community-service assignment to
    `CANCELLED` without erasing what was worked, and both party counters fall as
    the citation leaves the live set.

    Design: Difficulty/compensating_invariant/citation_money_identity_survives_direct_payment_service_credit_and_dismissal_reversal
    """
    chain = _citation_part_paid_and_part_worked_off(api)
    _dismiss_at_hearing(api, chain)

    assignment = fixtures.read_service_assignment(api, chain["assignment"]["id"])
    assert assignment["status"] == SERVICE_STATUS_CANCELLED
    assert assignment["hours_completed"] == 2
    assert assignment["credited_cents"] == 3000

    assert fixtures.read_rider(api, chain["rider"]["id"])["prior_citation_count"] == 0
    assert (
        fixtures.read_inspector(api, chain["inspector"]["id"])["citations_issued_count"] == 0
    )


# ── A sample count conserved across a void ───────────────────────────

def _deployment_with_three_resolved_and_two_pending(api):
    """
    Five encounters on one deployment against a target of five: three resolved
    compliant, two still pending.
    """
    env = fixtures.build_environment(api)
    second_rider = fixtures.register_rider(
        api,
        rider_ref="R-200",
        display_name="Rider Two",
        demographic_band="BAND_B",
        residence_geo_tract="T-002",
    )
    deployment = fixtures.build_active_deployment(
        api, env, observe_at="2026-08-05T10:00:00Z"
    )
    inspector_id = env["inspector"]["id"]

    compliant = []
    for index, (occurred_at, validated_at, rider) in enumerate(
        (
            ("2026-08-05T07:00:00Z", "2026-08-05T06:55:00Z", None),
            ("2026-08-05T07:15:00Z", "2026-08-05T07:10:00Z", second_rider),
            ("2026-08-05T07:30:00Z", "2026-08-05T07:25:00Z", None),
        ),
        start=1,
    ):
        encounter = fixtures.build_pending_encounter(
            api,
            env,
            deployment,
            occurred_at=occurred_at,
            fare_media_type=MEDIA_SMARTCARD,
            rider=rider,
            media_reference=f"SC-100{index}",
            media_validated_at=validated_at,
            media_expires_at="2026-12-01T00:00:00Z",
            media_zone_code="ZN1",
            identity_capture_method=IDENTITY_SELF_REPORTED,
        )
        fixtures.resolve(api, encounter["id"], inspector_id, "COMPLIANT")
        compliant.append(encounter)

    pending = [
        fixtures.build_pending_encounter(
            api, env, deployment, occurred_at="2026-08-05T08:00:00Z"
        ),
        fixtures.build_pending_encounter(
            api, env, deployment, occurred_at="2026-08-05T08:30:00Z", rider=second_rider
        ),
    ]
    return env, deployment, compliant, pending


def test_all_five_encounters_are_in_the_achieved_sample_before_the_void(api):
    """
    `achieved_sample_count` counts the deployment's encounters whose `outcome` is
    not `VOIDED` and `voided_encounter_count` counts those that are, so with
    nothing voided the deployment stands at five of five.

    Design: Difficulty/compensating_invariant/deployment_encounter_count_conservation_across_void
    """
    _env, deployment, _compliant, _pending = _deployment_with_three_resolved_and_two_pending(api)

    before = fixtures.read_deployment(api, deployment["id"])
    assert before["achieved_sample_count"] == 5
    assert before["voided_encounter_count"] == 0
    assert_rate_equals(before["sample_adequacy_ratio"], 1.0000, "sample_adequacy_ratio")


def test_the_void_repartitions_the_five_encounters_without_losing_any(api):
    """
    Voiding the deployment sweeps only the encounters whose `outcome` is still
    `PENDING`, so the two counters move from five and nothing to three and two
    while their sum is unchanged and the ratio falls to exactly 0.6000.

    Design: Difficulty/compensating_invariant/deployment_encounter_count_conservation_across_void
    """
    _env, deployment, _compliant, _pending = _deployment_with_three_resolved_and_two_pending(api)

    voided = validate_success(api.void_deployment(deployment["id"], PLANNER_HEADERS), 200)
    assert voided["status"] == DEPLOYMENT_STATUS_VOIDED
    assert voided["void_reason"] == VOID_REASON_PLANNER_CANCELLED

    after = fixtures.read_deployment(api, deployment["id"])
    assert after["achieved_sample_count"] == 3
    assert after["voided_encounter_count"] == 2
    assert after["achieved_sample_count"] + after["voided_encounter_count"] == 5
    assert_rate_equals(after["sample_adequacy_ratio"], 0.6000, "sample_adequacy_ratio")


def test_the_void_touches_the_pending_rows_only_and_computes_no_close_metrics(api):
    """
    The three terminal rows keep their `COMPLIANT` outcome while the two pending
    rows become `VOIDED`, and the two figures that only closing computes stay
    empty.

    Design: Difficulty/compensating_invariant/deployment_encounter_count_conservation_across_void
    """
    _env, deployment, compliant, pending = _deployment_with_three_resolved_and_two_pending(api)
    fixtures.get_success_data(api.void_deployment(deployment["id"], PLANNER_HEADERS))

    for encounter in compliant:
        assert (
            fixtures.read_encounter(api, encounter["id"])["outcome"] == OUTCOME_COMPLIANT
        )
    for encounter in pending:
        assert fixtures.read_encounter(api, encounter["id"])["outcome"] == OUTCOME_VOIDED

    after = fixtures.read_deployment(api, deployment["id"])
    assert after["measured_evasion_rate_bps"] is None
    assert after["enforcement_cost_cents"] is None

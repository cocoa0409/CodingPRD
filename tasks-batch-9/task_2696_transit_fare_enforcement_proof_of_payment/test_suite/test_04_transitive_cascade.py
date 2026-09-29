"""
Cascades that travel several causal links from one request: an appeal grant
that reaches the payment ledger, and an ordinary audit row that reaches a
pending encounter.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures
from test_helpers.assertions import (
    assert_instant_equals,
    assert_ledger_row,
    assert_rate_equals,
    ledger_sources,
    sole_row_with_source,
)
from test_helpers.constants import (
    ADJUDICATION_DISMISSED,
    APPEAL_DECISION_GRANTED,
    APPEAL_STATUS_GRANTED,
    BAND_B,
    DEPLOYMENT_STATUS_VOIDED,
    DISMISSAL_REASON_SIGNAGE_DEFICIENT,
    GROUNDS_SIGNAGE_DEFICIENCY,
    OUTCOME_COMPLIANT,
    OUTCOME_VOIDED,
    PAYMENT_SOURCE_DISMISSAL_REVERSAL,
    PAYMENT_SOURCE_DOWN_PAYMENT,
    PLAN_STATUS_CANCELLED,
    SETTLEMENT_WRITTEN_OFF,
    SUSPENSION_REASON_SIGNAGE_DEFICIENCY,
    VOID_REASON_ZONE_SUSPENDED,
    ZONE_STATUS_SUSPENDED,
)
from test_helpers.test_users import (
    BOARD_MEMBER_HEADERS,
    BOARD_MEMBER_USER_ID,
    make_rider_headers,
)


# ── Appeal grant, four links deep ────────────────────────────────────

DISMISSAL_AT = "2026-08-07T00:00:00Z"


def _appealed_citation_with_money_on_it(api):
    """
    A second-offence citation of 20160 carrying a live 3-installment plan and a
    2500 down payment, upheld at hearing and under appeal.
    """
    env = fixtures.build_environment(api)
    deployment = fixtures.build_active_deployment(api, env)
    inspector_id = env["inspector"]["id"]
    rider_id = env["rider"]["id"]

    warned = fixtures.build_pending_encounter(
        api, env, deployment, occurred_at="2026-08-05T07:00:00Z"
    )
    fixtures.resolve(api, warned["id"], inspector_id, "WARNING_ISSUED")
    cited = fixtures.build_pending_encounter(
        api, env, deployment, occurred_at="2026-08-05T08:00:00Z"
    )
    citation = fixtures.issue_citation(api, cited["id"], inspector_id)
    assert citation["total_due_cents"] == 20160

    plan = fixtures.get_success_data(
        api.create_payment_plan(
            factories.payment_plan_payload(
                citation_id=citation["id"],
                installment_count=3,
                down_payment_cents=2500,
                expected_citation_version=citation["version"],
            ),
            make_rider_headers(rider_id),
        )
    )

    fixtures.move_clock(api, "2026-08-06T00:00:00Z")
    hearing = fixtures.contest(api, citation["id"], rider_id)
    fixtures.decide_hearing(api, hearing["id"], "UPHOLD")
    fixtures.move_clock(api, DISMISSAL_AT)
    appeal = fixtures.file_appeal(
        api,
        citation["id"],
        hearing["id"],
        rider_id,
        GROUNDS_SIGNAGE_DEFICIENCY,
        statement=(
            "The platform I boarded from carried no proof-of-payment signage on "
            "the date of inspection."
        ),
    )
    return {
        "env": env,
        "citation": citation,
        "hearing": hearing,
        "plan": plan,
        "appeal": appeal,
    }


def test_a_grant_carries_the_dismissal_reason_down_onto_the_citation(api):
    """
    A grant runs in four ordered links: the appeal's own `status` becomes
    `GRANTED`, and caused by that the citation moves to `DISMISSED` with
    `dismissal_reason_code` taken from the appeal's own `dismissal_reason_code`
    and `dismissed_at` stamped from the logical clock.

    Design: Difficulty/transitive_cascade/appeal_grant_cascades_four_links_to_dismissal_reversal_ledger_row
    """
    world = _appealed_citation_with_money_on_it(api)

    granted = validate_success(
        api.decide_appeal(
            world["appeal"]["id"],
            factories.appeal_decision_payload(
                APPEAL_DECISION_GRANTED,
                dismissal_reason_code=DISMISSAL_REASON_SIGNAGE_DEFICIENT,
            ),
            BOARD_MEMBER_HEADERS,
        ),
        200,
    )
    assert granted["status"] == APPEAL_STATUS_GRANTED
    assert granted["decided_by_user_id"] == BOARD_MEMBER_USER_ID
    assert_instant_equals(granted["decided_at"], DISMISSAL_AT, "granted.decided_at")

    dismissed = fixtures.read_citation(api, world["citation"]["id"])
    assert dismissed["adjudication_status"] == ADJUDICATION_DISMISSED
    assert dismissed["dismissal_reason_code"] == DISMISSAL_REASON_SIGNAGE_DEFICIENT
    assert_instant_equals(dismissed["dismissed_at"], DISMISSAL_AT, "dismissed.dismissed_at")


def test_the_write_off_reaches_the_live_payment_plan(api):
    """
    Caused by the dismissal, `settlement_status` becomes `WRITTEN_OFF` with
    `outstanding_balance_cents` set to 0 and every `ACTIVE` payment plan on the
    citation becomes `CANCELLED`, while the billed figures survive as the
    historical record.

    Design: Difficulty/transitive_cascade/appeal_grant_cascades_four_links_to_dismissal_reversal_ledger_row
    """
    world = _appealed_citation_with_money_on_it(api)
    fixtures.get_success_data(
        api.decide_appeal(
            world["appeal"]["id"],
            factories.appeal_decision_payload(
                APPEAL_DECISION_GRANTED,
                dismissal_reason_code=DISMISSAL_REASON_SIGNAGE_DEFICIENT,
            ),
            BOARD_MEMBER_HEADERS,
        )
    )

    citation = fixtures.read_citation(api, world["citation"]["id"])
    assert citation["settlement_status"] == SETTLEMENT_WRITTEN_OFF
    assert citation["outstanding_balance_cents"] == 0
    assert citation["assessed_penalty_cents"] == 18000
    assert citation["total_due_cents"] == 20160

    assert fixtures.read_plan(api, world["plan"]["id"])["status"] == PLAN_STATUS_CANCELLED


def test_the_reversal_row_returns_the_cash_already_collected(api):
    """
    Caused by the write-off, and only where `amount_paid_cents` immediately
    before the cascade was greater than zero, a ledger row is appended with
    `source` `DISMISSAL_REVERSAL`, `amount_cents` equal to that pre-cascade paid
    figure, an empty `plan_id` and `applied_at` set to the logical clock,
    driving `amount_paid_cents` to 0.

    Design: Difficulty/transitive_cascade/appeal_grant_cascades_four_links_to_dismissal_reversal_ledger_row
    """
    world = _appealed_citation_with_money_on_it(api)
    citation_id = world["citation"]["id"]
    assert fixtures.read_citation(api, citation_id)["amount_paid_cents"] == 2500

    fixtures.get_success_data(
        api.decide_appeal(
            world["appeal"]["id"],
            factories.appeal_decision_payload(
                APPEAL_DECISION_GRANTED,
                dismissal_reason_code=DISMISSAL_REASON_SIGNAGE_DEFICIENT,
            ),
            BOARD_MEMBER_HEADERS,
        )
    )

    rows = fixtures.citation_ledger(api, citation_id)
    assert len(rows) == 2, f"expected two ledger rows, got {ledger_sources(rows)}"
    assert_ledger_row(
        sole_row_with_source(rows, PAYMENT_SOURCE_DOWN_PAYMENT),
        PAYMENT_SOURCE_DOWN_PAYMENT,
        2500,
        plan_id=world["plan"]["id"],
        label="down payment row",
    )
    assert_ledger_row(
        sole_row_with_source(rows, PAYMENT_SOURCE_DISMISSAL_REVERSAL),
        PAYMENT_SOURCE_DISMISSAL_REVERSAL,
        2500,
        plan_id=None,
        applied_at=DISMISSAL_AT,
        label="reversal row",
    )

    assert fixtures.read_citation(api, citation_id)["amount_paid_cents"] == 0


def test_both_party_counters_fall_but_the_warning_counter_does_not(api):
    """
    The rider's `prior_citation_count` and the issuing inspector's
    `citations_issued_count` are then recomputed downward, and nothing in the
    cascade touches the warning the rider collected before the citation.

    Design: Difficulty/transitive_cascade/appeal_grant_cascades_four_links_to_dismissal_reversal_ledger_row
    """
    world = _appealed_citation_with_money_on_it(api)
    fixtures.get_success_data(
        api.decide_appeal(
            world["appeal"]["id"],
            factories.appeal_decision_payload(
                APPEAL_DECISION_GRANTED,
                dismissal_reason_code=DISMISSAL_REASON_SIGNAGE_DEFICIENT,
            ),
            BOARD_MEMBER_HEADERS,
        )
    )

    rider = fixtures.read_rider(api, world["env"]["rider"]["id"])
    assert rider["prior_citation_count"] == 0
    assert rider["prior_warning_count"] == 1
    assert (
        fixtures.read_inspector(api, world["env"]["inspector"]["id"])[
            "citations_issued_count"
        ]
        == 0
    )


# ── An audit row that voids a pending encounter ──────────────────────

def _deployment_with_one_resolved_and_one_pending_encounter(api):
    """
    An active deployment carrying a COMPLIANT smartcard encounter and a second,
    still-pending encounter against a different rider.
    """
    env = fixtures.build_environment(api)
    second_rider = fixtures.register_rider(
        api,
        rider_ref="R-200",
        display_name="Rider Two",
        demographic_band=BAND_B,
        residence_geo_tract="T-002",
    )
    deployment = fixtures.build_active_deployment(
        api, env, observe_at="2026-08-05T10:00:00Z"
    )
    inspector_id = env["inspector"]["id"]

    compliant = fixtures.build_pending_encounter(
        api,
        env,
        deployment,
        occurred_at="2026-08-05T07:00:00Z",
        fare_media_type="SMARTCARD",
        media_reference="SC-0001",
        media_validated_at="2026-08-05T06:55:00Z",
        media_expires_at="2026-12-01T00:00:00Z",
        media_zone_code="ZN1",
        identity_capture_method="SELF_REPORTED",
    )
    fixtures.resolve(api, compliant["id"], inspector_id, "COMPLIANT")
    pending = fixtures.build_pending_encounter(
        api,
        env,
        deployment,
        occurred_at="2026-08-05T08:00:00Z",
        rider=second_rider,
    )
    return {
        "env": env,
        "deployment": deployment,
        "compliant": compliant,
        "pending": pending,
    }


def _file_deficient_audit(api, zone_id):
    return fixtures.file_audit(
        api,
        zone_id,
        signs_verified_count=8,
        audited_at="2026-08-05T09:30:00Z",
        deficiency_note="Two platform signs removed during shelter replacement.",
    )


def test_a_deficient_audit_row_suspends_the_zone_it_reports_on(api):
    """
    Filing an audit recomputes the zone's `verified_sign_count` and
    `signage_compliance_pct` from the newest audit, and where that figure is
    below 0.9000 on a `DESIGNATED` zone the zone moves to `SUSPENDED` with
    `suspension_reason` `SIGNAGE_DEFICIENCY`.

    Design: Difficulty/transitive_cascade/signage_audit_deficiency_cascades_three_links_to_pending_encounter_void
    """
    world = _deployment_with_one_resolved_and_one_pending_encounter(api)
    zone_id = world["env"]["zone"]["id"]

    audit = _file_deficient_audit(api, zone_id)
    assert audit["signs_verified_count"] == 8

    zone = fixtures.read_zone(api, zone_id)
    assert zone["verified_sign_count"] == 8
    assert_rate_equals(zone["signage_compliance_pct"], 0.8000, "signage_compliance_pct")
    assert zone["designation_status"] == ZONE_STATUS_SUSPENDED
    assert zone["suspension_reason"] == SUSPENSION_REASON_SIGNAGE_DEFICIENCY


def test_the_suspension_voids_the_deployment_and_only_its_pending_encounter(api):
    """
    The suspension moves the zone's `PLANNED` and `ACTIVE` deployments to
    `VOIDED` with `void_reason` `ZONE_SUSPENDED` and voids every encounter on
    them whose `outcome` is still `PENDING`, leaving already-resolved encounters
    exactly as they stand.

    Design: Difficulty/transitive_cascade/signage_audit_deficiency_cascades_three_links_to_pending_encounter_void
    """
    world = _deployment_with_one_resolved_and_one_pending_encounter(api)
    _file_deficient_audit(api, world["env"]["zone"]["id"])

    deployment = fixtures.read_deployment(api, world["deployment"]["id"])
    assert deployment["status"] == DEPLOYMENT_STATUS_VOIDED
    assert deployment["void_reason"] == VOID_REASON_ZONE_SUSPENDED

    assert (
        fixtures.read_encounter(api, world["pending"]["id"])["outcome"] == OUTCOME_VOIDED
    )
    assert (
        fixtures.read_encounter(api, world["compliant"]["id"])["outcome"]
        == OUTCOME_COMPLIANT
    )


def test_the_voided_encounter_is_recounted_out_of_the_achieved_sample(api):
    """
    `achieved_sample_count` counts the deployment's encounters whose `outcome` is
    not `VOIDED` and `voided_encounter_count` counts those that are, so
    `sample_adequacy_ratio` falls to 0.2000; the two closing figures stay empty
    because only closing computes them.

    Design: Difficulty/transitive_cascade/signage_audit_deficiency_cascades_three_links_to_pending_encounter_void
    """
    world = _deployment_with_one_resolved_and_one_pending_encounter(api)
    _file_deficient_audit(api, world["env"]["zone"]["id"])

    deployment = fixtures.read_deployment(api, world["deployment"]["id"])
    assert deployment["achieved_sample_count"] == 1
    assert deployment["voided_encounter_count"] == 1
    assert_rate_equals(deployment["sample_adequacy_ratio"], 0.2000, "sample_adequacy_ratio")
    assert deployment["measured_evasion_rate_bps"] is None
    assert deployment["enforcement_cost_cents"] is None

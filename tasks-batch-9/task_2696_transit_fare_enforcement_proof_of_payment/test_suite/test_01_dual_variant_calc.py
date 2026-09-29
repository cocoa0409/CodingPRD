"""
Paired-variant calculations: the two figures a single formula family produces
from the same inputs must be computed independently and must diverge.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures
from test_helpers.assertions import (
    assert_instant_equals,
    assert_citation_money_identity,
    assert_rate_equals,
)
from test_helpers.constants import (
    ADJUDICATION_ISSUED,
    BASIS_ACCRUAL,
    BASIS_CASH,
    DEPLOYMENT_STATUS_CLOSED,
    IDENTITY_GOVT_ID,
    IDENTITY_REFUSED,
    MEDIA_NONE,
    MEDIA_SMARTCARD,
    OUTCOME_CITATION_ISSUED,
    OUTCOME_UNRESOLVED_IDENTITY,
    SETTLEMENT_OUTSTANDING,
    VALIDATION_NO_PROOF,
)
from test_helpers.test_users import ANALYST_HEADERS, PLANNER_HEADERS


# ── offense_sequence versus citation_only_sequence ───────────────────

def _rider_with_one_prior_warning(api):
    """A rider carrying exactly one prior warning and one fresh pending encounter."""
    env = fixtures.build_environment(api)
    deployment = fixtures.build_active_deployment(api, env)
    first = fixtures.build_pending_encounter(
        api, env, deployment, occurred_at="2026-08-05T07:00:00Z"
    )
    fixtures.resolve(api, first["id"], env["inspector"]["id"], "WARNING_ISSUED")
    second = fixtures.build_pending_encounter(
        api, env, deployment, occurred_at="2026-08-05T08:00:00Z"
    )
    return env, deployment, first, second


def test_offense_sequence_counts_the_prior_warning_and_the_floor_does_not(api):
    """
    `offense_sequence`, the warning-inclusive variant, is 1 plus the prior-warning
    count plus the prior-citation count; `citation_only_sequence`, the
    citation-only variant, is 1 plus the prior-citation count alone.  A rider
    whose only prior contact was a warning therefore reaches rung 2 on the
    assessed penalty and stays on rung 1 for the reduction floor.

    Design: Difficulty/dual_variant_calc/offense_sequence_variants_diverge_on_prior_warning
    """
    env, _deployment, _first, second = _rider_with_one_prior_warning(api)

    response = api.create_citation(
        factories.citation_payload(second["id"]),
        fixtures.make_fare_inspector_headers(env["inspector"]["id"]),
    )
    citation = validate_success(response, 201)

    assert citation["offense_sequence"] == 2
    assert citation["citation_only_sequence"] == 1
    assert citation["assessed_penalty_cents"] == 18000
    assert citation["reduction_floor_cents"] == 9000
    assert citation["reduction_floor_cents"] != citation["assessed_penalty_cents"]


def test_the_two_rungs_produce_two_different_money_figures(api):
    """
    Fed the `offense_sequence` the four-step assessment yields
    `assessed_penalty_cents`, and fed the `citation_only_sequence` it yields
    `reduction_floor_cents`, so an assessed penalty of 18000 carries the
    1200-basis-point fee band and a total of 20160 while the floor sits at 9000.

    Design: Difficulty/dual_variant_calc/offense_sequence_variants_diverge_on_prior_warning
    """
    env, _deployment, _first, second = _rider_with_one_prior_warning(api)

    citation = fixtures.issue_citation(api, second["id"], env["inspector"]["id"])

    assert citation["assessed_penalty_cents"] == 18000
    assert citation["admin_fee_cents"] == 2160
    assert citation["total_due_cents"] == 20160
    assert citation["outstanding_balance_cents"] == 20160
    assert citation["reduction_floor_cents"] == 9000
    assert_instant_equals(citation["contest_deadline_at"], "2026-09-04T09:00:00Z", "citation.contest_deadline_at")
    assert_citation_money_identity(citation)


def test_issuance_moves_the_encounter_and_both_party_counters(api):
    """
    Issuance also flips the source encounter's `outcome` to `CITATION_ISSUED`
    and recomputes the rider's `prior_citation_count` and the inspector's
    `citations_issued_count`, while the warning already recorded against that
    rider leaves `prior_warning_count` at 1.

    Design: Difficulty/dual_variant_calc/offense_sequence_variants_diverge_on_prior_warning
    """
    env, _deployment, _first, second = _rider_with_one_prior_warning(api)

    fixtures.issue_citation(api, second["id"], env["inspector"]["id"])

    assert fixtures.read_encounter(api, second["id"])["outcome"] == OUTCOME_CITATION_ISSUED
    rider = fixtures.read_rider(api, env["rider"]["id"])
    assert rider["prior_warning_count"] == 1
    assert rider["prior_citation_count"] == 1
    assert fixtures.read_inspector(api, env["inspector"]["id"])["citations_issued_count"] == 1


# ── measured versus resolved evasion rate ────────────────────────────

def _five_resolved_encounters(api):
    """
    Five resolved encounters on one deployment: two compliant, two warned and
    one whose rider refused to identify themselves.
    """
    env = fixtures.build_environment(api)
    rider_two = fixtures.register_rider(
        api,
        rider_ref="R-200",
        display_name="Rider Two",
        demographic_band="BAND_B",
        residence_geo_tract="T-002",
    )
    deployment = fixtures.build_active_deployment(
        api, env, observe_at="2026-08-05T13:00:00Z"
    )
    inspector_id = env["inspector"]["id"]

    valid_media = {
        "fare_media_type": MEDIA_SMARTCARD,
        "media_expires_at": "2026-08-05T23:00:00Z",
        "media_zone_code": "ZN1",
        "identity_capture_method": IDENTITY_GOVT_ID,
    }
    first = fixtures.build_pending_encounter(
        api, env, deployment,
        occurred_at="2026-08-05T07:00:00Z",
        media_reference="SC-001",
        media_validated_at="2026-08-05T06:55:00Z",
        **valid_media,
    )
    fixtures.resolve(api, first["id"], inspector_id, "COMPLIANT")
    second = fixtures.build_pending_encounter(
        api, env, deployment,
        rider=rider_two,
        occurred_at="2026-08-05T07:30:00Z",
        media_reference="SC-002",
        media_validated_at="2026-08-05T07:00:00Z",
        **valid_media,
    )
    fixtures.resolve(api, second["id"], inspector_id, "COMPLIANT")
    third = fixtures.build_pending_encounter(
        api, env, deployment, occurred_at="2026-08-05T08:00:00Z", fare_media_type=MEDIA_NONE
    )
    fixtures.resolve(api, third["id"], inspector_id, "WARNING_ISSUED")
    fourth = fixtures.build_pending_encounter(
        api, env, deployment,
        rider=rider_two,
        occurred_at="2026-08-05T08:30:00Z",
        fare_media_type=MEDIA_NONE,
    )
    fixtures.resolve(api, fourth["id"], inspector_id, "WARNING_ISSUED")
    refused = fixtures.build_pending_encounter(
        api, env, deployment,
        rider=None,
        occurred_at="2026-08-05T09:00:00Z",
        fare_media_type=MEDIA_NONE,
        identity_capture_method=IDENTITY_REFUSED,
    )
    fixtures.resolve(api, refused["id"], inspector_id, "UNRESOLVED_IDENTITY")
    return env, deployment, refused


def test_measured_and_resolved_evasion_rates_diverge_on_the_refused_encounter(api):
    """
    The published measured rate counts every non-voided encounter, while the
    resolved rate additionally excludes the encounters whose `outcome` is
    `UNRESOLVED_IDENTITY` from both the numerator and the denominator, so three
    non-compliant out of five reads 6000 basis points against two out of four
    reading 5000.

    Design: Difficulty/dual_variant_calc/evasion_rate_variants_diverge_on_identity_refusal
    """
    _env, deployment, _refused = _five_resolved_encounters(api)

    closed = validate_success(api.close_deployment(deployment["id"], PLANNER_HEADERS), 200)

    assert closed["status"] == DEPLOYMENT_STATUS_CLOSED
    assert closed["measured_evasion_rate_bps"] == 6000
    assert closed["resolved_evasion_rate_bps"] == 5000
    assert closed["measured_evasion_rate_bps"] != closed["resolved_evasion_rate_bps"]


def test_closing_freezes_the_sample_counters_and_the_enforcement_cost(api):
    """
    Closing freezes the sampling figures alongside the two rates: five encounters
    survive against a target of five, none were voided, and the enforcement cost
    of a 480-minute shift with three inspectors in a zone above the statutory
    multiplier is 136080 cents.

    Design: Difficulty/dual_variant_calc/evasion_rate_variants_diverge_on_identity_refusal
    """
    _env, deployment, refused = _five_resolved_encounters(api)

    fixtures.get_success_data(api.close_deployment(deployment["id"], PLANNER_HEADERS))
    closed = fixtures.read_deployment(api, deployment["id"])

    assert closed["achieved_sample_count"] == 5
    assert closed["voided_encounter_count"] == 0
    assert_rate_equals(closed["sample_adequacy_ratio"], 1.0000, "sample_adequacy_ratio")
    assert closed["enforcement_cost_cents"] == 136080

    refused_now = fixtures.read_encounter(api, refused["id"])
    assert refused_now["validation_result"] == VALIDATION_NO_PROOF
    assert refused_now["outcome"] == OUTCOME_UNRESOLVED_IDENTITY


# ── accrual versus cash revenue recovery ─────────────────────────────

def _one_citation_partly_banked(api):
    """One cited encounter, one compliant encounter, a closed shift and 5000 banked."""
    env = fixtures.build_environment(api)
    deployment = fixtures.build_active_deployment(
        api, env, target_sample_size=2, observe_at="2026-08-05T10:00:00Z"
    )
    inspector_id = env["inspector"]["id"]

    cited = fixtures.build_pending_encounter(
        api, env, deployment, occurred_at="2026-08-05T07:00:00Z"
    )
    citation = fixtures.issue_citation(api, cited["id"], inspector_id)
    compliant = fixtures.build_pending_encounter(
        api, env, deployment,
        occurred_at="2026-08-05T08:00:00Z",
        fare_media_type=MEDIA_SMARTCARD,
        media_reference="SC-001",
        media_validated_at="2026-08-05T07:50:00Z",
        media_expires_at="2026-08-05T23:00:00Z",
        media_zone_code="ZN1",
    )
    fixtures.resolve(api, compliant["id"], inspector_id, "COMPLIANT")
    fixtures.get_success_data(api.close_deployment(deployment["id"], PLANNER_HEADERS))
    fixtures.pay_direct(api, citation["id"], 5000, env["rider"]["id"])
    fixtures.move_clock(api, "2026-08-06T00:00:00Z")
    return env, deployment, citation


WINDOW = ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")


def test_accrual_basis_reports_what_was_billed(api):
    """
    Under the `ACCRUAL` basis the recovery leg gathers every citation whose
    `issued_at` falls inside the window and whose adjudication status is live and
    sums their `total_due_cents`, so the ledger is ignored entirely and the full
    9720 is recovered against a cost leg of 136080.

    Design: Difficulty/dual_variant_calc/revenue_recovery_accrual_and_cash_bases_diverge_on_same_window
    """
    _env, _deployment, _citation = _one_citation_partly_banked(api)

    report = validate_success(
        api.get_revenue_recovery_report(
            factories.revenue_report_params(*WINDOW, basis=BASIS_ACCRUAL), ANALYST_HEADERS
        ),
        200,
    )

    assert report["basis"] == BASIS_ACCRUAL
    assert report["citations_counted"] == 1
    assert report["deployments_counted"] == 1
    assert report["recovered_cents"] == 9720
    assert report["enforcement_cost_cents"] == 136080
    assert report["net_recovery_cents"] == -126360
    assert report["recovery_ratio_bps"] == 714


def test_cash_basis_reports_only_what_was_banked(api):
    """
    Under the `CASH` basis the recovery leg gathers every ledger row whose
    `applied_at` falls inside the window and sums the positive sources, so only
    the 5000 actually paid is recovered and the same window yields a different
    net position and a different ratio.

    Design: Difficulty/dual_variant_calc/revenue_recovery_accrual_and_cash_bases_diverge_on_same_window
    """
    _env, _deployment, citation = _one_citation_partly_banked(api)

    report = validate_success(
        api.get_revenue_recovery_report(
            factories.revenue_report_params(*WINDOW, basis=BASIS_CASH), ANALYST_HEADERS
        ),
        200,
    )

    assert report["basis"] == BASIS_CASH
    assert report["citations_counted"] == 1
    assert report["deployments_counted"] == 1
    assert report["recovered_cents"] == 5000
    assert report["enforcement_cost_cents"] == 136080
    assert report["net_recovery_cents"] == -131080
    assert report["recovery_ratio_bps"] == 367

    settled = fixtures.read_citation(api, citation["id"])
    assert settled["total_due_cents"] == 9720
    assert settled["amount_paid_cents"] == 5000
    assert settled["outstanding_balance_cents"] == 4720
    assert settled["adjudication_status"] == ADJUDICATION_ISSUED
    assert settled["settlement_status"] == SETTLEMENT_OUTSTANDING

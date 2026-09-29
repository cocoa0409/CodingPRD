"""Difficulty rule: dual_variant_calc.

The same stored evidence is evaluated twice under two different variants, and
the two evaluations must diverge — once in the scoring domain (provisional
versus final tightening) and once in the insurance domain (per-occurrence
basis versus depleted-aggregate basis).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prd_bench_local_runner.testing import (  # noqa: E402
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ERR_COVERAGE_LIMIT_INSUFFICIENT  # noqa: E402
from test_helpers.assertions import (  # noqa: E402
    assert_certificate_state,
    assert_contractor_posture,
    assert_effective_thresholds,
    assert_prequalification_state,
    assert_score_equals,
    assert_site_posture,
)
from test_helpers.constants import INITIAL_CLOCK  # noqa: E402


def _summit_under_review(build):
    """A tier-2 contractor carried to UNDER_REVIEW on the canonical statistic.

    Summit declares [GENERAL, HEIGHTS] so its base hazard tier is 2, and its
    certificates are sized for the 1.5 tier multiplier: GL 2000000/4000000 and
    WC 1000000/2000000.
    """
    build.set_clock(INITIAL_CLOCK)
    client = build.create_client()
    contractor = build.create_contractor(
        legal_name="Summit Steel Erectors",
        scope_of_work=["GENERAL_BUILDING"],
        hazard_profile=["GENERAL", "HEIGHTS"],
        employee_count=120,
    )
    build.verified_certificate(
        contractor["id"],
        "GL",
        each_occurrence_limit=2000000,
        aggregate_limit=4000000,
    )
    build.verified_certificate(
        contractor["id"],
        "WC",
        each_occurrence_limit=1000000,
        aggregate_limit=2000000,
    )
    prequalification = build.open_prequalification(contractor["id"], client["id"])
    build.verified_statistic(prequalification["id"], contractor["id"])
    build.accept_required_programs(
        prequalification["id"],
        contractor["id"],
        client["id"],
        contractor["hazard_profile"],
    )
    submitted = build.submit_prequalification(prequalification["id"], contractor["id"])
    return {
        "client_id": client["id"],
        "contractor_id": contractor["id"],
        "prequalification_id": prequalification["id"],
        "submitted": submitted,
    }


def test_scorecard_reports_provisional_and_final_variants_side_by_side(build, api):
    """The scorecard shows 80.51 untightened against 77.06 at tier 2.

    PRD Section 3.6: "Both scores are recomputed live from the currently
    governing statistic so the two variants can be compared side by side — the
    provisional figure against the published, untightened ceilings and the
    final figure against the tightened, variance-overlaid ones."

    Design: Difficulty/dual_variant_calc/provisional_and_final_composite_diverge_on_hazard_tier_tightening
    """
    scenario = _summit_under_review(build)

    # The submission itself wrote the provisional figure only.
    assert_prequalification_state(
        scenario["submitted"],
        provisional_composite_score=80.51,
        final_composite_score=None,
        grade=None,
    )
    assert scenario["submitted"]["effective_thresholds"] is None

    scorecard = validate_success(
        api.get_scorecard(
            scenario["prequalification_id"], build.manager_headers(scenario["client_id"])
        )
    )

    assert_score_equals(scorecard["provisional_composite_score"], 80.51)
    assert_score_equals(scorecard["final_composite_score"], 77.06)
    assert scorecard["hazard_tier"] == 2, (
        f"expected hazard_tier 2 for a HEIGHTS contractor, got {scorecard['hazard_tier']}"
    )
    # Section 3.6: grade and effective_thresholds read null until graded.
    assert scorecard["grade"] is None
    assert scorecard["effective_thresholds"] is None
    assert scorecard["governing_reporting_year"] == 2025


def test_final_variant_tightens_thresholds_at_tier_two_and_approves_at_77_06(build, api):
    """Grading applies the 0.85 tier-2 factor and stores the tightened snapshot.

    PRD Section 3.6: "Under the final variant the factor is 1.00 at tier 1,
    0.85 at tier 2 and 0.70 at tier 3."

    Design: Difficulty/dual_variant_calc/provisional_and_final_composite_diverge_on_hazard_tier_tightening
    """
    scenario = _summit_under_review(build)

    graded = build.grade_prequalification(
        scenario["prequalification_id"], scenario["client_id"]
    )

    assert_prequalification_state(
        graded,
        status="APPROVED",
        grade="B",
        deficiency_codes=[],
        final_composite_score=77.06,
        provisional_composite_score=80.51,
    )
    assert_effective_thresholds(
        graded["effective_thresholds"],
        max_trir=2.5500,
        max_dart_rate=1.2750,
        max_emr=0.8500,
        max_citation_points=5.1000,
        tightening=0.85,
        hazard_tier=2,
    )

    # The stored row agrees with the response, and the provisional figure the
    # submit transition wrote is untouched by grading.
    stored = build.read_prequalification(scenario["prequalification_id"])
    assert_prequalification_state(
        stored,
        status="APPROVED",
        grade="B",
        deficiency_codes=[],
        final_composite_score=77.06,
        provisional_composite_score=80.51,
    )


def _acme_approved_with_recordable_incident(build):
    """The canonical tier-1 approval, then one open RECORDABLE incident."""
    build.set_clock(INITIAL_CLOCK)
    scenario = build.graded_standing()
    incident = build.file_incident(
        scenario["client_id"],
        scenario["contractor_id"],
        scenario["site_id"],
        severity="RECORDABLE",
        description="Hand laceration requiring stitches",
    )
    scenario["incident"] = incident
    return scenario


def test_recordable_incident_depletes_the_verified_aggregate_to_1750000(build, api):
    """A verified certificate keeps VERIFIED while its aggregate drops 250000.

    PRD Section 3.9: "First, when the `severity` is `RECORDABLE`, `LOST_TIME`
    or `FATALITY`, the contractor's `open_severe_incident_count` rises by 1 —
    that field counts the contractor's reports at those three severities whose
    review is still open — and because insurance depletion is driven by that
    counter, `available_aggregate` is re-materialized on every one of that
    contractor's insurance certificates."

    Design: Difficulty/dual_variant_calc/insurance_per_occurrence_verifies_then_aggregate_depletion_blocks_grant
    """
    scenario = _acme_approved_with_recordable_incident(build)

    contractor = build.read_contractor(scenario["contractor_id"])
    assert_contractor_posture(
        contractor,
        status="ACTIVE",
        base_hazard_tier=1,
        open_severe_incident_count=1,
        incident_review_flag=False,
    )

    rows, _meta = validate_paginated(
        api.list_certificates(
            scenario["contractor_id"],
            scenario["contractor_headers"],
            {"coverage_type": "GL"},
        )
    )
    assert len(rows) == 1, f"expected exactly one GL certificate, got {len(rows)}"
    assert_certificate_state(
        rows[0],
        verification_status="VERIFIED",
        available_aggregate=1750000,
    )


def test_depleted_aggregate_blocks_the_badge_the_per_occurrence_basis_allowed(build, api):
    """The same GL row that verified now fails the gate's adequacy test.

    PRD Section 3.5: "The consequence is deliberate — the same
    one-million-per-occurrence, two-million-aggregate general-liability
    certificate that passed verification becomes inadequate the moment its
    contractor carries a single open recordable incident, because 2,000,000
    less 250,000 leaves 1,750,000 against a 2,000,000 floor, and
    `ERR_COVERAGE_LIMIT_INSUFFICIENT` then fires at grading and at the gate
    even though verification succeeded earlier."

    Design: Difficulty/dual_variant_calc/insurance_per_occurrence_verifies_then_aggregate_depletion_blocks_grant
    """
    scenario = _acme_approved_with_recordable_incident(build)

    response = api.create_grant(
        {
            "worker_id": scenario["worker_id"],
            "site_id": scenario["site_id"],
            "prequalification_id": scenario["prequalification_id"],
            "expires_at": "2026-12-31T00:00:00Z",
        },
        scenario["contractor_headers"],
    )
    validate_error(response, ERR_COVERAGE_LIMIT_INSUFFICIENT, 422)

    site = validate_success(
        api.get_site(scenario["site_id"], scenario["manager_headers"])
    )
    assert_site_posture(site, granted_worker_count=0, access_gate_status="RESTRICTED")

    # A RECORDABLE report does not suspend the standing.
    stored = build.read_prequalification(scenario["prequalification_id"])
    assert_prequalification_state(stored, status="APPROVED", grade="B")

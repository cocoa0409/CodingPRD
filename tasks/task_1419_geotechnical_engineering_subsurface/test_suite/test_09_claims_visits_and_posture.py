"""Construction-phase observation visits and changed-condition claims:
quantum variants, exposure rollup, posture cascade, appeal cap, temporal
gating, claim-amount floor, and the differing-findings intake cascade."""
import pytest

from test_helpers import (
    PM,
    SE,
    SEN,
    ApiErrorId,
    api_client,
    create_claim,
    create_visit,
    get_project,
    get_success_data,
    set_logical_clock,
    setup_construction_support_project,
    transition_claim,
    transition_visit,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Quantum dual variants (difficulty instance, two tests)
# ---------------------------------------------------------------------------

class TestClaimQuantumReportBaselineVsSiteObserved:
    """The same claim (120000c claimed, baseline 6000 psf, observed 4000 psf)
    yields 40000c report-baseline and 50000c site-observed."""

    def _claim_under_review(self, api):
        """CONSTRUCTION_SUPPORT project whose VERIFIED analysis has final
        bearing 6000 psf; a DIFFERING visit at 4000 psf; a manual claim of
        120000c linked to that visit, taken to UNDER_REVIEW."""
        ctx = setup_construction_support_project()  # qu 4000, fs 3.0 -> 6000
        project_id = ctx["project"]["id"]
        visit = create_visit(project_id, visit_date="2026-08-10T00:00:00Z")
        set_logical_clock("2026-08-12T00:00:00Z")
        transition_visit(visit["id"], "PERFORMED")
        transition_visit(visit["id"], "FINDINGS_FILED",
                         findings="DIFFERING", observed_bearing_psf=4000)
        claim = create_claim(project_id, claimed_amount_cents=120000,
                             observation_visit_id=visit["id"])
        reviewed = transition_claim(claim["id"], "UNDER_REVIEW")
        return ctx, claim, reviewed

    def test_quantum_variants_computed_at_under_review(self, api):
        """PRD section 3.7: "The report-baseline variant stores
        `quantum_report_baseline_cents` as the claimed amount multiplied by
        the shortfall capped at one-half, rounded half-up to whole cents —
        at most fifty percent of the claim is recoverable on the report's
        numbers. The site-observed variant stores
        `quantum_site_observed_cents` as the claimed amount multiplied by the
        shortfall scaled by 1.25 and capped at three-quarters, rounded
        half-up to whole cents — an aggravation multiplier with a higher
        ceiling, so identical inputs yield a different figure: a baseline of
        6,000 psf, an observed 4,000 psf, and a claim of 120,000 cents
        produce 40,000 cents report-baseline against 50,000 cents
        site-observed."

        Design: Difficulty/dual_variant_calc/claim_quantum_report_baseline_vs_site_observed
        """
        _ctx, _claim, reviewed = self._claim_under_review(api)
        # shortfall = (6000 - 4000) / 6000 = 1/3.
        # report_baseline: 120000 * min(1/3, 0.5) = 40000.
        # site_observed:   120000 * min(1/3 * 1.25, 0.75) = 50000.
        assert reviewed["quantum_report_baseline_cents"] == 40000
        assert reviewed["quantum_site_observed_cents"] == 50000
        assert reviewed["quantum_report_baseline_cents"] != \
            reviewed["quantum_site_observed_cents"], (
            "Identical inputs must diverge across the two quantum variants"
        )

    def test_quantum_variants_persisted_on_the_claim(self, api):
        """PRD section 3.7: "A `SeniorEngineer` opens review (`SUBMITTED` →
        `UNDER_REVIEW`), which computes both quantum variants." and "a
        baseline of 6,000 psf, an observed 4,000 psf, and a claim of 120,000
        cents produce 40,000 cents report-baseline against 50,000 cents
        site-observed."

        Design: Difficulty/dual_variant_calc/claim_quantum_report_baseline_vs_site_observed
        """
        _ctx, claim, _reviewed = self._claim_under_review(api)
        reread = get_success_data(api.get_claim(claim["id"], SEN))
        assert reread["status"] == "UNDER_REVIEW"
        assert reread["quantum_report_baseline_cents"] == 40000
        assert reread["quantum_site_observed_cents"] == 50000
        assert reread["baseline_bearing_psf"] == pytest.approx(6000)


# ---------------------------------------------------------------------------
# Exposure rollup and posture cascade (difficulty instance, two tests)
# ---------------------------------------------------------------------------

class TestClaimReviewRollupDrivesPosture:
    """Entering review recomputes the project's claims exposure (link 1) and
    flips posture to CLAIM_REVIEW (link 2)."""

    def test_exposure_counts_under_review_claim_at_claimed_amount(self, api):
        """PRD section 3.7: "The exposure rollup is precise:
        `claims_exposure_cents` sums `claimed_amount_cents` over claims in
        `UNDER_REVIEW` and `quantum_report_baseline_cents` over claims in
        `SUBSTANTIATED`; claims in `SUBMITTED`, `REBUTTED`, or `SETTLED`
        contribute zero."

        Design: Difficulty/transitive_cascade/claim_review_rollup_drives_posture
        """
        ctx = setup_construction_support_project()
        project_id = ctx["project"]["id"]
        assert get_project(project_id)["claims_exposure_cents"] == 0

        claim = create_claim(project_id, claimed_amount_cents=120000,
                             basis_text="DSC")
        assert get_project(project_id)["claims_exposure_cents"] == 0, (
            "A SUBMITTED claim contributes zero to exposure"
        )

        transition_claim(claim["id"], "UNDER_REVIEW")
        project = get_project(project_id)
        assert project["claims_exposure_cents"] == 120000, (
            "An UNDER_REVIEW claim contributes its full claimed amount"
        )

    def test_posture_flips_to_claim_review(self, api):
        """PRD section 3.7: "Entering review also recomputes the project's
        `claims_exposure_cents` (link 1) and its `posture`, which becomes
        `CLAIM_REVIEW` while any claim stands in `UNDER_REVIEW` or
        `SUBSTANTIATED` (link 2)."
        PRD section 3.2: "`posture` is `FROZEN` when any clearance of the
        active plan's borings is `CONFLICT_MARKED`; otherwise it is
        `CLAIM_REVIEW` when any claim of the project stands in `UNDER_REVIEW`
        or `SUBSTANTIATED` (§3.7); otherwise it is `OPEN`."

        Design: Difficulty/transitive_cascade/claim_review_rollup_drives_posture
        """
        ctx = setup_construction_support_project()
        project_id = ctx["project"]["id"]
        assert get_project(project_id)["posture"] == "OPEN"

        claim = create_claim(project_id, claimed_amount_cents=120000,
                             basis_text="DSC")
        transition_claim(claim["id"], "UNDER_REVIEW")
        project = get_project(project_id)
        assert project["posture"] == "CLAIM_REVIEW", (
            f"Posture must become CLAIM_REVIEW while a claim is UNDER_REVIEW, "
            f"got {project['posture']}"
        )


# ---------------------------------------------------------------------------
# Appeal cap, visit temporal gate, claim-amount floor, intake cascade
# ---------------------------------------------------------------------------

def test_claim_appeal_cap_enforced(api):
    """PRD section 3.7: "A rebutted claim may be appealed back into review
    exactly once (`REBUTTED` → `UNDER_REVIEW`): the attempt requires
    `appeal_count` still below its cap of 1, drawing `ERR_APPEAL_LIMIT`
    (HTTP 409) at the cap, and re-entry increments `appeal_count` from its
    initial 0 and recomputes both quanta."

    Design: Corner/state_machines/claim_appeal_cap_enforced
    """
    ctx = setup_construction_support_project()
    claim = create_claim(ctx["project"]["id"], claimed_amount_cents=80000,
                         basis_text="DSC")
    transition_claim(claim["id"], "UNDER_REVIEW")
    transition_claim(claim["id"], "REBUTTED")
    appealed = transition_claim(claim["id"], "UNDER_REVIEW")
    assert appealed["appeal_count"] == 1, (
        "The first appeal re-entry increments appeal_count from 0 to 1"
    )
    transition_claim(claim["id"], "REBUTTED")

    resp = api.transition_claim(claim["id"], {"to": "UNDER_REVIEW"}, SEN)
    validate_error(resp, ApiErrorId.ERR_APPEAL_LIMIT)
    assert resp.status_code == 409

    reread = get_success_data(api.get_claim(claim["id"], SEN))
    assert reread["appeal_count"] == 1
    assert reread["status"] == "REBUTTED", (
        "A rejected appeal leaves the claim untouched"
    )


def test_visit_perform_before_visit_date_rejected(api):
    """PRD section 3.7: "A `StaffEngineer` performs the visit (`SCHEDULED` →
    `PERFORMED`) once the project stands in `CONSTRUCTION_SUPPORT`
    (`ERR_PROJECT_STATE_FORBIDS` otherwise) and the current logical time has
    reached `visit_date` — an early performance is rejected with
    `ERR_VISIT_DATE_FUTURE` (HTTP 422)."
    PRD section 2.6: "Before any client call adjusts it, the logical clock
    reads exactly `2026-08-01T00:00:00Z`".

    Design: Corner/validations/visit_perform_before_visit_date_rejected
    """
    ctx = setup_construction_support_project()
    visit = create_visit(ctx["project"]["id"],
                         visit_date="2026-08-10T00:00:00Z")
    # The logical clock is untouched: 2026-08-01T00:00:00Z < visit_date.
    resp = api.transition_observation_visit(visit["id"], {"to": "PERFORMED"}, SE)
    validate_error(resp, ApiErrorId.ERR_VISIT_DATE_FUTURE)
    assert resp.status_code == 422


def test_manual_claim_zero_amount_rejected(api):
    """PRD section 3.7: "Beyond the automatic intake, a `ProjectManager` or
    `ClientRep` may file a claim manually under a project in
    `CONSTRUCTION_SUPPORT` (`ERR_PROJECT_STATE_FORBIDS` otherwise), supplying
    `claimed_amount_cents` — the contractor's claimed extra cost, which must
    be non-negative as a body check (`ERR_VALIDATION`) and at least 1 cent
    for a manual filing (`ERR_CLAIM_AMOUNT_INVALID`, HTTP 422; only
    auto-opened claims may carry zero)".

    Design: Corner/validations/manual_claim_zero_amount_rejected
    """
    ctx = setup_construction_support_project()
    resp = api.create_claim(
        ctx["project"]["id"], {"claimed_amount_cents": 0, "basis_text": "zero"},
        PM)
    validate_error(resp, ApiErrorId.ERR_CLAIM_AMOUNT_INVALID)
    assert resp.status_code == 422


def test_differing_findings_autocreate_submitted_claim(api):
    """PRD section 3.7: "A `DIFFERING` filing is the first link of the
    claim-intake cascade: the server automatically opens a
    ChangedConditionClaim on the project in `SUBMITTED` with
    `claimed_amount_cents` equal to 0, `basis_text` set to 'Auto-opened from
    differing-site-condition finding', and `observation_visit_id` pointing at
    this visit."

    Design: Corner/complexity_layers/differing_findings_autocreate_submitted_claim
    """
    ctx = setup_construction_support_project()
    project_id = ctx["project"]["id"]
    visit = create_visit(project_id, visit_date="2026-08-02T00:00:00Z")
    set_logical_clock("2026-08-03T00:00:00Z")
    transition_visit(visit["id"], "PERFORMED")
    transition_visit(visit["id"], "FINDINGS_FILED",
                     findings="DIFFERING", observed_bearing_psf=4000)

    resp = api.list_claims(PM, params={"project_id": project_id})
    claims, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    auto = claims[0]
    assert auto["status"] == "SUBMITTED"
    assert auto["claimed_amount_cents"] == 0
    assert auto["observation_visit_id"] == visit["id"]
    assert auto["basis_text"] == "Auto-opened from differing-site-condition finding"

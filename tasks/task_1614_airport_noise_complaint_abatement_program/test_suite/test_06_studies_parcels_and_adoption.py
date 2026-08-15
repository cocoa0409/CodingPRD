"""Part 150 studies and parcels: the revision cycle, supersession, the
PRELIMINARY/FINAL exposure variant flip, and the depth-3 adoption cascade onto
parcels, applications and the fund pipeline."""
import pytest

from test_helpers import (
    add_parcel,
    advance_study,
    create_application,
    create_fund,
    create_study,
    decide_application,
    read_fund,
    screen_application,
    submit_application,
    TEST_USERS,
    validate_success,
)

ADMIN = TEST_USERS["noise_office_admin_headers"]
COORDINATOR = TEST_USERS["study_coordinator_headers"]


def test_study_revision_cycle_increments_count(api):
    """PRD 3.7: "from `PUBLIC_REVIEW` the study may return to `DATA_COLLECTION` for
    another pass — each such request, carrying a `reason`, increments
    `revision_count` — or proceed to adoption."

    Design: Corner/state_machines/study_revision_cycle_increments_count
    """
    study = create_study(title="Part150 Mu")
    advance_study(study["id"], "PUBLIC_REVIEW")

    returned = validate_success(
        api.request_revision(study["id"], {"reason": "incomplete contour"}, COORDINATOR),
        200,
    )
    assert returned["status"] == "DATA_COLLECTION"
    assert returned["revision_count"] == 1

    validate_success(api.release_draft(study["id"], {}, COORDINATOR), 200)
    validate_success(api.open_public_comment(study["id"], {}, COORDINATOR), 200)
    adopted = validate_success(api.adopt_study(study["id"], {}, ADMIN), 200)
    assert adopted["status"] == "ADOPTED"


def test_study_supersede_moves_prior_adopted_to_superseded(api):
    """PRD 3.7: "Adoption is reserved for a `NoiseOfficeAdmin`: it stamps
    `adopted_at`, and when `supersedes_study_id` is set, the named study must
    currently be `ADOPTED` (else `ERR_INVALID_STUDY_STATE`) and moves to
    `SUPERSEDED`, which is terminal."

    Design: Corner/state_machines/study_supersede_moves_prior_adopted_to_superseded
    """
    study_a = create_study(title="Part150 Nu-A", baseline_year=2024)
    advance_study(study_a["id"], "ADOPTED")

    study_b = create_study(
        title="Part150 Nu-B", baseline_year=2025, supersedes_study_id=study_a["id"]
    )
    advance_study(study_b["id"], "PUBLIC_REVIEW")
    adopted = validate_success(api.adopt_study(study_b["id"], {}, ADMIN), 200)
    assert adopted["status"] == "ADOPTED"

    reread_a = validate_success(api.get_study(study_a["id"], COORDINATOR))
    assert reread_a["status"] == "SUPERSEDED"


def test_parcel_preliminary_variant_before_adoption(api):
    """PRD 3.7: "While the owning study is not yet `ADOPTED`, the `PRELIMINARY`
    variant applies: `dnl_db_effective` is the modeled level minus a conservative
    1.5 dB adjustment, rounded half-up to one decimal."

    Design: Difficulty/dual_variant_calc/parcel_dnl_preliminary_final_variants_flip_eligibility
    """
    study = create_study(title="Part150 Alpha")
    advance_study(study["id"], "DATA_COLLECTION")
    parcel = add_parcel(
        study["id"],
        parcel_ref="P-100",
        land_use="RESIDENTIAL",
        dnl_db_measured=64.8,
        dnl_db_modeled=67.0,
        zone_code="Z1",
    )
    # PRELIMINARY: 67.0 - 1.5 = 65.5 -> band 65 -> INCOMPATIBLE_RESIDENTIAL.
    assert parcel["dnl_db_effective"] == pytest.approx(65.5, abs=1e-6)
    assert parcel["dnl_band"] == 65
    assert parcel["compatibility_status"] == "INCOMPATIBLE_RESIDENTIAL"
    assert parcel["insulation_eligible"] is True

    # The variant flip itself is exercised by the sibling test.
    advance_study(study["id"], "PUBLIC_REVIEW")
    still_preliminary = validate_success(api.get_parcel(parcel["id"], COORDINATOR))
    assert still_preliminary["dnl_db_effective"] == pytest.approx(65.5, abs=1e-6)
    assert still_preliminary["insulation_eligible"] is True


def test_parcel_final_variant_after_adoption_flips_eligibility(api):
    """PRD 3.7: "Once the study is `ADOPTED`, the `FINAL` variant applies:
    `dnl_db_effective` is the measured level taken verbatim."
    PRD 3.7: "Because the two variants read different inputs, identical parcel data
    can flip a parcel's eligibility across adoption — which is precisely what drives
    the cascade."

    Design: Difficulty/dual_variant_calc/parcel_dnl_preliminary_final_variants_flip_eligibility
    """
    study = create_study(title="Part150 Alpha")
    advance_study(study["id"], "DATA_COLLECTION")
    parcel = add_parcel(
        study["id"],
        parcel_ref="P-100",
        land_use="RESIDENTIAL",
        dnl_db_measured=64.8,
        dnl_db_modeled=67.0,
        zone_code="Z1",
    )
    assert parcel["insulation_eligible"] is True
    advance_study(study["id"], "PUBLIC_REVIEW")

    validate_success(api.adopt_study(study["id"], {}, ADMIN), 200)

    reread = validate_success(api.get_parcel(parcel["id"], COORDINATOR))
    # FINAL: measured 64.8 verbatim -> 60.0 <= 64.8 < 65.0 band of compatibility.
    assert reread["dnl_db_effective"] == pytest.approx(64.8, abs=1e-6)
    assert reread["dnl_band"] == 60
    assert reread["compatibility_status"] == "COMPATIBLE_WITH_MEASURES"
    assert reread["insulation_eligible"] is False


def _setup_adoption_cascade(api):
    """ACTIVE fund; PUBLIC_REVIEW study with parcels P-1 (64.8/67.0) and P-3
    (75.2/73.4); App1 on P-1 decided ELIGIBLE_TIER2 (est 500,000); App3 on P-3
    decided ELIGIBLE_TIER1 (est 1,000,000)."""
    fund = create_fund(fiscal_year="FY2027", total_allocation_cents=20_000_000)
    study = create_study(title="Part150 Epsilon")
    advance_study(study["id"], "DATA_COLLECTION")
    p1 = add_parcel(study["id"], parcel_ref="P-1", dnl_db_measured=64.8,
                    dnl_db_modeled=67.0, zone_code="Z1")
    p3 = add_parcel(study["id"], parcel_ref="P-3", dnl_db_measured=75.2,
                    dnl_db_modeled=73.4, zone_code="Z1")

    app1 = create_application(p1["id"], rooms_count=4, est_cost_cents=500_000)
    submit_application(app1["id"])
    screen_application(app1["id"])
    app1 = decide_application(app1["id"], "ELIGIBLE_TIER2")

    app3 = create_application(p3["id"], rooms_count=4, est_cost_cents=1_000_000)
    submit_application(app3["id"])
    screen_application(app3["id"])
    app3 = decide_application(app3["id"], "ELIGIBLE_TIER1")

    advance_study(study["id"], "PUBLIC_REVIEW")
    return {
        "fund": fund, "study": study, "p1": p1, "p3": p3,
        "app1": app1, "app3": app3,
    }


def test_adoption_cascade_revokes_applications_on_evaporated_parcels(api):
    """PRD 3.8: "when cascade A flips a parcel's `insulation_eligible` from true to
    false, any application on that parcel sitting in `SUBMITTED`, `SCREENING`,
    `ELIGIBLE_TIER1`, or `ELIGIBLE_TIER2` with funding still `UNFUNDED` is moved by
    the system to `INELIGIBLE` with `decided_at` stamped and its `priority_score`
    recomputed".

    Design: Difficulty/transitive_cascade/study_adoption_cascade_parcel_application_fund
    """
    ctx = _setup_adoption_cascade(api)
    # Preliminary variant: P-1 reads 67.0 - 1.5 = 65.5 (eligible).
    assert ctx["p1"]["dnl_db_effective"] == pytest.approx(65.5, abs=1e-6)
    assert ctx["p1"]["insulation_eligible"] is True
    assert ctx["app1"]["eligibility_status"] == "ELIGIBLE_TIER2"

    validate_success(api.adopt_study(ctx["study"]["id"], {}, ADMIN), 200)

    parcel = validate_success(api.get_parcel(ctx["p1"]["id"], COORDINATOR))
    # Hop B: FINAL variant reads the measured level verbatim.
    assert parcel["dnl_db_effective"] == pytest.approx(64.8, abs=1e-6)
    assert parcel["insulation_eligible"] is False

    app1 = validate_success(api.get_application(ctx["app1"]["id"], COORDINATOR))
    # Hop C1: the eligibility that evaporated revokes the UNFUNDED application.
    assert app1["eligibility_status"] == "INELIGIBLE"
    assert app1["funding_status"] == "UNFUNDED"


def test_adoption_cascade_rescores_survivors_and_recomputes_pipeline(api):
    """PRD 3.7: "Hop two: applications on parcels whose eligibility evaporated are
    revoked by the system, and every non-withdrawn application on the study's
    parcels has its `priority_score` recomputed. Hop three: the active fund's
    `projected_pipeline_cents` is recomputed."
    PRD 3.8: "`projected_pipeline_cents` sums the provisional obligations — each
    computed on the application's `est_cost_cents` — of every `UNFUNDED` application
    currently at either eligibility tier".

    Design: Difficulty/transitive_cascade/study_adoption_cascade_parcel_application_fund
    """
    ctx = _setup_adoption_cascade(api)
    # App3 preliminary exposure 73.4 - 1.5 = 71.9 -> band 70 -> 60 + 10 = 70.
    assert ctx["app3"]["priority_score"] == 70

    pipeline_before = read_fund(ctx["fund"]["id"])["projected_pipeline_cents"]
    # App1 provisional 460,000 + App3 provisional 1,150,000.
    assert pipeline_before == 1_610_000

    validate_success(api.adopt_study(ctx["study"]["id"], {}, ADMIN), 200)

    app3 = validate_success(api.get_application(ctx["app3"]["id"], COORDINATOR))
    # Hop C2: band flips 70 -> 75, so the rescore reads 80 + 10 = 90.
    assert app3["eligibility_status"] == "ELIGIBLE_TIER1"
    assert app3["priority_score"] == 90

    pipeline_after = read_fund(ctx["fund"]["id"])["projected_pipeline_cents"]
    # Hop D: only App3's provisional obligation remains in the pipeline.
    assert pipeline_after == 1_150_000

"""Sound insulation intake: parcel eligibility gates, the one-active-application
rule, tier decision gates, the appeal window, the appeal/re-screening cycle on
the eligibility dimension, and the state-over-temporal validation ordering."""
from test_helpers import (
    ApiErrorId,
    add_parcel,
    advance_study,
    create_application,
    create_fund,
    create_study,
    decide_application,
    issue_offer,
    screen_application,
    set_clock,
    setup_adopted_study_with_parcel,
    submit_application,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

COORDINATOR = TEST_USERS["study_coordinator_headers"]
LIAISON = TEST_USERS["community_liaison_headers"]


def test_second_active_application_same_parcel_rejected(api):
    """PRD 3.8: "no other application for the same parcel may currently sit in
    `NEW`, `SUBMITTED`, `SCREENING`, `ELIGIBLE_TIER1`, `ELIGIBLE_TIER2`, or
    `APPEALED` (else `ERR_ACTIVE_APPLICATION_EXISTS`)."

    Design: Corner/validations/second_active_application_same_parcel_rejected
    """
    study = create_study(title="Part150 Tau")
    advance_study(study["id"], "DATA_COLLECTION")
    # Preliminary variant: 67.0 - 1.5 = 65.5 -> eligible.
    parcel = add_parcel(study["id"], parcel_ref="P-930", dnl_db_measured=64.0,
                        dnl_db_modeled=67.0)

    first = validate_success(
        api.create_application(
            {
                "parcel_id": parcel["id"],
                "dwelling_type": "SINGLE_FAMILY",
                "rooms_count": 4,
                "est_cost_cents": 300_000,
            },
            LIAISON,
        ),
        201,
    )
    assert first["eligibility_status"] == "NEW"

    second = api.create_application(
        {
            "parcel_id": parcel["id"],
            "dwelling_type": "MULTI_FAMILY",
            "rooms_count": 6,
            "est_cost_cents": 400_000,
        },
        LIAISON,
    )
    validate_error(second, ApiErrorId.ERR_ACTIVE_APPLICATION_EXISTS)


def test_tier1_decision_without_band_or_institution_rejected(api):
    """PRD 3.8: "`ELIGIBLE_TIER1` requires the parcel's `dnl_db_effective` to be at
    least 70.0 or its `land_use` to be `SCHOOL` or `HOSPITAL` (else
    `ERR_TIER_NOT_PERMITTED`); `ELIGIBLE_TIER2` needs no extra gate".

    Design: Corner/validations/tier1_decision_without_band_or_institution_rejected
    """
    create_fund(fiscal_year="FY2027", total_allocation_cents=5_000_000)
    study = create_study(title="Part150 Upsilon")
    advance_study(study["id"], "DATA_COLLECTION")
    # Preliminary: 67.0 - 1.5 = 65.5 -> eligible, band 65, plain RESIDENTIAL.
    parcel = add_parcel(study["id"], parcel_ref="P-940", dnl_db_measured=64.0,
                        dnl_db_modeled=67.0)
    application = create_application(parcel["id"], est_cost_cents=300_000)
    submit_application(application["id"])
    screen_application(application["id"])

    rejected = api.record_decision(
        application["id"], {"decision": "ELIGIBLE_TIER1"}, COORDINATOR
    )
    validate_error(rejected, ApiErrorId.ERR_TIER_NOT_PERMITTED)

    accepted = validate_success(
        api.record_decision(application["id"], {"decision": "ELIGIBLE_TIER2"}, COORDINATOR),
        200,
    )
    assert accepted["eligibility_status"] == "ELIGIBLE_TIER2"
    assert accepted["tier_cap_cents"] == 4_000_000


def test_appeal_after_30_day_window_rejected(api):
    """PRD 3.8: "Within thirty days of `decided_at` (later is
    `ERR_APPEAL_WINDOW_EXPIRED`) and at most twice per application (a third attempt
    is `ERR_APPEAL_LIMIT_REACHED`), a `CommunityLiaison` may appeal with a
    `reason`, moving the application to `APPEALED` and incrementing
    `appeal_count`".

    Design: Corner/validations/appeal_after_30_day_window_rejected
    """
    create_fund(
        fiscal_year="FY2027",
        total_allocation_cents=5_000_000,
        intake_closes_at="2026-12-31T00:00:00Z",
    )
    study = create_study(title="Part150 Phi")
    advance_study(study["id"], "DATA_COLLECTION")
    parcel = add_parcel(study["id"], parcel_ref="P-950", dnl_db_measured=64.0,
                        dnl_db_modeled=67.0)
    application = create_application(parcel["id"], est_cost_cents=300_000)
    submit_application(application["id"])
    screen_application(application["id"])
    decide_application(application["id"], "INELIGIBLE")

    # Decision stamped at the startup clock 2026-08-01; 2026-09-01 is later than
    # decided_at + 30 days.
    set_clock("2026-09-01T00:00:00Z")

    response = api.appeal_application(
        application["id"], {"reason": "too late"}, LIAISON
    )
    validate_error(response, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED)


def test_dnl_64_9_parcel_rejects_application_create(api):
    """PRD 3.8: "the parcel's `insulation_eligible` must be `true` (else
    `ERR_PARCEL_NOT_INCOMPATIBLE`)".
    PRD 3.7: "for `RESIDENTIAL`, `SCHOOL`, and `HOSPITAL` parcels, an effective
    level of at least 65.0 is `INCOMPATIBLE_RESIDENTIAL`, at least 60.0 but below
    65.0 is `COMPATIBLE_WITH_MEASURES`, and below 60.0 is `COMPATIBLE`".

    Design: Difficulty/boundary_precision_check/dnl_eligibility_64_9_vs_65_0
    """
    create_fund(fiscal_year="FY2027", total_allocation_cents=5_000_000)
    study = create_study(title="Part150 Theta")
    advance_study(study["id"], "DATA_COLLECTION")
    add_parcel(study["id"], parcel_ref="P-LOW", dnl_db_measured=64.9,
               dnl_db_modeled=66.5)
    advance_study(study["id"], "ADOPTED")

    parcels, _meta = validate_paginated(
        api.list_study_parcels(study["id"], COORDINATOR)
    )
    # FINAL variant reads measured verbatim: 64.9 < 65.0 -> COMPATIBLE_WITH_MEASURES.
    assert parcels[0]["compatibility_status"] == "COMPATIBLE_WITH_MEASURES"
    assert parcels[0]["insulation_eligible"] is False

    response = api.create_application(
        {
            "parcel_id": parcels[0]["id"],
            "dwelling_type": "SINGLE_FAMILY",
            "rooms_count": 4,
            "est_cost_cents": 500_000,
        },
        LIAISON,
    )
    validate_error(response, ApiErrorId.ERR_PARCEL_NOT_INCOMPATIBLE)


def test_dnl_65_0_parcel_accepts_application_create(api):
    """PRD 3.7: "The `insulation_eligible` flag is `true` exactly when the
    compatibility status is `INCOMPATIBLE_RESIDENTIAL`".
    PRD 3.8: "A new application is `NEW` on its eligibility dimension
    (`eligibility_status`) and `UNFUNDED` on its funding dimension
    (`funding_status`)".

    Design: Difficulty/boundary_precision_check/dnl_eligibility_64_9_vs_65_0
    """
    create_fund(fiscal_year="FY2027", total_allocation_cents=5_000_000)
    study = create_study(title="Part150 Theta")
    advance_study(study["id"], "DATA_COLLECTION")
    add_parcel(study["id"], parcel_ref="P-EXACT", dnl_db_measured=65.0,
               dnl_db_modeled=66.5)
    advance_study(study["id"], "ADOPTED")

    parcels, _meta = validate_paginated(api.list_study_parcels(study["id"], COORDINATOR))
    # FINAL variant: 65.0 >= 65.0 (boundary inclusive) -> INCOMPATIBLE_RESIDENTIAL.
    assert parcels[0]["compatibility_status"] == "INCOMPATIBLE_RESIDENTIAL"
    assert parcels[0]["insulation_eligible"] is True

    created = validate_success(
        api.create_application(
            {
                "parcel_id": parcels[0]["id"],
                "dwelling_type": "SINGLE_FAMILY",
                "rooms_count": 4,
                "est_cost_cents": 500_000,
            },
            LIAISON,
        ),
        201,
    )
    assert created["eligibility_status"] == "NEW"
    assert created["funding_status"] == "UNFUNDED"
    assert created["tier_cap_cents"] == 0


def _setup_ineligible_application(api):
    """Adopted study (parcel 66.0/67.5 RESIDENTIAL), active fund, and an
    application decided INELIGIBLE."""
    fund = create_fund(fiscal_year="FY2027", total_allocation_cents=5_000_000)
    ctx = setup_adopted_study_with_parcel(measured=66.0, modeled=67.5, zone_code="Z4")
    application = create_application(ctx["parcel"]["id"], rooms_count=5,
                                     est_cost_cents=500_000)
    submit_application(application["id"])
    screen_application(application["id"])
    decided = decide_application(application["id"], "INELIGIBLE")
    return {"fund": fund, **ctx, "application": decided}


def test_appeal_cycle_moves_eligibility_while_funding_stays_unfunded(api):
    """PRD 3.8: "the two dimensions evolve independently, and the funding machine's
    guards read the eligibility dimension."
    PRD 3.8: "a `CommunityLiaison` may appeal with a `reason`, moving the
    application to `APPEALED` and incrementing `appeal_count`; from there,
    screening begins again."

    Design: Difficulty/non_linear_state_machine/insulation_appeal_cycle_with_parallel_funding_dimension
    """
    ctx = _setup_ineligible_application(api)
    assert ctx["application"]["funding_status"] == "UNFUNDED"

    appealed = validate_success(
        api.appeal_application(
            ctx["application"]["id"], {"reason": "new acoustics report"}, LIAISON
        ),
        200,
    )
    assert appealed["eligibility_status"] == "APPEALED"
    assert appealed["funding_status"] == "UNFUNDED"
    assert appealed["appeal_count"] == 1

    screen_application(ctx["application"]["id"])
    decided = decide_application(ctx["application"]["id"], "ELIGIBLE_TIER2")
    assert decided["eligibility_status"] == "ELIGIBLE_TIER2"
    assert decided["tier_cap_cents"] == 4_000_000
    assert decided["funding_status"] == "UNFUNDED"


def test_issue_offer_opens_only_after_eligibility_lands(api):
    """PRD 3.8: "the funding dimension must be `UNFUNDED` and the eligibility
    dimension must be `ELIGIBLE_TIER1` or `ELIGIBLE_TIER2` — the cross-dimension
    guard, both failures surfacing as `ERR_INVALID_APPLICATION_STATE`".
    PRD 3.8: "for tier two, the covered amount is 80 percent of the cost basis
    rounded half-up to whole cents, and the structure component is that amount
    capped at 4,000,000 cents."

    Design: Difficulty/non_linear_state_machine/insulation_appeal_cycle_with_parallel_funding_dimension
    """
    ctx = _setup_ineligible_application(api)
    validate_success(
        api.appeal_application(
            ctx["application"]["id"], {"reason": "new acoustics report"}, LIAISON
        ),
        200,
    )
    screen_application(ctx["application"]["id"])
    decide_application(ctx["application"]["id"], "ELIGIBLE_TIER2")

    offered = issue_offer(ctx["application"]["id"], ctx["fund"]["id"])
    assert offered["eligibility_status"] == "ELIGIBLE_TIER2"
    assert offered["funding_status"] == "OFFER_ISSUED"
    # Provisional split on 500,000: structure 400,000 + contingency 40,000 + admin 20,000.
    assert offered["offered_amount_cents"] == 460_000


def test_state_beats_temporal_on_withdrawn_application_submit(api):
    """PRD 2.11: "Every request is checked against a fixed sequence of gates, and
    the first gate that fails determines the error returned; later gates are not
    evaluated for that request."
    PRD 2.11: "8. **State-machine legality** — the target resource sits in a valid
    from-state for the attempted transition".
    PRD 3.8: "Every out-of-state transition on either dimension is rejected with
    `ERR_INVALID_APPLICATION_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_withdrawn_application_submit
    """
    create_fund(
        fiscal_year="FY2027",
        total_allocation_cents=5_000_000,
        intake_closes_at="2026-08-15T00:00:00Z",
    )
    ctx = setup_adopted_study_with_parcel(measured=66.0, modeled=67.5, zone_code="Z5")
    application = create_application(ctx["parcel"]["id"], est_cost_cents=500_000)
    submit_application(application["id"])
    validate_success(api.withdraw_application(application["id"], {}, LIAISON), 200)

    # Advance past the intake close so the temporal gate would also fail.
    set_clock("2026-08-20T00:00:00Z")

    response = api.submit_application(application["id"], {}, LIAISON)
    # State (gate 8) outranks temporal windows (gate 10).
    validate_error(response, ApiErrorId.ERR_INVALID_APPLICATION_STATE)


def test_submission_window_error_fires_when_state_is_valid(api):
    """PRD 3.8: "Submitting moves `NEW` to `SUBMITTED`, stamps `submitted_at`, and
    requires that an `ACTIVE` fund exists whose intake window covers now (else
    `ERR_SUBMISSION_WINDOW_CLOSED`)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_withdrawn_application_submit
    """
    create_fund(
        fiscal_year="FY2027",
        total_allocation_cents=5_000_000,
        intake_closes_at="2026-08-15T00:00:00Z",
    )
    ctx = setup_adopted_study_with_parcel(measured=66.0, modeled=67.5, zone_code="Z5")
    application = create_application(ctx["parcel"]["id"], est_cost_cents=500_000)

    # Still NEW (valid from-state for submit) but the intake window has closed.
    set_clock("2026-08-20T00:00:00Z")

    response = api.submit_application(application["id"], {}, LIAISON)
    validate_error(response, ApiErrorId.ERR_SUBMISSION_WINDOW_CLOSED)

"""Cross-cutting coverage: the three version guards, a derived disclosure pair and a short cascade.

PRD §2.7: "Three write operations are guarded by optimistic concurrency control against the
`version` of a parent row. In each case the guard field is a required, non-optional member of
the request body."
"""

from test_helpers import (
    ANALYST_HEADERS,
    CONTROLLER_HEADERS,
    ENGINEER_HEADERS,
    ERR_STALE_FIELD_ACTION_VERSION,
    ERR_STALE_PERIOD_VERSION,
    WARRANTY_ANALYST_USER_ID,
    create_accrual,
    create_failure_mode,
    create_family,
    create_field_action,
    create_observation,
    create_period,
    create_remedy_option,
    create_vintage,
    decide_field_action,
    factories,
    lock_period,
    period_version,
    propose_accrual,
    read_accrual,
    read_family,
    read_field_action,
    read_period,
    select_remedy,
    submit_field_action,
    success_data,
    validate_error,
    validate_paginated,
)


def _analog_basis(api):
    """FAM-A: 300 observed claims on a 10000-unit cohort, the standard analogue basis."""
    analog_family = create_family(
        api,
        family_code="FAM-A",
        name="Legacy Compressor Platform",
        launch_date="2022-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=20000,
        reserve_cap_cents=100000000,
    )
    analog_vintage = create_vintage(
        api,
        analog_family["id"],
        vintage_code="A-MY2022",
        units_shipped=10000,
        ship_period_code="2022-Q1",
        warranty_expiry_date="2029-12-31",
    )
    analog_mode = create_failure_mode(
        api,
        analog_family["id"],
        mode_code="FM-A-CORE",
        description="Legacy compressor core wear",
        severity="FUNCTIONAL",
        cost_per_claim_cents=20000,
    )
    create_observation(
        api,
        analog_vintage["id"],
        analog_mode["id"],
        observation_period_code="2026-Q3",
        months_in_service_from=0,
        months_in_service_to=24,
        claim_count=300,
        paid_cost_cents=6000000,
    )
    return analog_family


def _blend_family(api, analog_family_id, family_code, name, reserve_cap_cents=100000000):
    """A blend family priced at 30000 cents a claim against the analogue basis."""
    return create_family(
        api,
        family_code=family_code,
        name=name,
        launch_date="2024-01-01",
        base_warranty_months=36,
        standard_cost_per_claim_cents=30000,
        reserve_cap_cents=reserve_cap_cents,
        engineering_estimate_rate_ppm=4000,
        analog_family_id=analog_family_id,
    )


def _campaign(
    api,
    family_id,
    action_code,
    unit_count,
    parts_cost_cents,
    admin_cost_cents,
    affected_build_start_date="2025-01-01",
    affected_build_end_date="2025-06-30",
):
    """A submitted campaign priced by a single engineering-approved option.

    The build window is a parameter because PRD §3.5 protects it with a 30-day buffered
    closed-interval conflict check on the same family: "only a gap of 31 days or more is
    accepted". Two campaigns on one family must therefore be given windows that clear it.
    """
    action = create_field_action(
        api,
        family_id,
        action_code=action_code,
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date=affected_build_start_date,
        affected_build_end_date=affected_build_end_date,
        affected_unit_count=unit_count,
    )
    option = create_remedy_option(
        api,
        action["id"],
        option_code=f"OPT-{action_code}",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=parts_cost_cents,
        labor_hours_centi=100,
        admin_cost_cents=admin_cost_cents,
        expected_take_rate_bps=10000,
        is_engineering_approved=True,
    )
    select_remedy(
        api,
        action["id"],
        remedy_option_id=option["id"],
        expected_field_action_version=action["version"],
    )
    return submit_field_action(api, action["id"])


def test_the_first_accrual_invalidates_a_second_writers_period_token(api):
    """A create bumps the period, so the co-writer must re-read before it may write.

    PRD §2.7: "`POST /warranty/accruals` must carry `expected_period_version` holding the
    client's last observed `version` of the `AccrualPeriod` named by `period_id`. If that value
    does not equal the period's current `version`, the create is rejected with
    `ERR_STALE_PERIOD_VERSION` (HTTP 412)." PRD §3.3 fixes the side effect: the create "advances
    the parent period's `version` by 1".

    Design: Corner/cross_cutting_complexity_layers/corner_occ_accrual_create_with_a_stale_period_version_rejected
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    first_token = period["version"]
    analog = _analog_basis(api)
    family = _blend_family(api, analog["id"], "FAM-OC1", "Concurrency Platform One")
    cohort_a = create_vintage(
        api,
        family["id"],
        vintage_code="OC1-MY2024-A",
        units_shipped=3000,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    cohort_b = create_vintage(
        api,
        family["id"],
        vintage_code="OC1-MY2024-B",
        units_shipped=3000,
        ship_period_code="2024-Q2",
        warranty_expiry_date="2028-12-31",
    )
    create_failure_mode(
        api,
        family["id"],
        mode_code="FM-OC1-01",
        description="Concurrency platform mode",
        severity="FUNCTIONAL",
        cost_per_claim_cents=30000,
    )

    first = create_accrual(
        api,
        period["id"],
        cohort_a["id"],
        method="ANALOG_BLEND",
        elapsed_exposure_bps=2000,
        expected_period_version=first_token,
    )
    assert first["accrued_amount_cents"] == 2910000

    validate_error(
        api.create_accrual_raw(
            ANALYST_HEADERS,
            factories.accrual_payload(
                period["id"],
                cohort_b["id"],
                first_token,
                method="ANALOG_BLEND",
                elapsed_exposure_bps=2000,
            ),
        ),
        ERR_STALE_PERIOD_VERSION,
        expected_status=412,
    )
    _, meta = validate_paginated(api.list_accruals(ANALYST_HEADERS, period_id=period["id"]))
    assert meta["total_count"] == 1

    fresh_token = period_version(api, period["id"])
    assert fresh_token == 2

    second = create_accrual(
        api,
        period["id"],
        cohort_b["id"],
        method="ANALOG_BLEND",
        elapsed_exposure_bps=2000,
        expected_period_version=fresh_token,
    )
    assert second["accrued_amount_cents"] == 2910000
    assert period_version(api, period["id"]) == 3


def test_locking_analysis_invalidates_the_rollforward_token_read_before_it(api):
    """The lock transition is itself a mutation, so the pre-lock token is refused.

    PRD §2.7: "`POST /warranty/periods/{periodId}/rollforward` must carry
    `expected_period_version` holding the client's last observed `version` of that same
    `AccrualPeriod`. A mismatch against the period's current `version` is rejected with
    `ERR_STALE_PERIOD_VERSION` (HTTP 412)." PRD §3.1 says locking "advances the period's
    `version` by 1", and PRD §3.9 that generation "flips the period's `rollforward_generated`
    to true and advances the period's `version` by 1".

    Design: Corner/cross_cutting_complexity_layers/corner_occ_rollforward_generation_with_a_stale_period_version_rejected
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    pre_lock_token = period["version"]
    locked = lock_period(api, period["id"])
    post_lock_token = locked["version"]
    assert post_lock_token == pre_lock_token + 1

    validate_error(
        api.generate_rollforward(
            CONTROLLER_HEADERS, period["id"], expected_period_version=pre_lock_token
        ),
        ERR_STALE_PERIOD_VERSION,
        expected_status=412,
    )
    assert read_period(api, period["id"])["rollforward_generated"] is False

    snapshot = success_data(
        api.generate_rollforward(
            CONTROLLER_HEADERS, period["id"], expected_period_version=post_lock_token
        ),
        expected_status=201,
    )
    assert snapshot["period_id"] == period["id"]

    after = read_period(api, period["id"])
    assert after["rollforward_generated"] is True
    assert after["version"] == post_lock_token + 1

    validate_error(
        api.generate_rollforward(
            CONTROLLER_HEADERS, period["id"], expected_period_version=post_lock_token
        ),
        ERR_STALE_PERIOD_VERSION,
        expected_status=412,
    )


def test_a_standing_remedy_selection_cannot_be_overwritten_blind(api):
    """The second selection must quote the version the first selection produced.

    PRD §2.7: "`POST /warranty/field-actions/{fieldActionId}/select-remedy` must carry
    `expected_field_action_version` holding the client's last observed `version` of the target
    `FieldAction`. A mismatch against the field action's current `version` is rejected with
    `ERR_STALE_FIELD_ACTION_VERSION` (HTTP 412). A new remedy selection supersedes the prior
    selection and rewrites `specific_accrual_cents`, so the writer must prove it observed the
    selection currently in force."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_select_remedy_with_a_stale_field_action_version_rejected
    """
    family = create_family(
        api,
        family_code="FAM-OC3",
        name="Concurrency Platform Three",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=15000000,
    )
    action = create_field_action(
        api,
        family["id"],
        action_code="FA-OC3-01",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-01-01",
        affected_build_end_date="2025-01-31",
        affected_unit_count=500,
    )
    cheap = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-OC3-CHEAP",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=1000,
        labor_hours_centi=100,
        admin_cost_cents=500,
        expected_take_rate_bps=10000,
        is_engineering_approved=True,
    )
    rich = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-OC3-RICH",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=4000,
        labor_hours_centi=100,
        admin_cost_cents=500,
        expected_take_rate_bps=10000,
        is_engineering_approved=True,
    )

    first_token = action["version"]
    standing = select_remedy(
        api, action["id"], remedy_option_id=rich["id"], expected_field_action_version=first_token
    )
    assert standing["specific_accrual_cents"] == 7000000
    assert standing["version"] == 2

    validate_error(
        api.select_remedy(
            ENGINEER_HEADERS,
            action["id"],
            expected_field_action_version=first_token,
            remedy_option_id=cheap["id"],
        ),
        ERR_STALE_FIELD_ACTION_VERSION,
        expected_status=412,
    )
    refused = read_field_action(api, action["id"])
    assert refused["selected_remedy_option_id"] == rich["id"]
    assert refused["specific_accrual_cents"] == 7000000
    assert refused["version"] == 2

    replaced = select_remedy(
        api,
        action["id"],
        remedy_option_id=cheap["id"],
        expected_field_action_version=standing["version"],
    )
    assert replaced["selected_remedy_option_id"] == cheap["id"]
    assert replaced["specific_accrual_cents"] == 5500000
    assert replaced["version"] == 3


def test_only_a_campaign_over_the_disclosure_threshold_moves_the_counter(api):
    """The counter tracks the threshold, and the snapshot freezes whatever it then held.

    PRD §3.1: "`significant_exposure_count` is the number of field actions whose
    `approved_period_id` is this period, whose `approval_state` is `APPROVED`, and whose
    `specific_accrual_cents` is at least 50,000,000 cents ...
    `requires_significant_exposure_disclosure` is true exactly when `significant_exposure_count`
    is 1 or greater. Both counters are re-derived whenever a field action of the period is
    approved." PRD §3.9 snapshots the same figure onto the rollforward alongside
    `campaign_accruals_cents`, "the sum of `specific_accrual_cents` over field actions whose
    `approved_period_id` is this period and whose `approval_state` is `APPROVED`".

    Design: Corner/cross_cutting_complexity_layers/corner_derived_significant_exposure_count_reconciles_on_every_source_change
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-SE2",
        name="Significant Exposure Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=500000000,
    )
    big = _campaign(
        api,
        family["id"],
        "FA-SE-BIG",
        10000,
        4000,
        500,
        affected_build_start_date="2025-01-01",
        affected_build_end_date="2025-03-31",
    )
    small = _campaign(
        api,
        family["id"],
        "FA-SE-SMALL",
        500,
        1000,
        500,
        affected_build_start_date="2025-08-01",
        affected_build_end_date="2025-09-30",
    )

    before = read_period(api, period["id"])
    assert before["significant_exposure_count"] == 0
    assert before["requires_significant_exposure_disclosure"] is False

    approved_big = decide_field_action(api, big["id"], "APPROVED")
    assert approved_big["specific_accrual_cents"] == 140000000
    after_big = read_period(api, period["id"])
    assert after_big["significant_exposure_count"] == 1
    assert after_big["requires_significant_exposure_disclosure"] is True

    approved_small = decide_field_action(api, small["id"], "APPROVED")
    assert approved_small["specific_accrual_cents"] == 5500000
    after_small = read_period(api, period["id"])
    assert after_small["significant_exposure_count"] == 1
    assert after_small["requires_significant_exposure_disclosure"] is True

    ledger = read_family(api, family["id"])
    assert ledger["warranty_reserve_balance_cents"] == 145500000
    assert ledger["reserve_posture"] == "NORMAL"

    locked = lock_period(api, period["id"])
    snapshot = success_data(
        api.generate_rollforward(
            CONTROLLER_HEADERS, period["id"], expected_period_version=locked["version"]
        ),
        expected_status=201,
    )
    assert snapshot["campaign_accruals_cents"] == 145500000
    assert snapshot["ending_balance_cents"] == 145500000
    assert snapshot["significant_exposure_count"] == 1


def test_an_approval_that_leaves_the_posture_normal_spares_the_proposed_accrual(api):
    """Hop four is conditional, so a proposed estimate survives the approval untouched.

    PRD §3.5: "Hop four fires only when hop three left `reserve_posture` at `CONSTRAINED`:
    every warranty accrual sitting in `PROPOSED` whose cohort belongs to this family is pushed
    back to `DRAFT`, with 1 added to its `revision_index` and its `proposed_by_user_id` cleared
    to null ... When hop three left the posture at `NORMAL` or `ELEVATED`, hop four has no
    effect at all and no accrual is touched." PRD §2.10 excludes the estimate itself from the
    ledger: "accruals in `DRAFT`, `PROPOSED` or `SUPERSEDED` contribute nothing".

    Design: Corner/cross_cutting_complexity_layers/corner_cascade_stops_short_when_the_posture_stays_normal
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    analog = _analog_basis(api)
    family = _blend_family(api, analog["id"], "FAM-PN", "Posture Normal Platform")
    cohort = create_vintage(
        api,
        family["id"],
        vintage_code="PN-MY2024",
        units_shipped=3000,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    create_failure_mode(
        api,
        family["id"],
        mode_code="FM-PN-01",
        description="Posture normal mode",
        severity="FUNCTIONAL",
        cost_per_claim_cents=30000,
    )
    accrual = create_accrual(
        api,
        period["id"],
        cohort["id"],
        method="ANALOG_BLEND",
        elapsed_exposure_bps=2000,
    )
    proposed = propose_accrual(api, accrual["id"])
    assert proposed["accrued_amount_cents"] == 2910000
    assert proposed["revision_index"] == 0

    action = _campaign(api, family["id"], "FA-PN-01", 500, 1000, 200)
    approved = decide_field_action(api, action["id"], "APPROVED")

    assert approved["approval_state"] == "APPROVED"
    assert approved["approved_period_id"] == period["id"]
    assert approved["specific_accrual_cents"] == 5350000

    ledger = read_family(api, family["id"])
    assert ledger["warranty_reserve_balance_cents"] == 5350000
    assert ledger["reserve_posture"] == "NORMAL"

    spared = read_accrual(api, accrual["id"])
    assert spared["status"] == "PROPOSED"
    assert spared["revision_index"] == 0
    assert spared["proposed_by_user_id"] == WARRANTY_ANALYST_USER_ID

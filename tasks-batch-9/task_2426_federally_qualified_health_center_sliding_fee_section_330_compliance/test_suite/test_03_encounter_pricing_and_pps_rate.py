"""The eight-step patient charge, the nominal floor, and the PPS encounter rate."""

from test_helpers import (
    ApiErrorId,
    BILLER,
    PROJECT_OFFICER,
    TWO_BAND_LADDER,
    api_client,
    create_encounter_payload,
    refresh_health_center,
    refresh_patient,
    refresh_service_site,
    same_instant,
    setup_boot_fs,
    setup_encounter,
    setup_grantee_with_adopted_schedule,
    setup_patient,
    setup_verified_patient,
    validate_error,
    validate_success,
)


def _boot_fs_with_a_verified_patient():
    ctx = setup_boot_fs()
    verified = setup_verified_patient(
        ctx,
        mrn="MRN-001",
        full_name="Ada Rivera",
        household_size=2,
        declared_annual_income_cents=2190000,
    )
    ctx.update(verified)
    return ctx


def test_nominal_floor_lifts_a_deeply_discounted_charge_up_to_the_nominal_fee():
    """A percent discount that falls below the nominal fee is raised to it.

    PRD 3.5: "Step six applies the nominal floor. If the tier's `discount_kind` is
    `PERCENT_DISCOUNT` and the raw amount has fallen below the pinned schedule's
    `nominal_fee_cents`, the raw amount is raised to the `nominal_fee_cents`, but
    still capped at `gross_charge_cents` — so a gross charge smaller than the
    nominal fee is never inflated to it."

    Design: Difficulty/combinatorial_formula/patient_charge_nominal_floor_beats_percent_discount_mode_a
    """
    ctx = _boot_fs_with_a_verified_patient()

    encounter = setup_encounter(
        ctx,
        ctx["patient_id"],
        encounter_date="2026-03-01T00:00:00Z",
        payer_type="SELF_PAY",
        gross_charge_cents=12000,
    )

    assert encounter["patient_charge_cents"] == 2500, (
        "an eighty percent discount on 12000 is 2400, which the nominal floor "
        f"raises to 2500, got {encounter['patient_charge_cents']}"
    )
    assert encounter["charge_basis"] == "SLIDING_FEE_TIER"
    assert encounter["sliding_fee_applied"] is True
    assert (
        encounter["pinned_discount_tier_id"] == ctx["tiers_by_label"]["PARTIAL_A"]["id"]
    ), "the charge is priced off the partial-discount band, not the nominal band"
    assert encounter["pps_encounter_rate_cents"] == 18000, (
        "a required-primary service at a service-delivery site attracts the full "
        f"base rate, got {encounter['pps_encounter_rate_cents']}"
    )


def test_a_percent_discount_above_the_floor_stands_and_both_charges_sum_in_the_ledger():
    """Above the floor the rounded percent discount is the charge, and the ledger accumulates.

    PRD 3.5: "When the kind is `PERCENT_DISCOUNT`, the raw amount is
    `gross_charge_cents` multiplied by the quantity one minus the tier's
    `discount_pct`, rounded half up to a whole cent." PRD 3.5 also states: "The
    patient's `patient_balance_cents` increases by the encounter's
    `patient_charge_cents` and the patient's `version` increments by one."

    Design: Difficulty/combinatorial_formula/patient_charge_nominal_floor_beats_percent_discount_mode_a
    """
    ctx = _boot_fs_with_a_verified_patient()

    setup_encounter(
        ctx,
        ctx["patient_id"],
        encounter_date="2026-03-01T00:00:00Z",
        payer_type="SELF_PAY",
        gross_charge_cents=12000,
    )
    larger = setup_encounter(
        ctx,
        ctx["patient_id"],
        encounter_date="2026-03-02T00:00:00Z",
        payer_type="SELF_PAY",
        gross_charge_cents=20000,
    )

    assert larger["patient_charge_cents"] == 4000, (
        "an eighty percent discount on 20000 is 4000, which already clears the "
        f"nominal floor, got {larger['patient_charge_cents']}"
    )
    assert larger["charge_basis"] == "SLIDING_FEE_TIER"
    assert (
        larger["pinned_discount_tier_id"] == ctx["tiers_by_label"]["PARTIAL_A"]["id"]
    )
    assert refresh_patient(ctx["patient_id"])["patient_balance_cents"] == 6500, (
        "the ledger carries 2500 from the floored encounter plus 4000 from the "
        "discounted one"
    )


def _rounding_ridge_with_a_compounded_multiplier():
    """An intermittent site and an additional service, so both reductions compound."""
    ctx = setup_grantee_with_adopted_schedule(
        legal_name="Rounding Ridge Health",
        grant_number="H80CS00428",
        pps_base_rate_cents=10003,
        site_name="Mobile Unit A",
        site_type="INTERMITTENT",
        service_code="DENTAL",
        service_category="ADDITIONAL",
        ladder=TWO_BAND_LADDER,
    )
    patient = setup_patient(mrn="MRN-201", full_name="Fay Lund", household_size=1)
    ctx.update({"patient": patient, "patient_id": patient["id"]})
    return ctx


def test_pps_rate_rounds_once_after_both_multipliers_have_compounded():
    """The rate is rounded a single time, after the product of all factors.

    PRD 3.5: "Then `pps_encounter_rate_cents` is the grantee's
    `pps_base_rate_cents` multiplied by the final multiplier, rounded half up to a
    whole cent — a single rounding, taken after all factors have multiplied, never
    once per factor."

    Design: Difficulty/combinatorial_formula/pps_rate_single_rounding_of_multiplier_product_mode_b
    """
    ctx = _rounding_ridge_with_a_compounded_multiplier()

    encounter = setup_encounter(
        ctx,
        ctx["patient_id"],
        encounter_date="2026-03-01T00:00:00Z",
        payer_type="PRIVATE",
        gross_charge_cents=30000,
    )

    assert encounter["pps_encounter_rate_cents"] == 7652, (
        "10003 times 0.85 times 0.90 is 7652.295, which rounds half up to 7652; "
        "rounding once per factor would have produced 7653, got "
        f"{encounter['pps_encounter_rate_cents']}"
    )


def test_a_third_party_payer_owes_nothing_yet_still_pins_the_covering_schedule():
    """No sliding fee logic runs for a private payer, but the schedule is still pinned.

    PRD 3.5: "Step one handles third-party payers. If `payer_type` is `MEDICARE`,
    `MEDICAID_FFS` or `PRIVATE`, then `sliding_fee_applied` is false, `charge_basis`
    is `THIRD_PARTY`, `pinned_discount_tier_id` is null, and `patient_charge_cents`
    is 0." PRD 3.5 adds of the fee-schedule selector: "The winner's identifier is
    pinned onto the encounter as `fee_schedule_id`, permanently."

    Design: Difficulty/combinatorial_formula/pps_rate_single_rounding_of_multiplier_product_mode_b
    """
    ctx = _rounding_ridge_with_a_compounded_multiplier()

    encounter = setup_encounter(
        ctx,
        ctx["patient_id"],
        encounter_date="2026-03-01T00:00:00Z",
        payer_type="PRIVATE",
        gross_charge_cents=30000,
    )

    assert encounter["patient_charge_cents"] == 0
    assert encounter["charge_basis"] == "THIRD_PARTY"
    assert encounter["sliding_fee_applied"] is False
    assert encounter["pinned_discount_tier_id"] is None
    assert encounter["fee_schedule_id"] == ctx["fee_schedule_id"], (
        "the only adopted schedule covering the date of service is pinned"
    )
    assert refresh_patient(ctx["patient_id"])["patient_balance_cents"] == 0


def test_an_encounter_at_a_suspended_site_is_refused():
    """A site out of scope cannot carry a visit.

    PRD 3.5: "The named site must have `status` equal to `IN_SCOPE`, or the request
    is rejected with `ERR_SITE_NOT_IN_SCOPE`."

    Design: Difficulty/cross_entity_state_dependency/encounter_creation_depends_on_service_site_scope_state
    """
    ctx = _boot_fs_with_a_verified_patient()

    suspended = validate_success(
        api_client.suspend_service_site(ctx["site_id"], PROJECT_OFFICER)
    )
    assert suspended["status"] == "SUSPENDED"

    validate_error(
        api_client.create_encounter(
            create_encounter_payload(
                ctx["patient_id"],
                ctx["site_id"],
                ctx["service_id"],
                encounter_date="2026-03-01T00:00:00Z",
                payer_type="SELF_PAY",
                gross_charge_cents=12000,
            ),
            BILLER,
        ),
        ApiErrorId.ERR_SITE_NOT_IN_SCOPE.value,
    )
    assert refresh_health_center(ctx["health_center_id"])["in_scope_site_count"] == 0, (
        "suspending the only in-scope site recomputes the grantee's site count"
    )
    assert refresh_patient(ctx["patient_id"])["patient_balance_cents"] == 0


def test_reinstating_the_site_restamps_in_scope_since_and_lets_the_same_visit_price():
    """Reinstatement returns the site to scope and the identical encounter succeeds.

    PRD 3.1: "The same officer may reverse it, moving the site `SUSPENDED →
    IN_SCOPE`, which re-stamps `in_scope_since` with the logical clock and again
    recomputes `in_scope_site_count` and `governance_posture` with a `version`
    increment."

    Design: Difficulty/cross_entity_state_dependency/encounter_creation_depends_on_service_site_scope_state
    """
    ctx = _boot_fs_with_a_verified_patient()
    validate_success(api_client.suspend_service_site(ctx["site_id"], PROJECT_OFFICER))

    reinstated = validate_success(
        api_client.reinstate_service_site(ctx["site_id"], PROJECT_OFFICER)
    )
    assert reinstated["status"] == "IN_SCOPE"
    assert same_instant(reinstated["in_scope_since"]) == "2026-08-01T00:00:00Z", (
        "in_scope_since is re-stamped with the logical clock, got "
        f"{reinstated['in_scope_since']}"
    )
    assert refresh_service_site(ctx["site_id"])["status"] == "IN_SCOPE"

    encounter = validate_success(
        api_client.create_encounter(
            create_encounter_payload(
                ctx["patient_id"],
                ctx["site_id"],
                ctx["service_id"],
                encounter_date="2026-03-01T00:00:00Z",
                payer_type="SELF_PAY",
                gross_charge_cents=12000,
            ),
            BILLER,
        ),
        201,
    )
    assert encounter["patient_charge_cents"] == 2500
    assert encounter["charge_basis"] == "SLIDING_FEE_TIER"
    assert (
        encounter["pinned_discount_tier_id"] == ctx["tiers_by_label"]["PARTIAL_A"]["id"]
    )
    assert refresh_health_center(ctx["health_center_id"])["in_scope_site_count"] == 1
    assert refresh_patient(ctx["patient_id"])["patient_balance_cents"] == 2500

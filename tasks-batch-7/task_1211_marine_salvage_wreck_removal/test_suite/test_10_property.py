"""Recovered property: parallel dimensions, liens, disposition, mass and capacity."""
from test_helpers import (
    ApiErrorId,
    assert_property_mass_conservation,
    assert_recovered_property,
    compute_award,
    get_success_data,
    log_property,
    make_operations_director_headers,
    register_site,
    secure_ashore,
    setup_active_contract,
    setup_completed_operation,
    setup_liened_lot,
    setup_running_phase,
    setup_verified_lot,
    survey_property,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    verify_value,
)


class TestCustodyDocumentationParallelDimensions:
    """Custody and documentation evolve independently of each other."""

    def _setup_lot(self):
        ctx = setup_active_contract(casualty_overrides={"vessel_name": "MV Pax"})
        ctx["site"] = register_site(name="Yard C", capacity_tonnes=500)
        lot = log_property(
            ctx["casualty"]["id"], property_type="CARGO",
            quantity_tonnes=40, declared_value_cents=8_000_000,
        )
        return ctx, lot

    def test_survey_leaves_custody_untouched(self, api):
        """PRD 3.8: "Valuation proceeds on the documentation dimension, which
        evolves in parallel with custody. A `MarineSurveyor` surveys the lot,
        supplying the `verified_value_cents`; the survey stamps `surveyor_id`
        with the acting surveyor's identity and moves `documentation_status`
        from `PENDING_SURVEY` to `SURVEYED`."

        Design: Difficulty/non_linear_state_machine/property_custody_documentation_parallel_dimensions
        """
        _, lot = self._setup_lot()
        assert lot["custody_status"] == "SALVED"
        assert lot["documentation_status"] == "PENDING_SURVEY"
        surveyed = survey_property(lot["id"], 7_500_000)
        assert surveyed["documentation_status"] == "SURVEYED"
        assert surveyed["custody_status"] == "SALVED", "survey does not move custody"
        assert surveyed["verified_value_cents"] == 7_500_000

    def test_secure_and_verify_leave_other_dimension_untouched(self, api):
        """PRD 3.8: "Securing sets the lot's `storage_site_id`, moves custody
        from `SALVED` to `SECURED_ASHORE`, and recomputes the site's
        `allocated_tonnes`."
        PRD 3.8: "Verification by an `OperationsDirector` then moves it from
        `SURVEYED` to `VALUE_VERIFIED` — terminal"

        Design: Difficulty/non_linear_state_machine/property_custody_documentation_parallel_dimensions
        """
        ctx, lot = self._setup_lot()
        surveyed = survey_property(lot["id"], 7_500_000)
        secured = secure_ashore(surveyed["id"], ctx["site"]["id"])
        assert secured["custody_status"] == "SECURED_ASHORE"
        assert secured["documentation_status"] == "SURVEYED", (
            "securing does not move documentation"
        )
        verified = verify_value(secured["id"])
        assert verified["documentation_status"] == "VALUE_VERIFIED"
        assert verified["custody_status"] == "SECURED_ASHORE", (
            "verification does not move custody"
        )


class TestStorageSiteAggregateCapacity:
    """Aggregate capacity: overlapping custody stacks until the sum overflows."""

    def _setup(self):
        ctx = setup_active_contract(casualty_overrides={"vessel_name": "MV Pax"})
        ctx["site"] = register_site(name="Yard D", capacity_tonnes=100)
        lot1 = log_property(ctx["casualty"]["id"], quantity_tonnes=60,
                            declared_value_cents=6_000_000)
        secure_ashore(lot1["id"], ctx["site"]["id"])
        lot2 = log_property(ctx["casualty"]["id"], property_type="BUNKERS",
                            quantity_tonnes=50, declared_value_cents=500_000)
        lot3 = log_property(ctx["casualty"]["id"], property_type="WRECK_DEBRIS",
                            quantity_tonnes=40, declared_value_cents=100_000)
        return ctx, lot2, lot3

    def test_overflowing_lot_rejected(self, api, salvage_master_headers):
        """PRD 3.8: "the site's `allocated_tonnes` plus the lot's
        `quantity_tonnes` must not exceed `capacity_tonnes`, exact equality
        passes, and overflow is rejected with `ERR_STORAGE_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/storage_site_aggregate_capacity_overlap
        """
        ctx, lot2, _ = self._setup()
        res = api.secure_ashore_property(
            lot2["id"], {"storage_site_id": ctx["site"]["id"]}, salvage_master_headers
        )
        validate_error(res, ApiErrorId.ERR_STORAGE_CAPACITY_EXCEEDED, expected_status=409)
        after = validate_success(api.get_property(lot2["id"], salvage_master_headers), 200)
        assert after["custody_status"] == "SALVED", "the rejected lot never moved"

    def test_exact_capacity_fit_accepted(self, api, salvage_master_headers):
        """PRD 3.8: "must not exceed `capacity_tonnes`, exact equality passes"
        PRD 3.8: "a site's `allocated_tonnes` is always the sum of
        `quantity_tonnes` over the lots naming that site in `storage_site_id`
        whose custody is `SECURED_ASHORE` or `LIENED`."

        Design: Difficulty/resource_temporal_overlap/storage_site_aggregate_capacity_overlap
        """
        ctx, lot2, lot3 = self._setup()
        validate_error(
            api.secure_ashore_property(
                lot2["id"], {"storage_site_id": ctx["site"]["id"]}, salvage_master_headers
            ),
            ApiErrorId.ERR_STORAGE_CAPACITY_EXCEEDED,
            expected_status=409,
        )
        secured = validate_success(
            api.secure_ashore_property(
                lot3["id"], {"storage_site_id": ctx["site"]["id"]}, salvage_master_headers
            ),
            200,
        )
        assert secured["custody_status"] == "SECURED_ASHORE", "60 + 40 == 100: exact fit passes"
        site = validate_success(api.get_storage_site(ctx["site"]["id"], salvage_master_headers), 200)
        assert site["allocated_tonnes"] == 100


class TestPropertyMassConservation:
    """Mass buckets conserve quantity across a partial-disposition sequence."""

    def _setup(self):
        ctx = setup_completed_operation(casualty_overrides={
            "vessel_name": "MV Kara", "casualty_type": "SUNK",
            "declared_salved_value_cents": 800_000_000, "position": "32N 64W",
        })
        lot = setup_verified_lot(
            ctx, quantity_tonnes=100, declared_value_cents=5_000_000
        )
        return ctx, lot

    def test_partial_scraps_keep_custody_and_conserve_mass(self, api, salvage_master_headers):
        """PRD 3.8: "Each disposition credits the method's bucket —
        `redelivered_tonnes`, `sold_tonnes`, or `disposed_tonnes` — and draws
        `in_custody_tonnes` down by the same amount, preserving the mass
        invariant of §2.6. A partial disposition leaves custody in
        `SECURED_ASHORE`"

        Design: Difficulty/compensating_invariant/property_disposition_converses_mass
        """
        _, lot = self._setup()
        step1 = validate_success(
            api.dispose_property(lot["id"], {"method": "SCRAP", "tonnes": 25},
                                 salvage_master_headers),
            200,
        )
        assert step1["disposed_tonnes"] == 25
        assert step1["in_custody_tonnes"] == 75
        assert step1["custody_status"] == "SECURED_ASHORE", "partial — not terminal"
        assert_property_mass_conservation(step1)

        step2 = validate_success(
            api.dispose_property(lot["id"], {"method": "SCRAP", "tonnes": 40},
                                 salvage_master_headers),
            200,
        )
        assert step2["disposed_tonnes"] == 65
        assert step2["in_custody_tonnes"] == 35
        assert step2["custody_status"] == "SECURED_ASHORE"
        assert_property_mass_conservation(step2)

    def test_zeroing_call_sets_terminal_custody_to_its_method(
        self, api, salvage_master_headers
    ):
        """PRD 3.8: "the lot reaches terminal custody exactly when a dispose
        call zeroes `in_custody_tonnes`, and the terminal state takes the method
        of that zeroing call — `REDELIVERED`, `SOLD`, or `DISPOSED`
        respectively."
        PRD 2.6: "For recovered property, a lot's `quantity_tonnes` always
        equals the sum of its `redelivered_tonnes`, `sold_tonnes`,
        `disposed_tonnes`, and `in_custody_tonnes`"

        Design: Difficulty/compensating_invariant/property_disposition_converses_mass
        """
        _, lot = self._setup()
        api.dispose_property(lot["id"], {"method": "SCRAP", "tonnes": 25}, salvage_master_headers)
        api.dispose_property(lot["id"], {"method": "SCRAP", "tonnes": 40}, salvage_master_headers)
        step3 = validate_success(
            api.dispose_property(lot["id"], {"method": "SCRAP", "tonnes": 35},
                                 salvage_master_headers),
            200,
        )
        assert step3["disposed_tonnes"] == 100
        assert step3["in_custody_tonnes"] == 0
        assert step3["custody_status"] == "DISPOSED", "the zeroing call's method wins"
        assert_property_mass_conservation(step3)


def test_sod_verify_value_by_same_surveyor_rejected(
    api, operations_director_headers, salvage_master_headers
):
    """PRD 3.8: "Verification by an `OperationsDirector` then moves it from
    `SURVEYED` to `VALUE_VERIFIED` — terminal — under the segregation-of-duties
    rule that the verifier must differ from the recorded `surveyor_id`
    (`ERR_SOD_VIOLATION`)."

    Design: Corner/validations/sod_verify_value_by_same_surveyor_rejected
    """
    ctx = setup_active_contract(casualty_overrides={"vessel_name": "MV Pax"})
    lot = log_property(
        ctx["casualty"]["id"], property_type="CARGO",
        quantity_tonnes=10, declared_value_cents=9_000_000,
    )
    surveyed = survey_property(lot["id"], 9_000_000)
    assert surveyed["surveyor_id"] == "surveyor-02"
    # The surveying operator, acting in the director capacity, cannot verify.
    res = api.verify_value_property(
        lot["id"], make_operations_director_headers("surveyor-02")
    )
    validate_error(res, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)
    verified = validate_success(
        api.verify_value_property(lot["id"], operations_director_headers), 200
    )
    assert verified["documentation_status"] == "VALUE_VERIFIED"


def test_dispose_tonnage_overshoot_rejected(api, salvage_master_headers, contracts_officer_headers):
    """PRD 3.8: "All branches require the lot to be disposition-eligible — the
    casualty in `OPERATIONS_COMPLETE`, or the contract `TERMINATED` — and
    tonnage within reach: `tonnes` greater than the lot's `in_custody_tonnes` is
    rejected with `ERR_QUANTITY_EXCEEDS_REMAINING`."

    Design: Corner/validations/dispose_tonnage_overshoot_rejected
    """
    ctx = setup_active_contract(casualty_overrides={
        "vessel_name": "MV Kara", "casualty_type": "SUNK",
        "declared_salved_value_cents": 800_000_000, "position": "32N 64W",
    })
    ctx["site"] = register_site(name="Yard A", capacity_tonnes=1000)
    lot = log_property(
        ctx["casualty"]["id"], property_type="WRECK_DEBRIS",
        quantity_tonnes=10, declared_value_cents=100_000,
    )
    secure_ashore(lot["id"], ctx["site"]["id"])
    survey_property(lot["id"], 100_000)
    # No-cure termination makes the lot disposition-eligible.
    validate_success(
        api.terminate_contract(ctx["contract"]["id"], {"reason": "NO_CURE"},
                               contracts_officer_headers),
        200,
    )
    res = api.dispose_property(
        lot["id"], {"method": "SCRAP", "tonnes": 11}, salvage_master_headers
    )
    validate_error(res, ApiErrorId.ERR_QUANTITY_EXCEEDS_REMAINING, expected_status=422)
    after = validate_success(api.get_property(lot["id"], salvage_master_headers), 200)
    assert after["in_custody_tonnes"] == 10
    assert_property_mass_conservation(after)


def test_redeliver_while_liened_rejected(api, salvage_master_headers):
    """PRD 3.8: "Redelivery requires `documentation_status` `VALUE_VERIFIED` and
    is only defined from `SECURED_ASHORE`; attempting it while the lot is liened
    meets `ERR_LIEN_ACTIVE`."
    PRD 2.7: "Priority 5 covers state permission: an action whose target is in
    the wrong from-state is rejected with `ERR_INVALID_STATE_TRANSITION`" — the
    PRD names the lien gate for this attempt while its pipeline tiers put the
    from-state rejection first, so either named rejection is conformant.

    Design: Corner/validations/redeliver_while_liened_rejected
    """
    ctx = setup_running_phase(casualty_overrides={
        "vessel_name": "MV Kara", "casualty_type": "SUNK",
        "declared_salved_value_cents": 800_000_000, "position": "32N 64W",
    })
    lot = setup_liened_lot(ctx, lien_amount_cents=5_000_000, quantity_tonnes=50,
                           declared_value_cents=9_000_000)
    assert lot["custody_status"] == "LIENED"
    res = api.dispose_property(
        lot["id"], {"method": "REDELIVER", "tonnes": 50}, salvage_master_headers
    )
    validate_error_is_one_of(
        res, [ApiErrorId.ERR_INVALID_STATE_TRANSITION, ApiErrorId.ERR_LIEN_ACTIVE]
    )
    after = validate_success(api.get_property(lot["id"], salvage_master_headers), 200)
    assert after["custody_status"] == "LIENED"
    assert after["lien_amount_cents"] == 5_000_000


def test_sell_without_award_paid_rejected(api, salvage_master_headers):
    """PRD 3.8: "An ordinary sale from `SECURED_ASHORE` requires
    `VALUE_VERIFIED` and requires the casualty's contract award to be `PAID` —
    the lien satisfied — otherwise `ERR_LIEN_ACTIVE`"

    Design: Corner/validations/sell_without_award_paid_rejected
    """
    ctx = setup_completed_operation(casualty_overrides={
        "vessel_name": "MV Kara", "casualty_type": "SUNK",
        "declared_salved_value_cents": 800_000_000, "position": "32N 64W",
    })
    lot = setup_verified_lot(ctx, quantity_tonnes=50, declared_value_cents=9_000_000)
    award = compute_award(ctx["contract"]["id"])
    assert award["status"] == "COMPUTED", "award computed but not paid"
    res = api.dispose_property(
        lot["id"], {"method": "SELL", "tonnes": 50}, salvage_master_headers
    )
    validate_error(res, ApiErrorId.ERR_LIEN_ACTIVE, expected_status=422)
    after = validate_success(api.get_property(lot["id"], salvage_master_headers), 200)
    assert after["custody_status"] == "SECURED_ASHORE"


def test_lien_sale_after_no_cure_termination(api, salvage_master_headers, contracts_officer_headers):
    """PRD 3.8: "a lien sale from `LIENED` is lawful only when the contract is
    `TERMINATED`, otherwise `ERR_LIEN_ACTIVE`, and likewise requires
    `VALUE_VERIFIED`."
    PRD 3.8: "A terminal lien sale also zeroes `lien_amount_cents`"

    Design: Corner/validations/lien_sale_after_no_cure_termination
    """
    ctx = setup_running_phase(casualty_overrides={
        "vessel_name": "MV Kara", "casualty_type": "SUNK",
        "declared_salved_value_cents": 800_000_000, "position": "32N 64W",
    })
    lot = setup_liened_lot(ctx, lien_amount_cents=5_000_000, quantity_tonnes=50,
                           declared_value_cents=9_000_000)
    assert lot["custody_status"] == "LIENED"
    validate_success(
        api.terminate_contract(ctx["contract"]["id"], {"reason": "NO_CURE"},
                               contracts_officer_headers),
        200,
    )
    sold = validate_success(
        api.dispose_property(lot["id"], {"method": "SELL", "tonnes": 50},
                             salvage_master_headers),
        200,
    )
    assert_recovered_property(sold)
    assert sold["custody_status"] == "SOLD", "lien sale permitted once the contract terminated"
    assert sold["lien_amount_cents"] == 0, "terminal lien sale zeroes the lien"
    assert sold["sold_tonnes"] == 50
    assert sold["in_custody_tonnes"] == 0
    assert_property_mass_conservation(sold)

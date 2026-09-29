"""The trademark dimension: registration effects, and its orthogonality."""

from test_helpers import (
    BREEDER,
    COORDINATOR,
    advance_clock,
    assert_instant_equals,
    brand_register_payload,
    brand_renew_payload,
    create_trial_site,
    create_variety,
    create_variety_trial_payload,
    validate_success,
)


class TestRegisteringTheMarkAppliesEveryDeclaredEffect:
    """One call writes three payload fields, stamps one clock field, moves one
    dimension, and leaves everything else exactly alone."""

    def _variety_at_the_tenth(self, api):
        variety = create_variety(
            api, denomination="Sable Bramble", species="Rubus idaeus",
            breeder_code="SB", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        advance_clock(api, "2026-08-10T00:00:00Z")
        return variety

    def test_the_three_payload_fields_and_the_stamped_instant_all_land(self, api):
        """The mark text, its Nice class and the next renewal instant are copied
        from the request, while the registration instant comes from the logical
        clock rather than from the caller.

        PRD 3.3: "Registration drives `BRAND_NONE → BRAND_REGISTERED`, writes `brand_mark_text`, `brand_registry_class` and `brand_renewal_due_at` from the payload, stamps `brand_registered_on` with the logical clock's present instant, and increments the variety's `version`."

        Design: Corner/state_machines/brand_register_applies_every_declared_side_effect
        """
        variety = self._variety_at_the_tenth(api)

        registered = validate_success(
            api.brand_register_variety(
                variety["id"],
                brand_register_payload(
                    brand_mark_text="SABLECREST", brand_registry_class=31,
                    brand_renewal_due_at="2026-09-01T00:00:00Z",
                ),
                BREEDER,
            )
        )
        assert registered["brand_status"] == "BRAND_REGISTERED"
        assert registered["brand_mark_text"] == "SABLECREST"
        assert registered["brand_registry_class"] == 31
        assert_instant_equals(
            registered["brand_renewal_due_at"], "2026-09-01T00:00:00Z",
            "brand_renewal_due_at",
        )
        assert_instant_equals(
            registered["brand_registered_on"], "2026-08-10T00:00:00Z",
            "brand_registered_on",
        )
        assert registered["version"] == 2

    def test_a_first_registration_is_not_a_renewal_and_moves_no_other_dimension(self, api):
        """The lap counter stays at zero because no renewal term has turned, and
        the candidate lifecycle and unprotected posture are untouched.

        PRD 3.3: "Nothing about `lifecycle_state`, `protection_posture` or `protected_jurisdictions` moves: a `CANDIDATE` variety may perfectly well hold a registered mark."

        Design: Corner/state_machines/brand_register_applies_every_declared_side_effect
        """
        variety = self._variety_at_the_tenth(api)

        validate_success(
            api.brand_register_variety(
                variety["id"], brand_register_payload(brand_mark_text="SABLECREST"), BREEDER
            )
        )

        refreshed = validate_success(api.get_variety(variety["id"], BREEDER))
        assert refreshed["brand_renewal_count"] == 0
        assert refreshed["lifecycle_state"] == "CANDIDATE"
        assert refreshed["protection_posture"] == "UNPROTECTED"
        assert refreshed["protected_jurisdictions"] == []


class TestTheTwoDimensionsAdvanceOnUnrelatedTriggers:
    """Planting moves the lifecycle; the sweep moves the brand."""

    def _branded_variety_in_trial(self, api):
        variety = create_variety(
            api, denomination="Yarrow Bramble", species="Rubus idaeus",
            breeder_code="YB", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        validate_success(
            api.brand_register_variety(
                variety["id"],
                brand_register_payload(
                    brand_mark_text="YARROWCREST", brand_registry_class=31,
                    brand_renewal_due_at="2026-09-01T00:00:00Z",
                ),
                BREEDER,
            )
        )
        site = create_trial_site(api, site_name="Yarrow Station", region_code="PNW",
                                 plot_capacity=60)
        trial = validate_success(
            api.create_variety_trial(
                create_variety_trial_payload(
                    variety["id"], site["id"], plot_count=10,
                    plant_date="2026-08-05T00:00:00Z",
                    harvest_date="2026-09-20T00:00:00Z",
                ),
                COORDINATOR,
            ),
            201,
        )
        advance_clock(api, "2026-08-05T00:00:00Z", COORDINATOR)
        validate_success(api.plant_variety_trial(trial["id"], COORDINATOR))
        return variety, trial

    def test_planting_moves_the_lifecycle_and_leaves_the_mark_registered(self, api):
        """A trialing event has nothing to say about the trademark, so the brand
        dimension holds its state while the lifecycle advances.

        PRD 2.9: "Neither dimension constrains the other."

        Design: Corner/state_machines/variety_lifecycle_and_brand_dimensions_advance_independently
        """
        variety, _trial = self._branded_variety_in_trial(api)

        refreshed = validate_success(api.get_variety(variety["id"], BREEDER))
        assert refreshed["lifecycle_state"] == "IN_TRIAL"
        assert refreshed["brand_status"] == "BRAND_REGISTERED"

    def test_the_sweep_moves_only_the_brand_when_the_renewal_instant_arrives(self, api):
        """Advancing to the renewal instant is reported by the brand counter and
        moves the mark into its due state, while the lifecycle stays in trialing
        and the renewal lap counter has not turned.

        PRD 3.3: "When the logical clock reaches or passes `brand_renewal_due_at`, the sweep moves the variety `BRAND_REGISTERED → BRAND_RENEWAL_DUE` and increments its `version`."

        Design: Corner/state_machines/variety_lifecycle_and_brand_dimensions_advance_independently
        """
        variety, _trial = self._branded_variety_in_trial(api)

        sweep = advance_clock(api, "2026-09-01T00:00:00Z")
        assert sweep["brand_renewal_due_count"] == 1

        refreshed = validate_success(api.get_variety(variety["id"], BREEDER))
        assert refreshed["brand_status"] == "BRAND_RENEWAL_DUE"
        assert refreshed["lifecycle_state"] == "IN_TRIAL"
        assert refreshed["brand_renewal_count"] == 0

    def test_renewing_the_mark_turns_only_the_brand_lap_counter(self, api):
        """Restating the mark with a fresh term returns the brand to registered
        and counts one completed lap, again without disturbing the lifecycle.

        PRD 3.3: "Renewal drives `BRAND_RENEWAL_DUE → BRAND_REGISTERED`, writes the new `brand_renewal_due_at`, re-stamps `brand_registered_on` with the present instant, increments `brand_renewal_count` by 1, and increments the variety's `version`."

        Design: Corner/state_machines/variety_lifecycle_and_brand_dimensions_advance_independently
        """
        variety, _trial = self._branded_variety_in_trial(api)
        advance_clock(api, "2026-09-01T00:00:00Z")

        renewed = validate_success(
            api.brand_renew_variety(
                variety["id"],
                brand_renew_payload(
                    brand_mark_text="YARROWCREST",
                    brand_renewal_due_at="2027-09-01T00:00:00Z",
                ),
                BREEDER,
            )
        )
        assert renewed["brand_status"] == "BRAND_REGISTERED"
        assert renewed["brand_renewal_count"] == 1
        assert_instant_equals(
            renewed["brand_registered_on"], "2026-09-01T00:00:00Z", "brand_registered_on"
        )
        assert renewed["lifecycle_state"] == "IN_TRIAL"

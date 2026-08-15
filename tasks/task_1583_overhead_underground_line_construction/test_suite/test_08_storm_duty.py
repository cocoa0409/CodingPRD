"""Storm duty: standby/call-out premium pay variants, one-active-activation
exclusivity, and the computed crew status across the storm lifecycle."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_storm_activation,
    create_storm_activation_payload,
    get_success_data,
    setup_active_contract,
    setup_storm_activation,
    validate_error,
    validate_success,
)
from test_helpers import create_crew_payload

PM = TEST_USERS["contractor_pm_headers"]
DISPATCHER = TEST_USERS["utility_dispatcher_headers"]


def _storm_contract(api, contract_number, crew_code, crew_type="STORM",
                    base_rate=60.00):
    """ACTIVE contract with one bid item and one crew. Returns (contract, crew)."""
    contract, _ = setup_active_contract(
        contract_overrides={"contract_number": contract_number},
        bid_item_overrides={"item_code": "UG-CONDUCE-4IN",
                            "description": "4in conduit", "unit": "LF",
                            "unit_price": 12.00, "estimated_quantity": 500})
    crew = get_success_data(api.create_crew(
        create_crew_payload(crew_code=crew_code, crew_type=crew_type,
                            base_rate_per_hour=base_rate), PM))
    return contract, crew


class TestPremiumPayVariants:
    def test_standby_convert_premium_pay(self, api):
        """PRD §3.7: "A standby-convert — created as `STANDBY` and later
        converted — credits `hours_standby` at one half of the crew's
        `base_rate_per_hour` plus `hours_worked` at double that rate, each
        component rounded half-up to two decimal places separately before being
        summed, with no minimum-hours guarantee; identical worked hours
        therefore price differently under the two variants."
        6 standby hours at 0.5 x 60.00 = 180.00 plus 3 worked hours at
        2.0 x 60.00 = 360.00 yields 540.00.

        Design: Difficulty/dual_variant_calc/standby_convert_vs_pure_callout_premium
        """
        contract, crew = _storm_contract(api, "C-200", "CR-S")
        activation = setup_storm_activation(contract["id"], crew["id"],
                                            kind="STANDBY",
                                            activation_date="2026-08-05")
        converted = get_success_data(
            api.convert_storm_activation(activation["id"], DISPATCHER))
        assert converted["kind"] == "CALLOUT"
        assert converted["converted"] is True, (
            "Converting sets kind to CALLOUT and converted to true")

        closed = validate_success(api.close_storm_activation(
            activation["id"], {"hours_standby": 6, "hours_worked": 3},
            DISPATCHER))
        assert_storm_activation(closed)
        assert closed["status"] == "CLOSED"
        assert closed["premium_pay"] == pytest.approx(540.00, abs=0.01), (
            "standby_convert: round(6 x 0.5 x 60, 2) + round(3 x 2.0 x 60, 2) "
            "= 180.00 + 360.00 = 540.00")

    def test_pure_callout_premium_pay_four_hour_minimum(self, api):
        """PRD §3.7: "A pure call-out — created as `CALLOUT` and never converted
        — credits the greater of `hours_worked` and four hours at double the
        crew's `base_rate_per_hour`, rounded half-up to two decimal places;
        standby hours are not credited in this variant, so the four-hour minimum
        is a pure call-out guarantee."
        3 worked hours fall below the four-hour minimum: max(3, 4) x 2.0 x
        60.00 = 480.00.

        Design: Difficulty/dual_variant_calc/standby_convert_vs_pure_callout_premium
        """
        contract, crew = _storm_contract(api, "C-200", "CR-C")
        activation = setup_storm_activation(contract["id"], crew["id"],
                                            kind="CALLOUT",
                                            activation_date="2026-08-05")
        assert activation["converted"] is False

        closed = validate_success(api.close_storm_activation(
            activation["id"], {"hours_standby": 0, "hours_worked": 3},
            DISPATCHER))
        assert_storm_activation(closed)
        assert closed["status"] == "CLOSED"
        assert closed["premium_pay"] == pytest.approx(480.00, abs=0.01), (
            "pure_callout: round(max(3, 4) x 2.0 x 60, 2) = 480.00; "
            "identical worked hours price differently than standby_convert")


class TestStormExclusivity:
    def test_duplicate_active_storm_activation_rejected(self, api):
        """PRD §3.7: "A crew may hold at most one `ACTIVE` activation at a time;
        a second activation for the same crew is rejected with
        `ERR_DUPLICATE_ACTIVE_STANDBY`."

        Design: Corner/validations/duplicate_active_storm_activation_rejected
        """
        contract, crew = _storm_contract(api, "CV-6", "CR-DS", base_rate=55.00)
        setup_storm_activation(contract["id"], crew["id"], kind="STANDBY")

        resp = api.create_storm_activation(
            contract["id"],
            create_storm_activation_payload(crew["id"], kind="CALLOUT"),
            DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_STANDBY)


class TestCrewStatusDerivation:
    def test_crew_status_through_storm_lifecycle(self, api):
        """PRD §3.2: "At registration both kinds of resource compute their status
        as `AVAILABLE`."
        PRD §3.2: "A crew reads `CALLOUT` when an `ACTIVE` storm activation of
        kind `CALLOUT` references it; failing that, `STANDBY` when an `ACTIVE`
        storm activation of kind `STANDBY` references it; failing that,
        `ASSIGNED` when an `ACTIVE` assignment covers it from its first through
        its last working date inclusive, measured against the logical clock's
        date; otherwise `AVAILABLE`."
        PRD §3.7: "converting requires the activation's `kind` to be `STANDBY` —
        attempting to convert a call-out fails with `ERR_INVALID_STATE` — and
        sets `kind` to `CALLOUT` and `converted` to true, with the crew's status
        recomputed from `STANDBY` to `CALLOUT`."
        PRD §3.7: "The dispatcher closes with `hours_standby` and `hours_worked`,
        each at least zero, and the system computes `premium_pay` before resting
        the activation in `CLOSED` and recomputing the crew's status."

        Design: Corner/entities/crew_status_derivation_through_storm_lifecycle
        """
        contract, crew = _storm_contract(api, "CD-6", "CR-L", base_rate=55.00)

        at_creation = validate_success(api.get_crew(crew["id"], PM))
        assert at_creation["status"] == "AVAILABLE", (
            "At registration the crew computes AVAILABLE")

        activation = setup_storm_activation(contract["id"], crew["id"],
                                            kind="STANDBY",
                                            activation_date="2026-08-05")
        on_standby = validate_success(api.get_crew(crew["id"], PM))
        assert on_standby["status"] == "STANDBY", (
            "An ACTIVE STANDBY activation turns the crew STANDBY")

        get_success_data(api.convert_storm_activation(activation["id"], DISPATCHER))
        on_callout = validate_success(api.get_crew(crew["id"], PM))
        assert on_callout["status"] == "CALLOUT", (
            "Conversion recomputes the crew from STANDBY to CALLOUT")
        activation_mid = validate_success(
            api.get_storm_activation(activation["id"], PM))
        assert activation_mid["converted"] is True

        closed = get_success_data(api.close_storm_activation(
            activation["id"], {"hours_standby": 2, "hours_worked": 5},
            DISPATCHER))
        assert closed["status"] == "CLOSED"
        after_close = validate_success(api.get_crew(crew["id"], PM))
        assert after_close["status"] == "AVAILABLE", (
            "With no ACTIVE activation or covering assignment the crew returns "
            "to AVAILABLE")

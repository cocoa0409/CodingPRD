"""Validation rules guarding the radio-frequency plant.

Every test in this module drives one refusal (or one deliberate acceptance) that
PRD.md states in prose: the four natural keys of PRD 3.1, 3.2 and 3.5, the
inter-site rule of PRD 3.4, the spectrum envelope of PRD 3.2, and the rejection
ladder of PRD 2.7.

The harness restarts the API and empties the database before every test, so each
test builds the whole world it needs from the published endpoints.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    activate_sector,
    assert_no_mutation,
    assert_sector,
    assert_spectrum_license,
    assert_tower,
    create_backhaul_circuit_payload,
    create_sector,
    create_sector_payload,
    create_service_plan_payload,
    create_spectrum_license,
    create_spectrum_license_payload,
    create_tower,
    create_tower_payload,
    get_sector,
    get_spectrum_license,
    setup_active_plant,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------
# Local composites (built only from published endpoints)
# --------------------------------------------------------------------------


def _setup_two_active_sectors_on_one_tower() -> dict:
    """One ACTIVE tower carrying two ACTIVE sectors bound to the same licence.

    The second sector sits at azimuth 270.0 against the first sector's 90.0, so
    the two boresights are 180 degrees apart.
    """
    scenario = setup_active_plant()
    second = create_sector(
        scenario["tower"]["id"],
        scenario["license"]["id"],
        azimuth_deg=270.0,
        channel_center_mhz=3620.0,
        channel_width_mhz=10.0,
    )
    scenario["second_sector"] = activate_sector(second["id"])
    return scenario


# --------------------------------------------------------------------------
# Natural-key uniqueness on the four creation endpoints
# --------------------------------------------------------------------------


class TestNaturalKeyUniqueness:
    def test_second_tower_reusing_a_site_code_is_rejected(self, api, network_engineer):
        """PRD 3.1: "Registration records the operator's own `site_code` as printed on the tower placard — between 4
        and 32 characters inclusive, and unique across all towers with case treated as
        significant, so `RB-NORTH-01` and `rb-north-01` are two different sites."
        PRD 3.1: "A second tower attempting to reuse an existing code is refused
        with `ERR_DUPLICATE_SITE_CODE`."

        Design: Corner/validations/duplicate_natural_keys_are_rejected_on_all_four_creation_endpoints
        """
        first = create_tower(site_code="RB-TWR-0001")
        assert_tower(first)

        response = api.create_tower(
            create_tower_payload(
                site_code="RB-TWR-0001",
                latitude=42.0,
                longitude=-105.5,
                ground_elevation_m=1400.0,
                antenna_agl_m=30.0,
                lease_landowner_name="Other Ranch LLC",
                lease_monthly_base_rent_cents=39000,
                lease_escalator_pct=0.03,
                lease_start_date="2024-01-01",
                lease_term_months=36,
            ),
            network_engineer,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_SITE_CODE.value)

    def test_site_code_uniqueness_treats_case_as_significant(self, api, network_engineer):
        """PRD 3.1: "Registration records the operator's own `site_code` as printed on the tower placard — between 4
        and 32 characters inclusive, and unique across all towers with case treated as
        significant, so `RB-NORTH-01` and `rb-north-01` are two different sites."

        Design: Corner/validations/duplicate_natural_keys_are_rejected_on_all_four_creation_endpoints
        """
        upper = create_tower(site_code="RB-NORTH-01")
        response = api.create_tower(
            create_tower_payload(site_code="rb-north-01"), network_engineer
        )
        lower = validate_success(response, 201)
        assert lower["site_code"] == "rb-north-01"
        assert lower["id"] != upper["id"], (
            "`RB-NORTH-01` and `rb-north-01` are two different sites"
        )

    @pytest.mark.parametrize("second_circuit_on_same_tower", [True, False])
    def test_second_circuit_reusing_a_circuit_ref_is_rejected(
        self, api, network_engineer, second_circuit_on_same_tower
    ):
        """PRD 3.1: "A `circuit_ref` already in use on another circuit is refused
        with `ERR_DUPLICATE_CIRCUIT_REF`."

        Design: Corner/validations/duplicate_natural_keys_are_rejected_on_all_four_creation_endpoints
        """
        first_tower = create_tower()
        other_tower = create_tower()
        first = validate_success(
            api.create_backhaul_circuit(
                create_backhaul_circuit_payload(
                    first_tower["id"], circuit_ref="PF-CIR-8801"
                ),
                network_engineer,
            ),
            201,
        )
        assert first["circuit_ref"] == "PF-CIR-8801"

        target = first_tower if second_circuit_on_same_tower else other_tower
        response = api.create_backhaul_circuit(
            create_backhaul_circuit_payload(
                target["id"],
                carrier_name="Second Carrier",
                circuit_ref="PF-CIR-8801",
                committed_mbps=200,
                monthly_cost_cents=80000,
            ),
            network_engineer,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_CIRCUIT_REF.value)

    def test_second_licence_reusing_a_license_ref_is_rejected(self, api, network_engineer):
        """PRD 3.2: "A licence carries the regulator's `license_ref`, unique across
        all licences and refused with `ERR_DUPLICATE_LICENSE_REF` when reused; a
        `band` drawn from `CBRS_3_5GHZ`, `EBS_2_5GHZ` and `LTE_700MHZ`; the block's
        `channel_center_mhz` between 600.0 and 6000.0 inclusive to one decimal
        place; its `channel_width_mhz` between 5.0 and 200.0 inclusive to one
        decimal place; the `max_eirp_dbm` ceiling between 20.0 and 65.0 inclusive
        to one decimal place; the regulator's `license_area_code`; and a validity
        window given as an inclusive `effective_from` and an exclusive
        `effective_to`, where `effective_to` must be strictly later than
        `effective_from`."

        Design: Corner/validations/duplicate_natural_keys_are_rejected_on_all_four_creation_endpoints
        """
        first = create_spectrum_license(license_ref="CBRS-PAL-4412")
        assert_spectrum_license(get_spectrum_license(first["id"]))

        response = api.create_spectrum_license(
            create_spectrum_license_payload(
                license_ref="CBRS-PAL-4412",
                band="LTE_700MHZ",
                channel_center_mhz=700.0,
                channel_width_mhz=10.0,
                max_eirp_dbm=55.0,
                license_area_code="WY-022",
                effective_from="2026-01-01T00:00:00Z",
                effective_to="2031-01-01T00:00:00Z",
            ),
            network_engineer,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_LICENSE_REF.value)

    def test_second_plan_reusing_a_tier_code_is_rejected(self, api, capacity_planner):
        """PRD 3.5: "A plan carries a `tier_code` unique across the catalogue and
        refused with `ERR_DUPLICATE_TIER_CODE` when reused; `downstream_mbps` and
        `upstream_mbps`, both whole numbers of at least 1; `monthly_price_cents`,
        not negative; a `soft_cap_gb` monthly fair-use allowance, strictly greater
        than zero to one decimal place; a `deprioritization_factor` between 0.05
        and 1.0 inclusive to two decimal places, being the fraction of downstream
        rate the account retains once it has passed its allowance; an
        `sla_uptime_pct` commitment between 90.0 and 100.0 inclusive to three
        decimal places; an `sla_credit_method` of either `SLA_SHORTFALL` or
        `PER_INCIDENT`, which decides how outage compensation is computed for
        accounts on the plan; and an `equipment_policy` of `RENTAL_ONLY`,
        `PURCHASE_ONLY` or `RENTAL_OR_PURCHASE`, which decides how the customer
        premises radio may be acquired."

        Design: Corner/validations/duplicate_natural_keys_are_rejected_on_all_four_creation_endpoints
        """
        first = validate_success(
            api.create_service_plan(
                create_service_plan_payload(tier_code="STD50"), capacity_planner
            ),
            201,
        )
        assert first["tier_code"] == "STD50"

        response = api.create_service_plan(
            create_service_plan_payload(
                tier_code="STD50",
                downstream_mbps=100,
                upstream_mbps=20,
                monthly_price_cents=9999,
                soft_cap_gb=900.0,
                deprioritization_factor=0.5,
                sla_uptime_pct=99.0,
                sla_credit_method="PER_INCIDENT",
                equipment_policy="RENTAL_ONLY",
            ),
            capacity_planner,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_TIER_CODE.value)


# --------------------------------------------------------------------------
# Coordination is an inter-site protocol
# --------------------------------------------------------------------------


def test_coordination_between_two_sectors_of_one_tower_is_rejected(api, network_engineer):
    """PRD 3.4: "Coordination is between towers, never within one."
    PRD 3.4: "If the two named sectors share a `tower_id` the request is refused with
    `ERR_SAME_TOWER_COORDINATION` — intra-site channel planning is an internal matter and needs
    no negotiation."

    Design: Corner/validations/coordination_between_two_sectors_of_the_same_tower_is_rejected
    """
    scenario = _setup_two_active_sectors_on_one_tower()
    requester = scenario["sector"]
    neighbor = scenario["second_sector"]
    assert requester["tower_id"] == neighbor["tower_id"]
    assert requester["id"] != neighbor["id"]

    response = api.create_coordination(
        {
            "requesting_sector_id": requester["id"],
            "neighbor_sector_id": neighbor["id"],
            "proposed_channel_center_mhz": 3565.0,
            "proposed_channel_width_mhz": 10.0,
            "proposed_eirp_dbm": 44.0,
            "guard_band_mhz": 2.0,
            "effective_from": "2026-08-15T00:00:00Z",
        },
        network_engineer,
    )
    validate_error(response, ApiErrorId.ERR_SAME_TOWER_COORDINATION.value)

    rows, meta = validate_paginated(
        api.list_sector_coordinations(requester["id"], network_engineer)
    )
    assert meta["total_count"] == 0, "a refused coordination must not be recorded"
    assert rows == []

    assert_no_mutation(requester, get_sector(requester["id"]), "requesting sector")
    assert_no_mutation(neighbor, get_sector(neighbor["id"]), "neighbour sector")


# --------------------------------------------------------------------------
# The spectrum envelope: power, channel edges, and clock effectivity
# --------------------------------------------------------------------------


class TestLicenceEnvelope:
    def test_sector_creation_rejects_radiated_power_above_the_licence_ceiling(
        self, api, network_engineer
    ):
        """PRD 3.2: "Sector construction is where the spectrum envelope is first
        enforced. The derived `eirp_dbm` must not exceed the bound licence's
        `max_eirp_dbm`, else the creation is refused with
        `ERR_EIRP_EXCEEDS_LICENSE`."
        PRD 3.2: "`eirp_dbm` is `tx_power_dbm` plus `antenna_gain_dbi`, rounded to
        one decimal place."

        Design: Corner/validations/licence_envelope_is_enforced_on_power_on_channel_and_on_effectivity
        """
        tower = create_tower()
        license_record = get_spectrum_license(create_spectrum_license()["id"])
        assert license_record["max_eirp_dbm"] == 47.0

        response = api.create_sector(
            create_sector_payload(
                tower["id"],
                license_record["id"],
                tx_power_dbm=35.0,
                antenna_gain_dbi=17.0,
            ),
            network_engineer,
        )
        validate_error(response, ApiErrorId.ERR_EIRP_EXCEEDS_LICENSE.value)

        _, meta = validate_paginated(
            api.list_sectors(network_engineer, params={"tower_id": tower["id"]})
        )
        assert meta["total_count"] == 0, "a refused sector must not be created"

    def test_sector_creation_accepts_radiated_power_exactly_at_the_licence_ceiling(
        self, api, network_engineer
    ):
        """PRD 3.2: "The derived `eirp_dbm` must not exceed the bound licence's
        `max_eirp_dbm`, else the creation is refused with
        `ERR_EIRP_EXCEEDS_LICENSE`."

        Design: Corner/validations/licence_envelope_is_enforced_on_power_on_channel_and_on_effectivity
        """
        tower = create_tower()
        license_record = get_spectrum_license(create_spectrum_license()["id"])

        response = api.create_sector(
            create_sector_payload(
                tower["id"],
                license_record["id"],
                tx_power_dbm=30.0,
                antenna_gain_dbi=17.0,
            ),
            network_engineer,
        )
        sector = validate_success(response, 201)
        assert_sector(sector)
        assert sector["eirp_dbm"] == 47.0 == license_record["max_eirp_dbm"]
        assert sector["status"] == "PLANNED"

    @pytest.mark.parametrize(
        "channel_center_mhz,channel_width_mhz",
        [
            pytest.param(3545.0, 10.0, id="lower_edge_below_licence"),
            pytest.param(3648.0, 10.0, id="upper_edge_above_licence"),
        ],
    )
    def test_sector_creation_rejects_a_channel_reaching_outside_the_licence(
        self, api, network_engineer, channel_center_mhz, channel_width_mhz
    ):
        """PRD 3.2: "The sector's `lower_edge_mhz` must be at or above the licence's
        `lower_edge_mhz` and its `upper_edge_mhz` must be at or below the licence's
        `upper_edge_mhz`, else the creation is refused with
        `ERR_CHANNEL_OUTSIDE_LICENSE`."
        PRD 3.2: "Two edges are derived from the block and reported on every read:
        `lower_edge_mhz` is `channel_center_mhz` less half of `channel_width_mhz`,
        and `upper_edge_mhz` is `channel_center_mhz` plus half of
        `channel_width_mhz`."

        Design: Corner/validations/licence_envelope_is_enforced_on_power_on_channel_and_on_effectivity
        """
        tower = create_tower()
        license_record = get_spectrum_license(create_spectrum_license()["id"])
        assert license_record["lower_edge_mhz"] == 3550.0
        assert license_record["upper_edge_mhz"] == 3650.0

        response = api.create_sector(
            create_sector_payload(
                tower["id"],
                license_record["id"],
                channel_center_mhz=channel_center_mhz,
                channel_width_mhz=channel_width_mhz,
            ),
            network_engineer,
        )
        validate_error(response, ApiErrorId.ERR_CHANNEL_OUTSIDE_LICENSE.value)

    @pytest.mark.parametrize(
        "channel_center_mhz,expected_lower,expected_upper",
        [
            pytest.param(3555.0, 3550.0, 3560.0, id="flush_with_licence_lower_edge"),
            pytest.param(3645.0, 3640.0, 3650.0, id="flush_with_licence_upper_edge"),
        ],
    )
    def test_sector_creation_accepts_a_channel_flush_with_a_licence_edge(
        self, api, network_engineer, channel_center_mhz, expected_lower, expected_upper
    ):
        """PRD 3.2: "The sector's `lower_edge_mhz` must be at or above the licence's
        `lower_edge_mhz` and its `upper_edge_mhz` must be at or below the licence's
        `upper_edge_mhz`, else the creation is refused with
        `ERR_CHANNEL_OUTSIDE_LICENSE`."

        Design: Corner/validations/licence_envelope_is_enforced_on_power_on_channel_and_on_effectivity
        """
        tower = create_tower()
        license_record = get_spectrum_license(create_spectrum_license()["id"])

        response = api.create_sector(
            create_sector_payload(
                tower["id"],
                license_record["id"],
                channel_center_mhz=channel_center_mhz,
                channel_width_mhz=10.0,
            ),
            network_engineer,
        )
        sector = validate_success(response, 201)
        assert sector["lower_edge_mhz"] == expected_lower
        assert sector["upper_edge_mhz"] == expected_upper

    @pytest.mark.parametrize(
        "effective_from,effective_to,expected_license_status",
        [
            pytest.param(
                "2027-01-01T00:00:00Z", "2032-01-01T00:00:00Z", "PENDING", id="pending"
            ),
            pytest.param(
                "2025-01-01T00:00:00Z", "2026-07-01T00:00:00Z", "EXPIRED", id="expired"
            ),
        ],
    )
    def test_activation_rejects_a_licence_that_is_not_clock_effective(
        self,
        api,
        network_engineer,
        effective_from,
        effective_to,
        expected_license_status,
    ):
        """PRD 3.2: "A sector may be created against a licence that is not yet
        `ACTIVE`; effectiveness is enforced only at activation and at coordination
        time."
        PRD 3.2: "the bound licence's clock-derived `status` must be `ACTIVE` at the
        current logical clock, a `PENDING` or `EXPIRED` licence being refused with
        `ERR_LICENSE_NOT_EFFECTIVE`."
        PRD 3.2: "The licence's `status` is not stored but recomputed against the
        logical clock on every read: `PENDING` while the clock is before
        `effective_from`, `ACTIVE` while the clock is at or after `effective_from`
        and strictly before `effective_to`, and `EXPIRED` once the clock reaches or
        passes `effective_to`."

        Design: Corner/validations/licence_envelope_is_enforced_on_power_on_channel_and_on_effectivity
        """
        scenario = setup_active_plant()
        assert scenario["tower"]["status"] == "ACTIVE"

        ineffective = create_spectrum_license(
            effective_from=effective_from, effective_to=effective_to
        )
        assert (
            get_spectrum_license(ineffective["id"])["status"] == expected_license_status
        )

        # Creation is allowed even though the licence is not effective.
        planned = validate_success(
            api.create_sector(
                create_sector_payload(
                    scenario["tower"]["id"], ineffective["id"], azimuth_deg=200.0
                ),
                network_engineer,
            ),
            201,
        )
        assert planned["status"] == "PLANNED"
        assert planned["spectrum_license_id"] == ineffective["id"]

        response = api.activate_sector(planned["id"], network_engineer)
        validate_error(response, ApiErrorId.ERR_LICENSE_NOT_EFFECTIVE.value)

        after = get_sector(planned["id"])
        assert after["status"] == "PLANNED"
        assert_no_mutation(planned, after, "sector")


# --------------------------------------------------------------------------
# The rejection ladder: rung 3 outranks rung 6, and rung 1 outranks all
# --------------------------------------------------------------------------


def _malformed_circuit_payload_naming_a_missing_tower() -> dict:
    """A transport-circuit body that violates rung 3 and rung 6 at once.

    `committed_mbps` of -5 is below the declared minimum of 1, and `tower_id`
    resolves to nothing.
    """
    return {
        "tower_id": NON_EXISTENT_UUID,
        "carrier_name": "Prairie Fiber Cooperative",
        "circuit_ref": "PF-CIR-9001",
        "committed_mbps": -5,
        "monthly_cost_cents": 120000,
    }


class TestRejectionLadderPrecedence:
    def test_body_shape_violation_outranks_an_unresolvable_body_reference(
        self, api, network_engineer
    ):
        """PRD 2.7: "When a single request violates more than one rule, the server
        reports exactly one error, chosen by a fixed ladder of precedence.
        Implementations must evaluate the rungs in this order and stop at the first
        violated rung:"
        PRD 2.7: "**Request-body shape** — required fields present, types correct, enum values drawn from the
        declared members, numeric values inside their declared ranges and decimal precision
        (including latitude and longitude ranges, non-negative traffic volumes, a reservation
        life between 1 and 30 days inclusive, and a measured throughput supplied on a
        transport-circuit acceptance), else `ERR_VALIDATION` (400). Applies to every write endpoint."
        PRD 2.7: "**Body-reference existence** — every identifier in the body resolves, in field order, else the
        matching 404 of §2.6."
        PRD 3.1: "a `NetworkEngineer` orders one by naming the `tower_id` it hauls
        for, the `carrier_name` delivering it, the `circuit_ref` the carrier uses to
        identify it, the `committed_mbps` information rate (at least 1), and the
        recurring `monthly_cost_cents` (not negative)."

        Design: Corner/validations/body_validation_outranks_existence_and_missing_auth_outranks_everything
        """
        response = api.create_backhaul_circuit(
            _malformed_circuit_payload_naming_a_missing_tower(), network_engineer
        )
        validate_error(response, ApiErrorId.ERR_VALIDATION.value)

    def test_an_unresolvable_body_reference_is_reported_once_the_body_is_well_formed(
        self, api, network_engineer
    ):
        """PRD 2.7: "**Body-reference existence** — every identifier in the body resolves, in field order, else the
        matching 404 of §2.6."
        PRD 2.6: "a missing tower yields `ERR_TOWER_NOT_FOUND`"

        Design: Corner/validations/body_validation_outranks_existence_and_missing_auth_outranks_everything
        """
        payload = _malformed_circuit_payload_naming_a_missing_tower()
        payload["committed_mbps"] = 500

        response = api.create_backhaul_circuit(payload, network_engineer)
        validate_error(response, ApiErrorId.ERR_TOWER_NOT_FOUND.value)

    @pytest.mark.parametrize(
        "headers",
        [
            pytest.param({}, id="both_headers_absent"),
            pytest.param({"X-User-Role": "NetworkEngineer"}, id="user_id_absent"),
            pytest.param({"X-User-ID": "op-neteng-1"}, id="user_role_absent"),
            pytest.param(
                {"X-User-ID": "op-neteng-1", "X-User-Role": "Regulator"},
                id="role_not_recognized",
            ),
        ],
    )
    def test_absent_or_unrecognized_auth_headers_outrank_every_other_rung(
        self, api, headers
    ):
        """PRD 2.1: "If either header is absent, or if the value of `X-User-Role` is
        not one of the seven role names declared below, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401). Header validation happens before anything
        else: an unauthenticated caller never learns whether the resource they
        addressed exists."
        PRD 2.7: "**Authentication** — headers present and `X-User-Role` recognized, else `ERR_UNAUTHENTICATED`
        (401). Applies to every endpoint."

        Design: Corner/validations/body_validation_outranks_existence_and_missing_auth_outranks_everything
        """
        response = api.create_backhaul_circuit(
            _malformed_circuit_payload_naming_a_missing_tower(), headers
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)

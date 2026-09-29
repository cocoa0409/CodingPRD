"""Record shapes: creation defaults, derived fields, listings and reference errors.

Every test here pins the observable representation of one record type against the
PRD sentence that declares it: the fields a fresh record opens with, the values
the server derives rather than accepts, the envelope a list endpoint returns, and
the 404 an unresolvable identifier produces.
"""

from datetime import datetime

import pytest

from test_helpers import (
    HTTP_STATUS_CODES,
    ApiErrorId,
    assert_capacity_hold,
    assert_equipment_assignment,
    assert_interference_coordination,
    assert_sector,
    assert_service_plan,
    assert_spectrum_license,
    assert_subscriber,
    assert_tower,
    assert_usage_record,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_backhaul_circuit_payload,
    create_coordination_payload,
    create_sector_payload,
    create_service_plan_payload,
    create_spectrum_license_payload,
    create_subscriber_payload,
    create_tower_payload,
    usage_record_payload,
)
from test_helpers.fixtures import (
    advance_clock,
    create_sector,
    create_spectrum_license,
    create_tower,
    get_sector,
    get_spectrum_license,
    ingest_usage,
    setup_active_subscriber,
    setup_neighbor_sectors,
    setup_held_reservation,
    setup_qualified_request,
)

# A well-formed UUID that no record in a freshly started database carries.
UNUSED_UUID = "11111111-2222-3333-4444-555555555555"


def _instant(value: str) -> datetime:
    """Parse a Z-suffixed ISO 8601 stamp, with or without fractional digits."""
    assert isinstance(value, str) and value.endswith("Z"), (
        f"expected a Z-suffixed ISO 8601 timestamp, got {value!r}"
    )
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _tower_101_payload() -> dict:
    """The reference site: lease commencing 2026-07-01, so no anniversary has yet
    fallen at or before the logical clock's startup reading of 2026-08-01."""
    return create_tower_payload(
        site_code="RB-TWR-101",
        latitude=41.3,
        longitude=-104.9,
        ground_elevation_m=1180.0,
        antenna_agl_m=36.0,
        lease_landowner_name="Kestrel Land Co",
        lease_monthly_base_rent_cents=45000,
        lease_escalator_pct=0.0275,
        lease_start_date="2026-07-01",
        lease_term_months=60,
    )


# ==========================================================================
# Tower registration
# ==========================================================================


class TestTowerRegistrationShape:
    def test_tower_opens_planned_with_zero_rollups_and_derived_rent(
        self, api, network_engineer
    ):
        """PRD §3.1: "Upon registration the site opens in `PLANNED` `status`, with
        `active_sector_count` at zero and `backhaul_accepted_mbps` at zero, and its
        `current_monthly_rent_cents` is derived immediately."
        PRD §3.1: "The rent for lease year zero is `lease_monthly_base_rent_cents`
        exactly."
        PRD §2.5: "**`version`** — an integer that starts at 1 on creation and
        increments by exactly 1 on every mutation of the record."

        Design: Corner/entities/tower_created_with_all_required_fields_returns_planned_and_zero_derived_fields
        """
        payload = _tower_101_payload()

        response = api.create_tower(payload, network_engineer)
        tower = validate_success(response, 201)

        assert_tower(tower)
        assert tower["site_code"] == "RB-TWR-101", (
            f"site_code must echo the placard code, got {tower['site_code']!r}"
        )
        assert tower["status"] == "PLANNED", (
            f"a newly registered site opens in PLANNED, got {tower['status']!r}"
        )
        assert tower["version"] == 1, (
            f"version starts at 1 on creation, got {tower['version']}"
        )
        assert tower["ground_elevation_m"] == 1180.0
        assert tower["antenna_agl_m"] == 36.0
        assert tower["active_sector_count"] == 0, (
            f"active_sector_count opens at zero, got {tower['active_sector_count']}"
        )
        assert tower["backhaul_accepted_mbps"] == 0, (
            "backhaul_accepted_mbps opens at zero, got "
            f"{tower['backhaul_accepted_mbps']}"
        )
        assert tower["current_monthly_rent_cents"] == 45000, (
            "lease year zero rent is lease_monthly_base_rent_cents exactly, expected "
            f"45000, got {tower['current_monthly_rent_cents']}"
        )
        assert _instant(tower["created_at"]) == _instant(tower["updated_at"]), (
            "an unmutated record's updated_at still sits at its creation instant"
        )

    def test_tower_create_without_antenna_agl_m_is_rejected_and_persists_nothing(
        self, api, network_engineer
    ):
        """PRD §2.7: "**Request-body shape** — required fields present, types
        correct, enum values drawn from the declared members, numeric values inside
        their declared ranges and decimal precision (including latitude and
        longitude ranges, non-negative traffic volumes, a reservation life between 1
        and 30 days inclusive, and a measured throughput supplied on a
        transport-circuit acceptance), else `ERR_VALIDATION` (400)."
        PRD §3.1: "A second tower attempting to reuse an existing code is refused
        with `ERR_DUPLICATE_SITE_CODE`."

        Design: Corner/entities/tower_create_missing_antenna_agl_m_is_rejected
        """
        complete = _tower_101_payload()
        without_agl = {k: v for k, v in complete.items() if k != "antenna_agl_m"}

        rejected = api.create_tower(without_agl, network_engineer)
        validate_error(rejected, ApiErrorId.ERR_VALIDATION.value, 400)

        # The rejected request stored nothing, so RB-TWR-101 is still a free code.
        retried = api.create_tower(complete, network_engineer)
        tower = validate_success(retried, 201)
        assert tower["site_code"] == "RB-TWR-101", (
            "the rejected create must not have reserved the site_code"
        )
        assert tower["antenna_agl_m"] == 36.0


# ==========================================================================
# Service plan catalogue
# ==========================================================================


class TestServicePlanShape:
    def test_service_plan_read_back_returns_every_published_value_unchanged(
        self, api, capacity_planner, sales_agent
    ):
        """PRD §3.5: "A plan carries a `tier_code` unique across the catalogue and
        refused with `ERR_DUPLICATE_TIER_CODE` when reused; `downstream_mbps` and
        `upstream_mbps`, both whole numbers of at least 1; `monthly_price_cents`,
        not negative; a `soft_cap_gb` monthly fair-use allowance, strictly greater
        than zero to one decimal place; a `deprioritization_factor` between 0.05 and
        1.0 inclusive to two decimal places, being the fraction of downstream rate
        the account retains once it has passed its allowance; an `sla_uptime_pct`
        commitment between 90.0 and 100.0 inclusive to three decimal places; an
        `sla_credit_method` of either `SLA_SHORTFALL` or `PER_INCIDENT`, which
        decides how outage compensation is computed for accounts on the plan; and an
        `equipment_policy` of `RENTAL_ONLY`, `PURCHASE_ONLY` or
        `RENTAL_OR_PURCHASE`, which decides how the customer premises radio may be
        acquired."

        Design: Corner/entities/service_plan_read_back_returns_every_stored_field_unchanged
        """
        payload = create_service_plan_payload(
            tier_code="STD50",
            downstream_mbps=50,
            upstream_mbps=10,
            monthly_price_cents=6999,
            soft_cap_gb=600.0,
            deprioritization_factor=0.25,
            sla_uptime_pct=99.5,
            sla_credit_method="SLA_SHORTFALL",
            equipment_policy="RENTAL_OR_PURCHASE",
        )
        created = validate_success(
            api.create_service_plan(payload, capacity_planner), 201
        )

        plan = validate_success(api.get_service_plan(created["id"], sales_agent), 200)

        assert_service_plan(plan)
        assert plan["id"] == created["id"]
        assert plan["tier_code"] == "STD50"
        assert plan["downstream_mbps"] == 50
        assert plan["upstream_mbps"] == 10
        assert plan["monthly_price_cents"] == 6999
        assert plan["soft_cap_gb"] == pytest.approx(600.0, abs=0.01), (
            f"soft_cap_gb is stored as published, got {plan['soft_cap_gb']}"
        )
        assert plan["deprioritization_factor"] == pytest.approx(0.25, abs=0.001), (
            f"deprioritization_factor is stored as published, got {plan['deprioritization_factor']}"
        )
        assert plan["sla_uptime_pct"] == pytest.approx(99.5, abs=0.0005), (
            f"sla_uptime_pct is stored as published, got {plan['sla_uptime_pct']}"
        )
        assert plan["sla_credit_method"] == "SLA_SHORTFALL"
        assert plan["equipment_policy"] == "RENTAL_OR_PURCHASE"


# ==========================================================================
# Sector construction: system defaults and derived spectrum values
# ==========================================================================


class TestSectorShape:
    def test_sector_omitting_max_oversubscription_ratio_takes_eight_and_opens_planned(
        self, api, network_engineer
    ):
        """PRD §3.2: "`max_oversubscription_ratio` is optional; when the caller omits
        it the sector takes 8.0, and when supplied it must lie between 1.0 and 20.0
        inclusive to one decimal place."
        PRD §3.2: "The sector opens in `PLANNED` `status` with `sold_mbps`,
        `held_mbps` and `committed_mbps` all zero, `capacity_policy_note` absent, and
        its `capacity_posture` derived immediately by the posture rules of §3.3."
        PRD §3.3: "`committed_mbps` is simply `sold_mbps` plus `held_mbps`, and
        `oversubscription_ratio` is `committed_mbps` divided by `capacity_mbps`,
        rounded half up to three decimal places."
        PRD §3.3: "Otherwise, if the parent tower's `backhaul_accepted_mbps` is zero
        — that is, no circuit on the tower is in `ACCEPTED` state — the posture is
        `FROZEN`."

        Design: Corner/entities/sector_created_without_max_oversubscription_ratio_defaults_to_eight
        """
        tower = create_tower(
            site_code="RB-TWR-101",
            latitude=41.3,
            longitude=-104.9,
            ground_elevation_m=1180.0,
            antenna_agl_m=36.0,
            lease_start_date="2026-07-01",
        )
        license_ = create_spectrum_license(
            license_ref="CBRS-PAL-4412",
            channel_center_mhz=3600.0,
            channel_width_mhz=100.0,
            max_eirp_dbm=47.0,
        )
        assert tower["backhaul_accepted_mbps"] == 0, (
            "the reference site carries no ACCEPTED circuit"
        )

        payload = create_sector_payload(
            tower["id"],
            license_["id"],
            azimuth_deg=90.0,
            beamwidth_deg=65.0,
            channel_center_mhz=3555.0,
            channel_width_mhz=10.0,
            tx_power_dbm=25.0,
            antenna_gain_dbi=17.0,
            capacity_mbps=25,
        )
        payload.pop("max_oversubscription_ratio")

        sector = validate_success(api.create_sector(payload, network_engineer), 201)

        assert_sector(sector)
        assert sector["max_oversubscription_ratio"] == pytest.approx(8.0, abs=0.05), (
            "an omitted max_oversubscription_ratio takes 8.0, got "
            f"{sector['max_oversubscription_ratio']}"
        )
        assert sector["status"] == "PLANNED", (
            f"a new sector opens in PLANNED, got {sector['status']!r}"
        )
        assert sector["version"] == 1, f"version starts at 1, got {sector['version']}"
        assert sector["sold_mbps"] == 0
        assert sector["held_mbps"] == 0
        assert sector["committed_mbps"] == 0
        assert sector["oversubscription_ratio"] == pytest.approx(0.0, abs=0.0005), (
            f"an empty ledger gives a ratio of 0.000, got {sector['oversubscription_ratio']}"
        )
        assert sector["capacity_posture"] == "FROZEN", (
            "a tower with backhaul_accepted_mbps of zero freezes its sectors, got "
            f"{sector['capacity_posture']!r}"
        )
        assert sector.get("capacity_policy_note") is None, (
            "capacity_policy_note is absent until the first policy override, got "
            f"{sector.get('capacity_policy_note')!r}"
        )

    def test_sector_and_license_edges_and_eirp_are_derived_not_stored(
        self, api, network_engineer, capacity_planner
    ):
        """PRD §3.2: "Two edges are derived from the block and reported on every
        read: `lower_edge_mhz` is `channel_center_mhz` less half of
        `channel_width_mhz`, and `upper_edge_mhz` is `channel_center_mhz` plus half
        of `channel_width_mhz`."
        PRD §3.2: "Three values are derived at creation. `eirp_dbm` is
        `tx_power_dbm` plus `antenna_gain_dbi`, rounded to one decimal place."
        PRD §3.2: "The licence's `status` is not stored but recomputed against the
        logical clock on every read: `PENDING` while the clock is before
        `effective_from`, `ACTIVE` while the clock is at or after `effective_from`
        and strictly before `effective_to`, and `EXPIRED` once the clock reaches or
        passes `effective_to`."

        Design: Corner/entities/sector_edges_and_eirp_are_computed_from_channel_and_power_inputs
        """
        tower = create_tower(
            site_code="RB-TWR-101",
            ground_elevation_m=1180.0,
            antenna_agl_m=36.0,
            lease_start_date="2026-07-01",
        )
        license_ = create_spectrum_license(
            license_ref="CBRS-PAL-4412",
            channel_center_mhz=3600.0,
            channel_width_mhz=100.0,
            max_eirp_dbm=47.0,
            effective_from="2025-01-01T00:00:00Z",
            effective_to="2030-01-01T00:00:00Z",
        )

        payload = create_sector_payload(
            tower["id"],
            license_["id"],
            channel_center_mhz=3555.0,
            channel_width_mhz=10.0,
            tx_power_dbm=25.0,
            antenna_gain_dbi=17.0,
        )
        sector = validate_success(api.create_sector(payload, network_engineer), 201)

        assert_sector(sector)
        assert sector["lower_edge_mhz"] == pytest.approx(3550.0, abs=0.05), (
            "lower_edge_mhz is 3555.0 less half of 10.0, got "
            f"{sector['lower_edge_mhz']}"
        )
        assert sector["upper_edge_mhz"] == pytest.approx(3560.0, abs=0.05), (
            "upper_edge_mhz is 3555.0 plus half of 10.0, got "
            f"{sector['upper_edge_mhz']}"
        )
        assert sector["eirp_dbm"] == pytest.approx(42.0, abs=0.05), (
            "eirp_dbm is tx_power_dbm 25.0 plus antenna_gain_dbi 17.0, got "
            f"{sector['eirp_dbm']}"
        )

        # The same half-width arithmetic on the licence, plus its clock-derived status.
        licence_read = validate_success(
            api.get_spectrum_license(license_["id"], capacity_planner), 200
        )
        assert_spectrum_license(licence_read)
        assert licence_read["lower_edge_mhz"] == pytest.approx(3550.0, abs=0.05), (
            "licence lower_edge_mhz is 3600.0 less half of 100.0, got "
            f"{licence_read['lower_edge_mhz']}"
        )
        assert licence_read["upper_edge_mhz"] == pytest.approx(3650.0, abs=0.05), (
            "licence upper_edge_mhz is 3600.0 plus half of 100.0, got "
            f"{licence_read['upper_edge_mhz']}"
        )
        assert licence_read["status"] == "ACTIVE", (
            "the clock sits at or after effective_from and strictly before "
            f"effective_to, so status is ACTIVE, got {licence_read['status']!r}"
        )


# ==========================================================================
# Sector listing: filter first, then the window
# ==========================================================================


class TestSectorListingPagination:
    def test_sector_list_filtered_by_tower_reports_filtered_total_count_and_has_more(
        self, api, capacity_planner
    ):
        """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`,
        and `has_more` inside the `meta` object of the envelope. `total_count` is the
        number of records matching the filter before pagination is applied, and
        `has_more` is true when records remain beyond the returned page."
        PRD §2.3: "The sector listing filters on `tower_id`, `spectrum_license_id`,
        `capacity_posture`, and `status`."

        Design: Corner/entities/sector_list_filtered_by_tower_paginates_with_total_count_and_has_more
        """
        tower = create_tower(site_code="RB-TWR-101", lease_start_date="2026-07-01")
        license_ = create_spectrum_license(
            license_ref="CBRS-PAL-4412", channel_center_mhz=3600.0, channel_width_mhz=100.0
        )
        sector_a = create_sector(
            tower["id"], license_["id"], azimuth_deg=90.0, channel_center_mhz=3555.0
        )
        sector_b = create_sector(
            tower["id"], license_["id"], azimuth_deg=210.0, channel_center_mhz=3575.0
        )
        sector_c = create_sector(
            tower["id"], license_["id"], azimuth_deg=330.0, channel_center_mhz=3595.0
        )
        # A fourth sector on a different tower must never enter the filtered count.
        other_tower = create_tower(site_code="RB-TWR-102", lease_start_date="2026-07-01")
        other_sector = create_sector(
            other_tower["id"], license_["id"], azimuth_deg=45.0, channel_center_mhz=3605.0
        )

        first_rows, first_meta = validate_paginated(
            api.list_sectors(capacity_planner, params={"tower_id": tower["id"], "limit": 2, "offset": 0})
        )
        assert len(first_rows) == 2, f"limit 2 caps the page at 2 rows, got {len(first_rows)}"
        assert first_meta["total_count"] == 3, (
            "total_count counts the three sectors matching tower_id, got "
            f"{first_meta['total_count']}"
        )
        assert first_meta["has_more"] is True, (
            "one sector remains beyond the first page, so has_more is true"
        )
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0

        second_rows, second_meta = validate_paginated(
            api.list_sectors(capacity_planner, params={"tower_id": tower["id"], "limit": 2, "offset": 2})
        )
        assert len(second_rows) == 1, (
            f"only one sector remains after skipping two, got {len(second_rows)}"
        )
        assert second_meta["total_count"] == 3, (
            "total_count is taken before pagination, got "
            f"{second_meta['total_count']}"
        )
        assert second_meta["has_more"] is False, (
            "nothing remains beyond the second page, so has_more is false"
        )
        assert second_meta["offset"] == 2

        seen = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
        assert len(seen) == len(set(seen)), f"no sector may repeat across pages, got {seen}"
        assert set(seen) == {sector_a["id"], sector_b["id"], sector_c["id"]}, (
            "the two pages together are exactly the filtered set, got "
            f"{sorted(seen)}"
        )
        assert other_sector["id"] not in seen, (
            "a sector on another tower must not appear under the tower_id filter"
        )


# ==========================================================================
# Capacity reservation: the window the caller did not choose
# ==========================================================================


class TestCapacityHoldDefaults:
    def test_capacity_hold_without_hold_days_takes_fourteen_days_and_opens_held_direct(
        self, api, sales_agent
    ):
        """PRD §3.6: "The `hold_days` window defaults to 14 when omitted and must
        otherwise be a whole number between 1 and 30 inclusive."
        PRD §3.6: "Everything else is derived and cannot be chosen: `sector_id` is
        copied from the enquiry's `qualified_sector_id`, and `held_mbps` is copied
        from the `downstream_mbps` of the enquiry's requested plan."
        PRD §3.6: "A successful reservation opens in `HELD` `status` with `origin`
        `DIRECT`, no `release_reason`, and an `expires_at` set to the current logical
        clock advanced by `hold_days` days."

        Design: Corner/entities/capacity_hold_created_without_hold_days_defaults_to_a_fourteen_day_window
        """
        scenario = setup_qualified_request()
        request = scenario["request"]
        sector = get_sector(scenario["sector"]["id"])
        assert request["status"] == "QUALIFIED", (
            f"Setup failed: enquiry is {request['status']!r}, not QUALIFIED"
        )
        assert request["qualified_sector_id"] == sector["id"], (
            "Setup failed: the enquiry did not qualify against the reference sector"
        )

        # hold_days is simply absent from the body.
        payload = {
            "serviceability_request_id": request["id"],
            "expected_sector_version": sector["version"],
        }
        hold = validate_success(api.create_capacity_hold(payload, sales_agent), 201)

        assert_capacity_hold(hold)
        assert hold["hold_days"] == 14, (
            f"an omitted hold_days defaults to 14, got {hold['hold_days']}"
        )
        assert hold["status"] == "HELD", (
            f"a successful reservation opens in HELD, got {hold['status']!r}"
        )
        assert hold["origin"] == "DIRECT", (
            f"a directly taken reservation carries origin DIRECT, got {hold['origin']!r}"
        )
        assert hold.get("release_reason") is None, (
            "a fresh reservation carries no release_reason, got "
            f"{hold.get('release_reason')!r}"
        )
        assert hold["sector_id"] == sector["id"], (
            "sector_id is copied from the enquiry's qualified_sector_id, expected "
            f"{sector['id']}, got {hold['sector_id']}"
        )
        assert hold["held_mbps"] == scenario["plan"]["downstream_mbps"], (
            "held_mbps is copied from the requested plan's downstream_mbps, expected "
            f"{scenario['plan']['downstream_mbps']}, got {hold['held_mbps']}"
        )
        assert hold["version"] == 1, f"version starts at 1, got {hold['version']}"
        # The clock has not moved since startup, so the window closes 14 days later.
        assert _instant(hold["expires_at"]) == _instant("2026-08-15T00:00:00Z"), (
            "expires_at is the logical clock advanced by 14 days, expected "
            f"2026-08-15T00:00:00Z, got {hold['expires_at']}"
        )


# ==========================================================================
# Account opening: the fields only the server may write
# ==========================================================================


class TestSubscriberSystemFields:
    def test_first_account_is_minted_rb_000001_pending_install_with_an_assigned_radio(
        self, api, sales_agent, field_tech
    ):
        """PRD §3.6: "A new account is stamped with an `account_number` from a
        deterministic sequential series in the form `RB-000001`, `RB-000002` and so
        on, zero-padded to six digits. It opens with `service_status`
        `PENDING_INSTALL` and `usage_priority` `STANDARD`. Its `sector_id` is copied
        from the enquiry's `qualified_sector_id` and is **never** changed thereafter —
        an account stays on the sector it was sold on for the whole of its life,
        including across plan changes. `cycle_start_date` is absent because no billing
        cycle opens until the radio is actually installed; `cycle_usage_gb` is
        therefore zero, `consecutive_breach_cycles` is zero,
        `sticky_deprioritization_active` is false, and `deprioritized_at`,
        `service_start_date` and `cancelled_at` are all absent."
        PRD §3.6: "Finally, exactly one equipment record is minted as a side effect:
        it opens in `ASSIGNED` `status`, its `acquisition_mode` copied from the
        account's `equipment_mode`, its `radio_serial` absent because no radio has
        been allocated yet, its `monthly_rental_cents` at 1000 for a `RENTAL`
        acquisition and 0 for a `PURCHASE`, its `purchase_price_cents` at 29900 for a
        `PURCHASE` and 0 for a `RENTAL`, its `replacement_cost_cents` at 34900 in both
        cases, its `settlement_cents` at 0 and its `settlement_basis`, `deployed_at`,
        `return_due_at`, `returned_at` and `return_condition` all absent."
        PRD §3.6: "That record is **not** returned in the account-creation response
        and has no creation endpoint of its own; the only way to discover it is the
        per-account equipment listing described in §4. The account's
        `equipment_monthly_charge_cents` is derived from it and is zero while the
        radio is merely assigned."

        Design: Corner/entities/subscriber_system_fields_mint_account_number_and_initial_status
        """
        scenario = setup_held_reservation()
        sector_id = scenario["sector"]["id"]

        payload = create_subscriber_payload(
            scenario["request"]["id"],
            scenario["plan"]["id"],
            billing_email="dana.reyes@example.com",
            equipment_mode="RENTAL",
        )
        subscriber = validate_success(api.create_subscriber(payload, sales_agent), 201)

        assert_subscriber(subscriber)
        assert subscriber["account_number"] == "RB-000001", (
            "the first account of the series is RB-000001, got "
            f"{subscriber['account_number']!r}"
        )
        assert subscriber["service_status"] == "PENDING_INSTALL", (
            f"a new account opens PENDING_INSTALL, got {subscriber['service_status']!r}"
        )
        assert subscriber["usage_priority"] == "STANDARD", (
            f"a new account opens STANDARD, got {subscriber['usage_priority']!r}"
        )
        assert subscriber["sector_id"] == sector_id, (
            "sector_id is copied from the enquiry's qualified_sector_id, expected "
            f"{sector_id}, got {subscriber['sector_id']}"
        )
        assert subscriber.get("cycle_start_date") is None, (
            "no billing cycle opens until the radio is installed, got "
            f"{subscriber.get('cycle_start_date')!r}"
        )
        assert subscriber.get("service_start_date") is None, (
            f"service_start_date is absent, got {subscriber.get('service_start_date')!r}"
        )
        assert subscriber.get("deprioritized_at") is None
        assert subscriber.get("cancelled_at") is None
        assert subscriber["cycle_usage_gb"] == pytest.approx(0.0, abs=0.05)
        assert subscriber["consecutive_breach_cycles"] == 0
        assert subscriber["sticky_deprioritization_active"] is False
        assert subscriber["credit_balance_cents"] == 0
        assert subscriber["settlement_balance_cents"] == 0
        assert subscriber["effective_downstream_mbps"] == pytest.approx(
            float(scenario["plan"]["downstream_mbps"]), abs=0.05
        ), (
            "effective_downstream_mbps starts equal to the plan's downstream_mbps, got "
            f"{subscriber['effective_downstream_mbps']}"
        )
        assert subscriber["version"] == 1, (
            f"version starts at 1, got {subscriber['version']}"
        )

        # The minted radio record is discoverable only through the per-account listing.
        rows, meta = validate_paginated(
            api.list_subscriber_equipment(subscriber["id"], field_tech)
        )
        assert meta["total_count"] == 1, (
            f"exactly one equipment record is minted, got {meta['total_count']}"
        )
        assignment = rows[0]
        assert_equipment_assignment(assignment)
        assert assignment["subscriber_id"] == subscriber["id"]
        assert assignment["status"] == "ASSIGNED", (
            f"the equipment record opens in ASSIGNED, got {assignment['status']!r}"
        )
        assert assignment["acquisition_mode"] == "RENTAL", (
            "acquisition_mode is copied from the account's equipment_mode, got "
            f"{assignment['acquisition_mode']!r}"
        )
        assert assignment.get("radio_serial") is None, (
            f"no radio has been allocated yet, got {assignment.get('radio_serial')!r}"
        )
        assert assignment["monthly_rental_cents"] == 1000, (
            "a RENTAL acquisition carries monthly_rental_cents 1000, got "
            f"{assignment['monthly_rental_cents']}"
        )
        assert assignment["purchase_price_cents"] == 0, (
            "a RENTAL acquisition carries purchase_price_cents 0, got "
            f"{assignment['purchase_price_cents']}"
        )
        assert assignment["replacement_cost_cents"] == 34900, (
            "replacement_cost_cents is 34900 in both cases, got "
            f"{assignment['replacement_cost_cents']}"
        )
        assert assignment["settlement_cents"] == 0
        assert assignment.get("settlement_basis") is None
        assert assignment.get("deployed_at") is None, (
            f"the radio is not deployed yet, got {assignment.get('deployed_at')!r}"
        )
        assert assignment.get("return_due_at") is None
        assert assignment.get("returned_at") is None
        assert assignment.get("return_condition") is None
        assert subscriber["equipment_monthly_charge_cents"] == 0, (
            "the recurring charge only begins once the radio is deployed, got "
            f"{subscriber['equipment_monthly_charge_cents']}"
        )


# ==========================================================================
# Spectrum licence: the enum and the validity window
# ==========================================================================


class TestSpectrumLicenseConstraints:
    def test_license_with_an_undeclared_band_is_refused_and_frees_the_license_ref(
        self, api, network_engineer
    ):
        """PRD §3.2: "A licence carries the regulator's `license_ref`, unique across
        all licences and refused with `ERR_DUPLICATE_LICENSE_REF` when reused; a
        `band` drawn from `CBRS_3_5GHZ`, `EBS_2_5GHZ` and `LTE_700MHZ`; the block's
        `channel_center_mhz` between 600.0 and 6000.0 inclusive to one decimal place;
        its `channel_width_mhz` between 5.0 and 200.0 inclusive to one decimal place;
        the `max_eirp_dbm` ceiling between 20.0 and 65.0 inclusive to one decimal
        place; the regulator's `license_area_code`; and a validity window given as an
        inclusive `effective_from` and an exclusive `effective_to`, where
        `effective_to` must be strictly later than `effective_from`."
        PRD §2.7: "**Request-body shape** — required fields present, types correct,
        enum values drawn from the declared members, numeric values inside their
        declared ranges and decimal precision (including latitude and longitude
        ranges, non-negative traffic volumes, a reservation life between 1 and 30 days
        inclusive, and a measured throughput supplied on a transport-circuit
        acceptance), else `ERR_VALIDATION` (400)."

        Design: Corner/entities/spectrum_license_rejects_an_undeclared_band_enum_member
        """
        payload = create_spectrum_license_payload(
            license_ref="CBRS-PAL-9999",
            band="CBRS_3_7GHZ",
            channel_center_mhz=3700.0,
            channel_width_mhz=100.0,
            max_eirp_dbm=47.0,
        )

        rejected = api.create_spectrum_license(payload, network_engineer)
        validate_error(rejected, ApiErrorId.ERR_VALIDATION.value, 400)

        # Nothing was stored, so the same license_ref is still free for a real band.
        accepted = dict(payload, band="CBRS_3_5GHZ")
        license_ = validate_success(
            api.create_spectrum_license(accepted, network_engineer), 201
        )
        assert license_["license_ref"] == "CBRS-PAL-9999", (
            "the rejected create must not have reserved the license_ref"
        )
        assert license_["band"] == "CBRS_3_5GHZ"

    def test_license_whose_effective_to_equals_effective_from_is_refused(
        self, api, network_engineer
    ):
        """PRD §3.2: "A licence carries the regulator's `license_ref`, unique across
        all licences and refused with `ERR_DUPLICATE_LICENSE_REF` when reused; a
        `band` drawn from `CBRS_3_5GHZ`, `EBS_2_5GHZ` and `LTE_700MHZ`; the block's
        `channel_center_mhz` between 600.0 and 6000.0 inclusive to one decimal place;
        its `channel_width_mhz` between 5.0 and 200.0 inclusive to one decimal place;
        the `max_eirp_dbm` ceiling between 20.0 and 65.0 inclusive to one decimal
        place; the regulator's `license_area_code`; and a validity window given as an
        inclusive `effective_from` and an exclusive `effective_to`, where
        `effective_to` must be strictly later than `effective_from`."
        PRD §2.7: "**Request-body shape** — required fields present, types correct,
        enum values drawn from the declared members, numeric values inside their
        declared ranges and decimal precision (including latitude and longitude
        ranges, non-negative traffic volumes, a reservation life between 1 and 30 days
        inclusive, and a measured throughput supplied on a transport-circuit
        acceptance), else `ERR_VALIDATION` (400)."
        PRD §2.7: "**Temporal and plant-readiness rules** — `ERR_INTERVAL_INVALID`,
        `ERR_OUTAGE_WINDOW_OVERLAP`, `ERR_USAGE_DATE_OUT_OF_CYCLE`,
        `ERR_RETURN_WINDOW_OPEN`, `ERR_BACKHAUL_NOT_ACCEPTED`, and
        `ERR_TOWER_HAS_ACTIVE_SUBSCRIBERS`, all HTTP 409."

        Design: Corner/entities/spectrum_license_rejects_effective_to_not_after_effective_from
        """
        payload = create_spectrum_license_payload(
            license_ref="CBRS-PAL-8888",
            band="CBRS_3_5GHZ",
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-01-01T00:00:00Z",
        )

        rejected = api.create_spectrum_license(payload, network_engineer)
        # An equal pair is not a valid window; the PRD states the constraint without
        # naming its rung, so either the shape rung or the temporal rung is faithful.
        error_id = validate_error_is_one_of(
            rejected,
            [ApiErrorId.ERR_VALIDATION.value, ApiErrorId.ERR_INTERVAL_INVALID.value],
        )
        assert rejected.status_code == HTTP_STATUS_CODES[ApiErrorId(error_id)], (
            f"{error_id} carries HTTP {HTTP_STATUS_CODES[ApiErrorId(error_id)]}, got "
            f"{rejected.status_code}"
        )

        # The refusal stored nothing: the same license_ref accepts a well-formed window.
        accepted = dict(payload, effective_to="2027-01-01T00:00:00Z")
        license_ = validate_success(
            api.create_spectrum_license(accepted, network_engineer), 201
        )
        assert license_["license_ref"] == "CBRS-PAL-8888", (
            "the rejected create must not have reserved the license_ref"
        )


# ==========================================================================
# Unresolvable identifiers
# ==========================================================================


class TestReferenceResolution:
    def test_get_unknown_subscriber_id_reports_subscriber_not_found(
        self, api, billing_admin
    ):
        """PRD §2.6: "The 404 code is the one belonging to the segment that failed: a
        missing tower yields `ERR_TOWER_NOT_FOUND`, a missing transport circuit
        `ERR_CIRCUIT_NOT_FOUND`, a missing spectrum licence `ERR_LICENSE_NOT_FOUND`, a
        missing sector `ERR_SECTOR_NOT_FOUND`, a missing coordination record
        `ERR_COORDINATION_NOT_FOUND`, a missing service plan `ERR_PLAN_NOT_FOUND`, a
        missing qualification `ERR_REQUEST_NOT_FOUND`, a missing capacity reservation
        `ERR_HOLD_NOT_FOUND`, a missing account `ERR_SUBSCRIBER_NOT_FOUND`, a missing
        install work order `ERR_WORK_ORDER_NOT_FOUND`, a missing equipment assignment
        `ERR_ASSIGNMENT_NOT_FOUND`, a missing outage record `ERR_OUTAGE_NOT_FOUND`,
        and a missing service-level credit `ERR_CREDIT_NOT_FOUND`."
        PRD §2.2: "The `message` provides a human-readable explanation of what went
        wrong."

        Design: Corner/entities/get_unknown_subscriber_id_returns_subscriber_not_found
        """
        response = api.get_subscriber(UNUSED_UUID, billing_admin)

        error = validate_error(response, ApiErrorId.ERR_SUBSCRIBER_NOT_FOUND.value, 404)
        assert isinstance(error["message"], str) and error["message"].strip(), (
            f"the error carries a human-readable message, got {error.get('message')!r}"
        )

    def test_circuit_create_against_an_unknown_tower_id_reports_tower_not_found(
        self, api, network_engineer
    ):
        """PRD §2.6: "Identifiers carried in a request body are resolved after every
        path identifier has resolved, and they are checked in the order the endpoint's
        input fields are listed."
        PRD §2.6: "The 404 code is the one belonging to the segment that failed: a
        missing tower yields `ERR_TOWER_NOT_FOUND`, a missing transport circuit
        `ERR_CIRCUIT_NOT_FOUND`, a missing spectrum licence `ERR_LICENSE_NOT_FOUND`, a
        missing sector `ERR_SECTOR_NOT_FOUND`, a missing coordination record
        `ERR_COORDINATION_NOT_FOUND`, a missing service plan `ERR_PLAN_NOT_FOUND`, a
        missing qualification `ERR_REQUEST_NOT_FOUND`, a missing capacity reservation
        `ERR_HOLD_NOT_FOUND`, a missing account `ERR_SUBSCRIBER_NOT_FOUND`, a missing
        install work order `ERR_WORK_ORDER_NOT_FOUND`, a missing equipment assignment
        `ERR_ASSIGNMENT_NOT_FOUND`, a missing outage record `ERR_OUTAGE_NOT_FOUND`,
        and a missing service-level credit `ERR_CREDIT_NOT_FOUND`."
        PRD §2.7: "**Body-reference existence** — every identifier in the body
        resolves, in field order, else the matching 404 of §2.6."
        PRD §3.1: "A `circuit_ref` already in use on another circuit is refused with
        `ERR_DUPLICATE_CIRCUIT_REF`."

        Design: Corner/entities/backhaul_circuit_create_with_unknown_tower_id_returns_tower_not_found
        """
        payload = create_backhaul_circuit_payload(
            UNUSED_UUID,
            carrier_name="Prairie Fiber",
            circuit_ref="PF-CIR-8801",
            committed_mbps=500,
            monthly_cost_cents=120000,
        )

        rejected = api.create_backhaul_circuit(payload, network_engineer)
        validate_error(rejected, ApiErrorId.ERR_TOWER_NOT_FOUND.value, 404)

        # No circuit row was written, so PF-CIR-8801 is still free on a real tower.
        tower = create_tower(site_code="RB-TWR-101", lease_start_date="2026-07-01")
        accepted = dict(payload, tower_id=tower["id"])
        circuit = validate_success(
            api.create_backhaul_circuit(accepted, network_engineer), 201
        )
        assert circuit["circuit_ref"] == "PF-CIR-8801", (
            "the refused create must not have reserved the circuit_ref"
        )
        assert circuit["tower_id"] == tower["id"]


# ==========================================================================
# Metered days: immutable observations, one per account per day
# ==========================================================================


class TestUsageRecordImmutability:
    def test_re_posting_the_same_usage_date_is_refused_and_the_stored_day_is_unchanged(
        self, api, billing_admin
    ):
        """PRD §3.8: "Metered days are the one record type in this product that
        carries no `updated_at` and no `version`, as noted in §2.5: they are immutable
        observations, never edited."
        PRD §3.8: "Only one record may exist per account per day, so a second record
        for the same `subscriber_id` and `usage_date` is refused with
        `ERR_DUPLICATE_USAGE_RECORD`."
        PRD §3.8: "Each record is stamped with an `ingest_sequence` from a system
        counter that increases by one per record ingested, which fixes the processing
        order when two records share a `usage_date`, and its `total_gb` is derived as
        `downstream_gb` plus `upstream_gb` to one decimal place. A record also reports
        `in_current_cycle`, true when its `usage_date` falls inside the account's
        current cycle window."
        PRD §3.8: "The cycle is breached when `cycle_usage_gb` is **strictly greater**
        than the plan's `soft_cap_gb`; usage landing exactly on the cap is not a
        breach."
        PRD §3.8: "While `STANDARD`, `effective_downstream_mbps` is simply the plan's
        `downstream_mbps`."

        Design: Corner/entities/usage_record_is_immutable_re_posting_the_same_day_is_rejected
        """
        scenario = setup_active_subscriber()
        subscriber_id = scenario["subscriber"]["id"]
        plan = scenario["plan"]
        assert plan["soft_cap_gb"] == pytest.approx(600.0, abs=0.05), (
            f"Setup failed: the reference plan caps at 600.0 GB, got {plan['soft_cap_gb']}"
        )
        advance_clock(days=5)

        first = ingest_usage(subscriber_id, "2026-08-03", 300.0, 0.0)
        second = ingest_usage(subscriber_id, "2026-08-04", 250.0, 50.0)
        assert_usage_record(first)
        assert_usage_record(second)
        assert first["in_current_cycle"] is True, (
            "2026-08-03 falls inside the account's opening cycle"
        )
        assert second["in_current_cycle"] is True, (
            "2026-08-04 falls inside the account's opening cycle"
        )
        assert second["ingest_sequence"] == first["ingest_sequence"] + 1, (
            "the ingest counter increases by one per record ingested, got "
            f"{first['ingest_sequence']} then {second['ingest_sequence']}"
        )

        # Re-posting 2026-08-03 with a different volume is a duplicate, not an edit.
        rejected = api.create_usage_record(
            subscriber_id,
            usage_record_payload("2026-08-03", 500.0, 0.0),
            billing_admin,
        )
        validate_error(rejected, ApiErrorId.ERR_DUPLICATE_USAGE_RECORD.value, 409)

        rows, meta = validate_paginated(
            api.list_usage_records(
                subscriber_id, billing_admin, params={"limit": 100, "offset": 0}
            )
        )
        assert meta["total_count"] == 2, (
            f"the refused re-post created no third record, got {meta['total_count']}"
        )
        by_date = {row["usage_date"]: row for row in rows}
        assert set(by_date) == {"2026-08-03", "2026-08-04"}, (
            f"exactly the two metered days remain, got {sorted(by_date)}"
        )
        kept = by_date["2026-08-03"]
        assert_usage_record(kept)
        assert kept["id"] == first["id"], (
            "the stored 2026-08-03 record is the original one, not a replacement"
        )
        assert kept["downstream_gb"] == pytest.approx(300.0, abs=0.05), (
            f"the stored day keeps its original 300.0 GB, got {kept['downstream_gb']}"
        )
        assert kept["upstream_gb"] == pytest.approx(0.0, abs=0.05)
        assert kept["total_gb"] == pytest.approx(300.0, abs=0.05), (
            f"total_gb is 300.0 plus 0.0, got {kept['total_gb']}"
        )
        assert kept["ingest_sequence"] == first["ingest_sequence"], (
            "an immutable observation keeps its ingest_sequence"
        )

        subscriber = validate_success(
            api.get_subscriber(subscriber_id, billing_admin), 200
        )
        assert_subscriber(subscriber)
        assert subscriber["cycle_usage_gb"] == pytest.approx(600.0, abs=0.05), (
            "the cycle totals 300.0 plus 300.0, not the 800.0 an overwrite would have "
            f"produced, got {subscriber['cycle_usage_gb']}"
        )
        assert subscriber["usage_priority"] == "STANDARD", (
            "usage landing exactly on the 600.0 GB cap is not a breach, got "
            f"{subscriber['usage_priority']!r}"
        )
        assert subscriber["effective_downstream_mbps"] == pytest.approx(
            float(plan["downstream_mbps"]), abs=0.05
        ), (
            "a STANDARD account keeps the plan's downstream_mbps, got "
            f"{subscriber['effective_downstream_mbps']}"
        )


# ==========================================================================
# Coordination: one record joining two sectors on two towers
# ==========================================================================


class TestCoordinationTopology:
    def test_coordination_joins_two_towers_and_is_listed_on_the_requester_side_only(
        self, api, network_engineer, capacity_planner
    ):
        """PRD §3.4: "A `NetworkEngineer` opens a coordination by naming the
        `requesting_sector_id` that wants the change, the `neighbor_sector_id` being
        asked to tolerate it, and the proposal itself: `proposed_channel_center_mhz`,
        `proposed_channel_width_mhz`, `proposed_eirp_dbm`, a `guard_band_mhz` between
        0.0 and 20.0 inclusive to one decimal place expressing how much clear spectrum
        the requester will leave on each side of its block, and an `effective_from`
        instant at which the coordinated parameters would take effect once agreed."
        PRD §3.4: "A newly opened coordination sits in `REQUESTED` `status` with
        `round_number` at 1 and `decision_note`, `decided_by_user_id` and
        `last_response_at` all absent."
        PRD §3.4: "When the circular separation is **60 degrees or more** the beams
        are considered to be pointing away from each other and no spectrum
        disjointness is required at all — the proposal passes this test regardless of
        channel."
        PRD §2.3: "The coordination listing for a sector filters on `status`, and the
        global coordination listing filters on `requesting_sector_id`,
        `neighbor_sector_id`, and `status`."
        PRD §4: "GET | `/sectors/{id}/interference-coordinations` | List the
        coordination records in which this sector is the requester."

        Design: Corner/entities/interference_coordination_links_two_sectors_on_different_towers
        """
        pair = setup_neighbor_sectors()
        sector_a = pair["local"]["sector"]
        sector_b = pair["neighbor"]["sector"]
        assert sector_a["tower_id"] != sector_b["tower_id"], (
            "Setup failed: the two sectors must stand on different towers"
        )
        # 90.0 against 270.0 is 180 degrees apart, so the beams point away from each
        # other and the guard-band test imposes no channel constraint.
        assert abs(sector_a["azimuth_deg"] - sector_b["azimuth_deg"]) == pytest.approx(
            180.0, abs=0.05
        ), "Setup failed: the reference pair points in opposite directions"

        payload = create_coordination_payload(
            sector_a["id"],
            sector_b["id"],
            proposed_channel_center_mhz=3570.0,
            proposed_channel_width_mhz=20.0,
            proposed_eirp_dbm=42.0,
            guard_band_mhz=2.0,
            effective_from="2026-09-01T00:00:00Z",
        )
        coordination = validate_success(
            api.create_coordination(payload, network_engineer), 201
        )

        assert_interference_coordination(coordination)
        assert coordination["requesting_sector_id"] == sector_a["id"], (
            "requesting_sector_id is the sector that wants the change, got "
            f"{coordination['requesting_sector_id']}"
        )
        assert coordination["neighbor_sector_id"] == sector_b["id"], (
            "neighbor_sector_id is the sector asked to tolerate it, got "
            f"{coordination['neighbor_sector_id']}"
        )
        assert coordination["status"] == "REQUESTED", (
            f"a newly opened coordination sits in REQUESTED, got {coordination['status']!r}"
        )
        assert coordination["round_number"] == 1, (
            f"round_number opens at 1, got {coordination['round_number']}"
        )
        assert coordination["version"] == 1, (
            f"version starts at 1, got {coordination['version']}"
        )
        assert coordination.get("decision_note") is None, (
            f"decision_note is absent until a response, got {coordination.get('decision_note')!r}"
        )
        assert coordination.get("decided_by_user_id") is None, (
            "decided_by_user_id is absent until a response, got "
            f"{coordination.get('decided_by_user_id')!r}"
        )
        assert coordination.get("last_response_at") is None, (
            "last_response_at is absent until a response, got "
            f"{coordination.get('last_response_at')!r}"
        )

        # The requester's own sector listing carries the record.
        requester_rows, requester_meta = validate_paginated(
            api.list_sector_coordinations(
                sector_a["id"], network_engineer, params={"limit": 50, "offset": 0}
            )
        )
        assert requester_meta["total_count"] == 1, (
            "the requesting sector lists the coordination it opened, got "
            f"{requester_meta['total_count']}"
        )
        assert requester_rows[0]["id"] == coordination["id"]

        # The neighbour is not the requester, so its own sector listing is empty; the
        # neighbour side of the junction is reached through the global filter instead.
        neighbor_rows, neighbor_meta = validate_paginated(
            api.list_sector_coordinations(
                sector_b["id"], capacity_planner, params={"limit": 50, "offset": 0}
            )
        )
        assert neighbor_meta["total_count"] == 0, (
            "the sector listing carries only records in which the sector is the "
            f"requester, got {neighbor_meta['total_count']}"
        )
        assert neighbor_rows == [], f"expected an empty page, got {neighbor_rows}"

        global_rows, global_meta = validate_paginated(
            api.list_coordinations(
                network_engineer,
                params={"neighbor_sector_id": sector_b["id"], "limit": 50, "offset": 0},
            )
        )
        assert global_meta["total_count"] == 1, (
            "the global listing filtered on neighbor_sector_id finds the same row, got "
            f"{global_meta['total_count']}"
        )
        assert global_rows[0]["id"] == coordination["id"], (
            "the junction is reachable from the neighbour side through the global filter"
        )
        assert global_rows[0]["requesting_sector_id"] == sector_a["id"]

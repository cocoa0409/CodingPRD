"""Connected-unit registration defaults, serial uniqueness, site-order linkage and lazy expiry."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    connected_unit_payload,
    create_connected_unit,
    create_equipment_model,
    read_connected_unit,
    read_site_order,
    set_clock,
    setup_covered_unit,
    setup_listed_model,
    setup_program_with_site_order,
    validate_error,
    validate_paginated,
    validate_success,
)

PLAIN_RELEASE = {
    "model_overrides": {"supported_controls_packages": ["STANDARD_DIAL"]},
    "config_overrides": {
        "option_codes": [],
        "controls_package": "STANDARD_DIAL",
        "branding_kit": "NONE",
    },
}


class TestRegistrationDefaults:
    def test_a_new_unit_is_stamped_with_the_declared_fleet_defaults(
        self, api, connected_ops_engineer
    ):
        """Registration without a site order stamps 1.0.0, generation 1, zero counters and 100.

        PRD §3.8: "A new unit reports `service_program_status` `PENDING_INSTALL`,
        `firmware_version` `1.0.0`, `recipe_book_version` 1, `fault_count_30d` and
        `missed_heartbeat_count` at zero, `coverage_start_date`, `coverage_end_date` and
        `grace_expires_on` null, and `reserve_initial_cents`, `reserve_balance_cents` and
        `claims_paid_cents` all at zero, with its `health_score` computed immediately."

        Design: Corner/entities/connected_unit_creation_applies_firmware_recipe_and_telemetry_defaults
        """
        set_clock()
        model = create_equipment_model()

        unit = validate_success(
            api.create_connected_unit(
                connected_unit_payload(model["id"], "SN-1"), connected_ops_engineer
            ),
            201,
        )

        assert unit["firmware_version"] == "1.0.0", (
            f"a new unit ships on 1.0.0, got {unit['firmware_version']}"
        )
        assert unit["recipe_book_version"] == 1, (
            f"and on recipe generation 1, got {unit['recipe_book_version']}"
        )
        assert unit["health_score"] == 100, (
            "no campaign has completed for the model, so there is no currency bonus and "
            f"the score is exactly 100 rather than 105, got {unit['health_score']}"
        )
        assert unit["site_order_id"] is None, (
            "the optional site order was not supplied, got "
            f"{unit['site_order_id']}"
        )
        assert unit["service_program_status"] == "PENDING_INSTALL", (
            f"coverage has not been activated yet, got {unit['service_program_status']}"
        )

        stored = read_connected_unit(unit["id"])
        assert stored["fault_count_30d"] == 0, (
            f"the fault counter starts at zero, got {stored['fault_count_30d']}"
        )
        assert stored["missed_heartbeat_count"] == 0, (
            f"as does the heartbeat counter, got {stored['missed_heartbeat_count']}"
        )
        assert stored["reserve_initial_cents"] == 0, (
            "no reserve exists before activation, got "
            f"{stored['reserve_initial_cents']}"
        )
        assert stored["reserve_balance_cents"] == 0, (
            f"nor any balance, got {stored['reserve_balance_cents']}"
        )
        assert stored["claims_paid_cents"] == 0, (
            f"and nothing has been paid, got {stored['claims_paid_cents']}"
        )
        assert stored["coverage_start_date"] is None, (
            f"the coverage dates are null before activation, got "
            f"{stored['coverage_start_date']}"
        )
        assert stored["coverage_end_date"] is None, (
            f"including the end date, got {stored['coverage_end_date']}"
        )
        assert stored["grace_expires_on"] is None, (
            f"and the grace stamp, got {stored['grace_expires_on']}"
        )


class TestUnknownUnitRead:
    def test_an_unknown_unit_id_answers_with_the_connected_not_found_error(
        self, api, connected_ops_engineer
    ):
        """A well-formed but unknown identifier returns the connected-domain 404 envelope.

        PRD §2.9: "Path identifiers are resolved left to right, and the first identifier
        that names no existing row determines the 404 the caller receives; the server does
        not look further right in the path once a segment has failed."

        Design: Corner/entities/connected_unit_get_with_unknown_id_returns_connected_resource_not_found
        """
        set_clock()

        missing = api.get_connected_unit(NON_EXISTENT_UUID, connected_ops_engineer)
        validate_error(missing, ApiErrorId.ERR_CONNECTED_RESOURCE_NOT_FOUND.value, 404)

        body = missing.json()
        assert body["response_type"] == "error", (
            f"the 404 uses the error envelope, got {body['response_type']}"
        )
        assert isinstance(body["data"]["message"], str) and body["data"]["message"], (
            f"and carries a non-empty message, got {body['data'].get('message')!r}"
        )

        empty, meta = validate_paginated(api.list_connected_units(connected_ops_engineer))
        assert meta["total_count"] == 0, (
            f"no unit was created by the refused read, got {meta['total_count']}"
        )
        assert empty == [], f"the fleet listing is empty, got {empty}"


class TestSerialUniqueness:
    def test_a_serial_number_cannot_be_reused_on_a_different_model(
        self, api, connected_ops_engineer
    ):
        """SN-1 registered against one model blocks SN-1 against another.

        PRD §3.8: "A `ConnectedOpsEngineer` registers a **connected unit** into the
        monitoring fleet with its `equipment_model_id`, its factory `serial_number`
        (unique across the fleet; a collision is rejected with
        `ERR_DUPLICATE_SERIAL_NUMBER`), the `service_tier` purchased for it — either
        `BASE` or `EXTENDED_PLUS` — and optionally the `site_order_id` that shipped it,
        which is null for an aftermarket unit registered outside any construction
        programme."

        Design: Corner/validations/serial_number_uniqueness_spans_the_whole_fleet_not_just_one_model
        """
        set_clock()
        fryer = create_equipment_model()
        oven = create_equipment_model(
            model_code="OVN-500", name="Combi Oven 500", category="COMBI_OVEN"
        )
        first = create_connected_unit(fryer["id"], "SN-1")
        assert first["equipment_model_id"] == fryer["id"], (
            "the first unit belongs to the fryer, got "
            f"{first['equipment_model_id']}"
        )

        collision = api.create_connected_unit(
            connected_unit_payload(oven["id"], "SN-1"), connected_ops_engineer
        )
        validate_error(collision, ApiErrorId.ERR_DUPLICATE_SERIAL_NUMBER.value, 409)

        distinct = validate_success(
            api.create_connected_unit(
                connected_unit_payload(oven["id"], "SN-2"), connected_ops_engineer
            ),
            201,
        )
        assert distinct["equipment_model_id"] == oven["id"], (
            "a fresh serial on the second model is accepted, got "
            f"{distinct['equipment_model_id']}"
        )

        _data, meta = validate_paginated(
            api.list_connected_units(connected_ops_engineer, {"limit": 100})
        )
        assert meta["total_count"] == 2, (
            "the refused registration left no row behind, so the fleet holds two units, "
            f"got {meta['total_count']}"
        )


class TestSiteOrderLinkage:
    def test_a_unit_registered_against_a_site_order_is_reachable_through_that_filter(
        self, api, connected_ops_engineer
    ):
        """The linked unit answers the site-order filter; the aftermarket unit does not.

        PRD §3.8: "A `ConnectedOpsEngineer` registers a **connected unit** into the
        monitoring fleet with its `equipment_model_id`, its factory `serial_number`
        (unique across the fleet; a collision is rejected with
        `ERR_DUPLICATE_SERIAL_NUMBER`), the `service_tier` purchased for it — either
        `BASE` or `EXTENDED_PLUS` — and optionally the `site_order_id` that shipped it,
        which is null for an aftermarket unit registered outside any construction
        programme."

        Design: Corner/endpoints/connected_unit_links_to_its_site_order_and_is_reachable_through_that_filter
        """
        set_clock()
        state = setup_program_with_site_order(**PLAIN_RELEASE)
        model_id = state["model"]["id"]
        site_order_id = state["site_order"]["id"]

        linked = validate_success(
            api.create_connected_unit(
                connected_unit_payload(
                    model_id, "SN-LINKED", site_order_id=site_order_id
                ),
                connected_ops_engineer,
            ),
            201,
        )
        loose = validate_success(
            api.create_connected_unit(
                connected_unit_payload(model_id, "SN-LOOSE"), connected_ops_engineer
            ),
            201,
        )

        assert linked["site_order_id"] == site_order_id, (
            "the optional association is stored as supplied, got "
            f"{linked['site_order_id']}"
        )
        assert linked["service_program_status"] == "PENDING_INSTALL", (
            "linking a unit to a site order does not activate coverage, got "
            f"{linked['service_program_status']}"
        )
        assert loose["site_order_id"] is None, (
            "an aftermarket unit on the same model has no association, got "
            f"{loose['site_order_id']}"
        )

        data, meta = validate_paginated(
            api.list_connected_units(
                connected_ops_engineer, {"site_order_id": site_order_id, "limit": 100}
            )
        )
        assert meta["total_count"] == 1, (
            "only the linked unit answers the filter, got "
            f"{meta['total_count']}"
        )
        returned = [unit["id"] for unit in data]
        assert linked["id"] in returned, (
            f"the linked unit must appear in the filtered page, got {returned}"
        )
        assert loose["id"] not in returned, (
            f"and the unlinked unit must not, got {returned}"
        )

        site_order = read_site_order(site_order_id)
        assert site_order["fulfillment_status"] == "PENDING", (
            "registering units does not advance the site order's fulfilment dimension, "
            f"got {site_order['fulfillment_status']}"
        )


class TestLazyCoverageExpiry:
    def test_coverage_expires_on_the_next_read_at_exactly_the_term_end(self):
        """A read one second before the term end shows ACTIVE and one at it shows EXPIRED.

        PRD §3.9: "Expiry is evaluated lazily rather than swept: on any read or write that
        touches a unit, and on every clock advance, a unit moves `ACTIVE → EXPIRED` or
        `EXTENDED → EXPIRED` once the clock has reached or passed `coverage_end_date`, and
        a unit in the grace state moves `GRACE → EXPIRED` once the clock has reached or
        passed `grace_expires_on`; either transition refreshes the unit's `updated_at`."

        Design: Corner/state_machines/coverage_lazily_expires_when_the_clock_reaches_coverage_end_date
        """
        set_clock()
        listed = setup_listed_model()
        unit = setup_covered_unit(listed["model"]["id"], "SN-1", "BASE")

        assert unit["service_program_status"] == "ACTIVE", (
            f"activation makes coverage live, got {unit['service_program_status']}"
        )
        assert unit["coverage_end_date"].startswith("2027-08-01T00:00:00"), (
            "a BASE term runs 365 days from the 2026-08-01 activation, got "
            f"{unit['coverage_end_date']}"
        )

        set_clock("2027-07-31T23:59:59Z")
        before = read_connected_unit(unit["id"])
        assert before["service_program_status"] == "ACTIVE", (
            "one second before the term end the unit is still covered, got "
            f"{before['service_program_status']}"
        )

        set_clock("2027-08-01T00:00:00Z")
        after = read_connected_unit(unit["id"])
        assert after["service_program_status"] == "EXPIRED", (
            "the comparison is inclusive, so at the term end the read itself expires the "
            f"unit, got {after['service_program_status']}"
        )
        assert after["reserve_balance_cents"] == 250000, (
            "expiry does not touch the reserve, got "
            f"{after['reserve_balance_cents']}"
        )
        assert after["claims_paid_cents"] == 0, (
            f"nothing was ever claimed, got {after['claims_paid_cents']}"
        )

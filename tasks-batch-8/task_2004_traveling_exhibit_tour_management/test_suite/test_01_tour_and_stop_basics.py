"""Tour creation defaults, required-field validation, and basic reads (PRD §2.8, §3.1, §3.2)."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_tour,
    assert_tour_stop,
    create_tour_payload,
    create_venue_payload,
    create_stop_payload,
    create_and_open_booking,
    create_venue,
    current_tour_version,
)

TM = TEST_USERS["tour_manager_headers"]


class TestTourCreationDefaults:
    def test_tour_creation_defaults(self, api):
        """PRD §3.1: "A new tour is born in `DRAFT` with its three ledger totals —
        `total_billed_cents`, `total_collected_cents`, and `total_waived_cents` —
        all initialized to zero."
        PRD §2.5: "`id` (string): a server-minted UUID with no type prefix."

        Design: Corner/entities/tour_creation_defaults_and_system_fields
        """
        res = api.create_tour(
            create_tour_payload(
                title="Origami",
                exhibit_code="ORIG-2026",
                crate_count=3,
                declared_value_cents=1000000,
                refurbishment_gap_days=4,
            ),
            TM,
        )
        tour = validate_success(res, 201)
        assert_tour(tour)
        assert tour["status"] == "DRAFT"
        assert tour["total_billed_cents"] == 0
        assert tour["total_collected_cents"] == 0
        assert tour["total_waived_cents"] == 0
        assert tour["version"] == 1

    def test_tour_creation_id_has_no_type_prefix(self, api):
        """PRD §2.5: "`id` (string): a server-minted UUID with no type prefix."

        Design: Corner/entities/tour_creation_defaults_and_system_fields
        """
        res = api.create_tour(create_tour_payload(), TM)
        tour = validate_success(res, 201)
        assert "_" not in tour["id"].replace("-", ""), (
            "id must be a bare UUID without a type prefix"
        )


class TestTourRequiredFields:
    @pytest.mark.parametrize(
        "missing_field",
        ["title", "exhibit_code", "crate_count", "declared_value_cents", "refurbishment_gap_days"],
    )
    def test_missing_required_field_rejected(self, api, missing_field):
        """PRD §2.8: "Independent of this ordering, a payload that is missing a
        required field, carries an unrecognized enum value, or is otherwise
        malformed is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/tour_missing_required_field_returns_invalid_request
        """
        payload = create_tour_payload()
        del payload[missing_field]
        res = api.create_tour(payload, TM)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestTourNotFound:
    def test_get_nonexistent_tour(self, api):
        """PRD §2.8: "The server resolves path identifiers left to right — tour
        first, then the stop or shipment within it, then the report or claim
        within that — and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at
        the first identifier that does not correspond to an existing resource."

        Design: Corner/entities/get_nonexistent_tour_returns_not_found
        """
        res = api.get_tour(NON_EXISTENT_UUID, TM)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)


class TestTourInitialState:
    def test_tour_initial_state_is_draft(self, api):
        """PRD §3.1: "A new tour is born in `DRAFT` with its three ledger totals —
        `total_billed_cents`, `total_collected_cents`, and `total_waived_cents` —
        all initialized to zero."

        Design: Corner/state_machines/tour_initial_state_is_draft
        """
        tour = validate_success(api.create_tour(create_tour_payload(), TM), 201)
        fetched = validate_success(api.get_tour(tour["id"], TM), 200)
        assert fetched["status"] == "DRAFT"


class TestStopWindowMalformed:
    def test_open_date_before_install_start_rejected(self, api):
        """PRD §3.2: "Fourth and last, window shape: the four timestamps must
        strictly increase from `install_start` to `open_date` to `close_date` to
        `teardown_end`, or the booking fails with `ERR_WINDOW_MALFORMED`
        (HTTP 422)."

        Design: Corner/entities/stop_window_malformed_rejected
        """
        tour, _ = create_and_open_booking()
        venue = create_venue()
        tv = current_tour_version(tour["id"])
        res = api.create_stop(
            tour["id"],
            create_stop_payload(
                venue["id"],
                tv,
                install_start="2026-09-10T00:00:00Z",
                open_date="2026-09-05T00:00:00Z",
                close_date="2026-10-03T00:00:00Z",
                teardown_end="2026-10-06T00:00:00Z",
            ),
            TM,
        )
        validate_error(res, ApiErrorId.ERR_WINDOW_MALFORMED)

    def test_close_date_before_open_date_rejected(self, api):
        """PRD §3.2: "Fourth and last, window shape: the four timestamps must
        strictly increase from `install_start` to `open_date` to `close_date` to
        `teardown_end`, or the booking fails with `ERR_WINDOW_MALFORMED`
        (HTTP 422)."

        Design: Corner/entities/stop_window_malformed_rejected
        """
        tour, _ = create_and_open_booking()
        venue = create_venue()
        tv = current_tour_version(tour["id"])
        res = api.create_stop(
            tour["id"],
            create_stop_payload(
                venue["id"],
                tv,
                install_start="2026-09-01T00:00:00Z",
                open_date="2026-09-05T00:00:00Z",
                close_date="2026-09-04T00:00:00Z",
                teardown_end="2026-10-06T00:00:00Z",
            ),
            TM,
        )
        validate_error(res, ApiErrorId.ERR_WINDOW_MALFORMED)


class TestStopSupervisionRequired:
    def test_non_climate_controlled_venue_forces_supervision(self, api):
        """PRD §3.2: "its `supervision_required` flag is computed on the spot:
        true whenever the host venue is not `climate_controlled`, or the tour's
        `crate_count` exceeds the climate-exempt crate ceiling."

        Design: Corner/entities/stop_supervision_required_computed_field
        """
        tour, _ = create_and_open_booking()
        venue = create_venue(climate_controlled=False)
        tv = current_tour_version(tour["id"])
        res = api.create_stop(tour["id"], create_stop_payload(venue["id"], tv), TM)
        stop = validate_success(res, 201)
        assert_tour_stop(stop)
        assert stop["supervision_required"] is True

    def test_climate_controlled_venue_below_crate_ceiling_not_required(self, api):
        """PRD §3.2: "its `supervision_required` flag is computed on the spot:
        true whenever the host venue is not `climate_controlled`, or the tour's
        `crate_count` exceeds the climate-exempt crate ceiling."

        Design: Corner/entities/stop_supervision_required_computed_field
        """
        tour, _ = create_and_open_booking()
        venue = create_venue(climate_controlled=True)
        tv = current_tour_version(tour["id"])
        res = api.create_stop(tour["id"], create_stop_payload(venue["id"], tv), TM)
        stop = validate_success(res, 201)
        assert stop["supervision_required"] is False

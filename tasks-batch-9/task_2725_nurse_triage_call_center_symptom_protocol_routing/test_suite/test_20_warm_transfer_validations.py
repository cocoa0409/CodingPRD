"""Location capture, the confidence threshold and the PSAP handshake order."""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_instant


@pytest.fixture
def emergency_call_awaiting_its_transfer(world):
    """Acuity 86 EMERGENCY_911 advice, so the call demands a warm transfer."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a",),
        protocol={"base_severity": 62},
    )
    call, assessment, disposition = world.dispositioned_call(
        "EMERGENCY_911", "nurse_a", red_flag_count=3, reason_text="crushing chest pain"
    )
    return call, assessment, disposition


class TestWarmTransferLocationCapture:
    def test_an_out_of_range_latitude_is_an_invalid_location(
        self, world, emergency_call_awaiting_its_transfer
    ):
        """PRD §3.7: "A latitude outside minus ninety through ninety degrees, a
        longitude outside minus one hundred eighty through one hundred eighty degrees,
        or an empty address line is refused with `ERR_INVALID_LOCATION`."

        Design: Corner/validations/warm_transfer_creation_rejects_bad_geography_and_a_state_mismatch
        """
        call, assessment, _ = emergency_call_awaiting_its_transfer
        assert assessment["acuity_score"] == 86
        assert world.call(call["id"])["requires_warm_transfer"] is True

        response = world.api.create_warm_transfer(
            call["id"],
            f.warm_transfer_payload(
                psap_center_code="PSAP-SFO-01",
                location_address_line="12 Mission Street",
                location_lat=91.0,
                location_lng=-122.4194,
            ),
            world.nurse_headers("nurse_a"),
        )

        validate_error(response, ApiErrorId.ERR_INVALID_LOCATION, 422)

    def test_a_blank_address_line_is_also_an_invalid_location(
        self, world, emergency_call_awaiting_its_transfer
    ):
        """PRD §3.7: "`location_address_line`, the street address for dispatch, one to
        two hundred characters".

        Design: Corner/validations/warm_transfer_creation_rejects_bad_geography_and_a_state_mismatch
        """
        call, _, _ = emergency_call_awaiting_its_transfer

        response = world.api.create_warm_transfer(
            call["id"],
            f.warm_transfer_payload(
                psap_center_code="PSAP-SFO-01",
                location_address_line="",
                location_lat=37.7749,
                location_lng=-122.4194,
            ),
            world.nurse_headers("nurse_a"),
        )

        validate_error(response, ApiErrorId.ERR_INVALID_LOCATION, 422)

    def test_a_well_formed_address_in_the_wrong_state_is_a_mismatch(
        self, world, emergency_call_awaiting_its_transfer
    ):
        """PRD §3.7: "The `location_state_code` must equal the call's
        `caller_state_code`, because dispatch is routed on the caller's state of record;
        a mismatch is a data error rather than a routing choice and is refused with
        `ERR_LOCATION_STATE_MISMATCH`."

        Design: Corner/validations/warm_transfer_creation_rejects_bad_geography_and_a_state_mismatch
        """
        call, _, _ = emergency_call_awaiting_its_transfer

        response = world.api.create_warm_transfer(
            call["id"],
            f.warm_transfer_payload(
                psap_center_code="PSAP-LAS-01",
                location_address_line="480 Fremont Street",
                location_state_code="NV",
                location_lat=36.1699,
                location_lng=-115.1398,
            ),
            world.nurse_headers("nurse_a"),
        )

        validate_error(response, ApiErrorId.ERR_LOCATION_STATE_MISMATCH, 409)

    def test_the_first_valid_transfer_opens_at_initiated_with_nothing_attested(
        self, world, emergency_call_awaiting_its_transfer
    ):
        """PRD §3.7: "A created transfer starts at `status` `INITIATED` with
        `location_verified_by`, `location_confidence_pct` and `psap_incident_number` all
        absent."

        Design: Corner/validations/warm_transfer_creation_rejects_bad_geography_and_a_state_mismatch
        """
        call, _, _ = emergency_call_awaiting_its_transfer
        for payload in (
            f.warm_transfer_payload(location_lat=91.0),
            f.warm_transfer_payload(location_address_line=""),
            f.warm_transfer_payload(location_state_code="NV"),
        ):
            world.api.create_warm_transfer(
                call["id"], payload, world.nurse_headers("nurse_a")
            )

        transfer = world.open_warm_transfer(
            call["id"],
            "nurse_a",
            psap_center_code="PSAP-SFO-01",
            location_address_line="12 Mission Street",
            location_lat=37.7749,
            location_lng=-122.4194,
        )

        assert transfer["status"] == "INITIATED"
        assert transfer["location_confidence_pct"] is None
        assert transfer["location_verified_by"] is None
        assert transfer["psap_incident_number"] is None
        assert transfer["psap_center_code"] == "PSAP-SFO-01"
        assert transfer["location_source"] == "CALLER_STATED"
        _, meta = validate_paginated(
            world.api.list_call_warm_transfers(call["id"], world.admin, None)
        )
        assert meta["total_count"] == 1, "the three refusals left no rows behind"

    def test_a_second_transfer_while_one_is_in_play_is_already_open(
        self, world, emergency_call_awaiting_its_transfer
    ):
        """PRD §3.7: "Only one transfer may be in play per call at a time: a request is
        refused with `ERR_WARM_TRANSFER_ALREADY_OPEN` when a transfer for that call
        already sits at `INITIATED`, `LOCATION_CONFIRMED`, `ACCEPTED_BY_PSAP` or
        `HANDOFF_COMPLETE`."

        Design: Corner/validations/warm_transfer_creation_rejects_bad_geography_and_a_state_mismatch
        """
        call, _, _ = emergency_call_awaiting_its_transfer
        world.open_warm_transfer(
            call["id"],
            "nurse_a",
            psap_center_code="PSAP-SFO-01",
            location_address_line="12 Mission Street",
        )

        response = world.api.create_warm_transfer(
            call["id"],
            f.warm_transfer_payload(
                psap_center_code="PSAP-SFO-02",
                location_source="DEVICE_GPS",
                location_address_line="12 Mission Street",
            ),
            world.nurse_headers("nurse_a"),
        )

        validate_error(response, ApiErrorId.ERR_WARM_TRANSFER_ALREADY_OPEN, 409)
        assert world.call(call["id"])["warm_transfer_completed_at"] is None


@pytest.fixture
def initiated_transfer(world):
    """An EMERGENCY_911 call with one transfer sitting at INITIATED."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a",),
        protocol={"base_severity": 62},
    )
    call, _, _ = world.dispositioned_call(
        "EMERGENCY_911", "nurse_a", red_flag_count=3, reason_text="crushing chest pain"
    )
    transfer = world.open_warm_transfer(
        call["id"],
        "nurse_a",
        psap_center_code="PSAP-SFO-01",
        location_address_line="12 Mission Street",
        location_lat=37.7749,
        location_lng=-122.4194,
    )
    return call, transfer


class TestPsapHandshakeIsStrictlyOrdered:
    def test_a_response_or_a_handoff_before_the_readback_is_an_invalid_state(
        self, world, initiated_transfer
    ):
        """PRD §3.7: "Requesting any of the three transfer moves from a state that does
        not permit it is refused with `ERR_TRANSFER_INVALID_STATE`, and naming a
        transfer that does not exist is refused with `ERR_WARM_TRANSFER_NOT_FOUND`."

        Design: Corner/validations/warm_transfer_confirmation_and_handoff_enforce_confidence_and_order
        """
        _, transfer = initiated_transfer

        response_first = world.api.psap_response(
            transfer["id"],
            f.psap_response_payload(True, "SFO-2026-0801"),
            world.intake,
        )
        handoff_first = world.api.complete_handoff(
            transfer["id"], {}, world.nurse_headers("nurse_a")
        )

        validate_error(response_first, ApiErrorId.ERR_TRANSFER_INVALID_STATE, 409)
        validate_error(handoff_first, ApiErrorId.ERR_TRANSFER_INVALID_STATE, 409)

    def test_seventy_four_percent_confidence_is_below_the_readback_bar(
        self, world, initiated_transfer
    ):
        """PRD §3.7: "The only input is `location_confidence_pct`, between 0 and 100,
        and it must be at least 75; anything lower is refused with
        `ERR_LOCATION_CONFIDENCE_TOO_LOW`, so a transfer can never be offered to a
        dispatch centre on a guess."

        Design: Corner/validations/warm_transfer_confirmation_and_handoff_enforce_confidence_and_order
        """
        _, transfer = initiated_transfer

        response = world.api.confirm_transfer_location(
            transfer["id"],
            f.confirm_location_payload(74),
            world.nurse_headers("nurse_a"),
        )

        validate_error(response, ApiErrorId.ERR_LOCATION_CONFIDENCE_TOO_LOW, 422)
        assert world.warm_transfer(transfer["id"])["status"] == "INITIATED"

    def test_exactly_seventy_five_percent_confirms_the_location(
        self, world, initiated_transfer
    ):
        """PRD §3.7: "On success the transfer records `location_verified_by` as the
        acting nurse's identifier along with the supplied `location_confidence_pct`,
        moves to `LOCATION_CONFIRMED`, and increases its `version` by one."

        Design: Corner/validations/warm_transfer_confirmation_and_handoff_enforce_confidence_and_order
        """
        _, transfer = initiated_transfer
        world.api.confirm_transfer_location(
            transfer["id"],
            f.confirm_location_payload(74),
            world.nurse_headers("nurse_a"),
        )

        confirmed = world.confirm_location(transfer["id"], "nurse_a", 75)

        assert confirmed["status"] == "LOCATION_CONFIRMED"
        assert confirmed["location_confidence_pct"] == 75
        assert confirmed["location_verified_by"] == world.nurse_id("nurse_a")

    def test_the_accept_then_handoff_sequence_stamps_the_call(
        self, world, initiated_transfer
    ):
        """PRD §3.7: "Completion sets the transfer's `status` to `HANDOFF_COMPLETE` and
        increases its `version` by one, and it also stamps `warm_transfer_completed_at`
        on the call with the current logical-clock instant and increases the call's
        `version` by one."

        Design: Corner/validations/warm_transfer_confirmation_and_handoff_enforce_confidence_and_order
        """
        call, transfer = initiated_transfer
        world.confirm_location(transfer["id"], "nurse_a", 75)

        accepted = world.psap_response(transfer["id"], True, "SFO-2026-0801")
        final = world.complete_handoff(transfer["id"], "nurse_a")

        assert accepted["status"] == "ACCEPTED_BY_PSAP"
        assert accepted["psap_incident_number"] == "SFO-2026-0801"
        assert final["status"] == "HANDOFF_COMPLETE"
        assert_instant(
            world.call(call["id"])["warm_transfer_completed_at"],
            "2026-08-03T14:30:00Z",
            "warm_transfer_completed_at",
        )


class TestWarmTransferOnANonEmergencyCall:
    def test_ed_now_advice_leaves_the_transfer_not_indicated(self, world):
        """PRD §3.7: "Opening a transfer is reserved to the call's assigned nurse and is
        only permitted while the call's `requires_warm_transfer` is true; a call that
        does not need one is refused with `ERR_WARM_TRANSFER_NOT_INDICATED`."

        Design: Corner/validations/warm_transfer_on_a_non_emergency_call_is_not_indicated
        """
        world.bootstrap(
            clock="2026-08-03T14:30:00Z",
            nurse_keys=("nurse_a",),
            protocol={"base_severity": 62},
        )
        call, _, _ = world.dispositioned_call(
            "ED_NOW", "nurse_a", red_flag_count=1, reason_text="chest discomfort"
        )
        assert world.call(call["id"])["requires_warm_transfer"] is False

        response = world.api.create_warm_transfer(
            call["id"],
            f.warm_transfer_payload(
                psap_center_code="PSAP-SFO-01",
                location_address_line="12 Mission Street",
                location_lat=37.7749,
                location_lng=-122.4194,
            ),
            world.nurse_headers("nurse_a"),
        )

        validate_error(response, ApiErrorId.ERR_WARM_TRANSFER_NOT_INDICATED, 409)
        _, meta = validate_paginated(
            world.api.list_call_warm_transfers(call["id"], world.admin, None)
        )
        assert meta["total_count"] == 0
        assert world.call(call["id"])["status"] == "DISPOSITIONED"

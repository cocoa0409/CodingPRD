"""Deposit workflow gates, reservation, retry — PRD §3.3."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    CompartmentStatus,
    CompartmentEventType,
    CorrectionOrigin,
    FeeWaiverReason,
    MAX_RETRY,
    ParcelStatus,
    PICKUP_CODE_LENGTH,
    advance_clock,
    assert_compartment,
    assert_parcel,
    begin_deposit,
    confirm_deposit,
    create_courier,
    create_machine,
    create_parcel_payload,
    deposit_parcel,
    get_compartment,
    get_machine,
    get_parcel,
    make_courier_headers,
    offline_machine,
    setup_basic_scenario,
    setup_deposited_parcel,
    setup_machine_with_compartments,
    unique_tracking_no,
    validate_error,
    validate_success,
)


class TestDepositGates:
    """PRD §3.3: 'Several gates fire in priority order before the parcel
    is even created.'"""

    def test_deposit_blocked_when_machine_offline(self, api):
        """PRD §3.3: 'The target machine must not be in degraded mode
        (ERR_MACHINE_OFFLINE_DEGRADED).'

        Claim: POST /parcels at a machine in degraded_mode=true returns
        ERR_MACHINE_OFFLINE_DEGRADED with HTTP 409.
        """
        machine, _, courier = setup_basic_scenario()
        offline_machine(machine["id"])
        resp = api.create_parcel(
            create_parcel_payload(locker_machine_id=machine["id"]),
            make_courier_headers(courier["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MACHINE_OFFLINE_DEGRADED.value)

    def test_deposit_no_fitting_compartment_returns_no_compartment_fits(
        self, api,
    ):
        """PRD §3.3: 'The machine must offer at least one compartment
        whose size is at least the requested required_size, otherwise the
        request is rejected with ERR_NO_COMPARTMENT_FITS.'

        Claim: a machine with only SMALL compartments rejects a LARGE
        deposit with ERR_NO_COMPARTMENT_FITS.
        """
        machine, _, courier = setup_basic_scenario(sizes=["SMALL"])
        resp = api.create_parcel(
            create_parcel_payload(
                locker_machine_id=machine["id"], required_size="LARGE",
            ),
            make_courier_headers(courier["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NO_COMPARTMENT_FITS.value)


class TestDepositReservation:
    """PRD §3.3: 'The selected compartment transitions from AVAILABLE to
    RESERVED and its current_parcel_id is set to the new parcel's id.'"""

    def test_begin_deposit_reserves_compartment(self, api):
        """PRD §3.3: 'The selected compartment transitions from AVAILABLE
        to RESERVED and its current_parcel_id is set to the new parcel's
        id.'

        Claim: after POST /parcels, the chosen compartment is RESERVED
        and its current_parcel_id equals the new parcel's id.
        """
        machine, _, courier = setup_basic_scenario(sizes=["MEDIUM"])
        parcel = begin_deposit(machine["id"], courier)
        comp = get_compartment(machine["id"], parcel["compartment_id"])
        assert comp["status"] == CompartmentStatus.RESERVED.value
        assert comp["current_parcel_id"] == parcel["id"]

    def test_new_parcel_starts_in_draft(self, api):
        """PRD §3.3: 'A new Parcel record is created with status = DRAFT,
        compartment_id set, failed_open_attempts = 0, correction_origin =
        NONE, replaces_parcel_id = null, fee_waived = false,
        fee_waiver_reason = NONE.'

        Claim: a freshly created parcel carries those exact initial
        values.
        """
        machine, _, courier = setup_basic_scenario()
        parcel = begin_deposit(machine["id"], courier)
        assert parcel["status"] == ParcelStatus.DRAFT.value
        assert parcel["compartment_id"] is not None
        assert parcel["failed_open_attempts"] == 0
        assert parcel["correction_origin"] == CorrectionOrigin.NONE.value
        assert parcel.get("replaces_parcel_id") in (None, "")
        assert parcel["fee_waived"] is False
        assert parcel["fee_waiver_reason"] == FeeWaiverReason.NONE.value


class TestConfirmDeposit:
    """PRD §3.3: 'Confirming advances the parcel from DRAFT to DEPOSITED,
    advances the compartment from RESERVED to OCCUPIED, generates a
    six-digit numeric pickup_code, sets deposited_at to the current
    server time …'"""

    def test_confirm_deposit_advances_states_and_generates_code(self, api):
        """PRD §3.3: 'Confirming advances the parcel from DRAFT to
        DEPOSITED, advances the compartment from RESERVED to OCCUPIED,
        generates a six-digit numeric pickup_code, sets deposited_at to
        the current server time.'

        Claim: after confirm-deposit, parcel.status=DEPOSITED,
        compartment.status=OCCUPIED, pickup_code is six numeric digits,
        and deposited_at is set.
        """
        machine, _, courier = setup_basic_scenario()
        parcel = begin_deposit(machine["id"], courier)
        confirmed = confirm_deposit(parcel["id"], courier)
        assert confirmed["status"] == ParcelStatus.DEPOSITED.value
        assert confirmed.get("pickup_code") is not None
        assert len(str(confirmed["pickup_code"])) == PICKUP_CODE_LENGTH, (
            "PRD §3.3: 'six-digit numeric pickup_code'"
        )
        assert str(confirmed["pickup_code"]).isdigit(), (
            "PRD §3.3: 'six-digit numeric pickup_code'"
        )
        assert confirmed.get("deposited_at") is not None
        comp = get_compartment(machine["id"], confirmed["compartment_id"])
        assert comp["status"] == CompartmentStatus.OCCUPIED.value


class TestRetryAndCancel:
    """PRD §3.3: 'When failed_open_attempts reaches the cap of three
    (MAX_RETRY = 3), any further confirm-deposit attempt is rejected with
    ERR_RETRY_EXHAUSTED; the courier must instead cancel the deposit.'"""

    def test_confirm_after_max_retry_returns_retry_exhausted(self, api):
        """PRD §3.3: 'When failed_open_attempts reaches the cap of three
        (MAX_RETRY = 3), any further confirm-deposit attempt is rejected
        with ERR_RETRY_EXHAUSTED.'

        Claim: after retry-open is invoked MAX_RETRY times, confirm-deposit
        returns ERR_RETRY_EXHAUSTED.
        """
        machine, _, courier = setup_basic_scenario()
        parcel = begin_deposit(machine["id"], courier)
        headers = make_courier_headers(courier["id"])
        for _ in range(MAX_RETRY):
            api.retry_open(parcel["id"], headers)
        resp = api.confirm_deposit(parcel["id"], headers)
        validate_error(resp, ApiErrorId.ERR_RETRY_EXHAUSTED.value)

    def test_cancel_deposit_releases_compartment(self, api):
        """PRD §3.3: 'Cancelling after retry exhaustion releases the
        compartment back to AVAILABLE (with current_parcel_id cleared),
        appends a CompartmentEvent with event_type = DEPOSIT_OPEN_FAILED,
        and frees the courier to begin a successor deposit whose
        correction_origin is RETRY_REASSIGN.'

        Claim: after cancel-deposit, the compartment returns to AVAILABLE
        with current_parcel_id cleared.
        """
        machine, _, courier = setup_basic_scenario()
        parcel = begin_deposit(machine["id"], courier)
        headers = make_courier_headers(courier["id"])
        for _ in range(MAX_RETRY):
            api.retry_open(parcel["id"], headers)
        resp = api.cancel_deposit(parcel["id"], headers)
        validate_success(resp)
        comp = get_compartment(machine["id"], parcel["compartment_id"])
        assert comp["status"] == CompartmentStatus.AVAILABLE.value
        assert comp.get("current_parcel_id") in (None, "")


class TestDuplicateTrackingNo:
    """PRD §3.3: 'The tracking_no is unique among parcels whose status is
    not WRONG_DEPOSIT_VOID — a duplicate live tracking_no is treated as
    an idempotency violation under ERR_DUPLICATE_PAYMENT_EVENT.'"""

    def test_duplicate_tracking_no_rejected(self, api):
        """PRD §3.3: 'a duplicate live tracking_no is treated as an
        idempotency violation under ERR_DUPLICATE_PAYMENT_EVENT.'

        Claim: a second POST /parcels with a tracking_no already in use
        on a non-WRONG_DEPOSIT_VOID parcel returns ERR_DUPLICATE_PAYMENT_EVENT.
        """
        machine, _, courier = setup_basic_scenario(
            sizes=["MEDIUM", "MEDIUM"],
        )
        tno = unique_tracking_no()
        first = api.create_parcel(
            create_parcel_payload(
                locker_machine_id=machine["id"], tracking_no=tno,
            ),
            make_courier_headers(courier["id"]),
        )
        validate_success(first, expected_status=201)
        resp = api.create_parcel(
            create_parcel_payload(
                locker_machine_id=machine["id"], tracking_no=tno,
            ),
            make_courier_headers(courier["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PAYMENT_EVENT.value)

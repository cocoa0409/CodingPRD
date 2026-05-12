"""Long-stay sweep, recall, return, dispose — PRD §3.7."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    CompartmentStatus,
    DISPOSE_THRESHOLD_HOURS,
    LONG_STAY_THRESHOLD_HOURS,
    ParcelStatus,
    RECALL_WINDOW_HOURS,
    advance_clock,
    advance_hours,
    create_courier,
    deposit_parcel,
    dispose_parcel_payload,
    get_compartment,
    get_parcel,
    make_courier_headers,
    run_sweep,
    setup_basic_scenario,
    setup_deposited_parcel,
    setup_dispose_eligible_parcel,
    setup_long_stay_parcel,
    validate_error,
    validate_success,
)


class TestLongStaySweep:
    """PRD §3.7: 'For each such parcel, the sweep checks whether the
    elapsed time since deposited_at is at least the long-stay threshold
    (LONG_STAY_THRESHOLD_HOURS of 168 hours); equality at the threshold
    triggers the transition.'"""

    def test_below_threshold_remains_deposited(self, api):
        """PRD §3.7: '… equality at the threshold triggers the transition.'

        Boundary claim: at elapsed_hours = LONG_STAY_THRESHOLD_HOURS - 1
        (167h), the sweep does NOT transition the parcel.
        """
        machine, _, _, parcel = setup_deposited_parcel()
        advance_hours(LONG_STAY_THRESHOLD_HOURS - 1)
        run_sweep()
        again = get_parcel(parcel["id"])
        assert again["status"] == ParcelStatus.DEPOSITED.value, (
            "below threshold; sweep must not advance status"
        )

    def test_at_threshold_advances_to_long_stay(self, api):
        """PRD §3.7: '… equality at the threshold triggers the transition.
        When the threshold is met, the parcel advances from DEPOSITED to
        LONG_STAY.'

        Claim: at elapsed_hours == LONG_STAY_THRESHOLD_HOURS the sweep
        transitions the parcel to LONG_STAY.
        """
        machine, _, _, parcel = setup_deposited_parcel()
        advance_hours(LONG_STAY_THRESHOLD_HOURS)
        run_sweep()
        again = get_parcel(parcel["id"])
        assert again["status"] == ParcelStatus.LONG_STAY.value, (
            f"PRD §3.7: at 168h, expected LONG_STAY; got {again['status']}"
        )

    def test_clock_advance_does_not_auto_run_sweep(self, api):
        """PRD §3.7: 'The _sweep/run capability does not auto-fire on a
        clock advance; the operator must trigger it explicitly.'

        Claim: advancing the clock past the threshold without invoking
        /_sweep/run leaves the parcel in DEPOSITED.
        """
        machine, _, _, parcel = setup_deposited_parcel()
        advance_hours(LONG_STAY_THRESHOLD_HOURS + 5)
        again = get_parcel(parcel["id"])
        assert again["status"] == ParcelStatus.DEPOSITED.value, (
            "PRD §3.7: clock advance must NOT auto-fire the sweep"
        )


class TestRecall:
    """PRD §3.7: 'The original courier may recall the parcel within the
    recall window (RECALL_WINDOW_HOURS = 72) measured from the moment of
    transition into LONG_STAY. Recalling is restricted to the parcel's
    owning courier (ERR_NOT_COURIER_OWNER otherwise) and requires the
    parcel still in LONG_STAY.'"""

    def test_recall_by_owner_advances_to_recalled(self, api):
        """PRD §3.7: 'A successful recall advances the parcel to RECALLED,
        releases the compartment to AVAILABLE.'

        Claim: a recall by the owning courier within the window advances
        status to RECALLED and releases the compartment to AVAILABLE.
        """
        machine, comp, courier, parcel = setup_long_stay_parcel()
        resp = api.recall_parcel(
            parcel["id"], make_courier_headers(courier["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == ParcelStatus.RECALLED.value
        # Compartment freed
        again_comp = get_compartment(machine["id"], parcel["compartment_id"])
        assert again_comp["status"] == CompartmentStatus.AVAILABLE.value

    def test_recall_by_non_owner_rejected(self, api):
        """PRD §3.7: 'Recalling is restricted to the parcel's owning
        courier (ERR_NOT_COURIER_OWNER otherwise).'

        Claim: another courier calling /recall returns
        ERR_NOT_COURIER_OWNER.
        """
        machine, _, _, parcel = setup_long_stay_parcel()
        intruder = create_courier()
        resp = api.recall_parcel(
            parcel["id"], make_courier_headers(intruder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_COURIER_OWNER.value)


class TestReturnToSender:
    """PRD §3.7: 'If the recall window has elapsed (the time since
    LONG_STAY entry is at least RECALL_WINDOW_HOURS), Operations may
    instead arrange a return to sender.'"""

    def test_return_after_recall_window_advances_to_returned(
        self, api, operations_admin_headers,
    ):
        """PRD §3.7: 'this advances the parcel to RETURNED, releases the
        compartment.'

        Claim: after RECALL_WINDOW_HOURS has elapsed since LONG_STAY
        entry, /return-to-sender advances status to RETURNED and frees
        the compartment.
        """
        machine, _, _, parcel = setup_long_stay_parcel()
        advance_hours(RECALL_WINDOW_HOURS)
        resp = api.return_to_sender(parcel["id"], operations_admin_headers)
        data = validate_success(resp)
        assert data["status"] == ParcelStatus.RETURNED.value
        comp = get_compartment(machine["id"], parcel["compartment_id"])
        assert comp["status"] == CompartmentStatus.AVAILABLE.value


class TestDispose:
    """PRD §3.7: 'After a longer threshold of 336 hours
    (DISPOSE_THRESHOLD_HOURS) measured from the LONG_STAY entry,
    Operations may also record an on-site disposal.'"""

    def test_dispose_after_threshold_advances_to_disposed(
        self, api, operations_admin_headers,
    ):
        """PRD §3.7: 'which moves the parcel to DISPOSED, releases the
        compartment, and appends an AuditLog row whose payload records
        the supplied reason.'

        Claim: at elapsed >= DISPOSE_THRESHOLD_HOURS since LONG_STAY,
        /dispose advances to DISPOSED and frees the compartment.
        """
        machine, _, _, parcel = setup_dispose_eligible_parcel()
        resp = api.dispose_parcel(
            parcel["id"], dispose_parcel_payload(reason="abandoned"),
            operations_admin_headers,
        )
        data = validate_success(resp)
        assert data["status"] == ParcelStatus.DISPOSED.value
        comp = get_compartment(machine["id"], parcel["compartment_id"])
        assert comp["status"] == CompartmentStatus.AVAILABLE.value

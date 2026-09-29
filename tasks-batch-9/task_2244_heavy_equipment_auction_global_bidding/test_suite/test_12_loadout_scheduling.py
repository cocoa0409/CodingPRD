"""Booking the crane: the overlapping-tonnage aggregate, rebooking and the booking guards."""
from test_helpers import (
    ApiErrorId,
    api_client,
    booked_loadout_slot,
    cancel_loadout_slot_payload,
    check_in_loadout_slot_payload,
    create_loadout_slot_payload,
    multi_lot_release_authorized,
    new_loadout_bay,
    new_yard,
    release_authorized_invoice,
    update_loadout_bay_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, OPERATOR, SETTLEMENT

HEAVY_LOT = {
    "serial_number": "CAT-D8T-0001",
    "weight_kg": 36_000,
    "reserve_price_cents": 1_000_000,
}
LIGHT_LOT = {
    "make": "Bobcat",
    "model": "S76",
    "model_year": 2021,
    "serial_number": "BOB-S76-0002",
    "hour_meter_reading": 900,
    "weight_kg": 6_000,
    "reserve_price_cents": 1_000_000,
}


def _two_released_machines():
    """One 36,000 kg machine and one 6,000 kg machine, both paid and cleared for release."""
    return multi_lot_release_authorized(
        [HEAVY_LOT, LIGHT_LOT],
        [12_000_000, 2_000_000],
        ["2026-08-10T16:00:00Z", "2026-08-10T16:05:00Z"],
    )


def _book(stage, invoice, bay, start, end, tonnage, version=None, **overrides):
    """Book or rebook a window for one invoice, reading the invoice version when not given."""
    if version is None:
        version = validate_success(api_client.get_invoice(invoice["id"], SETTLEMENT))["version"]
    return api_client.create_loadout_slot(
        create_loadout_slot_payload(
            invoice["id"], bay["id"], version, start, end, tonnage, **overrides
        ),
        stage["bidder_headers"],
    )


def _reserved(bay):
    return validate_success(api_client.get_loadout_bay(bay["id"], ADMIN))[
        "reserved_tonnage_kg"
    ]


class TestCraneAggregate:
    def test_two_machines_that_fit_singly_are_refused_when_their_windows_overlap(self):
        """36,000 kg and 6,000 kg each sit under the 40,000 kg rating, and the small machine is
        refused only for the hours it shares with the big one.

        PRD 3.9: "Finally the bay's crane rating must hold: sum `tonnage_kg` across the bay's
        `BOOKED` and `CHECKED_IN` slots that overlap the requested interval in time, add this
        slot's own tonnage, and the total must not exceed the bay's `crane_capacity_kg`,
        otherwise `ERR_BAY_CAPACITY_EXCEEDED`. Each individual booking may fit comfortably while
        the overlapping set does not — that is the point of the aggregate check."
        PRD 2.9: "On a load-out bay, `reserved_tonnage_kg` sums `tonnage_kg` across that bay's
        slots whose `status` is `BOOKED` or `CHECKED_IN`."

        Design: Difficulty/resource_temporal_overlap/bay_crane_capacity_aggregates_overlapping_slots_excluding_superseded
        """
        stage = _two_released_machines()
        heavy_invoice, light_invoice = stage["invoices"]
        bay = new_loadout_bay(stage["yard"]["id"], crane_capacity_kg=40_000)

        heavy_slot = validate_success(
            _book(
                stage,
                heavy_invoice,
                bay,
                "2026-08-18T08:00:00Z",
                "2026-08-18T10:00:00Z",
                36_000,
                transport_mode="BUYER_ARRANGED",
            ),
            expected_status=201,
        )
        assert heavy_slot["status"] == "BOOKED"
        assert heavy_slot["supersedes_slot_id"] is None
        assert _reserved(bay) == 36_000

        overlapping = _book(
            stage,
            light_invoice,
            bay,
            "2026-08-18T09:00:00Z",
            "2026-08-18T11:00:00Z",
            6_000,
            transport_mode="RAIL",
        )

        validate_error(
            overlapping, ApiErrorId.ERR_BAY_CAPACITY_EXCEEDED, expected_status=409
        )
        assert _reserved(bay) == 36_000
        assert (
            validate_success(api_client.get_invoice(light_invoice["id"], SETTLEMENT))[
                "release_status"
            ]
            == "RELEASE_AUTHORIZED"
        )

        afternoon = validate_success(
            _book(
                stage,
                light_invoice,
                bay,
                "2026-08-18T12:00:00Z",
                "2026-08-18T14:00:00Z",
                6_000,
                transport_mode="RAIL",
            ),
            expected_status=201,
        )

        assert afternoon["status"] == "BOOKED"
        assert afternoon["tonnage_kg"] == 6_000
        assert (
            validate_success(api_client.get_invoice(light_invoice["id"], SETTLEMENT))[
                "release_status"
            ]
            == "LOADOUT_BOOKED"
        )
        assert _reserved(bay) == 42_000

    def test_a_superseded_booking_stops_reserving_the_crane_it_used_to_hold(self):
        """Moving the big machine to another day leaves the bay reserving 36,000 kg rather than
        double-counting the booking it replaced.

        PRD 3.9: "**Rebooking** is the self-loop on the custody axis: a slot booking made while
        the invoice is already `LOADOUT_BOOKED` leaves the invoice in `LOADOUT_BOOKED` and
        supersedes the prior booking, provided the version guard passes and exactly one slot of
        that invoice is currently `BOOKED`. The prior slot becomes `CANCELLED` with its
        `cancel_reason` set to `SUPERSEDED`".
        PRD 3.9: "The new slot records the cancelled slot's identifier in `supersedes_slot_id`,
        `reserved_tonnage_kg` is recomputed for both bays involved when the move crosses bays,
        and the invoice's `version` increments by 1."

        Design: Difficulty/resource_temporal_overlap/bay_crane_capacity_aggregates_overlapping_slots_excluding_superseded
        """
        stage = _two_released_machines()
        heavy_invoice = stage["invoices"][0]
        bay = new_loadout_bay(stage["yard"]["id"], crane_capacity_kg=40_000)
        first = validate_success(
            _book(
                stage,
                heavy_invoice,
                bay,
                "2026-08-18T08:00:00Z",
                "2026-08-18T10:00:00Z",
                36_000,
            ),
            expected_status=201,
        )
        assert _reserved(bay) == 36_000
        booked_version = validate_success(
            api_client.get_invoice(heavy_invoice["id"], SETTLEMENT)
        )["version"]

        moved = validate_success(
            _book(
                stage,
                heavy_invoice,
                bay,
                "2026-08-19T08:00:00Z",
                "2026-08-19T10:00:00Z",
                36_000,
                version=booked_version,
            ),
            expected_status=201,
        )

        assert moved["status"] == "BOOKED"
        assert moved["supersedes_slot_id"] == first["id"]
        superseded = validate_success(api_client.get_loadout_slot(first["id"], SETTLEMENT))
        assert superseded["status"] == "CANCELLED"
        assert superseded["cancel_reason"] == "SUPERSEDED"
        assert _reserved(bay) == 36_000
        assert _reserved(bay) != 72_000

        refreshed = validate_success(api_client.get_invoice(heavy_invoice["id"], SETTLEMENT))
        assert refreshed["release_status"] == "LOADOUT_BOOKED"
        assert refreshed["version"] == booked_version + 1
        rows, meta = validate_paginated(
            api_client.list_loadout_slots(SETTLEMENT, params={"bay_id": bay["id"]})
        )
        assert meta["total_count"] == 2
        assert len([row for row in rows if row["status"] == "BOOKED"]) == 1


class TestCancellingGivesTheCraneBack:
    def test_cancelling_the_only_booking_returns_the_bay_to_its_pre_booking_tonnage(self):
        """The compensating move lands on zero — the bay's value before the booking — and the
        custody axis falls back one step while the machine and the money stay put.

        PRD 3.9: "Either outcome performs the compensating tonnage move — the bay's
        `reserved_tonnage_kg` returns to its pre-booking value — and moves the invoice
        `LOADOUT_BOOKED → RELEASE_AUTHORIZED` once no non-terminal slot of that invoice remains,
        so the buyer may book again."
        PRD 3.9: "A `CANCELLED` outcome is available from `BOOKED` or `CHECKED_IN`; the buyer may
        cancel its own `BOOKED` slot, while cancelling a slot already checked in is a
        `SettlementOfficer` action."

        Design: Difficulty/compensating_invariant/bay_reserved_tonnage_returns_to_zero_after_slot_cancel
        """
        stage = booked_loadout_slot(
            lot_overrides={"serial_number": "CAT-D8T-0001"}, settle_consignor=False
        )
        bay, slot, invoice = stage["bay"], stage["slot"], stage["invoice"]
        assert _reserved(bay) == 36_000
        assert invoice["release_status"] == "LOADOUT_BOOKED"
        assert invoice["total_due_cents"] == 12_498_438

        cancelled = validate_success(
            api_client.cancel_loadout_slot(
                slot["id"], cancel_loadout_slot_payload(), stage["bidder_headers"]
            )
        )

        assert cancelled["status"] == "CANCELLED"
        assert _reserved(bay) == 0
        after = validate_success(api_client.get_invoice(invoice["id"], SETTLEMENT))
        assert after["release_status"] == "RELEASE_AUTHORIZED"
        assert after["payment_status"] == "PAID"
        assert after["total_due_cents"] == 12_498_438
        assert (
            validate_success(api_client.get_lot(stage["lot"]["id"], OPERATOR))[
                "lifecycle_status"
            ]
            == "HAMMERED"
        )

    def test_the_freed_crane_can_be_booked_to_the_same_tonnage_again(self):
        """After the cancellation the identical 36,000 kg reservation is accepted in the same
        bay, leaving two slots of which exactly one is live.

        PRD 3.9: "The new slot is created in `BOOKED` with `gate_pass_ref`,
        `supersedes_slot_id` and `cancel_reason` all null, and it moves the invoice
        `RELEASE_AUTHORIZED → LOADOUT_BOOKED`."
        PRD 3.9: "`COMPLETED`, `CANCELLED` and `NO_SHOW` are all terminal for a slot."

        Design: Difficulty/compensating_invariant/bay_reserved_tonnage_returns_to_zero_after_slot_cancel
        """
        stage = booked_loadout_slot(
            lot_overrides={"serial_number": "CAT-D8T-0001"}, settle_consignor=False
        )
        bay, slot, invoice = stage["bay"], stage["slot"], stage["invoice"]
        validate_success(
            api_client.cancel_loadout_slot(
                slot["id"], cancel_loadout_slot_payload(), stage["bidder_headers"]
            )
        )
        assert _reserved(bay) == 0

        rebooked = validate_success(
            _book(
                stage,
                invoice,
                bay,
                "2026-08-19T08:00:00Z",
                "2026-08-19T10:00:00Z",
                36_000,
                transport_mode="HOUSE_BROKERED",
            ),
            expected_status=201,
        )

        assert rebooked["status"] == "BOOKED"
        assert rebooked["supersedes_slot_id"] is None
        assert rebooked["cancel_reason"] is None
        assert rebooked["gate_pass_ref"] is None
        assert _reserved(bay) == 36_000
        assert (
            validate_success(api_client.get_invoice(invoice["id"], SETTLEMENT))[
                "release_status"
            ]
            == "LOADOUT_BOOKED"
        )
        rows, meta = validate_paginated(
            api_client.list_loadout_slots(SETTLEMENT, params={"bay_id": bay["id"]})
        )
        assert meta["total_count"] == 2
        assert len([row for row in rows if row["status"] == "BOOKED"]) == 1


class TestEachBookingGuardHasItsOwnId:
    def test_the_wrong_yard_a_dead_bay_a_late_window_and_an_overlap_all_answer_differently(self):
        """Four refused bookings and one early arrival report five distinct identifiers, and the
        only accepted booking is the one inside every constraint.

        PRD 3.9: "The bay must belong to the same yard as the auction that sold the machine —
        equipment leaves only from the yard that held the event — otherwise
        `ERR_BAY_YARD_MISMATCH`. The bay's `is_active` must be true, otherwise
        `ERR_BAY_INACTIVE`; bays taken out of service keep their existing bookings but accept no
        new ones."
        PRD 3.9: "The requested interval must not overlap another `BOOKED` or `CHECKED_IN` slot
        of the **same invoice**, otherwise `ERR_SLOT_OVERLAP`; because the intervals are
        half-open, a slot starting at exactly another slot's `slot_end` is adjacent rather than
        overlapping and is accepted. The interval must sit inside the auction's load-out window:
        `slot_start` at or after the auction's `window_end`, and `slot_end` at or before the
        auction's `loadout_deadline_at`, otherwise `ERR_SLOT_OUTSIDE_DEADLINE`."
        PRD 3.9: "Check-in is only permitted when the logical clock is at or after `slot_start`
        and strictly before `slot_end`; arrival before the window opens or after it closes is
        refused with `ERR_SLOT_NOT_IN_WINDOW`."

        Design: Corner/errors/loadout_booking_guards_each_report_their_own_conflict_id
        """
        stage = release_authorized_invoice(
            lot_overrides={"serial_number": "CAT-D8T-0001"}, settle_consignor=False
        )
        invoice = stage["invoice"]
        assert stage["auction"]["loadout_deadline_at"].startswith("2026-08-20T22:00:00")
        good_bay = new_loadout_bay(stage["yard"]["id"], bay_number=1)
        dead_bay = new_loadout_bay(stage["yard"]["id"], bay_number=2)
        validate_success(
            api_client.update_loadout_bay(
                dead_bay["id"], update_loadout_bay_payload(is_active=False), ADMIN
            )
        )
        far_bay = new_loadout_bay(new_yard(code="YRD-HOU")["id"], bay_number=1)
        version = invoice["version"]

        validate_error(
            _book(
                stage,
                invoice,
                far_bay,
                "2026-08-12T08:00:00Z",
                "2026-08-12T12:00:00Z",
                36_000,
                version=version,
                transport_mode="BUYER_ARRANGED",
            ),
            ApiErrorId.ERR_BAY_YARD_MISMATCH,
            expected_status=409,
        )
        validate_error(
            _book(
                stage,
                invoice,
                dead_bay,
                "2026-08-12T08:00:00Z",
                "2026-08-12T12:00:00Z",
                36_000,
                version=version,
                transport_mode="BUYER_ARRANGED",
            ),
            ApiErrorId.ERR_BAY_INACTIVE,
            expected_status=409,
        )
        validate_error(
            _book(
                stage,
                invoice,
                good_bay,
                "2026-08-21T08:00:00Z",
                "2026-08-21T12:00:00Z",
                36_000,
                version=version,
                transport_mode="BUYER_ARRANGED",
            ),
            ApiErrorId.ERR_SLOT_OUTSIDE_DEADLINE,
            expected_status=422,
        )

        booked = validate_success(
            _book(
                stage,
                invoice,
                good_bay,
                "2026-08-12T08:00:00Z",
                "2026-08-12T12:00:00Z",
                36_000,
                version=version,
                transport_mode="BUYER_ARRANGED",
            ),
            expected_status=201,
        )
        assert booked["status"] == "BOOKED"
        assert booked["supersedes_slot_id"] is None
        assert (
            validate_success(api_client.get_invoice(invoice["id"], SETTLEMENT))[
                "release_status"
            ]
            == "LOADOUT_BOOKED"
        )

        validate_error(
            _book(
                stage,
                invoice,
                good_bay,
                "2026-08-12T11:00:00Z",
                "2026-08-12T15:00:00Z",
                36_000,
                transport_mode="BUYER_ARRANGED",
            ),
            ApiErrorId.ERR_SLOT_OVERLAP,
            expected_status=409,
        )
        assert (
            validate_success(api_client.get_loadout_slot(booked["id"], SETTLEMENT))["status"]
            == "BOOKED"
        )

        validate_error(
            api_client.check_in_loadout_slot(
                booked["id"], check_in_loadout_slot_payload(), stage["bidder_headers"]
            ),
            ApiErrorId.ERR_SLOT_NOT_IN_WINDOW,
            expected_status=409,
        )
        assert _reserved(good_bay) == 36_000
        assert _reserved(dead_bay) == 0


class TestRebookingVersionGuard:
    def test_the_stale_invoice_version_is_what_stops_an_otherwise_legal_rebooking(self):
        """The self-loop is a permitted transition, so only the consumed version refuses the
        second booking, and the refreshed one supersedes the original.

        PRD 2.8: "`expected_sale_version` or `expected_invoice_version` equals the parent's
        current `version` — otherwise `ERR_STALE_SALE_VERSION` or `ERR_STALE_INVOICE_VERSION`
        (412). Checked before any state precondition, so a stale version on a resource that is
        also in the wrong state still returns 412."
        PRD 3.9: "The prior slot becomes `CANCELLED` with its `cancel_reason` set to
        `SUPERSEDED`, and this happens **only after every validation has passed** — a rejected
        rebooking leaves the original booking intact."

        Design: Corner/cross-cutting complexity layers/stale_expected_invoice_version_on_a_slot_rebooking_returns_412
        """
        stage = booked_loadout_slot(
            lot_overrides={"serial_number": "CAT-D8T-0001"}, settle_consignor=False
        )
        bay, first_slot, invoice = stage["bay"], stage["slot"], stage["invoice"]
        consumed_version = invoice["version"] - 1

        stale = _book(
            stage,
            invoice,
            bay,
            "2026-08-13T08:00:00Z",
            "2026-08-13T12:00:00Z",
            36_000,
            version=consumed_version,
        )

        validate_error(stale, ApiErrorId.ERR_STALE_INVOICE_VERSION, expected_status=412)
        assert (
            validate_success(api_client.get_loadout_slot(first_slot["id"], SETTLEMENT))[
                "status"
            ]
            == "BOOKED"
        )
        held = validate_success(api_client.get_invoice(invoice["id"], SETTLEMENT))
        assert held["version"] == consumed_version + 1
        assert held["release_status"] == "LOADOUT_BOOKED"

        fresh = validate_success(
            _book(
                stage,
                invoice,
                bay,
                "2026-08-13T08:00:00Z",
                "2026-08-13T12:00:00Z",
                36_000,
                version=held["version"],
            ),
            expected_status=201,
        )

        assert fresh["status"] == "BOOKED"
        assert fresh["supersedes_slot_id"] == first_slot["id"]
        superseded = validate_success(
            api_client.get_loadout_slot(first_slot["id"], SETTLEMENT)
        )
        assert superseded["status"] == "CANCELLED"
        assert superseded["cancel_reason"] == "SUPERSEDED"
        assert _reserved(bay) == 36_000
        assert _reserved(bay) != 72_000
        final = validate_success(api_client.get_invoice(invoice["id"], SETTLEMENT))
        assert final["release_status"] == "LOADOUT_BOOKED"
        assert final["version"] == held["version"] + 1

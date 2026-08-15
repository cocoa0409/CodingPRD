"""Consignment agreements: window semantics, creation guards, terminate and
clock-sweep cascades."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_seller, create_bin, create_lot, create_active_listing,
    create_consignment_agreement, create_consignment_agreement_payload,
    set_clock,
    setup_listed_consignment_scenario,
    assert_instant_equals,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

BROKER = TEST_USERS["broker_ops_headers"]


def _consignment_lot(seller_name, bin_code, mpn="PIC16F877", quantity=5,
                     agreed=9000):
    seller = create_seller(name=seller_name)
    storage_bin = create_bin(capacity_units=20, bin_code=bin_code)
    lot, _ = create_lot(
        seller, storage_bin, mpn=mpn, quantity=quantity,
        ask_price_per_unit_cents=agreed, agreed_unit_price_cents=agreed,
        acquisition_mode="CONSIGNMENT",
    )
    return seller, storage_bin, lot


class TestWindowOverlapSemantics:
    def test_interior_overlap_rejected(self, api):
        """PRD section 3.4: "And the window must not overlap any other `ACTIVE`
        agreement on the same lot under half-open semantics — two windows that
        merely touch, one ending exactly when the other begins, do not overlap
        — otherwise `ERR_CONSIGNMENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/consignment_window_half_open_overlap_semantics
        """
        seller, _, lot = _consignment_lot("Oscar Overstock", "BIN-O1", quantity=8)
        create_consignment_agreement(
            seller, lot, broker_fee_bps=1200,
            effective_from="2026-08-01T00:00:00Z",
            effective_to="2026-09-01T00:00:00Z",
        )
        # [2026-08-15, 2026-10-01) overlaps the ACTIVE window's interior.
        res = api.create_consignment_agreement(
            create_consignment_agreement_payload(
                seller["id"], lot["id"], broker_fee_bps=1200,
                effective_from="2026-08-15T00:00:00Z",
                effective_to="2026-10-01T00:00:00Z",
            ),
            BROKER,
        )
        validate_error(
            res, ApiErrorId.ERR_CONSIGNMENT_WINDOW_OVERLAP, expected_status=409
        )

    def test_adjacent_window_touching_boundary_admitted(self, api):
        """PRD section 3.4: "And the window must not overlap any other `ACTIVE`
        agreement on the same lot under half-open semantics — two windows that
        merely touch, one ending exactly when the other begins, do not overlap
        — otherwise `ERR_CONSIGNMENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/consignment_window_half_open_overlap_semantics
        """
        seller, _, lot = _consignment_lot("Oscar Overstock", "BIN-O1", quantity=8)
        create_consignment_agreement(
            seller, lot, broker_fee_bps=1200,
            effective_from="2026-08-01T00:00:00Z",
            effective_to="2026-09-01T00:00:00Z",
        )
        # [2026-09-01, 2026-10-01) starts exactly when the first window ends:
        # adjacency is not overlap under half-open [from, to) semantics.
        res = api.create_consignment_agreement(
            create_consignment_agreement_payload(
                seller["id"], lot["id"], broker_fee_bps=1200,
                effective_from="2026-09-01T00:00:00Z",
                effective_to="2026-10-01T00:00:00Z",
            ),
            BROKER,
        )
        created = validate_success(res, 201)
        assert created["status"] == "ACTIVE"
        # PRD pins the window's instant, not the echo's string representation.
        assert_instant_equals(created["effective_from"], "2026-09-01T00:00:00Z")


class TestWindowCreationGuards:
    def test_empty_window_rejected(self, api):
        """PRD section 3.4: "The window must open before it closes —
        `effective_from` strictly earlier than `effective_to` — otherwise
        `ERR_CONSIGNMENT_WINDOW_INVALID`."

        Design: Corner/validations/consignment_window_from_after_to_rejected
        """
        seller, _, lot = _consignment_lot("Wi Wanda", "BIN-WI1")
        res = api.create_consignment_agreement(
            create_consignment_agreement_payload(
                seller["id"], lot["id"], broker_fee_bps=1000,
                effective_from="2026-09-01T00:00:00Z",
                effective_to="2026-09-01T00:00:00Z",
            ),
            BROKER,
        )
        validate_error(
            res, ApiErrorId.ERR_CONSIGNMENT_WINDOW_INVALID, expected_status=422
        )

    def test_zero_fee_bps_rejected(self, api):
        """PRD section 3.4: "The fee itself must sit between 1 and 5000 basis
        points inclusive, otherwise `ERR_INVALID_FEE_BPS`."

        Design: Corner/validations/invalid_fee_bps_rejected
        """
        seller, _, lot = _consignment_lot("Fb Finn", "BIN-FB1")
        res = api.create_consignment_agreement(
            create_consignment_agreement_payload(
                seller["id"], lot["id"], broker_fee_bps=0,
                effective_from="2026-08-01T00:00:00Z",
                effective_to="2027-08-01T00:00:00Z",
            ),
            BROKER,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_FEE_BPS, expected_status=422)

    def test_seller_mismatch_rejected(self, api):
        """PRD section 3.4: "The named seller must be the seller of the lot's
        originating buy offer, otherwise `ERR_CONSIGNMENT_SELLER_MISMATCH`."

        Design: Corner/validations/consignment_seller_mismatch_rejected
        """
        seller_a, _, lot = _consignment_lot("Sm Amy", "BIN-SM1")
        seller_b = create_seller(name="Sm Bob")
        res = api.create_consignment_agreement(
            create_consignment_agreement_payload(
                seller_b["id"], lot["id"], broker_fee_bps=1000,
                effective_from="2026-08-01T00:00:00Z",
                effective_to="2027-08-01T00:00:00Z",
            ),
            BROKER,
        )
        validate_error(
            res, ApiErrorId.ERR_CONSIGNMENT_SELLER_MISMATCH, expected_status=422
        )

    def test_agreement_on_broker_owned_lot_rejected(self, api):
        """PRD section 3.4: "The lot's `storage_mode` must be `CONSIGNMENT`,
        otherwise the creation fails with `ERR_LOT_NOT_CONSIGNMENT`."

        Design: Corner/validations/agreement_on_broker_owned_lot_rejected
        """
        seller = create_seller(name="Bo Betty")
        storage_bin = create_bin(capacity_units=20, bin_code="BIN-BO1")
        lot, _ = create_lot(
            seller, storage_bin, mpn="2N2222", quantity=5,
            ask_price_per_unit_cents=4000, agreed_unit_price_cents=4000,
            acquisition_mode="BROKER_OWNED",
        )
        res = api.create_consignment_agreement(
            create_consignment_agreement_payload(
                seller["id"], lot["id"], broker_fee_bps=1000,
                effective_from="2026-08-01T00:00:00Z",
                effective_to="2027-08-01T00:00:00Z",
            ),
            BROKER,
        )
        validate_error(res, ApiErrorId.ERR_LOT_NOT_CONSIGNMENT, expected_status=409)


class TestTerminateCascade:
    def test_terminate_pauses_active_listing_and_recomputes_posture(self, api):
        """PRD section 3.4: "`BrokerOps` may terminate an agreement, which
        requires it to be `ACTIVE` — termination in any other state is rejected
        with `ERR_AGREEMENT_NOT_ACTIVE` — and moves it to `TERMINATED`.
        Alternatively the clock sweep of §2.4 expires an agreement whose window
        has closed, moving it from `ACTIVE` to `EXPIRED`. Either way, every
        `ACTIVE` listing on the agreement's lot is paused to `PAUSED` and the
        lot's posture is recomputed, so a consignment lot whose coverage lapses
        silently falls off the market until a fresh window is in place."

        Design: Corner/state_machines/consignment_terminate_pauses_active_listing
        """
        sc = setup_listed_consignment_scenario(
            mpn="PIC16F877", quantity=5, agreed_unit_price_cents=9000,
            asking_price_per_unit_cents=12000, broker_fee_bps=1000,
            bin_capacity=20,
        )
        terminated = validate_success(
            api.terminate_consignment_agreement(sc["agreement"]["id"], BROKER), 200
        )
        assert terminated["status"] == "TERMINATED"

        listing = validate_success(api.get_listing(sc["listing"]["id"], BROKER), 200)
        assert listing["status"] == "PAUSED"

        lot = validate_success(api.get_lot(sc["lot"]["id"], BROKER), 200)
        assert lot["status"] == "IN_STOCK"

    def test_double_terminate_rejected(self, api):
        """PRD section 3.4: "`BrokerOps` may terminate an agreement, which
        requires it to be `ACTIVE` — termination in any other state is rejected
        with `ERR_AGREEMENT_NOT_ACTIVE` — and moves it to `TERMINATED`."

        Design: Corner/errors/error_agreement_not_active_on_double_terminate
        """
        seller, _, lot = _consignment_lot("Dt Dave", "BIN-DT1")
        agreement = create_consignment_agreement(
            seller, lot, broker_fee_bps=1000,
            effective_from="2026-08-01T00:00:00Z",
            effective_to="2027-08-01T00:00:00Z",
        )
        validate_success(
            api.terminate_consignment_agreement(agreement["id"], BROKER), 200
        )
        res = api.terminate_consignment_agreement(agreement["id"], BROKER)
        validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, expected_status=409)


class TestClockSweep:
    def test_clock_at_effective_to_expires_agreement_and_pauses_listing(self, api):
        """PRD section 2.4: "The call sweeps the consignment book: every
        agreement still `ACTIVE` whose `effective_to` falls at or before the
        new current time transitions to `EXPIRED`, every `ACTIVE` listing on
        each expired agreement's lot cascades to `PAUSED`, and each affected
        lot's posture is recomputed."

        Design: Corner/state_machines/clock_sweep_expires_agreement_and_pauses_listing
        """
        seller, _, lot = _consignment_lot("Swp Sam", "BIN-S1")
        agreement = create_consignment_agreement(
            seller, lot, broker_fee_bps=1000,
            effective_from="2026-08-01T00:00:00Z",
            effective_to="2026-09-01T00:00:00Z",
        )
        listing, active = create_active_listing(
            lot, asking_price_per_unit_cents=12000
        )
        assert active["status"] == "ACTIVE"

        # effective_to is exclusive: at exactly 2026-09-01 the window has closed.
        set_clock("2026-09-01T00:00:00Z")

        agreement_after = validate_success(
            api.get_consignment_agreement(agreement["id"], BROKER), 200
        )
        assert agreement_after["status"] == "EXPIRED"

        listing_after = validate_success(api.get_listing(listing["id"], BROKER), 200)
        assert listing_after["status"] == "PAUSED"

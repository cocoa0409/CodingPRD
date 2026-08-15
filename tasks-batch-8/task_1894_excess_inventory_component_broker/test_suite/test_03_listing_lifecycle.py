"""Listing lifecycle: activation gating, pause cycles, withdrawal, OCC repricing."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_seller, create_customer, create_bin, create_lot, create_active_listing,
    create_listing_payload, patch_listing_payload,
    setup_listed_broker_owned_scenario, setup_listed_consignment_scenario,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

BROKER = TEST_USERS["broker_ops_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


class TestPauseCycle:
    def test_listing_pause_reactivate_cycle_twice(self, api):
        """PRD section 3.5: "Activation moves a listing from `DRAFT` to
        `ACTIVE`, or from `PAUSED` back to `ACTIVE`, under a battery of
        preconditions evaluated in the precedence order of §2.10."
        PRD section 3.5: "Pausing moves an `ACTIVE` listing to `PAUSED` and
        recomputes the lot's posture, which falls back to `IN_STOCK` when no
        other `ACTIVE` listing remains on the lot."

        Design: Difficulty/non_linear_state_machine/listing_active_pause_cycle
        """
        seller = create_seller(name="Echo Electronics")
        storage_bin = create_bin(capacity_units=50, bin_code="BIN-E1")
        lot, _ = create_lot(
            seller, storage_bin, mpn="NE555", quantity=20,
            ask_price_per_unit_cents=5000, agreed_unit_price_cents=5000,
        )
        listing = validate_success(
            api.create_listing(
                create_listing_payload(lot["id"], asking_price_per_unit_cents=8000),
                BROKER,
            ),
            201,
        )

        for cycle in range(2):
            active = validate_success(api.activate_listing(listing["id"], BROKER), 200)
            assert active["status"] == "ACTIVE", f"activate failed on cycle {cycle}"
            lot_now = validate_success(api.get_lot(lot["id"], BROKER), 200)
            assert lot_now["status"] == "LISTED"

            paused = validate_success(api.pause_listing(listing["id"], BROKER), 200)
            assert paused["status"] == "PAUSED", f"pause failed on cycle {cycle}"
            lot_now = validate_success(api.get_lot(lot["id"], BROKER), 200)
            assert lot_now["status"] == "IN_STOCK", (
                "lot posture must fall back to IN_STOCK when the last ACTIVE "
                "listing pauses"
            )

        final = validate_success(api.activate_listing(listing["id"], BROKER), 200)
        assert final["status"] == "ACTIVE"
        lot_final = validate_success(api.get_lot(lot["id"], BROKER), 200)
        assert lot_final["status"] == "LISTED"

    def test_paused_listing_reactivates_and_lot_follows(self, api):
        """PRD section 3.5: "Activation moves a listing from `DRAFT` to
        `ACTIVE`, or from `PAUSED` back to `ACTIVE`, under a battery of
        preconditions evaluated in the precedence order of §2.10."
        PRD section 3.5: "A successful activation recomputes the lot's posture
        from `IN_STOCK` to `LISTED`."

        Design: Difficulty/non_linear_state_machine/listing_active_pause_cycle
        """
        seller = create_seller(name="Echo Electronics")
        storage_bin = create_bin(capacity_units=50, bin_code="BIN-E1")
        lot, _ = create_lot(
            seller, storage_bin, mpn="NE555", quantity=20,
            ask_price_per_unit_cents=5000, agreed_unit_price_cents=5000,
        )
        listing, _ = create_active_listing(lot, asking_price_per_unit_cents=8000)

        paused = validate_success(api.pause_listing(listing["id"], BROKER), 200)
        assert paused["status"] == "PAUSED"
        lot_mid = validate_success(api.get_lot(lot["id"], BROKER), 200)
        assert lot_mid["status"] == "IN_STOCK"

        reactivated = validate_success(api.activate_listing(listing["id"], BROKER), 200)
        assert reactivated["status"] == "ACTIVE"
        lot_end = validate_success(api.get_lot(lot["id"], BROKER), 200)
        assert lot_end["status"] == "LISTED"

    def test_second_listing_activation_blocked_while_first_active(self, api):
        """PRD section 3.5: "The lot's posture must be `IN_STOCK`, failing with
        `ERR_LOT_NOT_IN_STOCK` — and because any other `ACTIVE` listing on the
        lot would already have made the posture `LISTED`, this one check also
        enforces the platform's rule of at most one `ACTIVE` listing per lot."

        Design: Difficulty/cross_entity_state_dependency/listing_activation_requires_lot_in_stock
        """
        seller = create_seller(name="Mike Micros")
        storage_bin = create_bin(capacity_units=50, bin_code="BIN-M1")
        lot, _ = create_lot(
            seller, storage_bin, mpn="2N2222", quantity=10,
            ask_price_per_unit_cents=4000, agreed_unit_price_cents=4000,
        )
        listing_a = validate_success(
            api.create_listing(
                create_listing_payload(lot["id"], asking_price_per_unit_cents=7000),
                BROKER,
            ),
            201,
        )
        validate_success(api.activate_listing(listing_a["id"], BROKER), 200)

        listing_b = validate_success(
            api.create_listing(
                create_listing_payload(lot["id"], asking_price_per_unit_cents=8000),
                BROKER,
            ),
            201,
        )
        res = api.activate_listing(listing_b["id"], BROKER)
        validate_error(res, ApiErrorId.ERR_LOT_NOT_IN_STOCK, expected_status=409)

        lot_now = validate_success(api.get_lot(lot["id"], BROKER), 200)
        assert lot_now["status"] == "LISTED"

    def test_second_listing_stays_draft_after_rejected_activation(self, api):
        """PRD section 3.5: "The lot's posture must be `IN_STOCK`, failing with
        `ERR_LOT_NOT_IN_STOCK` — and because any other `ACTIVE` listing on the
        lot would already have made the posture `LISTED`, this one check also
        enforces the platform's rule of at most one `ACTIVE` listing per lot."

        Design: Difficulty/cross_entity_state_dependency/listing_activation_requires_lot_in_stock
        """
        seller = create_seller(name="Mike Micros")
        storage_bin = create_bin(capacity_units=50, bin_code="BIN-M1")
        lot, _ = create_lot(
            seller, storage_bin, mpn="2N2222", quantity=10,
            ask_price_per_unit_cents=4000, agreed_unit_price_cents=4000,
        )
        listing_a, _ = create_active_listing(lot, asking_price_per_unit_cents=7000)
        listing_b = validate_success(
            api.create_listing(
                create_listing_payload(lot["id"], asking_price_per_unit_cents=8000),
                BROKER,
            ),
            201,
        )
        validate_error(
            api.activate_listing(listing_b["id"], BROKER),
            ApiErrorId.ERR_LOT_NOT_IN_STOCK,
        )
        reread = validate_success(api.get_listing(listing_b["id"], BROKER), 200)
        assert reread["status"] == "DRAFT", (
            "a rejected activation must leave the listing in DRAFT"
        )


class TestWithdraw:
    def test_activate_on_withdrawn_listing_returns_invalid_state(self, api):
        """PRD section 3.5: "Withdrawing is permanent: a listing in `DRAFT`,
        `ACTIVE`, or `PAUSED` may move to `WITHDRAWN`, whether through an
        explicit `BrokerOps` withdrawal or automatically when its lot is
        quarantined."
        PRD section 3.5: "Invoking any of these listing actions from an
        incompatible state — pausing a draft, withdrawing a sold-out listing,
        and so on — is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/withdraw_is_terminal_for_listing
        """
        seller = create_seller(name="Wd Wanda")
        storage_bin = create_bin(capacity_units=20, bin_code="BIN-W1")
        lot, _ = create_lot(
            seller, storage_bin, mpn="NE555", quantity=5,
            ask_price_per_unit_cents=4000, agreed_unit_price_cents=4000,
        )
        listing = validate_success(
            api.create_listing(
                create_listing_payload(lot["id"], asking_price_per_unit_cents=5000),
                BROKER,
            ),
            201,
        )
        withdrawn = validate_success(api.withdraw_listing(listing["id"], BROKER), 200)
        assert withdrawn["status"] == "WITHDRAWN"

        res = api.activate_listing(listing["id"], BROKER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestConsignmentActivationGate:
    def test_activate_on_consignment_lot_without_agreement_rejected(self, api):
        """PRD section 3.5: "When the lot is consigned, an `ACTIVE` consignment
        agreement whose window contains the current clock time must exist —
        the current instant must be at or after `effective_from` and strictly
        before `effective_to` — failing with
        `ERR_NO_CURRENT_CONSIGNMENT_AGREEMENT`."

        Design: Corner/validations/activate_consignment_listing_without_agreement_rejected
        """
        seller = create_seller(name="Na Nora")
        storage_bin = create_bin(capacity_units=20, bin_code="BIN-NA1")
        lot, _ = create_lot(
            seller, storage_bin, mpn="PIC16F877", quantity=5,
            ask_price_per_unit_cents=9000, agreed_unit_price_cents=9000,
            acquisition_mode="CONSIGNMENT",
        )
        listing = validate_success(
            api.create_listing(
                create_listing_payload(lot["id"], asking_price_per_unit_cents=12000),
                BROKER,
            ),
            201,
        )
        res = api.activate_listing(listing["id"], BROKER)
        validate_error(
            res, ApiErrorId.ERR_NO_CURRENT_CONSIGNMENT_AGREEMENT,
            expected_status=409,
        )


class TestCostFloor:
    def test_activate_at_exact_cost_floor_admitted(self, api):
        """PRD section 3.5: "The asking price itself is governed by a cost
        floor at every stage of life: it must never fall below eighty percent
        of the lot's `cost_basis_per_unit_cents`, rounded down to a whole cent."

        Design: Corner/validations/asking_below_cost_floor_rejected_on_activate
        """
        seller = create_seller(name="Fl Floyd")
        storage_bin = create_bin(capacity_units=20, bin_code="BIN-FL1")
        lot, _ = create_lot(
            seller, storage_bin, mpn="ATmega328P", quantity=5,
            ask_price_per_unit_cents=8000, agreed_unit_price_cents=8000,
        )
        # Create above the floor (floor is checked at creation per PRD 3.5),
        # then reprice down to exactly the floor.
        listing = validate_success(
            api.create_listing(
                create_listing_payload(lot["id"], asking_price_per_unit_cents=8000),
                BROKER,
            ),
            201,
        )
        # Reprice to exactly the floor (6400), then activation succeeds.
        patched = validate_success(
            api.patch_listing(
                listing["id"],
                patch_listing_payload(6400, listing["version"]),
                BROKER,
            ),
            200,
        )
        assert patched["asking_price_per_unit_cents"] == 6400
        activated = validate_success(api.activate_listing(listing["id"], BROKER), 200)
        assert activated["status"] == "ACTIVE"


class TestRecommendedPrice:
    def test_recommended_price_null_without_snapshot(self, api):
        """PRD section 3.5: "`BrokerOps` creates it in `DRAFT` against a
        `lot_id`, and the system immediately computes
        `recommended_price_per_unit_cents`: the most recent snapshot for the
        lot's part number — greatest `observed_at`, ties broken by greatest
        `created_at` — marked up by ten percent and rounded half-up to a whole
        cent, or null when no snapshot exists for that part number."

        Design: Corner/calculations/recommended_price_null_without_snapshot
        """
        seller = create_seller(name="Np Ned")
        storage_bin = create_bin(capacity_units=20, bin_code="BIN-NP1")
        lot, _ = create_lot(
            seller, storage_bin, mpn="2N2222", quantity=5,
            ask_price_per_unit_cents=4000, agreed_unit_price_cents=4000,
        )
        listing = validate_success(
            api.create_listing(
                create_listing_payload(lot["id"], asking_price_per_unit_cents=7000),
                BROKER,
            ),
            201,
        )
        assert listing["recommended_price_per_unit_cents"] is None
        assert listing["status"] == "DRAFT"


class TestOccRepricing:
    def test_stale_reprice_rejected_and_version_bumps_on_success(self, api):
        """PRD section 2.9: "A reprice request must carry
        `expected_listing_version`, a non-optional field holding the listing
        `version` the client last observed. If that value no longer matches the
        listing's current `version` — because another write has advanced the
        listing since the client's last read — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412) and no change is applied. A successful
        reprice increments the listing's `version` by one."

        Design: Corner/cross_cutting_layers/listing_patch_stale_version_conflict
        """
        seller = create_seller(name="Oc Ollie")
        storage_bin = create_bin(capacity_units=20, bin_code="BIN-OC1")
        lot, _ = create_lot(
            seller, storage_bin, mpn="ULN2003", quantity=5,
            ask_price_per_unit_cents=5000, agreed_unit_price_cents=5000,
        )
        listing = validate_success(
            api.create_listing(
                create_listing_payload(lot["id"], asking_price_per_unit_cents=8000),
                BROKER,
            ),
            201,
        )
        observed_version = listing["version"]

        patched = validate_success(
            api.patch_listing(
                listing["id"],
                patch_listing_payload(8500, observed_version),
                BROKER,
            ),
            200,
        )
        assert patched["version"] == observed_version + 1, (
            "a successful reprice must bump version by exactly one"
        )

        res = api.patch_listing(
            listing["id"],
            patch_listing_payload(9000, observed_version),
            BROKER,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_losing_stale_write_does_not_apply(self, api):
        """PRD section 2.9: "If that value no longer matches the listing's
        current `version` — because another write has advanced the listing
        since the client's last read — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412) and no change is applied."

        Design: Corner/cross_cutting_layers/listing_patch_stale_version_conflict
        """
        seller = create_seller(name="Oc Ollie")
        storage_bin = create_bin(capacity_units=20, bin_code="BIN-OC1")
        lot, _ = create_lot(
            seller, storage_bin, mpn="ULN2003", quantity=5,
            ask_price_per_unit_cents=5000, agreed_unit_price_cents=5000,
        )
        listing = validate_success(
            api.create_listing(
                create_listing_payload(lot["id"], asking_price_per_unit_cents=8000),
                BROKER,
            ),
            201,
        )
        observed_version = listing["version"]
        validate_success(
            api.patch_listing(
                listing["id"], patch_listing_payload(8500, observed_version), BROKER
            ),
            200,
        )
        validate_error(
            api.patch_listing(
                listing["id"], patch_listing_payload(9000, observed_version), BROKER
            ),
            ApiErrorId.ERR_STALE_VERSION,
        )
        reread = validate_success(api.get_listing(listing["id"], BROKER), 200)
        assert reread["asking_price_per_unit_cents"] == 8500, (
            "the stale write must not overwrite the winning price"
        )

"""Rights-slot lifecycle: initial state, withdraw guard, and the
AVAILABLE <-> ENCUMBERED cycle driven by exclusive licenses."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_slot,
    create_direct_license,
    create_license_payload,
    create_rights_slot_payload,
    get_license,
    get_slot,
    get_success_data,
    setup_catalog,
    validate_error,
    validate_success,
)

RM = TEST_USERS["rights_manager_headers"]


class TestSlotInitialState:
    def test_slot_created_in_initial_available_state(self, api):
        """PRD §3.2: "The slot's `slot_status` begins at `AVAILABLE`."

        Design: Corner/state_machines/slot_created_in_initial_available_state
        """
        workspace = setup_catalog()
        resp = api.create_rights_slot(
            create_rights_slot_payload(
                workspace["title"]["id"], workspace["holder"]["id"],
            ),
            RM,
        )
        slot = validate_success(resp, 201)
        assert slot["slot_status"] == "AVAILABLE"


class TestSlotWithdrawGuard:
    def test_slot_withdraw_from_encumbered_returns_409(self, api):
        """PRD §3.2: "A `RightsManager` may pull a slot from the market by withdrawing it, which is permitted only while the slot is `AVAILABLE`; attempting to withdraw a slot in any other state is rejected with `ERR_SLOT_NOT_WITHDRAWABLE` (409)."

        Design: Corner/state_machines/slot_withdraw_from_encumbered_returns_409
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-08-01T00:00:00Z",
            license_end="2026-12-01T00:00:00Z",
            exclusive=True, flat_fee_cents=100000,
        )
        assert get_slot(slot["id"])["slot_status"] == "ENCUMBERED"

        resp = api.withdraw_rights_slot(slot["id"], RM)
        validate_error(resp, ApiErrorId.ERR_SLOT_NOT_WITHDRAWABLE, 409)
        assert get_slot(slot["id"])["slot_status"] == "ENCUMBERED", (
            "a rejected withdraw must leave the slot ENCUMBERED with no side effects"
        )

    def test_license_create_on_withdrawn_slot_returns_409(self, api):
        """PRD §3.6: "The slot must not be `WITHDRAWN` or `EXPIRED` — an `ENCUMBERED` slot is allowed, because the conflict rules are what decide — otherwise the create is rejected with `ERR_SLOT_NOT_AVAILABLE`."

        Design: Corner/validations/license_create_on_withdrawn_slot_returns_409
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        get_success_data(api.withdraw_rights_slot(slot["id"], RM))

        resp = api.create_license_agreement(
            create_license_payload(slot["id"], workspace["platform"]["id"]),
            RM,
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_NOT_AVAILABLE, 409)


class TestSlotEncumberReleaseCycle:
    def test_slot_cycles_available_encumbered_available_encumbered(self, api):
        """PRD §3.4: "When an exclusive license comes into existence on a slot — whether by direct deal or by package acceptance — the slot moves from `AVAILABLE` to `ENCUMBERED`."
        PRD §3.6: "If the license was exclusive and no other `EXECUTED` or `ACTIVE` exclusive license references the slot, the slot moves from `ENCUMBERED` back to `AVAILABLE`, and the line-unblock cascade restores `BLOCKED` lines on `OFFERED` packages to `OFFERED`."

        Design: Difficulty/non_linear_state_machine/rights_slot_encumber_release_cycle
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        assert slot["slot_status"] == "AVAILABLE"

        first = create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-08-01T00:00:00Z",
            license_end="2026-12-01T00:00:00Z",
            exclusive=True, flat_fee_cents=100000,
        )
        assert get_slot(slot["id"])["slot_status"] == "ENCUMBERED"

        get_success_data(api.terminate_license(first["id"], RM))
        assert get_slot(slot["id"])["slot_status"] == "AVAILABLE", (
            "terminating the only exclusive license must release the slot"
        )

        create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-09-01T00:00:00Z",
            license_end="2027-01-01T00:00:00Z",
            exclusive=True, flat_fee_cents=200000,
        )
        assert get_slot(slot["id"])["slot_status"] == "ENCUMBERED", (
            "the cycle must be re-enterable: a new exclusive license re-encumbers"
        )

    def test_terminated_exclusive_license_does_not_block_successor(self, api):
        """PRD §3.4: "The same-cell check applies to licenses sharing title (through the slot), territory, language, and window type, ignoring `EXPIRED` and `TERMINATED` licenses; it fires `ERR_EXCLUSIVITY_CONFLICT`."

        Design: Difficulty/non_linear_state_machine/rights_slot_encumber_release_cycle
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        first = create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-08-01T00:00:00Z",
            license_end="2026-12-01T00:00:00Z",
            exclusive=True, flat_fee_cents=100000,
        )
        get_success_data(api.terminate_license(first["id"], RM))
        assert get_license(first["id"])["license_status"] == "TERMINATED"

        successor = create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-09-01T00:00:00Z",
            license_end="2027-01-01T00:00:00Z",
            exclusive=True, flat_fee_cents=200000,
        )
        assert successor["license_status"] == "EXECUTED", (
            "a TERMINATED exclusive license must not block a successor on the slot"
        )


class TestSlotAvailabilityInvariant:
    def test_partial_compensation_keeps_slot_encumbered(self, api):
        """PRD §3.4: "When an exclusive license on a slot becomes `EXPIRED` or `TERMINATED` and no other `EXECUTED` or `ACTIVE` exclusive license still references the slot — and the slot itself is not already `EXPIRED` or `WITHDRAWN`, since slot expiry dominates — the slot returns from `ENCUMBERED` to `AVAILABLE`."

        Design: Difficulty/compensating_invariant/license_terminate_restores_slot_availability_invariant
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        first = create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-08-01T00:00:00Z",
            license_end="2026-12-01T00:00:00Z",
            exclusive=True, flat_fee_cents=100000,
        )
        create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-12-01T00:00:00Z",
            license_end="2027-04-01T00:00:00Z",
            exclusive=True, flat_fee_cents=100000,
        )
        assert get_slot(slot["id"])["slot_status"] == "ENCUMBERED"

        get_success_data(api.terminate_license(first["id"], RM))
        assert get_slot(slot["id"])["slot_status"] == "ENCUMBERED", (
            "one EXECUTED exclusive license still references the slot, so the "
            "encumbrance predicate must hold after only partial compensation"
        )

    def test_full_compensation_restores_slot_available(self, api):
        """PRD §3.4: "When an exclusive license on a slot becomes `EXPIRED` or `TERMINATED` and no other `EXECUTED` or `ACTIVE` exclusive license still references the slot — and the slot itself is not already `EXPIRED` or `WITHDRAWN`, since slot expiry dominates — the slot returns from `ENCUMBERED` to `AVAILABLE`."

        Design: Difficulty/compensating_invariant/license_terminate_restores_slot_availability_invariant
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        first = create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-08-01T00:00:00Z",
            license_end="2026-12-01T00:00:00Z",
            exclusive=True, flat_fee_cents=100000,
        )
        second = create_direct_license(
            slot["id"], workspace["platform"]["id"],
            license_start="2026-12-01T00:00:00Z",
            license_end="2027-04-01T00:00:00Z",
            exclusive=True, flat_fee_cents=100000,
        )

        get_success_data(api.terminate_license(first["id"], RM))
        get_success_data(api.terminate_license(second["id"], RM))
        assert get_slot(slot["id"])["slot_status"] == "AVAILABLE", (
            "with zero EXECUTED/ACTIVE exclusive licenses remaining, the slot "
            "must return to AVAILABLE"
        )
        assert get_license(first["id"])["license_status"] == "TERMINATED"
        assert get_license(second["id"])["license_status"] == "TERMINATED"

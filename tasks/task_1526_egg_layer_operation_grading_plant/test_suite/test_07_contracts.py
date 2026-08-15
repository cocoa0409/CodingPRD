"""Retailer contracts: windows, schema consistency, allocation gates, expiry."""
import pytest

from test_helpers import (
    ApiErrorId,
    confirm_grading_run,
    contract_payload,
    create_draft_settlement,
    grading_submit_payload,
    run_daily_ops,
    set_clock,
    setup_active_contract,
    setup_confirmed_lot,
    setup_farm,
    setup_laying_flock_with_production,
    setup_shipped_lots,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    CONTRACT_MANAGER,
    QA_MANAGER,
    get_contract,
    get_lot,
)


def _window(farm_id, start, end, retailer="RetailCo"):
    return contract_payload(
        farm_id, retailer_name=retailer, effective_start=start, effective_end=end
    )


class TestContractWindows:
    def test_contract_windows_half_open_touching_allowed(self, api):
        """PRD §3.6: "The effective window runs from `effective_start`
        inclusive to `effective_end` exclusive — a half-open window"
        PRD §3.6: "Among contracts of the same farm that have not reached
        `EXPIRED`, the half-open windows must not overlap — touching at a
        boundary is allowed — and the check runs both at creation and again at
        activation, where a violation is rejected with
        `ERR_CONTRACT_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/contract_windows_half_open_touching_allowed
        """
        farm = setup_farm()
        validate_success(
            api.create_contract(
                _window(farm["id"], "2026-01-01", "2026-03-01", retailer="A"),
                CONTRACT_MANAGER,
            ),
            201,
        )
        c2 = validate_success(
            api.create_contract(
                _window(farm["id"], "2026-03-01", "2026-06-01", retailer="B"),
                CONTRACT_MANAGER,
            ),
            201,
        )
        assert c2["status"] == "DRAFT", (
            "a window starting exactly at the other's end is adjacency, not overlap"
        )

    def test_contract_windows_day_earlier_overlaps(self, api):
        """PRD §3.6: "Among contracts of the same farm that have not reached
        `EXPIRED`, the half-open windows must not overlap — touching at a
        boundary is allowed — and the check runs both at creation and again at
        activation, where a violation is rejected with
        `ERR_CONTRACT_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/contract_windows_half_open_touching_allowed
        """
        farm = setup_farm()
        validate_success(
            api.create_contract(
                _window(farm["id"], "2026-01-01", "2026-03-01", retailer="A"),
                CONTRACT_MANAGER,
            ),
            201,
        )
        resp = api.create_contract(
            _window(farm["id"], "2026-02-28", "2026-05-01", retailer="C"),
            CONTRACT_MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_WINDOW_OVERLAP)
        _, meta = validate_paginated(
            api.list_contracts(CONTRACT_MANAGER, params={"farm_id": farm["id"]})
        )
        assert meta["total_count"] == 1, "the overlapping contract must not persist"


class TestContractSchema:
    def test_market_index_contract_with_margin_rejected(self, api):
        """PRD §3.6: "`margin_pct` — the cost-plus margin fraction — is zero
        or more, belongs to `COST_PLUS` contracts, and must be exactly 0 on a
        `MARKET_INDEX` contract; a payload inconsistent with its pricing model
        is rejected with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/validations/market_index_contract_with_margin_rejected
        """
        farm = setup_farm()
        resp = api.create_contract(
            contract_payload(farm["id"], pricing_model="MARKET_INDEX", spread_cents=5,
                             margin_pct=0.20),
            CONTRACT_MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)
        _, meta = validate_paginated(
            api.list_contracts(CONTRACT_MANAGER, params={"farm_id": farm["id"]})
        )
        assert meta["total_count"] == 0


class TestAllocationGates:
    def test_allocate_to_draft_contract_rejected(self, api):
        """PRD §3.5: "The contract must be `ACTIVE`, else
        `ERR_CONTRACT_INACTIVE` (HTTP 409)."

        Design: Corner/validations/allocate_to_draft_contract_rejected
        """
        ctx = setup_confirmed_lot(eggs_to_grade=240)
        lot_id = ctx["lots"][0]["id"]
        contract = validate_success(
            api.create_contract(contract_payload(ctx["farm"]["id"]), CONTRACT_MANAGER),
            201,
        )
        validate_success(api.release_lot(lot_id, QA_MANAGER))

        resp = api.allocate_lot(lot_id, {"contract_id": contract["id"]}, CONTRACT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_INACTIVE)
        assert get_lot(lot_id)["lifecycle_status"] == "RELEASED"
        assert get_contract(contract["id"])["status"] == "DRAFT"

    def test_allocate_rejected_on_claim_mismatch(self, api):
        """PRD §3.5: "The lot's claim must satisfy the contract's
        `claim_required`: `NONE` accepts every claim program; `CAGE_FREE`
        accepts a lot whose `claim_program` is `CAGE_FREE` or `PASTURE`;
        `PASTURE` accepts only a `PASTURE` lot — a failure is
        `ERR_CLAIM_MISMATCH` (HTTP 409)."

        Design: Corner/validations/allocate_rejected_on_claim_mismatch
        """
        ctx = setup_confirmed_lot(eggs_to_grade=240)
        lot_id = ctx["lots"][0]["id"]
        assert ctx["lots"][0]["claim_program"] == "CONVENTIONAL"
        contract = setup_active_contract(
            ctx["farm"]["id"], claim_required="CAGE_FREE", claim_premium_pct=0.10
        )
        validate_success(api.release_lot(lot_id, QA_MANAGER))

        resp = api.allocate_lot(lot_id, {"contract_id": contract["id"]}, CONTRACT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_CLAIM_MISMATCH)
        assert get_lot(lot_id)["lifecycle_status"] == "RELEASED"
        assert get_contract(contract["id"])["allocated_dozen"] == 0

    def _setup_two_released_lots(self, api, max_open_dozen=30):
        """480 eggs -> two confirmed runs of 240 -> lot1, lot2 (20 dozen each);
        ACTIVE contract; lot1 released + allocated (allocated_dozen 20),
        lot2 released only."""
        ctx = setup_laying_flock_with_480(api)
        run1, lots1 = confirm_grading_run(ctx["flock"]["id"], "A", 240)
        run2, lots2 = confirm_grading_run(ctx["flock"]["id"], "A", 240)
        ctx["lot1"] = lots1[0]
        ctx["lot2"] = lots2[0]
        ctx["contract"] = setup_active_contract(
            ctx["farm"]["id"], max_open_dozen=max_open_dozen
        )
        validate_success(api.release_lot(ctx["lot1"]["id"], QA_MANAGER))
        validate_success(api.release_lot(ctx["lot2"]["id"], QA_MANAGER))
        validate_success(
            api.allocate_lot(
                ctx["lot1"]["id"], {"contract_id": ctx["contract"]["id"]},
                CONTRACT_MANAGER,
            )
        )
        return ctx

    def test_allocate_rejected_over_volume_cap(self, api):
        """PRD §3.5: "And the volume must fit: the contract's `allocated_dozen`
        plus the lot's `dozen_count` must not exceed `max_open_dozen`, else
        `ERR_CONTRACT_VOLUME_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/allocate_rejected_over_volume_cap
        """
        ctx = self._setup_two_released_lots(api, max_open_dozen=30)
        assert get_contract(ctx["contract"]["id"])["allocated_dozen"] == 20

        resp = api.allocate_lot(
            ctx["lot2"]["id"], {"contract_id": ctx["contract"]["id"]}, CONTRACT_MANAGER
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_VOLUME_EXCEEDED)  # 20 + 20 > 30
        assert get_lot(ctx["lot2"]["id"])["lifecycle_status"] == "RELEASED"
        assert get_contract(ctx["contract"]["id"])["allocated_dozen"] == 20


def setup_laying_flock_with_480(api):
    return setup_laying_flock_with_production(
        [{"lay_date": "2026-07-31", "eggs_collected": 480, "rejected_eggs": 0}]
    )


class TestAllocatePriorityPair:
    def test_allocate_fresh_lot_over_volume_state_beats_fiscal(self, api):
        """PRD §2.8: "Tier 6 is the target entity's own state machine — the
        requested transition must be permitted from its current state, else
        `ERR_INVALID_STATE` (HTTP 409)."
        PRD §2.8: "Tier 12 is money and volume — the contract open-dozen cap
        (`ERR_CONTRACT_VOLUME_EXCEEDED`, HTTP 422) and the non-empty
        settlement requirement (`ERR_SETTLEMENT_EMPTY`, HTTP 422)."
        PRD §2.8: "checks are evaluated in twelve fixed priority tiers, and
        the lowest tier number wins."

        Design: Difficulty/priority_pair_validation_conflict/allocate_fresh_lot_over_volume_state_beats_fiscal
        """
        # Same shape as the volume-cap setup, but lot2 is never released:
        # the request violates tier 6 (FRESH lot) and tier 12 (cap) at once.
        ctx = setup_laying_flock_with_480(api)
        _run1, lots1 = confirm_grading_run(ctx["flock"]["id"], "A", 240)
        _run2, lots2 = confirm_grading_run(ctx["flock"]["id"], "A", 240)
        lot1, lot2 = lots1[0], lots2[0]
        contract = setup_active_contract(ctx["farm"]["id"], max_open_dozen=30)
        validate_success(api.release_lot(lot1["id"], QA_MANAGER))
        validate_success(
            api.allocate_lot(lot1["id"], {"contract_id": contract["id"]}, CONTRACT_MANAGER)
        )
        assert get_contract(contract["id"])["allocated_dozen"] == 20

        resp = api.allocate_lot(lot2["id"], {"contract_id": contract["id"]}, CONTRACT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_allocate_fresh_lot_rejection_leaves_counters_unchanged(self, api):
        """PRD §2.8: "checks are evaluated in twelve fixed priority tiers, and
        the lowest tier number wins."
        PRD §3.5: "Allocating sets the lot's `contract_id`, adds its
        `dozen_count` into the contract's `allocated_dozen`, and increments
        both the lot's and the contract's `version` by 1." (A rejected
        allocate performs none of these.)

        Design: Difficulty/priority_pair_validation_conflict/allocate_fresh_lot_over_volume_state_beats_fiscal
        """
        ctx = setup_laying_flock_with_480(api)
        _run1, lots1 = confirm_grading_run(ctx["flock"]["id"], "A", 240)
        _run2, lots2 = confirm_grading_run(ctx["flock"]["id"], "A", 240)
        lot1, lot2 = lots1[0], lots2[0]
        contract = setup_active_contract(ctx["farm"]["id"], max_open_dozen=30)
        validate_success(api.release_lot(lot1["id"], QA_MANAGER))
        validate_success(
            api.allocate_lot(lot1["id"], {"contract_id": contract["id"]}, CONTRACT_MANAGER)
        )

        resp = api.allocate_lot(lot2["id"], {"contract_id": contract["id"]}, CONTRACT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_lot(lot2["id"])["lifecycle_status"] == "FRESH"
        assert get_contract(contract["id"])["allocated_dozen"] == 20, (
            "no partial mutation from a rejected allocate"
        )


class TestContractExpiry:
    def test_contract_auto_expires_at_effective_end(self, api):
        """PRD §3.6: "Finally, the daily ops run expires any contract whose
        `effective_end` has arrived — the clock date on or after
        `effective_end` — from `DRAFT`, `ACTIVE`, or `SUSPENDED` into terminal
        `EXPIRED`, processing contracts in `effective_end` ascending order;
        expiry from `ACTIVE` or `SUSPENDED` also auto-voids the contract's
        `DRAFT` settlements, and each transition increments the contract's
        `version` by 1."

        Design: Corner/state_machines/contract_auto_expires_at_effective_end
        """
        farm = setup_farm()
        contract = setup_active_contract(
            farm["id"], effective_start="2026-01-01", effective_end="2026-08-10",
            max_open_dozen=100,
        )
        settlement = create_draft_settlement(
            contract["id"], "2026-07-27", "2026-08-02", market_index_cents=140
        )
        set_clock("2026-08-10T00:00:00Z")
        summary = run_daily_ops()
        assert summary["contracts_expired"] == 1

        contract_after = get_contract(contract["id"])
        assert contract_after["status"] == "EXPIRED", (
            "the half-open window ends at 2026-08-10, so the 2026-08-10 run expires it"
        )
        settlement_after = validate_success(
            api.get_settlement(settlement["id"], CONTRACT_MANAGER)
        )
        assert settlement_after["status"] == "VOIDED", (
            "contract expiry auto-voids its DRAFT settlements"
        )

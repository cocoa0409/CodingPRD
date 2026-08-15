"""End-of-season disposition: approval gating, scope snapshotting, execution
preconditions, and memorabilia-sale proceeds."""
from test_helpers import (
    EM,
    TA,
    ApiErrorId,
    assert_disposition_case,
    create_approved_disposition,
    create_disposition,
    create_pool,
    get_case,
    get_pool,
    setup_reserved_kit,
    validate_error,
    validate_success,
)


class TestDispositionStateMachine:
    def test_disposition_execute_from_proposed_rejected(self, api):
        """PRD §3.8: "Execution is the `EquipmentManager`'s act on an
        `APPROVED` case (`ERR_DISPOSITION_NOT_APPROVED` otherwise)."

        Design: Corner/state_machines/disposition_execute_from_proposed_rejected
        """
        create_pool(season_label="2026-FALL", garment_type="SOCKS",
                    size_code="L", stock_on_hand=3)
        case = create_disposition(season_label="2026-FALL",
                                  garment_type="SOCKS", method="DISCARD")
        assert case["status"] == "PROPOSED"

        resp = api.execute_disposition_case(case["id"], EM)
        validate_error(resp, ApiErrorId.ERR_DISPOSITION_NOT_APPROVED)
        assert get_case(case["id"])["status"] == "PROPOSED", (
            "The rejected execution leaves the case PROPOSED")

    def test_disposition_approve_twice_rejected(self, api):
        """PRD §3.8: "A `TeamAdmin` then adjudicates. Approval — valid only
        from `PROPOSED` (`ERR_DISPOSITION_NOT_PROPOSED`) — snapshots the scope
        into `affected_pool_ids`: every `ACTIVE` pool matching the case's
        season and garment type, narrowed to the size code when one was
        given."

        Design: Corner/state_machines/disposition_approve_twice_rejected
        """
        create_pool(season_label="2026-FALL", garment_type="SOCKS",
                    size_code="M", stock_on_hand=2)
        case = create_approved_disposition(season_label="2026-FALL",
                                           garment_type="SOCKS", method="DONATE")
        assert case["status"] == "APPROVED"

        resp = api.approve_disposition_case(case["id"], TA)
        validate_error(resp, ApiErrorId.ERR_DISPOSITION_NOT_PROPOSED)
        assert get_case(case["id"])["status"] == "APPROVED", (
            "The second approval is refused and the case stays APPROVED")


class TestDispositionExecution:
    def test_disposition_scope_empty_rejected(self, api):
        """PRD §3.8: "The snapshot must be non-empty
        (`ERR_DISPOSITION_SCOPE_EMPTY`), and every affected pool must stand
        clear of commitments — zero reserved and zero in-laundry units — or
        the execution halts with `ERR_POOL_HAS_ACTIVE_COMMITMENTS`."

        Design: Corner/validations/disposition_scope_empty_rejected
        """
        case = create_approved_disposition(season_label="2027-FALL",
                                           garment_type="SOCKS", method="DISCARD")
        assert case["status"] == "APPROVED", (
            "Approval succeeds even when no pool matches the scope")

        resp = api.execute_disposition_case(case["id"], EM)
        validate_error(resp, ApiErrorId.ERR_DISPOSITION_SCOPE_EMPTY)
        assert get_case(case["id"])["status"] == "APPROVED", (
            "The empty-scope execution halts without executing the case")

    def test_disposition_blocked_by_reserved_pool_rejected(self, api):
        """PRD §3.8: "every affected pool must stand clear of commitments —
        zero reserved and zero in-laundry units — or the execution halts with
        `ERR_POOL_HAS_ACTIVE_COMMITMENTS`."

        Design: Corner/validations/disposition_blocked_by_reserved_pool_rejected
        """
        ws = setup_reserved_kit(jersey_number=72, jersey_stock=4, pants_stock=4,
                                player_name="Blk One")
        case = create_approved_disposition(season_label="2026-FALL",
                                           garment_type="GAME_JERSEY",
                                           method="DONATE")

        resp = api.execute_disposition_case(case["id"], EM)
        validate_error(resp, ApiErrorId.ERR_POOL_HAS_ACTIVE_COMMITMENTS)

        pool = get_pool(ws["jersey_pool"]["id"])
        assert pool["stock_on_hand"] == 4
        assert pool["status"] == "ACTIVE", (
            "The halted execution leaves the committed pool untouched")
        assert get_case(case["id"])["status"] == "APPROVED"

    def test_disposition_memorabilia_proceeds_totals(self, api):
        """PRD §3.8: "`MEMORABILIA_SALE` performs the same write-off and
        closure, but records `proceeds_cents` as the disposed units multiplied
        by the case's `unit_price_cents`."
        PRD §3.8: "`DONATE` and `DISCARD` write each affected pool's
        `stock_on_hand` off to zero — the total counted into `units_disposed`
        — and close the pools (`ACTIVE → CLOSED`), with zero proceeds."
        PRD §3.8: "an optional `size_code` filter (omitting it scopes the
        case to every size of that garment)"

        Design: Corner/calculations/disposition_memorabilia_proceeds_totals
        """
        pool_m = create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                             size_code="M", stock_on_hand=4)
        pool_l = create_pool(season_label="2026-FALL", garment_type="GAME_JERSEY",
                             size_code="L", stock_on_hand=6)
        case = create_approved_disposition(
            season_label="2026-FALL", garment_type="GAME_JERSEY",
            method="MEMORABILIA_SALE", unit_price_cents=1500)
        assert set(case["affected_pool_ids"]) == {pool_m["id"], pool_l["id"]}, (
            "Approval snapshots every ACTIVE pool of the season and garment")

        executed = validate_success(api.execute_disposition_case(case["id"], EM))
        assert_disposition_case(executed)
        assert executed["status"] == "EXECUTED"
        assert executed["units_disposed"] == 10, "4 in size M plus 6 in size L"
        assert executed["proceeds_cents"] == 15000, "10 units x 1500 cents"

        for pool_id in (pool_m["id"], pool_l["id"]):
            pool = get_pool(pool_id)
            assert pool["stock_on_hand"] == 0
            assert pool["status"] == "CLOSED", (
                "A memorabilia sale writes off and closes every affected pool")

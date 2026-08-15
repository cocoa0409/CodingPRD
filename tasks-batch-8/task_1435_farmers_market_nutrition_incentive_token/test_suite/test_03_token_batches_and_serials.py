"""Token-batch registration, serial governance, minting order, and recall (PRD §3.1, §3.4)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    create_program, create_market, create_batch, create_token_batch_payload,
    setup_booth_scenario, issue_tokens,
    assert_token, assert_token_batch,
)

ADMIN = TEST_USERS["program_admin_headers"]
BOOTH = TEST_USERS["booth_operator_headers"]
MANAGER = TEST_USERS["market_manager_headers"]

_SERIAL_RULE = (
    "Serial ranges are policed program-wide across every kind and denomination: "
    "a new batch's closed range may not intersect the range of any other batch "
    "that has not been `RECALLED`, and because the ranges are closed intervals, "
    "sharing even a single endpoint serial is a conflict rejected with "
    "`ERR_SERIAL_RANGE_OVERLAP`; strictly adjacent ranges, where one batch's "
    "`serial_end` sits exactly one below the other's `serial_start`, are legal."
)


class TestBatchRegistration:
    def test_match_batch_denomination_constraint(self, api):
        """PRD §3.1: "Shape rules enforced at registration: `BASE` batches may
        carry only the 500-cent or 100-cent denomination, `MATCH` batches must
        carry the 100-cent denomination, and `serial_end` may not precede
        `serial_start` — violations are rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/c_ent_match_batch_denomination_constraint
        """
        program = create_program(pool_cents=50000)
        market = create_market(program["id"])
        resp = api.create_token_batch(
            create_token_batch_payload(market_id=market["id"], kind="MATCH",
                                       denomination_cents=500,
                                       serial_start=300001, serial_end=300100),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_recall_sealed_batch_rejected(self, api):
        """PRD §3.1: "Recall moves an `ACTIVE` batch to `RECALLED`, which is
        terminal, and triggers a two-hop cascade: every token of the batch still
        `ISSUED` transitions to `VOIDED` (tokens already `REDEEMED`, `SETTLED`,
        `FLAGGED`, or `CONFISCATED` are unaffected), and for each affected market
        day the `voided_value_cents` and `variance_cents` recompute — the
        variance dropping by the voided face value, which can move a day between
        `CLOSED` and `VARIANCE_FLAGGED` as its variance crosses the
        reconciliation tolerance in either direction."
        PRD §2.10: "State gates come next: first the generic rule that any
        transition attempted from a state that does not permit it is rejected
        with `ERR_INVALID_STATE`, then the specific gates in their relative
        order — shopper eligibility (`ERR_SHOPPER_NOT_ELIGIBLE`), vendor
        standing (`ERR_VENDOR_NOT_ACTIVE`), market-day openness
        (`ERR_MARKET_DAY_NOT_OPEN`), and market-day closedness
        (`ERR_MARKET_DAY_NOT_CLOSED`)."

        Design: Corner/state_machines/c_sm_batch_recall_from_sealed_rejected
        """
        program = create_program(pool_cents=50000)
        market = create_market(program["id"])
        batch = create_batch(market["id"], "BASE", 500, 100001, 100100, activate=False)
        assert batch["status"] == "SEALED"

        resp = api.recall_token_batch(batch["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_success_data(api.get_token_batch(batch["id"], ADMIN))
        assert after["status"] == "SEALED", "batch untouched by invalid recall"


class TestSerialRangeGovernance:
    def test_shared_endpoint_serial_conflicts(self, api):
        """PRD §3.1: "Serial ranges are policed program-wide across every kind
        and denomination: a new batch's closed range may not intersect the range
        of any other batch that has not been `RECALLED`, and because the ranges
        are closed intervals, sharing even a single endpoint serial is a conflict
        rejected with `ERR_SERIAL_RANGE_OVERLAP`; strictly adjacent ranges, where
        one batch's `serial_end` sits exactly one below the other's
        `serial_start`, are legal."

        Design: Difficulty/resource_temporal_overlap/serial_range_closed_interval_endpoint_sharing_vs_adjacency
        """
        program = create_program()
        market = create_market(program["id"])
        create_batch(market["id"], "BASE", 500, 100001, 100100, activate=False)

        conflict = api.create_token_batch(
            create_token_batch_payload(market_id=market["id"], kind="BASE",
                                       denomination_cents=500,
                                       serial_start=100100, serial_end=100200),
            ADMIN)
        validate_error(conflict, ApiErrorId.ERR_SERIAL_RANGE_OVERLAP)

    def test_strictly_adjacent_serial_ranges_legal(self, api):
        """PRD §3.1: "Serial ranges are policed program-wide across every kind
        and denomination: a new batch's closed range may not intersect the range
        of any other batch that has not been `RECALLED`, and because the ranges
        are closed intervals, sharing even a single endpoint serial is a conflict
        rejected with `ERR_SERIAL_RANGE_OVERLAP`; strictly adjacent ranges, where
        one batch's `serial_end` sits exactly one below the other's
        `serial_start`, are legal."

        Design: Difficulty/resource_temporal_overlap/serial_range_closed_interval_endpoint_sharing_vs_adjacency
        """
        program = create_program()
        market = create_market(program["id"])
        create_batch(market["id"], "BASE", 500, 100001, 100100, activate=False)

        adjacent = api.create_token_batch(
            create_token_batch_payload(market_id=market["id"], kind="BASE",
                                       denomination_cents=500,
                                       serial_start=100101, serial_end=100200),
            ADMIN)
        created = validate_success(adjacent, expected_status=201)
        assert_token_batch(created)
        assert created["serial_start"] == 100101

    def test_serial_overlap_scope_is_program_wide(self, api):
        """PRD §3.1: "Serial ranges are policed program-wide across every kind
        and denomination: a new batch's closed range may not intersect the range
        of any other batch that has not been `RECALLED`, and because the ranges
        are closed intervals, sharing even a single endpoint serial is a conflict
        rejected with `ERR_SERIAL_RANGE_OVERLAP`; strictly adjacent ranges, where
        one batch's `serial_end` sits exactly one below the other's
        `serial_start`, are legal."

        Design: Difficulty/resource_temporal_overlap/serial_overlap_scope_is_program_wide_across_markets
        """
        program = create_program()
        market_a = create_market(program["id"], name="M-A")
        market_b = create_market(program["id"], name="M-B")
        create_batch(market_a["id"], "BASE", 500, 100001, 100100, activate=False)

        cross_market = api.create_token_batch(
            create_token_batch_payload(market_id=market_b["id"], kind="MATCH",
                                       denomination_cents=100,
                                       serial_start=100050, serial_end=100300),
            ADMIN)
        validate_error(cross_market, ApiErrorId.ERR_SERIAL_RANGE_OVERLAP)

    def test_serial_overlap_program_wide_no_partial_creation(self, api):
        """PRD §3.1: "Serial ranges are policed program-wide across every kind
        and denomination: a new batch's closed range may not intersect the range
        of any other batch that has not been `RECALLED`, and because the ranges
        are closed intervals, sharing even a single endpoint serial is a conflict
        rejected with `ERR_SERIAL_RANGE_OVERLAP`; strictly adjacent ranges, where
        one batch's `serial_end` sits exactly one below the other's
        `serial_start`, are legal."
        PRD §3.1: "The batch roster of a market can be listed with `market_id`,
        `status`, and `kind` filters."

        Design: Difficulty/resource_temporal_overlap/serial_overlap_scope_is_program_wide_across_markets
        """
        program = create_program()
        market_a = create_market(program["id"], name="M-A")
        market_b = create_market(program["id"], name="M-B")
        create_batch(market_a["id"], "BASE", 500, 100001, 100100, activate=False)

        cross_market = api.create_token_batch(
            create_token_batch_payload(market_id=market_b["id"], kind="MATCH",
                                       denomination_cents=100,
                                       serial_start=100050, serial_end=100300),
            ADMIN)
        validate_error(cross_market, ApiErrorId.ERR_SERIAL_RANGE_OVERLAP)

        batches_b, meta_b = validate_paginated(
            api.list_token_batches(ADMIN, params={"market_id": market_b["id"]}))
        assert meta_b["total_count"] == 0, "rejected registration leaves no batch at market B"


class TestMinting:
    def test_token_fields_stamped_from_batch(self, api):
        """PRD §3.1: "Every token minted anywhere in the program records its
        `serial_number`, the `kind` and `denomination_cents` copied from its
        supplying batch, the `issuance_id` that minted it, the `token_batch_id`
        its serial was drawn from, and two lifecycle references that start
        empty: `redeemed_vendor_id`, set when a vendor accepts the token, and
        `submission_id`, set while a reimbursement claim holds the token."
        PRD §3.4: "Among eligible batches the winner has the lowest
        `serial_start`, ties broken by the earliest `created_at`, never by `id`."

        Design: Corner/entities/c_ent_token_system_fields_stamped_from_batch
        """
        sc = setup_booth_scenario()
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 300)

        assert len(tokens) == 6, "charge 300 mints 3 base + 3 match tokens"
        for token in tokens:
            assert_token(token)
            assert token["issuance_id"] == issuance["id"]
        assert tokens[0]["serial_number"] == 200001, "first BASE-100 serial of the batch"
        assert tokens[0]["kind"] == "BASE"
        assert tokens[3]["serial_number"] == 300001, "first MATCH serial of the match batch"
        assert tokens[3]["kind"] == "MATCH"
        assert tokens[3]["denomination_cents"] == 100

    def test_serial_minting_order_and_batch_cursor(self, api):
        """PRD §3.4: "Minting assigns serials in ascending order beginning at
        the chosen batch's `next_serial`, which then advances by the number
        minted; once `next_serial` passes `serial_end` the batch is exhausted."
        PRD §3.4: "The base value, recorded as `base_value_cents` and always
        equal to `benefit_charged_cents`, is minted greedily, largest
        denomination first, over the `BASE` denominations: as many five-dollar
        tokens as the value allows, then one-dollar tokens for the remainder."

        Design: Corner/calculations/c_calc_serial_minting_order_and_batch_cursor
        """
        sc = setup_booth_scenario()
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 1200)

        serials = [t["serial_number"] for t in tokens]
        assert serials == sorted(serials), "token list is serial ascending"
        assert serials[:5] == [100001, 100002, 200001, 200002, 300001], (
            "2x500 base, then 2x100 base, then 12x100 match")
        assert len(tokens) == 16

        b5 = get_success_data(api.get_token_batch(sc["batch_base500"]["id"], ADMIN))
        bm = get_success_data(api.get_token_batch(sc["batch_match"]["id"], ADMIN))
        assert b5["next_serial"] == 100003, "cursor advanced by the 2 minted 500s"
        assert bm["next_serial"] == 300013, "cursor advanced by the 12 minted match tokens"


class TestBatchRecallCascade:
    def _setup_issued_300(self, api):
        sc = setup_booth_scenario(with_vendor=False)
        issuance, tokens = issue_tokens(sc["shopper"]["id"], sc["market_day"]["id"], 300)
        sc.update({"issuance": issuance, "tokens": tokens})
        return sc

    def test_batch_recall_voids_issued_tokens(self, api):
        """PRD §3.1: "Recall moves an `ACTIVE` batch to `RECALLED`, which is
        terminal, and triggers a two-hop cascade: every token of the batch still
        `ISSUED` transitions to `VOIDED` (tokens already `REDEEMED`, `SETTLED`,
        `FLAGGED`, or `CONFISCATED` are unaffected), and for each affected market
        day the `voided_value_cents` and `variance_cents` recompute — the
        variance dropping by the voided face value, which can move a day between
        `CLOSED` and `VARIANCE_FLAGGED` as its variance crosses the
        reconciliation tolerance in either direction."

        Design: Difficulty/transitive_cascade/batch_recall_void_cascade_depth2
        """
        sc = self._setup_issued_300(api)
        recalled = validate_success(api.recall_token_batch(sc["batch_base100"]["id"], ADMIN))
        assert recalled["status"] == "RECALLED"

        data, _meta = validate_paginated(
            api.list_tokens(ADMIN, params={"issuance_id": sc["issuance"]["id"], "limit": 100}))
        by_serial = {t["serial_number"]: t for t in data}
        for serial in (200001, 200002, 200003):
            assert by_serial[serial]["status"] == "VOIDED", f"base token {serial} voided by recall"
        for serial in (300001, 300002, 300003):
            assert by_serial[serial]["status"] == "ISSUED", f"match token {serial} of another batch unaffected"

    def test_batch_recall_recomputes_day_ledger(self, api):
        """PRD §3.1: "Recall moves an `ACTIVE` batch to `RECALLED`, which is
        terminal, and triggers a two-hop cascade: every token of the batch still
        `ISSUED` transitions to `VOIDED` (tokens already `REDEEMED`, `SETTLED`,
        `FLAGGED`, or `CONFISCATED` are unaffected), and for each affected market
        day the `voided_value_cents` and `variance_cents` recompute — the
        variance dropping by the voided face value, which can move a day between
        `CLOSED` and `VARIANCE_FLAGGED` as its variance crosses the
        reconciliation tolerance in either direction."
        PRD §3.2: "The day's `variance_cents` is what remains unaccounted:
        issued minus voided minus redeemed."

        Design: Difficulty/transitive_cascade/batch_recall_void_cascade_depth2
        """
        sc = self._setup_issued_300(api)
        validate_success(api.recall_token_batch(sc["batch_base100"]["id"], ADMIN))

        day = get_success_data(api.get_market_day(sc["market_day"]["id"], ADMIN))
        assert day["issued_value_cents"] == 600, "voided issuance still minted 600 on the day"
        assert day["voided_value_cents"] == 300, "3 voided base-100 tokens"
        assert day["redeemed_value_cents"] == 0
        assert day["variance_cents"] == 300, "600 - 300 - 0"
        assert day["status"] == "OPEN", "recall moves only the ledger, not an OPEN day's status"

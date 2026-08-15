"""Weekly cycle checkpoint and mission transfer pool math, OCC, SoD, lifecycle."""
from test_helpers import (
    ApiErrorId,
    FIN,
    MGR,
    assert_same_instant,
    close_cycle,
    count_session,
    close_till_session,
    create_cycle,
    create_mission_transfer,
    create_worker,
    disburse_transfer,
    approve_transfer,
    get_open_cycle,
    get_success_data,
    make_finance_clerk_headers,
    make_store_manager_headers,
    open_till_session,
    set_clock,
    setup_closed_cycle_with_net_revenue,
    validate_error,
    validate_paginated,
    validate_success,
)


def _amounts_by_program(transfer):
    return {line["program"]: line["amount_cents"]
            for line in transfer["allocation_amounts"]}


class TestCycleOpenUniqueness:
    def test_cycle_second_open_rejected(self, api):
        """PRD 2.7: "Store merchandising runs on weekly cycles, and at most one
        WeeklyCycle may be OPEN at any moment: attempting to open a cycle while
        another is OPEN is rejected with `ERR_CYCLE_INVALID_STATE`."
        PRD 3.4: "The close then spawns the next cycle: sequence number advanced by
        one, rotation color advanced accordingly, status OPEN"

        Design: Corner/endpoints/cycle_second_open_rejected
        """
        cycle1 = create_cycle()
        resp = api.create_cycle(MGR)
        validate_error(resp, ApiErrorId.ERR_CYCLE_INVALID_STATE)

        close_cycle(cycle1["id"])
        # The close itself spawned the next OPEN cycle, so a manual open still fails.
        resp2 = api.create_cycle(MGR)
        validate_error(resp2, ApiErrorId.ERR_CYCLE_INVALID_STATE)
        open_cycle = get_open_cycle()
        assert open_cycle["id"] != cycle1["id"]


class TestCycleCloseTillGate:
    def test_cycle_close_blocked_by_open_till(self, api):
        """PRD 3.4: "Close is blocked while any till session remains `OPEN`,
        `PENDING_APPROVAL`, or `RECONCILED` — every drawer must reach `CLOSED` first,
        or the close fails with `ERR_TILL_SESSIONS_UNCLOSED`."

        Design: Corner/endpoints/cycle_close_blocked_by_open_till
        """
        cycle = create_cycle()
        cashier = create_worker("W Cash", "STAFF")
        session = open_till_session(cashier["id"], 4000)

        resp = api.close_cycle(cycle["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_TILL_SESSIONS_UNCLOSED)

        count_session(session["id"], 4000)
        close_till_session(session["id"])
        closed = close_cycle(cycle["id"])
        assert closed["status"] == "CLOSED", "the retry succeeds once drawers close"


class TestCycleCloseEpoch:
    def test_cycle_close_spawns_next_epoch(self, api):
        """PRD 3.4: "And `shrink_rate_bp` is the shrink value multiplied by ten
        thousand and divided by the sum of the shrink value and gross sales, rounded
        half up to a whole basis point — or zero when that denominator is zero."
        PRD 3.4: "The close then spawns the next cycle: sequence number advanced by
        one, rotation color advanced accordingly, status OPEN, `opened_at` from the
        clock, and `shrink_alert_active` copied from the closing cycle's posture test"
        PRD 2.7: "a sequence number whose remainder when divided by four is 1 rotates
        `RED`, remainder 2 rotates `BLUE`"

        Design: Corner/complexity_layers/cycle_close_spawns_next_epoch
        """
        cycle1 = create_cycle()
        assert cycle1["sequence_number"] == 1
        assert cycle1["rotation_color"] == "RED"
        set_clock("2026-08-06T00:00:00Z")

        closed = close_cycle(cycle1["id"])
        assert closed["status"] == "CLOSED"
        assert_same_instant(closed["closed_at"], "2026-08-06T00:00:00Z")
        assert closed["gross_sales_cents"] == 0
        assert closed["salvage_revenue_cents"] == 0
        assert closed["net_revenue_cents"] == 0
        assert closed["shrink_value_cents"] == 0
        assert closed["shrink_rate_bp"] == 0, "zero denominator pins the rate to 0"

        cycle2 = get_open_cycle()
        assert cycle2["sequence_number"] == 2
        assert cycle2["rotation_color"] == "BLUE"
        assert cycle2["status"] == "OPEN"
        assert_same_instant(cycle2["opened_at"], "2026-08-06T00:00:00Z")
        assert cycle2["shrink_alert_active"] is False
        assert cycle2["markdown_runs_count"] == 0


class TestMissionPoolTiers:
    def test_mission_pool_tier_keyed_on_gross(self, api):
        """PRD 3.9: "The transfer's amounts are computed in a pinned order, because
        the reserve tier reads the gross pool, not the net."
        PRD 3.9: "Keying the tier on the net instead would misprice the reserve: a
        gross pool of 110000 cents tiers at 15 percent — reserve 16500, net pool
        93500 — where a net-keyed reading would wrongly have taken 10 percent."

        Design: Difficulty/combinatorial_formula/mission_pool_tier_keyed_on_gross
        """
        closed_cycle = setup_closed_cycle_with_net_revenue(110000)
        assert closed_cycle["net_revenue_cents"] == 110000

        transfer = create_mission_transfer(
            closed_cycle["id"], closed_cycle["version"],
            [
                {"program": "JOB_TRAINING", "pct": 50.000},
                {"program": "YOUTH_SERVICES", "pct": 30.000},
                {"program": "HOUSING_SUPPORT", "pct": 20.000},
            ],
            preparer_user_id="fin-1",
        )
        assert transfer["status"] == "DRAFT"
        assert transfer.get("prepared_by_user_id") == "fin-1"
        assert transfer["gross_pool_cents"] == 110000
        assert transfer["reserve_pct"] == 15, "110000 gross lands in the 15% tier"
        assert transfer["reserve_cents"] == 16500
        assert transfer["net_pool_cents"] == 93500
        amounts = _amounts_by_program(transfer)
        assert amounts == {
            "JOB_TRAINING": 46750,
            "YOUTH_SERVICES": 28050,
            "HOUSING_SUPPORT": 18700,
        }
        assert sum(amounts.values()) == 93500

    def test_mission_pool_under_first_tier(self, api):
        """PRD 3.9: "Then `reserve_pct` is keyed on that gross figure: under 100000
        cents the reserve is 10 percent; at least 100000 and under 500000 cents it is
        15 percent; at least 500000 cents it is 20 percent. Next `reserve_cents` is
        the gross pool multiplied by the reserve percentage and divided by one
        hundred, rounded half up to whole cents, and `net_pool_cents` is the gross
        pool minus the reserve."

        Design: Difficulty/combinatorial_formula/mission_pool_tier_keyed_on_gross
        """
        closed_cycle = setup_closed_cycle_with_net_revenue(99999)
        assert closed_cycle["net_revenue_cents"] == 99999

        transfer = create_mission_transfer(
            closed_cycle["id"], closed_cycle["version"],
            [{"program": "GENERAL_FUND", "pct": 100.000}],
            preparer_user_id="fin-1",
        )
        assert transfer["gross_pool_cents"] == 99999
        assert transfer["reserve_pct"] == 10, "gross below 100000 tiers at 10%"
        # round_half_up(99999 x 10 / 100) = round(9999.9) = 10000.
        assert transfer["reserve_cents"] == 10000
        assert transfer["net_pool_cents"] == 89999
        assert _amounts_by_program(transfer) == {"GENERAL_FUND": 89999}


class TestTransferSupersedeAndRemainder:
    def test_transfer_supersede_and_remainder(self, api):
        """PRD 3.9: "Creation supersedes the cycle's paperwork: any existing DRAFT
        transfer for the same cycle moves to `CANCELLED`."
        PRD 3.9: "Each line of `allocation_amounts` then takes the net pool
        multiplied by the line's `pct` and divided by one hundred, rounded half DOWN
        to whole cents, and whatever remainder remains after the rounded lines are
        summed is added to the LAST line in request order, so the lines always sum
        exactly to `net_pool_cents`."

        Design: Corner/calculations/transfer_supersede_and_remainder
        """
        closed_cycle = setup_closed_cycle_with_net_revenue(110000)
        first = create_mission_transfer(
            closed_cycle["id"], closed_cycle["version"],
            [
                {"program": "JOB_TRAINING", "pct": 50.000},
                {"program": "YOUTH_SERVICES", "pct": 30.000},
                {"program": "HOUSING_SUPPORT", "pct": 20.000},
            ],
            preparer_user_id="fin-1",
        )
        fresh = validate_success(api.get_cycle(closed_cycle["id"], FIN))

        second = create_mission_transfer(
            closed_cycle["id"], fresh["version"],
            [
                {"program": "JOB_TRAINING", "pct": 33.334},
                {"program": "YOUTH_SERVICES", "pct": 33.333},
                {"program": "HOUSING_SUPPORT", "pct": 33.333},
            ],
            preparer_user_id="fin-1",
        )
        assert second["status"] == "DRAFT"
        assert second["net_pool_cents"] == 93500
        # round_half_down lines: 31167.29 -> 31167, 31166.355 -> 31166, 31166.355 ->
        # 31166; the 1-cent remainder lands on the LAST line in request order.
        amounts = _amounts_by_program(second)
        assert amounts == {
            "JOB_TRAINING": 31167,
            "YOUTH_SERVICES": 31166,
            "HOUSING_SUPPORT": 31167,
        }
        assert sum(amounts.values()) == 93500

        first_after = validate_success(api.get_transfer(first["id"], MGR))
        assert first_after["status"] == "CANCELLED", "the new draft supersedes it"


class TestTransferOccAndAllocation:
    def test_occ_transfer_create_stale_version(self, api):
        """PRD 2.8: "A request creating a mission transfer for a cycle must carry
        `expected_cycle_version` holding the cycle `version` the client last
        observed. A mismatch with the cycle's current `version` is rejected with
        `ERR_STALE_CYCLE_VERSION` (HTTP 412). A new draft transfer legitimately
        supersedes the cycle's existing draft, so a writer holding a stale version
        would supersede a transfer it never saw."

        Design: Corner/complexity_layers/occ_transfer_create_stale_version
        """
        closed_cycle = setup_closed_cycle_with_net_revenue(0)
        first = create_mission_transfer(
            closed_cycle["id"], closed_cycle["version"],
            [{"program": "GENERAL_FUND", "pct": 100.000}],
        )
        assert first["status"] == "DRAFT"

        # The create bumped the cycle version, replaying the observed one is stale.
        resp = api.create_mission_transfer(
            closed_cycle["id"],
            {
                "expected_cycle_version": closed_cycle["version"],
                "allocations": [{"program": "JOB_TRAINING", "pct": 100.000}],
            },
            FIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_CYCLE_VERSION, 412)

        first_after = validate_success(api.get_transfer(first["id"], MGR))
        assert first_after["status"] == "DRAFT", (
            "the rejected create must not supersede the existing draft"
        )

    def test_allocation_sum_not_100_rejected(self, api):
        """PRD 3.9: "Each allocation names a `program` — `JOB_TRAINING`,
        `YOUTH_SERVICES`, `HOUSING_SUPPORT`, or `GENERAL_FUND` — and a `pct` greater
        than zero and at most 100, with up to three decimal places; the percentages
        across the array must sum to exactly 100, else `ERR_ALLOCATION_SUM_INVALID`."

        Design: Corner/validations/allocation_sum_not_100_rejected
        """
        closed_cycle = setup_closed_cycle_with_net_revenue(0)
        resp = api.create_mission_transfer(
            closed_cycle["id"],
            {
                "expected_cycle_version": closed_cycle["version"],
                "allocations": [
                    {"program": "JOB_TRAINING", "pct": 60.000},
                    {"program": "GENERAL_FUND", "pct": 30.000},
                ],
            },
            FIN,
        )
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_SUM_INVALID)

        transfers, meta = validate_paginated(
            api.list_transfers(MGR, params={"cycle_id": closed_cycle["id"]})
        )
        assert transfers == [], "a rejected transfer leaves no row"


class TestTransferLifecycleAndSod:
    def test_sod_preparer_cannot_approve_transfer(self, api):
        """PRD 2.10: "Mission transfers split preparation from approval the same way:
        the `StoreManager` approving a transfer must differ from the `FinanceClerk`
        recorded as `prepared_by_user_id`, or the approval is rejected with
        `ERR_SOD_APPROVER_IS_PREPARER` (HTTP 422)."
        PRD 3.9: "A `FinanceClerk` then disburses an APPROVED transfer, stamping
        `disbursed_at` and moving it `APPROVED` → `DISBURSED`"

        Design: Corner/validations/sod_preparer_cannot_approve_transfer
        """
        closed_cycle = setup_closed_cycle_with_net_revenue(0)
        transfer = create_mission_transfer(
            closed_cycle["id"], closed_cycle["version"],
            [
                {"program": "JOB_TRAINING", "pct": 50.000},
                {"program": "GENERAL_FUND", "pct": 50.000},
            ],
            preparer_user_id="fin-1",
        )

        resp = api.approve_transfer(transfer["id"], make_store_manager_headers("fin-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_APPROVER_IS_PREPARER)

        approved = approve_transfer(transfer["id"], approver_user_id="mgr-1")
        assert approved["status"] == "APPROVED"
        assert approved.get("approved_by_user_id") == "mgr-1"

        disbursed = disburse_transfer(transfer["id"], disburser_user_id="fin-1")
        assert disbursed["status"] == "DISBURSED"
        assert disbursed.get("disbursed_at"), "disburse stamps the clock"

    def test_transfer_disburse_from_draft_rejected(self, api):
        """PRD 3.9: "A `FinanceClerk` then disburses an APPROVED transfer, stamping
        `disbursed_at` and moving it `APPROVED` → `DISBURSED`; disbursing from any
        other state is likewise `ERR_TRANSFER_INVALID_STATE`."

        Design: Corner/errors/transfer_disburse_from_draft_rejected
        """
        closed_cycle = setup_closed_cycle_with_net_revenue(0)
        transfer = create_mission_transfer(
            closed_cycle["id"], closed_cycle["version"],
            [{"program": "GENERAL_FUND", "pct": 100.000}],
        )
        resp = api.disburse_transfer(transfer["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_TRANSFER_INVALID_STATE)
        after = validate_success(api.get_transfer(transfer["id"], MGR))
        assert after["status"] == "DRAFT"

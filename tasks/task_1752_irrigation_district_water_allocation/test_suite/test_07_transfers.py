"""Transfers of allocation: shape rules, lifecycle gates, balance re-checks,
drought freeze, OCC, and volume conservation."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_amount,
    assert_transfer_request,
    create_drought,
    create_reach,
    create_transfer,
    create_transfer_request_payload,
    effectuate_drought,
    get_allocation,
    get_transfer,
    make_water_user_headers,
    place_order,
    post_transfer_full,
    setup_two_accounts_with_allocations,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTransferShapeAndLifecycle:
    def test_transfer_to_same_account_returns_invalid_request(self, api):
        """PRD §2.7: "The transfer rule that `to_account_id` must differ from
        `from_account_id` is a shape rule enforced here."
        PRD §3.6: "`to_account_id` (which must differ from the source; this is
        a request-shape rule)".

        Design: Corner/validations/transfer_to_same_account_returns_invalid_request
        """
        scenario = setup_two_accounts_with_allocations()
        account_a = scenario["account_a"]
        allocation = get_allocation(scenario["alloc_a"]["id"])
        resp = api.create_transfer_request(
            create_transfer_request_payload(
                account_a["id"], account_a["id"], scenario["season"]["id"], 1.0,
                expected_source_allocation_version=allocation["version"],
            ),
            make_water_user_headers(account_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_post_pending_transfer_rejected(self, api):
        """PRD §3.6: "Transfers in terminal states — `POSTED`, `REJECTED`,
        `CANCELLED` — accept no further transitions; posting a `PENDING`
        transfer or approving a `POSTED` one is refused with
        `ERR_INVALID_TRANSFER_STATE`."

        Design: Corner/state_machines/post_pending_transfer_rejected
        """
        scenario = setup_two_accounts_with_allocations()
        transfer = create_transfer(
            scenario["alloc_a"]["id"], scenario["account_a"]["id"],
            scenario["account_b"]["id"], scenario["season"]["id"], 1.0,
        )
        assert transfer["status"] == "PENDING"

        resp = api.post_transfer(transfer["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSFER_STATE)

        alloc_a = get_allocation(scenario["alloc_a"]["id"])
        alloc_b = get_allocation(scenario["alloc_b"]["id"])
        assert_amount(alloc_a["transfers_out_af"], 0.00,
                      "No ledger movement on the source")
        assert_amount(alloc_b["transfers_in_af"], 0.00,
                      "No ledger movement on the destination")


class TestBalanceRechecks:
    def _setup_transfer_then_order(self, transfer_qty):
        """Transfer created while the source has 10.00 af available; then an
        order commits 8.26 af (5 cfs x 20 h), leaving 1.74 af."""
        scenario = setup_two_accounts_with_allocations(acres_a=5.0, acres_b=1.0)
        reach = create_reach(name="Reach RK", max_capacity_cfs=50.0)
        transfer = create_transfer(
            scenario["alloc_a"]["id"], scenario["account_a"]["id"],
            scenario["account_b"]["id"], scenario["season"]["id"], transfer_qty,
        )
        place_order(
            scenario["account_a"]["id"], scenario["alloc_a"]["id"], reach["id"],
            requested_cfs=5.0,
            start="2026-06-01T08:00:00Z", end="2026-06-02T04:00:00Z",
        )
        scenario.update({"transfer": transfer, "reach": reach})
        return scenario

    def test_approve_transfer_rechecks_balance(self, api):
        """PRD §3.6: "Approving a `PENDING` transfer re-verifies that both
        accounts are still `ACTIVE`, that the season remains `OPEN`, that no
        drought declaration has become `EFFECTIVE`, and that the source
        allocation's `available_af` still covers `quantity_af`, moving the
        transfer `PENDING → APPROVED`."
        With 8.26 af newly committed, available is 1.74 — below the 5.00 af
        transfer — so approval is refused.

        Design: Corner/validations/approve_transfer_rechecks_balance
        """
        scenario = self._setup_transfer_then_order(5.0)
        resp = api.approve_transfer(scenario["transfer"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ALLOCATION)
        assert get_transfer(scenario["transfer"]["id"])["status"] == "PENDING"

    def test_post_transfer_rechecks_balance(self, api):
        """PRD §3.6: "Posting an `APPROVED` transfer repeats the
        account-active check, the drought freeze, and the source-balance check
        one final time — a balance that sufficed at approval may no longer
        suffice at posting if intervening orders have committed water — ..."
        The 3.00 af transfer was approved at 10.00 available; at post time
        available is 1.74, so posting is refused.

        Design: Corner/validations/post_transfer_rechecks_balance
        """
        scenario = setup_two_accounts_with_allocations(acres_a=5.0, acres_b=1.0)
        reach = create_reach(name="Reach PR", max_capacity_cfs=50.0)
        transfer = create_transfer(
            scenario["alloc_a"]["id"], scenario["account_a"]["id"],
            scenario["account_b"]["id"], scenario["season"]["id"], 3.0,
        )
        validate_success(api.approve_transfer(transfer["id"], ADMIN))
        place_order(
            scenario["account_a"]["id"], scenario["alloc_a"]["id"], reach["id"],
            requested_cfs=5.0,
            start="2026-06-01T08:00:00Z", end="2026-06-02T04:00:00Z",
        )

        resp = api.post_transfer(transfer["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ALLOCATION)

        transfer_after = get_transfer(transfer["id"])
        assert transfer_after["status"] == "APPROVED"
        alloc_a = get_allocation(scenario["alloc_a"]["id"])
        assert_amount(alloc_a["transfers_out_af"], 0.00,
                      "No ledger movement occurred")


class TestTransferOCC:
    def test_occ_stale_version_on_transfer_create(self, api):
        """PRD §2.6: "Requesting a transfer must carry
        `expected_source_allocation_version` equal to the current `version` of
        the source `SeasonAllocation`. A mismatch with the source allocation's
        current version is likewise rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD §3.6: "A transfer is born `PENDING`; its creation increments the
        source allocation's `version` by 1."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_transfer_create
        """
        scenario = setup_two_accounts_with_allocations()
        account_a = scenario["account_a"]
        stale_version = scenario["alloc_a"]["version"]

        first = validate_success(
            api.create_transfer_request(
                create_transfer_request_payload(
                    account_a["id"], scenario["account_b"]["id"],
                    scenario["season"]["id"], 1.0,
                    expected_source_allocation_version=stale_version,
                ),
                make_water_user_headers(account_a["id"]),
            ),
            expected_status=201,
        )
        assert_transfer_request(first)
        assert first["status"] == "PENDING"

        allocation = get_allocation(scenario["alloc_a"]["id"])
        assert allocation["version"] == stale_version + 1, (
            "Transfer creation increments the source allocation version by 1"
        )

        resp = api.create_transfer_request(
            create_transfer_request_payload(
                account_a["id"], scenario["account_b"]["id"],
                scenario["season"]["id"], 1.0,
                expected_source_allocation_version=stale_version,
            ),
            make_water_user_headers(account_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestDroughtFreeze:
    def _setup_effective_drought(self):
        # SENIOR account A (10.00 af) and JUNIOR account B (10.00 -> 8.50 af
        # under STAGE_1); no orders, so the cascade cancels nothing.
        scenario = setup_two_accounts_with_allocations(
            acres_a=5.0, acres_b=5.0,
            priority_a="1888-01-01T00:00:00Z",
            priority_b="1922-05-01T00:00:00Z",
        )
        drought = create_drought(scenario["season"]["id"], "STAGE_1")
        effectuate_drought(drought["id"])
        scenario["drought"] = drought
        return scenario

    def test_transfer_blocked_by_effective_drought(self, api):
        """PRD §3.6: "Creation requires both accounts `ACTIVE` (else
        `ERR_ACCOUNT_NOT_ACTIVE`), the season `OPEN` (else
        `ERR_SEASON_NOT_OPEN`), no `EFFECTIVE` drought declaration on the
        season (else `ERR_TRANSFER_BLOCKED_DROUGHT`), and a source
        `available_af` on the net-of-committed reading at least equal to
        `quantity_af` (else `ERR_INSUFFICIENT_ALLOCATION`)."
        Both accounts are ACTIVE and the 1.00 af balance check would pass, yet
        the drought freeze rejects the create.

        Design: Difficulty/cross_entity_state_dependency/transfer_blocked_by_effective_drought
        """
        scenario = self._setup_effective_drought()
        resp = api.create_transfer_request(
            create_transfer_request_payload(
                scenario["account_a"]["id"], scenario["account_b"]["id"],
                scenario["season"]["id"], 1.0,
                expected_source_allocation_version=get_allocation(
                    scenario["alloc_a"]["id"]
                )["version"],
            ),
            make_water_user_headers(scenario["account_a"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TRANSFER_BLOCKED_DROUGHT)

        _data, meta = validate_paginated(
            api.list_transfer_requests(
                ADMIN, params={"from_account_id": scenario["account_a"]["id"]},
            )
        )
        assert meta["total_count"] == 0, "No transfer may be persisted"

    def test_approve_blocked_when_drought_becomes_effective(self, api):
        """PRD §3.7: "While any declaration is `EFFECTIVE` on a season, the
        transfer freeze of §3.6 applies to transfer creation, approval, and
        posting alike."

        Design: Difficulty/cross_entity_state_dependency/transfer_blocked_by_effective_drought
        """
        scenario = setup_two_accounts_with_allocations(
            acres_a=5.0, acres_b=5.0,
            priority_a="1888-01-01T00:00:00Z",
            priority_b="1922-05-01T00:00:00Z",
        )
        # Transfer created while no declaration is EFFECTIVE.
        transfer = create_transfer(
            scenario["alloc_a"]["id"], scenario["account_a"]["id"],
            scenario["account_b"]["id"], scenario["season"]["id"], 1.0,
        )
        assert transfer["status"] == "PENDING"

        drought = create_drought(scenario["season"]["id"], "STAGE_1")
        effectuate_drought(drought["id"])

        resp = api.approve_transfer(transfer["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_TRANSFER_BLOCKED_DROUGHT)
        assert get_transfer(transfer["id"])["status"] == "PENDING"


class TestTransferConservation:
    def test_post_moves_volume_between_ledgers(self, api):
        """PRD §3.6: "on success moves the transfer `APPROVED → POSTED` while
        mutating both ledgers in one stroke: `quantity_af` is added to the
        source allocation's `transfers_out_af` and to the destination
        allocation's `transfers_in_af`, and both allocations' `version` values
        increment by 1."
        After posting 3.00 af A->B: A.available_af is 7.00 and
        B.available_af is 5.00.

        Design: Difficulty/compensating_invariant/transfer_post_and_reverse_volume_conservation
        """
        scenario = setup_two_accounts_with_allocations(acres_a=5.0, acres_b=1.0)
        transfer = post_transfer_full(
            scenario["alloc_a"]["id"], scenario["account_a"]["id"],
            scenario["account_b"]["id"], scenario["season"]["id"], 3.0,
        )
        assert transfer["status"] == "POSTED"

        alloc_a = get_allocation(scenario["alloc_a"]["id"])
        alloc_b = get_allocation(scenario["alloc_b"]["id"])
        assert_amount(alloc_a["transfers_out_af"], 3.00, "A.transfers_out_af")
        assert_amount(alloc_a["available_af"], 7.00, "A.available_af")
        assert_amount(alloc_b["transfers_in_af"], 3.00, "B.transfers_in_af")
        assert_amount(alloc_b["available_af"], 5.00, "B.available_af")
        assert_amount(
            alloc_a["available_af"] + alloc_b["available_af"], 12.00,
            "A.available_af + B.available_af (no volume created)",
        )

    def test_reverse_post_restores_balances(self, api):
        """PRD §3.6: "`quantity_af` is added to the source allocation's
        `transfers_out_af` and to the destination allocation's
        `transfers_in_af`..."
        Posting 3.00 af A->B and then the compensating 3.00 af B->A returns
        both available balances to 10.00 and 2.00, with district-wide
        transfers_in minus transfers_out equal to zero.

        Design: Difficulty/compensating_invariant/transfer_post_and_reverse_volume_conservation
        """
        scenario = setup_two_accounts_with_allocations(acres_a=5.0, acres_b=1.0)
        post_transfer_full(
            scenario["alloc_a"]["id"], scenario["account_a"]["id"],
            scenario["account_b"]["id"], scenario["season"]["id"], 3.0,
        )
        post_transfer_full(
            scenario["alloc_b"]["id"], scenario["account_b"]["id"],
            scenario["account_a"]["id"], scenario["season"]["id"], 3.0,
        )

        alloc_a = get_allocation(scenario["alloc_a"]["id"])
        alloc_b = get_allocation(scenario["alloc_b"]["id"])
        assert_amount(alloc_a["available_af"], 10.00, "A.available_af restored")
        assert_amount(alloc_b["available_af"], 2.00, "B.available_af restored")
        net = (alloc_a["transfers_in_af"] + alloc_b["transfers_in_af"]) - (
            alloc_a["transfers_out_af"] + alloc_b["transfers_out_af"]
        )
        assert_amount(net, 0.00, "district-wide transfers_in - transfers_out")
        assert_amount(
            alloc_a["available_af"] + alloc_b["available_af"], 12.00,
            "total available water is conserved",
        )

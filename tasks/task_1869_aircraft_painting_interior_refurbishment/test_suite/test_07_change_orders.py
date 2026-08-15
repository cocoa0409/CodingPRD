"""Change orders: the three-link approval cascade and OCC (PRD §2.6, §3.7, §3.10)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_calendar_day,
    assert_change_order,
    assert_delay_event,
    create_engagement,
    create_invoice,
    create_submitted_change_order,
    get_program,
    make_customer_rep_headers,
    set_logical_clock,
    setup_ready_for_delivery,
    validate_error,
    validate_paginated,
    validate_success,
)

_PM = TEST_USERS["program_manager_headers"]
_FIN = TEST_USERS["finance_clerk_headers"]


class TestApprovalCascade:
    def test_approval_updates_contract_value_and_committed_date(self, api):
        """PRD §3.7: "Link one: the program's `total_contract_value_cents` —
        defined as `base_price_cents` plus the signed `delta_price_cents` of
        every `APPROVED` change order — absorbs this order's delta, and if
        `delta_days` is positive the `committed_delivery_date` shifts out by
        that many days; the program version increments."

        Design: Difficulty/transitive_cascade/change_order_approval_depth3_cascade
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        ctx = create_engagement()
        order = create_submitted_change_order(
            ctx["program"]["id"], delta_price_cents=600000, delta_days=3,
            description="Add galley refurbishment",
        )
        resp = api.approve_change_order(
            order["id"],
            {"expected_program_version": get_program(ctx["program"]["id"])["version"]},
            make_customer_rep_headers(ctx["customer"]["id"]),
        )
        approved = validate_success(resp)
        assert_change_order(approved)
        assert approved["status"] == "APPROVED"

        program = get_program(ctx["program"]["id"])
        assert program["total_contract_value_cents"] == 12345673 + 600000
        assert_calendar_day(
            program["committed_delivery_date"], "2026-09-04", "committed_delivery_date"
        )

    def test_approval_spawns_confirmed_event_and_regenerates_invoice(self, api):
        """PRD §3.7: "Link two: that same positive `delta_days` causes the
        system to create a Delay Event with `source` of `CHANGE_ORDER`,
        category `CUSTOMER_CAUSED`, `impact_days` equal to the `delta_days`,
        and status `CONFIRMED` — such events are born confirmed and never pass
        through `REPORTED`. Link three: the confirmation of that event triggers
        recomputation of the program's `projected_penalty_cents` and
        regeneration of every DRAFT invoice's lines, including the penalty
        credit line on the `FINAL` kind."

        Design: Difficulty/transitive_cascade/change_order_approval_depth3_cascade
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        ctx = create_engagement()
        invoice = create_invoice(ctx["program"]["id"], "FINAL")
        assert invoice["total_cents"] == 6172837  # remainder only

        order = create_submitted_change_order(
            ctx["program"]["id"], delta_price_cents=600000, delta_days=3,
            description="Add galley refurbishment",
        )
        validate_success(
            api.approve_change_order(
                order["id"],
                {"expected_program_version": get_program(ctx["program"]["id"])["version"]},
                make_customer_rep_headers(ctx["customer"]["id"]),
            )
        )

        # Link 2: exactly one delay event, born CONFIRMED via CHANGE_ORDER.
        events, meta = validate_paginated(api.list_delay_events(_PM))
        assert meta["total_count"] == 1
        event = events[0]
        assert_delay_event(event)
        assert event["source"] == "CHANGE_ORDER"
        assert event["status"] == "CONFIRMED"
        assert event["category"] == "CUSTOMER_CAUSED"
        assert event["impact_days"] == 3

        # Link 3: the DRAFT FINAL invoice regenerated its remainder line from
        # the new contract value: 12945673 - 1234567 - 4938269 = 6772837.
        regen = validate_success(api.get_invoice(invoice["id"], _FIN))
        assert regen["total_cents"] == 6772837


class TestPenaltyEvaluationOrder:
    def test_cap_uses_post_approval_contract_value(self, api):
        """PRD §3.10: "First, the contract value is fixed as `base_price_cents`
        plus the signed `delta_price_cents` of all `APPROVED` change orders —
        the cap depends on this value, so it is computed before anything else.
        Second, the cap is that contract value multiplied by the program's
        `penalty_cap_pct`, rounded half-up to integer cents."

        Design: Difficulty/combinatorial_formula/penalty_evaluation_order_pinned
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        ctx = setup_ready_for_delivery()
        order = create_submitted_change_order(
            ctx["program"]["id"], delta_price_cents=2400000, delta_days=5,
            description="Add satcom interior scope",
        )
        validate_success(
            api.approve_change_order(
                order["id"],
                {"expected_program_version": get_program(ctx["program"]["id"])["version"]},
                make_customer_rep_headers(ctx["customer"]["id"]),
            )
        )
        program = get_program(ctx["program"]["id"])
        assert program["total_contract_value_cents"] == 12345673 + 2400000 == 14745673
        assert_calendar_day(
            program["committed_delivery_date"], "2026-09-06", "committed_delivery_date"
        )

    def test_days_counted_against_adjusted_committed_date(self, api):
        """PRD §3.10: "Third, the adjusted committed date is the contractual
        date plus the included excusable events' days in `event_seq` order.
        Fourth, the non-excusable late days are the calendar days from that
        adjusted date to the reference date, floored at zero. Fifth, the raw
        penalty is those days multiplied by `daily_penalty_rate_cents`. Sixth
        and finally, the penalty is the smaller of the raw figure and the cap."
        and the settlement variant "takes its reference date as the actual
        delivery date (or the logical clock date at issuance if the aircraft
        has not yet been delivered)".

        Design: Difficulty/combinatorial_formula/penalty_evaluation_order_pinned
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        ctx = setup_ready_for_delivery()
        order = create_submitted_change_order(
            ctx["program"]["id"], delta_price_cents=2400000, delta_days=5,
            description="Add satcom interior scope",
        )
        validate_success(
            api.approve_change_order(
                order["id"],
                {"expected_program_version": get_program(ctx["program"]["id"])["version"]},
                make_customer_rep_headers(ctx["customer"]["id"]),
            )
        )
        set_logical_clock("2026-09-10T00:00:00Z")

        invoice = create_invoice(ctx["program"]["id"], "FINAL")
        issued = validate_success(api.issue_invoice(invoice["id"], _FIN))
        # Adjusted committed 2026-09-06; 4 late days x 150000 = 600000
        # (cap is round(14745673 x 0.10) = 1474567, not binding).
        program = get_program(ctx["program"]["id"])
        assert program["penalty_final_cents"] == 600000
        # remainder 8572837 + booth 200000 - penalty 600000.
        assert issued["total_cents"] == 8172837


class TestChangeOrderOcc:
    def test_stale_change_order_approval_rejected(self, api, program_manager_headers):
        """PRD §2.6: "If the program's current `version` no longer matches —
        because another writer has advanced it since the client last read the
        program — the request is rejected with `ERR_STALE_PROGRAM_VERSION`
        (HTTP 412)." PRD §3.7: change-order approval is one of "Three write
        operations — and only these three — ... guarded by optimistic
        concurrency control against the Refurb Program's `version`".

        Design: Corner/cross_cutting_complexity_layers/occ_change_order_approve_stale_version_rejected
        """
        ctx = create_engagement()
        v0 = ctx["program"]["version"]
        co1 = create_submitted_change_order(
            ctx["program"]["id"], delta_price_cents=100000, delta_days=0,
            description="CO-1 galley tweak",
        )
        co2 = create_submitted_change_order(
            ctx["program"]["id"], delta_price_cents=200000, delta_days=0,
            description="CO-2 carpet upgrade",
        )

        approved1 = validate_success(
            api.approve_change_order(
                co1["id"], {"expected_program_version": v0},
                make_customer_rep_headers(ctx["customer"]["id"]),
            )
        )
        assert approved1["status"] == "APPROVED"

        stale = api.approve_change_order(
            co2["id"], {"expected_program_version": v0},
            make_customer_rep_headers(ctx["customer"]["id"]),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_PROGRAM_VERSION)

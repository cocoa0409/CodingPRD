"""Invoicing, quota tiers, commission rates, and the accrual ledger (PRD §3.5).

Covers the fulfillment/commission state dimensions, the pinned rating order
(pool read before the order joins it), tier boundary inclusivity, the
registration bonus stack, per-line rounding, largest-remainder allocation,
year rollover, and immediate ledger visibility.
"""
from test_helpers import (
    ApiErrorId,
    CLOCK_DEFAULT,
    approve_registration,
    cancel_order,
    create_invoiced_order,
    create_order,
    get_principal,
    invoice_order,
    list_entries,
    list_splits,
    make_order_line,
    make_principal_ops_headers,
    mark_order_paid,
    order_line,
    parse_instant,
    set_clock,
    setup_base_scenario,
    ship_order,
    splits_for_line,
    submit_registration,
    validate_error,
    validate_paginated,
    TEST_USERS,
)


def _admin():
    return TEST_USERS["agency_admin_headers"]


def _auditor():
    return TEST_USERS["auditor_headers"]


class TestInvoiceStateMachine:
    def test_order_invoice_before_ship_rejected(self, api):
        """PRD §3.5: "Invoicing is the pivotal commercial event, and it too belongs
        to the owning `PrincipalOps` operator acting on a `SHIPPED` order."
        PRD §2.9: "The target resource's state permits the
        requested transition, terminal states are locked, a return authorization is
        created only against an order in `SHIPPED`, `INVOICED`, or `PAID`, a sample
        checkout is created only against a unit in `IN_STOCK`, and a split override is
        attempted only while the order's commission dimension is still `ATTRIBUTED` —
        otherwise `ERR_INVALID_STATE_TRANSITION` or `ERR_SPLITS_LOCKED`."

        Design: Corner/state_machines/order_invoice_before_ship_rejected
        """
        base = setup_base_scenario(agreement_territories=["CA", "OR", "WA"])
        order = create_order(
            base["customer"]["id"], base["principal"]["id"], "PO-1",
            lines=[make_order_line(quantity=5, unit_price_cents=5000)],
        )
        resp = api.invoice_order(
            order["id"], make_principal_ops_headers(base["principal"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = api.get_order(order["id"], _admin()).json()["data"]
        assert after["fulfillment_status"] == "PLACED"
        assert after["commission_status"] == "ATTRIBUTED"
        _e, meta = validate_paginated(
            api.list_commission_entries(_admin(), params={"order_id": order["id"]})
        )
        assert meta["total_count"] == 0, "a rejected invoice must post no accruals"

    def test_cancelled_order_terminal_lockdown(self, api):
        """PRD §3.4: "An order that never should have been booked can be cancelled by
        an `AgencyAdmin`, but only from `PLACED`. Cancellation moves
        `fulfillment_status` to `CANCELLED` and the commission dimension to `CLOSED`,
        increments the order's `version`, and retains the order's split rows for
        audit."
        PRD §2.9: "The target resource's state permits the requested transition,
        terminal states are locked"

        Design: Corner/state_machines/cancelled_order_terminal_lockdown
        """
        base = setup_base_scenario(agreement_territories=["CA", "OR", "WA"])
        order = create_order(
            base["customer"]["id"], base["principal"]["id"], "PO-1",
            lines=[make_order_line(quantity=5, unit_price_cents=5000)],
        )
        cancel_order(order["id"])
        resp = api.ship_order(
            order["id"], make_principal_ops_headers(base["principal"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = api.get_order(order["id"], _admin()).json()["data"]
        assert after["fulfillment_status"] == "CANCELLED"
        assert after["commission_status"] == "CLOSED"

    def test_fulfillment_and_commission_dimensions_independent(self, api):
        """PRD §3.4: "An order evolves along two independent state dimensions on the
        same row: `fulfillment_status` runs from `PLACED` through `SHIPPED` and
        `INVOICED` to `PAID` (or to `CANCELLED` from `PLACED`), while
        `commission_status` runs from `ATTRIBUTED` to `ACCRUED` to `SETTLED` (or to
        `CLOSED` on cancel)."
        PRD §3.5: "Later, when the customer pays, the owning operator records payment:
        `fulfillment_status` moves from `INVOICED` to `PAID`, `paid_at` takes the
        clock, and the version increments again."

        Design: Corner/state_machines/fulfillment_and_commission_dimensions_independent
        """
        base = setup_base_scenario(agreement_territories=["CA", "OR", "WA"])
        order = create_order(
            base["customer"]["id"], base["principal"]["id"], "PO-1",
            lines=[make_order_line(quantity=10, unit_price_cents=5000)],
        )
        ship_order(order["id"], base["principal"]["id"])
        invoice_order(order["id"], base["principal"]["id"])
        paid = mark_order_paid(order["id"], base["principal"]["id"])
        assert paid["fulfillment_status"] == "PAID"
        assert paid["commission_status"] == "ACCRUED", (
            "payment moves only the fulfillment dimension; settle moves commission"
        )
        assert parse_instant(paid["paid_at"]) == parse_instant(CLOCK_DEFAULT)
        assert parse_instant(paid["invoiced_at"]) == parse_instant(CLOCK_DEFAULT)


class TestRatingAndTierBoundaries:
    def test_protected_line_rate_stacks_base_tier_and_bonus(self, api):
        """PRD §3.5: "The effective rate is that base scaled by the tier multiplier
        and divided by 10,000, rounded down to a whole basis point, then increased by
        the schedule's `registration_bonus_bp` when the line is registration-protected
        per §3.3." and "the line's commission is the net amount scaled by the
        effective rate and divided by 10,000, rounded half up to whole cents."
        PRD §3.3: a window "contains the order's `placed_at` — including the window's
        opening instant and excluding its closing instant."

        Design: Difficulty/combinatorial_formula/line_commission_rate_stack_protected
        """
        base = setup_base_scenario()
        principal = base["principal"]
        r1 = base["reps"][0]
        customer = base["customer"]
        reg = submit_registration(principal["id"], customer["id"], r1["id"],
                                  project_name="Project Falcon")
        approve_registration(reg["id"], principal["id"])

        order = create_order(
            customer["id"], principal["id"], "PO-P",
            lines=[make_order_line(quantity=100, unit_price_cents=5000)],
        )
        ship_order(order["id"], principal["id"])
        invoiced = invoice_order(order["id"], principal["id"])

        line = order_line(invoiced, "L1")
        # floor(1000 x 10000 / 10000) + 200 bonus = 1200bp; 500,000c x 1200bp = 60,000c.
        assert line["applied_rate_bp"] == 1200
        assert line["commission_cents"] == 60000
        assert line["protected_registration_id"] == reg["id"]

    def test_protected_line_attribution_registers_full_share(self, api):
        """PRD §3.4: "When the line matches a protected registration per §3.3, a
        single `REGISTERED` row grants the registering rep the agreement's
        `registered_protection_share_bp`, and any residual share falls to a `HOUSE`
        row". With a 10,000bp protection share there is no residual.
        PRD §3.5: "For each pairing of rep and order, one `ACCRUAL` ledger entry posts
        the sum of that rep's per-line shares, with its `business_date` taken from the
        order's `invoiced_at`."

        Design: Difficulty/combinatorial_formula/line_commission_rate_stack_protected
        """
        base = setup_base_scenario()
        principal = base["principal"]
        r1 = base["reps"][0]
        customer = base["customer"]
        reg = submit_registration(principal["id"], customer["id"], r1["id"],
                                  project_name="Project Falcon")
        approve_registration(reg["id"], principal["id"])
        order = create_order(
            customer["id"], principal["id"], "PO-P",
            lines=[make_order_line(quantity=100, unit_price_cents=5000)],
        )
        ship_order(order["id"], principal["id"])
        invoice_order(order["id"], principal["id"])

        rows = splits_for_line(list_splits(order_id=order["id"]), "L1")
        assert len(rows) == 1
        assert rows[0]["role"] == "REGISTERED"
        assert rows[0]["rep_id"] == r1["id"]
        assert rows[0]["share_bp"] == 10000

        entries = list_entries(rep_id=r1["id"], entry_type="ACCRUAL")
        assert len(entries) == 1
        assert entries[0]["amount_cents"] == 60000
        assert entries[0]["order_id"] == order["id"]

    def test_unprotected_line_gets_no_registration_bonus(self, api):
        """PRD §3.5: "The effective rate is that base scaled by the tier multiplier
        and divided by 10,000, rounded down to a whole basis point, then increased by
        the schedule's `registration_bonus_bp` when the line is registration-protected
        per §3.3." Without protection the bonus branch never applies.

        Design: Corner/calculations/unprotected_line_gets_no_registration_bonus
        """
        base = setup_base_scenario(agreement_territories=["CA", "OR", "WA"])
        invoiced = create_invoiced_order(
            base["customer"]["id"], base["principal"]["id"], "PO-NB",
            lines=[make_order_line(quantity=10, unit_price_cents=5000)],
        )
        line = order_line(invoiced, "L1")
        assert line["applied_rate_bp"] == 1000
        assert line["commission_cents"] == 5000

    def test_attainment_exactly_at_threshold_gets_higher_tier(self, api):
        """PRD §3.5: "Third, the applicable tier is the `attainment_tiers` entry with
        the largest `min_attainment_bp` that the attainment value reaches — the
        boundary is inclusive, so attainment exactly equal to a tier's threshold
        qualifies for that tier."

        Design: Difficulty/boundary_precision_check/attainment_tier_boundary_inclusive
        """
        base = setup_base_scenario()
        principal = base["principal"]
        customer = base["customer"]
        # Pool reaches exactly 100% of the 10,000,000c quota: 2000 x 5000c.
        create_invoiced_order(
            customer["id"], principal["id"], "PO-A",
            lines=[make_order_line(quantity=2000, unit_price_cents=5000)],
        )
        order_b = create_order(
            customer["id"], principal["id"], "PO-B",
            lines=[make_order_line(quantity=100, unit_price_cents=5000)],
        )
        ship_order(order_b["id"], principal["id"])
        invoiced = invoice_order(order_b["id"], principal["id"])
        line = order_line(invoiced, "L1")
        # attainment_bp == 10000 qualifies for the {10000, 12500} tier -> 1250bp.
        assert line["applied_rate_bp"] == 1250
        assert line["commission_cents"] == 62500

    def test_attainment_one_bp_below_threshold_stays_lower_tier(self, api):
        """PRD §3.5: "Second, attainment is computed as the pool scaled by 10,000 and
        divided by the principal's `annual_quota_cents`, rounded down to a whole basis
        point." A pool of 9,999,000c against a 10,000,000c quota yields 9,999bp — one
        basis point below the 10,000bp threshold — so the {8000, 11000} tier applies.

        Design: Difficulty/boundary_precision_check/attainment_tier_boundary_inclusive
        """
        base = setup_base_scenario()
        principal = base["principal"]
        customer = base["customer"]
        # 9999 x 1000c = 9,999,000c pool -> floor(9999000 x 10000 / 10000000) = 9999bp.
        create_invoiced_order(
            customer["id"], principal["id"], "PO-A",
            lines=[make_order_line(quantity=9999, unit_price_cents=1000)],
        )
        order_b = create_order(
            customer["id"], principal["id"], "PO-B",
            lines=[make_order_line(quantity=100, unit_price_cents=5000)],
        )
        ship_order(order_b["id"], principal["id"])
        invoiced = invoice_order(order_b["id"], principal["id"])
        line = order_line(invoiced, "L1")
        assert line["applied_rate_bp"] == 1100
        assert line["commission_cents"] == 55000

    def test_invoice_rates_against_pool_excluding_current_order(self, api):
        """PRD §3.5: "Rating follows a pinned evaluation order that removes the
        circular dependency between an order's commission and the quota pool it feeds.
        First, the pool is read as the principal's `credited_ytd_sales_cents` before
        this order joins it." A 9,700,000c pool yields 9,700bp -> the {8000, 11000}
        tier -> 1100bp, not the 12,500bp multiplier a self-inclusive read would give.

        Design: Difficulty/combinatorial_formula/attainment_excludes_invoicing_order
        """
        base = setup_base_scenario()
        principal = base["principal"]
        customer = base["customer"]
        create_invoiced_order(
            customer["id"], principal["id"], "PO-0",
            lines=[make_order_line(quantity=1940, unit_price_cents=5000)],
        )
        order_c = create_order(
            customer["id"], principal["id"], "PO-C",
            lines=[make_order_line(quantity=80, unit_price_cents=5000)],
        )
        ship_order(order_c["id"], principal["id"])
        invoiced = invoice_order(order_c["id"], principal["id"])
        line = order_line(invoiced, "L1")
        assert line["applied_rate_bp"] == 1100
        assert line["commission_cents"] == 44000

    def test_pool_absorbs_order_after_rating(self, api):
        """PRD §3.5: "the principal's `credited_ytd_sales_cents` grows by the sum of
        the order's line amounts — the order joins the year-to-date pool only after
        its own rate was fixed".

        Design: Difficulty/combinatorial_formula/attainment_excludes_invoicing_order
        """
        base = setup_base_scenario()
        principal = base["principal"]
        customer = base["customer"]
        create_invoiced_order(
            customer["id"], principal["id"], "PO-0",
            lines=[make_order_line(quantity=1940, unit_price_cents=5000)],
        )
        assert get_principal(principal["id"])["credited_ytd_sales_cents"] == 9_700_000
        order_c = create_order(
            customer["id"], principal["id"], "PO-C",
            lines=[make_order_line(quantity=80, unit_price_cents=5000)],
        )
        ship_order(order_c["id"], principal["id"])
        invoice_order(order_c["id"], principal["id"])
        assert get_principal(principal["id"])["credited_ytd_sales_cents"] == 10_100_000

    def test_ytd_rollover_resets_attainment(self, api):
        """PRD §3.9: "when a clock advance crosses into a new calendar year, each
        principal's `credited_ytd_sales_cents` resets to zero and its `ytd_year`
        advances, so a new selling year starts with a clean quota pool while the prior
        year's settled history remains in the ledger."

        Design: Corner/calculations/ytd_rollover_resets_attainment
        """
        base = setup_base_scenario(agreement_territories=["CA", "OR", "WA"])
        principal = base["principal"]
        customer = base["customer"]
        set_clock("2026-12-15T00:00:00Z")
        # December order maxes the 10,000,000c quota on its own.
        create_invoiced_order(
            customer["id"], principal["id"], "PO-DEC", placed_at="2026-12-15T00:00:00Z",
            lines=[make_order_line(quantity=2000, unit_price_cents=5000)],
        )
        set_clock("2027-01-05T00:00:00Z")
        after = get_principal(principal["id"])
        assert after["credited_ytd_sales_cents"] == 0
        assert after["ytd_year"] == 2027

        jan = create_order(
            customer["id"], principal["id"], "PO-JAN", placed_at="2027-01-05T00:00:00Z",
            lines=[make_order_line(quantity=100, unit_price_cents=5000)],
        )
        ship_order(jan["id"], principal["id"])
        invoiced = invoice_order(jan["id"], principal["id"])
        line = order_line(invoiced, "L1")
        assert line["applied_rate_bp"] == 1000, "pool reset drops rating back to tier 0"
        assert line["commission_cents"] == 50000


class TestAllocationAndLedger:
    def test_split_allocation_largest_remainder(self, api):
        """PRD §3.5: "Each row's raw share is the line's `commission_cents` scaled by
        the row's `share_bp` and divided by 10,000, rounded down; the leftover cents
        are dealt one by one to the rows ordered by `share_bp` descending, breaking
        ties by the rep's `created_at` ascending. The invariant holds exactly: a
        line's allocated cents sum to its `commission_cents`, and its shares sum to
        10,000."

        Design: Corner/calculations/split_allocation_largest_remainder
        """
        base = setup_base_scenario(agreement_territories=["CA", "OR", "WA"])
        r1, r2 = base["reps"]
        invoiced = create_invoiced_order(
            base["customer"]["id"], base["principal"]["id"], "PO-CENT",
            lines=[make_order_line(quantity=1, unit_price_cents=1005)],
        )
        line = order_line(invoiced, "L1")
        assert line["commission_cents"] == 101, "round half up of 100.5"
        entries = {e["rep_id"]: e["amount_cents"]
                   for e in list_entries(order_id=invoiced["id"], entry_type="ACCRUAL")}
        # floor(60.6)=60 and floor(40.4)=40; the 1c residual goes to the 6000bp row.
        assert entries[r1["id"]] == 61
        assert entries[r2["id"]] == 40
        assert sum(entries.values()) == 101

    def test_fk_reverse_lookup_filtered_lists(self, api):
        """PRD §3.4: "Split rows can be browsed via the split list, narrowed with the
        `order_id` and `rep_id` query parameters."
        PRD §3.7: "All ledger rows — accruals, chargebacks, adjustments, payments,
        recoveries, and sample charges alike — are visible through the entry list,
        filterable by `rep_id`, `principal_id`, `order_id`, `statement_id`, or `type`."

        Design: Corner/endpoints/fk_reverse_lookup_filtered_lists
        """
        base = setup_base_scenario(agreement_territories=["CA", "OR", "WA"])
        r1, r2 = base["reps"]
        invoiced = create_invoiced_order(
            base["customer"]["id"], base["principal"]["id"], "PO-1",
            lines=[
                make_order_line("L1", "CONNECTORS", 100, 5000),
                make_order_line("L2", "CABLES", 50, 2000),
            ],
        )
        _s, split_meta = validate_paginated(
            api.list_order_splits(_admin(), params={"order_id": invoiced["id"]})
        )
        assert split_meta["total_count"] == 4, "2 lines x SPECIFY/SHIP_TO rows"

        r1_entries = list_entries(rep_id=r1["id"])
        assert len(r1_entries) == 1
        assert r1_entries[0]["type"] == "ACCRUAL"
        assert r1_entries[0]["amount_cents"] == 34800

        order_entries = list_entries(order_id=invoiced["id"])
        assert len(order_entries) == 2
        by_rep = {e["rep_id"]: e["amount_cents"] for e in order_entries}
        assert by_rep == {r1["id"]: 34800, r2["id"]: 23200}

    def test_immediate_consistency_invoice_then_read(self, api):
        """PRD §3.5: "For each pairing of rep and order, one `ACCRUAL` ledger entry
        posts the sum of that rep's per-line shares, with its `business_date` taken
        from the order's `invoiced_at`." and "Invoicing closes with its bookkeeping:
        `invoiced_at` takes the clock, `fulfillment_status` moves to `INVOICED`,
        `commission_status` moves from `ATTRIBUTED` to `ACCRUED`". PRD §2.2: "Unless
        otherwise noted, operations that create or modify a resource will return the
        created or updated resource object in the data field." The mutation and its
        ledger effects are committed together, so a read in the same instant already
        shows them.

        Design: Corner/consistency_model/immediate_consistency_invoice_then_read
        """
        base = setup_base_scenario(agreement_territories=["CA", "OR", "WA"])
        r1 = base["reps"][0]
        order = create_order(
            base["customer"]["id"], base["principal"]["id"], "PO-1",
            lines=[
                make_order_line("L1", "CONNECTORS", 100, 5000),
                make_order_line("L2", "CABLES", 50, 2000),
            ],
        )
        ship_order(order["id"], base["principal"]["id"])
        invoiced = invoice_order(order["id"], base["principal"]["id"])

        assert invoiced["commission_status"] == "ACCRUED"
        assert order_line(invoiced, "L1")["applied_rate_bp"] == 1000
        assert order_line(invoiced, "L1")["commission_cents"] == 50000
        assert order_line(invoiced, "L2")["applied_rate_bp"] == 800
        assert order_line(invoiced, "L2")["commission_cents"] == 8000

        # Immediate ledger read (as read-only Auditor) shows both accrual entries.
        _entries, meta = validate_paginated(
            api.list_commission_entries(_auditor(), params={"order_id": order["id"]})
        )
        assert meta["total_count"] == 2
        rep = api.get_rep(r1["id"], _auditor()).json()["data"]
        assert rep["commission_balance_cents"] == 34800

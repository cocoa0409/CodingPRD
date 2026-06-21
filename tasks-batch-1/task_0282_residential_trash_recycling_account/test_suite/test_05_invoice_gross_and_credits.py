"""Invoice gross calculation, credit application, void/restore, and conserved-quantity
invariants. Covers difficulty rules dual_variant_calc, combinatorial_formula,
transitive_cascade (void branch), and compensating_invariant (credit branch).
"""
from test_helpers import (
    validate_success, get_success_data, api_client,
    TEST_USERS, make_account_holder_headers,
    setup_account_with_missed_trash_credit,
    setup_account_with_scheduled_extra_pickup,
    create_active_account, create_plan, create_zone, set_clock,
    create_account, add_standard_carts, account_version,
    generate_invoice_payload,
)

DISP = TEST_USERS["dispatcher_headers"]
CREW = TEST_USERS["crew_lead_headers"]

PERIOD = dict(period_start="2026-03-01T00:00:00Z",
              period_end="2026-04-01T00:00:00Z",
              due_date="2026-04-15T00:00:00Z")


class TestProvisionalVoidRebill:
    def test_provisional_invoice_consumes_credit_at_generation(self, api):
        """PRD §3.11: "The amount applied is the smaller of the gross and the account's
        current credit_balance_cents." PRD §3.11: "the amount due (amount_due_cents)
        is the gross minus the credit applied, floored at zero so it never goes negative."

        Design: Difficulty/dual_variant_calc/invoice_gross_provisional_then_void_restore_rebill
        """
        s = setup_account_with_missed_trash_credit(clock="2026-03-02T00:00:00Z")
        acct = s["account"]
        v1 = account_version(acct["id"])
        inv1 = validate_success(api.generate_invoice(
            acct["id"], generate_invoice_payload(v1, **PERIOD), DISP), 201)
        assert inv1["gross_amount_cents"] == 4000, "base only, two provisioned carts"
        assert inv1["credit_applied_cents"] == 300, "the single ISSUED 300 credit consumed"
        assert inv1["amount_due_cents"] == 3700

    def test_void_restores_credit_and_rebill_reapplies(self, api):
        """PRD §3.12: "Voiding restores any MissedPickupCredit this invoice had consumed
        back to ISSUED — re-pointing each such credit's applied_invoice_id to null — so
        the account's credit_balance_cents is conserved across the void."
        PRD §3.11: "voiding releases the credit it had consumed back to ISSUED, so
        re-billing the same account for the same period can yield a different
        amount_due_cents if credits or contamination changed in between."

        Design: Difficulty/dual_variant_calc/invoice_gross_provisional_then_void_restore_rebill
        """
        s = setup_account_with_missed_trash_credit(clock="2026-03-02T00:00:00Z")
        acct = s["account"]
        cr_id = s["credit"]["id"]

        v1 = account_version(acct["id"])
        inv1 = validate_success(api.generate_invoice(
            acct["id"], generate_invoice_payload(v1, **PERIOD), DISP), 201)
        validate_success(api.void_invoice(inv1["id"], DISP), 200)

        credit = validate_success(api.get_credit(cr_id, DISP), 200)
        assert credit["status"] == "ISSUED", "void restores the consumed credit to ISSUED"
        assert credit["applied_invoice_id"] is None

        v2 = account_version(acct["id"])
        inv2 = validate_success(api.generate_invoice(
            acct["id"], generate_invoice_payload(v2, **PERIOD), DISP), 201)
        assert inv2["credit_applied_cents"] == 300
        assert inv2["amount_due_cents"] == 3700


class TestVoidConservesCreditBalance:
    def test_credit_balance_300_then_0_then_300(self, api):
        """PRD §3.12: "Voiding restores any MissedPickupCredit this invoice had consumed
        back to ISSUED — re-pointing each such credit's applied_invoice_id to null — so
        the account's credit_balance_cents is conserved across the void."
        PRD §3.2: "The credit balance is the sum of amount_cents over every
        MissedPickupCredit on the account still in ISSUED status."

        Design: Difficulty/compensating_invariant/void_conserves_credit_balance
        """
        s = setup_account_with_missed_trash_credit(clock="2026-03-02T00:00:00Z")
        acct = s["account"]

        before = validate_success(api.get_account(acct["id"], DISP), 200)
        assert before["credit_balance_cents"] == 300

        v = account_version(acct["id"])
        inv = validate_success(api.generate_invoice(
            acct["id"], generate_invoice_payload(v, **PERIOD), DISP), 201)
        mid = validate_success(api.get_account(acct["id"], DISP), 200)
        assert mid["credit_balance_cents"] == 0, "credit consumed at generation"

        validate_success(api.void_invoice(inv["id"], DISP), 200)
        after = validate_success(api.get_account(acct["id"], DISP), 200)
        assert after["credit_balance_cents"] == 300, "void conserves the credit balance"

    def test_void_restores_credit_balance_invariant_explicit(self, api):
        """PRD §3.12: "so the account's credit_balance_cents is conserved across the void."

        Design: Difficulty/compensating_invariant/void_conserves_credit_balance
        """
        s = setup_account_with_missed_trash_credit(clock="2026-03-02T00:00:00Z")
        acct = s["account"]
        v = account_version(acct["id"])
        inv = validate_success(api.generate_invoice(
            acct["id"], generate_invoice_payload(v, **PERIOD), DISP), 201)
        validate_success(api.void_invoice(inv["id"], DISP), 200)
        after = validate_success(api.get_account(acct["id"], DISP), 200)
        assert after["credit_balance_cents"] == 300


class TestPinnedOrderGross:
    def test_gross_base_plus_extra_cart_plus_extras_minus_credit(self, api):
        """PRD §3.11: "Part one is the plan's monthly_base_cents." PRD §3.11: "Part two
        is the extra-cart surcharge: take the count of ACTIVE carts on the account,
        subtract the two carts every plan provisions (one TRASH plus one RECYCLING),
        floor that difference at zero, and multiply by the plan's extra_cart_monthly_cents."
        PRD §3.11: "Part three is the sum of charge_cents over every ExtraPickupRequest
        on the account whose status is SCHEDULED or COMPLETED and whose requested_date
        falls on or after period_start and strictly before period_end."

        Design: Difficulty/combinatorial_formula/invoice_gross_pinned_order_subtotal_then_credit_application
        """
        plan = create_plan()
        zone = create_zone()
        set_clock("2026-03-02T00:00:00Z")
        acct = create_account(plan["id"], zone["id"], address="16 Oak St")
        # three carts -> one extra
        get_success_data(api.create_cart(acct["id"], {"cart_type": "TRASH", "size_gallons": 65}, DISP))
        get_success_data(api.create_cart(acct["id"], {"cart_type": "RECYCLING", "size_gallons": 65}, DISP))
        get_success_data(api.create_cart(acct["id"], {"cart_type": "TRASH", "size_gallons": 35}, DISP))
        acct = get_success_data(api.activate_start(acct["id"], DISP))

        # a missed TRASH pickup -> 300 credit
        rows = get_success_data(api.list_pickup_schedules(acct["id"], DISP, {"stream": "TRASH"}))
        s0 = rows[0]
        get_success_data(api.report_event(
            s0["id"], {"outcome": "MISSED", "reported_at": s0["effective_pickup_date"]}, CREW))

        # one SCHEDULED extra pickup of 3 items in March -> charge 3300
        holder = make_account_holder_headers(acct["id"])
        req = get_success_data(api.create_extra_pickup(
            acct["id"], {"requested_date": "2026-03-22T00:00:00Z", "bulk_item_count": 3}, holder))
        get_success_data(api.schedule_extra_pickup(req["id"], DISP))

        v = account_version(acct["id"])
        inv = validate_success(api.generate_invoice(
            acct["id"], generate_invoice_payload(v, **PERIOD), DISP), 201)
        assert inv["gross_amount_cents"] == 8500, "4000 base + 1200 extra-cart + 3300 extra-pickup"
        assert inv["credit_applied_cents"] == 300
        assert inv["amount_due_cents"] == 8200

    def test_amount_due_is_gross_minus_credit_floored(self, api):
        """PRD §3.11: "the amount due (amount_due_cents) is the gross minus the credit
        applied, floored at zero so it never goes negative."

        Design: Difficulty/combinatorial_formula/invoice_gross_pinned_order_subtotal_then_credit_application
        """
        s = setup_account_with_missed_trash_credit(clock="2026-03-02T00:00:00Z")
        acct = s["account"]
        v = account_version(acct["id"])
        inv = validate_success(api.generate_invoice(
            acct["id"], generate_invoice_payload(v, **PERIOD), DISP), 201)
        assert inv["amount_due_cents"] == inv["gross_amount_cents"] - inv["credit_applied_cents"]


class TestMissedCreditConsumeRestoreCascade:
    def test_missed_to_credit_to_applied_to_restored(self, api):
        """PRD §3.8: "When a pickup is reported missed, the system issues a missed-pickup
        credit on the account, in ISSUED status, linking back to the originating event
        through its pickup_event_id."
        PRD §3.11: "marking each consumed credit APPLIED and setting its applied_invoice_id
        to this invoice, until the applied total reaches the computed amount."
        PRD §3.12: "Voiding restores any MissedPickupCredit this invoice had consumed back
        to ISSUED — re-pointing each such credit's applied_invoice_id to null."

        Design: Difficulty/transitive_cascade/missed_event_credits_then_invoice_consumes_then_void_restores
        """
        s = setup_account_with_missed_trash_credit(clock="2026-03-02T00:00:00Z")
        acct = s["account"]
        cr_id = s["credit"]["id"]
        assert s["credit"]["status"] == "ISSUED"

        v = account_version(acct["id"])
        inv = validate_success(api.generate_invoice(
            acct["id"], generate_invoice_payload(v, **PERIOD), DISP), 201)

        applied = validate_success(api.get_credit(cr_id, DISP), 200)
        assert applied["status"] == "APPLIED"
        assert applied["applied_invoice_id"] == inv["id"]

        validate_success(api.void_invoice(inv["id"], DISP), 200)
        restored = validate_success(api.get_credit(cr_id, DISP), 200)
        assert restored["status"] == "ISSUED"
        assert restored["applied_invoice_id"] is None

    def test_missed_event_issues_issued_credit_first_hop(self, api):
        """PRD §3.8: "When a pickup is reported missed, the system issues a missed-pickup
        credit on the account, in ISSUED status, linking back to the originating event
        through its pickup_event_id and recording the account_id it benefits."

        Design: Difficulty/transitive_cascade/missed_event_credits_then_invoice_consumes_then_void_restores
        """
        s = setup_account_with_missed_trash_credit(clock="2026-03-02T00:00:00Z")
        credit = s["credit"]
        assert credit["status"] == "ISSUED"
        assert credit["pickup_event_id"] == s["event"]["id"]
        assert credit["account_id"] == s["account"]["id"]

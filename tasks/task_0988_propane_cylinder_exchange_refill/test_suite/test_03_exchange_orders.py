"""Exchange counter: swap pricing, completion, selector, refunds, idempotency (PRD §3.3)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    advance_clock,
    assert_exchange_order,
    close_ticket,
    complete_order,
    confirm_leak,
    create_order,
    create_priced_site,
    create_site,
    create_technician,
    create_ticket,
    fill_ticket,
    get_site,
    make_technician_headers,
    open_session,
    count_session,
    record_certification,
    weigh_ticket,
    register_customer_cylinder,
    register_fleet_cylinders,
    report_leak,
    resolve_leak,
    setup_single_swap_day,
    swap_completed,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK1 = TEST_USERS["site_clerk_headers"]
OFFICER1 = TEST_USERS["compliance_officer_headers"]


class TestSwapCharge:
    def test_swap_with_return_zeroes_deposit(self, api):
        """PRD §3.3: "`core_deposit_cents` is zero when the customer hands over a cylinder and the policy's `core_deposit_cents` otherwise; `tax_cents` is the subtotal — unit price plus core deposit — multiplied by the policy's `tax_rate_bps` and divided by ten thousand, rounded half-up once to whole cents; and `total_cents` is the subtotal plus the tax."

        Design: Difficulty/combinatorial_formula/swap_charge_conditional_deposit_and_tax
        """
        site, _policy = create_priced_site()
        register_fleet_cylinders(site_id=site["id"], count=2, fill="FULL", serial_prefix="FS")
        customer = register_customer_cylinder(fill="EMPTY")
        order = create_order(site["id"], CLERK1, returned_cylinder_id=customer["id"])
        assert_exchange_order(order)
        assert order["status"] == "DRAFT"
        assert order["unit_price_cents"] == 2499
        assert order["core_deposit_cents"] == 0
        assert order["tax_cents"] == 206, "round_half_up(2499 * 825 / 10000)"
        assert order["total_cents"] == 2705

    def test_swap_without_return_charges_deposit_and_tax_on_it(self, api):
        """PRD §3.3: "`core_deposit_cents` is zero when the customer hands over a cylinder and the policy's `core_deposit_cents` otherwise; `tax_cents` is the subtotal — unit price plus core deposit — multiplied by the policy's `tax_rate_bps` and divided by ten thousand, rounded half-up once to whole cents; and `total_cents` is the subtotal plus the tax."

        Design: Difficulty/combinatorial_formula/swap_charge_conditional_deposit_and_tax
        """
        site, _policy = create_priced_site()
        register_fleet_cylinders(site_id=site["id"], count=1, fill="FULL", serial_prefix="FS")
        order = create_order(site["id"], CLERK1)
        assert order["core_deposit_cents"] == 3500
        # subtotal 2499 + 3500 = 5999; tax = round_half_up(5999 * 825 / 10000) = 495
        assert order["tax_cents"] == 495
        assert order["total_cents"] == 6494


class TestCompletion:
    def test_complete_response_immediately_consistent(self, api):
        """PRD §3.3: "The order's `business_date` and `sale_seq` are stamped per §2.9, `change_due_cents` is computed as the tendered cash minus `total_cents`, the order lands in `COMPLETED`, and the site's open reconciliation session, if one exists for the current date, has its `expected_cash_cents` recomputed to include the order's `total_cents` as a cash addition."
        PRD §3.3: "its `current_site_id` is cleared to null — it is with the customer — so the site's `full_on_hand` drops by one."

        Design: Corner/endpoints/complete_response_immediately_consistent
        """
        site, _policy = create_priced_site()
        full = register_fleet_cylinders(site_id=site["id"], count=1, fill="FULL",
                                        serial_prefix="IC")[0]
        order = create_order(site["id"], CLERK1)
        completed = complete_order(order["id"], CLERK1, payment_cash_cents=7000)
        assert completed["status"] == "COMPLETED"
        assert completed["issued_cylinder_id"] == full["id"]
        assert completed["change_due_cents"] == 506, "7000 - 6494"
        assert completed["business_date"] == "2026-05-01"
        assert completed["sale_seq"] == 1
        assert get_site(site["id"])["full_on_hand"] == 0

    def test_double_complete_returns_invalid_state(self, api):
        """PRD §2.7 (stage 6): "The target resource is in a valid from-state for the requested transition, terminal states are locked against further action, the site is `ACTIVE` for sales and dispatch (`ERR_SITE_NOT_ACTIVE`), and a driver's arrival date matches the run's planned date; otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/double_complete_returns_invalid_state
        """
        site, _policy = create_priced_site()
        register_fleet_cylinders(site_id=site["id"], count=1, fill="FULL", serial_prefix="DC")
        order = create_order(site["id"], CLERK1)
        complete_order(order["id"], CLERK1, payment_cash_cents=6494)
        res = api.complete_exchange_order(order["id"], {"payment_cash_cents": 6494}, CLERK1)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_complete_voided_order_state_beats_fiscal(self, api):
        """PRD §2.7: "Incoming requests are validated against a fixed, fourteen-stage evaluation order; the first stage that fails determines the rejection, and later stages are not consulted."
        PRD §2.7 (stage 6): "The target resource is in a valid from-state for the requested transition, terminal states are locked against further action, the site is `ACTIVE` for sales and dispatch (`ERR_SITE_NOT_ACTIVE`), and a driver's arrival date matches the run's planned date; otherwise `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/complete_voided_order_state_beats_fiscal
        """
        site, _policy = create_priced_site()
        register_fleet_cylinders(site_id=site["id"], count=1, fill="FULL", serial_prefix="PV")
        order = create_order(site["id"], CLERK1)
        validate_success(api.void_exchange_order(order["id"], CLERK1), 200)
        # Payment 1 < total 6494 would fail stage 13, but the VOIDED state fails stage 6 first.
        res = api.complete_exchange_order(order["id"], {"payment_cash_cents": 1}, CLERK1)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_complete_draft_with_insufficient_payment(self, api):
        """PRD §3.3: "The clerk tenders `payment_cash_cents`, which must equal or exceed `total_cents`, else the completion is rejected with `ERR_INSUFFICIENT_PAYMENT`."
        The order is in a valid from-state (DRAFT), so the stage-13 payment check is the one that fires.

        Design: Difficulty/priority_pair_validation_conflict/complete_voided_order_state_beats_fiscal
        """
        site, _policy = create_priced_site()
        register_fleet_cylinders(site_id=site["id"], count=1, fill="FULL", serial_prefix="PI")
        order = create_order(site["id"], CLERK1)
        assert order["total_cents"] == 6494
        res = api.complete_exchange_order(order["id"], {"payment_cash_cents": 6493}, CLERK1)
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PAYMENT, expected_status=402)


class TestSelector:
    def test_selector_issues_oldest_certified_first(self, api):
        """PRD §3.3: "candidates are fleet-owned, `CERTIFIED`, `FULL` cylinders physically at the order's site and not in transit; they are ranked by `certified_on` ascending — oldest-certified first — with ties broken by `created_at` ascending; and the first candidate is issued."

        Design: Corner/calculations/selector_issues_oldest_certified_first
        """
        site, _policy = create_priced_site()
        register_fleet_cylinders(site_id=site["id"], count=1, fill="FULL",
                                 manufacture_date="2021-03-10", serial_prefix="NEW")
        older = register_fleet_cylinders(site_id=site["id"], count=1, fill="FULL",
                                         manufacture_date="2019-06-01", serial_prefix="OLD")[0]
        order = create_order(site["id"], CLERK1)
        completed = complete_order(order["id"], CLERK1, payment_cash_cents=6494)
        assert completed["issued_cylinder_id"] == older["id"], (
            "oldest certified_on first, even though the newer cylinder was registered first"
        )

    def test_selector_empty_pool_returns_no_stock(self, api):
        """PRD §3.3: "An empty candidate set rejects the completion with `ERR_NO_STOCK`."
        PRD §3.3: "Because the selector requires `CERTIFIED` while the cage count of §2.8 merely excludes the condemned, a cage can report stock on hand yet be unable to sell — `RECERT_DUE` cylinders are visible in `full_on_hand` but invisible to the selector."

        Design: Corner/calculations/selector_empty_pool_returns_no_stock
        """
        site, _policy = create_priced_site()
        register_fleet_cylinders(site_id=site["id"], count=1, fill="FULL",
                                 manufacture_date="2014-06-01", serial_prefix="NS")
        order = create_order(site["id"], CLERK1)
        advance_clock("2026-06-02T00:00:00Z")  # cylinder flips to RECERT_DUE
        res = api.complete_exchange_order(order["id"], {"payment_cash_cents": 6494}, CLERK1)
        validate_error(res, ApiErrorId.ERR_NO_STOCK, expected_status=409)


class TestCreationGates:
    def test_exchange_create_bogus_return_reference(self, api):
        """PRD §3.3: "if a returned cylinder is offered it must exist (else `ERR_REFERENCE_NOT_FOUND`) and must not be condemned (else `ERR_CYLINDER_CONDEMNED`)."

        Design: Corner/validations/exchange_create_bogus_return_reference
        """
        site, _policy = create_priced_site()
        res = api.create_exchange_order(
            {"site_id": site["id"], "returned_cylinder_id": NON_EXISTENT_UUID}, CLERK1)
        validate_error(res, ApiErrorId.ERR_REFERENCE_NOT_FOUND, expected_status=422)

    def test_exchange_without_policy_rejected(self, api):
        """PRD §3.1: "Whenever a site has no current policy at the present logical date, sales at that site are refused with `ERR_NO_ACTIVE_POLICY`."

        Design: Corner/validations/exchange_without_policy_rejected
        """
        # site with stock but NO pricing policy
        site = create_site(name="No Policy Site")
        register_fleet_cylinders(site_id=site["id"], count=1, fill="FULL", serial_prefix="NP")
        res = api.create_exchange_order({"site_id": site["id"]}, CLERK1)
        validate_error(res, ApiErrorId.ERR_NO_ACTIVE_POLICY, expected_status=409)

    def test_exchange_create_blocked_by_leak_posture(self, api):
        """PRD §3.3: "Creation is gated by the site's operating posture: the site must be `ACTIVE` (else `ERR_SITE_NOT_ACTIVE`), its `sales_posture` must be `SALES_OPEN` (else `ERR_SALES_BLOCKED`), a current pricing policy must exist (else `ERR_NO_ACTIVE_POLICY`)"
        PRD §2.8: "`sales_posture` is `SALES_BLOCKED` whenever the site has a leak report in `CONFIRMED` status whose `severity` is `MAJOR` or whose `quarantine_cage` flag is true, and `SALES_OPEN` otherwise; a blocked posture refuses new sales with `ERR_SALES_BLOCKED`."

        Design: Difficulty/cross_entity_state_dependency/exchange_create_blocked_by_leak_posture
        """
        site, _policy = create_priced_site()
        register_fleet_cylinders(site_id=site["id"], count=1, fill="FULL", serial_prefix="FG")
        leak = report_leak(site["id"], CLERK1, severity="MINOR", quarantine_cage=True)
        confirm_leak(leak["id"], OFFICER1)
        assert get_site(site["id"])["sales_posture"] == "SALES_BLOCKED"
        res = api.create_exchange_order({"site_id": site["id"]}, CLERK1)
        validate_error(res, ApiErrorId.ERR_SALES_BLOCKED, expected_status=409)

    def test_exchange_create_succeeds_after_leak_resolved(self, api):
        """PRD §3.5: "A successful resolution stamps `resolved_by` and the supplied `resolution_note`, moves the report to `RESOLVED`, and recomputes the site's `sales_posture` — which returns to `SALES_OPEN` when no other confirmed quarantining leak remains."

        Design: Difficulty/cross_entity_state_dependency/exchange_create_blocked_by_leak_posture
        """
        site, _policy = create_priced_site()
        full = register_fleet_cylinders(site_id=site["id"], count=1, fill="FULL",
                                        serial_prefix="FR")[0]
        tech = create_technician(cert_level="VISUAL_ONLY", name="Tech R")
        leak = report_leak(site["id"], CLERK1, severity="MINOR", quarantine_cage=True)
        confirm_leak(leak["id"], OFFICER1)
        assert get_site(site["id"])["sales_posture"] == "SALES_BLOCKED"
        # Post-confirmation re-inspection evidence on a site fleet cylinder.
        record_certification(full["id"], tech, method="VISUAL", outcome="PASS",
                             note="post-leak re-inspection")
        resolved = resolve_leak(leak["id"], "cage re-inspected, valve replaced", OFFICER1)
        assert resolved["status"] == "RESOLVED"
        assert get_site(site["id"])["sales_posture"] == "SALES_OPEN"
        order = create_order(site["id"], CLERK1)
        assert order["status"] == "DRAFT"


class TestRefund:
    def test_refunded_order_terminal_lockdown(self, api):
        """PRD §3.3: "either violation is rejected with `ERR_REFUND_WINDOW_CLOSED`, as is any refund attempt on an order not in `COMPLETED` (via `ERR_INVALID_STATE`)."

        Design: Corner/state_machines/refunded_order_terminal_lockdown
        """
        site, _policy = create_priced_site()
        register_fleet_cylinders(site_id=site["id"], count=1, fill="FULL", serial_prefix="TL")
        order = create_order(site["id"], CLERK1)
        complete_order(order["id"], CLERK1, payment_cash_cents=6494)
        refunded = validate_success(api.refund_exchange_order(order["id"], CLERK1), 200)
        assert refunded["status"] == "REFUNDED"
        res = api.refund_exchange_order(order["id"], CLERK1)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_refund_after_session_balanced_rejected(self, api):
        """PRD §3.3: "the order's `business_date` must equal the current logical date, and the site's reconciliation session for today, if one exists, must still be in `OPEN` or `VARIANCE_FLAGGED`; either violation is rejected with `ERR_REFUND_WINDOW_CLOSED`"

        Design: Corner/validations/refund_after_session_balanced_rejected
        """
        site, _customer, order = setup_single_swap_day()
        session = open_session(site["id"], "2026-05-01", CLERK1)
        counted = count_session(session["id"], 22705, 0, 1, CLERK1)
        assert counted["status"] == "BALANCED"
        res = api.refund_exchange_order(order["id"], CLERK1)
        validate_error(res, ApiErrorId.ERR_REFUND_WINDOW_CLOSED, expected_status=409)

    def test_refund_side_effects_immediately_visible(self, api):
        """PRD §3.3: "A refund stamps `refunded_on` with the current date, moves the order to `REFUNDED`, and sends the issued cylinder back to the site in `fill_status` `QUARANTINED` pending returned-goods inspection — the site's counts and `restock_alert` recompute accordingly"

        Design: Corner/consistency_model/refund_side_effects_immediately_visible
        """
        site, _policy = create_priced_site()
        full = register_fleet_cylinders(site_id=site["id"], count=1, fill="FULL",
                                        serial_prefix="RV")[0]
        order = create_order(site["id"], CLERK1)
        complete_order(order["id"], CLERK1, payment_cash_cents=6494)
        refunded = validate_success(api.refund_exchange_order(order["id"], CLERK1), 200)
        assert refunded["status"] == "REFUNDED"
        assert refunded["refunded_on"] == "2026-05-01"
        cyl = validate_success(api.get_cylinder(full["id"], ADMIN), 200)
        assert cyl["fill_status"] == "QUARANTINED"
        assert cyl["current_site_id"] == site["id"]
        assert get_site(site["id"])["quarantined_on_hand"] == 1


class TestIdempotency:
    def test_idempotent_exchange_create_replay(self, api):
        """PRD §2.9: "Two intake endpoints accept a client-supplied `idempotency_key`: exchange order creation and reconciliation session creation. The key is unique per clerk. Replaying a key with the identical payload returns the original resource without creating a duplicate; reusing the same key with a different payload is rejected with `ERR_IDEMPOTENCY_CONFLICT`."

        Design: Corner/cross_cutting_layers/idempotent_exchange_create_replay
        """
        site, _policy = create_priced_site()
        register_fleet_cylinders(site_id=site["id"], count=2, fill="FULL", serial_prefix="I")
        customer = register_customer_cylinder(fill="EMPTY")
        first = create_order(site["id"], CLERK1, idempotency_key="K-1")
        replay = create_order(site["id"], CLERK1, idempotency_key="K-1")
        assert replay["id"] == first["id"], "replay returns the original order"
        res = api.create_exchange_order(
            {"site_id": site["id"], "returned_cylinder_id": customer["id"],
             "idempotency_key": "K-1"},
            CLERK1,
        )
        validate_error(res, ApiErrorId.ERR_IDEMPOTENCY_CONFLICT, expected_status=409)


class TestCompensatingInvariants:
    def test_swap_with_return_conserves_site_population(self, api):
        """PRD §3.3: "the issued cylinder's `id` is recorded as `issued_cylinder_id` and its `current_site_id` is cleared to null — it is with the customer — so the site's `full_on_hand` drops by one. If a `returned_cylinder_id` was supplied, that cylinder is absorbed into the fleet: its `owner_kind` becomes `FLEET`, its `current_site_id` becomes the order's site, its `fill_status` is `EMPTY`, and the site's `empty_on_hand` rises by one."

        Design: Difficulty/compensating_invariant/swap_with_return_conserves_site_population
        """
        site, _policy = create_priced_site()
        register_fleet_cylinders(site_id=site["id"], count=8, fill="FULL", serial_prefix="FI")
        register_fleet_cylinders(site_id=site["id"], count=3, fill="EMPTY", serial_prefix="FI")
        customer = register_customer_cylinder(fill="EMPTY")
        before = get_site(site["id"])
        assert (before["full_on_hand"], before["empty_on_hand"],
                before["quarantined_on_hand"]) == (8, 3, 0)
        order = create_order(site["id"], CLERK1, returned_cylinder_id=customer["id"])
        complete_order(order["id"], CLERK1)
        after = get_site(site["id"])
        assert (after["full_on_hand"], after["empty_on_hand"],
                after["quarantined_on_hand"]) == (7, 4, 0)
        pre_total = before["full_on_hand"] + before["empty_on_hand"] + before["quarantined_on_hand"]
        post_total = after["full_on_hand"] + after["empty_on_hand"] + after["quarantined_on_hand"]
        assert pre_total == post_total == 11, "site cylinder population is conserved"

    def test_swap_without_return_shrinks_population_by_one(self, api):
        """PRD §3.3: "its `current_site_id` is cleared to null — it is with the customer — so the site's `full_on_hand` drops by one."
        With no returned cylinder nothing is absorbed, so the site's population drops by the issued unit.

        Design: Difficulty/compensating_invariant/swap_with_return_conserves_site_population
        """
        site, _policy = create_priced_site()
        register_fleet_cylinders(site_id=site["id"], count=1, fill="FULL", serial_prefix="FJ")
        order = create_order(site["id"], CLERK1)
        complete_order(order["id"], CLERK1)
        after = get_site(site["id"])
        assert after["full_on_hand"] == 0
        assert after["empty_on_hand"] == 0
        assert after["quarantined_on_hand"] == 0

    def test_complete_then_refund_conserves_expected_cash(self, api):
        """PRD §3.3: "the site's open reconciliation session, if one exists for the current date, has its `expected_cash_cents` recomputed to include the order's `total_cents` as a cash addition."
        PRD §3.3: "the day's open reconciliation session recomputes `expected_cash_cents` to include the order's `total_cents` as a cash subtraction."

        Design: Difficulty/compensating_invariant/complete_then_refund_conserves_expected_cash
        """
        site, _policy = create_priced_site()
        register_fleet_cylinders(site_id=site["id"], count=1, fill="FULL", serial_prefix="FC")
        customer = register_customer_cylinder(fill="EMPTY")
        session = open_session(site["id"], "2026-05-01", CLERK1)
        assert session["expected_cash_cents"] == 20000, "float snapshot before any sale"

        order = create_order(site["id"], CLERK1, returned_cylinder_id=customer["id"])
        complete_order(order["id"], CLERK1)  # total 2705
        mid = validate_success(api.get_reconciliation_session(session["id"], ADMIN), 200)
        assert mid["expected_cash_cents"] == 22705, "20000 + 2705"

        validate_success(api.refund_exchange_order(order["id"], CLERK1), 200)
        post = validate_success(api.get_reconciliation_session(session["id"], ADMIN), 200)
        assert post["expected_cash_cents"] == 20000, (
            "complete + compensating refund net to zero drift from the creation snapshot"
        )

    def test_refill_close_adds_total_to_expected_cash(self, api):
        """PRD §3.4: "the site's open reconciliation session for the current date, if one exists, recomputes `expected_cash_cents` to include the ticket's `total_cents` as a cash addition."

        Design: Difficulty/compensating_invariant/complete_then_refund_conserves_expected_cash
        """
        site, _policy = create_priced_site()
        customer = register_customer_cylinder(fill="EMPTY")
        session = open_session(site["id"], "2026-05-01", CLERK1)
        assert session["expected_cash_cents"] == 20000
        ticket = create_ticket(site["id"], customer["id"], CLERK1, pre_weight_lbs=17.00)
        weigh_ticket(ticket["id"], 17.00, CLERK1)
        filled = fill_ticket(ticket["id"], 35.50, CLERK1)  # 18.50 lbs -> charge 6282
        assert filled["total_cents"] == 6282
        close_ticket(filled["id"], 6282, CLERK1)
        post = validate_success(api.get_reconciliation_session(session["id"], ADMIN), 200)
        assert post["expected_cash_cents"] == 26282, "20000 + 6282"

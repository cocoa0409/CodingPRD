"""Reservation gauntlet: copy-window overlap, rentability, ledger visibility."""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_copy_pool_invariant,
    assert_rental_set,
    cancel_order,
    confirm_order,
    create_account,
    create_order,
    create_publisher,
    create_rental_set,
    create_work,
    dispatch_order,
    fetch_order,
    fetch_set,
    get_success_data,
    order_lines,
    renew_order,
    reserve_order,
    setup_order_on_loan,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ADMIN, BILLING, CLERK


class TestHalfOpenCopyWindows:
    def _setup_one_copy_set(self):
        publisher = create_publisher("Pub Fifteen")
        work = create_work(publisher["id"], title="Solo Pieces",
                           catalog_number="P15-001")
        rental_set = create_rental_set(work["id"], set_code="SET-1301", copy_count=1,
                                       replacement_value_cents=8000)
        account = create_account("Elm HS", credit_tier="STANDARD", credit_limit_cents=0)
        advance_clock()
        return account, rental_set

    def test_adjacent_windows_do_not_overlap(self, api):
        """PRD §2.10: "Two windows that merely touch — one loan's `due_date` equal
        to another's `checkout_date`, or vice versa — do not overlap, so
        back-to-back bookings of the same copy are permitted."

        Design: Difficulty/resource_temporal_overlap/rental_copy_half_open_adjacency
        """
        account, rental_set = self._setup_one_copy_set()
        first = create_order(account["id"], rental_set["id"], copies=1,
                             checkout_date="2026-08-05", due_date="2026-09-04")
        reserve_order(first["id"])
        second = create_order(account["id"], rental_set["id"], copies=1,
                              checkout_date="2026-09-04", due_date="2026-10-04")

        reserved = validate_success(api.reserve_rental_order(second["id"], CLERK))
        assert reserved["status"] == "RESERVED", (
            "a checkout exactly at the prior loan's due_date touches the window "
            "boundary and must be allocatable"
        )

    def test_one_day_overlap_rejected(self, api):
        """PRD §3.5: "The requested window must leave at least `copies_requested`
        allocatable copies on the set: `copy_count` minus the copies held by lines
        in `RESERVED`, `DISPATCHED`, `ON_LOAN`, or `OVERDUE` whose own windows
        overlap the request under the half-open rule of §2.10 — a shortfall is
        `ERR_INSUFFICIENT_COPIES`."

        Design: Difficulty/resource_temporal_overlap/rental_copy_half_open_adjacency
        """
        account, rental_set = self._setup_one_copy_set()
        first = create_order(account["id"], rental_set["id"], copies=1,
                             checkout_date="2026-08-05", due_date="2026-09-04")
        reserve_order(first["id"])
        overlapping = create_order(account["id"], rental_set["id"], copies=1,
                                   checkout_date="2026-09-03", due_date="2026-10-03")

        resp = api.reserve_rental_order(overlapping["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_COPIES)

    def test_zero_copy_pool_boundary_on_overlap(self, api):
        """PRD §3.5: "a shortfall is `ERR_INSUFFICIENT_COPIES`".
        PRD §2.10: "Two windows that merely touch — one loan's `due_date` equal
        to another's `checkout_date`, or vice versa — do not overlap, so
        back-to-back bookings of the same copy are permitted."

        Design: Corner/validations/zero_copy_pool_boundary_on_overlap
        """
        publisher = create_publisher("Pub Twelve")
        work = create_work(publisher["id"], title="Nocturne", catalog_number="P12-001")
        rental_set = create_rental_set(work["id"], set_code="SET-1001", copy_count=2,
                                       replacement_value_cents=16000)
        account = create_account("Lake MS", credit_tier="STANDARD", credit_limit_cents=0)
        advance_clock()
        first = create_order(account["id"], rental_set["id"], copies=2,
                             checkout_date="2026-08-05", due_date="2026-09-04")
        reserve_order(first["id"])
        overlapping = create_order(account["id"], rental_set["id"], copies=1,
                                   checkout_date="2026-08-20", due_date="2026-09-19")
        adjacent = create_order(account["id"], rental_set["id"], copies=2,
                                checkout_date="2026-09-04", due_date="2026-10-04")

        # The two-copy booking leaves zero allocatable copies inside its window.
        resp = api.reserve_rental_order(overlapping["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_COPIES)
        # Touching at the exact due_date is not an overlap: the pool is free there.
        adjacent_reserved = validate_success(
            api.reserve_rental_order(adjacent["id"], CLERK)
        )
        assert adjacent_reserved["status"] == "RESERVED"


class TestCopyPoolConservation:
    def _setup_thirty_copy_set(self):
        publisher = create_publisher("Pub Seventeen")
        work = create_work(publisher["id"], title="Trio", catalog_number="P17-001")
        rental_set = create_rental_set(work["id"], set_code="SET-1401", copy_count=30,
                                       replacement_value_cents=240000)
        account = create_account("Birch HS", credit_tier="STANDARD", credit_limit_cents=0)
        advance_clock()
        return account, rental_set

    def test_reserve_debits_available_copies(self, api):
        """PRD §3.2: "The availability ledger keeps `available_copy_count` equal to
        `copy_count` minus the copies held by rental lines in `RESERVED`,
        `DISPATCHED`, `ON_LOAN`, or `OVERDUE` status. Every allocation decrements
        it, every returned or released line restores one unit, and a lost line
        restores nothing — the copy never comes back."

        Design: Difficulty/compensating_invariant/copy_pool_conserved_across_reserve_and_cancel
        """
        account, rental_set = self._setup_thirty_copy_set()
        order = create_order(account["id"], rental_set["id"], copies=5,
                             checkout_date="2026-08-05", due_date="2026-09-04")
        reserve_order(order["id"])

        set_after = fetch_set(rental_set["id"])
        assert set_after["available_copy_count"] == 25, (
            f"reserving 5 of 30 must debit the pool to 25, got "
            f"{set_after['available_copy_count']}"
        )
        held = [line for line in order_lines(order["id"])
                if line["status"] in ("RESERVED", "DISPATCHED", "ON_LOAN", "OVERDUE")]
        assert_copy_pool_invariant(set_after, len(held))

    def test_cancel_restores_available_copies(self, api):
        """PRD §3.5: "cancellation by a `LibraryClerk` is permitted only from
        `DRAFT` or `RESERVED` — any other state is `ERR_ORDER_NOT_CANCELLABLE` —
        and runs a compensating cascade: any allocated lines move to `RELEASED`,
        each released line restores one unit of the set's `available_copy_count`".

        Design: Difficulty/compensating_invariant/copy_pool_conserved_across_reserve_and_cancel
        """
        account, rental_set = self._setup_thirty_copy_set()
        order = create_order(account["id"], rental_set["id"], copies=5,
                             checkout_date="2026-08-05", due_date="2026-09-04")
        reserve_order(order["id"])
        assert fetch_set(rental_set["id"])["available_copy_count"] == 25

        cancel_order(order["id"])

        set_after = fetch_set(rental_set["id"])
        assert set_after["available_copy_count"] == 30, (
            f"the compensating cascade must restore the pool exactly to 30, got "
            f"{set_after['available_copy_count']}"
        )
        lines = order_lines(order["id"])
        assert all(line["status"] == "RELEASED" for line in lines)
        assert_copy_pool_invariant(set_after, 0)


class TestRentabilityAndLicenseGates:
    def test_license_format_digital_rejected_on_print_only_work(self, api):
        """PRD §3.5: "`DIGITAL` fulfillment requires the work's `license_format`
        to be `DIGITAL_ONLY` or `PRINT_AND_DIGITAL` and the publisher's
        `print_only_rental` flag to be false, else
        `ERR_LICENSE_FORMAT_NOT_AVAILABLE` (HTTP 422)."

        Design: Corner/validations/license_format_digital_rejected_on_print_only_work
        """
        publisher = create_publisher("LF Pub")
        work = create_work(publisher["id"], title="LF Work", catalog_number="LF-1",
                           license_format="PRINT_ONLY")
        rental_set = create_rental_set(work["id"], set_code="LF-SET", copy_count=5,
                                       replacement_value_cents=40000)
        account = create_account("LF Acct", account_kind="INDIVIDUAL")
        advance_clock()
        order = create_order(account["id"], rental_set["id"], copies=1,
                             fulfillment_format="DIGITAL")

        resp = api.reserve_rental_order(order["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_LICENSE_FORMAT_NOT_AVAILABLE)

    def test_suspended_publisher_blocks_reserve(self, api):
        """PRD §3.5: "The work must be `CATALOGED` and its publisher `ACTIVE`
        (`ERR_WORK_NOT_RENTABLE`)."
        PRD §3.1: "suspension blocks all new rental, perusal, and purchase
        activity on its works."

        Design: Corner/validations/suspended_publisher_blocks_reserve
        """
        publisher = create_publisher("SP2 Pub")
        work = create_work(publisher["id"], title="SP2 Work", catalog_number="SP2-1")
        rental_set = create_rental_set(work["id"], set_code="SP2-SET", copy_count=5,
                                       replacement_value_cents=40000)
        account = create_account("SP2 Acct", account_kind="INDIVIDUAL")
        advance_clock()
        order = create_order(account["id"], rental_set["id"], copies=1)
        get_success_data(api.patch_publisher(publisher["id"], {"status": "SUSPENDED"}, ADMIN))

        resp = api.reserve_rental_order(order["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_WORK_NOT_RENTABLE)


class TestInvalidTransitions:
    def test_settle_from_on_loan_returns_invalid_state(self, api):
        """PRD §3.6: "Settlement — a `BillingManager` moving `RETURNED` →
        `SETTLED`".
        PRD §2.9: "state-transition admissibility, where the target must sit in a
        from-state permitting the requested transition, else `ERR_INVALID_STATE`".

        Design: Corner/state_machines/settle_from_on_loan_returns_invalid_state
        """
        ws = setup_order_on_loan(order_copies=1, publisher_name="IV Pub",
                                 work_title="IV Work", catalog_number="IV-1",
                                 set_code="IV-SET", replacement=40000,
                                 account_overrides={
                                     "account_name": "IV Acct",
                                     "account_kind": "INDIVIDUAL",
                                 })

        resp = api.settle_rental_order(ws["order"]["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert fetch_order(ws["order"]["id"])["status"] == "ON_LOAN"

    def test_terminal_state_lockdown_cancelled_order(self, api):
        """PRD §3.5: "The order's full status vocabulary is `DRAFT`, `RESERVED`,
        `DISPATCHED`, `ON_LOAN`, `OVERDUE`, `RETURNED`, `DISPUTED`, `SETTLED`, and
        `CANCELLED`, with `SETTLED` and `CANCELLED` terminal."
        PRD §3.5: "cancellation by a `LibraryClerk` is permitted only from `DRAFT`
        or `RESERVED` — any other state is `ERR_ORDER_NOT_CANCELLABLE`".

        Design: Corner/state_machines/terminal_state_lockdown_cancelled_order
        """
        publisher = create_publisher("TL Pub")
        work = create_work(publisher["id"], title="TL Work", catalog_number="TL-1")
        rental_set = create_rental_set(work["id"], set_code="TL-SET", copy_count=5,
                                       replacement_value_cents=40000)
        account = create_account("TL Acct", account_kind="INDIVIDUAL")
        advance_clock()
        order = create_order(account["id"], rental_set["id"], copies=1)
        cancel_order(order["id"])
        assert fetch_order(order["id"])["status"] == "CANCELLED"

        # A terminal order admits no further transitions.
        resp_reserve = api.reserve_rental_order(order["id"], CLERK)
        validate_error(resp_reserve, ApiErrorId.ERR_INVALID_STATE)
        resp_cancel = api.cancel_rental_order(order["id"], CLERK)
        validate_error(resp_cancel, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE)


class TestVersionAndVisibility:
    def test_version_increments_on_every_mutation(self, api):
        """PRD §2.4: "`version` (integer): a system-managed counter that increments
        by 1 with every modification to the resource."

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        publisher = create_publisher("VR Pub")
        work = create_work(publisher["id"], title="VR Work", catalog_number="VR-1")
        rental_set = create_rental_set(work["id"], set_code="VR-SET", copy_count=30,
                                       replacement_value_cents=240000)
        account = create_account("VR Acct", credit_tier="STANDARD", credit_limit_cents=0)
        advance_clock()
        order = create_order(account["id"], rental_set["id"], copies=1)
        v_create = order["version"]

        v_res = reserve_order(order["id"])["version"]
        assert v_res == v_create + 1, "reserve must increment the order's version"
        v_dis = dispatch_order(order["id"])["version"]
        assert v_dis == v_res + 1, "dispatch must increment the order's version"
        v_conf = confirm_order(order["id"], account["id"])["version"]
        assert v_conf == v_dis + 1, "confirm-receipt must increment the version"
        v_ren = renew_order(order["id"], v_conf)["version"]
        assert v_ren == v_conf + 1, "renewal must increment the order's version"

    def test_immediate_visibility_of_reserve_side_effects(self, api):
        """PRD §3.5: "On success the system allocates: it creates one rental line
        per requested copy with `copy_seq` running from 1 through
        `copies_requested`, each line `RESERVED`; decrements the set's
        `available_copy_count` by `copies_requested`; stamps `estimated_fee_cents`".
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/immediate_visibility_of_reserve_side_effects
        """
        publisher = create_publisher("IC Pub")
        work = create_work(publisher["id"], title="IC Work", catalog_number="IC-1")
        rental_set = create_rental_set(work["id"], set_code="IC-SET", copy_count=10,
                                       replacement_value_cents=80000)
        account = create_account("IC Acct", credit_tier="STANDARD", credit_limit_cents=0)
        advance_clock()
        order = create_order(account["id"], rental_set["id"], copies=3)

        reserved = validate_success(api.reserve_rental_order(order["id"], CLERK))
        # 3 copies x 10000 cents x 1 loan period, no volume discount below 10.
        assert reserved["status"] == "RESERVED"
        assert reserved["estimated_fee_cents"] == 30000

        set_after = fetch_set(rental_set["id"])
        assert_rental_set(set_after)
        assert set_after["available_copy_count"] == 7, (
            "the debit must be visible on an immediate re-read; got "
            f"{set_after['available_copy_count']}"
        )

    def test_rental_order_list_filtered_by_account(self, api):
        """PRD §3.5: "Rental orders may be listed with filters on `account_id`,
        `rental_set_id`, or `purchase_order_id`."

        Design: Corner/endpoints/rental_order_list_filtered_by_account
        """
        publisher = create_publisher("FL Pub")
        work = create_work(publisher["id"], title="FL Work", catalog_number="FL-1")
        rental_set = create_rental_set(work["id"], set_code="FL-SET", copy_count=30,
                                       replacement_value_cents=240000)
        account_a = create_account("FL A", credit_tier="STANDARD", credit_limit_cents=0)
        account_b = create_account("FL B", credit_tier="STANDARD", credit_limit_cents=0)
        advance_clock()
        create_order(account_a["id"], rental_set["id"], copies=1)
        create_order(account_a["id"], rental_set["id"], copies=1)
        create_order(account_b["id"], rental_set["id"], copies=1)

        resp = api.list_rental_orders(CLERK, params={"account_id": account_a["id"]})
        rows, meta = validate_paginated(resp)
        assert meta["total_count"] == 2, (
            f"account A owns exactly 2 of the 3 orders, got {meta['total_count']}"
        )
        assert len(rows) == 2
        assert all(row["account_id"] == account_a["id"] for row in rows)

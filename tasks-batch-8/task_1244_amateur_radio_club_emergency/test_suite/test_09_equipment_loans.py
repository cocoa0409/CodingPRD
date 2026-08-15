"""Equipment loans and the privilege cascade (PRD §3.8): loan window rules,
the one-outstanding invariant, late-fee arithmetic with pinned rounding,
mark-lost pricing, overdue system transition, and immediate consistency."""
from test_helpers import (
    ApiErrorId,
    assert_equipment_loan,
    assert_instant_equals,
    create_active_member,
    create_equipment_loan_payload,
    create_loan,
    get_success_data,
    make_member_headers,
    return_loan,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestLoanWindowAndUniqueness:
    def test_due_at_beyond_90_days_rejected(self, api, admin_headers):
        """PRD §3.8: "The window rule is strict: `due_at` must lie strictly
        after the current clock and no more than 90 days in the future (else
        `ERR_LOAN_WINDOW_INVALID`)."

        Design: Corner/validations/loan_window_invalid_rejected
        """
        member = create_active_member("K1OPR")
        # Default clock 2026-05-01: the furthest legal due date is 2026-07-30;
        # 2026-09-01 exceeds it.
        resp = api.create_equipment_loan(
            create_equipment_loan_payload(item_tag="HT-9",
                                          due_at="2026-09-01T00:00:00Z"),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_LOAN_WINDOW_INVALID)

    def test_second_checkout_of_same_item_rejected(self, api, admin_headers):
        """PRD §3.8: "At most one outstanding loan — status `ACTIVE` or
        `OVERDUE` — may exist per `item_tag`; a second checkout of the same tag
        is rejected with `ERR_ITEM_ON_LOAN`."

        Design: Corner/validations/item_on_loan_conflict
        """
        member = create_active_member("K1OPR")
        create_loan(member["id"], item_tag="HT-7")
        resp = api.create_equipment_loan(
            create_equipment_loan_payload(item_tag="HT-7"),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_ITEM_ON_LOAN)


class TestOutstandingRoundtrip:
    def test_return_settles_zero_fee_when_on_time(self, api, admin_headers):
        """PRD §3.8: "A loan returned at or before `due_at` owes nothing." and
        "A return stamps `returned_at` and settles `late_fee_cents`, which is
        zero while a loan is outstanding."

        Design: Difficulty/compensating_invariant/equipment_loan_outstanding_roundtrip
        """
        member = create_active_member("K1AAA")
        loan = create_loan(member["id"], item_tag="HT-300",
                           due_at="2026-06-01T00:00:00Z")
        returned = return_loan(loan["id"], member["id"], "GOOD")
        assert_equipment_loan(returned)
        assert returned["status"] == "RETURNED"
        assert returned["late_fee_cents"] == 0

    def test_item_tag_is_checkoutable_again_after_return(self, api, admin_headers):
        """PRD §3.8: "At most one outstanding loan — status `ACTIVE` or
        `OVERDUE` — may exist per `item_tag`; a second checkout of the same tag
        is rejected with `ERR_ITEM_ON_LOAN`." — returning the outstanding loan
        restores the tag's availability.

        Design: Difficulty/compensating_invariant/equipment_loan_outstanding_roundtrip
        """
        member = create_active_member("K1AAA")
        loan1 = create_loan(member["id"], item_tag="HT-300",
                            due_at="2026-06-01T00:00:00Z")
        return_loan(loan1["id"], member["id"], "GOOD")
        loan2 = get_success_data(api.create_equipment_loan(
            create_equipment_loan_payload(item_tag="HT-300",
                                          due_at="2026-06-15T00:00:00Z"),
            make_member_headers(member["id"])))
        assert loan2["status"] == "ACTIVE"
        rows, meta = validate_paginated(api.list_equipment_loans(
            admin_headers, params={"item_tag": "HT-300", "status": "ACTIVE"}))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == loan2["id"]


class TestLateFeeComputation:
    def test_component_rounding_order_pinned(self, api, admin_headers):
        """PRD §3.8: "For a late return, the days overdue are the elapsed time
        from `due_at` to `returned_at` divided into days and rounded up to a
        whole day; the base fee is that day count times 150 cents per day,
        rounded half-up to whole cents. When the `return_condition` is
        `DAMAGED`, a damage fee of one tenth of the declared value — ten
        percent of `estimated_value_cents`, itself rounded half-up to whole
        cents — is computed."

        Design: Difficulty/combinatorial_formula/late_fee_component_rounding_order
        """
        member = create_active_member("K1AAA")
        loan = create_loan(member["id"], item_tag="HT-100",
                           due_at="2026-05-02T00:00:00Z",
                           estimated_value_cents=1005)
        set_clock("2026-05-05T00:00:00Z")
        returned = return_loan(loan["id"], member["id"], "DAMAGED")
        assert_equipment_loan(returned)
        assert returned["status"] == "RETURNED"
        # 3 days overdue -> base round_half_up(3 * 150) = 450; damage
        # round_half_up(1005 * 0.10) = 101; sum 551 is below the 1005 cap.
        assert returned["late_fee_cents"] == 551

    def test_damaged_return_suspends_equipment_privilege(self, api, admin_headers):
        """PRD §3.8: "A `DAMAGED` return — and equally a mark-lost write-off, a
        `ClubAdmin` action available from `ACTIVE` or `OVERDUE` — suspends the
        member's `equipment_privilege` (`GOOD_STANDING` → `SUSPENDED`), bumps
        the member's `version`, and recomputes readiness with the 50-point
        privilege penalty now applied."

        Design: Difficulty/combinatorial_formula/late_fee_component_rounding_order
        """
        member = create_active_member("K1AAA")
        loan = create_loan(member["id"], item_tag="HT-100",
                           due_at="2026-05-02T00:00:00Z",
                           estimated_value_cents=1005)
        set_clock("2026-05-05T00:00:00Z")
        return_loan(loan["id"], member["id"], "DAMAGED")
        detail = get_success_data(api.get_member(member["id"], admin_headers))
        assert detail["equipment_privilege"] == "SUSPENDED"

    def test_fee_capped_at_estimated_value(self, api, admin_headers):
        """PRD §3.8: "The two rounded components are summed, and the total is
        capped at `estimated_value_cents`; the cap is applied last, after
        rounding and summation."

        Design: Corner/calculations/late_fee_capped_at_estimated_value
        """
        member = create_active_member("K1OPR")
        loan = create_loan(member["id"], item_tag="HT-2",
                           due_at="2026-05-02T00:00:00Z",
                           estimated_value_cents=500)
        set_clock("2026-05-07T00:00:00Z")
        returned = return_loan(loan["id"], member["id"], "GOOD")
        assert returned["status"] == "RETURNED"
        # 5 days * 150 = 750 exceeds the declared value; the cap binds at 500.
        assert returned["late_fee_cents"] == 500

    def test_mark_lost_prices_full_value_and_suspends_privilege(self, api, admin_headers):
        """PRD §3.8: "A loan marked lost is priced at its full declared value:
        `late_fee_cents` equals `estimated_value_cents`, and no further
        arithmetic applies." and "A `DAMAGED` return — and equally a mark-lost
        write-off, a `ClubAdmin` action available from `ACTIVE` or `OVERDUE` —
        suspends the member's `equipment_privilege` (`GOOD_STANDING` →
        `SUSPENDED`)".

        Design: Corner/calculations/mark_lost_fee_equals_estimated_value
        """
        member = create_active_member("K1OPR")
        loan = create_loan(member["id"], item_tag="HT-3",
                           due_at="2026-06-01T00:00:00Z",
                           estimated_value_cents=800)
        lost = get_success_data(api.mark_loan_lost(loan["id"], admin_headers))
        assert lost["status"] == "LOST"
        assert lost["late_fee_cents"] == 800
        detail = get_success_data(api.get_member(member["id"], admin_headers))
        assert detail["equipment_privilege"] == "SUSPENDED"


class TestOverdueTransition:
    def test_clock_past_due_marks_loan_overdue(self, api, admin_headers):
        """PRD §3.8: "When the clock passes `due_at`, an `ACTIVE` loan becomes
        `OVERDUE` automatically." and "A return stamps `returned_at` and
        settles `late_fee_cents`, which is zero while a loan is outstanding."
        PRD §2.4: "`version` (integer): a system-managed integer that
        increments by one on every mutation of the resource, including
        mutations caused by cascades originating on other entities."

        Design: Corner/state_machines/loan_overdue_system_transition
        """
        member = create_active_member("K1OPR")
        loan = create_loan(member["id"], item_tag="HT-1",
                           due_at="2026-05-03T00:00:00Z")
        assert loan["status"] == "ACTIVE"
        set_clock("2026-05-04T00:00:00Z")
        after = get_success_data(api.get_equipment_loan(loan["id"], admin_headers))
        assert after["status"] == "OVERDUE"
        assert after["version"] == loan["version"] + 1
        assert after["late_fee_cents"] == 0


class TestPrivilegeGating:
    def test_suspended_privilege_blocks_new_loan(self, api, admin_headers):
        """PRD §3.8: "The borrower must be `ACTIVE` (`ERR_MEMBERSHIP_NOT_ACTIVE`)
        and hold `equipment_privilege` `GOOD_STANDING`
        (`ERR_EQUIPMENT_PRIVILEGE_SUSPENDED`)."

        Design: Corner/validations/equipment_privilege_suspended_blocks_loan
        """
        member = create_active_member("K1OPR")
        loan = create_loan(member["id"], item_tag="HT-8",
                           due_at="2026-06-01T00:00:00Z")
        return_loan(loan["id"], member["id"], "DAMAGED")
        resp = api.create_equipment_loan(
            create_equipment_loan_payload(item_tag="HT-10",
                                          estimated_value_cents=500),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_PRIVILEGE_SUSPENDED)
        detail = get_success_data(api.get_member(member["id"], admin_headers))
        assert detail["equipment_privilege"] == "SUSPENDED"


class TestReturnLockdown:
    def test_double_return_rejected(self, api, admin_headers):
        """PRD §3.8: "return or write-off against a loan that is not
        outstanding — neither `ACTIVE` nor `OVERDUE` — is rejected with
        `ERR_LOAN_NOT_OUTSTANDING`."

        Design: Corner/errors/double_return_rejected
        """
        member = create_active_member("K1OPR")
        loan = create_loan(member["id"], item_tag="HT-5",
                           due_at="2026-06-01T00:00:00Z")
        return_loan(loan["id"], member["id"], "GOOD")
        resp = api.return_equipment_loan(
            loan["id"], {"return_condition": "GOOD"}, make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_LOAN_NOT_OUTSTANDING)


class TestImmediateConsistency:
    def test_return_response_carries_settled_fields(self, api, admin_headers):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field." and §3.8: "A return stamps `returned_at` and settles
        `late_fee_cents`, which is zero while a loan is outstanding."
        PRD §2.5: "At server startup the logical clock reads exactly
        `2026-05-01T00:00:00Z`".

        Design: Corner/consistency_model/immediate_read_after_write
        """
        member = create_active_member("K1OPR")
        loan = create_loan(member["id"], item_tag="HT-6",
                           due_at="2026-06-01T00:00:00Z",
                           estimated_value_cents=2000)
        resp = api.return_equipment_loan(
            loan["id"], {"return_condition": "DAMAGED"},
            make_member_headers(member["id"]))
        returned = validate_success(resp, 200)
        assert returned["status"] == "RETURNED"
        # Not overdue: base fee 0; damage fee = 10% of 2000 = 200.
        assert returned["late_fee_cents"] == 200
        assert_instant_equals(returned["returned_at"], "2026-05-01T00:00:00Z",
                              "returned_at")

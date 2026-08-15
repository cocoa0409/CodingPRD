"""Exception queue: deadline computation, decisions, defaults, liability
derivation, segregation of duties, and validation ordering."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_user,
    assert_instant_equal,
    create_active_enrollment,
    create_enrollment,
    daily_sweep,
    decide,
    fee_statement,
    get_account,
    get_check_by_number,
    get_enrollment,
    get_exception,
    make_check_row,
    make_customer_decision_maker_headers,
    present_item,
    set_clock,
    setup_open_exception,
    upload_checks,
    validate_error,
    validate_success,
)

BANK_MGR = TEST_USERS["bank_treasury_manager_headers"]
BANK_OPS = TEST_USERS["bank_ops_headers"]


# ----------------------------------------------------------------------
# Deadline variants
# ----------------------------------------------------------------------

class TestDeadlineVariants:
    def test_same_day_cutoff_before_1400_gives_same_day_2000(self, api):
        """PRD §3.5: "Under `SAME_DAY_CUTOFF`, an item presented before
        14:00:00 UTC gets a deadline of 20:00:00 UTC that same day".

        Design: Difficulty/dual_variant_calc/deadline_same_day_cutoff_vs_rolling_hours
        """
        b = create_active_enrollment("CutoffCo", "REVERSE_POSITIVE_PAY",
                                     "RETURN", account_number="910001",
                                     deadline_mode="SAME_DAY_CUTOFF")
        set_clock("2026-08-03T13:00:00Z")
        item = present_item(b["account"]["id"], "1", 500, "X",
                            channel="CLEARING")
        exc = get_exception(item["exception_id"])
        assert_instant_equal(exc["decision_deadline_at"],
                             "2026-08-03T20:00:00Z")

    def test_rolling_hours_adds_window_to_presented_at(self, api):
        """PRD §3.5: "Under `ROLLING_HOURS`, the deadline is exactly
        `decision_window_hours` hours after `presented_at` — an item presented
        at 13:00:00 UTC with a 24-hour window is due at 13:00:00 UTC the next
        day".

        Design: Difficulty/dual_variant_calc/deadline_same_day_cutoff_vs_rolling_hours
        """
        b = create_active_enrollment("RollCo", "REVERSE_POSITIVE_PAY", "RETURN",
                                     account_number="920001",
                                     deadline_mode="ROLLING_HOURS",
                                     decision_window_hours=24)
        set_clock("2026-08-03T13:00:00Z")
        item = present_item(b["account"]["id"], "1", 500, "X",
                            channel="CLEARING")
        exc = get_exception(item["exception_id"])
        assert_instant_equal(exc["decision_deadline_at"],
                             "2026-08-04T13:00:00Z")

    def test_presented_exactly_at_cutoff_rolls_to_next_day(self, api):
        """PRD §3.5: "an item presented at exactly 14:00:00 UTC or later gets
        20:00:00 UTC on the following day."

        Design: Corner/calculations/cutoff_exactly_1400_rolls_next_day
        """
        b = create_active_enrollment("CutCo", "REVERSE_POSITIVE_PAY", "PAY",
                                     account_number="820012")
        item1 = present_item(b["account"]["id"], "1", 100, "A",
                             presented_at="2026-08-03T13:59:59Z")
        item2 = present_item(b["account"]["id"], "2", 100, "B",
                             presented_at="2026-08-03T14:00:00Z")
        assert_instant_equal(get_exception(item1["exception_id"])
                             ["decision_deadline_at"], "2026-08-03T20:00:00Z")
        assert_instant_equal(get_exception(item2["exception_id"])
                             ["decision_deadline_at"], "2026-08-04T20:00:00Z")


class TestDeadlineInclusiveSecond:
    def _setup(self):
        b = create_active_enrollment("SecCo", "REVERSE_POSITIVE_PAY", "PAY",
                                     account_number="990002",
                                     user_roles=("ADMIN", "DECISION_MAKER"),
                                     deadline_mode="ROLLING_HOURS",
                                     decision_window_hours=24)
        set_clock("2026-08-03T13:00:00Z")
        ex1 = present_item(b["account"]["id"], "1", 500, "P1")["exception_id"]
        ex2 = present_item(b["account"]["id"], "2", 500, "P2")["exception_id"]
        return b, ex1, ex2

    def test_decision_at_exact_deadline_accepted_and_sweep_defaults_none(
            self, api):
        """PRD §3.5: "The deadline is inclusive for customer decisions: a
        decision recorded at exactly `decision_deadline_at` is accepted. The
        daily sweep, by contrast, defaults only exceptions whose deadline is
        strictly behind the clock."

        Design: Difficulty/boundary_precision_check/decision_deadline_exact_second_inclusive
        """
        b, ex1, _ = self._setup()
        set_clock("2026-08-04T13:00:00Z")
        decided = decide(ex1, "PAY", b["headers"]["DECISION_MAKER"])
        assert decided["status"] == "DECISIONED_PAY"
        run = daily_sweep(b["enrollment"]["id"])
        assert run["exceptions_defaulted"] == 0, (
            "a deadline exactly equal to the clock is not strictly behind it")

    def test_decision_one_second_past_deadline_rejected_then_defaulted(
            self, api):
        """PRD §3.5: "a logical clock later than `decision_deadline_at` rejects
        with `ERR_DECISION_DEADLINE_PASSED`".
        PRD §3.5: "a snapshot of `PAY` moves the exception to `DEFAULTED_PAY`".
        PRD §3.9: "Every `OPEN` exception whose `decision_deadline_at` is
        strictly earlier than the logical clock is defaulted per its snapshot,
        counted as `exceptions_defaulted`." — both setup exceptions are OPEN
        and strictly past due at the sweep, so both default.

        Design: Difficulty/boundary_precision_check/decision_deadline_exact_second_inclusive
        """
        b, ex1, ex2 = self._setup()
        set_clock("2026-08-04T13:00:01Z")
        resp = api.decide_exception(ex2, "PAY", b["headers"]["DECISION_MAKER"])
        validate_error(resp, ApiErrorId.ERR_DECISION_DEADLINE_PASSED)
        run = daily_sweep(b["enrollment"]["id"])
        assert run["exceptions_defaulted"] == 2, (
            "ex1 and ex2 are both OPEN and strictly past their shared deadline")
        assert get_exception(ex2)["status"] == "DEFAULTED_PAY"
        assert get_exception(ex1)["status"] == "DEFAULTED_PAY"


# ----------------------------------------------------------------------
# Validation ordering on decisions
# ----------------------------------------------------------------------

class TestDecisionValidationOrder:
    def _setup_defaulted(self):
        b = create_active_enrollment("PrioCo", "REVERSE_POSITIVE_PAY", "RETURN",
                                     account_number="980001",
                                     user_roles=("ADMIN", "DECISION_MAKER"))
        item = present_item(b["account"]["id"], "1", 900, "P",
                            presented_at="2026-08-03T10:00:00Z")
        set_clock("2026-08-04T09:00:00Z")
        run = daily_sweep(b["enrollment"]["id"])
        return b, item["exception_id"], run

    def test_sweep_defaults_expired_exception(self, api):
        """PRD §3.5: "An exception still `OPEN` whose `decision_deadline_at` is
        strictly earlier than the logical clock is defaulted according to its
        `default_decision_snapshot`: ... a snapshot of `RETURN` moves the
        exception to `DEFAULTED_RETURN`".

        Design: Difficulty/priority_pair_validation_conflict/exception_not_open_beats_deadline_passed
        """
        b, ex, run = self._setup_defaulted()
        assert run["exceptions_defaulted"] == 1
        assert get_exception(ex)["status"] == "DEFAULTED_RETURN"

    def test_not_open_beats_deadline_passed(self, api):
        """PRD §3.5: "The decision enforces four preconditions, evaluated in
        order — enrollment state first ..., then exception state (not `OPEN`
        rejects with `ERR_EXCEPTION_NOT_OPEN`), then the deadline (a logical
        clock later than `decision_deadline_at` rejects with
        `ERR_DECISION_DEADLINE_PASSED`)".

        Design: Difficulty/priority_pair_validation_conflict/exception_not_open_beats_deadline_passed
        """
        b, ex, _ = self._setup_defaulted()
        resp = api.decide_exception(ex, "PAY", b["headers"]["DECISION_MAKER"])
        validate_error(resp, ApiErrorId.ERR_EXCEPTION_NOT_OPEN)

    def test_enrollment_state_beats_exception_state(self, api):
        """PRD §3.5: "The decision enforces four preconditions, evaluated in
        order — enrollment state first (a `TERMINATED` enrollment rejects with
        `ERR_ENROLLMENT_TERMINATED`, any other non-`ACTIVE` status with
        `ERR_ENROLLMENT_NOT_ACTIVE`), then exception state".

        Design: Corner/validations/enrollment_state_beats_exception_state
        """
        b, ex, _ = self._setup_defaulted()
        validate_success(api.suspend_enrollment(b["enrollment"]["id"], BANK_MGR))
        resp = api.decide_exception(ex, "PAY", b["headers"]["DECISION_MAKER"])
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE)

    def test_invalid_enum_on_missing_id_returns_shape_error(self, api):
        """PRD §2.10: "shape failures yield `ERR_INVALID_REQUEST` and surface
        before any resource lookup, so a malformed body on a nonexistent id
        returns `ERR_INVALID_REQUEST`."

        Design: Corner/validations/invalid_enum_beats_not_found
        """
        enr = create_enrollment("ShpCo", "POSITIVE_PAY", "PAY")
        dm = add_user(enr["id"], "Dec", "DECISION_MAKER")
        resp = api.decide_exception(NON_EXISTENT_UUID, "MAYBE",
                                    make_customer_decision_maker_headers(
                                        dm["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestExtendDeadline:
    def test_extension_after_deadline_passed_rejected(self, api):
        """PRD §3.5: "requires the logical clock still be at or before the
        current `decision_deadline_at` (`ERR_DECISION_DEADLINE_PASSED`)".

        Design: Corner/endpoints/extend_deadline_after_expiry_rejected
        """
        b = create_active_enrollment("Ext4Co", "REVERSE_POSITIVE_PAY", "PAY",
                                     account_number="840004",
                                     user_roles=("ADMIN",),
                                     deadline_mode="ROLLING_HOURS",
                                     decision_window_hours=24)
        set_clock("2026-08-03T10:00:00Z")
        ex = present_item(b["account"]["id"], "1", 100, "A")["exception_id"]
        set_clock("2026-08-04T12:00:00Z")
        resp = api.extend_exception_deadline(ex, "2026-08-05T09:00:00Z",
                                             BANK_OPS)
        validate_error(resp, ApiErrorId.ERR_DECISION_DEADLINE_PASSED)


# ----------------------------------------------------------------------
# Liability derivation matrix at the exception level
# ----------------------------------------------------------------------

def _matrix_setup():
    """PAYEE-tier enrollment with three exceptions:
    e1 PAYEE_MISMATCH (check 101), e2 AMOUNT_MISMATCH (check 102),
    e3 NO_ISSUE_RECORD (unknown check 999).
    'ACME IND' vs issued 'ACME INDUSTRIES' scores floor(4*100/14) +
    floor(10*50/14) = 28 + 35 = 63 < threshold 85 -> PAYEE_MISMATCH."""
    b = create_active_enrollment("MatrixCo", "PAYEE_POSITIVE_PAY", "RETURN",
                                 account_number="930001",
                                 user_roles=("MANAGER", "DECISION_MAKER"))
    upload_checks(b["enrollment"]["id"], b["account"]["id"], "F-MATRIX",
                  [make_check_row("101", 30000, "ACME INDUSTRIES"),
                   make_check_row("102", 40000, "BETA LLC")],
                  b["headers"]["MANAGER"])
    e1 = present_item(b["account"]["id"], "101", 30000, "ACME IND",
                      presented_at="2026-08-03T10:00:00Z")["exception_id"]
    e2 = present_item(b["account"]["id"], "102", 40050, "BETA LLC",
                      presented_at="2026-08-03T10:00:00Z")["exception_id"]
    e3 = present_item(b["account"]["id"], "999", 7000, "GHOST",
                      presented_at="2026-08-03T10:00:00Z")["exception_id"]
    return b, e1, e2, e3


class TestLiabilityPartyMatrix:
    def test_decisioned_pay_assigns_customer(self, api):
        """PRD §3.5: "The customer approved the item, so `liability_party` is
        set to `CUSTOMER`."
        PRD §3.5: "The liability matrix at the exception level is therefore
        complete: `DECISIONED_RETURN` yields `NONE`, and every pay or default
        path — `DECISIONED_PAY`, `DEFAULTED_PAY`, `DEFAULTED_RETURN` — yields
        `CUSTOMER`."

        Design: Difficulty/combinatorial_formula/liability_party_branch_matrix_by_reason_and_path
        """
        b, e1, _, _ = _matrix_setup()
        decided = decide(e1, "PAY", b["headers"]["DECISION_MAKER"])
        assert decided["status"] == "DECISIONED_PAY"
        assert decided["liability_party"] == "CUSTOMER"

    def test_decisioned_return_assigns_none(self, api):
        """PRD §3.5: "A `RETURN` decision moves the exception to
        `DECISIONED_RETURN` ... and sets `liability_party` to `NONE` — the item
        was never paid, so there is no loss to allocate."

        Design: Difficulty/combinatorial_formula/liability_party_branch_matrix_by_reason_and_path
        """
        b, _, e2, _ = _matrix_setup()
        decided = decide(e2, "RETURN", b["headers"]["DECISION_MAKER"])
        assert decided["status"] == "DECISIONED_RETURN"
        assert decided["liability_party"] == "NONE"

    def test_defaulted_return_assigns_customer(self, api):
        """PRD §3.5: "because the deadline was missed and the default rule
        governs — set `liability_party` to `CUSTOMER` on both the pay and the
        return default."

        Design: Difficulty/combinatorial_formula/liability_party_branch_matrix_by_reason_and_path
        """
        b, _, _, e3 = _matrix_setup()
        set_clock("2026-08-04T09:00:00Z")
        daily_sweep(b["enrollment"]["id"])
        exc = get_exception(e3)
        assert exc["status"] == "DEFAULTED_RETURN"
        assert exc["liability_party"] == "CUSTOMER"


# ----------------------------------------------------------------------
# Decision side effects
# ----------------------------------------------------------------------

class TestDecisionSideEffects:
    def test_pay_decision_consumes_check_at_presented_amount(self, api):
        """PRD §3.5: "A `PAY` decision moves the exception to `DECISIONED_PAY`
        and the item from `EXCEPTION_HELD` to `PAID`, with the full pay-side
        cascade: `paid_at` stamped, the account ledger updated, the review
        threshold evaluated (which may flip the account to `REVIEW_HOLD`), and
        the linked check — when there is one — moved from `REGISTERED` to
        `CONSUMED` with `consumed_by_item_id` set."
        PRD §3.2: "On every item pay event — a clean auto-match, an exception
        decided to pay, or an exception defaulted to pay — the item's
        `amount_cents` is added to `cumulative_paid_cents`."

        Design: Corner/state_machines/decision_pay_consumes_issued_check
        """
        b = create_active_enrollment("ConsCo", "PAYEE_POSITIVE_PAY", "PAY",
                                     account_number="810012",
                                     user_roles=("ADMIN", "DECISION_MAKER"))
        upload_checks(b["enrollment"]["id"], b["account"]["id"], "F-CONS",
                      [make_check_row("702", 800, "C CO")],
                      b["headers"]["ADMIN"])
        item = present_item(b["account"]["id"], "702", 801, "C CO",
                            presented_at="2026-08-03T10:00:00Z")
        assert item["match_result"] == "AMOUNT_MISMATCH"
        decide(item["exception_id"], "PAY", b["headers"]["DECISION_MAKER"])
        check = get_check_by_number(b["account"]["id"], "702")
        assert check["status"] == "CONSUMED"
        assert check["consumed_by_item_id"] == item["id"]
        account = get_account(b["account"]["id"])
        assert account["cumulative_paid_cents"] == 801, (
            "the item settles at the presented amount, not the issued amount")

    def test_defaulted_return_accrues_return_fee(self, api):
        """PRD §3.5: "a snapshot of `RETURN` moves the exception to
        `DEFAULTED_RETURN` and the item to `DEFAULT_RETURNED` with the 500-cent
        return-fee accrual."
        PRD §3.7: "every exception creation — for any reason, including
        `REVERSE_REVIEW` — accrues one `EXCEPTION_FEE` entry of 200 cents in
        `ACCRUED` status".

        Design: Corner/state_machines/default_return_applies_return_fee
        """
        b = create_active_enrollment("DefRetCo", "REVERSE_POSITIVE_PAY",
                                     "RETURN", account_number="810011")
        item = present_item(b["account"]["id"], "1", 500, "P",
                            presented_at="2026-08-03T10:00:00Z")
        set_clock("2026-08-04T09:00:00Z")
        run = daily_sweep(b["enrollment"]["id"])
        assert run["exceptions_defaulted"] == 1
        assert get_presented_item_status(api, item["id"]) == "DEFAULT_RETURNED"
        stmt = fee_statement(b["enrollment"]["id"], "2026-08")
        assert stmt["exception_fees_cents"] == 200
        assert stmt["return_fees_cents"] == 500

    def test_open_exception_count_reconciled_across_paths(self, api):
        """PRD §3.5: "Creation also accrues a provisional 200-cent exception fee
        (§3.7) linked through the exception's `fee_entry_id`, and adds one to
        the enrollment's `open_exception_count`."
        PRD §3.5: "On either decision the server records `decided_by_user_id`
        from the caller and stamps `decided_at`, derives `liability_party`, and
        subtracts one from the enrollment's `open_exception_count`."
        PRD §3.5: "Defaults carry no `decided_by_user_id` or `decided_at`,
        subtract one from `open_exception_count`".

        Design: Corner/complexity_layers/open_exception_count_reconciled
        """
        b = create_active_enrollment("CntCo", "REVERSE_POSITIVE_PAY", "RETURN",
                                     account_number="860009",
                                     user_roles=("ADMIN", "DECISION_MAKER"))
        e1 = present_item(b["account"]["id"], "1", 100, "A",
                          presented_at="2026-08-03T10:00:00Z")["exception_id"]
        present_item(b["account"]["id"], "2", 100, "B",
                     presented_at="2026-08-03T10:00:00Z")
        assert get_enrollment(b["enrollment"]["id"])["open_exception_count"] == 2
        decide(e1, "PAY", b["headers"]["DECISION_MAKER"])
        assert get_enrollment(b["enrollment"]["id"])["open_exception_count"] == 1
        set_clock("2026-08-04T09:00:00Z")
        daily_sweep(b["enrollment"]["id"])
        assert get_enrollment(b["enrollment"]["id"])["open_exception_count"] == 0

    def test_decision_response_matches_immediate_read(self, api):
        """PRD §3.5: "A `RETURN` decision moves the exception to
        `DECISIONED_RETURN` and the item from `EXCEPTION_HELD` to `RETURNED` ...
        and sets `liability_party` to `NONE`".

        Design: Corner/consistency_model/immediate_read_after_decision_write
        """
        b = setup_open_exception(tier="REVERSE_POSITIVE_PAY",
                                 default_decision="PAY", business_name="ImmCo",
                                 account_number="860011")
        decided = decide(b["exception_id"], "RETURN",
                         b["headers"]["DECISION_MAKER"])
        assert decided["status"] == "DECISIONED_RETURN"
        assert decided["liability_party"] == "NONE"
        reread = get_exception(b["exception_id"])
        assert reread["status"] == "DECISIONED_RETURN"
        assert reread["liability_party"] == "NONE"


def get_presented_item_status(api, item_id):
    return validate_success(api.get_presented_item(item_id, BANK_OPS))["status"]


# ----------------------------------------------------------------------
# RBAC and segregation of duties on decisions
# ----------------------------------------------------------------------

class TestDecisionRbac:
    def test_viewer_cannot_decide(self, api):
        """PRD §2.1: "A caller whose role is not listed for the endpoint, or a
        customer-role caller whose `EnrollmentUser.user_role` does not match the
        claimed role, is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).
        `CustomerViewer` is read-only across the entire API."

        Design: Corner/rbac/viewer_decision_forbidden
        """
        b = setup_open_exception(tier="REVERSE_POSITIVE_PAY",
                                 default_decision="PAY", business_name="ViewCo",
                                 account_number="850001",
                                 user_roles=("ADMIN", "VIEWER"))
        resp = api.decide_exception(b["exception_id"], "PAY",
                                    b["headers"]["VIEWER"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_cross_enrollment_decision_denied(self, api):
        """PRD §2.1: "a customer-role caller may only touch resources whose
        owning enrollment equals the `enrollment_id` of their own
        `EnrollmentUser` record, and any attempt to reach across enrollment
        boundaries is rejected with `ERR_CROSS_ENROLLMENT_ACCESS` (HTTP 403)."

        Design: Corner/rbac/cross_enrollment_decision_denied
        """
        a = create_active_enrollment("OwnA", "REVERSE_POSITIVE_PAY", "PAY",
                                     user_roles=("MANAGER",), with_account=False,
                                     trainer_id="tr-1")
        b = setup_open_exception(tier="REVERSE_POSITIVE_PAY",
                                 default_decision="PAY", business_name="OwnB",
                                 account_number="850002",
                                 user_roles=("ADMIN",))
        resp = api.decide_exception(b["exception_id"], "PAY",
                                    a["headers"]["MANAGER"])
        validate_error(resp, ApiErrorId.ERR_CROSS_ENROLLMENT_ACCESS)

    def test_claimed_role_must_match_persisted_user_role(self, api):
        """PRD §2.1: "that record's `user_role` field (one of `ADMIN`,
        `MANAGER`, `DECISION_MAKER`, `VIEWER`) must correspond to the claimed
        role: `ADMIN` for `CustomerAdmin`, `MANAGER` for `CustomerManager`,
        `DECISION_MAKER` for `CustomerDecisionMaker`, and `VIEWER` for
        `CustomerViewer`."

        Design: Corner/rbac/admin_role_mismatch_decision_forbidden
        """
        b = setup_open_exception(tier="REVERSE_POSITIVE_PAY",
                                 default_decision="PAY", business_name="MisCo",
                                 account_number="850003",
                                 user_roles=("ADMIN",))
        resp = api.decide_exception(
            b["exception_id"], "PAY",
            make_customer_decision_maker_headers(b["users"]["ADMIN"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_uploader_may_not_decide_own_file_exception(self, api):
        """PRD §2.8: "When deciding an exception whose `issued_check_id` is
        non-null, the caller's `X-User-ID` must differ from the
        `uploaded_by_user_id` of the issue file that registered that check. A
        violation is rejected with `ERR_SOD_UPLOAD_DECISION_CONFLICT`."

        Design: Corner/rbac/sod_upload_decision_conflict
        """
        b = create_active_enrollment("SodCo", "PAYEE_POSITIVE_PAY", "PAY",
                                     account_number="850005",
                                     user_roles=("MANAGER", "DECISION_MAKER"))
        upload_checks(b["enrollment"]["id"], b["account"]["id"], "F-SOD",
                      [make_check_row("901", 5000, "SOD PAYEE")],
                      b["headers"]["MANAGER"])
        item = present_item(b["account"]["id"], "901", 5001, "SOD PAYEE",
                            presented_at="2026-08-03T10:00:00Z")
        assert item["match_result"] == "AMOUNT_MISMATCH"
        resp = api.decide_exception(item["exception_id"], "PAY",
                                    b["headers"]["MANAGER"])
        validate_error(resp, ApiErrorId.ERR_SOD_UPLOAD_DECISION_CONFLICT)
        decided = decide(item["exception_id"], "PAY",
                         b["headers"]["DECISION_MAKER"])
        assert decided["status"] == "DECISIONED_PAY"

    def test_no_issue_record_exception_exempt_from_uploader_sod(self, api):
        """PRD §2.8: "When deciding an exception whose `issued_check_id` is
        non-null, the caller's `X-User-ID` must differ from the
        `uploaded_by_user_id` of the issue file that registered that check" —
        the rule keys on a non-null `issued_check_id`, which `NO_ISSUE_RECORD`
        exceptions lack (§3.5).

        Design: Corner/rbac/sod_no_issue_record_exempt
        """
        b = create_active_enrollment("SodXCo", "PAYEE_POSITIVE_PAY", "PAY",
                                     account_number="850006",
                                     user_roles=("MANAGER",))
        upload_checks(b["enrollment"]["id"], b["account"]["id"], "F-SODX",
                      [make_check_row("910", 5000, "OK PAYEE")],
                      b["headers"]["MANAGER"])
        item = present_item(b["account"]["id"], "9999", 300, "UNKNOWN",
                            presented_at="2026-08-03T10:00:00Z")
        assert item["match_result"] == "NO_ISSUE_RECORD"
        decided = decide(item["exception_id"], "RETURN",
                         b["headers"]["MANAGER"])
        assert decided["status"] == "DECISIONED_RETURN"

"""Extension option granting constraints, exercise gates, fee computation, and
calendar-month maturity arithmetic."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_statement,
    create_borrower,
    create_extension_option,
    create_extension_option_payload,
    create_loan,
    exercise_option,
    get_loan,
    get_success_data,
    make_borrower_headers,
    set_clock,
    set_payment_status,
    submit_statement,
    validate_error,
    validate_paginated,
    validate_success,
)

MS = TEST_USERS["master_servicer_headers"]

Q2_2026 = ("2026-04-01T00:00:00Z", "2026-06-30T00:00:00Z")


def _option_workspace(tax_id, loan_number, origination="2025-01-01T00:00:00Z",
                      maturity="2027-06-30T00:00:00Z", principal=100_000_000,
                      note_rate=0.05, **overrides):
    borrower = create_borrower(legal_name=f"{loan_number} Co", tax_id=tax_id,
                               contact_email=f"{tax_id.lower()}@x.com")
    loan = create_loan(borrower["id"], loan_number=loan_number,
                       original_principal_cents=principal, note_rate=note_rate,
                       origination_date=origination, maturity_date=maturity,
                       **overrides)
    return borrower, loan


def _option_status(api, loan_id, option_id):
    rows, _meta = validate_paginated(api.list_extension_options(loan_id, MS))
    for row in rows:
        if row["id"] == option_id:
            return row["status"]
    raise AssertionError(f"extension option {option_id} not found")


class TestOptionGrantConstraints:
    def test_extension_window_overlap_rejected(self, api):
        """PRD §3.7: "A loan carries at most two options — a third is refused with
        `ERR_MAX_OPTIONS_REACHED` (HTTP 422) — and overlapping closed windows or a
        duplicated sequence number on the same loan are refused with
        `ERR_EXTENSION_WINDOW_OVERLAP`."

        Design: Corner/validations/extension_window_overlap_rejected
        """
        _b, loan = _option_workspace("TX-WIN", "LN-WIN")
        create_extension_option(
            loan["id"], option_seq=1,
            exercise_window_start="2026-12-01T00:00:00Z",
            exercise_window_end="2027-01-31T00:00:00Z")
        # Closed intervals: [2027-01-15, 2027-03-01] overlaps [2026-12-01, 2027-01-31].
        resp = api.create_extension_option(
            loan["id"],
            create_extension_option_payload(
                option_seq=2, exercise_window_start="2027-01-15T00:00:00Z",
                exercise_window_end="2027-03-01T00:00:00Z"), MS)
        validate_error(resp, ApiErrorId.ERR_EXTENSION_WINDOW_OVERLAP)

    def test_max_two_extension_options_enforced(self, api):
        """PRD §3.7: "A loan carries at most two options — a third is refused with
        `ERR_MAX_OPTIONS_REACHED` (HTTP 422)"

        Design: Corner/validations/max_two_extension_options_enforced
        """
        _b, loan = _option_workspace("TX-MAX", "LN-MAX",
                                     maturity="2028-06-30T00:00:00Z")
        create_extension_option(
            loan["id"], option_seq=1,
            exercise_window_start="2026-12-01T00:00:00Z",
            exercise_window_end="2027-01-31T00:00:00Z")
        create_extension_option(
            loan["id"], option_seq=2,
            exercise_window_start="2027-02-01T00:00:00Z",
            exercise_window_end="2027-03-31T00:00:00Z", extension_months=6)
        # A third option fails on the count cap even with a disjoint window.
        resp = api.create_extension_option(
            loan["id"],
            create_extension_option_payload(
                option_seq=3, exercise_window_start="2027-04-01T00:00:00Z",
                exercise_window_end="2027-05-31T00:00:00Z", extension_months=6), MS)
        validate_error(resp, ApiErrorId.ERR_MAX_OPTIONS_REACHED)


class TestExerciseGates:
    def test_extension_seq2_before_seq1_rejected(self, api):
        """PRD §3.7: "an option with `option_seq` greater than 1 may be exercised
        only once the option with the preceding sequence number stands
        `EXERCISED` (else `ERR_EXTENSION_SEQUENCE_VIOLATION`)"
        PRD §2.10: "when several checks would fail at once, the error returned is
        the one belonging to the earliest failing check" — step 27 is "Extension
        sequencing — `ERR_EXTENSION_SEQUENCE_VIOLATION`" and step 30 is "Extension
        exercise window — `ERR_EXTENSION_WINDOW_CLOSED`".

        Design: Corner/validations/extension_seq2_before_seq1_rejected
        """
        borrower, loan = _option_workspace("TX-SEQ", "LN-SEQ")
        opt1 = create_extension_option(
            loan["id"], option_seq=1,
            exercise_window_start="2026-12-01T00:00:00Z",
            exercise_window_end="2027-01-31T00:00:00Z")
        opt2 = create_extension_option(
            loan["id"], option_seq=2,
            exercise_window_start="2027-02-01T00:00:00Z",
            exercise_window_end="2027-03-31T00:00:00Z", fee_pct=0.005)
        # The clock (2026-08-01) is also outside seq 2's window; the sequence
        # constraint (step 27) fires before the window check (step 30).
        resp = api.exercise_extension_option(
            opt2["id"], make_borrower_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_EXTENSION_SEQUENCE_VIOLATION)
        assert _option_status(api, loan["id"], opt1["id"]) == "AVAILABLE"
        assert _option_status(api, loan["id"], opt2["id"]) == "AVAILABLE"
        assert get_loan(loan["id"])["maturity_date"].startswith("2027-06-30")

    def test_exercise_before_window_opens_rejected(self, api):
        """PRD §3.7: "the clock must fall inside the inclusive window from
        `exercise_window_start` to `exercise_window_end` (else
        `ERR_EXTENSION_WINDOW_CLOSED`)."

        Design: Corner/validations/exercise_before_window_opens_rejected
        """
        borrower, loan = _option_workspace("TX-EAR", "LN-EAR")
        opt = create_extension_option(
            loan["id"], option_seq=1,
            exercise_window_start="2026-12-01T00:00:00Z",
            exercise_window_end="2027-03-01T00:00:00Z")
        resp = api.exercise_extension_option(
            opt["id"], make_borrower_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_EXTENSION_WINDOW_CLOSED)
        assert _option_status(api, loan["id"], opt["id"]) == "AVAILABLE"

    def test_exercise_expired_option_rejected(self, api):
        """PRD §3.7: "the clock sweep lapses an `AVAILABLE` option whose
        `exercise_window_end` has passed to `EXPIRED`"
        PRD §3.7: "`EXERCISED` and `EXPIRED` are terminal."
        PRD §3.7: "the option must stand `AVAILABLE` (else `ERR_INVALID_STATE`)"

        Design: Corner/state_machines/exercise_expired_option_rejected
        """
        borrower, loan = _option_workspace(
            "TX-LTX", "LN-LTX", origination="2026-08-01T00:00:00Z")
        opt = create_extension_option(
            loan["id"], option_seq=1,
            exercise_window_start="2026-08-15T00:00:00Z",
            exercise_window_end="2026-09-15T00:00:00Z")
        set_clock("2026-10-01T00:00:00Z")
        assert _option_status(api, loan["id"], opt["id"]) == "EXPIRED", (
            "the sweep lapses the AVAILABLE option past its window end")
        resp = api.exercise_extension_option(
            opt["id"], make_borrower_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestExerciseSuccess:
    def test_extension_maturity_month_end_clamp(self, api):
        """PRD §3.7: "Exercising records `exercised_fee_cents` — null until the
        option is exercised — equal to the loan's `current_balance_cents`
        multiplied by the option's `fee_pct`, rounded half-up to whole cents, and
        pushes the loan's `maturity_date` forward by `extension_months` calendar
        months — clamping the day of month to the target month's last day when
        that day does not exist there — advancing the loan's `version`."

        Design: Corner/calculations/extension_maturity_month_end_clamp
        """
        borrower, loan = _option_workspace(
            "TX-CLM", "LN-CLM", maturity="2027-01-31T00:00:00Z",
            principal=500_000_000)
        opt = create_extension_option(
            loan["id"], option_seq=1,
            exercise_window_start="2026-08-01T00:00:00Z",
            exercise_window_end="2026-11-30T00:00:00Z",
            extension_months=1, fee_pct=0)
        exercised = exercise_option(opt["id"], borrower["id"])
        assert exercised["status"] == "EXERCISED"
        assert exercised["exercised_fee_cents"] == 0
        # 2027-01-31 + 1 calendar month clamps to 2027-02-28 (2027 is no leap year).
        assert get_loan(loan["id"])["maturity_date"].startswith("2027-02-28")

    def test_exercise_blocked_while_loan_delinquent(self, api):
        """PRD §3.7: "Exercising is the borrower's act on its own loan, gated in
        pipeline order: the option must stand `AVAILABLE` (else
        `ERR_INVALID_STATE`); no `OPEN` covenant assessment may exist (else
        `ERR_OPEN_COVENANT_BREACH`); the loan must be `CURRENT` (else
        `ERR_LOAN_NOT_CURRENT`)"

        Design: Difficulty/cross_entity_state_dependency/extension_exercise_gated_by_loan_payment_and_covenant
        """
        borrower, loan = _option_workspace(
            "TX-GT1", "LN-GT1", principal=500_000_000, note_rate=0.06)
        opt = create_extension_option(
            loan["id"], option_seq=1,
            exercise_window_start="2026-08-01T00:00:00Z",
            exercise_window_end="2026-11-30T00:00:00Z", fee_pct=0.0025)
        set_payment_status(loan["id"], "DELINQUENT")
        resp = api.exercise_extension_option(
            opt["id"], make_borrower_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_LOAN_NOT_CURRENT)
        assert _option_status(api, loan["id"], opt["id"]) == "AVAILABLE"

    def test_exercise_after_cure_succeeds_with_fee_and_maturity_shift(self, api):
        """PRD §3.7: "Exercising records `exercised_fee_cents` — null until the
        option is exercised — equal to the loan's `current_balance_cents`
        multiplied by the option's `fee_pct`, rounded half-up to whole cents, and
        pushes the loan's `maturity_date` forward by `extension_months` calendar
        months — clamping the day of month to the target month's last day when
        that day does not exist there — advancing the loan's `version`."
        PRD §3.6: "either servicer role may set a `CURRENT` loan to `DELINQUENT`,
        return a `DELINQUENT` loan to `CURRENT`, or move a `DELINQUENT` loan to
        `DEFAULT`, each by naming a `to_status`."

        Design: Difficulty/cross_entity_state_dependency/extension_exercise_gated_by_loan_payment_and_covenant
        """
        borrower, loan = _option_workspace(
            "TX-GT1B", "LN-GT1B", principal=500_000_000, note_rate=0.06)
        opt = create_extension_option(
            loan["id"], option_seq=1,
            exercise_window_start="2026-08-01T00:00:00Z",
            exercise_window_end="2026-11-30T00:00:00Z", fee_pct=0.0025)
        set_payment_status(loan["id"], "DELINQUENT")
        validate_error(
            api.exercise_extension_option(opt["id"],
                                          make_borrower_headers(borrower["id"])),
            ApiErrorId.ERR_LOAN_NOT_CURRENT)
        set_payment_status(loan["id"], "CURRENT")
        exercised = exercise_option(opt["id"], borrower["id"])
        assert exercised["status"] == "EXERCISED"
        # round_half_up(500,000,000 x 0.0025) = 1,250,000.
        assert exercised["exercised_fee_cents"] == 1_250_000
        # 2027-06-30 + 12 calendar months.
        assert get_loan(loan["id"])["maturity_date"].startswith("2028-06-30")


class TestExerciseBreachPriority:
    def _setup_breached_loan_with_option(self, tax_id, loan_number):
        borrower, loan = _option_workspace(
            tax_id, loan_number, dscr_covenant_threshold=1.20,
            dscr_basis="T3_ANNUALIZED", principal=1_000_000_000, note_rate=0.06)
        # T3: 15,000,000 x 4 = 60,000,000 / 60,000,000 = 1.0000 < 1.20 -> OPEN.
        stmt = submit_statement(loan["id"], borrower["id"], "OPERATING_STATEMENT",
                                *Q2_2026, net_operating_income_cents=15_000_000)
        accept_statement(stmt["id"])
        opt = create_extension_option(
            loan["id"], option_seq=1,
            exercise_window_start="2026-12-01T00:00:00Z",
            exercise_window_end="2027-03-01T00:00:00Z", fee_pct=0.0025)
        return borrower, loan, opt

    def test_exercise_with_breach_and_closed_window_reports_breach(self, api):
        """PRD §2.10: "An extension exercise attempted with an open covenant
        breach and a closed window reports `ERR_OPEN_COVENANT_BREACH`, because
        step 9 precedes step 30."

        Design: Difficulty/priority_pair_validation_conflict/exercise_breach_safety_beats_window_temporal
        """
        borrower, _loan, opt = self._setup_breached_loan_with_option(
            "TX-PR2", "LN-PR2")
        # The 2026-08-01 clock is also before the 2026-12-01 window start; the
        # open-breach safety check (step 9) is reported before the temporal one.
        resp = api.exercise_extension_option(
            opt["id"], make_borrower_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_OPEN_COVENANT_BREACH)
        body = resp.json()
        assert body["data"]["error_id"] != "ERR_EXTENSION_WINDOW_CLOSED"

    def test_blocked_exercise_leaves_option_and_maturity_unchanged(self, api):
        """PRD §2.10: "An extension exercise attempted with an open covenant
        breach and a closed window reports `ERR_OPEN_COVENANT_BREACH`, because
        step 9 precedes step 30."
        PRD §3.7: "Exercising records `exercised_fee_cents` — null until the
        option is exercised"

        Design: Difficulty/priority_pair_validation_conflict/exercise_breach_safety_beats_window_temporal
        """
        borrower, loan, opt = self._setup_breached_loan_with_option(
            "TX-PR2B", "LN-PR2B")
        resp = api.exercise_extension_option(
            opt["id"], make_borrower_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_OPEN_COVENANT_BREACH)
        assert _option_status(api, loan["id"], opt["id"]) == "AVAILABLE", (
            "a blocked exercise never transitions the option")
        assert get_loan(loan["id"])["maturity_date"].startswith("2027-06-30")

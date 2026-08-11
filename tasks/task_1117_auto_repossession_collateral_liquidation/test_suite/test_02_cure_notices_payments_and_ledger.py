"""Right-to-cure notices, cure payments, OCC on case documents, and the
append-only recovery ledger."""
from test_helpers import (
    ApiErrorId,
    assert_ledger_entry,
    create_borrower,
    create_loan,
    issue_cure_notice,
    list_cure_notices,
    list_ledger_entries,
    make_borrower_headers,
    open_case,
    parse_instant,
    post_cost,
    rm_headers,
    set_clock,
    setup_case_cure_expired,
    setup_case_cure_pending,
    validate_error,
    validate_success,
)


class TestLedgerEntries:
    def test_ledger_entries_are_immutable(self, api):
        """PRD §2.4: "A `RecoveryLedgerEntry` is append-only: it carries `id`
        and `created_at` and nothing else from the standard set — `updated_at`
        and `version` are absent, and no endpoint updates or deletes a ledger
        entry."

        Design: Corner/entities/ledger_entries_are_immutable
        """
        borrower = create_borrower(full_name="IM", email="im@x.com")
        loan = create_loan(borrower["id"], vin="VIN00000000000044",
                           principal_balance_cents=500_000, apr_bps=900,
                           monthly_payment_cents=20_000, missed_installments=2,
                           accrued_interest_cents=8_000, late_fees_cents=3_000)
        case = open_case(loan["id"])
        resp = api.create_ledger_entry(
            case["id"], {"kind": "COST_KEY", "amount_cents": 7_500, "memo": "key cut"},
            rm_headers())
        entry = validate_success(resp, expected_status=201)
        assert_ledger_entry(entry)
        entries = validate_success(api.list_ledger_entries(case["id"], rm_headers()))
        assert len(entries) == 1
        assert entries[0]["id"] == entry["id"]
        assert entries[0]["kind"] == "COST_KEY"
        assert entries[0]["amount_cents"] == 7_500

    def test_ledger_manual_payment_kind_rejected(self, api):
        """PRD §2.10: "Manual posting by a `RecoveryManager` accepts only the
        cost and adjustment kinds — `COST_REPO_FEE`, `COST_STORAGE`,
        `COST_TRANSPORT`, `COST_KEY`, `COST_OTHER`, and `ADJUSTMENT` — each of
        which increases the borrower-owed costs of the case. The remaining kinds
        are written exclusively by system transitions: `PAYMENT` when borrower
        money arrives, `REVERSAL` when a prior entry is undone, and `REFUND`
        when a surplus is paid out."

        Design: Corner/entities/ledger_manual_payment_kind_rejected
        """
        borrower = create_borrower(full_name="LK", email="lk@x.com")
        loan = create_loan(borrower["id"], vin="VIN00000000000045",
                           principal_balance_cents=500_000, apr_bps=900,
                           monthly_payment_cents=20_000, missed_installments=2,
                           accrued_interest_cents=8_000, late_fees_cents=3_000)
        case = open_case(loan["id"])
        resp = api.create_ledger_entry(
            case["id"], {"kind": "PAYMENT", "amount_cents": 100}, rm_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestCureNoticeSupersession:
    def test_second_cure_notice_supersedes_and_resets_deadline(self, api):
        """PRD §3.2: "the prior `SENT` notice transitions to `SUPERSEDED` with
        its `superseded_by_id` set to the new notice, the replacement is created
        in `SENT` carrying a freshly computed `cure_amount_cents`, the case's
        `cure_deadline` is recomputed as the new `sent_at` plus fourteen days,
        `current_cure_notice_id` is repointed, and the case `version` increments
        again."

        Design: Corner/state_machines/second_cure_notice_supersedes_and_resets_deadline
        """
        ctx = setup_case_cure_pending(
            costs=[("COST_REPO_FEE", 35_000), ("COST_STORAGE", 4_500)],
            borrower_overrides={"full_name": "RN", "email": "rn@x.com"},
            loan_overrides={"vin": "VIN00000000000053"})
        case = ctx["case"]
        notice1 = ctx["notice"]
        # First snapshot: 3 x 45,000 + 12,000 + 39,500 = 186,500c.
        assert notice1["cure_amount_cents"] == 186_500

        set_clock("2026-05-03T00:00:00Z")
        post_cost(case["id"], "COST_KEY", 5_000)
        notice2 = issue_cure_notice(case["id"])
        # Recomputed from the current ledger: 186,500 + 5,000 = 191,500c.
        assert notice2["cure_amount_cents"] == 191_500
        assert notice2["status"] == "SENT"

        notices = {n["id"]: n for n in list_cure_notices(case["id"])}
        assert notices[notice1["id"]]["status"] == "SUPERSEDED"
        assert notices[notice1["id"]]["superseded_by_id"] == notice2["id"]

        case_after = api.get_recovery_case(case["id"], rm_headers())
        case_after = validate_success(case_after)
        assert case_after["status"] == "CURE_PENDING"
        assert case_after["current_cure_notice_id"] == notice2["id"]
        # New notice sent 2026-05-03 -> deadline reset to 2026-05-17.
        assert parse_instant(case_after["cure_deadline"]) == parse_instant("2026-05-17T00:00:00Z")


class TestCurePayments:
    def test_cure_payment_insufficient_in_window(self, api):
        """PRD §3.2: "the payment must be at least the live notice's
        `cure_amount_cents`, else the request fails with
        `ERR_PAYMENT_INSUFFICIENT` (HTTP 422)."

        Design: Corner/validations/cure_payment_insufficient_in_window
        """
        ctx = setup_case_cure_pending(
            borrower_overrides={"full_name": "IP", "email": "ip@x.com"},
            loan_overrides={"vin": "VIN00000000000060",
                            "principal_balance_cents": 500_000, "apr_bps": 900,
                            "monthly_payment_cents": 20_000, "missed_installments": 2,
                            "accrued_interest_cents": 8_000, "late_fees_cents": 3_000})
        case = ctx["case"]
        assert ctx["notice"]["cure_amount_cents"] == 43_000  # 2 x 20,000 + 3,000, no costs
        set_clock("2026-05-02T00:00:00Z")  # in-window (deadline 2026-05-15)
        resp = api.create_cure_payment(
            case["id"], {"amount_cents": 42_999},
            make_borrower_headers(ctx["borrower"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PAYMENT_INSUFFICIENT)
        entries = validate_success(api.list_ledger_entries(case["id"], rm_headers()))
        assert entries == [], "a rejected payment writes no ledger entry"
        case_after = validate_success(api.get_recovery_case(case["id"], rm_headers()))
        assert case_after["status"] == "CURE_PENDING"

    def test_assignment_rejected_before_cure_expiry(self, api):
        """PRD §3.3: "Assignment creation is a `RecoveryManager` act on a case
        standing in `CURE_EXPIRED` or `REPO_ACTIVE` — provided no assignment of
        that case is currently `ASSIGNED` or `ACCEPTED`; otherwise the create is
        rejected with `ERR_INVALID_CASE_STATE`."

        Design: Corner/state_machines/assignment_rejected_before_cure_expiry
        """
        ctx = setup_case_cure_pending(
            borrower_overrides={"full_name": "IV", "email": "iv@x.com"},
            loan_overrides={"vin": "VIN00000000000048"})
        case = ctx["case"]
        agent_resp = api.create_repo_agent(
            {"name": "Agent N", "license_number": "LIC-N",
             "licensed_state_codes": ["CA"], "max_active_assignments": 5},
            rm_headers())
        agent = validate_success(agent_resp, expected_status=201)
        resp = api.create_repo_assignment(
            case["id"],
            {"agent_id": agent["id"],
             "field_window_start": "2026-05-02T00:00:00Z",
             "field_window_end": "2026-05-03T00:00:00Z"},
            rm_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_CASE_STATE)
        assignments = validate_success(api.list_case_assignments(case["id"], rm_headers()))
        assert assignments == []


class TestCureNoticeOCC:
    def test_cure_notice_occ_stale_version(self, api):
        """PRD §2.8: "If the case's current `version` does not match — because
        another write has advanced the case since the client's last read — the
        request is rejected with `ERR_STALE_VERSION` (HTTP 412), and nothing is
        created or superseded. Supersession is a legitimate product operation,
        so no state-field check would ever catch a second sequential create; the
        version check is the only guard protecting a client from superseding a
        notice or quote it never saw."

        Design: Corner/complexity_layers/cure_notice_occ_stale_version
        """
        borrower = create_borrower(full_name="OC", email="oc@x.com")
        loan = create_loan(borrower["id"], vin="VIN00000000000072",
                           principal_balance_cents=500_000, apr_bps=900,
                           monthly_payment_cents=20_000, missed_installments=2,
                           accrued_interest_cents=8_000, late_fees_cents=3_000)
        case = open_case(loan["id"])
        version_at_open = case["version"]

        first = api.create_cure_notice(
            case["id"], {"expected_recovery_case_version": version_at_open}, rm_headers())
        notice1 = validate_success(first, expected_status=201)

        replay = api.create_cure_notice(
            case["id"], {"expected_recovery_case_version": version_at_open}, rm_headers())
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)

        case_after = validate_success(api.get_recovery_case(case["id"], rm_headers()))
        assert case_after["version"] == version_at_open + 1

        retry = api.create_cure_notice(
            case["id"],
            {"expected_recovery_case_version": case_after["version"]},
            rm_headers())
        notice2 = validate_success(retry, expected_status=201)
        notices = {n["id"]: n for n in list_cure_notices(case["id"])}
        assert notices[notice2["id"]]["status"] == "SENT"
        assert notices[notice1["id"]]["status"] == "SUPERSEDED"


class TestStateBeatsFiscalOnCurePayment:
    """Priority pair: state tier (PRD §2.7 step 5) is evaluated before fiscal
    sufficiency (step 9)."""

    def _expired_case(self, vin):
        ctx = setup_case_cure_expired(
            borrower_overrides={"full_name": "SF", "email": "sf@x.com"},
            loan_overrides={"vin": vin})
        # Case auto-transitioned to CURE_EXPIRED when the clock passed the
        # 2026-05-15 deadline; cure amount is 186,500c.
        assert ctx["case"]["status"] == "CURE_EXPIRED"
        return ctx

    def test_state_beats_fiscal_on_cure_payment_error_id(self, api):
        """PRD §3.2: "Two guards apply in cascade order: the case must stand in
        `CURE_PENDING` (a state-tier rejection with `ERR_INVALID_CASE_STATE`),
        and only then is sufficiency judged — the payment must be at least the
        live notice's `cure_amount_cents`, else the request fails with
        `ERR_PAYMENT_INSUFFICIENT` (HTTP 422)."
        PRD §3.2: "A payment attempted after the deadline therefore always
        observes `CURE_EXPIRED` and fails the state guard rather than the
        clock."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_cure_payment
        """
        ctx = self._expired_case("VIN00000000000016")
        # 1c violates BOTH the state gate (case CURE_EXPIRED) and the fiscal
        # floor (1 < 186,500c): the state tier must win.
        resp = api.create_cure_payment(
            ctx["case"]["id"], {"amount_cents": 1},
            make_borrower_headers(ctx["borrower"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_CASE_STATE)

    def test_state_beats_fiscal_on_cure_payment_writes_nothing(self, api):
        """PRD §2.7: "Every mutating request passes through a fixed validation
        cascade, and the first failing check wins — later checks are never
        evaluated for a rejected request."
        PRD §3.2: "A full in-window payment writes a `PAYMENT` ledger entry for
        the paid `amount_cents` ... and restores the loan from `IN_DEFAULT` to
        `CURRENT`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_cure_payment
        """
        ctx = self._expired_case("VIN0000000000016B")
        resp = api.create_cure_payment(
            ctx["case"]["id"], {"amount_cents": 1},
            make_borrower_headers(ctx["borrower"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_CASE_STATE)
        # The costs posted before the notice are the only ledger rows.
        entries = list_ledger_entries(ctx["case"]["id"])
        assert [e["kind"] for e in entries] == ["COST_REPO_FEE", "COST_STORAGE"]
        case_after = validate_success(api.get_recovery_case(ctx["case"]["id"], rm_headers()))
        assert case_after["status"] == "CURE_EXPIRED"
        notices = list_cure_notices(ctx["case"]["id"])
        assert notices[0]["status"] == "EXPIRED"


class TestCurePaymentDeadlineBoundary:
    """Boundary precision on the cure deadline: in-window means now <=
    cure_deadline; one second past it the clock has already expired the case."""

    def test_cure_payment_exactly_at_deadline_cures(self, api):
        """PRD §2.5: "Cure notices whose deadline has passed move from `SENT` to
        `EXPIRED` first, and only then do their cases move from `CURE_PENDING`
        to `CURE_EXPIRED`."
        PRD §3.2: "A full in-window payment writes a `PAYMENT` ledger entry for
        the paid `amount_cents`, increments the loan's `paid_to_date_cents` by
        the same amount (incrementing the loan's `version`), moves the current
        notice to `CURED`, moves the case to `CURED`, and restores the loan from
        `IN_DEFAULT` to `CURRENT`."

        Design: Difficulty/boundary_precision_check/cure_payment_exactly_at_deadline
        """
        ctx = setup_case_cure_pending(
            costs=[("COST_REPO_FEE", 35_000), ("COST_STORAGE", 4_500)],
            borrower_overrides={"full_name": "T1", "email": "t1@x.com"},
            loan_overrides={"vin": "VIN00000000000021"})
        case = ctx["case"]
        # At exactly the deadline the notice's deadline has not "passed".
        set_clock("2026-05-15T00:00:00Z")
        resp = api.create_cure_payment(
            case["id"], {"amount_cents": 186_500},
            make_borrower_headers(ctx["borrower"]["id"]))
        entry = validate_success(resp, expected_status=201)
        assert entry["kind"] == "PAYMENT"
        assert entry["amount_cents"] == 186_500
        case_after = validate_success(api.get_recovery_case(case["id"], rm_headers()))
        assert case_after["status"] == "CURED"
        loan_after = validate_success(api.get_loan_account(ctx["loan"]["id"], rm_headers()))
        assert loan_after["status"] == "CURRENT"
        assert loan_after["paid_to_date_cents"] == 186_500
        notice_after = [n for n in list_cure_notices(case["id"])][0]
        assert notice_after["status"] == "CURED"

    def test_cure_payment_one_second_after_deadline_fails_state(self, api):
        """PRD §3.2: "Note that the moment the logical clock passes
        `cure_deadline`, the automatic transition of §2.5 fires: the live notice
        moves from `SENT` to `EXPIRED` and the case from `CURE_PENDING` to
        `CURE_EXPIRED`. A payment attempted after the deadline therefore always
        observes `CURE_EXPIRED` and fails the state guard rather than the
        clock."

        Design: Difficulty/boundary_precision_check/cure_payment_exactly_at_deadline
        """
        ctx = setup_case_cure_pending(
            costs=[("COST_REPO_FEE", 35_000), ("COST_STORAGE", 4_500)],
            borrower_overrides={"full_name": "T2", "email": "t2@x.com"},
            loan_overrides={"vin": "VIN00000000000022"})
        case = ctx["case"]
        # One second past the deadline: the clock-set eagerly expires the case.
        set_clock("2026-05-15T00:00:01Z")
        resp = api.create_cure_payment(
            case["id"], {"amount_cents": 186_500},
            make_borrower_headers(ctx["borrower"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_CASE_STATE)
        case_after = validate_success(api.get_recovery_case(case["id"], rm_headers()))
        assert case_after["status"] == "CURE_EXPIRED"
        notice_after = [n for n in list_cure_notices(case["id"])][0]
        assert notice_after["status"] == "EXPIRED"

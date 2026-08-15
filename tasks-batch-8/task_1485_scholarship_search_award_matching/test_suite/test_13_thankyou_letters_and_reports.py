"""Thank-you letters, donor reports, and the disbursement confirm cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equal,
    create_report,
    get_award,
    get_fund,
    get_letter_for_award,
    get_report,
    get_success_data,
    list_letters,
    make_donor_headers,
    make_student_headers,
    send_and_confirm,
    set_clock,
    setup_accepted_award,
    setup_fully_disbursed_award,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestThankYouLetterLifecycle:
    def test_revision_loop_and_delivery(self, api):
        """PRD §3.9: "The student submits content — the caller's `X-User-ID`
        must equal the award's `student_id` (otherwise
        `ERR_FORBIDDEN_OWNERSHIP`) and a `content_ref` must be present
        (otherwise `ERR_VALIDATION`) — moving the letter from `REQUIRED` or
        `REVISION_REQUESTED` to `SUBMITTED`. A coordinator may then request a
        revision (`SUBMITTED` → `REVISION_REQUESTED`, the revision cycle),
        approve the letter (`SUBMITTED` → `APPROVED`), and finally deliver it
        (`APPROVED` → `DELIVERED`)".
        PRD §3.9: "Stewardship begins the moment an award is fully disbursed:
        the disbursement cascade of §3.7 auto-creates a thank-you letter for
        the award when none exists yet — letters are only ever
        cascade-created, so `auto_created` is always true — with `status`
        `REQUIRED`".

        Design: Corner/state_machines/tyl_revision_loop_and_delivery
        """
        ctx = setup_fully_disbursed_award(amount_cents=300000)
        letter = get_letter_for_award(ctx["award"]["id"])
        assert letter["status"] == "REQUIRED"
        assert letter["auto_created"] is True

        student_headers = make_student_headers(ctx["students"][0]["id"])
        submitted = validate_success(
            api.submit_letter(
                letter["id"], {"content_ref": "s3://letters/v1.pdf"},
                student_headers,
            )
        )
        assert submitted["status"] == "SUBMITTED"

        revision = validate_success(api.request_revision(letter["id"], COORD))
        assert revision["status"] == "REVISION_REQUESTED"

        resubmitted = validate_success(
            api.submit_letter(
                letter["id"], {"content_ref": "s3://letters/v2.pdf"},
                student_headers,
            )
        )
        assert resubmitted["status"] == "SUBMITTED", "revision cycle traversed"

        approved = validate_success(api.approve_letter(letter["id"], COORD))
        assert approved["status"] == "APPROVED"
        delivered = validate_success(api.deliver_letter(letter["id"], COORD))
        assert delivered["status"] == "DELIVERED"

    def test_auto_waived_for_anonymous_donor(self, api):
        """PRD §3.9: "with `status` `REQUIRED`, or `WAIVED` at creation when
        the program's donor is anonymous".
        PRD §3.1: "Anonymity has teeth — when `anonymous` is true, thank-you
        letters are waived and reports omit recipient identity".

        Design: Corner/state_machines/tyl_auto_waived_for_anonymous_donor
        """
        ctx = setup_fully_disbursed_award(
            amount_cents=300000,
            donor_overrides={"anonymous": True},
        )
        letter = get_letter_for_award(ctx["award"]["id"])
        assert letter["status"] == "WAIVED", (
            "anonymous donor skips the student-letter requirement"
        )
        assert letter["auto_created"] is True

    def test_waive_non_anonymous_rejected(self, api):
        """PRD §3.9: "A coordinator may instead waive a `REQUIRED` letter, but
        only when the program's donor is anonymous — otherwise the waive is
        refused with `ERR_TYL_NOT_WAIVABLE`."

        Design: Corner/state_machines/tyl_waive_non_anonymous_rejected
        """
        ctx = setup_fully_disbursed_award(amount_cents=300000)
        letter = get_letter_for_award(ctx["award"]["id"])
        assert letter["status"] == "REQUIRED"

        resp = api.waive_letter(letter["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_TYL_NOT_WAIVABLE)
        current = validate_success(api.get_letter(letter["id"], COORD))
        assert current["status"] == "REQUIRED"


class TestDonorReportFlow:
    def _setup_report(self, api, amount_cents=300000):
        """FULLY_DISBURSED award (letter still REQUIRED) + GENERATED report
        over a covering window."""
        ctx = setup_fully_disbursed_award(amount_cents=amount_cents)
        report = create_report(ctx["donor"]["id"])
        generated = validate_success(api.generate_report(report["id"], COORD))
        return ctx, generated

    def test_send_blocked_until_thank_you_complete_then_full_loop(self, api):
        """PRD §3.9: "Sending requires the report to be `GENERATED`
        (otherwise `ERR_INVALID_STATE`) and `thank_you_complete` to be true —
        a report whose covered letters are not all delivered or waived is
        refused with `ERR_REPORT_INCOMPLETE`; a successful send moves the
        report to `SENT` and stamps `sent_at`."
        PRD §3.9: "delivery reverts every covered donor report in `GENERATED`
        back to `DRAFT` for a staleness recompute."
        PRD §3.9: "the donor — and only that donor, with `X-User-ID` equal to
        the report's `donor_id` (otherwise `ERR_FORBIDDEN_OWNERSHIP`) — moves
        the report from `SENT` to `ACKNOWLEDGED`, its terminal state."
        PRD §3.9: "`thank_you_complete` is true exactly when every included
        award's letter sits in `DELIVERED` or `WAIVED`."

        Design: Corner/state_machines/report_send_blocked_until_thankyou_complete
        """
        ctx, generated = self._setup_report(api)
        assert generated["status"] == "GENERATED"
        assert generated["total_awards_count"] == 1
        assert generated["thank_you_complete"] is False, "letter still REQUIRED"

        resp = api.send_report(generated["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_REPORT_INCOMPLETE)

        letter = get_letter_for_award(ctx["award"]["id"])
        student_headers = make_student_headers(ctx["students"][0]["id"])
        get_success_data(
            api.submit_letter(
                letter["id"], {"content_ref": "s3://letters/r.pdf"},
                student_headers,
            )
        )
        get_success_data(api.approve_letter(letter["id"], COORD))
        get_success_data(api.deliver_letter(letter["id"], COORD))

        stale = get_report(generated["id"])
        assert stale["status"] == "DRAFT", "delivery reverted GENERATED -> DRAFT"

        regenerated = validate_success(api.generate_report(generated["id"], COORD))
        assert regenerated["thank_you_complete"] is True
        sent = validate_success(api.send_report(generated["id"], COORD))
        assert sent["status"] == "SENT"
        assert sent["sent_at"] is not None

        acknowledged = validate_success(
            api.acknowledge_report(
                generated["id"], make_donor_headers(ctx["donor"]["id"])
            )
        )
        assert acknowledged["status"] == "ACKNOWLEDGED"

    def test_report_period_half_open_excludes_end(self, api):
        """PRD §3.9: "The included awards are those whose application's
        program belongs to the report's donor and that hold at least one
        `CONFIRMED` disbursement whose `confirmed_at` falls inside the
        half-open window, where a confirmation exactly at `period_end` is
        excluded. `total_awards_count` counts those awards;
        `total_disbursed_cents` sums their in-window confirmed amounts; and
        `thank_you_complete` is true exactly when every included award's
        letter sits in `DELIVERED` or `WAIVED`."

        Design: Corner/calculations/calc_report_period_half_open_excludes_end
        """
        ctx = setup_accepted_award(
            amount_cents=600000, term_count=2,
            program_overrides={"program_type": "NEED",
                               "award_amount_cents": 600000},
        )
        disb_1, disb_2 = ctx["disbursements"]
        # Confirm term 1 at the default clock (2026-08-01).
        send_and_confirm(disb_1["id"])
        # Confirm term 2 at exactly 2027-08-01 — report 1's period_end.
        set_clock("2027-08-01T00:00:00Z")
        confirmed_2 = send_and_confirm(disb_2["id"])
        assert_instant_equal(
            confirmed_2["confirmed_at"], "2027-08-01T00:00:00Z",
            "term-2 confirmed_at",
        )

        report_1 = create_report(
            ctx["donor"]["id"], period_start="2026-08-01", period_end="2027-08-01"
        )
        generated_1 = validate_success(api.generate_report(report_1["id"], COORD))
        assert generated_1["total_disbursed_cents"] == 300000, (
            "confirmation exactly at period_end is excluded (half-open)"
        )
        assert generated_1["total_awards_count"] == 1

        report_2 = create_report(
            ctx["donor"]["id"], period_start="2026-08-01", period_end="2027-08-02"
        )
        generated_2 = validate_success(api.generate_report(report_2["id"], COORD))
        assert generated_2["total_disbursed_cents"] == 600000, (
            "one day further includes the second confirmation"
        )
        assert generated_2["total_awards_count"] == 1, (
            "the award is counted once despite two in-window disbursements"
        )


class TestConfirmToDonorReportStaleness:
    """Depth-3 cascade from ONE disbursement confirm."""

    def _setup(self, api):
        """2-term award with disb_1 confirmed and a GENERATED report over a
        covering window; returns (ctx, disb_2, report)."""
        ctx = setup_accepted_award(
            amount_cents=600000, term_count=2,
            student_overrides={"household_income_cents": 3000000},
            program_overrides={"program_type": "NEED",
                               "award_amount_cents": 600000},
            fund_overrides={"committed_cents": 10000000},
        )
        disb_1, disb_2 = ctx["disbursements"]
        send_and_confirm(disb_1["id"])
        report = create_report(ctx["donor"]["id"])
        generated = validate_success(api.generate_report(report["id"], COORD))
        assert generated["total_awards_count"] == 1
        assert generated["total_disbursed_cents"] == 300000
        return ctx, disb_2, generated

    def test_confirm_fully_disburses_and_creates_letter(self, api):
        """PRD §3.7: "when the net confirmed amount reaches `amount_cents` the
        award moves `DISBURSING` → `FULLY_DISBURSED`. Reaching
        `FULLY_DISBURSED` fires the cascade's second and third links: a
        thank-you letter is auto-created for the award when none exists yet
        (§3.9)".
        PRD §3.9: "with `status` `REQUIRED`, or `WAIVED` at creation when the
        program's donor is anonymous, and a `due_at` thirty days after the
        full-disbursement timestamp."

        Design: Difficulty/transitive_cascade/disbursement_confirm_to_donor_report_staleness
        """
        ctx, disb_2, _ = self._setup(api)
        award_id = ctx["award"]["id"]
        mid = get_award(award_id)
        assert mid["funding_status"] == "DISBURSING", "first confirm moved it"

        set_clock("2027-02-01T00:00:00Z")
        send_and_confirm(disb_2["id"])

        award = get_award(award_id)
        assert award["funding_status"] == "FULLY_DISBURSED"

        letters, meta = list_letters({"award_id": award_id})
        assert meta["total_count"] == 1, "exactly one letter auto-created"
        letter = letters[0]
        assert letter["status"] == "REQUIRED", "donor is not anonymous"
        assert letter["auto_created"] is True

    def test_confirm_marks_generated_report_stale_and_updates_fund(self, api):
        """PRD §3.7: "Reaching `FULLY_DISBURSED` fires the cascade's second
        and third links: a thank-you letter is auto-created for the award
        when none exists yet (§3.9), and every donor report of that donor
        currently in `GENERATED` reverts to `DRAFT` for regeneration."
        PRD §3.7: "the fund's `disbursed_cents` grows by the confirmed amount,
        the fund's `reserved_cents` is recomputed".
        PRD §2.9: "`available_cents` equals `committed_cents` minus
        `reserved_cents` minus `disbursed_cents` plus `returned_cents`."

        Design: Difficulty/transitive_cascade/disbursement_confirm_to_donor_report_staleness
        """
        ctx, disb_2, report = self._setup(api)
        assert get_report(report["id"])["status"] == "GENERATED"

        set_clock("2027-02-01T00:00:00Z")
        send_and_confirm(disb_2["id"])

        stale = get_report(report["id"])
        assert stale["status"] == "DRAFT", (
            "the letter creation / newly confirmed disbursement marked the "
            "GENERATED report stale"
        )

        fund = get_fund(ctx["fund"]["id"])
        assert fund["disbursed_cents"] == 600000
        assert fund["reserved_cents"] == 0, "net confirmed reaches the amount"
        assert fund["available_cents"] == 10000000 - 0 - 600000 + 0

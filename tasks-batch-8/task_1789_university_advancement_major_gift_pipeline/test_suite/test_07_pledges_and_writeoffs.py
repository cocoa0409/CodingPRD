"""Pledges: schedule generation, reminders, overdue sweep, write-offs, and the
pledge's own status re-evaluation."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    setup_active_pledge, setup_executed_agreement,
    create_pledge_for, create_write_off_payload,
    get_pledge, list_installments, set_clock,
    assert_iso_instant_equal,
)

DIR = TEST_USERS["director_headers"]
DIR2 = TEST_USERS["director2_headers"]
DRO = TEST_USERS["dro_headers"]
FIN = TEST_USERS["finance_headers"]


class TestInstallmentSchedule:
    def test_installment_schedule_rounding_and_month_end_clamp(self, api):
        """PRD §3.6: "The base installment amount is the `total_amount_cents`
        divided by the `installment_count`, rounded down to a whole cent; the
        remainder — the total minus the base times the count — is distributed one
        extra cent to each of the earliest-due installments, so installment 1
        absorbs first."
        PRD §3.6: "a `due_date` computed by advancing `first_due_date` by one
        `frequency` step per preceding installment — one calendar month for
        `MONTHLY`, three for `QUARTERLY`, one year for `ANNUAL` — with the day of
        month clamped to the last day of the target month, so a January 31 start
        with monthly frequency lands on February 28 or 29."
        PRD §3.6: "the pledge's `outstanding_cents` — the sum over installments
        of each installment's `amount_cents` minus its `paid_cents` minus its
        `written_off_cents` — equals `total_amount_cents` at creation."

        Design: Corner/calculations/installment_schedule_rounding_and_month_end_clamp
        """
        ctx = setup_active_pledge(
            100, installment_count=3, frequency="MONTHLY",
            first_due_date="2026-01-31T00:00:00Z",
        )
        rows = list_installments(ctx["pledge"]["id"])
        assert len(rows) == 3
        # base 33, remainder 1 front-loaded to the earliest-due installment
        assert [r["amount_cents"] for r in rows] == [34, 33, 33]
        assert_iso_instant_equal(rows[0]["due_date"], "2026-01-31T00:00:00Z")
        assert_iso_instant_equal(rows[1]["due_date"], "2026-02-28T00:00:00Z")  # 2026 is not a leap year
        assert_iso_instant_equal(rows[2]["due_date"], "2026-03-31T00:00:00Z")
        assert get_pledge(ctx["pledge"]["id"])["outstanding_cents"] == 100


class TestReminders:
    def test_reminder_limit_boundary_at_three(self, api):
        """PRD §3.6: "A `DonorRelationsOfficer` may send a reminder for an
        installment in `SCHEDULED`, `REMINDED`, or `OVERDUE` status — a `PAID` or
        `WRITTEN_OFF` installment rejects with `ERR_INSTALLMENT_NOT_REMINDABLE` —
        provided `reminder_count` is still below the system maximum of 3; a third
        reminder already sent means the next attempt fails with
        `ERR_REMINDER_LIMIT_EXCEEDED`."

        Design: Corner/state_machines/reminder_limit_boundary_at_three
        """
        ctx = setup_active_pledge(100, installment_count=1, frequency="MONTHLY",
                                  first_due_date="2026-12-01T00:00:00Z")
        inst = list_installments(ctx["pledge"]["id"])[0]

        validate_success(api.remind_installment(inst["id"], DRO))
        validate_success(api.remind_installment(inst["id"], DRO))
        d3 = validate_success(api.remind_installment(inst["id"], DRO))
        assert d3["reminder_count"] == 3
        assert d3["status"] == "REMINDED"

        resp = api.remind_installment(inst["id"], DRO)
        validate_error(resp, ApiErrorId.ERR_REMINDER_LIMIT_EXCEEDED)


class TestOverdueSweep:
    def test_installment_overdue_boundary_strict_greater(self, api):
        """PRD §3.6: "the clock sweep moves a `SCHEDULED` or `REMINDED`
        installment to `OVERDUE` once the current logical time is strictly later
        than the installment's `due_date` plus 30 days; an installment exactly 30
        days past due is not yet overdue."

        Design: Corner/state_machines/installment_overdue_boundary_strict_greater
        """
        ctx = setup_active_pledge(300, installment_count=3, frequency="MONTHLY",
                                  first_due_date="2026-08-05T00:00:00Z")
        pl_id = ctx["pledge"]["id"]

        # 2026-09-04 is exactly due_date + 30 days for installment 1: not overdue.
        set_clock("2026-09-04T00:00:00Z")
        rows = list_installments(pl_id)
        assert rows[0]["status"] == "SCHEDULED"

        # One day later: strictly past the grace period.
        set_clock("2026-09-05T00:00:00Z")
        rows = list_installments(pl_id)
        assert rows[0]["status"] == "OVERDUE"
        assert rows[1]["status"] == "SCHEDULED"
        assert rows[2]["status"] == "SCHEDULED"


class TestWriteOffs:
    def test_writeoff_reject_leaves_pledge_untouched(self, api):
        """PRD §3.6: "Rejection simply closes the request as `REJECTED` with
        `decided_by` recorded."

        Design: Corner/state_machines/writeoff_reject_leaves_pledge_untouched
        """
        ctx = setup_active_pledge(100, installment_count=1, frequency="MONTHLY",
                                  first_due_date="2026-12-01T00:00:00Z")
        pl_id = ctx["pledge"]["id"]
        resp = api.create_write_off(pl_id, create_write_off_payload(amount_cents=100, reason="DONOR_HARDSHIP"), FIN)
        wo = validate_success(resp, expected_status=201)

        d = validate_success(api.review_write_off(
            wo["id"], {"decision": "REJECT", "review_rationale": "insufficient documentation"}, DIR,
        ))
        assert d["status"] == "REJECTED"
        assert d["decided_by"] == "dir-1"

        pledge = get_pledge(pl_id)
        assert pledge["status"] == "ACTIVE"
        assert pledge["outstanding_cents"] == 100
        assert pledge["written_off_cents"] == 0

    def test_writeoff_review_of_decided_writeoff_rejected(self, api):
        """PRD §3.6: "a write-off no longer `PENDING` rejects review with
        `ERR_WRITE_OFF_NOT_PENDING`."

        Design: Corner/state_machines/writeoff_review_of_decided_writeoff_rejected
        """
        ctx = setup_active_pledge(100, installment_count=1, frequency="ANNUAL",
                                  first_due_date="2026-12-01T00:00:00Z")
        pl_id = ctx["pledge"]["id"]
        resp = api.create_write_off(pl_id, create_write_off_payload(amount_cents=50, reason="DUPLICATE"), FIN)
        wo = validate_success(resp, expected_status=201)
        validate_success(api.review_write_off(wo["id"], {"decision": "REJECT"}, DIR))

        resp = api.review_write_off(wo["id"], {"decision": "APPROVE"}, DIR2)
        validate_error(resp, ApiErrorId.ERR_WRITE_OFF_NOT_PENDING)

        rows, _ = validate_paginated(api.list_write_offs(pl_id, FIN))
        assert rows[0]["status"] == "REJECTED"

    def test_writeoff_over_outstanding_rejected(self, api):
        """PRD §3.6: "the amount must not exceed the pledge's `outstanding_cents`
        at request time (`ERR_WRITE_OFF_EXCEEDS_OUTSTANDING`)."

        Design: Corner/validations/writeoff_over_outstanding_rejected
        """
        ctx = setup_active_pledge(500000, installment_count=1, frequency="ANNUAL",
                                  first_due_date="2026-12-01T00:00:00Z")
        pl_id = ctx["pledge"]["id"]
        resp = api.create_write_off(pl_id, create_write_off_payload(amount_cents=500001, reason="UNCOLLECTIBLE"), FIN)
        validate_error(resp, ApiErrorId.ERR_WRITE_OFF_EXCEEDS_OUTSTANDING)

        rows, meta = validate_paginated(api.list_write_offs(pl_id, FIN))
        assert rows == [] and meta["total_count"] == 0


class TestPledgeCreationGates:
    def test_pledge_on_outright_agreement_rejected(self, api):
        """PRD §3.6: "The agreement must be `EXECUTED` (otherwise
        `ERR_AGREEMENT_INVALID_STATE`) and its proposal must be of type `PLEDGE`
        (otherwise `ERR_PLEDGE_TYPE_REQUIRED`)."

        Design: Corner/validations/pledge_on_outright_agreement_rejected
        """
        ctx = setup_executed_agreement(500000, proposal_type="OUTRIGHT")
        resp = api.create_pledge(
            {
                "agreement_id": ctx["agr"]["id"], "total_amount_cents": 500000,
                "installment_count": 2, "frequency": "ANNUAL",
                "first_due_date": "2026-12-01T00:00:00Z",
            },
            __import__("test_helpers").make_gift_officer_headers(ctx["f"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PLEDGE_TYPE_REQUIRED)

    def test_second_pledge_on_same_agreement_rejected(self, api):
        """PRD §3.6: "one agreement supports exactly one pledge, so a second
        attempt on the same agreement fails with `ERR_PLEDGE_ALREADY_EXISTS`."

        Design: Corner/validations/second_pledge_on_same_agreement_rejected
        """
        ctx = setup_active_pledge(300000, installment_count=1, frequency="ANNUAL",
                                  first_due_date="2026-12-01T00:00:00Z")
        from test_helpers import make_gift_officer_headers
        officer = make_gift_officer_headers(ctx["f"]["id"])
        resp = api.create_pledge(
            {
                "agreement_id": ctx["agr"]["id"], "total_amount_cents": 200000,
                "installment_count": 1, "frequency": "ANNUAL",
                "first_due_date": "2027-12-01T00:00:00Z",
            },
            officer,
        )
        validate_error(resp, ApiErrorId.ERR_PLEDGE_ALREADY_EXISTS)

        rows, meta = validate_paginated(api.list_pledges(FIN, params={"agreement_id": ctx["agr"]["id"]}))
        assert len(rows) == 1
        assert rows[0]["id"] == ctx["pledge"]["id"]

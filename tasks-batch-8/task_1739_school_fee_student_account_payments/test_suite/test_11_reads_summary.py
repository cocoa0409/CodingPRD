"""Reads: pagination envelope, status filters, the computed summary read."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    api_client, ApiErrorId,
    create_student_payload,
    setup_open_year, setup_year_with_fee, add_student_with_account,
    setup_account_with_assessment, setup_approved_waiver_account,
    pay_and_settle, set_clock,
    make_bookkeeper_headers, make_family_headers,
)

BK = make_bookkeeper_headers()


class TestPagination:
    def test_list_pagination_envelope(self, bookkeeper_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return; it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter specifies how many items to skip and defaults
        to 0." and "Paginated list responses carry the following fields in the
        `meta` object of the response envelope: `limit`, `offset`, `total_count`,
        and `has_more`."

        Design: Corner/endpoints/list_pagination_envelope
        """
        for ref, name, grade, fam in (("S-1", "Ada", 10, "fam-a"),
                                      ("S-2", "Ben", 11, "fam-b"),
                                      ("S-3", "Cid", 12, "fam-c")):
            get_success_data(api_client.create_student(
                create_student_payload(external_ref=ref, full_name=name,
                                       grade_level=grade, family_id=fam),
                bookkeeper_headers))
        page1, meta1 = validate_paginated(api_client.list_students(
            bookkeeper_headers, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0
        page2, meta2 = validate_paginated(api_client.list_students(
            bookkeeper_headers, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_filtered_list_by_status(self, bookkeeper_headers, family_headers):
        """PRD §3.5: "The assessment list read filters by status or
        department_id."
        PRD §3.8: "Third, every assessment still `ASSESSED` or `PARTIALLY_PAID`
        whose created_at is more than k days old with outstanding_cents above
        zero becomes `DELINQUENT`"

        Design: Corner/endpoints/filtered_list_by_status
        """
        env = setup_year_with_fee(fee_amount=1000,
                                  year_overrides={"aging_interval_days": 10})
        student, account = add_student_with_account(env["year"]["id"])
        a1 = get_success_data(api_client.create_fee_assessment(
            account["id"], {"fee_item_id": env["fee_item"]["id"],
                            "assessed_amount_cents": 3000}, bookkeeper_headers))
        a2 = get_success_data(api_client.create_fee_assessment(
            account["id"], {"fee_item_id": env["fee_item"]["id"],
                            "assessed_amount_cents": 2000}, bookkeeper_headers))
        # Pay A1 (oldest) fully with a 3000-cent payment
        pay_and_settle(account["id"], 3000, idempotency_key="k1")
        # Age A2 (created at the default clock) past k=10 days
        set_clock("2026-08-12T00:00:00Z")
        get_success_data(api_client.run_ops(env["year"]["id"], bookkeeper_headers))
        delinq, meta_d = validate_paginated(api_client.list_fee_assessments(
            account["id"], bookkeeper_headers, params={"status": "DELINQUENT"}))
        assert meta_d["total_count"] == 1
        assert delinq[0]["assessed_amount_cents"] == 2000
        paid, meta_p = validate_paginated(api_client.list_fee_assessments(
            account["id"], bookkeeper_headers, params={"status": "PAID"}))
        assert meta_p["total_count"] == 1
        assert paid[0]["assessed_amount_cents"] == 3000


class TestSummaryRead:
    def test_summary_computed_read_consistent(self, family_headers):
        """PRD §3.2: "A computed summary read on the account returns its
        balance_cents, family_balance_cents, posture, assessed_cents,
        waived_cents, paid_cents, and open_case_count in one payload."
        PRD §3.2: "balance_cents — assessed_cents minus waived_cents minus
        paid_cents"

        Design: Corner/endpoints/summary_computed_read_consistent
        """
        env = setup_approved_waiver_account(fee_amount=5000, waiver_pct_bp=5000,
                                            grade_level=10, enroll=True,
                                            program_overrides={
                                                "waiver_pct_bp": 5000,
                                                "max_waived_per_student_cents": 100000})
        account_id = env["account"]["id"]
        pay_and_settle(account_id, 1000, idempotency_key="k1")
        resp = api_client.get_account_summary(account_id, family_headers)
        data = validate_success(resp, 200)
        assert data["assessed_cents"] == 5000
        assert data["waived_cents"] == 2500
        assert data["paid_cents"] == 1000
        assert data["balance_cents"] == 1500, (
            f"5000 - 2500 - 1000 = 1500; got {data['balance_cents']}")
        assert data["open_case_count"] == 0
        assert data["posture"] == "CLEAR"

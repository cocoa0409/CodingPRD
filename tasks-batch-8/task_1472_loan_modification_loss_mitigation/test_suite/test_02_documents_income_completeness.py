"""Document cycle, verified-income aggregation, and package completeness."""
import pytest

from test_helpers import (
    AGENT,
    ApiErrorId,
    acknowledge,
    assert_timestamp_instant,
    board_loan,
    create_application_payload,
    get_application,
    get_success_data,
    make_borrower,
    make_borrower_headers,
    reject_document,
    set_clock,
    setup_complete_application,
    submit_application,
    submit_document,
    accept_document,
    validate_error,
    validate_success,
)


class TestVerifiedIncomeAggregation:
    def test_input_set_filtering_and_multi_source_sum(self, api):
        """PRD §3.4: "`verified_monthly_income_cents` aggregates only `ACCEPTED`
        documents whose type bears income (`PAYSTUB`, `TAX_RETURN`, `PROFIT_LOSS`);
        `BANK_STATEMENT` and `HARDSHIP_AFFIDAVIT` contribute nothing."
        PRD §3.4: "Its monthly figure is `gross_per_period_cents` multiplied by a
        frequency factor: 52/12 for `WEEKLY`, 26/12 for `BIWEEKLY`, 2 for
        `SEMIMONTHLY`, 1 for `MONTHLY`; the product is rounded half-up to whole
        cents."
        PRD §3.4: "each `ACCEPTED` profit-and-loss statement contributes its
        `ytd_net_income_cents` divided by `ytd_months`, rounded half-up to whole
        cents"

        Design: Corner/calculations/verified_income_input_set_filtering_and_multi_source_sum
        """
        borrower = make_borrower(full_name="Sara S", email="sara@x.com")
        loan = board_loan(borrower["id"], loan_number="LN-CALC1", delinquency_days=150)
        app = submit_application(
            loan, borrower["id"], stated_income=470_000
        )
        acknowledge(app["id"])
        pay = submit_document(
            app["id"], borrower["id"], "PAYSTUB",
            gross_per_period_cents=200_000, pay_frequency="BIWEEKLY",
            pay_period_end_date="2026-07-31",
        )
        pl = submit_document(
            app["id"], borrower["id"], "PROFIT_LOSS",
            ytd_net_income_cents=240_000, ytd_months=6,
        )
        tax = submit_document(
            app["id"], borrower["id"], "TAX_RETURN", annual_gross_cents=99_999_900
        )
        bank = submit_document(app["id"], borrower["id"], "BANK_STATEMENT")
        aff = submit_document(app["id"], borrower["id"], "HARDSHIP_AFFIDAVIT")
        accept_document(pay["id"])
        accept_document(pl["id"])
        reject_document(tax["id"], "illegible")
        accept_document(bank["id"])
        accept_document(aff["id"])

        after = get_application(app["id"])
        # 200000 * 26/12 = 433333 (half-up) + 240000/6 = 40000 = 473333.
        assert after["verified_monthly_income_cents"] == 473_333
        assert after["status"] == "COMPLETE_PACKAGE"

    def test_income_frequency_multiplier_constants(self, api):
        """PRD §3.4: "Its monthly figure is `gross_per_period_cents` multiplied by
        a frequency factor: 52/12 for `WEEKLY`, 26/12 for `BIWEEKLY`, 2 for
        `SEMIMONTHLY`, 1 for `MONTHLY`; the product is rounded half-up to whole
        cents."

        Design: Corner/calculations/income_frequency_multiplier_constants
        """
        borrower = make_borrower(full_name="Tim T", email="tim@x.com")
        loan_a = board_loan(borrower["id"], loan_number="LN-CALC2A", delinquency_days=150)
        loan_b = board_loan(borrower["id"], loan_number="LN-CALC2B", delinquency_days=150)
        app_a = submit_application(loan_a, borrower["id"], hardship_type="OTHER", stated_income=1)
        app_b = submit_application(loan_b, borrower["id"], hardship_type="OTHER", stated_income=1)
        d_a = submit_document(
            app_a["id"], borrower["id"], "PAYSTUB",
            gross_per_period_cents=100_000, pay_frequency="SEMIMONTHLY",
            pay_period_end_date="2026-07-31",
        )
        d_b = submit_document(
            app_b["id"], borrower["id"], "PAYSTUB",
            gross_per_period_cents=100_000, pay_frequency="WEEKLY",
            pay_period_end_date="2026-07-31",
        )
        accept_document(d_a["id"])
        accept_document(d_b["id"])

        assert get_application(app_a["id"])["verified_monthly_income_cents"] == 200_000
        # 100000 * 52/12 = 433333.33 -> half-up 433333.
        assert get_application(app_b["id"])["verified_monthly_income_cents"] == 433_333


class TestDocumentResolution:
    def test_accept_already_resolved_document_rejected(self, api, agent_headers):
        """PRD §3.3: "Acting on a document not in `SUBMITTED` is rejected with
        `ERR_DOCUMENT_ALREADY_RESOLVED`, and the parent application must not be
        terminal."

        Design: Corner/state_machines/accept_already_resolved_document_rejected
        """
        borrower = make_borrower(full_name="Kim K", email="kim@x.com")
        loan = board_loan(borrower["id"], loan_number="LN-SM3", delinquency_days=150)
        app = submit_application(loan, borrower["id"], hardship_type="MEDICAL", stated_income=100_000)
        acknowledge(app["id"])
        doc = submit_document(
            app["id"], borrower["id"], "PAYSTUB",
            gross_per_period_cents=100_000, pay_frequency="MONTHLY",
            pay_period_end_date="2026-07-31",
        )
        validate_success(api.accept_document(doc["id"], agent_headers), 200)

        res = api.accept_document(doc["id"], agent_headers)
        validate_error(res, ApiErrorId.ERR_DOCUMENT_ALREADY_RESOLVED, expected_status=409)
        docs = get_success_data(api.list_documents(app["id"], agent_headers))
        assert docs[0]["status"] == "ACCEPTED"

    def test_document_reject_requires_reason(self, api, agent_headers):
        """PRD §3.3: "rejecting moves it to `REJECTED` and requires a
        `rejection_reason`."
        PRD §2.7: "3. **Request shape** — required fields present, enum members
        valid, integer types well-formed, else `ERR_VALIDATION`."

        Design: Corner/validations/document_reject_requires_reason
        """
        borrower = make_borrower(full_name="Ugo U", email="ugo@x.com")
        loan = board_loan(borrower["id"], loan_number="LN-VAL8", delinquency_days=150)
        app = submit_application(loan, borrower["id"], hardship_type="OTHER", stated_income=100_000)
        doc = submit_document(app["id"], borrower["id"], "BANK_STATEMENT")

        res = api.reject_document(doc["id"], {}, agent_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)
        docs = get_success_data(api.list_documents(app["id"], agent_headers))
        assert docs[0]["status"] == "SUBMITTED"


class TestCompletenessBoundary:
    def test_one_outstanding_category_keeps_acknowledged(self, api, admin_headers):
        """PRD §3.3: "When an accept empties `outstanding_doc_categories` while
        the application is `ACKNOWLEDGED`, the application transitions to
        `COMPLETE_PACKAGE`" — with one category still outstanding there is no flip.

        Design: Difficulty/boundary_precision_check/outstanding_docs_one_to_zero_flips_complete
        """
        borrower = make_borrower(full_name="Omar O", email="omar@x.com")
        loan = board_loan(borrower["id"], loan_number="LN-BP2", delinquency_days=150)
        app = submit_application(loan, borrower["id"], hardship_type="MEDICAL", stated_income=400_000)
        acknowledge(app["id"])
        pay = submit_document(
            app["id"], borrower["id"], "PAYSTUB",
            gross_per_period_cents=200_000, pay_frequency="BIWEEKLY",
            pay_period_end_date="2026-07-31",
        )
        aff = submit_document(app["id"], borrower["id"], "HARDSHIP_AFFIDAVIT")
        bank = submit_document(app["id"], borrower["id"], "BANK_STATEMENT")
        accept_document(pay["id"])
        accept_document(aff["id"])

        mid = get_application(app["id"])
        assert mid["status"] == "ACKNOWLEDGED"
        assert mid["outstanding_doc_categories"] == ["BANK_STATEMENT"]

    def test_zero_outstanding_flips_complete_and_anchors(self, api, admin_headers):
        """PRD §3.3: "When an accept empties `outstanding_doc_categories` while
        the application is `ACKNOWLEDGED`, the application transitions to
        `COMPLETE_PACKAGE`, `completed_at` is stamped to the current instant
        **on first completion only** (it is never cleared afterwards — it anchors
        the 37-day and 90-day dual-tracking rules), and `evaluation_deadline` is
        set to `completed_at` plus thirty days."

        Design: Difficulty/boundary_precision_check/outstanding_docs_one_to_zero_flips_complete
        """
        borrower = make_borrower(full_name="Omar O2", email="omar2@x.com")
        loan = board_loan(borrower["id"], loan_number="LN-BP2B", delinquency_days=150)
        app = submit_application(loan, borrower["id"], hardship_type="MEDICAL", stated_income=400_000)
        acknowledge(app["id"])
        pay = submit_document(
            app["id"], borrower["id"], "PAYSTUB",
            gross_per_period_cents=200_000, pay_frequency="BIWEEKLY",
            pay_period_end_date="2026-07-31",
        )
        aff = submit_document(app["id"], borrower["id"], "HARDSHIP_AFFIDAVIT")
        bank = submit_document(app["id"], borrower["id"], "BANK_STATEMENT")
        accept_document(pay["id"])
        accept_document(aff["id"])
        set_clock("2026-08-05T00:00:00Z")
        accept_document(bank["id"])

        after = get_application(app["id"])
        assert after["status"] == "COMPLETE_PACKAGE"
        assert after["outstanding_doc_categories"] == []
        assert_timestamp_instant(after["completed_at"], "2026-08-05T00:00:00Z")


class TestCompletenessReopenCycle:
    def test_supersession_reopens_completeness(self, api):
        """PRD §3.3: "Submitting a new document of the same `doc_type` as an
        existing `ACCEPTED` document on the same application supersedes the older
        one — the older document transitions to `SUPERSEDED`, which recomputes
        both income and package completeness (see below) and may re-open the
        cycle."
        PRD §3.3: "When a supersession later re-opens a gap — the only `ACCEPTED`
        document of a required category is displaced — the application falls back
        from `COMPLETE_PACKAGE` to `ACKNOWLEDGED`, retaining the original
        `completed_at`."

        Design: Difficulty/non_linear_state_machine/application_completeness_reopen_cycle
        """
        scenario = setup_complete_application(
            economics="A", complete_at="2026-08-05T00:00:00Z",
            # Paystub is the ONLY income-bearing document, so superseding it
            # displaces the only ACCEPTED document of the INCOME_PROOF category
            # (PRD 3.3: INCOME_PROOF is satisfied by ANY income-bearing
            # accepted document -- fixture A's tax return would mask the gap).
            docs=[
                ("PAYSTUB", {
                    "gross_per_period_cents": 200_000,
                    "pay_frequency": "BIWEEKLY",
                    "pay_period_end_date": "2026-07-31",
                }),
                ("HARDSHIP_AFFIDAVIT", {}),
                ("BANK_STATEMENT", {}),
            ],
        )
        app_id = scenario["application"]["id"]
        borrower_id = scenario["borrower"]["id"]

        # Supersede the only ACCEPTED paystub (the application's INCOME_PROOF).
        new_stub = submit_document(
            app_id, borrower_id, "PAYSTUB",
            gross_per_period_cents=210_000, pay_frequency="BIWEEKLY",
            pay_period_end_date="2026-08-07",
        )
        mid = get_application(app_id)
        assert mid["status"] == "ACKNOWLEDGED"
        assert mid["outstanding_doc_categories"] == ["INCOME_PROOF"]
        # No accepted income-bearing document remains.
        assert mid["verified_monthly_income_cents"] == 0
        assert_timestamp_instant(mid["completed_at"], "2026-08-05T00:00:00Z")
        scenario["new_stub"] = new_stub
        return scenario

    def test_reacceptance_completes_cycle_with_anchor_retained(self, api):
        """PRD §3.3: "When an accept empties `outstanding_doc_categories` while
        the application is `ACKNOWLEDGED`, the application transitions to
        `COMPLETE_PACKAGE`, `completed_at` is stamped to the current instant
        **on first completion only** (it is never cleared afterwards — it anchors
        the 37-day and 90-day dual-tracking rules), and `evaluation_deadline` is
        set to `completed_at` plus thirty days."
        PRD §3.4: "Its monthly figure is `gross_per_period_cents` multiplied by a
        frequency factor: 52/12 for `WEEKLY`, 26/12 for `BIWEEKLY`, 2 for
        `SEMIMONTHLY`, 1 for `MONTHLY`; the product is rounded half-up to whole
        cents."

        Design: Difficulty/non_linear_state_machine/application_completeness_reopen_cycle
        """
        scenario = setup_complete_application(
            economics="A", complete_at="2026-08-05T00:00:00Z",
            # Paystub is the ONLY income-bearing document (see the sibling
            # test above for why the fixture A tax return is excluded).
            docs=[
                ("PAYSTUB", {
                    "gross_per_period_cents": 200_000,
                    "pay_frequency": "BIWEEKLY",
                    "pay_period_end_date": "2026-07-31",
                }),
                ("HARDSHIP_AFFIDAVIT", {}),
                ("BANK_STATEMENT", {}),
            ],
        )
        app_id = scenario["application"]["id"]
        borrower_id = scenario["borrower"]["id"]
        new_stub = submit_document(
            app_id, borrower_id, "PAYSTUB",
            gross_per_period_cents=210_000, pay_frequency="BIWEEKLY",
            pay_period_end_date="2026-08-07",
        )
        assert get_application(app_id)["status"] == "ACKNOWLEDGED"

        accept_document(new_stub["id"])
        after = get_application(app_id)
        assert after["status"] == "COMPLETE_PACKAGE"
        # 210000 * 26/12 = 455000 (half-up); the paystub is the only income.
        assert after["verified_monthly_income_cents"] == 455_000
        assert_timestamp_instant(after["completed_at"], "2026-08-05T00:00:00Z")

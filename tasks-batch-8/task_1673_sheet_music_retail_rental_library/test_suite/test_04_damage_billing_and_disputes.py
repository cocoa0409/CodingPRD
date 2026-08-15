"""Condition assessment, damage pricing, invoice lifecycle, and dispute loop."""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    check_in_order,
    create_account,
    create_condition_report_payload,
    create_order,
    create_publisher,
    create_rental_set,
    create_work,
    dispute_order,
    fetch_account,
    fetch_order,
    fetch_report,
    fetch_set,
    get_success_data,
    make_billing_manager_headers,
    make_customer_headers,
    make_returns_clerk_headers,
    order_lines,
    reports_for_line,
    reserve_order,
    dispatch_order,
    confirm_order,
    setup_draft_invoice,
    setup_draft_invoice_with_assessor,
    setup_issued_invoice,
    setup_order_on_loan,
    setup_returned_order,
    validate_error,
    validate_success,
)

from test_helpers import BILLING, CLERK, RETURNS


class TestDamageChargeConstants:
    def test_damage_charge_floor_and_cap_and_zero_degradation(self, api):
        """PRD §3.6: "when the observed grade is not worse than the line's
        `checkout_condition`, there is no degradation and `assessed_charge_cents`
        is 0."
        PRD §3.6: "the product is rounded half-up, then capped at 200,000 cents by
        taking the smaller of the raw figure and the cap, then floored at 1,500
        cents by taking the larger of the capped figure and the floor."
        PRD §3.6: "for each line whose observed grade degraded relative to its
        `checkout_condition`, a condition report is filed in `FILED` status
        carrying a computed `assessed_charge_cents`".

        Design: Corner/calculations/damage_charge_floor_and_cap_and_zero_degradation
        """
        publisher = create_publisher("DC Pub")
        work = create_work(publisher["id"], title="DC Work", catalog_number="DC-1",
                           base_rental_rate_cents=1000, sale_price_cents=500)
        set_floor = create_rental_set(work["id"], set_code="DC-FLOOR", copy_count=4,
                                      replacement_value_cents=6000)
        set_cap = create_rental_set(work["id"], set_code="DC-CAP", copy_count=2,
                                    replacement_value_cents=50000000)
        account = create_account("DC Acct", credit_tier="STANDARD", credit_limit_cents=0)
        advance_clock()

        def loan_and_return(set_id, grades):
            order = create_order(account["id"], set_id, copies=1)
            reserve_order(order["id"])
            dispatch_order(order["id"])
            confirm_order(order["id"], account["id"])
            return check_in_order(order["id"], grades)

        clean = loan_and_return(set_floor["id"], "A")
        floored = loan_and_return(set_floor["id"], "B")
        capped = loan_and_return(set_cap["id"], "D")

        # No degradation -> no condition report is filed for the line at all.
        clean_line = order_lines(clean["id"])[0]
        assert reports_for_line(clean_line["id"]) == [], (
            "an A->A return must not file a condition report"
        )

        # Floor: per-copy rhu(6000/4)=1500; raw rhu(1500 x 0.10)=150 -> 1500.
        floor_line = order_lines(floored["id"])[0]
        floor_report = reports_for_line(floor_line["id"])[0]
        assert floor_report["observed_grade"] == "B"
        assert floor_report["assessed_charge_cents"] == 1500
        assert floor_report["status"] == "FILED"

        # Cap: per-copy rhu(50000000/2)=25000000; raw rhu(x 0.60)=15000000 -> 200000.
        cap_line = order_lines(capped["id"])[0]
        cap_report = reports_for_line(cap_line["id"])[0]
        assert cap_report["observed_grade"] == "D"
        assert cap_report["assessed_charge_cents"] == 200000


class TestGradeDCascade:
    def test_checkin_grade_d_cascades_set_under_repair(self, api):
        """PRD §3.6: "the set's `condition_grade` is reset to the worst grade
        across all of its returned lines, and if any line came back `D` the set
        drops from `IN_SERVICE` to `UNDER_REPAIR` with its `version` incrementing".
        PRD §3.5: "The set must be `IN_SERVICE` with a condition grade other than
        `D` (`ERR_RENTAL_SET_NOT_RENTABLE`)."

        Design: Corner/state_machines/checkin_grade_d_cascades_set_under_repair
        """
        ws = setup_order_on_loan(order_copies=1, publisher_name="GD Pub",
                                 work_title="GD Work", catalog_number="GD-1",
                                 set_code="GD-SET", copies=5, replacement=40000,
                                 account_overrides={"account_name": "GD Acct",
                                                    "account_kind": "INDIVIDUAL"})
        check_in_order(ws["order"]["id"], "D")

        set_after = fetch_set(ws["rental_set"]["id"])
        assert set_after["condition_grade"] == "D"
        assert set_after["status"] == "UNDER_REPAIR"

        # A grade-D set is unrentable until repaired.
        second = create_order(ws["account"]["id"], ws["rental_set"]["id"], copies=1,
                              checkout_date="2026-08-06", due_date="2026-09-05")
        resp = api.reserve_rental_order(second["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_RENTAL_SET_NOT_RENTABLE)


class TestReportLost:
    def test_report_lost_files_lost_condition_report_at_per_copy_value(self, api):
        """PRD §3.6: "The line moves to `LOST`, a condition report is auto-filed
        with `observed_grade` `LOST` and the per-copy replacement charge, and the
        set's `available_copy_count` is pointedly not incremented — the copy never
        returns."
        PRD §3.6: "When a line's `observed_grade` is `LOST`, the charge is the
        per-copy replacement value: the set's `replacement_value_cents` divided by
        its `copy_count`, rounded half-up."

        Design: Corner/state_machines/report_lost_files_lost_condition_report_at_per_copy_value
        """
        ws = setup_order_on_loan(order_copies=2, publisher_name="LS Pub",
                                 work_title="LS Work", catalog_number="LS-1",
                                 set_code="LS-SET", copies=30, replacement=240000,
                                 account_overrides={"account_name": "LS Acct",
                                                    "account_kind": "INDIVIDUAL"})
        assert fetch_set(ws["rental_set"]["id"])["available_copy_count"] == 28
        line = order_lines(ws["order"]["id"])[0]

        lost = validate_success(api.report_line_lost(line["id"], CLERK))
        assert lost["status"] == "LOST"

        reports = reports_for_line(line["id"])
        assert len(reports) == 1
        # rhu(240000 / 30) = 8000 per-copy replacement charge.
        assert reports[0]["observed_grade"] == "LOST"
        assert reports[0]["assessed_charge_cents"] == 8000

        set_after = fetch_set(ws["rental_set"]["id"])
        assert set_after["available_copy_count"] == 28, (
            "the lost copy restores nothing; the second line is still ON_LOAN; got "
            f"{set_after['available_copy_count']}"
        )


class TestDisputeReissueLoop:
    def test_reissue_supersedes_report_and_updates_amount(self, api):
        """PRD §3.6: "Reissue — a `BillingManager` supplying
        `new_condition_report_id` — likewise applies only from `DISPUTED` and
        requires a superseding report: one in `FILED` status for the same line
        carrying a different assessed charge, otherwise `ERR_REASSESSMENT_REQUIRED`.
        Reissue moves the old report to `SUPERSEDED`, the new report to
        `INVOICED`, updates `amount_cents` to the new charge, returns the invoice
        to `ISSUED`, and recomputes exposures with the account's `version`
        incrementing."

        Design: Difficulty/non_linear_state_machine/damage_invoice_dispute_reissue_loop
        """
        ws = setup_issued_invoice(publisher_name="Pub Six", work_title="Waltzes",
                                  catalog_number="P6-001", set_code="SET-401",
                                  account_overrides={"account_name": "East Prep"})
        assert ws["invoice"]["amount_cents"] == 2400  # A->C on per-copy 8000
        dispute_order(ws["order"]["id"], ws["account"]["id"])
        reassessment = get_success_data(api.create_condition_report(
            create_condition_report_payload(
                ws["line"]["id"], observed_grade="D",
                findings="water damage, binding detached",
            ),
            RETURNS,
        ))

        reissued = validate_success(api.reissue_damage_invoice(
            ws["invoice"]["id"], reassessment["id"], BILLING,
        ))
        # A->D: rhu(8000 x 0.60) = 4800.
        assert reissued["status"] == "ISSUED"
        assert reissued["amount_cents"] == 4800
        assert fetch_report(ws["report"]["id"])["status"] == "SUPERSEDED"
        assert fetch_report(reassessment["id"])["status"] == "INVOICED"

    def test_dispute_loop_closes_via_resolve_accepted(self, api):
        """PRD §3.6: "acceptance moves the invoice to `RESOLVED_ACCEPTED` with the
        amount standing and exposures recomputing exactly as if it had been paid".
        PRD §3.6: "A `BillingManager` closes the loop only when every `DISPUTED`
        invoice has been resolved — accepted or waived — or re-assessed with its
        old report superseded and the invoice re-issued".

        Design: Difficulty/non_linear_state_machine/damage_invoice_dispute_reissue_loop
        """
        ws = setup_issued_invoice(publisher_name="Pub Six", work_title="Waltzes",
                                  catalog_number="P6-001", set_code="SET-401",
                                  account_overrides={"account_name": "East Prep"})
        dispute_order(ws["order"]["id"], ws["account"]["id"])
        reassessment = get_success_data(api.create_condition_report(
            create_condition_report_payload(
                ws["line"]["id"], observed_grade="D",
                findings="water damage, binding detached",
            ),
            RETURNS,
        ))
        get_success_data(api.reissue_damage_invoice(
            ws["invoice"]["id"], reassessment["id"], BILLING,
        ))
        # The re-issued invoice clears the dispute close; the loop re-opens on a
        # fresh dispute and the invoice is finally accepted.
        closed = get_success_data(
            api.resolve_dispute_rental_order(ws["order"]["id"], BILLING)
        )
        assert closed["status"] == "RETURNED"
        disputed_again = dispute_order(ws["order"]["id"], ws["account"]["id"])
        assert disputed_again["status"] == "DISPUTED"

        resolved = validate_success(api.resolve_damage_invoice(
            ws["invoice"]["id"], "RESOLVED_ACCEPTED", BILLING,
        ))
        assert resolved["status"] == "RESOLVED_ACCEPTED"
        assert resolved["amount_cents"] == 4800
        # The order leaves the loop only via resolve-dispute.
        assert fetch_order(ws["order"]["id"])["status"] == "DISPUTED"


class TestDisputeAndSettleGates:
    def test_dispute_with_nothing_issued_rejected(self, api):
        """PRD §3.6: "A `Customer` may dispute a `RETURNED` order, which requires
        at least one `ISSUED` damage invoice on the order's lines
        (`ERR_NOTHING_TO_DISPUTE`)".

        Design: Corner/validations/dispute_with_nothing_issued_rejected
        """
        ws = setup_returned_order(grades="A", copies=1, publisher_name="ND Pub",
                                  work_title="ND Work", catalog_number="ND-1",
                                  set_code="ND-SET", replacement=40000,
                                  account_overrides={"account_name": "ND Acct",
                                                     "account_kind": "INDIVIDUAL"})
        resp = api.dispute_rental_order(
            ws["order"]["id"], make_customer_headers(ws["account"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOTHING_TO_DISPUTE)

    def test_settle_with_unsettled_invoices_rejected_then_succeeds(self, api):
        """PRD §3.6: "Settlement — a `BillingManager` moving `RETURNED` →
        `SETTLED` — requires every damage invoice on the order's lines to sit in
        `PAID`, `RESOLVED_ACCEPTED`, or `RESOLVED_WAIVED`, with none left in
        `DRAFT`, `ISSUED`, or `DISPUTED` (`ERR_UNSETTLED_DAMAGE_INVOICES`)."

        Design: Corner/validations/settle_with_unsettled_invoices_rejected_then_succeeds
        """
        ws = setup_issued_invoice(publisher_name="US Pub", work_title="US Work",
                                  catalog_number="US-1", set_code="US-SET",
                                  account_overrides={"account_name": "US Acct"})

        resp = api.settle_rental_order(ws["order"]["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_UNSETTLED_DAMAGE_INVOICES)

        paid = validate_success(
            api.record_invoice_payment(ws["invoice"]["id"], BILLING)
        )
        assert paid["status"] == "PAID"
        settled = validate_success(api.settle_rental_order(ws["order"]["id"], BILLING))
        assert settled["status"] == "SETTLED"

    def test_reissue_without_reassessment_rejected(self, api):
        """PRD §3.6: "Reissue — a `BillingManager` supplying
        `new_condition_report_id` — likewise applies only from `DISPUTED` and
        requires a superseding report: one in `FILED` status for the same line
        carrying a different assessed charge, otherwise `ERR_REASSESSMENT_REQUIRED`."

        Design: Corner/validations/reissue_without_reassessment_rejected
        """
        ws = setup_issued_invoice(publisher_name="RA Pub", work_title="RA Work",
                                  catalog_number="RA-1", set_code="RA-SET",
                                  account_overrides={"account_name": "RA Acct"})
        dispute_order(ws["order"]["id"], ws["account"]["id"])

        # The only report on the line is already INVOICED — no FILED superseder.
        resp = api.reissue_damage_invoice(ws["invoice"]["id"], ws["report"]["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_REASSESSMENT_REQUIRED)


class TestSegregationOfDuties:
    def test_wrong_role_trumps_segregation_of_duties(self, api):
        """PRD §2.9: "Every write request is evaluated against a fixed pipeline of
        validation tiers, and an earlier tier's failure masks every later tier —
        the surfaced error is always the earliest applicable one. The order is:
        (1) the user-context header check of §2.1; (2) role authorization; (3)
        path-resource existence per §2.8; (4) state-transition admissibility ...
        (5) segregation of duties on damage-invoice issuance and dispute
        resolution".

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_invoice_issue
        """
        ws = setup_draft_invoice_with_assessor(
            "rc-shared-1", publisher_name="Pub Ten", work_title="Gavotte",
            catalog_number="P10-001", set_code="SET-801",
            account_overrides={"account_name": "Hill College",
                               "account_kind": "INSTITUTION"},
        )
        assert ws["report"]["assessor_user_id"] == "rc-shared-1"

        # The caller violates role authorization (tier 2) AND segregation of
        # duties (tier 5): the earlier tier masks the later one.
        resp = api.issue_damage_invoice(
            ws["invoice"]["id"], make_returns_clerk_headers("rc-shared-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_right_role_same_person_hits_segregation_then_distinct_succeeds(self, api):
        """PRD §3.6: "Issuance moves `DRAFT` → `ISSUED` and enforces segregation
        of duties: the issuer's `X-User-ID` must differ from the supporting
        report's `assessor_user_id` on that line, or the request is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_invoice_issue
        """
        ws = setup_draft_invoice_with_assessor(
            "rc-shared-1", publisher_name="Pub Ten", work_title="Gavotte",
            catalog_number="P10-001", set_code="SET-801",
            account_overrides={"account_name": "Hill College",
                               "account_kind": "INSTITUTION"},
        )

        # The permitted role but the same person as the assessor: SoD fires.
        resp = api.issue_damage_invoice(
            ws["invoice"]["id"], make_billing_manager_headers("rc-shared-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        # A different BillingManager user clears the SoD gate.
        issued = validate_success(api.issue_damage_invoice(
            ws["invoice"]["id"], make_billing_manager_headers("bm-distinct-1"),
        ))
        assert issued["status"] == "ISSUED"


class TestSettledExposureConservation:
    def _ws_with_draft_invoice(self, api):
        return setup_draft_invoice(
            grades="C", copies=1, publisher_name="Pub Eighteen",
            work_title="Bagatelles", catalog_number="P18-001", base_rate=5400,
            sale_price=900, set_code="SET-1501",
            account_overrides={"account_name": "Aspen College",
                               "account_kind": "INSTITUTION",
                               "credit_tier": "STANDARD", "credit_limit_cents": 0},
        )

    def test_issue_adds_invoice_to_settled_exposure(self, api):
        """PRD §3.3: "The enforcement measure, `settled_exposure_cents`, uses
        narrower sets: damage invoices count only when `ISSUED` or `DISPUTED`
        (drafts are excluded)".
        PRD §3.6: "Issuing moves the supporting report to `INVOICED`, recomputes
        both exposures — the invoice now counts in each".

        Design: Difficulty/compensating_invariant/outstanding_balance_conserved_across_issue_and_waive
        """
        ws = self._ws_with_draft_invoice(api)
        # On-time return of 1 copy at base 5400: final fee 5400 is the only
        # settled component while the 2400 invoice is still DRAFT.
        assert fetch_account(ws["account"]["id"])["settled_exposure_cents"] == 5400

        issued = validate_success(
            api.issue_damage_invoice(ws["invoice"]["id"], BILLING)
        )
        assert issued["status"] == "ISSUED"
        account = fetch_account(ws["account"]["id"])
        assert account["settled_exposure_cents"] == 7800, (
            f"issuing must add the 2400 invoice to settled exposure; got "
            f"{account['settled_exposure_cents']}"
        )

    def test_dispute_and_waive_restores_settled_exposure(self, api):
        """PRD §3.6: "waiver moves it to `RESOLVED_WAIVED`, zeroing the collected
        amount but preserving the record for audit."
        PRD §3.3: "damage invoices count only when `ISSUED` or `DISPUTED` (drafts
        are excluded)".

        Design: Difficulty/compensating_invariant/outstanding_balance_conserved_across_issue_and_waive
        """
        ws = self._ws_with_draft_invoice(api)
        get_success_data(api.issue_damage_invoice(ws["invoice"]["id"], BILLING))
        assert fetch_account(ws["account"]["id"])["settled_exposure_cents"] == 7800

        dispute_order(ws["order"]["id"], ws["account"]["id"])
        waived = validate_success(api.resolve_damage_invoice(
            ws["invoice"]["id"], "RESOLVED_WAIVED", BILLING,
        ))
        assert waived["status"] == "RESOLVED_WAIVED"

        account = fetch_account(ws["account"]["id"])
        assert account["settled_exposure_cents"] == 5400, (
            "the waive must compensate the issue exactly — no ledger drift; got "
            f"{account['settled_exposure_cents']}"
        )

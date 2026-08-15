"""Deferred revenue accounting: recognition-variant snapshotting, per-variant
timing divergence at mailing, rounding-residual absorption, and the
recognized + deferred == gross conservation invariant."""
from test_helpers import (
    api_client,
    validate_success,
    ApiErrorId,
    TEST_USERS,
    assert_subscription_term,
    assert_term_balance_invariant,
    create_publication,
    create_issue,
    create_subscriber,
    create_subscription,
    activate_subscription,
    get_first_term,
    list_term_revenue_entries,
    drive_issue_to_mailed,
    mail_sequential_issues,
    set_clock,
    CM,
)

CM_H = TEST_USERS["circulation_manager_headers"]

PRICE_1205 = 1205  # 12-issue term: per-issue round_half_up(1205/12) = 100, residual 5


def _activate_with_term(pub_id, subscriber_id, issue_id, term_issues=12, price=PRICE_1205):
    sub = create_subscription(
        pub_id, subscriber_id, issue_id,
        term_issues=term_issues, price_paid_cents=price,
        qualification_tier="PAID", payment_method="CARD",
    )
    return activate_subscription(pub_id, sub["id"])


class TestRecognitionVariantSnapshot:
    def test_recognition_variant_snapshot_per_publication_method(self, api):
        """Two publications with different deferred_revenue_method values
        produce terms pinned to their own publication's variant; before any
        issue is mailed, issues_served is zero on both subscriptions.

        PRD §2.10: "Each term pins its recognition variant at birth: `recognition_variant` is a snapshot of the publication's `deferred_revenue_method` taken when the term is created, and it does not change mid-term even if the publication's method is later edited."
        PRD §3.2: "Two counters track service against the term: `issues_served`, the number of issues already mailed to the subscription within the current term, and `issues_suspended_count`, the number of issues skipped while the subscription was suspended."

        Design: Difficulty/dual_variant_calc/deferred_revenue_pro_rata_vs_straight_line_per_issue_divergence
        """
        set_clock()
        pub_pr = create_publication(deferred_revenue_method="PRO_RATA_ISSUE")
        pub_sl = create_publication(deferred_revenue_method="STRAIGHT_LINE_MONTH")
        issue_pr = create_issue(pub_pr["id"])
        issue_sl = create_issue(pub_sl["id"])

        sub_pr = _activate_with_term(pub_pr["id"], create_subscriber()["id"], issue_pr["id"])
        sub_sl = _activate_with_term(pub_sl["id"], create_subscriber()["id"], issue_sl["id"])

        assert sub_pr["issues_served"] == 0, "no issue has been mailed yet"
        assert sub_sl["issues_served"] == 0, "no issue has been mailed yet"

        term_pr = get_first_term(pub_pr["id"], sub_pr["id"])
        term_sl = get_first_term(pub_sl["id"], sub_sl["id"])
        assert_subscription_term(term_pr)
        assert_subscription_term(term_sl)
        assert term_pr["recognition_variant"] == "PRO_RATA_ISSUE", (
            f"term must snapshot PRO_RATA_ISSUE from the publication, got {term_pr['recognition_variant']}"
        )
        assert term_sl["recognition_variant"] == "STRAIGHT_LINE_MONTH", (
            f"term must snapshot STRAIGHT_LINE_MONTH from the publication, got {term_sl['recognition_variant']}"
        )

    def test_pro_rata_recognizes_on_mail_straight_line_waits_for_month_end(self, api):
        """Mailing one mid-term issue recognizes round_half_up(1205/12) = 100
        cents on the PRO_RATA_ISSUE term immediately, while the
        STRAIGHT_LINE_MONTH term — which recognizes at month-end rather than
        per issue — shows no recognition and no ledger entries (the clock has
        not crossed a month-end).

        PRD §3.5: "Under `PRO_RATA_ISSUE`, each issue of the term recognizes the term's `gross_amount_cents` divided by `issues_in_term`, rounded half up to whole cents — except the term's final issue, identified when the count of `RECOGNITION` entries already posted against the term has reached one less than `issues_in_term`, which instead recognizes whatever amount remains so that `recognized_balance_cents` and `deferred_balance_cents` together equal `gross_amount_cents` exactly."
        PRD §3.5: "Under the alternative `STRAIGHT_LINE_MONTH` variant, recognition spreads evenly across the calendar months the term spans rather than tracking individual issues, and runs as a month-end pass over every `OPEN` term whose `recognition_variant` is `STRAIGHT_LINE_MONTH` and whose term covers the closing month, with `recognized_at` set to month-end."
        PRD §3.5: "The issue's `revenue_recognized_cents` records the sum of the recognition entries posted against it."

        Design: Difficulty/dual_variant_calc/deferred_revenue_pro_rata_vs_straight_line_per_issue_divergence
        """
        # Clock lands mid-month; no month-end is crossed by any later step.
        set_clock("2026-08-15T00:00:00Z")
        pub_pr = create_publication(deferred_revenue_method="PRO_RATA_ISSUE")
        pub_sl = create_publication(deferred_revenue_method="STRAIGHT_LINE_MONTH")
        issue_pr = create_issue(pub_pr["id"], mail_date="2026-08-15T00:00:00Z")
        issue_sl = create_issue(pub_sl["id"], mail_date="2026-08-15T00:00:00Z")
        sub_pr = _activate_with_term(pub_pr["id"], create_subscriber()["id"], issue_pr["id"])
        sub_sl = _activate_with_term(pub_sl["id"], create_subscriber()["id"], issue_sl["id"])

        mailed_pr = drive_issue_to_mailed(pub_pr["id"], issue_pr["id"])
        mailed_sl = drive_issue_to_mailed(pub_sl["id"], issue_sl["id"])

        term_pr = get_first_term(pub_pr["id"], sub_pr["id"])
        assert term_pr["recognized_balance_cents"] == 100, (
            f"PRO_RATA_ISSUE must recognize round_half_up(1205/12)=100 on the first mailed issue, "
            f"got {term_pr['recognized_balance_cents']}"
        )
        assert term_pr["deferred_balance_cents"] == 1105
        assert_term_balance_invariant(term_pr)
        assert mailed_pr["revenue_recognized_cents"] == 100

        term_sl = get_first_term(pub_sl["id"], sub_sl["id"])
        assert term_sl["recognized_balance_cents"] == 0, (
            "STRAIGHT_LINE_MONTH recognizes at month-end, not on an issue mail event; "
            f"no month-end has passed, got recognized={term_sl['recognized_balance_cents']}"
        )
        assert term_sl["deferred_balance_cents"] == PRICE_1205
        assert mailed_sl["revenue_recognized_cents"] == 0
        entries_sl = list_term_revenue_entries(pub_sl["id"], sub_sl["id"], term_sl["id"])
        assert entries_sl == [], (
            f"no DeferredRevenueEntry may be posted to the STRAIGHT_LINE_MONTH term yet, got {entries_sl}"
        )


class TestResidualAbsorption:
    def test_term_balances_start_at_gross_with_zero_recognized(self, api):
        """At activation the term's gross and deferred balances both equal the
        price paid and nothing has been recognized yet.

        PRD §3.2: "Activation creates the first **SubscriptionTerm** with `term_index` 1, its `term_start_issue_id` equal to the subscription's start issue, `issues_in_term` equal to `term_issues`, `gross_amount_cents` and `deferred_balance_cents` both equal to the price paid, and `recognition_variant` snapshotted from the publication's current `deferred_revenue_method`."
        PRD §2.10: "Every SubscriptionTerm records the cash received as `gross_amount_cents`, the still-unrecognized remainder as `deferred_balance_cents`, and the cumulative recognized portion as `recognized_balance_cents`; while the term stands `OPEN`, the recognized and deferred balances always sum exactly to the gross."

        Design: Difficulty/combinatorial_formula/deferred_revenue_residual_absorption_rounding_order
        """
        set_clock()
        pub = create_publication(deferred_revenue_method="PRO_RATA_ISSUE")
        issue = create_issue(pub["id"])
        sub = _activate_with_term(pub["id"], create_subscriber()["id"], issue["id"])

        term = get_first_term(pub["id"], sub["id"])
        assert_subscription_term(term)
        assert term["gross_amount_cents"] == PRICE_1205
        assert term["deferred_balance_cents"] == PRICE_1205
        assert term["recognized_balance_cents"] == 0
        assert_term_balance_invariant(term)

    def test_final_issue_recognition_absorbs_rounding_residual(self, api):
        """A 1205-cent, 12-issue PRO_RATA_ISSUE term recognizes 100 cents on
        each of the first eleven issues and exactly 105 on the final issue —
        the residual is absorbed so recognized + deferred lands on gross
        exactly, with no cents leaked by per-issue rounding.

        PRD §3.5: "Under `PRO_RATA_ISSUE`, each issue of the term recognizes the term's `gross_amount_cents` divided by `issues_in_term`, rounded half up to whole cents — except the term's final issue, identified when the count of `RECOGNITION` entries already posted against the term has reached one less than `issues_in_term`, which instead recognizes whatever amount remains so that `recognized_balance_cents` and `deferred_balance_cents` together equal `gross_amount_cents` exactly."
        PRD §2.10: "A term whose entire gross has been recognized stands `FULLY_RECOGNIZED`; a cancelled term ends `REFUNDED` or `PARTIALLY_REFUNDED` as described in §3.6."

        Design: Difficulty/combinatorial_formula/deferred_revenue_residual_absorption_rounding_order
        """
        set_clock()
        pub = create_publication(deferred_revenue_method="PRO_RATA_ISSUE")
        issue_1 = create_issue(pub["id"], issue_number=1)
        sub = _activate_with_term(pub["id"], create_subscriber()["id"], issue_1["id"])
        term_id = get_first_term(pub["id"], sub["id"])["id"]

        # Issue 1 is mailed first, then eleven more sequential issues.
        drive_issue_to_mailed(pub["id"], issue_1["id"])
        term = get_first_term(pub["id"], sub["id"])
        assert term["recognized_balance_cents"] == 100
        assert term["deferred_balance_cents"] == 1105
        assert_term_balance_invariant(term)

        mail_sequential_issues(pub["id"], 10)  # issues 2..11
        term = get_first_term(pub["id"], sub["id"])
        assert term["recognized_balance_cents"] == 1100, (
            f"eleven issues at 100 cents each must total 1100, got {term['recognized_balance_cents']}"
        )
        assert term["deferred_balance_cents"] == 105
        assert_term_balance_invariant(term)

        mail_sequential_issues(pub["id"], 1)  # issue 12, the term's final issue
        term = get_first_term(pub["id"], sub["id"])
        assert term["recognized_balance_cents"] == PRICE_1205
        assert term["deferred_balance_cents"] == 0
        assert term["status"] == "FULLY_RECOGNIZED"
        assert_term_balance_invariant(term)

        entries = [
            e for e in list_term_revenue_entries(pub["id"], sub["id"], term_id)
            if e["entry_type"] == "RECOGNITION"
        ]
        amounts = sorted(e["amount_cents"] for e in entries)
        assert amounts == [100] * 11 + [105], (
            f"eleven 100-cent issues plus a 105-cent residual-absorbing final issue, got {amounts}"
        )
        assert sum(amounts) == PRICE_1205


class TestRecognizedPlusDeferredConservation:
    def test_invariant_holds_at_activation(self, api):
        """Immediately after activation the invariant recognized + deferred ==
        gross holds with the full price still deferred.

        PRD §2.10: "Every SubscriptionTerm records the cash received as `gross_amount_cents`, the still-unrecognized remainder as `deferred_balance_cents`, and the cumulative recognized portion as `recognized_balance_cents`; while the term stands `OPEN`, the recognized and deferred balances always sum exactly to the gross."
        PRD §3.2: "Activation creates the first **SubscriptionTerm** with `term_index` 1, its `term_start_issue_id` equal to the subscription's start issue, `issues_in_term` equal to `term_issues`, `gross_amount_cents` and `deferred_balance_cents` both equal to the price paid, and `recognition_variant` snapshotted from the publication's current `deferred_revenue_method`."

        Design: Difficulty/compensating_invariant/deferred_revenue_recognized_plus_deferred_equals_gross
        """
        set_clock()
        pub = create_publication()
        issue = create_issue(pub["id"])
        sub = _activate_with_term(pub["id"], create_subscriber()["id"], issue["id"])
        term = get_first_term(pub["id"], sub["id"])
        assert term["gross_amount_cents"] == PRICE_1205
        assert term["recognized_balance_cents"] == 0
        assert term["deferred_balance_cents"] == PRICE_1205
        assert_term_balance_invariant(term)

    def test_invariant_conserved_across_recognition_event(self, api):
        """Mailing an issue moves 100 cents from deferred to recognized while
        the sum stays pinned to the 1205-cent gross.

        PRD §2.10: "Every SubscriptionTerm records the cash received as `gross_amount_cents`, the still-unrecognized remainder as `deferred_balance_cents`, and the cumulative recognized portion as `recognized_balance_cents`; while the term stands `OPEN`, the recognized and deferred balances always sum exactly to the gross."
        PRD §3.5: "Each recognition posts an entry with `entry_type` `RECOGNITION` and `variant` `PRO_RATA_ISSUE`, increases `recognized_balance_cents`, and decreases `deferred_balance_cents` by the same amount, with `recognized_at` set to the issue's `mail_date`."

        Design: Difficulty/compensating_invariant/deferred_revenue_recognized_plus_deferred_equals_gross
        """
        set_clock()
        pub = create_publication()
        issue = create_issue(pub["id"])
        sub = _activate_with_term(pub["id"], create_subscriber()["id"], issue["id"])

        drive_issue_to_mailed(pub["id"], issue["id"])
        term = get_first_term(pub["id"], sub["id"])
        assert term["recognized_balance_cents"] == 100
        assert term["deferred_balance_cents"] == 1105
        assert_term_balance_invariant(term)

    def test_cancel_before_any_issue_fully_refunds_and_liquidates(self, api):
        """Cancelling before any issue is served refunds the entire balance:
        a REFUND_LIQUIDATION entry for the negative of the full deferred
        balance zeroes the liability and the term ends REFUNDED.

        PRD §3.6: "The refund is computed from the cancelled term's remaining `deferred_balance_cents`: when no issues have been served, the entire balance is refunded; when one, two, or three issues have been served, ninety percent of the balance; when more than three have been served, fifty percent."
        PRD §3.6: "The unrefunded remainder is recognized immediately as a `RECOGNITION` entry, and a second entry of type `REFUND_LIQUIDATION` for the negative of the entire remaining deferred balance zeroes out the liability. The term is then marked `REFUNDED` when the full balance was refunded, or `PARTIALLY_REFUNDED` otherwise."

        Design: Difficulty/compensating_invariant/deferred_revenue_recognized_plus_deferred_equals_gross
        """
        set_clock()
        pub = create_publication()
        issue = create_issue(pub["id"])
        sub = _activate_with_term(pub["id"], create_subscriber()["id"], issue["id"])
        term_id = get_first_term(pub["id"], sub["id"])["id"]

        cancelled = validate_success(api.cancel_subscription(pub["id"], sub["id"], CM_H))
        assert cancelled["status"] == "CANCELLED"

        term = get_first_term(pub["id"], sub["id"])
        assert term["deferred_balance_cents"] == 0, (
            f"the liquidation entry must zero out the liability, got {term['deferred_balance_cents']}"
        )
        assert term["status"] == "REFUNDED", (
            f"full refund marks the term REFUNDED, got {term['status']}"
        )
        assert term["recognized_balance_cents"] == 0, (
            "with the entire balance refunded, nothing remains recognized"
        )

        entries = list_term_revenue_entries(pub["id"], sub["id"], term_id)
        liquidations = [e for e in entries if e["entry_type"] == "REFUND_LIQUIDATION"]
        assert len(liquidations) == 1, f"exactly one REFUND_LIQUIDATION entry expected, got {liquidations}"
        assert liquidations[0]["amount_cents"] == -PRICE_1205, (
            f"liquidation must be the negative of the entire deferred balance, got "
            f"{liquidations[0]['amount_cents']}"
        )

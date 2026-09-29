"""Money, metric and window arithmetic of the program: response posture edges,
company reporting scores, the payment waterfall, renewal pricing, interval
geometry, the premises roll-up and the two conservation identities.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U

# Every chargeable occurrence below is ruled at this instant, which is strictly
# after the first permit's new-installation grace through of 2026-08-31.
DETERMINATION_CLOCK = "2026-09-20T01:00:00Z"

# occurrence instant, cause code, dispatch-request overrides. The fourth
# occurrence is a duress signal lodged with no call verification at all, so it
# carries the non-ECV surcharge while still verifying sufficiently.
_OCCURRENCES = [
    ("2026-09-15T03:09:00Z", "OPERATOR_ERROR", {}),
    ("2026-09-16T04:00:00Z", "OPEN_DOOR_WINDOW", {}),
    ("2026-09-17T04:00:00Z", "EQUIPMENT_MALFUNCTION", {}),
    (
        "2026-09-18T04:00:00Z",
        "OPERATOR_ERROR",
        {"alarm_type": "DURESS", "verification_method": "NONE", "call_attempts": []},
    ),
    ("2026-09-19T04:00:00Z", "OPEN_DOOR_WINDOW", {}),
    ("2026-09-19T05:00:00Z", "EQUIPMENT_MALFUNCTION", {}),
]


def _counted_run(api, count):
    """A COMMERCIAL premises carrying ``count`` chargeable occurrences.

    Each occurrence gets its own permitted system, and every determination is
    taken with the logical clock parked at ``DETERMINATION_CLOCK``.
    """
    bundle = X.setup_program_baseline(
        api,
        clock=DETERMINATION_CLOCK,
        site_overrides={"occupancy_class": "COMMERCIAL"},
        contact_count=3,
        system_count=count,
        installed_at=C.CLOCK_STARTUP_UTC,
    )
    incidents = []
    for index in range(count):
        occurred_at, cause_code, overrides = _OCCURRENCES[index]
        incidents.append(
            X.create_counted_incident(
                api,
                bundle,
                bundle.system_ids[index],
                occurred_at,
                cause_code=cause_code,
                **overrides,
            )
        )
    return bundle, incidents


def _two_permit_site(api):
    """Two systems permitted at one premises on 2026-08-01, raising two
    5500-cent issue-fee invoices in issuance order."""
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_STARTUP_UTC,
        installed_at=C.CLOCK_STARTUP_UTC,
        system_count=2,
    )
    invoices = X.invoices_of_site(api, bundle.site_id, kind="PERMIT_ISSUE_FEE")
    assert len(invoices) == 2, f"expected two issue-fee invoices, got {len(invoices)}"
    return bundle, invoices


def test_site_response_posture_suspends_only_once_the_clock_enters_the_served_window(api):
    """A served suspension order withholds police response only while the clock
    sits inside its closed interval; before it the premises is merely on
    probation.

    "And when `chargeable_count_window` reaches or exceeds `suspension_threshold_count`, an enforcement order is auto-proposed for the premises: a suspension order in `PROPOSED` with `basis` of `EXCESSIVE_FALSE_ALARMS`, its `triggering_incident_id` set to this incident, `effective_from` at the logical clock plus 10 days and `effective_through` at 30 days after that."
    "If the premises has a suspension order in `EFFECTIVE` or `REINSTATEMENT_PENDING` whose closed interval contains the current instant, the posture is `RESPONSE_SUSPENDED`."
    "Otherwise, if `chargeable_count_window` is at or above `probation_threshold_count`, the posture is `RESPONSE_PROBATION`."

    Six chargeable occurrences ruled at 2026-09-20T01:00:00Z auto-propose an
    order running 2026-09-30T01:00:00Z through 2026-10-30T01:00:00Z. Serving it
    at 2026-09-20T01:00:00Z therefore leaves the clock outside that interval, so
    the cascade falls through to the probation arm on the window count of 6;
    moving the clock to 2026-10-05T00:00:00Z puts it inside the interval and the
    first arm wins.

    Design: Corner/calculations/site_response_posture_suspends_only_once_the_clock_enters_the_served_window
    """
    bundle, incidents = _counted_run(api, 6)

    orders = X.orders_of_site(api, bundle.site_id)
    assert len(orders) == 1, f"exactly one order should be auto-proposed, got {len(orders)}"
    order = orders[0]
    A.assert_status(order, "PROPOSED")
    assert order["basis"] == "EXCESSIVE_FALSE_ALARMS"
    assert order["triggering_incident_id"] == incidents[5].incident_id
    assert order["effective_from"].startswith("2026-09-30T01:00:00")
    assert order["effective_through"].startswith("2026-10-30T01:00:00")

    validate_success(api.serve_suspension_order(order["id"], U.PERMIT_CLERK), 200)

    after_serve = X.get_site(api, bundle.site_id)
    A.assert_status(after_serve, "RESPONSE_PROBATION", field="response_status")
    assert after_serve["chargeable_count_window"] == 6

    X.set_clock(api, "2026-10-05T00:00:00Z")

    inside_window = X.get_site(api, bundle.site_id)
    A.assert_status(inside_window, "RESPONSE_SUSPENDED", field="response_status")
    assert inside_window["chargeable_count_window"] == 6


def test_site_response_posture_stays_active_one_incident_below_the_probation_threshold(api):
    """Three chargeable occurrences leave the premises in good standing because
    the probation comparison is inclusive at four.

    "Otherwise, if `chargeable_count_window` is at or above `probation_threshold_count`, the posture is `RESPONSE_PROBATION`. Otherwise it is `RESPONSE_ACTIVE`."
    "Both thresholds are inclusive: with the defaults, a window count of 4 puts the premises on probation and 3 does not, and a count of 6 proposes a suspension while 5 does not."
    "Fifth, `renewal_block_active` becomes true exactly when `outstanding_balance_cents` is at or above `delinquent_balance_block_cents` — the comparison is inclusive, so a balance of exactly 50000 cents blocks renewal."

    Three permitted systems bill 3 * 5500 = 16500 cents, and the third
    occurrence prices at the 10000-cent tier times the COMMERCIAL multiplier
    1.50 = 15000 plus a 750-cent administrative fee = 15750, for an outstanding
    balance of 32250 cents, which is below the 50000-cent block.

    Design: Corner/calculations/site_response_posture_stays_active_one_incident_below_the_probation_threshold
    """
    bundle, incidents = _counted_run(api, 3)

    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_window"] == 3
    A.assert_status(site, "RESPONSE_ACTIVE", field="response_status")
    A.assert_money_cents(site["outstanding_balance_cents"], 32250, "outstanding_balance_cents")
    assert site["renewal_block_active"] is False

    assert X.orders_of_site(api, bundle.site_id) == []

    fee_invoice = X.get_invoice(api, incidents[2].invoice_id)
    A.assert_invoice_totals(
        fee_invoice, subtotal_cents=15000, admin_fee_cents=750, assessed_cents=15750
    )


def test_company_reporting_compliance_score_volume_weighted_ignores_a_zero_volume_period(api):
    """Under volume weighting a period with no recorded dispatches carries no
    weight, so its zero score cannot pull the company down.

    "`system_dispatch_count` is the number of dispatch requests attributed to that company whose `occurred_at` falls inside the closed period interval and whose status is not `CANCELLED` — a `REFUSED` request still counts, because the company did ask for dispatch even though the city declined, and only a cancellation removes the ask."
    "`variance_pct` is that count divided by the greater of 1 and `system_dispatch_count`, at four decimal places."
    "`period_accuracy` is 1 minus the lesser of 1 and `variance_pct`, at four decimal places, so accuracy floors at zero however wild the claim."
    "`period_ecv_rate` is the lesser of 1 and `ecv_attempt_count` divided by the greater of 1 and `reported_dispatch_count`, at four decimal places, so extra verification attempts earn no credit above a rate of 1."
    "`period_score` is 0.6 times `period_accuracy` plus 0.4 times `period_ecv_rate`, rounded half up to two decimal places."
    "Under `VOLUME_WEIGHTED`, the weight total is the sum of `system_dispatch_count` across the set, and the score is the sum of each `period_score` times its own `system_dispatch_count` divided by that total — falling back to the plain mean of the period scores when the weight total is zero."

    August holds no dispatch request, so its metrics are 3/1 = 3.0000 variance,
    0.0000 accuracy, 0.0000 verification rate and a 0.00 period score with
    weight 0. September holds exactly one, giving 0.0000 variance, 1.0000
    accuracy, min(1, 2/1) = 1.0000 verification rate and a 1.00 score with
    weight 1. The company score is therefore (0.00*0 + 1.00*1) / 1 = 1.00.

    Design: Corner/calculations/company_reporting_compliance_score_volume_weighted_ignores_a_zero_volume_period
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_PRESENT_UTC,
        installed_at=C.CLOCK_STARTUP_UTC,
        company_overrides={"score_mode": "VOLUME_WEIGHTED"},
    )
    X.submit_dispatch_request(
        api, bundle, bundle.system_id, C.FIRST_CHARGEABLE_OCCURRED_AT
    )
    X.set_clock(api, "2026-09-30T00:00:00Z")

    august_id = X.submit_compliance_report(
        api,
        bundle,
        "2026-08-01T00:00:00Z",
        "2026-08-31T00:00:00Z",
        reported_dispatch_count=3,
        reported_cancellation_count=0,
        ecv_attempt_count=0,
    )
    september_id = X.submit_compliance_report(
        api,
        bundle,
        "2026-09-01T00:00:00Z",
        "2026-09-30T00:00:00Z",
        reported_dispatch_count=1,
        reported_cancellation_count=0,
        ecv_attempt_count=2,
    )
    X.review_compliance_report(
        api, september_id, "ACCEPT", variance_notes="Counts reconcile exactly."
    )
    flagged = X.review_compliance_report(
        api,
        august_id,
        "FLAG_VARIANCE",
        variance_notes="Three dispatches reported for a month with none on record.",
    )
    A.assert_status(flagged, "VARIANCE_FLAGGED")

    august = X.get_report(api, august_id)
    assert august["system_dispatch_count"] == 0
    assert august["variance_count"] == 3
    A.assert_ratio_4dp(august["variance_pct"], 3.0000, "august variance_pct")
    A.assert_ratio_4dp(august["period_accuracy"], 0.0000, "august period_accuracy")
    A.assert_ratio_4dp(august["period_ecv_rate"], 0.0000, "august period_ecv_rate")
    A.assert_score_2dp(august["period_score"], 0.00, "august period_score")

    september = X.get_report(api, september_id)
    assert september["system_dispatch_count"] == 1
    assert september["variance_count"] == 0
    A.assert_ratio_4dp(september["variance_pct"], 0.0000, "september variance_pct")
    A.assert_ratio_4dp(september["period_accuracy"], 1.0000, "september period_accuracy")
    A.assert_ratio_4dp(september["period_ecv_rate"], 1.0000, "september period_ecv_rate")
    A.assert_score_2dp(september["period_score"], 1.00, "september period_score")
    A.assert_status(september, "ACCEPTED")

    company = X.get_company(api, bundle.company_id)
    A.assert_score_2dp(company["reporting_compliance_score"], 1.00, "reporting_compliance_score")
    A.assert_status(company, "ACTIVE")
    assert company["consecutive_flagged_report_count"] == 1


def test_company_reporting_compliance_score_period_equal_halves_the_same_two_reports(api):
    """The same two reports scored with equal period weight average to 0.50 and
    cost the company its good standing.

    "Under `PERIOD_EQUAL`, the score is simply the sum of the period scores divided by the number of entries."
    "Finally `company_probation_score_threshold` (0.70) and `company_suspension_score_threshold` (0.50) are the reporting-score levels below which a monitoring company loses standing; both comparisons are strict, so a score exactly equal to a threshold is *not* below it."
    "From `ACTIVE`, a recomputed score below `company_probation_score_threshold` but at or above `company_suspension_score_threshold` moves the company to `PROBATION`, stamping `probation_started_at`, `status_reason` and `last_status_action_at`; dispatch requests are still accepted on probation."

    The August period still scores 0.00 and the September period 1.00, but the
    company score is (0.00 + 1.00) / 2 = 0.50. That is strictly below 0.70 and
    is not strictly below 0.50, so the company lands on probation anchored at
    the reviewing instant 2026-09-30T00:00:00Z rather than being suspended.

    Design: Corner/calculations/company_reporting_compliance_score_period_equal_halves_the_same_two_reports
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_PRESENT_UTC,
        installed_at=C.CLOCK_STARTUP_UTC,
        company_overrides={"score_mode": "PERIOD_EQUAL"},
    )
    X.submit_dispatch_request(
        api, bundle, bundle.system_id, C.FIRST_CHARGEABLE_OCCURRED_AT
    )
    X.set_clock(api, "2026-09-30T00:00:00Z")

    august_id = X.submit_compliance_report(
        api,
        bundle,
        "2026-08-01T00:00:00Z",
        "2026-08-31T00:00:00Z",
        reported_dispatch_count=3,
        reported_cancellation_count=0,
        ecv_attempt_count=0,
    )
    september_id = X.submit_compliance_report(
        api,
        bundle,
        "2026-09-01T00:00:00Z",
        "2026-09-30T00:00:00Z",
        reported_dispatch_count=1,
        reported_cancellation_count=0,
        ecv_attempt_count=2,
    )
    X.review_compliance_report(
        api, september_id, "ACCEPT", variance_notes="Counts reconcile exactly."
    )
    X.review_compliance_report(
        api,
        august_id,
        "FLAG_VARIANCE",
        variance_notes="Three dispatches reported for a month with none on record.",
    )

    A.assert_score_2dp(
        X.get_report(api, august_id)["period_score"], 0.00, "august period_score"
    )
    A.assert_score_2dp(
        X.get_report(api, september_id)["period_score"], 1.00, "september period_score"
    )

    company = X.get_company(api, bundle.company_id)
    A.assert_score_2dp(company["reporting_compliance_score"], 0.50, "reporting_compliance_score")
    A.assert_status(company, "PROBATION")
    assert company["probation_started_at"].startswith("2026-09-30T00:00:00")


def test_compliance_report_period_metrics_counts_a_refused_dispatch_request(api):
    """A dispatch request the city refused still counts as an ask, so a report
    claiming no dispatches for that month reconciles to a full variance.

    "`system_dispatch_count` is the number of dispatch requests attributed to that company whose `occurred_at` falls inside the closed period interval and whose status is not `CANCELLED` — a `REFUSED` request still counts, because the company did ask for dispatch even though the city declined, and only a cancellation removes the ask."
    "`variance_count` is the absolute difference between `reported_dispatch_count` and `system_dispatch_count`, so over-reporting and under-reporting are penalised identically."
    "The report is created in `SUBMITTED` with `correction_count` 0 and `reviewed_at`, `reviewed_by_user_id` and `variance_notes` null."
    "Flagging requires an actual discrepancy — `variance_pct` must be strictly above 0.1000, else `ERR_NO_REPORTABLE_VARIANCE` — and moves the report to `VARIANCE_FLAGGED`, storing the `variance_notes` and incrementing `consecutive_flagged_report_count`."

    One refused September request against a claim of zero gives a
    system_dispatch_count of 1, a variance_count of |0 - 1| = 1 and a
    variance_pct of 1/max(1, 1) = 1.0000. Accuracy is 1 - min(1, 1.0000) =
    0.0000, the verification rate is min(1, 0/max(1, 0)) = 0.0000 and the period
    score is 0.6 * 0 + 0.4 * 0 = 0.00. The 1.0000 variance is strictly above
    0.1000, so the row is flag-eligible.

    Design: Corner/calculations/compliance_report_period_metrics_counts_a_refused_dispatch_request
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_PRESENT_UTC, installed_at=C.CLOCK_STARTUP_UTC
    )
    request_id = X.submit_dispatch_request(
        api, bundle, bundle.system_id, C.FIRST_CHARGEABLE_OCCURRED_AT
    )
    refused = api.refuse_dispatch_request(
        request_id, {"refusal_reason": "VERIFIED_RESPONSE_MISSING"}, U.DISPATCH_SUPERVISOR
    )
    validate_success(refused, 200)
    A.assert_status(get_success_data(refused), "REFUSED")
    assert get_success_data(refused)["refusal_reason"] == "VERIFIED_RESPONSE_MISSING"

    X.set_clock(api, "2026-09-30T00:00:00Z")

    response = api.create_compliance_report(
        F.compliance_report_payload(
            bundle.company_id,
            "2026-09-01T00:00:00Z",
            "2026-09-30T00:00:00Z",
            reported_dispatch_count=0,
            reported_cancellation_count=0,
            ecv_attempt_count=0,
        ),
        bundle.operator_headers,
    )
    validate_success(response, 201)
    report = get_success_data(response)

    assert report["system_dispatch_count"] == 1
    assert report["variance_count"] == 1
    A.assert_ratio_4dp(report["variance_pct"], 1.0000, "variance_pct")
    A.assert_ratio_4dp(report["period_accuracy"], 0.0000, "period_accuracy")
    A.assert_ratio_4dp(report["period_ecv_rate"], 0.0000, "period_ecv_rate")
    A.assert_score_2dp(report["period_score"], 0.00, "period_score")
    A.assert_status(report, "SUBMITTED")
    assert report["correction_count"] == 0
    assert report["variance_pct"] > 0.1000


def test_ecv_verification_sufficiency_two_calls_to_one_contact_is_insufficient(api):
    """Two call attempts placed to the same responsible party freeze a distinct
    contact count of one and fail two-call verification.

    "`distinct_ecv_contact_count` is then the number of distinct contact identifiers surviving that filter, defaulting to 0 for an empty log."
    "Two consequences follow directly and are both intended: a log of two calls placed to the *same* contact yields a distinct count of 1 and is therefore insufficient for a two-call request even though two calls really were made, while a log of exactly two calls to *different* contacts yields 2, meets the inclusive threshold and is sufficient."
    "The same submission also freezes `system_permitted_at_occurrence`, which is true when the system's status was `PERMITTED` at that moment."
    "**Verification sufficiency is computed once, at submission, and frozen on the row.**"

    The threshold counts distinct contact identifiers, not attempts, so a
    TWO_CALL_ECV log naming one contact twice freezes
    distinct_ecv_contact_count 1 and ecv_sufficient false while the row is still
    accepted into SUBMITTED.

    Design: Corner/calculations/ecv_verification_sufficiency_two_calls_to_one_contact_is_insufficient
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_PRESENT_UTC,
        installed_at=C.CLOCK_STARTUP_UTC,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )
    occurred_at = "2026-09-15T03:09:00Z"
    duplicate_log = [
        F.call_attempt(bundle.contact_ids[0], "2026-09-15T03:10:00Z", "NO_ANSWER"),
        F.call_attempt(bundle.contact_ids[0], "2026-09-15T03:14:00Z", "VOICEMAIL"),
    ]
    response = api.create_dispatch_request(
        F.dispatch_request_payload(
            bundle.system_id,
            occurred_at,
            duplicate_log,
            verification_method="TWO_CALL_ECV",
            alarm_type="BURGLARY",
        ),
        bundle.operator_headers,
    )
    validate_success(response, 201)
    request = get_success_data(response)

    assert request["distinct_ecv_contact_count"] == 1
    assert request["ecv_sufficient"] is False
    assert request["system_permitted_at_occurrence"] is True
    A.assert_status(request, "SUBMITTED")

    reread = X.get_site(api, bundle.site_id)
    assert reread["ecv_callable_contact_count"] == 2


def _invoice_of_permit(api, site_id, permit_id):
    """The single issue-fee invoice raised by one permit's issuance."""
    rows = X.invoices_of_site(api, site_id, alarm_permit_id=permit_id)
    assert len(rows) == 1, f"expected one invoice for permit {permit_id}, got {len(rows)}"
    return rows[0]


def _ordered_allocations(api, payment_id, expected_count):
    rows = X.allocations_of_payment(api, payment_id)
    assert len(rows) == expected_count, (
        f"expected {expected_count} allocation lines, got {len(rows)}"
    )
    for row in rows:
        A.assert_allocation_row(row)
        assert row["payment_record_id"] == payment_id
        A.assert_status(row, "APPLIED")
    return sorted(rows, key=lambda row: row["sequence_index"])


def test_payment_waterfall_allocation_breaks_a_stage_and_due_date_tie_on_created_at(api):
    """Two invoices sharing a stage and a due date are filled in issuance order,
    the first taking all it is owed before the second sees a cent.

    "Candidates are ordered by dunning stage rank descending, where `REFERRED` ranks 4, `FINAL_NOTICE` ranks 3, `NOTICE` ranks 2 and `CURRENT` ranks 1; ties are broken by `due_on` ascending and then by `created_at` ascending."
    "The row identifier is never an ordering input."
    "Walking that order with a running remainder, each invoice takes the lesser of the remainder and its own `outstanding_cents`."
    "The invoice's `paid_cents` rises by that amount and its `payment_status` becomes `PAID` when `paid_cents` plus `adjusted_cents` equals `assessed_cents`, and `PARTIALLY_PAID` otherwise."

    Both issue-fee invoices are raised at 2026-08-01 into CURRENT with due_on
    2026-08-31, so stage rank and due date tie and only created_at can order
    them. A 6000-cent tender takes min(6000, 5500) = 5500 for the first line and
    min(500, 5500) = 500 for the second, leaving the second owing 5000 and the
    premises owing 5000 in total.

    Design: Corner/calculations/payment_waterfall_allocation_breaks_a_stage_and_due_date_tie_on_created_at
    """
    bundle, invoices = _two_permit_site(api)
    first, second = sorted(invoices, key=lambda row: row["invoice_number"])
    assert first["alarm_permit_id"] == bundle.permit_ids[0]
    assert second["alarm_permit_id"] == bundle.permit_ids[1]
    for invoice in (first, second):
        A.assert_invoice_totals(
            invoice,
            assessed_cents=C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS,
            outstanding_cents=C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS,
            payment_status="UNPAID",
            collections_stage="CURRENT",
        )
        assert invoice["due_on"].startswith("2026-08-31")

    payment_id = X.post_payment(api, bundle, 6000, C.CLOCK_STARTUP_UTC)

    lines = _ordered_allocations(api, payment_id, 2)
    assert lines[0]["sequence_index"] == 1
    assert lines[0]["penalty_invoice_id"] == first["id"]
    A.assert_money_cents(lines[0]["amount_cents"], 5500, "first line amount_cents")
    assert lines[1]["sequence_index"] == 2
    assert lines[1]["penalty_invoice_id"] == second["id"]
    A.assert_money_cents(lines[1]["amount_cents"], 500, "second line amount_cents")

    A.assert_invoice_totals(
        X.get_invoice(api, first["id"]),
        paid_cents=5500,
        outstanding_cents=0,
        payment_status="PAID",
    )
    A.assert_invoice_totals(
        X.get_invoice(api, second["id"]),
        paid_cents=500,
        outstanding_cents=5000,
        payment_status="PARTIALLY_PAID",
    )

    payment = X.get_payment(api, payment_id)
    A.assert_money_cents(payment["allocated_cents"], 6000, "allocated_cents")
    A.assert_money_cents(payment["credited_cents"], 0, "credited_cents")
    A.assert_cash_conservation(payment)

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["outstanding_balance_cents"], 5000, "outstanding_balance_cents")
    A.assert_money_cents(site["credit_balance_cents"], 0, "credit_balance_cents")


def test_payment_waterfall_allocation_parks_the_unallocatable_remainder_as_credit(api):
    """A tender larger than everything owed settles both invoices and parks the
    residual as premises credit instead of over-applying it.

    "Whatever remains after every candidate is exhausted becomes the payment's `credited_cents` and is added to the premises' `credit_balance_cents`; `allocated_cents` is the tendered amount minus that credit."
    "A parked credit is not spent by itself: it is released only by a later payment's allocation or by a void reversal, never auto-consumed by the next invoice the premises incurs."
    "Walking that order with a running remainder, each invoice takes the lesser of the remainder and its own `outstanding_cents`."

    The premises owes 5500 + 5500 = 11000 cents. A 12000-cent tender applies
    5500 and then 5500, exhausting the candidate set with 12000 - 11000 = 1000
    cents left over, so credited_cents is 1000, allocated_cents is 11000 and the
    premises holds 1000 cents of credit against nothing.

    Design: Corner/calculations/payment_waterfall_allocation_parks_the_unallocatable_remainder_as_credit
    """
    bundle, invoices = _two_permit_site(api)
    first, second = sorted(invoices, key=lambda row: row["invoice_number"])

    payment_id = X.post_payment(api, bundle, 12000, C.CLOCK_STARTUP_UTC, method="ACH")

    lines = _ordered_allocations(api, payment_id, 2)
    assert [line["sequence_index"] for line in lines] == [1, 2]
    assert [line["penalty_invoice_id"] for line in lines] == [first["id"], second["id"]]
    for line in lines:
        A.assert_money_cents(line["amount_cents"], 5500, "line amount_cents")

    for invoice_id in (first["id"], second["id"]):
        A.assert_invoice_totals(
            X.get_invoice(api, invoice_id),
            paid_cents=5500,
            outstanding_cents=0,
            payment_status="PAID",
        )

    payment = X.get_payment(api, payment_id)
    A.assert_money_cents(payment["allocated_cents"], 11000, "allocated_cents")
    A.assert_money_cents(payment["credited_cents"], 1000, "credited_cents")
    A.assert_cash_conservation(payment)

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["credit_balance_cents"], 1000, "credit_balance_cents")
    A.assert_money_cents(site["outstanding_balance_cents"], 0, "outstanding_balance_cents")


def test_payment_waterfall_allocation_prefers_the_higher_dunning_stage(api):
    """A dunned invoice is settled ahead of a newer current one, and the newer
    invoice receives nothing at all.

    "Candidates are ordered by dunning stage rank descending, where `REFERRED` ranks 4, `FINAL_NOTICE` ranks 3, `NOTICE` ranks 2 and `CURRENT` ranks 1; ties are broken by `due_on` ascending and then by `created_at` ascending."
    "The city collects its most desperate debt first: a referred invoice is paid before an older but merely current one, so `due_on` only decides between invoices standing at the same stage."
    "The nightly run advances `CURRENT → NOTICE` once `days_delinquent` is at least 1, and `NOTICE → FINAL_NOTICE` once it is at least 30; both steps require `outstanding_cents` above zero and require that the linked incident, when there is one, is not in `APPEALED`."
    "Step two: `late_penalty_cents` is that principal times `late_penalty_pct`, rounded half up, and is added into `assessed_cents` — once per invoice, never twice."
    "An invoice can be `REFERRED` and still reach `PAID`; it can be `PAID` while still sitting at `FINAL_NOTICE` until the next nightly run resettles the stage."

    The first invoice falls due 2026-08-31, so on 2026-09-01 it is one day
    delinquent: the nightly run adds 5500 * 0.10 = 550 cents of late penalty and
    moves it to NOTICE at 6050 cents assessed. The second permit's invoice is
    raised the same day at CURRENT, due 2026-10-01. Stage rank 2 beats stage rank
    1, so the whole 6050-cent tender goes to the dunned invoice as a single line
    and the premises still owes the untouched 5500.

    Design: Corner/calculations/payment_waterfall_allocation_prefers_the_higher_dunning_stage
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, installed_at=C.CLOCK_STARTUP_UTC
    )
    first = _invoice_of_permit(api, bundle.site_id, bundle.permit_ids[0])
    assert first["due_on"].startswith("2026-08-31")

    X.set_clock(api, "2026-09-01T00:00:00Z")
    X.run_nightly(api)

    dunned = X.get_invoice(api, first["id"])
    assert dunned["days_delinquent"] == 1
    A.assert_money_cents(dunned["late_penalty_cents"], 550, "late_penalty_cents")
    A.assert_invoice_totals(
        dunned,
        subtotal_cents=C.PERMIT_ISSUE_INVOICE_SUBTOTAL_CENTS,
        admin_fee_cents=C.PERMIT_ISSUE_INVOICE_ADMIN_CENTS,
        assessed_cents=6050,
        outstanding_cents=6050,
        payment_status="UNPAID",
        collections_stage="NOTICE",
    )

    _system_id, permit2_id = X.add_permitted_system(api, bundle)
    second = _invoice_of_permit(api, bundle.site_id, permit2_id)
    A.assert_invoice_totals(
        second,
        assessed_cents=C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS,
        payment_status="UNPAID",
        collections_stage="CURRENT",
    )
    assert second["due_on"].startswith("2026-10-01")

    payment_id = X.post_payment(api, bundle, 6050, "2026-09-01T00:00:00Z", method="CARD")

    lines = _ordered_allocations(api, payment_id, 1)
    assert lines[0]["sequence_index"] == 1
    assert lines[0]["penalty_invoice_id"] == first["id"]
    A.assert_money_cents(lines[0]["amount_cents"], 6050, "amount_cents")

    A.assert_invoice_totals(
        X.get_invoice(api, first["id"]),
        assessed_cents=6050,
        paid_cents=6050,
        outstanding_cents=0,
        payment_status="PAID",
        collections_stage="NOTICE",
    )
    A.assert_invoice_totals(
        X.get_invoice(api, second["id"]),
        paid_cents=0,
        outstanding_cents=C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS,
        payment_status="UNPAID",
        collections_stage="CURRENT",
    )

    payment = X.get_payment(api, payment_id)
    A.assert_money_cents(payment["allocated_cents"], 6050, "allocated_cents")
    A.assert_money_cents(payment["credited_cents"], 0, "credited_cents")
    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["outstanding_balance_cents"], 5500, "outstanding_balance_cents")


def _paid_up_permit_in_grace(api, grace_clock):
    """One permitted system whose issue fee is settled, aged into GRACE.

    The permit runs 2026-08-01 .. 2027-08-01 with grace through 2027-08-31; a
    nightly run at 2027-07-05 makes it renewable and a second run at
    ``grace_clock`` carries it into grace.
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, installed_at=C.CLOCK_STARTUP_UTC
    )
    issue_invoice = _invoice_of_permit(api, bundle.site_id, bundle.permit_ids[0])
    X.pay_invoice_in_full(api, bundle, issue_invoice["id"], C.CLOCK_STARTUP_UTC)

    X.set_clock(api, "2027-07-05T00:00:00Z")
    X.run_nightly(api)
    renewable = X.get_permit(api, bundle.permit_ids[0])
    A.assert_status(renewable, "RENEWAL_DUE")

    X.set_clock(api, grace_clock)
    X.run_nightly(api)
    permit = X.get_permit(api, bundle.permit_ids[0])
    A.assert_status(permit, "GRACE")
    assert permit["term_end_at"].startswith("2027-08-01T00:00:00")
    assert permit["grace_through_at"].startswith("2027-08-31T00:00:00")
    return bundle, permit


def _renewal_invoice(api, site_id):
    rows = X.invoices_of_site(api, site_id, kind="PERMIT_RENEWAL_FEE")
    assert len(rows) == 1, f"expected one renewal invoice, got {len(rows)}"
    return rows[0]


def test_permit_renewal_fee_fifteen_days_late_selects_the_first_late_tier(api):
    """A renewal taken exactly fifteen days past the term end is priced on the
    first late tier, not the second.

    "The days late on a renewal are the whole days between the permit's `term_end_at` and the logical clock, computed by dividing the elapsed UTC seconds by 86400 and discarding the remainder, with any negative result clamped to 0."
    "The late tier is the first entry of `late_renewal_tiers`, in declared order, whose `max_days_late` is null or is at least the days late."
    "A renewal is therefore priced as one `PERMIT_RENEWAL` line at `permit_renewal_fee_cents`, plus — only when the late fee is above zero — one `LATE_RENEWAL` line at that fee."
    "On success the permit returns to `ACTIVE` with `term_start_at` set to the logical clock, `term_end_at` recomputed as that instant plus `permit_term_days`, `grace_through_at` recomputed from the new term end, `renewal_count` increased by 1, `last_renewed_at` stamped, and `new_installation_grace_through` left null."
    "`admin_fee_cents` is then the subtotal times `admin_fee_pct`, rounded half up once on the already-rounded subtotal, and clamped upward to `admin_fee_min_cents` and downward to `admin_fee_max_cents`; the clamp binds before the fee joins the assessment, so a 200-cent subtotal still carries the 500-cent floor and a 200000-cent subtotal carries the 5000-cent ceiling."

    From term end 2027-08-01 to 2027-08-16 is 15 whole days, and the first tier
    whose max_days_late is at least 15 is the 15-day entry at 1500 cents, so the
    ladder never reaches the 30-day 3000-cent entry. The invoice carries 3000 +
    1500 = 4500 cents of subtotal; 4500 * 0.05 is 225, which the 500-cent floor
    clamps upward, giving 4500 + 500 = 5000 cents assessed. The new term runs
    2027-08-16 to 2028-08-15, 365 whole days across the 2028 leap day.

    Design: Corner/calculations/permit_renewal_fee_fifteen_days_late_selects_the_first_late_tier
    """
    bundle, permit = _paid_up_permit_in_grace(api, "2027-08-16T00:00:00Z")

    response = api.renew_permit(
        permit["id"], {"expected_alarm_permit_version": permit["version"]}, U.PERMIT_CLERK
    )
    validate_success(response, 200)
    renewed = get_success_data(response)

    A.assert_status(renewed, "ACTIVE")
    assert renewed["renewal_count"] == 1
    assert renewed["term_start_at"].startswith("2027-08-16T00:00:00")
    assert renewed["term_end_at"].startswith("2028-08-15T00:00:00")

    invoice = _renewal_invoice(api, bundle.site_id)
    assert invoice["alarm_permit_id"] == permit["id"]
    codes = [line["code"] for line in invoice["line_items"]]
    assert codes == ["PERMIT_RENEWAL", "LATE_RENEWAL"], f"unexpected line codes {codes}"
    A.assert_money_cents(invoice["line_items"][0]["extended_cents"], 3000, "PERMIT_RENEWAL line")
    A.assert_money_cents(invoice["line_items"][1]["extended_cents"], 1500, "LATE_RENEWAL line")
    A.assert_invoice_totals(
        invoice,
        subtotal_cents=4500,
        admin_fee_cents=500,
        assessed_cents=5000,
        outstanding_cents=5000,
        payment_status="UNPAID",
    )

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["outstanding_balance_cents"], 5000, "outstanding_balance_cents")


def test_permit_renewal_fee_thirty_days_late_is_still_renewable_at_the_second_tier(api):
    """The last legal day of grace is thirty days late, which is renewable and
    selects the second late tier rather than the open-ended one.

    "Note the interaction with the grace geometry: renewal is accepted while the clock is at or before `grace_through_at`, which with the default 30-day grace means days late of at most 30, and days late of exactly 30 is still renewable and selects the 3000-cent tier."
    "The open-ended 6000-cent tier is only reachable when the grace window is configured longer than the tier bounds."
    "The late tier is the first entry of `late_renewal_tiers`, in declared order, whose `max_days_late` is null or is at least the days late."
    "Renewing out of `GRACE` additionally requires the logical clock to be at or before `grace_through_at` — past that instant the nightly run has already expired the permit, and the attempt fails on the declared-transition check."

    From term end 2027-08-01 to 2027-08-31 is 30 whole days, which is exactly
    grace_through_at, so the nightly run leaves the permit in GRACE rather than
    expiring it. The 15-day tier no longer admits 30, so the 30-day tier at 3000
    cents applies: 3000 + 3000 = 6000 cents of subtotal, 6000 * 0.05 = 300
    clamped up to the 500-cent floor, and 6500 cents assessed. The new term runs
    2027-08-31 to 2028-08-30.

    Design: Corner/calculations/permit_renewal_fee_thirty_days_late_is_still_renewable_at_the_second_tier
    """
    bundle, permit = _paid_up_permit_in_grace(api, "2027-08-31T00:00:00Z")

    response = api.renew_permit(
        permit["id"], {"expected_alarm_permit_version": permit["version"]}, U.PERMIT_CLERK
    )
    validate_success(response, 200)
    renewed = get_success_data(response)

    A.assert_status(renewed, "ACTIVE")
    assert renewed["renewal_count"] == 1
    assert renewed["term_start_at"].startswith("2027-08-31T00:00:00")
    assert renewed["term_end_at"].startswith("2028-08-30T00:00:00")

    invoice = _renewal_invoice(api, bundle.site_id)
    codes = [line["code"] for line in invoice["line_items"]]
    assert codes == ["PERMIT_RENEWAL", "LATE_RENEWAL"], f"unexpected line codes {codes}"
    A.assert_money_cents(invoice["line_items"][1]["extended_cents"], 3000, "LATE_RENEWAL line")
    A.assert_invoice_totals(
        invoice,
        subtotal_cents=6000,
        admin_fee_cents=500,
        assessed_cents=6500,
        outstanding_cents=6500,
        payment_status="UNPAID",
    )


def test_docket_session_overlap_accepts_a_session_starting_exactly_fifteen_minutes_later(api):
    """The earliest legal back-to-back sitting for one officer starts exactly a
    fifteen-minute turnaround after the previous session ends.

    "The intervals are half-open, and a 15-minute turnaround buffer is applied on both sides of the existing session: a conflict exists when the new `session_start` is strictly before the existing `session_end` plus 15 minutes **and** the existing `session_start` is strictly before the new `session_end` plus 15 minutes."
    "Both arms are strict and the buffer is symmetric, so back-to-back sessions collide — a new session starting exactly at an existing session's end leaves a zero-minute gap, which is under the buffer — and the earliest legal back-to-back start is exactly the existing `session_end` plus 15 minutes, since strictness makes that value pass."
    "The docket is created in `OPEN` with `scheduled_appeal_count` at 0 and `held_at` null."

    The first session ends at 16:00, so the buffered edge is 16:15. A second
    session starting at 16:15 is not strictly before 16:15, the first conjunct
    fails, and no conflict exists however the second arm evaluates.

    Design: Corner/calculations/docket_session_overlap_accepts_a_session_starting_exactly_fifteen_minutes_later
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    first_id = X.create_docket(api, "2026-10-05T14:00:00Z", "2026-10-05T16:00:00Z")
    before = A.data_of(api.get_hearing_docket(first_id, U.HEARING_OFFICER))

    response = api.create_hearing_docket(
        F.hearing_docket_payload(
            U.HEARING_OFFICER_ID,
            "2026-10-05T16:15:00Z",
            "2026-10-05T18:15:00Z",
            location="Municipal Court Annex Room 2B",
            capacity=4,
        ),
        U.HEARING_OFFICER,
    )
    validate_success(response, 201)
    second = get_success_data(response)

    A.assert_status(second, "OPEN")
    assert second["scheduled_appeal_count"] == 0
    assert second["capacity"] == 4
    assert second["held_at"] is None
    assert second["session_start"].startswith("2026-10-05T16:15:00")
    assert second["session_end"].startswith("2026-10-05T18:15:00")
    assert second["hearing_officer_user_id"] == U.HEARING_OFFICER_ID

    after = A.data_of(api.get_hearing_docket(first_id, U.HEARING_OFFICER))
    A.assert_status(after, "OPEN")
    A.assert_version_unchanged(before, after)
    assert after["scheduled_appeal_count"] == 0


def test_suspension_period_overlap_accepts_a_consecutive_order_one_day_after_through(api):
    """A second withdrawal of police response may begin one day after the live
    order's closed interval ends.

    "The intervals are **closed**, `effective_from` through `effective_through`, and the buffer is **zero**: a conflict exists when the new `effective_from` is at or before the existing `effective_through` **and** the existing `effective_from` is at or before the new `effective_through`."
    "Touching endpoints therefore collide — a new order starting on the very day an existing order ends is a conflict — and the earliest accepted consecutive start is one day after the existing `effective_through`."
    "Candidates are the premises' own orders in `PROPOSED`, `EFFECTIVE` or `REINSTATEMENT_PENDING`; `LIFTED`, `VACATED` and `EXPIRED` orders free their interval."
    "The accepted order is created in `PROPOSED` with `served_at`, `reinstatement_requested_at`, `technician_inspection_date`, `ecv_attestation`, `lifted_at` and `vacated_reason` all null."
    "Its `suspension_sequence` is the premises' `lifted_suspension_count` plus 1, and the premises' `version` rises by 1."

    The sixth chargeable occurrence auto-proposes an order running the logical
    clock plus 10 days, 2026-09-30T01:00:00Z, through 30 days after that,
    2026-10-30T01:00:00Z. A manual order beginning 2026-10-31T01:00:00Z is one
    day after that end, so the first conjunct of the closed-interval test fails
    and the order is accepted. Neither order has been lifted, so the premises'
    lifted count is still 0 and both orders carry sequence 0 + 1 = 1.

    Design: Corner/calculations/suspension_period_overlap_accepts_a_consecutive_order_one_day_after_through
    """
    bundle, incidents = _counted_run(api, 6)
    orders = X.orders_of_site(api, bundle.site_id)
    assert len(orders) == 1, f"expected one auto-proposed order, got {len(orders)}"
    auto = orders[0]
    A.assert_status(auto, "PROPOSED")
    assert auto["effective_from"].startswith("2026-09-30T01:00:00")
    assert auto["effective_through"].startswith("2026-10-30T01:00:00")
    assert auto["suspension_sequence"] == 1

    response = api.create_suspension_order(
        F.suspension_order_payload(
            bundle.site_id,
            incidents[5].incident_id,
            "2026-10-31T01:00:00Z",
            "2026-11-30T01:00:00Z",
            X.site_version(api, bundle.site_id),
        ),
        U.PROGRAM_ADMIN,
    )
    validate_success(response, 201)
    second = get_success_data(response)

    A.assert_status(second, "PROPOSED")
    assert second["effective_from"].startswith("2026-10-31T01:00:00")
    assert second["effective_through"].startswith("2026-11-30T01:00:00")
    assert second["suspension_sequence"] == 1
    assert second["served_at"] is None
    assert second["lifted_at"] is None

    A.assert_status(X.get_order(api, auto["id"]), "PROPOSED")
    site = X.get_site(api, bundle.site_id)
    assert site["lifted_suspension_count"] == 0


def test_site_balance_rollup_blocks_renewal_at_exactly_the_delinquent_balance(api):
    """A premises owing exactly the blocking threshold is already blocked,
    because the roll-up compares inclusively.

    "Fifth, `renewal_block_active` becomes true exactly when `outstanding_balance_cents` is at or above `delinquent_balance_block_cents` — the comparison is inclusive, so a balance of exactly 50000 cents blocks renewal."
    "Second, `outstanding_balance_cents` is the sum of `outstanding_cents` over the premises' invoices whose `payment_status` is `UNPAID` or `PARTIALLY_PAID` and whose `collections_stage` is not `WRITTEN_OFF`."
    "Third, `lifetime_assessed_cents` is the sum of `assessed_cents` over every invoice of the premises whose `payment_status` is not `VOIDED` — so a written-off invoice still counts toward lifetime assessment even though it has left the outstanding balance."
    "Revoking a permit for cause produces the identical downstream chain: an administrator supplies `revocation_reason`, the permit moves from `ACTIVE`, `RENEWAL_DUE`, `RENEWAL_BLOCKED` or `GRACE` to `REVOKED` (terminal), the reason is stored, and the system falls to `UNPERMITTED` with the same penalty and the same fiscal knock-on."
    "Fourth, the three derived counts are recomputed: `ecv_callable_contact_count` as the number of contacts that are `ACTIVE` with `is_ecv_callable` true, `unpermitted_system_count` as the number of systems in `UNPERMITTED`, and `lifted_suspension_count` as the number of suspension orders in `LIFTED`."

    With the administrative charge switched off — a zero percentage against a
    zero floor — the two invoices are exact: 5000 cents at issuance and 45000
    cents when the revocation drops the system out of permit. The sum is exactly
    50000, which is at the threshold rather than above it, and the inclusive
    comparison flips the block on.

    Design: Corner/calculations/site_balance_rollup_blocks_renewal_at_exactly_the_delinquent_balance
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_STARTUP_UTC,
        installed_at=C.CLOCK_STARTUP_UTC,
        schedule_overrides={
            "permit_issue_fee_cents": 5000,
            "unpermitted_operation_penalty_cents": 45000,
            "admin_fee_pct": 0,
            "admin_fee_min_cents": 0,
        },
    )
    issue_invoice = _invoice_of_permit(api, bundle.site_id, bundle.permit_ids[0])
    A.assert_invoice_totals(
        issue_invoice,
        subtotal_cents=5000,
        admin_fee_cents=0,
        assessed_cents=5000,
        outstanding_cents=5000,
    )

    response = api.revoke_permit(
        bundle.permit_ids[0],
        {"revocation_reason": "Repeated unverified dispatch requests from this panel."},
        U.PROGRAM_ADMIN,
    )
    validate_success(response, 200)
    A.assert_status(get_success_data(response), "REVOKED")

    system = X.get_system(api, bundle.system_ids[0])
    A.assert_status(system, "UNPERMITTED")
    assert system["unpermitted_since"].startswith("2026-08-01T00:00:00")

    penalties = X.invoices_of_site(
        api, bundle.site_id, kind="UNPERMITTED_OPERATION_PENALTY"
    )
    assert len(penalties) == 1, f"expected one unpermitted penalty invoice, got {len(penalties)}"
    A.assert_invoice_totals(
        penalties[0],
        subtotal_cents=45000,
        admin_fee_cents=0,
        assessed_cents=45000,
        outstanding_cents=45000,
    )

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["outstanding_balance_cents"], 50000, "outstanding_balance_cents")
    assert site["renewal_block_active"] is True
    assert site["unpermitted_system_count"] == 1
    A.assert_money_cents(site["lifetime_assessed_cents"], 50000, "lifetime_assessed_cents")


def test_money_conservation_invariant_returns_to_zero_drift_after_a_payment_void(api):
    """Voiding a tender pulls back both the allocations and the parked credit in
    one request, leaving no drift behind.

    "The payment moves `APPLIED → VOIDED` with `voided_at` stamped, every one of its allocations flips `APPLIED → REVERSED`, each touched invoice's `paid_cents` drops by the reversed amount and its `payment_status` recomputes downward, the payment's `credited_cents` is subtracted back out of the premises' `credit_balance_cents`, and the premises' `version` rises by 1."
    "A void is the exact compensating action: it removes the payment from the left side and its allocations from the right side within the same request, restoring both sides to their pre-payment values with zero drift in `credit_balance_cents`, which may never fall below zero."
    "Voiding a payment reverses that movement: `PARTIALLY_PAID → UNPAID` when the voided payment's allocations were the only payments against the invoice, and `PAID → PARTIALLY_PAID` when other applied allocations remain, in which case the invoice must not be written off, else `ERR_INVOICE_WRITTEN_OFF`."
    "Both reversals restore `paid_cents` and `outstanding_cents` to their pre-payment values, return the payment's credited residual out of the premises' `credit_balance_cents`, and leave `collections_stage` where it stands until the nightly run."

    The tender applied 5500 to each invoice and parked 1000 cents. The void
    reverses both lines, so each invoice returns to 0 paid and 5500 outstanding
    and — no other payment having touched them — to UNPAID rather than
    PARTIALLY_PAID; the 1000-cent residual leaves the premises credit. Both sides
    of the identity fall to zero and the premises owes the original 11000 again.

    Design: Corner/calculations/money_conservation_invariant_returns_to_zero_drift_after_a_payment_void
    """
    bundle, invoices = _two_permit_site(api)
    payment_id = X.post_payment(api, bundle, 12000, C.CLOCK_STARTUP_UTC, method="ACH")
    assert len(X.allocations_of_payment(api, payment_id)) == 2

    response = api.void_payment_record(
        payment_id,
        {"void_reason": "Cheque returned unpaid by the drawee bank."},
        U.PROGRAM_ADMIN,
    )
    validate_success(response, 200)
    voided = get_success_data(response)
    A.assert_status(voided, "VOIDED")
    assert voided["voided_at"].startswith("2026-08-01T00:00:00")

    for row in X.allocations_of_payment(api, payment_id):
        A.assert_status(row, "REVERSED")

    for invoice in invoices:
        A.assert_invoice_totals(
            X.get_invoice(api, invoice["id"]),
            paid_cents=0,
            outstanding_cents=C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS,
            payment_status="UNPAID",
        )

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["credit_balance_cents"], 0, "credit_balance_cents")
    A.assert_money_cents(site["outstanding_balance_cents"], 11000, "outstanding_balance_cents")


def test_chargeable_count_conservation_invariant_renumbers_and_reprices_after_a_grant(api):
    """Granting an appeal on the third occurrence renumbers and re-prices the
    fourth, leaving the premises where it would have been had the third never
    counted.

    "Hop one: the incident moves from `APPEALED` to the terminal `EXEMPT_BY_APPEAL`, with `determination` set to `EXEMPT`, `exempt_cause_code` taken from the ruling, `occurrence_index` set to null and `assessed_fee_cents` set to 0."
    "Hop two: because the incident left the chargeable set, the premises' chargeable counters decrement and every remaining chargeable incident at that premises — those in `COUNTED` or `APPEALED` — is renumbered contiguously in order of occurrence instant ascending then creation instant ascending, and its fee re-derived at its new tier."
    "Hop three: because a renumbered incident's assessed fee changed, its invoice is re-assessed, `assessed_cents` recomputed, and any `paid_cents` above the new `assessed_cents` moved into the premises' `credit_balance_cents`."
    "The set of `occurrence_index` values across those incidents is exactly the contiguous run from 1 to that count, with no gaps and no duplicates, assigned in order of occurrence instant ascending and, for ties, creation instant ascending."
    "And the premises' `lifetime_assessed_cents` equals the sum of the re-derived assessed amounts over every non-voided invoice for the indices currently in force."

    Occurrences 1 and 2 fall inside the free allowance, the third prices at
    10000 * 1.50 = 15000 and the fourth, a non-verified duress signal, at 25000 *
    1.50 * 1.20 = 45000. Striking the third moves the fourth down to index 3,
    where its tier base becomes 10000 and its fee 10000 * 1.50 * 1.20 = 18000,
    with 18000 * 0.05 = 900 of administrative charge for 18900 assessed. The
    premises is then left with four 5500-cent permit invoices plus that 18900,
    that is 40900 cents both assessed over its lifetime and still owed, three
    chargeable occurrences indexed 1, 2 and 3, and a posture back in good
    standing because 3 is below the probation threshold of 4.

    Design: Corner/calculations/chargeable_count_conservation_invariant_renumbers_and_reprices_after_a_grant
    """
    bundle, incidents = _counted_run(api, 4)
    third, fourth = incidents[2], incidents[3]
    A.assert_money_cents(
        X.get_incident(api, fourth.incident_id)["assessed_fee_cents"], 45000, "fourth fee"
    )

    appeal_id, _docket_id = X.create_heard_appeal(
        api,
        bundle,
        third.incident_id,
        session_start="2026-10-05T14:00:00Z",
        session_end="2026-10-05T16:00:00Z",
    )
    decided = X.decide_appeal(
        api,
        appeal_id,
        "GRANTED",
        findings="The utility transient is an exempt cause; the occurrence is struck.",
        exempt_cause_code="UTILITY_POWER_FAILURE",
    )
    A.assert_status(decided, "GRANTED")
    assert decided["decided_by_user_id"] == U.HEARING_OFFICER_ID

    exempted = X.get_incident(api, third.incident_id)
    A.assert_status(exempted, "EXEMPT_BY_APPEAL")
    assert exempted["occurrence_index"] is None
    A.assert_money_cents(exempted["assessed_fee_cents"], 0, "exempted fee")
    A.assert_invoice_totals(
        X.get_invoice(api, third.invoice_id), outstanding_cents=0, payment_status="VOIDED"
    )

    repriced = X.get_incident(api, fourth.incident_id)
    assert repriced["occurrence_index"] == 3
    A.assert_money_cents(repriced["assessed_fee_cents"], 18000, "repriced fee")
    A.assert_fee_basis(
        repriced["fee_basis"],
        tier_base_cents=10000,
        occupancy_multiplier=1.50,
        non_ecv_surcharge_applied=True,
    )
    A.assert_invoice_totals(
        X.get_invoice(api, fourth.invoice_id),
        subtotal_cents=18000,
        admin_fee_cents=900,
        assessed_cents=18900,
    )

    chargeable = [
        row
        for row in X.incidents_of_site(api, bundle.site_id)
        if row["status"] in ("COUNTED", "APPEALED")
    ]
    assert sorted(row["occurrence_index"] for row in chargeable) == [1, 2, 3]

    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_window"] == 3
    A.assert_money_cents(site["lifetime_assessed_cents"], 40900, "lifetime_assessed_cents")
    A.assert_money_cents(site["outstanding_balance_cents"], 40900, "outstanding_balance_cents")
    assert site["renewal_block_active"] is False
    A.assert_status(site, "RESPONSE_ACTIVE", field="response_status")

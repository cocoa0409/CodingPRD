"""Compensating writes checked against two partitions: the facility's money and the
request's pages."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_facility_money,
    assert_line,
    assert_page_ledger,
    money_partition_sum,
)
from test_helpers.test_users import ANALYST_1


# --------------------------------------------------------------------------
# invoice_void_restores_facility_money_three_way_sum
# --------------------------------------------------------------------------
def _two_release_ready_requests(api):
    """Request A is a 62-page certified paper job worth 4501; request B is a 25-page
    portal job worth 2188.  Neither is released, so no penalty or forfeiture applies."""
    world = fx.third_party_world(api)
    request_a = fx.simple_third_party_request_at_release_ready(
        api,
        world,
        62,
        delivery_format="PAPER_MAIL",
        certification_requested=True,
        date_range_start="2024-01-01",
        date_range_end="2024-12-31",
    )
    request_b = fx.simple_third_party_request_at_release_ready(
        api, world, 25, date_range_start="2023-01-01", date_range_end="2023-12-31"
    )
    return {
        "world": world,
        "request_a": request_a["request_id"],
        "request_b": request_b["request_id"],
    }


def _issue_b_then_a(api, scenario):
    """B is issued first so that A's reversal can never hide behind an all-zero ledger."""
    invoice_b = fx.create_invoice(api, scenario["request_b"])
    fx.issue_invoice(api, invoice_b["id"])
    invoice_a = fx.create_invoice(api, scenario["request_a"])
    fx.issue_invoice(api, invoice_a["id"])
    scenario["invoice_a"] = invoice_a["id"]
    scenario["invoice_b"] = invoice_b["id"]
    return scenario


def test_the_two_invoices_price_to_4501_and_2188(api):
    """Five lines with per-line rounding on A, two on B.

    PRD: "Each emitted line's `amount_cents` is its own `quantity` multiplied by its own `unit_millicents`, divided by 1000, rounded half up to whole cents."

    Design: Difficulty/compensating_invariant/invoice_void_restores_facility_money_three_way_sum
    """
    scenario = _issue_b_then_a(api, _two_release_ready_requests(api))
    lines = fx.read_lines(api, scenario["invoice_a"])

    assert len(lines) == 5
    assert_line(lines[0], "BASE_RETRIEVAL", 1, 1500000, 1500)
    assert_line(lines[1], "PER_PAGE_TIER1", 25, 27500, 688)
    assert_line(lines[2], "PER_PAGE_TIER2", 37, 12500, 463)
    assert_line(lines[3], "CERTIFICATION", 1, 1000000, 1000)
    assert_line(lines[4], "POSTAGE", 1, 850000, 850)

    assert fx.read_invoice(api, scenario["invoice_a"])["amount_due_cents"] == 4501
    assert fx.read_invoice(api, scenario["invoice_b"])["amount_due_cents"] == 2188


def test_issuing_both_invoices_posts_the_whole_sum_as_receivable(api):
    """4501 plus 2188 sits in one bucket and the other two stay empty.

    PRD: "`receivable_cents` is the sum, over those invoices whose `status` is `ISSUED`, of the invoice's `amount_due_cents` minus its `paid_cents`."

    Design: Difficulty/compensating_invariant/invoice_void_restores_facility_money_three_way_sum
    """
    scenario = _two_release_ready_requests(api)
    fx.issue_invoice(api, fx.create_invoice(api, scenario["request_b"])["id"])
    assert_facility_money(fx.read_facility(api, scenario["world"]["facility_id"]), 2188, 0, 0)

    fx.issue_invoice(api, fx.create_invoice(api, scenario["request_a"])["id"])

    facility = fx.read_facility(api, scenario["world"]["facility_id"])
    assert_facility_money(facility, 6689, 0, 0)
    assert money_partition_sum(facility) == 6689


def test_the_void_unposts_only_the_voided_invoice(api):
    """A's 4501 is reversed and B's 2188 posting is left exactly where it was.

    PRD: "`VOID` is permitted from `DRAFT`, `ISSUED` or `WAIVED`, records the supplied `reason` as `void_reason` — the reason vocabulary being `SUPERSEDED_BY_REPRICE`, `AUTHORIZATION_REVOKED` and `BILLING_CLERK_VOID` — sets `settled_at`, moves the invoice to `VOIDED`, returns the request's `billing_status` to `PENDING_INVOICE` from `INVOICED` or from `WAIVED`, and reverses whichever ledger postings that invoice had made, so that the facility's `receivable_cents`, `collected_cents` and `written_off_cents` return together to their pre-issue values."

    Design: Difficulty/compensating_invariant/invoice_void_restores_facility_money_three_way_sum
    """
    scenario = _issue_b_then_a(api, _two_release_ready_requests(api))

    fx.void_invoice(api, scenario["invoice_a"])

    assert fx.read_invoice(api, scenario["invoice_a"])["status"] == "VOIDED"
    facility = fx.read_facility(api, scenario["world"]["facility_id"])
    assert_facility_money(facility, 2188, 0, 0)
    assert money_partition_sum(facility) == 2188


def test_the_voided_invoice_keeps_its_historical_amount_due(api):
    """The figure is not zeroed; it simply stops contributing to every bucket.

    PRD: "Invoices in `DRAFT` or `VOIDED` contribute to no bucket."

    Design: Difficulty/compensating_invariant/invoice_void_restores_facility_money_three_way_sum
    """
    scenario = _issue_b_then_a(api, _two_release_ready_requests(api))

    fx.void_invoice(api, scenario["invoice_a"])

    voided = fx.read_invoice(api, scenario["invoice_a"])
    assert voided["amount_due_cents"] == 4501
    assert voided["void_reason"] == "BILLING_CLERK_VOID"


def test_the_void_makes_the_request_billable_again_without_moving_its_record_state(api):
    """billing_status walks backwards while fulfillment_status stands still.

    PRD: "`billing_status` tracks the money and takes one of `PENDING_INVOICE`, `INVOICED`, `PAID`, `WAIVED` or `NOT_BILLABLE`, starting at `PENDING_INVOICE`, with `PAID` and `NOT_BILLABLE` terminal; `WAIVED` is deliberately not terminal, because a waived invoice may still be voided and thereby return the request to `PENDING_INVOICE`."

    Design: Difficulty/compensating_invariant/invoice_void_restores_facility_money_three_way_sum
    """
    scenario = _issue_b_then_a(api, _two_release_ready_requests(api))
    assert fx.read_request(api, scenario["request_a"])["billing_status"] == "INVOICED"

    fx.void_invoice(api, scenario["invoice_a"])

    request = fx.read_request(api, scenario["request_a"])
    assert request["billing_status"] == "PENDING_INVOICE"
    assert request["fulfillment_status"] == "RELEASE_READY"


def test_payment_moves_money_between_buckets_without_changing_the_total(api):
    """B's 2188 leaves receivable and arrives in collected; the partition sum is unmoved.

    PRD: "A successful payment records `paid_cents` as the settled `amount_cents` and `settled_at` as the current logical clock, moves the invoice to `PAID` and the request's `billing_status` to `PAID`, subtracts `amount_due_cents` from the facility's `receivable_cents` and adds it to `collected_cents`."

    Design: Difficulty/compensating_invariant/invoice_void_restores_facility_money_three_way_sum
    """
    scenario = _issue_b_then_a(api, _two_release_ready_requests(api))
    fx.void_invoice(api, scenario["invoice_a"])

    fx.pay_invoice(api, scenario["invoice_b"], 2188)

    facility = fx.read_facility(api, scenario["world"]["facility_id"])
    assert_facility_money(facility, 0, 2188, 0)
    assert money_partition_sum(facility) == 2188


def test_re_invoicing_after_the_void_reproduces_the_same_figure(api):
    """A voided invoice does not block a re-price, and the re-price does not drift.

    PRD: "An invoice may not be created while another invoice for the same `request_id` holds `status` `ISSUED`, `PAID` or `WAIVED`; that is `ERR_INVOICE_ALREADY_EXISTS`."

    Design: Difficulty/compensating_invariant/invoice_void_restores_facility_money_three_way_sum
    """
    scenario = _issue_b_then_a(api, _two_release_ready_requests(api))
    fx.void_invoice(api, scenario["invoice_a"])
    fx.pay_invoice(api, scenario["invoice_b"], 2188)

    replacement = fx.create_invoice(api, scenario["request_a"])

    assert replacement["subtotal_cents"] == 4501
    assert replacement["amount_due_cents"] == 4501

    rows, meta = fx.list_invoices_for(api, scenario["request_a"])
    assert meta["total_count"] == 2
    assert [row["status"] for row in rows].count("VOIDED") == 1


def test_the_three_buckets_still_partition_the_issued_money_at_the_end(api):
    """0 receivable, 2188 collected and 4501 written off sum to the 6689 ever issued.

    PRD: "Because a payment must settle the full amount due, `paid_cents` is always 0 on an `ISSUED` invoice, so the three buckets partition the issued money exactly: their sum always equals the sum of `amount_due_cents` over every invoice whose `status` is `ISSUED`, `PAID` or `WAIVED`."

    Design: Difficulty/compensating_invariant/invoice_void_restores_facility_money_three_way_sum
    """
    scenario = _issue_b_then_a(api, _two_release_ready_requests(api))
    fx.void_invoice(api, scenario["invoice_a"])
    fx.pay_invoice(api, scenario["invoice_b"], 2188)
    replacement = fx.create_invoice(api, scenario["request_a"])
    fx.issue_invoice(api, replacement["id"])
    fx.waive_invoice(api, replacement["id"])

    facility = fx.read_facility(api, scenario["world"]["facility_id"])
    assert_facility_money(facility, 0, 2188, 4501)
    assert money_partition_sum(facility) == 6689


# --------------------------------------------------------------------------
# segment_withdraw_restores_request_page_partition
# --------------------------------------------------------------------------
def _three_segment_request_in_redaction(api):
    """40 general-medical, 22 behavioural-health and 18 HIV pages: the behavioural-health
    segment is included with redaction required and the HIV segment is withheld."""
    world = fx.third_party_world(
        api,
        scope_categories=["GENERAL_MEDICAL", "BEHAVIORAL_HEALTH", "HIV"],
        sensitive_categories_authorized=["BEHAVIORAL_HEALTH"],
    )
    request = fx.open_third_party_request(
        api,
        world,
        requested_categories=["GENERAL_MEDICAL", "BEHAVIORAL_HEALTH", "HIV"],
        date_range_start="2024-01-01",
        date_range_end="2024-12-31",
    )
    ids = fx.walk_to_sensitive_review(
        api,
        request["id"],
        [
            {"label": "gen", "category": "GENERAL_MEDICAL", "page_count": 40},
            {"label": "bh", "category": "BEHAVIORAL_HEALTH", "page_count": 22},
            {
                "label": "hiv",
                "category": "HIV",
                "page_count": 18,
                "source_system": "SCANNED_PAPER",
            },
        ],
    )
    fx.run_sensitive_review(
        api,
        request["id"],
        [f.include_decision(ids["bh"], redaction_required=True), f.withhold_decision(ids["hiv"])],
    )
    return {"world": world, "request_id": request["id"], "segment_ids": ids}


def _withdraw(api, segment_id):
    return get_success_data(
        api.segment_disposition(segment_id, f.withdrawn_payload(), ANALYST_1)
    )


def test_the_partition_closes_at_eighty_before_any_compensation(api):
    """Checkpoint 1: 62 billable plus 18 withheld plus 0 redacted is 80 retrieved.

    PRD: "Then `billable_page_count` is the sum, over the releasable segments, of that segment's `page_count` less its `redacted_page_count` when its `redaction_status` is `APPROVED` and less nothing otherwise; `withheld_page_count` is the sum of `page_count` over the segments whose `sensitivity_status` is `WITHHELD`; and `redacted_page_count_total` is the sum of `redacted_page_count` over the releasable segments whose `redaction_status` is `APPROVED`."

    Design: Difficulty/compensating_invariant/segment_withdraw_restores_request_page_partition
    """
    scenario = _three_segment_request_in_redaction(api)

    request = fx.read_request(api, scenario["request_id"])
    assert request["fulfillment_status"] == "REDACTION"
    assert_page_ledger(request, 80, 62, 18, 0)


def test_an_applied_but_unapproved_redaction_moves_no_page(api):
    """Checkpoint 2: nine redacted pages exist on the segment and nowhere on the request.

    PRD: "Redacted pages therefore count only once a redaction has been approved: an `APPLIED`-but-unapproved redaction leaves `billable_page_count` completely untouched."

    Design: Difficulty/compensating_invariant/segment_withdraw_restores_request_page_partition
    """
    scenario = _three_segment_request_in_redaction(api)

    fx.apply_redaction(api, scenario["segment_ids"]["bh"], 9)

    assert fx.read_segment(api, scenario["segment_ids"]["bh"])["redacted_page_count"] == 9
    assert_page_ledger(fx.read_request(api, scenario["request_id"]), 80, 62, 18, 0)


def test_withdrawing_the_withheld_segment_empties_the_withheld_bucket(api):
    """Checkpoint 3: the gross total drops to 62 and the partition closes again.

    PRD: "A `disposition` of `WITHDRAWN` moves the segment from `PENDING` or `RETRIEVED` to `WITHDRAWN` and is permitted while the parent request's `fulfillment_status` is `COMPILATION`, `SENSITIVE_REVIEW` or `REDACTION`; it resets `sensitivity_status` to `UNCLASSIFIED` from whichever of `NOT_SENSITIVE`, `SEGREGATED_PENDING_REVIEW`, `AUTHORIZED_INCLUDE` or `WITHHELD` it held, resets `redaction_status` to `NOT_REQUIRED` from whichever of `OPEN`, `APPLIED`, `APPROVED` or `REWORK` it held, and resets `redacted_page_count` to 0, so the segment leaves every page aggregate of the parent request."

    Design: Difficulty/compensating_invariant/segment_withdraw_restores_request_page_partition
    """
    scenario = _three_segment_request_in_redaction(api)
    fx.apply_redaction(api, scenario["segment_ids"]["bh"], 9)

    _withdraw(api, scenario["segment_ids"]["hiv"])

    assert_page_ledger(fx.read_request(api, scenario["request_id"]), 62, 62, 0, 0)


def test_the_withdrawal_resets_both_classification_dimensions_of_the_segment(api):
    """The withdrawn segment forgets that it was ever withheld.

    PRD: "A `disposition` of `WITHDRAWN` moves the segment from `PENDING` or `RETRIEVED` to `WITHDRAWN` and is permitted while the parent request's `fulfillment_status` is `COMPILATION`, `SENSITIVE_REVIEW` or `REDACTION`; it resets `sensitivity_status` to `UNCLASSIFIED` from whichever of `NOT_SENSITIVE`, `SEGREGATED_PENDING_REVIEW`, `AUTHORIZED_INCLUDE` or `WITHHELD` it held, resets `redaction_status` to `NOT_REQUIRED` from whichever of `OPEN`, `APPLIED`, `APPROVED` or `REWORK` it held, and resets `redacted_page_count` to 0, so the segment leaves every page aggregate of the parent request."

    Design: Difficulty/compensating_invariant/segment_withdraw_restores_request_page_partition
    """
    scenario = _three_segment_request_in_redaction(api)
    hiv = scenario["segment_ids"]["hiv"]
    assert fx.read_segment(api, hiv)["sensitivity_status"] == "WITHHELD"

    _withdraw(api, hiv)

    segment = fx.read_segment(api, hiv)
    assert segment["retrieval_status"] == "WITHDRAWN"
    assert segment["sensitivity_status"] == "UNCLASSIFIED"
    assert segment["redaction_status"] == "NOT_REQUIRED"
    assert segment["redacted_page_count"] == 0


def test_the_withdrawal_does_not_unblock_the_other_segments_redaction(api):
    """The re-evaluation runs but finds the behavioural-health redaction still APPLIED.

    PRD: "A withdrawal also re-evaluates whether the parent request can now leave `REDACTION` for `RELEASE_READY`, since removing the last unapproved segment unblocks that move."

    Design: Difficulty/compensating_invariant/segment_withdraw_restores_request_page_partition
    """
    scenario = _three_segment_request_in_redaction(api)
    fx.apply_redaction(api, scenario["segment_ids"]["bh"], 9)

    _withdraw(api, scenario["segment_ids"]["hiv"])

    assert fx.read_segment(api, scenario["segment_ids"]["bh"])["redaction_status"] == "APPLIED"
    assert fx.read_request(api, scenario["request_id"])["fulfillment_status"] == "REDACTION"


def test_the_final_partition_closes_at_sixty_two_after_the_approval(api):
    """Checkpoint 4: 53 billable plus 0 withheld plus 9 redacted is 62.

    PRD: "`APPROVE` moves `redaction_status` from `APPLIED` to `APPROVED`, records `redaction_approved_by_user_id` as the acting `X-User-ID`, and only now folds the segment's `redacted_page_count` into the parent request's `redacted_page_count_total` and subtracts it from `billable_page_count`; it then re-derives `redacted_page_count_total` and `billable_page_count`, and bubbles the parent request from `REDACTION` to `RELEASE_READY` provided that, after this decision is applied, no segment of the request holds `redaction_status` `OPEN`, `APPLIED` or `REWORK`."

    Design: Difficulty/compensating_invariant/segment_withdraw_restores_request_page_partition
    """
    scenario = _three_segment_request_in_redaction(api)
    fx.apply_redaction(api, scenario["segment_ids"]["bh"], 9)
    _withdraw(api, scenario["segment_ids"]["hiv"])

    fx.approve_redaction(api, scenario["segment_ids"]["bh"])

    request = fx.read_request(api, scenario["request_id"])
    assert request["fulfillment_status"] == "RELEASE_READY"
    assert_page_ledger(request, 62, 53, 0, 9)


def test_fifty_three_billable_pages_keep_the_request_awaiting_a_clerk(api):
    """A non-zero prospective subtotal leaves billing_status where it started.

    PRD: "If the prospective subtotal is above 0 cents, `billing_status` stays at `PENDING_INVOICE` and awaits a clerk."

    Design: Difficulty/compensating_invariant/segment_withdraw_restores_request_page_partition
    """
    scenario = _three_segment_request_in_redaction(api)
    fx.apply_redaction(api, scenario["segment_ids"]["bh"], 9)
    _withdraw(api, scenario["segment_ids"]["hiv"])
    fx.approve_redaction(api, scenario["segment_ids"]["bh"])

    assert fx.read_request(api, scenario["request_id"])["billing_status"] == "PENDING_INVOICE"

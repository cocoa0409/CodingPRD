"""Which state a row has to be in before a request is allowed to move it.

Every action endpoint declares the states it accepts as origins, and a request
arriving at a row in any other state is refused rather than absorbed.  The
scenarios here sit on both sides of that rule: replays and skipped steps that are
refused without writing anything, opening states that a create writes for itself,
and the one long chain of legal transitions that walks an item out of suspension.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiClient,
    ApiErrorId,
    assert_no_verification_verdict,
    classify_return_case_payload,
    create_return_case_payload,
    is_iso8601_timestamp,
    make_customer_headers,
    make_fit_analyst_headers,
    make_merch_ops_admin_headers,
    make_returns_auditor_headers,
    retire_size_chart_payload,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx  # noqa: E402

SCENARIO_START = "2026-06-01T00:00:00Z"


def test_listing_an_item_that_is_already_on_the_storefront_is_refused(api):
    """PRD §2.9: "The target row is in a state the requested transition declares as
    its origin, otherwise `ERR_INVALID_ITEM_STATE`, `ERR_INVALID_SPEC_STATE`,
    `ERR_INVALID_CHART_STATE`, `ERR_INVALID_RETURN_CASE_STATE`, or
    `ERR_INVALID_DEPLOYMENT_STATE` (409). Applies to every action endpoint: list,
    delist, product-page enhancement, publish-guidance, submit, verify, resubmit,
    standardize, retire, classify, resolve, void, terminate, and retract."  Listing
    declares only the draft state as its origin, so replaying it on an item that is
    already listed is refused rather than silently accepted, and the version the
    first listing left behind is unchanged by the refusal.

    Design: Corner/state_machines/item_list_action_repeated_returns_invalid_item_state
    """
    built = fx.setup_listed_item(api, SCENARIO_START)

    before = fx.read_item(api, built["item"]["id"])
    assert before["listing_status"] == "LISTED"
    assert before["version"] == 2

    response = api.list_item(built["item"]["id"], make_merch_ops_admin_headers())
    validate_error(response, ApiErrorId.ERR_INVALID_ITEM_STATE.value, 409)

    after = fx.read_item(api, built["item"]["id"])
    assert after["listing_status"] == "LISTED"
    assert after["version"] == before["version"]


def test_verifying_a_draft_specification_runs_no_check_at_all(api):
    """PRD §3.2: "It is permitted only from `SUBMITTED` and only while the item is
    not `DELISTED`; from any other specification status the request is refused with
    `ERR_INVALID_SPEC_STATE`."  A specification the brand authored but never handed
    over is still in draft, so the analyst's verification request never reaches the
    arithmetic: the verdict fields stay as the create left them and no correction
    round is charged against the brand.

    Design: Corner/state_machines/specification_verify_from_draft_returns_invalid_spec_state
    """
    built = fx.setup_vendor_and_item(api, SCENARIO_START)
    spec = fx.create_spec(api, built["item"]["id"], built["vendor"]["id"])
    assert spec["status"] == "DRAFT"

    response = api.verify_measurement_spec(spec["id"], make_fit_analyst_headers())
    validate_error(response, ApiErrorId.ERR_INVALID_SPEC_STATE.value, 409)

    stored = fx.read_spec(api, spec["id"])
    assert stored["status"] == "DRAFT"
    assert stored["revision_round"] == 0
    assert_no_verification_verdict(stored)

    vendor = fx.read_vendor(api, built["vendor"]["id"])
    assert vendor["correction_round_count"] == 0
    assert vendor["correction_spend_cents"] == 0
    assert vendor["reliability_score_bp"] == 10000


def _build_shopper_ready_to_return(api: ApiClient, **line_overrides) -> dict:
    """A listed pair of tops delivered on the twentieth of May under a thirty-day
    category default, with the clock standing on the first of June."""
    return fx.setup_shopper_with_delivered_line(
        api,
        SCENARIO_START,
        policy_overrides={
            "window_days": 30,
            "restocking_applies": True,
            "non_refundable_shipping": False,
            "effective_from": "2026-01-01T00:00:00Z",
        },
        line_overrides=line_overrides or None,
    )


def test_a_new_case_opens_in_triage_with_its_policy_frozen_onto_the_row(api):
    """PRD §3.7: "The policy that will govern the case is resolved once, at
    creation, and **frozen** on the case as `effective_policy_id`; it is never
    re-resolved later, not even at resolution time."  The only candidate is the
    category default, so that row's identifier is what the case carries; the case
    itself opens in triage with the shopper's own reason code, nothing coded or
    closed by anyone, and no money written.

    Design: Corner/state_machines/return_case_initial_state_is_triage_with_frozen_policy_snapshot
    """
    built = _build_shopper_ready_to_return(api, shipping_allocated_cents=495)

    case = validate_success(
        api.create_return_case(
            create_return_case_payload(
                built["order_line"]["id"], requested_reason_code="FIT_TOO_SMALL"
            ),
            make_customer_headers(built["customer"]["id"]),
        ),
        201,
    )

    assert case["status"] == "TRIAGE"
    assert case["effective_policy_id"] == built["policy"]["id"]
    assert case["requested_reason_code"] == "FIT_TOO_SMALL"
    assert case["reason_code"] == "FIT_TOO_SMALL"
    assert case["reason_family"] == "FIT"
    assert case["item_condition"] is None
    assert case["classified_by_user_id"] is None
    assert case["resolved_by_user_id"] is None
    assert case["void_reason"] is None
    assert case["restocking_fee_cents"] == 0
    assert case["refund_amount_cents"] == 0
    assert case["total_cost_cents"] == 0


def test_the_frozen_window_puts_the_deadline_thirty_days_after_delivery(api):
    """PRD §3.7: "`return_deadline_at` is the order line's `delivered_at` plus
    `effective_window_days` whole days."  A standard-window shopper takes the
    category default's thirty days unchanged, so a line delivered on the twentieth
    of May is returnable through the nineteenth of June, and the request instant
    recorded on the case is the logical clock rather than wall-clock time.

    Design: Corner/state_machines/return_case_initial_state_is_triage_with_frozen_policy_snapshot
    """
    built = _build_shopper_ready_to_return(api, shipping_allocated_cents=495)
    assert built["customer"]["policy_class"] == "STANDARD_WINDOW"
    assert built["policy"]["window_days"] == 30

    case = fx.open_case(
        api,
        built["order_line"]["id"],
        built["customer"]["id"],
        requested_reason_code="FIT_TOO_SMALL",
    )

    assert case["effective_window_days"] == 30
    assert is_iso8601_timestamp(case["return_deadline_at"])
    assert case["return_deadline_at"].startswith("2026-06-19T00:00:00")
    assert is_iso8601_timestamp(case["requested_at"])
    assert case["requested_at"].startswith("2026-06-01T00:00:00")


def test_opening_the_case_moves_the_line_and_recomputes_the_shoppers_standing(api):
    """PRD §3.7: "The purchased line moves to `RETURN_IN_PROGRESS`, and the
    shopper's `return_case_count`, `return_rate_bp`, `abuse_status`, and
    `policy_class` are recomputed — which means opening a return can, by itself,
    push a shopper into `BLOCKED` on the rate rule."  One case against one purchased
    line is a return rate of ten thousand basis points, which is far above the block
    threshold and still leaves the shopper clear because the rate rule also demands
    four purchased lines.  The item has closed nothing, so its return counter is
    still empty.

    Design: Corner/state_machines/return_case_initial_state_is_triage_with_frozen_policy_snapshot
    """
    built = _build_shopper_ready_to_return(api, shipping_allocated_cents=495)

    fx.open_case(
        api,
        built["order_line"]["id"],
        built["customer"]["id"],
        requested_reason_code="FIT_TOO_SMALL",
    )

    order_line = fx.read_order_line(api, built["order_line"]["id"])
    assert order_line["status"] == "RETURN_IN_PROGRESS"

    customer = fx.read_customer(api, built["customer"]["id"])
    assert customer["return_case_count"] == 1
    assert customer["purchase_line_count"] == 1
    assert customer["return_rate_bp"] == 10000
    assert customer["abuse_status"] == "CLEAR"

    item = fx.read_item(api, built["item"]["id"])
    assert item["total_return_count"] == 0


def test_a_delisted_item_cannot_be_put_back_on_the_storefront(api):
    """PRD §3.1: "The request carries a `delist_reason_code` of
    `CHRONIC_FIT_RETURNS`, `VENDOR_EXIT`, `SEASONAL_END`, or `MANUAL`, which is
    stored on the item; `listing_status` becomes `DELISTED`, a terminal state, and
    the item's `version` increments by 1."  Nothing declares the delisted state as
    an origin, so a listing request against it is refused on the state check and the
    reason the item was withdrawn for stays exactly as it was stored.

    Design: Corner/state_machines/delisted_item_cannot_be_relisted_from_terminal_state
    """
    built = fx.setup_vendor_and_item(api, SCENARIO_START)
    delisted = fx.delist_item(
        api, built["item"]["id"], delist_reason_code="MANUAL"
    )
    assert delisted["listing_status"] == "DELISTED"

    response = api.list_item(built["item"]["id"], make_merch_ops_admin_headers())
    validate_error(response, ApiErrorId.ERR_INVALID_ITEM_STATE.value, 409)

    item = fx.read_item(api, built["item"]["id"])
    assert item["listing_status"] == "DELISTED"
    assert item["delist_reason_code"] == "MANUAL"
    assert item["fit_readiness"] == "UNVERIFIED"


def test_a_draft_chart_cannot_skip_standardization_on_its_way_to_retirement(api):
    """PRD §3.3: "Retirement is permitted only from `STANDARDIZED`, stores the
    supplied `retire_reason_code` of `SUPERSEDED_BY_NEW_CHART`,
    `VENDOR_SYSTEM_CHANGE`, or `DATA_QUALITY`, and moves the chart to `RETIRED`, a
    terminal state."  A chart that was drafted and never standardized has no route
    to retirement, so the reason code the request carried is never stored and the
    chart is left in draft with the row count and fallback anchor its create
    computed.

    Design: Corner/state_machines/size_chart_retire_from_draft_returns_invalid_chart_state
    """
    fx.set_clock(api, SCENARIO_START)
    chart = fx.create_chart(api, chart_code="STD-TOPS-S5")
    assert chart["status"] == "DRAFT"
    assert chart["row_count"] == 2
    assert chart["median_row_index"] == 0

    response = api.retire_size_chart(
        chart["id"],
        retire_size_chart_payload(retire_reason_code="SUPERSEDED_BY_NEW_CHART"),
        make_merch_ops_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_CHART_STATE.value, 409)

    stored = fx.read_chart(api, chart["id"])
    assert stored["status"] == "DRAFT"
    assert stored["retire_reason_code"] is None


def test_a_second_auditor_cannot_recode_a_case_that_has_left_triage(api):
    """PRD §3.8: "Coding a case that is not in `TRIAGE` is refused with
    `ERR_INVALID_RETURN_CASE_STATE`."  The first coder moved the case into its fit
    review branch and is recorded on the row, so a later attempt to recode it as a
    quality defect changes neither the reason nor the recorded coder — which is what
    keeps the segregation-of-duties check reading a stable name.

    Design: Corner/state_machines/classify_repeated_returns_invalid_return_case_state
    """
    built = _build_shopper_ready_to_return(api)
    case = fx.open_case(
        api,
        built["order_line"]["id"],
        built["customer"]["id"],
        requested_reason_code="FIT_TOO_SMALL",
    )

    coded = fx.classify_case(api, case["id"], "FIT_TOO_SMALL", user_id="auditor-1")
    assert coded["status"] == "FIT_REVIEW"
    assert coded["classified_by_user_id"] == "auditor-1"

    response = api.classify_return_case(
        case["id"],
        classify_return_case_payload("QUALITY_DEFECT"),
        make_returns_auditor_headers("auditor-9"),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_RETURN_CASE_STATE.value, 409)

    stored = fx.read_case(api, case["id"])
    assert stored["status"] == "FIT_REVIEW"
    assert stored["reason_code"] == "FIT_TOO_SMALL"
    assert stored["reason_family"] == "FIT"
    assert stored["classified_by_user_id"] == "auditor-1"


def _build_expectation_review_case(api: ApiClient) -> dict:
    """A two-unit line of 2,295-cent tops whose shopper asked for a fit return and
    whose auditor recoded it as an expectation mismatch."""
    built = _build_shopper_ready_to_return(
        api, quantity=2, shipping_allocated_cents=495
    )
    built["case"] = fx.open_case(
        api,
        built["order_line"]["id"],
        built["customer"]["id"],
        requested_reason_code="FIT_TOO_SMALL",
    )
    built["coded"] = fx.classify_case(
        api, built["case"]["id"], "EXPECTATION_MISMATCH", user_id="auditor-1"
    )
    return built


def test_the_auditors_code_replaces_the_shoppers_and_picks_the_branch(api):
    """PRD §3.8: "The supplied code overwrites the case's `reason_code`,
    `reason_family` is re-derived from it, and the acting `X-User-ID` is stamped onto
    `classified_by_user_id`."  The shopper's own selection survives on the row as
    what was requested, while the code the auditor believes is correct is the one
    that carries the case into the expectation branch and drives every number that
    follows.

    Design: Corner/state_machines/expectation_branch_resolve_sets_pdp_review_required
    """
    built = _build_expectation_review_case(api)

    assert built["order_line"]["gross_line_cents"] == 4590
    assert built["coded"]["status"] == "EXPECTATION_REVIEW"
    assert built["coded"]["reason_family"] == "EXPECTATION"
    assert built["coded"]["requested_reason_code"] == "FIT_TOO_SMALL"
    assert built["coded"]["reason_code"] == "EXPECTATION_MISMATCH"
    assert built["coded"]["classified_by_user_id"] == "auditor-1"


def test_the_expectation_close_pays_the_whole_gross_and_bills_eleven_minutes(api):
    """PRD §3.8: "`PROCESSING_LABOR` is a labor rate of 62 cents per minute
    multiplied by the handling minutes the case's `reason_family` consumes — 9
    minutes for `FIT`, 17 for `QUALITY`, 11 for `EXPECTATION`, and 7 for
    `CHANGE_OF_MIND` — rounded half up."  The recode changed the family, so the
    ledger bills eleven minutes at 682 cents instead of nine at 558; there is no
    restocking fee outside the change-of-mind branch and the policy refunds
    shipping, so the whole 4,590-cent gross goes back to the shopper and the five
    charges sum to 2,345.

    Design: Corner/state_machines/expectation_branch_resolve_sets_pdp_review_required
    """
    built = _build_expectation_review_case(api)

    case = fx.resolve_case(api, built["case"]["id"], "RESELLABLE_B")

    assert case["status"] == "RESOLVED_REFUNDED"
    assert case["restocking_fee_cents"] == 0
    assert case["refund_amount_cents"] == 4590
    assert case["total_cost_cents"] == 2345

    postings = fx.read_cost_postings(api, built["case"]["id"])
    assert [row["component"] for row in postings] == [
        "FREIGHT_INBOUND",
        "PROCESSING_LABOR",
        "REFURB_REPACK",
        "MARKDOWN_LOSS",
        "PAYMENT_FEE_UNRECOVERED",
    ]
    assert [row["amount_cents"] for row in postings] == [795, 682, 184, 551, 133]


def test_the_expectation_close_queues_the_product_page_and_spares_the_fit_counter(api):
    """PRD §3.8: "An `EXPECTATION_REVIEW → RESOLVED_REFUNDED` close carries no
    restocking fee and no chargeback. It increases the item's
    `expectation_return_count` by 1 alongside `total_return_count`, sets the item's
    `pdp_review_required` flag to true so that the product page copy is queued for a
    rewrite, and recomputes `chronic_return_score_bp` — where the expectation rate
    contributes its own weighted share — and re-derives `fit_watch_state`."  One
    expectation return over two delivered units is a rate of 5,000 basis points, and
    at a quarter weight that scores 1,250 — under the watch threshold — so the item
    stays normal and listed while its fit counter never moves.

    Design: Corner/state_machines/expectation_branch_resolve_sets_pdp_review_required
    """
    built = _build_expectation_review_case(api)

    fx.resolve_case(api, built["case"]["id"], "RESELLABLE_B")

    item = fx.read_item(api, built["item"]["id"])
    assert item["pdp_review_required"] is True
    assert item["expectation_return_count"] == 1
    assert item["fit_return_count"] == 0
    assert item["total_return_count"] == 1
    assert item["expectation_return_rate_bp"] == 5000
    assert item["fit_return_rate_bp"] == 0
    assert item["chronic_return_score_bp"] == 1250
    assert item["fit_watch_state"] == "NORMAL"
    assert item["listing_status"] == "LISTED"
    assert item["return_cost_accrued_cents"] == 2345

    order_line = fx.read_order_line(api, built["order_line"]["id"])
    assert order_line["status"] == "RETURNED"

    customer = fx.read_customer(api, built["customer"]["id"])
    assert customer["refunded_total_cents"] == 4590
    assert customer["change_of_mind_count"] == 0
    assert customer["abuse_strike_count"] == 0


def _build_chronic_suspended_item(api: ApiClient) -> dict:
    """An item carried all the way to published guidance and then driven back out of
    it by two refunded fit returns over its only two delivered units."""
    built = fx.setup_guidance_ready_item(
        api, SCENARIO_START, pdp_overrides={"detail_image_count": 3}
    )
    built["policy"] = fx.create_policy(
        api,
        category_code="TOPS",
        window_days=30,
        restocking_applies=True,
        non_refundable_shipping=False,
        effective_from="2026-01-01T00:00:00Z",
    )
    customer = fx.create_customer(api, email="shopper-s8@example.com")
    lines = [
        fx.create_order_line(
            api,
            customer["id"],
            built["item"]["id"],
            size_label=label,
            quantity=1,
            unit_price_cents=2295,
            shipping_allocated_cents=0,
            delivered_at="2026-05-20T00:00:00Z",
        )
        for label in ("M", "S")
    ]
    cases = []
    for line, reason_code in ((lines[0], "FIT_TOO_SMALL"), (lines[1], "FIT_TOO_LARGE")):
        case = fx.open_case(
            api, line["id"], customer["id"], requested_reason_code=reason_code
        )
        fx.classify_case(api, case["id"], reason_code, user_id="auditor-1")
        cases.append(fx.resolve_case(api, case["id"], "RESELLABLE_A"))
    built["customer"] = customer
    built["order_lines"] = lines
    built["cases"] = cases
    built["item"] = fx.read_item(api, built["item"]["id"])
    return built


def test_two_fit_returns_over_two_units_flip_the_item_to_chronic(api):
    """PRD §3.8: "`fit_watch_state` follows from the score and the raw fit count
    together: `CHRONIC` when the score is at least 2,500 basis points **and**
    `fit_return_count` is at least 2; otherwise `WATCH` when the score is at least
    1,500 basis points **and** `fit_return_count` is at least 1; otherwise
    `NORMAL`."  Both delivered units came back as fit returns, so the fit rate is
    the full 10,000 basis points and the three-quarters weight scores 7,500 with two
    fit returns behind it, which is the flip.  The flip takes the storefront axis
    down to suspended, the readiness axis all the way back to unverified, and
    reopens the brand's verified specification without anybody asking it to.

    Design: Corner/state_machines/suspended_item_relisted_by_publish_guidance_after_correction_and_void
    """
    built = _build_chronic_suspended_item(api)

    assert built["cases"][0]["status"] == "RESOLVED_REFUNDED"
    assert built["item"]["fit_return_count"] == 2
    assert built["item"]["units_sold_count"] == 2
    assert built["item"]["fit_return_rate_bp"] == 10000
    assert built["item"]["chronic_return_score_bp"] == 7500
    assert built["item"]["fit_watch_state"] == "CHRONIC"
    assert built["item"]["listing_status"] == "SUSPENDED"
    assert built["item"]["fit_readiness"] == "UNVERIFIED"

    spec = fx.read_spec(api, built["spec"]["id"])
    assert spec["status"] == "CORRECTION_REQUESTED"
    assert spec["correction_reason"] == "CHRONIC_FIT_RETURNS"


def test_voiding_one_case_walks_the_score_back_without_undoing_the_transitions(api):
    """PRD §3.8: "What reversal does *not* do is unwind transitions that already
    fired: a specification reopened into `CORRECTION_REQUESTED` stays there, a
    suspended listing stays suspended, and the 2,500-cent vendor debit stays spent."
    Voiding one of the two returns halves the fit rate and takes the score from
    7,500 down to 3,750, which is watch rather than chronic — but the listing is
    still suspended, the readiness axis is still unverified and the reopened
    specification is still waiting on the brand.

    Design: Corner/state_machines/suspended_item_relisted_by_publish_guidance_after_correction_and_void
    """
    built = _build_chronic_suspended_item(api)

    voided = fx.void_case(
        api, built["cases"][1]["id"], void_reason="AUDIT_REVERSAL"
    )
    assert voided["status"] == "VOIDED"
    assert voided["total_cost_cents"] == 0

    item = fx.read_item(api, built["item"]["id"])
    assert item["fit_return_count"] == 1
    assert item["fit_return_rate_bp"] == 5000
    assert item["chronic_return_score_bp"] == 3750
    assert item["fit_watch_state"] == "WATCH"
    assert item["listing_status"] == "SUSPENDED"
    assert item["fit_readiness"] == "UNVERIFIED"

    spec = fx.read_spec(api, built["spec"]["id"])
    assert spec["status"] == "CORRECTION_REQUESTED"

    vendor = fx.read_vendor(api, built["vendor"]["id"])
    assert vendor["correction_spend_cents"] == 2500


def test_republishing_guidance_is_the_only_route_back_onto_the_storefront(api):
    """PRD §3.4: "When the item's `listing_status` is `SUSPENDED` and its
    `fit_watch_state` is no longer `CHRONIC`, and every condition of the readiness
    advance above holds, `listing_status` moves from `SUSPENDED` back to `LISTED`."
    The void alone restores nothing, so the brand has to answer the correction
    request and the analyst has to rebuild the readiness axis: resubmit, verify,
    remap onto the same standardized chart, and only then does publishing carry the
    item back to listed and guidance-ready in one request.

    Design: Corner/state_machines/suspended_item_relisted_by_publish_guidance_after_correction_and_void
    """
    built = _build_chronic_suspended_item(api)
    fx.void_case(api, built["cases"][1]["id"], void_reason="AUDIT_REVERSAL")

    resubmitted = fx.resubmit_spec(
        api, built["spec"]["id"], built["vendor"]["id"]
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_round"] == 1

    verified = fx.verify_spec(api, built["spec"]["id"])
    assert verified["status"] == "VERIFIED"
    assert verified["violation_count"] == 0

    replacement = fx.create_mapping(
        api, built["item"]["id"], built["chart"]["id"]
    )
    assert replacement["status"] == "ACTIVE"
    assert replacement["coverage_bp"] == 10000

    superseded = fx.read_mapping(api, built["mapping"]["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["superseded_reason"] == "NEW_MAPPING"

    item = validate_success(
        api.publish_guidance(built["item"]["id"], make_fit_analyst_headers())
    )
    assert item["listing_status"] == "LISTED"
    assert item["fit_readiness"] == "GUIDANCE_READY"


def test_the_restored_item_carries_only_the_surviving_returns_arithmetic(api):
    """PRD §2.8: "Every derived counter, score, rate, and classification in this
    system is recomputed from its inputs rather than incrementally adjusted, so a
    reversal walks the derived state back down: voiding a return case can move
    `fit_watch_state` from `CHRONIC` back to `WATCH` or `NORMAL`, and can move a
    shopper's `abuse_status` from `BLOCKED` back to `RESTRICTED` or `CLEAR`."  Once
    the item is back on the storefront its numbers read from the one return that was
    never voided: a single fit return, a single refund on the shopper, an accrual of
    1,454 cents, and an order line free to be returned again.  The brand's correction
    round is not among the things restored.

    Design: Corner/state_machines/suspended_item_relisted_by_publish_guidance_after_correction_and_void
    """
    built = _build_chronic_suspended_item(api)
    fx.void_case(api, built["cases"][1]["id"], void_reason="AUDIT_REVERSAL")
    fx.resubmit_spec(api, built["spec"]["id"], built["vendor"]["id"])
    fx.verify_spec(api, built["spec"]["id"])
    fx.create_mapping(api, built["item"]["id"], built["chart"]["id"])
    fx.publish_guidance(api, built["item"]["id"])

    item = fx.read_item(api, built["item"]["id"])
    assert item["fit_return_count"] == 1
    assert item["units_sold_count"] == 2
    assert item["return_cost_accrued_cents"] == 1454

    vendor = fx.read_vendor(api, built["vendor"]["id"])
    assert vendor["correction_round_count"] == 1
    assert vendor["correction_spend_cents"] == 2500
    assert vendor["reliability_score_bp"] == 9700
    assert vendor["status"] == "ACTIVE"

    customer = fx.read_customer(api, built["customer"]["id"])
    assert customer["refunded_total_cents"] == 2295
    assert customer["return_case_count"] == 1

    order_line = fx.read_order_line(api, built["order_lines"][1]["id"])
    assert order_line["status"] == "DELIVERED"

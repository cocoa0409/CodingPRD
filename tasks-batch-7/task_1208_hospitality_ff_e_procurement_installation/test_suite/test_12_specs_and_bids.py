"""Queue B (breadth) — spec submission / brand-review guards and the vendor bid
lifecycle: evaluated-cost award selector, sample-round cap, and intake guards.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId,
    create_project, create_spec, submit_spec, brand_review,
    create_approved_spec, create_bid, sample_decide, award, get_bid,
    TEST_USERS,
)

PA = TEST_USERS["purchasing_agent_headers"]
VEN = TEST_USERS["vendor_headers"]


def test_spec_submit_invalid_from_submitted(api):
    """PRD §3.2: "Submission moves a spec from `DRAFT` to `SUBMITTED`; the same
    action resubmits a spec from `BRAND_REJECTED` back to `SUBMITTED`, closing the
    revision loop, and the loop is unbounded. From any other state the attempt
    fails with `ERR_SPEC_NOT_SUBMITTABLE`."
    A spec already in SUBMITTED cannot be submitted again.

    Design: Corner/state_machines/spec_submit_invalid_from_submitted
    """
    project = create_project(
        name="P-S1", hotel_name="H", brand_program="INDIE_SOFT",
        total_budget_cents=5_000_000,
    )
    spec = create_spec(
        project["id"], category="TEXTILES", description="Drapery",
        brand_standard_ref="IS-D", quantity_per_room=1, room_count=10,
        unit_budget_cents=5000,
    )
    submit_spec(spec["id"])

    res = api_client.submit_spec_item(spec["id"], PA)
    validate_error(res, ApiErrorId.ERR_SPEC_NOT_SUBMITTABLE, expected_status=409)

    after = validate_success(api_client.get_spec_item(spec["id"], PA))
    assert after["status"] == "SUBMITTED"


def test_brand_review_from_draft_rejected(api):
    """PRD §3.2: "The `BrandApprover` then records a brand-standard `decision` of
    `APPROVE` or `REJECT`, with optional `notes`, on a spec currently `SUBMITTED`
    — otherwise `ERR_SPEC_NOT_IN_REVIEW` — moving it to `BRAND_APPROVED` or
    `BRAND_REJECTED` respectively."
    A DRAFT spec was never submitted for review, so the decision fails.

    Design: Corner/state_machines/brand_review_from_draft_rejected
    """
    project = create_project(
        name="P-S2", hotel_name="H", brand_program="INDIE_SOFT",
        total_budget_cents=5_000_000,
    )
    spec = create_spec(
        project["id"], category="DECOR", description="Artwork",
        brand_standard_ref="IS-A", quantity_per_room=1, room_count=10,
        unit_budget_cents=3000,
    )

    res = api_client.brand_review_spec_item(
        spec["id"], {"decision": "APPROVE"}, TEST_USERS["brand_approver_headers"]
    )
    validate_error(res, ApiErrorId.ERR_SPEC_NOT_IN_REVIEW, expected_status=409)

    after = validate_success(api_client.get_spec_item(spec["id"], PA))
    assert after["status"] == "DRAFT"


def test_award_selector_and_terminal_lockdown(api):
    """PRD §3.3: "It is the bid's `unit_price_cents` multiplied by the spec's
    `total_qty`, plus the `freight_estimate_cents`, plus a lead-time penalty of
    25000 cents for each day by which `lead_time_days` exceeds the spec's
    `required_lead_days` — a bid at or under the required lead time pays no
    penalty."
    PRD §3.3: "Third, the bid must be the top-ranked eligible bid: among all
    `SAMPLE_APPROVED` bids for the same `spec_item_id`, the lowest
    `evaluated_cost_cents` wins, with ties broken by the earliest bid
    `created_at`; any other bid is rejected with `ERR_BID_NOT_BEST_EVALUATED`."
    PRD §3.3: "A successful award moves the bid to `AWARDED` and the system
    immediately moves every sibling bid of the same spec sitting in `SUBMITTED` or
    `SAMPLE_APPROVED` to `REJECTED`."
    PRD §3.3: "The `PurchasingAgent` rules on the current sample round with an
    `outcome` of `APPROVED` or `REJECTED`, legal only while the bid is `SUBMITTED`
    (otherwise `ERR_BID_NOT_SUBMITTED`), moving it to `SAMPLE_APPROVED` or
    `SAMPLE_REJECTED`."
    Bid A evaluates to 12000*40 + 30000 + 9*25000 = 735000c; bid B to
    13000*40 + 20000 + 0 = 540000c. Only B is awardable; A cascades to REJECTED;
    the AWARDED bid no longer accepts sample decisions.

    Design: Corner/state_machines/award_selector_and_terminal_lockdown
    """
    project = create_project(
        name="P-S5", hotel_name="H", brand_program="MARQUEE_SELECT",
        total_budget_cents=10_000_000,
    )
    spec = create_approved_spec(
        project["id"], category="FURNITURE", description="Guest chair",
        brand_standard_ref="MS-GR-01", quantity_per_room=2, room_count=20,
        unit_budget_cents=15000, required_lead_days=21,
    )
    bid_a = create_bid(spec["id"], vendor_name="VENDA", unit_price_cents=12000,
                       freight_estimate_cents=30000, lead_time_days=30)
    bid_b = create_bid(spec["id"], vendor_name="VENDA", unit_price_cents=13000,
                       freight_estimate_cents=20000, lead_time_days=20)
    sample_decide(bid_a["id"], "APPROVED")
    sample_decide(bid_b["id"], "APPROVED")

    res = api_client.award_bid(bid_a["id"], PA)
    validate_error(res, ApiErrorId.ERR_BID_NOT_BEST_EVALUATED,
                   expected_status=409)

    awarded = validate_success(api_client.award_bid(bid_b["id"], PA), 200)
    assert awarded["status"] == "AWARDED"
    assert awarded["evaluated_cost_cents"] == 540000

    bid_a_after = get_bid(bid_a["id"])
    assert bid_a_after["status"] == "REJECTED", (
        "the sibling bid must cascade to REJECTED on award"
    )
    assert bid_a_after["evaluated_cost_cents"] == 735000

    res = api_client.sample_decision_bid(bid_b["id"], {"outcome": "APPROVED"}, PA)
    validate_error(res, ApiErrorId.ERR_BID_NOT_SUBMITTED, expected_status=409)


def test_sample_round_cap_blocks_second_resubmit(api):
    """PRD §3.3: "A rejected vendor may resubmit: from `SAMPLE_REJECTED` only
    (otherwise `ERR_BID_NOT_RESUBMITTABLE`), and only while `sample_round` is
    still below the hard cap of 2 — a resubmit attempted at round 2 fails with
    `ERR_SAMPLE_ROUNDS_EXHAUSTED`, so the sample negotiation cycle `SUBMITTED` to
    `SAMPLE_REJECTED` to `SUBMITTED` permits at most one resubmit."
    PRD §3.3: "Resubmission increments `sample_round` by one, replaces any of
    `unit_price_cents`, `freight_estimate_cents`, or `lead_time_days` that are
    provided, and recomputes `evaluated_cost_cents`."

    Design: Corner/state_machines/sample_round_cap_blocks_second_resubmit
    """
    project = create_project(
        name="P-S4", hotel_name="H", brand_program="MARQUEE_SELECT",
        total_budget_cents=10_000_000,
    )
    spec = create_approved_spec(
        project["id"], category="FURNITURE", description="Guest chair",
        brand_standard_ref="MS-GR-01", quantity_per_room=2, room_count=20,
        unit_budget_cents=15000,
    )
    bid = create_bid(spec["id"], vendor_name="VENDA", unit_price_cents=15000,
                     freight_estimate_cents=0, lead_time_days=14)
    sample_decide(bid["id"], "REJECTED")

    resubmitted = validate_success(
        api_client.resubmit_bid(bid["id"], {"unit_price_cents": 14500}, VEN), 200
    )
    assert resubmitted["sample_round"] == 2
    assert resubmitted["status"] == "SUBMITTED"

    sample_decide(bid["id"], "REJECTED")

    res = api_client.resubmit_bid(bid["id"], {"unit_price_cents": 14000}, VEN)
    validate_error(res, ApiErrorId.ERR_SAMPLE_ROUNDS_EXHAUSTED,
                   expected_status=409)

    after = get_bid(bid["id"])
    assert after["status"] == "SAMPLE_REJECTED"
    assert after["sample_round"] == 2


def test_bid_state_guards(api):
    """PRD §3.3: "Bids are accepted only against `BRAND_APPROVED` specs; anything
    earlier is rejected with `ERR_SPEC_NOT_OPEN_FOR_BIDS`."
    PRD §3.3: "First, the bid being awarded must itself be `SAMPLE_APPROVED`, else
    `ERR_BID_NOT_SAMPLE_APPROVED`."
    PRD §3.3: "A rejected vendor may resubmit: from `SAMPLE_REJECTED` only
    (otherwise `ERR_BID_NOT_RESUBMITTABLE`)"
    Three guard arms: intake against a merely SUBMITTED spec, award of a merely
    SUBMITTED bid, and resubmit of a SAMPLE_APPROVED bid.

    Design: Corner/errors/bid_state_guards
    """
    project = create_project(
        name="P-R7", hotel_name="H", brand_program="MARQUEE_SELECT",
        total_budget_cents=5_000_000,
    )
    spec_1 = create_spec(
        project["id"], category="FURNITURE", description="Chair",
        brand_standard_ref="MS-C", quantity_per_room=2, room_count=20,
        unit_budget_cents=15000,
    )
    submit_spec(spec_1["id"])
    spec_2 = create_approved_spec(
        project["id"], category="FURNITURE", description="Lamp",
        brand_standard_ref="MS-L", quantity_per_room=1, room_count=10,
        unit_budget_cents=10000,
    )
    bid_2 = create_bid(spec_2["id"], vendor_name="VENDA",
                       unit_price_cents=10000, freight_estimate_cents=0,
                       lead_time_days=7)

    res = api_client.create_bid(
        {"spec_item_id": spec_1["id"], "vendor_name": "VENDA",
         "unit_price_cents": 15000, "freight_estimate_cents": 0,
         "lead_time_days": 14},
        VEN,
    )
    validate_error(res, ApiErrorId.ERR_SPEC_NOT_OPEN_FOR_BIDS,
                   expected_status=409)

    res = api_client.award_bid(bid_2["id"], PA)
    validate_error(res, ApiErrorId.ERR_BID_NOT_SAMPLE_APPROVED,
                   expected_status=409)

    sample_decide(bid_2["id"], "APPROVED")
    res = api_client.resubmit_bid(bid_2["id"], {"unit_price_cents": 9000}, VEN)
    validate_error(res, ApiErrorId.ERR_BID_NOT_RESUBMITTABLE,
                   expected_status=409)

    after = get_bid(bid_2["id"])
    assert after["status"] == "SAMPLE_APPROVED"
    assert after["sample_round"] == 1

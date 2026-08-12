"""Sale offering, bid book mechanics, award and reoffer loop (PRD §3.4)."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_buyer_payload,
    create_prescription_payload,
    create_sale_payload,
    create_forester_payload,
    create_landowner_payload,
    create_stand_payload,
    create_tract_payload,
    create_cruise_payload,
    make_buyer_headers,
    make_forester_headers,
    make_landowner_headers,
    setup_approved_prescription,
    setup_certified_cruise,
    setup_reconciled_cruise,
    setup_sale_bidding_open,
    setup_sale_draft,
    setup_sale_offered,
    setup_tract_and_stand,
)

ADMIN = TEST_USERS["admin_headers"]


def test_sale_offer_requires_prescription_approved_and_cruise_certified(api):
    """PRD §3.4: "The prescription must be `APPROVED`, else
    `ERR_PRESCRIPTION_NOT_APPROVED` (HTTP 409). The prescription's cruise must
    be `CERTIFIED`, else `ERR_CRUISE_NOT_CERTIFIED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/sale_offer_requires_prescription_approved_and_cruise_certified
    """
    base = setup_reconciled_cruise()
    fh = base["forester_headers"]
    lh = base["landowner_headers"]
    prescription = get_success_data(api.create_prescription(
        create_prescription_payload(stand_id=base["stand"]["id"],
                                    cruise_id=base["cruise"]["id"]),
        fh,
    ))
    get_success_data(api.propose_prescription(prescription["id"], fh))
    # approve with cruise merely RECONCILED -> ERR_CRUISE_NOT_CERTIFIED
    resp_approve = api.approve_prescription(prescription["id"], lh)
    validate_error(resp_approve, ApiErrorId.ERR_CRUISE_NOT_CERTIFIED)

    # Certify cruise now.
    stand = get_success_data(api.get_stand(base["stand"]["id"], fh))
    get_success_data(api.certify_cruise(
        base["cruise"]["id"], {"expected_stand_version": stand["version"]}, fh
    ))

    # Sale DRAFT on PROPOSED prescription; offer -> ERR_PRESCRIPTION_NOT_APPROVED.
    sale = get_success_data(api.create_sale(
        create_sale_payload(tract_id=base["tract"]["id"],
                            stand_id=base["stand"]["id"],
                            prescription_id=prescription["id"]),
        fh,
    ))
    resp_offer = api.offer_sale(sale["id"], fh)
    validate_error(resp_offer, ApiErrorId.ERR_PRESCRIPTION_NOT_APPROVED)
    sale_now = get_success_data(api.get_sale(sale["id"], fh))
    assert sale_now["status"] == "DRAFT"


def test_sale_offer_with_proposed_prescription_only_fails(api):
    """PRD §3.4: "The prescription must be `APPROVED`, else
    `ERR_PRESCRIPTION_NOT_APPROVED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/sale_offer_requires_prescription_approved_and_cruise_certified
    """
    base = setup_certified_cruise()
    fh = base["forester_headers"]
    prescription = get_success_data(api.create_prescription(
        create_prescription_payload(stand_id=base["stand"]["id"],
                                    cruise_id=base["cruise"]["id"]),
        fh,
    ))
    get_success_data(api.propose_prescription(prescription["id"], fh))
    sale = get_success_data(api.create_sale(
        create_sale_payload(tract_id=base["tract"]["id"],
                            stand_id=base["stand"]["id"],
                            prescription_id=prescription["id"]),
        fh,
    ))
    resp = api.offer_sale(sale["id"], fh)
    validate_error(resp, ApiErrorId.ERR_PRESCRIPTION_NOT_APPROVED)


def test_cancel_cancelled_sale_returns_already_terminal(api):
    """PRD §2.7: "no transition is ever permitted out of a terminal state
    (`ERR_ALREADY_TERMINAL`, HTTP 409)."
    PRD §3.4: "`AWARDED` and `CANCELLED` are terminal."

    Design: Corner/state_machines/cancel_cancelled_sale_returns_already_terminal
    """
    base = setup_sale_draft(sale_overrides={"sale_type": "LUMP_SUM",
                                            "advertised_minimum_cents": 7_000_000,
                                            "species_minimum_rates": None})
    fh = base["forester_headers"]
    get_success_data(api.cancel_sale(base["sale"]["id"], fh))
    resp = api.cancel_sale(base["sale"]["id"], fh)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


def test_below_minimum_bid_disqualified_then_no_sale_then_reoffer(api):
    """PRD §3.4: "Every `SUBMITTED` bid whose `bid_total_cents` falls below
    `advertised_minimum_cents` is moved to `DISQUALIFIED` — a bid exactly equal
    to the minimum qualifies."
    PRD §3.4: "When `winning_bid_id` is null the forester instead declares
    no-sale: the sale moves `BIDDING_CLOSED → NO_SALE` and all `SUBMITTED`
    bids move to `LOST`."
    PRD §3.4: "reoffering moves `NO_SALE → OFFERED` with a fresh bid window
    supplied in the request".

    Design: Corner/state_machines/below_minimum_bid_disqualified_then_no_sale_then_reoffer
    """
    base = setup_sale_bidding_open(
        sale_overrides={"sale_type": "LUMP_SUM",
                        "advertised_minimum_cents": 8_000_000,
                        "species_minimum_rates": None},
    )
    fh = base["forester_headers"]
    bh = base["buyer_headers"]
    sale = base["sale"]
    bid = get_success_data(api.submit_bid(
        sale["id"],
        {"expected_sale_version": sale["version"], "deposit_cents": 50_000,
         "lump_sum_amount_cents": 7_000_000},
        bh,
    ))
    get_success_data(api.set_clock({"to_iso8601": "2026-05-21T00:00:00Z"}, ADMIN))
    sale = get_success_data(api.close_bidding(sale["id"], fh))
    assert sale["winning_bid_id"] is None
    bid_after = get_success_data(api.get_bid(bid["id"], fh))
    assert bid_after["status"] == "DISQUALIFIED"

    sale = get_success_data(api.no_sale(sale["id"], fh))
    assert sale["status"] == "NO_SALE"

    reoffered = validate_success(api.reoffer_sale(
        sale["id"],
        {"bid_open_at": "2026-06-01T00:00:00Z", "bid_close_at": "2026-06-10T00:00:00Z",
         "advertised_minimum_cents": 7_500_000},
        fh,
    ))
    assert reoffered["status"] == "OFFERED"
    assert reoffered["bid_open_at"] == "2026-06-01T00:00:00Z"
    assert reoffered["advertised_minimum_cents"] == 7_500_000


def test_buyer_resubmission_supersedes_prior_bid(api):
    """PRD §3.4: "A buyer who bids again on the same sale replaces their own
    prior entry: the earlier `SUBMITTED` bid moves to `SUPERSEDED`, the new bid
    becomes that buyer's sole `SUBMITTED` bid, and both bids' versions
    increment."

    Design: Corner/state_machines/buyer_resubmission_supersedes_prior_bid
    """
    base = setup_sale_bidding_open(
        sale_overrides={"sale_type": "LUMP_SUM",
                        "advertised_minimum_cents": 7_000_000,
                        "species_minimum_rates": None},
    )
    bh = base["buyer_headers"]
    fh = base["forester_headers"]
    sale = base["sale"]
    bid1 = get_success_data(api.submit_bid(
        sale["id"],
        {"expected_sale_version": sale["version"], "deposit_cents": 50_000,
         "lump_sum_amount_cents": 8_000_000},
        bh,
    ))
    sale = get_success_data(api.get_sale(sale["id"], fh))
    bid2 = validate_success(api.submit_bid(
        sale["id"],
        {"expected_sale_version": sale["version"], "deposit_cents": 60_000,
         "lump_sum_amount_cents": 8_100_000},
        bh,
    ), 201)
    bid1_now = get_success_data(api.get_bid(bid1["id"], fh))
    assert bid1_now["status"] == "SUPERSEDED"
    assert bid2["status"] == "SUBMITTED"
    assert bid2["bid_total_cents"] == 8_100_000


def test_award_non_winning_bid_rejected(api):
    """PRD §3.4: "from `BIDDING_CLOSED`, the forester's award request must
    name a `bid_id` exactly equal to the computed `winning_bid_id`, or it is
    refused with `ERR_NOT_WINNING_BID` (HTTP 409)."

    Design: Corner/state_machines/award_non_winning_bid_rejected
    """
    base = setup_sale_bidding_open(
        sale_overrides={"sale_type": "LUMP_SUM",
                        "advertised_minimum_cents": 7_000_000,
                        "species_minimum_rates": None},
    )
    fh = base["forester_headers"]
    buyer2 = get_success_data(api.create_buyer(
        create_buyer_payload(company_name="Red Mill", license_no="B-200"), ADMIN
    ))
    bh2 = make_buyer_headers(buyer2["id"])
    sale = base["sale"]
    bh1 = base["buyer_headers"]
    bid1 = get_success_data(api.submit_bid(
        sale["id"],
        {"expected_sale_version": sale["version"], "deposit_cents": 50_000,
         "lump_sum_amount_cents": 8_000_000},
        bh1,
    ))
    sale = get_success_data(api.get_sale(sale["id"], fh))
    bid2 = get_success_data(api.submit_bid(
        sale["id"],
        {"expected_sale_version": sale["version"], "deposit_cents": 50_000,
         "lump_sum_amount_cents": 8_100_000},
        bh2,
    ))
    get_success_data(api.set_clock({"to_iso8601": "2026-05-21T00:00:00Z"}, ADMIN))
    sale = get_success_data(api.close_bidding(sale["id"], fh))
    assert sale["winning_bid_id"] == bid2["id"]
    resp = api.award_sale(sale["id"], {"bid_id": bid1["id"]}, fh)
    validate_error(resp, ApiErrorId.ERR_NOT_WINNING_BID)
    sale_now = get_success_data(api.get_sale(sale["id"], fh))
    assert sale_now["status"] == "BIDDING_CLOSED"
    assert sale_now["winning_bid_id"] == bid2["id"]


def test_winner_tiebreak_deposit_desc(api):
    """PRD §3.4: "Among the bids that remain, `winning_bid_id` is the highest
    `bid_total_cents`; ties break first toward the larger `deposit_cents`,
    then toward the earlier `submitted_at`, then toward the buyer whose
    `created_at` is earliest."

    Design: Corner/state_machines/winner_tiebreak_deposit_desc
    """
    base = setup_sale_bidding_open(
        sale_overrides={"sale_type": "LUMP_SUM",
                        "advertised_minimum_cents": 7_000_000,
                        "species_minimum_rates": None},
    )
    fh = base["forester_headers"]
    buyer2 = get_success_data(api.create_buyer(
        create_buyer_payload(company_name="Red Mill", license_no="B-200"), ADMIN
    ))
    bh2 = make_buyer_headers(buyer2["id"])
    sale = base["sale"]
    bh1 = base["buyer_headers"]
    bid1 = get_success_data(api.submit_bid(
        sale["id"],
        {"expected_sale_version": sale["version"], "deposit_cents": 100_000,
         "lump_sum_amount_cents": 8_000_000},
        bh1,
    ))
    sale = get_success_data(api.get_sale(sale["id"], fh))
    bid2 = get_success_data(api.submit_bid(
        sale["id"],
        {"expected_sale_version": sale["version"], "deposit_cents": 200_000,
         "lump_sum_amount_cents": 8_000_000},
        bh2,
    ))
    get_success_data(api.set_clock({"to_iso8601": "2026-05-21T00:00:00Z"}, ADMIN))
    sale = get_success_data(api.close_bidding(sale["id"], fh))
    assert sale["winning_bid_id"] == bid2["id"], (
        f"higher-deposit bid {bid2['id']} should win over {bid1['id']} at equal total"
    )


def test_withdraw_after_close_returns_invalid_transition(api):
    """PRD §3.4: "withdrawing is allowed on the buyer's own `SUBMITTED` bid
    while the sale is `BIDDING_OPEN` and the clock has not yet reached
    `bid_close_at`".

    Design: Corner/state_machines/withdraw_after_close_returns_invalid_transition
    """
    base = setup_sale_bidding_open(
        sale_overrides={"sale_type": "LUMP_SUM",
                        "advertised_minimum_cents": 7_000_000,
                        "species_minimum_rates": None},
    )
    fh = base["forester_headers"]
    bh = base["buyer_headers"]
    sale = base["sale"]
    bid = get_success_data(api.submit_bid(
        sale["id"],
        {"expected_sale_version": sale["version"], "deposit_cents": 50_000,
         "lump_sum_amount_cents": 8_000_000},
        bh,
    ))
    get_success_data(api.set_clock({"to_iso8601": "2026-05-21T00:00:00Z"}, ADMIN))
    get_success_data(api.close_bidding(sale["id"], fh))
    resp = api.withdraw_bid(bid["id"], bh)
    validate_error(resp, ApiErrorId.ERR_SALE_NOT_OPEN_FOR_BIDDING)


def test_sales_list_pagination_defaults(api):
    """PRD §2.3: "The `limit` defaults to 10, must be at least 1, and may not
    exceed 100. The `offset` defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`, where `has_more` indicates whether further
    pages exist beyond the returned window."

    Design: Corner/endpoints/sales_list_pagination_defaults
    """
    base = setup_approved_prescription()
    fh = base["forester_headers"]
    for i in range(3):
        payload = create_sale_payload(tract_id=base["tract"]["id"],
                                      stand_id=base["stand"]["id"],
                                      prescription_id=base["prescription"]["id"],
                                      sale_type="LUMP_SUM",
                                      advertised_minimum_cents=7_000_000 + i * 100_000)
        payload.pop("species_minimum_rates", None)
        get_success_data(api.create_sale(payload, fh))
    resp = api.list_sales(fh, params={"limit": 2})
    data, meta = validate_paginated(resp)
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    resp2 = api.list_sales(fh)
    data2, meta2 = validate_paginated(resp2)
    assert len(data2) == 3
    assert meta2["total_count"] == 3


def test_bids_filtered_list_by_sale(api):
    """PRD §2.3: "bids by `sale_id`, `buyer_id`, and `status`".

    Design: Corner/endpoints/bids_filtered_list_by_sale
    """
    base = setup_sale_bidding_open(
        sale_overrides={"sale_type": "LUMP_SUM",
                        "advertised_minimum_cents": 7_000_000,
                        "species_minimum_rates": None},
    )
    fh = base["forester_headers"]
    bh = base["buyer_headers"]
    # Second sale on the same prescription (no bid).
    payload2 = create_sale_payload(tract_id=base["tract"]["id"],
                                   stand_id=base["stand"]["id"],
                                   prescription_id=base["prescription"]["id"],
                                   sale_type="LUMP_SUM",
                                   advertised_minimum_cents=7_100_000)
    payload2.pop("species_minimum_rates", None)
    sale2 = get_success_data(api.create_sale(payload2, fh))
    sale1 = base["sale"]
    bid1 = get_success_data(api.submit_bid(
        sale1["id"],
        {"expected_sale_version": sale1["version"], "deposit_cents": 100_000,
         "lump_sum_amount_cents": 8_000_000},
        bh,
    ))
    resp1 = api.list_bids(fh, params={"sale_id": sale1["id"]})
    data1, meta1 = validate_paginated(resp1)
    assert [b["id"] for b in data1] == [bid1["id"]]

    resp2 = api.list_bids(fh, params={"sale_id": sale2["id"]})
    data2, meta2 = validate_paginated(resp2)
    assert data2 == []
    assert meta2["total_count"] == 0

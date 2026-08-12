"""Consignment agreements, the showroom floor, the proceeds split and Cascade C."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_consignment_agreement,
    assert_sale_proceeds_conservation,
    assert_same_instant,
    consignment_agreement_payload,
    instrument_version,
    make_showroom_agent_headers,
    move_instrument_to_shop,
    read_instrument,
    set_clock,
    setup_client_with_instrument,
    setup_listed_consignment,
    setup_listed_consignment_with_rebuild_advance,
    validate_error,
    validate_success,
    warranty_for_instrument,
)

MANAGER = TEST_USERS["shop_manager_headers"]
AGENT = TEST_USERS["showroom_agent_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_above_reserve_sale_splits_the_proceeds_and_conserves_them(api):
    """PRD 3.10: "First, `advance_recovered_cents` is the smaller of
    `advanced_restoration_cents` and `sale_price_cents` — the shop cannot recover more
    advance than the piano fetched. Second, the residual is `sale_price_cents` less
    `advance_recovered_cents`. Third, the commission is computed from one of two
    variants. When `sale_price_cents` is at most `reserve_price_cents`, `split_variant`
    is `AT_OR_BELOW_RESERVE` and the commission is 25 percent of the whole residual,
    rounded half up. When the sale beats the reserve, `split_variant` is
    `ABOVE_RESERVE`: the excess is `sale_price_cents` less `reserve_price_cents`; the
    reserve portion is the residual less that excess, floored at 0; the excess portion
    is the residual less the reserve portion; and the commission is 15 percent of the
    reserve portion rounded half up **plus** 50 percent of the excess portion rounded
    half up, the two legs rounded independently before being added."
    PRD 3.10: "Fourth, `consignor_payout_cents` is the residual less the commission, and
    `shop_commission_cents` is computed **last**, as `sale_price_cents` less
    `advance_recovered_cents` less `consignor_payout_cents`, so that any rounding
    remainder lands on the shop and the three parts add back to the sale price exactly."
    PRD 3.10: "Activation sets `start_date` to the clock's date, sets `expires_at` to
    180 days after the clock, and computes `advanced_restoration_cents` as the sum of
    `contract_total_cents` over that instrument's `COMPLETED` service orders whose
    `service_type` is `REBUILD` — the shop's own money sunk into restoring the piano,
    which it recovers off the top when the piano sells."
    PRD 3.10: "Its remaining term is recomputed: the whole days elapsed from the
    warranty's `start_date` to the sale date are subtracted from its `term_days` to give
    the remainder, and the new `term_days` is that remainder or 30 days, whichever is
    **larger** — so even a nearly exhausted warranty transfers with a month of cover."

    Design: Corner/calculations/consignment_above_reserve_split_conserves_proceeds
    """
    ctx = setup_listed_consignment_with_rebuild_advance(reserve_price_cents=1800000)
    agreement, buyer = ctx["agreement"], ctx["buyer"]
    assert agreement["advanced_restoration_cents"] == 1363000

    sold = validate_success(
        api.record_consignment_sale(
            agreement["id"],
            {"buyer_client_id": buyer["id"], "sale_price_cents": 2000000},
            make_showroom_agent_headers("agent-advance-sales"),
        )
    )

    assert_consignment_agreement(sold)
    assert sold["split_variant"] == "ABOVE_RESERVE"
    assert sold["advance_recovered_cents"] == 1363000
    assert sold["shop_commission_cents"] == 165550
    assert sold["consignor_payout_cents"] == 471450
    assert sold["status"] == "SOLD"
    assert_sale_proceeds_conservation(sold)

    instrument = read_instrument(ctx["instrument"]["id"])
    assert instrument["custody_status"] == "SOLD"
    assert instrument["client_id"] == buyer["id"]

    warranty = warranty_for_instrument(instrument["id"])
    assert warranty["status"] == "TRANSFERRED"
    assert warranty["client_id"] == buyer["id"]
    assert warranty["term_days"] == 1095, "no days had elapsed at the sale"


def test_withdrawing_a_listed_agreement_returns_the_instrument_to_the_client(api):
    """PRD 3.10: "A `ShowroomAgent` **withdraws** an `ACTIVE` or `LISTED` agreement with
    an optional `reason`, and the daily sweep **expires** an `ACTIVE` or `LISTED`
    agreement once the clock reaches `expires_at`. Both clear the instrument's
    `consignment_agreement_id` and, when the instrument is standing on the showroom
    floor, return its custody to `AT_CLIENT_SITE`."
    PRD 3.10: "Activation sets `start_date` to the clock's date, sets `expires_at` to
    180 days after the clock, and computes `advanced_restoration_cents` as the sum of
    `contract_total_cents` over that instrument's `COMPLETED` service orders whose
    `service_type` is `REBUILD` — the shop's own money sunk into restoring the piano,
    which it recovers off the top when the piano sells."

    Design: Corner/state_machines/consignment_withdraw_returns_instrument_from_showroom_to_client_site
    """
    ctx = setup_listed_consignment(reserve_price_cents=900000)
    agreement = ctx["agreement"]
    assert agreement["advanced_restoration_cents"] == 0, "no COMPLETED REBUILD exists"
    assert_same_instant(
        agreement["expires_at"], "2026-10-28T00:00:00Z",
        "ConsignmentAgreement.expires_at",
    )

    withdrawn = validate_success(
        api.withdraw_consignment_agreement(
            agreement["id"], {"reason": "owner changed their mind"}, AGENT
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"

    instrument = read_instrument(ctx["instrument"]["id"])
    assert instrument["custody_status"] == "AT_CLIENT_SITE"
    assert instrument["consignment_agreement_id"] is None


def test_sale_below_the_eighty_percent_floor_is_refused(api):
    """PRD 3.10: "The price must also clear a floor: the reserve price multiplied by
    0.80 and rounded half up to whole cents, compared inclusively, so a sale landing
    exactly on the floor is accepted while anything below is refused with
    `ERR_SALE_BELOW_FLOOR`."
    PRD 3.10: "When `sale_price_cents` is at most `reserve_price_cents`, `split_variant`
    is `AT_OR_BELOW_RESERVE` and the commission is 25 percent of the whole residual,
    rounded half up."

    Design: Corner/validations/consignment_sale_below_the_eighty_percent_floor_is_rejected
    """
    ctx = setup_listed_consignment(
        reserve_price_cents=1000000, creator_user_id="agent-floor-1"
    )
    agreement, buyer = ctx["agreement"], ctx["buyer"]
    seller = make_showroom_agent_headers("agent-floor-sales")

    response = api.record_consignment_sale(
        agreement["id"],
        {"buyer_client_id": buyer["id"], "sale_price_cents": 700000},
        seller,
    )
    validate_error(response, ApiErrorId.ERR_SALE_BELOW_FLOOR.value)

    still_listed = validate_success(
        api.get_consignment_agreement(agreement["id"], MANAGER)
    )
    assert still_listed["status"] == "LISTED"
    assert still_listed["sale_price_cents"] is None

    sold = validate_success(
        api.record_consignment_sale(
            agreement["id"],
            {"buyer_client_id": buyer["id"], "sale_price_cents": 800000},
            seller,
        )
    )
    assert sold["split_variant"] == "AT_OR_BELOW_RESERVE"
    assert sold["shop_commission_cents"] == 200000
    assert sold["consignor_payout_cents"] == 600000
    assert_sale_proceeds_conservation(sold)


def test_listing_after_the_consignment_term_expires_is_refused(api):
    """PRD 2.8: "**Consignment validity.** The logical clock must be strictly before the
    agreement's `expires_at`. Otherwise `ERR_CONSIGNMENT_EXPIRED` (409). Applies to
    `POST /consignment-agreements/{id}/list-showroom` and
    `POST /consignment-agreements/{id}/record-sale`."
    PRD 3.4: "**Step 3** moves every `ACTIVE` or `LISTED` consignment agreement whose
    `expires_at` the clock has reached or passed to `EXPIRED`, clearing the instrument's
    `consignment_agreement_id` and returning it from `SHOWROOM_FLOOR` to
    `AT_CLIENT_SITE` where applicable, reporting `expired_consignment_count`."

    Design: Corner/validations/consignment_listing_after_the_term_expires_is_rejected
    """
    base = setup_client_with_instrument()
    move_instrument_to_shop(base["instrument"]["id"])
    creator = make_showroom_agent_headers("agent-expiry-1")
    agreement = validate_success(
        api.create_consignment_agreement(
            consignment_agreement_payload(
                base["instrument"]["id"], base["client"]["id"], 900000,
                instrument_version(base["instrument"]["id"]),
            ),
            creator,
        ),
        201,
    )
    validate_success(api.activate_consignment_agreement(agreement["id"], creator))
    set_clock("2026-11-01T00:00:00Z")

    response = api.list_showroom_consignment_agreement(agreement["id"], creator)
    validate_error(response, ApiErrorId.ERR_CONSIGNMENT_EXPIRED.value)

    assert validate_success(
        api.get_consignment_agreement(agreement["id"], MANAGER)
    )["status"] == "ACTIVE"
    assert read_instrument(base["instrument"]["id"])["custody_status"] == "IN_SHOP"

    report = validate_success(api.run_daily_sweep(ADMIN))
    assert report["expired_consignment_count"] == 1
    assert validate_success(
        api.get_consignment_agreement(agreement["id"], MANAGER)
    )["status"] == "EXPIRED"


def test_the_agreement_creator_cannot_record_its_sale(api):
    """PRD 2.8: "**Sale segregation.** The recording `X-User-ID` must differ from
    `created_by_user_id`. Otherwise `ERR_SEGREGATION_OF_DUTIES` (403). Applies to
    `POST /consignment-agreements/{id}/record-sale`."
    PRD 3.10: "Drafting stamps `created_by_user_id` from the acting `X-User-ID`, bumps
    the instrument's `version` by 1, and enters status `DRAFT` with `buyer_client_id`,
    `sale_price_cents`, `split_variant` and `expires_at` all null and
    `advanced_restoration_cents`, `advance_recovered_cents`, `shop_commission_cents` and
    `consignor_payout_cents` all 0."

    Design: Corner/rbac/consignment_creator_cannot_record_the_sale
    """
    ctx = setup_listed_consignment(
        reserve_price_cents=900000, creator_user_id="agent-sod-1"
    )
    agreement, buyer = ctx["agreement"], ctx["buyer"]

    blocked = api.record_consignment_sale(
        agreement["id"],
        {"buyer_client_id": buyer["id"], "sale_price_cents": 900000},
        make_showroom_agent_headers("agent-sod-1"),
    )
    validate_error(blocked, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    still_listed = validate_success(
        api.get_consignment_agreement(agreement["id"], MANAGER)
    )
    assert still_listed["status"] == "LISTED"
    assert still_listed["created_by_user_id"] == "agent-sod-1"

    sold = validate_success(
        api.record_consignment_sale(
            agreement["id"],
            {"buyer_client_id": buyer["id"], "sale_price_cents": 900000},
            make_showroom_agent_headers("agent-sod-1-sales"),
        )
    )
    assert sold["split_variant"] == "AT_OR_BELOW_RESERVE"
    assert sold["shop_commission_cents"] == 225000
    assert sold["consignor_payout_cents"] == 675000
    assert_sale_proceeds_conservation(sold)

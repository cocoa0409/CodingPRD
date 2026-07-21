"""Gift intake: designation, the two fee components, and what the card is charged."""

from test_helpers import (
    ApiErrorId,
    assert_donation,
    create_donation_payload,
    create_donor,
    create_gift,
    create_participant,
    create_settled_gift,
    make_donor_headers,
    setup_published_campaign,
    setup_two_published_campaigns,
    validate_error,
    validate_success,
)


def test_each_fee_component_is_rounded_on_its_own_before_the_sum(api):
    """PRD §3.4: "Two components are derived independently and each is rounded to
    whole cents by itself before anything is added."
    PRD §3.4: "The stored `fee_cents` is the platform component plus the processing
    component plus a flat 30-cent processing charge; that sum is never re-rounded."

    Design: Difficulty/combinatorial_formula/fee_rounding_per_line_then_sum_not_sum_then_round
    """
    ctx = setup_published_campaign(api=api)
    donor = create_donor(api=api)

    first = create_gift(
        ctx["campaign_id"], donor["id"], "CAMPAIGN", ctx["campaign_id"], 1550, api=api
    )
    second = create_gift(
        ctx["campaign_id"], donor["id"], "CAMPAIGN", ctx["campaign_id"], 2450, api=api
    )

    assert first["fee_cents"] == 153, "78 platform + 45 processing + 30 flat"
    assert first["net_cents"] == 1397
    assert second["fee_cents"] == 224, "123 platform + 71 processing + 30 flat"
    assert second["net_cents"] == 2226


def test_campaign_fee_total_sums_the_per_gift_figures(api):
    """PRD §3.9: "`fee_total_cents` is the sum of the per-gift `fee_cents` over gifts
    whose payment dimension is `SETTLED` **or** `REFUNDED` — fees are retained on a
    refund, and per §2.6 this total is built by summing values already rounded on each
    row rather than by rounding an aggregate."
    PRD §2.6: "Second, when a campaign-level total is derived from many rows, the
    system sums the values already stored on each row rather than recomputing an
    aggregate from raw inputs and rounding once at the end — round per line, then sum."

    Design: Difficulty/combinatorial_formula/fee_rounding_per_line_then_sum_not_sum_then_round
    """
    ctx = setup_published_campaign(api=api)
    donor = create_donor(api=api)
    create_settled_gift(
        ctx["campaign_id"], donor["id"], "CAMPAIGN", ctx["campaign_id"], 1550, api=api
    )
    create_settled_gift(
        ctx["campaign_id"], donor["id"], "CAMPAIGN", ctx["campaign_id"], 2450, api=api
    )

    report = validate_success(api.get_report(ctx["campaign_id"], ctx["cm_headers"]))

    assert report["fee_total_cents"] == 377, "153 + 224, not a re-rounded 376"
    assert report["gross_amount_cents"] == 4000


def test_a_covered_fee_is_derived_from_the_designated_amount_only(api):
    """PRD §3.4: "when `cover_fees` is false, `net_cents` — the amount the campaign
    nets from the gift itself — is `amount_cents` reduced by `fee_cents`; when
    `cover_fees` is true, `net_cents` is the full `amount_cents`."
    PRD §3.4: "The system does not re-derive the fee from the charged figure and does
    not iterate toward a fixed point; exactly one grossing-up pass is performed."

    Design: Difficulty/combinatorial_formula/donor_covered_fee_single_pass_gross_up
    """
    ctx = setup_published_campaign(api=api)
    donor = create_donor(api=api)

    response = api.create_donation(
        create_donation_payload(
            ctx["campaign_id"], donor["id"], "CAMPAIGN", ctx["campaign_id"], 10000,
            cover_fees=True,
        ),
        make_donor_headers(donor["id"]),
    )

    gift = validate_success(response, expected_status=201)
    assert gift["fee_cents"] == 820, "Derived from amount_cents, never from the charge"
    assert gift["net_cents"] == 10000


def test_a_covered_fee_charges_the_amount_plus_that_fee(api):
    """PRD §3.4: "When `cover_fees` is true, `charged_amount_cents` is `amount_cents`
    plus `fee_cents`; otherwise `charged_amount_cents` equals `amount_cents`."
    PRD §3.4: "A new gift begins with its payment dimension at `PENDING` and its match
    dimension at `UNMATCHED`, with `matched_amount_cents` at 0, no pool attached, and
    both `settled_at` and `refunded_at` empty."

    Design: Difficulty/combinatorial_formula/donor_covered_fee_single_pass_gross_up
    """
    ctx = setup_published_campaign(api=api)
    donor = create_donor(api=api)

    response = api.create_donation(
        create_donation_payload(
            ctx["campaign_id"], donor["id"], "CAMPAIGN", ctx["campaign_id"], 10000,
            cover_fees=True,
        ),
        make_donor_headers(donor["id"]),
    )

    gift = validate_success(response, expected_status=201)
    assert gift["charged_amount_cents"] == 10820, "10000 + 820, not an iterated 10885"
    assert gift["payment_status"] == "PENDING"


def test_fee_net_and_match_figures_are_computed_by_the_server(api):
    """PRD §3.4: "Fees are computed once, at gift creation, and never recomputed."
    PRD §3.4: "The **platform component** is the gift's `amount_cents` multiplied by 5
    percent, rounded half up. The **processing component** is the gift's
    `amount_cents` multiplied by 2.9 percent, rounded half up."

    Design: Corner/entities/donation_computed_fee_fields_input_ignored
    """
    ctx = setup_published_campaign(api=api)
    donor = create_donor(api=api)

    response = api.create_donation(
        create_donation_payload(
            ctx["campaign_id"], donor["id"], "CAMPAIGN", ctx["campaign_id"], 10000,
            benefit_value_cents=0,
        ),
        make_donor_headers(donor["id"]),
    )

    gift = validate_success(response, expected_status=201)
    assert_donation(gift)
    assert gift["fee_cents"] == 820
    assert gift["net_cents"] == 9180
    assert gift["charged_amount_cents"] == 10000
    assert gift["matched_amount_cents"] == 0
    assert gift["match_status"] == "UNMATCHED"


def test_an_unrecognised_designation_type_is_rejected(api):
    """PRD §3.4: "`designation_type` is one of `CAMPAIGN`, `TEAM` or `PARTICIPANT`,
    and `designation_id` is resolved according to it — a campaign identifier when
    `CAMPAIGN`, a team identifier when `TEAM`, a fundraiser page identifier when
    `PARTICIPANT`."
    PRD §2.8: "**Request shape** — required fields present, types correct, enum
    members recognized, and declared numeric ranges honored, otherwise
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/donation_invalid_designation_type_enum_rejected
    """
    ctx = setup_published_campaign(api=api)
    donor = create_donor(api=api)

    response = api.create_donation(
        create_donation_payload(
            ctx["campaign_id"], donor["id"], "SPONSOR", ctx["campaign_id"], 10000
        ),
        make_donor_headers(donor["id"]),
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_a_designation_target_in_another_campaign_is_unresolvable(api):
    """PRD §3.4: "The resolved row must belong to the gift's own campaign. When the
    identifier does not resolve to a row of the named type inside that campaign, the
    gift is rejected with `ERR_DESIGNATION_UNRESOLVABLE`."

    Design: Corner/validations/donation_designation_id_of_other_campaign_rejected
    """
    ctx = setup_two_published_campaigns(api=api)
    foreign = create_participant(ctx["campaign_b_id"], api=api, display_name="Bea Bravo")
    donor = create_donor(api=api)

    response = api.create_donation(
        create_donation_payload(
            ctx["campaign_a_id"], donor["id"], "PARTICIPANT", foreign["id"], 10000
        ),
        make_donor_headers(donor["id"]),
    )

    validate_error(
        response, ApiErrorId.ERR_DESIGNATION_UNRESOLVABLE.value, expected_status=422
    )

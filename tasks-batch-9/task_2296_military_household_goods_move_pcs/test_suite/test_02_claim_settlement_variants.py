"""Claim settlement bases, the bounded information loop and the performance cascade."""

import pytest

from test_helpers import (
    ApiErrorId,
    EXAMINER,
    add_claim_item,
    api_client,
    disposition_item,
    get_success_data,
    open_claim,
    provide_claim_info_payload,
    read_capacity_block,
    read_claim,
    read_tsp,
    request_claim_info_payload,
    review_claim,
    set_clock,
    settle_claim,
    setup_delivered_shipment,
    submit_claim,
    validate_error,
)

WEIGH_DATE = "2026-08-17T00:00:00Z"
NOTICE_DATE = "2026-09-01T00:00:00Z"

IDENTICAL_ITEM_SET = [
    {
        "replacement_cost_usd": 4200.00,
        "category": "ELECTRONICS",
        "age_years": 3.0,
        "high_value_inventory_documented": True,
    },
    {
        "replacement_cost_usd": 900.00,
        "category": "CLOTHING",
        "age_years": 5.0,
        "high_value_inventory_documented": False,
    },
]


def _read_item(item_id):
    """Read one claim item as the reviewing examiner."""
    return get_success_data(api_client.get_claim_item(item_id, EXAMINER))


def _add_items(scenario, claim_id, tag):
    rows = []
    for index, spec in enumerate(IDENTICAL_ITEM_SET):
        spec = dict(spec)
        cost = spec.pop("replacement_cost_usd")
        rows.append(
            add_claim_item(
                scenario,
                claim_id,
                cost,
                inventory_item_number=f"INV-{tag}{index + 1}",
                **spec,
            )
        )
    return rows


def _two_claims_settled_on_different_bases():
    """Two claims with the same two items, filed 42 days and 314 days after delivery."""
    scenario = setup_delivered_shipment(weigh_date=WEIGH_DATE)
    set_clock(NOTICE_DATE)

    claim_a = open_claim(scenario, NOTICE_DATE)
    items_a = _add_items(scenario, claim_a["id"], "A")
    claim_b = open_claim(scenario, NOTICE_DATE)
    items_b = _add_items(scenario, claim_b["id"], "B")

    set_clock("2026-10-01T00:00:00Z")
    submit_claim(scenario, claim_a["id"])
    set_clock("2027-06-30T00:00:00Z")
    submit_claim(scenario, claim_b["id"])

    review_claim(claim_a["id"])
    review_claim(claim_b["id"])
    for item in items_a + items_b:
        disposition_item(item["id"], "ALLOWED")

    settled_a = settle_claim(claim_a["id"])
    settled_b = settle_claim(claim_b["id"])
    return scenario, settled_a, settled_b, items_a, items_b


def _claim_in_the_information_loop():
    """A filed claim under review that has already run three information requests."""
    scenario = setup_delivered_shipment(weigh_date=WEIGH_DATE)
    set_clock(NOTICE_DATE)
    claim = open_claim(scenario, NOTICE_DATE, claim_type="LOSS")
    add_claim_item(
        scenario,
        claim["id"],
        4200.00,
        category="ELECTRONICS",
        age_years=3.0,
        high_value_inventory_documented=True,
    )
    submit_claim(scenario, claim["id"])
    review_claim(claim["id"])

    for round_number in range(3):
        requested = api_client.request_claim_info(
            claim["id"],
            request_claim_info_payload(
                info_request_note=f"Provide document {round_number + 1}"
            ),
            EXAMINER,
        )
        assert requested.status_code == 200, requested.text
        provided = api_client.provide_claim_info(
            claim["id"],
            provide_claim_info_payload(response_note=f"Document {round_number + 1} sent"),
            scenario["member_headers"],
        )
        assert provided.status_code == 200, provided.text

    return scenario, claim


def _settled_heavy_claim():
    """A 13,500 dollar documented loss settled against an otherwise clean provider."""
    scenario = setup_delivered_shipment(weigh_date=WEIGH_DATE)
    set_clock("2026-10-01T00:00:00Z")
    claim = open_claim(scenario, "2026-09-05T00:00:00Z", claim_type="LOSS")
    item = add_claim_item(
        scenario,
        claim["id"],
        13500.00,
        category="ELECTRONICS",
        age_years=1.0,
        high_value_inventory_documented=True,
    )
    submit_claim(scenario, claim["id"])
    review_claim(claim["id"])
    disposition_item(item["id"], "ALLOWED", adjudication_note="Total loss")
    settled = settle_claim(claim["id"], settlement_note="Full replacement value paid")
    return scenario, settled


class TestFullReplacementValueVersusDepreciatedValue:
    """The same two items settle for different money depending on the filing date."""

    def test_filing_date_fixes_the_settlement_basis_of_each_claim(self):
        """42 days earns full replacement value; 314 days earns depreciated value.

        "From that count the `settlement_basis` follows: at most 270 days — filing within
        nine months of delivery, boundary inclusive — earns `FULL_REPLACEMENT_VALUE`;
        more than 270 days but at most 730 earns `DEPRECIATED_VALUE`."

        Design: Difficulty/dual_variant_calc/claim_settlement_frv_versus_depreciated_on_identical_item_set
        """
        _, claim_a, claim_b, _, _ = _two_claims_settled_on_different_bases()

        assert claim_a["filing_window_days"] == 42
        assert claim_a["settlement_basis"] == "FULL_REPLACEMENT_VALUE"
        assert claim_b["filing_window_days"] == 314
        assert claim_b["settlement_basis"] == "DEPRECIATED_VALUE"

    def test_full_replacement_value_pays_the_replacement_cost_with_no_age_reduction(self):
        """The electronics item pays 4,200.00 and the clothing item 900.00, totalling 5,100.00.

        "Under `FULL_REPLACEMENT_VALUE`, `item_settlement_usd` is that effective cost
        rounded half up to cents, with no reduction for age."

        Design: Difficulty/dual_variant_calc/claim_settlement_frv_versus_depreciated_on_identical_item_set
        """
        _, claim_a, _, items_a, _ = _two_claims_settled_on_different_bases()

        settlements = [
            _read_item(item["id"])["item_settlement_usd"] for item in items_a
        ]
        assert settlements[0] == pytest.approx(4200.00, abs=0.01)
        assert settlements[1] == pytest.approx(900.00, abs=0.01)
        assert claim_a["settlement_total_usd"] == pytest.approx(5100.00, abs=0.01)

    def test_depreciated_value_applies_the_age_factor_with_a_one_fifth_floor(self):
        """Three-year electronics pay 2,940.00; five-year clothing floors at 180.00.

        "Under `DEPRECIATED_VALUE`, a residual factor is computed as one less the item's
        `depreciation_rate_pct_per_year` multiplied by its `age_years`, with a floor of
        0.20 so that no item ever settles below a fifth of its effective cost, and
        `item_settlement_usd` is the effective cost multiplied by that factor, rounded
        half up to cents."

        Design: Difficulty/dual_variant_calc/claim_settlement_frv_versus_depreciated_on_identical_item_set
        """
        _, _, claim_b, _, items_b = _two_claims_settled_on_different_bases()

        settlements = [
            _read_item(item["id"])["item_settlement_usd"] for item in items_b
        ]
        assert settlements[0] == pytest.approx(2940.00, abs=0.01)
        assert settlements[1] == pytest.approx(180.00, abs=0.01)
        assert claim_b["settlement_total_usd"] == pytest.approx(3120.00, abs=0.01)

    def test_the_earlier_filing_is_worth_one_thousand_nine_hundred_eighty_dollars_more(self):
        """The identical item set settles 1,980.00 higher on the full replacement basis.

        "Identical items therefore settle strictly higher under `FULL_REPLACEMENT_VALUE`
        than under `DEPRECIATED_VALUE` whenever `age_years` is greater than zero."

        Design: Difficulty/dual_variant_calc/claim_settlement_frv_versus_depreciated_on_identical_item_set
        """
        _, claim_a, claim_b, _, _ = _two_claims_settled_on_different_bases()

        difference = claim_a["settlement_total_usd"] - claim_b["settlement_total_usd"]
        assert difference == pytest.approx(1980.00, abs=0.01)


class TestInformationRequestCycleLimit:
    """The request and response loop is bounded at three requests."""

    def test_answering_an_information_request_returns_the_claim_to_review(self):
        """Three completed rounds leave the claim under review with the counter at three.

        "the member answers with a `response_note`, moving it
        `INFO_REQUESTED → UNDER_REVIEW` with no counter change."

        Design: Difficulty/non_linear_state_machine/claim_review_info_request_cycle_terminates_at_third_request
        """
        _, claim = _claim_in_the_information_loop()

        current = read_claim(claim["id"])
        assert current["status"] == "UNDER_REVIEW"
        assert current["info_request_count"] == 3

    def test_a_fourth_information_request_is_refused(self):
        """The loop terminates rather than continuing past its published ceiling.

        "That cycle is bounded at three requests: a fourth attempt, made with
        `info_request_count` already at 3, is refused with
        `ERR_CLAIM_INFO_REQUEST_LIMIT`."

        Design: Difficulty/non_linear_state_machine/claim_review_info_request_cycle_terminates_at_third_request
        """
        _, claim = _claim_in_the_information_loop()

        response = api_client.request_claim_info(
            claim["id"],
            request_claim_info_payload(info_request_note="Fourth request"),
            EXAMINER,
        )
        validate_error(response, ApiErrorId.ERR_CLAIM_INFO_REQUEST_LIMIT.value, 409)

    def test_the_refused_request_changes_nothing_on_the_claim(self):
        """The claim keeps its counter, stays under review and has settled no money.

        "**Settlement** moves the claim `UNDER_REVIEW → SETTLED`, may carry a
        `settlement_note`, requires that no item of the claim is still `PENDING`
        (otherwise `ERR_CLAIM_ITEM_PENDING`), requires the acting `X-User-ID` to differ
        from `reviewed_by_user_id`, and stamps `settled_by_user_id`."

        Design: Difficulty/non_linear_state_machine/claim_review_info_request_cycle_terminates_at_third_request
        """
        _, claim = _claim_in_the_information_loop()
        api_client.request_claim_info(
            claim["id"],
            request_claim_info_payload(info_request_note="Fourth request"),
            EXAMINER,
        )

        current = read_claim(claim["id"])
        assert current["info_request_count"] == 3
        assert current["status"] == "UNDER_REVIEW"
        assert current["settlement_total_usd"] == pytest.approx(0.00, abs=0.01)


class TestSettlementCascadesToCapacity:
    """One heavy settlement runs claim, provider, standing and capacity in one request."""

    def test_settlement_pays_the_documented_replacement_cost_in_full(self):
        """The claim reaches its terminal settled state at 13,500.00.

        "`settlement_total_usd` is the sum of the per-item settlements, rounded half up
        to cents, and then capped at 100,000.00 US dollars per claim."

        Design: Difficulty/transitive_cascade/claim_settlement_cascades_four_links_to_capacity_block_restriction
        """
        _, claim = _settled_heavy_claim()

        assert claim["status"] == "SETTLED"
        assert claim["settlement_basis"] == "FULL_REPLACEMENT_VALUE"
        assert claim["settlement_total_usd"] == pytest.approx(13500.00, abs=0.01)

    def test_the_provider_score_is_recomputed_from_the_settlement_total(self):
        """One claim costs five points and 13,500.00 costs a further twenty-seven.

        "the `MovingCompany` owning the claim's shipment has its `settled_claim_count`
        incremented, its `claim_settlement_total_usd` increased by
        `settlement_total_usd`, and its `performance_score` recomputed: starting from
        100.00, deduct 5.00 points for each settled claim counted against the provider,
        deduct a further point for every 500.00 US dollars of cumulative settlement,
        round half up to two decimals, and floor the result at 0.00."

        Design: Difficulty/transitive_cascade/claim_settlement_cascades_four_links_to_capacity_block_restriction
        """
        scenario, _ = _settled_heavy_claim()

        provider = read_tsp(scenario["tsp"]["id"])
        assert provider["settled_claim_count"] == 1
        assert provider["claim_settlement_total_usd"] == pytest.approx(13500.00, abs=0.01)
        assert provider["performance_score"] == pytest.approx(68.00, abs=0.01)

    def test_the_provider_standing_drops_to_probation(self):
        """A score of 68.00 sits below seventy and at or above fifty.

        "standing is re-derived from the score immediately: below 50.00 the provider
        becomes `SUSPENDED`; at or above 50.00 but below 70.00 it becomes `PROBATION`;
        otherwise it stays `ACTIVE`."

        Design: Difficulty/transitive_cascade/claim_settlement_cascades_four_links_to_capacity_block_restriction
        """
        scenario, _ = _settled_heavy_claim()

        assert read_tsp(scenario["tsp"]["id"])["status"] == "PROBATION"

    def test_the_providers_open_capacity_block_is_restricted(self):
        """The block follows its provider onto probation without resizing its pools.

        "when the provider lands on `PROBATION`, every capacity block of that provider
        whose `status` is `OPEN` moves `OPEN → RESTRICTED`; when the provider lands on
        `SUSPENDED`, every block of that provider whose `status` is `OPEN` or
        `RESTRICTED` moves to `CLOSED`."

        Design: Difficulty/transitive_cascade/claim_settlement_cascades_four_links_to_capacity_block_restriction
        """
        scenario, _ = _settled_heavy_claim()

        block = read_capacity_block(scenario["block"]["id"])
        assert block["status"] == "RESTRICTED"
        assert block["total_capacity_lbs"] == 12000
        assert block["general_pool_lbs"] == 9000
        assert block["short_notice_pool_lbs"] == 3000

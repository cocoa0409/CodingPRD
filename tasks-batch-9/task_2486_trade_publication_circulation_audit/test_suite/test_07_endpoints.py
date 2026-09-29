"""Guarantee settlement and make-good acceptance: the money axis end to end."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_MAKEGOOD_POOL_EXCEEDED,
    ERR_NO_SHORTFALL_TO_SETTLE,
    ERR_NOT_CONTRACT_OWNER,
)
from test_helpers.assertions import assert_pct
from test_helpers.factories import settle_guarantees_payload
from test_helpers.fixtures import (
    accept_make_good,
    add_complete_rule_set,
    certify_statement,
    move_clock,
    offer_make_good,
    open_statement,
    qualify_subscriber,
    read_contract,
    read_statement,
    register_contract,
    register_publication,
    settle_guarantees,
)
from test_helpers.test_users import (
    MANAGER_HEADERS,
    make_advertiser_contact_headers,
)

PERIOD_START = "2026-07-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"
SETTLEMENT_CLOCK = "2026-10-01T00:00:00Z"


def paid_publication(name, copies, paid_amount_cents):
    """A title with the full rule set and one verified PAID recipient of `copies`."""
    publication = register_publication(name=name, industry_code="MANUFACTURING")
    add_complete_rule_set(publication["id"])
    member = qualify_subscriber(
        publication["id"],
        signed_at="2026-07-01T00:00:00Z",
        captured_at="2026-07-15T00:00:00Z",
        subscription_class="PAID",
        copies=copies,
        paid_amount_cents=paid_amount_cents,
    )
    return publication, member["subscriber"]


def filed_statement_over_the_quarter(publication_id, expected_total):
    """Close the quarter, open the statement over it, and certify it into FILED."""
    move_clock(SETTLEMENT_CLOCK)
    statement = open_statement(
        publication_id,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        basis="AS_OF_PERIOD_END",
    )
    assert statement["total_qualified_copies"] == expected_total
    filed = certify_statement(statement["id"])
    assert filed["status"] == "FILED"
    assert filed["declared_total_copies"] == expected_total
    return filed


def test_settle_guarantees_with_no_shortfall_rejected():
    """Over-delivery is not an empty settlement; it is a refusal.

    "And if no `ACTIVE` contract of the publication has a `shortfall_pct` strictly
    greater than its own `shortfall_tolerance_pct`, there is nothing to settle and
    the request is refused with `ERR_NO_SHORTFALL_TO_SETTLE` and HTTP 409 rather
    than succeeding with an empty array."

    Design: Corner/endpoints/settle_guarantees_with_no_shortfall_rejected
    """
    publication, _ = paid_publication("Over Delivery Monthly", 1200, 24000)
    contract = register_contract(
        publication["id"],
        advertiser_name="Modest Guarantee Corp",
        insertion_count=6,
        gross_rate_cents_per_insertion=500000,
        guaranteed_rate_base=1000,
        shortfall_tolerance_pct=2.00,
    )
    assert contract["guarantee_status"] == "ACTIVE"
    # Six insertions at 500,000 cents each is a 3,000,000 cent credit pool.
    assert contract["makegood_credit_pool_cents"] == 3000000

    filed = filed_statement_over_the_quarter(publication["id"], 1200)

    response = api_client.settle_guarantees(
        filed["id"],
        settle_guarantees_payload(settlement_note="attempting to settle an overrun"),
        MANAGER_HEADERS,
    )
    validate_error(response, ERR_NO_SHORTFALL_TO_SETTLE, 409)

    # 1,200 delivered against a 1,000 guarantee is a surplus, so the pool is untouched.
    unspent = read_contract(contract["id"])
    assert unspent["makegood_credit_committed_cents"] == 0
    assert unspent["makegood_credit_available_cents"] == 3000000
    assert unspent["guarantee_status"] == "ACTIVE"

    rows = validate_success(
        api_client.list_make_goods(
            MANAGER_HEADERS, params={"contract_id": contract["id"]}
        ),
        200,
    )
    assert rows == []

    unchanged = read_statement(filed["id"])
    assert unchanged["status"] == "FILED"
    assert unchanged["guarantees_settled_at"] is None


def test_accept_makegood_by_other_advertiser_unauthorized():
    """An advertiser is its contract, so a stranger's credit is unreachable.

    "when an `AdvertiserContact` reads or accepts a make-good obligation, the
    obligation's `contract_id` must equal `X-User-ID`; if it does not, the request
    is rejected with `ERR_NOT_CONTRACT_OWNER` and HTTP 403."

    Design: Corner/endpoints/accept_makegood_by_other_advertiser_unauthorized
    """
    publication, _ = paid_publication("Shortfall Ownership Monthly", 1200, 24000)
    shorted = register_contract(
        publication["id"],
        advertiser_name="Hydraulics International",
        insertion_count=12,
        gross_rate_cents_per_insertion=850000,
        guaranteed_rate_base=1750,
        shortfall_tolerance_pct=2.00,
    )
    satisfied = register_contract(
        publication["id"],
        advertiser_name="Modest Guarantee Corp",
        insertion_count=6,
        gross_rate_cents_per_insertion=500000,
        guaranteed_rate_base=1000,
        shortfall_tolerance_pct=2.00,
    )
    assert shorted["makegood_credit_pool_cents"] == 10200000
    assert satisfied["guarantee_status"] == "ACTIVE"

    filed = filed_statement_over_the_quarter(publication["id"], 1200)

    obligations = settle_guarantees(
        filed["id"], settlement_note="quarterly guarantee settlement"
    )
    # Only the 1,750-copy guarantee was missed, so the batch holds a single row.
    assert len(obligations) == 1
    obligation = obligations[0]
    assert obligation["contract_id"] == shorted["id"]
    assert obligation["statement_id"] == filed["id"]
    assert obligation["shortfall_copies"] == 550
    # 550 of 1,750 is 31.43 percent, whose tier factor is 1.50.
    assert_pct(obligation["shortfall_pct"], 31.43)
    assert_pct(obligation["tier_factor"], 1.50)
    assert obligation["per_insertion_credit_cents"] == 400733
    assert obligation["credit_cents"] == 4808796
    assert obligation["status"] == "PENDING"

    offered = offer_make_good(obligation["id"], offer_note="credit offered")
    assert offered["status"] == "OFFERED"

    response = api_client.accept_make_good(
        obligation["id"],
        {"acceptance_note": "accepting a stranger's credit"},
        make_advertiser_contact_headers(satisfied["id"]),
    )
    validate_error(response, ERR_NOT_CONTRACT_OWNER, 403)
    still_offered = validate_success(
        api_client.get_make_good(obligation["id"], MANAGER_HEADERS), 200
    )
    assert still_offered["status"] == "OFFERED"

    accepted = accept_make_good(
        obligation["id"],
        shorted["id"],
        acceptance_note="accepting our own credit",
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["accepted_at"].startswith("2026-10-01T00:00:00")

    committed = read_contract(shorted["id"])
    assert committed["makegood_credit_committed_cents"] == 4808796
    assert committed["makegood_credit_available_cents"] == 5391204

    untouched = read_contract(satisfied["id"])
    assert untouched["makegood_credit_committed_cents"] == 0
    assert untouched["guarantee_status"] == "ACTIVE"


def test_settle_guarantees_credit_exceeding_pool_rejected():
    """A credit larger than the contract's own pool voids the whole batch.

    "If the computed `credit_cents` for *any* qualifying contract exceeds that
    contract's `makegood_credit_available_cents`, the entire request fails with
    `ERR_MAKEGOOD_POOL_EXCEEDED` and HTTP 422, and **no obligation is persisted
    for any contract in the batch**".

    Design: Corner/endpoints/settle_guarantees_credit_exceeding_pool_rejected
    """
    publication, _ = paid_publication("Catastrophic Shortfall Monthly", 300, 6000)
    contract = register_contract(
        publication["id"],
        advertiser_name="Overreach Media",
        insertion_count=12,
        gross_rate_cents_per_insertion=850000,
        guaranteed_rate_base=1750,
        shortfall_tolerance_pct=2.00,
    )
    assert contract["makegood_credit_pool_cents"] == 10200000
    assert contract["makegood_credit_available_cents"] == 10200000

    filed = filed_statement_over_the_quarter(publication["id"], 300)

    # 1,450 of 1,750 is 82.86 percent, whose tier factor of 1.50 yields a
    # per-insertion credit of 1,056,465 cents and 12,677,580 cents over twelve
    # insertions — more than the 10,200,000 cent pool can bear.
    response = api_client.settle_guarantees(
        filed["id"],
        settle_guarantees_payload(
            settlement_note="catastrophic shortfall settlement"
        ),
        MANAGER_HEADERS,
    )
    validate_error(response, ERR_MAKEGOOD_POOL_EXCEEDED, 422)

    rows = validate_success(
        api_client.list_make_goods(
            MANAGER_HEADERS, params={"contract_id": contract["id"]}
        ),
        200,
    )
    assert rows == []

    intact = read_contract(contract["id"])
    assert intact["makegood_credit_committed_cents"] == 0
    assert intact["makegood_credit_available_cents"] == 10200000
    assert intact["guarantee_status"] == "ACTIVE"

    unsettled = read_statement(filed["id"])
    assert unsettled["status"] == "FILED"
    assert unsettled["guarantees_settled_at"] is None

"""
Optimistic concurrency on the two settlement alternatives: a plan and a service
assignment are each submitted on a citation view that a direct payment has
already moved, and in both cases the version comparison refuses the write
before the terms it would have locked in are computed.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_NOT_RESOURCE_OWNER,
    ERR_STALE_CITATION_VERSION,
)
from test_helpers.assertions import (
    assert_citation_money_identity,
    assert_installment_schedule,
    assert_instant_equals,
    assert_ledger_row,
    ledger_sources,
    sole_row_with_source,
)
from test_helpers.constants import (
    PAYMENT_SOURCE_DIRECT,
    PAYMENT_SOURCE_DOWN_PAYMENT,
    PLAN_STATUS_ACTIVE,
    SERVICE_STATUS_ACTIVE,
    SETTLEMENT_OUTSTANDING,
    SETTLEMENT_PLAN_ACTIVE,
    SETTLEMENT_SERVICE_ACTIVE,
)
from test_helpers.fixtures import OBSERVATION_AT
from test_helpers.test_users import PLANNER_HEADERS, make_rider_headers

FIRST_DUE_AT = "2026-09-04T09:00:00Z"
PARTNER_ORG = "Riverside Food Bank"


def test_a_plan_on_a_stale_citation_view_is_refused_and_the_retry_prices_the_moved_balance(api):
    """
    Opening an installment plan against a citation requires the request to carry
    `expected_citation_version`, a non-optional input field holding the `version`
    value the client last observed on that citation.  If that value does not equal
    the citation's current `version`, the request is rejected with
    `ERR_STALE_CITATION_VERSION` (HTTP 412). ... only the version comparison pins
    the client's reading of `outstanding_balance_cents` and `settlement_status` at
    the instant the plan terms were computed.

    Design: Corner/cross_cutting_layers/payment_plan_creation_rejects_a_stale_expected_citation_version
    """
    chain = fixtures.build_citation_chain(api)
    citation_id = chain["citation"]["id"]
    rider_id = chain["rider"]["id"]
    rider_headers = make_rider_headers(rider_id)

    assert chain["citation"]["version"] == 1
    assert chain["citation"]["total_due_cents"] == 9720
    assert chain["citation"]["outstanding_balance_cents"] == 9720

    fixtures.pay_direct(api, citation_id, 1000, rider_id)
    moved = fixtures.read_citation(api, citation_id)
    assert moved["version"] == 2
    assert moved["amount_paid_cents"] == 1000
    assert moved["outstanding_balance_cents"] == 8720
    assert moved["settlement_status"] == SETTLEMENT_OUTSTANDING

    stale_body = factories.payment_plan_payload(
        citation_id=citation_id,
        installment_count=2,
        down_payment_cents=1000,
        expected_citation_version=1,
    )
    validate_error(
        api.create_payment_plan(stale_body, rider_headers), ERR_STALE_CITATION_VERSION, 412
    )

    # The refusal leaves nothing behind: no plan row and no movement on the citation.
    _, plan_meta = validate_paginated(
        api.list_payment_plans(PLANNER_HEADERS, {"citation_id": citation_id})
    )
    assert plan_meta["total_count"] == 0
    unmoved = fixtures.read_citation(api, citation_id)
    assert unmoved["version"] == 2
    assert unmoved["settlement_status"] == SETTLEMENT_OUTSTANDING

    plan = validate_success(
        api.create_payment_plan(
            factories.payment_plan_payload(
                citation_id=citation_id,
                installment_count=2,
                down_payment_cents=1000,
                expected_citation_version=2,
            ),
            rider_headers,
        ),
        201,
    )

    # The schedule is priced off the post-payment balance: financing the stale
    # 9720 view would have carried 8720 and paid 4360 twice instead.
    assert plan["status"] == PLAN_STATUS_ACTIVE
    assert plan["financed_cents"] == 7720
    assert plan["base_installment_cents"] == 3860
    assert plan["final_installment_cents"] == 3860
    assert plan["remaining_balance_cents"] == 7720
    assert plan["installments_paid_count"] == 0
    assert plan["missed_installment_count"] == 0
    assert_installment_schedule(plan)
    assert_instant_equals(plan["first_due_at"], FIRST_DUE_AT, "plan.first_due_at")

    settled = fixtures.read_citation(api, citation_id)
    assert settled["version"] == 3
    assert settled["settlement_status"] == SETTLEMENT_PLAN_ACTIVE
    assert settled["amount_paid_cents"] == 2000
    assert settled["outstanding_balance_cents"] == 7720
    assert_citation_money_identity(settled)

    rows = fixtures.citation_ledger(api, citation_id)
    assert sorted(ledger_sources(rows)) == sorted(
        [PAYMENT_SOURCE_DIRECT, PAYMENT_SOURCE_DOWN_PAYMENT]
    )
    assert_ledger_row(
        sole_row_with_source(rows, PAYMENT_SOURCE_DIRECT),
        PAYMENT_SOURCE_DIRECT,
        1000,
        applied_at=OBSERVATION_AT,
        label="direct row",
    )
    assert_ledger_row(
        sole_row_with_source(rows, PAYMENT_SOURCE_DOWN_PAYMENT),
        PAYMENT_SOURCE_DOWN_PAYMENT,
        1000,
        plan_id=plan["id"],
        applied_at=OBSERVATION_AT,
        label="down payment row",
    )


def test_a_stale_service_assignment_is_refused_on_version_even_when_the_wrong_rider_sends_it(api):
    """
    Opening a community-service alternative against a citation is guarded
    identically: the request requires `expected_citation_version` carrying the
    client's last observed citation `version`, and a value that does not equal the
    citation's current `version` is rejected with `ERR_STALE_CITATION_VERSION`
    (HTTP 412).  Here the exposure is `required_hours`, which is derived from
    `outstanding_balance_cents` at creation time — a stale view would lock in an
    hour count the ledger no longer supports.  Version pinning is evaluated next
    ... The three ownership and separation checks follow in order.

    Design: Corner/cross_cutting_layers/service_assignment_rejects_a_stale_version_before_checking_ownership
    """
    chain = fixtures.build_citation_chain(api)
    citation_id = chain["citation"]["id"]
    owner_headers = make_rider_headers(chain["rider"]["id"])
    stranger = fixtures.register_rider(
        api,
        rider_ref="R-200",
        display_name="Rider Two",
        demographic_band="BAND_B",
        residence_geo_tract="T-002",
    )
    stranger_headers = make_rider_headers(stranger["id"])

    fixtures.pay_direct(api, citation_id, 1500, chain["rider"]["id"])
    moved = fixtures.read_citation(api, citation_id)
    assert moved["version"] == 2
    assert moved["outstanding_balance_cents"] == 8220
    assert moved["settlement_status"] == SETTLEMENT_OUTSTANDING

    stale_body = factories.service_assignment_payload(
        citation_id=citation_id,
        partner_org_name=PARTNER_ORG,
        expected_citation_version=1,
    )
    validate_error(
        api.create_service_assignment(stale_body, owner_headers),
        ERR_STALE_CITATION_VERSION,
        412,
    )

    # The same stale body from a rider who owns nothing still answers on the
    # version rule, which is evaluated ahead of the ownership rule.
    by_stranger = api.create_service_assignment(stale_body, stranger_headers)
    validate_error(by_stranger, ERR_STALE_CITATION_VERSION, 412)
    assert by_stranger.json()["data"]["error_id"] != ERR_NOT_RESOURCE_OWNER

    _, service_meta = validate_paginated(
        api.list_service_assignments(PLANNER_HEADERS, {"citation_id": citation_id})
    )
    assert service_meta["total_count"] == 0
    unmoved = fixtures.read_citation(api, citation_id)
    assert unmoved["version"] == 2
    assert unmoved["settlement_status"] == SETTLEMENT_OUTSTANDING

    assignment = validate_success(
        api.create_service_assignment(
            factories.service_assignment_payload(
                citation_id=citation_id,
                partner_org_name=PARTNER_ORG,
                expected_citation_version=2,
            ),
            owner_headers,
        ),
        201,
    )

    # ceil(8220 / 1500) is 6 hours, not the 7 that ceil(9720 / 1500) would have
    # locked in from the stale view.
    assert assignment["required_hours"] == 6
    assert assignment["hours_completed"] == 0
    assert assignment["credited_cents"] == 0
    assert assignment["status"] == SERVICE_STATUS_ACTIVE
    assert assignment["partner_org_name"] == PARTNER_ORG

    settled = fixtures.read_citation(api, citation_id)
    assert settled["version"] == 3
    assert settled["settlement_status"] == SETTLEMENT_SERVICE_ACTIVE
    assert settled["outstanding_balance_cents"] == 8220
    assert settled["service_credit_cents"] == 0
    assert_citation_money_identity(settled)

"""Credit-limit boundary at approval and the two optimistic-concurrency guards."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_order_line,
    approve_order,
    create_advertiser,
    create_avail_unit,
    create_avail_week,
    create_order,
    create_program,
    get_avail_unit,
    get_order,
    get_spot,
    list_line_spots,
    place_spot_payload,
    setup_second_advertiser_order,
    submit_order,
    validate_error,
    validate_success,
    approve_order_payload,
)

SALESREP = TEST_USERS["salesrep_headers"]
TRAFFIC = TEST_USERS["trafficmanager_headers"]


class TestCreditLimitBoundary:
    def test_exposure_exactly_at_limit_passes_one_cent_over_fails(self, api):
        """PRD §3.4: "The credit rule of §3.1 is then applied: the advertiser's outstanding exposure — the summed `gross_budget_cents` of its `APPROVED` and `COMPLETED` orders — plus this order's `gross_budget_cents` must not exceed the advertiser's `credit_limit_cents`, or approval is rejected with `ERR_CREDIT_LIMIT`; a total exactly equal to the limit passes."

        Design: Difficulty/boundary_precision_check/credit_limit_equality_boundary_on_approve
        """
        advertiser = create_advertiser(name="A13", credit_limit_cents=50000)
        program = create_program(
            title="Sat Prime 13", daypart_code="PRIME", airs_weekday=6, rating_estimate=5.0
        )
        order = create_order(advertiser["id"])
        add_order_line(order["id"], program["id"], gross_rate_cents=50000)
        submit_order(order["id"])
        order_b = create_order(advertiser["id"])
        add_order_line(order_b["id"], program["id"], gross_rate_cents=1)
        submit_order(order_b["id"])

        approved = approve_order(order["id"])
        assert approved["status"] == "APPROVED", "0 + 50000 <= 50000: equality accepted"

        resp = api.approve_order(
            order_b["id"],
            approve_order_payload(get_order(order_b["id"])["version"]),
            TRAFFIC,
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT)
        assert get_order(order_b["id"])["status"] == "SUBMITTED", (
            "50000 + 1 > 50000: rejected by exactly one cent"
        )

    def test_exposure_accumulates_across_approved_orders(self, api):
        """PRD §3.1: "An advertiser's outstanding exposure is the sum of `gross_budget_cents` across its orders currently in `APPROVED` or `COMPLETED` status; §3.4 describes how approval adds the candidate order's budget to that exposure and rejects the approval with `ERR_CREDIT_LIMIT` when the total would exceed `credit_limit_cents`."

        Design: Difficulty/boundary_precision_check/credit_limit_equality_boundary_on_approve
        """
        advertiser = create_advertiser(name="A13b", credit_limit_cents=100000)
        program = create_program(
            title="Sat Prime 13b", daypart_code="PRIME", airs_weekday=6, rating_estimate=5.0
        )
        orders = []
        for rate in (50000, 50000, 1):
            order = create_order(advertiser["id"])
            add_order_line(order["id"], program["id"], gross_rate_cents=rate)
            submit_order(order["id"])
            orders.append(order)

        assert approve_order(orders[0]["id"])["status"] == "APPROVED"
        assert approve_order(orders[1]["id"])["status"] == "APPROVED", (
            "50000 + 50000 = 100000 <= 100000: running equality accepted"
        )
        resp = api.approve_order(
            orders[2]["id"],
            approve_order_payload(get_order(orders[2]["id"])["version"]),
            TRAFFIC,
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT)
        assert get_order(orders[2]["id"])["status"] == "SUBMITTED"


class TestOptimisticConcurrency:
    def test_stale_order_version_rejected_on_approve(self, api):
        """PRD §2.8: "Approving an order requires the request to carry `expected_order_version`, holding the order `version` the client last observed. If the order's current `version` has advanced since that observation — because another writer added or cancelled a line, or the order was otherwise mutated in the interim — the approval is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), so the client never approves a budget and line set it has not actually seen."
        PRD §2.9: "Within an order, adding or cancelling a line recomputes the order's budget and advances the order's `version`, and every order action — submission, approval, rejection, revision, cancellation, completion — advances the order's `version` as well."

        Design: Corner/cross_cutting_layers/occ_stale_order_version_on_approve
        """
        advertiser = create_advertiser(name="OCC")
        program = create_program(
            title="OCC P", daypart_code="PRIME", airs_weekday=6, rating_estimate=5.0
        )
        order = create_order(advertiser["id"])
        stale_version = order["version"]  # observed at creation
        add_order_line(order["id"], program["id"], gross_rate_cents=5000)
        submit_order(order["id"])
        fresh_version = get_order(order["id"])["version"]
        assert fresh_version > stale_version

        resp = api.approve_order(
            order["id"], approve_order_payload(stale_version), TRAFFIC
        )
        validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION)

        approved = validate_success(
            api.approve_order(order["id"], approve_order_payload(fresh_version), TRAFFIC)
        )
        assert approved["status"] == "APPROVED"

    def test_stale_avail_version_rejected_on_place(self, api):
        """PRD §2.8: "Placing a spot requires the request to carry `expected_avail_unit_version`, holding the target avail unit's `version` the client last observed. Because every placement, preemption, or cancellation against a unit advances that unit's `version`, a mismatch means the client's headroom computation is stale; the placement is rejected with `ERR_STALE_AVAIL_VERSION` (HTTP 412) and must be recomputed against a fresh read before retrying."
        PRD §2.10: "Because the stale-version checks run last, a stale version surfaces only on an otherwise-valid request."

        Design: Corner/cross_cutting_layers/occ_stale_avail_version_on_place
        """
        program = create_program(
            title="OCC2 P", daypart_code="PRIME", airs_weekday=6, rating_estimate=5.0
        )
        week = create_avail_week("2026-08-03")
        unit = create_avail_unit(
            week["id"], program["id"], "2026-08-08", total_seconds=120
        )
        unit_version_at_read = unit["version"]
        # Two different categories so commercial separation cannot fail: the
        # request is otherwise valid and the stale-version check decides.
        _, _, _, spots_a = setup_second_advertiser_order(
            program["id"], category="AUTOMOTIVE"
        )
        _, _, _, spots_b = setup_second_advertiser_order(
            program["id"], category="RETAIL"
        )

        placed = validate_success(
            api.place_spot(
                spots_a[0]["id"],
                place_spot_payload(unit["id"], unit_version_at_read),
                TRAFFIC,
            )
        )
        assert placed["status"] == "SCHEDULED", "first place succeeds: version matches"

        resp = api.place_spot(
            spots_b[0]["id"],
            place_spot_payload(unit["id"], unit_version_at_read),
            TRAFFIC,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_AVAIL_VERSION)
        assert get_spot(spots_b[0]["id"])["status"] == "PENDING_PLACEMENT"
        assert get_avail_unit(unit["id"])["booked_commercial_seconds"] == 30

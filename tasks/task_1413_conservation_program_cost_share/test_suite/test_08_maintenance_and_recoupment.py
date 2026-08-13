"""Maintenance violations and recoupment demands."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equal,
    assert_pool_invariants,
    get_item,
    get_pool,
    list_demands,
    list_obligations_for_item,
    make_applicant_headers,
    make_planner_headers,
    make_qa_headers,
    set_clock,
    setup_certified_item,
    setup_disbursed_request,
    TEST_USERS,
    api_client,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_maintenance_violation_creates_recoupment_demand(api):
    """PRD §3.8: "when the item's `paid_amount_cents` is greater than zero, a
    recoupment demand is created for exactly that amount, linked through
    `maintenance_obligation_id` and due thirty days hence, and the item's
    payment dimension falls from `PAID` to `RECOUPMENT_PENDING`." PRD §3.8: "A
    paid demand restores the pool, reducing `paid_cents` by the recovered
    amount; moves the linked item from `RECOUPMENT_PENDING` to `RECOUPED`, the
    payment dimension's terminal state".

    Design: Corner/calculations/maintenance_violation_recoupment_amount
    """
    ctx = setup_disbursed_request(certified_quantity=1000, documented_cost_cents=350000)
    # computed = min(1000 x 300, 350000) = 300000, disbursed in full.
    assert ctx["request"]["status"] == "DISBURSED"

    set_clock("2026-11-10T00:00:00Z")
    obligation = list_obligations_for_item(ctx["item"]["id"])[0]

    reported = validate_success(
        api.report_violation(obligation["id"], make_planner_headers("planner-2")), 200
    )
    assert reported["status"] == "VIOLATION_REVIEW"

    confirmed = validate_success(
        api.confirm_violation(obligation["id"], make_qa_headers("qa-1")), 200
    )
    assert confirmed["status"] == "VIOLATION_CONFIRMED"

    demands = list_demands(maintenance_obligation_id=obligation["id"])
    assert len(demands) == 1
    demand = demands[0]
    assert demand["amount_cents"] == 300000, "demand carries item.paid_amount_cents"
    # Confirm clock 2026-11-10 + 30 days.
    assert_instant_equal(demand["due_date"], "2026-12-10T00:00:00Z", "demand due_date")

    item = get_item(ctx["item"]["id"])
    assert item["payment_status"] == "RECOUPMENT_PENDING"

    paid = validate_success(
        api.pay_recoupment_demand(
            demand["id"], {"amount_cents": 300000},
            make_applicant_headers(ctx["applicant"]["id"]),
        ),
        200,
    )
    assert paid["status"] == "PAID"

    item = get_item(ctx["item"]["id"])
    assert item["payment_status"] == "RECOUPED"

    pool = get_pool(ctx["pool"]["id"])
    assert pool["paid_cents"] == 0
    assert pool["available_cents"] == 1000000
    assert_pool_invariants(pool)


def test_violation_confirmer_is_reporter_rejected(api):
    """PRD §3.8: "A `ConservationPlanner` who finds a certified practice
    unmaintained reports a violation against an `ACTIVE` obligation
    (`ERR_OBLIGATION_NOT_ACTIVE`, HTTP 409), moving it to `VIOLATION_REVIEW`
    and stamping `reported_by_user_id`." and "Confirmation moves it to its
    terminal `VIOLATION_CONFIRMED` state, enforces the segregation boundary of
    §2.11 — the confirmer must differ from the reporter,
    `ERR_SEGREGATION_OF_DUTIES`". PRD §3.8: "Dismissal returns the obligation
    to `ACTIVE`, and the cycle may repeat."

    Design: Corner/rbac/violation_confirmer_is_reporter_rejected
    """
    ctx = setup_certified_item(certified_quantity=1000)
    obligation = list_obligations_for_item(ctx["item"]["id"])[0]

    reported = validate_success(
        api.report_violation(obligation["id"], make_planner_headers("planner-2")), 200
    )
    assert reported["status"] == "VIOLATION_REVIEW"

    # The confirming QA officer is the same person who reported (planner-2).
    resp = api.confirm_violation(obligation["id"], make_qa_headers("planner-2"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    dismissed = validate_success(
        api.dismiss_violation(obligation["id"], make_qa_headers("qa-1")), 200
    )
    assert dismissed["status"] == "ACTIVE", "dismissal completes the review cycle"

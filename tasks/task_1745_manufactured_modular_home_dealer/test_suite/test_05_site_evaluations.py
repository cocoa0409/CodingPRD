"""Site evaluation workflows: findings, bubbles, supersession, capacity, OCC (PRD §2.7, §2.8, §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_evaluation,
    confirm_order,
    create_site_evaluation_payload,
    get_success_data,
    make_site_evaluator_headers,
    new_order_scenario,
    record_findings,
    reject_evaluation,
    schedule_evaluation,
    validate_error,
    validate_paginated,
    validate_success,
)

CONSULTANT = TEST_USERS["consultant_headers"]
INSTALLER = TEST_USERS["installer_headers"]
LENDER = TEST_USERS["lender_headers"]


def test_eval_approve_bubbles_order_to_site_approved(api, consultant_headers):
    """PRD §3.4: "Approval is permitted only when `findings_result` is `PASS` or
    `CONDITIONAL` — approving a `FAIL` evaluation is rejected with
    `ERR_INVALID_STATE` — and moves the evaluation to `APPROVED`; when that
    evaluation is the order's latest non-`SUPERSEDED` one, the order bubbles up
    from `PENDING_SITE_EVAL` to `SITE_APPROVED`."

    Design: Corner/state_machines/eval_approve_bubbles_order_to_site_approved
    """
    scn = new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=4_200_000)
    confirm_order(scn, 212_100)
    schedule_evaluation(scn)
    record_findings(scn, findings_result="CONDITIONAL", foundation_type="SLAB", permit_number="P-400", install_estimate_cents=180_000)

    evaluation = approve_evaluation(scn)
    assert evaluation["status"] == "APPROVED", "CONDITIONAL findings are approvable"
    order = get_success_data(api.get_sales_order(scn["order"]["id"], consultant_headers))
    assert order["deal_status"] == "SITE_APPROVED", f"bubble-up side effect, got {order['deal_status']}"


def test_eval_reject_returns_order_to_draft(api, consultant_headers):
    """PRD §3.4: "Rejection moves the evaluation to `REJECTED` and, when it is
    the order's latest non-`SUPERSEDED` one, drops the order back to `DRAFT` from
    either `PENDING_SITE_EVAL` or `SITE_APPROVED` — the reconfiguration loop that
    lets the sales desk re-spec the deal and evaluate again."

    Design: Corner/state_machines/eval_reject_returns_order_to_draft
    """
    scn = new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=4_200_000)
    confirm_order(scn, 212_100)
    evaluation = schedule_evaluation(scn)
    validate_success(
        api.record_findings(
            evaluation["id"],
            {
                "foundation_type": "SLAB",
                "utilities_verified": False,
                "findings_result": "FAIL",
                "install_estimate_cents": 0,
            },
            make_site_evaluator_headers("eval-1"),
        )
    )

    evaluation = reject_evaluation(scn)
    assert evaluation["status"] == "REJECTED"

    order = get_success_data(api.get_sales_order(scn["order"]["id"], consultant_headers))
    assert order["deal_status"] == "DRAFT", f"reconfiguration loop returns the order to DRAFT, got {order['deal_status']}"
    assert order["payment_status"] == "DEPOSIT_PAID", "payment dimension is untouched by the loop"

    reconfirmed = confirm_order(scn, 212_100)
    assert reconfirmed["deal_status"] == "PENDING_SITE_EVAL", "re-confirm after the loop succeeds"


def test_second_evaluation_supersedes_first(api, consultant_headers):
    """PRD §3.4: "Creating a new evaluation for an order supersedes the order's
    prior evaluations still in `SCHEDULED` or `FINDINGS_RECORDED`, pushing them
    to `SUPERSEDED`, and increments the order's `version`."

    Design: Corner/state_machines/second_evaluation_supersedes_first
    """
    scn = new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=4_200_000)
    confirm_order(scn, 212_100)
    ev1 = schedule_evaluation(scn)

    ev2 = schedule_evaluation(scn, scheduled_date="2026-08-07T09:00:00Z", evaluator_id="eval-2")
    assert ev2["status"] == "SCHEDULED"

    ev1_view = get_success_data(api.get_site_evaluation(ev1["id"], consultant_headers))
    assert ev1_view["status"] == "SUPERSEDED", f"prior evaluation superseded, got {ev1_view['status']}"

    rows, meta = validate_paginated(api.list_site_evaluations(scn["order"]["id"], consultant_headers))
    assert {row["id"] for row in rows} == {ev1["id"], ev2["id"]}, "history is preserved on the order"


def test_eval_scheduled_in_past_rejected(api, consultant_headers):
    """PRD §2.8: "scheduled dates must not precede the current clock date, else
    `ERR_SCHEDULE_IN_PAST` (HTTP 422)."

    Design: Corner/validations/eval_scheduled_in_past_rejected
    """
    scn = new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=4_200_000)
    confirm_order(scn, 212_100)
    version = scn["order"]["version"]
    resp = api.create_site_evaluation(
        scn["order"]["id"],
        create_site_evaluation_payload(version, scheduled_date="2026-07-01T09:00:00Z"),
        consultant_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_IN_PAST)


def test_evaluator_daily_cap_allows_three(api, consultant_headers):
    """PRD §3.4: "One evaluator may hold at most three open evaluations (status
    `SCHEDULED` or `FINDINGS_RECORDED`) on the same calendar date; scheduling a
    fourth fails with `ERR_EVALUATOR_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/evaluator_daily_headcount_cap
    """
    scenarios = [
        new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=4_200_000)
        for _ in range(3)
    ]
    for scn in scenarios:
        confirm_order(scn, 212_100)
    created = [
        schedule_evaluation(scn, scheduled_date=f"2026-08-05T{hour}:00:00Z")
        for scn, hour in zip(scenarios, ["09", "10", "11"])
    ]
    assert all(ev["status"] == "SCHEDULED" for ev in created), "the first three evaluations on the date fit the cap"


def test_evaluator_daily_cap_rejects_fourth(api, consultant_headers):
    """PRD §3.4: "One evaluator may hold at most three open evaluations (status
    `SCHEDULED` or `FINDINGS_RECORDED`) on the same calendar date; scheduling a
    fourth fails with `ERR_EVALUATOR_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/evaluator_daily_headcount_cap
    """
    scenarios = [
        new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=4_200_000)
        for _ in range(4)
    ]
    for scn in scenarios:
        confirm_order(scn, 212_100)
    for scn, hour in zip(scenarios[:3], ["09", "10", "11"]):
        schedule_evaluation(scn, scheduled_date=f"2026-08-05T{hour}:00:00Z")

    scn_d = scenarios[3]
    version = get_success_data(api.get_sales_order(scn_d["order"]["id"], consultant_headers))["version"]
    resp = api.create_site_evaluation(
        scn_d["order"]["id"],
        create_site_evaluation_payload(version, scheduled_date="2026-08-05T13:00:00Z"),
        consultant_headers,
    )
    validate_error(resp, ApiErrorId.ERR_EVALUATOR_CAPACITY_EXCEEDED)

    rows, _ = validate_paginated(api.list_site_evaluations(scn_d["order"]["id"], consultant_headers))
    assert rows == [], "a capacity-rejected scheduling creates no evaluation"

    # The cap is per calendar date: a different date accepts the fourth booking.
    ev_next_day = schedule_evaluation(scn_d, scheduled_date="2026-08-06T09:00:00Z")
    assert ev_next_day["status"] == "SCHEDULED"


def test_occ_stale_evaluation_create_rejected(api, consultant_headers):
    """PRD §2.7: "Each requires a non-optional request field,
    `expected_sales_order_version`, carrying the `version` of the `SalesOrder`
    the client last observed. If that value does not match the order's current
    `version` — for example because another writer advanced the order since the
    client read it — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_evaluation_create_rejected
    """
    scn = new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=4_200_000)
    confirmed = confirm_order(scn, 212_100)
    stale_version = confirmed["version"]

    ev1 = schedule_evaluation(scn)
    assert ev1["status"] == "SCHEDULED"

    resp = api.create_site_evaluation(
        scn["order"]["id"],
        create_site_evaluation_payload(stale_version, scheduled_date="2026-08-06T09:00:00Z"),
        consultant_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    fresh_version = get_success_data(api.get_sales_order(scn["order"]["id"], consultant_headers))["version"]
    ev2 = validate_success(
        api.create_site_evaluation(
            scn["order"]["id"],
            create_site_evaluation_payload(fresh_version, scheduled_date="2026-08-06T09:00:00Z"),
            consultant_headers,
        ),
        expected_status=201,
    )
    assert ev2["status"] == "SCHEDULED", "retry with the fresh version succeeds"
    ev1_view = get_success_data(api.get_site_evaluation(ev1["id"], consultant_headers))
    assert ev1_view["status"] == "SUPERSEDED"


def test_lender_cannot_record_findings(api):
    """PRD §2.1: "If the role is declared but not authorized for the target
    endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: POST /api/site-evaluations/{id}/record-findings — "Assigned evaluator
    records findings (SCHEDULED → FINDINGS_RECORDED) | SiteEvaluator".

    Design: Corner/rbac/lender_cannot_record_findings
    """
    scn = new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=4_200_000)
    confirm_order(scn, 212_100)
    evaluation = schedule_evaluation(scn)

    resp = api.record_findings(
        evaluation["id"],
        {
            "foundation_type": "SLAB",
            "utilities_verified": True,
            "permit_number": "P-500",
            "findings_result": "PASS",
            "install_estimate_cents": 180_000,
        },
        LENDER,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    view = get_success_data(api.get_site_evaluation(evaluation["id"], CONSULTANT))
    assert view["status"] == "SCHEDULED", "a role-rejected call leaves the evaluation untouched"


def test_evaluator_cannot_record_others_evaluation(api):
    """PRD §3.4: "The assigned evaluator — and only that evaluator, by
    `X-User-ID` matching `evaluator_id`, else `ERR_UNAUTHORIZED` — records
    findings while the order is `PENDING_SITE_EVAL` (else `ERR_INVALID_STATE`)".

    Design: Corner/rbac/evaluator_cannot_record_others_evaluation
    """
    scn = new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=4_200_000)
    confirm_order(scn, 212_100)
    evaluation = schedule_evaluation(scn, evaluator_id="eval-1")

    resp = api.record_findings(
        evaluation["id"],
        {
            "foundation_type": "SLAB",
            "utilities_verified": True,
            "permit_number": "P-502",
            "findings_result": "PASS",
            "install_estimate_cents": 180_000,
        },
        make_site_evaluator_headers("eval-2"),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    view = get_success_data(api.get_site_evaluation(evaluation["id"], CONSULTANT))
    assert view["status"] == "SCHEDULED"
    assert view.get("evaluated_by") is None, "evaluated_by is stamped only on a successful recording"

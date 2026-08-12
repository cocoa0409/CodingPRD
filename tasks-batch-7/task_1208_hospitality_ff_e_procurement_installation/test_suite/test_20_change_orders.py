"""Queue B (breadth) — owner change orders: fiscal rejection arms, segregation
of duties by X-User-ID, and optimistic concurrency on the project version.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId,
    setup_change_order_scenario, apply_change_order_now,
    current_project_version, get_budget_line, get_project,
    make_owner_rep_headers, TEST_USERS,
)

PA = TEST_USERS["purchasing_agent_headers"]
OWNER_1 = make_owner_rep_headers("owner-1")
OWNER_9 = make_owner_rep_headers("owner-9")
OWNER_10 = make_owner_rep_headers("owner-10")


def test_change_order_unfunded_and_below_obligations(api):
    """PRD §3.9: "Fifth, the funding check — evaluated last in the validation
    pipeline, as all fiscal checks are — requires `unallocated_contingency_cents`
    plus `NEG` to be at least `POS` plus `fee_cents`, else
    `ERR_CHANGE_ORDER_UNFUNDED` (402)."
    PRD §3.9: "Independently, every adjusted budget line must keep its
    `budgeted_cents` at or above its current `committed_cents` plus `actual_cents`
    after the delta is applied, else `ERR_BUDGET_BELOW_OBLIGATIONS` (402)."
    CO-A draws 50000c + 2500c fee against 5000c of contingency; CO-B's -50000c
    would drop the 100000c line below its 80000c committed obligations. Failed
    approvals mutate nothing.

    Design: Corner/errors/change_order_unfunded_and_below_obligations
    """
    scenario = setup_change_order_scenario(
        total_budget_cents=500000,
        unallocated_contingency_cents=5000,
        budgeted_cents=100000,
        committed_line=(2, 40000),
        deltas=(("CO-A unfunded", 50000), ("CO-B below obligations", -50000)),
    )
    co_a, co_b = scenario["change_orders"]
    version = scenario["project_version"]

    res = api_client.apply_change_order(
        co_a["id"], {"expected_project_version": version}, OWNER_1
    )
    validate_error(res, ApiErrorId.ERR_CHANGE_ORDER_UNFUNDED,
                   expected_status=402)

    res = api_client.apply_change_order(
        co_b["id"], {"expected_project_version": version}, OWNER_1
    )
    validate_error(res, ApiErrorId.ERR_BUDGET_BELOW_OBLIGATIONS,
                   expected_status=402)

    co_a_after = validate_success(api_client.get_change_order(co_a["id"], PA))
    co_b_after = validate_success(api_client.get_change_order(co_b["id"], PA))
    assert co_a_after["status"] == "PROPOSED"
    assert co_b_after["status"] == "PROPOSED"

    budget_line = get_budget_line(scenario["budget_line"]["id"])
    assert budget_line["budgeted_cents"] == 100000
    project = get_project(scenario["project"]["id"])
    assert project["unallocated_contingency_cents"] == 5000
    assert project["sunk_fees_cents"] == 0
    assert project["version"] == version, (
        "failed approvals must not advance the project version"
    )


def test_sod_self_approval_blocked(api):
    """PRD §2.1: "The single place an operator identity is persisted is the
    change-order workflow: when a change order is proposed, the server records the
    request's `X-User-ID` as the order's `proposer_user_id`, and segregation of
    duties later forbids that same user id from applying or rejecting the order —
    a self-decision attempt is rejected with `ERR_CHANGE_ORDER_SELF_APPROVAL`
    (HTTP 403)."
    PRD §3.9: "Third, the rate is 5 percent when utilization is at most 0.80, 8
    percent when utilization is above 0.80 and at most 0.95, and 12 percent above
    0.95. Fourth, `fee_cents` is the rate multiplied by `POS`, rounded half-up to
    whole cents."
    The proposing OwnerRep (owner-9) cannot apply; a different OwnerRep
    (owner-10) applies with a 5 percent fee of 500c on the +10000c draw.

    Design: Corner/roles/sod_self_approval_blocked
    """
    scenario = setup_change_order_scenario(
        total_budget_cents=5_000_000,
        unallocated_contingency_cents=100000,
        budgeted_cents=1_000_000,
        deltas=(("Owner CO", 10000),),
        proposer_headers=OWNER_9,
    )
    change_order = scenario["change_orders"][0]
    version = scenario["project_version"]

    res = api_client.apply_change_order(
        change_order["id"], {"expected_project_version": version}, OWNER_9
    )
    validate_error(res, ApiErrorId.ERR_CHANGE_ORDER_SELF_APPROVAL,
                   expected_status=403)

    applied = apply_change_order_now(change_order["id"], version, OWNER_10)
    assert applied["status"] == "APPLIED"
    assert applied["fee_cents"] == 500, (
        "utilization 10000/5000000 = 0.002 is in the 5 percent tier"
    )

    budget_line = get_budget_line(scenario["budget_line"]["id"])
    assert budget_line["budgeted_cents"] == 1010000


def test_occ_stale_project_version_on_second_apply(api):
    """PRD §2.6: "First, applying a change order requires the request body to
    carry `expected_project_version`, a non-optional field holding the project
    `version` the approver last observed. Since that read, a receiving-event post,
    a damage-claim resolution, or another applied change order may have advanced
    the project version by recomputing committed and actual totals and posture, so
    the funding check must run against a current view. If
    `expected_project_version` does not equal the project's current `version`, the
    apply is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."
    PRD §3.9: "The project's `version` and the order's `version` each bump."
    After CO-A applies, CO-B's pre-A version is stale (412); re-reading and
    retrying succeeds.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_project_version_on_second_apply
    """
    scenario = setup_change_order_scenario(
        total_budget_cents=5_000_000,
        unallocated_contingency_cents=100000,
        budgeted_cents=1_000_000,
        deltas=(("CO-A", 10000), ("CO-B", 10000)),
    )
    co_a, co_b = scenario["change_orders"]
    stale_version = scenario["project_version"]

    applied_a = apply_change_order_now(co_a["id"], stale_version, OWNER_1)
    assert applied_a["status"] == "APPLIED"

    res = api_client.apply_change_order(
        co_b["id"], {"expected_project_version": stale_version}, OWNER_1
    )
    validate_error(res, ApiErrorId.ERR_STALE_PROJECT_VERSION,
                   expected_status=412)

    co_b_after = validate_success(api_client.get_change_order(co_b["id"], PA))
    assert co_b_after["status"] == "PROPOSED"

    fresh_version = current_project_version(scenario["project"]["id"])
    assert fresh_version == stale_version + 1, (
        "the first apply bumps the project version exactly once"
    )

    applied_b = apply_change_order_now(co_b["id"], fresh_version, OWNER_1)
    assert applied_b["status"] == "APPLIED"

    budget_line = get_budget_line(scenario["budget_line"]["id"])
    assert budget_line["budgeted_cents"] == 1020000

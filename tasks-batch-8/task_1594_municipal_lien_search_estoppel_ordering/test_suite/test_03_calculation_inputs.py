"""Calculation input-set and pinned-constant claims: which children feed the
order totals, rush surcharge application, and statute pinning."""
from test_helpers import (
    FINDINGS_EMPTY,
    UTILITY_ONLY_DEPARTMENTS,
    complete_task,
    create_statute,
    get_estoppel,
    get_order,
    list_order_estoppels,
    make_research_analyst_headers,
    place_estoppel,
    record_findings,
    set_clock,
    setup_config_a,
    setup_identified_order,
    create_search_order,
    identify_order,
    list_order_tasks,
    validate_success,
)

ANALYST = make_research_analyst_headers("analyst_1")


def test_in_progress_task_contributes_nothing_to_totals(api):
    """PRD 3.4: "The order's payoff total is defined precisely:
    `total_payoff_cents` is the sum of `unpaid_balance_cents` over the order's
    `COMPLETED` research tasks plus the sum of `payoff_amount_cents` over its
    `RECEIVED` estoppel orders — tasks in any other state and estoppels in any
    other state contribute zero. Likewise `total_fees_cents` is the sum of
    `fee_charged_cents` over `COMPLETED` tasks plus the sum of
    `lifetime_fees_cents` over estoppels in `RECEIVED` or `EXPIRED`; once
    charged, fees are never refunded, even by cancellation."

    Design: Corner/calculations/in_progress_task_balance_excluded_from_payoff
    """
    ctx = setup_identified_order(
        "P-G3", departments=UTILITY_ONLY_DEPARTMENTS, with_association=False
    )
    task = ctx["tasks"][0]
    record_findings(
        task, [{"finding_kind": "UNPAID_UTILITY", "amount_cents": 300000}]
    )

    mid = get_order(ctx["order"]["id"])
    assert mid["total_payoff_cents"] == 0, (
        "An IN_PROGRESS task's balance must not feed total_payoff_cents"
    )
    assert mid["total_fees_cents"] == 0

    complete_task(task["id"])
    end = get_order(ctx["order"]["id"])
    assert end["total_payoff_cents"] == 300000
    assert end["total_fees_cents"] == 5000


def test_rush_order_task_fee_includes_surcharge(api):
    """PRD 3.4: "Completing a task — allowed only once findings have been
    recorded — moves it from `IN_PROGRESS` to `COMPLETED`, records the caller in
    `completed_by_user_id`, and fixes `fee_charged_cents` as the snapshotted
    `fee_base_cents` plus, when the owning order is `RUSH`, the snapshotted
    `fee_rush_surcharge_cents`."

    Design: Corner/calculations/rush_task_fee_includes_surcharge
    """
    ctx = setup_config_a(departments=UTILITY_ONLY_DEPARTMENTS, with_association=False)
    order = create_search_order(
        "P-H4",
        order_class="RUSH",
        service_date="2026-08-10",
        jurisdiction_id=ctx["jurisdiction"]["id"],
    )
    identify_order(order["id"], ctx["jurisdiction"]["id"])
    task = list_order_tasks(order["id"])[0]
    record_findings(task, FINDINGS_EMPTY)
    completed = complete_task(task["id"])
    assert completed["fee_charged_cents"] == 7500, (
        f"RUSH task fee must be 5000 base + 2500 surcharge, got "
        f"{completed['fee_charged_cents']}"
    )
    assert get_order(order["id"])["total_fees_cents"] == 7500


def test_placement_uses_pinned_statute_not_current_window(api):
    """PRD 2.9: "a search order pins whichever window covers the clock date at
    the moment its jurisdiction is identified, keeping that statute for the life
    of the order regardless of later legislative changes."
    PRD 3.5: "Placement moves the estoppel from `DRAFT` to `ORDERED`, stamps
    `ordered_at` with the clock, and computes `statutory_due_at` as the ordered
    date plus the statute's `estoppel_response_days` calendar days, fixed at
    23:59:59.000Z on the resulting date."

    Design: Corner/calculations/statute_pinning_uses_creation_window_not_current
    """
    set_clock()
    from test_helpers import create_jurisdiction, create_department, create_association

    jurisdiction = create_jurisdiction()
    window_one = create_statute(
        jurisdiction["id"],
        effective_from="2026-01-01",
        effective_to="2026-09-01",
        estoppel_response_days=10,
        estoppel_fee_cap_cents=12000,
        estoppel_validity_days=30,
    )
    create_statute(
        jurisdiction["id"],
        effective_from="2026-09-01",
        effective_to=None,
        estoppel_response_days=12,
        estoppel_fee_cap_cents=5000,
        estoppel_validity_days=45,
    )
    create_department(
        jurisdiction["id"],
        dept_type="UTILITY",
        name="Water & Sewer",
        research_fee_cents=5000,
        rush_surcharge_cents=2500,
        supports_rush=True,
    )
    association = create_association(jurisdiction["id"])
    order = create_search_order(
        "P-J5", closing_date="2026-10-20", association_id=association["id"]
    )
    identify_order(order["id"], jurisdiction["id"])
    pinned = get_order(order["id"])
    assert pinned["statute_id"] == window_one["id"], (
        "The statute in force at identify time must be pinned for the order"
    )
    estoppel = list_order_estoppels(order["id"])[0]

    # Advance past window one's end; window two (cap 5000, 12 days) now rules,
    # but the order keeps window one (cap 12000, 10 days).
    set_clock("2026-09-05T09:00:00Z")
    response = api.place_estoppel(
        estoppel["id"], {"fee_quoted_cents": 8000}, ANALYST
    )
    placed = validate_success(response, 200)
    assert placed["status"] == "ORDERED"
    assert placed["statutory_due_at"] == "2026-09-15T23:59:59.000Z", (
        f"Pinned 10-day window from 2026-09-05 must give 2026-09-15 end of day, "
        f"got {placed['statutory_due_at']}"
    )

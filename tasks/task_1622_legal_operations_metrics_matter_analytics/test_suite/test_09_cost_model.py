"""Insource-vs-outsource cost model: provisional vs final variants."""

from test_helpers import (
    api_client,
    assert_cost_model,
    close_matter,
    create_accrual,
    create_firm,
    create_paid_invoice,
    setup_matter_graph,
    validate_success,
    ANALYST,
)


def test_cost_model_provisional_vs_final_diverges(api):
    """PRD §3.8: "While the matter is `ACTIVE` or `ON_HOLD`, the read is
    provisional and uses `actual_spend_cents` plus `accrual_outstanding_cents` —
    a forward-looking view that counts fees still accruing. Once the matter is
    `CLOSED`, `REOPENED`, or `ARCHIVED`, the read is final and uses
    `actual_spend_cents` alone, ignoring accruals entirely."

    The accrual and the paid invoice are routed through different firms so the
    approval-time accrual match (same matter + period + firm, PRD §3.5) does not
    consume the accrual — keeping it OUTSTANDING for the provisional read.

    Design: Difficulty/dual_variant_calc/insource_outsource_provisional_vs_final_diverges
    """
    graph = setup_matter_graph(
        assignment_hours=100,
        firm_overrides={"blended_hourly_rate_cents": 25000},
        counsel_overrides={"loaded_hourly_cost_cents": 15000},
        matter_overrides={"budget_cents": 100000000},
    )
    fp_id = graph["fiscal_period"]["id"]
    m_id = graph["matter"]["id"]
    # Second firm carries the invoice so the accrual (primary firm) never matches.
    firm2 = create_firm(tier="TIER_2")

    accrual = create_accrual(m_id, fp_id, graph["firm"]["id"], 4000000)
    create_paid_invoice(m_id, firm2["id"], fp_id, 3000000)

    prov = validate_success(api_client.get_matter_cost_model(m_id, ANALYST), 200)
    assert_cost_model(prov)
    assert prov["insource_cost_cents"] == 100 * 15000
    # provisional: actual_spend 3000000 + accrual_outstanding 4000000
    assert prov["outsource_cost_cents"] == 7000000
    assert prov["modeled_outsource_cost_cents"] == 100 * 25000

    validate_success(api_client.release_accrual(accrual["id"], ANALYST), 200)
    close_matter(m_id)

    final = validate_success(api_client.get_matter_cost_model(m_id, ANALYST), 200)
    # final: actual_spend alone, accruals ignored
    assert final["outsource_cost_cents"] == 3000000
    assert final["insource_cost_cents"] == 100 * 15000
    assert final["outsource_cost_cents"] != prov["outsource_cost_cents"]


def test_cost_model_provisional_in_active_and_on_hold_final_when_closed(api):
    """PRD §3.8: "While the matter is `ACTIVE` or `ON_HOLD`, the read is
    provisional and uses `actual_spend_cents` plus `accrual_outstanding_cents` —
    a forward-looking view that counts fees still accruing. Once the matter is
    `CLOSED`, `REOPENED`, or `ARCHIVED`, the read is final and uses
    `actual_spend_cents` alone, ignoring accruals entirely."

    Design: Difficulty/dual_variant_calc/insource_outsource_provisional_vs_final_diverges
    """
    graph = setup_matter_graph()  # default 5h assignment
    fp_id = graph["fiscal_period"]["id"]
    m_id = graph["matter"]["id"]

    accrual = create_accrual(m_id, fp_id, graph["firm"]["id"], 400000)

    active_read = validate_success(api_client.get_matter_cost_model(m_id, ANALYST), 200)
    assert active_read["outsource_cost_cents"] == 400000  # 0 actual + 400000 accrual

    validate_success(api_client.hold_matter(m_id, ANALYST), 200)
    hold_read = validate_success(api_client.get_matter_cost_model(m_id, ANALYST), 200)
    # ON_HOLD is still the provisional variant
    assert hold_read["outsource_cost_cents"] == 400000

    validate_success(api_client.release_accrual(accrual["id"], ANALYST), 200)
    validate_success(api_client.resume_matter(m_id, ANALYST), 200)
    close_matter(m_id)

    final_read = validate_success(api_client.get_matter_cost_model(m_id, ANALYST), 200)
    assert final_read["outsource_cost_cents"] == 0


def test_cost_model_returns_full_inline_object(api):
    """PRD §3.8: "`insource_cost_cents` sums, across those assignments, each
    assignment's `allocated_hours` multiplied by its counsel's
    `loaded_hourly_cost_cents`."
    PRD §3.8: "`savings_cents` is the modeled outsource figure minus the insource
    figure: a positive value decides `INSOURCE_CHEAPER`, a negative value decides
    `OUTSOURCE_CHEAPER`, and exactly zero decides `BREAK_EVEN`."
    PRD §3.8: "Alongside the three cost figures, `savings_cents`, and the
    `decision`, the response carries the `matter_id`."

    Design: Corner/endpoints/computed_read_cost_model_returns_inline_object
    """
    graph = setup_matter_graph(assignment_hours=10)
    fp_id = graph["fiscal_period"]["id"]
    m_id = graph["matter"]["id"]
    create_paid_invoice(m_id, graph["firm"]["id"], fp_id, 50000)

    data = validate_success(api_client.get_matter_cost_model(m_id, ANALYST), 200)
    assert_cost_model(data)
    assert data["matter_id"] == m_id
    assert data["insource_cost_cents"] == 10 * 15000
    # provisional variant with no accruals outstanding: actual spend only
    assert data["outsource_cost_cents"] == 50000
    assert data["modeled_outsource_cost_cents"] == 10 * 25000
    assert data["savings_cents"] == 250000 - 150000
    assert data["decision"] == "INSOURCE_CHEAPER"

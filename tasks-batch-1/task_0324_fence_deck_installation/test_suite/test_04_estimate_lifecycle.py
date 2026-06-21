"""Estimate acceptance, the draw waterfall, invalid transitions, and immediate
consistency.

Translates Corner/state_machines (price-already-priced, accept-unpriced),
Corner/calculations/draw_schedule_amounts_sum_to_contract_total, and
Corner/consistency_model/immediate_contract_total_visible_in_accept_response.
"""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_customer, create_project,
    create_line_item_payload,
    setup_priced_estimate, make_customer_headers,
    find_draw_by_milestone,
)

PM = TEST_USERS["project_manager_headers"]
EST = TEST_USERS["estimator_headers"]


def test_price_already_priced_estimate_returns_invalid_state(api):
    """PRD §3.2: "A successful pricing moves the estimate from `DRAFT` to `PRICED`."
    PRD §2.9: "the system evaluate state-machine legality, yielding `ERR_INVALID_STATE` (HTTP 409) when the target resource is not in a state from which the requested transition is defined". Re-pricing a PRICED estimate has
    no defined transition.

    Design: Corner/state_machines/price_already_priced_estimate_returns_invalid_state
    """
    cust = create_customer()
    proj = create_project(cust["id"], job_type="FENCE")
    est = get_success_data(api.create_estimate(proj["id"], {}, EST))
    get_success_data(api.create_line_item(
        create_line_item_payload(est["id"], quantity_units=100), EST))
    get_success_data(api.price_estimate(proj["id"], est["id"], EST))
    resp = api.price_estimate(proj["id"], est["id"], EST)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_accept_unpriced_estimate_returns_estimate_not_priced(api):
    """PRD §3.3: "the estimate must be in `PRICED` status or the request is rejected with `ERR_ESTIMATE_NOT_PRICED`."

    Design: Corner/state_machines/accept_unpriced_estimate_returns_estimate_not_priced
    """
    cust = create_customer()
    proj = create_project(cust["id"], job_type="FENCE")
    est = get_success_data(api.create_estimate(proj["id"], {}, EST))
    get_success_data(api.create_line_item(
        create_line_item_payload(est["id"], quantity_units=100), EST))
    resp = api.accept_estimate(proj["id"], est["id"], make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_ESTIMATE_NOT_PRICED.value)


def test_draw_schedule_amounts_sum_to_contract_total(api):
    """PRD §3.3: "four `Draw` rows are created in `SCHEDULED` status, one per `milestone`, in the fixed order `DEPOSIT`, `DELIVERY`, `FRAMING`, `FINAL`. Each draw carries a `pct` of the contract — 0.20 for `DEPOSIT`, 0.30 for `DELIVERY`, 0.30 for `FRAMING`, and 0.20 for `FINAL`."
    PRD §3.3: "the `FINAL` draw's amount is set to the contract total minus that running total, rounded to 2 places, so that it absorbs both the deposit clamp and any rounding remainder and the four amounts sum exactly to the contract total." Contract total 21605.04 -> DEPOSIT 4321.01, DELIVERY
    6481.51, FRAMING 6481.51, FINAL 4321.01.

    Design: Corner/calculations/draw_schedule_amounts_sum_to_contract_total
    """
    ctx = setup_priced_estimate()
    pid = ctx["project"]["id"]
    get_success_data(api.accept_estimate(pid, ctx["estimate"]["id"], ctx["customer_headers"]))
    draws = get_success_data(api.list_draws(pid, PM))
    deposit = find_draw_by_milestone(draws, "DEPOSIT")
    delivery = find_draw_by_milestone(draws, "DELIVERY")
    framing = find_draw_by_milestone(draws, "FRAMING")
    final = find_draw_by_milestone(draws, "FINAL")
    assert deposit["amount"] == 4321.01
    assert delivery["amount"] == 6481.51
    assert framing["amount"] == 6481.51
    assert final["amount"] == 4321.01
    total = round(deposit["amount"] + delivery["amount"] + framing["amount"] + final["amount"], 2)
    assert total == 21605.04


def test_immediate_contract_total_visible_in_accept_response(api):
    """PRD §3.3: "Acceptance moves the estimate from `PRICED` to `ACCEPTED`, drives any previously `ACCEPTED` estimate on the project to `SUPERSEDED`, sets the project's `active_estimate_id` to this estimate and its `contract_total` to the estimate's `contract_total`, and bubbles the project from `DRAFT` up to `ESTIMATED`."
    The immediate GET after accept reflects contract_total 21605.04, status
    ESTIMATED, and four SCHEDULED draws.

    Design: Corner/consistency_model/immediate_contract_total_visible_in_accept_response
    """
    ctx = setup_priced_estimate()
    pid = ctx["project"]["id"]
    get_success_data(api.accept_estimate(pid, ctx["estimate"]["id"], ctx["customer_headers"]))
    proj = get_success_data(api.get_project(pid, PM))
    assert proj["contract_total"] == 21605.04
    assert proj["status"] == "ESTIMATED"
    draws = get_success_data(api.list_draws(pid, PM))
    assert len(draws) == 4
    assert all(d["status"] == "SCHEDULED" for d in draws)

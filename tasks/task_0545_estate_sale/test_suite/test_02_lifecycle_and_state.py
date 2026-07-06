"""Project/lot/sale-event lifecycles: negotiation cycle, reprice loop, cross-entity gates,
and invalid/terminal state rejections.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, MANAGER, APPRAISER, CASHIER,
    new_client, new_project, contracted_project, new_lot, research_and_price,
    patch_project, listed_fixed_lot, crew_booked_event, make_client_headers,
)


# ---- Difficulty: non_linear_state_machine / project_contract_negotiation_cycle -------------
def _project_at_proposed(api):
    client = new_client(api)
    project = new_project(client["id"], api, estimated_total_value_cents=300000)
    pid = project["id"]
    patch_project(pid, {"status": "ASSESSED"}, MANAGER, api)
    patch_project(pid, {"status": "PROPOSED"}, MANAGER, api)
    return client, pid


def test_project_negotiation_cycle_returns_to_proposed(api):
    """PRD §3.1: "From `PROPOSED`, the `Client` may reject the current terms and counter,
    driving `PROPOSED → COUNTERED` — but only on their own project, where the caller's
    `X-User-ID` equals the project's `client_id`. The `SaleManager` then re-proposes, driving
    `COUNTERED → PROPOSED` and possibly adjusting `minimum_commission_cents`, and the two sides
    can cycle through `PROPOSED ↔ COUNTERED` as many times as needed."

    Design: Difficulty/non_linear_state_machine/project_contract_negotiation_cycle
    """
    client, pid = _project_at_proposed(api)
    patch_project(pid, {"status": "COUNTERED"}, make_client_headers(client["id"]), api)
    resp = api.patch_project(pid, {"status": "PROPOSED", "minimum_commission_cents": 60000}, MANAGER)
    data = validate_success(resp, 200)
    assert data["status"] == "PROPOSED"


def test_project_reproposal_adjusts_minimum_commission(api):
    """PRD §3.1: "The `SaleManager` then re-proposes, driving `COUNTERED → PROPOSED` and
    possibly adjusting `minimum_commission_cents`, and the two sides can cycle through
    `PROPOSED ↔ COUNTERED` as many times as needed."

    Design: Difficulty/non_linear_state_machine/project_contract_negotiation_cycle
    """
    client, pid = _project_at_proposed(api)
    patch_project(pid, {"status": "COUNTERED"}, make_client_headers(client["id"]), api)
    resp = api.patch_project(pid, {"status": "PROPOSED", "minimum_commission_cents": 60000}, MANAGER)
    data = validate_success(resp, 200)
    assert data["minimum_commission_cents"] == 60000


# ---- Difficulty: non_linear_state_machine / lot_reprice_revert_cycle -----------------------
def _listed_lot_at_5000(api):
    ctx = listed_fixed_lot(api, list_price_cents=5000, reserve_price_cents=100, open_now=False)
    return ctx["lot_id"]


def test_lot_reprice_revert_cycle_reaches_priced(api):
    """PRD §3.2: "From any of `PRICED`, `STAGED`, `TAGGED`, or `LISTED`, an appraiser may
    re-open a lot back to `RESEARCHED` to re-research and re-price it, provided the lot has not
    yet sold."

    Design: Difficulty/non_linear_state_machine/lot_reprice_revert_cycle
    """
    lot_id = _listed_lot_at_5000(api)
    validate_success(
        api.patch_lot(lot_id, {"status": "RESEARCHED", "research_notes": "underpriced, redo"}, APPRAISER)
    )
    resp = api.patch_lot(lot_id, {"status": "PRICED", "list_price_cents": 6000}, APPRAISER)
    data = validate_success(resp, 200)
    assert data["status"] == "PRICED"


def test_lot_reprice_revert_cycle_updates_list_price(api):
    """PRD §3.2: "Along the way a lot's `list_price_cents`, `reserve_price_cents`,
    `min_increment_cents`, `research_notes`, and `bid_mode` can be adjusted."

    Design: Difficulty/non_linear_state_machine/lot_reprice_revert_cycle
    """
    lot_id = _listed_lot_at_5000(api)
    validate_success(api.patch_lot(lot_id, {"status": "RESEARCHED"}, APPRAISER))
    resp = api.patch_lot(lot_id, {"status": "PRICED", "list_price_cents": 6000}, APPRAISER)
    data = validate_success(resp, 200)
    assert data["list_price_cents"] == 6000


# ---- Difficulty: cross_entity_state_dependency / lot_listed_requires_project_in_sale -------
def _tagged_lot_on_contracted_project(api):
    _, project = contracted_project(api)
    pid = project["id"]
    lot = new_lot(pid, api, title="Desk", list_price_cents=5000, reserve_price_cents=100)
    research_and_price(lot["id"], api, list_price_cents=5000)
    validate_success(api.patch_lot(lot["id"], {"status": "STAGED"}, APPRAISER))
    validate_success(api.patch_lot(lot["id"], {"status": "TAGGED"}, APPRAISER))
    return lot["id"]


def test_listing_before_sale_phase_rejected(api):
    """PRD §3.2: "Listing, `TAGGED → LISTED`, is gated on the project having reached the sale
    phase: it is allowed only when the project's `status` is `SALE_SETUP` or `SALE_LIVE`, and a
    listing attempt against a project not yet in the sale is rejected with
    `ERR_PROJECT_NOT_IN_SALE`."

    Design: Difficulty/cross_entity_state_dependency/lot_listed_requires_project_in_sale
    """
    lot_id = _tagged_lot_on_contracted_project(api)
    resp = api.patch_lot(lot_id, {"status": "LISTED"}, APPRAISER)
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_IN_SALE.value)


def test_listing_before_sale_phase_leaves_lot_tagged(api):
    """PRD §3.2: "Listing, `TAGGED → LISTED`, is gated on the project having reached the sale
    phase: it is allowed only when the project's `status` is `SALE_SETUP` or `SALE_LIVE`, and a
    listing attempt against a project not yet in the sale is rejected with
    `ERR_PROJECT_NOT_IN_SALE`."

    Design: Difficulty/cross_entity_state_dependency/lot_listed_requires_project_in_sale
    """
    lot_id = _tagged_lot_on_contracted_project(api)
    api.patch_lot(lot_id, {"status": "LISTED"}, APPRAISER)
    data = validate_success(api.get_lot(lot_id, APPRAISER))
    assert data["status"] == "TAGGED"


# ---- Difficulty: cross_entity_state_dependency / transaction_requires_sale_event_open ------
def test_transaction_on_unopened_sale_event_rejected(api):
    """PRD §3.4: "The transaction is only accepted while its sale event is `OPEN`; otherwise it
    is rejected with `ERR_SALE_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/transaction_requires_sale_event_open
    """
    ctx = listed_fixed_lot(api, list_price_cents=5000, reserve_price_cents=100, open_now=False)
    resp = api.create_transaction(
        {"sale_event_id": ctx["sale_event_id"], "lot_id": ctx["lot_id"], "payment_method": "CASH"},
        CASHIER,
    )
    validate_error(resp, ApiErrorId.ERR_SALE_NOT_OPEN.value)


def test_transaction_on_unopened_sale_event_leaves_lot_listed(api):
    """PRD §3.4: "The transaction is only accepted while its sale event is `OPEN`; otherwise it
    is rejected with `ERR_SALE_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/transaction_requires_sale_event_open
    """
    ctx = listed_fixed_lot(api, list_price_cents=5000, reserve_price_cents=100, open_now=False)
    api.create_transaction(
        {"sale_event_id": ctx["sale_event_id"], "lot_id": ctx["lot_id"], "payment_method": "CASH"},
        CASHIER,
    )
    data = validate_success(api.get_lot(ctx["lot_id"], APPRAISER))
    assert data["status"] == "LISTED"


# ---- Corner: state_machines ----------------------------------------------------------------
def test_lot_new_to_listed_skip_rejected(api):
    """PRD §3.2: describes the ordered ladder — research (`NEW → RESEARCHED`), pricing
    (`RESEARCHED → PRICED`), staging (`PRICED → STAGED`), tagging (`STAGED → TAGGED`), and
    "Listing, `TAGGED → LISTED`".
    PRD §2.11: "State — the target resource is in a valid state for the requested transition,
    else the matching state error (409): `ERR_INVALID_STATE`".

    Design: Corner/state_machines/lot_invalid_transition_new_to_listed_rejected
    """
    _, project = contracted_project(api)
    lot = new_lot(project["id"], api, title="Toolbox", list_price_cents=3000, reserve_price_cents=100)
    resp = api.patch_lot(lot["id"], {"status": "LISTED"}, APPRAISER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    data = validate_success(api.get_lot(lot["id"], APPRAISER))
    assert data["status"] == "NEW"


def test_cancelled_project_blocks_further_patch(api):
    """PRD §3.1: "None of these transitions are permitted once the project is terminal; a
    mutation attempted on a `SETTLED` or `CANCELLED` project is rejected with
    `ERR_PROJECT_TERMINAL`."

    Design: Corner/state_machines/project_terminal_blocks_further_patch
    """
    client = new_client(api)
    project = new_project(client["id"], api, estimated_total_value_cents=1000)
    validate_success(api.cancel_project(project["id"], MANAGER))
    resp = api.patch_project(project["id"], {"status": "ASSESSED"}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_PROJECT_TERMINAL.value)
    data = validate_success(api.get_project(project["id"], MANAGER))
    assert data["status"] == "CANCELLED"


def test_close_scheduled_sale_event_rejected(api):
    """PRD §3.6: "When a sale day ends, the `SaleManager` closes the event, driving
    `OPEN → CLOSED`."
    PRD §2.11: "State — the target resource is in a valid state for the requested transition,
    else the matching state error (409): `ERR_INVALID_STATE`".

    Design: Corner/state_machines/sale_event_close_from_scheduled_rejected
    """
    ctx = crew_booked_event(api)
    resp = api.close_sale_event(ctx["sale_event_id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    data = validate_success(api.get_sale_event(ctx["sale_event_id"], MANAGER))
    assert data["status"] == "SCHEDULED"

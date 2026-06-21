"""SREC sweep sales: settlement rounding, empty pool, OCC, reverse-reachability."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    make_homeowner_headers, make_broker_headers,
    register_broker, register_homeowner,
    setup_operational_project, mint_and_list_srecs, mint_srecs,
    current_project_version,
    create_project_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _broker_headers(broker):
    return make_broker_headers(broker["id"])


# --- Difficulty: combinatorial_formula / srec_sale_fee_sum_then_round ---

def test_srec_sale_fee_sum_then_round_net_proceeds(api):
    """PRD 3.9: "The broker fee is computed on the gross total — not per
    certificate — as the gross_proceeds_cents multiplied by the broker's
    broker_fee_pct, rounded half up; the net_proceeds_cents is the gross proceeds
    minus that fee. This sum-then-round ordering is pinned: the fee is taken once
    against the total."

    Design: Difficulty/combinatorial_formula/srec_sale_fee_sum_then_round
    """
    ctx = setup_operational_project(model="LOAN")
    broker = register_broker(broker_fee_pct=0.035, operating_states=["CA"])
    mint_and_list_srecs(ctx["project"]["id"], ctx["homeowner"]["id"], 5, vintage_year=2026)
    pv = current_project_version(ctx)
    resp = api.create_srec_sale(
        {"project_id": ctx["project"]["id"], "broker_id": broker["id"],
         "vintage_year": 2026, "price_cents_per_srec": 32099,
         "expected_project_version": pv},
        _broker_headers(broker),
    )
    data = validate_success(resp, 201)
    assert data["srec_count"] == 5
    # gross 5*32099 == 160495; fee round_half_up(160495*0.035)==5617; net 154878
    assert data["gross_proceeds_cents"] == 160495
    assert data["net_proceeds_cents"] == 154878


def test_srec_sale_gross_proceeds_count_times_price(api):
    """PRD 3.9: "The srec_count is the number swept. The gross_proceeds_cents is
    that count multiplied by the price_cents_per_srec."

    Design: Difficulty/combinatorial_formula/srec_sale_fee_sum_then_round
    """
    ctx = setup_operational_project(model="LOAN")
    broker = register_broker(broker_fee_pct=0.035, operating_states=["CA"])
    mint_and_list_srecs(ctx["project"]["id"], ctx["homeowner"]["id"], 5, vintage_year=2026)
    pv = current_project_version(ctx)
    resp = api.create_srec_sale(
        {"project_id": ctx["project"]["id"], "broker_id": broker["id"],
         "vintage_year": 2026, "price_cents_per_srec": 32099,
         "expected_project_version": pv},
        _broker_headers(broker),
    )
    data = validate_success(resp, 201)
    assert data["gross_proceeds_cents"] == 160495


# --- Difficulty: boundary_precision_check / srec_sale_empty_listed_pool_rejected ---

def test_srec_sale_empty_listed_pool_rejected(api):
    """PRD 3.9: "The sweep gathers every certificate of the named project and
    vintage whose status is LISTED; if no such certificate exists the sale is
    rejected with ERR_NO_LISTED_SRECS (HTTP 422)."

    Design: Difficulty/boundary_precision_check/srec_sale_empty_listed_pool_rejected
    """
    ctx = setup_operational_project(model="LOAN")
    broker = register_broker(broker_fee_pct=0.04, operating_states=["CA"])
    mint_srecs(ctx["project"]["id"], 2, vintage_year=2026)  # MINTED, never LISTED
    pv = current_project_version(ctx)
    resp = api.create_srec_sale(
        {"project_id": ctx["project"]["id"], "broker_id": broker["id"],
         "vintage_year": 2026, "price_cents_per_srec": 30000,
         "expected_project_version": pv},
        _broker_headers(broker),
    )
    validate_error(resp, ApiErrorId.ERR_NO_LISTED_SRECS, 422)


def test_srec_sale_empty_pool_returns_422(api):
    """PRD 3.9: "if no such certificate exists the sale is rejected with
    ERR_NO_LISTED_SRECS (HTTP 422)."

    Design: Difficulty/boundary_precision_check/srec_sale_empty_listed_pool_rejected
    """
    ctx = setup_operational_project(model="LOAN")
    broker = register_broker(broker_fee_pct=0.04, operating_states=["CA"])
    mint_srecs(ctx["project"]["id"], 2, vintage_year=2026)
    pv = current_project_version(ctx)
    resp = api.create_srec_sale(
        {"project_id": ctx["project"]["id"], "broker_id": broker["id"],
         "vintage_year": 2026, "price_cents_per_srec": 30000,
         "expected_project_version": pv},
        _broker_headers(broker),
    )
    assert resp.status_code == 422


# --- Corner: calculations / srec_sale_correct_net_proceeds_clean_fee ---

def test_srec_sale_clean_fee_net_proceeds(api):
    """PRD 3.9: "the net_proceeds_cents is the gross proceeds minus that fee."

    Design: Corner/calculations/srec_sale_correct_net_proceeds_clean_fee
    """
    ctx = setup_operational_project(model="LOAN")
    broker = register_broker(broker_fee_pct=0.04, operating_states=["CA"])
    mint_and_list_srecs(ctx["project"]["id"], ctx["homeowner"]["id"], 7, vintage_year=2026)
    pv = current_project_version(ctx)
    resp = api.create_srec_sale(
        {"project_id": ctx["project"]["id"], "broker_id": broker["id"],
         "vintage_year": 2026, "price_cents_per_srec": 32000,
         "expected_project_version": pv},
        _broker_headers(broker),
    )
    data = validate_success(resp, 201)
    assert data["srec_count"] == 7
    assert data["gross_proceeds_cents"] == 224000
    assert data["net_proceeds_cents"] == 215040


# --- Corner: validations / broker_market_mismatch ---

def test_broker_market_mismatch_on_sale(api):
    """PRD 3.9: "The broker must trade the homeowner's market — the homeowner's
    state_code must appear in the broker's operating_states, else
    ERR_BROKER_MARKET_MISMATCH (HTTP 422)."

    Design: Corner/validations/broker_market_mismatch_on_sale
    """
    ctx = setup_operational_project(model="LOAN", state_code="CA")
    broker = register_broker(broker_fee_pct=0.04, operating_states=["TX"], firm_name="TxBroker")
    mint_and_list_srecs(ctx["project"]["id"], ctx["homeowner"]["id"], 1, vintage_year=2026)
    pv = current_project_version(ctx)
    resp = api.create_srec_sale(
        {"project_id": ctx["project"]["id"], "broker_id": broker["id"],
         "vintage_year": 2026, "price_cents_per_srec": 30000,
         "expected_project_version": pv},
        _broker_headers(broker),
    )
    validate_error(resp, ApiErrorId.ERR_BROKER_MARKET_MISMATCH, 422)


# --- Corner: cross_cutting / occ stale project version ---

def test_occ_stale_project_version_on_srec_sale(api):
    """PRD 2.8: "in both a mismatch with the project's current version is rejected
    with ERR_STALE_PROJECT_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_project_version_on_srec_sale
    """
    ctx = setup_operational_project(model="LOAN")
    broker = register_broker(broker_fee_pct=0.04, operating_states=["CA"])
    mint_and_list_srecs(ctx["project"]["id"], ctx["homeowner"]["id"], 2, vintage_year=2026)
    pv = current_project_version(ctx)
    resp = api.create_srec_sale(
        {"project_id": ctx["project"]["id"], "broker_id": broker["id"],
         "vintage_year": 2026, "price_cents_per_srec": 30000,
         "expected_project_version": pv - 1},  # stale
        _broker_headers(broker),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION, 412)


# --- Corner: endpoints / reverse-reachability ---

def test_srecs_reverse_reachable_by_project_id(api):
    """PRD 2.5: "certificates by project_id, srec_sale_id, or status"
    PRD 3.9: "Minting increments the project's lifetime_srec_count — the running
    count of certificates ever minted for that project — and the project's
    version."

    Design: Corner/endpoints/srecs_reverse_reachable_by_project_id
    """
    ctx = setup_operational_project(model="LOAN")
    mint_srecs(ctx["project"]["id"], 2, vintage_year=2026)
    resp = api.list_srecs(ctx["ho_headers"], params={"project_id": ctx["project"]["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    proj = get_success_data(api.get_project(ctx["project"]["id"], ctx["ho_headers"]))
    assert proj["lifetime_srec_count"] == 2


def test_list_projects_filtered_by_homeowner_id(api):
    """PRD 2.5: "projects may be filtered by homeowner_id, installer_id, or
    financing_plan_id"
    PRD 2.3: "the meta block of a list response carries the four pagination fields
    limit, offset, total_count, and has_more, where total_count reflects the full
    count of matching resources before the page window is applied and has_more
    indicates whether further pages remain."

    Design: Corner/endpoints/list_projects_filtered_by_homeowner_id
    """
    homeowner = register_homeowner(state_code="CA")
    ho_headers = make_homeowner_headers(homeowner["id"])
    get_success_data(api.create_project(
        create_project_payload(homeowner_id=homeowner["id"], roof_area_sqft=700), ho_headers))
    get_success_data(api.create_project(
        create_project_payload(homeowner_id=homeowner["id"], roof_area_sqft=800), ho_headers))
    resp = api.list_projects(ho_headers, params={"homeowner_id": homeowner["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False

"""Composite setup helpers — multi-step pipelines used across tests.

Every helper builds preconditions from scratch using only PRD-declared
endpoints, and uses get_success_data() so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: Grower is entity-backed by GrowerAccount — every
ownership-gated Grower call uses make_grower_headers(grower["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _api
from .constants import TEST_DEFAULTS as TD
from . import factories as F
from .test_users import TEST_USERS, make_grower_headers

AGRON = TEST_USERS["agronomist_headers"]
PLANT = TEST_USERS["plant_operator_headers"]
DISPATCH = TEST_USERS["logistics_dispatcher_headers"]
CREDIT = TEST_USERS["credit_manager_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
ADMIN = TEST_USERS["branch_admin_headers"]


def grower_headers(grower) -> dict:
    """Ownership-correct Grower headers for the given GrowerAccount dict/id."""
    gid = grower["id"] if isinstance(grower, dict) else grower
    return make_grower_headers(gid)


# ---------------------------------------------------------------------------
# Tier 1: basic entities
# ---------------------------------------------------------------------------

def create_grower(legal_name="Test Farms", credit_limit_cents=10_000_000) -> dict:
    resp = _api.create_grower(F.create_grower_payload(legal_name=legal_name, credit_limit_cents=credit_limit_cents), CREDIT)
    return get_success_data(resp)


def create_field(grower, name="Test Field", acres=50, watershed_zone="STANDARD") -> dict:
    payload = {"name": name, "acres": acres, "watershed_zone": watershed_zone}
    resp = _api.create_field(grower["id"], payload, grower_headers(grower))
    return get_success_data(resp)


def create_soil_test(field_id, grower) -> dict:
    resp = _api.create_soil_test(field_id, {}, grower_headers(grower))
    return get_success_data(resp)


def resulted_soil_test(field_id, grower, p_ppm=None, k_ppm=None, ph=None) -> dict:
    """Create a soil test and walk it REQUESTED -> SAMPLED -> RESULTED."""
    st = create_soil_test(field_id, grower)
    get_success_data(_api.record_sampling(st["id"], AGRON))
    resp = _api.post_results(
        st["id"],
        F.post_results_payload(
            p_ppm=p_ppm if p_ppm is not None else TD["SOIL_P_PPM"],
            k_ppm=k_ppm if k_ppm is not None else TD["SOIL_K_PPM"],
            ph=ph if ph is not None else TD["SOIL_PH"],
        ),
        AGRON,
    )
    return get_success_data(resp)


def create_recommendation(soil_test_id, **overrides) -> dict:
    resp = _api.create_recommendation(soil_test_id, F.create_recommendation_payload(**overrides), AGRON)
    return get_success_data(resp)


def approved_recommendation(soil_test_id, **overrides) -> dict:
    """Create a recommendation and walk it DRAFT -> PENDING_REVIEW -> APPROVED."""
    rec = create_recommendation(soil_test_id, **overrides)
    get_success_data(_api.submit_recommendation(rec["id"], AGRON))
    resp = _api.approve_recommendation(rec["id"], COMPLIANCE)
    return get_success_data(resp)


def create_nutrient_plan(field_id, **overrides) -> dict:
    resp = _api.create_nutrient_plan(field_id, F.create_nutrient_plan_payload(**overrides), AGRON)
    return get_success_data(resp)


def approved_nutrient_plan(field_id, **overrides) -> dict:
    """Create a plan and walk it DRAFT -> SUBMITTED -> APPROVED."""
    plan = create_nutrient_plan(field_id, **overrides)
    get_success_data(_api.submit_nutrient_plan(plan["id"], AGRON))
    resp = _api.approve_nutrient_plan(plan["id"], COMPLIANCE)
    return get_success_data(resp)


def create_product(name, analysis_n_pct, analysis_p2o5_pct, analysis_k2o_pct, form="DRY", **overrides) -> dict:
    payload = F.create_product_payload(
        name=name,
        analysis_n_pct=analysis_n_pct,
        analysis_p2o5_pct=analysis_p2o5_pct,
        analysis_k2o_pct=analysis_k2o_pct,
        form=form,
        **overrides,
    )
    resp = _api.create_product(payload, ADMIN)
    return get_success_data(resp)


def published_price_sheet(product_id, price_per_ton_cents, season="FALL",
                          effective_from=None, effective_to=None) -> dict:
    payload = F.create_price_sheet_payload(
        season=season,
        price_per_ton_cents=price_per_ton_cents,
        effective_from=effective_from or TD["SHEET_FROM"],
        effective_to=effective_to or TD["SHEET_TO"],
    )
    sheet = get_success_data(_api.create_price_sheet(product_id, payload, ADMIN))
    resp = _api.publish_price_sheet(sheet["id"], ADMIN)
    return get_success_data(resp)


def active_permit(permit_type="FERTILIZER_STORAGE", site_code=None, max_storage_tons=1000,
                  setback_ft=200, expires_at=None) -> dict:
    """Create a permit and walk it APPLICATION -> UNDER_INSPECTION -> ACTIVE."""
    payload = {
        "permit_type": permit_type,
        "site_code": site_code or TD["SITE_CODE"],
        "setback_ft": setback_ft,
    }
    if permit_type == "FERTILIZER_STORAGE":
        payload["max_storage_tons"] = max_storage_tons
    permit = get_success_data(_api.create_permit(payload, COMPLIANCE))
    get_success_data(_api.begin_inspection(permit["id"], COMPLIANCE))
    resp = _api.activate_permit(permit["id"], {"expires_at": expires_at or TD["PERMIT_EXPIRES"]}, COMPLIANCE)
    return get_success_data(resp)


def receive_lot(product_id, received_tons, warehouse_code="WH-A", lot_cost_cents_per_ton=40000) -> dict:
    payload = F.receive_lot_payload(
        product_id=product_id,
        warehouse_code=warehouse_code,
        received_tons=received_tons,
        lot_cost_cents_per_ton=lot_cost_cents_per_ton,
    )
    resp = _api.receive_inventory_lot(payload, PLANT)
    return get_success_data(resp)


def create_blender(site_code=None, form_supported="BOTH", name="BLENDER-1", capacity_tons_per_hour=40) -> dict:
    payload = F.create_blender_payload(
        name=name, site_code=site_code or TD["SITE_CODE"],
        capacity_tons_per_hour=capacity_tons_per_hour, form_supported=form_supported,
    )
    resp = _api.create_blender(payload, PLANT)
    return get_success_data(resp)


def create_prepay_program(**overrides) -> dict:
    resp = _api.create_prepay_program(F.create_prepay_program_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_prepay_contract(grower, prepay_program_id, product_id, committed_tons=20, expected_grower_version=None) -> dict:
    """Sign a prepay contract; OCC expected version defaults to the grower's live version."""
    if expected_grower_version is None:
        expected_grower_version = get_success_data(_api.get_grower(grower["id"], CREDIT))["version"]
    payload = F.create_prepay_contract_payload(
        prepay_program_id=prepay_program_id,
        product_id=product_id,
        committed_tons=committed_tons,
        expected_grower_version=expected_grower_version,
    )
    resp = _api.create_prepay_contract(grower["id"], payload, grower_headers(grower))
    return get_success_data(resp)


def fund_contract(contract_id, amount_cents) -> dict:
    resp = _api.fund_prepay_contract(contract_id, {"amount_cents": amount_cents}, CREDIT)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2/3: order pipelines
# ---------------------------------------------------------------------------

def create_blend_order(grower, field_id, recommendation_id, acres, lines, price_mode="FLOATING",
                       prepay_contract_id=None) -> dict:
    payload = {
        "field_id": field_id,
        "recommendation_id": recommendation_id,
        "acres": acres,
        "price_mode": price_mode,
        "lines": lines,
    }
    if prepay_contract_id is not None:
        payload["prepay_contract_id"] = prepay_contract_id
    resp = _api.create_blend_order(grower["id"], payload, grower_headers(grower))
    return get_success_data(resp)


def book_order(order_id, grower) -> dict:
    resp = _api.book_blend_order(order_id, grower_headers(grower))
    return get_success_data(resp)


def order_line_ids(order_id) -> list:
    """Line ids of an order in list order."""
    data, _meta = _paginated(_api.list_order_lines(order_id, PLANT))
    return [ln["id"] for ln in data]


def _paginated(resp):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(resp)


def setup_order_pipeline(
    legal_name="Pipeline Farms",
    credit_limit_cents=10_000_000,
    field_name="Pipeline Field",
    field_acres=50,
    watershed_zone="STANDARD",
    p_ppm=12,
    k_ppm=90,
    ph=6.1,
    n_cap_lbs_per_acre=300,
    approve_nmp=True,
    products=None,
    prices=None,
    lots=None,
    with_blender=False,
    blender_form="BOTH",
    blender_permit_expires=None,
    lines=None,
    price_mode="FLOATING",
    prepay_contract_id=None,
    recommendation_overrides=None,
):
    """Full grower -> field -> soil test -> approved recommendation -> approved NMP
    -> products+sheets -> permits -> lots -> (blender) -> QUOTED order pipeline.

    products: list of dicts {name, analysis_n_pct, analysis_p2o5_pct, analysis_k2o_pct, form}
    prices:   dict product-name -> price_per_ton_cents (sheet covering the default clock)
    lots:     dict product-name -> received_tons (or list of tons for multiple lots)
    lines:    list of dicts {product_id, target_rate_lbs_per_acre}; when None, caller
              should treat the returned order as absent (order created only when lines given)

    Returns a dict of the scenario context.
    """
    ctx = {}
    grower = create_grower(legal_name=legal_name, credit_limit_cents=credit_limit_cents)
    ctx["grower"] = grower
    field = create_field(grower, name=field_name, acres=field_acres, watershed_zone=watershed_zone)
    ctx["field"] = field
    st = resulted_soil_test(field["id"], grower, p_ppm=p_ppm, k_ppm=k_ppm, ph=ph)
    ctx["soil_test"] = st
    rec = approved_recommendation(st["id"], **(recommendation_overrides or {}))
    ctx["recommendation"] = rec
    plan = create_nutrient_plan(field["id"], n_cap_lbs_per_acre=n_cap_lbs_per_acre)
    plan = get_success_data(_api.submit_nutrient_plan(plan["id"], AGRON))
    if approve_nmp:
        plan = get_success_data(_api.approve_nutrient_plan(plan["id"], COMPLIANCE))
    ctx["nmp"] = plan

    products = products or []
    prices = prices or {}
    lots = lots or {}
    prods = {}
    for spec in products:
        prods[spec["name"]] = create_product(**spec)
    ctx["products"] = prods
    for name, price in prices.items():
        published_price_sheet(prods[name]["id"], price)
    if lots:
        ctx["storage_permit"] = active_permit("FERTILIZER_STORAGE")
        for name, tons in lots.items():
            tons_list = tons if isinstance(tons, list) else [tons]
            for t in tons_list:
                receive_lot(prods[name]["id"], t)
    if with_blender:
        ctx["blender_permit"] = active_permit("BLENDER_SITE", expires_at=blender_permit_expires)
        ctx["blender"] = create_blender(form_supported=blender_form)
    if lines:
        resolved = [
            {**ln, "product_id": prods[ln["product_id"]]["id"] if ln.get("product_id") in prods else ln.get("product_id")}
            for ln in lines
        ]
        ctx["order"] = create_blend_order(
            grower, field["id"], rec["id"], field_acres, resolved,
            price_mode=price_mode, prepay_contract_id=prepay_contract_id,
        )
    return ctx


def setup_booked_order(**kwargs):
    """Pipeline through BOOKED. Accepts setup_order_pipeline kwargs."""
    ctx = setup_order_pipeline(**kwargs)
    ctx["order"] = book_order(ctx["order"]["id"], ctx["grower"])
    return ctx


def setup_batch_in_progress(batch_start="2026-08-05T08:00:00Z", batch_end="2026-08-05T09:00:00Z", **kwargs):
    """Pipeline through a SCHEDULED batch that has been started (IN_PROGRESS)."""
    kwargs.setdefault("with_blender", True)
    ctx = setup_booked_order(**kwargs)
    batch = get_success_data(_api.create_batch(
        ctx["order"]["id"],
        F.create_batch_payload(blender_id=ctx["blender"]["id"],
                               scheduled_start=batch_start, scheduled_end=batch_end),
        PLANT,
    ))
    ctx["batch"] = batch
    get_success_data(_api.start_batch(batch["id"], PLANT))
    ctx["line_ids"] = order_line_ids(ctx["order"]["id"])
    return ctx


def complete_order_batch(ctx, actual_rates=None):
    """Complete the in-progress batch of ctx with actuals matching targets (or given)."""
    order_id = ctx["order"]["id"]
    data, _meta = _paginated(_api.list_order_lines(order_id, PLANT))
    actuals = []
    for ln in data:
        rate = ln["target_rate_lbs_per_acre"]
        if actual_rates and ln["id"] in actual_rates:
            rate = actual_rates[ln["id"]]
        actuals.append({"blend_line_id": ln["id"], "actual_rate_lbs_per_acre": rate})
    return _api.complete_batch(ctx["batch"]["id"], {"actuals": actuals}, PLANT)


def setup_batched_order(**kwargs):
    """Pipeline through batch completion (order BATCHED)."""
    ctx = setup_batch_in_progress(**kwargs)
    get_success_data(complete_order_batch(ctx))
    ctx["order"] = get_success_data(_api.get_blend_order(ctx["order"]["id"], CREDIT))
    return ctx

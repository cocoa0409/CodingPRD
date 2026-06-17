"""Composite setup helpers for the Auto Dealership Management System.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is reset before each test. Fixtures use
get_success_data() (lenient) internally so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: the only entity_backed role is Customer; ownership-gated
Customer calls in test_suite use make_customer_headers(customer_id). The fixtures
below perform their writes as the appropriate operator (opaque) roles.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as f

INV = TEST_USERS["inventory_clerk_headers"]
SALES = TEST_USERS["sales_manager_headers"]
FIN = TEST_USERS["finance_manager_headers"]
SVC = TEST_USERS["service_advisor_headers"]
TITLE = TEST_USERS["title_clerk_headers"]


# --------------------------------------------------------------------------- #
# Tier 0: leaf creators
# --------------------------------------------------------------------------- #
def create_vehicle(**overrides) -> dict:
    return get_success_data(api_client.create_vehicle(f.create_vehicle_payload(**overrides), INV))


def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(f.create_customer_payload(**overrides), SALES))


def create_lender_program(**overrides) -> dict:
    return get_success_data(api_client.create_lender_program(f.create_lender_program_payload(**overrides), FIN))


def create_finance_product(**overrides) -> dict:
    return get_success_data(api_client.create_finance_product(f.create_finance_product_payload(**overrides), FIN))


def create_oem_incentive(**overrides) -> dict:
    return get_success_data(api_client.create_oem_incentive(f.create_oem_incentive_payload(**overrides), SALES))


def create_deal(vehicle_id, customer_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_deal(f.create_deal_payload(vehicle_id, customer_id, **overrides), SALES)
    )


def floor_vehicle(vehicle_id, expected_vehicle_version, **overrides) -> dict:
    return get_success_data(
        api_client.create_floor_plan_line(
            vehicle_id, f.create_floor_plan_line_payload(expected_vehicle_version, **overrides), INV
        )
    )


def upload_document(deal_id, doc_type, uri=None, headers=None) -> dict:
    payload = f.create_document_payload(doc_type=doc_type)
    if uri is not None:
        payload["uri"] = uri
    return get_success_data(api_client.upload_document(deal_id, payload, headers or SALES))


# --------------------------------------------------------------------------- #
# Tier 1: vehicle + (optional) floor-plan line
# --------------------------------------------------------------------------- #
def create_floored_vehicle(principal_cents=1800000, annual_rate_bps=825,
                           floored_on="2026-05-01T00:00:00.000Z", **veh_overrides):
    """Create a vehicle and floor it once. Returns (vehicle, floor_plan_line).

    The vehicle dict reflects state at creation (version 1); flooring bumps the
    live vehicle version by one.
    """
    veh = create_vehicle(**veh_overrides)
    line = floor_vehicle(
        veh["id"], veh["version"],
        principal_cents=principal_cents, annual_rate_bps=annual_rate_bps, floored_on=floored_on,
    )
    return veh, line


# --------------------------------------------------------------------------- #
# Tier 2/3: deal lifecycle shortcuts
# --------------------------------------------------------------------------- #
def create_desked_deal(vehicle_id=None, customer_id=None, deal_overrides=None,
                       customer_overrides=None, vehicle_overrides=None):
    """Create vehicle + customer + DRAFT deal and desk it once.

    Returns (deal_after_desk, vehicle_id, customer_id). The deal dict is the
    response of POST /deals/{id}/desk (status DESKING).
    """
    deal_overrides = deal_overrides or {}
    if vehicle_id is None:
        vehicle_id = create_vehicle(**(vehicle_overrides or {}))["id"]
    if customer_id is None:
        customer_id = create_customer(**(customer_overrides or {}))["id"]
    deal = create_deal(vehicle_id, customer_id, **deal_overrides)
    desked = get_success_data(api_client.desk_deal(deal["id"], SALES))
    return desked, vehicle_id, customer_id


def create_approved_deal(lender_overrides=None, deal_overrides=None,
                         customer_overrides=None, vehicle_overrides=None,
                         with_floor_plan=False, floor_overrides=None):
    """Build a deal all the way to APPROVED.

    Steps: vehicle (+optional floor-plan line) -> customer -> lender program ->
    deal -> desk -> CREDIT_APP doc -> submit-to-lender -> approve.

    Returns dict with keys: deal (the APPROVED deal response), vehicle_id,
    customer_id, lender_program_id, floor_plan_line_id (or None).
    """
    lender_overrides = lender_overrides or {}
    deal_overrides = deal_overrides or {}

    if with_floor_plan:
        veh, line = create_floored_vehicle(**(floor_overrides or {}), **(vehicle_overrides or {}))
        vehicle_id, fp_id = veh["id"], line["id"]
    else:
        vehicle_id = create_vehicle(**(vehicle_overrides or {}))["id"]
        fp_id = None

    customer_id = create_customer(**(customer_overrides or {}))["id"]
    lp = create_lender_program(**lender_overrides)
    deal = create_deal(vehicle_id, customer_id, **deal_overrides)
    deal_id = deal["id"]
    get_success_data(api_client.desk_deal(deal_id, SALES))
    upload_document(deal_id, "CREDIT_APP")
    get_success_data(api_client.submit_to_lender(deal_id, SALES))
    approved = get_success_data(
        api_client.lender_decision(deal_id, {"decision": "APPROVE", "lender_program_id": lp["id"]}, FIN)
    )
    return {
        "deal": approved,
        "deal_id": deal_id,
        "vehicle_id": vehicle_id,
        "customer_id": customer_id,
        "lender_program_id": lp["id"],
        "floor_plan_line_id": fp_id,
    }


def add_finance_contract(deal_id, lender_program_id, expected_deal_version,
                         markup_bps=100, term_months=72):
    """Create a finance contract on an APPROVED deal. Returns the contract dict."""
    payload = f.create_finance_contract_payload(
        lender_program_id, expected_deal_version, markup_bps=markup_bps, term_months=term_months
    )
    return get_success_data(api_client.create_finance_contract(deal_id, payload, FIN))


def create_contracted_deal(lender_overrides=None, deal_overrides=None,
                           customer_overrides=None, vehicle_overrides=None,
                           with_floor_plan=False, floor_overrides=None,
                           markup_bps=100, term_months=72, with_insurance=True):
    """Build a deal through to CONTRACTED.

    Returns dict with keys: deal (CONTRACTED response), deal_id, vehicle_id,
    customer_id, lender_program_id, finance_contract_id, floor_plan_line_id.
    """
    ctx = create_approved_deal(
        lender_overrides=lender_overrides, deal_overrides=deal_overrides,
        customer_overrides=customer_overrides, vehicle_overrides=vehicle_overrides,
        with_floor_plan=with_floor_plan, floor_overrides=floor_overrides,
    )
    deal_id = ctx["deal_id"]
    approved_version = ctx["deal"]["version"]
    fc = add_finance_contract(deal_id, ctx["lender_program_id"], approved_version,
                              markup_bps=markup_bps, term_months=term_months)
    if with_insurance:
        upload_document(deal_id, "INSURANCE")
    contracted = get_success_data(api_client.contract_deal(deal_id, FIN))
    ctx["deal"] = contracted
    ctx["finance_contract_id"] = fc["id"]
    return ctx


def create_funded_deal(lender_overrides=None, deal_overrides=None,
                       customer_overrides=None, vehicle_overrides=None,
                       floor_overrides=None, markup_bps=100, term_months=72,
                       with_odometer=True):
    """Build a deal through to FUNDED (vehicle floored so the payoff cascade fires).

    Returns dict with keys: deal (FUNDED response), deal_id, vehicle_id,
    customer_id, lender_program_id, finance_contract_id, floor_plan_line_id,
    title_registration_id.
    """
    ctx = create_contracted_deal(
        lender_overrides=lender_overrides, deal_overrides=deal_overrides,
        customer_overrides=customer_overrides, vehicle_overrides=vehicle_overrides,
        with_floor_plan=True, floor_overrides=floor_overrides,
        markup_bps=markup_bps, term_months=term_months,
    )
    deal_id = ctx["deal_id"]
    veh = get_success_data(api_client.get_vehicle(ctx["vehicle_id"], FIN))
    funded = get_success_data(
        api_client.fund_deal(deal_id, {"expected_vehicle_version": veh["version"]}, FIN)
    )
    ctx["deal"] = funded
    # Locate the auto-created title registration.
    trs, _ = _list(api_client.list_title_registrations(TITLE, params={"deal_id": deal_id}))
    ctx["title_registration_id"] = trs[0]["id"] if trs else None
    if with_odometer:
        upload_document(deal_id, "ODOMETER", headers=TITLE)
    return ctx


def create_submitted_title(lender_overrides=None, deal_overrides=None,
                           customer_overrides=None, vehicle_overrides=None):
    """Fund a deal, then submit its auto-created title registration once.

    Returns dict (the funded-deal context) plus title_registration_id of a
    SUBMITTED registration.
    """
    ctx = create_funded_deal(
        lender_overrides=lender_overrides, deal_overrides=deal_overrides,
        customer_overrides=customer_overrides, vehicle_overrides=vehicle_overrides,
        with_odometer=True,
    )
    tr_id = ctx["title_registration_id"]
    get_success_data(api_client.submit_title_registration(tr_id, TITLE))
    return ctx


# --------------------------------------------------------------------------- #
# Tier 4: deal with trade / products / incentive (rich pricing scenario)
# --------------------------------------------------------------------------- #
def build_rich_deal_inputs(vehicle_overrides=None, deal_overrides=None,
                           customer_overrides=None, trade=None, incentive=None,
                           products=None):
    """Create vehicle + customer + DRAFT deal, optionally attaching a trade-in,
    an OEM incentive, and finance products before any desk.

    ``trade`` : dict of trade-in payload overrides (or None to skip).
    ``incentive`` : dict of oem incentive payload overrides (applied to the deal)
                    or None to skip.
    ``products`` : list of (finance_product_overrides, sold_price_cents) tuples.

    Returns dict: deal_id, vehicle_id, customer_id, trade_in_id, incentive_id,
    product_ids (list).
    """
    vehicle_id = create_vehicle(**(vehicle_overrides or {}))["id"]
    customer_id = create_customer(**(customer_overrides or {}))["id"]
    deal = create_deal(vehicle_id, customer_id, **(deal_overrides or {}))
    deal_id = deal["id"]

    trade_in_id = None
    if trade is not None:
        td = get_success_data(api_client.attach_trade_in(deal_id, f.create_trade_in_payload(**trade), SALES))
        trade_in_id = td["id"]

    incentive_id = None
    if incentive is not None:
        inc = create_oem_incentive(**incentive)
        incentive_id = inc["id"]
        get_success_data(api_client.apply_incentive(deal_id, {"oem_incentive_id": incentive_id}, SALES))

    product_ids = []
    for prod_overrides, sold_price in (products or []):
        fp = create_finance_product(**prod_overrides)
        dp = get_success_data(
            api_client.attach_product(deal_id, {"finance_product_id": fp["id"], "sold_price_cents": sold_price}, FIN)
        )
        product_ids.append(dp["id"])

    return {
        "deal_id": deal_id,
        "vehicle_id": vehicle_id,
        "customer_id": customer_id,
        "trade_in_id": trade_in_id,
        "incentive_id": incentive_id,
        "product_ids": product_ids,
    }


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _list(response):
    """Return (data_list, meta) from a list response, tolerating either shape."""
    body = response.json() if hasattr(response, "json") else response
    data = body.get("data", [])
    meta = body.get("meta", {})
    return data, meta

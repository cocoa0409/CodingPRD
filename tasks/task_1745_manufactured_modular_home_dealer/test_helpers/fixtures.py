"""Composite setup helpers for multi-step dealer workflows (PRD §3).

Every helper builds its preconditions from scratch against a fresh server and
uses the lenient setup validator so failures surface as clear setup errors.
OCC-guarded creations (site evaluations, financing applications) always re-read
the order first so `expected_sales_order_version` matches the live version.
"""
from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DISPATCH_CLOCK,
    ESCORT_WIDTH_THRESHOLD_1,
    ESCORT_WIDTH_THRESHOLD_2,
    EVAL_DATE,
    JOB_START,
)
from .factories import (
    create_community_payload,
    create_customer_payload,
    create_financing_application_payload,
    create_home_model_payload,
    create_home_unit_payload,
    create_lot_payload,
    create_order_option_payload,
    create_sales_order_payload,
    create_site_evaluation_payload,
    create_title_record_payload,
    create_trade_in_appraisal_payload,
    create_transport_crew_payload,
    create_transport_job_payload,
    create_warranty_claim_payload,
    double_wide_model_payload,
    inspect_trade_in_payload,
    record_findings_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_site_evaluator_headers,
)

ADMIN = TEST_USERS["admin_headers"]
CONSULTANT = TEST_USERS["consultant_headers"]
INSTALLER = TEST_USERS["installer_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
LENDER = TEST_USERS["lender_headers"]
SERVICE = TEST_USERS["service_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]


def min_deposit_cents(total_price_cents: int) -> int:
    """round_half_up(5% of total_price_cents) — the confirm floor (PRD §3.4)."""
    return int((Decimal(total_price_cents) * Decimal("0.05")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def required_escort_count(width_ft: float) -> int:
    """Escort requirement on model width: >=14.0 -> 1, >=16.0 -> 2 (PRD §3.6)."""
    if width_ft >= ESCORT_WIDTH_THRESHOLD_2:
        return 2
    if width_ft >= ESCORT_WIDTH_THRESHOLD_1:
        return 1
    return 0


# --- Tier 1: single-resource creation -------------------------------------

def create_model(double_wide: bool = False, **overrides) -> dict:
    payload = double_wide_model_payload(**overrides) if double_wide else create_home_model_payload(**overrides)
    return get_success_data(api_client.create_home_model(payload, ADMIN))


def create_community(**overrides) -> dict:
    return get_success_data(api_client.create_community(create_community_payload(**overrides), ADMIN))


def create_lot(community_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_lot(community_id, create_lot_payload(**overrides), ADMIN))


def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), CONSULTANT))


def create_unit(model_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_home_unit(create_home_unit_payload(model_id, **overrides), ADMIN))


def create_crew(**overrides) -> dict:
    return get_success_data(api_client.create_transport_crew(create_transport_crew_payload(**overrides), ADMIN))


def reserve_lot(lot_id: str) -> dict:
    return get_success_data(api_client.reserve_lot(lot_id, CONSULTANT))


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_sales_order(order_id, CONSULTANT))


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# --- Tier 2: order scenarios ------------------------------------------------

def new_order_scenario(
    placement_type: str = "PRIVATE_LAND",
    agreed_home_price_cents: int = 4_200_000,
    financing_type: str = "CHATTEL",
    double_wide: bool = False,
    model_overrides: dict | None = None,
    lot_overrides: dict | None = None,
    options: list | None = None,
    reserve: bool = True,
) -> dict:
    """Model + customer + STOCK unit (+ community/lot when COMMUNITY_LOT) + DRAFT order."""
    scn: dict = {"community": None, "lot": None, "options": []}
    scn["model"] = create_model(double_wide=double_wide, **(model_overrides or {}))
    scn["customer"] = create_customer()
    scn["unit"] = create_unit(scn["model"]["id"])
    if placement_type == "COMMUNITY_LOT":
        scn["community"] = create_community()
        scn["lot"] = create_lot(scn["community"]["id"], **(lot_overrides or {}))
        if reserve:
            scn["lot"] = reserve_lot(scn["lot"]["id"])
    payload = create_sales_order_payload(
        scn["customer"]["id"],
        scn["unit"]["id"],
        placement_type=placement_type,
        financing_type=financing_type,
        agreed_home_price_cents=agreed_home_price_cents,
    )
    if scn["lot"] is not None:
        payload["lot_id"] = scn["lot"]["id"]
    scn["order"] = get_success_data(api_client.create_sales_order(payload, CONSULTANT))
    for opt in options or []:
        added = get_success_data(api_client.add_order_option(scn["order"]["id"], opt, CONSULTANT))
        scn["options"].append(added)
    if options:
        scn["order"] = get_order(scn["order"]["id"])
    return scn


def canonical_community_scenario() -> dict:
    """Double-wide community order with the two canonical option lines:
    home 9,200,000 + 250,100 + 89,999 -> total 9,471,997 (PRD §3.3 pricing)."""
    return new_order_scenario(
        placement_type="COMMUNITY_LOT",
        agreed_home_price_cents=9_200_000,
        double_wide=True,
        options=[
            {"option_code": "OPT-APP", "description": "Appliance package", "unit_price_cents": 125_050, "quantity": 2},
            {"option_code": "OPT-EXT", "description": "Exterior package", "unit_price_cents": 89_999, "quantity": 1},
        ],
    )


def refresh_order(scn: dict) -> dict:
    scn["order"] = get_order(scn["order"]["id"])
    return scn["order"]


# --- Tier 3: deal pipeline progression --------------------------------------

def confirm_order(scn: dict, deposit_cents: int | None = None) -> dict:
    if deposit_cents is None:
        deposit_cents = min_deposit_cents(refresh_order(scn)["total_price_cents"])
    scn["order"] = get_success_data(
        api_client.confirm_sales_order(scn["order"]["id"], {"deposit_cents": deposit_cents}, CONSULTANT)
    )
    return scn["order"]


def schedule_evaluation(scn: dict, scheduled_date: str = EVAL_DATE, evaluator_id: str = "eval-1") -> dict:
    version = refresh_order(scn)["version"]
    payload = create_site_evaluation_payload(
        version, scheduled_date=scheduled_date, evaluator_id=evaluator_id
    )
    scn["evaluation"] = get_success_data(
        api_client.create_site_evaluation(scn["order"]["id"], payload, CONSULTANT)
    )
    refresh_order(scn)
    return scn["evaluation"]


def record_findings(scn: dict, evaluation: dict | None = None, **overrides) -> dict:
    ev = evaluation or scn["evaluation"]
    scn["evaluation"] = get_success_data(
        api_client.record_findings(
            ev["id"], record_findings_payload(**overrides), make_site_evaluator_headers(ev["evaluator_id"])
        )
    )
    return scn["evaluation"]


def approve_evaluation(scn: dict, evaluation: dict | None = None) -> dict:
    ev = evaluation or scn["evaluation"]
    scn["evaluation"] = get_success_data(api_client.approve_site_evaluation(ev["id"], INSTALLER))
    refresh_order(scn)
    return scn["evaluation"]


def reject_evaluation(scn: dict, evaluation: dict | None = None) -> dict:
    ev = evaluation or scn["evaluation"]
    scn["evaluation"] = get_success_data(api_client.reject_site_evaluation(ev["id"], INSTALLER))
    refresh_order(scn)
    return scn["evaluation"]


def progress_to_site_approved(scn: dict, deposit_cents: int | None = None, **findings) -> dict:
    confirm_order(scn, deposit_cents)
    schedule_evaluation(scn)
    record_findings(scn, **findings)
    return approve_evaluation(scn)


def create_application(scn: dict, term_months: int = 240, financing_type: str | None = None, **overrides) -> dict:
    version = refresh_order(scn)["version"]
    payload = create_financing_application_payload(
        financing_type or scn["order"]["financing_type"],
        version,
        term_months=term_months,
        down_payment_cents=scn["order"]["deposit_cents"],
        **overrides,
    )
    scn["application"] = get_success_data(
        api_client.create_financing_application(scn["order"]["id"], payload, CONSULTANT)
    )
    refresh_order(scn)
    return scn["application"]


def submit_application(scn: dict, application: dict | None = None) -> dict:
    app = application or scn["application"]
    scn["application"] = get_success_data(api_client.submit_financing_application(app["id"], CONSULTANT))
    return scn["application"]


def decide_application(scn: dict, decision: str = "APPROVE", apr_bps: int | None = None, application: dict | None = None) -> dict:
    app = application or scn["application"]
    payload: dict = {"decision": decision}
    if apr_bps is not None:
        payload["apr_bps"] = apr_bps
    scn["application"] = get_success_data(api_client.decide_financing_application(app["id"], payload, LENDER))
    refresh_order(scn)
    return scn["application"]


def progress_to_financing_approved(scn: dict, term_months: int = 240, apr_bps: int = 725, **kwargs) -> dict:
    """DRAFT -> PENDING_SITE_EVAL -> SITE_APPROVED -> PENDING_FINANCING -> FINANCING_APPROVED."""
    progress_to_site_approved(scn, **kwargs)
    create_application(scn, term_months=term_months)
    submit_application(scn)
    return decide_application(scn, "APPROVE", apr_bps)


def issue_title_for_order(scn: dict, title_type: str | None = None) -> dict:
    if title_type is None:
        title_type = "MANUFACTURED_CERTIFICATE" if scn["order"]["financing_type"] == "CHATTEL" else "REAL_PROPERTY_AFFIXED"
    title = get_success_data(
        api_client.create_title_record(scn["unit"]["id"], create_title_record_payload(title_type=title_type), ADMIN)
    )
    scn["title"] = get_success_data(api_client.issue_title_record(title["id"], ADMIN))
    return scn["title"]


def fund_application(scn: dict, application: dict | None = None, funded_amount_cents: int | None = None) -> dict:
    app = application or scn["application"]
    if funded_amount_cents is None:
        funded_amount_cents = get_success_data(
            api_client.get_financing_application(app["id"], LENDER)
        )["requested_amount_cents"]
    scn["application"] = get_success_data(
        api_client.fund_financing_application(app["id"], {"funded_amount_cents": funded_amount_cents}, LENDER)
    )
    refresh_order(scn)
    return scn["application"]


def progress_to_funded(scn: dict, **kwargs) -> dict:
    """Full pipeline through AWAITING_DELIVERY + FINANCED (title gate satisfied)."""
    progress_to_financing_approved(scn, **kwargs)
    issue_title_for_order(scn)
    return fund_application(scn)


# --- Tier 4: transport execution --------------------------------------------

def book_transport(scn: dict, crew: dict | None = None, **job_overrides) -> tuple:
    if crew is None:
        crew = create_crew()
    scn["crew"] = crew
    escorts = job_overrides.pop("escort_vehicle_count", None)
    if escorts is None:
        escorts = required_escort_count(scn["model"]["width_ft"])
    payload = create_transport_job_payload(
        scn["unit"]["id"], crew["id"], escort_vehicle_count=escorts, **job_overrides
    )
    scn["job"] = get_success_data(api_client.create_transport_job(scn["order"]["id"], payload, COORDINATOR))
    refresh_order(scn)
    return crew, scn["job"]


def progress_to_delivered(scn: dict, dispatch_clock: str = DISPATCH_CLOCK, **kwargs) -> dict:
    """Through booking, dispatch and delivery: unit ON_SITE, order DELIVERED.

    PRD order: booking requires deal_status FINANCING_APPROVED (3.6); funding
    then bubbles the order FINANCING_APPROVED -> AWAITING_DELIVERY (3.5), so
    the booking must be placed before funding, not after."""
    progress_to_financing_approved(scn, **kwargs)
    book_transport(scn)
    issue_title_for_order(scn)
    fund_application(scn)
    set_clock(dispatch_clock)
    job = scn["job"]
    get_success_data(api_client.dispatch_transport_job(job["id"], COORDINATOR))
    scn["job"] = get_success_data(api_client.deliver_transport_job(job["id"], COORDINATOR))
    scn["unit"] = get_success_data(api_client.get_home_unit(scn["unit"]["id"], ADMIN))
    refresh_order(scn)
    return scn["job"]


def progress_to_installed(scn: dict, set_clock_time: str | None = None, **kwargs) -> dict:
    """Through set completion: unit INSTALLED, order SET_COMPLETE (or TITLED)."""
    progress_to_delivered(scn, **kwargs)
    if set_clock_time:
        set_clock(set_clock_time)
    scn["job"] = get_success_data(api_client.complete_set_transport_job(scn["job"]["id"], INSTALLER))
    scn["unit"] = get_success_data(api_client.get_home_unit(scn["unit"]["id"], ADMIN))
    refresh_order(scn)
    return scn["job"]


# --- Tier 5: warranty / trade-in shortcuts -----------------------------------

def create_claim(scn: dict, claim_type: str = "FACTORY_DEFECT", description: str = "Roof seam leak",
                 estimated_cost_cents: int = 240_000, as_role: str = "customer") -> dict:
    payload = create_warranty_claim_payload(
        scn["unit"]["id"], scn["order"]["id"],
        claim_type=claim_type, description=description, estimated_cost_cents=estimated_cost_cents,
    )
    headers = make_customer_headers(scn["customer"]["id"]) if as_role == "customer" else SERVICE
    return get_success_data(api_client.create_warranty_claim(payload, headers))


def create_trade_in(scn: dict, model_id: str | None = None, **overrides) -> dict:
    payload = create_trade_in_appraisal_payload(model_id or scn["model"]["id"], **overrides)
    scn["trade_in"] = get_success_data(
        api_client.create_trade_in_appraisal(scn["order"]["id"], payload, CONSULTANT)
    )
    return scn["trade_in"]


def inspect_trade_in(scn: dict, appraisal: dict | None = None, **overrides) -> dict:
    ta = appraisal or scn["trade_in"]
    scn["trade_in"] = get_success_data(
        api_client.inspect_trade_in_appraisal(ta["id"], inspect_trade_in_payload(**overrides), APPRAISER)
    )
    return scn["trade_in"]


def offer_trade_in(scn: dict, appraisal: dict | None = None) -> dict:
    ta = appraisal or scn["trade_in"]
    scn["trade_in"] = get_success_data(api_client.offer_trade_in_appraisal(ta["id"], APPRAISER))
    return scn["trade_in"]


def create_offered_trade_in(scn: dict, **inspect_overrides) -> dict:
    ta = create_trade_in(scn)
    inspect_trade_in(scn, ta, **inspect_overrides)
    return offer_trade_in(scn)


def accept_trade_in(scn: dict, appraisal: dict | None = None) -> dict:
    ta = appraisal or scn["trade_in"]
    scn["trade_in"] = get_success_data(
        api_client.decide_trade_in_appraisal(
            ta["id"], {"decision": "ACCEPT"}, make_customer_headers(scn["customer"]["id"])
        )
    )
    refresh_order(scn)
    return scn["trade_in"]

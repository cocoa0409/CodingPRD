"""Composite setup helpers for multi-step test prerequisites.

The interesting claims in this PRD (issued pricing, funding waterfall, install
crews, service-plan fees, removal cascades) each need 5-25 API calls of
precondition state. These fixtures build that state from scratch using only
PRD-declared endpoints. They use get_success_data() (lenient) so a setup
failure surfaces as a clear "Setup failed" error rather than a confusing
assertion failure deep in a test.

Identity threading: Customer is the entity-backed role; every ownership-gated
call (quote accept, payment) uses make_customer_headers(customer["id"]).
Version tokens for the OCC-guarded endpoints are always re-read from a fresh
GET immediately before the guarded write, because any state mutation advances
the resource's version.
"""
import itertools
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    MODEL_STRAIGHT, MODEL_CURVED, MODEL_CURVED_OUTDOOR,
    MEASURE_STRAIGHT, MEASURE_CURVED, MEASURE_CURVED_OUTDOOR, TEST_DEFAULTS,
)
from .factories import (
    create_customer_payload, create_product_model_payload,
    create_equipment_unit_payload, create_home_assessment_payload,
    create_measure_payload, create_approve_payload, create_quote_payload,
    create_accept_payload, create_funding_application_payload,
    create_decision_payload, create_payment_payload, create_install_job_payload,
    create_complete_install_payload, create_service_plan_payload,
    create_warranty_claim_payload, create_adjudication_payload,
    create_removal_job_payload,
)
from .test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
ASSESSOR = TEST_USERS["assessor_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
FUNDING = TEST_USERS["funding_officer_headers"]
COORD = TEST_USERS["install_coordinator_headers"]
INVENTORY = TEST_USERS["inventory_manager_headers"]
CLAIMS = TEST_USERS["claims_adjuster_headers"]

_crew_counter = itertools.count(1)
_serial_counter = itertools.count(100)


def fresh_crew(prefix="CREW"):
    """Unique crew id per scenario so buffer/capacity rules never cross-talk."""
    return f"{prefix}-{next(_crew_counter):04d}"


def fresh_serial():
    return f"SN-{next(_serial_counter):06d}"


# ---------------------------------------------------------------------------
# Tier 0: clock + catalog + customer primitives
# ---------------------------------------------------------------------------

_clock_state = {"last": None}


def reset_clock_cache():
    """Reset the monotonic-clock cache. Must run before every test: under
    per-test-server isolation the server reboots (logical clock returns to the
    PRD boot default) for each test, while this pytest process — and therefore
    this module-level cache — persists across tests. Without a reset, a test
    running after one that advanced the clock far forward would see its
    set_clock calls no-op against a fresh server still sitting at boot time."""
    _clock_state["last"] = None


def _parse_iso(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def timeline_dates(offset_days=0):
    """Scenario timeline shifted forward by offset_days so that tests building
    several scenarios in one database keep the logical clock monotone."""
    shift = timedelta(days=offset_days)
    base = _parse_iso(TEST_DEFAULTS["BASE_CLOCK"]) + shift
    install_start = _parse_iso(TEST_DEFAULTS["INSTALL_START"]) + shift
    install_end = _parse_iso(TEST_DEFAULTS["INSTALL_END"]) + shift
    install_clock = _parse_iso(TEST_DEFAULTS["INSTALL_CLOCK"]) + shift
    past_cooling = install_clock + timedelta(days=35)
    return {
        "base": _iso(base),
        "install_start": _iso(install_start),
        "install_end": _iso(install_end),
        "install_clock": _iso(install_clock),
        "past_cooling_off": _iso(past_cooling),
    }


def set_clock(iso=TEST_DEFAULTS["BASE_CLOCK"]):
    """Move the logical clock forward; fires quote-expiry and plan-lapse
    sweeps. The clock only advances — a request at or before the current
    logical time is a no-op so composite fixtures stay monotone."""
    if _clock_state["last"] is not None and iso <= _clock_state["last"]:
        return None
    res = api_client.set_clock(iso, ADMIN)
    data = get_success_data(res)
    assert res.status_code == 200, f"Setup failed: set_clock -> {res.status_code} {res.text}"
    _clock_state["last"] = iso
    return data


def create_catalog_model(model_dict=None, **overrides):
    payload = dict(model_dict or MODEL_STRAIGHT)
    payload.update(overrides)
    res = api_client.create_product_model(payload, ADMIN)
    assert res.status_code == 201, f"Setup failed: create_product_model -> {res.text}"
    return get_success_data(res)


def create_customer(**overrides):
    res = api_client.create_customer(create_customer_payload(**overrides), SALES)
    assert res.status_code == 201, f"Setup failed: create_customer -> {res.text}"
    return get_success_data(res)


def get_customer(customer_id):
    res = api_client.get_customer(customer_id, ADMIN)
    assert res.status_code == 200, f"Setup failed: get_customer -> {res.text}"
    return get_success_data(res)


def get_agreement(agreement_id):
    res = api_client.get_agreement(agreement_id, ADMIN)
    assert res.status_code == 200, f"Setup failed: get_agreement -> {res.text}"
    return get_success_data(res)


def get_quote(quote_id):
    res = api_client.get_quote(quote_id, ADMIN)
    assert res.status_code == 200, f"Setup failed: get_quote -> {res.text}"
    return get_success_data(res)


def get_equipment_unit(unit_id):
    res = api_client.get_equipment_unit(unit_id, ADMIN)
    assert res.status_code == 200, f"Setup failed: get_equipment_unit -> {res.text}"
    return get_success_data(res)


def get_service_plan(plan_id):
    res = api_client.get_service_plan(plan_id, ADMIN)
    assert res.status_code == 200, f"Setup failed: get_service_plan -> {res.text}"
    return get_success_data(res)


def get_warranty_claim(claim_id):
    res = api_client.get_warranty_claim(claim_id, ADMIN)
    assert res.status_code == 200, f"Setup failed: get_warranty_claim -> {res.text}"
    return get_success_data(res)


def create_unit(model_code, serial=None):
    res = api_client.create_equipment_unit(
        create_equipment_unit_payload(model_code, serial_number=serial or fresh_serial()),
        INVENTORY)
    assert res.status_code == 201, f"Setup failed: create_equipment_unit -> {res.text}"
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 1: assessment pipeline (schedule -> measure -> approve)
# ---------------------------------------------------------------------------

def schedule_assessment(customer_id, scheduled_date="2026-06-02"):
    res = api_client.create_home_assessment(
        customer_id, create_home_assessment_payload(scheduled_date=scheduled_date), ASSESSOR)
    assert res.status_code == 201, f"Setup failed: schedule_assessment -> {res.text}"
    return get_success_data(res)


def measure_assessment(assessment_id, measure_dict=None, **overrides):
    payload = dict(measure_dict or MEASURE_STRAIGHT)
    payload.update(overrides)
    res = api_client.measure_home_assessment(assessment_id, payload, ASSESSOR)
    assert res.status_code == 200, f"Setup failed: measure_assessment -> {res.text}"
    return get_success_data(res)


def approve_assessment(assessment_id, model_code):
    res = api_client.approve_home_assessment(
        assessment_id, create_approve_payload(model_code), REVIEWER)
    assert res.status_code == 200, f"Setup failed: approve_assessment -> {res.text}"
    return get_success_data(res)


def setup_approved_assessment(model_code=MODEL_STRAIGHT["model_code"],
                              measure_dict=None, customer_overrides=None):
    """Customer + APPROVED HomeAssessment against model_code. Returns bag."""
    customer = create_customer(**(customer_overrides or {}))
    assessment = schedule_assessment(customer["id"])
    measured = measure_assessment(assessment["id"], measure_dict)
    approved = approve_assessment(assessment["id"], model_code)
    return {"customer": customer, "assessment": approved}


def setup_measured_assessment(model_code=MODEL_STRAIGHT["model_code"],
                              measure_dict=None, customer_overrides=None):
    """Customer + MEASURED (not yet approved) HomeAssessment. Returns bag."""
    customer = create_customer(**(customer_overrides or {}))
    assessment = schedule_assessment(customer["id"])
    measured = measure_assessment(assessment["id"], measure_dict)
    return {"customer": customer, "assessment": measured}


# ---------------------------------------------------------------------------
# Tier 2: quote pipeline (draft -> issue -> accept)
# ---------------------------------------------------------------------------

def create_draft_quote(customer_id, assessment_id,
                       model_code=MODEL_STRAIGHT["model_code"],
                       acquisition_mode="PURCHASE"):
    res = api_client.create_quote(
        customer_id, create_quote_payload(assessment_id, model_code, acquisition_mode), SALES)
    assert res.status_code == 201, f"Setup failed: create_quote -> {res.text}"
    return get_success_data(res)


def issue_quote(quote_id):
    res = api_client.issue_quote(quote_id, SALES)
    assert res.status_code == 200, f"Setup failed: issue_quote -> {res.text}"
    return get_success_data(res)


def create_issued_quote(customer_id, assessment_id,
                        model_code=MODEL_STRAIGHT["model_code"],
                        acquisition_mode="PURCHASE"):
    quote = create_draft_quote(customer_id, assessment_id, model_code, acquisition_mode)
    return issue_quote(quote["id"])


def accept_quote(quote_id, unit_id, customer_id, **accept_overrides):
    """Customer accepts an ISSUED quote. Re-reads the customer version so the
    OCC token is fresh. Returns the created Agreement."""
    customer = get_customer(customer_id)
    payload = create_accept_payload(unit_id, customer["version"], **accept_overrides)
    res = api_client.accept_quote(quote_id, payload, make_customer_headers(customer_id))
    assert res.status_code == 201, f"Setup failed: accept_quote -> {res.text}"
    return get_success_data(res)


def create_agreement(customer_id, assessment_id, model_code=MODEL_STRAIGHT["model_code"],
                     acquisition_mode="PURCHASE", unit=None, **accept_overrides):
    """Issued quote + reserved unit -> Agreement in PENDING_FUNDING.
    Returns bag with quote/unit/agreement."""
    quote = create_issued_quote(customer_id, assessment_id, model_code, acquisition_mode)
    unit = unit or create_unit(model_code)
    agreement = accept_quote(quote["id"], unit["id"], customer_id, **accept_overrides)
    return {"quote": quote, "unit": unit, "agreement": agreement}


# ---------------------------------------------------------------------------
# Tier 3: funding gate (full funding or waiver+skip), install, activation
# ---------------------------------------------------------------------------

def decide_funding(application_id, decision="APPROVED", **overrides):
    res = api_client.decide_funding_application(
        application_id, create_decision_payload(decision, **overrides), FUNDING)
    assert res.status_code == 200, f"Setup failed: decide_funding -> {res.text}"
    return get_success_data(res)


def file_funding_application(quote_id, **overrides):
    res = api_client.create_funding_application(
        quote_id, create_funding_application_payload(**overrides), FUNDING)
    assert res.status_code == 201, f"Setup failed: file_funding_application -> {res.text}"
    return get_success_data(res)


def fully_fund_agreement(quote_id, agreement_id):
    """File and fully approve a single application for the agreement's list
    price; waterfall auto-transitions PENDING_FUNDING -> FUNDED."""
    agreement = get_agreement(agreement_id)
    app = file_funding_application(
        quote_id, requested_cents=agreement["list_price_cents"], priority_rank=1)
    decide_funding(app["id"], "APPROVED",
                   approved_cents=agreement["list_price_cents"])
    funded = get_agreement(agreement_id)
    assert funded["status"] == "FUNDED", \
        f"Setup failed: agreement not FUNDED after full approval -> {funded}"
    return funded


def skip_funding(agreement_id):
    res = api_client.skip_funding(agreement_id, FUNDING)
    assert res.status_code == 200, f"Setup failed: skip_funding -> {res.text}"
    return get_success_data(res)


def schedule_and_complete_install(agreement_id, crew=None, rail_length=4.00,
                                  labor_hours=4, timeline_offset_days=0):
    """Create install job, advance clock past its start, start + complete it.
    Agreement moves -> SCHEDULED (on create) then -> INSTALLED (on complete)."""
    crew = crew or fresh_crew("CREW-INSTALL")
    tl = timeline_dates(timeline_offset_days)
    res = api_client.create_install_job(
        agreement_id, create_install_job_payload(
            crew, scheduled_start_utc=tl["install_start"],
            scheduled_end_utc=tl["install_end"]), COORD)
    assert res.status_code == 201, f"Setup failed: create_install_job -> {res.text}"
    job = get_success_data(res)
    set_clock(tl["install_clock"])
    res = api_client.start_install_job(job["id"], COORD)
    assert res.status_code == 200, f"Setup failed: start_install_job -> {res.text}"
    res = api_client.complete_install_job(
        job["id"], create_complete_install_payload(labor_hours, rail_length), COORD)
    assert res.status_code == 200, f"Setup failed: complete_install_job -> {res.text}"
    return get_success_data(res)


def attach_service_plan(agreement_id, tier="BASIC"):
    res = api_client.create_service_plan(
        agreement_id, create_service_plan_payload(tier), COORD)
    assert res.status_code == 201, f"Setup failed: create_service_plan -> {res.text}"
    return get_success_data(res)


def activate_agreement(agreement_id):
    res = api_client.activate_agreement(agreement_id, COORD)
    assert res.status_code == 200, f"Setup failed: activate_agreement -> {res.text}"
    return get_success_data(res)


def drive_agreement_to_installed(agreement, quote, funding="full",
                                 crew=None, rail_length=4.00, labor_hours=4,
                                 timeline_offset_days=0):
    """Clear the funding gate, then run the install to completion.
    funding="full": full-amount application approved (auto FUNDED).
    funding="skip": waiver-signed skip-funding escape hatch.
    Returns refreshed INSTALLED agreement."""
    if funding == "skip":
        skip_funding(agreement["id"])
    else:
        fully_fund_agreement(quote["id"], agreement["id"])
    schedule_and_complete_install(agreement["id"], crew=crew,
                                  rail_length=rail_length, labor_hours=labor_hours,
                                  timeline_offset_days=timeline_offset_days)
    installed = get_agreement(agreement["id"])
    assert installed["status"] == "INSTALLED", \
        f"Setup failed: agreement not INSTALLED -> {installed}"
    return installed


def drive_agreement_to_active(agreement, quote, tier="BASIC", funding="full",
                              crew=None, rail_length=4.00, labor_hours=4,
                              timeline_offset_days=0):
    """Full lifecycle through ACTIVE. Returns (agreement, service_plan)."""
    drive_agreement_to_installed(agreement, quote, funding=funding, crew=crew,
                                 rail_length=rail_length, labor_hours=labor_hours,
                                 timeline_offset_days=timeline_offset_days)
    plan = attach_service_plan(agreement["id"], tier)
    active = activate_agreement(agreement["id"])
    return active, plan


def record_payment(agreement_id, amount_cents, customer_id):
    """OCC-guarded payment with a freshly re-read agreement version."""
    agreement = get_agreement(agreement_id)
    res = api_client.record_payment(
        agreement_id,
        create_payment_payload(amount_cents, agreement["version"]),
        make_customer_headers(customer_id))
    assert res.status_code == 200, f"Setup failed: record_payment -> {res.text}"
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 4: end-to-end scenario builders
# ---------------------------------------------------------------------------

def setup_active_agreement(model_dict=None, measure_dict=None,
                           acquisition_mode="PURCHASE", waiver=False,
                           tier="BASIC", committed_rental_months=None,
                           customer_overrides=None, funding="full",
                           timeline_offset_days=0):
    """Customer -> approved assessment -> issued quote -> accepted (unit
    reserved) -> funding cleared -> installed -> plan -> ACTIVE.

    Returns a bag: customer, assessment, quote, unit, agreement, service_plan.
    """
    model_dict = model_dict or MODEL_STRAIGHT
    measure_dict = measure_dict or MEASURE_STRAIGHT
    tl = timeline_dates(timeline_offset_days)
    set_clock(tl["base"])
    model = create_catalog_model(model_dict)
    base = setup_approved_assessment(model["model_code"], measure_dict, customer_overrides)
    accept_overrides = {"liability_waiver_signed": True} if waiver else {}
    if acquisition_mode == "RENTAL" and committed_rental_months is not None:
        accept_overrides["committed_rental_months"] = committed_rental_months
    bag = create_agreement(base["customer"]["id"], base["assessment"]["id"],
                           model["model_code"], acquisition_mode, **accept_overrides)
    rail = 4.56 if measure_dict.get("staircase_kind") == "CURVED" else 4.00
    labor = model_dict["install_labor_hours"]
    agreement, plan = drive_agreement_to_active(
        bag["agreement"], bag["quote"], tier=tier, funding=funding,
        rail_length=rail, labor_hours=labor,
        timeline_offset_days=timeline_offset_days)
    return {
        "customer": get_customer(base["customer"]["id"]),
        "assessment": base["assessment"],
        "quote": get_quote(bag["quote"]["id"]),
        "unit": get_equipment_unit(bag["unit"]["id"]),
        "agreement": agreement,
        "service_plan": plan,
        "timeline": tl,
    }


def create_refurbished_unit(model_dict=None, grade="REFURB_B", crew=None):
    """Produce an IN_STOCK unit whose condition_grade is `grade` by running a
    full sacrificial lifecycle: NEW unit installed for a throwaway PURCHASE
    agreement, removed past the 30-day cooling-off with the requested grade,
    then restocked by the InventoryManager.

    Needed because receiving always yields condition NEW, and the risk adder
    for REFURB_B/REFURB_C can only attach to a previously removed unit.
    """
    model_dict = model_dict or MODEL_STRAIGHT
    set_clock()
    model = create_catalog_model(model_dict)
    base = setup_approved_assessment(model["model_code"], MEASURE_STRAIGHT)
    unit = create_unit(model["model_code"])
    bag = create_agreement(base["customer"]["id"], base["assessment"]["id"],
                           model["model_code"], "PURCHASE", unit=unit,
                           liability_waiver_signed=True)
    drive_agreement_to_active(bag["agreement"], bag["quote"], tier="BASIC",
                              funding="skip", crew=fresh_crew("CREW-REFURB"))
    # PURCHASE cooling-off: advance 35 days past the install completion.
    tl = timeline_dates(0)
    set_clock(tl["past_cooling_off"])
    res = api_client.create_removal_job(
        bag["agreement"]["id"],
        create_removal_job_payload(fresh_crew("CREW-REFURB-RM"),
                                   scheduled_start_utc="2026-07-20T09:00:00Z",
                                   scheduled_end_utc="2026-07-20T11:00:00Z"),
        COORD)
    assert res.status_code == 201, f"Setup failed: refurb removal create -> {res.text}"
    removal = get_success_data(res)
    res = api_client.complete_removal_job(
        removal["id"], {"condition_grade_at_removal": grade}, COORD)
    assert res.status_code == 200, f"Setup failed: refurb removal complete -> {res.text}"
    removed = get_equipment_unit(unit["id"])
    assert removed["status"] == "REMOVED" and removed["condition_grade"] == grade, \
        f"Setup failed: unit not REMOVED/{grade} -> {removed}"
    res = api_client.restock_equipment_unit(unit["id"], INVENTORY)
    assert res.status_code == 200, f"Setup failed: restock -> {res.text}"
    restocked = get_equipment_unit(unit["id"])
    assert restocked["status"] == "IN_STOCK", \
        f"Setup failed: unit not IN_STOCK after restock -> {restocked}"
    return restocked


def setup_active_agreement_with_refurb_unit(model_dict=None, measure_dict=None,
                                            waiver=False, tier="PREMIUM"):
    """ACTIVE agreement whose installed unit is REFURB_B (refurb risk adder
    eligible), with the service plan NOT yet attached. Returns the scenario
    bag plus the refurbished unit; the caller creates the plan under test.

    Waiver path uses skip-funding; non-waiver path uses full funding so the
    skip-funding escape-hatch preconditions never hinge on an empty
    application set. The clock is left where the refurb pipeline put it (past
    the sacrificial install's cooling-off); the main install's scheduled
    window is earlier than the clock, which the start gate permits.
    """
    model_dict = model_dict or MODEL_CURVED
    measure_dict = measure_dict or MEASURE_CURVED
    unit = create_refurbished_unit(model_dict, grade="REFURB_B")
    model = create_catalog_model(model_dict)
    base = setup_approved_assessment(model["model_code"], measure_dict)
    accept_overrides = {"liability_waiver_signed": True} if waiver else {}
    bag = create_agreement(base["customer"]["id"], base["assessment"]["id"],
                           model["model_code"], "PURCHASE", unit=unit,
                           **accept_overrides)
    drive_agreement_to_installed(bag["agreement"], bag["quote"],
                                 funding="skip" if waiver else "full",
                                 rail_length=4.56,
                                 labor_hours=model_dict["install_labor_hours"])
    return {
        "customer": get_customer(base["customer"]["id"]),
        "assessment": base["assessment"],
        "quote": get_quote(bag["quote"]["id"]),
        "unit": get_equipment_unit(unit["id"]),
        "agreement": get_agreement(bag["agreement"]["id"]),
    }


def setup_active_purchase_past_cooling_off(model_dict=None, tier="STANDARD",
                                           region="NORTH", timeline_offset_days=0):
    """ACTIVE PURCHASE agreement with the logical clock advanced 35 days past
    its install completion (beyond the 30-day cooling-off). Pass distinct
    timeline_offset_days when a test builds several such scenarios in one
    database so the logical clock stays monotone. Returns bag."""
    bag = setup_active_agreement(model_dict=model_dict or MODEL_STRAIGHT,
                                 tier=tier,
                                 customer_overrides={"home_region_code": region},
                                 timeline_offset_days=timeline_offset_days)
    set_clock(bag["timeline"]["past_cooling_off"])
    return bag


def schedule_removal(agreement_id, crew=None, start="2026-08-01T09:00:00Z",
                     end="2026-08-01T11:00:00Z"):
    res = api_client.create_removal_job(
        agreement_id,
        create_removal_job_payload(crew or fresh_crew("CREW-RM"),
                                   scheduled_start_utc=start,
                                   scheduled_end_utc=end),
        COORD)
    assert res.status_code == 201, f"Setup failed: schedule_removal -> {res.text}"
    return get_success_data(res)


def file_claim(agreement_id, plan_id, claim_kind="MECHANICAL", claimed_cents=5000):
    res = api_client.create_warranty_claim(
        agreement_id,
        create_warranty_claim_payload(plan_id, claim_kind, claimed_cents),
        CLAIMS)
    assert res.status_code == 201, f"Setup failed: file_claim -> {res.text}"
    return get_success_data(res)


def review_claim(claim_id):
    res = api_client.review_warranty_claim(claim_id, CLAIMS)
    assert res.status_code == 200, f"Setup failed: review_claim -> {res.text}"
    return get_success_data(res)


def adjudicate_claim(claim_id, decision="APPROVED", **overrides):
    res = api_client.adjudicate_warranty_claim(
        claim_id, create_adjudication_payload(decision, **overrides), CLAIMS)
    assert res.status_code == 200, f"Setup failed: adjudicate_claim -> {res.text}"
    return get_success_data(res)

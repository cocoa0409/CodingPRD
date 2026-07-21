"""Composite setup helpers for the HEI lifecycle.

Every helper accepts the ApiClient as its first argument and builds its
preconditions from scratch using only PRD-declared endpoints. Setup calls use
get_success_data() so a broken precondition surfaces as a clear "Setup failed".

The dominant preamble across the suite is:
  fund -> homeowner -> application -> AVM valuation -> submit -> approve
  -> present offer -> accept -> record lien -> activate -> initiate-exit
  -> advance clock -> read agreement.version
which lands an Agreement at EXIT_INITIATED with adjusted_start_value 72,000,000
(from an 80,000,000 AVM basis and a 0.10 risk adjustment).
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import (
    TEST_USERS,
    make_homeowner_headers,
    make_appraiser_headers,
    make_inspector_headers,
    make_compliance_headers,
)
from . import factories as F

ANALYST = TEST_USERS["analyst_headers"]
CLOSING = TEST_USERS["closing_agent_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# --------------------------------------------------------------------------
# Low-level single-entity helpers
# --------------------------------------------------------------------------
def create_fund(api, total_capital_cents=50000000, name=None):
    payload = F.create_fund_payload(total_capital_cents=total_capital_cents)
    if name is not None:
        payload["name"] = name
    return get_success_data(api.create_fund(payload, ANALYST))


def create_homeowner(api):
    return get_success_data(api.create_homeowner(F.create_homeowner_payload(), ANALYST))


def create_application(api, homeowner_id, fund_id, **overrides):
    ho_headers = make_homeowner_headers(homeowner_id)
    payload = F.create_application_payload(homeowner_id, fund_id, **overrides)
    return get_success_data(api.create_application(payload, ho_headers))


def create_avm_valuation(api, application_id, valued_amount_cents=80000000):
    payload = F.create_avm_valuation_payload(valued_amount_cents=valued_amount_cents)
    return get_success_data(api.create_valuation(application_id, payload, ANALYST))


def create_appraisal_valuation(api, application_id):
    payload = F.create_appraisal_valuation_payload()
    return get_success_data(api.create_valuation(application_id, payload, ANALYST))


def submit_application(api, application_id, homeowner_id):
    return get_success_data(
        api.submit_application(application_id, make_homeowner_headers(homeowner_id))
    )


def approve_application(api, application_id):
    return get_success_data(
        api.decide_application(application_id, {"decision": "APPROVE"}, ANALYST)
    )


def present_offer(api, application_id, valuation_id, **overrides):
    payload = F.create_offer_payload(valuation_id, **overrides)
    return get_success_data(api.create_offer(application_id, payload, ANALYST))


def accept_offer(api, offer_id, homeowner_id):
    return get_success_data(api.accept_offer(offer_id, make_homeowner_headers(homeowner_id)))


def agreement_for_offer(api, offer_id):
    data, _ = _list(api.list_agreements(ANALYST, params={"offer_id": offer_id}))
    assert data, f"no agreement found for offer {offer_id}"
    return data[0]


def lien_for_agreement(api, agreement_id):
    data, _ = _list(api.list_liens(CLOSING, params={"agreement_id": agreement_id}))
    assert data, f"no lien found for agreement {agreement_id}"
    return data[0]


def record_lien(api, lien_id, title_status="CLEAR", lien_position=2):
    return get_success_data(
        api.record_lien(lien_id, {"title_status": title_status, "lien_position": lien_position}, CLOSING)
    )


def activate_agreement(api, agreement_id):
    return get_success_data(api.activate_agreement(agreement_id, CLOSING))


def initiate_exit(api, agreement_id, homeowner_id):
    return get_success_data(api.initiate_exit(agreement_id, make_homeowner_headers(homeowner_id)))


def set_clock(api, to_iso8601):
    return api.set_clock(to_iso8601, COMPLIANCE)


def agreement_version(api, agreement_id):
    return get_success_data(api.get_agreement(agreement_id, COMPLIANCE))["version"]


def _list(response):
    """Parse a paginated list response into (data_list, meta)."""
    body = response.json()
    return body["data"], body.get("meta", {})


# --------------------------------------------------------------------------
# Tier 1/2: application-stage composites
# --------------------------------------------------------------------------
def setup_under_review_application(api, *, fund_total_cents=50000000,
                                   valued_amount_cents=80000000,
                                   requested_investment_cents=10000000,
                                   existing_mortgage_balance_cents=40000000,
                                   property_type="SINGLE_FAMILY"):
    """Fund + homeowner + application + COMPLETED AVM valuation + submit.
    Leaves the application UNDER_REVIEW (no decision yet)."""
    fund = create_fund(api, total_capital_cents=fund_total_cents)
    homeowner = create_homeowner(api)
    application = create_application(
        api, homeowner["id"], fund["id"],
        property_type=property_type,
        homeowner_estimated_value_cents=valued_amount_cents,
        existing_mortgage_balance_cents=existing_mortgage_balance_cents,
        requested_investment_cents=requested_investment_cents,
    )
    valuation = create_avm_valuation(api, application["id"], valued_amount_cents=valued_amount_cents)
    submit_application(api, application["id"], homeowner["id"])
    return {
        "fund": fund,
        "homeowner": homeowner,
        "application": application,
        "valuation": valuation,
    }


def setup_approved_application(api, **kwargs):
    """UNDER_REVIEW application advanced through APPROVE. Returns the same dict
    with the (re-read) approved application."""
    ctx = setup_under_review_application(api, **kwargs)
    ctx["application"] = approve_application(api, ctx["application"]["id"])
    return ctx


def setup_approved_with_dual_basis(api, *, avm_valued_cents=80000000,
                                   appraisal_valued_cents=90000000,
                                   requested_investment_cents=25000000,
                                   existing_mortgage_balance_cents=20000000,
                                   fund_total_cents=50000000,
                                   property_type="CONDO"):
    """Approved application carrying BOTH a COMPLETED AVM valuation and a
    COMPLETED APPRAISAL valuation (completed via an appointment), so the two
    bases yield different investment ceilings. Returns fund/homeowner/
    application plus `avm_valuation` and `appraisal_valuation`."""
    fund = create_fund(api, total_capital_cents=fund_total_cents)
    homeowner = create_homeowner(api)
    application = create_application(
        api, homeowner["id"], fund["id"],
        property_type=property_type,
        homeowner_estimated_value_cents=appraisal_valued_cents,
        existing_mortgage_balance_cents=existing_mortgage_balance_cents,
        requested_investment_cents=requested_investment_cents,
    )
    avm = create_avm_valuation(api, application["id"], valued_amount_cents=avm_valued_cents)
    appraisal = create_appraisal_valuation(api, application["id"])
    appraiser = get_success_data(api.create_appraiser(F.create_appraiser_payload(region_code="CA-BAY"), ANALYST))
    appointment = schedule_appointment(api, appraiser["id"], appraisal["id"])
    get_success_data(api.complete_appointment(
        appointment["id"], {"valued_amount_cents": appraisal_valued_cents},
        make_appraiser_headers(appraiser["id"]),
    ))
    submit_application(api, application["id"], homeowner["id"])
    application = approve_application(api, application["id"])
    return {
        "fund": fund,
        "homeowner": homeowner,
        "application": application,
        "avm_valuation": avm,
        "appraisal_valuation": get_success_data(api.get_valuation(appraisal["id"], ANALYST)),
    }


def setup_presented_offer(api, *, offer_overrides=None, **kwargs):
    """Approved application with one PRESENTED offer on the AVM basis."""
    ctx = setup_approved_application(api, **kwargs)
    offer_overrides = offer_overrides or {}
    ctx["offer"] = present_offer(
        api, ctx["application"]["id"], ctx["valuation"]["id"], **offer_overrides
    )
    return ctx


# --------------------------------------------------------------------------
# Tier 3: agreement-lifecycle composites
# --------------------------------------------------------------------------
def setup_funded_agreement(api, *, offer_overrides=None, **kwargs):
    """Accept the presented offer -> Agreement FUNDED with a PENDING Lien."""
    ctx = setup_presented_offer(api, offer_overrides=offer_overrides, **kwargs)
    accept_offer(api, ctx["offer"]["id"], ctx["homeowner"]["id"])
    ctx["agreement"] = agreement_for_offer(api, ctx["offer"]["id"])
    ctx["lien"] = lien_for_agreement(api, ctx["agreement"]["id"])
    return ctx


def setup_active_agreement(api, *, offer_overrides=None, **kwargs):
    """Funded agreement with lien recorded CLEAR and agreement ACTIVE."""
    ctx = setup_funded_agreement(api, offer_overrides=offer_overrides, **kwargs)
    ctx["lien"] = record_lien(api, ctx["lien"]["id"])
    ctx["agreement"] = activate_agreement(api, ctx["agreement"]["id"])
    return ctx


def setup_exit_initiated_agreement(api, *, clock="2028-07-01T00:00:00Z",
                                   offer_overrides=None, **kwargs):
    """Active agreement moved to EXIT_INITIATED, then the clock advanced.
    Captures the current agreement version under `agreement_version`."""
    ctx = setup_active_agreement(api, offer_overrides=offer_overrides, **kwargs)
    ctx["agreement"] = initiate_exit(api, ctx["agreement"]["id"], ctx["homeowner"]["id"])
    if clock is not None:
        set_clock(api, clock)
    ctx["agreement_version"] = agreement_version(api, ctx["agreement"]["id"])
    return ctx


def propose_sale_settlement(api, agreement_id, sale_price_cents, mortgage_payoff_cents,
                            expected_agreement_version, officer_user_id=None):
    headers = make_compliance_headers(officer_user_id) if officer_user_id else COMPLIANCE
    payload = F.create_sale_settlement_payload(
        sale_price_cents, mortgage_payoff_cents, expected_agreement_version
    )
    return get_success_data(api.create_settlement(agreement_id, payload, headers))


def propose_buyout_settlement(api, agreement_id, current_appraised_value_cents,
                              mortgage_payoff_cents, expected_agreement_version,
                              officer_user_id=None):
    headers = make_compliance_headers(officer_user_id) if officer_user_id else COMPLIANCE
    payload = F.create_buyout_settlement_payload(
        current_appraised_value_cents, mortgage_payoff_cents, expected_agreement_version
    )
    return get_success_data(api.create_settlement(agreement_id, payload, headers))


def dispute_settlement(api, settlement_id, homeowner_id, reason="value too low",
                       disputed_value_cents=130000000):
    payload = {"reason": reason, "disputed_value_cents": disputed_value_cents}
    return get_success_data(
        api.dispute_settlement(settlement_id, payload, make_homeowner_headers(homeowner_id))
    )


# --------------------------------------------------------------------------
# Tier 3: settlement-stage composites (single flexible SALE proposal)
# --------------------------------------------------------------------------
def setup_proposed_sale_settlement(api, *, sale_price_cents, mortgage_payoff_cents,
                                   clock="2028-07-01T00:00:00Z", officer_user_id=None,
                                   offer_overrides=None, **kwargs):
    """EXIT_INITIATED agreement with one PROPOSED SALE settlement. Returns the
    context plus `settlement` and the officer id that proposed it."""
    ctx = setup_exit_initiated_agreement(api, clock=clock, offer_overrides=offer_overrides, **kwargs)
    ctx["settlement"] = propose_sale_settlement(
        api, ctx["agreement"]["id"], sale_price_cents, mortgage_payoff_cents,
        ctx["agreement_version"], officer_user_id=officer_user_id,
    )
    ctx["proposing_officer"] = officer_user_id or "test-compliance-1"
    return ctx


# --------------------------------------------------------------------------
# Tier 2: appraisal-appointment composites
# --------------------------------------------------------------------------
def setup_appraiser_with_pending_valuations(api, *, num_valuations=1, region_code="CA-BAY"):
    """Application with N PENDING APPRAISAL valuations and one appraiser."""
    fund = create_fund(api)
    homeowner = create_homeowner(api)
    application = create_application(api, homeowner["id"], fund["id"])
    valuations = [create_appraisal_valuation(api, application["id"]) for _ in range(num_valuations)]
    appraiser = get_success_data(
        api.create_appraiser(F.create_appraiser_payload(region_code=region_code), ANALYST)
    )
    return {
        "fund": fund,
        "homeowner": homeowner,
        "application": application,
        "valuations": valuations,
        "appraiser": appraiser,
    }


def schedule_appointment(api, appraiser_id, valuation_id, *, region_code="CA-BAY",
                         scheduled_start="2026-07-05T10:00:00Z",
                         scheduled_end="2026-07-05T11:00:00Z"):
    payload = F.create_appointment_payload(
        appraiser_id, valuation_id, region_code=region_code,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
    )
    return get_success_data(api.create_appointment(payload, ANALYST))


# --------------------------------------------------------------------------
# Tier 2: inspection composites
# --------------------------------------------------------------------------
def create_inspector(api, region_code="CA-BAY"):
    return get_success_data(api.create_inspector(F.create_inspector_payload(region_code=region_code), ANALYST))


def schedule_inspection(api, agreement_id, inspector_id, scheduled_date="2026-09-01"):
    payload = F.create_inspection_payload(inspector_id, scheduled_date=scheduled_date)
    return get_success_data(api.create_inspection(agreement_id, payload, ANALYST))


def complete_inspection(api, inspection_id, inspector_id, result, condition_score):
    payload = {"result": result, "condition_score": condition_score}
    return get_success_data(
        api.complete_inspection(inspection_id, payload, make_inspector_headers(inspector_id))
    )

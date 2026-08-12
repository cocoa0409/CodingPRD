"""Composite setup helpers for multi-step test prerequisites.

The interesting claims in this PRD require the system to be deep into a
workflow (a signed contract, an active operation phase, a computed award).
These helpers encapsulate those chains so tests focus on assertions.

All helpers use get_success_data() (lenient) so a setup failure surfaces as a
clear "Setup step failed" error naming the offending call.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import PERMIT_MAP, TEST_DEFAULTS
from .factories import (
    create_assessment_payload,
    create_casualty_payload,
    create_charter_payload,
    create_contract_payload,
    create_disburse_payload,
    create_doc_pack_payload,
    create_equipment_asset_payload,
    create_permit_payload,
    create_phase_activation_payload,
    create_phase_payload,
    create_plan_payload,
    create_pollution_event_payload,
    create_property_payload,
    create_security_payload,
    create_storage_site_payload,
    create_weather_window_payload,
)
from .test_users import TEST_USERS

SM = TEST_USERS["salvage_master_headers"]
CO = TEST_USERS["contracts_officer_headers"]
SURVEYOR = TEST_USERS["marine_surveyor_headers"]
PROP_SURVEYOR = TEST_USERS["property_surveyor_headers"]
ENV = TEST_USERS["environmental_officer_headers"]
OPS = TEST_USERS["operations_director_headers"]
ARB = TEST_USERS["arbitrator_headers"]
INS = TEST_USERS["insurer_surveyor_headers"]

# Standard operation timeline used by most fixtures
OPS_NOW = "2026-05-10T00:00:00Z"
CHARTER_START = "2026-05-10T00:00:00Z"
CHARTER_END = "2026-05-24T00:00:00Z"
WEATHER_START = "2026-05-08T00:00:00Z"
WEATHER_END = "2026-05-26T00:00:00Z"
PERMIT_FROM = "2026-05-01T00:00:00Z"
PERMIT_TO = "2026-06-30T00:00:00Z"


# ─── Tier 1: single-entity creation + state progression ───
def report_casualty(**overrides):
    """Report a casualty. Returns the created Casualty (REPORTED, ENV_CLEAR)."""
    res = api_client.create_casualty(create_casualty_payload(**overrides), SM)
    return get_success_data(res)


def submit_assessment(casualty_id, headers=None, **overrides):
    """File an assessment, threading the casualty's CURRENT version (OCC)."""
    headers = headers or SURVEYOR
    casualty = get_success_data(api_client.get_casualty(casualty_id, SURVEYOR))
    payload = create_assessment_payload(casualty_id, casualty["version"], **overrides)
    res = api_client.create_assessment(payload, headers)
    return get_success_data(res)


def approve_assessment(assessment_id, headers=None):
    res = api_client.approve_assessment(assessment_id, headers or OPS)
    return get_success_data(res)


def draft_plan(casualty_id, headers=None, **overrides):
    res = api_client.create_plan(create_plan_payload(casualty_id, **overrides), headers or SM)
    return get_success_data(res)


def submit_plan(plan_id, headers=None):
    return get_success_data(api_client.submit_plan(plan_id, headers or SM))


def approve_plan(plan_id, headers=None):
    return get_success_data(api_client.approve_plan(plan_id, headers or OPS))


def register_asset(headers=None, **overrides):
    return get_success_data(
        api_client.create_equipment_asset(create_equipment_asset_payload(**overrides), headers or OPS)
    )


def set_clock(to_iso8601, headers=None):
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, headers or OPS)
    )


def grant_permit(casualty_id, agency_type, valid_from=PERMIT_FROM, valid_to=PERMIT_TO):
    """File + grant a permit. Returns the granted Permit."""
    permit = get_success_data(
        api_client.create_permit(
            create_permit_payload(
                casualty_id, agency_type=agency_type,
                valid_from=valid_from, valid_to=valid_to,
            ),
            ENV,
        )
    )
    return get_success_data(api_client.grant_permit(permit["id"], ENV))


def book_charter(casualty_id, asset_id, headers=None, **overrides):
    res = api_client.create_charter(
        create_charter_payload(casualty_id, asset_id, **overrides), headers or SM
    )
    return get_success_data(res)


def open_weather_window(casualty_id, **overrides):
    return get_success_data(
        api_client.create_weather_window(
            create_weather_window_payload(casualty_id, **overrides), SM
        )
    )


def report_pollution_event(casualty_id, **overrides):
    return get_success_data(
        api_client.create_pollution_event(
            create_pollution_event_payload(casualty_id, **overrides), ENV
        )
    )


def register_site(**overrides):
    return get_success_data(
        api_client.create_storage_site(create_storage_site_payload(**overrides), OPS)
    )


# ─── Tier 2: entity hierarchy — casualty paperwork chain ───
def setup_assessed_casualty(casualty_overrides=None, assessment_overrides=None,
                            assessor_headers=None, approver_headers=None):
    """Casualty + APPROVED assessment. Casualty ends in ASSESSED."""
    casualty = report_casualty(**(casualty_overrides or {}))
    assessment = submit_assessment(
        casualty["id"], headers=assessor_headers, **(assessment_overrides or {})
    )
    assessment = approve_assessment(assessment["id"], headers=approver_headers)
    casualty = get_success_data(api_client.get_casualty(casualty["id"], SM))
    return {"casualty": casualty, "assessment": assessment}


def setup_planned_casualty(plan_method="REFLOAT", plan_classes=None, **kwargs):
    """Assessed casualty + APPROVED plan. Casualty ends in PLANNED."""
    ctx = setup_assessed_casualty(**kwargs)
    plan = draft_plan(
        ctx["casualty"]["id"],
        method=plan_method,
        required_equipment_classes=plan_classes or ["TUG"],
    )
    submit_plan(plan["id"])
    plan = approve_plan(plan["id"])
    ctx["plan"] = plan
    ctx["casualty"] = get_success_data(api_client.get_casualty(ctx["casualty"]["id"], SM))
    return ctx


def create_contract(casualty_id, plan_id, **overrides):
    return get_success_data(
        api_client.create_contract(
            create_contract_payload(casualty_id, plan_id, **overrides), CO
        )
    )


def offer_contract(contract_id):
    return get_success_data(api_client.offer_contract(contract_id, CO))


def sign_contract(contract_id):
    return get_success_data(api_client.sign_contract(contract_id, CO))


def lodge_security(contract_id, amount_cents):
    return get_success_data(
        api_client.create_security(
            create_security_payload(contract_id, lodged_amount_cents=amount_cents), CO
        )
    )


def setup_signed_contract(form="NO_CURE_NO_PAY", fixed_price_cents=None,
                          scopic_clause_included=False, offer=True, **kwargs):
    """Planned casualty + contract through offer -> sign. Ends SIGNED;
    casualty CONTRACTED. The contract carries computed provisional award and
    security requirement figures."""
    ctx = setup_planned_casualty(**kwargs)
    contract_overrides = {"form": form, "scopic_clause_included": scopic_clause_included}
    if fixed_price_cents is not None:
        contract_overrides["fixed_price_cents"] = fixed_price_cents
    contract = create_contract(
        ctx["casualty"]["id"], ctx["plan"]["id"], **contract_overrides
    )
    if offer:
        contract = offer_contract(contract["id"])
    contract = sign_contract(contract["id"])
    ctx["contract"] = contract
    ctx["casualty"] = get_success_data(api_client.get_casualty(ctx["casualty"]["id"], SM))
    return ctx


def setup_active_contract(security_amount_cents=None, lodge=True, **kwargs):
    """Signed contract + security lodged + activation. Ends ACTIVE."""
    ctx = setup_signed_contract(**kwargs)
    amount = security_amount_cents
    if amount is None:
        amount = ctx["contract"]["security_required_cents"]
    if lodge:
        ctx["security"] = lodge_security(ctx["contract"]["id"], amount)
    ctx["contract"] = get_success_data(
        api_client.activate_contract(ctx["contract"]["id"], CO)
    )
    return ctx


# ─── Tier 3: full lifecycle shortcuts ───
def setup_running_phase(phase_type="REFLOAT", phase_duration_hours=96,
                        asset_class="TUG", day_rate_cents=2_000_000,
                        max_hs_meters=2.50, forecast_hs_meters=2.00,
                        charter_window=(CHARTER_START, CHARTER_END),
                        weather_window=(WEATHER_START, WEATHER_END),
                        ops_now=OPS_NOW, permit_agencies=None,
                        permit_valid_from=PERMIT_FROM, permit_valid_to=PERMIT_TO,
                        activate=True, **kwargs):
    """Active contract + on-hire charter + open weather window + granted
    permits + (optionally) an ACTIVATED phase. Casualty ends IN_OPERATION
    when activated (CONTRACTED otherwise)."""
    ctx = setup_active_contract(**kwargs)
    asset = register_asset(asset_class=asset_class, day_rate_cents=day_rate_cents,
                           max_hs_meters=max_hs_meters)
    set_clock(ops_now)
    charter = book_charter(
        ctx["casualty"]["id"], asset["id"],
        window_start=charter_window[0], window_end=charter_window[1],
    )
    charter = get_success_data(api_client.on_hire_charter(charter["id"], SM))
    window = open_weather_window(
        ctx["casualty"]["id"], window_start=weather_window[0],
        window_end=weather_window[1], forecast_hs_meters=forecast_hs_meters,
    )
    permits = {}
    for agency in (permit_agencies if permit_agencies is not None else PERMIT_MAP[phase_type]):
        permits[agency] = grant_permit(
            ctx["casualty"]["id"], agency,
            valid_from=permit_valid_from, valid_to=permit_valid_to,
        )
    phase = get_success_data(
        api_client.create_phase(
            create_phase_payload(
                ctx["contract"]["id"], phase_type=phase_type,
                planned_duration_hours=phase_duration_hours,
            ),
            SM,
        )
    )
    if activate:
        phase = get_success_data(
            api_client.activate_phase(
                phase["id"],
                create_phase_activation_payload(window["id"], [charter["id"]]),
                SM,
            )
        )
    ctx.update({"asset": asset, "charter": charter, "window": window,
                "permits": permits, "phase": phase})
    ctx["casualty"] = get_success_data(api_client.get_casualty(ctx["casualty"]["id"], SM))
    return ctx


def complete_phase(phase_id):
    return get_success_data(api_client.complete_phase(phase_id, SM))


def setup_completed_operation(**kwargs):
    """Running phase completed. Contract PERFORMANCE_COMPLETE; casualty
    OPERATIONS_COMPLETE (the property-disposition gate)."""
    ctx = setup_running_phase(**kwargs)
    ctx["phase"] = complete_phase(ctx["phase"]["id"])
    ctx["contract"] = get_success_data(api_client.get_contract(ctx["contract"]["id"], CO))
    ctx["casualty"] = get_success_data(api_client.get_casualty(ctx["casualty"]["id"], SM))
    return ctx


# ─── Tier 4: property, valuation, liens ───
def log_property(casualty_id, **overrides):
    return get_success_data(
        api_client.create_property(create_property_payload(casualty_id, **overrides), SM)
    )


def secure_ashore(property_id, site_id):
    return get_success_data(
        api_client.secure_ashore_property(property_id, {"storage_site_id": site_id}, SM)
    )


def survey_property(property_id, verified_value_cents, headers=None):
    return get_success_data(
        api_client.survey_property(
            property_id, {"verified_value_cents": verified_value_cents},
            headers or PROP_SURVEYOR,
        )
    )


def verify_value(property_id, headers=None):
    return get_success_data(
        api_client.verify_value_property(property_id, headers or OPS)
    )


def setup_verified_lot(ctx, quantity_tonnes=50, declared_value_cents=9_000_000,
                       verified_value_cents=None, property_type="CARGO",
                       site_capacity_tonnes=1000, secure=True):
    """Storage site + property lot surveyed and VALUE_VERIFIED.
    Ends SECURED_ASHORE x VALUE_VERIFIED (secured when secure=True)."""
    if "site" not in ctx:
        ctx["site"] = register_site(
            name=f"Yard {len(ctx)}", capacity_tonnes=site_capacity_tonnes
        )
    lot = log_property(
        ctx["casualty"]["id"], property_type=property_type,
        quantity_tonnes=quantity_tonnes, declared_value_cents=declared_value_cents,
    )
    if secure:
        lot = secure_ashore(lot["id"], ctx["site"]["id"])
    lot = survey_property(
        lot["id"],
        verified_value_cents if verified_value_cents is not None else declared_value_cents,
    )
    lot = verify_value(lot["id"])
    return lot


def setup_liened_lot(ctx, lien_amount_cents=5_000_000, **lot_kwargs):
    """Verified lot then liened. Requires casualty IN_OPERATION/OPERATIONS_COMPLETE."""
    lot = setup_verified_lot(ctx, **lot_kwargs)
    lot = get_success_data(
        api_client.lien_property(lot["id"], {"lien_amount_cents": lien_amount_cents}, CO)
    )
    return lot


# ─── Tier 5: awards, settlement, insurer documentation ───
def compute_award(contract_id):
    return get_success_data(api_client.create_award(contract_id, CO))


def setup_computed_award(lots=None, **kwargs):
    """Completed operation + verified lots + award COMPUTED.
    `lots` is a list of dicts: quantity_tonnes / declared/verified values."""
    ctx = setup_completed_operation(**kwargs)
    ctx["lots"] = []
    for spec in (lots or [{"quantity_tonnes": 50, "declared_value_cents": 200_000_000}]):
        ctx["lots"].append(setup_verified_lot(ctx, **spec))
    ctx["award"] = compute_award(ctx["contract"]["id"])
    return ctx


def open_doc_pack(contract_id):
    return get_success_data(
        api_client.create_doc_pack(create_doc_pack_payload(contract_id), SM)
    )


def add_doc_entry(pack_id, entry_type, ref_id, entry_date="2026-05-11T00:00:00Z",
                  summary="log entry"):
    return get_success_data(
        api_client.create_doc_entry(
            pack_id,
            {"entry_type": entry_type, "ref_id": ref_id,
             "entry_date": entry_date, "summary": summary},
            SM,
        )
    )


def disburse_security(security_id, mode, amount_cents):
    return get_success_data(
        api_client.disburse_security(
            security_id, create_disburse_payload(mode, amount_cents), CO
        )
    )

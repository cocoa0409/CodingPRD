"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (each test runs against a fresh server), and uses get_success_data()
so setup failures surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_abatement_payload,
    create_appeal_payload,
    create_asset_payload,
    create_class_rule_payload,
    create_client_payload,
    create_clock_payload,
    create_decision_payload,
    create_disposal_payload,
    create_exemption_application_payload,
    create_forecast_payload,
    create_hearing_payload,
    create_jurisdiction_payload,
    create_notice_payload,
    create_operator_payload,
    create_payment_schedule_payload,
    create_rendition_payload,
    create_review_payload,
    create_tax_bill_payload,
)
from .test_users import (
    TEST_USERS,
    make_client_headers,
    make_tax_analyst_headers,
    make_senior_manager_headers,
)

FIRM_ADMIN = TEST_USERS["firm_admin_headers"]
ASSESSOR_CLERK = TEST_USERS["assessor_clerk_headers"]


# ─── Primitives ───────────────────────────────────────

def create_client_account(**overrides) -> dict:
    """Onboard a client account as FirmAdmin. Returns the ClientAccount."""
    return get_success_data(api_client.create_client(create_client_payload(**overrides),
                                                     FIRM_ADMIN))


def create_operator_account(display_name: str, operator_role: str) -> dict:
    """Register an operator as FirmAdmin. Returns the Operator."""
    return get_success_data(api_client.create_operator(
        create_operator_payload(display_name=display_name, operator_role=operator_role),
        FIRM_ADMIN))


def new_analyst(display_name: str = "Ann Analyst") -> dict:
    """Create a TAX_ANALYST operator. Returns {"operator", "id", "headers"}."""
    op = create_operator_account(display_name, "TAX_ANALYST")
    return {"operator": op, "id": op["id"], "headers": make_tax_analyst_headers(op["id"])}


def new_manager(display_name: str = "Manny Manager") -> dict:
    """Create a SENIOR_MANAGER operator. Returns {"operator", "id", "headers"}."""
    op = create_operator_account(display_name, "SENIOR_MANAGER")
    return {"operator": op, "id": op["id"],
            "headers": make_senior_manager_headers(op["id"])}


def client_headers_for(client: dict) -> dict:
    """Ownership-correct Client headers for a persisted ClientAccount."""
    return make_client_headers(client["id"])


def create_jurisdiction_account(**overrides) -> dict:
    """Register a jurisdiction as FirmAdmin. Returns the Jurisdiction."""
    return get_success_data(api_client.create_jurisdiction(
        create_jurisdiction_payload(**overrides), FIRM_ADMIN))


def create_class_rule_for(jurisdiction_id: str, **overrides) -> dict:
    """Configure a class rule as FirmAdmin. Returns the JurisdictionClassRule."""
    return get_success_data(api_client.create_class_rule(
        create_class_rule_payload(jurisdiction_id, **overrides), FIRM_ADMIN))


def create_asset_for(client_id: str, jurisdiction_id: str, analyst_headers: dict,
                     **overrides) -> dict:
    """Import one asset as the given analyst. Returns the Asset."""
    return get_success_data(api_client.create_asset(
        create_asset_payload(client_id, jurisdiction_id, **overrides), analyst_headers))


def classify(asset_id: str, taxable_classification: str, analyst_headers: dict) -> dict:
    """Classify an asset. Returns the updated Asset."""
    return get_success_data(api_client.classify_asset(
        asset_id, {"taxable_classification": taxable_classification}, analyst_headers))


def open_rendition(client_id: str, jurisdiction_id: str, tax_year: int,
                   analyst_headers: dict) -> dict:
    """Open a rendition. Returns the DRAFT Rendition."""
    return get_success_data(api_client.create_rendition(
        create_rendition_payload(client_id, jurisdiction_id, tax_year), analyst_headers))


def generate(rendition_id: str, analyst_headers: dict) -> dict:
    """(Re)generate line items. Returns the updated Rendition."""
    return get_success_data(api_client.generate_lines(rendition_id, analyst_headers))


def file_it(rendition_id: str, headers: dict) -> dict:
    """File (or re-file) a rendition. Returns the FILED Rendition."""
    return get_success_data(api_client.file_rendition(rendition_id, headers))


def set_logical_clock(to_iso8601: str) -> None:
    """Advance the logical clock as FirmAdmin (runs the five compliance sweeps)."""
    get_success_data(api_client.set_clock(create_clock_payload(to_iso8601), FIRM_ADMIN))


def current_client_version(client_id: str) -> int:
    """Read the client and return its current OCC version."""
    return get_success_data(api_client.get_client(client_id, FIRM_ADMIN))["version"]


def publish_forecast(client_id: str, tax_year: int, variant: str, as_of_date: str,
                     manager_headers: dict) -> dict:
    """Publish an accrual forecast, reading the current client version for OCC."""
    version = current_client_version(client_id)
    return get_success_data(api_client.publish_forecast(
        client_id,
        create_forecast_payload(tax_year, variant, as_of_date, version),
        manager_headers))


def list_audit_events(client_id: str, headers=None) -> list:
    """Read the client's audit trail (data list only)."""
    data = get_success_data(api_client.list_client_audit_events(
        client_id, headers or FIRM_ADMIN))
    return data


# ─── Tier 1/2: scenario composites ────────────────────

def setup_classified_asset(*, jurisdiction_overrides=None, rule_overrides=None,
                           asset_overrides=None, client_overrides=None,
                           taxable_classification="TAXABLE", with_manager=False,
                           classify_asset=True) -> dict:
    """Client + analyst (+ optional manager) + jurisdiction + class rule + asset.

    With classify_asset=True the asset is classified (default TAXABLE).
    Returns a context dict: client, analyst, manager?, jurisdiction, rule, asset.
    """
    ctx = {}
    ctx["client"] = create_client_account(**(client_overrides or {}))
    ctx["analyst"] = new_analyst()
    if with_manager:
        ctx["manager"] = new_manager()
    ctx["jurisdiction"] = create_jurisdiction_account(**(jurisdiction_overrides or {}))
    ctx["rule"] = create_class_rule_for(ctx["jurisdiction"]["id"],
                                        **(rule_overrides or {}))
    ctx["asset"] = create_asset_for(ctx["client"]["id"], ctx["jurisdiction"]["id"],
                                    ctx["analyst"]["headers"],
                                    **(asset_overrides or {}))
    if classify_asset:
        ctx["asset"] = classify(ctx["asset"]["id"], taxable_classification,
                                ctx["analyst"]["headers"])
    return ctx


def setup_draft_rendition(*, tax_year: int = 2027, generate_lines: bool = True,
                          **kwargs) -> dict:
    """setup_classified_asset + an opened rendition (+ generated lines).

    Adds "rendition" to the context.
    """
    ctx = setup_classified_asset(**kwargs)
    ctx["rendition"] = open_rendition(ctx["client"]["id"], ctx["jurisdiction"]["id"],
                                      tax_year, ctx["analyst"]["headers"])
    if generate_lines:
        ctx["rendition"] = generate(ctx["rendition"]["id"], ctx["analyst"]["headers"])
    return ctx


def setup_filed_rendition(*, filer: str = "analyst", **kwargs) -> dict:
    """setup_draft_rendition + filing. filer is "analyst" or "manager"."""
    kwargs.setdefault("with_manager", True)
    ctx = setup_draft_rendition(**kwargs)
    headers = (ctx["manager"]["headers"] if filer == "manager"
               else ctx["analyst"]["headers"])
    ctx["rendition"] = file_it(ctx["rendition"]["id"], headers)
    ctx["filed_by"] = headers["X-User-ID"]
    return ctx


def setup_notice_for_filed(*, notice_overrides=None, accept: bool = False,
                           **kwargs) -> dict:
    """setup_filed_rendition + an assessment notice recorded by the clerk.

    Adds "notice". With accept=True the notice is ACCEPTED.
    """
    ctx = setup_filed_rendition(**kwargs)
    ctx["notice"] = get_success_data(api_client.create_notice(
        ctx["rendition"]["id"],
        create_notice_payload(**(notice_overrides or {})),
        ASSESSOR_CLERK))
    if accept:
        ctx["notice"] = get_success_data(api_client.accept_notice(
            ctx["notice"]["id"], ctx["analyst"]["headers"]))
    return ctx


def setup_validated_bill(*, bill_overrides=None, notice_overrides=None,
                         **kwargs) -> dict:
    """Full chain through a validated bill: filed rendition + ACCEPTED notice
    + bill imported by the analyst + validated by a (different) manager.

    Adds "notice" (ACCEPTED), "bill" (validated).
    """
    ctx = setup_notice_for_filed(notice_overrides=notice_overrides, accept=True, **kwargs)
    ctx["bill"] = get_success_data(api_client.create_tax_bill(
        ctx["notice"]["id"],
        create_tax_bill_payload(**(bill_overrides or {})),
        ctx["analyst"]["headers"]))
    ctx["bill"] = get_success_data(api_client.validate_bill(
        ctx["bill"]["id"], ctx["manager"]["headers"]))
    return ctx


def setup_decided_appeal(*, claimed_value_cents: int = 600000,
                         decided_value_cents: int = 600000,
                         decision: str = "GRANTED_REDUCTION",
                         notice_overrides=None, **kwargs) -> dict:
    """setup_filed_rendition + notice (RECEIVED) + appeal FILED ->
    HEARING_SCHEDULED -> DECIDED. Adds "notice" and "appeal".
    """
    ctx = setup_notice_for_filed(notice_overrides=notice_overrides, accept=False, **kwargs)
    ctx["appeal"] = get_success_data(api_client.create_appeal(
        ctx["notice"]["id"],
        create_appeal_payload(claimed_value_cents=claimed_value_cents),
        ctx["analyst"]["headers"]))
    ctx["appeal"] = get_success_data(api_client.schedule_hearing(
        ctx["appeal"]["id"], create_hearing_payload(), ASSESSOR_CLERK))
    ctx["appeal"] = get_success_data(api_client.record_decision(
        ctx["appeal"]["id"],
        create_decision_payload(decision=decision, decided_value_cents=decided_value_cents),
        ASSESSOR_CLERK))
    return ctx


def setup_approved_exemption(*, exemption_overrides=None, **kwargs) -> dict:
    """setup_classified_asset + a FREEPORT exemption application walked to
    APPROVED (submit by analyst, APPROVE review by clerk). Adds "exemption".
    """
    ctx = setup_classified_asset(**kwargs)
    ctx["exemption"] = get_success_data(api_client.create_exemption_application(
        ctx["asset"]["id"],
        create_exemption_application_payload(**(exemption_overrides or {})),
        ctx["analyst"]["headers"]))
    ctx["exemption"] = get_success_data(api_client.submit_exemption_application(
        ctx["exemption"]["id"], ctx["analyst"]["headers"]))
    ctx["exemption"] = get_success_data(api_client.review_exemption_application(
        ctx["exemption"]["id"], create_review_payload("APPROVE"), ASSESSOR_CLERK))
    return ctx


def setup_abated_asset(*, abatement_overrides=None, **kwargs) -> dict:
    """setup_classified_asset + an ACTIVE abatement agreement. Adds "abatement"."""
    ctx = setup_classified_asset(**kwargs)
    ctx["abatement"] = get_success_data(api_client.create_abatement(
        ctx["asset"]["id"],
        create_abatement_payload(**(abatement_overrides or {})),
        ctx["analyst"]["headers"]))
    return ctx

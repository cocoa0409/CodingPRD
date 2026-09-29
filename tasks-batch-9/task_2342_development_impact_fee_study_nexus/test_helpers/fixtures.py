"""Composite setup builders.

Each test starts against an empty service, so every precondition has to be
built through the service's own endpoints. These builders walk the statutory
lifecycle in layers: a program with its facility standards, a draft study with
priced components and schedule lines, then certification, notice, protest,
adoption and activation, and finally the collection and fund states that live
downstream of an effective study.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .constants import (
    CLOCK_ADOPTION,
    CLOCK_ASSESSMENT,
    CLOCK_EFFECTIVE_DATE,
    CLOCK_NOTICE_PUBLISHED,
    CLOCK_PAYMENT,
    CLOCK_PROGRAM_SETUP,
    CLOCK_PROTEST_WINDOW_END,
    DECISION_APPROVE_FULL,
    DEFERRAL_DECISION_EXECUTE,
    LAND_USE_SINGLE_FAMILY,
    METHODOLOGY_PLAN_BASED,
    PARKS_SINGLE_FAMILY_CONVERSION_FACTOR,
    ROADS_SINGLE_FAMILY_CONVERSION_FACTOR,
    UNIT_BASIS_PER_DWELLING,
)
from .test_users import (
    make_admin_headers,
    make_analyst_headers,
    make_clerk_headers,
    make_developer_headers,
    make_finance_headers,
    make_permit_officer_headers,
)
from .types import Headers, Payload

ADMIN = make_admin_headers()
ANALYST = make_analyst_headers()
CLERK = make_clerk_headers()
PERMIT_OFFICER = make_permit_officer_headers()
DEVELOPER = make_developer_headers()
FINANCE = make_finance_headers()


@dataclass
class Chain:
    """Identifiers produced while walking one program's statutory lifecycle."""

    program_id: str = ""
    parks_category_id: str = ""
    roads_category_id: str = ""
    study_id: str = ""
    parks_component_id: str = ""
    roads_component_id: str = ""
    parks_item_id: str = ""
    roads_item_id: str = ""
    application_id: str = ""
    component_ids: List[str] = field(default_factory=list)
    category_ids: List[str] = field(default_factory=list)
    extras: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Primitive steps
# ---------------------------------------------------------------------------
def set_clock(api: ApiClient, instant: str) -> Dict[str, Any]:
    """Move the logical clock every timestamp in this service reads."""
    return get_success_data(api.set_clock(instant))


def create_program(
    api: ApiClient, payload: Optional[Payload] = None, headers: Optional[Headers] = None
) -> Dict[str, Any]:
    body = payload if payload is not None else factories.fee_program_payload()
    return get_success_data(api.create_fee_program(body, headers or ADMIN), 201)


def program_version(api: ApiClient, program_id: str) -> int:
    return get_success_data(api.get_fee_program(program_id, ADMIN))["version"]


def application_version(api: ApiClient, application_id: str) -> int:
    return get_success_data(api.get_development_application(application_id, ADMIN))["version"]


def category_version(api: ApiClient, category_id: str) -> int:
    return get_success_data(api.get_facility_category(category_id, ADMIN))["version"]


def create_parks_category(api: ApiClient, program_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_facility_category(
            factories.parks_category_payload(program_id, **overrides), ADMIN
        ),
        201,
    )


def create_roads_category(api: ApiClient, program_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_facility_category(
            factories.roads_category_payload(program_id, **overrides), ADMIN
        ),
        201,
    )


def create_study(
    api: ApiClient,
    program_id: str,
    methodology: str = METHODOLOGY_PLAN_BASED,
    title: str = "2026 Impact Fee Study",
    headers: Optional[Headers] = None,
    **overrides,
) -> Dict[str, Any]:
    payload = factories.fee_study_payload(
        program_id,
        program_version(api, program_id),
        methodology=methodology,
        title=title,
        **overrides,
    )
    return get_success_data(api.create_fee_study(payload, headers or ANALYST), 201)


def create_parks_component(
    api: ApiClient, study_id: str, category_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_nexus_component(
            factories.parks_component_payload(study_id, category_id, **overrides), ANALYST
        ),
        201,
    )


def create_roads_component(
    api: ApiClient, study_id: str, category_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_nexus_component(
            factories.roads_component_payload(study_id, category_id, **overrides), ANALYST
        ),
        201,
    )


def allocate(api: ApiClient, component_id: str) -> Dict[str, Any]:
    return get_success_data(api.allocate_nexus_component(component_id, ANALYST))


def add_schedule_line(
    api: ApiClient,
    component_id: str,
    conversion_factor: float,
    land_use_category: str = LAND_USE_SINGLE_FAMILY,
    unit_basis: str = UNIT_BASIS_PER_DWELLING,
) -> Dict[str, Any]:
    payload = factories.schedule_item_payload(
        land_use_category=land_use_category,
        unit_basis=unit_basis,
        conversion_factor=conversion_factor,
    )
    return get_success_data(api.create_fee_schedule_item(component_id, payload, ANALYST), 201)


# ---------------------------------------------------------------------------
# Layer one: a program with its adopted facility standards
# ---------------------------------------------------------------------------
def program_with_categories(
    api: ApiClient,
    clock: Optional[str] = CLOCK_PROGRAM_SETUP,
    program_payload: Optional[Payload] = None,
    with_roads: bool = True,
) -> Chain:
    """A fee program plus the parks (and optionally roads) facility standards."""
    if clock is not None:
        set_clock(api, clock)
    program = create_program(api, program_payload)
    chain = Chain(program_id=program["id"])
    parks = create_parks_category(api, chain.program_id)
    chain.parks_category_id = parks["id"]
    chain.category_ids.append(parks["id"])
    if with_roads:
        roads = create_roads_category(api, chain.program_id)
        chain.roads_category_id = roads["id"]
        chain.category_ids.append(roads["id"])
    return chain


# ---------------------------------------------------------------------------
# Layer two: a draft study whose components are allocated and priced
# ---------------------------------------------------------------------------
def draft_study_with_priced_components(
    api: ApiClient,
    chain: Chain,
    methodology: str = METHODOLOGY_PLAN_BASED,
    title: str = "2026 Impact Fee Study",
    parks_overrides: Optional[Payload] = None,
    roads_overrides: Optional[Payload] = None,
    with_roads: Optional[bool] = None,
) -> Chain:
    """Open a draft study, add one component per standard, allocate both and
    adopt a single-family schedule line on each."""
    study = create_study(api, chain.program_id, methodology=methodology, title=title)
    chain.study_id = study["id"]

    parks_component = create_parks_component(
        api, chain.study_id, chain.parks_category_id, **(parks_overrides or {})
    )
    chain.parks_component_id = parks_component["id"]
    chain.component_ids.append(parks_component["id"])
    allocate(api, chain.parks_component_id)
    chain.parks_item_id = add_schedule_line(
        api, chain.parks_component_id, PARKS_SINGLE_FAMILY_CONVERSION_FACTOR
    )["id"]

    include_roads = chain.roads_category_id != "" if with_roads is None else with_roads
    if include_roads and chain.roads_category_id:
        roads_component = create_roads_component(
            api, chain.study_id, chain.roads_category_id, **(roads_overrides or {})
        )
        chain.roads_component_id = roads_component["id"]
        chain.component_ids.append(roads_component["id"])
        allocate(api, chain.roads_component_id)
        chain.roads_item_id = add_schedule_line(
            api, chain.roads_component_id, ROADS_SINGLE_FAMILY_CONVERSION_FACTOR
        )["id"]
    return chain


def draft_program(
    api: ApiClient,
    methodology: str = METHODOLOGY_PLAN_BASED,
    program_payload: Optional[Payload] = None,
    with_roads: bool = True,
    clock: Optional[str] = CLOCK_PROGRAM_SETUP,
) -> Chain:
    """A program whose single draft study is fully priced and ready to certify."""
    chain = program_with_categories(
        api, clock=clock, program_payload=program_payload, with_roads=with_roads
    )
    return draft_study_with_priced_components(api, chain, methodology=methodology)


# ---------------------------------------------------------------------------
# Layer three: the legislative lifecycle
# ---------------------------------------------------------------------------
def certify(api: ApiClient, study_id: str, headers: Optional[Headers] = None) -> Dict[str, Any]:
    return get_success_data(api.certify_nexus(study_id, headers or ANALYST))


def publish_notice(
    api: ApiClient,
    study_id: str,
    notice_days: int = 30,
    notice_method: str = "NEWSPAPER",
    headers: Optional[Headers] = None,
) -> Dict[str, Any]:
    payload = factories.notice_payload(notice_method=notice_method, notice_days=notice_days)
    return get_success_data(api.publish_notice(study_id, payload, headers or CLERK))


def record_protest(api: ApiClient, study_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_protest_filing(study_id, factories.protest_filing_payload(**overrides), CLERK),
        201,
    )


def close_protest_window(
    api: ApiClient, study_id: str, headers: Optional[Headers] = None
) -> Dict[str, Any]:
    return get_success_data(api.close_protest_window(study_id, headers or CLERK))


def adopt(api: ApiClient, study_id: str, headers: Optional[Headers] = None) -> Dict[str, Any]:
    return get_success_data(api.adopt_fee_study(study_id, headers or CLERK))


def activate(api: ApiClient, study_id: str, headers: Optional[Headers] = None) -> Dict[str, Any]:
    return get_success_data(api.activate_fee_study(study_id, headers or ADMIN))


def certified_program(
    api: ApiClient,
    methodology: str = METHODOLOGY_PLAN_BASED,
    program_payload: Optional[Payload] = None,
    with_roads: bool = True,
    certifier: Optional[Headers] = None,
) -> Chain:
    """A program whose study has been certified but not yet noticed."""
    chain = draft_program(
        api, methodology=methodology, program_payload=program_payload, with_roads=with_roads
    )
    certify(api, chain.study_id, certifier)
    return chain


def noticed_program(
    api: ApiClient,
    methodology: str = METHODOLOGY_PLAN_BASED,
    program_payload: Optional[Payload] = None,
    with_roads: bool = True,
    notice_days: int = 30,
    certifier: Optional[Headers] = None,
) -> Chain:
    """A program whose certified study is inside its statutory notice window."""
    chain = certified_program(
        api,
        methodology=methodology,
        program_payload=program_payload,
        with_roads=with_roads,
        certifier=certifier,
    )
    set_clock(api, CLOCK_NOTICE_PUBLISHED)
    publish_notice(api, chain.study_id, notice_days=notice_days)
    return chain


def protest_cleared_program(
    api: ApiClient,
    methodology: str = METHODOLOGY_PLAN_BASED,
    program_payload: Optional[Payload] = None,
    with_roads: bool = True,
    certifier: Optional[Headers] = None,
) -> Chain:
    """A program whose study has come through its protest window uncontested."""
    chain = noticed_program(
        api,
        methodology=methodology,
        program_payload=program_payload,
        with_roads=with_roads,
        certifier=certifier,
    )
    set_clock(api, CLOCK_PROTEST_WINDOW_END)
    close_protest_window(api, chain.study_id)
    return chain


def adopted_program(
    api: ApiClient,
    methodology: str = METHODOLOGY_PLAN_BASED,
    program_payload: Optional[Payload] = None,
    with_roads: bool = True,
    certifier: Optional[Headers] = None,
    adopter: Optional[Headers] = None,
) -> Chain:
    """A program whose study is adopted with its effective date fixed."""
    chain = protest_cleared_program(
        api,
        methodology=methodology,
        program_payload=program_payload,
        with_roads=with_roads,
        certifier=certifier,
    )
    set_clock(api, CLOCK_ADOPTION)
    adopt(api, chain.study_id, adopter)
    return chain


def effective_program(
    api: ApiClient,
    methodology: str = METHODOLOGY_PLAN_BASED,
    program_payload: Optional[Payload] = None,
    with_roads: bool = True,
) -> Chain:
    """A program with exactly one study in status EFFECTIVE, priced for a
    single-family land use on every facility standard it carries."""
    chain = adopted_program(
        api, methodology=methodology, program_payload=program_payload, with_roads=with_roads
    )
    set_clock(api, CLOCK_EFFECTIVE_DATE)
    activate(api, chain.study_id)
    return chain


# ---------------------------------------------------------------------------
# Layer four: applications, assessment and collection
# ---------------------------------------------------------------------------
def file_application(
    api: ApiClient, program_id: str, headers: Optional[Headers] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_development_application(
            factories.development_application_payload(program_id, **overrides),
            headers or DEVELOPER,
        ),
        201,
    )


def assess(api: ApiClient, application_id: str, headers: Optional[Headers] = None) -> Dict[str, Any]:
    return get_success_data(api.assess_application(application_id, headers or PERMIT_OFFICER))


def pay(
    api: ApiClient, application_id: str, amount_cents: int, headers: Optional[Headers] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.create_payment(
            application_id, factories.payment_payload(amount_cents), headers or PERMIT_OFFICER
        )
    )


def assessed_application(
    api: ApiClient,
    chain: Optional[Chain] = None,
    clock: Optional[str] = CLOCK_ASSESSMENT,
    application_overrides: Optional[Payload] = None,
    **program_kwargs,
) -> Dict[str, Any]:
    """An effective program with one filed, priced application. Returns the
    assessed application body; the chain carries the identifiers."""
    if chain is None:
        chain = effective_program(api, **program_kwargs)
    application = file_application(
        api, chain.program_id, **(application_overrides or {})
    )
    chain.application_id = application["id"]
    if clock is not None:
        set_clock(api, clock)
    assessed = assess(api, chain.application_id)
    chain.extras["chain"] = chain
    return assessed


def paid_application(
    api: ApiClient,
    chain: Chain,
    clock: Optional[str] = CLOCK_PAYMENT,
    amount_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """Settle an assessed application's balance exactly, opening its fund rows."""
    if clock is not None:
        set_clock(api, clock)
    current = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    due = current["net_due_cents"] - current["paid_cents"] if amount_cents is None else amount_cents
    return pay(api, chain.application_id, due)


def effective_program_with_paid_application(
    api: ApiClient, **program_kwargs
) -> Chain:
    """The canonical end-to-end state: one effective study, one assessed and
    fully paid application, and one COLLECTION row per assessed line."""
    chain = effective_program(api, **program_kwargs)
    assessed_application(api, chain)
    paid_application(api, chain)
    return chain


# ---------------------------------------------------------------------------
# Layer five: credit claims, deferrals and the fund ledger
# ---------------------------------------------------------------------------
def file_credit_claim(
    api: ApiClient, application_id: str, headers: Optional[Headers] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_credit_claim(
            application_id, factories.credit_claim_payload(**overrides), headers or DEVELOPER
        ),
        201,
    )


def decide_credit_claim(
    api: ApiClient,
    claim_id: str,
    application_id: str,
    decision: str = DECISION_APPROVE_FULL,
    approved_cents: Optional[int] = None,
    headers: Optional[Headers] = None,
) -> Dict[str, Any]:
    payload = factories.credit_decision_payload(
        application_version(api, application_id),
        decision=decision,
        approved_cents=approved_cents,
    )
    return get_success_data(api.decide_credit_claim(claim_id, payload, headers or ANALYST))


def request_deferral(
    api: ApiClient,
    application_id: str,
    security_amount_cents: int,
    requested_due_at: str,
    headers: Optional[Headers] = None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_deferral_agreement(
            application_id,
            factories.deferral_agreement_payload(
                security_amount_cents, requested_due_at, **overrides
            ),
            headers or DEVELOPER,
        ),
        201,
    )


def decide_deferral(
    api: ApiClient,
    agreement_id: str,
    decision: str = DEFERRAL_DECISION_EXECUTE,
    headers: Optional[Headers] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.decide_deferral_agreement(
            agreement_id, factories.deferral_decision_payload(decision), headers or PERMIT_OFFICER
        )
    )


def spend(
    api: ApiClient,
    category_id: str,
    amount_cents: int,
    project_name: str = "Harborview Park Phase One",
    headers: Optional[Headers] = None,
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    version = category_version(api, category_id) if expected_version is None else expected_version
    payload = factories.expenditure_payload(amount_cents, version, project_name=project_name)
    return get_success_data(api.create_expenditure(category_id, payload, headers or FINANCE), 201)


def refund(
    api: ApiClient, entry_id: str, headers: Optional[Headers] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.refund_ledger_entry(entry_id, headers or FINANCE, factories.refund_payload(**overrides)),
        201,
    )


def sweep(api: ApiClient, program_id: str, headers: Optional[Headers] = None) -> Dict[str, Any]:
    return get_success_data(api.run_deadline_sweep(program_id, headers or ADMIN))


def ledger_rows(api: ApiClient, params: Optional[Payload] = None) -> List[Dict[str, Any]]:
    """Every ledger row matching the filters, in the service's own ledger order."""
    query: Payload = {"limit": 100}
    query.update(params or {})
    return api.list_fund_ledger_entries(ADMIN, query).json()["data"]


def collection_rows_for(
    api: ApiClient, category_id: str
) -> List[Dict[str, Any]]:
    """The COLLECTION rows of one facility category, in ledger order."""
    response = api.list_fund_ledger_entries(
        ADMIN, {"facility_category_id": category_id, "kind": "COLLECTION", "limit": 100}
    )
    return response.json()["data"]


def rows_of_kind(api: ApiClient, kind: str, **filters) -> List[Dict[str, Any]]:
    params: Payload = {"kind": kind, "limit": 100}
    params.update(filters)
    return api.list_fund_ledger_entries(ADMIN, params).json()["data"]

"""Composite scenario builders.

Every test starts against an empty database, so each precondition has to be
built from scratch through documented endpoints. These builders walk the
statutory ladder step by step and thread the correct actor identity at every
call: a `MunicipalPlanner` and a `CityClerk` carry the acting municipality's
`id`, and a `PropertyOwner` carries their own `id`.

Each builder takes and returns a mutable ``ctx`` dictionary so that a test can
stop at any rung of the ladder and inspect what it has.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .api_client import AnnexationApiClient
from .test_users import (
    boundary_commissioner_headers,
    county_assessor_headers,
    fiscal_analyst_headers,
    make_city_clerk_headers,
    make_municipal_planner_headers,
    make_property_owner_headers,
    state_law_admin_headers,
)


# ==========================================================================
# Primitive builders
# ==========================================================================
def set_clock(api: AnnexationApiClient, to_iso8601: str) -> str:
    data = get_success_data(api.set_clock(state_law_admin_headers(), to_iso8601))
    return data["current_utc"]


def create_statute(api: AnnexationApiClient, **overrides: Any) -> Dict[str, Any]:
    payload = F.statute_profile_payload(**overrides)
    return get_success_data(
        api.create_statute_profile(state_law_admin_headers(), payload), 201
    )


def create_municipality(
    api: AnnexationApiClient, statute_profile_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Register a city under a statute profile.

    A city's `state_code` must equal the referenced profile's `state_code`, so
    unless a test overrides it deliberately the code is read back off the
    profile rather than guessed.
    """
    if "state_code" not in overrides:
        profile = get_success_data(
            api.get_statute_profile(state_law_admin_headers(), statute_profile_id)
        )
        overrides["state_code"] = profile["state_code"]
    payload = F.municipality_payload(statute_profile_id, **overrides)
    return get_success_data(api.create_municipality(state_law_admin_headers(), payload), 201)


def create_provider(
    api: AnnexationApiClient, municipality_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = F.service_provider_payload(**overrides)
    return get_success_data(
        api.create_service_provider(
            make_municipal_planner_headers(municipality_id), municipality_id, payload
        ),
        201,
    )


def create_owner(api: AnnexationApiClient, **overrides: Any) -> Dict[str, Any]:
    payload = F.property_owner_payload(**overrides)
    return get_success_data(api.create_property_owner(state_law_admin_headers(), payload), 201)


def create_case(
    api: AnnexationApiClient, municipality_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = F.annexation_case_payload(municipality_id, **overrides)
    return get_success_data(
        api.create_annexation_case(make_municipal_planner_headers(municipality_id), payload),
        201,
    )


def add_parcel(
    api: AnnexationApiClient,
    municipality_id: str,
    case_id: str,
    primary_owner_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = F.parcel_payload(primary_owner_id, **overrides)
    return get_success_data(
        api.create_parcel(
            make_municipal_planner_headers(municipality_id), case_id, payload
        ),
        201,
    )


def add_utility_account(
    api: AnnexationApiClient,
    municipality_id: str,
    parcel_id: str,
    service_provider_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = F.utility_account_payload(parcel_id, service_provider_id, **overrides)
    return get_success_data(
        api.create_utility_account(make_municipal_planner_headers(municipality_id), payload),
        201,
    )


def read_case(api: AnnexationApiClient, municipality_id: str, case_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_annexation_case(make_municipal_planner_headers(municipality_id), case_id)
    )


def read_plan(api: AnnexationApiClient, municipality_id: str, plan_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_plan_of_services(make_municipal_planner_headers(municipality_id), plan_id)
    )


def read_parcel(api: AnnexationApiClient, municipality_id: str, parcel_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_parcel(make_municipal_planner_headers(municipality_id), parcel_id)
    )


def read_account(
    api: AnnexationApiClient, municipality_id: str, utility_account_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.get_utility_account(
            make_municipal_planner_headers(municipality_id), utility_account_id
        )
    )


def read_provider(
    api: AnnexationApiClient, municipality_id: str, service_provider_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.get_service_provider(
            make_municipal_planner_headers(municipality_id), service_provider_id
        )
    )


def read_hearing(
    api: AnnexationApiClient, municipality_id: str, hearing_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.get_public_hearing(make_city_clerk_headers(municipality_id), hearing_id)
    )


def read_petition(
    api: AnnexationApiClient, municipality_id: str, petition_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.get_petition(make_city_clerk_headers(municipality_id), petition_id)
    )


def read_commitment(
    api: AnnexationApiClient, municipality_id: str, commitment_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.get_service_commitment(
            make_municipal_planner_headers(municipality_id), commitment_id
        )
    )


def read_municipality(api: AnnexationApiClient, municipality_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_municipality(state_law_admin_headers(), municipality_id)
    )


# ==========================================================================
# Context helpers
# ==========================================================================
def planner(ctx: Dict[str, Any]) -> Dict[str, str]:
    return make_municipal_planner_headers(ctx["municipality"]["id"])


def clerk(ctx: Dict[str, Any]) -> Dict[str, str]:
    return make_city_clerk_headers(ctx["municipality"]["id"])


def owner_headers(ctx: Dict[str, Any], index: int = 0) -> Dict[str, str]:
    return make_property_owner_headers(ctx["owners"][index]["id"])


def case_version(api: AnnexationApiClient, ctx: Dict[str, Any]) -> int:
    return read_case(api, ctx["municipality"]["id"], ctx["case"]["id"])["version"]


def plan_version(api: AnnexationApiClient, ctx: Dict[str, Any]) -> int:
    return read_plan(api, ctx["municipality"]["id"], ctx["plan"]["id"])["version"]


def refresh_case(api: AnnexationApiClient, ctx: Dict[str, Any]) -> Dict[str, Any]:
    ctx["case"] = read_case(api, ctx["municipality"]["id"], ctx["case"]["id"])
    return ctx["case"]


def refresh_plan(api: AnnexationApiClient, ctx: Dict[str, Any]) -> Dict[str, Any]:
    ctx["plan"] = read_plan(api, ctx["municipality"]["id"], ctx["plan"]["id"])
    return ctx["plan"]


# ==========================================================================
# Composite: jurisdiction
# ==========================================================================
def setup_jurisdiction(
    api: AnnexationApiClient,
    statute: Optional[Dict[str, Any]] = None,
    municipality: Optional[Dict[str, Any]] = None,
    provider: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A statute profile, a municipality bound to it, and one service provider
    offering all four service types."""
    statute_record = create_statute(api, **(statute or {}))
    municipality_record = create_municipality(
        api, statute_record["id"], **(municipality or {})
    )
    provider_record = create_provider(
        api, municipality_record["id"], **(provider or {})
    )
    return {
        "statute": statute_record,
        "municipality": municipality_record,
        "provider": provider_record,
        "planner_headers": make_municipal_planner_headers(municipality_record["id"]),
        "clerk_headers": make_city_clerk_headers(municipality_record["id"]),
        "admin_headers": state_law_admin_headers(),
        "analyst_headers": fiscal_analyst_headers(),
        "commissioner_headers": boundary_commissioner_headers(),
        "assessor_headers": county_assessor_headers(),
    }


# ==========================================================================
# Composite: a DRAFT case with territory
# ==========================================================================
def setup_draft_case(
    api: AnnexationApiClient,
    statute: Optional[Dict[str, Any]] = None,
    municipality: Optional[Dict[str, Any]] = None,
    provider: Optional[Dict[str, Any]] = None,
    case: Optional[Dict[str, Any]] = None,
    parcel_count: int = 4,
    parcel_values_cents: Optional[List[int]] = None,
    parcel_overrides: Optional[Dict[str, Any]] = None,
    owners_per_parcel: bool = True,
) -> Dict[str, Any]:
    """A `DRAFT` case whose parcels sum to a territory that passes all three
    statutory tests under the default statute."""
    ctx = setup_jurisdiction(api, statute, municipality, provider)
    ctx["case"] = create_case(api, ctx["municipality"]["id"], **(case or {}))

    values = parcel_values_cents or [25000000] * parcel_count
    owners: List[Dict[str, Any]] = []
    parcels: List[Dict[str, Any]] = []
    shared_owner = None
    for value in values:
        if owners_per_parcel:
            owner = create_owner(api)
        else:
            shared_owner = shared_owner or create_owner(api)
            owner = shared_owner
        owners.append(owner)
        overrides: Dict[str, Any] = {"assessed_value_cents": value}
        overrides.update(parcel_overrides or {})
        parcels.append(
            add_parcel(
                api,
                ctx["municipality"]["id"],
                ctx["case"]["id"],
                owner["id"],
                **overrides,
            )
        )
    ctx["owners"] = owners
    ctx["parcels"] = parcels
    refresh_case(api, ctx)
    return ctx


# ==========================================================================
# Composite: a certified territory
# ==========================================================================
def setup_certified_case(api: AnnexationApiClient, **kwargs: Any) -> Dict[str, Any]:
    ctx = kwargs.pop("ctx", None) or setup_draft_case(api, **kwargs)
    ctx["case"] = get_success_data(
        api.certify_territory(planner(ctx), ctx["case"]["id"])
    )
    ctx["parcels"] = [
        read_parcel(api, ctx["municipality"]["id"], p["id"]) for p in ctx["parcels"]
    ]
    return ctx


# ==========================================================================
# Composite: the petition limb
# ==========================================================================
def open_petition(
    api: AnnexationApiClient, ctx: Dict[str, Any], **overrides: Any
) -> Dict[str, Any]:
    payload = F.petition_payload(ctx["case"]["id"], **overrides)
    ctx["petition"] = get_success_data(api.create_petition(planner(ctx), payload), 201)
    return ctx["petition"]


def sign_consent(
    api: AnnexationApiClient,
    ctx: Dict[str, Any],
    parcel_index: int = 0,
    owner_index: Optional[int] = None,
    ownership_share_pct: float = 100.00,
    as_clerk: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    parcel = ctx["parcels"][parcel_index]
    owner = ctx["owners"][parcel_index if owner_index is None else owner_index]
    payload = F.consent_payload(
        ctx["petition"]["id"], parcel["id"], owner["id"], ownership_share_pct, **overrides
    )
    headers = clerk(ctx) if as_clerk else make_property_owner_headers(owner["id"])
    return get_success_data(api.create_consent(headers, payload), 201)


def setup_sufficient_petition(
    api: AnnexationApiClient,
    petition_type: str = "OWNER_MAJORITY",
    **kwargs: Any,
) -> Dict[str, Any]:
    """A certified petition-method case whose petition has been signed by every
    owner and certified `SUFFICIENT`, leaving the case in
    `SUFFICIENCY_REVIEW`."""
    case_overrides = kwargs.pop("case", None) or {}
    case_overrides.setdefault("method", "PETITION_MAJORITY")
    ctx = setup_certified_case(api, case=case_overrides, **kwargs)
    open_petition(api, ctx, petition_type=petition_type)
    ctx["consents"] = [
        sign_consent(api, ctx, parcel_index=i) for i in range(len(ctx["parcels"]))
    ]
    ctx["petition"] = get_success_data(
        api.certify_sufficiency(clerk(ctx), ctx["petition"]["id"])
    )
    refresh_case(api, ctx)
    return ctx


# ==========================================================================
# Composite: the plan of services
# ==========================================================================
def open_plan(api: AnnexationApiClient, ctx: Dict[str, Any]) -> Dict[str, Any]:
    payload = F.plan_of_services_payload(ctx["case"]["id"])
    ctx["plan"] = get_success_data(api.create_plan_of_services(planner(ctx), payload), 201)
    return ctx["plan"]


def add_commitment(
    api: AnnexationApiClient,
    ctx: Dict[str, Any],
    service_type: str,
    service_provider_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = F.service_commitment_payload(
        ctx["plan"]["id"],
        service_provider_id or ctx["provider"]["id"],
        service_type,
        plan_version(api, ctx),
        **overrides,
    )
    return get_success_data(api.create_service_commitment(planner(ctx), payload), 201)


def activate_commitment(
    api: AnnexationApiClient, ctx: Dict[str, Any], commitment_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.activate_service_commitment(planner(ctx), commitment_id)
    )


def setup_adopted_plan(
    api: AnnexationApiClient,
    ctx: Dict[str, Any],
    service_types: Optional[List[str]] = None,
    account_counts: Optional[Dict[str, int]] = None,
    cost_cents: int = 100000,
    window_start_date: str = C.COMMITMENT_WINDOW_START,
    window_end_date: str = C.COMMITMENT_WINDOW_END,
) -> Dict[str, Any]:
    """Open a plan, commit and activate one commitment per required service
    type, then have the clerk adopt it."""
    open_plan(api, ctx)
    types = service_types or list(
        ctx["statute"].get("required_service_types", C.DEFAULT_REQUIRED_SERVICE_TYPES)
    )
    commitments: Dict[str, Dict[str, Any]] = {}
    for service_type in types:
        overrides: Dict[str, Any] = {
            "cost_cents": cost_cents,
            "window_start_date": window_start_date,
            "window_end_date": window_end_date,
        }
        if account_counts and service_type in account_counts:
            overrides["committed_account_count"] = account_counts[service_type]
        commitment = add_commitment(api, ctx, service_type, **overrides)
        commitments[service_type] = activate_commitment(api, ctx, commitment["id"])
    ctx["commitments"] = commitments
    ctx["plan"] = get_success_data(
        api.adopt_plan_of_services(clerk(ctx), ctx["plan"]["id"])
    )
    refresh_case(api, ctx)
    return ctx


# ==========================================================================
# Composite: notice, hearing, protest
# ==========================================================================
def schedule_hearing(
    api: AnnexationApiClient, ctx: Dict[str, Any], **overrides: Any
) -> Dict[str, Any]:
    payload = F.public_hearing_payload(
        ctx["case"]["id"], ctx["municipality"]["id"], **overrides
    )
    ctx["hearing"] = get_success_data(api.create_public_hearing(clerk(ctx), payload), 201)
    return ctx["hearing"]


def publish_notice(
    api: AnnexationApiClient,
    ctx: Dict[str, Any],
    publication_type: str = "NEWSPAPER",
    hearing_id: Optional[str] = None,
) -> Dict[str, Any]:
    notice = get_success_data(
        api.publish_notice(
            clerk(ctx), hearing_id or ctx["hearing"]["id"], publication_type
        ),
        201,
    )
    ctx.setdefault("notices", []).append(notice)
    return notice


def setup_hearing_noticed(
    api: AnnexationApiClient, ctx: Dict[str, Any], **hearing_overrides: Any
) -> Dict[str, Any]:
    """Schedule a hearing and publish statutory notice, advancing the case to
    `HEARING_NOTICED`."""
    schedule_hearing(api, ctx, **hearing_overrides)
    publish_notice(api, ctx)
    ctx["hearing"] = read_hearing(api, ctx["municipality"]["id"], ctx["hearing"]["id"])
    refresh_case(api, ctx)
    return ctx


def setup_hearing_held(
    api: AnnexationApiClient,
    ctx: Dict[str, Any],
    clock_at_hearing: str = C.CLOCK_AT_HEARING,
) -> Dict[str, Any]:
    """Move the clock to the hearing's start and hold it, which opens the
    written-objection window."""
    set_clock(api, clock_at_hearing)
    ctx["hearing"] = get_success_data(api.hold_hearing(clerk(ctx), ctx["hearing"]["id"]))
    refresh_case(api, ctx)
    return ctx


def file_protest(
    api: AnnexationApiClient,
    ctx: Dict[str, Any],
    parcel_index: int = 0,
    owner_index: Optional[int] = None,
    ownership_share_pct: float = 100.00,
    as_clerk: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    parcel = ctx["parcels"][parcel_index]
    owner = ctx["owners"][parcel_index if owner_index is None else owner_index]
    payload = F.protest_filing_payload(
        ctx["hearing"]["id"], parcel["id"], owner["id"], ownership_share_pct, **overrides
    )
    headers = clerk(ctx) if as_clerk else make_property_owner_headers(owner["id"])
    filing = get_success_data(api.create_protest_filing(headers, payload), 201)
    ctx.setdefault("filings", []).append(filing)
    return filing


def close_protest_period(
    api: AnnexationApiClient,
    ctx: Dict[str, Any],
    clock_after_window: str = C.CLOCK_AFTER_PROTEST_WINDOW,
) -> Dict[str, Any]:
    """Move the clock strictly past the close instant and tabulate."""
    set_clock(api, clock_after_window)
    ctx["hearing"] = get_success_data(
        api.close_protest_period(clerk(ctx), ctx["hearing"]["id"])
    )
    refresh_case(api, ctx)
    return ctx


# ==========================================================================
# Composite: the fiscal analysis of record
# ==========================================================================
def author_analysis(
    api: AnnexationApiClient,
    ctx: Dict[str, Any],
    analysis_method: str = "AVERAGE_COST",
    projected_population: int = 0,
    analyst_user_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = F.fiscal_analysis_payload(
        ctx["case"]["id"],
        case_version(api, ctx),
        analysis_method=analysis_method,
        projected_population=projected_population,
        **overrides,
    )
    headers = fiscal_analyst_headers(analyst_user_id) if analyst_user_id else fiscal_analyst_headers()
    ctx["analysis"] = get_success_data(
        api.create_fiscal_impact_analysis(headers, payload), 201
    )
    return ctx["analysis"]


def finalize_analysis(
    api: AnnexationApiClient,
    ctx: Dict[str, Any],
    analyst_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    headers = fiscal_analyst_headers(analyst_user_id) if analyst_user_id else fiscal_analyst_headers()
    ctx["analysis"] = get_success_data(
        api.finalize_fiscal_impact_analysis(headers, ctx["analysis"]["id"])
    )
    refresh_case(api, ctx)
    return ctx["analysis"]


def setup_finalized_analysis(
    api: AnnexationApiClient,
    ctx: Dict[str, Any],
    analysis_method: str = "AVERAGE_COST",
    projected_population: int = 0,
    analyst_user_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    author_analysis(
        api,
        ctx,
        analysis_method=analysis_method,
        projected_population=projected_population,
        analyst_user_id=analyst_user_id,
        **overrides,
    )
    finalize_analysis(api, ctx, analyst_user_id=analyst_user_id)
    return ctx


# ==========================================================================
# Composite: the full ladder to an adoptable, effectuable case
# ==========================================================================
def setup_case_ready_for_ordinance(
    api: AnnexationApiClient,
    method: str = "INVOLUNTARY_ORDINANCE",
    statute: Optional[Dict[str, Any]] = None,
    municipality: Optional[Dict[str, Any]] = None,
    provider: Optional[Dict[str, Any]] = None,
    case: Optional[Dict[str, Any]] = None,
    parcel_count: int = 4,
    parcel_values_cents: Optional[List[int]] = None,
    account_counts: Optional[Dict[str, int]] = None,
    analysis_method: str = "AVERAGE_COST",
    projected_population: int = 0,
    analyst_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Certify territory, adopt a plan, notice and hold the hearing, let the
    protest window close with no objections, and finalize a surplus analysis.

    The result is a case in `HEARING_HELD` with `protest_outcome` `FAILED`, an
    `ADOPTED` plan and a `FINALIZED` analysis — every precondition of ordinance
    adoption satisfied.
    """
    case_overrides = dict(case or {})
    case_overrides.setdefault("method", method)
    ctx = setup_certified_case(
        api,
        statute=statute,
        municipality=municipality,
        provider=provider,
        case=case_overrides,
        parcel_count=parcel_count,
        parcel_values_cents=parcel_values_cents,
    )
    setup_adopted_plan(api, ctx, account_counts=account_counts)
    setup_hearing_noticed(api, ctx)
    setup_hearing_held(api, ctx)
    close_protest_period(api, ctx)
    setup_finalized_analysis(
        api,
        ctx,
        analysis_method=analysis_method,
        projected_population=projected_population,
        analyst_user_id=analyst_user_id,
    )
    return ctx


def adopt_ordinance(api: AnnexationApiClient, ctx: Dict[str, Any]) -> Dict[str, Any]:
    ctx["case"] = get_success_data(api.adopt_ordinance(clerk(ctx), ctx["case"]["id"]))
    return ctx["case"]


def setup_case_ordinance_adopted(api: AnnexationApiClient, **kwargs: Any) -> Dict[str, Any]:
    ctx = kwargs.pop("ctx", None) or setup_case_ready_for_ordinance(api, **kwargs)
    adopt_ordinance(api, ctx)
    return ctx


def effectuate(
    api: AnnexationApiClient,
    ctx: Dict[str, Any],
    effective_date: str = C.EFFECTIVE_DATE_AFTER_PROTEST,
) -> Dict[str, Any]:
    ctx["case"] = get_success_data(
        api.effectuate(planner(ctx), ctx["case"]["id"], effective_date)
    )
    return ctx["case"]


def setup_effective_case(
    api: AnnexationApiClient,
    effective_date: str = C.EFFECTIVE_DATE_AFTER_PROTEST,
    **kwargs: Any,
) -> Dict[str, Any]:
    ctx = kwargs.pop("ctx", None) or setup_case_ordinance_adopted(api, **kwargs)
    effectuate(api, ctx, effective_date)
    return ctx


def post_tax_roll(api: AnnexationApiClient, ctx: Dict[str, Any]) -> Dict[str, Any]:
    ctx["case"] = get_success_data(
        api.post_tax_roll(county_assessor_headers(), ctx["case"]["id"])
    )
    return ctx["case"]


def setup_posted_tax_roll(api: AnnexationApiClient, **kwargs: Any) -> Dict[str, Any]:
    ctx = kwargs.pop("ctx", None) or setup_effective_case(api, **kwargs)
    post_tax_roll(api, ctx)
    return ctx


# ==========================================================================
# Composite: a case defeated by protest
# ==========================================================================
def setup_protest_sustained_case(
    api: AnnexationApiClient,
    parcel_count: int = 4,
    protesting_parcels: int = 4,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Every owner in the territory objects, so the tabulation carries the
    protest and the case lands in `PROTEST_SUSTAINED`."""
    case_overrides = kwargs.pop("case", None) or {}
    case_overrides.setdefault("method", "INVOLUNTARY_ORDINANCE")
    ctx = setup_certified_case(
        api, case=case_overrides, parcel_count=parcel_count, **kwargs
    )
    setup_adopted_plan(api, ctx)
    setup_hearing_noticed(api, ctx)
    setup_hearing_held(api, ctx)
    set_clock(api, C.CLOCK_DURING_PROTEST_WINDOW)
    for index in range(protesting_parcels):
        file_protest(api, ctx, parcel_index=index)
    close_protest_period(api, ctx)
    return ctx


# ==========================================================================
# Composite: a de-annexation successor over an effective predecessor
# ==========================================================================
def setup_de_annexation_case(
    api: AnnexationApiClient,
    ctx: Dict[str, Any],
    method: str = "INVOLUNTARY_ORDINANCE",
) -> Dict[str, Any]:
    """Open a successor case that unwinds `ctx["case"]`, carry it to
    `HEARING_HELD` with a failed protest, an adopted plan and a finalized
    analysis, and adopt its ordinance."""
    predecessor = ctx["case"]
    successor: Dict[str, Any] = {
        "statute": ctx["statute"],
        "municipality": ctx["municipality"],
        "provider": ctx["provider"],
        "owners": ctx["owners"],
        "parcels": [],
        "predecessor": predecessor,
    }
    payload = F.de_annexation_case_payload(
        ctx["municipality"]["id"], predecessor["id"], method=method
    )
    successor["case"] = get_success_data(
        api.create_annexation_case(planner(successor), payload), 201
    )
    successor["case"] = get_success_data(
        api.certify_territory(planner(successor), successor["case"]["id"])
    )
    setup_adopted_plan(
        api,
        successor,
        window_start_date=C.DE_ANNEXATION_COMMITMENT_WINDOW_START,
        window_end_date=C.DE_ANNEXATION_COMMITMENT_WINDOW_END,
    )
    setup_hearing_noticed(
        api,
        successor,
        scheduled_start_at=C.DE_ANNEXATION_HEARING_START_AT,
        scheduled_end_at=C.DE_ANNEXATION_HEARING_END_AT,
    )
    setup_hearing_held(
        api, successor, clock_at_hearing=C.DE_ANNEXATION_HEARING_START_AT
    )
    close_protest_period(
        api, successor, clock_after_window=C.DE_ANNEXATION_CLOCK_AFTER_PROTEST
    )
    setup_finalized_analysis(api, successor)
    adopt_ordinance(api, successor)
    return successor

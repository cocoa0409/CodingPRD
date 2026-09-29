"""Composite setup helpers that walk the API into the states tests need.

Every helper uses the lenient `get_success_data` so that a broken setup surfaces as a
clear setup failure rather than as a confusing assertion inside a test.

Identity threading: an `OwnerAgent`'s `X-User-ID` is the `id` of the acting `Owner`, so
every ownership-gated call below is made with `make_owner_agent_headers(owner["id"])`.
"""
from __future__ import annotations

import itertools
from typing import Any, Iterable, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    apply_utility_allowance_payload,
    challenge_study_payload,
    create_comparable_payload,
    create_direct_ledger_claim_payload,
    create_hap_contract_payload,
    create_owner_payload,
    create_property_payload,
    create_renewal_case_payload,
    create_restructuring_determination_payload,
    create_study_payload,
    create_tenant_certification_payload,
    create_tenant_household_payload,
    create_tenant_notice_payload,
    create_utility_allowance_analysis_payload,
    create_vacancy_claim_payload,
    create_voucher_submission_payload,
    decide_claim_payload,
    decide_study_payload,
    decide_utility_allowance_payload,
    elect_adjustment_payload,
    execute_renewal_payload,
    move_out_payload,
    rescind_payload,
    reverse_voucher_payload,
    select_option_payload,
)
from .test_users import (
    TEST_USERS,
    make_contract_administrator_headers,
    make_hud_field_office_headers,
    make_owner_agent_headers,
    make_pha_administrator_headers,
)

CA_HEADERS = TEST_USERS["contract_administrator_headers"]
CA_APPROVER_HEADERS = TEST_USERS["contract_administrator_approver_headers"]
HUD_HEADERS = TEST_USERS["hud_field_office_headers"]
PHA_HEADERS = TEST_USERS["pha_administrator_headers"]

# The logical clock a freshly started server begins at.
CLOCK_START_DATE = "2026-08-01"

# The clock date at which the reference contract (expiring 2027-12-31) sits 395 whole
# days from expiration, comfortably inside the renewal window.
RENEWAL_WINDOW_CLOCK_DATE = "2026-12-01"

_tin_counter = itertools.count(1)

# The three reference comparables used by the comparability-study chains.
REFERENCE_COMPARABLES: list[dict[str, Any]] = [
    {
        "address_label": "88 Alder Court",
        "raw_rent_cents": 125000,
        "adjustment_total_cents": 4650,
        "utility_adjustment_cents": 1500,
        "weight": 3,
    },
    {
        "address_label": "12 Birch Lane",
        "raw_rent_cents": 118000,
        "adjustment_total_cents": 4100,
        "utility_adjustment_cents": 1500,
        "weight": 2,
    },
    {
        "address_label": "5 Cypress Way",
        "raw_rent_cents": 133000,
        "adjustment_total_cents": 5925,
        "utility_adjustment_cents": 1500,
        "weight": 1,
    },
]

# The two reference households: unit 101 pays the 30-percent-of-income figure, unit 102
# falls back to the minimum rent.
REFERENCE_HOUSEHOLD_ONE: dict[str, Any] = {
    "unit_number": "101",
    "household_name": "Alvarez",
    "annual_adjusted_income_cents": 1800000,
    "annual_gross_income_cents": 1920000,
    "family_size": 3,
}
REFERENCE_HOUSEHOLD_TWO: dict[str, Any] = {
    "unit_number": "102",
    "household_name": "Boone",
    "annual_adjusted_income_cents": 60000,
    "annual_gross_income_cents": 60000,
    "family_size": 1,
}


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(to_iso8601: str, headers: Optional[dict] = None) -> dict:
    """Move the logical clock to an explicit instant."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or CA_HEADERS))


def set_clock_date(date_str: str, headers: Optional[dict] = None) -> dict:
    """Move the logical clock to midnight UTC on `date_str`."""
    return set_clock(f"{date_str}T00:00:00Z", headers)


# --------------------------------------------------------------------------
# Version readers
# --------------------------------------------------------------------------
def current_contract_version(contract_id: str, headers: Optional[dict] = None) -> int:
    return get_success_data(api_client.get_hap_contract(contract_id, headers or CA_HEADERS))[
        "version"
    ]


def current_property_version(property_id: str, headers: Optional[dict] = None) -> int:
    return get_success_data(api_client.get_property(property_id, headers or CA_HEADERS))[
        "version"
    ]


def current_tenant_version(tenant_id: str, headers: Optional[dict] = None) -> int:
    return get_success_data(
        api_client.get_tenant_household(tenant_id, headers or CA_HEADERS)
    )["version"]


# --------------------------------------------------------------------------
# Tier 1: single-entity creation
# --------------------------------------------------------------------------
def create_owner(**overrides: Any) -> dict:
    """Register an owner. A unique `tin` is minted unless one is supplied."""
    payload = create_owner_payload(**overrides)
    if "tin" not in overrides:
        payload["tin"] = f"27-33100{next(_tin_counter):02d}"
    return get_success_data(api_client.create_owner(payload, CA_HEADERS))


def create_owner_with_headers(**overrides: Any) -> tuple[dict, dict]:
    """Register an owner and return it with the headers its staff must present."""
    owner = create_owner(**overrides)
    return owner, make_owner_agent_headers(owner["id"])


def create_property(owner_id: str, owner_headers: dict, **overrides: Any) -> dict:
    payload = create_property_payload(owner_id, **overrides)
    return get_success_data(api_client.create_property(payload, owner_headers))


def create_contract(property_id: str, **overrides: Any) -> dict:
    payload = create_hap_contract_payload(property_id, **overrides)
    return get_success_data(api_client.create_hap_contract(payload, CA_HEADERS))


# --------------------------------------------------------------------------
# Tier 2: portfolio hierarchy
# --------------------------------------------------------------------------
def setup_portfolio(
    owner_overrides: Optional[dict] = None,
    property_overrides: Optional[dict] = None,
    contract_overrides: Optional[dict] = None,
) -> dict:
    """Owner -> property -> HAP contract, the shared base of nearly every chain.

    Returns `owner`, `owner_headers`, `property`, `contract`.
    """
    owner, owner_headers = create_owner_with_headers(**(owner_overrides or {}))
    prop = create_property(owner["id"], owner_headers, **(property_overrides or {}))
    contract = create_contract(prop["id"], **(contract_overrides or {}))
    return {
        "owner": owner,
        "owner_headers": owner_headers,
        "property": prop,
        "contract": contract,
    }


def setup_property_only(
    owner_overrides: Optional[dict] = None, property_overrides: Optional[dict] = None
) -> dict:
    """Owner -> property, for chains that never need a contract."""
    owner, owner_headers = create_owner_with_headers(**(owner_overrides or {}))
    prop = create_property(owner["id"], owner_headers, **(property_overrides or {}))
    return {"owner": owner, "owner_headers": owner_headers, "property": prop}


def setup_renewal_case(
    clock_date: Optional[str] = RENEWAL_WINDOW_CLOCK_DATE,
    owner_overrides: Optional[dict] = None,
    property_overrides: Optional[dict] = None,
    contract_overrides: Optional[dict] = None,
    base: Optional[dict] = None,
) -> dict:
    """Portfolio plus an open renewal case. Moves the clock inside the renewal window."""
    ctx = base or setup_portfolio(owner_overrides, property_overrides, contract_overrides)
    if clock_date is not None:
        set_clock_date(clock_date)
    case = get_success_data(
        api_client.create_renewal_case(
            create_renewal_case_payload(ctx["contract"]["id"]), ctx["owner_headers"]
        )
    )
    ctx["case"] = case
    return ctx


# --------------------------------------------------------------------------
# Tier 3: renewal-case lifecycle shortcuts
# --------------------------------------------------------------------------
def setup_option_selected(
    renewal_option: str = "OPTION_2_OCAF",
    clock_date: Optional[str] = RENEWAL_WINDOW_CLOCK_DATE,
    base: Optional[dict] = None,
    **case_kwargs: Any,
) -> dict:
    """Open a case and elect `renewal_option`, leaving the rent track at OPTION_SELECTED."""
    ctx = setup_renewal_case(clock_date=clock_date, base=base, **case_kwargs)
    ctx["case"] = get_success_data(
        api_client.select_option(
            ctx["case"]["id"], select_option_payload(renewal_option), ctx["owner_headers"]
        )
    )
    return ctx


def setup_adjustment_elected(
    renewal_option: str = "OPTION_2_OCAF",
    adjustment_method: str = "OCAF",
    clock_date: Optional[str] = RENEWAL_WINDOW_CLOCK_DATE,
    base: Optional[dict] = None,
    **case_kwargs: Any,
) -> dict:
    """Open a case, elect the option and then the adjustment method."""
    ctx = setup_option_selected(
        renewal_option=renewal_option, clock_date=clock_date, base=base, **case_kwargs
    )
    ctx["case"] = get_success_data(
        api_client.elect_adjustment(
            ctx["case"]["id"],
            elect_adjustment_payload(adjustment_method),
            ctx["owner_headers"],
        )
    )
    return ctx


def add_comparables(
    study_id: str, owner_headers: dict, comparables: Optional[Iterable[dict]] = None
) -> list[dict]:
    """Add comparables to a DRAFT study one at a time, in the supplied order."""
    specs = list(comparables if comparables is not None else REFERENCE_COMPARABLES)
    created: list[dict] = []
    for spec in specs:
        created.append(
            get_success_data(
                api_client.create_comparable(
                    create_comparable_payload(study_id, **spec), owner_headers
                )
            )
        )
    return created


def setup_study(
    case_id: str,
    owner_headers: dict,
    comparables: Optional[Iterable[dict]] = None,
    appraiser_name: str = "Hollis Appraisal Group",
    supersedes_study_id: Optional[str] = None,
) -> dict:
    """Commission a study on a case and populate it with comparables while it is DRAFT."""
    payload = create_study_payload(case_id, appraiser_name=appraiser_name)
    if supersedes_study_id is not None:
        payload["supersedes_study_id"] = supersedes_study_id
    study = get_success_data(api_client.create_study(payload, owner_headers))
    created = add_comparables(study["id"], owner_headers, comparables)
    return {"study": study, "comparables": created}


def setup_submitted_study(
    case_id: str,
    owner_headers: dict,
    comparables: Optional[Iterable[dict]] = None,
    appraiser_name: str = "Hollis Appraisal Group",
    supersedes_study_id: Optional[str] = None,
) -> dict:
    """Commission, populate and submit a study."""
    bundle = setup_study(
        case_id, owner_headers, comparables, appraiser_name, supersedes_study_id
    )
    bundle["study"] = get_success_data(
        api_client.submit_study(bundle["study"]["id"], owner_headers)
    )
    return bundle


def setup_accepted_study(
    case_id: str,
    owner_headers: dict,
    comparables: Optional[Iterable[dict]] = None,
    decider_headers: Optional[dict] = None,
) -> dict:
    """Commission, populate, submit and accept a study."""
    bundle = setup_submitted_study(case_id, owner_headers, comparables)
    bundle["study"] = get_success_data(
        api_client.decide_study(
            bundle["study"]["id"],
            decide_study_payload("ACCEPT"),
            decider_headers or CA_HEADERS,
        )
    )
    return bundle


def setup_rejected_study(
    case_id: str,
    owner_headers: dict,
    comparables: Optional[Iterable[dict]] = None,
    reason: str = "Appraisal support is insufficient",
    decider_headers: Optional[dict] = None,
) -> dict:
    """Commission, populate, submit and reject a study."""
    bundle = setup_submitted_study(case_id, owner_headers, comparables)
    bundle["study"] = get_success_data(
        api_client.decide_study(
            bundle["study"]["id"],
            decide_study_payload("REJECT", reason),
            decider_headers or CA_HEADERS,
        )
    )
    return bundle


def setup_challenged_study(
    case_id: str,
    owner_headers: dict,
    struck_index: int = 0,
    comparables: Optional[Iterable[dict]] = None,
    reason: str = "Comparable is not truly comparable",
    reviewer_headers: Optional[dict] = None,
) -> dict:
    """Submit a study and have a reviewer strike one of its comparables."""
    bundle = setup_submitted_study(case_id, owner_headers, comparables)
    struck = bundle["comparables"][struck_index]
    bundle["study"] = get_success_data(
        api_client.challenge_study(
            bundle["study"]["id"],
            challenge_study_payload(reason, [struck["id"]]),
            reviewer_headers or CA_HEADERS,
        )
    )
    bundle["struck"] = struck
    return bundle


def setup_case_with_accepted_study(
    renewal_option: str = "OPTION_1_MARK_UP_TO_MARKET",
    adjustment_method: str = "OCAF",
    comparables: Optional[Iterable[dict]] = None,
    clock_date: Optional[str] = RENEWAL_WINDOW_CLOCK_DATE,
    base: Optional[dict] = None,
    decider_headers: Optional[dict] = None,
    **case_kwargs: Any,
) -> dict:
    """A case at RCS_IN_PROGRESS carrying one ACCEPTED comparability study."""
    ctx = setup_adjustment_elected(
        renewal_option=renewal_option,
        adjustment_method=adjustment_method,
        clock_date=clock_date,
        base=base,
        **case_kwargs,
    )
    bundle = setup_accepted_study(
        ctx["case"]["id"], ctx["owner_headers"], comparables, decider_headers
    )
    ctx.update(bundle)
    ctx["case"] = get_success_data(
        api_client.get_renewal_case(ctx["case"]["id"], CA_HEADERS)
    )
    return ctx


def approve_rents(case_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.approve_rents(case_id, headers or CA_APPROVER_HEADERS)
    )


def issue_renewal_intent_notice(
    case_id: str, owner_headers: dict, effective_date: str = "2027-12-31", **overrides: Any
) -> dict:
    """Issue the RENEWAL_INTENT notice that advances the notice track."""
    payload = create_tenant_notice_payload(
        case_id, notice_type="RENEWAL_INTENT", effective_date=effective_date, **overrides
    )
    return get_success_data(api_client.create_tenant_notice(payload, owner_headers))


def issue_opt_out_notice(
    case_id: str, owner_headers: dict, effective_date: str = "2027-12-31", **overrides: Any
) -> dict:
    """Issue the OPT_OUT_ONE_YEAR notice that arms the opt-out."""
    payload = create_tenant_notice_payload(
        case_id, notice_type="OPT_OUT_ONE_YEAR", effective_date=effective_date, **overrides
    )
    return get_success_data(api_client.create_tenant_notice(payload, owner_headers))


def setup_executed_renewal(
    renewal_option: str = "OPTION_2_OCAF",
    adjustment_method: str = "OCAF",
    clock_date: Optional[str] = RENEWAL_WINDOW_CLOCK_DATE,
    notice_effective_date: str = "2027-12-31",
    base: Optional[dict] = None,
    approver_headers: Optional[dict] = None,
    **case_kwargs: Any,
) -> dict:
    """Walk both tracks to the coupling point and execute the renewal.

    Returns the portfolio plus `case`, `notice` and the post-execution `contract`.
    """
    ctx = setup_adjustment_elected(
        renewal_option=renewal_option,
        adjustment_method=adjustment_method,
        clock_date=clock_date,
        base=base,
        **case_kwargs,
    )
    ctx["case"] = approve_rents(ctx["case"]["id"], approver_headers)
    ctx["notice"] = issue_renewal_intent_notice(
        ctx["case"]["id"], ctx["owner_headers"], notice_effective_date
    )
    version = current_contract_version(ctx["contract"]["id"])
    ctx["case"] = get_success_data(
        api_client.execute_renewal(
            ctx["case"]["id"], execute_renewal_payload(version), CA_HEADERS
        )
    )
    ctx["contract"] = get_success_data(
        api_client.get_hap_contract(ctx["contract"]["id"], CA_HEADERS)
    )
    return ctx


# --------------------------------------------------------------------------
# Tier 3: households and certifications
# --------------------------------------------------------------------------
def create_household(property_id: str, owner_headers: dict, **overrides: Any) -> dict:
    payload = create_tenant_household_payload(property_id, **overrides)
    return get_success_data(api_client.create_tenant_household(payload, owner_headers))


def certify_household(
    tenant_id: str,
    owner_headers: dict,
    effective_date: str,
    cert_type: str = "INITIAL",
    expected_tenant_version: Optional[int] = None,
    **overrides: Any,
) -> dict:
    """Create a certification, reading the household's current `version` when none given."""
    version = (
        expected_tenant_version
        if expected_tenant_version is not None
        else current_tenant_version(tenant_id)
    )
    payload = create_tenant_certification_payload(
        tenant_id,
        version,
        cert_type=cert_type,
        effective_date=effective_date,
        **overrides,
    )
    return get_success_data(api_client.create_tenant_certification(payload, owner_headers))


def setup_certified_household(
    property_id: str,
    owner_headers: dict,
    household_overrides: Optional[dict] = None,
    effective_date: str = "2026-07-01",
    cert_type: str = "INITIAL",
) -> dict:
    """Register one household and give it an ACTIVE certification."""
    household = create_household(property_id, owner_headers, **(household_overrides or {}))
    cert = certify_household(household["id"], owner_headers, effective_date, cert_type)
    return {"household": household, "certification": cert}


def setup_reference_households(
    property_id: str,
    owner_headers: dict,
    effective_date: str = "2026-07-01",
    certify: bool = True,
) -> dict:
    """Register the two reference households, certified in `created_at` order."""
    first = create_household(property_id, owner_headers, **REFERENCE_HOUSEHOLD_ONE)
    second = create_household(property_id, owner_headers, **REFERENCE_HOUSEHOLD_TWO)
    result: dict[str, Any] = {"household_one": first, "household_two": second}
    if certify:
        result["certification_one"] = certify_household(
            first["id"], owner_headers, effective_date
        )
        result["certification_two"] = certify_household(
            second["id"], owner_headers, effective_date
        )
        # Certifying a household re-points its current figures and increments its
        # `version`, so the rows captured at registration are stale. Re-read them so
        # callers observe the post-certification state.
        result["household_one"] = get_success_data(
            api_client.get_tenant_household(first["id"], owner_headers)
        )
        result["household_two"] = get_success_data(
            api_client.get_tenant_household(second["id"], owner_headers)
        )
    return result


def move_out_household(
    tenant_id: str, owner_headers: dict, move_out_date: str
) -> dict:
    return get_success_data(
        api_client.move_out_tenant_household(
            tenant_id, move_out_payload(move_out_date), owner_headers
        )
    )


# --------------------------------------------------------------------------
# Tier 3: utility allowance analyses
# --------------------------------------------------------------------------
def create_ua_analysis(property_id: str, owner_headers: dict, **overrides: Any) -> dict:
    payload = create_utility_allowance_analysis_payload(property_id, **overrides)
    return get_success_data(
        api_client.create_utility_allowance_analysis(payload, owner_headers)
    )


def setup_submitted_ua_analysis(
    property_id: str, owner_headers: dict, **overrides: Any
) -> dict:
    analysis = create_ua_analysis(property_id, owner_headers, **overrides)
    return get_success_data(
        api_client.submit_utility_allowance_analysis(analysis["id"], owner_headers)
    )


def setup_approved_ua_analysis(
    property_id: str,
    owner_headers: dict,
    decider_headers: Optional[dict] = None,
    **overrides: Any,
) -> dict:
    """Open, submit and accept a utility allowance analysis."""
    analysis = setup_submitted_ua_analysis(property_id, owner_headers, **overrides)
    headers = decider_headers
    if headers is None:
        headers = (
            HUD_HEADERS if analysis.get("requires_field_office_approval") else CA_HEADERS
        )
    return get_success_data(
        api_client.decide_utility_allowance_analysis(
            analysis["id"], decide_utility_allowance_payload("ACCEPT"), headers
        )
    )


def apply_ua_analysis(
    analysis_id: str,
    property_id: str,
    expected_property_version: Optional[int] = None,
    headers: Optional[dict] = None,
) -> dict:
    version = (
        expected_property_version
        if expected_property_version is not None
        else current_property_version(property_id)
    )
    return get_success_data(
        api_client.apply_utility_allowance_analysis(
            analysis_id, apply_utility_allowance_payload(version), headers or CA_HEADERS
        )
    )


def setup_applied_ua_analysis(
    property_id: str, owner_headers: dict, **overrides: Any
) -> dict:
    """Open, submit, accept and apply a utility allowance analysis."""
    analysis = setup_approved_ua_analysis(property_id, owner_headers, **overrides)
    return apply_ua_analysis(analysis["id"], property_id)


# --------------------------------------------------------------------------
# Tier 3: monthly vouchers
# --------------------------------------------------------------------------
def create_voucher(
    contract_id: str,
    owner_headers: dict,
    period_month: str,
    expected_contract_version: Optional[int] = None,
    **overrides: Any,
) -> dict:
    version = (
        expected_contract_version
        if expected_contract_version is not None
        else current_contract_version(contract_id)
    )
    payload = create_voucher_submission_payload(
        contract_id, version, period_month=period_month, **overrides
    )
    return get_success_data(api_client.create_voucher_submission(payload, owner_headers))


def setup_submitted_voucher(
    contract_id: str,
    owner_headers: dict,
    period_month: str,
    submit_clock_date: Optional[str] = None,
) -> dict:
    """Open a voucher and submit it, moving the clock past the billed month if asked."""
    voucher = create_voucher(contract_id, owner_headers, period_month)
    if submit_clock_date is not None:
        set_clock_date(submit_clock_date)
    return get_success_data(
        api_client.submit_voucher_submission(voucher["id"], owner_headers)
    )


def setup_paid_voucher(
    contract_id: str,
    owner_headers: dict,
    period_month: str,
    submit_clock_date: Optional[str] = None,
    payer_headers: Optional[dict] = None,
) -> dict:
    """Open, submit and pay a monthly voucher."""
    voucher = setup_submitted_voucher(
        contract_id, owner_headers, period_month, submit_clock_date
    )
    return get_success_data(
        api_client.pay_voucher_submission(voucher["id"], payer_headers or CA_HEADERS)
    )


def reverse_voucher(
    voucher_id: str, reason: str = "Billing correction", headers: Optional[dict] = None
) -> dict:
    return get_success_data(
        api_client.reverse_voucher_submission(
            voucher_id, reverse_voucher_payload(reason), headers or CA_HEADERS
        )
    )


# --------------------------------------------------------------------------
# Tier 3: special claims
# --------------------------------------------------------------------------
def create_vacancy_claim(
    contract_id: str,
    owner_headers: dict,
    unit_number: str,
    claim_period_month: str,
    vacancy_start_date: str,
    vacancy_end_date: Optional[str] = None,
    estimated_vacancy_days: Optional[int] = None,
    **overrides: Any,
) -> dict:
    payload = create_vacancy_claim_payload(
        contract_id,
        unit_number,
        claim_period_month,
        vacancy_start_date,
        vacancy_end_date,
        estimated_vacancy_days,
        **overrides,
    )
    return get_success_data(api_client.create_special_claim(payload, owner_headers))


def create_direct_ledger_claim(
    contract_id: str,
    owner_headers: dict,
    claim_type: str,
    unit_number: str,
    claim_period_month: str,
    claimed_amount_cents: int,
    security_deposit_balance_cents: Optional[int] = None,
    **overrides: Any,
) -> dict:
    payload = create_direct_ledger_claim_payload(
        contract_id,
        claim_type,
        unit_number,
        claim_period_month,
        claimed_amount_cents,
        security_deposit_balance_cents,
        **overrides,
    )
    return get_success_data(api_client.create_special_claim(payload, owner_headers))


def submit_claim(claim_id: str, owner_headers: dict) -> dict:
    return get_success_data(api_client.submit_special_claim(claim_id, owner_headers))


def decide_claim(
    claim_id: str,
    decision: str,
    reason: Optional[str] = None,
    headers: Optional[dict] = None,
) -> dict:
    return get_success_data(
        api_client.decide_special_claim(
            claim_id, decide_claim_payload(decision, reason), headers or CA_HEADERS
        )
    )


def setup_approved_claim(
    claim: dict, owner_headers: dict, reason: Optional[str] = None
) -> dict:
    """Submit and approve an existing DRAFT claim."""
    submit_claim(claim["id"], owner_headers)
    return decide_claim(claim["id"], "APPROVE", reason)


# --------------------------------------------------------------------------
# Tier 4: the opt-out cascade
# --------------------------------------------------------------------------
def setup_case_with_households(
    clock_date: Optional[str] = RENEWAL_WINDOW_CLOCK_DATE,
    cert_effective_date: str = "2026-07-01",
    owner_overrides: Optional[dict] = None,
    property_overrides: Optional[dict] = None,
    contract_overrides: Optional[dict] = None,
) -> dict:
    """Portfolio with the two certified reference households and an open renewal case.

    Households are registered and certified before the clock moves into the renewal
    window, so their certifications carry the pre-renewal rent basis.
    """
    ctx = setup_portfolio(owner_overrides, property_overrides, contract_overrides)
    ctx.update(
        setup_reference_households(
            ctx["property"]["id"], ctx["owner_headers"], cert_effective_date
        )
    )
    if clock_date is not None:
        set_clock_date(clock_date)
    ctx["case"] = get_success_data(
        api_client.create_renewal_case(
            create_renewal_case_payload(ctx["contract"]["id"]), ctx["owner_headers"]
        )
    )
    return ctx


def setup_opt_out_noticed_case(
    clock_date: Optional[str] = RENEWAL_WINDOW_CLOCK_DATE,
    notice_effective_date: str = "2027-12-31",
    cert_effective_date: str = "2026-07-01",
    base: Optional[dict] = None,
    owner_overrides: Optional[dict] = None,
    property_overrides: Optional[dict] = None,
    contract_overrides: Optional[dict] = None,
) -> dict:
    """Walk the whole opt-out cascade: one-year notice, then record-opt-out.

    Returns the portfolio, both households, the `notice`, the post-cascade `case` and the
    minted `enhanced_vouchers` in household `created_at` order.
    """
    ctx = base or setup_case_with_households(
        clock_date=clock_date,
        cert_effective_date=cert_effective_date,
        owner_overrides=owner_overrides,
        property_overrides=property_overrides,
        contract_overrides=contract_overrides,
    )
    ctx["notice"] = issue_opt_out_notice(
        ctx["case"]["id"], ctx["owner_headers"], notice_effective_date
    )
    ctx["case"] = get_success_data(
        api_client.record_opt_out(ctx["case"]["id"], ctx["owner_headers"])
    )
    vouchers, _ = _paginated(
        api_client.list_case_enhanced_vouchers(ctx["case"]["id"], CA_HEADERS, limit=100)
    )
    ctx["enhanced_vouchers"] = vouchers
    return ctx


def _paginated(response: Any) -> tuple[list[dict], dict]:
    """Read a list envelope leniently, for setup use."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})


def issue_enhanced_voucher(voucher_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.issue_enhanced_voucher(voucher_id, headers or PHA_HEADERS)
    )


def rescind_enhanced_voucher(
    voucher_id: str, reason: str = "Household declined the voucher", headers=None
) -> dict:
    return get_success_data(
        api_client.rescind_enhanced_voucher(
            voucher_id, rescind_payload(reason), headers or PHA_HEADERS
        )
    )


def setup_opt_out_with_issued_vouchers(
    clock_date: Optional[str] = RENEWAL_WINDOW_CLOCK_DATE,
    notice_effective_date: str = "2027-12-31",
    base: Optional[dict] = None,
    **kwargs: Any,
) -> dict:
    """The opt-out cascade with every minted enhanced voucher issued."""
    ctx = setup_opt_out_noticed_case(
        clock_date=clock_date,
        notice_effective_date=notice_effective_date,
        base=base,
        **kwargs,
    )
    issued = [issue_enhanced_voucher(ev["id"]) for ev in ctx["enhanced_vouchers"]]
    ctx["enhanced_vouchers"] = issued
    return ctx


def rescind_notice(
    notice_id: str, reason: str = "Owner reconsidered", headers: Optional[dict] = None
) -> dict:
    return get_success_data(
        api_client.rescind_tenant_notice(notice_id, rescind_payload(reason), headers)
    )


# --------------------------------------------------------------------------
# Tier 4: restructuring determinations
# --------------------------------------------------------------------------
def create_determination(case_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.create_restructuring_determination(
            create_restructuring_determination_payload(case_id), headers or CA_HEADERS
        )
    )


def setup_evaluated_determination(case_id: str, headers: Optional[dict] = None) -> dict:
    """Open a determination on a case and evaluate it."""
    determination = create_determination(case_id, headers)
    return get_success_data(
        api_client.evaluate_restructuring_determination(
            determination["id"], headers or CA_HEADERS
        )
    )


def approve_determination(determination_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.approve_restructuring_determination(
            determination_id, headers or HUD_HEADERS
        )
    )


# --------------------------------------------------------------------------
# Tier 5: terminal-state and accumulation targeting
# --------------------------------------------------------------------------
def setup_finalized_opt_out(
    clock_date: Optional[str] = RENEWAL_WINDOW_CLOCK_DATE,
    notice_effective_date: str = "2027-12-31",
    finalize_clock_date: Optional[str] = None,
    **kwargs: Any,
) -> dict:
    """Drive the opt-out path to its terminal state on both the case and the contract."""
    ctx = setup_opt_out_with_issued_vouchers(
        clock_date=clock_date, notice_effective_date=notice_effective_date, **kwargs
    )
    set_clock_date(finalize_clock_date or notice_effective_date)
    ctx["case"] = get_success_data(
        api_client.finalize_opt_out(ctx["case"]["id"], CA_HEADERS)
    )
    ctx["contract"] = get_success_data(
        api_client.get_hap_contract(ctx["contract"]["id"], CA_HEADERS)
    )
    ctx["property"] = get_success_data(
        api_client.get_property(ctx["property"]["id"], CA_HEADERS)
    )
    return ctx


def setup_vacancy_days_used(
    contract_id: str,
    owner_headers: dict,
    unit_number: str,
    claim_period_month: str,
    vacancy_start_date: str,
    vacancy_end_date: str,
) -> dict:
    """File and submit one vacancy claim so its days count toward the aggregate cap."""
    claim = create_vacancy_claim(
        contract_id,
        owner_headers,
        unit_number,
        claim_period_month,
        vacancy_start_date,
        vacancy_end_date=vacancy_end_date,
    )
    return submit_claim(claim["id"], owner_headers)


def setup_ledger_at_balance(
    authorized_hap_budget_cents: int,
    **kwargs: Any,
) -> dict:
    """Portfolio whose contract carries an explicit HAP authorization."""
    contract_overrides = dict(kwargs.pop("contract_overrides", None) or {})
    contract_overrides["authorized_hap_budget_cents"] = authorized_hap_budget_cents
    return setup_portfolio(contract_overrides=contract_overrides, **kwargs)

"""Composite setup helpers.

Every test starts against an empty database, so all preconditions are built by
replaying real endpoint calls.  The helpers here are layered:

  tier 1  single-entity creators and clock movement
  tier 2  entity hierarchies (employer -> plan -> employee -> dependents)
  tier 3  full-lifecycle shortcuts (matched / confirmed / completed / no-show)
  tier 4  accumulation and threshold targeting (incidents, strikes, overage)
  tier 5  finalization (draft / issued / paid / voided invoices)

Reads use the lenient success accessor so a helper never masks the assertion a
test actually wants to make.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import COLD_START_UTC, REQUIRED_CREDENTIAL_TYPES
from .test_users import (
    TEST_USERS,
    make_care_coordinator_headers,
    make_employee_user_headers,
    make_network_admin_headers,
    make_provider_manager_headers,
)

NETWORK_ADMIN = TEST_USERS["network_admin"]
BENEFITS_ADMIN = TEST_USERS["benefits_admin"]
CARE_COORDINATOR = TEST_USERS["care_coordinator"]

FAR_FUTURE_EXPIRY = "2027-12-31"


# ==========================================================================
# Tier 1 — clock and single-entity creators
# ==========================================================================
def set_clock(api: ApiClient, current_utc: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Advance the logical clock and return the reported clock state."""
    response = api.set_clock(f.clock_payload(current_utc), headers or NETWORK_ADMIN)
    return get_success_data(response)


def create_employer(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    response = api.create_employer(f.employer_payload(**overrides), NETWORK_ADMIN)
    return get_success_data(response)


def read_employer(api: ApiClient, employer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_employer(employer_id, NETWORK_ADMIN))


def create_draft_plan(api: ApiClient, employer_id: str, **overrides: Any) -> Dict[str, Any]:
    """Draft a plan, reading the employer version fresh so the guard passes."""
    employer = read_employer(api, employer_id)
    payload = f.benefit_plan_payload(employer_id, employer["version"], **overrides)
    return get_success_data(api.create_benefit_plan(payload, BENEFITS_ADMIN))


def activate_plan(api: ApiClient, plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.activate_benefit_plan(plan_id, BENEFITS_ADMIN))


def create_active_plan(api: ApiClient, employer_id: str, **overrides: Any) -> Dict[str, Any]:
    """Draft then activate a plan; returns the ACTIVE row."""
    plan = create_draft_plan(api, employer_id, **overrides)
    return activate_plan(api, plan["id"])


def create_employee(
    api: ApiClient,
    employer_id: str,
    benefit_plan_id: str,
    user_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.employee_payload(employer_id, benefit_plan_id, user_id, **overrides)
    return get_success_data(api.create_employee(payload, BENEFITS_ADMIN))


def read_employee(api: ApiClient, employee_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_employee(employee_id, BENEFITS_ADMIN))


def read_entitlement(api: ApiClient, employee_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_entitlement(employee_id, BENEFITS_ADMIN))


def create_dependent(
    api: ApiClient, employee_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    payload = f.dependent_payload(**overrides)
    return get_success_data(api.create_dependent(employee_id, payload, headers or BENEFITS_ADMIN))


def create_provider(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_provider(f.provider_payload(**overrides), NETWORK_ADMIN))


def read_provider(api: ApiClient, provider_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_provider(provider_id, NETWORK_ADMIN))


def add_credential(
    api: ApiClient, provider_id: str, credential_type: str, **overrides: Any
) -> Dict[str, Any]:
    payload = f.credential_payload(credential_type, **overrides)
    return get_success_data(api.create_credential(provider_id, payload, NETWORK_ADMIN))


def add_all_credentials(
    api: ApiClient,
    provider_id: str,
    expires_on: str = FAR_FUTURE_EXPIRY,
    types: Optional[List[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Attach one credential of each required type; returns them keyed by type."""
    result: Dict[str, Dict[str, Any]] = {}
    for credential_type in types or REQUIRED_CREDENTIAL_TYPES:
        result[credential_type] = add_credential(
            api, provider_id, credential_type, expires_on=expires_on
        )
    return result


def run_credential_review(api: ApiClient, provider_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = f.credential_review_payload(**overrides)
    return get_success_data(api.credential_review(provider_id, payload, NETWORK_ADMIN))


def set_network_status(
    api: ApiClient, provider_id: str, target_status: str, **overrides: Any
) -> Dict[str, Any]:
    payload = f.network_status_payload(target_status, **overrides)
    return get_success_data(api.set_network_status(provider_id, payload, NETWORK_ADMIN))


def create_capacity_block(
    api: ApiClient,
    provider_id: str,
    start_time_utc: str,
    end_time_utc: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.capacity_block_payload(start_time_utc, end_time_utc, **overrides)
    return get_success_data(
        api.create_capacity_block(provider_id, payload, headers or NETWORK_ADMIN)
    )


def read_capacity_block(api: ApiClient, block_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_capacity_block(block_id, NETWORK_ADMIN))


def create_reservation(
    api: ApiClient,
    employee_id: str,
    dependent_ids: List[str],
    care_start_utc: str,
    care_end_utc: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.reservation_payload(
        employee_id, dependent_ids, care_start_utc, care_end_utc, **overrides
    )
    return get_success_data(api.create_reservation(payload, headers or CARE_COORDINATOR))


def read_reservation(api: ApiClient, reservation_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_reservation(reservation_id, CARE_COORDINATOR))


def read_reservation_ledger(api: ApiClient, reservation_id: str) -> List[Dict[str, Any]]:
    body = api.list_reservation_ledger_entries(reservation_id, NETWORK_ADMIN).json()
    return body["data"]


def read_employee_ledger(api: ApiClient, employee_id: str) -> List[Dict[str, Any]]:
    body = api.list_employee_ledger_entries(employee_id, NETWORK_ADMIN).json()
    return body["data"]


def read_offers_for_reservation(api: ApiClient, reservation_id: str) -> List[Dict[str, Any]]:
    """Every offer of a reservation, in rank order."""
    body = api.list_match_offers(
        CARE_COORDINATOR, params={"reservation_id": reservation_id, "limit": 100}
    ).json()
    offers = body["data"]
    return sorted(offers, key=lambda offer: offer["rank_position"])


def read_provider_credentials(
    api: ApiClient, provider_id: str, **params: Any
) -> List[Dict[str, Any]]:
    body = api.list_credentials(provider_id, NETWORK_ADMIN, params=params or None).json()
    return body["data"]


# ==========================================================================
# Tier 2 — entity hierarchies
# ==========================================================================
def setup_employer_with_active_plan(
    api: ApiClient,
    employer_overrides: Optional[Dict[str, Any]] = None,
    plan_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Employer plus one ACTIVE benefit plan."""
    employer = create_employer(api, **(employer_overrides or {}))
    plan = create_active_plan(api, employer["id"], **(plan_overrides or {}))
    return {"employer": employer, "plan": plan}


def setup_enrolled_employee(
    api: ApiClient,
    dependent_count: int = 1,
    employer_overrides: Optional[Dict[str, Any]] = None,
    plan_overrides: Optional[Dict[str, Any]] = None,
    employee_overrides: Optional[Dict[str, Any]] = None,
    dependent_overrides: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Employer, ACTIVE plan, one enrolled employee and N ACTIVE dependents."""
    base = setup_employer_with_active_plan(api, employer_overrides, plan_overrides)
    employee = create_employee(
        api,
        base["employer"]["id"],
        base["plan"]["id"],
        user_id,
        **(employee_overrides or {}),
    )
    dependents = [
        create_dependent(api, employee["id"], **(dependent_overrides or {}))
        for _ in range(dependent_count)
    ]
    return {
        "employer": base["employer"],
        "plan": base["plan"],
        "employee": employee,
        "dependents": dependents,
        "dependent_ids": [d["id"] for d in dependents],
        "employee_headers": make_employee_user_headers(employee["user_id"]),
    }


def setup_credentialed_provider(
    api: ApiClient,
    expires_on: str = FAR_FUTURE_EXPIRY,
    **provider_overrides: Any,
) -> Dict[str, Any]:
    """Provider with all four valid credentials, moved to CREDENTIALED."""
    provider = create_provider(api, **provider_overrides)
    credentials = add_all_credentials(api, provider["id"], expires_on=expires_on)
    reviewed = run_credential_review(api, provider["id"])
    return {
        "provider": reviewed,
        "credentials": credentials,
        "manager_headers": make_provider_manager_headers(provider["owner_user_id"]),
    }


def setup_provider_with_block(
    api: ApiClient,
    start_time_utc: str,
    end_time_utc: str,
    total_slots: int = 4,
    expires_on: str = FAR_FUTURE_EXPIRY,
    **provider_overrides: Any,
) -> Dict[str, Any]:
    """A CREDENTIALED provider holding one OPEN capacity block."""
    bundle = setup_credentialed_provider(api, expires_on=expires_on, **provider_overrides)
    block = create_capacity_block(
        api,
        bundle["provider"]["id"],
        start_time_utc,
        end_time_utc,
        total_slots=total_slots,
    )
    bundle["block"] = block
    return bundle


def setup_matchable_world(
    api: ApiClient,
    care_start_utc: str,
    care_end_utc: str,
    block_start_utc: str,
    block_end_utc: str,
    market_code: str = "MKT-SEA",
    total_slots: int = 4,
    dependent_count: int = 1,
    provider_care_mode: str = "CENTER_BASED",
    requested_care_mode: str = "CENTER_BASED",
    employer_overrides: Optional[Dict[str, Any]] = None,
    plan_overrides: Optional[Dict[str, Any]] = None,
    provider_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Everything a reservation needs to reach OFFERED: employer, plan, employee,
    dependents, one credentialed provider in the same market with an open block,
    and the reservation itself in INTAKE."""
    world = setup_enrolled_employee(
        api,
        dependent_count=dependent_count,
        employer_overrides=employer_overrides,
        plan_overrides=plan_overrides,
    )
    provider_kwargs = {
        "care_mode": provider_care_mode,
        "market_code": market_code,
        "daily_capacity_slots": total_slots,
    }
    provider_kwargs.update(provider_overrides or {})
    provider_bundle = setup_provider_with_block(
        api,
        block_start_utc,
        block_end_utc,
        total_slots=total_slots,
        **provider_kwargs,
    )
    reservation = create_reservation(
        api,
        world["employee"]["id"],
        world["dependent_ids"],
        care_start_utc,
        care_end_utc,
        market_code=market_code,
        requested_care_mode=requested_care_mode,
    )
    world.update(
        {
            "provider": provider_bundle["provider"],
            "credentials": provider_bundle["credentials"],
            "block": provider_bundle["block"],
            "manager_headers": provider_bundle["manager_headers"],
            "reservation": reservation,
        }
    )
    return world


# ==========================================================================
# Tier 3 — full-lifecycle shortcuts
# ==========================================================================
def match_reservation(
    api: ApiClient, reservation_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(api.match_reservation(reservation_id, headers or CARE_COORDINATOR))


def selected_offer(api: ApiClient, reservation_id: str) -> Dict[str, Any]:
    """The one offer at rank position 1."""
    offers = read_offers_for_reservation(api, reservation_id)
    selected = [offer for offer in offers if offer["offer_status"] == "SELECTED"]
    assert selected, f"reservation {reservation_id} has no SELECTED offer"
    return selected[0]


def confirm_reservation(
    api: ApiClient,
    reservation_id: str,
    block_id: str,
    block_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Confirm against a block, reading its version fresh unless one is pinned."""
    version = block_version if block_version is not None else read_capacity_block(api, block_id)["version"]
    payload = f.confirm_payload(block_id, version)
    return get_success_data(
        api.confirm_reservation(reservation_id, payload, headers or CARE_COORDINATOR)
    )


def setup_offered_reservation(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """setup_matchable_world driven one step further, into OFFERED."""
    world = setup_matchable_world(api, **kwargs)
    world["reservation"] = match_reservation(api, world["reservation"]["id"])
    world["offers"] = read_offers_for_reservation(api, world["reservation"]["id"])
    return world


def setup_confirmed_reservation(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """A reservation carried all the way to CONFIRMED with its RESERVE entry."""
    world = setup_offered_reservation(api, **kwargs)
    world["reservation"] = confirm_reservation(
        api, world["reservation"]["id"], world["block"]["id"]
    )
    world["block"] = read_capacity_block(api, world["block"]["id"])
    return world


def check_in(
    api: ApiClient, reservation_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(api.check_in_reservation(reservation_id, headers or CARE_COORDINATOR))


def complete(
    api: ApiClient,
    reservation_id: str,
    actual_start_utc: str,
    actual_end_utc: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = f.complete_payload(actual_start_utc, actual_end_utc)
    return get_success_data(
        api.complete_reservation(reservation_id, payload, headers or CARE_COORDINATOR)
    )


def drive_to_completed(
    api: ApiClient,
    reservation_id: str,
    actual_start_utc: str,
    actual_end_utc: str,
    check_in_clock: Optional[str] = None,
    complete_clock: Optional[str] = None,
) -> Dict[str, Any]:
    """Check in, then complete, moving the clock as the service window demands."""
    if check_in_clock:
        set_clock(api, check_in_clock)
    check_in(api, reservation_id)
    if complete_clock:
        set_clock(api, complete_clock)
    return complete(api, reservation_id, actual_start_utc, actual_end_utc)


def mark_no_show(
    api: ApiClient,
    reservation_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.no_show_payload(**overrides)
    return get_success_data(
        api.no_show_reservation(reservation_id, payload, headers or CARE_COORDINATOR)
    )


def cancel(
    api: ApiClient,
    reservation_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.cancel_payload(**overrides)
    return get_success_data(
        api.cancel_reservation(reservation_id, payload, headers or CARE_COORDINATOR)
    )


def reject_offer(
    api: ApiClient,
    reservation_id: str,
    match_offer_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.reject_offer_payload(match_offer_id, **overrides)
    return get_success_data(api.reject_offer(reservation_id, payload, headers or CARE_COORDINATOR))


def setup_accrued_completed_reservation(
    api: ApiClient,
    care_date: str = "2026-08-10",
    care_start_time: str = "T09:00:00Z",
    care_end_time: str = "T15:00:00Z",
    **kwargs: Any,
) -> Dict[str, Any]:
    """A reservation in COMPLETED / ACCRUED, ready to be swept onto an invoice."""
    care_start = f"{care_date}{care_start_time}"
    care_end = f"{care_date}{care_end_time}"
    world = setup_confirmed_reservation(
        api,
        care_start_utc=care_start,
        care_end_utc=care_end,
        block_start_utc=f"{care_date}T08:00:00Z",
        block_end_utc=f"{care_date}T18:00:00Z",
        **kwargs,
    )
    world["reservation"] = drive_to_completed(
        api,
        world["reservation"]["id"],
        care_start,
        care_end,
        check_in_clock=care_start,
        complete_clock=care_end,
    )
    world["block"] = read_capacity_block(api, world["block"]["id"])
    return world


# ==========================================================================
# Tier 4 — accumulation and threshold targeting
# ==========================================================================
def file_incident(
    api: ApiClient,
    provider_id: str,
    severity: str = "MODERATE",
    filer_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.incident_report_payload(provider_id, severity, **overrides)
    return get_success_data(
        api.create_incident_report(payload, filer_headers or CARE_COORDINATOR)
    )


def review_incident(
    api: ApiClient, incident_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(api.review_incident_report(incident_id, headers or NETWORK_ADMIN))


def substantiate_incident(
    api: ApiClient,
    incident_id: str,
    qa_action: str = "NONE",
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.substantiate_payload(qa_action, **overrides)
    return get_success_data(
        api.substantiate_incident_report(incident_id, payload, headers or NETWORK_ADMIN)
    )


def dismiss_incident(
    api: ApiClient,
    incident_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.dismiss_payload(**overrides)
    return get_success_data(
        api.dismiss_incident_report(incident_id, payload, headers or NETWORK_ADMIN)
    )


def substantiated_incident(
    api: ApiClient,
    provider_id: str,
    severity: str = "MODERATE",
    qa_action: str = "NONE",
    filer_user_id: str = "u_cc_2",
    resolver_user_id: str = "u_na_1",
    resolution_reason_code: str = "FINDING_CONFIRMED",
    **overrides: Any,
) -> Dict[str, Any]:
    """File, review and substantiate one incident with segregated actors."""
    incident = file_incident(
        api,
        provider_id,
        severity,
        filer_headers=make_care_coordinator_headers(filer_user_id),
        **overrides,
    )
    review_incident(api, incident["id"], make_network_admin_headers(resolver_user_id))
    return substantiate_incident(
        api,
        incident["id"],
        qa_action,
        headers=make_network_admin_headers(resolver_user_id),
        resolution_reason_code=resolution_reason_code,
    )


def drive_quality_score(
    api: ApiClient,
    provider_id: str,
    severities: List[str],
    qa_action: str = "NONE",
) -> Dict[str, Any]:
    """Substantiate one incident per severity, then return the provider."""
    for index, severity in enumerate(severities):
        substantiated_incident(
            api,
            provider_id,
            severity,
            qa_action=qa_action,
            filer_user_id=f"u_cc_{index + 2}",
        )
    return read_provider(api, provider_id)


def accrue_no_show_strikes(
    api: ApiClient,
    world: Dict[str, Any],
    care_dates: List[str],
    no_show_clock_time: str = "T09:30:00Z",
) -> List[Dict[str, Any]]:
    """Confirm then no-show one reservation per date so strikes accumulate."""
    results = []
    for care_date in care_dates:
        block = create_capacity_block(
            api,
            world["provider"]["id"],
            f"{care_date}T08:00:00Z",
            f"{care_date}T18:00:00Z",
            total_slots=4,
        )
        reservation = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            f"{care_date}T09:00:00Z",
            f"{care_date}T15:00:00Z",
            market_code=world["provider"]["market_code"],
        )
        match_reservation(api, reservation["id"])
        confirm_reservation(api, reservation["id"], block["id"])
        set_clock(api, f"{care_date}{no_show_clock_time}")
        results.append(mark_no_show(api, reservation["id"]))
    return results


# ==========================================================================
# Tier 5 — invoice finalization
# ==========================================================================
def create_invoice(
    api: ApiClient, employer_id: str, period_start: str, period_end: str, **overrides: Any
) -> Dict[str, Any]:
    payload = f.invoice_payload(period_start, period_end, **overrides)
    return get_success_data(api.create_employer_invoice(employer_id, payload, NETWORK_ADMIN))


def read_invoice(api: ApiClient, invoice_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_invoice(invoice_id, NETWORK_ADMIN))


def read_invoice_lines(api: ApiClient, invoice_id: str) -> List[Dict[str, Any]]:
    body = api.list_invoice_lines(invoice_id, NETWORK_ADMIN, params={"limit": 100}).json()
    return body["data"]


def issue_invoice(api: ApiClient, invoice_id: str) -> Dict[str, Any]:
    return get_success_data(api.issue_invoice(invoice_id, NETWORK_ADMIN))


def pay_invoice(api: ApiClient, invoice_id: str, amount_cents: int) -> Dict[str, Any]:
    payload = f.payment_payload(amount_cents)
    return get_success_data(api.pay_invoice(invoice_id, payload, NETWORK_ADMIN))


def void_invoice(api: ApiClient, invoice_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = f.void_invoice_payload(**overrides)
    return get_success_data(api.void_invoice(invoice_id, payload, NETWORK_ADMIN))


def setup_issued_invoice(
    api: ApiClient, employer_id: str, period_start: str, period_end: str
) -> Dict[str, Any]:
    """A DRAFT invoice swept and issued in one step."""
    invoice = create_invoice(api, employer_id, period_start, period_end)
    return issue_invoice(api, invoice["id"])


def setup_paid_invoice(
    api: ApiClient, employer_id: str, period_start: str, period_end: str
) -> Dict[str, Any]:
    issued = setup_issued_invoice(api, employer_id, period_start, period_end)
    return pay_invoice(api, issued["id"], issued["total_cents"])


def setup_voided_invoice(
    api: ApiClient, employer_id: str, period_start: str, period_end: str, **overrides: Any
) -> Dict[str, Any]:
    invoice = create_invoice(api, employer_id, period_start, period_end)
    return void_invoice(api, invoice["id"], **overrides)


# ==========================================================================
# Small time helpers
# ==========================================================================
def at(date: str, time: str) -> str:
    """Compose a whole-second UTC instant from a calendar date and a clock time."""
    return f"{date}T{time}Z"


COLD_START = COLD_START_UTC

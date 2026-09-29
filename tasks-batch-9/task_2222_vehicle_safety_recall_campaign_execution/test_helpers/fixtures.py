"""
Composite setup helpers.

Tier 1 primitives wrap a single write and return its `data`. Tiers 2-5 compose
those primitives into the recurring campaign states the suite needs: a filed
campaign, a released remedy, a stocked dealer, a submitted or approved claim, a
mailed wave, a monitored campaign, and a campaign standing at the closure gates.

Every helper takes the `ApiClient` as its first argument and uses
`get_success_data`, so a broken setup step fails loudly with the server's own
error id rather than silently poisoning the assertions that follow.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .test_users import (
    CLAIMS_AUDITOR,
    COMPLIANCE_OFFICER_1,
    OPERATIONS_MANAGER,
    SAFETY_ENGINEER_1,
    SAFETY_ENGINEER_2,
    make_dealer_service_manager_headers,
)
from .types import (
    AdjudicationDecision,
    AuditDecision,
    RegionCode,
    WaveType,
)

# The instant the suite pins the logical clock to before most scenarios, one
# business day after the startup default.
DEFAULT_SCENARIO_CLOCK = "2026-08-03T09:00:00Z"
DEFAULT_DETERMINATION_DATE = "2026-08-03T09:00:00Z"


# ─────────────────────────────────────────────────────
# Tier 1 — single-write primitives
# ─────────────────────────────────────────────────────

def set_clock(api, to_iso8601: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Reposition the logical clock; answers with the resulting `current_utc`."""
    return get_success_data(
        api.set_clock(f.clock_payload(to_iso8601=to_iso8601), headers or OPERATIONS_MANAGER)
    )


def create_campaign(api, headers: Optional[Dict] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_campaign(f.campaign_payload(**overrides), headers or SAFETY_ENGINEER_1)
    )


def create_vehicle(api, headers: Optional[Dict] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_vehicle(f.vehicle_payload(**overrides), headers or OPERATIONS_MANAGER)
    )


def add_population_rule(api, campaign_id: str, headers: Optional[Dict] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_population_rule(
            campaign_id, f.population_rule_payload(**overrides), headers or SAFETY_ENGINEER_1
        )
    )


def determine_defect(
    api,
    campaign_id: str,
    determination_date: str = DEFAULT_DETERMINATION_DATE,
    headers: Optional[Dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.defect_determination_payload(
        defect_determination_date=determination_date, **overrides
    )
    return get_success_data(
        api.record_defect_determination(campaign_id, payload, headers or SAFETY_ENGINEER_1)
    )


def run_population(api, campaign_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.run_population(campaign_id, {}, headers or SAFETY_ENGINEER_1))


def file_defect_notice(api, campaign_id: str, headers: Optional[Dict] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_filing(campaign_id, f.defect_notice_payload(**overrides), headers or COMPLIANCE_OFFICER_1)
    )


def file_quarterly(
    api, campaign_id: str, report_period: str = "2026Q3", headers: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_filing(
            campaign_id,
            f.quarterly_filing_payload(report_period=report_period, **overrides),
            headers or COMPLIANCE_OFFICER_1,
        )
    )


def add_labor_operation(api, campaign_id: str, headers: Optional[Dict] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_labor_operation(
            campaign_id, f.labor_operation_payload(**overrides), headers or SAFETY_ENGINEER_1
        )
    )


def add_remedy_part(api, campaign_id: str, headers: Optional[Dict] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_remedy_part(campaign_id, f.remedy_part_payload(**overrides), headers or SAFETY_ENGINEER_1)
    )


def create_dealer(api, headers: Optional[Dict] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_dealer(f.dealer_payload(**overrides), headers or OPERATIONS_MANAGER))


def suspend_dealer(api, dealer_id: str, headers: Optional[Dict] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.suspend_dealer(dealer_id, f.suspend_dealer_payload(**overrides), headers or OPERATIONS_MANAGER)
    )


def issue_interim_advisory(
    api, campaign_id: str, stop_sale: bool = False, do_not_drive: bool = True, headers: Optional[Dict] = None
) -> Dict[str, Any]:
    payload = f.interim_advisory_payload(stop_sale=stop_sale, do_not_drive=do_not_drive)
    return get_success_data(
        api.issue_interim_advisory(campaign_id, payload, headers or SAFETY_ENGINEER_1)
    )


def plan_wave(api, campaign_id: str, headers: Optional[Dict] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_notification_wave(
            campaign_id, f.notification_wave_payload(**overrides), headers or OPERATIONS_MANAGER
        )
    )


def release_wave(api, wave_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.release_wave(wave_id, {}, headers or OPERATIONS_MANAGER))


def mail_wave(api, wave_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.mail_wave(wave_id, {}, headers or OPERATIONS_MANAGER))


def cancel_wave(api, wave_id: str, headers: Optional[Dict] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.cancel_wave(wave_id, f.cancel_wave_payload(**overrides), headers or OPERATIONS_MANAGER)
    )


def log_outreach(api, affected_vehicle_id: str, headers: Optional[Dict] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_outreach_attempt(
            affected_vehicle_id, f.outreach_attempt_payload(**overrides), headers or OPERATIONS_MANAGER
        )
    )


def audit_claim(
    api, claim_id: str, decision: str = AuditDecision.APPROVE, headers: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.audit_repair_claim(claim_id, f.audit_payload(decision=decision, **overrides), headers or CLAIMS_AUDITOR)
    )


def reverse_claim(api, claim_id: str, headers: Optional[Dict] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.reverse_repair_claim(claim_id, f.reverse_claim_payload(**overrides), headers or CLAIMS_AUDITOR)
    )


def submit_reimbursement(
    api, campaign_id: str, vehicle_id: str, headers: Optional[Dict] = None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_owner_reimbursement(
            f.owner_reimbursement_payload(campaign_id, vehicle_id, **overrides),
            headers or OPERATIONS_MANAGER,
        )
    )


def request_documents(api, reimbursement_id: str, headers: Optional[Dict] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.request_reimbursement_documents(
            reimbursement_id, f.request_documents_payload(**overrides), headers or CLAIMS_AUDITOR
        )
    )


def resubmit_reimbursement(api, reimbursement_id: str, headers: Optional[Dict] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.resubmit_owner_reimbursement(
            reimbursement_id, f.resubmit_payload(**overrides), headers or OPERATIONS_MANAGER
        )
    )


def adjudicate_reimbursement(
    api,
    reimbursement_id: str,
    decision: str = AdjudicationDecision.APPROVE,
    headers: Optional[Dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.adjudicate_owner_reimbursement(
            reimbursement_id, f.adjudicate_payload(decision=decision, **overrides), headers or CLAIMS_AUDITOR
        )
    )


# ─────────────────────────────────────────────────────
# Read helpers used to thread version tokens and ids
# ─────────────────────────────────────────────────────

def campaign_version(api, campaign_id: str, headers: Optional[Dict] = None) -> int:
    """Read the campaign's current `version`, as a remedy release must."""
    return get_success_data(api.get_campaign(campaign_id, headers or SAFETY_ENGINEER_2))["version"]


def read_campaign(api, campaign_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api.get_campaign(campaign_id, headers or SAFETY_ENGINEER_1))


def part_version(api, campaign_id: str, part_number: str, headers: Optional[Dict] = None) -> int:
    """Read a remedy part's current `version`, as a parts allocation must."""
    data, _ = validate_paginated(
        api.list_remedy_parts(campaign_id, headers or OPERATIONS_MANAGER, {"part_number": part_number})
    )
    assert data, f"no remedy part {part_number!r} registered on the campaign"
    return data[0]["version"]


def read_part(api, campaign_id: str, part_number: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    data, _ = validate_paginated(
        api.list_remedy_parts(campaign_id, headers or OPERATIONS_MANAGER, {"part_number": part_number})
    )
    assert data, f"no remedy part {part_number!r} registered on the campaign"
    return data[0]


def find_affected_vehicle(api, campaign_id: str, vehicle_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Locate the affected-vehicle row joining one campaign to one build record."""
    data, _ = validate_paginated(
        api.list_affected_vehicles(
            headers or OPERATIONS_MANAGER, {"campaign_id": campaign_id, "vehicle_id": vehicle_id}
        )
    )
    assert data, f"no affected-vehicle row for campaign {campaign_id} and vehicle {vehicle_id}"
    return data[0]


def list_affected_vehicles_for(api, campaign_id: str, headers: Optional[Dict] = None) -> List[Dict[str, Any]]:
    data, _ = validate_paginated(
        api.list_affected_vehicles(headers or OPERATIONS_MANAGER, {"campaign_id": campaign_id, "limit": 100})
    )
    return data


def list_allocations_for_part(api, remedy_part_id: str, headers: Optional[Dict] = None) -> List[Dict[str, Any]]:
    data, _ = validate_paginated(
        api.list_parts_allocations(headers or OPERATIONS_MANAGER, {"remedy_part_id": remedy_part_id, "limit": 100})
    )
    return data


def list_claims_for_campaign(api, campaign_id: str, headers: Optional[Dict] = None) -> List[Dict[str, Any]]:
    data, _ = validate_paginated(
        api.list_repair_claims(headers or CLAIMS_AUDITOR, {"campaign_id": campaign_id, "limit": 100})
    )
    return data


def list_reimbursements_for_campaign(api, campaign_id: str, headers: Optional[Dict] = None) -> List[Dict[str, Any]]:
    data, _ = validate_paginated(
        api.list_owner_reimbursements(headers or CLAIMS_AUDITOR, {"campaign_id": campaign_id, "limit": 100})
    )
    return data


# ─────────────────────────────────────────────────────
# Version-threaded writes
# ─────────────────────────────────────────────────────

def release_remedy(
    api,
    campaign_id: str,
    labor_operation_id: str,
    headers: Optional[Dict] = None,
    expected_campaign_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Release the remedy, reading the campaign's current `version` first so the
    guard of PRD §2.8 is satisfied.
    """
    acting = headers or SAFETY_ENGINEER_2
    version = (
        expected_campaign_version
        if expected_campaign_version is not None
        else campaign_version(api, campaign_id, acting)
    )
    payload = f.remedy_release_payload(labor_operation_id, version, **overrides)
    return get_success_data(api.release_remedy(campaign_id, payload, acting))


def allocate_parts(
    api,
    campaign_id: str,
    part_number: str,
    remedy_part_id: str,
    dealer_id: str,
    requested_qty: int = 2,
    headers: Optional[Dict] = None,
    expected_part_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Allocate kits to a dealer, reading the remedy part's current `version`
    first so the guard of PRD §2.8 is satisfied.
    """
    acting = headers or OPERATIONS_MANAGER
    version = (
        expected_part_version
        if expected_part_version is not None
        else part_version(api, campaign_id, part_number, acting)
    )
    payload = f.parts_allocation_payload(
        remedy_part_id, dealer_id, version, requested_qty=requested_qty, **overrides
    )
    return get_success_data(api.create_parts_allocation(payload, acting))


def submit_claim(
    api,
    affected_vehicle_id: str,
    dealer_id: str,
    labor_operation_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Submit a repair claim as the dealer that performed it. The acting
    `X-User-ID` is the Dealer's own id, per PRD §2.1.
    """
    payload = f.repair_claim_payload(affected_vehicle_id, dealer_id, labor_operation_id, **overrides)
    return get_success_data(
        api.create_repair_claim(payload, make_dealer_service_manager_headers(dealer_id))
    )


def book_appointment(api, affected_vehicle_id: str, dealer_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = f.schedule_payload(dealer_id, **overrides)
    return get_success_data(
        api.schedule_repair(affected_vehicle_id, payload, make_dealer_service_manager_headers(dealer_id))
    )


# ─────────────────────────────────────────────────────
# Tier 2 — campaign lifecycle shortcuts
# ─────────────────────────────────────────────────────

def draft_campaign(api, clock: Optional[str] = DEFAULT_SCENARIO_CLOCK, **overrides: Any) -> Dict[str, Any]:
    """A campaign standing in DRAFT with the logical clock pinned."""
    if clock:
        set_clock(api, clock)
    campaign = create_campaign(api, **overrides)
    return {"campaign": campaign, "campaign_id": campaign["id"]}


def determined_campaign(
    api,
    clock: Optional[str] = DEFAULT_SCENARIO_CLOCK,
    determination_date: str = DEFAULT_DETERMINATION_DATE,
    **overrides: Any,
) -> Dict[str, Any]:
    """A campaign carried from DRAFT to DEFECT_DETERMINED."""
    state = draft_campaign(api, clock=clock, **overrides)
    state["campaign"] = determine_defect(api, state["campaign_id"], determination_date)
    return state


def campaign_with_population(
    api,
    vehicles: Optional[List[Dict[str, Any]]] = None,
    clock: Optional[str] = DEFAULT_SCENARIO_CLOCK,
    determination_date: str = DEFAULT_DETERMINATION_DATE,
    rule: Optional[Dict[str, Any]] = None,
    campaign: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    A DEFECT_DETERMINED campaign with build records ingested, one INCLUDE rule
    attached, and the matching pass run.

    `vehicles` is a list of `vehicle_payload` override dicts; the default is one
    NE SOLD build inside the default rule's window and part range.
    """
    state = draft_campaign(api, clock=clock, **(campaign or {}))
    campaign_id = state["campaign_id"]

    specs = vehicles if vehicles is not None else [{}]
    state["vehicles"] = [create_vehicle(api, **spec) for spec in specs]
    state["vehicle"] = state["vehicles"][0]
    state["vehicle_id"] = state["vehicles"][0]["id"]

    state["rule"] = add_population_rule(api, campaign_id, **(rule or {}))
    state["rule_id"] = state["rule"]["id"]

    state["campaign"] = determine_defect(api, campaign_id, determination_date)
    state["population_run"] = run_population(api, campaign_id)
    state["campaign"] = read_campaign(api, campaign_id)
    return state


def filed_campaign(
    api,
    vehicles: Optional[List[Dict[str, Any]]] = None,
    clock: Optional[str] = DEFAULT_SCENARIO_CLOCK,
    determination_date: str = DEFAULT_DETERMINATION_DATE,
    rule: Optional[Dict[str, Any]] = None,
    campaign: Optional[Dict[str, Any]] = None,
    narrative: Optional[str] = None,
) -> Dict[str, Any]:
    """
    The suite's base state: a campaign whose population is materialised and
    whose Part 573 defect notice has been filed, so `campaign_status` is FILED.
    """
    state = campaign_with_population(
        api,
        vehicles=vehicles,
        clock=clock,
        determination_date=determination_date,
        rule=rule,
        campaign=campaign,
    )
    kwargs = {"narrative": narrative} if narrative else {}
    state["defect_notice"] = file_defect_notice(api, state["campaign_id"], **kwargs)
    state["campaign"] = read_campaign(api, state["campaign_id"])
    return state


# ─────────────────────────────────────────────────────
# Tier 3 — remedy engineering and dealer stocking
# ─────────────────────────────────────────────────────

def campaign_with_remedy(
    api,
    vehicles: Optional[List[Dict[str, Any]]] = None,
    labor_operation: Optional[Dict[str, Any]] = None,
    remedy_part: Optional[Dict[str, Any]] = None,
    interim_advisory: Optional[Dict[str, Any]] = None,
    release: bool = True,
    **filed_kwargs: Any,
) -> Dict[str, Any]:
    """
    A FILED campaign with a labor operation and a remedy part registered, and
    (unless `release=False`) the remedy released so `remedy_status` is
    REMEDY_RELEASED.

    Pass `interim_advisory={"stop_sale": ..., "do_not_drive": ...}` to route the
    campaign through INTERIM_NOTIFIED/INTERIM_ONLY first.
    """
    state = filed_campaign(api, vehicles=vehicles, **filed_kwargs)
    campaign_id = state["campaign_id"]

    if interim_advisory is not None:
        state["campaign"] = issue_interim_advisory(api, campaign_id, **interim_advisory)

    state["labor_operation"] = add_labor_operation(api, campaign_id, **(labor_operation or {}))
    state["labor_operation_id"] = state["labor_operation"]["id"]
    state["remedy_part"] = add_remedy_part(api, campaign_id, **(remedy_part or {}))
    state["remedy_part_id"] = state["remedy_part"]["id"]
    state["part_number"] = state["remedy_part"]["part_number"]

    if release:
        state["campaign_version_before_release"] = campaign_version(api, campaign_id)
        state["campaign"] = release_remedy(
            api,
            campaign_id,
            state["labor_operation_id"],
            expected_campaign_version=state["campaign_version_before_release"],
        )
    return state


def campaign_with_allocation(
    api,
    requested_qty: int = 2,
    dealer: Optional[Dict[str, Any]] = None,
    **remedy_kwargs: Any,
) -> Dict[str, Any]:
    """A campaign with a released remedy and one dealer holding kits."""
    state = campaign_with_remedy(api, **remedy_kwargs)
    state["dealer"] = create_dealer(api, **(dealer or {}))
    state["dealer_id"] = state["dealer"]["id"]
    state["dealer_headers"] = make_dealer_service_manager_headers(state["dealer_id"])
    state["allocation"] = allocate_parts(
        api,
        state["campaign_id"],
        state["part_number"],
        state["remedy_part_id"],
        state["dealer_id"],
        requested_qty=requested_qty,
    )
    state["allocation_id"] = state["allocation"]["id"]
    return state


# ─────────────────────────────────────────────────────
# Tier 4 — claims, accumulation and threshold targeting
# ─────────────────────────────────────────────────────

def campaign_with_submitted_claim(
    api,
    claim: Optional[Dict[str, Any]] = None,
    **allocation_kwargs: Any,
) -> Dict[str, Any]:
    """A campaign whose first affected-vehicle row carries a SUBMITTED claim."""
    state = campaign_with_allocation(api, **allocation_kwargs)
    row = find_affected_vehicle(api, state["campaign_id"], state["vehicle_id"])
    state["affected_vehicle"] = row
    state["affected_vehicle_id"] = row["id"]
    state["claim"] = submit_claim(
        api,
        row["id"],
        state["dealer_id"],
        state["labor_operation_id"],
        **(claim or {}),
    )
    state["claim_id"] = state["claim"]["id"]
    return state


def campaign_with_approved_claim(
    api,
    claim: Optional[Dict[str, Any]] = None,
    **allocation_kwargs: Any,
) -> Dict[str, Any]:
    """A campaign whose first affected-vehicle row stands at REMEDIED."""
    state = campaign_with_submitted_claim(api, claim=claim, **allocation_kwargs)
    state["claim"] = audit_claim(api, state["claim_id"], AuditDecision.APPROVE)
    state["campaign"] = read_campaign(api, state["campaign_id"])
    return state


def mailed_remedy_wave(
    api,
    state: Dict[str, Any],
    scheduled_mail_date: str = "2026-08-03",
    wave_type: str = WaveType.REMEDY,
    target_region_code: str = RegionCode.NE,
) -> Dict[str, Any]:
    """
    Plan, approve and drop one wave on an existing campaign state, carrying the
    campaign to OWNER_NOTIFIED when the wave is a REMEDY or FOLLOW_UP drop.
    """
    wave = plan_wave(
        api,
        state["campaign_id"],
        wave_type=wave_type,
        target_region_code=target_region_code,
        scheduled_mail_date=scheduled_mail_date,
    )
    state["wave"] = release_wave(api, wave["id"])
    state["wave"] = mail_wave(api, wave["id"])
    state["wave_id"] = wave["id"]
    state["campaign"] = read_campaign(api, state["campaign_id"])
    return state


def monitored_campaign(
    api,
    report_period: str = "2026Q3",
    scheduled_mail_date: str = "2026-08-03",
    **claim_kwargs: Any,
) -> Dict[str, Any]:
    """
    A campaign carried all the way into MONITORING: population matched, defect
    notice filed, remedy released, kits allocated, one claim approved, one
    REMEDY wave mailed, and one quarterly report accepted.
    """
    state = campaign_with_approved_claim(api, **claim_kwargs)
    state = mailed_remedy_wave(api, state, scheduled_mail_date=scheduled_mail_date)
    state["quarterly_filing"] = file_quarterly(api, state["campaign_id"], report_period=report_period)
    state["campaign"] = read_campaign(api, state["campaign_id"])
    return state


# ─────────────────────────────────────────────────────
# Tier 5 — finalisation and terminal states
# ─────────────────────────────────────────────────────

def campaign_at_closure_gates(
    api,
    first_period: str = "2026Q3",
    second_period: str = "2026Q4",
    **claim_kwargs: Any,
) -> Dict[str, Any]:
    """
    A MONITORING campaign with two quarterly filings on record, which is the
    reporting gate of PRD §3.9. Whether the remaining gates hold depends on the
    population the caller passes in.
    """
    state = monitored_campaign(api, report_period=first_period, **claim_kwargs)
    state["quarterly_filing_2"] = file_quarterly(api, state["campaign_id"], report_period=second_period)
    state["campaign"] = read_campaign(api, state["campaign_id"])
    return state


def superseding_campaign(
    api, superseded_campaign_id: str, campaign_number: str = "26V-999", **overrides: Any
) -> Dict[str, Any]:
    """Open a new campaign file pointed at the campaign it replaces."""
    return create_campaign(
        api,
        campaign_number=campaign_number,
        supersedes_campaign_id=superseded_campaign_id,
        **overrides,
    )

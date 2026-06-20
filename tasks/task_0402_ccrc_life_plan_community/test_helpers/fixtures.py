"""Composite setup helpers for multi-step test prerequisites (PRD §3).

The harness restarts the server before every test, so every fixture builds its
preconditions from scratch using only PRD-declared endpoints, against an empty
database.

Identity threading (PRD §2.1):
  * FinanceOfficer, AdmissionsDirector, and CareCoordinator are opaque; the
    shared builder functions are safe.
  * Resident is entity_backed:Resident; resident-acting calls (votes) use
    make_resident_headers(resident_id) with the real Resident.id.

Setup helpers use get_success_data (lenient validator) so a failed precondition
surfaces as a clear "setup failed" error rather than a misleading assertion
failure deep inside a test.
"""
from typing import List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_bed_reservation_payload,
    create_care_transition_payload,
    create_community_payload,
    create_contract_plan_payload,
    create_council_payload,
    create_resident_payload,
    create_residency_payload,
    create_resolution_payload,
    create_second_person_payload,
    create_unit_payload,
    create_waitlist_entry_payload,
)
from .test_users import (
    make_admissions_director_headers,
    make_care_coordinator_headers,
    make_finance_officer_headers,
    make_resident_headers,
)

FO = make_finance_officer_headers()
AD = make_admissions_director_headers()
CC = make_care_coordinator_headers()


# ─── Tier 1: single-entity creators ─────────────────────────────────────────

def create_community(
    name: str = "Test Community",
    actuarial_discount_rate_bps: int = 0,
    **overrides,
) -> dict:
    """Create a Community (PRD §3.1). FinanceOfficer-owned."""
    payload = create_community_payload(
        name=name,
        actuarial_discount_rate_bps=actuarial_discount_rate_bps,
        **overrides,
    )
    return get_success_data(api_client.create_community(payload, FO))


def create_plan(community_id: str, name: str = "Test Plan", **overrides) -> dict:
    """Create a ContractPlan under a community (PRD §3.1)."""
    payload = create_contract_plan_payload(
        community_id=community_id, name=name, **overrides,
    )
    return get_success_data(api_client.create_contract_plan(payload, FO))


def create_unit(
    community_id: str,
    unit_number: str = "U-1",
    care_level: str = "INDEPENDENT",
    **overrides,
) -> dict:
    """Create a Unit (PRD §3.1). AdmissionsDirector-owned."""
    payload = create_unit_payload(
        community_id=community_id, unit_number=unit_number,
        care_level=care_level, **overrides,
    )
    return get_success_data(api_client.create_unit(payload, AD))


def create_resident(
    community_id: str,
    full_name: str = "Test Resident",
    date_of_birth: str = "1930-01-01",
    **overrides,
) -> dict:
    """Register a Resident (PRD §3.1)."""
    payload = create_resident_payload(
        community_id=community_id, full_name=full_name,
        date_of_birth=date_of_birth, **overrides,
    )
    return get_success_data(api_client.create_resident(payload, AD))


def create_residency(
    community_id: str, primary_resident_id: str, contract_plan_id: str,
) -> dict:
    """Open a residency in DEPOSIT_HELD (PRD §3.2)."""
    payload = create_residency_payload(
        community_id=community_id,
        primary_resident_id=primary_resident_id,
        contract_plan_id=contract_plan_id,
    )
    return get_success_data(api_client.create_residency(payload, AD))


def create_council(community_id: str, name: str = "Council", **overrides) -> dict:
    """Create the resident council for a community (PRD §3.8)."""
    payload = create_council_payload(
        community_id=community_id, name=name, **overrides,
    )
    return get_success_data(api_client.create_council(payload, FO))


def create_resolution(council_id: str, title: str = "Topic") -> dict:
    """Draft a council resolution in DRAFT (PRD §3.8)."""
    payload = create_resolution_payload(council_id=council_id, title=title)
    return get_success_data(api_client.create_resolution(payload, FO))


def advance_clock(community_id: str, by_periods: int) -> dict:
    """Advance the community clock by N periods (PRD §2.5)."""
    return get_success_data(
        api_client.advance_clock(community_id, {"by_periods": by_periods}, FO),
    )


def get_residency(residency_id: str) -> dict:
    return get_success_data(api_client.get_residency(residency_id, FO))


def get_community(community_id: str) -> dict:
    return get_success_data(api_client.get_community(community_id, FO))


def get_unit(unit_id: str) -> dict:
    return get_success_data(api_client.get_unit(unit_id, FO))


def get_bed_reservation(brid: str) -> dict:
    return get_success_data(api_client.get_bed_reservation(brid, FO))


def get_waitlist_entry(wid: str) -> dict:
    return get_success_data(api_client.get_waitlist_entry(wid, FO))


def list_refund_disbursements(residency_id: str) -> List[dict]:
    resp = api_client.list_refund_disbursements(FO, params={"residency_id": residency_id})
    return get_success_data(resp)


# ─── Tier 2: catalogue setup ──────────────────────────────────────────

def setup_community_and_plan(
    community_name: str = "Test Community",
    actuarial_discount_rate_bps: int = 0,
    plan_overrides: Optional[dict] = None,
    **community_overrides,
) -> Tuple[dict, dict]:
    """Active community + one contract plan. Returns (community, plan)."""
    community = create_community(
        name=community_name,
        actuarial_discount_rate_bps=actuarial_discount_rate_bps,
        **community_overrides,
    )
    plan = create_plan(community["id"], **(plan_overrides or {}))
    return community, plan


# ─── Tier 3: residency lifecycle shortcuts ──────────────────────────────────

def open_residency(community: dict, plan: dict, resident_name: str = "Res",
                   dob: str = "1930-01-01", priority_score: Optional[int] = None) -> dict:
    """Create a resident and open a DEPOSIT_HELD residency. Returns residency."""
    extra = {}
    if priority_score is not None:
        extra["priority_score"] = priority_score
    resident = create_resident(
        community["id"], full_name=resident_name, date_of_birth=dob, **extra,
    )
    residency = create_residency(community["id"], resident["id"], plan["id"])
    # carry the resident id forward for vote / ownership threading
    residency = dict(residency)
    residency["_primary_resident_id"] = resident["id"]
    return residency


def reserve_residency_via_assign(community: dict, plan: dict, unit: dict,
                                 resident_name: str = "Res",
                                 dob: str = "1930-01-01") -> dict:
    """Open a residency and assign an INDEPENDENT unit (→ RESERVED).
    Returns the RESERVED residency body (carrying its current version)."""
    residency = open_residency(community, plan, resident_name, dob)
    reserved = get_success_data(
        api_client.assign_unit(residency["id"], {"unit_id": unit["id"]}, AD),
    )
    reserved = dict(reserved)
    reserved["_primary_resident_id"] = residency["_primary_resident_id"]
    return reserved


def activate_residency(residency: dict) -> dict:
    """Activate a RESERVED residency using its current version (→ ACTIVE).
    Returns the ACTIVE residency body."""
    activated = get_success_data(api_client.activate_residency(
        residency["id"],
        {"expected_residency_version": residency["version"]},
        AD,
    ))
    activated = dict(activated)
    if "_primary_resident_id" in residency:
        activated["_primary_resident_id"] = residency["_primary_resident_id"]
    return activated


def setup_active_residency(
    community_name: str = "Test Community",
    actuarial_discount_rate_bps: int = 0,
    plan_overrides: Optional[dict] = None,
    resident_name: str = "Res",
    dob: str = "1930-01-01",
    unit_number: str = "IND-1",
    **community_overrides,
) -> Tuple[dict, dict, dict, dict]:
    """Community + plan + INDEPENDENT unit + one ACTIVE residency.

    Returns (community, plan, unit, active_residency). The residency dict
    carries its post-activation version and a `_primary_resident_id` key for
    downstream vote / ownership threading.
    """
    community, plan = setup_community_and_plan(
        community_name=community_name,
        actuarial_discount_rate_bps=actuarial_discount_rate_bps,
        plan_overrides=plan_overrides,
        **community_overrides,
    )
    unit = create_unit(community["id"], unit_number=unit_number,
                       care_level="INDEPENDENT")
    reserved = reserve_residency_via_assign(community, plan, unit,
                                            resident_name=resident_name, dob=dob)
    active = activate_residency(reserved)
    return community, plan, unit, active


# ─── Tier 4: bed reservation / care-continuum setup ───────────────────

def hold_bed(residency_id: str, skilled_unit_id: str,
             hold_expiry_period: int) -> dict:
    """Hold a SKILLED bed for a residency (→ HELD). Returns reservation."""
    payload = create_bed_reservation_payload(
        residency_id=residency_id, unit_id=skilled_unit_id,
        hold_expiry_period=hold_expiry_period,
    )
    return get_success_data(api_client.create_bed_reservation(payload, CC))


def occupy_bed(brid: str) -> dict:
    return get_success_data(api_client.occupy_bed_reservation(brid, CC))


def propose_and_apply_transition(residency_id: str, to_level: str) -> dict:
    """Propose then apply a one-step care transition (→ APPLIED). Returns the
    applied transition."""
    proposed = get_success_data(api_client.create_care_transition(
        create_care_transition_payload(residency_id, to_level), CC,
    ))
    return get_success_data(
        api_client.apply_care_transition(proposed["id"], CC),
    )


def setup_residency_in_skilled_with_occupied_bed(
    community_name: str = "Skilled Town",
    plan_overrides: Optional[dict] = None,
    hold_expiry_period: int = 10,
) -> Tuple[dict, dict, dict, dict, dict]:
    """ACTIVE residency stepped INDEPENDENT→ASSISTED→SKILLED with an OCCUPIED
    skilled bed. Returns (community, plan, ind_unit, skilled_unit, residency).
    """
    community, plan = setup_community_and_plan(
        community_name=community_name, plan_overrides=plan_overrides,
    )
    ind_unit = create_unit(community["id"], unit_number="SKI-IND",
                           care_level="INDEPENDENT")
    skilled_unit = create_unit(community["id"], unit_number="SKI-SK",
                               care_level="SKILLED", bed_capacity=1)
    reserved = reserve_residency_via_assign(community, plan, ind_unit)
    active = activate_residency(reserved)
    brid = hold_bed(active["id"], skilled_unit["id"], hold_expiry_period)
    occupy_bed(brid["id"])
    propose_and_apply_transition(active["id"], "ASSISTED")
    propose_and_apply_transition(active["id"], "SKILLED")
    return community, plan, ind_unit, skilled_unit, active


# ─── Tier 5: termination / refund setup ───────────────────────────────

def terminate_residency(residency_id: str, reason: str,
                        expected_version: int) -> dict:
    """Terminate a residency (→ TERMINATED_*). Returns the terminated body."""
    return get_success_data(api_client.terminate_residency(
        residency_id,
        {"reason": reason, "expected_residency_version": expected_version},
        AD,
    ))


def setup_terminated_with_refund(
    community_name: str = "Refund Town",
    plan_overrides: Optional[dict] = None,
    occupied_months: int = 0,
    reason: str = "VOLUNTARY",
) -> Tuple[dict, dict, dict, dict]:
    """ACTIVE residency advanced to `occupied_months`, then terminated.
    Returns (community, plan, residency_pre_terminate, refund_disbursement).
    """
    community, plan, _unit, active = setup_active_residency(
        community_name=community_name, plan_overrides=plan_overrides,
    )
    if occupied_months:
        advance_clock(community["id"], occupied_months)
    fresh = get_residency(active["id"])
    terminate_residency(fresh["id"], reason, fresh["version"])
    disbursements = list_refund_disbursements(fresh["id"])
    refund = disbursements[0] if disbursements else None
    return community, plan, fresh, refund


# ─── Tier 6: council / governance setup ───────────────────────────────

def setup_open_resolution_with_active_residencies(
    num_residencies: int = 1,
    quorum_pct_bps: Optional[int] = None,
    community_name: str = "Vote Town",
) -> Tuple[dict, dict, dict, List[dict]]:
    """Community + council + N ACTIVE residencies + one OPEN resolution.

    eligible_voter_count is snapshotted at open time, so all N residencies are
    ACTIVE before the resolution is opened. Returns
    (community, council, resolution, active_residencies). Each residency dict
    carries `_primary_resident_id` for vote threading.
    """
    community, plan = setup_community_and_plan(community_name=community_name)
    council_overrides = {}
    if quorum_pct_bps is not None:
        council_overrides["quorum_pct_bps"] = quorum_pct_bps
    council = create_council(community["id"], **council_overrides)

    residencies: List[dict] = []
    for i in range(num_residencies):
        unit = create_unit(community["id"], unit_number=f"V-{i}",
                           care_level="INDEPENDENT")
        reserved = reserve_residency_via_assign(
            community, plan, unit, resident_name=f"Voter {i}",
            dob=f"1930-01-0{(i % 9) + 1}",
        )
        active = activate_residency(reserved)
        residencies.append(active)

    resolution = create_resolution(council["id"], title="Raise dues")
    resolution = get_success_data(
        api_client.open_resolution(resolution["id"], FO),
    )
    return community, council, resolution, residencies


def cast_vote(resolution_id: str, residency: dict, choice: str) -> dict:
    """Cast a vote as the residency's primary Resident (PRD §3.8)."""
    headers = make_resident_headers(residency["_primary_resident_id"])
    return get_success_data(api_client.cast_vote(
        resolution_id,
        {"residency_id": residency["id"], "choice": choice},
        headers,
    ))


# ─── Tier 7: waitlist setup ───────────────────────────────────────────

def enqueue_waitlist(community: dict, residency: dict,
                     target_care_level: str = "INDEPENDENT") -> dict:
    """Enqueue a DEPOSIT_HELD residency onto the waitlist (→ WAITLISTED).
    Returns the PENDING waitlist entry."""
    payload = create_waitlist_entry_payload(
        community_id=community["id"], residency_id=residency["id"],
        target_care_level=target_care_level,
    )
    return get_success_data(api_client.create_waitlist_entry(payload, AD))


def setup_two_waitlisted_for_independent(
    community_name: str = "Waitlist Town",
) -> Tuple[dict, dict, dict, dict, dict, dict]:
    """Two DEPOSIT_HELD residencies both WAITLISTED for INDEPENDENT (r1 enqueued
    first so rank 1, r2 rank 2), and one AVAILABLE INDEPENDENT unit.

    Returns (community, plan, unit, r1, w1, w2) where w2 is the rank-2 entry.
    """
    community, plan = setup_community_and_plan(community_name=community_name)
    unit = create_unit(community["id"], unit_number="WL-IND",
                       care_level="INDEPENDENT")
    r1 = open_residency(community, plan, resident_name="WL One",
                       dob="1932-01-01", priority_score=0)
    r2 = open_residency(community, plan, resident_name="WL Two",
                       dob="1931-01-01", priority_score=0)
    w1 = enqueue_waitlist(community, r1, "INDEPENDENT")
    w2 = enqueue_waitlist(community, r2, "INDEPENDENT")
    return community, plan, unit, r1, w1, w2


def generate_reserve_report(community_id: str) -> dict:
    """Generate an actuarial reserve disclosure (PRD §3.6). Returns report body."""
    return get_success_data(
        api_client.create_reserve_report(community_id, {}, FO),
    )

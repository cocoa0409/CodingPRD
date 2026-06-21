"""Composite setup helpers for multi-step test prerequisites.

Each fixture builds its preconditions from scratch using only PRD-declared
endpoints; the test harness restarts the server before every test, so every
fixture starts against an empty database.

Identity threading (PRD §2.1):
  * HomeOwner writes MUST use make_homeowner_headers(owner_id) because
    X-User-ID must equal the acting Owner.id for ownership-gated transitions.
  * The other five roles are opaque per PRD §2.1; the shared constants in
    test_users.py are safe.

Setup helpers use get_success_data from the framework so a failed setup
surfaces as a clear "setup failed" error rather than a misleading assertion
failure deep inside a test.
"""
from typing import Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_acc_request_payload,
    create_assessment_payload,
    create_community_payload,
    create_election_payload,
    create_owner_payload,
    create_payment_payload,
    create_property_payload,
    create_reserve_component_payload,
    create_reserve_study_payload,
    create_violation_payload,
    create_vote_payload,
)
from .test_users import (
    make_acc_member_headers,
    make_board_president_headers,
    make_board_secretary_headers,
    make_homeowner_headers,
    make_platform_admin_headers,
    make_treasurer_headers,
)


# ─── Clock ────────────────────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Advance the server wall clock (PRD §2.5; requires PlatformAdmin)."""
    return get_success_data(
        api_client.set_clock(to_iso8601, make_platform_admin_headers()),
    )


# ─── Tier 1: single-entity creators ───────────────────────────────────────

def create_community(
    name: str = "Test HOA",
    fiscal_year_start_month: int = 1,
    regular_assessment_cents: int = 30000,
    **overrides,
) -> dict:
    """Create a Community (PRD §3.1). Defaults exercise the implicit fallbacks
    enumerated by PRD §3.1 for late-fee, lien, election, and inflation knobs.
    """
    payload = create_community_payload(
        name=name,
        fiscal_year_start_month=fiscal_year_start_month,
        regular_assessment_cents=regular_assessment_cents,
        **overrides,
    )
    return get_success_data(api_client.create_community(
        payload, make_platform_admin_headers(),
    ))


def create_owner(
    community_id: str,
    email: str = "owner@example.com",
    full_name: str = "Test Owner",
) -> dict:
    """Create an Owner under a Community (PRD §3.1)."""
    payload = create_owner_payload(
        community_id=community_id, email=email, full_name=full_name,
    )
    return get_success_data(api_client.create_owner(
        payload, make_platform_admin_headers(),
    ))


def create_property(
    community_id: str,
    owner_id: str,
    unit_label: str = "U-1",
) -> dict:
    """Create a Property bound to an Owner (PRD §3.1)."""
    payload = create_property_payload(
        community_id=community_id, owner_id=owner_id, unit_label=unit_label,
    )
    return get_success_data(api_client.create_property(
        payload, make_platform_admin_headers(),
    ))


def create_assessment(
    property_id: str,
    kind: str = "REGULAR",
    principal_cents: int = 30000,
    due_date: str = "2027-01-01T00:00:00Z",
) -> dict:
    """Bill an Assessment (PRD §3.2; Treasurer-exclusive)."""
    payload = create_assessment_payload(
        property_id=property_id,
        kind=kind,
        principal_cents=principal_cents,
        due_date=due_date,
    )
    return get_success_data(api_client.create_assessment(
        payload, make_treasurer_headers(),
    ))


def apply_payment(
    assessment_id: str,
    amount_cents: int,
    expected_assessment_version: int,
    as_owner_id: Optional[str] = None,
) -> dict:
    """Apply a payment (PRD §3.2). Defaults to Treasurer; pass `as_owner_id`
    to call as a HomeOwner with proper identity threading."""
    payload = create_payment_payload(
        assessment_id=assessment_id,
        amount_cents=amount_cents,
        expected_assessment_version=expected_assessment_version,
    )
    headers = (
        make_homeowner_headers(as_owner_id)
        if as_owner_id is not None
        else make_treasurer_headers()
    )
    return get_success_data(api_client.create_payment(payload, headers))


def create_violation(
    property_id: str,
    category: str = "NOISE",
) -> dict:
    """Open a Violation (PRD §3.5; BoardSecretary-exclusive)."""
    payload = create_violation_payload(property_id=property_id, category=category)
    return get_success_data(api_client.create_violation(
        payload, make_board_secretary_headers(),
    ))


def create_acc_request(
    property_id: str,
    owner_id: str,
    scope: str = "APPEARANCE",
    description: str = "Paint exterior trim",
) -> dict:
    """Submit an ACCRequest (PRD §3.6; HomeOwner with ownership)."""
    payload = create_acc_request_payload(
        property_id=property_id, scope=scope, description=description,
    )
    return get_success_data(api_client.create_acc_request(
        payload, make_homeowner_headers(owner_id),
    ))


def create_election(
    community_id: str,
    cycle_label: str = "FY2026",
    opens_at: str = "2026-02-01T00:00:00Z",
    closes_at: str = "2026-02-16T00:00:00Z",
) -> dict:
    """Draft an election (PRD §3.7; BoardSecretary-exclusive)."""
    payload = create_election_payload(
        community_id=community_id,
        cycle_label=cycle_label,
        opens_at=opens_at,
        closes_at=closes_at,
    )
    return get_success_data(api_client.create_election(
        payload, make_board_secretary_headers(),
    ))


def open_election(election_id: str, expected_community_version: int) -> dict:
    """Open an election (PRD §3.7). The OCC field per PRD §2.8 is required."""
    return get_success_data(api_client.open_election(
        election_id, expected_community_version, make_board_secretary_headers(),
    ))


def cast_vote(
    election_id: str,
    owner_id: str,
    candidate_name: str = "Alice",
) -> dict:
    """Owner casts a ballot (PRD §3.7; HomeOwner with ownership)."""
    payload = create_vote_payload(
        election_id=election_id, owner_id=owner_id, candidate_name=candidate_name,
    )
    return get_success_data(api_client.create_vote(
        payload, make_homeowner_headers(owner_id),
    ))


def create_reserve_component(
    community_id: str,
    label: str = "Roof - Building A",
    useful_life_years: int = 20,
    remaining_life_years: int = 5,
    replacement_cost_cents: int = 500000,
) -> dict:
    """Register a ReserveComponent (PRD §3.8; PlatformAdmin or BoardPresident)."""
    payload = create_reserve_component_payload(
        community_id=community_id,
        label=label,
        useful_life_years=useful_life_years,
        remaining_life_years=remaining_life_years,
        replacement_cost_cents=replacement_cost_cents,
    )
    return get_success_data(api_client.create_reserve_component(
        payload, make_platform_admin_headers(),
    ))


def create_reserve_study(
    community_id: str,
    fiscal_year: int = 2026,
    method: str = "COMPONENT",
    accumulated_funds_cents: int = 1_000_000,
) -> dict:
    """Create a ReserveStudy (PRD §3.8; BoardPresident-exclusive)."""
    payload = create_reserve_study_payload(
        community_id=community_id,
        fiscal_year=fiscal_year,
        method=method,
        accumulated_funds_cents=accumulated_funds_cents,
    )
    return get_success_data(api_client.create_reserve_study(
        payload, make_board_president_headers(),
    ))


# ─── Tier 2: tenant bootstrap (Community + Owner + Property) ──────────────

def bootstrap_tenant(
    community_name: str = "Test HOA",
    owner_email: str = "owner@example.com",
    owner_name: str = "Test Owner",
    unit_label: str = "U-1",
    **community_overrides,
) -> Tuple[dict, dict, dict]:
    """Single-property tenant bootstrap: Community + Owner + Property.
    Returns (community, owner, property).
    """
    community = create_community(name=community_name, **community_overrides)
    owner = create_owner(community["id"], email=owner_email, full_name=owner_name)
    prop = create_property(community["id"], owner["id"], unit_label=unit_label)
    return community, owner, prop


# ─── Tier 3: lifecycle shortcuts ──────────────────────────────────────────

def get_assessment(assessment_id: str) -> dict:
    """Re-fetch an Assessment (any non-HomeOwner role works for GET)."""
    return get_success_data(api_client.get_assessment(
        assessment_id, make_treasurer_headers(),
    ))


def get_property(property_id: str) -> dict:
    """Re-fetch a Property."""
    return get_success_data(api_client.get_property(
        property_id, make_treasurer_headers(),
    ))


def get_election(election_id: str, as_owner_id: Optional[str] = None) -> dict:
    """Re-fetch a BoardElection."""
    headers = (
        make_homeowner_headers(as_owner_id)
        if as_owner_id is not None
        else make_board_secretary_headers()
    )
    return get_success_data(api_client.get_election(election_id, headers))


def list_liens_for_property(property_id: str) -> list:
    """Return the list of liens for a given property."""
    resp = api_client.list_liens(
        make_board_secretary_headers(), params={"property_id": property_id},
    )
    data = get_success_data(resp)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("items") or data.get("data") or []
    return []


def fully_pay_assessment(assessment_id: str) -> dict:
    """Pay an Assessment in full so it transitions to PAID (PRD §3.2).
    Returns the resulting Assessment view."""
    a = get_assessment(assessment_id)
    owed = a["principal_cents"] + a["late_fee_cents"] - a["paid_cents"]
    apply_payment(assessment_id, owed, a["version"])
    return get_assessment(assessment_id)


# ─── Tier 4: scenario bootstraps shared by multiple difficulty / corner
#            instances. Each anchors a specific PRD claim and is named after
#            it so the consumer test reads like the claim itself. ──────────

def bootstrap_assessment_overdue_by_clock(
    community_name: str = "Test HOA",
    owner_email: str = "a@x.com",
    owner_name: str = "A",
    unit_label: str = "U-1",
    principal_cents: int = 30000,
    due_date: str = "2026-01-01T00:00:00Z",
    advance_to: str = "2026-02-01T00:00:00Z",
    kind: str = "REGULAR",
    **community_overrides,
) -> Tuple[dict, dict, dict, dict]:
    """Bootstrap a single Assessment that has crossed the grace boundary by
    advancing the wall clock past due_date + late_fee_grace_days (PRD §3.3).
    Returns (community, owner, property, assessment_after_overdue).
    """
    community, owner, prop = bootstrap_tenant(
        community_name=community_name,
        owner_email=owner_email,
        owner_name=owner_name,
        unit_label=unit_label,
        **community_overrides,
    )
    assessment = create_assessment(
        prop["id"], kind=kind, principal_cents=principal_cents, due_date=due_date,
    )
    set_clock(advance_to)
    assessment = get_assessment(assessment["id"])
    return community, owner, prop, assessment


def bootstrap_lien_via_cascade(
    community_name: str = "LienVille",
    owner_email: str = "d@x.com",
    owner_name: str = "D",
    unit_label: str = "U-L",
    principal_cents: int = 250000,
    due_date: str = "2026-01-01T00:00:00Z",
    advance_to: str = "2026-02-01T00:00:00Z",
    lien_threshold_cents: int = 250000,
) -> Tuple[dict, dict, dict, dict, dict]:
    """Bootstrap a Community + Owner + Property + a single large SPECIAL
    assessment, then advance the clock so the assessment turns OVERDUE,
    late_fee accrues, the property balance crosses lien_threshold_cents, and
    a FILED Lien is auto-created (PRD §3.4 cascade).
    Returns (community, owner, property, assessment, lien).
    """
    community, owner, prop, assessment = bootstrap_assessment_overdue_by_clock(
        community_name=community_name,
        owner_email=owner_email,
        owner_name=owner_name,
        unit_label=unit_label,
        principal_cents=principal_cents,
        due_date=due_date,
        advance_to=advance_to,
        kind="SPECIAL",
        lien_threshold_cents=lien_threshold_cents,
    )
    liens = list_liens_for_property(prop["id"])
    assert liens, "Cascade setup failed: expected a FILED lien on property"
    return community, owner, prop, assessment, liens[0]


def bootstrap_election_open_with_voters(
    community_name: str = "VoteVille",
    eligible_owner_count: int = 1,
    cycle_label: str = "FY-VV",
    opens_at: str = "2026-02-01T00:00:00Z",
    closes_at: str = "2026-02-16T00:00:00Z",
    clock_before_open: str = "2026-01-15T00:00:00Z",
    clock_after_open: str = "2026-02-02T00:00:00Z",
    election_quorum_pct: Optional[int] = None,
) -> Tuple[dict, list, dict]:
    """Bootstrap an OPEN BoardElection with N eligible voters (each owns at
    least one Property and has no FILED Lien). Sets the clock past `opens_at`
    so casting is permitted. Returns (community, owners, election).
    """
    if election_quorum_pct is not None:
        community = create_community(
            name=community_name, election_quorum_pct=election_quorum_pct,
        )
    else:
        community = create_community(name=community_name)
    owners = []
    for i in range(1, eligible_owner_count + 1):
        owner = create_owner(
            community["id"],
            email=f"voter{i}@vv.com",
            full_name=f"Voter{i}",
        )
        create_property(community["id"], owner["id"], unit_label=f"VV-{i}")
        owners.append(owner)
    set_clock(clock_before_open)
    election = create_election(
        community["id"],
        cycle_label=cycle_label,
        opens_at=opens_at,
        closes_at=closes_at,
    )
    election = open_election(election["id"], community["version"])
    set_clock(clock_after_open)
    return community, owners, election


def bootstrap_acc_request_on_compliant_property(
    community_name: str = "ACC-Compliant",
    scope: str = "APPEARANCE",
    description: str = "Paint trim",
) -> Tuple[dict, dict, dict, dict]:
    """Bootstrap Community + Owner + Property (posture COMPLIANT) + a
    SUBMITTED ACCRequest. Returns (community, owner, property, acc_request).
    """
    community, owner, prop = bootstrap_tenant(
        community_name=community_name,
        owner_email="acc@x.com",
        owner_name="Acc",
    )
    acc = create_acc_request(
        prop["id"], owner["id"], scope=scope, description=description,
    )
    return community, owner, prop, acc


def bootstrap_acc_request_on_suspended_property(
    community_name: str = "ACC-Suspended",
    scope: str = "LANDSCAPING",
    description: str = "Plant olive tree",
) -> Tuple[dict, dict, dict, dict, dict]:
    """Bootstrap Community + Owner + Property whose compliance_posture has
    been forced to SUSPENDED by the lien cascade, plus a SUBMITTED ACCRequest
    on that property. Returns (community, owner, property, acc_request, lien).
    """
    community, owner, prop, _assess, lien = bootstrap_lien_via_cascade(
        community_name=community_name,
        owner_email="susp@x.com",
        owner_name="Susp",
    )
    acc = create_acc_request(
        prop["id"], owner["id"], scope=scope, description=description,
    )
    return community, owner, prop, acc, lien


def bootstrap_violation_in_contested(
    community_name: str = "Posture Ville",
    category: str = "NOISE",
) -> Tuple[dict, dict, dict, dict]:
    """Bootstrap a Violation that has been contested by the owner.
    Returns (community, owner, property, violation_in_CONTESTED).
    """
    community, owner, prop = bootstrap_tenant(
        community_name=community_name,
        owner_email="pv@x.com",
        owner_name="PV",
    )
    violation = create_violation(prop["id"], category=category)
    get_success_data(api_client.contest_violation(
        violation["id"], make_homeowner_headers(owner["id"]),
    ))
    return community, owner, prop, violation


def bootstrap_paid_assessment(
    community_name: str = "Term",
    unit_label: str = "TR-1",
) -> Tuple[dict, dict, dict, dict]:
    """Bootstrap a Community + Owner + Property + Assessment paid in full
    (status == PAID). Returns (community, owner, property, paid_assessment).
    """
    community, owner, prop = bootstrap_tenant(
        community_name=community_name,
        owner_email="tr@x.com",
        owner_name="TR",
        unit_label=unit_label,
        regular_assessment_cents=10000,
    )
    a = create_assessment(
        prop["id"], kind="REGULAR", principal_cents=10000,
        due_date="2027-06-01T00:00:00Z",
    )
    apply_payment(a["id"], 10000, a["version"])
    a = get_assessment(a["id"])
    return community, owner, prop, a

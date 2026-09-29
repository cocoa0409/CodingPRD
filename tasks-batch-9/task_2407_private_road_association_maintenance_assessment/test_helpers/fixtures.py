"""Composite setup helpers.

Every helper builds its preconditions exclusively from endpoints the PRD
declares, because each test starts against an empty database.

The helpers return plain dicts of freshly-read entity bodies so callers can
assert against them directly and can re-read to observe later cascades.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .test_users import (
    make_clerk_headers,
    make_commissioner_headers,
    make_contractor_headers,
    make_member_owner_headers,
    make_secretary_headers,
    make_treasurer_headers,
)

# --------------------------------------------------------------------------
# Canonical parcel sets used by several scenarios
# --------------------------------------------------------------------------

# One parcel, 290 frontage feet, RESIDENTIAL_YEAR_ROUND, 6 trips/day.
# frontage_share_units 290.0, trip_share_units 208.0
PARCELS_SINGLE = [
    {
        "deed_book_page": "DB120-P41",
        "frontage_feet": 290,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 6,
    },
]

# Three parcels: frontage units 290 / 240 / 200 (total 730);
# trip units 208 / 155 / 200 (total 563).
PARCELS_THREE = [
    {
        "deed_book_page": "DB120-P41",
        "frontage_feet": 290,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 6,
    },
    {
        "deed_book_page": "DB120-P42",
        "frontage_feet": 400,
        "usage_class": "SEASONAL",
        "trips_per_day": 3,
    },
    {
        "deed_book_page": "DB120-P43",
        "frontage_feet": 250,
        "usage_class": "AGRICULTURAL",
        "trips_per_day": 6,
    },
]

# Four parcels: frontage units 290 / 240 / 200 / 300 (total 1030).
PARCELS_FOUR = PARCELS_THREE + [
    {
        "deed_book_page": "DB120-P44",
        "frontage_feet": 300,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 4,
    },
]

OWNER_NAMES = [
    "Ada Reyes",
    "Ben Okafor",
    "Cora Lindqvist",
    "Dov Marchetti",
    "Elin Nakamura",
    "Faris Oyelaran",
]


def _data(response) -> dict:
    """Lenient success extraction — fixtures set up state, they do not assert."""
    return get_success_data(response)


# --------------------------------------------------------------------------
# Tier 1 — single entities
# --------------------------------------------------------------------------

def setup_association(headers=None, **overrides) -> dict:
    """Register an association. Defaults: target 1_000_000, PER_PARCEL,
    STATUTORY, quorum 5000 basis points (all PRD §3.1 defaults)."""
    headers = headers or make_secretary_headers()
    return _data(api_client.create_association(f.create_association_payload(**overrides), headers))


def setup_road_segment(association_id: str, headers=None, **overrides) -> dict:
    """Record a maintained segment. Default geometry: 1600 ft long, 22 ft wide,
    8 percent grade, 1 turnout, turnaround present, no bridge."""
    headers = headers or make_commissioner_headers()
    return _data(
        api_client.create_road_segment(
            f.create_road_segment_payload(association_id, **overrides), headers
        )
    )


def setup_parcel(road_segment_id: str, headers=None, **overrides) -> dict:
    headers = headers or make_secretary_headers()
    return _data(
        api_client.create_parcel(f.create_parcel_payload(road_segment_id, **overrides), headers)
    )


def setup_member(parcel_id: str, verified: bool = True, headers=None, **overrides) -> dict:
    """Enroll a member on a parcel and, by default, verify its deed so the
    parcel becomes assessable (PRD §3.3)."""
    headers = headers or make_secretary_headers()
    member = _data(
        api_client.create_member(f.create_member_payload(parcel_id, **overrides), headers)
    )
    if verified:
        member = _data(
            api_client.verify_deed(
                member["id"], f.verify_deed_payload(member["deed_book_page"]), headers
            )
        )
    return member


def setup_assessment_roll(association_id: str, headers=None, **overrides) -> dict:
    headers = headers or make_clerk_headers()
    return _data(
        api_client.create_assessment_roll(
            f.create_assessment_roll_payload(association_id, **overrides), headers
        )
    )


def set_clock(to_iso8601: str, headers=None) -> dict:
    """Move the logical clock (PRD §2.4)."""
    headers = headers or make_clerk_headers()
    return _data(api_client.set_clock(to_iso8601, headers))


def record_access_inspection(segment_id: str, inspected_at: str, headers=None, **overrides) -> dict:
    """Record an inspection, which is the only way a segment leaves UNKNOWN."""
    headers = headers or make_commissioner_headers()
    return _data(
        api_client.create_access_inspection(
            segment_id, f.create_access_inspection_payload(inspected_at, **overrides), headers
        )
    )


def grade_segment_compliant(segment_id: str, inspected_at: str = "2026-08-01T00:00:00Z") -> dict:
    """Inspect a segment with measurements that satisfy all five conditions of
    the access standard (PRD §2.7): 22 ft wide, 8 percent grade, turnaround
    present, and enough turnouts for a 2400 ft segment."""
    return record_access_inspection(
        segment_id,
        inspected_at,
        measured_width_feet=22,
        measured_max_grade_pct=8,
        measured_turnout_count=3,
        turnaround_present=True,
    )


def grade_segment_deficient(segment_id: str, inspected_at: str = "2026-08-01T00:00:00Z") -> dict:
    """Inspect a segment too narrow to satisfy the twenty-foot minimum."""
    return record_access_inspection(
        segment_id,
        inspected_at,
        measured_width_feet=18,
        measured_max_grade_pct=8,
        measured_turnout_count=3,
        turnaround_present=True,
    )


# --------------------------------------------------------------------------
# Tier 2 — an association with a segment, parcels, and verified members
# --------------------------------------------------------------------------

def setup_membership_roll(
    parcel_specs=None,
    association_overrides=None,
    segment_overrides=None,
    verify_members=True,
) -> dict:
    """Build an association, one segment, and one verified member per parcel.

    Returns a dict with `association`, `segment`, `parcels`, `members`, and
    `member_headers` (a list of `MemberOwner` header dicts, index-aligned with
    `members`).
    """
    parcel_specs = parcel_specs if parcel_specs is not None else PARCELS_SINGLE
    association = setup_association(**(association_overrides or {}))
    segment = setup_road_segment(association["id"], **(segment_overrides or {}))

    parcels = []
    members = []
    for index, spec in enumerate(parcel_specs):
        parcel = setup_parcel(segment["id"], **spec)
        parcels.append(parcel)
        members.append(
            setup_member(
                parcel["id"],
                verified=verify_members,
                owner_name=OWNER_NAMES[index % len(OWNER_NAMES)],
                deed_book_page=parcel["deed_book_page"],
                deed_recorded_date="2019-04-12",
            )
        )

    return {
        "association": association,
        "segment": segment,
        "parcels": parcels,
        "members": members,
        "member_headers": [make_member_owner_headers(m["id"]) for m in members],
    }


# --------------------------------------------------------------------------
# Tier 3 — the annual assessment cycle
# --------------------------------------------------------------------------

def list_roll_charges(roll_id: str, headers=None) -> list:
    """All charges of a roll, in `created_at` ascending order (PRD §2.3)."""
    headers = headers or make_clerk_headers()
    response = api_client.list_assessment_charges(headers, params={"roll_id": roll_id, "limit": 100})
    return get_success_data(response)


def list_parcel_charges(parcel_id: str, headers=None) -> list:
    headers = headers or make_clerk_headers()
    response = api_client.list_assessment_charges(
        headers, params={"parcel_id": parcel_id, "limit": 100}
    )
    return get_success_data(response)


def setup_annual_assessment(
    parcel_specs=None,
    fiscal_year: int = 2026,
    fy_start_date: str = "2026-01-01",
    fy_end_date: str = "2026-12-31",
    budget_requirement_cents: int = 4_000_000,
    method_variant: str = "FRONTAGE_WEIGHTED",
    certify: bool = True,
    levy: bool = True,
    levy_clock: str = None,
    association_overrides=None,
    segment_overrides=None,
) -> dict:
    """Stand up an association, its parcels and members, then open a roll and
    optionally certify and levy it (PRD §3.4).

    When `levy_clock` is supplied the logical clock is moved to that instant
    before the levy, which fixes the charges' `due_date` at levy date plus
    forty-five days.

    Returns the `setup_membership_roll` dict plus `roll` and `charges`.
    """
    scenario = setup_membership_roll(
        parcel_specs=parcel_specs,
        association_overrides=association_overrides,
        segment_overrides=segment_overrides,
    )
    roll = setup_assessment_roll(
        scenario["association"]["id"],
        fiscal_year=fiscal_year,
        fy_start_date=fy_start_date,
        fy_end_date=fy_end_date,
        budget_requirement_cents=budget_requirement_cents,
        method_variant=method_variant,
    )

    if certify:
        roll = _data(api_client.certify_roll(roll["id"], make_clerk_headers()))
    if levy:
        if levy_clock is not None:
            set_clock(levy_clock)
        roll = _data(api_client.levy_roll(roll["id"], make_treasurer_headers()))

    scenario["roll"] = roll
    scenario["charges"] = list_roll_charges(roll["id"]) if certify else []
    scenario["association"] = _data(
        api_client.get_association(scenario["association"]["id"], make_secretary_headers())
    )
    return scenario


def setup_delinquent_charge(
    parcel_specs=None,
    fiscal_year: int = 2026,
    fy_start_date: str = "2026-01-01",
    fy_end_date: str = "2026-12-31",
    budget_requirement_cents: int = 4_000_000,
    levy_clock: str = "2026-08-01T00:00:00Z",
    remedy_clock: str = "2026-10-15T00:00:00Z",
    action_type: str = "NOTICE",
    action_overrides=None,
    initiator_headers=None,
) -> dict:
    """Levy a roll, move the clock past the charge's due date plus the thirty
    grace days, and initiate one remedy against the first charge (PRD §3.6).

    Returns the `setup_annual_assessment` dict plus `charge` and `action`.
    """
    scenario = setup_annual_assessment(
        parcel_specs=parcel_specs,
        fiscal_year=fiscal_year,
        fy_start_date=fy_start_date,
        fy_end_date=fy_end_date,
        budget_requirement_cents=budget_requirement_cents,
        levy_clock=levy_clock,
    )
    charge = scenario["charges"][0]

    set_clock(remedy_clock)
    action = _data(
        api_client.create_delinquency_action(
            charge["id"],
            f.create_delinquency_action_payload(action_type, **(action_overrides or {})),
            initiator_headers or make_treasurer_headers("bt-1"),
        )
    )

    scenario["charge"] = _data(
        api_client.get_assessment_charge(charge["id"], make_clerk_headers())
    )
    scenario["action"] = action
    return scenario


# --------------------------------------------------------------------------
# Tier 4 — special assessment balloting
# --------------------------------------------------------------------------

def setup_proposal(
    scenario: dict,
    project_type: str = "GRADING",
    estimated_cost_cents: int = 1_500_000,
    cost_allocation_method: str = "EQUAL_SHARE",
    headers=None,
    **overrides,
) -> dict:
    """Draft a proposal against the scenario's segment (PRD §3.5)."""
    headers = headers or make_treasurer_headers()
    payload = f.create_proposal_payload(
        scenario["segment"]["id"],
        project_type=project_type,
        estimated_cost_cents=estimated_cost_cents,
        cost_allocation_method=cost_allocation_method,
        **overrides,
    )
    return _data(api_client.create_proposal(payload, headers))


def open_balloting(proposal_id: str, balloting_closes_at: str, headers=None) -> dict:
    headers = headers or make_treasurer_headers()
    return _data(
        api_client.open_balloting(
            proposal_id, f.open_balloting_payload(balloting_closes_at), headers
        )
    )


def cast_ballot(proposal: dict, member: dict, choice: str, expected_proposal_version: int) -> dict:
    """Cast one ballot as the owning `MemberOwner` (PRD §3.5)."""
    return _data(
        api_client.create_ballot(
            f.create_ballot_payload(
                proposal["id"], member["id"], choice, expected_proposal_version
            ),
            make_member_owner_headers(member["id"]),
        )
    )


def setup_open_balloting(
    parcel_specs=None,
    balloting_closes_at: str = "2026-08-15T00:00:00Z",
    project_type: str = "GRADING",
    estimated_cost_cents: int = 1_500_000,
    cost_allocation_method: str = "EQUAL_SHARE",
    voting_basis: str = None,
    association_overrides=None,
    levy: bool = True,
    levy_clock: str = None,
    **assessment_kwargs,
) -> dict:
    """Levy a roll (so `ASSESSED_SHARE` weights and special charges have a roll
    to hang on), draft a proposal, and open its balloting round.

    Returns the assessment scenario plus `proposal`.
    """
    scenario = setup_annual_assessment(
        parcel_specs=parcel_specs,
        association_overrides=association_overrides,
        levy=levy,
        levy_clock=levy_clock,
        **assessment_kwargs,
    )
    proposal_overrides = {} if voting_basis is None else {"voting_basis": voting_basis}
    proposal = setup_proposal(
        scenario,
        project_type=project_type,
        estimated_cost_cents=estimated_cost_cents,
        cost_allocation_method=cost_allocation_method,
        **proposal_overrides,
    )
    scenario["proposal"] = open_balloting(proposal["id"], balloting_closes_at)
    return scenario


# --------------------------------------------------------------------------
# Tier 5 — contracting
# --------------------------------------------------------------------------

def setup_project(
    road_segment_id: str,
    category: str = "GRADING",
    window_start_date: str = "2026-08-05",
    window_end_date: str = "2026-08-08",
    headers=None,
    **overrides,
) -> dict:
    """Open a maintenance project, which opens its bid solicitation."""
    headers = headers or make_commissioner_headers("rc-1")
    payload = f.create_maintenance_project_payload(
        road_segment_id,
        category=category,
        window_start_date=window_start_date,
        window_end_date=window_end_date,
        **overrides,
    )
    return _data(api_client.create_maintenance_project(payload, headers))


def submit_bid(
    project: dict,
    amount_cents: int,
    contractor_user_id: str = "c-1",
    contractor_name: str = None,
    bond_on_file: bool = True,
    expected_project_version: int = None,
) -> dict:
    """Submit one bid, reading the project's current `version` when the caller
    does not pin one (PRD §2.9)."""
    if expected_project_version is None:
        current = _data(
            api_client.get_maintenance_project(project["id"], make_commissioner_headers())
        )
        expected_project_version = current["version"]
    payload = f.create_contractor_bid_payload(
        expected_project_version,
        contractor_name=contractor_name or f"Firm {contractor_user_id}",
        amount_cents=amount_cents,
        bond_on_file=bond_on_file,
    )
    return _data(
        api_client.create_contractor_bid(
            project["id"], payload, make_contractor_headers(contractor_user_id)
        )
    )


def setup_project_with_bids(
    road_segment_id: str,
    bid_specs=None,
    category: str = "GRADING",
    window_start_date: str = "2026-08-05",
    window_end_date: str = "2026-08-08",
    project_overrides=None,
) -> dict:
    """Open a project and submit one bid per spec.

    Each spec is a dict of `submit_bid` keyword arguments. Returns `project`
    (re-read after every submission bumped its version) and `bids`.
    """
    bid_specs = bid_specs if bid_specs is not None else [{"amount_cents": 400_000}]
    project = setup_project(
        road_segment_id,
        category=category,
        window_start_date=window_start_date,
        window_end_date=window_end_date,
        **(project_overrides or {}),
    )
    bids = [submit_bid(project, **spec) for spec in bid_specs]
    project = _data(api_client.get_maintenance_project(project["id"], make_commissioner_headers()))
    return {"project": project, "bids": bids}


def award_project(project_id: str, bid_id: str, headers=None) -> dict:
    """Award a bid as a second commissioner, since the awarding user must differ
    from `created_by_user_id` (PRD §2.1)."""
    headers = headers or make_commissioner_headers("rc-2")
    return _data(api_client.award_project(project_id, f.award_payload(bid_id), headers))


def setup_awarded_project(
    road_segment_id: str,
    bid_specs=None,
    category: str = "GRADING",
    window_start_date: str = "2026-08-05",
    window_end_date: str = "2026-08-08",
    project_overrides=None,
) -> dict:
    """Open a project, take bids, and award the lowest responsive one."""
    solicited = setup_project_with_bids(
        road_segment_id,
        bid_specs=bid_specs,
        category=category,
        window_start_date=window_start_date,
        window_end_date=window_end_date,
        project_overrides=project_overrides,
    )
    winner = min(solicited["bids"], key=lambda b: b["amount_cents"])
    solicited["project"] = award_project(solicited["project"]["id"], winner["id"])
    solicited["awarded_bid"] = _data(
        api_client.get_contractor_bid(winner["id"], make_commissioner_headers())
    )
    return solicited


# --------------------------------------------------------------------------
# Tier 5 — subdivision and new-lot connections
# --------------------------------------------------------------------------

def subdivide(parcel_id: str, children: list, headers=None) -> dict:
    """Split a parcel. The response carries `parent_parcel` and `children` in
    request order (PRD §3.2)."""
    headers = headers or make_secretary_headers()
    return _data(api_client.subdivide_parcel(parcel_id, f.subdivide_payload(children), headers))


def setup_subdivided_lots(
    scenario: dict,
    children=None,
    parcel_index: int = 0,
) -> dict:
    """Subdivide one of the scenario's parcels into `PENDING_CONNECTION` lots.

    Returns the scenario with `parent_parcel` and `child_parcels` added.
    """
    parent = scenario["parcels"][parcel_index]
    children = children if children is not None else [
        {"deed_book_page": "DB120-P41A", "frontage_feet": 180},
        {"deed_book_page": "DB120-P41B", "frontage_feet": 70},
        {"deed_book_page": "DB120-P41C", "frontage_feet": 40},
    ]
    result = subdivide(parent["id"], children)
    scenario["parent_parcel"] = result["parent_parcel"]
    scenario["child_parcels"] = result["children"]
    return scenario


def file_connection_request(
    parcel_id: str,
    requested_usage_class: str = "RESIDENTIAL_YEAR_ROUND",
    requested_trips_per_day: int = 4,
    easement_grant_recorded: bool = True,
    headers=None,
) -> dict:
    headers = headers or make_secretary_headers()
    payload = f.create_connection_request_payload(
        parcel_id,
        requested_usage_class=requested_usage_class,
        requested_trips_per_day=requested_trips_per_day,
        easement_grant_recorded=easement_grant_recorded,
    )
    return _data(api_client.create_connection_request(payload, headers))


def setup_connection_request(
    parcel_specs=None,
    children=None,
    requested_usage_class: str = "RESIDENTIAL_YEAR_ROUND",
    requested_trips_per_day: int = 4,
    easement_grant_recorded: bool = True,
    levy_clock: str = "2026-08-01T00:00:00Z",
    child_index: int = 0,
    **assessment_kwargs,
) -> dict:
    """Levy a roll (a connection fee needs a levied roll to hang its charge on),
    subdivide the first parcel, and file a request on one of the new lots.

    Returns the assessment scenario plus `parent_parcel`, `child_parcels`, and
    `connection_request`.
    """
    scenario = setup_annual_assessment(
        parcel_specs=parcel_specs, levy_clock=levy_clock, **assessment_kwargs
    )
    scenario = setup_subdivided_lots(scenario, children=children)
    scenario["connection_request"] = file_connection_request(
        scenario["child_parcels"][child_index]["id"],
        requested_usage_class=requested_usage_class,
        requested_trips_per_day=requested_trips_per_day,
        easement_grant_recorded=easement_grant_recorded,
    )
    return scenario


# --------------------------------------------------------------------------
# Convenience re-reads
# --------------------------------------------------------------------------

def read_association(association_id: str) -> dict:
    return _data(api_client.get_association(association_id, make_secretary_headers()))


def read_segment(segment_id: str) -> dict:
    return _data(api_client.get_road_segment(segment_id, make_commissioner_headers()))


def read_parcel(parcel_id: str) -> dict:
    return _data(api_client.get_parcel(parcel_id, make_secretary_headers()))


def read_member(member_id: str) -> dict:
    return _data(api_client.get_member(member_id, make_secretary_headers()))


def read_roll(roll_id: str) -> dict:
    return _data(api_client.get_assessment_roll(roll_id, make_clerk_headers()))


def read_charge(charge_id: str) -> dict:
    return _data(api_client.get_assessment_charge(charge_id, make_clerk_headers()))


def read_proposal(proposal_id: str) -> dict:
    return _data(api_client.get_proposal(proposal_id, make_treasurer_headers()))


def read_ballot(ballot_id: str) -> dict:
    return _data(api_client.get_ballot(ballot_id, make_treasurer_headers()))


def read_project(project_id: str) -> dict:
    return _data(api_client.get_maintenance_project(project_id, make_commissioner_headers()))


def read_bid(bid_id: str) -> dict:
    return _data(api_client.get_contractor_bid(bid_id, make_commissioner_headers()))


def read_action(action_id: str) -> dict:
    return _data(api_client.get_delinquency_action(action_id, make_treasurer_headers()))


def read_connection_request(request_id: str) -> dict:
    return _data(api_client.get_connection_request(request_id, make_secretary_headers()))

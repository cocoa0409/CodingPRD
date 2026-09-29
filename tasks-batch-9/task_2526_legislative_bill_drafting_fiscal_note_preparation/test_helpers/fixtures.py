"""Composite setup helpers.

Every test starts against an empty database, so all state is built from scratch
through the public API. These helpers encapsulate the multi-step preambles the
domain needs: a convened session with its reference data, a drafting request
walked to DRAFT_READY, an introduced bill, a referred bill, a routed fiscal note
with its cost estimate lines, a certified note, an adopted amendment and a
prepared enrollment.

Identity threading matters here: Member, Drafter, ReviewCounsel and AgencyAnalyst
are backed by real rows, so every ownership-gated call below is made with headers
built from the real Member.id / Drafter.id / Agency.id.
"""
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    assign_payload,
    certify_draft_payload,
    complete_research_payload,
    create_agency_payload,
    create_amendment_payload,
    create_bill_payload,
    create_committee_payload,
    create_cost_estimate_payload,
    create_drafter_payload,
    create_drafting_request_payload,
    create_fiscal_note_request_payload,
    create_member_payload,
    create_referral_payload,
    create_session_payload,
    create_statutory_conflict_payload,
    create_technical_correction_payload,
    draft_amendment_payload,
    report_payload,
    resolve_conflict_payload,
    signature_payload,
)
from .test_users import (
    make_agency_analyst_headers,
    make_clerk_headers,
    make_drafter_headers,
    make_fiscal_officer_headers,
    make_member_headers,
    make_platform_admin_headers,
    make_review_counsel_headers,
)

DEFAULT_CLOCK = TEST_DEFAULTS["CLOCK"]

ADMIN = make_platform_admin_headers()
CLERK = make_clerk_headers()
FISCAL_OFFICER = make_fiscal_officer_headers()


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(current_utc: str) -> None:
    """Move the logical clock. Every deadline in this domain is measured against it.

    The clock endpoint returns no resource body, so only the status is checked.
    """
    response = api_client.set_clock(current_utc, ADMIN)
    assert 200 <= response.status_code < 300, (
        f"Setting the logical clock to {current_utc} failed with "
        f"HTTP {response.status_code}: {response.text}"
    )


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
def create_session(**overrides) -> Dict[str, Any]:
    """Create a session; it starts in PENDING."""
    return get_success_data(
        api_client.create_session(create_session_payload(**overrides), ADMIN)
    )


def create_convened_session(**overrides) -> Dict[str, Any]:
    """Create a session and convene it, so business writes are admitted."""
    session = create_session(**overrides)
    return get_success_data(api_client.convene_session(session["id"], CLERK))


def create_committee(session_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_committee(session_id, create_committee_payload(**overrides), CLERK)
    )


def create_member(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_member(create_member_payload(**overrides), ADMIN))


def create_drafter(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_drafter(create_drafter_payload(**overrides), ADMIN))


def create_senior_counsel(**overrides) -> Dict[str, Any]:
    """A senior drafter, eligible to act under the ReviewCounsel role."""
    defaults = {"full_name": "Counsel Senior", "is_senior": True, "max_concurrent_engagements": 2}
    defaults.update(overrides)
    return create_drafter(**defaults)


def create_agency(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_agency(create_agency_payload(**overrides), ADMIN))


def setup_world(
    clock: str = DEFAULT_CLOCK,
    with_committee: bool = False,
    session_overrides: Optional[Dict[str, Any]] = None,
    committee_overrides: Optional[Dict[str, Any]] = None,
    member_overrides: Optional[Dict[str, Any]] = None,
    drafter_overrides: Optional[Dict[str, Any]] = None,
    counsel_overrides: Optional[Dict[str, Any]] = None,
    with_agency: bool = False,
    agency_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pin the clock, convene a session, and register the standard cast:
    one member, one junior drafter, one senior review counsel, optionally a
    committee and an agency. Returns a dict of rows plus ready-made headers."""
    set_clock(clock)
    session = create_convened_session(**(session_overrides or {}))
    member = create_member(**(member_overrides or {}))
    drafter = create_drafter(**(drafter_overrides or {}))
    counsel = create_senior_counsel(**(counsel_overrides or {}))
    world: Dict[str, Any] = {
        "clock": clock,
        "session": session,
        "member": member,
        "drafter": drafter,
        "counsel": counsel,
        "committee": None,
        "agency": None,
        "admin_headers": ADMIN,
        "clerk_headers": CLERK,
        "fiscal_officer_headers": FISCAL_OFFICER,
        "member_headers": make_member_headers(member["id"]),
        "drafter_headers": make_drafter_headers(drafter["id"]),
        "counsel_headers": make_review_counsel_headers(counsel["id"]),
        "analyst_headers": None,
    }
    if with_committee:
        world["committee"] = create_committee(session["id"], **(committee_overrides or {}))
    if with_agency:
        agency = create_agency(**(agency_overrides or {}))
        world["agency"] = agency
        world["analyst_headers"] = make_agency_analyst_headers(agency["id"])
    return world


def add_agency(world: Dict[str, Any], **overrides) -> Dict[str, Any]:
    """Register an extra agency and return it. The first one also becomes
    world['agency'] with its analyst headers."""
    agency = create_agency(**overrides)
    if world.get("agency") is None:
        world["agency"] = agency
        world["analyst_headers"] = make_agency_analyst_headers(agency["id"])
    return agency


def add_committee(world: Dict[str, Any], **overrides) -> Dict[str, Any]:
    committee = create_committee(world["session"]["id"], **overrides)
    if world.get("committee") is None:
        world["committee"] = committee
    return committee


def add_member(world: Dict[str, Any], **overrides) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Register a second member and return (member, its headers)."""
    member = create_member(**overrides)
    return member, make_member_headers(member["id"])


def add_drafter(world: Dict[str, Any], **overrides) -> Tuple[Dict[str, Any], Dict[str, str]]:
    drafter = create_drafter(**overrides)
    return drafter, make_drafter_headers(drafter["id"])


# ---------------------------------------------------------------------------
# Drafting request lifecycle
# ---------------------------------------------------------------------------
def file_drafting_request(world: Dict[str, Any], **overrides) -> Dict[str, Any]:
    """The member files a drafting request; it starts in SUBMITTED."""
    payload = create_drafting_request_payload(world["session"]["id"], **overrides)
    return get_success_data(
        api_client.create_drafting_request(payload, world["member_headers"])
    )


def assign_request(
    world: Dict[str, Any],
    request: Dict[str, Any],
    drafter: Optional[Dict[str, Any]] = None,
    engagement_start_utc: str = "2026-09-02T00:00:00Z",
    engagement_end_utc: str = "2026-09-05T00:00:00Z",
) -> Dict[str, Any]:
    """Review counsel assigns a drafter, moving the request SUBMITTED -> RESEARCH."""
    target = drafter or world["drafter"]
    payload = assign_payload(
        target["id"],
        engagement_start_utc=engagement_start_utc,
        engagement_end_utc=engagement_end_utc,
    )
    return get_success_data(
        api_client.assign_drafting_request(request["id"], payload, world["counsel_headers"])
    )


def complete_research(
    world: Dict[str, Any],
    request: Dict[str, Any],
    affected_sections_count: int = 3,
    drafter_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """The assigned drafter reports the researched footprint: RESEARCH -> DRAFTING."""
    return get_success_data(
        api_client.complete_research(
            request["id"],
            complete_research_payload(affected_sections_count),
            drafter_headers or world["drafter_headers"],
        )
    )


def certify_draft(
    world: Dict[str, Any],
    request: Dict[str, Any],
    style_findings_count: int = 0,
    counsel_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Review counsel certifies drafting-style compliance: DRAFTING -> DRAFT_READY."""
    return get_success_data(
        api_client.certify_draft(
            request["id"],
            certify_draft_payload(style_findings_count),
            counsel_headers or world["counsel_headers"],
        )
    )


def setup_request_in_research(world: Dict[str, Any], **overrides) -> Dict[str, Any]:
    """File a request and assign it, leaving it in RESEARCH."""
    engagement = {
        "engagement_start_utc": overrides.pop("engagement_start_utc", "2026-09-02T00:00:00Z"),
        "engagement_end_utc": overrides.pop("engagement_end_utc", "2026-09-05T00:00:00Z"),
    }
    drafter = overrides.pop("drafter", None)
    request = file_drafting_request(world, **overrides)
    return assign_request(world, request, drafter=drafter, **engagement)


def setup_request_in_drafting(
    world: Dict[str, Any], affected_sections_count: Optional[int] = None, **overrides
) -> Dict[str, Any]:
    """File, assign and complete research, leaving the request in DRAFTING."""
    sections = (
        affected_sections_count
        if affected_sections_count is not None
        else overrides.get("requested_sections_count", 3)
    )
    request = setup_request_in_research(world, **overrides)
    return complete_research(world, request, affected_sections_count=sections)


def setup_draft_ready_request(
    world: Dict[str, Any], affected_sections_count: Optional[int] = None, **overrides
) -> Dict[str, Any]:
    """Walk a request all the way to DRAFT_READY with zero style findings."""
    request = setup_request_in_drafting(
        world, affected_sections_count=affected_sections_count, **overrides
    )
    return certify_draft(world, request)


def file_statutory_conflict(
    world: Dict[str, Any],
    request: Dict[str, Any],
    severity: str = "BLOCKING",
    drafter_headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """The assigned drafter records a conflict with existing code."""
    payload = create_statutory_conflict_payload(request["id"], severity=severity, **overrides)
    return get_success_data(
        api_client.create_statutory_conflict(
            payload, drafter_headers or world["drafter_headers"]
        )
    )


def resolve_statutory_conflict(
    world: Dict[str, Any],
    conflict: Dict[str, Any],
    resolution_status: str = "RESOLVED",
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    payload = resolve_conflict_payload(resolution_status, **overrides)
    default_headers = (
        world["counsel_headers"] if resolution_status == "WAIVED" else world["drafter_headers"]
    )
    return get_success_data(
        api_client.resolve_statutory_conflict(conflict["id"], payload, headers or default_headers)
    )


# ---------------------------------------------------------------------------
# Bills
# ---------------------------------------------------------------------------
def introduce_bill(world: Dict[str, Any], request: Dict[str, Any]) -> Dict[str, Any]:
    """The clerk introduces a DRAFT_READY request as a bill."""
    return get_success_data(
        api_client.create_bill(create_bill_payload(request["id"]), world["clerk_headers"])
    )


def setup_introduced_bill(
    world: Dict[str, Any], affected_sections_count: Optional[int] = None, **overrides
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """DRAFT_READY request plus its introduced bill. Returns (request, bill)."""
    request = setup_draft_ready_request(
        world, affected_sections_count=affected_sections_count, **overrides
    )
    bill = introduce_bill(world, request)
    return request, bill


def refer_bill(
    world: Dict[str, Any],
    bill: Dict[str, Any],
    committee: Optional[Dict[str, Any]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Refer the bill to a committee of its own session and chamber."""
    target = committee or world["committee"]
    payload = create_referral_payload(target["id"], **overrides)
    return get_success_data(
        api_client.create_referral(bill["id"], payload, world["clerk_headers"])
    )


def report_referral(
    world: Dict[str, Any], referral: Dict[str, Any], outcome: str = "FAVORABLE"
) -> Dict[str, Any]:
    return get_success_data(
        api_client.report_referral(referral["id"], report_payload(outcome), world["clerk_headers"])
    )


def read_bill(world: Dict[str, Any], bill_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_bill(bill_id, world["clerk_headers"]))


def read_session(world: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api_client.get_session(world["session"]["id"], world["clerk_headers"]))


def read_member(world: Dict[str, Any], member_id: Optional[str] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_member(member_id or world["member"]["id"], world["clerk_headers"])
    )


def read_drafter(world: Dict[str, Any], drafter_id: Optional[str] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_drafter(drafter_id or world["drafter"]["id"], world["clerk_headers"])
    )


def read_agency(world: Dict[str, Any], agency_id: Optional[str] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_agency(agency_id or world["agency"]["id"], world["fiscal_officer_headers"])
    )


def read_drafting_request(world: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_drafting_request(request_id, world["clerk_headers"])
    )


def read_committee(world: Dict[str, Any], committee_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_committee(committee_id, world["clerk_headers"]))


def read_referral(world: Dict[str, Any], referral_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_committee_referral(referral_id, world["clerk_headers"])
    )


def read_note(world: Dict[str, Any], note_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_fiscal_note_request(note_id, world["fiscal_officer_headers"])
    )


def read_amendment(world: Dict[str, Any], amendment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_amendment(amendment_id, world["clerk_headers"]))


def read_enrolled_bill(world: Dict[str, Any], enrolled_bill_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_enrolled_bill(enrolled_bill_id, world["clerk_headers"])
    )


def read_correction(world: Dict[str, Any], correction_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_technical_correction(correction_id, world["clerk_headers"])
    )


# ---------------------------------------------------------------------------
# Fiscal notes
# ---------------------------------------------------------------------------
def route_fiscal_note(
    world: Dict[str, Any],
    bill: Dict[str, Any],
    agency: Optional[Dict[str, Any]] = None,
    methodology: str = "INCREMENTAL_COST",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Route a fiscal note request to an agency; it starts in ROUTED."""
    target = agency or world["agency"]
    payload = create_fiscal_note_request_payload(target["id"], methodology=methodology)
    return get_success_data(
        api_client.create_fiscal_note_request(
            bill["id"], payload, headers or world["fiscal_officer_headers"]
        )
    )


def append_cost_estimate(
    world: Dict[str, Any],
    note: Dict[str, Any],
    analyst_headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Append one cost estimate line, refreshing the note's version first.

    Each appended line increments the note's version, so the next line must
    carry a freshly read expected_fiscal_note_request_version.
    """
    headers = analyst_headers or world["analyst_headers"]
    current = get_success_data(api_client.get_fiscal_note_request(note["id"], headers))
    payload = create_cost_estimate_payload(current["version"], **overrides)
    return get_success_data(api_client.create_cost_estimate(note["id"], payload, headers))


def append_cost_estimates(
    world: Dict[str, Any],
    note: Dict[str, Any],
    lines: List[Dict[str, Any]],
    analyst_headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Append a whole set of cost estimate lines in order."""
    return [append_cost_estimate(world, note, analyst_headers, **line) for line in lines]


def submit_note(
    world: Dict[str, Any],
    note: Dict[str, Any],
    analyst_headers: Optional[Dict[str, str]] = None,
    **payload_overrides,
) -> Dict[str, Any]:
    """The agency analyst submits the note, running every cost and revenue total."""
    return get_success_data(
        api_client.submit_fiscal_note_request(
            note["id"], dict(payload_overrides), analyst_headers or world["analyst_headers"]
        )
    )


def return_note(world: Dict[str, Any], note: Dict[str, Any], **payload_overrides) -> Dict[str, Any]:
    """The fiscal officer returns a submitted note, opening a new revision round."""
    payload = {"return_reason": "Assumptions need restating."}
    payload.update(payload_overrides)
    return get_success_data(
        api_client.return_fiscal_note_request(
            note["id"], payload, world["fiscal_officer_headers"]
        )
    )


def certify_note(world: Dict[str, Any], note: Dict[str, Any], **payload_overrides) -> Dict[str, Any]:
    """The fiscal officer certifies the note and posts it to the session ledger."""
    return get_success_data(
        api_client.certify_fiscal_note_request(
            note["id"], dict(payload_overrides), world["fiscal_officer_headers"]
        )
    )


# Two BASELINE lines covering the standard required fiscal years [2027, 2028]
# whose INCREMENTAL_COST total certifies at 26568000 cents.
STANDARD_COST_LINES: List[Dict[str, Any]] = [
    {
        "fiscal_year": 2027,
        "scenario": "BASELINE",
        "personnel_cost_cents": 14_000_000,
        "operating_cost_cents": 4_100_000,
        "one_time_cost_cents": 3_000_000,
        "fte_count": 1.0,
        "revenue_impact_cents": 0,
        "assumption_note": "FY2027.",
    },
    {
        "fiscal_year": 2028,
        "scenario": "BASELINE",
        "personnel_cost_cents": 10_400_000,
        "operating_cost_cents": 3_500_000,
        "one_time_cost_cents": 0,
        "fte_count": 0.4,
        "revenue_impact_cents": 0,
        "assumption_note": "FY2028.",
    },
]

# Two BASELINE lines whose INCREMENTAL_COST total certifies at exactly 50000000.
FIFTY_MILLION_COST_LINES: List[Dict[str, Any]] = [
    {
        "fiscal_year": 2027,
        "scenario": "BASELINE",
        "personnel_cost_cents": 20_000_000,
        "operating_cost_cents": 3_148_148,
        "one_time_cost_cents": 0,
        "fte_count": 1.0,
        "revenue_impact_cents": 0,
        "assumption_note": "FY2027 crew and materials.",
    },
    {
        "fiscal_year": 2028,
        "scenario": "BASELINE",
        "personnel_cost_cents": 20_000_000,
        "operating_cost_cents": 3_148_148,
        "one_time_cost_cents": 0,
        "fte_count": 1.0,
        "revenue_impact_cents": 0,
        "assumption_note": "FY2028 crew and materials.",
    },
]


def cheap_cost_lines(
    fiscal_years: Optional[List[int]] = None, personnel_cost_cents: int = 100_000
) -> List[Dict[str, Any]]:
    """A minimal complete BASELINE line set for every required fiscal year."""
    years = fiscal_years or list(TEST_DEFAULTS["REQUIRED_FISCAL_YEARS"])
    return [
        {
            "fiscal_year": year,
            "scenario": "BASELINE",
            "personnel_cost_cents": personnel_cost_cents,
            "operating_cost_cents": 0,
            "one_time_cost_cents": 0,
            "fte_count": 1.0,
            "revenue_impact_cents": 0,
            "assumption_note": f"FY{year} minimal cost.",
        }
        for year in years
    ]


def setup_submitted_note(
    world: Dict[str, Any],
    bill: Dict[str, Any],
    lines: Optional[List[Dict[str, Any]]] = None,
    agency: Optional[Dict[str, Any]] = None,
    methodology: str = "INCREMENTAL_COST",
) -> Dict[str, Any]:
    """Route a note, file its cost estimate lines and submit it."""
    note = route_fiscal_note(world, bill, agency=agency, methodology=methodology)
    analyst_headers = (
        make_agency_analyst_headers(agency["id"]) if agency else world["analyst_headers"]
    )
    append_cost_estimates(world, note, lines or STANDARD_COST_LINES, analyst_headers)
    return submit_note(world, note, analyst_headers)


def setup_certified_note(
    world: Dict[str, Any],
    bill: Dict[str, Any],
    lines: Optional[List[Dict[str, Any]]] = None,
    agency: Optional[Dict[str, Any]] = None,
    methodology: str = "INCREMENTAL_COST",
) -> Dict[str, Any]:
    """Route, file, submit and certify a note, posting it to the session ledger."""
    note = setup_submitted_note(
        world, bill, lines=lines, agency=agency, methodology=methodology
    )
    return certify_note(world, note)


def setup_bill_with_certified_note(
    world: Dict[str, Any],
    appropriation_requested_cents: int = 12_000_000,
    lines: Optional[List[Dict[str, Any]]] = None,
    affected_sections_count: int = 4,
    requested_sections_count: int = 4,
    refer: bool = False,
    **request_overrides,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]]:
    """Introduce a bill that needs a fiscal note, optionally refer it, and certify
    the note. Returns (request, bill, note, referral)."""
    request, bill = setup_introduced_bill(
        world,
        affected_sections_count=affected_sections_count,
        requested_sections_count=requested_sections_count,
        appropriation_requested_cents=appropriation_requested_cents,
        **request_overrides,
    )
    referral = None
    if refer:
        referral = refer_bill(world, bill)
    note = setup_certified_note(world, bill, lines=lines)
    return request, bill, note, referral


# ---------------------------------------------------------------------------
# Amendments
# ---------------------------------------------------------------------------
def request_amendment(
    world: Dict[str, Any],
    bill: Dict[str, Any],
    member_headers: Optional[Dict[str, str]] = None,
    expected_bill_version: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    """A member requests an amendment against the bill's current version."""
    headers = member_headers or world["member_headers"]
    version = expected_bill_version
    if version is None:
        version = get_success_data(
            api_client.get_bill(bill["id"], world["clerk_headers"])
        )["version"]
    payload = create_amendment_payload(version, bill["id"], **overrides)
    return get_success_data(api_client.create_amendment(payload, headers))


def draft_amendment(
    world: Dict[str, Any],
    amendment: Dict[str, Any],
    drafter_headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.draft_amendment(
            amendment["id"],
            draft_amendment_payload(**overrides),
            drafter_headers or world["drafter_headers"],
        )
    )


def adopt_amendment(world: Dict[str, Any], amendment: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(
        api_client.adopt_amendment(amendment["id"], world["clerk_headers"])
    )


def setup_drafted_amendment(
    world: Dict[str, Any], bill: Dict[str, Any], **overrides
) -> Dict[str, Any]:
    """Request and draft an amendment, leaving it in DRAFTED."""
    amendment = request_amendment(world, bill, **overrides)
    return draft_amendment(world, amendment)


def setup_adopted_amendment(
    world: Dict[str, Any], bill: Dict[str, Any], **overrides
) -> Dict[str, Any]:
    """Request, draft and adopt an amendment."""
    amendment = setup_drafted_amendment(world, bill, **overrides)
    return adopt_amendment(world, amendment)


# ---------------------------------------------------------------------------
# Passage, enrollment, corrections and signatures
# ---------------------------------------------------------------------------
def pass_bill(world: Dict[str, Any], bill: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api_client.pass_bill(bill["id"], world["clerk_headers"]))


def enroll_bill(world: Dict[str, Any], bill: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api_client.enroll_bill(bill["id"], world["clerk_headers"]))


def propose_correction(
    world: Dict[str, Any],
    enrolled_bill: Dict[str, Any],
    drafter_headers: Optional[Dict[str, str]] = None,
    expected_enrolled_bill_version: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    """A drafter proposes a non-substantive correction to enrolled text."""
    version = expected_enrolled_bill_version
    if version is None:
        version = get_success_data(
            api_client.get_enrolled_bill(enrolled_bill["id"], world["clerk_headers"])
        )["version"]
    payload = create_technical_correction_payload(version, **overrides)
    return get_success_data(
        api_client.create_technical_correction(
            enrolled_bill["id"], payload, drafter_headers or world["drafter_headers"]
        )
    )


def apply_correction(
    world: Dict[str, Any],
    correction: Dict[str, Any],
    counsel_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Review counsel applies a proposed correction; it must not be the proposer."""
    return get_success_data(
        api_client.apply_technical_correction(
            correction["id"], counsel_headers or world["counsel_headers"]
        )
    )


def sign_enrollment(
    world: Dict[str, Any], enrolled_bill: Dict[str, Any], signature_role: str
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_signature(
            enrolled_bill["id"], signature_payload(signature_role), world["clerk_headers"]
        )
    )


def setup_reported_bill(
    world: Dict[str, Any],
    appropriation_requested_cents: int = 0,
    lines: Optional[List[Dict[str, Any]]] = None,
    hearing_window_start_utc: str = "2026-10-05T14:00:00Z",
    hearing_window_end_utc: str = "2026-10-05T16:00:00Z",
    report_clock: Optional[str] = None,
    **request_overrides,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Introduce a bill, refer it, satisfy its fiscal obligation if it has one,
    and report it out FAVORABLE. Returns (request, bill, referral)."""
    request, bill = setup_introduced_bill(
        world,
        appropriation_requested_cents=appropriation_requested_cents,
        **request_overrides,
    )
    referral = refer_bill(
        world,
        bill,
        hearing_window_start_utc=hearing_window_start_utc,
        hearing_window_end_utc=hearing_window_end_utc,
    )
    if appropriation_requested_cents > 0:
        setup_certified_note(world, bill, lines=lines)
    if report_clock:
        set_clock(report_clock)
    report_referral(world, referral, "FAVORABLE")
    return request, bill, referral


def setup_passed_bill(
    world: Dict[str, Any], appropriation_requested_cents: int = 0, **overrides
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Introduce, refer, report FAVORABLE and pass a bill."""
    request, bill, referral = setup_reported_bill(
        world, appropriation_requested_cents=appropriation_requested_cents, **overrides
    )
    pass_bill(world, bill)
    return request, bill, referral


def setup_enrolled_bill(
    world: Dict[str, Any], appropriation_requested_cents: int = 0, **overrides
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Introduce, refer, report, pass and enroll a bill.
    Returns (bill, referral, enrolled_bill)."""
    _request, bill, referral = setup_passed_bill(
        world, appropriation_requested_cents=appropriation_requested_cents, **overrides
    )
    enrolled = enroll_bill(world, bill)
    return bill, referral, enrolled

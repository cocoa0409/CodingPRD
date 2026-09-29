"""
Composite setup helpers and pytest fixtures.

The harness restarts the API server before every individual test, so each test begins
against an empty database. Every precondition therefore has to be built from scratch
through declared endpoints — there is no seeded data and no back door.

A brownfield parcel has to travel a long way before most rules become reachable: the
protection has to establish its all-appropriate-inquiries record before acquisition,
two assessment phases have to be approved before cleanup goals exist, the enrollment
has to be accepted before a remedy can be filed, and the remedy has to clear a
technical review and a public comment period before it can be approved. The staged
builders below walk that chain one landing at a time, each returning the ``World`` so
a test can stop wherever its rule lives and vary anything downstream of that point.

Identity matters throughout. A ``Redeveloper``, ``EnvironmentalConsultant`` or
``Insurer`` authenticates as the ``Party`` row it is, so the ``World`` hands out
headers built from the real party ids rather than from constants.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import BrownfieldClient
from .constants import CLOCK_EPOCH
from .factories import (
    acquisition_payload,
    canonical_cost_lines,
    consultant_payload,
    continuing_obligation_payload,
    eligibility_decision_payload,
    enrollment_payload,
    finding_payload,
    funding_award_payload,
    inquiry_completion_payload,
    insurer_payload,
    laboratory_payload,
    lender_acceptance_payload,
    liability_protection_payload,
    monitoring_event_payload,
    nfa_letter_payload,
    operation_certification_payload,
    phase_ii_payload,
    phase_review_payload,
    plan_payload,
    policy_payload,
    public_comment_close_payload,
    redeveloper_payload,
    sampling_result_payload,
    site_control_payload,
    site_payload,
    assessment_phase_payload,
    cleanup_goal_payload,
    tax_credit_award_payload,
    technical_review_payload,
)
from .test_users import (
    LENDER,
    PROGRAM_ADMIN,
    REVIEWER_ALPHA,
    REVIEWER_ALPHA_USER_ID,
    REVIEWER_BETA,
    REVIEWER_BETA_USER_ID,
    REVIEWER_GAMMA,
    make_consultant_headers,
    make_insurer_headers,
    make_redeveloper_headers,
)

# ─── Fixtures every test needs ────────────────────────────────────────────────


@pytest.fixture
def api() -> BrownfieldClient:
    """A client pointed at the API under test."""
    return BrownfieldClient()


@pytest.fixture
def admin() -> Dict[str, str]:
    """ProgramAdmin headers (opaque operator identity)."""
    return PROGRAM_ADMIN


@pytest.fixture
def reviewer() -> Dict[str, str]:
    """The reviewer who runs most of the agency-side chain."""
    return REVIEWER_ALPHA


@pytest.fixture
def reviewer_beta() -> Dict[str, str]:
    """A second reviewer identity, for the two segregation-of-duties rules."""
    return REVIEWER_BETA


@pytest.fixture
def reviewer_gamma() -> Dict[str, str]:
    """A third reviewer identity, where two distinct others are needed at once."""
    return REVIEWER_GAMMA


@pytest.fixture
def lender() -> Dict[str, str]:
    """Lender headers (opaque operator identity)."""
    return LENDER


# ─── The clock ────────────────────────────────────────────────────────────────


def set_clock(api: BrownfieldClient, current_utc: str, headers=PROGRAM_ADMIN) -> str:
    """Reposition the logical clock and return the instant the server adopted."""
    data = get_success_data(api.set_clock(current_utc, headers))
    return data["current_utc"]


# ─── The world ────────────────────────────────────────────────────────────────


class World:
    """
    Everything a staged chain has created so far, keyed by role in the story.

    Attributes appear as the chain advances; a test that stops at an early landing
    simply never touches the later ones. ``rows`` keeps the most recent read of each
    named row, and the ``*_headers`` properties always derive from the real party ids.
    """

    def __init__(self, api: BrownfieldClient):
        self.api = api
        self.redeveloper: Optional[Dict[str, Any]] = None
        self.consultant: Optional[Dict[str, Any]] = None
        self.insurer: Optional[Dict[str, Any]] = None
        self.laboratory: Optional[Dict[str, Any]] = None
        self.site: Optional[Dict[str, Any]] = None
        self.protection: Optional[Dict[str, Any]] = None
        self.phase_i: Optional[Dict[str, Any]] = None
        self.phase_i_finding: Optional[Dict[str, Any]] = None
        self.phase_ii: Optional[Dict[str, Any]] = None
        self.phase_ii_findings: List[Dict[str, Any]] = []
        self.goal_restricted: Optional[Dict[str, Any]] = None
        self.goal_unrestricted: Optional[Dict[str, Any]] = None
        self.enrollment: Optional[Dict[str, Any]] = None
        self.enrollment_version: Optional[int] = None
        self.plan: Optional[Dict[str, Any]] = None
        self.control: Optional[Dict[str, Any]] = None
        self.policy: Optional[Dict[str, Any]] = None
        self.awards: List[Dict[str, Any]] = []
        self.obligations: Dict[str, Dict[str, Any]] = {}
        self.letter: Optional[Dict[str, Any]] = None

    # ── Headers derived from the real party rows ──

    @property
    def redev_headers(self) -> Dict[str, str]:
        return make_redeveloper_headers(self.redeveloper["id"])

    @property
    def consult_headers(self) -> Dict[str, str]:
        return make_consultant_headers(self.consultant["id"])

    @property
    def insurer_headers(self) -> Dict[str, str]:
        return make_insurer_headers(self.insurer["id"])

    # ── Convenience ids ──

    @property
    def site_id(self) -> str:
        return self.site["id"]

    @property
    def plan_id(self) -> str:
        return self.plan["id"]

    @property
    def enrollment_id(self) -> str:
        return self.enrollment["id"]

    # ── Fresh reads ──

    def read_site(self) -> Dict[str, Any]:
        self.site = get_success_data(self.api.get_site(self.site["id"], self.redev_headers))
        return self.site

    def read_plan(self, plan: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        target = plan or self.plan
        row = get_success_data(self.api.get_plan(target["id"], self.consult_headers))
        if plan is None:
            self.plan = row
        return row

    def read_enrollment(self) -> Dict[str, Any]:
        self.enrollment = get_success_data(
            self.api.get_enrollment(self.enrollment["id"], self.redev_headers)
        )
        return self.enrollment

    def read_protection(self) -> Dict[str, Any]:
        self.protection = get_success_data(
            self.api.get_liability_protection(self.protection["id"], self.redev_headers)
        )
        return self.protection

    def read_control(self, control: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        target = control or self.control
        return get_success_data(
            self.api.get_site_control(target["id"], self.redev_headers)
        )

    def read_policy(self, policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        target = policy or self.policy
        row = get_success_data(self.api.get_policy(target["id"], self.insurer_headers))
        if policy is None:
            self.policy = row
        return row

    def read_letter(self) -> Dict[str, Any]:
        self.letter = get_success_data(
            self.api.get_nfa_letter(self.letter["id"], self.redev_headers)
        )
        return self.letter

    def read_goal(self, goal: Dict[str, Any]) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_cleanup_goal(goal["id"], self.consult_headers)
        )

    def read_obligation(self, obligation: Dict[str, Any]) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_continuing_obligation(obligation["id"], self.redev_headers)
        )

    def read_award(self, award: Dict[str, Any]) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_funding_award(award["id"], self.redev_headers)
        )

    def read_funding_assembly(self) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_funding_assembly(self.site["id"], self.redev_headers)
        )

    def read_goals(self) -> List[Dict[str, Any]]:
        rows, _ = validate_paginated(
            self.api.list_cleanup_goals(self.site["id"], self.consult_headers)
        )
        return rows


# ─── Landing 1: the registry ──────────────────────────────────────────────────


def stage_registry(api: BrownfieldClient, clock: str = CLOCK_EPOCH) -> World:
    """
    Position the clock and register the three parties and the laboratory.

    Every later landing needs these: the redeveloper owns the parcel, the consultant
    performs the assessments and files the remedy, the insurer prices the cost cap and
    the laboratory receives the monitoring events.
    """
    world = World(api)
    set_clock(api, clock)
    world.redeveloper = get_success_data(
        api.create_party(redeveloper_payload(), PROGRAM_ADMIN), 201
    )
    world.consultant = get_success_data(
        api.create_party(consultant_payload(), PROGRAM_ADMIN), 201
    )
    world.insurer = get_success_data(
        api.create_party(insurer_payload(), PROGRAM_ADMIN), 201
    )
    world.laboratory = get_success_data(
        api.create_laboratory(laboratory_payload(), PROGRAM_ADMIN), 201
    )
    return world


def add_party(world: World, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Register one more party, for tests that need a second or a wrongly typed one."""
    return get_success_data(world.api.create_party(payload, PROGRAM_ADMIN), 201)


def add_laboratory(world: World, **overrides) -> Dict[str, Any]:
    """Register one more laboratory, for the capacity rule's second bench."""
    return get_success_data(
        world.api.create_laboratory(laboratory_payload(**overrides), PROGRAM_ADMIN), 201
    )


# ─── Landing 2: the parcel ────────────────────────────────────────────────────


def stage_site(world: World, **overrides) -> World:
    """Declare the parcel the redeveloper is pursuing."""
    world.site = get_success_data(
        world.api.create_site(
            site_payload(world.redeveloper["id"], **overrides), world.redev_headers
        ),
        201,
    )
    return world


def add_site(world: World, **overrides) -> Dict[str, Any]:
    """Declare a second parcel, for the tests that need two."""
    return get_success_data(
        world.api.create_site(
            site_payload(world.redeveloper["id"], **overrides), world.redev_headers
        ),
        201,
    )


def stage_protection(world: World, site: Optional[Dict[str, Any]] = None) -> World:
    """Open the parcel's liability-protection record."""
    target = site or world.site
    world.protection = get_success_data(
        world.api.create_liability_protection(
            liability_protection_payload(target["id"]), world.redev_headers
        ),
        201,
    )
    return world


# ─── Landing 3: the approved PHASE_I and the inquiry ──────────────────────────


def add_assessment_phase(world: World, **overrides) -> Dict[str, Any]:
    """File one assessment phase in DRAFT."""
    payload = assessment_phase_payload(
        overrides.pop("site_id", world.site["id"]),
        overrides.pop("consultant_party_id", world.consultant["id"]),
        **overrides,
    )
    return get_success_data(
        world.api.create_assessment_phase(payload, world.consult_headers), 201
    )


def add_finding(world: World, phase: Dict[str, Any], **overrides) -> Dict[str, Any]:
    """Record one contaminant finding against a draft phase."""
    return get_success_data(
        world.api.record_contaminant_finding(
            phase["id"], finding_payload(**overrides), world.consult_headers
        ),
        201,
    )


def submit_phase(world: World, phase: Dict[str, Any]) -> Dict[str, Any]:
    """Submit a draft phase for review."""
    return get_success_data(
        world.api.submit_assessment_phase(phase["id"], world.consult_headers)
    )


def review_phase(
    world: World,
    phase: Dict[str, Any],
    decision: str = "APPROVE",
    headers=REVIEWER_ALPHA,
    **overrides,
) -> Dict[str, Any]:
    """Record a reviewer's decision on a submitted phase."""
    return get_success_data(
        world.api.review_assessment_phase(
            phase["id"], phase_review_payload(decision=decision, **overrides), headers
        )
    )


def stage_phase_i(world: World, **phase_overrides) -> World:
    """
    Carry a PHASE_I assessment from filing through approval.

    One SOIL_VAPOR finding at 480 against a 5.0 screening level is recorded so the
    phase has something to submit and the parcel has a documented exceedance.
    """
    world.phase_i = add_assessment_phase(world, phase_type="PHASE_I", **phase_overrides)
    world.phase_i_finding = add_finding(world, world.phase_i)
    submit_phase(world, world.phase_i)
    review_phase(world, world.phase_i, "APPROVE")
    world.phase_i = get_success_data(
        world.api.get_assessment_phase(world.phase_i["id"], world.consult_headers)
    )
    return world


def stage_inquiry(world: World, phase: Optional[Dict[str, Any]] = None) -> World:
    """Record the all-appropriate-inquiries phase against the protection."""
    basis = phase or world.phase_i
    world.protection = get_success_data(
        world.api.complete_inquiry(
            world.protection["id"],
            inquiry_completion_payload(basis["id"]),
            world.consult_headers,
        )
    )
    return world


def stage_acquisition(
    world: World,
    clock: str = "2026-10-15T00:00:00Z",
    acquisition_date: str = "2026-10-15",
) -> World:
    """Advance the clock to closing and record the acquisition."""
    set_clock(world.api, clock)
    world.site = get_success_data(
        world.api.record_acquisition(
            world.site["id"], acquisition_payload(acquisition_date), world.redev_headers
        )
    )
    return world


# ─── Landing 4: the approved PHASE_II ─────────────────────────────────────────


def stage_phase_ii(world: World, clock: str = "2026-12-10T00:00:00Z", **overrides) -> World:
    """
    Carry a PHASE_II assessment from filing through approval.

    Its three findings give the parcel two distinct SOIL_VAPOR analytes above their
    screening levels and one groundwater analyte, and its highest exceedance factor is
    4.80 — below the threshold that adds to the contingency tier.
    """
    set_clock(world.api, clock)
    payload = phase_ii_payload(world.site["id"], world.consultant["id"], **overrides)
    world.phase_ii = get_success_data(
        world.api.create_assessment_phase(payload, world.consult_headers), 201
    )
    world.phase_ii_findings = [
        add_finding(
            world,
            world.phase_ii,
            contaminant_code="TCE",
            media="SOIL_VAPOR",
            sample_location_code="SV-11",
            max_concentration_ugl=24.0,
            screening_level_ugl=5.0,
            delineated=True,
        ),
        add_finding(
            world,
            world.phase_ii,
            contaminant_code="PCE",
            media="SOIL_VAPOR",
            sample_location_code="SV-12",
            max_concentration_ugl=4.75,
            screening_level_ugl=2.5,
            delineated=True,
        ),
        add_finding(
            world,
            world.phase_ii,
            contaminant_code="BENZENE",
            media="GROUNDWATER",
            sample_location_code="MW-03",
            max_concentration_ugl=22.5,
            screening_level_ugl=5.0,
            delineated=True,
        ),
    ]
    submit_phase(world, world.phase_ii)
    review_phase(world, world.phase_ii, "APPROVE")
    world.phase_ii = get_success_data(
        world.api.get_assessment_phase(world.phase_ii["id"], world.consult_headers)
    )
    return world


def stage_assessed(api: BrownfieldClient, **site_overrides) -> World:
    """
    The whole pre-remedy chain: registry, parcel, protection, both approved phases.

    This is where most rules become reachable, because the parcel now has an
    established inquiry record, a recorded acquisition and a delineated PHASE_II.
    """
    world = stage_registry(api)
    stage_site(world, **site_overrides)
    stage_protection(world)
    stage_phase_i(world)
    stage_inquiry(world)
    stage_acquisition(world)
    stage_phase_ii(world)
    return world


# ─── Landing 5: the cleanup goals ─────────────────────────────────────────────


def add_goal(world: World, **overrides) -> Dict[str, Any]:
    """Derive one cleanup goal for the parcel."""
    return get_success_data(
        world.api.derive_cleanup_goal(
            overrides.pop("site_id", world.site["id"]),
            cleanup_goal_payload(**overrides),
            world.consult_headers,
        ),
        201,
    )


def stage_goals(world: World) -> World:
    """
    Derive the parcel's two soil-vapour goals, one on each basis.

    The restricted goal credits the vapour-mitigation control; the unrestricted goal
    takes no credit at all. Both are derived after the phases are approved, so the
    distinct-analyte count that drives the cumulative cap is settled.
    """
    world.goal_restricted = add_goal(
        world,
        contaminant_code="TCE",
        media="SOIL_VAPOR",
        screening_level_ugl=5.0,
        basis="RESTRICTED",
        control_credit_type="VAPOR_MITIGATION",
    )
    world.goal_unrestricted = add_goal(
        world,
        contaminant_code="PCE",
        media="SOIL_VAPOR",
        screening_level_ugl=5.0,
        basis="UNRESTRICTED",
    )
    return world


# ─── Landing 6: the enrollment ────────────────────────────────────────────────


def add_enrollment(world: World, **overrides) -> Dict[str, Any]:
    """Apply to the voluntary cleanup programme."""
    return get_success_data(
        world.api.create_enrollment(
            enrollment_payload(overrides.pop("site_id", world.site["id"]), **overrides),
            world.redev_headers,
        ),
        201,
    )


def decide_eligibility(
    world: World,
    enrollment: Optional[Dict[str, Any]] = None,
    decision: str = "ENROLL",
    headers=REVIEWER_ALPHA,
    **overrides,
) -> Dict[str, Any]:
    """Record the agency's eligibility decision on an application."""
    target = enrollment or world.enrollment
    return get_success_data(
        world.api.decide_eligibility(
            target["id"],
            eligibility_decision_payload(decision=decision, **overrides),
            headers,
        )
    )


def stage_enrollment(world: World, **overrides) -> World:
    """Apply and be accepted onto the restricted-closure track."""
    world.enrollment = add_enrollment(world, **overrides)
    world.enrollment = decide_eligibility(world, world.enrollment, "ENROLL")
    world.enrollment_version = world.enrollment["version"]
    return world


def stage_enrolled(api: BrownfieldClient, **site_overrides) -> World:
    """The chain through an accepted enrollment with both cleanup goals derived."""
    world = stage_assessed(api, **site_overrides)
    stage_goals(world)
    stage_enrollment(world)
    return world


# ─── Landing 7: the remedy and its control ────────────────────────────────────


def add_plan(world: World, **overrides) -> Dict[str, Any]:
    """File one remedial action plan in DRAFT."""
    payload = plan_payload(
        overrides.pop("vcp_enrollment_id", world.enrollment["id"]),
        overrides.pop("site_id", world.site["id"]),
        overrides.pop("basis_assessment_phase_id", world.phase_ii["id"]),
        overrides.pop("expected_vcp_enrollment_version", world.enrollment_version),
        **overrides,
    )
    return get_success_data(world.api.create_plan(payload, world.consult_headers), 201)


def add_control(world: World, plan: Optional[Dict[str, Any]] = None, **overrides) -> Dict[str, Any]:
    """Register one site control against a plan."""
    target = plan or world.plan
    payload = site_control_payload(
        overrides.pop("site_id", world.site["id"]),
        overrides.pop("remedial_action_plan_id", target["id"]),
        **overrides,
    )
    return get_success_data(
        world.api.create_site_control(payload, world.consult_headers), 201
    )


def stage_plan(world: World, cost_lines: Optional[List[Dict[str, Any]]] = None, **overrides) -> World:
    """
    File the draft remedy and the vapour-mitigation control the restricted goal credits.

    The six canonical cost lines are used unless a test supplies its own, and the
    enrollment version captured at acceptance is echoed back so the filing passes the
    concurrency check.
    """
    world.plan = add_plan(
        world,
        cost_lines=canonical_cost_lines() if cost_lines is None else cost_lines,
        **overrides,
    )
    world.control = add_control(world)
    return world


def submit_plan(world: World, plan: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Submit a draft remedy, which forks it into technical review and comment."""
    target = plan or world.plan
    return get_success_data(
        world.api.submit_plan(target["id"], world.consult_headers)
    )


def technical_review(
    world: World,
    plan: Optional[Dict[str, Any]] = None,
    decision: str = "PASS",
    headers=REVIEWER_ALPHA,
    **overrides,
) -> Dict[str, Any]:
    """Record a technical decision on a submitted remedy."""
    target = plan or world.plan
    return get_success_data(
        world.api.technical_review_plan(
            target["id"],
            technical_review_payload(decision=decision, **overrides),
            headers,
        )
    )


def close_comment(
    world: World,
    plan: Optional[Dict[str, Any]] = None,
    public_comment_count: int = 7,
    headers=REVIEWER_ALPHA,
) -> Dict[str, Any]:
    """Close the public comment period on a remedy."""
    target = plan or world.plan
    return get_success_data(
        world.api.close_public_comment(
            target["id"], public_comment_close_payload(public_comment_count), headers
        )
    )


def approve_plan(
    world: World, plan: Optional[Dict[str, Any]] = None, headers=REVIEWER_ALPHA
) -> Dict[str, Any]:
    """Approve a remedy whose two branches have both landed."""
    target = plan or world.plan
    return get_success_data(world.api.approve_plan(target["id"], headers))


def stage_plan_approved(world: World, headers=REVIEWER_ALPHA) -> World:
    """Carry the filed remedy through both fork branches and into approval."""
    submit_plan(world)
    technical_review(world, decision="PASS")
    close_comment(world)
    world.plan = approve_plan(world, headers=headers)
    world.control = world.read_control()
    return world


def stage_approved(api: BrownfieldClient, cost_lines=None, **site_overrides) -> World:
    """The whole chain through an APPROVED remedy with an APPROVED control."""
    world = stage_enrolled(api, **site_overrides)
    stage_plan(world, cost_lines=cost_lines)
    stage_plan_approved(world)
    return world


# ─── Landing 8: the cost cap ──────────────────────────────────────────────────


def add_policy(world: World, **overrides) -> Dict[str, Any]:
    """Ask the insurer to price a cost cap over the approved remedy."""
    payload = policy_payload(
        overrides.pop("remedial_action_plan_id", world.plan["id"]),
        overrides.pop("insurer_party_id", world.insurer["id"]),
        overrides.pop("expected_remedial_action_plan_version", world.plan["version"]),
        **overrides,
    )
    return get_success_data(world.api.quote_policy(payload, world.insurer_headers), 201)


def stage_quote(world: World, **overrides) -> World:
    """Price one cost-cap policy against the current plan version."""
    world.policy = add_policy(world, **overrides)
    return world


def stage_bind(world: World) -> World:
    """Bind the quoted policy, folding its premium into the funding need."""
    world.policy = get_success_data(
        world.api.bind_policy(world.policy["id"], world.insurer_headers)
    )
    world.plan = world.read_plan()
    return world


# ─── Landing 9: continuing obligations ────────────────────────────────────────

# The five duty categories and the weight each one carries, in the order a reviewer
# would naturally impose them.
_OBLIGATION_SPECS = (
    ("REASONABLE_STEPS", "Maintain fencing, signage and stormwater controls.", "2027-03-01", 90),
    (
        "LAND_USE_RESTRICTION_COMPLIANCE",
        "Honour the commercial-only land use restriction.",
        "2027-03-01",
        180,
    ),
    (
        "INSTITUTIONAL_CONTROL_MAINTENANCE",
        "Inspect and maintain the sub-slab depressurisation system.",
        "2027-03-01",
        90,
    ),
    ("ACCESS_AND_COOPERATION", "Provide agency access on 24 hours notice.", "2027-06-01", 365),
    (
        "NOTIFICATION",
        "Report any newly discovered contamination within 30 days.",
        "2027-06-01",
        365,
    ),
)


def impose_obligation(world: World, headers=REVIEWER_ALPHA, **overrides) -> Dict[str, Any]:
    """Impose one continuing obligation on the parcel's protection."""
    return get_success_data(
        world.api.impose_continuing_obligation(
            world.protection["id"], continuing_obligation_payload(**overrides), headers
        ),
        201,
    )


def stage_obligations(world: World, headers=REVIEWER_ALPHA) -> World:
    """
    Impose one duty in each of the five declared categories.

    The two defence-critical categories are imposed alongside the three that are not,
    so a test can tell a lapse that forfeits the defence from one that merely drags the
    compliance figure down.
    """
    for category, description, due_date, recurrence_days in _OBLIGATION_SPECS:
        world.obligations[category] = impose_obligation(
            world,
            headers=headers,
            obligation_category=category,
            description=description,
            due_date=due_date,
            recurrence_days=recurrence_days,
        )
    world.protection = world.read_protection()
    return world


def certify_obligation(world: World, obligation: Dict[str, Any]) -> Dict[str, Any]:
    """The owning redeveloper certifies one duty for the current period."""
    return get_success_data(
        world.api.certify_obligation(obligation["id"], world.redev_headers)
    )


def void_certification(
    world: World, obligation: Dict[str, Any], headers=REVIEWER_BETA, **overrides
) -> Dict[str, Any]:
    """A reviewer other than the imposing one voids a certification."""
    from .factories import void_payload

    return get_success_data(
        world.api.void_certification(obligation["id"], headers, void_payload(**overrides))
    )


def run_sweep(
    world: World,
    as_of_date: str,
    site_id: Optional[str] = None,
    headers=REVIEWER_ALPHA,
) -> Dict[str, Any]:
    """Run the compliance sweep, optionally scoped to one parcel."""
    return get_success_data(
        world.api.run_compliance_sweep(as_of_date, headers, site_id=site_id)
    )


# ─── Landing 10: controls in operation ────────────────────────────────────────


def certify_control(
    world: World,
    control: Optional[Dict[str, Any]] = None,
    condition: str = "PASS",
    certification_date: str = "2027-01-15",
) -> Dict[str, Any]:
    """The owning redeveloper certifies a control's condition for a date."""
    target = control or world.control
    return get_success_data(
        world.api.certify_control_operation(
            target["id"],
            operation_certification_payload(
                condition=condition, certification_date=certification_date
            ),
            world.redev_headers,
        )
    )


def stage_control_operating(
    world: World, clock: str = "2027-01-15T00:00:00Z", certification_date: str = "2027-01-15"
) -> World:
    """
    Advance into the coverage period and put the control into service.

    The first passing certification is what moves the enrollment out of remedy approval
    and into implementation, so this landing is a precondition for everything that
    follows on the operational side.
    """
    set_clock(world.api, clock)
    world.control = certify_control(
        world, condition="PASS", certification_date=certification_date
    )
    world.enrollment = world.read_enrollment()
    world.site = world.read_site()
    return world


def stage_implementation(api: BrownfieldClient, cost_lines=None, **site_overrides) -> World:
    """The chain through an OPERATING control, so the enrollment is in implementation."""
    world = stage_approved(api, cost_lines=cost_lines, **site_overrides)
    stage_control_operating(world)
    return world


# ─── Landing 11: monitoring ───────────────────────────────────────────────────


def add_event(world: World, **overrides) -> Dict[str, Any]:
    """Schedule one monitoring event with the laboratory."""
    payload = monitoring_event_payload(
        overrides.pop("site_id", world.site["id"]),
        overrides.pop("laboratory_id", world.laboratory["id"]),
        overrides.pop("cleanup_goal_id", world.goal_restricted["id"]),
        **overrides,
    )
    return get_success_data(
        world.api.create_monitoring_event(payload, world.consult_headers), 201
    )


def file_result(world: World, event: Dict[str, Any], result_value_ugl) -> Dict[str, Any]:
    """The consultant files a sampling result against a scheduled event."""
    return get_success_data(
        world.api.file_monitoring_result(
            event["id"], sampling_result_payload(result_value_ugl), world.consult_headers
        )
    )


# Four consecutive monthly sampling windows, which is exactly the streak the contract
# requires before a goal counts as attained.
_ATTAINMENT_WINDOWS = (
    ("2027-M02", "2027-02-05", "2027-02-01T00:00:00Z", "2027-02-10T00:00:00Z"),
    ("2027-M03", "2027-03-05", "2027-03-01T00:00:00Z", "2027-03-10T00:00:00Z"),
    ("2027-M04", "2027-04-05", "2027-04-01T00:00:00Z", "2027-04-10T00:00:00Z"),
    ("2027-M05", "2027-05-05", "2027-05-01T00:00:00Z", "2027-05-10T00:00:00Z"),
)


def schedule_attainment_events(
    world: World, goal: Dict[str, Any], prefix: str = ""
) -> List[Dict[str, Any]]:
    """Schedule the four consecutive sampling events one goal needs to attain."""
    events = []
    for code, sample_date, window_start, window_end in _ATTAINMENT_WINDOWS:
        events.append(
            add_event(
                world,
                cleanup_goal_id=goal["id"],
                monitoring_period_code=f"{prefix}{code}",
                sample_date=sample_date,
                window_start=window_start,
                window_end=window_end,
            )
        )
    return events


def stage_goal_attained(
    world: World,
    goal: Dict[str, Any],
    result_value_ugl=100.0,
    prefix: str = "",
    clock: str = "2027-06-01T00:00:00Z",
) -> List[Dict[str, Any]]:
    """
    Drive one goal to ATTAINED with four compliant results.

    All four events are scheduled first and the clock is then moved past the last
    window, because a result cannot be filed before its own window has opened.
    """
    events = schedule_attainment_events(world, goal, prefix=prefix)
    set_clock(world.api, clock)
    for event in events:
        file_result(world, event, result_value_ugl)
    return events


def stage_all_goals_attained(world: World, clock: str = "2027-06-01T00:00:00Z") -> World:
    """
    Drive both of the parcel's goals to ATTAINED.

    The results are 100.0, comfortably inside both attenuated goal figures, so the
    streak reaches four on each goal without any exceedance in between.
    """
    events = schedule_attainment_events(world, world.goal_restricted, prefix="G1-")
    events += schedule_attainment_events(world, world.goal_unrestricted, prefix="G2-")
    set_clock(world.api, clock)
    for event in events:
        file_result(world, event, 100.0)
    return world


# ─── Landing 12: funding ──────────────────────────────────────────────────────


def add_award(world: World, **overrides) -> Dict[str, Any]:
    """Apply to one funding programme for the parcel."""
    payload = funding_award_payload(
        overrides.pop("site_id", world.site["id"]), **overrides
    )
    return get_success_data(
        world.api.create_funding_award(payload, world.redev_headers), 201
    )


def add_tax_credit_award(world: World, **overrides) -> Dict[str, Any]:
    """Apply to the remediation tax-credit programme for the parcel."""
    payload = tax_credit_award_payload(
        overrides.pop("site_id", world.site["id"]), **overrides
    )
    return get_success_data(
        world.api.create_funding_award(payload, world.redev_headers), 201
    )


def decide_award(
    world: World, award: Dict[str, Any], decision: str = "AWARD", headers=REVIEWER_ALPHA, **overrides
) -> Dict[str, Any]:
    """Record the agency's decision on a funding application."""
    from .factories import funding_decision_payload

    return get_success_data(
        world.api.decide_funding_award(
            award["id"], funding_decision_payload(decision=decision, **overrides), headers
        )
    )


def stage_two_awards(world: World) -> World:
    """
    Apply to both programmes, the grant at priority 1 and the tax credit at priority 2.

    Their eligible categories do not overlap, so the two draw on different parts of the
    same design estimate and the fill order is observable in the allocations.
    """
    world.awards = [add_award(world), add_tax_credit_award(world)]
    return world


def stage_two_awards_granted(world: World) -> World:
    """Apply to both programmes and have both applications awarded."""
    stage_two_awards(world)
    world.awards = [decide_award(world, award, "AWARD") for award in world.awards]
    return world


# ─── Landing 13: closure ──────────────────────────────────────────────────────


def request_completion(world: World) -> Dict[str, Any]:
    """The owning redeveloper asks the agency to review the remedy as complete."""
    return get_success_data(
        world.api.request_completion(world.enrollment["id"], world.redev_headers)
    )


def add_letter(world: World, **overrides) -> Dict[str, Any]:
    """Draft a closure letter request at the given scope."""
    payload = nfa_letter_payload(
        overrides.pop("site_id", world.site["id"]),
        overrides.pop("vcp_enrollment_id", world.enrollment["id"]),
        **overrides,
    )
    return get_success_data(world.api.create_nfa_letter(payload, world.redev_headers), 201)


def issue_letter(
    world: World, letter: Optional[Dict[str, Any]] = None, headers=REVIEWER_BETA
) -> Dict[str, Any]:
    """
    A reviewer issues the letter.

    The default identity is deliberately not the reviewer who approved the remedy,
    because the contract refuses the issuance when the two coincide.
    """
    target = letter or world.letter
    return get_success_data(world.api.issue_nfa_letter(target["id"], headers))


def accept_letter(world: World, letter: Optional[Dict[str, Any]] = None, **overrides) -> Dict[str, Any]:
    """A lender records reliance on the issued letter."""
    target = letter or world.letter
    return get_success_data(
        world.api.accept_nfa_letter(target["id"], lender_acceptance_payload(**overrides), LENDER)
    )


def stage_completion_review(world: World, clock: str = "2027-06-01T00:00:00Z") -> World:
    """
    Bring the enrollment to completion review with a drafted closure letter.

    Both goals are attained and the single control is operating, which are exactly the
    two conditions the completion request tests.
    """
    stage_all_goals_attained(world, clock=clock)
    world.enrollment = request_completion(world)
    world.letter = add_letter(world)
    return world


def stage_closed(api: BrownfieldClient, **site_overrides) -> World:
    """
    The whole chain to a closed enrollment with an issued, lender-accepted letter.

    This is the deepest landing: registry, parcel, protection, two approved phases, two
    goals, an accepted enrollment, an approved remedy, an operating control, four
    compliant results on each goal, a completion request, and an issued letter the
    lender has relied on.
    """
    world = stage_implementation(api, **site_overrides)
    stage_completion_review(world)
    world.letter = issue_letter(world)
    world.letter = accept_letter(world)
    world.enrollment = world.read_enrollment()
    return world


# ─── Composite fixtures at the common landings ────────────────────────────────


@pytest.fixture
def registry(api: BrownfieldClient) -> World:
    """Three parties and one laboratory, clock at the epoch."""
    return stage_registry(api)


@pytest.fixture
def sited(api: BrownfieldClient) -> World:
    """A declared parcel with its liability-protection record open."""
    world = stage_registry(api)
    stage_site(world)
    stage_protection(world)
    return world


@pytest.fixture
def assessed(api: BrownfieldClient) -> World:
    """Both assessment phases approved, inquiry recorded, acquisition closed."""
    return stage_assessed(api)


@pytest.fixture
def enrolled(api: BrownfieldClient) -> World:
    """Both cleanup goals derived and the enrollment accepted."""
    return stage_enrolled(api)


@pytest.fixture
def planned(api: BrownfieldClient) -> World:
    """A draft remedy on the six canonical cost lines, with its proposed control."""
    world = stage_enrolled(api)
    stage_plan(world)
    return world


@pytest.fixture
def approved(api: BrownfieldClient) -> World:
    """An approved remedy and an approved control."""
    return stage_approved(api)


@pytest.fixture
def quoted(api: BrownfieldClient) -> World:
    """An approved remedy with one quoted cost-cap policy over it."""
    world = stage_approved(api)
    stage_quote(world)
    return world


@pytest.fixture
def bound(api: BrownfieldClient) -> World:
    """An approved remedy with one bound cost-cap policy folded into the need."""
    world = stage_approved(api)
    stage_quote(world)
    stage_bind(world)
    return world


@pytest.fixture
def implementing(api: BrownfieldClient) -> World:
    """An operating control, so the enrollment sits in implementation."""
    return stage_implementation(api)


@pytest.fixture
def obligated(api: BrownfieldClient) -> World:
    """A protection carrying one duty in each of the five categories."""
    world = stage_registry(api)
    stage_site(world)
    stage_protection(world)
    stage_phase_i(world)
    stage_inquiry(world)
    stage_acquisition(world)
    stage_obligations(world)
    return world


@pytest.fixture
def closed(api: BrownfieldClient) -> World:
    """A closed enrollment with an issued, lender-accepted closure letter."""
    return stage_closed(api)

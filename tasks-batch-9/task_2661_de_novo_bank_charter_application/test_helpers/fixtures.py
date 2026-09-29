"""
Composite state builders for the De Novo Bank Charter Application API.

The harness restarts the service before every individual test, so every test
starts against an empty database and a logical clock sitting at its startup
value. Nothing here reaches behind the API: each builder walks the same public
endpoints a real charter project would, in the order the PRD requires, and
returns the ids it minted along the way.

The canonical project used throughout is "Cascade Charter Bank", a NATIONAL
charter in WA, seated with five organizers whose persisted integer subscores are
68, 76, 54, 97 and 64 — a management composite of 71.80, comfortably above the
70.00 floor, with all four key officer roles qualified, four independent members
and no affiliation code held by more than two organizers.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .test_users import (
    CHARTERING_EXAMINER_HEADERS,
    COUNSEL_HEADERS,
    ESCROW_AGENT_HEADERS,
    INSURANCE_EXAMINER_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    make_lead_organizer_headers,
)
from .types import (
    AUTHORITY_CHARTERING,
    AUTHORITY_DEPOSIT_INSURER,
    CREDIT_CLEARED,
    DECISION_CONDITIONALLY_APPROVED,
    DECISION_FINAL_APPROVED,
    DIMENSION_CREDIT,
    DIMENSION_FINGERPRINT,
    DOMAIN_COMPLIANCE_BSA_AML,
    DOMAIN_INFORMATION_SECURITY,
    DOMAIN_LENDING,
    DOMAIN_RISK_MANAGEMENT,
    EXAM_OUTCOME_DEFICIENT,
    EXAM_OUTCOME_PASSED,
    EXAM_SCOPE_FULL,
    FINGERPRINT_CLEARED,
    FUNDING_EVENT_FUND,
    REVIEW_ACCEPTED,
    SCENARIO_ADVERSE,
    STAGE_FILING_READY,
    STAGE_OPEN,
    STAGE_PRE_OPENING,
    VENDOR_SELECTED,
    VENDOR_SIGNED,
)

# ---------------------------------------------------------------------------
# The canonical organizing group and its five seats (PRD 3.1)
# ---------------------------------------------------------------------------
CANONICAL_ORGANIZERS: List[Dict[str, Any]] = [
    {
        "key": "o1",
        "full_name": "Dana Whitfield",
        "role_on_board": "PROPOSED_CEO",
        "is_independent": False,
        "affiliation_code": "FIRSTCAP",
        "banking_years": 7,
        "regulatory_experience_score": 83,
        "expected_subscore": 68,
    },
    {
        "key": "o2",
        "full_name": "Marcus Ibarra",
        "role_on_board": "PROPOSED_CFO",
        "is_independent": False,
        "affiliation_code": "FIRSTCAP",
        "banking_years": 13,
        "regulatory_experience_score": 71,
        "expected_subscore": 76,
    },
    {
        "key": "o3",
        "full_name": "Priya Raghunathan",
        "role_on_board": "PROPOSED_CRO",
        "is_independent": True,
        "affiliation_code": "IND_A",
        "banking_years": 3,
        "regulatory_experience_score": 66,
        "expected_subscore": 54,
    },
    {
        "key": "o4",
        "full_name": "Elena Kowalski",
        "role_on_board": "PROPOSED_CCO",
        "is_independent": True,
        "affiliation_code": "IND_B",
        "banking_years": 20,
        "regulatory_experience_score": 90,
        "expected_subscore": 97,
    },
    {
        "key": "o5",
        "full_name": "Theo Nakamura",
        "role_on_board": "DIRECTOR",
        "is_independent": True,
        "affiliation_code": "IND_C",
        "banking_years": 10,
        "regulatory_experience_score": 54,
        "expected_subscore": 64,
    },
]

# Composite of the five persisted integers: (68+76+54+97+64) / 5.
CANONICAL_COMPOSITE_SCORE = 71.80
# Composite with only the first four seated: (68+76+54+97) / 4.
FOUR_SEAT_COMPOSITE_SCORE = 73.75


def _org_payload(spec: Dict[str, Any]) -> Dict[str, Any]:
    return f.organizer_payload(
        full_name=spec["full_name"],
        role_on_board=spec["role_on_board"],
        is_independent=spec["is_independent"],
        affiliation_code=spec["affiliation_code"],
        banking_years=spec["banking_years"],
        regulatory_experience_score=spec["regulatory_experience_score"],
    )


# ---------------------------------------------------------------------------
# Tier 0 helpers
# ---------------------------------------------------------------------------
def set_clock(api, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock forward, as only a PlatformAdmin may."""
    return get_success_data(api.set_clock(to_iso8601, PLATFORM_ADMIN_HEADERS))


def read_group(api, group_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_organizing_group(group_id, COUNSEL_HEADERS))


def group_version(api, group_id: str) -> int:
    """Re-read the group so a business-plan create can carry a fresh expectation."""
    return read_group(api, group_id)["version"]


def read_contract(api, contract_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_vendor_contract(contract_id, COUNSEL_HEADERS))


def contract_version(api, contract_id: str) -> int:
    return read_contract(api, contract_id)["version"]


def read_raise(api, raise_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_capital_raise(raise_id, COUNSEL_HEADERS))


def read_filing(api, filing_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_regulatory_filing(filing_id, COUNSEL_HEADERS))


def read_condition(api, condition_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_approval_condition(condition_id, COUNSEL_HEADERS))


def read_policy(api, policy_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_policy_document(policy_id, COUNSEL_HEADERS))


def read_plan(api, plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_business_plan(plan_id, COUNSEL_HEADERS))


def read_exam(api, exam_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_readiness_exam(exam_id, COUNSEL_HEADERS))


def read_subscription(api, subscription_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_subscription(subscription_id, COUNSEL_HEADERS))


def read_window(api, window_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_conversion_window(window_id, COUNSEL_HEADERS))


def read_deviation(api, deviation_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_deviation_request(deviation_id, COUNSEL_HEADERS))


# ---------------------------------------------------------------------------
# Tier 1 — the bare group and its seats
# ---------------------------------------------------------------------------
def open_group(api, **overrides: Any) -> Dict[str, Any]:
    """A brand-new organizing file at stage ORGANIZING with composition FORMING."""
    data = get_success_data(
        api.create_organizing_group(f.organizing_group_payload(**overrides), COUNSEL_HEADERS),
        expected_status=201,
    )
    return {"group_id": data["id"], "group": data}


def seat_organizer(api, group_id: str, spec: Dict[str, Any]) -> str:
    data = get_success_data(
        api.create_organizer(group_id, _org_payload(spec), COUNSEL_HEADERS),
        expected_status=201,
    )
    return data["id"]


def clear_background(api, organizer_id: str, both: bool = True) -> None:
    """Record CLEARED on the fingerprint dimension, and by default on credit too."""
    get_success_data(
        api.record_background_result(
            organizer_id,
            f.background_result_payload(
                dimension=DIMENSION_FINGERPRINT, outcome=FINGERPRINT_CLEARED
            ),
            CHARTERING_EXAMINER_HEADERS,
        )
    )
    if both:
        get_success_data(
            api.record_background_result(
                organizer_id,
                f.background_result_payload(
                    dimension=DIMENSION_CREDIT, outcome=CREDIT_CLEARED
                ),
                CHARTERING_EXAMINER_HEADERS,
            )
        )


def seated_group(api, seats: int = 5, clear: bool = True, **group_overrides: Any):
    """
    Seat the first `seats` canonical organizers and clear both background
    dimensions on each. With five seats the group reaches COMPOSITION_MET with a
    management composite of 71.80; with four it stays FORMING at 73.75.
    """
    world = open_group(api, **group_overrides)
    for spec in CANONICAL_ORGANIZERS[:seats]:
        world[spec["key"]] = seat_organizer(api, world["group_id"], spec)
    if clear:
        for spec in CANONICAL_ORGANIZERS[:seats]:
            clear_background(api, world[spec["key"]])
    world["organizer_ids"] = [world[s["key"]] for s in CANONICAL_ORGANIZERS[:seats]]
    world["lead_headers"] = make_lead_organizer_headers(world["o1"])
    return world


def composition_met_group(api, **group_overrides: Any) -> Dict[str, Any]:
    """The five-seat group whose composition_status is COMPOSITION_MET."""
    return seated_group(api, seats=5, clear=True, **group_overrides)


def second_group(api) -> Dict[str, Any]:
    """
    A wholly separate charter project, used wherever a foreign organizer or a
    foreign parent row is needed. PRD 2.1 and 3.7 both compare a supplied
    organizer against the group in scope, so the mismatch cases need a real
    organizer that belongs somewhere else.
    """
    world = open_group(
        api,
        proposed_bank_name="Rainier Community Bank",
        home_state_code="OR",
        target_opening_date="2027-06-01T00:00:00Z",
    )
    world["ob1"] = seat_organizer(
        api,
        world["group_id"],
        {
            "full_name": "Yusuf Bello",
            "role_on_board": "PROPOSED_CEO",
            "is_independent": False,
            "affiliation_code": "RAINIER",
            "banking_years": 12,
            "regulatory_experience_score": 80,
        },
    )
    clear_background(api, world["ob1"])
    return world


# ---------------------------------------------------------------------------
# Tier 2 — the business plan and its overlay
# ---------------------------------------------------------------------------
def add_business_plan(api, world: Dict[str, Any], **plan_overrides: Any) -> str:
    """Create a plan against the group, carrying a freshly read group version."""
    payload = f.business_plan_payload(
        world["group_id"], group_version(api, world["group_id"]), **plan_overrides
    )
    data = get_success_data(
        api.create_business_plan(payload, COUNSEL_HEADERS), expected_status=201
    )
    return data["id"]


def add_stress_scenario(
    api, plan_id: str, scenario_code: str = SCENARIO_ADVERSE, **overrides: Any
) -> str:
    data = get_success_data(
        api.create_stress_scenario(
            plan_id, f.stress_scenario_payload(scenario_code, **overrides), COUNSEL_HEADERS
        ),
        expected_status=201,
    )
    return data["id"]


def submitted_plan_group(api, **group_overrides: Any) -> Dict[str, Any]:
    """
    The canonical group with one plan carrying a single ADVERSE overlay, submitted
    for review. The overlay's governing dynamic path clears the 800 basis point
    stress floor and the plan's adequacy verdict is ADEQUATE, so submission passes
    all six gates.
    """
    world = composition_met_group(api, **group_overrides)
    world["plan_id"] = add_business_plan(api, world)
    world["scenario_id"] = add_stress_scenario(
        api,
        world["plan_id"],
        SCENARIO_ADVERSE,
        credit_loss_rate_bps=60,
        nim_compression_bps=15,
        expense_overrun_cents=0,
    )
    get_success_data(api.submit_business_plan(world["plan_id"], world["lead_headers"]))
    return world


def filing_ready_group(api, **group_overrides: Any) -> Dict[str, Any]:
    """The submitted-plan group advanced from ORGANIZING to FILING_READY."""
    world = submitted_plan_group(api, **group_overrides)
    get_success_data(
        api.advance_group(
            world["group_id"], f.advance_payload(STAGE_FILING_READY), COUNSEL_HEADERS
        )
    )
    return world


# ---------------------------------------------------------------------------
# Tier 3 — the capital raise and escrow
# ---------------------------------------------------------------------------
def add_capital_raise(api, world: Dict[str, Any], **overrides: Any) -> str:
    data = get_success_data(
        api.create_capital_raise(
            f.capital_raise_payload(world["group_id"], **overrides), COUNSEL_HEADERS
        ),
        expected_status=201,
    )
    return data["id"]


def open_raise(api, world: Dict[str, Any], **overrides: Any) -> str:
    """Structure the raise and open the offering for subscription."""
    raise_id = add_capital_raise(api, world, **overrides)
    get_success_data(api.open_capital_raise(raise_id, COUNSEL_HEADERS))
    world["raise_id"] = raise_id
    return raise_id


def add_subscription(
    api,
    raise_id: str,
    subscriber_name: str,
    shares: int,
    organizer_id: Optional[str] = None,
) -> str:
    data = get_success_data(
        api.create_subscription(
            f.subscription_payload(raise_id, subscriber_name, shares, organizer_id),
            ESCROW_AGENT_HEADERS,
        ),
        expected_status=201,
    )
    return data["id"]


def fund(api, subscription_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.record_funding_event(
            subscription_id, f.funding_payload(FUNDING_EVENT_FUND), ESCROW_AGENT_HEADERS
        )
    )


def screen(api, subscription_id: str, outcome: str) -> Dict[str, Any]:
    return get_success_data(
        api.record_screening_result(
            subscription_id, f.screening_payload(outcome), ESCROW_AGENT_HEADERS
        )
    )


def open_raise_with_two_subscriptions(api, world: Dict[str, Any]) -> Dict[str, Any]:
    """
    An open raise carrying the canonical pair of subscriptions: Harbor Trust LP at
    2,000,000 shares and Puget Founders Fund at 2,150,000 shares, priced at 1000
    cents a share, so the pledged basis is 4,150,000,000 cents against a minimum
    of 4,100,000,000. Neither row has been funded or screened yet, so the cleared
    basis is still zero.
    """
    open_raise(api, world)
    world["s1"] = add_subscription(api, world["raise_id"], "Harbor Trust LP", 2_000_000)
    world["s2"] = add_subscription(
        api, world["raise_id"], "Puget Founders Fund", 2_150_000
    )
    return world


def escrow_ready_group(api, **group_overrides: Any) -> Dict[str, Any]:
    """
    The FILING_READY group with both canonical subscriptions funded and cleared,
    so the cleared basis stands at the full 4,150,000,000 cents and the raise is
    lockable.
    """
    world = filing_ready_group(api, **group_overrides)
    open_raise_with_two_subscriptions(api, world)
    fund(api, world["s1"])
    fund(api, world["s2"])
    screen(api, world["s1"], "CLEARED")
    screen(api, world["s2"], "CLEARED")
    return world


def lock_escrow(api, world: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api.lock_escrow(world["raise_id"], ESCROW_AGENT_HEADERS))


# ---------------------------------------------------------------------------
# Tier 4 — the two filings
# ---------------------------------------------------------------------------
def add_filing(api, world: Dict[str, Any], authority: str, plan_id: Optional[str] = None):
    data = get_success_data(
        api.create_regulatory_filing(
            f.regulatory_filing_payload(
                world["group_id"], plan_id or world["plan_id"], authority
            ),
            COUNSEL_HEADERS,
        ),
        expected_status=201,
    )
    return data["id"]


def file_filing(api, filing_id: str) -> Dict[str, Any]:
    return get_success_data(api.file_regulatory_filing(filing_id, COUNSEL_HEADERS))


def examiner_headers_for(authority: str) -> Dict[str, str]:
    """Only the examiner of a filing's own authority may decide or condition it."""
    return (
        CHARTERING_EXAMINER_HEADERS
        if authority == AUTHORITY_CHARTERING
        else INSURANCE_EXAMINER_HEADERS
    )


def decide_filing(api, filing_id: str, decision: str, authority: str, **overrides: Any):
    return get_success_data(
        api.record_filing_decision(
            filing_id,
            f.filing_decision_payload(decision, **overrides),
            examiner_headers_for(authority),
        )
    )


def both_filings_filed(api, world: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare and file both applications, moving the group to UNDER_REVIEW."""
    world["f_ca"] = add_filing(api, world, AUTHORITY_CHARTERING)
    world["f_di"] = add_filing(api, world, AUTHORITY_DEPOSIT_INSURER)
    file_filing(api, world["f_ca"])
    file_filing(api, world["f_di"])
    return world


def conditionally_approved_group(api, **group_overrides: Any) -> Dict[str, Any]:
    """
    Both filings conditionally approved, which pins the plan on the chartering
    side and moves the group from UNDER_REVIEW to CONDITIONALLY_APPROVED, and the
    escrow locked on the cleared basis.
    """
    world = escrow_ready_group(api, **group_overrides)
    both_filings_filed(api, world)
    decide_filing(api, world["f_ca"], DECISION_CONDITIONALLY_APPROVED, AUTHORITY_CHARTERING)
    decide_filing(
        api, world["f_di"], DECISION_CONDITIONALLY_APPROVED, AUTHORITY_DEPOSIT_INSURER
    )
    lock_escrow(api, world)
    return world


# ---------------------------------------------------------------------------
# Tier 4b — conditions of approval
# ---------------------------------------------------------------------------
def add_condition(
    api,
    filing_id: str,
    condition_code: str,
    category: str,
    is_pre_opening_blocking: bool,
    authority: str = AUTHORITY_CHARTERING,
    deadline_utc: str = "2026-12-01T00:00:00Z",
) -> str:
    data = get_success_data(
        api.create_approval_condition(
            filing_id,
            f.approval_condition_payload(
                condition_code=condition_code,
                category=category,
                is_pre_opening_blocking=is_pre_opening_blocking,
                deadline_utc=deadline_utc,
            ),
            examiner_headers_for(authority),
        ),
        expected_status=201,
    )
    return data["id"]


def submit_evidence(api, condition_id: str, evidence_reference: str) -> Dict[str, Any]:
    return get_success_data(
        api.submit_condition_evidence(
            condition_id, f.evidence_payload(evidence_reference), COUNSEL_HEADERS
        )
    )


def adjudicate(
    api, condition_id: str, disposition: str, authority: str = AUTHORITY_CHARTERING
):
    return get_success_data(
        api.adjudicate_condition(
            condition_id,
            f.adjudication_payload(disposition),
            examiner_headers_for(authority),
        )
    )


# ---------------------------------------------------------------------------
# Tier 5 — the operational build-out, pre-opening and opening day
# ---------------------------------------------------------------------------
POLICY_PLAN = (
    ("pol_len", DOMAIN_LENDING, "Lending and Credit Administration Policy", "o3"),
    ("pol_bsa", DOMAIN_COMPLIANCE_BSA_AML, "BSA/AML Compliance Program", "o4"),
    ("pol_sec", DOMAIN_INFORMATION_SECURITY, "Information Security Program", "o5"),
    ("pol_risk", DOMAIN_RISK_MANAGEMENT, "Enterprise Risk Management Policy", "o3"),
)


def draft_policy(
    api,
    world: Dict[str, Any],
    domain: str,
    document_title: str,
    drafter_key: str = "o1",
    headers: Optional[Dict[str, str]] = None,
) -> str:
    """
    Draft a board policy. The drafter is named in the body and the acting
    principal's X-User-ID must be an organizer of the policy's own group, so the
    canonical drafter o1 acts as LeadOrganizer.
    """
    drafter_id = world[drafter_key]
    data = get_success_data(
        api.create_policy_document(
            f.policy_document_payload(
                world["group_id"], drafter_id, domain=domain, document_title=document_title
            ),
            headers or make_lead_organizer_headers(drafter_id),
        ),
        expected_status=201,
    )
    return data["id"]


def adopt_policy(api, world: Dict[str, Any], policy_id: str, adopter_key: str):
    """Board-adopt as an IndependentDirector who is not the drafter."""
    from .test_users import make_independent_director_headers

    return get_success_data(
        api.adopt_policy_document(
            policy_id, make_independent_director_headers(world[adopter_key])
        )
    )


def review_policy(api, policy_id: str, outcome: str = REVIEW_ACCEPTED, **overrides: Any):
    return get_success_data(
        api.review_policy_document(
            policy_id, f.policy_review_payload(outcome, **overrides), CHARTERING_EXAMINER_HEADERS
        )
    )


def all_four_policies_accepted(api, world: Dict[str, Any]) -> Dict[str, Any]:
    """
    Draft, board-adopt and examiner-accept one policy in each of the four required
    domains, which is what the pre-opening coverage gate reads.
    """
    for key, domain, title, adopter in POLICY_PLAN:
        policy_id = draft_policy(api, world, domain, title)
        world[key] = policy_id
        adopt_policy(api, world, policy_id, adopter)
        review_policy(api, policy_id, REVIEW_ACCEPTED)
    return world


def add_vendor_contract(api, world: Dict[str, Any], **overrides: Any) -> str:
    data = get_success_data(
        api.create_vendor_contract(
            f.vendor_contract_payload(world["group_id"], **overrides), COUNSEL_HEADERS
        ),
        expected_status=201,
    )
    return data["id"]


def advance_vendor(api, contract_id: str, target_status: str) -> Dict[str, Any]:
    return get_success_data(
        api.advance_vendor_contract(
            contract_id, f.vendor_advance_payload(target_status), COUNSEL_HEADERS
        )
    )


def signed_core_vendor(api, world: Dict[str, Any], **overrides: Any) -> str:
    """A CRITICAL CORE_PROCESSING contract walked EVALUATING -> SELECTED -> SIGNED."""
    contract_id = add_vendor_contract(api, world, **overrides)
    advance_vendor(api, contract_id, VENDOR_SELECTED)
    advance_vendor(api, contract_id, VENDOR_SIGNED)
    world["vc_id"] = contract_id
    return contract_id


def reserve_window(
    api,
    contract_id: str,
    window_start_utc: str,
    window_end_utc: str,
    expected_vendor_contract_version: Optional[int] = None,
    api_for_version=None,
) -> str:
    version = (
        expected_vendor_contract_version
        if expected_vendor_contract_version is not None
        else contract_version(api, contract_id)
    )
    data = get_success_data(
        api.create_conversion_window(
            f.conversion_window_payload(
                contract_id, version, window_start_utc, window_end_utc
            ),
            COUNSEL_HEADERS,
        ),
        expected_status=201,
    )
    return data["id"]


def pre_opening_group(api, **group_overrides: Any) -> Dict[str, Any]:
    """
    The whole project walked to PRE_OPENING: both filings conditionally approved,
    escrow locked on the cleared basis, all four policy domains examiner-accepted,
    and a signed critical core-processing vendor.
    """
    world = conditionally_approved_group(api, **group_overrides)
    all_four_policies_accepted(api, world)
    signed_core_vendor(api, world)
    get_success_data(
        api.advance_group(
            world["group_id"], f.advance_payload(STAGE_PRE_OPENING), COUNSEL_HEADERS
        )
    )
    return world


def schedule_exam(
    api,
    world: Dict[str, Any],
    window_start_utc: str = "2026-10-05T09:00:00Z",
    window_end_utc: str = "2026-10-07T17:00:00Z",
    exam_scope: str = EXAM_SCOPE_FULL,
) -> str:
    data = get_success_data(
        api.create_readiness_exam(
            world["group_id"],
            f.readiness_exam_payload(window_start_utc, window_end_utc, exam_scope),
            CHARTERING_EXAMINER_HEADERS,
        ),
        expected_status=201,
    )
    return data["id"]


def record_exam_result(api, exam_id: str, outcome: str, finding_count: int = 0):
    return get_success_data(
        api.record_exam_result(
            exam_id,
            f.exam_result_payload(outcome, finding_count),
            CHARTERING_EXAMINER_HEADERS,
        )
    )


def passed_exam_group(api, **group_overrides: Any) -> Dict[str, Any]:
    """
    The PRE_OPENING group with its full-scope examination scheduled, the clock moved
    to the examination's start instant, and a PASSED result carrying two findings.
    """
    world = pre_opening_group(api, **group_overrides)
    world["ex1"] = schedule_exam(api, world)
    set_clock(api, "2026-10-05T09:00:00Z")
    record_exam_result(api, world["ex1"], EXAM_OUTCOME_PASSED, 2)
    return world


def deficient_exam_group(api, **group_overrides: Any) -> Dict[str, Any]:
    """
    The PRE_OPENING group knocked back by a DEFICIENT examination, which returns the
    group to CONDITIONALLY_APPROVED with opening_blocked_reason EXAM_DEFICIENT while
    the deficient examination keeps holding its buffer-extended slot.
    """
    world = pre_opening_group(api, **group_overrides)
    world["ex1"] = schedule_exam(api, world)
    set_clock(api, "2026-10-05T09:00:00Z")
    record_exam_result(api, world["ex1"], EXAM_OUTCOME_DEFICIENT, 9)
    return world


def opened_bank(api, **group_overrides: Any) -> Dict[str, Any]:
    """
    Opening day: a passed examination, both filings final-approved, escrow released
    and the group advanced to OPEN, which starts heightened supervision at year 1.
    """
    world = passed_exam_group(api, **group_overrides)
    decide_filing(api, world["f_ca"], DECISION_FINAL_APPROVED, AUTHORITY_CHARTERING)
    decide_filing(api, world["f_di"], DECISION_FINAL_APPROVED, AUTHORITY_DEPOSIT_INSURER)
    get_success_data(api.release_escrow(world["raise_id"], ESCROW_AGENT_HEADERS))
    get_success_data(
        api.advance_group(world["group_id"], f.advance_payload(STAGE_OPEN), COUNSEL_HEADERS)
    )
    return world


# ---------------------------------------------------------------------------
# Targeted variants
# ---------------------------------------------------------------------------
def bare_open_raise(api, **raise_overrides: Any) -> Dict[str, Any]:
    """
    A group with nothing but an open offering. Structuring a raise only requires the
    group's stage to be neither OPEN nor ABANDONED, so none of the composition or
    plan machinery is needed to exercise the offering and escrow arithmetic.
    """
    world = open_group(api)
    open_raise(api, world, **raise_overrides)
    return world


def add_investor_only_organizer(api, world: Dict[str, Any]) -> str:
    """
    Seat a sixth organizer holding INVESTOR_ONLY, whose subscore is computed and
    persisted like anyone else's but who is excluded from the management composite
    because the eligible population is every organizer other than an INVESTOR_ONLY.
    """
    organizer_id = seat_organizer(
        api,
        world["group_id"],
        {
            "full_name": "Roland Achebe",
            "role_on_board": "INVESTOR_ONLY",
            "is_independent": False,
            "affiliation_code": "INV_D",
            "banking_years": 2,
            "regulatory_experience_score": 40,
        },
    )
    world["o6"] = organizer_id
    return organizer_id


# Plan projections whose year-three loan concentration lands exactly on the 6500
# basis point trip point, so the concentration add-on is zero and the required
# leverage is the bare 800 basis point national tier.
BOUNDARY_PLAN_OVERRIDES: Dict[str, Any] = {
    "projected_loans_y3_cents": 27_950_000_000,
}


def boundary_plan_group(api, **group_overrides: Any) -> Dict[str, Any]:
    """
    The composition-met group carrying two draft plans with identical projections,
    ready for the two stress overlays that straddle the 800 basis point floor.
    """
    world = composition_met_group(api, **group_overrides)
    world["b1"] = add_business_plan(api, world, **BOUNDARY_PLAN_OVERRIDES)
    world["b2"] = add_business_plan(api, world, **BOUNDARY_PLAN_OVERRIDES)
    return world


def conditioned_group(
    api,
    conditions: List[Dict[str, Any]],
    **group_overrides: Any,
) -> Dict[str, Any]:
    """
    The conditionally-approved group with a list of conditions attached. Each entry
    names `key`, `condition_code`, `category`, `is_pre_opening_blocking` and
    optionally `authority` and `deadline_utc`.
    """
    world = conditionally_approved_group(api, **group_overrides)
    for spec in conditions:
        authority = spec.get("authority", AUTHORITY_CHARTERING)
        filing_id = world["f_ca"] if authority == AUTHORITY_CHARTERING else world["f_di"]
        world[spec["key"]] = add_condition(
            api,
            filing_id,
            spec["condition_code"],
            spec["category"],
            spec["is_pre_opening_blocking"],
            authority=authority,
            deadline_utc=spec.get("deadline_utc", "2026-12-01T00:00:00Z"),
        )
    return world


def satisfy_condition(
    api,
    condition_id: str,
    evidence_reference: str,
    authority: str = AUTHORITY_CHARTERING,
) -> Dict[str, Any]:
    """Walk one condition OPEN -> EVIDENCE_SUBMITTED -> SATISFIED."""
    submit_evidence(api, condition_id, evidence_reference)
    return adjudicate(api, condition_id, "SATISFIED", authority=authority)

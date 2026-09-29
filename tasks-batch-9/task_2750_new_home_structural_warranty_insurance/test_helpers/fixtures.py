"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, because each test runs against a freshly restarted server with
an empty database. Setup calls go through the lenient ``get_success_data``
validator so a broken precondition reports as a setup failure rather than as a
confusing assertion mismatch.

Identity discipline: a ``BuilderPrincipal`` acts with
``make_builder_principal_headers(builder["id"])`` and a ``Homeowner`` with
``make_homeowner_headers(homeowner["id"])`` — the shared TEST_USERS constants
are never used for an ownership-gated call.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import (
    BUILDER_PERIOD_INSTANT,
    CANONICAL_CLOSING_DATE,
    CANONICAL_CLOSING_INSTANT,
    CANONICAL_PURCHASE_PRICE_CENTS,
    INSURER_PERIOD_INSTANT,
)
from .test_users import (
    ADJUSTER_USER_ID,
    SECOND_ADJUSTER_USER_ID,
    TEST_USERS,
    make_builder_principal_headers,
    make_claims_adjuster_headers,
    make_homeowner_headers,
)

UW = TEST_USERS["underwriting_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]
SECOND_ADJUSTER = TEST_USERS["second_claims_adjuster_headers"]


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock forward and run the epoch sweep."""
    return get_success_data(
        api_client.set_clock(f.set_clock_payload(to_iso8601), COMPLIANCE)
    )


# --------------------------------------------------------------------------
# Tier 1: builder state progression
# --------------------------------------------------------------------------
def create_builder(**overrides) -> Dict[str, Any]:
    """A builder file in DRAFT with no score at all."""
    return get_success_data(
        api_client.create_builder(f.create_builder_payload(**overrides), UW)
    )


def create_submitted_builder(**overrides) -> Dict[str, Any]:
    """DRAFT -> SUBMITTED, attested by the builder principal itself."""
    builder = create_builder(**overrides)
    get_success_data(
        api_client.submit_builder(
            builder["id"], f.submit_builder_payload(),
            make_builder_principal_headers(builder["id"]),
        )
    )
    return read_builder(builder["id"])


def create_builder_under_review(**overrides) -> Dict[str, Any]:
    """DRAFT -> SUBMITTED -> UNDER_REVIEW, which is where the score is written."""
    builder = create_submitted_builder(**overrides)
    return get_success_data(
        api_client.take_builder_into_review(builder["id"], f.review_intake_payload(), UW)
    )


def create_approved_builder(**overrides) -> Dict[str, Any]:
    """Walk a builder file all the way to APPROVED. Defaults score 45.00 (class C)."""
    builder = create_builder_under_review(**overrides)
    get_success_data(
        api_client.create_underwriting_review(
            builder["id"], f.underwriting_review_payload("APPROVE"), UW
        )
    )
    return read_builder(builder["id"])


def suspend_builder(builder_id: str, reason: str = "Adverse loss experience"
                    ) -> Dict[str, Any]:
    return get_success_data(
        api_client.suspend_builder(
            builder_id, f.suspension_payload(reason=reason), COMPLIANCE
        )
    )


def declare_builder_default(builder_id: str,
                            reason: str = "Builder ceased operations"
                            ) -> Dict[str, Any]:
    return get_success_data(
        api_client.declare_builder_default(
            builder_id, f.default_declaration_payload(reason=reason), COMPLIANCE
        )
    )


# --------------------------------------------------------------------------
# Parties
# --------------------------------------------------------------------------
def create_homeowner(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_homeowner(f.create_homeowner_payload(**overrides), UW)
    )


def create_neutral(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_neutral(f.create_neutral_payload(**overrides), COMPLIANCE)
    )


# --------------------------------------------------------------------------
# Read helpers for setup chains
# --------------------------------------------------------------------------
def read_builder(builder_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_builder(builder_id, UW))


def read_policy(policy_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_policy(policy_id, UW))


def read_claim(claim_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_claim(claim_id, UW))


def read_coverage_term(coverage_term_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_coverage_term(coverage_term_id, UW))


def read_transfer(transfer_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_transfer(transfer_id, UW))


def read_neutral(neutral_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_neutral(neutral_id, COMPLIANCE))


def read_escalation_case(case_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_escalation_case(case_id, UW))


def read_loss_monitor(builder_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_loss_monitor(builder_id, UW))


def read_coverage_terms(policy_id: str) -> List[Dict[str, Any]]:
    return get_success_data(
        api_client.list_policy_coverage_terms(policy_id, UW, {"limit": 100})
    )


def find_term(terms: List[Dict[str, Any]], coverage_type: str,
              term_kind: str = "BASE") -> Dict[str, Any]:
    """Pick one coverage term out of a policy's term set."""
    for term in terms:
        if term["coverage_type"] == coverage_type and term["term_kind"] == term_kind:
            return term
    raise AssertionError(
        f"Setup failed: no {term_kind} {coverage_type} term among "
        f"{[(t['coverage_type'], t['term_kind']) for t in terms]}"
    )


def read_reserve_entries(claim_id: str, **filters) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"claim_id": claim_id, "limit": 100}
    params.update(filters)
    return get_success_data(api_client.list_reserve_entries(COMPLIANCE, params))


# --------------------------------------------------------------------------
# Tier 2: home enrollment progression
# --------------------------------------------------------------------------
def enroll_policy(builder_id: str, initial_owner_id: str, **overrides
                  ) -> Dict[str, Any]:
    """Enroll one closed home. Lands PENDING_ENROLLMENT / UNBILLED."""
    return get_success_data(
        api_client.create_policy(
            f.create_policy_payload(builder_id, initial_owner_id, **overrides),
            make_builder_principal_headers(builder_id),
        )
    )


def invoice_policy(policy_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_premium_invoice(
            policy_id, f.premium_invoice_payload(**overrides), UW
        )
    )


def pay_policy_premium(policy_id: str, builder_id: str, **overrides
                       ) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_premium_payment(
            policy_id, f.premium_payment_payload(**overrides),
            make_builder_principal_headers(builder_id),
        )
    )


def activate_policy(policy_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.activate_policy(policy_id, UW))


def enroll_paid_policy(builder_id: str, initial_owner_id: str, **overrides
                       ) -> Dict[str, Any]:
    """PENDING_ENROLLMENT on the coverage axis, PAID on the premium axis."""
    policy = enroll_policy(builder_id, initial_owner_id, **overrides)
    invoice_policy(policy["id"])
    pay_policy_premium(policy["id"], builder_id)
    return read_policy(policy["id"])


def enroll_active_policy(builder_id: str, initial_owner_id: str, **overrides
                         ) -> Dict[str, Any]:
    """Enroll, bill, pay and activate: ACTIVE / PAID."""
    policy = enroll_paid_policy(builder_id, initial_owner_id, **overrides)
    activate_policy(policy["id"])
    return read_policy(policy["id"])


def add_endorsement_term(policy_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_coverage_term(
            policy_id, f.create_coverage_term_payload(**overrides), UW
        )
    )


def setup_approved_builder_and_owner(clock: Optional[str] = CANONICAL_CLOSING_INSTANT,
                                     homeowner_overrides: Optional[Dict] = None,
                                     **builder_overrides) -> Dict[str, Any]:
    """An APPROVED builder, a registered buyer, and the clock at the closing
    instant. Returns the scenario dict every richer fixture extends."""
    builder = create_approved_builder(**builder_overrides)
    homeowner = create_homeowner(**(homeowner_overrides or {}))
    if clock is not None:
        set_clock(clock)
    return {
        "builder": builder,
        "builder_headers": make_builder_principal_headers(builder["id"]),
        "homeowner": homeowner,
        "owner_headers": make_homeowner_headers(homeowner["id"]),
    }


def setup_active_policy(purchase_price_cents: int = CANONICAL_PURCHASE_PRICE_CENTS,
                        closing_date: str = CANONICAL_CLOSING_DATE,
                        clock: Optional[str] = CANONICAL_CLOSING_INSTANT,
                        state_code: str = "TX",
                        builder_overrides: Optional[Dict] = None,
                        homeowner_overrides: Optional[Dict] = None,
                        **policy_overrides) -> Dict[str, Any]:
    """The canonical spine: approved builder + buyer + one ACTIVE, PAID home
    with its three BASE coverage terms.

    Returns a scenario dict with builder, builder_headers, homeowner,
    owner_headers, policy, terms and the three named terms.
    """
    scenario = setup_approved_builder_and_owner(
        clock=clock, homeowner_overrides=homeowner_overrides,
        **(builder_overrides or {})
    )
    policy = enroll_active_policy(
        scenario["builder"]["id"], scenario["homeowner"]["id"],
        purchase_price_cents=purchase_price_cents,
        closing_date=closing_date, state_code=state_code, **policy_overrides
    )
    terms = read_coverage_terms(policy["id"])
    scenario.update({
        "policy": policy,
        "terms": terms,
        "workmanship_term": find_term(terms, "WORKMANSHIP"),
        "systems_term": find_term(terms, "SYSTEMS"),
        "structural_term": find_term(terms, "STRUCTURAL"),
        "builder": read_builder(scenario["builder"]["id"]),
    })
    return scenario


def setup_paid_pending_policy(**kwargs) -> Dict[str, Any]:
    """Like setup_active_policy but stops one step short: PAID premium with the
    coverage axis still in PENDING_ENROLLMENT."""
    purchase_price_cents = kwargs.pop("purchase_price_cents",
                                      CANONICAL_PURCHASE_PRICE_CENTS)
    closing_date = kwargs.pop("closing_date", CANONICAL_CLOSING_DATE)
    clock = kwargs.pop("clock", CANONICAL_CLOSING_INSTANT)
    state_code = kwargs.pop("state_code", "TX")
    builder_overrides = kwargs.pop("builder_overrides", None)
    homeowner_overrides = kwargs.pop("homeowner_overrides", None)
    scenario = setup_approved_builder_and_owner(
        clock=clock, homeowner_overrides=homeowner_overrides,
        **(builder_overrides or {})
    )
    policy = enroll_paid_policy(
        scenario["builder"]["id"], scenario["homeowner"]["id"],
        purchase_price_cents=purchase_price_cents,
        closing_date=closing_date, state_code=state_code, **kwargs
    )
    scenario.update({"policy": policy, "terms": read_coverage_terms(policy["id"])})
    return scenario


# --------------------------------------------------------------------------
# Tier 3: claim lifecycle shortcuts
# --------------------------------------------------------------------------
def file_claim(policy_id: str, owner_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_claim(
            f.create_claim_payload(policy_id, **overrides),
            make_homeowner_headers(owner_id),
        )
    )


def investigate_claim(claim_id: str, substantiation_ratio: float = 1.00,
                      adjuster_user_id: str = ADJUSTER_USER_ID) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_investigation(
            claim_id, f.investigation_payload(substantiation_ratio),
            make_claims_adjuster_headers(adjuster_user_id),
        )
    )


def file_structural_assessment(claim_id: str,
                               adjuster_user_id: str = ADJUSTER_USER_ID,
                               **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_structural_assessment(
            claim_id, f.structural_assessment_payload(**overrides),
            make_claims_adjuster_headers(adjuster_user_id),
        )
    )


def route_claim(claim_id: str, adjuster_user_id: str = ADJUSTER_USER_ID,
                **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.route_claim_obligation(
            claim_id, f.obligation_routing_payload(**overrides),
            make_claims_adjuster_headers(adjuster_user_id),
        )
    )


def respond_to_obligation(claim_id: str, builder_id: str,
                          response: str = "ACCEPT_OBLIGATION",
                          **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_builder_response(
            claim_id, f.builder_response_payload(response, **overrides),
            make_builder_principal_headers(builder_id),
        )
    )


def complete_repair(claim_id: str, builder_id: str,
                    completion_date: str = "2026-10-01") -> Dict[str, Any]:
    return get_success_data(
        api_client.create_repair_completion(
            claim_id, f.repair_completion_payload(completion_date),
            make_builder_principal_headers(builder_id),
        )
    )


def adjudicate_claim(claim_id: str, outcome: str = "APPROVE",
                     adjuster_user_id: str = ADJUSTER_USER_ID,
                     **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_adjudication(
            claim_id, f.adjudication_payload(outcome, **overrides),
            make_claims_adjuster_headers(adjuster_user_id),
        )
    )


def authorize_reserve(claim_id: str, amount_cents: int,
                      entry_type: str = "INITIAL",
                      expected_claim_version: Optional[int] = None,
                      adjuster_user_id: str = ADJUSTER_USER_ID,
                      **overrides) -> Dict[str, Any]:
    """Authorise a case reserve. The claim's current version is read for the
    mandatory expected_claim_version when the caller does not supply one."""
    if expected_claim_version is None:
        expected_claim_version = read_claim(claim_id)["version"]
    return get_success_data(
        api_client.create_reserve_entry(
            claim_id,
            f.reserve_entry_payload(amount_cents, expected_claim_version,
                                    entry_type, **overrides),
            make_claims_adjuster_headers(adjuster_user_id),
        )
    )


def pay_claim(claim_id: str, amount_cents: int,
              adjuster_user_id: str = SECOND_ADJUSTER_USER_ID,
              **overrides) -> Dict[str, Any]:
    """Disburse indemnity. The default adjuster differs from the adjudicating
    adjuster so the segregation-of-duties rule is satisfied."""
    return get_success_data(
        api_client.create_payment(
            claim_id, f.payment_payload(amount_cents, **overrides),
            make_claims_adjuster_headers(adjuster_user_id),
        )
    )


def reverse_payment(claim_id: str, reserve_entry_id: str, **overrides
                    ) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_payment_reversal(
            claim_id, f.payment_reversal_payload(reserve_entry_id, **overrides),
            COMPLIANCE,
        )
    )


def latest_payment_entry_id(claim_id: str) -> str:
    """The reserve journal is the only channel through which a client can
    discover a system-created PAYMENT row that a reversal must name."""
    entries = read_reserve_entries(claim_id, entry_type="PAYMENT")
    assert entries, f"Setup failed: claim {claim_id} has no PAYMENT journal row"
    return entries[-1]["id"]


# --------------------------------------------------------------------------
# Tier 4: composite claim scenarios
# --------------------------------------------------------------------------
def setup_routed_claim(claimed_amount_cents: int = 1_000_000,
                       substantiation_ratio: float = 1.00,
                       coverage_type: str = "STRUCTURAL",
                       defect_category: str = "WATER_INTRUSION",
                       claim_instant: str = INSURER_PERIOD_INSTANT,
                       assessments: Optional[List[Dict[str, Any]]] = None,
                       route: bool = True,
                       scenario: Optional[Dict[str, Any]] = None,
                       claim_overrides: Optional[Dict[str, Any]] = None,
                       **policy_kwargs) -> Dict[str, Any]:
    """One ACTIVE home with a claim carried to the end of obligation routing.

    ``claim_instant`` decides the arm: an instant on or before the policy's
    builder_obligation_end_date routes into the builder-obligation arm, a later
    instant into the insurer-backed arm. ``assessments`` is a list of payload
    override dicts filed before routing so the structural designation is in
    place when the deductible schedule is selected.
    """
    scenario = scenario or setup_active_policy(**policy_kwargs)
    if claim_instant is not None:
        set_clock(claim_instant)
    claim = file_claim(
        scenario["policy"]["id"], scenario["homeowner"]["id"],
        coverage_type=coverage_type, defect_category=defect_category,
        claimed_amount_cents=claimed_amount_cents,
        **(claim_overrides or {})
    )
    investigate_claim(claim["id"], substantiation_ratio)
    for assessment in (assessments or []):
        file_structural_assessment(claim["id"], **assessment)
    if route:
        route_claim(claim["id"])
    scenario = dict(scenario)
    scenario["claim"] = read_claim(claim["id"])
    scenario["coverage_term"] = read_coverage_term(scenario["claim"]["coverage_term_id"])
    return scenario


def setup_builder_arm_claim(claimed_amount_cents: int = 1_750_000,
                            **kwargs) -> Dict[str, Any]:
    """A claim reported inside the builder-obligation period and routed into
    BUILDER_OBLIGATION_NOTICE."""
    kwargs.setdefault("claim_instant", BUILDER_PERIOD_INSTANT)
    return setup_routed_claim(claimed_amount_cents=claimed_amount_cents, **kwargs)


def setup_insurer_arm_claim(claimed_amount_cents: int = 1_750_000,
                            **kwargs) -> Dict[str, Any]:
    """A claim reported after the obligation boundary and routed into
    INSURER_ADJUDICATION, which puts the reserve up and recomputes the
    builder's loss-ratio figures."""
    kwargs.setdefault("claim_instant", INSURER_PERIOD_INSTANT)
    return setup_routed_claim(claimed_amount_cents=claimed_amount_cents, **kwargs)


def setup_approved_claim(claimed_amount_cents: int = 1_000_000,
                         adjuster_user_id: str = ADJUSTER_USER_ID,
                         **kwargs) -> Dict[str, Any]:
    """An insurer-arm claim adjudicated APPROVE, ready for disbursement."""
    scenario = setup_insurer_arm_claim(claimed_amount_cents=claimed_amount_cents,
                                       **kwargs)
    adjudicate_claim(scenario["claim"]["id"], "APPROVE",
                     adjuster_user_id=adjuster_user_id)
    scenario["claim"] = read_claim(scenario["claim"]["id"])
    scenario["adjudicated_by_user_id"] = adjuster_user_id
    return scenario


def setup_denied_claim(claimed_amount_cents: int = 900_000,
                       adjuster_user_id: str = ADJUSTER_USER_ID,
                       adjudication_note: str = "maintenance exclusion",
                       **kwargs) -> Dict[str, Any]:
    """An insurer-arm claim adjudicated DENY: the reserve is released, a denial
    date is stamped and escalation_deadline_date is set 60 days out."""
    scenario = setup_insurer_arm_claim(claimed_amount_cents=claimed_amount_cents,
                                       **kwargs)
    adjudicate_claim(scenario["claim"]["id"], "DENY",
                     adjuster_user_id=adjuster_user_id,
                     adjudication_note=adjudication_note)
    scenario["claim"] = read_claim(scenario["claim"]["id"])
    return scenario


# --------------------------------------------------------------------------
# Tier 5: the escalation ladder
# --------------------------------------------------------------------------
def book_escalation(claim_id: str, owner_id: str, neutral_id: str,
                    stage: str = "MEDIATION",
                    window_start: str = "2028-09-10T14:00:00Z",
                    window_end: str = "2028-09-10T16:00:00Z",
                    **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_escalation(
            claim_id,
            f.create_escalation_payload(neutral_id, stage, window_start,
                                        window_end, **overrides),
            make_homeowner_headers(owner_id),
        )
    )


def record_session_outcome(case_id: str, outcome: str = "IMPASSE",
                           adjuster_user_id: str = SECOND_ADJUSTER_USER_ID,
                           **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_session_outcome(
            case_id, f.session_outcome_payload(outcome, **overrides),
            make_claims_adjuster_headers(adjuster_user_id),
        )
    )


def issue_award(case_id: str, award_amount_cents: int,
                adjuster_user_id: str = ADJUSTER_USER_ID,
                **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_award(
            case_id, f.award_payload(award_amount_cents, **overrides),
            make_claims_adjuster_headers(adjuster_user_id),
        )
    )


def setup_mediation_case(neutral_overrides: Optional[Dict] = None,
                         window_start: str = "2028-09-10T14:00:00Z",
                         window_end: str = "2028-09-10T16:00:00Z",
                         **kwargs) -> Dict[str, Any]:
    """A denied claim escalated to MEDIATION on an ACTIVE panel neutral."""
    neutral = create_neutral(**(neutral_overrides or {}))
    scenario = setup_denied_claim(**kwargs)
    case = book_escalation(
        scenario["claim"]["id"], scenario["homeowner"]["id"], neutral["id"],
        stage="MEDIATION", window_start=window_start, window_end=window_end,
    )
    scenario["neutral"] = neutral
    scenario["mediation_case"] = case
    scenario["claim"] = read_claim(scenario["claim"]["id"])
    return scenario


def setup_arbitration_case(mediation_outcome_adjuster: str = SECOND_ADJUSTER_USER_ID,
                           impasse_instant: str = "2028-09-10T15:00:00Z",
                           arbitration_window_start: str = "2028-09-20T14:00:00Z",
                           arbitration_window_end: str = "2028-09-20T16:00:00Z",
                           **kwargs) -> Dict[str, Any]:
    """A mediation deadlocked at IMPASSE and the arbitration rung opened on the
    same neutral, ready for an award."""
    scenario = setup_mediation_case(**kwargs)
    set_clock(impasse_instant)
    record_session_outcome(scenario["mediation_case"]["id"], "IMPASSE",
                           adjuster_user_id=mediation_outcome_adjuster)
    arbitration_case = book_escalation(
        scenario["claim"]["id"], scenario["homeowner"]["id"],
        scenario["neutral"]["id"], stage="ARBITRATION",
        window_start=arbitration_window_start,
        window_end=arbitration_window_end,
        prior_case_id=scenario["mediation_case"]["id"],
    )
    scenario["arbitration_case"] = arbitration_case
    scenario["mediation_outcome_adjuster"] = mediation_outcome_adjuster
    scenario["claim"] = read_claim(scenario["claim"]["id"])
    return scenario


# --------------------------------------------------------------------------
# Transfers
# --------------------------------------------------------------------------
def request_transfer(policy_id: str, owner_id: str, new_owner_id: str,
                     expected_policy_version: Optional[int] = None,
                     transfer_date: str = "2028-09-05",
                     **overrides) -> Dict[str, Any]:
    if expected_policy_version is None:
        expected_policy_version = read_policy(policy_id)["version"]
    return get_success_data(
        api_client.create_transfer(
            policy_id,
            f.create_transfer_payload(new_owner_id, expected_policy_version,
                                      transfer_date, **overrides),
            make_homeowner_headers(owner_id),
        )
    )


def approve_transfer(transfer_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.decide_transfer(
            transfer_id, f.transfer_decision_payload("APPROVE", **overrides), UW
        )
    )


def record_transfer(transfer_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.record_transfer(transfer_id, UW))


def setup_approved_transfer(transfer_date: str = "2028-09-05",
                            clock: Optional[str] = INSURER_PERIOD_INSTANT,
                            scenario: Optional[Dict[str, Any]] = None,
                            **kwargs) -> Dict[str, Any]:
    """An ACTIVE home with a second registered buyer and a transfer request
    carried to APPROVED, one step short of recording."""
    scenario = scenario or setup_active_policy(**kwargs)
    if clock is not None:
        set_clock(clock)
    transferee = create_homeowner(full_name="Ben Calder",
                                  email="ben.calder@example.com")
    transfer = request_transfer(
        scenario["policy"]["id"], scenario["homeowner"]["id"], transferee["id"],
        transfer_date=transfer_date,
    )
    approve_transfer(transfer["id"])
    scenario = dict(scenario)
    scenario["transferee"] = transferee
    scenario["transfer"] = read_transfer(transfer["id"])
    scenario["policy"] = read_policy(scenario["policy"]["id"])
    return scenario


# --------------------------------------------------------------------------
# Limit-exhaustion staging
# --------------------------------------------------------------------------
def setup_limit_exhaustion_scenario(purchase_price_cents: int = 5_000_000,
                                    primary_claimed_cents: int = 6_000_000,
                                    sibling_claimed_cents: int = 600_000,
                                    with_pending_sibling_policy: bool = True,
                                    adjudicating_adjuster: str = ADJUSTER_USER_ID,
                                    **policy_kwargs) -> Dict[str, Any]:
    """Stage a coverage term that one disbursement can drive to zero capacity.

    One ACTIVE home whose STRUCTURAL BASE term is the full purchase price, an
    APPROVED claim whose net_payable_cents is capped at that whole limit, a
    sibling claim sitting in INSURER_ADJUDICATION on the same term, and
    optionally a second home of the same builder left in PENDING_ENROLLMENT so
    the enrollment_hold link of the cascade is observable.

    Returns the scenario dict plus primary_claim, sibling_claim,
    structural_term and pending_policy.
    """
    scenario = setup_active_policy(purchase_price_cents=purchase_price_cents,
                                   **policy_kwargs)
    pending_policy = None
    if with_pending_sibling_policy:
        pending_policy = enroll_policy(
            scenario["builder"]["id"], scenario["homeowner"]["id"],
            purchase_price_cents=purchase_price_cents,
            street_address="220 Cedar Ridge Ct",
        )
    set_clock(INSURER_PERIOD_INSTANT)
    primary = file_claim(scenario["policy"]["id"], scenario["homeowner"]["id"],
                         coverage_type="STRUCTURAL",
                         defect_category="STRUCTURAL_CRACKING",
                         claimed_amount_cents=primary_claimed_cents,
                         damage_description="Foundation displacement, first event")
    investigate_claim(primary["id"], 1.00)
    file_structural_assessment(primary["id"], affected_elements=["FOOTING"],
                               deflection_ratio=0.0500,
                               load_bearing_affected=True)
    route_claim(primary["id"])
    adjudicate_claim(primary["id"], "APPROVE",
                     adjuster_user_id=adjudicating_adjuster)
    sibling = file_claim(scenario["policy"]["id"], scenario["homeowner"]["id"],
                         coverage_type="STRUCTURAL",
                         defect_category="WATER_INTRUSION",
                         claimed_amount_cents=sibling_claimed_cents,
                         damage_description="Seepage at the slab edge, second event")
    investigate_claim(sibling["id"], 1.00)
    route_claim(sibling["id"])
    scenario = dict(scenario)
    scenario["primary_claim"] = read_claim(primary["id"])
    scenario["sibling_claim"] = read_claim(sibling["id"])
    scenario["structural_term"] = read_coverage_term(
        scenario["primary_claim"]["coverage_term_id"]
    )
    scenario["pending_policy"] = (read_policy(pending_policy["id"])
                                  if pending_policy else None)
    scenario["adjudicated_by_user_id"] = adjudicating_adjuster
    return scenario

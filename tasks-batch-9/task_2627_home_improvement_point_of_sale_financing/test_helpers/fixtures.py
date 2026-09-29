"""Scenario builders.

The harness restarts the server and empties the store before every test, so
nothing here may assume pre-existing rows: every builder drives the public
endpoints from an empty database.

Builders are layered.  Each layer takes an optional ``Scenario`` and extends it,
building the layers beneath it when none is supplied:

    program  ->  approved_merchant  ->  enrolled_merchant
             ->  activated_loan     ->  project_with_milestones  ->  settled_draw

Every builder uses :func:`get_success_data`, so a setup failure raises with the
server's own error id rather than a confusing downstream assertion.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .api_client import ApiClient
from .test_users import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    ANALYST_HEADERS,
    UNDERWRITER_HEADERS,
    consumer_headers,
    merchant_headers,
)


class Scenario:
    """A mutable bag of the rows one test needs, plus the headers to act as them."""

    def __init__(self) -> None:
        self.trade_rule: Dict[str, Any] = {}
        self.plan: Dict[str, Any] = {}
        self.merchant: Dict[str, Any] = {}
        self.license: Dict[str, Any] = {}
        self.enrollment: Dict[str, Any] = {}
        self.consumer: Dict[str, Any] = {}
        self.application: Dict[str, Any] = {}
        self.loan: Dict[str, Any] = {}
        self.project: Dict[str, Any] = {}
        self.milestones: List[Dict[str, Any]] = []
        self.draws: List[Dict[str, Any]] = []

    # Convenience accessors -----------------------------------------

    @property
    def merchant_id(self) -> str:
        return self.merchant["id"]

    @property
    def consumer_id(self) -> str:
        return self.consumer["id"]

    @property
    def plan_id(self) -> str:
        return self.plan["id"]

    @property
    def application_id(self) -> str:
        return self.application["id"]

    @property
    def loan_id(self) -> str:
        return self.loan["id"]

    @property
    def project_id(self) -> str:
        return self.project["id"]

    @property
    def as_merchant(self) -> Dict[str, str]:
        return merchant_headers(self.merchant["id"])

    @property
    def as_consumer(self) -> Dict[str, str]:
        return consumer_headers(self.consumer["id"])

    def milestone_id(self, index: int = 0) -> str:
        return self.milestones[index]["id"]

    @property
    def draw(self) -> Dict[str, Any]:
        return self.draws[-1]


# ─── Clock and sweep ──────────────────────────────────

def set_clock(api: ApiClient, instant: str) -> Dict[str, Any]:
    """Move the logical clock to `instant` as a `ServicingAgent`."""
    return get_success_data(api.set_clock(F.clock_payload(instant), AGENT_HEADERS))


def run_sweep(api: ApiClient) -> Dict[str, Any]:
    """Run the operations checkpoint and return its seven counts."""
    return get_success_data(api.run_expiration_sweep({}, AGENT_HEADERS))


# ─── Single-step builders ─────────────────────────────

def create_trade_rule(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_trade_rule(F.trade_rule_payload(**overrides), ADMIN_HEADERS)
    )


def create_promotion_plan(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_promotion_plan(F.promotion_plan_payload(**overrides), ADMIN_HEADERS)
    )


def register_merchant(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_merchant(F.merchant_payload(**overrides), ADMIN_HEADERS)
    )


def file_license(api: ApiClient, merchant_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.file_license(merchant_id, F.license_payload(**overrides), ADMIN_HEADERS)
    )


def verify_license(api: ApiClient, merchant_id: str, license_id: str,
                   outcome: str = "VERIFIED") -> Dict[str, Any]:
    return get_success_data(
        api.verify_license(
            merchant_id,
            license_id,
            F.license_verification_payload(outcome),
            UNDERWRITER_HEADERS,
        )
    )


def submit_enrollment(api: ApiClient, merchant_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.submit_enrollment(
            merchant_id, F.enrollment_submission_payload(**overrides), ADMIN_HEADERS
        )
    )


def decide_enrollment(api: ApiClient, merchant_id: str, decision: str = "APPROVE",
                     headers: Optional[Dict] = None, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.decide_enrollment(
            merchant_id,
            F.enrollment_decision_payload(decision, **overrides),
            headers or UNDERWRITER_HEADERS,
        )
    )


def program_action(api: ApiClient, merchant_id: str, action: str,
                   **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.program_action(merchant_id, F.program_action_payload(action, **overrides),
                           ADMIN_HEADERS)
    )


def enroll_in_promotion(api: ApiClient, merchant_id: str, plan_id: str,
                        **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_promotion_enrollment(
            merchant_id,
            F.promotion_enrollment_payload(plan_id, **overrides),
            UNDERWRITER_HEADERS,
        )
    )


def register_consumer(api: ApiClient, merchant_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_consumer(F.consumer_payload(**overrides), merchant_headers(merchant_id))
    )


def raise_fraud_alert(api: ApiClient, merchant_id: str, alert_type: str = "PHANTOM_PROJECT",
                      severity_weight: int = 35, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_fraud_alert(
            merchant_id,
            F.fraud_alert_payload(alert_type, severity_weight, **overrides),
            ANALYST_HEADERS,
        )
    )


def merchant_version(api: ApiClient, merchant_id: str) -> int:
    """The merchant's current `version`, read fresh for an OCC-guarded write."""
    return get_success_data(api.get_merchant(merchant_id, ADMIN_HEADERS))["version"]


def loan_version(api: ApiClient, loan_id: str) -> int:
    """The loan account's current `version`, read fresh for a draw request."""
    return get_success_data(api.get_loan_account(loan_id, ADMIN_HEADERS))["version"]


def read_merchant(api: ApiClient, merchant_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_merchant(merchant_id, ADMIN_HEADERS))


def read_loan(api: ApiClient, loan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_loan_account(loan_id, ADMIN_HEADERS))


def read_project(api: ApiClient, project_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_project(project_id, ADMIN_HEADERS))


def read_draw(api: ApiClient, draw_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_funding_draw(draw_id, ADMIN_HEADERS))


def read_application(api: ApiClient, application_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_credit_application(application_id, ADMIN_HEADERS))


def read_dispute(api: ApiClient, case_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_dispute_case(case_id, ADMIN_HEADERS))


def read_milestones(api: ApiClient, project_id: str) -> List[Dict[str, Any]]:
    return get_success_data(api.list_milestones(project_id, ADMIN_HEADERS))


# ─── Layered scenario builders ────────────────────────

def program(api: ApiClient, trade_rule: Optional[Dict[str, Any]] = None,
            plan: Optional[Dict[str, Any]] = None) -> Scenario:
    """Lay down the two reference tables: one ROOFING trade rule and one plan."""
    scenario = Scenario()
    scenario.trade_rule = create_trade_rule(api, **(trade_rule or {}))
    scenario.plan = create_promotion_plan(api, **(plan or {}))
    return scenario


def approved_merchant(api: ApiClient, scenario: Optional[Scenario] = None,
                      merchant: Optional[Dict[str, Any]] = None,
                      license_: Optional[Dict[str, Any]] = None,
                      approve: bool = True, **program_kwargs: Any) -> Scenario:
    """Register a merchant, file and verify its licence, then take it to `APPROVED`."""
    scenario = scenario or program(api, **program_kwargs)
    scenario.merchant = register_merchant(api, **(merchant or {}))
    scenario.license = file_license(api, scenario.merchant_id, **(license_ or {}))
    verify_license(api, scenario.merchant_id, scenario.license["id"])
    submit_enrollment(api, scenario.merchant_id)
    if approve:
        scenario.merchant = decide_enrollment(api, scenario.merchant_id, "APPROVE")
    return scenario


def enrolled_merchant(api: ApiClient, scenario: Optional[Scenario] = None,
                      enrollment: Optional[Dict[str, Any]] = None,
                      **merchant_kwargs: Any) -> Scenario:
    """Extend an approved merchant with an `ACTIVE` promotion enrollment."""
    scenario = scenario or approved_merchant(api, **merchant_kwargs)
    scenario.enrollment = enroll_in_promotion(
        api, scenario.merchant_id, scenario.plan_id, **(enrollment or {})
    )
    return scenario


def application(api: ApiClient, scenario: Optional[Scenario] = None,
                consumer: Optional[Dict[str, Any]] = None,
                ticket_cents: Optional[int] = None,
                **enrollment_kwargs: Any) -> Scenario:
    """Register a homeowner and file the point-of-sale application for an instant decision."""
    scenario = scenario or enrolled_merchant(api, **enrollment_kwargs)
    scenario.consumer = register_consumer(api, scenario.merchant_id, **(consumer or {}))
    overrides: Dict[str, Any] = {}
    if ticket_cents is not None:
        overrides["project_amount_cents"] = ticket_cents
    scenario.application = get_success_data(
        api.create_credit_application(
            F.credit_application_payload(
                scenario.merchant_id, scenario.consumer_id, scenario.plan_id, **overrides
            ),
            scenario.as_merchant,
        )
    )
    return scenario


def disclosed_application(api: ApiClient, scenario: Optional[Scenario] = None,
                          template_version: Optional[str] = None,
                          acknowledge: bool = True,
                          **application_kwargs: Any) -> Scenario:
    """Deliver the disclosure and, unless told otherwise, acknowledge it."""
    scenario = scenario or application(api, **application_kwargs)
    overrides: Dict[str, Any] = {}
    if template_version is not None:
        overrides["disclosure_template_version"] = template_version
    scenario.application = get_success_data(
        api.deliver_disclosure(
            scenario.application_id,
            F.disclosure_delivery_payload(**overrides),
            scenario.as_merchant,
        )
    )
    if acknowledge:
        scenario.application = get_success_data(
            api.acknowledge_disclosure(
                scenario.application_id,
                F.disclosure_acknowledgement_payload(),
                scenario.as_consumer,
            )
        )
    return scenario


def activated_loan(api: ApiClient, scenario: Optional[Scenario] = None,
                   accept_counter_offer: Optional[bool] = None,
                   **disclosure_kwargs: Any) -> Scenario:
    """Accept the offer, originating the loan account."""
    scenario = scenario or disclosed_application(api, **disclosure_kwargs)
    overrides: Dict[str, Any] = {}
    if accept_counter_offer is not None:
        overrides["accept_counter_offer"] = accept_counter_offer
    scenario.application = get_success_data(
        api.accept_offer(
            scenario.application_id, F.acceptance_payload(**overrides), scenario.as_consumer
        )
    )
    accounts = get_success_data(
        api.list_loan_accounts(ADMIN_HEADERS, {"application_id": scenario.application_id})
    )
    assert accounts, "Acceptance did not originate a loan account"
    scenario.loan = accounts[0]
    return scenario


def project(api: ApiClient, scenario: Optional[Scenario] = None,
            contract_amount_cents: Optional[int] = None,
            scope_description: Optional[str] = None,
            **loan_kwargs: Any) -> Scenario:
    """Open the contracted project against the activated application."""
    scenario = scenario or activated_loan(api, **loan_kwargs)
    overrides: Dict[str, Any] = {}
    if contract_amount_cents is not None:
        overrides["contract_amount_cents"] = contract_amount_cents
    if scope_description is not None:
        overrides["scope_description"] = scope_description
    scenario.project = get_success_data(
        api.create_project(
            F.project_payload(scenario.application_id, **overrides), scenario.as_merchant
        )
    )
    return scenario


def add_milestones(api: ApiClient, scenario: Scenario,
                   releases: Sequence[int] = (3000, 4000, 3000),
                   requires_consumer_signoff: Optional[bool] = None) -> Scenario:
    """Lay out milestones carrying the given release shares, in sequence order."""
    names = [m["name"] for m in C.CANONICAL_MILESTONES]
    for index, share in enumerate(releases):
        overrides: Dict[str, Any] = {}
        if requires_consumer_signoff is not None:
            overrides["requires_consumer_signoff"] = requires_consumer_signoff
        payload = F.milestone_payload(
            sequence_no=index + 1,
            name=names[index] if index < len(names) else f"Stage {index + 1}",
            release_pct_bps=share,
            **overrides,
        )
        scenario.milestones.append(
            get_success_data(
                api.create_milestone(scenario.project_id, payload, scenario.as_merchant)
            )
        )
    return scenario


def claim_milestone(api: ApiClient, scenario: Scenario, index: int = 0,
                    evidence_ref: Optional[str] = None) -> Dict[str, Any]:
    """Claim one milestone as its merchant and return the updated row."""
    overrides = {} if evidence_ref is None else {"evidence_ref": evidence_ref}
    updated = get_success_data(
        api.claim_milestone(
            scenario.project_id,
            scenario.milestone_id(index),
            F.claim_payload(**overrides),
            scenario.as_merchant,
        )
    )
    scenario.milestones[index] = updated
    return updated


def verify_milestone(api: ApiClient, scenario: Scenario, index: int = 0,
                     outcome: str = "VERIFY",
                     headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Record a verification decision on one milestone and return the updated row."""
    updated = get_success_data(
        api.verify_milestone(
            scenario.project_id,
            scenario.milestone_id(index),
            F.milestone_verification_payload(outcome),
            headers or scenario.as_consumer,
        )
    )
    scenario.milestones[index] = updated
    return updated


def project_with_milestones(api: ApiClient, scenario: Optional[Scenario] = None,
                            releases: Sequence[int] = (3000, 4000, 3000),
                            verify: Sequence[int] = (0,),
                            requires_consumer_signoff: Optional[bool] = None,
                            **project_kwargs: Any) -> Scenario:
    """Open a project, lay out its milestones and carry the named ones to `VERIFIED`."""
    scenario = scenario or project(api, **project_kwargs)
    add_milestones(api, scenario, releases, requires_consumer_signoff)
    for index in verify:
        claim_milestone(api, scenario, index)
        verify_milestone(api, scenario, index)
    scenario.project = read_project(api, scenario.project_id)
    return scenario


def request_draw(api: ApiClient, scenario: Scenario, amount_cents: int,
                 milestone_index: int = 0, settlement_speed: str = "STANDARD_3DAY",
                 expected_version: Optional[int] = None) -> Dict[str, Any]:
    """Request a draw against a verified milestone, reading the loan version fresh."""
    version = (
        expected_version
        if expected_version is not None
        else loan_version(api, scenario.loan_id)
    )
    draw = get_success_data(
        api.create_funding_draw(
            F.funding_draw_payload(
                scenario.loan_id,
                scenario.milestone_id(milestone_index),
                amount_cents,
                version,
                settlement_speed,
            ),
            scenario.as_merchant,
        )
    )
    scenario.draws.append(draw)
    return draw


def settle_draw(api: ApiClient, scenario: Scenario, draw_id: Optional[str] = None,
                headers: Optional[Dict] = None) -> Dict[str, Any]:
    """Settle a requested draw as a `ServicingAgent`."""
    target = draw_id or scenario.draws[-1]["id"]
    settled = get_success_data(
        api.settle_funding_draw(
            target, F.settlement_payload("SETTLE"), headers or AGENT_HEADERS
        )
    )
    for index, draw in enumerate(scenario.draws):
        if draw["id"] == target:
            scenario.draws[index] = settled
    return settled


def settled_draw(api: ApiClient, scenario: Optional[Scenario] = None,
                 amount_cents: int = 1000050, milestone_index: int = 0,
                 settlement_speed: str = "STANDARD_3DAY",
                 **project_kwargs: Any) -> Scenario:
    """Carry the canonical chain all the way to one settled draw."""
    scenario = scenario or project_with_milestones(api, **project_kwargs)
    request_draw(api, scenario, amount_cents, milestone_index, settlement_speed)
    settle_draw(api, scenario)
    scenario.project = read_project(api, scenario.project_id)
    scenario.loan = read_loan(api, scenario.loan_id)
    scenario.merchant = read_merchant(api, scenario.merchant_id)
    return scenario


def file_dispute(api: ApiClient, scenario: Scenario, claimed_cents: int,
                 **overrides: Any) -> Dict[str, Any]:
    """File a consumer dispute over incomplete work on the scenario's project."""
    return get_success_data(
        api.create_dispute_case(
            F.dispute_case_payload(
                scenario.loan_id, scenario.project_id, claimed_cents, **overrides
            ),
            scenario.as_consumer,
        )
    )

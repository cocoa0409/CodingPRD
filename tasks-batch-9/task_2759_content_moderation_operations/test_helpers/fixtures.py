"""Composite state builders and pytest fixtures.

The harness restarts the server before every individual test, so each test
begins against an empty database and must build every precondition through the
API itself. Almost every claim in this API needs the same spine — a supervised
account, an ACTIVE policy version beneath a category, a queue that serves that
category and language, a certified reviewer, an ingested content item — so that
spine is built once here and shared by name.

Setup steps use the lenient success reader deliberately: a fixture's job is to
reach a state, not to assert the contract. Only the test body asserts.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient, api_client
from .assertions import add_hours, add_minutes, normalize_instant
from .constants import CLOCK_T0
from .test_users import (
    ADMIN_HEADERS,
    LEGAL_HEADERS,
    POLICY_ACTIVATOR_HEADERS,
    POLICY_AUTHOR_HEADERS,
    make_account_holder_headers,
    make_qa_auditor_headers,
    make_reviewer_headers,
)


# ---------------------------------------------------------------------------
# The world builder
# ---------------------------------------------------------------------------


class ModerationWorld:
    """A thin scripting layer over the API for building test preconditions."""

    def __init__(self, client: Optional[ApiClient] = None) -> None:
        self.client = client or api_client
        self.now: str = CLOCK_T0

    # -- Clock ------------------------------------------------------------

    def set_clock(self, instant: str) -> str:
        """Move the logical clock and remember where it now stands."""
        data = get_success_data(self.client.set_clock(instant, headers=ADMIN_HEADERS))
        self.now = normalize_instant(data["current_utc"])
        return self.now

    def advance_minutes(self, minutes: int) -> str:
        """Move the clock forward by whole minutes from where it stands."""
        return self.set_clock(add_minutes(self.now, minutes))

    def advance_hours(self, hours: int) -> str:
        """Move the clock forward by whole hours from where it stands."""
        return self.set_clock(add_hours(self.now, hours))

    # -- Accounts and content ---------------------------------------------

    def create_account(self, **overrides: Any) -> Dict[str, Any]:
        """Register a supervised author."""
        payload = factories.create_account_payload(**overrides)
        return get_success_data(self.client.create_account(payload, headers=ADMIN_HEADERS))

    def get_account(self, account_id: str) -> Dict[str, Any]:
        return get_success_data(self.client.get_account(account_id, headers=ADMIN_HEADERS))

    def create_content(self, account_id: str, **overrides: Any) -> Dict[str, Any]:
        """Ingest a piece of content authored by the given account."""
        payload = factories.create_content_item_payload(account_id, **overrides)
        return get_success_data(self.client.create_content_item(payload, headers=ADMIN_HEADERS))

    def get_content(self, content_item_id: str) -> Dict[str, Any]:
        return get_success_data(self.client.get_content_item(content_item_id, headers=ADMIN_HEADERS))

    # -- Taxonomy and policy versions -------------------------------------

    def create_category(self, **overrides: Any) -> Dict[str, Any]:
        """Add a taxonomy node."""
        payload = factories.create_policy_category_payload(**overrides)
        return get_success_data(
            self.client.create_policy_category(payload, headers=POLICY_AUTHOR_HEADERS)
        )

    def get_category(self, category_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_policy_category(category_id, headers=POLICY_AUTHOR_HEADERS)
        )

    def create_draft_version(self, category_id: str, **overrides: Any) -> Dict[str, Any]:
        """Write a draft enforcement rule beneath a category."""
        payload = factories.create_policy_version_payload(category_id, **overrides)
        return get_success_data(
            self.client.create_policy_version(payload, headers=POLICY_AUTHOR_HEADERS)
        )

    def back_test(self, policy_version_id: str) -> Dict[str, Any]:
        """Replay the draft over history so it becomes activatable."""
        return get_success_data(
            self.client.back_test_policy_version(policy_version_id, headers=POLICY_AUTHOR_HEADERS)
        )

    def revise(self, policy_version_id: str, **overrides: Any) -> Dict[str, Any]:
        """Send a back-tested draft back for rework."""
        payload = factories.revise_policy_version_payload(**overrides)
        return get_success_data(
            self.client.revise_policy_version(
                policy_version_id, payload, headers=POLICY_AUTHOR_HEADERS
            )
        )

    def activate(self, policy_version_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Activate a back-tested version under a manager who did not draft it."""
        return get_success_data(
            self.client.activate_policy_version(
                policy_version_id, headers=headers or POLICY_ACTIVATOR_HEADERS
            )
        )

    def create_active_version(self, category_id: str, **overrides: Any) -> Dict[str, Any]:
        """Draft, back-test and activate one version in a single step."""
        draft = self.create_draft_version(category_id, **overrides)
        self.back_test(draft["id"])
        return self.activate(draft["id"])

    def get_policy_version(self, policy_version_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_policy_version(policy_version_id, headers=POLICY_AUTHOR_HEADERS)
        )

    # -- Queues -----------------------------------------------------------

    def create_queue(self, category_id: str, **overrides: Any) -> Dict[str, Any]:
        """Open a queue serving one category in one language."""
        payload = factories.create_review_queue_payload(category_id, **overrides)
        return get_success_data(self.client.create_review_queue(payload, headers=ADMIN_HEADERS))

    def get_queue(self, queue_id: str) -> Dict[str, Any]:
        return get_success_data(self.client.get_review_queue(queue_id, headers=ADMIN_HEADERS))

    # -- Reviewers --------------------------------------------------------

    def create_reviewer(self, **overrides: Any) -> Dict[str, Any]:
        """Onboard a reviewer."""
        payload = factories.create_reviewer_payload(**overrides)
        return get_success_data(self.client.create_reviewer(payload, headers=ADMIN_HEADERS))

    def get_reviewer(self, reviewer_id: str) -> Dict[str, Any]:
        return get_success_data(self.client.get_reviewer(reviewer_id, headers=ADMIN_HEADERS))

    def certify(
        self,
        reviewer_id: str,
        policy_version_id: str,
        expected_reviewer_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Grant a reviewer a certification, reading the current version first."""
        if expected_reviewer_version is None:
            expected_reviewer_version = self.get_reviewer(reviewer_id)["version"]
        payload = factories.certification_payload(policy_version_id, expected_reviewer_version)
        return get_success_data(
            self.client.grant_certification(reviewer_id, payload, headers=POLICY_AUTHOR_HEADERS)
        )

    def start_wellness_break(self, reviewer_id: str, **overrides: Any) -> Dict[str, Any]:
        """Place a reviewer on a protective break."""
        payload = factories.wellness_break_payload(**overrides)
        return get_success_data(
            self.client.start_wellness_break(reviewer_id, payload, headers=ADMIN_HEADERS)
        )

    def return_to_duty(self, reviewer_id: str) -> Dict[str, Any]:
        """End a reviewer's protective break."""
        return get_success_data(self.client.return_to_duty(reviewer_id, headers=ADMIN_HEADERS))

    # -- Detection signals and cases --------------------------------------

    def submit_signal(self, content_item_id: str, **overrides: Any) -> Dict[str, Any]:
        """Submit a classifier score against a content item."""
        payload = factories.create_detection_signal_payload(content_item_id, **overrides)
        return get_success_data(self.client.create_detection_signal(payload, headers=ADMIN_HEADERS))

    def get_signal(self, signal_id: str) -> Dict[str, Any]:
        return get_success_data(self.client.get_detection_signal(signal_id, headers=ADMIN_HEADERS))

    def open_manual_case(self, content_item_id: str, **overrides: Any) -> Dict[str, Any]:
        """Hand-open a manual-report case."""
        payload = factories.create_moderation_case_payload(content_item_id, **overrides)
        return get_success_data(self.client.create_moderation_case(payload, headers=ADMIN_HEADERS))

    def open_legal_case(self, content_item_id: str, **overrides: Any) -> Dict[str, Any]:
        """Hand-open a legal-request case, which is reserved to legal counsel."""
        payload = factories.legal_case_payload(content_item_id, **overrides)
        return get_success_data(self.client.create_moderation_case(payload, headers=LEGAL_HEADERS))

    def get_case(self, case_id: str) -> Dict[str, Any]:
        return get_success_data(self.client.get_moderation_case(case_id, headers=ADMIN_HEADERS))

    def assign(
        self,
        case_id: str,
        target_reviewer_id: Optional[str] = None,
        expected_case_version: Optional[int] = None,
        exclude_reviewer_ids: Optional[List[str]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Assign a case, reading its current version first when not supplied."""
        if expected_case_version is None:
            expected_case_version = self.get_case(case_id)["version"]
        payload = factories.assign_case_payload(
            expected_case_version,
            target_reviewer_id=target_reviewer_id,
            exclude_reviewer_ids=exclude_reviewer_ids,
        )
        return get_success_data(
            self.client.assign_case(case_id, payload, headers=headers or ADMIN_HEADERS)
        )

    def decide(self, case_id: str, reviewer_id: str, **overrides: Any) -> Dict[str, Any]:
        """Record a reviewer's decision on a case they hold."""
        payload = factories.decide_case_payload(**overrides)
        return get_success_data(
            self.client.decide_case(case_id, payload, headers=make_reviewer_headers(reviewer_id))
        )

    def decide_as_legal(self, case_id: str, **overrides: Any) -> Dict[str, Any]:
        """Record a legal decision on an escalated legal-request case."""
        payload = factories.decide_case_payload(**overrides)
        return get_success_data(self.client.decide_case(case_id, payload, headers=LEGAL_HEADERS))

    def escalate(self, case_id: str, reviewer_id: str, **overrides: Any) -> Dict[str, Any]:
        """Escalate a case out of the holding reviewer's hands."""
        payload = factories.escalate_case_payload(**overrides)
        return get_success_data(
            self.client.escalate_case(case_id, payload, headers=make_reviewer_headers(reviewer_id))
        )

    def return_case(self, case_id: str, **overrides: Any) -> Dict[str, Any]:
        """Return an escalated case to its queue."""
        payload = factories.return_case_payload(**overrides)
        return get_success_data(
            self.client.return_case_to_queue(case_id, payload, headers=ADMIN_HEADERS)
        )

    # -- Appeals ----------------------------------------------------------

    def file_appeal(self, case_id: str, account_id: str, **overrides: Any) -> Dict[str, Any]:
        """File an appeal as the author of the appealed content."""
        payload = factories.create_appeal_payload(case_id, **overrides)
        return get_success_data(
            self.client.create_appeal(payload, headers=make_account_holder_headers(account_id))
        )

    def route_appeal(
        self,
        appeal_id: str,
        auditor_reviewer_id: str,
        target_reviewer_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Route a submitted appeal to an independent reviewer."""
        payload = factories.route_appeal_payload(target_reviewer_id=target_reviewer_id)
        return get_success_data(
            self.client.assign_appeal_reviewer(
                appeal_id, payload, headers=make_qa_auditor_headers(auditor_reviewer_id)
            )
        )

    def resolve_appeal(self, appeal_id: str, reviewer_id: str, **overrides: Any) -> Dict[str, Any]:
        """Resolve an appeal as its independent reviewer."""
        payload = factories.resolve_appeal_payload(**overrides)
        return get_success_data(
            self.client.resolve_appeal(
                appeal_id, payload, headers=make_reviewer_headers(reviewer_id)
            )
        )

    def get_appeal(self, appeal_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        return get_success_data(self.client.get_appeal(appeal_id, headers=headers or ADMIN_HEADERS))

    # -- Audit samples ----------------------------------------------------

    def draw_sample(self, case_id: str, auditor_reviewer_id: str, **overrides: Any) -> Dict[str, Any]:
        """Draw a quality sample over a decided case."""
        payload = factories.create_audit_sample_payload(case_id, **overrides)
        return get_success_data(
            self.client.create_audit_sample(
                payload, headers=make_qa_auditor_headers(auditor_reviewer_id)
            )
        )

    def audit(self, sample_id: str, auditor_reviewer_id: str, **overrides: Any) -> Dict[str, Any]:
        """Record a verdict on a drawn sample."""
        payload = factories.audit_verdict_payload(**overrides)
        return get_success_data(
            self.client.record_audit_verdict(
                sample_id, payload, headers=make_qa_auditor_headers(auditor_reviewer_id)
            )
        )

    def dispute(self, sample_id: str, reviewer_id: str, **overrides: Any) -> Dict[str, Any]:
        """Contest a verdict as the reviewer who decided the underlying case."""
        payload = factories.audit_dispute_payload(**overrides)
        return get_success_data(
            self.client.dispute_audit_sample(
                sample_id, payload, headers=make_reviewer_headers(reviewer_id)
            )
        )

    def get_sample(self, sample_id: str) -> Dict[str, Any]:
        return get_success_data(self.client.get_audit_sample(sample_id, headers=ADMIN_HEADERS))

    # -- Transparency reports ---------------------------------------------

    def create_report(self, **overrides: Any) -> Dict[str, Any]:
        """Open a reporting period."""
        payload = factories.create_transparency_report_payload(**overrides)
        return get_success_data(
            self.client.create_transparency_report(payload, headers=ADMIN_HEADERS)
        )

    def compute_report(self, report_id: str, **overrides: Any) -> Dict[str, Any]:
        """Compute a report under one variant."""
        payload = factories.compute_report_payload(**overrides)
        return get_success_data(
            self.client.compute_transparency_report(report_id, payload, headers=ADMIN_HEADERS)
        )

    def publish_report(self, report_id: str) -> Dict[str, Any]:
        """Publish a restated report."""
        return get_success_data(
            self.client.publish_transparency_report(report_id, headers=ADMIN_HEADERS)
        )

    def get_report(self, report_id: str) -> Dict[str, Any]:
        return get_success_data(
            self.client.get_transparency_report(report_id, headers=ADMIN_HEADERS)
        )


# ---------------------------------------------------------------------------
# Composite state records
# ---------------------------------------------------------------------------


@dataclass
class PolicyBaseline:
    """A supervised account, an ACTIVE policy version and a queue serving it."""

    world: ModerationWorld
    account: Dict[str, Any]
    category: Dict[str, Any]
    version: Dict[str, Any]
    queue: Dict[str, Any]

    @property
    def account_id(self) -> str:
        return self.account["id"]

    @property
    def category_id(self) -> str:
        return self.category["id"]

    @property
    def version_id(self) -> str:
        return self.version["id"]

    @property
    def queue_id(self) -> str:
        return self.queue["id"]

    @property
    def category_code(self) -> str:
        return self.category["code"]

    @property
    def now(self) -> str:
        return self.world.now


@dataclass
class WorkforceBaseline(PolicyBaseline):
    """A policy baseline plus a certified frontline, senior and QA reviewer."""

    frontline: Dict[str, Any] = field(default_factory=dict)
    senior: Dict[str, Any] = field(default_factory=dict)
    auditor: Dict[str, Any] = field(default_factory=dict)

    @property
    def frontline_id(self) -> str:
        return self.frontline["id"]

    @property
    def senior_id(self) -> str:
        return self.senior["id"]

    @property
    def auditor_id(self) -> str:
        return self.auditor["id"]


@dataclass
class CaseScenario:
    """A workforce baseline plus one content item and the case raised on it."""

    base: WorkforceBaseline
    content: Dict[str, Any]
    case: Dict[str, Any]
    signal: Optional[Dict[str, Any]] = None

    @property
    def world(self) -> ModerationWorld:
        return self.base.world

    @property
    def content_id(self) -> str:
        return self.content["id"]

    @property
    def case_id(self) -> str:
        return self.case["id"]

    def refreshed_case(self) -> Dict[str, Any]:
        """Re-read the case so a test sees the server's current row."""
        return self.base.world.get_case(self.case["id"])


@dataclass
class AppealScenario:
    """A decided case with an appeal filed against it."""

    case_scenario: CaseScenario
    appeal: Dict[str, Any]

    @property
    def appeal_id(self) -> str:
        return self.appeal["id"]

    @property
    def world(self) -> ModerationWorld:
        return self.case_scenario.base.world


@dataclass
class AuditScenario:
    """A decided case with a quality sample drawn over it."""

    case_scenario: CaseScenario
    sample: Dict[str, Any]

    @property
    def sample_id(self) -> str:
        return self.sample["id"]

    @property
    def world(self) -> ModerationWorld:
        return self.case_scenario.base.world


# ---------------------------------------------------------------------------
# Tier 1: the policy spine
# ---------------------------------------------------------------------------


def build_policy_baseline(
    world: ModerationWorld,
    clock: str = CLOCK_T0,
    account_overrides: Optional[Dict[str, Any]] = None,
    category_overrides: Optional[Dict[str, Any]] = None,
    version_overrides: Optional[Dict[str, Any]] = None,
    queue_overrides: Optional[Dict[str, Any]] = None,
) -> PolicyBaseline:
    """Bring the clock, one account, one ACTIVE policy version and one queue into being."""
    world.set_clock(clock)
    account = world.create_account(**(account_overrides or {}))
    category = world.create_category(**(category_overrides or {}))
    version = world.create_active_version(category["id"], **(version_overrides or {}))
    queue = world.create_queue(
        category["id"],
        specialty=category["specialty"],
        **(queue_overrides or {}),
    )
    return PolicyBaseline(
        world=world,
        account=account,
        category=world.get_category(category["id"]),
        version=version,
        queue=queue,
    )


# ---------------------------------------------------------------------------
# Tier 2: the workforce
# ---------------------------------------------------------------------------


def build_workforce_baseline(
    world: ModerationWorld,
    clock: str = CLOCK_T0,
    account_overrides: Optional[Dict[str, Any]] = None,
    category_overrides: Optional[Dict[str, Any]] = None,
    version_overrides: Optional[Dict[str, Any]] = None,
    queue_overrides: Optional[Dict[str, Any]] = None,
    certify_all: bool = True,
) -> WorkforceBaseline:
    """A policy baseline plus three certified reviewers, one of each role class."""
    baseline = build_policy_baseline(
        world,
        clock=clock,
        account_overrides=account_overrides,
        category_overrides=category_overrides,
        version_overrides=version_overrides,
        queue_overrides=queue_overrides,
    )
    languages = [baseline.queue["language"]]
    specialties = [baseline.queue["specialty"]]
    frontline = world.create_reviewer(
        display_name="Rita Frontline",
        role_class="FRONTLINE",
        languages=languages,
        specialties=specialties,
    )
    senior = world.create_reviewer(
        display_name="Sven Senior",
        role_class="SENIOR",
        languages=languages,
        specialties=specialties,
    )
    auditor = world.create_reviewer(
        display_name="Quinn Quality",
        role_class="QA",
        languages=languages,
        specialties=specialties,
    )
    if certify_all:
        for reviewer in (frontline, senior, auditor):
            world.certify(reviewer["id"], baseline.version_id)
    return WorkforceBaseline(
        world=world,
        account=baseline.account,
        category=baseline.category,
        version=baseline.version,
        queue=baseline.queue,
        frontline=world.get_reviewer(frontline["id"]),
        senior=world.get_reviewer(senior["id"]),
        auditor=world.get_reviewer(auditor["id"]),
    )


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts, one per reachable case state
# ---------------------------------------------------------------------------

# A score that clears the default floor of 0.4 without reaching the default
# ceiling of 0.9, so the routing chain lands on human review.
HUMAN_REVIEW_CONFIDENCE = 0.7

# A score at or above the default ceiling of 0.9, so the routing chain lands on
# automatic enforcement.
AUTO_ACTION_CONFIDENCE = 0.95

# A score strictly below the default floor of 0.4, so the signal is discarded.
DISCARD_CONFIDENCE = 0.2


def build_pending_case(
    base: WorkforceBaseline,
    content_overrides: Optional[Dict[str, Any]] = None,
    classifier_confidence: float = HUMAN_REVIEW_CONFIDENCE,
    account_id: Optional[str] = None,
) -> CaseScenario:
    """Ingest content and raise a classifier case that awaits assignment."""
    world = base.world
    content = world.create_content(
        account_id or base.account_id,
        language=base.queue["language"],
        **(content_overrides or {}),
    )
    signal = world.submit_signal(
        content["id"],
        policy_category_code=base.category_code,
        classifier_confidence=classifier_confidence,
    )
    case = world.get_case(signal["resulting_case_id"])
    return CaseScenario(base=base, content=world.get_content(content["id"]), case=case, signal=signal)


def build_manual_case(
    base: WorkforceBaseline,
    content_overrides: Optional[Dict[str, Any]] = None,
) -> CaseScenario:
    """Ingest content and hand-open a manual-report case on it."""
    world = base.world
    content = world.create_content(
        base.account_id,
        language=base.queue["language"],
        **(content_overrides or {}),
    )
    case = world.open_manual_case(content["id"], policy_category_code=base.category_code)
    return CaseScenario(base=base, content=world.get_content(content["id"]), case=case)


def build_legal_case(
    base: WorkforceBaseline,
    content_overrides: Optional[Dict[str, Any]] = None,
    **case_overrides: Any,
) -> CaseScenario:
    """Ingest content and open a legal-request case, which is born escalated."""
    world = base.world
    content = world.create_content(
        base.account_id,
        language=base.queue["language"],
        **(content_overrides or {}),
    )
    case = world.open_legal_case(
        content["id"], policy_category_code=base.category_code, **case_overrides
    )
    return CaseScenario(base=base, content=world.get_content(content["id"]), case=case)


def build_auto_action_case(
    base: WorkforceBaseline,
    content_overrides: Optional[Dict[str, Any]] = None,
) -> CaseScenario:
    """Raise a signal confident enough to be enforced without human review."""
    return build_pending_case(
        base,
        content_overrides=content_overrides,
        classifier_confidence=AUTO_ACTION_CONFIDENCE,
    )


def build_assigned_case(
    base: WorkforceBaseline,
    reviewer_id: Optional[str] = None,
    content_overrides: Optional[Dict[str, Any]] = None,
) -> CaseScenario:
    """Reach a case held by a named reviewer."""
    scenario = build_pending_case(base, content_overrides=content_overrides)
    base.world.assign(scenario.case_id, target_reviewer_id=reviewer_id or base.frontline_id)
    scenario.case = base.world.get_case(scenario.case_id)
    return scenario


def build_decided_case(
    base: WorkforceBaseline,
    reviewer_id: Optional[str] = None,
    outcome: str = "REMOVE",
    content_overrides: Optional[Dict[str, Any]] = None,
) -> CaseScenario:
    """Reach a case a reviewer has decided."""
    holder = reviewer_id or base.frontline_id
    scenario = build_assigned_case(base, reviewer_id=holder, content_overrides=content_overrides)
    base.world.decide(scenario.case_id, holder, outcome=outcome)
    scenario.case = base.world.get_case(scenario.case_id)
    return scenario


def build_escalated_case(
    base: WorkforceBaseline,
    reviewer_id: Optional[str] = None,
    escalation_reason: str = "CALIBRATION",
    content_overrides: Optional[Dict[str, Any]] = None,
) -> CaseScenario:
    """Reach a case that a holding reviewer has escalated away."""
    holder = reviewer_id or base.frontline_id
    scenario = build_assigned_case(base, reviewer_id=holder, content_overrides=content_overrides)
    base.world.escalate(scenario.case_id, holder, escalation_reason=escalation_reason)
    scenario.case = base.world.get_case(scenario.case_id)
    return scenario


# ---------------------------------------------------------------------------
# Tier 4: accumulation and threshold targeting
# ---------------------------------------------------------------------------


def accumulate_strike_points(
    base: WorkforceBaseline,
    minimum_points: int,
    max_rounds: int = 8,
) -> Dict[str, Any]:
    """Charge the account through automatic enforcement until the ledger clears a floor.

    Each round ingests a fresh item and raises a signal confident enough to be
    enforced automatically, which charges the account and recomputes both the
    ledger and the posture derived from it.
    """
    world = base.world
    for _ in range(max_rounds):
        account = world.get_account(base.account_id)
        if account["strike_points"] >= minimum_points:
            return account
        build_auto_action_case(base)
    return world.get_account(base.account_id)


def drive_account_to_banned(base: WorkforceBaseline, max_rounds: int = 8) -> Dict[str, Any]:
    """Charge the account until its posture reaches the hardest block."""
    from .constants import STANDING_BANNED_AT

    return accumulate_strike_points(base, STANDING_BANNED_AT, max_rounds=max_rounds)


def fill_queue_to_depth(
    base: WorkforceBaseline,
    open_case_count: int,
    max_rounds: int = 40,
) -> Dict[str, Any]:
    """Raise human-review cases until the queue holds at least this many open cases."""
    world = base.world
    for _ in range(max_rounds):
        queue = world.get_queue(base.queue_id)
        if queue["open_case_count"] >= open_case_count:
            return queue
        build_pending_case(base)
    return world.get_queue(base.queue_id)


def load_reviewer_to_capacity(
    base: WorkforceBaseline,
    reviewer_id: str,
    max_rounds: int = 20,
) -> Dict[str, Any]:
    """Assign cases to a reviewer until they hold as many as they may hold at once."""
    world = base.world
    for _ in range(max_rounds):
        reviewer = world.get_reviewer(reviewer_id)
        if reviewer["open_case_count"] >= reviewer["max_concurrent_cases"]:
            return reviewer
        scenario = build_pending_case(base)
        world.assign(scenario.case_id, target_reviewer_id=reviewer_id)
    return world.get_reviewer(reviewer_id)


# ---------------------------------------------------------------------------
# Tier 5: terminal and near-terminal states
# ---------------------------------------------------------------------------


def build_submitted_appeal(
    base: WorkforceBaseline,
    outcome: str = "REMOVE",
    reviewer_id: Optional[str] = None,
) -> AppealScenario:
    """Reach an appeal freshly filed by the author against a decided case."""
    scenario = build_decided_case(base, reviewer_id=reviewer_id, outcome=outcome)
    appeal = base.world.file_appeal(scenario.case_id, base.account_id)
    return AppealScenario(case_scenario=scenario, appeal=appeal)


def build_appeal_under_independent_review(
    base: WorkforceBaseline,
    outcome: str = "REMOVE",
    independent_reviewer_id: Optional[str] = None,
) -> AppealScenario:
    """Reach an appeal routed to an independent reviewer who is not the decider."""
    filed = build_submitted_appeal(base, outcome=outcome)
    base.world.route_appeal(
        filed.appeal_id,
        base.auditor_id,
        target_reviewer_id=independent_reviewer_id or base.senior_id,
    )
    filed.appeal = base.world.get_appeal(filed.appeal_id)
    return filed


def build_resolved_appeal(
    base: WorkforceBaseline,
    resolution: str = "OVERTURNED",
    outcome: str = "REMOVE",
    independent_reviewer_id: Optional[str] = None,
) -> AppealScenario:
    """Reach an appeal the independent reviewer has already resolved."""
    routed = build_appeal_under_independent_review(
        base, outcome=outcome, independent_reviewer_id=independent_reviewer_id
    )
    reviewer = independent_reviewer_id or base.senior_id
    base.world.resolve_appeal(routed.appeal_id, reviewer, resolution=resolution)
    routed.appeal = base.world.get_appeal(routed.appeal_id)
    return routed


def build_drawn_sample(
    base: WorkforceBaseline,
    outcome: str = "REMOVE",
    reviewer_id: Optional[str] = None,
) -> AuditScenario:
    """Reach a quality sample drawn over a case the frontline reviewer decided."""
    scenario = build_decided_case(base, reviewer_id=reviewer_id, outcome=outcome)
    sample = base.world.draw_sample(scenario.case_id, base.auditor_id)
    return AuditScenario(case_scenario=scenario, sample=sample)


def build_audited_sample(
    base: WorkforceBaseline,
    verdict: str = "AGREE",
    correct_outcome: Optional[str] = None,
    outcome: str = "REMOVE",
    reviewer_id: Optional[str] = None,
) -> AuditScenario:
    """Reach a sample that already carries a verdict."""
    drawn = build_drawn_sample(base, outcome=outcome, reviewer_id=reviewer_id)
    overrides: Dict[str, Any] = {"verdict": verdict}
    if verdict != "AGREE":
        overrides["correct_outcome"] = correct_outcome or "WARN"
    base.world.audit(drawn.sample_id, base.auditor_id, **overrides)
    drawn.sample = base.world.get_sample(drawn.sample_id)
    return drawn


def build_disputed_sample(
    base: WorkforceBaseline,
    verdict: str = "DISAGREE_MATERIAL",
    reviewer_id: Optional[str] = None,
) -> AuditScenario:
    """Reach a sample the deciding reviewer has contested."""
    holder = reviewer_id or base.frontline_id
    audited = build_audited_sample(base, verdict=verdict, reviewer_id=holder)
    base.world.dispute(audited.sample_id, holder)
    audited.sample = base.world.get_sample(audited.sample_id)
    return audited


def build_computed_report(
    world: ModerationWorld,
    variant: str = "RESTATED",
    **report_overrides: Any,
) -> Dict[str, Any]:
    """Reach a report that has been computed but not yet published."""
    report = world.create_report(**report_overrides)
    world.compute_report(report["id"], variant=variant)
    return world.get_report(report["id"])


def build_published_report(
    world: ModerationWorld,
    **report_overrides: Any,
) -> Dict[str, Any]:
    """Reach a report that has been published and is therefore frozen."""
    report = build_computed_report(world, variant="RESTATED", **report_overrides)
    world.publish_report(report["id"])
    return world.get_report(report["id"])


def suspend_reviewer_through_accuracy_gate(
    base: WorkforceBaseline,
    reviewer_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive a reviewer below the suspension floor through two disagreeing audits.

    Two audited samples with no agreement give a gate score of zero over a
    denominator of two, which is enough evidence for the gate to act.
    """
    holder = reviewer_id or base.frontline_id
    for _ in range(2):
        build_audited_sample(
            base,
            verdict="DISAGREE_MATERIAL",
            correct_outcome="NO_ACTION",
            reviewer_id=holder,
        )
    return base.world.get_reviewer(holder)


def demote_reviewer_to_pending_retraining(
    base: WorkforceBaseline,
    reviewer_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive a reviewer between the two floors through three audits, two agreeing.

    Two agreements out of three gives a gate score of 0.6667, which sits at or
    above the suspension floor but strictly below the retraining floor.
    """
    holder = reviewer_id or base.frontline_id
    build_audited_sample(base, verdict="AGREE", reviewer_id=holder)
    build_audited_sample(base, verdict="AGREE", reviewer_id=holder)
    build_audited_sample(
        base,
        verdict="DISAGREE_MATERIAL",
        correct_outcome="NO_ACTION",
        reviewer_id=holder,
    )
    return base.world.get_reviewer(holder)


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def world() -> ModerationWorld:
    """A scripting layer over the API for the test's own setup steps."""
    return ModerationWorld(api_client)


@pytest.fixture
def clock_at_t0(world: ModerationWorld) -> str:
    """The logical clock parked at the instant the scenarios open at."""
    return world.set_clock(CLOCK_T0)


@pytest.fixture
def account(world: ModerationWorld, clock_at_t0: str) -> Dict[str, Any]:
    """One supervised author in good standing."""
    return world.create_account()


@pytest.fixture
def policy_baseline(world: ModerationWorld) -> PolicyBaseline:
    """An account, an ACTIVE policy version and a queue that serves it."""
    return build_policy_baseline(world)


@pytest.fixture
def workforce(world: ModerationWorld) -> WorkforceBaseline:
    """The policy spine plus a certified frontline, senior and QA reviewer."""
    return build_workforce_baseline(world)


@pytest.fixture
def pending_case(workforce: WorkforceBaseline) -> CaseScenario:
    """A classifier case awaiting assignment."""
    return build_pending_case(workforce)


@pytest.fixture
def manual_case(workforce: WorkforceBaseline) -> CaseScenario:
    """A hand-opened manual-report case awaiting assignment."""
    return build_manual_case(workforce)


@pytest.fixture
def assigned_case(workforce: WorkforceBaseline) -> CaseScenario:
    """A case held by the certified frontline reviewer."""
    return build_assigned_case(workforce)


@pytest.fixture
def decided_case(workforce: WorkforceBaseline) -> CaseScenario:
    """A case the frontline reviewer has decided by removing the content."""
    return build_decided_case(workforce)


@pytest.fixture
def escalated_case(workforce: WorkforceBaseline) -> CaseScenario:
    """A case the holding reviewer has escalated away."""
    return build_escalated_case(workforce)


@pytest.fixture
def auto_action_case(workforce: WorkforceBaseline) -> CaseScenario:
    """A case born decided by automatic enforcement."""
    return build_auto_action_case(workforce)


@pytest.fixture
def legal_case(workforce: WorkforceBaseline) -> CaseScenario:
    """A legal-request case, which opens already escalated."""
    return build_legal_case(workforce)


@pytest.fixture
def submitted_appeal(workforce: WorkforceBaseline) -> AppealScenario:
    """An appeal the author has just filed."""
    return build_submitted_appeal(workforce)


@pytest.fixture
def appeal_under_review(workforce: WorkforceBaseline) -> AppealScenario:
    """An appeal routed to an independent senior reviewer."""
    return build_appeal_under_independent_review(workforce)


@pytest.fixture
def drawn_sample(workforce: WorkforceBaseline) -> AuditScenario:
    """A quality sample drawn over a decided case."""
    return build_drawn_sample(workforce)


@pytest.fixture
def audited_sample(workforce: WorkforceBaseline) -> AuditScenario:
    """A quality sample that already carries an agreeing verdict."""
    return build_audited_sample(workforce)


@pytest.fixture
def draft_report(world: ModerationWorld, clock_at_t0: str) -> Dict[str, Any]:
    """A reporting period opened but not yet computed."""
    return world.create_report()


@pytest.fixture
def computed_report(world: ModerationWorld, clock_at_t0: str) -> Dict[str, Any]:
    """A reporting period computed under the restated variant."""
    return build_computed_report(world, variant="RESTATED")

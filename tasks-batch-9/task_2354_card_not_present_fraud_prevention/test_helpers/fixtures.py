"""Composite setup helpers.

Every test starts against an empty database, so each precondition is built from
scratch through the documented endpoints. The helpers below stack in five tiers:

* Tier 1 — single-row primitives and state progressions (clock moves, posture
  moves, shift moves, lifecycle actions).
* Tier 2 — entity hierarchies: the shopper triple, the decisioning assets, and
  the ``BOOT-W`` environment that stands up an ACTIVE rule pack and an ACTIVE
  risk model so an assessment can be opened at all.
* Tier 3 — full-lifecycle shortcuts: open-and-score in one call, an approved
  order, an order sitting in the review queue with its case, an assigned case,
  a resolved case, a lost dispute, an approved policy exception, a step-up
  challenge already issued.
* Tier 4 — accumulation and threshold targeting: a customer carried over the
  good-customer thresholds, a device carried up its reputation ladder, a
  velocity burst, a training corpus with the required reason-code segments.
* Tier 5 — finalisation and terminal states: containment, retirement, a
  chargeback driven to WON or LOST.

All helpers use ``get_success_data`` so that a broken precondition fails loudly
with the setup step's own error identifier rather than surfacing later as a
confusing assertion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .constants import (
    CLOCK_EPOCH,
    LARGE_ORDER_CENTS,
    PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR,
    PROB_REVIEW_MID_BAND,
    SMALL_ORDER_CENTS,
    STANDARD_ORDER_CENTS,
)
from .factories import (
    address_whitelist_exception_payload,
    analyst_shift_payload,
    assign_case_payload,
    challenge_payload,
    chargeback_transition_payload,
    create_address_payload,
    create_analyst_payload,
    create_assessment_payload,
    create_auth_event_payload,
    create_chargeback_payload,
    create_customer_payload,
    create_device_payload,
    create_policy_exception_payload,
    create_risk_model_payload,
    create_rule_pack_payload,
    create_rule_payload,
    emulator_hard_decline_rule_payload,
    exception_decision_payload,
    fast_checkout_rule_payload,
    lock_account_payload,
    model_lifecycle_payload,
    resolve_case_payload,
    set_clock_payload,
    unlock_account_payload,
)
from .test_users import (
    make_checkout_service_headers,
    make_platform_admin_headers,
    make_policy_engineer_approver_headers,
    make_policy_engineer_author_headers,
    make_review_lead_headers,
    make_risk_analyst_headers,
)
from .types import (
    AnalystStatus,
    AuthEventType,
    ChallengeAction,
    ChargebackAction,
    ChargebackReasonCode,
    CustomerTier,
    ExceptionAction,
    RiskModelAction,
    Seniority,
    SignalFamily,
)

CHECKOUT = make_checkout_service_headers()
ADMIN = make_platform_admin_headers()
ENGINEER = make_policy_engineer_author_headers()
ENGINEER_APPROVER = make_policy_engineer_approver_headers()


# ===========================================================================
# Tier 1 — primitives and single-row state progressions
# ===========================================================================


def set_clock(api: Any, current_utc: str = CLOCK_EPOCH) -> Dict[str, Any]:
    """Advance the server's logical clock to ``current_utc``."""
    return get_success_data(api.set_clock(set_clock_payload(current_utc), ADMIN))


def create_customer(api: Any, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_customer(create_customer_payload(**overrides), CHECKOUT)
    )


def create_high_value_customer(api: Any, **overrides: Any) -> Dict[str, Any]:
    overrides.setdefault("tier", CustomerTier.HIGH_VALUE)
    return create_customer(api, **overrides)


def create_business_customer(api: Any, **overrides: Any) -> Dict[str, Any]:
    overrides.setdefault("tier", CustomerTier.BUSINESS)
    return create_customer(api, **overrides)


def read_customer(api: Any, customer_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(api.get_customer(customer_id, headers or ADMIN))


def lock_customer(api: Any, customer_id: str, reason: str = "manual review hold"):
    """Drive ``account_status`` ``ACTIVE -> LOCKED``."""
    return get_success_data(
        api.set_customer_posture(customer_id, lock_account_payload(reason), ADMIN)
    )


def unlock_customer(api: Any, customer_id: str) -> Dict[str, Any]:
    """Drive ``account_status`` ``LOCKED -> ACTIVE``."""
    return get_success_data(
        api.set_customer_posture(customer_id, unlock_account_payload(), ADMIN)
    )


def create_device(api: Any, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_device(create_device_payload(**overrides), CHECKOUT)
    )


def create_emulator_device(api: Any, **overrides: Any) -> Dict[str, Any]:
    overrides.setdefault("emulator_flag", True)
    return create_device(api, **overrides)


def read_device(api: Any, device_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(api.get_device(device_id, headers or CHECKOUT))


def create_address(api: Any, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_address(create_address_payload(**overrides), CHECKOUT)
    )


def read_address(api: Any, address_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(api.get_address(address_id, headers or CHECKOUT))


def create_analyst(api: Any, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_analyst(create_analyst_payload(**overrides), ADMIN)
    )


def read_analyst(api: Any, analyst_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(api.get_analyst(analyst_id, headers or ADMIN))


def move_analyst_off_shift(api: Any, analyst_id: str) -> Dict[str, Any]:
    """Move an analyst away from ``AVAILABLE``, firing the shift-release cascade."""
    return get_success_data(
        api.set_analyst_shift(
            analyst_id, analyst_shift_payload(AnalystStatus.OFF_SHIFT), ADMIN
        )
    )


def set_analyst_status(api: Any, analyst_id: str, status: str) -> Dict[str, Any]:
    return get_success_data(
        api.set_analyst_shift(analyst_id, analyst_shift_payload(status), ADMIN)
    )


# ---------------------------------------------------------------------------
# Rule packs
# ---------------------------------------------------------------------------


def draft_rule_pack(api: Any, **overrides: Any) -> Dict[str, Any]:
    """Draft a pack as the author engineer, whose id becomes ``created_by_user_id``."""
    return get_success_data(
        api.create_rule_pack(create_rule_pack_payload(**overrides), ENGINEER)
    )


def add_rule(api: Any, pack_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_rule(pack_id, create_rule_payload(**overrides), ENGINEER)
    )


def add_rule_payload(api: Any, pack_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api.create_rule(pack_id, payload, ENGINEER))


def activate_rule_pack(api: Any, pack_id: str) -> Dict[str, Any]:
    """Activate a pack as a second engineer, so the segregation check is clear."""
    return get_success_data(api.activate_rule_pack(pack_id, ENGINEER_APPROVER))


def read_rule_pack(api: Any, pack_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(api.get_rule_pack(pack_id, headers or ENGINEER))


#: The single BEH_FAST_CHECKOUT rule the reference pack carries.
REFERENCE_RULES: Tuple[Dict[str, Any], ...] = (
    fast_checkout_rule_payload(points=20, evaluation_order=10),
)

#: The reference pack plus the hard-decline DEV_EMULATOR rule worth 45 points.
REFERENCE_RULES_WITH_HARD_DECLINE: Tuple[Dict[str, Any], ...] = (
    fast_checkout_rule_payload(points=20, evaluation_order=10),
    emulator_hard_decline_rule_payload(points=45, evaluation_order=20),
)


def build_active_rule_pack(
    api: Any,
    rules: Sequence[Dict[str, Any]] = REFERENCE_RULES,
    **pack_overrides: Any,
) -> Dict[str, Any]:
    """Draft a pack, add ``rules`` to it while it is DRAFT, then activate it."""
    pack = draft_rule_pack(api, **pack_overrides)
    for rule in rules:
        add_rule_payload(api, pack["id"], dict(rule))
    return activate_rule_pack(api, pack["id"])


def build_draft_rule_pack(
    api: Any,
    rules: Sequence[Dict[str, Any]] = REFERENCE_RULES,
    **pack_overrides: Any,
) -> Dict[str, Any]:
    """Draft a pack and populate it, leaving it in DRAFT."""
    pack = draft_rule_pack(api, **pack_overrides)
    for rule in rules:
        add_rule_payload(api, pack["id"], dict(rule))
    return read_rule_pack(api, pack["id"])


# ---------------------------------------------------------------------------
# Risk models
# ---------------------------------------------------------------------------


def draft_risk_model(api: Any, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_risk_model(create_risk_model_payload(**overrides), ENGINEER)
    )


def model_action(api: Any, model_id: str, action: str) -> Dict[str, Any]:
    return get_success_data(
        api.risk_model_lifecycle(model_id, model_lifecycle_payload(action), ENGINEER)
    )


def build_active_risk_model(api: Any, **overrides: Any) -> Dict[str, Any]:
    """Draft a cold-start model, publish it to SHADOW, then promote it to ACTIVE."""
    model = draft_risk_model(api, **overrides)
    model_action(api, model["id"], RiskModelAction.PUBLISH_SHADOW)
    return model_action(api, model["id"], RiskModelAction.PROMOTE)


def read_risk_model(api: Any, model_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(api.get_risk_model(model_id, headers or ENGINEER))


# ===========================================================================
# Tier 2 — entity hierarchies
# ===========================================================================


@dataclass
class ShopperTriple:
    """A customer, a device profile and one address, all freshly registered."""

    customer: Dict[str, Any]
    device: Dict[str, Any]
    address: Dict[str, Any]

    @property
    def customer_id(self) -> str:
        return self.customer["id"]

    @property
    def device_id(self) -> str:
        return self.device["id"]

    @property
    def address_id(self) -> str:
        return self.address["id"]


def build_shopper_triple(
    api: Any,
    customer_overrides: Optional[Dict[str, Any]] = None,
    device_overrides: Optional[Dict[str, Any]] = None,
    address_overrides: Optional[Dict[str, Any]] = None,
) -> ShopperTriple:
    """The shopper triple every scoring scenario needs."""
    return ShopperTriple(
        customer=create_customer(api, **(customer_overrides or {})),
        device=create_device(api, **(device_overrides or {})),
        address=create_address(api, **(address_overrides or {})),
    )


@dataclass
class ScoringEnv:
    """A shopper triple plus an ACTIVE rule pack and an ACTIVE risk model."""

    customer: Dict[str, Any]
    device: Dict[str, Any]
    address: Dict[str, Any]
    pack: Dict[str, Any]
    model: Dict[str, Any]
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def customer_id(self) -> str:
        return self.customer["id"]

    @property
    def device_id(self) -> str:
        return self.device["id"]

    @property
    def address_id(self) -> str:
        return self.address["id"]

    @property
    def pack_id(self) -> str:
        return self.pack["id"]

    @property
    def model_id(self) -> str:
        return self.model["id"]


def build_scoring_env(
    api: Any,
    rules: Sequence[Dict[str, Any]] = REFERENCE_RULES,
    customer_overrides: Optional[Dict[str, Any]] = None,
    device_overrides: Optional[Dict[str, Any]] = None,
    address_overrides: Optional[Dict[str, Any]] = None,
    set_clock_first: bool = True,
    **pack_overrides: Any,
) -> ScoringEnv:
    """Stand up everything an assessment needs before it can be opened.

    The pack is WEIGHTED with ``rule_weight`` 0.40, ``model_weight`` 0.60,
    ``review_floor_score`` 40.00 and ``decline_floor_score`` 60.00, holding the
    rules given in ``rules``. The model has ``calibration_intercept`` 0.05 and
    ``calibration_slope`` 1.20.
    """
    if set_clock_first:
        set_clock(api, CLOCK_EPOCH)
    triple = build_shopper_triple(
        api, customer_overrides, device_overrides, address_overrides
    )
    pack = build_active_rule_pack(api, rules, **pack_overrides)
    model = build_active_risk_model(api)
    return ScoringEnv(
        customer=triple.customer,
        device=triple.device,
        address=triple.address,
        pack=pack,
        model=model,
    )


def build_scoring_env_with_hard_decline_rule(api: Any, **kwargs: Any) -> ScoringEnv:
    """The reference environment whose pack also carries the hard-decline rule."""
    return build_scoring_env(api, rules=REFERENCE_RULES_WITH_HARD_DECLINE, **kwargs)


# ---------------------------------------------------------------------------
# Analyst rosters
# ---------------------------------------------------------------------------


@dataclass
class Roster:
    """A named set of analysts, keyed by the label the scenario uses."""

    analysts: Dict[str, Dict[str, Any]]

    def id_of(self, label: str) -> str:
        return self.analysts[label]["id"]

    def version_of(self, label: str) -> int:
        return int(self.analysts[label]["version"])

    def __getitem__(self, label: str) -> Dict[str, Any]:
        return self.analysts[label]


def build_roster(api: Any, specs: Dict[str, Dict[str, Any]]) -> Roster:
    """Register one analyst per entry of ``specs``, preserving insertion order."""
    return Roster({label: create_analyst(api, **spec) for label, spec in specs.items()})


def build_behavioral_roster(api: Any) -> Roster:
    """A junior behavioural analyst with capacity 2 and a lead with capacity 3.

    The lead's ``skill_families`` also cover ``BEHAVIORAL`` so the lead can take
    an escalated behavioural case.
    """
    return build_roster(
        api,
        {
            "junior": {
                "display_name": "AN1",
                "seniority": Seniority.JUNIOR,
                "skill_families": [SignalFamily.BEHAVIORAL],
                "shift_capacity_cases": 2,
            },
            "lead": {
                "display_name": "LEAD1",
                "seniority": Seniority.LEAD,
                "skill_families": [SignalFamily.BEHAVIORAL],
                "shift_capacity_cases": 3,
            },
        },
    )


def build_lead(api: Any, **overrides: Any) -> Dict[str, Any]:
    """A LEAD analyst, which is what the ``ReviewLead`` role's X-User-ID must name."""
    overrides.setdefault("display_name", "LEAD1")
    overrides.setdefault("seniority", Seniority.LEAD)
    overrides.setdefault("skill_families", list(SignalFamily.ALL))
    overrides.setdefault("shift_capacity_cases", 3)
    return create_analyst(api, **overrides)


# ===========================================================================
# Tier 3 — full-lifecycle shortcuts
# ===========================================================================


def open_assessment(api: Any, env: ScoringEnv, **overrides: Any) -> Dict[str, Any]:
    """Open an assessment against ``env``, pinning its pack and model."""
    payload = create_assessment_payload(
        env.customer_id, env.device_id, env.address_id, **overrides
    )
    return get_success_data(api.create_assessment(payload, CHECKOUT))


def score_assessment(api: Any, assessment_id: str) -> Dict[str, Any]:
    """Run the scoring pipeline; the response carries every score field."""
    return get_success_data(api.score_assessment(assessment_id, CHECKOUT))


def open_and_score(api: Any, env: ScoringEnv, **overrides: Any) -> Dict[str, Any]:
    """Open an assessment and score it in one step, returning the score response."""
    opened = open_assessment(api, env, **overrides)
    return score_assessment(api, opened["id"])


def read_assessment(
    api: Any, assessment_id: str, headers: Optional[Dict[str, str]] = None
):
    return get_success_data(api.get_assessment(assessment_id, headers or CHECKOUT))


def build_approved_assessment(
    api: Any,
    env: ScoringEnv,
    amount_cents: int = SMALL_ORDER_CENTS,
    **overrides: Any,
) -> Dict[str, Any]:
    """An order scored straight to ``DECIDED_APPROVE`` by the score band.

    ``model_raw_probability`` 0.4021 yields ``model_points`` 53.25 and a
    ``blended_score`` of 39.95, just under the 40.00 review floor.
    """
    overrides.setdefault(
        "model_raw_probability", PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR
    )
    overrides["amount_cents"] = amount_cents
    return open_and_score(api, env, **overrides)


def build_reviewed_assessment(
    api: Any,
    env: ScoringEnv,
    amount_cents: int = LARGE_ORDER_CENTS,
    **overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """An order scored into the review band, together with the case it created.

    ``model_raw_probability`` 0.5417 yields ``model_points`` 70.00 and a
    ``blended_score`` of 50.00, which sits between the 40.00 review floor and
    the 60.00 decline floor.
    """
    overrides.setdefault("model_raw_probability", PROB_REVIEW_MID_BAND)
    overrides["amount_cents"] = amount_cents
    assessment = open_and_score(api, env, **overrides)
    case = find_case_for_assessment(api, assessment["id"])
    assert case is not None, (
        "the review branch must create a review case for the scored assessment"
    )
    return assessment, case


def find_case_for_assessment(
    api: Any, assessment_id: str, headers: Optional[Dict[str, str]] = None
) -> Optional[Dict[str, Any]]:
    """Locate the review case the review branch created for an assessment."""
    rows, _meta = validate_paginated(
        api.list_review_cases(headers or ADMIN, params={"assessment_id": assessment_id})
    )
    return rows[0] if rows else None


def list_cases_for_assessment(
    api: Any, assessment_id: str, headers: Optional[Dict[str, str]] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return validate_paginated(
        api.list_review_cases(headers or ADMIN, params={"assessment_id": assessment_id})
    )


def read_case(api: Any, case_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(api.get_review_case(case_id, headers or ADMIN))


def assign_case(
    api: Any,
    case_id: str,
    analyst_id: str,
    expected_analyst_version: int,
    lead_id: str,
) -> Dict[str, Any]:
    """Assign a case by name, acting as the ``ReviewLead`` analyst ``lead_id``."""
    return get_success_data(
        api.assign_case(
            case_id,
            assign_case_payload(analyst_id, expected_analyst_version),
            make_review_lead_headers(lead_id),
        )
    )


def assign_case_to(
    api: Any, case_id: str, analyst: Dict[str, Any], lead_id: str
) -> Dict[str, Any]:
    """Assign a case using the analyst row's currently observed ``version``."""
    fresh = read_analyst(api, analyst["id"])
    return assign_case(api, case_id, fresh["id"], int(fresh["version"]), lead_id)


def auto_assign_case(api: Any, case_id: str, lead_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.auto_assign_case(case_id, make_review_lead_headers(lead_id))
    )


def resolve_case_as_analyst(
    api: Any, case_id: str, analyst_id: str, action: str, **overrides: Any
) -> Dict[str, Any]:
    """Resolve or escalate acting as the ``RiskAnalyst`` who holds the case."""
    return get_success_data(
        api.resolve_case(
            case_id,
            resolve_case_payload(action, **overrides),
            make_risk_analyst_headers(analyst_id),
        )
    )


def resolve_case_as_lead(
    api: Any, case_id: str, lead_id: str, action: str, **overrides: Any
) -> Dict[str, Any]:
    """Resolve acting as a ``ReviewLead``, who may resolve any ASSIGNED case."""
    return get_success_data(
        api.resolve_case(
            case_id,
            resolve_case_payload(action, **overrides),
            make_review_lead_headers(lead_id),
        )
    )


@dataclass
class StaffedCase:
    """A review case that has been assigned to a named analyst."""

    assessment: Dict[str, Any]
    case: Dict[str, Any]
    analyst: Dict[str, Any]
    lead: Dict[str, Any]

    @property
    def case_id(self) -> str:
        return self.case["id"]

    @property
    def analyst_id(self) -> str:
        return self.analyst["id"]

    @property
    def lead_id(self) -> str:
        return self.lead["id"]


def build_staffed_case(
    api: Any,
    env: ScoringEnv,
    amount_cents: int = LARGE_ORDER_CENTS,
    roster: Optional[Roster] = None,
    **overrides: Any,
) -> StaffedCase:
    """An order in review whose case is ASSIGNED to a junior behavioural analyst."""
    roster = roster or build_behavioral_roster(api)
    assessment, case = build_reviewed_assessment(api, env, amount_cents, **overrides)
    assigned = assign_case_to(api, case["id"], roster["junior"], roster.id_of("lead"))
    return StaffedCase(
        assessment=assessment,
        case=assigned,
        analyst=read_analyst(api, roster.id_of("junior")),
        lead=roster["lead"],
    )


def escalate_case(api: Any, case_id: str, analyst_id: str, note: Optional[str] = None):
    """Escalate acting as the case's assigned analyst."""
    overrides = {"resolution_note": note} if note is not None else {}
    return resolve_case_as_analyst(api, case_id, analyst_id, "ESCALATE", **overrides)


# ---------------------------------------------------------------------------
# Policy exceptions
# ---------------------------------------------------------------------------


def request_exception(
    api: Any, customer_id: str, analyst_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Request an exception acting as the ``RiskAnalyst`` analyst ``analyst_id``."""
    return get_success_data(
        api.create_policy_exception(
            create_policy_exception_payload(customer_id, **overrides),
            make_risk_analyst_headers(analyst_id),
        )
    )


def request_address_whitelist_exception(
    api: Any,
    customer_id: str,
    analyst_id: str,
    whitelisted_address_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_policy_exception(
            address_whitelist_exception_payload(
                customer_id, whitelisted_address_id, **overrides
            ),
            make_risk_analyst_headers(analyst_id),
        )
    )


def decide_exception(
    api: Any,
    exception_id: str,
    lead_id: str,
    action: str,
    expected_customer_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.decide_policy_exception(
            exception_id,
            exception_decision_payload(action, expected_customer_version, **overrides),
            make_review_lead_headers(lead_id),
        )
    )


def approve_exception(
    api: Any, exception_id: str, lead_id: str, customer_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Approve an exception, reading the customer's current version first."""
    customer = read_customer(api, customer_id)
    return decide_exception(
        api,
        exception_id,
        lead_id,
        ExceptionAction.APPROVE,
        int(customer["version"]),
        **overrides,
    )


@dataclass
class ExceptionSetup:
    """An APPROVED policy exception plus the two analysts involved."""

    exception: Dict[str, Any]
    requester: Dict[str, Any]
    lead: Dict[str, Any]

    @property
    def exception_id(self) -> str:
        return self.exception["id"]

    @property
    def requester_id(self) -> str:
        return self.requester["id"]

    @property
    def lead_id(self) -> str:
        return self.lead["id"]


def build_approved_exception(
    api: Any, customer_id: str, **overrides: Any
) -> ExceptionSetup:
    """Register a requesting analyst and a deciding lead, then approve an exception."""
    requester = create_analyst(
        api,
        display_name="AN-REQ",
        seniority=Seniority.SENIOR,
        skill_families=list(SignalFamily.ALL),
        shift_capacity_cases=3,
    )
    lead = build_lead(api)
    requested = request_exception(api, customer_id, requester["id"], **overrides)
    approved = approve_exception(api, requested["id"], lead["id"], customer_id)
    return ExceptionSetup(exception=approved, requester=requester, lead=lead)


# ---------------------------------------------------------------------------
# Authentication events and step-up challenges
# ---------------------------------------------------------------------------


def record_auth_event(
    api: Any,
    customer_id: str,
    device_id: str,
    event_type: str = AuthEventType.LOGIN,
    ip_country: str = "US",
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_auth_event(
            create_auth_event_payload(
                customer_id, device_id, event_type, ip_country, **overrides
            ),
            CHECKOUT,
        )
    )


def read_auth_event(api: Any, event_id: str, headers: Optional[Dict[str, str]] = None):
    return get_success_data(api.get_auth_event(event_id, headers or CHECKOUT))


def drive_challenge(
    api: Any, event_id: str, action: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.challenge(event_id, challenge_payload(action, **overrides), CHECKOUT)
    )


def build_step_up_event(
    api: Any, customer_id: str, device_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A ``PASSWORD_CHANGE`` from a foreign IP on a known device.

    A base of 25.00 plus a geography term of 25.00 is 50.00, which lands in
    ``STEP_UP_REQUIRED`` and issues a challenge.
    """
    overrides.setdefault("event_type", AuthEventType.PASSWORD_CHANGE)
    overrides.setdefault("ip_country", "GB")
    return record_auth_event(api, customer_id, device_id, **overrides)


def fail_challenge_then_reissue(
    api: Any, event_id: str, method: Optional[str] = None
) -> Dict[str, Any]:
    """One FAIL followed by one REISSUE, leaving the challenge back in ISSUED."""
    drive_challenge(api, event_id, ChallengeAction.FAIL)
    overrides = {"challenge_method": method} if method else {}
    return drive_challenge(api, event_id, ChallengeAction.REISSUE, **overrides)


# ---------------------------------------------------------------------------
# Chargebacks
# ---------------------------------------------------------------------------


def file_chargeback(
    api: Any,
    assessment_id: str,
    amount_cents: int,
    received_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_chargeback(
            create_chargeback_payload(
                assessment_id, amount_cents, received_at, **overrides
            ),
            ADMIN,
        )
    )


def transition_chargeback(
    api: Any, chargeback_id: str, action: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.transition_chargeback(
            chargeback_id, chargeback_transition_payload(action, **overrides), ADMIN
        )
    )


def read_chargeback(
    api: Any, chargeback_id: str, headers: Optional[Dict[str, str]] = None
):
    return get_success_data(api.get_chargeback(chargeback_id, headers or ADMIN))


def build_represented_chargeback(
    api: Any,
    assessment_id: str,
    amount_cents: int,
    received_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """File a dispute and move it ``RECEIVED -> REPRESENTED``."""
    chargeback = file_chargeback(
        api, assessment_id, amount_cents, received_at, **overrides
    )
    return transition_chargeback(
        api,
        chargeback["id"],
        ChargebackAction.REPRESENT,
        evidence_note="AVS match and device history attached",
    )


def build_lost_chargeback(
    api: Any,
    assessment_id: str,
    amount_cents: int,
    received_at: str,
    represent_first: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """Drive a dispute all the way to ``LOST``, running the five-link cascade."""
    chargeback = file_chargeback(
        api, assessment_id, amount_cents, received_at, **overrides
    )
    if represent_first:
        transition_chargeback(
            api, chargeback["id"], ChargebackAction.REPRESENT, evidence_note="Contested"
        )
    return transition_chargeback(api, chargeback["id"], ChargebackAction.LOSE)


def build_won_chargeback(
    api: Any,
    assessment_id: str,
    amount_cents: int,
    received_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Drive a dispute to ``WON`` through a successful representment."""
    represented = build_represented_chargeback(
        api, assessment_id, amount_cents, received_at, **overrides
    )
    return transition_chargeback(api, represented["id"], ChargebackAction.WIN)


# ===========================================================================
# Tier 4 — accumulation and threshold targeting
# ===========================================================================


def build_good_customer(
    api: Any,
    env: ScoringEnv,
    amount_cents: int = SMALL_ORDER_CENTS,
) -> List[Dict[str, Any]]:
    """Carry the environment's customer over the good-customer thresholds.

    Two approvals of 15,000 cents each take ``approved_count`` to 2 and
    ``lifetime_net_approved_cents`` to 30,000, clearing the minimum of 2
    approvals and 20,000 cents of net approved value.
    """
    return [
        build_approved_assessment(api, env, amount_cents),
        build_approved_assessment(api, env, amount_cents),
    ]


def build_velocity_burst(
    api: Any, env: ScoringEnv, count: int, **overrides: Any
) -> List[Dict[str, Any]]:
    """Open ``count`` sibling assessments without scoring them.

    State is deliberately not filtered by the one-hour customer velocity count,
    so assessments still sitting in ``PENDING_SIGNALS`` count as velocity.
    """
    return [open_assessment(api, env, **overrides) for _ in range(count)]


def build_training_corpus(
    api: Any,
    env: ScoringEnv,
    segments: Sequence[Tuple[str, str]],
    dispute_amount_cents: int = 5000,
    order_amount_cents: int = SMALL_ORDER_CENTS,
) -> List[Dict[str, Any]]:
    """Produce one LOST dispute per ``(reason_code, received_at)`` pair.

    Each dispute is filed against its own approved order so that the ledger
    reversal of a lost fraud dispute fires once per order rather than being
    swallowed by the idempotence guard.
    """
    disputes: List[Dict[str, Any]] = []
    for reason_code, received_at in segments:
        approved = build_approved_assessment(api, env, order_amount_cents)
        disputes.append(
            build_lost_chargeback(
                api,
                approved["id"],
                dispute_amount_cents,
                received_at,
                represent_first=False,
                reason_code=reason_code,
            )
        )
    return disputes


def build_fraud_segment_corpus(
    api: Any,
    env: ScoringEnv,
    cnp_received_at: Sequence[str],
    ato_received_at: Sequence[str],
    dispute_amount_cents: int = 5000,
) -> List[Dict[str, Any]]:
    """A corpus with the named ``FRAUD_CNP`` and ``FRAUD_ATO`` receipt instants."""
    segments: List[Tuple[str, str]] = [
        (ChargebackReasonCode.FRAUD_CNP, instant) for instant in cnp_received_at
    ]
    segments += [
        (ChargebackReasonCode.FRAUD_ATO, instant) for instant in ato_received_at
    ]
    return build_training_corpus(api, env, segments, dispute_amount_cents)


def build_device_at_reputation(
    api: Any, env: ScoringEnv, approvals: int, amount_cents: int = STANDARD_ORDER_CENTS
) -> List[Dict[str, Any]]:
    """Score ``approvals`` approved orders onto the environment's device."""
    return [
        build_approved_assessment(api, env, amount_cents) for _ in range(approvals)
    ]


# ===========================================================================
# Tier 5 — finalisation and terminal states
# ===========================================================================


def contain_customer_via_blocked_event(
    api: Any, customer_id: str, device_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Drive a customer to ``CONTAINED`` through a ``BLOCKED`` event.

    A ``PAYMENT_INSTRUMENT_ADD`` base of 35.00, a foreign-IP geography term of
    25.00 and a first-seen device term of 20.00 sum to 80.00, which is at or
    above the 75.00 block floor.
    """
    overrides.setdefault("event_type", AuthEventType.PAYMENT_INSTRUMENT_ADD)
    overrides.setdefault("ip_country", "GB")
    return record_auth_event(api, customer_id, device_id, **overrides)


def contain_customer_via_third_failure(
    api: Any, customer_id: str, device_id: str
) -> Dict[str, Any]:
    """Drive a customer to ``CONTAINED`` through the third challenge failure.

    Two FAIL/REISSUE rounds leave ``challenge_attempts`` at 2 with the challenge
    back in ``ISSUED``; the third failure carries it to the attempt budget of 3,
    which is the first link of the containment chain.
    """
    event = build_step_up_event(api, customer_id, device_id)
    fail_challenge_then_reissue(api, event["id"])
    fail_challenge_then_reissue(api, event["id"])
    return drive_challenge(api, event["id"], ChallengeAction.FAIL)


def retire_active_model_by_promoting_successor(api: Any) -> Dict[str, Any]:
    """Publish and promote a second cold-start model, retiring the incumbent."""
    successor = draft_risk_model(api)
    model_action(api, successor["id"], RiskModelAction.PUBLISH_SHADOW)
    return model_action(api, successor["id"], RiskModelAction.PROMOTE)


def retire_active_pack_by_activating_successor(
    api: Any,
    effective_from: str,
    effective_until: str,
    rules: Sequence[Dict[str, Any]] = REFERENCE_RULES,
    **pack_overrides: Any,
) -> Dict[str, Any]:
    """Activate a later pack whose window retires the incumbent by cascade."""
    return build_active_rule_pack(
        api,
        rules,
        effective_from=effective_from,
        effective_until=effective_until,
        **pack_overrides,
    )


__all__ = [
    "ADMIN",
    "CHECKOUT",
    "ENGINEER",
    "ENGINEER_APPROVER",
    "REFERENCE_RULES",
    "REFERENCE_RULES_WITH_HARD_DECLINE",
    "ExceptionSetup",
    "Roster",
    "ScoringEnv",
    "ShopperTriple",
    "StaffedCase",
    "activate_rule_pack",
    "add_rule",
    "add_rule_payload",
    "approve_exception",
    "assign_case",
    "assign_case_to",
    "auto_assign_case",
    "build_active_risk_model",
    "build_active_rule_pack",
    "build_approved_assessment",
    "build_approved_exception",
    "build_behavioral_roster",
    "build_device_at_reputation",
    "build_draft_rule_pack",
    "build_fraud_segment_corpus",
    "build_good_customer",
    "build_lead",
    "build_lost_chargeback",
    "build_represented_chargeback",
    "build_reviewed_assessment",
    "build_roster",
    "build_scoring_env",
    "build_scoring_env_with_hard_decline_rule",
    "build_shopper_triple",
    "build_staffed_case",
    "build_step_up_event",
    "build_training_corpus",
    "build_velocity_burst",
    "build_won_chargeback",
    "contain_customer_via_blocked_event",
    "contain_customer_via_third_failure",
    "create_address",
    "create_analyst",
    "create_business_customer",
    "create_customer",
    "create_device",
    "create_emulator_device",
    "create_high_value_customer",
    "decide_exception",
    "draft_risk_model",
    "draft_rule_pack",
    "drive_challenge",
    "escalate_case",
    "fail_challenge_then_reissue",
    "file_chargeback",
    "find_case_for_assessment",
    "list_cases_for_assessment",
    "lock_customer",
    "model_action",
    "move_analyst_off_shift",
    "open_and_score",
    "open_assessment",
    "read_address",
    "read_analyst",
    "read_assessment",
    "read_auth_event",
    "read_case",
    "read_chargeback",
    "read_customer",
    "read_device",
    "read_risk_model",
    "read_rule_pack",
    "record_auth_event",
    "request_address_whitelist_exception",
    "request_exception",
    "resolve_case_as_analyst",
    "resolve_case_as_lead",
    "retire_active_model_by_promoting_successor",
    "retire_active_pack_by_activating_successor",
    "score_assessment",
    "set_analyst_status",
    "set_clock",
    "transition_chargeback",
    "unlock_customer",
]

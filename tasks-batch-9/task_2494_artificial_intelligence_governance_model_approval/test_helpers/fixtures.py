"""Composite setup helpers.

The harness restarts the API server with an empty database before every single
test, so nothing here may assume pre-existing data: each helper drives the API
through the PRD's own endpoints from scratch.

The module is layered:

* **Primitives** — one helper per single state transition, each of which reads the
  parent's current ``version`` back rather than guessing it, so a caller never has
  to track optimistic-concurrency counters by hand.
* **Named chains** — the multi-step governance positions the suite reuses, each
  returning a :class:`Chain` carrying every record it created.

Every helper uses ``get_success_data`` for setup calls: a setup step that fails
should raise a clear error about the setup, not a confusing assertion about the
behaviour under test.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import ApiClient
from .constants import DEFAULT_CLOCK, REQUIRED_METRIC_NAME
from .factories import (
    ASSESSMENT_GRADE_B,
    ASSESSMENT_GRADE_C,
    FIRST_PARTY_ASSET,
    FORCED_PROHIBITED_USE_CASE,
    HIGH_USE_CASE,
    LIMITED_EU_USE_CASE,
    LIMITED_USE_CASE,
    MINIMAL_USE_CASE,
    THIRD_PARTY_ASSET_NIMBUS,
    THIRD_PARTY_ASSET_NORTHWIND,
    approval_payload,
    assessment_decision_payload,
    classify_payload,
    conditions,
    design_decision_payload,
    disclosure_notice_payload,
    evaluation_completion_payload,
    evaluation_schedule_payload,
    issue_conditions_payload,
    model_binding_payload,
    monitoring_incident_payload,
    oversight_design_payload,
    plus_days,
    revocation_payload,
    shadow_deployment_payload,
    use_case_payload,
    vendor_assessment_payload,
)
from .test_users import (
    GATE_REVIEWER_HEADERS,
    OFFICER,
    REQUESTER,
    SECURITY_REVIEWER,
)


@dataclass
class Chain:
    """Everything a composite setup helper built, addressable by name."""

    use_case: dict[str, Any] = field(default_factory=dict)
    asset: dict[str, Any] = field(default_factory=dict)
    assessment: Optional[dict[str, Any]] = None
    binding: Optional[dict[str, Any]] = None
    design: Optional[dict[str, Any]] = None
    gates: dict[str, dict[str, Any]] = field(default_factory=dict)
    evaluations: dict[str, dict[str, Any]] = field(default_factory=dict)
    notices: dict[str, dict[str, Any]] = field(default_factory=dict)
    incidents: list[dict[str, Any]] = field(default_factory=list)
    shadows: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def use_case_id(self) -> str:
        return self.use_case["id"]

    @property
    def asset_id(self) -> str:
        return self.asset["id"]

    @property
    def binding_id(self) -> str:
        assert self.binding is not None, "this chain built no model binding"
        return self.binding["id"]

    @property
    def design_id(self) -> str:
        assert self.design is not None, "this chain built no oversight design"
        return self.design["id"]

    @property
    def assessment_id(self) -> str:
        assert self.assessment is not None, "this chain built no vendor assessment"
        return self.assessment["id"]

    def gate_id(self, gate_type: str) -> str:
        return self.gates[gate_type]["id"]

    def evaluation_id(self, eval_type: str) -> str:
        return self.evaluations[eval_type]["id"]

    def notice_id(self, jurisdiction: str) -> str:
        return self.notices[jurisdiction]["id"]


# ─── Clock primitives (PRD §2.5) ───────────────────────────────────────────


def pin_clock(api: ApiClient, instant: str = DEFAULT_CLOCK) -> str:
    """Pin the logical clock explicitly, so a recipe never depends on the default."""
    get_success_data(api.set_clock(instant, headers=OFFICER))
    return instant


def move_clock(api: ApiClient, instant: str) -> str:
    """Advance the logical clock. Moving the clock performs no transitions itself."""
    get_success_data(api.set_clock(instant, headers=OFFICER))
    return instant


# ─── Read-back primitives ──────────────────────────────────────────────────


def read_use_case(api: ApiClient, use_case_id: str) -> dict[str, Any]:
    return get_success_data(api.get_use_case(use_case_id, headers=OFFICER))


def read_asset(api: ApiClient, asset_id: str) -> dict[str, Any]:
    return get_success_data(api.get_model_asset(asset_id, headers=OFFICER))


def read_evaluation(api: ApiClient, evaluation_id: str) -> dict[str, Any]:
    return get_success_data(api.get_test_evaluation(evaluation_id, headers=OFFICER))


def read_incident(api: ApiClient, incident_id: str) -> dict[str, Any]:
    return get_success_data(api.get_monitoring_incident(incident_id, headers=OFFICER))


def read_shadow(api: ApiClient, shadow_id: str) -> dict[str, Any]:
    return get_success_data(api.get_shadow_deployment(shadow_id, headers=OFFICER))


def read_summary(api: ApiClient, **params: Any) -> dict[str, Any]:
    return get_success_data(api.get_inventory_summary(headers=OFFICER, **params))


def current_version(api: ApiClient, use_case_id: str) -> int:
    """The use case's current version, for the four operations that pin it."""
    return read_use_case(api, use_case_id)["version"]


def list_gates(api: ApiClient, use_case_id: str) -> list[dict[str, Any]]:
    records, _ = validate_paginated(api.list_review_gates(use_case_id, headers=OFFICER))
    return records


def gates_by_type(api: ApiClient, use_case_id: str) -> dict[str, dict[str, Any]]:
    return {gate["gate_type"]: gate for gate in list_gates(api, use_case_id)}


def list_bindings(api: ApiClient, use_case_id: str) -> list[dict[str, Any]]:
    records, _ = validate_paginated(
        api.list_model_bindings(use_case_id, headers=OFFICER)
    )
    return records


def list_ledger(api: ApiClient, use_case_id: str, **params: Any) -> list[dict[str, Any]]:
    records, _ = validate_paginated(
        api.list_ledger_entries(use_case_id, headers=OFFICER, **params)
    )
    return records


def list_snapshots(api: ApiClient, use_case_id: str, **params: Any) -> list[dict[str, Any]]:
    records, _ = validate_paginated(
        api.list_classification_snapshots(use_case_id, headers=OFFICER, **params)
    )
    return records


def list_notices(api: ApiClient, use_case_id: str, **params: Any) -> list[dict[str, Any]]:
    records, _ = validate_paginated(
        api.list_disclosure_notices(use_case_id, headers=OFFICER, **params)
    )
    return records


def list_evaluations(api: ApiClient, **params: Any) -> list[dict[str, Any]]:
    records, _ = validate_paginated(api.list_test_evaluations(headers=OFFICER, **params))
    return records


def list_assessments(api: ApiClient, asset_id: str, **params: Any) -> list[dict[str, Any]]:
    records, _ = validate_paginated(
        api.list_vendor_assessments(asset_id, headers=OFFICER, **params)
    )
    return records


# ─── Tier 1: single-transition primitives ──────────────────────────────────


def register_asset(
    api: ApiClient, payload: Optional[dict] = None
) -> dict[str, Any]:
    """Register a model asset. It lands in REGISTERED with no vendor grade."""
    return get_success_data(
        api.create_model_asset(payload or dict(FIRST_PARTY_ASSET), headers=OFFICER),
        expected_status=201,
    )


def submit_assessment(
    api: ApiClient, asset_id: str, payload: Optional[dict] = None
) -> dict[str, Any]:
    """File a vendor assessment. It is graded immediately under the conservative variant."""
    return get_success_data(
        api.create_vendor_assessment(
            asset_id, payload or vendor_assessment_payload(), headers=OFFICER
        ),
        expected_status=201,
    )


def decide_assessment(
    api: ApiClient,
    assessment_id: str,
    decision: str,
    terms_variant: str,
    headers: Optional[dict] = None,
) -> dict[str, Any]:
    return get_success_data(
        api.decide_vendor_assessment(
            assessment_id,
            assessment_decision_payload(decision, terms_variant),
            headers=headers or OFFICER,
        )
    )


def approve_asset(api: ApiClient, asset_id: str) -> dict[str, Any]:
    """Clear an asset for binding. This bumps the asset's version."""
    return get_success_data(api.approve_asset_for_use(asset_id, headers=OFFICER))


def ready_asset(
    api: ApiClient,
    asset_payload: Optional[dict] = None,
    assessment_payload: Optional[dict] = None,
    terms_variant: str = "DOCUMENTED_TERMS",
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """Register an asset, accept its terms when third-party, and clear it for use.

    Returns the asset as APPROVED_FOR_USE plus the accepted assessment, if any.
    """
    asset = register_asset(api, asset_payload)
    assessment = None
    if asset["is_third_party"]:
        assessment = submit_assessment(
            api, asset["id"], assessment_payload or ASSESSMENT_GRADE_B
        )
        assessment = decide_assessment(
            api, assessment["id"], "ACCEPT", terms_variant
        )
    asset = approve_asset(api, asset["id"])
    return asset, assessment


def file_use_case(
    api: ApiClient, payload: Optional[dict] = None, headers: Optional[dict] = None
) -> dict[str, Any]:
    """File an intake. It lands in DRAFT carrying no risk tier."""
    return get_success_data(
        api.create_use_case(payload or use_case_payload(), headers=headers or REQUESTER),
        expected_status=201,
    )


def classify(api: ApiClient, use_case_id: str) -> dict[str, Any]:
    """Run classification against the use case's current version."""
    return get_success_data(
        api.classify_use_case(
            use_case_id,
            classify_payload(current_version(api, use_case_id)),
            headers=OFFICER,
        )
    )


def classified_use_case(
    api: ApiClient, payload: Optional[dict] = None
) -> dict[str, Any]:
    """File an intake and classify it in one step."""
    use_case = file_use_case(api, payload)
    return classify(api, use_case["id"])


def create_binding(
    api: ApiClient, use_case_id: str, asset_id: str
) -> dict[str, Any]:
    """Pin an approved asset to the use case at the asset's current version."""
    return get_success_data(
        api.create_model_binding(
            use_case_id,
            model_binding_payload(asset_id, current_version(api, use_case_id)),
            headers=OFFICER,
        ),
        expected_status=201,
    )


def schedule_evaluation(
    api: ApiClient,
    binding_id: str,
    eval_type: str,
    window_start_at: str,
    window_end_at: str,
    use_case_id: Optional[str] = None,
    headers: Optional[dict] = None,
) -> dict[str, Any]:
    """Reserve an exclusive test window on the bound asset, freezing thresholds."""
    return get_success_data(
        api.create_test_evaluation(
            evaluation_schedule_payload(
                binding_id, eval_type, window_start_at, window_end_at, use_case_id
            ),
            headers=headers or SECURITY_REVIEWER,
        ),
        expected_status=201,
    )


def complete_evaluation(
    api: ApiClient,
    evaluation_id: str,
    metric_value: float,
    sample_size: int,
    eval_type: Optional[str] = None,
    headers: Optional[dict] = None,
) -> dict[str, Any]:
    """Record a run's results; the frozen profile decides PASSED or FAILED.

    The metric key is read back off the scheduled row when ``eval_type`` is not
    supplied, so the body always names the field the profile designated.
    """
    if eval_type is None:
        metric_name = read_evaluation(api, evaluation_id)["required_metric_name"]
    else:
        metric_name = REQUIRED_METRIC_NAME[eval_type]
    return get_success_data(
        api.complete_test_evaluation(
            evaluation_id,
            evaluation_completion_payload(
                metric_value, sample_size, metric_name=metric_name
            ),
            headers=headers or SECURITY_REVIEWER,
        )
    )


def run_evaluation(
    api: ApiClient,
    binding_id: str,
    eval_type: str,
    window_start_at: str,
    window_end_at: str,
    metric_value: float,
    sample_size: int,
    use_case_id: Optional[str] = None,
) -> dict[str, Any]:
    """Schedule and immediately complete one evaluation."""
    scheduled = schedule_evaluation(
        api, binding_id, eval_type, window_start_at, window_end_at, use_case_id
    )
    return complete_evaluation(
        api, scheduled["id"], metric_value, sample_size, eval_type
    )


def file_design(
    api: ApiClient, use_case_id: str, **overrides: Any
) -> dict[str, Any]:
    """File the oversight design; adequacy is scored on filing."""
    return get_success_data(
        api.create_oversight_design(
            use_case_id,
            oversight_design_payload(current_version(api, use_case_id), **overrides),
            headers=REQUESTER,
        ),
        expected_status=201,
    )


def decide_design(
    api: ApiClient, design_id: str, decision: str = "APPROVE"
) -> dict[str, Any]:
    return get_success_data(
        api.decide_oversight_design(
            design_id, design_decision_payload(decision), headers=OFFICER
        )
    )


def approved_design(api: ApiClient, use_case_id: str, **overrides: Any) -> dict[str, Any]:
    """File a design and approve it."""
    design = file_design(api, use_case_id, **overrides)
    return decide_design(api, design["id"], "APPROVE")


def publish_notice(
    api: ApiClient,
    use_case_id: str,
    jurisdiction: str,
    notice_type: str = "AUTOMATED_DECISION_NOTICE",
    effective_from: str = DEFAULT_CLOCK,
    effective_to: str = "2027-12-31T00:00:00Z",
    headers: Optional[dict] = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Publish a notice whose closed window is in force at the default clock."""
    return get_success_data(
        api.create_disclosure_notice(
            use_case_id,
            disclosure_notice_payload(
                notice_type, jurisdiction, effective_from, effective_to, **overrides
            ),
            headers=headers or REQUESTER,
        ),
        expected_status=201,
    )


def take_up_gate(api: ApiClient, gate_id: str, gate_type: str) -> dict[str, Any]:
    """Take a gate up for review, acting as the reviewer role that owns it."""
    return get_success_data(
        api.start_gate_review(gate_id, headers=GATE_REVIEWER_HEADERS[gate_type])
    )


def issue_conditions(
    api: ApiClient, gate_id: str, gate_type: str, condition_count: int
) -> dict[str, Any]:
    """Issue ``condition_count`` conditions on a gate that is under review."""
    return get_success_data(
        api.issue_gate_conditions(
            gate_id,
            issue_conditions_payload(conditions(condition_count)),
            headers=GATE_REVIEWER_HEADERS[gate_type],
        )
    )


def clear_gate(
    api: ApiClient, gate_id: str, gate_type: str, headers: Optional[dict] = None
) -> dict[str, Any]:
    """Clear a gate, acting as the reviewer role that owns it."""
    return get_success_data(
        api.clear_gate(gate_id, headers=headers or GATE_REVIEWER_HEADERS[gate_type])
    )


def take_up_and_clear(
    api: ApiClient, gate_id: str, gate_type: str
) -> dict[str, Any]:
    """Take a gate up and clear it in one step."""
    take_up_gate(api, gate_id, gate_type)
    return clear_gate(api, gate_id, gate_type)


def clear_all_gates(api: ApiClient, use_case_id: str) -> dict[str, dict[str, Any]]:
    """Take up and clear every gate the classification opened, in canonical order."""
    cleared: dict[str, dict[str, Any]] = {}
    for gate in list_gates(api, use_case_id):
        cleared[gate["gate_type"]] = take_up_and_clear(
            api, gate["id"], gate["gate_type"]
        )
    return cleared


def approve_use_case(
    api: ApiClient, use_case_id: str, headers: Optional[dict] = None
) -> dict[str, Any]:
    """Sign the deployment approval against the use case's current version."""
    return get_success_data(
        api.approve_use_case(
            use_case_id,
            approval_payload(current_version(api, use_case_id)),
            headers=headers or OFFICER,
        )
    )


def revoke_use_case(api: ApiClient, use_case_id: str) -> dict[str, Any]:
    """Revoke a use case. PRD §3.8 makes the revocation take a free-text
    ``revocation_reason``, so the body must carry one."""
    return get_success_data(
        api.revoke_use_case(use_case_id, revocation_payload(), headers=OFFICER)
    )


def report_incident(
    api: ApiClient,
    use_case_id: str,
    severity: str,
    detected_at: Optional[str] = None,
    headers: Optional[dict] = None,
    **overrides: Any,
) -> dict[str, Any]:
    return get_success_data(
        api.create_monitoring_incident(
            monitoring_incident_payload(
                use_case_id, severity, detected_at, **overrides
            ),
            headers=headers or OFFICER,
        ),
        expected_status=201,
    )


def discover_shadow(
    api: ApiClient,
    asset_id: str,
    environment: str = "SANDBOX",
    discovered_at: Optional[str] = None,
    **overrides: Any,
) -> dict[str, Any]:
    return get_success_data(
        api.create_shadow_deployment(
            shadow_deployment_payload(
                asset_id, environment, discovered_at, **overrides
            ),
            headers=OFFICER,
        ),
        expected_status=201,
    )


def run_sweep(api: ApiClient) -> dict[str, Any]:
    return get_success_data(api.run_governance_sweep(headers=OFFICER))


# ─── Tier 2/3: named governance chains ─────────────────────────────────────

# The evaluation windows below are laid out back to back. Windows are half-open,
# so a window that starts exactly where the previous one ended does not conflict.
EVAL_WINDOWS = {
    "BIAS": ("2026-08-02T00:00:00Z", "2026-08-03T00:00:00Z"),
    "ROBUSTNESS": ("2026-08-03T00:00:00Z", "2026-08-04T00:00:00Z"),
    "HALLUCINATION": ("2026-08-04T00:00:00Z", "2026-08-05T00:00:00Z"),
    "SECURITY_REDTEAM": ("2026-08-05T00:00:00Z", "2026-08-06T00:00:00Z"),
}

# Metric values that clear the HIGH-tier profile (0.80 / 0.90 / 0.95 / 0.95) with
# the HIGH-tier sample size of 1000.
HIGH_PASSING_RUNS = {
    "BIAS": (0.8500, 1000),
    "ROBUSTNESS": (0.9200, 1000),
    "HALLUCINATION": (0.9600, 1000),
    "SECURITY_REDTEAM": (0.9600, 1000),
}

# A metric value and sample size that clear the LIMITED-tier BIAS profile
# (0.70 threshold, 300 samples).
LIMITED_PASSING_BIAS = (0.8500, 500)


def minimal_use_case_under_review(api: ApiClient) -> Chain:
    """A MINIMAL-tier use case classified into review, so only BUSINESS is open."""
    pin_clock(api)
    asset, _ = ready_asset(api)
    use_case = classified_use_case(api, MINIMAL_USE_CASE)
    return Chain(
        use_case=use_case, asset=asset, gates=gates_by_type(api, use_case["id"])
    )


def minimal_approved_use_case(api: ApiClient) -> Chain:
    """A MINIMAL-tier use case carried all the way to APPROVED.

    MINIMAL demands no evaluations, so the control credit comes from the single
    cleared BUSINESS gate alone.
    """
    chain = minimal_use_case_under_review(api)
    chain.binding = create_binding(api, chain.use_case_id, chain.asset_id)
    chain.design = approved_design(api, chain.use_case_id)
    chain.gates = clear_all_gates(api, chain.use_case_id)
    chain.use_case = approve_use_case(api, chain.use_case_id)
    chain.asset = read_asset(api, chain.asset_id)
    return chain


def limited_use_case_under_review(
    api: ApiClient, use_case_payload_override: Optional[dict] = None
) -> Chain:
    """A LIMITED-tier use case classified into review, with PRIVACY and BUSINESS open."""
    pin_clock(api)
    asset, _ = ready_asset(api)
    use_case = classified_use_case(api, use_case_payload_override or LIMITED_USE_CASE)
    return Chain(
        use_case=use_case, asset=asset, gates=gates_by_type(api, use_case["id"])
    )


def limited_use_case_with_binding(api: ApiClient) -> Chain:
    """A LIMITED-tier use case under review with one PINNED binding."""
    chain = limited_use_case_under_review(api)
    chain.binding = create_binding(api, chain.use_case_id, chain.asset_id)
    chain.use_case = read_use_case(api, chain.use_case_id)
    return chain


def limited_approved_use_case(api: ApiClient) -> Chain:
    """A LIMITED-tier use case carried all the way to APPROVED.

    LIMITED demands a passing BIAS run, so the chain schedules and completes one
    before clearing the two gates the tier opened.
    """
    chain = limited_use_case_with_binding(api)
    value, samples = LIMITED_PASSING_BIAS
    start, end = EVAL_WINDOWS["BIAS"]
    chain.evaluations["BIAS"] = run_evaluation(
        api, chain.binding_id, "BIAS", start, end, value, samples, chain.use_case_id
    )
    chain.design = approved_design(api, chain.use_case_id)
    chain.gates = clear_all_gates(api, chain.use_case_id)
    chain.use_case = approve_use_case(api, chain.use_case_id)
    chain.asset = read_asset(api, chain.asset_id)
    return chain


def high_tier_use_case_under_review(
    api: ApiClient,
    use_case_payload_override: Optional[dict] = None,
    asset_payload: Optional[dict] = None,
    assessment_payload: Optional[dict] = None,
) -> Chain:
    """A HIGH-tier use case classified into review, with all four gates open.

    The asset is third-party by default so that the LEGAL gate has accepted vendor
    terms to consult and the approval has a vendor penalty to apply.
    """
    pin_clock(api)
    asset, assessment = ready_asset(
        api,
        asset_payload or THIRD_PARTY_ASSET_NIMBUS,
        assessment_payload or ASSESSMENT_GRADE_B,
    )
    use_case = classified_use_case(api, use_case_payload_override or HIGH_USE_CASE)
    return Chain(
        use_case=use_case,
        asset=asset,
        assessment=assessment,
        gates=gates_by_type(api, use_case["id"]),
    )


def high_tier_use_case_with_evidence(
    api: ApiClient,
    use_case_payload_override: Optional[dict] = None,
    asset_payload: Optional[dict] = None,
    assessment_payload: Optional[dict] = None,
) -> Chain:
    """A HIGH-tier use case with its binding, notices, four passing runs and design.

    This is everything the four gates and the approval need, stopping short of
    clearing any gate, so a caller can drive the gate stage itself.
    """
    chain = high_tier_use_case_under_review(
        api, use_case_payload_override, asset_payload, assessment_payload
    )
    chain.binding = create_binding(api, chain.use_case_id, chain.asset_id)
    for jurisdiction in chain.use_case["jurisdictions"]:
        chain.notices[jurisdiction] = publish_notice(
            api, chain.use_case_id, jurisdiction
        )
    for eval_type, (value, samples) in HIGH_PASSING_RUNS.items():
        start, end = EVAL_WINDOWS[eval_type]
        chain.evaluations[eval_type] = run_evaluation(
            api,
            chain.binding_id,
            eval_type,
            start,
            end,
            value,
            samples,
            chain.use_case_id,
        )
    chain.design = approved_design(api, chain.use_case_id)
    chain.use_case = read_use_case(api, chain.use_case_id)
    return chain


def high_tier_use_case_ready_for_approval(
    api: ApiClient,
    use_case_payload_override: Optional[dict] = None,
    asset_payload: Optional[dict] = None,
    assessment_payload: Optional[dict] = None,
) -> Chain:
    """A HIGH-tier use case whose four gates are all cleared."""
    chain = high_tier_use_case_with_evidence(
        api, use_case_payload_override, asset_payload, assessment_payload
    )
    chain.gates = clear_all_gates(api, chain.use_case_id)
    chain.use_case = read_use_case(api, chain.use_case_id)
    return chain


def high_tier_approved_use_case(
    api: ApiClient,
    use_case_payload_override: Optional[dict] = None,
    asset_payload: Optional[dict] = None,
    assessment_payload: Optional[dict] = None,
) -> Chain:
    """A HIGH-tier use case carried all the way to APPROVED.

    Four cleared gates and four passing runs earn more credit than the cap allows,
    which is what makes this chain useful for probing the cap.
    """
    chain = high_tier_use_case_ready_for_approval(
        api, use_case_payload_override, asset_payload, assessment_payload
    )
    chain.use_case = approve_use_case(api, chain.use_case_id)
    chain.asset = read_asset(api, chain.asset_id)
    chain.binding = list_bindings(api, chain.use_case_id)[0]
    return chain


# ─── Tier 4: accumulation and threshold targeting ──────────────────────────


def high_tier_with_conditions_on_every_gate(api: ApiClient) -> Chain:
    """A HIGH-tier use case holding two LEGAL conditions and one on each other gate.

    This is the spread that separates rounding each gate's debt before summing
    from summing the raw products and rounding once.
    """
    chain = high_tier_use_case_under_review(api)
    condition_counts = {"LEGAL": 2, "PRIVACY": 1, "SECURITY": 1, "BUSINESS": 1}
    for gate_type in ["LEGAL", "PRIVACY", "SECURITY", "BUSINESS"]:
        gate = chain.gates[gate_type]
        take_up_gate(api, gate["id"], gate_type)
        chain.gates[gate_type] = issue_conditions(
            api, gate["id"], gate_type, condition_counts[gate_type]
        )
    chain.use_case = read_use_case(api, chain.use_case_id)
    chain.extra["condition_counts"] = condition_counts
    return chain


def high_tier_with_legal_conditions(api: ApiClient, condition_count: int = 2) -> Chain:
    """A HIGH-tier use case whose LEGAL gate alone carries booked control debt."""
    chain = high_tier_use_case_under_review(api)
    gate = chain.gates["LEGAL"]
    take_up_gate(api, gate["id"], "LEGAL")
    chain.gates["LEGAL"] = issue_conditions(api, gate["id"], "LEGAL", condition_count)
    chain.use_case = read_use_case(api, chain.use_case_id)
    return chain


def limited_use_case_with_privacy_conditions(
    api: ApiClient, condition_count: int = 2
) -> Chain:
    """A LIMITED-tier use case whose PRIVACY gate has been sent back with conditions."""
    chain = limited_use_case_under_review(api)
    gate = chain.gates["PRIVACY"]
    take_up_gate(api, gate["id"], "PRIVACY")
    chain.gates["PRIVACY"] = issue_conditions(
        api, gate["id"], "PRIVACY", condition_count
    )
    chain.use_case = read_use_case(api, chain.use_case_id)
    return chain


def shared_asset_two_bound_use_cases(api: ApiClient) -> Chain:
    """One approved asset with two LIMITED use cases each holding a PINNED binding.

    Test windows are reserved on the *asset*, not the binding, so two bindings on
    one asset compete for the same windows.
    """
    pin_clock(api)
    asset, _ = ready_asset(api)
    first = classified_use_case(api, LIMITED_USE_CASE)
    binding_a = create_binding(api, first["id"], asset["id"])
    second = classified_use_case(
        api,
        use_case_payload(
            title="Knowledge base answer drafter",
            business_unit="Support",
            description="drafts knowledge base answers for agent review",
        ),
    )
    binding_b = create_binding(api, second["id"], asset["id"])
    chain = Chain(use_case=read_use_case(api, first["id"]), asset=asset)
    chain.binding = binding_a
    chain.extra["second_use_case"] = read_use_case(api, second["id"])
    chain.extra["binding_b"] = binding_b
    return chain


def use_case_with_eu_notice(api: ApiClient) -> Chain:
    """A LIMITED-tier EU use case with an EU notice already published and in force."""
    chain = limited_use_case_under_review(api, LIMITED_EU_USE_CASE)
    chain.binding = create_binding(api, chain.use_case_id, chain.asset_id)
    chain.notices["EU"] = publish_notice(api, chain.use_case_id, "EU")
    chain.use_case = read_use_case(api, chain.use_case_id)
    return chain


def use_case_with_september_eu_notice_window(api: ApiClient) -> Chain:
    """A use case with one published EU notice occupying all of September 2026.

    The window is closed at both ends and carries a seven-day quiet buffer after
    it, which is what a successor window has to clear.
    """
    pin_clock(api)
    use_case = file_use_case(api, LIMITED_EU_USE_CASE)
    notice = publish_notice(
        api,
        use_case["id"],
        "EU",
        notice_type="AUTOMATED_DECISION_NOTICE",
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-09-30T00:00:00Z",
    )
    chain = Chain(use_case=read_use_case(api, use_case["id"]))
    chain.notices["EU"] = notice
    return chain


def exactly_seventy_high_use_case(api: ApiClient) -> Chain:
    """A use case whose additive score lands exactly on the HIGH band's floor.

    40 impact + 18 autonomy + 6 sensitivity + 6 reach + 0 jurisdiction points, so
    the frozen evaluation profile is the HIGH one.
    """
    payload = use_case_payload(
        title="Workforce reduction impact scorer",
        business_unit="HR",
        description="scores workforce reduction impact for a review panel",
        affects_individuals=True,
        decision_autonomy="HUMAN_ON_LOOP",
        data_sensitivity="INTERNAL",
        individual_impact="CONSEQUENTIAL",
        jurisdictions=[],
        deployed_headcount_reach=100000,
    )
    chain = high_tier_use_case_under_review(api, payload, FIRST_PARTY_ASSET)
    chain.binding = create_binding(api, chain.use_case_id, chain.asset_id)
    chain.use_case = read_use_case(api, chain.use_case_id)
    return chain


def high_tier_grade_c_large_reach(api: ApiClient) -> Chain:
    """A HIGH-tier use case whose reach alone exceeds the portfolio cap.

    40 impact + 30 autonomy + 6 sensitivity + 6 reach = 82, bound to a grade-C
    third-party asset so the vendor penalty is 12.
    """
    payload = use_case_payload(
        title="Automated claims adjudication",
        business_unit="Claims",
        description="adjudicates routine claims and routes exceptions to an adjuster",
        affects_individuals=True,
        decision_autonomy="FULLY_AUTOMATED",
        data_sensitivity="INTERNAL",
        individual_impact="CONSEQUENTIAL",
        jurisdictions=[],
        deployed_headcount_reach=300000,
    )
    chain = high_tier_use_case_under_review(
        api, payload, THIRD_PARTY_ASSET_NORTHWIND, ASSESSMENT_GRADE_C
    )
    chain.binding = create_binding(api, chain.use_case_id, chain.asset_id)
    chain.design = approved_design(api, chain.use_case_id)
    chain.use_case = read_use_case(api, chain.use_case_id)
    return chain


# ─── Tier 5: finalization and terminal states ──────────────────────────────


def prohibited_rejected_use_case(api: ApiClient) -> Chain:
    """A use case rejected outright by the prohibited conjunction, hence terminal."""
    pin_clock(api)
    use_case = classified_use_case(api, FORCED_PROHIBITED_USE_CASE)
    return Chain(use_case=use_case, gates=gates_by_type(api, use_case["id"]))


def suspended_use_case_via_sev1(api: ApiClient) -> Chain:
    """An APPROVED LIMITED use case suspended by a SEV1 incident report.

    The report impairs the posture, which suspends the approval and stales the
    binding without touching the asset's own status.
    """
    chain = limited_approved_use_case(api)
    chain.incidents.append(report_incident(api, chain.use_case_id, "SEV1"))
    chain.use_case = read_use_case(api, chain.use_case_id)
    chain.asset = read_asset(api, chain.asset_id)
    chain.binding = list_bindings(api, chain.use_case_id)[0]
    return chain


def revoked_use_case_after_high_approval(api: ApiClient) -> Chain:
    """A HIGH-tier approval driven all the way through revocation.

    Revocation runs the four-hop cascade: binding, asset, vendor assessment, and
    the published notices.
    """
    chain = high_tier_approved_use_case(api)
    chain.use_case = revoke_use_case(api, chain.use_case_id)
    chain.asset = read_asset(api, chain.asset_id)
    chain.binding = list_bindings(api, chain.use_case_id)[0]
    return chain


def use_case_under_reassessment(api: ApiClient) -> Chain:
    """A MINIMAL approval whose reassessment cycle the sweep has opened.

    The clock is moved to the exact reassessment due instant, which the sweep
    treats inclusively.
    """
    chain = minimal_approved_use_case(api)
    due_at = chain.use_case["reassessment_due_at"]
    move_clock(api, due_at)
    chain.extra["sweep"] = run_sweep(api)
    chain.use_case = read_use_case(api, chain.use_case_id)
    return chain


def shadow_deployment_past_grace(
    api: ApiClient, environment: str = "SANDBOX"
) -> Chain:
    """A discovered shadow deployment whose grace period has already elapsed."""
    pin_clock(api)
    asset, _ = ready_asset(api)
    shadow = discover_shadow(api, asset["id"], environment)
    move_clock(api, plus_days(shadow["grace_deadline_at"], 1))
    chain = Chain(asset=asset)
    chain.shadows.append(read_shadow(api, shadow["id"]))
    return chain


def approved_use_case_with_matching_shadow(api: ApiClient) -> Chain:
    """An APPROVED use case plus a shadow deployment on the very asset it pins."""
    chain = limited_approved_use_case(api)
    chain.shadows.append(discover_shadow(api, chain.asset_id, "SANDBOX"))
    return chain

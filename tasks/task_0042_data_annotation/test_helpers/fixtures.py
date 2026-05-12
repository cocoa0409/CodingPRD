"""Composite setup helpers for the Data Annotation test suite.

Most interesting test claims require the system to be in a specific
state that takes 5–15 API calls to reach: an OPEN project with packages
in POOL; an annotator on a particular tier; a package walked all the
way to APPROVED with ledger entries booked; a payroll period locked
after enough work has been approved. These helpers encapsulate those
preambles.

Identity threading (PRD §2.1):

- Annotator is entity-backed -- 'X-User-ID is the id of the acting
  AnnotatorProfile'. Any ownership-gated call (claim, submit,
  rework-claim, arbitrate, /appeals, /appeals/{id}/decide) MUST use
  make_annotator_headers(annotator['id']) so the X-User-ID resolves
  to a real AnnotatorProfile.id. Falling back to TEST_USERS would
  defeat every ownership check.

- ProjectManager and QAReviewer are opaque -- the shared TEST_USERS
  constants are canonical for these roles.

Setup calls use get_success_data (lenient validator), so broken
preconditions surface as obvious errors rather than confusing
assertion failures.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .factories import (
    arbitrate_payload,
    clock_advance_payload,
    create_annotator_payload,
    create_appeal_payload,
    create_golden_sample_payload,
    create_payroll_period_payload,
    create_project_payload,
    decide_appeal_payload,
    dispatch_package_payload,
    finalize_inspection_payload,
    labels_for_count,
    split_packages_payload,
    submit_package_payload,
)
from .test_users import (
    TEST_USERS,
    make_annotator_headers,
    make_project_manager_headers,
    make_qa_reviewer_headers,
)


# ===========================================================================
# Time helpers (PRD §2.4 -- ISO 8601 UTC with three fractional digits)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits.

    PRD §2.4: 'All timestamps emitted by the API ... use the same ISO 8601
    UTC format with three fractional digits.'
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = f"{dt.microsecond // 1000:03d}"
    return f"{base}.{millis}Z"


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 string with optional 'Z' suffix to a tz-aware datetime."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def add_seconds(dt_iso: str, seconds: int) -> str:
    return iso_z(parse_iso(dt_iso) + timedelta(seconds=seconds))


# ---------------------------------------------------------------------------
# Project lifecycle helpers
# ---------------------------------------------------------------------------
def create_draft_project(
    *,
    pm_headers: Optional[Dict[str, str]] = None,
    task_type: str = "CLASSIFICATION",
    difficulty: str = "EASY",
    package_size: int = 10,
    distribution_mode: str = "GRAB",
    unit_price_cents: int = 100,
    pass_rate_target: float = 0.80,
    timeout_seconds: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a project in DRAFT and return the project dict."""
    headers = pm_headers or TEST_USERS["project_manager_headers"]
    payload = create_project_payload(
        task_type=task_type,
        difficulty=difficulty,
        package_size=package_size,
        distribution_mode=distribution_mode,
        unit_price_cents=unit_price_cents,
        pass_rate_target=pass_rate_target,
        timeout_seconds=timeout_seconds,
        **overrides,
    )
    resp = api_client.create_project(payload, headers)
    return get_success_data(resp)


def add_n_golden_samples(
    project_id: str,
    n: int,
    *,
    pm_headers: Optional[Dict[str, str]] = None,
    expected_label: Any = None,
) -> List[Dict[str, Any]]:
    """Add `n` GoldenSample rows to the project."""
    headers = pm_headers or TEST_USERS["project_manager_headers"]
    out: List[Dict[str, Any]] = []
    for _ in range(n):
        resp = api_client.add_golden_sample(
            project_id,
            create_golden_sample_payload(
                expected_label=expected_label
                if expected_label is not None
                else {"class": "cat"},
            ),
            headers,
        )
        out.append(get_success_data(resp))
    return out


def split_packages_for_project(
    project_id: str,
    total_item_count: int,
    *,
    pm_headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Split a project into TaskPackages."""
    headers = pm_headers or TEST_USERS["project_manager_headers"]
    resp = api_client.split_packages(
        project_id,
        split_packages_payload(total_item_count=total_item_count),
        headers,
    )
    data = get_success_data(resp)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # The response envelope returned data as a list inside _request;
        # but in case the runner returns the inner data dict, normalize.
        if "task_packages" in data and isinstance(data["task_packages"], list):
            return data["task_packages"]
        if "packages" in data and isinstance(data["packages"], list):
            return data["packages"]
    return data  # type: ignore[return-value]


def open_project(
    project_id: str,
    *,
    pm_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Walk DRAFT -> OPEN."""
    headers = pm_headers or TEST_USERS["project_manager_headers"]
    resp = api_client.open_project(project_id, headers)
    return get_success_data(resp)


def close_project(
    project_id: str,
    *,
    pm_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = pm_headers or TEST_USERS["project_manager_headers"]
    resp = api_client.close_project(project_id, headers)
    return get_success_data(resp)


def archive_project(
    project_id: str,
    *,
    pm_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = pm_headers or TEST_USERS["project_manager_headers"]
    resp = api_client.archive_project(project_id, headers)
    return get_success_data(resp)


def setup_open_project(
    *,
    pm_headers: Optional[Dict[str, str]] = None,
    task_type: str = "CLASSIFICATION",
    difficulty: str = "EASY",
    package_size: int = 10,
    total_item_count: Optional[int] = None,
    distribution_mode: str = "GRAB",
    unit_price_cents: int = 100,
    pass_rate_target: float = 0.80,
    timeout_seconds: Optional[int] = None,
    golden_count: int = 5,
    **overrides: Any,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Build a project in OPEN status with `golden_count` golden samples
    and one batch split. Returns (project, packages)."""
    headers = pm_headers or TEST_USERS["project_manager_headers"]
    project = create_draft_project(
        pm_headers=headers,
        task_type=task_type,
        difficulty=difficulty,
        package_size=package_size,
        distribution_mode=distribution_mode,
        unit_price_cents=unit_price_cents,
        pass_rate_target=pass_rate_target,
        timeout_seconds=timeout_seconds,
        **overrides,
    )
    add_n_golden_samples(project["id"], golden_count, pm_headers=headers)
    pkgs = split_packages_for_project(
        project["id"],
        total_item_count or package_size,
        pm_headers=headers,
    )
    project = open_project(project["id"], pm_headers=headers)
    # Re-list packages to reflect tier_required initialization.
    list_resp = api_client.list_packages(
        project["id"], headers, params={"limit": 100}
    )
    pkgs, _meta = validate_paginated(list_resp)
    return project, pkgs


# ---------------------------------------------------------------------------
# Annotator helpers
# ---------------------------------------------------------------------------
def create_annotator(
    *,
    entry_test_score: float = 70.0,
    pm_headers: Optional[Dict[str, str]] = None,
    domain_tags: Optional[List[str]] = None,
    display_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Register an AnnotatorProfile. PRD §3.2 derives initial tier from
    entry_test_score: >=95 EXPERT, >=80 SENIOR, else JUNIOR."""
    headers = pm_headers or TEST_USERS["project_manager_headers"]
    resp = api_client.create_annotator(
        create_annotator_payload(
            display_name=display_name,
            domain_tags=domain_tags,
            entry_test_score=entry_test_score,
        ),
        headers,
    )
    return get_success_data(resp)


def create_junior_annotator(**kwargs: Any) -> Dict[str, Any]:
    return create_annotator(entry_test_score=70.0, **kwargs)


def create_senior_annotator(**kwargs: Any) -> Dict[str, Any]:
    return create_annotator(entry_test_score=85.0, **kwargs)


def create_expert_annotator(**kwargs: Any) -> Dict[str, Any]:
    return create_annotator(entry_test_score=98.0, **kwargs)


def re_evaluate(
    annotator_id: str,
    *,
    pm_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = pm_headers or TEST_USERS["project_manager_headers"]
    resp = api_client.re_evaluate_annotator(annotator_id, headers)
    return get_success_data(resp)


def reinstate(
    annotator_id: str,
    *,
    pm_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = pm_headers or TEST_USERS["project_manager_headers"]
    resp = api_client.reinstate_annotator(annotator_id, headers)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Package lifecycle helpers
# ---------------------------------------------------------------------------
def claim_package(
    package_id: str,
    annotator_id: str,
) -> Dict[str, Any]:
    """Annotator self-claims (GRAB / HYBRID).
    Identity threading: X-User-ID == annotator_id (PRD §2.1)."""
    resp = api_client.claim_package(
        package_id, make_annotator_headers(annotator_id)
    )
    return get_success_data(resp)


def dispatch_package(
    package_id: str,
    annotator_id: str,
    *,
    pm_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = pm_headers or TEST_USERS["project_manager_headers"]
    resp = api_client.dispatch_package(
        package_id,
        dispatch_package_payload(annotator_id=annotator_id),
        headers,
    )
    return get_success_data(resp)


def submit_labels(
    package_id: str,
    annotator_id: str,
    *,
    item_count: int,
    label: Any = "A",
) -> Dict[str, Any]:
    """Submit a uniform label array of size item_count."""
    resp = api_client.submit_package(
        package_id,
        submit_package_payload(labels=labels_for_count(item_count, label)),
        make_annotator_headers(annotator_id),
    )
    return get_success_data(resp)


def submit_with_labels(
    package_id: str,
    annotator_id: str,
    labels: List[Any],
) -> Dict[str, Any]:
    resp = api_client.submit_package(
        package_id,
        submit_package_payload(labels=labels),
        make_annotator_headers(annotator_id),
    )
    return get_success_data(resp)


def start_inspection(
    package_id: str,
    *,
    qa_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = qa_headers or TEST_USERS["qa_reviewer_headers"]
    resp = api_client.start_inspection(package_id, headers)
    return get_success_data(resp)


def finalize_inspection(
    package_id: str,
    inspection_id: str,
    outcome: str,
    defects_found: int,
    *,
    qa_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = qa_headers or TEST_USERS["qa_reviewer_headers"]
    resp = api_client.finalize_inspection(
        package_id, inspection_id,
        finalize_inspection_payload(
            outcome=outcome, defects_found=defects_found,
        ),
        headers,
    )
    return get_success_data(resp)


def get_package(package_id: str,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["project_manager_headers"]
    return get_success_data(api_client.get_package(package_id, h))


def get_annotator(annotator_id: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["project_manager_headers"]
    return get_success_data(api_client.get_annotator(annotator_id, h))


def get_appeal(appeal_id: str,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    h = headers or TEST_USERS["project_manager_headers"]
    return get_success_data(api_client.get_appeal(appeal_id, h))


# ---------------------------------------------------------------------------
# Composite scenarios -- claim/submit/inspect chains
# ---------------------------------------------------------------------------
def _seed_pass_history(
    annotator: Dict[str, Any],
    n: int,
    *,
    package_size: int,
    difficulty: str,
    distribution_mode: str,
    unit_price_cents: int,
    pass_rate_target: float,
    task_type: str,
) -> None:
    """Drive `annotator` through N consecutive PASS finalisations on
    fresh single-package EASY projects so that subsequent FAILs in the
    test body don't drop rolling_pass_rate below the 0.70 suspension
    threshold (PRD §3.2). Each iteration creates one project, one
    package; the annotator claims, submits, the package is inspected
    and finalised PASS.

    The seed's projects are always EASY (tier_required=JUNIOR) to keep
    the seed loop running independent of the test's actual difficulty:
    a HARD test demotes the annotator to JUNIOR after the first
    finalise (because lifetime submitted < 50 invalidates EXPERT and
    < 20 invalidates SENIOR), so subsequent HARD claims would fail
    with ERR_TIER_INSUFFICIENT.
    """
    if n <= 0:
        return
    for _ in range(n):
        _proj, _pkgs = setup_open_project(
            task_type=task_type,
            difficulty="EASY",
            package_size=package_size,
            distribution_mode=distribution_mode,
            unit_price_cents=unit_price_cents,
            pass_rate_target=pass_rate_target,
        )
        seed_pkg = _pkgs[0]
        seed_pkg = claim_package(seed_pkg["id"], annotator["id"])
        submit_labels(
            seed_pkg["id"], annotator["id"], item_count=seed_pkg["item_count"],
        )
        insp = start_inspection(seed_pkg["id"])
        finalize_inspection(
            seed_pkg["id"], insp["id"], "PASS", defects_found=0,
        )


def setup_in_progress_package(
    *,
    annotator_score: float = 70.0,
    package_size: int = 10,
    difficulty: str = "EASY",
    distribution_mode: str = "GRAB",
    unit_price_cents: int = 100,
    pass_rate_target: float = 0.80,
    timeout_seconds: Optional[int] = None,
    task_type: str = "CLASSIFICATION",
    seed_pass_count: int = 0,
) -> Dict[str, Any]:
    """OPEN project + 1 package + 1 annotator who has claimed it.

    `seed_pass_count` (when > 0) seeds the annotator with that many
    prior PASS finalisations so that subsequent FAIL transitions in
    the test body don't immediately push the rolling pass rate below
    0.70 (PRD §3.2 suspension threshold). Tests that drive FAIL
    transitions should set this to a large enough number that the
    annotator's running rolling_pass_rate stays >= 0.70 even after
    the test's FAILs. Default is 0 — test bodies that don't FAIL the
    package don't need this and pricing tests rely on the
    fresh-annotator gross totals.
    Returns dict with keys: project, package, annotator."""
    annotator = create_annotator(entry_test_score=annotator_score)
    _seed_pass_history(
        annotator, seed_pass_count,
        package_size=package_size,
        difficulty=difficulty,
        distribution_mode=distribution_mode,
        unit_price_cents=unit_price_cents,
        pass_rate_target=pass_rate_target,
        task_type=task_type,
    )
    project, packages = setup_open_project(
        package_size=package_size,
        difficulty=difficulty,
        distribution_mode=distribution_mode,
        unit_price_cents=unit_price_cents,
        pass_rate_target=pass_rate_target,
        timeout_seconds=timeout_seconds,
        task_type=task_type,
    )
    pkg = packages[0]
    pkg = claim_package(pkg["id"], annotator["id"])
    return {
        "project": project,
        "package": pkg,
        "annotator": annotator,
    }


def setup_submitted_package(
    *,
    annotator_score: float = 70.0,
    package_size: int = 10,
    difficulty: str = "EASY",
    distribution_mode: str = "GRAB",
    unit_price_cents: int = 100,
    pass_rate_target: float = 0.80,
    task_type: str = "CLASSIFICATION",
    seed_pass_count: int = 0,
) -> Dict[str, Any]:
    """Drive a package from POOL through IN_PROGRESS to SUBMITTED."""
    state = setup_in_progress_package(
        annotator_score=annotator_score,
        package_size=package_size,
        difficulty=difficulty,
        distribution_mode=distribution_mode,
        unit_price_cents=unit_price_cents,
        pass_rate_target=pass_rate_target,
        task_type=task_type,
        seed_pass_count=seed_pass_count,
    )
    pkg = state["package"]
    annotator = state["annotator"]
    submit_labels(
        pkg["id"], annotator["id"],
        item_count=pkg["item_count"],
    )
    state["package"] = get_package(pkg["id"])
    return state


def setup_inspecting_package(**kwargs: Any) -> Dict[str, Any]:
    """Drive a package to INSPECTING. State['inspection'] holds the
    QualityInspection."""
    state = setup_submitted_package(**kwargs)
    pkg = state["package"]
    inspection = start_inspection(pkg["id"])
    state["inspection"] = inspection
    state["package"] = get_package(pkg["id"])
    return state


def setup_approved_package(
    *,
    defects_found: int = 0,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Drive a package to APPROVED via INSPECTING -> finalize PASS."""
    state = setup_inspecting_package(**kwargs)
    inspection = state["inspection"]
    pkg = state["package"]
    finalize_inspection(
        pkg["id"], inspection["id"],
        outcome="PASS",
        defects_found=defects_found,
    )
    state["package"] = get_package(pkg["id"])
    state["inspection"] = get_success_data(
        api_client.get_package(pkg["id"], TEST_USERS["project_manager_headers"])
    )["status"] and state["inspection"]
    return state


def setup_rejected_package_via_arbitration(
    *,
    expert_for_arbitration: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Drive a package to REJECTED through MAX_REWORK_ROUNDS+1 inspections
    plus an EXPERT arbiter REJECT."""
    # Force: fail twice (round 0 -> REWORK_PENDING with rework_round=1;
    # rework -> fail again -> REWORK_PENDING with rework_round=2; rework
    # -> fail third time -> ARBITRATING).
    # Seed enough PASS history so the 3 FAILs we issue in this helper do
    # not push rolling_pass_rate below 0.70 (PRD §3.2). With 17 prior
    # PASSes and 3 FAILs, the rolling 20-window holds 17/20 = 0.85.
    kwargs.setdefault("seed_pass_count", 17)

    # An EXPERT arbiter must exist *before* the third FAIL, because
    # finalize_inspection's arbitration routing calls select_arbiter
    # synchronously and rejects with ERR_NO_ELIGIBLE_ARBITER if no
    # EXPERT-ACTIVE annotator (other than the owner) is available.
    arbiter = expert_for_arbitration or create_expert_annotator()

    state = setup_inspecting_package(**kwargs)
    pkg = state["package"]
    annotator = state["annotator"]
    inspection = state["inspection"]
    # Round 0: FAIL (defects = sample_size to guarantee >10%).
    finalize_inspection(
        pkg["id"], inspection["id"], "FAIL",
        defects_found=inspection["sample_size"],
    )
    pkg = get_package(pkg["id"])
    # Round 1: rework-claim, submit, inspect, fail.
    get_success_data(api_client.rework_claim(
        pkg["id"], make_annotator_headers(annotator["id"])
    ))
    submit_labels(pkg["id"], annotator["id"], item_count=pkg["item_count"])
    insp2 = start_inspection(pkg["id"])
    finalize_inspection(
        pkg["id"], insp2["id"], "FAIL",
        defects_found=insp2["sample_size"],
    )
    pkg = get_package(pkg["id"])
    # Round 2: rework-claim, submit, inspect, fail -> ARBITRATING.
    get_success_data(api_client.rework_claim(
        pkg["id"], make_annotator_headers(annotator["id"])
    ))
    submit_labels(pkg["id"], annotator["id"], item_count=pkg["item_count"])
    insp3 = start_inspection(pkg["id"])
    finalize_inspection(
        pkg["id"], insp3["id"], "FAIL",
        defects_found=insp3["sample_size"],
    )
    pkg = get_package(pkg["id"])
    state["package"] = pkg
    state["inspection"] = insp3

    # Arbitrate with the pre-allocated EXPERT.
    resp = api_client.arbitrate_package(
        pkg["id"],
        arbitrate_payload(decision="REJECT"),
        make_annotator_headers(arbiter["id"]),
    )
    get_success_data(resp)
    state["package"] = get_package(pkg["id"])
    state["arbiter"] = arbiter
    return state


# ---------------------------------------------------------------------------
# Appeal helpers
# ---------------------------------------------------------------------------
def submit_appeal(
    package_id: str,
    inspection_id: str,
    annotator_id: str,
    *,
    reason: str = "Dispute the defects.",
) -> Dict[str, Any]:
    """PRD §3.8: appeal is filed by the annotator whose id is the
    package's submitter -- ownership-gated."""
    resp = api_client.create_appeal(
        package_id,
        create_appeal_payload(inspection_id=inspection_id, reason=reason),
        make_annotator_headers(annotator_id),
    )
    return get_success_data(resp)


def assign_arbiter(
    appeal_id: str,
    *,
    pm_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = pm_headers or TEST_USERS["project_manager_headers"]
    resp = api_client.assign_arbiter(appeal_id, headers)
    return get_success_data(resp)


def decide_appeal(
    appeal_id: str,
    arbiter_id: str,
    decision: str,
) -> Dict[str, Any]:
    """PRD §3.8: 'the arbiter -- an annotator whose id equals
    appeal.arbiter_id -- decides the appeal as UPHOLD or REJECT.'"""
    resp = api_client.decide_appeal(
        appeal_id,
        decide_appeal_payload(decision=decision),
        make_annotator_headers(arbiter_id),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Payroll helpers
# ---------------------------------------------------------------------------
def create_payroll_period(
    *,
    opens_at: str,
    closes_at: str,
    tax_rate: float = 0.10,
    pm_headers: Optional[Dict[str, str]] = None,
    cycle_label: Optional[str] = None,
) -> Dict[str, Any]:
    headers = pm_headers or TEST_USERS["project_manager_headers"]
    resp = api_client.create_payroll_period(
        create_payroll_period_payload(
            opens_at=opens_at,
            closes_at=closes_at,
            tax_rate=tax_rate,
            cycle_label=cycle_label,
        ),
        headers,
    )
    return get_success_data(resp)


def lock_payroll(
    period_id: str,
    *,
    pm_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = pm_headers or TEST_USERS["project_manager_headers"]
    resp = api_client.lock_payroll_period(period_id, headers)
    return get_success_data(resp)


def settle_payroll(
    period_id: str,
    *,
    pm_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = pm_headers or TEST_USERS["project_manager_headers"]
    resp = api_client.settle_payroll_period(period_id, headers)
    return get_success_data(resp)


def list_ledger(
    period_id: str,
    *,
    annotator_id: Optional[str] = None,
    pm_headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    headers = pm_headers or TEST_USERS["project_manager_headers"]
    params: Dict[str, Any] = {"limit": 100}
    if annotator_id is not None:
        params["annotator_id"] = annotator_id
    resp = api_client.list_ledger_entries(period_id, headers, params=params)
    data, _meta = validate_paginated(resp)
    return data


def list_audit(
    *,
    subject_kind: Optional[str] = None,
    subject_id: Optional[str] = None,
    pm_headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    headers = pm_headers or TEST_USERS["project_manager_headers"]
    params: Dict[str, Any] = {"limit": 100}
    if subject_kind is not None:
        params["subject_kind"] = subject_kind
    if subject_id is not None:
        params["subject_id"] = subject_id
    resp = api_client.list_audit_logs(headers, params=params)
    data, _meta = validate_paginated(resp)
    return data


def list_external(
    *,
    target_system: Optional[str] = None,
    pm_headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    headers = pm_headers or TEST_USERS["project_manager_headers"]
    params: Dict[str, Any] = {"limit": 100}
    if target_system is not None:
        params["target_system"] = target_system
    resp = api_client.list_external_events(headers, params=params)
    data, _meta = validate_paginated(resp)
    return data


# ---------------------------------------------------------------------------
# Clock helper
# ---------------------------------------------------------------------------
def advance_clock(
    to_iso: str,
    *,
    pm_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = pm_headers or TEST_USERS["project_manager_headers"]
    resp = api_client.advance_clock(to_iso, headers)
    return get_success_data(resp)


def dispatch_pending_events(
    *,
    pm_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = pm_headers or TEST_USERS["project_manager_headers"]
    resp = api_client.dispatch_pending_events(headers)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting (for difficulty-design)
# ---------------------------------------------------------------------------
def setup_annotator_with_history(
    *,
    pass_count: int,
    fail_count: int,
    package_size: int = 10,
    difficulty: str = "EASY",
    pass_rate_target: float = 0.80,
    distribution_mode: str = "GRAB",
    unit_price_cents: int = 100,
    annotator_score: float = 70.0,
    task_type: str = "CLASSIFICATION",
) -> Dict[str, Any]:
    """Build an annotator with pass_count APPROVED packages and fail_count
    REJECTED packages via the arbitration path (3 fails -> ARBITRATING ->
    REJECT). Each package created on its own project to avoid coupling.

    Returns: {"annotator": ..., "approved_packages": [...],
              "rejected_packages": [...], "arbiter": ...}
    """
    annotator = create_annotator(entry_test_score=annotator_score)
    arbiter = create_expert_annotator()
    approved: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    for _ in range(pass_count):
        project, pkgs = setup_open_project(
            package_size=package_size,
            difficulty=difficulty,
            distribution_mode=distribution_mode,
            unit_price_cents=unit_price_cents,
            pass_rate_target=pass_rate_target,
            task_type=task_type,
        )
        pkg = pkgs[0]
        pkg = claim_package(pkg["id"], annotator["id"])
        submit_labels(pkg["id"], annotator["id"], item_count=pkg["item_count"])
        insp = start_inspection(pkg["id"])
        finalize_inspection(
            pkg["id"], insp["id"], "PASS", defects_found=0,
        )
        approved.append(get_package(pkg["id"]))

    for _ in range(fail_count):
        state = setup_rejected_package_via_arbitration(
            annotator_score=annotator_score,
            package_size=package_size,
            difficulty=difficulty,
            distribution_mode=distribution_mode,
            unit_price_cents=unit_price_cents,
            pass_rate_target=pass_rate_target,
            task_type=task_type,
            expert_for_arbitration=arbiter,
        )
        # Each iteration creates a fresh project + annotator, but to
        # accumulate counters on the SAME annotator we must rerun the
        # same-annotator path. We re-do the arbitration flow on a new
        # project but for the configured `annotator`.
        # Override by using the controlled flow below.
        rejected.append(state["package"])

    return {
        "annotator": get_annotator(annotator["id"]),
        "approved_packages": approved,
        "rejected_packages": rejected,
        "arbiter": arbiter,
    }


def setup_annotator_with_pass_fail_history(
    *,
    annotator: Dict[str, Any],
    pass_then_fail: List[str],
    package_size: int = 10,
    difficulty: str = "EASY",
    pass_rate_target: float = 0.80,
    distribution_mode: str = "GRAB",
    unit_price_cents: int = 100,
    task_type: str = "CLASSIFICATION",
    arbiter: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Drive the SAME annotator through a sequence of "PASS"/"FAIL"
    inspections in chronological order. Each event is a fresh project +
    package owned by the annotator. Each "PASS" / "FAIL" produces
    EXACTLY ONE finalize-event so the chronological running counters
    move by 1 per item -- e.g., a sequence of 7 PASS + 3 FAIL yields 10
    finalize events with submitted_count=10 and approved_count=7.

    Returns {"approved_packages": [...], "failed_packages": [...],
             "inspection_pairs": [(package, inspection), ...],
             "arbiter": ...}.
    """
    annotator_id = annotator["id"]
    if arbiter is None:
        arbiter = create_expert_annotator()
    approved: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    inspection_pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []

    for outcome in pass_then_fail:
        project, pkgs = setup_open_project(
            package_size=package_size,
            difficulty=difficulty,
            distribution_mode=distribution_mode,
            unit_price_cents=unit_price_cents,
            pass_rate_target=pass_rate_target,
            task_type=task_type,
        )
        pkg = pkgs[0]
        pkg = claim_package(pkg["id"], annotator_id)
        submit_labels(pkg["id"], annotator_id, item_count=pkg["item_count"])
        insp = start_inspection(pkg["id"])
        if outcome == "PASS":
            finalize_inspection(
                pkg["id"], insp["id"], "PASS", defects_found=0,
            )
            approved.append(get_package(pkg["id"]))
            inspection_pairs.append((get_package(pkg["id"]), insp))
        else:  # "FAIL"
            # Single FAIL on a fresh package routes INSPECTING ->
            # REWORK_PENDING (rework_round 0 + 1 <= MAX_REWORK_ROUNDS=2).
            # PRD §3.4: 'submitted_count increments by 1 but
            # approved_count does not'. That's exactly one submitted
            # increment per "FAIL" entry, matching the difficulty-design
            # recipe.
            finalize_inspection(
                pkg["id"], insp["id"], "FAIL",
                defects_found=insp["sample_size"],
            )
            failed.append(get_package(pkg["id"]))
            inspection_pairs.append((get_package(pkg["id"]), insp))

    return {
        "approved_packages": approved,
        # Backwards-compatible alias used by older callers.
        "rejected_packages": failed,
        "failed_packages": failed,
        "inspection_pairs": inspection_pairs,
        "arbiter": arbiter,
    }


# ---------------------------------------------------------------------------
# Pre-supplied complex setups for difficulty-design tests
# ---------------------------------------------------------------------------
def setup_piece_rate_rounding_scenario() -> Dict[str, Any]:
    """SCAFFOLD_DIFFICULTY_DESIGN piece_rate_rounding_order: a SENIOR
    annotator on a MEDIUM CLASSIFICATION project with unit_price_cents=7
    and package_size=10 (the PRD-mandated minimum), claim+submit+inspect,
    ready for the finalize PASS that should book a piece-rate of 110
    cents per the pinned 'round per item, then sum' rule (per-item
    raw = 7 * 1.5 * 1.00 = 10.5 -> round_half_up = 11 -> gross 11 * 10
    = 110), versus 105 under the sum-then-round alternative
    (round_half_up(10.5 * 10) = round(105.0) = 105).
    """
    project, pkgs = setup_open_project(
        task_type="CLASSIFICATION",
        difficulty="MEDIUM",
        package_size=10,
        unit_price_cents=7,
        pass_rate_target=1.0,
        distribution_mode="GRAB",
    )
    senior = create_senior_annotator()
    pkg = pkgs[0]
    pkg = claim_package(pkg["id"], senior["id"])
    submit_labels(pkg["id"], senior["id"], item_count=pkg["item_count"])
    insp = start_inspection(pkg["id"])
    return {
        "project": project,
        "annotator": senior,
        "package": get_package(pkg["id"]),
        "inspection": insp,
    }


def setup_inspection_above_bonus_band() -> Dict[str, Any]:
    """SCAFFOLD_DIFFICULTY_DESIGN bonus_band_exact_equality: JUNIOR
    annotator, EASY project, unit_price_cents=100, package_size=20,
    pass_rate_target=0.85. JUNIOR sample_size = item_count = 20. With
    defects_found=2, defect ratio = 2/20 = 0.10 (PASS-routing
    threshold) and pass_rate = 1 - 2/20 = 0.90 = target+0.05,
    triggering BONUS at the inclusive boundary.

    Note: a PRD-faithful implementation routes the inspection to PASS
    only when defects/sample_size <= 0.10 (PRD §3.4). pass_rate must
    therefore be at least 0.90, so target+0.05 = 0.90 fixes target at
    0.85; the test then exercises the inclusive bonus boundary
    pass_rate >= target+0.05.
    """
    project, pkgs = setup_open_project(
        task_type="CLASSIFICATION",
        difficulty="EASY",
        package_size=20,
        unit_price_cents=100,
        pass_rate_target=0.85,
        distribution_mode="GRAB",
    )
    junior = create_junior_annotator()
    pkg = pkgs[0]
    pkg = claim_package(pkg["id"], junior["id"])
    submit_labels(pkg["id"], junior["id"], item_count=pkg["item_count"])
    insp = start_inspection(pkg["id"])
    return {
        "project": project,
        "annotator": junior,
        "package": get_package(pkg["id"]),
        "inspection": insp,
    }


def setup_empty_golden_history_annotator() -> Dict[str, Any]:
    """SCAFFOLD_DIFFICULTY_DESIGN golden_hit_rate_zero_total_empty_set:
    item_count=10 makes golden_inserted_count = floor(10*0.05) = 0;
    annotator's cumulative golden_total stays at 0; golden_hit_rate
    presumed 1.0 by the empty-set boundary.
    """
    project, pkgs = setup_open_project(
        task_type="CLASSIFICATION",
        difficulty="EASY",
        package_size=10,
        unit_price_cents=100,
        pass_rate_target=0.80,
        distribution_mode="GRAB",
    )
    junior = create_junior_annotator()
    pkg = pkgs[0]
    pkg = claim_package(pkg["id"], junior["id"])
    return {
        "project": project,
        "annotator": junior,
        "package": get_package(pkg["id"]),
    }


def setup_cyclic_rework_pre_arbitration(
    *,
    annotator_score: float = 70.0,
) -> Dict[str, Any]:
    """SCAFFOLD_DIFFICULTY_DESIGN task_package_cyclic_rework_loop:
    drive a single package through INSPECTING -> REWORK_PENDING ->
    IN_PROGRESS -> SUBMITTED -> INSPECTING (one full cycle).
    Returns state with package in INSPECTING after the cycle plus a
    history of inspection ids.

    Seed enough PASS history on the annotator that the FAIL we issue
    in the rework cycle does not push rolling_pass_rate below 0.70
    (PRD §3.2). Otherwise the implicit suspension cascade reverts the
    REWORK_PENDING package to POOL and the subsequent rework-claim
    fails with ERR_PACKAGE_STATE_INVALID.
    """
    state = setup_inspecting_package(
        annotator_score=annotator_score, seed_pass_count=10,
    )
    pkg = state["package"]
    annotator = state["annotator"]
    insp1 = state["inspection"]
    # FAIL with high defects -> REWORK_PENDING (rework_round=1)
    finalize_inspection(
        pkg["id"], insp1["id"], "FAIL",
        defects_found=insp1["sample_size"],
    )
    pkg = get_package(pkg["id"])
    # Rework-claim by same owner -> IN_PROGRESS
    get_success_data(api_client.rework_claim(
        pkg["id"], make_annotator_headers(annotator["id"])
    ))
    # Submit again -> SUBMITTED
    submit_labels(pkg["id"], annotator["id"], item_count=pkg["item_count"])
    pkg = get_package(pkg["id"])
    # Start-inspection again -> INSPECTING (back in the cycle)
    insp2 = start_inspection(pkg["id"])
    state["package"] = get_package(pkg["id"])
    state["inspection"] = insp2
    state["first_inspection"] = insp1
    return state


def setup_payroll_with_one_approved_package(
    *,
    opens_at_iso: Optional[str] = None,
    closes_at_iso: Optional[str] = None,
    tax_rate: float = 0.10,
    package_size: int = 10,
    unit_price_cents: int = 100,
    difficulty: str = "EASY",
    annotator_score: float = 70.0,
    pass_rate_target: float = 1.0,
) -> Dict[str, Any]:
    """Open project + 1 approved package + 1 payroll period locked,
    ready for /settle. Returns state with project, package, annotator,
    period.

    The default pass_rate_target=1.0 keeps the package outside the
    bonus and penalty bands (PRD §3.6), so the salary ledger contains
    exactly one PIECE_RATE entry and tax computations are
    straightforward. Tests that exercise BONUS/PENALTY pass an
    explicit pass_rate_target.
    """
    pm_headers = TEST_USERS["project_manager_headers"]
    # Default time window: large window covering "today".
    if opens_at_iso is None:
        opens_at_iso = "2026-01-01T00:00:00.000Z"
    if closes_at_iso is None:
        closes_at_iso = "2027-01-01T00:00:00.000Z"

    state = setup_in_progress_package(
        annotator_score=annotator_score,
        package_size=package_size,
        difficulty=difficulty,
        unit_price_cents=unit_price_cents,
        pass_rate_target=pass_rate_target,
    )
    pkg = state["package"]
    annotator = state["annotator"]
    submit_labels(pkg["id"], annotator["id"], item_count=pkg["item_count"])
    insp = start_inspection(pkg["id"])
    finalize_inspection(pkg["id"], insp["id"], "PASS", defects_found=0)
    pkg = get_package(pkg["id"])

    period = create_payroll_period(
        opens_at=opens_at_iso, closes_at=closes_at_iso, tax_rate=tax_rate,
    )
    # Advance clock past closes_at so we can lock.
    advance_clock(closes_at_iso, pm_headers=pm_headers)
    period = lock_payroll(period["id"], pm_headers=pm_headers)

    return {
        "project": state["project"],
        "package": pkg,
        "annotator": annotator,
        "period": period,
        "inspection": insp,
    }


__all__ = [
    "iso_z",
    "parse_iso",
    "add_seconds",
    "create_draft_project",
    "add_n_golden_samples",
    "split_packages_for_project",
    "open_project",
    "close_project",
    "archive_project",
    "setup_open_project",
    "create_annotator",
    "create_junior_annotator",
    "create_senior_annotator",
    "create_expert_annotator",
    "re_evaluate",
    "reinstate",
    "claim_package",
    "dispatch_package",
    "submit_labels",
    "submit_with_labels",
    "start_inspection",
    "finalize_inspection",
    "get_package",
    "get_annotator",
    "get_appeal",
    "setup_in_progress_package",
    "setup_submitted_package",
    "setup_inspecting_package",
    "setup_approved_package",
    "setup_rejected_package_via_arbitration",
    "submit_appeal",
    "assign_arbiter",
    "decide_appeal",
    "create_payroll_period",
    "lock_payroll",
    "settle_payroll",
    "list_ledger",
    "list_audit",
    "list_external",
    "advance_clock",
    "dispatch_pending_events",
    "setup_annotator_with_history",
    "setup_annotator_with_pass_fail_history",
    "setup_piece_rate_rounding_scenario",
    "setup_inspection_above_bonus_band",
    "setup_empty_golden_history_annotator",
    "setup_cyclic_rework_pre_arbitration",
    "setup_payroll_with_one_approved_package",
]

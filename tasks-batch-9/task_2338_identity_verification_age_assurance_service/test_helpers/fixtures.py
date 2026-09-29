"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because each test runs against an empty database. Setup calls use the
lenient ``get_success_data`` validator so a broken precondition surfaces as a
setup failure rather than as a confusing assertion failure.

Identity threading: a ``ClientIntegrator``'s ``X-User-ID`` is the acting
Client's ``id``, so every ownership-gated call below is issued with
``make_client_integrator_headers(client["id"])``.
"""
from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    age_estimation_profile_payload,
    assign_case_payload,
    attestation_pathway_payload,
    biometric_profile_payload,
    create_bias_audit_payload,
    create_client_payload,
    create_cohort_metric_payload,
    create_document_capture_payload,
    create_liveness_check_payload,
    create_verification_policy_payload,
    create_verification_session_payload,
    database_check_profile_payload,
    database_evidence_payload,
    knowledge_based_evidence_payload,
    knowledge_based_profile_payload,
    document_scan_profile_payload,
    estimation_result_payload,
    pathway_decision_payload,
    publish_policy_payload,
    remediation_payload,
    review_decision_payload,
    vouching_pathway_payload,
    vouching_profile_payload,
)
from .test_users import (
    COMPLIANCE_OFFICER_USER_ID,
    INCLUSION_REVIEWER_USER_ID,
    MANUAL_REVIEWER_USER_ID,
    REVIEW_MANAGER_USER_ID,
    TEST_USERS,
    make_client_integrator_headers,
    make_compliance_officer_headers,
    make_inclusion_reviewer_headers,
    make_manual_reviewer_headers,
    make_review_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]

PROFILE_PAYLOAD_BUILDERS = {
    "DOCUMENT_SCAN": document_scan_profile_payload,
    "DATABASE_CHECK": database_check_profile_payload,
    "KNOWLEDGE_BASED": knowledge_based_profile_payload,
    "BIOMETRIC_COMPARISON": biometric_profile_payload,
    "VOUCHING_ATTESTATION": vouching_profile_payload,
    "AGE_ESTIMATION": age_estimation_profile_payload,
}


# ==========================================================================
# Tier 0: primitives
# ==========================================================================
def set_clock(current_utc: str) -> dict:
    """Move the logical clock and return the echoed instant."""
    return get_success_data(api_client.set_clock(current_utc, ADMIN))


def register_client(**overrides) -> dict:
    """Register a relying-party client; it lands in SANDBOX."""
    return get_success_data(api_client.create_client(create_client_payload(**overrides), ADMIN))


def patch_client(client_id: str, **fields) -> dict:
    return get_success_data(api_client.patch_client(client_id, dict(fields), ADMIN))


def read_client(client_id: str) -> dict:
    return get_success_data(api_client.get_client(client_id, ADMIN))


def client_version(client_id: str) -> int:
    return read_client(client_id)["version"]


def create_live_client(**overrides) -> dict:
    """Register a client and move its integration posture to LIVE."""
    client = register_client(**overrides)
    return patch_client(client["id"], integration_state="LIVE")


def register_method_profile(method_code: str, **overrides) -> dict:
    builder = PROFILE_PAYLOAD_BUILDERS[method_code]
    return get_success_data(api_client.create_method_profile(builder(**overrides), ADMIN))


def read_method_profile(profile_id: str) -> dict:
    return get_success_data(api_client.get_method_profile(profile_id, ADMIN))


def draft_policy(client_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_verification_policy(
            create_verification_policy_payload(client_id, **overrides),
            make_client_integrator_headers(client_id),
        )
    )


def publish_policy(policy_id: str, expected_client_version: int, officer_user_id: str = COMPLIANCE_OFFICER_USER_ID) -> dict:
    return get_success_data(
        api_client.publish_verification_policy(
            policy_id,
            publish_policy_payload(expected_client_version),
            make_compliance_officer_headers(officer_user_id),
        )
    )


def create_published_policy(client_id: str, **overrides) -> dict:
    """Draft a policy for the client and publish it at the client's live version."""
    policy = draft_policy(client_id, **overrides)
    return publish_policy(policy["id"], client_version(client_id))


def open_session(client_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_verification_session(
            create_verification_session_payload(client_id, **overrides),
            make_client_integrator_headers(client_id),
        )
    )


def read_session(session_id: str, client_id: Optional[str] = None) -> dict:
    headers = make_client_integrator_headers(client_id) if client_id else ADMIN
    return get_success_data(api_client.get_verification_session(session_id, headers))


def read_attempt(attempt_id: str, client_id: Optional[str] = None) -> dict:
    headers = make_client_integrator_headers(client_id) if client_id else ADMIN
    return get_success_data(api_client.get_method_attempt(attempt_id, headers))


# ==========================================================================
# Tier 1: state progression
# ==========================================================================
def open_attempt(session_id: str, client_id: str, method_profile_id: Optional[str] = None) -> dict:
    """Open an attempt, either on a named profile or on the selector's winner."""
    payload: Dict[str, Any] = {}
    if method_profile_id is not None:
        payload["method_profile_id"] = method_profile_id
    return get_success_data(
        api_client.create_method_attempt(
            session_id, payload, make_client_integrator_headers(client_id)
        )
    )


def submit_document_capture(attempt_id: str, client_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_document_capture(
            attempt_id,
            create_document_capture_payload(**overrides),
            make_client_integrator_headers(client_id),
        )
    )


def submit_liveness_check(attempt_id: str, client_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_liveness_check(
            attempt_id,
            create_liveness_check_payload(**overrides),
            make_client_integrator_headers(client_id),
        )
    )


def submit_database_evidence(
    attempt_id: str, client_id: str, matched_field_count: int, total_field_count: int
) -> dict:
    return get_success_data(
        api_client.create_data_evidence(
            attempt_id,
            database_evidence_payload(matched_field_count, total_field_count),
            make_client_integrator_headers(client_id),
        )
    )


def submit_knowledge_based_evidence(
    attempt_id: str, client_id: str, correct_answer_count: int, question_count: int
) -> dict:
    return get_success_data(
        api_client.create_data_evidence(
            attempt_id,
            knowledge_based_evidence_payload(correct_answer_count, question_count),
            make_client_integrator_headers(client_id),
        )
    )


def finalize_attempt(attempt_id: str, client_id: str) -> dict:
    return get_success_data(
        api_client.finalize_method_attempt(attempt_id, make_client_integrator_headers(client_id))
    )


def step_up(session_id: str, client_id: str) -> dict:
    return get_success_data(
        api_client.step_up_session(session_id, make_client_integrator_headers(client_id))
    )


def complete_session(session_id: str, client_id: str) -> dict:
    return get_success_data(
        api_client.complete_session(session_id, make_client_integrator_headers(client_id))
    )


def run_sweep() -> dict:
    return get_success_data(api_client.run_retention_sweep(ADMIN))


# ==========================================================================
# Tier 2: entity hierarchy — the shared onboarding preamble
# ==========================================================================
def setup_client_with_published_policy(
    method_codes: Sequence[str] = ("DOCUMENT_SCAN",),
    client_overrides: Optional[Dict[str, Any]] = None,
    policy_overrides: Optional[Dict[str, Any]] = None,
    extra_profiles: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """LIVE client + vendor profiles + one PUBLISHED policy.

    ``method_codes`` are both registered as profiles and admitted by the policy.
    ``extra_profiles`` registers further profiles (keyed by method code with
    payload overrides) that the policy does not admit — used for the vouching,
    age-estimation and out-of-policy scenarios.

    Returns ``{"client", "profiles", "policy"}`` where ``profiles`` maps method
    code to the registered profile.
    """
    client = create_live_client(**(client_overrides or {}))
    profiles: Dict[str, dict] = {}
    for code in method_codes:
        profiles[code] = register_method_profile(code)
    for code, overrides in (extra_profiles or {}).items():
        profiles[code] = register_method_profile(code, **(overrides or {}))

    policy_kwargs: Dict[str, Any] = {"allowed_method_codes": list(method_codes)}
    policy_kwargs.update(policy_overrides or {})
    policy = create_published_policy(client["id"], **policy_kwargs)
    return {"client": client, "profiles": profiles, "policy": policy}


def setup_session(
    method_codes: Sequence[str] = ("DOCUMENT_SCAN",),
    client_overrides: Optional[Dict[str, Any]] = None,
    policy_overrides: Optional[Dict[str, Any]] = None,
    session_overrides: Optional[Dict[str, Any]] = None,
    extra_profiles: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """The full onboarding preamble plus one open verification session.

    Returns ``{"client", "profiles", "policy", "session", "headers"}``.
    """
    env = setup_client_with_published_policy(
        method_codes=method_codes,
        client_overrides=client_overrides,
        policy_overrides=policy_overrides,
        extra_profiles=extra_profiles,
    )
    env["session"] = open_session(env["client"]["id"], **(session_overrides or {}))
    env["headers"] = make_client_integrator_headers(env["client"]["id"])
    return env


# ==========================================================================
# Tier 3: full lifecycle shortcuts
# ==========================================================================
def setup_scored_document_attempt(
    capture_overrides: Optional[Dict[str, Any]] = None,
    **session_kwargs,
) -> Dict[str, Any]:
    """Session with one DOCUMENT_SCAN attempt carrying a scored capture.

    Returns the session environment plus ``attempt`` and ``capture``.
    """
    env = setup_session(**session_kwargs)
    client_id = env["client"]["id"]
    attempt = open_attempt(
        env["session"]["id"], client_id, env["profiles"]["DOCUMENT_SCAN"]["id"]
    )
    capture = submit_document_capture(attempt["id"], client_id, **(capture_overrides or {}))
    env["attempt"] = read_attempt(attempt["id"], client_id)
    env["capture"] = capture
    return env


def setup_finalized_document_attempt(
    capture_overrides: Optional[Dict[str, Any]] = None,
    **session_kwargs,
) -> Dict[str, Any]:
    """Session with one DOCUMENT_SCAN attempt scored and then finalised."""
    env = setup_scored_document_attempt(capture_overrides=capture_overrides, **session_kwargs)
    env["attempt"] = finalize_attempt(env["attempt"]["id"], env["client"]["id"])
    return env


FORGED_CAPTURE = {
    "document_type": "RESIDENCE_PERMIT",
    "required_feature_count": 10,
    "passed_feature_count": 5,
    "tamper_signal_count": 3,
    "mrz_checksum_valid": False,
}

SUSPECT_CAPTURE = {
    "document_type": "DRIVERS_LICENSE",
    "required_feature_count": 8,
    "passed_feature_count": 7,
    "tamper_signal_count": 2,
    "mrz_checksum_valid": True,
}


def setup_session_in_manual_review_from_fraud(**session_kwargs) -> Dict[str, Any]:
    """Escalate a session to MANUAL_REVIEW through a FORGED document finalisation.

    Returns the environment plus ``attempt`` and ``case`` (the QUEUED case).
    """
    env = setup_finalized_document_attempt(capture_overrides=dict(FORGED_CAPTURE), **session_kwargs)
    cases, _ = _list(
        api_client.list_manual_review_cases(env["session"]["id"], make_review_manager_headers())
    )
    env["case"] = cases[0]
    return env


def setup_assigned_review_case(
    reviewer_user_id: str = MANUAL_REVIEWER_USER_ID,
    manager_user_id: str = REVIEW_MANAGER_USER_ID,
    **session_kwargs,
) -> Dict[str, Any]:
    """A FRAUD_SIGNAL case moved to ASSIGNED, reserving one review credit."""
    env = setup_session_in_manual_review_from_fraud(**session_kwargs)
    env["case"] = get_success_data(
        api_client.assign_manual_review_case(
            env["case"]["id"],
            assign_case_payload(reviewer_user_id),
            make_review_manager_headers(manager_user_id),
        )
    )
    return env


def decide_review_case(
    case_id: str, decision: str, reviewer_user_id: str = MANUAL_REVIEWER_USER_ID
) -> dict:
    return get_success_data(
        api_client.decide_manual_review_case(
            case_id, review_decision_payload(decision), make_manual_reviewer_headers(reviewer_user_id)
        )
    )


def setup_stored_biometric_template(
    liveness_overrides: Optional[Dict[str, Any]] = None,
    **session_kwargs,
) -> Dict[str, Any]:
    """Session with an accepted biometric attempt and one STORED template.

    The default liveness capture is an ACTIVE modality with pad 9000 and match
    9200, which passes the tuned threshold and stores a template.
    """
    session_kwargs.setdefault("method_codes", ("BIOMETRIC_COMPARISON",))
    session_kwargs.setdefault("policy_overrides", {"min_assurance_score": 30, "pad_threshold_bps": 7500})
    session_overrides = dict(session_kwargs.pop("session_overrides", {}) or {})
    session_overrides.setdefault("biometric_consent", True)
    env = setup_session(session_overrides=session_overrides, **session_kwargs)
    client_id = env["client"]["id"]
    attempt = open_attempt(
        env["session"]["id"], client_id, env["profiles"]["BIOMETRIC_COMPARISON"]["id"]
    )
    overrides = {"capture_modality": "ACTIVE", "pad_score_bps": 9000, "match_score_bps": 9200}
    overrides.update(liveness_overrides or {})
    env["liveness"] = submit_liveness_check(attempt["id"], client_id, **overrides)
    env["attempt"] = finalize_attempt(attempt["id"], client_id)
    templates, _ = _list(
        api_client.list_biometric_templates(env["session"]["id"], ADMIN)
    )
    env["template"] = templates[0] if templates else None
    return env


def request_pathway(session_id: str, client_id: str, pathway_type: str, **overrides) -> dict:
    payload = (
        vouching_pathway_payload(**overrides)
        if pathway_type == "VOUCHING"
        else attestation_pathway_payload(**overrides)
    )
    return get_success_data(
        api_client.create_alternative_pathway(
            session_id, payload, make_client_integrator_headers(client_id)
        )
    )


def decide_pathway(
    pathway_id: str, action: str, reviewer_user_id: str = INCLUSION_REVIEWER_USER_ID
) -> dict:
    return get_success_data(
        api_client.decide_alternative_pathway(
            pathway_id,
            pathway_decision_payload(action),
            make_inclusion_reviewer_headers(reviewer_user_id),
        )
    )


def setup_pending_pathway(pathway_type: str = "VOUCHING", **session_kwargs) -> Dict[str, Any]:
    """Session with a pending inclusion pathway and a vouching profile on file."""
    extra = dict(session_kwargs.pop("extra_profiles", {}) or {})
    extra.setdefault("VOUCHING_ATTESTATION", {})
    session_overrides = dict(session_kwargs.pop("session_overrides", {}) or {})
    session_overrides.setdefault("documentation_status", "NO_STANDARD_DOCS")
    env = setup_session(extra_profiles=extra, session_overrides=session_overrides, **session_kwargs)
    env["pathway"] = request_pathway(
        env["session"]["id"], env["client"]["id"], pathway_type
    )
    return env


# ==========================================================================
# Tier 4: accumulation and threshold targeting
# ==========================================================================
def setup_age_gated_session(
    required_min_age_years: int = 18,
    age_buffer_multiplier_bps: int = 15000,
    estimation_mae_months: int = 18,
    band_accuracy_bps: Optional[Dict[str, int]] = None,
    **session_kwargs,
) -> Dict[str, Any]:
    """Session whose pinned policy gates on age, plus an AGE_ESTIMATION profile."""
    extra = dict(session_kwargs.pop("extra_profiles", {}) or {})
    age_overrides: Dict[str, Any] = {"estimation_mae_months": estimation_mae_months}
    if band_accuracy_bps is not None:
        age_overrides["band_accuracy_bps"] = band_accuracy_bps
    extra.setdefault("AGE_ESTIMATION", age_overrides)
    policy_overrides = dict(session_kwargs.pop("policy_overrides", {}) or {})
    policy_overrides.setdefault("required_min_age_years", required_min_age_years)
    policy_overrides.setdefault("age_buffer_multiplier_bps", age_buffer_multiplier_bps)
    return setup_session(
        extra_profiles=extra, policy_overrides=policy_overrides, **session_kwargs
    )


def record_estimation_result(
    session_id: str, client_id: str, estimation_profile_id: str, estimated_age_months: int
) -> dict:
    return get_success_data(
        api_client.create_age_assurance_result(
            session_id,
            estimation_result_payload(estimation_profile_id, estimated_age_months),
            make_client_integrator_headers(client_id),
        )
    )


# Three balanced cohorts whose pooled false-reject rate is 400 bps and whose
# highest cohort rate is 500 bps.
RESTRICTING_COHORTS: List[Tuple[str, int, int]] = [
    ("AGE_18_24", 1000, 50),
    ("AGE_25_44", 1000, 30),
    ("AGE_65_PLUS", 1000, 40),
]


def open_bias_audit(
    method_profile_id: str,
    window_start: str = "2026-07-01T00:00:00Z",
    window_end: str = "2026-08-01T00:00:00Z",
    officer_user_id: str = COMPLIANCE_OFFICER_USER_ID,
) -> dict:
    return get_success_data(
        api_client.create_bias_audit(
            create_bias_audit_payload(method_profile_id, window_start, window_end),
            make_compliance_officer_headers(officer_user_id),
        )
    )


def add_cohort_metric(
    audit_id: str,
    cohort_code: str,
    attempt_count: int,
    false_reject_count: int,
    false_accept_count: int = 2,
    officer_user_id: str = COMPLIANCE_OFFICER_USER_ID,
) -> dict:
    return get_success_data(
        api_client.create_cohort_metric(
            audit_id,
            create_cohort_metric_payload(
                cohort_code, attempt_count, false_reject_count, false_accept_count
            ),
            make_compliance_officer_headers(officer_user_id),
        )
    )


def setup_bias_audit_with_cohorts(
    method_profile_id: str,
    cohorts: Sequence[Tuple[str, int, int]] = tuple(RESTRICTING_COHORTS),
    window_start: str = "2026-07-01T00:00:00Z",
    window_end: str = "2026-08-01T00:00:00Z",
    officer_user_id: str = COMPLIANCE_OFFICER_USER_ID,
) -> dict:
    """A COLLECTING audit carrying the supplied cohort rows."""
    audit = open_bias_audit(
        method_profile_id, window_start, window_end, officer_user_id=officer_user_id
    )
    for cohort_code, attempt_count, false_reject_count in cohorts:
        add_cohort_metric(
            audit["id"],
            cohort_code,
            attempt_count,
            false_reject_count,
            officer_user_id=officer_user_id,
        )
    return audit


def evaluate_audit(audit_id: str, officer_user_id: str = COMPLIANCE_OFFICER_USER_ID) -> dict:
    return get_success_data(
        api_client.evaluate_bias_audit(audit_id, make_compliance_officer_headers(officer_user_id))
    )


def remediate_audit(
    audit_id: str,
    expected_method_profile_version: int,
    officer_user_id: str,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.remediate_bias_audit(
            audit_id,
            remediation_payload(expected_method_profile_version, **overrides),
            make_compliance_officer_headers(officer_user_id),
        )
    )


def restrict_profile_by_bias(
    method_profile_id: str,
    cohorts: Sequence[Tuple[str, int, int]] = tuple(RESTRICTING_COHORTS),
    window_start: str = "2026-07-01T00:00:00Z",
    window_end: str = "2026-08-01T00:00:00Z",
    officer_user_id: str = COMPLIANCE_OFFICER_USER_ID,
) -> dict:
    """Drive a profile to RESTRICTED through a completed disparity evaluation.

    The default cohorts produce a gating ratio of 12500 basis points.
    """
    audit = setup_bias_audit_with_cohorts(
        method_profile_id,
        cohorts=cohorts,
        window_start=window_start,
        window_end=window_end,
        officer_user_id=officer_user_id,
    )
    return evaluate_audit(audit["id"], officer_user_id=officer_user_id)


def open_sessions_up_to(client_id: str, count: int, prefix: str = "subj-fill") -> List[dict]:
    """Open ``count`` sessions so the client's rolling window fills up."""
    return [
        open_session(client_id, external_subject_ref=f"{prefix}-{index}")
        for index in range(count)
    ]


# ==========================================================================
# Tier 5: finalisation and terminal states
# ==========================================================================
def setup_verified_session_with_scheduled_template(
    completion_clock: str = "2026-08-10T09:00:00Z",
    **session_kwargs,
) -> Dict[str, Any]:
    """A VERIFIED session whose biometric template sits in PURGE_SCHEDULED.

    The client retains templates for ninety days, so completion schedules the
    purge rather than deleting at once.
    """
    set_clock(completion_clock)
    client_overrides = dict(session_kwargs.pop("client_overrides", {}) or {})
    client_overrides.setdefault("biometric_retention_mode", "RETAIN_90_DAYS")
    env = setup_stored_biometric_template(client_overrides=client_overrides, **session_kwargs)
    env["session"] = complete_session(env["session"]["id"], env["client"]["id"])
    templates, _ = _list(api_client.list_biometric_templates(env["session"]["id"], ADMIN))
    env["template"] = templates[0]
    return env


# ==========================================================================
# Read helpers
# ==========================================================================
def _list(response) -> Tuple[list, dict]:
    body = response.json()
    return body.get("data", []), body.get("meta", {})


def list_session_attempts(session_id: str) -> Tuple[list, dict]:
    return _list(api_client.list_method_attempts(ADMIN, params={"session_id": session_id}))


def list_session_audit_events(session_id: str, event_type: Optional[str] = None) -> Tuple[list, dict]:
    params = {"event_type": event_type} if event_type else None
    return _list(api_client.list_audit_events(session_id, ADMIN, params=params))


def list_session_templates(session_id: str, state: Optional[str] = None) -> Tuple[list, dict]:
    params = {"state": state} if state else None
    return _list(api_client.list_biometric_templates(session_id, ADMIN, params=params))


def list_session_cases(session_id: str, state: Optional[str] = None) -> Tuple[list, dict]:
    params = {"state": state} if state else None
    return _list(
        api_client.list_manual_review_cases(session_id, make_review_manager_headers(), params=params)
    )


def list_session_pathways(session_id: str, client_id: str) -> Tuple[list, dict]:
    return _list(
        api_client.list_alternative_pathways(
            session_id, make_client_integrator_headers(client_id)
        )
    )


def list_session_age_results(session_id: str, client_id: str) -> Tuple[list, dict]:
    return _list(
        api_client.list_age_assurance_results(
            session_id, make_client_integrator_headers(client_id)
        )
    )


def list_profile_audits(profile_id: str) -> Tuple[list, dict]:
    return _list(api_client.list_profile_bias_audits(profile_id, ADMIN))


def read_bias_audit(audit_id: str) -> dict:
    return get_success_data(api_client.get_bias_audit(audit_id, OFFICER))


def read_policy(policy_id: str) -> dict:
    return get_success_data(api_client.get_verification_policy(policy_id, ADMIN))

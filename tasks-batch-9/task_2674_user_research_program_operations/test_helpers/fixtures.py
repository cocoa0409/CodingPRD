"""Composite setup helpers.

Every helper builds its preconditions from scratch through declared endpoints
only, and every one accepts ``**overrides`` so a caller can retarget a value
without re-inventing the chain.  Helpers use ``get_success_data`` internally so a
broken setup step fails loudly and distinguishably from the assertion under test.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient, api_client
from .test_users import (
    PRIVACY_OFFICER_HEADERS,
    RESEARCH_LEAD_HEADERS,
    RESEARCH_LEAD_USER_ID,
    RESEARCH_OPS_ADMIN_HEADERS,
    RESEARCHER_HEADERS,
    RESEARCHER_USER_ID,
    STAKEHOLDER_HEADERS,
    STAKEHOLDER_USER_ID,
)


# ===========================================================================
# Tier 0 - primitives
# ===========================================================================
def set_clock(to_iso8601: str, api: ApiClient = api_client) -> Dict[str, Any]:
    """Move the logical clock, which is the sole source of "now"."""
    return get_success_data(
        api.set_clock(to_iso8601, RESEARCH_OPS_ADMIN_HEADERS)
    )


def run_retention_sweep(api: ApiClient = api_client, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.run_retention_sweep(headers or RESEARCH_OPS_ADMIN_HEADERS)
    )


def create_decision(api: ApiClient = api_client, **overrides: Any) -> Dict[str, Any]:
    payload = factories.create_roadmap_decision_payload(**overrides)
    return get_success_data(
        api.create_roadmap_decision(payload, STAKEHOLDER_HEADERS)
    )


def create_request(
    decision_id: str, api: ApiClient = api_client, headers=None, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.create_research_request_payload(decision_id, **overrides)
    return get_success_data(
        api.create_research_request(payload, headers or STAKEHOLDER_HEADERS)
    )


def triage_request(
    request_id: str,
    outcome: str = "APPROVED",
    reason: Optional[str] = None,
    method_override: Optional[str] = None,
    api: ApiClient = api_client,
) -> Dict[str, Any]:
    payload = factories.triage_payload(outcome, reason, method_override)
    return get_success_data(
        api.triage_research_request(request_id, payload, RESEARCH_LEAD_HEADERS)
    )


def create_pool(api: ApiClient = api_client, **overrides: Any) -> Dict[str, Any]:
    payload = factories.create_participant_pool_payload(**overrides)
    return get_success_data(
        api.create_participant_pool(payload, RESEARCH_OPS_ADMIN_HEADERS)
    )


def enroll_participant(
    pool_id: str, api: ApiClient = api_client, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.create_participant_payload(**overrides)
    return get_success_data(
        api.enroll_participant(pool_id, payload, RESEARCH_OPS_ADMIN_HEADERS)
    )


def enroll_participants(
    pool_id: str,
    count: int,
    api: ApiClient = api_client,
    segment: str = "POWER_USER",
    locale: str = "en-US",
    ref_prefix: str = "p",
    **overrides: Any,
) -> List[Dict[str, Any]]:
    """Enroll ``count`` participants in creation order, which is the selector's
    final tie-break key."""
    rows = []
    for index in range(1, count + 1):
        rows.append(
            enroll_participant(
                pool_id,
                api,
                external_ref=f"{ref_prefix}{index}-{pool_id[:8]}",
                segment=segment,
                locale=locale,
                **overrides,
            )
        )
    return rows


def create_study(
    request_id: str,
    pool_id: str,
    api: ApiClient = api_client,
    headers=None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.create_study_payload(request_id, pool_id, **overrides)
    return get_success_data(api.create_study(payload, headers or RESEARCHER_HEADERS))


def write_guide(
    study_id: str, api: ApiClient = api_client, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.study_guide_payload(**overrides)
    return get_success_data(api.write_study_guide(study_id, payload, RESEARCHER_HEADERS))


def approve_guide(study_id: str, api: ApiClient = api_client) -> Dict[str, Any]:
    return get_success_data(api.approve_study_guide(study_id, RESEARCH_LEAD_HEADERS))


def field_study(study_id: str, api: ApiClient = api_client) -> Dict[str, Any]:
    return get_success_data(api.field_study(study_id, RESEARCHER_HEADERS))


def close_fielding(study_id: str, api: ApiClient = api_client) -> Dict[str, Any]:
    return get_success_data(api.close_study_fielding(study_id, RESEARCHER_HEADERS))


def invite(
    study_id: str,
    participant_id: str,
    api: ApiClient = api_client,
    headers=None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.create_recruitment_payload(participant_id, **overrides)
    return get_success_data(
        api.create_recruitment(study_id, payload, headers or RESEARCHER_HEADERS)
    )


def screen(recruitment_id: str, api: ApiClient = api_client) -> Dict[str, Any]:
    return get_success_data(api.screen_recruitment(recruitment_id, RESEARCHER_HEADERS))


def schedule(
    recruitment_id: str,
    scheduled_start: str,
    scheduled_end: str,
    api: ApiClient = api_client,
    moderator_user_id: str = RESEARCH_LEAD_USER_ID,
) -> Dict[str, Any]:
    payload = factories.schedule_payload(
        scheduled_start, scheduled_end, moderator_user_id
    )
    return get_success_data(
        api.schedule_recruitment(recruitment_id, payload, RESEARCHER_HEADERS)
    )


def complete_session(
    recruitment_id: str, api: ApiClient = api_client, actual_duration_min: int = 55
) -> Dict[str, Any]:
    payload = factories.complete_recruitment_payload(actual_duration_min)
    return get_success_data(
        api.complete_recruitment(recruitment_id, payload, RESEARCHER_HEADERS)
    )


def record_no_show(
    recruitment_id: str, api: ApiClient = api_client, reason: str = "Did not join"
) -> Dict[str, Any]:
    return get_success_data(
        api.record_no_show(recruitment_id, factories.no_show_payload(reason), RESEARCHER_HEADERS)
    )


def withdraw(
    recruitment_id: str, api: ApiClient = api_client, reason: str = "Withdrew early"
) -> Dict[str, Any]:
    return get_success_data(
        api.withdraw_recruitment(
            recruitment_id, factories.withdraw_payload(reason), RESEARCHER_HEADERS
        )
    )


def grant_consent(
    participant_id: str,
    study_id: str,
    api: ApiClient = api_client,
    scopes: Optional[Sequence[str]] = None,
    retention_days: int = 120,
    headers=None,
) -> Dict[str, Any]:
    payload = factories.create_consent_record_payload(
        participant_id,
        study_id,
        scopes=list(scopes) if scopes is not None else ["RECORDING", "TRANSCRIPT", "PII_QUOTE"],
        retention_days=retention_days,
    )
    return get_success_data(
        api.create_consent_record(payload, headers or PRIVACY_OFFICER_HEADERS)
    )


def revoke_consent(
    consent_id: str, api: ApiClient = api_client, reason: str = "Participant asked for erasure"
) -> Dict[str, Any]:
    return get_success_data(
        api.revoke_consent_record(
            consent_id, factories.revoke_consent_payload(reason), PRIVACY_OFFICER_HEADERS
        )
    )


def register_artifact(
    recruitment_id: str,
    api: ApiClient = api_client,
    artifact_type: str = "TRANSCRIPT",
    contains_pii: bool = False,
) -> Dict[str, Any]:
    payload = factories.create_artifact_payload(artifact_type, contains_pii)
    return get_success_data(api.create_artifact(recruitment_id, payload, RESEARCHER_HEADERS))


def create_theme(
    api: ApiClient = api_client,
    label: Optional[str] = None,
    parent_theme_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.create_theme_payload(label, parent_theme_id, **overrides)
    return get_success_data(api.create_theme(payload, RESEARCHER_HEADERS))


def create_finding(
    study_id: str,
    theme_id: str,
    api: ApiClient = api_client,
    headers=None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.create_finding_payload(study_id, theme_id, **overrides)
    return get_success_data(api.create_finding(payload, headers or RESEARCHER_HEADERS))


def link_evidence(
    finding_id: str,
    artifact_id: str,
    api: ApiClient = api_client,
    weight_class: str = "DIRECT_QUOTE",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.create_evidence_link_payload(
        artifact_id, weight_class, **overrides
    )
    return get_success_data(
        api.create_evidence_link(finding_id, payload, RESEARCHER_HEADERS)
    )


def lock_finding(finding_id: str, api: ApiClient = api_client) -> Dict[str, Any]:
    return get_success_data(api.lock_finding(finding_id, RESEARCHER_HEADERS))


def publish_finding(
    finding_id: str, api: ApiClient = api_client, headers=None
) -> Dict[str, Any]:
    """Publication is refused when the publisher authored the finding, so the
    default publisher is the research lead while findings are authored by the
    researcher."""
    return get_success_data(
        api.publish_finding(finding_id, headers or RESEARCH_LEAD_HEADERS)
    )


def draft_readout(
    study_id: str,
    decision_id: str,
    cited_finding_ids: Sequence[str],
    api: ApiClient = api_client,
    expected_study_version: Optional[int] = None,
    headers=None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Drafting requires the client's last observed study ``version``; re-read the
    study when the caller did not supply one."""
    if expected_study_version is None:
        study = get_success_data(api.get_study(study_id, RESEARCHER_HEADERS))
        expected_study_version = study["version"]
    payload = factories.create_readout_payload(
        decision_id, list(cited_finding_ids), expected_study_version, **overrides
    )
    return get_success_data(
        api.create_readout(study_id, payload, headers or RESEARCHER_HEADERS)
    )


def deliver_readout(readout_id: str, api: ApiClient = api_client) -> Dict[str, Any]:
    return get_success_data(api.deliver_readout(readout_id, RESEARCHER_HEADERS))


def respond_to_readout(
    readout_id: str,
    outcome: str = "ACCEPTED",
    api: ApiClient = api_client,
    note: Optional[str] = None,
    headers=None,
) -> Dict[str, Any]:
    payload = factories.respond_to_readout_payload(outcome, note)
    return get_success_data(
        api.respond_to_readout(readout_id, payload, headers or STAKEHOLDER_HEADERS)
    )


def open_follow_up(
    readout_id: str,
    api: ApiClient = api_client,
    owner_user_id: str = STAKEHOLDER_USER_ID,
    due_date: str = "2026-09-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.create_follow_up_payload(owner_user_id, due_date, **overrides)
    return get_success_data(
        api.create_follow_up(readout_id, payload, STAKEHOLDER_HEADERS)
    )


def settle(
    pool_id: str,
    study_id: str,
    mode: str,
    api: ApiClient = api_client,
    expected_pool_version: Optional[int] = None,
) -> Dict[str, Any]:
    if expected_pool_version is None:
        pool = get_success_data(
            api.get_participant_pool(pool_id, RESEARCH_OPS_ADMIN_HEADERS)
        )
        expected_pool_version = pool["version"]
    payload = factories.create_incentive_settlement_payload(
        study_id, mode, expected_pool_version
    )
    return get_success_data(
        api.create_incentive_settlement(pool_id, payload, RESEARCH_OPS_ADMIN_HEADERS)
    )


# ---------------------------------------------------------------------------
# Read-back shortcuts
# ---------------------------------------------------------------------------
def read_pool(pool_id: str, api: ApiClient = api_client) -> Dict[str, Any]:
    return get_success_data(
        api.get_participant_pool(pool_id, RESEARCH_OPS_ADMIN_HEADERS)
    )


def read_participant(participant_id: str, api: ApiClient = api_client) -> Dict[str, Any]:
    return get_success_data(api.get_participant(participant_id, RESEARCHER_HEADERS))


def read_study(study_id: str, api: ApiClient = api_client) -> Dict[str, Any]:
    return get_success_data(api.get_study(study_id, RESEARCHER_HEADERS))


def read_request(request_id: str, api: ApiClient = api_client) -> Dict[str, Any]:
    return get_success_data(api.get_research_request(request_id, RESEARCH_LEAD_HEADERS))


def read_decision(decision_id: str, api: ApiClient = api_client) -> Dict[str, Any]:
    return get_success_data(api.get_roadmap_decision(decision_id, STAKEHOLDER_HEADERS))


def read_recruitment(recruitment_id: str, api: ApiClient = api_client) -> Dict[str, Any]:
    return get_success_data(api.get_recruitment(recruitment_id, RESEARCHER_HEADERS))


def read_artifact(artifact_id: str, api: ApiClient = api_client) -> Dict[str, Any]:
    return get_success_data(api.get_artifact(artifact_id, RESEARCHER_HEADERS))


def read_consent(consent_id: str, api: ApiClient = api_client) -> Dict[str, Any]:
    return get_success_data(api.get_consent_record(consent_id, PRIVACY_OFFICER_HEADERS))


def read_theme(theme_id: str, api: ApiClient = api_client) -> Dict[str, Any]:
    return get_success_data(api.get_theme(theme_id, RESEARCHER_HEADERS))


def read_finding(finding_id: str, api: ApiClient = api_client) -> Dict[str, Any]:
    return get_success_data(api.get_finding(finding_id, RESEARCHER_HEADERS))


def read_readout(readout_id: str, api: ApiClient = api_client) -> Dict[str, Any]:
    return get_success_data(api.get_readout(readout_id, RESEARCHER_HEADERS))


def read_metrics(study_id: str, api: ApiClient = api_client) -> Dict[str, Any]:
    return get_success_data(api.get_study_metrics(study_id, RESEARCHER_HEADERS))


# ===========================================================================
# Tier 1 - state progression
# ===========================================================================
def setup_approved_request(
    api: ApiClient = api_client,
    method: str = "INTERVIEW",
    question_type: str = "DISCOVERY",
    evidence_gap: str = "FULL",
    reversibility: str = "IRREVERSIBLE",
    impacted_user_count: int = 12000,
    decision_deadline: str = "2026-10-01T00:00:00Z",
    decision: Optional[Dict[str, Any]] = None,
    requester_headers=None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A decision plus a request triaged `APPROVED` with ``approved_method`` pinned
    to ``method``, which is the join a study creation has to satisfy."""
    if decision is None:
        decision = create_decision(
            api,
            reversibility=reversibility,
            impacted_user_count=impacted_user_count,
            decision_deadline=decision_deadline,
        )
    request = create_request(
        decision["id"],
        api,
        headers=requester_headers,
        question_type=question_type,
        evidence_gap=evidence_gap,
        **overrides,
    )
    request = triage_request(
        request["id"], "APPROVED", method_override=method, api=api
    )
    return {"decision": decision, "request": request}


def setup_request_needing_reframing(
    api: ApiClient = api_client,
    reason: str = "Question is too broad to field",
    **overrides: Any,
) -> Dict[str, Any]:
    """A request sitting in `NEEDS_REFRAMING`, which is where the bounded
    reframing loop starts."""
    decision = create_decision(api, **overrides.pop("decision_overrides", {}))
    request = create_request(decision["id"], api, **overrides)
    request = triage_request(request["id"], "NEEDS_REFRAMING", reason=reason, api=api)
    return {"decision": decision, "request": request}


def setup_pool_with_participants(
    api: ApiClient = api_client,
    participant_count: int = 3,
    segment: str = "POWER_USER",
    locale: str = "en-US",
    ref_prefix: str = "p",
    **pool_overrides: Any,
) -> Dict[str, Any]:
    pool = create_pool(api, **pool_overrides)
    participants = enroll_participants(
        pool["id"],
        participant_count,
        api,
        segment=segment,
        locale=locale,
        ref_prefix=ref_prefix,
    )
    return {"pool": read_pool(pool["id"], api), "participants": participants}


def setup_planned_study(
    api: ApiClient = api_client,
    method: str = "INTERVIEW",
    participant_count: int = 3,
    pool_overrides: Optional[Dict[str, Any]] = None,
    request_overrides: Optional[Dict[str, Any]] = None,
    **study_overrides: Any,
) -> Dict[str, Any]:
    """A study freshly opened: `PLANNED` on the execution dimension and
    `NOT_STARTED` on the recruitment dimension."""
    intake = setup_approved_request(api, method=method, **(request_overrides or {}))
    panel = setup_pool_with_participants(
        api, participant_count=participant_count, **(pool_overrides or {})
    )
    study = create_study(
        intake["request"]["id"],
        panel["pool"]["id"],
        api,
        method=method,
        **study_overrides,
    )
    return {
        "decision": intake["decision"],
        "request": intake["request"],
        "pool": panel["pool"],
        "participants": panel["participants"],
        "study": study,
    }


def setup_guide_approved_study(
    api: ApiClient = api_client,
    guide_version_label: str = "G1",
    guide_question_count: int = 8,
    **overrides: Any,
) -> Dict[str, Any]:
    """A study whose guide has been written and approved, so `guide_status` is
    `APPROVED` and the version is pinned."""
    ctx = setup_planned_study(api, **overrides)
    write_guide(
        ctx["study"]["id"],
        api,
        guide_version_label=guide_version_label,
        guide_question_count=guide_question_count,
    )
    ctx["study"] = approve_guide(ctx["study"]["id"], api)
    return ctx


def setup_fielding_study(api: ApiClient = api_client, **overrides: Any) -> Dict[str, Any]:
    """A study in the field, which is the precondition every invitation needs."""
    ctx = setup_guide_approved_study(api, **overrides)
    ctx["study"] = field_study(ctx["study"]["id"], api)
    return ctx


# ===========================================================================
# Tier 2 - entity hierarchy: invitations, consent, sessions, artifacts
# ===========================================================================
def setup_invited_recruitments(
    api: ApiClient = api_client,
    invite_count: Optional[int] = None,
    participant_count: int = 3,
    **overrides: Any,
) -> Dict[str, Any]:
    """Named invitations, each reserving money against the pool at the surcharge
    tier implied by the pool's pre-call utilization."""
    ctx = setup_fielding_study(api, participant_count=participant_count, **overrides)
    how_many = participant_count if invite_count is None else invite_count
    ctx["recruitments"] = [
        invite(ctx["study"]["id"], ctx["participants"][index]["id"], api)
        for index in range(how_many)
    ]
    ctx["study"] = read_study(ctx["study"]["id"], api)
    ctx["pool"] = read_pool(ctx["pool"]["id"], api)
    return ctx


def setup_consented_recruitments(
    api: ApiClient = api_client,
    consent_scopes: Optional[Sequence[str]] = None,
    retention_days: int = 120,
    **overrides: Any,
) -> Dict[str, Any]:
    """Invitations with consent already on file for every invited participant."""
    ctx = setup_invited_recruitments(api, **overrides)
    ctx["consents"] = [
        grant_consent(
            recruitment["participant_id"],
            ctx["study"]["id"],
            api,
            scopes=consent_scopes,
            retention_days=retention_days,
        )
        for recruitment in ctx["recruitments"]
    ]
    return ctx


def setup_screened_in_recruitments(
    api: ApiClient = api_client, **overrides: Any
) -> Dict[str, Any]:
    ctx = setup_consented_recruitments(api, **overrides)
    ctx["recruitments"] = [
        screen(recruitment["id"], api) for recruitment in ctx["recruitments"]
    ]
    ctx["study"] = read_study(ctx["study"]["id"], api)
    return ctx


def setup_scheduled_sessions(
    api: ApiClient = api_client,
    scheduled_start: str = "2026-08-05T14:00:00Z",
    scheduled_end: str = "2026-08-05T15:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Every screened-in candidate booked into the same slot; the buffer rule is a
    per-participant rule, so distinct participants never clash."""
    ctx = setup_screened_in_recruitments(api, **overrides)
    ctx["recruitments"] = [
        schedule(recruitment["id"], scheduled_start, scheduled_end, api)
        for recruitment in ctx["recruitments"]
    ]
    ctx["study"] = read_study(ctx["study"]["id"], api)
    return ctx


def setup_completed_sessions(
    api: ApiClient = api_client,
    artifact_type: Optional[str] = "TRANSCRIPT",
    contains_pii: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """Completed sessions, each carrying one registered artifact so evidence links
    have something to cite."""
    ctx = setup_scheduled_sessions(api, **overrides)
    ctx["recruitments"] = [
        complete_session(recruitment["id"], api) for recruitment in ctx["recruitments"]
    ]
    ctx["artifacts"] = []
    if artifact_type is not None:
        ctx["artifacts"] = [
            register_artifact(
                recruitment["id"], api, artifact_type=artifact_type, contains_pii=contains_pii
            )
            for recruitment in ctx["recruitments"]
        ]
    ctx["study"] = read_study(ctx["study"]["id"], api)
    ctx["pool"] = read_pool(ctx["pool"]["id"], api)
    return ctx


def setup_study_in_analysis(api: ApiClient = api_client, **overrides: Any) -> Dict[str, Any]:
    """Completed sessions with fielding closed, which is the door that lets a
    finding be locked and the binding settlement mode run."""
    ctx = setup_completed_sessions(api, **overrides)
    ctx["study"] = close_fielding(ctx["study"]["id"], api)
    return ctx


# ===========================================================================
# Tier 3 - full lifecycle shortcuts through the repository and readouts
# ===========================================================================
def setup_draft_finding_with_links(
    api: ApiClient = api_client,
    weight_classes: Sequence[str] = ("DIRECT_QUOTE", "DIRECT_QUOTE", "DIRECT_QUOTE"),
    severity: str = "MEDIUM",
    in_analysis: bool = True,
    theme_label: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """One theme, one draft finding and one evidence link per artifact, so the
    finding's distinct participant count equals the number of links."""
    participant_count = overrides.pop("participant_count", len(weight_classes))
    builder = setup_study_in_analysis if in_analysis else setup_completed_sessions
    ctx = builder(api, participant_count=participant_count, **overrides)
    ctx["theme"] = create_theme(api, label=theme_label)
    ctx["finding"] = create_finding(
        ctx["study"]["id"], ctx["theme"]["id"], api, severity=severity
    )
    ctx["links"] = []
    for index, weight_class in enumerate(weight_classes):
        ctx["links"].append(
            link_evidence(
                ctx["finding"]["id"],
                ctx["artifacts"][index]["id"],
                api,
                weight_class=weight_class,
            )
        )
    ctx["finding"] = read_finding(ctx["finding"]["id"], api)
    return ctx


def setup_locked_finding(api: ApiClient = api_client, **overrides: Any) -> Dict[str, Any]:
    """A finding whose evidence set is final, so its strength reads under the
    corroborated variant."""
    ctx = setup_draft_finding_with_links(api, **overrides)
    ctx["finding"] = lock_finding(ctx["finding"]["id"], api)
    return ctx


def setup_published_finding(
    api: ApiClient = api_client, publisher_headers=None, **overrides: Any
) -> Dict[str, Any]:
    """A published finding, which is the only kind that carries theme weight."""
    ctx = setup_locked_finding(api, **overrides)
    ctx["finding"] = publish_finding(ctx["finding"]["id"], api, headers=publisher_headers)
    ctx["theme"] = read_theme(ctx["theme"]["id"], api)
    return ctx


def setup_drafted_readout(api: ApiClient = api_client, **overrides: Any) -> Dict[str, Any]:
    ctx = setup_published_finding(api, **overrides)
    ctx["readout"] = draft_readout(
        ctx["study"]["id"], ctx["decision"]["id"], [ctx["finding"]["id"]], api
    )
    ctx["study"] = read_study(ctx["study"]["id"], api)
    return ctx


def setup_delivered_readout(api: ApiClient = api_client, **overrides: Any) -> Dict[str, Any]:
    ctx = setup_drafted_readout(api, **overrides)
    ctx["readout"] = deliver_readout(ctx["readout"]["id"], api)
    ctx["study"] = read_study(ctx["study"]["id"], api)
    return ctx


def setup_accepted_readout(
    api: ApiClient = api_client, note: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """A readout accepted by the stakeholder who raised the request, which closes
    the study and its request and moves decision confidence."""
    ctx = setup_delivered_readout(api, **overrides)
    ctx["readout"] = respond_to_readout(
        ctx["readout"]["id"], "ACCEPTED", api, note=note
    )
    ctx["study"] = read_study(ctx["study"]["id"], api)
    ctx["request"] = read_request(ctx["request"]["id"], api)
    ctx["decision"] = read_decision(ctx["decision"]["id"], api)
    ctx["theme"] = read_theme(ctx["theme"]["id"], api)
    return ctx


# ===========================================================================
# Tier 4 - accumulation and threshold targeting
# ===========================================================================
def setup_pool_with_reservations(
    api: ApiClient = api_client,
    reservation_count: int = 2,
    participant_count: int = 4,
    incentive_amount_cents: int = 5000,
    pool_overrides: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Walks the pool's utilization up one named invitation at a time, so a caller
    can land the next reservation on a chosen surcharge tier."""
    return setup_invited_recruitments(
        api,
        invite_count=reservation_count,
        participant_count=participant_count,
        incentive_amount_cents=incentive_amount_cents,
        pool_overrides=pool_overrides,
        **overrides,
    )


def setup_participant_with_one_strike(
    api: ApiClient = api_client,
    scheduled_start: str = "2026-08-05T14:00:00Z",
    scheduled_end: str = "2026-08-05T15:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """One no-show already recorded against the first participant, so the next
    no-show is their second strike."""
    ctx = setup_scheduled_sessions(
        api, scheduled_start=scheduled_start, scheduled_end=scheduled_end, **overrides
    )
    ctx["recruitments"][0] = record_no_show(ctx["recruitments"][0]["id"], api)
    ctx["participants"][0] = read_participant(ctx["participants"][0]["id"], api)
    ctx["pool"] = read_pool(ctx["pool"]["id"], api)
    ctx["study"] = read_study(ctx["study"]["id"], api)
    return ctx


def setup_theme_chain(
    api: ApiClient = api_client, depth: int = 3, label_prefix: str = "Theme"
) -> List[Dict[str, Any]]:
    """A chain of nested themes, one level per hop, for rollup and depth work."""
    chain: List[Dict[str, Any]] = []
    parent_id = None
    for level in range(1, depth + 1):
        theme = create_theme(
            api,
            label=f"{label_prefix}-L{level}-{len(chain)}-{parent_id or 'root'}"[:120],
            parent_theme_id=parent_id,
        )
        chain.append(theme)
        parent_id = theme["id"]
    return chain


def setup_dual_findings_on_one_study(
    api: ApiClient = api_client,
    method: str = "DIARY_STUDY",
    weight_class: str = "OBSERVED_BEHAVIOR",
    participant_count: int = 3,
    severity: str = "MEDIUM",
    publish: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """Two findings of one study under one theme, each citing the same artifacts,
    which is the shape the evidence-withdrawal cascade walks."""
    ctx = setup_study_in_analysis(
        api, method=method, participant_count=participant_count, **overrides
    )
    ctx["theme"] = create_theme(api)
    findings = []
    links: List[List[Dict[str, Any]]] = []
    for _ in range(2):
        finding = create_finding(
            ctx["study"]["id"], ctx["theme"]["id"], api, severity=severity
        )
        finding_links = [
            link_evidence(finding["id"], artifact["id"], api, weight_class=weight_class)
            for artifact in ctx["artifacts"]
        ]
        finding = lock_finding(finding["id"], api)
        if publish:
            finding = publish_finding(finding["id"], api)
        findings.append(finding)
        links.append(finding_links)
    ctx["findings"] = findings
    ctx["finding_links"] = links
    ctx["theme"] = read_theme(ctx["theme"]["id"], api)
    return ctx


def setup_locked_decision_on_dual_findings(
    api: ApiClient = api_client, **overrides: Any
) -> Dict[str, Any]:
    """A decision locked on accepted evidence: two published findings cited by one
    accepted readout, then the stakeholder's lock."""
    ctx = setup_dual_findings_on_one_study(api, **overrides)
    ctx["readout"] = draft_readout(
        ctx["study"]["id"],
        ctx["decision"]["id"],
        [finding["id"] for finding in ctx["findings"]],
        api,
    )
    ctx["readout"] = deliver_readout(ctx["readout"]["id"], api)
    ctx["readout"] = respond_to_readout(ctx["readout"]["id"], "ACCEPTED", api)
    ctx["decision"] = get_success_data(
        api.lock_roadmap_decision(ctx["decision"]["id"], STAKEHOLDER_HEADERS)
    )
    ctx["study"] = read_study(ctx["study"]["id"], api)
    ctx["theme"] = read_theme(ctx["theme"]["id"], api)
    return ctx


def setup_two_fielding_studies_sharing_pool(
    api: ApiClient = api_client,
    windows: Sequence[Sequence[str]] = (
        ("2026-08-03T00:00:00Z", "2026-08-21T00:00:00Z"),
        ("2026-08-05T00:00:00Z", "2026-08-25T00:00:00Z"),
    ),
    participant_count: int = 4,
    method: str = "INTERVIEW",
    pool_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Two studies of one pool already in the field, which exhausts the pool's
    concurrent-fielding headroom for any overlapping window."""
    panel = setup_pool_with_participants(
        api, participant_count=participant_count, **(pool_overrides or {})
    )
    studies = []
    for start, end in windows:
        intake = setup_approved_request(api, method=method)
        study = create_study(
            intake["request"]["id"],
            panel["pool"]["id"],
            api,
            method=method,
            fielding_start=start,
            fielding_end=end,
        )
        write_guide(study["id"], api)
        approve_guide(study["id"], api)
        studies.append(field_study(study["id"], api))
    return {
        "pool": read_pool(panel["pool"]["id"], api),
        "participants": panel["participants"],
        "studies": studies,
    }


# ===========================================================================
# Tier 5 - finalization and terminal states
# ===========================================================================
def setup_settled_study(
    api: ApiClient = api_client, mode: str = "CHRONOLOGICAL_ACTUAL", **overrides: Any
) -> Dict[str, Any]:
    """A study whose incentives have already been settled bindingly, so a second
    binding run is refused."""
    ctx = setup_study_in_analysis(api, **overrides)
    ctx["settlement"] = settle(ctx["pool"]["id"], ctx["study"]["id"], mode, api)
    ctx["pool"] = read_pool(ctx["pool"]["id"], api)
    return ctx


def setup_retracted_finding_via_revocation(
    api: ApiClient = api_client, **overrides: Any
) -> Dict[str, Any]:
    """A published finding pulled back to `RETRACTED` by revoking the consent that
    covered its evidence."""
    ctx = setup_published_finding(api, **overrides)
    consent = ctx["consents"][0]
    ctx["revoked_consent"] = revoke_consent(consent["id"], api)
    ctx["finding"] = read_finding(ctx["finding"]["id"], api)
    ctx["theme"] = read_theme(ctx["theme"]["id"], api)
    return ctx


def setup_closed_study(api: ApiClient = api_client, **overrides: Any) -> Dict[str, Any]:
    """The whole chain closed out: readout accepted, study `CLOSED`, request
    `CLOSED`."""
    return setup_accepted_readout(api, **overrides)

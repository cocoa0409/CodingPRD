"""Composite setup helpers for the Prior Authorization UM test suite.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Helpers use get_success_data() so setup
failures surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    appeal_decision_payload,
    appeal_payload,
    audit_finding_payload,
    clock_payload,
    create_criteria_set_payload,
    create_guideline_version_payload,
    create_prior_auth_request_payload,
    create_provider_payload,
    delegation_arrangement_payload,
    gold_card_evaluation_payload,
    md_decision_payload,
    p2p_schedule_payload,
    reviewer_decision_payload,
)
from .test_users import (
    TEST_USERS,
    make_appeals_reviewer_headers,
    make_clinical_reviewer_headers,
    make_medical_director_headers,
)

ADMIN = TEST_USERS["um_admin_headers"]
EDITOR = TEST_USERS["policy_editor_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
CLERK = TEST_USERS["appeals_clerk_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_provider(name="Test Provider", npi=None, specialty=None) -> dict:
    """Register a provider (PRD §3.6). Returns the created Provider."""
    overrides = {}
    if npi is not None:
        overrides["npi"] = npi
    if specialty is not None:
        overrides["specialty"] = specialty
    payload = create_provider_payload(name=name, **overrides)
    return get_success_data(api_client.create_provider(payload, ADMIN), 201)


def get_provider(provider_id) -> dict:
    return get_success_data(api_client.get_provider(provider_id, ADMIN))


def create_criteria_set(
    name="Spine Imaging Criteria",
    line_of_business="COMMERCIAL",
    service_category="IMAGING",
) -> dict:
    """Create a criteria set in DRAFT (PRD §3.1)."""
    payload = create_criteria_set_payload(
        name=name, line_of_business=line_of_business,
        service_category=service_category,
    )
    return get_success_data(api_client.create_criteria_set(payload, EDITOR), 201)


def get_criteria_set(criteria_set_id) -> dict:
    return get_success_data(api_client.get_criteria_set(criteria_set_id, EDITOR))


def transition_criteria_set(criteria_set_id, to_status) -> dict:
    return get_success_data(
        api_client.transition_criteria_set(
            criteria_set_id, {"to_status": to_status}, EDITOR,
        )
    )


def create_guideline_version(
    criteria_set_id,
    version_label="1.0",
    content="Clinical criteria content",
    auto_approve_eligible=False,
    effective_from="2026-01-01T00:00:00Z",
    effective_until=None,
    supersedes_version_id=None,
) -> dict:
    """Create a DRAFT guideline version in the set (PRD §3.1)."""
    payload = create_guideline_version_payload(
        version_label=version_label, content=content,
        auto_approve_eligible=auto_approve_eligible,
        effective_from=effective_from,
    )
    if effective_until is not None:
        payload["effective_until"] = effective_until
    if supersedes_version_id is not None:
        payload["supersedes_version_id"] = supersedes_version_id
    return get_success_data(
        api_client.create_guideline_version(criteria_set_id, payload, EDITOR), 201,
    )


def get_guideline_version(guideline_version_id) -> dict:
    return get_success_data(
        api_client.get_guideline_version(guideline_version_id, EDITOR)
    )


def transition_guideline_version(
    guideline_version_id, to_status, expected_criteria_set_version,
) -> dict:
    """Publish or retire a guideline version (OCC-guarded, PRD §2.6)."""
    payload = {
        "to_status": to_status,
        "expected_criteria_set_version": expected_criteria_set_version,
    }
    return get_success_data(
        api_client.transition_guideline_version(guideline_version_id, payload, EDITOR)
    )


def publish_guideline_version(guideline_version_id, expected_criteria_set_version) -> dict:
    return transition_guideline_version(
        guideline_version_id, "PUBLISHED", expected_criteria_set_version,
    )


# ---------------------------------------------------------------------------
# Tier 2: composite environment builders
# ---------------------------------------------------------------------------

def make_active_criteria_set(
    name="Spine Imaging Criteria",
    line_of_business="COMMERCIAL",
    service_category="IMAGING",
    version_label="1.0",
    content="Clinical criteria content",
    auto_approve_eligible=False,
    effective_from="2026-01-01T00:00:00Z",
    effective_until=None,
):
    """Criteria set with one PUBLISHED guideline version, transitioned to ACTIVE.

    Returns (criteria_set, guideline_version); the criteria set dict is the
    refreshed post-activation representation.
    """
    cs = create_criteria_set(
        name=name, line_of_business=line_of_business,
        service_category=service_category,
    )
    gv = create_guideline_version(
        cs["id"], version_label=version_label, content=content,
        auto_approve_eligible=auto_approve_eligible,
        effective_from=effective_from, effective_until=effective_until,
    )
    publish_guideline_version(gv["id"], expected_criteria_set_version=cs["version"])
    cs = transition_criteria_set(cs["id"], "ACTIVE")
    return cs, gv


def basic_um_environment(**set_overrides):
    """Active COMMERCIAL/IMAGING criteria set (non-auto-eligible guideline)
    plus one provider. Returns (provider, criteria_set, guideline_version)."""
    cs, gv = make_active_criteria_set(**set_overrides)
    provider = create_provider()
    return provider, cs, gv


# ---------------------------------------------------------------------------
# Tier 3: request intake and decision ladders
# ---------------------------------------------------------------------------

def intake_request(
    provider_id,
    criteria_set_id,
    member_ref="M-01",
    service_code="72148",
    urgency="STANDARD",
    intake_channel="FAX",
    documentation_complete=False,
    extra_fields=None,
) -> dict:
    """Intake one request (PRD §3.2). Returns the created PriorAuthRequest."""
    payload = create_prior_auth_request_payload(
        provider_id=provider_id, criteria_set_id=criteria_set_id,
        member_ref=member_ref, service_code=service_code, urgency=urgency,
        intake_channel=intake_channel,
        documentation_complete=documentation_complete,
    )
    if extra_fields:
        payload.update(extra_fields)
    return get_success_data(
        api_client.create_prior_auth_request(payload, INTAKE), 201,
    )


def pended_request(provider_id, criteria_set_id, **kwargs) -> dict:
    """Intake a request that lands in PENDED_REVIEW (neither auto lane fires)."""
    req = intake_request(provider_id, criteria_set_id, **kwargs)
    assert req["status"] == "PENDED_REVIEW", (
        f"Setup expected PENDED_REVIEW, got {req['status']}"
    )
    return req


def reviewer_decide(request_id, decision, reason_code=None, user_id="u-rev-1") -> dict:
    """Post a reviewer-tier decision (PRD §3.3). Returns the updated request."""
    headers = make_clinical_reviewer_headers(user_id)
    return get_success_data(
        api_client.reviewer_decision(
            request_id, reviewer_decision_payload(decision, reason_code), headers,
        )
    )


def md_decide(request_id, decision, reason_code=None, user_id="u-md-1") -> dict:
    """Post a medical-director decision (PRD §3.3). Returns the updated request."""
    headers = make_medical_director_headers(user_id)
    return get_success_data(
        api_client.md_decision(
            request_id, md_decision_payload(decision, reason_code), headers,
        )
    )


def escalated_request(
    provider_id, criteria_set_id, reviewer_user_id="u-rev-1", **kwargs,
) -> dict:
    """Pended request escalated to ESCALATED_MD by the given reviewer."""
    req = pended_request(provider_id, criteria_set_id, **kwargs)
    return reviewer_decide(req["id"], "ESCALATE", user_id=reviewer_user_id)


def list_request_determinations(request_id) -> list:
    return get_success_data(
        api_client.list_determinations(ADMIN, params={"request_id": request_id})
    )


def get_request_determination(request_id) -> dict:
    """Fetch the single non-void determination of a decided request."""
    rows = list_request_determinations(request_id)
    assert len(rows) == 1, (
        f"Setup expected exactly 1 determination for {request_id}, got {len(rows)}"
    )
    return rows[0]


def get_determination(determination_id) -> dict:
    return get_success_data(api_client.get_determination(determination_id, ADMIN))


def approved_determination(
    provider_id, criteria_set_id, member_ref="M-01",
    reviewer_user_id="u-rev-1", **kwargs,
):
    """Intake a pended request and APPROVE it at the reviewer tier.
    Returns (request, determination)."""
    req = pended_request(provider_id, criteria_set_id, member_ref=member_ref, **kwargs)
    reviewer_decide(
        req["id"], "APPROVE", reason_code="MEDICAL_NECESSITY_MET",
        user_id=reviewer_user_id,
    )
    return req, get_request_determination(req["id"])


def denied_determination(
    provider_id, criteria_set_id, member_ref="M-01",
    deny_reason_code="MEDICAL_NECESSITY_NOT_MET",
    reviewer_user_id="u-rev-1", **kwargs,
):
    """Intake a pended request and DENY it at the reviewer tier.
    Returns (request, determination)."""
    req = pended_request(provider_id, criteria_set_id, member_ref=member_ref, **kwargs)
    reviewer_decide(
        req["id"], "DENY", reason_code=deny_reason_code,
        user_id=reviewer_user_id,
    )
    return req, get_request_determination(req["id"])


def accumulate_human_determinations(
    provider_id,
    criteria_set_id,
    approvals=0,
    denials=0,
    member_prefix="M",
    reviewer_user_id="u-rev-1",
    deny_reason_code="MEDICAL_NECESSITY_NOT_MET",
    urgency="STANDARD",
    service_code="72148",
) -> list:
    """Intake FAX/incomplete requests (the rules lane never fires) and decide
    each at the reviewer tier: `approvals` approvals first, then `denials`
    denials. Returns the created determinations in issuance order.

    Note: on a GOLD_CARDED provider whose gold-card category equals the
    criteria set's service_category, the gold lane (PRD §3.2) would
    auto-approve these intakes — callers targeting human-lane decisions on a
    gold-carded provider must route through a criteria set whose
    service_category does not match the provider's gold-card category.
    """
    determinations = []
    seq = 0
    for decision, reason, count in (
        ("APPROVE", "MEDICAL_NECESSITY_MET", approvals),
        ("DENY", deny_reason_code, denials),
    ):
        for _ in range(count):
            seq += 1
            req = pended_request(
                provider_id, criteria_set_id,
                member_ref=f"{member_prefix}-{seq:02d}",
                urgency=urgency, service_code=service_code,
            )
            reviewer_decide(
                req["id"], decision, reason_code=reason, user_id=reviewer_user_id,
            )
            determinations.append(get_request_determination(req["id"]))
    return determinations


# ---------------------------------------------------------------------------
# Tier 4: gold-card program
# ---------------------------------------------------------------------------

def run_gold_card_evaluation(provider_id, service_category="IMAGING") -> dict:
    """Run a gold-card eligibility evaluation (PRD §3.6). Returns the record."""
    return get_success_data(
        api_client.create_gold_card_evaluation(
            provider_id, gold_card_evaluation_payload(service_category), ADMIN,
        ),
        201,
    )


def list_gold_card_evaluations(provider_id) -> list:
    return get_success_data(api_client.list_gold_card_evaluations(provider_id, ADMIN))


def make_gold_carded_provider(criteria_set_id, service_category="IMAGING",
                              name="Gold Provider"):
    """Provider with 10 reviewer approvals on the given set, then a granted
    gold-card evaluation. Returns (provider_after_grant, evaluation_record)."""
    provider = create_provider(name=name)
    accumulate_human_determinations(provider["id"], criteria_set_id, approvals=10)
    evaluation = run_gold_card_evaluation(provider["id"], service_category)
    return get_provider(provider["id"]), evaluation


# ---------------------------------------------------------------------------
# Tier 5: peer-to-peer conferences
# ---------------------------------------------------------------------------

def scheduled_conference(
    request_id,
    md_user_id="u-md-1",
    scheduled_start="2026-08-10T14:00:00Z",
    scheduled_end="2026-08-10T15:00:00Z",
) -> dict:
    """Schedule a peer-to-peer conference on an escalated request (PRD §3.3)."""
    headers = make_medical_director_headers(md_user_id)
    return get_success_data(
        api_client.schedule_p2p_conference(
            request_id,
            p2p_schedule_payload(scheduled_start, scheduled_end),
            headers,
        ),
        201,
    )


def resolve_conference(conference_id, outcome="COMPLETED", md_user_id="u-md-1") -> dict:
    headers = make_medical_director_headers(md_user_id)
    return get_success_data(
        api_client.resolve_p2p_conference(conference_id, {"outcome": outcome}, headers)
    )


def list_conferences(request_id) -> list:
    return get_success_data(api_client.list_p2p_conferences(request_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 6: appeals
# ---------------------------------------------------------------------------

def file_appeal(determination_id, appeal_reason="Appeal reason") -> dict:
    """File an appeal against a FINAL determination (PRD §3.5)."""
    return get_success_data(
        api_client.create_appeal(
            determination_id, appeal_payload(appeal_reason), CLERK,
        ),
        201,
    )


def begin_appeal_review(appeal_id, user_id="u-ar-1") -> dict:
    headers = make_appeals_reviewer_headers(user_id)
    return get_success_data(api_client.begin_appeal_review(appeal_id, headers))


def decide_appeal(appeal_id, outcome, user_id="u-ar-1", rationale=None) -> dict:
    headers = make_appeals_reviewer_headers(user_id)
    return get_success_data(
        api_client.decide_appeal(
            appeal_id, appeal_decision_payload(outcome, rationale), headers,
        )
    )


def get_appeal(appeal_id) -> dict:
    return get_success_data(api_client.get_appeal(appeal_id, CLERK))


def setup_appeal_scenario(
    begin_review=False,
    reviewer_user_id="u-rev-1",
    appeals_reviewer_user_id="u-ar-1",
    deny_reason_code="INSUFFICIENT_INFO",
) -> dict:
    """Active set + provider + reviewer-denied request + filed appeal.

    With begin_review=True the appeal is additionally moved to IN_REVIEW
    assigned to appeals_reviewer_user_id. Returns a dict with keys:
    provider, criteria_set, request, determination, appeal.
    """
    provider, cs, _gv = basic_um_environment()
    req, det = denied_determination(
        provider["id"], cs["id"], deny_reason_code=deny_reason_code,
        reviewer_user_id=reviewer_user_id,
    )
    appeal = file_appeal(det["id"])
    if begin_review:
        appeal = begin_appeal_review(appeal["id"], user_id=appeals_reviewer_user_id)
    return {
        "provider": provider,
        "criteria_set": cs,
        "request": req,
        "determination": det,
        "appeal": appeal,
    }


# ---------------------------------------------------------------------------
# Tier 7: delegation oversight
# ---------------------------------------------------------------------------

def create_arrangement(criteria_set_id, delegating_plan_name="Plan X") -> dict:
    """Create a delegation arrangement for a criteria set (PRD §3.7)."""
    return get_success_data(
        api_client.create_delegation_arrangement(
            delegation_arrangement_payload(
                delegating_plan_name=delegating_plan_name,
                criteria_set_id=criteria_set_id,
            ),
            ADMIN,
        ),
        201,
    )


def get_arrangement(arrangement_id) -> dict:
    return get_success_data(
        api_client.get_delegation_arrangement(arrangement_id, COMPLIANCE)
    )


def create_audit_finding(arrangement_id, determination_id,
                         finding_type="NOTICE_DEFICIENT") -> dict:
    return get_success_data(
        api_client.create_audit_finding(
            arrangement_id,
            audit_finding_payload(
                determination_id=determination_id, finding_type=finding_type,
            ),
            COMPLIANCE,
        ),
        201,
    )


def close_audit_finding(finding_id) -> dict:
    return get_success_data(
        api_client.transition_audit_finding(
            finding_id, {"to_status": "CLOSED"}, COMPLIANCE,
        )
    )


def setup_arrangement_with_denied_determinations(n=3) -> dict:
    """Active set + arrangement + provider with `n` reviewer-denied requests
    in the arrangement's scope. Returns dict with provider, criteria_set,
    arrangement, determinations."""
    provider, cs, _gv = basic_um_environment()
    arrangement = create_arrangement(cs["id"])
    determinations = []
    for i in range(n):
        _req, det = denied_determination(
            provider["id"], cs["id"], member_ref=f"M-{i + 1:02d}",
        )
        determinations.append(det)
    return {
        "provider": provider,
        "criteria_set": cs,
        "arrangement": arrangement,
        "determinations": determinations,
    }


# ---------------------------------------------------------------------------
# Tier 8: compliance events and the logical clock
# ---------------------------------------------------------------------------

def list_request_events(request_id, event_type=None) -> list:
    params = {"event_type": event_type} if event_type else None
    return get_success_data(
        api_client.list_request_compliance_events(request_id, ADMIN, params=params)
    )


def list_provider_events(provider_id, event_type=None) -> list:
    params = {"event_type": event_type} if event_type else None
    return get_success_data(
        api_client.list_provider_compliance_events(provider_id, ADMIN, params=params)
    )


def list_all_events(event_type=None) -> list:
    params = {"event_type": event_type} if event_type else None
    return get_success_data(api_client.list_compliance_events(ADMIN, params=params))


def set_clock(to_iso8601) -> dict:
    """Advance the logical clock and run the breach sweep (PRD §2.5).
    Returns {current_utc, requests_flagged, appeals_flagged}."""
    return get_success_data(
        api_client.set_current_utc(clock_payload(to_iso8601), ADMIN)
    )

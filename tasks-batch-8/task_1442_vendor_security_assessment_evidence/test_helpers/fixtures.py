"""Composite setup helpers for multi-step test prerequisites.

Every test runs against a freshly started server with an empty database, so
each helper builds its preconditions from scratch using only PRD-declared
endpoints. Setup calls use get_success_data() so a setup failure surfaces as
a clear "Setup step failed" error rather than a confusing assertion failure.

Vendor-side calls (responses, evidence, progress, disclosures, attestations,
signatures) are ownership-gated for the entity-backed VendorContact role, so
fixtures thread the created contact's id into make_vendor_contact_headers().

Unless a test drives the logical clock explicitly, every timestamp lands on
the startup default 2026-08-01T00:00:00Z (PRD §2.6).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TIER_PROFILES
from .factories import (
    create_acceptance_payload,
    create_alert_payload,
    create_contact_payload,
    create_cycle_payload,
    create_evidence_payload,
    create_exception_payload,
    create_plan_payload,
    create_response_payload,
    create_subprocessor_payload,
    create_template_payload,
    create_tier_policy_payload,
    create_vendor_payload,
    set_clock_payload,
    submit_attestation_payload,
)
from .test_users import TEST_USERS, make_risk_analyst_headers, make_vendor_contact_headers

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["risk_analyst_headers"]
APPROVER = TEST_USERS["security_approver_headers"]

# A second analyst identity for segregation-of-duties-respecting verify calls.
ANALYST_1 = make_risk_analyst_headers("analyst-1")
ANALYST_2 = make_risk_analyst_headers("analyst-2")


def contact_headers(ctx) -> dict:
    """Entity-backed VendorContact headers for the vendor created in ctx."""
    return make_vendor_contact_headers(ctx["contact"]["id"])


# --- Tier 1: atomic builders -------------------------------------------------

def setup_active_policy(**overrides) -> dict:
    """Create the single active AssessmentTierPolicy. Returns the policy."""
    return get_success_data(api_client.create_tier_policy(create_tier_policy_payload(**overrides), ADMIN))


def create_published_template(tiers=("TIER_1",), items=None, title="Baseline Template") -> dict:
    """Create a template in DRAFT and publish it. Returns the PUBLISHED template."""
    payload = create_template_payload(title=title, applies_to_tiers=list(tiers))
    if items is not None:
        payload["items"] = items
    template = get_success_data(api_client.create_template(payload, ANALYST))
    return get_success_data(api_client.publish_template(template["id"], ANALYST))


def register_vendor(tier: str = "TIER_1", with_contact: bool = True, **overrides):
    """Register a vendor whose classification ranks land in `tier` via the
    rank-sum fallback, plus (optionally) one primary VendorContact whose id
    backs vendor-side calls. Returns (vendor, contact)."""
    attrs = dict(TIER_PROFILES[tier])
    attrs.update(overrides)
    vendor = get_success_data(api_client.create_vendor(create_vendor_payload(**attrs), ANALYST))
    contact = None
    if with_contact:
        contact = get_success_data(
            api_client.create_contact(vendor["id"], create_contact_payload(), ANALYST)
        )
    return vendor, contact


def open_cycle(vendor_id: str, template_id: str) -> dict:
    """Create a DRAFT cycle for the vendor with a fresh OCC version (PRD §2.7).
    Returns the created cycle."""
    fresh = get_success_data(api_client.get_vendor(vendor_id, ANALYST))
    return get_success_data(
        api_client.create_cycle(
            vendor_id,
            create_cycle_payload(template_id, fresh["version"]),
            ANALYST,
        )
    )


def issue_cycle(vendor_id: str, cycle_id: str) -> dict:
    return get_success_data(api_client.issue_cycle(vendor_id, cycle_id, ANALYST))


def yes_answers(template: dict) -> list:
    return [{"item_key": item["item_key"], "answer_value": "YES"} for item in template["items"]]


def create_and_submit_response(vendor_id: str, cycle_id: str, contact_headers_: dict, answers: list) -> dict:
    """Create a DRAFT response and submit it. Returns the SUBMITTED response."""
    response = get_success_data(
        api_client.create_response(
            vendor_id, cycle_id, create_response_payload(answers=answers), contact_headers_
        )
    )
    return get_success_data(
        api_client.submit_response(vendor_id, cycle_id, response["id"], contact_headers_)
    )


def get_cycle_response(cycle_id: str) -> dict:
    """Fetch the cycle's single questionnaire response via the list endpoint."""
    responses = get_success_data(api_client.list_cycle_responses(cycle_id, ANALYST))
    assert isinstance(responses, list) and len(responses) == 1, "Expected exactly one response"
    return responses[0]


def get_cycle_artifact(cycle_id: str, artifact_id: str) -> dict:
    artifacts = get_success_data(api_client.list_cycle_evidence(cycle_id, ANALYST))
    for artifact in artifacts:
        if artifact["id"] == artifact_id:
            return artifact
    raise AssertionError(f"Artifact {artifact_id} not found in cycle {cycle_id}")


def score_cycle(vendor_id: str, cycle_id: str) -> dict:
    return get_success_data(api_client.score_cycle(vendor_id, cycle_id, ANALYST))


def upload_evidence(vendor_id: str, cycle_id: str, contact_headers_: dict, **overrides) -> dict:
    return get_success_data(
        api_client.upload_evidence(
            vendor_id, cycle_id, create_evidence_payload(**overrides), contact_headers_
        )
    )


def review_artifact_clean(vendor_id: str, cycle_id: str, artifact_id: str) -> dict:
    """Start then complete an artifact review with no attached exceptions."""
    get_success_data(api_client.start_evidence_review(vendor_id, cycle_id, artifact_id, ANALYST))
    return get_success_data(api_client.complete_artifact_review(vendor_id, cycle_id, artifact_id, ANALYST))


# --- Tier 2/3: lifecycle composites ------------------------------------------

def setup_issued_cycle(tier: str = "TIER_1", items=None, policy_overrides=None) -> dict:
    """Policy + published template + vendor + DRAFT cycle + issued.
    Returns ctx with policy/template/vendor/contact/cycle (cycle ISSUED)."""
    policy = setup_active_policy(**(policy_overrides or {}))
    template = create_published_template(tiers=(tier,), items=items)
    vendor, contact = register_vendor(tier=tier)
    cycle = open_cycle(vendor["id"], template["id"])
    cycle = issue_cycle(vendor["id"], cycle["id"])
    return {"policy": policy, "template": template, "vendor": vendor, "contact": contact, "cycle": cycle}


def setup_scored_cycle(tier: str = "TIER_1", answers=None, items=None, policy_overrides=None) -> dict:
    """Issued cycle + all-YES (or supplied) response submitted + scored passing.
    ctx gains response and the refreshed SCORED cycle."""
    ctx = setup_issued_cycle(tier=tier, items=items, policy_overrides=policy_overrides)
    if answers is None:
        answers = yes_answers(ctx["template"])
    ctx["response"] = create_and_submit_response(
        ctx["vendor"]["id"], ctx["cycle"]["id"], contact_headers(ctx), answers
    )
    ctx["cycle"] = score_cycle(ctx["vendor"]["id"], ctx["cycle"]["id"])
    return ctx


def setup_evidence_review_cycle(tier: str = "TIER_1", evidence_overrides=None, **kw) -> dict:
    """Scored cycle + first artifact uploaded (cycle now EVIDENCE_REVIEW).
    ctx gains artifact and the refreshed cycle."""
    ctx = setup_scored_cycle(tier=tier, **kw)
    artifact = upload_evidence(
        ctx["vendor"]["id"], ctx["cycle"]["id"], contact_headers(ctx), **(evidence_overrides or {})
    )
    ctx["artifact"] = artifact
    ctx["cycle"] = get_success_data(api_client.get_cycle(ctx["cycle"]["id"], ANALYST))
    return ctx


def setup_remediation_cycle(
    tier: str = "TIER_1",
    exception_severities=("MEDIUM",),
    evidence_overrides=None,
    **kw,
) -> dict:
    """Cycle driven to REMEDIATION: artifact reviewed clean, then N exceptions
    created against it, then evidence review completed. ctx gains artifact,
    exceptions, and the REMEDIATION cycle."""
    ctx = setup_evidence_review_cycle(tier=tier, evidence_overrides=evidence_overrides, **kw)
    review_artifact_clean(ctx["vendor"]["id"], ctx["cycle"]["id"], ctx["artifact"]["id"])
    exceptions = []
    for severity in exception_severities:
        exceptions.append(
            get_success_data(
                api_client.create_exception(
                    ctx["vendor"]["id"],
                    ctx["cycle"]["id"],
                    create_exception_payload(
                        severity=severity, evidence_artifact_id=ctx["artifact"]["id"]
                    ),
                    ANALYST,
                )
            )
        )
    ctx["exceptions"] = exceptions
    ctx["cycle"] = get_success_data(
        api_client.complete_evidence_review(ctx["vendor"]["id"], ctx["cycle"]["id"], ANALYST)
    )
    return ctx


def setup_approved_vendor(tier: str = "TIER_1", **kw) -> dict:
    """Full clean pass: cycle APPROVED, vendor posture APPROVED.
    ctx gains artifact and the refreshed terminal cycle + vendor."""
    ctx = setup_evidence_review_cycle(tier=tier, **kw)
    review_artifact_clean(ctx["vendor"]["id"], ctx["cycle"]["id"], ctx["artifact"]["id"])
    ctx["cycle"] = get_success_data(
        api_client.complete_evidence_review(ctx["vendor"]["id"], ctx["cycle"]["id"], ANALYST)
    )
    ctx["vendor"] = get_success_data(api_client.get_vendor(ctx["vendor"]["id"], ANALYST))
    return ctx


def setup_risk_acceptance_review_cycle(tier: str = "TIER_1", exception_severities=("LOW",)) -> dict:
    """Cycle in RISK_ACCEPTANCE_REVIEW via false-positive closure + resolve."""
    ctx = setup_remediation_cycle(tier=tier, exception_severities=exception_severities)
    for exception in ctx["exceptions"]:
        get_success_data(
            api_client.mark_false_positive(
                ctx["vendor"]["id"], ctx["cycle"]["id"], exception["id"],
                {"closure_reason": "re-classified as not applicable"}, ANALYST,
            )
        )
    ctx["cycle"] = get_success_data(
        api_client.resolve_remediation(ctx["vendor"]["id"], ctx["cycle"]["id"], ANALYST)
    )
    return ctx


# --- Tier 4: domain composites ------------------------------------------------

def request_risk_acceptance(ctx, exception_ids, expires_at="2027-01-01T00:00:00Z", requester=None) -> dict:
    """RiskAnalyst requests a risk acceptance. Returns the REQUESTED acceptance."""
    return get_success_data(
        api_client.create_risk_acceptance(
            ctx["vendor"]["id"], ctx["cycle"]["id"],
            create_acceptance_payload(exception_ids, expires_at=expires_at),
            requester or ANALYST,
        )
    )


def approve_acceptance(ctx, acceptance_id: str, approver=None) -> dict:
    """SecurityApprover approves with a fresh OCC cycle version (PRD §2.7)."""
    fresh = get_success_data(api_client.get_cycle(ctx["cycle"]["id"], ANALYST))
    return get_success_data(
        api_client.approve_risk_acceptance(
            ctx["vendor"]["id"], ctx["cycle"]["id"], acceptance_id,
            {"expected_cycle_version": fresh["version"]},
            approver or APPROVER,
        )
    )


def setup_proposed_plan(ctx, exception_ids=None, tasks=None) -> dict:
    """PROPOSED plan covering ctx's exceptions (or the supplied ids)."""
    ids = exception_ids if exception_ids is not None else [e["id"] for e in ctx["exceptions"]]
    payload = create_plan_payload(ids)
    if tasks is not None:
        payload["tasks"] = tasks
    return get_success_data(
        api_client.create_remediation_plan(ctx["vendor"]["id"], ctx["cycle"]["id"], payload, ANALYST)
    )


def setup_completed_plan(ctx, exception_ids=None, acceptor=None):
    """Plan accepted by `acceptor` (default analyst-1) then progressed to
    COMPLETED by the vendor. Returns (plan, acceptor_headers)."""
    acceptor = acceptor or ANALYST_1
    plan = setup_proposed_plan(ctx, exception_ids=exception_ids)
    plan = get_success_data(
        api_client.accept_plan(ctx["vendor"]["id"], ctx["cycle"]["id"], plan["id"], acceptor)
    )
    task_keys = [t["task_key"] for t in plan["tasks"]]
    plan = get_success_data(
        api_client.progress_plan(
            ctx["vendor"]["id"], ctx["cycle"]["id"], plan["id"],
            {"completed_task_keys": task_keys}, contact_headers(ctx),
        )
    )
    return plan, acceptor


def create_alert(vendor_id: str, **overrides) -> dict:
    """PlatformAdmin records a monitoring alert. Returns the OPEN alert."""
    return get_success_data(api_client.create_alert(vendor_id, create_alert_payload(**overrides), ADMIN))


def setup_disclosure_under_review(vendor_id: str, contact_headers_: dict) -> dict:
    """VendorContact discloses a subprocessor; RiskAnalyst starts review.
    Returns the UNDER_REVIEW disclosure."""
    disclosure = get_success_data(
        api_client.create_subprocessor(vendor_id, create_subprocessor_payload(), contact_headers_)
    )
    return get_success_data(
        api_client.start_subprocessor_review(vendor_id, disclosure["id"], ANALYST)
    )


def setup_offboarding_vendor(tier: str = "TIER_1") -> dict:
    """Vendor offboarded from ONBOARDING: posture OFFBOARDING with a fresh
    REQUESTED attestation. Returns ctx with vendor/contact/attestation."""
    setup_active_policy()
    vendor, contact = register_vendor(tier=tier)
    vendor = get_success_data(api_client.offboard_vendor(vendor["id"], ANALYST))
    attestations = get_success_data(api_client.list_attestations(vendor["id"], ANALYST))
    assert len(attestations) == 1, "Offboarding must create exactly one attestation"
    return {"vendor": vendor, "contact": contact, "attestation": attestations[0]}


def set_clock(to_iso8601: str) -> dict:
    """PlatformAdmin advances the logical clock, firing due sweeps (PRD §2.6)."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


def list_schedule_events(vendor_id: str, kind: str = None) -> list:
    params = {"kind": kind} if kind else None
    return get_success_data(api_client.list_reassessment_schedule(vendor_id, ANALYST, params=params))

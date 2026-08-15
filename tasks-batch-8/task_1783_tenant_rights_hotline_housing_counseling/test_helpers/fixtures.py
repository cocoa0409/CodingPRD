"""Composite setup helpers (PRD §3 workflows).

Every helper builds preconditions from scratch against a fresh server using
only PRD-declared endpoints, and uses get_success_data() so setup failures
surface as clear "Setup step failed" errors. Entity-backed roles always
thread the real entity id through make_caller_headers / make_counselor_headers.

Bundle convention: a plain dict with keys
    jurisdiction, author, reviewer, scripts (category -> script), script,
    worker, worker_headers, author_headers, reviewer_headers, primary_category
plus scenario keys (caller, session, case, org, consent, policy, ...) added by
the higher-tier helpers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CERT_EXPIRY, CRITICAL_CASE_FACTS, DEFAULT_CLOCK
from .factories import (
    create_caller_payload,
    create_case_payload,
    create_counselor_payload,
    create_interpreter_payload,
    create_jurisdiction_payload,
    create_legal_aid_org_payload,
    create_retention_policy_payload,
    create_script_payload,
    create_self_help_resource_payload,
    create_session_payload,
)
from .test_users import TEST_USERS, make_caller_headers, make_counselor_headers

ADMIN = TEST_USERS["agency_admin_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
DPO = TEST_USERS["dpo_headers"]
ANALYST = TEST_USERS["analyst_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Tier 0: thin creators (single POST each)
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock (PRD §2.5). Returns {current_utc}."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def run_time_sweep() -> dict:
    """Run the scheduled sweep (PRD §2.5). Returns the counter summary."""
    return get_success_data(api_client.run_time_sweep(ADMIN))


def create_jurisdiction(**overrides) -> dict:
    return get_success_data(
        api_client.create_jurisdiction(create_jurisdiction_payload(**overrides), ADMIN)
    )


def create_counselor(**overrides) -> dict:
    return get_success_data(
        api_client.create_counselor(create_counselor_payload(**overrides), ADMIN)
    )


def create_interpreter(**overrides) -> dict:
    return get_success_data(
        api_client.create_interpreter(create_interpreter_payload(**overrides), ADMIN)
    )


def create_caller(**overrides) -> dict:
    return get_success_data(
        api_client.create_caller(create_caller_payload(**overrides), ANONYMOUS)
    )


def create_legal_aid_org(**overrides) -> dict:
    return get_success_data(
        api_client.create_legal_aid_org(create_legal_aid_org_payload(**overrides), ADMIN)
    )


def create_retention_policy(retention_days=30, jurisdiction_id=None,
                            issue_category=None) -> dict:
    payload = create_retention_policy_payload(
        retention_days=retention_days,
        jurisdiction_id=jurisdiction_id,
        issue_category=issue_category,
    )
    return get_success_data(api_client.create_retention_policy(payload, DPO))


def create_self_help_resource(bundle, script_id, category=None, **overrides) -> dict:
    category = category or bundle["primary_category"]
    payload = create_self_help_resource_payload(
        bundle["jurisdiction"]["id"], script_id, issue_category=category, **overrides
    )
    return get_success_data(
        api_client.create_self_help_resource(payload, bundle["worker_headers"])
    )


# ---------------------------------------------------------------------------
# Tier 1: script chain and counselor training
# ---------------------------------------------------------------------------
def author_submit_publish_script(jurisdiction_id, category, author_id, reviewer_id,
                                 effective_from=DEFAULT_CLOCK, version_no=1,
                                 supersedes_script_id=None,
                                 body="Standard counselor guidance script.") -> dict:
    """Author (DRAFT) -> submit (IN_REVIEW) -> publish (PUBLISHED)."""
    script = get_success_data(api_client.create_script(
        create_script_payload(
            jurisdiction_id, issue_category=category, version_no=version_no,
            body=body, supersedes_script_id=supersedes_script_id,
        ),
        make_counselor_headers(author_id),
    ))
    get_success_data(api_client.transition_script(
        script["id"], {"to_status": "IN_REVIEW"}, make_counselor_headers(author_id)
    ))
    return get_success_data(api_client.transition_script(
        script["id"],
        {"to_status": "PUBLISHED", "effective_from": effective_from},
        make_counselor_headers(reviewer_id),
    ))


def record_training(counselor_id, script_id, score=90) -> dict:
    """Supervisor records a training certification; returns updated counselor."""
    return get_success_data(api_client.create_training_certification(
        counselor_id, {"script_id": script_id, "score": score}, SUPERVISOR
    ))


# ---------------------------------------------------------------------------
# Tier 2: the hotline base chain
# ---------------------------------------------------------------------------
def setup_hotline(categories=("EVICTION",), *, jurisdiction_overrides=None,
                  worker_languages=("en",), script_effective_from=DEFAULT_CLOCK,
                  worker_cert_expiry=CERT_EXPIRY, train_worker=True) -> dict:
    """Jurisdiction + author + reviewer + one PUBLISHED script per category +
    a worker counselor certified for the jurisdiction and (optionally) trained
    on every published script."""
    jur = create_jurisdiction(**(jurisdiction_overrides or {}))
    cats = list(categories)
    author = create_counselor(display_name="Author A", certified_categories=cats,
                              is_script_reviewer=False)
    reviewer = create_counselor(display_name="Reviewer R", certified_categories=cats,
                                is_script_reviewer=True)
    scripts = {}
    for cat in cats:
        scripts[cat] = author_submit_publish_script(
            jur["id"], cat, author["id"], reviewer["id"],
            effective_from=script_effective_from,
            body=f"{cat.title()} guidance v1",
        )
    worker = create_counselor(
        display_name="Worker W",
        languages=list(worker_languages),
        certified_jurisdiction_codes=[jur["code"]],
        certified_categories=cats,
        certification_expires_at=worker_cert_expiry,
        is_script_reviewer=False,
    )
    if train_worker:
        for cat in cats:
            worker = record_training(worker["id"], scripts[cat]["id"], score=90)
    return {
        "jurisdiction": jur,
        "author": author,
        "reviewer": reviewer,
        "scripts": scripts,
        "script": scripts[cats[0]],
        "worker": worker,
        "worker_headers": make_counselor_headers(worker["id"]),
        "author_headers": make_counselor_headers(author["id"]),
        "reviewer_headers": make_counselor_headers(reviewer["id"]),
        "primary_category": cats[0],
    }


# ---------------------------------------------------------------------------
# Tier 3: sessions and cases
# ---------------------------------------------------------------------------
def intake_session(bundle, caller, category=None) -> dict:
    """Public intake of a QUEUED session (interpretation NOT_REQUIRED)."""
    category = category or bundle["primary_category"]
    return get_success_data(api_client.create_session(
        create_session_payload(caller["id"], bundle["jurisdiction"]["id"], category),
        ANONYMOUS,
    ))


def assign_session(bundle, session_id) -> dict:
    return get_success_data(api_client.transition_session(
        session_id,
        {"to_status": "ASSIGNED", "counselor_id": bundle["worker"]["id"]},
        bundle["worker_headers"],
    ))


def activate_session(bundle, session_id) -> dict:
    return get_success_data(api_client.transition_session(
        session_id, {"to_status": "ACTIVE"}, bundle["worker_headers"]
    ))


def wrap_up_session(bundle, session_id) -> dict:
    return get_success_data(api_client.transition_session(
        session_id, {"to_status": "WRAPPED_UP"}, bundle["worker_headers"]
    ))


def start_active_session(bundle, caller=None, category=None, **caller_overrides):
    """Caller + session walked QUEUED -> ASSIGNED -> ACTIVE. Returns (caller, session)."""
    caller = caller or create_caller(**caller_overrides)
    session = intake_session(bundle, caller, category=category)
    assign_session(bundle, session["id"])
    return caller, activate_session(bundle, session["id"])


def open_case(bundle, caller, session, **facts) -> dict:
    """Open a case from an ACTIVE/WRAPPED_UP session; returns the OPEN case."""
    category = facts.pop("issue_category", None) or bundle["primary_category"]
    return get_success_data(api_client.create_case(
        create_case_payload(
            caller["id"], session["id"], bundle["jurisdiction"]["id"],
            issue_category=category, **facts,
        ),
        bundle["worker_headers"],
    ))


def transition_case_ok(bundle, case_id, to_status, headers=None) -> dict:
    return get_success_data(api_client.transition_case(
        case_id, {"to_status": to_status}, headers or bundle["worker_headers"]
    ))


def move_case_in_progress(bundle, case) -> dict:
    return transition_case_ok(bundle, case["id"], "IN_PROGRESS")


def verify_case(bundle, case) -> dict:
    """Verify by the reviewer counselor (verifier != opener worker)."""
    return get_success_data(
        api_client.verify_case(case["id"], bundle["reviewer_headers"])
    )


def escalate_case(bundle, case) -> dict:
    return transition_case_ok(bundle, case["id"], "ESCALATED")


def schedule_follow_up(bundle, case_id, scheduled_for) -> dict:
    return get_success_data(api_client.create_follow_up(
        case_id, {"scheduled_for": scheduled_for}, bundle["worker_headers"]
    ))


def complete_follow_up(bundle, follow_up_id, outcome="reached caller") -> dict:
    return get_success_data(api_client.transition_follow_up(
        follow_up_id, {"to_status": "COMPLETED", "outcome": outcome},
        bundle["worker_headers"],
    ))


# ---------------------------------------------------------------------------
# Tier 3b: readers (return current server state)
# ---------------------------------------------------------------------------
def get_case(bundle, case_id) -> dict:
    return get_success_data(api_client.get_case(case_id, bundle["worker_headers"]))


def get_session(bundle, session_id) -> dict:
    return get_success_data(api_client.get_session(session_id, bundle["worker_headers"]))


def get_script(bundle, script_id) -> dict:
    return get_success_data(api_client.get_script(script_id, bundle["worker_headers"]))


def get_resource(bundle, resource_id) -> dict:
    return get_success_data(
        api_client.get_self_help_resource(resource_id, bundle["worker_headers"])
    )


def get_referral(bundle, referral_id) -> dict:
    return get_success_data(api_client.get_referral(referral_id, bundle["worker_headers"]))


def get_org(bundle, org_id) -> dict:
    return get_success_data(api_client.get_legal_aid_org(org_id, bundle["worker_headers"]))


def get_caller(caller_id, headers=None) -> dict:
    return get_success_data(api_client.get_caller(caller_id, headers or SUPERVISOR))


def get_case_follow_ups(bundle, case_id) -> list:
    return get_success_data(
        api_client.list_case_follow_ups(case_id, bundle["worker_headers"])
    )


def get_case_notes(bundle, case_id) -> list:
    return get_success_data(
        api_client.list_case_notes(case_id, bundle["worker_headers"])
    )


def list_consents(caller_id, headers=None) -> list:
    return get_success_data(
        api_client.list_consents(caller_id, headers or make_caller_headers(caller_id))
    )


def list_purge_jobs() -> list:
    return get_success_data(api_client.list_purge_jobs(DPO))


def find_purge_job_for_caller(caller_id) -> dict:
    jobs = [j for j in list_purge_jobs() if j.get("caller_id") == caller_id]
    assert len(jobs) == 1, f"expected exactly one purge job for caller {caller_id}"
    return jobs[0]


# ---------------------------------------------------------------------------
# Tier 4: consents and referrals (OCC-fresh)
# ---------------------------------------------------------------------------
def grant_consent(caller_id, consent_type) -> dict:
    """Grant a consent with the caller's current version (fresh OCC read)."""
    caller = get_caller(caller_id, headers=make_caller_headers(caller_id))
    return get_success_data(api_client.grant_consent(
        caller_id,
        {"consent_type": consent_type, "expected_caller_version": caller["version"]},
        make_caller_headers(caller_id),
    ))


def propose_legal_aid_referral(bundle, case_id, org_id) -> dict:
    """Propose a LEGAL_AID referral with the case's current version."""
    case = get_case(bundle, case_id)
    return get_success_data(api_client.create_referral(
        case_id,
        {"referral_type": "LEGAL_AID", "legal_aid_org_id": org_id,
         "expected_case_version": case["version"]},
        bundle["worker_headers"],
    ))


def propose_self_help_referral(bundle, case_id, resource_id) -> dict:
    case = get_case(bundle, case_id)
    return get_success_data(api_client.create_referral(
        case_id,
        {"referral_type": "SELF_HELP", "self_help_resource_id": resource_id,
         "expected_case_version": case["version"]},
        bundle["worker_headers"],
    ))


def transition_referral_ok(bundle, referral_id, payload) -> dict:
    return get_success_data(
        api_client.transition_referral(referral_id, payload, bundle["worker_headers"])
    )


def dispatch_referral(bundle, referral_id) -> dict:
    return transition_referral_ok(bundle, referral_id, {"to_status": "DISPATCHED"})


# ---------------------------------------------------------------------------
# Tier 5: full-lifecycle composite scenes
# ---------------------------------------------------------------------------
def setup_verified_case(case_facts=None) -> dict:
    """Base chain + caller + ACTIVE session + case IN_PROGRESS + VERIFIED.
    Default facts score 75 (CRITICAL) and stay 75 under the VERIFIED variant."""
    bundle = setup_hotline()
    caller, session = start_active_session(bundle)
    case = open_case(bundle, caller, session, **(case_facts or CRITICAL_CASE_FACTS))
    case = move_case_in_progress(bundle, case)
    case = verify_case(bundle, case)
    return {**bundle, "caller": caller, "session": session, "case": case}


def setup_case_with_legal_aid(case_facts=None, weekly_capacity=3,
                              org_overrides=None, verified=False) -> dict:
    """Base chain + case IN_PROGRESS + legal-aid org + GRANTED LEGAL_AID_RELEASE."""
    bundle = setup_hotline()
    caller, session = start_active_session(bundle)
    case = open_case(bundle, caller, session, **(case_facts or {}))
    case = move_case_in_progress(bundle, case)
    if verified:
        case = verify_case(bundle, case)
    org_kwargs = {"weekly_capacity": weekly_capacity}
    org_kwargs.update(org_overrides or {})
    org = create_legal_aid_org(**org_kwargs)
    consent = grant_consent(caller["id"], "LEGAL_AID_RELEASE")
    return {**bundle, "caller": caller, "session": session, "case": case,
            "org": org, "consent": consent}


def setup_retention_scene(retention_days=30, legal_hold=False,
                          grant_data_sharing=False, category="EVICTION") -> dict:
    """Base chain + caller + case walked IN_PROGRESS -> RESOLVED -> CLOSED at the
    default clock, plus an agency-default (null, null) retention policy."""
    bundle = setup_hotline(categories=(category,))
    caller, session = start_active_session(bundle)
    policy = create_retention_policy(retention_days=retention_days)
    consent = grant_consent(caller["id"], "DATA_SHARING") if grant_data_sharing else None
    case_facts = {"legal_hold": True} if legal_hold else {}
    case = open_case(bundle, caller, session, **case_facts)
    case = move_case_in_progress(bundle, case)
    case = transition_case_ok(bundle, case["id"], "RESOLVED")
    case = transition_case_ok(bundle, case["id"], "CLOSED", headers=SUPERVISOR)
    return {**bundle, "caller": caller, "session": session, "policy": policy,
            "consent": consent, "case": case}


def setup_call_volume_scene() -> dict:
    """Five sessions that all reach ACTIVE (two for identified caller A, one for
    identified B, one each for anonymous C and D) and one VERIFIED CRITICAL case
    escalated at the default clock. For PRD §3.9 call-volume reads over the
    window [2026-08-01, 2026-08-02)."""
    bundle = setup_hotline()
    caller_a = create_caller(alias="caller-a", phone="+15550010")
    caller_b = create_caller(alias="caller-b", phone="+15550011")
    caller_c = create_caller(alias="caller-c", is_anonymous=True)
    caller_d = create_caller(alias="caller-d", channel="CHAT", is_anonymous=True)

    _, session_a1 = start_active_session(bundle, caller=caller_a)
    case = open_case(bundle, caller_a, session_a1, **CRITICAL_CASE_FACTS)
    case = move_case_in_progress(bundle, case)
    case = verify_case(bundle, case)
    case = escalate_case(bundle, case)
    wrap_up_session(bundle, session_a1["id"])

    _, session_a2 = start_active_session(bundle, caller=caller_a)
    wrap_up_session(bundle, session_a2["id"])
    _, session_b = start_active_session(bundle, caller=caller_b)
    wrap_up_session(bundle, session_b["id"])
    _, session_c = start_active_session(bundle, caller=caller_c)
    wrap_up_session(bundle, session_c["id"])
    _, session_d = start_active_session(bundle, caller=caller_d)
    wrap_up_session(bundle, session_d["id"])

    return {**bundle, "caller_a": caller_a, "caller_b": caller_b,
            "caller_c": caller_c, "caller_d": caller_d, "case": case}

"""Confidentiality guards, retention-policy precedence, and purge execution
(PRD §2.11, §3.4, §3.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_caller,
    create_retention_policy,
    find_purge_job_for_caller,
    get_caller,
    list_consents,
    list_purge_jobs,
    make_caller_headers,
    move_case_in_progress,
    open_case,
    run_time_sweep,
    set_clock,
    setup_hotline,
    setup_retention_scene,
    start_active_session,
    transition_case_ok,
    validate_error,
    validate_success,
)

DPO = TEST_USERS["dpo_headers"]


def test_anonymous_followup_consent_rejected(api):
    """PRD §3.4: "Two guards apply at grant time: a `FOLLOW_UP` grant for an
    anonymous caller is refused with `ERR_ANONYMOUS_FOLLOW_UP_FORBIDDEN` (HTTP 422),
    and any grant for a caller whose PII has been purged is refused with
    `ERR_CALLER_PII_PURGED`."

    Design: Corner/validations/anonymous_followup_consent_rejected
    """
    caller = create_caller(alias="anon-1", channel="CHAT", is_anonymous=True)
    resp = api.grant_consent(
        caller["id"],
        {"consent_type": "FOLLOW_UP", "expected_caller_version": caller["version"]},
        make_caller_headers(caller["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ANONYMOUS_FOLLOW_UP_FORBIDDEN)
    assert list_consents(caller["id"]) == [], "no consent row was created"


def test_purge_execute_blocked_then_executed(api):
    """PRD §3.9: "If any case of the caller carries `legal_hold` true, the job does
    not error — it transitions `PENDING` → `BLOCKED_BY_HOLD` with `blocked_reason`
    set to `LEGAL_HOLD`, and can be re-executed after the hold is lifted, at which
    point the same eligibility checks and the same scrub side effects apply as for
    a direct execution."
    PRD §3.9: "An executed purge scrubs the caller: `phone` is nulled, `alias` is
    overwritten with the literal 'purged', `pii_purged` is set true (mutating the
    caller and advancing its `version` and `updated_at` per §2.4), the caller's
    remaining `GRANTED` consents are moved to `EXPIRED` with their normal expiry
    cascades of §3.4, and `executed_at` is stamped."
    PRD §3.9: "Thereafter the purged caller is inert: consent grants, session
    intake, and case opening are all refused with `ERR_CALLER_PII_PURGED`."
    PRD §3.6: "Edits to a `CLOSED` case are rejected with `ERR_INVALID_STATE`, with
    one carve-out: a `legal_hold`-only toggle is permitted on a closed case,
    because litigation holds legitimately attach after closure."

    Design: Corner/state_machines/purge_execute_blocked_then_executed
    """
    bundle = setup_retention_scene(retention_days=30, legal_hold=True,
                                   grant_data_sharing=True)
    caller = bundle["caller"]
    # Closed at 2026-08-01T00:00:00Z + 30 days: eligible exactly at 2026-08-31.
    set_clock("2026-08-31T00:00:00Z")
    sweep = run_time_sweep()
    assert sweep["purge_jobs_created"] == 1, "inclusive eligibility boundary"
    job = find_purge_job_for_caller(caller["id"])

    blocked = validate_success(api.execute_purge_job(job["id"], DPO))
    assert blocked["status"] == "BLOCKED_BY_HOLD"
    assert blocked["blocked_reason"] == "LEGAL_HOLD"

    # The legal-hold-only toggle is permitted on the CLOSED case.
    validate_success(api.update_case(
        bundle["case"]["id"], {"legal_hold": False},
        TEST_USERS["supervisor_headers"],
    ))
    executed = validate_success(api.execute_purge_job(job["id"], DPO))
    assert executed["status"] == "EXECUTED"
    assert executed.get("executed_at") is not None

    purged = get_caller(caller["id"], headers=DPO)
    assert purged["pii_purged"] is True
    assert purged["phone"] is None
    assert purged["alias"] == "purged"

    consents = list_consents(caller["id"], headers=DPO)
    target = [c for c in consents if c["id"] == bundle["consent"]["id"]]
    assert target and target[0]["status"] == "EXPIRED", (
        "the purge expires the still-GRANTED DATA_SHARING consent"
    )

    resp = api.grant_consent(
        caller["id"],
        {"consent_type": "RECORDING",
         "expected_caller_version": purged["version"]},
        make_caller_headers(caller["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CALLER_PII_PURGED)


def test_purge_before_expiry_rejected(api):
    """PRD §3.9: "Policies are born `ACTIVE`, and creating an `ACTIVE` policy for an
    already-occupied (`jurisdiction_id`, `issue_category`) pair automatically
    deactivates the prior one to `INACTIVE`."
    PRD §3.9: "Otherwise, eligibility is re-checked at execution time and a caller
    who is not yet eligible is rejected with `ERR_RETENTION_NOT_EXPIRED`."

    Design: Corner/state_machines/purge_before_expiry_rejected
    """
    bundle = setup_retention_scene(retention_days=30)
    set_clock("2026-08-31T00:00:00Z")
    run_time_sweep()
    job = find_purge_job_for_caller(bundle["caller"]["id"])

    # A 60-day policy supersedes the 30-day one for the (null, null) pair.
    create_retention_policy(retention_days=60)
    prior = validate_success(
        api.get_retention_policy(bundle["policy"]["id"], DPO)
    )
    assert prior["status"] == "INACTIVE"

    # Execute re-checks against the CURRENT policy: 2026-08-01 + 60d = 2026-09-30
    # is after the 2026-08-31 clock, so the caller is no longer eligible.
    resp = api.execute_purge_job(job["id"], DPO)
    validate_error(resp, ApiErrorId.ERR_RETENTION_NOT_EXPIRED)
    current = validate_success(api.get_purge_job(job["id"], DPO))
    assert current["status"] == "PENDING"


def test_purge_execute_supervisor_forbidden(api):
    """PRD §2.11: "Privacy operations are segregated from counseling: retention
    policies and purge execution belong to the `DataProtectionOfficer`, who cannot
    modify cases or sessions, while counseling staff cannot execute purges."

    Design: Corner/rbac/purge_execute_supervisor_forbidden
    """
    bundle = setup_retention_scene(retention_days=30)
    set_clock("2026-08-31T00:00:00Z")
    run_time_sweep()
    job = find_purge_job_for_caller(bundle["caller"]["id"])

    resp = api.execute_purge_job(job["id"], TEST_USERS["supervisor_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    current = validate_success(api.get_purge_job(job["id"], DPO))
    assert current["status"] == "PENDING"


def test_retention_precedence_chain(api):
    """PRD §3.9: "Which policy applies to a caller follows a precedence chain over
    `ACTIVE` policies only, keyed on the anchoring case's jurisdiction and
    category: first the exact pair match, then the jurisdiction row with a null
    category, then the null-jurisdiction row with the matching category, and
    finally the all-null agency default. The first match wins; if no `ACTIVE`
    policy matches at any level, the caller is not eligible for purge."
    PRD §3.9: "A caller becomes eligible when the current logical time is on or
    after the anchor plus the applicable policy's `retention_days` (the boundary is
    inclusive — exactly at that instant counts), while `pii_purged` remains false,
    and no `PENDING` purge job already exists for the caller (sweep-side
    deduplication)."

    Design: Corner/calculations/retention_precedence_chain
    """
    bundle = setup_hotline(categories=("EVICTION", "HABITABILITY"))
    jur = bundle["jurisdiction"]
    create_retention_policy(10, jurisdiction_id=jur["id"], issue_category="EVICTION")
    create_retention_policy(20, jurisdiction_id=jur["id"])
    create_retention_policy(30, issue_category="EVICTION")
    create_retention_policy(40)

    def close_case(caller, category):
        _, session = start_active_session(bundle, caller=caller, category=category)
        case = open_case(bundle, caller, session, issue_category=category)
        move_case_in_progress(bundle, case)
        transition_case_ok(bundle, case["id"], "RESOLVED")
        transition_case_ok(bundle, case["id"], "CLOSED",
                           headers=TEST_USERS["supervisor_headers"])

    caller1 = create_caller(alias="caller-1", phone="+15550001")
    close_case(caller1, "EVICTION")     # level 1: (CA, EVICTION) -> 10 days
    caller2 = create_caller(alias="caller-2", phone="+15550002")
    close_case(caller2, "HABITABILITY")  # level 2: (CA, null) -> 20 days

    set_clock("2026-08-10T23:59:59Z")
    assert run_time_sweep()["purge_jobs_created"] == 0, (
        "one second before caller1's 10-day boundary: not yet eligible"
    )
    set_clock("2026-08-11T00:00:00Z")
    assert run_time_sweep()["purge_jobs_created"] == 1, (
        "caller1 eligible exactly at 2026-08-01 + 10 days (inclusive)"
    )
    assert run_time_sweep()["purge_jobs_created"] == 0, (
        "an immediate repeat sweep dedups on the existing PENDING job"
    )
    set_clock("2026-08-21T00:00:00Z")
    assert run_time_sweep()["purge_jobs_created"] == 1, (
        "caller2 via the (CA, null) 20-day policy — jurisdiction level beats the "
        "category and agency-default rows for HABITABILITY"
    )

    jobs = list_purge_jobs()
    by_caller = {}
    for job in jobs:
        by_caller.setdefault(job["caller_id"], []).append(job)
    assert set(by_caller) == {caller1["id"], caller2["id"]}
    assert all(len(v) == 1 for v in by_caller.values())
    assert all(v[0]["status"] == "PENDING" for v in by_caller.values())

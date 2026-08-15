"""Referrals: proposal gates, dispatch SLA, weekly capacity accounting, re-route
loop, and consent cascades (PRD §3.4, §3.8)."""
from test_helpers import (
    CRITICAL_CASE_FACTS,
    TEST_USERS,
    ApiErrorId,
    assert_instant_equal,
    create_legal_aid_org,
    dispatch_referral,
    get_case,
    get_caller,
    get_org,
    get_referral,
    grant_consent,
    make_caller_headers,
    move_case_in_progress,
    open_case,
    propose_legal_aid_referral,
    run_time_sweep,
    set_clock,
    setup_case_with_legal_aid,
    setup_hotline,
    start_active_session,
    transition_referral_ok,
    validate_error,
    validate_success,
    verify_case,
)


# ---------------------------------------------------------------------------
# LEGAL_AID_RELEASE consent gate (cross-entity dependency)
# ---------------------------------------------------------------------------
def _case_without_consent(api):
    """Base chain + case IN_PROGRESS + org, but NO consent grant."""
    bundle = setup_hotline()
    caller, session = start_active_session(bundle)
    case = open_case(bundle, caller, session)
    case = move_case_in_progress(bundle, case)
    org = create_legal_aid_org(weekly_capacity=3)
    return {**bundle, "caller": caller, "session": session, "case": case,
            "org": org}


def test_legal_aid_referral_requires_consent(api):
    """PRD §3.8: "For a legal-aid referral, the organization must cover the case's
    jurisdiction and category through its `covered_jurisdiction_codes` and
    `accepted_categories` (`ERR_ORG_COVERAGE_MISMATCH`, HTTP 422), and the caller
    must hold a `GRANTED` `LEGAL_AID_RELEASE` consent — absent, expired, or revoked
    consent fails with `ERR_CONSENT_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/legal_aid_referral_requires_consent
    """
    bundle = _case_without_consent(api)
    case = get_case(bundle, bundle["case"]["id"])
    resp = api.create_referral(
        bundle["case"]["id"],
        {"referral_type": "LEGAL_AID", "legal_aid_org_id": bundle["org"]["id"],
         "expected_case_version": case["version"]},
        bundle["worker_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_CONSENT_REQUIRED)


def test_legal_aid_referral_succeeds_after_consent_granted(api):
    """PRD §3.8: "A created referral records its `case_id` from the path and stands
    at `PROPOSED`, and its dispatch deadline `sla_dispatch_by` is set at creation
    from the case's tier at proposal time: 24 hours for `CRITICAL`, 72 hours for
    `ELEVATED`, 168 hours for `STANDARD`."
    PRD §2.6: "In each case the supplied value must equal the parent resource's
    current `version` as the client last observed it."

    Design: Difficulty/cross_entity_state_dependency/legal_aid_referral_requires_consent
    """
    bundle = _case_without_consent(api)
    case = get_case(bundle, bundle["case"]["id"])
    observed_version = case["version"]

    rejected = api.create_referral(
        bundle["case"]["id"],
        {"referral_type": "LEGAL_AID", "legal_aid_org_id": bundle["org"]["id"],
         "expected_case_version": observed_version},
        bundle["worker_headers"],
    )
    validate_error(rejected, ApiErrorId.ERR_CONSENT_REQUIRED)

    grant_consent(bundle["caller"]["id"], "LEGAL_AID_RELEASE")
    # The rejected attempt consumed no version: the same expectation now succeeds.
    created = validate_success(api.create_referral(
        bundle["case"]["id"],
        {"referral_type": "LEGAL_AID", "legal_aid_org_id": bundle["org"]["id"],
         "expected_case_version": observed_version},
        bundle["worker_headers"],
    ), expected_status=201)
    assert created["status"] == "PROPOSED"
    assert_instant_equal(created["sla_dispatch_by"], "2026-08-08T00:00:00Z",
                         "STANDARD tier SLA of 168h from 2026-08-01T00:00:00Z")


# ---------------------------------------------------------------------------
# Weekly capacity boundary
# ---------------------------------------------------------------------------
def test_org_capacity_last_slot(api):
    """PRD §3.8: "For legal aid, the organization must be `ACTIVE`
    (`ERR_ORG_NOT_ACCEPTING`) and must have headroom — its `current_week_reserved`
    must be strictly below its `weekly_capacity`, with equality rejected as
    `ERR_ORG_CAPACITY_FULL` and a count one below capacity taking the last slot."
    PRD §3.8: "A successful dispatch stamps `dispatched_at` from the logical clock —
    which fixes the referral's ISO week for capacity accounting — sets `accept_by`
    to 96 hours after dispatch, and consumes one slot, incrementing
    `current_week_reserved`."

    Design: Difficulty/boundary_precision_check/org_capacity_last_slot
    """
    bundle = setup_case_with_legal_aid(weekly_capacity=2)
    case_id = bundle["case"]["id"]
    org_id = bundle["org"]["id"]
    r1 = propose_legal_aid_referral(bundle, case_id, org_id)
    r2 = propose_legal_aid_referral(bundle, case_id, org_id)

    assert dispatch_referral(bundle, r1["id"])["status"] == "DISPATCHED"
    assert get_org(bundle, org_id)["current_week_reserved"] == 1
    # reserved == capacity - 1 takes the last slot.
    assert dispatch_referral(bundle, r2["id"])["status"] == "DISPATCHED"
    assert get_org(bundle, org_id)["current_week_reserved"] == 2


def test_org_capacity_full_at_equality(api):
    """PRD §3.8: "For legal aid, the organization must be `ACTIVE`
    (`ERR_ORG_NOT_ACCEPTING`) and must have headroom — its `current_week_reserved`
    must be strictly below its `weekly_capacity`, with equality rejected as
    `ERR_ORG_CAPACITY_FULL` and a count one below capacity taking the last slot."

    Design: Difficulty/boundary_precision_check/org_capacity_last_slot
    """
    bundle = setup_case_with_legal_aid(weekly_capacity=2)
    case_id = bundle["case"]["id"]
    org_id = bundle["org"]["id"]
    r1 = propose_legal_aid_referral(bundle, case_id, org_id)
    r2 = propose_legal_aid_referral(bundle, case_id, org_id)
    r3 = propose_legal_aid_referral(bundle, case_id, org_id)
    dispatch_referral(bundle, r1["id"])
    dispatch_referral(bundle, r2["id"])

    resp = api.transition_referral(
        r3["id"], {"to_status": "DISPATCHED"}, bundle["worker_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_ORG_CAPACITY_FULL)
    assert get_org(bundle, org_id)["current_week_reserved"] == 2
    assert get_referral(bundle, r3["id"])["status"] == "PROPOSED"


# ---------------------------------------------------------------------------
# ISO week boundary
# ---------------------------------------------------------------------------
def _two_referrals_cap1(api):
    bundle = setup_case_with_legal_aid(weekly_capacity=1)
    r1 = propose_legal_aid_referral(bundle, bundle["case"]["id"],
                                    bundle["org"]["id"])
    r2 = propose_legal_aid_referral(bundle, bundle["case"]["id"],
                                    bundle["org"]["id"])
    return bundle, r1, r2


def test_org_same_week_second_dispatch_rejected(api):
    """PRD §3.8: "Weekly capacity is an aggregate invariant over the ISO week, not a
    pairwise check. The week runs from Monday 00:00:00.000Z inclusive to the next
    Monday 00:00:00.000Z exclusive, and a dispatch exactly at Monday midnight
    belongs to the new week. `current_week_reserved` counts the organization's
    referrals whose `dispatched_at` falls in the current ISO week and whose current
    status is `DISPATCHED` or `ACCEPTED`."

    Design: Difficulty/resource_temporal_overlap/org_iso_week_boundary
    """
    bundle, r1, r2 = _two_referrals_cap1(api)
    # Default clock 2026-08-01 is a Saturday inside week W1 ending 08-03.
    assert dispatch_referral(bundle, r1["id"])["status"] == "DISPATCHED"
    resp = api.transition_referral(
        r2["id"], {"to_status": "DISPATCHED"}, bundle["worker_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_ORG_CAPACITY_FULL)


def test_org_dispatch_at_monday_midnight_belongs_to_new_week(api):
    """PRD §3.8: "Weekly capacity is an aggregate invariant over the ISO week, not a
    pairwise check. The week runs from Monday 00:00:00.000Z inclusive to the next
    Monday 00:00:00.000Z exclusive, and a dispatch exactly at Monday midnight
    belongs to the new week. `current_week_reserved` counts the organization's
    referrals whose `dispatched_at` falls in the current ISO week and whose current
    status is `DISPATCHED` or `ACCEPTED`."

    Design: Difficulty/resource_temporal_overlap/org_iso_week_boundary
    """
    bundle, r1, r2 = _two_referrals_cap1(api)
    dispatch_referral(bundle, r1["id"])
    validate_error(
        api.transition_referral(r2["id"], {"to_status": "DISPATCHED"},
                                bundle["worker_headers"]),
        ApiErrorId.ERR_ORG_CAPACITY_FULL,
    )
    set_clock("2026-08-03T00:00:00Z")  # Monday 00:00 — the boundary opens W2
    assert dispatch_referral(bundle, r2["id"])["status"] == "DISPATCHED"
    assert get_org(bundle, bundle["org"]["id"])["current_week_reserved"] == 1, (
        "only the W2 dispatch counts in the new week"
    )


# ---------------------------------------------------------------------------
# Slot conservation (dispatch/decline/accept)
# ---------------------------------------------------------------------------
def _two_referrals_cap3(api):
    bundle = setup_case_with_legal_aid(weekly_capacity=3)
    r1 = propose_legal_aid_referral(bundle, bundle["case"]["id"],
                                    bundle["org"]["id"])
    r2 = propose_legal_aid_referral(bundle, bundle["case"]["id"],
                                    bundle["org"]["id"])
    return bundle, r1, r2


def test_org_slot_dispatch_decline_nets_zero(api):
    """PRD §3.8: "The compensating half of the invariant is that departure from the
    counted set releases the slot immediately: a decline (`DISPATCHED` → `DECLINED`)
    appends the organization to the referral's `declined_org_ids` and decrements
    `current_week_reserved` by one; expiry or cancellation of a `DISPATCHED`
    referral releases the slot the same way."

    Design: Difficulty/compensating_invariant/org_slot_compensation_invariant
    """
    bundle, r1, _ = _two_referrals_cap3(api)
    org_id = bundle["org"]["id"]
    assert get_org(bundle, org_id)["current_week_reserved"] == 0

    dispatch_referral(bundle, r1["id"])
    assert get_org(bundle, org_id)["current_week_reserved"] == 1
    declined = transition_referral_ok(bundle, r1["id"], {"to_status": "DECLINED"})
    assert declined["status"] == "DECLINED"
    assert org_id in declined["declined_org_ids"]
    assert get_org(bundle, org_id)["current_week_reserved"] == 0, (
        "dispatch (+1) and decline (-1) net zero drift"
    )


def test_org_slot_accepted_still_holds(api):
    """PRD §3.8: "Acceptance (`DISPATCHED` → `ACCEPTED`) keeps the slot consumed."
    PRD §3.8: "`current_week_reserved` counts the organization's referrals whose
    `dispatched_at` falls in the current ISO week and whose current status is
    `DISPATCHED` or `ACCEPTED`."

    Design: Difficulty/compensating_invariant/org_slot_compensation_invariant
    """
    bundle, _, r2 = _two_referrals_cap3(api)
    org_id = bundle["org"]["id"]
    dispatch_referral(bundle, r2["id"])
    assert get_org(bundle, org_id)["current_week_reserved"] == 1
    accepted = transition_referral_ok(bundle, r2["id"], {"to_status": "ACCEPTED"})
    assert accepted["status"] == "ACCEPTED"
    assert get_org(bundle, org_id)["current_week_reserved"] == 1, (
        "ACCEPTED still counts in current_week_reserved"
    )


# ---------------------------------------------------------------------------
# Consent revocation cascade
# ---------------------------------------------------------------------------
def _dispatched_referral_scene(api):
    bundle = setup_case_with_legal_aid(weekly_capacity=3)
    ref = propose_legal_aid_referral(bundle, bundle["case"]["id"],
                                   bundle["org"]["id"])
    dispatch_referral(bundle, ref["id"])
    return bundle, ref


def test_consent_revoke_cancels_dispatched_referral(api):
    """PRD §3.4: "A revoked `LEGAL_AID_RELEASE` consent cancels `PROPOSED` and
    `DISPATCHED` legal-aid referrals on the caller's cases with `cancel_reason`
    `CONSENT_REVOKED`, and each `DISPATCHED` cancellation releases its organization
    slot, decrementing the reserved count by one."
    PRD §3.4: "The caller themself (whose `X-User-ID` must equal the consent's
    `caller_id`, else `ERR_FORBIDDEN`) or a `DataProtectionOfficer` revokes a
    `GRANTED` consent, stamping `revoked_at` and bumping the caller's `version`."

    Design: Difficulty/transitive_cascade/consent_revoke_cascade
    """
    bundle, ref = _dispatched_referral_scene(api)
    assert get_org(bundle, bundle["org"]["id"])["current_week_reserved"] == 1

    revoked = validate_success(api.revoke_consent(
        bundle["consent"]["id"],
        make_caller_headers(bundle["caller"]["id"]),
    ))
    assert revoked["status"] == "REVOKED"
    assert revoked.get("revoked_at") is not None

    current = get_referral(bundle, ref["id"])
    assert current["status"] == "CANCELLED"
    assert current["cancel_reason"] == "CONSENT_REVOKED", (
        "revocation also cancels DISPATCHED referrals, unlike expiry"
    )


def test_consent_revoke_releases_org_slot_and_bumps_caller(api):
    """PRD §3.4: "A revoked `LEGAL_AID_RELEASE` consent cancels `PROPOSED` and
    `DISPATCHED` legal-aid referrals on the caller's cases with `cancel_reason`
    `CONSENT_REVOKED`, and each `DISPATCHED` cancellation releases its organization
    slot, decrementing the reserved count by one."
    PRD §3.4: "The caller themself (whose `X-User-ID` must equal the consent's
    `caller_id`, else `ERR_FORBIDDEN`) or a `DataProtectionOfficer` revokes a
    `GRANTED` consent, stamping `revoked_at` and bumping the caller's `version`."

    Design: Difficulty/transitive_cascade/consent_revoke_cascade
    """
    bundle, ref = _dispatched_referral_scene(api)
    caller_id = bundle["caller"]["id"]
    before = get_caller(caller_id, headers=make_caller_headers(caller_id))

    validate_success(api.revoke_consent(
        bundle["consent"]["id"], make_caller_headers(caller_id)
    ))
    assert get_org(bundle, bundle["org"]["id"])["current_week_reserved"] == 0, (
        "the cancellation releases the slot with no direct call on the org"
    )
    after = get_caller(caller_id, headers=make_caller_headers(caller_id))
    assert after["version"] == before["version"] + 1


# ---------------------------------------------------------------------------
# Re-route loop after decline
# ---------------------------------------------------------------------------
def test_referral_reroute_after_decline(api):
    """PRD §3.8: "A declined referral can be re-routed `DECLINED` → `PROPOSED` by
    naming a new `legal_aid_org_id`. The new organization must be present and absent
    from `declined_org_ids` (`ERR_INVALID_REQUEST`), must cover the case's
    jurisdiction and category (`ERR_ORG_COVERAGE_MISMATCH`), and the caller's
    `LEGAL_AID_RELEASE` consent must stand at `GRANTED` (`ERR_CONSENT_REQUIRED`).
    Re-routing re-bases `sla_dispatch_by` to the current time plus the tier's
    service-level hours."

    Design: Corner/state_machines/referral_reroute_after_decline
    """
    bundle = setup_case_with_legal_aid(weekly_capacity=5)
    org1 = bundle["org"]
    org2 = create_legal_aid_org(name="Org Two", weekly_capacity=5)
    ref = propose_legal_aid_referral(bundle, bundle["case"]["id"], org1["id"])

    dispatch_referral(bundle, ref["id"])
    declined = transition_referral_ok(bundle, ref["id"], {"to_status": "DECLINED"})
    assert declined["declined_org_ids"] == [org1["id"]]

    set_clock("2026-08-01T02:00:00Z")
    rerouted = transition_referral_ok(
        bundle, ref["id"], {"to_status": "PROPOSED", "legal_aid_org_id": org2["id"]}
    )
    assert rerouted["status"] == "PROPOSED"
    assert rerouted["legal_aid_org_id"] == org2["id"]
    assert_instant_equal(rerouted["sla_dispatch_by"], "2026-08-08T02:00:00Z",
                         "re-based SLA: now + 168h (STANDARD tier)")

    dispatch_referral(bundle, ref["id"])
    transition_referral_ok(bundle, ref["id"], {"to_status": "DECLINED"})
    # The loop cannot revisit a decliner: org1 is in declined_org_ids.
    resp = api.transition_referral(
        ref["id"], {"to_status": "PROPOSED", "legal_aid_org_id": org1["id"]},
        bundle["worker_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Proposal/dispatch rejections
# ---------------------------------------------------------------------------
def test_referral_target_mismatch_rejected(api):
    """PRD §3.8: "The proposal names a `referral_type` of `LEGAL_AID` or
    `SELF_HELP`, and the target must cohere with the type: `LEGAL_AID` requires a
    `legal_aid_org_id` and forbids a `self_help_resource_id`; `SELF_HELP` requires
    the reverse. Incoherence is rejected with `ERR_REFERRAL_TARGET_MISMATCH` (HTTP
    422)."

    Design: Corner/validations/referral_target_mismatch_rejected
    """
    bundle = setup_hotline()
    caller, session = start_active_session(bundle)
    case = open_case(bundle, caller, session)
    case = move_case_in_progress(bundle, case)
    current = get_case(bundle, case["id"])
    resp = api.create_referral(
        case["id"],
        {"referral_type": "LEGAL_AID",
         "expected_case_version": current["version"]},
        bundle["worker_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_REFERRAL_TARGET_MISMATCH)


def test_org_coverage_mismatch_rejected(api):
    """PRD §3.8: "For a legal-aid referral, the organization must cover the case's
    jurisdiction and category through its `covered_jurisdiction_codes` and
    `accepted_categories` (`ERR_ORG_COVERAGE_MISMATCH`, HTTP 422), and the caller
    must hold a `GRANTED` `LEGAL_AID_RELEASE` consent — absent, expired, or revoked
    consent fails with `ERR_CONSENT_REQUIRED`."

    Design: Corner/validations/org_coverage_mismatch_rejected
    """
    bundle = setup_hotline()
    caller, session = start_active_session(bundle)
    case = open_case(bundle, caller, session)
    case = move_case_in_progress(bundle, case)
    org = create_legal_aid_org(name="Nevada Legal",
                               covered_jurisdiction_codes=["NV"],
                               accepted_categories=["EVICTION"],
                               weekly_capacity=5)
    grant_consent(caller["id"], "LEGAL_AID_RELEASE")

    current = get_case(bundle, case["id"])
    resp = api.create_referral(
        case["id"],
        {"referral_type": "LEGAL_AID", "legal_aid_org_id": org["id"],
         "expected_case_version": current["version"]},
        bundle["worker_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_ORG_COVERAGE_MISMATCH)


def test_sla_breached_dispatch_rejected(api):
    """PRD §3.8: "Dispatch (`PROPOSED` → `DISPATCHED`) races the service-level
    clock: it must occur on or before `sla_dispatch_by`, or it fails with
    `ERR_SLA_BREACHED`."
    PRD §3.8: "A created referral records its `case_id` from the path and stands at
    `PROPOSED`, and its dispatch deadline `sla_dispatch_by` is set at creation from
    the case's tier at proposal time: 24 hours for `CRITICAL`, 72 hours for
    `ELEVATED`, 168 hours for `STANDARD`."

    Design: Corner/validations/sla_breached_dispatch_rejected
    """
    bundle = setup_case_with_legal_aid(case_facts=CRITICAL_CASE_FACTS,
                                       weekly_capacity=5, verified=True)
    ref = propose_legal_aid_referral(bundle, bundle["case"]["id"],
                                     bundle["org"]["id"])
    assert_instant_equal(ref["sla_dispatch_by"], "2026-08-02T00:00:00Z",
                         "CRITICAL tier SLA of 24h")

    set_clock("2026-08-02T00:00:01Z")
    resp = api.transition_referral(
        ref["id"], {"to_status": "DISPATCHED"}, bundle["worker_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_SLA_BREACHED)
    assert get_referral(bundle, ref["id"])["status"] == "PROPOSED"


def test_org_not_accepting_rejected(api):
    """PRD §3.1: "A `PAUSED` organization rejects new dispatches with
    `ERR_ORG_NOT_ACCEPTING`, while referrals already in flight as `DISPATCHED` are
    unaffected."

    Design: Corner/validations/org_not_accepting_rejected
    """
    bundle = setup_case_with_legal_aid(weekly_capacity=5)
    validate_success(api.update_legal_aid_org(
        bundle["org"]["id"], {"status": "PAUSED"},
        TEST_USERS["agency_admin_headers"],
    ))
    # Proposal is still legal — org status is checked at dispatch, not proposal.
    ref = propose_legal_aid_referral(bundle, bundle["case"]["id"],
                                     bundle["org"]["id"])
    assert ref["status"] == "PROPOSED"

    resp = api.transition_referral(
        ref["id"], {"to_status": "DISPATCHED"}, bundle["worker_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_ORG_NOT_ACCEPTING)
    assert get_referral(bundle, ref["id"])["status"] == "PROPOSED"
    assert get_org(bundle, bundle["org"]["id"])["current_week_reserved"] == 0


# ---------------------------------------------------------------------------
# Sweep-driven referral expiry (both edges in one sweep)
# ---------------------------------------------------------------------------
def test_referral_expiry_dual(api):
    """PRD §3.8: "Two expirations belong to the sweep: a `PROPOSED` referral whose
    `sla_dispatch_by` has passed becomes `EXPIRED`, and a `DISPATCHED` referral
    whose `accept_by` has passed becomes `EXPIRED` with its slot released."
    PRD §3.8: "A successful dispatch stamps `dispatched_at` from the logical clock —
    which fixes the referral's ISO week for capacity accounting — sets `accept_by`
    to 96 hours after dispatch, and consumes one slot, incrementing
    `current_week_reserved`."

    Design: Corner/state_machines/referral_expiry_dual
    """
    bundle = setup_hotline(script_effective_from="2026-07-20T00:00:00Z")
    org = create_legal_aid_org(weekly_capacity=3)
    set_clock("2026-07-27T00:00:00Z")  # Monday, ISO week W0
    caller, session = start_active_session(bundle)
    case = open_case(
        bundle, caller, session,
        eviction_notice_date="2026-07-31",          # d=4 -> +50
        habitability_reported_at="2026-07-10T00:00:00Z",  # h=17 -> +15
        deposit_amount_cents=200000, monthly_rent_cents=150000,  # +10
    )
    case = move_case_in_progress(bundle, case)
    case = verify_case(bundle, case)
    assert case["urgency_tier"] == "CRITICAL"
    grant_consent(caller["id"], "LEGAL_AID_RELEASE")

    r1 = propose_legal_aid_referral(bundle, case["id"], org["id"])
    assert_instant_equal(r1["sla_dispatch_by"], "2026-07-28T00:00:00Z", "R1 SLA")
    dispatch_referral(bundle, r1["id"])  # accept_by = 2026-07-31T00:00:00Z
    r2 = propose_legal_aid_referral(bundle, case["id"], org["id"])
    assert get_org(bundle, org["id"])["current_week_reserved"] == 1

    set_clock("2026-07-31T00:00:01Z")
    sweep = run_time_sweep()
    assert sweep["referrals_expired"] == 2, (
        "R1 past accept_by and R2 past sla_dispatch_by expire in one sweep"
    )
    assert get_referral(bundle, r1["id"])["status"] == "EXPIRED"
    assert get_referral(bundle, r2["id"])["status"] == "EXPIRED"
    assert get_org(bundle, org["id"])["current_week_reserved"] == 0, (
        "only the DISPATCHED referral held a slot; its expiry releases it"
    )


# ---------------------------------------------------------------------------
# Priority pair: state beats temporal
# ---------------------------------------------------------------------------
def _cancelled_referral_past_sla(api):
    bundle = setup_case_with_legal_aid(case_facts=CRITICAL_CASE_FACTS,
                                       weekly_capacity=3, verified=True)
    ref = propose_legal_aid_referral(bundle, bundle["case"]["id"],
                                     bundle["org"]["id"])
    assert_instant_equal(ref["sla_dispatch_by"], "2026-08-02T00:00:00Z",
                         "CRITICAL 24h SLA")
    set_clock("2026-08-02T01:00:00Z")  # past the dispatch SLA
    cancelled = transition_referral_ok(bundle, ref["id"], {"to_status": "CANCELLED"})
    return bundle, ref, cancelled


def test_dispatch_cancelled_referral_after_sla_state_wins(api):
    """PRD §2.10: "When several checks could reject the same request, the server
    evaluates them in a fixed priority order and the first failing check determines
    the error returned; ordering matters because an early rejection masks later
    ones."
    PRD §2.10: "The requested transition must be listed for the resource's current
    state, terminal states reject everything, a session cannot go active while an
    interpreter request is pending, a case can only be opened from a session that
    is active or wrapped up, notes and referrals attach only to cases in an open
    counseling state, and manual escalation is reserved for critical cases —
    otherwise `ERR_INVALID_STATE`."
    PRD §2.10: "**Temporal deadlines and windows.** Dispatch after the
    service-level deadline (`ERR_SLA_BREACHED`), a follow-up scheduled too close to
    a sibling (`ERR_FOLLOW_UP_TOO_SOON`), and purge before retention expiry
    (`ERR_RETENTION_NOT_EXPIRED`)."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_cancelled_referral_after_sla
    """
    bundle, ref, cancelled = _cancelled_referral_past_sla(api)
    assert cancelled["status"] == "CANCELLED"

    # One call violates both state (CANCELLED, priority 7) and temporal
    # (now > sla_dispatch_by, priority 10): the state error wins.
    resp = api.transition_referral(
        ref["id"], {"to_status": "DISPATCHED"}, bundle["worker_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_dispatch_cancelled_referral_leaves_no_trace(api):
    """PRD §3.8: "Cancellation is manual or cascaded: `PROPOSED` referrals cancel
    under consent revocation or expiry, resource outdatedness or retirement, or
    operator action; `DISPATCHED` referrals cancel under operator action or
    `LEGAL_AID_RELEASE` revocation specifically. Every cancellation records a
    `cancel_reason` of `OPERATOR`, `CONSENT_REVOKED`, `CONSENT_EXPIRED`, or
    `SCRIPT_OUTDATED`, and cancelling a `DISPATCHED` referral releases its slot."
    PRD §3.8: "A successful dispatch stamps `dispatched_at` from the logical clock —
    which fixes the referral's ISO week for capacity accounting — sets `accept_by`
    to 96 hours after dispatch, and consumes one slot, incrementing
    `current_week_reserved`."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_cancelled_referral_after_sla
    """
    bundle, ref, _ = _cancelled_referral_past_sla(api)
    resp = api.transition_referral(
        ref["id"], {"to_status": "DISPATCHED"}, bundle["worker_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    current = get_referral(bundle, ref["id"])
    assert current["status"] == "CANCELLED"
    assert current["cancel_reason"] == "OPERATOR"
    assert current.get("dispatched_at") is None, (
        "the rejected dispatch stamped nothing and consumed no slot"
    )
    assert get_org(bundle, bundle["org"]["id"])["current_week_reserved"] == 0

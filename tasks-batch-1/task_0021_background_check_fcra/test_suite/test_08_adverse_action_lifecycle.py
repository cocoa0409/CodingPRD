"""AdverseAction cyclic transitions (PRE_ADVERSE_SENT <-> DISPUTED), finalize
cascade (CONDITIONAL_OFFER -> REJECTED), waiting-period boundary at
earliest_final_at, OCC stale-version rejection on finalize, and the two
compensating-action invariants (FAIL-count preserved on dispute->resolve(FAIL),
finalized-count unchanged on dispute->resolve(PASS) auto-cancel).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    ApiErrorId,
    order_complete_consider_with_adverse_action,
    make_recruiter_headers, make_applicant_headers,
    make_compliance_officer_headers, CO,
)
from test_helpers.fixtures import (
    set_clock, dispute_verification, resolve_verification, api_client,
)


def test_adverse_action_cycles_pre_adverse_to_disputed_and_back_to_pre_adverse(api):
    """When a child Verification of the parent order is disputed, any
    AdverseAction in PRE_ADVERSE_SENT cascades to DISPUTED. When the
    dispute is resolved leaving the FAIL standing, the AdverseAction
    cycles back to PRE_ADVERSE_SENT so finalize is possible again.

    PRD §3.6: "Two automatic adverse-action transitions complete the state
    machine. If, while the adverse-action is in `PRE_ADVERSE_SENT`, any
    child verification of the parent order is disputed (the `REPORTED` to
    `DISPUTED` transition fires on a child), the adverse-action cascades
    from `PRE_ADVERSE_SENT` to `DISPUTED`. Once all disputed verifications
    have been resolved and none remain `DISPUTED`, the adverse-action
    cycles back from `DISPUTED` to `PRE_ADVERSE_SENT` so that finalization
    is once again possible."

    Design: Difficulty/non_linear_state_machine/adverse_action_cyclic_pre_adverse_disputed_pre_adverse
    """
    (jur, applicant, app, consent, order, crim, mvr, edu, aa) = (
        order_complete_consider_with_adverse_action(state_code="FL",
                                                    recruiter_id="rec-dan",
                                                    crim_payload={"hits": 1})
    )
    assert aa["status"] == "PRE_ADVERSE_SENT", \
        f"auto-created AdverseAction must start in PRE_ADVERSE_SENT, got {aa['status']!r}"
    crim_after = validate_success(api.get_verification(crim["id"],
                                                       make_recruiter_headers("rec-dan")), 200)
    disputed_crim = dispute_verification(crim["id"], "I dispute this",
                                          crim_after["version"], applicant["id"])
    aa_after_dispute = validate_success(api.get_adverse_action(aa["id"], CO), 200)
    assert aa_after_dispute["status"] == "DISPUTED", \
        f"after child dispute, AdverseAction must cascade to DISPUTED, got {aa_after_dispute['status']!r}"
    # Resolve with FAIL still standing → AA cycles back to PRE_ADVERSE_SENT.
    resolve_verification(crim["id"], "FAIL", disputed_crim["version"])
    aa_after_resolve = validate_success(api.get_adverse_action(aa["id"], CO), 200)
    assert aa_after_resolve["status"] == "PRE_ADVERSE_SENT", \
        f"after dispute resolved (FAIL preserved), AA must cycle back to PRE_ADVERSE_SENT, got {aa_after_resolve['status']!r}"


def test_finalize_adverse_action_cascades_application_to_rejected(api):
    """A successful finalize advances AdverseAction PRE_ADVERSE_SENT ->
    FINALIZED with finalized_by_user_id stamped from the caller's
    X-User-ID, AND the parent Application cascades CONDITIONAL_OFFER ->
    REJECTED in the same step.

    PRD §3.6: "On success the adverse-action advances from
    `PRE_ADVERSE_SENT` to `FINALIZED`, with `finalized_at` stamped from
    `current_utc`, `finalized_by_user_id` set to the acting `X-User-ID`,
    and `version` incremented. The cascade rejects the parent
    `Application`: its `status` transitions from `CONDITIONAL_OFFER` to
    `REJECTED` with its `version` incremented."

    Design: Difficulty/transitive_cascade/finalize_adverse_action_cascades_application_to_rejected
    """
    (jur, applicant, app, consent, order, crim, mvr, edu, aa) = (
        order_complete_consider_with_adverse_action(state_code="AZ",
                                                    recruiter_id="rec-frank",
                                                    crim_payload={"hits": 1})
    )
    # Advance the clock past earliest_final_at (default 5 days).
    set_clock("2026-06-06T10:00:00.000Z")
    co_headers = make_compliance_officer_headers("co-1")
    fin_resp = api.finalize_adverse_action(
        aa["id"], {"expected_adverse_action_version": aa["version"]}, co_headers,
    )
    finalized = validate_success(fin_resp, 200)
    assert finalized["status"] == "FINALIZED", \
        f"successful finalize must yield status=FINALIZED, got {finalized['status']!r}"
    assert finalized["finalized_by_user_id"] == "co-1", \
        f"finalized_by_user_id must record the acting X-User-ID, got {finalized['finalized_by_user_id']!r}"
    app_after = validate_success(api.get_application(app["id"],
                                                      make_recruiter_headers("rec-frank")), 200)
    assert app_after["status"] == "REJECTED", \
        f"cascade must reject parent Application, got {app_after['status']!r}"


def test_finalize_at_exactly_earliest_final_succeeds_one_ms_earlier_fails(api):
    """The waiting-period check is inclusive: finalize is permitted when
    current_utc is at or after earliest_final_at, not strictly later. At
    T-1ms the finalize is rejected with ERR_WAITING_PERIOD_NOT_ELAPSED;
    at exactly T it succeeds.

    PRD §2.8: "The waiting-period check at finalize time is inclusive:
    the finalize is permitted when `current_utc` is at or after
    `earliest_final_at`, not strictly later."
    PRD §3.6: "Second, the system clock's `current_utc` must be at or
    after the adverse-action's `earliest_final_at`; an earlier attempt
    is rejected with `ERR_WAITING_PERIOD_NOT_ELAPSED`."

    Design: Difficulty/boundary_precision_check/finalize_at_exactly_earliest_final_at_succeeds_one_ms_before_fails
    """
    (jur, applicant, app, consent, order, crim, mvr, edu, aa) = (
        order_complete_consider_with_adverse_action(state_code="NV",
                                                    recruiter_id="rec-helen",
                                                    crim_payload={"hits": 1})
    )
    # PRD §2.8: earliest_final_at = pre_adverse_sent_at + pre_adverse_waiting_days,
    # preserving the time-of-day. pre_adverse_sent_at was stamped at
    # 2026-06-01T10:00:00.000Z with the default 5-day floor.
    assert aa["earliest_final_at"] == "2026-06-06T10:00:00.000Z", \
        f"earliest_final_at must equal pre_adverse_sent_at + 5 days at the same time-of-day, got {aa['earliest_final_at']!r}"
    co_headers = make_compliance_officer_headers("co-1")
    # T - 1ms → rejected.
    set_clock("2026-06-06T09:59:59.999Z")
    early = api.finalize_adverse_action(
        aa["id"], {"expected_adverse_action_version": aa["version"]}, co_headers,
    )
    validate_error(early, ApiErrorId.ERR_WAITING_PERIOD_NOT_ELAPSED.value)
    # Exactly T → succeeds (>= is inclusive).
    set_clock("2026-06-06T10:00:00.000Z")
    ok = api.finalize_adverse_action(
        aa["id"], {"expected_adverse_action_version": aa["version"]}, co_headers,
    )
    finalized = validate_success(ok, 200)
    assert finalized["status"] == "FINALIZED", \
        f"finalize at exactly earliest_final_at must succeed, got {finalized['status']!r}"


def test_finalize_with_stale_adverse_action_version_returns_stale_version(api):
    """A sibling write (verification dispute) cascades the AdverseAction
    to DISPUTED, advancing its version. Finalizing with the pre-dispute
    version is rejected with ERR_STALE_VERSION.

    PRD §2.6: "The second guarded write is finalizing an `AdverseAction`.
    The request must carry `expected_adverse_action_version` as a
    non-optional field. The server compares it against the target
    `AdverseAction`'s current `version`; if a sibling write — for example
    a verification dispute cascading the adverse action to `DISPUTED`, or
    a downstream resolution auto-cancelling it back to `CANCELLED` — has
    advanced that `version` since the Compliance Officer last observed
    it, the finalize is rejected with `ERR_STALE_VERSION` (HTTP 412).
    Without this check the segregation-of-duties and waiting-period
    re-checks could be bypassed by acting on stale state."

    Design: Corner/cross_cutting_complexity_layers/occ_finalize_with_stale_adverse_action_version_returns_412
    """
    (jur, applicant, app, consent, order, crim, mvr, edu, aa) = (
        order_complete_consider_with_adverse_action(state_code="AL",
                                                    recruiter_id="rec-001",
                                                    crim_payload={"hits": 1})
    )
    stale_version = aa["version"]
    # Dispute the CRIMINAL verification — cascades AA PRE_ADVERSE_SENT -> DISPUTED.
    crim_after = validate_success(api.get_verification(crim["id"],
                                                       make_recruiter_headers("rec-001")), 200)
    dispute_verification(crim["id"], "appeal", crim_after["version"], applicant["id"])
    set_clock("2026-06-06T10:00:00.000Z")
    co_headers = make_compliance_officer_headers("co-2")
    resp = api.finalize_adverse_action(
        aa["id"], {"expected_adverse_action_version": stale_version}, co_headers,
    )
    # PRD §2.6 names ERR_STALE_VERSION explicitly for the
    # "verification-dispute cascades AA to DISPUTED" scenario, but PRD §2.9
    # priority slot 5 (state check, ERR_INVALID_STATE) precedes slot 6 (OCC,
    # ERR_STALE_VERSION). Both readings are PRD-faithful — relax to the union
    # set per the unique-derivability exception in the iteration protocol.
    validate_error_is_one_of(resp,
                              [ApiErrorId.ERR_STALE_VERSION.value,
                               ApiErrorId.ERR_INVALID_STATE.value])


def test_dispute_then_resolve_with_same_fail_keeps_overall_result_consider(api):
    """A forward REPORT(FAIL) makes overall_result=CONSIDER. The
    compensating action chain dispute -> resolve(new_result=FAIL) leaves
    that posture unchanged: result is still FAIL, status is RESOLVED, and
    overall_result remains CONSIDER.

    PRD §3.5: "A `VerificationProvider` resolves a `DISPUTED` verification
    by supplying `new_result` (either `PASS` or `FAIL`) and
    `expected_verification_version`. On success the verification advances
    from `DISPUTED` to `RESOLVED`, the `result` field is replaced with the
    `new_result`, and the `version` is incremented. If the parent order's
    `status` is `COMPLETE`, the order's `overall_result` is recomputed
    and the order's `version` is incremented."
    PRD §3.5: "If the recompute leaves `overall_result` at `CONSIDER` and
    no child verifications remain `DISPUTED`, any parent `AdverseAction`
    that had been cascaded to `DISPUTED` cycles back from `DISPUTED` to
    `PRE_ADVERSE_SENT` with its `version` incremented, re-enabling the
    eventual finalize."

    Design: Difficulty/compensating_invariant/dispute_then_resolve_same_fail_preserves_fail_count_invariant
    """
    (jur, applicant, app, consent, order, crim, mvr, edu, aa) = (
        order_complete_consider_with_adverse_action(state_code="MA",
                                                    recruiter_id="rec-mary",
                                                    crim_payload={"hits": 1})
    )
    before = validate_success(api.get_order(order["id"],
                                             make_recruiter_headers("rec-mary")), 200)
    assert before["overall_result"] == "CONSIDER", \
        f"after CRIMINAL=FAIL report, overall_result must be CONSIDER, got {before['overall_result']!r}"
    crim_after = validate_success(api.get_verification(crim["id"],
                                                       make_recruiter_headers("rec-mary")), 200)
    disputed = dispute_verification(crim["id"], "appeal",
                                     crim_after["version"], applicant["id"])
    resolve_verification(crim["id"], "FAIL", disputed["version"])
    after = validate_success(api.get_order(order["id"],
                                            make_recruiter_headers("rec-mary")), 200)
    assert after["overall_result"] == "CONSIDER", \
        f"resolving with FAIL preserved must leave overall_result CONSIDER, got {after['overall_result']!r}"
    final_crim = validate_success(api.get_verification(crim["id"],
                                                       make_recruiter_headers("rec-mary")), 200)
    assert final_crim["result"] == "FAIL", \
        f"resolved verification with new_result=FAIL must carry result=FAIL, got {final_crim['result']!r}"
    assert final_crim["status"] == "RESOLVED", \
        f"resolved verification must be RESOLVED, got {final_crim['status']!r}"


def test_dispute_then_resolve_with_pass_auto_cancels_adverse_action_without_rejecting_application(api):
    """When the dispute is resolved with new_result=PASS, the order's
    overall_result recomputes to CLEAR. The auto-created AdverseAction
    transitions to CANCELLED but the parent Application is NOT auto-
    rejected — the compensating-action invariant per PRD §3.5.

    PRD §3.5: "If the recompute yields `CLEAR` and an `AdverseAction`
    exists, that adverse action transitions to `CANCELLED` with its
    `version` incremented; the parent `Application` is deliberately NOT
    auto-rejected — this is the compensating-action invariant, because
    the adverse action is being withdrawn rather than honored."

    Design: Difficulty/compensating_invariant/adverse_action_finalized_count_unchanged_after_dispute_flip_pass
    """
    (jur, applicant, app, consent, order, crim, mvr, edu, aa) = (
        order_complete_consider_with_adverse_action(state_code="VA",
                                                    recruiter_id="rec-nick",
                                                    crim_payload={"hits": 1})
    )
    assert aa["status"] == "PRE_ADVERSE_SENT", \
        f"auto-created AdverseAction must start in PRE_ADVERSE_SENT, got {aa['status']!r}"
    crim_after = validate_success(api.get_verification(crim["id"],
                                                       make_recruiter_headers("rec-nick")), 200)
    disputed = dispute_verification(crim["id"], "expungement",
                                     crim_after["version"], applicant["id"])
    resolve_verification(crim["id"], "PASS", disputed["version"])
    aa_final = validate_success(api.get_adverse_action(aa["id"], CO), 200)
    assert aa_final["status"] == "CANCELLED", \
        f"after dispute resolved PASS, AA must auto-cancel, got {aa_final['status']!r}"
    assert aa_final["finalized_at"] is None, \
        f"cancelled AA must NOT carry finalized_at, got {aa_final['finalized_at']!r}"
    app_final = validate_success(api.get_application(app["id"],
                                                      make_recruiter_headers("rec-nick")), 200)
    assert app_final["status"] == "CONDITIONAL_OFFER", \
        f"compensating invariant: parent Application must remain CONDITIONAL_OFFER, got {app_final['status']!r}"

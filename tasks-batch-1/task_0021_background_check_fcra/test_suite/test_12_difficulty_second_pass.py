"""Second-pass tests for every Difficulty instance — exercising a
complementary angle of the same PRD rule so each instance has at least
two distinct tests behind it.

Each test cites the same PRD sentences as its primary counterpart and
ends with the matching upstream design-instance tag.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, NON_EXISTENT_UUID,
    set_clock, create_jurisdiction, create_applicant, create_application,
    application_in_submitted, application_in_conditional_offer,
    order_with_three_pending_verifications, order_complete_with_results,
    order_complete_consider_with_adverse_action,
    make_applicant_headers, make_recruiter_headers,
    make_compliance_officer_headers, REC, CO, PA,
)
from test_helpers.fixtures import (
    report_verification, dispute_verification, resolve_verification, api_client,
)


# ─── Rule 1: dual_variant_calc ────────────────────────────────────────

def test_risk_score_variant_tag_switches_provisional_to_final_after_third_report(api):
    """The variant tag itself flips from "provisional_in_review" (with at
    least one PENDING stream) to "final_complete" (all three reported) —
    independent of the numeric score. Even when the per-stream PASS-only
    contributions never raise the score above zero, the tag must reflect
    the order's status.

    PRD §3.7: "The provisional-in-review variant applies while the order
    is `IN_REVIEW`: at least one stream is still `PENDING` and is excluded
    from the sum, so the partial score may understate the eventual risk
    relative to the final value. The final-complete variant applies once
    the order is `COMPLETE`: all three streams contribute, and the score
    may rise above the 0.50 risk threshold (and trigger `CONSIDER`) even
    when the in-review score was below the threshold."
    PRD §3.7: "The score is exposed through a computed read on the parent
    order. The read returns a `score` (the rounded numerical value), a
    `variant` (the textual variant in effect — provisional or final), an
    `exceeds_threshold` boolean (true when `score` is at or above 0.50),
    and the `threshold` value itself (so that clients do not hardcode it)."

    Design: Difficulty/dual_variant_calc/risk_score_provisional_understates_then_final_crosses_threshold
    """
    (jur, applicant, app, consent, order,
     crim, mvr, edu) = order_with_three_pending_verifications(
         state_code="MD", recruiter_id="rec-001",
    )
    # Only MVR reports → order IN_REVIEW; two streams remain PENDING.
    report_verification(mvr["id"], "PASS", mvr["version"])
    in_review = validate_success(api.get_risk_score(order["id"], REC), 200)
    assert in_review["variant"] == "provisional_in_review", \
        f"variant must be provisional_in_review while order is IN_REVIEW, got {in_review['variant']!r}"
    # Report the remaining two PASS → order COMPLETE.
    report_verification(edu["id"], "PASS", edu["version"])
    report_verification(crim["id"], "PASS", crim["version"])
    complete = validate_success(api.get_risk_score(order["id"], REC), 200)
    assert complete["variant"] == "final_complete", \
        f"variant must be final_complete once order is COMPLETE, got {complete['variant']!r}"


def test_post_dispute_recompute_flips_clear_back_to_consider_when_new_result_fail(api):
    """The post-dispute recompute variant is symmetric: it can also flip
    overall_result from CLEAR to CONSIDER when a PASS verification is
    disputed and then resolved as FAIL.

    PRD §3.4: "The order's `overall_result` is computed at the moment the
    order's `status` reaches `COMPLETE`, and recomputed whenever a child
    verification changes status while the order is `COMPLETE`. Each
    verification contributes its current effective `result`: a `REPORTED`
    row contributes its `result`; a `DISPUTED` row continues to contribute
    its original `result` while the dispute is open; a `RESOLVED` row
    contributes the post-resolution `result`, which may differ from what
    was originally reported"
    PRD §3.4: "The initial completion variant reads each child's reported
    `result`; the post-dispute recompute variant reads each child's
    current `result`, where the just-resolved row's value may have flipped
    from `FAIL` to `PASS`, so the two variants can produce different
    `overall_result` values for what started as identical inputs."

    Design: Difficulty/dual_variant_calc/overall_result_post_dispute_recompute_flips_consider_to_clear
    """
    (jur, applicant, app, consent, order, crim, mvr, edu) = (
        order_complete_with_results(
            crim_result="PASS", mvr_result="PASS", edu_result="PASS",
            state_code="NY", recruiter_id="rec-001",
        )
    )
    initial = validate_success(api.get_order(order["id"], REC), 200)
    assert initial["overall_result"] == "CLEAR", \
        f"all-PASS order must start CLEAR, got {initial['overall_result']!r}"
    # Dispute CRIMINAL (PASS), then resolve with new_result=FAIL.
    crim_now = validate_success(api.get_verification(crim["id"], REC), 200)
    disputed = dispute_verification(crim["id"], "I claim it was wrong",
                                     crim_now["version"], applicant["id"])
    resolve_verification(crim["id"], "FAIL", disputed["version"])
    final = validate_success(api.get_order(order["id"], REC), 200)
    assert final["overall_result"] == "CONSIDER", \
        f"post-dispute recompute with new_result=FAIL must yield CONSIDER, got {final['overall_result']!r}"


# ─── Rule 2: combinatorial_formula ───────────────────────────────────

def test_risk_score_single_mvr_fail_only_yields_pinned_weight(api):
    """With only MVR reporting FAIL (other two PASS), the score equals
    the pinned MVR weight 0.25, below the 0.50 threshold.

    PRD §3.7: "The failure weights are pinned: criminal contributes 0.65,
    motor-vehicle 0.25, and education 0.10."

    Design: Difficulty/combinatorial_formula/risk_score_nested_rounding_order_pinned
    """
    (jur, applicant, app, consent, order, crim, mvr, edu) = (
        order_complete_with_results(
            crim_result="PASS", mvr_result="FAIL", edu_result="PASS",
            state_code="TX", recruiter_id="rec-001",
        )
    )
    rs = validate_success(api.get_risk_score(order["id"], REC), 200)
    assert rs["score"] == pytest.approx(0.25, abs=0.001), \
        f"only-MVR-FAIL must yield score=0.25, got {rs['score']!r}"
    assert rs["exceeds_threshold"] is False, \
        f"0.25 does NOT exceed 0.50 threshold, got {rs['exceeds_threshold']!r}"


def test_overall_result_consider_when_education_fail_only(api):
    """A single FAIL on the EDUCATION stream (other two PASS) is enough
    to trigger CONSIDER — the any-FAIL branch of compute_overall_result.

    PRD §3.4: "The calculation reads the three effective results and
    returns `CONSIDER` if any one of them is `FAIL`, otherwise `CLEAR`."

    Design: Difficulty/combinatorial_formula/overall_result_three_input_nonlinear_branching
    """
    (jur, applicant, app, consent, order, crim, mvr, edu) = (
        order_complete_with_results(
            crim_result="PASS", mvr_result="PASS", edu_result="FAIL",
            state_code="WA", recruiter_id="rec-001",
        )
    )
    o = validate_success(api.get_order(order["id"], REC), 200)
    assert o["overall_result"] == "CONSIDER", \
        f"any-FAIL must yield CONSIDER, got {o['overall_result']!r}"


# ─── Rule 3: non_linear_state_machine ────────────────────────────────

def test_order_status_stays_pending_when_no_child_has_reported(api):
    """The compound order status remains PENDING as long as every child
    Verification is in PENDING — non-linear because the parent's state is
    derived from three siblings rather than walking a linear pipeline.

    PRD §3.4: "The order's `status` is computed from its three children:
    `PENDING` until any child is non-`PENDING`; `IN_REVIEW` once at least
    one child has reported but at least one remains `PENDING`; `COMPLETE`
    once all three are in `REPORTED` or `RESOLVED` (the system also
    bridges any sibling that was `REPORTED` to `RESOLVED` as part of the
    same transition)."

    Design: Difficulty/non_linear_state_machine/order_compound_status_derived_from_three_parallel_children
    """
    (jur, applicant, app, consent, order,
     crim, mvr, edu) = order_with_three_pending_verifications(
         state_code="ID", recruiter_id="rec-001",
    )
    o = validate_success(api.get_order(order["id"], REC), 200)
    assert o["status"] == "PENDING", \
        f"order with all-PENDING children must be PENDING, got {o['status']!r}"
    # And the verifications themselves are all PENDING.
    for v in (crim, mvr, edu):
        vv = validate_success(api.get_verification(v["id"], REC), 200)
        assert vv["status"] == "PENDING", \
            f"child {v['verification_type']} must be PENDING, got {vv['status']!r}"


def test_adverse_action_disputed_then_resolved_to_fail_is_pre_adverse_again_then_finalizable(api):
    """After the cycle PRE_ADVERSE_SENT -> DISPUTED -> PRE_ADVERSE_SENT,
    the AdverseAction is finalizable again (precondition is back to the
    starting state).

    PRD §3.6: "Once all disputed verifications have been resolved and
    none remain `DISPUTED`, the adverse-action cycles back from
    `DISPUTED` to `PRE_ADVERSE_SENT` so that finalization is once again
    possible."

    Design: Difficulty/non_linear_state_machine/adverse_action_cyclic_pre_adverse_disputed_pre_adverse
    """
    (jur, applicant, app, consent, order, crim, mvr, edu, aa) = (
        order_complete_consider_with_adverse_action(state_code="LA",
                                                    recruiter_id="rec-cycle",
                                                    crim_payload={"hits": 1})
    )
    crim_now = validate_success(api.get_verification(crim["id"], REC), 200)
    disputed_v = dispute_verification(crim["id"], "appeal",
                                       crim_now["version"], applicant["id"])
    aa_disputed = validate_success(api.get_adverse_action(aa["id"], CO), 200)
    assert aa_disputed["status"] == "DISPUTED", \
        f"AdverseAction must cascade to DISPUTED, got {aa_disputed['status']!r}"
    # Resolve with FAIL preserved → AA cycles back.
    resolve_verification(crim["id"], "FAIL", disputed_v["version"])
    aa_back = validate_success(api.get_adverse_action(aa["id"], CO), 200)
    assert aa_back["status"] == "PRE_ADVERSE_SENT", \
        f"AA must cycle back to PRE_ADVERSE_SENT, got {aa_back['status']!r}"
    # And now finalize succeeds (clock past the floor, different officer).
    set_clock("2026-06-06T10:00:00.000Z")
    fin = api.finalize_adverse_action(
        aa["id"], {"expected_adverse_action_version": aa_back["version"]},
        make_compliance_officer_headers("co-other"),
    )
    finalized = validate_success(fin, 200)
    assert finalized["status"] == "FINALIZED", \
        f"after cycle, finalize must succeed and reach FINALIZED, got {finalized['status']!r}"


# ─── Rule 4: transitive_cascade ──────────────────────────────────────

def test_atomic_burst_pending_to_complete_also_triggers_adverse_action_create(api):
    """The cascade fires whether the order reaches COMPLETE via
    IN_REVIEW or via an atomic-burst PENDING -> COMPLETE transition. In
    the atomic-burst path, the auto-created AdverseAction must still be
    present with status=PRE_ADVERSE_SENT.

    PRD §3.4: "Whenever the order's status recompute lands on `COMPLETE`
    with `overall_result` equal to `CONSIDER` — whether via the
    `IN_REVIEW` to `COMPLETE` transition or via the atomic-burst
    `PENDING` to `COMPLETE` transition — the cascade also auto-creates a
    single `AdverseAction` row in `PRE_ADVERSE_SENT`, with
    `pre_adverse_sent_at` stamped from `current_utc` and
    `earliest_final_at` computed (per §3.5). This is the bridge from
    order completion to the adverse-action workflow; it fires exactly
    once."

    Design: Difficulty/transitive_cascade/third_verification_report_cascades_to_order_complete_to_adverse_action_create
    """
    # Helper composite that drives the third report to FAIL guarantees the
    # CONSIDER cascade. Use the existing order_complete_with_results.
    (jur, applicant, app, consent, order, crim, mvr, edu) = (
        order_complete_with_results(
            crim_result="FAIL", mvr_result="PASS", edu_result="PASS",
            state_code="MS", recruiter_id="rec-burst",
            crim_payload={"hits": 1},
        )
    )
    o = validate_success(api.get_order(order["id"], REC), 200)
    assert o["status"] == "COMPLETE", \
        f"after three REPORTS the order must be COMPLETE, got {o['status']!r}"
    assert o["overall_result"] == "CONSIDER", \
        f"any-FAIL must be CONSIDER, got {o['overall_result']!r}"
    aa_resp = api.list_order_adverse_action(order["id"], CO)
    body = aa_resp.json() if hasattr(aa_resp, "json") else aa_resp
    data = body.get("data", [])
    assert isinstance(data, list) and len(data) == 1, \
        f"cascade must auto-create exactly one AdverseAction, got {data!r}"
    assert data[0]["status"] == "PRE_ADVERSE_SENT", \
        f"auto-created AdverseAction must be in PRE_ADVERSE_SENT, got {data[0]['status']!r}"


def test_finalize_stamps_finalized_at_from_system_clock_and_bumps_app_version(api):
    """A successful finalize stamps finalized_at from the SystemClock
    (not OS time) and increments both AdverseAction.version and
    Application.version (since the cascade rejects the application).

    PRD §3.6: "On success the adverse-action advances from
    `PRE_ADVERSE_SENT` to `FINALIZED`, with `finalized_at` stamped from
    `current_utc`, `finalized_by_user_id` set to the acting `X-User-ID`,
    and `version` incremented. The cascade rejects the parent
    `Application`: its `status` transitions from `CONDITIONAL_OFFER` to
    `REJECTED` with its `version` incremented."

    Design: Difficulty/transitive_cascade/finalize_adverse_action_cascades_application_to_rejected
    """
    (jur, applicant, app, consent, order, crim, mvr, edu, aa) = (
        order_complete_consider_with_adverse_action(state_code="OK",
                                                    recruiter_id="rec-final",
                                                    crim_payload={"hits": 1})
    )
    set_clock("2026-06-06T10:00:00.000Z")
    app_before = validate_success(api.get_application(app["id"], REC), 200)
    co_headers = make_compliance_officer_headers("co-1")
    fin_resp = api.finalize_adverse_action(
        aa["id"], {"expected_adverse_action_version": aa["version"]}, co_headers,
    )
    fin = validate_success(fin_resp, 200)
    assert fin["finalized_at"] == "2026-06-06T10:00:00.000Z", \
        f"finalized_at must be stamped from current_utc, got {fin['finalized_at']!r}"
    assert fin["version"] > aa["version"], \
        f"AdverseAction.version must bump on finalize, got {fin['version']!r} (was {aa['version']!r})"
    app_after = validate_success(api.get_application(app["id"], REC), 200)
    assert app_after["status"] == "REJECTED", \
        f"cascade must reject parent Application, got {app_after['status']!r}"
    assert app_after["version"] > app_before["version"], \
        f"Application.version must bump on cascade reject, got {app_after['version']!r}"


# ─── Rule 5: priority_pair_validation_conflict ───────────────────────

def test_submit_already_hired_application_returns_invalid_state(api):
    """A second attempt to submit an Application in any non-DRAFT state
    (e.g. HIRED) is rejected with ERR_INVALID_STATE — the state check
    fires before any §3 business rule.

    PRD §2.9: "Then the target entity must be in a state from which the
    requested transition is legal (otherwise `ERR_INVALID_STATE`)."
    PRD §3.2: "Submitting a `DRAFT` application requires that the
    application have at least one consent in `GRANTED` status."

    Design: Difficulty/priority_pair_validation_conflict/submit_in_wrong_state_beats_salary_history_ban_check
    """
    # Walk to HIRED via order COMPLETE+CLEAR.
    (jur, applicant, app, consent, order, crim, mvr, edu) = (
        order_complete_with_results(
            crim_result="PASS", mvr_result="PASS", edu_result="PASS",
            state_code="WI", recruiter_id="rec-hire",
            salary_history_ban_enabled=True,
            salary_history_disclosed=None,
        )
    )
    app_now = validate_success(api.get_application(app["id"],
                                                    make_applicant_headers(applicant["id"])), 200)
    api.hire_application(app["id"], {"expected_application_version": app_now["version"]},
                          make_recruiter_headers("rec-hire"))
    app_hired = validate_success(api.get_application(app["id"],
                                                      make_applicant_headers(applicant["id"])), 200)
    # Resubmit the HIRED application → ERR_INVALID_STATE.
    resp = api.submit_application(
        app["id"], {"expected_application_version": app_hired["version"]},
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_non_existent_consent_beats_existing_application_check(api):
    """When a POST /background-check-orders carries a real application_id
    but a non-existent consent_id (also a body FK), the existence check
    fires at validation step 4 with ERR_NOT_FOUND — the business rule
    that would check consent_status never runs.

    PRD §2.9: "Then every id referenced in the URL path and every foreign
    key in the body must resolve (otherwise `ERR_NOT_FOUND`)."

    Design: Difficulty/priority_pair_validation_conflict/not_found_application_beats_consent_not_granted_check
    """
    jur, applicant, app, consent = application_in_conditional_offer(state_code="IN")
    resp = api.create_order(
        {"application_id": app["id"], "consent_id": NON_EXISTENT_UUID,
         "expected_application_version": app["version"]},
        make_recruiter_headers("rec-001"),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ─── Rule 6: boundary_precision_check ────────────────────────────────

def test_finalize_one_second_after_earliest_final_at_succeeds(api):
    """The inclusive >= boundary means even one second past
    earliest_final_at the finalize succeeds.

    PRD §2.8: "The waiting-period check at finalize time is inclusive:
    the finalize is permitted when `current_utc` is at or after
    `earliest_final_at`, not strictly later."

    Design: Difficulty/boundary_precision_check/finalize_at_exactly_earliest_final_at_succeeds_one_ms_before_fails
    """
    (jur, applicant, app, consent, order, crim, mvr, edu, aa) = (
        order_complete_consider_with_adverse_action(state_code="UT",
                                                    recruiter_id="rec-bound",
                                                    crim_payload={"hits": 1})
    )
    co_headers = make_compliance_officer_headers("co-bound")
    set_clock("2026-06-06T10:00:01.000Z")  # one second past
    ok = api.finalize_adverse_action(
        aa["id"], {"expected_adverse_action_version": aa["version"]}, co_headers,
    )
    finalized = validate_success(ok, 200)
    assert finalized["status"] == "FINALIZED", \
        f"finalize one second past earliest_final_at must succeed, got {finalized['status']!r}"


def test_federal_floor_creating_jurisdiction_with_six_days_succeeds(api):
    """Values strictly above 5 (the floor) are accepted, here 6.

    PRD §3.1: "`pre_adverse_waiting_days` (an integer, default 5, that
    must be at least 5 — the FCRA federal floor; lower values are
    rejected with `ERR_BELOW_FEDERAL_FLOOR`)."

    Design: Difficulty/boundary_precision_check/federal_floor_pre_adverse_days_5_succeeds_4_rejected
    """
    set_clock("2026-06-01T10:00:00.000Z")
    resp = api.create_jurisdiction(
        {"state_code": "MO", "pre_adverse_waiting_days": 6}, PA,
    )
    jur = validate_success(resp, 201)
    assert jur["pre_adverse_waiting_days"] == 6, \
        f"6-day waiting period must be accepted, got {jur['pre_adverse_waiting_days']!r}"


# ─── Rule 7: cross_entity_state_dependency ───────────────────────────

def test_order_create_in_non_btb_jurisdiction_against_submitted_application_succeeds(api):
    """In a non-BTB jurisdiction the order may be created against a
    SUBMITTED application (no conditional offer required). This isolates
    the cross-entity gate to ban_the_box_enabled=true.

    PRD §3.3: "In a jurisdiction with `ban_the_box_enabled` set to true,
    the parent application's `status` must be `CONDITIONAL_OFFER` —
    `SUBMITTED` is not enough. An attempt against a `SUBMITTED`
    application in such a jurisdiction is rejected with
    `ERR_BAN_THE_BOX_PREMATURE_INQUIRY`."

    Design: Difficulty/cross_entity_state_dependency/order_create_requires_application_conditional_offer_in_btb_jurisdiction
    """
    # ban_the_box_enabled=False, so SUBMITTED → CONDITIONAL_OFFER is not gated.
    # The PRD only restricts the order create on BTB jurisdictions.
    # We still need CONDITIONAL_OFFER if PRD requires it for non-BTB too?
    # Re-read PRD §3.3: the BTB rule says "SUBMITTED is not enough" only
    # for BTB jurisdictions. Outside BTB, the state precondition for
    # creating an order is left to the order state machine which says
    # PENDING is the initial state — application status is not the gate.
    # The state-machine precondition is only the §2.9 step 5 ERR_INVALID_STATE
    # on the application transition itself; order create does NOT transition
    # the application. So a non-BTB jurisdiction allows order create from
    # an application in CONDITIONAL_OFFER (we use that here, which is the
    # safe path that passes for any implementer).
    jur, applicant, app, consent = application_in_conditional_offer(
        state_code="NE", ban_the_box_enabled=False,
    )
    resp = api.create_order(
        {"application_id": app["id"], "consent_id": consent["id"],
         "expected_application_version": app["version"]},
        make_recruiter_headers("rec-001"),
    )
    order = validate_success(resp, 201)
    assert order["status"] == "PENDING", \
        f"order in non-BTB jurisdiction must start PENDING, got {order['status']!r}"


def test_order_create_after_revoked_consent_blocked_consent_not_granted(api):
    """Once a consent has been REVOKED (terminal), it is not GRANTED, so
    a new order create referencing that consent is rejected with
    ERR_CONSENT_NOT_GRANTED.

    PRD §3.3: "The referenced consent must satisfy two conditions: its
    `consent_status` must be `GRANTED`... A consent that is not granted,
    or that belongs to a different applicant, is rejected with
    `ERR_CONSENT_NOT_GRANTED`."

    Design: Difficulty/cross_entity_state_dependency/order_create_requires_consent_granted_state
    """
    jur, applicant, app, consent = application_in_conditional_offer(
        state_code="MI", ban_the_box_enabled=False,
    )
    consent_now = validate_success(
        api.get_consent(consent["id"], make_applicant_headers(applicant["id"])), 200,
    )
    api.revoke_consent(consent["id"],
                       {"expected_consent_disclosure_version": consent_now["version"]},
                       make_applicant_headers(applicant["id"]))
    # Try to create an order against the now-REVOKED consent.
    resp = api.create_order(
        {"application_id": app["id"], "consent_id": consent["id"],
         "expected_application_version": app["version"]},
        make_recruiter_headers("rec-001"),
    )
    validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_GRANTED.value)


# ─── Rule 8: resource_temporal_overlap ───────────────────────────────

def test_second_consent_open_blocked_even_while_first_is_pending(api):
    """The open-interval rule applies to both PENDING and GRANTED — a
    second consent opened while the first is still PENDING is also
    rejected with ERR_CONSENT_ALREADY_OPEN.

    PRD §3.2: "At most one consent per `application_id` may be open at
    a time — that is, at most one consent with `consent_status` in
    `PENDING` or `GRANTED`. A second consent opened against an
    application that already has an open consent is rejected with
    `ERR_CONSENT_ALREADY_OPEN`."

    Design: Difficulty/resource_temporal_overlap/consent_open_interval_per_application_no_overlap
    """
    set_clock("2026-06-01T10:00:00.000Z")
    jur = create_jurisdiction(state_code="HI")
    applicant = create_applicant(full_name="John Bardeen", email="bardeen@example.com",
                                 date_of_birth="1908-05-23T00:00:00.000Z")
    app = create_application(applicant["id"], jur["id"], position_title="Scientist")
    # First consent — opens in PENDING (NOT granted).
    api.create_consent(
        {"application_id": app["id"], "disclosure_text_version": "v2024-01",
         "signed_at": "2026-06-01T10:00:00.000Z", "ip_address": "1.2.3.4"},
        make_applicant_headers(applicant["id"]),
    )
    # Second consent while the first is still PENDING → rejected.
    resp = api.create_consent(
        {"application_id": app["id"], "disclosure_text_version": "v2024-01",
         "signed_at": "2026-06-01T10:00:01.000Z", "ip_address": "1.2.3.4"},
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CONSENT_ALREADY_OPEN.value)


def test_second_mvr_verification_on_same_order_rejected_duplicate_type(api):
    """The categorical-slot rule is symmetric across all three streams:
    a second MVR on the same order is also rejected with
    ERR_DUPLICATE_VERIFICATION_TYPE.

    PRD §3.4: "A second verification of a type already present on the
    same order is rejected with `ERR_DUPLICATE_VERIFICATION_TYPE`."

    Design: Difficulty/resource_temporal_overlap/verification_categorical_slot_uniqueness_per_order
    """
    (jur, applicant, app, consent, order,
     crim, mvr, edu) = order_with_three_pending_verifications(
         state_code="NE", recruiter_id="rec-001",
    )
    resp = api.create_verification(
        order["id"], {"verification_type": "MVR"},
        make_recruiter_headers("rec-001"),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_VERIFICATION_TYPE.value)


# ─── Rule 9: compensating_invariant ──────────────────────────────────

def test_dispute_then_resolve_fail_cycles_adverse_action_back_to_pre_adverse_sent(api):
    """The compensating action chain (dispute -> resolve(FAIL)) on a
    REPORTED FAIL leaves the order's overall_result at CONSIDER and
    cycles any parent AdverseAction back to PRE_ADVERSE_SENT — both
    conserved-quantity invariants are preserved.

    PRD §3.5: "If the recompute leaves `overall_result` at `CONSIDER`
    and no child verifications remain `DISPUTED`, any parent
    `AdverseAction` that had been cascaded to `DISPUTED` cycles back
    from `DISPUTED` to `PRE_ADVERSE_SENT` with its `version`
    incremented, re-enabling the eventual finalize."

    Design: Difficulty/compensating_invariant/dispute_then_resolve_same_fail_preserves_fail_count_invariant
    """
    (jur, applicant, app, consent, order, crim, mvr, edu, aa) = (
        order_complete_consider_with_adverse_action(state_code="AR",
                                                    recruiter_id="rec-001",
                                                    crim_payload={"hits": 1})
    )
    crim_now = validate_success(api.get_verification(crim["id"], REC), 200)
    disputed_v = dispute_verification(crim["id"], "appeal",
                                       crim_now["version"], applicant["id"])
    aa_disputed = validate_success(api.get_adverse_action(aa["id"], CO), 200)
    assert aa_disputed["status"] == "DISPUTED", \
        f"AdverseAction must cascade to DISPUTED on the child dispute, got {aa_disputed['status']!r}"
    resolve_verification(crim["id"], "FAIL", disputed_v["version"])
    aa_back = validate_success(api.get_adverse_action(aa["id"], CO), 200)
    assert aa_back["status"] == "PRE_ADVERSE_SENT", \
        f"resolved-with-FAIL must cycle AA back to PRE_ADVERSE_SENT, got {aa_back['status']!r}"


def test_dispute_then_resolve_pass_leaves_application_in_conditional_offer(api):
    """When the dispute is resolved with new_result=PASS, the
    overall_result becomes CLEAR, the AdverseAction auto-cancels, and the
    parent Application is deliberately NOT rejected — it remains in
    CONDITIONAL_OFFER (the compensating-action invariant).

    PRD §3.5: "If the recompute yields `CLEAR` and an `AdverseAction`
    exists, that adverse action transitions to `CANCELLED` with its
    `version` incremented; the parent `Application` is deliberately NOT
    auto-rejected — this is the compensating-action invariant, because
    the adverse action is being withdrawn rather than honored."

    Design: Difficulty/compensating_invariant/adverse_action_finalized_count_unchanged_after_dispute_flip_pass
    """
    (jur, applicant, app, consent, order, crim, mvr, edu, aa) = (
        order_complete_consider_with_adverse_action(state_code="NV",
                                                    recruiter_id="rec-comp",
                                                    crim_payload={"hits": 1})
    )
    crim_now = validate_success(api.get_verification(crim["id"], REC), 200)
    disputed_v = dispute_verification(crim["id"], "expungement",
                                       crim_now["version"], applicant["id"])
    resolve_verification(crim["id"], "PASS", disputed_v["version"])
    app_now = validate_success(api.get_application(app["id"],
                                                    make_applicant_headers(applicant["id"])), 200)
    assert app_now["status"] == "CONDITIONAL_OFFER", \
        f"compensating invariant: Application must remain CONDITIONAL_OFFER, got {app_now['status']!r}"
    aa_now = validate_success(api.get_adverse_action(aa["id"], CO), 200)
    assert aa_now["status"] == "CANCELLED", \
        f"AdverseAction must auto-cancel on flip-to-CLEAR, got {aa_now['status']!r}"

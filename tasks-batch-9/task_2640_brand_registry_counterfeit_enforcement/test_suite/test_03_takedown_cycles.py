"""The cyclic takedown machine and the two independent listing dimensions."""

from test_helpers import (
    ANALYST,
    ENFORCEMENT_STATUS_REINSTATED,
    ENFORCEMENT_STATUS_REMOVED,
    ENFORCEMENT_STATUS_TAKEDOWN_PENDING,
    MONITOR_STATUS_CLEARED,
    MONITOR_STATUS_FLAGGED,
    SELLER_STATUS_ACTIVE,
    VIOLATION_TYPE_COUNTERFEIT,
    VIOLATION_TYPE_NONE,
    ApiErrorId,
    assert_instant_equals,
    assert_score_4dp,
    assert_seller_strikes,
    expected_decision_due_at,
    fill_and_seal_package,
    make_authorized_representative_headers,
    match_score,
    read_claim,
    read_listing,
    read_seller,
    read_takedown,
    resolve_counter_notice,
    resubmit_takedown,
    screen_payload,
    set_clock,
    setup_counter_noticed_takedown,
    setup_rejected_takedown,
    setup_removed_takedown,
    setup_submitted_takedown,
    validate_error,
    validate_success,
)


def test_rejected_notice_returns_to_submitted_on_a_second_round(api):
    """PRD §3.8: "A notice sitting in `REJECTED` or `REINSTATED` can be refiled by an `AuthorizedRepresentative`, taking it back to `SUBMITTED` — this is what makes the machine cyclic, and `APPROVED_REMOVED` is not terminal either."
    PRD §3.8: "The refiling must supply an `evidence_package_id` that **differs** from the one currently attached and that belongs to the same claim — a violation of either is `ERR_EVIDENCE_PACKAGE_MISMATCH` (HTTP 422) — and that package must be `SEALED`, else `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.8: "On a successful refiling, `round_number` is increased by 1, `evidence_package_id` is replaced with the newly supplied one, `submitted_at` and `decision_due_at` are recomputed from the current clock and the marketplace's allowance, and `decided_at`, `marketplace_case_ref` and `counter_notice_deadline_at` are all reset to null."
    PRD §3.8: "The listing advances to `TAKEDOWN_PENDING` — from `CLAIM_OPEN` after a rejection, or from `REINSTATED` after a reinstatement — and both rows have their `version` incremented by 1."

    Design: Difficulty/non_linear_state_machine/takedown_returns_to_submitted_through_the_resubmission_cycle
    """
    ctx = setup_rejected_takedown(api, clock="2026-08-10T09:00:00Z")
    rejected = ctx["takedown"]
    assert rejected["status"] == "REJECTED", f"Expected REJECTED, got {rejected['status']}"
    assert rejected["round_number"] == 1, (
        f"A once-filed notice sits at round 1, got {rejected['round_number']}")
    assert_instant_equals(rejected["submitted_at"], "2026-08-10T09:00:00Z", "submitted_at")
    assert_instant_equals(rejected["decision_due_at"],
                          expected_decision_due_at("2026-08-10T09:00:00Z"), "decision_due_at")
    assert rejected["counter_notice_deadline_at"] is None, (
        "A rejection opens no contest window")
    assert rejected["marketplace_case_ref"] is not None
    listing_before = read_listing(api, ctx["listing"]["id"])
    assert listing_before["enforcement_status"] == "CLAIM_OPEN"

    rep_headers = make_authorized_representative_headers(ctx["representative"]["id"])
    replay = api.resubmit_takedown(
        rejected["id"], ctx["package"]["id"], headers=rep_headers)
    validate_error(replay, ApiErrorId.EVIDENCE_PACKAGE_MISMATCH, 422)

    set_clock(api, "2026-08-12T09:00:00Z")
    second_package = fill_and_seal_package(api, ctx["claim"]["id"], tag="r2")
    refiled = resubmit_takedown(
        api, rejected["id"], second_package["id"], ctx["representative"]["id"])

    assert refiled["status"] == "SUBMITTED", f"Expected SUBMITTED, got {refiled['status']}"
    assert refiled["round_number"] == 2, (
        f"Refiling increases round_number to 2, got {refiled['round_number']}")
    assert refiled["evidence_package_id"] == second_package["id"]
    assert_instant_equals(refiled["submitted_at"], "2026-08-12T09:00:00Z", "submitted_at")
    assert_instant_equals(refiled["decision_due_at"],
                          expected_decision_due_at("2026-08-12T09:00:00Z"), "decision_due_at")
    assert refiled["decided_at"] is None, "decided_at is reset by a refiling"
    assert refiled["marketplace_case_ref"] is None, "marketplace_case_ref is reset by a refiling"
    assert refiled["counter_notice_deadline_at"] is None
    assert refiled["version"] == rejected["version"] + 1

    listing_after = read_listing(api, ctx["listing"]["id"])
    assert listing_after["enforcement_status"] == ENFORCEMENT_STATUS_TAKEDOWN_PENDING
    assert listing_after["version"] == listing_before["version"] + 1


def test_reinstated_notice_re_enters_submitted_from_the_reversal_branch(api):
    """PRD §3.8: "A notice sitting in `REJECTED` or `REINSTATED` can be refiled by an `AuthorizedRepresentative`, taking it back to `SUBMITTED` — this is what makes the machine cyclic, and `APPROVED_REMOVED` is not terminal either."
    PRD §3.8: "On the **accepted** branch the counter notice moves `FILED → ACCEPTED`, `resolved_at` is stamped from the logical clock, and a four-level reversal cascade runs."
    PRD §3.4: "It advances `NONE → CLAIM_OPEN` when a claim is opened, returns `CLAIM_OPEN → NONE` when the last open claim on the listing disappears, advances `CLAIM_OPEN → TAKEDOWN_PENDING` when a notice is filed and `REINSTATED → TAKEDOWN_PENDING` when one is refiled, resolves `TAKEDOWN_PENDING → REMOVED` on a removal decision or `TAKEDOWN_PENDING → CLAIM_OPEN` on a rejection or an enrolment-suspension cascade, and finally moves `REMOVED → REINSTATED` when a counter notice on the listing's notice is accepted or expires."

    Design: Difficulty/non_linear_state_machine/takedown_returns_to_submitted_through_the_resubmission_cycle
    """
    ctx = setup_removed_takedown(
        api, clock="2026-08-10T09:00:00Z", marketplace_case_ref="MP-CYCLE")
    ctx = setup_counter_noticed_takedown(api, ctx, clock="2026-08-12T09:00:00Z")
    resolve_counter_notice(api, ctx["counter_notice"]["id"], "ACCEPTED")

    reinstated = read_takedown(api, ctx["takedown"]["id"])
    assert reinstated["status"] == "REINSTATED", (
        f"Acceptance reinstates the notice, got {reinstated['status']}")
    assert reinstated["round_number"] == 1
    assert read_listing(api, ctx["listing"]["id"])["enforcement_status"] == (
        ENFORCEMENT_STATUS_REINSTATED)
    assert read_claim(api, ctx["claim"]["id"])["status"] == "SUBSTANTIATED"
    assert_seller_strikes(read_seller(api, ctx["seller"]["id"]), 0.00, 0.00, SELLER_STATUS_ACTIVE)

    set_clock(api, "2026-08-13T09:00:00Z")
    next_package = fill_and_seal_package(api, ctx["claim"]["id"], tag="r2")
    refiled = resubmit_takedown(
        api, reinstated["id"], next_package["id"], ctx["representative"]["id"])

    assert refiled["status"] == "SUBMITTED", f"Expected SUBMITTED, got {refiled['status']}"
    assert refiled["round_number"] == 2
    assert_instant_equals(refiled["submitted_at"], "2026-08-13T09:00:00Z", "submitted_at")
    assert_instant_equals(refiled["decision_due_at"],
                          expected_decision_due_at("2026-08-13T09:00:00Z"), "decision_due_at")
    assert refiled["counter_notice_deadline_at"] is None, (
        "The reversed contest window is not carried into the new round")
    listing = read_listing(api, ctx["listing"]["id"])
    assert listing["enforcement_status"] == ENFORCEMENT_STATUS_TAKEDOWN_PENDING, (
        f"REINSTATED must advance to TAKEDOWN_PENDING, got {listing['enforcement_status']}")


def test_rescreen_clears_the_listing_while_enforcement_stays_removed(api):
    """PRD §3.4: "A re-screen may flip `FLAGGED → CLEARED` while the enforcement dimension stays at `REMOVED`, and a marketplace decision may move the enforcement dimension while the screening dimension stays `FLAGGED`."
    PRD §3.4: "A screen is permitted whenever the listing's `monitor_status` is `NEW`, `CLEARED` or `FLAGGED` — re-screening in either direction is expected and normal — but it is refused with `ERR_INVALID_STATE` (HTTP 409) whenever `enforcement_status` is `TAKEDOWN_PENDING`, because a marketplace decision is in flight and the evidence behind it must not shift underneath the marketplace."
    PRD §3.4: "`violation_type` is always `NONE` whenever `monitor_status` is `NEW` or `CLEARED`."
    PRD §3.4: "The enforcement dimension, by contrast, is never touched by screening."

    Design: Difficulty/non_linear_state_machine/listing_screening_and_enforcement_dimensions_move_independently
    """
    ctx = setup_removed_takedown(api, clock="2026-08-10T09:00:00Z")
    before = read_listing(api, ctx["listing"]["id"])
    assert before["monitor_status"] == MONITOR_STATUS_FLAGGED
    assert before["enforcement_status"] == ENFORCEMENT_STATUS_REMOVED
    assert_seller_strikes(read_seller(api, ctx["seller"]["id"]), 12.55, 12.55,
                          SELLER_STATUS_ACTIVE)

    rescreened = validate_success(
        api.screen_listing(ctx["listing"]["id"], screen_payload(0.10, 0.10),
                           headers=ANALYST), 200)

    # The seller's standalone points sit at 12.55, so the 0.03 boost rung applies:
    # 0.045 plus 0.035 plus 0.20 plus 0.03 accumulates 0.3100.
    assert_score_4dp(rescreened["match_score"], match_score(0.10, 0.10, 1.0000, 0.03),
                     "match_score")
    assert_score_4dp(rescreened["match_score"], 0.3100, "match_score")
    assert rescreened["monitor_status"] == MONITOR_STATUS_CLEARED, (
        f"0.3100 clears the listing, got {rescreened['monitor_status']}")
    assert rescreened["violation_type"] == VIOLATION_TYPE_NONE, (
        f"A cleared listing resets violation_type, got {rescreened['violation_type']}")
    assert rescreened["enforcement_status"] == ENFORCEMENT_STATUS_REMOVED, (
        f"Screening never touches enforcement, got {rescreened['enforcement_status']}")
    assert rescreened["version"] == before["version"] + 1


def test_enforcement_dimension_advances_while_the_screening_verdict_stands(api):
    """PRD §3.4: "A re-screen may flip `FLAGGED → CLEARED` while the enforcement dimension stays at `REMOVED`, and a marketplace decision may move the enforcement dimension while the screening dimension stays `FLAGGED`."
    PRD §3.4: "There are exactly two couplings between them: re-screening is blocked while a notice is pending, and a claim may only be opened against a listing whose `monitor_status` is `FLAGGED`."
    PRD §3.8: "The claim's listing advances `TAKEDOWN_PENDING → REMOVED`."

    Design: Difficulty/non_linear_state_machine/listing_screening_and_enforcement_dimensions_move_independently
    """
    ctx = setup_submitted_takedown(api, clock="2026-08-10T09:00:00Z")
    pending = read_listing(api, ctx["listing"]["id"])
    assert pending["monitor_status"] == MONITOR_STATUS_FLAGGED
    assert pending["enforcement_status"] == ENFORCEMENT_STATUS_TAKEDOWN_PENDING
    assert pending["violation_type"] == VIOLATION_TYPE_COUNTERFEIT

    blocked = api.screen_listing(ctx["listing"]["id"], screen_payload(0.10, 0.10),
                                 headers=ANALYST)
    validate_error(blocked, ApiErrorId.INVALID_STATE, 409)
    unchanged = read_listing(api, ctx["listing"]["id"])
    assert unchanged["version"] == pending["version"], (
        "A refused screen must leave the listing untouched")
    assert_score_4dp(unchanged["match_score"], 1.0000, "match_score")

    ctx = setup_removed_takedown(api, ctx)
    removed = read_listing(api, ctx["listing"]["id"])
    assert removed["enforcement_status"] == ENFORCEMENT_STATUS_REMOVED, (
        f"The removal decision advances enforcement, got {removed['enforcement_status']}")
    assert removed["monitor_status"] == MONITOR_STATUS_FLAGGED, (
        f"The screening verdict is untouched by the decision, got {removed['monitor_status']}")
    assert removed["violation_type"] == VIOLATION_TYPE_COUNTERFEIT
    assert_score_4dp(removed["match_score"], 1.0000, "match_score")
    assert removed["version"] == pending["version"] + 1

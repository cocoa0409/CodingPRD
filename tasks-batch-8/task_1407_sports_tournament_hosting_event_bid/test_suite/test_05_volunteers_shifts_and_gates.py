"""Volunteer/shift workflows and cross-entity state dependency gates."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    assert_instant_equals,
    ApiErrorId,
    create_event, create_bid, create_requirement_payload, create_verified_bid,
    create_active_volunteer, create_shift, create_shift_payload,
    setup_completed_event, setup_accepted_impact_report,
    make_volunteer_headers, set_clock,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
CVB = TEST_USERS["cvb_headers"]
ANY = TEST_USERS["any_headers"]


def _get_volunteer(api, volunteer_id):
    return get_success_data(api.get_volunteer(volunteer_id, ANY))


def _get_signup(api, signup_id):
    return get_success_data(api.get_signup(signup_id, ANY))


# ===========================================================================
# Queue A: cross_entity_state_dependency /
#          bid_submit_gated_by_requirement_states
# ===========================================================================

def test_bid_submit_gated_by_requirement_states(api):
    """PRD §3.1: "Submitting the bid is the checklist's moment of truth,
    enforced in order: the event must be in `BIDDING` posture (otherwise
    `ERR_EVENT_POSTURE_FORBIDS`); every mandatory requirement must be
    `VERIFIED`; and every requirement of the bid, mandatory or not, must be in
    `VERIFIED` or `WAIVED` — any shortfall is rejected with
    `ERR_BID_REQUIREMENTS_INCOMPLETE` (HTTP 409)."
    PRD §3.1: "The `review_score` is the bid's weighted completeness score: the
    sum of `weight_points` over all `VERIFIED` requirements, plus half of each
    `WAIVED` requirement's `weight_points` rounded down to a whole number. It is
    recomputed on every verify and every waive."

    Design: Difficulty/cross_entity_state_dependency/bid_submit_gated_by_requirement_states
    """
    ev = create_event()
    bid = create_bid(ev["id"])
    rq1 = get_success_data(api.create_requirement(
        bid["id"], create_requirement_payload(kind="INSURANCE_CERT", is_mandatory=True,
                                              weight_points=100), ADMIN))
    rq2 = get_success_data(api.create_requirement(
        bid["id"], create_requirement_payload(kind="LEGACY_PLAN", is_mandatory=False,
                                              weight_points=20), ADMIN))
    # Both requirements PENDING: submit is rejected and the bid stays DRAFT.
    resp = api.submit_bid(bid["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_BID_REQUIREMENTS_INCOMPLETE)
    assert get_success_data(api.get_bid(bid["id"], ANY))["status"] == "DRAFT"
    # R1 VERIFIED + R2 WAIVED -> submit succeeds; score 100 + floor(20/2) = 110.
    get_success_data(api.submit_evidence(rq1["id"], {"evidence_uri": "s3://ev/ins.pdf"}, ADMIN))
    get_success_data(api.verify_requirement(rq1["id"], {"decision": "VERIFIED"}, REVIEWER))
    get_success_data(api.waive_requirement(rq2["id"],
                                           {"waiver_reason": "covered by city program"}, REVIEWER))
    submitted = validate_success(api.submit_bid(bid["id"], ADMIN))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["review_score"] == 110


def test_bid_submit_rejected_while_mandatory_unverified(api):
    """PRD §3.1: "Submitting the bid is the checklist's moment of truth,
    enforced in order: the event must be in `BIDDING` posture (otherwise
    `ERR_EVENT_POSTURE_FORBIDS`); every mandatory requirement must be
    `VERIFIED`; and every requirement of the bid, mandatory or not, must be in
    `VERIFIED` or `WAIVED` — any shortfall is rejected with
    `ERR_BID_REQUIREMENTS_INCOMPLETE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/bid_submit_gated_by_requirement_states
    """
    ev = create_event()
    bid = create_bid(ev["id"])
    rq1 = get_success_data(api.create_requirement(
        bid["id"], create_requirement_payload(kind="INSURANCE_CERT", is_mandatory=True,
                                              weight_points=100), ADMIN))
    rq2 = get_success_data(api.create_requirement(
        bid["id"], create_requirement_payload(kind="LEGACY_PLAN", is_mandatory=False,
                                              weight_points=20), ADMIN))
    # The non-mandatory requirement is WAIVED but the mandatory one is only
    # EVIDENCE_SUBMITTED — not VERIFIED — so the gate still rejects.
    get_success_data(api.submit_evidence(rq1["id"], {"evidence_uri": "s3://ev/ins.pdf"}, ADMIN))
    get_success_data(api.waive_requirement(rq2["id"],
                                           {"waiver_reason": "covered by city program"}, REVIEWER))
    resp = api.submit_bid(bid["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_BID_REQUIREMENTS_INCOMPLETE)
    assert get_success_data(api.get_bid(bid["id"], ANY))["status"] == "DRAFT"


# ===========================================================================
# Queue A: cross_entity_state_dependency /
#          settlement_approve_gated_by_impact_report
# ===========================================================================

def _setup_certified_settlement_with_report_under_audit():
    """COMPLETED event; block reconciled; report SUBMITTED then UNDER_AUDIT;
    settlement created and certified by ops-admin-1. Returns ctx dict."""
    from test_helpers import api_client as _api
    ctx = setup_completed_event(with_settlement=True)
    report = get_success_data(_api.create_impact_report(
        ctx["event"]["id"], {"projected_attendance": 400},
        {"X-User-ID": "ops-admin-1", "X-User-Role": "CommissionAdmin"}))
    validate_success(_api.submit_impact_report(report["id"], ADMIN))
    validate_success(_api.audit_impact_report(report["id"], {"actual_attendance": 350}, CVB))
    ctx["report"] = get_success_data(_api.get_impact_report(report["id"], ANY))
    settlement = validate_success(_api.certify_settlement(
        ctx["settlement"]["id"],
        {"X-User-ID": "ops-admin-1", "X-User-Role": "CommissionAdmin"}))
    ctx["settlement"] = settlement
    return ctx


def test_settlement_approve_gated_by_impact_report(api):
    """PRD §3.9: "Approval is segregated: a `CommissionAdmin` approves an
    `EXPENSES_CERTIFIED` settlement only if their `X-User-ID` differs from
    `certified_by_user_id` (otherwise `ERR_SOD_VIOLATION`) and an impact report
    of the event has reached `ACCEPTED` (otherwise
    `ERR_IMPACT_REPORT_NOT_ACCEPTED`, HTTP 409). Approval stamps
    `approved_by_user_id`."

    Design: Difficulty/cross_entity_state_dependency/settlement_approve_gated_by_impact_report
    """
    ctx = _setup_certified_settlement_with_report_under_audit()
    approver = {"X-User-ID": "ops-admin-2", "X-User-Role": "CommissionAdmin"}
    # The event's only report is UNDER_AUDIT: approve is rejected.
    resp = api.approve_settlement(ctx["settlement"]["id"], approver)
    validate_error(resp, ApiErrorId.ERR_IMPACT_REPORT_NOT_ACCEPTED)
    assert get_success_data(api.get_settlement(ctx["settlement"]["id"], ANY))["status"] == \
        "EXPENSES_CERTIFIED"
    # Once the report is ACCEPTED, the same approve succeeds.
    validate_success(api.audit_decision(ctx["report"]["id"], {"decision": "ACCEPTED"}, CVB))
    approved = validate_success(api.approve_settlement(ctx["settlement"]["id"], approver))
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "ops-admin-2"


def test_settlement_approve_sod_certifier_cannot_approve(api):
    """PRD §2.11: "And the administrator approving a settlement must not be the
    administrator who certified it: the approver's `X-User-ID` must differ from
    the settlement's `certified_by_user_id`."

    Design: Difficulty/cross_entity_state_dependency/settlement_approve_gated_by_impact_report
    """
    ctx = setup_completed_event(with_settlement=True)
    setup_accepted_impact_report(ctx)  # report ACCEPTED so only SoD can fail
    from test_helpers import api_client as _api
    certifier = {"X-User-ID": "ops-admin-1", "X-User-Role": "CommissionAdmin"}
    settlement = validate_success(_api.certify_settlement(ctx["settlement"]["id"], certifier))
    # The same operator approving their own certification breaches SoD.
    resp = api.approve_settlement(settlement["id"], certifier)
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
    assert get_success_data(api.get_settlement(settlement["id"], ANY))["status"] == \
        "EXPENSES_CERTIFIED"


# ===========================================================================
# Queue A: non_linear_state_machine / bid_revision_cycle_loop
# ===========================================================================

def test_bid_revision_cycle_loop(api):
    """PRD §3.1: "The revision loop is cyclic: `UNDER_REVIEW` →
    `REVISION_REQUESTED` → `SUBMITTED` → `UNDER_REVIEW`, and each resubmission
    from `REVISION_REQUESTED` re-enforces the same requirement gates, re-stamps
    `submitted_at`, and increments the bid's `revision_count` (which counts
    exactly those resubmissions, starting from 0)."

    Design: Difficulty/non_linear_state_machine/bid_revision_cycle_loop
    """
    ev = create_event()
    bid = create_verified_bid(ev["id"])
    validate_success(api.submit_bid(bid["id"], ADMIN))
    validate_success(api.review_bid(bid["id"], REVIEWER))
    validate_success(api.request_revision(bid["id"], {"revision_notes": "need hotel detail"},
                                        REVIEWER))
    # The second submit from REVISION_REQUESTED succeeds and bumps the count.
    resubmitted = validate_success(api.submit_bid(bid["id"], ADMIN))
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_count"] == 1
    # The loop can continue: review again, then award.
    validate_success(api.review_bid(bid["id"], REVIEWER))
    awarded = validate_success(api.decide_bid(bid["id"], {"decision": "AWARDED"}, REVIEWER))
    assert awarded["status"] == "AWARDED"
    from test_helpers import get_event
    assert get_event(ev["id"])["posture"] == "AWARDED"


def test_bid_revision_loop_resubmission_restamps_submitted_at(api):
    """PRD §3.1: "The revision loop is cyclic: `UNDER_REVIEW` →
    `REVISION_REQUESTED` → `SUBMITTED` → `UNDER_REVIEW`, and each resubmission
    from `REVISION_REQUESTED` re-enforces the same requirement gates, re-stamps
    `submitted_at`, and increments the bid's `revision_count` (which counts
    exactly those resubmissions, starting from 0)."

    Design: Difficulty/non_linear_state_machine/bid_revision_cycle_loop
    """
    ev = create_event()
    bid = create_verified_bid(ev["id"])
    first = validate_success(api.submit_bid(bid["id"], ADMIN))
    assert_instant_equals(first["submitted_at"], "2026-08-01T00:00:00Z", "first submitted_at")
    validate_success(api.review_bid(bid["id"], REVIEWER))
    validate_success(api.request_revision(bid["id"], {"revision_notes": "more detail"}, REVIEWER))
    set_clock("2026-08-02T00:00:00Z")
    second = validate_success(api.submit_bid(bid["id"], ADMIN))
    assert second["revision_count"] == 1
    assert_instant_equals(second["submitted_at"], "2026-08-02T00:00:00Z", "second submitted_at")


# ===========================================================================
# Corner / calculations (volunteer hours) and errors (volunteer/shift battery)
# ===========================================================================

def test_volunteer_hours_worked_aggregation(api):
    """PRD §3.8: "Each volunteer accumulates `hours_worked`: the sum of
    `credited_hours` over their signups in `WORKED` status, expressed with two
    decimal places; signups in any other status contribute zero."
    PRD §3.8: "Completion resolves every remaining signup: each `CONFIRMED`
    signup becomes `WORKED` and earns `credited_hours` equal to the shift's
    duration — the difference between `ends_at` and `starts_at` in minutes,
    divided by sixty, rounded half up to two decimal places — while each signup
    still `SIGNED_UP` is cancelled; every volunteer's `hours_worked` is then
    recomputed."

    Design: Corner/calculations/volunteer_hours_worked_aggregation
    """
    ev = create_event()
    vol = create_active_volunteer(ev["id"])
    s1 = create_shift(ev["id"], role_needed="FIELD_MARSHAL",
                      starts_at="2026-10-10T08:00:00Z", ends_at="2026-10-10T10:30:00Z",
                      capacity=2)
    s2 = create_shift(ev["id"], role_needed="PARKING",
                      starts_at="2026-10-11T08:00:00Z", ends_at="2026-10-11T09:00:00Z",
                      capacity=2)
    g1 = get_success_data(api.create_signup(s1["id"], {"volunteer_id": vol["id"]},
                                            make_volunteer_headers(vol["id"])))
    g2 = get_success_data(api.create_signup(s2["id"], {"volunteer_id": vol["id"]},
                                            make_volunteer_headers(vol["id"])))
    validate_success(api.confirm_signup(g1["id"], ADMIN))
    validate_success(api.confirm_signup(g2["id"], ADMIN))
    set_clock("2026-10-12T00:00:00Z")
    validate_success(api.complete_shift(s1["id"], ADMIN))
    validate_success(api.mark_no_show(g2["id"], ADMIN))
    g1_after = _get_signup(api, g1["id"])
    assert g1_after["status"] == "WORKED"
    assert g1_after["credited_hours"] == pytest.approx(2.5, abs=0.001)
    g2_after = _get_signup(api, g2["id"])
    assert g2_after["status"] == "NO_SHOW"
    assert g2_after["credited_hours"] is None
    assert _get_volunteer(api, vol["id"])["hours_worked"] == pytest.approx(2.5, abs=0.001)


def test_volunteer_shift_error_battery_rejected(api):
    """PRD §3.8: "`APPROVE` moves `APPLIED` → `APPROVED` but only when
    `background_check_cleared` is true (approving without it is rejected with
    `ERR_BACKGROUND_CHECK_REQUIRED`, HTTP 409)"
    PRD §3.8: "Finally, the volunteer's existing `SIGNED_UP` and `CONFIRMED`
    signups must have pairwise non-overlapping half-open shift windows from
    `starts_at` to `ends_at`; an overlapping commitment is rejected with
    `ERR_SHIFT_WINDOW_OVERLAP` (HTTP 409)."
    PRD §3.8: "Capacity bites at two depths: the shift's count of non-cancelled
    signups must be below `capacity` to accept a new signup at all, and later
    confirmation must find `confirmed_count` below `capacity` — either failure
    is `ERR_SHIFT_FULL` (HTTP 409)."
    PRD §3.8: "The `OPEN` ↔ `FILLED` pair is a self-managing bubble: when
    `confirmed_count` reaches `capacity` the shift becomes `FILLED` on its own,
    and when a cancellation or no-show later drops the count below `capacity` it
    reopens to `OPEN`."
    PRD §3.8: "the shift must be `OPEN` (otherwise `ERR_SHIFT_NOT_OPEN`, HTTP
    409)"
    PRD §3.8: "A `CommissionAdmin` creates a shift under an event with a
    `role_needed` of `FIELD_MARSHAL`, `REGISTRATION_DESK`, `SCORE_RUNNER`,
    `HOSPITALITY`, or `PARKING`, a `starts_at`, an `ends_at` strictly after the
    start (otherwise `ERR_SHIFT_TIME_INVALID`, HTTP 422), and a `capacity` of at
    least 1 — the maximum number of confirmed signups."

    Design: Corner/errors/volunteer_shift_error_battery_rejected
    """
    from test_helpers import create_volunteer_payload
    ev = create_event()
    v1 = get_success_data(api.create_volunteer(ev["id"], create_volunteer_payload(
        name="Vic One", email="v1@x.com"), ADMIN))
    v2 = create_active_volunteer(ev["id"], name="Vic Two", email="v2@x.com")
    v3 = create_active_volunteer(ev["id"], name="Vic Three", email="v3@x.com")
    s1 = create_shift(ev["id"], role_needed="FIELD_MARSHAL",
                      starts_at="2026-10-10T08:00:00Z", ends_at="2026-10-10T10:00:00Z",
                      capacity=1)
    s2 = create_shift(ev["id"], role_needed="PARKING",
                      starts_at="2026-10-10T09:00:00Z", ends_at="2026-10-10T11:00:00Z",
                      capacity=2)
    # e1: V1 never had the background check cleared.
    resp = api.transition_volunteer(v1["id"], {"action": "APPROVE"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_BACKGROUND_CHECK_REQUIRED)
    # e2: 09:00-11:00 intersects V2's existing 08:00-10:00 signup window.
    g1 = get_success_data(api.create_signup(s1["id"], {"volunteer_id": v2["id"]},
                                            make_volunteer_headers(v2["id"])))
    resp = api.create_signup(s2["id"], {"volunteer_id": v2["id"]},
                             make_volunteer_headers(v2["id"]))
    validate_error(resp, ApiErrorId.ERR_SHIFT_WINDOW_OVERLAP)
    # Confirming G1 reaches capacity 1: the shift bubbles to FILLED.
    validate_success(api.confirm_signup(g1["id"], ADMIN))
    assert get_success_data(api.get_shift(s1["id"], ANY))["status"] == "FILLED"
    # e3: S1 already holds 1 non-cancelled signup >= capacity 1.
    resp = api.create_signup(s1["id"], {"volunteer_id": v3["id"]},
                             make_volunteer_headers(v3["id"]))
    validate_error(resp, ApiErrorId.ERR_SHIFT_FULL)
    # e4: signup on a cancelled shift.
    validate_success(api.cancel_shift(s2["id"], ADMIN))
    resp = api.create_signup(s2["id"], {"volunteer_id": v2["id"]},
                             make_volunteer_headers(v2["id"]))
    validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_OPEN)
    # e5: ends_at <= starts_at.
    resp = api.create_shift(ev["id"], create_shift_payload(
        role_needed="HOSPITALITY", starts_at="2026-10-10T10:00:00Z",
        ends_at="2026-10-10T09:00:00Z", capacity=1), ADMIN)
    validate_error(resp, ApiErrorId.ERR_SHIFT_TIME_INVALID)

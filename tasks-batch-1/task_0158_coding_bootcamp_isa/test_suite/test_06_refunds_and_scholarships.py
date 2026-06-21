"""Refund computation and workflow (cooling-off / withdrawal), refund guards, and
scholarship optimistic-concurrency control.

Translates difficulty `combinatorial_formula` (refund), `transitive_cascade`
(withdraw voids ISA), corner `errors` (cooling-off, re-approve), and
`cross_cutting` OCC instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_scholarship_payload,
    assert_refund_request,
    setup_enrolled,
    setup_pending_refund,
    get_isa_for_enrollment,
    set_clock,
)

ADMIN = TEST_USERS["admissions_officer_headers"]
SERVICING = TEST_USERS["servicing_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_refund_per_line_rounding_order_pinned():
    """PRD §3.6: "The `gross_refund_cents` is the sum of those two independently rounded lines. The administrative fee is the `gross_refund_cents` multiplied by five percent, rounded half-up to whole cents. The `net_refund_cents` is the `gross_refund_cents` minus that rounded administrative fee."

    Design: Difficulty/combinatorial_formula/refund_per_line_rounding_order_pinned
    """
    # WITHDRAWAL refund, progress 40, deposit 200000, tuition 1500000.
    # deposit_line = round(200000*0.90)=180000; tuition_line = round(1500000*0.6*0.5)=450000.
    # gross = 630000; admin = round(630000*0.05)=31500; net = 598500.
    cohort, enrollment, refund = setup_pending_refund(
        financing_choice="UPFRONT", refund_reason="WITHDRAWAL",
        progress_pct=40, present=True, email="refundcalc@example.com",
    )
    approved = validate_success(api_client.approve_refund_request(refund["id"], COMPLIANCE), 200)
    assert approved["gross_refund_cents"] == 630_000
    assert approved["net_refund_cents"] == 598_500
    assert approved["status"] == "APPROVED"
    assert_refund_request(approved)


def test_refund_cooling_off_full_deposit_with_admin_fee():
    """PRD §3.6: "For a `COOLING_OFF` reason, the deposit line is the full deposit `amount_cents`."
    PRD §3.6: "For a `COOLING_OFF` reason this tuition line is zero, since no instruction has been consumed."
    PRD §3.6: "The administrative fee applies to the gross even in the cooling-off case, where the gross consists solely of the full deposit."

    Design: Difficulty/combinatorial_formula/refund_per_line_rounding_order_pinned
    """
    # COOLING_OFF from ENROLLED (cohort not started): deposit 200000, tuition_line 0.
    # gross = 200000; admin = round(200000*0.05)=10000; net = 190000.
    cohort, enrollment, refund = setup_pending_refund(
        financing_choice="UPFRONT", refund_reason="COOLING_OFF",
        progress_pct=None, email="coolfull@example.com",
    )
    approved = validate_success(api_client.approve_refund_request(refund["id"], COMPLIANCE), 200)
    assert approved["gross_refund_cents"] == 200_000
    assert approved["net_refund_cents"] == 190_000


def test_withdraw_voids_isa_and_opens_refund_depth2():
    """PRD §3.5: "Withdrawing releases the seat by decrementing `seats_committed`, voids any linked `PENDING` ISA contract to `VOIDED`, and opens a **RefundRequest** in `PENDING` status against the withdrawing enrollment."

    Design: Difficulty/transitive_cascade/withdraw_voids_isa_and_opens_refund_depth2
    """
    cohort, applicant, enrollment = setup_enrolled("ISA", email="voidisa@example.com")
    isa = get_isa_for_enrollment(enrollment["id"], SERVICING)
    assert isa["status"] == "PENDING"
    withdrawn = validate_success(
        api_client.withdraw_enrollment(enrollment["id"], ADMIN, {"refund_reason": "COOLING_OFF"}), 200
    )
    assert withdrawn["status"] == "WITHDRAWN"
    isa_after = get_success_data(api_client.get_isa_contract(isa["id"], SERVICING))
    assert isa_after["status"] == "VOIDED", "withdraw voids the linked PENDING ISA"


def test_withdraw_opens_pending_refund_request():
    """PRD §3.5: "Withdrawing releases the seat by decrementing `seats_committed`, voids any linked `PENDING` ISA contract to `VOIDED`, and opens a **RefundRequest** in `PENDING` status against the withdrawing enrollment."

    Design: Difficulty/transitive_cascade/withdraw_voids_isa_and_opens_refund_depth2
    """
    cohort, applicant, enrollment = setup_enrolled("ISA", email="openrefund@example.com")
    get_success_data(
        api_client.withdraw_enrollment(enrollment["id"], ADMIN, {"refund_reason": "COOLING_OFF"})
    )
    refunds = get_success_data(
        api_client.list_refund_requests(COMPLIANCE, params={"enrollment_id": enrollment["id"]})
    )
    rows = refunds if isinstance(refunds, list) else refunds["data"]
    assert len(rows) == 1, "withdraw opens exactly one RefundRequest"
    assert rows[0]["status"] == "PENDING", "the opened RefundRequest is PENDING"


def test_refund_approve_on_approved_returns_invalid_state():
    """PRD §3.5: "Its lifecycle is `PENDING → {APPROVED | REJECTED}`, owned by the `ComplianceOfficer`."
    PRD §2.8: "Then state: a transition attempted from a state in which it is not defined yields `ERR_INVALID_STATE`."

    Design: Corner/errors/refund_approve_on_approved_returns_invalid_state
    """
    cohort, enrollment, refund = setup_pending_refund(
        financing_choice="UPFRONT", refund_reason="COOLING_OFF",
        progress_pct=None, email="reapprove@example.com",
    )
    get_success_data(api_client.approve_refund_request(refund["id"], COMPLIANCE))
    resp = api_client.approve_refund_request(refund["id"], COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cooling_off_expired_standalone():
    """PRD §3.5: "if the reason is `COOLING_OFF`, the time elapsed between the request's `requested_at` and the enrollment's `enrolled_at` must be 14 days or fewer, counting the fourteenth day as still inside the window; a cooling-off request filed after that grace period expires is rejected with `ERR_COOLING_OFF_EXPIRED`."

    Design: Corner/errors/cooling_off_expired_standalone
    """
    # PRD §3.5 measures the cooling-off window between the refund request's
    # `requested_at` (stamped when the withdrawal opens the RefundRequest) and the
    # enrollment's `enrolled_at`. To expire the window we must advance the clock
    # *before* the withdrawal so `requested_at` lands more than 14 days after
    # `enrolled_at`; advancing it only at approval time would leave the already-
    # stamped `requested_at` within the window.
    cohort, applicant, enrollment = setup_enrolled(
        "UPFRONT", email="coolexp@example.com",
        cohort_overrides={"start_date": "2026-03-01T00:00:00Z", "end_date": "2026-06-01T00:00:00Z"},
    )
    # Advance well past the 14-day window, then withdraw so requested_at >> enrolled_at.
    set_clock("2026-02-21T00:00:00Z", ADMIN)
    get_success_data(
        api_client.withdraw_enrollment(enrollment["id"], ADMIN, {"refund_reason": "COOLING_OFF"})
    )
    refunds = get_success_data(
        api_client.list_refund_requests(COMPLIANCE, params={"enrollment_id": enrollment["id"]})
    )
    rows = refunds if isinstance(refunds, list) else refunds["data"]
    refund = rows[0]
    resp = api_client.approve_refund_request(refund["id"], COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_COOLING_OFF_EXPIRED.value)


def test_occ_correct_version_supersedes_prior_scholarship():
    """PRD §3.7: "Any prior scholarship still in `APPLIED` on the same enrollment is superseded, transitioning `APPLIED → SUPERSEDED` so that it stops contributing to the cap reduction; the newest award's `cap_reduction_pct` governs going forward."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_supersedes_prior_scholarship
    """
    cohort, applicant, enrollment = setup_enrolled("ISA", email="occ1@example.com")
    enr_id = enrollment["id"]
    v0 = enrollment["version"]
    sch1 = get_success_data(api_client.create_scholarship(
        create_scholarship_payload(enr_id, v0, kind="MERIT", cap_reduction_pct=0.20), ADMIN))
    enr_after = get_success_data(api_client.get_enrollment(enr_id, ADMIN))
    v1 = enr_after["version"]
    assert v1 != v0, "applying a scholarship increments the enrollment version"
    sch2 = validate_success(api_client.create_scholarship(
        create_scholarship_payload(enr_id, v1, kind="NEED", cap_reduction_pct=0.30), ADMIN), 201)
    s1 = get_success_data(api_client.get_scholarship(sch1["id"], ADMIN))
    assert s1["status"] == "SUPERSEDED"
    assert sch2["status"] == "APPLIED"


def test_occ_stale_enrollment_version_rejected():
    """PRD §2.9: "If another writer has already applied a scholarship to the same enrollment (legitimately superseding the prior award and incrementing the enrollment's `version`), the submitting client's view is stale, and its create is rejected with `ERR_STALE_VERSION` at HTTP 412, preventing it from silently overwriting a cap recomputation it never saw."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_enrollment_version_rejected
    """
    cohort, applicant, enrollment = setup_enrolled("ISA", email="occ2@example.com")
    enr_id = enrollment["id"]
    v0 = enrollment["version"]
    # First apply with the current version (succeeds, bumps version).
    get_success_data(api_client.create_scholarship(
        create_scholarship_payload(enr_id, v0, kind="MERIT", cap_reduction_pct=0.20), ADMIN))
    # Second apply still carrying stale v0 -> 412.
    resp = api_client.create_scholarship(
        create_scholarship_payload(enr_id, v0, kind="NEED", cap_reduction_pct=0.30), ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

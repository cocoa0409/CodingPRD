"""Regulatory actions: maker-checker segregation of duties, the disciplinary
cascade through licenses/appointments/commissions, probation spacing, and fine
allocation rounding (PRD sections 2.1, 2.4, 2.7, 3.6, 3.7).
"""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_instant_equals,
    assert_regulatory_action,
    confirm_regulatory_action,
    create_producer,
    create_regulatory_action,
    decide_application,
    get_appointment,
    get_entry_for_application,
    get_license,
    get_producer,
    issue_application,
    setup_issued_application,
    setup_producer_with_active_appointment,
    submit_application,
    validate_error,
    validate_success,
    DEFAULT_CLOCK_ISO,
    OFFICER_A_USER_ID,
    OFFICER_B_USER_ID,
    TEST_USERS,
)

LC = TEST_USERS["licensing_coordinator_headers"]
OFFICER_A = TEST_USERS["compliance_officer_a_headers"]
OFFICER_B = TEST_USERS["compliance_officer_b_headers"]


def _issue_application(producer_id, npn_state="CA", line="PROPERTY",
                       premium=10_000_000, applicant_name="Risk"):
    """Submit, approve, and issue one application for an already-licensed and
    appointed producer; returns the issued application."""
    application = submit_application(
        producer_id, state_code=npn_state, line_of_authority=line,
        applicant_name=applicant_name, premium_cents=premium,
    )
    decide_application(application["id"], "APPROVE")
    return issue_application(application["id"])


def test_confirm_suspension_cascades_license_and_appointment():
    """PRD section 3.7: "Confirming a `SUSPENSION` or `REVOCATION` cascades
    through the book."
    PRD section 3.7: "The matching license — same subject, same `state_code` —
    moves from `ACTIVE` to `SUSPENDED`, or from `ACTIVE` (or already
    `SUSPENDED`) to `REVOKED`."
    PRD section 3.7: "Every one of the subject's `ACTIVE` appointments in that
    state follows to `TERMINATION_PENDING` with `termination_reason`
    `LICENSE_INACTIVE` and `termination_initiated_at` stamped, each such
    appointment mutation incrementing its `version`."

    Design: Difficulty/transitive_cascade/regulatory_confirm_cascade_depth3
    """
    bundle = setup_issued_application(
        npn="NPN-2007", line_of_authority="PROPERTY", premium_cents=10_000_000
    )
    appointment_before = bundle["appointment"]
    action = create_regulatory_action(
        producer_id=bundle["producer"]["id"], state_code="CA",
        action_type="SUSPENSION", effective_date="2026-08-01T00:00:00Z",
    )
    confirmed = confirm_regulatory_action(action["id"])
    assert confirmed["status"] == "CONFIRMED"

    license_after = get_license(bundle["license"]["id"])
    assert license_after["status"] == "SUSPENDED", "hop 1: license suspended"

    appointment_after = get_appointment(appointment_before["id"])
    assert appointment_after["status"] == "TERMINATION_PENDING", "hop 2"
    assert appointment_after["termination_reason"] == "LICENSE_INACTIVE"
    assert_instant_equals(
        appointment_after["termination_initiated_at"], DEFAULT_CLOCK_ISO,
        "termination_initiated_at stamped to the clock",
    )
    assert appointment_after["version"] == appointment_before["version"] + 1, (
        "each cascaded appointment mutation increments its version (PRD 2.4)"
    )


def test_confirm_suspension_reholds_payable_commission():
    """PRD section 3.7: "The cascade then reaches commissions: every one of
    the producer's entries with status `PAYABLE` is re-held as `HELD` with
    `hold_reason` `REGULATORY_HOLD`, and the producer's
    `commission_held_cents` is recomputed." PRD section 3.6: "The producer's
    `commission_held_cents` is the sum of `amount_cents` across their `HELD`
    entries, recomputed on every commission status change."

    Design: Difficulty/transitive_cascade/regulatory_confirm_cascade_depth3
    """
    bundle = setup_issued_application(
        npn="NPN-2008", line_of_authority="PROPERTY", premium_cents=10_000_000
    )
    entry_before = bundle["entry"]
    assert entry_before["status"] == "PAYABLE"
    assert get_producer(bundle["producer"]["id"])["commission_held_cents"] == 0

    action = create_regulatory_action(
        producer_id=bundle["producer"]["id"], state_code="CA",
        action_type="SUSPENSION", effective_date="2026-08-01T00:00:00Z",
    )
    confirm_regulatory_action(action["id"])

    entry_after = get_entry_for_application(bundle["application"]["id"])
    assert entry_after["status"] == "HELD", "hop 3: payable entry re-held"
    assert entry_after["hold_reason"] == "REGULATORY_HOLD"
    held_total = get_producer(bundle["producer"]["id"])["commission_held_cents"]
    assert held_total == entry_after["amount_cents"], (
        "the held total is the sum over HELD entries — exactly this entry"
    )


def test_probation_spacing_364_days_rejected():
    """PRD section 3.7: "Confirming a `PROBATION` carries a spacing rule: the
    action's `effective_date` must be at least 365 days after the effective
    date of any other already-`CONFIRMED` probation against the same subject in
    the same state; a probation that lands inside that 365-day gap is rejected
    with `ERR_PROBATION_SPACING`." A 2025-12-31 probation is only 364 days
    after the confirmed 2025-01-01 probation.

    Design: Difficulty/resource_temporal_overlap/probation_spacing_buffer_365_days
    """
    producer = create_producer(npn="NPN-2024", full_name="Probationer")
    first = create_regulatory_action(
        producer_id=producer["id"], state_code="CA", action_type="PROBATION",
        effective_date="2025-01-01T00:00:00Z",
    )
    assert confirm_regulatory_action(first["id"])["status"] == "CONFIRMED"

    too_close = create_regulatory_action(
        producer_id=producer["id"], state_code="CA", action_type="PROBATION",
        effective_date="2025-12-31T00:00:00Z",
    )
    resp = api_client.confirm_regulatory_action(too_close["id"], OFFICER_B)
    validate_error(resp, ApiErrorId.ERR_PROBATION_SPACING)
    reread = validate_success(
        api_client.get_regulatory_action(too_close["id"], OFFICER_A), 200
    )
    assert reread["status"] == "REPORTED", "rejected confirmation leaves it REPORTED"


def test_probation_spacing_exactly_365_days_confirmed():
    """PRD section 3.7: "the action's `effective_date` must be at least 365
    days after the effective date of any other already-`CONFIRMED` probation
    against the same subject in the same state". Exactly 365 days satisfies
    the inclusive buffer.

    Design: Difficulty/resource_temporal_overlap/probation_spacing_buffer_365_days
    """
    producer = create_producer(npn="NPN-2025", full_name="Probationer")
    first = create_regulatory_action(
        producer_id=producer["id"], state_code="CA", action_type="PROBATION",
        effective_date="2025-01-01T00:00:00Z",
    )
    assert confirm_regulatory_action(first["id"])["status"] == "CONFIRMED"

    exactly_365 = create_regulatory_action(
        producer_id=producer["id"], state_code="CA", action_type="PROBATION",
        effective_date="2026-01-01T00:00:00Z",
    )
    confirmed = confirm_regulatory_action(exactly_365["id"])
    assert confirmed["status"] == "CONFIRMED"


def test_fine_allocation_floor_per_line_then_remainder():
    """PRD section 3.7: "each application's raw share is the fine amount
    multiplied by the application's `premium_cents` and divided by the total
    premium of the set; each raw share is rounded down to a whole cent; and the
    difference between the fine amount and the sum of the rounded shares is
    then distributed one cent at a time to applications in that same order
    until the fine is fully allocated." Three equal premiums of 10,000,000
    against a 10,001-cent fine: floor(10001/3) = 3333 each, then the 2-cent
    remainder goes to the first two applications in input-set order
    (premium descending, `created_at` ascending as the tie-break).

    Design: Difficulty/combinatorial_formula/fine_allocation_rounding_remainder
    """
    bundle = setup_producer_with_active_appointment(
        npn="NPN-2026", lines_of_authority=("PROPERTY",),
    )
    producer_id = bundle["producer"]["id"]
    # Distinct created_at instants make the created_at-ascending tie-break
    # between equal premiums deterministic.
    app1 = _issue_application(producer_id, applicant_name="A1")
    advance_clock("2026-08-02T00:00:00Z")
    app2 = _issue_application(producer_id, applicant_name="A2")
    advance_clock("2026-08-03T00:00:00Z")
    app3 = _issue_application(producer_id, applicant_name="A3")

    action = create_regulatory_action(
        producer_id=producer_id, state_code="CA", action_type="FINE",
        fine_amount_cents=10001, effective_date="2026-08-03T00:00:00Z",
    )
    confirmed = confirm_regulatory_action(action["id"])
    assert_regulatory_action(confirmed)
    assert confirmed["status"] == "CONFIRMED"

    allocations = [
        (a["application_id"], a["allocated_cents"])
        for a in confirmed["fine_allocations"]
    ]
    assert allocations == [
        (app1["id"], 3334),
        (app2["id"], 3334),
        (app3["id"], 3333),
    ], "floor-per-line 3333 each, then the 2-cent remainder in input-set order"
    assert sum(a for _, a in allocations) == 10001


def test_fine_allocation_orders_by_premium_desc():
    """PRD section 3.7: "The input set is the subject producer's applications
    with status `ISSUED` in the action's `state_code`, ordered by
    `premium_cents` descending with `created_at` ascending as the tie-break"
    and the rounded shares plus the one-cent-at-a-time remainder distribution
    produce a list "in input-set order, each pairing the source
    `application_id` with its final `allocated_cents` share." Premiums
    30,000,000 / 20,000,000 / 10,000,000 (issued in that order) against a
    10,001-cent fine: floors 5000 / 3333 / 1666, remainder 2 to the first two.

    Design: Difficulty/combinatorial_formula/fine_allocation_rounding_remainder
    """
    bundle = setup_producer_with_active_appointment(
        npn="NPN-2027", lines_of_authority=("PROPERTY",),
    )
    producer_id = bundle["producer"]["id"]
    app_big = _issue_application(producer_id, premium=30_000_000, applicant_name="Big")
    app_mid = _issue_application(producer_id, premium=20_000_000, applicant_name="Mid")
    app_small = _issue_application(producer_id, premium=10_000_000, applicant_name="Small")

    action = create_regulatory_action(
        producer_id=producer_id, state_code="CA", action_type="FINE",
        fine_amount_cents=10001, effective_date="2026-08-01T00:00:00Z",
    )
    confirmed = confirm_regulatory_action(action["id"])

    allocations = [
        (a["application_id"], a["allocated_cents"])
        for a in confirmed["fine_allocations"]
    ]
    assert allocations == [
        (app_big["id"], 5001),
        (app_mid["id"], 3334),
        (app_small["id"], 1666),
    ]
    total = sum(amount for _, amount in allocations)
    assert total == 10001 == action["fine_amount_cents"], (
        "the allocation fully distributes the fine"
    )


def test_sod_maker_cannot_confirm_own_action():
    """PRD section 2.1: "confirming or dismissing a regulatory action requires
    the acting `X-User-ID` to differ from the action's recorded
    `created_by_user_id`, so no operator may single-handedly report and ratify
    the same action. A breach is rejected with `ERR_SOD_VIOLATION`
    (HTTP 403)." PRD section 3.7: "The report records the reporter in
    `created_by_user_id`" and "whichever officer acts is recorded in
    `decided_by_user_id`". With no ISSUED applications in the state,
    `fine_allocations` is an empty list (section 3.7).

    Design: Corner/rbac/sod_maker_confirm_rejected
    """
    producer = create_producer(npn="NPN-3034", full_name="SoD Target")
    action = create_regulatory_action(
        producer_id=producer["id"], state_code="CA", action_type="FINE",
        fine_amount_cents=5000, effective_date="2026-08-01T00:00:00Z",
    )
    assert action["created_by_user_id"] == OFFICER_A_USER_ID
    assert action["status"] == "REPORTED"

    own = api_client.confirm_regulatory_action(action["id"], OFFICER_A)
    validate_error(own, ApiErrorId.ERR_SOD_VIOLATION)

    confirmed = validate_success(
        api_client.confirm_regulatory_action(action["id"], OFFICER_B), 200
    )
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["decided_by_user_id"] == OFFICER_B_USER_ID
    assert confirmed["fine_allocations"] == []

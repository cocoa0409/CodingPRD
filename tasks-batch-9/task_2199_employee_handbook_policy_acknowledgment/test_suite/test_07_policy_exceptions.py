"""Policy exceptions: the two risk-score variants and the counter compensations."""
from test_helpers import (
    api_client,
    assert_open_ack_count_matches,
    assert_same_instant,
    make_admin_headers,
    refresh_assignment,
    refresh_employee,
    refresh_package,
    set_clock,
    setup_granted_exception,
    setup_submitted_exception,
    sweep,
    validate_success,
)


def test_moderate_request_dilutes_in_the_aggregate_but_the_peak_lifts_the_ceiling():
    """PRD §3.9: "The reason factor is a lookup on `reason_code`: 20 for
    `RELIGIOUS`, 25 for `MEDICAL` ... The duration factor is `requested_days`
    multiplied by 100 and divided by 180 ... The history factor is
    `prior_exception_count` multiplied by 30 ... 40 for `CODE_OF_CONDUCT`" ...
    "a weighted mean: 20 percent of the reason factor plus 15 percent of the
    duration factor plus 25 percent of the history factor plus 40 percent of the
    category factor. The `weighted_aggregate` variant is that weighted mean rounded
    half up to two decimal places, and it is stored as `risk_score_aggregate` ...
    The `conservative_ceiling` variant takes the single largest of the four factors
    — the peak — and blends 60 percent of that peak with 40 percent of the weighted
    mean ... it is stored as `risk_score_conservative`."

    Design: Difficulty/dual_variant_calc/exception_risk_aggregate_vs_conservative_ceiling
    """
    ctx = setup_submitted_exception(
        reason_code="MEDICAL",
        requested_days=90,
        document={"max_ack_deadline_days": 5},
    )
    request = ctx["exception"]

    assert request["status"] == "SUBMITTED"
    assert request["prior_exception_count"] == 0, (
        f"a first request freezes prior_exception_count at 0, got {request['prior_exception_count']}"
    )
    assert float(request["risk_score_aggregate"]) == 28.50, (
        "reason 25, duration 50.0000, history 0 and category 40 weight to "
        "0.20*25 + 0.15*50 + 0.25*0 + 0.40*40 = 28.50, got "
        f"{request['risk_score_aggregate']}"
    )
    assert float(request["risk_score_conservative"]) == 41.40, (
        "the peak factor is the duration factor 50, so 0.60*50 + 0.40*28.50 = 41.40, "
        f"got {request['risk_score_conservative']}"
    )
    assert request["expires_at"] is None
    assert request["approving_manager_id"] is None
    assert request["deciding_reviewer_id"] is None


def test_a_single_extreme_category_factor_drives_the_conservative_variant_up():
    """PRD §3.9: "The category factor is a lookup on the `category` of the document
    owning the exception's policy version: 90 for `SAFETY` ..." ... "The
    `conservative_ceiling` variant takes the single largest of the four factors —
    the peak — and blends 60 percent of that peak with 40 percent of the weighted
    mean, rounding the result half up to two decimal places ... Because the peak
    dominates it, one extreme factor alone can push the conservative score high even
    when the weighted mean is moderate".

    Design: Difficulty/dual_variant_calc/exception_risk_aggregate_vs_conservative_ceiling
    """
    ctx = setup_submitted_exception(
        reason_code="RELIGIOUS",
        requested_days=18,
        document={"category": "SAFETY"},
    )
    request = ctx["exception"]

    assert float(request["risk_score_aggregate"]) == 41.50, (
        "reason 20, duration 10.0000, history 0 and category 90 weight to "
        "0.20*20 + 0.15*10 + 0.25*0 + 0.40*90 = 41.50, got "
        f"{request['risk_score_aggregate']}"
    )
    assert float(request["risk_score_conservative"]) == 70.60, (
        "the peak factor is the category factor 90, so 0.60*90 + 0.40*41.50 = 70.60, "
        f"got {request['risk_score_conservative']}"
    )
    assert float(request["risk_score_conservative"]) > float(
        request["risk_score_aggregate"]
    ), "the peak-weighted variant must exceed the diluted weighted mean here"


def test_admin_revocation_of_a_grant_restores_the_open_ack_counter_and_keeps_due_date():
    """PRD §3.9: "An `HRComplianceAdmin` may also cut a grant short: revoking a
    request in `GRANTED` moves it `GRANTED → REVOKED`, returns the assignment
    `EXEMPT → PENDING` and increments `open_ack_count` by 1, but does not touch
    `due_date`; an optional `reason` may accompany the revocation."

    Design: Difficulty/compensating_invariant/exception_revocation_restores_denormalized_open_ack_counter
    """
    from test_helpers import acknowledgments_for, retention_rows_for

    ctx = setup_granted_exception(document={"max_ack_deadline_days": 5})
    request, employee = ctx["exception"], ctx["employee"]
    assert request["status"] == "GRANTED"
    assert request["approving_manager_id"] == ctx["manager"]["id"]
    assert request["deciding_reviewer_id"] == ctx["reviewer_2"]["id"]
    assert_same_instant(request["expires_at"], "2026-11-13T00:00:00.000Z", "expires_at")
    assert float(request["risk_score_aggregate"]) == 28.50
    assert float(request["risk_score_conservative"]) == 41.40
    assert refresh_assignment(ctx["assignment"]["id"])["ack_state"] == "EXEMPT"
    assert refresh_employee(employee["id"])["open_ack_count"] == 0

    revoked = validate_success(
        api_client.revoke_policy_exception(
            request["id"], {"reason": "Accommodation no longer needed."}, make_admin_headers()
        )
    )
    assert revoked["status"] == "REVOKED", (
        f"GRANTED -> REVOKED expected, got {revoked['status']}"
    )

    assignment = refresh_assignment(ctx["assignment"]["id"])
    assert assignment["ack_state"] == "PENDING", (
        f"the assignment must return EXEMPT -> PENDING, got {assignment['ack_state']}"
    )
    assert_same_instant(assignment["due_date"], "2026-08-20T00:00:00Z", "due_date")
    assert refresh_employee(employee["id"])["open_ack_count"] == 1, (
        "revoking the grant must restore the open acknowledgment counter to 1"
    )
    assert_open_ack_count_matches(api_client, employee["id"], make_admin_headers())

    assert retention_rows_for(employee["id"]) == [], (
        "an exemption is not evidence, so no retention row may exist"
    )
    assert acknowledgments_for(employee["id"]) == [], (
        "an exemption is not an acknowledgment"
    )
    assert refresh_package(ctx["package"]["id"])["status"] == "RELEASED"


def test_grant_expiry_rederives_due_date_from_expires_at_without_the_four_clamps():
    """PRD §3.9: "any request whose `status` is `GRANTED` and whose `expires_at` the
    logical clock has reached or passed moves `GRANTED → EXPIRED`, its linked
    assignment returns `EXEMPT → PENDING`, the employee's `open_ack_count` is
    incremented by 1, and the assignment's `due_date` is **re-derived on a different
    basis** — it becomes the request's `expires_at` advanced by the assignment
    jurisdiction's `ack_deadline_days` whole days, with none of the four clamps of
    §3.7 applied."

    Design: Difficulty/compensating_invariant/exception_revocation_restores_denormalized_open_ack_counter
    """
    from test_helpers import refresh_exception

    ctx = setup_granted_exception(document={"max_ack_deadline_days": 5})
    request, employee = ctx["exception"], ctx["employee"]
    assert ctx["jurisdiction"]["ack_deadline_days"] == 30
    assert_same_instant(request["expires_at"], "2026-11-13T00:00:00.000Z", "expires_at")
    assert_same_instant(
        refresh_assignment(ctx["assignment"]["id"])["due_date"],
        "2026-08-20T00:00:00Z",
        "due_date",
    )

    set_clock("2026-11-13T00:00:00Z")
    sweep()

    expired = refresh_exception(request["id"])
    assert expired["status"] == "EXPIRED", (
        f"a grant whose expires_at the clock reached must expire, got {expired['status']}"
    )

    assignment = refresh_assignment(ctx["assignment"]["id"])
    assert assignment["ack_state"] == "PENDING", (
        f"expiry returns the assignment EXEMPT -> PENDING, got {assignment['ack_state']}"
    )
    assert_same_instant(assignment["due_date"], "2026-12-13T00:00:00.000Z", "due_date")
    assert refresh_employee(employee["id"])["open_ack_count"] == 1, (
        "expiry must restore the open acknowledgment counter to 1"
    )
    assert_open_ack_count_matches(api_client, employee["id"], make_admin_headers())

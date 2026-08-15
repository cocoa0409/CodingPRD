"""Field period: invitation lifecycle, submissions, windows, counters."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_survey_invite,
    build_answers,
    close_cycle,
    get_cycle,
    get_invite,
    get_success_data,
    make_active_bank,
    make_employee_headers,
    set_clock,
    setup_cycle_with_field_results,
    submit_full,
    submit_partial,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    api_client,
)
from test_helpers import TEST_USERS

HR_ADMIN = TEST_USERS["hr_admin_headers"]
PEOPLE_ANALYST = TEST_USERS["people_analyst_headers"]


def test_second_submit_on_submitted_invite_rejected(api):
    """PRD §3.4: "An employee holding an invitation in `INVITED` or `REMINDED`
    status may submit a complete response, moving the invitation to
    `SUBMITTED`; may submit a partial response, moving it to `PARTIAL`; and may
    later upgrade a `PARTIAL` invitation to `SUBMITTED` by completing the
    remaining items."
    PRD §2.8: "an action that the target resource's current state does not
    permit is rejected with `ERR_INVALID_STATE` (HTTP 409), so an illegal
    transition always surfaces as a state error rather than being masked by a
    business rule."
    PRD §3.4: "Each invitation carries exactly one response row set — the
    response's `invite_id` is unique per invitation"

    Design: Corner/state_machines/submitted_invite_rejects_second_submit
    """
    sc = setup_cycle_with_field_results(
        unit_name="TwiceUnit", manager_user_id="mgr-tw", num_employees=1,
        target_state="OPEN",
    )
    invite = sc["invites"][0]
    emp_id = invite["employee_id"]
    ci_ids = [ci["id"] for ci in sc["cycle_items"]]

    first = api.submit_invite(
        invite["id"], {"answers": build_answers(ci_ids, [3, 3, 3])},
        make_employee_headers(emp_id),
    )
    validate_success(first, 201)

    second = api.submit_invite(
        invite["id"], {"answers": build_answers(ci_ids, [5, 5, 5])},
        make_employee_headers(emp_id),
    )
    validate_error(second, ApiErrorId.ERR_INVALID_STATE)

    responses = validate_success(
        api.get_invite_response(invite["id"], make_employee_headers(emp_id)), 200
    )
    assert len(responses) == 1, "exactly one response row set per invitation"
    scores = sorted(a["score"] for a in responses[0]["answers"])
    assert scores == [3, 3, 3], "the rejected resubmission must not overwrite the original answers"


def test_employee_cannot_submit_another_employees_invite(api):
    """PRD §3.4: "Every submission is personal: the caller's `X-User-ID` must
    equal the invitation's `employee_id`, and a mismatch is rejected with
    `ERR_INVITE_OWNERSHIP` (HTTP 403)."

    Design: Corner/errors/error_invite_ownership
    """
    sc = setup_cycle_with_field_results(
        unit_name="OwnUnit", manager_user_id="mgr-ow", num_employees=2,
        target_state="OPEN",
    )
    invite_a = sc["invites"][0]
    other_emp_id = sc["employees"][1]["id"]
    ci_ids = [ci["id"] for ci in sc["cycle_items"]]

    resp = api.submit_invite(
        invite_a["id"], {"answers": build_answers(ci_ids, [4, 4, 4])},
        make_employee_headers(other_emp_id),
    )
    validate_error(resp, ApiErrorId.ERR_INVITE_OWNERSHIP)

    after = get_invite(invite_a["id"])
    assert after["status"] == "INVITED", "a rejected submission has no side effects"


def test_full_submit_with_missing_answers_rejected(api):
    """PRD §3.4: "A complete submission must cover every cycle item of the
    cycle; a partial submission must answer at least one item while leaving at
    least one unanswered. A complete submission with missing items, or a
    partial submission that is empty or actually complete, is rejected with
    `ERR_ANSWERS_INCOMPLETE` (HTTP 422)."

    Design: Corner/errors/error_answers_incomplete_on_full_submit
    """
    sc = setup_cycle_with_field_results(
        unit_name="IncUnit", manager_user_id="mgr-in", num_employees=1,
        target_state="OPEN",
    )
    invite = sc["invites"][0]
    ci_ids = [ci["id"] for ci in sc["cycle_items"]]

    resp = api.submit_invite(
        invite["id"], {"answers": build_answers(ci_ids[:2], [4, 4])},
        make_employee_headers(invite["employee_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ANSWERS_INCOMPLETE)

    after = get_invite(invite["id"])
    assert after["status"] == "INVITED"


def test_computed_cycle_counters_ignore_client_supplied_values(api):
    """PRD §3.3: "The cycle tracks its own traction through derived counters —
    `invited_count`, `submitted_count`, `partial_count`, and the computed
    `response_rate` — plus an `attrition_risk` figure that remains null until
    scoring begins."
    PRD §3.5: "Expired invitations remain in the denominator because those
    employees were invited; `invited_count` is frozen at cycle close, and a
    cycle in which nobody was ever invited has a null `response_rate`."

    Design: Corner/entities/computed_cycle_counters_input_ignored
    """
    bank, _items = make_active_bank("Computed Bank")
    resp = api.create_survey_cycle(
        {
            "label": "Computed Cycle",
            "cycle_kind": "CENSUS",
            "bank_id": bank["id"],
            "opens_at": "2026-09-01T00:00:00Z",
            "closes_at": "2026-09-15T00:00:00Z",
            "invited_count": 999,
            "response_rate": 0.99,
        },
        HR_ADMIN,
    )
    cycle = validate_success(resp, 201)
    assert cycle["invited_count"] == 0, "derived counter starts at 0; client-sent 999 ignored"
    assert cycle["response_rate"] is None, "no invitations yet -> null response_rate"
    assert cycle["submitted_count"] == 0
    assert cycle["partial_count"] == 0
    assert cycle["attrition_risk"] is None, "attrition_risk remains null until scoring begins"


def test_submit_response_immediately_visible(api):
    """PRD §3.4: "A complete submission writes the survey response row with
    `is_partial` false, stamps the invitation's `submitted_at`, adds 1 to the
    cycle's `submitted_count`, and recomputes the cycle's `response_rate`."
    PRD §2.10: "The server performs these reconciliations on its own initiative
    whenever their criteria are satisfied, without requiring a client request
    aimed at the affected parent."

    Design: Corner/consistency_model/submit_response_immediately_visible
    """
    sc = setup_cycle_with_field_results(
        unit_name="ImmUnit", manager_user_id="mgr-im", num_employees=1,
        target_state="OPEN",
    )
    invite = sc["invites"][0]
    resp = submit_full(invite, sc["cycle_items"], [5, 5, 5])
    validate_success(resp, 201)

    invite_after = get_invite(invite["id"])
    assert_survey_invite(invite_after)
    assert invite_after["status"] == "SUBMITTED", "read-after-write shows SUBMITTED at once"
    assert invite_after["submitted_at"] is not None

    cycle = get_cycle(sc["cycle"]["id"])
    assert cycle["submitted_count"] == 1
    assert cycle["response_rate"] == pytest.approx(1.0, abs=1e-9), (
        "1 of 1 invited submitted -> response_rate 1.0000 in the same logical instant"
    )


def test_submit_one_second_before_closes_at_succeeds(api):
    """PRD §2.5: "A survey cycle's field window opens at `opens_at` (inclusive)
    and ends at `closes_at` (exclusive), and `closes_at` must be strictly after
    `opens_at`."
    PRD §3.4: "Timing is enforced twice over: submitting against a cycle that
    is no longer `OPEN` is a state error rejected with `ERR_INVALID_STATE`,
    while submitting at or after `closes_at` violates the field window and is
    rejected with `ERR_WINDOW_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/submit_window_half_open_at_closes_at
    """
    sc = setup_cycle_with_field_results(
        unit_name="HalfOpenA", manager_user_id="mgr-ha", num_employees=1,
        target_state="OPEN",
    )
    invite = sc["invites"][0]
    set_clock("2026-09-14T23:59:59Z")
    resp = submit_full(invite, sc["cycle_items"], [5, 5, 5])
    invite_after = validate_success(resp, 201)
    assert invite_after["status"] == "SUBMITTED", (
        "one second before closes_at is inside the half-open window"
    )


def test_submit_exactly_at_closes_at_rejected(api):
    """PRD §2.5: "A survey cycle's field window opens at `opens_at` (inclusive)
    and ends at `closes_at` (exclusive), and `closes_at` must be strictly after
    `opens_at`."
    PRD §3.4: "Timing is enforced twice over: submitting against a cycle that
    is no longer `OPEN` is a state error rejected with `ERR_INVALID_STATE`,
    while submitting at or after `closes_at` violates the field window and is
    rejected with `ERR_WINDOW_VIOLATION`."
    PRD §2.5: "Setting the clock may cause system auto-transitions whose time
    preconditions now hold to fire — in particular the automatic close of a
    survey cycle whose close instant has been reached."

    Design: Difficulty/resource_temporal_overlap/submit_window_half_open_at_closes_at
    """
    sc = setup_cycle_with_field_results(
        unit_name="HalfOpenB", manager_user_id="mgr-hb", num_employees=1,
        target_state="OPEN",
    )
    invite = sc["invites"][0]
    set_clock("2026-09-15T00:00:00Z")
    resp = submit_full(invite, sc["cycle_items"], [5, 5, 5])
    # At exactly closes_at the submit is outside the half-open window. Because
    # setting the clock may also have auto-closed the cycle (flipping the
    # invite to EXPIRED first), the state-machine rejection is equally valid.
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_WINDOW_VIOLATION, ApiErrorId.ERR_INVALID_STATE]
    )


def test_partial_submit_sets_partial_counter_and_half_weight_rate(api):
    """PRD §3.4: "A partial submission writes the response row with
    `is_partial` true and instead adds 1 to `partial_count`, again recomputing
    `response_rate`."
    PRD §3.5: "The cycle's `response_rate` is recomputed — the rate is the sum
    of `submitted_count` plus half of `partial_count`, divided by the number of
    employees invited, rounded half-up to 4 decimal places."

    Design: Difficulty/compensating_invariant/partial_then_full_submit_conserves_invite_totals
    """
    sc = setup_cycle_with_field_results(
        unit_name="InvMid", manager_user_id="mgr-pm", num_employees=1,
        target_state="OPEN",
    )
    invite = sc["invites"][0]
    resp = submit_partial(invite, sc["cycle_items"][:1], [3])
    validate_success(resp, 201)

    cycle = get_cycle(sc["cycle"]["id"])
    assert cycle["invited_count"] == 1
    assert cycle["submitted_count"] == 0, "a partial is not a submission"
    assert cycle["partial_count"] == 1
    assert cycle["response_rate"] == pytest.approx(0.5, abs=1e-9), (
        "(0 + 0.5*1) / 1 = 0.5000 at half weight"
    )


def test_partial_then_full_submit_conserves_invite_totals(api):
    """PRD §3.4: "Upgrading from `PARTIAL` to `SUBMITTED` replaces the existing
    response row with a complete one (`is_partial` false), moves 1 from
    `partial_count` to `submitted_count`, and recomputes the rate."
    PRD §3.5: "The cycle's `response_rate` is recomputed — the rate is the sum
    of `submitted_count` plus half of `partial_count`, divided by the number of
    employees invited, rounded half-up to 4 decimal places."

    Design: Difficulty/compensating_invariant/partial_then_full_submit_conserves_invite_totals
    """
    sc = setup_cycle_with_field_results(
        unit_name="InvFin", manager_user_id="mgr-pf", num_employees=1,
        target_state="OPEN",
    )
    invite = sc["invites"][0]
    resp = submit_partial(invite, sc["cycle_items"][:1], [3])
    validate_success(resp, 201)

    upgrade = submit_full(invite, sc["cycle_items"], [3, 3, 3])
    upgraded = validate_success(upgrade, 201)
    assert upgraded["status"] == "SUBMITTED"

    cycle = get_cycle(sc["cycle"]["id"])
    assert cycle["submitted_count"] == 1, "the upgrade increments submitted_count exactly once"
    assert cycle["partial_count"] == 0, "the compensating decrement retires the partial"
    assert cycle["invited_count"] == 1, "invariant: invited_count is untouched by the pair"
    assert cycle["response_rate"] == pytest.approx(1.0, abs=1e-9), (
        "1.0000, not the 1.5000 a missing partial-decrement would double-count"
    )


def test_partial_upgrade_mid_state_counters(api):
    """PRD §3.4: "A partial submission writes the response row with
    `is_partial` true and instead adds 1 to `partial_count`, again recomputing
    `response_rate`."
    PRD §3.5: "The cycle's `response_rate` is recomputed — the rate is the sum
    of `submitted_count` plus half of `partial_count`, divided by the number of
    employees invited, rounded half-up to 4 decimal places."

    Design: Difficulty/combinatorial_formula/response_rate_evaluation_order_on_partial_to_submit
    """
    sc = setup_cycle_with_field_results(
        unit_name="RateMid", manager_user_id="mgr-rm", num_employees=4,
        target_state="OPEN", submitters=3, submit_scores=[[4, 4, 4]] * 3,
        partial_submitters=1, partial_answers=[[5]],
    )
    cycle = get_cycle(sc["cycle"]["id"])
    assert cycle["invited_count"] == 4
    assert cycle["submitted_count"] == 3
    assert cycle["partial_count"] == 1
    assert cycle["response_rate"] == pytest.approx(0.875, abs=1e-9), (
        "(3 + 0.5*1) / 4 = 0.8750 while the fourth invite is PARTIAL"
    )


def test_partial_upgrade_recomputes_rate_once_without_double_count(api):
    """PRD §3.4: "Upgrading from `PARTIAL` to `SUBMITTED` replaces the existing
    response row with a complete one (`is_partial` false), moves 1 from
    `partial_count` to `submitted_count`, and recomputes the rate."
    PRD §3.5: "The cycle's `response_rate` is recomputed — the rate is the sum
    of `submitted_count` plus half of `partial_count`, divided by the number of
    employees invited, rounded half-up to 4 decimal places."

    Design: Difficulty/combinatorial_formula/response_rate_evaluation_order_on_partial_to_submit
    """
    sc = setup_cycle_with_field_results(
        unit_name="RateFin", manager_user_id="mgr-rf", num_employees=4,
        target_state="OPEN", submitters=3, submit_scores=[[4, 4, 4]] * 3,
        partial_submitters=1, partial_answers=[[5]],
    )
    partial_invite = sc["invites"][3]
    upgrade = submit_full(partial_invite, sc["cycle_items"], [5, 4, 4])
    validate_success(upgrade, 201)

    cycle = get_cycle(sc["cycle"]["id"])
    assert cycle["submitted_count"] == 4
    assert cycle["partial_count"] == 0, "single atomic recompute: no double count"
    assert cycle["response_rate"] == pytest.approx(1.0, abs=1e-9), (
        "4/4 = 1.0000 — a decrement-then-recompute-then-increment order would "
        "transiently yield 1.1250"
    )


def test_close_expires_unanswered_invitations(api):
    """PRD §3.5: "At close, every invitation still in `INVITED` or `REMINDED`
    status flips to `EXPIRED`; invitations in `PARTIAL` status remain `PARTIAL`
    and continue to count at half weight in the response rate."

    Design: Difficulty/transitive_cascade/cycle_close_cascades_invite_expiry_then_response_rate
    """
    sc = setup_cycle_with_field_results(
        unit_name="CloseExp", manager_user_id="mgr-ce", num_employees=4,
        target_state="OPEN", submitters=1, submit_scores=[[4, 4, 4]],
    )
    close_cycle(sc["cycle"]["id"])

    statuses = [get_invite(inv["id"])["status"] for inv in sc["invites"]]
    assert statuses[0] == "SUBMITTED", "the answered invite is untouched by close"
    assert statuses[1] == "EXPIRED"
    assert statuses[2] == "EXPIRED"
    assert statuses[3] == "EXPIRED", "cascade hop 1: cycle close flips open invites to EXPIRED"


def test_close_recomputes_response_rate_with_expired_in_denominator(api):
    """PRD §3.5: "Expired invitations remain in the denominator because those
    employees were invited; `invited_count` is frozen at cycle close, and a
    cycle in which nobody was ever invited has a null `response_rate`."
    PRD §3.5: "The cycle's `response_rate` is recomputed — the rate is the sum
    of `submitted_count` plus half of `partial_count`, divided by the number of
    employees invited, rounded half-up to 4 decimal places."

    Design: Difficulty/transitive_cascade/cycle_close_cascades_invite_expiry_then_response_rate
    """
    sc = setup_cycle_with_field_results(
        unit_name="CloseRate", manager_user_id="mgr-cr", num_employees=4,
        target_state="OPEN", submitters=1, submit_scores=[[4, 4, 4]],
    )
    close_cycle(sc["cycle"]["id"])

    cycle = get_cycle(sc["cycle"]["id"])
    assert cycle["invited_count"] == 4, "EXPIRED rows stay in the invited denominator"
    assert cycle["submitted_count"] == 1
    assert cycle["partial_count"] == 0
    assert cycle["response_rate"] == pytest.approx(0.25, abs=1e-9), (
        "hop 2 recompute: 1/4 = 0.2500 with expired invites counted in the denominator only"
    )

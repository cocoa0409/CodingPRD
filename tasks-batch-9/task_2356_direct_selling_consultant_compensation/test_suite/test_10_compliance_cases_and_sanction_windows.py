"""Discipline: the cyclic case machine, the permanent escalation ladder, the closed sanction window
with its cool-off buffer, and the triggers each lifecycle refuses from the wrong state."""

from test_helpers import (
    assert_buyback_request,
    assert_compliance_case,
    assert_instant,
    constants as k,
    factories as f,
    fixtures as fx,
    make_consultant_headers,
    TEST_USERS,
    validate_error,
    validate_success,
)

CONTROLLER = TEST_USERS["finance_controller_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
COMPLIANCE_2 = TEST_USERS["compliance_officer_2_headers"]

CASE_1_FROM = "2026-08-05T00:00:00Z"
CASE_1_UNTIL = "2026-08-20T00:00:00Z"


def _case_appealed_after_probation(api):
    """A case opened, reviewed, sanctioned at PROBATION and then appealed by its subject."""
    env = fx.setup_environment(api)
    ray = fx.enroll_root(api, env, "ray@example.com", "Ray Root")
    opened = fx.open_case(api, ray, claim_type="PRODUCT_CLAIM", evidence_reference="EV-9")
    reviewed = fx.review_case(api, opened)
    sanctioned = fx.sanction_case(
        api, opened, "PROBATION", CASE_1_FROM, CASE_1_UNTIL,
        decision_reason="unapproved product claim",
    )
    appealed = fx.appeal_case(api, ray, opened, "the claim was quoted from approved literature")
    return {
        "env": env, "ray": ray, "case": opened, "opened": opened,
        "reviewed": reviewed, "sanctioned": sanctioned, "appealed": appealed,
    }


def _sanctioned_consultant_with_a_second_case_in_review(api):
    """One PROBATION already on the ladder for [2026-08-05, 2026-08-20], a second case in review."""
    env = fx.setup_environment(api)
    sam = fx.enroll_root(api, env, "sam@example.com", "Sam Root")
    first = fx.sanction_consultant(
        api, sam, sanction_level="PROBATION",
        effective_from=CASE_1_FROM, effective_until=CASE_1_UNTIL,
    )
    assert first["status"] == "SANCTIONED", "the first case is decided"
    assert first["sanction_order"] == 2, "PROBATION sits at position 2 on the ladder"
    assert first["effective_until"] == CASE_1_UNTIL, "the window the later attempts must clear"
    assert fx.read_consultant(api, sam["id"])["highest_sanction_order"] == 2, (
        "the ladder now stands at 2 for this consultant"
    )
    second = fx.review_case(
        api, fx.open_case(api, sam, claim_type="PRICING_VIOLATION", evidence_reference="EV-2")
    )
    assert second["status"] == "UNDER_REVIEW", "the second case awaits a decision"
    return env, sam, first, second


def _sanction_attempt(api, case, level, effective_from, effective_until, reason):
    return api.decide_compliance_case(
        case["id"],
        f.compliance_decision_payload(
            "SANCTION",
            sanction_level=level,
            effective_from=effective_from,
            effective_until=effective_until,
            decision_reason=reason,
        ),
        COMPLIANCE,
    )


def test_a_probation_sanction_is_not_stayed_by_the_appeal_it_provokes(api):
    """Review, sanction and appeal walk the case to APPEALED, and the consultant is still on
    probation throughout because filing an appeal buys no suspension of execution.

    PRD: "The sanction is expressly **not** stayed while the appeal is pending: there is no
    suspension of execution, and the consultant remains under whatever status the sanction imposed
    until a further review and decision says otherwise."

    Design: Difficulty/non_linear_state_machine/compliance_case_sanction_appeal_review_cycle_returns_consultant_to_active
    """
    state = _case_appealed_after_probation(api)
    assert_compliance_case(state["sanctioned"])

    assert state["opened"]["status"] == "OPEN", "a new case starts at OPEN"
    assert state["reviewed"]["status"] == "UNDER_REVIEW", "OPEN moves into review"
    assert state["reviewed"]["reviewed_by_user_id"] == k.COMPLIANCE_USER_ID, (
        "the reviewer is stamped from the caller's identity"
    )
    assert state["sanctioned"]["status"] == "SANCTIONED", "the review ended in a sanction"
    assert state["sanctioned"]["sanction_level"] == "PROBATION", "the level that was imposed"
    assert state["sanctioned"]["sanction_order"] == 2, "PROBATION is position 2 on the ladder"
    assert_instant(
        state["sanctioned"]["appeal_deadline_at"], "2026-08-19T00:00:00Z", "appeal_deadline_at"
    )
    assert_instant(state["sanctioned"]["resolved_at"], k.INITIAL_CLOCK, "resolved_at")

    assert state["appealed"]["status"] == "APPEALED", "SANCTIONED is exitable through APPEALED"
    assert state["appealed"]["appeal_count"] == 1, "one appeal is permitted per case"
    assert state["appealed"]["sanction_level"] == "PROBATION", "the appeal rewrites no sanction"

    consultant = fx.read_consultant(api, state["ray"]["id"])
    assert consultant["status"] == "PROBATION", "the pending appeal does not restore ACTIVE"
    assert consultant["active_sanction_level"] == "PROBATION", "the standing sanction is unchanged"
    assert_instant(consultant["active_sanction_until"], CASE_1_UNTIL, "active_sanction_until")
    assert consultant["highest_sanction_order"] == 2, "the ladder records the imposed level"
    assert consultant["open_case_count"] == 1, "filing the appeal reopened the case count"


def test_the_appealed_case_re_enters_review_and_a_dismissal_restores_active(api):
    """A second officer reviews the appeal and dismisses it: the consultant returns to ACTIVE with
    the sanction cleared, while the escalation ladder keeps the position it reached.

    PRD: "**Moving a case into review** is reserved to a `ComplianceOfficer`, requires `status`
    `OPEN` or `APPEALED` — anything else is `ERR_CASE_NOT_REVIEWABLE` — drives `OPEN → UNDER_REVIEW`
    or `APPEALED → UNDER_REVIEW`, and sets `reviewed_by_user_id` to the caller's `X-User-ID`."

    PRD: "Two things a dismissal deliberately does not do: `highest_sanction_order` is not reduced,
    because the escalation ladder is permanent, and a `TERMINATION` is not automatically undone,
    because restoring a terminated consultant remains the separate act described in §3.8."

    Design: Difficulty/non_linear_state_machine/compliance_case_sanction_appeal_review_cycle_returns_consultant_to_active
    """
    state = _case_appealed_after_probation(api)

    re_reviewed = fx.review_case(api, state["case"], headers=COMPLIANCE_2)
    assert re_reviewed["status"] == "UNDER_REVIEW", "APPEALED re-enters UNDER_REVIEW"
    assert re_reviewed["reviewed_by_user_id"] == k.COMPLIANCE_USER_ID_2, (
        "the second review stamps the officer who performed it"
    )
    assert re_reviewed["appeal_count"] == 1, "the appeal that caused the cycle is still recorded"

    dismissed = fx.dismiss_case(
        api, state["case"], decision_reason="appeal upheld, literature was compliant",
        headers=COMPLIANCE_2,
    )
    assert dismissed["status"] == "DISMISSED", "the second review ended in a dismissal"
    assert dismissed["decision_reason"] == "appeal upheld, literature was compliant", (
        "the dismissal records its reason"
    )

    consultant = fx.read_consultant(api, state["ray"]["id"])
    assert consultant["status"] == "ACTIVE", "dismissing the case that imposed PROBATION restores ACTIVE"
    assert consultant["active_sanction_level"] is None, "the standing sanction is cleared"
    assert consultant["active_sanction_until"] is None, "and so is its end instant"
    assert consultant["highest_sanction_order"] == 2, (
        "the ladder is asymmetric: the dismissal does not walk it back down"
    )
    assert consultant["open_case_count"] == 0, "the resolved case leaves the open count"


def test_repeating_a_level_inside_an_existing_window_names_the_escalation_error(api):
    """The second decision both repeats PROBATION and overlaps the first window, and the answer is
    the escalation error, never the window error.

    PRD: "A decision that both repeats a sanction level the consultant has already received
    **and** collides with an existing sanction window is rejected with
    `ERR_DISCIPLINARY_ESCALATION_REQUIRED`, never with `ERR_SANCTION_WINDOW_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/escalation_safety_error_precedes_sanction_window_temporal_error
    """
    env, sam, first, second = _sanctioned_consultant_with_a_second_case_in_review(api)

    validate_error(
        _sanction_attempt(
            api, second, "PROBATION", "2026-08-10T00:00:00Z", "2026-08-18T00:00:00Z",
            "second offence",
        ),
        "ERR_DISCIPLINARY_ESCALATION_REQUIRED",
        422,
    )

    unchanged = validate_success(api.get_compliance_case(second["id"], COMPLIANCE))
    assert unchanged["status"] == "UNDER_REVIEW", "a refused decision advances nothing"
    assert unchanged["sanction_order"] == 0, "no ladder position was recorded"
    assert unchanged["sanction_level"] is None, "and no level either"

    consultant = fx.read_consultant(api, sam["id"])
    assert consultant["highest_sanction_order"] == 2, "the ladder is where the first case left it"
    assert consultant["status"] == "PROBATION", "the standing sanction is untouched"


def test_raising_the_level_uncovers_the_window_conflict_the_escalation_error_hid(api):
    """The identical window at SUSPENSION clears the escalation rule and is then refused by the
    window rule, and only a window past the cool-off is accepted.

    PRD: "The closed window from `effective_from` through `effective_until` must neither intersect
    any other sanctioned window of the same consultant nor begin within the plan's
    `sanction_cooloff_days` after such a window's `effective_until`, or
    `ERR_SANCTION_WINDOW_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/escalation_safety_error_precedes_sanction_window_temporal_error
    """
    env, sam, first, second = _sanctioned_consultant_with_a_second_case_in_review(api)

    validate_error(
        _sanction_attempt(
            api, second, "PROBATION", "2026-08-10T00:00:00Z", "2026-08-18T00:00:00Z",
            "second offence",
        ),
        "ERR_DISCIPLINARY_ESCALATION_REQUIRED",
        422,
    )
    validate_error(
        _sanction_attempt(
            api, second, "SUSPENSION", "2026-08-10T00:00:00Z", "2026-08-18T00:00:00Z",
            "second offence, escalated",
        ),
        "ERR_SANCTION_WINDOW_CONFLICT",
        409,
    )
    assert validate_success(api.get_compliance_case(second["id"], COMPLIANCE))["status"] == (
        "UNDER_REVIEW"
    ), "neither rejected attempt moved the case out of review"

    accepted = validate_success(
        _sanction_attempt(
            api, second, "SUSPENSION", "2026-09-20T00:00:00Z", "2026-09-30T00:00:00Z",
            "second offence, escalated and rescheduled",
        )
    )
    assert accepted["status"] == "SANCTIONED", "a level and a window that both pass are recorded"
    assert accepted["sanction_level"] == "SUSPENSION", "the escalated level was imposed"
    assert accepted["sanction_order"] == 3, "SUSPENSION sits at position 3 on the ladder"

    consultant = fx.read_consultant(api, sam["id"])
    assert consultant["highest_sanction_order"] == 3, "the ladder rises with the new sanction"
    assert consultant["status"] == "SUSPENDED", "PROBATION moves to SUSPENDED on the escalation"


def test_a_sanction_window_may_not_touch_the_endpoint_of_an_earlier_one(api):
    """The closed interval refuses a window that starts on the instant the previous one ends, and
    an inverted window is refused earlier still by the shape rule.

    PRD: "`effective_until` must be strictly after `effective_from`, or
    `ERR_SANCTION_WINDOW_INVALID`."

    PRD: "The closed window from `effective_from` through `effective_until` must neither intersect
    any other sanctioned window of the same consultant nor begin within the plan's
    `sanction_cooloff_days` after such a window's `effective_until`, or
    `ERR_SANCTION_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/sanction_windows_reject_touching_endpoints_and_the_cooloff_buffer_start
    """
    env, sam, first, second = _sanctioned_consultant_with_a_second_case_in_review(api)

    validate_error(
        _sanction_attempt(
            api, second, "SUSPENSION", "2026-08-20T00:00:00Z", "2026-08-21T00:00:00Z",
            "touching endpoint attempt",
        ),
        "ERR_SANCTION_WINDOW_CONFLICT",
        409,
    )
    validate_error(
        _sanction_attempt(
            api, second, "SUSPENSION", "2026-09-20T00:00:00Z", "2026-09-19T00:00:00Z",
            "inverted window attempt",
        ),
        "ERR_SANCTION_WINDOW_INVALID",
        422,
    )

    still_open = validate_success(api.get_compliance_case(second["id"], COMPLIANCE))
    assert still_open["status"] == "UNDER_REVIEW", "both rejections left the case in review"
    assert still_open["effective_from"] is None, "no window was ever recorded on the case"
    assert still_open["effective_until"] is None, "including the inverted one"
    assert fx.read_consultant(api, sam["id"])["highest_sanction_order"] == 2, (
        "the ladder still shows only the first sanction"
    )


def test_a_disjoint_window_that_starts_inside_the_cooloff_buffer_is_refused(api):
    """Twenty-one days after the first sanction ends is still inside the thirty-day buffer, so the
    first admissible start is the instant just past it.

    PRD: "The closed window from `effective_from` through `effective_until` must neither intersect
    any other sanctioned window of the same consultant nor begin within the plan's
    `sanction_cooloff_days` after such a window's `effective_until`, or
    `ERR_SANCTION_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/sanction_windows_reject_touching_endpoints_and_the_cooloff_buffer_start
    """
    env, sam, first, second = _sanctioned_consultant_with_a_second_case_in_review(api)
    assert k.PLAN_DEFAULTS["sanction_cooloff_days"] == 30, "the buffer the later window must clear"

    validate_error(
        _sanction_attempt(
            api, second, "SUSPENSION", "2026-09-10T00:00:00Z", "2026-09-20T00:00:00Z",
            "disjoint but inside the cooloff buffer",
        ),
        "ERR_SANCTION_WINDOW_CONFLICT",
        409,
    )

    accepted = validate_success(
        _sanction_attempt(
            api, second, "SUSPENSION", "2026-09-20T00:00:00Z", "2026-09-30T00:00:00Z",
            "first admissible window",
        )
    )
    assert accepted["status"] == "SANCTIONED", "the first start past the buffer is accepted"
    assert_instant(accepted["effective_from"], "2026-09-20T00:00:00Z", "effective_from")
    assert accepted["sanction_order"] == 3, "the escalated level is recorded with the window"
    assert fx.read_consultant(api, sam["id"])["highest_sanction_order"] == 3, (
        "and the ladder rises to match"
    )


def test_cases_and_buyback_requests_refuse_triggers_from_the_wrong_state(api):
    """Deciding an unreviewed case, appealing an unsanctioned one, reviewing twice, refunding an
    undecided request and re-deciding a denied one are each refused on their own state.

    PRD: "The request must be `REQUESTED`, or the decision is refused with
    `ERR_BUYBACK_NOT_REQUESTED`; and a `DENY` decision must supply a `decision_reason`, since
    denials must be justified in writing whereas approvals need no reason, or it is refused with
    `ERR_DECISION_REASON_REQUIRED`."

    Design: Corner/state_machines/illegal_moves_on_compliance_cases_and_buyback_requests
    """
    env = fx.setup_environment(api)
    ann = fx.enroll_root(api, env, "ann@example.com", "Ann Root")
    order = fx.place_and_pay_order(
        api, env, ann, [("SERUM", 30)], order_type="PERSONAL_INVENTORY"
    )
    case = fx.open_case(api, ann, claim_type="PRODUCT_CLAIM", evidence_reference="EV-9")

    validate_error(
        api.decide_compliance_case(
            case["id"], f.compliance_decision_payload("DISMISS"), COMPLIANCE
        ),
        "ERR_CASE_NOT_UNDER_REVIEW",
        409,
    )
    validate_error(
        api.appeal_compliance_case(
            case["id"], f.appeal_payload("Early appeal"), make_consultant_headers(ann["id"])
        ),
        "ERR_CASE_NOT_SANCTIONED",
        409,
    )

    reviewed = fx.review_case(api, case)
    assert reviewed["status"] == "UNDER_REVIEW", "the case is reviewable exactly once from OPEN"
    assert reviewed["reviewed_by_user_id"] == k.COMPLIANCE_USER_ID, "the reviewer is recorded"
    validate_error(api.review_compliance_case(case["id"], None, COMPLIANCE),
                   "ERR_CASE_NOT_REVIEWABLE", 409)

    validate_error(
        api.decide_compliance_case(
            case["id"], f.compliance_decision_payload("SANCTION"), COMPLIANCE
        ),
        "ERR_SANCTION_FIELDS_REQUIRED",
        422,
    )
    validate_error(
        _sanction_attempt(
            api, case, "PROBATION", "2026-08-20T00:00:00Z", "2026-08-05T00:00:00Z", None
        ),
        "ERR_SANCTION_WINDOW_INVALID",
        422,
    )

    buyback = fx.request_buyback(
        api, env, ann, fx.buyback_lines_from_order(env, order, "SERUM", 2)
    )
    assert_buyback_request(buyback)
    assert buyback["status"] == "REQUESTED", "a new request starts at REQUESTED"
    validate_error(
        api.refund_buyback_request(buyback["id"], None, CONTROLLER),
        "ERR_BUYBACK_NOT_APPROVED",
        409,
    )
    validate_error(
        api.decide_buyback_request(buyback["id"], f.buyback_decision_payload("DENY"), CONTROLLER),
        "ERR_DECISION_REASON_REQUIRED",
        422,
    )

    denied = validate_success(
        api.decide_buyback_request(
            buyback["id"],
            f.buyback_decision_payload("DENY", "Not resalable on inspection"),
            CONTROLLER,
        )
    )
    assert denied["status"] == "DENIED", "a justified denial is recorded"
    assert denied["decided_by_user_id"] == k.CONTROLLER_USER_ID, "the decider is stamped"
    validate_error(
        api.decide_buyback_request(buyback["id"], f.buyback_decision_payload("APPROVE"), CONTROLLER),
        "ERR_BUYBACK_NOT_REQUESTED",
        409,
    )

    final_case = validate_success(api.get_compliance_case(case["id"], COMPLIANCE))
    assert final_case["status"] == "UNDER_REVIEW", "no refused decision moved the case"
    assert final_case["sanction_order"] == 0, "and no sanction was ever recorded"
    assert fx.read_consultant(api, ann["id"])["status"] == "ACTIVE", "the consultant is untouched"

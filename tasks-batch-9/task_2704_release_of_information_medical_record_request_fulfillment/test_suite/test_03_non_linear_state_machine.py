"""Backward edges, multi-dimensional segment state and a self-loop with a ceiling."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import Instant, assert_event_count
from test_helpers.test_users import ANALYST_2, INTAKE_1, REVIEWER_1, REVIEWER_2


# --------------------------------------------------------------------------
# request_returns_to_intake_review_with_toll_saturated_at_cap
# --------------------------------------------------------------------------
def _defect_open_for_fifteen_and_a_half_days(api):
    """Parked on the defect at 2026-08-05T00:00:00Z, cured at 2026-08-20T12:00:00Z with
    a signature date of 2026-08-10T00:00:00Z."""
    world = fx.third_party_world(api, signature_verified=False)
    request = fx.open_third_party_request(api, world)

    fx.set_clock(api, "2026-08-05T00:00:00Z")
    get_success_data(
        api.intake_decision(
            request["id"],
            f.intake_decision_payload("DEFECT", defect_reasons=["signature not verified"]),
            INTAKE_1,
        )
    )
    fx.set_clock(api, "2026-08-20T12:00:00Z")
    get_success_data(
        api.cure_authorization(
            world["authorization_id"],
            f.authorization_cure_payload(signed_at="2026-08-10T00:00:00Z"),
            INTAKE_1,
        )
    )
    return {"world": world, "request_id": request["id"]}


def test_the_backward_edge_reoccupies_intake_review_with_the_toll_clamped(api):
    """A 1339200-second defect interval is clamped to the 864000-second allowance.

    PRD: "While `defect_opened_at` is non-null the request is tolling; when the cure described in §3.2 returns the request to `INTAKE_REVIEW`, the interval closes: the whole seconds between `defect_opened_at` and the current logical clock are added to `tolled_seconds`, but only up to whatever remains of the ten-day, 864000-second total allowance, after which `defect_opened_at` returns to null, `statutory_due_at` is re-derived using the new `tolled_seconds`, both penalty measures are re-derived, and the request's `version` increments by 1."

    Design: Difficulty/non_linear_state_machine/request_returns_to_intake_review_with_toll_saturated_at_cap
    """
    scenario = _defect_open_for_fifteen_and_a_half_days(api)
    request = fx.read_request(api, scenario["request_id"])

    assert request["fulfillment_status"] == "INTAKE_REVIEW"
    assert request["defect_opened_at"] is None
    assert request["tolled_seconds"] == 864000
    assert request["tolled_seconds"] != 1339200


def test_the_saturated_toll_buys_exactly_ten_days_of_deadline(api):
    """The deadline moves by the ceiling, not by the raw interval.

    PRD: "Step four adds the tolling allowance, and the allowance is capped *before* it is added: the number of seconds added is the smaller of the request's `tolled_seconds` and a ceiling of ten whole days, which is 864000 seconds."

    Design: Difficulty/non_linear_state_machine/request_returns_to_intake_review_with_toll_saturated_at_cap
    """
    scenario = _defect_open_for_fifteen_and_a_half_days(api)
    request = fx.read_request(api, scenario["request_id"])

    assert request["statutory_due_at"] == Instant("2026-09-19T00:00:00Z")
    assert request["penalty_exposure_cents"] == 0


def test_the_second_visit_to_intake_review_can_still_be_accepted(api):
    """Re-entering INTAKE_REVIEW restores the forward edge to COMPILATION.

    PRD: "`AUTH_DEFECT_PENDING` returns to `INTAKE_REVIEW` when a defective authorization is cured, `DENIED` returns to `COMPILATION` when a denial is overturned, and `INVOICED` returns to `PENDING_INVOICE` when the invoice is voided."

    Design: Difficulty/non_linear_state_machine/request_returns_to_intake_review_with_toll_saturated_at_cap
    """
    scenario = _defect_open_for_fifteen_and_a_half_days(api)
    fx.accept_request(api, scenario["request_id"])

    accepted = fx.read_request(api, scenario["request_id"])
    assert accepted["fulfillment_status"] == "COMPILATION"
    assert accepted["tolled_seconds"] == 864000
    assert accepted["statutory_due_at"] == Instant("2026-09-19T00:00:00Z")


# --------------------------------------------------------------------------
# record_segment_three_dimensions_with_redaction_rework_cycle
# --------------------------------------------------------------------------
def _behavioral_health_segment_in_redaction(api):
    """40 general-medical pages plus 22 behavioural-health pages; the sensitive segment
    is included with redaction required and u-analyst-1 has applied nine pages."""
    world = fx.third_party_world(
        api,
        scope_categories=["GENERAL_MEDICAL", "BEHAVIORAL_HEALTH"],
        sensitive_categories_authorized=["BEHAVIORAL_HEALTH"],
    )
    request = fx.open_third_party_request(
        api, world, requested_categories=["GENERAL_MEDICAL", "BEHAVIORAL_HEALTH"]
    )
    ids = fx.walk_to_sensitive_review(
        api,
        request["id"],
        [
            {"label": "gen", "category": "GENERAL_MEDICAL", "page_count": 40},
            {"label": "bh", "category": "BEHAVIORAL_HEALTH", "page_count": 22},
        ],
    )
    fx.run_sensitive_review(api, request["id"], [f.include_decision(ids["bh"], redaction_required=True)])
    fx.apply_redaction(api, ids["bh"], 9)
    return {"world": world, "request_id": request["id"], "segment_ids": ids}


def test_rework_clears_the_applier_and_leaves_the_other_two_dimensions_alone(api):
    """REWORK moves only the redaction dimension and frees the segment for a new pass.

    PRD: "`REWORK` instead moves `redaction_status` from `APPLIED` to `REWORK`, clears `redaction_applied_by_user_id` so the same analyst is free to apply again, leaves the parent request in `REDACTION`, and touches no page-ledger field."

    Design: Difficulty/non_linear_state_machine/record_segment_three_dimensions_with_redaction_rework_cycle
    """
    scenario = _behavioral_health_segment_in_redaction(api)
    bh = scenario["segment_ids"]["bh"]

    get_success_data(
        api.redaction_decision(bh, f.redaction_decision_payload("REWORK", "over-redacted"), REVIEWER_1)
    )

    segment = fx.read_segment(api, bh)
    assert segment["redaction_status"] == "REWORK"
    assert segment["redaction_applied_by_user_id"] is None
    assert segment["retrieval_status"] == "RETRIEVED"
    assert segment["sensitivity_status"] == "AUTHORIZED_INCLUDE"

    request = fx.read_request(api, scenario["request_id"])
    assert request["fulfillment_status"] == "REDACTION"
    assert request["billable_page_count"] == 62


def test_the_second_pass_may_be_applied_by_a_different_analyst(api):
    """REWORK -> APPLIED closes the cycle and records the new applier, ledger untouched.

    PRD: "Applying records `redaction_applied_by_user_id` as the acting `X-User-ID`, does **not** yet move the page ledger — the redacted pages are not counted until approval — and increments both the segment's `version` and the parent request's `version` by 1."

    Design: Difficulty/non_linear_state_machine/record_segment_three_dimensions_with_redaction_rework_cycle
    """
    scenario = _behavioral_health_segment_in_redaction(api)
    bh = scenario["segment_ids"]["bh"]
    get_success_data(
        api.redaction_decision(bh, f.redaction_decision_payload("REWORK", "over-redacted"), REVIEWER_1)
    )

    fx.apply_redaction(api, bh, 5, headers=ANALYST_2)

    segment = fx.read_segment(api, bh)
    assert segment["redaction_status"] == "APPLIED"
    assert segment["redacted_page_count"] == 5
    assert segment["redaction_applied_by_user_id"] == "u-analyst-2"
    assert fx.read_request(api, scenario["request_id"])["billable_page_count"] == 62


def test_only_the_approved_visit_moves_the_parent_page_ledger(api):
    """APPROVE folds the five pages in and bubbles the request up to RELEASE_READY.

    PRD: "`APPROVE` moves `redaction_status` from `APPLIED` to `APPROVED`, records `redaction_approved_by_user_id` as the acting `X-User-ID`, and only now folds the segment's `redacted_page_count` into the parent request's `redacted_page_count_total` and subtracts it from `billable_page_count`; it then re-derives `redacted_page_count_total` and `billable_page_count`, and bubbles the parent request from `REDACTION` to `RELEASE_READY` provided that, after this decision is applied, no segment of the request holds `redaction_status` `OPEN`, `APPLIED` or `REWORK`."

    Design: Difficulty/non_linear_state_machine/record_segment_three_dimensions_with_redaction_rework_cycle
    """
    scenario = _behavioral_health_segment_in_redaction(api)
    bh = scenario["segment_ids"]["bh"]
    get_success_data(
        api.redaction_decision(bh, f.redaction_decision_payload("REWORK", "over-redacted"), REVIEWER_1)
    )
    fx.apply_redaction(api, bh, 5, headers=ANALYST_2)
    fx.approve_redaction(api, bh, headers=REVIEWER_1)

    segment = fx.read_segment(api, bh)
    assert segment["redaction_status"] == "APPROVED"
    assert segment["redaction_approved_by_user_id"] == "u-review-1"

    request = fx.read_request(api, scenario["request_id"])
    assert request["fulfillment_status"] == "RELEASE_READY"
    assert request["billable_page_count"] == 57
    assert request["redacted_page_count_total"] == 5

    untouched = fx.read_segment(api, scenario["segment_ids"]["gen"])
    assert untouched["retrieval_status"] == "RETRIEVED"
    assert untouched["sensitivity_status"] == "NOT_SENSITIVE"
    assert untouched["redaction_status"] == "NOT_REQUIRED"


# --------------------------------------------------------------------------
# delivery_failed_self_loop_until_attempt_limit
# --------------------------------------------------------------------------
def _released_request_with_an_open_paper_delivery(api):
    """62 pages, PAPER_MAIL with certification, invoiced at 4501, paid, released, and a
    delivery opened to the designated recipient under AES256_ZIP."""
    world = fx.third_party_world(api)
    scenario = fx.released_third_party_request(
        api, world, 62, delivery_format="PAPER_MAIL", certification_requested=True
    )
    delivery = fx.open_delivery(
        api,
        scenario["request_id"],
        delivery_format="PAPER_MAIL",
        recipient_endpoint="counsel@firm.example",
        encryption="AES256_ZIP",
    )
    return {"world": world, "request_id": scenario["request_id"], "delivery_id": delivery["id"]}


def _fail_once(api, delivery_id, reason):
    return get_success_data(
        api.record_transmission(delivery_id, f.transmission_payload("FAILED", failure_reason=reason), REVIEWER_2)
    )


def test_the_failed_self_loop_advances_only_the_attempt_count(api):
    """FAILED -> FAILED three times: the status never changes, the counter does.

    PRD: "An `outcome` of `FAILED` moves the delivery from `PENDING` or from `FAILED` back to `FAILED` — the loop is deliberate, since a failed transmission may be retried — adds 1 to `attempt_count`, records the supplied `failure_reason`, appends a `DELIVERY_FAILED` compliance event, and increments the delivery's `version` by 1."

    Design: Difficulty/non_linear_state_machine/delivery_failed_self_loop_until_attempt_limit
    """
    scenario = _released_request_with_an_open_paper_delivery(api)
    delivery_id = scenario["delivery_id"]

    for expected_count, reason in enumerate(
        ["address unverified", "returned to sender", "carrier refused the parcel"], start=1
    ):
        _fail_once(api, delivery_id, reason)
        delivery = get_success_data(api.get_delivery(delivery_id, REVIEWER_2))
        assert delivery["status"] == "FAILED"
        assert delivery["attempt_count"] == expected_count
        assert delivery["sent_at"] is None


def test_the_fourth_attempt_is_refused_at_the_three_attempt_ceiling(api):
    """The loop terminates on a condition rather than on a terminal state.

    PRD: "Both outcomes require `attempt_count` to be strictly below the ceiling of three attempts; once `attempt_count` has reached 3 no further attempt is accepted and the call is refused with `ERR_DELIVERY_ATTEMPT_LIMIT`."

    Design: Difficulty/non_linear_state_machine/delivery_failed_self_loop_until_attempt_limit
    """
    scenario = _released_request_with_an_open_paper_delivery(api)
    delivery_id = scenario["delivery_id"]
    for reason in ["address unverified", "returned to sender", "carrier refused the parcel"]:
        _fail_once(api, delivery_id, reason)

    response = api.record_transmission(delivery_id, f.transmission_payload("SENT"), REVIEWER_2)
    validate_error(response, e.ERR_DELIVERY_ATTEMPT_LIMIT, 409)

    delivery = get_success_data(api.get_delivery(delivery_id, REVIEWER_2))
    assert delivery["status"] == "FAILED"
    assert delivery["attempt_count"] == 3
    assert delivery["sent_at"] is None


def test_three_failures_leave_three_events_and_do_not_move_the_request(api):
    """Each failure is evidenced once and the parent request stays RELEASED.

    PRD: "An `outcome` of `FAILED` moves the delivery from `PENDING` or from `FAILED` back to `FAILED` — the loop is deliberate, since a failed transmission may be retried — adds 1 to `attempt_count`, records the supplied `failure_reason`, appends a `DELIVERY_FAILED` compliance event, and increments the delivery's `version` by 1."

    Design: Difficulty/non_linear_state_machine/delivery_failed_self_loop_until_attempt_limit
    """
    scenario = _released_request_with_an_open_paper_delivery(api)
    for reason in ["address unverified", "returned to sender", "carrier refused the parcel"]:
        _fail_once(api, scenario["delivery_id"], reason)

    events = fx.read_events(api, scenario["request_id"], {"event_type": "DELIVERY_FAILED"})
    assert len(events) == 3
    assert_event_count(events, "DELIVERY_FAILED", 3)
    assert fx.read_request(api, scenario["request_id"])["fulfillment_status"] == "RELEASED"

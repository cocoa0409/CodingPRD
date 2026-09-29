"""Rejection precedence: two live violations on one request, one reportable answer."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS, make_subrecipient_coordinator_headers


# ─── Presenting an offer: offer state ahead of the fiscal cap ──────────────────

def _withdrawn_offer_over_a_tight_cap(api):
    """A DRAFT offer of 21,400,000 withdrawn under a cap of 10,000,000."""
    state = fixtures.parcel_with_draft_offer(
        api, project_overrides={"total_federal_share_cap_cents": 10_000_000}
    )
    coordinator = make_subrecipient_coordinator_headers(state["project"]["id"])
    state["offer"] = validate_success(
        api.withdraw_purchase_offer(
            state["offer"]["id"],
            factories.withdraw_offer_payload(state["offer"]["id"]),
            coordinator,
        )
    )
    assert state["offer"]["status"] == "WITHDRAWN"
    assert state["offer"]["net_offer_cents"] == 21_400_000
    return state


def test_presenting_a_withdrawn_offer_reports_the_state_error_not_the_cap_error(api):
    """Both checks are live, and only the offer-state answer is permitted.

    "As noted in §2.9, when both the offer-state check and the cap check are
    violated the response is `ERR_INVALID_OFFER_STATE`."

    "They are evaluated in one **single global ascending order**, and the
    response reports the **first** violated check only."

    Design: Difficulty/priority_pair_validation_conflict/offer_state_check_outranks_federal_cap_check_on_presentation
    """
    state = _withdrawn_offer_over_a_tight_cap(api)

    response = api.present_purchase_offer(
        state["offer"]["id"],
        make_subrecipient_coordinator_headers(state["project"]["id"]),
    )

    body = validate_error(response, ApiErrorId.ERR_INVALID_OFFER_STATE.value, 409)
    assert body["error_id"] != ApiErrorId.ERR_FEDERAL_SHARE_CAP_EXCEEDED.value
    assert response.status_code != 422


def test_the_refused_presentation_moves_neither_the_offer_nor_the_obligation(api):
    """A rejected presentation books nothing and stamps nothing.

    "Presentation moves `status` to `PRESENTED`, stamps `presented_at` from the
    logical clock, computes `expires_at` as `presented_at` plus 30 calendar days,
    moves the parcel's `acquisition_status` from `VALUE_ESTABLISHED` to
    `OFFER_OUTSTANDING`, recomputes the project's `federal_obligated_cents`, and
    advances the offer's `version`, the parcel's `version` and the project's
    `version` each by 1."

    "From `DRAFT` the withdrawal is far narrower: the offer moves to `WITHDRAWN`
    with `withdrawal_reason` stored and its `version` advanced by 1, and nothing
    else moves at all - no parcel state, no `federal_obligated_cents` change (a
    `DRAFT` offer was never obligated) and no project `version` bump."

    Design: Difficulty/priority_pair_validation_conflict/offer_state_check_outranks_federal_cap_check_on_presentation
    """
    state = _withdrawn_offer_over_a_tight_cap(api)

    api.present_purchase_offer(
        state["offer"]["id"],
        make_subrecipient_coordinator_headers(state["project"]["id"]),
    )

    offer = validate_success(
        api.get_purchase_offer(
            state["offer"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert offer["status"] == "WITHDRAWN"
    assert offer["presented_at"] is None
    assert offer["net_offer_cents"] == 21_400_000

    project = validate_success(
        api.get_mitigation_project(
            state["project"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert project["federal_obligated_cents"] == 0

    parcel = validate_success(
        api.get_parcel(
            state["parcel"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert parcel["acquisition_status"] == "VALUE_ESTABLISHED"


# ─── Starting a demolition: the safety gate ahead of the readiness gate ────────

def _work_order_on_hold_without_a_survey(api):
    """A work order in UTILITY_HOLD whose only confirmed utility is WATER."""
    project = fixtures.create_draft_project(api)
    parcel = fixtures.create_parcel(api, project)
    contractor = fixtures.create_contractor(api, asbestos_certified=True)
    coordinator = make_subrecipient_coordinator_headers(project["id"])
    work_order = fixtures.issue_work_order(
        api,
        project,
        parcel["id"],
        contractor["id"],
        asbestos_survey_status="NOT_PERFORMED",
    )
    water = validate_success(
        api.create_utility_disconnection(
            work_order["id"],
            factories.create_utility_disconnection_payload(work_order["id"], "WATER"),
            coordinator,
        ),
        201,
    )
    validate_success(
        api.resolve_utility_disconnection(
            water["id"],
            factories.resolve_disconnection_payload(
                water["id"], "CONFIRMED", confirmation_reference="W-1"
            ),
            coordinator,
        )
    )
    work_order = validate_success(
        api.get_demolition_work_order(
            work_order["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert work_order["status"] == "UTILITY_HOLD"
    return {"project": project, "parcel": parcel, "work_order": work_order}


def test_the_asbestos_gate_answers_ahead_of_the_utility_gate_on_the_same_start(api):
    """A hold state is admitted precisely so both gates can fire, and safety wins.

    "Because the asbestos gate sits ahead of the utility gate, a work order that
    is simultaneously in `UTILITY_HOLD` and carrying an unusable survey reports
    `ERR_ASBESTOS_SURVEY_MISSING`, as noted in §2.9."

    "Note that `UTILITY_HOLD` is admitted by the state check specifically so that
    the more informative utility error can be reported instead."

    "A `NOT_PERFORMED` or `PERFORMED_POSITIVE` survey, or an `ABATED` survey under
    an uncertified contractor, is `ERR_ASBESTOS_SURVEY_MISSING`."

    Design: Difficulty/priority_pair_validation_conflict/asbestos_survey_check_outranks_utility_completion_check_on_demolition_start
    """
    state = _work_order_on_hold_without_a_survey(api)

    response = api.start_demolition_work_order(
        state["work_order"]["id"],
        make_subrecipient_coordinator_headers(state["project"]["id"]),
    )

    body = validate_error(response, ApiErrorId.ERR_ASBESTOS_SURVEY_MISSING.value, 422)
    assert body["error_id"] != ApiErrorId.ERR_UTILITY_DISCONNECT_INCOMPLETE.value
    assert response.status_code != 409


def test_the_refused_start_leaves_the_work_order_exactly_on_hold(api):
    """Nothing about the derived parent or its counters moves on a refused start.

    "A successful start moves `status` to `IN_PROGRESS` and advances the work
    order's `version` by 1."

    "`confirmed_utility_types` holds the `utility_type` values of children whose
    `status` is `CONFIRMED`, ordered by those children's `created_at` ascending."

    Design: Difficulty/priority_pair_validation_conflict/asbestos_survey_check_outranks_utility_completion_check_on_demolition_start
    """
    state = _work_order_on_hold_without_a_survey(api)

    api.start_demolition_work_order(
        state["work_order"]["id"],
        make_subrecipient_coordinator_headers(state["project"]["id"]),
    )

    work_order = validate_success(
        api.get_demolition_work_order(
            state["work_order"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert work_order["status"] == "UTILITY_HOLD"
    assert work_order["asbestos_survey_status"] == "NOT_PERFORMED"
    assert work_order["confirmed_utility_types"] == ["WATER"]
    assert work_order["failed_inspection_count"] == 0


# ─── Funding a closing: two 422s that only the error_id separates ──────────────

def _closing_past_the_period_and_over_the_cap(api):
    """A closing dated past the period of performance whose share also breaks the cap."""
    state = fixtures.parcel_with_scheduled_closing(
        api,
        project_overrides={
            "period_of_performance_end_date": "2026-08-31",
            "total_federal_share_cap_cents": 16_050_000,
        },
        closing_overrides={
            "scheduled_closing_date": "2026-12-01",
            "settlement_cost_cents": 8_000_000,
        },
    )
    project = validate_success(
        api.get_mitigation_project(
            state["project"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert project["federal_obligated_cents"] == 16_050_000
    state["project"] = project
    return state


def test_the_period_of_performance_error_outranks_the_cap_error_at_equal_status(api):
    """Both candidates carry 422, so only the error_id can distinguish the answer.

    "As stated in §2.9, when both the period-of-performance check and the cap
    check are violated the response is `ERR_PERIOD_OF_PERFORMANCE_EXPIRED`."

    "The `scheduled_closing_date` must be no later than the project's
    `period_of_performance_end_date`; a date strictly after it is
    `ERR_PERIOD_OF_PERFORMANCE_EXPIRED`, and a date falling exactly on the end
    date is still fundable."

    Design: Difficulty/priority_pair_validation_conflict/period_of_performance_check_outranks_federal_cap_check_on_closing_funding
    """
    state = _closing_past_the_period_and_over_the_cap(api)

    response = api.fund_closing_record(
        state["closing"]["id"], TEST_USERS["program_administrator_headers"]
    )

    body = validate_error(
        response, ApiErrorId.ERR_PERIOD_OF_PERFORMANCE_EXPIRED.value, 422
    )
    assert body["error_id"] != ApiErrorId.ERR_FEDERAL_SHARE_CAP_EXCEEDED.value


def test_the_refused_funding_leaves_the_closing_scheduled_and_the_ledger_flat(api):
    """The settlement item never enters the ledger and title never passes.

    "Funding moves the closing to `FUNDED`, stamps `funded_at` from the logical
    clock and `funded_by_user_id` with the acting `X-User-ID`, moves the parcel's
    `acquisition_status` from `OFFER_ACCEPTED` to `CLOSED`, recomputes the
    project's `federal_obligated_cents` to include the settlement-cost item."

    "A `SCHEDULED` closing contributes nothing to the obligation ledger."

    Design: Difficulty/priority_pair_validation_conflict/period_of_performance_check_outranks_federal_cap_check_on_closing_funding
    """
    state = _closing_past_the_period_and_over_the_cap(api)

    api.fund_closing_record(
        state["closing"]["id"], TEST_USERS["program_administrator_headers"]
    )

    closing = validate_success(
        api.get_closing_record(
            state["closing"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert closing["status"] == "SCHEDULED"
    assert closing["funded_at"] is None
    assert closing["funded_by_user_id"] is None

    project = validate_success(
        api.get_mitigation_project(
            state["project"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert project["federal_obligated_cents"] == 16_050_000

    parcel = validate_success(
        api.get_parcel(
            state["parcel"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert parcel["acquisition_status"] == "OFFER_ACCEPTED"

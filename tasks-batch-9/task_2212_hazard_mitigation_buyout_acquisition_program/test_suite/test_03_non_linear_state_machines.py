"""Non-linear state machines: parallel dimensions, counted cycles and derived parents."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions, factories, fixtures
from test_helpers.test_users import TEST_USERS, make_subrecipient_coordinator_headers


# ─── The parcel's two orthogonal dimensions ───────────────────────────────────

def _parcel_interested_with_submitted_review(api):
    """A parcel still only INTERESTED whose REVIEW appraisal is awaiting a decision."""
    state = fixtures.parcel_interested(api)
    state["initial_appraisal"] = fixtures.accepted_initial_appraisal(
        api, state["parcel"]["id"]
    )
    review = validate_success(
        api.create_appraisal(
            state["parcel"]["id"],
            factories.create_review_appraisal_payload(
                state["parcel"]["id"], state["initial_appraisal"]["id"]
            ),
            TEST_USERS["review_appraiser_headers"],
        ),
        201,
    )
    state["review_appraisal"] = validate_success(
        api.submit_appraisal(review["id"], TEST_USERS["review_appraiser_headers"])
    )
    return state


def test_acquisition_reaches_value_established_while_participation_is_only_interested(api):
    """The acquisition dimension advances without waiting for the voluntary signature.

    "A parcel carries two orthogonal state dimensions that advance on separate
    schedules and must never be conflated."

    "Accepting a `REVIEW` appraisal additionally moves the parcel's
    `acquisition_status` from `APPRAISAL_IN_PROGRESS` to `VALUE_ESTABLISHED` and
    advances the parcel's `version` by 1 - this is the moment the parcel's value
    is established and offers become possible."

    Design: Difficulty/non_linear_state_machine/parcel_participation_and_acquisition_dimensions_advance_independently
    """
    state = _parcel_interested_with_submitted_review(api)

    accepted = validate_success(
        api.review_appraisal(
            state["review_appraisal"]["id"],
            factories.review_decision_payload(state["review_appraisal"]["id"], "ACCEPT"),
            TEST_USERS["review_appraiser_2_headers"],
        )
    )
    assert accepted["status"] == "ACCEPTED"

    parcel = validate_success(
        api.get_parcel(
            state["parcel"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert parcel["participation_status"] == "INTERESTED"
    assert parcel["acquisition_status"] == "VALUE_ESTABLISHED"


def test_confirming_voluntary_participation_leaves_the_acquisition_dimension_alone(api):
    """The later signature moves only the participation dimension.

    "A parcel at `DECLINED` on the participation dimension can still be at
    `ACQUISITION_CANCELLED` or back at `NOT_STARTED` on the acquisition
    dimension; a parcel at `VOLUNTARY_CONFIRMED` can be anywhere from
    `NOT_STARTED` to `OPEN_SPACE_RECORDED`."

    "The supplied date is stored on the parcel as
    `voluntary_acknowledgement_signed_on` and the parcel's `version` advances by
    1."

    Design: Difficulty/non_linear_state_machine/parcel_participation_and_acquisition_dimensions_advance_independently
    """
    state = _parcel_interested_with_submitted_review(api)
    validate_success(
        api.review_appraisal(
            state["review_appraisal"]["id"],
            factories.review_decision_payload(state["review_appraisal"]["id"], "ACCEPT"),
            TEST_USERS["review_appraiser_2_headers"],
        )
    )

    parcel = validate_success(
        api.record_participation(
            state["parcel"]["id"],
            factories.participation_payload(state["parcel"]["id"], "CONFIRM_VOLUNTARY"),
            make_subrecipient_coordinator_headers(state["project"]["id"]),
        )
    )

    assert parcel["participation_status"] == "VOLUNTARY_CONFIRMED"
    assert parcel["acquisition_status"] == "VALUE_ESTABLISHED"
    assert parcel["voluntary_acknowledgement_signed_on"] == "2026-08-01"


# ─── The counted return/resubmit cycle ────────────────────────────────────────

def _submitted_initial_appraisal(api):
    state = fixtures.create_approved_project(api)
    appraisal = validate_success(
        api.create_appraisal(
            state["parcel"]["id"],
            factories.create_appraisal_payload(state["parcel"]["id"]),
            TEST_USERS["staff_appraiser_headers"],
        ),
        201,
    )
    state["appraisal"] = validate_success(
        api.submit_appraisal(appraisal["id"], TEST_USERS["staff_appraiser_headers"])
    )
    assert state["appraisal"]["revision_count"] == 0
    return state


def _return_appraisal(api, appraisal_id):
    return validate_success(
        api.review_appraisal(
            appraisal_id,
            factories.review_decision_payload(
                appraisal_id, "RETURN", review_note="adjustment grid unsupported"
            ),
            TEST_USERS["review_appraiser_headers"],
        )
    )


def test_each_return_increments_the_revision_counter_on_the_same_row(api):
    """Two returns leave revision_count at 2 while the row keeps cycling.

    "`RETURN` is admitted only from `SUBMITTED`; a return attempted against an
    appraisal already in `RETURNED_FOR_REVISION` is
    `ERR_INVALID_APPRAISAL_STATE`. It moves `status` to
    `RETURNED_FOR_REVISION`, increments `revision_count` by 1, and advances
    `version` by 1."

    "The submission may optionally carry a revised `effective_date` and a revised
    `indicated_value_cents`, which overwrite the stored values before the
    validity window is computed."

    Design: Difficulty/non_linear_state_machine/appraisal_return_resubmit_cycle_increments_revision_count_twice
    """
    state = _submitted_initial_appraisal(api)
    appraisal_id = state["appraisal"]["id"]

    first_return = _return_appraisal(api, appraisal_id)
    assert first_return["status"] == "RETURNED_FOR_REVISION"
    assert first_return["revision_count"] == 1

    validate_success(
        api.submit_appraisal(
            appraisal_id,
            TEST_USERS["staff_appraiser_headers"],
            payload=factories.submit_appraisal_payload(
                appraisal_id, indicated_value_cents=20_500_000
            ),
        )
    )
    second_return = _return_appraisal(api, appraisal_id)
    assert second_return["revision_count"] == 2


def test_the_third_submission_is_still_legal_at_a_revision_count_of_exactly_two(api):
    """A revision_count of exactly 2 submits, so the row survives two returns.

    "Resubmission after a return is bounded. A submission from
    `RETURNED_FOR_REVISION` requires `revision_count` to be at most 2; a
    `revision_count` of exactly 2 still submits, and a `revision_count` of 3 is
    refused with `ERR_APPRAISAL_REVISION_LIMIT`."

    "On submission the server computes `validity_end_date` as `effective_date`
    plus 12 calendar months, clamped to month end where the anchor day-of-month
    does not exist in the target month."

    Design: Difficulty/non_linear_state_machine/appraisal_return_resubmit_cycle_increments_revision_count_twice
    """
    state = _submitted_initial_appraisal(api)
    appraisal_id = state["appraisal"]["id"]

    _return_appraisal(api, appraisal_id)
    validate_success(
        api.submit_appraisal(
            appraisal_id,
            TEST_USERS["staff_appraiser_headers"],
            payload=factories.submit_appraisal_payload(
                appraisal_id, indicated_value_cents=20_500_000
            ),
        )
    )
    _return_appraisal(api, appraisal_id)

    resubmitted = validate_success(
        api.submit_appraisal(
            appraisal_id,
            TEST_USERS["staff_appraiser_headers"],
            payload=factories.submit_appraisal_payload(
                appraisal_id, indicated_value_cents=21_000_000
            ),
        )
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_count"] == 2
    assert resubmitted["indicated_value_cents"] == 21_000_000
    assert resubmitted["validity_end_date"] == "2027-07-01"

    accepted = validate_success(
        api.review_appraisal(
            appraisal_id,
            factories.review_decision_payload(appraisal_id, "ACCEPT"),
            TEST_USERS["review_appraiser_headers"],
        )
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["revision_count"] == 2


# ─── The derived work-order parent and the FAILED self-loop ───────────────────

def _ready_work_order(api):
    """A READY work order on a DRAFT project: the parcel dimension is not gated here."""
    project = fixtures.create_draft_project(api)
    parcel = fixtures.create_parcel(api, project)
    contractor = fixtures.create_contractor(
        api, asbestos_certified=True, max_concurrent_work_orders=1
    )
    work_order = fixtures.issue_work_order(api, project, parcel["id"], contractor["id"])
    disconnections = fixtures.order_all_utility_disconnections(
        api, project, work_order["id"]
    )
    fixtures.confirm_all_utility_disconnections(api, project, disconnections)
    work_order = validate_success(
        api.get_demolition_work_order(
            work_order["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert work_order["status"] == "READY"
    return {
        "project": project,
        "parcel": parcel,
        "contractor": contractor,
        "work_order": work_order,
        "disconnections": disconnections,
    }


def test_revoking_one_confirmation_bubbles_the_parent_back_from_ready_to_hold(api):
    """A FAILED outcome against a CONFIRMED child drags the derived parent backwards.

    "A `FAILED` outcome from `CONFIRMED` is the bubble-up revocation: `status`
    becomes `FAILED`, `failed_attempt_count` increments, the parent recomputes
    `confirmed_utility_types` and, if the parent was `READY`, falls back to
    `UTILITY_HOLD`; both the child's `version` and the parent's `version`
    advance by 1."

    "The parent is `READY` exactly when every `utility_type` listed in
    `required_utility_types` has a child with that `utility_type` in `status`
    `CONFIRMED`, and it cycles back to `UTILITY_HOLD` the moment any of those
    confirmations is revoked."

    "`buffered_start` is `scheduled_start` minus 24 hours and `buffered_end` is
    `scheduled_end` plus 24 hours, and the buffered occupation interval is
    **closed** - both endpoints are included."

    Design: Difficulty/non_linear_state_machine/utility_disconnection_failed_self_loop_bubbles_work_order_back_to_hold
    """
    state = _ready_work_order(api)
    water = state["disconnections"]["WATER"]
    coordinator = make_subrecipient_coordinator_headers(state["project"]["id"])

    assertions.assert_buffered_window(
        state["work_order"], "2026-10-04T08:00:00Z", "2026-10-07T17:00:00Z"
    )

    failed = validate_success(
        api.resolve_utility_disconnection(
            water["id"],
            factories.resolve_disconnection_payload(water["id"], "FAILED"),
            coordinator,
        )
    )
    assert failed["status"] == "FAILED"
    assert failed["failed_attempt_count"] == 1

    parent = validate_success(
        api.get_demolition_work_order(
            state["work_order"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert parent["status"] == "UTILITY_HOLD"
    assert "WATER" not in parent["confirmed_utility_types"]


def test_failed_to_failed_is_a_counted_self_loop_and_reconfirmation_restores_ready(api):
    """A second failure increments the counter without moving either status.

    "A `FAILED` outcome from `FAILED` likewise advances only the child's
    `version` by 1 while incrementing `failed_attempt_count` and re-stamping
    `resolved_at`; `status` stays `FAILED` and the parent is not touched."

    "A `CONFIRMED` outcome from `PENDING` or from `FAILED` sets `status` to
    `CONFIRMED`, stores the `confirmation_reference`, recomputes the parent's
    `confirmed_utility_types` and, if the confirmed set has just become
    complete, moves the parent from `UTILITY_HOLD` to `READY`; the child's
    `version` and the parent's `version` each advance by 1."

    Design: Difficulty/non_linear_state_machine/utility_disconnection_failed_self_loop_bubbles_work_order_back_to_hold
    """
    state = _ready_work_order(api)
    water = state["disconnections"]["WATER"]
    coordinator = make_subrecipient_coordinator_headers(state["project"]["id"])

    validate_success(
        api.resolve_utility_disconnection(
            water["id"],
            factories.resolve_disconnection_payload(water["id"], "FAILED"),
            coordinator,
        )
    )
    looped = validate_success(
        api.resolve_utility_disconnection(
            water["id"],
            factories.resolve_disconnection_payload(water["id"], "FAILED"),
            coordinator,
        )
    )
    assert looped["status"] == "FAILED"
    assert looped["failed_attempt_count"] == 2

    reconfirmed = validate_success(
        api.resolve_utility_disconnection(
            water["id"],
            factories.resolve_disconnection_payload(
                water["id"], "CONFIRMED", confirmation_reference="W-2"
            ),
            coordinator,
        )
    )
    assert reconfirmed["status"] == "CONFIRMED"
    assert reconfirmed["failed_attempt_count"] == 2
    assert reconfirmed["confirmation_reference"] == "W-2"

    parent = validate_success(
        api.get_demolition_work_order(
            state["work_order"]["id"], TEST_USERS["program_administrator_headers"]
        )
    )
    assert parent["status"] == "READY"
    assert sorted(parent["confirmed_utility_types"]) == sorted(
        ["WATER", "ELECTRIC", "GAS", "SEWER"]
    )

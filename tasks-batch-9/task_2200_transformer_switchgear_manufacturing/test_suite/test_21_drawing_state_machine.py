"""The submittal-drawing state machine and the engineering dimension it drives."""

from test_helpers import (
    CUSTOMER_REVIEWER,
    DESIGN_ENGINEER,
    PLANT_ADMIN,
    USER_DESIGN_1,
    USER_REVIEWER_1,
    USER_REVIEWER_2,
    assert_order_state,
    assert_instant_equals,
    begin_review,
    create_drawing,
    create_order,
    disposition,
    make_headers,
    read_order,
    set_clock,
    submit_drawing,
    submittal_drawing_payload,
)
from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers.api_errors import ApiErrorId


def _order(api, order_number):
    return create_order(
        api,
        order_number=order_number,
        customer_name="Riverbend Utility",
        product_family="MV_SWITCHGEAR",
        rated_kv=15,
        contract_value_cents=4000000,
        sold_at="2026-01-05T00:00:00Z",
        promised_ship_at="2026-10-01T00:00:00Z",
    )


def _read_drawing(api, drawing_id):
    return validate_success(api.get_submittal_drawing(drawing_id, PLANT_ADMIN))


def test_the_first_drawing_on_an_order_is_draft_at_round_one(api):
    """PRD 3.2: "The server assigns `revision_round` itself — 1 for the first
    package on the order... and sets `supersedes_drawing_id` to the immediately
    preceding revision, leaving it null for round 1... A drawing row is born in
    `DRAFT` with `notes_count` defaulting to 0."

    Design: Corner/state_machines/first_submittal_drawing_starts_in_draft_at_revision_round_one
    """
    set_clock(api, "2026-03-02T08:00:00Z")
    order = _order(api, "ORD-CORNER-SM1")
    drawing = validate_success(
        api.create_submittal_drawing(
            order["id"],
            submittal_drawing_payload(
                order["version"],
                drawing_set_code="DS-100",
                authored_by_user_id=USER_DESIGN_1,
            ),
            DESIGN_ENGINEER,
        ),
        201,
    )
    assert drawing["status"] == "DRAFT"
    assert drawing["revision_round"] == 1
    assert drawing["supersedes_drawing_id"] is None
    assert drawing["engineered_order_id"] == order["id"]
    assert drawing["authored_by_user_id"] == USER_DESIGN_1
    assert drawing["reviewed_by_user_id"] is None
    assert drawing["notes_count"] == 0
    assert drawing["submitted_at"] is None


def test_submitting_moves_engineering_only_and_leaves_fulfilment_in_planning(api):
    """PRD 3.2: "Submission by the authoring `DesignEngineer` moves the drawing
    `DRAFT → SUBMITTED`, stamps `submitted_at` from the logical clock"; PRD 2.6:
    "It has two, and they move independently."

    Design: Corner/state_machines/submit_drawing_advances_engineering_dimension_leaving_fulfillment_in_planning
    """
    set_clock(api, "2026-03-02T08:00:00Z")
    order = _order(api, "ORD-CORNER-SM2")
    drawing = create_drawing(api, order["id"], drawing_set_code="DS-100")
    submitted = submit_drawing(api, drawing["id"])
    assert submitted["status"] == "SUBMITTED"
    assert_instant_equals(submitted["submitted_at"], "2026-03-02T08:00:00Z")
    assert_order_state(
        read_order(api, order["id"]),
        engineering_status="SUBMITTAL_IN_REVIEW",
        fulfillment_status="PLANNING",
        production_posture="OPEN",
        posture_reason_codes=[],
    )


def test_beginning_review_before_submission_is_an_invalid_transition(api):
    """PRD 2.11: "a row whose current status is not a legal source for the
    requested transition yields `ERR_INVALID_STATE_TRANSITION` (HTTP 409)"; PRD
    3.2 makes review begin from `SUBMITTED`.

    Design: Corner/state_machines/begin_review_on_draft_drawing_returns_invalid_state_transition
    """
    set_clock(api, "2026-03-02T08:00:00Z")
    order = _order(api, "ORD-CORNER-SM3")
    drawing = create_drawing(api, order["id"], drawing_set_code="DS-100")
    validate_error(
        api.begin_review_drawing(drawing["id"], {}, CUSTOMER_REVIEWER),
        ApiErrorId.INVALID_STATE_TRANSITION,
        409,
    )
    assert _read_drawing(api, drawing["id"])["status"] == "DRAFT"
    assert read_order(api, order["id"])["engineering_status"] == "ENG_OPEN"


def test_replaying_submit_is_refused_and_does_not_restamp_the_timestamp(api):
    """PRD 2.11: "a row whose current status is not a legal source for the
    requested transition yields `ERR_INVALID_STATE_TRANSITION` (HTTP 409)"; PRD
    2.10: "every timestamp the server writes (`submitted_at`...) is taken from
    that clock at the moment of the transition."

    Design: Corner/state_machines/second_submit_of_already_submitted_drawing_returns_invalid_state_transition
    """
    set_clock(api, "2026-03-02T08:00:00Z")
    order = _order(api, "ORD-CORNER-SM4")
    drawing = create_drawing(api, order["id"], drawing_set_code="DS-100")
    submit_drawing(api, drawing["id"])

    set_clock(api, "2026-03-03T09:00:00Z")
    validate_error(
        api.submit_drawing(drawing["id"], {}, DESIGN_ENGINEER),
        ApiErrorId.INVALID_STATE_TRANSITION,
        409,
    )
    unchanged = _read_drawing(api, drawing["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert_instant_equals(unchanged["submitted_at"], "2026-03-02T08:00:00Z")
    assert read_order(api, order["id"])["engineering_status"] == "SUBMITTAL_IN_REVIEW"


def test_the_terminal_guard_outranks_the_source_state_guard_on_an_approved_drawing(api):
    """PRD 2.11: "First, a target row already in a terminal state for its
    dimension is rejected with `ERR_TERMINAL_STATE` (HTTP 409); the terminal
    values are... `APPROVED`, `APPROVED_AS_NOTED` and `VOID` for drawings"; and
    "Next, a row whose current status is not a legal source for the requested
    transition yields `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

    Design: Corner/state_machines/begin_review_on_approved_drawing_returns_terminal_state
    """
    set_clock(api, "2026-03-02T08:00:00Z")
    order = _order(api, "ORD-CORNER-SM5")
    drawing = create_drawing(api, order["id"], drawing_set_code="DS-100")
    submit_drawing(api, drawing["id"])
    begin_review(api, drawing["id"])
    approved = disposition(
        api,
        drawing["id"],
        "APPROVED",
        USER_REVIEWER_1,
        notes_count=0,
        as_noted_changes_bill_of_material=False,
    )
    assert approved["status"] == "APPROVED"

    validate_error(
        api.begin_review_drawing(
            drawing["id"], {}, make_headers(USER_REVIEWER_2, "CustomerReviewer")
        ),
        ApiErrorId.TERMINAL_STATE,
        409,
    )
    assert _read_drawing(api, drawing["id"])["status"] == "APPROVED"
    reopened = read_order(api, order["id"])
    assert reopened["engineering_status"] == "DESIGN_RELEASED"
    assert reopened["released_drawing_revision"] == 1

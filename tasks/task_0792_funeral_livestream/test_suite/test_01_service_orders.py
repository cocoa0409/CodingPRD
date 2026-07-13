"""Service order creation, existence, input validation, and the parallel status model.

Covers queue-B corner instances (entities / state_machines sections) and the
queue-A non-linear-state-machine instance about independent axes on one order.
"""
from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_error, ApiErrorId,
    assert_service_order,
    create_funeral_home_payload, create_venue_payload, create_service_order_payload,
    setup_home_and_venue, setup_ended_order, transition_order,
    NON_EXISTENT_UUID,
)

ADMIN = TEST_USERS["admin_headers"]


def test_create_service_order_starts_with_default_axes(api):
    """PRD §2.7: "When an order is created, `broadcast_status` is `DRAFT`,
    `settlement_status` is `UNBILLED`, `stream_status` is `PENDING`,
    `recording_status` is `NONE`, and `memorial_status` is `DRAFT`."

    Design: Corner/entities/create_service_order_returns_201_with_default_axes
    """
    base = setup_home_and_venue()
    payload = create_service_order_payload(base["home"]["id"], base["venue"]["id"],
                                           decedent_name="A Cee")
    resp = api.create_service_order(payload, ADMIN)
    data = validate_success(resp, 201)
    assert_service_order(data)
    assert data["broadcast_status"] == "DRAFT"
    assert data["settlement_status"] == "UNBILLED"
    assert data["stream_status"] == "PENDING"
    assert data["memorial_status"] == "DRAFT"
    assert data["recording_status"] == "NONE"


def test_create_service_order_version_starts_at_one(api):
    """PRD §2.4: "`version`: an integer that starts at its initial value on
    creation and increments by one on every mutation of the resource."

    Design: Corner/entities/create_service_order_returns_201_with_default_axes
    """
    base = setup_home_and_venue()
    payload = create_service_order_payload(base["home"]["id"], base["venue"]["id"],
                                           decedent_name="A Cee")
    data = validate_success(api.create_service_order(payload, ADMIN), 201)
    assert data["version"] == 1, f"fresh order version should be 1, got {data['version']}"


def test_get_service_order_unknown_id_returns_not_found(api):
    """PRD §2.5: "the server resolves that identifier first and rejects the
    request with the resource-specific not-found error if it does not exist —
    `ERR_FUNERAL_HOME_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_OPERATOR_NOT_FOUND`,
    `ERR_SERVICE_ORDER_NOT_FOUND`"

    Design: Corner/entities/get_service_order_not_found_returns_404
    """
    resp = api.get_service_order(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_SERVICE_ORDER_NOT_FOUND)


def test_create_order_missing_decedent_name_rejected(api):
    """PRD §2.6: "The input-shape stage (priority 5) reports `ERR_VALIDATION`
    for a missing required field or an unrecognized enum value".
    PRD §3.3: "Creation requires the `home_id`, the `venue_id` of the chosen
    venue, the `decedent_name`, and the planned broadcast window given as
    `scheduled_start` and `scheduled_end`".

    Design: Corner/entities/create_order_missing_decedent_name_returns_422
    """
    base = setup_home_and_venue()
    payload = {
        "home_id": base["home"]["id"],
        "venue_id": base["venue"]["id"],
        "scheduled_start": "2026-06-20T10:00:00Z",
        "scheduled_end": "2026-06-20T11:00:00Z",
    }
    validate_error(api.create_service_order(payload, ADMIN), ApiErrorId.ERR_VALIDATION)


def test_create_order_with_unknown_venue_rejected(api):
    """PRD §2.5: "When a path or payload references multiple identifiers, they
    are validated left to right, and the first one that does not resolve
    determines the not-found error returned."

    Design: Corner/entities/create_order_with_unknown_venue_returns_not_found
    """
    home = validate_success(
        api.create_funeral_home(create_funeral_home_payload(name="Fk Home"), ADMIN), 201
    )
    payload = create_service_order_payload(home["id"], NON_EXISTENT_UUID, decedent_name="F Kay")
    validate_error(api.create_service_order(payload, ADMIN), ApiErrorId.ERR_VENUE_NOT_FOUND)


def test_create_order_camera_count_out_of_range_rejected(api):
    """PRD §3.3: "`camera_count` (defaulting to one and constrained to between
    one and four inclusive, otherwise `ERR_INVALID_CAMERA_COUNT`)".

    Design: Corner/entities/create_order_invalid_camera_count_returns_422
    """
    base = setup_home_and_venue()
    payload = create_service_order_payload(base["home"]["id"], base["venue"]["id"],
                                           decedent_name="C Cee", camera_count=5)
    validate_error(api.create_service_order(payload, ADMIN), ApiErrorId.ERR_INVALID_CAMERA_COUNT)


def test_create_order_end_not_after_start_rejected(api):
    """PRD §3.3: "the planned broadcast window given as `scheduled_start` and
    `scheduled_end`; the end must be strictly after the start, or the request
    is rejected with `ERR_INVALID_TIME_RANGE`."

    Design: Corner/entities/create_order_invalid_time_range_returns_422
    """
    base = setup_home_and_venue()
    payload = create_service_order_payload(
        base["home"]["id"], base["venue"]["id"], decedent_name="T Ree",
        scheduled_start="2026-06-20T12:00:00Z", scheduled_end="2026-06-20T10:00:00Z",
    )
    validate_error(api.create_service_order(payload, ADMIN), ApiErrorId.ERR_INVALID_TIME_RANGE)


def test_go_live_from_draft_rejected(api):
    """PRD §3.6: "Going live advances `broadcast_status` from `SCHEDULED` to
    `LIVE`; it requires the order to be `SCHEDULED` (otherwise
    `ERR_ORDER_NOT_SCHEDULED`)".

    Design: Corner/state_machines/go_live_from_draft_returns_not_scheduled
    """
    base = setup_home_and_venue()
    order = validate_success(
        api.create_service_order(
            create_service_order_payload(base["home"]["id"], base["venue"]["id"],
                                         decedent_name="G Ell"),
            ADMIN),
        201,
    )
    resp = api.transition_service_order(order["id"], {"action": "GO_LIVE"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_SCHEDULED)


def test_cancelled_order_cannot_be_cancelled_again(api):
    """PRD §3.6: "Cancellation is available while the order is in either `DRAFT`
    or `SCHEDULED`; attempting it from any other broadcast state is rejected
    with `ERR_ORDER_NOT_CANCELLABLE`."

    Design: Corner/state_machines/cancelled_order_not_cancellable_again_terminal_lockdown
    """
    base = setup_home_and_venue()
    order = validate_success(
        api.create_service_order(
            create_service_order_payload(base["home"]["id"], base["venue"]["id"],
                                         decedent_name="L Kay"),
            ADMIN),
        201,
    )
    transition_order(order["id"], "CANCEL")
    resp = api.transition_service_order(order["id"], {"action": "CANCEL"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE)


# --- Queue A: independent status axes on one order ---------------------------
def test_recording_edit_leaves_broadcast_and_recording_distinct(api):
    """PRD §2.7: "It carries several independent status axes that advance on
    their own, and a transition on one axis never implicitly moves another".
    PRD §3.8: "Starting the edit advances `recording_status` from `RAW` to
    `EDITING`".

    Design: Difficulty/non_linear_state_machine/service_order_broadcast_and_settlement_axes_evolve_independently
    """
    base = setup_ended_axes_order(api)
    order = transition_order(base["order"]["id"], "START_EDIT")
    assert order["broadcast_status"] == "ENDED"
    assert order["recording_status"] == "EDITING"


def test_recording_edit_does_not_touch_settlement_axis(api):
    """PRD §2.7: "It carries several independent status axes that advance on
    their own, and a transition on one axis never implicitly moves another".
    PRD §3.7: "Billing runs on its own axis, independent of the broadcast."

    Design: Difficulty/non_linear_state_machine/service_order_broadcast_and_settlement_axes_evolve_independently
    """
    base = setup_ended_axes_order(api)
    order = transition_order(base["order"]["id"], "START_EDIT")
    assert order["settlement_status"] == "UNBILLED", \
        "editing the recording must not advance the settlement axis"


def setup_ended_axes_order(api):
    """A one-hour order taken LIVE then ENDED (recording auto RAW), settlement untouched."""
    return setup_ended_order(
        initial_credits=1, camera_count=1,
        scheduled_start="2026-06-06T10:00:00Z", scheduled_end="2026-06-06T11:00:00Z",
        go_live_at="2026-06-06T10:00:00Z", end_at="2026-06-06T11:00:00Z",
    )

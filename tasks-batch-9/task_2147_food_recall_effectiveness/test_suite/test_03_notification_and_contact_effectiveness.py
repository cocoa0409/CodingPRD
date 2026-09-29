"""Consignee notification: two independent dimensions, cooling-off and contact
coverage."""
from test_helpers import (
    ApiErrorId,
    assert_effectiveness_payload,
    assert_notification,
    case_with_confirmed_shipment,
    classified_case,
    create_notification_payload,
    make_coordinator_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

COORDINATOR = make_coordinator_headers("coord-1")


def test_recording_delivery_twice_is_an_invalid_notification_state(api):
    """PRD §3.5: "Recording delivery when `delivery_state` is no longer `SENT` is refused with `ERR_INVALID_NOTIFICATION_STATE`."
    PRD §3.5: "On the delivery dimension, a `FirmRecallOfficer` records an `outcome` of `DELIVERED`, advancing `SENT → DELIVERED`, or `UNDELIVERABLE`, advancing `SENT → UNDELIVERABLE`; either way `delivery_recorded_at` is stamped from the clock."

    Design: Corner/state_machines/second_delivery_call_on_a_delivered_notification_returns_invalid_notification_state
    """
    case = case_with_confirmed_shipment(clock="2026-09-01T00:00:00Z")
    notification = case.notify(case.c1_id, method="EMAIL")
    delivered = case.record_delivery(notification["id"], "DELIVERED")
    assert delivered["delivery_recorded_at"] == "2026-09-01T00:00:00.000Z"

    set_clock("2026-09-03T00:00:00Z")
    response = api.record_delivery(
        notification["id"], {"outcome": "UNDELIVERABLE"}, case.officer
    )
    validate_error(response, ApiErrorId.ERR_INVALID_NOTIFICATION_STATE.value)
    assert response.status_code == 409

    rows, _ = validate_paginated(
        api.list_consignee_notifications(case.c1_id, COORDINATOR)
    )
    assert rows[0]["delivery_state"] == "DELIVERED"
    assert rows[0]["delivery_recorded_at"] == "2026-09-01T00:00:00.000Z"
    assert case.read_consignee(case.c1_id)["escalation_level"] == 0


def test_response_on_an_undeliverable_notification_is_rejected(api):
    """PRD §3.5: "That call requires the row's `response_state` to still be `AWAITING` and its `delivery_state` to be `SENT` or `DELIVERED`, and a violation of either is `ERR_INVALID_NOTIFICATION_STATE`."
    PRD §3.5: "An `UNDELIVERABLE` outcome additionally increments the consignee's `escalation_level` by one, and it freezes the response dimension of that row at `AWAITING` forever, because the response call requires a `delivery_state` of `SENT` or `DELIVERED`."

    Design: Corner/state_machines/response_on_an_undeliverable_notification_returns_invalid_notification_state
    """
    case = case_with_confirmed_shipment()
    notification = case.notify(case.c1_id, method="CERTIFIED_MAIL")
    case.record_delivery(notification["id"], "UNDELIVERABLE")

    response = api.record_response(
        notification["id"], {"outcome": "ACKNOWLEDGED"}, case.officer
    )
    validate_error(response, ApiErrorId.ERR_INVALID_NOTIFICATION_STATE.value)
    assert response.status_code == 409

    rows, _ = validate_paginated(
        api.list_consignee_notifications(case.c1_id, COORDINATOR)
    )
    assert rows[0]["response_state"] == "AWAITING"
    assert rows[0]["counts_toward_effectiveness"] is False

    consignee = case.read_consignee(case.c1_id)
    assert consignee["escalation_level"] == 1
    assert consignee["response_state"] == "AWAITING"

    recall = case.read_recall()
    assert recall["responded_count"] == 0
    assert recall["contact_effectiveness_pct"] == 0.00


def test_cooling_off_is_reported_before_the_duplicate_active_notification(api):
    """PRD §2.6: "Checks are evaluated strictly in the ascending order listed below; the first violated rung wins and short-circuits every later rung."
    PRD §2.6: "The cooling-off buffer since the same consignee's most recent notification must have fully elapsed — otherwise `ERR_NOTIFICATION_COOLING_OFF` (409). Applies to `POST /recalls/{id}/notifications`."
    PRD §2.6: "The same consignee may not hold two notifications whose delivery dimension is still in flight — otherwise `ERR_DUPLICATE_ACTIVE_NOTIFICATION` (409). Applies to `POST /recalls/{id}/notifications`."

    Design: Corner/validations/cooling_off_outranks_duplicate_active_notification
    """
    case = case_with_confirmed_shipment(clock="2026-09-01T00:00:00Z")
    first = case.notify(case.c1_id, method="EMAIL")
    assert first["delivery_state"] == "SENT"

    set_clock("2026-09-01T01:00:00Z")
    current_version = case.consignee_version(case.c1_id)
    response = api.create_notification(
        case.recall_id,
        create_notification_payload(case.c1_id, current_version, method="EMAIL"),
        case.officer,
    )
    error = validate_error(response, ApiErrorId.ERR_NOTIFICATION_COOLING_OFF.value)
    assert response.status_code == 409
    assert error["error_id"] != ApiErrorId.ERR_DUPLICATE_ACTIVE_NOTIFICATION.value

    rows, meta = validate_paginated(
        api.list_consignee_notifications(case.c1_id, COORDINATOR)
    )
    assert meta["total_count"] == 1
    assert rows[0]["attempt_no"] == 1


def test_dispatch_is_blocked_while_a_shipment_line_is_still_declared(api):
    """PRD §3.5: "The distribution list must be complete: if any distribution record of this recall is still in `DECLARED`, the dispatch is refused with `ERR_DISTRIBUTION_LIST_INCOMPLETE`."
    PRD §3.4: "A declared line contributes nothing at all to the recall's `total_shipped_units`; only reconciliation gives a line weight."

    Design: Corner/validations/notification_before_distribution_list_is_reconciled_returns_incomplete
    """
    case = classified_case()
    consignee = case.add_consignee()
    case.confirmed_shipment(consignee["id"], 600)
    unreconciled = case.add_shipment(
        consignee["id"], 100, lot_code="L-88B", ship_date="2026-08-22T00:00:00Z"
    )

    response = api.create_notification(
        case.recall_id,
        create_notification_payload(
            consignee["id"], case.consignee_version(consignee["id"]), method="EMAIL"
        ),
        case.officer,
    )
    validate_error(response, ApiErrorId.ERR_DISTRIBUTION_LIST_INCOMPLETE.value)
    assert response.status_code == 409

    recall = case.read_recall()
    assert recall["status"] == "CLASSIFIED"
    assert recall["total_shipped_units"] == 600

    lines, _ = validate_paginated(
        api.list_distribution_records(case.recall_id, COORDINATOR)
    )
    still_declared = [row for row in lines if row["id"] == unreconciled["id"]][0]
    assert still_declared["status"] == "DECLARED"
    assert still_declared["effective_quantity"] == 0

    notifications, meta = validate_paginated(
        api.list_consignee_notifications(consignee["id"], COORDINATOR)
    )
    assert notifications == []
    assert meta["total_count"] == 0


def test_contact_effectiveness_counts_consignees_not_notification_rows(api):
    """PRD §3.7: "Take the consignees of this recall whose `tier` is at or below `sample_tier_scope`, and count those having at least one notification whose `delivery_state` is `DELIVERED` and whose `response_state` is `ACKNOWLEDGED` or `REFUSED`; that count is `responded_count`, and a consignee with three qualifying notifications still contributes exactly one."
    PRD §3.7: "Then `contact_effectiveness_pct` is 100.00 when `required_sample_size` is zero; otherwise it is the smaller of `responded_count` and `required_sample_size`, divided by `required_sample_size`, multiplied by 100, rounded half up to two decimal places."

    Design: Corner/calculations/contact_effectiveness_counts_distinct_consignees_not_notification_rows
    """
    case = classified_case(clock="2026-09-01T00:00:00Z")
    c1 = case.add_consignee("Metro Distributors", "DISTRIBUTOR")
    c2 = case.add_consignee("Harbor Grocery", "RETAILER")
    case.confirmed_shipment(c1["id"], 600)
    case.confirmed_shipment(c2["id"], 400, ship_date="2026-08-21T00:00:00Z")

    case.notify_delivered_and_acknowledged(c1["id"])
    set_clock("2026-09-02T00:00:00Z")
    case.notify_delivered_and_acknowledged(c1["id"])

    effectiveness = validate_success(api.get_effectiveness(case.recall_id, COORDINATOR))
    assert_effectiveness_payload(effectiveness)
    assert effectiveness["required_sample_size"] == 2
    assert effectiveness["responded_count"] == 1
    assert effectiveness["contact_effectiveness_pct"] == 50.00

    rows, meta = validate_paginated(
        api.list_consignee_notifications(c1["id"], COORDINATOR)
    )
    assert meta["total_count"] == 2
    for row in rows:
        assert_notification(row)
        assert row["counts_toward_effectiveness"] is True

    recall = case.read_recall()
    assert recall["status"] == "NOTIFICATION_IN_PROGRESS"
    assert recall["quantity_effectiveness_pct"] == 0.00


def test_checkpoint_ages_a_delivered_notification_at_the_window_edge(api):
    """PRD §3.8: "Second, notification aging runs: over this recall's notifications in ascending `sent_at`, ties broken by ascending `created_at`, every notification whose `delivery_state` is `DELIVERED` and whose `response_state` is still `AWAITING` and whose time since `delivery_recorded_at` has reached the response window for the recall's hazard class moves `AWAITING → NO_RESPONSE`, stamps `response_recorded_at`, increments that consignee's `escalation_level` by one, and refreshes the consignee's rolled-up `response_state`."
    PRD §3.8: "The response window is 24 hours for `CLASS_I`, 72 hours for `CLASS_II` and 168 hours — a full week — for `CLASS_III`, and the comparison is inclusive, so a notification sitting exactly at the window edge does age out."
    PRD §3.8: "Otherwise it is `WATCH` when `official_effectiveness_pct` is strictly below 60.00 *and* the recall's `status` is `RETRIEVAL_ACCOUNTING`, `EFFECTIVENESS_REVIEW` or `TERMINATION_REQUESTED`."

    Design: Corner/calculations/checkpoint_ages_a_delivered_notification_at_exactly_the_response_window_edge
    """
    case = case_with_confirmed_shipment(clock="2026-09-01T00:00:00Z")
    notification = case.notify(case.c1_id, method="EMAIL")
    case.record_delivery(notification["id"], "DELIVERED")

    set_clock("2026-09-02T00:00:00Z")
    after_checkpoint = case.checkpoint()

    rows, _ = validate_paginated(
        api.list_consignee_notifications(case.c1_id, COORDINATOR)
    )
    aged = rows[0]
    assert aged["response_state"] == "NO_RESPONSE"
    assert aged["response_recorded_at"] == "2026-09-02T00:00:00.000Z"
    assert aged["counts_toward_effectiveness"] is False

    consignee = case.read_consignee(case.c1_id)
    assert consignee["escalation_level"] == 1
    assert consignee["response_state"] == "NO_RESPONSE"

    assert after_checkpoint["responded_count"] == 0
    assert after_checkpoint["overdue_report_count"] == 0
    assert after_checkpoint["compliance_flag"] == "COMPLIANT"
    assert after_checkpoint["status"] == "NOTIFICATION_IN_PROGRESS"
    assert after_checkpoint["contact_effectiveness_pct"] == 0.00


def test_dispatch_bumps_the_consignee_version_so_the_old_one_goes_stale(api):
    """PRD §2.5: "A request to `POST /recalls/{id}/notifications` must carry `expected_consignee_version` as a required, non-optional body field holding the client's last observed `version` of the `Consignee` named in the body."
    PRD §2.5: "If that value does not equal that consignee's current `version`, the dispatch is rejected with `ERR_STALE_CONSIGNEE_VERSION` and HTTP 412."
    PRD §2.5: "A successful dispatch increments the consignee's `version` by one."
    PRD §3.5: "The consignee's `last_contact_at` is set to that `sent_at`."

    Design: Corner/cross_cutting_complexity_layers/current_expected_consignee_version_succeeds_and_bumps_the_consignee_version
    """
    case = case_with_confirmed_shipment(clock="2026-09-01T00:00:00Z")
    observed_version = case.consignee_version(case.c1_id)

    first = api.create_notification(
        case.recall_id,
        create_notification_payload(case.c1_id, observed_version, method="PHONE"),
        case.officer,
    )
    notification = validate_success(first, 201)
    assert case.consignee_version(case.c1_id) == observed_version + 1

    case.record_delivery(notification["id"], "UNDELIVERABLE")
    set_clock("2026-09-03T00:00:00Z")

    stale = api.create_notification(
        case.recall_id,
        create_notification_payload(case.c1_id, observed_version, method="PHONE"),
        case.officer,
    )
    error = validate_error(stale, ApiErrorId.ERR_STALE_CONSIGNEE_VERSION.value)
    assert stale.status_code == 412
    assert error["error_id"] != ApiErrorId.ERR_STALE_RECALL_VERSION.value
    assert error["error_id"] != ApiErrorId.ERR_NOTIFICATION_COOLING_OFF.value

    _, meta = validate_paginated(
        api.list_consignee_notifications(case.c1_id, COORDINATOR)
    )
    assert meta["total_count"] == 1

    consignee = case.read_consignee(case.c1_id)
    assert consignee["escalation_level"] == 1
    assert consignee["last_contact_at"] == "2026-09-01T00:00:00.000Z"


class TestNotificationParallelDimensions:
    """delivery_state and response_state evolve independently on one row."""

    def test_response_can_be_recorded_while_delivery_is_still_sent(self, api):
        """PRD §3.5: "The two state dimensions on a notification evolve independently and neither waits for the other."
        PRD §3.5: "A notification's `counts_toward_effectiveness` is true when, and only when, its `delivery_state` is `DELIVERED` and its `response_state` is either `ACKNOWLEDGED` or `REFUSED` — a refusal is a response, and it counts exactly as much as an acknowledgement."

        Design: Difficulty/non_linear_state_machine/notification_parallel_dimensions_advance_independently
        """
        case = case_with_confirmed_shipment(clock="2026-09-01T00:00:00Z")
        notification = case.notify(case.c1_id, method="EMAIL")

        after_response = case.record_response(
            notification["id"], "ACKNOWLEDGED",
            response_note="Stock pulled from shelves.",
        )
        assert after_response["delivery_state"] == "SENT"
        assert after_response["counts_toward_effectiveness"] is False

        after_delivery = case.record_delivery(notification["id"], "DELIVERED")
        assert after_delivery["response_state"] == "ACKNOWLEDGED"
        assert after_delivery["counts_toward_effectiveness"] is True
        assert_notification(after_delivery)

    def test_completing_both_dimensions_advances_the_recall(self, api):
        """PRD §3.5: "Whenever the recall is in `NOTIFICATION_IN_PROGRESS` and its `required_sample_size` is greater than zero and its `responded_count` has reached at least that size, the recall automatically advances `NOTIFICATION_IN_PROGRESS → RETRIEVAL_ACCOUNTING`; that check is evaluated at the end of a delivery recording, at the end of a response recording, and during a checkpoint."
        PRD §3.7: "Then `contact_effectiveness_pct` is 100.00 when `required_sample_size` is zero; otherwise it is the smaller of `responded_count` and `required_sample_size`, divided by `required_sample_size`, multiplied by 100, rounded half up to two decimal places."

        Design: Difficulty/non_linear_state_machine/notification_parallel_dimensions_advance_independently
        """
        case = case_with_confirmed_shipment(clock="2026-09-01T00:00:00Z")
        notification = case.notify(case.c1_id, method="EMAIL")
        case.record_response(notification["id"], "ACKNOWLEDGED")
        case.record_delivery(notification["id"], "DELIVERED")

        rows, _ = validate_paginated(
            api.list_consignee_notifications(case.c1_id, COORDINATOR)
        )
        assert rows[0]["delivery_state"] == "DELIVERED"
        assert rows[0]["response_state"] == "ACKNOWLEDGED"

        recall = case.read_recall()
        assert recall["responded_count"] == 1
        assert recall["contact_effectiveness_pct"] == 100.00
        assert recall["status"] == "RETRIEVAL_ACCOUNTING"


class TestCoolingOffBuffer:
    """The buffer is the larger of the two methods' buffers, and its edge is
    admitted."""

    def test_dispatch_one_hour_short_of_the_buffer_is_refused(self, api):
        """PRD §3.5: "The cooling-off buffer must have elapsed: the buffer is 24 hours for `EMAIL`, 12 hours for `PHONE` and 72 hours for `CERTIFIED_MAIL`, and the buffer that applies is the larger of the buffer for the method now being used and the buffer for the method of this consignee's most recent prior notification — the one with the greatest `sent_at`, ties broken by the greatest `created_at`, considered across all of that consignee's notifications including undeliverable ones."
        PRD §3.5: "If the time elapsed since that prior notification's `sent_at` is strictly less than the applicable buffer, the dispatch is refused with `ERR_NOTIFICATION_COOLING_OFF`; a dispatch exactly at the buffer edge is allowed."

        Design: Difficulty/resource_temporal_overlap/notification_cooling_off_uses_max_method_buffer_and_admits_the_exact_edge
        """
        case = case_with_confirmed_shipment(clock="2026-09-01T00:00:00Z")
        first = case.notify(case.c1_id, method="PHONE")
        case.record_delivery(first["id"], "UNDELIVERABLE")

        set_clock("2026-09-01T23:00:00Z")
        response = api.create_notification(
            case.recall_id,
            create_notification_payload(
                case.c1_id, case.consignee_version(case.c1_id), method="EMAIL"
            ),
            case.officer,
        )
        validate_error(response, ApiErrorId.ERR_NOTIFICATION_COOLING_OFF.value)
        assert response.status_code == 409

        _, meta = validate_paginated(
            api.list_consignee_notifications(case.c1_id, COORDINATOR)
        )
        assert meta["total_count"] == 1

    def test_dispatch_exactly_at_the_buffer_edge_is_accepted(self, api):
        """PRD §3.5: "If the time elapsed since that prior notification's `sent_at` is strictly less than the applicable buffer, the dispatch is refused with `ERR_NOTIFICATION_COOLING_OFF`; a dispatch exactly at the buffer edge is allowed."
        PRD §3.5: "A dispatched notification records `attempt_no` as one more than the count of pre-existing notifications for the same consignee, stamps `sent_at` from the logical clock, and starts life in `delivery_state` `SENT` and `response_state` `AWAITING`, with `delivery_recorded_at`, `response_recorded_at` and `response_note` all null and `counts_toward_effectiveness` false."

        Design: Difficulty/resource_temporal_overlap/notification_cooling_off_uses_max_method_buffer_and_admits_the_exact_edge
        """
        case = case_with_confirmed_shipment(clock="2026-09-01T00:00:00Z")
        first = case.notify(case.c1_id, method="PHONE")
        case.record_delivery(first["id"], "UNDELIVERABLE")

        set_clock("2026-09-02T00:00:00Z")
        response = api.create_notification(
            case.recall_id,
            create_notification_payload(
                case.c1_id, case.consignee_version(case.c1_id), method="EMAIL"
            ),
            case.officer,
        )
        second = validate_success(response, 201)
        assert second["attempt_no"] == 2
        assert second["sent_at"] == "2026-09-02T00:00:00.000Z"
        assert second["delivery_state"] == "SENT"
        assert second["response_state"] == "AWAITING"

        assert case.read_consignee(case.c1_id)["escalation_level"] == 1
        _, meta = validate_paginated(
            api.list_consignee_notifications(case.c1_id, COORDINATOR)
        )
        assert meta["total_count"] == 2

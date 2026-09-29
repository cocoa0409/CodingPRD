"""Initial states, valid transitions, repeated transitions and terminal lockdowns."""

import pytest

from test_helpers import (
    ADMIN,
    COUNSELOR,
    COUNSELOR_USER_ID,
    ApiErrorId,
    amend_order,
    amend_order_payload,
    api_client,
    award_shipment,
    cancel_shipment_payload,
    create_capacity_block,
    create_service_member,
    create_order,
    create_counseling_session,
    create_shipment_payload,
    create_tsp,
    complete_counseling_payload,
    authorize_entitlement_payload,
    deliver_shipment,
    dispatch_notification_payload,
    dispute_weight_payload,
    entitlement_version,
    find_notification,
    get_success_data,
    pack_shipment,
    pickup_shipment,
    read_entitlement,
    read_shipment,
    record_actual_weight,
    record_actual_weight_payload,
    reweigh_payload,
    set_clock,
    setup_authorized_entitlement,
    setup_booked_shipment,
    setup_delivered_shipment,
    setup_packed_shipment,
    setup_weighed_shipment,
    survey_shipment,
    validate_error,
    validate_paginated,
    validate_success,
)

WEIGH_DATE = "2026-08-17T00:00:00Z"
DISPUTE_DEADLINE = "2026-10-01T00:00:00Z"
DAY_AFTER_DEADLINE = "2026-10-02T00:00:00Z"


def _entitlement_and_provider():
    """An authorized E6 ledger and one onboarded provider, nothing booked yet."""
    scenario = setup_authorized_entitlement()
    scenario["tsp"] = create_tsp()
    return scenario


def _book(scenario):
    return api_client.create_shipment(
        create_shipment_payload(
            scenario["order"]["id"],
            scenario["entitlement"]["id"],
            scenario["tsp"]["id"],
            entitlement_version(scenario["entitlement"]["id"]),
        ),
        COUNSELOR,
    )


def _scheduled_session():
    """A member, orders and one booked counseling appointment."""
    set_clock()
    member = create_service_member()
    order = create_order(member["id"])
    return order, create_counseling_session(order["id"], session_type="IN_PERSON")


def _complete(session_id):
    return api_client.complete_counseling_session(
        session_id, complete_counseling_payload(), COUNSELOR
    )


def _delivered_move_with_one_amendment():
    """A delivered 4,700 pound move whose orders were amended once after booking."""
    scenario = setup_booked_shipment()
    amend_order(
        scenario["order"]["id"],
        amendment_reason="REPORT DATE SLIPPED",
        report_no_later_than_date_override="2026-10-15T00:00:00Z",
    )
    scenario["shipment"] = survey_shipment(scenario)
    scenario["block"] = create_capacity_block(scenario["tsp"]["id"])
    award_shipment(scenario["block"]["id"], scenario["shipment"]["id"])
    pack_shipment(scenario)
    record_actual_weight(scenario, 6200, 1500, weigh_date=WEIGH_DATE)
    pickup_shipment(scenario)
    scenario["shipment"] = deliver_shipment(scenario)
    return scenario


class TestInitialAndValidTransitions:
    """What a freshly created record looks like before anything acts on it."""

    def test_a_new_booking_starts_awarded_pending_and_unpriced(self):
        """The booking is peak-season but not short notice, so the spread runs 15 to 24 August.

        "A new shipment enters the world with `movement_status` `AWARDED`,
        `weight_recon_status` `PENDING`, `capacity_block_id` null, `billable_weight_lbs` 0,
        `billable_basis` `NONE`, `pro_gear_excluded_lbs` 0, `reweigh_required` false"

        "a short-notice booking receives a spread of zero days before and two days after the
        requested pickup date; failing that, a peak-season booking receives two days before
        and seven days after"

        Design: Corner/state_machines/shipment_starts_in_awarded_and_pending_with_no_billable_basis
        """
        scenario = _entitlement_and_provider()

        shipment = validate_success(_book(scenario), 201)
        assert shipment["movement_status"] == "AWARDED"
        assert shipment["weight_recon_status"] == "PENDING"
        assert shipment["billable_basis"] == "NONE"
        assert shipment["billable_weight_lbs"] == 0
        assert shipment["pro_gear_excluded_lbs"] == 0
        assert shipment["capacity_block_id"] is None
        assert shipment["survey_date"] is None
        assert shipment["estimated_gross_lbs"] is None
        assert shipment["booked_at"] == "2026-08-03T00:00:00Z"
        assert shipment["is_short_notice"] is False
        assert shipment["peak_season"] is True
        assert shipment["spread_start_date"] == "2026-08-15T00:00:00Z"
        assert shipment["spread_end_date"] == "2026-08-24T00:00:00Z"
        assert shipment["transit_days_allowed"] == 6
        assert shipment["required_delivery_by"] is None

        assert read_entitlement(scenario["entitlement"]["id"])[
            "charged_billable_weight_lbs"
        ] == 0

    def test_completing_counseling_creates_the_draft_entitlement(self):
        """An E6 with two dependents and a spouse present earns 11,000 pounds and 2,500 of gear.

        "One `EntitlementAuthorization` is created in `status` `DRAFT`, carrying `order_id`
        copied from the session's orders and `counseling_session_id` naming the session that
        produced it, with `admin_weight_bump_lbs` initialised to 0,
        `rank_code_at_authorization` snapshotted from the member's `rank_code`"

        "`pro_gear_member_allowance_lbs` is always 2,000 pounds."

        Design: Corner/state_machines/counseling_completion_creates_draft_entitlement_with_pro_gear_allowances
        """
        order, session = _scheduled_session()

        completed = validate_success(_complete(session["id"]), 200)
        assert completed["status"] == "COMPLETED"
        assert completed["entitlement_briefed"] is True

        rows, meta = validate_paginated(
            api_client.list_order_entitlements(order["id"], COUNSELOR)
        )
        assert meta["total_count"] == 1

        entitlement = rows[0]
        assert entitlement["status"] == "DRAFT"
        assert entitlement["order_id"] == order["id"]
        assert entitlement["counseling_session_id"] == session["id"]
        assert entitlement["rank_code_at_authorization"] == "E6"
        assert entitlement["dependent_status_effective"] == "WITH_DEPENDENTS"
        assert entitlement["base_weight_allowance_lbs"] == 11000
        assert entitlement["total_billable_cap_lbs"] == 11000
        assert entitlement["pro_gear_member_allowance_lbs"] == 2000
        assert entitlement["pro_gear_spouse_allowance_lbs"] == 500
        assert entitlement["admin_weight_bump_lbs"] == 0
        assert entitlement["charged_billable_weight_lbs"] == 0
        assert entitlement["gross_excess_cost_usd"] == pytest.approx(0.00, abs=0.01)

    def test_the_dispute_window_is_open_on_its_forty_fifth_day(self):
        """A dispute lodged exactly 45 days after the weighing is heard, one day later is not.

        "Two conditions apply: the status must be `ACTUAL_RECORDED`, and the logical clock
        must be no later than `weigh_date` advanced by 45 days — a dispute raised beyond that
        six-and-a-half-week window is refused with `ERR_WEIGHT_DISPUTE_WINDOW_EXPIRED`."

        "A dispute forces `reweigh_required` to true and changes no ledger figure whatsoever:
        `DISPUTED` sits inside the inclusion set, so the disputed pounds continue to be
        charged while the matter is resolved."

        Design: Corner/state_machines/weight_dispute_window_closes_forty_five_days_after_the_weigh_date
        """
        scenario = setup_weighed_shipment(weigh_date=WEIGH_DATE)
        shipment_id = scenario["shipment"]["id"]

        set_clock(DISPUTE_DEADLINE)
        disputed = validate_success(
            api_client.dispute_weight(
                shipment_id,
                dispute_weight_payload(dispute_reason="SCALE TICKET TARE LOOKS WRONG"),
                COUNSELOR,
            ),
            200,
        )
        assert disputed["weight_recon_status"] == "DISPUTED"
        assert disputed["reweigh_required"] is True
        assert disputed["movement_status"] == "PACKED"
        assert read_entitlement(scenario["entitlement"]["id"])[
            "charged_billable_weight_lbs"
        ] == 4700

        reweighed = validate_success(
            api_client.reweigh_shipment(
                shipment_id,
                reweigh_payload(6200, 1500, WEIGH_DATE),
                scenario["tsp_headers"],
            ),
            200,
        )
        assert reweighed["weight_recon_status"] == "ACTUAL_RECORDED"
        assert reweighed["billable_weight_lbs"] == 4700
        assert reweighed["billable_basis"] == "ACTUAL"
        assert reweighed["movement_status"] == "PACKED"

        set_clock(DAY_AFTER_DEADLINE)
        validate_error(
            api_client.dispute_weight(
                shipment_id,
                dispute_weight_payload(dispute_reason="SECOND THOUGHTS"),
                COUNSELOR,
            ),
            ApiErrorId.ERR_WEIGHT_DISPUTE_WINDOW_EXPIRED.value,
            422,
        )
        assert read_shipment(shipment_id)["weight_recon_status"] == "ACTUAL_RECORDED"

    def test_reconciling_closes_the_ledger_and_the_orders(self):
        """Freezing the last shipment's pounds bubbles closure up to the orders themselves.

        "Reconciliation freezes a shipment's contribution and is a counselor or
        program-office action moving `weight_recon_status` `ACTUAL_RECORDED → RECONCILED`,
        the terminal state of the weight dimension."

        "A `CLOSED` entitlement accepts no further shipments — an attempt draws
        `ERR_ENTITLEMENT_NOT_AUTHORIZED` — and its closure in turn bubbles the owning orders
        from `ISSUED` or `AMENDED` to `CLOSED`, after which no amendment is accepted and
        `ERR_INVALID_ORDER_STATE` is returned."

        Design: Corner/state_machines/reconcile_weight_closes_the_entitlement_and_freezes_the_order
        """
        scenario = _delivered_move_with_one_amendment()

        reconciled = validate_success(
            api_client.reconcile_weight(
                scenario["shipment"]["id"],
                {"reconcile_note": "LEDGER AGREED WITH THE MEMBER"},
                COUNSELOR,
            ),
            200,
        )
        assert reconciled["weight_recon_status"] == "RECONCILED"
        assert reconciled["movement_status"] == "DELIVERED"

        entitlement = read_entitlement(scenario["entitlement"]["id"])
        assert entitlement["status"] == "CLOSED"
        assert entitlement["charged_billable_weight_lbs"] == 4700

        order = get_success_data(
            api_client.get_order(scenario["order"]["id"], COUNSELOR)
        )
        assert order["status"] == "CLOSED"
        assert order["amendment_count"] == 1

        validate_error(
            api_client.amend_order(
                scenario["order"]["id"],
                amend_order_payload(
                    amendment_reason="LATE CHANGE", dependents_count_override=3
                ),
                COUNSELOR,
            ),
            ApiErrorId.ERR_INVALID_ORDER_STATE.value,
            409,
        )
        assert (
            get_success_data(api_client.get_order(scenario["order"]["id"], COUNSELOR))[
                "amendment_count"
            ]
            == 1
        )

        validate_error(
            api_client.create_shipment(
                create_shipment_payload(
                    scenario["order"]["id"],
                    scenario["entitlement"]["id"],
                    scenario["tsp"]["id"],
                    entitlement["version"],
                    shipment_code="SHP-C02",
                ),
                COUNSELOR,
            ),
            ApiErrorId.ERR_ENTITLEMENT_NOT_AUTHORIZED.value,
            409,
        )


class TestRepeatedTransitionsAreRefused:
    """A transition already taken cannot be taken again, and nothing moves when it is tried."""

    def test_a_second_counseling_completion_names_the_session_state(self):
        """The already-completed session outranks the duplicate-entitlement complaint.

        "Completing the session is exclusive to a `MoveCounselor` and moves `status` from
        `SCHEDULED` to `COMPLETED`; attempting it on a session that is already `COMPLETED`
        draws `ERR_INVALID_COUNSELING_STATE`."

        Design: Corner/state_machines/second_counseling_completion_is_refused_as_invalid_counseling_state
        """
        order, session = _scheduled_session()
        _complete(session["id"])

        validate_error(
            _complete(session["id"]),
            ApiErrorId.ERR_INVALID_COUNSELING_STATE.value,
            409,
        )

        _, meta = validate_paginated(
            api_client.list_order_entitlements(order["id"], COUNSELOR)
        )
        assert meta["total_count"] == 1

        stored = get_success_data(
            api_client.get_counseling_session(session["id"], COUNSELOR)
        )
        assert stored["status"] == "COMPLETED"
        assert stored["completed_at"] == "2026-08-03T00:00:00Z"

    def test_a_second_authorization_cannot_raise_the_cap(self):
        """A 500 pound bump arriving after authorization is refused outright.

        "Authorizing the entitlement moves it `DRAFT → AUTHORIZED` and is available to a
        counselor or administrator; attempting it on an entitlement that is not `DRAFT` draws
        `ERR_INVALID_ENTITLEMENT_STATE`."

        Design: Corner/state_machines/second_authorize_is_refused_as_invalid_entitlement_state
        """
        scenario = setup_authorized_entitlement()
        entitlement_id = scenario["entitlement"]["id"]
        version_before = scenario["entitlement"]["version"]

        validate_error(
            api_client.authorize_entitlement(
                entitlement_id,
                authorize_entitlement_payload(admin_weight_bump_lbs=500),
                ADMIN,
            ),
            ApiErrorId.ERR_INVALID_ENTITLEMENT_STATE.value,
            409,
        )

        stored = read_entitlement(entitlement_id)
        assert stored["status"] == "AUTHORIZED"
        assert stored["admin_weight_bump_lbs"] == 0
        assert stored["total_billable_cap_lbs"] == 11000
        assert stored["version"] == version_before
        assert stored["authorized_by_user_id"] == COUNSELOR_USER_ID

    def test_a_dispatched_obligation_cannot_be_dispatched_again(self):
        """The email goes out on time; the follow-up text message is refused.

        "An obligation already `SENT` or `LATE` cannot be dispatched again and draws
        `ERR_INVALID_NOTIFICATION_STATE`. Dispatch stamps `sent_at` from the logical clock,
        stores the channel, and branches on a boundary: when the clock reads at or before
        `due_by` the obligation moves `PENDING → SENT` and `hours_late` stays 0.00"

        "`due_by` is `trigger_event_at` advanced by `sla_hours` hours."

        Design: Corner/state_machines/notification_dispatch_is_not_repeatable
        """
        scenario = setup_packed_shipment()
        obligation = find_notification(
            scenario["shipment"]["id"], "PACK_DATE_CONFIRMED"
        )
        assert obligation["status"] == "PENDING"
        assert obligation["sla_hours"] == 72
        assert obligation["due_by"] == "2026-08-06T00:00:00Z"

        sent = validate_success(
            api_client.dispatch_notification(
                obligation["id"], dispatch_notification_payload("EMAIL"), COUNSELOR
            ),
            200,
        )
        assert sent["status"] == "SENT"
        assert sent["sent_at"] == "2026-08-03T00:00:00Z"
        assert sent["channel"] == "EMAIL"
        assert sent["hours_late"] == pytest.approx(0.00, abs=0.01)

        validate_error(
            api_client.dispatch_notification(
                obligation["id"],
                dispatch_notification_payload("SMS"),
                scenario["tsp_headers"],
            ),
            ApiErrorId.ERR_INVALID_NOTIFICATION_STATE.value,
            409,
        )

        final = get_success_data(
            api_client.get_notification(obligation["id"], COUNSELOR)
        )
        assert final["channel"] == "EMAIL"
        assert final["status"] == "SENT"


class TestOutOfOrderAndTerminalStates:
    """Transitions attempted too early, and one attempted after the goods are gone."""

    def test_the_scale_cannot_be_read_before_the_survey(self):
        """A pending shipment has no estimate to replace, so the weight is refused.

        "The shipment's `weight_recon_status` must be `ESTIMATED`, or
        `ERR_INVALID_WEIGHT_RECON_STATE` applies, and its `movement_status` must be one of
        `SURVEYED`, `PACKED`, `PICKED_UP` or `IN_SIT`"

        Design: Corner/state_machines/record_actual_weight_before_survey_is_refused
        """
        scenario = setup_booked_shipment()

        validate_error(
            api_client.record_actual_weight(
                scenario["shipment"]["id"],
                record_actual_weight_payload(6200, 1500, WEIGH_DATE),
                scenario["tsp_headers"],
            ),
            ApiErrorId.ERR_INVALID_WEIGHT_RECON_STATE.value,
            409,
        )

        shipment = read_shipment(scenario["shipment"]["id"])
        assert shipment["weight_recon_status"] == "PENDING"
        assert shipment["actual_gross_lbs"] is None
        assert shipment["net_actual_lbs"] is None
        assert shipment["billable_basis"] == "NONE"
        assert shipment["billable_weight_lbs"] == 0
        assert read_entitlement(scenario["entitlement"]["id"])[
            "charged_billable_weight_lbs"
        ] == 0

    def test_a_delivered_shipment_can_no_longer_be_cancelled(self):
        """The household is already in the new quarters, so the cancellation is refused.

        "Cancellation is available to the member, a counselor or the program office, and only
        before the goods are gone: `movement_status` may be `AWARDED`, `ON_HOLD`, `SURVEYED`
        or `PACKED`, and any other movement state draws
        `ERR_INVALID_SHIPMENT_MOVEMENT_STATE`."

        "the system maintains it as the count of that member's shipments whose
        `movement_status` is neither `DELIVERED` nor `CANCELLED`"

        Design: Corner/state_machines/delivered_shipment_cannot_be_cancelled
        """
        scenario = setup_delivered_shipment(weigh_date=WEIGH_DATE)

        validate_error(
            api_client.cancel_shipment(
                scenario["shipment"]["id"],
                cancel_shipment_payload(cancel_reason="MEMBER CHANGED PLANS"),
                COUNSELOR,
            ),
            ApiErrorId.ERR_INVALID_SHIPMENT_MOVEMENT_STATE.value,
            409,
        )

        shipment = read_shipment(scenario["shipment"]["id"])
        assert shipment["movement_status"] == "DELIVERED"
        assert shipment["cancel_reason"] is None
        assert shipment["delivery_date"] == "2026-08-20T00:00:00Z"
        assert shipment["required_delivery_by"] == "2026-08-23T00:00:00Z"

        assert read_entitlement(scenario["entitlement"]["id"])[
            "charged_billable_weight_lbs"
        ] == 4700
        member = get_success_data(
            api_client.get_service_member(scenario["member"]["id"], COUNSELOR)
        )
        assert member["active_shipment_count"] == 0

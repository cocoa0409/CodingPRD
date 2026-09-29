"""Transitions that are blocked by state living on a different aggregate.

In both pairs the row being written is perfectly valid throughout; only the
neighbouring aggregate moves, and that alone decides whether the call succeeds.
"""

import pytest

from test_helpers import (
    OPS_HEADERS,
    build_courier,
    build_network,
    build_patient,
    build_order,
    build_queued_delivery,
    build_window,
    factories,
    read_courier,
    read_delivery,
    read_grant,
    read_order,
    read_window,
    set_clock,
    utc_ts,
    validate_error,
    validate_paginated,
    validate_success,
)

SINGLE_LINE_ORDER = {
    "rx_line_count": 1,
    "cold_chain_required": False,
    "controlled_schedule": "NONE",
    "total_rx_value_cents": 1000,
}


@pytest.fixture
def suspended_sole_courier(api):
    """A queued Z1 bag and the network's only courier, suspended by ops.

    Nothing about the delivery differs between the failing and succeeding calls;
    only the courier's status does.
    """
    scn = build_queued_delivery(api, order_kwargs=SINGLE_LINE_ORDER)
    courier = build_courier(api)
    validate_success(
        api.set_courier_status(
            courier["id"], factories.courier_status_payload("SUSPENDED"), headers=OPS_HEADERS
        )
    )
    set_clock(api, utc_ts(3, 13, 45))
    scn.courier = courier
    return scn


class TestDispatchBlockedByCourierSuspension:
    """"Suspension from `AVAILABLE` removes the courier from the selector
    candidate set for all future dispatches"
    """

    def test_naming_a_suspended_courier_is_rejected_by_name(
        self, api, suspended_sole_courier
    ):
        """The override path complains about the courier it was handed.

        "it must not be `SUSPENDED` (`ERR_COURIER_SUSPENDED`) or `OFFLINE`
        (`ERR_COURIER_UNAVAILABLE`); and the buffered-interval rule still
        applies."

        Design: Difficulty/cross_entity_state_dependency/delivery_dispatch_blocked_by_courier_suspension
        """
        scn = suspended_sole_courier
        response = api.dispatch_delivery(
            scn.delivery["id"],
            headers=OPS_HEADERS,
            payload=factories.dispatch_payload(scn.courier["id"]),
        )
        validate_error(response, "ERR_COURIER_SUSPENDED", 409)

    def test_the_selector_cannot_even_see_a_suspended_courier(
        self, api, suspended_sole_courier
    ):
        """The same fact reaches the selector as an empty pool, not an objection.

        "These four certification checks are unreachable through the selector,
        which filters rather than complains."

        Design: Difficulty/cross_entity_state_dependency/delivery_dispatch_blocked_by_courier_suspension
        """
        scn = suspended_sole_courier
        response = api.dispatch_delivery(
            scn.delivery["id"], headers=OPS_HEADERS, payload=factories.dispatch_payload()
        )
        validate_error(response, "ERR_NO_ELIGIBLE_COURIER", 409)

        delivery = read_delivery(api, scn.delivery["id"])
        assert delivery["custody_status"] == "QUEUED"
        assert delivery["courier_id"] is None
        _rows, meta = validate_paginated(
            api.list_courier_assignments(OPS_HEADERS, delivery_id=scn.delivery["id"])
        )
        assert meta["total_count"] == 0

        courier = read_courier(api, scn.courier["id"])
        assert courier["status"] == "SUSPENDED"
        assert courier["active_delivery_count"] == 0

    def test_lifting_the_suspension_makes_the_identical_dispatch_succeed(
        self, api, suspended_sole_courier
    ):
        """The delivery row was never the problem: reinstate and retry.

        "Only `NetworkOps` may lift a suspension, by submitting `AVAILABLE` for a
        courier whose `status` is `SUSPENDED`; a `Courier` attempting to clear its
        own `SUSPENDED` status is rejected with `ERR_INVALID_COURIER_STATE`."

        Design: Difficulty/cross_entity_state_dependency/delivery_dispatch_blocked_by_courier_suspension
        """
        scn = suspended_sole_courier
        validate_error(
            api.dispatch_delivery(
                scn.delivery["id"],
                headers=OPS_HEADERS,
                payload=factories.dispatch_payload(scn.courier["id"]),
            ),
            "ERR_COURIER_SUSPENDED",
            409,
        )

        reinstated = validate_success(
            api.set_courier_status(
                scn.courier["id"],
                factories.courier_status_payload("AVAILABLE"),
                headers=OPS_HEADERS,
            )
        )
        assert reinstated["status"] == "AVAILABLE"

        assignment = validate_success(
            api.dispatch_delivery(
                scn.delivery["id"],
                headers=OPS_HEADERS,
                payload=factories.dispatch_payload(scn.courier["id"]),
            ),
            201,
        )
        assert assignment["status"] == "OFFERED"
        assert assignment["courier_id"] == scn.courier["id"]


@pytest.fixture
def order_for_a_patient_who_revoked_consent(api):
    """An intake order for Sam Iyer, whose HIPAA consent is revoked.

    A second recipient registered with consent granted shows that the site and
    the order shape are otherwise beyond reproach.
    """
    net = build_network(
        api,
        patient={
            "full_name": "Sam Iyer",
            "date_of_birth": "1961-02-08",
            "phone_last4": "7781",
            "address_line": "5 Quince Ct",
            "zone_code": "Z1",
            "hipaa_consent_status": "REVOKED",
        },
    )
    consenting = build_patient(api, net.pharmacy["id"])
    order = build_order(api, net, **SINGLE_LINE_ORDER)
    window = build_window(api, net.zone["id"], capacity_slots=2)
    return net, consenting, order, window


class TestOrderReleaseBlockedByRevokedConsent:
    """"flipping it to `REVOKED` immediately blocks release of that patient's
    orders and reservation of new deliveries with `ERR_CONSENT_NOT_GRANTED`"
    """

    def test_release_is_refused_while_the_recipient_withholds_consent(
        self, api, order_for_a_patient_who_revoked_consent
    ):
        """The order cannot advance on the state of another aggregate.

        "`Patient.hipaa_consent_status` is `GRANTED` — otherwise
        `ERR_CONSENT_NOT_GRANTED`. Guards releasing an order to ready and
        reserving a delivery; an order cannot advance on the state of a different
        aggregate without this being true."

        Design: Difficulty/cross_entity_state_dependency/order_mark_ready_blocked_by_revoked_patient_consent
        """
        net, _consenting, order, _window = order_for_a_patient_who_revoked_consent
        response = api.mark_order_ready(order["id"], headers=net.pharmacy_headers)
        validate_error(response, "ERR_CONSENT_NOT_GRANTED", 409)
        assert read_order(api, order["id"])["status"] == "INTAKE"

    def test_granting_consent_lets_the_identical_release_through(
        self, api, order_for_a_patient_who_revoked_consent
    ):
        """Same request body, different state on the recipient.

        "Either the patient themselves or a pharmacy operator may afterwards
        submit a fresh `hipaa_consent_status`, which is the switch that authorises
        third-party courier disclosure"

        Design: Difficulty/cross_entity_state_dependency/order_mark_ready_blocked_by_revoked_patient_consent
        """
        net, _consenting, order, _window = order_for_a_patient_who_revoked_consent
        validate_error(
            api.mark_order_ready(order["id"], headers=net.pharmacy_headers),
            "ERR_CONSENT_NOT_GRANTED",
            409,
        )

        patient = validate_success(
            api.record_patient_consent(
                net.patient["id"],
                factories.consent_payload("GRANTED"),
                headers=net.patient_headers,
            )
        )
        assert patient["hipaa_consent_status"] == "GRANTED"

        released = validate_success(
            api.mark_order_ready(order["id"], headers=net.pharmacy_headers)
        )
        assert released["status"] == "READY"

    def test_a_revocation_after_release_still_stops_the_reservation(
        self, api, order_for_a_patient_who_revoked_consent
    ):
        """The gate is re-evaluated at reservation, so a mid-flight flip bites.

        "The order must be `READY`, or the request is `ERR_ORDER_NOT_READY`; the
        recipient's consent must still be `GRANTED`; the window must not be
        `CLOSED` or `FULL` by status flag, or the request is
        `ERR_WINDOW_CLOSED`"

        Design: Difficulty/cross_entity_state_dependency/order_mark_ready_blocked_by_revoked_patient_consent
        """
        net, _consenting, order, window = order_for_a_patient_who_revoked_consent
        validate_success(
            api.record_patient_consent(
                net.patient["id"],
                factories.consent_payload("GRANTED"),
                headers=net.patient_headers,
            )
        )
        validate_success(api.mark_order_ready(order["id"], headers=net.pharmacy_headers))

        revoked = validate_success(
            api.record_patient_consent(
                net.patient["id"],
                factories.consent_payload("REVOKED"),
                headers=net.patient_headers,
            )
        )
        assert revoked["hipaa_consent_status"] == "REVOKED"

        response = api.create_delivery(
            factories.delivery_payload(
                order["id"], window["id"], read_window(api, window["id"])["version"]
            ),
            headers=net.pharmacy_headers,
        )
        validate_error(response, "ERR_CONSENT_NOT_GRANTED", 409)

        assert read_window(api, window["id"])["reserved_slots"] == 0
        _rows, meta = validate_paginated(
            api.list_deliveries(OPS_HEADERS, order_id=order["id"])
        )
        assert meta["total_count"] == 0
        assert read_grant(api, net.grant["id"])["committed_cents"] == 0

"""Validation precedence: requests that break two rules at once.

Each scenario is arranged so two independent checks would both reject the call.
The higher-precedence identifier must win, and the paired test proves the
lower-precedence check is still live once the higher one is satisfied.
"""

from test_helpers import (
    ApiErrorId,
    CO_ALPHA,
    CO_BRAVO,
    WORKING_TUESDAY_10AM,
    apply_substitution_payload,
    create_order_payload,
    deactivate_product,
    make_compliance_headers,
    set_clock,
    setup_open_hold_with_open_dispute,
    setup_substitution_candidates,
    setup_verified_prescription,
    validate_error,
    validate_paginated,
    validate_success,
)

EXPIRY_DATE = "2026-09-10"
CLOCK_AFTER_EXPIRY = "2026-09-11T09:00:00Z"


def _single_box_prescription_expiring_soon():
    """A verified prescription authorising one box in total and expiring
    2026-09-10, with the clock still inside its validity interval."""
    return setup_verified_prescription(
        clock=WORKING_TUESDAY_10AM,
        prescription_overrides={
            "expiry_date": EXPIRY_DATE,
            "boxes_authorized_total": 1,
        },
    )


def _four_box_order_payload(scenario):
    return create_order_payload(
        scenario["customer"]["id"],
        scenario["prescription"]["id"],
        scenario["product"]["id"],
        boxes_od=2,
        boxes_os=2,
    )


class TestExpiredPrescriptionOutranksBoxAuthorization:
    """A lapsed prescription and an over-drawn box ledger both reject the same
    order; expiry is the earlier check, and both errors carry HTTP 409, so only
    the identifier separates the two evaluation orders."""

    def test_expired_prescription_outranks_box_authorization_on_order_create(
        self, api, customer_headers_for
    ):
        """PRD §2.10: "The first check that fails determines the response, and no
        later check is evaluated."
        PRD §2.10 item 12: "Prescription not expired, on order placement, on the
        auto-reorder run and on prescription submit → `ERR_PRESCRIPTION_EXPIRED`
        (409)."
        PRD §2.10 item 37: "Box authorisation not exceeded, on order placement and
        on the auto-reorder run → `ERR_BOX_AUTHORIZATION_EXCEEDED` (409)."
        PRD §3.5: "A prescription whose `expiry_date` is at or before the current
        logical date, or whose `status` is already `EXPIRED`, cannot be ordered
        against at all and yields `ERR_PRESCRIPTION_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/expired_prescription_outranks_box_authorization_on_order_create
        """
        scenario = _single_box_prescription_expiring_soon()
        set_clock(CLOCK_AFTER_EXPIRY)

        response = api.create_order(
            _four_box_order_payload(scenario),
            customer_headers_for(scenario["customer"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_PRESCRIPTION_EXPIRED)

        prescription = validate_success(
            api.get_prescription(
                scenario["prescription"]["id"],
                customer_headers_for(scenario["customer"]["id"]),
            )
        )
        assert prescription["boxes_consumed"] == 0

        _, meta = validate_paginated(
            api.list_orders(
                customer_headers_for(scenario["customer"]["id"]),
                params={"customer_id": scenario["customer"]["id"]},
            )
        )
        assert meta["total_count"] == 0

    def test_box_authorization_still_rejects_the_same_order_while_unexpired(
        self, api, customer_headers_for
    ):
        """PRD §3.5: "And the box ledger must have room: the prescription's
        `boxes_consumed` plus the requested `boxes_od` plus `boxes_os` must not
        exceed its `boxes_authorized_total`, or the order is refused with
        `ERR_BOX_AUTHORIZATION_EXCEEDED`."
        PRD §2.10 item 37: "Box authorisation not exceeded, on order placement and
        on the auto-reorder run → `ERR_BOX_AUTHORIZATION_EXCEEDED` (409)."

        Design: Difficulty/priority_pair_validation_conflict/expired_prescription_outranks_box_authorization_on_order_create
        """
        scenario = _single_box_prescription_expiring_soon()

        response = api.create_order(
            _four_box_order_payload(scenario),
            customer_headers_for(scenario["customer"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_BOX_AUTHORIZATION_EXCEEDED)

        prescription = validate_success(
            api.get_prescription(
                scenario["prescription"]["id"],
                customer_headers_for(scenario["customer"]["id"]),
            )
        )
        assert prescription["boxes_consumed"] == 0

        _, meta = validate_paginated(
            api.list_orders(
                customer_headers_for(scenario["customer"]["id"]),
                params={"customer_id": scenario["customer"]["id"]},
            )
        )
        assert meta["total_count"] == 0


class TestDeviationCeilingOutranksInactiveProduct:
    """A substitute that is both clinically too far away and deactivated must
    report the fitting failure, not the catalogue failure."""

    def test_deviation_ceiling_outranks_inactive_product_on_substitution(
        self, api, fulfillment_headers
    ):
        """PRD §3.6: "Note the evaluation order, which is unusual and deliberate:
        the deviation ceiling is checked first, then the consent requirement, and
        only then whether a usable mapping exists at all."
        PRD §3.6: "An index **above 1.00** is clinically unacceptable and the swap
        is refused outright with `ERR_PARAMETER_DEVIATION_EXCEEDED` at HTTP 422,
        regardless of any consent the patient may have given."
        PRD §3.6: "After that, the substitute product must not be `INACTIVE`, or
        the request is refused with `ERR_PRODUCT_INACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/deviation_ceiling_outranks_inactive_product_on_substitution
        """
        scenario = setup_substitution_candidates(
            [
                {
                    "brand": "FarFit",
                    "name": "Daily 30 Flat",
                    "base_curve": 8.80,
                    "diameter": 14.40,
                    "equivalence": {
                        "equivalence_class": "CLINICAL",
                        "requires_patient_consent": False,
                    },
                }
            ]
        )
        substitute = scenario["substitutes"][0]
        deactivate_product(substitute["id"])
        original_version = scenario["order"]["version"]

        response = api.apply_substitution(
            scenario["order"]["id"],
            apply_substitution_payload(
                substitute["id"], original_version, patient_consent=True
            ),
            fulfillment_headers,
        )
        validate_error(response, ApiErrorId.ERR_PARAMETER_DEVIATION_EXCEEDED)

        order = validate_success(
            api.get_order(scenario["order"]["id"], fulfillment_headers)
        )
        assert order["substitution_type"] == "NONE"
        assert float(order["parameter_deviation_index"]) == 0.00
        assert order["fulfilled_product_id"] == scenario["product"]["id"]
        assert order["version"] == original_version

    def test_inactive_substitute_inside_the_ceiling_reports_product_inactive(
        self, api, fulfillment_headers
    ):
        """PRD §3.6: "An index of **at most 0.50** auto-approves: the swap
        proceeds without consent."
        PRD §3.6: "After that, the substitute product must not be `INACTIVE`, or
        the request is refused with `ERR_PRODUCT_INACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/deviation_ceiling_outranks_inactive_product_on_substitution
        """
        scenario = setup_substitution_candidates(
            [
                {
                    "brand": "FarFit",
                    "name": "Daily 30 Same Fit",
                    "base_curve": 8.60,
                    "diameter": 14.20,
                    "equivalence": {
                        "equivalence_class": "CLINICAL",
                        "requires_patient_consent": False,
                    },
                }
            ]
        )
        substitute = scenario["substitutes"][0]
        deactivate_product(substitute["id"])
        original_version = scenario["order"]["version"]

        response = api.apply_substitution(
            scenario["order"]["id"],
            apply_substitution_payload(substitute["id"], original_version),
            fulfillment_headers,
        )
        validate_error(response, ApiErrorId.ERR_PRODUCT_INACTIVE)

        order = validate_success(
            api.get_order(scenario["order"]["id"], fulfillment_headers)
        )
        assert order["substitution_type"] == "NONE"
        assert order["fulfilled_product_id"] == scenario["product"]["id"]
        assert order["version"] == original_version


class TestSegregationOfDutiesOutranksOpenDispute:
    """The officer who opened a hold cannot release it, and that refusal outranks
    the open dispute that would block the release anyway."""

    def test_segregation_of_duties_outranks_open_dispute_on_hold_release(self, api):
        """PRD §2.8: "Releasing a reorder hold requires an `X-User-ID` different
        from the hold's `opened_by_user_id`."
        PRD §3.7: "Releasing a hold has three gates, evaluated in the §2.10 order:
        the releasing `X-User-ID` must differ from `opened_by_user_id`, or the
        release is refused with `ERR_SEGREGATION_OF_DUTIES`; the prescription's
        `status` must be `VERIFIED_ACTIVE`, or the release is refused with
        `ERR_PRESCRIPTION_NOT_VERIFIED`; and no prescriber dispute on the same
        prescription may be in `OPEN` status, or the release is refused with
        `ERR_OPEN_DISPUTE_BLOCKS_RELEASE`."
        PRD §2.10: "The first check that fails determines the response, and no
        later check is evaluated."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_open_dispute_on_hold_release
        """
        scenario = setup_open_hold_with_open_dispute(hold_opener=CO_ALPHA)

        response = api.release_reorder_hold(
            scenario["hold"]["id"],
            {"note": "customer called in"},
            make_compliance_headers(CO_ALPHA),
        )
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        hold = validate_success(
            api.get_reorder_hold(
                scenario["hold"]["id"], make_compliance_headers(CO_BRAVO)
            )
        )
        assert hold["status"] == "OPEN"
        assert hold.get("released_by_user_id") is None

    def test_open_dispute_blocks_the_release_once_a_second_officer_acts(self, api):
        """PRD §3.7: "Releasing a hold has three gates, evaluated in the §2.10
        order: the releasing `X-User-ID` must differ from `opened_by_user_id`, or
        the release is refused with `ERR_SEGREGATION_OF_DUTIES`; the
        prescription's `status` must be `VERIFIED_ACTIVE`, or the release is
        refused with `ERR_PRESCRIPTION_NOT_VERIFIED`; and no prescriber dispute on
        the same prescription may be in `OPEN` status, or the release is refused
        with `ERR_OPEN_DISPUTE_BLOCKS_RELEASE`."
        PRD §3.9: "Filing appends a `DISPUTE_FILED` compliance event, and from
        that moment the dispute's existence in `OPEN` status blocks release of any
        reorder hold on the same prescription."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_open_dispute_on_hold_release
        """
        scenario = setup_open_hold_with_open_dispute(hold_opener=CO_ALPHA)

        response = api.release_reorder_hold(
            scenario["hold"]["id"],
            {"note": "customer called in"},
            make_compliance_headers(CO_BRAVO),
        )
        validate_error(response, ApiErrorId.ERR_OPEN_DISPUTE_BLOCKS_RELEASE)

        hold = validate_success(
            api.get_reorder_hold(
                scenario["hold"]["id"], make_compliance_headers(CO_ALPHA)
            )
        )
        assert hold["status"] == "OPEN"
        assert hold.get("released_by_user_id") is None

"""Vial preparation: required-activity formula, delivery posture, and the
possession-limit projection."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_dose_vial,
    create_dose_vial_payload,
    create_order,
    get_order,
    setup_f18_department,
    setup_f18_order,
    setup_f18_prepared_order,
    setup_i131_department,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
RP = TEST_USERS["radiopharmacist_headers"]


class TestRequiredActivity:
    """The required activity is prescribed x 2^(dt/HL) x tier overage, rounded
    half-up to three decimals in a single final rounding."""

    def test_required_activity_short_halflife_tier(self, api):
        """PRD §3.4: "An overage factor is then chosen from the isotope's
        half-life: 1.10 when the half-life is under 120 minutes, 1.05 when it is
        at least 120 minutes and at most 1440 minutes — a full day — and 1.00
        when it exceeds 1440 minutes. The `prescribed_activity_mbq` is multiplied
        by two raised to the power of the elapsed minutes divided by the
        half-life in minutes, and that intermediate result is multiplied by the
        overage factor. The final product is rounded half-up to three decimal
        places in a single rounding applied at the end, and recorded as the
        vial's `required_activity_mbq`."

        F-18 (HL 110 < 120 -> 1.10), prescribed 100, dt = 110 min:
        100 x 2^1 x 1.10 = 220.000.

        Design: Difficulty/combinatorial_formula/required_activity_branching_formula
        """
        ctx = setup_f18_order()
        vial = validate_success(
            api.create_dose_vial(
                create_dose_vial_payload(ctx["order"]["id"], ctx["delivery"]["id"]), RP
            ),
            201,
        )
        assert_dose_vial(vial)
        assert vial["required_activity_mbq"] == pytest.approx(220.000, abs=1e-9)
        assert vial["status"] == "PREPARED"

    def test_vial_creation_advances_order_to_dose_prepared(self, api):
        """PRD §3.4: "On success the vial is created in `PREPARED` status with
        `prepared_at` stamped from the clock, `waste_container_id` left null, and
        the order advances from `ORDERED` to `DOSE_PREPARED`; the possession
        ledger is recomputed."

        Design: Difficulty/combinatorial_formula/required_activity_branching_formula
        """
        ctx = setup_f18_order()
        validate_success(
            api.create_dose_vial(
                create_dose_vial_payload(ctx["order"]["id"], ctx["delivery"]["id"]), RP
            ),
            201,
        )
        order = get_order(ctx["order"]["id"])
        assert order["status"] == "DOSE_PREPARED"

    def test_required_activity_long_halflife_tier(self, api):
        """PRD §3.4: "An overage factor is then chosen from the isotope's
        half-life: 1.10 when the half-life is under 120 minutes, 1.05 when it is
        at least 120 minutes and at most 1440 minutes — a full day — and 1.00
        when it exceeds 1440 minutes."

        I-131 (HL 11568 > 1440 -> 1.00), prescribed 1000, dt = 30 min:
        round(1000 x 2^(30/11568) x 1.00, 3) = 1001.799.

        Design: Corner/calculations/required_activity_overage_tier_long_halflife
        """
        ctx = setup_i131_department()
        order = create_order(
            ctx["patient"]["id"],
            ctx["isotope"]["id"],
            ctx["authorized_user"],
            use_type="THERAPEUTIC",
            prescribed_activity_mbq=1000,
            administration_scheduled_at="2026-08-01T09:00:00Z",
        )
        vial = validate_success(
            api.create_dose_vial(
                create_dose_vial_payload(order["id"], ctx["delivery"]["id"]), RP
            ),
            201,
        )
        assert vial["required_activity_mbq"] == pytest.approx(1001.799, abs=1e-9)


class TestDeliveryPostureForPreparation:
    """DoseVial x IsotopeDelivery: the referenced delivery must be RECEIVED."""

    def test_scheduled_delivery_rejected(self, api):
        """PRD §3.4: "Preparation is guarded, in precedence order, by: the order
        must be in `ORDERED` status, otherwise `ERR_INVALID_STATE`; the
        referenced delivery must be `RECEIVED`, otherwise
        `ERR_DELIVERY_NOT_RECEIVED` (HTTP 409); ..."

        The delivery is never received (still SCHEDULED).

        Design: Difficulty/cross_entity_state_dependency/vial_prep_requires_received_delivery
        """
        # Build with an unreceived delivery: department fixture with receive=False.
        ctx = setup_f18_department(receive=False, with_room=False)
        order = create_order(ctx["patient"]["id"], ctx["isotope"]["id"], ctx["authorized_user"])
        res = api.create_dose_vial(
            create_dose_vial_payload(order["id"], ctx["delivery"]["id"]), RP
        )
        validate_error(res, "ERR_DELIVERY_NOT_RECEIVED", expected_status=409)
        assert get_order(order["id"])["status"] == "ORDERED", "no partial vial, no status drift"

    def test_failed_delivery_rejected(self, api):
        """PRD §3.4: "the referenced delivery must be `RECEIVED`, otherwise
        `ERR_DELIVERY_NOT_RECEIVED` (HTTP 409)". A FAILED delivery is not
        RECEIVED, so the same rejection applies.

        Design: Difficulty/cross_entity_state_dependency/vial_prep_requires_received_delivery
        """
        ctx = setup_f18_department(receive=False, with_room=False)
        validate_success(
            api.mark_isotope_delivery_failed(
                ctx["delivery"]["id"], {"reason": "generator outage"}, RP
            ),
            200,
        )
        order = create_order(ctx["patient"]["id"], ctx["isotope"]["id"], ctx["authorized_user"])
        res = api.create_dose_vial(
            create_dose_vial_payload(order["id"], ctx["delivery"]["id"]), RP
        )
        validate_error(res, "ERR_DELIVERY_NOT_RECEIVED", expected_status=409)
        assert get_order(order["id"])["status"] == "ORDERED"


class TestVialReverseLookup:
    def test_vial_filter_by_order_and_unknown_order(self, api):
        """PRD §2.10: "Reverse reachability is provided by filtered list
        endpoints rather than nested routes. ... Vials can be filtered by
        `order_id`, `delivery_id`, `waste_container_id`, and `status`." A filter
        naming an unknown order id matches nothing and yields an empty page.

        Design: Corner/endpoints/vial_reverse_lookup_by_order_and_empty_filter
        """
        ctx = setup_f18_prepared_order()
        data, meta = validate_paginated(
            api.list_dose_vials(ADMIN, params={"order_id": ctx["order"]["id"]})
        )
        assert len(data) == 1 and data[0]["id"] == ctx["vial"]["id"]
        assert meta["total_count"] == 1

        data2, meta2 = validate_paginated(
            api.list_dose_vials(ADMIN, params={"order_id": NON_EXISTENT_UUID})
        )
        assert data2 == [] and meta2["total_count"] == 0


class TestPossessionLimitProjection:
    def test_projected_possession_exceeding_license_cap_rejected(self, api):
        """PRD §3.4: "the projected `current_possession_mbq` after the draw must
        not exceed either the license-wide `max_possession_mbq` or the matching
        isotope condition's `max_possession_mbq`, otherwise
        `ERR_POSSESSION_LIMIT_EXCEEDED` (HTTP 409)".

        License cap 100 MBq; the projected draw of 220.000 MBq exceeds it while
        the delivery itself holds ample activity.

        Design: Corner/validations/vial_prep_possession_limit_exceeded
        """
        ctx = setup_f18_department(
            with_room=False, license_overrides={"license_number": "L-TINY", "max_possession_mbq": 100}
        )
        order = create_order(ctx["patient"]["id"], ctx["isotope"]["id"], ctx["authorized_user"])
        res = api.create_dose_vial(
            create_dose_vial_payload(order["id"], ctx["delivery"]["id"]), RP
        )
        validate_error(res, "ERR_POSSESSION_LIMIT_EXCEEDED", expected_status=409)
        assert get_order(order["id"])["status"] == "ORDERED"

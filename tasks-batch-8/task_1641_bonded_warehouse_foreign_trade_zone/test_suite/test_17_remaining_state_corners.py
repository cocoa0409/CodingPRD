"""Remaining corner coverage: withdrawal on a depleted lot, completing an
unapproved order, badge schema window rule, and immediate read-after-write
consistency."""
from test_helpers import (
    ApiErrorId,
    api_client,
    complete_manipulation_order,
    create_access_badge_payload,
    create_badge,
    create_filed_withdrawal,
    create_manipulation_order,
    create_withdrawal,
    create_zone,
    get_lot,
    get_success_data,
    get_zone,
    make_gate_officer_headers,
    make_importer_headers,
    make_zone_operator_headers,
    setup_zone_with_lot,
    submit_admission,
    admit_admission,
    create_admission,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestWithdrawalOnDepletedLotRejected:
    def test_file_against_depleted_lot_rejected(self):
        """PRD §3.5: "Filing requires the withdrawal to be `DRAFT` ... and the lot
        to be `IN_ZONE` (otherwise `ERR_LOT_NOT_IN_ZONE`)."
        PRD §3.5: "a lot left at zero on hand transitions from `IN_ZONE` to
        `DEPLETED`"

        Design: Corner/errors/c_withdrawal_on_depleted_lot_rejected
        """
        zone, _a, lot = setup_zone_with_lot(
            quantity=5, unit_value_cents=1000, hts_code="0401.10",
            zone_status="NON_PRIVILEGED_FOREIGN", bond_coverage_cents=10_000_000_000,
            importer_id="imp-1", zone_name="Depleted Zone", zone_code="Z-DPL",
        )
        # W1 (qty 5) files first, depleting the lot; W2 was created while IN_ZONE.
        w1 = create_filed_withdrawal(zone["id"], lot["id"], quantity=5,
                                     withdrawal_type="EXPORT", importer_id="imp-1")
        w2 = create_withdrawal(zone["id"], lot["id"], quantity=1,
                               withdrawal_type="EXPORT", importer_id="imp-1")
        assert get_lot(lot["id"])["status"] == "DEPLETED"

        imp = make_importer_headers("imp-1")
        resp = api_client.file_withdrawal(w2["id"], imp)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_IN_ZONE, expected_status=409)
        w2_after = get_success_data(api_client.get_withdrawal(w2["id"], make_zone_operator_headers()))
        assert w2_after["status"] == "DRAFT"


class TestCompleteUnapprovedOrderRejected:
    def test_complete_requested_order_rejected(self):
        """PRD §3.4: "Completion is performed by the owning importer against an
        `APPROVED` order"
        PRD §3.4: "Acting on an order outside these states yields
        `ERR_ORDER_INVALID_TRANSITION`."

        Design: Corner/errors/c_complete_unapproved_order_rejected
        """
        zone, _a, lot = setup_zone_with_lot(
            quantity=100, unit_value_cents=10000, hts_code="8542.31",
            zone_status="NON_PRIVILEGED_FOREIGN", bond_coverage_cents=10_000_000_000,
            importer_id="imp-1", zone_name="Order Zone", zone_code="Z-ORD",
        )
        m = create_manipulation_order(
            zone["id"], lot["id"], input_quantity=10, output_hts_code="9503.00",
            output_quantity=5, value_added_cents=10000, output_description="Kitting",
            importer_id="imp-1",
        )
        imp = make_importer_headers("imp-1")
        resp = api_client.complete_manipulation_order(m["id"], imp)
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_TRANSITION, expected_status=409)
        assert get_lot(lot["id"])["quantity_on_hand"] == 100


class TestBadgeInvalidWindowRejected:
    def test_valid_from_equal_valid_until_rejected(self):
        """PRD §3.8: "`valid_until` must be strictly after `valid_from` or issuance
        fails schema validation with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/c_badge_invalid_window_rejected
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Badge Check Zone",
                           zone_code="Z-BCK")
        op = make_zone_operator_headers()
        resp = api_client.create_access_badge(
            create_access_badge_payload(
                zone_id=zone["id"], holder_name="Bad Window",
                valid_from="2026-08-10T00:00:00Z", valid_until="2026-08-10T00:00:00Z",
            ), op,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestImmediateVisibilityAfterAdmit:
    def test_reads_immediately_observe_admit_effects(self):
        """PRD §1 Introduction: "every mutation and every cascade it triggers must
        be visible immediately in the same request's response and in all subsequent
        reads — there is no eventual consistency anywhere in this system."
        PRD §3.2: "Admitting stamps `admission_date` from the logical clock (the
        field is null beforehand) and creates an **InventoryLot** in `IN_ZONE`
        status ... The zone's `deferred_duty_exposure_cents` and `active_lot_count`
        are then recomputed to reflect the new lot."

        Design: Corner/consistency_model/c_immediate_visibility_after_admit
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Immediate Zone",
                           zone_code="Z-IMM")
        a = create_admission(zone["id"], importer_id="imp-1", description="Dairy",
                             hts_code="0401.10", quantity=4, unit_value_cents=2500,
                             zone_status="NON_PRIVILEGED_FOREIGN")
        submit_admission(a["id"], importer_id="imp-1")
        admitted = admit_admission(a["id"])
        assert admitted["status"] == "ADMITTED"

        # The very next reads observe the lot and the updated aggregates.
        z = get_zone(zone["id"])
        # round(4 x 2500 x 0.05) = 500
        assert z["deferred_duty_exposure_cents"] == 500, (
            f"exposure immediately 500, got {z['deferred_duty_exposure_cents']}"
        )
        assert z["active_lot_count"] == 1

        op = make_zone_operator_headers()
        rows, meta = validate_paginated(api_client.list_lots(op, params={"admission_id": a["id"]}))
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "IN_ZONE"
        assert rows[0]["quantity_on_hand"] == 4

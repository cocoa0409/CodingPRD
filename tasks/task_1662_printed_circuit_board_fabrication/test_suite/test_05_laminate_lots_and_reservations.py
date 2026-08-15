"""Laminate lot lifecycle, reservation guard chain, conservation invariant,
OCC on the lot, and reservation listing filters (PRD §2.6, §2.8, §3.5).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_lot_conservation,
    create_customer, create_order, create_and_lock_stackup, submit_dfm,
    dfm_approve, create_and_release_array, create_laminate_lot, qualify_lot,
    create_qualified_lot, get_laminate_lot, reserve_panels, prepare_order,
    create_laminate_lot_payload, create_reservation_payload,
    make_customer_headers,
    TEST_USERS,
    DEFAULT_SHIP_DATE,
)

ENG = TEST_USERS["process_engineer_headers"]
QI = TEST_USERS["quality_inspector_headers"]
PLANNER = TEST_USERS["production_planner_headers"]


class TestReserveReleaseConservation:
    def test_reserve_then_release_conserves_lot_panels(self, api):
        """PRD §3.5: "Its `panels_available` is always the remainder of
        `panels_total` minus `panels_reserved` minus `panels_consumed` — a
        conservation invariant the system maintains on every mutation" and
        "A successful reservation opens in `RESERVED` status, adds its
        `panels_allocated` to the lot's `panels_reserved`"; a manual release
        is "returning its panels to the lot's availability".

        Design: Difficulty/compensating_invariant/laminate_reserve_release_conservation
        """
        ctx = prepare_order(
            company_name="Rho Circuits", contact_email="ops@rho.example",
            lot_code="LOT-Q1", panels_total=100, with_reservation=False,
        )
        lot = ctx["lot"]

        reservation = reserve_panels(
            ctx["order"]["id"], ctx["array"]["id"], lot["id"], 34,
        )
        assert reservation["status"] == "RESERVED"

        mid = get_laminate_lot(lot["id"])
        assert_lot_conservation(mid)
        assert mid["panels_reserved"] == 34
        assert mid["panels_consumed"] == 0
        assert mid["panels_available"] == 66, "100 == 34 reserved + 0 consumed + 66"

        get_success_data(api.release_reservation(reservation["id"], PLANNER))
        fin = get_laminate_lot(lot["id"])
        assert_lot_conservation(fin)
        assert fin["panels_reserved"] == 0
        assert fin["panels_consumed"] == 0
        assert fin["panels_available"] == 100, (
            "reserve + release must conserve the lot exactly: 100 == 0 + 0 + 100"
        )

        reservation = get_success_data(api.get_reservation(reservation["id"], PLANNER))
        assert reservation["status"] == "RELEASED"

    def test_full_reservation_depletes_then_release_revives_lot(self, api):
        """PRD §3.5: "whenever consumption or reservation drives a `QUALIFIED`
        lot's `panels_available` to exactly zero, the lot becomes `DEPLETED`;
        and when a reservation release lifts a `DEPLETED` lot's availability
        back above zero, the lot returns to `QUALIFIED`." PRD §3.6: "the system
        itself places an `AWAITING_LAMINATE` order `ON_HOLD` whenever a
        reservation leaves `RESERVED` status and coverage drops below
        `panels_required`".

        Design: Difficulty/compensating_invariant/laminate_reserve_release_conservation
        """
        ctx = prepare_order(
            company_name="Rho Two", contact_email="ops@rho2.example",
            lot_code="LOT-Q2", panels_total=34, panels_to_reserve=34,
        )
        lot = ctx["lot"]
        reservation = ctx["reservation"]

        mid = get_laminate_lot(lot["id"])
        assert_lot_conservation(mid)
        assert mid["panels_available"] == 0
        assert mid["status"] == "DEPLETED", (
            f"reserving all 34 panels must deplete the lot, got {mid['status']}"
        )

        get_success_data(api.release_reservation(reservation["id"], PLANNER))
        fin = get_laminate_lot(lot["id"])
        assert_lot_conservation(fin)
        assert fin["panels_available"] == 34
        assert fin["status"] == "QUALIFIED", (
            f"release lifting availability above zero must revive the lot, got {fin['status']}"
        )

        order = get_success_data(api.get_fab_order(ctx["order"]["id"], PLANNER))
        assert order["fab_status"] == "ON_HOLD", (
            f"coverage dropped to 0 < 34, so the order must drop to ON_HOLD, got {order['fab_status']}"
        )


class TestReservationGuardChain:
    def test_temporal_violation_masks_insufficient_panels(self, api):
        """PRD §3.5 lists the reservation guard chain "evaluated in precedence
        order": "the lot must outlive the shipment, meaning its `expiry_date`
        must fall strictly after the order's `requested_ship_date`, with equality
        rejecting as `ERR_LOT_EXPIRES_BEFORE_SHIP`; the lot must physically have
        the panels, so `panels_allocated` greater than the lot's
        `panels_available` is rejected with `ERR_INSUFFICIENT_LAMINATE`".

        Design: Difficulty/priority_pair_validation_conflict/reservation_temporal_beats_insufficient_panels
        """
        ctx = prepare_order(
            company_name="Kappa Circuits", contact_email="ops@kappa.example",
            lot_code="LOT-T1", manufacture_date="2025-08-10T00:00:00Z",
            panels_total=10, with_reservation=False,
        )
        # Lot expires 2026-08-10, exactly the ship date (temporal violation),
        # and only 10 panels are available for a 34-panel ask (fiscal violation).
        lot = ctx["lot"]
        payload = create_reservation_payload(
            ctx["order"]["id"], ctx["array"]["id"], lot["id"], lot["version"],
            panels_allocated=34,
        )
        resp = api.create_reservation(payload, PLANNER)
        validate_error(resp, ApiErrorId.ERR_LOT_EXPIRES_BEFORE_SHIP)

    def test_expiry_exactly_at_ship_date_rejects(self, api):
        """PRD §3.5: "the lot must outlive the shipment, meaning its
        `expiry_date` must fall strictly after the order's `requested_ship_date`,
        with equality rejecting as `ERR_LOT_EXPIRES_BEFORE_SHIP`".

        Design: Difficulty/priority_pair_validation_conflict/reservation_temporal_beats_insufficient_panels
        """
        ctx = prepare_order(
            company_name="Kappa Two", contact_email="ops@kappa2.example",
            lot_code="LOT-T2", manufacture_date="2025-08-10T00:00:00Z",
            panels_total=100, with_reservation=False,
        )
        # Expiry == ship date exactly; panels are plentiful, so only the
        # strict-greater-than temporal rule can fail.
        lot = ctx["lot"]
        payload = create_reservation_payload(
            ctx["order"]["id"], ctx["array"]["id"], lot["id"], lot["version"],
            panels_allocated=34,
        )
        resp = api.create_reservation(payload, PLANNER)
        validate_error(resp, ApiErrorId.ERR_LOT_EXPIRES_BEFORE_SHIP)

    def test_date_code_one_second_grace(self, api):
        """PRD §3.5: "its `expiry_date` must fall strictly after the order's
        `requested_ship_date`, with equality rejecting" and "its `expiry_date`
        is exactly 365 days after `manufacture_date`". One second of grace
        satisfies the strict inequality.

        Design: Corner/calculations/date_code_boundary_one_second_grace
        """
        ctx = prepare_order(
            company_name="Grace Co", contact_email="grace@co.example",
            lot_code="LOT-G1", manufacture_date="2025-08-10T00:00:01Z",
            panels_total=100, with_reservation=False,
        )
        # expiry 2026-08-10T00:00:01Z is strictly after ship 2026-08-10T00:00:00Z.
        reservation = reserve_panels(
            ctx["order"]["id"], ctx["array"]["id"], ctx["lot"]["id"], 34,
        )
        assert reservation["status"] == "RESERVED"

    def test_expired_lot_qualify_rejected(self, api):
        """PRD §3.5: "Qualification is refused when the clock has reached the
        lot's `expiry_date` — at the exact expiry instant the lot is already too
        old — surfacing `ERR_LOT_NOT_QUALIFIED`" and "When the logical clock
        reaches a lot's `expiry_date` — re-evaluated both when the clock is set
        and on every access to the lot — a `RECEIVED` lot simply becomes
        `EXPIRED`".

        Design: Corner/state_machines/expired_lot_qualify_rejected
        """
        # Manufacture 2025-08-01 -> expiry 2026-08-01T00:00:00Z == the default
        # logical clock, so the lot is already at its expiry instant.
        lot = create_laminate_lot(
            "LOT-EX1", manufacture_date="2025-08-01T00:00:00Z", panels_total=10,
        )
        resp = api.qualify_lot(lot["id"], QI)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_QUALIFIED)
        lot = get_laminate_lot(lot["id"])
        assert lot["status"] == "EXPIRED"

    def test_duplicate_lot_code_rejected(self, api):
        """PRD §3.5: "a supplier `lot_code` unique across all lots (a duplicate
        is rejected with `ERR_DUPLICATE_LOT_CODE`)".

        Design: Corner/validations/duplicate_lot_code_rejected
        """
        create_laminate_lot("LOT-DUP", panels_total=10)
        payload = create_laminate_lot_payload(
            material_code="FR4_TG135", lot_code="LOT-DUP",
            manufacture_date="2025-10-01T00:00:00Z", panels_total=5,
        )
        resp = api.create_laminate_lot(payload, ENG)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LOT_CODE)

    def test_reservation_reference_not_found(self, api):
        """PRD §3.5: "The referenced records must exist and the named array must
        belong to the named order, else `ERR_REFERENCE_NOT_FOUND`".

        Design: Corner/validations/reservation_reference_not_found
        """
        ctx = prepare_order(
            company_name="Ref Co", contact_email="ref@co.example",
            lot_code="LOT-RF1", with_reservation=False,
        )
        payload = create_reservation_payload(
            ctx["order"]["id"], ctx["array"]["id"], NON_EXISTENT_UUID,
            ctx["lot"]["version"], panels_allocated=34,
        )
        resp = api.create_reservation(payload, PLANNER)
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)

    def test_reservation_mismatched_array_rejected(self, api):
        """PRD §2.8: "a `panel_array_id` that belongs to a different order than
        the `fab_order_id` in the same payload is not merely missing, it is
        mis-parented. Any such dangling or mis-parented body reference is
        rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 422)."

        Design: Corner/validations/reservation_mismatched_array_rejected
        """
        ctx1 = prepare_order(
            company_name="Mix One", contact_email="mix1@co.example",
            lot_code="LOT-MX1", with_reservation=False,
        )
        ctx2 = prepare_order(
            company_name="Mix Two", contact_email="mix2@co.example",
            lot_code="LOT-MX2", with_lot=False, with_reservation=False,
        )
        payload = create_reservation_payload(
            ctx1["order"]["id"], ctx2["array"]["id"], ctx1["lot"]["id"],
            ctx1["lot"]["version"], panels_allocated=34,
        )
        resp = api.create_reservation(payload, PLANNER)
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)

    def test_occ_reservation_stale_lot_rejected(self, api):
        """PRD §2.6: "Creating a laminate reservation requires
        `expected_laminate_lot_version`, carrying the `version` of the target
        `LaminateLot` the client last observed. ... if the lot's current
        `version` has advanced since that read — through another reservation, a
        release, or a qualification — the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_reservation_stale_lot_rejected
        """
        ctx = prepare_order(
            company_name="OccL Co", contact_email="occl@co.example",
            lot_code="LOT-OC1", with_reservation=False,
        )
        lot = ctx["lot"]
        stale_version = lot["version"]

        # First reservation advances LaminateLot.version past the captured value.
        reserve_panels(ctx["order"]["id"], ctx["array"]["id"], lot["id"], 34)

        payload = create_reservation_payload(
            ctx["order"]["id"], ctx["array"]["id"], lot["id"], stale_version,
            panels_allocated=10,
        )
        resp = api.create_reservation(payload, PLANNER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_quarantine_with_live_reservations_rejected(self, api):
        """PRD §3.5: "a `QUALIFIED` lot can be quarantined only while no
        `RESERVED` reservation references it, else `ERR_INVALID_STATE`".

        Design: Corner/validations/quarantine_with_reservations_rejected
        """
        ctx = prepare_order(
            company_name="Quar Co", contact_email="quar@co.example",
            lot_code="LOT-QZ1",
        )
        resp = api.quarantine_lot(ctx["lot"]["id"], {"reason": "supplier recall"}, QI)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        lot = get_laminate_lot(ctx["lot"]["id"])
        assert lot["status"] == "QUALIFIED"


class TestReservationListing:
    def test_filtered_reservations_list(self, api):
        """PRD §3.5: "Reservation listings may be filtered by any of their
        foreign keys or by `status`." PRD §2.3: "Every list response is sorted
        by `created_at` in ascending order unless stated otherwise".

        Design: Corner/endpoints/filtered_reservations_list
        """
        ctx = prepare_order(
            company_name="Filt Co", contact_email="filt@co.example",
            lot_code="LOT-F1", panels_total=60, with_reservation=False,
        )
        lot2 = create_qualified_lot("LOT-F2", panels_total=60)

        res1 = reserve_panels(ctx["order"]["id"], ctx["array"]["id"],
                              ctx["lot"]["id"], 34)
        res2 = reserve_panels(ctx["order"]["id"], ctx["array"]["id"],
                              lot2["id"], 10)

        data, meta = validate_paginated(
            api.list_reservations(PLANNER, params={"laminate_lot_id": lot2["id"]})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in data] == [res2["id"]]

        data, meta = validate_paginated(
            api.list_reservations(PLANNER, params={"fab_order_id": ctx["order"]["id"]})
        )
        assert meta["total_count"] == 2
        assert [row["id"] for row in data] == [res1["id"], res2["id"]], (
            "created_at ascending order must list res1 before res2"
        )

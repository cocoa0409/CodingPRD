"""Entitlement consolidation: request shape, initial status, voiding, window
overlap, and the clock sweep (PRD §2.4, §3.2)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_entitlement,
    create_entitlement,
    create_entitlement_payload,
    create_vendor_and_product,
    get_license_position,
    list_product_entitlements,
    set_clock,
    setup_product_with_gap,
    validate_error,
    validate_success,
)


class TestEntitlementCreateShape:
    def test_entitlement_create_missing_quantity_returns_invalid_request(
            self, api, sam_manager_headers):
        """PRD §2.10: "Request shape — required fields are present, types match,
        enum values are valid, `quantity` and `amount_cents` are positive,
        `effective_from` is earlier than `effective_to` when both are present,
        required arrays such as `covered_scope_item_ids` and
        `target_deployment_ids` are non-empty where required, an entitlement
        `source` on manual creation is limited to `MANUAL_IMPORT` or
        `CONTRACT_EXTRACT`, and `future_license_discount_pct` lies within its
        allowed range; violations yield `ERR_INVALID_REQUEST`."
        PRD §3.2: "A `SAMManager` or `ProcurementLead` consolidates each purchase by
        providing the `product_id` the purchase entitles, the procurement
        `purchase_order_number` as contract reference, the licensed `quantity` as a
        positive integer, the `coverage_class` the purchase covers (`PRODUCTION`,
        `NON_PRODUCTION`, or `DISASTER_RECOVERY`), the coverage window
        `effective_from` and optionally `effective_to`, and the record's `source` —
        `MANUAL_IMPORT` or `CONTRACT_EXTRACT`."

        Design: Corner/entities/entitlement_create_missing_quantity_returns_invalid_request
        """
        _vendor, product = create_vendor_and_product()
        payload = create_entitlement_payload(product["id"])
        del payload["quantity"]
        resp = api.create_entitlement(payload, sam_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestInitialStatus:
    def test_entitlement_active_immediately_when_effective_from_passed(
            self, api, sam_manager_headers):
        """PRD §3.2: "A record's initial `status` is decided against the logical
        clock at creation: when `effective_from` lies in the future the record
        begins `SCHEDULED`, and otherwise it begins `ACTIVE` and immediately
        contributes to the product's entitled quantity."

        Design: Corner/entities/entitlement_active_immediately_when_effective_from_passed
        """
        _vendor, product = create_vendor_and_product()
        resp = api.create_entitlement(
            create_entitlement_payload(product["id"], quantity=40,
                                       effective_from="2026-01-01T00:00:00Z"),
            sam_manager_headers)
        entitlement = validate_success(resp, 201)
        assert_entitlement(entitlement)
        assert entitlement["status"] == "ACTIVE", \
            "effective_from 2026-01-01 is before the 2026-08-01 logical clock"

        position = get_license_position(product["id"])
        assert position["entitled_quantity"] == 40, \
            "an ACTIVE record immediately contributes its quantity"


class TestEntitlementVoid:
    def test_entitlement_void_twice_rejected(self, api, sam_manager_headers):
        """PRD §3.2: "Only `ACTIVE` or `SCHEDULED` records can be voided; attempting
        to void a record in any other state is rejected with
        `ERR_ENTITLEMENT_INVALID_STATE`."
        PRD §3.2: "Voiding an `ACTIVE` record drops its quantity from the position
        and triggers the same recompute cascade across position, case rollups, and
        alerts; voiding a `SCHEDULED` record has no downstream effects."

        Design: Corner/state_machines/entitlement_void_twice_rejected
        """
        _vendor, product = create_vendor_and_product()
        entitlement = create_entitlement(product["id"], quantity=40)

        voided = validate_success(
            api.void_entitlement(entitlement["id"], sam_manager_headers), 200)
        assert voided["status"] == "VOID"

        resp = api.void_entitlement(entitlement["id"], sam_manager_headers)
        validate_error(resp, ApiErrorId.ERR_ENTITLEMENT_INVALID_STATE)

        position = get_license_position(product["id"])
        assert position["entitled_quantity"] == 0, \
            "the quantity is debited exactly once by the single successful void"

    def test_entitlement_not_found_on_void(self, api, sam_manager_headers):
        """PRD §3.2: "A product's purchase history can be listed with an optional
        `status` filter, and unknown entitlement identifiers surface as
        `ERR_ENTITLEMENT_NOT_FOUND`."

        Design: Corner/errors/entitlement_not_found_on_void
        """
        resp = api.void_entitlement(NON_EXISTENT_UUID, sam_manager_headers)
        validate_error(resp, ApiErrorId.ERR_ENTITLEMENT_NOT_FOUND)


class TestEntitlementWindowOverlap:
    def test_entitlement_window_touching_boundary_overlaps(self, api,
                                                           sam_manager_headers):
        """PRD §3.2: "Coverage windows are closed intervals that include both their
        boundary dates, so two records for the same product and `coverage_class`
        whose windows merely touch at a boundary date are already considered
        overlapping."
        PRD §3.2: "Creation is rejected with `ERR_ENTITLEMENT_WINDOW_OVERLAP` when
        the new window overlaps an existing `SCHEDULED` or `ACTIVE` record of the
        same product and coverage class; `AUTO_TRUE_UP` records are exempt from
        this check, and records already `EXPIRED` or `VOID` no longer participate
        in it."

        Design: Difficulty/resource_temporal_overlap/entitlement_window_closed_interval_touch
        """
        _vendor, product = create_vendor_and_product()
        first = create_entitlement(
            product["id"], purchase_order_number="PO-2026", quantity=100,
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-12-31T00:00:00Z")
        assert first["status"] == "ACTIVE"

        touching = api.create_entitlement(
            create_entitlement_payload(
                product["id"], purchase_order_number="PO-DUP", quantity=50,
                effective_from="2026-12-31T00:00:00Z",
                effective_to="2027-12-31T00:00:00Z"),
            sam_manager_headers)
        validate_error(touching, ApiErrorId.ERR_ENTITLEMENT_WINDOW_OVERLAP)

    def test_entitlement_window_disjoint_start_succeeds_scheduled(
            self, api, sam_manager_headers):
        """PRD §3.2: "Coverage windows are closed intervals that include both their
        boundary dates, so two records for the same product and `coverage_class`
        whose windows merely touch at a boundary date are already considered
        overlapping."
        PRD §3.2: "A record's initial `status` is decided against the logical clock
        at creation: when `effective_from` lies in the future the record begins
        `SCHEDULED`, and otherwise it begins `ACTIVE` and immediately contributes to
        the product's entitled quantity."

        Design: Difficulty/resource_temporal_overlap/entitlement_window_closed_interval_touch
        """
        _vendor, product = create_vendor_and_product()
        create_entitlement(
            product["id"], purchase_order_number="PO-2026", quantity=100,
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-12-31T00:00:00Z")

        resp = api.create_entitlement(
            create_entitlement_payload(
                product["id"], purchase_order_number="PO-2027", quantity=50,
                effective_from="2027-01-01T00:00:00Z",
                effective_to="2027-12-31T00:00:00Z"),
            sam_manager_headers)
        second = validate_success(resp, 201)
        assert_entitlement(second)
        assert second["status"] == "SCHEDULED", \
            "the 2027-01-01 window is disjoint from [2026-01-01, 2026-12-31] and " \
            "starts after the 2026-08-01 logical clock"


class TestClockSweep:
    def test_scheduled_entitlement_activates_on_clock_sweep(self, api,
                                                            sam_manager_headers):
        """PRD §2.4: "Setting the clock triggers the entitlement status sweep (every
        `SCHEDULED` record whose `effective_from` has been reached becomes `ACTIVE`,
        and every `ACTIVE` record whose `effective_to` has been reached or passed
        becomes `EXPIRED`), the `ENTITLEMENT_EXPIRING` alert sweep, position
        recomputation for affected products, and recomputation of the audit case
        rollups that depend on them."
        PRD §3.4: "Its `entitled_quantity` is the sum of `quantity` over the
        product's entitlement records currently in `ACTIVE` status; records in
        `SCHEDULED`, `EXPIRED`, or `VOID` never contribute."

        Design: Corner/calculations/scheduled_entitlement_activates_on_clock_sweep
        """
        _vendor, product = create_vendor_and_product()
        resp = api.create_entitlement(
            create_entitlement_payload(
                product["id"], purchase_order_number="PO-FUT", quantity=25,
                effective_from="2026-09-01T00:00:00Z",
                effective_to="2027-08-31T00:00:00Z", source="CONTRACT_EXTRACT"),
            sam_manager_headers)
        entitlement = validate_success(resp, 201)
        assert entitlement["status"] == "SCHEDULED", \
            "effective_from 2026-09-01 is after the 2026-08-01 logical clock"
        assert get_license_position(product["id"])["entitled_quantity"] == 0, \
            "a SCHEDULED record contributes nothing"

        set_clock("2026-09-01T00:00:00Z")

        rows = list_product_entitlements(product["id"])
        swept = next(r for r in rows if r["id"] == entitlement["id"])
        assert swept["status"] == "ACTIVE", \
            "the sweep activates a record once effective_from is reached (inclusive)"
        assert get_license_position(product["id"])["entitled_quantity"] == 25

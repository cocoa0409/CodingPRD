"""Role-based access control, validation priority ordering, uniqueness
constraints, and disposition-record retention."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    advance_clock,
    create_freezer_payload,
    create_supplier_payload,
    get_success_data,
    make_manifest_item,
    setup_freezer,
    setup_implanted_unit,
    setup_received_shipment,
    setup_supplier_and_freezer,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
QM = TEST_USERS["quality_headers"]
CO = TEST_USERS["compliance_headers"]
SURG = TEST_USERS["surgeon_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestRbac:
    def test_rbac_coordinator_cannot_create_freezer(self, api):
        """PRD §2.1: "An authenticated operator whose role is not listed for
        the endpoint they call is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: freezer registration is authorized for `SupplyChainAdmin` only.

        Design: Corner/rbac/rbac_coordinator_cannot_create_freezer
        """
        resp = api.create_freezer(
            create_freezer_payload(name="FZ-X", nominal_capacity=10), COORD
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_rbac_surgeon_cannot_release_unit(self, api):
        """PRD §2.1: "An authenticated operator whose role is not listed for
        the endpoint they call is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §2.8: "2. **Role authorization** — the role is listed for the
        endpoint (`ERR_INSUFFICIENT_PERMISSIONS`, 403)."
        PRD §2.8: "3. **Path existence** — identifiers resolve left to right
        (the 404 family of §2.6)."

        Design: Corner/rbac/rbac_surgeon_cannot_release_unit
        """
        # Role check (rung 2) precedes path existence (rung 3): even an unknown
        # unit id is rejected 403 for an unauthorized role.
        resp = api.release_unit(NON_EXISTENT_UUID, SURG)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_rbac_admin_cannot_approve_supplier(self, api):
        """PRD §2.1: "An authenticated operator whose role is not listed for
        the endpoint they call is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §3.1: "Approval is the compliance function's decision."

        Design: Corner/rbac/rbac_admin_cannot_approve_supplier
        """
        supplier = get_success_data(
            api.create_supplier(create_supplier_payload(), QM)
        )
        resp = api.approve_supplier(supplier["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        after = validate_success(api.get_supplier(supplier["id"], QM))
        assert after["status"] == "PENDING_QUALIFICATION"

    def test_rbac_quality_cannot_finalize_disposition(self, api):
        """PRD §2.1: "An authenticated operator whose role is not listed for
        the endpoint they call is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §2.11: "A `ComplianceOfficer` finalizes a draft, which moves the
        record to `FINALIZED`, stamps `finalized_at` with the logical clock,
        and records the officer as `finalized_by_user_id`."

        Design: Corner/rbac/rbac_quality_cannot_finalize_disposition
        """
        resp = api.finalize_disposition_record(NON_EXISTENT_UUID, QM)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestPriorityOrdering:
    def test_role_denied_before_not_found(self, api):
        """PRD §2.8: "When a request violates several rules, the platform
        reports exactly one failure: the one from the earliest rung of a pinned
        priority ladder."
        PRD §2.8: "2. **Role authorization** — the role is listed for the
        endpoint (`ERR_INSUFFICIENT_PERMISSIONS`, 403)."
        PRD §2.8: "3. **Path existence** — identifiers resolve left to right
        (the 404 family of §2.6)."

        Design: Corner/validations/role_denied_before_not_found
        """
        freezer = setup_freezer()
        resp = api.update_freezer(
            NON_EXISTENT_UUID,
            {"max_celsius": -59.0,
             "expected_freezer_version": freezer["version"]},
            QM,  # QualityManager is not authorized for freezer reconfiguration
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_request_shape_before_state_on_reject(self, api):
        """PRD §2.8: "This rung is deliberately pinned after headers and path
        existence but before OCC and before any state-machine precondition — a
        malformed body is reported only once the caller and the target are
        established."
        PRD §3.2: "Rejection by a `TissueBankCoordinator` requires a
        `rejection_reason` of at least ten characters (anything shorter fails
        with `ERR_INVALID_REQUEST`)"

        Design: Corner/validations/request_shape_before_state_on_reject
        """
        _, _, shipment, _ = setup_received_shipment()
        get_success_data(
            api.reject_shipment(
                shipment["id"], {"rejection_reason": "Cold chain broken in transit"}, COORD
            )
        )
        # The shipment is already REJECTED, but the too-short reason is a
        # request-shape failure and is reported before the state error.
        resp = api.reject_shipment(shipment["id"], {"rejection_reason": "short"}, COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestUniqueness:
    def test_duplicate_value_three_surfaces(self, api):
        """PRD §3.1: "The license number is unique across suppliers; a
        duplicate submission is rejected with `ERR_DUPLICATE_VALUE`."
        PRD §3.3: "A `SupplyChainAdmin` registers each storage unit with a
        display `name` (unique across freezers, duplicates failing with
        `ERR_DUPLICATE_VALUE`)"
        PRD §3.2: "a `serial_number` unique within the shipment (duplicates
        across two lines of the same manifest are rejected with
        `ERR_DUPLICATE_VALUE`)"

        Design: Corner/errors/error_duplicate_value_three_surfaces
        """
        supplier, freezer = setup_supplier_and_freezer()  # QUALIFIED, FZ-ULT-1
        resp1 = api.create_supplier(
            create_supplier_payload(legal_name="Copycat Tissue",
                                    license_number="LIC-001"),
            QM,
        )
        validate_error(resp1, ApiErrorId.ERR_DUPLICATE_VALUE)
        resp2 = api.create_freezer(
            create_freezer_payload(name="FZ-ULT-1", min_celsius=-40.0,
                                   max_celsius=-20.0, nominal_capacity=10),
            ADMIN,
        )
        validate_error(resp2, ApiErrorId.ERR_DUPLICATE_VALUE)
        resp3 = api.create_shipment(
            {
                "supplier_id": supplier["id"],
                "freezer_id": freezer["id"],
                "items": [
                    make_manifest_item(serial_number="U-001", unit_cost_cents=5000),
                    make_manifest_item(serial_number="U-001", unit_cost_cents=6000),
                ],
            },
            COORD,
        )
        validate_error(resp3, ApiErrorId.ERR_DUPLICATE_VALUE)


class TestDispositionRetention:
    def test_disposition_lifecycle_finalize_then_retention_boundary(self, api):
        """PRD §2.11: "Once finalized, a record is immutable, and its retention
        clock starts: deletion is permitted only when the logical clock has
        reached at least `finalized_at` plus 3650 days — a ten-year retention
        floor. Purging earlier is rejected with `ERR_RETENTION_PERIOD_ACTIVE`
        (HTTP 409), and attempting to delete a record still in `DRAFT` is
        rejected with `ERR_DISPOSITION_INVALID_STATE`. A successful purge
        returns 204 with no data."
        PRD §2.11: "Finalizing a record that is not in `DRAFT` is rejected with
        `ERR_DISPOSITION_INVALID_STATE`."

        Design: Corner/state_machines/disposition_lifecycle_finalize_then_retention_boundary
        """
        bundle = setup_implanted_unit(via_reservation=False)
        records = get_success_data(
            api.list_unit_disposition_records(bundle["unit"]["id"], CO)
        )
        assert len(records) == 1
        record = records[0]
        assert record["status"] == "DRAFT"

        finalized = validate_success(api.finalize_disposition_record(record["id"], CO))
        assert finalized["status"] == "FINALIZED"
        assert finalized["finalized_at"].startswith("2026-08-10T11:00:00")
        assert finalized["finalized_by_user_id"] == "co-1"

        # Immutable thereafter: a second finalize is rejected.
        validate_error(
            api.finalize_disposition_record(record["id"], CO),
            ApiErrorId.ERR_DISPOSITION_INVALID_STATE,
        )
        # One day before finalized_at + 3650 days: retention still active.
        advance_clock("2036-08-06T11:00:00Z")
        validate_error(
            api.delete_disposition_record(record["id"], CO),
            ApiErrorId.ERR_RETENTION_PERIOD_ACTIVE,
        )
        # Exactly at the boundary (>= semantics): purge succeeds.
        advance_clock("2036-08-07T11:00:00Z")
        purged = api.delete_disposition_record(record["id"], CO)
        assert purged.status_code == 204, (
            f"expected 204 purge at the retention boundary, got {purged.status_code}"
        )
        validate_error(
            api.get_disposition_record(record["id"], CO),
            ApiErrorId.ERR_DISPOSITION_NOT_FOUND,
        )

    def test_disposition_delete_draft_blocked(self, api):
        """PRD §2.11: "attempting to delete a record still in `DRAFT` is
        rejected with `ERR_DISPOSITION_INVALID_STATE`"
        PRD §3.2: "every minted unit, still `QUARANTINED`, is moved to
        `RETURNED_TO_SUPPLIER` with `hold_reason` cleared to `NONE`, one
        `DRAFT` disposition record of type `RETURNED_TO_SUPPLIER` is created
        per unit under the coordinator's `recorded_by_user_id`"

        Design: Corner/errors/error_disposition_delete_draft_blocked
        """
        _, _, shipment, units = setup_received_shipment()
        get_success_data(
            api.reject_shipment(
                shipment["id"], {"rejection_reason": "Packaging integrity failure"}, COORD
            )
        )
        records = get_success_data(api.list_unit_disposition_records(units[0]["id"], CO))
        assert len(records) == 1
        assert records[0]["status"] == "DRAFT"
        resp = api.delete_disposition_record(records[0]["id"], CO)
        validate_error(resp, ApiErrorId.ERR_DISPOSITION_INVALID_STATE)

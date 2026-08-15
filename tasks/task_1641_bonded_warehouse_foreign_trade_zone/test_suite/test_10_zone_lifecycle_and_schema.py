"""Corner coverage: zone creation defaults, request schema strictness, not-found
reporting, and zone lifecycle preconditions."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    admit_admission,
    api_client,
    assert_zone,
    create_admission,
    create_zone,
    get_zone,
    is_valid_uuid,
    make_customs_officer_headers,
    make_importer_headers,
    make_zone_operator_headers,
    setup_zone_with_lot,
    submit_admission,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestZoneCreateDefaults:
    def test_zone_create_applies_system_defaults(self):
        """PRD §3.1: "A new zone starts with `status` set to `ACTIVE`,
        `compliance_posture` set to `NORMAL`, and both
        `deferred_duty_exposure_cents` and `active_lot_count` at zero."
        PRD §2.4: "`id` (string): a server-minted UUID that serves purely as the
        resource's identity"
        PRD §2.4: "`version` (integer): a system-managed integer that increments
        by one on every modification of the resource"

        Design: Corner/entities/c_zone_create_defaults
        """
        op = make_zone_operator_headers()
        resp = api_client.create_zone(
            {"name": "Prime Zone", "zone_code": "Z-PRI", "bond_coverage_cents": 5000000}, op,
        )
        data = validate_success(resp, expected_status=201)
        assert_zone(data)
        assert data["status"] == "ACTIVE"
        assert data["compliance_posture"] == "NORMAL"
        assert data["deferred_duty_exposure_cents"] == 0
        assert data["active_lot_count"] == 0
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])


class TestZoneCreateSchema:
    def test_missing_required_bond_returns_invalid_request(self):
        """PRD §2.9: "Every required field must be present, every type must be
        correct ... Any failure here yields `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "A `ZoneOperator` provisions a zone by supplying a human-readable
        `name`, an operator-assigned `zone_code` (free text carried for information
        only), and a `bond_coverage_cents` amount"

        Design: Corner/entities/c_zone_create_missing_required_returns_invalid_request
        """
        op = make_zone_operator_headers()
        resp = api_client.create_zone({"name": "No Bond Zone", "zone_code": "Z-NB"}, op)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
        _rows, meta = validate_paginated(api_client.list_zones(op))
        assert meta["total_count"] == 0, f"no zone may persist, got {meta['total_count']}"

    def test_unknown_body_field_rejected(self):
        """PRD §2.9: "Unknown fields in a body are rejected outright. Any failure
        here yields `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/c_zone_create_unknown_field_rejected
        """
        op = make_zone_operator_headers()
        resp = api_client.create_zone(
            {"name": "Sneaky Zone", "zone_code": "Z-SNK", "bond_coverage_cents": 100,
             "version": 9}, op,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestNotFoundReporting:
    def test_admission_get_not_found(self):
        """PRD §2.8: "Each unresolved identifier maps to its own error:
        `ERR_ZONE_NOT_FOUND`, `ERR_ADMISSION_NOT_FOUND`, ... all HTTP 404."

        Design: Corner/entities/c_admission_get_not_found_returns_404
        """
        op = make_zone_operator_headers()
        resp = api_client.get_admission("00000000-0000-4000-8000-0000000000aa", op)
        validate_error(resp, ApiErrorId.ERR_ADMISSION_NOT_FOUND, expected_status=404)

    def test_child_resources_report_domain_specific_404(self):
        """PRD §2.8: "Each unresolved identifier maps to its own error:
        `ERR_ZONE_NOT_FOUND`, `ERR_ADMISSION_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
        `ERR_MANIPULATION_ORDER_NOT_FOUND`, `ERR_WITHDRAWAL_NOT_FOUND`,
        `ERR_WEEKLY_ENTRY_NOT_FOUND`, `ERR_RECONCILIATION_NOT_FOUND`,
        `ERR_BADGE_NOT_FOUND`, or `ERR_ACCESS_EVENT_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/c_child_resources_not_found_return_404
        """
        op = make_zone_operator_headers()
        cases = [
            (api_client.get_lot("00000000-0000-4000-8000-000000000001", op),
             ApiErrorId.ERR_LOT_NOT_FOUND),
            (api_client.get_withdrawal("00000000-0000-4000-8000-000000000002", op),
             ApiErrorId.ERR_WITHDRAWAL_NOT_FOUND),
            (api_client.get_weekly_entry("00000000-0000-4000-8000-000000000003", op),
             ApiErrorId.ERR_WEEKLY_ENTRY_NOT_FOUND),
            (api_client.get_annual_reconciliation("00000000-0000-4000-8000-000000000004", op),
             ApiErrorId.ERR_RECONCILIATION_NOT_FOUND),
            (api_client.get_access_badge("00000000-0000-4000-8000-000000000005", op),
             ApiErrorId.ERR_BADGE_NOT_FOUND),
            (api_client.get_access_event("00000000-0000-4000-8000-000000000006", op),
             ApiErrorId.ERR_ACCESS_EVENT_NOT_FOUND),
            (api_client.get_manipulation_order("00000000-0000-4000-8000-000000000007", op),
             ApiErrorId.ERR_MANIPULATION_ORDER_NOT_FOUND),
        ]
        for resp, expected_id in cases:
            validate_error(resp, expected_id, expected_status=404)

    def test_body_fk_to_missing_zone_returns_404(self):
        """PRD §2.8: "Once path identifiers resolve, foreign keys carried in the
        request body — `zone_id`, `lot_id`, `source_lot_id`, `weekly_entry_id`, and
        `badge_id` — are validated for existence in the same fashion."

        Design: Corner/errors/c_zone_not_found_returns_404
        """
        imp = make_importer_headers("imp-1")
        resp = api_client.create_admission(
            {"zone_id": "00000000-0000-4000-8000-0000000000ff", "description": "Nowhere",
             "hts_code": "0401.10", "quantity": 1, "unit_value_cents": 100,
             "zone_status": "DOMESTIC"}, imp,
        )
        validate_error(resp, ApiErrorId.ERR_ZONE_NOT_FOUND, expected_status=404)


class TestZoneLifecyclePreconditions:
    def test_deactivate_non_empty_zone_rejected(self):
        """PRD §3.1: "Deactivation is permanent: from either `ACTIVE` or
        `SUSPENDED` the zone moves to the terminal `DEACTIVATED` state, but only
        when the zone holds no live merchandise — deactivation is rejected with
        `ERR_ZONE_NOT_EMPTY` unless the zone's `active_lot_count` is zero."

        Design: Corner/state_machines/c_zone_deactivate_non_empty_rejected
        """
        zone, _a, _lot = setup_zone_with_lot(
            quantity=5, unit_value_cents=1000, hts_code="0401.10",
            importer_id="imp-1", zone_name="NonEmpty Zone", zone_code="Z-NE",
        )
        op = make_zone_operator_headers()
        resp = api_client.transition_zone(zone["id"], {"to_status": "DEACTIVATED"}, op)
        validate_error(resp, ApiErrorId.ERR_ZONE_NOT_EMPTY, expected_status=409)
        assert get_zone(zone["id"])["status"] == "ACTIVE"

    def test_undeclared_zone_transition_rejected(self):
        """PRD §3.1: "Any request whose `to_status` is not reachable from the
        zone's current status is rejected with `ERR_ZONE_INVALID_TRANSITION`."

        Design: Corner/state_machines/c_zone_invalid_transition_rejected
        """
        zone = create_zone(bond_coverage_cents=1000000, name="Bad Trans Zone", zone_code="Z-BT")
        op = make_zone_operator_headers()
        # ACTIVE -> ACTIVE is not a declared transition.
        resp = api_client.transition_zone(zone["id"], {"to_status": "ACTIVE"}, op)
        validate_error(resp, ApiErrorId.ERR_ZONE_INVALID_TRANSITION, expected_status=409)


class TestLotsFilteredByAdmission:
    def test_lots_reverse_reachable_by_admission_id(self):
        """PRD §3.3: "lots arise only from admitted admissions and completed
        manipulation orders"
        PRD §3.2: "Admitting stamps `admission_date` from the logical clock (the
        field is null beforehand) and creates an **InventoryLot** in `IN_ZONE`
        status whose `admitted_quantity` and `quantity_on_hand` both equal the
        admission's `quantity`"
        PRD §3.3: "they change only through withdrawal filings and cancellations,
        manipulation approvals and completions, and the freeze cascade of §3.7."

        Design: Corner/entities/c_lots_filtered_by_admission_id
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Filter Zone", zone_code="Z-FLT")
        a1 = create_admission(zone["id"], importer_id="imp-1", description="Dairy A",
                              hts_code="0401.10", quantity=2, unit_value_cents=1000,
                              zone_status="NON_PRIVILEGED_FOREIGN")
        submit_admission(a1["id"], importer_id="imp-1")
        admit_admission(a1["id"])
        a2 = create_admission(zone["id"], importer_id="imp-1", description="Dairy B",
                              hts_code="0401.10", quantity=3, unit_value_cents=1000,
                              zone_status="NON_PRIVILEGED_FOREIGN")
        submit_admission(a2["id"], importer_id="imp-1")
        admit_admission(a2["id"])

        op = make_zone_operator_headers()
        rows, meta = validate_paginated(api_client.list_lots(op, params={"admission_id": a1["id"]}))
        assert meta["total_count"] == 1, f"exactly one lot for admission A1, got {meta['total_count']}"
        assert rows[0]["admission_id"] == a1["id"]

        _all, meta_all = validate_paginated(api_client.list_lots(op, params={"zone_id": zone["id"]}))
        assert meta_all["total_count"] == 2, f"two lots in the zone, got {meta_all['total_count']}"

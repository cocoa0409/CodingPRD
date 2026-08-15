"""Corner coverage for the validation cascade: auth, ownership, safety
prohibitions, temporal rules, and resource constraints."""
from test_helpers import (
    ApiErrorId,
    api_client,
    approve_manipulation_order,
    create_access_badge_payload,
    create_admission,
    create_badge,
    create_filed_withdrawal,
    create_manipulation_order,
    create_weekly_entry,
    create_withdrawal,
    create_zone,
    file_withdrawal,
    get_lot,
    get_success_data,
    make_customs_officer_headers,
    make_gate_officer_headers,
    make_importer_headers,
    make_zone_operator_headers,
    setup_zone_with_lot,
    submit_admission,
    admit_admission,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthCascadeEntry:
    def test_missing_headers_rejected_on_read(self):
        """PRD §2.1: "A request missing either header, or carrying a role value
        outside these four declared roles, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/c_missing_auth_header_returns_unauthenticated
        """
        resp = api_client.list_zones(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                       expected_status=400)


class TestExistenceBeatsStatePriority:
    def test_admit_nonexistent_admission_reports_404(self):
        """PRD §2.9: "3. **Existence.** Path identifiers are validated left to
        right, then body foreign keys, each failure surfacing the corresponding
        not-found error of §2.8." — existence runs before the state category.
        PRD §2.9: "a request that violates several rules is rejected with the error
        belonging to the earliest category, never with a list"

        Design: Corner/validations/c_existence_beats_state_priority
        """
        customs = make_customs_officer_headers()
        resp = api_client.admit_admission("00000000-0000-4000-8000-0000000000ad", customs)
        validate_error(resp, ApiErrorId.ERR_ADMISSION_NOT_FOUND, expected_status=404)


class TestReferentialBeatsFiscalPriority:
    def test_unknown_hts_beats_bond_breach(self):
        """PRD §2.9: "10. **Referential consistency with external tables and
        zones.** Tariff codes must exist and zone references must align, yielding
        `ERR_UNKNOWN_HTS_CODE` (HTTP 422) and `ERR_CROSS_ZONE_REFERENCE` (HTTP
        422)."
        PRD §2.9: "11. **Fiscal capacity.** The surety-bond ceiling is enforced
        last, yielding `ERR_BOND_CAPACITY_EXCEEDED` (HTTP 402)."
        PRD §3.3: "any admission or manipulation order citing a code outside it
        fails at the verification point with `ERR_UNKNOWN_HTS_CODE`"

        Design: Corner/validations/c_referential_beats_fiscal_priority
        """
        # Bond 100: any positive exposure breaches it, but the unknown HTS code
        # (priority 10) is evaluated before the fiscal check (priority 11).
        zone = create_zone(bond_coverage_cents=100, name="RefFiscal Zone", zone_code="Z-RF")
        a = create_admission(zone["id"], importer_id="imp-1", description="Mystery goods",
                             hts_code="9999.99", quantity=5, unit_value_cents=1000,
                             zone_status="NON_PRIVILEGED_FOREIGN")
        submit_admission(a["id"], importer_id="imp-1")
        customs = make_customs_officer_headers()
        resp = api_client.admit_admission(a["id"], customs)
        err = validate_error(resp, ApiErrorId.ERR_UNKNOWN_HTS_CODE, expected_status=422)
        assert err["error_id"] != ApiErrorId.ERR_BOND_CAPACITY_EXCEEDED


class TestOwnershipGate:
    def test_non_owner_cannot_file_withdrawal(self):
        """PRD §3.5: "Filing requires the withdrawal to be `DRAFT` (otherwise
        `ERR_WITHDRAWAL_INVALID_TRANSITION`), the caller to own it"
        PRD §2.9: "5. **Ownership.** Where a rule ties a resource to its creating
        importer, the caller's identity must match; otherwise
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/validations/c_non_owner_file_forbidden
        """
        zone, _a, lot = setup_zone_with_lot(
            quantity=5, unit_value_cents=1000, hts_code="0401.10",
            zone_status="NON_PRIVILEGED_FOREIGN", bond_coverage_cents=10_000_000_000,
            importer_id="imp-1", zone_name="Owner Zone", zone_code="Z-OWN",
        )
        w = create_withdrawal(zone["id"], lot["id"], quantity=1,
                              withdrawal_type="CONSUMPTION", importer_id="imp-1")
        other = make_importer_headers("imp-2")
        resp = api_client.file_withdrawal(w["id"], other)
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)
        w_after = get_success_data(api_client.get_withdrawal(w["id"], make_zone_operator_headers()))
        assert w_after["status"] == "DRAFT"


class TestCrossZoneReference:
    def test_withdrawal_zone_must_match_lot_zone(self):
        """PRD §2.8: "a withdrawal must name the same zone as the lot it draws
        from, a weekly entry attached to a withdrawal must belong to that same
        zone, and a gate event must name the same zone as the badge it cites. Any
        such mismatch is rejected with `ERR_CROSS_ZONE_REFERENCE` (HTTP 422)."

        Design: Corner/validations/c_cross_zone_lot_reference_rejected
        """
        za = create_zone(bond_coverage_cents=10_000_000_000, name="Zone A", zone_code="Z-A")
        zb = create_zone(bond_coverage_cents=10_000_000_000, name="Zone B", zone_code="Z-B")
        a = create_admission(zb["id"], importer_id="imp-1", description="Dairy B",
                             hts_code="0401.10", quantity=5, unit_value_cents=1000,
                             zone_status="NON_PRIVILEGED_FOREIGN")
        submit_admission(a["id"], importer_id="imp-1")
        admit_admission(a["id"])
        op = make_zone_operator_headers()
        lot = get_success_data(api_client.list_lots(op, params={"admission_id": a["id"]}))[0]

        imp = make_importer_headers("imp-1")
        resp = api_client.create_withdrawal(
            {"zone_id": za["id"], "lot_id": lot["id"], "withdrawal_type": "CONSUMPTION",
             "quantity": 1}, imp,
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_ZONE_REFERENCE, expected_status=422)
        _rows, meta = validate_paginated(
            api_client.list_withdrawals(op, params={"lot_id": lot["id"]}))
        assert meta["total_count"] == 0


class TestZoneRestrictedProhibitions:
    def test_consumption_on_zr_lot_forbidden_but_export_allowed(self):
        """PRD §3.5: "a `CONSUMPTION` withdrawal against a `ZONE_RESTRICTED` lot is
        rejected with `ERR_ZR_CONSUMPTION_FORBIDDEN`, because zone-restricted
        merchandise may only ever be exported."

        Design: Corner/validations/c_zr_consumption_rejected
        """
        zone, _a, lot = setup_zone_with_lot(
            quantity=5, unit_value_cents=1000, hts_code="0401.10",
            zone_status="ZONE_RESTRICTED", bond_coverage_cents=10_000_000_000,
            importer_id="imp-1", zone_name="ZR Zone", zone_code="Z-ZR",
        )
        imp = make_importer_headers("imp-1")
        resp = api_client.create_withdrawal(
            {"zone_id": zone["id"], "lot_id": lot["id"], "withdrawal_type": "CONSUMPTION",
             "quantity": 1}, imp,
        )
        validate_error(resp, ApiErrorId.ERR_ZR_CONSUMPTION_FORBIDDEN, expected_status=422)

        ok = validate_success(api_client.create_withdrawal(
            {"zone_id": zone["id"], "lot_id": lot["id"], "withdrawal_type": "EXPORT",
             "quantity": 1}, imp,
        ), expected_status=201)
        assert ok["status"] == "DRAFT"

    def test_manipulation_on_zr_lot_rejected_at_approval(self):
        """PRD §3.4: "the source lot's `zone_status` to be anything other than
        `ZONE_RESTRICTED`, because zone-restricted merchandise may never be
        manipulated (otherwise `ERR_MANIPULATION_NOT_PERMITTED`)"

        Design: Corner/validations/c_manipulation_on_zr_lot_rejected
        """
        zone, _a, lot = setup_zone_with_lot(
            quantity=10, unit_value_cents=1221, hts_code="8708.29",
            zone_status="ZONE_RESTRICTED", bond_coverage_cents=10_000_000_000,
            importer_id="imp-1", zone_name="ZR Manip Zone", zone_code="Z-ZRM",
        )
        m = create_manipulation_order(
            zone["id"], lot["id"], input_quantity=5, output_hts_code="9503.00",
            output_quantity=2, value_added_cents=1000, output_description="Repairs",
            importer_id="imp-1",
        )
        op = make_zone_operator_headers()
        resp = api_client.approve_manipulation_order(m["id"], op)
        validate_error(resp, ApiErrorId.ERR_MANIPULATION_NOT_PERMITTED, expected_status=422)

        m_after = get_success_data(api_client.get_manipulation_order(m["id"], op))
        assert m_after["status"] == "REQUESTED"
        assert get_lot(lot["id"])["reserved_quantity"] == 0


class TestGateSequenceAlternation:
    def test_events_strictly_alternate_starting_with_in(self):
        """PRD §3.8: "events for a given badge must strictly alternate, beginning
        with `IN`: an `IN` event is accepted only when the badge's recorded `IN`
        count equals its recorded `OUT` count, and an `OUT` event is accepted only
        when the recorded `IN` count exceeds the recorded `OUT` count by exactly
        one; any break in the alternation is rejected with
        `ERR_GATE_SEQUENCE_VIOLATION`."

        Design: Corner/validations/c_gate_sequence_alternation
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Seq Zone", zone_code="Z-SEQ")
        b = create_badge(zone["id"], holder_name="Ada Lovelace",
                         valid_from="2026-08-01T00:00:00Z", valid_until="2026-12-31T00:00:00Z")
        gate = make_gate_officer_headers()

        ok1 = validate_success(api_client.create_access_event(
            {"zone_id": zone["id"], "badge_id": b["id"], "direction": "IN",
             "occurred_at": "2026-08-10T09:00:00Z"}, gate), expected_status=201)
        assert ok1["direction"] == "IN"

        err1 = api_client.create_access_event(
            {"zone_id": zone["id"], "badge_id": b["id"], "direction": "IN",
             "occurred_at": "2026-08-10T10:00:00Z"}, gate)
        validate_error(err1, ApiErrorId.ERR_GATE_SEQUENCE_VIOLATION, expected_status=422)

        ok2 = validate_success(api_client.create_access_event(
            {"zone_id": zone["id"], "badge_id": b["id"], "direction": "OUT",
             "occurred_at": "2026-08-10T11:00:00Z"}, gate), expected_status=201)
        assert ok2["direction"] == "OUT"

        err2 = api_client.create_access_event(
            {"zone_id": zone["id"], "badge_id": b["id"], "direction": "OUT",
             "occurred_at": "2026-08-10T12:00:00Z"}, gate)
        validate_error(err2, ApiErrorId.ERR_GATE_SEQUENCE_VIOLATION, expected_status=422)

        op = make_zone_operator_headers()
        _rows, meta = validate_paginated(
            api_client.list_access_events(op, params={"badge_id": b["id"]}))
        assert meta["total_count"] == 2, f"only the alternating pair persists, got {meta['total_count']}"


class TestWithdrawalOutsideEntryWeek:
    def test_filing_outside_attached_week_rejected(self):
        """PRD §3.5: "the logical clock's current instant must fall within the
        entry's week — on or after its `week_start_date` and strictly before its
        `week_end_date` — otherwise `ERR_WITHDRAWAL_OUTSIDE_ENTRY_WEEK`."
        PRD §2.5: "At server startup the logical clock reads exactly
        2026-08-01T00:00:00Z"

        Design: Corner/validations/c_withdrawal_outside_entry_week_rejected
        """
        zone, _a, lot = setup_zone_with_lot(
            quantity=5, unit_value_cents=1000, hts_code="0401.10",
            zone_status="NON_PRIVILEGED_FOREIGN", bond_coverage_cents=10_000_000_000,
            importer_id="imp-1", zone_name="Week Zone", zone_code="Z-WK",
        )
        # Entry week [2026-08-03, 2026-08-10); the default clock 2026-08-01 precedes it.
        entry = create_weekly_entry(zone["id"], week_start_date="2026-08-03T00:00:00Z",
                                    importer_id="imp-1")
        imp = make_importer_headers("imp-1")
        w = get_success_data(api_client.create_withdrawal(
            {"zone_id": zone["id"], "lot_id": lot["id"], "withdrawal_type": "CONSUMPTION",
             "quantity": 1, "weekly_entry_id": entry["id"]}, imp,
        ))
        resp = api_client.file_withdrawal(w["id"], imp)
        validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_OUTSIDE_ENTRY_WEEK, expected_status=422)

        w_after = get_success_data(api_client.get_withdrawal(w["id"], make_zone_operator_headers()))
        assert w_after["status"] == "DRAFT"
        assert get_lot(lot["id"])["quantity_on_hand"] == 5


class TestBadgeEventOutsideWindow:
    def test_event_outside_validity_window_rejected(self):
        """PRD §3.8: "The event's `occurred_at` must fall inside the badge's closed
        validity window, on or after `valid_from` and on or before `valid_until`,
        otherwise `ERR_BADGE_WINDOW_VIOLATION`."

        Design: Corner/validations/c_badge_event_outside_window_rejected
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Window Badge Zone",
                           zone_code="Z-WB")
        b = create_badge(zone["id"], holder_name="Alan Turing",
                         valid_from="2026-08-01T00:00:00Z", valid_until="2026-08-31T00:00:00Z")
        gate = make_gate_officer_headers()
        resp = api_client.create_access_event(
            {"zone_id": zone["id"], "badge_id": b["id"], "direction": "IN",
             "occurred_at": "2026-09-01T09:00:00Z"}, gate,
        )
        validate_error(resp, ApiErrorId.ERR_BADGE_WINDOW_VIOLATION, expected_status=422)


class TestLotBusyRejected:
    def test_second_approve_on_reserved_lot_rejected(self):
        """PRD §3.4: "the lot to be free of other commitments — its
        `reserved_quantity` must be zero, so a lot already reserved under another
        approved order rejects with `ERR_LOT_BUSY`"

        Design: Corner/validations/c_lot_busy_rejected
        """
        zone, _a, lot = setup_zone_with_lot(
            quantity=100, unit_value_cents=10000, hts_code="8542.31",
            zone_status="NON_PRIVILEGED_FOREIGN", bond_coverage_cents=10_000_000_000,
            importer_id="imp-1", zone_name="Busy Zone", zone_code="Z-BSY",
        )
        m1 = create_manipulation_order(
            zone["id"], lot["id"], input_quantity=40, output_hts_code="9503.00",
            output_quantity=20, value_added_cents=50000, output_description="Kitting A",
            importer_id="imp-1",
        )
        approve_manipulation_order(m1["id"])
        m2 = create_manipulation_order(
            zone["id"], lot["id"], input_quantity=10, output_hts_code="9503.00",
            output_quantity=5, value_added_cents=10000, output_description="Kitting B",
            importer_id="imp-1",
        )
        op = make_zone_operator_headers()
        resp = api_client.approve_manipulation_order(m2["id"], op)
        validate_error(resp, ApiErrorId.ERR_LOT_BUSY, expected_status=422)
        m2_after = get_success_data(api_client.get_manipulation_order(m2["id"], op))
        assert m2_after["status"] == "REQUESTED"


class TestEntryFileEmptyRejected:
    def test_filing_entry_without_line_items_rejected(self):
        """PRD §3.6: "Filing is only meaningful with content: at least one attached
        `CONSUMPTION` withdrawal must be in `FILED` or `DUTY_PAID` status,
        otherwise `ERR_ENTRY_NO_LINE_ITEMS`."

        Design: Corner/validations/c_entry_file_empty_rejected
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Empty Zone", zone_code="Z-EMP")
        entry = create_weekly_entry(zone["id"], week_start_date="2026-07-27T00:00:00Z",
                                    importer_id="imp-1")
        imp = make_importer_headers("imp-1")
        resp = api_client.file_weekly_entry(entry["id"], imp)
        validate_error(resp, ApiErrorId.ERR_ENTRY_NO_LINE_ITEMS, expected_status=422)
        e_after = get_success_data(api_client.get_weekly_entry(entry["id"], make_zone_operator_headers()))
        assert e_after["status"] == "OPEN"


class TestBondCapacityBoundary:
    def test_bond_check_inclusive_at_equality(self):
        """PRD §3.2: "admitting is rejected with `ERR_BOND_CAPACITY_EXCEEDED` when
        the zone's current `deferred_duty_exposure_cents` plus the deferred-duty
        estimate of the lot the admission would create exceeds the zone's
        `bond_coverage_cents`, with exact equality permitted."

        Design: Corner/validations/c_bond_capacity_boundary
        """
        # Bond 250; each admission's deferred estimate: round(5 x 1000 x 0.05) = 250.
        zone = create_zone(bond_coverage_cents=250, name="Bond Zone", zone_code="Z-BND")
        a1 = create_admission(zone["id"], importer_id="imp-1", description="Dairy 1",
                              hts_code="0401.10", quantity=5, unit_value_cents=1000,
                              zone_status="NON_PRIVILEGED_FOREIGN")
        submit_admission(a1["id"], importer_id="imp-1")
        a2 = create_admission(zone["id"], importer_id="imp-1", description="Dairy 2",
                              hts_code="0401.10", quantity=5, unit_value_cents=1000,
                              zone_status="NON_PRIVILEGED_FOREIGN")
        submit_admission(a2["id"], importer_id="imp-1")

        customs = make_customs_officer_headers()
        # 250 <= 250: equality permitted.
        ok = validate_success(api_client.admit_admission(a1["id"], customs))
        assert ok["status"] == "ADMITTED"
        # 250 + 250 > 250: breach.
        resp = api_client.admit_admission(a2["id"], customs)
        validate_error(resp, ApiErrorId.ERR_BOND_CAPACITY_EXCEEDED, expected_status=402)

"""Priority-pair validation conflicts: the first failure in the fixed cascade
wins. Each scenario sets up TWO violations and asserts the earlier category's
error is reported."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_access_badge_payload,
    create_admission,
    create_zone,
    get_success_data,
    make_customs_officer_headers,
    make_gate_officer_headers,
    make_importer_headers,
    make_zone_operator_headers,
    submit_admission,
    validate_error,
    validate_paginated,
)


class TestAdmitStateErrorBeatsBondFiscal:
    """(state p6, business_fiscal p11): admission still DRAFT AND its admission
    would breach the tiny bond — the state error must win."""

    def test_draft_admit_reports_invalid_transition_not_bond(self):
        """PRD §2.9: "Every mutating request passes through a fixed validation
        cascade, and the first failure encountered wins — a request that violates
        several rules is rejected with the error belonging to the earliest
        category, never with a list."
        PRD §3.2: "If the documentation is sound, customs admits the merchandise,
        moving the admission from `SUBMITTED` to the terminal `ADMITTED` state."

        Design: Difficulty/priority_pair_validation_conflict/admit_state_error_beats_bond_fiscal
        """
        # Bond 100: admitting qty 5 @ 1000 @ rate 0.05 would add 250 > 100 (fiscal breach),
        # but the admission is still DRAFT (state breach at the earlier category).
        zone = create_zone(bond_coverage_cents=100, name="Tiny Bond Zone", zone_code="Z-TB")
        a = create_admission(zone["id"], importer_id="imp-1", description="Dairy",
                             hts_code="0401.10", quantity=5, unit_value_cents=1000,
                             zone_status="NON_PRIVILEGED_FOREIGN")
        customs = make_customs_officer_headers()
        resp = api_client.admit_admission(a["id"], customs)
        validate_error(resp, ApiErrorId.ERR_ADMISSION_INVALID_TRANSITION, expected_status=409)

    def test_state_violation_leaves_no_lot_and_draft_status(self):
        """PRD §3.2: "Admitting stamps `admission_date` from the logical clock (the
        field is null beforehand) and creates an **InventoryLot** in `IN_ZONE`
        status" — a rejected admit must create nothing.

        Design: Difficulty/priority_pair_validation_conflict/admit_state_error_beats_bond_fiscal
        """
        zone = create_zone(bond_coverage_cents=100, name="Tiny Bond Zone 2", zone_code="Z-T2")
        a = create_admission(zone["id"], importer_id="imp-1", description="Dairy",
                             hts_code="0401.10", quantity=5, unit_value_cents=1000,
                             zone_status="NON_PRIVILEGED_FOREIGN")
        customs = make_customs_officer_headers()
        resp = api_client.admit_admission(a["id"], customs)
        err = validate_error(resp, ApiErrorId.ERR_ADMISSION_INVALID_TRANSITION)
        assert err["error_id"] != ApiErrorId.ERR_BOND_CAPACITY_EXCEEDED, (
            "the fiscal check is never reached when the earlier state check fails"
        )

        op = make_zone_operator_headers()
        a_after = get_success_data(api_client.get_admission(a["id"], op))
        assert a_after["status"] == "DRAFT", f"admission must remain DRAFT, got {a_after['status']}"
        lots, meta = validate_paginated(
            api_client.list_lots(op, params={"zone_id": zone["id"]})
        )
        assert meta["total_count"] == 0, f"no lot may be created, got {meta['total_count']}"


class TestGateBadgeSafetyBeatsWindowTemporal:
    """(business_safety p7, business_temporal p8): badge REVOKED AND occurred_at
    outside its validity window — the safety error must win."""

    def _setup_revoked_badge(self):
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Gate Zone", zone_code="Z-GTE")
        op = make_zone_operator_headers()
        b = get_success_data(api_client.create_access_badge(
            create_access_badge_payload(
                zone_id=zone["id"], holder_name="Grace Hopper",
                valid_from="2026-08-01T00:00:00Z", valid_until="2026-08-31T00:00:00Z",
            ), op,
        ))
        get_success_data(api_client.transition_access_badge(b["id"], {"to_status": "REVOKED"}, op))
        return zone, b

    def test_revoked_badge_outside_window_reports_access_denied(self):
        """PRD §3.8: "The cited badge must be `ACTIVE` at recording time — a gate
        event against a suspended or revoked badge is rejected with
        `ERR_BADGE_ACCESS_DENIED`."
        PRD §2.9: "the first failure encountered wins — a request that violates
        several rules is rejected with the error belonging to the earliest
        category"

        Design: Difficulty/priority_pair_validation_conflict/gate_badge_safety_beats_window_temporal
        """
        zone, b = self._setup_revoked_badge()
        gate = make_gate_officer_headers()
        # occurred_at 2026-09-05 is ALSO outside the badge window [08-01, 08-31].
        resp = api_client.create_access_event(
            {"zone_id": zone["id"], "badge_id": b["id"], "direction": "IN",
             "occurred_at": "2026-09-05T09:00:00Z"}, gate,
        )
        validate_error(resp, ApiErrorId.ERR_BADGE_ACCESS_DENIED, expected_status=422)

    def test_safety_violation_persists_no_event(self):
        """PRD §3.8: "Every passage through the zone's gates is recorded as a
        **ZoneAccessEvent** by a `GateOfficer`" — a rejected recording persists
        nothing.

        Design: Difficulty/priority_pair_validation_conflict/gate_badge_safety_beats_window_temporal
        """
        zone, b = self._setup_revoked_badge()
        gate = make_gate_officer_headers()
        resp = api_client.create_access_event(
            {"zone_id": zone["id"], "badge_id": b["id"], "direction": "IN",
             "occurred_at": "2026-09-05T09:00:00Z"}, gate,
        )
        err = validate_error(resp, ApiErrorId.ERR_BADGE_ACCESS_DENIED)
        assert err["error_id"] != ApiErrorId.ERR_BADGE_WINDOW_VIOLATION, (
            "the temporal check is masked by the earlier safety check"
        )

        op = make_zone_operator_headers()
        _events, meta = validate_paginated(
            api_client.list_access_events(op, params={"badge_id": b["id"]})
        )
        assert meta["total_count"] == 0, f"no event may persist, got {meta['total_count']}"

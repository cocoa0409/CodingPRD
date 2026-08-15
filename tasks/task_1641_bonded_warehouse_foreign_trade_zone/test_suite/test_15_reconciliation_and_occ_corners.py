"""Corner coverage for annual reconciliation: duplicate submission guard, OCC on
the zone version, audit-hold gating of child operations, invalid transitions,
and the strictly-greater audit threshold."""
import pytest

from test_helpers import (
    ApiErrorId,
    accept_reconciliation,
    api_client,
    create_admission,
    create_annual_reconciliation_payload,
    create_reconciliation,
    create_zone,
    get_success_data,
    get_zone,
    make_customs_officer_headers,
    make_importer_headers,
    make_zone_operator_headers,
    setup_zone_with_lot,
    setup_zone_in_audit_hold,
    submit_reconciliation,
    validate_error,
    validate_success,
)


class TestReconDuplicateYearRejected:
    def test_second_create_for_submitted_year_rejected(self):
        """PRD §3.7: "What creation may not do is stack on an active filing: if a
        reconciliation for the same zone and `zone_year` is already `SUBMITTED`,
        the create is rejected with `ERR_RECONCILIATION_ALREADY_SUBMITTED` (HTTP
        409)."

        Design: Corner/errors/c_recon_duplicate_year_rejected
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Dup Zone", zone_code="Z-DUP")
        r1 = create_reconciliation(zone["id"], zone_year=2026,
                                   beginning_value_cents=0, physical_ending_value_cents=0)
        submit_reconciliation(r1["id"])

        # Fresh OCC version, but the SUBMITTED filing blocks stacking.
        op = make_zone_operator_headers()
        z = get_success_data(api_client.get_zone(zone["id"], op))
        resp = api_client.create_annual_reconciliation(
            create_annual_reconciliation_payload(
                zone_id=zone["id"], zone_year=2026, beginning_value_cents=0,
                physical_ending_value_cents=0, expected_zone_version=z["version"],
            ), op,
        )
        validate_error(resp, ApiErrorId.ERR_RECONCILIATION_ALREADY_SUBMITTED, expected_status=409)

        r1_after = get_success_data(api_client.get_annual_reconciliation(r1["id"], op))
        assert r1_after["status"] == "SUBMITTED"


class TestAuditHoldBlocksAdmit:
    def test_submit_blocked_under_audit_hold(self):
        """PRD §3.7: "From that moment until clearance, every workflow in §3 that
        declares the posture gate rejects with `ERR_ZONE_AUDIT_HOLD`."
        PRD §3.2: "requires the zone to be `ACTIVE` with posture `NORMAL`
        (otherwise `ERR_ZONE_NOT_ACTIVE` or `ERR_ZONE_AUDIT_HOLD` respectively)."

        Design: Corner/errors/c_audit_hold_blocks_admit
        """
        zone, _lot, recon = setup_zone_in_audit_hold(
            beginning_value_cents=0, physical_ending_value_cents=1000,
            admission_quantity=5, admission_unit_value_cents=1000,
            admission_hts_code="0401.10", importer_id="imp-1",
        )
        assert get_zone(zone["id"])["compliance_posture"] == "AUDIT_HOLD"

        a2 = create_admission(zone["id"], importer_id="imp-1", description="More dairy",
                              hts_code="0401.10", quantity=2, unit_value_cents=1000,
                              zone_status="NON_PRIVILEGED_FOREIGN")
        imp = make_importer_headers("imp-1")
        resp = api_client.submit_admission(a2["id"], imp)
        validate_error(resp, ApiErrorId.ERR_ZONE_AUDIT_HOLD, expected_status=409)
        a2_after = get_success_data(api_client.get_admission(a2["id"], make_zone_operator_headers()))
        assert a2_after["status"] == "DRAFT"


class TestAcceptDraftReconRejected:
    def test_accept_draft_rejected(self):
        """PRD §3.7: "A `CustomsOfficer` accepts a `SUBMITTED` reconciliation,
        moving it to the terminal `ACCEPTED` state; acting on a reconciliation in
        any other status yields `ERR_RECONCILIATION_INVALID_TRANSITION`."

        Design: Corner/errors/c_accept_draft_recon_rejected
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Draft Recon Zone",
                           zone_code="Z-DR")
        r = create_reconciliation(zone["id"], zone_year=2026,
                                  beginning_value_cents=0, physical_ending_value_cents=0)
        customs = make_customs_officer_headers()
        resp = api_client.accept_annual_reconciliation(r["id"], customs)
        validate_error(resp, ApiErrorId.ERR_RECONCILIATION_INVALID_TRANSITION, expected_status=409)
        r_after = get_success_data(
            api_client.get_annual_reconciliation(r["id"], make_zone_operator_headers()))
        assert r_after["status"] == "DRAFT"


class TestOccStaleZoneVersion:
    def test_stale_version_rejected_then_fresh_create_supersedes(self):
        """PRD §2.7: "If the zone's current `version` does not equal the supplied
        `expected_zone_version`, the create is rejected with
        `ERR_STALE_ZONE_VERSION` (HTTP 412)"
        PRD §3.7: "creating a reconciliation for a zone-year that already has a
        `DRAFT` reconciliation legitimately supersedes that draft — the older draft
        moves silently to `SUPERSEDED`"
        PRD §3.7: "A successful create also increments the zone's `version` by
        one."

        Design: Corner/cross_cutting_layers/c_occ_stale_zone_version_rejected
        """
        op = make_zone_operator_headers()
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="OCC Zone", zone_code="Z-OCC")
        zv1 = zone["version"]
        r1 = create_reconciliation(zone["id"], zone_year=2026,
                                   beginning_value_cents=0, physical_ending_value_cents=0)
        # The successful create bumped the zone version; zv1 is now stale.
        z_now = get_zone(zone["id"])
        assert z_now["version"] == zv1 + 1

        stale = api_client.create_annual_reconciliation(
            create_annual_reconciliation_payload(
                zone_id=zone["id"], zone_year=2026, beginning_value_cents=10,
                physical_ending_value_cents=10, expected_zone_version=zv1,
            ), op,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_ZONE_VERSION, expected_status=412)

        fresh = validate_success(api_client.create_annual_reconciliation(
            create_annual_reconciliation_payload(
                zone_id=zone["id"], zone_year=2026, beginning_value_cents=10,
                physical_ending_value_cents=10, expected_zone_version=z_now["version"],
            ), op,
        ), expected_status=201)
        assert fresh["status"] == "DRAFT"

        r1_after = get_success_data(api_client.get_annual_reconciliation(r1["id"], op))
        assert r1_after["status"] == "SUPERSEDED", (
            f"prior DRAFT must be superseded, got {r1_after['status']}"
        )


class TestAuditThresholdExactHalfPct:
    def test_exactly_half_pct_does_not_flag_but_above_does(self):
        """PRD §3.7: "The reconciliation is `audit_flagged` when that percentage is
        strictly greater than one-half of one percent — a variance of exactly 0.5
        does not flag."
        PRD §3.7: "The zone's `compliance_posture` moves from `NORMAL` to
        `AUDIT_HOLD`." (only when flagged)

        Design: Corner/cross_cutting_layers/c_audit_threshold_exact_half_pct
        """
        op = make_zone_operator_headers()
        # Zone A: no activity; beginning 200000, physical 201000 -> |1000|/200000*100 = 0.5 exactly.
        za = create_zone(bond_coverage_cents=10_000_000_000, name="Half Pct A", zone_code="Z-HPA")
        ra = create_reconciliation(za["id"], zone_year=2026,
                                   beginning_value_cents=200000, physical_ending_value_cents=201000)
        data_a = submit_reconciliation(ra["id"])
        assert data_a["discrepancy_pct"] == pytest.approx(0.5, abs=1e-9), (
            f"exactly 0.5, got {data_a['discrepancy_pct']}"
        )
        assert data_a["audit_flagged"] is False, "exactly at threshold does NOT flag"
        assert get_zone(za["id"])["compliance_posture"] == "NORMAL"

        # Zone B: physical 201010 -> 1010/200000*100 = 0.505 > 0.5 -> flags.
        zb = create_zone(bond_coverage_cents=10_000_000_000, name="Half Pct B", zone_code="Z-HPB")
        rb = create_reconciliation(zb["id"], zone_year=2026,
                                   beginning_value_cents=200000, physical_ending_value_cents=201010)
        data_b = submit_reconciliation(rb["id"])
        assert data_b["discrepancy_pct"] == pytest.approx(0.505, abs=1e-9), (
            f"0.505, got {data_b['discrepancy_pct']}"
        )
        assert data_b["audit_flagged"] is True
        assert get_zone(zb["id"])["compliance_posture"] == "AUDIT_HOLD"

"""Corner coverage for role-based access control: exclusive write surfaces and
shared reads."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_admission,
    create_badge,
    create_weekly_entry,
    create_zone,
    get_success_data,
    make_customs_officer_headers,
    make_gate_officer_headers,
    make_importer_headers,
    make_zone_operator_headers,
    submit_admission,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRbacDenials:
    def test_importer_cannot_admit(self):
        """PRD §3.2: "Customs review is a two-outcome gate operated by a
        `CustomsOfficer`."
        PRD §2.1: "A request whose role is not listed among the roles authorized
        for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: "POST /zones/admissions/{admissionId}/admit ... CustomsOfficer"

        Design: Corner/rbac/c_importer_cannot_admit
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="RBAC Zone 1", zone_code="Z-R1")
        a = create_admission(zone["id"], importer_id="imp-1", description="Dairy",
                             hts_code="0401.10", quantity=5, unit_value_cents=1000,
                             zone_status="NON_PRIVILEGED_FOREIGN")
        submit_admission(a["id"], importer_id="imp-1")

        imp = make_importer_headers("imp-1")
        resp = api_client.admit_admission(a["id"], imp)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)
        a_after = get_success_data(api_client.get_admission(a["id"], make_zone_operator_headers()))
        assert a_after["status"] == "SUBMITTED"

    def test_customs_officer_cannot_create_zone(self):
        """PRD §3.1: "A `ZoneOperator` provisions a zone by supplying a
        human-readable `name` ..."
        PRD §2.1: "A request whose role is not listed among the roles authorized
        for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: "POST /zones ... ZoneOperator"

        Design: Corner/rbac/c_officer_cannot_create_zone
        """
        customs = make_customs_officer_headers()
        resp = api_client.create_zone(
            {"name": "Officer Zone", "zone_code": "Z-OFF", "bond_coverage_cents": 1000}, customs,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    def test_gate_officer_cannot_issue_badge(self):
        """PRD §3.8: "Physical access to the zone is controlled through
        **AccessBadge** records issued by the `ZoneOperator`."
        PRD §2.1: "A request whose role is not listed among the roles authorized
        for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: "POST /zones/access-badges ... ZoneOperator"

        Design: Corner/rbac/c_gate_officer_cannot_issue_badge
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="RBAC Badge Zone",
                           zone_code="Z-RB")
        gate = make_gate_officer_headers()
        resp = api_client.create_access_badge(
            {"zone_id": zone["id"], "holder_name": "Gate Keeper",
             "valid_from": "2026-08-01T00:00:00Z", "valid_until": "2026-12-31T00:00:00Z"}, gate,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    def test_customs_officer_cannot_file_weekly_entry(self):
        """PRD §3.6: "Filing the entry is the owning importer's act"
        PRD §2.1: "A request whose role is not listed among the roles authorized
        for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: "POST /zones/weekly-entries/{entryId}/file ... Importer"

        Design: Corner/rbac/c_officer_cannot_file_weekly_entry
        """
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="RBAC Entry Zone",
                           zone_code="Z-RE")
        entry = create_weekly_entry(zone["id"], week_start_date="2026-07-27T00:00:00Z",
                                    importer_id="imp-1")
        customs = make_customs_officer_headers()
        resp = api_client.file_weekly_entry(entry["id"], customs)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)


class TestRbacSharedReads:
    def test_gate_officer_shared_reads(self):
        """PRD §3.1: "Listing zones and reading a single zone are available to all
        four roles."
        PRD §2.1: "The system recognizes exactly four roles: `ZoneOperator`,
        `Importer`, `CustomsOfficer`, and `GateOfficer`."

        Design: Corner/rbac/c_gate_officer_shared_reads
        """
        zone = create_zone(bond_coverage_cents=1000000, name="Shared Zone", zone_code="Z-SHR")
        gate = make_gate_officer_headers()
        _rows, meta = validate_paginated(api_client.list_zones(gate))
        assert meta["total_count"] == 1
        data = validate_success(api_client.get_zone(zone["id"], gate))
        assert data["name"] == "Shared Zone"

"""Cross-entity state gates: FamilyAgreement gates assignment creation
(PRD §3.2/§3.4) and AuditSweep unaccounted flag gates write-off (PRD §3.9)."""

from test_helpers import (
    ApiErrorId,
    create_assignment_payload,
    enroll_student,
    make_family_headers,
    refresh_student,
    setup_closed_sweep,
    setup_program_fleet_assets,
    setup_retired_unit,
    validate_error,
    TEST_USERS,
)

REGISTRAR = TEST_USERS["registrar_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestAssignmentGatedByFamilyAgreement:
    def test_assignment_rejected_while_agreement_pending(self, api):
        """PRD §3.4: "The family agreement must be `SIGNED` (`ERR_AGREEMENT_NOT_SIGNED`)."

        The FamilyAgreement is auto-created in PENDING at enrollment; until a
        guardian signs it, assignment creation is rejected.

        Design: Difficulty/cross_entity_state_dependency/assignment_create_gated_by_family_agreement
        """
        program, fleet, assets = setup_program_fleet_assets(n_assets=1)
        student = enroll_student(program["id"], "SIS-X-1", "Pending Agreement")
        payload = create_assignment_payload(assets[0]["id"], student["version"])
        res = api.create_assignment(program["id"], student["id"], payload, REGISTRAR)
        validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_SIGNED)
        assignments = api.list_assignments(program["id"], student["id"], REGISTRAR)
        assert assignments.json()["data"] == [], "No assignment may be created"

    def test_assignment_rejected_after_agreement_declined(self, api):
        """PRD §3.2: "Declining moves the agreement `PENDING → DECLINED` and flips the account's flag to `DECLINED`, after which the student cannot receive new assignments until a fresh agreement is signed."

        Design: Difficulty/cross_entity_state_dependency/assignment_create_gated_by_family_agreement
        """
        program, fleet, assets = setup_program_fleet_assets(n_assets=1)
        student = enroll_student(program["id"], "SIS-X-2", "Declining")
        res_decline = api.decline_family_agreement(
            program["id"], student["id"], make_family_headers(student["id"])
        )
        assert res_decline.status_code == 200, res_decline.text
        student = refresh_student(program["id"], student["id"])
        assert student["family_agreement_status"] == "DECLINED"
        payload = create_assignment_payload(assets[0]["id"], student["version"])
        res = api.create_assignment(program["id"], student["id"], payload, REGISTRAR)
        validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_SIGNED)


class TestWriteOffGatedByAuditSweep:
    def test_write_off_without_any_audit_flag_rejected(self, api, admin_headers):
        """PRD §3.9: "Write-off is the audit-driven exit: it requires the unit to have been flagged unaccounted in a `CLOSED` audit sweep, else `ERR_NOT_UNACCOUNTED`, and it forces the `depreciated_value_cents` to zero while appending `WRITE_OFF`."

        No audit sweep ever ran, so the retired unit is not flagged and the
        write-off is rejected.

        Design: Difficulty/cross_entity_state_dependency/write_off_gated_by_audit_sweep_unaccounted_flag
        """
        program, fleet, retired = setup_retired_unit()
        assert retired["lifecycle_status"] == "END_OF_LIFE"
        res = api.write_off_asset_unit(program["id"], retired["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_UNACCOUNTED)

    def test_write_off_rejected_when_closed_sweep_did_not_flag_unit(self, api,
                                                                    admin_headers):
        """PRD §3.9: "it requires the unit to have been flagged unaccounted in a `CLOSED` audit sweep, else `ERR_NOT_UNACCOUNTED`".

        A sweep that ran to CLOSED with every expected unit scanned flagged
        nobody; the retired unit still is not unaccounted, so write-off is
        rejected even though a CLOSED sweep exists.

        Design: Difficulty/cross_entity_state_dependency/write_off_gated_by_audit_sweep_unaccounted_flag
        """
        program, fleet, retired = setup_retired_unit()
        sweep = setup_closed_sweep(program, [retired["asset_tag_barcode"]])
        assert sweep["status"] == "CLOSED"
        assert sweep["unaccounted_count"] == 0
        res = api.write_off_asset_unit(program["id"], retired["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_UNACCOUNTED)

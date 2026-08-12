"""Master data creation rules, lookup errors, auth headers, and RBAC denials."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID, build_user_headers,
    create_allergen_payload, create_product_payload, create_production_run_payload,
    create_production_line_payload, create_matrix_entry_payload,
    create_changeover_procedure_payload,
    create_allergen, create_line, create_product, create_technician,
    create_incident_ok, drive_incident_to_contained,
    assert_allergen,
    make_qa_technician_headers, make_auditor_headers,
    TEST_USERS,
)

MANAGER = TEST_USERS["qa_manager_headers"]
SUPERVISOR = TEST_USERS["qa_supervisor_headers"]


class TestAllergenCreation:
    def test_allergen_create_applies_is_active_default(self, api):
        """PRD §3.1: "Each allergen also carries an `is_active` flag, defaulting
        to true, which soft-disables the allergen: an inactive allergen cannot
        be newly mapped anywhere."
        PRD §2.6: "All resources in this API — allergens, production lines,
        products, matrix entries, production runs, changeovers, changeover
        procedures, swab results, technicians, label reconciliations, rework
        batches, incidents, and audit findings — carry a standard set of
        system-managed fields".

        Design: Corner/entities/allergen_create_success_and_defaults
        """
        res = api.create_allergen(
            create_allergen_payload(code="PEANUT", display_name="Peanut",
                                    regulatory_class="MAJOR_9"),
            MANAGER)
        allergen = validate_success(res, 201)
        assert_allergen(allergen)
        assert allergen["is_active"] is True, "is_active must default to true"
        assert allergen["code"] == "PEANUT"


class TestProductCreation:
    def test_product_create_missing_sku_rejected(self, api):
        """PRD §3.2: "A `QaManager` registers each **product** with a unique
        `sku`, a commercial `product_name`, and the `allergen_set`".
        PRD §2.8: "Malformed payloads, missing required fields, and values
        outside their permitted ranges fail schema validation with
        `ERR_INVALID_REQUEST` (HTTP 400) wherever they occur."

        Design: Corner/entities/product_create_missing_required_sku_rejected
        """
        payload = {"product_name": "No SKU", "allergen_set": [], "rework_class": "NO_REWORK"}
        res = api.create_product(payload, MANAGER)
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_product_get_not_found(self, api):
        """PRD §2.8: "A request that names a non-existent identifier is rejected
        with `ERR_NOT_FOUND` (HTTP 404) at the *first* unresolved identifier in
        the path, before any later identifier is examined."

        Design: Corner/entities/product_get_not_found_returns_404
        """
        res = api.get_product(NON_EXISTENT_UUID, MANAGER)
        validate_error(res, "ERR_NOT_FOUND")


class TestProductionRunCreation:
    def test_run_create_with_equal_start_end_rejected(self, api):
        """PRD §3.4: "The planned end must be strictly later than the planned
        start, failing with `ERR_INVALID_TIME_RANGE` (HTTP 400) otherwise."

        Design: Corner/entities/production_run_invalid_time_range_rejected
        """
        line = create_line("LINE-T1", "ALLERGEN_DEDICATED")
        product = create_product("P-T1", [])
        res = api.create_production_run(
            create_production_run_payload(
                line["id"], product["id"],
                planned_start_utc="2026-06-01T12:00:00Z",
                planned_end_utc="2026-06-01T12:00:00Z"),
            SUPERVISOR)
        validate_error(res, "ERR_INVALID_TIME_RANGE")


class TestMatrixEntryReferentialIntegrity:
    def test_matrix_entry_with_inactive_allergen_rejected(self, api):
        """PRD §3.1: "Referential integrity is enforced at write time: a matrix
        entry that references an allergen whose `is_active` is false is rejected
        with `ERR_ALLERGEN_INACTIVE` (HTTP 422)".

        Design: Corner/entities/line_allergen_matrix_inactive_allergen_rejected
        """
        allergen = create_allergen("OLD", regulatory_class="OTHER", is_active=False)
        line = create_line("LINE-T2", "WET_WASH")
        res = api.create_matrix_entry(
            create_matrix_entry_payload(line["id"], allergen["id"], handling="ALLOWED"),
            MANAGER)
        validate_error(res, "ERR_ALLERGEN_INACTIVE")


class TestAuthHeaders:
    def test_missing_user_context_headers_rejected(self, api):
        """PRD §2.1: "A request with missing or malformed headers is rejected
        with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/auth_missing_headers_rejected
        """
        # Positive control: the endpoint answers 200 with proper role headers.
        ok_res = api.list_allergens(MANAGER)
        data, meta = validate_paginated(ok_res)
        assert isinstance(data, list)

        # Missing identity headers entirely.
        res = api.list_allergens(headers={})
        validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


class TestRbacDenials:
    def test_line_operator_cannot_create_allergen(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403), regardless
        of how otherwise valid the request may be."
        PRD §4: POST /qa/allergens is authorized for QaManager only.

        Design: Corner/rbac/line_operator_cannot_create_allergen
        """
        res = api.create_allergen(
            create_allergen_payload(code="X", display_name="x", regulatory_class="OTHER"),
            TEST_USERS["line_operator_headers"])
        validate_error(res, "ERR_UNAUTHORIZED_ROLE")

    def test_qa_technician_cannot_close_incident(self, api):
        """PRD §3.8: "Closure is reserved for a `QaManager`, moving `CONTAINED`
        → `CLOSED`."
        PRD §4: POST /qa/incidents/{incidentId}/close is authorized for
        QaManager only, so a QaTechnician caller is rejected with
        ERR_UNAUTHORIZED_ROLE.

        Design: Corner/rbac/qa_technician_cannot_close_incident
        """
        incident = create_incident_ok("LABEL_MISMATCH", "LOW", description="t")
        drive_incident_to_contained(incident["id"])
        allergen = create_allergen("MILK")
        tech = create_technician("TECH-R2", [allergen["id"]])
        res = api.close_incident(
            incident["id"], {"root_cause": "x"}, make_qa_technician_headers(tech["id"]))
        validate_error(res, "ERR_UNAUTHORIZED_ROLE")

    def test_qa_supervisor_cannot_approve_procedure(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403), regardless
        of how otherwise valid the request may be."
        PRD §4: POST /qa/changeover-procedures/{procedureId}/approve lists
        QaManager as its only authorized role.

        Design: Corner/rbac/qa_supervisor_cannot_approve_procedure
        """
        allergen = create_allergen("MILK")
        proc_res = api.create_changeover_procedure(
            create_changeover_procedure_payload(allergen["id"], procedure_code="COP-R3"),
            MANAGER)
        proc = validate_success(proc_res, 201)
        res = api.approve_procedure(
            proc["id"], {"expected_procedure_version": proc["version"]}, SUPERVISOR)
        validate_error(res, "ERR_UNAUTHORIZED_ROLE")


class TestAuditorAllows:
    def test_auditor_creates_finding_and_lists_technicians(self, api):
        """PRD §4: POST /qa/audit-findings is authorized for Auditor, and
        GET /qa/technicians is authorized for QaManager, QaSupervisor, Auditor.
        PRD §3.9: "An `Auditor` records a finding against a technician by
        supplying the `technician_id` audited, the `auditor_id` performing the
        audit, a `finding_type` of `PROCEDURE_DEVIATION`, `DOCUMENTATION_GAP`,
        `TRAINING_DEFICIENCY`, `SWAB_TECHNIQUE`, or `LABEL_CONTROL`, a
        `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, and the
        `corrective_action_due_utc` deadline."

        Design: Corner/rbac/auditor_can_create_finding_and_read_techs
        """
        allergen = create_allergen("MILK")
        auditee = create_technician("TECH-R4A", [allergen["id"]])
        auditor = create_technician("TECH-R4B", [allergen["id"]])

        finding_res = api.create_audit_finding(
            {"technician_id": auditee["id"], "auditor_id": auditor["id"],
             "finding_type": "DOCUMENTATION_GAP", "severity": "MINOR",
             "corrective_action_due_utc": "2026-12-01T00:00:00Z"},
            make_auditor_headers(auditor["id"]))
        finding = validate_success(finding_res, 201)
        assert finding["status"] == "OPEN"

        list_res = api.list_technicians(make_auditor_headers(auditor["id"]))
        techs, meta = validate_paginated(list_res)
        assert auditee["id"] in [t["id"] for t in techs]

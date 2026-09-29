"""The endpoint role matrix, checked from the outside by roles that hold nothing."""
from test_helpers import (
    NON_EXISTENT_UUID,
    fixtures as fx,
    validate_error,
    validate_paginated,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    change_order_payload,
    disclosure_response_payload,
    field_event_payload,
    nfa_letter_payload,
    permit_decision_payload,
    property_payload,
    result_payload,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    FIELD_TECHNICIAN,
    LSP_DRAFTER,
    PROJECT_COORDINATOR,
)

#: Codes that a later rung of the ladder would have produced had the role gate
#: not answered first.
LATER_RUNG_CODES = (
    ApiErrorId.ERR_TANK_PROJECT_NOT_FOUND,
    ApiErrorId.ERR_WORK_ORDER_NOT_FOUND,
    ApiErrorId.ERR_SOIL_SAMPLE_NOT_FOUND,
    ApiErrorId.ERR_DISCLOSURE_NOT_FOUND,
    ApiErrorId.ERR_PERMIT_NOT_FOUND,
    ApiErrorId.ERR_INVALID_REQUEST,
)


class TestRoleExclusiveOperations:
    def test_each_role_exclusive_write_is_refused_to_every_other_role(self, api):
        """PRD §2.1: "If both headers are well formed but the named role does not appear in the authorized-role list for the endpoint being addressed (see §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD §2.1: "The `ProjectCoordinator` is the contractor-side operator: they intake sites, record sweep surveys, send homeowner disclosures, file permits, register crews, schedule field work and drive the billing dimension of a work order. The `FieldTechnician` is a crew member who executes field events and collects soil aliquots but may never report or retract a laboratory result. The `LicensedSiteProfessional` is the licensed environmental professional who scopes remediation change orders and drafts and signs no-further-action letters. The `ComplianceOfficer` is the regulatory operator who renders permit decisions, registers laboratories, decides change orders, administers trust-fund claims, notifies insurance carriers and rescinds no-further-action letters; a `ComplianceOfficer` may neither draft nor issue a closure letter, may not perform field work, and may not report laboratory results."
        PRD §2.11: "2. **Endpoint role authorization** — `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint."
        PRD §2.11: "4. **Path identifier resolution, left to right** — the entity-specific 404 from §2.6. Applies to every endpoint that carries an identifier in its path."

        Design: Corner/rbac/every_role_exclusive_operation_is_forbidden_to_non_holders
        """
        ctx = fx.project_at_intake()
        project = ctx["project"]
        opening_version = project["version"]

        attempts = [
            (
                "site intake belongs to the coordinator",
                api.create_property(
                    property_payload(street_address="41 Corner Way"), FIELD_TECHNICIAN
                ),
            ),
            (
                "field events belong to the technician",
                api.create_field_event(
                    NON_EXISTENT_UUID,
                    field_event_payload("MOBILIZE"),
                    PROJECT_COORDINATOR,
                ),
            ),
            (
                "result reporting belongs to the laboratory",
                api.report_result(
                    NON_EXISTENT_UUID, result_payload(120.0, 0.05), FIELD_TECHNICIAN
                ),
            ),
            (
                "answering a notice belongs to the homeowner",
                api.respond_to_disclosure(
                    NON_EXISTENT_UUID,
                    disclosure_response_payload(),
                    PROJECT_COORDINATOR,
                ),
            ),
            (
                "drafting a closure letter belongs to the site professional",
                api.create_nfa_letter(
                    nfa_letter_payload(NON_EXISTENT_UUID), COMPLIANCE_OFFICER
                ),
            ),
            (
                "permit decisions belong to the compliance officer",
                api.decide_permit(
                    NON_EXISTENT_UUID, permit_decision_payload("ISSUED"), LSP_DRAFTER
                ),
            ),
            (
                "scoping a change order belongs to the site professional",
                api.create_change_order(
                    change_order_payload(
                        project["id"],
                        opening_version,
                        additional_cubic_yards=2.0,
                        unit_rate_cents=1000,
                    ),
                    COMPLIANCE_OFFICER,
                ),
            ),
        ]

        for reason, response in attempts:
            error_id = validate_error(
                response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403
            )["error_id"]
            for later in LATER_RUNG_CODES:
                assert error_id != later.value, (
                    f"{reason}, and the role gate answers before the existence and "
                    f"shape checks, so {later.value} must never surface, got {error_id}"
                )

        _, project_meta = validate_paginated(
            api.list_tank_projects(
                PROJECT_COORDINATOR, params={"property_id": ctx["property"]["id"]}
            )
        )
        assert project_meta["total_count"] == 1, (
            "the forbidden intake attempt registered nothing, so only the fixture "
            f"project stands, got {project_meta['total_count']}"
        )

        assert fx.project_version(project["id"]) == opening_version, (
            "the refused change-order create never touched the project, so its "
            f"version is unchanged from {opening_version}"
        )

        _, change_order_meta = validate_paginated(
            api.list_change_orders(
                COMPLIANCE_OFFICER, params={"tank_project_id": project["id"]}
            )
        )
        assert change_order_meta["total_count"] == 0, (
            "no change order was written by the forbidden scoping attempt, got "
            f"{change_order_meta['total_count']}"
        )

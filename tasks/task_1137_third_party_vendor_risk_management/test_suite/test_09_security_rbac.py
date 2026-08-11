"""RBAC enforcement across roles and the vendor-side OCC guard."""
from test_helpers import (
    ApiErrorId,
    create_board_report_payload,
    create_dd_package,
    create_engagement,
    create_vendor,
    file_incident,
    get_engagement,
    get_vendor,
    reset_clock,
    setup_active_engagement,
    submit_dd_package,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import VRM, RO, BUO, AUDITOR, DIRECTOR


class TestRoleEnforcement:
    def test_compliance_director_cannot_create_vendor(self, api):
        """PRD §2.1: "If the role identified by `X-User-Role` is not authorized
        for the target endpoint per §4, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /tprm/vendors — "Create a vendor in `ONBOARDING` with
        initial tier `TIER_3_STANDARD`. | VendorRelationshipManager"

        Design: Corner/validations/wrong_role_returns_403
        """
        reset_clock()
        res = api.create_vendor(
            {"legal_name": "X", "headquarters_region": "NA", "service_category": "BPO"},
            DIRECTOR,
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_internal_auditor_cannot_create_vendor(self, api):
        """PRD §2.1: "If the role identified by `X-User-Role` is not authorized
        for the target endpoint per §4, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /tprm/vendors — "Create a vendor in `ONBOARDING` with
        initial tier `TIER_3_STANDARD`. | VendorRelationshipManager"

        Design: Corner/roles/internal_auditor_cannot_create_vendor
        """
        reset_clock()
        res = api.create_vendor(
            {"legal_name": "X", "headquarters_region": "NA", "service_category": "BPO"},
            AUDITOR,
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_business_unit_owner_cannot_approve_dd(self, api):
        """PRD §2.1: "If the role identified by `X-User-Role` is not authorized
        for the target endpoint per §4, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /tprm/due-diligence-packages/{id}/approve — "Transition
        package `UNDER_REVIEW → APPROVED`; SoD and OCC guarded. | RiskOfficer"

        Design: Corner/roles/business_unit_owner_cannot_approve_dd
        """
        reset_clock()
        vendor = create_vendor(name="RBAC1")
        engagement = create_engagement(vendor["id"], code="RB1-E1", sensitivity="PUBLIC", spend=100)
        package = create_dd_package(engagement["id"], reviewer_tag="rb1")
        submit_dd_package(package["id"])
        validate_success(api.begin_review_dd_package(package["id"], RO), 200)
        current = get_engagement(engagement["id"])

        res = api.approve_dd_package(
            package["id"], {"expected_engagement_version": current["version"]}, BUO
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_compliance_director_cannot_triage_incident(self, api):
        """PRD §2.1: "If the role identified by `X-User-Role` is not authorized
        for the target endpoint per §4, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /tprm/incidents/{id}/triage — "Transition incident `OPEN →
        TRIAGED`; computes `remediation_due_at`. | RiskOfficer"

        Design: Corner/roles/compliance_director_cannot_triage_incident
        """
        ctx = setup_active_engagement(vendor_name="RBAC2")
        incident = file_incident(
            ctx["engagement"]["id"], severity="SEV_3", detected_at="2026-05-02T00:00:00Z"
        )
        res = api.triage_incident(incident["id"], DIRECTOR)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_vrm_cannot_publish_board_report(self, api):
        """PRD §2.1: "If the role identified by `X-User-Role` is not authorized
        for the target endpoint per §4, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /tprm/board-reports/{id}/publish — "Transition report
        `DRAFT → PUBLISHED`; computes `snapshot_payload`. | ComplianceDirector"

        Design: Corner/roles/vendor_relationship_manager_cannot_publish_board_report
        """
        reset_clock()
        report = validate_success(
            api.create_board_report(
                create_board_report_payload(
                    period_start="2026-04-01T00:00:00Z", period_end="2026-05-01T00:00:00Z"
                ),
                DIRECTOR,
            ),
            201,
        )
        res = api.publish_board_report(report["id"], VRM)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)


class TestVendorTierChangeOcc:
    def test_stale_vendor_version_rejected_on_tier_change(self, api):
        """PRD §3.11: "A `RiskOfficer` changes a vendor's `criticality_tier` by
        supplying `to_tier`, a free-text `reason`, and
        `expected_vendor_version` carrying the officer's last observed
        `version` of the vendor. A mismatch against the current `version` is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.7: "If the value does not match the parent entity's current
        `version`, the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412), protecting the client from overwriting changes it has not
        observed."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_tier_change
        """
        reset_clock()
        vendor = create_vendor(name="OccT")
        current = get_vendor(vendor["id"])
        res = api.tier_change_vendor(
            vendor["id"],
            {
                "to_tier": "TIER_1_CRITICAL",
                "reason": "x",
                "expected_vendor_version": current["version"] - 1,
            },
            RO,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)

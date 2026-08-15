"""Role-based access control: role gates, entity-backed ownership, and
assignment checks (PRD §2.1)."""
from test_helpers import (
    ApiErrorId,
    create_chargeback_payload,
    make_billing_clerk_headers,
    make_compliance_officer_headers,
    make_resident_headers,
    make_technician_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    MANAGER,
    assess_chargeback,
    create_lease,
    create_resident,
    create_unit,
    dispute_chargeback,
    schedule_inspection,
    setup_community,
    setup_prep_notified_treatment,
)


class TestRoleDenials:
    def test_resident_cannot_assess_chargeback_returns_403(self, api):
        """PRD §2.1: "When the role is legitimate but not authorized for the
        endpoint — or when an entity-backed ownership check fails — the request
        is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.1: "A `BillingClerk` is the fiscal operator who assesses,
        bills, and collects chargebacks; its `X-User-ID` is an opaque
        identifier, recorded as the assessor on each chargeback it creates."

        Design: Corner/rbac/resident_cannot_assess_chargeback_returns_403
        """
        ctx = setup_community(contract_overrides={"scope_pest_types": ["ROACHES"]})
        resp = api.create_chargeback(
            ctx["lease"]["id"],
            create_chargeback_payload(),
            make_resident_headers(ctx["resident"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_billing_clerk_cannot_resolve_dispute_returns_403(self, api):
        """PRD §2.1: "A `BillingClerk` is the fiscal operator who assesses,
        bills, and collects chargebacks; its `X-User-ID` is an opaque
        identifier, recorded as the assessor on each chargeback it creates. By
        design it is barred from resolving disputes."

        Design: Corner/rbac/billing_clerk_cannot_resolve_dispute_returns_403
        """
        ctx = setup_community(contract_overrides={"scope_pest_types": ["ROACHES"]})
        cb = assess_chargeback(ctx["lease"]["id"])
        disputed = dispute_chargeback(cb["id"], ctx["resident"])
        resp = api.resolve_dispute(
            cb["id"],
            {"resolution": "UPHELD", "expected_chargeback_version": disputed["version"]},
            make_billing_clerk_headers("clerk-2"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_technician_cannot_verify_prep_returns_403(self, api):
        """PRD §2.1: "When `X-User-Role` is `Technician`, `X-User-ID` is the
        `id` of the acting `Technician` record; assignment checks on any
        resource that references a technician compare the resource's
        `technician_id` field to `X-User-ID`. A technician acts only on records
        assigned to them."
        PRD §3.4: "Finally the `PropertyManager` verifies preparation,
        passing `compliant` and optionally `notes`."

        Design: Corner/rbac/technician_cannot_verify_prep_returns_403
        """
        ctx = setup_community(with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        tr = setup_prep_notified_treatment(ctx["unit"]["id"], ctx["technician"]["id"])
        resp = api.verify_prep(
            tr["id"], {"compliant": True}, make_technician_headers(ctx["technician"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_compliance_officer_cannot_bill_returns_403(self, api):
        """PRD §2.1: "A `ComplianceOfficer` adjudicates disputes and assembles
        and finalizes habitability claim packets; its `X-User-ID` is an opaque
        identifier, recorded as the resolver on each dispute it decides. It is
        barred from assessing or billing chargebacks."

        Design: Corner/rbac/compliance_officer_cannot_bill_returns_403
        """
        ctx = setup_community(with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        cb = assess_chargeback(ctx["lease"]["id"])
        resp = api.bill_chargeback(cb["id"], make_compliance_officer_headers("officer-9"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestEntityBackedOwnership:
    def test_resident_reading_other_unit_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `Resident`, `X-User-ID` is the `id`
        of the acting `Resident` record; ownership checks compare the
        resident's `unit_id` (and, for chargeback actions, the resident's
        `lease_id`) against the target resource's scoping fields. A resident
        acts only on records of their own unit and lease."

        Design: Corner/rbac/resident_reading_other_unit_forbidden
        """
        ctx = setup_community(contract_overrides={"scope_pest_types": ["ROACHES"]})
        u2 = create_unit(ctx["property"]["id"], unit_number="102", floor=1, stack_index=2)
        resp = api.get_unit(u2["id"], make_resident_headers(ctx["resident"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_unassigned_technician_cannot_complete_inspection(self, api):
        """PRD §3.3: "Only the assigned technician may complete an inspection,
        and only from `SCHEDULED`."
        PRD §2.1: "When `X-User-Role` is `Technician`, `X-User-ID` is the `id`
        of the acting `Technician` record; assignment checks on any resource
        that references a technician compare the resource's `technician_id`
        field to `X-User-ID`. A technician acts only on records assigned to
        them."

        Design: Corner/rbac/unassigned_technician_cannot_complete_inspection
        """
        ctx = setup_community(with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        from test_helpers.fixtures import create_technician
        t1 = ctx["technician"]
        t2 = create_technician(full_name="T Two")
        insp = schedule_inspection(ctx["unit"]["id"], t1["id"])
        resp = api.complete_inspection(
            insp["id"],
            {"live_sightings": 0, "evidence_count": 0, "bed_bug_positive": False},
            make_technician_headers(t2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestAuthentication:
    def test_unauthenticated_missing_role_header_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or naming an undeclared
        role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.10: "When several rules could reject the same request, the
        server evaluates them in a fixed order and reports the first failure."
        PRD §2.10: "Authentication comes first (`ERR_UNAUTHENTICATED`), then
        role authorization and entity-backed ownership (`ERR_FORBIDDEN_ROLE`),
        then the existence-and-shape stage (`ERR_NOT_FOUND` and
        `ERR_INVALID_REQUEST`)"

        Design: Corner/rbac/unauthenticated_missing_role_header_returns_401
        """
        resp = api._request(
            "GET",
            "/pest/properties/8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
            headers={},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

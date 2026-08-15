"""Establishment registry, auth/RBAC basics, error envelope, and OCC."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_establishment,
    close_blockage,
    create_active_interceptor,
    create_and_assess_blockage,
    create_and_permit_hauler,
    create_establishment,
    create_establishment_payload,
    create_failing_inspection,
    create_inspection_payload,
    create_interceptor,
    create_pump_manifest_payload,
    create_variance,
    get_establishment,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_compliance_officer_headers,
    make_fse_contact_headers,
    make_hauler_admin_headers,
    patch_establishment_payload,
    pay_share,
    setup_pumping_chain,
    setup_submitted_manifest,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


class TestEstablishmentCreation:
    def test_establishment_create_applies_defaults_and_system_fields(self, api):
        """PRD: "The boolean `has_charbroiler` is optional and defaults to false
        when omitted. At enrollment the establishment's `compliance_status` is
        `COMPLIANT`, its `open_violation_count` — the count of its violations
        standing at `NOTICED` or `CITATION` — and its `missed_pump_windows` are
        zero, and both `last_verified_pump_at` and
        `variance_override_frequency_days` are null."
        PRD: "`id` (string): a unique, server-generated identifier formatted as
        a UUID, with no type prefix."
        PRD: "`version` (integer): a system-managed integer that increments
        with every modification to the resource."

        Design: Corner/entities/c_establishment_create_defaults_and_system_fields
        """
        resp = api.create_establishment(
            create_establishment_payload(name="Defaults Diner",
                                         street_address="1 A St"),
            ADMIN,
        )
        est = validate_success(resp, 201)
        assert_establishment(est)
        assert est["has_charbroiler"] is False, "has_charbroiler defaults to false"
        assert is_valid_uuid(est["id"]), "id is a bare UUID"
        assert is_iso8601_timestamp(est["created_at"])
        assert est["version"] == 1, "A freshly created resource has version 1"
        assert est["compliance_status"] == "COMPLIANT"
        assert est["open_violation_count"] == 0
        assert est["missed_pump_windows"] == 0
        assert est["last_verified_pump_at"] is None
        assert est["variance_override_frequency_days"] is None

    def test_establishment_missing_required_field_returns_400(self, api):
        """PRD: "Request-body shape: required fields present, no type
        violations, enum values in range, ... (`ERR_INVALID_REQUEST`)."
        PRD: "A `ProgramAdmin` enrolls a food-service establishment by
        supplying its `name`, `street_address`, `seating_capacity` (a
        non-negative integer), `fryer_count` (a non-negative integer), and
        `cuisine_profile`"

        Design: Corner/entities/c_establishment_missing_required_returns_400
        """
        payload = create_establishment_payload(name="No Seats",
                                               street_address="2 B St")
        del payload["seating_capacity"]
        resp = api.create_establishment(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_computed_field_input_ignored_on_establishment_create(self, api):
        """PRD: "The `risk_score` is the sum of three components: a seating
        contribution of one-tenth of a point per seat, capped at 40 points; an
        equipment contribution of 10 points per deep fryer plus a further 10
        points when a charbroiler is installed, capped at 30 points; and a
        cuisine contribution of 10 points for `LOW_GREASE`, 20 points for
        `MEDIUM_GREASE`, or 30 points for `HIGH_GREASE`."
        PRD: "An establishment's `compliance_status` is never set directly; it
        is recomputed from underlying facts whenever those facts change."

        Design: Corner/entities/c_computed_field_input_ignored_on_establishment_create
        """
        payload = create_establishment_payload(
            name="Sneaky Steakhouse", street_address="3 C St",
            seating_capacity=200, fryer_count=3, has_charbroiler=False,
            cuisine_profile="HIGH_GREASE")
        payload["risk_class"] = "LOW"
        payload["compliance_status"] = "SUSPENDED"
        est = validate_success(api.create_establishment(payload, ADMIN), 201)
        # 200 seats -> 20 + 3 fryers -> 30 + HIGH_GREASE -> 30 = 80 >= 70.
        assert est["risk_score"] == 80, (
            f"Server computes risk_score from the profile, got {est['risk_score']}"
        )
        assert est["risk_class"] == "HIGH", "Client-supplied LOW is ignored"
        assert est["compliance_status"] == "COMPLIANT", (
            "Client-supplied posture is ignored; enrollment posture is COMPLIANT"
        )

    def test_get_nonexistent_establishment_returns_404(self, api):
        """PRD: "Existence of every referenced identifier, in path and body
        alike — establishments, interceptors, haulers, manifests, inspections,
        violations, blockage events, variance requests, campaigns, outreach
        events, and the establishments named inside blockage contributions
        (`ERR_NOT_FOUND`)."

        Design: Corner/entities/c_get_nonexistent_establishment_returns_404
        """
        resp = api.get_establishment(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestManifestListingAndImmutability:
    def test_filtered_manifests_list_pagination(self, api):
        """PRD: "Manifests can be listed with optional `establishment_id`,
        `hauler_id`, `interceptor_id`, and `status` filters, or read
        individually."
        PRD: "List responses carry `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the response envelope."

        Design: Corner/entities/c_filtered_manifests_list_pagination
        """
        est, interceptor, h1 = setup_pumping_chain(
            establishment_name="List Diner", hauler_name="H1 Haul",
            permit_number="PN-L1")
        h2 = get_success_data(api.create_hauler(
            {"name": "H2 Haul", "permit_number": "PN-L2",
             "insurance_expires_on": "2027-06-01T00:00:00Z"}, ADMIN))
        get_success_data(api.permit_hauler(h2["id"], ADMIN))

        fse = make_fse_contact_headers(est["id"])
        # PRD keys manifest uniqueness on (interceptor, pump_date), so the
        # three manifests on this one interceptor need distinct pump_dates.
        for hauler_id, pump_date in ((h1["id"], "2026-08-01T00:00:00Z"),
                                     (h1["id"], "2026-08-02T00:00:00Z"),
                                     (h2["id"], "2026-08-03T00:00:00Z")):
            get_success_data(api.create_pump_manifest(
                create_pump_manifest_payload(est["id"], interceptor["id"],
                                             hauler_id, pump_date=pump_date),
                fse))

        resp = api.list_pump_manifests(
            INSPECTOR, {"hauler_id": h1["id"], "limit": 1})
        data, meta = validate_paginated(resp)
        assert len(data) == 1, "limit=1 honored"
        assert meta["total_count"] == 2, "H1 owns exactly two manifests"
        assert meta["has_more"] is True
        assert all(m["hauler_id"] == h1["id"] for m in data), (
            "hauler_id filter excludes H2's manifest"
        )

    def test_disposal_record_immutable_no_version(self, api):
        """PRD: "Two record types are immutable once created — the Inspection
        and the DisposalRecord. They carry only `id` and `created_at`; both
        `updated_at` and `version` are absent from them, because their
        contents never change after creation."

        Design: Corner/entities/c_disposal_record_immutable_no_version
        """
        est, interceptor, hauler, manifest = setup_submitted_manifest(
            establishment_name="Immutable Eats", hauler_name="Imm Haul",
            permit_number="PN-IMM")
        disposal = validate_success(api.create_disposal_record(
            {"hauler_id": hauler["id"], "manifest_id": manifest["id"],
             "disposed_volume_gal": 1000, "disposal_site_name": "Site C",
             "disposed_at": "2026-08-01T12:00:00Z"},
            make_hauler_admin_headers(hauler["id"])), 201)
        assert is_valid_uuid(disposal["id"])
        assert is_iso8601_timestamp(disposal["created_at"])
        assert "updated_at" not in disposal, (
            "append-only record must not expose updated_at"
        )
        assert "version" not in disposal, (
            "append-only record must not expose version"
        )


class TestAuthAndRbac:
    def test_missing_auth_headers_returns_401(self, api):
        """PRD: "A request missing either header, or carrying a role outside
        the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/c_missing_auth_headers_returns_401
        """
        resp = api.create_establishment(
            create_establishment_payload(name="No Auth",
                                         street_address="17 N St"),
            {"Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_fsecontact_cannot_create_inspection(self, api):
        """PRD: "Access to each operation is restricted by role; a caller
        whose role is not listed for the endpoint is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD: "An `Inspector` records a site inspection by supplying the
        `establishment_id` and an `items` array of findings"

        Design: Corner/rbac/c_fsecontact_cannot_create_inspection
        """
        est = create_establishment(name="RBAC Ramen", street_address="32 Z St")
        resp = api.create_inspection(
            create_inspection_payload(est["id"], []),
            make_fse_contact_headers(est["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        inspections, meta = validate_paginated(
            api.list_inspections(INSPECTOR, {"establishment_id": est["id"]}))
        assert meta["total_count"] == 0, "No inspection is persisted"

    def test_inspector_cannot_approve_interceptor(self, api):
        """PRD: "Access to each operation is restricted by role; a caller
        whose role is not listed for the endpoint is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD: "Sizing approval belongs to a `ComplianceOfficer` and is allowed
        only from `PROPOSED`."

        Design: Corner/rbac/c_inspector_cannot_approve_interceptor
        """
        est = create_establishment(name="RBAC BBQ", street_address="33 Z St")
        interceptor = create_interceptor(est["id"], nominal_capacity_gal=50)
        resp = api.approve_interceptor(interceptor["id"], INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        current = validate_success(api.get_interceptor(interceptor["id"], ADMIN))
        assert current["status"] == "PROPOSED", (
            "The role check precedes the state transition"
        )

    def test_hauleradmin_cannot_file_disposal_for_other_hauler(self, api):
        """PRD: "When `X-User-Role` is `HaulerAdmin`, the `X-User-ID` is the
        `id` of the acting Hauler, and the same comparison applies against
        hauler foreign keys."
        PRD: "a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP
        403)."

        Design: Corner/rbac/c_hauleradmin_cannot_file_disposal_for_other_hauler
        """
        est, interceptor, h1 = setup_pumping_chain(
            establishment_name="Own Eats", hauler_name="H1 Own",
            permit_number="PN-O1")
        h2 = get_success_data(api.create_hauler(
            {"name": "H2 Own", "permit_number": "PN-O2",
             "insurance_expires_on": "2027-06-01T00:00:00Z"}, ADMIN))
        manifest = get_success_data(api.create_pump_manifest(
            create_pump_manifest_payload(est["id"], interceptor["id"],
                                         h1["id"]),
            make_fse_contact_headers(est["id"])))
        resp = api.create_disposal_record(
            {"hauler_id": h1["id"], "manifest_id": manifest["id"],
             "disposed_volume_gal": 1000, "disposal_site_name": "Site G",
             "disposed_at": "2026-08-01T12:00:00Z"},
            make_hauler_admin_headers(h2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)

    def test_fsecontact_cannot_submit_manifest_for_other_establishment(self, api):
        """PRD: "When `X-User-Role` is `FseContact`, the `X-User-ID` is the
        `id` of the acting Establishment; ownership checks on any resource
        that references an establishment compare the resource's establishment
        foreign key to `X-User-ID`, and a mismatch is rejected with
        `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

        Design: Corner/rbac/c_fsecontact_cannot_submit_manifest_for_other_establishment
        """
        e1 = create_establishment(name="Own One", street_address="35 Z St",
                                  seating_capacity=200, fryer_count=3,
                                  cuisine_profile="HIGH_GREASE")
        interceptor = create_active_interceptor(e1["id"], 600)
        e2 = create_establishment(name="Own Two", street_address="36 Z St")
        hauler = create_and_permit_hauler(name="Own Haul", permit_number="PN-OWN")
        resp = api.create_pump_manifest(
            create_pump_manifest_payload(e1["id"], interceptor["id"],
                                         hauler["id"]),
            make_fse_contact_headers(e2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)


class TestSegregationOfDuties:
    def test_sod_recorder_cannot_dismiss_own_violation(self, api):
        """PRD: "segregation of duties forbids dismissing a violation whose
        `recorded_by_user_id` equals the caller's own identity, a rejection
        carried by `ERR_SOD_VIOLATION` (HTTP 403); a successful dismissal
        stamps `dismissed_at` and records `dismissed_by_user_id`."

        Design: Corner/rbac/c_sod_recorder_cannot_dismiss_own_violation
        """
        est = create_establishment(name="SoD Sushi", street_address="37 Z St")
        _insp, violation = create_failing_inspection(est["id"],
                                                     inspector_user_id="insp-7")
        resp = api.dismiss_violation(
            violation["id"], make_compliance_officer_headers("insp-7"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, 403)

        dismissed = validate_success(api.dismiss_violation(
            violation["id"], make_compliance_officer_headers("officer-9")))
        assert dismissed["status"] == "DISMISSED"
        assert dismissed["dismissed_by_user_id"] == "officer-9"

    def test_sod_assessor_cannot_close_blockage(self, api):
        """PRD: "Closure belongs to a `ComplianceOfficer` and is deliberately
        two-keyed: the closer's identity must differ from
        `assessed_by_user_id` (`ERR_SOD_VIOLATION`, HTTP 403), and every
        contribution must show a non-null `paid_at` (`ERR_COST_SHARE_UNPAID`,
        HTTP 409)."

        Design: Corner/rbac/c_sod_assessor_cannot_close_blockage
        """
        est = create_establishment(name="SoD Soup", street_address="38 Z St")
        blockage = create_and_assess_blockage(
            5000, [{"establishment_id": est["id"], "weight_percent": 100}],
            inspector_user_id="insp-1", location_description="13th Ave")
        pay_share(blockage["id"], est["id"])

        resp = api.close_blockage_event(
            blockage["id"], make_compliance_officer_headers("insp-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, 403)

        closed = close_blockage(blockage["id"], officer_user_id="officer-2")
        assert closed["status"] == "CLOSED"


class TestErrorEnvelope:
    def test_error_response_envelope_shape(self, api):
        """PRD: "All error API responses (4xx status codes) follow this
        standard envelope format: ... `\"response_type\": \"error\"` ..."
        PRD: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/errors/c_error_response_envelope_shape
        """
        resp = api.get_hauler(NON_EXISTENT_UUID, ADMIN)
        assert resp.status_code == 404
        body = resp.json()
        assert body.get("response_type") == "error"
        data = body["data"]
        assert data["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(data["message"], str) and data["message"].strip()


class TestOptimisticConcurrency:
    def test_occ_stale_version_on_establishment_patch(self, api):
        """PRD: "The first is the establishment profile update: if the
        supplied value no longer matches the establishment's current
        `version` — because a variance approval cascade or an earlier profile
        update has advanced it since the client last read the record — the
        update is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client
        must rebase on a fresh read before reapplying."

        Design: Corner/cross_cutting_layers/c_occ_stale_version_on_establishment_patch
        """
        est = create_establishment(name="OCC Omelets", street_address="39 Z St")
        version_at_create = est["version"]

        updated = validate_success(api.patch_establishment(
            est["id"],
            patch_establishment_payload(version_at_create,
                                        street_address="39 Z St Ste B"),
            ADMIN))
        assert updated["street_address"] == "39 Z St Ste B"
        assert updated["version"] == 2, "A successful PATCH advances the version"

        resp = api.patch_establishment(
            est["id"],
            patch_establishment_payload(version_at_create,
                                        street_address="39 Z St Ste C"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        current = get_establishment(est["id"])
        assert current["street_address"] == "39 Z St Ste B", (
            "The rejected PATCH wrote nothing"
        )

    def test_occ_stale_version_on_variance_approve(self, api):
        """PRD: "The second is variance approval, which pins a requested
        pumping frequency onto the establishment: the same comparison is made
        against the establishment's current `version`, and a mismatch is
        likewise rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting_layers/c_occ_stale_version_on_variance_approve
        """
        est = create_establishment(name="OCC Variance", street_address="40 Z St")
        version_before_v1 = est["version"]

        v1 = create_variance(est["id"], scope="PUMPING_FREQUENCY",
                             requested_frequency_days=120, justification="v1")
        approved_v1 = validate_success(api.approve_variance_request(
            v1["id"], version_before_v1, OFFICER))
        assert approved_v1["status"] == "APPROVED"

        v2 = create_variance(est["id"], scope="PUMPING_FREQUENCY",
                             requested_frequency_days=150, justification="v2",
                             effective_from="2028-01-01T00:00:00Z",
                             effective_to="2028-07-01T00:00:00Z")
        resp = api.approve_variance_request(v2["id"], version_before_v1, OFFICER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        current = validate_success(api.get_variance_request(v2["id"], OFFICER))
        assert current["status"] == "UNDER_REVIEW"


class TestDerivedFieldRecompute:
    def test_derived_field_recompute_on_profile_patch(self, api):
        """PRD: "When any of `seating_capacity`, `fryer_count`,
        `has_charbroiler`, or `cuisine_profile` changes, the risk
        classification is recomputed; `pumping_frequency_days` and the
        compliance posture are recomputed as well, and the establishment's
        `version` advances by one."
        PRD: "The `risk_score` is the sum of three components: a seating
        contribution of one-tenth of a point per seat, capped at 40 points; an
        equipment contribution of 10 points per deep fryer plus a further 10
        points when a charbroiler is installed, capped at 30 points; and a
        cuisine contribution of 10 points for `LOW_GREASE`, 20 points for
        `MEDIUM_GREASE`, or 30 points for `HIGH_GREASE`."

        Design: Corner/cross_cutting_layers/c_derived_field_recompute_on_profile_patch
        """
        est = create_establishment(name="Recompute Ramen",
                                   street_address="41 Z St",
                                   seating_capacity=200, fryer_count=3,
                                   cuisine_profile="HIGH_GREASE")
        assert est["risk_class"] == "HIGH"
        assert est["pumping_frequency_days"] == 90

        updated = validate_success(api.patch_establishment(
            est["id"],
            patch_establishment_payload(est["version"], fryer_count=0),
            ADMIN))
        # min(40, 200*0.1) + min(30, 0) + 30 = 20 + 0 + 30 = 50.
        assert updated["risk_score"] == 50, (
            f"risk_score recomputes with the profile, got {updated['risk_score']}"
        )
        assert updated["risk_class"] == "MEDIUM", "50 >= 40 flips HIGH -> MEDIUM"
        assert updated["pumping_frequency_days"] == 180, (
            "pumping_frequency_days follows the new risk class in the same request"
        )
        assert updated["version"] == 2

"""RBAC, ownership, validation pipeline ordering, and optimistic concurrency
(PRD §2.1, §2.5, §2.8, §3.1, §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    build_user_headers,
    create_entry_requirement,
    create_entry_requirement_payload,
    create_premises,
    create_premises_payload,
    create_quarantine_order_payload,
    create_test_record_payload,
    create_veterinarian,
    get_permit,
    make_vet_headers,
    set_clock,
    setup_issued_certificate_with_permit,
    create_draft_certificate,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestUserContextHeader:
    def test_empty_user_context_header_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying an empty
        value for either, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any
        other check runs."

        Design: Corner/validations/empty_user_context_header_rejected
        """
        resp = api.list_entry_requirements(build_user_headers("", "ProgramAdmin"))
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestForbiddenBeatsBodyValidation:
    def test_forbidden_beats_body_validation(self, api, officer_headers):
        """PRD §2.5: "Every request passes through a fixed pipeline of
        validation layers, evaluated in the order below; the first layer that
        fails determines the error the client sees." (role authorization is
        layer 2; request-body schema is layer 3.)
        PRD §2.1: "a role not listed for that endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/validations/forbidden_beats_body_validation
        """
        # StateVetOfficer is not authorized for POST /api/premises; the body is
        # also missing the required county — the role check must win.
        resp = api.create_premises(
            {
                "name": "Ranch V2",
                "state_code": "CA",
                "species_code": "CATTLE",
                "initial_head_count": 5,
            },
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestRbacWriteDenials:
    def test_rbac_write_denials_officer_admin_lab(
        self, api, officer_headers, admin_headers, lab_headers
    ):
        """PRD §2.1: "Once the headers are accepted, the role is matched
        against the endpoint's authorized role list; a role not listed for that
        endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4 endpoint table: POST /api/premises is ProgramAdmin-only;
        POST /api/certificates is AccreditedVet-only; POST /api/test-records is
        LabTechnician-only; POST /api/outbreak-zones and
        POST /api/test-records/{id}/result are StateVetOfficer/LabTechnician
        exclusives respectively; POST /api/quarantine-orders and
        POST /api/certificates/{id}/issue are StateVetOfficer-only.

        Design: Corner/rbac/rbac_write_denials_officer_admin_lab
        """
        validate_error(
            api.create_premises(create_premises_payload(name="Ranch R1"), officer_headers),
            ApiErrorId.ERR_FORBIDDEN,
        )
        validate_error(
            api.create_certificate(
                {
                    "origin_premises_id": "00000000-0000-0000-0000-0000000000aa",
                    "destination_state_code": "KS", "species_code": "CATTLE",
                    "head_count": 5, "inspection_date": "2026-08-01T00:00:00Z",
                },
                officer_headers,
            ),
            ApiErrorId.ERR_FORBIDDEN,
        )
        validate_error(
            api.create_test_record(
                create_test_record_payload(
                    premises_id="00000000-0000-0000-0000-0000000000aa",
                    lab_reference="LAB-R1",
                ),
                officer_headers,
            ),
            ApiErrorId.ERR_FORBIDDEN,
        )
        validate_error(
            api.create_outbreak_zone(
                {
                    "county": "Yolo", "state_code": "CA",
                    "disease_code": "VESICULAR_STOMATITIS", "species_code": "CATTLE",
                    "severity": "LOW", "effective_from": "2026-08-01T00:00:00Z",
                },
                admin_headers,
            ),
            ApiErrorId.ERR_FORBIDDEN,
        )
        validate_error(
            api.report_test_result(
                "00000000-0000-0000-0000-0000000000bb", {"result": "NEGATIVE"}, admin_headers
            ),
            ApiErrorId.ERR_FORBIDDEN,
        )
        validate_error(
            api.create_quarantine_order(
                create_quarantine_order_payload(
                    premises_id="00000000-0000-0000-0000-0000000000aa",
                    start_at="2026-08-01T00:00:00Z", end_at="2026-08-15T00:00:00Z",
                    reason="X",
                ),
                lab_headers,
            ),
            ApiErrorId.ERR_FORBIDDEN,
        )
        validate_error(
            api.issue_certificate("00000000-0000-0000-0000-0000000000cc", lab_headers),
            ApiErrorId.ERR_FORBIDDEN,
        )

    def test_rbac_write_denials_vet_and_auditor(
        self, api, admin_headers, auditor_headers
    ):
        """PRD §2.1: "a role not listed for that endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "**StateAuditor** — a read-only auditor for traceback and
        compliance review."
        PRD §4 endpoint table: certificate issue, outbreak-zone declaration,
        test registration, and veterinarian registration are not AccreditedVet
        operations; premises registration, certificate submission, and movement
        scheduling are not StateAuditor operations.

        Design: Corner/rbac/rbac_write_denials_vet_and_auditor
        """
        vet = create_veterinarian()
        vet_h = make_vet_headers(vet["id"])

        validate_error(
            api.issue_certificate("00000000-0000-0000-0000-0000000000cc", vet_h),
            ApiErrorId.ERR_FORBIDDEN,
        )
        validate_error(
            api.create_outbreak_zone(
                {
                    "county": "Yolo", "state_code": "CA",
                    "disease_code": "VESICULAR_STOMATITIS", "species_code": "CATTLE",
                    "severity": "LOW", "effective_from": "2026-08-01T00:00:00Z",
                },
                vet_h,
            ),
            ApiErrorId.ERR_FORBIDDEN,
        )
        validate_error(
            api.create_test_record(
                create_test_record_payload(
                    premises_id="00000000-0000-0000-0000-0000000000aa",
                    lab_reference="LAB-R2",
                ),
                vet_h,
            ),
            ApiErrorId.ERR_FORBIDDEN,
        )
        validate_error(
            api.create_veterinarian(
                {
                    "full_name": "Dr. Fake", "accreditation_number": "ACCRED-F",
                    "accreditation_expires_at": "2027-01-01T00:00:00Z",
                },
                vet_h,
            ),
            ApiErrorId.ERR_FORBIDDEN,
        )
        validate_error(
            api.create_premises(create_premises_payload(name="Ranch R3"), auditor_headers),
            ApiErrorId.ERR_FORBIDDEN,
        )
        validate_error(
            api.submit_certificate("00000000-0000-0000-0000-0000000000cc", auditor_headers),
            ApiErrorId.ERR_FORBIDDEN,
        )
        validate_error(
            api.create_movement_record(
                {
                    "permit_id": "00000000-0000-0000-0000-0000000000dd",
                    "head_count": 2, "destination_name": "Nowhere",
                    "planned_ship_date": "2026-08-21T00:00:00Z",
                },
                auditor_headers,
            ),
            ApiErrorId.ERR_FORBIDDEN,
        )


class TestOwnershipEnforcement:
    def test_ownership_enforced_for_vet_of_record(self, api, admin_headers, officer_headers):
        """PRD §2.1: "Ownership checks on any resource that references a
        `Veterinarian` compare the resource's foreign-key field to `X-User-ID`
        — directly for a certificate's `vet_id`, and through the
        permit-to-certificate chain for movement records (see §3.5)."
        PRD §3.4: "Only the veterinarian of record may submit: the caller's
        `X-User-ID` must equal the certificate's `vet_id`, else
        `ERR_NOT_CERTIFICATE_OWNER` (HTTP 403)."
        PRD §3.5: "Scheduling a **movement record** is the veterinarian's act,
        and ownership is checked through the chain: the caller's `X-User-ID`
        must equal the `vet_id` of the certificate backing the record's permit,
        else `ERR_NOT_CERTIFICATE_OWNER`."

        Design: Corner/rbac/ownership_enforced_for_vet_of_record
        """
        premises = create_premises(name="Ranch R4", initial_head_count=30)
        vet_a = create_veterinarian(accreditation_number="ACCRED-1", full_name="Dr. Ada")
        vet_b = create_veterinarian(accreditation_number="ACCRED-2", full_name="Dr. Bob")
        create_entry_requirement(none_type=True)
        set_clock("2026-08-10T00:00:00Z")
        cert = create_draft_certificate(premises["id"], vet_a["id"])
        ha, hb = make_vet_headers(vet_a["id"]), make_vet_headers(vet_b["id"])

        # Vet B cannot submit vet A's certificate.
        validate_error(api.submit_certificate(cert["id"], hb), ApiErrorId.ERR_NOT_CERTIFICATE_OWNER)
        assert validate_success(api.submit_certificate(cert["id"], ha), 200)["status"] == "PENDING_REVIEW"

        # Vet B cannot revise vet A's rejected certificate.
        validate_success(
            api.reject_certificate(cert["id"], {"reason_code": "INCOMPLETE"}, officer_headers),
            200,
        )
        validate_error(api.revise_certificate(cert["id"], hb), ApiErrorId.ERR_NOT_CERTIFICATE_OWNER)
        assert validate_success(api.revise_certificate(cert["id"], ha), 200)["status"] == "DRAFT"

        # Drive to ISSUED + ISSUED permit owned (through the chain) by vet A.
        validate_success(api.submit_certificate(cert["id"], ha), 200)
        validate_success(api.issue_certificate(cert["id"], officer_headers), 200)
        permit = validate_success(
            api.create_movement_permit(
                {
                    "certificate_id": cert["id"], "allocated_head_count": 10,
                    "valid_from": "2026-08-11T00:00:00Z",
                    "valid_until": "2026-09-08T00:00:00Z",
                },
                ha,
            ),
            201,
        )
        validate_success(api.issue_movement_permit(permit["id"], officer_headers), 200)

        payload = {
            "permit_id": permit["id"], "head_count": 2,
            "destination_name": "KS Feedlot",
            "planned_ship_date": "2026-08-21T00:00:00Z",
        }
        validate_error(
            api.create_movement_record(payload, hb),
            ApiErrorId.ERR_NOT_CERTIFICATE_OWNER,
        )
        scheduled = validate_success(api.create_movement_record(payload, ha), 201)
        assert scheduled["status"] == "SCHEDULED"


class TestOptimisticConcurrency:
    def test_permit_adjust_stale_version_rejected(self, api, admin_headers, officer_headers):
        """PRD §2.8: "Adjusting an issued movement permit — the operation that
        changes `allocated_head_count` or `valid_until` — must likewise carry
        `expected_permit_version` holding the permit's last observed `version`.
        A mismatch with the permit's current `version` is rejected with
        `ERR_STALE_PERMIT_VERSION` (HTTP 412), and a successful adjustment
        increments the permit's `version` by one and recomputes its headrooms
        and fee totals."

        Design: Corner/cross_cutting_layers/permit_adjust_stale_version_rejected
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(allocation=10)
        pv = get_permit(permit["id"])["version"]

        first = validate_success(
            api.adjust_movement_permit(
                permit["id"],
                {"expected_permit_version": pv, "allocated_head_count": 15},
                officer_headers,
            ),
            200,
        )
        assert first["allocated_head_count"] == 15
        assert first["committed_headroom"] == 15
        assert first["version"] == pv + 1, "a successful adjust increments version by one"

        # Replaying the pre-adjustment version is the stale write.
        resp = api.adjust_movement_permit(
            permit["id"],
            {"expected_permit_version": pv, "allocated_head_count": 18},
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_PERMIT_VERSION)

        after = get_permit(permit["id"])
        assert after["allocated_head_count"] == 15, "the rejected write leaves no drift"
        assert after["version"] == pv + 1

    def test_entry_requirement_amend_stale_version_rejected(self, api, admin_headers):
        """PRD §2.8: "Amending an entry-requirement matrix row — the
        operation that adjusts `test_validity_days`, `vaccination_required`,
        `vaccination_min_days_before_inspection`, `permit_required`, or
        `effective_until` on a requirement — must carry
        `expected_requirement_version` as a non-optional input holding the
        row's `version` the client last observed."
        PRD §2.8: "If the row's current `version` differs — because another
        amendment landed in between — the request is rejected with
        `ERR_STALE_REQUIREMENT_VERSION` (HTTP 412)."
        PRD §2.8: "A successful amendment increments the requirement's
        `version` by one."
        PRD §2.8: "Because a requirement row remains `ACTIVE` after any
        amendment, a second sequential amend would otherwise succeed silently;
        the version check is the only detection of the stale write."

        Design: Corner/cross_cutting_layers/entry_requirement_amend_stale_version_rejected
        """
        req = create_entry_requirement(vaccination_required=False)
        rv = req["version"]

        first = validate_success(
            api.amend_entry_requirement(
                req["id"],
                {"expected_requirement_version": rv, "test_validity_days": 45},
                admin_headers,
            ),
            200,
        )
        assert first["test_validity_days"] == 45
        assert first["version"] == rv + 1
        assert first["status"] == "ACTIVE"

        resp = api.amend_entry_requirement(
            req["id"],
            {"expected_requirement_version": rv, "test_validity_days": 60},
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_REQUIREMENT_VERSION)

        rows, meta = validate_paginated(
            api.list_entry_requirements(
                build_user_headers("auditor-1", "StateAuditor"),
                params={"destination_state_code": "KS", "species_code": "CATTLE"},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["test_validity_days"] == 45, "the rejected amend leaves no drift"


class TestRequirementWindowOverlap:
    def test_entry_requirement_amend_window_overlap_rejected(self, api, admin_headers):
        """PRD §3.1: "Two rows fight for the same slot when their half-open
        windows overlap while both are `ACTIVE` for the same combination of
        `destination_state_code`, `species_code`, and `test_type` — creating
        such a row, or amending `effective_until` into such an overlap, is
        rejected with `ERR_REQUIREMENT_WINDOW_OVERLAP` (HTTP 409)."
        PRD §3.1: "changing `effective_until` re-evaluates the window-overlap
        rule below."

        Design: Corner/validations/entry_requirement_amend_window_overlap_rejected
        """
        r1 = create_entry_requirement(
            vaccination_required=False,
            effective_from="2026-06-01T00:00:00Z", effective_until="2026-07-01T00:00:00Z",
        )
        create_entry_requirement(
            vaccination_required=False,
            effective_from="2026-07-01T00:00:00Z", effective_until="2026-08-01T00:00:00Z",
        )

        # Extending R1's window into R2's window overlaps.
        resp = api.amend_entry_requirement(
            r1["id"],
            {
                "expected_requirement_version": r1["version"],
                "effective_until": "2026-07-15T00:00:00Z",
            },
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REQUIREMENT_WINDOW_OVERLAP)

        # The rejected amend did not bump the version; shrinking inside R1's
        # own span with the same expected version succeeds.
        shrunk = validate_success(
            api.amend_entry_requirement(
                r1["id"],
                {
                    "expected_requirement_version": r1["version"],
                    "effective_until": "2026-06-20T00:00:00Z",
                },
                admin_headers,
            ),
            200,
        )
        assert shrunk["effective_until"] == "2026-06-20T00:00:00Z"

    def test_entry_requirement_create_overlap_key_scoped(self, api, admin_headers):
        """PRD §3.1: "Two rows fight for the same slot when their half-open
        windows overlap while both are `ACTIVE` for the same combination of
        `destination_state_code`, `species_code`, and `test_type` — creating
        such a row, or amending `effective_until` into such an overlap, is
        rejected with `ERR_REQUIREMENT_WINDOW_OVERLAP` (HTTP 409)."

        Design: Corner/validations/entry_requirement_create_overlap_key_scoped
        """
        create_entry_requirement(vaccination_required=False)  # KS/CATTLE/BRUCELLOSIS [06-01, open)

        # Same key, overlapping window -> rejected.
        resp_same = api.create_entry_requirement(
            create_entry_requirement_payload(
                test_validity_days=45, vaccination_required=False,
                effective_from="2026-07-01T00:00:00Z",
            ),
            admin_headers,
        )
        validate_error(resp_same, ApiErrorId.ERR_REQUIREMENT_WINDOW_OVERLAP)

        # Different test_type / destination / species overlap freely.
        r3 = create_entry_requirement(
            test_type="TUBERCULOSIS", test_validity_days=45,
            vaccination_required=False, permit_required=False,
            effective_from="2026-07-01T00:00:00Z",
        )
        assert r3["status"] == "ACTIVE"
        r4 = create_entry_requirement(
            destination_state_code="TX", test_validity_days=45,
            vaccination_required=False, effective_from="2026-07-01T00:00:00Z",
        )
        assert r4["status"] == "ACTIVE"
        r5 = create_entry_requirement(
            species_code="SWINE", test_validity_days=45,
            vaccination_required=False, permit_required=False,
            effective_from="2026-07-01T00:00:00Z",
        )
        assert r5["status"] == "ACTIVE"


class TestImmediateVisibility:
    def test_immediate_mutation_visibility_in_response(self, api, admin_headers, officer_headers):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §1: "every mutation and every cascade it triggers completes
        atomically within the request".
        PRD §3.4: "A successful issuance mints the `cvi_number` per §2.10,
        stamps `issued_at` with the logical clock, sets `valid_until` thirty
        days out per §2.9, and computes the **final issuance fee** into
        `final_fee_cents` using the same formula re-evaluated at issuance
        time."

        Design: Corner/consistency_model/immediate_mutation_visibility_in_response
        """
        # Defaults and computed fields are visible in the create response.
        prem = validate_success(
            api.create_premises(create_premises_payload(name="Ranch L3"), admin_headers), 201
        )
        assert prem["disease_status"] == "MONITORED"
        assert prem["current_head_count"] == 30

        vet = validate_success(
            api.create_veterinarian(
                {
                    "full_name": "Dr. Ada", "accreditation_number": "ACCRED-1",
                    "accreditation_expires_at": "2027-01-01T00:00:00Z",
                },
                admin_headers,
            ),
            201,
        )
        assert vet["status"] == "ACTIVE"
        assert vet["is_credential_current"] is True

        create_entry_requirement(none_type=True)
        clock = validate_success(api.set_clock("2026-08-10T00:00:00Z", admin_headers), 200)
        assert clock["current_utc"] == "2026-08-10T00:00:00Z"

        cert = validate_success(
            api.create_certificate(
                {
                    "origin_premises_id": prem["id"], "destination_state_code": "KS",
                    "species_code": "CATTLE", "head_count": 10,
                    "inspection_date": "2026-08-10T00:00:00Z",
                },
                make_vet_headers(vet["id"]),
            ),
            201,
        )
        assert cert["status"] == "DRAFT"
        assert cert["vet_id"] == vet["id"]

        # The fee computed by the transition is in the transition's response.
        submitted = validate_success(
            api.submit_certificate(cert["id"], make_vet_headers(vet["id"])), 200
        )
        assert submitted["status"] == "PENDING_REVIEW"
        assert submitted["provisional_fee_cents"] == 5000  # 2500 + 150*10 + 1000

        issued = validate_success(api.issue_certificate(cert["id"], officer_headers), 200)
        assert issued["status"] == "ISSUED"
        assert issued["final_fee_cents"] == 5000
        assert issued["cvi_number"] == "CVI-CA-000001"
        assert issued["valid_until"] == "2026-09-09T00:00:00Z"

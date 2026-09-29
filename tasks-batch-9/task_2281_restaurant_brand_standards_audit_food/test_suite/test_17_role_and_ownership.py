"""The role model: exclusive operations, shared ones, identity, ownership and duties."""
import pytest

from test_helpers import (
    ADMIN_HEADERS,
    INTEGRATOR_HEADERS,
    NON_EXISTENT_UUID,
    TEST_DEFAULTS,
    ApiErrorId,
    api_client,
    attach_action_photo,
    attach_dispute_photo,
    audit_visit_payload,
    create_franchisee,
    dispute_payload,
    evidence_photo_payload,
    health_inspection_payload,
    live_brand_version,
    make_calibration_reviewer_headers,
    make_franchisee_headers,
    make_headers,
    request_info_payload,
    rescore_payload,
    resolve_dispute_payload,
    rubric_version_payload,
    setup_brand_program,
    setup_filed_dispute,
    setup_finalized_visit,
    validate_error,
    validate_paginated,
    validate_success,
)

LATER_VISIT_START = "2026-08-26T09:00:00Z"
LATER_VISIT_END = "2026-08-26T13:00:00Z"


def without_header(headers, name):
    """The same headers with one of the two identity headers removed."""
    return {key: value for key, value in headers.items() if key != name}


class TestBrandAdminExclusives:
    def test_admin_only_operations_refuse_every_other_role(self):
        """Four roles are each refused on a different exclusive, reads included.

        PRD: "A syntactically valid request whose acting role is not among the roles authorized
        for the target operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/brand_admin_exclusive_operations_are_denied_to_every_other_role
        """
        program = setup_finalized_visit(with_reviewer=True)
        brand_id = program["brand"]["id"]
        location_id = program["location"]["id"]

        validate_error(
            api_client.create_audit_visit(
                audit_visit_payload(
                    location_id, program["auditor"]["id"], program["rubric_version"]["id"],
                    LATER_VISIT_START, LATER_VISIT_END,
                ),
                program["franchisee_headers"],
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            expected_status=403,
        )
        validate_error(
            api_client.run_overdue_sweep(program["auditor_headers"], {}),
            ApiErrorId.ERR_UNAUTHORIZED,
            expected_status=403,
        )
        validate_error(
            api_client.get_brand_risk_index(brand_id, program["franchisee_headers"]),
            ApiErrorId.ERR_UNAUTHORIZED,
            expected_status=403,
        )
        validate_error(
            api_client.list_franchisees(
                program["reviewer_calibration_headers"], params={"brand_id": brand_id}
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            expected_status=403,
        )
        validate_error(
            api_client.set_clock("2026-09-01T00:00:00Z", INTEGRATOR_HEADERS),
            ApiErrorId.ERR_UNAUTHORIZED,
            expected_status=403,
        )
        validate_error(
            api_client.create_rubric_version(
                rubric_version_payload(
                    brand_id, live_brand_version(brand_id),
                    version_label="RV-2027.1", effective_from="2027-01-01T00:00:00Z",
                ),
                INTEGRATOR_HEADERS,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            expected_status=403,
        )

        _, ledger_meta = validate_paginated(
            api_client.list_visit_escalation_events(
                program["visit"]["id"], ADMIN_HEADERS, params={"limit": 10, "offset": 0}
            )
        )
        assert ledger_meta["total_count"] == 0, "the same read is open to the compliance office"
        risk = validate_success(api_client.get_brand_risk_index(brand_id, ADMIN_HEADERS))
        assert risk["brand_risk_index"] == pytest.approx(11.58, abs=0.01)

        validate_error(
            api_client.create_health_inspection(
                health_inspection_payload(location_id, "2026-08-20T00:00:00Z", 95, "A"),
                INTEGRATOR_HEADERS,
            ),
            ApiErrorId.ERR_TIMESTAMP_IN_FUTURE,
            expected_status=422,
        )

        _, visit_meta = validate_paginated(
            api_client.list_audit_visits(ADMIN_HEADERS, params={"location_id": location_id})
        )
        assert visit_meta["total_count"] == 1, "no refused call scheduled anything"


class TestSharedOperations:
    def test_shared_reads_and_the_shared_write_accept_every_declaring_role(self):
        """Four roles read the same body; two roles write and are stamped differently.

        PRD: "The server records `uploaded_by_role` from the acting role, which is therefore
        either `Franchisee` or `Auditor`."

        Design: Corner/rbac/shared_operations_are_open_to_every_role_that_declares_them
        """
        program = setup_finalized_visit(with_reviewer=True)
        visit_id = program["visit"]["id"]
        action_id = program["actions"]["FS-1"]["id"]

        readers = {
            "BrandAdmin": ADMIN_HEADERS,
            "Auditor": program["auditor_headers"],
            "Franchisee": program["franchisee_headers"],
            "CalibrationReviewer": program["reviewer_calibration_headers"],
        }
        for role, headers in readers.items():
            visit = validate_success(api_client.get_audit_visit(visit_id, headers))
            assert visit["composite_score"] == pytest.approx(90.70, abs=0.01), \
                f"{role} reads the same shared body"
            assert visit["grade"] == "PASS"

        validate_error(
            api_client.get_audit_visit(visit_id, INTEGRATOR_HEADERS),
            ApiErrorId.ERR_UNAUTHORIZED,
            expected_status=403,
        )

        franchisee_photo = validate_success(
            api_client.create_evidence_photo(
                evidence_photo_payload(
                    "2026-08-05T12:10:00Z", corrective_action_id=action_id,
                    file_uri="s3://ev/fr.jpg",
                ),
                program["franchisee_headers"],
            ),
            expected_status=201,
        )
        assert franchisee_photo["uploaded_by_role"] == "Franchisee"

        auditor_photo = validate_success(
            api_client.create_evidence_photo(
                evidence_photo_payload(
                    "2026-08-05T12:20:00Z", corrective_action_id=action_id,
                    file_uri="s3://ev/aud.jpg",
                ),
                program["auditor_headers"],
            ),
            expected_status=201,
        )
        assert auditor_photo["uploaded_by_role"] == "Auditor", \
            "the stamp follows the caller, not the target"

        action = validate_success(api_client.get_corrective_action(action_id, ADMIN_HEADERS))
        assert action["evidence_photo_count"] == 2, "both writes landed on the same parent"


class TestIdentityHeaders:
    def test_missing_or_undeclared_identity_headers_answer_before_authorization(self):
        """Three header failures all answer 401, even on an endpoint the role may call.

        PRD: "A request missing either header, or presenting a role string that is not one of
        the five declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_or_undeclared_identity_headers_are_rejected_before_any_other_check
        """
        program = setup_brand_program()
        location_id = program["location"]["id"]

        validate_error(
            api_client.get_location(location_id, without_header(ADMIN_HEADERS, "X-User-Role")),
            ApiErrorId.ERR_UNAUTHENTICATED,
            expected_status=401,
        )
        validate_error(
            api_client.get_location(
                location_id, make_headers("RegionalManager", program["auditor"]["id"])
            ),
            ApiErrorId.ERR_UNAUTHENTICATED,
            expected_status=401,
        )
        validate_error(
            api_client.get_location(
                location_id, without_header(program["auditor_headers"], "X-User-ID")
            ),
            ApiErrorId.ERR_UNAUTHENTICATED,
            expected_status=401,
        )

        location = validate_success(api_client.get_location(location_id, ADMIN_HEADERS))
        assert location["store_number"] == TEST_DEFAULTS["STORE_NUMBER"]
        assert location["franchise_agreement_status"] == "GOOD_STANDING", \
            "the same read with both headers present is a plain success"


class TestActingIdentityResolution:
    def test_entity_backed_identities_must_resolve_but_opaque_ones_need_not(self):
        """The same unknown identifier is a 404 for three roles and inert for two.

        PRD: "For the three entity-backed roles — `Auditor`, `CalibrationReviewer`, and
        `Franchisee` — the identifier in `X-User-ID` must resolve to an existing row of the
        backing entity. If it does not, the request fails with `ERR_ACTING_IDENTITY_NOT_FOUND`
        (HTTP 404), which is evaluated before any ownership comparison."

        Design: Corner/rbac/entity_backed_identities_must_resolve_while_opaque_identities_need_not
        """
        program = setup_finalized_visit()
        visit_id = program["visit"]["id"]
        action_id = program["actions"]["FS-1"]["id"]
        attach_action_photo(program, action_id)

        ghost_auditor = make_headers("Auditor", NON_EXISTENT_UUID)
        ghost_franchisee = make_headers("Franchisee", NON_EXISTENT_UUID)
        ghost_reviewer = make_headers("CalibrationReviewer", NON_EXISTENT_UUID)

        validate_error(
            api_client.get_audit_visit(visit_id, ghost_auditor),
            ApiErrorId.ERR_ACTING_IDENTITY_NOT_FOUND,
            expected_status=404,
        )
        validate_error(
            api_client.submit_corrective_action(
                action_id, ghost_franchisee, {"remediation_note": "Done"},
            ),
            ApiErrorId.ERR_ACTING_IDENTITY_NOT_FOUND,
            expected_status=404,
        )
        validate_error(
            api_client.list_disputes(ghost_reviewer, params={"limit": 10, "offset": 0}),
            ApiErrorId.ERR_ACTING_IDENTITY_NOT_FOUND,
            expected_status=404,
        )

        validate_error(
            api_client.get_audit_visit(NON_EXISTENT_UUID, ghost_auditor),
            ApiErrorId.ERR_VISIT_NOT_FOUND,
            expected_status=404,
        )

        as_admin = validate_success(
            api_client.get_audit_visit(visit_id, make_headers("BrandAdmin", NON_EXISTENT_UUID))
        )
        assert as_admin["composite_score"] == pytest.approx(90.70, abs=0.01), \
            "an opaque operator identifier is never compared to a row"
        as_integrator = validate_success(
            api_client.get_brand(
                program["brand"]["id"],
                make_headers("ComplianceIntegrator", NON_EXISTENT_UUID),
            )
        )
        assert as_integrator["brand_code"] == TEST_DEFAULTS["BRAND_CODE"]

        action = validate_success(api_client.get_corrective_action(action_id, ADMIN_HEADERS))
        assert action["status"] == "ASSIGNED", "the refused submit left the action untouched"


class TestPeerIsolation:
    def test_a_peer_franchisee_is_refused_on_another_franchisees_resources(self):
        """Ownership answers on all four franchisee writes and on a foreign rescore.

        PRD: "When the acting principal resolves but does not own the target resource, the
        rejection is `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/one_franchisee_cannot_act_on_another_franchisees_resources
        """
        program = setup_filed_dispute(
            item_code="BS-1", requested_points=15, with_reviewer=True,
        )
        action_id = program["actions"]["FS-1"]["id"]
        attach_action_photo(program, action_id, captured_at="2026-08-05T12:30:00Z")

        peer = create_franchisee(
            program["brand"]["id"], legal_name="Lakeshore QSR Group Inc",
            contact_email="ops@lakeshore.test", agreement_signed_at="2025-06-15T00:00:00Z",
        )
        peer_headers = make_franchisee_headers(peer["id"])

        validate_error(
            api_client.submit_corrective_action(
                action_id, peer_headers, {"remediation_note": "Not my store"},
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            expected_status=403,
        )
        validate_error(
            api_client.create_dispute(
                dispute_payload(program["scored"]["FC-1"]["id"], 12), peer_headers,
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            expected_status=403,
        )
        validate_error(
            api_client.withdraw_dispute(
                program["dispute"]["id"], peer_headers, {"note": "Dropping it"},
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            expected_status=403,
        )
        validate_error(
            api_client.create_evidence_photo(
                evidence_photo_payload(
                    "2026-08-05T12:35:00Z", corrective_action_id=action_id,
                    file_uri="s3://ev/peer.jpg",
                ),
                peer_headers,
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            expected_status=403,
        )

        visit = validate_success(
            api_client.get_audit_visit(program["visit"]["id"], ADMIN_HEADERS)
        )
        validate_error(
            api_client.rescore_audit_visit(
                program["visit"]["id"],
                rescore_payload(program["scored"]["FS-1"]["id"], 29, visit["version"]),
                program["reviewer_headers"],
            ),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
            expected_status=403,
        )

        cured = validate_success(
            api_client.submit_corrective_action(
                action_id, program["franchisee_headers"],
                {"remediation_note": "Hood degreased"},
            )
        )
        assert cured["status"] == "SUBMITTED", "the owner's identical call is accepted"
        assert cured["submission_count"] == 1

        action = validate_success(api_client.get_corrective_action(action_id, ADMIN_HEADERS))
        assert action["assigned_franchisee_id"] == program["franchisee"]["id"], \
            "no refused call reassigned the action"


class TestSegregationOfDuties:
    def test_the_scoring_auditor_may_neither_review_nor_shadow_their_own_visit(self):
        """Both expressions of the rule refuse the scorer and admit a second auditor.

        PRD: "On the appeal path, the acting `CalibrationReviewer` must not be the auditor who
        scored the visit that the disputed item belongs to. On the calibration path, a shadow
        visit may not be assigned to the same auditor who performed the visit it shadows. Both
        violations report `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/the_scoring_auditor_may_not_review_their_own_visit_or_shadow_it
        """
        program = setup_filed_dispute(
            item_code="BS-1", requested_points=15, with_reviewer=True,
        )
        dispute_id = program["dispute"]["id"]
        scorer_id = program["auditor"]["id"]
        reviewer_id = program["reviewer"]["id"]
        scorer_in_review_seat = make_calibration_reviewer_headers(scorer_id)
        attach_dispute_photo(program, dispute_id, captured_at="2026-08-05T12:45:00Z")

        validate_error(
            api_client.request_dispute_info(
                dispute_id, request_info_payload(), scorer_in_review_seat,
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            expected_status=403,
        )

        supplemented = validate_success(
            api_client.supplement_dispute(
                dispute_id, program["franchisee_headers"], {"note": "Invoice attached"},
            )
        )
        assert supplemented["status"] == "EVIDENCE_REVIEW", \
            "the only state from which a resolution is legal"

        validate_error(
            api_client.resolve_dispute(
                dispute_id, resolve_dispute_payload("UPHELD"), scorer_in_review_seat,
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            expected_status=403,
        )

        def shadow_candidate(acting_auditor_id):
            return audit_visit_payload(
                program["location"]["id"], acting_auditor_id,
                program["rubric_version"]["id"], LATER_VISIT_START, LATER_VISIT_END,
                visit_type="SHADOW", shadow_of_visit_id=program["visit"]["id"],
            )

        validate_error(
            api_client.create_audit_visit(shadow_candidate(scorer_id), ADMIN_HEADERS),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            expected_status=403,
        )
        accepted = validate_success(
            api_client.create_audit_visit(shadow_candidate(reviewer_id), ADMIN_HEADERS),
            expected_status=201,
        )
        assert accepted["visit_type"] == "SHADOW"
        assert accepted["shadow_of_visit_id"] == program["visit"]["id"]

        reviewed = validate_success(
            api_client.request_dispute_info(
                dispute_id, request_info_payload(), program["reviewer_calibration_headers"],
            )
        )
        assert reviewed["status"] == "INFO_REQUESTED"
        assert reviewed["info_request_count"] == 1
        assert reviewed["reviewer_auditor_id"] == reviewer_id, \
            "the review seat is recorded on the dispute"
        assert reviewed["reviewer_auditor_id"] != scorer_id

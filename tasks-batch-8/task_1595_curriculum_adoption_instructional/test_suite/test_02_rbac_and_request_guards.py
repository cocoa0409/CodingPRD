"""Authentication, authorization, and existence tiers of the request
validation cascade."""
from test_helpers import (
    ANONYMOUS_HEADERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_framework,
    create_cycle,
    setup_cycle_in_pilot_open,
    validate_error,
)

ADMIN = TEST_USERS["district_admin_headers"]
DIRECTOR = TEST_USERS["curriculum_director_headers"]
SECRETARY = TEST_USERS["board_secretary_headers"]
PROCUREMENT = TEST_USERS["procurement_officer_headers"]
TEACHER = TEST_USERS["teacher_headers"]
COMMUNITY = TEST_USERS["community_member_headers"]


class TestAuthenticationTier:
    def test_missing_auth_header_rejected(self, api):
        """PRD §2.1: "A request with a missing header, or whose declared role
        is not one of these nine, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_rejected
        """
        validate_error(api.list_frameworks(ANONYMOUS_HEADERS),
                       ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        validate_error(
            api.create_framework(
                {"code": "FW-1", "subject_area": "MATHEMATICS",
                 "grade_band": "K_5", "standards_required_count": 1,
                 "effective_year": 2026},
                ANONYMOUS_HEADERS),
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestAuthorizationTier:
    def test_rbac_exclusive_operation_denials(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target
        endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §2.7: "Every request is evaluated against an ordered cascade of
        checks; a rejection at an earlier tier masks every later tier."

        Design: Corner/rbac/rbac_exclusive_operation_denials
        """
        framework = create_framework()
        cycle = create_cycle(framework["id"])

        # Teacher creating a framework (DistrictAdmin-only endpoint).
        validate_error(
            api.create_framework(
                {"code": "FW-X", "subject_area": "SCIENCE", "grade_band": "K_5",
                 "standards_required_count": 1, "effective_year": 2026},
                TEACHER),
            ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        # CurriculumDirector posting an award (ProcurementOfficer-only). The
        # quote id does not even exist — authorization fires before existence.
        validate_error(
            api.award(cycle["id"],
                      {"quote_id": NON_EXISTENT_UUID,
                       "expected_cycle_version": cycle["version"]},
                      DIRECTOR),
            ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        # CommunityMember casting a vote (CommitteeMember-only), again on a
        # non-existent challenge id.
        validate_error(
            api.cast_vote(NON_EXISTENT_UUID, {"vote": "UPHOLD"}, COMMUNITY),
            ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        # BoardSecretary posting an appropriation (DistrictAdmin-only).
        validate_error(
            api.post_appropriation(cycle["id"], {"amount": 100}, SECRETARY),
            ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        # ProcurementOfficer creating a distribution order
        # (WarehouseManager-only), on a non-existent material id.
        validate_error(
            api.create_distribution_order(
                {"material_id": NON_EXISTENT_UUID, "school_code": "SCH-A",
                 "classroom_label": "RM-1", "quantity": 1, "need_priority": 1},
                PROCUREMENT),
            ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestExistenceTier:
    def test_entity_not_found_returns_404(self, api):
        """PRD §2.7: "3. Existence: identifiers in the path are validated in
        left-to-right order, then identifiers referenced in the body —
        `framework_id`, `material_id`, `quote_id`, and `target_id` interpreted
        per `target_type` — are resolved (`ERR_NOT_FOUND`; the error message
        names the resource type that was not found)."

        Design: Corner/entities/entity_not_found_returns_404
        """
        missing = "11111111-2222-3333-4444-555555555555"
        validate_error(api.get_material(missing, DIRECTOR),
                       ApiErrorId.ERR_NOT_FOUND)

    def test_existence_beats_state_priority(self, api):
        """PRD §2.7: "Every request is evaluated against an ordered cascade
        of checks; a rejection at an earlier tier masks every later tier."
        PRD §2.7: "3. Existence: identifiers in the path are validated in
        left-to-right order, then identifiers referenced in the body —
        `framework_id`, `material_id`, `quote_id`, and `target_id` interpreted
        per `target_type` — are resolved (`ERR_NOT_FOUND`; the error message
        names the resource type that was not found)."

        Design: Corner/validations/existence_beats_state_priority
        """
        missing = "11111111-2222-3333-4444-555555555555"
        err = validate_error(
            api.transition_material(missing, {"to_state": "VETTED"},
                                    TEST_USERS["instructional_specialist_headers"]),
            ApiErrorId.ERR_NOT_FOUND)
        assert err["error_id"] != ApiErrorId.ERR_INVALID_STATE, (
            "existence (tier 3) must be evaluated before state (tier 5)")

    def test_body_reference_not_found(self, api):
        """PRD §2.7: "3. Existence: identifiers in the path are validated in
        left-to-right order, then identifiers referenced in the body —
        `framework_id`, `material_id`, `quote_id`, and `target_id` interpreted
        per `target_type` — are resolved (`ERR_NOT_FOUND`; the error message
        names the resource type that was not found)."

        Design: Corner/entities/body_reference_not_found
        """
        ctx = setup_cycle_in_pilot_open()
        missing = "99999999-8888-7777-6666-555555555555"
        validate_error(
            api.create_quote(
                ctx["cycle"]["id"],
                {"material_id": missing, "publisher_name": "PubX",
                 "print_unit_price": 10.00, "print_quantity": 5,
                 "digital_seat_rate": 0, "digital_seat_count": 0,
                 "training_sessions": 0, "license_years": 0},
                PROCUREMENT),
            ApiErrorId.ERR_NOT_FOUND)

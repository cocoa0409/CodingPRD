"""Authentication, role authorization, and optimistic concurrency (PRD §2.1, §2.6, §4)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_campus,
    create_rating_payload,
    create_reviewer_payload,
    create_standard_payload,
    create_system,
    create_term,
    get_success_data,
    make_reviewer_headers,
    validate_error,
)

OFFICER = TEST_USERS["officer_headers"]
LEADER = TEST_USERS["leader_headers"]
BURSAR = TEST_USERS["bursar_headers"]


class TestAuthentication:
    def test_missing_headers_rejected_unauthenticated(self, api):
        """PRD §2.1: "A request that arrives without these headers, or whose
        role value is not one of the declared roles, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.5: "Existence checking runs after authentication
        (`ERR_UNAUTHENTICATED`) and authorization (`ERR_FORBIDDEN`)".

        Design: Corner/validations/unauthenticated_missing_headers
        """
        # No X-User-ID / X-User-Role headers at all; the 404 candidate resource
        # must not mask the authentication failure.
        resp = api_client.get_system(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleAuthorization:
    def test_schoolleader_cannot_decide_term(self, api, leader_headers):
        """PRD §2.1: "A request whose role is authenticated but not permitted
        for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.2: "The decision itself belongs to the `AccreditationCommission`,
        which posts an `outcome`."

        Design: Corner/validations/rbac_forbidden_schoolleader_cannot_decide
        """
        system = create_system(name="RBAC County", system_type="SINGLE_SCHOOL")
        create_campus(system["id"], name="Main", enrollment=100)
        term = create_term(system["id"])
        resp = api_client.decide_term(term["id"], {"outcome": "ACCREDITED"},
                                      leader_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_reviewer_cannot_create_standards(self, api, officer_headers):
        """PRD §2.1: "A request whose role is authenticated but not permitted
        for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /accreditation/standards is listed with authorized role
        AccreditationOfficer only.

        Design: Corner/rbac/reviewer_cannot_create_standards
        """
        reviewer = get_success_data(api_client.create_reviewer(
            create_reviewer_payload(full_name="Rev R", email="revr@accreditor.org"),
            officer_headers))
        resp = api_client.create_standard(
            create_standard_payload(code="X1", title="Bad", domain="LEADERSHIP",
                                    weight_pct=100, evidence_min_items=0),
            make_reviewer_headers(reviewer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_bursar_cannot_advance_term(self, api, bursar_headers):
        """PRD §2.1: "A request whose role is authenticated but not permitted
        for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /accreditation/terms/{id}/advance is listed with authorized
        role AccreditationOfficer only.

        Design: Corner/rbac/bursar_cannot_advance_term
        """
        system = create_system(name="Bursar County", system_type="SINGLE_SCHOOL")
        create_campus(system["id"], name="Main", enrollment=100)
        term = create_term(system["id"])
        resp = api_client.advance_term(term["id"], bursar_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestOptimisticConcurrency:
    def test_stale_term_version_on_rating_create(self, api, leader_headers):
        """PRD §2.6: "Creating a `SelfStudyRating` requires the request body to
        carry `expected_term_version`, the client-observed `version` of the
        target `AccreditationTerm`. If the term's current `version` no longer
        matches — because, for instance, another writer advanced the term from
        `PREPARATION` to `SELF_STUDY` after the client last read it — the create
        is rejected with `ERR_STALE_TERM_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_term_version_on_rating_create
        """
        std_l1 = get_success_data(api_client.create_standard(
            create_standard_payload(code="L1", title="Leadership 1",
                                    domain="LEADERSHIP", weight_pct=100,
                                    evidence_min_items=0), OFFICER))
        std_t1 = get_success_data(api_client.create_standard(
            create_standard_payload(code="T1", title="Teaching 1",
                                    domain="LEARNING", weight_pct=100,
                                    evidence_min_items=0), OFFICER))
        system = create_system(name="OCC County", system_type="SINGLE_SCHOOL")
        campus = create_campus(system["id"], name="Main", enrollment=100)
        term = create_term(system["id"])
        observed = term["version"]

        # First create against the observed version succeeds and mutates the
        # term (PRD §2.6: every mutation increments version by exactly 1).
        ok_payload = create_rating_payload(
            term_id=term["id"], campus_id=campus["id"], standard_id=std_l1["id"],
            rating=3, expected_term_version=observed)
        get_success_data(api_client.create_rating(ok_payload, leader_headers))

        # Replaying the same observed version is now stale.
        stale_payload = create_rating_payload(
            term_id=term["id"], campus_id=campus["id"], standard_id=std_t1["id"],
            rating=3, expected_term_version=observed)
        resp = api_client.create_rating(stale_payload, leader_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_TERM_VERSION)

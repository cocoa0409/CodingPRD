"""RBAC denials, authentication, and existence-before-state ordering on
cross-reference writes (PRD §2.1, §2.7, §2.8, §4)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    SAFE_CLOCK,
    ApiErrorId,
    create_farm_payload,
    create_farm_with_member,
    make_producer_headers,
    set_clock,
    validate_error,
    validate_success,
)


@pytest.fixture
def specialist(county_specialist_headers):
    return county_specialist_headers


@pytest.fixture
def ced(county_executive_director_headers):
    return county_executive_director_headers


@pytest.fixture
def committee(county_committee_headers):
    return county_committee_headers


class TestRbacDenials:
    def test_producer_cannot_certify_own_report_rbac(self, api, specialist):
        """PRD §2.1: "If the role named in `X-User-Role` is not permitted to
        invoke the endpoint, the request is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4: "| POST | /fsa/acreage-reports/{report_id}/certify | Certify a
        filed report (SoD) | CountySpecialist |"

        Design: Corner/endpoints/producer_cannot_certify_own_report_rbac
        """
        set_clock(SAFE_CLOCK)
        farm, producer, _ = create_farm_with_member()
        producer_headers = make_producer_headers(producer["id"])
        report = validate_success(
            api.create_acreage_report(
                farm["id"], {"program_year": 2026}, producer_headers
            ),
            201,
        )
        resp = api.certify_acreage_report(report["id"], producer_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_county_specialist_cannot_ced_approve(self, api, specialist, ced):
        """PRD §2.1: "If the role named in `X-User-Role` is not permitted to
        invoke the endpoint, the request is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4: "| POST | /fsa/enrollments/{enrollment_id}/ced-approve | CED
        approval (AGI + conservation gates) | CountyExecutiveDirector |"

        Design: Corner/endpoints/county_specialist_cannot_ced_approve
        """
        farm, producer, _ = create_farm_with_member()
        enrollment = validate_success(
            api.create_enrollment(
                farm["id"],
                {"program_year": 2026, "commodity": "CORN"},
                make_producer_headers(producer["id"]),
            ),
            201,
        )
        resp = api.ced_approve_enrollment(enrollment["id"], specialist)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_county_committee_cannot_create_farm(self, api, committee):
        """PRD §2.1: "If the role named in `X-User-Role` is not permitted to
        invoke the endpoint, the request is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4: "| POST | /fsa/farms | Create a farm record | CountySpecialist |"

        Design: Corner/rbac/county_committee_cannot_create_farm
        """
        resp = api.create_farm(
            create_farm_payload(farm_number="F24", county_code="019", program_year=2026),
            committee,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


class TestAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "Every request carries two headers: `X-User-ID` and
        `X-User-Role`. If either header is missing or malformed the request is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.8: "The ordering matters because it determines which error a
        multi-violation request surfaces: a request that is both unauthenticated
        and malformed returns `ERR_UNAUTHENTICATED`"

        Design: Corner/rbac/missing_auth_headers_unauthenticated
        """
        resp = api.get_farm(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


class TestExistenceBeforeState:
    def test_appeal_against_nonexistent_enrollment_returns_not_found(
        self, api, specialist
    ):
        """PRD §2.7: "Every path id and every foreign key referenced in the
        request body must resolve to an existing entity; any unresolvable
        reference is rejected with `ERR_NOT_FOUND` (HTTP 404)."
        PRD §2.8: "then existence resolution of every path id and body foreign
        key, then the state-machine check that the target resource is in a state
        from which the requested transition is defined"

        Design: Corner/validations/acreage_certify_segregation_of_duties
        """
        set_clock(SAFE_CLOCK)
        farm, producer, _ = create_farm_with_member()
        resp = api.file_appeal(
            {
                "farm_id": farm["id"],
                "enrollment_id": NON_EXISTENT_UUID,
                "ground_code": "FACTUAL_ERROR",
                "filed_by_producer_id": producer["id"],
            },
            make_producer_headers(producer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

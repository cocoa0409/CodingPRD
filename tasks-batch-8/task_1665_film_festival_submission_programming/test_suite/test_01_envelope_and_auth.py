"""Response envelope, authentication, and role/ownership boundaries (PRD §2)."""
import pytest

from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, build_user_headers,
    create_edition_payload,
    make_filmmaker_headers, make_programmer_headers,
    st_advance, st_assign, st_edition, st_film, st_programmer, st_rule,
    st_submitter,
    validate_error, validate_success,
)

MISSING = NON_EXISTENT_UUID


class TestResponseEnvelope:
    def test_envelope_shape_success_and_error(self, api, admin_headers):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body" and
        "All error API responses (4xx status codes) follow this standard
        envelope format" with "data": {"error_id", "message"}; the
        `api_request_id` "is a server-generated unique identifier for the
        request that starts with `req_`".

        Design: Corner/endpoints/response_envelope_shape_success_and_error
        """
        create_resp = api.create_edition(create_edition_payload(), admin_headers)
        assert create_resp.status_code == 201
        body = create_resp.json()
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["response_type"] == "object"
        assert isinstance(body["data"]["id"], str) and body["data"]["id"]

        missing_resp = api.get_edition(MISSING, admin_headers)
        err_body = missing_resp.json()
        assert missing_resp.status_code == 404
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        assert err_body["data"]["message"].strip()


class TestAuthentication:
    def test_create_edition_missing_auth_headers(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/create_edition_missing_auth_headers
        """
        resp = api.create_edition(create_edition_payload(), headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_filmmaker_cannot_create_edition(self, api):
        """PRD §2.1: "A request whose role is not in the target endpoint's
        authorized role list is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)." PRD §4 grants POST /festival/editions to FESTIVAL_ADMIN.

        Design: Corner/validations/filmmaker_cannot_create_edition_unauthorized
        """
        submitter = st_submitter()
        headers = build_user_headers(submitter["id"], "FILMMAKER")
        resp = api.create_edition(create_edition_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)

    def test_edition_get_not_found(self, api, admin_headers):
        """PRD §2.10: "the request is rejected with `ERR_NOT_FOUND` (HTTP 404)
        at the first identifier that does not resolve to an existing resource."

        Design: Corner/entities/edition_get_not_found
        """
        resp = api.get_edition(MISSING, admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestRbacMatrix:
    """Role gate fires before path resolution (PRD §2.9 ordering: shape, then
    authentication, then role, then path-templated resource existence), so a
    wrong-role call on a nonexistent id still fails 403."""

    WRONG_ROLE_CALLS = [
        ("lock slate as PROGRAM_CHAIR",
         lambda api: api.lock_slate(MISSING, build_user_headers("chair-1", "PROGRAM_CHAIR"))),
        ("approve travel as SCHEDULING_OPS",
         lambda api: api.approve_travel_package(MISSING, 1, build_user_headers("ops-1", "SCHEDULING_OPS"))),
        ("create award as JUROR",
         lambda api: api.create_award(
             {"edition_id": MISSING, "name": "X", "section": "SHORTS",
              "prize_cents": 1, "assigned_juror_ids": [MISSING]},
             build_user_headers("j-1", "JUROR"))),
        ("advance edition as TRAVEL_COORDINATOR",
         lambda api: api.advance_edition(MISSING, "INTAKE_OPEN", build_user_headers("travel-1", "TRAVEL_COORDINATOR"))),
        ("recuse assignment as FILMMAKER",
         lambda api: api.recuse_assignment(MISSING, build_user_headers(MISSING, "FILMMAKER"))),
        ("sign agreement as PROGRAM_CHAIR",
         lambda api: api.sign_agreement(MISSING, build_user_headers("chair-1", "PROGRAM_CHAIR"))),
        ("create venue as AWARDS_ADMIN",
         lambda api: api.create_venue(
             {"edition_id": MISSING, "name": "V", "seat_capacity": 1,
              "formats_supported": ["DCP_2K"]},
             build_user_headers("awards-1", "AWARDS_ADMIN"))),
    ]

    @pytest.mark.parametrize("label,call", WRONG_ROLE_CALLS,
                             ids=[c[0] for c in WRONG_ROLE_CALLS])
    def test_wrong_role_denied_everywhere(self, api, label, call):
        """PRD §2.9: "Third, the role is checked against the endpoint's
        authorized list (`ERR_UNAUTHORIZED_ROLE`). Fourth, path-templated
        resources are resolved left to right (`ERR_NOT_FOUND`)."

        Design: Corner/rbac/rbac_denial_matrix_wrong_role_everywhere
        """
        resp = call(api)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)

    def test_shared_read_spotcheck(self, api, admin_headers):
        """PRD §4: GET /festival/editions/{id} is open to "All authenticated
        roles", and §4 defines that phrase as "every role in §2.1 except
        `PUBLIC`"; a role not in the endpoint's list is rejected with
        `ERR_UNAUTHORIZED_ROLE` (§2.1).

        Design: Corner/rbac/rbac_shared_read_spotcheck
        """
        ctx = st_edition(with_config=False)
        edition_id = ctx["edition"]["id"]
        for role, uid in (("PROGRAMMER", "p-x"), ("JUROR", "j-x"),
                          ("TRAVEL_COORDINATOR", "t-x")):
            data = validate_success(
                api.get_edition(edition_id, build_user_headers(uid, role))
            )
            assert data["id"] == edition_id
        denied = api.get_edition(edition_id, build_user_headers("pub-1", "PUBLIC"))
        validate_error(denied, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)


class TestOwnershipBoundaries:
    def test_ownership_boundaries_for_filmmaker_and_programmer(self, api):
        """PRD §2.1: "An entity-backed actor operating on a resource they do
        not own is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)";
        §3.4: "the caller's `X-User-ID` must equal the assignment's
        `programmer_id`, failing with `ERR_FORBIDDEN_OWNERSHIP`"; §3.2: a
        filmmaker "may read only their own submission by id".

        Design: Corner/validations/ownership_boundaries_for_filmmaker_and_programmer
        """
        ctx = st_edition()
        st_advance(ctx, "INTAKE_OPEN")
        owner = st_submitter({"legal_name": "Ann Ash", "email": "ann@example.com"})
        other = st_submitter({"legal_name": "Bob Ray", "email": "bob@example.com"})
        film = st_film(ctx, owner, {"title": "Owned"})
        st_rule(ctx, film["id"], "ELIGIBLE")
        st_advance(ctx, "INTAKE_CLOSED")
        st_advance(ctx, "SCREENING")
        p1 = st_programmer({"display_name": "S1"})
        p2 = st_programmer({"display_name": "S2"})
        assignment = st_assign(film["id"], p1["id"])

        resp_other_read = api.get_submission(
            film["id"], make_filmmaker_headers(other["id"])
        )
        validate_error(resp_other_read, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value)

        resp_wrong_scorer = api.create_score(
            assignment["id"],
            {"originality": 5, "craft": 5, "story": 5, "overall": 5,
             "recommendation": "NEUTRAL"},
            make_programmer_headers(p2["id"]),
        )
        validate_error(resp_wrong_scorer, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value)

        own = validate_success(
            api.get_submission(film["id"], make_filmmaker_headers(owner["id"]))
        )
        assert own["id"] == film["id"]

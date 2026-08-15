"""Authentication, role authorization, and segregation of duties (PRD §2.1, §2.8)."""
from test_helpers import (
    ApiErrorId,
    admin_headers,
    api_client,
    as_insider,
    as_member,
    as_officer,
    create_attestation_payload,
    create_covered_person_payload,
    create_current_person,
    create_officer,
    create_person,
    create_submitted_exception,
    create_submitted_request,
    decide_request,
    get_success_data,
    make_committee_member_headers,
    set_logical_clock,
    validate_error,
    validate_success,
)


class TestAuthentication:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request with a missing header, a malformed header, or an
        unrecognized role value is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/request_missing_auth_headers
        """
        resp = api.create_covered_person(
            create_covered_person_payload(
                full_name="No Headers",
                email="noheaders@x.com",
                designation="EMPLOYEE",
                department="Ops",
            ),
            headers=None,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleAuthorization:
    def test_insider_cannot_review_request(self, api):
        """PRD §2.1: "A request whose declared role is not permitted on the target
        endpoint — including an `Insider` attempting to act on a resource owned by
        another covered person — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §3.4: "Review is a two-step officer workflow."

        Design: Corner/rbac/insider_cannot_review_request_unauthorized
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        person = create_current_person("Insider R1", "insider_r1@x.com")
        req = create_submitted_request(person, proposed_trade_date="2026-08-20T00:00:00Z")

        resp = api.review_preclearance_request(req["id"], as_insider(person))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        fresh = get_success_data(api.get_preclearance_request(req["id"], admin_headers()))
        assert fresh["status"] == "SUBMITTED"

    def test_committee_member_cannot_ingest_confirmation(self, api):
        """PRD §2.1: "A request whose declared role is not permitted on the target
        endpoint — including an `Insider` attempting to act on a resource owned by
        another covered person — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §3.7: "A compliance officer ingests a broker confirmation carrying the
        executing insider's `covered_person_id`".

        Design: Corner/rbac/committee_member_cannot_ingest_confirmation
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        member = create_person("Member R2", "member_r2@x.com", designation="DIRECTOR",
                               department="Board")
        resp = api.create_trade_confirmation(
            {
                "covered_person_id": member["id"],
                "security_ticker": "ACME",
                "trade_side": "BUY",
                "quantity": 10,
                "price": 10.00,
                "trade_date": "2026-08-01T10:00:00Z",
                "broker_ref": "BR-C-R2",
            },
            as_member(member),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_insider_cannot_complete_others_attestation(self, api):
        """PRD §3.1: "The assignee — acting as an `Insider`, so `X-User-ID` must equal
        the attestation's `covered_person_id` — completes it". PRD §2.1: "A request
        whose declared role is not permitted on the target endpoint — including an
        `Insider` attempting to act on a resource owned by another covered person —
        is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/insider_cannot_complete_others_attestation
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        owner = create_person("Owner A", "owner_a@x.com", department="A")
        other = create_person("Other B", "other_b@x.com", department="B")
        att = get_success_data(
            api.create_attestation(
                create_attestation_payload(
                    covered_person_id=owner["id"], kind="POLICY_ACK",
                    period_year=2026, due_date="2026-12-31T00:00:00Z",
                ),
                admin_headers(),
            ),
            expected_status=201,
        )
        resp = api.complete_attestation(att["id"], as_insider(other))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        fresh = get_success_data(api.get_attestation(att["id"], admin_headers()))
        assert fresh["status"] == "ASSIGNED"


class TestSegregationOfDuties:
    def test_officer_cannot_decide_own_request(self, api):
        """PRD §2.8: "A violation of this rule is rejected with
        `ERR_SELF_ACTION_FORBIDDEN` (HTTP 403). This applies even where the actor's
        role would otherwise entitle them to the operation: an officer who submitted
        a request as an insider cannot then approve it wearing an officer's hat, and
        a committee member cannot vote on their own hardship request."

        Design: Corner/rbac/officer_cannot_decide_own_request_forbidden
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        owner_officer = create_current_person("Officer Owner", "officer_owner@x.com",
                                              department="Legal")
        req = create_submitted_request(
            owner_officer, proposed_trade_date="2026-08-20T00:00:00Z"
        )
        reviewed = get_success_data(
            api.review_preclearance_request(req["id"], as_officer(owner_officer))
        )
        resp = decide_request(reviewed, owner_officer, "APPROVE", reviewed["version"])
        validate_error(resp, ApiErrorId.ERR_SELF_ACTION_FORBIDDEN)
        fresh = get_success_data(api.get_preclearance_request(req["id"], admin_headers()))
        assert fresh["status"] == "UNDER_REVIEW"

    def test_member_cannot_vote_own_exception(self, api):
        """PRD §3.5: "a member voting on their own hardship request violates
        segregation of duties (`ERR_SELF_ACTION_FORBIDDEN`)". PRD §2.8: "a committee
        member cannot vote on their own hardship request."

        Design: Corner/rbac/member_cannot_vote_own_exception_forbidden
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        member_owner = create_person("Member Owner", "member_owner@x.com",
                                     designation="DIRECTOR", department="Board")
        exc = create_submitted_exception(member_owner, quantity=100)
        resp = api.vote_exception_request(
            exc["id"], {"vote": "APPROVE"}, as_member(member_owner)
        )
        validate_error(resp, ApiErrorId.ERR_SELF_ACTION_FORBIDDEN)
        fresh = get_success_data(api.get_exception_request(exc["id"], admin_headers()))
        assert fresh["votes_for"] == 0

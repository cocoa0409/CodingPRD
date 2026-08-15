"""Corner queue: authentication, RBAC denials, validation priority, EXITING fencing, SoD."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    adopted_capital_call,
    api_client,
    capital_call_payload,
    cast_vote,
    close_motion,
    comp_policy_payload,
    create_and_open_motion,
    create_committee,
    add_member,
    create_motion,
    create_motion_payload,
    create_physician,
    create_policy,
    create_shareholder,
    file_coi_disclosure,
    get_motion,
    get_policy,
    initiate_exit,
    make_compliance_officer_headers,
    make_physician_headers,
    open_motion,
    propose_motion,
    review_coi_disclosure,
    validate_error,
)


class TestMissingRoleHeaderUnauthenticated:
    def test_no_role_header_rejected_401(self, api):
        """PRD §2.1: "A missing or unrecognized `X-User-Role`, or a missing
        `X-User-ID` where the role requires one, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.7: "First, authentication: the role header must be present and
        recognized, and the user id must be present for the entity-backed physician
        role (`ERR_UNAUTHENTICATED`)."

        Design: Corner/validations/missing_role_header_unauthenticated
        """
        create_policy(total_shares_authorized=1000000)
        resp = api_client.list_physicians(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestShapeValidationBeatsRoleCheck:
    def test_malformed_body_from_wrong_role_gets_shape_error(self, api):
        """PRD §2.7: "Every request is validated in a fixed priority order, and the
        first failure wins. First, authentication: the role header must be present and
        recognized, and the user id must be present for the entity-backed physician
        role (`ERR_UNAUTHENTICATED`). Second, request shape: required fields present,
        enum values valid, amounts positive integers, and the payload sub-fields
        required by the motion type present (`ERR_INVALID_REQUEST`). Third, role
        permission on the endpoint (`ERR_FORBIDDEN`)."
        A Physician creating a physician with a missing `hire_date` fails shape
        (second) before role permission (third).

        Design: Corner/validations/shape_validation_beats_role_check
        """
        create_policy(total_shares_authorized=1000000)
        p = create_physician(full_name="Dr P", hire_date="2024-01-01T00:00:00Z")
        resp = api_client.create_physician(
            {"full_name": "Dr Orphan"}, make_physician_headers(p["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestExistenceBeatsStateOnVote:
    def test_vote_on_nonexistent_motion_is_404(self, api):
        """PRD §2.7: "Fifth, existence: path identifiers are validated left to right,
        and foreign keys referenced in the body must resolve (`ERR_NOT_FOUND`).
        Sixth, state gates: the target resource must be in a status that permits the
        operation — the various state errors described in §3."
        A ballot on a nonexistent motion id resolves existence before any state gate.

        Design: Corner/validations/existence_beats_state_on_vote
        """
        create_policy(total_shares_authorized=1000000)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        resp = api_client.cast_vote(
            NON_EXISTENT_UUID, {"vote_choice": "FOR"}, make_physician_headers(a["id"])
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPhysicianExitingBlocked:
    def test_exiting_blocked_from_offer_and_sponsorship(self, api):
        """PRD §3.1: "An `EXITING` physician is in a wind-down state and is blocked
        from two activities: receiving new buy-in offers and sponsoring motions — both
        are rejected with `ERR_PHYSICIAN_EXITING`."

        Design: Corner/validations/physician_exiting_blocked_from_offer_and_sponsorship
        """
        create_policy(total_shares_authorized=1000000)
        x = create_shareholder("Dr X", 1000, "2010-01-01T00:00:00Z")
        initiate_exit(x["id"], "VOLUNTARY")

        resp = api_client.create_buy_in_offer(
            {"physician_id": x["id"], "target_tier": "SHAREHOLDER",
             "share_grant": 100, "installment_count": 1},
            TEST_USERS["board_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PHYSICIAN_EXITING)

        resp = api_client.create_motion(
            create_motion_payload(
                "CAPITAL_CALL", x["id"], capital_call_payload(50000, purpose="Blocked")
            ),
            make_physician_headers(x["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PHYSICIAN_EXITING)


class TestSegregationOfDutiesCompPolicy:
    def test_chair_cannot_sponsor_and_sponsor_cannot_vote(self, api):
        """PRD §3.4: "and segregation of duties forbids the sponsor from voting on
        their own `COMP_POLICY` motion, and forbids the `CHAIR` of the `COMPENSATION`
        committee from sponsoring a `COMP_POLICY` motion at all
        (`ERR_SEGREGATION_OF_DUTIES`)."
        PRD §3.4: "An adopted `COMP_POLICY` writes `new_bonus_pool_pct` onto the
        policy's `bonus_pool_pct`, increments `comp_policy_version` by 1, and bumps the
        policy's `version`."

        Design: Corner/validations/segregation_of_duties_comp_policy
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        s = create_shareholder("Dr S", 1000, "2014-01-01T00:00:00Z")
        t = create_shareholder("Dr T", 1000, "2015-01-01T00:00:00Z")
        u = create_shareholder("Dr U", 1000, "2016-01-01T00:00:00Z")
        committee = create_committee(
            name="Compensation Committee", committee_type="COMPENSATION", quorum_count=1
        )
        add_member(committee["id"], s["id"], "CHAIR")

        resp = api_client.create_motion(
            create_motion_payload("COMP_POLICY", s["id"], comp_policy_payload(0.30)),
            make_physician_headers(s["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        motion = create_motion("COMP_POLICY", t, comp_policy_payload(0.30))
        propose_motion(motion["id"], t)
        open_motion(motion["id"], t)

        resp = api_client.cast_vote(
            motion["id"], {"vote_choice": "FOR"}, make_physician_headers(t["id"])
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        cast_vote(motion["id"], u, "FOR")
        closed = close_motion(motion["id"])
        assert closed["status"] == "ADOPTED"
        policy = get_policy()
        assert policy["bonus_pool_pct"] == pytest.approx(0.30)
        assert policy["comp_policy_version"] == 1


class TestTreasuryShareCapOnFounding:
    def test_founding_beyond_treasury_rejected(self, api):
        """PRD §3.1: "A physician created with `founding_shareholder` set to true
        enters directly as a `SHAREHOLDER` holding `initial_shares` — which must then
        be at least 1 — and those shares are debited from treasury; if the treasury
        does not hold enough shares the onboarding is rejected with
        `ERR_INSUFFICIENT_TREASURY_SHARES`."

        Design: Corner/validations/treasury_share_cap_on_founding_and_buyin
        """
        create_policy(total_shares_authorized=1000)
        create_shareholder("Dr P1", 800, "2010-01-01T00:00:00Z")
        resp = api_client.create_physician(
            {"full_name": "Dr P2", "hire_date": "2011-01-01T00:00:00Z",
             "founding_shareholder": True, "initial_shares": 300},
            TEST_USERS["board_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_TREASURY_SHARES)
        assert get_policy()["treasury_shares"] == 200


class TestPhysicianCannotAdminister:
    def test_physician_denied_admin_exclusives(self, api):
        """PRD §2.1: "A well-authenticated caller whose role is not permitted on the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: creating physicians, creating board seats, and creating the policy are
        BoardAdmin-only rows in the endpoint table.

        Design: Corner/rbac/physician_cannot_administer_forbidden
        """
        create_policy(total_shares_authorized=1000000)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        a_headers = make_physician_headers(a["id"])

        resp = api_client.create_physician(
            {"full_name": "Dr Rogue", "hire_date": "2020-01-01T00:00:00Z"}, a_headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        resp = api_client.create_board_seat(
            {"seat_label": "SEAT-X", "seat_class": "AT_LARGE"}, a_headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        resp = api_client.create_policy({"total_shares_authorized": 5}, a_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestComplianceOfficerExclusiveCoiReview:
    def test_admin_cannot_review_and_co_cannot_bill(self, api):
        """PRD §2.1: "Segregation of duties is structural: only a `ComplianceOfficer`
        may review a conflict-of-interest disclosure, so the filer of a disclosure is
        never its reviewer, and a `BoardAdmin` who can do almost everything else still
        cannot review disclosures."
        PRD §2.1: "A well-authenticated caller whose role is not permitted on the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.7: "the reviewer's `X-User-ID` is recorded as `reviewed_by`."

        Design: Corner/rbac/compliance_officer_exclusive_coi_review
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        b = create_shareholder("Dr B", 1000, "2016-01-01T00:00:00Z")
        motion = create_and_open_motion(
            "CAPITAL_CALL", a, capital_call_payload(50000, purpose="RBAC")
        )
        disclosure = file_coi_disclosure(b, "Review target", related_motion_id=motion["id"])
        cast_vote(motion["id"], a, "FOR")
        close_motion(motion["id"])
        _m, call = adopted_capital_call(a, 50000, purpose="RBAC")

        resp = api_client.review_coi_disclosure(
            disclosure["id"], {"outcome": "CLEARED"}, TEST_USERS["board_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        resp = api_client.bill_capital_call(
            call["id"], make_compliance_officer_headers("co-1")
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        reviewed = review_coi_disclosure(disclosure["id"], "CLEARED")
        assert reviewed["status"] == "CLEARED"
        assert reviewed["reviewed_by"] == "co-1"


class TestPhysicianCloseMotionForbidden:
    def test_sponsor_physician_cannot_close(self, api):
        """PRD §3.4: "Closing a motion is a `BoardAdmin` act with two gates, checked
        in order."
        PRD §2.1: "A well-authenticated caller whose role is not permitted on the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/physician_close_motion_forbidden
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        motion = create_and_open_motion(
            "CAPITAL_CALL", a, capital_call_payload(50000, purpose="RBAC close")
        )
        cast_vote(motion["id"], a, "FOR")
        resp = api_client.close_motion(motion["id"], make_physician_headers(a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_motion(motion["id"])["status"] == "OPEN"

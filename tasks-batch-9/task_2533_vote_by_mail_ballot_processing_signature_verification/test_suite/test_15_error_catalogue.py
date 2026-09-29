"""Error catalogue corners: the authentication gate, the two typed 404s that are
not the generic record 404, and the state guards that make a replayed write safe.
"""
import pytest

from test_helpers import (
    ADMIN,
    CLERK,
    SUPERVISOR,
    ApiErrorId,
    api_client,
    build_user_headers,
    check_in_observer,
    create_trained_reviewer,
    get_election,
    get_envelope,
    make_observer_headers,
    make_signature_reviewer_headers,
    schedule_observer_session,
    set_clock,
    setup_accepted_envelope,
    setup_completed_remake,
    setup_election,
    setup_received_envelopes,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_REVIEWER_ID = "00000000-0000-0000-0000-0000000000aa"
UNKNOWN_ENVELOPE_ID = "00000000-0000-0000-0000-0000000000bb"

MALFORMED_IDENTITIES = [
    ("role_header_absent", {"X-User-ID": "someone",
                            "Content-Type": "application/json"}),
    ("role_header_empty", build_user_headers("someone", "")),
    ("role_outside_the_five", build_user_headers("someone", "BallotClerk")),
    ("user_id_header_absent", {"X-User-Role": "ElectionsClerk",
                               "Content-Type": "application/json"}),
    ("user_id_header_empty", build_user_headers("", "ElectionsClerk")),
]


class TestAuthenticationGate:
    @pytest.mark.parametrize("label,headers",
                             MALFORMED_IDENTITIES,
                             ids=[case[0] for case in MALFORMED_IDENTITIES])
    def test_missing_or_unknown_role_header_returns_unauthenticated(self, label, headers):
        """An absent, empty or undeclared identity header is an authentication failure,
        which outranks the authorisation gate, while a well-formed clerk read succeeds.

        PRD: "If either header is absent or empty, or if `X-User-Role` is not one of the
        five declared role names, the request is rejected with `ERR_UNAUTHENTICATED`."
        Design: Corner/errors/missing_or_unknown_role_header_returns_unauthenticated
        """
        election = setup_election(clock="2026-09-10T09:00:00Z")

        validate_error(api_client.get_election(election["id"], headers),
                       ApiErrorId.ERR_UNAUTHENTICATED, 401)

        allowed = validate_success(api_client.get_election(election["id"], CLERK), 200)
        assert allowed["id"] == election["id"], \
            "the same read is served once the identity headers are well formed"


class TestTypedNotFound:
    def test_unknown_reviewer_ids_return_reviewer_not_found(self):
        """A bogus reviewer identifier is a reviewer-shaped 404 both on a direct read
        and inside a remake body, where existence is resolved before team composition.

        PRD: "a reviewer identifier — including either of the two remake team member
        identifiers — yields `ERR_REVIEWER_NOT_FOUND`"
        Design: Corner/errors/unknown_reviewer_ids_return_reviewer_not_found
        """
        bundle = setup_received_envelopes(count=1)
        envelope = get_envelope(bundle["envelopes"][0]["id"])
        member_a = create_trained_reviewer(full_name="Bo Reyes", party_affiliation="REP")

        validate_error(api_client.get_reviewer(UNKNOWN_REVIEWER_ID, ADMIN),
                       ApiErrorId.ERR_REVIEWER_NOT_FOUND, 404)

        payload = {
            "team_member_a_reviewer_id": member_a["id"],
            "team_member_b_reviewer_id": UNKNOWN_REVIEWER_ID,
            "reason_code": "DAMAGED",
            "session_start_at": "2026-11-03T13:00:00Z",
            "session_end_at": "2026-11-03T14:00:00Z",
            "expected_envelope_version": envelope["version"],
        }
        validate_error(api_client.create_remake(envelope["id"], payload, SUPERVISOR),
                       ApiErrorId.ERR_REVIEWER_NOT_FOUND, 404)

        _, meta = validate_paginated(api_client.list_remake_records(
            SUPERVISOR, params={"original_envelope_id": envelope["id"]}))
        assert meta["total_count"] == 0

        after = get_envelope(envelope["id"])
        assert after["version"] == envelope["version"], \
            "a refused remake never bumps the envelope"
        assert after["custody_status"] == "SEALED"

    def test_separation_run_with_an_unknown_envelope_id_returns_envelope_not_found(self):
        """The submitted identifier array is resolved in order, so an unresolvable
        element is reported before the pool cardinality rule can bite.

        PRD: "Every listed envelope is resolved in array order, and the first
        identifier that resolves to nothing yields `ERR_ENVELOPE_NOT_FOUND`."
        Design: Corner/errors/separation_run_with_an_unknown_envelope_id_returns_envelope_not_found
        """
        bundle = setup_received_envelopes(count=1)
        election_id = bundle["election"]["id"]
        envelope_id = bundle["envelopes"][0]["id"]

        payload = {"return_envelope_ids": [envelope_id, UNKNOWN_ENVELOPE_ID]}
        validate_error(
            api_client.create_separation_run(election_id, payload, SUPERVISOR),
            ApiErrorId.ERR_ENVELOPE_NOT_FOUND, 404)

        envelope = get_envelope(envelope_id)
        assert envelope["custody_status"] == "SEALED"
        assert envelope["separation_run_sequence"] is None

        election = get_election(election_id)
        assert election["separation_run_sequence"] == 0


class TestSignatureStateGuards:
    def test_cure_notice_on_an_accepted_envelope_returns_signature_state_invalid(self):
        """An accepted signature is settled: no cure notice may be issued against it and
        no further review round may be opened on it.

        PRD: "A clerk issues one against an envelope whose `signature_status` is
        `CURE_REQUIRED` — any other signature state is refused with
        `ERR_ENVELOPE_SIGNATURE_STATE_INVALID`"
        Design: Corner/errors/cure_notice_on_an_accepted_envelope_returns_signature_state_invalid
        """
        bundle = setup_accepted_envelope(similarity_score=95)
        envelope_id = bundle["envelope"]["id"]
        reviewer_id = bundle["review"]["reviewer_id"]
        assert bundle["envelope"]["signature_status"] == "ACCEPTED"

        validate_error(api_client.create_cure_notice(envelope_id, CLERK),
                       ApiErrorId.ERR_ENVELOPE_SIGNATURE_STATE_INVALID, 409)
        validate_error(api_client.open_signature_review(envelope_id, CLERK),
                       ApiErrorId.ERR_ENVELOPE_SIGNATURE_STATE_INVALID, 409)

        _, notices = validate_paginated(api_client.list_cure_notices(
            CLERK, params={"return_envelope_id": envelope_id}))
        assert notices["total_count"] == 0

        election = get_election(bundle["election"]["id"])
        assert election["open_cure_count"] == 0

        _, reviews = validate_paginated(api_client.list_signature_reviews(
            CLERK, params={"return_envelope_id": envelope_id}))
        assert reviews["total_count"] == 1, "the refused round was never created"

        envelope = get_envelope(envelope_id)
        assert envelope["review_round_count"] == 1
        assert envelope["signature_status"] == "ACCEPTED"

        reviewer = validate_success(api_client.get_reviewer(reviewer_id, ADMIN), 200)
        assert reviewer["active_review_count"] == 0
        assert reviewer["completed_review_count"] == 1

    def test_second_decision_on_the_same_review_returns_review_already_submitted(self):
        """A submitted review is a closed record: replaying a different decision on it
        is refused and leaves the first decision and its resolved envelope untouched.

        PRD: "The review must be in `ASSIGNED`; a second submission on the same review,
        or one on a review already voided, is rejected with
        `ERR_REVIEW_ALREADY_SUBMITTED`."
        Design: Corner/errors/second_decision_on_the_same_review_returns_review_already_submitted
        """
        bundle = setup_accepted_envelope(similarity_score=80)
        review = bundle["review"]
        reviewer_headers = make_signature_reviewer_headers(review["reviewer_id"])
        assert review["status"] == "SUBMITTED"
        assert review["confidence_score"] == 0.8

        validate_error(api_client.submit_signature_decision(
            review["id"], {"decision": "NO_MATCH", "similarity_score": 40},
            reviewer_headers), ApiErrorId.ERR_REVIEW_ALREADY_SUBMITTED, 409)

        replayed = validate_success(
            api_client.get_signature_review(review["id"], CLERK), 200)
        assert replayed["status"] == "SUBMITTED"
        assert replayed["decision"] == "MATCH"
        assert replayed["similarity_score"] == 80
        assert replayed["confidence_score"] == 0.8

        envelope = get_envelope(bundle["envelope"]["id"])
        assert envelope["signature_status"] == "ACCEPTED"
        assert envelope["review_round_count"] == 1

        reviewer = validate_success(
            api_client.get_reviewer(review["reviewer_id"], ADMIN), 200)
        assert reviewer["active_review_count"] == 0
        assert reviewer["completed_review_count"] == 1


class TestTerminalStateReplays:
    def test_second_completion_of_a_remake_returns_remake_state_invalid(self):
        """Completion is once-only: a second completion carrying a different serial is
        refused, so exactly one replacement ballot ever exists for the session.

        PRD: "It requires the record to be in `OPEN`, else `ERR_REMAKE_STATE_INVALID`"
        Design: Corner/errors/second_completion_of_a_remake_returns_remake_state_invalid
        """
        bundle = setup_completed_remake(remade_serial="RM-0001")
        remake = bundle["remake"]
        assert remake["status"] == "COMPLETED"
        assert remake["remade_serial"] == "RM-0001"
        replacement_id = bundle["replacement"]["id"]

        validate_error(api_client.complete_remake(
            remake["id"], {"remade_serial": "RM-0002"}, SUPERVISOR),
            ApiErrorId.ERR_REMAKE_STATE_INVALID, 409)

        reread = validate_success(api_client.get_remake_record(remake["id"], SUPERVISOR), 200)
        assert reread["status"] == "COMPLETED"
        assert reread["remade_serial"] == "RM-0001", "the refused serial was never taken"
        assert reread["remade_envelope_id"] == replacement_id

        rows, meta = validate_paginated(api_client.list_return_envelopes(
            CLERK, params={"remade_from_envelope_id": bundle["envelope"]["id"]}))
        assert meta["total_count"] == 1, "a refused completion mints no second replacement"
        assert rows[0]["id"] == replacement_id

        original = get_envelope(bundle["envelope"]["id"])
        assert original["custody_status"] == "SUPERSEDED_BY_REMAKE"

    def test_second_check_in_and_double_revocation_return_session_state_invalid(self):
        """A checked-in session cannot be checked in again, and once revoked the session
        is terminal, so a second revocation is refused too.

        PRD: "The session must be in `SCHEDULED`, else `ERR_SESSION_STATE_INVALID`"
        Design: Corner/errors/second_check_in_and_double_revocation_return_session_state_invalid
        """
        election = setup_election(posture="RECEIVING", clock="2026-11-03T09:00:00Z")
        session = schedule_observer_session(
            election["id"], "obs-1", headers=CLERK, party_affiliation="DEM",
            station_area="SIGNATURE_REVIEW", window_start_at="2026-11-03T09:00:00Z",
            window_end_at="2026-11-03T18:00:00Z")
        assert session["status"] == "SCHEDULED"

        set_clock("2026-11-03T10:00:00Z")
        checked_in = check_in_observer(session)
        assert checked_in["status"] == "CHECKED_IN"

        observer = make_observer_headers("obs-1")
        validate_error(api_client.check_in_observer(session["id"], observer),
                       ApiErrorId.ERR_SESSION_STATE_INVALID, 409)

        still_in = validate_success(
            api_client.get_observer_session(session["id"], CLERK), 200)
        assert still_in["status"] == "CHECKED_IN"

        revoked = validate_success(api_client.revoke_observer_session(
            session["id"], {"revocation_reason_code": "MISCONDUCT"}, SUPERVISOR), 200)
        assert revoked["status"] == "REVOKED"
        assert revoked["revocation_reason_code"] == "MISCONDUCT"

        validate_error(api_client.revoke_observer_session(
            session["id"], {"revocation_reason_code": "WITHDRAWN"}, ADMIN),
            ApiErrorId.ERR_SESSION_STATE_INVALID, 409)

        final = validate_success(api_client.get_observer_session(session["id"], CLERK), 200)
        assert final["status"] == "REVOKED"
        assert final["revocation_reason_code"] == "MISCONDUCT", \
            "the refused second revocation never overwrote the recorded reason"

        rows, meta = validate_paginated(api_client.list_observer_sessions(
            CLERK, params={"election_id": election["id"], "status": "REVOKED"}))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == session["id"]

        _, log_meta = validate_paginated(api_client.list_transparency_log(
            ADMIN, params={"election_id": election["id"],
                           "event_type": "OBSERVER_SESSION_REVOKED"}))
        assert log_meta["total_count"] == 1, "only the accepted revocation was logged"

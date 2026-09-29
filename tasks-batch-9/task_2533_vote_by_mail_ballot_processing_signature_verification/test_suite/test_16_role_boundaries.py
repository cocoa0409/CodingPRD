"""Role boundaries: each of the five roles is tested at the edge of its mandate, so
every refusal is paired with the authorised role performing the very same call.
"""
from datetime import datetime

from test_helpers import (
    ADMIN,
    CLERK,
    OBSERVER,
    SUPERVISOR,
    ApiErrorId,
    api_client,
    create_trained_reviewer,
    create_voter,
    get_election,
    get_envelope,
    get_success_data,
    make_observer_headers,
    make_signature_reviewer_headers,
    open_review,
    set_clock,
    setup_cure_notice_under_evidence_review,
    setup_election,
    setup_received_envelopes,
    submit_decision,
    validate_error,
    validate_paginated,
    validate_success,
    voter_payload,
)


def _instant(value):
    """Parse an emitted UTC instant so a stamp may be compared to the logical clock
    value regardless of how many fractional digits it carries."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _decide_missing_signature(review):
    """Submit a MISSING_SIGNATURE decision, which carries no similarity_score."""
    headers = make_signature_reviewer_headers(review["reviewer_id"])
    return get_success_data(api_client.submit_signature_decision(
        review["id"], {"decision": "MISSING_SIGNATURE"}, headers))


class TestSignatureReviewerBoundary:
    def test_signature_reviewer_cannot_open_a_review_round_or_issue_a_cure(self):
        """A reviewer decides the reviews the server hands them and nothing more:
        opening a round and issuing a cure notice are both clerk work.

        PRD: "When the headers are well formed but the named role is not among the roles
        authorised for the target operation, the request is rejected with
        `ERR_ROLE_FORBIDDEN`."
        Design: Corner/rbac/signature_reviewer_cannot_open_a_review_round_or_issue_a_cure
        """
        reviewer = create_trained_reviewer()
        bundle = setup_received_envelopes(count=1)
        envelope_id = bundle["envelopes"][0]["id"]
        reviewer_headers = make_signature_reviewer_headers(reviewer["id"])

        validate_error(api_client.open_signature_review(envelope_id, reviewer_headers),
                       ApiErrorId.ERR_ROLE_FORBIDDEN, 403)
        _, before = validate_paginated(api_client.list_signature_reviews(
            CLERK, params={"return_envelope_id": envelope_id}))
        assert before["total_count"] == 0, "the refused open created no review"

        review = validate_success(
            api_client.open_signature_review(envelope_id, CLERK), 201)
        assert review["reviewer_id"] == reviewer["id"], \
            "the server picks the only eligible reviewer; the client never names one"
        assert review["review_round"] == 1
        assert review["status"] == "ASSIGNED"

        _decide_missing_signature(review)
        assert get_envelope(envelope_id)["signature_status"] == "CURE_REQUIRED"

        validate_error(api_client.create_cure_notice(envelope_id, reviewer_headers),
                       ApiErrorId.ERR_ROLE_FORBIDDEN, 403)
        _, no_notices = validate_paginated(api_client.list_cure_notices(
            CLERK, params={"return_envelope_id": envelope_id}))
        assert no_notices["total_count"] == 0

        notice = validate_success(api_client.create_cure_notice(envelope_id, CLERK), 201)
        assert notice["status"] == "ISSUED"
        assert notice["reason_code"] == "MISSING_SIGNATURE"
        assert get_election(bundle["election"]["id"])["open_cure_count"] == 1


class TestElectionsClerkBoundary:
    def test_elections_clerk_cannot_adjudicate_cures_or_run_separation(self):
        """The clerk logs evidence but does not judge it, and never performs the
        secrecy-creating separation run; both belong to the canvass supervisor.

        PRD: "A `CanvassSupervisor` adjudicates. The notice must be in
        `UNDER_EVIDENCE_REVIEW`, else `ERR_CURE_STATE_INVALID`"
        Design: Corner/rbac/elections_clerk_cannot_adjudicate_cures_or_run_separation
        """
        bundle = setup_cure_notice_under_evidence_review()
        notice = bundle["cure_notice"]
        envelope_id = bundle["envelope"]["id"]
        election_id = bundle["election"]["id"]
        assert notice["status"] == "UNDER_EVIDENCE_REVIEW"

        validate_error(api_client.adjudicate_cure_notice(
            notice["id"], {"outcome": "CURE"}, CLERK),
            ApiErrorId.ERR_ROLE_FORBIDDEN, 403)
        validate_error(api_client.create_separation_run(
            election_id, {"return_envelope_ids": [envelope_id]}, CLERK),
            ApiErrorId.ERR_ROLE_FORBIDDEN, 403)
        assert get_election(election_id)["separation_run_sequence"] == 0

        cured = validate_success(api_client.adjudicate_cure_notice(
            notice["id"], {"outcome": "CURE"}, SUPERVISOR), 200)
        assert cured["status"] == "CURED"
        assert _instant(cured["resolved_at"]) == _instant("2026-11-03T12:00:00Z")

        envelope = get_envelope(envelope_id)
        assert envelope["signature_status"] == "ACCEPTED"

        evidence = validate_success(
            api_client.get_cure_evidence(bundle["evidence"]["id"], CLERK), 200)
        assert evidence["accepted"] is True

        assert get_election(election_id)["open_cure_count"] == 0


class TestCanvassSupervisorBoundary:
    def test_canvass_supervisor_cannot_advance_posture_or_drive_the_clock(self):
        """The supervisor runs the floor's judgment calls, but the election's posture,
        the canvass checkpoint and the logical clock are the admin's alone.

        PRD: "An `ElectionsAdmin` may reposition the clock by supplying `to_iso8601`;
        the response reports the new value as `current_utc`."
        Design: Corner/rbac/canvass_supervisor_cannot_advance_posture_or_drive_the_clock
        """
        election = setup_election(clock="2026-09-10T09:00:00Z")
        assert election["posture"] == "PRE_MAIL"

        validate_error(api_client.advance_posture(
            election["id"], {"target_posture": "MAILING"}, SUPERVISOR),
            ApiErrorId.ERR_ROLE_FORBIDDEN, 403)
        validate_error(api_client.run_canvass_sweep(election["id"], {}, SUPERVISOR),
                       ApiErrorId.ERR_ROLE_FORBIDDEN, 403)
        validate_error(api_client.set_clock("2026-10-01T00:00:00Z", SUPERVISOR),
                       ApiErrorId.ERR_ROLE_FORBIDDEN, 403)

        unmoved = get_election(election["id"])
        assert unmoved["posture"] == "PRE_MAIL"
        assert unmoved["canvass_sweep_index"] == 0

        _, meta = validate_paginated(api_client.list_transparency_log(
            SUPERVISOR, params={"election_id": election["id"],
                                "event_type": "POSTURE_CHANGED"}))
        assert meta["total_count"] == 0

        stamped = create_voter()
        assert _instant(stamped["created_at"]) == _instant("2026-09-10T09:00:00Z"), \
            "the refused clock move left the logical clock where the admin put it"

        advanced = validate_success(api_client.advance_posture(
            election["id"], {"target_posture": "MAILING"}, ADMIN), 200)
        assert advanced["posture"] == "MAILING"


class TestObserverBoundary:
    def test_observer_reads_transparency_surfaces_but_not_voter_records(self):
        """An observer sees the public accounting of the election and the audit log, and
        is refused the voter register and the signature-review record.

        PRD: "An `Observer` holds a scheduled floor-access window, may file challenges
        only while checked in, and may never read voter registration records."
        Design: Corner/rbac/observer_reads_transparency_surfaces_but_not_voter_records
        """
        reviewer = create_trained_reviewer()
        bundle = setup_received_envelopes(count=1)
        election_id = bundle["election"]["id"]
        voter_id = bundle["voters"][0]["id"]
        review = open_review(bundle["envelopes"][0]["id"])
        assert review["reviewer_id"] == reviewer["id"]

        election = validate_success(api_client.get_election(election_id, OBSERVER), 200)
        assert election["posture"] == "RECEIVING"

        report = validate_success(
            api_client.get_accountability(election_id, OBSERVER), 200)
        assert report["packets_mailed_count"] == 1
        assert report["envelopes_received_count"] == 1

        entries, meta = validate_paginated(api_client.list_transparency_log(
            OBSERVER, params={"election_id": election_id}))
        assert meta["total_count"] >= 1
        entry = validate_success(
            api_client.get_transparency_entry(entries[0]["id"], OBSERVER), 200)
        assert entry["ballot_content_disclosed"] is False

        validate_error(api_client.get_voter(voter_id, OBSERVER),
                       ApiErrorId.ERR_ROLE_FORBIDDEN, 403)
        validate_error(api_client.list_voters(OBSERVER),
                       ApiErrorId.ERR_ROLE_FORBIDDEN, 403)
        validate_error(api_client.get_signature_review(review["id"], OBSERVER),
                       ApiErrorId.ERR_ROLE_FORBIDDEN, 403)

        named_observer = make_observer_headers("obs-1")
        validate_error(api_client.get_voter(voter_id, named_observer),
                       ApiErrorId.ERR_ROLE_FORBIDDEN, 403)


class TestSharedAndExclusiveWrites:
    def test_voter_creation_is_shared_by_admin_and_clerk(self):
        """Voter registration is one of the few writes both office roles may perform,
        while enrolling that voter on the permanent absentee list is the clerk's alone.

        PRD: "An `ElectionsClerk` works the processing floor: logging ballot requests and
        address-verification results, building and dispatching mailing batches, recording
        undeliverable packets, logging returned envelopes and cure evidence, opening
        signature-review rounds, issuing cure notices, and administering the permanent
        absentee list."
        Design: Corner/rbac/voter_creation_is_shared_by_admin_and_clerk
        """
        set_clock("2026-09-10T09:00:00Z")

        by_clerk = validate_success(api_client.create_voter(
            voter_payload(full_name="Ada Boyle"), CLERK), 201)
        by_admin = validate_success(api_client.create_voter(
            voter_payload(full_name="Bo Ellis"), ADMIN), 201)

        for created in (by_clerk, by_admin):
            assert created["registration_status"] == "ACTIVE"
            assert created["version"] == 1
            assert created["permanent_absentee_active"] is False
        assert by_clerk["id"] != by_admin["id"]

        validate_error(api_client.create_enrollment(by_admin["id"], {}, ADMIN),
                       ApiErrorId.ERR_ROLE_FORBIDDEN, 403)
        _, no_enrollments = validate_paginated(api_client.list_enrollments(
            CLERK, params={"voter_id": by_admin["id"]}))
        assert no_enrollments["total_count"] == 0

        enrolled = validate_success(
            api_client.create_enrollment(by_admin["id"], {}, CLERK), 201)
        assert enrolled["status"] == "ACTIVE"

        _, voters = validate_paginated(api_client.list_voters(ADMIN))
        assert voters["total_count"] == 2


class TestSegregationOfDuties:
    def test_escalation_round_two_never_reassigns_the_round_one_reviewer(self):
        """A reviewer who has already looked at an envelope is excluded from the
        selector's candidate set for every later round on that same envelope.

        PRD: "A reviewer who has any signature review on an envelope — of any status —
        can never be selected for a later escalation round on that same envelope."
        Design: Corner/rbac/escalation_round_two_never_reassigns_the_round_one_reviewer
        """
        first = create_trained_reviewer(full_name="Tess Ward", party_affiliation="NPP")
        second = create_trained_reviewer(full_name="Ivan Ruiz", party_affiliation="REP")
        bundle = setup_received_envelopes(count=1)
        envelope_id = bundle["envelopes"][0]["id"]

        round_one = open_review(envelope_id)
        assert round_one["reviewer_id"] == first["id"], \
            "an empty pool ranks the earliest-created reviewer first"
        submit_decision(round_one, "NO_MATCH", 60)

        escalated = get_envelope(envelope_id)
        assert escalated["signature_status"] == "ESCALATED"
        assert escalated["review_round_count"] == 1

        round_two = validate_success(
            api_client.open_signature_review(envelope_id, CLERK), 201)
        assert round_two["review_round"] == 2
        assert round_two["reviewer_id"] != first["id"]
        assert round_two["reviewer_id"] == second["id"]
        assert round_two["status"] == "ASSIGNED"

        assert get_envelope(envelope_id)["signature_status"] == "PENDING_REVIEW"

        first_after = validate_success(api_client.get_reviewer(first["id"], ADMIN), 200)
        assert first_after["active_review_count"] == 0
        assert first_after["completed_review_count"] == 1

        second_after = validate_success(api_client.get_reviewer(second["id"], ADMIN), 200)
        assert second_after["active_review_count"] == 1
        assert second_after["completed_review_count"] == 0

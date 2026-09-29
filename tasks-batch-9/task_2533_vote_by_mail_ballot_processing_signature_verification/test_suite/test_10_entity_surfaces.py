"""Entity surfaces of the Vote-By-Mail Processing API.

Every test builds its own world from an empty database through the public API,
and every asserted value is read back from the PRD's declared defaults, derived
fields and identifier-resolution rules.
"""
from datetime import datetime

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_ballot_request,
    assert_cure_evidence,
    assert_election,
    assert_immutable_artifact_fields,
    assert_return_envelope,
    assert_reviewer,
    assert_voter,
    ballot_request_payload,
    create_ballot_request,
    create_election,
    create_voter,
    cure_evidence_payload,
    return_envelope_payload,
    set_clock,
    setup_issued_cure_notice,
    setup_mailed_packets,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["elections_admin_headers"]
CLERK = TEST_USERS["elections_clerk_headers"]

# The statutory calendar every recipe below hangs off, carrying only the inputs
# the PRD declares mandatory so the optional grace parameters fall to defaults.
ELECTION_REQUIRED_ONLY = {
    "name": "General Election 2026",
    "election_date": "2026-11-03",
    "uocava_send_deadline_date": "2026-09-19",
    "domestic_send_deadline_date": "2026-10-05",
    "return_deadline_at": "2026-11-03T20:00:00Z",
    "postage_budget_cents": 1_000_000,
}

VOTER_REQUIRED_ONLY = {
    "full_name": "Vera Ames",
    "party_affiliation": "DEM",
    "residence_address": "11 Ash St, Springfield",
    "last_signature_update_at": "2026-01-05T00:00:00Z",
}

ZERO_COUNTERS = (
    "packets_mailed_count",
    "envelopes_received_count",
    "outstanding_packet_count",
    "undeliverable_packet_count",
    "countable_envelope_count",
    "attributable_ballot_count",
    "rejected_envelope_count",
    "provisional_referral_count",
    "open_cure_count",
    "postage_committed_cents",
    "postage_actual_cents",
    "separation_run_sequence",
    "canvass_sweep_index",
)

UNPERSISTED_UUID = "99999999-9999-4999-8999-999999999999"
UNPERSISTED_VOTER_UUID = "11111111-1111-4111-8111-111111111111"


def _instant(value):
    """Parse an ISO 8601 UTC instant so two spellings of one instant compare equal."""
    assert isinstance(value, str), f"expected an ISO 8601 UTC string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestElectionRegistrationSurface:
    """Registering an election, and reading one that does not exist."""

    def test_election_create_returns_declared_fields_and_pre_mail_posture(self):
        """Registering with only the mandatory calendar inputs opens the election in
        PRE_MAIL with the standard canvass length, the two default grace parameters
        and every derived counter at zero.

        PRD: "A newly registered election opens in posture `PRE_MAIL`."

        Design: Corner/entities/election_create_returns_declared_fields_and_pre_mail_posture
        """
        set_clock("2026-09-10T09:00:00Z")

        data = validate_success(
            api_client.create_election(dict(ELECTION_REQUIRED_ONLY), ADMIN), 201)

        assert_election(data)
        assert data["name"] == "General Election 2026"
        assert data["election_date"] == "2026-11-03"
        assert _instant(data["return_deadline_at"]) == _instant("2026-11-03T20:00:00Z")
        assert data["posture"] == "PRE_MAIL"
        # Omitted optional inputs take their declared defaults of 7 and 21 whole days.
        assert data["postmark_grace_days"] == 7
        assert data["cure_window_days"] == 21
        # canvass_days is the standard 17, so canvass_lock_at is the deadline plus 17 days.
        assert data["canvass_days"] == 17
        assert _instant(data["canvass_lock_at"]) == _instant("2026-11-20T20:00:00Z")
        assert data["reconciliation_status"] == "IN_BALANCE"
        for counter in ZERO_COUNTERS:
            assert data[counter] == 0, f"{counter} must initialise to zero"
        assert data["version"] == 1

    def test_election_get_with_unknown_id_returns_election_not_found(self):
        """A syntactically valid but unpersisted election id resolves to nothing, so the
        read fails with the election-specific not-found identifier rather than a generic
        one, and the stored election table is untouched.

        PRD: "An election identifier that resolves to nothing yields `ERR_ELECTION_NOT_FOUND`"

        Design: Corner/entities/election_get_with_unknown_id_returns_election_not_found
        """
        set_clock("2026-09-10T09:00:00Z")
        create_election()

        error = validate_error(
            api_client.get_election(UNPERSISTED_UUID, CLERK),
            ApiErrorId.ERR_ELECTION_NOT_FOUND, 404)

        assert error["message"].strip(), "the error carries a human-readable message"
        rows, meta = validate_paginated(api_client.list_elections(ADMIN))
        assert meta["total_count"] == 1, "the refused read created no election"
        assert all(row["id"] != UNPERSISTED_UUID for row in rows)


class TestVoterRegistrationSurface:
    """Voter creation defaults and the read-back of a stored registration record."""

    def test_voter_create_applies_declared_defaults(self):
        """Omitting registration_status, mailing_address, uocava_status and
        signature_on_file_count yields ACTIVE, null, NONE and 1, and both derived
        flags start false.

        PRD: "`registration_status` defaults to `ACTIVE` and may otherwise be `INACTIVE` or `CANCELLED`."

        Design: Corner/entities/voter_create_applies_declared_defaults
        """
        set_clock("2026-09-10T09:00:00Z")

        data = validate_success(
            api_client.create_voter(dict(VOTER_REQUIRED_ONLY), CLERK), 201)

        assert_voter(data)
        assert data["registration_status"] == "ACTIVE"
        assert data["mailing_address"] is None
        assert data["uocava_status"] == "NONE"
        assert data["signature_on_file_count"] == 1
        assert data["permanent_absentee_active"] is False
        assert data["provisional_ballot_eligible"] is False
        assert data["version"] == 1

    def test_voter_get_returns_stored_registration_record(self):
        """Reading a voter back echoes the stored row field for field, with no
        mutation of the record and no version bump from the read.

        PRD: "A voter record is created by an `ElectionsClerk` or an `ElectionsAdmin` with the registered `full_name` as printed on the registration record, a `party_affiliation`, the `residence_address`, and `last_signature_update_at`"

        Design: Corner/entities/voter_get_returns_stored_registration_record
        """
        set_clock("2026-09-10T09:00:00Z")
        created = create_voter(**VOTER_REQUIRED_ONLY)

        data = validate_success(api_client.get_voter(created["id"], CLERK), 200)

        assert_voter(data)
        assert data["id"] == created["id"]
        assert data["full_name"] == "Vera Ames"
        assert data["party_affiliation"] == "DEM"
        assert data["residence_address"] == "11 Ash St, Springfield"
        assert _instant(data["last_signature_update_at"]) == _instant("2026-01-05T00:00:00Z")
        assert data["version"] == 1


class TestReviewerCertificationSurface:
    """The reviewer's certification window is derived, never supplied."""

    def test_reviewer_training_expires_at_computed_as_completion_plus_365_days(self):
        """A reviewer trained on 2026-06-01T00:00:00Z carries a certification window
        expiring exactly 365 whole days later, and both workload counters open at zero.

        PRD: "the reviewer's `training_expires_at` is derived as that instant advanced by 365 whole days"

        Design: Corner/entities/reviewer_training_expires_at_computed_as_completion_plus_365_days
        """
        set_clock("2026-09-10T09:00:00Z")
        payload = {
            "full_name": "Rosa Vidal",
            "party_affiliation": "DEM",
            "training_status": "TRAINED",
            "training_completed_at": "2026-06-01T00:00:00Z",
            "curriculum_version": "SV-2026.1",
        }

        data = validate_success(api_client.create_reviewer(payload, ADMIN), 201)

        assert_reviewer(data)
        assert data["training_status"] == "TRAINED"
        assert _instant(data["training_completed_at"]) == _instant("2026-06-01T00:00:00Z")
        assert _instant(data["training_expires_at"]) == _instant("2027-06-01T00:00:00Z")
        assert data["active_review_count"] == 0
        assert data["completed_review_count"] == 0
        assert data["curriculum_version"] == "SV-2026.1"


class TestBallotRequestCreationSurface:
    """Logging a ballot request creates its address verification and bumps the voter."""

    def test_ballot_request_create_opens_pending_address_verification_and_bumps_voter_version(self):
        """One logged request opens in RECEIVED with forwarding_class UNKNOWN and a
        mailing_address_snapshot frozen from the residence address, creates exactly one
        PENDING address verification pointing back at it, and drives the voter's version
        from 1 to 2.

        PRD: "One address verification is created in status `PENDING` and linked back to the request through its `ballot_request_id`."

        Design: Corner/entities/ballot_request_create_opens_pending_address_verification_and_bumps_voter_version
        """
        set_clock("2026-09-10T09:00:00Z")
        election = create_election()
        voter = create_voter(**VOTER_REQUIRED_ONLY)
        assert voter["version"] == 1

        data = validate_success(
            api_client.create_ballot_request(
                ballot_request_payload(voter["id"], election["id"], voter["version"]),
                CLERK),
            201)

        assert_ballot_request(data)
        assert data["status"] == "RECEIVED"
        assert data["forwarding_class"] == "UNKNOWN"
        assert data["permanent_flag"] is False
        # mailing_address is null on this voter, so the residence address is frozen instead.
        assert data["mailing_address_snapshot"] == "11 Ash St, Springfield"

        rows, meta = validate_paginated(
            api_client.list_address_verifications(
                CLERK, params={"ballot_request_id": data["id"]}))
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "PENDING"
        assert rows[0]["ncoa_result"] is None
        assert rows[0]["ballot_request_id"] == data["id"]

        voter_after = validate_success(api_client.get_voter(voter["id"], CLERK), 200)
        assert voter_after["version"] == 2

        entries, log_meta = validate_paginated(
            api_client.list_transparency_log(
                ADMIN, params={"election_id": election["id"],
                               "event_type": "REQUEST_LOGGED"}))
        assert log_meta["total_count"] == 1
        assert entries[0]["ballot_content_disclosed"] is False

    def test_ballot_requests_list_paginates_with_limit_offset_and_total_count(self):
        """Three requests on one election page two-at-a-time: the first window reports
        total_count 3 with has_more true, the second returns the remaining row with
        has_more false, and the two windows together cover every row once.

        PRD: "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside `meta`, where `total_count` is the number of rows matching the filters before the page window is applied"

        Design: Corner/entities/ballot_requests_list_paginates_with_limit_offset_and_total_count
        """
        set_clock("2026-09-10T09:00:00Z")
        election = create_election()
        seeded = [
            ("Vera Ames", "DEM", "11 Ash St, Springfield", "2026-01-05T00:00:00Z", "ONLINE"),
            ("Bram Cole", "REP", "22 Birch Rd, Springfield", "2026-02-10T00:00:00Z", "PAPER"),
            ("Cleo Dunn", "NPP", "33 Cedar Ln, Springfield", "2026-03-15T00:00:00Z", "PHONE"),
        ]
        request_ids = []
        for full_name, party, address, signed_at, channel in seeded:
            voter = create_voter(full_name=full_name, party_affiliation=party,
                                 residence_address=address,
                                 last_signature_update_at=signed_at)
            request = create_ballot_request(voter, election, request_channel=channel)
            request_ids.append(request["id"])

        page_one, meta_one = validate_paginated(
            api_client.list_ballot_requests(
                CLERK, params={"election_id": election["id"], "limit": 2, "offset": 0}))
        page_two, meta_two = validate_paginated(
            api_client.list_ballot_requests(
                CLERK, params={"election_id": election["id"], "limit": 2, "offset": 2}))

        assert len(page_one) == 2
        assert meta_one["total_count"] == 3
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0
        assert meta_one["has_more"] is True

        assert len(page_two) == 1
        assert meta_two["total_count"] == 3
        assert meta_two["limit"] == 2
        assert meta_two["offset"] == 2
        assert meta_two["has_more"] is False

        paged_ids = [row["id"] for row in page_one] + [row["id"] for row in page_two]
        assert len(paged_ids) == len(set(paged_ids)), "no row appears on both pages"
        assert set(paged_ids) == set(request_ids)


class TestBallotRequestRejectionSurface:
    """Schema and existence failures on the ballot-request write, and what they leave behind."""

    def test_ballot_request_create_without_delivery_method_returns_invalid_request(self):
        """delivery_method has no default, so omitting it fails the schema check before
        anything is written: no request, no address verification and no version bump.

        PRD: "required body fields present, enum values inside their declared sets"

        Design: Corner/entities/ballot_request_create_without_delivery_method_returns_invalid_request
        """
        set_clock("2026-09-10T09:00:00Z")
        election = create_election()
        voter = create_voter(**VOTER_REQUIRED_ONLY)
        payload = {
            "voter_id": voter["id"],
            "election_id": election["id"],
            "request_channel": "ONLINE",
            "expected_voter_version": voter["version"],
        }

        validate_error(api_client.create_ballot_request(payload, CLERK),
                       ApiErrorId.ERR_INVALID_REQUEST, 400)

        _, request_meta = validate_paginated(
            api_client.list_ballot_requests(CLERK, params={"voter_id": voter["id"]}))
        assert request_meta["total_count"] == 0
        _, verification_meta = validate_paginated(
            api_client.list_address_verifications(CLERK))
        assert verification_meta["total_count"] == 0
        voter_after = validate_success(api_client.get_voter(voter["id"], CLERK), 200)
        assert voter_after["version"] == 1, "a refused write never bumps the voter"

    def test_ballot_request_create_with_unknown_delivery_method_enum_is_rejected(self):
        """delivery_method is a closed two-value set, so an out-of-set spelling fails the
        schema check rather than the downstream delivery-eligibility rule.

        PRD: "the `delivery_method`, which is either `MAIL` or `EMAIL_UOCAVA`"

        Design: Corner/entities/ballot_request_create_with_unknown_delivery_method_enum_is_rejected
        """
        set_clock("2026-09-10T09:00:00Z")
        election = create_election()
        voter = create_voter(**VOTER_REQUIRED_ONLY)
        assert voter["uocava_status"] == "NONE"
        payload = ballot_request_payload(voter["id"], election["id"], voter["version"],
                                        delivery_method="FAX")

        validate_error(api_client.create_ballot_request(payload, CLERK),
                       ApiErrorId.ERR_INVALID_REQUEST, 400)

        _, request_meta = validate_paginated(
            api_client.list_ballot_requests(CLERK, params={"voter_id": voter["id"]}))
        assert request_meta["total_count"] == 0

    def test_ballot_request_create_with_unknown_voter_returns_voter_not_found(self):
        """The voter identifier is resolved before the stale-view guard is consulted, so
        an unpersisted voter_id surfaces as a voter not-found rather than a version conflict.

        PRD: "Identifiers are resolved strictly left to right as they appear in the request, and the first identifier that fails to resolve determines the error."

        Design: Corner/entities/ballot_request_create_with_unknown_voter_returns_voter_not_found
        """
        set_clock("2026-09-10T09:00:00Z")
        election = create_election()
        voter = create_voter(**VOTER_REQUIRED_ONLY)
        payload = ballot_request_payload(UNPERSISTED_VOTER_UUID, election["id"],
                                        voter["version"])

        validate_error(api_client.create_ballot_request(payload, CLERK),
                       ApiErrorId.ERR_VOTER_NOT_FOUND, 404)

        _, request_meta = validate_paginated(api_client.list_ballot_requests(CLERK))
        assert request_meta["total_count"] == 0


class TestSystemStampedAndImmutableSurfaces:
    """Fields the server owns: the logical-clock stamps and the immutable audit artifacts."""

    def test_envelope_intake_stamps_system_fields_from_the_logical_clock(self):
        """Intake reads received_at from the logical clock rather than the request body,
        opens all three state dimensions at their initial values, and leaves every
        downstream field null while the carrying packet moves to RETURNED.

        PRD: "A successful intake creates the envelope with all three of its state dimensions at their initial values"

        Design: Corner/entities/envelope_intake_stamps_system_fields_from_the_logical_clock
        """
        bundle = setup_mailed_packets(count=1, posture="MAILING",
                                     clock="2026-09-10T09:00:00Z")
        packet = bundle["packets"][0]
        assert packet["status"] == "MAILED"
        # Intake lands before return_deadline_at 2026-11-03T20:00:00Z.
        set_clock("2026-11-03T12:00:00Z")

        data = validate_success(
            api_client.create_return_envelope(
                return_envelope_payload(packet["id"], "DROPBOX"), CLERK),
            201)

        assert_return_envelope(data)
        assert _instant(data["received_at"]) == _instant("2026-11-03T12:00:00Z")
        assert data["signature_status"] == "UNVERIFIED"
        assert data["custody_status"] == "SEALED"
        assert data["challenge_status"] == "NONE"
        assert data["remade_from_envelope_id"] is None
        assert data["separation_run_sequence"] is None
        assert data["final_timeliness"] is None
        assert data["challenge_reason_code"] is None
        assert data["challenge_findings"] is None
        assert data["review_round_count"] == 0
        assert data["resolved_signature_confidence"] is None
        assert data["version"] == 1
        # A drop-box return at or before the deadline is timely with no grace involved.
        assert data["preliminary_timeliness"] == "TIMELY"

        packet_after = validate_success(
            api_client.get_ballot_packet(packet["id"], CLERK), 200)
        assert packet_after["status"] == "RETURNED"

        election_after = validate_success(
            api_client.get_election(bundle["election"]["id"], ADMIN), 200)
        assert election_after["posture"] == "RECEIVING"
        assert election_after["envelopes_received_count"] == 1

    def test_cure_evidence_row_is_immutable_with_no_version_and_no_write_back_endpoint(self):
        """A cure evidence submission is an immutable audit artifact: it carries an id and
        a created_at but no updated_at and no version, its adjudication fields start null,
        and submitting it moves the notice into evidence review.

        PRD: "Two record types are immutable audit artifacts and therefore carry only `id` and `created_at`"

        Design: Corner/entities/cure_evidence_row_is_immutable_with_no_version_and_no_write_back_endpoint
        """
        bundle = setup_issued_cure_notice()
        notice = bundle["cure_notice"]
        assert notice["status"] == "ISSUED"

        data = validate_success(
            api_client.submit_cure_evidence(notice["id"], cure_evidence_payload(), CLERK),
            201)

        assert_cure_evidence(data)
        assert data["cure_notice_id"] == notice["id"]
        assert data["evidence_type"] == "SIGNED_AFFIDAVIT"
        assert data["submission_channel"] == "MAIL"
        assert data["affirmation_signed"] is True
        assert _instant(data["received_at"]) == _instant("2026-11-03T12:00:00Z")
        assert data["accepted"] is None
        assert data["deficiency_reason_code"] is None

        fetched = validate_success(api_client.get_cure_evidence(data["id"], CLERK), 200)
        assert_immutable_artifact_fields(fetched)
        assert "version" not in fetched
        assert "updated_at" not in fetched
        assert fetched["id"] == data["id"]

        notice_after = validate_success(
            api_client.get_cure_notice(notice["id"], CLERK), 200)
        assert notice_after["status"] == "UNDER_EVIDENCE_REVIEW"
        assert notice_after["evidence_submission_count"] == 1

    def test_cure_evidence_list_row_carries_no_mutable_bookkeeping_fields(self):
        """The listed evidence row exposes the same immutable surface as the read: only
        an id and a created_at alongside its own submission fields.

        PRD: "A **CureEvidence** row is created with `cure_notice_id` pointing at the notice and `received_at` stamped from the logical clock; its `accepted` and `deficiency_reason_code` both start null and are written only by adjudication."

        Design: Corner/entities/cure_evidence_row_is_immutable_with_no_version_and_no_write_back_endpoint
        """
        bundle = setup_issued_cure_notice()
        notice = bundle["cure_notice"]
        created = validate_success(
            api_client.submit_cure_evidence(notice["id"], cure_evidence_payload(), CLERK),
            201)

        rows, meta = validate_paginated(
            api_client.list_cure_evidence(CLERK, params={"cure_notice_id": notice["id"]}))

        assert meta["total_count"] == 1
        assert rows[0]["id"] == created["id"]
        assert_immutable_artifact_fields(rows[0])
        assert rows[0]["accepted"] is None
        assert rows[0]["deficiency_reason_code"] is None

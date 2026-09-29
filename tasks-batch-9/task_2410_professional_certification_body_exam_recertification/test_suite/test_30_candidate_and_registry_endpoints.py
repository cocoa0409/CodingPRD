"""The candidate collection's create-read-list round trip, and the headerless registry read."""

from test_helpers import ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success

CANDIDATE_A = {"email": "cand.a@example.com", "full_name": "Cand A"}
CANDIDATE_B = {"email": "cand.b@example.com", "full_name": "Cand B"}
UNKNOWN_CERTIFICATE_NUMBER = "CPX-2026-99999"


class TestCandidateRoundTrip:
    """Create, read back, refuse the duplicate, and page the collection."""

    def test_the_created_candidate_reads_back_identically_under_its_own_id(self, api):
        """A new candidate is active with no bar, and the read as a different role returns
        the same stored row rather than a re-derived one.

        PRD §3.6: "A new candidate's `status` is `ACTIVE`, with `barred_until` and
        `bar_reason` both null."

        PRD §2.10: "Operations that bring a new resource into existence answer with **HTTP
        201**."

        Design: Corner/endpoints/candidate_create_read_and_list_round_trip_with_a_duplicate_email_rejected
        """
        created = validate_success(api.create_candidate(
            f.create_candidate_payload(**CANDIDATE_A), fx.EXAM_OPERATIONS), 201)

        assert created["status"] == "ACTIVE"
        assert created["barred_until"] is None
        assert created["bar_reason"] is None
        ax.assert_candidate(created, expected_version=1)

        fetched = validate_success(
            api.get_candidate(created["id"], fx.ELIGIBILITY_REVIEWER_1), 200)
        assert fetched["email"] == CANDIDATE_A["email"]
        assert fetched["full_name"] == CANDIDATE_A["full_name"]
        assert fetched["created_at"] == created["created_at"]
        assert fetched["version"] == created["version"]

    def test_a_second_candidate_reusing_the_email_is_refused_and_creates_nothing(self, api):
        """The uniqueness constraint is on the email alone, so a different name does not
        rescue it, and the stored row keeps its own name.

        PRD §3.6: "Either an `ExamOperations` or an `EligibilityReviewer` operator registers
        a candidate with an `email`, which must be unique across all candidates — a
        duplicate is refused with `ERR_CANDIDATE_EMAIL_TAKEN` — and a `full_name`, which is
        the legal name that will eventually appear on the credential."

        Design: Corner/endpoints/candidate_create_read_and_list_round_trip_with_a_duplicate_email_rejected
        """
        created = fx.create_candidate(api, **CANDIDATE_A)

        refused = api.create_candidate(
            f.create_candidate_payload(email=CANDIDATE_A["email"],
                                       full_name="Cand A Duplicate"),
            fx.EXAM_OPERATIONS)

        validate_error(refused, ApiErrorId.ERR_CANDIDATE_EMAIL_TAKEN.value, 409)
        assert fx.read_candidate(api, created["id"])["full_name"] == "Cand A"
        _rows, meta = validate_paginated(api.list_candidates(fx.PROGRAM_ADMIN))
        assert meta["total_count"] == 1

    def test_the_listing_pages_two_rows_one_at_a_time_and_reports_has_more(self, api):
        """Each page carries one row and the same pre-pagination total, and only the first
        page reports that records remain.

        PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count`, and
        `has_more` inside the `meta` object, where `total_count` is the number of records
        matching the filters before pagination and `has_more` indicates whether records
        remain beyond the current page."

        Design: Corner/endpoints/candidate_create_read_and_list_round_trip_with_a_duplicate_email_rejected
        """
        candidate_a = fx.create_candidate(api, **CANDIDATE_A)
        candidate_b = fx.create_candidate(api, **CANDIDATE_B)

        first_rows, first_meta = validate_paginated(api.list_candidates(
            fx.PROGRAM_ADMIN, {"status": "ACTIVE", "limit": 1, "offset": 0}))
        assert len(first_rows) == 1
        assert first_meta["total_count"] == 2
        assert first_meta["limit"] == 1
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True

        second_rows, second_meta = validate_paginated(api.list_candidates(
            fx.PROGRAM_ADMIN, {"status": "ACTIVE", "limit": 1, "offset": 1}))
        assert len(second_rows) == 1
        assert second_meta["total_count"] == 2
        assert second_meta["offset"] == 1
        assert second_meta["has_more"] is False

        assert {first_rows[0]["id"], second_rows[0]["id"]} == {candidate_a["id"],
                                                              candidate_b["id"]}


class TestPublicRegistryVerification:
    """One projection, readable by anybody, and silent about numbers it does not hold."""

    def test_the_projection_is_readable_with_no_headers_at_all(self, api):
        """No `X-User-ID` and no `X-User-Role` are supplied and the read still answers 200,
        reporting the holder's public facts plus a `verified_at` taken from the clock rather
        than from the issue date.

        PRD §3.10: "Public verification is the outward face of the registry and the only
        capability in the system reachable with no headers whatsoever."

        PRD §3.10: "A verifier supplies a `certificate_number` and receives back that
        `certificate_number`, the issuing program's `credential_code`, the holder's
        `full_name`, a `credential_status`, the `publication_status`, the `issued_on` and
        `valid_through` instants, and a `verified_at` stamp recording the logical-clock
        instant at which the lookup was performed."

        Design: Corner/endpoints/registry_verify_reads_the_public_projection_without_headers_and_hides_unknown_numbers
        """
        state = fx.pipeline_through_certificant(api)
        assert state.certificate_number == "CPX-2026-00001"

        response = api.verify_registry({"certificate_number": state.certificate_number})

        verification = validate_success(response, 200)
        assert verification["certificate_number"] == "CPX-2026-00001"
        assert verification["credential_code"] == "CPX"
        assert verification["full_name"] == "Cand A"
        assert verification["credential_status"] == "ACTIVE"
        assert verification["publication_status"] == "PUBLISHED"
        assert str(verification["issued_on"]).startswith("2026-08-10")
        assert str(verification["valid_through"]).startswith("2027-08-10")
        assert str(verification["verified_at"]).startswith("2026-08-10T00:00:00")
        ax.assert_registry_verification(verification)

    def test_an_unknown_certificate_number_is_a_not_found_and_the_reads_mutate_nothing(
            self, api):
        """A number nobody holds answers 404 on the certificant, and neither read touches
        the stored credential.

        PRD §3.10: "Suppression is deliberately indistinguishable from non-existence: when
        the matched certificant's `publication_status` is `WITHHELD` or `REMOVED`, the
        verification answers `ERR_CERTIFICANT_NOT_FOUND` rather than revealing that a
        suppressed record exists."

        PRD §2.4: "Setting the clock is deliberately inert: it never mutates a stored
        record."

        Design: Corner/endpoints/registry_verify_reads_the_public_projection_without_headers_and_hides_unknown_numbers
        """
        state = fx.pipeline_through_certificant(api)
        api.verify_registry({"certificate_number": state.certificate_number})

        refused = api.verify_registry(
            {"certificate_number": UNKNOWN_CERTIFICATE_NUMBER})

        validate_error(refused, ApiErrorId.ERR_CERTIFICANT_NOT_FOUND.value, 404)
        certificant = fx.read_certificant(api, state.certificant_id)
        assert certificant["status"] == "ACTIVE"
        assert certificant["version"] == state.certificant_version

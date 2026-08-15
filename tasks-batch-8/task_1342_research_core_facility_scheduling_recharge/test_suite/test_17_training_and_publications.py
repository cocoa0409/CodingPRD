"""Training recertification cycle and publication acknowledgment gates
(PRD §3.3, §3.12)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    TEST_USERS, create_publication_payload,
    make_researcher_headers,
    create_user, create_instrument, enroll_and_certify, set_clock,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestRecertificationCycle:
    def _setup(self, api):
        u1 = create_user(is_pi=True)
        i1 = create_instrument()
        t1 = enroll_and_certify(u1["id"], i1["id"])
        return u1, i1, t1

    def test_certified_expires_at_exact_boundary(self, api):
        """PRD §3.3: "On certification, `certified_at` is set to the current
        logical time and `expires_at` to exactly twelve months later." PRD
        §2.4: "A `CERTIFIED` `TrainingRecord` whose `expires_at` is at or
        before the current logical time is reported and treated as `EXPIRED`.
        The boundary is inclusive: exactly at `expires_at` the record is
        expired; one second before, it is still certified."

        Design: Difficulty/non_linear_state_machine/training_recertification_cycle
        """
        u1, i1, t1 = self._setup(api)
        # Certified at the 2026-08-01T00:00:00Z startup-default clock.
        assert t1["status"] == "CERTIFIED"
        assert t1["expires_at"].startswith("2027-08-01T00:00:00"), (
            "certified_at + exactly twelve months"
        )
        set_clock("2027-07-31T23:59:59Z")  # one second before expiry
        still_valid = validate_success(api.get_training_record(t1["id"], STAFF), 200)
        assert still_valid["status"] == "CERTIFIED"
        set_clock("2027-08-01T00:00:00Z")  # exactly at expires_at
        expired = validate_success(api.get_training_record(t1["id"], STAFF), 200)
        assert expired["status"] == "EXPIRED", "at expires_at the record IS expired"

    def test_reenroll_clears_and_recertify_restamps(self, api):
        """PRD §3.3: "An `EXPIRED` record can be re-enrolled by `CoreStaff`,
        which returns it to `ENROLLED` and clears both `certified_at` and
        `expires_at` to null, starting the cycle over." and "On certification,
        `certified_at` is set to the current logical time and `expires_at` to
        exactly twelve months later."

        Design: Difficulty/non_linear_state_machine/training_recertification_cycle
        """
        u1, i1, t1 = self._setup(api)
        set_clock("2027-08-01T00:00:00Z")
        reenrolled = validate_success(
            api.reenroll_training_record(t1["id"], STAFF), 200
        )
        assert reenrolled["status"] == "ENROLLED"
        assert reenrolled["certified_at"] is None
        assert reenrolled["expires_at"] is None

        recertified = validate_success(
            api.certify_training_record(t1["id"], STAFF), 200
        )
        assert recertified["status"] == "CERTIFIED"
        assert recertified["certified_at"].startswith("2027-08-01T00:00:00")
        assert recertified["expires_at"].startswith("2028-08-01T00:00:00"), (
            "the full cycle restamps expiry twelve months out"
        )


class TestPublicationGates:
    def test_publication_ack_reason_and_evidence(self, api):
        """PRD §3.12: "When `acknowledges_core` is false, `non_ack_reason` is
        required and non-empty (`ERR_ACK_REASON_REQUIRED`)." and "Verification
        by `CoreStaff` requires evidence: the reporting user must have at least
        one `VALIDATED` usage log whose `instrument_id` appears in the
        publication's `instrument_ids`; without one the verification fails with
        `ERR_PUBLICATION_EVIDENCE_MISSING`."

        Design: Corner/validations/publication_ack_reason_and_evidence
        """
        u1 = create_user()
        i1 = create_instrument()
        owner = make_researcher_headers(u1["id"])

        no_reason = api.create_publication(
            create_publication_payload(
                u1["id"], [i1["id"]], title="NoAck", journal="JACS",
                acknowledges_core=False,
            ),
            owner,
        )
        validate_error(no_reason, "ERR_ACK_REASON_REQUIRED", expected_status=422)

        p2 = validate_success(
            api.create_publication(
                create_publication_payload(
                    u1["id"], [i1["id"]], title="GoodPaper",
                ),
                owner,
            ),
            201,
        )
        no_evidence = api.verify_publication(p2["id"], STAFF)
        validate_error(
            no_evidence, "ERR_PUBLICATION_EVIDENCE_MISSING", expected_status=422
        )
        after = validate_success(api.get_publication(p2["id"], STAFF), 200)
        assert after["status"] == "REPORTED"

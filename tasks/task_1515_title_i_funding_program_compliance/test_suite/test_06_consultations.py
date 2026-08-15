"""Private-school equitable-services consultations (PRD §3.6, §3.3)."""

from test_helpers import (
    ApiErrorId,
    api_client,
    build_user_headers,
    open_consultation,
    open_grant,
    record_session,
    register_private_school,
    setup_ranking_locked,
    setup_signed_consultation,
    validate_error,
    validate_success,
)

DIRECTOR = build_user_headers("director-1", "FederalProgramsDirector")
ANALYST = build_user_headers("analyst-1", "ComplianceAnalyst")
MONITOR = build_user_headers("monitor-1", "SEAMonitor")
OMBUDSMAN = build_user_headers("omb-1", "PrivateSchoolOmbudsman")


class TestConsultationOpening:

    def test_duplicate_consultation_rejected(self):
        """PRD §3.6: "The school must have `nonprofit_verified` set, else
        `ERR_PRIVATE_SCHOOL_NOT_VERIFIED`, and the pair must be unique — a
        second consultation for the same grant and school is rejected with
        `ERR_DUPLICATE_CONSULTATION`."

        Design: Corner/errors/duplicate_consultation_rejected
        """
        grant = open_grant(2070, 5_000_000)
        ps = register_private_school("Dup Academy", 10, "om@dup.example")
        open_consultation(grant["id"], ps["id"])
        resp = api_client.create_consultation(
            {"grant_id": grant["id"], "private_school_id": ps["id"]}, ANALYST)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CONSULTATION)

    def test_unverified_private_school_rejected(self):
        """PRD §3.6: "The school must have `nonprofit_verified` set, else
        `ERR_PRIVATE_SCHOOL_NOT_VERIFIED`, and the pair must be unique — a
        second consultation for the same grant and school is rejected with
        `ERR_DUPLICATE_CONSULTATION`."
        PRD §3.2: "a `nonprofit_verified` flag that defaults to false."

        Design: Corner/errors/unverified_private_school_rejected
        """
        grant = open_grant(2071, 5_000_000)
        ps = register_private_school("Unverified Academy", 8,
                                     "om@unv.example", nonprofit_verified=False)
        assert ps["nonprofit_verified"] is False
        resp = api_client.create_consultation(
            {"grant_id": grant["id"], "private_school_id": ps["id"]}, ANALYST)
        validate_error(resp, ApiErrorId.ERR_PRIVATE_SCHOOL_NOT_VERIFIED)

    def test_finalize_blocked_by_unsigned_consultation(self):
        """PRD §3.3: "Before any arithmetic, a consultation gate fires when
        the grant's `equitable_count_method` is `CONSULTATION_AGREED`: every
        private school with `nonprofit_verified` set must have a consultation
        for this grant in `AFFIRMATION_SIGNED` status, or finalization is
        rejected with `ERR_CONSULTATION_INCOMPLETE`."

        Design: Corner/errors/finalize_blocked_by_unsigned_consultation
        """
        ps = register_private_school("Gate Academy", 9, "om@gate.example")
        ctx = setup_ranking_locked(2072, [(50, 100)],
                                   total_allocation_cents=5_000_000,
                                   equitable_count_method="CONSULTATION_AGREED")
        consultation = open_consultation(ctx["grant"]["id"], ps["id"])
        record_session(consultation["id"], topics="introductions",
                       attendee_count=2)  # CONSULTING, unsigned
        resp = api_client.finalize_allocations(ctx["grant"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_CONSULTATION_INCOMPLETE)
        grant = validate_success(api_client.get_grant(ctx["grant"]["id"],
                                                      DIRECTOR))
        assert grant["status"] == "RANKING_LOCKED"


class TestConsultationSessionsAndSigning:

    def test_sign_affirmation_with_one_session_rejected(self):
        """PRD §3.6: "Signing requires the consultation to be in `CONSULTING`,
        requires at least two logged sessions — fewer is rejected with
        `ERR_INSUFFICIENT_CONSULTATION_SESSIONS` — and requires the grant to
        be in `SETUP` or `RANKING_LOCKED`, because affirmations lock before
        allocation; a grant already past that point yields
        `ERR_GRANT_INVALID_STATE`."

        Design: Corner/errors/sign_affirmation_with_one_session_rejected
        """
        grant = open_grant(2073, 5_000_000)
        ps = register_private_school("Session Academy", 7, "om@ses.example")
        consultation = open_consultation(grant["id"], ps["id"])
        record_session(consultation["id"], topics="needs", attendee_count=2)
        resp = api_client.sign_affirmation(
            consultation["id"], {"agreed_low_income_count": 7}, OMBUDSMAN)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CONSULTATION_SESSIONS)
        record_session(consultation["id"], topics="funding", attendee_count=2)
        ok = validate_success(api_client.sign_affirmation(
            consultation["id"], {"agreed_low_income_count": 7}, OMBUDSMAN))
        assert ok["status"] == "AFFIRMATION_SIGNED"
        assert ok["sessions_count"] == 2

    def test_record_session_on_signed_consultation_rejected(self):
        """PRD §3.6: "Logging is permitted from `INITIATED` (the first session
        moves the consultation to `CONSULTING`), from `CONSULTING` itself (a
        self-loop), and from `DISPUTED` (resuming after a dispute); from any
        other status it is rejected with `ERR_CONSULTATION_INVALID_STATE`."

        Design: Corner/errors/record_session_on_signed_consultation_rejected
        """
        grant = open_grant(2074, 5_000_000)
        ps = register_private_school("Signed Academy", 6, "om@sgn.example")
        consultation = setup_signed_consultation(grant["id"], ps["id"], 6)
        assert consultation["status"] == "AFFIRMATION_SIGNED"
        resp = api_client.record_session(
            consultation["id"],
            {"session_date": "2026-08-01", "topics": "late session",
             "attendee_count": 2},
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_CONSULTATION_INVALID_STATE)
        after = validate_success(
            api_client.get_consultation(consultation["id"], DIRECTOR))
        assert after["sessions_count"] == 2

    def test_session_date_in_future_rejected(self):
        """PRD §3.6: "A `session_date` after the current clock date is
        rejected with `ERR_SESSION_DATE_IN_FUTURE`."
        PRD §2.10: "At startup, before any client call, the clock reads
        exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock
        time."

        Design: Corner/errors/session_date_in_future_rejected
        """
        grant = open_grant(2088, 5_000_000)
        ps = register_private_school("Future Academy", 5, "om@fut.example")
        consultation = open_consultation(grant["id"], ps["id"])
        resp = api_client.record_session(
            consultation["id"],
            {"session_date": "2027-01-01", "topics": "premature",
             "attendee_count": 2},
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_DATE_IN_FUTURE)
        after = validate_success(
            api_client.get_consultation(consultation["id"], DIRECTOR))
        assert after["sessions_count"] == 0
        assert after["status"] == "INITIATED"


class TestConsultationDisputeResumeCycle:

    def test_consultation_dispute_resume_cycle(self):
        """PRD §3.6: "The ombudsman who disagrees may instead dispute the
        outcome from `CONSULTING`, recording a `dispute_reason` as the
        consultation moves to `DISPUTED`; from `DISPUTED` they may escalate to
        a formal SEA complaint by filing `complaint_text`, moving to
        `COMPLAINT_FILED`. An `SEAMonitor` resolves the complaint by posting
        the SEA's `determination_note`, which is recorded as
        `complaint_determination` while the consultation returns to
        `CONSULTING` for continued work. Every one of these transitions
        enforces its source state with `ERR_CONSULTATION_INVALID_STATE`."
        PRD §3.6: "Sessions are logged by the analyst, each appending an entry
        of `session_date`, `topics`, and `attendee_count` to the append-only
        `sessions` array and incrementing `sessions_count` by one."

        Design: Difficulty/non_linear_state_machine/consultation_dispute_resume_cycle
        """
        grant = open_grant(2041, 5_000_000,
                           equitable_count_method="CONSULTATION_AGREED")
        ps = register_private_school("Pilot Academy", 12, "om@pilot.example")
        consultation = open_consultation(grant["id"], ps["id"])
        record_session(consultation["id"], topics="needs assessment")
        record_session(consultation["id"], topics="count methodology")

        disputed = validate_success(api_client.dispute_consultation(
            consultation["id"],
            {"dispute_reason": "district used an outdated survey source for "
                               "the count"},
            OMBUDSMAN))
        assert disputed["status"] == "DISPUTED"

        # Resume loop: logging a session from DISPUTED returns to CONSULTING.
        resumed = record_session(consultation["id"],
                                 topics="reconciliation of count source",
                                 attendee_count=5)
        assert resumed["status"] == "CONSULTING"
        assert resumed["sessions_count"] == 3, \
            "sessions survive the dispute (append-only log)"

        validate_success(api_client.dispute_consultation(
            consultation["id"],
            {"dispute_reason": "proportional share still contested"},
            OMBUDSMAN))
        complaint = validate_success(api_client.file_complaint(
            consultation["id"],
            {"complaint_text": "formal complaint: consultation was not "
                               "timely and meaningful"},
            OMBUDSMAN))
        assert complaint["status"] == "COMPLAINT_FILED"

        resolved = validate_success(api_client.resolve_complaint(
            consultation["id"],
            {"determination_note": "SEA directs the district to apply the "
                                   "updated survey count"},
            MONITOR))
        assert resolved["status"] == "CONSULTING", \
            "second reversion to CONSULTING in one lifecycle"

        signed = validate_success(api_client.sign_affirmation(
            consultation["id"], {"agreed_low_income_count": 14}, OMBUDSMAN))
        assert signed["status"] == "AFFIRMATION_SIGNED"
        assert signed["sessions_count"] == 3
        assert signed["agreed_low_income_count"] == 14

    def test_dispute_and_complaint_enforce_source_states(self):
        """PRD §3.6: "The ombudsman who disagrees may instead dispute the
        outcome from `CONSULTING`, recording a `dispute_reason` as the
        consultation moves to `DISPUTED`; from `DISPUTED` they may escalate to
        a formal SEA complaint by filing `complaint_text`, moving to
        `COMPLAINT_FILED`. An `SEAMonitor` resolves the complaint by posting
        the SEA's `determination_note`, which is recorded as
        `complaint_determination` while the consultation returns to
        `CONSULTING` for continued work. Every one of these transitions
        enforces its source state with `ERR_CONSULTATION_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/consultation_dispute_resume_cycle
        """
        grant = open_grant(2040, 5_000_000)
        ps = register_private_school("State Academy", 11,
                                     "om@state.example")
        consultation = open_consultation(grant["id"], ps["id"])
        record_session(consultation["id"], topics="needs")
        # file-complaint requires DISPUTED; the consultation is CONSULTING.
        resp = api_client.file_complaint(
            consultation["id"], {"complaint_text": "premature complaint"},
            OMBUDSMAN)
        validate_error(resp, ApiErrorId.ERR_CONSULTATION_INVALID_STATE)
        disputed = validate_success(api_client.dispute_consultation(
            consultation["id"], {"dispute_reason": "count contested"},
            OMBUDSMAN))
        assert disputed["status"] == "DISPUTED"
        # dispute requires CONSULTING; already DISPUTED here.
        resp = api_client.dispute_consultation(
            consultation["id"], {"dispute_reason": "second dispute"},
            OMBUDSMAN)
        validate_error(resp, ApiErrorId.ERR_CONSULTATION_INVALID_STATE)
        # The resume loop restores CONSULTING with the log intact.
        resumed = record_session(consultation["id"], topics="reconciliation")
        assert resumed["status"] == "CONSULTING"
        assert resumed["sessions_count"] == 2

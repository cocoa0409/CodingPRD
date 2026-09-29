"""Requests that break two rules at once, and must be told about the earlier one.

Each scenario is arranged so a naive implementation could plausibly answer with the later
code; the assertions pin the earlier one and then show the later check never ran.
"""
from test_helpers import (
    ApiErrorId,
    class_session_payload,
    create_employer_account,
    enrollment_payload,
    get_account,
    get_session,
    get_trainer_row,
    lock_roster,
    enroll_server,
    make_employer_admin_headers,
    register_alcohol_server,
    setup_training_base,
    validate_error,
    validate_paginated,
)

CONFLICT_CLOCK = "2026-08-20T09:00:00Z"
CREDENTIAL_EXPIRES_AT = "2026-08-25T16:00:00Z"
FIRST_SESSION_START = "2026-08-25T09:00:00Z"
FIRST_SESSION_END = "2026-08-25T13:00:00Z"
SECOND_SESSION_START = "2026-08-25T14:00:00Z"
SECOND_SESSION_END = "2026-08-25T18:00:00Z"


def _locked_roster_with_a_penniless_sponsor():
    """A ROSTER_LOCKED session plus an account that has never bought a seat credit."""
    base = setup_training_base()
    account = create_employer_account(legal_name="Zero Credit Cantina")
    employer_headers = make_employer_admin_headers(account["id"])

    first_server = register_alcohol_server(base["jurisdiction"]["id"])
    second_server = register_alcohol_server(
        base["jurisdiction"]["id"], full_name="Bo Nakamura", email="bo@example.com")
    enroll_server(base["session"]["id"], first_server["id"])
    lock_roster(base["session"]["id"], base["trainer_headers"])

    session = get_session(base["session"]["id"])
    return base, account, employer_headers, second_server, session


class TestRosterStateOutranksSeatCredits:
    def test_a_locked_roster_is_reported_before_an_empty_credit_balance(self, api):
        """PRD §2.9: "Checks are evaluated in the following strict priority order, with the
        first failure short-circuiting the request:"
        PRD §2.9: "Class-session state matches the from-state of the requested transition —
        `ERR_SESSION_INVALID_STATE`."
        PRD §2.9: "The sponsoring account has a seat credit to spend —
        `ERR_INSUFFICIENT_SEAT_CREDITS`."
        PRD §3.5: "The session must still be `SCHEDULED` — enrolling into a `ROSTER_LOCKED`
        session is `ERR_SESSION_INVALID_STATE` — and `enrolled_count` must be strictly less than
        `capacity`, otherwise `ERR_SESSION_AT_CAPACITY`."
        PRD §3.5: "A sponsored seat requires the sponsoring account to have
        `seat_credit_balance` of at least one, failing with `ERR_INSUFFICIENT_SEAT_CREDITS`
        (HTTP 402), and requires the account's `account_status` not to be `SUSPENDED`, failing
        with `ERR_ACCOUNT_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/session_roster_locked_state_outranks_insufficient_seat_credits
        """
        base, account, employer_headers, second_server, session = (
            _locked_roster_with_a_penniless_sponsor())
        assert account["seat_credit_balance"] == 0

        response = api.create_enrollment(
            enrollment_payload(session["id"], second_server["id"], session["version"],
                               sponsoring_employer_account_id=account["id"]),
            employer_headers)
        validate_error(response, ApiErrorId.ERR_SESSION_INVALID_STATE, 409)

    def test_the_seat_credit_ledger_and_the_roster_are_both_left_alone(self, api):
        """PRD §2.9: "Many endpoints carry several checks at once, and the order in which they
        are evaluated is part of the contract — a caller who violates two rules must be told
        about the earlier one."
        PRD §3.8: "The seat-credit ledger is an identity that must hold at all times:
        `seat_credit_balance` equals `seat_credits_purchased_total` minus
        `seat_credits_consumed_total` plus `seat_credits_refunded_total`."
        PRD §3.5: "An accepted enrollment lands in `REGISTERED`, raises the session's
        `enrolled_count` by one and increments the session's `version` by one."
        PRD §3.6: "Locking the roster moves a class `SCHEDULED → ROSTER_LOCKED` and is the
        point after which no further seats may be claimed."

        Design: Difficulty/priority_pair_validation_conflict/session_roster_locked_state_outranks_insufficient_seat_credits
        """
        base, account, employer_headers, second_server, session = (
            _locked_roster_with_a_penniless_sponsor())

        api.create_enrollment(
            enrollment_payload(session["id"], second_server["id"], session["version"],
                               sponsoring_employer_account_id=account["id"]),
            employer_headers)

        after_account = get_account(account["id"])
        assert after_account["seat_credit_balance"] == 0
        assert after_account["seat_credits_consumed_total"] == 0, (
            "the seat-credit check never executed, got "
            f"{after_account['seat_credits_consumed_total']}")

        seats, meta = validate_paginated(api.list_enrollments(
            base["trainer_headers"], {"class_session_id": session["id"]}))
        assert meta["total_count"] == 1, (
            f"the refused request created no seat, got {meta['total_count']}")

        after_session = get_session(session["id"])
        assert after_session["enrolled_count"] == 1
        assert after_session["session_status"] == "ROSTER_LOCKED"
        assert after_session["version"] == session["version"], (
            "a refused enrollment does not bump the roster revision, got "
            f"{after_session['version']} against {session['version']}")


class TestCredentialGapOutranksScheduleConflict:
    def test_an_uncovered_credential_is_reported_before_the_buffered_conflict(self, api):
        """PRD §2.9: "The instructing trainer, and at exam opening the proctor, is properly
        credentialed — `ERR_TRAINER_NOT_CERTIFIED`."
        PRD §3.5: "If that widened closed interval intersects the closed interval from
        `scheduled_start_at` to `scheduled_end_at` of any other class session with the same
        instructing trainer whose `session_status` is `SCHEDULED`, `ROSTER_LOCKED` or
        `EXAM_OPEN`, the request is refused with `ERR_TRAINER_SCHEDULE_CONFLICT`."
        PRD §3.5: "The instructing trainer must have `trainer_status` equal to `CERTIFIED`,
        must list the course's `track` among `certified_tracks`, must list the jurisdiction's
        `state_code` among `certified_state_codes`, and must hold a `credential_expires_at`
        strictly after the session's `scheduled_end_at` — a credential that would lapse
        mid-class is not good enough."
        PRD §3.5: "The requested window is widened by one hour on each side into a closed
        interval running from `scheduled_start_at` minus sixty minutes to `scheduled_end_at`
        plus sixty minutes."
        PRD §3.5: "Because both intervals are closed, a class beginning exactly one hour after
        another ends still conflicts."

        Design: Difficulty/priority_pair_validation_conflict/trainer_certification_gap_outranks_buffered_schedule_conflict
        """
        base = setup_training_base(
            clock=CONFLICT_CLOCK,
            credential_overrides={"credential_expires_at": CREDENTIAL_EXPIRES_AT},
            session_overrides={"scheduled_start_at": FIRST_SESSION_START,
                               "scheduled_end_at": FIRST_SESSION_END})

        response = api.create_class_session(
            class_session_payload(base["course"]["id"], base["jurisdiction"]["id"],
                                  base["trainer"]["id"],
                                  scheduled_start_at=SECOND_SESSION_START,
                                  scheduled_end_at=SECOND_SESSION_END, capacity=20),
            base["trainer_headers"])
        validate_error(response, ApiErrorId.ERR_TRAINER_NOT_CERTIFIED, 422)

    def test_the_refused_request_leaves_the_trainers_schedule_and_metrics_untouched(self, api):
        """PRD §2.9: "Many endpoints carry several checks at once, and the order in which they
        are evaluated is part of the contract — a caller who violates two rules must be told
        about the earlier one."
        PRD §3.5: "A new session lands in `SCHEDULED` with `enrolled_count` and `passed_count`
        at zero, `proctor_trainer_id`, `exam_opened_at`, `completed_at` and
        `cancellation_reason` unset."
        PRD §3.4: "`sessions_taught_count` is the number of class sessions in `COMPLETED`
        naming this trainer as instructor."
        PRD §3.4: "Teaching metrics are recomputed whenever one of this trainer's classes
        completes, never on read."

        Design: Difficulty/priority_pair_validation_conflict/trainer_certification_gap_outranks_buffered_schedule_conflict
        """
        base = setup_training_base(
            clock=CONFLICT_CLOCK,
            credential_overrides={"credential_expires_at": CREDENTIAL_EXPIRES_AT},
            session_overrides={"scheduled_start_at": FIRST_SESSION_START,
                               "scheduled_end_at": FIRST_SESSION_END})

        api.create_class_session(
            class_session_payload(base["course"]["id"], base["jurisdiction"]["id"],
                                  base["trainer"]["id"],
                                  scheduled_start_at=SECOND_SESSION_START,
                                  scheduled_end_at=SECOND_SESSION_END, capacity=20),
            base["trainer_headers"])

        sessions, meta = validate_paginated(api.list_class_sessions(
            base["trainer_headers"], {"trainer_id": base["trainer"]["id"]}))
        assert meta["total_count"] == 1, (
            f"no second class was created, got {meta['total_count']}")
        assert sessions[0]["id"] == base["session"]["id"]

        assert get_session(base["session"]["id"])["session_status"] == "SCHEDULED"
        trainer = get_trainer_row(base["trainer"]["id"])
        assert trainer["trainer_status"] == "CERTIFIED"
        assert trainer["sessions_taught_count"] == 0

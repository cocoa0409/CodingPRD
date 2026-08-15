"""Case notes (append-only ledger, conditional outcome) and the closure gate
that requires a follow-up outcome on file."""
from test_helpers import (
    CLOCK_DEFAULT,
    ApiErrorId,
    append_follow_up_note,
    assert_case_note,
    assert_clock_instant,
    create_application,
    create_case_note_payload,
    create_household,
    create_vendor,
    get_application,
    set_clock,
    setup_paid,
    TEST_USERS,
    validate_error,
    validate_success,
)

CW1 = TEST_USERS["caseworker_headers"]


def _intake_application(api):
    vendor = create_vendor("LANDLORD")
    household = create_household()
    return create_application(household["id"], vendor["id"])


class TestCaseNotes:
    def test_case_note_immutable_no_version_and_default_occurred_at(self, api):
        """PRD §2.5: "Three record types are append-only ledgers and carry only
        `id` and `created_at`: ApplicationDocument, CaseNote, and ReplenishmentRun.
        On these three, both `updated_at` and `version` are absent."
        PRD §3.9: "an optional `occurred_at` that defaults to the logical clock
        time when omitted; the server records the writer as `author_id`."
        PRD §2.4: "At startup the clock reads exactly 2026-08-01T00:00:00Z."

        Design: Corner/entities/case_note_immutable_no_version_and_default_occurred_at
        """
        set_clock(CLOCK_DEFAULT)
        application = _intake_application(api)
        resp = api.create_case_note(
            application["id"],
            create_case_note_payload("GENERAL", "initial intake conversation"),
            CW1,
        )
        data = validate_success(resp, 201)
        assert_case_note(data)  # also pins absence of version/updated_at
        assert_clock_instant(data["occurred_at"], CLOCK_DEFAULT)
        assert data["author_id"] == "cw-1"

    def test_follow_up_note_missing_outcome_rejected(self, api):
        """PRD §3.9: "A `FOLLOW_UP` note must additionally carry an `outcome` —
        one of `CRISIS_RESOLVED`, `PARTIAL_RELIEF`, `NO_CHANGE`, or `LOST_CONTACT`
        — and its absence on a follow-up note is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/follow_up_note_missing_outcome_rejected
        """
        application = _intake_application(api)
        resp = api.create_case_note(
            application["id"],
            {"note_type": "FOLLOW_UP", "body": "called the family"},
            CW1,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # Control: a GENERAL note without an outcome is accepted.
        ok = api.create_case_note(
            application["id"],
            create_case_note_payload("GENERAL", "called the family"),
            CW1,
        )
        validate_success(ok, 201)


class TestClosureFollowUpGate:
    def test_close_rejected_without_follow_up_note(self, api):
        """PRD §3.9: "At least one case note of type `FOLLOW_UP` must exist for
        the application before it can close, else the attempt is rejected with
        `ERR_FOLLOW_UP_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/close_gated_by_followup_case_note
        """
        ctx = setup_paid(requested_amount_cents=10000)
        assert ctx["application"]["status"] == "PAID"
        resp = api.close_application(ctx["application"]["id"], CW1)
        validate_error(resp, ApiErrorId.ERR_FOLLOW_UP_REQUIRED)
        assert get_application(ctx["application"]["id"])["status"] == "PAID"

    def test_close_succeeds_after_follow_up_note_recorded(self, api):
        """PRD §3.9: "At least one case note of type `FOLLOW_UP` must exist for
        the application before it can close, else the attempt is rejected with
        `ERR_FOLLOW_UP_REQUIRED`."
        PRD §3.9: "A successful close stamps `closed_at` from the logical clock,
        lands the application in the terminal `CLOSED` state, and bumps its
        `version`."

        Design: Difficulty/cross_entity_state_dependency/close_gated_by_followup_case_note
        """
        ctx = setup_paid(requested_amount_cents=10000)
        app_id = ctx["application"]["id"]
        version_before = ctx["application"]["version"]
        append_follow_up_note(app_id, body="family stable after payment",
                              outcome="CRISIS_RESOLVED")
        resp = api.close_application(app_id, CW1)
        data = validate_success(resp, 200)
        assert data["status"] == "CLOSED"
        assert data["version"] > version_before, "close must bump the application version"
        assert_clock_instant(data["closed_at"], CLOCK_DEFAULT)

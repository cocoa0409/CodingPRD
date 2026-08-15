"""Meeting creation, record-date list building, and uniqueness constraints
(PRD §3.1, §3.2)."""
from datetime import datetime

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_meeting, assert_shareholder_account,
    create_meeting_payload, create_shareholder_account_payload, create_proposal_payload,
    create_draft_meeting, add_account, lock_record_date,
    CLOCK_DEFAULT_ISO,
)


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestMeetingCreation:
    def test_meeting_creation_applies_defaults_and_system_fields(self, api, proxy_admin_headers):
        """PRD §3.1: "A new meeting begins in `DRAFT` status."
        PRD §3.1: "The meeting resource also carries two system fields that stay
        null until the very end of the lifecycle — `filed_at` and
        `filing_reference`, populated only when results are filed — and a
        `walk_in_shares` counter, initially zero, that records shares present at
        the meeting without a voted proxy and is counted only by the `FINAL`
        quorum variant."
        PRD §2.4: "At server startup the logical clock is set to exactly
        `2026-08-01T00:00:00Z` and the server must not fall back to wall-clock
        time under any circumstance."

        Design: Corner/entities/meeting_creation_applies_defaults_and_system_fields
        """
        resp = api.create_meeting(create_meeting_payload(), proxy_admin_headers)
        data = validate_success(resp, 201)
        assert_meeting(data)
        assert data["status"] == "DRAFT", f"expected DRAFT, got {data['status']}"
        assert data["walk_in_shares"] == 0, "walk_in_shares must start at zero"
        assert data["filed_at"] is None, "filed_at must be null until filing"
        assert data["filing_reference"] is None, "filing_reference must be null until filing"
        created = _parse_ts(data["created_at"])
        assert created == _parse_ts(CLOCK_DEFAULT_ISO), (
            f"created_at must come from the logical clock default "
            f"{CLOCK_DEFAULT_ISO}, got {data['created_at']}"
        )

    def test_meeting_missing_required_field_returns_invalid_request(self, api, proxy_admin_headers):
        """PRD §3.1: the administrator supplies "the `outstanding_shares` as of
        the record date, which must be a positive integer" (a required input).
        PRD §2.6: "10. **Request body shape.** Required fields present, enum values
        valid, numbers in range, datetimes parseable (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/meeting_missing_required_field_returns_invalid_request
        """
        payload = create_meeting_payload()
        del payload["outstanding_shares"]
        resp = api.create_meeting(payload, proxy_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_meeting_invalid_enum_returns_invalid_request(self, api, proxy_admin_headers):
        """PRD §3.1: "the `meeting_type` (`ANNUAL`, `SPECIAL`, or `CONTESTED`)"
        — `PROXY` is not a declared member.
        PRD §2.6: "10. **Request body shape.** Required fields present, enum values
        valid, numbers in range, datetimes parseable (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/meeting_invalid_enum_returns_invalid_request
        """
        resp = api.create_meeting(
            create_meeting_payload(meeting_type="PROXY"), proxy_admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_record_date_not_before_meeting_returns_record_date_invalid(self, api, proxy_admin_headers):
        """PRD §3.1: "The `record_date` must fall strictly before the
        `meeting_datetime`; this ordering is enforced at creation, on every
        amendment, and again at record-date lock, with violations rejected as
        `ERR_RECORD_DATE_INVALID`."

        Design: Corner/validations/record_date_not_before_meeting_returns_record_date_invalid
        """
        resp = api.create_meeting(
            create_meeting_payload(record_date="2026-09-16"), proxy_admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_RECORD_DATE_INVALID, 422)


class TestRecordDateList:
    def test_account_creation_applies_defaults_and_mints_control_number(self, api, transfer_agent_headers):
        """PRD §3.2: "a `delivery_preference` of `NOTICE_AND_ACCESS`,
        `FULL_MAIL`, or `E_DELIVERY` (defaulting to `NOTICE_AND_ACCESS`), and a
        `householding_opt_out` flag (defaulting to `false`)"; "At creation the
        system mints the holder's `control_number` — a 12-digit number printed
        on the holder's materials and required on remote-channel votes — and
        sets the account's `status` to `PENDING`."

        Design: Corner/entities/account_creation_applies_defaults_and_mints_control_number
        """
        meeting = create_draft_meeting()
        resp = api.create_shareholder_account(
            create_shareholder_account_payload(meeting["id"], "A-1001"),
            transfer_agent_headers,
        )
        data = validate_success(resp, 201)
        assert_shareholder_account(data)
        assert data["delivery_preference"] == "NOTICE_AND_ACCESS", "default delivery preference"
        assert data["householding_opt_out"] is False, "default householding_opt_out"
        cn = data["control_number"]
        assert str(cn).isdigit() and len(str(cn)) == 12, (
            f"control_number must be a minted 12-digit value, got {cn!r}"
        )
        assert data["status"] == "PENDING", f"expected PENDING, got {data['status']}"

    def test_create_account_zero_shares_returns_invalid_request(self, api, transfer_agent_headers):
        """PRD §3.2: "the `shares_held` on the record date as a positive
        integer".
        PRD §2.6: "10. **Request body shape.** Required fields present, enum values
        valid, numbers in range, datetimes parseable (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/create_account_zero_shares_returns_invalid_request
        """
        meeting = create_draft_meeting()
        resp = api.create_shareholder_account(
            create_shareholder_account_payload(meeting["id"], "A-1001", shares_held=0),
            transfer_agent_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_account_creation_blocked_after_record_date_lock(self, api, transfer_agent_headers):
        """PRD §3.2: "Accounts may only be added while the meeting is `DRAFT`;
        the attempt against any later state fails with
        `ERR_INVALID_MEETING_STATE`."

        Design: Corner/entities/account_creation_blocked_after_record_date_lock
        """
        meeting = create_draft_meeting()
        add_account(meeting["id"], "A-1001")
        lock_record_date(meeting["id"])
        resp = api.create_shareholder_account(
            create_shareholder_account_payload(meeting["id"], "A-1002", shares_held=100),
            transfer_agent_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_MEETING_STATE, 409)

    def test_lock_record_date_activates_eligible_accounts(self, api, proxy_admin_headers):
        """PRD §3.2: "The lock snapshots the list: every account of the meeting
        transitions `PENDING → ELIGIBLE`, and the meeting moves `DRAFT →
        RECORD_DATE_LOCKED` with its `version` incremented by one."

        Design: Corner/state_machines/lock_record_date_activates_eligible_accounts
        """
        meeting = create_draft_meeting()
        a1 = add_account(meeting["id"], "A-1001", shares_held=6000)
        a2 = add_account(meeting["id"], "A-1002", shares_held=4000)
        locked = lock_record_date(meeting["id"])
        assert locked["status"] == "RECORD_DATE_LOCKED"
        for account in (a1, a2):
            resp = api.get_shareholder_account(account["id"], proxy_admin_headers)
            data = validate_success(resp, 200)
            assert data["status"] == "ELIGIBLE", (
                f"account {account['account_number']} must flip to ELIGIBLE, got {data['status']}"
            )

    def test_duplicate_account_number_within_meeting_returns_conflict(self, api, transfer_agent_headers):
        """PRD §3.2: "an `account_number` that must be unique within the meeting
        (duplicates are rejected with `ERR_DUPLICATE_ACCOUNT_NUMBER`)".

        Design: Corner/validations/duplicate_account_number_within_meeting_returns_conflict
        """
        meeting = create_draft_meeting()
        add_account(meeting["id"], "A-1001")
        resp = api.create_shareholder_account(
            create_shareholder_account_payload(meeting["id"], "A-1001", shares_held=100),
            transfer_agent_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACCOUNT_NUMBER, 409)

    def test_duplicate_proposal_number_within_meeting_returns_conflict(self, api, proxy_admin_headers):
        """PRD §3.4: "a `proposal_number` unique within the meeting
        (`ERR_DUPLICATE_PROPOSAL_NUMBER` on collision)".

        Design: Corner/validations/duplicate_proposal_number_within_meeting_returns_conflict
        """
        meeting = create_draft_meeting()
        resp = api.create_proposal(create_proposal_payload(meeting["id"], 1), proxy_admin_headers)
        validate_success(resp, 201)
        resp = api.create_proposal(
            create_proposal_payload(
                meeting["id"], 1, title="Ratify auditor", proposal_type="RATIFICATION"
            ),
            proxy_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PROPOSAL_NUMBER, 409)

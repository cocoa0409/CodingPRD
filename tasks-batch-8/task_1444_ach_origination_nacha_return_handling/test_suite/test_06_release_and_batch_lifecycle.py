"""Release preconditions, batch state gates, and cross-entity release gating."""
from test_helpers import (
    ApiErrorId,
    create_warehoused_file,
    entry_payload,
    open_manual_risk_case,
    read_batch,
    read_file,
    read_originator,
    release_file_ok,
    resolve_case_ok,
    set_clock,
    setup_file_with_entries,
    setup_released_file,
    setup_standard_environment,
    validate_error,
    validate_success,
)


def test_release_already_released_file_rejected(api, operations_headers):
    """PRD 3.4: "The file must be `WAREHOUSED` (`ERR_FILE_NOT_WAREHOUSED`),
    its originator must be `ACTIVE` (`ERR_ORIGINATOR_NOT_ACTIVE`), the file
    must contain at least one entry (`ERR_FILE_EMPTY`), the current banking day
    under the logical clock must equal the file's `effective_date`
    (`ERR_RELEASE_DATE_MISMATCH`), and window rows must exist to support the
    assignment rule (`ERR_NO_ELIGIBLE_WINDOW`)."

    Design: Corner/state_machines/release_already_released_file_returns_invalid_state
    """
    org = setup_standard_environment("State Co")
    released, batch_id = setup_released_file(
        org, [entry_payload("DEBIT", 100_000, "st-1")])

    res = api.release_file(released["id"], operations_headers)
    validate_error(res, ApiErrorId.ERR_FILE_NOT_WAREHOUSED, expected_status=409)

    after = read_file(released["id"])
    assert after["status"] == "RELEASED"
    assert after["settlement_batch_id"] == batch_id, \
        "a rejected second release must not reassign the batch"


def test_settle_open_batch_rejected(api, operations_headers):
    """PRD 3.5: "Settling a batch (`action` of `SETTLE`) requires the batch to
    be `DISPATCHED`, otherwise `ERR_BATCH_NOT_OPEN`."

    Design: Corner/state_machines/settle_open_batch_returns_invalid_state
    """
    org = setup_standard_environment("Batch Co")
    _, batch_id = setup_released_file(org, [entry_payload("DEBIT", 100_000, "bt-1")])

    res = api.advance_batch(batch_id, {"action": "SETTLE"}, operations_headers)
    validate_error(res, ApiErrorId.ERR_BATCH_NOT_OPEN, expected_status=409)

    assert read_batch(batch_id)["status"] == "OPEN"


def test_release_empty_file_rejected(api, operations_headers):
    """PRD 3.4: "The file must be `WAREHOUSED` (`ERR_FILE_NOT_WAREHOUSED`),
    its originator must be `ACTIVE` (`ERR_ORIGINATOR_NOT_ACTIVE`), the file
    must contain at least one entry (`ERR_FILE_EMPTY`), the current banking day
    under the logical clock must equal the file's `effective_date`
    (`ERR_RELEASE_DATE_MISMATCH`), and window rows must exist to support the
    assignment rule (`ERR_NO_ELIGIBLE_WINDOW`)."

    Design: Corner/state_machines/release_empty_file_returns_file_empty
    """
    org = setup_standard_environment("Empty Co")
    ach_file = create_warehoused_file(org, "CCD", "NEXT_DAY", "2026-08-03")

    res = api.release_file(ach_file["id"], operations_headers)
    validate_error(res, ApiErrorId.ERR_FILE_EMPTY, expected_status=422)

    assert read_file(ach_file["id"])["status"] == "WAREHOUSED"


def test_release_before_effective_date_rejected_then_succeeds(
        api, operations_headers):
    """PRD 3.4: "the current banking day under the logical clock must equal the
    file's `effective_date` (`ERR_RELEASE_DATE_MISMATCH`)"
    PRD 3.4: "the `settlement_date` follows from it: today when a same-day
    window was assigned, or the next banking day when the file rolled to
    `NEXT_DAY`."

    Design: Corner/state_machines/release_on_wrong_effective_date_returns_mismatch
    """
    org = setup_standard_environment("Date Co")
    ach_file = setup_file_with_entries(
        org, [entry_payload("DEBIT", 100_000, "dt-1")], effective_date="2026-08-04")

    early = api.release_file(ach_file["id"], operations_headers)
    validate_error(early, ApiErrorId.ERR_RELEASE_DATE_MISMATCH,
                   expected_status=409)
    assert read_file(ach_file["id"])["status"] == "WAREHOUSED"

    set_clock("2026-08-04T10:00:00Z")
    released = release_file_ok(ach_file["id"])
    assert released["status"] == "RELEASED"
    assert released["assigned_window_kind"] == "NEXT_DAY"
    # 2026-08-04 is a Tuesday; the next banking day is Wednesday 2026-08-05.
    assert released["settlement_date"] == "2026-08-05"


def _setup_watch_originator_with_file():
    """ACTIVE originator with a one-entry WAREHOUSED file, moved to WATCH."""
    org = setup_standard_environment("Omicron Ltd")
    ach_file = setup_file_with_entries(org, [entry_payload("DEBIT", 100_000, "o-1")])
    case = open_manual_risk_case(org["id"])
    resolve_case_ok(case["id"], "WATCH")
    return org, ach_file


class TestReleaseRequiresActiveOriginator:
    def test_release_with_watch_originator_rejected(self, api, operations_headers):
        """PRD 3.4: "its originator must be `ACTIVE`
        (`ERR_ORIGINATOR_NOT_ACTIVE`)"
        PRD 3.8: "`WATCH` applies only to an `ACTIVE` originator and moves it to
        `WATCH`."

        Design: Difficulty/cross_entity_state_dependency/file_release_requires_originator_active
        """
        org, ach_file = _setup_watch_originator_with_file()
        assert read_originator(org["id"])["status"] == "WATCH"

        res = api.release_file(ach_file["id"], operations_headers)
        validate_error(res, ApiErrorId.ERR_ORIGINATOR_NOT_ACTIVE,
                       expected_status=409)

    def test_rejected_release_leaves_file_warehoused(self, api,
                                                     operations_headers):
        """PRD 3.4: "Release is the bank's act: an `OdfiOperations` operator
        releases a file, moving it from `WAREHOUSED` to `RELEASED`."
        PRD 3.4: "its originator must be `ACTIVE` (`ERR_ORIGINATOR_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/file_release_requires_originator_active
        """
        org, ach_file = _setup_watch_originator_with_file()

        res = api.release_file(ach_file["id"], operations_headers)
        validate_error(res, ApiErrorId.ERR_ORIGINATOR_NOT_ACTIVE,
                       expected_status=409)

        after = read_file(ach_file["id"])
        assert after["status"] == "WAREHOUSED"
        # PRD 3.3: pre-release fields "remain unset until release" — a rejected
        # release must leave them unset (absent or null).
        assert after.get("settlement_batch_id") is None
        assert after.get("assessed_fee_cents") is None

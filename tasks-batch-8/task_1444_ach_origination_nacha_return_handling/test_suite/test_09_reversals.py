"""Reversal requests: eligibility window, duplicate ceiling, advance branches."""
from test_helpers import (
    ApiErrorId,
    advance_reversal_ok,
    assert_reversal_request,
    create_reversal_ok,
    entry_payload,
    get_success_data,
    make_originator_headers,
    set_clock,
    setup_released_file,
    setup_settled_file,
    setup_standard_environment,
    dispatch_batch_ok,
    list_file_entries,
    validate_error,
    validate_success,
)


def test_reversal_window_boundary(api, operations_headers):
    """PRD 3.7: "Timing is strict: the request's `window_expires_at` is computed
    as five banking days after the date of the entry's `settled_at`, and the
    request must be created on or before that date — a later attempt is rejected
    with `ERR_REVERSAL_WINDOW_EXPIRED`."

    Design: Corner/calculations/reversal_window_expiry_day_boundary
    """
    org = setup_standard_environment("Win Co")
    _, _, entries = setup_settled_file(org, [
        entry_payload("DEBIT", 100_000, "wn-1"),
        entry_payload("DEBIT", 100_000, "wn-2"),
    ])
    e1_id, e2_id = entries[0]["id"], entries[1]["id"]

    # Settled Monday 2026-08-03; five banking days later is Monday 2026-08-10.
    set_clock("2026-08-10T09:00:00Z")
    on_time = create_reversal_ok(e1_id, org["id"], "DUPLICATE_ENTRY")
    assert_reversal_request(on_time)
    assert on_time["status"] == "REQUESTED"
    assert on_time["window_expires_at"] == "2026-08-10", \
        "the expiry day itself is inside the window (inclusive boundary)"

    set_clock("2026-08-11T09:00:00Z")
    res = api.create_reversal(e2_id, {"reason": "DUPLICATE_ENTRY"},
                              make_originator_headers(org["id"]))
    validate_error(res, ApiErrorId.ERR_REVERSAL_WINDOW_EXPIRED,
                   expected_status=422)


def test_duplicate_active_reversal_rejected(api, operations_headers):
    """PRD 3.7: "One active reversal per entry is the structural ceiling: if
    the entry already has a reversal request in `REQUESTED` or `TRANSMITTED`,
    the new request is rejected with `ERR_DUPLICATE_ACTIVE_REVERSAL`."

    Design: Corner/calculations/duplicate_active_reversal_rejected
    """
    org = setup_standard_environment("Dup Co")
    _, _, entries = setup_settled_file(org, [entry_payload("DEBIT", 100_000, "dp-1")])
    entry_id = entries[0]["id"]

    create_reversal_ok(entry_id, org["id"], "DUPLICATE_ENTRY")

    res = api.create_reversal(entry_id, {"reason": "WRONG_AMOUNT"},
                              make_originator_headers(org["id"]))
    validate_error(res, ApiErrorId.ERR_DUPLICATE_ACTIVE_REVERSAL,
                   expected_status=409)

    reversals = get_success_data(
        api.list_reversal_requests(entry_id, operations_headers))
    assert len(reversals) == 1, "the rejected second request must not persist"


def test_reversal_cancel_branch_then_dead(api, operations_headers):
    """PRD 3.7: "Under `CANCEL`, performed by the owning `OriginatorOps` caller,
    the reversal moves from `REQUESTED` to `CANCELLED`."
    PRD 3.7: "Either action against a reversal no longer in `REQUESTED` —
    already transmitted, settled, or cancelled — is rejected with
    `ERR_REVERSAL_NOT_ACTIONABLE`."
    PRD 3.7: "One active reversal per entry is the structural ceiling: if the
    entry already has a reversal request in `REQUESTED` or `TRANSMITTED`, the
    new request is rejected with `ERR_DUPLICATE_ACTIVE_REVERSAL`."

    Design: Corner/state_machines/reversal_cancel_branch_then_not_actionable
    """
    org = setup_standard_environment("Cancel Co")
    _, _, entries = setup_settled_file(org, [entry_payload("DEBIT", 100_000, "cn-1")])
    entry_id = entries[0]["id"]

    set_clock("2026-08-04T09:00:00Z")
    reversal = create_reversal_ok(entry_id, org["id"], "DUPLICATE_ENTRY")

    cancelled = advance_reversal_ok(reversal["id"], "CANCEL",
                                    headers=make_originator_headers(org["id"]))
    assert cancelled["status"] == "CANCELLED"

    res = api.advance_reversal(reversal["id"], {"action": "TRANSMIT"},
                               operations_headers)
    validate_error(res, ApiErrorId.ERR_REVERSAL_NOT_ACTIONABLE,
                   expected_status=409)

    # A CANCELLED reversal is not active: the entry accepts a fresh request.
    fresh = create_reversal_ok(entry_id, org["id"], "WRONG_AMOUNT")
    assert fresh["status"] == "REQUESTED"
    assert fresh["window_expires_at"] == "2026-08-10"


def test_transmit_transmitted_reversal_rejected(api, operations_headers):
    """PRD 3.7: "Either action against a reversal no longer in `REQUESTED` —
    already transmitted, settled, or cancelled — is rejected with
    `ERR_REVERSAL_NOT_ACTIONABLE`."

    Design: Corner/state_machines/advance_transmitted_reversal_returns_invalid_state
    """
    org = setup_standard_environment("Adv Co")
    _, _, entries = setup_settled_file(org, [entry_payload("DEBIT", 100_000, "ad-1")])
    entry_id = entries[0]["id"]

    reversal = create_reversal_ok(entry_id, org["id"], "DUPLICATE_ENTRY")
    transmitted = advance_reversal_ok(reversal["id"], "TRANSMIT",
                                      headers=operations_headers)
    assert transmitted["status"] == "TRANSMITTED"

    res = api.advance_reversal(reversal["id"], {"action": "TRANSMIT"},
                               operations_headers)
    validate_error(res, ApiErrorId.ERR_REVERSAL_NOT_ACTIONABLE,
                   expected_status=409)

    reversals = get_success_data(
        api.list_reversal_requests(entry_id, operations_headers))
    assert reversals[0]["id"] == reversal["id"]
    assert reversals[0]["status"] == "TRANSMITTED"


def _setup_transmitted_entry():
    """Entry dispatched (TRANSMITTED) but not yet settled."""
    org = setup_standard_environment("Pi Corp")
    released, batch_id = setup_released_file(
        org, [entry_payload("DEBIT", 100_000, "p-1")])
    dispatch_batch_ok(batch_id)
    entry = list_file_entries(released["id"])[0]
    assert entry["status"] == "TRANSMITTED"
    return org, entry


class TestReversalRequiresSettledEntry:
    def test_reversal_on_transmitted_entry_rejected(self, api,
                                                    operations_headers):
        """PRD 3.7: "The entry must be in `SETTLED`, otherwise
        `ERR_ENTRY_NOT_SETTLED`, and the ownership chain is enforced as
        `ERR_RESOURCE_OWNERSHIP`."

        Design: Difficulty/cross_entity_state_dependency/reversal_requires_entry_settled
        """
        org, entry = _setup_transmitted_entry()

        res = api.create_reversal(entry["id"], {"reason": "DUPLICATE_ENTRY"},
                                  make_originator_headers(org["id"]))
        validate_error(res, ApiErrorId.ERR_ENTRY_NOT_SETTLED, expected_status=409)

    def test_rejected_reversal_persists_nothing(self, api, operations_headers):
        """PRD 3.7: "A compliant request is created in `REQUESTED` status with
        `requested_at` stamped at the logical clock."
        PRD 3.7: "The entry must be in `SETTLED`, otherwise
        `ERR_ENTRY_NOT_SETTLED`, and the ownership chain is enforced as
        `ERR_RESOURCE_OWNERSHIP`."

        Design: Difficulty/cross_entity_state_dependency/reversal_requires_entry_settled
        """
        org, entry = _setup_transmitted_entry()

        res = api.create_reversal(entry["id"], {"reason": "DUPLICATE_ENTRY"},
                                  make_originator_headers(org["id"]))
        validate_error(res, ApiErrorId.ERR_ENTRY_NOT_SETTLED, expected_status=409)

        reversals = get_success_data(
            api.list_reversal_requests(entry["id"], operations_headers))
        assert reversals == [], "no ReversalRequest may persist after a 409"

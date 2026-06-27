"""Matter intake, conflict screening, the conflict gate, and matter open/close.

Mixes queue A (non_linear_state_machine cyclic, cross_entity_state_dependency)
and queue B (state_machines, validations) instances.
"""
import pytest
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error, validate_error_is_one_of,
    ApiErrorId,
    create_matter_payload, create_conflict_check_payload, create_time_entry_payload,
    create_matter_in_intake, create_matter_conflict_cleared, create_open_matter,
    create_flagged_matter, create_timekeeper, create_client, ensure_billing_codes,
    setup_issued_invoice, capture_time_entry,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]
ATT = TEST_USERS["attorney_headers"]


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine / matter_conflict_cyclic_block_then_waive_clear
# ---------------------------------------------------------------------------
def test_flagged_screen_blocks_matter(api):
    """PRD §3.2: "If the candidate set is non-empty, `result` is `FLAGGED`; the
    system then takes the subset of candidates that are clients, orders them by
    `created_at` ascending, and sets `matched_client_id` to the earliest such
    client's `id`". PRD §3.2: "When it is `FLAGGED`, the system advances the
    matter from `CONFLICT_PENDING` to `CONFLICT_BLOCKED` instead."

    Design: Difficulty/non_linear_state_machine/matter_conflict_cyclic_block_then_waive_clear
    """
    matter, cc, subject_id, adverse_id, _ = create_flagged_matter(
        subject_name="Acme Corp", adverse_name="Rival Inc")
    assert cc["result"] == "FLAGGED"
    assert cc["matched_client_id"] == adverse_id
    m = validate_success(api.get_matter(matter["id"], CLERK))
    assert m["status"] == "CONFLICT_BLOCKED"


def test_waive_reopens_blocked_matter_to_cleared(api):
    """PRD §3.2: "the waiver sets the check's `result` to `WAIVED`, records the
    approving attorney's identifier on the check, and moves the matter from
    `CONFLICT_BLOCKED` back to `CONFLICT_CLEARED`."

    Design: Difficulty/non_linear_state_machine/matter_conflict_cyclic_block_then_waive_clear
    """
    matter, cc, subject_id, adverse_id, _ = create_flagged_matter(
        subject_name="Acme Corp", adverse_name="Rival Inc")
    waived = validate_success(api.waive_conflict_check(cc["id"], ATT))
    assert waived["result"] == "WAIVED"
    m = validate_success(api.get_matter(matter["id"], CLERK))
    assert m["status"] == "CONFLICT_CLEARED"


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency / matter_open_requires_conflict_cleared
# ---------------------------------------------------------------------------
def test_open_flagged_matter_rejected_conflict_not_cleared(api):
    """PRD §3.2: "a matter may not be opened, and no time or expense may be
    captured against it, unless its latest conflict check has a `result` of either
    `CLEAR` or `WAIVED`; a matter whose latest check is `FLAGGED` is
    `CONFLICT_BLOCKED`, and any of these three operations — opening the matter,
    capturing a time entry, or capturing an expense entry — is rejected with
    `ERR_CONFLICT_NOT_CLEARED` (HTTP 409) when the gate is not satisfied."

    Design: Difficulty/cross_entity_state_dependency/matter_open_requires_conflict_cleared
    """
    matter, cc, _, _, _ = create_flagged_matter()
    # PRD §3.2 names ERR_CONFLICT_NOT_CLEARED for opening a FLAGGED/CONFLICT_BLOCKED
    # matter; PRD §3.3 ("opens a matter that is in CONFLICT_CLEARED") + the §2.10
    # precedence (ERR_INVALID_STATE before ERR_CONFLICT_NOT_CLEARED) also admit a
    # faithful ERR_INVALID_STATE reading. Accept either.
    validate_error_is_one_of(
        api.open_matter(matter["id"], ATT),
        [ApiErrorId.ERR_CONFLICT_NOT_CLEARED, ApiErrorId.ERR_INVALID_STATE])


def test_open_blocked_matter_does_not_advance(api):
    """PRD §3.2: "a matter may not be opened ... unless its latest conflict check
    has a `result` of either `CLEAR` or `WAIVED`; a matter whose latest check is
    `FLAGGED` is `CONFLICT_BLOCKED`, and any of these three operations — opening
    the matter, capturing a time entry, or capturing an expense entry — is
    rejected with `ERR_CONFLICT_NOT_CLEARED` (HTTP 409) when the gate is not
    satisfied."

    Design: Difficulty/cross_entity_state_dependency/matter_open_requires_conflict_cleared
    """
    matter, cc, _, _, _ = create_flagged_matter()
    # PRD §3.2 names ERR_CONFLICT_NOT_CLEARED; §3.3 + §2.10 precedence also admit a
    # faithful ERR_INVALID_STATE reading. Accept either; the rejection is non-mutating.
    validate_error_is_one_of(
        api.open_matter(matter["id"], ATT),
        [ApiErrorId.ERR_CONFLICT_NOT_CLEARED, ApiErrorId.ERR_INVALID_STATE])
    m = validate_success(api.get_matter(matter["id"], CLERK))
    assert m["status"] == "CONFLICT_BLOCKED"


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency / matter_close_requires_no_issued_invoice
# ---------------------------------------------------------------------------
def test_close_matter_with_issued_invoice_rejected(api):
    """PRD §3.7: "no outstanding receivable, meaning the matter has no invoice
    whose `billing_status` is `ISSUED` or `PARTIALLY_PAID`. A close attempt that
    violates either condition is rejected with `ERR_MATTER_HAS_OPEN_BALANCE`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/matter_close_requires_no_issued_invoice
    """
    base = setup_issued_invoice()
    validate_error(api.close_matter(base["matter"]["id"], ATT),
                   ApiErrorId.ERR_MATTER_HAS_OPEN_BALANCE)


def test_close_matter_with_issued_invoice_keeps_matter_open(api):
    """PRD §3.7: "An `Attorney` closes an `OPEN` matter only when there is no
    un-invoiced work in progress — both `wip_fees_cents` and `wip_expenses_cents`
    must be zero — and no outstanding receivable, meaning the matter has no
    invoice whose `billing_status` is `ISSUED` or `PARTIALLY_PAID`. A close
    attempt that violates either condition is rejected with
    `ERR_MATTER_HAS_OPEN_BALANCE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/matter_close_requires_no_issued_invoice
    """
    base = setup_issued_invoice()
    validate_error(api.close_matter(base["matter"]["id"], ATT),
                   ApiErrorId.ERR_MATTER_HAS_OPEN_BALANCE)
    m = validate_success(api.get_matter(base["matter"]["id"], CLERK))
    assert m["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Section 2 — State Machines (queue B)
# ---------------------------------------------------------------------------
def test_matter_initial_state_is_intake(api):
    """PRD §3.1: "A new matter is created in `status` `INTAKE` with both
    `wip_fees_cents` and `wip_expenses_cents` at 0."

    Design: Corner/state_machines/matter_initial_state_is_intake
    """
    matter, _, _ = create_matter_in_intake()
    assert matter["status"] == "INTAKE"


def test_open_matter_from_intake_invalid_state(api):
    """PRD §3.3: "An `Attorney` opens a matter that is in `CONFLICT_CLEARED`,
    moving its `status` to `OPEN`." PRD §3.3: "an attempt to capture against a
    matter in any other state is an invalid-state rejection (`ERR_INVALID_STATE`,
    HTTP 409)."

    Design: Corner/state_machines/open_matter_from_intake_invalid_state
    """
    matter, _, _ = create_matter_in_intake()
    validate_error(api.open_matter(matter["id"], ATT), ApiErrorId.ERR_INVALID_STATE)


def test_clear_conflict_screen_moves_matter_to_cleared(api):
    """PRD §3.2: "If the candidate set is empty, `result` is `CLEAR` and
    `matched_client_id` is left null." PRD §3.2: "When the just-created check is
    `CLEAR`, the system advances the matter from `CONFLICT_PENDING` to
    `CONFLICT_CLEARED`."

    Design: Corner/state_machines/clear_conflict_screen_moves_matter_to_cleared
    """
    matter, _, _ = create_matter_in_intake()
    cc = validate_success(
        api.create_conflict_check(matter["id"],
                                  create_conflict_check_payload("Totally Unrelated Party"), CLERK),
        expected_status=201)
    assert cc["result"] == "CLEAR"
    assert cc["matched_client_id"] is None
    m = validate_success(api.get_matter(matter["id"], CLERK))
    assert m["status"] == "CONFLICT_CLEARED"


def test_matter_compound_bubble_up_client_active(api):
    """PRD §3.3: "Opening has cascading effects: if the owning client is still
    `PROSPECT`, its `status` is promoted to `ACTIVE`".

    Design: Corner/state_machines/matter_compound_bubble_up_client_active
    """
    matter, client_id, _ = create_open_matter(matter_rate_cents=50000)
    client = validate_success(api.get_client(client_id, CLERK))
    assert client["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Section 4 — Validations (conflict gate / state) (queue B)
# ---------------------------------------------------------------------------
def test_conflict_blocks_time_capture(api):
    """PRD §3.2: "no time or expense may be captured against it, unless its
    latest conflict check has a `result` of either `CLEAR` or `WAIVED`; ... any of
    these three operations — opening the matter, capturing a time entry, or
    capturing an expense entry — is rejected with `ERR_CONFLICT_NOT_CLEARED`
    (HTTP 409) when the gate is not satisfied."

    Design: Corner/validations/conflict_blocks_time_capture
    """
    ensure_billing_codes()
    matter, cc, subject_id, adverse_id, tk_id = create_flagged_matter(
        subject_name="Acme Corp", adverse_name="Rival Inc")
    payload = create_time_entry_payload(matter["id"], tk_id, minutes=60)
    # PRD §3.2 names ERR_CONFLICT_NOT_CLEARED for capturing time against a
    # FLAGGED/CONFLICT_BLOCKED matter; PRD §3.3 ("capture becomes legal only once the
    # matter is OPEN") + the §2.10 precedence (ERR_INVALID_STATE before
    # ERR_CONFLICT_NOT_CLEARED) also admit a faithful ERR_INVALID_STATE reading.
    validate_error_is_one_of(
        api.create_time_entry(payload, ATT),
        [ApiErrorId.ERR_CONFLICT_NOT_CLEARED, ApiErrorId.ERR_INVALID_STATE])


def test_time_capture_on_non_open_matter_invalid_state(api):
    """PRD §3.3: "Capture of time and expense becomes legal only once the matter
    is `OPEN` — an attempt to capture against a matter in any other state is an
    invalid-state rejection (`ERR_INVALID_STATE`, HTTP 409)."

    Design: Corner/validations/time_capture_on_non_open_matter_invalid_state
    """
    ensure_billing_codes()
    # CONFLICT_CLEARED but not opened.
    matter, client_id, tk_id = create_matter_conflict_cleared(matter_rate_cents=50000)
    assert matter["status"] == "CONFLICT_CLEARED"
    payload = create_time_entry_payload(matter["id"], tk_id, minutes=60)
    validate_error(api.create_time_entry(payload, ATT), ApiErrorId.ERR_INVALID_STATE)

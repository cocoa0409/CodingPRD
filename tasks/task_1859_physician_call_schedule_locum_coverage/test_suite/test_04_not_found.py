"""Existence checks: every unknown id surfaces its own 404 error, and
body-referenced ids are validated in declared input order."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]


def test_get_nonexistent_physician_returns_not_found(api):
    """PRD §2.11: "Existence — path identifiers are validated left-to-right, then
    body-referenced identifiers in their declared input order (so a
    manual-assignment request validates `slot_id` before `physician_id`); each
    unknown id surfaces its own 404: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_PHYSICIAN_NOT_FOUND`, ..."

    Design: Corner/errors/get_nonexistent_physician_returns_not_found
    """
    resp = api.get_physician(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PHYSICIAN_NOT_FOUND, 404)


def test_get_nonexistent_slot_returns_not_found(api):
    """PRD §2.11: "each unknown id surfaces its own 404: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_PHYSICIAN_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, ..."

    Design: Corner/errors/get_nonexistent_slot_returns_not_found
    """
    resp = api.get_slot(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_SLOT_NOT_FOUND, 404)


def test_get_nonexistent_assignment_returns_not_found(api):
    """PRD §2.11: "each unknown id surfaces its own 404: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_PHYSICIAN_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, ..."

    Design: Corner/errors/get_nonexistent_assignment_returns_not_found
    """
    resp = api.get_assignment(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND, 404)


def test_get_nonexistent_swap_returns_not_found(api):
    """PRD §2.11: "each unknown id surfaces its own 404: `ERR_PROGRAM_NOT_FOUND`,
    ..., `ERR_SWAP_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, ..."

    Design: Corner/errors/get_nonexistent_swap_returns_not_found
    """
    resp = api.get_swap(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_SWAP_NOT_FOUND, 404)


def test_get_nonexistent_window_returns_not_found(api):
    """PRD §2.11: "each unknown id surfaces its own 404: `ERR_PROGRAM_NOT_FOUND`,
    ..., `ERR_WINDOW_NOT_FOUND`, `ERR_GAP_NOT_FOUND`, ..."

    Design: Corner/errors/get_nonexistent_window_returns_not_found
    """
    resp = api.get_window(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_FOUND, 404)


def test_get_nonexistent_gap_returns_not_found(api):
    """PRD §2.11: "each unknown id surfaces its own 404: `ERR_PROGRAM_NOT_FOUND`,
    ..., `ERR_GAP_NOT_FOUND`, `ERR_REQUISITION_NOT_FOUND`, ..."

    Design: Corner/errors/get_nonexistent_gap_returns_not_found
    """
    resp = api.get_gap(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_GAP_NOT_FOUND, 404)


def test_get_nonexistent_requisition_returns_not_found(api):
    """PRD §2.11: "each unknown id surfaces its own 404: `ERR_PROGRAM_NOT_FOUND`,
    ..., `ERR_REQUISITION_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, ..."

    Design: Corner/errors/get_nonexistent_requisition_returns_not_found
    """
    resp = api.get_requisition(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_REQUISITION_NOT_FOUND, 404)


def test_get_nonexistent_case_returns_not_found(api):
    """PRD §2.11: "each unknown id surfaces its own 404: `ERR_PROGRAM_NOT_FOUND`,
    ..., `ERR_CASE_NOT_FOUND`, or `ERR_PAY_ENTRY_NOT_FOUND`."

    Design: Corner/errors/get_nonexistent_case_returns_not_found
    """
    resp = api.get_case(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND, 404)


def test_get_nonexistent_pay_entry_returns_not_found(api):
    """PRD §2.11: "each unknown id surfaces its own 404: `ERR_PROGRAM_NOT_FOUND`,
    ..., `ERR_CASE_NOT_FOUND`, or `ERR_PAY_ENTRY_NOT_FOUND`."

    Design: Corner/errors/get_nonexistent_pay_entry_returns_not_found
    """
    resp = api.get_pay_entry(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PAY_ENTRY_NOT_FOUND, 404)


def test_create_assignment_unknown_ids_returns_slot_not_found_first(api):
    """PRD §2.11: "Existence — path identifiers are validated left-to-right, then
    body-referenced identifiers in their declared input order (so a
    manual-assignment request validates `slot_id` before `physician_id`)".

    Design: Corner/validations/create_assignment_unknown_ids_returns_slot_not_found_first
    """
    resp = api.create_assignment(
        {
            "slot_id": "00000000-0000-0000-0000-000000000000",
            "physician_id": "11111111-1111-1111-1111-111111111111",
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_SLOT_NOT_FOUND, 404)

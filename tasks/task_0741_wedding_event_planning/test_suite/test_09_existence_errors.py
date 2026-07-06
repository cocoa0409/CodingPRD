"""Existence-resolution (404) corners across the resource collections.

All queue B not-found corners. Each cites the PRD existence-gate sentence that
enumerates the per-resource not-found error identifiers.
"""
from test_helpers import (
    validate_error,
    ApiErrorId,
    PLANNER,
    NON_EXISTENT_UUID,
    create_event,
)


def test_get_event_not_found(api):
    """PRD §2.7: "The existence gate resolves identifiers left to right in the order they
    appear — path identifier first, then body identifiers in their listed order — and
    reports the first one that does not resolve using the not-found error for that
    resource type: `ERR_EVENT_NOT_FOUND` for an event, `ERR_CONTRACT_NOT_FOUND` for a
    contract, `ERR_VENDOR_NOT_FOUND` for a vendor, `ERR_COI_NOT_FOUND` for a certificate
    of insurance, `ERR_BOOKING_NOT_FOUND` for a vendor booking, `ERR_PAYMENT_NOT_FOUND`
    for a vendor payment, `ERR_TIMELINE_BLOCK_NOT_FOUND` for a timeline block,
    `ERR_GUEST_NOT_FOUND` for a guest, `ERR_TABLE_NOT_FOUND` for a table,
    `ERR_SEAT_ASSIGNMENT_NOT_FOUND` for a seat assignment, `ERR_STAFF_MEMBER_NOT_FOUND`
    for a staff member, and `ERR_STAFF_ASSIGNMENT_NOT_FOUND` for a staff assignment."

    Design: Corner/entities/get_event_not_found_returns_404
    """
    validate_error(api.get_event(NON_EXISTENT_UUID, PLANNER), ApiErrorId.ERR_EVENT_NOT_FOUND.value)


def test_get_contract_not_found(api):
    """PRD §2.7: "The existence gate resolves identifiers left to right in the order they
    appear — path identifier first, then body identifiers in their listed order — and
    reports the first one that does not resolve using the not-found error for that
    resource type: `ERR_EVENT_NOT_FOUND` for an event, `ERR_CONTRACT_NOT_FOUND` for a
    contract, `ERR_VENDOR_NOT_FOUND` for a vendor, `ERR_COI_NOT_FOUND` for a certificate
    of insurance, `ERR_BOOKING_NOT_FOUND` for a vendor booking, `ERR_PAYMENT_NOT_FOUND`
    for a vendor payment, `ERR_TIMELINE_BLOCK_NOT_FOUND` for a timeline block,
    `ERR_GUEST_NOT_FOUND` for a guest, `ERR_TABLE_NOT_FOUND` for a table,
    `ERR_SEAT_ASSIGNMENT_NOT_FOUND` for a seat assignment, `ERR_STAFF_MEMBER_NOT_FOUND`
    for a staff member, and `ERR_STAFF_ASSIGNMENT_NOT_FOUND` for a staff assignment."

    Design: Corner/errors/get_contract_not_found_returns_404
    """
    validate_error(api.get_contract(NON_EXISTENT_UUID, PLANNER), ApiErrorId.ERR_CONTRACT_NOT_FOUND.value)


def test_get_vendor_booking_not_found(api):
    """PRD §2.7: "The existence gate resolves identifiers left to right in the order they
    appear — path identifier first, then body identifiers in their listed order — and
    reports the first one that does not resolve using the not-found error for that
    resource type: `ERR_EVENT_NOT_FOUND` for an event, `ERR_CONTRACT_NOT_FOUND` for a
    contract, `ERR_VENDOR_NOT_FOUND` for a vendor, `ERR_COI_NOT_FOUND` for a certificate
    of insurance, `ERR_BOOKING_NOT_FOUND` for a vendor booking, `ERR_PAYMENT_NOT_FOUND`
    for a vendor payment, `ERR_TIMELINE_BLOCK_NOT_FOUND` for a timeline block,
    `ERR_GUEST_NOT_FOUND` for a guest, `ERR_TABLE_NOT_FOUND` for a table,
    `ERR_SEAT_ASSIGNMENT_NOT_FOUND` for a seat assignment, `ERR_STAFF_MEMBER_NOT_FOUND`
    for a staff member, and `ERR_STAFF_ASSIGNMENT_NOT_FOUND` for a staff assignment."

    Design: Corner/errors/get_booking_not_found_returns_404
    """
    validate_error(
        api.get_vendor_booking(NON_EXISTENT_UUID, PLANNER), ApiErrorId.ERR_BOOKING_NOT_FOUND.value
    )


def test_get_guest_not_found(api):
    """PRD §2.7: "The existence gate resolves identifiers left to right in the order they
    appear — path identifier first, then body identifiers in their listed order — and
    reports the first one that does not resolve using the not-found error for that
    resource type: `ERR_EVENT_NOT_FOUND` for an event, `ERR_CONTRACT_NOT_FOUND` for a
    contract, `ERR_VENDOR_NOT_FOUND` for a vendor, `ERR_COI_NOT_FOUND` for a certificate
    of insurance, `ERR_BOOKING_NOT_FOUND` for a vendor booking, `ERR_PAYMENT_NOT_FOUND`
    for a vendor payment, `ERR_TIMELINE_BLOCK_NOT_FOUND` for a timeline block,
    `ERR_GUEST_NOT_FOUND` for a guest, `ERR_TABLE_NOT_FOUND` for a table,
    `ERR_SEAT_ASSIGNMENT_NOT_FOUND` for a seat assignment, `ERR_STAFF_MEMBER_NOT_FOUND`
    for a staff member, and `ERR_STAFF_ASSIGNMENT_NOT_FOUND` for a staff assignment."

    Design: Corner/errors/get_guest_not_found_returns_404
    """
    validate_error(api.get_guest(NON_EXISTENT_UUID, PLANNER), ApiErrorId.ERR_GUEST_NOT_FOUND.value)


def test_get_table_not_found(api):
    """PRD §2.7: "The existence gate resolves identifiers left to right in the order they
    appear — path identifier first, then body identifiers in their listed order — and
    reports the first one that does not resolve using the not-found error for that
    resource type: `ERR_EVENT_NOT_FOUND` for an event, `ERR_CONTRACT_NOT_FOUND` for a
    contract, `ERR_VENDOR_NOT_FOUND` for a vendor, `ERR_COI_NOT_FOUND` for a certificate
    of insurance, `ERR_BOOKING_NOT_FOUND` for a vendor booking, `ERR_PAYMENT_NOT_FOUND`
    for a vendor payment, `ERR_TIMELINE_BLOCK_NOT_FOUND` for a timeline block,
    `ERR_GUEST_NOT_FOUND` for a guest, `ERR_TABLE_NOT_FOUND` for a table,
    `ERR_SEAT_ASSIGNMENT_NOT_FOUND` for a seat assignment, `ERR_STAFF_MEMBER_NOT_FOUND`
    for a staff member, and `ERR_STAFF_ASSIGNMENT_NOT_FOUND` for a staff assignment."

    Design: Corner/errors/get_table_not_found_returns_404
    """
    validate_error(api.get_table(NON_EXISTENT_UUID, PLANNER), ApiErrorId.ERR_TABLE_NOT_FOUND.value)


def test_get_timeline_block_not_found(api):
    """PRD §2.7: "The existence gate resolves identifiers left to right in the order they
    appear — path identifier first, then body identifiers in their listed order — and
    reports the first one that does not resolve using the not-found error for that
    resource type: `ERR_EVENT_NOT_FOUND` for an event, `ERR_CONTRACT_NOT_FOUND` for a
    contract, `ERR_VENDOR_NOT_FOUND` for a vendor, `ERR_COI_NOT_FOUND` for a certificate
    of insurance, `ERR_BOOKING_NOT_FOUND` for a vendor booking, `ERR_PAYMENT_NOT_FOUND`
    for a vendor payment, `ERR_TIMELINE_BLOCK_NOT_FOUND` for a timeline block,
    `ERR_GUEST_NOT_FOUND` for a guest, `ERR_TABLE_NOT_FOUND` for a table,
    `ERR_SEAT_ASSIGNMENT_NOT_FOUND` for a seat assignment, `ERR_STAFF_MEMBER_NOT_FOUND`
    for a staff member, and `ERR_STAFF_ASSIGNMENT_NOT_FOUND` for a staff assignment."

    Design: Corner/errors/get_timeline_block_not_found_returns_404
    """
    validate_error(
        api.get_timeline_block(NON_EXISTENT_UUID, PLANNER),
        ApiErrorId.ERR_TIMELINE_BLOCK_NOT_FOUND.value,
    )


def test_get_staff_assignment_not_found(api):
    """PRD §2.7: "The existence gate resolves identifiers left to right in the order they
    appear — path identifier first, then body identifiers in their listed order — and
    reports the first one that does not resolve using the not-found error for that
    resource type: `ERR_EVENT_NOT_FOUND` for an event, `ERR_CONTRACT_NOT_FOUND` for a
    contract, `ERR_VENDOR_NOT_FOUND` for a vendor, `ERR_COI_NOT_FOUND` for a certificate
    of insurance, `ERR_BOOKING_NOT_FOUND` for a vendor booking, `ERR_PAYMENT_NOT_FOUND`
    for a vendor payment, `ERR_TIMELINE_BLOCK_NOT_FOUND` for a timeline block,
    `ERR_GUEST_NOT_FOUND` for a guest, `ERR_TABLE_NOT_FOUND` for a table,
    `ERR_SEAT_ASSIGNMENT_NOT_FOUND` for a seat assignment, `ERR_STAFF_MEMBER_NOT_FOUND`
    for a staff member, and `ERR_STAFF_ASSIGNMENT_NOT_FOUND` for a staff assignment."

    Design: Corner/errors/get_staff_assignment_not_found_returns_404
    """
    validate_error(
        api.get_staff_assignment(NON_EXISTENT_UUID, PLANNER),
        ApiErrorId.ERR_STAFF_ASSIGNMENT_NOT_FOUND.value,
    )


def test_verify_coi_not_found(api):
    """PRD §2.7: "The existence gate resolves identifiers left to right in the order they
    appear — path identifier first, then body identifiers in their listed order — and
    reports the first one that does not resolve using the not-found error for that
    resource type: `ERR_EVENT_NOT_FOUND` for an event, `ERR_CONTRACT_NOT_FOUND` for a
    contract, `ERR_VENDOR_NOT_FOUND` for a vendor, `ERR_COI_NOT_FOUND` for a certificate
    of insurance, `ERR_BOOKING_NOT_FOUND` for a vendor booking, `ERR_PAYMENT_NOT_FOUND`
    for a vendor payment, `ERR_TIMELINE_BLOCK_NOT_FOUND` for a timeline block,
    `ERR_GUEST_NOT_FOUND` for a guest, `ERR_TABLE_NOT_FOUND` for a table,
    `ERR_SEAT_ASSIGNMENT_NOT_FOUND` for a seat assignment, `ERR_STAFF_MEMBER_NOT_FOUND`
    for a staff member, and `ERR_STAFF_ASSIGNMENT_NOT_FOUND` for a staff assignment."

    Design: Corner/errors/verify_coi_not_found_returns_404
    """
    validate_error(api.verify_coi(NON_EXISTENT_UUID, PLANNER), ApiErrorId.ERR_COI_NOT_FOUND.value)


def test_coi_create_vendor_not_found(api):
    """PRD §2.7: "The existence gate resolves identifiers left to right in the order they
    appear — path identifier first, then body identifiers in their listed order — and
    reports the first one that does not resolve using the not-found error for that
    resource type: `ERR_EVENT_NOT_FOUND` for an event, `ERR_CONTRACT_NOT_FOUND` for a
    contract, `ERR_VENDOR_NOT_FOUND` for a vendor, `ERR_COI_NOT_FOUND` for a certificate
    of insurance, `ERR_BOOKING_NOT_FOUND` for a vendor booking, `ERR_PAYMENT_NOT_FOUND`
    for a vendor payment, `ERR_TIMELINE_BLOCK_NOT_FOUND` for a timeline block,
    `ERR_GUEST_NOT_FOUND` for a guest, `ERR_TABLE_NOT_FOUND` for a table,
    `ERR_SEAT_ASSIGNMENT_NOT_FOUND` for a seat assignment, `ERR_STAFF_MEMBER_NOT_FOUND`
    for a staff member, and `ERR_STAFF_ASSIGNMENT_NOT_FOUND` for a staff assignment."

    Design: Corner/errors/coi_create_vendor_not_found_returns_404
    """
    validate_error(
        api.create_coi(
            {
                "vendor_id": NON_EXISTENT_UUID,
                "policy_number": "POL-X",
                "coverage_amount_cents": 1_000_000,
                "coverage_expiry_date": "2027-01-01T00:00:00Z",
            },
            PLANNER,
        ),
        ApiErrorId.ERR_VENDOR_NOT_FOUND.value,
    )


def test_staff_assignment_staff_member_not_found(api):
    """PRD §2.7: "The existence gate resolves identifiers left to right in the order they
    appear — path identifier first, then body identifiers in their listed order — and
    reports the first one that does not resolve using the not-found error for that
    resource type: `ERR_EVENT_NOT_FOUND` for an event, `ERR_CONTRACT_NOT_FOUND` for a
    contract, `ERR_VENDOR_NOT_FOUND` for a vendor, `ERR_COI_NOT_FOUND` for a certificate
    of insurance, `ERR_BOOKING_NOT_FOUND` for a vendor booking, `ERR_PAYMENT_NOT_FOUND`
    for a vendor payment, `ERR_TIMELINE_BLOCK_NOT_FOUND` for a timeline block,
    `ERR_GUEST_NOT_FOUND` for a guest, `ERR_TABLE_NOT_FOUND` for a table,
    `ERR_SEAT_ASSIGNMENT_NOT_FOUND` for a seat assignment, `ERR_STAFF_MEMBER_NOT_FOUND`
    for a staff member, and `ERR_STAFF_ASSIGNMENT_NOT_FOUND` for a staff assignment."

    The event_id resolves; the staff_member_id does not.

    Design: Corner/errors/staff_assignment_staff_member_not_found_returns_404
    """
    event = create_event(package_type="PARTIAL", total_budget_cents=3_000_000)
    validate_error(
        api.create_staff_assignment(
            {
                "event_id": event["id"],
                "staff_member_id": NON_EXISTENT_UUID,
                "shift_start_offset_min": 600,
                "shift_end_offset_min": 720,
            },
            PLANNER,
        ),
        ApiErrorId.ERR_STAFF_MEMBER_NOT_FOUND.value,
    )


def test_delete_seat_assignment_not_found(api):
    """PRD §2.7: "The existence gate resolves identifiers left to right in the order they
    appear — path identifier first, then body identifiers in their listed order — and
    reports the first one that does not resolve using the not-found error for that
    resource type: `ERR_EVENT_NOT_FOUND` for an event, `ERR_CONTRACT_NOT_FOUND` for a
    contract, `ERR_VENDOR_NOT_FOUND` for a vendor, `ERR_COI_NOT_FOUND` for a certificate
    of insurance, `ERR_BOOKING_NOT_FOUND` for a vendor booking, `ERR_PAYMENT_NOT_FOUND`
    for a vendor payment, `ERR_TIMELINE_BLOCK_NOT_FOUND` for a timeline block,
    `ERR_GUEST_NOT_FOUND` for a guest, `ERR_TABLE_NOT_FOUND` for a table,
    `ERR_SEAT_ASSIGNMENT_NOT_FOUND` for a seat assignment, `ERR_STAFF_MEMBER_NOT_FOUND`
    for a staff member, and `ERR_STAFF_ASSIGNMENT_NOT_FOUND` for a staff assignment."

    Design: Corner/errors/delete_seat_assignment_not_found_returns_404
    """
    validate_error(
        api.delete_seat_assignment(NON_EXISTENT_UUID, PLANNER),
        ApiErrorId.ERR_SEAT_ASSIGNMENT_NOT_FOUND.value,
    )


def test_pay_payment_not_found(api):
    """PRD §2.7: "The existence gate resolves identifiers left to right in the order they
    appear — path identifier first, then body identifiers in their listed order — and
    reports the first one that does not resolve using the not-found error for that
    resource type: `ERR_EVENT_NOT_FOUND` for an event, `ERR_CONTRACT_NOT_FOUND` for a
    contract, `ERR_VENDOR_NOT_FOUND` for a vendor, `ERR_COI_NOT_FOUND` for a certificate
    of insurance, `ERR_BOOKING_NOT_FOUND` for a vendor booking, `ERR_PAYMENT_NOT_FOUND`
    for a vendor payment, `ERR_TIMELINE_BLOCK_NOT_FOUND` for a timeline block,
    `ERR_GUEST_NOT_FOUND` for a guest, `ERR_TABLE_NOT_FOUND` for a table,
    `ERR_SEAT_ASSIGNMENT_NOT_FOUND` for a seat assignment, `ERR_STAFF_MEMBER_NOT_FOUND`
    for a staff member, and `ERR_STAFF_ASSIGNMENT_NOT_FOUND` for a staff assignment."

    Design: Corner/errors/pay_payment_not_found_returns_404
    """
    validate_error(
        api.pay_vendor_payment(NON_EXISTENT_UUID, PLANNER), ApiErrorId.ERR_PAYMENT_NOT_FOUND.value
    )

"""Accreditation: clock-derived status boundaries, the expiry cascade, and the
ComplianceOfficer lifecycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_site_day,
    book_appointment,
    create_accreditation,
    create_accreditation_payload,
    create_contract,
    create_facility,
    create_route_plan,
    create_unit,
    get_day_statement,
    get_success_data,
    make_facility_coordinator_headers,
    set_clock,
    setup_bookable_day,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["operations_director_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_accreditation_expiring_soon_30_day_boundary(api):
    """PRD §3.7: "Status is clock-derived rather than stored opinion: a record
    is `EXPIRED` when `expires_on` is before the logical clock date,
    `EXPIRING_SOON` when the clock date is between zero and thirty days before
    expiry inclusive, and `ACTIVE` when expiry is more than thirty days out; a
    new record's initial status is derived from the clock at creation by the
    same rule."

    Design: Corner/calculations/accreditation_expiring_soon_30_day_boundary
    """
    set_clock()  # 2026-08-01
    unit1 = create_unit(unit_code="MIU-01")
    unit2 = create_unit(unit_code="MIU-02")

    # Exactly 30 days out -> inside the inclusive warning window.
    acc1 = create_accreditation(unit1["id"], expires_on="2026-08-31")
    assert acc1["status"] == "EXPIRING_SOON", (
        f"Expiry exactly 30 days out must be EXPIRING_SOON, got {acc1['status']}"
    )
    # 31 days out -> still fully ACTIVE.
    acc2 = create_accreditation(unit2["id"], expires_on="2026-09-01")
    assert acc2["status"] == "ACTIVE", (
        f"Expiry 31 days out must be ACTIVE, got {acc2['status']}"
    )


def test_accreditation_expiry_cascade_day_cancelled(api):
    """PRD §3.7: "When a governing record flips to `EXPIRED` under a clock
    advance, the cascade is automatic and punitive to the operator, not the
    facility: every `SCHEDULED` site day for that unit whose `service_date` is
    after the clock date is cancelled with `cancel_reason`
    `ACCREDITATION_EXPIRED`, its `REQUESTED` and `CONFIRMED` appointments are
    cancelled with `cancel_reason` `DAY_CANCELLED`, and a zero-amount
    `PROVISIONAL` statement is created for each such day."

    Design: Difficulty/transitive_cascade/accreditation_expiry_cascade_cancels_future_days
    """
    ids = _setup_future_day_with_expiring_accreditation(api)

    set_clock("2026-08-16T00:00:00Z")  # one day past expiry 2026-08-15

    acc = validate_success(api.get_accreditation(ids["acc_id"], COMPLIANCE))
    assert acc["status"] == "EXPIRED", f"Hop 1: record must be EXPIRED, got {acc['status']}"

    day = validate_success(api.get_site_day(ids["day_id"], OPS))
    assert day["status"] == "CANCELLED", (
        f"Hop 2: future SCHEDULED day must be CANCELLED, got {day['status']}"
    )
    assert day["cancel_reason"] == "ACCREDITATION_EXPIRED"


def test_accreditation_expiry_cascade_appointment_and_statement(api):
    """PRD §3.7: "When a governing record flips to `EXPIRED` under a clock
    advance, the cascade is automatic and punitive to the operator, not the
    facility: every `SCHEDULED` site day for that unit whose `service_date` is
    after the clock date is cancelled with `cancel_reason`
    `ACCREDITATION_EXPIRED`, its `REQUESTED` and `CONFIRMED` appointments are
    cancelled with `cancel_reason` `DAY_CANCELLED`, and a zero-amount
    `PROVISIONAL` statement is created for each such day."

    Design: Difficulty/transitive_cascade/accreditation_expiry_cascade_cancels_future_days
    """
    ids = _setup_future_day_with_expiring_accreditation(api)

    set_clock("2026-08-16T00:00:00Z")

    appt = validate_success(api.get_appointment(ids["appt_id"], OPS))
    assert appt["status"] == "CANCELLED", (
        f"Hop 3: appointment must be CANCELLED, got {appt['status']}"
    )
    assert appt["cancel_reason"] == "DAY_CANCELLED"

    stmt = get_day_statement(ids["day_id"])
    assert stmt["status"] == "PROVISIONAL"
    assert stmt["provisional_amount_cents"] == 0, (
        f"Provider-caused cancellation must create a zero-amount statement, "
        f"got {stmt['provisional_amount_cents']}"
    )


def _setup_future_day_with_expiring_accreditation(api) -> dict:
    """CT unit whose accreditation expires 2026-08-15; a SCHEDULED day on
    2026-08-20 with one REQUESTED appointment; clock still 2026-08-01."""
    set_clock()
    facility = create_facility()
    unit = create_unit()
    # 14 days out at creation -> EXPIRING_SOON, still valid for site-day create.
    acc = create_accreditation(unit["id"], expires_on="2026-08-15")
    contract = create_contract(facility["id"])
    plan = create_route_plan(unit["id"], week_start_date="2026-08-17")
    day = add_site_day(plan["id"], facility["id"], contract["id"], "2026-08-20")
    appt = book_appointment(day["id"], facility["id"], "P-001")
    return {"acc_id": acc["id"], "day_id": day["id"], "appt_id": appt["id"]}


def test_compliance_officer_manages_accreditation_lifecycle(api):
    """PRD §3.7: "A record may also be manually suspended — an audit finding —
    moving `ACTIVE` or `EXPIRING_SOON` to `SUSPENDED` with the supplied
    `reason` stored as `suspend_reason` (`ERR_INVALID_STATE` from any other
    state)".
    PRD §4: the accreditation create and suspend rows name ComplianceOfficer as
    the authorized role.

    Design: Corner/rbac/compliance_officer_manages_accreditation_lifecycle
    """
    set_clock()
    unit = create_unit()
    resp = api.create_accreditation(
        create_accreditation_payload(unit["id"], accrediting_body="IAC"), COMPLIANCE
    )
    acc = validate_success(resp, 201)
    assert acc["status"] == "ACTIVE", (
        f"Expiry 2027-01-01 is more than thirty days out, got {acc['status']}"
    )

    suspended = validate_success(
        api.suspend_accreditation(acc["id"], {"reason": "audit finding 12"}, COMPLIANCE)
    )
    assert suspended["status"] == "SUSPENDED", (
        f"Suspend must land SUSPENDED, got {suspended['status']}"
    )

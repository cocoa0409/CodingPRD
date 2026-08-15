"""Access control (auth context, RBAC, ownership, segregation of duties) and
the employee registry (required fields, badge uniqueness, enum validation,
pagination, termination)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_employee,
    assert_instant_equals,
    create_employee_payload,
    create_lot_payload,
    create_program,
    create_employee,
    create_lot,
    create_violation_payload,
    issue_violations,
    make_appeals_officer_headers,
    make_employee_headers,
    make_enforcement_officer_headers,
    set_logical_clock,
    setup_active_permit,
    setup_offered_permit,
    setup_program_lot_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["parking_admin_headers"]
PAYROLL = TEST_USERS["payroll_admin_headers"]
DISPATCHER = TEST_USERS["shuttle_dispatcher_headers"]


# ─── Authentication context ───────────────────────────────────────────

def test_missing_auth_headers_rejected(api):
    """PRD section 2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring their operational
    capacity. A request with a missing header or an unrecognized role is rejected
    with `ERR_MISSING_OR_INVALID_AUTH_CONTEXT` (HTTP 400)."

    Design: Corner/errors/missing_auth_header_unauthenticated
    """
    program = create_program(name="P-ER1")

    # Sent without X-User-ID / X-User-Role headers at all.
    res = api.create_lot(
        create_lot_payload(program["id"], code="CORE-A", tier="CORE", capacity=5),
        headers=None,
    )
    validate_error(res, "ERR_MISSING_OR_INVALID_AUTH_CONTEXT", expected_status=400)

    data, meta = validate_paginated(
        api.list_lots(ADMIN, params={"program_id": program["id"]})
    )
    assert meta["total_count"] == 0, "rejected request must not persist a lot"


# ─── RBAC exclusive-denial ────────────────────────────────────────────

def test_employee_cannot_create_lot(api):
    """PRD section 2.1: "A request whose role is not authorized for the target
    endpoint — or, on event-style endpoints, for the particular event verb
    requested — is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD section 4: "| POST | `/parking/lots` | Create a parking lot | ParkingAdmin |"

    Design: Corner/rbac/employee_cannot_create_lot
    """
    program = create_program(name="P-RB1")

    res = api.create_lot(
        create_lot_payload(program["id"], code="CORE-A", tier="CORE", capacity=5),
        headers=make_employee_headers("emp-outsider"),
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_payroll_admin_cannot_issue_violation(api):
    """PRD section 4: "| POST | `/parking/violations` | Issue a violation against
    a permit | EnforcementOfficer |"
    PRD section 2.8: the fixed order evaluates "2. **Role authorization.**" before
    "4. **Existence.**" — "When several checks could reject the same request, the
    server evaluates them in a fixed order, and an earlier failure masks all later
    ones."

    Design: Corner/rbac/payroll_admin_cannot_issue_violation
    """
    create_program(name="P-RB2")

    # The cited permit does not even exist: the role gate (step 2) must fire
    # before the existence check (step 4), so 403, not 404.
    res = api.create_violation(
        create_violation_payload(NON_EXISTENT_UUID, "WRONG_LOT"),
        headers=PAYROLL,
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_enforcement_officer_cannot_decide_appeal(api):
    """PRD section 2.8: "The acting role is listed for the endpoint; on
    event-style endpoints, event-verb restrictions apply at the same step —
    permit `SUSPEND`, `REINSTATE`, and `REVOKE` are `ParkingAdmin`-only events,
    `APPEAL` is `Employee`-only, and `DECIDE_APPEAL` is `AppealsOfficer`-only
    (`ERR_FORBIDDEN_ROLE`)."

    Design: Corner/rbac/enforcement_officer_cannot_decide_appeal
    """
    bundle = setup_active_permit(program_overrides={"monthly_subsidy_pool_cents": 0})
    set_logical_clock("2026-08-05T10:00:00Z")
    violation = issue_violations(bundle["permit"], "WRONG_LOT", count=1)[0]
    appealed = validate_success(
        api.violation_event(
            violation["id"], {"event_type": "APPEAL"},
            make_employee_headers(bundle["employee"]["id"]),
        ),
        200,
    )
    assert appealed["appeal_status"] == "APPEALED"

    res = api.violation_event(
        violation["id"], {"event_type": "DECIDE_APPEAL", "decision": "UPHELD"},
        make_enforcement_officer_headers("officer-1"),
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)

    after = validate_success(api.get_violation(violation["id"], ADMIN), 200)
    assert after["appeal_status"] == "APPEALED", "rejected decision must not land"


def test_employee_cannot_act_on_others_permit(api):
    """PRD section 2.8: "Immediately after the path resource loads — and before
    any state check — Employee path-ownership is enforced on permit events,
    renewal creation, and violation events: the loaded resource's owning
    `employee_id` must equal the caller's `X-User-ID` (`ERR_NOT_RESOURCE_OWNER`)."

    Design: Corner/rbac/employee_cannot_act_on_others_permit
    """
    bundle = setup_offered_permit(with_cycle=False, lot_overrides={"capacity": 2})
    other = create_employee(bundle["program"]["id"], badge_number="B002")

    res = api.permit_event(
        bundle["permit"]["id"], {"event_type": "DECLINE"},
        make_employee_headers(other["id"]),
    )
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)

    permit = validate_success(api.get_permit(bundle["permit"]["id"], ADMIN), 200)
    assert permit["status"] == "OFFERED", "rejected event must leave the permit untouched"


def test_segregation_issuer_cannot_decide_own_appeal(api):
    """PRD section 3.7: "An `AppealsOfficer` then decides with a `decision` of
    `UPHELD` or `DISMISSED`; segregation of duties forbids the decider's
    `X-User-ID` from matching the violation's `issued_by`, and a match is
    rejected with `ERR_SEGREGATION_OF_DUTIES`. An `UPHELD` decision changes
    nothing further."

    Design: Corner/rbac/segregation_issuer_cannot_decide_own_appeal
    """
    bundle = setup_active_permit(program_overrides={"monthly_subsidy_pool_cents": 0})
    set_logical_clock("2026-08-05T10:00:00Z")
    violation = issue_violations(bundle["permit"], "WRONG_LOT", count=1,
                                 officer_id="officer-1")[0]
    validate_success(
        api.violation_event(
            violation["id"], {"event_type": "APPEAL"},
            make_employee_headers(bundle["employee"]["id"]),
        ),
        200,
    )

    # An AppealsOfficer carrying the issuer's operator id is refused.
    res = api.violation_event(
        violation["id"], {"event_type": "DECIDE_APPEAL", "decision": "UPHELD"},
        make_appeals_officer_headers("officer-1"),
    )
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=409)

    # A different AppealsOfficer id decides successfully.
    decided = validate_success(
        api.violation_event(
            violation["id"], {"event_type": "DECIDE_APPEAL", "decision": "UPHELD"},
            make_appeals_officer_headers("officer-2"),
        ),
        200,
    )
    assert decided["appeal_status"] == "UPHELD"
    assert decided["payment_status"] == "UNPAID", "UPHELD keeps the fine collectible"


# ─── Employee registry ────────────────────────────────────────────────

def test_employee_creation_missing_badge_number(api):
    """PRD section 3.1: "Registering an employee takes the `program_id` of the
    program they park under, a `badge_number` that must be unique within that
    program across all employees (a conflict is rejected with
    `ERR_BADGE_NUMBER_TAKEN`), a `full_name`, an `employer_code` identifying the
    tenant or airline, a `shift_pattern` of `DAY`, `NIGHT`, `ROTATING`, or
    `SPLIT`, and a `hire_date` as an ISO calendar date."
    PRD section 2.8: "`ERR_INVALID_REQUEST` at HTTP 400, the last of which also
    covers malformed JSON, missing required fields, invalid enum values, bad date
    or datetime formats, sign-rule violations on manual adjustments, and lot-code
    conflicts"

    Design: Corner/entities/employee_creation_missing_required_field
    """
    program = create_program(name="P-E1")

    payload = create_employee_payload(program["id"], full_name="No Badge")
    del payload["badge_number"]
    res = api.create_employee(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

    _data, meta = validate_paginated(
        api.list_employees(ADMIN, params={"program_id": program["id"]})
    )
    assert meta["total_count"] == 0, "rejected create must not persist an employee"


def test_badge_number_unique_per_program_only(api):
    """PRD section 3.1: "Registering an employee takes the `program_id` of the
    program they park under, a `badge_number` that must be unique within that
    program across all employees (a conflict is rejected with
    `ERR_BADGE_NUMBER_TAKEN`), a `full_name`, an `employer_code` identifying the
    tenant or airline, a `shift_pattern` of `DAY`, `NIGHT`, `ROTATING`, or
    `SPLIT`, and a `hire_date` as an ISO calendar date."

    Design: Corner/entities/badge_number_unique_per_program_only
    """
    p1 = create_program(name="P1")
    p2 = create_program(name="P2")
    create_employee(p1["id"], badge_number="B100", shift_pattern="DAY")

    dup = api.create_employee(
        create_employee_payload(p1["id"], badge_number="B100", full_name="Dup",
                                shift_pattern="NIGHT", hire_date="2024-02-01"),
        ADMIN,
    )
    validate_error(dup, "ERR_BADGE_NUMBER_TAKEN", expected_status=409)

    # Uniqueness is scoped per program: the same badge in another program succeeds.
    ok = validate_success(
        api.create_employee(
            create_employee_payload(p2["id"], badge_number="B100", full_name="Ok",
                                    shift_pattern="NIGHT", hire_date="2024-02-01"),
            ADMIN,
        ),
        201,
    )
    assert_employee(ok)
    assert ok["badge_number"] == "B100"


def test_employee_invalid_enum_shift_pattern(api):
    """PRD section 3.1: "Registering an employee takes the `program_id` of the
    program they park under, a `badge_number` that must be unique within that
    program across all employees (a conflict is rejected with
    `ERR_BADGE_NUMBER_TAKEN`), a `full_name`, an `employer_code` identifying the
    tenant or airline, a `shift_pattern` of `DAY`, `NIGHT`, `ROTATING`, or
    `SPLIT`, and a `hire_date` as an ISO calendar date."
    PRD section 2.8: "`ERR_INVALID_REQUEST` at HTTP 400, the last of which also
    covers malformed JSON, missing required fields, invalid enum values, bad date
    or datetime formats, sign-rule violations on manual adjustments, and lot-code
    conflicts"

    Design: Corner/entities/employee_invalid_enum_shift_pattern
    """
    program = create_program(name="P-E3")

    res = api.create_employee(
        create_employee_payload(program["id"], shift_pattern="GRAVEYARD"),
        ADMIN,
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_employee_list_pagination_and_filter(api):
    """PRD section 2.3: "The `limit` parameter caps the number of items returned;
    it defaults to 10, with a minimum of 1 and a maximum of 100." and "The `meta`
    object of a list response carries `limit`, `offset`, `total_count`, and
    `has_more`."
    PRD section 4: "| GET | `/parking/employees` | List employees; filterable by
    `program_id`, `shift_pattern`, `standing`, `employment_status` | All roles |"

    Design: Corner/entities/employee_list_pagination_and_filter
    """
    program = create_program(name="P-LST")
    for i in range(1, 13):
        create_employee(
            program["id"], badge_number=f"B{i:03d}", full_name=f"E{i:02d}",
            shift_pattern="DAY" if i <= 2 else "NIGHT",
        )

    data, meta = validate_paginated(
        api.list_employees(ADMIN, params={"program_id": program["id"]})
    )
    assert meta["limit"] == 10, "default limit is 10"
    assert meta["total_count"] == 12
    assert meta["has_more"] is True
    assert len(data) == 10

    filtered, fmeta = validate_paginated(
        api.list_employees(
            ADMIN, params={"program_id": program["id"], "shift_pattern": "DAY"}
        )
    )
    assert fmeta["total_count"] == 2
    assert len(filtered) == 2
    assert all(row["shift_pattern"] == "DAY" for row in filtered)


def test_employee_cannot_terminate_twice(api):
    """PRD section 3.1: "When a `ParkingAdmin` terminates an employee,
    `employment_status` becomes `TERMINATED` and `terminated_at` is stamped with
    the current logical time; the employee's permits are not revoked at that
    moment." and "`TERMINATED` is terminal."
    PRD section 2.8: "The target resource must be in the exact from-state of the
    requested transition, and program posture must permit the operation
    (`ERR_PROGRAM_FROZEN`, `ERR_PERMIT_NOT_OFFERED`, `ERR_INVALID_STATE`,
    `ERR_LOT_NOT_BOOKABLE`, `ERR_ROUTE_NOT_ACTIVE`, `ERR_CYCLE_NOT_OPEN`)."

    Design: Corner/state_machines/employee_cannot_terminate_twice
    """
    program = create_program(name="P-SM3")
    employee = create_employee(program["id"], badge_number="B001")

    set_logical_clock("2026-08-02T09:00:00Z")
    terminated = validate_success(api.terminate_employee(employee["id"], ADMIN), 200)
    assert terminated["employment_status"] == "TERMINATED"
    assert_instant_equals(terminated["terminated_at"], "2026-08-02T09:00:00Z",
                          label="terminated_at")

    res = api.terminate_employee(employee["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    reread = validate_success(api.get_employee(employee["id"], ADMIN), 200)
    assert_instant_equals(reread["terminated_at"], "2026-08-02T09:00:00Z",
                          label="terminated_at after rejected second terminate")


def test_permit_get_not_found(api):
    """PRD section 2.9: "Identifiers embedded in a URL path are validated in
    left-to-right order: the first identifier that does not correspond to an
    existing resource yields `ERR_NOT_FOUND` (HTTP 404) before any further
    processing."
    PRD section 2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/permit_get_not_found
    """
    res = api.get_permit(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)
    body = res.json()
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["meta"]["api_request_id"].startswith("req_"), (
        "error envelope meta carries the server-generated api_request_id"
    )

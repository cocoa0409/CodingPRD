"""Program-level concerns: configuration defaults, the posture gate, the ops
checkpoint's termination sweep, and renewal OCC + decision lifecycle."""
import pytest

from test_helpers import (
    PARKING_ADMIN_ID,
    TEST_USERS,
    accept_permit,
    apply_for_permit,
    assert_program,
    create_employee,
    create_program,
    create_renewal_payload,
    get_cycle,
    get_employee,
    get_lot,
    make_employee_headers,
    set_logical_clock,
    setup_active_permit,
    setup_offered_permit,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["parking_admin_headers"]
PAYROLL = TEST_USERS["payroll_admin_headers"]


def test_program_config_defaults_applied(api):
    """PRD section 3.1: "The `proration_mode` selects the proration variant —
    `CALENDAR_DAY` (the default) or `HALF_MONTH` — and is immutable after
    creation. The `monthly_subsidy_pool_cents` seeds the subsidy pool available
    per billing cycle (default 0, never negative). Three policy knobs govern
    enforcement timing: `waitlist_offer_ttl_hours` sets how many hours an offer
    remains acceptable (default 72, must be positive),
    `violation_suspension_threshold` sets the unpaid-violation count that
    suspends a permit (default 3, at least 1), and `tow_hold_hours` sets the
    minimum suspension age in hours before a tow may be authorized (default 48,
    never negative). A new program starts in `posture` `PROGRAM_NORMAL` with its
    batch checkpoint counter `ops_run_index` at 0."

    Design: Corner/entities/program_config_defaults_applied
    """
    program = validate_success(api.create_program({"name": "P-DEF"}, ADMIN), 201)
    assert_program(program)
    assert program["proration_mode"] == "CALENDAR_DAY"
    assert program["monthly_subsidy_pool_cents"] == 0
    assert program["waitlist_offer_ttl_hours"] == 72
    assert program["violation_suspension_threshold"] == 3
    assert program["tow_hold_hours"] == 48
    assert program["posture"] == "PROGRAM_NORMAL"
    assert program["ops_run_index"] == 0


def test_posture_freeze_blocks_applications_not_accepts(api):
    """PRD section 3.1: "Posture is the program's master gate. A `ParkingAdmin`
    may freeze a `PROGRAM_NORMAL` program into `PROGRAM_FROZEN` and thaw it back
    at will. While frozen, waitlist promotion is disabled, and new permit
    applications and renewal creations are rejected with `ERR_PROGRAM_FROZEN`.
    Thawing a program back to `PROGRAM_NORMAL` immediately runs a waitlist
    promotion pass on every bookable lot of the program, processing the lots in
    `created_at` ascending order."

    Design: Corner/endpoints/posture_freeze_blocks_applications_not_accepts
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    bundle = setup_offered_permit(lot_overrides={"capacity": 2})
    other = create_employee(bundle["program"]["id"], badge_number="B002")

    validate_success(
        api.set_program_posture(bundle["program"]["id"], "PROGRAM_FROZEN", ADMIN),
        200,
    )

    # New applications are rejected while frozen...
    res = api.create_permit(
        {"employee_id": other["id"], "lot_id": bundle["lot"]["id"],
         "vehicle_plate": "P002"},
        make_employee_headers(other["id"]),
    )
    validate_error(res, "ERR_PROGRAM_FROZEN", expected_status=409)

    # ...but an outstanding offer can still be accepted (accept is not
    # posture-gated).
    accepted = accept_permit(bundle["permit"], bundle["employee"])
    assert accepted["status"] == "ACTIVE"

    # Thawing restores applications.
    validate_success(
        api.set_program_posture(bundle["program"]["id"], "PROGRAM_NORMAL", ADMIN),
        200,
    )
    offered = apply_for_permit(other, bundle["lot"], vehicle_plate="P002")
    assert offered["status"] == "OFFERED"


def test_run_ops_termination_sweep_revokes_and_prorates(api):
    """PRD section 3.1: "When a `ParkingAdmin` terminates an employee,
    `employment_status` becomes `TERMINATED` and `terminated_at` is stamped with
    the current logical time; the employee's permits are not revoked at that
    moment."
    PRD section 3.9: "Fourth, the termination sweep revokes every non-terminal
    permit of a `TERMINATED` employee — `ACTIVE` permits receive the revocation
    span-truncation repost, `OFFERED` permits release their reservations."
    PRD section 3.9: "Seventh, the program's `ops_run_index` increments by one."

    Design: Corner/endpoints/run_ops_termination_sweep_revokes_and_prorates
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    bundle = setup_active_permit(
        program_overrides={"monthly_subsidy_pool_cents": 100000},
        lot_overrides={"capacity": 5},
    )

    set_logical_clock("2026-08-16T09:00:00Z")
    validate_success(api.terminate_employee(bundle["employee"]["id"], ADMIN), 200)

    pre = validate_success(api.get_permit(bundle["permit"]["id"], ADMIN), 200)
    assert pre["status"] == "ACTIVE", "termination alone does not revoke"

    set_logical_clock("2026-08-16T10:00:00Z")
    program = validate_success(
        api.run_program_ops(bundle["program"]["id"], ADMIN), 200
    )
    assert program["ops_run_index"] == 1

    post = validate_success(api.get_permit(bundle["permit"]["id"], ADMIN), 200)
    assert post["status"] == "REVOKED", "the sweep revoked it"

    cycle = get_cycle(bundle["cycle"]["id"])
    # net 10800 truncated to [2026-08-01, 2026-08-16]: 16 active days of 31.
    assert cycle["total_charges_cents"] == 5574
    assert get_lot(bundle["lot"]["id"])["occupied_slots"] == 0


def test_occ_renewal_create_stale_version(api):
    """PRD section 2.7: "First, renewal creation: a request to create a renewal
    for a permit must carry `expected_permit_version`, holding the permit
    `version` the client last observed. If the permit's current `version` has
    advanced since that observation — for example because another writer's
    renewal create already bumped it, or a cascade-driven suspension did — the
    create is rejected with `ERR_STALE_PERMIT_VERSION` (HTTP 412), and the client
    must re-read before writing."
    PRD section 3.5: "A successful creation starts the renewal at `PENDING`,
    stamps `requested_at`, supersedes any existing `PENDING` renewal of the same
    permit by moving it to `SUPERSEDED`, and increments the permit's `version` by
    one."

    Design: Corner/cross_cutting_layers/occ_renewal_create_stale_version
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    bundle = setup_active_permit(
        program_overrides={"monthly_subsidy_pool_cents": 0},
        lot_overrides={"capacity": 2},
    )
    permit_id = bundle["permit"]["id"]
    owner = make_employee_headers(bundle["employee"]["id"])

    observed = validate_success(api.get_permit(permit_id, ADMIN), 200)["version"]
    r1 = validate_success(
        api.create_permit_renewal(permit_id, create_renewal_payload(observed),
                                  owner),
        201,
    )
    assert r1["status"] == "PENDING"

    # The first create bumped the permit's version, so the same snapshot is stale.
    stale = api.create_permit_renewal(permit_id, create_renewal_payload(observed),
                                      owner)
    validate_error(stale, "ERR_STALE_PERMIT_VERSION", expected_status=412)

    fresh = validate_success(api.get_permit(permit_id, ADMIN), 200)["version"]
    r2 = validate_success(
        api.create_permit_renewal(permit_id, create_renewal_payload(fresh), owner),
        201,
    )

    renewals, meta = validate_paginated(
        api.list_permit_renewals(permit_id, ADMIN)
    )
    by_id = {r["id"]: r for r in renewals}
    assert by_id[r1["id"]]["status"] == "SUPERSEDED", "create-with-supersede"
    assert by_id[r2["id"]]["status"] == "PENDING"


def test_renewal_decide_twice_rejected(api):
    """PRD section 3.5: "A `ParkingAdmin` then decides: a `decision` of `APPROVE`
    requires the permit to be `ACTIVE` (`ERR_INVALID_STATE` otherwise) and
    extends the permit's `term_end` by 12 months; a `decision` of `REJECT` closes
    the renewal as `REJECTED`. Either decision records the decider's `X-User-ID`
    in `decided_by`."
    PRD section 3.5: "`APPROVED`, `REJECTED`, `SUPERSEDED`, and `EXPIRED` are
    terminal."
    PRD section 3.4: "Activation stamps `activated_at`, sets `term_end` to the
    activation date plus 12 months, releases the reservation and increases the
    lot's derived occupancy by one, and freezes the permit's gross monthly fee."

    Design: Corner/state_machines/renewal_decide_twice_rejected
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    bundle = setup_active_permit(
        program_overrides={"monthly_subsidy_pool_cents": 0},
        lot_overrides={"capacity": 2},
    )
    permit_id = bundle["permit"]["id"]
    assert bundle["permit"]["term_end"] == "2027-08-01"

    observed = validate_success(api.get_permit(permit_id, ADMIN), 200)["version"]
    renewal = validate_success(
        api.create_permit_renewal(
            permit_id, create_renewal_payload(observed),
            make_employee_headers(bundle["employee"]["id"]),
        ),
        201,
    )

    decided = validate_success(
        api.decide_renewal(renewal["id"], {"decision": "APPROVE"}, ADMIN), 200
    )
    assert decided["status"] == "APPROVED"
    assert decided["decided_by"] == PARKING_ADMIN_ID, (
        "the decider's X-User-ID is recorded"
    )

    permit = validate_success(api.get_permit(permit_id, ADMIN), 200)
    assert permit["term_end"] == "2028-08-01", "12-month extension applied once"

    # APPROVED is terminal: a second decision is a lifecycle violation.
    res = api.decide_renewal(renewal["id"], {"decision": "REJECT"}, ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

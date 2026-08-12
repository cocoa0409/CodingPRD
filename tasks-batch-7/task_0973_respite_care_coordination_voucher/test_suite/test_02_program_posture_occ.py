"""Program posture gates, 404 resolution, and OCC stale-version rules."""
from test_helpers import (
    ADMIN,
    ANON,
    COORD,
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_active_caregiver,
    create_caregiver_payload,
    create_program,
    get_success_data,
    issue_voucher,
    api_client,
    make_caregiver_headers,
    validate_error,
    validate_success,
)


def test_get_program_not_found(api):
    """PRD §2.9: "(5) path and body id resolution (the appropriate `ERR_*_NOT_FOUND`)"
    PRD §5: ERR_PROGRAM_NOT_FOUND maps to HTTP 404.

    Design: Corner/entities/program_get_not_found_returns_404
    """
    res = api.get_program(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_FOUND, expected_status=404)


def test_posture_pause_gates_caregiver_creation(api):
    """PRD §2.8: "Creating a caregiver or provider, or approving an eligibility
    application, requires `ENROLLMENT_OPEN`."
    PRD §2.8: "A violation of either posture gate is rejected with `ERR_POSTURE_GATE`
    (HTTP 409)."

    Design: Corner/validations/posture_pause_gates_enrollment
    """
    program = create_program()
    validate_success(
        api.set_program_posture(program["id"], {"target_posture": "ENROLLMENT_PAUSED"}, ADMIN),
        200)
    res = api.create_caregiver(create_caregiver_payload(), ANON)
    validate_error(res, ApiErrorId.ERR_POSTURE_GATE, expected_status=409)

    validate_success(
        api.set_program_posture(program["id"], {"target_posture": "ENROLLMENT_OPEN"}, ADMIN),
        200)
    caregiver = validate_success(api.create_caregiver(create_caregiver_payload(), ANON), 201)
    assert caregiver["status"] == "ENROLLED"


def test_budget_adjust_stale_version_rejected(api):
    """PRD §3.1: "If the program's `version` has advanced since the client last read
    it, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.1: "When applied, the adjustment adds `delta_cents` to `total_budget_cents`"
    PRD §3.1: "Each successful adjustment appends a `BudgetLedgerEntry` of `entry_type`
    `ADJUSTMENT` and increments `Program.version` by 1."

    Design: Corner/complexity_layers/occ_program_budget_adjust_stale_version
    """
    program = create_program()
    observed_version = program["version"]

    updated = validate_success(
        api.create_budget_adjustment(
            program["id"],
            {"delta_cents": 100000, "reason": "top-up",
             "expected_program_version": observed_version},
            ADMIN),
        201)
    assert updated["total_budget_cents"] == 50100000
    assert updated["version"] == observed_version + 1

    res = api.create_budget_adjustment(
        program["id"],
        {"delta_cents": 50000, "reason": "stale retry",
         "expected_program_version": observed_version},
        ADMIN)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    after = validate_success(api.get_program(program["id"], ADMIN), 200)
    assert after["total_budget_cents"] == 50100000


def test_grant_adjust_stale_version_rejected(api):
    """PRD §3.3: "If the allocation's `version` has advanced since the client last
    read it — because a voucher issue, redeem, or revoke cascade has touched it, or
    because a prior adjustment did — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."
    PRD §3.3: "When applied, `delta_hours` is added to both `granted_hours` and
    `available_hours`"

    Design: Corner/complexity_layers/occ_allocation_grant_adjust_stale_version
    """
    ctx = create_active_caregiver()
    alloc = ctx["allocation"]
    stale_version = alloc["version"]

    # A voucher issue cascade bumps the allocation version between read and write.
    issue_voucher(alloc["id"], ctx["caregiver"]["id"], 10)

    res = api.create_grant_adjustment(
        alloc["id"],
        {"delta_hours": 10, "reason": "stale view",
         "expected_allocation_version": stale_version},
        COORD)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    fresh = validate_success(api.get_allocation(alloc["id"], COORD), 200)
    assert fresh["granted_hours"] == 80.00

    adjusted = validate_success(
        api.create_grant_adjustment(
            alloc["id"],
            {"delta_hours": 10, "reason": "fresh view",
             "expected_allocation_version": fresh["version"]},
            COORD),
        201)
    assert adjusted["granted_hours"] == 90.00
    assert adjusted["available_hours"] == 80.00

"""Queue B — §1.7 RBAC corners: the two auth rungs answering above existence and state,
one exclusive operation of each operator role refused to the others, the two entity-backed
scopes over the same rows, and segregation of duties compared by identifier."""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    COMPLIANCE_ALT,
    PREPARER,
    ApiErrorId,
    approve_period,
    assert_instant_equals,
    build_user_headers,
    close_shift,
    compute_period,
    create_back_wage_correction_payload,
    create_dispute_payload,
    create_location_payload,
    create_shift_payload,
    declare_shift_tips,
    declare_tips_payload,
    list_pay_lines_of,
    make_compliance_officer_headers,
    make_employee_headers,
    make_shift_manager_headers,
    new_correction,
    new_employee,
    new_location,
    new_role_assignment,
    new_shift,
    read_correction,
    read_pay_line,
    read_pay_period,
    read_shift,
    setup_texas_wage_world,
    sole_pay_line_of,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-10T12:00:00Z"
NO_HEADERS = {}
MISSING_PAY_LINE = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
MISSING_POLICY = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
MISSING_LINE_FOR_DISPUTE = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"


def _approved_world() -> dict:
    """The Texas wage unit with one 480-minute CLOSED shift declaring 15000 cash tips,
    computed by op_prep_1 and approved by op_comp_1."""
    world = setup_texas_wage_world()
    shift = new_shift(
        world["employee"]["id"],
        world["location"]["id"],
        world["role_server"]["id"],
        world["pay_period"]["id"],
    )
    close_shift(shift["id"])
    declare_shift_tips(shift["id"], world["employee"]["id"], 15000, 0)
    compute_period(world["pay_period"]["id"])
    approve_period(world["pay_period"]["id"])
    world["shift"] = shift
    world["pay_line"] = sole_pay_line_of(world["pay_period"]["id"])
    return world


# ---------------------------------------------------------------------------
# rbac / missing_credentials_and_wrong_role_are_refused_before_existence_and_state
# ---------------------------------------------------------------------------
def test_the_two_auth_rungs_answer_above_existence_and_above_state(api):
    """No headers is a 401 on an unknown id; a wrong role is a 403 on an unknown id.

    PRD §2.10: "1. Both `X-User-ID` and `X-User-Role` present and non-empty —
    `ERR_UNAUTHENTICATED`, 401, on every endpoint."
    PRD §2.10: "2. The value of `X-User-Role` appears in the target endpoint's authorised
    role list — `ERR_FORBIDDEN_ROLE`, 403, on every endpoint."
    PRD §2.10: "Every rule in the system occupies a fixed rung on a single precedence
    ladder, and the rule on the lowest-numbered rung that the request violates is the rule
    that produces the response; every rule below it on the ladder is never reached."
    PRD §2.1: "If either header is missing or present but empty, the request is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs."

    Design: Corner/rbac/missing_credentials_and_wrong_role_are_refused_before_existence_and_state
    """
    world = _approved_world()

    validate_error(
        api.create_location(
            create_location_payload(name="Anonymous Unit"), NO_HEADERS
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )
    validate_error(
        api.get_pay_line(MISSING_PAY_LINE, NO_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    validate_error(
        api.activate_tip_pool_policy(
            MISSING_POLICY, {"expected_location_version": 1}, PREPARER
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    validate_error(
        api.create_dispute(
            create_dispute_payload(
                MISSING_LINE_FOR_DISPUTE,
                world["employee"]["id"],
                category="CC_FEE",
                claimed_amount_cents=400,
            ),
            make_shift_manager_headers(world["employee"]["id"]),
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    validate_error(
        api.compute_pay_period(world["pay_period"]["id"], COMPLIANCE),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    assert read_pay_period(world["pay_period"]["id"])["status"] == "APPROVED", (
        "the role rung answered before the period's own state could"
    )


def test_one_exclusive_operation_of_each_operator_role_refuses_the_others(api):
    """Registration, voiding, issuing and the clock each belong to exactly one role.

    PRD §2.1: "If the value of `X-User-Role` is not among the roles authorised for the
    endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "A `PayrollAdmin` is the chain configuration operator: it registers restaurant
    units, defines chain-wide job roles, hires employees, records role assignments, drafts
    tip-pool policies, and drives the server's logical clock."
    PRD §2.1: "A `PayrollPreparer` is the unit payroll operator: it records shifts and
    service charges, closes shifts, builds and distributes tip pools, voids shifts and
    service charges, and computes pay periods."
    PRD §2.1: "A `ShiftManager` is a front-of-house supervisor who records and closes
    shifts, records service charges, and may declare tips on behalf of staff."
    PRD §2.1: "Both a `ComplianceOfficer` and a `PayrollPreparer` may post a pending
    back-wage correction to its pay line."

    Design: Corner/rbac/missing_credentials_and_wrong_role_are_refused_before_existence_and_state
    """
    world = _approved_world()
    line = world["pay_line"]

    validate_error(
        api.create_location(create_location_payload(name="Preparer Unit"), PREPARER),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    validate_error(
        api.void_shift(
            world["shift"]["id"],
            make_shift_manager_headers(world["employee"]["id"]),
            {"reason": "manager overreach"},
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    validate_error(
        api.create_back_wage_correction(
            create_back_wage_correction_payload(
                line["id"],
                line["version"],
                amount_cents=500,
                reason_code="POOL_SHARE_SHORTFALL",
            ),
            PREPARER,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )
    validate_error(
        api.set_clock({"current_utc": "2027-01-01T00:00:00Z"}, COMPLIANCE),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )

    _units, unit_meta = validate_paginated(api.list_locations(ADMIN))
    assert unit_meta["total_count"] == 1, "no refused registration was stored"
    assert read_shift(world["shift"]["id"])["time_status"] == "CLOSED"
    _corrections, correction_meta = validate_paginated(
        api.list_back_wage_corrections(COMPLIANCE)
    )
    assert correction_meta["total_count"] == 0
    _disputes, dispute_meta = validate_paginated(api.list_disputes(COMPLIANCE))
    assert dispute_meta["total_count"] == 0
    assert read_pay_line(line["id"])["version"] == 2

    later = new_employee(world["location"]["id"], external_payroll_ref="E9")
    assert_instant_equals(later["created_at"], CLOCK, "created_at")


# ---------------------------------------------------------------------------
# rbac / entity_backed_roles_are_confined_to_their_own_employee_and_unit
# ---------------------------------------------------------------------------
def _two_unit_staff_world() -> dict:
    """Dallas with Ana and Bea, Austin with Cid, and Ana's and Bea's CLOSED shifts on
    2026-08-04 at Dallas, only Bea's declared."""
    world = setup_texas_wage_world()
    dallas, role, ana, period = (
        world["location"],
        world["role_server"],
        world["employee"],
        world["pay_period"],
    )
    austin = new_location(name="Austin Unit")
    bea = new_employee(dallas["id"], full_name="Bea Lima", external_payroll_ref="E2")
    cid = new_employee(austin["id"], full_name="Cid Marek", external_payroll_ref="E3")
    new_role_assignment(bea["id"], role["id"])
    new_role_assignment(cid["id"], role["id"])
    manager = make_shift_manager_headers(bea["id"])

    ana_shift = new_shift(ana["id"], dallas["id"], role["id"], period["id"], headers=manager)
    bea_shift = new_shift(bea["id"], dallas["id"], role["id"], period["id"], headers=manager)
    close_shift(ana_shift["id"], manager)
    close_shift(bea_shift["id"], manager)
    declare_shift_tips(bea_shift["id"], bea["id"], 9000, 0)

    world.update(
        {
            "dallas": dallas,
            "austin": austin,
            "ana": ana,
            "bea": bea,
            "cid": cid,
            "ana_shift": ana_shift,
            "bea_shift": bea_shift,
        }
    )
    return world


def test_an_employee_declares_on_their_own_shift_and_on_no_other(api):
    """Bea cannot put words in Ana's mouth; Ana can.

    PRD §2.1: "Concretely, an acting `Employee` may declare tips only on a shift whose
    `employee_id` equals `X-User-ID`, may raise a dispute only where the supplied
    `raised_by_employee_id` equals `X-User-ID` and only against a pay line whose
    `employee_id` equals `X-User-ID`, and may read only those pay lines, shifts and
    pool-allocation rows whose `employee_id` equals `X-User-ID`."
    PRD §2.1: "Any breach of either scope is rejected with `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403)."
    PRD §3.5: "The declaration dimension moves `UNDECLARED → DECLARED` on the first
    declaration, `DECLARED → AMENDED` on the second, and thereafter cycles
    `AMENDED → AMENDED` without bound for as long as the period stays `OPEN` and the shift
    stays unpooled."

    Design: Corner/rbac/entity_backed_roles_are_confined_to_their_own_employee_and_unit
    """
    world = _two_unit_staff_world()

    validate_error(
        api.declare_tips(
            world["ana_shift"]["id"],
            declare_tips_payload(15000, 0),
            make_employee_headers(world["bea"]["id"]),
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )
    assert read_shift(world["ana_shift"]["id"])["declaration_status"] == "UNDECLARED"

    declared = validate_success(
        api.declare_tips(
            world["ana_shift"]["id"],
            declare_tips_payload(15000, 0),
            make_employee_headers(world["ana"]["id"]),
        )
    )
    assert declared["declared_cash_tips_cents"] == 15000
    assert declared["declaration_status"] == "DECLARED"


def test_the_manager_scope_is_the_unit_where_the_employee_scope_is_the_person(api):
    """One shift read three ways, and the mismatch rule that still guards a write.

    PRD §2.1: "When `X-User-Role` is `ShiftManager`, `X-User-ID` is likewise the `id` of the
    acting `Employee`, but the ownership check is widened one level: a `ShiftManager` is
    confined to the `location_id` of the `Employee` row that `X-User-ID` names, and may act
    on and read shifts, pay lines, allocation rows and disputes belonging to that unit rather
    than only to that one person."
    PRD §2.11: "The two entity-backed roles are narrowed as described in §2.1 — a
    `ShiftManager` sees only its own unit's records and an `Employee` sees only its own — and
    single-resource reads outside that scope on a pay line, a shift or a pool-allocation row
    are refused with `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.4: "Then the shift's `location_id` must equal both the employee's own
    `location_id` and the period's `location_id`, failing which
    `ERR_EMPLOYEE_LOCATION_MISMATCH`."

    Design: Corner/rbac/entity_backed_roles_are_confined_to_their_own_employee_and_unit
    """
    world = _two_unit_staff_world()
    shift_id = world["ana_shift"]["id"]

    validate_error(
        api.get_shift(shift_id, make_employee_headers(world["bea"]["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )
    validate_error(
        api.get_shift(shift_id, make_shift_manager_headers(world["cid"]["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )
    inside_scope = validate_success(
        api.get_shift(shift_id, make_shift_manager_headers(world["bea"]["id"]))
    )
    assert inside_scope["employee_id"] == world["ana"]["id"], (
        "a colleague's shift at the manager's own unit is readable"
    )

    validate_error(
        api.create_shift(
            create_shift_payload(
                world["cid"]["id"],
                world["dallas"]["id"],
                world["role_server"]["id"],
                world["pay_period"]["id"],
                business_date="2026-08-05T00:00:00Z",
                start_at="2026-08-05T16:00:00Z",
                end_at="2026-08-06T00:00:00Z",
            ),
            PREPARER,
        ),
        ApiErrorId.ERR_EMPLOYEE_LOCATION_MISMATCH.value,
    )


def test_a_pay_line_and_the_right_to_dispute_it_belong_to_one_person(api):
    """Ownership at rung 6 answers both dispute mismatch shapes before rung 32 is reached.

    PRD §2.10: "6. Resource ownership for the two entity-backed roles, as described in
    §2.1 — `ERR_NOT_RESOURCE_OWNER`, 403, on `POST /shifts/{shift_id}/declare-tips`,
    `POST /disputes`, `GET /pay-lines/{pay_line_id}`, `GET /shifts/{shift_id}` and
    `GET /pool-allocations/{allocation_id}`."
    PRD §2.10: "32. The shift's `location_id` equals both the employee's `location_id` and
    the pay period's `location_id`; and a dispute's `raised_by_employee_id` matches the
    disputed pay line's `employee_id` — `ERR_EMPLOYEE_LOCATION_MISMATCH`, 422, on
    `POST /shifts` and `POST /disputes`."
    PRD §3.9: "Four checks guard a dispute, in this order. The acting employee must own the
    line, meaning both that `raised_by_employee_id` equals `X-User-ID` and that the line's
    own `employee_id` equals `X-User-ID`, failing which `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.9: "A newly raised dispute has `status` `OPEN`, `adjudicated_amount_cents` 0,
    `adjudicated_by_user_id` null and `closed_at` null."

    Design: Corner/rbac/entity_backed_roles_are_confined_to_their_own_employee_and_unit
    """
    world = _two_unit_staff_world()
    declare_shift_tips(world["ana_shift"]["id"], world["ana"]["id"], 15000, 0)
    compute_period(world["pay_period"]["id"])
    approve_period(world["pay_period"]["id"])

    rows, meta = validate_paginated(
        api.list_pay_lines(
            COMPLIANCE, params={"pay_period_id": world["pay_period"]["id"]}
        )
    )
    assert meta["total_count"] == 2, "one line per employee"
    assert all(row["status"] == "FINAL" for row in rows)

    ana_line = list_pay_lines_of(
        world["pay_period"]["id"], COMPLIANCE, employee_id=world["ana"]["id"]
    )[0]
    assert ana_line["employee_id"] == world["ana"]["id"]
    assert ana_line["straight_cash_cents"] == 1704
    assert ana_line["minimum_wage_obligation_cents"] == 5800
    assert ana_line["tips_available_cents"] == 15000
    assert ana_line["tip_credit_cents"] == 4096
    assert ana_line["total_gross_cents"] == 1704

    validate_error(
        api.get_pay_line(ana_line["id"], make_employee_headers(world["bea"]["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )
    own = validate_success(
        api.get_pay_line(ana_line["id"], make_employee_headers(world["ana"]["id"]))
    )
    assert own["id"] == ana_line["id"]

    validate_error(
        api.create_dispute(
            create_dispute_payload(
                ana_line["id"],
                world["ana"]["id"],
                category="TIP_CREDIT",
                claimed_amount_cents=500,
            ),
            make_employee_headers(world["bea"]["id"]),
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )
    validate_error(
        api.create_dispute(
            create_dispute_payload(
                ana_line["id"],
                world["bea"]["id"],
                category="TIP_CREDIT",
                claimed_amount_cents=500,
            ),
            make_employee_headers(world["bea"]["id"]),
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )
    raised = validate_success(
        api.create_dispute(
            create_dispute_payload(
                ana_line["id"],
                world["ana"]["id"],
                category="TIP_CREDIT",
                claimed_amount_cents=500,
            ),
            make_employee_headers(world["ana"]["id"]),
        ),
        expected_status=201,
    )
    assert raised["status"] == "OPEN"
    _disputes, dispute_meta = validate_paginated(
        api.list_disputes(COMPLIANCE, params={"pay_line_id": ana_line["id"]})
    )
    assert dispute_meta["total_count"] == 1


# ---------------------------------------------------------------------------
# rbac / segregation_of_duties_blocks_the_same_operator_at_both_steps
# ---------------------------------------------------------------------------
def _computed_world() -> dict:
    """The Texas wage unit with one 480-minute CLOSED shift declaring 15000 cash tips,
    computed by op_prep_1 and not yet approved."""
    world = setup_texas_wage_world()
    shift = new_shift(
        world["employee"]["id"],
        world["location"]["id"],
        world["role_server"]["id"],
        world["pay_period"]["id"],
    )
    close_shift(shift["id"])
    declare_shift_tips(shift["id"], world["employee"]["id"], 15000, 0)
    compute_period(world["pay_period"]["id"])
    world["shift"] = shift
    return world


def test_the_approver_is_compared_by_identifier_and_not_by_role(api):
    """op_prep_1 wearing a ComplianceOfficer header is still the operator who computed.

    PRD §2.9: "The operator who approves a pay period must not be the operator whose compute
    call produced its current pay lines: if `X-User-ID` on the approval equals the period's
    `computed_by_user_id`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)."
    PRD §2.9: "Because both checks are on identifiers and not on roles, the two payroll
    operator roles cannot be collapsed onto one person even where the role list would permit
    it."
    PRD §3.8: "Approval recomputes every non-`SUPERSEDED` pay line of the period under the
    `PER_SHIFT` variant, overwriting `tip_credit_cents`, `topup_cents` and
    `total_gross_cents`; runs the reporting test below, writing each line's
    `allocated_tips_cents` and the period's `allocation_shortfall_cents`; moves every
    non-`SUPERSEDED` pay line from `DRAFT` to `FINAL`; sets the period's `compute_variant` to
    `PER_SHIFT` and its `approved_by_user_id` to the acting `X-User-ID`; and recomputes the
    period's `total_tip_credit_cents` and `total_topup_cents` from the new `PER_SHIFT`
    figures."

    Design: Corner/rbac/segregation_of_duties_blocks_the_same_operator_at_both_steps
    """
    world = _computed_world()
    period_id = world["pay_period"]["id"]

    validate_error(
        api.approve_pay_period(
            period_id, build_user_headers("op_prep_1", "ComplianceOfficer")
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )
    still_computed = read_pay_period(period_id)
    assert still_computed["status"] == "COMPUTED"
    assert still_computed["approved_by_user_id"] is None
    assert all(
        row["status"] == "DRAFT" for row in list_pay_lines_of(period_id, COMPLIANCE)
    )

    approved = validate_success(api.approve_pay_period(period_id, COMPLIANCE))
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "op_comp_1"
    assert approved["computed_by_user_id"] == "op_prep_1"

    line = sole_pay_line_of(period_id, COMPLIANCE)
    assert line["status"] == "FINAL"
    assert line["version"] == 2
    assert line["straight_cash_cents"] == 1704
    assert line["tip_credit_cents"] == 4096
    assert line["total_gross_cents"] == 1704


def test_the_issuer_of_a_correction_may_not_also_post_it(api):
    """Two different officers are two different humans, which is all the rule asks.

    PRD §2.9: "Likewise, the operator who applies a back-wage correction must not be the
    operator who issued it: if `X-User-ID` on the apply equals that correction's
    `issued_by_user_id`, the same `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) is returned."
    PRD §3.9: "A newly issued correction has `status` `PENDING`, its `issued_by_user_id` set
    to the acting `X-User-ID`, and `applied_by_user_id`, `applied_at` and `voided_at` all
    null."
    PRD §3.9: "The correction's `amount_cents` is subtracted from the line's
    `pending_correction_cents`; the same amount is added to the line's
    `correction_applied_cents`; the same amount is added to the line's `total_gross_cents`;
    the line's `version` is incremented by 1; and `applied_at` is stamped with the current
    logical instant while `applied_by_user_id` records the acting `X-User-ID`."

    Design: Corner/rbac/segregation_of_duties_blocks_the_same_operator_at_both_steps
    """
    world = _computed_world()
    period_id = world["pay_period"]["id"]
    approve_period(period_id)
    line = sole_pay_line_of(period_id, COMPLIANCE)

    correction = new_correction(
        line["id"],
        line["version"],
        headers=COMPLIANCE_ALT,
        amount_cents=500,
        reason_code="POOL_SHARE_SHORTFALL",
    )
    assert correction["status"] == "PENDING"
    assert correction["issued_by_user_id"] == "op_comp_2"
    assert correction["applied_by_user_id"] is None
    assert correction["applied_at"] is None

    validate_error(
        api.apply_back_wage_correction(correction["id"], COMPLIANCE_ALT),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )
    still_pending = read_correction(correction["id"])
    assert still_pending["status"] == "PENDING"
    assert still_pending["applied_at"] is None
    assert still_pending["applied_by_user_id"] is None

    applied = validate_success(
        api.apply_back_wage_correction(
            correction["id"], make_compliance_officer_headers("op_comp_1")
        )
    )
    assert applied["status"] == "APPLIED"
    assert applied["applied_by_user_id"] == "op_comp_1"
    assert_instant_equals(applied["applied_at"], CLOCK, "applied_at")

    settled = read_pay_line(line["id"])
    assert settled["correction_applied_cents"] == 500
    assert settled["pending_correction_cents"] == 0
    assert settled["total_gross_cents"] == 2204, "1704 of wages plus the 500 posted"

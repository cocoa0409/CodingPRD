"""Two pairs of rungs that a single call violates at once.

In each pair the higher rung of Section 2.9 must be the one reported, and a
control unit that violates only the lower rung proves the lower rung was
genuinely violated too rather than merely unreachable.
"""

from test_helpers import (
    BuildStatus,
    CertificationStatus,
    ChangeOrderStatus,
    ErrorCode,
    ProgramStatus,
    WeightStatus,
    assert_axle_loads,
    assert_program_ledger,
    assert_unit_dimensions,
    assert_unit_money,
    award_unit,
    confirm_reservation,
    create_plant_bay,
    create_slot_line,
    deliver_unit,
    hold_trip,
    make_program_admin_headers,
    make_purchasing_officer_headers,
    raise_change_order,
    read_change_order,
    read_program,
    read_unit,
    record_test_result,
    reserve_slot,
    schedule_trip,
    setup_awarded_unit,
    setup_program_with_released_spec,
    setup_unit_at_stage,
    submit_certification_test,
    submit_change_order,
    validate_error,
    validate_success,
)


PUMP_CLAUSE = [
    {"clause_code": "C1", "category": "PUMP",
     "requirement_text": "1500 gpm single stage pump",
     "mandatory": True, "is_restrictive": False},
]

RIVERSIDE = {"name": "Riverside FD ladder program",
             "agency_name": "Riverside Fire",
             "max_option_units": 1,
             "contract_ceiling_cents": 150_000_000}

BIG_LINE = [{"description": "Aerial waterway retrofit", "quantity": 1,
             "unit_cost_cents": 120_000_000, "markup_pct": 0.0,
             "is_taxable": False}]

SMALL_LINE = [{"description": "Compartment shelving", "quantity": 1,
               "unit_cost_cents": 400_000, "markup_pct": 0.0,
               "is_taxable": False}]


def _delivered_unit_with_a_submitted_amendment(api):
    """The amendment is raised before delivery and outlives it.

    Delivery itself has no open-change-order gate, so the unit reaches
    ``DELIVERED`` while a 120,000,000-cent amendment is still `SUBMITTED`.
    """
    ctx = setup_unit_at_stage(
        api, "FINAL_INSPECTED",
        program_overrides=dict(RIVERSIDE),
        clauses=PUMP_CLAUSE,
        bay_overrides={"name": "Bay P1", "max_concurrent_visitors": 10},
        pre_trip_overrides={"scheduled_start": "2026-08-10T08:00:00Z",
                            "scheduled_end": "2026-08-10T16:00:00Z"},
        slot_line_overrides={"supplier_name": "Freightline Custom Chassis",
                             "total_slot_count": 2},
    )
    change_order = raise_change_order(api, ctx["unit_id"], ctx["mid_trip_id"],
                                      ctx["program_id"], line_items=BIG_LINE)
    submitted = submit_change_order(api, change_order["id"], ctx["program_id"])
    assert submitted["price_delta_cents"] == 120_000_000, submitted
    ctx["change_order_id"] = change_order["id"]
    ctx["unit"] = deliver_unit(api, ctx["unit_id"])
    return ctx


def _amendable_unit_with_a_submitted_amendment(api):
    """The same 120,000,000-cent amendment on a unit that is still amendable."""
    ctx = setup_awarded_unit(api, program_overrides=dict(RIVERSIDE),
                             clauses=PUMP_CLAUSE)
    bay = create_plant_bay(api, name="Bay P2", max_concurrent_visitors=10)
    trip = schedule_trip(api, ctx["unit_id"], bay["id"],
                         trip_type="PRE_CONSTRUCTION",
                         scheduled_start="2026-08-11T08:00:00Z",
                         scheduled_end="2026-08-11T16:00:00Z", committee_size=4)
    hold_trip(api, trip["id"])
    change_order = raise_change_order(api, ctx["unit_id"], trip["id"],
                                      ctx["program_id"], line_items=BIG_LINE)
    submitted = submit_change_order(api, change_order["id"], ctx["program_id"])
    assert submitted["price_delta_cents"] == 120_000_000, submitted
    ctx["change_order_id"] = change_order["id"]
    ctx["unit"] = read_unit(api, ctx["unit_id"])
    return ctx


def _twin_certified_units(api):
    """Two pumpers of one program differing by one kilogram of rear rating.

    Unit A is rated 10,109 kg against a computed rear load of 10,110 kg, so it
    reports ``OVER_REAR``; unit B is rated exactly 10,110 kg and reports
    ``WITHIN_LIMITS``. Both are ``MID_CON_HELD`` and ``CERTIFIED``, and both
    carry one outstanding DRAFT change order.
    """
    ctx = setup_program_with_released_spec(
        api,
        program_overrides={"name": "Twin-unit pumper program",
                           "agency_name": "Northgate Fire",
                           "max_option_units": 2},
        clauses=PUMP_CLAUSE,
    )
    admin = make_program_admin_headers()
    unit_a = award_unit(api, ctx["program_id"], ctx["specification_id"],
                        rear_axle_rating_kg=10_109)
    unit_b = award_unit(api, ctx["program_id"], ctx["specification_id"],
                        rear_axle_rating_kg=10_110)
    bay_a = create_plant_bay(api, name="Bay A", max_concurrent_visitors=8)
    bay_b = create_plant_bay(api, name="Bay B", max_concurrent_visitors=8)
    line = create_slot_line(api, supplier_name="Freightline Custom Chassis",
                            component_type="CHASSIS", total_slot_count=2)

    twins = {}
    for key, unit, bay, pre_day, mid_day, window in (
        ("a", unit_a, bay_a, "2026-08-10", "2026-09-20",
         ("2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z")),
        ("b", unit_b, bay_b, "2026-08-11", "2026-09-21",
         ("2026-09-22T00:00:00Z", "2026-10-06T00:00:00Z")),
    ):
        pre_trip = schedule_trip(api, unit["id"], bay["id"],
                                 trip_type="PRE_CONSTRUCTION",
                                 scheduled_start=f"{pre_day}T08:00:00Z",
                                 scheduled_end=f"{pre_day}T16:00:00Z",
                                 committee_size=4)
        hold_trip(api, pre_trip["id"])
        reservation = reserve_slot(api, ctx["program_id"], line["id"],
                                   unit_order_id=unit["id"],
                                   slot_start_date=window[0],
                                   slot_end_date=window[1])
        confirm_reservation(api, reservation["id"])
        validate_success(api.start_production(unit["id"], admin))
        mid_trip = schedule_trip(api, unit["id"], bay["id"],
                                 trip_type="MID_CONSTRUCTION",
                                 scheduled_start=f"{mid_day}T08:00:00Z",
                                 scheduled_end=f"{mid_day}T16:00:00Z",
                                 committee_size=4)
        hold_trip(api, mid_trip["id"])
        test = submit_certification_test(api, unit["id"],
                                        test_standard="NFPA_1901")
        record_test_result(api, test["id"])
        change_order = raise_change_order(api, unit["id"], mid_trip["id"],
                                          ctx["program_id"],
                                          line_items=SMALL_LINE)
        twins[key] = {"unit_id": unit["id"], "mid_trip_id": mid_trip["id"],
                      "change_order_id": change_order["id"]}
    ctx["twins"] = twins
    return ctx


def test_the_amendability_rung_outranks_the_fiscal_rung_on_approval(api,
                                                                   admin_headers):
    """A delivered unit reports rung 13, not the rung 52 it also breaks.

    PRD 2.9 rung 13: "The unit is still amendable, meaning its `build_status` is
    none of `DELIVERED`, `WARRANTY_ACTIVE` or `CANCELLED` — otherwise
    `ERR_UNIT_NOT_AMENDABLE`, 409. Applies to all six change-order operations:
    raise, submit, negotiate, revise, approve and rescind."
    PRD 2.9 rung 52: "Fiscal, and last but one: the program's resulting
    `committed_cents` is at most its `contract_ceiling_cents` — otherwise
    `ERR_CONTRACT_CEILING_EXCEEDED`, 409. Applies to unit-order award and to
    change-order approval."
    PRD 2.9: "The first rule that fails determines the response, nothing is
    persisted, and no lower rung is consulted."

    Design: Difficulty/priority_pair_validation_conflict/unit_not_amendable_state_check_preempts_contract_ceiling_check
    """
    ctx = _delivered_unit_with_a_submitted_amendment(api)
    assert_unit_dimensions(ctx["unit"], build_status=BuildStatus.DELIVERED.value)

    validate_error(
        api.approve_change_order(ctx["change_order_id"],
                                 make_purchasing_officer_headers("po-releaser")),
        ErrorCode.ERR_UNIT_NOT_AMENDABLE,
        409,
    )

    untouched = read_change_order(api, ctx["change_order_id"])
    assert untouched["status"] == ChangeOrderStatus.SUBMITTED.value, untouched
    assert untouched["approved_by_user_id"] is None, untouched
    assert untouched["applied_at"] is None, untouched

    unit = read_unit(api, ctx["unit_id"])
    assert_unit_money(unit, price_cents=68_276_000, change_order_total_cents=0,
                      open_change_order_count=1)
    assert_unit_dimensions(unit, build_status=BuildStatus.DELIVERED.value)
    assert_program_ledger(read_program(api, ctx["program_id"]), 68_276_000,
                          ProgramStatus.ACTIVE.value, None)


def test_the_same_amendment_on_an_amendable_unit_reaches_the_fiscal_rung(
        api, admin_headers):
    """The lower rung is genuinely violated: 188,276,000 against 150,000,000.

    PRD 2.10: "A write whose resulting `committed_cents` would exceed the hard
    ceiling is rejected outright with `ERR_CONTRACT_CEILING_EXCEEDED` and nothing
    is persisted — the program's `status` is left exactly as it was."
    PRD 2.9 rung 52: "Fiscal, and last but one: the program's resulting
    `committed_cents` is at most its `contract_ceiling_cents` — otherwise
    `ERR_CONTRACT_CEILING_EXCEEDED`, 409. Applies to unit-order award and to
    change-order approval."

    Design: Difficulty/priority_pair_validation_conflict/unit_not_amendable_state_check_preempts_contract_ceiling_check
    """
    ctx = _amendable_unit_with_a_submitted_amendment(api)
    assert_unit_dimensions(ctx["unit"],
                           build_status=BuildStatus.PRE_CON_HELD.value)

    validate_error(
        api.approve_change_order(ctx["change_order_id"],
                                 make_purchasing_officer_headers("po-releaser")),
        ErrorCode.ERR_CONTRACT_CEILING_EXCEEDED,
        409,
    )

    untouched = read_change_order(api, ctx["change_order_id"])
    assert untouched["status"] == ChangeOrderStatus.SUBMITTED.value, untouched
    assert untouched["approved_by_user_id"] is None, untouched
    assert untouched["applied_at"] is None, untouched

    assert_unit_money(read_unit(api, ctx["unit_id"]), price_cents=68_276_000,
                      change_order_total_cents=0, open_change_order_count=1)
    assert_program_ledger(read_program(api, ctx["program_id"]), 68_276_000,
                          ProgramStatus.ACTIVE.value, None)


def test_the_axle_safety_rung_outranks_the_open_amendment_rung(api, admin_headers):
    """One kilogram over the rear rating reports rung 31, not rung 34.

    PRD 2.9: "First, on final inspection the axle-overload check sits *above* the
    certification check, which sits above the open-change-order check: a unit that
    is simultaneously overloaded, uncertified and carrying an open change order
    reports `ERR_AXLE_LOAD_EXCEEDED`, not the other two."
    PRD 2.9 rung 31: "Safety: the unit's `weight_status` is `WITHIN_LIMITS` —
    otherwise `ERR_AXLE_LOAD_EXCEEDED`, 422. Applies to final inspection and to
    delivery."
    PRD 2.9 rung 34: "The unit's `open_change_order_count` is 0, meaning no draft,
    submitted or in-negotiation change order is outstanding against it — otherwise
    `ERR_OPEN_CHANGE_ORDERS`, 409. Applies to final inspection and to unit
    cancellation."

    Design: Difficulty/priority_pair_validation_conflict/axle_safety_check_preempts_open_change_order_check
    """
    ctx = _twin_certified_units(api)
    unit_a = read_unit(api, ctx["twins"]["a"]["unit_id"])
    assert_axle_loads(unit_a, front_kg=5_810, rear_kg=10_110, gross_kg=15_920,
                      weight_status=WeightStatus.OVER_REAR.value)
    assert unit_a["rear_axle_rating_kg"] == 10_109, unit_a
    assert_unit_money(unit_a, open_change_order_count=1)

    validate_error(
        api.final_inspection(ctx["twins"]["a"]["unit_id"], admin_headers),
        ErrorCode.ERR_AXLE_LOAD_EXCEEDED,
        422,
    )

    assert_unit_dimensions(
        read_unit(api, ctx["twins"]["a"]["unit_id"]),
        build_status=BuildStatus.MID_CON_HELD.value,
        certification_status=CertificationStatus.CERTIFIED.value)
    still_draft = read_change_order(api, ctx["twins"]["a"]["change_order_id"])
    assert still_draft["status"] == ChangeOrderStatus.DRAFT.value, still_draft
    assert_program_ledger(read_program(api, ctx["program_id"]), 136_552_000,
                          ProgramStatus.ACTIVE.value, None)


def test_the_identical_twin_one_kilogram_wider_reaches_the_open_amendment_rung(
        api, admin_headers):
    """A rear load exactly on its rating is compliant, so rung 34 fires alone.

    PRD 3.5: "Every comparison is strict, so a load exactly equal to its rating
    is `WITHIN_LIMITS`".
    PRD 3.9: "the unit's `weight_status` must be `WITHIN_LIMITS` (otherwise
    `ERR_AXLE_LOAD_EXCEEDED`), its `certification_status` must be `CERTIFIED`
    (otherwise `ERR_CERTIFICATION_NOT_PASSED`), and its `open_change_order_count`
    must be 0 (otherwise `ERR_OPEN_CHANGE_ORDERS`)."

    Design: Difficulty/priority_pair_validation_conflict/axle_safety_check_preempts_open_change_order_check
    """
    ctx = _twin_certified_units(api)
    unit_b = read_unit(api, ctx["twins"]["b"]["unit_id"])
    assert_axle_loads(unit_b, front_kg=5_810, rear_kg=10_110, gross_kg=15_920,
                      weight_status=WeightStatus.WITHIN_LIMITS.value)
    assert unit_b["rear_axle_rating_kg"] == 10_110, unit_b
    assert_unit_money(unit_b, open_change_order_count=1)

    validate_error(
        api.final_inspection(ctx["twins"]["b"]["unit_id"], admin_headers),
        ErrorCode.ERR_OPEN_CHANGE_ORDERS,
        409,
    )

    assert_unit_dimensions(
        read_unit(api, ctx["twins"]["b"]["unit_id"]),
        build_status=BuildStatus.MID_CON_HELD.value,
        certification_status=CertificationStatus.CERTIFIED.value)
    still_draft = read_change_order(api, ctx["twins"]["b"]["change_order_id"])
    assert still_draft["status"] == ChangeOrderStatus.DRAFT.value, still_draft
    assert_program_ledger(read_program(api, ctx["program_id"]), 136_552_000,
                          ProgramStatus.ACTIVE.value, None)

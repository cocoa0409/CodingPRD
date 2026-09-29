"""Two state machines that loop instead of marching forward.

The certification dimension cycles through a failure and a retest while the
build dimension stays pinned, and a change order can go round the negotiation
loop as often as purchasing likes — but only ever re-entered through negotiate.
"""

from test_helpers import (
    BuildStatus,
    CertificationStatus,
    CertificationTestStatus,
    ChangeOrderStatus,
    ErrorCode,
    LongLeadStatus,
    ProgramStatus,
    TestResult,
    assert_program_ledger,
    assert_unit_dimensions,
    assert_unit_money,
    build_line_item,
    create_plant_bay,
    hold_trip,
    make_customer_committee_rep_headers,
    make_third_party_tester_headers,
    negotiate_change_order,
    raise_change_order,
    read_certification_test,
    read_change_order,
    read_program,
    read_unit,
    revise_change_order,
    schedule_trip,
    setup_awarded_unit,
    setup_unit_at_stage,
    submit_certification_test,
    submit_change_order,
    record_test_result,
    validate_error,
)


PUMP_CLAUSE = [
    {"clause_code": "C1", "category": "PUMP",
     "requirement_text": "1500 gpm single stage pump",
     "mandatory": True, "is_restrictive": False},
]

PROGRAM = {"name": "Metro FD 2024-2029 Apparatus",
           "agency_name": "Metro Fire District", "max_option_units": 3}


def _mid_con_held_unit(api):
    return setup_unit_at_stage(
        api, "MID_CON_HELD",
        program_overrides=dict(PROGRAM),
        clauses=PUMP_CLAUSE,
        bay_overrides={"name": "Bay A", "max_concurrent_visitors": 10},
        pre_trip_overrides={"scheduled_start": "2026-08-10T08:00:00Z",
                            "scheduled_end": "2026-08-10T16:00:00Z"},
        slot_line_overrides={"supplier_name": "Freightline Custom Chassis",
                             "total_slot_count": 2},
    )


def _submitted_change_order(api):
    """A PRE_CON_HELD pumper carrying one SUBMITTED change order of 1,000,000."""
    ctx = setup_awarded_unit(api, program_overrides=dict(PROGRAM),
                             clauses=PUMP_CLAUSE)
    bay = create_plant_bay(api, name="Bay A", max_concurrent_visitors=10)
    trip = schedule_trip(api, ctx["unit_id"], bay["id"],
                         trip_type="PRE_CONSTRUCTION",
                         scheduled_start="2026-08-10T08:00:00Z",
                         scheduled_end="2026-08-10T16:00:00Z", committee_size=4)
    hold_trip(api, trip["id"])
    ctx["trip_id"] = trip["id"]
    change_order = raise_change_order(
        api, ctx["unit_id"], trip["id"], ctx["program_id"],
        line_items=[build_line_item(description="Hose bed divider", quantity=1,
                                    unit_cost_cents=1_000_000, markup_pct=0.0,
                                    is_taxable=False)],
    )
    assert change_order["price_delta_cents"] == 1_000_000, change_order
    ctx["change_order"] = submit_change_order(api, change_order["id"],
                                             ctx["program_id"])
    ctx["change_order_id"] = change_order["id"]
    return ctx


def test_a_failed_test_and_a_retest_walk_the_certification_dimension_in_a_circle(
        api, admin_headers):
    """NOT_SUBMITTED to IN_TESTING to REJECTED_TESTING to IN_TESTING to CERTIFIED.

    PRD 3.9: "When the submission comes after a failure, the same operation moves
    the unit `REJECTED_TESTING` to `IN_TESTING` and creates another test row; this
    retest cycle may repeat, and `build_status` is untouched throughout."
    PRD 3.9: "On a `FAIL` the test moves `SUBMITTED` to the terminal `FAILED`
    state with `result` set to `FAIL`, and the unit's `certification_status` moves
    `IN_TESTING` to `REJECTED_TESTING`."

    Design: Difficulty/non_linear_state_machine/certification_retest_cycle_leaves_build_dimension_frozen
    """
    ctx = _mid_con_held_unit(api)
    assert_unit_dimensions(ctx["unit"],
                           certification_status=CertificationStatus.NOT_SUBMITTED.value)

    first = submit_certification_test(api, ctx["unit_id"],
                                      test_standard="NFPA_1901")
    assert first["status"] == CertificationTestStatus.SUBMITTED.value, first
    assert first["result"] is None, first
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           certification_status=CertificationStatus.IN_TESTING.value)

    failed = record_test_result(api, first["id"], result="FAIL",
                                signed_by_user_id="eng-2")
    assert failed["status"] == CertificationTestStatus.FAILED.value, failed
    assert failed["result"] == TestResult.FAIL.value, failed
    assert_unit_dimensions(
        read_unit(api, ctx["unit_id"]),
        certification_status=CertificationStatus.REJECTED_TESTING.value)

    second = submit_certification_test(api, ctx["unit_id"],
                                      test_standard="NFPA_1901")
    assert second["status"] == CertificationTestStatus.SUBMITTED.value, second
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           certification_status=CertificationStatus.IN_TESTING.value)

    passed = record_test_result(api, second["id"], result="PASS",
                                signed_by_user_id="eng-2")
    assert passed["status"] == CertificationTestStatus.PASSED.value, passed
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           certification_status=CertificationStatus.CERTIFIED.value)

    stale = read_certification_test(api, first["id"])
    assert stale["status"] == CertificationTestStatus.FAILED.value, stale
    assert stale["invalidated_reason"] is None, stale


def test_the_build_dimension_never_moves_while_certification_loops(api,
                                                                  admin_headers):
    """Four certification hops leave build and long-lead exactly where they were.

    PRD 3.9: "this retest cycle may repeat, and `build_status` is untouched
    throughout."
    PRD 3.9: "The unit's `certification_status` must be `NOT_SUBMITTED` or
    `REJECTED_TESTING`, the two states from which a fresh test is meaningful; a
    submission while the unit is already `IN_TESTING` or already `CERTIFIED` is
    refused with `ERR_INVALID_CERTIFICATION_STATE`."

    Design: Difficulty/non_linear_state_machine/certification_retest_cycle_leaves_build_dimension_frozen
    """
    ctx = _mid_con_held_unit(api)
    expected = dict(build_status=BuildStatus.MID_CON_HELD.value,
                    long_lead_status=LongLeadStatus.CONFIRMED.value,
                    spec_drift_flag=False)

    first = submit_certification_test(api, ctx["unit_id"],
                                      test_standard="NFPA_1901")
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]), **expected)
    record_test_result(api, first["id"], result="FAIL", signed_by_user_id="eng-2")
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]), **expected)
    second = submit_certification_test(api, ctx["unit_id"],
                                      test_standard="NFPA_1901")
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]), **expected)
    record_test_result(api, second["id"], result="PASS", signed_by_user_id="eng-2")
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]), **expected)

    validate_error(
        api.create_certification_test(
            {"unit_order_id": ctx["unit_id"], "test_standard": "NFPA_1901"},
            make_third_party_tester_headers(),
        ),
        ErrorCode.ERR_INVALID_CERTIFICATION_STATE,
        409,
    )
    assert_unit_dimensions(
        read_unit(api, ctx["unit_id"]),
        certification_status=CertificationStatus.CERTIFIED.value, **expected)


def test_each_trip_round_the_negotiation_loop_reprices_from_scratch(api,
                                                                   admin_headers):
    """Two revisions, two fresh prices and a revision_count that counts them.

    PRD 3.8: "The committee then revises it, taking `IN_NEGOTIATION` back to
    `SUBMITTED` with a fresh `line_items` array and fresh `weight_delta_front_kg`
    and `weight_delta_rear_kg` values that wholly replace the previous ones; the
    markup cap is re-checked over the new lines, `price_delta_cents` is recomputed
    from scratch, and `revision_count` increases by one."

    Design: Difficulty/non_linear_state_machine/change_order_negotiation_loop_increments_revision_count
    """
    ctx = _submitted_change_order(api)
    assert ctx["change_order"]["status"] == ChangeOrderStatus.SUBMITTED.value
    assert ctx["change_order"]["revision_count"] == 0, ctx["change_order"]

    returned = negotiate_change_order(api, ctx["change_order_id"])
    assert returned["status"] == ChangeOrderStatus.IN_NEGOTIATION.value, returned

    first_revision = revise_change_order(
        api, ctx["change_order_id"], ctx["program_id"],
        line_items=[build_line_item(description="Hose bed divider, revised",
                                    quantity=2, unit_cost_cents=500_000,
                                    markup_pct=10.0, is_taxable=True)],
    )
    assert first_revision["status"] == ChangeOrderStatus.SUBMITTED.value, \
        first_revision
    assert first_revision["revision_count"] == 1, first_revision
    assert first_revision["price_delta_cents"] == 1_171_500, first_revision

    negotiate_change_order(api, ctx["change_order_id"])
    second_revision = revise_change_order(
        api, ctx["change_order_id"], ctx["program_id"],
        line_items=[build_line_item(description="Hose bed divider, final scope",
                                    quantity=1, unit_cost_cents=250_000,
                                    markup_pct=22.0, is_taxable=False)],
    )
    assert second_revision["status"] == ChangeOrderStatus.SUBMITTED.value, \
        second_revision
    assert second_revision["revision_count"] == 2, second_revision
    assert second_revision["price_delta_cents"] == 305_000, second_revision


def test_the_loop_is_re_enterable_only_through_negotiate(api, admin_headers):
    """A revise from SUBMITTED is refused, and the loop moves no money at all.

    PRD 3.8: "The `SUBMITTED` to `IN_NEGOTIATION` to `SUBMITTED` loop may repeat
    without bound, and `revision_count` is the record of how many times it went
    round."
    PRD 3.8: "The unit's `change_order_total_cents` is rebuilt as the sum of the
    `price_delta_cents` of every change order of that unit whose `status` is
    `APPROVED`".

    Design: Difficulty/non_linear_state_machine/change_order_negotiation_loop_increments_revision_count
    """
    ctx = _submitted_change_order(api)
    committee = make_customer_committee_rep_headers(ctx["program_id"])

    validate_error(
        api.revise_change_order(
            ctx["change_order_id"],
            {"line_items": [build_line_item(quantity=1, unit_cost_cents=250_000,
                                            markup_pct=0.0, is_taxable=False)],
             "weight_delta_front_kg": 0, "weight_delta_rear_kg": 0},
            committee,
        ),
        ErrorCode.ERR_INVALID_CHANGE_ORDER_STATE,
        409,
    )
    unchanged = read_change_order(api, ctx["change_order_id"])
    assert unchanged["status"] == ChangeOrderStatus.SUBMITTED.value, unchanged
    assert unchanged["revision_count"] == 0, unchanged
    assert unchanged["price_delta_cents"] == 1_000_000, unchanged

    negotiate_change_order(api, ctx["change_order_id"])
    revise_change_order(
        api, ctx["change_order_id"], ctx["program_id"],
        line_items=[build_line_item(description="Hose bed divider, revised",
                                    quantity=2, unit_cost_cents=500_000,
                                    markup_pct=10.0, is_taxable=True)],
    )

    unit = read_unit(api, ctx["unit_id"])
    assert_unit_money(unit, price_cents=68_276_000, change_order_total_cents=0,
                      open_change_order_count=1)
    assert_unit_dimensions(unit, build_status=BuildStatus.PRE_CON_HELD.value)
    assert_program_ledger(read_program(api, ctx["program_id"]), 68_276_000,
                          ProgramStatus.ACTIVE.value, None)

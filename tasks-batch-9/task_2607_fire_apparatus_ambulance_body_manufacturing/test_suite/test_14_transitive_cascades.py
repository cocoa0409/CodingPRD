"""The two chained cascades, hop by hop.

A change-order approval walks money, weight, certification, the build dimension
and the final trip in that causal order; a successor release walks the
predecessor, its pending entries, the drift flag and the certification along an
entirely different axis, and never touches the build dimension at all.
"""

from test_helpers import (
    assert_clock_stamp,
    BuildStatus,
    CertificationStatus,
    CertificationTestStatus,
    ChangeOrderStatus,
    ComplianceDisposition,
    ErrorCode,
    InvalidatedReason,
    ProgramStatus,
    SpecificationStatus,
    TripStatus,
    WeightStatus,
    add_clause,
    approve_change_order,
    assert_axle_loads,
    assert_program_ledger,
    assert_unit_dimensions,
    assert_unit_money,
    build_line_item,
    create_draft_specification,
    file_compliance_entry,
    make_purchasing_officer_headers,
    raise_change_order,
    read_certification_test,
    read_program,
    read_trip,
    read_unit,
    schedule_trip,
    setup_unit_at_stage,
    submit_change_order,
    submit_specification_for_review,
    validate_error,
    validate_success,
)


PUMP_CLAUSE = [
    {"clause_code": "C1", "category": "PUMP",
     "requirement_text": "1500 gpm single stage pump",
     "mandatory": True, "is_restrictive": False},
]

PROGRAM = {"name": "Metro FD 2024-2029 Apparatus",
           "agency_name": "Metro Fire District", "max_option_units": 3}


def _final_inspected_with_pending_amendment(api):
    """A certified, final-inspected pumper with a one-kilogram amendment waiting.

    The pumper's rear axle load sits exactly on its 10,110 kg rating, so a single
    kilogram of approved rear delta is the whole difference between
    ``WITHIN_LIMITS`` and ``OVER_REAR``.
    """
    ctx = setup_unit_at_stage(
        api, "FINAL_INSPECTED",
        program_overrides=dict(PROGRAM),
        clauses=PUMP_CLAUSE,
        bay_overrides={"name": "Bay A", "max_concurrent_visitors": 10},
        pre_trip_overrides={"scheduled_start": "2026-08-10T08:00:00Z",
                            "scheduled_end": "2026-08-10T16:00:00Z"},
        slot_line_overrides={"supplier_name": "Freightline Custom Chassis",
                             "total_slot_count": 2},
    )
    final_trip = schedule_trip(api, ctx["unit_id"], ctx["bay_id"],
                               trip_type="FINAL",
                               scheduled_start="2026-10-05T08:00:00Z",
                               scheduled_end="2026-10-05T16:00:00Z",
                               committee_size=4)
    ctx["final_trip_id"] = final_trip["id"]
    change_order = raise_change_order(
        api, ctx["unit_id"], ctx["mid_trip_id"], ctx["program_id"],
        line_items=[build_line_item(description="Rear ladder rack", quantity=1,
                                    unit_cost_cents=500_000, markup_pct=0.0,
                                    is_taxable=False)],
        weight_delta_front_kg=0, weight_delta_rear_kg=1,
    )
    submit_change_order(api, change_order["id"], ctx["program_id"])
    ctx["change_order_id"] = change_order["id"]
    return ctx


def _superseding_revision(api):
    """Rev A released and pinned by a certified unit, rev B waiting to supersede."""
    ctx = setup_unit_at_stage(
        api, "CERTIFIED",
        program_overrides=dict(PROGRAM),
        clauses=PUMP_CLAUSE,
        bay_overrides={"name": "Bay A", "max_concurrent_visitors": 10},
        pre_trip_overrides={"scheduled_start": "2026-08-10T08:00:00Z",
                            "scheduled_end": "2026-08-10T16:00:00Z"},
        slot_line_overrides={"supplier_name": "Freightline Custom Chassis",
                             "total_slot_count": 2},
    )
    successor = create_draft_specification(api, ctx["program_id"],
                                          title="Pumper spec rev B",
                                          supersedes_spec_id=ctx["specification_id"])
    clause = add_clause(api, successor["id"], clause_code="C1", category="PUMP",
                        requirement_text="1750 gpm two stage pump",
                        mandatory=True, is_restrictive=False)
    file_compliance_entry(api, successor["id"], clause["id"], response="COMPLY")
    submit_specification_for_review(api, successor["id"])
    ctx["successor_id"] = successor["id"]
    return ctx


def test_approval_rebuilds_the_money_and_the_weight_and_tears_up_the_certificate(
        api, admin_headers):
    """Hops 1 and 2: one kilogram of rear delta invalidates a passed certificate.

    PRD 3.8: "The unit's `change_order_total_cents` is rebuilt as the sum of the
    `price_delta_cents` of every change order of that unit whose `status` is
    `APPROVED`... And the unit's axle loads are re-run over the cumulative
    approved weight deltas, refreshing `front_axle_load_kg`, `rear_axle_load_kg`,
    `gross_weight_kg` and `weight_status`."
    PRD 3.8: "If the rebuilt `weight_status` is anything other than
    `WITHIN_LIMITS` and the unit's `certification_status` is `CERTIFIED`, that
    certification is reset `CERTIFIED` to `NOT_SUBMITTED`, and every certification
    test of the unit whose `status` is `PASSED` moves `PASSED` to `INVALIDATED` in
    ascending `created_at` order with `invalidated_reason` set to
    `WEIGHT_STATUS_CHANGE`."

    Design: Difficulty/transitive_cascade/change_order_approval_cascades_weight_certification_build_and_trip
    """
    ctx = _final_inspected_with_pending_amendment(api)
    assert_axle_loads(ctx["unit"], front_kg=5_810, rear_kg=10_110, gross_kg=15_920,
                      weight_status=WeightStatus.WITHIN_LIMITS.value)

    approved = approve_change_order(api, ctx["change_order_id"],
                                    officer="po-releaser")
    assert approved["status"] == ChangeOrderStatus.APPROVED.value, approved
    assert approved["approved_by_user_id"] == "po-releaser", approved
    assert_clock_stamp(approved["applied_at"], "2026-08-01T00:00:00Z")

    unit = read_unit(api, ctx["unit_id"])
    assert_unit_money(unit, price_cents=68_276_000, change_order_total_cents=500_000,
                      open_change_order_count=0)
    assert_axle_loads(unit, front_kg=5_810, rear_kg=10_111, gross_kg=15_921,
                      weight_status=WeightStatus.OVER_REAR.value)
    assert_unit_dimensions(
        unit, certification_status=CertificationStatus.NOT_SUBMITTED.value)

    torn_up = read_certification_test(api, ctx["certification_test_id"])
    assert torn_up["status"] == CertificationTestStatus.INVALIDATED.value, torn_up
    assert torn_up["invalidated_reason"] == \
        InvalidatedReason.WEIGHT_STATUS_CHANGE.value, torn_up


def test_the_certification_reset_drags_the_build_back_and_cancels_the_final_trip(
        api, admin_headers):
    """Hops 3 and 4 plus the ledger sync, all inside the approving request.

    PRD 3.8: "If the unit's `build_status` was `FINAL_INSPECTED` at the moment its
    certification was reset, it reverts `FINAL_INSPECTED` to `IN_PRODUCTION`. This
    is the one place in the system where the build dimension moves backwards".
    PRD 3.8: "Every inspection trip of that unit whose `trip_type` is `FINAL` and
    whose `status` is `SCHEDULED` moves `SCHEDULED` to `CANCELLED`, in ascending
    `created_at` order, freeing each trip's `committee_size` from its bay."
    PRD 3.8: "The program's `committed_cents` is recomputed and its `version`
    increments".

    Design: Difficulty/transitive_cascade/change_order_approval_cascades_weight_certification_build_and_trip
    """
    ctx = _final_inspected_with_pending_amendment(api)
    assert_unit_dimensions(ctx["unit"],
                           build_status=BuildStatus.FINAL_INSPECTED.value)

    approve_change_order(api, ctx["change_order_id"], officer="po-releaser")

    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           build_status=BuildStatus.IN_PRODUCTION.value)
    assert read_trip(api, ctx["final_trip_id"])["status"] == \
        TripStatus.CANCELLED.value
    assert read_trip(api, ctx["mid_trip_id"])["status"] == TripStatus.HELD.value

    assert_program_ledger(read_program(api, ctx["program_id"]), 68_776_000,
                          ProgramStatus.ACTIVE.value, None)
    assert_unit_money(read_unit(api, ctx["unit_id"]), price_cents=68_276_000)


def test_a_successor_release_supersedes_voids_and_drifts_in_one_chain(api,
                                                                     admin_headers):
    """Hops 1 to 3: SUPERSEDED, VOID, the drift flag and an invalidated certificate.

    PRD 3.4: "The first hop moves the predecessor from `RELEASED` to the terminal
    `SUPERSEDED` state and increments its `version`. As part of that same hop,
    every compliance matrix entry belonging to the predecessor whose `disposition`
    is still `PENDING` moves to `VOID`".
    PRD 3.4: "a unit whose `spec_drift_flag` has just become true and whose
    `certification_status` is `CERTIFIED` has that certification reset from
    `CERTIFIED` back to `NOT_SUBMITTED`, and every certification test of that unit
    whose `status` is `PASSED` moves `PASSED` to `INVALIDATED`... with
    `invalidated_reason` set to `SPEC_SUPERSEDED`."

    Design: Difficulty/transitive_cascade/specification_supersede_cascades_void_drift_and_certification
    """
    ctx = _superseding_revision(api)

    released = validate_success(
        api.release_specification(ctx["successor_id"],
                                  make_purchasing_officer_headers("po-releaser"))
    )
    assert released["status"] == SpecificationStatus.RELEASED.value, released
    assert released["released_by_user_id"] == "po-releaser", released

    predecessor = validate_success(
        api.get_specification(ctx["specification_id"], admin_headers)
    )
    assert predecessor["status"] == SpecificationStatus.SUPERSEDED.value, predecessor
    voided = validate_success(
        api.get_compliance_entry(ctx["entry_ids"][0], admin_headers)
    )
    assert voided["disposition"] == ComplianceDisposition.VOID.value, voided

    unit = read_unit(api, ctx["unit_id"])
    assert_unit_dimensions(
        unit, spec_drift_flag=True,
        certification_status=CertificationStatus.NOT_SUBMITTED.value)
    assert unit["specification_id"] == ctx["specification_id"], unit

    invalidated = read_certification_test(api, ctx["certification_test_id"])
    assert invalidated["status"] == CertificationTestStatus.INVALIDATED.value, \
        invalidated
    assert invalidated["invalidated_reason"] == \
        InvalidatedReason.SPEC_SUPERSEDED.value, invalidated


def test_the_supersession_cascade_is_fiscally_and_physically_silent(api,
                                                                   admin_headers):
    """The build dimension, the price and the ledger all sit still.

    PRD 3.4: "Note that this third hop resets the certification dimension only; it
    does not itself drag the build dimension backwards, because the build revert
    is a consequence of a *weight* reset rather than of a specification reset."
    PRD 3.4: "that predecessor must itself be `RELEASED` (otherwise
    `ERR_PREDECESSOR_NOT_RELEASED`)".

    Design: Difficulty/transitive_cascade/specification_supersede_cascades_void_drift_and_certification
    """
    ctx = _superseding_revision(api)
    validate_success(
        api.release_specification(ctx["successor_id"],
                                  make_purchasing_officer_headers("po-releaser"))
    )

    unit = read_unit(api, ctx["unit_id"])
    assert_unit_dimensions(unit, build_status=BuildStatus.MID_CON_HELD.value)
    assert_unit_money(unit, price_cents=68_276_000, change_order_total_cents=0)
    assert_program_ledger(read_program(api, ctx["program_id"]), 68_276_000,
                          ProgramStatus.ACTIVE.value, None)

    late = create_draft_specification(api, ctx["program_id"],
                                     title="Pumper spec rev C",
                                     supersedes_spec_id=ctx["specification_id"])
    clause = add_clause(api, late["id"], clause_code="C1", category="PUMP",
                        requirement_text="2000 gpm two stage pump",
                        mandatory=True, is_restrictive=False)
    file_compliance_entry(api, late["id"], clause["id"], response="COMPLY")
    submit_specification_for_review(api, late["id"])

    validate_error(
        api.release_specification(late["id"],
                                  make_purchasing_officer_headers("po-releaser")),
        ErrorCode.ERR_PREDECESSOR_NOT_RELEASED,
        409,
    )
    still_superseded = validate_success(
        api.get_specification(ctx["specification_id"], admin_headers)
    )
    assert still_superseded["status"] == SpecificationStatus.SUPERSEDED.value, \
        still_superseded

"""The money and score arithmetic: per-line rounding, bond tiers, ratios.

Covers the change-order per-line rounding order and its inclusive markup cap,
the option premium against the third bond tier, the input-set filtering that
separates the two readiness scores, the mandatory-only restrictive ratio, the
live committed-money aggregation, slot exhaustion as a pure count check, and
the calendar clamp on the warranty term.
"""

from test_helpers import (
    BuildStatus,
    ChangeOrderStatus,
    ComplianceDisposition,
    ComplianceResponse,
    ErrorCode,
    ProgramStatus,
    ReservationStatus,
    WarrantyStatus,
    add_clause,
    assert_price_reconciliation,
    assert_slot_occupancy,
    assert_spec_scores,
    assert_unit_money,
    assert_warranty_window,
    award_unit,
    build_line_item,
    build_reservation_payload,
    create_active_program,
    create_draft_specification,
    create_program,
    create_released_specification,
    create_slot_line,
    dispose_entry,
    file_compliance_entry,
    fresh_slot_line_version,
    fresh_unit_version,
    make_customer_committee_rep_headers,
    make_program_admin_headers,
    make_purchasing_officer_headers,
    raise_change_order,
    read_program,
    read_reservation,
    read_slot_line,
    read_unit,
    release_reservation,
    reserve_slot,
    setup_program_with_released_spec,
    setup_unit_at_stage,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_change_order_lines_round_individually_and_the_markup_cap_is_inclusive(
    api, admin_headers
):
    """A two-line order prices to 1,599,300 and 22.01 percent markup is refused.

    PRD 3.8: "each line item is rounded on its own and the rounded line values
    are then summed. Summing unrounded line values and rounding once at the end
    produces a different figure and is wrong."
    PRD 3.8: "computes the line tax as the marked-up line value multiplied by
    the tax rate of six and a half percent".
    PRD 3.8: "The substance of a change order is its `line_items`, an ordered
    array of between 1 and 12 entries."
    PRD 2.9 rung 47: "Every change-order line item's `markup_pct` is at most
    22.0 — otherwise `ERR_MARKUP_CAP_EXCEEDED`, 422."

    Design: Corner/calculations/change_order_line_markup_tax_and_cap_boundary
    """
    ctx = setup_unit_at_stage(api, "MID_CON_HELD",
                             program_overrides={"name": "Markup program"})
    committee = make_customer_committee_rep_headers(ctx["program_id"])

    change_order = raise_change_order(
        api, ctx["unit_id"], ctx["mid_trip_id"], ctx["program_id"],
        line_items=[
            build_line_item(description="Stainless steel body upgrade", quantity=2,
                            unit_cost_cents=500_000, markup_pct=22.0,
                            is_taxable=True),
            build_line_item(description="Committee travel reimbursement", quantity=1,
                            unit_cost_cents=300_000, markup_pct=0.0,
                            is_taxable=False),
        ],
        weight_delta_front_kg=0,
        weight_delta_rear_kg=0,
    )
    assert change_order["price_delta_cents"] == 1_599_300, change_order
    assert change_order["status"] == ChangeOrderStatus.DRAFT.value, change_order
    assert change_order["revision_count"] == 0, change_order
    assert change_order["raised_by_user_id"] == ctx["program_id"], change_order
    assert change_order["applied_at"] is None, change_order

    assert_unit_money(read_unit(api, ctx["unit_id"]), change_order_total_cents=0,
                      open_change_order_count=1)

    over_cap_version = fresh_unit_version(api, ctx["unit_id"])
    validate_error(
        api.create_change_order(
            {
                "unit_order_id": ctx["unit_id"],
                "inspection_trip_id": ctx["mid_trip_id"],
                "line_items": [
                    build_line_item(description="Chrome package", quantity=1,
                                    unit_cost_cents=400_000, markup_pct=22.01,
                                    is_taxable=True),
                ],
                "weight_delta_front_kg": 0,
                "weight_delta_rear_kg": 0,
                "expected_unit_order_version": over_cap_version,
            },
            committee,
        ),
        ErrorCode.ERR_MARKUP_CAP_EXCEEDED,
        422,
    )

    validate_error(
        api.create_change_order(
            {
                "unit_order_id": ctx["unit_id"],
                "inspection_trip_id": ctx["mid_trip_id"],
                "line_items": [
                    build_line_item(description=f"L{n}", quantity=1,
                                    unit_cost_cents=100, markup_pct=0.0,
                                    is_taxable=False)
                    for n in range(1, 14)
                ],
                "weight_delta_front_kg": 0,
                "weight_delta_rear_kg": 0,
                "expected_unit_order_version": over_cap_version,
            },
            committee,
        ),
        ErrorCode.ERR_INVALID_REQUEST,
        400,
    )

    rows, meta = validate_paginated(
        api.list_change_orders(admin_headers, {"unit_order_id": ctx["unit_id"]})
    )
    assert meta["total_count"] == 1, meta
    assert [row["id"] for row in rows] == [change_order["id"]], rows
    assert_unit_money(read_unit(api, ctx["unit_id"]), open_change_order_count=1)


def test_an_option_unit_pays_the_premium_and_the_third_bond_tier(api):
    """The option premium lifts the subtotal past 90,000,000 into the 0.75 tier.

    PRD 3.5: "The option premium is three and a half percent of that escalated
    base, quantised to whole cents with round-half-up, when the unit's
    `option_unit` is true; it is 0 when `option_unit` is false."
    PRD 3.5: "a subtotal above that but at most 90,000,000 cents (900,000
    dollars) takes the second-tier rate of 1.00 percent; a subtotal above
    90,000,000 cents takes the third-tier rate of 0.75 percent."
    PRD 2.9 rung 48: "When `option_unit` is true, the program's
    `options_exercised_count` is strictly less than its `max_option_units` —
    otherwise `ERR_OPTION_LIMIT_EXCEEDED`, 409."

    Design: Corner/calculations/option_premium_and_tier_three_bond_rate_applied
    """
    program = create_active_program(
        api, name="Option program", base_year=2026,
        base_unit_price_cents=100_000_000, escalation_index_pct_per_year=4.0,
        max_option_units=1, contract_ceiling_cents=800_000_000,
    )
    spec = create_released_specification(
        api, program["id"], title="Aerial spec rev A",
        clauses=[{"clause_code": "C1", "category": "AERIAL",
                  "requirement_text": "105 ft rear mount aerial",
                  "mandatory": True, "is_restrictive": False}],
    )
    officer = make_purchasing_officer_headers("po-releaser")

    def award(**overrides):
        payload = {
            "program_id": program["id"],
            "specification_id": spec["specification_id"],
            "unit_type": "PUMPER",
            "award_year": 2026,
            "gvwr_kg": 17_000,
            "front_axle_rating_kg": 6_800,
            "rear_axle_rating_kg": 10_110,
            "base_curb_front_kg": 5_200,
            "base_curb_rear_kg": 7_000,
            "crew_seat_count": 4,
            "weight_calc_engineer_user_id": "eng-1",
        }
        payload.update(overrides)
        return api.create_unit_order(payload, officer)

    option_unit = validate_success(award(option_unit=True), 201)
    assert option_unit["option_unit"] is True, option_unit
    assert option_unit["price_cents"] == 104_276_250, option_unit
    assert read_program(api, program["id"])["options_exercised_count"] == 1

    base_unit = validate_success(award(), 201)
    assert base_unit["option_unit"] is False, base_unit
    assert base_unit["price_cents"] == 100_750_000, base_unit

    ledger = read_program(api, program["id"])
    assert ledger["options_exercised_count"] == 1, ledger
    assert ledger["committed_cents"] == 205_026_250, ledger
    assert ledger["status"] == ProgramStatus.ACTIVE.value, ledger
    assert ledger["suspension_reason"] is None, ledger

    validate_error(award(option_unit=True),
                   ErrorCode.ERR_OPTION_LIMIT_EXCEEDED, 409)

    after = read_program(api, program["id"])
    assert after["options_exercised_count"] == 1, after
    assert after["committed_cents"] == 205_026_250, after
    _, meta = validate_paginated(
        api.list_unit_orders(officer, {"program_id": program["id"]})
    )
    assert meta["total_count"] == 2, meta


def test_the_two_readiness_scores_diverge_only_on_pending_exceptions(api,
                                                                    admin_headers):
    """Strict 50.00 against provisional 87.50, and a rejection collapses both.

    PRD 3.3: "Every clause of the specification carries a weight: a mandatory
    clause weighs 3 and an optional clause weighs 1."
    PRD 3.3: "For `compliance_score_provisional`, a clause's entry counts as
    compliant when its `response` is `COMPLY`, or when its `response` is
    `EXCEPTION` or `ALTERNATE` *and* its `disposition` is either `PENDING` or
    `ACCEPTED`; a still-pending exception counts as compliant."
    PRD 3.3: "rejecting a response removes the clause from both scores'
    compliant sets."

    Design: Corner/calculations/compliance_score_input_set_filtering_across_dispositions
    """
    program = create_program(api, name="Scoring program")
    spec = create_draft_specification(api, program["id"], title="Scoring spec")
    clause_one = add_clause(api, spec["id"], clause_code="C1", category="PUMP",
                            requirement_text="1500 gpm single stage pump",
                            mandatory=True, is_restrictive=False)
    clause_two = add_clause(api, spec["id"], clause_code="C2", category="AERIAL",
                            requirement_text="105 ft rear mount aerial",
                            mandatory=True, is_restrictive=False)
    clause_three = add_clause(api, spec["id"], clause_code="C3", category="PAINT",
                              requirement_text="Two tone paint scheme",
                              mandatory=False, is_restrictive=False)
    add_clause(api, spec["id"], clause_code="C4", category="ELECTRICAL",
               requirement_text="Scene lighting package", mandatory=False,
               is_restrictive=False)

    file_compliance_entry(api, spec["id"], clause_one["id"],
                          response=ComplianceResponse.COMPLY.value)
    pending = file_compliance_entry(
        api, spec["id"], clause_two["id"],
        response=ComplianceResponse.EXCEPTION.value,
        exception_text="Offering 100 ft rear mount",
    )
    alternate = file_compliance_entry(
        api, spec["id"], clause_three["id"],
        response=ComplianceResponse.ALTERNATE.value,
        exception_text="Single colour with reflective striping",
    )
    dispose_entry(api, alternate["id"],
                  disposition=ComplianceDisposition.ACCEPTED.value)

    before = validate_success(api.get_specification(spec["id"], admin_headers))
    assert_spec_scores(before, strict=50.00, provisional=87.50,
                       restrictive_ratio=0.00, clause_count=4,
                       mandatory_clause_count=2)

    rejected = dispose_entry(api, pending["id"],
                             disposition=ComplianceDisposition.REJECTED.value,
                             disposition_note="Aerial reach is a hard requirement")
    assert rejected["disposition"] == ComplianceDisposition.REJECTED.value, rejected

    after = validate_success(api.get_specification(spec["id"], admin_headers))
    assert_spec_scores(after, strict=50.00, provisional=50.00,
                       restrictive_ratio=0.00, clause_count=4,
                       mandatory_clause_count=2)
    assert after["status"] == "DRAFT", after


def test_the_restrictive_ratio_ignores_optional_clauses_entirely(api, admin_headers):
    """Two restrictive optional clauses score 0.00; one of three mandatory scores 33.33.

    PRD 3.2: "Take the specification's clauses whose `mandatory` flag is true.
    If there are none, `restrictive_clause_ratio_pct` is pinned to 0.00."
    PRD 3.2: "Optional clauses never enter the numerator or the denominator,
    even when they are themselves restrictive".
    PRD 2.6: "`compliance_score_strict`, `compliance_score_provisional` and
    `restrictive_clause_ratio_pct` are all two-decimal numbers."

    Design: Corner/calculations/restrictive_ratio_counts_mandatory_clauses_only
    """
    program = create_program(api, name="Ratio program")
    spec = create_draft_specification(api, program["id"], title="Ratio spec")

    def read_spec():
        return validate_success(api.get_specification(spec["id"], admin_headers))

    add_clause(api, spec["id"], clause_code="O1", category="PAINT",
               requirement_text="Factory paint booth finish only", mandatory=False,
               is_restrictive=True)
    add_clause(api, spec["id"], clause_code="O2", category="PAINT",
               requirement_text="Named brand clear coat", mandatory=False,
               is_restrictive=True)
    optional_only = read_spec()
    assert_spec_scores(optional_only, clause_count=2, mandatory_clause_count=0,
                       restrictive_ratio=0.00, strict=0.00, provisional=0.00)

    add_clause(api, spec["id"], clause_code="M1", category="PUMP",
               requirement_text="1500 gpm single stage pump", mandatory=True,
               is_restrictive=False)
    one_mandatory = read_spec()
    assert_spec_scores(one_mandatory, mandatory_clause_count=1,
                       restrictive_ratio=0.00)

    add_clause(api, spec["id"], clause_code="M2", category="CHASSIS",
               requirement_text="Named brand custom cab chassis only",
               mandatory=True, is_restrictive=True)
    two_mandatory = read_spec()
    assert_spec_scores(two_mandatory, mandatory_clause_count=2,
                       restrictive_ratio=50.00)

    add_clause(api, spec["id"], clause_code="M3", category="ELECTRICAL",
               requirement_text="Multiplex electrical system", mandatory=True,
               is_restrictive=False)
    three_mandatory = read_spec()
    assert_spec_scores(three_mandatory, clause_count=5, mandatory_clause_count=3,
                       restrictive_ratio=33.33, strict=0.00, provisional=0.00)


def test_cancelling_a_unit_decommits_its_money_from_the_ledger(api, admin_headers):
    """Two awards commit 136,552,000; one cancellation returns it to 68,276,000.

    PRD 2.10: "it is recomputed from the program's unit orders whenever anything
    that could change it happens, and its recomputed value is what gets
    persisted."
    PRD 2.10: "`CANCELLED` is the only build state excluded, which is exactly why
    cancelling a unit decommits its money."
    PRD 3.5: "`price_cents` is computed at award time under the
    *award-year-locked* pricing rule and then frozen for the life of the unit".

    Design: Corner/calculations/committed_cents_reverses_on_unit_cancellation
    """
    ctx = setup_program_with_released_spec(
        api, program_overrides={"name": "Ledger program"}
    )
    first = award_unit(api, ctx["program_id"], ctx["specification_id"])
    assert read_program(api, ctx["program_id"])["committed_cents"] == 68_276_000

    second = award_unit(api, ctx["program_id"], ctx["specification_id"])
    both = read_program(api, ctx["program_id"])
    assert both["committed_cents"] == 136_552_000, both
    assert both["status"] == ProgramStatus.ACTIVE.value, both
    assert both["suspension_reason"] is None, both

    cancelled = validate_success(
        api.cancel_unit_order(second["id"], admin_headers)
    )
    assert cancelled["build_status"] == BuildStatus.CANCELLED.value, cancelled
    assert cancelled["price_cents"] == 68_276_000, cancelled

    after = read_program(api, ctx["program_id"])
    assert after["committed_cents"] == 68_276_000, after

    survivor = read_unit(api, first["id"])
    assert survivor["price_cents"] == 68_276_000, survivor
    assert survivor["build_status"] == BuildStatus.SPEC_LOCKED.value, survivor


def test_a_full_slot_line_refuses_a_non_overlapping_window_on_the_count(api,
                                                                      admin_headers):
    """A one-slot line rejects a 2027 booking on availability, not on overlap.

    PRD 3.6: "`available_slot_count` is a conserved quantity that must never go
    negative: a booking attempted on a line whose `available_slot_count` has
    already reached 0 is refused with `ERR_SLOT_LINE_EXHAUSTED`, and the zero
    boundary is strict."
    PRD 3.6: "A `RELEASED` or `EXPIRED` reservation leaves the occupied set
    entirely, which is what makes release and expiry exactly compensating
    against a booking."
    PRD 2.9 rung 39: "The supplier line still has at least one available slot
    before the new reservation is written — otherwise `ERR_SLOT_LINE_EXHAUSTED`,
    409."

    Design: Corner/calculations/slot_line_exhausted_when_available_count_reaches_zero
    """
    program = create_active_program(api, name="Slot program")
    line = create_slot_line(api, supplier_name="Ladder Works Aerial Devices",
                            component_type="AERIAL_DEVICE", total_slot_count=1)
    first = reserve_slot(api, program["id"], line["id"],
                         slot_start_date="2026-09-01T00:00:00Z",
                         slot_end_date="2026-09-15T00:00:00Z",
                         reserved_price_cents=45_000_000,
                         expiry_at="2026-12-01T00:00:00Z")
    assert_slot_occupancy(read_slot_line(api, line["id"]), reserved=1, available=0,
                          total=1)

    far_future = build_reservation_payload(
        program["id"], line["id"], fresh_slot_line_version(api, line["id"]),
        slot_start_date="2027-01-01T00:00:00Z",
        slot_end_date="2027-01-15T00:00:00Z",
        reserved_price_cents=45_000_000,
        expiry_at="2027-04-01T00:00:00Z",
    )
    validate_error(
        api.create_chassis_reservation(far_future, make_program_admin_headers()),
        ErrorCode.ERR_SLOT_LINE_EXHAUSTED,
        409,
    )

    released = release_reservation(api, first["id"])
    assert released["status"] == ReservationStatus.RELEASED.value, released
    assert_slot_occupancy(read_slot_line(api, line["id"]), reserved=0, available=1,
                          total=1)

    retried = reserve_slot(api, program["id"], line["id"],
                           slot_start_date="2027-01-01T00:00:00Z",
                           slot_end_date="2027-01-15T00:00:00Z",
                           reserved_price_cents=45_000_000,
                           expiry_at="2027-04-01T00:00:00Z")
    assert retried["status"] == ReservationStatus.RESERVED.value, retried
    assert_slot_occupancy(read_slot_line(api, line["id"]), reserved=1, available=0,
                          total=1)

    rows, meta = validate_paginated(
        api.list_chassis_reservations(admin_headers, {"slot_line_id": line["id"]})
    )
    assert meta["total_count"] == 2, meta
    assert [row["id"] for row in rows] == [first["id"], retried["id"]], rows
    assert read_reservation(api, first["id"])["status"] == \
        ReservationStatus.RELEASED.value


def test_the_warranty_term_clamps_down_to_the_last_day_of_the_month(api,
                                                                   admin_headers):
    """An 31 August delivery ends on 29 February, never rolled into March.

    PRD 2.6: "The warranty term is a whole number of calendar months added to a
    start date, landing on the same day of month, with the day clamped down to
    the last day of the target month when that day does not exist in it."
    PRD 3.9: "its `warranty_start_date` is the `delivery_date` moved thirty
    whole days later, and its `warranty_end_date` is that start date plus
    `warranty_months` whole calendar months".
    PRD 3.9: "its `warranty_start_date` is pulled back from the deferred date to
    the `delivery_date` itself, its `warranty_end_date` is recomputed as that
    pulled-back start plus `warranty_months` calendar months".

    Design: Corner/calculations/warranty_window_clamps_to_the_last_day_of_the_target_month
    """
    ctx = setup_unit_at_stage(
        api, "FINAL_INSPECTED",
        program_overrides={"name": "Clamping program"},
        pre_trip_overrides={"scheduled_start": "2026-08-03T08:00:00Z",
                            "scheduled_end": "2026-08-03T16:00:00Z"},
        mid_trip_overrides={"scheduled_start": "2026-08-10T08:00:00Z",
                            "scheduled_end": "2026-08-10T16:00:00Z"},
    )

    delivered = validate_success(
        api.deliver_unit_order(
            ctx["unit_id"],
            {"delivery_date": "2026-08-31T00:00:00Z", "training_hours": 0.0,
             "warranty_months": 18},
            admin_headers,
        )
    )
    assert delivered["build_status"] == BuildStatus.DELIVERED.value, delivered

    rows, _ = validate_paginated(
        api.list_warranty_startups(admin_headers, {"unit_order_id": ctx["unit_id"]})
    )
    assert len(rows) == 1, rows
    warranty = rows[0]
    assert_warranty_window(warranty, status=WarrantyStatus.PENDING_TRAINING.value,
                           training_hours=0.0, start_date="2026-09-30",
                           end_date="2028-03-30")
    assert_price_reconciliation(warranty, final_price_cents=69_647_916,
                                price_variance_cents=1_371_916)

    activated = validate_success(
        api.complete_training(warranty["id"], {"additional_training_hours": 16.0},
                              admin_headers)
    )
    assert_warranty_window(activated, status=WarrantyStatus.ACTIVE.value,
                           training_hours=16.0, start_date="2026-08-31",
                           end_date="2028-02-29")
    assert_price_reconciliation(activated, final_price_cents=69_647_916,
                                price_variance_cents=1_371_916)

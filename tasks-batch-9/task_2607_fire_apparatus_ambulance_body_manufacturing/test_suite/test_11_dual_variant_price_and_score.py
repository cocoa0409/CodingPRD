"""The two pricing variants and the two compliance-score variants.

Both calculations in this file exist in two variants over identical inputs: the
award-year-locked price compounds whole years while the delivery-year-actual
price is simple pro-rata over whole months, and the strict readiness score
scores a pending exception as non-compliant while the provisional score credits
it. In each pair only one variant governs a gate.
"""

from test_helpers import (
    assert_clock_stamp,
    BuildStatus,
    ErrorCode,
    ProgramStatus,
    SpecificationStatus,
    WarrantyStatus,
    add_clause,
    assert_calendar_date,
    assert_price_reconciliation,
    assert_program_ledger,
    assert_spec_scores,
    assert_unit_money,
    assert_warranty_window,
    create_active_program,
    create_draft_specification,
    dispose_entry,
    file_compliance_entry,
    make_purchasing_officer_headers,
    read_program,
    read_unit,
    set_clock,
    setup_unit_at_stage,
    submit_specification_for_review,
    validate_error,
    validate_success,
    warranty_for_unit,
)


CHASSIS_CLAUSE = [
    {"clause_code": "C1", "category": "CHASSIS",
     "requirement_text": "Custom cab chassis, four-door",
     "mandatory": True, "is_restrictive": False},
]

AMBULANCE_CLAUSES = (
    {"clause_code": "C1", "category": "PATIENT_COMPARTMENT",
     "requirement_text": "Type I module, 170 inch",
     "mandatory": True, "is_restrictive": False},
    {"clause_code": "C2", "category": "ELECTRICAL",
     "requirement_text": "Multiplex electrical system",
     "mandatory": False, "is_restrictive": False},
    {"clause_code": "C3", "category": "PAINT",
     "requirement_text": "Two-tone paint scheme",
     "mandatory": False, "is_restrictive": False},
    {"clause_code": "C4", "category": "CHASSIS",
     "requirement_text": "Dual rear wheel chassis, 14500 lb GVWR",
     "mandatory": True, "is_restrictive": False},
)


def _final_inspected_unit(api):
    """One PUMPER awarded in 2026 against a 2024 base year, ready to deliver."""
    return setup_unit_at_stage(
        api, "FINAL_INSPECTED",
        program_overrides={"name": "Metro FD 2024-2029 Apparatus",
                           "agency_name": "Metro Fire District",
                           "max_option_units": 3},
        clauses=CHASSIS_CLAUSE,
        bay_overrides={"name": "Bay A", "max_concurrent_visitors": 10},
        pre_trip_overrides={"scheduled_start": "2026-08-10T08:00:00Z",
                            "scheduled_end": "2026-08-10T16:00:00Z"},
        slot_line_overrides={"supplier_name": "Freightline Custom Chassis",
                             "total_slot_count": 2},
    )


def _ambulance_clause_book(api):
    """Four clauses weighing 8, the mandatory C4 answered with a live exception.

    The specification is left `DRAFT`, because an entry may only be disposed
    while its parent specification is still `DRAFT` (PRD 3.3).
    """
    program = create_active_program(api, name="County EMS Ambulance Program",
                                    agency_name="County EMS", max_option_units=2)
    spec = create_draft_specification(api, program["id"],
                                      title="Ambulance spec rev A")
    entries = {}
    for clause_spec in AMBULANCE_CLAUSES:
        clause = add_clause(api, spec["id"], **clause_spec)
        if clause_spec["clause_code"] == "C4":
            entries["C4"] = file_compliance_entry(
                api, spec["id"], clause["id"], response="EXCEPTION",
                exception_text="Single rear wheel chassis offered",
            )
        else:
            entries[clause_spec["clause_code"]] = file_compliance_entry(
                api, spec["id"], clause["id"], response="COMPLY"
            )
    return {"program": program, "spec": spec, "entries": entries}


def test_the_frozen_award_price_and_the_delivery_year_price_disagree_by_a_pinned_variance(
        api, admin_headers):
    """Compounded whole years versus simple pro-rata months on one unit.

    PRD 3.5: "`price_cents` is computed at award time under the *award-year-locked*
    pricing rule and then frozen for the life of the unit — no later change
    order, cascade or rescission ever alters it."
    PRD 3.9: "`final_price_cents` is computed under the *delivery-year-actual*
    pricing rule, which differs from the award-year-locked rule at exactly one
    step: escalation is simple and pro-rata over whole months rather than
    compounded over whole years."
    PRD 3.9: "the unit whose award-locked `price_cents` was 68,276,000 and which
    is delivered on 1 November 2026 against a 2024 base year has thirty-four
    whole months elapsed, a `final_price_cents` of 70,279,166 and therefore a
    `price_variance_cents` of 2,003,166."

    Design: Difficulty/dual_variant_calc/award_locked_versus_delivery_year_escalation_price
    """
    ctx = _final_inspected_unit(api)
    assert_unit_money(ctx["unit"], price_cents=68_276_000,
                      change_order_total_cents=0, open_change_order_count=0)

    set_clock(api, "2026-11-01T00:00:00Z")
    delivered = validate_success(
        api.deliver_unit_order(ctx["unit_id"],
                               {"delivery_date": "2026-11-01T00:00:00Z",
                                "training_hours": 8.0, "warranty_months": 24},
                               admin_headers)
    )
    assert delivered["build_status"] == BuildStatus.DELIVERED.value, delivered
    assert_unit_money(delivered, price_cents=68_276_000)
    assert_clock_stamp(delivered["delivered_at"], "2026-11-01T00:00:00Z")

    warranty = warranty_for_unit(api, ctx["unit_id"])
    assert_price_reconciliation(warranty, final_price_cents=70_279_166,
                                price_variance_cents=2_003_166)
    assert_unit_money(read_unit(api, ctx["unit_id"]), price_cents=68_276_000)


def test_the_reconciliation_variance_defers_the_warranty_but_never_reaches_the_ledger(
        api, admin_headers):
    """A thirty-day deferred start, and committed money that ignores the variance.

    PRD 3.9: "The row is **always** created in `PENDING_TRAINING` with a deferred
    warranty start, whatever training was booked at handover: its
    `warranty_start_date` is the `delivery_date` moved thirty whole days later,
    and its `warranty_end_date` is that start date plus `warranty_months` whole
    calendar months".
    PRD 3.9: "`price_variance_cents` is then `final_price_cents` minus the unit's
    frozen `price_cents`, and it is deliberately excluded from the program's
    `committed_cents` — the variance is a reconciliation figure reported to the
    purchasing department, not a fresh commitment against the ceiling."

    Design: Difficulty/dual_variant_calc/award_locked_versus_delivery_year_escalation_price
    """
    ctx = _final_inspected_unit(api)
    set_clock(api, "2026-11-01T00:00:00Z")
    validate_success(
        api.deliver_unit_order(ctx["unit_id"],
                               {"delivery_date": "2026-11-01T00:00:00Z",
                                "training_hours": 8.0, "warranty_months": 24},
                               admin_headers)
    )

    warranty = warranty_for_unit(api, ctx["unit_id"])
    assert_warranty_window(warranty, status=WarrantyStatus.PENDING_TRAINING.value,
                           training_hours=8.0, start_date="2026-12-01",
                           end_date="2028-12-01")
    assert warranty["warranty_months"] == 24, warranty
    assert_calendar_date(warranty["delivery_date"], "2026-11-01")

    assert_program_ledger(read_program(api, ctx["program_id"]), 68_276_000,
                          ProgramStatus.ACTIVE.value, None)


def test_a_perfect_provisional_score_does_not_open_the_release_gate(api,
                                                                   admin_headers):
    """The gate reads the strict score only, and it stands at 62.50.

    PRD 3.3: "For `compliance_score_strict`, a clause's entry counts as compliant
    when its `response` is `COMPLY`, or when its `response` is `EXCEPTION` or
    `ALTERNATE` *and* its `disposition` is `ACCEPTED`; a still-pending exception
    counts as non-compliant."
    PRD 3.3: "the release gate reads `compliance_score_strict` and only
    `compliance_score_strict`."
    PRD 3.4: "Its `compliance_score_strict` must be at least 75.00 — exactly
    75.00 is admitted, and anything below it is refused with
    `ERR_SPEC_COMPLIANCE_BELOW_THRESHOLD`."

    Design: Difficulty/dual_variant_calc/strict_versus_provisional_compliance_score_release_gate
    """
    ctx = _ambulance_clause_book(api)
    spec_id = ctx["spec"]["id"]
    submit_specification_for_review(api, spec_id)

    before = validate_success(api.get_specification(spec_id, admin_headers))
    assert_spec_scores(before, strict=62.50, provisional=100.00,
                       restrictive_ratio=0.00, clause_count=4,
                       mandatory_clause_count=2)
    assert before["status"] == SpecificationStatus.UNDER_REVIEW.value, before

    validate_error(
        api.release_specification(spec_id,
                                  make_purchasing_officer_headers("po-releaser")),
        ErrorCode.ERR_SPEC_COMPLIANCE_BELOW_THRESHOLD,
        422,
    )
    after = validate_success(api.get_specification(spec_id, admin_headers))
    assert after["status"] == SpecificationStatus.UNDER_REVIEW.value, after
    assert after["released_by_user_id"] is None, after
    assert_spec_scores(after, strict=62.50, provisional=100.00)


def test_accepting_the_exception_lifts_the_strict_score_and_the_same_release_passes(
        api, admin_headers):
    """One disposition moves the strict score from 62.50 to 100.00.

    PRD 3.3: "Accepting an `EXCEPTION` or `ALTERNATE` response is the *only* way
    the strict score can count that clause as compliant".
    PRD 3.3: "The entry may only be disposed while its own `disposition` is
    `PENDING` *and* its parent specification is still `DRAFT`".
    PRD 3.4: "Its `compliance_score_strict` must be at least 75.00 — exactly
    75.00 is admitted, and anything below it is refused with
    `ERR_SPEC_COMPLIANCE_BELOW_THRESHOLD`."

    Design: Difficulty/dual_variant_calc/strict_versus_provisional_compliance_score_release_gate
    """
    ctx = _ambulance_clause_book(api)
    spec_id = ctx["spec"]["id"]

    pending = validate_success(api.get_specification(spec_id, admin_headers))
    assert_spec_scores(pending, strict=62.50, provisional=100.00)

    disposed = dispose_entry(api, ctx["entries"]["C4"]["id"],
                             disposition="ACCEPTED")
    assert disposed["disposition"] == "ACCEPTED", disposed

    lifted = validate_success(api.get_specification(spec_id, admin_headers))
    assert_spec_scores(lifted, strict=100.00, provisional=100.00,
                       restrictive_ratio=0.00, clause_count=4,
                       mandatory_clause_count=2)

    submit_specification_for_review(api, spec_id)
    released = validate_success(
        api.release_specification(spec_id,
                                  make_purchasing_officer_headers("po-releaser"))
    )
    assert released["status"] == SpecificationStatus.RELEASED.value, released
    assert released["released_by_user_id"] == "po-releaser", released
    assert_spec_scores(released, strict=100.00, provisional=100.00)

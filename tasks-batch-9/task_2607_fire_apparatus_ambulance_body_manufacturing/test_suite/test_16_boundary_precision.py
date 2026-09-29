"""Values sitting exactly on a boundary, and the one rounding that decides a split.

Every comparison in the weight verdict is strict and every release gate is
inclusive, so a single kilogram of rating or a single restrictive clause is the
whole difference between admitted and refused.
"""

from test_helpers import (
    ComplianceDisposition,
    ErrorCode,
    ProgramStatus,
    SpecificationStatus,
    WeightStatus,
    add_clause,
    assert_axle_loads,
    assert_program_ledger,
    assert_spec_scores,
    assert_unit_money,
    award_unit,
    create_active_program,
    create_draft_specification,
    create_released_specification,
    file_compliance_entry,
    make_purchasing_officer_headers,
    read_program,
    submit_specification_for_review,
    validate_error,
    validate_success,
)


CHASSIS_CLAUSE = [
    {"clause_code": "C1", "category": "CHASSIS",
     "requirement_text": "Tandem rear axle",
     "mandatory": True, "is_restrictive": False},
]

# One pumper on the standard 17,000 kg chassis, then five variants each one
# input away from it.
PUMPER_ON_THE_LINE = {
    "unit_type": "PUMPER", "award_year": 2026, "gvwr_kg": 17_000,
    "front_axle_rating_kg": 6_800, "rear_axle_rating_kg": 10_110,
    "base_curb_front_kg": 5_200, "base_curb_rear_kg": 7_000,
    "crew_seat_count": 4, "weight_calc_engineer_user_id": "eng-1",
}

AMBULANCE_ON_THE_HALF = {
    "unit_type": "AMBULANCE", "award_year": 2026, "gvwr_kg": 4_491,
    "front_axle_rating_kg": 1_600, "rear_axle_rating_kg": 2_300,
    "base_curb_front_kg": 1_200, "base_curb_rear_kg": 1_600,
    "crew_seat_count": 2, "weight_calc_engineer_user_id": "eng-1",
}

SPEC_X_CLAUSES = (
    {"clause_code": "X1", "category": "PUMP", "requirement_text": "1500 gpm pump",
     "mandatory": True, "is_restrictive": True},
    {"clause_code": "X2", "category": "CHASSIS",
     "requirement_text": "Named chassis brand",
     "mandatory": True, "is_restrictive": True},
    {"clause_code": "X3", "category": "PATIENT_COMPARTMENT",
     "requirement_text": "Aluminium body",
     "mandatory": True, "is_restrictive": False},
    {"clause_code": "X4", "category": "ELECTRICAL",
     "requirement_text": "Load manager", "mandatory": True, "is_restrictive": False},
    {"clause_code": "X5", "category": "AERIAL",
     "requirement_text": "105 ft rear mount", "mandatory": True,
     "is_restrictive": False},
    {"clause_code": "X6", "category": "PAINT", "requirement_text": "Two tone paint",
     "mandatory": False, "is_restrictive": False},
)

SPEC_Y_CLAUSES = (
    {"clause_code": "Y1", "category": "PUMP", "requirement_text": "1500 gpm pump",
     "mandatory": True, "is_restrictive": True},
    {"clause_code": "Y2", "category": "CHASSIS",
     "requirement_text": "Named chassis brand",
     "mandatory": True, "is_restrictive": True},
    {"clause_code": "Y3", "category": "PATIENT_COMPARTMENT",
     "requirement_text": "Aluminium body",
     "mandatory": True, "is_restrictive": False},
)


def _six_boundary_units(api):
    """Six awards off one released specification, each one kilogram from a verdict."""
    program = create_active_program(api, name="Boundary fleet program",
                                    agency_name="Eastvale Fire", base_year=2024,
                                    base_unit_price_cents=62_500_000,
                                    escalation_index_pct_per_year=4.0,
                                    max_option_units=2,
                                    contract_ceiling_cents=800_000_000)
    spec = create_released_specification(api, program["id"],
                                        clauses=CHASSIS_CLAUSE,
                                        title="Fleet spec rev A")
    variants = {
        "rear_on_the_line": {},
        "rear_over": {"rear_axle_rating_kg": 10_109},
        "front_over": {"front_axle_rating_kg": 5_809},
        "gvwr_on_the_line": {"gvwr_kg": 15_920},
        "gvwr_over": {"gvwr_kg": 15_919},
    }
    units = {}
    for key, overrides in variants.items():
        payload = dict(PUMPER_ON_THE_LINE)
        payload.update(overrides)
        units[key] = award_unit(api, program["id"], spec["specification_id"],
                                **payload)
    units["ambulance"] = award_unit(api, program["id"], spec["specification_id"],
                                    **AMBULANCE_ON_THE_HALF)
    return {"program": program, "program_id": program["id"], "units": units}


def _spec_x_on_both_thresholds(api):
    """Five mandatory clauses of which two are restrictive, one exception pending."""
    program = create_active_program(api, name="Threshold program",
                                    agency_name="Summit Fire",
                                    max_option_units=1)
    spec = create_draft_specification(api, program["id"],
                                      title="Spec X at both boundaries")
    entries = {}
    for clause_spec in SPEC_X_CLAUSES:
        clause = add_clause(api, spec["id"], **clause_spec)
        code = clause_spec["clause_code"]
        if code == "X5":
            entries[code] = file_compliance_entry(
                api, spec["id"], clause["id"], response="EXCEPTION",
                exception_text="Offering 100 ft rear mount",
            )
        elif code != "X6":
            entries[code] = file_compliance_entry(api, spec["id"], clause["id"],
                                                  response="COMPLY")
    submit_specification_for_review(api, spec["id"])
    return {"program_id": program["id"], "spec_id": spec["id"], "entries": entries}


def _spec_y_over_the_ratio_line(api):
    """Two restrictive clauses out of three mandatory: 66.67 percent."""
    program = create_active_program(api, name="Threshold program",
                                    agency_name="Summit Fire",
                                    max_option_units=1)
    spec = create_draft_specification(api, program["id"],
                                      title="Spec Y over the ratio line")
    for clause_spec in SPEC_Y_CLAUSES:
        clause = add_clause(api, spec["id"], **clause_spec)
        file_compliance_entry(api, spec["id"], clause["id"], response="COMPLY")
    submit_specification_for_review(api, spec["id"])
    return {"program_id": program["id"], "spec_id": spec["id"]}


def test_one_kilogram_of_rating_or_of_gross_flips_the_verdict(api, admin_headers):
    """Identical loads, three different verdicts, decided by strict comparisons.

    PRD 3.5: "The verdict, `weight_status`, is then decided by three strict
    comparisons evaluated in exactly this order. If `gross_weight_kg` is strictly
    greater than `gvwr_kg`, the verdict is `OVER_GVWR`. Otherwise, if
    `front_axle_load_kg` is strictly greater than `front_axle_rating_kg`, the
    verdict is `OVER_FRONT`. Otherwise, if `rear_axle_load_kg` is strictly greater
    than `rear_axle_rating_kg`, the verdict is `OVER_REAR`. Otherwise the verdict
    is `WITHIN_LIMITS`."
    PRD 3.5: "a chassis rated to 10,110 kilograms on the rear axle carrying exactly
    10,110 kilograms is a compliant vehicle, and it takes a single additional
    kilogram to make it `OVER_REAR`."

    Design: Difficulty/boundary_precision_check/axle_verdict_boundaries_and_front_share_half_up
    """
    units = _six_boundary_units(api)["units"]

    assert_axle_loads(units["rear_on_the_line"], front_kg=5_810, rear_kg=10_110,
                      gross_kg=15_920,
                      weight_status=WeightStatus.WITHIN_LIMITS.value)
    assert_axle_loads(units["rear_over"], front_kg=5_810, rear_kg=10_110,
                      gross_kg=15_920, weight_status=WeightStatus.OVER_REAR.value)
    assert_axle_loads(units["front_over"], front_kg=5_810, rear_kg=10_110,
                      gross_kg=15_920, weight_status=WeightStatus.OVER_FRONT.value)
    assert_axle_loads(units["gvwr_on_the_line"], front_kg=5_810, rear_kg=10_110,
                      gross_kg=15_920,
                      weight_status=WeightStatus.WITHIN_LIMITS.value)
    assert_axle_loads(units["gvwr_over"], front_kg=5_810, rear_kg=10_110,
                      gross_kg=15_920, weight_status=WeightStatus.OVER_GVWR.value)
    assert units["gvwr_on_the_line"]["gvwr_kg"] == 15_920, \
        units["gvwr_on_the_line"]
    assert units["gvwr_over"]["gvwr_kg"] == 15_919, units["gvwr_over"]


def test_the_front_payload_share_rounds_half_up_and_the_cap_legs_still_bind(
        api, admin_headers):
    """An ambulance payload of 898 kilograms splits 225 / 673, never 224 / 674.

    PRD 3.5: "That payload is then split between the axles. The front share is one
    quarter of the payload, quantised to a whole kilogram with round-half-up, but
    capped at 450 kilograms — whichever of the two is smaller. The rear share is
    the whole payload minus the front share, so nothing is lost in the split."
    PRD 3.5: "For an `AMBULANCE` the cap is 900 kilograms and the percentage is 20
    percent of `gvwr_kg`. In each case the payload is whichever of the two figures
    is smaller, with the percentage figure floored before the comparison."
    PRD 2.6: "The one fractional intermediate in the weight model — the front
    share of the payload — is quantised with round-half-up, and the one
    intermediate that is truncated — the percentage-of-rating leg of payload
    capacity — is floored."

    Design: Difficulty/boundary_precision_check/axle_verdict_boundaries_and_front_share_half_up
    """
    ctx = _six_boundary_units(api)
    ambulance = ctx["units"]["ambulance"]

    assert_axle_loads(ambulance, front_kg=1_585, rear_kg=2_273, gross_kg=3_858,
                      weight_status=WeightStatus.WITHIN_LIMITS.value)
    assert ambulance["front_axle_load_kg"] != 1_584, ambulance
    assert ambulance["rear_axle_load_kg"] != 2_274, ambulance
    assert_unit_money(ambulance, price_cents=68_276_000)

    assert_program_ledger(read_program(api, ctx["program_id"]), 409_656_000,
                          ProgramStatus.ACTIVE.value, None)


def test_a_specification_on_both_release_thresholds_at_once_is_admitted(
        api, admin_headers):
    """Strict score exactly 75.00 and restrictive ratio exactly 40.00 both pass.

    PRD 3.4: "Its `restrictive_clause_ratio_pct` must be at most 40.00 — exactly
    40.00 is admitted, and anything above it is refused with
    `ERR_RESTRICTIVE_CLAUSE_RATIO_EXCEEDED`. Its `compliance_score_strict` must be
    at least 75.00 — exactly 75.00 is admitted, and anything below it is refused
    with `ERR_SPEC_COMPLIANCE_BELOW_THRESHOLD`."
    PRD 3.2: "Optional clauses never enter the numerator or the denominator, even
    when they are themselves restrictive".
    PRD 3.3: "the release gate reads `compliance_score_strict` and only
    `compliance_score_strict`."

    Design: Difficulty/boundary_precision_check/release_gates_admit_values_exactly_on_the_threshold
    """
    ctx = _spec_x_on_both_thresholds(api)

    under_review = validate_success(
        api.get_specification(ctx["spec_id"], admin_headers)
    )
    assert_spec_scores(under_review, strict=75.00, provisional=93.75,
                       restrictive_ratio=40.00, clause_count=6,
                       mandatory_clause_count=5)

    released = validate_success(
        api.release_specification(ctx["spec_id"],
                                  make_purchasing_officer_headers("po-releaser"))
    )
    assert released["status"] == SpecificationStatus.RELEASED.value, released
    assert released["released_by_user_id"] == "po-releaser", released
    assert_spec_scores(released, strict=75.00, restrictive_ratio=40.00)

    pending = validate_success(
        api.get_compliance_entry(ctx["entries"]["X5"]["id"], admin_headers)
    )
    assert pending["disposition"] == ComplianceDisposition.PENDING.value, pending


def test_one_restrictive_clause_over_the_line_is_refused_until_rework_dilutes_it(
        api, admin_headers):
    """66.67 percent is refused; two more mandatory clauses bring it to 40.00.

    PRD 3.2: "count how many of those mandatory clauses have `is_restrictive`
    true, multiply that count by one hundred, divide by the total number of
    mandatory clauses, and quantise the result to two decimal places with
    round-half-up."
    PRD 3.2: "Sending the document back for rework takes `UNDER_REVIEW` to
    `DRAFT`, increments `revision_number` by one and increments `version`."
    PRD 3.2: "The cycle exists because clauses and compliance responses may be
    written *only* while the specification is `DRAFT`".

    Design: Difficulty/boundary_precision_check/release_gates_admit_values_exactly_on_the_threshold
    """
    ctx = _spec_y_over_the_ratio_line(api)
    spec_id = ctx["spec_id"]

    over_the_line = validate_success(api.get_specification(spec_id, admin_headers))
    assert_spec_scores(over_the_line, strict=100.00, restrictive_ratio=66.67,
                       clause_count=3, mandatory_clause_count=3)

    validate_error(
        api.release_specification(spec_id,
                                 make_purchasing_officer_headers("po-releaser")),
        ErrorCode.ERR_RESTRICTIVE_CLAUSE_RATIO_EXCEEDED,
        422,
    )

    reworked = validate_success(
        api.rework_specification(spec_id,
                                make_purchasing_officer_headers("po-author"))
    )
    assert reworked["status"] == SpecificationStatus.DRAFT.value, reworked
    assert reworked["revision_number"] == 2, reworked

    for clause_spec in (
        {"clause_code": "Y4", "category": "ELECTRICAL",
         "requirement_text": "Load manager", "mandatory": True,
         "is_restrictive": False},
        {"clause_code": "Y5", "category": "PAINT",
         "requirement_text": "Single stage paint", "mandatory": True,
         "is_restrictive": False},
    ):
        clause = add_clause(api, spec_id, **clause_spec)
        file_compliance_entry(api, spec_id, clause["id"], response="COMPLY")

    diluted = submit_specification_for_review(api, spec_id)
    assert_spec_scores(diluted, strict=100.00, restrictive_ratio=40.00,
                       clause_count=5, mandatory_clause_count=5)

    released = validate_success(
        api.release_specification(spec_id,
                                 make_purchasing_officer_headers("po-releaser"))
    )
    assert released["status"] == SpecificationStatus.RELEASED.value, released

"""Calculation corners for the protective-equipment reconditioning API.

Severity-index weighting, conditioning and material constants, half-up rounding
precision, turnaround commitment dates, component verdict thresholds, plant-wide
label sequencing and the loaner selector's ranking keys.
"""
from datetime import datetime, timezone

from test_helpers import (
    INSPECTOR_1,
    INTAKE_CLERK,
    TECHNICIAN_1,
    TEST_DEFAULTS,
    accept_shipment_payload,
    api_client,
    assert_certification_label,
    assert_component_inspection,
    assert_disposition_ledger_conserved,
    assert_equipment_unit,
    assert_intake_shipment,
    assert_label_code,
    assert_loaner_assignment,
    assert_loaner_unit,
    assert_shell_test,
    book_loaner,
    create_certification_label_payload,
    create_inspection_payload,
    create_loaner_assignment_payload,
    create_loaner,
    disassemble_unit,
    identify_unit,
    inspect_component,
    issue_label,
    read_label,
    read_loaner_unit,
    read_shipment,
    read_unit,
    record_impacts_payload,
    return_loaner,
    schedule_shell_test,
    set_clock,
    setup_accepted_shipment,
    setup_counted_shipment,
    setup_determined_units,
    setup_inspected_units,
    setup_reference_data,
    shell_component_criteria,
    unit_version,
    validate_success,
    void_label,
)

# An ABS shell on the reference severity bands: the material offset of 25 only
# applies to ABS, and the bands stay 300.0 / 360.0.
ABS_MODEL_OVERRIDES = {
    "manufacturer": "Schutt",
    "model_code": "AB-2026",
    "shell_material": "ABS",
}


def _as_instant(value):
    """Parse an ISO 8601 UTC instant the API returned into a comparable value."""
    assert isinstance(value, str) and value, (
        f"expected an ISO 8601 UTC instant, got {value!r}"
    )
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _assert_instant(actual, expected, field):
    """Exact instant equality, tolerant only of the ``Z`` / offset spelling."""
    assert _as_instant(actual) == _as_instant(expected), (
        f"{field} must be {expected}, got {actual!r}"
    )


def _assert_calendar_date(actual, expected_date, field):
    """The date portion of a value the PRD defines as a calendar date."""
    assert isinstance(actual, str) and actual[:10] == expected_date, (
        f"{field} must fall on {expected_date}, got {actual!r}"
    )


def _hot_abs_session():
    """An ABS-shelled unit inspected CLEAR with a HOT session booked on a
    calibrated rig, ready for its three impact readings."""
    ctx = setup_inspected_units(unit_count=1, model_overrides=ABS_MODEL_OVERRIDES)
    assert ctx["model"]["shell_material"] == "ABS"
    assert ctx["model"]["pass_si_max"] == 300.0
    assert ctx["model"]["repair_si_max"] == 360.0
    ctx["shell_test"] = schedule_shell_test(
        ctx["unit"]["id"], ctx["bench"]["id"], conditioning="HOT"
    )
    return ctx


def test_severity_index_applies_condition_multiplier_then_material_offset():
    """The conditioning multiplier scales the weighted sum and only then is the material offset added.

    PRD: "The three capped contributions are added together to give a raw index.
    That raw index is multiplied by the conditioning multiplier for the session's
    `conditioning` — 1.00 for `AMBIENT`, 1.15 for `HOT`, and 1.08 for `COLD` —
    and then the material offset for the model's `shell_material` is added: 0 for
    `POLYCARBONATE` and 25 for `ABS`."

    PRD: "The same three readings taken `HOT` on an `ABS` model instead give
    300.0 multiplied by 1.15, which is 345.0, plus an offset of 25, for a
    `severity_index` of 370.0 — beyond a `repair_si_max` of 360.0, and therefore
    a `CONDEMN`."

    PRD: "The order of these steps is part of the specification: the per-site cap
    is applied before summation, and the material offset is added after the
    conditioning multiplier has been applied, never before."

    Design: Corner/calculations/severity_index_applies_condition_multiplier_then_material_offset
    """
    ctx = _hot_abs_session()

    response = api_client.record_impacts(
        ctx["shell_test"]["id"], record_impacts_payload(300, 300, 300), TECHNICIAN_1
    )
    session = validate_success(response, 200)

    assert_shell_test(session)
    assert session["severity_index"] == 370.0, (
        "150.0 + 90.0 + 60.0 = 300.0, times the HOT multiplier 1.15 is 345.0, "
        "plus the ABS offset of 25"
    )
    assert session["computed_result"] == "CONDEMN"
    assert session["status"] == "COMPLETED"
    assert session["peak_g_front"] == 300
    assert session["peak_g_side"] == 300
    assert session["peak_g_crown"] == 300

    unit = read_unit(ctx["unit"]["id"])
    assert_equipment_unit(unit)
    assert unit["recon_status"] == "TESTED"
    assert unit["current_si"] == 370.0
    assert unit["retest_count"] == 0


def test_severity_index_rounds_half_up_to_one_decimal_place():
    """A severity index landing exactly on a half at the second decimal rounds up to one place.

    PRD: "The result is rounded half up to one decimal place and stored as
    `severity_index`."

    PRD: "Severity indices are decimal numbers carried to exactly one decimal
    place, rounded half up."

    PRD: "`computed_result` is then the band the index falls into: `PASS` when
    `severity_index` is less than or equal to the model's `pass_si_max`,
    otherwise `REPAIR` when it is less than or equal to the model's
    `repair_si_max`, and otherwise `CONDEMN`."

    Design: Corner/calculations/severity_index_rounds_half_up_to_one_decimal_place
    """
    ctx = _hot_abs_session()

    response = api_client.record_impacts(
        ctx["shell_test"]["id"], record_impacts_payload(250, 300, 300), TECHNICIAN_1
    )
    session = validate_success(response, 200)

    assert_shell_test(session)
    assert session["severity_index"] == 341.3, (
        "125.0 + 90.0 + 60.0 = 275.0, times the HOT multiplier 1.15 is 316.25, "
        "plus the ABS offset of 25 is 341.25, which rounds half up to 341.3"
    )
    assert session["computed_result"] == "REPAIR", (
        "341.3 is still at or below the repair band ceiling of 360.0"
    )
    assert session["status"] == "COMPLETED"

    unit = read_unit(ctx["unit"]["id"])
    assert unit["recon_status"] == "TESTED"
    assert unit["current_si"] == 341.3


def test_priority_rush_turnaround_commits_inside_the_season_deadline():
    """A PRIORITY_RUSH raw due date earlier than the season deadline is kept unclipped.

    PRD: "`raw_due_at` is `accepted_at` advanced by the sum of the tier base
    allowance and the batch allowance, in whole days."

    PRD: "Independently, the season deadline is `season_start_date` pulled back
    by a 7-day pre-season buffer, so the plant aims to have equipment back a full
    week before the first competition."

    PRD: "`committed_due_at` is then the earlier of `raw_due_at` and that season
    deadline."

    PRD: "`loaner_required` is set to true exactly when `raw_due_at` falls
    strictly later than `committed_due_at` — that is, when the season deadline is
    what clipped the commitment, meaning the plant has promised a date it cannot
    actually meet on its own throughput and must cover the gap with loaner
    equipment."

    PRD: "Because no unit has reached `CERTIFIED` or `CONDEMNED` at acceptance
    time, the billable set is empty then, so the provisional run instead prices
    `counted_unit_count` synthetic lines, each being the exact base amount of
    8,996 cents multiplied by the tier multiplier with no extras."

    PRD: "From that gross figure both variants continue identically: the discount
    rate is 0.000 when the gross is below 10,000 cents (100 dollars), 0.125 when
    the gross is below 100,000 cents (1,000 dollars), and 0.150 otherwise; the
    discount amount is the gross multiplied by that rate, rounded half up to
    whole cents; the net is the gross minus the discount; a compliance surcharge
    of 2 percent of the net is computed and rounded half up to whole cents; and
    the total is the net plus that surcharge."

    Design: Corner/calculations/priority_rush_turnaround_commits_inside_the_season_deadline
    """
    ctx = setup_counted_shipment(unit_count=1, service_tier="PRIORITY_RUSH")
    assert ctx["shipment"]["status"] == "COUNTED"

    response = api_client.accept_intake_shipment(
        ctx["shipment"]["id"], accept_shipment_payload("MATCHED"), INTAKE_CLERK
    )
    shipment = validate_success(response, 200)

    assert_intake_shipment(shipment)
    assert shipment["status"] == "ACCEPTED"
    _assert_instant(shipment["accepted_at"], "2026-08-01T00:00:00Z", "accepted_at")
    _assert_instant(
        shipment["raw_due_at"], "2026-08-12T00:00:00Z", "raw_due_at"
    )
    _assert_instant(
        shipment["committed_due_at"], "2026-08-12T00:00:00Z", "committed_due_at"
    )
    assert shipment["loaner_required"] is False, (
        "the raw date beats the season deadline of 18 August 2026, so nothing was clipped"
    )
    assert shipment["provisional_total_cents"] == 10840, (
        "8996 times 1.35 rounds to a gross of 12145, less a 0.125 discount of 1518 "
        "leaves a net of 10627, plus a 2 percent surcharge of 213"
    )
    assert shipment["units_in_process"] == 1
    assert shipment["units_certified"] == 0
    assert_disposition_ledger_conserved(shipment)


def test_inspection_verdict_is_inclusive_at_the_replace_threshold():
    """A LOWER_IS_WORSE liner measured exactly at its replace threshold is REPLACE, not PASS.

    PRD: "When it is `LOWER_IS_WORSE`, the verdict is `FAIL` if
    `measurement_value` is less than or equal to `fail_threshold_applied`,
    otherwise `REPLACE` if `measurement_value` is less than or equal to
    `replace_threshold_applied`, and otherwise `PASS`."

    PRD: "Both comparisons are inclusive at the threshold — a liner measured at
    exactly its replace threshold is `REPLACE`, not `PASS` — and `FAIL` is always
    evaluated before `REPLACE`, so a value that satisfies both conditions is a
    `FAIL`."

    PRD: "The recorded row snapshots the manufacturer criteria in force at that
    moment — `metric_direction_applied`, `replace_threshold_applied` and
    `fail_threshold_applied` are all copied from the criteria object of the unit's
    model whose `code` matches the supplied `component_code` — so that a later
    edit to the model specification cannot retroactively change a verdict already
    reached."

    PRD: "otherwise it is `REPLACE_REQUIRED` when any inspection on a
    non-`SHELL` code carries verdict `REPLACE` or `FAIL`; and otherwise it is
    `CLEAR`."

    PRD: "Once — and only once — the inspection set covers every code in
    `required_component_codes`, the unit advances `DISASSEMBLED → INSPECTED`
    automatically, with no separate request; the unit's `version` advances by one
    on each recorded inspection."

    Design: Corner/calculations/inspection_verdict_is_inclusive_at_the_replace_threshold
    """
    liner_criteria = shell_component_criteria(
        code="LINER",
        metric="pad_thickness_mm",
        metric_direction="LOWER_IS_WORSE",
        replace_threshold=4.0,
        fail_threshold=2.0,
    )
    ctx = setup_accepted_shipment(
        unit_count=1,
        model_overrides={
            "model_code": "SF-2026-L",
            "required_component_codes": ["SHELL", "LINER"],
            "component_criteria": [shell_component_criteria(), liner_criteria],
        },
    )
    unit_id = ctx["unit"]["id"]
    identify_unit(unit_id, ctx["model"]["id"])
    disassemble_unit(unit_id)
    inspect_component(
        unit_id, component_code="SHELL", measurement_value=1.50, note="shell sound"
    )
    assert read_unit(unit_id)["inspection_verdict_summary"] == "PENDING"

    response = api_client.create_component_inspection(
        unit_id,
        create_inspection_payload(
            component_code="LINER",
            measurement_value=4.00,
            note="pad at the replace limit",
        ),
        TECHNICIAN_1,
    )
    inspection = validate_success(response, 201)

    assert_component_inspection(inspection)
    assert inspection["component_code"] == "LINER"
    assert inspection["measurement_value"] == 4.00
    assert inspection["verdict"] == "REPLACE", (
        "a value equal to the replace threshold is inclusive of the replace band"
    )
    assert inspection["metric_direction_applied"] == "LOWER_IS_WORSE"
    assert inspection["replace_threshold_applied"] == 4.0
    assert inspection["fail_threshold_applied"] == 2.0

    unit = read_unit(unit_id)
    assert unit["inspection_verdict_summary"] == "REPLACE_REQUIRED", (
        "a REPLACE on a non-SHELL code rolls up to REPLACE_REQUIRED, never to FAIL"
    )
    assert unit["condemn_required"] is False
    assert unit["recon_status"] == "INSPECTED"


def test_label_sequence_still_counts_numbers_consumed_by_voided_labels():
    """A voided label keeps its daily sequence number, so the next label that day is 002.

    PRD: "`daily_sequence` is a **plant-wide** running number within a single
    certification date: it is one greater than the count of all certification
    labels — across every unit, every shipment and every account — whose
    `certified_on` equals the `certified_on` now being assigned and whose
    `status` is either `ACTIVE` or `VOIDED`, considered in `created_at` order."

    PRD: "Voided labels still consume their sequence number, so codes are never
    reused."

    PRD: "The `label_code` itself is assembled as the fixed prefix `RCP`, then a
    hyphen, then `standard_code_snapshot`, then a hyphen, then `certified_on`
    rendered as four-digit year followed by two-digit month followed by two-digit
    day with no separators, then a hyphen, then `daily_sequence` rendered as a
    decimal number zero-padded to three digits."

    PRD: "The voided unit is now back in `REPAIR_PENDING` and must travel the
    repair-retest-determine-certify path again from the beginning."

    Design: Corner/calculations/label_sequence_still_counts_numbers_consumed_by_voided_labels
    """
    ctx = setup_determined_units(unit_count=2, determination="PASS")
    first_unit, second_unit = ctx["units"][0], ctx["units"][1]

    first_label = issue_label(first_unit["id"])
    assert_label_code(first_label, TEST_DEFAULTS["STANDARD_CODE"], "20260801", 1)
    void_label(first_label["id"], void_reason="decal misprint")

    response = api_client.create_certification_label(
        create_certification_label_payload(
            second_unit["id"], unit_version(second_unit["id"])
        ),
        INSPECTOR_1,
    )
    second_label = validate_success(response, 201)

    assert_certification_label(second_label)
    assert_label_code(second_label, TEST_DEFAULTS["STANDARD_CODE"], "20260801", 2)
    assert second_label["label_code"] == "RCP-ND002-20260801-002"
    assert second_label["daily_sequence"] == 2
    assert second_label["status"] == "ACTIVE"
    _assert_calendar_date(second_label["certified_on"], "2026-08-01", "certified_on")

    reread_first = read_label(first_label["id"])
    assert reread_first["label_code"] == "RCP-ND002-20260801-001"
    assert reread_first["daily_sequence"] == 1
    assert reread_first["status"] == "VOIDED"

    assert read_unit(second_unit["id"])["recon_status"] == "CERTIFIED"
    assert read_unit(first_unit["id"])["recon_status"] == "REPAIR_PENDING"

    shipment = read_shipment(ctx["shipment"]["id"])
    assert shipment["units_certified"] == 1
    assert shipment["units_in_process"] == 1
    assert_disposition_ledger_conserved(shipment)


def test_loaner_selector_ranks_grade_then_count_then_created_at():
    """The selector applies condition_grade, then assignment_count, then created_at.

    PRD: "A loaner is eligible only if all four of the following hold: its
    `model_spec_id` equals the requested `requested_model_spec_id`; its `status`
    is `AVAILABLE`; its `certification_valid_until` is greater than or equal to
    the requested `window_end`; and it carries no assignment in `RESERVED` or
    `OUT_ON_LOAN` status whose half-open window intersects the requested
    half-open window."

    PRD: "Among the eligible pool, the winner is chosen by three ranking keys
    applied in order: first `condition_grade` ascending in the order `A`, then
    `B`, then `C`, so the best-conditioned loaner goes out first; then
    `assignment_count` ascending, so the least-worked loaner of a given grade is
    preferred; and finally `created_at` ascending as a deterministic last
    tie-break."

    PRD: "The clerk may name a specific `loaner_unit_id`, in which case
    `selected_by` is recorded as `EXPLICIT`; omitting it delegates the choice to
    the plant's selector policy and records `selected_by` as `SERVER_SELECTED`."

    PRD: "The assignment's initial `status` depends on the clock at creation:
    `OUT_ON_LOAN` when `window_start` is less than or equal to the logical clock,
    and `RESERVED` when `window_start` is strictly later."

    Design: Corner/calculations/loaner_selector_ranks_grade_then_count_then_created_at
    """
    window_start = "2026-08-05T00:00:00Z"
    window_end = "2026-08-12T00:00:00Z"
    long_certification = "2026-12-31T00:00:00Z"
    ctx = setup_reference_data()
    model_id = ctx["model"]["id"]

    # Grade A, created earliest of all, but worked once already: one completed
    # loan leaves it AVAILABLE with assignment_count 1.
    worked_a = create_loaner(
        model_id,
        asset_tag="LN-WORKED-A",
        condition_grade="A",
        certification_valid_until=long_certification,
    )
    finished = book_loaner(
        ctx["account"]["id"],
        model_id,
        loaner_unit_id=worked_a["id"],
        window_start=window_start,
        window_end=window_end,
    )
    return_loaner(finished["id"])
    worked_a = read_loaner_unit(worked_a["id"])
    assert worked_a["status"] == "AVAILABLE"
    assert worked_a["assignment_count"] == 1

    # Grade B, never loaned: it loses on the first key despite the lowest count.
    grade_b = create_loaner(
        model_id,
        asset_tag="LN-FRESH-B",
        condition_grade="B",
        certification_valid_until=long_certification,
    )
    # Grade A whose own recertification lapses one day before the window ends,
    # so it never enters the eligible pool at all.
    lapsing_a = create_loaner(
        model_id,
        asset_tag="LN-LAPSING-A",
        condition_grade="A",
        certification_valid_until="2026-08-11T00:00:00Z",
    )

    # Two unworked grade A loaners, separated on the clock so that created_at
    # ascending is the deciding key between them.
    set_clock("2026-08-02T00:00:00Z")
    earlier_a = create_loaner(
        model_id,
        asset_tag="LN-EARLIER-A",
        condition_grade="A",
        certification_valid_until=long_certification,
    )
    set_clock("2026-08-03T00:00:00Z")
    later_a = create_loaner(
        model_id,
        asset_tag="LN-LATER-A",
        condition_grade="A",
        certification_valid_until=long_certification,
    )
    assert earlier_a["assignment_count"] == 0
    assert later_a["assignment_count"] == 0

    response = api_client.create_loaner_assignment(
        create_loaner_assignment_payload(
            ctx["account"]["id"],
            model_id,
            window_start=window_start,
            window_end=window_end,
        ),
        INTAKE_CLERK,
    )
    assignment = validate_success(response, 201)

    assert_loaner_assignment(assignment)
    assert assignment["loaner_unit_id"] == earlier_a["id"], (
        "grade A beats grade B, count 0 beats count 1, and the earlier-created "
        "of the two unworked grade A loaners wins the final tie-break"
    )
    assert assignment["selected_by"] == "SERVER_SELECTED"
    assert assignment["status"] == "RESERVED"
    assert assignment["returned_at"] is None
    assert assignment["requested_model_spec_id"] == model_id

    winner = read_loaner_unit(earlier_a["id"])
    assert_loaner_unit(winner)
    assert winner["asset_tag"] == "LN-EARLIER-A"
    assert winner["status"] == "RESERVED"
    assert winner["assignment_count"] == 1
    assert winner["version"] == earlier_a["version"] + 1

    for loser, expected_count in (
        (worked_a, 1),
        (grade_b, 0),
        (lapsing_a, 0),
        (later_a, 0),
    ):
        reread = read_loaner_unit(loser["id"])
        assert reread["status"] == "AVAILABLE", (
            f"{reread['asset_tag']} must stay AVAILABLE, got {reread['status']}"
        )
        assert reread["assignment_count"] == expected_count, (
            f"{reread['asset_tag']} must keep assignment_count {expected_count}, "
            f"got {reread['assignment_count']}"
        )

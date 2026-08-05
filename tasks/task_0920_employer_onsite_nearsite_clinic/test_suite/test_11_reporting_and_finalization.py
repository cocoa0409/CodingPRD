"""Finalization, vendor true-up, the utilization report and small-cell suppression."""

from test_helpers import (
    ApiErrorId,
    add_member,
    api_client,
    book,
    check_in,
    complete_encounter,
    finalize_period,
    new_reporting_period,
    read_period,
    read_report,
    set_clock,
    setup_clinic,
    setup_completed_visit,
    start_encounter,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]

_TRACKS = (
    ("2026-06-08T09:00:00Z", "PRIMARY_CARE", {"clinical_note": "Primary care follow-up"}),
    ("2026-06-08T09:30:00Z", "OCC_HEALTH", {"fitness_conclusion": "FIT_FOR_DUTY"}),
    ("2026-06-08T10:00:00Z", "WELLNESS", {"clinical_note": "Wellness screening"}),
)


def _one_visit_per_track(code, name, fee_model, member, participant_name):
    """One participant with exactly one COMPLETED visit of each visit_type on
    2026-06-08, with the June period still OPEN and the clock at 2026-07-01."""
    world = setup_clinic(
        employer={"legal_name": name, "employer_code": code},
        site={"site_name": f"{code} On-Site Clinic", "daily_slot_capacity": 8},
        contract={"fee_model": fee_model, "quota_visits_total": 20},
        eligibility={
            "subscriber_external_id": f"S-{member}",
            "member_external_id": f"M-{member}",
        },
        participant={"display_name": participant_name},
        reporting_period={},
    )
    appointments = [
        book(
            world.participant_id,
            world.site_id,
            world.clinician_id,
            start,
            visit_type=visit_type,
        )
        for start, visit_type, _ in _TRACKS
    ]
    set_clock("2026-06-08T11:00:00Z")
    world.visits = []
    for appointment, (_, _, completion) in zip(appointments, _TRACKS):
        visit = check_in(appointment["id"], world.clinician_id)
        start_encounter(visit["id"], world.clinician_id)
        world.visits.append(
            complete_encounter(visit["id"], world.clinician_id, **completion)
        )
    set_clock("2026-07-01T00:00:00Z")
    return world


def test_avoided_cost_rounds_each_category_before_summing():
    """PRD §3.9: "For each visit type in the fixed order `PRIMARY_CARE`, `OCC_HEALTH`,
    `WELLNESS`, take the count of in-period visits of that type in `COMPLETED`,
    `AMENDED` or `LOCKED`, multiply by that track's diversion rate — 0.62 for primary
    care, 0.40 for occupational health, 0.15 for wellness, these being the shares of
    visits deemed to have displaced an outside encounter — and then by that track's
    benchmark outside cost, which is 185.33 dollars, that is 18533 cents, for primary
    care, 240.11 dollars, that is 24011 cents, for occupational health, and 90.07
    dollars, that is 9007 cents, for wellness. **Round each of the three category
    products half-up to whole cents first, and only then add the three rounded values
    together** to obtain `avoided_cost_cents`; summing the raw products and rounding
    once at the end produces a different total and is wrong."

    Design: Difficulty/combinatorial_formula/roi_rounds_each_visit_type_category_before_summing
    """
    world = _one_visit_per_track("ROI", "ROI Co", "PER_VISIT", "4001", "Rae Ortiz")
    finalize_period(world.period_id)

    report = read_report(world.period_id)

    assert report["avoided_cost_cents"] == 22445, (
        "11490 + 9604 + 1351; summing the raw products first would give 22446"
    )
    assert report["completed_visit_count"] == 3
    assert report["utilizing_participant_count"] == 1
    assert report["primary_care_visit_count"] == 1
    assert report["occ_health_visit_count"] == 1
    assert report["wellness_visit_count"] == 1
    assert report["suppressed_cell_keys"] == []


def test_per_visit_true_up_drives_program_cost_roi_and_pepm():
    """PRD §3.9: "`true_up_amount_cents` is then whichever is larger of zero and
    `minimum_guarantee_cents` less `gross_fee_cents`, so it is zero whenever the gross
    fee already meets or exceeds the guarantee. `contract_cost_cents` is
    `gross_fee_cents` plus `true_up_amount_cents`."
    PRD §3.9: "`roi_ratio` divides the already-rounded `avoided_cost_cents` by
    `program_cost_cents` and rounds half-up to four decimal places, and is exactly 0.0
    when the program cost is zero."
    PRD §3.9: "Then divide `program_cost_cents` by the enrolled population multiplied
    by that month count, rounding half-up to whole cents."

    Design: Difficulty/combinatorial_formula/roi_rounds_each_visit_type_category_before_summing
    """
    world = _one_visit_per_track("ROI", "ROI Co", "PER_VISIT", "4001", "Rae Ortiz")
    finalize_period(world.period_id)

    contract = validate_success(api_client.get_vendor_contract(world.contract_id, ADMIN))
    assert contract["billable_visit_count"] == 3
    assert contract["gross_fee_cents"] == 28500
    assert contract["true_up_amount_cents"] == 71500
    assert contract["contract_cost_cents"] == 100000

    report = read_report(world.period_id)
    assert report["program_cost_cents"] == 100000
    assert report["roi_ratio"] == 0.2245
    assert report["pepm_cents"] == 100000


def test_fte_hour_contract_prices_from_staffed_hours():
    """PRD §3.9: "Under `FTE_HOUR` it is `staffed_hours` multiplied by
    `fte_hourly_rate_cents`, rounded half-up to whole cents, and the visit count,
    although recorded, does not price the contract — which is why a period with no
    visits at all still bills the full staffed hours under this model, and why the
    minimum-guarantee true-up fires far less often here than it does under per-visit
    pricing."
    PRD §3.9: "`staffed_hours` on the contract is the sum, over every staffing shift
    at the contract's `site_id` whose `shift_start` falls inside the period from
    `period_start` at midnight UTC through `period_end` at one second before the
    following midnight UTC — both bounds inclusive — of that shift's own
    `staffed_hours`, where **each shift's hours are rounded half-up to two decimals
    first and the already-rounded values are then added together.**"

    Design: Difficulty/combinatorial_formula/vendor_true_up_evaluation_order_pins_program_cost_and_roi
    """
    world = _one_visit_per_track("FTE", "FTE Co", "FTE_HOUR", "5001", "Lee Nakamura")
    assert world.shift["staffed_hours"] == 9.0

    finalize_period(world.period_id)

    contract = validate_success(api_client.get_vendor_contract(world.contract_id, ADMIN))
    assert contract["billable_visit_count"] == 3
    assert contract["staffed_hours"] == 9.0
    assert contract["gross_fee_cents"] == 126000
    assert contract["true_up_amount_cents"] == 0, (
        "the gross fee already exceeds the 100000-cent guarantee"
    )
    assert contract["contract_cost_cents"] == 126000
    assert contract["status"] == "TRUED_UP"


def test_finalization_books_contract_cost_into_the_employer_and_report():
    """PRD §3.9: "Caused by that lock, every `ACTIVE` vendor contract of this employer
    is priced and moves to `TRUED_UP`. And caused by that pricing, the employer's
    `program_cost_to_date_cents` rises by the sum of those contracts'
    `contract_cost_cents`."
    PRD §3.9: "`program_cost_cents` is the sum of `contract_cost_cents` over the
    employer's vendor contracts whose `status` is `TRUED_UP`; contracts still
    `ACTIVE`, because the period has not been finalized, contribute zero."

    Design: Difficulty/combinatorial_formula/vendor_true_up_evaluation_order_pins_program_cost_and_roi
    """
    world = _one_visit_per_track("FTE", "FTE Co", "FTE_HOUR", "5001", "Lee Nakamura")

    before = read_report(world.period_id)
    assert before["program_cost_cents"] == 0, "an ACTIVE contract contributes zero"

    finalized = finalize_period(world.period_id)
    assert finalized["status"] == "FINALIZED"
    assert finalized["finalized_at"] is not None

    employer = validate_success(
        api_client.get_employer(world.employer_id, world.employer_headers)
    )
    assert employer["program_cost_to_date_cents"] == 126000

    report = read_report(world.period_id)
    assert report["program_cost_cents"] == 126000
    assert report["avoided_cost_cents"] == 22445
    assert report["roi_ratio"] == 0.1781
    assert report["pepm_cents"] == 126000

    for visit in world.visits:
        locked = validate_success(
            api_client.get_visit(visit["id"], world.clinician_headers)
        )
        assert locked["encounter_status"] == "LOCKED"


def _six_wellness_utilizers():
    """Six enrolled members, each with exactly one COMPLETED WELLNESS visit."""
    world = setup_clinic(
        employer={"legal_name": "Cell Co", "employer_code": "CEL"},
        site={"site_name": "CEL On-Site Clinic", "daily_slot_capacity": 8},
        contract={"quota_visits_total": 20},
        coverage_role="WELLNESS",
        eligibility={"subscriber_external_id": "S-01", "member_external_id": "M-01"},
        participant={"display_name": "P One"},
        reporting_period={},
    )
    members = [world.participant]
    for index in range(2, 7):
        members.append(add_member(world, f"0{index}", display_name=f"P {index}"))

    slots = (
        "09:00",
        "09:30",
        "10:00",
        "10:30",
        "11:00",
        "11:30",
    )
    appointments = [
        book(
            member["id"],
            world.site_id,
            world.clinician_id,
            f"2026-06-08T{slot}:00Z",
            visit_type="WELLNESS",
        )
        for member, slot in zip(members, slots)
    ]
    set_clock("2026-06-08T12:30:00Z")
    for appointment in appointments:
        visit = check_in(appointment["id"], world.clinician_id)
        start_encounter(visit["id"], world.clinician_id)
        complete_encounter(visit["id"], world.clinician_id)
    world.members = members
    return world


def test_cell_of_exactly_six_participants_is_reported_in_full():
    """PRD §3.9: "A cell with at least one and strictly fewer than six distinct
    participants has both its visit count and its participant count replaced by null,
    and the visit-type name is appended to `suppressed_cell_keys`. A cell with six or
    more distinct participants is reported unchanged."
    PRD §3.9: "The utilizing cell is protected on the same rule: when
    `utilizing_participant_count` is at least one and strictly fewer than six, both
    `utilizing_participant_count` and `visits_per_utilizer` are replaced by null and
    the key `UTILIZING` is appended to `suppressed_cell_keys` **after** any visit-type
    keys."

    Design: Difficulty/boundary_precision_check/report_cell_with_exactly_six_participants_is_not_suppressed
    """
    world = _six_wellness_utilizers()

    report = read_report(world.period_id, world.employer_headers)

    assert report["wellness_visit_count"] == 6
    assert report["wellness_participant_count"] == 6
    assert report["utilizing_participant_count"] == 6
    assert report["visits_per_utilizer"] == 1.0
    assert report["suppressed_cell_keys"] == []
    assert report["completed_visit_count"] == 6


def test_empty_visit_type_cells_are_reported_as_zero():
    """PRD §3.9: "A cell with zero distinct participants is reported as it stands,
    with its visit count and participant count both 0, and is **not** suppressed — an
    empty cell re-identifies nobody."
    PRD §3.9: "`eligible_population_count` counts the eligibility rows of the period's
    employer whose closed coverage span — from `effective_date` through
    `termination_date`, with a null termination meaning unbounded into the future —
    shares at least one date with the period's closed span; people who were eligible
    but never enrolled are counted here."

    Design: Difficulty/boundary_precision_check/report_cell_with_exactly_six_participants_is_not_suppressed
    """
    world = _six_wellness_utilizers()

    report = read_report(world.period_id, world.employer_headers)

    assert report["primary_care_visit_count"] == 0
    assert report["primary_care_participant_count"] == 0
    assert report["occ_health_visit_count"] == 0
    assert report["occ_health_participant_count"] == 0
    assert report["suppressed_cell_keys"] == []
    assert report["eligible_population_count"] == 6
    assert report["enrolled_population_count"] == 6
    assert report["engagement_rate_over_eligible"] == 1.0
    assert report["engagement_rate_over_enrolled"] == 1.0
    assert report["avoided_cost_cents"] == 8106
    assert report["program_cost_cents"] == 0
    assert report["roi_ratio"] == 0.0
    assert report["pepm_cents"] == 0


def test_small_cell_suppression_applies_only_to_the_employer_view():
    """PRD §3.9: "**Small-cell suppression is applied last, after every figure above
    has been computed, and only when the caller is an employer-side role.** A
    `ProgramAdmin` sees the report exactly as computed, with `suppressed_cell_keys` an
    empty array."
    PRD §3.9: "A cell with at least one and strictly fewer than six distinct
    participants has both its visit count and its participant count replaced by null,
    and the visit-type name is appended to `suppressed_cell_keys`."
    PRD §3.9: "Everything else survives suppression untouched —
    `engagement_rate_over_eligible`, `engagement_rate_over_enrolled`,
    `eligible_population_count`, `enrolled_population_count`, `completed_visit_count`,
    `avoided_cost_cents`, `program_cost_cents`, `roi_ratio` and `pepm_cents` are never
    suppressed."

    Design: Corner/calculations/small_cell_suppression_applies_to_employer_view_only
    """
    world = setup_completed_visit(
        visit_type="WELLNESS",
        scheduled_start="2026-06-08T09:00:00Z",
        visit_clock="2026-06-08T10:00:00Z",
        employer={"legal_name": "Suppress Co", "employer_code": "SUP"},
        site={"site_name": "SUP Clinic"},
        eligibility={"subscriber_external_id": "S-4501", "member_external_id": "M-4501"},
        participant={"display_name": "Sup Tester"},
        reporting_period={},
    )

    employer_view = read_report(world.period_id, world.employer_headers)
    assert employer_view["wellness_visit_count"] is None
    assert employer_view["wellness_participant_count"] is None
    assert employer_view["utilizing_participant_count"] is None
    assert employer_view["visits_per_utilizer"] is None
    assert employer_view["suppressed_cell_keys"] == ["WELLNESS", "UTILIZING"]
    assert employer_view["primary_care_visit_count"] == 0
    assert employer_view["occ_health_visit_count"] == 0
    assert employer_view["eligible_population_count"] == 1
    assert employer_view["enrolled_population_count"] == 1
    assert employer_view["engagement_rate_over_eligible"] == 1.0
    assert employer_view["avoided_cost_cents"] == 1351

    admin_view = read_report(world.period_id)
    assert admin_view["wellness_visit_count"] == 1
    assert admin_view["wellness_participant_count"] == 1
    assert admin_view["utilizing_participant_count"] == 1
    assert admin_view["visits_per_utilizer"] == 1.0
    assert admin_view["suppressed_cell_keys"] == []


def test_restatement_cycle_ends_in_closed_at_the_cap():
    """PRD §3.9: "**Restatement** reopens a finalized period for late corrections. It
    moves the period `FINALIZED → RESTATING`, raises `restatement_count` by one, and
    returns every `LOCKED` visit whose `service_date` falls inside the period to
    `AMENDED` — note that a visit that entered the lock from `COMPLETED` comes back as
    `AMENDED`, not as `COMPLETED`."
    PRD §3.9: "Restatement is available only while `restatement_count` is strictly
    less than two, so a period may be reopened at most twice; a third attempt is
    refused with `ERR_INVALID_STATE`, as is any restatement of a period that is
    `OPEN`, `RESTATING` or `CLOSED`."
    PRD §3.9: "Where the allowance is exhausted — `restatement_count` exactly two —
    the same finalization lands in `CLOSED` instead, running the identical four
    effects and rendering the period permanently immutable: no further restatement is
    possible from `CLOSED`, and the rung-6 freeze applies to `CLOSED` periods exactly
    as it does to `FINALIZED` ones."

    Design: Corner/state_machines/reporting_period_restatement_cycle_ends_in_closed_at_the_cap
    """
    world = setup_clinic(
        employer={"legal_name": "Restate Co", "employer_code": "RST"},
        contract=False,
        shift=False,
        participant=False,
    )
    period = new_reporting_period(world.employer_id)
    set_clock("2026-07-01T00:00:00Z")

    first_final = validate_success(
        api_client.finalize_reporting_period(period["id"], ADMIN)
    )
    assert first_final["status"] == "FINALIZED"
    assert first_final["restatement_count"] == 0

    first_restate = validate_success(
        api_client.restate_reporting_period(period["id"], ADMIN)
    )
    assert first_restate["status"] == "RESTATING"
    assert first_restate["restatement_count"] == 1

    second_final = validate_success(
        api_client.finalize_reporting_period(period["id"], ADMIN)
    )
    assert second_final["status"] == "FINALIZED"
    assert second_final["restatement_count"] == 1

    second_restate = validate_success(
        api_client.restate_reporting_period(period["id"], ADMIN)
    )
    assert second_restate["status"] == "RESTATING"
    assert second_restate["restatement_count"] == 2

    third_final = validate_success(
        api_client.finalize_reporting_period(period["id"], ADMIN)
    )
    assert third_final["status"] == "CLOSED"

    validate_error(
        api_client.restate_reporting_period(period["id"], ADMIN),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )
    assert read_period(period["id"])["status"] == "CLOSED"

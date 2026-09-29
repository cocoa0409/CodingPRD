"""Derived-number corners of the State Veterans Home API.

Every test here pins a single-pass computation the PRD defines over persisted
rows: the priority class ladder and the weighted priority score, the bed-count
identity of a care unit, the trust-fund replay, the ten-step cost-share
waterfall and its tier boundary, the census-day projection with its bed-hold
classification and per-day pricing, the governing-determination selector, and
the survey compliance score with its immediate-jeopardy override.

The server is relaunched before each test, so every test performs its own setup
against an empty database with the logical clock at its starting instant.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_bed_counts,
    assert_fields,
    assert_ledger_replay,
    assert_running_balances,
)
from test_helpers.test_users import (
    DEFAULT_ASSESSOR_USER,
    DEFAULT_BOM_USER,
    DEFAULT_COORDINATOR_USER,
    make_business_office_manager_headers,
    make_clinical_assessor_headers,
)

NURSING_DAILY_RATE_CENTS = 11857
BED_HOLD_HALF_RATE_CENTS = 5929


def _home_and_unit(
    api,
    clock="2026-08-01T00:00:00Z",
    care_level="NURSING",
    licensed_bed_count=2,
    out_of_service_bed_count=0,
    **home_overrides,
):
    """Place the clock, register one home and create one care unit under it."""
    fx.set_clock(api, clock)
    home = fx.create_home(api, **home_overrides)
    unit = fx.create_unit(
        api,
        home["id"],
        care_level=care_level,
        licensed_bed_count=licensed_bed_count,
        out_of_service_bed_count=out_of_service_bed_count,
    )
    return home, unit


def _admit(
    api,
    home_id,
    unit_id,
    admission_date,
    care_level="NURSING",
    application_received_date=None,
    assessment_date=None,
    assessor_user_id=DEFAULT_ASSESSOR_USER,
    coordinator_user_id=DEFAULT_COORDINATOR_USER,
    **applicant_overrides,
):
    """Carry one applicant through eligibility, the queue and an approved decision."""
    application_received_date = application_received_date or admission_date
    applicant = fx.create_applicant(
        api,
        home_id,
        requested_care_level=care_level,
        application_received_date=application_received_date,
        **applicant_overrides,
    )
    fx.determine_eligibility(api, applicant["id"])
    entry = fx.create_waitlist_entry(api, applicant["id"], unit_id)
    assessment = fx.create_assessment(
        api,
        applicant["id"],
        assessor_user_id,
        assessed_care_level=care_level,
        assessment_date=assessment_date or application_received_date,
    )
    fx.submit_assessment(api, assessment["id"], assessor_user_id)
    resident = get_success_data(
        fx.approve_admission(
            api,
            applicant["id"],
            unit_id,
            assessment["id"],
            admission_date,
            coordinator_user_id,
        )
    )
    return {
        "applicant": applicant,
        "entry": entry,
        "assessment": assessment,
        "resident": resident,
    }


def test_priority_class_ladder_boundaries_and_score_totals(api, coordinator_headers):
    """The class ladder is first-match-wins on inclusive bounds, and each class base anchors the score.

    Per the PRD: "An applicant whose VA `service_connected_disability_pct` is at
    least 70, or whose `nursing_care_for_service_connected` flag is true, is
    `CLASS_1`." A disability of exactly 70 therefore lands in CLASS_1 without
    ever being retested against the CLASS_2 predicate, while 69 with exactly five
    residency years falls through to CLASS_2 and 69 with four years to CLASS_3.
    Per the PRD: "The **class base** contributes 1,000 points for `CLASS_1`, 700
    for `CLASS_2`, 400 for `CLASS_3` and 100 for `CLASS_4`." With every applicant
    filed on the clock's own date the tenure term is zero, so the totals are the
    class base plus three points per disability point plus five points per
    residency year, and the CLASS_4 raw total of 105 survives the floor.

    Design: Corner/calculations/calc_priority_class_threshold_boundaries
    """
    home, _unit = _home_and_unit(api, licensed_bed_count=4)
    shared = {
        "service_days": 900,
        "discharge_character": "HONORABLE",
        "nursing_care_for_service_connected": False,
        "requested_care_level": "NURSING",
        "application_received_date": "2026-08-01",
    }
    class_one = fx.create_applicant(
        api,
        home["id"],
        full_name="Class One Boundary",
        date_of_birth="1950-01-01",
        wartime_service=True,
        service_connected_disability_pct=70,
        state_residency_years=6,
        **shared,
    )
    class_two = fx.create_applicant(
        api,
        home["id"],
        full_name="Class Two Boundary",
        date_of_birth="1950-01-02",
        wartime_service=True,
        service_connected_disability_pct=69,
        state_residency_years=5,
        **shared,
    )
    class_three = fx.create_applicant(
        api,
        home["id"],
        full_name="Class Three Boundary",
        date_of_birth="1950-01-03",
        wartime_service=True,
        service_connected_disability_pct=69,
        state_residency_years=4,
        **shared,
    )
    class_four = fx.create_applicant(
        api,
        home["id"],
        full_name="Class Four Boundary",
        date_of_birth="1950-01-04",
        wartime_service=False,
        service_connected_disability_pct=0,
        state_residency_years=1,
        **shared,
    )

    first = validate_success(
        api.determine_eligibility(class_one["id"], {}, coordinator_headers), 200
    )
    second = validate_success(
        api.determine_eligibility(class_two["id"], {}, coordinator_headers), 200
    )
    third = validate_success(
        api.determine_eligibility(class_three["id"], {}, coordinator_headers), 200
    )
    fourth = validate_success(
        api.determine_eligibility(class_four["id"], {}, coordinator_headers), 200
    )

    assert_fields(first, eligibility_reason_code="ELIGIBLE", priority_class="CLASS_1")
    assert first["priority_score"] == 1240
    assert_fields(second, priority_class="CLASS_2")
    assert second["priority_score"] == 932
    assert_fields(third, priority_class="CLASS_3")
    assert third["priority_score"] == 627
    assert_fields(fourth, priority_class="CLASS_4", status="ELIGIBLE")
    assert fourth["priority_score"] == 105


def test_priority_score_reads_only_the_latest_submitted_assessment(api, coordinator_headers):
    """Exactly one assessment feeds the acuity term, and a later DRAFT one feeds nothing.

    Per the PRD: "The **acuity term** is drawn from at most one clinical
    assessment: the applicant's assessment with the greatest `created_at` among
    those whose status is `SUBMITTED` or `ACCEPTED`." Per the PRD: "When one does
    exist, it contributes twenty points for each activity of daily living in its
    `adl_dependency_count` (capped at six dependencies, hence at 120 points), a
    further forty points when its `cognitive_impairment` flag is true, and a
    *deduction* of thirty points when its `behavioral_risk_flag` is true —
    behavioural risk narrows the set of units that can safely take the applicant,
    so it lowers rather than raises the queue position." Per the PRD:
    "Assessments still in `DRAFT`, and assessments that ended `REJECTED`,
    contribute nothing, and when no qualifying assessment exists the acuity term
    is exactly zero." The pre-acuity score of a CLASS_1 applicant with disability
    80 and six residency years filed on the clock's date is 1,270; the first
    submission adds 40, the second replaces it with 130, and the unsubmitted
    third assessment leaves the total where it was.

    Design: Corner/calculations/calc_priority_score_selects_latest_submitted_assessment_with_caps
    """
    home, _unit = _home_and_unit(api)
    applicant = fx.create_applicant(
        api,
        home["id"],
        full_name="Nora Halvorsen",
        date_of_birth="1946-06-06",
        service_days=900,
        discharge_character="HONORABLE",
        wartime_service=True,
        service_connected_disability_pct=80,
        nursing_care_for_service_connected=False,
        state_residency_years=6,
        requested_care_level="NURSING",
        application_received_date="2026-08-01",
    )
    determined = validate_success(
        api.determine_eligibility(applicant["id"], {}, coordinator_headers), 200
    )
    assert determined["priority_score"] == 1270

    assessor = make_clinical_assessor_headers(DEFAULT_ASSESSOR_USER)
    first = validate_success(
        api.create_clinical_assessment(
            applicant["id"],
            f.clinical_assessment_payload(
                adl_dependency_count=2,
                cognitive_impairment=False,
                behavioral_risk_flag=False,
                skilled_nursing_hours_per_day=3.00,
                assessment_date="2026-08-01",
            ),
            assessor,
        ),
        201,
    )
    submitted_first = validate_success(
        api.submit_clinical_assessment(first["id"], {}, assessor), 200
    )
    assert submitted_first["acuity_points"] == 40
    after_first = validate_success(api.get_applicant(applicant["id"], coordinator_headers), 200)
    assert after_first["priority_score"] == 1310

    second = validate_success(
        api.create_clinical_assessment(
            applicant["id"],
            f.clinical_assessment_payload(
                adl_dependency_count=6,
                cognitive_impairment=True,
                behavioral_risk_flag=True,
                skilled_nursing_hours_per_day=4.00,
                assessment_date="2026-08-01",
            ),
            assessor,
        ),
        201,
    )
    submitted_second = validate_success(
        api.submit_clinical_assessment(second["id"], {}, assessor), 200
    )
    assert submitted_second["acuity_points"] == 130
    after_second = validate_success(api.get_applicant(applicant["id"], coordinator_headers), 200)
    assert after_second["priority_score"] == 1400

    third = validate_success(
        api.create_clinical_assessment(
            applicant["id"],
            f.clinical_assessment_payload(
                adl_dependency_count=6,
                cognitive_impairment=True,
                behavioral_risk_flag=False,
                skilled_nursing_hours_per_day=4.00,
                assessment_date="2026-08-01",
            ),
            assessor,
        ),
        201,
    )
    assert_fields(third, status="DRAFT", acuity_points=160)
    after_third = validate_success(api.get_applicant(applicant["id"], coordinator_headers), 200)
    assert after_third["priority_score"] == 1400


def test_bed_counts_are_conserved_across_a_hold_and_a_discharge(api):
    """The four bed counts always sum to the licensed count, and a hold only moves a bed sideways.

    Per the PRD: "For a care unit, `occupied_bed_count` is the number of residents
    assigned to that unit whose `occupancy_status` is `ADMITTED`; `held_bed_count`
    is the number assigned to that unit whose `occupancy_status` is `HOSPITALIZED`
    and whose `bed_hold_days_used` is still strictly below the thirty-day bed-hold
    ceiling; and `available_bed_count` is the unit's `licensed_bed_count` less its
    `out_of_service_bed_count`, less `occupied_bed_count`, less `held_bed_count`."
    Per the PRD: "The unit-side cascade is a compensating pair:
    `occupied_bed_count` falls by 1 while `held_bed_count` rises by 1, so
    `available_bed_count` does not move at all, and the unit's `version`
    increments alongside the resident's." Per the PRD: "Residents whose
    `occupancy_status` is `DISCHARGED` are counted in neither occupancy tally." On
    a unit licensed for three beds with one out of service the counts therefore
    read 1/0/1 after admission, 0/1/1 while the bed is held, and 0/0/2 once the
    resident is discharged straight out of hospital.

    Design: Corner/calculations/calc_bed_availability_conserves_beds_across_hold_and_discharge
    """
    home, unit = _home_and_unit(api, licensed_bed_count=3, out_of_service_bed_count=1)
    assert_bed_counts(unit, occupied=0, held=0, available=2, posture="OPEN")

    admitted = _admit(api, home["id"], unit["id"], "2026-08-01")
    resident_id = admitted["resident"]["id"]
    after_admission = fx.read_unit(api, unit["id"])
    assert_bed_counts(after_admission, occupied=1, held=0, available=1, posture="OPEN")

    fx.set_clock(api, "2026-08-05T00:00:00Z")
    validate_success(fx.hospitalize(api, resident_id, "2026-08-05"), 200)
    after_hold = fx.read_unit(api, unit["id"])
    assert_bed_counts(after_hold, occupied=0, held=1, available=1)

    fx.set_clock(api, "2026-08-08T00:00:00Z")
    discharged = validate_success(
        fx.discharge(api, resident_id, "2026-08-08", "TRANSFER_OUT"), 200
    )
    assert discharged["occupancy_status"] == "DISCHARGED"
    after_discharge = fx.read_unit(api, unit["id"])
    assert_bed_counts(after_discharge, occupied=0, held=0, available=2, posture="OPEN")
    assert after_discharge["out_of_service_bed_count"] == 1


def test_trust_fund_replays_by_effective_date_not_insertion_order(api):
    """A late-entered earlier-dated posting retroactively renumbers the balances above it.

    Per the PRD: "The ledger is replayed, never accumulated: rows are ordered by
    `effective_date` ascending and then by `created_at` ascending — the record
    `id` is never a sort key — and each row's `balance_after_cents` is the sum of
    `signed_amount_cents` over every row at or before it in that order." A 50,000
    cent deposit dated the fifth therefore reads 50,000 when posted, but once a
    20,000 cent deposit dated the second is entered behind it the earlier-dated
    row reads 20,000 and the later-dated row reads 70,000, and the closing 60,000
    cent withdrawal leaves the resident at exactly 10,000.

    Design: Corner/calculations/calc_trust_fund_replays_out_of_order_effective_dates
    """
    home, unit = _home_and_unit(api)
    resident_id = _admit(api, home["id"], unit["id"], "2026-08-01")["resident"]["id"]
    fx.set_clock(api, "2026-08-10T00:00:00Z")

    later = validate_success(
        fx.post_trust_entry(api, resident_id, "DEPOSIT", 50000, "2026-08-05", "family deposit"),
        201,
    )
    assert later["balance_after_cents"] == 50000

    earlier = validate_success(
        fx.post_trust_entry(
            api, resident_id, "DEPOSIT", 20000, "2026-08-02", "late-entered earlier deposit"
        ),
        201,
    )
    assert earlier["balance_after_cents"] == 20000
    assert earlier["signed_amount_cents"] == 20000

    replayed_later = fx.read_transaction(api, later["id"])
    assert replayed_later["balance_after_cents"] == 70000
    assert replayed_later["reversed"] is False

    withdrawal = validate_success(
        fx.post_trust_entry(
            api, resident_id, "WITHDRAWAL", 60000, "2026-08-10", "resident purchase"
        ),
        201,
    )
    assert withdrawal["signed_amount_cents"] == -60000
    assert withdrawal["balance_after_cents"] == 10000

    resident = fx.read_resident(api, resident_id)
    assert resident["trust_fund_balance_cents"] == 10000
    ledger = fx.read_transactions(api, resident_id=resident_id)
    assert_running_balances(ledger)
    assert_ledger_replay(ledger, resident["trust_fund_balance_cents"])


def test_cost_share_tier_boundary_straddles_on_a_single_cent(api):
    """One cent of extra income crosses the tier boundary and moves the share by exactly one cent.

    Per the PRD: "It is `TIER_1` when that figure is 100,000 cents or less,
    `TIER_2` when it is above 100,000 cents and at most 250,000 cents, and
    `TIER_3` when it is above 250,000 cents." Per the PRD: "`tiered_share_cents`
    is the sum of three separately rounded products: the first band at 4,000 basis
    points (forty percent), the second at 5,500 basis points (fifty-five percent)
    and the third at 7,000 basis points (seventy percent), where each band's
    product is divided by ten thousand and **rounded half up before the three are
    added**." Against the default 9,000 cent personal needs allowance, gross
    countable income of 109,000 nets exactly 100,000 and stays in TIER_1 at 40,000
    cents, while 109,001 nets 100,001, becomes TIER_2, and adds a second band of
    one cent whose separately rounded product is one cent rather than 550.

    Design: Corner/calculations/calc_cost_share_tier_boundary_straddle_at_one_cent
    """
    home, unit = _home_and_unit(api, licensed_bed_count=2)
    assert home["personal_needs_allowance_monthly_cents"] == 9000
    low_edge = _admit(
        api, home["id"], unit["id"], "2026-08-01", full_name="Tier Low Edge"
    )["resident"]["id"]
    high_edge = _admit(
        api, home["id"], unit["id"], "2026-08-01", full_name="Tier High Edge"
    )["resident"]["id"]

    fx.declare_income(api, low_edge, "SSA", 109000, "2026-08", verify=False)
    low = validate_success(
        fx.determine_cost_share(api, low_edge, variant="PROVISIONAL", effective_month="2026-08"),
        201,
    )
    assert low["gross_countable_income_cents"] == 109000
    assert low["income_tier"] == "TIER_1"
    assert low["tiered_share_cents"] == 40000
    assert low["resident_day_count"] == 31
    assert low["monthly_cost_share_cents"] == 40000

    fx.declare_income(api, high_edge, "SSA", 109001, "2026-08", verify=False)
    high = validate_success(
        fx.determine_cost_share(api, high_edge, variant="PROVISIONAL", effective_month="2026-08"),
        201,
    )
    assert high["income_tier"] == "TIER_2"
    assert high["tiered_share_cents"] == 40001
    assert high["allowed_medical_deduction_cents"] == 0
    assert high["federal_per_diem_offset_cents"] == 0
    assert high["monthly_cost_share_cents"] == 40001


def test_final_determination_outranks_provisional_for_the_same_month(api):
    """Once a FINAL row exists for the month it governs, offset-capped, and advances billing.

    Per the PRD: "If at least one `FINAL` determination exists, the governing one
    is the `FINAL` row with the greatest `created_at`." Per the PRD: "For `FINAL`
    it is the lesser of two separately rounded quantities: the federal daily per
    diem rate for the resident's `current_care_level`, multiplied by
    `resident_day_count`, multiplied by 500 basis points (five percent), divided by
    ten thousand and rounded half up; and `tiered_share_cents` multiplied by 3,000
    basis points (thirty percent), divided by ten thousand and rounded half up."
    Verified SSA income of 114,000 cents nets 105,000 against the 9,000 cent
    allowance, which is TIER_2 and a tiered share of 42,750; over 31 census
    resident days the rate arm of the offset is 18,378 cents but the thirty
    percent cap arm is 12,825, so the FINAL share is 29,925 and the change it
    introduces against the governing provisional row is -12,825.

    Design: Corner/calculations/calc_governing_cost_share_final_outranks_provisional
    """
    home, unit = _home_and_unit(api)
    resident_id = _admit(
        api, home["id"], unit["id"], "2026-08-01", full_name="Delia Sorenson"
    )["resident"]["id"]

    income = fx.declare_income(api, resident_id, "SSA", 114000, "2026-08", verify=True)
    assert income["verification_status"] == "VERIFIED"

    provisional = validate_success(
        fx.determine_cost_share(api, resident_id, variant="PROVISIONAL", effective_month="2026-08"),
        201,
    )
    assert provisional["resident_day_count"] == 31
    assert provisional["monthly_cost_share_cents"] == 42750
    after_provisional = fx.read_resident(api, resident_id)
    assert after_provisional["monthly_cost_share_cents"] == 42750
    assert after_provisional["billing_status"] == "PROVISIONAL_COST_SHARE"

    fx.set_clock(api, "2026-09-01T00:00:00Z")
    counters = fx.census_run(api, "2026-08-31", home["id"])
    assert counters["generated_census_day_count"] == 31
    assert counters["skipped_cost_share_debit_count"] == 1

    final = validate_success(
        fx.determine_cost_share(
            api,
            resident_id,
            variant="FINAL",
            effective_month="2026-08",
            declared_medical_expense_cents=0,
        ),
        201,
    )
    assert final["income_tier"] == "TIER_2"
    assert final["tiered_share_cents"] == 42750
    assert final["resident_day_count"] == 31
    assert final["federal_per_diem_offset_cents"] == 12825
    assert final["monthly_cost_share_cents"] == 29925
    assert final["delta_from_prior_cents"] == -12825

    after_final = fx.read_resident(api, resident_id)
    assert after_final["monthly_cost_share_cents"] == 29925
    assert after_final["billing_status"] == "FINAL_COST_SHARE"


def _census_page(api, **params):
    """Read one page of census days as the business office, returning (rows, meta)."""
    params.setdefault("limit", 100)
    return validate_paginated(
        api.list_census_days(make_business_office_manager_headers(DEFAULT_BOM_USER), params)
    )


def test_census_days_are_adjacent_across_a_closed_bed_hold(api):
    """A 27-day stay with one closed hold yields 27 rows with no gap, no overlap and pinned prices.

    Per the PRD: "For every resident whose stay overlaps the run window, one census
    day row is created per calendar date, and `last_census_date` is then advanced
    to the end of the window." Per the PRD: "The consequences are worth stating
    plainly: the `hospitalization_start_date` is itself a `BED_HOLD_DAY`, and the
    `readmission_date` is itself a `RESIDENT_DAY`." Per the PRD: "`care_level` is
    the care level of the attributed unit; `per_diem_eligible` is true exactly when
    `census_class` is `RESIDENT_DAY` or `BED_HOLD_DAY`, since an `ABSENT_DAY` is
    never payable; and `payable_rate_cents` is the full federal rate for that
    `care_level` on a `RESIDENT_DAY`, that rate at 5,000 basis points rounded half
    up on a `BED_HOLD_DAY`, and 0 on an `ABSENT_DAY`." The half of the nursing rate
    of 11,857 cents rounds half up to 5,929, the four dates from the 20th through
    the 23rd are held days, and the remaining 23 dates are resident days.

    Design: Corner/calculations/calc_census_day_projection_is_adjacent_with_no_gap_or_overlap
    """
    home, unit = _home_and_unit(api, clock="2026-08-05T00:00:00Z")
    assert unit["per_diem_rate_cents"] == NURSING_DAILY_RATE_CENTS
    resident_id = _admit(
        api, home["id"], unit["id"], "2026-08-05", full_name="Cass Merritt"
    )["resident"]["id"]

    fx.set_clock(api, "2026-08-20T00:00:00Z")
    validate_success(fx.hospitalize(api, resident_id, "2026-08-20"), 200)
    fx.set_clock(api, "2026-08-24T00:00:00Z")
    readmitted = validate_success(fx.readmit(api, resident_id, "2026-08-24"), 200)
    assert readmitted["bed_hold_days_used"] == 4
    assert readmitted["bed_hold_started_on"] == "2026-08-20"
    assert readmitted["last_hospitalization_end_date"] == "2026-08-24"

    fx.set_clock(api, "2026-09-01T00:00:00Z")
    counters = fx.census_run(api, "2026-08-31")
    assert counters["generated_census_day_count"] == 27

    _resident_days, resident_meta = _census_page(
        api, resident_id=resident_id, census_class="RESIDENT_DAY"
    )
    assert resident_meta["total_count"] == 23

    hold_days, hold_meta = _census_page(
        api, resident_id=resident_id, census_class="BED_HOLD_DAY"
    )
    assert hold_meta["total_count"] == 4
    assert hold_days[0]["service_date"] == "2026-08-20"
    assert hold_days[0]["payable_rate_cents"] == BED_HOLD_HALF_RATE_CENTS
    assert hold_days[0]["per_diem_eligible"] is True

    before_hold, before_meta = _census_page(
        api, resident_id=resident_id, service_date_from="2026-08-19", service_date_to="2026-08-19"
    )
    assert before_meta["total_count"] == 1
    assert before_hold[0]["census_class"] == "RESIDENT_DAY"
    assert before_hold[0]["payable_rate_cents"] == NURSING_DAILY_RATE_CENTS

    boundary, boundary_meta = _census_page(
        api, resident_id=resident_id, service_date_from="2026-08-23", service_date_to="2026-08-24"
    )
    assert boundary_meta["total_count"] == 2
    assert boundary[0]["census_class"] == "BED_HOLD_DAY"
    assert boundary[1]["census_class"] == "RESIDENT_DAY"
    assert boundary[1]["payable_rate_cents"] == NURSING_DAILY_RATE_CENTS

    assert fx.read_resident(api, resident_id)["last_census_date"] == "2026-08-31"


def test_absent_days_begin_after_exactly_thirty_bed_hold_days(api):
    """An unbroken 61-day hold pays 30 held days and then turns absent, without touching the counter.

    Per the PRD: "A hold day is classified `BED_HOLD_DAY` while the days used at
    the end of it are below thirty, and `ABSENT_DAY` from that point on." Per the
    PRD: "The hospitalization start date therefore counts zero, and the thirty-first
    consecutive day of one unbroken hold is the first `ABSENT_DAY`." Per the PRD:
    "The checkpoint never mutates `bed_hold_days_used`; that field advances only at
    readmission." A resident hospitalized on the admission date of 1 August and
    never readmitted therefore holds the bed for the thirty dates through 30
    August, and every date from 31 August onward is an absent day that is not
    payable and carries a rate of zero.

    Design: Corner/calculations/calc_bed_hold_absent_day_after_exactly_thirty_days
    """
    home, unit = _home_and_unit(api)
    resident_id = _admit(
        api, home["id"], unit["id"], "2026-08-01", full_name="Ruben Ostlund"
    )["resident"]["id"]
    held = validate_success(fx.hospitalize(api, resident_id, "2026-08-01"), 200)
    assert held["bed_hold_started_on"] == "2026-08-01"
    assert held["bed_hold_active"] is True

    fx.set_clock(api, "2026-10-01T00:00:00Z")
    counters = fx.census_run(api, "2026-09-30")
    assert counters["generated_census_day_count"] == 61

    _hold_rows, hold_meta = _census_page(
        api, resident_id=resident_id, census_class="BED_HOLD_DAY"
    )
    assert hold_meta["total_count"] == 30

    absent_rows, absent_meta = _census_page(
        api, resident_id=resident_id, census_class="ABSENT_DAY"
    )
    assert absent_meta["total_count"] == 31
    assert absent_rows[0]["service_date"] == "2026-08-31"
    assert absent_rows[0]["per_diem_eligible"] is False
    assert absent_rows[0]["payable_rate_cents"] == 0
    assert absent_rows[0]["per_diem_claim_id"] is None

    _resident_rows, resident_meta = _census_page(
        api, resident_id=resident_id, census_class="RESIDENT_DAY"
    )
    assert resident_meta["total_count"] == 0

    last_paid, last_paid_meta = _census_page(
        api, resident_id=resident_id, service_date_from="2026-08-30", service_date_to="2026-08-30"
    )
    assert last_paid_meta["total_count"] == 1
    assert last_paid[0]["census_class"] == "BED_HOLD_DAY"
    assert last_paid[0]["payable_rate_cents"] == BED_HOLD_HALF_RATE_CENTS

    resident = fx.read_resident(api, resident_id)
    assert resident["bed_hold_days_used"] == 0
    assert resident["occupancy_status"] == "HOSPITALIZED"


def test_immediate_jeopardy_overrides_the_numeric_compliance_bands(api, surveyor_headers):
    """A score of 20 decertifies when immediate jeopardy is found, while a score of 11 only restricts.

    Per the PRD: "The unit's `last_survey_compliance_score` is the sum, over every
    deficiency in the payload, of the scope weight multiplied by the severity
    weight." Per the PRD: "The scope weights are 1 for `ISOLATED`, 2 for `PATTERN`
    and 4 for `WIDESPREAD`." Per the PRD: "If **any** deficiency in the payload has
    a `severity` of `IMMEDIATE_JEOPARDY`, the outcome is `DECERTIFIED`, and this
    override defeats the numeric bands entirely." One isolated immediate-jeopardy
    finding scores only 20, which sits inside the conditional band below the
    decertifying threshold of 25, yet the unit must land in DECERTIFIED and FROZEN
    and suspend its home, while a sibling unit scoring 11 from three lesser
    findings lands in CONDITIONAL and RESTRICTED.

    Design: Corner/calculations/calc_survey_immediate_jeopardy_overrides_numeric_band
    """
    home, unit_a = _home_and_unit(api, licensed_bed_count=4)
    unit_b = fx.create_unit(api, home["id"], care_level="NURSING", licensed_bed_count=4)

    conditional = validate_success(
        api.record_survey_result(
            unit_b["id"],
            f.survey_result_payload(
                "2026-08-01",
                [
                    f.deficiency("PATTERN", "MINIMAL_HARM"),
                    f.deficiency("ISOLATED", "MINIMAL"),
                    f.deficiency("WIDESPREAD", "MINIMAL"),
                ],
            ),
            surveyor_headers,
        ),
        200,
    )
    assert conditional["last_survey_compliance_score"] == 11
    assert conditional["certification_status"] == "CONDITIONAL"
    assert conditional["operational_posture"] == "RESTRICTED"

    decertified = validate_success(
        api.record_survey_result(
            unit_a["id"],
            f.survey_result_payload("2026-08-01", [f.deficiency("ISOLATED", "IMMEDIATE_JEOPARDY")]),
            surveyor_headers,
        ),
        200,
    )
    assert decertified["last_survey_compliance_score"] == 20
    assert decertified["certification_status"] == "DECERTIFIED"
    assert decertified["operational_posture"] == "FROZEN"

    after = fx.read_home(api, home["id"])
    assert_fields(
        after,
        recognition_status="SUSPENDED",
        recognition_suspended_reason="UNIT_DECERTIFIED",
        decertified_unit_count=1,
        last_survey_date="2026-08-01",
    )


def test_queue_order_tie_breaks_on_application_date_then_entry_created_at(api, coordinator_headers):
    """Three identically scored entries queue by application date and then by their own creation order.

    Per the PRD: "The candidate set is every entry on that unit whose status is
    `ACTIVE` or `OFFERED`; those candidates are ranked by the owning applicant's
    `priority_score` descending, then by the applicant's
    `application_received_date` ascending, then by the entry's own `created_at`
    ascending, and `queue_position` is the one-based index in that ranking." Per the
    PRD: "Bed offers are issued only by the nightly checkpoint, never by the
    operation that freed the bed." Two applicants who applied on 1 August score
    1,275 from thirty residency points and five tenure days, and a third who
    applied on the clock's own date reaches the same 1,275 from thirty-five
    residency points and no tenure, so the three tie and are separated only by the
    two later keys; the unit's single licensed bed is out of service, so it is
    RESTRICTED and no entry is offered.

    Design: Corner/calculations/calc_waitlist_queue_order_tie_break_chain
    """
    home, unit = _home_and_unit(
        api,
        clock="2026-08-06T00:00:00Z",
        licensed_bed_count=1,
        out_of_service_bed_count=1,
    )
    assert unit["available_bed_count"] == 0
    assert unit["operational_posture"] == "RESTRICTED"

    shared = {
        "service_days": 900,
        "discharge_character": "HONORABLE",
        "wartime_service": True,
        "service_connected_disability_pct": 80,
        "nursing_care_for_service_connected": False,
        "requested_care_level": "NURSING",
    }
    first_applicant = fx.create_applicant(
        api,
        home["id"],
        full_name="Queue First",
        date_of_birth="1939-09-09",
        state_residency_years=6,
        application_received_date="2026-08-01",
        **shared,
    )
    second_applicant = fx.create_applicant(
        api,
        home["id"],
        full_name="Queue Second",
        date_of_birth="1939-10-10",
        state_residency_years=6,
        application_received_date="2026-08-01",
        **shared,
    )
    third_applicant = fx.create_applicant(
        api,
        home["id"],
        full_name="Queue Third",
        date_of_birth="1939-11-11",
        state_residency_years=7,
        application_received_date="2026-08-06",
        **shared,
    )

    first_scored = validate_success(
        api.determine_eligibility(first_applicant["id"], {}, coordinator_headers), 200
    )
    second_scored = validate_success(
        api.determine_eligibility(second_applicant["id"], {}, coordinator_headers), 200
    )
    third_scored = validate_success(
        api.determine_eligibility(third_applicant["id"], {}, coordinator_headers), 200
    )
    assert first_scored["priority_class"] == "CLASS_1"
    assert first_scored["priority_score"] == 1275
    assert second_scored["priority_score"] == 1275
    assert third_scored["priority_score"] == 1275

    first_entry = validate_success(
        api.create_waitlist_entry(
            f.waitlist_entry_payload(first_applicant["id"], unit["id"]), coordinator_headers
        ),
        201,
    )
    assert first_entry["queue_position"] == 1
    assert first_entry["rank_score_snapshot"] == 1275
    assert first_entry["priority_class_snapshot"] == "CLASS_1"
    assert first_entry["status"] == "ACTIVE"

    second_entry = validate_success(
        api.create_waitlist_entry(
            f.waitlist_entry_payload(second_applicant["id"], unit["id"]), coordinator_headers
        ),
        201,
    )
    assert second_entry["queue_position"] == 2

    third_entry = validate_success(
        api.create_waitlist_entry(
            f.waitlist_entry_payload(third_applicant["id"], unit["id"]), coordinator_headers
        ),
        201,
    )
    assert third_entry["queue_position"] == 3
    assert third_entry["offer_expires_at"] is None

    rows, meta = validate_paginated(
        api.list_unit_waitlist_entries(unit["id"], coordinator_headers, {"status": "ACTIVE", "limit": 10})
    )
    assert meta["total_count"] == 3
    assert [row["applicant_id"] for row in rows] == [
        first_applicant["id"],
        second_applicant["id"],
        third_applicant["id"],
    ]
    assert rows[0]["queue_position"] == 1
    assert rows[2]["queue_position"] == 3
    assert fx.read_unit(api, unit["id"])["waitlist_active_count"] == 3

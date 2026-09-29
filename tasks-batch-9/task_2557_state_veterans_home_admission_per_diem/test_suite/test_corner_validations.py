"""Validation corners of the State Veterans Home admission and per diem API.

Each test here pins one rejection rule, and — where the PRD makes the neighbouring
success observable — the adjacent accepted call, so that the rule is shown to be
scoped exactly as the PRD scopes it rather than merely firing. Every expectation
is read off the PRD: the validation ladder that fixes which identifier a
multiply-violating request receives, the uniqueness and interval rules, the
fiscal floors of the trust-fund ledger, and the claim-assembly guards.

The server is restarted before every test, so each test builds its own world from
an empty database with the logical clock at its starting instant.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_errors import (
    ERR_BED_HOLD_OVERLAP,
    ERR_CLAIM_CENSUS_EMPTY,
    ERR_CLAIM_MONTH_MISMATCH,
    ERR_DATE_OUT_OF_RANGE,
    ERR_DUPLICATE_WAITLIST_ENTRY,
    ERR_HOME_NOT_FOUND,
    ERR_INCOME_NOT_VERIFIED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_TRANSFER_TARGET,
    ERR_PNA_RESERVE_BREACH,
    ERR_TRUST_FUND_INSUFFICIENT,
)
from test_helpers.assertions import (
    assert_bed_counts,
    assert_fields,
    assert_ledger_replay,
    assert_page_meta,
    assert_running_balances,
)
from test_helpers.constants import DEFAULT_PNA_MONTHLY_CENTS, PER_DIEM_RATE_CENTS
from test_helpers.test_users import (
    DEFAULT_ASSESSOR_USER,
    DEFAULT_BOM_USER,
    SECOND_BOM_USER,
    make_admissions_coordinator_headers,
    make_business_office_manager_headers,
    make_clinical_assessor_headers,
    make_state_program_admin_headers,
    make_survey_agency_headers,
)

CLOCK_AT_AUGUST_FIRST = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Local scenario helpers
# ---------------------------------------------------------------------------
def _recognized_home_with_nursing_units(
    api,
    unit_count=1,
    licensed_bed_count=2,
    clock=CLOCK_AT_AUGUST_FIRST,
    **home_overrides,
):
    """A home at its default RECOGNIZED standing plus N CERTIFIED nursing units."""
    fixtures.set_clock(api, clock)
    home = fixtures.create_home(api, **home_overrides)
    units = [
        fixtures.create_unit(
            api, home["id"], care_level="NURSING", licensed_bed_count=licensed_bed_count
        )
        for _ in range(unit_count)
    ]
    return home, units


def _eligible_nursing_applicant(api, home_id, application_received_date="2026-08-01"):
    """File one applicant who satisfies all three eligibility criteria."""
    applicant = fixtures.create_applicant(
        api,
        home_id,
        requested_care_level="NURSING",
        application_received_date=application_received_date,
    )
    return fixtures.determine_eligibility(api, applicant["id"])


def _place_on_queue(api, applicant_id, care_unit_id):
    """Raw waitlist placement, so a rejection can be inspected."""
    return api.create_waitlist_entry(
        f.waitlist_entry_payload(applicant_id, care_unit_id),
        make_admissions_coordinator_headers(),
    )


def _hospitalize_as_assessor(api, resident_id, start_date):
    return api.hospitalize_resident(
        resident_id,
        f.hospitalization_payload(start_date),
        make_clinical_assessor_headers(),
    )


def _readmit_as_assessor(api, resident_id, readmission_date):
    return api.readmit_resident(
        resident_id,
        f.readmission_payload(readmission_date),
        make_clinical_assessor_headers(),
    )


def _record_survey(api, care_unit_id, survey_date, deficiencies=None):
    return api.record_survey_result(
        care_unit_id,
        f.survey_result_payload(survey_date, deficiencies or []),
        make_survey_agency_headers(),
    )


# ---------------------------------------------------------------------------
# Waitlist uniqueness
# ---------------------------------------------------------------------------
def test_duplicate_waitlist_entry_is_scoped_to_one_unit_not_to_the_applicant(api):
    """A second live entry on the same unit is refused; a sibling unit accepts one.

    Per the PRD: "And the applicant must not already hold an entry on that same
    unit whose status is `ACTIVE` or `OFFERED`, or the placement is rejected with
    `ERR_DUPLICATE_WAITLIST_ENTRY` (HTTP 409) — note that an entry which has
    reached `ADMITTED`, `EXPIRED` or `CANCELLED` does not block a fresh
    placement."

    Per the PRD: "A `WAITLISTED` applicant may be placed on a *second* unit of
    the same requested care level, which creates a further entry with status
    `ACTIVE`, leaves the applicant's `status` at `WAITLISTED`, and increments
    `waitlist_active_count` and `version` on the newly joined unit only — the
    unit the applicant was already queued on is untouched."

    Per the PRD: "`waitlist_active_count` on a unit is the number of waitlist
    entries on that unit whose status is either `ACTIVE` or `OFFERED`; entries in
    any other status do not count."

    Design: Corner/validations/val_duplicate_waitlist_entry_rejected_per_unit_not_per_applicant
    """
    home, (unit_a, unit_b) = _recognized_home_with_nursing_units(api, unit_count=2)
    applicant = _eligible_nursing_applicant(api, home["id"])
    assert_fields(applicant, status="ELIGIBLE")

    first_entry = validate_success(_place_on_queue(api, applicant["id"], unit_a["id"]), 201)
    assert_fields(first_entry, care_unit_id=unit_a["id"], status="ACTIVE", queue_position=1)

    duplicate = _place_on_queue(api, applicant["id"], unit_a["id"])
    validate_error(duplicate, ERR_DUPLICATE_WAITLIST_ENTRY, 409)

    second_entry = validate_success(_place_on_queue(api, applicant["id"], unit_b["id"]), 201)
    assert_fields(second_entry, care_unit_id=unit_b["id"], status="ACTIVE", queue_position=1)

    live_entries, meta = validate_paginated(
        api.list_applicant_waitlist_entries(
            applicant["id"], make_admissions_coordinator_headers(), {"status": "ACTIVE", "limit": 10}
        )
    )
    assert_page_meta(meta, total_count=2)
    assert len(live_entries) == 2, f"expected two live entries, got {live_entries}"

    assert_fields(fixtures.read_unit(api, unit_a["id"]), waitlist_active_count=1)
    assert_fields(fixtures.read_unit(api, unit_b["id"]), waitlist_active_count=1)
    assert_fields(fixtures.read_applicant(api, applicant["id"]), status="WAITLISTED")


# ---------------------------------------------------------------------------
# Bed-hold intervals
# ---------------------------------------------------------------------------
def test_bed_hold_overlap_is_refused_on_the_readmission_date_but_not_the_day_after(api):
    """The half-open interval refuses a restart on the readmission date itself.

    Per the PRD: "Intervals are half-open — a hold runs from its start date up to
    but not including the readmission date — so a new hold starting the day after
    a prior readmission is legal zero-gap adjacency, while a new hold starting
    *on* the prior readmission date overlaps and is refused."

    Per the PRD: "On success `occupancy_status` returns to `ADMITTED`,
    `last_hospitalization_end_date` is set to the `readmission_date`,
    `bed_hold_days_used` increases by the number of days between
    `bed_hold_started_on` and the `readmission_date`, `readmission_count`
    increases by 1, `bed_hold_active` becomes false, and the compensating pair
    reverses — `held_bed_count` falls by 1 and `occupied_bed_count` rises by 1,
    again leaving `available_bed_count` unchanged — with both the unit's and the
    resident's `version` incrementing."

    Per the PRD: "Opening the hold sets `occupancy_status` to `HOSPITALIZED`,
    stamps `bed_hold_started_on` with the supplied `hospitalization_start_date`,
    increases `hospitalization_count` by 1, and sets `bed_hold_active` to true —
    `bed_hold_active` being true exactly when the resident is `HOSPITALIZED` and
    `bed_hold_days_used` is still below the thirty-day ceiling."

    Design: Corner/validations/val_bed_hold_overlap_rejected_at_zero_gap_boundary
    """
    scenario = fixtures.admitted_resident(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=2
    )

    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    validate_success(_hospitalize_as_assessor(api, scenario.resident_id, "2026-08-05"), 200)
    fixtures.set_clock(api, "2026-08-10T00:00:00Z")
    readmitted = validate_success(
        _readmit_as_assessor(api, scenario.resident_id, "2026-08-10"), 200
    )
    assert_fields(
        readmitted,
        occupancy_status="ADMITTED",
        bed_hold_days_used=5,
        last_hospitalization_end_date="2026-08-10",
        readmission_count=1,
        bed_hold_active=False,
    )

    overlapping = _hospitalize_as_assessor(api, scenario.resident_id, "2026-08-10")
    validate_error(overlapping, ERR_BED_HOLD_OVERLAP, 409)

    fixtures.set_clock(api, "2026-08-11T00:00:00Z")
    adjacent = validate_success(
        _hospitalize_as_assessor(api, scenario.resident_id, "2026-08-11"), 200
    )
    assert_fields(
        adjacent,
        occupancy_status="HOSPITALIZED",
        bed_hold_started_on="2026-08-11",
        bed_hold_days_used=5,
        hospitalization_count=2,
        bed_hold_active=True,
    )


# ---------------------------------------------------------------------------
# Future dates against the logical clock
# ---------------------------------------------------------------------------
def test_future_survey_date_is_judged_against_the_logical_clock(api):
    """A survey dated one day past the logical clock is refused; the clock's own day passes.

    Per the PRD: "A `survey_date`, `plan_date`, `effective_date` or `through_date`
    that lies in the future relative to the current logical clock is rejected with
    `ERR_DATE_OUT_OF_RANGE` (HTTP 409), as is any supplied date that violates its
    ordering rule against the resident's `admission_date`, `bed_hold_started_on`,
    or another prior date named in §3."

    Per the PRD: "An empty `deficiencies` array is entirely legal and represents a
    clean survey."

    Per the PRD: "Every survey, whatever its outcome, writes
    `last_survey_compliance_score`, sets the unit's `last_survey_date` to the
    supplied `survey_date`, sets the operating home's `last_survey_date` to the
    same value, recomputes `operational_posture`, and increments the unit's
    `version`."

    Per the PRD: "Only a certified unit with at least one free bed is `OPEN`."

    Design: Corner/validations/val_future_survey_date_rejected_against_logical_clock
    """
    clock = fixtures.set_clock(api, CLOCK_AT_AUGUST_FIRST)
    assert clock["current_utc"].startswith("2026-08-01T00:00:00"), (
        f"the clock should report the instant it was set to, got {clock['current_utc']!r}"
    )
    home = fixtures.create_home(api)
    unit = fixtures.create_unit(api, home["id"], care_level="NURSING", licensed_bed_count=2)

    future_dated = _record_survey(api, unit["id"], "2026-08-02")
    validate_error(future_dated, ERR_DATE_OUT_OF_RANGE, 409)

    clean = validate_success(_record_survey(api, unit["id"], "2026-08-01"), 200)
    assert_fields(
        clean,
        last_survey_compliance_score=0,
        certification_status="CERTIFIED",
        last_survey_date="2026-08-01",
        operational_posture="OPEN",
    )
    assert_fields(fixtures.read_home(api, home["id"]), last_survey_date="2026-08-01")


# ---------------------------------------------------------------------------
# Transfer target rules
# ---------------------------------------------------------------------------
def test_self_transfer_is_refused_once_the_active_care_plan_rung_has_passed(api):
    """With a governing plan in place a same-unit transfer names the target rule, not the plan rule.

    Per the PRD: "The `target_care_unit_id` must differ from the resident's
    current `care_unit_id` and must belong to the same `veterans_home_id`, else
    `ERR_INVALID_TRANSFER_TARGET` (HTTP 409)."

    Per the PRD: "When the resident holds an `ACTIVE` plan, that plan's
    `care_level` must equal the target unit's `care_level`, else
    `ERR_CARE_LEVEL_MISMATCH`; the separate case of a resident holding *no*
    `ACTIVE` plan at all is checked one rung later and is rejected with
    `ERR_NO_ACTIVE_CARE_PLAN` (HTTP 409)."

    Per the PRD: "A new plan is `DRAFT` — the plan lifecycle runs `DRAFT`,
    `ACTIVE`, `REVIEW_DUE`, `SUPERSEDED` and `VOID`, the last two terminal — with
    `authored_by_user_id` taken from the acting `X-User-ID`, `activated_at` null,
    `review_due_date` null, and `revision_number` set to one more than the
    superseded plan's `revision_number`, or to 1 when `supersedes_care_plan_id` is
    absent."

    Per the PRD: "On success the plan's `status` becomes `ACTIVE`, `activated_at`
    is stamped from the logical clock, `review_due_date` is stamped as the plan's
    own `plan_date` plus a ninety-day review cycle, `revision_number` is set to
    one more than the superseded plan's `revision_number` (or 1 when there is no
    predecessor), the superseded plan — when one was named — moves to
    `SUPERSEDED`, the `version` of both plans increments, and the resident's
    `current_care_level` is re-stamped from this plan's `care_level`, incrementing
    the resident's `version`."

    Per the PRD: "The source unit's `occupied_bed_count` falls by 1 and the target
    unit's rises by 1; `available_bed_count` and `operational_posture` are
    recomputed on **both** units; `queue_position` is recomputed for the `ACTIVE`
    and `OFFERED` entries on both units; both units' `version` values increment,
    as does the resident's."

    Design: Corner/validations/val_transfer_to_current_unit_rejected_after_care_plan_check_passes
    """
    scenario = fixtures.admitted_resident(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=2
    )
    unit_b = fixtures.add_unit(api, scenario, care_level="NURSING", licensed_bed_count=2)

    drafted = validate_success(
        api.create_care_plan(
            scenario.resident_id,
            f.care_plan_payload(
                care_level="NURSING", adl_support_level="MODERATE", plan_date="2026-08-01"
            ),
            make_clinical_assessor_headers(DEFAULT_ASSESSOR_USER),
        ),
        201,
    )
    assert_fields(drafted, status="DRAFT", review_due_date=None, revision_number=1)

    activated = validate_success(
        api.activate_care_plan(
            drafted["id"], {}, make_clinical_assessor_headers(DEFAULT_ASSESSOR_USER)
        ),
        200,
    )
    assert_fields(activated, status="ACTIVE", review_due_date="2026-10-30", revision_number=1)

    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    self_transfer = fixtures.transfer(api, scenario.resident_id, scenario.unit_id, "2026-08-05")
    validate_error(self_transfer, ERR_INVALID_TRANSFER_TARGET, 409)

    moved = validate_success(
        fixtures.transfer(api, scenario.resident_id, unit_b["id"], "2026-08-05"), 200
    )
    assert_fields(
        moved,
        care_unit_id=unit_b["id"],
        current_care_level="NURSING",
        occupancy_status="ADMITTED",
    )
    assert_bed_counts(fixtures.read_unit(api, scenario.unit_id), occupied=0, held=0, available=2)
    assert_bed_counts(fixtures.read_unit(api, unit_b["id"]), occupied=1, held=0, available=1)


# ---------------------------------------------------------------------------
# Income verification gates the FINAL variant
# ---------------------------------------------------------------------------
def test_final_cost_share_is_gated_on_a_verified_income_record_for_that_month(api):
    """The FINAL variant is refused while the month's only income record is UNVERIFIED.

    Per the PRD: "A resident whose `billing_status` is `PROVISIONAL_COST_SHARE`
    moves to `FINAL_COST_SHARE` the first time a `FINAL` determination is created,
    provided `expected_resident_version` matches, the resident is not
    `DISCHARGED`, and at least one of the resident's income records for that
    `effective_month` is `VERIFIED`; a `FINAL` determination requested for a month
    with no verified income is rejected with `ERR_INCOME_NOT_VERIFIED` (HTTP 409)."

    Per the PRD: "A new record's `verification_status` is `UNVERIFIED` and its
    `verified_by_user_id` is null; recording it increments the parent resident's
    `version`."

    Per the PRD: "The decision is written to `verification_status`,
    `verified_by_user_id` is taken from the acting `X-User-ID`, the record's own
    `version` increments and so does the parent resident's."

    Per the PRD: "From it, `countable_amount_cents` is computed as the gross
    `monthly_amount_cents` multiplied by `countable_rate_bps`, divided by ten
    thousand, and rounded half up to a whole cent."

    Per the PRD: "`pna_deduction_cents` is the
    `personal_needs_allowance_monthly_cents` of the home that operates the
    resident's unit."

    Per the PRD: "It is `TIER_1` when that figure is 100,000 cents or less,
    `TIER_2` when it is above 100,000 cents and at most 250,000 cents, and
    `TIER_3` when it is above 250,000 cents."

    Per the PRD: "`tiered_share_cents` is the sum of three separately rounded
    products: the first band at 4,000 basis points (forty percent), the second at
    5,500 basis points (fifty-five percent) and the third at 7,000 basis points
    (seventy percent), where each band's product is divided by ten thousand and
    **rounded half up before the three are added**."

    Per the PRD: "For `FINAL` it is the number of the resident's census days
    classified `RESIDENT_DAY` whose `service_date` falls inside `effective_month`."

    Per the PRD: "For `FINAL`, it is simply `tiered_share_cents` less
    `federal_per_diem_offset_cents`, floored at zero, with no proration at all."

    Design: Corner/validations/val_final_cost_share_blocked_until_income_verified
    """
    scenario = fixtures.admitted_resident(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=2
    )

    record = validate_success(
        api.create_income_record(
            scenario.resident_id,
            f.income_record_payload("SSA", 114000, "2026-08"),
            make_business_office_manager_headers(DEFAULT_BOM_USER),
        ),
        201,
    )
    assert_fields(
        record,
        verification_status="UNVERIFIED",
        verified_by_user_id=None,
        countable_rate_bps=10000,
        countable_amount_cents=114000,
    )

    blocked = fixtures.determine_cost_share(
        api,
        scenario.resident_id,
        variant="FINAL",
        effective_month="2026-08",
        declared_medical_expense_cents=0,
    )
    validate_error(blocked, ERR_INCOME_NOT_VERIFIED, 409)

    verified = validate_success(
        api.verify_income_record(
            record["id"],
            f.income_verification_payload("VERIFIED"),
            make_business_office_manager_headers(SECOND_BOM_USER),
        ),
        200,
    )
    assert_fields(
        verified, verification_status="VERIFIED", verified_by_user_id=SECOND_BOM_USER
    )

    determination = validate_success(
        fixtures.determine_cost_share(
            api,
            scenario.resident_id,
            variant="FINAL",
            effective_month="2026-08",
            declared_medical_expense_cents=0,
        ),
        201,
    )
    assert_fields(
        determination,
        variant="FINAL",
        effective_month="2026-08",
        gross_countable_income_cents=114000,
        pna_deduction_cents=DEFAULT_PNA_MONTHLY_CENTS,
        income_tier="TIER_2",
        allowed_medical_deduction_cents=0,
        tiered_share_cents=42750,
        resident_day_count=0,
        federal_per_diem_offset_cents=0,
        monthly_cost_share_cents=42750,
    )
    assert_fields(
        fixtures.read_resident(api, scenario.resident_id),
        billing_status="FINAL_COST_SHARE",
        monthly_cost_share_cents=42750,
    )


# ---------------------------------------------------------------------------
# The two trust-fund floors
# ---------------------------------------------------------------------------
def test_cost_share_reserve_and_withdrawal_floor_are_two_different_floors(api):
    """A cost-share debit stops at the allowance reserve; a withdrawal stops at zero.

    Per the PRD: "A `COST_SHARE_DEBIT` that would drive the balance below the
    home's `personal_needs_allowance_monthly_cents` reserve is rejected with
    `ERR_PNA_RESERVE_BREACH` (HTTP 409) — the personal needs allowance is money
    the resident keeps, and cost share may not reach it."

    Per the PRD: "A `WITHDRAWAL` that would drive the balance below zero is
    rejected with `ERR_TRUST_FUND_INSUFFICIENT` (HTTP 409)."

    Per the PRD: "`personal_needs_allowance_monthly_cents` sets the monthly
    personal needs allowance the home credits each resident and reserves from
    cost-share debits; it must not be negative and defaults to 9,000 cents, that
    is ninety dollars a month."

    Per the PRD: "`signed_amount_cents` is therefore the `amount_cents` itself for
    a `DEPOSIT` or `PNA_CREDIT`, the negation of `amount_cents` for a `WITHDRAWAL`
    or `COST_SHARE_DEBIT`, and, for a `REVERSAL`, the negation of the reversed
    row's own `signed_amount_cents`."

    Per the PRD: "The resident's `trust_fund_balance_cents` is the
    `balance_after_cents` of the last row in that order, or 0 when the resident
    has no postings."

    Design: Corner/validations/val_trust_fund_floor_rules_separate_withdrawal_from_cost_share_debit
    """
    scenario = fixtures.admitted_resident(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=2
    )
    assert_fields(
        fixtures.read_home(api, scenario.home_id),
        personal_needs_allowance_monthly_cents=DEFAULT_PNA_MONTHLY_CENTS,
    )

    deposit = validate_success(
        fixtures.post_trust_entry(
            api, scenario.resident_id, "DEPOSIT", 20000, "2026-08-01", memo="opening deposit"
        ),
        201,
    )
    assert_fields(deposit, signed_amount_cents=20000, balance_after_cents=20000)

    past_reserve = fixtures.post_trust_entry(
        api,
        scenario.resident_id,
        "COST_SHARE_DEBIT",
        11001,
        "2026-08-01",
        memo="debit one cent past the reserve",
    )
    validate_error(past_reserve, ERR_PNA_RESERVE_BREACH, 409)

    onto_reserve = validate_success(
        fixtures.post_trust_entry(
            api,
            scenario.resident_id,
            "COST_SHARE_DEBIT",
            11000,
            "2026-08-01",
            memo="debit exactly to the reserve",
        ),
        201,
    )
    assert_fields(
        onto_reserve,
        signed_amount_cents=-11000,
        balance_after_cents=DEFAULT_PNA_MONTHLY_CENTS,
    )

    past_zero = fixtures.post_trust_entry(
        api,
        scenario.resident_id,
        "WITHDRAWAL",
        9001,
        "2026-08-01",
        memo="one cent more than the fund holds",
    )
    validate_error(past_zero, ERR_TRUST_FUND_INSUFFICIENT, 409)

    onto_zero = validate_success(
        fixtures.post_trust_entry(
            api,
            scenario.resident_id,
            "WITHDRAWAL",
            9000,
            "2026-08-01",
            memo="empty the fund to zero",
        ),
        201,
    )
    assert_fields(onto_zero, signed_amount_cents=-9000, balance_after_cents=0)

    resident = fixtures.read_resident(api, scenario.resident_id)
    assert_fields(resident, trust_fund_balance_cents=0)

    rows, meta = validate_paginated(
        api.list_trust_fund_transactions(
            make_business_office_manager_headers(),
            {"resident_id": scenario.resident_id, "limit": 10},
        )
    )
    assert_page_meta(meta, total_count=3)
    assert_ledger_replay(rows, resident["trust_fund_balance_cents"])
    assert_running_balances(rows)


# ---------------------------------------------------------------------------
# A claim with no census behind it may be drafted but never submitted
# ---------------------------------------------------------------------------
def test_a_claim_with_no_census_days_drafts_cleanly_and_fails_at_submission(api):
    """An empty month opens as a zero-valued draft and is refused only on submit.

    Per the PRD: "A new claim starts `DRAFT` with `correction_generation` 0 and
    `corrects_claim_id`, `submitted_at`, `adjudicated_at`, `paid_amount_cents`,
    `rejection_code` and `adjudication_note` all null, and `recognition_verified`
    false."

    Per the PRD: "From that set, `resident_day_count` is the number of rows
    classified `RESIDENT_DAY`, `bed_hold_day_count` the number classified
    `BED_HOLD_DAY`, and `census_reported_resident_count` the number of distinct
    `resident_id` values appearing in it."

    Per the PRD: "The `claim_month` must be strictly earlier than the month of the
    current logical clock, because the census month must be closed, or
    `ERR_CLAIM_MONTH_NOT_CLOSED` (HTTP 409) — a claim for the current month is
    never submittable however complete it looks."

    Per the PRD: "Finally the claim must not be empty:
    `census_reported_resident_count` must be at least 1 and `billable_day_count` at
    least 1, or `ERR_CLAIM_CENSUS_EMPTY` (HTTP 409)."

    Per the PRD: "Submission re-prices the claim from the live census before
    anything is written, because days may have been generated, released or taken
    over since the draft was assembled; then it sets `status` to `SUBMITTED`,
    stamps `submitted_at` from the logical clock, sets `recognition_verified` to
    true, sets `per_diem_claim_id` on every attributed census day so that each
    row's `claimed` flag becomes true, and increments both the claim's `version`
    and the unit's `version`."

    Design: Corner/validations/val_empty_census_claim_rejected_on_submit
    """
    home, units = _recognized_home_with_nursing_units(
        api, recognition_effective_date="2026-06-01"
    )
    unit = units[0]
    assert_fields(home, recognition_status="RECOGNIZED")

    claim = validate_success(
        fixtures.open_claim(api, home["id"], unit["id"], claim_month="2026-07"), 201
    )
    assert_fields(
        claim,
        claim_month="2026-07",
        basis="AUDITED_BASIS",
        status="DRAFT",
        correction_generation=0,
        corrects_claim_id=None,
        resident_day_count=0,
        bed_hold_day_count=0,
        billable_day_count=0,
        census_reported_resident_count=0,
        claim_amount_cents=0,
        recognition_verified=False,
        submitted_at=None,
        adjudicated_at=None,
        paid_amount_cents=None,
        rejection_code=None,
    )

    refused = fixtures.submit_claim(api, claim["id"])
    validate_error(refused, ERR_CLAIM_CENSUS_EMPTY, 409)

    unchanged = fixtures.read_claim(api, claim["id"])
    assert_fields(
        unchanged,
        status="DRAFT",
        submitted_at=None,
        recognition_verified=False,
        version=claim["version"],
    )


# ---------------------------------------------------------------------------
# The optional claim_month echo on a correction
# ---------------------------------------------------------------------------
def test_a_correction_month_echo_that_disagrees_with_the_target_writes_nothing(api):
    """A wrong `claim_month` echo is refused, and the refusal leaves the target intact.

    Per the PRD: "**Pricing** starts from the federal daily rate for the unit's
    `care_level` — 11,857 cents for `NURSING`, 5,502 cents for `DOMICILIARY`,
    4,230 cents for `ADULT_DAY_HEALTH` — and then diverges by basis:"

    Per the PRD: "`billable_day_count` is `resident_day_count` plus those payable
    bed-hold days — so bed-hold days beyond the cap are excluded from the billable
    count entirely — and `claim_amount_cents` is the full rate times
    `resident_day_count`, plus the per-day bed-hold rate times the payable bed-hold
    days."

    Per the PRD: "On an outcome of `REJECTED`, a `rejection_code` of
    `CENSUS_MISMATCH`, `RECOGNITION_LAPSE` or `DUPLICATE_PERIOD` is required;
    `status` becomes `REJECTED`, `adjudicated_at` is stamped, `paid_amount_cents`
    is set to 0, the code is stored, and every attributed census day is released
    with `per_diem_claim_id` set back to null and `claimed` back to false, which
    returns those days to the pool."

    Per the PRD: "That last field is an optional confirmation echo and nothing
    more: the new claim always copies its `claim_month` and `care_unit_id` from the
    target, but when the caller does supply `claim_month` it must equal the
    target's, and a mismatch is rejected with `ERR_CLAIM_MONTH_MISMATCH` (HTTP 409)
    before anything is written."

    Per the PRD: "The correction creates a fresh `DRAFT` claim whose
    `corrects_claim_id` names the target and whose `correction_generation` is the
    target's plus one, so a chain of corrections is self-describing."

    Design: Corner/validations/val_correction_month_echo_mismatch_rejected
    """
    scenario = fixtures.billed_month(
        api,
        admission_date="2026-07-01",
        through_date="2026-07-31",
        clock_after_month="2026-08-01T00:00:00Z",
        care_level="NURSING",
    )
    full_month_cents = 31 * PER_DIEM_RATE_CENTS["NURSING"]
    assert full_month_cents == 367567

    claim = validate_success(
        fixtures.open_claim(api, scenario.home_id, scenario.unit_id, claim_month="2026-07"), 201
    )
    assert_fields(
        claim,
        resident_day_count=31,
        bed_hold_day_count=0,
        billable_day_count=31,
        census_reported_resident_count=1,
        claim_amount_cents=full_month_cents,
    )

    validate_success(fixtures.submit_claim(api, claim["id"]), 200)
    rejected = validate_success(
        fixtures.adjudicate_claim(
            api,
            claim["id"],
            outcome="REJECTED",
            rejection_code="CENSUS_MISMATCH",
            note="reported days do not agree with the census",
        ),
        200,
    )
    assert_fields(
        rejected, status="REJECTED", rejection_code="CENSUS_MISMATCH", paid_amount_cents=0
    )
    settled_version = rejected["version"]

    wrong_echo = api.correct_per_diem_claim(
        claim["id"],
        f.correction_payload(
            settled_version, "recount after audit", claim_month="2026-06"
        ),
        make_business_office_manager_headers(DEFAULT_BOM_USER),
    )
    validate_error(wrong_echo, ERR_CLAIM_MONTH_MISMATCH, 409)

    untouched = fixtures.read_claim(api, claim["id"])
    assert_fields(untouched, version=settled_version, status="REJECTED")

    correction = validate_success(
        api.correct_per_diem_claim(
            claim["id"],
            f.correction_payload(
                settled_version, "recount after audit", claim_month="2026-07"
            ),
            make_business_office_manager_headers(DEFAULT_BOM_USER),
        ),
        201,
    )
    assert_fields(
        correction,
        status="DRAFT",
        claim_month="2026-07",
        care_unit_id=scenario.unit_id,
        corrects_claim_id=claim["id"],
        correction_generation=1,
        resident_day_count=31,
        billable_day_count=31,
        claim_amount_cents=full_month_cents,
    )


# ---------------------------------------------------------------------------
# A required field left out of the body
# ---------------------------------------------------------------------------
def test_filing_an_applicant_without_a_full_name_is_a_request_shape_rejection(api):
    """`full_name` is required, so omitting it is refused and nothing is filed.

    Per the PRD: "An `AdmissionsCoordinator` files an **applicant** against a
    specific home, naming that home with `veterans_home_id`."

    Per the PRD: "The filing payload carries the applicant's `full_name` (between 1
    and 200 characters, not blank) and `date_of_birth` in `YYYY-MM-DD` form, the
    service evidence — `service_days` (the total days of qualifying active military
    service, which must not be negative), `discharge_character` (one of
    `HONORABLE`, `GENERAL`, `OTHER_THAN_HONORABLE`, `BAD_CONDUCT` or
    `DISHONORABLE`), the boolean `wartime_service` recording whether any qualifying
    service fell inside a recognized wartime period,
    `service_connected_disability_pct` (the VA disability rating, between 0 and 100
    inclusive) and the boolean `nursing_care_for_service_connected` recording
    whether nursing care is required specifically for that service-connected
    disability — the residency evidence `state_residency_years` (completed years of
    residency in the operating state, not negative), the `requested_care_level` the
    applicant is applying for (`NURSING`, `DOMICILIARY` or `ADULT_DAY_HEALTH`), and
    the `application_received_date`."

    Per the PRD: "Every required field present, every enum value inside its
    declared set, every numeric field inside its declared range, dates in
    `YYYY-MM-DD` form and months in `YYYY-MM` form, `licensed_bed_count` at least
    1, `out_of_service_bed_count` no greater than `licensed_bed_count`,
    `amount_cents` strictly greater than zero, `adl_dependency_count` between 0 and
    6 inclusive, `service_connected_disability_pct` between 0 and 100 inclusive,
    and pagination `limit` between 1 and 100 inclusive with `offset` at least zero.
    Any violation is `ERR_INVALID_REQUEST`."

    Design: Corner/validations/val_missing_required_full_name_returns_422
    """
    home, _units = _recognized_home_with_nursing_units(api, unit_count=0)

    payload = f.applicant_payload(home["id"])
    payload.pop("full_name")
    refused = api.create_applicant(payload, make_admissions_coordinator_headers())
    validate_error(refused, ERR_INVALID_REQUEST, 422)

    _rows, meta = validate_paginated(
        api.list_home_applicants(
            home["id"], make_admissions_coordinator_headers(), {"limit": 10}
        )
    )
    assert_page_meta(meta, total_count=0)

    accepted = validate_success(
        api.create_applicant(
            f.applicant_payload(home["id"]), make_admissions_coordinator_headers()
        ),
        201,
    )
    assert accepted["full_name"], "an accepted filing carries the name it was given"


# ---------------------------------------------------------------------------
# Request shape outranks path resolution
# ---------------------------------------------------------------------------
def test_a_bad_care_level_enum_is_reported_ahead_of_an_unresolvable_home_id(api):
    """A request that is both malformed and misaddressed reports the shape failure.

    Per the PRD: "When several rules could reject the same request, the order in
    which they are evaluated is part of the contract, because the error the client
    receives must be deterministic."

    Per the PRD: "Every endpoint evaluates its applicable rules in the following
    sequence, and the first rule that fails is the one reported."

    Per the PRD: "Every required field present, every enum value inside its
    declared set, every numeric field inside its declared range, dates in
    `YYYY-MM-DD` form and months in `YYYY-MM` form, `licensed_bed_count` at least
    1, `out_of_service_bed_count` no greater than `licensed_bed_count`,
    `amount_cents` strictly greater than zero, `adl_dependency_count` between 0 and
    6 inclusive, `service_connected_disability_pct` between 0 and 100 inclusive,
    and pagination `limit` between 1 and 100 inclusive with `offset` at least zero.
    Any violation is `ERR_INVALID_REQUEST`."

    Per the PRD: "Identifiers embedded in a path are resolved strictly left to
    right, and the first one that resolves to nothing determines the error."

    Per the PRD: "A unit declares its `unit_name` (between 1 and 120 characters,
    not blank), its `care_level` — one of `NURSING`, `DOMICILIARY` or
    `ADULT_DAY_HEALTH` — and its `licensed_bed_count`, which must be at least 1."

    Design: Corner/validations/val_invalid_enum_rejected_before_home_not_found
    """
    home, _units = _recognized_home_with_nursing_units(api, unit_count=0)
    admin = make_state_program_admin_headers()

    both_wrong = api.create_care_unit(
        NON_EXISTENT_UUID, f.care_unit_payload(care_level="SKILLED"), admin
    )
    validate_error(both_wrong, ERR_INVALID_REQUEST, 422)

    only_enum_wrong = api.create_care_unit(
        home["id"], f.care_unit_payload(care_level="SKILLED"), admin
    )
    validate_error(only_enum_wrong, ERR_INVALID_REQUEST, 422)

    only_path_wrong = api.create_care_unit(
        NON_EXISTENT_UUID, f.care_unit_payload(care_level="NURSING"), admin
    )
    validate_error(only_path_wrong, ERR_HOME_NOT_FOUND, 404)

    _rows, meta = validate_paginated(
        api.list_home_care_units(home["id"], admin, {"limit": 10})
    )
    assert_page_meta(meta, total_count=0)

    unit = validate_success(
        api.create_care_unit(home["id"], f.care_unit_payload(care_level="NURSING"), admin),
        201,
    )
    assert_fields(unit, veterans_home_id=home["id"], care_level="NURSING")

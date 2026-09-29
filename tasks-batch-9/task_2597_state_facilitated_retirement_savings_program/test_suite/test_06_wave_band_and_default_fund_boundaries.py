"""
Threshold behaviour of the mandate's lowest coverage band and of the default
fund selector's target-year comparison.

Both rules are stated as inclusive comparisons, so each is probed at the exact
threshold and one step past it: a five-employee firm against a four-employee
one, and one identical target-date fund seen by two savers whose retirement
years sit either side of that fund's landing year.
"""

from test_helpers import (
    PARTICIPANT_ROSA,
    PARTICIPANT_TOMAS,
    EMPLOYER_HARBOR,
    EMPLOYER_ORCHARD,
    account_for_participant,
    active_election,
    assert_fields,
    build_employer_environment,
    build_program_configuration,
    create_employer,
    create_enrollment,
    create_participant,
    read_employer,
    run_auto_enrollment,
    set_clock,
)

# A menu whose target-date and capital-preservation options are deliberately
# split on the flag that governs the automatic default selector.
TARGET_DATE_2040_SELECTABLE = {
    "fund_code": "TDF2040",
    "name": "Target Retirement 2040",
    "category": "TARGET_DATE",
    "target_year": 2040,
    "expense_ratio_bp": 25,
    "default_eligible": True,
}
TARGET_DATE_2045_NOT_SELECTABLE = {
    "fund_code": "TDF2045",
    "name": "Target Retirement 2045",
    "category": "TARGET_DATE",
    "target_year": 2045,
    "expense_ratio_bp": 40,
    "default_eligible": False,
}
MONEY_MARKET_SELECTABLE = {
    "fund_code": "MMKT01",
    "name": "Government Money Market",
    "category": "CAPITAL_PRESERVATION",
    "expense_ratio_bp": 20,
    "default_eligible": True,
}
STABLE_VALUE_NOT_SELECTABLE = {
    "fund_code": "STABLE1",
    "name": "Stable Value Trust",
    "category": "CAPITAL_PRESERVATION",
    "expense_ratio_bp": 15,
    "default_eligible": False,
}

SPLIT_FUND_MENU = [
    TARGET_DATE_2040_SELECTABLE,
    TARGET_DATE_2045_NOT_SELECTABLE,
    MONEY_MARKET_SELECTABLE,
    STABLE_VALUE_NOT_SELECTABLE,
]

ACTIVATION_CLOCK = "2026-02-01T00:00:00Z"


def _activate_two_savers_on_the_split_menu(api):
    """
    Configure the split fund menu, register one employer, enrol a saver who
    reaches 65 in 2040 and a saver who reaches 65 in 2045, then let the
    auto-enrolment batch open both accounts and choose both default funds.
    """
    env = build_employer_environment(api, funds=SPLIT_FUND_MENU)
    tomas = create_participant(api, PARTICIPANT_TOMAS)
    rosa = create_participant(api, PARTICIPANT_ROSA)
    create_enrollment(api, env["employer_id"], tomas["id"], "2026-01-05", 8400000)
    create_enrollment(api, env["employer_id"], rosa["id"], "2026-01-05", 9600000)
    set_clock(api, ACTIVATION_CLOCK)
    env["batch_result"] = run_auto_enrollment(api)
    env["tomas_id"] = tomas["id"]
    env["rosa_id"] = rosa["id"]
    return env


def _sole_allocation(election):
    """Return the single allocation entry of a default fund election."""
    entries = election["allocations"]
    assert len(entries) == 1, (
        f"Expected exactly one allocation entry, got {entries}"
    )
    return entries[0]


def test_headcount_of_exactly_five_lands_in_the_third_wave(api):
    """
    The smallest headcount the mandate still covers must resolve to the third
    wave with a concrete June 2027 deadline and a pending mandate dimension.

    "The headcount is matched against four descending bands, and the band fixes
    both `wave_tier` and `registration_deadline`: a headcount of at least 100
    lands in `WAVE_1` with a deadline of 30 June 2026; a headcount from 50
    through 99 inclusive lands in `WAVE_2` with a deadline of 31 December 2026;
    a headcount from 5 through 49 inclusive lands in `WAVE_3` with a deadline of
    30 June 2027; and a headcount of 4 or fewer lands in `NOT_COVERED`, whose
    `registration_deadline` is null because there is nothing to register for."

    Design: Difficulty/boundary_precision_check/employee_count_five_versus_four_flips_wave_coverage
    """
    build_program_configuration(api)

    employer = create_employer(api, EMPLOYER_HARBOR)

    assert_fields(employer, {
        "employee_count": 5,
        "wave_tier": "WAVE_3",
        "registration_deadline": "2027-06-30",
        "registration_status": "PENDING_REGISTRATION",
        "compliance_status": "COMPLIANT",
    }, label="five-employee employer")


def test_headcount_of_four_falls_out_of_the_mandate_entirely(api):
    """
    One employee below the floor the firm is not covered at all: no wave, no
    deadline, and the mandate dimension opens at the small-employer exemption
    rather than at pending registration.

    "On creation, an employer whose tier resolves to `NOT_COVERED` is placed
    directly in `EXEMPT_SMALL` rather than in `PENDING_REGISTRATION`; every
    covered employer starts in `PENDING_REGISTRATION`."

    Design: Difficulty/boundary_precision_check/employee_count_five_versus_four_flips_wave_coverage
    """
    build_program_configuration(api)

    employer = create_employer(api, EMPLOYER_ORCHARD)

    assert_fields(employer, {
        "employee_count": 4,
        "wave_tier": "NOT_COVERED",
        "registration_deadline": None,
        "registration_status": "EXEMPT_SMALL",
        "compliance_status": "COMPLIANT",
    }, label="four-employee employer")


def test_one_employee_separates_a_covered_deadline_from_no_deadline_at_all(api):
    """
    Read back side by side, the two firms differ on every mandate figure: the
    five-employee firm keeps a plain calendar deadline while the four-employee
    firm has none, which is the whole content of the lowest band boundary.

    "Deadlines are plain calendar dates with no time component."

    Design: Difficulty/boundary_precision_check/employee_count_five_versus_four_flips_wave_coverage
    """
    build_program_configuration(api)
    covered = create_employer(api, EMPLOYER_HARBOR)
    uncovered = create_employer(api, EMPLOYER_ORCHARD)

    covered = read_employer(api, covered["id"])
    uncovered = read_employer(api, uncovered["id"])

    assert covered["wave_tier"] != uncovered["wave_tier"], (
        "A five-employee firm and a four-employee firm must not share a wave"
    )
    assert covered["registration_deadline"] == "2027-06-30"
    assert uncovered["registration_deadline"] is None
    assert covered["registration_status"] == "PENDING_REGISTRATION"
    assert uncovered["registration_status"] == "EXEMPT_SMALL"


def test_target_date_fund_qualifies_on_equality_with_the_retirement_year(api):
    """
    A saver who reaches 65 in 2040 is placed in the 2040 target-date fund,
    because the selector admits a landing year equal to the retirement year.

    "It then builds a first candidate pool from every menu option whose
    `category` is `TARGET_DATE`, whose `status` is `OPEN`, whose
    `default_eligible` is true, and whose `target_year` is greater than or equal
    to that retirement year."

    Design: Difficulty/boundary_precision_check/default_fund_target_year_inclusive_at_participant_retirement_year
    """
    env = _activate_two_savers_on_the_split_menu(api)
    assert_fields(env["batch_result"], {
        "activated_count": 2,
        "accounts_opened_count": 2,
        "skipped_count": 0,
    }, label="auto-enrolment run")

    account = account_for_participant(api, env["tomas_id"])
    election = active_election(api, account["id"])

    entry = _sole_allocation(election)
    assert entry["fund_code"] == "TDF2040"
    assert entry["allocation_bp"] == 10000
    assert_fields(election, {
        "selection_basis": "TARGET_DATE_GLIDE_PATH",
        "source": "SYSTEM_DEFAULT",
        "status": "ACTIVE",
    }, label="default election of the 2040 saver")


def test_the_same_fund_one_year_short_forces_the_capital_preservation_fallback(api):
    """
    A saver who reaches 65 in 2045 cannot be placed in that identical 2040 fund,
    and with no selectable target-date option left the selector falls back to the
    cheapest money-market option instead.

    "If the first pool is empty, the selector falls back to a second pool of
    every option whose `category` is `CAPITAL_PRESERVATION`, whose `status` is
    `OPEN` and whose `default_eligible` is true, picking the smallest
    `expense_ratio_bp` and breaking ties on the earliest creation; that election
    records `selection_basis` as `CAPITAL_PRESERVATION_FALLBACK`."

    Design: Difficulty/boundary_precision_check/default_fund_target_year_inclusive_at_participant_retirement_year
    """
    env = _activate_two_savers_on_the_split_menu(api)

    account = account_for_participant(api, env["rosa_id"])
    election = active_election(api, account["id"])

    entry = _sole_allocation(election)
    assert entry["fund_code"] == "MMKT01"
    assert entry["allocation_bp"] == 10000
    assert_fields(election, {
        "selection_basis": "CAPITAL_PRESERVATION_FALLBACK",
        "source": "SYSTEM_DEFAULT",
        "status": "ACTIVE",
    }, label="default election of the 2045 saver")


def test_the_selector_skips_cheaper_funds_that_are_not_default_eligible(api):
    """
    Neither saver is placed in the cheaper stable-value option nor in the
    matching 2045 target-date option, because both are flagged out of the
    automatic default selector however attractive their expense ratio is.

    "A successful default election holds exactly one allocation entry at the full
    10000 basis points and records `source` as `SYSTEM_DEFAULT`."

    Design: Difficulty/boundary_precision_check/default_fund_target_year_inclusive_at_participant_retirement_year
    """
    env = _activate_two_savers_on_the_split_menu(api)

    chosen = []
    for participant_id in (env["tomas_id"], env["rosa_id"]):
        account = account_for_participant(api, participant_id)
        election = active_election(api, account["id"])
        entry = _sole_allocation(election)
        assert election["source"] == "SYSTEM_DEFAULT"
        assert entry["allocation_bp"] == 10000
        chosen.append(entry["fund_code"])

    assert "STABLE1" not in chosen, (
        "A fund flagged out of the default selector must never be chosen"
    )
    assert "TDF2045" not in chosen, (
        "A fund flagged out of the default selector must never be chosen"
    )
    assert chosen == ["TDF2040", "MMKT01"]

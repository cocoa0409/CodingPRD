"""Pre-tax exclusion arithmetic, ordinance headcount filtering and the program cap.

Four concerns share this module because all four are pure calculations whose
inputs are ordinary program setup values and whose outputs are exact whole-cent
integers or exact counts:

* the ratio cap as the binding ceiling of the four-ceiling exclusion waterfall,
  and the post-tax spill it produces;
* the truncation discipline of that ratio cap, proved on a deliberate half-cent;
* the three independent filters applied to an ordinance covered headcount;
* the strictly-greater-than breach test that decides whether a funded
  commitment landing exactly on the program cap suspends the program.

Every expected figure below is computed by hand from the documented formula and
asserted as a literal integer.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    PROGRAM_ADMIN,
    assert_account_conservation,
    assert_entry_types,
    assert_exclusion_split,
    assert_ledger_matches_account,
    make_compliance_reviewer_headers,
)
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx


def test_01_ratio_cap_is_the_binding_ceiling_and_the_overage_spills_to_posttax(api):
    """PRD 3.4: "the ratio cap is that requested total multiplied by the employer's
    `pretax_ratio_cap_pct` and divided by one hundred, truncated toward zero to a
    whole number of cents"
    PRD 3.4: "`excluded_amount_cents` is then the smallest of those four values:
    the requested `pretax_amount_cents`, the group headroom, the category cap, and
    the ratio cap."
    PRD 3.4: "Under `SPILL_TO_POSTTAX` the overage is simply reclassified, and
    `posttax_effective_cents` becomes the requested `posttax_amount_cents` plus
    `posttax_spill_cents`"
    PRD 3.4: "which runs when an election is created and again on every amendment,
    and which sets `exclusion_basis` to `ELECTED_BASIS`"

    Design: Corner/calculations/exclusion_split_ratio_cap_is_the_binding_ceiling_and_spills
    """
    base = fx.make_program_with_participant(
        api,
        region_code=C.REGION_AUS,
        employer_overrides={
            "legal_name": "Ratio Cap Co",
            "transit_group_limit_cents": 30000,
            "parking_group_limit_cents": 30000,
            "program_cap_cents": 5000000,
            "pretax_ratio_cap_pct": 80,
        },
        category_overrides={
            "category_type": "TRANSIT_PASS",
            "monthly_exclusion_limit_cents": 30000,
        },
    )
    account_version = fx.current_account_version(api, base["account"]["id"])

    election = validate_success(
        api.create_election(
            f.election_payload(
                base["employee"]["id"],
                base["window"]["id"],
                base["category"]["id"],
                account_version,
                pretax_amount_cents=10000,
                posttax_amount_cents=0,
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )

    # Requested total = 10000 + 0 = 10000 cents.
    # Ceiling 1, group headroom  = 30000 - 0 consumed = 30000  (slack).
    # Ceiling 2, category cap    = 30000                        (slack).
    # Ceiling 3, ratio cap       = 10000 * 80 / 100 = 8000      (binding).
    # Ceiling 4, requested pretax= 10000                        (slack).
    # excluded_amount_cents = min(10000, 30000, 30000, 8000) = 8000
    # posttax_spill_cents   = 10000 - 8000                  = 2000
    # posttax_effective     = requested posttax 0 + spill 2000 = 2000
    assert_exclusion_split(
        election,
        excluded_amount_cents=8000,
        posttax_spill_cents=2000,
        total_amount_cents=10000,
        exclusion_basis="ELECTED_BASIS",
    )
    assert election["posttax_effective_cents"] == 2000, (
        "posttax_effective_cents must be the requested 0 plus the 2000-cent spill, "
        f"got {election['posttax_effective_cents']}"
    )
    assert election["excluded_amount_cents"] != 10000, (
        "10000 is what ignoring the ratio cap entirely would produce"
    )
    assert election["funding_status"] == "PENDING", election["funding_status"]


def test_02_ratio_cap_truncates_an_exact_half_cent_downward(api):
    """PRD 2.8: "the pre-tax ratio cap on an election truncates toward zero rather
    than rounding: the capped amount is the largest whole number of cents not
    exceeding the requested total multiplied by the employer's permitted pre-tax
    percentage divided by one hundred."
    PRD 3.4: "Whatever pre-tax the employee asked for beyond that becomes the
    overage: `posttax_spill_cents` is the requested `pretax_amount_cents` minus
    `excluded_amount_cents`."

    Design: Corner/calculations/ratio_cap_uses_floor_not_round_half_up_on_a_half_cent
    """
    base = fx.make_program_with_participant(
        api,
        region_code=C.REGION_CHI,
        employer_overrides={
            "legal_name": "Truncation Co",
            "transit_group_limit_cents": 30000,
            "parking_group_limit_cents": 30000,
            "program_cap_cents": 5000000,
            "pretax_ratio_cap_pct": 45,
        },
        category_overrides={
            "category_type": "TRANSIT_PASS",
            "monthly_exclusion_limit_cents": 30000,
        },
    )
    account_version = fx.current_account_version(api, base["account"]["id"])

    election = validate_success(
        api.create_election(
            f.election_payload(
                base["employee"]["id"],
                base["window"]["id"],
                base["category"]["id"],
                account_version,
                pretax_amount_cents=1010,
                posttax_amount_cents=0,
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )

    # Requested total = 1010 + 0 = 1010 cents; ratio cap percentage is 45.
    # 1010 * 45 / 100 = 454.5 exactly -- a deliberate half-cent.
    # Truncated toward zero: 454.  Round half up would give 455.
    # excluded_amount_cents = min(1010, 30000, 30000, 454) = 454
    # posttax_spill_cents   = 1010 - 454 = 556   (555 under the wrong rounding)
    assert_exclusion_split(
        election,
        excluded_amount_cents=454,
        posttax_spill_cents=556,
        total_amount_cents=1010,
        exclusion_basis="ELECTED_BASIS",
    )
    assert election["posttax_effective_cents"] == 556, (
        f"posttax_effective_cents must be 0 + 556, got {election['posttax_effective_cents']}"
    )
    assert election["excluded_amount_cents"] != 455, (
        "455 is the round-half-up answer; the 454.5 half-cent must truncate"
    )


def test_03_ratio_cap_truncates_a_fraction_above_the_half_cent(api):
    """PRD 2.8: "the pre-tax ratio cap on an election truncates toward zero rather
    than rounding: the capped amount is the largest whole number of cents not
    exceeding the requested total multiplied by the employer's permitted pre-tax
    percentage divided by one hundred."
    PRD 3.4: "Whatever pre-tax the employee asked for beyond that becomes the
    overage: `posttax_spill_cents` is the requested `pretax_amount_cents` minus
    `excluded_amount_cents`."

    Design: Corner/calculations/ratio_cap_uses_floor_not_round_half_up_on_a_half_cent
    """
    base = fx.make_program_with_participant(
        api,
        region_code=C.REGION_CHI,
        employer_overrides={
            "legal_name": "Truncation Above Half Co",
            "transit_group_limit_cents": 30000,
            "parking_group_limit_cents": 30000,
            "program_cap_cents": 5000000,
            "pretax_ratio_cap_pct": 45,
        },
        category_overrides={
            "category_type": "TRANSIT_PASS",
            "monthly_exclusion_limit_cents": 30000,
        },
    )
    account_version = fx.current_account_version(api, base["account"]["id"])

    election = validate_success(
        api.create_election(
            f.election_payload(
                base["employee"]["id"],
                base["window"]["id"],
                base["category"]["id"],
                account_version,
                pretax_amount_cents=1011,
                posttax_amount_cents=0,
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )

    # 1011 * 45 / 100 = 454.95 -- a fraction well above the half-cent.
    # The largest whole number of cents not exceeding 454.95 is still 454;
    # any rounding rule other than truncation would produce 455.
    # posttax_spill_cents = 1011 - 454 = 557
    assert_exclusion_split(
        election,
        excluded_amount_cents=454,
        posttax_spill_cents=557,
        total_amount_cents=1011,
        exclusion_basis="ELECTED_BASIS",
    )
    assert election["posttax_effective_cents"] == 557, (
        f"posttax_effective_cents must be 0 + 557, got {election['posttax_effective_cents']}"
    )
    assert election["excluded_amount_cents"] != 455, (
        "455 is what rounding 454.95 up would produce; the rule is truncation"
    )


def test_04_ordinance_headcount_drops_other_region_terminated_and_late_hires(api):
    """PRD 3.9: "counts the covered headcount: the employees of this employer whose
    `status` is `ACTIVE`, whose `work_region_code` equals the employer's own
    `region_code`, and whose `hire_date` falls at or before that month-end boundary"
    PRD 3.9: "Terminated employees never count, employees who report for work in a
    different region never count, and an employee hired after the assessed month
    ends never counts."
    PRD 3.9: "the assessment records `EXEMPT` with `finding`
    `EXEMPT_BELOW_THRESHOLD`; a headcount of exactly 20 is mandated, not exempt"
    PRD 3.9: "Whatever verdict is reached is written back onto the employer as
    `ordinance_mandate_status`"

    Design: Corner/calculations/ordinance_headcount_excludes_other_region_terminated_and_late_hires
    """
    built = fx.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {"category_type": "TRANSIT_PASS", "monthly_exclusion_limit_cents": 31500}
        ],
        region_code=C.REGION_SFO,
        legal_name="Roster Filter Co",
        transit_group_limit_cents=31500,
        parking_group_limit_cents=31500,
        program_cap_cents=5000000,
    )
    employer = built["employer"]

    # Two employees that satisfy all three filters.
    for external_ref in ("SFO-F1", "SFO-F2"):
        fx.make_employee(
            api,
            employer["id"],
            PROGRAM_ADMIN,
            external_ref=external_ref,
            work_region_code=C.REGION_SFO,
            hire_date="2026-02-01T00:00:00Z",
        )
    # Filter 1: reports for work in a different region.
    fx.make_employee(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        external_ref="AUS-F3",
        work_region_code=C.REGION_AUS,
        hire_date="2026-02-01T00:00:00Z",
    )
    # Filter 2: same region and hired in time, but terminated before the assessment.
    late_departure = fx.make_employee(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        external_ref="SFO-F4",
        work_region_code=C.REGION_SFO,
        hire_date="2026-02-01T00:00:00Z",
    )
    # Filter 3: hired after the assessed month's last instant (2026-08-31T23:59:59.999Z).
    fx.make_employee(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        external_ref="SFO-F5",
        work_region_code=C.REGION_SFO,
        hire_date="2026-09-15T00:00:00Z",
    )
    terminated = fx.terminate(
        api, late_departure["id"], termination_date="2026-07-01T00:00:00Z"
    )
    assert terminated["status"] == "TERMINATED", terminated["status"]

    assessment = validate_success(
        api.create_compliance_assessment(
            employer["id"],
            f.compliance_assessment_payload("2026-08"),
            make_compliance_reviewer_headers("rev-assess"),
        ),
        201,
    )

    # Five employees on the roster; the covered headcount keeps only SFO-F1 and
    # SFO-F2, so 5 - 1 (other region) - 1 (TERMINATED) - 1 (hired 2026-09-15) = 2.
    assert assessment["covered_employee_count"] == 2, (
        "covered_employee_count must be 2, not 5, 4 or 3 -- the other-region, "
        "TERMINATED and post-month hires are all filtered out; got "
        f"{assessment['covered_employee_count']}"
    )
    # 2 is strictly fewer than the 20-employee ordinance threshold.
    assert assessment["mandate_status"] == "EXEMPT", assessment["mandate_status"]
    assert assessment["finding"] == "EXEMPT_BELOW_THRESHOLD", assessment["finding"]

    employer_after = fx.read_employer(api, employer["id"])
    assert employer_after["ordinance_mandate_status"] == "EXEMPT", (
        f"verdict must be written back, got {employer_after['ordinance_mandate_status']}"
    )


def test_05_commitment_landing_exactly_on_the_program_cap_leaves_the_program_active(api):
    """PRD 3.4: "The employer's `total_pretax_committed_cents` is recomputed as the
    sum of `excluded_amount_cents` over every election whose window belongs to this
    employer and whose `funding_status` is exactly `FUNDED`."
    PRD 3.4: "A committed total exactly equal to `program_cap_cents` does **not**
    suspend the program; only a breach does."
    PRD 3.4: "which runs at lock time and sets `exclusion_basis` to `FUNDED_BASIS`"
    PRD 3.4: "the account's `contributed_cents` increases by that same
    `total_amount_cents`, `available_balance_cents` is recomputed against the
    conservation identities, `ledger_entry_count` is incremented, and
    `BenefitAccount.version` advances by 1"

    Design: Corner/calculations/commitment_exactly_equal_to_program_cap_does_not_suspend
    """
    base = fx.make_program_with_participant(
        api,
        region_code=C.REGION_AUS,
        employer_overrides={
            "legal_name": "Exact Cap Co",
            "transit_group_limit_cents": 30000,
            "parking_group_limit_cents": 30000,
            "program_cap_cents": 5000,
        },
        category_overrides={
            "category_type": "TRANSIT_PASS",
            "monthly_exclusion_limit_cents": 30000,
        },
    )
    election = fx.make_election(
        api,
        base["employee"]["id"],
        base["window"]["id"],
        base["category"]["id"],
        base["account"]["id"],
        pretax_amount_cents=5000,
        posttax_amount_cents=0,
    )

    window = validate_success(
        api.lock_election_window(base["window"]["id"], PROGRAM_ADMIN), 200
    )
    assert window["status"] == "LOCKED", window["status"]

    # The lone funded election excludes min(5000, 30000, 30000, 5000 * 100 / 100)
    # = 5000 cents, so total_pretax_committed_cents = 5000, which is exactly
    # program_cap_cents.  The breach test is strictly greater-than: 5000 > 5000 is
    # false, so no suspension fires.
    employer_after = fx.read_employer(api, base["employer"]["id"])
    assert employer_after["total_pretax_committed_cents"] == 5000, (
        f"committed total must be 5000, got {employer_after['total_pretax_committed_cents']}"
    )
    assert employer_after["program_status"] == "ACTIVE", (
        "program_status must stay ACTIVE at exactly the cap, got "
        f"{employer_after['program_status']}"
    )

    election_after = fx.read_election(api, election["id"])
    assert election_after["funding_status"] == "FUNDED", election_after["funding_status"]
    assert election_after["excluded_amount_cents"] == 5000, (
        election_after["excluded_amount_cents"]
    )
    assert election_after["exclusion_basis"] == "FUNDED_BASIS", (
        election_after["exclusion_basis"]
    )

    account_after = fx.read_account(api, base["account"]["id"])
    assert account_after["contributed_cents"] == 5000, account_after["contributed_cents"]
    assert account_after["available_balance_cents"] == 5000, (
        account_after["available_balance_cents"]
    )
    assert_account_conservation(account_after)

    entries = fx.read_ledger(api, base["account"]["id"])
    assert_entry_types(entries, ["CONTRIBUTION"])
    assert_ledger_matches_account(account_after, entries)

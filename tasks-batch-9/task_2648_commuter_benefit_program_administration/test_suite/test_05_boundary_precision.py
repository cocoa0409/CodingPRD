"""Numeric boundary precision in the commuter benefit program.

Three independent thresholds are exercised on both sides, one unit apart, with
exact expected integers rather than ranges:

* the local ordinance headcount that separates an exempt employer from a
  mandated one,
* the auto-substantiation ceiling that separates a swipe cleared without
  documentation from one that must wait for it, and
* the sub-cent rounding point of the regional handling surcharge charged on a
  single procurement invoice line.

Every test builds its own employer program from scratch through the documented
endpoints, because the service is restarted against an empty database before
each test.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import PROGRAM_ADMIN, fixtures as fx
from test_helpers.assertions import (
    assert_account_conservation,
    assert_append_only_common_fields,
    assert_invoice_totals,
    assert_ledger_matches_account,
    assert_ledger_sequence,
    assert_media_line,
)
from test_helpers.constants import REGION_AUS, REGION_CHI, REGION_SEA
from test_helpers.factories import card_transaction_payload
from test_helpers.test_users import (
    make_compliance_reviewer_headers,
    make_order_desk_headers,
)

ORDINANCE_MONTH = "2026-08"
SEATTLE_HIRE_DATE = "2026-01-05T00:00:00Z"
REVIEWER = "reviewer-okafor"
DESK = "desk-precision"


# ---------------------------------------------------------------------------
# Composite state builders used by the tests in this module.
# ---------------------------------------------------------------------------
def _build_seattle_program(api, headcount: int) -> dict:
    """An ACTIVE employer in the ordinance-covered US-WA-SEA region whose transit
    group limit sits exactly on the ordinance minimum and which offers one
    ACTIVE pre-tax TRANSIT_PASS category, staffed with ``headcount`` ACTIVE
    employees who all report for work in that same region.

    Only the headcount varies between the two sides of the ordinance boundary.
    """
    built = fx.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {
                "category_type": "TRANSIT_PASS",
                "monthly_exclusion_limit_cents": 30000,
                "pretax_allowed": True,
                "posttax_allowed": True,
            }
        ],
        legal_name="Emerald City Transit Benefits",
        region_code=REGION_SEA,
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
        program_cap_cents=5000000,
    )
    employer = built["employer"]
    roster = fx.make_roster(
        api,
        employer["id"],
        headcount,
        work_region_code=REGION_SEA,
        hire_date=SEATTLE_HIRE_DATE,
        prefix="SEA",
    )
    return {
        "employer": employer,
        "category": built["categories"][0],
        "roster": roster,
    }


def _assess(api, employer_id: str, reviewer_user_id: str = REVIEWER) -> dict:
    """Run one ordinance assessment for the pinned month and return the row."""
    return validate_success(
        api.create_compliance_assessment(
            employer_id,
            {"assessment_month": ORDINANCE_MONTH},
            make_compliance_reviewer_headers(reviewer_user_id),
        ),
        201,
    )


def _build_funded_chicago_account(api) -> dict:
    """An employee in the non-covered US-IL-CHI region whose TRANSIT_PASS benefit
    account has been credited 10000 cents by a locked window's funding cascade.

    That balance comfortably covers the two swipes that straddle the
    auto-substantiation ceiling, so neither is refused on balance grounds.
    """
    return fx.make_funded_election(
        api,
        region_code=REGION_CHI,
        pretax_amount_cents=10000,
        employer_overrides={
            "legal_name": "Chicago Transit Card Co",
            "transit_group_limit_cents": 30000,
            "parking_group_limit_cents": 30000,
            "pretax_ratio_cap_pct": 100,
            "program_cap_cents": 5000000,
        },
        category_overrides={
            "category_type": "TRANSIT_PASS",
            "monthly_exclusion_limit_cents": 30000,
        },
    )


def _swipe(api, election_id: str, amount_cents: int, transaction_at: str) -> dict:
    """Ingest one settled transit swipe at a permitted merchant category code."""
    return validate_success(
        api.create_card_transaction(
            card_transaction_payload(
                election_id,
                amount_cents=amount_cents,
                merchant_category_code=4111,
                merchant_name="CTA VENTRA RELOAD",
                transaction_at=transaction_at,
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )


def _build_priced_batch(api, unit_prices: list) -> dict:
    """One OPEN procurement batch for US-TX-AUS carrying one PENDING media line
    per entry in ``unit_prices``.

    Each line belongs to a different employee and a different catalogue product,
    so no line can be removed by a supersede-cancel and every line is priced
    when the batch is sealed.
    """
    built = fx.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {
                "category_type": "TRANSIT_PASS",
                "monthly_exclusion_limit_cents": 30000,
            }
        ],
        legal_name="Austin Precision Passes",
        region_code=REGION_AUS,
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
        pretax_ratio_cap_pct=100,
        program_cap_cents=5000000,
    )
    employer = built["employer"]
    category = built["categories"][0]
    window = fx.make_open_window(api, employer["id"], PROGRAM_ADMIN)
    batch = fx.make_open_batch(api, window["id"], REGION_AUS, DESK)

    orders = []
    for index, unit_price_cents in enumerate(unit_prices, start=1):
        media = fx.make_transit_media(
            api,
            region_code=REGION_AUS,
            eligible_category_type="TRANSIT_PASS",
            unit_price_cents=unit_price_cents,
            sku=f"AUS-PRECISION-{index:02d}",
            requires_physical_fulfillment=True,
        )
        enrolled = fx.make_enrolled_employee(
            api,
            employer["id"],
            category["id"],
            PROGRAM_ADMIN,
            external_ref=f"AUS-PREC-{index:02d}",
            work_region_code=REGION_AUS,
        )
        election = fx.make_election(
            api,
            enrolled["employee"]["id"],
            window["id"],
            category["id"],
            enrolled["account"]["id"],
            pretax_amount_cents=unit_price_cents,
            transit_media_id=media["id"],
            media_quantity=1,
        )
        orders.append(
            fx.make_media_order(
                api, election["id"], media["id"], batch["id"], DESK, quantity=1
            )
        )

    return {
        "employer": employer,
        "category": category,
        "window": window,
        "batch": batch,
        "orders": orders,
    }


# ---------------------------------------------------------------------------
# The ordinance headcount boundary: 19 employees versus 20.
# ---------------------------------------------------------------------------
def test_01_ordinance_headcount_of_nineteen_is_exempt_below_threshold(api):
    """PRD 3.9: "and then counts the covered headcount: the employees of this
    employer whose `status` is `ACTIVE`, whose `work_region_code` equals the
    employer's own `region_code`, and whose `hire_date` falls at or before that
    month-end boundary."
    PRD 3.9: "Otherwise, if the covered headcount is **strictly fewer than 20**
    employees, the assessment records `EXEMPT` with `finding`
    `EXEMPT_BELOW_THRESHOLD`; a headcount of exactly 20 is mandated, not exempt."
    PRD 3.9: "The result is recorded on the assessment as
    `covered_employee_count`, and the employer's `transit_group_limit_cents` at
    assessment time is snapshotted alongside it as
    `assessed_transit_group_limit_cents`."
    PRD 2.4: "A `ComplianceAssessment` likewise carries only `id` and
    `created_at`, with no `updated_at` and no `version`, and is immutable from
    the moment it is appended."

    Design: Difficulty/boundary_precision_check/ordinance_headcount_boundary_nineteen_exempt_versus_twenty_mandated
    """
    program = _build_seattle_program(api, 19)

    assessment = _assess(api, program["employer"]["id"])

    assert assessment["covered_employee_count"] == 19, (
        "19 ACTIVE US-WA-SEA employees hired before the month-end boundary must "
        f"all count, got {assessment['covered_employee_count']}"
    )
    assert assessment["mandate_status"] == "EXEMPT", (
        "a headcount one short of the ordinance threshold is exempt, got "
        f"{assessment['mandate_status']}"
    )
    assert assessment["finding"] == "EXEMPT_BELOW_THRESHOLD", (
        f"expected EXEMPT_BELOW_THRESHOLD, got {assessment['finding']}"
    )
    assert assessment["assessed_transit_group_limit_cents"] == 30000
    assert_append_only_common_fields(assessment)


def test_02_ordinance_headcount_of_exactly_twenty_is_mandated_and_compliant(api):
    """PRD 3.9: "Otherwise, if the covered headcount is **strictly fewer than
    20** employees, the assessment records `EXEMPT` with `finding`
    `EXEMPT_BELOW_THRESHOLD`; a headcount of exactly 20 is mandated, not exempt."
    PRD 3.9: "The service counts the qualifying transit offerings — the
    employer's benefit categories whose `status` is `ACTIVE`, whose
    `pretax_allowed` is true, and whose `category_type` is `TRANSIT_PASS` or
    `VANPOOL` — and records that count as `qualifying_transit_offering_count`."
    PRD 3.9: "Otherwise, if the employer's `transit_group_limit_cents` is
    strictly below the ordinance minimum of 30000 cents — three hundred dollars
    a month — the assessment records `MANDATED_NONCOMPLIANT` with `finding`
    `DEFICIENT_LIMIT_BELOW_MINIMUM`. Otherwise it records `MANDATED_COMPLIANT`
    with `finding` `COMPLIANT`."

    Design: Difficulty/boundary_precision_check/ordinance_headcount_boundary_nineteen_exempt_versus_twenty_mandated
    """
    program = _build_seattle_program(api, 20)

    assessment = _assess(api, program["employer"]["id"])

    assert assessment["covered_employee_count"] == 20, (
        f"expected exactly 20 covered employees, got "
        f"{assessment['covered_employee_count']}"
    )
    assert assessment["qualifying_transit_offering_count"] == 1, (
        "one ACTIVE pre-tax TRANSIT_PASS category qualifies, got "
        f"{assessment['qualifying_transit_offering_count']}"
    )
    assert assessment["assessed_transit_group_limit_cents"] == 30000, (
        "a transit group limit exactly on the ordinance minimum is not below it"
    )
    assert assessment["mandate_status"] == "MANDATED_COMPLIANT", (
        "a headcount of exactly 20 is mandated, not exempt, and a compliant "
        f"offering makes it MANDATED_COMPLIANT, got {assessment['mandate_status']}"
    )
    assert assessment["finding"] == "COMPLIANT", (
        f"expected COMPLIANT, got {assessment['finding']}"
    )


def test_03_one_extra_hire_flips_the_ordinance_verdict_onto_the_employer(api):
    """PRD 3.9: "Otherwise, if the covered headcount is **strictly fewer than
    20** employees, the assessment records `EXEMPT` with `finding`
    `EXEMPT_BELOW_THRESHOLD`; a headcount of exactly 20 is mandated, not exempt."
    PRD 3.9: "Whatever verdict is reached is written back onto the employer as
    `ordinance_mandate_status`, advancing `Employer.version` by 1, and that
    write-back has teeth: an employer whose `ordinance_mandate_status` is
    `MANDATED_NONCOMPLIANT` may not take on new elections or amend existing ones
    until the deficiency is cured — by adding a qualifying pre-tax transit
    offering, or by raising `transit_group_limit_cents` to the ordinance
    minimum — and re-assessed."
    PRD 2.4: "A `ComplianceAssessment` likewise carries only `id` and
    `created_at`, with no `updated_at` and no `version`, and is immutable from
    the moment it is appended."

    Design: Difficulty/boundary_precision_check/ordinance_headcount_boundary_nineteen_exempt_versus_twenty_mandated
    """
    program = _build_seattle_program(api, 19)
    employer_id = program["employer"]["id"]

    below = _assess(api, employer_id)
    employer_below = fx.read_employer(api, employer_id)

    assert below["covered_employee_count"] == 19
    assert below["mandate_status"] == "EXEMPT"
    assert below["finding"] == "EXEMPT_BELOW_THRESHOLD"
    assert employer_below["ordinance_mandate_status"] == "EXEMPT", (
        "the exempt verdict must be written back onto the employer, got "
        f"{employer_below['ordinance_mandate_status']}"
    )

    # One single extra hire in the same region, and nothing else changed.
    fx.make_employee(
        api,
        employer_id,
        PROGRAM_ADMIN,
        external_ref="SEA-20",
        work_region_code=REGION_SEA,
        hire_date=SEATTLE_HIRE_DATE,
    )

    at_threshold = _assess(api, employer_id)
    employer_at_threshold = fx.read_employer(api, employer_id)

    assert at_threshold["covered_employee_count"] == 20, (
        "the twentieth hire must be counted, got "
        f"{at_threshold['covered_employee_count']}"
    )
    assert at_threshold["mandate_status"] == "MANDATED_COMPLIANT", (
        "crossing from 19 to 20 covered employees must flip the verdict away "
        f"from EXEMPT, got {at_threshold['mandate_status']}"
    )
    assert at_threshold["finding"] == "COMPLIANT"
    assert at_threshold["qualifying_transit_offering_count"] == 1
    assert at_threshold["assessed_transit_group_limit_cents"] == 30000
    assert employer_at_threshold["ordinance_mandate_status"] == "MANDATED_COMPLIANT", (
        "the mandated verdict must overwrite the earlier exempt one on the "
        f"employer, got {employer_at_threshold['ordinance_mandate_status']}"
    )

    # The two assessments are append-only audit rows: the second does not
    # overwrite the first, and both remain individually readable.
    assert below["id"] != at_threshold["id"]
    reviewer_headers = make_compliance_reviewer_headers(REVIEWER)
    first_again = validate_success(
        api.get_compliance_assessment(below["id"], reviewer_headers), 200
    )
    second_again = validate_success(
        api.get_compliance_assessment(at_threshold["id"], reviewer_headers), 200
    )
    assert first_again["covered_employee_count"] == 19
    assert first_again["mandate_status"] == "EXEMPT"
    assert second_again["covered_employee_count"] == 20
    assert second_again["mandate_status"] == "MANDATED_COMPLIANT"
    assert_append_only_common_fields(first_again)
    assert_append_only_common_fields(second_again)


# ---------------------------------------------------------------------------
# The auto-substantiation ceiling: 2500 cents inclusive versus 2501.
# ---------------------------------------------------------------------------
def test_04_swipe_of_exactly_the_auto_substantiation_ceiling_needs_no_documents(api):
    """PRD 3.7: "Second, for a swipe whose merchant category *is* permitted, the
    amount decides: a swipe of 2500 cents or less — twenty-five dollars, with the
    boundary inclusive, so exactly 2500 clears and 2501 does not — is created in
    `AUTO_SUBSTANTIATED`, and a larger swipe is created in `PENDING_DOCS`
    awaiting documentation."
    PRD 3.7: "In both of those cases `posted_spend_cents` equals the full
    `amount_cents`."
    PRD 3.7: "Whenever `posted_spend_cents` is greater than zero the money moves
    at ingestion: one ledger entry is appended with `entry_type` `SPEND` and a
    negative `amount_cents` equal to the posted spend, with `source_entity`
    `CardTransaction` and `source_id` the transaction's identifier; the account's
    `spent_cents` increases by the posted amount and `available_balance_cents` is
    recomputed."

    Design: Difficulty/boundary_precision_check/auto_substantiation_ceiling_boundary_2500_inclusive_versus_2501
    """
    funded = _build_funded_chicago_account(api)
    account_id = funded["account"]["id"]
    assert funded["account"]["available_balance_cents"] == 10000, (
        "the locked window's funding cascade must have credited 10000 cents, got "
        f"{funded['account']['available_balance_cents']}"
    )

    transaction = _swipe(api, funded["election"]["id"], 2500, "2026-08-03T08:00:00Z")

    assert transaction["substantiation_status"] == "AUTO_SUBSTANTIATED", (
        "a swipe of exactly 2500 cents sits on the inclusive side of the ceiling, "
        f"got {transaction['substantiation_status']}"
    )
    assert transaction["posted_spend_cents"] == 2500, (
        f"expected the full 2500 cents posted, got {transaction['posted_spend_cents']}"
    )

    account = fx.read_account(api, account_id)
    assert account["spent_cents"] == 2500
    assert account["available_balance_cents"] == 7500, (
        f"10000 credited minus 2500 spent is 7500, got "
        f"{account['available_balance_cents']}"
    )
    assert_account_conservation(account)
    entries = fx.read_ledger(api, account_id)
    assert_ledger_sequence(
        entries, [("CONTRIBUTION", 10000, 10000), ("SPEND", -2500, 7500)]
    )
    assert_ledger_matches_account(account, entries)


def test_05_swipe_one_cent_above_the_ceiling_awaits_documentation(api):
    """PRD 3.7: "Second, for a swipe whose merchant category *is* permitted, the
    amount decides: a swipe of 2500 cents or less — twenty-five dollars, with the
    boundary inclusive, so exactly 2500 clears and 2501 does not — is created in
    `AUTO_SUBSTANTIATED`, and a larger swipe is created in `PENDING_DOCS`
    awaiting documentation."
    PRD 3.7: "In both of those cases `posted_spend_cents` equals the full
    `amount_cents`."
    PRD 3.7: "Whenever `posted_spend_cents` is greater than zero the money moves
    at ingestion: one ledger entry is appended with `entry_type` `SPEND` and a
    negative `amount_cents` equal to the posted spend, with `source_entity`
    `CardTransaction` and `source_id` the transaction's identifier; the account's
    `spent_cents` increases by the posted amount and `available_balance_cents` is
    recomputed."

    Design: Difficulty/boundary_precision_check/auto_substantiation_ceiling_boundary_2500_inclusive_versus_2501
    """
    funded = _build_funded_chicago_account(api)
    account_id = funded["account"]["id"]

    transaction = _swipe(api, funded["election"]["id"], 2501, "2026-08-04T08:00:00Z")

    assert transaction["substantiation_status"] == "PENDING_DOCS", (
        "one cent above the ceiling must await documentation, got "
        f"{transaction['substantiation_status']}"
    )
    assert transaction["posted_spend_cents"] == 2501, (
        "a swipe above the ceiling still posts its full amount, got "
        f"{transaction['posted_spend_cents']}"
    )

    account = fx.read_account(api, account_id)
    assert account["spent_cents"] == 2501
    assert account["available_balance_cents"] == 7499, (
        f"10000 credited minus 2501 spent is 7499, got "
        f"{account['available_balance_cents']}"
    )
    assert_account_conservation(account)
    entries = fx.read_ledger(api, account_id)
    assert_ledger_sequence(
        entries, [("CONTRIBUTION", 10000, 10000), ("SPEND", -2501, 7499)]
    )
    assert_ledger_matches_account(account, entries)


def test_06_both_sides_of_the_ceiling_post_spend_identically_on_one_account(api):
    """PRD 3.7: "Second, for a swipe whose merchant category *is* permitted, the
    amount decides: a swipe of 2500 cents or less — twenty-five dollars, with the
    boundary inclusive, so exactly 2500 clears and 2501 does not — is created in
    `AUTO_SUBSTANTIATED`, and a larger swipe is created in `PENDING_DOCS`
    awaiting documentation."
    PRD 3.7: "In both of those cases `posted_spend_cents` equals the full
    `amount_cents`."
    PRD 2.9: "First, `available_balance_cents` equals `rollover_in_cents` plus `contributed_cents`, minus `spent_cents`,
    minus `forfeited_cents`, minus `refunded_cents`, minus `reversed_cents`, minus
    `fee_charged_cents`."
    PRD 2.9: "A third, order-sensitive identity governs the log itself: each
    entry's `balance_after_cents` equals the running signed total of all entries
    for that account up to and including itself, taken in ascending `created_at`
    order."
    PRD 3.7: "Whenever `posted_spend_cents` is greater than zero the money moves
    at ingestion: one ledger entry is appended with `entry_type` `SPEND` and a
    negative `amount_cents` equal to the posted spend, with `source_entity`
    `CardTransaction` and `source_id` the transaction's identifier; the account's
    `spent_cents` increases by the posted amount and `available_balance_cents` is
    recomputed."

    Design: Difficulty/boundary_precision_check/auto_substantiation_ceiling_boundary_2500_inclusive_versus_2501
    """
    funded = _build_funded_chicago_account(api)
    account_id = funded["account"]["id"]
    election_id = funded["election"]["id"]

    at_ceiling = _swipe(api, election_id, 2500, "2026-08-03T08:00:00Z")
    over_ceiling = _swipe(api, election_id, 2501, "2026-08-04T08:00:00Z")

    assert at_ceiling["substantiation_status"] == "AUTO_SUBSTANTIATED"
    assert over_ceiling["substantiation_status"] == "PENDING_DOCS"
    assert at_ceiling["posted_spend_cents"] == 2500
    assert over_ceiling["posted_spend_cents"] == 2501

    account = fx.read_account(api, account_id)
    assert account["spent_cents"] == 5001, (
        f"2500 plus 2501 is 5001 spent, got {account['spent_cents']}"
    )
    assert account["available_balance_cents"] == 4999, (
        f"10000 credited minus 5001 spent is 4999, got "
        f"{account['available_balance_cents']}"
    )
    assert account["ledger_entry_count"] == 3, (
        "one funding credit plus two spend debits, got "
        f"{account['ledger_entry_count']}"
    )
    assert_account_conservation(account)

    entries = fx.read_ledger(api, account_id)
    assert_ledger_sequence(
        entries,
        [
            ("CONTRIBUTION", 10000, 10000),
            ("SPEND", -2500, 7500),
            ("SPEND", -2501, 4999),
        ],
    )
    assert_ledger_matches_account(account, entries)
    for entry in entries[1:]:
        assert entry["source_entity"] == "CardTransaction"
    assert {entry["source_id"] for entry in entries[1:]} == {
        at_ceiling["id"],
        over_ceiling["id"],
    }


# ---------------------------------------------------------------------------
# The per-line surcharge rounding point: an exact half cent versus just below.
# ---------------------------------------------------------------------------
def test_07_line_surcharge_on_an_exact_half_cent_rounds_away_from_zero(api):
    """PRD 2.8: "Wherever a percentage is applied to a cent amount, the result is
    converted back to whole cents at a pinned rounding point using **round half
    up** — a result exactly on the half-cent boundary rounds away from zero to
    the larger magnitude."
    PRD 3.5: "For each priced line, `line_gross_cents` is
    `unit_price_cents_snapshot` multiplied by `quantity`; `line_surcharge_cents`
    is that gross amount multiplied by the batch region's handling surcharge
    percentage and divided by one hundred, **rounded half up to whole cents for
    that line alone**; and `line_total_cents` is the gross plus the rounded
    surcharge."
    PRD 3.5: "The regional surcharge percentages are 7.5 percent for
    `US-CA-SFO`, 6.25 percent for `US-NY-NYC`, 5.0 percent for `US-IL-CHI`, 4.0
    percent for `US-WA-SEA` and 2.5 percent for `US-TX-AUS`."

    A gross of 1020 cents at the 2.5 percent Austin rate is exactly 25.5 cents of
    surcharge, which must land on 26 rather than 25.

    Design: Difficulty/boundary_precision_check/line_surcharge_round_half_up_boundary_exact_half_cent_versus_just_below
    """
    built = _build_priced_batch(api, [1020])
    order = built["orders"][0]
    assert order["unit_price_cents_snapshot"] == 1020, (
        "the line must snapshot the catalogue price, got "
        f"{order['unit_price_cents_snapshot']}"
    )

    sealed = validate_success(
        api.seal_order_batch(built["batch"]["id"], make_order_desk_headers(DESK)), 200
    )

    line = fx.read_media_order(api, order["id"])
    assert line["line_surcharge_cents"] == 26, (
        "1020 cents at 2.5 percent is exactly 25.5 and round half up gives 26, "
        f"got {line['line_surcharge_cents']}"
    )
    assert_media_line(line, 1020, 26, 1046)
    assert_invoice_totals(sealed, 1, 1046, 0, 1046)
    assert sealed["status"] == "SEALED"


def test_08_line_surcharge_just_below_the_half_cent_rounds_down(api):
    """PRD 2.8: "Wherever a percentage is applied to a cent amount, the result is
    converted back to whole cents at a pinned rounding point using **round half
    up** — a result exactly on the half-cent boundary rounds away from zero to
    the larger magnitude."
    PRD 3.5: "For each priced line, `line_gross_cents` is
    `unit_price_cents_snapshot` multiplied by `quantity`; `line_surcharge_cents`
    is that gross amount multiplied by the batch region's handling surcharge
    percentage and divided by one hundred, **rounded half up to whole cents for
    that line alone**; and `line_total_cents` is the gross plus the rounded
    surcharge."
    PRD 3.5: "The regional surcharge percentages are 7.5 percent for
    `US-CA-SFO`, 6.25 percent for `US-NY-NYC`, 5.0 percent for `US-IL-CHI`, 4.0
    percent for `US-WA-SEA` and 2.5 percent for `US-TX-AUS`."

    One cent of gross lower, a gross of 1019 cents at the same 2.5 percent rate
    is 25.475 cents of surcharge, which sits below the half-cent boundary and
    must land on 25.

    Design: Difficulty/boundary_precision_check/line_surcharge_round_half_up_boundary_exact_half_cent_versus_just_below
    """
    built = _build_priced_batch(api, [1019])
    order = built["orders"][0]
    assert order["unit_price_cents_snapshot"] == 1019

    sealed = validate_success(
        api.seal_order_batch(built["batch"]["id"], make_order_desk_headers(DESK)), 200
    )

    line = fx.read_media_order(api, order["id"])
    assert line["line_surcharge_cents"] == 25, (
        "1019 cents at 2.5 percent is 25.475 and rounds down to 25, got "
        f"{line['line_surcharge_cents']}"
    )
    assert_media_line(line, 1019, 25, 1044)
    assert_invoice_totals(sealed, 1, 1044, 0, 1044)
    assert sealed["status"] == "SEALED"


def test_09_sealed_invoice_sums_surcharges_rounded_one_line_at_a_time(api):
    """PRD 3.5: "For each priced line, `line_gross_cents` is
    `unit_price_cents_snapshot` multiplied by `quantity`; `line_surcharge_cents`
    is that gross amount multiplied by the batch region's handling surcharge
    percentage and divided by one hundred, **rounded half up to whole cents for
    that line alone**; and `line_total_cents` is the gross plus the rounded
    surcharge."
    PRD 3.5: "The batch's `line_count` is then the number of lines priced, and
    `subtotal_cents` is the plain integer sum of their `line_total_cents` values
    — an order-free sum of amounts that have already been rounded."
    PRD 3.5: "A bulk discount follows, keyed on the line count: batches of 4
    lines or fewer earn no discount at all, batches of 5 through 9 lines earn 1.5
    percent, and batches of 10 or more lines earn 3.0 percent."
    PRD 3.5: "The batch then moves `OPEN → SEALED`, `sealed_by_user_id` records
    the acting `X-User-ID`, `sealed_at` records the current logical clock
    instant, and `OrderBatch.version` advances by 1 alongside the `version` of
    every priced media line."

    Design: Difficulty/boundary_precision_check/line_surcharge_round_half_up_boundary_exact_half_cent_versus_just_below
    """
    built = _build_priced_batch(api, [1020, 1019])
    half_cent_order, just_below_order = built["orders"]

    sealed = validate_success(
        api.seal_order_batch(built["batch"]["id"], make_order_desk_headers(DESK)), 200
    )

    half_cent_line = fx.read_media_order(api, half_cent_order["id"])
    just_below_line = fx.read_media_order(api, just_below_order["id"])
    assert_media_line(half_cent_line, 1020, 26, 1046)
    assert_media_line(just_below_line, 1019, 25, 1044)

    assert sealed["subtotal_cents"] == 2090, (
        "1046 plus 1044 is 2090; a subtotal of 2089 would mean the exact 25.5 "
        f"half cent was rounded down instead of up, got {sealed['subtotal_cents']}"
    )
    assert_invoice_totals(sealed, 2, 2090, 0, 2090)
    assert sealed["status"] == "SEALED"
    assert sealed["sealed_by_user_id"] == DESK, (
        "the sealing operator identifier must be recorded, got "
        f"{sealed['sealed_by_user_id']}"
    )

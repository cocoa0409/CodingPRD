"""Athlete age-band classification and the six-step fee settlement.

Both areas are pinned by prose that fixes a single answer: which of the two
persisted ages becomes the basis age is decided by the edition's `age_basis`,
and the settlement's discount tier keys on the entry count while the surcharge
tier keys on the amount the discount itself produces.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    TEST_USERS,
    create_athlete,
    create_edition,
    create_sport,
    create_sport_event,
    get_athlete,
    open_registration,
    setup_open_edition,
    create_entry,
    pay_fees,
    validate_error,
    validate_paginated,
    validate_success,
    athlete_payload,
    unique_email,
)

OFFICER = TEST_USERS["registration_officer_headers"]
ADMIN = TEST_USERS["games_admin_headers"]

# 20 November 1971 straddles the two target dates of the reference calendar:
# 54 years old on 10 September 2026, 55 years old on 31 December 2026.
DOB_STRADDLING_BIRTHDAY = "1971-11-20"


def _edition_with_band(age_basis: str, age_group_code: str) -> dict:
    """An open edition whose one event is coded for `age_group_code`."""
    return setup_open_edition(
        edition={"age_basis": age_basis, "municipal_support_cents": 500000},
        event={"age_group_code": age_group_code},
    )


def test_reference_date_basis_puts_the_straddling_birthday_in_the_older_band():
    """PRD §3.2: "`age_at_reference` applies that count from `date_of_birth` to the
    edition's `age_reference_date`, and `age_at_first_day` applies it from
    `date_of_birth` to the edition's `competition_start_date`."
    PRD §3.2: "Which of the two becomes the athlete's **basis age** is decided by the
    edition's `age_basis`: `REFERENCE_DATE` selects `age_at_reference`,
    `FIRST_COMPETITION_DAY` selects `age_at_first_day`."
    PRD §3.2: "Otherwise the band floor is 50 plus five years for each complete
    five-year step the basis age sits above 50, and the code is that floor joined by a
    hyphen to the floor plus four — so a basis age of 67 gives the floor 65 and the code
    `65-69`."
    PRD §3.2: "Because the two age computations can straddle a birthday, the choice of
    `age_basis` is materially observable on the same row: an athlete born on 20 November
    1971, in an edition whose `competition_start_date` is 10 September 2026 and whose
    `age_reference_date` is 31 December 2026, is 54 and lands in `50-54` under the
    first-competition-day basis but is 55 and lands in `55-59` under the reference-date
    basis."

    `REFERENCE_DATE` selects `age_at_reference`, so a birth date of 20
    November 1971 is 55 against an `age_reference_date` of 31 December 2026 and
    lands in `55-59` — even though the same row also persists
    `age_at_first_day` 54 against a `competition_start_date` of 10 September
    2026.

    Design: Difficulty/dual_variant_calc/age_basis_variant_flips_athlete_age_group_band
    """
    ctx = _edition_with_band("REFERENCE_DATE", "55-59")

    response = api_client.create_athlete(
        athlete_payload(
            ctx["edition"]["id"],
            full_name="Ray Nolan",
            email=unique_email("ray.nolan"),
            date_of_birth=DOB_STRADDLING_BIRTHDAY,
        ),
        OFFICER,
    )

    athlete = validate_success(response, expected_status=201)
    assert athlete["age_at_reference"] == 55
    assert athlete["age_at_first_day"] == 54
    assert athlete["age_group_code"] == "55-59"


def test_first_competition_day_basis_puts_the_same_birthday_in_the_younger_band():
    """PRD §3.2: "`age_at_reference` applies that count from `date_of_birth` to the
    edition's `age_reference_date`, and `age_at_first_day` applies it from
    `date_of_birth` to the edition's `competition_start_date`."
    PRD §3.2: "Which of the two becomes the athlete's **basis age** is decided by the
    edition's `age_basis`: `REFERENCE_DATE` selects `age_at_reference`,
    `FIRST_COMPETITION_DAY` selects `age_at_first_day`."
    PRD §3.2: "Otherwise the band floor is 50 plus five years for each complete
    five-year step the basis age sits above 50, and the code is that floor joined by a
    hyphen to the floor plus four — so a basis age of 67 gives the floor 65 and the code
    `65-69`."
    PRD §3.2: "Because the two age computations can straddle a birthday, the choice of
    `age_basis` is materially observable on the same row: an athlete born on 20 November
    1971, in an edition whose `competition_start_date` is 10 September 2026 and whose
    `age_reference_date` is 31 December 2026, is 54 and lands in `50-54` under the
    first-competition-day basis but is 55 and lands in `55-59` under the reference-date
    basis."

    `FIRST_COMPETITION_DAY` selects `age_at_first_day`, so the identical
    birth date of 20 November 1971 is 54 against a `competition_start_date` of
    10 September 2026 and lands in `50-54`.  Both ages are still persisted
    unchanged, so only the selected basis differs between the two editions.

    Design: Difficulty/dual_variant_calc/age_basis_variant_flips_athlete_age_group_band
    """
    ctx = _edition_with_band("FIRST_COMPETITION_DAY", "50-54")

    response = api_client.create_athlete(
        athlete_payload(
            ctx["edition"]["id"],
            full_name="Ray Nolan",
            email=unique_email("ray.nolan"),
            date_of_birth=DOB_STRADDLING_BIRTHDAY,
        ),
        OFFICER,
    )

    athlete = validate_success(response, expected_status=201)
    assert athlete["age_at_reference"] == 55
    assert athlete["age_at_first_day"] == 54
    assert athlete["age_group_code"] == "50-54"


def test_the_two_bases_disagree_on_the_band_for_one_and_the_same_birth_date():
    """PRD §3.2: "Which of the two becomes the athlete's **basis age** is decided by the
    edition's `age_basis`: `REFERENCE_DATE` selects `age_at_reference`,
    `FIRST_COMPETITION_DAY` selects `age_at_first_day`."
    PRD §3.2: "Because the two age computations can straddle a birthday, the choice of
    `age_basis` is materially observable on the same row: an athlete born on 20 November
    1971, in an edition whose `competition_start_date` is 10 September 2026 and whose
    `age_reference_date` is 31 December 2026, is 54 and lands in `50-54` under the
    first-competition-day basis but is 55 and lands in `55-59` under the reference-date
    basis."

    Run both variants side by side in two editions of the same games: the
    same `date_of_birth` yields `55-59` under `REFERENCE_DATE` and `50-54`
    under `FIRST_COMPETITION_DAY`, so the configuration field alone decides
    which competitive band the row belongs to.

    Design: Difficulty/dual_variant_calc/age_basis_variant_flips_athlete_age_group_band
    """
    sport = create_sport()

    reference_edition = create_edition(
        name="Prairie Senior Games 2026 (reference basis)",
        age_basis="REFERENCE_DATE",
    )
    create_sport_event(sport["id"], reference_edition["id"], age_group_code="55-59")
    open_registration(reference_edition["id"])

    first_day_edition = create_edition(
        name="Prairie Senior Games 2026 (first-day basis)",
        host_city="Peoria",
        age_basis="FIRST_COMPETITION_DAY",
    )
    create_sport_event(sport["id"], first_day_edition["id"], age_group_code="50-54")
    open_registration(first_day_edition["id"])

    on_reference = create_athlete(
        reference_edition["id"],
        full_name="Ray Nolan",
        date_of_birth=DOB_STRADDLING_BIRTHDAY,
    )
    on_first_day = create_athlete(
        first_day_edition["id"],
        full_name="Ray Nolan",
        date_of_birth=DOB_STRADDLING_BIRTHDAY,
    )

    assert on_reference["age_group_code"] == "55-59"
    assert on_first_day["age_group_code"] == "50-54"
    assert on_reference["age_group_code"] != on_first_day["age_group_code"]


def _athlete_with_entries(entry_fee_cents_list) -> dict:
    """One open edition, one event per fee in the list, and one athlete holding a
    `SUBMITTED` entry on each of them."""
    ctx = setup_open_edition(event={"entry_fee_cents": entry_fee_cents_list[0]})
    athlete = create_athlete(ctx["edition"]["id"])
    create_entry(athlete["id"], ctx["event"]["id"])
    for index, fee in enumerate(entry_fee_cents_list[1:], start=2):
        event = create_sport_event(
            ctx["sport"]["id"],
            ctx["edition"]["id"],
            event_code=f"T{index}00M",
            entry_fee_cents=fee,
        )
        create_entry(athlete["id"], event["id"])
    return athlete


def test_fee_settlement_runs_count_keyed_discount_before_amount_keyed_surcharge():
    """PRD §3.2: "Fee settlement is recomputed from scratch at payment time — never at
    entry time — and its six steps are evaluated in a pinned order, because the discount
    tier keys on the number of entries while the surcharge tier keys on the amount the
    discount itself produces."
    PRD §3.2: "**Step one** counts the athlete's live entries: those in `SUBMITTED`,
    `UNDER_REVIEW`, `REVISION_REQUESTED`, `WAITLISTED` or `ACCEPTED`, which becomes
    `entry_count`; entries on `MEDICAL_HOLD`, `REJECTED` or `WITHDRAWN` are excluded."
    PRD §3.2: "**Step two** sums the `entry_fee_cents` of the sport event behind each of
    those same entries into `event_fees_cents`, in whole cents with no rounding."
    PRD §3.2: "**Step three** adds the base registration fee — ninety-five dollars, that
    is 9500 cents — to `event_fees_cents` to give `subtotal_cents`."
    PRD §3.2: "**Step four** picks the multi-event `discount_pct` from `entry_count`:
    zero for a single entry or none at all, five percent for two or three entries,
    twelve percent for four or five entries, and twenty percent for six or more;
    `discount_cents` is the subtotal multiplied by that percentage and rounded half up
    to whole cents, and this is the only rounding step in the whole settlement;
    `discounted_cents` is the subtotal less the discount."
    PRD §3.2: "**Step five** picks `surcharge_cents` from `discounted_cents`: nothing at
    all below two hundred and fifty dollars, fifteen dollars — 1500 cents — from two
    hundred and fifty dollars up to but not including six hundred dollars, and forty
    dollars — 4000 cents — at six hundred dollars and above."
    PRD §3.2: "**Step six** sets `fee_total_cents` to `discounted_cents` plus
    `surcharge_cents`, and pins the seven intermediate values into `fee_breakdown` under
    the keys `entry_count`, `event_fees_cents`, `subtotal_cents`, `discount_pct`,
    `discount_cents`, `discounted_cents` and `surcharge_cents`."

    Four live entries carrying 29000 cents of event fees settle to exactly
    35380 cents: subtotal 38500, a twelve-percent discount of 4620 keyed on the
    entry count, discounted 33880, and a 1500-cent surcharge keyed on that
    discounted figure.  All seven intermediate values are pinned into
    `fee_breakdown`.

    Design: Difficulty/combinatorial_formula/fee_settlement_pinned_order_count_discount_then_amount_surcharge
    """
    athlete = _athlete_with_entries([6000, 6000, 8500, 8500])

    response = api_client.pay_fees(athlete["id"], {"amount_cents": 35380}, ADMIN)

    settled = validate_success(response)
    assert settled["fee_total_cents"] == 35380
    assert settled["fee_paid_cents"] == 35380
    assert settled["registration_status"] == "REGISTERED"
    breakdown = settled["fee_breakdown"]
    assert breakdown["entry_count"] == 4
    assert breakdown["event_fees_cents"] == 29000
    assert breakdown["subtotal_cents"] == 38500
    assert float(breakdown["discount_pct"]) == 0.12
    assert breakdown["discount_cents"] == 4620
    assert breakdown["discounted_cents"] == 33880
    assert breakdown["surcharge_cents"] == 1500


def test_surcharge_reads_the_discounted_figure_not_the_subtotal():
    """PRD §3.2: "Fee settlement is recomputed from scratch at payment time — never at
    entry time — and its six steps are evaluated in a pinned order, because the discount
    tier keys on the number of entries while the surcharge tier keys on the amount the
    discount itself produces."
    PRD §3.2: "**Step three** adds the base registration fee — ninety-five dollars, that
    is 9500 cents — to `event_fees_cents` to give `subtotal_cents`."
    PRD §3.2: "**Step four** picks the multi-event `discount_pct` from `entry_count`:
    zero for a single entry or none at all, five percent for two or three entries,
    twelve percent for four or five entries, and twenty percent for six or more;
    `discount_cents` is the subtotal multiplied by that percentage and rounded half up
    to whole cents, and this is the only rounding step in the whole settlement;
    `discounted_cents` is the subtotal less the discount."
    PRD §3.2: "**Step five** picks `surcharge_cents` from `discounted_cents`: nothing at
    all below two hundred and fifty dollars, fifteen dollars — 1500 cents — from two
    hundred and fifty dollars up to but not including six hundred dollars, and forty
    dollars — 4000 cents — at six hundred dollars and above."
    PRD §3.2: "**Step six** sets `fee_total_cents` to `discounted_cents` plus
    `surcharge_cents`, and pins the seven intermediate values into `fee_breakdown` under
    the keys `entry_count`, `event_fees_cents`, `subtotal_cents`, `discount_pct`,
    `discount_cents`, `discounted_cents` and `surcharge_cents`."

    Six entries carrying 17000 cents of event fees give a subtotal of 26500 —
    above the 25000-cent surcharge threshold — but the twenty-percent discount
    of 5300 drops `discounted_cents` to 21200, which is below it.  Because the
    surcharge tier is picked from `discounted_cents`, `surcharge_cents` is 0 and
    the total is 21200, not the 22700 a subtotal-keyed surcharge would produce.

    Design: Difficulty/combinatorial_formula/fee_settlement_pinned_order_count_discount_then_amount_surcharge
    """
    athlete = _athlete_with_entries([3000, 3000, 3000, 3000, 3000, 2000])

    response = api_client.pay_fees(athlete["id"], {"amount_cents": 21200}, ADMIN)

    settled = validate_success(response)
    breakdown = settled["fee_breakdown"]
    assert breakdown["entry_count"] == 6
    assert breakdown["event_fees_cents"] == 17000
    assert breakdown["subtotal_cents"] == 26500
    assert float(breakdown["discount_pct"]) == 0.20
    assert breakdown["discount_cents"] == 5300
    assert breakdown["discounted_cents"] == 21200
    assert breakdown["surcharge_cents"] == 0
    assert settled["fee_total_cents"] == 21200


def test_tendering_the_wrong_order_s_total_is_refused_to_the_cent():
    """PRD §3.2: "Fee settlement is recomputed from scratch at payment time — never at
    entry time — and its six steps are evaluated in a pinned order, because the discount
    tier keys on the number of entries while the surcharge tier keys on the amount the
    discount itself produces."
    PRD §3.2: "**Step five** picks `surcharge_cents` from `discounted_cents`: nothing at
    all below two hundred and fifty dollars, fifteen dollars — 1500 cents — from two
    hundred and fifty dollars up to but not including six hundred dollars, and forty
    dollars — 4000 cents — at six hundred dollars and above."
    PRD §3.2: "An `Athlete` acting on their own registration, or a `GamesAdmin` acting
    for them, submits `amount_cents`, and the settlement is run; if the tendered
    `amount_cents` differs by even one cent from the `fee_total_cents` the settlement
    produces, the request is refused with `ERR_FEE_AMOUNT_MISMATCH` and nothing is
    written."

    The settlement is recomputed at payment time and the tendered figure has
    to match it exactly.  Tendering 22700 — the total a subtotal-keyed surcharge
    would have produced for the same six entries — differs from the settlement's
    21200 and is refused, with nothing written to the athlete.

    Design: Difficulty/combinatorial_formula/fee_settlement_pinned_order_count_discount_then_amount_surcharge
    """
    athlete = _athlete_with_entries([3000, 3000, 3000, 3000, 3000, 2000])

    response = api_client.pay_fees(athlete["id"], {"amount_cents": 22700}, ADMIN)

    validate_error(response, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH.value)
    unchanged = get_athlete(athlete["id"])
    assert unchanged["registration_status"] == "PENDING_PAYMENT"
    assert unchanged["fee_paid_cents"] == 0


def _two_entry_athlete(first_fee: int, second_fee: int, date_of_birth: str) -> dict:
    """One athlete holding two live entries on two events of the given fees."""
    ctx = setup_open_edition(event={"entry_fee_cents": first_fee})
    second_event = create_sport_event(
        ctx["sport"]["id"], ctx["edition"]["id"],
        event_code="T200M", entry_fee_cents=second_fee,
    )
    athlete = create_athlete(ctx["edition"]["id"], date_of_birth=date_of_birth)
    create_entry(athlete["id"], ctx["event"]["id"])
    create_entry(athlete["id"], second_event["id"])
    return athlete


def test_surcharge_stays_off_two_cents_below_the_threshold():
    """PRD §3.2: "**Step four** picks the multi-event `discount_pct` from `entry_count`:
    zero for a single entry or none at all, five percent for two or three entries,
    twelve percent for four or five entries, and twenty percent for six or more;
    `discount_cents` is the subtotal multiplied by that percentage and rounded half up
    to whole cents, and this is the only rounding step in the whole settlement;
    `discounted_cents` is the subtotal less the discount."
    PRD §3.2: "**Step five** picks `surcharge_cents` from `discounted_cents`: nothing at
    all below two hundred and fifty dollars, fifteen dollars — 1500 cents — from two
    hundred and fifty dollars up to but not including six hundred dollars, and forty
    dollars — 4000 cents — at six hundred dollars and above."
    PRD §3.2: "**Step six** sets `fee_total_cents` to `discounted_cents` plus
    `surcharge_cents`, and pins the seven intermediate values into `fee_breakdown` under
    the keys `entry_count`, `event_fees_cents`, `subtotal_cents`, `discount_pct`,
    `discount_cents`, `discounted_cents` and `surcharge_cents`."
    PRD §2.8: "The registration fee settlement rounds exactly once, on the discount
    amount, and never again."
    PRD §3.2: "On success the recomputed `fee_total_cents` and `fee_breakdown` are
    stored, `fee_paid_cents` is set equal to `fee_total_cents`, and the registration
    dimension advances `PENDING_PAYMENT` → `REGISTERED`."

    Two entries of 8407 cents each give a subtotal of 26314, a five-percent
    discount of 1315.7 rounded half up to 1316, and `discounted_cents` 24998 —
    two cents below the 25000-cent surcharge threshold — so `surcharge_cents` is
    0 and the total is 24998.

    Design: Difficulty/boundary_precision_check/fee_surcharge_boundary_at_exactly_25000_discounted_cents
    """
    athlete = _two_entry_athlete(8407, 8407, "1966-03-02")

    settled = validate_success(api_client.pay_fees(athlete["id"], {"amount_cents": 24998}, ADMIN))

    breakdown = settled["fee_breakdown"]
    assert breakdown["entry_count"] == 2
    assert breakdown["event_fees_cents"] == 16814
    assert breakdown["subtotal_cents"] == 26314
    assert breakdown["discount_cents"] == 1316
    assert breakdown["discounted_cents"] == 24998
    assert breakdown["surcharge_cents"] == 0
    assert settled["fee_total_cents"] == 24998
    assert settled["registration_status"] == "REGISTERED"


def test_surcharge_stays_off_one_cent_below_the_threshold():
    """PRD §3.2: "**Step four** picks the multi-event `discount_pct` from `entry_count`:
    zero for a single entry or none at all, five percent for two or three entries,
    twelve percent for four or five entries, and twenty percent for six or more;
    `discount_cents` is the subtotal multiplied by that percentage and rounded half up
    to whole cents, and this is the only rounding step in the whole settlement;
    `discounted_cents` is the subtotal less the discount."
    PRD §3.2: "**Step five** picks `surcharge_cents` from `discounted_cents`: nothing at
    all below two hundred and fifty dollars, fifteen dollars — 1500 cents — from two
    hundred and fifty dollars up to but not including six hundred dollars, and forty
    dollars — 4000 cents — at six hundred dollars and above."
    PRD §3.2: "**Step six** sets `fee_total_cents` to `discounted_cents` plus
    `surcharge_cents`, and pins the seven intermediate values into `fee_breakdown` under
    the keys `entry_count`, `event_fees_cents`, `subtotal_cents`, `discount_pct`,
    `discount_cents`, `discounted_cents` and `surcharge_cents`."
    PRD §2.8: "The registration fee settlement rounds exactly once, on the discount
    amount, and never again."

    Fees of 8408 and 8407 cents give a subtotal of 26315, a discount of
    1315.75 rounded half up to 1316, and `discounted_cents` 24999 — one cent
    short of the threshold — so the surcharge is still 0.

    Design: Difficulty/boundary_precision_check/fee_surcharge_boundary_at_exactly_25000_discounted_cents
    """
    athlete = _two_entry_athlete(8408, 8407, "1963-07-18")

    settled = validate_success(api_client.pay_fees(athlete["id"], {"amount_cents": 24999}, ADMIN))

    breakdown = settled["fee_breakdown"]
    assert breakdown["event_fees_cents"] == 16815
    assert breakdown["subtotal_cents"] == 26315
    assert breakdown["discount_cents"] == 1316
    assert breakdown["discounted_cents"] == 24999
    assert breakdown["surcharge_cents"] == 0
    assert settled["fee_total_cents"] == 24999


def test_surcharge_switches_on_at_exactly_the_threshold():
    """PRD §3.2: "**Step four** picks the multi-event `discount_pct` from `entry_count`:
    zero for a single entry or none at all, five percent for two or three entries,
    twelve percent for four or five entries, and twenty percent for six or more;
    `discount_cents` is the subtotal multiplied by that percentage and rounded half up
    to whole cents, and this is the only rounding step in the whole settlement;
    `discounted_cents` is the subtotal less the discount."
    PRD §3.2: "**Step five** picks `surcharge_cents` from `discounted_cents`: nothing at
    all below two hundred and fifty dollars, fifteen dollars — 1500 cents — from two
    hundred and fifty dollars up to but not including six hundred dollars, and forty
    dollars — 4000 cents — at six hundred dollars and above."
    PRD §3.2: "**Step six** sets `fee_total_cents` to `discounted_cents` plus
    `surcharge_cents`, and pins the seven intermediate values into `fee_breakdown` under
    the keys `entry_count`, `event_fees_cents`, `subtotal_cents`, `discount_pct`,
    `discount_cents`, `discounted_cents` and `surcharge_cents`."

    Fees of 8408 cents each give a subtotal of 26316, the same 1316-cent
    discount, and `discounted_cents` of exactly 25000.  The 1500-cent surcharge
    applies from 25000 upward, so the total jumps to 26500: a two-cent change of
    input swings the settlement by 1502 cents.

    Design: Difficulty/boundary_precision_check/fee_surcharge_boundary_at_exactly_25000_discounted_cents
    """
    athlete = _two_entry_athlete(8408, 8408, "1962-11-30")

    settled = validate_success(api_client.pay_fees(athlete["id"], {"amount_cents": 26500}, ADMIN))

    breakdown = settled["fee_breakdown"]
    assert breakdown["event_fees_cents"] == 16816
    assert breakdown["subtotal_cents"] == 26316
    assert breakdown["discount_cents"] == 1316
    assert breakdown["discounted_cents"] == 25000
    assert breakdown["surcharge_cents"] == 1500
    assert settled["fee_total_cents"] == 26500


def test_at_the_threshold_the_surcharge_is_inside_the_amount_that_must_be_tendered():
    """PRD §3.2: "**Step five** picks `surcharge_cents` from `discounted_cents`: nothing at
    all below two hundred and fifty dollars, fifteen dollars — 1500 cents — from two
    hundred and fifty dollars up to but not including six hundred dollars, and forty
    dollars — 4000 cents — at six hundred dollars and above."
    PRD §3.2: "**Step six** sets `fee_total_cents` to `discounted_cents` plus
    `surcharge_cents`, and pins the seven intermediate values into `fee_breakdown` under
    the keys `entry_count`, `event_fees_cents`, `subtotal_cents`, `discount_pct`,
    `discount_cents`, `discounted_cents` and `surcharge_cents`."
    PRD §3.2: "An `Athlete` acting on their own registration, or a `GamesAdmin` acting
    for them, submits `amount_cents`, and the settlement is run; if the tendered
    `amount_cents` differs by even one cent from the `fee_total_cents` the settlement
    produces, the request is refused with `ERR_FEE_AMOUNT_MISMATCH` and nothing is
    written."

    Because `fee_total_cents` at the boundary is `discounted_cents` plus the
    surcharge, tendering the bare 25000 is a mismatch against the settled 26500
    and is refused.

    Design: Difficulty/boundary_precision_check/fee_surcharge_boundary_at_exactly_25000_discounted_cents
    """
    athlete = _two_entry_athlete(8408, 8408, "1962-11-30")

    response = api_client.pay_fees(athlete["id"], {"amount_cents": 25000}, ADMIN)

    validate_error(response, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH.value)
    assert get_athlete(athlete["id"])["registration_status"] == "PENDING_PAYMENT"


def test_basis_age_of_exactly_fifty_is_admitted():
    """PRD §3.2: "A basis age below the games-wide floor of 50 is not eligible at all and
    the registration is refused with `ERR_ATHLETE_UNDER_MINIMUM_AGE`."
    PRD §3.2: "Whole years elapsed between a birth date and a target date are counted as
    the difference of the two calendar years, reduced by one when the target date's
    month-and-day pair falls earlier in the year than the birth date's month-and-day
    pair; a birthday landing exactly on the target date therefore counts as having been
    reached."
    PRD §3.2: "`age_at_reference` applies that count from `date_of_birth` to the
    edition's `age_reference_date`, and `age_at_first_day` applies it from
    `date_of_birth` to the edition's `competition_start_date`."
    PRD §3.2: "Which of the two becomes the athlete's **basis age** is decided by the
    edition's `age_basis`: `REFERENCE_DATE` selects `age_at_reference`,
    `FIRST_COMPETITION_DAY` selects `age_at_first_day`."
    PRD §3.2: "Otherwise the band floor is 50 plus five years for each complete
    five-year step the basis age sits above 50, and the code is that floor joined by a
    hyphen to the floor plus four — so a basis age of 67 gives the floor 65 and the code
    `65-69`."

    The games-wide floor is a basis age of 50 and the comparison is
    inclusive.  Under `REFERENCE_DATE` with an `age_reference_date` of 31
    December 2026, a birth date of 31 December 1976 is exactly 50 — a birthday
    landing on the target date counts as reached — and the athlete is created in
    `50-54`, even though the same row's `age_at_first_day` reads 49.

    Design: Difficulty/boundary_precision_check/minimum_eligible_age_boundary_fifty_admitted_forty_nine_rejected
    """
    ctx = _edition_with_band("REFERENCE_DATE", "50-54")

    response = api_client.create_athlete(
        athlete_payload(
            ctx["edition"]["id"], full_name="Tess Marlow", date_of_birth="1976-12-31"
        ),
        OFFICER,
    )

    athlete = validate_success(response, expected_status=201)
    assert athlete["age_at_reference"] == 50
    assert athlete["age_at_first_day"] == 49
    assert athlete["age_group_code"] == "50-54"
    assert athlete["registration_status"] == "PENDING_PAYMENT"
    assert athlete["medical_status"] == "NOT_SCREENED"


def test_basis_age_one_day_short_of_fifty_is_refused():
    """PRD §3.2: "A basis age below the games-wide floor of 50 is not eligible at all and
    the registration is refused with `ERR_ATHLETE_UNDER_MINIMUM_AGE`."
    PRD §3.2: "Whole years elapsed between a birth date and a target date are counted as
    the difference of the two calendar years, reduced by one when the target date's
    month-and-day pair falls earlier in the year than the birth date's month-and-day
    pair; a birthday landing exactly on the target date therefore counts as having been
    reached."
    PRD §3.2: "Which of the two becomes the athlete's **basis age** is decided by the
    edition's `age_basis`: `REFERENCE_DATE` selects `age_at_reference`,
    `FIRST_COMPETITION_DAY` selects `age_at_first_day`."

    One calendar day later — a birth date of 1 January 1977 — the basis age is
    49, below the floor of 50, and the registration is refused outright.

    Design: Difficulty/boundary_precision_check/minimum_eligible_age_boundary_fifty_admitted_forty_nine_rejected
    """
    ctx = _edition_with_band("REFERENCE_DATE", "50-54")

    response = api_client.create_athlete(
        athlete_payload(
            ctx["edition"]["id"],
            full_name="Uri Kessler",
            email="uri.kessler@example.com",
            date_of_birth="1977-01-01",
        ),
        OFFICER,
    )

    validate_error(response, ApiErrorId.ERR_ATHLETE_UNDER_MINIMUM_AGE.value)
    rows, _meta = validate_paginated(
        api_client.list_athletes(OFFICER, {"limit": 100, "offset": 0})
    )
    assert all(row["email"] != "uri.kessler@example.com" for row in rows)


def test_the_eligibility_floor_reads_the_edition_s_configured_basis():
    """PRD §3.2: "A basis age below the games-wide floor of 50 is not eligible at all and
    the registration is refused with `ERR_ATHLETE_UNDER_MINIMUM_AGE`."
    PRD §3.2: "Which of the two becomes the athlete's **basis age** is decided by the
    edition's `age_basis`: `REFERENCE_DATE` selects `age_at_reference`,
    `FIRST_COMPETITION_DAY` selects `age_at_first_day`."
    PRD §3.2: "At the eligibility boundary the same divergence decides admission
    outright: an athlete who is 49 on the first competition day but turns 50 before the
    reference date is refused under the first-competition-day basis and admitted under
    the reference-date basis."

    The floor is applied to the basis age, not to whichever age happens to be
    larger.  The same 31 December 1976 birth date that is admitted under
    `REFERENCE_DATE` is 49 on a `competition_start_date` of 10 September 2026 and
    is therefore refused by an edition configured for
    `FIRST_COMPETITION_DAY`.

    Design: Difficulty/boundary_precision_check/minimum_eligible_age_boundary_fifty_admitted_forty_nine_rejected
    """
    ctx = _edition_with_band("FIRST_COMPETITION_DAY", "50-54")

    response = api_client.create_athlete(
        athlete_payload(
            ctx["edition"]["id"], full_name="Tess Marlow", date_of_birth="1976-12-31"
        ),
        OFFICER,
    )

    validate_error(response, ApiErrorId.ERR_ATHLETE_UNDER_MINIMUM_AGE.value)


def _registered_single_entry_athlete() -> dict:
    """An athlete already settled at 15500 cents for one 6000-cent entry, so the
    registration dimension has left `PENDING_PAYMENT`."""
    ctx = setup_open_edition()
    athlete = create_athlete(ctx["edition"]["id"])
    create_entry(athlete["id"], ctx["event"]["id"])
    pay_fees(athlete["id"], 15500)
    return get_athlete(athlete["id"])


def test_paying_twice_reports_the_state_failure_not_the_amount_failure():
    """PRD §2.10: "Checks are evaluated in the following order, and the first failure
    decides the response."
    PRD §2.10: "The target row's own current status is a declared origin state of the
    requested transition — otherwise `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."
    PRD §2.10: "The tendered payment equals the settled fee — otherwise
    `ERR_FEE_AMOUNT_MISMATCH` (HTTP 422)."
    PRD §3.2: "On success the recomputed `fee_total_cents` and `fee_breakdown` are
    stored, `fee_paid_cents` is set equal to `fee_total_cents`, and the registration
    dimension advances `PENDING_PAYMENT` → `REGISTERED`."

    A second payment on an athlete who is already `REGISTERED` violates both
    the origin-state rule and the tendered-amount rule.  The origin-state rule is
    evaluated first, so the answer is the state failure and the amount is never
    looked at; the already-settled figures stand untouched.

    Design: Difficulty/priority_pair_validation_conflict/pay_fees_state_error_beats_fee_amount_mismatch
    """
    athlete = _registered_single_entry_athlete()
    assert athlete["registration_status"] == "REGISTERED"

    response = api_client.pay_fees(athlete["id"], {"amount_cents": 9999}, ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)
    unchanged = get_athlete(athlete["id"])
    assert unchanged["registration_status"] == "REGISTERED"
    assert unchanged["fee_paid_cents"] == 15500
    assert unchanged["fee_total_cents"] == 15500


def test_the_state_failure_survives_a_perfectly_correct_amount():
    """PRD §2.10: "Checks are evaluated in the following order, and the first failure
    decides the response."
    PRD §2.10: "The target row's own current status is a declared origin state of the
    requested transition — otherwise `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."
    PRD §2.10: "The tendered payment equals the settled fee — otherwise
    `ERR_FEE_AMOUNT_MISMATCH` (HTTP 422)."

    Repeating the payment with the exact settled figure of 15500 still fails
    on the origin state, which proves the state rule is decided before the
    tendered amount is compared at all rather than merely masking a mismatch.

    Design: Difficulty/priority_pair_validation_conflict/pay_fees_state_error_beats_fee_amount_mismatch
    """
    athlete = _registered_single_entry_athlete()

    response = api_client.pay_fees(athlete["id"], {"amount_cents": 15500}, ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)
    assert get_athlete(athlete["id"])["fee_paid_cents"] == 15500

"""Petition filing-fee computation (provisional vs final, per-record rounding) and fee waivers."""
from test_helpers import fixtures, validate_success, validate_error, ApiErrorId
from test_helpers.constants import CLOCK_START

CLERK = fixtures.CLERK

# Three-record scenario used by the provisional-vs-final tests.
#   R1 MISDEMEANOR/CONVICTED (eligible)      -> 12000*1.0 *1.075 = 12900
#   R2 FELONY_CLASS_B/DISMISSED (ineligible) -> 25000*0.5 *1.075 = 13437.5 -> 13438
#   R3 INFRACTION/ARREST_ONLY (eligible)     ->  5000*0.25*1.075 =  1343.75 -> 1344
#   provisional (ALL) = 27682 ; final (ELIGIBLE only R1+R3) = 14244
THREE_RECORDS = [
    {"offense_code": "PC-1", "offense_class": "MISDEMEANOR", "disposition": "CONVICTED",
     "disposition_date": "2019-06-01T00:00:00Z", "sentence_completion_date": "2020-01-01T00:00:00Z"},
    {"offense_code": "PC-2", "offense_class": "FELONY_CLASS_B", "disposition": "DISMISSED",
     "disposition_date": "2023-01-01T00:00:00Z"},
    {"offense_code": "PC-3", "offense_class": "INFRACTION", "disposition": "ARREST_ONLY",
     "disposition_date": "2020-01-01T00:00:00Z"},
]


def test_provisional_fee_sums_all_records_regardless_of_eligibility(api):
    """PRD §3.3: "The petition's `provisional_fee_cents` is the sum of the
    per-record fees over **all** items regardless of eligibility."
    PRD §3.3: "The rounding order is fixed: each per-record fee is rounded to whole
    cents first, and only then are the rounded per-record fees summed. The fees are
    never summed before rounding."

    Design: Difficulty/dual_variant_calc/petition_fee_provisional_vs_final
    """
    ctx = fixtures.build_petition_with_records(api, THREE_RECORDS, to_status="SCREENED")
    assert ctx["petition"]["provisional_fee_cents"] == 27682


def test_final_fee_sums_only_eligible_records(api):
    """PRD §3.5: "the system computes `final_fee_cents` as the sum of the per-record
    fees — using the same per-record formula and round-then-sum order as in Section
    3.3 — but summed only over the items whose `eligibility_at_screening` is
    `ELIGIBLE`; because ineligible items drop out, the final fee is at most the
    provisional fee."

    Design: Difficulty/dual_variant_calc/petition_fee_provisional_vs_final
    """
    ctx = fixtures.build_petition_with_records(api, THREE_RECORDS, to_status="SCREENED")
    pet_id = ctx["petition"]["id"]
    fixtures.pay_fee(api, pet_id, 27682)
    filed = fixtures.transition_petition(api, pet_id, "FILED")
    assert filed["final_fee_cents"] == 14244


def test_provisional_fee_rounds_each_record_before_summing(api):
    """PRD §3.3: "The rounding order is fixed: each per-record fee is rounded to
    whole cents first, and only then are the rounded per-record fees summed. The
    fees are never summed before rounding."

    Design: Difficulty/combinatorial_formula/filing_fee_round_per_record_then_sum
    """
    specs = [
        {"offense_code": "PC-A", "offense_class": "INFRACTION", "disposition": "ARREST_ONLY",
         "disposition_date": "2020-01-01T00:00:00Z"},
        {"offense_code": "PC-B", "offense_class": "INFRACTION", "disposition": "ARREST_ONLY",
         "disposition_date": "2020-01-01T00:00:00Z"},
        {"offense_code": "PC-C", "offense_class": "INFRACTION", "disposition": "ARREST_ONLY",
         "disposition_date": "2020-01-01T00:00:00Z"},
    ]
    ctx = fixtures.build_petition_with_records(api, specs, to_status="SCREENED")
    # round(1343.75)=1344 per record; 1344*3 = 4032 (not round(4031.25)=4031)
    assert ctx["petition"]["provisional_fee_cents"] == 4032


def test_per_record_fee_snapshot_uses_rounded_per_record_amount(api):
    """PRD §3.3: "For each `PetitionItem` it records `eligibility_at_screening` — the
    `ELIGIBLE` or `INELIGIBLE` state of its record at that moment — and
    `fee_at_screening_cents`, the per-record fee for that item."
    PRD §3.3: "The rounding order is fixed: each per-record fee is rounded to whole
    cents first, and only then are the rounded per-record fees summed."

    Design: Difficulty/combinatorial_formula/filing_fee_round_per_record_then_sum
    """
    specs = [
        {"offense_code": "PC-A", "offense_class": "INFRACTION", "disposition": "ARREST_ONLY",
         "disposition_date": "2020-01-01T00:00:00Z"},
        {"offense_code": "PC-B", "offense_class": "INFRACTION", "disposition": "ARREST_ONLY",
         "disposition_date": "2020-01-01T00:00:00Z"},
    ]
    ctx = fixtures.build_petition_with_records(api, specs, to_status="SCREENED")
    items, _meta = _list_items(api, ctx["petition"]["id"])
    assert len(items) == 2
    for item in items:
        assert item["fee_at_screening_cents"] == 1344, (
            f"each INFRACTION/ARREST_ONLY per-record fee must round to 1344, got {item}")


def test_fee_waiver_threshold_household_of_three_income_under_125(api):
    """PRD §3.4: "The system first computes the household poverty line in cents as
    1,500,000 plus 530,000 for each household member beyond the first — that is,
    1,500,000 plus (the petitioner's `household_size` minus 1) times 530,000. It
    then sets `income_threshold_cents` to that poverty line multiplied by 1.25 (the
    125% threshold), rounded to whole cents using round half up."
    PRD §3.4: "The basis is `INCOME_UNDER_125` when the petitioner's
    `annual_income_cents` is less than or equal to `income_threshold_cents` **and**
    their `monthly_liquid_assets_cents` is less than or equal to the asset cap of
    200,000 cents; both bounds are inclusive."

    Design: Difficulty/combinatorial_formula/fee_waiver_income_threshold_branches
    """
    ctx = fixtures.setup_requested_fee_waiver(
        api, income=3_000_000, household_size=3, monthly_liquid_assets_cents=150_000)
    # poverty_line = 1_500_000 + 2*530_000 = 2_560_000 ; *1.25 = 3_200_000
    assert ctx["waiver"]["income_threshold_cents"] == 3_200_000
    assert ctx["waiver"]["determination_basis"] == "INCOME_UNDER_125"


def test_fee_waiver_income_exactly_at_threshold_is_inclusive(api):
    """PRD §3.4: "The basis is `INCOME_UNDER_125` when the petitioner's
    `annual_income_cents` is less than or equal to `income_threshold_cents` **and**
    their `monthly_liquid_assets_cents` is less than or equal to the asset cap of
    200,000 cents; both bounds are inclusive."

    Design: Difficulty/combinatorial_formula/fee_waiver_income_threshold_branches
    """
    # household 1 -> poverty_line 1_500_000 ; *1.25 = 1_875_000 ; income exactly == threshold
    ctx = fixtures.setup_requested_fee_waiver(
        api, income=1_875_000, household_size=1, monthly_liquid_assets_cents=0)
    assert ctx["waiver"]["income_threshold_cents"] == 1_875_000
    assert ctx["waiver"]["determination_basis"] == "INCOME_UNDER_125", (
        "income equal to the threshold is inclusive -> INCOME_UNDER_125")


def test_grant_waiver_over_threshold_rejected(api):
    """PRD §3.4: "Granting it is permitted only when `determination_basis` is
    `INCOME_UNDER_125`; an attempt to grant a waiver whose basis is `OVER_THRESHOLD`
    is rejected with `ERR_WAIVER_NOT_ELIGIBLE` (409)."

    Design: Corner/state_machines/fee_waiver_grant_over_threshold_not_eligible
    """
    ctx = fixtures.setup_requested_fee_waiver(api, income=9_000_000, household_size=1)
    assert ctx["waiver"]["determination_basis"] == "OVER_THRESHOLD"
    resp = api.transition_fee_waiver(ctx["waiver"]["id"], {"to_status": "GRANTED"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_WAIVER_NOT_ELIGIBLE.value)


def test_granting_waiver_sets_petition_fee_waived_and_fee_due_zero(api):
    """PRD §3.4: "When a waiver is granted, the referenced petition's `fee_waived`
    flag is set to true and its `fee_due_cents` is set to 0."

    Design: Corner/endpoints/petition_fee_due_zero_when_waiver_granted
    """
    ctx = fixtures.setup_requested_fee_waiver(
        api, income=3_000_000, household_size=3, monthly_liquid_assets_cents=150_000)
    validate_success(api.transition_fee_waiver(ctx["waiver"]["id"], {"to_status": "GRANTED"}, CLERK))
    petition = validate_success(api.get_petition(ctx["petition"]["id"], CLERK))
    assert petition["fee_waived"] is True
    assert petition["fee_due_cents"] == 0


def _list_items(api, petition_id):
    from test_helpers import validate_paginated
    return validate_paginated(api.list_petition_items(CLERK, params={"petition_id": petition_id}))

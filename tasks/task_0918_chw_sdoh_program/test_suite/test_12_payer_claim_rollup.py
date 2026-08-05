"""Monthly payer claims: the provisional-versus-final input set, the pinned
rounding order, the billing-code thresholds and the anti-double-dip gate."""

from test_helpers import (
    ApiErrorId,
    assert_cents,
    assert_payer_claim,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.constants import CM_CODE_EXTENDED, CM_CODE_STANDARD
from test_helpers.factories import create_payer_claim_payload
from test_helpers.test_users import BILLING_SPECIALIST


def _june_month_with_three_encounters(employee_code, mrn):
    """Three June encounters of 48, 30 and 24 billable minutes; the first two
    submitted, the third deliberately left in DRAFT."""
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-20T00:00:00Z", employee_code=employee_code,
        mrn=mrn, full_name="Rosa Diaz", household_size=3,
        monthly_income_cents=180_000,
    )
    first = fx.submitted_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-05",
        direct_minutes=30, indirect_minutes=10, travel_minutes=0,
        documentation_minutes=5,
    )
    second = fx.submitted_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-09",
        direct_minutes=20, indirect_minutes=4, travel_minutes=0,
        documentation_minutes=3,
    )
    third = fx.create_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-12",
        direct_minutes=15, indirect_minutes=3, travel_minutes=0,
        documentation_minutes=3,
    )
    return worker, patient, chw_headers, first, second, third


def test_a_provisional_claim_counts_draft_time_and_mutates_nothing(api):
    """PRD §3.8: "**The input set.** Under either basis, the candidate
    encounters are those whose `patient_id` matches the claim's, whose
    `service_month` matches the claim's, and whose `funding_source` is
    `UNFUNDED`. The basis then filters by status. `PROVISIONAL` includes
    encounters in `DRAFT` **or** `SUBMITTED`. `FINAL` includes **only**
    encounters in `SUBMITTED`, which makes a final claim's minutes strictly
    smaller than the provisional estimate whenever any draft time exists for
    that month. Encounters in `VOIDED` or `LOCKED` never participate under
    either basis."
    PRD §3.8: "A `PROVISIONAL` claim mutates **no** encounter whatsoever:
    nothing locks, `funding_source` stays `UNFUNDED`, and the same minutes
    remain claimable later."

    Design: Difficulty/dual_variant_calc/payer_claim_provisional_vs_final_basis_divergence
    """
    worker, patient, chw_headers, first, second, third = (
        _june_month_with_three_encounters("W-001", "MRN-010")
    )
    assert first["billable_minutes"] == 48
    assert second["billable_minutes"] == 30
    assert third["billable_minutes"] == 24

    claim = validate_success(
        api.create_payer_claim(
            create_payer_claim_payload(patient["id"], "2026-06", "PROVISIONAL"),
            BILLING_SPECIALIST,
        ),
        201,
    )
    assert_payer_claim(claim)
    assert claim["claimed_minutes"] == 102, (
        f"the provisional set adds the DRAFT row too, got {claim['claimed_minutes']}"
    )
    assert claim["claimed_encounter_count"] == 3
    assert claim["units"] == 6, f"floor(102 / 15) is 6, got {claim['units']}"
    assert_cents(claim["allowed_amount_cents"], 12_900, "allowed_amount_cents")
    assert claim["billing_code"] == CM_CODE_STANDARD

    for encounter, expected_status in (
        (first, "SUBMITTED"), (second, "SUBMITTED"), (third, "DRAFT")
    ):
        reread = fx.read_encounter(encounter["id"])
        assert reread["status"] == expected_status, (
            f"the provisional claim mutated {encounter['id']}"
        )
        assert reread["funding_source"] == "UNFUNDED"


def test_a_final_claim_counts_only_submitted_time_and_locks_it(api):
    """PRD §3.8: "**What creation does.** A `FINAL` claim moves every encounter
    in its input set from `SUBMITTED` to `LOCKED`, setting each one's
    `funding_source` to `PAYER` and its `funding_claim_id` to the new claim's
    `id`."
    PRD §3.8: "Fourth, `units` is `claimed_minutes` divided by 15 and truncated
    downward to a whole number — floor, never rounding — and
    `allowed_amount_cents` is `units` multiplied by 2150 cents."

    Design: Difficulty/dual_variant_calc/payer_claim_provisional_vs_final_basis_divergence
    """
    worker, patient, chw_headers, first, second, third = (
        _june_month_with_three_encounters("W-001B", "MRN-010B")
    )
    fx.create_claim(patient["id"], "2026-06", "PROVISIONAL")

    final = validate_success(
        api.create_payer_claim(
            create_payer_claim_payload(patient["id"], "2026-06", "FINAL"),
            BILLING_SPECIALIST,
        ),
        201,
    )
    assert final["claimed_minutes"] == 78, (
        f"the final set excludes the DRAFT row, got {final['claimed_minutes']}"
    )
    assert final["claimed_encounter_count"] == 2
    assert final["units"] == 5, f"floor(78 / 15) is 5, got {final['units']}"
    assert_cents(final["allowed_amount_cents"], 10_750, "allowed_amount_cents")
    assert final["status"] == "SUBMITTED"
    assert final["denial_reason"] is None
    assert final["denied_at"] is None
    assert final["appealed_at"] is None

    for encounter in (first, second):
        reread = fx.read_encounter(encounter["id"])
        assert reread["status"] == "LOCKED"
        assert reread["funding_source"] == "PAYER"
        assert reread["funding_claim_id"] == final["id"]

    untouched = fx.read_encounter(third["id"])
    assert untouched["status"] == "DRAFT"
    assert untouched["funding_source"] == "UNFUNDED"


def test_each_encounter_is_rounded_before_the_month_is_summed(api):
    """PRD §3.8: "**The rollup.** The order of operations is pinned and is not
    interchangeable. First, each encounter in the input set is reduced to its
    own rounded billable figure — the sum of its `direct_minutes`,
    `indirect_minutes` and `documentation_minutes`, with travel excluded,
    divided by 6, rounded half up, and multiplied back by 6. Second, those
    **already-rounded** per-encounter values are added together to give
    `claimed_minutes`; the aggregate is never formed by summing raw minutes and
    rounding once at the end, and the two orders give different answers."
    PRD §3.7: "Because the rounding is half up on the quotient, a raw value
    three above a multiple of six always rounds upward — a raw 21 becomes 24, a
    raw 27 becomes 30."

    Design: Difficulty/combinatorial_formula/minute_rounding_per_encounter_before_summing
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-07-20T00:00:00Z", employee_code="W-003",
        mrn="MRN-030", full_name="Mai Tran", household_size=4,
        monthly_income_cents=200_000,
    )
    encounters = [
        fx.submitted_encounter(
            chw_headers, patient["id"], worker["id"], date,
            direct_minutes=15, indirect_minutes=3, travel_minutes=0,
            documentation_minutes=3,
        )
        for date in ("2026-07-06", "2026-07-08", "2026-07-10")
    ]
    for encounter in encounters:
        assert encounter["raw_billable_minutes"] == 21
        assert encounter["billable_minutes"] == 24

    claim = validate_success(
        api.create_payer_claim(
            create_payer_claim_payload(patient["id"], "2026-07", "FINAL"),
            BILLING_SPECIALIST,
        ),
        201,
    )
    assert claim["claimed_minutes"] == 72, (
        f"three already-rounded 24s sum to 72, got {claim['claimed_minutes']}"
    )
    assert claim["claimed_minutes"] != 66, (
        "66 is the sum-then-round answer and is the wrong order of operations"
    )


def test_the_rounded_monthly_total_drives_units_and_the_allowed_amount(api):
    """PRD §3.8: "Fourth, `units` is `claimed_minutes` divided by 15 and
    truncated downward to a whole number — floor, never rounding — and
    `allowed_amount_cents` is `units` multiplied by 2150 cents."
    PRD §3.8: "Third, the claim's `billing_code` is chosen by threshold:
    `claimed_minutes` of at least 120 selects `CM-120`; otherwise
    `claimed_minutes` of at least 60 selects `CM-60`; and anything below 60 is
    not billable at all and is rejected at rung 17 with
    `ERR_MINUTE_THRESHOLD_NOT_MET` (HTTP 422) — exactly 60 minutes qualifies for
    `CM-60`, and 59 does not."

    Design: Difficulty/combinatorial_formula/minute_rounding_per_encounter_before_summing
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-07-20T00:00:00Z", employee_code="W-003B",
        mrn="MRN-030B", full_name="Mai Tran", household_size=4,
    )
    for date in ("2026-07-06", "2026-07-08", "2026-07-10"):
        fx.submitted_encounter(
            chw_headers, patient["id"], worker["id"], date,
            direct_minutes=15, indirect_minutes=3, travel_minutes=0,
            documentation_minutes=3,
        )

    claim = fx.create_claim(patient["id"], "2026-07", "FINAL")

    assert claim["claimed_encounter_count"] == 3
    assert claim["units"] == 4, f"floor(72 / 15) is 4, got {claim['units']}"
    assert_cents(claim["allowed_amount_cents"], 8_600, "allowed_amount_cents")
    assert claim["billing_code"] == CM_CODE_STANDARD


def test_exactly_sixty_claimed_minutes_qualifies_for_the_standard_code(api):
    """PRD §3.8: "Third, the claim's `billing_code` is chosen by threshold:
    `claimed_minutes` of at least 120 selects `CM-120`; otherwise
    `claimed_minutes` of at least 60 selects `CM-60`; and anything below 60 is
    not billable at all and is rejected at rung 17 with
    `ERR_MINUTE_THRESHOLD_NOT_MET` (HTTP 422) — exactly 60 minutes qualifies for
    `CM-60`, and 59 does not."

    Design: Difficulty/boundary_precision_check/cm_minute_threshold_exactly_sixty_qualifies
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-20T00:00:00Z", employee_code="W-014",
        mrn="MRN-130", full_name="Boundary A", household_size=1,
        monthly_income_cents=60_000,
    )
    encounter = fx.submitted_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-04",
        direct_minutes=45, indirect_minutes=10, travel_minutes=0,
        documentation_minutes=5,
    )
    assert encounter["billable_minutes"] == 60

    claim = validate_success(
        api.create_payer_claim(
            create_payer_claim_payload(patient["id"], "2026-06", "FINAL"),
            BILLING_SPECIALIST,
        ),
        201,
    )
    assert claim["claimed_minutes"] == 60
    assert claim["billing_code"] == CM_CODE_STANDARD
    assert claim["units"] == 4, f"floor(60 / 15) is 4, got {claim['units']}"
    assert_cents(claim["allowed_amount_cents"], 8_600, "allowed_amount_cents")


def test_fifty_four_claimed_minutes_is_below_the_billable_threshold(api):
    """PRD §3.8: "Third, the claim's `billing_code` is chosen by threshold:
    `claimed_minutes` of at least 120 selects `CM-120`; otherwise
    `claimed_minutes` of at least 60 selects `CM-60`; and anything below 60 is
    not billable at all and is rejected at rung 17 with
    `ERR_MINUTE_THRESHOLD_NOT_MET` (HTTP 422) — exactly 60 minutes qualifies for
    `CM-60`, and 59 does not."
    PRD §2.5: "**Fiscal caps and thresholds** — the grant budget cap and the
    care-management minute threshold (`ERR_GRANT_BUDGET_EXCEEDED`, 422;
    `ERR_MINUTE_THRESHOLD_NOT_MET`, 422)."

    Design: Difficulty/boundary_precision_check/cm_minute_threshold_exactly_sixty_qualifies
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-20T00:00:00Z", employee_code="W-014B",
        mrn="MRN-131", full_name="Boundary B", household_size=1,
        monthly_income_cents=60_000,
    )
    encounter = fx.submitted_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-04",
        direct_minutes=40, indirect_minutes=8, travel_minutes=0,
        documentation_minutes=6,
    )
    assert encounter["billable_minutes"] == 54

    response = api.create_payer_claim(
        create_payer_claim_payload(patient["id"], "2026-06", "FINAL"),
        BILLING_SPECIALIST,
    )
    validate_error(response, ApiErrorId.ERR_MINUTE_THRESHOLD_NOT_MET.value, 422)

    reread = fx.read_encounter(encounter["id"])
    assert reread["status"] == "SUBMITTED", "the rejected claim locked nothing"
    assert reread["funding_source"] == "UNFUNDED"


def test_exactly_one_hundred_and_twenty_minutes_selects_the_extended_code(api):
    """PRD §3.8: "Third, the claim's `billing_code` is chosen by threshold:
    `claimed_minutes` of at least 120 selects `CM-120`; otherwise
    `claimed_minutes` of at least 60 selects `CM-60`; and anything below 60 is
    not billable at all and is rejected at rung 17 with
    `ERR_MINUTE_THRESHOLD_NOT_MET` (HTTP 422) — exactly 60 minutes qualifies for
    `CM-60`, and 59 does not."
    PRD §3.8: "Fourth, `units` is `claimed_minutes` divided by 15 and truncated
    downward to a whole number — floor, never rounding — and
    `allowed_amount_cents` is `units` multiplied by 2150 cents."

    Design: Corner/cross_cutting_complexity_layers/cm_extended_code_at_exactly_120_minutes
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-20T00:00:00Z", employee_code="C-065",
        mrn="MRN-C65", full_name="Extended Code Case", household_size=1,
        monthly_income_cents=80_000,
    )
    first = fx.submitted_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-05",
        direct_minutes=45, indirect_minutes=10, travel_minutes=0,
        documentation_minutes=5,
    )
    second = fx.submitted_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-06",
        direct_minutes=45, indirect_minutes=10, travel_minutes=0,
        documentation_minutes=5,
    )

    claim = validate_success(
        api.create_payer_claim(
            create_payer_claim_payload(patient["id"], "2026-06", "FINAL"),
            BILLING_SPECIALIST,
        ),
        201,
    )
    assert claim["claimed_minutes"] == 120
    assert claim["billing_code"] == CM_CODE_EXTENDED, (
        f"exactly 120 minutes selects CM-120, got {claim['billing_code']}"
    )
    assert claim["units"] == 8
    assert_cents(claim["allowed_amount_cents"], 17_200, "allowed_amount_cents")
    assert claim["claimed_encounter_count"] == 2

    for encounter in (first, second):
        assert fx.read_encounter(encounter["id"])["status"] == "LOCKED"


def test_a_final_claim_on_a_grant_funded_month_is_refused(api):
    """PRD §3.8: "**Anti-double-dip.** Before a `FINAL` claim is allowed to
    carve anything, rung 15 checks two things about the patient-and-month pair.
    No encounter for that pair may already have `funding_source` of `GRANT`, and
    no earlier `FINAL` claim for that pair may exist in `SUBMITTED`, `PAID`,
    `APPEALED` or `OVERTURNED`. Either condition rejects the request with
    `ERR_MINUTES_ALREADY_FUNDED` (HTTP 409)."

    Design: Corner/validations/final_payer_claim_on_grant_funded_month_rejected
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-20T00:00:00Z", employee_code="C-043",
        mrn="MRN-C43", full_name="Grant First Case", household_size=1,
        monthly_income_cents=80_000,
    )
    award, encounter, line = fx.grant_funded_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-10",
    )

    response = api.create_payer_claim(
        create_payer_claim_payload(patient["id"], "2026-06", "FINAL"),
        BILLING_SPECIALIST,
    )
    validate_error(response, ApiErrorId.ERR_MINUTES_ALREADY_FUNDED.value, 409)

    assert fx.read_encounter(encounter["id"])["funding_source"] == "GRANT"
    assert fx.read_charge_line(line["id"])["status"] == "POSTED"

    _rows, meta = validate_paginated(
        api.list_payer_claims(BILLING_SPECIALIST, params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 0, "the refused claim was never created"

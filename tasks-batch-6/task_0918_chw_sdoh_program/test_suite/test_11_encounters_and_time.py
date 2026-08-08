"""Capturing community health worker time: derived minute fields, the marginal
mileage bands, the visit-documentation gate on submission and the void cascade."""

from test_helpers import (
    ApiErrorId,
    assert_cents,
    assert_encounter,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import SUPERVISOR


def test_travel_reimbursement_is_banded_per_encounter_at_creation(api):
    """PRD §3.7: "Under the **per-encounter** variant used at encounter
    creation, the calculation is applied to this one encounter's `travel_miles`
    and the 5000-cent cap binds on that single encounter."
    PRD §3.7: "**Mileage reimbursement.** Rates are marginal, never average, and
    there are three bands. The first 10 miles are paid at 67 cents per mile.
    Miles beyond the first 10 and up to 30 — that is, at most 20 miles' worth —
    are paid at 55 cents per mile. Every mile beyond 30 is paid at 40 cents per
    mile. The three band amounts are added together, the gross is rounded half
    up to whole cents, and the result is capped at 5000 cents."

    Design: Difficulty/dual_variant_calc/travel_reimbursement_per_encounter_vs_monthly_aggregate
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-20T00:00:00Z", employee_code="W-002",
        mrn="MRN-020", full_name="Luis Ortiz",
    )
    first = fx.submitted_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-05",
        direct_minutes=30, indirect_minutes=0, travel_minutes=25,
        documentation_minutes=0, travel_miles=10.0,
    )
    second = fx.submitted_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-11",
        direct_minutes=30, indirect_minutes=0, travel_minutes=25,
        documentation_minutes=0, travel_miles=10.0,
    )

    assert_encounter(first)
    assert_cents(
        first["travel_reimbursement_cents"], 670,
        "first encounter travel_reimbursement_cents",
    )
    assert_cents(
        second["travel_reimbursement_cents"], 670,
        "second encounter travel_reimbursement_cents",
    )


def test_the_monthly_report_walks_the_mileage_bands_once(api):
    """PRD §3.7: "Under the **monthly aggregated** variant used by the program
    report, the same band walk is applied **once** to the sum of the month's
    `travel_miles`, so later miles fall into cheaper bands and the cap binds
    once on the monthly figure rather than per row. The two variants genuinely
    diverge: two separate 10-mile encounters produce 670 plus 670, or 1340
    cents, per encounter, but the same 20 aggregate miles produce 10 miles at 67
    plus 10 miles at 55, or 1220 cents, when computed monthly."
    PRD §3.10: "`travel_reimbursement_monthly_cents` applies the monthly
    aggregated variant of the mileage rule to the sum of `travel_miles` over
    that same encounter set."

    Design: Difficulty/dual_variant_calc/travel_reimbursement_per_encounter_vs_monthly_aggregate
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-20T00:00:00Z", employee_code="W-002B",
        mrn="MRN-020B", full_name="Luis Ortiz",
    )
    fx.submitted_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-05",
        direct_minutes=30, indirect_minutes=0, travel_minutes=25,
        documentation_minutes=0, travel_miles=10.0,
    )
    fx.submitted_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-11",
        direct_minutes=30, indirect_minutes=0, travel_minutes=25,
        documentation_minutes=0, travel_miles=10.0,
    )

    report = validate_success(
        api.program_summary(
            SUPERVISOR,
            params={"service_month": "2026-06", "denominator_basis": "ENROLLED_ONLY"},
        )
    )

    assert_cents(
        report["travel_reimbursement_monthly_cents"], 1220,
        "travel_reimbursement_monthly_cents",
    )
    assert report["travel_reimbursement_monthly_cents"] != 1340, (
        "the monthly figure must not be the sum of the two per-encounter values"
    )
    assert report["unfunded_minutes"] == 60, (
        "travel minutes are never billable, so each encounter contributes 30, "
        f"got {report['unfunded_minutes']}"
    )


def test_submission_is_refused_while_the_linked_visit_is_unattested(api):
    """PRD §3.7: "When the encounter carries a non-null `home_visit_id`, that
    visit's `documentation_status` must be `ATTESTED` or `AMENDED` at rung 9, or
    the submission is rejected with `ERR_INVALID_STATE`."
    PRD §3.5: "Billing depends on the second axis only: an encounter linked to a
    visit can be submitted only once that visit's documentation is `ATTESTED` or
    `AMENDED`."

    Design: Difficulty/cross_entity_state_dependency/encounter_submit_blocked_while_home_visit_unattested
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-02T08:00:00Z", employee_code="W-020",
        mrn="MRN-190", full_name="Axis Case",
    )
    visit = fx.completed_visit(chw_headers, patient["id"], worker["id"])
    assert visit["scheduling_status"] == "COMPLETED"
    assert visit["documentation_status"] == "DRAFT"

    fx.set_clock("2026-06-02T10:30:00Z")
    encounter = fx.create_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-02",
        direct_minutes=55, indirect_minutes=5, travel_minutes=20,
        documentation_minutes=0, home_visit_id=visit["id"],
    )

    response = api.submit_encounter(encounter["id"], chw_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    assert fx.read_home_visit(visit["id"])["scheduling_status"] == "COMPLETED", (
        "the blocking axis is documentation_status, not scheduling_status"
    )
    assert fx.read_encounter(encounter["id"])["status"] == "DRAFT"


def test_attesting_the_visit_unblocks_the_linked_submission(api):
    """PRD §3.7: "When the encounter carries a non-null `home_visit_id`, that
    visit's `documentation_status` must be `ATTESTED` or `AMENDED` at rung 9, or
    the submission is rejected with `ERR_INVALID_STATE`."
    PRD §3.7: "`raw_billable_minutes` is the sum of `direct_minutes`,
    `indirect_minutes` and `documentation_minutes` — travel time is worked time
    but it is never billable time, so it is excluded here even though it counts
    toward `total_minutes`."

    Design: Difficulty/cross_entity_state_dependency/encounter_submit_blocked_while_home_visit_unattested
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-02T08:00:00Z", employee_code="W-020B",
        mrn="MRN-190B", full_name="Axis Case",
    )
    visit = fx.completed_visit(chw_headers, patient["id"], worker["id"])

    fx.set_clock("2026-06-02T10:30:00Z")
    encounter = fx.create_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-02",
        direct_minutes=55, indirect_minutes=5, travel_minutes=20,
        documentation_minutes=0, home_visit_id=visit["id"],
    )
    blocked = api.submit_encounter(encounter["id"], chw_headers)
    validate_error(blocked, ApiErrorId.ERR_INVALID_STATE.value, 409)

    attested = fx.attest_visit(
        chw_headers, visit["id"], "Home visit completed, food box delivered"
    )
    assert attested["documentation_status"] == "ATTESTED"

    submitted = validate_success(api.submit_encounter(encounter["id"], chw_headers))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["total_minutes"] == 80, (
        f"total_minutes sums all four buckets, got {submitted['total_minutes']}"
    )
    assert submitted["raw_billable_minutes"] == 60, (
        f"travel is excluded from raw_billable_minutes, got "
        f"{submitted['raw_billable_minutes']}"
    )
    assert submitted["billable_minutes"] == 60


def test_voiding_a_grant_locked_encounter_reverses_its_charge_line(api):
    """PRD §3.7: "Voiding a grant-locked encounter runs a three-link cascade:
    the encounter's `status` becomes `VOIDED` and its `funding_source` returns
    to `UNFUNDED`; the charge line whose `encounter_id` names this encounter and
    whose `status` is `POSTED` is reversed, taking a `reversed_at` of the
    current logical clock, a `reversal_reason` of `ENCOUNTER_VOIDED` and a
    `status` of `REVERSED`; and the award behind that line has its
    `committed_cents` reduced by the line's `total_amount_cents`, its
    `remaining_budget_cents` raised by the same amount, and its `version`
    incremented by 1."

    Design: Difficulty/transitive_cascade/encounter_void_cascade_reverses_grant_line_and_restores_budget
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-20T00:00:00Z", employee_code="W-008",
        mrn="MRN-080", full_name="Devon Clark", household_size=1,
        monthly_income_cents=80_000,
    )
    award, encounter, line = fx.grant_funded_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-10",
    )
    assert encounter["billable_minutes"] == 60
    assert_cents(line["total_amount_cents"], 4620, "charge line total_amount_cents")

    voided = validate_success(
        api.void_encounter(
            encounter["id"], {"reason": "Documented against the wrong patient"},
            SUPERVISOR,
        )
    )
    assert voided["status"] == "VOIDED"
    assert voided["funding_source"] == "UNFUNDED"

    reversed_line = fx.read_charge_line(line["id"])
    assert reversed_line["status"] == "REVERSED"
    assert reversed_line["reversal_reason"] == "ENCOUNTER_VOIDED", (
        "the void cascade stamps ENCOUNTER_VOIDED, got "
        f"{reversed_line['reversal_reason']}"
    )


def test_the_void_cascade_returns_every_committed_cent_to_the_award(api):
    """PRD §3.7: "Voiding a grant-locked encounter runs a three-link cascade:
    the encounter's `status` becomes `VOIDED` and its `funding_source` returns
    to `UNFUNDED`; the charge line whose `encounter_id` names this encounter and
    whose `status` is `POSTED` is reversed, taking a `reversed_at` of the
    current logical clock, a `reversal_reason` of `ENCOUNTER_VOIDED` and a
    `status` of `REVERSED`; and the award behind that line has its
    `committed_cents` reduced by the line's `total_amount_cents`, its
    `remaining_budget_cents` raised by the same amount, and its `version`
    incremented by 1."
    PRD §2.10: "**Grant budget.** An award's `budget_cap_cents` always equals
    its `committed_cents` plus its `remaining_budget_cents`, where
    `committed_cents` is the sum of `total_amount_cents` over that award's
    charge lines whose `status` is `POSTED`. Reversing a line subtracts exactly
    the amount it added."

    Design: Difficulty/transitive_cascade/encounter_void_cascade_reverses_grant_line_and_restores_budget
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-20T00:00:00Z", employee_code="W-008B",
        mrn="MRN-080B", full_name="Devon Clark", household_size=1,
    )
    award, encounter, line = fx.grant_funded_encounter(
        chw_headers, patient["id"], worker["id"], "2026-06-10",
    )
    committed = fx.read_award(award["id"])
    assert_cents(committed["committed_cents"], 4620, "committed_cents after posting")

    fx.void_encounter(encounter["id"], "Documented against the wrong patient")

    restored = fx.read_award(award["id"])
    assert_cents(restored["committed_cents"], 0, "committed_cents after the void")
    assert_cents(
        restored["remaining_budget_cents"], 200_000,
        "remaining_budget_cents after the void",
    )
    assert restored["budget_cap_cents"] == (
        restored["committed_cents"] + restored["remaining_budget_cents"]
    ), "the budget partition must balance after the compensating cascade"


def test_client_supplied_values_for_computed_encounter_fields_are_ignored(api):
    """PRD §3.7: "Creation derives five values. `service_month` is the first
    seven characters of `encounter_date`, in `YYYY-MM` form, and is the monthly
    bucket every billing rule works in. `total_minutes` is the sum of all four
    minute buckets. `raw_billable_minutes` is the sum of `direct_minutes`,
    `indirect_minutes` and `documentation_minutes` — travel time is worked time
    but it is never billable time, so it is excluded here even though it counts
    toward `total_minutes`. `billable_minutes` is `raw_billable_minutes` rounded
    to the nearest 6-minute increment, half up: the raw figure is divided by 6,
    that quotient is rounded half up to a whole number, and the result is
    multiplied back by 6."
    PRD §3.7: "An encounter is created in `status` `DRAFT` with `funding_source`
    `UNFUNDED`, `funding_claim_id` null and `submitted_at` null."

    Design: Corner/entities/encounter_computed_fields_input_ignored
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-20T00:00:00Z", employee_code="C-006",
        mrn="MRN-C06", full_name="Computed Case",
    )

    data = validate_success(
        api.create_encounter(
            {
                "patient_id": patient["id"],
                "chw_id": worker["id"],
                "encounter_date": "2026-06-05",
                "direct_minutes": 30,
                "indirect_minutes": 10,
                "travel_minutes": 0,
                "documentation_minutes": 5,
                "billable_minutes": 999,
                "service_month": "1999-01",
                "funding_source": "PAYER",
            },
            chw_headers,
        ),
        201,
    )

    assert_encounter(data)
    assert data["raw_billable_minutes"] == 45
    assert data["billable_minutes"] == 48, (
        f"a raw 45 rounds up to the nearest six-minute increment, got "
        f"{data['billable_minutes']}"
    )
    assert data["total_minutes"] == 45
    assert data["service_month"] == "2026-06", (
        "service_month is derived from encounter_date, not from the request body"
    )
    assert data["funding_source"] == "UNFUNDED"
    assert_cents(data["travel_reimbursement_cents"], 0, "travel_reimbursement_cents")
    assert data["status"] == "DRAFT"


def test_mileage_beyond_thirty_miles_uses_the_third_band_rate(api):
    """PRD §3.7: "**Mileage reimbursement.** Rates are marginal, never average,
    and there are three bands. The first 10 miles are paid at 67 cents per mile.
    Miles beyond the first 10 and up to 30 — that is, at most 20 miles' worth —
    are paid at 55 cents per mile. Every mile beyond 30 is paid at 40 cents per
    mile. The three band amounts are added together, the gross is rounded half
    up to whole cents, and the result is capped at 5000 cents."

    Design: Corner/calculations/mileage_third_band_marginal_rate_applied
    """
    worker, patient, chw_headers = fx.program_with_patient(
        clock="2026-06-20T00:00:00Z", employee_code="C-023",
        mrn="MRN-C23", full_name="Mileage Case",
    )

    data = validate_success(
        api.create_encounter(
            {
                "patient_id": patient["id"],
                "chw_id": worker["id"],
                "encounter_date": "2026-06-11",
                "direct_minutes": 30,
                "indirect_minutes": 0,
                "travel_minutes": 60,
                "documentation_minutes": 0,
                "travel_miles": 35.0,
            },
            chw_headers,
        ),
        201,
    )

    assert_cents(
        data["travel_reimbursement_cents"], 1970,
        "35 miles at 10x67 + 20x55 + 5x40 marginal band rates",
    )
    assert data["total_minutes"] == 90
    assert data["raw_billable_minutes"] == 30
    assert data["billable_minutes"] == 30

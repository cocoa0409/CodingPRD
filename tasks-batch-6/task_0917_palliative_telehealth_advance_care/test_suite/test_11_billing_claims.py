"""Advance-care-planning billing: units, rate variants, the cap and the ledgers."""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, assert_claim
from test_helpers import factories as f
from test_helpers.fixtures import (
    ADMIN,
    BILLING,
    NURSE,
    adjudicate_claim,
    attest_claim,
    attest_conference,
    book_conference,
    create_claim,
    elected_hospice_patient,
    enroll_patient,
    hold_conference,
    read_patient,
    set_clock,
    submit_claim,
)


# ---------------------------------------------------------------------------
# Modality rate variants
# ---------------------------------------------------------------------------
def test_a_telehealth_claim_is_scaled_and_carries_the_modifier_code(api):
    """PRD 3.11: "Second, `allowed_amount_cents`. The base amount is 8,600 cents
    for the first unit plus 7,500 cents for each unit beyond the first. The
    `modality` then selects a rate variant: a `TELEHEALTH` claim scales the base by
    0.85 and stamps `modifier_code` with the string `95`, while an `IN_PERSON`
    claim scales the base by 1.0 — that is, passes it through — and leaves
    `modifier_code` null. The scaled amount is rounded half up to whole cents at
    that point, once."
    PRD 3.11: "The claim is created in `status` `DRAFT` with
    `documentation_attested` false."

    Design: Difficulty/dual_variant_calc/claim_allowed_amount_diverges_by_telehealth_modality
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Bo Ferraro")

    response = api.create_claim(
        f.claim_payload(
            patient["id"],
            service_date="2026-06-01T13:00:00Z",
            documented_minutes=46,
            modality="TELEHEALTH",
        ),
        BILLING,
    )
    claim = validate_success(response, 201)
    assert_claim(claim)

    assert claim["billable_units"] == 2
    assert claim["allowed_amount_cents"] == 13685, (
        "16100 base scaled by 0.85 is 13685, "
        f"got {claim['allowed_amount_cents']}"
    )
    assert claim["modifier_code"] == "95"
    assert claim["status"] == "DRAFT"
    assert claim["documentation_attested"] is False


def test_an_in_person_claim_of_the_same_length_is_worth_strictly_more(api):
    """PRD 3.11: "Identical `documented_minutes` therefore yield a strictly larger
    `allowed_amount_cents` for an in-person claim than for a telehealth one
    whenever the annual cap is not binding."
    PRD 3.11: "The `modality` then selects a rate variant: a `TELEHEALTH` claim
    scales the base by 0.85 and stamps `modifier_code` with the string `95`, while
    an `IN_PERSON` claim scales the base by 1.0 — that is, passes it through — and
    leaves `modifier_code` null."

    Design: Difficulty/dual_variant_calc/claim_allowed_amount_diverges_by_telehealth_modality
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Bo Ferraro")

    telehealth = create_claim(
        patient["id"],
        service_date="2026-06-01T13:00:00Z",
        documented_minutes=46,
        modality="TELEHEALTH",
    )
    in_person = create_claim(
        patient["id"],
        service_date="2026-06-01T15:00:00Z",
        documented_minutes=46,
        modality="IN_PERSON",
    )

    assert in_person["billable_units"] == 2
    assert in_person["allowed_amount_cents"] == 16100
    assert in_person["modifier_code"] is None
    assert in_person["allowed_amount_cents"] > telehealth["allowed_amount_cents"]


# ---------------------------------------------------------------------------
# Billable units
# ---------------------------------------------------------------------------
def test_sixteen_minutes_is_billable_and_fifteen_is_not(api):
    """PRD 3.11: "A claim whose `documented_minutes` is below 16 is not billable
    at all and is refused with `ERR_INSUFFICIENT_DOCUMENTED_TIME`; exactly 16
    minutes is billable."
    PRD 3.11: "First, `billable_units`. The first unit is earned at 16 minutes,
    and each further unit takes another full 30 minutes: take the documented
    minutes, subtract 16, divide by 30 discarding any remainder, add 1, and cap
    the result at 4 units."

    Design: Difficulty/boundary_precision_check/acp_first_unit_minimum_minutes_is_inclusive_at_sixteen
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Kira Osei")

    at_the_floor = create_claim(
        patient["id"],
        service_date="2026-06-01T09:00:00Z",
        documented_minutes=16,
        modality="IN_PERSON",
    )
    assert at_the_floor["billable_units"] == 1
    assert at_the_floor["allowed_amount_cents"] == 8600

    rejected = api.create_claim(
        f.claim_payload(
            patient["id"],
            service_date="2026-06-01T12:00:00Z",
            documented_minutes=15,
            modality="IN_PERSON",
        ),
        BILLING,
    )
    validate_error(rejected, ApiErrorId.ERR_INSUFFICIENT_DOCUMENTED_TIME.value, 422)


def test_the_additional_unit_midpoint_is_inclusive_at_forty_six_minutes(api):
    """PRD 3.11: "Sixteen minutes gives exactly 1 unit, 45 minutes still gives 1,
    46 gives 2, 75 gives 2, 76 gives 3, 106 gives 4, and 240 is capped at 4. This
    is floor division throughout; nothing is ever rounded up."
    PRD 3.11: "The base amount is 8,600 cents for the first unit plus 7,500 cents
    for each unit beyond the first."

    Design: Difficulty/boundary_precision_check/acp_first_unit_minimum_minutes_is_inclusive_at_sixteen
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Kira Osei")

    forty_five = create_claim(
        patient["id"],
        service_date="2026-06-01T10:00:00Z",
        documented_minutes=45,
        modality="IN_PERSON",
    )
    forty_six = create_claim(
        patient["id"],
        service_date="2026-06-01T11:00:00Z",
        documented_minutes=46,
        modality="IN_PERSON",
    )

    assert forty_five["billable_units"] == 1, (
        f"45 minutes still buys one unit, got {forty_five['billable_units']}"
    )
    assert forty_six["billable_units"] == 2
    assert forty_six["allowed_amount_cents"] == 16100


def test_billable_units_are_capped_at_four(api):
    """PRD 3.11: "Sixteen minutes gives exactly 1 unit, 45 minutes still gives 1,
    46 gives 2, 75 gives 2, 76 gives 3, 106 gives 4, and 240 is capped at 4. This
    is floor division throughout; nothing is ever rounded up."
    PRD 3.11: "Third, and this is the step whose ordering is most easily got
    wrong, `coinsurance_pct` is read off the **capped** `allowed_amount_cents`, not
    off the rated amount before the cap: it is 0.1 when `allowed_amount_cents` is
    10,000 cents or less — the boundary is inclusive, so exactly 10,000 uses the
    low rate — and 0.2 when `allowed_amount_cents` is 10,001 cents or more."

    Design: Corner/calculations/acp_billable_units_are_capped_at_four
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Wren Achebe")

    at_the_cap = create_claim(
        patient["id"],
        service_date="2026-06-01T09:00:00Z",
        documented_minutes=106,
        modality="IN_PERSON",
    )
    beyond_the_cap = create_claim(
        patient["id"],
        service_date="2026-06-01T13:00:00Z",
        documented_minutes=240,
        modality="IN_PERSON",
    )

    assert at_the_cap["billable_units"] == 4
    assert at_the_cap["allowed_amount_cents"] == 31100
    assert at_the_cap["coinsurance_pct"] == pytest.approx(0.2, abs=1e-9)
    assert at_the_cap["patient_responsibility_cents"] == 6220
    assert at_the_cap["net_payable_cents"] == 24880
    assert beyond_the_cap["billable_units"] == 4
    assert beyond_the_cap["allowed_amount_cents"] == 31100


# ---------------------------------------------------------------------------
# The annual cap drives the coinsurance tier
# ---------------------------------------------------------------------------
def _patient_with_paid_history():
    """Two paid claims driving acp_paid_cents_ytd to 32620."""
    patient, _ = enroll_patient(
        clock="2026-06-01T00:00:00Z",
        full_name="Dov Ramirez",
        jurisdiction_code="JUR_NOTARY",
    )
    for service_date, minutes in (("2026-06-01T09:00:00Z", 106), ("2026-06-01T11:00:00Z", 16)):
        claim = create_claim(
            patient["id"],
            service_date=service_date,
            documented_minutes=minutes,
            modality="IN_PERSON",
        )
        attest_claim(claim["id"])
        submit_claim(claim["id"])
        adjudicate_claim(claim["id"], "PAID")
    return patient


def test_paid_claims_accumulate_into_the_patient_annual_total(api):
    """PRD 3.11: "A `PAID` outcome moves the claim `SUBMITTED → PAID`, the
    terminal state, and increases the patient's `acp_paid_cents_ytd` by this
    claim's `net_payable_cents` — which is exactly how the annual cap tightens for
    the next claim."
    PRD 3.11: "Fourth, `patient_responsibility_cents` is `allowed_amount_cents`
    multiplied by `coinsurance_pct`, rounded half up to whole cents. Fifth,
    `net_payable_cents` is `allowed_amount_cents` minus
    `patient_responsibility_cents`, an exact subtraction with no rounding of its
    own."

    Design: Difficulty/combinatorial_formula/claim_net_payable_pins_coinsurance_tier_after_annual_cap
    """
    patient = _patient_with_paid_history()

    claims, meta = validate_paginated(
        api.list_claims(BILLING, params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 2
    nets = sorted(row["net_payable_cents"] for row in claims)
    assert nets == [7740, 24880], (
        "the 16-minute claim nets 7740 under the low coinsurance rate and the "
        f"106-minute claim nets 24880 under the high rate, got {nets}"
    )

    final = validate_success(api.get_patient(patient["id"], ADMIN))
    assert final["acp_paid_cents_ytd"] == 32620, (
        "24880 from the 106-minute claim plus 7740 from the 16-minute claim, "
        f"got {final['acp_paid_cents_ytd']}"
    )
    assert final["acp_minutes_claimed"] == 122


def test_the_coinsurance_tier_is_read_off_the_capped_amount(api):
    """PRD 3.11: "Then the patient's annual cap applies: the remaining capacity is
    40,000 cents minus the patient's `acp_paid_cents_ytd`, floored at zero so it
    never goes negative, and `allowed_amount_cents` is the smaller of the rated
    amount and that remaining capacity."
    PRD 3.11: "Third, and this is the step whose ordering is most easily got
    wrong, `coinsurance_pct` is read off the **capped** `allowed_amount_cents`, not
    off the rated amount before the cap: it is 0.1 when `allowed_amount_cents` is
    10,000 cents or less — the boundary is inclusive, so exactly 10,000 uses the
    low rate — and 0.2 when `allowed_amount_cents` is 10,001 cents or more."

    Design: Difficulty/combinatorial_formula/claim_net_payable_pins_coinsurance_tier_after_annual_cap
    """
    patient = _patient_with_paid_history()

    capped = create_claim(
        patient["id"],
        service_date="2026-06-01T14:00:00Z",
        documented_minutes=46,
        modality="TELEHEALTH",
    )

    assert capped["billable_units"] == 2
    assert capped["allowed_amount_cents"] == 7380, (
        "the rated 13685 is capped to the remaining 40000 - 32620 = 7380, "
        f"got {capped['allowed_amount_cents']}"
    )
    assert capped["coinsurance_pct"] == pytest.approx(0.1, abs=1e-9), (
        "reading the tier off the uncapped 13685 would wrongly give the high rate"
    )
    assert capped["patient_responsibility_cents"] == 738
    assert capped["net_payable_cents"] == 6642


# ---------------------------------------------------------------------------
# The conserved minutes ledger
# ---------------------------------------------------------------------------
def test_submitting_a_claim_adds_its_minutes_to_the_patient_ledger(api):
    """PRD 3.11: "Submission, which may carry an optional `submission_note`, moves
    an `ATTESTED` claim whose `documentation_attested` is true to `SUBMITTED` and
    increases the patient's `acp_minutes_claimed` by this claim's
    `documented_minutes`."
    PRD 2.9: "`acp_minutes_claimed` on the patient equals the sum of
    `documented_minutes` over that patient's claims whose `status` is `SUBMITTED`
    or `PAID`; claims in `DRAFT`, `ATTESTED` and `DENIED` contribute zero."

    Design: Difficulty/compensating_invariant/claim_submit_then_denial_conserves_patient_acp_minutes
    """
    patient, _ = enroll_patient(
        clock="2026-06-01T00:00:00Z",
        full_name="Sami Haddad",
        jurisdiction_code="JUR_NOTARY",
    )
    claim = create_claim(
        patient["id"],
        service_date="2026-06-01T09:00:00Z",
        documented_minutes=46,
        modality="IN_PERSON",
    )
    assert claim["billable_units"] == 2
    assert claim["net_payable_cents"] == 12880

    attested = attest_claim(
        claim["id"], "46 minutes of goals-of-care discussion documented"
    )
    assert attested["status"] == "ATTESTED"
    assert read_patient(patient["id"])["acp_minutes_claimed"] == 0, (
        "an ATTESTED claim contributes zero to the minutes ledger"
    )

    submitted = validate_success(api.submit_claim(claim["id"], {}, BILLING))
    assert submitted["status"] == "SUBMITTED"
    assert read_patient(patient["id"])["acp_minutes_claimed"] == 46


def test_a_denial_returns_the_minutes_ledger_to_its_prior_value(api):
    """PRD 3.11: "A `DENIED` outcome moves the claim `SUBMITTED → DENIED`, stores
    the `denial_reason`, returns `documentation_attested` to false, clears
    `attested_by_user_id` to null, and decreases the patient's
    `acp_minutes_claimed` by exactly the `documented_minutes` that submission
    added, restoring that ledger to its prior value."
    PRD 2.9: "`acp_paid_cents_ytd` equals the sum of `net_payable_cents` over that
    patient's claims whose `status` is exactly `PAID`. Submitting a claim and then
    having the payer deny it must return `acp_minutes_claimed` to exactly its
    prior value."

    Design: Difficulty/compensating_invariant/claim_submit_then_denial_conserves_patient_acp_minutes
    """
    patient, _ = enroll_patient(
        clock="2026-06-01T00:00:00Z",
        full_name="Sami Haddad",
        jurisdiction_code="JUR_NOTARY",
    )
    claim = create_claim(
        patient["id"],
        service_date="2026-06-01T09:00:00Z",
        documented_minutes=46,
        modality="IN_PERSON",
    )
    attest_claim(claim["id"], "46 minutes of goals-of-care discussion documented")
    submit_claim(claim["id"])
    assert read_patient(patient["id"])["acp_minutes_claimed"] == 46

    denied = validate_success(
        api.adjudicate_claim(
            claim["id"],
            {"outcome": "DENIED", "denial_reason": "DOCUMENTATION_INSUFFICIENT"},
            ADMIN,
        )
    )

    assert denied["status"] == "DENIED"
    assert denied["denial_reason"] == "DOCUMENTATION_INSUFFICIENT"
    assert denied["documentation_attested"] is False
    assert denied["net_payable_cents"] == 12880

    final = read_patient(patient["id"])
    assert final["acp_minutes_claimed"] == 0, "the denial must undo exactly what submission added"
    assert final["acp_paid_cents_ytd"] == 0, "no claim reached PAID, so the paid ledger never moved"


# ---------------------------------------------------------------------------
# The denial and resubmission loop
# ---------------------------------------------------------------------------
def test_a_denied_claim_can_be_reattested_resubmitted_and_paid(api):
    """PRD 3.11: "A denied claim can be re-attested — `DENIED → ATTESTED` sets
    `documentation_attested` true again while retaining `denial_reason` for the
    audit trail — and resubmitted, and the `DENIED → ATTESTED → SUBMITTED` loop
    may repeat."
    PRD 3.11: "A `PAID` outcome moves the claim `SUBMITTED → PAID`, the terminal
    state, and increases the patient's `acp_paid_cents_ytd` by this claim's
    `net_payable_cents` — which is exactly how the annual cap tightens for the
    next claim."

    Design: Corner/state_machines/claim_denied_then_reattested_resubmitted_and_paid
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Lena Brandt")
    claim = create_claim(
        patient["id"],
        service_date="2026-06-01T09:00:00Z",
        documented_minutes=46,
        modality="IN_PERSON",
    )
    attest_claim(claim["id"], "first attestation")
    submit_claim(claim["id"])
    adjudicate_claim(claim["id"], "DENIED", denial_reason="DOCUMENTATION_INSUFFICIENT")

    reattested = attest_claim(claim["id"], "corrected documentation attached")
    assert reattested["status"] == "ATTESTED"
    assert reattested["documentation_attested"] is True
    assert reattested["denial_reason"] == "DOCUMENTATION_INSUFFICIENT"

    submit_claim(claim["id"], note="resubmission")
    paid = adjudicate_claim(claim["id"], "PAID")

    assert paid["status"] == "PAID"
    assert paid["net_payable_cents"] == 12880
    final = read_patient(patient["id"])
    assert final["acp_minutes_claimed"] == 46
    assert final["acp_paid_cents_ytd"] == 12880


# ---------------------------------------------------------------------------
# Concurrent care
# ---------------------------------------------------------------------------
def test_a_claim_inside_an_elected_period_needs_the_carve_out_on_both_sides(api):
    """PRD 3.11: "And a claim whose `service_date` falls inside a currently elected
    hospice benefit period for the same patient — at or after that election's
    `current_period_start` and strictly before its `current_period_end`, for an
    election whose `status` is `ELECTED` — is refused with
    `ERR_CONCURRENT_CARE_OVERLAP` unless the claim's `concurrent_care_carve_out`
    **and** that election's `concurrent_care_carve_out` are both true. One flag
    alone is not enough; the carve-out must be agreed on both sides so that the
    same service is never counted twice."

    Design: Corner/validations/claim_inside_an_elected_benefit_period_returns_concurrent_care_overlap
    """
    patient, election = elected_hospice_patient(
        clock="2026-06-01T00:00:00Z",
        conference_held_at="2026-06-02T09:00:00Z",
        period_start="2026-06-02T00:00:00Z",
        election_overrides={"concurrent_care_carve_out": False},
        full_name="Nia Osei",
    )
    assert election["status"] == "ELECTED"

    inside = api.create_claim(
        f.claim_payload(
            patient["id"],
            service_date="2026-07-01T10:00:00Z",
            documented_minutes=46,
            modality="TELEHEALTH",
            concurrent_care_carve_out=True,
        ),
        BILLING,
    )
    validate_error(inside, ApiErrorId.ERR_CONCURRENT_CARE_OVERLAP.value, 409)

    outside = validate_success(
        api.create_claim(
            f.claim_payload(
                patient["id"],
                service_date="2026-09-01T10:00:00Z",
                documented_minutes=46,
                modality="TELEHEALTH",
            ),
            BILLING,
        ),
        201,
    )
    assert outside["status"] == "DRAFT"
    assert outside["allowed_amount_cents"] == 13685


# ---------------------------------------------------------------------------
# The documentation gate
# ---------------------------------------------------------------------------
def test_a_claim_cannot_be_attested_before_its_conference_documentation_is_complete(api):
    """PRD 3.11: "When the claim's `conference_id` is non-null, the named
    conference must have `attestation_complete` true first, or the attestation is
    refused with `ERR_ATTESTATION_REQUIRED` — a claim cannot lean on documentation
    that does not yet exist."
    PRD 3.11: "Attesting a claim carries an `attestation_statement`, sets
    `documentation_attested` true, stamps `attested_by_user_id` from `X-User-ID`,
    and moves the claim to `ATTESTED` from either `DRAFT` or `DENIED`."

    Design: Corner/validations/claim_attest_before_conference_attestation_returns_attestation_required
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Oren Blaise")
    conference = book_conference(
        patient["id"],
        conference_type="FAMILY",
        modality="TELEHEALTH",
        scheduled_start="2026-06-02T09:00:00Z",
        scheduled_end="2026-06-02T10:00:00Z",
    )
    set_clock("2026-06-02T09:00:00Z")
    hold_conference(
        conference["id"], documented_minutes=46, disciplines_present=["PHYSICIAN", "NURSE"]
    )
    attest_conference(conference["id"], "PHYSICIAN", "goals of care documented")

    claim = create_claim(
        patient["id"],
        service_date="2026-06-02T09:30:00Z",
        documented_minutes=46,
        modality="TELEHEALTH",
        conference_id=conference["id"],
    )

    premature = api.attest_claim(
        claim["id"], {"attestation_statement": "premature attestation"}, BILLING
    )
    validate_error(premature, ApiErrorId.ERR_ATTESTATION_REQUIRED.value, 422)

    completed = validate_success(
        api.attest_conference(
            conference["id"],
            {"discipline": "NURSE", "note_text": "symptom documentation complete"},
            NURSE,
        )
    )
    assert completed["attestation_complete"] is True
    assert completed["status"] == "ATTESTED"

    attested = validate_success(
        api.attest_claim(
            claim["id"], {"attestation_statement": "documentation complete"}, BILLING
        )
    )
    assert attested["status"] == "ATTESTED"
    assert attested["documentation_attested"] is True
    assert attested["attested_by_user_id"] == "u_billing_1"

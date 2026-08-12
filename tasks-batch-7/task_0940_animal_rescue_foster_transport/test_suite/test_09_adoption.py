"""Adoption: household matching, the fee waterfall, deposits and finalization."""
from test_helpers import (
    COUNSELOR_ONE,
    COUNSELOR_TWO,
    TEST_USERS,
    ApiErrorId,
    adoption_application_payload,
    adoption_payload,
    animal_version,
    assert_adoption,
    assert_adoption_application,
    assert_adoption_fee_components_conserved,
    assert_same_instant,
    finalize_adoption,
    make_adopter_headers,
    make_altered,
    make_counselor_headers,
    new_adopter,
    new_animal,
    new_organization,
    new_person,
    screen_application,
    set_clock,
    setup_adoptable_animal,
    setup_finalized_adoption,
    submit_application,
    take_into_custody,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_officer_headers"]
VET = TEST_USERS["veterinarian_headers"]
COUNSELOR = TEST_USERS["adoption_counselor_headers"]


# --------------------------------------------------------------------------
# The fee waterfall under its two credit-application orders
# --------------------------------------------------------------------------
def test_credit_first_spends_the_sponsorship_before_the_waiver_shrinks_the_fee(api):
    """PRD 3.8: "**The base fee** is selected by species alone: 25000 cents for a `DOG`,
    12500 for a `CAT`, 6000 for an `OTHER`, stored as `base_fee_cents`."
    PRD 3.8: "An animal qualifies for the senior waiver when its `age_months` is at
    least 84 — that is, seven years — which discounts 60 percent."
    PRD 3.8: "Under `CREDIT_FIRST`, sponsorship goes first: `sponsorship_applied_cents`
    is the smaller of `base_fee_cents` and the pool total; what remains of the base fee
    after that is then reduced by the waiver, with `waiver_applied_cents` being the
    waiver percentage applied to that remainder and rounded half up; and
    `adopter_charged_cents` is the remainder less the waiver."
    PRD 3.8: "`residual_credit_cents` is always the pool total less
    `sponsorship_applied_cents`, and there is a non-monotone consequence worth stating
    plainly: a **larger** waiver under `WAIVER_FIRST` consumes **less** sponsorship and
    therefore leaves **more** residual credit."

    A dog born 2018-01-01 is 3073 days old on 2026-06-01, so age_months is 102 and the
    SENIOR waiver applies. Sponsorship takes min(25000, 20000) = 20000, leaving 5000;
    60 percent of 5000 is 3000, so the adopter is charged 2000 and no credit remains.

    Design: Difficulty/dual_variant_calc/adoption_fee_waterfall_credit_first_vs_waiver_first
    """
    scenario = setup_finalized_adoption(
        api, sponsorship_cents=20000, sponsorship_reference="SPON-A",
        date_of_birth="2018-01-01T00:00:00Z", size_class="LARGE", weight_lb=65.0,
        finalize_options={"credit_application_order": "CREDIT_FIRST"},
    )
    adoption = scenario["adoption"]
    assert_adoption(adoption)

    assert adoption["base_fee_cents"] == 25000
    assert adoption["waiver_kind"] == "SENIOR"
    assert adoption["sponsorship_applied_cents"] == 20000
    assert adoption["waiver_applied_cents"] == 3000
    assert adoption["adopter_charged_cents"] == 2000
    assert adoption["residual_credit_cents"] == 0
    assert adoption["alteration_deposit_cents"] == 0
    assert_adoption_fee_components_conserved(adoption)


def test_waiver_first_shrinks_the_fee_first_and_leaves_residual_credit(api):
    """PRD 3.8: "Under `WAIVER_FIRST`, the waiver goes first: `waiver_applied_cents` is
    the waiver percentage applied to the full `base_fee_cents` and rounded half up;
    `sponsorship_applied_cents` is then the smaller of the post-waiver amount and the
    pool total; and `adopter_charged_cents` is the post-waiver amount less the
    sponsorship. Either way exactly one rounding occurs, and the three components
    always sum back to `base_fee_cents`."
    PRD 3.8: "Under `WAIVER_FIRST` a large waiver can drop the fee below the available
    credit, so the adopter owes nothing and a strictly positive
    `residual_credit_cents` appears."

    Sixty percent of 25000 is 15000, leaving 10000 for the 20000-cent pool to absorb,
    so the adopter is charged nothing and 10000 cents of credit is left over.

    Design: Difficulty/dual_variant_calc/adoption_fee_waterfall_credit_first_vs_waiver_first
    """
    scenario = setup_finalized_adoption(
        api, sponsorship_cents=20000, sponsorship_reference="SPON-B",
        date_of_birth="2018-01-01T00:00:00Z", size_class="LARGE", weight_lb=66.0,
        finalize_options={"credit_application_order": "WAIVER_FIRST"},
    )
    adoption = scenario["adoption"]

    assert adoption["base_fee_cents"] == 25000
    assert adoption["waiver_kind"] == "SENIOR"
    assert adoption["waiver_applied_cents"] == 15000
    assert adoption["sponsorship_applied_cents"] == 10000
    assert adoption["adopter_charged_cents"] == 0
    assert adoption["residual_credit_cents"] == 10000
    assert_adoption_fee_components_conserved(adoption)


def test_the_finalize_response_already_carries_the_whole_fee_breakdown(api):
    """PRD 2.2: "The `data` field contains the resource object or an array of resource
    objects. For 2xx responses with no data, it contains an empty object. Unless
    otherwise noted, operations that create or modify a resource will return the
    created or updated resource object in the data field."
    PRD 3.8: "The adoption row is written in `status` `FINALIZED` and `fee_status`
    `UNPAID`, with `finalized_at` stamped at the current clock instant,
    `finalized_by_user_id` recording the acting `X-User-ID`, `adopter_paid_cents`,
    `refund_issued_cents`, `credit_restored_cents` and
    `alteration_deposit_refunded_cents` all at zero, and `returned_at` null."

    Design: Corner/consistency_model/adoption_response_carries_every_derived_fee_field_immediately
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    adopter = new_adopter(api)
    donor = new_person(api, "Gil Marsh", "gil@example.test")
    animal = new_animal(api, org["id"], name="Rex", size_class="LARGE", weight_lb=65.0,
                        date_of_birth="2018-01-01T00:00:00Z")
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    make_altered(api, animal["id"], "2026-05-01T00:00:00Z")
    validate_success(
        api.create_contribution(
            {"donor_person_id": donor["id"], "amount_cents": 20000,
             "donor_reference": "SPON-IM", "designated_animal_id": animal["id"],
             "designated_program": "NONE", "restriction_category": "UNRESTRICTED"},
            TEST_USERS["finance_officer_headers"],
        ),
        201,
    )
    set_clock(api, "2026-06-01T00:00:00Z")
    application = submit_application(api, animal["id"], adopter["id"])
    screen_application(api, application["id"], "APPROVE", COUNSELOR_ONE)

    response = api.create_adoption(
        adoption_payload(application["id"], animal_version(api, animal["id"])),
        make_counselor_headers(COUNSELOR_TWO),
    )
    adoption = validate_success(response, 201)

    assert adoption["base_fee_cents"] == 25000
    assert adoption["waiver_kind"] == "SENIOR"
    assert adoption["sponsorship_applied_cents"] == 20000
    assert adoption["waiver_applied_cents"] == 3000
    assert adoption["adopter_charged_cents"] == 2000
    assert adoption["residual_credit_cents"] == 0
    assert adoption["fee_status"] == "UNPAID"
    assert adoption["status"] == "FINALIZED"
    assert adoption["adopter_paid_cents"] == 0
    assert adoption["refund_issued_cents"] == 0
    assert adoption["credit_restored_cents"] == 0
    assert adoption["alteration_deposit_refunded_cents"] == 0
    assert adoption["returned_at"] is None
    assert adoption["finalized_by_user_id"] == COUNSELOR_TWO
    assert_same_instant(adoption["finalized_at"], "2026-06-01T00:00:00Z", "finalized_at")



# --------------------------------------------------------------------------
# The household match at submission time
# --------------------------------------------------------------------------
def _animal_restricted_to_six_year_olds(api):
    set_clock(api, "2026-05-05T00:00:00Z")
    org = new_organization(api)
    animal = new_animal(
        api, org["id"], name="Rex", size_class="LARGE", weight_lb=65.0,
        date_of_birth="2020-01-01T00:00:00Z", restriction_no_children_under_years=6,
        restriction_no_cats=False, restriction_no_dogs=False,
        restriction_requires_fenced_yard=False, restriction_housing_types_excluded=[],
    )
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-05T00:00:00Z")
    return {"org": org, "animal": animal}


def test_a_household_exactly_at_the_child_age_restriction_is_admitted(api):
    """PRD 3.8: "The five criteria are evaluated in a pinned order and the first failure
    ends the evaluation: first, the applicant's `youngest_child_age_years` must be at
    least the animal's `restriction_no_children_under_years`, an inclusive comparison
    so a household whose youngest child is exactly the restriction age qualifies;
    second, either the animal's `restriction_no_cats` is false or the applicant's
    `resident_cat_count` is zero; third, either `restriction_no_dogs` is false or
    `resident_dog_count` is zero; fourth, either `restriction_requires_fenced_yard` is
    false or the applicant's `has_fenced_yard` is true; fifth, the applicant's
    `housing_type` must not appear in the animal's `restriction_housing_types_excluded`
    array."
    PRD 3.8: "A surviving application is created in `status` `SUBMITTED` with
    `attempt_count` 1, and with `screened_by_user_id`, `screened_at` and
    `decline_reason` all null."

    Design: Difficulty/boundary_precision_check/household_child_age_inclusive_boundary_on_application
    """
    scenario = _animal_restricted_to_six_year_olds(api)
    applicant = new_adopter(api, "Ada Six", "ada@example.test", youngest_child_age_years=6)

    response = api.create_adoption_application(
        adoption_application_payload(scenario["animal"]["id"], applicant["id"]), COUNSELOR
    )
    application = validate_success(response, 201)
    assert_adoption_application(application)
    assert application["status"] == "SUBMITTED"
    assert application["attempt_count"] == 1
    assert application["screened_by_user_id"] is None
    assert application["screened_at"] is None
    assert application["decline_reason"] is None


def test_a_household_one_year_below_the_restriction_is_refused(api):
    """PRD 3.8: "Any failure rejects the submission with `ERR_HOUSEHOLD_MISMATCH` (HTTP
    422)."
    PRD 3.8: "Because the match happens at create time, **no application row ever
    exists carrying a household-mismatch decline** — the only two members of
    `decline_reason` are `COUNSELOR_DECISION` and `SUPERSEDED_BY_FINALIZED_SIBLING`."

    Design: Difficulty/boundary_precision_check/household_child_age_inclusive_boundary_on_application
    """
    scenario = _animal_restricted_to_six_year_olds(api)
    applicant = new_adopter(api, "Ben Five", "ben@example.test", youngest_child_age_years=5)

    validate_error(
        api.create_adoption_application(
            adoption_application_payload(scenario["animal"]["id"], applicant["id"]), COUNSELOR
        ),
        ApiErrorId.ERR_HOUSEHOLD_MISMATCH.value,
        422,
    )


# --------------------------------------------------------------------------
# The capped resubmission cycle
# --------------------------------------------------------------------------
def _declined_application(api):
    set_clock(api, "2026-05-05T00:00:00Z")
    org = new_organization(api)
    adopter = new_adopter(api)
    animal = new_animal(api, org["id"], name="Rex", size_class="LARGE", weight_lb=65.0,
                        date_of_birth="2020-01-01T00:00:00Z")
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-05T00:00:00Z")
    application = validate_success(
        api.create_adoption_application(
            adoption_application_payload(animal["id"], adopter["id"]),
            make_adopter_headers(adopter["id"]),
        ),
        201,
    )
    screen_application(api, application["id"], "DECLINE", COUNSELOR_ONE)
    return {"adopter": adopter, "animal": animal, "application": application}


def test_a_declined_application_may_be_resubmitted_up_to_three_times(api):
    """PRD 3.8: "Resubmission is reserved to the applicant themself — an `Adopter` whose
    `X-User-ID` equals the application's `applicant_person_id` — moves it `DECLINED →
    SUBMITTED`, raises `attempt_count` by one, clears `decline_reason`,
    `screened_by_user_id` and `screened_at` back to null, and increments `version`."
    PRD 3.8: "`APPROVE` moves it `SUBMITTED → APPROVED`; `DECLINE` moves it `SUBMITTED
    → DECLINED` and sets `decline_reason` to `COUNSELOR_DECISION`."

    Design: Difficulty/non_linear_state_machine/adoption_application_capped_resubmission_cycle
    """
    scenario = _declined_application(api)
    adopter_headers = make_adopter_headers(scenario["adopter"]["id"])

    declined = validate_success(
        api.get_adoption_application(scenario["application"]["id"], COUNSELOR)
    )
    assert declined["status"] == "DECLINED"
    assert declined["decline_reason"] == "COUNSELOR_DECISION"

    second = validate_success(
        api.resubmit_adoption_application(scenario["application"]["id"], adopter_headers)
    )
    assert second["attempt_count"] == 2
    assert second["status"] == "SUBMITTED"
    assert second["decline_reason"] is None
    assert second["screened_by_user_id"] is None
    assert second["screened_at"] is None

    screen_application(api, scenario["application"]["id"], "DECLINE", COUNSELOR_ONE)
    third = validate_success(
        api.resubmit_adoption_application(scenario["application"]["id"], adopter_headers)
    )
    assert third["attempt_count"] == 3
    assert third["status"] == "SUBMITTED"


def test_the_fourth_submission_is_refused_by_the_attempt_limit(api):
    """PRD 3.8: "The loop is capped at three submissions counting the original, so the
    third submission is permitted and the fourth is refused with
    `ERR_APPLICATION_ATTEMPT_LIMIT`."

    Design: Difficulty/non_linear_state_machine/adoption_application_capped_resubmission_cycle
    """
    scenario = _declined_application(api)
    adopter_headers = make_adopter_headers(scenario["adopter"]["id"])

    validate_success(
        api.resubmit_adoption_application(scenario["application"]["id"], adopter_headers)
    )
    screen_application(api, scenario["application"]["id"], "DECLINE", COUNSELOR_ONE)
    validate_success(
        api.resubmit_adoption_application(scenario["application"]["id"], adopter_headers)
    )
    screen_application(api, scenario["application"]["id"], "DECLINE", COUNSELOR_ONE)

    validate_error(
        api.resubmit_adoption_application(scenario["application"]["id"], adopter_headers),
        ApiErrorId.ERR_APPLICATION_ATTEMPT_LIMIT.value,
        409,
    )

    final = validate_success(
        api.get_adoption_application(scenario["application"]["id"], COUNSELOR)
    )
    assert final["status"] == "DECLINED"
    assert final["attempt_count"] == 3


# --------------------------------------------------------------------------
# Waivers, base fees and the deferred-alteration deposit
# --------------------------------------------------------------------------
def test_long_stay_waiver_is_selected_when_the_animal_is_not_senior(api):
    """PRD 3.8: "It qualifies for the long-stay waiver when its `length_of_stay_days` is
    at least 120 — four 30-day months in this system's arithmetic — which discounts 50
    percent. Both boundaries are inclusive."
    PRD 3.8: "When neither qualifies, `waiver_kind` is `NONE` and the waiver percentage
    is zero. The chosen member is recorded as `waiver_kind`."

    A dog born 2022-01-01 is 1704 days old on 2026-09-01, so age_months is 56 and the
    SENIOR test fails; intaken 2026-05-01 it has 123 days in care, which clears the
    inclusive 120-day boundary, so 50 percent of 25000 is waived.

    Design: Corner/calculations/long_stay_waiver_selected_when_animal_is_not_senior
    """
    scenario = setup_adoptable_animal(
        api, clock_at_intake="2026-05-01T00:00:00Z", clock_at_adoption="2026-09-01T00:00:00Z",
        date_of_birth="2022-01-01T00:00:00Z",
    )
    animal = validate_success(api.get_animal(scenario["animal"]["id"], ADMIN))
    assert animal["length_of_stay_days"] == 123
    assert animal["age_months"] == 56

    adoption = finalize_adoption(
        api, scenario["application"]["id"], animal["version"], COUNSELOR_TWO
    )
    assert adoption["waiver_kind"] == "LONG_STAY"
    assert adoption["waiver_applied_cents"] == 12500
    assert adoption["adopter_charged_cents"] == 12500
    assert adoption["sponsorship_applied_cents"] == 0
    assert adoption["base_fee_cents"] == 25000
    assert_adoption_fee_components_conserved(adoption)


def test_base_fee_follows_the_species_for_cats_and_other_animals(api):
    """PRD 3.8: "**The base fee** is selected by species alone: 25000 cents for a `DOG`,
    12500 for a `CAT`, 6000 for an `OTHER`, stored as `base_fee_cents`."
    PRD 3.8: "The pool's total is the sum of `available_cents` across the eligible
    rows; when nothing is eligible the total is zero and the waterfall simply proceeds
    with no sponsorship applied."

    Design: Corner/calculations/adoption_base_fee_cat_and_other_species_variants
    """
    cat_scenario = setup_adoptable_animal(
        api, species="CAT", size_class="SMALL", weight_lb=9.0,
        date_of_birth="2023-01-01T00:00:00Z",
        adopter_overrides={"email": "cat-adopter@example.test"},
    )
    cat_adoption = finalize_adoption(
        api, cat_scenario["application"]["id"],
        animal_version(api, cat_scenario["animal"]["id"]), COUNSELOR_TWO,
    )
    assert cat_adoption["base_fee_cents"] == 12500
    assert cat_adoption["adopter_charged_cents"] == 12500
    assert cat_adoption["waiver_kind"] == "NONE"

    other_scenario = setup_adoptable_animal(
        api, species="OTHER", size_class="SMALL", weight_lb=4.0,
        date_of_birth="2023-01-01T00:00:00Z",
        adopter_overrides={"email": "other-adopter@example.test"},
    )
    other_adoption = finalize_adoption(
        api, other_scenario["application"]["id"],
        animal_version(api, other_scenario["animal"]["id"]), COUNSELOR_TWO,
    )
    assert other_adoption["base_fee_cents"] == 6000
    assert other_adoption["adopter_charged_cents"] == 6000
    assert other_adoption["waiver_kind"] == "NONE"


def test_flat_and_age_scaled_deposits_diverge_and_redeem_on_proof(api):
    """PRD 3.8: "**The deferred-alteration deposit** is a separate, refundable amount
    assessed only when the animal is not `ALTERED` and its `age_weeks` is below 16.
    Under a `FLAT` `deposit_basis` it is always 15000 cents, however young the animal
    is. Under `AGE_SCALED` it is 1200 cents for each week the animal falls short of 16
    weeks, clamped to a floor of 6000 cents and a cap of 18000 cents — so a twelve-week
    animal's raw figure sits below the floor and the floor binds, while a newborn's raw
    figure exceeds the cap and the cap binds."
    PRD 3.8: "The result is stored as `alteration_deposit_cents`, defaulting to 0 when
    no deposit is due, and assessing a deposit moves the animal's `alteration_status`
    to `DEFERRED_DEPOSIT`."
    PRD 3.8: "Supplying a `proof_reference` sets `alteration_deposit_refunded_cents`,
    moves the animal's `alteration_status` `DEFERRED_DEPOSIT → ALTERED`, and increments
    both the adoption's `version` and the animal's `version`."
    PRD 3.8: "The target the payment is measured against is `adopter_charged_cents`
    **plus** `alteration_deposit_cents` — the adopter must cover both."

    Kittens born 2026-04-01 are 8 weeks old on 2026-06-01, so the AGE_SCALED figure is
    1200 * (16 - 8) = 9600, inside the 6000-to-18000 clamp; the adopter pays the whole
    12500 + 9600 = 22100 target before the deposit is redeemed.

    Design: Corner/calculations/alteration_deposit_flat_versus_age_scaled_and_redemption
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    adopter = new_adopter(api)
    kittens = []
    for name in ("K1", "K2"):
        kitten = new_animal(api, org["id"], name=name, species="CAT", size_class="SMALL",
                            weight_lb=3.0, date_of_birth="2026-04-01T00:00:00Z")
        take_into_custody(api, kitten["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
        kittens.append(kitten)

    set_clock(api, "2026-06-01T00:00:00Z")
    applications = []
    for kitten in kittens:
        application = submit_application(api, kitten["id"], adopter["id"])
        screen_application(api, application["id"], "APPROVE", COUNSELOR_ONE)
        applications.append(application)

    assert validate_success(api.get_animal(kittens[0]["id"], ADMIN))["age_weeks"] == 8

    flat = finalize_adoption(
        api, applications[0]["id"], animal_version(api, kittens[0]["id"]), COUNSELOR_TWO,
        deposit_basis="FLAT",
    )
    scaled = finalize_adoption(
        api, applications[1]["id"], animal_version(api, kittens[1]["id"]), COUNSELOR_TWO,
        deposit_basis="AGE_SCALED",
    )

    assert flat["alteration_deposit_cents"] == 15000
    assert scaled["alteration_deposit_cents"] == 9600
    assert flat["adopter_charged_cents"] == 12500
    assert scaled["adopter_charged_cents"] == 12500
    assert validate_success(api.get_animal(kittens[0]["id"], ADMIN))[
        "alteration_status"
    ] == "DEFERRED_DEPOSIT"

    paid = validate_success(
        api.pay_adoption(scaled["id"], {"amount_cents": 22100},
                         make_adopter_headers(adopter["id"]))
    )
    assert paid["adopter_paid_cents"] == 22100
    assert paid["fee_status"] == "PAID"

    redeemed = validate_success(
        api.redeem_alteration_proof(scaled["id"], {"proof_reference": "SN-CERT-7781"}, VET)
    )
    assert redeemed["alteration_deposit_refunded_cents"] == 9600
    assert validate_success(api.get_animal(kittens[1]["id"], ADMIN))[
        "alteration_status"
    ] == "ALTERED"


# --------------------------------------------------------------------------
# Finalization preconditions
# --------------------------------------------------------------------------
def test_finalizing_auto_declines_every_sibling_application(api):
    """PRD 3.8: "The application moves `APPROVED → FINALIZED`. Every **other**
    application on the same animal standing at `SUBMITTED` or `APPROVED` is moved to
    `AUTO_DECLINED` with `decline_reason` `SUPERSEDED_BY_FINALIZED_SIBLING`."
    PRD 3.9: "And the animal itself moves `IN_CUSTODY → OUTCOME_CLOSED`, with its
    `version` incremented. From that moment the outcome-closed gate of §2.6 fires
    against it."

    Design: Corner/state_machines/adoption_finalize_auto_declines_sibling_applications
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    applicants = [
        new_adopter(api, "Ann One", "ann@example.test"),
        new_adopter(api, "Bo Two", "bo@example.test"),
        new_adopter(api, "Cy Three", "cy@example.test"),
    ]
    animal = new_animal(api, org["id"], name="Rex", weight_lb=40.0,
                        date_of_birth="2022-01-01T00:00:00Z")
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    make_altered(api, animal["id"], "2026-05-01T00:00:00Z")

    applications = [submit_application(api, animal["id"], person["id"]) for person in applicants]
    screen_application(api, applications[0]["id"], "APPROVE", COUNSELOR_ONE)
    screen_application(api, applications[1]["id"], "APPROVE", COUNSELOR_ONE)

    adoption = finalize_adoption(
        api, applications[0]["id"], animal_version(api, animal["id"]), COUNSELOR_TWO
    )
    assert adoption["base_fee_cents"] == 25000

    assert validate_success(api.get_adoption_application(applications[0]["id"], COUNSELOR))[
        "status"
    ] == "FINALIZED"
    for superseded in applications[1:]:
        row = validate_success(api.get_adoption_application(superseded["id"], COUNSELOR))
        assert row["status"] == "AUTO_DECLINED"
        assert row["decline_reason"] == "SUPERSEDED_BY_FINALIZED_SIBLING"

    assert validate_success(api.get_animal(animal["id"], ADMIN))[
        "lifecycle_status"
    ] == "OUTCOME_CLOSED"


def test_the_screening_actor_may_not_also_finalize(api):
    """PRD 3.8: "The finalizing `X-User-ID` must differ from the application's
    `screened_by_user_id`, failing which the answer is `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403) — and `PlatformAdmin` gets no exemption."
    PRD 2.1: "The actor whose `X-User-ID` screened an adoption application to
    `APPROVED` may not be the actor who later finalizes that application into an
    `Adoption`, whatever role either of them holds."
    PRD 3.8: "Both branches record the acting `X-User-ID` as `screened_by_user_id` and
    the current clock instant as `screened_at`, and both increment the application's
    `version` by one."

    Design: Corner/validations/segregation_of_duties_same_actor_screens_and_finalizes
    """
    scenario = setup_adoptable_animal(
        api, clock_at_intake="2026-05-01T00:00:00Z", clock_at_adoption="2026-05-01T00:00:00Z",
        date_of_birth="2022-01-01T00:00:00Z",
    )
    application = validate_success(
        api.get_adoption_application(scenario["application"]["id"], COUNSELOR)
    )
    assert application["screened_by_user_id"] == COUNSELOR_ONE

    expected_version = animal_version(api, scenario["animal"]["id"])
    validate_error(
        api.create_adoption(
            adoption_payload(application["id"], expected_version),
            make_counselor_headers(COUNSELOR_ONE),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )

    adoption = finalize_adoption(api, application["id"], expected_version, COUNSELOR_TWO)
    assert adoption["finalized_by_user_id"] == COUNSELOR_TWO
    assert adoption["adopter_charged_cents"] == 25000
    assert validate_success(api.get_adoption_application(application["id"], COUNSELOR))[
        "status"
    ] == "FINALIZED"


def test_the_stray_hold_blocks_finalization_but_not_screening(api):
    """PRD 3.8: "Screening is deliberately permitted while the animal's stray hold is
    still `HOLD_ACTIVE` — the counselor can do the paperwork during the hold; it is
    only finalization that must wait."
    PRD 3.8: "The animal's current custody episode must have latched to
    `HOLD_EXPIRED`, failing which the answer is `ERR_STRAY_HOLD_NOT_EXPIRED`."

    Design: Corner/validations/stray_hold_blocks_finalize_but_permits_screening
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    adopter = new_adopter(api)
    animal = new_animal(api, org["id"], name="Rex", weight_lb=40.0,
                        date_of_birth="2022-01-01T00:00:00Z")
    episode = take_into_custody(api, animal["id"], "STRAY", "2026-05-01T00:00:00Z")
    make_altered(api, animal["id"], "2026-05-01T00:00:00Z")

    set_clock(api, "2026-05-02T00:00:00Z")
    application = submit_application(api, animal["id"], adopter["id"])
    expected_version = animal_version(api, animal["id"])

    screened = validate_success(
        api.screen_adoption_application(
            application["id"], {"decision": "APPROVE"}, make_counselor_headers(COUNSELOR_ONE)
        )
    )
    assert screened["status"] == "APPROVED"

    validate_error(
        api.create_adoption(
            adoption_payload(application["id"], expected_version),
            make_counselor_headers(COUNSELOR_TWO),
        ),
        ApiErrorId.ERR_STRAY_HOLD_NOT_EXPIRED.value,
        409,
    )
    episode_read = validate_success(api.get_intake_record(episode["id"], INTAKE))
    assert_same_instant(
        episode_read["hold_expires_at"], "2026-05-04T00:00:00Z", "hold_expires_at"
    )

    set_clock(api, "2026-05-04T00:00:00Z")
    adoption = finalize_adoption(api, application["id"], expected_version, COUNSELOR_TWO)
    assert adoption["base_fee_cents"] == 25000
    assert validate_success(api.get_intake_record(episode["id"], INTAKE))[
        "hold_status"
    ] == "HOLD_EXPIRED"


def test_a_stale_animal_version_is_rejected_on_finalize(api):
    """PRD 2.7: "Finalizing an adoption requires `expected_animal_version`, carrying the
    caller's last observed `version` of the `Animal` being adopted."
    PRD 2.7: "If a hold, a restriction update, or any other write has advanced the
    animal's `version` since the counselor read it, the finalize is refused rather than
    being computed against a posture the counselor never saw."
    PRD 3.1: "All five restriction fields are individually optional on that update;
    those supplied replace their prior values, those omitted are left alone, and the
    animal's `version` increments by one."

    Design: Corner/cross_cutting_layers/occ_stale_animal_version_rejected_on_adoption_finalize
    """
    scenario = setup_adoptable_animal(
        api, clock_at_intake="2026-05-01T00:00:00Z", clock_at_adoption="2026-05-01T00:00:00Z",
        date_of_birth="2022-01-01T00:00:00Z",
    )
    stale_version = animal_version(api, scenario["animal"]["id"])

    validate_success(
        api.update_animal_restrictions(
            scenario["animal"]["id"], {"restriction_requires_fenced_yard": True},
            make_counselor_headers(COUNSELOR_ONE),
        )
    )

    validate_error(
        api.create_adoption(
            adoption_payload(scenario["application"]["id"], stale_version),
            make_counselor_headers(COUNSELOR_TWO),
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
        412,
    )

    adoption = finalize_adoption(
        api, scenario["application"]["id"], animal_version(api, scenario["animal"]["id"]),
        COUNSELOR_TWO,
    )
    assert adoption["adopter_charged_cents"] == 25000
    assert validate_success(
        api.get_adoption_application(scenario["application"]["id"], COUNSELOR)
    )["status"] == "FINALIZED"


def test_an_adopter_may_not_screen_their_own_application(api):
    """PRD 2.1: "Only once the role is recognised does the system ask whether that role
    is listed as authorised for the endpoint being called; when it is not, the answer
    is `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 2.1: "`AdoptionCounselor` screens adoption applications, finalizes adoptions
    and processes adopter returns."
    PRD 3.8: "A surviving application is created in `status` `SUBMITTED` with
    `attempt_count` 1, and with `screened_by_user_id`, `screened_at` and
    `decline_reason` all null."

    Design: Corner/rbac/adopter_cannot_screen_an_adoption_application
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    adopter = new_adopter(api)
    animal = new_animal(api, org["id"], name="Rex", weight_lb=40.0,
                        date_of_birth="2022-01-01T00:00:00Z")
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")

    adopter_headers = make_adopter_headers(adopter["id"])
    application = validate_success(
        api.create_adoption_application(
            adoption_application_payload(animal["id"], adopter["id"]), adopter_headers
        ),
        201,
    )

    validate_error(
        api.screen_adoption_application(
            application["id"], {"decision": "APPROVE"}, adopter_headers
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    after = validate_success(api.get_adoption_application(application["id"], COUNSELOR))
    assert after["status"] == "SUBMITTED"
    assert after["screened_by_user_id"] is None

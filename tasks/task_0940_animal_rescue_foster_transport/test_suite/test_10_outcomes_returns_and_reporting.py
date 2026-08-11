"""Outcomes, the adopter return and the live-release report."""
from test_helpers import (
    COUNSELOR_ONE,
    COUNSELOR_THREE,
    COUNSELOR_TWO,
    TEST_USERS,
    ApiErrorId,
    animal_version,
    assert_contribution_money_conserved,
    assert_outcome_record,
    finalize_adoption,
    make_adopter_headers,
    make_altered,
    make_counselor_headers,
    new_adopter,
    new_animal,
    new_contribution,
    new_organization,
    new_person,
    open_intake_for,
    record_outcome,
    screen_application,
    set_clock,
    setup_finalized_adoption,
    standing_outcome_for,
    submit_application,
    take_into_custody,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_officer_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
COUNSELOR = TEST_USERS["adoption_counselor_headers"]


# --------------------------------------------------------------------------
# The live-release report under its two methodologies
# --------------------------------------------------------------------------
def _four_outcomes_in_may(api):
    """One ADOPTION, one EUTHANASIA_MEDICAL and two EUTHANASIA_OWNER_REQUESTED
    outcomes, all recorded on 2026-05-10."""
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    counterparty = new_person(api, "Ivy Chen", "ivy@example.test")
    animals = []
    for index, name in enumerate(("A1", "A2", "A3", "A4")):
        animal = new_animal(api, org["id"], name=name, size_class="SMALL",
                            weight_lb=20.0 + index, date_of_birth="2020-01-01T00:00:00Z")
        take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
        animals.append(animal)

    set_clock(api, "2026-05-10T00:00:00Z")
    record_outcome(api, animals[0]["id"], "ADOPTION", counterparty_person_id=counterparty["id"])
    record_outcome(api, animals[1]["id"], "EUTHANASIA_MEDICAL")
    record_outcome(api, animals[2]["id"], "EUTHANASIA_OWNER_REQUESTED")
    record_outcome(api, animals[3]["id"], "EUTHANASIA_OWNER_REQUESTED")
    return {"org": org, "animals": animals}


def test_sac_keeps_owner_requested_euthanasia_in_the_denominator(api):
    """PRD 3.9: "Three counts are then taken over that pool and reported:
    `live_outcome_count` over the four live types, `non_live_outcome_count` over the
    five non-live types, and `owner_requested_euthanasia_count` over
    `EUTHANASIA_OWNER_REQUESTED` alone."
    PRD 3.9: "Under `SAC` it is the live count plus the non-live count, leaving
    owner-requested euthanasia in and depressing the rate."
    PRD 3.9: "`live_release_rate` is the live count divided by the denominator, rounded
    half up to four decimal places — and is reported as null, not zero, when the
    denominator is zero."

    One live outcome against three non-live ones gives a denominator of 4 and a rate of
    1 / 4 == 0.25.

    Design: Difficulty/dual_variant_calc/live_release_rate_sac_vs_asilomar_denominator
    """
    _four_outcomes_in_may(api)

    report = validate_success(
        api.live_release_report(
            ADMIN,
            {"from_date": "2026-05-01", "to_date": "2026-05-31", "methodology": "SAC"},
        )
    )
    assert report["methodology"] == "SAC"
    assert report["live_outcome_count"] == 1
    assert report["non_live_outcome_count"] == 3
    assert report["owner_requested_euthanasia_count"] == 2
    assert report["denominator"] == 4
    assert report["live_release_rate"] == 0.25


def test_asilomar_removes_owner_requested_euthanasia_from_the_denominator(api):
    """PRD 3.9: "Under `ASILOMAR` it is that same sum **less** the owner-requested count,
    removing those cases from the denominator entirely, so identical data yields a
    strictly higher rate whenever any owner-requested euthanasia falls in the window."
    PRD 3.9: "The response echoes the `methodology`, `from_date` and `to_date` it was
    computed under."

    The same four outcomes give a denominator of 4 - 2 == 2 and a rate of
    1 / 2 == 0.5.

    Design: Difficulty/dual_variant_calc/live_release_rate_sac_vs_asilomar_denominator
    """
    _four_outcomes_in_may(api)

    report = validate_success(
        api.live_release_report(
            ADMIN,
            {"from_date": "2026-05-01", "to_date": "2026-05-31", "methodology": "ASILOMAR"},
        )
    )
    assert report["methodology"] == "ASILOMAR"
    assert report["owner_requested_euthanasia_count"] == 2
    assert report["denominator"] == 2
    assert report["live_release_rate"] == 0.5
    assert report["from_date"] == "2026-05-01"
    assert report["to_date"] == "2026-05-31"


def test_an_empty_window_reports_a_null_rate_rather_than_zero(api):
    """PRD 3.9: "The pool consists of outcome records whose `reversed_at` is null and
    whose `recorded_at` date falls on or after `from_date` and on or before `to_date`;
    when `organization_id` is supplied, the pool is further narrowed to outcomes whose
    animal's `current_organization_id` matches."
    PRD 3.9: "`live_release_rate` is the live count divided by the denominator, rounded
    half up to four decimal places — and is reported as null, not zero, when the
    denominator is zero."

    Design: Difficulty/boundary_precision_check/live_release_rate_empty_window_returns_null_rate
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    animal = new_animal(api, org["id"], name="Solo", species="CAT", size_class="SMALL",
                        weight_lb=9.0, date_of_birth="2023-01-01T00:00:00Z")
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    set_clock(api, "2026-05-10T00:00:00Z")
    record_outcome(api, animal["id"], "DIED_IN_CARE")

    response = api.live_release_report(
        ADMIN, {"from_date": "2026-06-01", "to_date": "2026-06-30", "methodology": "SAC"}
    )
    report = validate_success(response, 200)
    assert report["denominator"] == 0
    assert report["live_release_rate"] is None
    assert report["live_outcome_count"] == 0
    assert report["non_live_outcome_count"] == 0


def test_a_window_holding_one_non_live_outcome_reports_a_zero_rate(api):
    """PRD 3.9: "Three counts are then taken over that pool and reported:
    `live_outcome_count` over the four live types, `non_live_outcome_count` over the
    five non-live types, and `owner_requested_euthanasia_count` over
    `EUTHANASIA_OWNER_REQUESTED` alone."
    PRD 3.9: "Under `SAC` it is the live count plus the non-live count, leaving
    owner-requested euthanasia in and depressing the rate."

    A single DIED_IN_CARE outcome gives a denominator of 1 and a rate of 0 / 1 == 0.0,
    which is a real zero rather than the null of an empty denominator.

    Design: Difficulty/boundary_precision_check/live_release_rate_empty_window_returns_null_rate
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    animal = new_animal(api, org["id"], name="Solo", species="CAT", size_class="SMALL",
                        weight_lb=9.0, date_of_birth="2023-01-01T00:00:00Z")
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    set_clock(api, "2026-05-10T00:00:00Z")
    record_outcome(api, animal["id"], "DIED_IN_CARE")

    report = validate_success(
        api.live_release_report(
            ADMIN,
            {"from_date": "2026-05-01", "to_date": "2026-05-31", "methodology": "SAC"},
        )
    )
    assert report["denominator"] == 1
    assert report["live_release_rate"] == 0.0
    assert report["live_outcome_count"] == 0
    assert report["non_live_outcome_count"] == 1


# --------------------------------------------------------------------------
# The adopter return
# --------------------------------------------------------------------------
def _paid_senior_adoption(api):
    """A senior dog adopted on 2026-06-01 under CREDIT_FIRST with a 20000-cent
    sponsorship, charged 2000 and paid in full, with the clock at 2026-06-21."""
    scenario = setup_finalized_adoption(
        api, sponsorship_cents=20000, sponsorship_reference="SPON-A",
        date_of_birth="2018-01-01T00:00:00Z", size_class="LARGE", weight_lb=65.0,
        finalize_options={"credit_application_order": "CREDIT_FIRST"},
    )
    paid = validate_success(
        api.pay_adoption(
            scenario["adoption"]["id"], {"amount_cents": 2000},
            make_adopter_headers(scenario["adopter"]["id"]),
        )
    )
    scenario["fee_status_after_payment"] = paid["fee_status"]
    scenario["outcome"] = standing_outcome_for(api, scenario["animal"]["id"], "ADOPTION")
    scenario["original_episode_id"] = scenario["outcome"]["intake_record_id"]
    set_clock(api, "2026-06-21T00:00:00Z")
    return scenario


def test_a_return_inside_the_partial_tier_refunds_half_the_cash(api):
    """PRD 3.8: "When the new `adopter_paid_cents` still falls short of that target the
    axis moves `UNPAID → PARTIALLY_PAID`; when it reaches or exceeds the target it
    moves `UNPAID → PAID` or `PARTIALLY_PAID → PAID`."
    PRD 3.9: "Inside the window the refund tier is chosen by whole elapsed days between
    `finalized_at` and the clock, rounded down. Fourteen days or fewer refunds 100
    percent; more than fourteen but no more than thirty refunds 50 percent; beyond
    thirty the tier would be 0 percent, but that case is unreachable in practice
    because the return is refused outright at the same boundary — the zero tier is
    retained only for completeness."
    PRD 3.9: "Under `FEE_PAID`, only the adopter's cash is refunded:
    `credit_restored_cents` stays at zero, and the sponsoring contributions keep their
    `applied_cents` untouched."
    PRD 3.9: "Hop one writes `returned_at`, `refund_issued_cents` and
    `credit_restored_cents`, and advances the money axis: from `PAID` to
    `REFUNDED_PARTIAL` when the refund is strictly positive and strictly less than
    `adopter_paid_cents`, or from `PAID` to `REFUNDED_FULL` when the refund equals
    `adopter_paid_cents` and that figure is itself strictly positive."

    Twenty whole days elapse between 2026-06-01 and 2026-06-21, which is inside the
    50-percent tier, so 2000 cents of cash refunds 1000.

    Design: Difficulty/transitive_cascade/adoption_return_reverses_outcome_and_reenters_intake
    """
    scenario = _paid_senior_adoption(api)
    assert scenario["fee_status_after_payment"] == "PAID"

    returned = validate_success(
        api.return_adoption(
            scenario["adoption"]["id"], make_counselor_headers(COUNSELOR_THREE),
            {"reason": "housing change"},
        )
    )
    assert returned["status"] == "RETURNED"
    assert returned["refund_issued_cents"] == 1000
    assert returned["credit_restored_cents"] == 0
    assert returned["fee_status"] == "REFUNDED_PARTIAL"

    outcome = validate_success(api.get_outcome(scenario["outcome"]["id"], INTAKE))
    assert_outcome_record(outcome)
    assert outcome["reversed_at"] is not None
    assert outcome["reversal_reason"] == "ADOPTER_RETURN"


def test_a_return_voids_the_old_episode_and_opens_a_return_episode(api):
    """PRD 3.9: "Hop three moves the superseded custody episode `CLOSED → VOIDED` and
    creates a fresh episode with `intake_type` `RETURN`, a `hold_days` of zero and a
    `hold_status` already latched to `HOLD_EXPIRED` — an animal coming back from an
    adoption serves no stray hold. Hop four moves the animal `OUTCOME_CLOSED →
    IN_CUSTODY` and repoints its `current_intake_record_id` at the new episode."

    Design: Difficulty/transitive_cascade/adoption_return_reverses_outcome_and_reenters_intake
    """
    scenario = _paid_senior_adoption(api)

    validate_success(
        api.return_adoption(
            scenario["adoption"]["id"], make_counselor_headers(COUNSELOR_THREE),
            {"reason": "housing change"},
        )
    )

    original = validate_success(
        api.get_intake_record(scenario["original_episode_id"], INTAKE)
    )
    assert original["status"] == "VOIDED"

    new_episode = open_intake_for(api, scenario["animal"]["id"])
    assert new_episode["intake_type"] == "RETURN"
    assert new_episode["hold_days"] == 0
    assert new_episode["hold_status"] == "HOLD_EXPIRED"
    assert new_episode["status"] == "OPEN"

    animal = validate_success(api.get_animal(scenario["animal"]["id"], ADMIN))
    assert animal["lifecycle_status"] == "IN_CUSTODY"
    assert animal["current_intake_record_id"] == new_episode["id"]


def test_a_return_after_the_outer_window_is_refused(api):
    """PRD 3.9: "It also requires the clock to be at or before `finalized_at` advanced
    by 30 days; beyond that outer window the return itself is refused with
    `ERR_RETURN_WINDOW_CLOSED`."

    A finalize on 2026-06-01 and a return attempt on 2026-07-05 are 34 whole days
    apart, past the 30-day outer window.

    Design: Corner/validations/return_window_closed_after_thirty_days
    """
    scenario = setup_finalized_adoption(
        api, date_of_birth="2022-01-01T00:00:00Z",
    )
    set_clock(api, "2026-07-05T00:00:00Z")

    validate_error(
        api.return_adoption(
            scenario["adoption"]["id"], make_counselor_headers(COUNSELOR_THREE),
            {"reason": "too late"},
        ),
        ApiErrorId.ERR_RETURN_WINDOW_CLOSED.value,
        409,
    )

    adoption = validate_success(api.get_adoption(scenario["adoption"]["id"], COUNSELOR))
    assert adoption["status"] == "FINALIZED"
    assert adoption["refund_issued_cents"] == 0
    assert validate_success(api.get_animal(scenario["animal"]["id"], ADMIN))[
        "lifecycle_status"
    ] == "OUTCOME_CLOSED"


def test_fee_assessed_restores_the_tier_share_of_the_sponsorship_credit(api):
    """PRD 3.9: "Under `FEE_ASSESSED`, the same cash refund is issued **and** the same
    tier percentage of `sponsorship_applied_cents`, rounded half up, is returned to the
    sponsoring contributions as `credit_restored_cents`, raising their
    `available_cents` and possibly moving a contribution `FULLY_APPLIED →
    PARTIALLY_APPLIED`."
    PRD 3.9: "`refund_issued_cents` is the tier percentage applied to
    `adopter_paid_cents` and rounded half up."

    A single sponsoring contribution supplied all 20000 cents, so the 50-percent tier
    restores 10000 to it and the allocation across contributions cannot diverge.

    Design: Corner/calculations/return_refund_fee_assessed_restores_sponsorship_credit
    """
    scenario = setup_finalized_adoption(
        api, sponsorship_cents=20000, sponsorship_reference="SPON-FA",
        date_of_birth="2018-01-01T00:00:00Z", size_class="LARGE", weight_lb=65.0,
        finalize_options={"credit_application_order": "CREDIT_FIRST",
                          "refund_basis": "FEE_ASSESSED"},
    )
    assert scenario["adoption"]["sponsorship_applied_cents"] == 20000

    paid = validate_success(
        api.pay_adoption(
            scenario["adoption"]["id"], {"amount_cents": 2000},
            make_adopter_headers(scenario["adopter"]["id"]),
        )
    )
    assert paid["fee_status"] == "PAID"

    set_clock(api, "2026-06-21T00:00:00Z")
    returned = validate_success(
        api.return_adoption(
            scenario["adoption"]["id"], make_counselor_headers(COUNSELOR_THREE),
            {"reason": "landlord objection"},
        )
    )
    assert returned["refund_issued_cents"] == 1000
    assert returned["credit_restored_cents"] == 10000

    contribution = validate_success(
        api.get_contribution(scenario["contribution"]["id"], FINANCE)
    )
    assert contribution["applied_cents"] == 10000
    assert contribution["available_cents"] == 10000
    assert contribution["status"] == "PARTIALLY_APPLIED"
    assert_contribution_money_conserved(contribution)


# --------------------------------------------------------------------------
# The two conservation identities exercised by the compensating pair
# --------------------------------------------------------------------------
def _adopted_then_returned_senior_dog(api):
    """A senior dog adopted on 2026-06-01 with no sponsorship and no payment, whose
    adoption is returned on 2026-06-10."""
    scenario = setup_finalized_adoption(api, date_of_birth="2018-01-01T00:00:00Z",
                                        size_class="LARGE", weight_lb=65.0)
    scenario["outcome"] = standing_outcome_for(api, scenario["animal"]["id"], "ADOPTION")
    scenario["original_episode_id"] = scenario["outcome"]["intake_record_id"]
    scenario["pre_return_lifecycle"] = validate_success(
        api.get_animal(scenario["animal"]["id"], ADMIN)
    )["lifecycle_status"]
    set_clock(api, "2026-06-10T00:00:00Z")
    return scenario


def test_the_return_compensates_the_close_and_reopens_one_episode(api):
    """PRD 2.10: "**Custody episodes.** The number of intake records that are not
    `VOIDED` equals the number of outcome records that have not been reversed, plus the
    number of animals whose `lifecycle_status` is `IN_CUSTODY`, `IN_TRANSIT` or
    `STRANDED`. An adopter return both reverses an outcome and opens a new episode
    while voiding the superseded one, so the identity survives the compensating pair."
    PRD 3.9: "Because the pair voids one episode and opens another while reversing one
    outcome, the custody-episode identity of §2.10 is preserved exactly."

    Design: Difficulty/compensating_invariant/intake_outcome_count_conservation_across_adoption_return
    """
    scenario = _adopted_then_returned_senior_dog(api)
    assert scenario["pre_return_lifecycle"] == "OUTCOME_CLOSED"

    validate_success(
        api.return_adoption(
            scenario["adoption"]["id"], make_counselor_headers(COUNSELOR_THREE),
            {"reason": "allergy in household"},
        )
    )

    assert validate_success(
        api.get_intake_record(scenario["original_episode_id"], INTAKE)
    )["status"] == "VOIDED"

    reopened = open_intake_for(api, scenario["animal"]["id"])
    assert reopened["intake_type"] == "RETURN"
    assert reopened["status"] == "OPEN"
    assert validate_success(api.get_outcome(scenario["outcome"]["id"], INTAKE))[
        "reversed_at"
    ] is not None
    assert validate_success(api.get_animal(scenario["animal"]["id"], ADMIN))[
        "lifecycle_status"
    ] == "IN_CUSTODY"


def test_the_custody_episode_count_identity_holds_after_the_return(api):
    """PRD 2.10: "**Custody episodes.** The number of intake records that are not
    `VOIDED` equals the number of outcome records that have not been reversed, plus the
    number of animals whose `lifecycle_status` is `IN_CUSTODY`, `IN_TRANSIT` or
    `STRANDED`."
    PRD 2.10: "Six identities must hold after every successful mutation. They are not
    reporting conveniences; they are the correctness contract of the ledgers, and any
    workflow described in §3 that appears to break one has been misread."

    After the return the whole system holds exactly one non-VOIDED custody episode,
    zero unreversed outcome records and exactly one in-custody animal: 1 == 0 + 1.

    Design: Difficulty/compensating_invariant/intake_outcome_count_conservation_across_adoption_return
    """
    scenario = _adopted_then_returned_senior_dog(api)

    validate_success(
        api.return_adoption(
            scenario["adoption"]["id"], make_counselor_headers(COUNSELOR_THREE),
            {"reason": "allergy in household"},
        )
    )

    episodes, _ = validate_paginated(
        api.list_intake_records(INTAKE, {"animal_id": scenario["animal"]["id"], "limit": 100})
    )
    live_episodes = [row for row in episodes if row["status"] != "VOIDED"]
    assert len(live_episodes) == 1, f"expected one non-VOIDED episode, got {live_episodes}"

    outcomes, _ = validate_paginated(
        api.list_outcomes(INTAKE, {"animal_id": scenario["animal"]["id"], "limit": 100})
    )
    standing = [row for row in outcomes if row["reversed_at"] is None]
    assert standing == [], f"expected no unreversed outcome, got {standing}"

    animals, _ = validate_paginated(
        api.list_animals(ADMIN, {"lifecycle_status": "IN_CUSTODY", "limit": 100})
    )
    assert len(animals) == 1
    assert len(live_episodes) == len(standing) + len(animals)


def test_the_waiver_first_residual_credit_is_released_on_the_outcome_cascade(api):
    """PRD 3.9: "Every contribution designated to this animal that still carries
    `available_cents` greater than zero moves to `RELEASED`: its remaining
    `available_cents` shifts into `released_cents` and the organization's
    `unrestricted_balance_cents` rises by the same amount — this is what finally frees
    the residual credit that a `WAIVER_FIRST` adoption left stranded."
    PRD 2.10: "**Donated cents.** For every contribution, `amount_cents` equals
    `applied_cents` plus `released_cents` plus `available_cents`."
    PRD 3.9: "A designated gift therefore ends either `FULLY_APPLIED`, every cent
    spent, or `RELEASED`, the residual handed to unrestricted funds — never both."

    Under WAIVER_FIRST the 20000-cent gift is drawn for 10000, and the adoption's own
    outcome cascade releases the remaining 10000.

    Design: Difficulty/compensating_invariant/contribution_money_conservation_across_residual_release
    """
    scenario = setup_finalized_adoption(
        api, sponsorship_cents=20000, sponsorship_reference="SPON-R",
        date_of_birth="2018-01-01T00:00:00Z", size_class="LARGE", weight_lb=65.0,
        finalize_options={"credit_application_order": "WAIVER_FIRST"},
    )
    assert scenario["adoption"]["residual_credit_cents"] == 10000
    assert scenario["adoption"]["adopter_charged_cents"] == 0

    contribution = validate_success(
        api.get_contribution(scenario["contribution"]["id"], FINANCE)
    )
    assert contribution["applied_cents"] == 10000
    assert contribution["released_cents"] == 10000
    assert contribution["available_cents"] == 0
    assert contribution["status"] == "RELEASED"
    assert_contribution_money_conserved(contribution)


def test_the_released_residual_lands_in_the_organizations_unrestricted_funds(api):
    """PRD 3.9: "`unrestricted_balance_cents` is the sum of `available_cents` over
    contributions whose `restriction_category` **is** `UNRESTRICTED` and whose `status`
    is `RECEIVED` or `PARTIALLY_APPLIED`, **plus** the sum of `released_cents` over
    every contribution whatever its category, **less** the sum of
    `admin_overhead_cents` over every completed medical record, **less** the sum of
    `cost_cents` over every completed medical record whose `funding_required` was
    false."
    PRD 3.8: "That residual is never refunded to the adopter and is never applied
    beyond the fee. It stays on its contribution until the adoption's own outcome
    cascade releases it into the organization's unrestricted funds — see §3.9."

    Before finalization the gift is fully available at 20000; afterwards 10000 is
    applied and the remaining 10000 sits in `released_cents`, so the organization's
    unrestricted position moves from 20000 to 10000.

    Design: Difficulty/compensating_invariant/contribution_money_conservation_across_residual_release
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    adopter = new_adopter(api)
    donor = new_person(api, "Gil Marsh", "gil@example.test")
    animal = new_animal(api, org["id"], name="Rex", size_class="LARGE", weight_lb=65.0,
                        date_of_birth="2018-01-01T00:00:00Z")
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    make_altered(api, animal["id"], "2026-05-01T00:00:00Z")
    contribution = new_contribution(
        api, donor["id"], 20000, "SPON-R", designated_animal_id=animal["id"],
        designated_program="NONE", restriction_category="UNRESTRICTED",
    )
    assert contribution["available_cents"] == 20000

    before = validate_success(api.get_organization(org["id"], ADMIN))
    assert before["unrestricted_balance_cents"] == 20000

    set_clock(api, "2026-06-01T00:00:00Z")
    application = submit_application(api, animal["id"], adopter["id"])
    screen_application(api, application["id"], "APPROVE", COUNSELOR_ONE)
    adoption = finalize_adoption(
        api, application["id"], animal_version(api, animal["id"]), COUNSELOR_TWO,
        credit_application_order="WAIVER_FIRST",
    )
    assert adoption["residual_credit_cents"] == 10000

    after = validate_success(api.get_organization(org["id"], ADMIN))
    assert after["unrestricted_balance_cents"] == 10000

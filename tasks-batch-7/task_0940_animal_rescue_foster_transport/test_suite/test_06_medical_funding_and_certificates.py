"""Veterinary work: restricted funding draws, per-line overhead and certificates."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_contribution_money_conserved,
    assert_health_certificate,
    assert_medical_record,
    assert_same_instant,
    health_certificate_payload,
    medical_record_payload,
    new_animal,
    new_contribution,
    new_organization,
    new_person,
    set_clock,
    take_into_custody,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
VET = TEST_USERS["veterinarian_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
INTAKE = TEST_USERS["intake_officer_headers"]


def _three_medical_gifts_and_a_funded_record(api):
    """Three MEDICAL gifts of 3333, 3333 and 10000 cents created at strictly
    increasing instants, plus one ORDERED 10000-cent funded MEDICAL record."""
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    donor = new_person(api, "Gil Marsh", "gil@example.test")
    animal = new_animal(api, org["id"], name="Pixel", species="CAT", size_class="SMALL",
                        weight_lb=9.0, date_of_birth="2024-01-01T00:00:00Z")
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")

    set_clock(api, "2026-05-02T00:00:00Z")
    c1 = new_contribution(api, donor["id"], 3333, "M-001",
                          restriction_category="MEDICAL", designated_program="NONE")
    set_clock(api, "2026-05-02T01:00:00Z")
    c2 = new_contribution(api, donor["id"], 3333, "M-002",
                          restriction_category="MEDICAL", designated_program="NONE")
    set_clock(api, "2026-05-02T02:00:00Z")
    c3 = new_contribution(api, donor["id"], 10000, "M-003",
                          restriction_category="MEDICAL", designated_program="NONE")

    record = validate_success(
        api.create_medical_record(
            animal["id"],
            medical_record_payload(
                procedure_type="TREATMENT", expense_category="MEDICAL", cost_cents=10000,
                scheduled_at="2026-05-02T03:00:00Z", funding_required=True,
            ),
            VET,
        ),
        201,
    )
    return {"org": org, "animal": animal, "c1": c1, "c2": c2, "c3": c3, "record": record}


def test_admin_overhead_is_rounded_once_per_draw_line_then_summed(api):
    """PRD 3.5: "Administrative overhead of 8 percent is computed on **each individual
    line**, rounded half up to whole cents at that point, and the rounded per-line
    figures are then summed into `admin_overhead_cents`; as §2.8 insists, summing the
    lines and rounding once at the end is a different and incorrect number."
    PRD 3.5: "They are drawn in a fully pinned order: `created_at` ascending first;
    then, among rows created at the same instant, `amount_cents` **descending**; and
    finally, as a last resort, `donor_reference` ascending lexicographically."
    PRD 3.5: "The identifiers of the drawn contributions are recorded in draw order as
    `funded_contribution_ids`, `funded_amount_cents` is set to the full `cost_cents`,
    and the organization's `unrestricted_balance_cents` is lowered by
    `admin_overhead_cents`."

    The 10000-cent cost splits into lines of 3333, 3333 and 3334. Eight percent of
    3333 is 266.64 which rounds half up to 267, and eight percent of 3334 is 266.72
    which also rounds to 267, so admin_overhead_cents is 267 + 267 + 267 = 801 — not
    the 800 that rounding the 10000-cent total once would give.

    Design: Difficulty/combinatorial_formula/medical_funding_per_line_overhead_rounding_mode_b
    """
    scenario = _three_medical_gifts_and_a_funded_record(api)

    completed = validate_success(api.complete_medical_record(scenario["record"]["id"], VET))
    assert_medical_record(completed)
    assert completed["status"] == "COMPLETED"
    assert completed["funded_amount_cents"] == 10000
    assert completed["admin_overhead_cents"] == 801
    assert completed["funded_contribution_ids"] == [
        scenario["c1"]["id"], scenario["c2"]["id"], scenario["c3"]["id"]
    ], "the draw trail records the contributions in created_at ascending order"

    c1 = validate_success(api.get_contribution(scenario["c1"]["id"], FINANCE))
    c2 = validate_success(api.get_contribution(scenario["c2"]["id"], FINANCE))
    c3 = validate_success(api.get_contribution(scenario["c3"]["id"], FINANCE))
    assert c1["applied_cents"] == 3333
    assert c1["available_cents"] == 0
    assert c1["status"] == "FULLY_APPLIED"
    assert c2["applied_cents"] == 3333
    assert c2["status"] == "FULLY_APPLIED"
    assert c3["applied_cents"] == 3334
    assert c3["available_cents"] == 6666
    assert c3["status"] == "PARTIALLY_APPLIED"
    for gift in (c1, c2, c3):
        assert_contribution_money_conserved(gift)


def test_a_funded_completion_charges_the_organization_only_the_overhead(api):
    """PRD 3.5: "Note the asymmetry: under funded completion the organization pays only
    the overhead, because the donors paid the cost; under unfunded completion the
    organization pays the entire cost and no overhead."
    PRD 3.9: "`unrestricted_balance_cents` is the sum of `available_cents` over
    contributions whose `restriction_category` **is** `UNRESTRICTED` and whose `status`
    is `RECEIVED` or `PARTIALLY_APPLIED`, **plus** the sum of `released_cents` over
    every contribution whatever its category, **less** the sum of
    `admin_overhead_cents` over every completed medical record, **less** the sum of
    `cost_cents` over every completed medical record whose `funding_required` was
    false."
    PRD 3.9: "`restricted_balance_cents` is the sum of `available_cents` over
    contributions whose `restriction_category` is not `UNRESTRICTED` and whose `status`
    is `RECEIVED` or `PARTIALLY_APPLIED`."

    With no unrestricted gifts, nothing released and no unfunded completion, the
    unrestricted position is 0 - 801 = -801, while the only gift still holding money is
    the third one at 6666 cents.

    Design: Difficulty/combinatorial_formula/medical_funding_per_line_overhead_rounding_mode_b
    """
    scenario = _three_medical_gifts_and_a_funded_record(api)
    validate_success(api.complete_medical_record(scenario["record"]["id"], VET))

    org = validate_success(api.get_organization(scenario["org"]["id"], FINANCE))
    assert org["unrestricted_balance_cents"] == -801
    assert org["restricted_balance_cents"] == 6666


def test_an_insufficient_eligible_pool_draws_nothing_at_all(api):
    """PRD 3.5: "If the total `available_cents` across the eligible pool is less than
    `cost_cents`, the completion is rejected with `ERR_INSUFFICIENT_RESTRICTED_FUNDS`
    and **nothing is drawn** — there are no partial draws and no partial completions."
    PRD 3.5: "A newly ordered record sits in `status` `ORDERED` with `completed_at`
    null, `funded_contribution_ids` an empty list, `funded_amount_cents` 0 and
    `admin_overhead_cents` 0."

    Design: Corner/calculations/medical_funding_insufficient_pool_rejects_completion
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    donor = new_person(api, "Gil Marsh", "gil@example.test")
    animal = new_animal(api, org["id"], name="Pixel", species="CAT", size_class="SMALL",
                        weight_lb=9.0, date_of_birth="2024-01-01T00:00:00Z")
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    gift = new_contribution(api, donor["id"], 5000, "GIFT-SHORT",
                            restriction_category="MEDICAL", designated_program="NONE")
    record = validate_success(
        api.create_medical_record(
            animal["id"],
            medical_record_payload(procedure_type="TREATMENT", expense_category="MEDICAL",
                                   cost_cents=10000, scheduled_at="2026-05-01T00:00:00Z",
                                   funding_required=True),
            VET,
        ),
        201,
    )

    validate_error(
        api.complete_medical_record(record["id"], VET),
        ApiErrorId.ERR_INSUFFICIENT_RESTRICTED_FUNDS.value,
        409,
    )

    after = validate_success(api.get_medical_record(record["id"], VET))
    assert after["status"] == "ORDERED"
    assert after["funded_amount_cents"] == 0
    assert after["admin_overhead_cents"] == 0
    gift_after = validate_success(api.get_contribution(gift["id"], FINANCE))
    assert gift_after["applied_cents"] == 0
    assert gift_after["available_cents"] == 5000


def test_naming_an_ineligible_contribution_reports_the_category_mismatch(api):
    """PRD 3.5: "Every explicitly named contribution must have a `restriction_category`
    equal to the record's `expense_category` or equal to `UNRESTRICTED`, and must not
    be designated to a different animal; a named contribution failing either test is
    rejected with `ERR_RESTRICTED_FUND_CATEGORY_MISMATCH`, and that check sits above
    the sufficiency check on the ladder, so an ineligible nomination reports the
    mismatch rather than an insufficiency."

    Design: Corner/calculations/medical_funding_explicit_ids_category_mismatch_rejected
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    donor = new_person(api, "Gil Marsh", "gil@example.test")
    animal = new_animal(api, org["id"], name="Pixel", species="CAT", size_class="SMALL",
                        weight_lb=9.0, date_of_birth="2024-01-01T00:00:00Z")
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    gift = new_contribution(api, donor["id"], 50000, "GIFT-TRANSPORT",
                            restriction_category="TRANSPORT",
                            designated_program="TRANSPORT_FUND")
    record = validate_success(
        api.create_medical_record(
            animal["id"],
            medical_record_payload(procedure_type="TREATMENT", expense_category="MEDICAL",
                                   cost_cents=1000, scheduled_at="2026-05-01T00:00:00Z",
                                   funding_required=True),
            VET,
        ),
        201,
    )

    validate_error(
        api.complete_medical_record(record["id"], VET,
                                    {"funding_contribution_ids": [gift["id"]]}),
        ApiErrorId.ERR_RESTRICTED_FUND_CATEGORY_MISMATCH.value,
        422,
    )
    assert validate_success(api.get_medical_record(record["id"], VET))["status"] == "ORDERED"
    assert validate_success(api.get_contribution(gift["id"], FINANCE))["applied_cents"] == 0


def test_an_unfunded_completion_charges_the_whole_cost_to_unrestricted_funds(api):
    """PRD 3.5: "The money branches sharply on `funding_required`. When it is
    **false**, completion draws no contributions at all: the whole `cost_cents` is
    charged against the organization's `unrestricted_balance_cents`, which may drive
    that balance negative, and `funded_amount_cents` and `admin_overhead_cents` both
    stay at zero."
    PRD 3.9: "That last term is why an organization completing unfunded veterinary work
    can drive its unrestricted position **negative**; the figure is not floored at
    zero."

    Design: Corner/calculations/unfunded_medical_record_charges_unrestricted_balance_only
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    donor = new_person(api, "Gil Marsh", "gil@example.test")
    animal = new_animal(api, org["id"], name="Pixel", species="CAT", size_class="SMALL",
                        weight_lb=9.0, date_of_birth="2024-01-01T00:00:00Z")
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    gift = new_contribution(api, donor["id"], 5000, "GIFT-KEEP",
                            restriction_category="MEDICAL", designated_program="NONE")
    record = validate_success(
        api.create_medical_record(
            animal["id"],
            medical_record_payload(procedure_type="EXAM", expense_category="MEDICAL",
                                   cost_cents=4000, scheduled_at="2026-05-01T00:00:00Z",
                                   funding_required=False),
            VET,
        ),
        201,
    )

    completed = validate_success(api.complete_medical_record(record["id"], VET))
    assert completed["status"] == "COMPLETED"
    assert completed["funded_amount_cents"] == 0
    assert completed["admin_overhead_cents"] == 0
    assert_same_instant(completed["completed_at"], "2026-05-01T00:00:00Z", "completed_at")

    org_after = validate_success(api.get_organization(org["id"], FINANCE))
    assert org_after["unrestricted_balance_cents"] == -4000
    assert org_after["restricted_balance_cents"] == 5000

    gift_after = validate_success(api.get_contribution(gift["id"], FINANCE))
    assert gift_after["available_cents"] == 5000
    assert gift_after["status"] == "RECEIVED"


def test_redesignation_is_refused_once_the_gift_has_been_drawn_against(api):
    """PRD 3.9: "**Redesignation** is a self-loop on `RECEIVED` and is legal only before
    a single cent has been applied: the contribution's `applied_cents` must still be
    zero. It replaces `designated_animal_id`, `designated_program` and
    `restriction_category`, raises `redesignation_count` by one, recomputes the
    organization's `restricted_balance_cents`, and increments the contribution's
    `version`. Attempting it on a gift that has already been drawn against matches no
    declared transition and yields `ERR_INVALID_STATE`."
    PRD 3.9: "Draws — whether from an adoption fee waterfall or a medical funding
    allocation — raise `applied_cents` and move the axis `RECEIVED → PARTIALLY_APPLIED`
    when some but not all of the gift is consumed, or straight to `FULLY_APPLIED` when
    a single draw consumes it whole; a later draw moves `PARTIALLY_APPLIED →
    FULLY_APPLIED`."

    Design: Corner/state_machines/contribution_redesignate_refused_after_first_application
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    donor = new_person(api, "Gil Marsh", "gil@example.test")
    animal = new_animal(api, org["id"], name="Pixel", species="CAT", size_class="SMALL",
                        weight_lb=9.0, date_of_birth="2024-01-01T00:00:00Z")
    take_into_custody(api, animal["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    gift = new_contribution(api, donor["id"], 5000, "GIFT-9",
                            restriction_category="MEDICAL", designated_program="NONE")
    record = validate_success(
        api.create_medical_record(
            animal["id"],
            medical_record_payload(procedure_type="TREATMENT", expense_category="MEDICAL",
                                   cost_cents=3000, scheduled_at="2026-05-01T00:00:00Z",
                                   funding_required=True),
            VET,
        ),
        201,
    )

    redesignated = validate_success(
        api.redesignate_contribution(
            gift["id"],
            {"designated_program": "MEDICAL_FUND", "restriction_category": "MEDICAL"},
            FINANCE,
        )
    )
    assert redesignated["redesignation_count"] == 1
    assert redesignated["designated_program"] == "MEDICAL_FUND"

    completed = validate_success(api.complete_medical_record(record["id"], VET))
    assert completed["status"] == "COMPLETED"
    assert completed["funded_amount_cents"] == 3000

    validate_error(
        api.redesignate_contribution(
            gift["id"],
            {"designated_program": "TRANSPORT_FUND", "restriction_category": "TRANSPORT"},
            FINANCE,
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )

    after = validate_success(api.get_contribution(gift["id"], FINANCE))
    assert after["redesignation_count"] == 1
    assert after["status"] == "PARTIALLY_APPLIED"
    assert after["available_cents"] == 2000
    assert_contribution_money_conserved(after)


def test_certificate_window_is_selected_by_species_alone(api):
    """PRD 3.5: "The validity window is selected by the animal's species and nothing
    else: a `DOG` gets 30 days, a `CAT` gets 15, and an `OTHER` gets 10. The selected
    figure is stored as `window_days` and `expires_at` is `issued_at` advanced by that
    many 24-hour periods. A certificate starts in `status` `VALID`."

    Design: Corner/calculations/cvi_window_dog_thirty_days_versus_other_ten_days
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    dog = new_animal(api, org["id"], name="Rex", weight_lb=40.0,
                     date_of_birth="2022-01-01T00:00:00Z")
    other = new_animal(api, org["id"], name="Bun", species="OTHER", size_class="SMALL",
                       weight_lb=4.0, date_of_birth="2022-01-01T00:00:00Z")
    take_into_custody(api, dog["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")
    take_into_custody(api, other["id"], "OWNER_SURRENDER", "2026-05-01T00:00:00Z")

    dog_cvi = validate_success(
        api.issue_health_certificate(
            dog["id"], health_certificate_payload("2026-05-01T00:00:00Z", "WA"), VET
        ),
        201,
    )
    other_cvi = validate_success(
        api.issue_health_certificate(
            other["id"], health_certificate_payload("2026-05-01T00:00:00Z", "WA"), VET
        ),
        201,
    )
    assert_health_certificate(dog_cvi)
    assert_health_certificate(other_cvi)

    assert dog_cvi["window_days"] == 30
    assert_same_instant(dog_cvi["expires_at"], "2026-05-31T00:00:00Z", "expires_at")
    assert dog_cvi["status"] == "VALID"
    assert other_cvi["window_days"] == 10
    assert_same_instant(other_cvi["expires_at"], "2026-05-11T00:00:00Z", "expires_at")
    assert other_cvi["status"] == "VALID"

"""Registering the network: organizations, people, animals, litters and money."""
from test_helpers import (
    TEST_USERS,
    assert_animal,
    assert_contribution,
    assert_contribution_money_conserved,
    assert_organization,
    assert_partner_commitment,
    assert_partner_slots_conserved,
    assert_person,
    animal_payload,
    contribution_payload,
    litter_payload,
    new_animal,
    new_litter,
    new_organization,
    new_partner_organization,
    new_person,
    organization_payload,
    partner_commitment_payload,
    person_payload,
    set_clock,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_officer_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
DISPATCH = TEST_USERS["transport_dispatcher_headers"]


def test_organization_registers_with_sac_default_and_zero_ledgers(api):
    """PRD 3.1: "An optional `default_methodology` — `SAC` when omitted — records
    which live-release accounting convention this organization prefers, and is the
    convention used when a live-release report is requested without naming one
    explicitly."
    PRD 3.1: "A newly registered organization starts `UNFROZEN` on its
    `freeze_status` axis with `records_freeze_active` false, `records_freeze_reason`
    null, and all three of its running ledgers — `unrestricted_balance_cents`,
    `restricted_balance_cents` and `open_commitment_slots_total` — at zero."
    PRD 2.4: "`version` begins at 1 when the row is created and increases by exactly
    1 on each mutation of that row, and `updated_at` is refreshed to the clock
    instant of the mutation whenever `version` moves."

    Design: Corner/entities/organization_create_returns_defaults_and_zero_balances
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    resp = api.create_organization(organization_payload(), ADMIN)
    org = validate_success(resp, 201)
    assert_organization(org)

    assert org["default_methodology"] == "SAC"
    assert org["freeze_status"] == "UNFROZEN"
    assert org["records_freeze_active"] is False
    assert org["records_freeze_reason"] is None
    assert org["unrestricted_balance_cents"] == 0
    assert org["restricted_balance_cents"] == 0
    assert org["open_commitment_slots_total"] == 0
    assert org["version"] == 1


def test_person_household_fields_take_their_permissive_defaults(api):
    """PRD 3.1: "`youngest_child_age_years` defaults to 99, which by convention means
    *no resident children at all* rather than a household of centenarian toddlers;
    `resident_cat_count` and `resident_dog_count` default to 0; `housing_type`
    defaults to `HOUSE`; `has_fenced_yard` defaults to false; `hardship_certified`
    defaults to false and is the precondition for the reclaim hardship waiver
    described in §3.2; and `driver_license_number` defaults to null."
    PRD 3.1: "Finally, every new person starts with `reclaim_history_count` at 0 — a
    derived counter, described in §3.2, that drives the repeat-offense multiplier."

    Design: Corner/entities/person_household_defaults_applied_when_omitted
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    resp = api.create_person(person_payload("Nil Default", "nil@example.test"), ADMIN)
    person = validate_success(resp, 201)
    assert_person(person)

    assert person["youngest_child_age_years"] == 99
    assert person["resident_cat_count"] == 0
    assert person["resident_dog_count"] == 0
    assert person["housing_type"] == "HOUSE"
    assert person["has_fenced_yard"] is False
    assert person["hardship_certified"] is False
    assert person["driver_license_number"] is None
    assert person["reclaim_history_count"] == 0


def test_animal_identifiable_is_derived_from_the_microchip(api):
    """PRD 3.1: "Registration derives `identifiable` as true exactly when
    `microchip_id` is non-null, and where a `litter_id` was supplied it raises that
    litter's `member_count` by one."
    PRD 3.1: "Animals are registered **before** intake, and start in
    `lifecycle_status` `PRE_INTAKE`."
    PRD 3.1: "`length_of_stay_days` is the whole elapsed days between the intake
    instant of the animal's currently open custody episode and the logical clock,
    rounded down; when `current_intake_record_id` is null it is 0 rather than absent."

    Design: Corner/entities/animal_identifiable_computed_from_microchip_id
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)

    chipped = validate_success(
        api.create_animal(
            animal_payload(
                org["id"], name="Chipped", size_class="SMALL", weight_lb=12.0,
                date_of_birth="2024-01-01T00:00:00Z",
                microchip_id="985141000123456",
            ),
            INTAKE,
        ),
        201,
    )
    plain = validate_success(
        api.create_animal(
            animal_payload(
                org["id"], name="Plain", size_class="SMALL", weight_lb=12.0,
                date_of_birth="2024-01-01T00:00:00Z",
            ),
            INTAKE,
        ),
        201,
    )

    assert_animal(chipped)
    assert_animal(plain)
    assert chipped["identifiable"] is True
    assert plain["identifiable"] is False
    assert chipped["lifecycle_status"] == "PRE_INTAKE"
    assert plain["lifecycle_status"] == "PRE_INTAKE"
    assert chipped["length_of_stay_days"] == 0
    assert chipped["current_intake_record_id"] is None


def test_animal_age_weeks_and_months_floor_fixed_day_counts(api):
    """PRD 3.1: "`age_weeks` and `age_months` are both computed from the whole elapsed
    days between `date_of_birth` and the logical clock, divided by 7 and 30
    respectively and rounded down, exactly as §2.8 describes."
    PRD 2.8: "No derivation in this system uses calendar months or leap-year
    arithmetic, so a month is always exactly 30 days and a year is never a special
    case."

    2026-04-01 to 2026-06-01 is 30 + 31 = 61 whole days, so age_weeks is
    61 // 7 == 8 and age_months is 61 // 30 == 2.

    Design: Corner/entities/animal_age_weeks_and_months_derived_from_whole_days
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    animal = new_animal(
        api, org["id"], name="Sprout", species="CAT", size_class="SMALL",
        weight_lb=3.0, date_of_birth="2026-04-01T00:00:00Z",
    )
    set_clock(api, "2026-06-01T00:00:00Z")

    read = validate_success(api.get_animal(animal["id"], ADMIN))
    assert read["age_weeks"] == 8, f"expected 61 // 7 == 8, got {read['age_weeks']}"
    assert read["age_months"] == 2, f"expected 61 // 30 == 2, got {read['age_months']}"


def test_litter_starts_grouped_and_counts_its_members(api):
    """PRD 3.1: "A new litter carries a human `label`, starts with `transport_basis`
    `GROUPED` and `member_count` 0, and has `split_approved_at` null."
    PRD 3.1: "Registration derives `identifiable` as true exactly when `microchip_id`
    is non-null, and where a `litter_id` was supplied it raises that litter's
    `member_count` by one."

    Design: Corner/entities/litter_member_count_tracks_animals_assigned_to_it
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    litter = validate_success(api.create_litter(litter_payload("Birch litter"), INTAKE), 201)

    assert litter["member_count"] == 0
    assert litter["transport_basis"] == "GROUPED"
    assert litter["split_approved_at"] is None

    for name in ("B1", "B2", "B3"):
        new_animal(
            api, org["id"], name=name, size_class="SMALL", weight_lb=5.0,
            date_of_birth="2026-04-01T00:00:00Z", litter_id=litter["id"],
        )

    read = validate_success(api.get_litter(litter["id"], ADMIN))
    assert read["member_count"] == 3


def test_animal_list_filtered_by_litter_returns_only_that_litter(api):
    """PRD 3.1: "Animals may be listed with any combination of `species`,
    `lifecycle_status`, `litter_id`, `current_organization_id`,
    `current_foster_home_id` and `current_intake_record_id` filters."
    PRD 2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of rows matching
    the filters before the limit and offset are applied, and `has_more` is true
    exactly when rows remain beyond the current page."

    Design: Corner/entities/animal_list_filtered_by_litter_id_returns_only_members
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    litter = new_litter(api, "Birch litter")
    b1 = new_animal(api, org["id"], name="B1", size_class="SMALL", weight_lb=5.0,
                    date_of_birth="2026-04-01T00:00:00Z", litter_id=litter["id"])
    b2 = new_animal(api, org["id"], name="B2", size_class="SMALL", weight_lb=5.0,
                    date_of_birth="2026-04-01T00:00:00Z", litter_id=litter["id"])
    loner = new_animal(api, org["id"], name="Loner", species="CAT", size_class="SMALL",
                       weight_lb=8.0, date_of_birth="2024-01-01T00:00:00Z")

    resp = api.list_animals(ADMIN, {"litter_id": litter["id"], "limit": 10, "offset": 0})
    rows, meta = validate_paginated(resp)

    returned = {row["id"] for row in rows}
    assert returned == {b1["id"], b2["id"]}, f"expected only the littermates, got {returned}"
    assert loner["id"] not in returned
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_contribution_opens_received_and_raises_the_restricted_balance(api):
    """PRD 3.9: "A new contribution opens in `status` `RECEIVED` with `applied_cents`
    and `released_cents` at zero, `available_cents` equal to `amount_cents`, and
    `redesignation_count` at zero. Recording it raises the organization's
    `unrestricted_balance_cents` when the category is `UNRESTRICTED` and its
    `restricted_balance_cents` otherwise."

    Design: Corner/entities/contribution_available_cents_and_status_on_create
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    donor = new_person(api, "Gil Marsh", "gil@example.test")

    contribution = validate_success(
        api.create_contribution(
            contribution_payload(
                donor["id"], 5000, "GIFT-1",
                restriction_category="MEDICAL", designated_program="NONE",
            ),
            FINANCE,
        ),
        201,
    )
    assert_contribution(contribution)

    assert contribution["applied_cents"] == 0
    assert contribution["released_cents"] == 0
    assert contribution["available_cents"] == 5000
    assert contribution["status"] == "RECEIVED"
    assert contribution["redesignation_count"] == 0
    assert_contribution_money_conserved(contribution)

    org_read = validate_success(api.get_organization(org["id"], FINANCE))
    assert org_read["unrestricted_balance_cents"] == 0
    assert org_read["restricted_balance_cents"] == 5000


def test_partner_commitment_opens_with_every_slot_free(api):
    """PRD 3.7: "The commitment opens in `status` `OPEN` with `slots_drawn` 0,
    `slots_released` 0 and `slots_open` equal to `slots_total`, and registering it
    raises that organization's `open_commitment_slots_total`."
    PRD 2.10: "**Partner slots.** For every partner commitment, `slots_total` equals
    `slots_drawn` plus `slots_released` plus `slots_open`."

    Design: Corner/entities/partner_commitment_slots_open_initialised_to_slots_total
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    partner = new_partner_organization(api)

    commitment = validate_success(
        api.create_partner_commitment(
            partner_commitment_payload(
                partner["id"], species="CAT", slots_total=5,
                expires_at="2026-07-01T00:00:00Z",
            ),
            DISPATCH,
        ),
        201,
    )
    assert_partner_commitment(commitment)

    assert commitment["slots_drawn"] == 0
    assert commitment["slots_released"] == 0
    assert commitment["slots_open"] == 5
    assert commitment["slots_total"] == 5
    assert commitment["status"] == "OPEN"
    assert_partner_slots_conserved(commitment)

    org_read = validate_success(api.get_organization(partner["id"], ADMIN))
    assert org_read["open_commitment_slots_total"] == 5

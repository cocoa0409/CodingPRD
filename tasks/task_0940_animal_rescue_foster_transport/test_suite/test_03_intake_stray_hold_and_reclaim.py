"""Custody episodes: the stray-hold clock and the owner-reclaim charge."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_intake_record,
    assert_same_instant,
    new_animal,
    new_organization,
    new_person,
    set_clock,
    take_into_custody,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_officer_headers"]


# --------------------------------------------------------------------------
# The monotone stray-hold latch
# --------------------------------------------------------------------------
def test_stray_hold_latches_at_the_inclusive_boundary_and_refuses_extension(api):
    """PRD 3.2: "A `STRAY` carries **seven** days when the animal was identifiable at
    the moment of intake and only **three** when it was not — the microchipped
    animal's owner gets four extra days to find them."
    PRD 3.2: "Any read or write that touches the episode while the logical clock has
    reached or passed `hold_expires_at` latches it to `HOLD_EXPIRED` — the boundary is
    inclusive, so a clock standing exactly at `hold_expires_at` yields `HOLD_EXPIRED`."
    PRD 3.2: "This latch is what makes the extension in §3.1 refusable — a stray-hold
    extension may only be applied while the episode is still `HOLD_ACTIVE`, is only
    meaningful on a `STRAY` episode whose `identifiable_at_intake` is still false, and
    once the latch has fired the extension is refused with `ERR_HOLD_ALREADY_EXPIRED`
    and the hold clock is not moved at all."

    Design: Corner/state_machines/stray_hold_monotone_latch_refuses_later_extension
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    animal = new_animal(api, org["id"], name="Wanderer", weight_lb=30.0,
                        date_of_birth="2023-01-01T00:00:00Z")
    episode = validate_success(
        api.create_intake_record(
            animal["id"],
            {"intake_type": "STRAY", "intake_datetime": "2026-05-01T00:00:00Z",
             "impound_billing_basis": "CALENDAR_DAY"},
            INTAKE,
        ),
        201,
    )
    assert_intake_record(episode)
    assert episode["hold_days"] == 3
    assert_same_instant(episode["hold_expires_at"], "2026-05-04T00:00:00Z", "hold_expires_at")

    set_clock(api, "2026-05-04T00:00:00Z")
    latched = validate_success(api.get_intake_record(episode["id"], INTAKE))
    assert latched["hold_status"] == "HOLD_EXPIRED"

    validate_error(
        api.record_identification(
            animal["id"], {"microchip_id": "985141000999888", "extend_stray_hold": True}, INTAKE
        ),
        ApiErrorId.ERR_HOLD_ALREADY_EXPIRED.value,
        409,
    )

    after = validate_success(api.get_intake_record(episode["id"], INTAKE))
    assert after["hold_status"] == "HOLD_EXPIRED"
    assert after["hold_days"] == 3
    assert_same_instant(after["hold_expires_at"], "2026-05-04T00:00:00Z", "hold_expires_at")


def test_stray_hold_extension_while_active_moves_expiry_to_seven_days(api):
    """PRD 3.2: "Whether the animal was identifiable is captured as
    `identifiable_at_intake`, a snapshot of the animal's `identifiable` flag taken as
    the episode is written, and it does not track later changes to the animal on its
    own."
    PRD 3.2: "When it is accepted, it flips `identifiable_at_intake` to true,
    recomputes `hold_days` to the seven-day identifiable figure, moves
    `hold_expires_at` correspondingly later, and increments the episode's `version` by
    one."
    PRD 3.1: "It always sets the animal's `microchip_id` and marks `identifiable`
    true, and it always increments the animal's `version` by one."

    The hold restarts from `intake_datetime`: 2026-05-01 advanced by seven 24-hour
    periods is 2026-05-08.

    Design: Corner/state_machines/stray_hold_extension_while_active_moves_expiry_to_seven_days
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    org = new_organization(api)
    animal = new_animal(api, org["id"], name="Wanderer", weight_lb=30.0,
                        date_of_birth="2023-01-01T00:00:00Z")
    episode = validate_success(
        api.create_intake_record(
            animal["id"],
            {"intake_type": "STRAY", "intake_datetime": "2026-05-01T00:00:00Z"},
            INTAKE,
        ),
        201,
    )
    assert episode["hold_days"] == 3
    assert_same_instant(episode["hold_expires_at"], "2026-05-04T00:00:00Z", "hold_expires_at")
    assert episode["identifiable_at_intake"] is False

    set_clock(api, "2026-05-02T00:00:00Z")
    updated_animal = validate_success(
        api.record_identification(
            animal["id"], {"microchip_id": "985141000999888", "extend_stray_hold": True}, INTAKE
        )
    )
    assert updated_animal["identifiable"] is True
    assert updated_animal["microchip_id"] == "985141000999888"

    after = validate_success(api.get_intake_record(episode["id"], INTAKE))
    assert after["hold_days"] == 7
    assert_same_instant(after["hold_expires_at"], "2026-05-08T00:00:00Z", "hold_expires_at")
    assert after["hold_status"] == "HOLD_ACTIVE"
    assert after["identifiable_at_intake"] is True


# --------------------------------------------------------------------------
# The four-step reclaim charge
# --------------------------------------------------------------------------
def test_hardship_waiver_applies_when_the_pre_waiver_total_reaches_the_threshold(api):
    """PRD 3.2: "Under `CALENDAR_DAY`, the count is the number of distinct UTC calendar
    dates touched by the stay, counting both the date of `intake_datetime` and the date
    of the current clock instant — so a stay that begins in the morning of one date and
    ends in the afternoon six dates later bills six days."
    PRD 3.2: "The first three billable days are charged at 1500 cents each. Days four
    through seven — that is, up to four further days — are charged at 2500 cents each.
    Every day beyond the seventh is charged at 4000 cents. The sum is
    `impound_subtotal_cents`."
    PRD 3.2: "If that pre-waiver total is **at least** 20000 cents and the reclaiming
    person's `hardship_certified` flag is true, a flat waiver of 2000 cents applies and
    is stored as `hardship_waiver_cents`; otherwise `hardship_waiver_cents` is 0."

    2026-05-10 through 2026-05-18 touches 9 distinct dates, so the subtotal is
    3*1500 + 4*2500 + 2*4000 = 22500; at multiplier 1.0 the pre-waiver total is
    22500 + 4500 = 27000, the 2000-cent waiver applies and the total is 25000.

    Design: Difficulty/combinatorial_formula/reclaim_hardship_waiver_keyed_on_pre_waiver_total_mode_c
    """
    set_clock(api, "2026-05-10T00:00:00Z")
    org = new_organization(api)
    owner = new_person(api, "Pat Ling", "pat@example.test", hardship_certified=True)
    animal = new_animal(api, org["id"], name="Scout", weight_lb=40.0,
                        date_of_birth="2022-01-01T00:00:00Z")
    episode = take_into_custody(
        api, animal["id"], "STRAY", "2026-05-10T09:00:00Z",
        source_person_id=owner["id"], impound_billing_basis="CALENDAR_DAY",
    )

    set_clock(api, "2026-05-18T14:00:00Z")
    outcome = validate_success(
        api.reclaim(episode["id"], {"reclaiming_person_id": owner["id"]}, INTAKE), 201
    )
    assert outcome["outcome_type"] == "RETURN_TO_OWNER"

    charged = validate_success(api.get_intake_record(episode["id"], INTAKE))
    assert charged["impound_billable_days"] == 9
    assert charged["impound_subtotal_cents"] == 22500
    assert charged["repeat_offense_multiplier"] == 1.0
    assert charged["reclaim_base_fee_cents"] == 4500
    assert charged["hardship_waiver_cents"] == 2000
    assert charged["reclaim_total_cents"] == 25000


def test_hardship_waiver_is_withheld_when_the_pre_waiver_total_is_below_the_threshold(api):
    """PRD 3.2: "Fourth, the **hardship waiver** is tested against the pre-waiver
    total."
    PRD 3.2: "If that pre-waiver total is **at least** 20000 cents and the reclaiming
    person's `hardship_certified` flag is true, a flat waiver of 2000 cents applies and
    is stored as `hardship_waiver_cents`; otherwise `hardship_waiver_cents` is 0."
    PRD 3.2: "The order here matters and is not negotiable: the waiver test reads the
    pre-waiver total, never the final `reclaim_total_cents`, which would otherwise be
    circular."

    An equally hardship-certified owner whose stay touches only 3 dates has a subtotal
    of 3*1500 = 4500 and a pre-waiver total of 4500 + 4500 = 9000, which is under the
    20000-cent threshold, so no waiver applies and the total stays 9000.

    Design: Difficulty/combinatorial_formula/reclaim_hardship_waiver_keyed_on_pre_waiver_total_mode_c
    """
    set_clock(api, "2026-05-16T00:00:00Z")
    org = new_organization(api)
    owner = new_person(api, "Quinn Ade", "quinn@example.test", hardship_certified=True)
    animal = new_animal(api, org["id"], name="Tilly", weight_lb=41.0,
                        date_of_birth="2022-01-01T00:00:00Z")
    episode = take_into_custody(
        api, animal["id"], "STRAY", "2026-05-16T09:00:00Z",
        source_person_id=owner["id"], impound_billing_basis="CALENDAR_DAY",
    )

    set_clock(api, "2026-05-18T14:00:00Z")
    outcome = validate_success(
        api.reclaim(episode["id"], {"reclaiming_person_id": owner["id"]}, INTAKE), 201
    )
    assert outcome["outcome_type"] == "RETURN_TO_OWNER"

    charged = validate_success(api.get_intake_record(episode["id"], INTAKE))
    assert charged["impound_billable_days"] == 3
    assert charged["impound_subtotal_cents"] == 4500
    assert charged["hardship_waiver_cents"] == 0
    assert charged["reclaim_total_cents"] == 9000


def test_calendar_day_and_overnight_bill_the_same_stay_differently(api):
    """PRD 3.2: "Under `CALENDAR_DAY`, the count is the number of distinct UTC calendar
    dates touched by the stay, counting both the date of `intake_datetime` and the date
    of the current clock instant — so a stay that begins in the morning of one date and
    ends in the afternoon six dates later bills six days."
    PRD 3.2: "Under `OVERNIGHT`, the count is the whole 24-hour periods elapsed between
    `intake_datetime` and the clock, rounded down, with a floor of one day — the same
    stay bills five."

    For 2026-05-10T09:00 to 2026-05-15T14:00: CALENDAR_DAY counts 6 dates for
    3*1500 + 3*2500 = 12000 and a 16500-cent total; OVERNIGHT counts 5 whole periods
    for 3*1500 + 2*2500 = 9500 and a 14000-cent total.

    Design: Corner/calculations/impound_calendar_day_versus_overnight_billable_days
    """
    set_clock(api, "2026-05-10T00:00:00Z")
    org = new_organization(api)
    owner_a = new_person(api, "Owner A", "oa@example.test", hardship_certified=False)
    owner_b = new_person(api, "Owner B", "ob@example.test", hardship_certified=False)
    animal_a = new_animal(api, org["id"], name="A", weight_lb=30.0,
                          date_of_birth="2022-01-01T00:00:00Z")
    animal_b = new_animal(api, org["id"], name="B", weight_lb=30.0,
                          date_of_birth="2022-01-01T00:00:00Z")
    episode_a = take_into_custody(api, animal_a["id"], "STRAY", "2026-05-10T09:00:00Z",
                                  source_person_id=owner_a["id"],
                                  impound_billing_basis="CALENDAR_DAY")
    episode_b = take_into_custody(api, animal_b["id"], "STRAY", "2026-05-10T09:00:00Z",
                                  source_person_id=owner_b["id"],
                                  impound_billing_basis="OVERNIGHT")

    set_clock(api, "2026-05-15T14:00:00Z")
    validate_success(api.reclaim(episode_a["id"], {"reclaiming_person_id": owner_a["id"]},
                                 INTAKE), 201)
    validate_success(api.reclaim(episode_b["id"], {"reclaiming_person_id": owner_b["id"]},
                                 INTAKE), 201)

    charged_a = validate_success(api.get_intake_record(episode_a["id"], INTAKE))
    charged_b = validate_success(api.get_intake_record(episode_b["id"], INTAKE))

    assert charged_a["impound_billable_days"] == 6
    assert charged_a["impound_subtotal_cents"] == 12000
    assert charged_a["reclaim_total_cents"] == 16500
    assert charged_a["hardship_waiver_cents"] == 0
    assert charged_b["impound_billable_days"] == 5
    assert charged_b["impound_subtotal_cents"] == 9500
    assert charged_b["reclaim_total_cents"] == 14000


def test_repeat_offense_multiplier_reads_the_history_before_the_current_reclaim(api):
    """PRD 3.2: "The count consulted is that person's `reclaim_history_count`, being the
    number of unreversed `RETURN_TO_OWNER` outcomes already naming them as
    counterparty, and it is read **before** the current reclaim is written — so a
    first-time owner sees zero and pays the base multiplier of 1.0, a second-time owner
    sees one and pays 1.5, and an owner with two or more prior reclaims pays 2.0."
    PRD 3.2: "The multiplier is applied to `impound_subtotal_cents` alone — never to
    the base fee — and that product is rounded half up to whole cents."

    The first reclaim bills 6 dates for 12000 and totals 12000 + 4500 = 16500; the
    second bills 4 dates for 3*1500 + 1*2500 = 7000, and at multiplier 1.5 totals
    10500 + 4500 = 15000.

    Design: Corner/calculations/repeat_offense_multiplier_applies_on_second_reclaim_only
    """
    set_clock(api, "2026-05-10T00:00:00Z")
    org = new_organization(api)
    owner = new_person(api, "Repeat Owner", "repeat@example.test", hardship_certified=False)
    animal_x = new_animal(api, org["id"], name="X", weight_lb=30.0,
                          date_of_birth="2022-01-01T00:00:00Z")
    animal_y = new_animal(api, org["id"], name="Y", weight_lb=30.0,
                          date_of_birth="2022-01-01T00:00:00Z")
    episode_x = take_into_custody(api, animal_x["id"], "STRAY", "2026-05-10T09:00:00Z",
                                  source_person_id=owner["id"],
                                  impound_billing_basis="CALENDAR_DAY")
    set_clock(api, "2026-05-12T00:00:00Z")
    episode_y = take_into_custody(api, animal_y["id"], "STRAY", "2026-05-12T09:00:00Z",
                                  source_person_id=owner["id"],
                                  impound_billing_basis="CALENDAR_DAY")

    set_clock(api, "2026-05-15T14:00:00Z")
    validate_success(api.reclaim(episode_x["id"], {"reclaiming_person_id": owner["id"]},
                                 INTAKE), 201)
    validate_success(api.reclaim(episode_y["id"], {"reclaiming_person_id": owner["id"]},
                                 INTAKE), 201)

    charged_x = validate_success(api.get_intake_record(episode_x["id"], INTAKE))
    charged_y = validate_success(api.get_intake_record(episode_y["id"], INTAKE))
    assert charged_x["repeat_offense_multiplier"] == 1.0
    assert charged_x["reclaim_total_cents"] == 16500
    assert charged_y["impound_billable_days"] == 4
    assert charged_y["impound_subtotal_cents"] == 7000
    assert charged_y["repeat_offense_multiplier"] == 1.5
    assert charged_y["reclaim_total_cents"] == 15000

    owner_read = validate_success(api.get_person(owner["id"], ADMIN))
    assert owner_read["reclaim_history_count"] == 2

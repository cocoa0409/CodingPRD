"""Derived arithmetic: checklist replay, window sizing, match scoring, pay and stock."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_turnover_payload,
    create_booking_payload,
    create_cleaner_payload,
    create_property_payload,
    create_quality_audit_payload,
    create_supply_line_payload,
    create_turnover_payload,
    fixtures as fx,
    make_cleaner_headers,
    replenish_payload,
    restock_entry,
    review_task_payload,
    same_instant,
    submit_task_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
REVIEWER = TEST_USERS["coordinator_reviewer_headers"]
AUDITOR = TEST_USERS["quality_auditor_headers"]


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def three_bedroom_house_ready_to_start(api):
    """A THREE_BR_PLUS unit whose accepted clean is waiting to be begun."""
    fx.reset_clock(api)
    p4 = validate_success(api.create_property(create_property_payload(
        code="AUS-104", name="Travis Heights House", zone_code="ZONE_A",
        size_tier="THREE_BR_PLUS", owner_contact_email="owner4@example.com",
        bedroom_count=3, bathroom_count=3, bed_count=4), ADMIN), 201)
    cc = validate_success(api.create_cleaner(create_cleaner_payload(
        name="Cleaner C", home_zone_code="ZONE_A", skill_level=4,
        max_daily_turnovers=3, initial_quality_score=92.00), ADMIN), 201)
    b_out = validate_success(api.create_booking(create_booking_payload(
        p4["id"], external_ref="OUT-4", guest_name="Guest Out 4"),
        COORDINATOR), 201)
    b_in = validate_success(api.create_booking(create_booking_payload(
        p4["id"], external_ref="IN-4", guest_name="Guest In 4",
        checkin_at="2026-08-08T21:00:00Z",
        checkout_at="2026-08-11T16:00:00Z"), COORDINATOR), 201)
    t4 = validate_success(api.create_turnover(create_turnover_payload(
        b_out["id"], b_in["id"]), COORDINATOR), 201)
    a4 = validate_success(api.assign_turnover(
        t4["id"], assign_turnover_payload(t4["version"], cc["id"]),
        COORDINATOR), 201)
    cleaner_headers = make_cleaner_headers(cc["id"])
    validate_success(api.accept_assignment(a4["id"], {}, cleaner_headers))
    fx.reset_clock(api, fx.CHECKOUT_INSTANT)
    validate_success(api.checkout_booking(b_out["id"], {}, COORDINATOR))
    return {"p4": p4, "t4": t4, "cleaner_headers": cleaner_headers}


@pytest.fixture
def pet_and_petless_twins(api):
    """Two identical TWO_BR units whose departing stays differ only in pet_stay."""
    fx.reset_clock(api)
    plain = fx.seed_property(api)
    pet = fx.seed_property(
        api, code="AUS-121", name="Barton Loft Pet Twin",
        owner_contact_email="owner21@example.com")
    plain_out = fx.seed_booking(
        api, plain["id"], external_ref="OUT-1", guest_name="Guest No Pet")
    plain_in = fx.seed_booking(
        api, plain["id"], external_ref="IN-1", guest_name="Guest In",
        checkin_at="2026-08-08T21:00:00Z", checkout_at="2026-08-11T16:00:00Z")
    pet_out = fx.seed_booking(
        api, pet["id"], external_ref="OUT-21", guest_name="Guest With Pet",
        party_size=2, pet_stay=True)
    pet_in = fx.seed_booking(
        api, pet["id"], external_ref="IN-21", guest_name="Guest In Twin",
        checkin_at="2026-08-08T21:00:00Z", checkout_at="2026-08-11T16:00:00Z")
    return {"plain_out": plain_out, "plain_in": plain_in,
            "pet_out": pet_out, "pet_in": pet_in}


@pytest.fixture
def tied_candidate_pool(api):
    """A ONE_BR unit and two ZONE_A cleaners who tie at 0.8500 by opposite routes."""
    fx.reset_clock(api)
    p5 = validate_success(api.create_property(create_property_payload(
        code="AUS-105", name="Rainey Studio One", zone_code="ZONE_A",
        size_tier="ONE_BR", owner_contact_email="owner5@example.com",
        bedroom_count=1, bathroom_count=1, bed_count=1), ADMIN), 201)
    c_qual = validate_success(api.create_cleaner(create_cleaner_payload(
        name="Cleaner Q", home_zone_code="ZONE_A", skill_level=2,
        max_daily_turnovers=3, initial_quality_score=90.00), ADMIN), 201)
    c_skill = validate_success(api.create_cleaner(create_cleaner_payload(
        name="Cleaner S", home_zone_code="ZONE_A", skill_level=4,
        max_daily_turnovers=3, initial_quality_score=70.00), ADMIN), 201)
    b_out = validate_success(api.create_booking(create_booking_payload(
        p5["id"], external_ref="OUT-5", guest_name="Guest Out 5"),
        COORDINATOR), 201)
    b_in = validate_success(api.create_booking(create_booking_payload(
        p5["id"], external_ref="IN-5", guest_name="Guest In 5",
        checkin_at="2026-08-08T21:00:00Z",
        checkout_at="2026-08-11T16:00:00Z"), COORDINATOR), 201)
    t5 = validate_success(api.create_turnover(create_turnover_payload(
        b_out["id"], b_in["id"]), COORDINATOR), 201)
    return {"c_qual": c_qual, "c_skill": c_skill, "t5": t5}


@pytest.fixture
def half_cent_scoring_world(api):
    """A min_skill_level 2 unit and a skill-3 cleaner scoring exactly 0.83825."""
    fx.reset_clock(api)
    p6 = validate_success(api.create_property(create_property_payload(
        code="AUS-106", name="Mueller One Bed", zone_code="ZONE_A",
        size_tier="ONE_BR", owner_contact_email="owner6@example.com",
        bedroom_count=1, bathroom_count=1, bed_count=1,
        min_skill_level=2), ADMIN), 201)
    cp = validate_success(api.create_cleaner(create_cleaner_payload(
        name="Cleaner P", home_zone_code="ZONE_A", skill_level=3,
        max_daily_turnovers=3, initial_quality_score=87.65), ADMIN), 201)
    b_out = validate_success(api.create_booking(create_booking_payload(
        p6["id"], external_ref="OUT-6", guest_name="Guest Out 6"),
        COORDINATOR), 201)
    b_in = validate_success(api.create_booking(create_booking_payload(
        p6["id"], external_ref="IN-6", guest_name="Guest In 6",
        checkin_at="2026-08-08T21:00:00Z",
        checkout_at="2026-08-11T16:00:00Z"), COORDINATOR), 201)
    t6 = validate_success(api.create_turnover(create_turnover_payload(
        b_out["id"], b_in["id"]), COORDINATOR), 201)
    return {"cp": cp, "t6": t6}


@pytest.fixture
def rejection_ladder_world(api):
    """A started canonical clean plus the provisional preview taken on acceptance."""
    world = fx.build_world(api, supply="pair")
    fx.offer_turnover(api, world)
    fx.accept_offer(api, world)
    world["preview_on_accept"] = validate_success(
        api.get_pay_preview(world["t1"]["id"], COORDINATOR))
    fx.start_clean(api, world)
    return world


@pytest.fixture
def soap_line_property(api):
    """A ONE_BR unit in ZONE_B with no stock configured yet."""
    fx.reset_clock(api)
    return validate_success(api.create_property(create_property_payload(
        code="AUS-108", name="Crestview Bungalow", zone_code="ZONE_B",
        size_tier="ONE_BR", owner_contact_email="owner8@example.com",
        bedroom_count=1, bathroom_count=1, bed_count=1), ADMIN), 201)


@pytest.fixture
def single_slot_cleaner_world(api):
    """Two same-day turns created back to front against a one-turn-a-day cleaner."""
    fx.reset_clock(api)
    pa = validate_success(api.create_property(create_property_payload(
        code="AUS-111", name="Zilker A", zone_code="ZONE_A",
        size_tier="ONE_BR", owner_contact_email="owner11@example.com",
        bedroom_count=1, bathroom_count=1, bed_count=1), ADMIN), 201)
    pb = validate_success(api.create_property(create_property_payload(
        code="AUS-112", name="Zilker B", zone_code="ZONE_A",
        size_tier="ONE_BR", owner_contact_email="owner12@example.com",
        bedroom_count=1, bathroom_count=1, bed_count=1), ADMIN), 201)
    cd = validate_success(api.create_cleaner(create_cleaner_payload(
        name="Cleaner D", home_zone_code="ZONE_A", skill_level=4,
        max_daily_turnovers=1, initial_quality_score=92.00), ADMIN), 201)
    bb_out = validate_success(api.create_booking(create_booking_payload(
        pb["id"], external_ref="OUT-B", guest_name="Guest Out B",
        checkin_at="2026-08-06T21:00:00Z",
        checkout_at="2026-08-08T20:45:00Z"), COORDINATOR), 201)
    bb_in = validate_success(api.create_booking(create_booking_payload(
        pb["id"], external_ref="IN-B", guest_name="Guest In B",
        checkin_at="2026-08-09T00:00:00Z",
        checkout_at="2026-08-12T16:00:00Z"), COORDINATOR), 201)
    tb = validate_success(api.create_turnover(create_turnover_payload(
        bb_out["id"], bb_in["id"]), COORDINATOR), 201)
    ba_out = validate_success(api.create_booking(create_booking_payload(
        pa["id"], external_ref="OUT-A", guest_name="Guest Out A"),
        COORDINATOR), 201)
    ba_in = validate_success(api.create_booking(create_booking_payload(
        pa["id"], external_ref="IN-A", guest_name="Guest In A",
        checkin_at="2026-08-08T21:00:00Z",
        checkout_at="2026-08-11T16:00:00Z"), COORDINATOR), 201)
    ta = validate_success(api.create_turnover(create_turnover_payload(
        ba_out["id"], ba_in["id"]), COORDINATOR), 201)
    return {"cd": cd, "ta": ta, "tb": tb,
            "cleaner_headers": make_cleaner_headers(cd["id"])}


# ─── corner_calc_checklist_template_replay_adds_patio_staging_for_three_br_plus ──

def test_01_a_three_bedroom_unit_earns_a_fifth_patio_row(
        api, three_bedroom_house_ready_to_start):
    """Five rows in template order, only STRIP_LINENS needing no photograph.

    PRD §3.5: "A fifth row, `PATIO_STAGING` at sequence 50, in `STAGING` and
    requiring a photograph, applies only to a `THREE_BR_PLUS` unit." PRD §3.5:
    "Each generated row copies its `task_code`, `category`, `sequence_no` and
    `requires_photo` from the template and lands in `status` `PENDING`." PRD
    §3.5: "The turnover's `checklist_task_count` is then set to the number of
    rows appended — four for a `STUDIO`, a `ONE_BR` or a `TWO_BR`, and five for
    a `THREE_BR_PLUS`."

    Design: Corner/calculations/corner_calc_checklist_template_replay_adds_patio_staging_for_three_br_plus
    """
    world = three_bedroom_house_ready_to_start
    t4 = world["t4"]
    assert t4["required_minutes"] == 268, (
        f"a THREE_BR_PLUS with 3 baths and 4 beds requires 200 + 36 + 32, "
        f"got {t4['required_minutes']}")
    assert t4["window_minutes"] == 270 and t4["slack_minutes"] == 2, (
        f"270 minutes against 268 leaves 2, got {t4['window_minutes']} / "
        f"{t4['slack_minutes']}")
    assert t4["is_tight"] is True, (
        f"2 minutes of slack is far below 45, got {t4['is_tight']}")
    assert t4["turn_type"] == "SAME_DAY", (
        f"departure and arrival share the local date, got {t4['turn_type']}")

    started = validate_success(
        api.start_turnover(t4["id"], {}, world["cleaner_headers"]))
    assert started["status"] == "IN_PROGRESS", (
        f"the clean must be underway, got {started['status']}")
    assert started["checklist_task_count"] == 5, (
        f"a THREE_BR_PLUS replay appends five rows, "
        f"got {started['checklist_task_count']}")

    rows = validate_success(api.list_turnover_checklist_tasks(
        t4["id"], world["cleaner_headers"]))
    assert [r["task_code"] for r in rows] == [
        "STRIP_LINENS", "BATHROOM_DEEP_CLEAN", "BED_STAGING",
        "SUPPLY_RESTOCK", "PATIO_STAGING"], (
        f"the rows must arrive in ascending template order, "
        f"got {[r['task_code'] for r in rows]}")
    assert rows[0]["sequence_no"] == 10 and rows[4]["sequence_no"] == 50, (
        f"the template sequence numbers must be copied, got "
        f"{rows[0]['sequence_no']} / {rows[4]['sequence_no']}")
    assert rows[4]["category"] == "STAGING", (
        f"the patio row belongs to STAGING, got {rows[4]['category']}")
    assert rows[0]["requires_photo"] is False, (
        f"STRIP_LINENS is the only row needing no photograph, "
        f"got {rows[0]['requires_photo']}")
    assert rows[4]["requires_photo"] is True, (
        f"the patio row requires a photograph, got {rows[4]['requires_photo']}")
    assert rows[0]["status"] == "PENDING", (
        f"every generated row lands PENDING, got {rows[0]['status']}")

    staging = validate_success(api.list_turnover_checklist_tasks(
        t4["id"], COORDINATOR, {"category": "STAGING"}))
    assert len(staging) == 2, (
        f"BED_STAGING and PATIO_STAGING are the two staging rows, "
        f"got {len(staging)}")


# ─── corner_calc_pet_stay_multiplier_is_applied_before_the_ceiling ────────

def test_02_a_pet_in_residence_inflates_the_requirement_before_the_ceiling(
        api, pet_and_petless_twins):
    """198 becomes ceil(237.6) equals 238, flipping is_tight on the same window.

    PRD §3.3: "When the departing stay's `pet_stay` flag is true, multiply that
    running subtotal by 1.20, adding a fifth again to every minute of the clean.
    Take the ceiling of the result so that a fractional minute always rounds up
    to the next whole minute, and then `required_minutes` is the larger of that
    ceiling and the unit's contractual `min_clean_minutes` floor." PRD §3.3:
    "`is_tight` is true whenever `slack_minutes` is strictly below 45 minutes —
    note that a comfortable window is not merely one that fits, but one that
    fits with three quarters of an hour to spare."

    Design: Corner/calculations/corner_calc_pet_stay_multiplier_is_applied_before_the_ceiling
    """
    world = pet_and_petless_twins
    assert world["plain_out"]["pet_stay"] is False, (
        f"the flag defaults to false, got {world['plain_out']['pet_stay']}")
    assert world["pet_out"]["pet_stay"] is True, (
        f"the pet stay must carry the flag, got {world['pet_out']['pet_stay']}")

    plain = validate_success(api.create_turnover(create_turnover_payload(
        world["plain_out"]["id"], world["plain_in"]["id"]), COORDINATOR), 201)
    pet = validate_success(api.create_turnover(create_turnover_payload(
        world["pet_out"]["id"], world["pet_in"]["id"]), COORDINATOR), 201)

    assert plain["required_minutes"] == 198, (
        f"150 + 24 + 24 is 198 without a pet, "
        f"got {plain['required_minutes']}")
    assert plain["window_minutes"] == 270 and plain["slack_minutes"] == 72, (
        f"the petless turn keeps 72 minutes of slack, got "
        f"{plain['window_minutes']} / {plain['slack_minutes']}")
    assert plain["is_tight"] is False, (
        f"72 minutes of slack is comfortable, got {plain['is_tight']}")

    assert pet["required_minutes"] == 238, (
        f"the ceiling of 198 times 1.20 is 238, "
        f"got {pet['required_minutes']}")
    assert pet["window_minutes"] == 270, (
        f"the window is identical on both twins, got {pet['window_minutes']}")
    assert pet["slack_minutes"] == 32, (
        f"270 less 238 is 32, got {pet['slack_minutes']}")
    assert pet["is_tight"] is True, (
        f"32 minutes of slack is strictly below 45, got {pet['is_tight']}")
    assert pet["escalation_required"] is False, (
        f"a non-negative slack raises no escalation, "
        f"got {pet['escalation_required']}")


# ─── corner_calc_checkout_clamped_variant_recomputes_without_refusing ─────

def test_03_a_very_late_departure_recomputes_the_window_and_never_refuses(
        api):
    """A 19:30Z departure leaves a 60-minute window at HTTP 200, not a 422.

    PRD §3.2: "This is the one boundary movement that **never refuses**: every
    non-terminal turnover whose departing stay is this booking re-derives
    `window_start_at`, `window_end_at`, `window_minutes`, `slack_minutes`,
    `turn_type` and `is_tight`, and has its `version` incremented by 1, but a
    window that would come out non-positive is clamped to 0 rather than
    rejected." PRD §3.2: "When the recomputed `window_minutes` falls below
    `required_minutes`, the turnover raises `escalation_required` to true."
    PRD §3.3: "Its opening instant, `window_start_at`, is the latest of three
    candidate instants on the departing stay, considering only those that are
    not null: the contracted `checkout_at`, the granted
    `late_checkout_until_at`, and the recorded `actual_checkout_at`."

    Design: Corner/calculations/corner_calc_checkout_clamped_variant_recomputes_without_refusing
    """
    world = fx.build_world(api, supply=None)
    before = world["t1"]
    assert before["window_minutes"] == 270 and before["slack_minutes"] == 72, (
        f"the contracted window is 270 with 72 of slack, got "
        f"{before['window_minutes']} / {before['slack_minutes']}")
    assert before["escalation_required"] is False and before["version"] == 1, (
        f"nothing has been escalated or rewritten yet, got "
        f"{before['escalation_required']} / {before['version']}")

    fx.reset_clock(api, "2026-08-08T19:30:00Z")
    booking = validate_success(api.checkout_booking(
        world["b_out"]["id"],
        {"actual_checkout_at": "2026-08-08T19:30:00Z"}, COORDINATOR), 200)
    assert booking["status"] == "CHECKED_OUT", (
        f"the departure must be recorded, got {booking['status']}")
    assert same_instant(booking["actual_checkout_at"], "2026-08-08T19:30:00Z"), (
        f"the supplied instant must be kept, "
        f"got {booking['actual_checkout_at']}")

    after = fx.read_turnover(api, world)
    assert same_instant(after["window_start_at"], "2026-08-08T19:30:00Z"), (
        f"the latest of the three candidate instants wins, "
        f"got {after['window_start_at']}")
    assert same_instant(after["window_end_at"], "2026-08-08T20:30:00Z"), (
        f"the closing instant is untouched, got {after['window_end_at']}")
    assert after["window_minutes"] == 60, (
        f"19:30Z to 20:30Z is 60 minutes, got {after['window_minutes']}")
    assert after["required_minutes"] == 198, (
        f"the work requirement is sized independently of the window, "
        f"got {after['required_minutes']}")
    assert after["slack_minutes"] == -138, (
        f"60 less 198 is -138, got {after['slack_minutes']}")
    assert after["is_tight"] is True and after["escalation_required"] is True, (
        f"a negative slack is both tight and escalated, got "
        f"{after['is_tight']} / {after['escalation_required']}")
    assert after["version"] == 2, (
        f"the recomputation bumps the version once, got {after['version']}")
    assert after["status"] == "PENDING_ASSIGNMENT", (
        f"the window moved but the workflow did not, got {after['status']}")

    arriving = validate_success(
        api.get_booking(world["b_in"]["id"], COORDINATOR))
    assert arriving["checkin_gate"] == "OPEN", (
        f"only a window collapsed to zero blocks the arrival, "
        f"got {arriving['checkin_gate']}")
    assert arriving["guest_notice_code"] == "NONE", (
        f"no delay notice is due, got {arriving['guest_notice_code']}")


# ─── corner_calc_match_score_tie_is_broken_by_higher_skill_level_not_by_created_at ──

def test_04_a_tied_selector_prefers_the_stronger_skill_over_the_older_record(
        api, tied_candidate_pool):
    """Both candidates score 0.8500 and the skill-4 cleaner takes the offer.

    PRD §3.4: "In selector mode the highest `match_score` wins, and ties are
    broken by a fixed chain applied in order: first the higher `skill_level`;
    then the lower count of the cleaner's non-terminal assignments on the same
    property-local date; then the earlier `created_at` on the cleaner record."
    PRD §3.4: "Skill headroom measures how far above the unit's floor the
    cleaner sits: take the cleaner's `skill_level`, subtract the property's
    `min_skill_level`, add 1, divide by 4, and cap the result at 1.0 — so a
    cleaner exactly at the floor scores 0.25 of headroom and a cleaner four
    tiers above it saturates." PRD §3.4: "A `Coordinator` may name the cleaner
    outright by supplying `cleaner_id`, which records `selection_mode`
    `EXPLICIT`, or omit it and let the server rank the eligible pool, which
    records `selection_mode` `SELECTOR`."

    Design: Corner/calculations/corner_calc_match_score_tie_is_broken_by_higher_skill_level_not_by_created_at
    """
    world = tied_candidate_pool
    t5 = world["t5"]
    assert t5["required_minutes"] == 140, (
        f"120 + 12 + 8 is 140 for a ONE_BR, got {t5['required_minutes']}")

    offer = validate_success(api.assign_turnover(
        t5["id"], assign_turnover_payload(t5["version"]), COORDINATOR), 201)
    assert offer["selection_mode"] == "SELECTOR", (
        f"omitting cleaner_id runs the ranking, got {offer['selection_mode']}")
    assert float(offer["zone_match_factor"]) == pytest.approx(1.0, abs=0.00005)
    assert float(offer["match_score"]) == pytest.approx(0.8500, abs=0.00005), (
        f"both candidates reach 0.8500 by opposite routes, "
        f"got {offer['match_score']}")
    assert offer["cleaner_id"] == world["c_skill"]["id"], (
        f"the skill-4 cleaner must win the tie, got {offer['cleaner_id']}")
    assert offer["cleaner_id"] != world["c_qual"]["id"], (
        "the higher-quality, earlier-created cleaner must lose the tie")

    rows, meta = validate_paginated(
        api.list_assignments(COORDINATOR, {"turnover_id": t5["id"]}))
    assert meta["total_count"] == 1, (
        f"the losing candidate gets no offer row, got {meta['total_count']}")
    assert len(rows) == 1


# ─── corner_calc_match_score_rounds_half_up_at_the_fourth_decimal ─────────

def test_05_a_score_ending_in_five_rounds_up_at_the_fourth_decimal(
        api, half_cent_scoring_world):
    """0.83825 becomes 0.8383 rather than 0.8382.

    PRD §3.4: "The score is then the sum of three weighted terms: normalised
    quality weighted at 0.50, the zone factor weighted at 0.30, and skill
    headroom weighted at 0.20." PRD §3.4: "Because the three weights sum to
    exactly 1.00, the score always lies between 0 and 1 inclusive; it is rounded
    half up to four decimal places." PRD §3.4: "Normalised quality is the
    cleaner's `quality_score` divided by 100, placing it on a 0-to-1 scale."

    Design: Corner/calculations/corner_calc_match_score_rounds_half_up_at_the_fourth_decimal
    """
    world = half_cent_scoring_world
    offer = validate_success(api.assign_turnover(
        world["t6"]["id"],
        assign_turnover_payload(world["t6"]["version"], world["cp"]["id"]),
        COORDINATOR), 201)

    assert float(offer["match_score"]) == pytest.approx(0.8383, abs=0.00005), (
        f"0.43825 + 0.30000 + 0.10000 rounds half up to 0.8383, "
        f"got {offer['match_score']}")
    assert offer["selection_mode"] == "EXPLICIT", (
        f"naming the cleaner records EXPLICIT, got {offer['selection_mode']}")
    assert float(offer["zone_match_factor"]) == pytest.approx(1.0, abs=0.00005)

    cleaner = validate_success(
        api.get_cleaner(world["cp"]["id"], COORDINATOR))
    assert float(cleaner["quality_score"]) == pytest.approx(87.65, abs=0.005), (
        f"scoring an offer never rewrites the cleaner's quality, "
        f"got {cleaner['quality_score']}")


# ─── corner_calc_photo_penalty_cap_holds_at_three_and_four_rejections ─────

def test_06_the_photo_penalty_saturates_at_nine_hundred_cents(
        api, rejection_ladder_world):
    """300, 600, 900 and then 900 again — the fourth rejection is free.

    PRD §3.8: "`photo_penalty_cents` is the smaller of 300 cents for each of the
    turnover's `rejected_review_count` rejections and an absolute ceiling of 900
    cents, so the photo penalty saturates at the third rejection." PRD §3.8:
    "`photo_pass_bonus_cents` is 500 cents when the turnover's
    `rejected_review_count` is 0 and 0 otherwise; photo penalties from
    rejections already booked apply under both variants, so a provisional line
    can carry a photo penalty and no photo-pass bonus." PRD §3.8: "While the
    turnover has not reached `COMPLETED` the preview uses the `PROVISIONAL`
    variant; once the turnover is `COMPLETED` it uses the `FINAL` variant."

    Design: Corner/calculations/corner_calc_photo_penalty_cap_holds_at_three_and_four_rejections
    """
    world = rejection_ladder_world
    p0 = world["preview_on_accept"]
    assert p0["gross_cents"] == 11254, (
        f"8325 base plus 1249 rush plus 1680 linen is 11254, "
        f"got {p0['gross_cents']}")
    assert p0["photo_penalty_cents"] == 0 and p0["bonus_cents"] == 1300, (
        f"an unrejected clean carries both bonuses and no penalty, got "
        f"{p0['photo_penalty_cents']} / {p0['bonus_cents']}")
    assert p0["net_cents"] == 12554, (
        f"11254 plus 1300 is 12554, got {p0['net_cents']}")

    k1, k2, k3, k4 = world["tasks"]
    sheets = world["supply_lines"][0]
    submissions = [
        (k1, submit_task_payload(note="linens stripped"), "hamper not emptied"),
        (k2, submit_task_payload(
            photo_uri="https://cdn.example.com/k2-a.jpg"), "mirror streaked"),
        (k3, submit_task_payload(
            photo_uri="https://cdn.example.com/k3-a.jpg"), "pillows unaligned"),
        (k4, submit_task_payload(
            photo_uri="https://cdn.example.com/k4-a.jpg",
            restock_entries=[restock_entry(sheets["id"], 1)]),
         "welcome tray missing"),
    ]
    previews = []
    for task, payload, reason in submissions:
        validate_success(api.submit_checklist_task(
            task["id"], payload, world["cleaner_headers"]))
        validate_success(api.review_checklist_task(
            task["id"], review_task_payload("REJECT", reject_reason=reason),
            REVIEWER))
        previews.append(validate_success(
            api.get_pay_preview(world["t1"]["id"], COORDINATOR)))
    p1, p2, p3, p4 = previews

    assert p1["photo_penalty_cents"] == 300, (
        f"one rejection costs 300, got {p1['photo_penalty_cents']}")
    assert p1["photo_pass_bonus_cents"] == 0, (
        f"the clean sheet bonus is lost on the first rejection, "
        f"got {p1['photo_pass_bonus_cents']}")
    assert p1["bonus_cents"] == 800 and p1["net_cents"] == 11754, (
        f"only the on-time bonus survives, got {p1['bonus_cents']} / "
        f"{p1['net_cents']}")
    assert p2["photo_penalty_cents"] == 600 and p2["net_cents"] == 11454, (
        f"two rejections sit one step below the ceiling, got "
        f"{p2['photo_penalty_cents']} / {p2['net_cents']}")
    assert p3["photo_penalty_cents"] == 900 and p3["net_cents"] == 11154, (
        f"three rejections land exactly on the ceiling, got "
        f"{p3['photo_penalty_cents']} / {p3['net_cents']}")
    assert p4["photo_penalty_cents"] == 900, (
        f"a raw 1200 must be clipped to 900, "
        f"got {p4['photo_penalty_cents']}")
    assert p4["net_cents"] == p3["net_cents"], (
        f"the fourth rejection costs nothing, which is the cap, got "
        f"{p4['net_cents']} against {p3['net_cents']}")
    assert p4["gross_cents"] == 11254, (
        f"rejections never touch the gross, got {p4['gross_cents']}")
    assert p4["late_penalty_cents"] == 0 and p4["variant"] == "PROVISIONAL", (
        f"provisional lateness is forced to zero, got "
        f"{p4['late_penalty_cents']} / {p4['variant']}")

    turnover = fx.read_turnover(api, world)
    assert turnover["rejected_review_count"] == 4, (
        f"four rejections must be counted, "
        f"got {turnover['rejected_review_count']}")
    assert turnover["status"] == "REWORK_REQUIRED", (
        f"rejection drives the parent into rework, got {turnover['status']}")


# ─── corner_calc_quality_carryover_curve_and_penalty_below_seventy ────────

def test_07_a_sixty_nine_audit_bends_the_rolling_score_and_debits_the_pay(
        api):
    """92.00 becomes 85.10 and the FINAL line is debited 1200 into ADJUSTED.

    PRD §3.9: "From there both variants converge: `resulting_quality_score` is
    seventy percent of the cleaner's current `quality_score` plus thirty percent
    of `observed_score`, rounded half up to two decimals, and the cleaner's
    `quality_score` is then replaced by that figure." PRD §3.9:
    "`pay_adjustment_cents` is positive 1,000 cents when the `score` is greater
    than or equal to 95, negative 1,200 cents when the `score` is strictly below
    70, and 0 for any score inside that neutral band." PRD §3.9: "When the
    adjustment is non-zero, the turnover's `FINAL` pay line folds it into
    `audit_adjustment_cents`, re-derives `net_cents` accordingly, moves `FINAL →
    ADJUSTED`, and the cleaner's `pending_payout_cents` moves by that same
    signed delta." PRD §3.9: "Nothing moves yet — neither `quality_score` nor
    any money — until the audit is finalized."

    Design: Corner/calculations/corner_calc_quality_carryover_curve_and_penalty_below_seventy
    """
    world = fx.world_completed(api, supply="pair")
    completed = world["t1"]
    assert completed["late_minutes"] == 0, (
        f"the clean finished before the window closed, "
        f"got {completed['late_minutes']}")
    assert completed["restock_chargeback_cents"] == 474, (
        f"280 plus 194 is 474, "
        f"got {completed['restock_chargeback_cents']}")
    assert same_instant(completed["finished_at"], "2026-08-08T20:00:00Z"), (
        f"finished_at reads the logical clock, got {completed['finished_at']}")

    before = validate_success(api.list_pay_lines(
        COORDINATOR, {"turnover_id": completed["id"]}))[0]
    assert before["variant"] == "FINAL" and before["status"] == "FINAL", (
        f"completion settles the line, got {before['variant']} / "
        f"{before['status']}")
    assert before["net_cents"] == 11114, (
        f"9814 gross plus 1300 of bonus is 11114, got {before['net_cents']}")

    audit = validate_success(api.create_quality_audit(
        create_quality_audit_payload(
            completed["id"], 69,
            findings="grout not detailed; oven interior missed"),
        AUDITOR), 201)
    assert audit["status"] == "SAMPLED", (
        f"a fresh sample lands in SAMPLED, got {audit['status']}")
    assert audit["observed_score"] is None, (
        f"the observed score is not computed until finalization, "
        f"got {audit['observed_score']}")
    assert float(fx.read_cleaner(api, world)["quality_score"]) == pytest.approx(
        92.00, abs=0.005), "sampling alone must not move the rolling score"
    assert validate_success(api.list_pay_lines(
        COORDINATOR, {"turnover_id": completed["id"]}))[0]["net_cents"] == 11114, (
        "sampling alone must not move any money")

    final = validate_success(
        api.finalize_quality_audit(audit["id"], {}, AUDITOR))
    assert final["variant_applied"] == "AUDIT_ONLY", (
        f"no guest rating had landed, got {final['variant_applied']}")
    assert final["guest_rating_at_audit"] is None, (
        f"there is no rating to capture, "
        f"got {final['guest_rating_at_audit']}")
    assert float(final["observed_score"]) == pytest.approx(69.00, abs=0.005), (
        f"AUDIT_ONLY carries the raw score across, "
        f"got {final['observed_score']}")
    assert float(final["resulting_quality_score"]) == pytest.approx(
        85.10, abs=0.005), (
        f"0.70 times 92.00 plus 0.30 times 69.00 is 85.10, "
        f"got {final['resulting_quality_score']}")
    assert final["pay_adjustment_cents"] == -1200, (
        f"69 is strictly below 70, got {final['pay_adjustment_cents']}")
    assert final["status"] == "FINALIZED", (
        f"finalization must complete, got {final['status']}")
    assert same_instant(final["finalized_at"], "2026-08-08T20:00:00Z"), (
        f"finalized_at reads the logical clock, got {final['finalized_at']}")

    cleaner = fx.read_cleaner(api, world)
    assert float(cleaner["quality_score"]) == pytest.approx(85.10, abs=0.005), (
        f"the carryover weight dominates a single audit, "
        f"got {cleaner['quality_score']}")
    assert cleaner["completed_turnover_count"] == 1, (
        f"one clean was closed out, "
        f"got {cleaner['completed_turnover_count']}")
    assert cleaner["pending_payout_cents"] == 9914, (
        f"the ledger tracks the adjusted net, "
        f"got {cleaner['pending_payout_cents']}")

    after = validate_success(api.list_pay_lines(
        COORDINATOR, {"turnover_id": completed["id"]}))[0]
    assert after["gross_cents"] == 9814, (
        f"an audit never touches the gross, got {after['gross_cents']}")
    assert after["audit_adjustment_cents"] == -1200, (
        f"the debit must be folded in, "
        f"got {after['audit_adjustment_cents']}")
    assert after["net_cents"] == 9914, (
        f"11114 less 1200 is 9914, got {after['net_cents']}")
    assert after["status"] == "ADJUSTED", (
        f"a non-zero adjustment moves FINAL to ADJUSTED, "
        f"got {after['status']}")


# ─── corner_calc_on_hand_qty_is_a_pure_sum_over_the_append_only_ledger ────

def test_08_on_hand_is_the_summed_ledger_and_never_an_edited_number(
        api, soap_line_property):
    """2, 7 and then 14 across three surviving movements whose deltas reconcile.

    PRD §2.9: "A supply line's `on_hand_qty` is a pure projection: it equals the
    sum of `delta_qty` across every `StockMovement` bearing that line's
    `supply_line_id`, regardless of the movement's `reason`." PRD §2.9:
    "Immediately after that projection is refreshed, `below_par` is recomputed as
    true exactly when `on_hand_qty` is less than or equal to `reorder_point`."
    PRD §3.1: "The append carries `reason` `REPLENISH` and a `delta_qty` equal
    to the supplied `qty`, refreshes `on_hand_qty` and `below_par`, and
    increments the line's `version` by 1."

    Design: Corner/calculations/corner_calc_on_hand_qty_is_a_pure_sum_over_the_append_only_ledger
    """
    p8 = soap_line_property
    line = validate_success(api.create_supply_line(
        p8["id"], create_supply_line_payload(
            sku="CON-SOAP", name="Bar Soap", category="CONSUMABLE",
            unit_cost_cents=200, par_qty=4, unit="EACH", reorder_point=3,
            initial_on_hand_qty=2), COORDINATOR), 201)
    assert line["on_hand_qty"] == 2, (
        f"the SEED movement projects 2, got {line['on_hand_qty']}")
    assert line["below_par"] is True, (
        f"2 is at or below a reorder_point of 3, got {line['below_par']}")
    assert line["version"] == 1 and line["status"] == "ACTIVE", (
        f"a fresh line is version 1 and ACTIVE, got {line['version']} / "
        f"{line['status']}")

    first = validate_success(api.replenish_supply_line(
        line["id"], replenish_payload(5, line["version"], note="weekly drop"),
        COORDINATOR))
    assert first["on_hand_qty"] == 7, (
        f"2 plus 5 is 7, got {first['on_hand_qty']}")
    assert first["below_par"] is False, (
        f"7 is above a reorder_point of 3, got {first['below_par']}")
    assert first["version"] == 2, (
        f"the append bumps the version once, got {first['version']}")

    second = validate_success(api.replenish_supply_line(
        line["id"], replenish_payload(7, first["version"]), COORDINATOR))
    assert second["on_hand_qty"] == 14, (
        f"2 plus 5 plus 7 is 14, got {second['on_hand_qty']}")
    assert second["below_par"] is False, (
        f"14 remains above the reorder point, got {second['below_par']}")
    assert second["version"] == 3, (
        f"a second append bumps the version again, got {second['version']}")

    movements, meta = validate_paginated(api.list_stock_movements(
        COORDINATOR, {"supply_line_id": line["id"]}))
    assert meta["total_count"] == 3, (
        f"no ledger row may be edited away, got {meta['total_count']}")
    assert [(m["reason"], m["delta_qty"]) for m in movements] == [
        ("SEED", 2), ("REPLENISH", 5), ("REPLENISH", 7)], (
        f"the ledger must record each append verbatim, got "
        f"{[(m['reason'], m['delta_qty']) for m in movements]}")
    assert movements[2]["charge_cents"] == 0, (
        f"only restock consumption carries money, "
        f"got {movements[2]['charge_cents']}")

    projected = validate_success(api.get_supply_line(line["id"], COORDINATOR))
    assert projected["on_hand_qty"] == sum(
        m["delta_qty"] for m in movements) == 14, (
        f"the projection must reconcile with the ledger, "
        f"got {projected['on_hand_qty']}")

    _, low = validate_paginated(api.list_property_supply_lines(
        p8["id"], COORDINATOR, {"below_par": True}))
    assert low["total_count"] == 0, (
        f"the restocked line is no longer below par, "
        f"got {low['total_count']}")


# ─── corner_calc_daily_load_counts_only_live_assignments_regardless_of_creation_order ──

def test_09_an_outstanding_offer_fills_the_daily_slot_until_it_is_declined(
        api, single_slot_cleaner_world):
    """The identical second offer is refused, then accepted verbatim after a decline.

    PRD §3.4: "The **daily load** referred to throughout is computed against the
    property-local calendar date of the turnover's `window_start_at`: it counts
    the cleaner's assignments whose `status` is `OFFERED`, `ACCEPTED` or `ACTIVE`
    and whose own turnover's `window_start_at`, converted using *that*
    turnover's property offset, falls on the same local date." PRD §3.4: "The
    cap is reached when that count is greater than or equal to
    `max_daily_turnovers`." PRD §3.4: "In explicit mode nothing is filtered —
    each pool condition the named cleaner fails becomes an error in its own
    right instead: a suspended or offboarded cleaner draws
    `ERR_CLEANER_NOT_ACTIVE`, a cleaner outside the served zones or below the
    required skill tier draws `ERR_CLEANER_NOT_ELIGIBLE`, a cleaner already at
    the daily ceiling draws `ERR_CLEANER_DAILY_CAP_REACHED`, and a cleaner whose
    existing windows collide draws `ERR_CLEANER_SCHEDULE_CONFLICT`." PRD §3.5:
    "But the turnover is left entirely alone — it stays in
    `PENDING_ASSIGNMENT`, and crucially its `version` is **not** incremented."

    Design: Corner/calculations/corner_calc_daily_load_counts_only_live_assignments_regardless_of_creation_order
    """
    world = single_slot_cleaner_world
    cd, ta, tb = world["cd"], world["ta"], world["tb"]
    assert cd["max_daily_turnovers"] == 1 and cd["decline_count"] == 0, (
        f"a one-slot cleaner starts with no refusals, got "
        f"{cd['max_daily_turnovers']} / {cd['decline_count']}")
    assert (same_instant(ta["window_start_at"], "2026-08-08T16:00:00Z")
            and same_instant(ta["window_end_at"], "2026-08-08T20:30:00Z")), (
        f"the later-created turn runs 16:00Z to 20:30Z, got "
        f"{ta['window_start_at']} / {ta['window_end_at']}")
    assert (same_instant(tb["window_start_at"], "2026-08-08T20:45:00Z")
            and same_instant(tb["window_end_at"], "2026-08-08T23:30:00Z")), (
        f"the earlier-created turn runs 20:45Z to 23:30Z, got "
        f"{tb['window_start_at']} / {tb['window_end_at']}")
    assert tb["window_minutes"] == 165, (
        f"20:45Z to 23:30Z is 165 minutes, got {tb['window_minutes']}")

    first = validate_success(api.assign_turnover(
        ta["id"], assign_turnover_payload(ta["version"], cd["id"]),
        COORDINATOR), 201)
    assert first["status"] == "OFFERED", (
        f"the first offer must stand, got {first['status']}")
    assert float(first["match_score"]) == pytest.approx(0.9600, abs=0.00005), (
        f"0.46 plus 0.30 plus 0.20 is 0.9600, got {first['match_score']}")

    blocked = api.assign_turnover(
        tb["id"], assign_turnover_payload(tb["version"], cd["id"]),
        COORDINATOR)
    validate_error(blocked, ApiErrorId.ERR_CLEANER_DAILY_CAP_REACHED.value, 409)

    declined = validate_success(api.decline_assignment(
        first["id"], {"decline_reason": "double-booked personally"},
        world["cleaner_headers"]))
    assert declined["status"] == "DECLINED", (
        f"the refusal must be recorded, got {declined['status']}")
    assert validate_success(
        api.get_cleaner(cd["id"], COORDINATOR))["decline_count"] == 1, (
        "the decline counter must rise by one")

    retry = validate_success(api.assign_turnover(
        tb["id"], assign_turnover_payload(tb["version"], cd["id"]),
        COORDINATOR), 201)
    assert retry["status"] == "OFFERED", (
        f"a DECLINED row no longer fills the slot, got {retry['status']}")
    assert float(retry["match_score"]) == pytest.approx(0.9600, abs=0.00005), (
        f"the identical payload scores identically, "
        f"got {retry['match_score']}")

    _, live = validate_paginated(api.list_assignments(
        COORDINATOR, {"cleaner_id": cd["id"], "status": "OFFERED"}))
    assert live["total_count"] == 1, (
        f"exactly one live offer may remain, got {live['total_count']}")

    after = validate_success(api.get_turnover(ta["id"], COORDINATOR))
    assert after["status"] == "PENDING_ASSIGNMENT", (
        f"the declined turn is offerable again, got {after['status']}")
    assert after["version"] == 2, (
        f"the offer bumped the version and the decline did not, "
        f"got {after['version']}")

"""Membership cycles, pausing, rolling, tier proration and cycle geometry."""

from test_helpers import (
    ApiErrorId,
    assert_calendar_date,
    assert_membership,
    assert_membership_lab_credit_conservation,
    assert_membership_visit_conservation,
    book_encounter,
    complete_encounter,
    membership_version,
    open_membership,
    read_membership,
    read_patient,
    register_nd,
    register_patient,
    set_clock,
    setup_patient_at_booking_score,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN


def _member_with_reserved_visit(api):
    """CORE member on 2026-05-01 with one reserved visit and the clock at 2026-05-14."""
    nd = register_nd(api)
    patient = setup_patient_at_booking_score(
        api,
        nd,
        attested=("CHIEF_COMPLAINT_TIMELINE", "SYSTEMS_REVIEW", "FAMILY_HISTORY"),
    )
    membership = open_membership(api, patient["id"], tier="CORE", cycle_start_date="2026-05-01")
    book_encounter(
        api,
        nd["id"],
        patient["id"],
        scheduled_start="2026-06-10T09:00:00Z",
        scheduled_end="2026-06-10T10:00:00Z",
    )
    set_clock(api, "2026-05-14T00:00:00Z")
    return nd, patient, membership


def test_pause_and_resume_slides_the_cycle_end_out_by_the_paused_days(api):
    """PRD §3.2: "Pausing a membership is a `PracticeAdmin` action that takes
    `ACTIVE → PAUSED`, stamps `paused_at` with the logical clock, and increments
    the membership's `version` by 1."
    PRD §3.2: "Resuming takes `PAUSED → ACTIVE` and repays the lost time: the
    number of whole days from `paused_at` to the current logical clock is
    computed, rounded **up** to the next whole day whenever any partial day has
    elapsed, added to `paused_days_total`, and added to `cycle_end_date` so the
    cycle window slides out by exactly that many days."

    Design: Corner/state_machines/membership_pause_and_resume_extends_the_cycle_end_date
    """
    nd = register_nd(api)
    patient = register_patient(api, nd["id"])
    membership = open_membership(
        api, patient["id"], tier="CORE", cycle_start_date="2026-05-01"
    )
    assert_calendar_date(membership["cycle_end_date"], "2026-05-30", "cycle_end_date")

    set_clock(api, "2026-05-05T00:00:00Z")
    paused = validate_success(api.pause_membership(membership["id"], ADMIN))
    assert paused["status"] == "PAUSED"

    set_clock(api, "2026-05-15T00:00:00Z")
    resumed = validate_success(api.resume_membership(membership["id"], ADMIN))

    assert_membership(resumed)
    assert resumed["status"] == "ACTIVE"
    assert resumed["paused_days_total"] == 10
    assert_calendar_date(resumed["cycle_end_date"], "2026-06-09", "cycle_end_date")
    assert resumed["paused_at"] is None
    assert resumed["visits_remaining"] == 4, "A pause grants, consumes and forfeits nothing"


def test_renewing_roll_forfeits_the_remainder_and_adds_a_fresh_grant(api):
    """PRD §3.2: "Either way, whatever sits in `visits_remaining` is added to
    `visits_forfeited` and whatever sits in `lab_credits_remaining` is added to
    `lab_credits_forfeited` — unused entitlement never carries forward."
    PRD §3.2: "When `renew` is true the membership stays `ACTIVE` in a
    self-loop: a fresh grant equal to the tier's included visits and included
    laboratory credits is added to `visits_granted` and `lab_credits_granted`,
    `visits_remaining` and `lab_credits_remaining` are set to those same tier
    figures, `cycle_index` increments by 1, `cycle_start_date` becomes the day
    after the previous `cycle_end_date`, and `cycle_end_date` is recomputed as
    that new start date plus 30 days minus one day."

    Design: Corner/state_machines/membership_roll_cycle_forfeits_the_remainder_and_regrants
    """
    nd = register_nd(api)
    patient = register_patient(api, nd["id"])
    membership = open_membership(
        api, patient["id"], tier="CORE", cycle_start_date="2026-05-01"
    )

    rolled = validate_success(
        api.roll_membership_cycle(membership["id"], {"renew": True}, ADMIN)
    )

    assert_membership(rolled)
    assert rolled["status"] == "ACTIVE"
    assert rolled["cycle_index"] == 2
    assert_calendar_date(rolled["cycle_start_date"], "2026-05-31", "cycle_start_date")
    assert_calendar_date(rolled["cycle_end_date"], "2026-06-29", "cycle_end_date")
    assert rolled["visits_granted"] == 8
    assert rolled["visits_consumed"] == 0
    assert rolled["visits_remaining"] == 4
    assert rolled["visits_forfeited"] == 4
    assert rolled["lab_credits_granted"] == 4
    assert rolled["lab_credits_forfeited"] == 2
    assert_membership_visit_conservation(rolled)
    assert_membership_lab_credit_conservation(rolled)


def test_non_renewing_roll_expires_the_membership_and_deactivates_the_patient(api):
    """PRD §3.2: "When `renew` is false, `visits_remaining` and
    `lab_credits_remaining` are instead set to 0, the membership moves
    `ACTIVE → EXPIRED`, and — because the membership expired — the owning
    patient's `clinical_status` moves to `INACTIVE` if it was `ESTABLISHED`."
    PRD §3.2: "If the patient was `INACTIVE`, opening the membership returns
    them to `ESTABLISHED`."

    Design: Corner/state_machines/membership_expiry_moves_the_patient_to_inactive
    """
    nd = register_nd(api)
    patient = setup_patient_at_booking_score(
        api,
        nd,
        attested=("CHIEF_COMPLAINT_TIMELINE", "SYSTEMS_REVIEW", "FAMILY_HISTORY"),
    )
    membership = open_membership(
        api, patient["id"], tier="CORE", cycle_start_date="2026-05-01"
    )
    encounter = book_encounter(api, nd["id"], patient["id"])
    complete_encounter(
        api, nd["id"], encounter["id"], duration_minutes=30, service_code="99213"
    )
    assert read_patient(api, patient["id"])["clinical_status"] == "ESTABLISHED"

    expired = validate_success(
        api.roll_membership_cycle(membership["id"], {"renew": False}, ADMIN)
    )
    assert expired["status"] == "EXPIRED"
    assert expired["visits_remaining"] == 0
    assert expired["visits_forfeited"] == 3
    assert read_patient(api, patient["id"])["clinical_status"] == "INACTIVE"

    second = open_membership(
        api, patient["id"], tier="FOUNDATION", cycle_start_date="2026-07-01"
    )
    assert second["visits_granted"] == 2
    assert read_patient(api, patient["id"])["clinical_status"] == "ESTABLISHED"


def test_tier_change_prorates_the_money_from_the_pre_change_counters(api):
    """PRD §3.2: "Compute the unused credit on the old tier as the old tier's
    monthly fee multiplied by `remaining_days`, divided by 30, rounded half up
    to whole cents."
    PRD §3.2: "Set `last_proration_net_charge_cents` to the new prorated fee
    minus the old unused credit. It is positive on an upgrade and negative — a
    credit — on a downgrade."
    PRD §3.2: "The money then lands on the patient: when
    `last_proration_net_charge_cents` is positive it is added to
    `cash_charged_total_cents`, and when it is negative its absolute value is
    added to `cash_refunded_total_cents`."

    Design: Difficulty/combinatorial_formula/tier_change_proration_pinned_evaluation_order
    """
    nd, patient, membership = _member_with_reserved_visit(api)
    expected_version = membership_version(api, patient["id"])

    changed = validate_success(
        api.change_membership_tier(
            membership["id"],
            {"new_tier": "PREMIER", "expected_membership_version": expected_version},
            ADMIN,
        )
    )

    assert changed["tier"] == "PREMIER"
    assert changed["last_proration_net_charge_cents"] == 8500
    assert changed["monthly_fee_cents"] == 34900
    assert changed["dispensary_discount_pct"] == 0.20

    refreshed = read_patient(api, patient["id"])
    assert refreshed["cash_charged_total_cents"] == 8500
    assert refreshed["cash_refunded_total_cents"] == 0


def test_tier_change_rewrites_the_grants_without_touching_consumed_or_forfeited(api):
    """PRD §3.2: "Rewrite `visits_granted` by subtracting the current
    `visits_remaining` from it and then adding the prorated visit grant, and set
    `visits_remaining` to the prorated visit grant."
    PRD §3.2: "Steps 8 and 9 remove the old remaining balance before adding the
    new grant, which is what leaves `visits_consumed`, `visits_forfeited`,
    `lab_credits_consumed` and `lab_credits_forfeited` untouched and keeps the
    conservation identities of §2.9 intact across a tier change."

    Design: Difficulty/combinatorial_formula/tier_change_proration_pinned_evaluation_order
    """
    nd, patient, membership = _member_with_reserved_visit(api)
    before = read_membership(api, patient["id"])
    assert before["visits_consumed"] == 1 and before["visits_remaining"] == 3

    changed = validate_success(
        api.change_membership_tier(
            membership["id"],
            {"new_tier": "PREMIER", "expected_membership_version": before["version"]},
            ADMIN,
        )
    )

    assert changed["visits_granted"] == 6
    assert changed["visits_consumed"] == 1
    assert changed["visits_remaining"] == 5
    assert changed["visits_forfeited"] == 0
    assert changed["lab_credits_granted"] == 3
    assert changed["lab_credits_consumed"] == 0
    assert changed["lab_credits_remaining"] == 3
    assert changed["lab_credits_forfeited"] == 0
    assert_membership_visit_conservation(changed)
    assert_membership_lab_credit_conservation(changed)


def test_a_cycle_starting_on_the_previous_cycle_end_date_collides(api):
    """PRD §3.2: "Because that interval is closed, a new cycle may not touch or
    overlap the cycle of any existing membership of the same patient whose
    `status` is `ACTIVE` or `PAUSED`: a cycle ending on a given day collides
    with one starting on that same day, and the request is refused with
    `ERR_MEMBERSHIP_CYCLE_OVERLAP`."
    PRD §2.7: "**Membership billing cycles on a patient are closed.** The
    occupied interval runs from `cycle_start_date` through `cycle_end_date`,
    both endpoints included."

    Design: Difficulty/resource_temporal_overlap/membership_cycles_are_closed_so_touching_cycles_collide
    """
    nd = register_nd(api)
    patient = register_patient(api, nd["id"])
    first = open_membership(
        api, patient["id"], tier="FOUNDATION", cycle_start_date="2026-05-01"
    )
    assert_calendar_date(first["cycle_end_date"], "2026-05-30", "cycle_end_date")

    response = api.create_membership(
        {"patient_id": patient["id"], "tier": "CORE", "cycle_start_date": "2026-05-30"},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_MEMBERSHIP_CYCLE_OVERLAP.value, 409)


def test_a_cycle_starting_the_day_after_the_previous_cycle_end_is_accepted(api):
    """PRD §3.2: "The server computes `cycle_end_date` as the start date plus 30
    days minus one day, so the cycle covers exactly thirty calendar days and
    both endpoints belong to it."
    PRD §3.2: "On success the tier constant block is resolved onto the row —
    `monthly_fee_cents`, `dispensary_discount_pct` and `includes_messaging` —
    the `cycle_index` starts at 1, `visits_granted` and `visits_remaining` are
    both set to the tier's included visits, `lab_credits_granted` and
    `lab_credits_remaining` are both set to the tier's included laboratory
    credits, and `visits_consumed`, `visits_forfeited`, `lab_credits_consumed`,
    `lab_credits_forfeited`, `paused_days_total` and
    `last_proration_net_charge_cents` all start at 0 with `paused_at` null."

    Design: Difficulty/resource_temporal_overlap/membership_cycles_are_closed_so_touching_cycles_collide
    """
    nd = register_nd(api)
    patient = register_patient(api, nd["id"])
    open_membership(api, patient["id"], tier="FOUNDATION", cycle_start_date="2026-05-01")

    response = api.create_membership(
        {"patient_id": patient["id"], "tier": "CORE", "cycle_start_date": "2026-05-31"},
        ADMIN,
    )
    second = validate_success(response, 201)

    assert_membership(second)
    assert_calendar_date(second["cycle_end_date"], "2026-06-29", "cycle_end_date")
    assert second["visits_granted"] == 4
    assert second["visits_remaining"] == 4
    assert second["cycle_index"] == 1
    assert second["paused_at"] is None
    assert second["last_proration_net_charge_cents"] == 0

"""Behaviour exactly on the stated boundaries: a genre share sitting on the cap,
a wave holding exactly one booking, and a whole-day count landing on the far
deposit threshold together with the first releasable date.

Every test builds its own preconditions from an empty database and sets the
logical clock explicitly, because the server is restarted before each test.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    BUSINESS_AFFAIRS,
    FINANCE_CONTROLLER,
    TALENT_BUYER,
    expected_deposit_pct,
    make_artist_rep_headers,
)
from test_helpers import fixtures as fx

AT_CAP_GUARANTEE_CENTS = 2000000
ONE_CENT_CENTS = 1
LATIN_WINDOW_START = "2026-11-04"
LATIN_WINDOW_END = "2026-12-14"
CLOCK_AT_120_DAYS = "2026-08-06T00:00:00Z"
CLOCK_AT_119_DAYS = "2026-08-07T00:00:00Z"
FIRST_RELEASABLE_CLOCK = "2026-08-29T00:00:00Z"


# --------------------------------------------------------------- module helpers
def _edition_whose_genre_cap_lands_on_a_whole_cent(api):
    """Allocatable 5000000 cents, so the 0.40 genre cap is exactly 2000000 cents.

    Three draw-80 acts: two LATIN and one POP. Their drafts are 2000000, one
    cent and one cent, so the second LATIN draft is a single cent of numerator
    past the cap once the first is live.
    """
    ctx = fx.single_tier_edition(
        api,
        festival_overrides={
            "talent_budget_cents": 5000000,
            "contingency_reserve_pct": 0.00,
        },
        tier_overrides={"max_slots": 4, "genre_focus": "MIXED"},
        artist_overrides={
            "legal_name": "Sol Ateneo LLC",
            "performing_name": "Sol Ateneo",
            "primary_genre": "LATIN",
            "agency": "Meridian Talent",
            "draw_score": 80,
            "default_radius_miles": 120,
        },
    )
    second_latin_act = fx.create_artist(
        api,
        legal_name="Ruta Cinco LLC",
        performing_name="Ruta Cinco",
        primary_genre="LATIN",
        agency="Meridian Talent",
        draw_score=80,
        default_radius_miles=120,
    )
    pop_act = fx.create_artist(
        api,
        legal_name="Pale Signal LLC",
        performing_name="Pale Signal",
        primary_genre="POP",
        agency="Foghorn Agency",
        draw_score=80,
        default_radius_miles=120,
    )
    terms = {
        "radius_miles": 120,
        "window_start_date": LATIN_WINDOW_START,
        "window_end_date": LATIN_WINDOW_END,
    }
    at_cap = fx.draft_offer(
        api,
        ctx,
        ctx["artist"],
        guarantee_cents=AT_CAP_GUARANTEE_CENTS,
        slot_start_utc="2026-12-04T21:00:00Z",
        **terms,
    )
    one_cent_over = fx.draft_offer(
        api,
        ctx,
        second_latin_act,
        guarantee_cents=ONE_CENT_CENTS,
        slot_start_utc="2026-12-05T21:00:00Z",
        **terms,
    )
    other_genre = fx.draft_offer(
        api,
        ctx,
        pop_act,
        guarantee_cents=ONE_CENT_CENTS,
        slot_start_utc="2026-12-06T21:00:00Z",
        **terms,
    )
    return {
        "ctx": ctx,
        "at_cap": at_cap,
        "one_cent_over": one_cent_over,
        "other_genre": other_genre,
    }


def _countersigned_booking_and_an_empty_wave(api):
    """One COUNTERSIGNED booking plus a PLANNED wave holding nothing yet."""
    ctx = fx.single_tier_edition(api)
    countersigned = fx.countersigned_booking(api, ctx)
    wave = fx.planned_wave(
        api, ctx["festival"]["id"], scheduled_reveal_utc="2026-09-20T17:00:00Z"
    )
    return {"ctx": ctx, "booking": countersigned["booking"], "wave": wave}


def _two_acceptances_a_day_apart(api):
    """Two identical 1800000-cent offers accepted at 120 and at 119 days out.

    The edition starts 2026-12-04, so the clock at 2026-08-06 is exactly 120
    whole days from the gates and 2026-08-07 is 119.
    """
    ctx = fx.single_tier_edition(
        api, clock=CLOCK_AT_120_DAYS, tier_overrides={"genre_focus": "MIXED"}
    )
    hip_hop_act = fx.create_artist(
        api,
        legal_name="Cass Meridian LLC",
        performing_name="Cass Meridian",
        primary_genre="HIP_HOP",
        agency="Foghorn Agency",
        draw_score=72,
        default_radius_miles=150,
    )
    far_offer = fx.issued_offer(
        api, ctx, ctx["artist"], slot_start_utc="2026-12-04T21:00:00Z"
    )
    near_offer = fx.issued_offer(
        api, ctx, hip_hop_act, slot_start_utc="2026-12-05T21:00:00Z"
    )
    far_booking = validate_success(
        api.accept_offer(
            far_offer["id"], make_artist_rep_headers(ctx["artist"]["id"])
        ),
        201,
    )
    fx.set_clock(api, CLOCK_AT_119_DAYS)
    near_booking = validate_success(
        api.accept_offer(
            near_offer["id"], make_artist_rep_headers(hip_hop_act["id"])
        ),
        201,
    )
    return {"ctx": ctx, "far_booking": far_booking, "near_booking": near_booking}


# ------------------------------------------- a projected share exactly on the cap
def test_an_offer_landing_exactly_on_the_genre_cap_can_be_issued(api):
    """A projected share of exactly 0.40 is inside the cap, not outside it.

    "Computed **including** the offer under evaluation, the share is tested against the hard genre cap of 0.40: a projected share of exactly 0.40 passes and one cent of numerator more fails, with the rejection reported as `ERR_GENRE_CAP_EXCEEDED`."
    "Computed **excluding** the offer under evaluation, the share picks the factor: `genre_balance_factor` is stamped at 1.00 when the share is at most 0.30, at 0.85 when the share is above 0.30 but at most 0.40, and at 0.60 when the share is above 0.40."
    Design: Difficulty/boundary_precision_check/genre_share_exactly_at_cap_passes
    """
    world = _edition_whose_genre_cap_lands_on_a_whole_cent(api)

    issued = validate_success(api.issue_offer(world["at_cap"]["id"], TALENT_BUYER), 200)

    assert issued["status"] == "ISSUED"
    assert issued["guarantee_cents"] == AT_CAP_GUARANTEE_CENTS
    assert issued["guarantee_ceiling_cents"] == 2000000
    assert issued["genre_balance_factor"] == 1.00


def test_one_cent_of_numerator_past_the_genre_cap_is_refused(api):
    """With the cap already exhausted, a single further cent of the genre fails.

    "Computed **including** the offer under evaluation, the share is tested against the hard genre cap of 0.40: a projected share of exactly 0.40 passes and one cent of numerator more fails, with the rejection reported as `ERR_GENRE_CAP_EXCEEDED`."
    "The numerator adds the `guarantee_cents` of every booking of this edition whose act's `primary_genre` is that genre and whose `contract_status` is not `CANCELLED`, plus the `guarantee_cents` of every *other* offer of this edition whose `status` is `ISSUED` or `COUNTERED` and whose act shares that genre."
    Design: Difficulty/boundary_precision_check/genre_share_exactly_at_cap_passes
    """
    world = _edition_whose_genre_cap_lands_on_a_whole_cent(api)
    validate_success(api.issue_offer(world["at_cap"]["id"], TALENT_BUYER), 200)

    validate_error(
        api.issue_offer(world["one_cent_over"]["id"], TALENT_BUYER),
        "ERR_GENRE_CAP_EXCEEDED",
        409,
    )

    refused = validate_success(
        api.get_offer(world["one_cent_over"]["id"], TALENT_BUYER)
    )
    assert refused["status"] == "DRAFT"
    assert refused["guarantee_cents"] == ONE_CENT_CENTS


def test_an_exhausted_genre_does_not_block_an_act_of_another_genre(api):
    """The cap is measured per genre, so a POP act is untouched by the LATIN share.

    "For a given genre, the committed share is a numerator over a denominator."
    "The numerator adds the `guarantee_cents` of every booking of this edition whose act's `primary_genre` is that genre and whose `contract_status` is not `CANCELLED`, plus the `guarantee_cents` of every *other* offer of this edition whose `status` is `ISSUED` or `COUNTERED` and whose act shares that genre."
    Design: Difficulty/boundary_precision_check/genre_share_exactly_at_cap_passes
    """
    world = _edition_whose_genre_cap_lands_on_a_whole_cent(api)
    validate_success(api.issue_offer(world["at_cap"]["id"], TALENT_BUYER), 200)
    validate_error(
        api.issue_offer(world["one_cent_over"]["id"], TALENT_BUYER),
        "ERR_GENRE_CAP_EXCEEDED",
        409,
    )

    issued = validate_success(
        api.issue_offer(world["other_genre"]["id"], TALENT_BUYER), 200
    )

    assert issued["status"] == "ISSUED"
    assert issued["genre_balance_factor"] == 1.00


# ------------------------------------- zero assignments versus exactly one
def test_locking_a_wave_with_nothing_in_it_is_refused(api):
    """An empty wave does not lock vacuously and its version does not move.

    "It requires the wave to be `PLANNED`, requires `assignment_count` to be at least 1 — a wave with nothing in it is rejected with `ERR_EMPTY_WAVE` rather than locking vacuously, and a single assignment is enough — requires every booking assigned to the wave whose `contract_status` is not `CANCELLED` to have reached `COUNTERSIGNED`, failing which the answer is `ERR_WAVE_BOOKING_NOT_COUNTERSIGNED`, requires the wave's `phase` to equal the edition's current `announcement_phase`, and requires the reveal instant to still precede the event start."
    Design: Difficulty/boundary_precision_check/empty_wave_lock_rejected_at_zero_assignments
    """
    world = _countersigned_booking_and_an_empty_wave(api)
    assert world["wave"]["assignment_count"] == 0

    validate_error(
        api.lock_wave(world["wave"]["id"], TALENT_BUYER), "ERR_EMPTY_WAVE", 409
    )

    wave = validate_success(
        api.get_announcement_wave(world["wave"]["id"], TALENT_BUYER)
    )
    assert wave["status"] == "PLANNED"
    assert wave["version"] == world["wave"]["version"]


def test_a_wave_holding_exactly_one_booking_locks(api):
    """One assignment is enough to lock, and it reveals first.

    "On success the booking's `announcement_wave_id` is set and its `reveal_order` becomes the wave's `assignment_count` after the increment, so the first booking assigned reveals first."
    "The wave's `assignment_count` increases by one, its `headliner_count` increases by one when the booking's `billing_position` is 1, and its `version` advances."
    Design: Difficulty/boundary_precision_check/empty_wave_lock_rejected_at_zero_assignments
    """
    world = _countersigned_booking_and_an_empty_wave(api)
    validate_error(
        api.lock_wave(world["wave"]["id"], TALENT_BUYER), "ERR_EMPTY_WAVE", 409
    )

    fx.assign_to_wave(api, world["wave"], world["booking"]["id"])

    booking = validate_success(
        api.get_booking(world["booking"]["id"], TALENT_BUYER)
    )
    assert booking["announcement_wave_id"] == world["wave"]["id"]
    assert booking["reveal_order"] == 1
    wave = validate_success(
        api.get_announcement_wave(world["wave"]["id"], TALENT_BUYER)
    )
    assert wave["assignment_count"] == 1
    assert wave["headliner_count"] == 1
    locked = validate_success(api.lock_wave(wave["id"], TALENT_BUYER))
    assert locked["status"] == "LOCKED"


def test_locking_an_already_locked_wave_is_refused(api):
    """The successful lock was a real transition, so a repeat call has nowhere to go.

    "The wave's own `status` must admit an assignment; a `LOCKED` wave accepts no further members and a `PUBLISHED` wave is terminal, both reported as `ERR_INVALID_WAVE_STATE`."
    "It requires the wave to be `PLANNED`, requires `assignment_count` to be at least 1 — a wave with nothing in it is rejected with `ERR_EMPTY_WAVE` rather than locking vacuously, and a single assignment is enough — requires every booking assigned to the wave whose `contract_status` is not `CANCELLED` to have reached `COUNTERSIGNED`, failing which the answer is `ERR_WAVE_BOOKING_NOT_COUNTERSIGNED`, requires the wave's `phase` to equal the edition's current `announcement_phase`, and requires the reveal instant to still precede the event start."
    Design: Difficulty/boundary_precision_check/empty_wave_lock_rejected_at_zero_assignments
    """
    world = _countersigned_booking_and_an_empty_wave(api)
    fx.assign_to_wave(api, world["wave"], world["booking"]["id"])
    validate_success(api.lock_wave(world["wave"]["id"], BUSINESS_AFFAIRS))

    validate_error(
        api.lock_wave(world["wave"]["id"], TALENT_BUYER),
        "ERR_INVALID_WAVE_STATE",
        409,
    )

    wave = validate_success(
        api.get_announcement_wave(world["wave"]["id"], TALENT_BUYER)
    )
    assert wave["status"] == "LOCKED"
    assert wave["assignment_count"] == 1


# ----------------------------- a whole-day count sitting on the far deposit tier
def test_accepting_exactly_120_days_out_takes_half_the_guarantee_as_deposit(api):
    """At exactly 120 days the far percentage still applies.

    "The deposit percentage is 0.50 when there are at least 120 days to go — exactly 120 days still earns 0.50 — 0.40 when there are at least 60 but fewer than 120, and 0.25 when there are fewer than 60."
    "The deposit's `due_date` is the later of today's date and the earlier of two candidates: today plus 30 days, and the edition's `event_start_date` less 14 days."
    Design: Difficulty/boundary_precision_check/deposit_tier_exactly_120_days_uses_half
    """
    world = _two_acceptances_a_day_apart(api)

    rows = fx.installments_of(api, world["far_booking"]["id"])

    assert expected_deposit_pct(120) == 0.50
    assert rows["DEPOSIT"]["amount_cents"] == 900000
    assert rows["DEPOSIT"]["due_date"] == "2026-09-05"
    assert rows["BALANCE"]["amount_cents"] == 900000
    assert rows["BALANCE"]["due_date"] == "2026-12-04"


def test_accepting_one_day_later_drops_the_deposit_to_two_fifths(api):
    """One day inside the threshold moves the percentage down a bracket.

    "The deposit percentage is 0.50 when there are at least 120 days to go — exactly 120 days still earns 0.50 — 0.40 when there are at least 60 but fewer than 120, and 0.25 when there are fewer than 60."
    "The balance's `due_date` is the calendar date of the booking's `slot_start_utc`."
    Design: Difficulty/boundary_precision_check/deposit_tier_exactly_120_days_uses_half
    """
    world = _two_acceptances_a_day_apart(api)

    rows = fx.installments_of(api, world["near_booking"]["id"])

    assert expected_deposit_pct(119) == 0.40
    assert rows["DEPOSIT"]["amount_cents"] == 720000
    assert rows["DEPOSIT"]["due_date"] == "2026-09-06"
    assert rows["BALANCE"]["amount_cents"] == 1080000
    assert rows["BALANCE"]["due_date"] == "2026-12-05"


def test_each_schedule_sums_back_to_the_guarantee(api):
    """The balance is the integer complement of the deposit, not its own rounding.

    "The deposit's `amount_cents` is the booking's `guarantee_cents` multiplied by that percentage and rounded half up once; the balance's `amount_cents` is the guarantee less the deposit, taken as an exact integer complement and never independently rounded, so the pair always sums back to the guarantee."
    Design: Difficulty/boundary_precision_check/deposit_tier_exactly_120_days_uses_half
    """
    world = _two_acceptances_a_day_apart(api)

    far = fx.installments_of(api, world["far_booking"]["id"])
    near = fx.installments_of(api, world["near_booking"]["id"])

    assert far["DEPOSIT"]["amount_cents"] + far["BALANCE"]["amount_cents"] == 1800000
    assert near["DEPOSIT"]["amount_cents"] + near["BALANCE"]["amount_cents"] == 1800000


def test_a_deposit_is_releasable_from_exactly_a_week_before_its_due_date(api):
    """Seven days ahead of the due date is the first releasable instant, not one later.

    "It also requires the release window to be open: the logical clock's date must have reached the installment's `due_date` less 7 days."
    "Money cannot leave more than a week ahead of its due date, and the boundary date itself is releasable; earlier than that is `ERR_PAYMENT_NOT_RELEASABLE`."
    Design: Difficulty/boundary_precision_check/deposit_tier_exactly_120_days_uses_half
    """
    world = _two_acceptances_a_day_apart(api)
    deposit = fx.installments_of(api, world["far_booking"]["id"])["DEPOSIT"]
    assert deposit["due_date"] == "2026-09-05"

    validate_error(
        api.release_installment(deposit["id"], FINANCE_CONTROLLER),
        "ERR_PAYMENT_NOT_RELEASABLE",
        409,
    )

    fx.set_clock(api, FIRST_RELEASABLE_CLOCK)
    released = validate_success(
        api.release_installment(deposit["id"], FINANCE_CONTROLLER)
    )
    assert released["status"] == "RELEASED"
    assert released["released_at"].startswith("2026-08-29T00:00:00")

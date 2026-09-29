"""Consistency breadth: every derived value is settled inside the response of the
write that causes it, every cross-row ledger is correct on the very next read,
and the single checkpoint-bound projection is the stated exception."""
from test_helpers import (
    create_accommodation_block,
    create_athlete,
    create_edition,
    create_entry,
    create_sport,
    create_sport_event,
    get_athlete,
    get_block,
    get_edition,
    get_event,
    open_registration,
    pay_fees,
    reserve_stay,
    screen_athlete,
    take_up_and_accept,
)


def test_every_derived_value_is_already_settled_in_the_response_that_causes_it(clock_at_epoch):
    """PRD §3.1: "A fresh event is `OPEN`, with `accepted_entry_count` at 0,
    `available_slots` equal to its `capacity`, `current_record_id` null and
    `seeded_at_utc` null."
    PRD §3.2: "A newly created athlete also reads `fee_total_cents` 0, `fee_paid_cents`
    0 and an empty `fee_breakdown`."
    PRD §3.2: "**Step six** sets `fee_total_cents` to `discounted_cents` plus
    `surcharge_cents`, and pins the seven intermediate values into `fee_breakdown` under
    the keys `entry_count`, `event_fees_cents`, `subtotal_cents`, `discount_pct`,
    `discount_cents`, `discounted_cents` and `surcharge_cents`."
    PRD §3.2: "On success the recomputed `fee_total_cents` and `fee_breakdown` are
    stored, `fee_paid_cents` is set equal to `fee_total_cents`, and the registration
    dimension advances `PENDING_PAYMENT` → `REGISTERED`."
    PRD §3.3: "`qualification_priority` is the rank weight of the source — 1 for
    `STATE_QUALIFIER`, 2 for `LOCAL_QUALIFIER`, 3 for `AGE_EXEMPT` and 4 for
    `ORGANIZER_INVITE`, so a lower number is a stronger claim."
    PRD §3.3: "On success it stores the `review_note`, increments the event's
    `accepted_entry_count` by one, decrements the event's `available_slots` by one, and
    lifts the event `UNDERSUBSCRIBED` → `OPEN` when the acceptance brings
    `accepted_entry_count` up to `min_entries_to_stage`."
    PRD §3.4: "`recommendation` follows directly from `risk_score`: below 25.0 it is
    `CLEARED`; from 25.0 up to but not including 60.0 it is `CLEARED_WITH_RESTRICTION`;
    at 60.0 and above it is `HOLD_PENDING_PHYSICIAN_REVIEW`."
    PRD §3.8: "Where the booking is accepted, the service derives the rest: `nights` is
    the whole number of days from the `check_in_date` to the `check_out_date`,
    `total_charge_cents` is that night count multiplied by the block's
    `nightly_rate_cents` — snapshotted at reservation so a later change to the block's
    nightly rate never rewrites an existing stay's charge — and the block's
    `reserved_bed_nights` is increased by the same night count."
    PRD §3.9: "Sixth, and only now that heads and stays have settled,
    `provisional_impact_cents` is recomputed."

    One pass down the registration lifecycle in which each write response is read
    for the values it derives — the capacity ledger, the age band, the seven-key fee
    breakdown, the risk score, the accepted count, the bed-night ledger — and the
    follow-up read is only ever used to prove it reveals nothing new.  The one
    exception is stated as such: the edition's provisional projection is bound to the
    operations checkpoint, so it is still zero for a registered athlete.

    Design: Corner/consistency_model/corner_consistency_immediate_derived_state_visible_without_a_reread
    """
    edition = create_edition()
    sport = create_sport(sport_code="TRACK", name="Track and Field")
    created_event = create_sport_event(
        sport["id"], edition["id"], entry_fee_cents=6000, capacity=8,
        min_entries_to_stage=1,
    )
    open_registration(edition["id"])
    created_block = create_accommodation_block(
        edition["id"], name="Maple Hall", bed_capacity=4, nightly_rate_cents=12000
    )

    # The capacity ledger is derived at insert time, not on first read.
    assert created_event["available_slots"] == 8
    assert created_event["accepted_entry_count"] == 0
    assert created_block["reserved_bed_nights"] == 0

    created_athlete = create_athlete(edition["id"], full_name="Ada Fenn")
    # 1966-03-02 against the reference date of 2026-12-31 is 60, and the band
    # follows from the age with no second call.
    assert created_athlete["age_at_reference"] == 60
    assert created_athlete["age_group_code"] == "60-64"
    # fee_total_cents is settled by pay-fees, so zero here is a correct opening
    # value rather than a stale one.
    assert created_athlete["fee_total_cents"] == 0
    assert created_athlete["registration_status"] == "PENDING_PAYMENT"

    created_entry = create_entry(
        created_athlete["id"], created_event["id"],
        qualification_source="ORGANIZER_INVITE",
    )
    assert created_entry["status"] == "SUBMITTED"
    # ORGANIZER_INVITE is the fourth rank weight, carried by the creation response.
    assert created_entry["qualification_priority"] == 4

    # 9500 base + one 6000 event fee, one entry so no discount tier and a subtotal
    # under the 25000 surcharge threshold.
    settled = pay_fees(created_athlete["id"], 15500)
    assert settled["fee_total_cents"] == 15500
    assert settled["fee_paid_cents"] == 15500
    assert settled["registration_status"] == "REGISTERED"
    breakdown = settled["fee_breakdown"]
    assert breakdown["entry_count"] == 1
    assert breakdown["event_fees_cents"] == 6000
    assert breakdown["subtotal_cents"] == 15500
    assert float(breakdown["discount_pct"]) == 0.0
    assert breakdown["discount_cents"] == 0
    assert breakdown["discounted_cents"] == 15500
    assert breakdown["surcharge_cents"] == 0

    # The follow-up read reveals nothing the write response did not already carry.
    after_payment = get_athlete(created_athlete["id"])
    assert after_payment["fee_total_cents"] == settled["fee_total_cents"]
    assert after_payment["registration_status"] == settled["registration_status"]

    # Age points (60 - 55) * 1.5 = 7.5; 128 mmHg is below the 130 threshold, 70 bpm
    # is at the floor, and the LOW-contact entry adds no load, so 7.5 stands
    # unmultiplied and lands below the 25.0 clearance band.
    screening = screen_athlete(created_athlete["id"])
    assert float(screening["risk_score"]) == 7.5
    assert screening["recommendation"] == "CLEARED"
    assert screening["contact_sport_count"] == 0
    # The driven dimension needs no settling call of its own.
    assert get_athlete(created_athlete["id"])["medical_status"] == "SCREENED_CLEARED"

    accepted = take_up_and_accept(created_entry["id"])
    assert accepted["status"] == "ACCEPTED"
    # The seat is off the ledger on the immediately following read, with no
    # operations checkpoint in between.
    event_after_acceptance = get_event(created_event["id"])
    assert event_after_acceptance["accepted_entry_count"] == 1
    assert event_after_acceptance["available_slots"] == 7
    assert event_after_acceptance["status"] == "OPEN"

    # 09-09 to 09-14 is five nights at 12000 a night.
    stay = reserve_stay(
        created_athlete["id"], created_block["id"],
        check_in_date="2026-09-09", check_out_date="2026-09-14",
    )
    assert stay["nights"] == 5
    assert stay["total_charge_cents"] == 60000
    assert stay["status"] == "RESERVED"
    # The two block reads bracket the ledger write: 0 before, 5 immediately after.
    assert get_block(created_block["id"])["reserved_bed_nights"] == 5

    # The stated exception.  One athlete is REGISTERED, yet the projection is bound
    # to a phase of the operations checkpoint, which has not run.
    edition_now = get_edition(edition["id"])
    assert edition_now["provisional_impact_cents"] == 0
    assert edition_now["ops_epoch"] == 0

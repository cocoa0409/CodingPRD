"""Validation-priority conflicts: when two checks both fail, the lower-priority
number is reported (PRD §2.9 fixed ordering).

Covers difficulty queue A rule priority_pair_validation_conflict.
"""
from test_helpers import (
    validate_success,
    validate_error,
    register_fan,
    register_and_verify_fan,
    create_event,
    create_tier,
    open_to_phase,
    setup_held_ticket,
    make_fan_headers,
)
from test_helpers.fixtures import PROMOTER
from test_helpers.factories import create_resale_listing_payload


def test_flagged_beats_presale_code_on_queue_join(api):
    """PRD §2.9: "Only after those five structural gates do the domain-specific
    business rules run, in this order: the bot-flag bar (ERR_FAN_FLAGGED), the
    presale-code gate (ERR_INVALID_PRESALE_CODE), the mobile-only entry gate
    (ERR_NON_MOBILE_ENTRY), the verified-fan restriction (ERR_FAN_NOT_VERIFIED)".
    PRD §2.9: "a flagged actor, for instance, is always reported as
    ERR_FAN_FLAGGED rather than being masked by the later verified-fan check."

    A FLAGGED fan joining PRESALE with a wrong code violates both the flag bar
    (priority 6) and the presale-code gate (priority 7); the flag bar wins.

    Design: Difficulty/priority_pair_validation_conflict/flagged_beats_presale_code_on_queue_join
    """
    event = create_event(venue_capacity=100, presale_code="SUMMER", face_value_cents=10000)
    tier = create_tier(event["id"], allocation=50)
    open_to_phase(event, "PRESALE")
    # Three fans on a shared device, then a 4th with a '+' email -> 60 + 25 = 85 >= 70.
    register_fan("s1@x.com", device="dev-bot", full_name="S1")
    register_fan("s2@x.com", device="dev-bot", full_name="S2")
    register_fan("s3@x.com", device="dev-bot", full_name="S3")
    fx = register_fan("x+bot@x.com", device="dev-bot", full_name="X")
    flagged = validate_success(api.verify_fan(fx["id"], make_fan_headers(fx["id"])), 200)
    assert flagged["verification_status"] == "FLAGGED", flagged
    res = api.create_queue_entry(
        {"event_id": event["id"], "fan_id": fx["id"], "tier_id": tier["id"],
         "presale_code_used": "WRONG", "requested_qty": 1},
        make_fan_headers(fx["id"]),
    )
    validate_error(res, "ERR_FAN_FLAGGED")


def test_invalid_state_beats_resale_cap_on_listing(api):
    """PRD §2.9: "then whether the target resource is in a state from which the
    requested transition is defined (ERR_INVALID_STATE). Only after those five
    structural gates do the domain-specific business rules run, in this order:
    ... the resale price cap (ERR_RESALE_CAP_EXCEEDED)".
    PRD §3.7: "Listing is permitted only when the ticket is HELD and VALID".

    A second listing attempt on an already-LISTED ticket at an over-cap price
    violates the state gate (priority 5) and the resale-cap gate (priority 11);
    the state gate wins with ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_resale_cap_on_listing
    """
    event, tier, fan, order, ticket = setup_held_ticket(
        phase="GENERAL", resale_cap_pct=110, face_value_cents=10000
    )
    # First listing at 11000 (within cap 21000) -> ticket becomes LISTED.
    validate_success(api.create_resale_listing(
        create_resale_listing_payload(ticket["id"], fan["id"], 11000),
        make_fan_headers(fan["id"]),
    ), 201)
    # Second listing on the now-LISTED ticket at over-cap 99000.
    res = api.create_resale_listing(
        create_resale_listing_payload(ticket["id"], fan["id"], 99000),
        make_fan_headers(fan["id"]),
    )
    validate_error(res, "ERR_INVALID_STATE")

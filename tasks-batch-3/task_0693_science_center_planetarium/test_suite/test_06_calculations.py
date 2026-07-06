"""Pricing calculations: non-member and member show pricing, inactive-card
filtering, early-bird tuition, and ASTC computed eligibility.

Queue B (Corner): section calculations + the astc-status endpoint reads.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    create_open_show,
    create_active_membership,
    create_membership,
    create_classroom_program,
)

CLERK = TEST_USERS["membership_clerk_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
PROGRAM = TEST_USERS["program_coordinator_headers"]


def test_nonmember_show_pricing_no_discount(api):
    """PRD §3.4: "The `member_discount_cents` is the member discount, which is 0 for
    any walk-up (no `membership_id`) and 0 whenever the named card is not currently
    `ACTIVE`."
    PRD §3.4: "The `net_price_cents` is the `gross_price_cents` minus the
    `member_discount_cents`, snapshotted at hold time and frozen thereafter."

    Non-member 2-seat hold, per_seat=2500: gross=5000, discount=0, net=5000.

    Design: Corner/calculations/nonmember_show_pricing_no_discount
    """
    show = create_open_show(seated_capacity=40, base_price_cents=2000,
                            feature_surcharge_cents=500, title="NM")
    booking = validate_success(api.create_show_booking(
        {"show_event_id": show["id"], "party_size": 2,
         "expected_show_version": show["version"]}, BOX_OFFICE), expected_status=201)
    assert booking["member_discount_cents"] == 0
    assert booking["net_price_cents"] == 5000, \
        f"expected net 5000, got {booking['net_price_cents']}"


def test_patron_discounts_base_only_not_surcharge(api):
    """PRD §3.4: "A `PATRON` card discounts 100% of the base price but never the
    feature surcharge; its discount is the `party_size` multiplied by the show's
    `base_price_cents`."

    ACTIVE PATRON, 2-seat hold, base=2000 surcharge=500: discount=2*2000=4000,
    gross=2*2500=5000, net=1000.

    Design: Corner/calculations/patron_surcharge_not_discounted
    """
    patron = create_active_membership(tier="PATRON", home_zip="90210", party_size=4,
                                      dues_cents=25000, primary_member_name="Pat")
    show = create_open_show(seated_capacity=40, base_price_cents=2000,
                            feature_surcharge_cents=500, title="Pat")
    booking = validate_success(api.create_show_booking(
        {"show_event_id": show["id"], "membership_id": patron["id"], "party_size": 2,
         "expected_show_version": show["version"]}, BOX_OFFICE), expected_status=201)
    assert booking["member_discount_cents"] == 4000, \
        f"expected discount 4000, got {booking['member_discount_cents']}"
    assert booking["net_price_cents"] == 1000, \
        f"expected net 1000, got {booking['net_price_cents']}"


def test_inactive_membership_gets_no_discount(api):
    """PRD §3.4: "The `member_discount_cents` is the member discount, which is 0 for
    any walk-up (no `membership_id`) and 0 whenever the named card is not currently
    `ACTIVE`."

    A PENDING (never-activated) FAMILY card on a 2-seat hold yields discount 0,
    net=5000.

    Design: Corner/calculations/inactive_membership_no_discount
    """
    pending = create_membership(tier="FAMILY", home_zip="90210", party_size=3,
                                primary_member_name="Pend")  # never activated -> PENDING
    show = create_open_show(seated_capacity=40, base_price_cents=2000,
                            feature_surcharge_cents=500, title="Pend")
    booking = validate_success(api.create_show_booking(
        {"show_event_id": show["id"], "membership_id": pending["id"], "party_size": 2,
         "expected_show_version": show["version"]}, BOX_OFFICE), expected_status=201)
    assert booking["member_discount_cents"] == 0, \
        f"inactive card must not discount, got {booking['member_discount_cents']}"
    assert booking["net_price_cents"] == 5000


def test_nonmember_first_enrollment_gets_early_bird_discount(api):
    """PRD §3.6: "A walk-up (no `membership_id`) or a participant whose card is not
    currently `ACTIVE` pays the full base. ... After that percentage step, an
    **early-bird** reduction may apply: if the session's `enrolled_count` observed
    immediately before this enrollment is fewer than 3, a further flat 1000 cents is
    subtracted, with the result floored at 0."

    Non-member, base tuition 10000, enrolled_count_before=0 < 3:
    tuition_charged_cents = 10000 - 1000 = 9000.

    Design: Corner/calculations/program_tuition_early_bird_threshold
    """
    program = create_classroom_program(capacity=10, tuition_cents=10000, min_age=5, max_age=99,
                                        title="EB")
    reg = validate_success(api.create_registration(
        {"program_session_id": program["id"], "participant_name": "Early",
         "participant_age": 10, "expected_session_version": program["version"]}, PROGRAM),
        expected_status=201)
    assert reg["tuition_charged_cents"] == 9000, \
        f"expected tuition 9000, got {reg['tuition_charged_cents']}"


def test_astc_eligible_family_within_radius(api):
    """PRD §3.2: "The card also computes a flag, `astc_eligible`, which is true exactly
    when the tier is `FAMILY` or `PATRON`".
    PRD §3.2: "The standalone ASTC-status read reports this determination for a given
    card."

    An ACTIVE FAMILY card with home_zip 60614 (within the 606 radius) is still
    ASTC-eligible by tier.

    Design: Corner/calculations/astc_reciprocal_within_radius_denied
    """
    member = create_active_membership(tier="FAMILY", home_zip="60614", party_size=2,
                                      dues_cents=12000, primary_member_name="Local")
    status = validate_success(api.get_membership_astc_status(member["id"], CLERK))
    assert status["astc_eligible"] is True, \
        f"FAMILY must be ASTC-eligible, got {status['astc_eligible']}"


def test_astc_status_read_for_out_of_radius_family(api):
    """PRD §3.2: "The card also computes a flag, `astc_eligible`, which is true exactly
    when the tier is `FAMILY` or `PATRON`".
    PRD §3.2: "The standalone ASTC-status read reports this determination for a given
    card."

    An ACTIVE FAMILY card with home_zip 90210 (outside the 606 radius) is
    ASTC-eligible.

    Design: Corner/endpoints/astc_status_computed_read
    """
    member = create_active_membership(tier="FAMILY", home_zip="90210", party_size=2,
                                      dues_cents=12000, primary_member_name="Far")
    status = validate_success(api.get_membership_astc_status(member["id"], BOX_OFFICE))
    assert status["astc_eligible"] is True, \
        f"FAMILY must be ASTC-eligible, got {status['astc_eligible']}"

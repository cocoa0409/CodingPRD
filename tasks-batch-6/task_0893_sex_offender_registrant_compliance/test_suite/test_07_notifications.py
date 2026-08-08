"""Community notification: tier-driven radius and the estimated vs actual
recipient variants."""
from test_helpers import (
    validate_success, get_success_data,
    create_jurisdiction, create_registrant, add_offense, activate, add_address,
    TEST_USERS,
)

OFFICER = TEST_USERS["registration_officer_headers"]


def _tier2_subject_with_one_neighbour():
    """TIER_2 subject with a RESIDENCE at (0,0), plus one OTHER registrant with a
    RESIDENCE at (0,0); jurisdiction est_households_per_notification == 100."""
    jur = create_jurisdiction(name="Metro", state_code="CA", est_households_per_notification=100)
    subject = create_registrant(jur["id"], full_name="Subject S")
    add_offense(subject["id"], offense_class="CLASS_A")  # tier_score 30 -> TIER_2
    subject = activate(subject["id"])
    add_address(subject["id"], subject["version"], address_type="RESIDENCE",
                line1="1 A St", grid_x=0, grid_y=0)
    other = create_registrant(jur["id"], full_name="Other O", date_of_birth="1979-02-02T00:00:00Z")
    add_offense(other["id"], offense_class="CLASS_B")
    other = activate(other["id"])
    add_address(other["id"], other["version"], address_type="RESIDENCE",
                line1="2 A St", grid_x=0, grid_y=0)
    return jur, subject


def test_notification_radius_and_estimated_recipients_for_tier_two(api):
    """PRD 3.7: "The notification `radius_meters` follows the registrant's tier: 0
    meters for `TIER_1`, 500 meters for `TIER_2`, and 1500 meters for `TIER_3`."
    PRD 3.7: "The forward-looking `estimated_recipients` is the owning
    jurisdiction's `est_households_per_notification` multiplied by a tier
    multiplier of 0 for `TIER_1`, 3 for `TIER_2`, and 10 for `TIER_3`; it ignores
    actual addresses."

    Design: Difficulty/dual_variant_calc/notification_estimated_vs_actual_recipients
    """
    jur, subject = _tier2_subject_with_one_neighbour()
    resp = api.create_notification(subject["id"], {"audience_scope": "PUBLIC"}, OFFICER)
    data = validate_success(resp, expected_status=201)
    assert data["radius_meters"] == 500
    assert data["estimated_recipients"] == 300, "est_households(100) * tier_mult(3) == 300"


def test_notification_actual_recipients_counts_nearby_residences(api):
    """PRD 3.7: "The measured `actual_recipients` is the count of `VERIFIED`
    `RESIDENCE` addresses belonging to other registrants whose straight-line grid
    distance to the subject registrant's current residence is less than or equal to
    the notification radius."

    Design: Difficulty/dual_variant_calc/notification_estimated_vs_actual_recipients
    """
    jur, subject = _tier2_subject_with_one_neighbour()
    resp = api.create_notification(subject["id"], {"audience_scope": "PUBLIC"}, OFFICER)
    data = validate_success(resp, expected_status=201)
    assert data["actual_recipients"] == 1, "one other VERIFIED RESIDENCE within 500m"

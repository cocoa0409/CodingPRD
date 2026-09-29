"""Waitlist entitlement and the offer run's exact-match candidate pool."""

from test_helpers import assertions as asserts
from test_helpers import fixtures as fx

OFFER_RUN_CLOCK = "2026-08-25T00:00:00Z"
OFFER_EXPIRY_AT_48H = "2026-08-27T00:00:00Z"

WRONG_ON_BOTH_KEYS = {
    "unit_code": "B-200",
    "bedroom_count": 3,
    "unit_type": "SFH",
    "designated_rank_category": "SENIOR_ENLISTED",
    "historic_flag": False,
}
RIGHT_BEDROOMS_WRONG_RANK = {
    "unit_code": "A-102",
    "bedroom_count": 2,
    "unit_type": "TOWNHOME",
    "designated_rank_category": "SENIOR_ENLISTED",
    "historic_flag": False,
}
RIGHT_ON_BOTH_KEYS = {
    "unit_code": "A-103",
    "bedroom_count": 2,
    "unit_type": "TOWNHOME",
    "designated_rank_category": "JUNIOR_ENLISTED",
    "historic_flag": False,
}


def _pending_family_and_one_mismatched_unit(api):
    """A two-bedroom junior-enlisted family waiting beside a big senior unit."""
    state = fx.setup_pending_application(
        api,
        clock=OFFER_RUN_CLOCK,
        installation_overrides={"offer_response_hours": 48},
        unit_specs=(WRONG_ON_BOTH_KEYS,),
    )
    assert state["application"]["bedroom_eligibility"] == 2
    assert state["application"]["rank_category"] == "JUNIOR_ENLISTED"
    return state


def test_offer_run_skips_a_unit_wrong_on_both_pool_keys(api):
    """A three-bedroom senior unit is no offer for a two-bedroom junior family.

    PRD: "If the candidate set is empty, the run **skips that unit and continues**: no error is raised, no offer is created, and the unit keeps `status` `AVAILABLE`."

    Design: Difficulty/boundary_precision_check/waitlist_offer_run_exact_pool_equality_at_the_boundary
    """
    state = _pending_family_and_one_mismatched_unit(api)

    installation = fx.run_offer_run(api, state["installation"]["id"])

    assert installation["offer_run_epoch"] == 1
    assert installation["available_unit_count"] == 1
    assert installation["assigned_unit_count"] == 0
    asserts.assert_instant_equals(installation["last_offer_run_at"], OFFER_RUN_CLOCK)
    application = fx.read_application(api, state["application"]["id"])
    assert application["status"] == "PENDING"
    assert application["offered_unit_id"] is None
    assert application["offer_count"] == 0
    assert application["offer_expires_at"] is None
    assert fx.read_housing_unit(api, state["units"][0]["id"])["status"] == "AVAILABLE"


def test_matching_bedroom_count_alone_is_not_enough_to_qualify(api):
    """The rank key must match too, so a second run still creates no offer.

    PRD: "An application qualifies when its `status` is `PENDING`, its `bedroom_eligibility` is **exactly equal** to the unit's `bedroom_count` — not merely large enough, and not merely no larger — its `rank_category` is **exactly equal** to the unit's `designated_rank_category`, and either its `accessibility_required` is false or the unit's `accessibility_features` contains `ROLL_IN_SHOWER`."

    Design: Difficulty/boundary_precision_check/waitlist_offer_run_exact_pool_equality_at_the_boundary
    """
    state = _pending_family_and_one_mismatched_unit(api)
    fx.run_offer_run(api, state["installation"]["id"])
    senior_two_bed = fx.create_housing_unit(
        api, state["installation"]["id"], **RIGHT_BEDROOMS_WRONG_RANK
    )

    installation = fx.run_offer_run(api, state["installation"]["id"])

    assert installation["offer_run_epoch"] == 2
    assert installation["available_unit_count"] == 2
    assert installation["assigned_unit_count"] == 0
    assert fx.read_application(api, state["application"]["id"])["status"] == "PENDING"
    assert fx.read_housing_unit(api, senior_two_bed["id"])["status"] == "AVAILABLE"


def test_offer_run_takes_the_exact_match_and_leaves_the_near_misses_free(api):
    """Only the unit matching on both keys is offered, and only once.

    PRD: "Winning an offer advances the application `PENDING → OFFERED`, writes the unit's identifier into `offered_unit_id`, sets `offer_expires_at` to the logical clock plus the installation's `offer_response_hours` hours, raises `offer_count` by 1, and increments the application's `version` by 1."

    Design: Difficulty/boundary_precision_check/waitlist_offer_run_exact_pool_equality_at_the_boundary
    """
    state = _pending_family_and_one_mismatched_unit(api)
    inst_id = state["installation"]["id"]
    fx.run_offer_run(api, inst_id)
    senior_two_bed = fx.create_housing_unit(api, inst_id, **RIGHT_BEDROOMS_WRONG_RANK)
    fx.run_offer_run(api, inst_id)
    exact_match = fx.create_housing_unit(api, inst_id, **RIGHT_ON_BOTH_KEYS)

    installation = fx.run_offer_run(api, inst_id)

    assert installation["offer_run_epoch"] == 3
    assert installation["available_unit_count"] == 2
    assert installation["assigned_unit_count"] == 1
    assert installation["pending_application_count"] == 0
    assert installation["total_unit_count"] == 3
    application = fx.read_application(api, state["application"]["id"])
    assert application["status"] == "OFFERED"
    assert application["offered_unit_id"] == exact_match["id"]
    assert application["offer_count"] == 1
    asserts.assert_instant_equals(
        application["offer_expires_at"], OFFER_EXPIRY_AT_48H
    )
    assert fx.read_housing_unit(api, exact_match["id"])["status"] == "ASSIGNED"
    assert fx.read_housing_unit(api, senior_two_bed["id"])["status"] == "AVAILABLE"
    assert fx.read_housing_unit(api, state["units"][0]["id"])["status"] == "AVAILABLE"
    asserts.assert_installation_counter_conservation(installation)


def test_child_reaching_ten_on_the_control_date_takes_a_private_bedroom(api):
    """A tenth birthday landing on the control date buys its own bedroom.

    PRD: "The age comparison is inclusive at ten, so a child whose tenth birthday falls exactly on the control date requires a private bedroom rather than a shared one."

    Design: Difficulty/boundary_precision_check/bedroom_eligibility_child_turning_ten_on_control_date
    """
    state = fx.setup_birthday_boundary_applications(api)
    application = state["on_the_day"]["application"]

    asserts.assert_waitlist_application(application)
    assert application["effective_control_date"] == "2026-08-25"
    assert application["rank_category"] == "JUNIOR_ENLISTED"
    # Base 1 + the ten-year-old's private bedroom + ceil(1/2) for his brother.
    assert application["bedroom_eligibility"] == 3
    assert application["status"] == "PENDING"
    assert application["offered_unit_id"] is None


def test_child_one_day_short_of_ten_shares_a_bedroom(api):
    """A child born one day later is nine, so the brothers share.

    PRD: "Among the dependents whose `relationship` is `CHILD`, every child whose age is at least 10 requires a private bedroom and contributes one bedroom each; the children under 10 share, two same-gender children to a bedroom."

    Design: Difficulty/boundary_precision_check/bedroom_eligibility_child_turning_ten_on_control_date
    """
    state = fx.setup_birthday_boundary_applications(api)
    application = state["the_day_after"]["application"]

    assert application["effective_control_date"] == "2026-08-25"
    # Base 1 + one shared MALE bedroom for two under-ten boys.
    assert application["bedroom_eligibility"] == 2
    assert application["status"] == "PENDING"


def test_one_day_of_date_of_birth_separates_the_two_entitlements(api):
    """Two otherwise identical households differ by exactly one bedroom.

    PRD: "A birthday landing exactly on the control date counts as having been reached."

    Design: Difficulty/boundary_precision_check/bedroom_eligibility_child_turning_ten_on_control_date
    """
    state = fx.setup_birthday_boundary_applications(api)
    on_the_day = state["on_the_day"]["application"]
    the_day_after = state["the_day_after"]["application"]

    assert on_the_day["bedroom_eligibility"] - the_day_after["bedroom_eligibility"] == 1
    assert (
        on_the_day["dependent_count_at_application"]
        == the_day_after["dependent_count_at_application"]
        == 3
    )
    assert on_the_day["rank_category"] == the_day_after["rank_category"]
    installation = fx.read_installation(api, state["installation"]["id"])
    assert installation["pending_application_count"] == 2

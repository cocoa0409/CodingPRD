"""The filing fee's four pinned steps and the shot clock they start."""

from typing import Any, Dict

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_fields,
    assert_instant,
    assert_money,
    assert_money_not,
    ok,
    setup_data,
)
from test_helpers.constants import iso
from test_helpers.test_users import AGENT_PEER, PLANNER_ALT

SUBTOTAL = 5700.00
EXPEDITE_FEE = 456.00
FEE_TOTAL = 6156.00
RE_DERIVED_TIER_TOTAL = 6384.00
DEADLINE = iso("2026-12-29")
VARIANCE_REVIEW_DAYS = 150


def _historic_variance_application(api: ApiClient) -> Dict[str, Any]:
    """A `VARIANCE` filing in a historic district with no simulations on file."""
    S.reset_clock(api)
    jurisdiction = S.create_historic_jurisdiction(api)
    ring = S.create_open_ring(
        api,
        name=C.RING_NAME_B,
        market_code=C.OTHER_MARKET_CODE,
        center_lat=42.4000,
        center_lon=-71.1000,
        priority_rank=2,
    )
    landlord = setup_data(
        api.create_landlord(
            F.landlord_payload(
                legal_name="Village Trust REIT",
                entity_type="REIT",
                contact_email="trust@village.example",
                market_code=C.OTHER_MARKET_CODE,
            ),
            headers=S.agent(AGENT_PEER),
        )
    )
    candidate = setup_data(
        api.create_candidate(
            F.candidate_payload(
                ring["id"],
                landlord["id"],
                jurisdiction["id"],
                owning_agent_user_id=AGENT_PEER,
                site_type="ROOFTOP",
                lat=42.4010,
                lon=-71.1010,
                distance_from_center_m=300,
                agl_m=50,
                months_to_availability=2,
                measured_rsrp_dbm=-90,
                offered_capacity_gbps=8,
            ),
            headers=S.agent(AGENT_PEER),
        )
    )
    cand_id = candidate["id"]
    for event in ("OUTREACH_SENT", "LANDLORD_REPLY"):
        setup_data(
            api.add_outreach_event(
                cand_id, {"event_type": event}, headers=S.agent(AGENT_PEER)
            )
        )

    lease = setup_data(
        api.create_lease(
            F.lease_payload(
                cand_id,
                landlord["id"],
                negotiating_agent_user_id=AGENT_PEER,
                escalation_type="FLAT_STEP",
                escalation_pct=F.OMIT,
                escalation_step_usd=50.00,
                renewal_option_count=1,
                equipment_expansion_sqft=90,
                revenue_share_pct=F.OMIT,
            ),
            headers=S.agent(AGENT_PEER),
        )
    )
    lease_id = lease["id"]
    setup_data(
        api.add_lease_round(
            lease_id,
            {"action": "SUBMIT", "counter_rent_usd": C.LEASE_BASE_RENT_USD},
            headers=S.agent(AGENT_PEER),
        )
    )
    setup_data(
        api.add_lease_round(lease_id, {"action": "ACCEPT"}, headers=S.agent(AGENT_PEER))
    )
    setup_data(
        api.execute_lease(
            lease_id, {"execution_date": C.CLOCK_DEFAULT}, headers=S.director()
        )
    )

    application = setup_data(
        api.create_zoning_application(
            F.zoning_application_payload(
                cand_id, application_type="VARIANCE", filed_by_user_id=PLANNER_ALT
            ),
            headers=S.planner(),
        )
    )
    return {"za_id": application["id"], "cand_id": cand_id, "jur_id": jurisdiction["id"]}


def test_expedite_rate_is_selected_from_the_pre_expedite_subtotal(
    api: ApiClient,
) -> None:
    """A 5700.00 subtotal takes the 0.08 tier even though the total clears 6000.

    PRD: "Step one builds a subtotal: a base fee determined by `application_type`
    — 1500.00 for `BY_RIGHT`, 3200.00 for `CONDITIONAL_USE`, 4800.00 for
    `VARIANCE` — plus 250.00 for each simulation counted in
    `visual_simulation_count`, plus a historic-district surcharge of 900.00 when
    the jurisdiction's `historic_district_flag` is true and nothing when it is
    false."

    PRD: "Step two selects an expedite rate **from that step-one subtotal**: a
    subtotal of 6000 or more takes 0.12, a subtotal of at least 4000 but below
    6000 takes 0.08, and a subtotal below 4000 takes 0.04."

    PRD: "Re-deriving the tier from the step-four total — which the expedite fee
    itself has inflated — is explicitly wrong and will misprice applications that
    sit near a tier boundary."

    Design: Difficulty/combinatorial_formula/zoning_expedite_tier_keyed_on_step_one_subtotal
    """
    scenario = _historic_variance_application(api)

    submitted = ok(api.submit_zoning_application(scenario["za_id"], headers=S.planner()))

    assert_fields(submitted, visual_simulation_count=0, status="SUBMITTED")
    assert_money(submitted["zoning_fee_total_usd"], FEE_TOTAL, "zoning_fee_total_usd")
    assert_money_not(
        submitted["zoning_fee_total_usd"],
        RE_DERIVED_TIER_TOTAL,
        "zoning_fee_total_usd",
    )
    assert_money(
        float(submitted["zoning_fee_total_usd"]) - SUBTOTAL,
        EXPEDITE_FEE,
        "expedite fee",
    )


def test_submission_starts_the_variance_shot_clock(api: ApiClient) -> None:
    """Filing stamps the submission date and derives the path's own deadline.

    PRD: "Submission stamps `submitted_date` with the logical clock, prices the
    filing fee into `zoning_fee_total_usd`, and computes the initial
    `shot_clock_deadline_date`."

    PRD: "`shot_clock_deadline_date` is the `submitted_date` advanced by the number
    of review days the jurisdiction publishes for this application's path —
    `by_right_review_days` for `BY_RIGHT`, `conditional_use_review_days` for
    `CONDITIONAL_USE`, `variance_review_days` for `VARIANCE` — and further
    advanced by the application's accumulated `tolled_days`."

    Design: Difficulty/combinatorial_formula/zoning_expedite_tier_keyed_on_step_one_subtotal
    """
    scenario = _historic_variance_application(api)

    submitted = ok(api.submit_zoning_application(scenario["za_id"], headers=S.planner()))

    assert_instant(submitted["submitted_date"], C.CLOCK_DEFAULT, "submitted_date")
    assert_instant(
        submitted["shot_clock_deadline_date"], DEADLINE, "shot_clock_deadline_date"
    )
    assert_fields(submitted, tolled_days=0)

    shot_clock = ok(api.get_shot_clock(scenario["za_id"], headers=S.planner()))
    assert_fields(
        shot_clock,
        review_days=VARIANCE_REVIEW_DAYS,
        tolled_days=0,
        days_remaining=VARIANCE_REVIEW_DAYS,
        deemed_grantable=False,
    )
    assert_instant(
        shot_clock["shot_clock_deadline_date"], DEADLINE, "shot_clock_deadline_date"
    )

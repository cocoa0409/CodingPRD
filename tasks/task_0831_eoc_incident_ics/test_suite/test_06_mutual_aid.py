"""EMAC mutual-aid negotiation: the offer/counter/re-offer cycle and the
liaison ownership gate.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_activated_incident,
    create_jurisdiction,
    create_mutual_aid_request,
    offer_mutual_aid,
    counter_mutual_aid,
    make_jurisdiction_liaison_headers,
)

LOG = TEST_USERS["logistics_chief_headers"]


# ─── Difficulty: non_linear_state_machine / mutual_aid_offer_counter_negotiation_cycle ───
def test_offer_counter_reoffer_returns_to_offered(api):
    """PRD §3.6: "From `OFFERED`, the `LogisticsChief` may counter, advancing to `COUNTERED`
    and setting `countered_units`, which must likewise be at least 1 (otherwise
    `ERR_INVALID_QUANTITY`). The liaison may then re-offer, advancing from `COUNTERED` back to
    `OFFERED` with a fresh `offered_units` of at least 1 (again subject to the ownership check)
    — a negotiation loop that may repeat."

    Design: Difficulty/non_linear_state_machine/mutual_aid_offer_counter_negotiation_cycle
    """
    inc = create_activated_incident(name="Regional Flood", hazard_type="FLOOD")
    jur = create_jurisdiction(name="North County")
    ma = create_mutual_aid_request(inc["id"], jur["id"], resource_type="PERSONNEL", requested_units=5)
    offer_mutual_aid(ma["id"], jur["id"], offered_units=4)
    counter_mutual_aid(ma["id"], countered_units=6)
    reoffered = validate_success(
        api.transition_mutual_aid_request(
            ma["id"], {"to_status": "OFFERED", "offered_units": 5},
            make_jurisdiction_liaison_headers(jur["id"]),
        )
    )
    assert reoffered["status"] == "OFFERED", f"expected OFFERED after re-offer, got {reoffered['status']}"


def test_reoffer_updates_offered_units(api):
    """PRD §3.6: "The liaison may then re-offer, advancing from `COUNTERED` back to `OFFERED`
    with a fresh `offered_units` of at least 1 (again subject to the ownership check) — a
    negotiation loop that may repeat."

    Design: Difficulty/non_linear_state_machine/mutual_aid_offer_counter_negotiation_cycle
    """
    inc = create_activated_incident(name="Regional Flood", hazard_type="FLOOD")
    jur = create_jurisdiction(name="North County")
    ma = create_mutual_aid_request(inc["id"], jur["id"], resource_type="PERSONNEL", requested_units=5)
    offer_mutual_aid(ma["id"], jur["id"], offered_units=4)
    counter_mutual_aid(ma["id"], countered_units=6)
    reoffered = validate_success(
        api.transition_mutual_aid_request(
            ma["id"], {"to_status": "OFFERED", "offered_units": 5},
            make_jurisdiction_liaison_headers(jur["id"]),
        )
    )
    assert reoffered["offered_units"] == 5, f"expected offered_units 5, got {reoffered['offered_units']}"


# ─── Corner: rbac / mutual_aid_offer_by_wrong_jurisdiction_owner ───
def test_offer_by_non_owning_liaison_rejected(api):
    """PRD §2.1: "A liaison whose `X-User-ID` does not match the `to_jurisdiction_id` of the
    mutual-aid request they are acting on is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/mutual_aid_offer_by_wrong_jurisdiction_owner
    """
    inc = create_activated_incident(name="Owner Ctx", hazard_type="FLOOD")
    jur1 = create_jurisdiction(name="Target Jur")
    jur2 = create_jurisdiction(name="Other Jur")
    ma = create_mutual_aid_request(inc["id"], jur1["id"], resource_type="PERSONNEL", requested_units=3)
    validate_error(
        api.transition_mutual_aid_request(
            ma["id"], {"to_status": "OFFERED", "offered_units": 3},
            make_jurisdiction_liaison_headers(jur2["id"]),
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )

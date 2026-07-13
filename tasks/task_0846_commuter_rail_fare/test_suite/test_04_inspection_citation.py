"""Onboard inspection, fare upgrades, citations, and the revocation cascade."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_passenger_headers,
)
from test_helpers import fixtures as fx
from test_helpers.fixtures import CONDUCTOR


def _upgrade_scenario(api, observed_zone, observed_product):
    """Buy+activate a 1->3 PEAK ticket, then inspect at observed_zone.
    observed_product is a (dest, base, peak) tuple for the observed-zone product."""
    fx.set_clock(api)
    fp13 = fx.create_fare_product(api, origin_zone=1, destination_zone=3,
                                  base_fare_cents=1000, peak_surcharge_cents=300)
    dest, base, peak = observed_product
    fx.create_fare_product(api, origin_zone=1, destination_zone=dest,
                           base_fare_cents=base, peak_surcharge_cents=peak)
    pax = fx.create_passenger(api)
    tkt = fx.purchase_ticket(api, pax["id"], fp13["id"], "PEAK")
    fx.activate_ticket(api, tkt["id"], pax["id"])
    insp = fx.create_inspection(api, pax["id"], observed_zone, ticket_id=tkt["id"])
    return pax, tkt, insp


# ==========================================================================
# cross_entity_state_dependency / upgrade_depends_on_inspection_result
# ==========================================================================

def test_upgrade_charges_fare_and_extends_ticket(api):
    """PRD 3.5: "The `upgrade_fare_cents` collected is computed by pricing the product for
    the ticket's origin zone, the observed destination zone, and the ticket's own ticket
    type: take that product's base fare, add its peak surcharge only when the ticket's
    travel period is peak, subtract the ticket's existing purchase price, floor the result
    at zero, and then add the flat onboard surcharge of 200 cents."

    Design: Difficulty/cross_entity_state_dependency/upgrade_depends_on_inspection_result
    """
    pax, tkt, insp = _upgrade_scenario(api, 5, (5, 1800, 400))
    assert insp["result"] == "UPGRADE_REQUIRED"
    upg = validate_success(
        api.create_upgrade({"inspection_id": insp["id"], "ticket_id": tkt["id"]}, CONDUCTOR), 201
    )
    assert upg["upgrade_fare_cents"] == 1100  # (1800+400) - 1300 + 200
    assert fx.get_ticket(api, tkt["id"])["destination_zone"] == 5


def test_upgrade_records_from_and_to_zone(api):
    """PRD 3.5: "The upgrade records the ticket's prior destination as `from_zone` and the
    inspection's observed zone as `to_zone`, then overwrites the ticket's `destination_zone`
    to that observed zone and advances the ticket's `version`."

    Design: Difficulty/cross_entity_state_dependency/upgrade_depends_on_inspection_result
    """
    pax, tkt, insp = _upgrade_scenario(api, 5, (5, 1800, 400))
    upg = validate_success(
        api.create_upgrade({"inspection_id": insp["id"], "ticket_id": tkt["id"]}, CONDUCTOR), 201
    )
    assert upg["from_zone"] == 3
    assert upg["to_zone"] == 5


# ==========================================================================
# boundary_precision_check / upgrade_rejected_when_observed_zone_equals_destination
# ==========================================================================

def test_upgrade_rejected_when_observed_zone_equals_destination(api):
    """PRD 3.5: "The result is `VALID` when the presented ticket genuinely covers the
    observed travel; `UPGRADE_REQUIRED` when a valid ticket is presented but the observed
    destination zone lies beyond the ticket's destination zone"
    PRD 3.5: "The referenced inspection must have result `UPGRADE_REQUIRED`, or the request
    fails with `ERR_UPGRADE_NOT_REQUIRED`"

    Design: Difficulty/boundary_precision_check/upgrade_rejected_when_observed_zone_equals_destination
    """
    pax, tkt, insp = _upgrade_scenario(api, 3, (3, 1000, 300))
    assert insp["result"] == "VALID"
    resp = api.create_upgrade({"inspection_id": insp["id"], "ticket_id": tkt["id"]}, CONDUCTOR)
    validate_error(resp, ApiErrorId.ERR_UPGRADE_NOT_REQUIRED.value)


def test_upgrade_accepted_when_observed_zone_beyond_destination(api):
    """PRD 3.5: "`UPGRADE_REQUIRED` when a valid ticket is presented but the observed
    destination zone lies beyond the ticket's destination zone"
    PRD 3.5: "a conductor collects an onboard upgrade by referencing the `inspection_id` and
    the `ticket_id` being upgraded."

    Design: Difficulty/boundary_precision_check/upgrade_rejected_when_observed_zone_equals_destination
    """
    pax, tkt, insp = _upgrade_scenario(api, 4, (4, 1500, 350))
    assert insp["result"] == "UPGRADE_REQUIRED"
    upg = validate_success(
        api.create_upgrade({"inspection_id": insp["id"], "ticket_id": tkt["id"]}, CONDUCTOR), 201
    )
    assert upg["upgrade_fare_cents"] == 750  # (1500+350) - 1300 + 200
    assert fx.get_ticket(api, tkt["id"])["destination_zone"] == 4


# ==========================================================================
# non_linear_state_machine / citation_branches_contested_to_dismissed
# ==========================================================================

def test_contested_citation_dismissed_reverses_evasion_count(api):
    """PRD 3.6: "the citation moves to the terminal `DISMISSED` state"
    PRD 3.6: "the passenger's `evasion_count` is decremented by one as a compensating
    reversal, advancing the passenger's `version`."
    PRD 3.6: "Only dismissal reverses the evasion count; upholding does not."

    Design: Difficulty/non_linear_state_machine/citation_branches_contested_to_dismissed
    """
    pax_id, insp, cit = fx.setup_evasion_citation(api)
    validate_success(api.contest_citation(cit["id"], {"grounds": "valid ticket shown"},
                                           make_passenger_headers(pax_id)), 200)
    resolved = validate_success(
        api.resolve_citation(cit["id"], {"decision": "DISMISSED"}, fx.ADMIN), 200
    )
    assert resolved["status"] == "DISMISSED"
    assert resolved["resolution_decision"] == "DISMISSED"
    assert fx.get_passenger(api, pax_id)["evasion_count"] == 0


def test_contested_citation_upheld_does_not_reverse_evasion_count(api):
    """PRD 3.6: "When the decision upholds the citation, the citation's
    `resolution_decision` is set to `UPHELD`, it moves to `UPHELD`, and its `version`
    advances"
    PRD 3.6: "Only dismissal reverses the evasion count; upholding does not."

    Design: Difficulty/non_linear_state_machine/citation_branches_contested_to_dismissed
    """
    pax_id, insp, cit = fx.setup_evasion_citation(api)
    validate_success(api.contest_citation(cit["id"], {"grounds": "no proof"},
                                          make_passenger_headers(pax_id)), 200)
    resolved = validate_success(
        api.resolve_citation(cit["id"], {"decision": "UPHELD"}, fx.ADMIN), 200
    )
    assert resolved["status"] == "UPHELD"
    assert resolved["resolution_decision"] == "UPHELD"
    assert fx.get_passenger(api, pax_id)["evasion_count"] == 1


# ==========================================================================
# transitive_cascade / citation_issue_to_evasion_count_to_eligibility_revoked_depth3
# ==========================================================================

def _raise_to_third_citation(api):
    """STUDENT-approved passenger; issue two citations (evasion_count -> 2) and return the
    passenger plus the standing third EVASION inspection, ready to issue the crossing
    citation."""
    pax, app = fx.setup_reduced_fare_passenger(api, category="STUDENT", dob="2005-01-01")
    for _ in range(2):
        insp = fx.create_inspection(api, pax["id"], 3)
        fx.issue_citation(api, insp["id"], pax["id"])
    insp3 = fx.create_inspection(api, pax["id"], 3)
    return pax, app, insp3


def test_third_citation_revokes_reduced_fare_eligibility(api):
    """PRD 3.6: "if that increment brings the evasion count to at least the revocation
    threshold of 3 and the passenger holds an approved reduced-fare application, that
    application is moved to `REVOKED`, the passenger's reduced-fare category is cleared, and
    `reduced_fare_valid_until` is nulled — all within the same request."

    Design: Difficulty/transitive_cascade/citation_issue_to_evasion_count_to_eligibility_revoked_depth3
    """
    pax, app, insp3 = _raise_to_third_citation(api)
    fx.issue_citation(api, insp3["id"], pax["id"])
    passenger = fx.get_passenger(api, pax["id"])
    assert passenger["evasion_count"] == 3
    assert passenger["reduced_fare_category"] == "NONE"
    assert passenger["reduced_fare_valid_until"] is None
    assert fx.get_application(api, app["id"])["status"] == "REVOKED"


def test_third_citation_penalty_uses_repeat_multiplier(api):
    """PRD 3.6: "a repeat multiplier of 2 applies when that prior count is at least 2, and a
    multiplier of 1 applies otherwise, so the `base_penalty_cents` is the base evasion
    penalty of 5000 cents times that multiplier. The `total_penalty_cents` is that base
    penalty plus the `fare_shortfall_cents` copied from the inspection."

    Design: Difficulty/transitive_cascade/citation_issue_to_evasion_count_to_eligibility_revoked_depth3
    """
    pax, app, insp3 = _raise_to_third_citation(api)
    cit3 = fx.issue_citation(api, insp3["id"], pax["id"])
    assert cit3["base_penalty_cents"] == 10000  # 5000 * 2 (prior count 2)
    assert cit3["total_penalty_cents"] == 11000  # 10000 + 1000 evasion shortfall


# ==========================================================================
# Corner: citation / upgrade guards
# ==========================================================================

def test_upgrade_ticket_mismatch_returns_error(api):
    """PRD 3.5: "the supplied ticket must be the same one the inspection recorded, or it
    fails with `ERR_UPGRADE_TICKET_MISMATCH`."

    Design: Corner/validations/upgrade_ticket_mismatch_returns_error
    """
    fx.set_clock(api)
    fp = fx.create_fare_product(api)
    fx.create_fare_product(api, origin_zone=1, destination_zone=5,
                           base_fare_cents=1800, peak_surcharge_cents=400)
    pax = fx.create_passenger(api)
    tkt_a = fx.purchase_ticket(api, pax["id"], fp["id"], "PEAK")
    tkt_b = fx.purchase_ticket(api, pax["id"], fp["id"], "PEAK")
    fx.activate_ticket(api, tkt_a["id"], pax["id"])
    insp = fx.create_inspection(api, pax["id"], 5, ticket_id=tkt_a["id"])
    resp = api.create_upgrade({"inspection_id": insp["id"], "ticket_id": tkt_b["id"]}, CONDUCTOR)
    validate_error(resp, ApiErrorId.ERR_UPGRADE_TICKET_MISMATCH.value)


def test_citation_on_valid_inspection_returns_no_evasion(api):
    """PRD 3.6: "The inspection must have result `EVASION`, or issuance fails with
    `ERR_NO_EVASION_FOUND`"

    Design: Corner/validations/citation_on_valid_inspection_returns_no_evasion
    """
    fx.set_clock(api)
    fp = fx.create_fare_product(api)
    pax = fx.create_passenger(api)
    tkt = fx.purchase_ticket(api, pax["id"], fp["id"], "PEAK")
    fx.activate_ticket(api, tkt["id"], pax["id"])
    insp = fx.create_inspection(api, pax["id"], 3, ticket_id=tkt["id"])  # observed==dest -> VALID
    resp = api.create_citation({"inspection_id": insp["id"], "passenger_id": pax["id"]}, CONDUCTOR)
    validate_error(resp, ApiErrorId.ERR_NO_EVASION_FOUND.value)


def test_pay_dismissed_citation_returns_invalid_state(api):
    """PRD 3.6: "They may pay the citation, permitted while it is `ISSUED` or `UPHELD`"
    PRD 3.6: "An attempt to pay or contest from a state that does not permit the transition
    fails with `ERR_INVALID_CITATION_STATE`."

    Design: Corner/state_machines/pay_dismissed_citation_returns_invalid_state
    """
    pax_id, insp, cit = fx.setup_evasion_citation(api)
    validate_success(api.contest_citation(cit["id"], {"grounds": "g"},
                                          make_passenger_headers(pax_id)), 200)
    validate_success(api.resolve_citation(cit["id"], {"decision": "DISMISSED"}, fx.ADMIN), 200)
    resp = api.pay_citation(cit["id"], make_passenger_headers(pax_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_CITATION_STATE.value)

"""Gates where one entity's state stops an operation on another.

An offer is refused because the landowner was flagged do-not-contact, a deal cannot leave
origination because a roster write staled the valuation it pinned, a stream that was never
acquired cannot be pledged, and a pledge cannot be released out from under the advances a
lender has already drawn against the facility's borrowing base.
"""

from test_helpers import (
    ApiErrorId,
    CarrierCreditTier,
    TenancyType,
    add_tenancy,
    approve_valuation,
    assert_borrowing_base,
    assert_pledge_eligible_value,
    build_chain,
    bps_of,
    closed_deal,
    create_facility,
    create_portfolio,
    create_valuation,
    draw_advance,
    factories,
    read_facility,
    read_lease_stream,
    validate_error,
    validate_paginated,
    validate_success,
)

COLOCATION_TENANCY = {
    "carrier_name": "Crestline Mobility",
    "carrier_credit_tier": CarrierCreditTier.INVESTMENT_GRADE.value,
    "tenancy_type": TenancyType.COLOCATION.value,
    "monthly_rent_share_cents": 90_000,
    "term_end_date": "2034-06-30",
}


def _offer_by_id(api, deal_id, offer_id, headers):
    """Offers are read through the deal's offer collection."""
    offers, _meta = validate_paginated(api.list_offers(deal_id, headers=headers))
    matches = [row for row in offers if row["id"] == offer_id]
    assert matches, f"offer {offer_id} is missing from the deal's offer collection"
    return matches[0]


# ===========================================================================
# A landowner flagged do-not-contact blocks the send of an otherwise valid offer
# ===========================================================================


def test_offer_send_refused_while_the_landowner_is_flagged_do_not_contact(api, analyst_headers):
    """Suppressing outreach on the landowner blocks the send of a DRAFT offer whose own deal,
    valuation and portfolio are all in good standing.

    PRD section 3.2: While a landowner sits at `DO_NOT_CONTACT`, no offer may be sent to them and no deal on their stream may begin outreach — both attempts are refused with `ERR_LANDOWNER_DO_NOT_CONTACT`.

    Design: Difficulty/cross_entity_state_dependency/offer_send_blocked_by_landowner_do_not_contact_flag
    """
    scenario = build_chain(api, "offer_draft")
    suppressed = validate_success(
        api.update_landowner(scenario.landowner_id, {"suppress_outreach": True}, headers=analyst_headers)
    )
    assert suppressed["outreach_status"] == "DO_NOT_CONTACT"

    resp = api.transition_offer(scenario.offer_id, {"action": "SEND"}, headers=analyst_headers)
    validate_error(resp, ApiErrorId.ERR_LANDOWNER_DO_NOT_CONTACT.value)

    offer = _offer_by_id(api, scenario.deal_id, scenario.offer_id, analyst_headers)
    assert offer["status"] == "DRAFT"
    assert offer.get("sent_at") is None
    assert offer["round_number"] == 0

    deal = validate_success(api.get_deal(scenario.deal_id, headers=analyst_headers))
    assert deal["stage"] == "OUTREACH"
    assert deal["negotiation_rounds"] == 0

    landowner = validate_success(api.get_landowner(scenario.landowner_id, headers=analyst_headers))
    assert landowner["outreach_status"] == "DO_NOT_CONTACT"


def test_offer_send_succeeds_once_landowner_outreach_suppression_is_lifted(api, analyst_headers):
    """Clearing the suppression flag restores the landowner to the value the progression implies,
    and the very same DRAFT offer then sends.

    PRD section 3.2: Setting `suppress_outreach` to true forces `outreach_status` to `DO_NOT_CONTACT`, which is the one value the progression logic never produces on its own; setting it back to false restores whatever value the offer and deal progression implies.

    PRD section 3.5: Sending stamps `sent_at` from the current instant, increments the deal's `negotiation_rounds` and then copies the new count into the offer's `round_number`, moves the deal `OUTREACH → NEGOTIATION`, and lifts the landowner's `outreach_status` from `NEW` to `CONTACTED` if it was still `NEW`.

    Design: Difficulty/cross_entity_state_dependency/offer_send_blocked_by_landowner_do_not_contact_flag
    """
    scenario = build_chain(api, "offer_draft")
    validate_success(
        api.update_landowner(scenario.landowner_id, {"suppress_outreach": True}, headers=analyst_headers)
    )
    blocked = api.transition_offer(scenario.offer_id, {"action": "SEND"}, headers=analyst_headers)
    validate_error(blocked, ApiErrorId.ERR_LANDOWNER_DO_NOT_CONTACT.value)

    restored = validate_success(
        api.update_landowner(scenario.landowner_id, {"suppress_outreach": False}, headers=analyst_headers)
    )
    assert restored["outreach_status"] == "NEW"

    sent = validate_success(api.transition_offer(scenario.offer_id, {"action": "SEND"}, headers=analyst_headers))
    assert sent["status"] == "SENT"
    assert sent["round_number"] == 1
    assert sent["sent_at"] is not None

    deal = validate_success(api.get_deal(scenario.deal_id, headers=analyst_headers))
    assert deal["stage"] == "NEGOTIATION"
    assert deal["negotiation_rounds"] == 1

    landowner = validate_success(api.get_landowner(scenario.landowner_id, headers=analyst_headers))
    assert landowner["outreach_status"] == "CONTACTED"


# ===========================================================================
# A staled pinned valuation blocks the deal's departure from origination
# ===========================================================================


def test_outreach_refused_when_a_roster_write_stales_the_pinned_valuation(api, analyst_headers):
    """A colocation added after the deal was opened lifts the stream's quality score, which stales
    the approved valuation the deal pinned, so the deal can no longer start outreach.

    PRD section 3.3: It also invalidates pricing: every valuation on that stream in `DRAFT` or `APPROVED` is moved to `STALE`, because its snapshotted score no longer matches the live score.

    PRD section 3.4: A deal pinning a stale valuation cannot advance beyond `ORIGINATION`; the attempt is refused with `ERR_VALUATION_STALE`, and an attempt to start outreach on a valuation still in `DRAFT` is refused with `ERR_VALUATION_NOT_APPROVED`.

    Design: Difficulty/cross_entity_state_dependency/deal_outreach_blocked_by_stale_pinned_valuation
    """
    scenario = build_chain(api, "deal")
    assert scenario["valuation"]["status"] == "APPROVED"
    assert scenario["valuation"]["tenancy_quality_score_snapshot"] == 40

    add_tenancy(api, scenario.lease_stream_id, **COLOCATION_TENANCY)
    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["tenancy_quality_score"] == 64

    resp = api.start_outreach(scenario.deal_id, headers=analyst_headers)
    validate_error(resp, ApiErrorId.ERR_VALUATION_STALE.value)

    valuations, _meta = validate_paginated(
        api.list_valuations(scenario.lease_stream_id, headers=analyst_headers)
    )
    pinned = [row for row in valuations if row["id"] == scenario.valuation_id][0]
    assert pinned["status"] == "STALE"
    assert pinned["tenancy_quality_score_snapshot"] == 40

    deal = validate_success(api.get_deal(scenario.deal_id, headers=analyst_headers))
    assert deal["stage"] == "ORIGINATION"
    assert read_lease_stream(api, scenario.lease_stream_id)["acquisition_status"] == "PROSPECT"


def test_outreach_starts_when_the_pinned_valuation_is_still_approved(api, analyst_headers):
    """With no roster write behind it the pinned valuation stays approved, and the same deal starts
    outreach and pushes its stream out of the funnel.

    PRD section 3.5: Starting outreach moves the deal `ORIGINATION → OUTREACH`, and is permitted only when the pinned valuation's `status` is `APPROVED` and the landowner is not at `DO_NOT_CONTACT`.

    PRD section 3.2: When a deal on the stream reaches outreach, `PROSPECT → UNDER_OFFER`.

    Design: Difficulty/cross_entity_state_dependency/deal_outreach_blocked_by_stale_pinned_valuation
    """
    scenario = build_chain(api, "deal")
    assert scenario["valuation"]["status"] == "APPROVED"
    assert read_lease_stream(api, scenario.lease_stream_id)["tenancy_quality_score"] == 40

    deal = validate_success(api.start_outreach(scenario.deal_id, headers=analyst_headers))
    assert deal["stage"] == "OUTREACH"
    assert deal["valuation_id"] == scenario.valuation_id
    assert read_lease_stream(api, scenario.lease_stream_id)["acquisition_status"] == "UNDER_OFFER"


def test_outreach_still_refused_after_a_fresher_valuation_is_approved_on_the_stream(api, analyst_headers):
    """Pricing the stream again at its new score does not rescue the deal: it answers to the stale
    valuation it pinned at creation, not to whichever valuation is currently approved.

    PRD section 3.5: If a fresher valuation is later approved on the same stream, this deal continues to answer to the one it pinned — that is what makes the guardrail, the segregation-of-duties check, and the staleness check all deterministic.

    PRD section 3.4: A deal pinning a stale valuation cannot advance beyond `ORIGINATION`; the attempt is refused with `ERR_VALUATION_STALE`, and an attempt to start outreach on a valuation still in `DRAFT` is refused with `ERR_VALUATION_NOT_APPROVED`.

    Design: Difficulty/cross_entity_state_dependency/deal_outreach_blocked_by_stale_pinned_valuation
    """
    scenario = build_chain(api, "deal")
    add_tenancy(api, scenario.lease_stream_id, **COLOCATION_TENANCY)

    fresh = create_valuation(api, scenario.lease_stream_id)
    fresh = approve_valuation(api, fresh["id"])
    assert fresh["status"] == "APPROVED"
    assert fresh["tenancy_quality_score_snapshot"] == 64

    resp = api.start_outreach(scenario.deal_id, headers=analyst_headers)
    validate_error(resp, ApiErrorId.ERR_VALUATION_STALE.value)

    deal = validate_success(api.get_deal(scenario.deal_id, headers=analyst_headers))
    assert deal["valuation_id"] == scenario.valuation_id
    assert deal["stage"] == "ORIGINATION"

    valuations, _meta = validate_paginated(
        api.list_valuations(scenario.lease_stream_id, headers=analyst_headers)
    )
    pinned = [row for row in valuations if row["id"] == scenario.valuation_id][0]
    assert pinned["status"] == "STALE"


# ===========================================================================
# A stream that is not acquired cannot be pledged into a healthy facility
# ===========================================================================


def test_pledge_refused_for_a_prospect_stream_that_was_never_acquired(api, treasury_headers):
    """A priced but unacquired stream cannot be posted as collateral, even though the facility is
    compliant and the pinned facility version is current.

    PRD section 3.9: The stream's `acquisition_status` must be `ACQUIRED`, or the request is refused with `ERR_STREAM_NOT_ACQUIRED`.

    Design: Difficulty/cross_entity_state_dependency/pledge_rejected_when_lease_stream_not_acquired
    """
    scenario = build_chain(api, "valuation_approved")
    portfolio = create_portfolio(api)
    facility = create_facility(api, portfolio["id"])
    assert read_lease_stream(api, scenario.lease_stream_id)["acquisition_status"] == "PROSPECT"

    payload = factories.pledge_payload(scenario.lease_stream_id, facility["version"])
    resp = api.create_pledge(facility["id"], payload, headers=treasury_headers)
    validate_error(resp, ApiErrorId.ERR_STREAM_NOT_ACQUIRED.value)

    after = read_facility(api, facility["id"])
    assert after["pledged_eligible_total_cents"] == 0
    assert after["borrowing_base_cents"] == 0
    assert after["pledged_stream_count"] == 0
    assert after["compliance_state"] == "COMPLIANT"

    pledges, meta = validate_paginated(
        api.list_collateral_pledges({"facility_id": facility["id"]}, headers=treasury_headers)
    )
    assert meta["total_count"] == 0
    assert pledges == []


def test_pledge_refused_while_the_stream_is_only_under_offer(api, treasury_headers):
    """A stream whose deal has merely reached outreach is `UNDER_OFFER`, not `ACQUIRED`, so the
    pledge is still refused.

    PRD section 2.8: **Stream acquired for servicing** — pledges and amendment events require the stream's `acquisition_status` to be `ACQUIRED`; otherwise `ERR_STREAM_NOT_ACQUIRED` (422).

    Design: Difficulty/cross_entity_state_dependency/pledge_rejected_when_lease_stream_not_acquired
    """
    scenario = build_chain(api, "outreach")
    facility = create_facility(api, scenario.portfolio_id)
    assert read_lease_stream(api, scenario.lease_stream_id)["acquisition_status"] == "UNDER_OFFER"

    payload = factories.pledge_payload(scenario.lease_stream_id, facility["version"])
    resp = api.create_pledge(facility["id"], payload, headers=treasury_headers)
    validate_error(resp, ApiErrorId.ERR_STREAM_NOT_ACQUIRED.value)

    after = read_facility(api, facility["id"])
    assert after["pledged_stream_count"] == 0
    assert after["pledged_eligible_total_cents"] == 0
    assert after["borrowing_base_cents"] == 0


def test_pledge_admitted_once_the_stream_has_been_acquired_by_a_closed_deal(api, treasury_headers):
    """Closing the deal moves the stream to `ACQUIRED`, and the identical pledge request is then
    admitted at the stream's approved model value.

    PRD section 3.7: The stream moves to `acquisition_status` `ACQUIRED` and `servicing_status` `PERFORMING`.

    PRD section 3.9: `basis_value_cents` follows that snapshot: under `MARK_TO_MODEL` it is the stream's `APPROVED` valuation's `value_cents`; under `COST_BASIS` it is the closed deal's `total_commitment_cents` for that stream.

    Design: Difficulty/cross_entity_state_dependency/pledge_rejected_when_lease_stream_not_acquired
    """
    scenario = closed_deal(api)
    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["acquisition_status"] == "ACQUIRED"
    assert stream["servicing_status"] == "PERFORMING"

    facility = create_facility(api, scenario.portfolio_id)
    payload = factories.pledge_payload(scenario.lease_stream_id, facility["version"])
    pledge = validate_success(api.create_pledge(facility["id"], payload, headers=treasury_headers), 201)

    assert pledge["status"] == "PLEDGED"
    assert pledge["basis_value_cents"] == scenario["valuation"]["value_cents"]
    assert pledge["haircut_bps"] == 0
    assert_pledge_eligible_value(pledge)

    after = read_facility(api, facility["id"])
    assert after["pledged_stream_count"] == 1
    assert after["pledged_eligible_total_cents"] == pledge["eligible_value_cents"]
    assert_borrowing_base(after)


# ===========================================================================
# Outstanding advances on the facility block the release of its collateral
# ===========================================================================


def test_pledge_release_refused_while_advances_exceed_the_post_release_borrowing_base(api, treasury_headers):
    """Releasing the facility's only collateral would drop the borrowing base below the advances
    already drawn, so the release is refused and the pledge stays put.

    PRD section 3.9: Releasing from `PLEDGED → RELEASED` is permitted only when the facility's `compliance_state` would still be `COMPLIANT` after the release recomputation; a release that would leave `advances_outstanding_cents` above the recomputed `borrowing_base_cents` is refused with `ERR_BORROWING_BASE_DEFICIT`, because a lender cannot be stripped of collateral it has already advanced against.

    Design: Difficulty/cross_entity_state_dependency/pledge_release_blocked_by_facility_borrowing_base_deficit
    """
    scenario = closed_deal(api)
    facility = create_facility(api, scenario.portfolio_id)
    payload = factories.pledge_payload(scenario.lease_stream_id, facility["version"])
    pledge = validate_success(api.create_pledge(facility["id"], payload, headers=treasury_headers), 201)

    funded = read_facility(api, facility["id"])
    expected_base = bps_of(pledge["eligible_value_cents"], funded["advance_rate_bps"])
    assert funded["borrowing_base_cents"] == expected_base
    drawn = expected_base - 7_557
    funded = draw_advance(api, facility["id"], drawn)
    assert funded["advances_outstanding_cents"] == drawn
    assert funded["compliance_state"] == "COMPLIANT"

    resp = api.release_collateral_pledge(pledge["id"], headers=treasury_headers)
    validate_error(resp, ApiErrorId.ERR_BORROWING_BASE_DEFICIT.value)

    held = validate_success(api.get_collateral_pledge(pledge["id"], headers=treasury_headers))
    assert held["status"] == "PLEDGED"
    assert held["eligible_value_cents"] == pledge["eligible_value_cents"]

    after = read_facility(api, facility["id"])
    assert after["pledged_eligible_total_cents"] == pledge["eligible_value_cents"]
    assert after["borrowing_base_cents"] == expected_base
    assert after["advances_outstanding_cents"] == drawn
    assert after["pledged_stream_count"] == 1
    assert after["compliance_state"] == "COMPLIANT"


def test_pledge_release_succeeds_while_the_facility_carries_no_advances(api, treasury_headers):
    """With nothing drawn on the facility the post-release borrowing base of zero is still
    compliant, so the same release goes through and strips the collateral out.

    PRD section 3.9: A release sets `eligible_value_cents` to zero, recomputes the facility's `pledged_eligible_total_cents` and `borrowing_base_cents`, and decrements `pledged_stream_count`.

    PRD section 3.9: `compliance_state` is `BORROWING_BASE_DEFICIT` whenever `advances_outstanding_cents` is strictly greater than `borrowing_base_cents`, and `COMPLIANT` otherwise.

    Design: Difficulty/cross_entity_state_dependency/pledge_release_blocked_by_facility_borrowing_base_deficit
    """
    scenario = closed_deal(api)
    facility = create_facility(api, scenario.portfolio_id)
    payload = factories.pledge_payload(scenario.lease_stream_id, facility["version"])
    pledge = validate_success(api.create_pledge(facility["id"], payload, headers=treasury_headers), 201)
    assert read_facility(api, facility["id"])["advances_outstanding_cents"] == 0

    released = validate_success(api.release_collateral_pledge(pledge["id"], headers=treasury_headers))
    assert released["status"] == "RELEASED"
    assert released["eligible_value_cents"] == 0

    after = read_facility(api, facility["id"])
    assert after["pledged_eligible_total_cents"] == 0
    assert after["borrowing_base_cents"] == 0
    assert after["pledged_stream_count"] == 0
    assert after["compliance_state"] == "COMPLIANT"

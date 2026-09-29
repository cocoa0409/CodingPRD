"""Reversals that must land exactly where they started, by money and by count."""
from test_helpers import (
    ApiErrorId,
    DESTINATION_OPT_OUT_WINDOW_HOURS,
    FOLIO_CHARGES_SUBTOTAL_CENTS,
    FOLIO_DESTINATION_AMOUNT_CENTS,
    FOLIO_DESTINATION_TAX_CENTS,
    FOLIO_TAX_TOTAL_CENTS,
    FOLIO_TOTAL_CENTS,
    OCCUPANCY_TAX_RATE_BPS,
    QUOTE_FOLIO_VARIANCE_CENTS,
    add_booking,
    add_channel,
    add_draft_profile,
    add_inquiry,
    assert_booking_mirrors_folio,
    assert_folio_ledger_conservation,
    assert_folio_sequence_integrity,
    assert_quote_folio_variance,
    deploy_profile,
    find_line_by_sequence,
    read_booking,
    read_folio,
    read_folio_lines,
    read_profile,
    read_property,
    setup_deployed_profile,
    setup_granted_opt_out,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, AGENT, COMPLIANCE, LIAISON, LIAISON_2

CREDITED_TOTAL_CENTS = 148372
CREDITED_TAX_TOTAL_CENTS = 17202
REBILLED_CHARGES_SUBTOTAL_CENTS = 143130


def test_granting_an_opt_out_appends_a_credit_and_leaves_the_charge_line_alone(api):
    """The credit mirrors the billed line exactly and nothing is edited in place.

    PRD 3.6: "The grant appends exactly one `FEE_CREDIT` line at the next
    `sequence_no` ... Its `amount_cents` is the source `MANDATORY_FEE` line's
    `amount_cents` — the stay-aggregation figure the folio actually billed, never
    the quote's per-night-rounded figure — carried positive. Its `tax_cents` is
    the **negation** of the source line's `tax_cents`, and its `tax_rate_bps` is
    the source line's rate. **No new rounding occurs** ... Its
    `taxability_determination` is `TAXABLE_IF_MANDATORY_WAIVED` when the fee
    code's rule is `TAXABLE_IF_MANDATORY`".

    Design: Difficulty/compensating_invariant/opt_out_grant_then_revoke_restores_guest_out_of_pocket_to_the_cent
    """
    env = setup_granted_opt_out()
    opt_out = env["opt_out"]
    folio = read_folio(env["folio"]["id"])
    lines = read_folio_lines(folio["id"])

    assert opt_out["status"] == "GRANTED"
    assert opt_out["requested_hours_before_arrival"] == 960
    assert opt_out["requested_hours_before_arrival"] >= (
        DESTINATION_OPT_OUT_WINDOW_HOURS
    )
    assert opt_out["credit_cents"] == FOLIO_DESTINATION_AMOUNT_CENTS
    assert opt_out["tax_credit_cents"] == FOLIO_DESTINATION_TAX_CENTS
    assert opt_out["credit_line_sequence_no"] == 5

    credit = find_line_by_sequence(lines, 5)
    assert credit["line_type"] == "FEE_CREDIT"
    assert credit["fee_id"] == env["fees"]["DESTINATION"]["id"]
    assert credit["amount_cents"] == FOLIO_DESTINATION_AMOUNT_CENTS
    assert credit["tax_cents"] == -FOLIO_DESTINATION_TAX_CENTS
    assert credit["tax_rate_bps"] == OCCUPANCY_TAX_RATE_BPS
    assert credit["taxability_determination"] == "TAXABLE_IF_MANDATORY_WAIVED"

    # The line the credit reverses is immutable and still reads as billed.
    charged = find_line_by_sequence(lines, 3)
    assert charged["line_type"] == "MANDATORY_FEE"
    assert charged["amount_cents"] == FOLIO_DESTINATION_AMOUNT_CENTS
    assert charged["tax_cents"] == FOLIO_DESTINATION_TAX_CENTS
    assert charged["taxability_determination"] == "TAXABLE_IF_MANDATORY_APPLIED"

    assert folio["status"] == "ADJUSTED"
    assert folio["line_count"] == 5
    assert folio["charges_subtotal_cents"] == FOLIO_CHARGES_SUBTOTAL_CENTS
    assert folio["credits_total_cents"] == FOLIO_DESTINATION_AMOUNT_CENTS
    assert folio["tax_total_cents"] == CREDITED_TAX_TOTAL_CENTS
    assert folio["folio_total_cents"] == CREDITED_TOTAL_CENTS

    booking = read_booking(env["booking"]["id"])
    assert booking["guest_out_of_pocket_cents"] == CREDITED_TOTAL_CENTS
    assert_booking_mirrors_folio(booking, folio)
    assert_folio_ledger_conservation(folio, lines)
    assert_folio_sequence_integrity(folio, lines)


def test_revoking_rebills_beside_the_credit_and_restores_the_total_exactly(api):
    """Six lines, the credit still standing, and the total back at 155152.

    PRD 3.6: "It appends one `FEE_REBILL` line with the same `fee_id`, an
    `amount_cents` equal to the recorded `credit_cents`, a **positive**
    `tax_cents` equal to the recorded `tax_credit_cents`, and the
    `taxability_determination` of the original charged line — not the waived
    determination of the credit. It then resets `credit_cents` to 0,
    `tax_credit_cents` to 0 and `credit_line_sequence_no` to null ... Mutating
    the original `MANDATORY_FEE` line in place would reach the same total while
    destroying the audit trail and breaking the contiguity of `sequence_no`, and
    is forbidden."

    Design: Difficulty/compensating_invariant/opt_out_grant_then_revoke_restores_guest_out_of_pocket_to_the_cent
    """
    env = setup_granted_opt_out()

    revoked = validate_success(api.revoke_opt_out_request(env["opt_out"]["id"], AGENT))

    assert revoked["status"] == "REVOKED"
    assert revoked["credit_cents"] == 0
    assert revoked["tax_credit_cents"] == 0
    assert revoked["credit_line_sequence_no"] is None

    folio = read_folio(env["folio"]["id"])
    lines = read_folio_lines(folio["id"])
    rebill = find_line_by_sequence(lines, 6)
    assert rebill["line_type"] == "FEE_REBILL"
    assert rebill["fee_id"] == env["fees"]["DESTINATION"]["id"]
    assert rebill["amount_cents"] == FOLIO_DESTINATION_AMOUNT_CENTS
    assert rebill["tax_cents"] == FOLIO_DESTINATION_TAX_CENTS
    assert rebill["taxability_determination"] == "TAXABLE_IF_MANDATORY_APPLIED"

    # The credit is not withdrawn; the compensation sits beside it.
    credit = find_line_by_sequence(lines, 5)
    assert credit["line_type"] == "FEE_CREDIT"
    assert credit["amount_cents"] == FOLIO_DESTINATION_AMOUNT_CENTS

    assert folio["status"] == "ADJUSTED"
    assert folio["line_count"] == 6
    assert folio["charges_subtotal_cents"] == REBILLED_CHARGES_SUBTOTAL_CENTS
    assert folio["credits_total_cents"] == FOLIO_DESTINATION_AMOUNT_CENTS
    assert folio["tax_total_cents"] == FOLIO_TAX_TOTAL_CENTS
    assert folio["folio_total_cents"] == FOLIO_TOTAL_CENTS

    booking = read_booking(env["booking"]["id"])
    assert booking["guest_out_of_pocket_cents"] == FOLIO_TOTAL_CENTS
    assert booking["folio_total_cents"] == FOLIO_TOTAL_CENTS
    assert booking["quote_folio_variance_cents"] == QUOTE_FOLIO_VARIANCE_CENTS
    assert_quote_folio_variance(booking)
    assert_booking_mirrors_folio(booking, folio)
    assert_folio_ledger_conservation(folio, lines)
    assert_folio_sequence_integrity(folio, lines)

    # REVOKED is terminal, so the compensation cannot be applied twice.
    validate_error(
        api.revoke_opt_out_request(env["opt_out"]["id"], AGENT),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    reposted = validate_success(api.post_folio(folio["id"], AGENT))
    assert reposted["status"] == "POSTED"
    assert reposted["folio_total_cents"] == FOLIO_TOTAL_CENTS


HELPFUL_GDS = {
    "name": "WorldGDS Terminal",
    "channel_type": "GDS",
    "supports_total_price_display": True,
    "supports_itemization": True,
}
OWNED_SITE = {
    "name": "Mirage Sands Website",
    "channel_type": "OWNED_WEB",
    "supports_total_price_display": True,
    "supports_itemization": True,
}
UNDER_FLOOR_PROFILE = {
    "first_quote_shows_total": True,
    "itemized_at_first_quote": False,
    "disclosure_placement": "CHECKOUT",
}
PARTIAL_MAP = {"RESORT": 6000, "DESTINATION": 5980}
GAP_UNDER_PARTIAL_MAP = 5572


def _docket_over_two_clean_paths(api):
    """Two paths at 100, a confirmed OTA booking, and an OTA-scoped docket."""
    env = setup_deployed_profile()
    gds = add_channel(env, "gds_channel", **HELPFUL_GDS)
    env["profile_gds"] = deploy_profile(env, profile=add_draft_profile(env, channel=gds))
    booking = add_booking(env, disclosed_fee_amounts=PARTIAL_MAP)
    env["booking"] = validate_success(api.confirm_booking(booking["id"], AGENT))
    env["baseline"] = read_property(env["property"]["id"])
    inquiry = add_inquiry(env)
    env["inquiry_at_receipt"] = inquiry
    validate_success(
        api.draft_inquiry_response(
            inquiry["id"], "The operator's account of both booking paths.", LIAISON
        )
    )
    validate_success(api.submit_inquiry_response(inquiry["id"], LIAISON_2))
    env["inquiry"] = validate_success(
        api.require_inquiry_remediation(
            inquiry["id"], "Rebuild the OTA path's first-quote total.", ADMIN
        )
    )
    return env


def test_a_live_docket_and_its_flagging_order_each_count_as_one_obligation(api):
    """The count walks 0 to 1 to 2 while the confirmed booking stays out of it.

    PRD 2.10: "A property's `open_disclosure_obligation_count` must always equal
    the number of its disclosure profiles in `FLAGGED` status, plus the number of
    its bookings whose `disclosure_status` is `DISPUTED` or
    `UNDISCLOSED_CONFIRMED`, plus the number of complaints on those bookings
    whose status is `SUBMITTED`, `UNDER_INVESTIGATION` or `SUBSTANTIATED`, plus
    the number of regulator inquiries on the property whose status is anything
    other than `ACCEPTED` or `WITHDRAWN`."

    Design: Difficulty/compensating_invariant/inquiry_withdraw_restores_obligation_count_and_posture_without_drift
    """
    env = _docket_over_two_clean_paths(api)
    baseline = env["baseline"]

    assert baseline["min_channel_disclosure_score"] == 100
    assert baseline["disclosure_posture"] == "COMPLIANT"
    assert baseline["open_disclosure_obligation_count"] == 0
    assert baseline["aggregate_disclosure_gap_cents"] == 0
    assert env["inquiry_at_receipt"]["status"] == "RECEIVED"

    ordered = env["inquiry"]
    assert ordered["status"] == "REMEDIATION_REQUIRED"
    assert ordered["remediation_round"] == 1
    assert ordered["flagged_profile_ids"] == [env["profile"]["id"]]
    assert ordered["exposure_cents"] == 0

    assert read_profile(env["profile"]["id"])["status"] == "FLAGGED"
    assert read_profile(env["profile_gds"]["id"])["status"] == "DEPLOYED"

    ordered_property = read_property(env["property"]["id"])
    assert ordered_property["min_channel_disclosure_score"] == 0
    assert ordered_property["disclosure_posture"] == "NON_COMPLIANT"
    assert ordered_property["open_disclosure_obligation_count"] == 2
    # A CONFIRMED booking is outside the dispute sweep, so no money is exposed.
    booking = read_booking(env["booking"]["id"])
    assert booking["stay_status"] == "CONFIRMED"
    assert booking["disclosure_status"] == "PENDING_AUDIT"
    assert booking["quote_disclosure_gap_cents"] == GAP_UNDER_PARTIAL_MAP
    assert ordered_property["aggregate_disclosure_gap_cents"] == 0


def test_withdrawing_the_docket_decrements_twice_and_leaves_no_drift(api):
    """Both the docket and the restored path leave the open set, count back to 0.

    PRD 3.8: "It records the reason, transitions every profile id in
    `flagged_profile_ids` that is still `FLAGGED` from `FLAGGED` back to
    `DEPLOYED`, sets `flagged_profile_ids` to the empty array, recomputes the
    property's `min_channel_disclosure_score`, `disclosure_posture` and
    `open_disclosure_obligation_count`, and increments both the property's and
    the docket's `version` by 1 ... when nothing else has changed in the meantime
    the property's score, posture and obligation count must return to their exact
    pre-require-remediation values, with no drift."

    Design: Difficulty/compensating_invariant/inquiry_withdraw_restores_obligation_count_and_posture_without_drift
    """
    env = _docket_over_two_clean_paths(api)
    baseline = env["baseline"]
    booking_before = read_booking(env["booking"]["id"])

    withdrawn = validate_success(
        api.withdraw_inquiry(
            env["inquiry"]["id"], "The regulator stood the docket down.", ADMIN
        )
    )

    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdrawal_reason"] == "The regulator stood the docket down."
    assert withdrawn["flagged_profile_ids"] == []

    restored = read_profile(env["profile"]["id"])
    assert restored["status"] == "DEPLOYED"
    assert restored["disclosure_score"] == 100
    assert restored["confirmed_undisclosed_count"] == 0
    # Returning by withdrawal is not a remediation, so no round was consumed.
    assert restored["remediation_round"] == 0

    after = read_property(env["property"]["id"])
    assert after["min_channel_disclosure_score"] == (
        baseline["min_channel_disclosure_score"]
    )
    assert after["disclosure_posture"] == baseline["disclosure_posture"]
    assert after["open_disclosure_obligation_count"] == 0
    assert after["aggregate_disclosure_gap_cents"] == 0
    # The semantic aggregates are conserved; the concurrency counters are not.
    assert after["version"] > baseline["version"]

    booking_after = read_booking(env["booking"]["id"])
    assert booking_after["version"] == booking_before["version"]
    assert booking_after["disclosure_status"] == "PENDING_AUDIT"

    validate_error(
        api.withdraw_inquiry(env["inquiry"]["id"], "A second stand-down.", ADMIN),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    validate_error(
        api.submit_inquiry_remediation(
            env["inquiry"]["id"], "Reporting a repair on a dead docket.", LIAISON
        ),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    assert read_property(env["property"]["id"])["open_disclosure_obligation_count"] == 0


def test_withdrawal_restores_only_the_paths_this_docket_flagged(api):
    """A path flagged by its own audit stays flagged, so the count settles at 1.

    PRD 3.8: "It restores **exactly** the paths this docket flagged and nothing
    else — a path flagged by a substantiated complaint or by a different docket
    stays flagged". PRD 3.3: "Profiles in `DRAFT` or `RETIRED` are excluded
    entirely ... Within the candidate set each profile contributes an effective
    score: 0 if the profile is `FLAGGED`, regardless of its stored
    `disclosure_score`".

    Design: Difficulty/compensating_invariant/inquiry_withdraw_restores_obligation_count_and_posture_without_drift
    """
    env = setup_deployed_profile()
    owned = add_channel(env, "owned_channel", **OWNED_SITE)
    weak = deploy_profile(
        env, profile=add_draft_profile(env, channel=owned, **UNDER_FLOOR_PROFILE)
    )
    assert weak["disclosure_score"] == 58

    independently_flagged = validate_success(api.audit_profile(weak["id"], COMPLIANCE))
    assert independently_flagged["status"] == "FLAGGED"
    before = read_property(env["property"]["id"])
    assert before["disclosure_posture"] == "NON_COMPLIANT"
    assert before["open_disclosure_obligation_count"] == 1

    inquiry = add_inquiry(env)
    validate_success(
        api.draft_inquiry_response(inquiry["id"], "Operator response.", LIAISON)
    )
    validate_success(api.submit_inquiry_response(inquiry["id"], LIAISON_2))
    ordered = validate_success(
        api.require_inquiry_remediation(
            inquiry["id"], "Repair the OTA path.", ADMIN
        )
    )
    assert ordered["flagged_profile_ids"] == [env["profile"]["id"]]
    assert read_property(env["property"]["id"])["open_disclosure_obligation_count"] == 3

    withdrawn = validate_success(
        api.withdraw_inquiry(inquiry["id"], "Docket stood down.", ADMIN)
    )
    assert withdrawn["flagged_profile_ids"] == []

    assert read_profile(env["profile"]["id"])["status"] == "DEPLOYED"
    assert read_profile(weak["id"])["status"] == "FLAGGED"
    after = read_property(env["property"]["id"])
    assert after["open_disclosure_obligation_count"] == 1
    assert after["min_channel_disclosure_score"] == 0
    assert after["disclosure_posture"] == "NON_COMPLIANT"

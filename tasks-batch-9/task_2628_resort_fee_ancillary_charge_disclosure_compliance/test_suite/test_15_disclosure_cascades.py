"""The two deep cascades: a regulator's order and a substantiated complaint."""
from test_helpers import (
    QUOTED_MANDATORY_FEE_CENTS,
    add_booking,
    add_channel,
    add_complaint,
    add_draft_profile,
    add_inquiry,
    deploy_profile,
    read_booking,
    read_profile,
    read_property,
    setup_deployed_profile,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    AGENT,
    COMPLIANCE,
    COMPLIANCE_2,
    LIAISON,
    LIAISON_2,
    advance_to_posted_folio,
)

WORLD_GDS = {
    "name": "WorldGDS Terminal",
    "channel_type": "GDS",
    "supports_total_price_display": True,
    "supports_itemization": True,
}
PARTIAL_MAP = {"RESORT": 6000, "DESTINATION": 5980}
GAP_UNDER_PARTIAL_MAP = 5572
UNITEMISED_PROFILE = {
    "first_quote_shows_total": True,
    "itemized_at_first_quote": False,
    "disclosure_placement": "RATE_DETAILS",
}


def _two_path_estate(api):
    """Two deployed paths at 100, three bookings, and a submitted docket."""
    env = setup_deployed_profile()
    gds = add_channel(env, "gds_channel", **WORLD_GDS)
    env["profile_gds"] = deploy_profile(
        env, profile=add_draft_profile(env, channel=gds)
    )
    env["b_ota_quoted"] = add_booking(env, disclosed_fee_amounts=PARTIAL_MAP)
    env["b_gds_quoted"] = add_booking(
        env, profile=env["profile_gds"], channel=gds
    )
    confirmed = add_booking(env)
    env["b_ota_confirmed"] = validate_success(
        api.confirm_booking(confirmed["id"], AGENT)
    )
    inquiry = add_inquiry(env)
    validate_success(
        api.draft_inquiry_response(
            inquiry["id"], "The operator's account of each in-scope path.", LIAISON
        )
    )
    env["inquiry"] = validate_success(
        api.submit_inquiry_response(inquiry["id"], LIAISON_2)
    )
    return env


def test_requiring_remediation_flags_only_in_scope_paths_and_drops_the_minimum(api):
    """The docket flags the OTA path alone, and one flag zeroes the minimum.

    PRD 3.8: "Link two transitions every booking path of the inquiry's property
    that is in `DEPLOYED` and whose channel's `channel_type` is in
    `channel_scope` from `DEPLOYED` to `FLAGGED`, appending each id to
    `flagged_profile_ids` in ascending profile `created_at` order; paths on
    out-of-scope channels and paths not currently `DEPLOYED` are untouched. Link
    three recomputes the property's `min_channel_disclosure_score` and
    `disclosure_posture`, and because a `FLAGGED` path contributes 0 to the
    minimum, the posture becomes `NON_COMPLIANT` whenever at least one path was
    flagged."

    Design: Difficulty/transitive_cascade/require_remediation_cascades_inquiry_to_profile_to_property_to_bookings
    """
    env = _two_path_estate(api)
    prop_before = read_property(env["property"]["id"])
    assert prop_before["min_channel_disclosure_score"] == 100
    assert prop_before["disclosure_posture"] == "COMPLIANT"
    assert prop_before["open_disclosure_obligation_count"] == 1
    assert prop_before["aggregate_disclosure_gap_cents"] == 0
    assert env["inquiry"]["exposure_cents"] == 0
    assert env["inquiry"]["flagged_profile_ids"] == []

    inquiry = validate_success(
        api.require_inquiry_remediation(
            env["inquiry"]["id"],
            "Rebuild the OTA booking path so the all-in total appears first.",
            ADMIN,
        )
    )

    assert inquiry["status"] == "REMEDIATION_REQUIRED"
    assert inquiry["remediation_round"] == 1
    assert inquiry["remediation_directive"] == (
        "Rebuild the OTA booking path so the all-in total appears first."
    )
    assert inquiry["flagged_profile_ids"] == [env["profile"]["id"]]

    assert read_profile(env["profile"]["id"])["status"] == "FLAGGED"
    out_of_scope = read_profile(env["profile_gds"]["id"])
    assert out_of_scope["status"] == "DEPLOYED"
    assert out_of_scope["disclosure_score"] == 100

    prop_after = read_property(env["property"]["id"])
    assert prop_after["min_channel_disclosure_score"] == 0
    assert prop_after["disclosure_posture"] == "NON_COMPLIANT"


def test_the_dispute_sweep_is_property_wide_while_exposure_stays_channel_scoped(api):
    """Both quoted bookings are disputed, yet only the OTA gap is exposure.

    PRD 3.8: "Link four then transitions every booking of that property whose
    `stay_status` is `QUOTED` and whose `disclosure_status` is `PENDING_AUDIT` to
    `DISPUTED`." On exposure: "a booking is skipped when its channel's
    `channel_type` is not in `channel_scope` and skipped again when its
    `disclosure_status` is not `DISPUTED` or `UNDISCLOSED_CONFIRMED`; each
    surviving booking contributes its `quote_disclosure_gap_cents`, and
    `exposure_cents` is the plain integer sum of those already-rounded
    per-booking gaps with no re-rounding."

    Design: Difficulty/transitive_cascade/require_remediation_cascades_inquiry_to_profile_to_property_to_bookings
    """
    env = _two_path_estate(api)
    prop_before = read_property(env["property"]["id"])
    confirmed_before = read_booking(env["b_ota_confirmed"]["id"])

    inquiry = validate_success(
        api.require_inquiry_remediation(
            env["inquiry"]["id"], "Repair every in-scope booking path.", ADMIN
        )
    )

    ota_quoted = read_booking(env["b_ota_quoted"]["id"])
    assert ota_quoted["disclosure_status"] == "DISPUTED"
    assert ota_quoted["stay_status"] == "QUOTED"
    assert ota_quoted["quote_disclosure_gap_cents"] == GAP_UNDER_PARTIAL_MAP

    gds_quoted = read_booking(env["b_gds_quoted"]["id"])
    assert gds_quoted["disclosure_status"] == "DISPUTED"
    assert gds_quoted["quote_disclosure_gap_cents"] == QUOTED_MANDATORY_FEE_CENTS

    confirmed_after = read_booking(env["b_ota_confirmed"]["id"])
    assert confirmed_after["disclosure_status"] == "PENDING_AUDIT"
    assert confirmed_after["stay_status"] == "CONFIRMED"
    assert confirmed_after["version"] == confirmed_before["version"]

    prop_after = read_property(env["property"]["id"])
    assert prop_after["aggregate_disclosure_gap_cents"] == 23124
    assert prop_after["open_disclosure_obligation_count"] == 4
    assert prop_after["version"] == prop_before["version"] + 1

    assert inquiry["exposure_cents"] == GAP_UNDER_PARTIAL_MAP
    assert inquiry["exposure_cents"] != 23124


def _posted_stay_beside_a_quoted_sibling(api):
    """One posted stay under-disclosed at quote, plus a silent quoted sibling."""
    env = setup_deployed_profile(profile_overrides=UNITEMISED_PROFILE)
    assert env["profile"]["disclosure_score"] == 65
    env["booking"] = add_booking(env, disclosed_fee_amounts=PARTIAL_MAP)
    env["sibling"] = add_booking(env)
    env["booking"] = validate_success(
        api.confirm_booking(env["booking"]["id"], AGENT)
    )
    advance_to_posted_folio(env)
    return env


def _investigated_pair(api, env):
    """Two complaints on the posted folio, the exempt one already substantiated."""
    first = add_complaint(env, fee_code="WIFI_PREMIUM")
    validate_success(api.investigate_complaint(first["id"], COMPLIANCE))
    env["complaint_first"] = validate_success(
        api.substantiate_complaint(first["id"], COMPLIANCE_2)
    )
    second = add_complaint(
        env,
        fee_code="RESORT",
        complaint_reason="MISSTATED_AMOUNT",
        narrative="I was quoted sixty dollars of resort fee for the whole stay.",
    )
    env["complaint_second"] = validate_success(
        api.investigate_complaint(second["id"], COMPLIANCE)
    )
    return env


def test_substantiation_walks_from_the_complaint_to_the_path_and_flags_it(api):
    """The second substantiation drops the path from exactly 60 to 55 and flags it.

    PRD 3.7: "Substantiation moves the complaint to `SUBSTANTIATED` and drives
    a four-level cascade. Level one writes the complaint's own arithmetic:
    `refund_variant`, `disputed_amount_cents`, `disclosed_amount_cents` and
    `refund_entitlement_cents`. Level two moves the booking's
    `disclosure_status` to `UNDISCLOSED_CONFIRMED`, from `PENDING_AUDIT`, from
    `DISCLOSED` or from `DISPUTED`. Level three increments the booking path's
    `confirmed_undisclosed_count` by 1 and rescores that path. Level four fires
    only conditionally: when the rescored `disclosure_score` is below 60 **and**
    the path is in `DEPLOYED`, the path transitions `DEPLOYED → FLAGGED`".

    Design: Difficulty/transitive_cascade/complaint_substantiation_cascades_complaint_to_booking_to_profile_to_property_to_sibling_booking
    """
    env = _investigated_pair(api, _posted_stay_beside_a_quoted_sibling(api))

    before = read_profile(env["profile"]["id"])
    assert before["confirmed_undisclosed_count"] == 1
    assert before["disclosure_score"] == 60
    assert before["status"] == "DEPLOYED"
    prop_before = read_property(env["property"]["id"])
    assert prop_before["min_channel_disclosure_score"] == 60
    assert prop_before["disclosure_posture"] == "AT_RISK"
    assert prop_before["aggregate_disclosure_gap_cents"] == GAP_UNDER_PARTIAL_MAP
    assert prop_before["open_disclosure_obligation_count"] == 3

    adjudicated = validate_success(
        api.substantiate_complaint(env["complaint_second"]["id"], COMPLIANCE_2)
    )

    assert adjudicated["status"] == "SUBSTANTIATED"
    assert adjudicated["refund_variant"] == "DISCLOSURE_GAP_DIFFERENTIAL"
    assert adjudicated["refund_entitlement_cents"] == 3367

    booking = read_booking(env["booking"]["id"])
    assert booking["disclosure_status"] == "UNDISCLOSED_CONFIRMED"

    after = read_profile(env["profile"]["id"])
    assert after["confirmed_undisclosed_count"] == 2
    assert after["disclosure_score"] == 55
    assert after["status"] == "FLAGGED"


def test_the_flag_reaches_the_property_and_disputes_the_untouched_sibling(api):
    """A complaint about one stay drags a wholly separate booking into dispute.

    PRD 3.7: "the path transitions `DEPLOYED → FLAGGED`, which in turn
    recomputes the property's `min_channel_disclosure_score`,
    `disclosure_posture` and `open_disclosure_obligation_count`. The property's
    `aggregate_disclosure_gap_cents` is recomputed as well, since the booking has
    entered a gap-contributing standing." PRD 3.4 supplies the last link: "A
    booking in `PENDING_AUDIT` whose `stay_status` is still `QUOTED` transitions
    to `DISPUTED` when its property's `disclosure_posture` becomes
    `NON_COMPLIANT`; only unconfirmed quotes are swept this way, and confirmed or
    in-house bookings are deliberately left alone."

    Design: Difficulty/transitive_cascade/complaint_substantiation_cascades_complaint_to_booking_to_profile_to_property_to_sibling_booking
    """
    env = _investigated_pair(api, _posted_stay_beside_a_quoted_sibling(api))
    sibling_before = read_booking(env["sibling"]["id"])
    assert sibling_before["disclosure_status"] == "PENDING_AUDIT"
    assert sibling_before["stay_status"] == "QUOTED"
    assert sibling_before["quote_disclosure_gap_cents"] == QUOTED_MANDATORY_FEE_CENTS

    validate_success(
        api.substantiate_complaint(env["complaint_second"]["id"], COMPLIANCE_2)
    )

    prop = read_property(env["property"]["id"])
    assert prop["min_channel_disclosure_score"] == 0
    assert prop["disclosure_posture"] == "NON_COMPLIANT"
    assert prop["aggregate_disclosure_gap_cents"] == 23124
    assert prop["open_disclosure_obligation_count"] == 5

    sibling_after = read_booking(env["sibling"]["id"])
    assert sibling_after["disclosure_status"] == "DISPUTED"
    assert sibling_after["stay_status"] == "QUOTED"

    # The first complaint's entitlement is a settled figure, not recomputed.
    first = validate_success(
        api.get_guest_complaint(env["complaint_first"]["id"], AGENT)
    )
    assert first["refund_variant"] == "FULL_FEE_REFUND"
    assert first["refund_entitlement_cents"] == 2600

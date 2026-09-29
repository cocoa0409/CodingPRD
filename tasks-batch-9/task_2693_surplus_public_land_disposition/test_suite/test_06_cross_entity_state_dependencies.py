"""Writes gated by the state of an entity the request never mentions.

An offering create carrying a perfectly valid payload against a perfectly
authorized declaration is refused because the parcel's valuation has aged out
overnight. A clear-title certification on a conveyance whose own fields are all
in order is refused because a defect was discovered on the parcel after the file
was opened.
"""

from test_helpers import ApiErrorId, factories as f, fixtures as fx
from test_helpers import get_success_data, validate_error


def _authorized_declaration_at_the_expiry_instant(api):
    """A disposition fully authorized last summer whose valuation lapses today.

    The appraisal was reported with an effective date of 2026-08-01, so it
    expires exactly 365 days later. Everything the offering needs was done at the
    default clock — adoption, an exempt environmental determination, a declined
    notice, the closed preference window and the competitive-sale authorization —
    and only then is the clock moved to the expiry instant itself.
    """
    ctx = fx.build_valued_parcel(
        api,
        appraised_value_cents=100000000,
        book_value_cents=70000000,
        cured_lien_actual_cents=250000,
        lien_estimate_cents=250000,
    )
    ctx = fx.build_authorized_declaration(api, ctx)
    ctx["version_before_trigger"] = fx.declaration_version(
        api, ctx["declaration"]["id"]
    )
    fx.set_clock(api, "2027-08-01T00:00:00Z")
    return ctx


def _create_the_offering(api, ctx, expected_declaration_version):
    """Post the same competitive-sale payload over next winter's window."""
    return api.create_offering(
        f.offering_payload(
            ctx["declaration"]["id"],
            expected_declaration_version,
            offering_type="COMPETITIVE_SALE",
            bid_open_at="2027-08-01T00:00:00Z",
            bid_close_at="2027-12-31T00:00:00Z",
        ),
        fx.OFFICER_HEADERS,
    )


def _conveyance_blocked_by_a_late_title_item(api):
    """A conveyance file awaiting title when a new encroachment is discovered.

    The parcel's only earlier defect was cured at 250,000 before the offering was
    created, so the minimum price froze at 99,750,000 and the winning bid of
    108,000,000 leaves a provisional net of 105,250,001. The encroachment is
    opened only after the conveyance exists, which drives the parcel's open item
    count back up to one.
    """
    ctx = fx.build_valued_parcel(
        api,
        appraised_value_cents=100000000,
        book_value_cents=70000000,
        cured_lien_actual_cents=250000,
        lien_estimate_cents=250000,
    )
    ctx = fx.build_conveyance(
        api,
        ctx,
        closing_costs_cents=1249999,
        broker_fee_cents=1500000,
        reverter_cure_period_days=30,
        bid_amount_cents=108000000,
        bidder_funding_cents=10000000,
    )
    ctx["late_item"] = fx.open_title_item(
        api,
        ctx["parcel"]["id"],
        item_type="ENCROACHMENT",
        description="Neighbor driveway encroachment found during the buyer walk-through",
        cure_cost_estimate_cents=400000,
    )
    return ctx


def test_01_the_offering_create_is_refused_because_the_valuation_has_aged_out(api):
    """The declaration is ready and the payload is valid, and the appraisal is not.

    "Next that accepted appraisal must still be inside its validity window,
    meaning the clock is strictly before its `expires_on`; a clock standing
    exactly on `expires_on` means the appraisal has already lapsed." "`expires_on`
    is anchored to the valuation date supplied by the appraiser, not to the moment
    of submission, so a report with a back-dated effective date arrives with less
    of its validity left."

    Design: Difficulty/cross_entity_state_dependency/offering_create_depends_on_accepted_appraisal_validity_window
    """
    ctx = _authorized_declaration_at_the_expiry_instant(api)
    appraisal = get_success_data(
        api.get_appraisal(ctx["appraisal"]["id"], fx.OFFICER_HEADERS)
    )
    assert appraisal["expires_on"] == "2027-08-01T00:00:00.000Z", (
        "an effective date of 2026-08-01 plus 365 days is 2027-08-01T00:00:00Z, "
        f"got {appraisal['expires_on']!r}"
    )
    assert ctx["declaration"]["status"] == "OFFERING_AUTHORIZED", (
        "the declaration is fully authorized, so nothing on the request's own "
        f"entity can be the obstacle, got {ctx['declaration']['status']!r}"
    )

    response = _create_the_offering(api, ctx, ctx["version_before_trigger"])
    validate_error(response, ApiErrorId.ERR_APPRAISAL_EXPIRED.value, 409)

    offerings = get_success_data(
        api.list_offerings(
            fx.OFFICER_HEADERS,
            {"declaration_id": ctx["declaration"]["id"], "limit": 100},
        )
    )
    assert offerings == [], (
        f"the refused create must leave no offering behind, got {offerings!r}"
    )


def test_02_the_refused_create_still_retires_the_appraisal_and_stales_the_parcel(api):
    """The refusal is not inert: it writes to the two entities it read.

    "Before the refusal is issued the service performs the expiry it just
    observed: the appraisal moves `ACCEPTED → EXPIRED`, the parcel's
    `valuation_status` becomes `STALE` and `disposition_ready` is recomputed to
    false, and those changes persist even though the offering create itself is
    refused with `ERR_APPRAISAL_EXPIRED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/offering_create_depends_on_accepted_appraisal_validity_window
    """
    ctx = _authorized_declaration_at_the_expiry_instant(api)
    _create_the_offering(api, ctx, ctx["version_before_trigger"])

    appraisal = get_success_data(
        api.get_appraisal(ctx["appraisal"]["id"], fx.OFFICER_HEADERS)
    )
    assert appraisal["status"] == "EXPIRED", (
        "the create that observed the expiry retires the report, got "
        f"{appraisal['status']!r}"
    )

    parcel = get_success_data(api.get_parcel(ctx["parcel"]["id"], fx.OFFICER_HEADERS))
    assert parcel["valuation_status"] == "STALE", (
        f"and the parcel's valuation goes stale with it, got {parcel['valuation_status']!r}"
    )
    assert parcel["disposition_ready"] is False, (
        f"so the parcel is no longer disposition-ready, got {parcel['disposition_ready']!r}"
    )

    declaration = get_success_data(
        api.get_declaration(ctx["declaration"]["id"], fx.OFFICER_HEADERS)
    )
    assert declaration["status"] == "OFFERING_AUTHORIZED", (
        "the declaration is not moved by the refusal, got "
        f"{declaration['status']!r}"
    )
    assert declaration["version"] == ctx["version_before_trigger"], (
        "and its concurrency token is not spent, so the caller may retry with it: "
        f"{declaration['version']} against {ctx['version_before_trigger']}"
    )


def test_03_the_identical_payload_succeeds_once_a_fresh_valuation_is_accepted(api):
    """Curing the foreign entity, not the request, is what makes the create work.

    "On success the offering is created in `DRAFT` with three computed values
    frozen onto it and never recomputed thereafter: `minimum_price_cents` from the
    minimum-price rules of §3.7, `minimum_price_variant` recording which variant
    produced it, and `required_deposit_cents`." "`expires_on` is computed as the
    `effective_date` plus 365 days, and the appraisal moves `ORDERED → REPORTED`."

    Design: Difficulty/cross_entity_state_dependency/offering_create_depends_on_accepted_appraisal_validity_window
    """
    ctx = _authorized_declaration_at_the_expiry_instant(api)
    _create_the_offering(api, ctx, ctx["version_before_trigger"])

    replacement = fx.make_accepted_appraisal(
        api,
        ctx["parcel"]["id"],
        ctx["appraiser"]["id"],
        appraised_value_cents=100000000,
        effective_date="2027-08-01T00:00:00Z",
        engagement_start_on="2027-08-02T00:00:00Z",
        engagement_end_on="2027-08-20T00:00:00Z",
    )
    assert replacement["status"] == "ACCEPTED", (
        f"the refreshed report governs the parcel, got {replacement['status']!r}"
    )
    assert replacement["expires_on"] == "2028-07-31T00:00:00.000Z", (
        "an effective date of 2027-08-01 plus 365 days is 2028-07-31T00:00:00Z, "
        f"got {replacement['expires_on']!r}"
    )

    parcel = get_success_data(api.get_parcel(ctx["parcel"]["id"], fx.OFFICER_HEADERS))
    assert parcel["valuation_status"] == "CURRENT", (
        f"the parcel is validly valued again, got {parcel['valuation_status']!r}"
    )
    assert parcel["disposition_ready"] is True, (
        f"and disposition-ready once more, got {parcel['disposition_ready']!r}"
    )

    version = fx.declaration_version(api, ctx["declaration"]["id"])
    offering = get_success_data(_create_the_offering(api, ctx, version))
    assert offering["status"] == "DRAFT", (
        f"the second attempt opens the offering, got {offering['status']!r}"
    )
    assert offering["minimum_price_cents"] == 99750000, (
        "100,000,000 with no write-down less the 250,000 cure deduction is "
        f"99,750,000, got {offering['minimum_price_cents']}"
    )
    assert offering["minimum_price_variant"] == "MARKET_FLOOR", (
        "a competitive sale is priced on the market-floor variant, got "
        f"{offering['minimum_price_variant']!r}"
    )


def test_04_a_defect_discovered_after_the_file_opened_blocks_clearing_title(api):
    """The conveyance is in order and the parcel is not, and the parcel governs.

    "Then, in order: every title curative item on the parcel must have left
    `OPEN` — cured, waived with an endorsement or reserved as an easement all
    satisfy the test, and a single open item is `ERR_TITLE_ITEMS_UNRESOLVED`
    (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/clear_title_depends_on_no_open_title_item_on_parcel
    """
    ctx = _conveyance_blocked_by_a_late_title_item(api)
    assert ctx["conveyance"]["recording_status"] == "PENDING_TITLE", (
        "the conveyance is validly awaiting title, got "
        f"{ctx['conveyance']['recording_status']!r}"
    )

    parcel = get_success_data(api.get_parcel(ctx["parcel"]["id"], fx.OFFICER_HEADERS))
    assert parcel["open_title_item_count"] == 1, (
        "the newly discovered encroachment puts the count back to one, got "
        f"{parcel['open_title_item_count']}"
    )

    response = api.clear_title(ctx["conveyance"]["id"], fx.OFFICER_HEADERS)
    validate_error(response, ApiErrorId.ERR_TITLE_ITEMS_UNRESOLVED.value, 422)


def test_05_the_refused_certification_mutates_nothing_on_the_conveyance(api):
    """Unlike the appraisal refusal, this one leaves the money unfrozen.

    "`recoverable_curative_cost_cents`, `net_proceeds_cents` and
    `allocated_proceeds_cents` all start at zero, and `recorded_instrument_number`,
    `recorded_at`, `violation_noticed_at`, `cure_deadline_at`,
    `violation_description`, `cure_note` and `reverted_at` all start empty."

    Design: Difficulty/cross_entity_state_dependency/clear_title_depends_on_no_open_title_item_on_parcel
    """
    ctx = _conveyance_blocked_by_a_late_title_item(api)
    api.clear_title(ctx["conveyance"]["id"], fx.OFFICER_HEADERS)

    conveyance = get_success_data(
        api.get_conveyance(ctx["conveyance"]["id"], fx.OFFICER_HEADERS)
    )
    assert conveyance["recording_status"] == "PENDING_TITLE", (
        "the refused certification does not advance the file, got "
        f"{conveyance['recording_status']!r}"
    )
    assert conveyance["net_proceeds_cents"] == 0, (
        "and the money is still unfrozen at its opening value, got "
        f"{conveyance['net_proceeds_cents']}"
    )
    assert conveyance["recoverable_curative_cost_cents"] == 0, (
        "as is the recoverable curative cost, got "
        f"{conveyance['recoverable_curative_cost_cents']}"
    )


def test_06_waiving_the_blocker_on_the_other_entity_unblocks_the_certification(api):
    """The write that clears the way is to the title item, and it costs nothing.

    "Resolving it as `WAIVED_WITH_ENDORSEMENT` means a title insurer has endorsed
    over the defect, so no curative money was spent: `actual_cure_cost_cents` is
    set to zero regardless of any value in the request, `resolved_at` is stamped,
    `open_title_item_count` falls by 1, and `disposition_ready` is recomputed."
    "The incurred curative cost is the sum of `actual_cure_cost_cents` over the
    title curative items on this conveyance's parcel whose `status` is `CURED`;
    items waived with an endorsement or reserved as an easement carry a zero cure
    cost and so contribute nothing."

    Design: Difficulty/cross_entity_state_dependency/clear_title_depends_on_no_open_title_item_on_parcel
    """
    ctx = _conveyance_blocked_by_a_late_title_item(api)
    api.clear_title(ctx["conveyance"]["id"], fx.OFFICER_HEADERS)

    waived = fx.waive_title_item(api, ctx["late_item"]["id"])
    assert waived["status"] == "WAIVED_WITH_ENDORSEMENT", (
        f"the insurer endorsed over the encroachment, got {waived['status']!r}"
    )
    assert waived["actual_cure_cost_cents"] == 0, (
        f"so no curative money was spent on it, got {waived['actual_cure_cost_cents']}"
    )
    parcel = get_success_data(api.get_parcel(ctx["parcel"]["id"], fx.OFFICER_HEADERS))
    assert parcel["open_title_item_count"] == 0, (
        f"and the parcel carries no open item again, got {parcel['open_title_item_count']}"
    )

    conveyance = fx.clear_title(api, ctx["conveyance"]["id"])
    assert conveyance["recording_status"] == "READY_TO_RECORD", (
        f"the same certification now succeeds, got {conveyance['recording_status']!r}"
    )
    assert conveyance["recoverable_curative_cost_cents"] == 250000, (
        "only the cured lien contributes, and the 15 percent cap of 15,787,500 "
        f"leaves it whole, got {conveyance['recoverable_curative_cost_cents']}"
    )
    assert conveyance["net_proceeds_cents"] == 105000001, (
        "105,250,001 less the 250,000 recovery is 105,000,001, got "
        f"{conveyance['net_proceeds_cents']}"
    )

    offering = get_success_data(
        api.get_offering(ctx["offering"]["id"], fx.OFFICER_HEADERS)
    )
    assert offering["minimum_price_cents"] == 99750000, (
        "the late-discovered defect does not disturb the frozen minimum price, "
        f"got {offering['minimum_price_cents']}"
    )

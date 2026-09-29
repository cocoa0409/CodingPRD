"""Consensus arithmetic, ownership tiering, meeting priority and posture windows.

These tests pin the decimal corners of the register and the consensus read: the
half-up rounding of the fourth decimal on a mean, the conjunctive eligible-set
filter that drops superseded and revoked rows, the rounded ownership percentage
that decides a tier, the capped engagement term inside a priority score, the
one-way activist escalation at exactly five percent, and the half-open blackout
window.
"""

from test_helpers import (
    ApiClient,
    CONTACT_INSTITUTIONAL_HOLDER,
    CONTACT_RETAIL_HOLDER,
    DEFAULT_CLOCK_UTC,
    DISCLOSURE_OFFICER,
    ESTIMATE_ACCEPTED,
    ESTIMATE_SUPERSEDED,
    IR_ADMIN,
    IR_ANALYST,
    MODEL_ACCESS_REVOKED,
    POSTURE_BLACKOUT,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    REQUEST_REQUESTED,
    SERVICING_REVOKE_MODEL_ACCESS,
    THREAT_ELEVATED,
    TIER_1,
    TIER_2,
    TIER_3,
    UNTIERED,
    VARIANT_ANCHORED,
    assertions,
    factories,
    fixtures,
    get_success_data,
    validate_paginated,
    validate_success,
)

CLOCK = DEFAULT_CLOCK_UTC


# ---------------------------------------------------------------------------
# Local composite setups (test_helpers has no equivalent)
# ---------------------------------------------------------------------------


def _consensus_world_two_estimates(api: ApiClient):
    """Two granted, covering analysts filing 2.0000 and 2.3001 for EPS / FY2026."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api,
        ticker="PRC",
        legal_name="Precision Consensus Corp",
        shares_outstanding=1000000,
    )
    seeded = fixtures.seed_estimates(
        api,
        company["id"],
        [2.0000, 2.3001],
        name_prefix="Precision Analyst",
        email_prefix="prc",
    )
    return company, seeded


def _consensus_world_filtered_rows(api: ApiClient):
    """Three stored estimates of which only one survives the eligible-set filter."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api,
        ticker="FLT",
        legal_name="Filtered Consensus Corp",
        shares_outstanding=1000000,
    )
    first_analyst = fixtures.create_granted_analyst(
        api,
        company["id"],
        display_name="Filter Analyst One",
        email="flt1@bank.test",
    )
    superseded = fixtures.file_estimate(api, first_analyst["id"], 2.0000)
    accepted = fixtures.file_estimate(api, first_analyst["id"], 2.4000)

    second_analyst = fixtures.create_granted_analyst(
        api,
        company["id"],
        display_name="Filter Analyst Two",
        email="flt2@bank.test",
    )
    dropped = fixtures.file_estimate(api, second_analyst["id"], 9.0000)
    revoked = get_success_data(
        api.servicing(
            second_analyst["id"],
            factories.servicing_payload(SERVICING_REVOKE_MODEL_ACCESS),
            DISCLOSURE_OFFICER,
        )
    )
    return {
        "company": company,
        "first_analyst": first_analyst,
        "second_analyst": revoked,
        "superseded": superseded,
        "accepted": accepted,
        "dropped": dropped,
    }


def _engagement_world(api: ApiClient):
    """A four-percent holder, a six-percent holder and an event open for requests."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api,
        ticker="ENG",
        legal_name="Engagement Cap Corp",
        shares_outstanding=1000000,
    )
    four_percent = fixtures.create_contact(
        api,
        company["id"],
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
        display_name="Four Percent Fund",
        email="eng1@funds.test",
        shares_held=40000,
        nda_on_file=True,
    )
    six_percent = fixtures.create_contact(
        api,
        company["id"],
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
        display_name="Six Percent Fund",
        email="eng2@funds.test",
        shares_held=60000,
        nda_on_file=True,
    )
    event = fixtures.open_event(
        api,
        company["id"],
        venue_city="Zurich",
        window_start="2026-09-01T13:00:00Z",
        window_end="2026-09-01T18:00:00Z",
        slot_minutes=30,
        capacity_slots=4,
    )
    return company, four_percent, six_percent, event


def _activist_stake_world(api: ApiClient):
    """An activist institutional holder at 4.0000% of a one-million-share register."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api,
        ticker="ACT",
        legal_name="Activist Stake Corp",
        shares_outstanding=1000000,
    )
    activist = fixtures.create_contact(
        api,
        company["id"],
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
        display_name="Stake Builder",
        email="act@funds.test",
        shares_held=40000,
        activist_flag=True,
    )
    return company, activist


def _half_open_window_company(api: ApiClient):
    """An issuer whose quiet period runs 2026-08-10 to 2026-08-20 with no activists."""
    fixtures.set_clock(api, CLOCK)
    return fixtures.create_company(
        api,
        ticker="HOP",
        legal_name="Half Open Corp",
        shares_outstanding=1000000,
        blackout_window_start="2026-08-10T00:00:00Z",
        blackout_window_end="2026-08-20T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# The mean rounds half up at the fourth decimal, and the band follows it
# ---------------------------------------------------------------------------


def test_simple_mean_rounds_half_up_and_anchors_the_band_on_the_rounded_figure(
    api: ApiClient,
):
    """PRD §3.7: "Sum the `value` of every eligible submission, divide by the number of eligible submissions, and round the quotient half up to 4 decimal places."
    PRD §3.7: "If no such row exists, `guidance_anchored` is false and the same fifteen-percent margins are applied to `simple_mean` instead: `band_low` is `simple_mean` multiplied by 0.85 and `band_high` is `simple_mean` multiplied by 1.15, each rounded half up to 4 decimal places."
    PRD §2.9: "Consensus means (`simple_mean`, `consensus_mean`) and the guidance band bounds (`band_low`, `band_high`) are carried to 4 decimal places; `dispersion_pct` is carried to 2 decimal places."

    Design: Corner/calculations/consensus_means_round_half_up_at_the_fourth_decimal
    """
    company, _seeded = _consensus_world_two_estimates(api)

    data = validate_success(
        api.get_consensus(company["id"], "EPS", "FY2026", None, IR_ANALYST), 200
    )

    # (2.0000 + 2.3001) / 2 = 2.15005, exactly half way, so it rounds up.
    assertions.assert_consensus(
        data,
        eligible_count=2,
        guidance_anchored=False,
        simple_mean=assertions.approx_4dp(2.1501),
        band_low=assertions.approx_4dp(1.8276),
        band_high=assertions.approx_4dp(2.4726),
    )


def test_untrimmed_set_reports_the_rounded_anchored_mean_and_two_decimal_dispersion(
    api: ApiClient,
):
    """PRD §3.7: "Keep every eligible submission whose `value` lies within the band, both bounds inclusive: a value exactly equal to `band_low` or exactly equal to `band_high` is kept."
    PRD §3.7: "Otherwise the anchored mean is the sum of the kept values divided by their count, rounded half up to 4 decimal places, and `trimmed_applied` is reported as true."
    PRD §3.7: "When `variant` is `ANCHORED`, or when it is omitted entirely (`ANCHORED` being the default), `consensus_mean` is the anchored mean from step four; for identical inputs the two variants diverge whenever `outlier_excluded_count` is greater than zero."
    PRD §3.7: "Finally, `dispersion_pct` is the spread of the kept values relative to the reported consensus: the largest kept value minus the smallest kept value, divided by `consensus_mean`, multiplied by 100 and rounded half up to 2 decimal places."

    Design: Corner/calculations/consensus_means_round_half_up_at_the_fourth_decimal
    """
    company, _seeded = _consensus_world_two_estimates(api)

    data = validate_success(
        api.get_consensus(company["id"], "EPS", "FY2026", None, IR_ANALYST), 200
    )

    # Both values sit inside [1.8276, 2.4726], so nothing is trimmed and the
    # anchored mean is the same 2.1501; 0.3001 / 2.1501 * 100 = 13.9575... -> 13.96.
    assertions.assert_consensus(
        data,
        outlier_excluded_count=0,
        trimmed_applied=True,
        consensus_mean=assertions.approx_4dp(2.1501),
        dispersion_pct=assertions.approx_2dp(13.96),
        variant=VARIANT_ANCHORED,
    )


# ---------------------------------------------------------------------------
# The eligible set is a conjunction: superseded and revoked rows drop out
# ---------------------------------------------------------------------------


def test_eligible_set_keeps_only_the_accepted_row_of_a_granted_analyst(api: ApiClient):
    """PRD §3.7: "A submission is eligible when all of the following hold together: its own `status` is `ACCEPTED`; the contact that filed it belongs to the issuer being read; that contact's `contact_type` is `SELL_SIDE_ANALYST`; that contact's `coverage_status` is `INITIATED`; that contact's `model_access_status` is anything other than `REVOKED`; its `metric` equals the requested metric; its `period_label` equals the requested period; and its `submitted_at` is at or after the logical clock's current instant minus 90 days, the lower bound being inclusive."
    PRD §3.7: "The size of the surviving set is reported as `eligible_count`."

    Design: Corner/calculations/consensus_eligible_set_drops_superseded_and_revoked_rows
    """
    world = _consensus_world_filtered_rows(api)

    data = validate_success(
        api.get_consensus(world["company"]["id"], "EPS", "FY2026", None, IR_ANALYST),
        200,
    )

    # The 2.0000 row is SUPERSEDED and the 9.0000 row's analyst is REVOKED, so an
    # unfiltered mean of 4.4667 collapses to the single surviving 2.4000.
    assertions.assert_consensus(
        data,
        eligible_count=1,
        simple_mean=assertions.approx_4dp(2.4000),
        consensus_mean=assertions.approx_4dp(2.4000),
        band_low=assertions.approx_4dp(2.0400),
        band_high=assertions.approx_4dp(2.7600),
        outlier_excluded_count=0,
        trimmed_applied=True,
        dispersion_pct=assertions.approx_2dp(0.00),
    )


def test_filtered_out_rows_are_still_stored_with_their_own_statuses(api: ApiClient):
    """PRD §3.7: "A successful filing is born with `status` `ACCEPTED` and `submitted_at` stamped from the logical clock, and it supersedes the filer's own history: any earlier submission by the same contact for the same `metric` and the same `period_label` that is still `ACCEPTED` transitions to `SUPERSEDED`."
    PRD §3.3: "Revoking model access moves `model_access_status` from `GRANTED` to `REVOKED` and requires the current value to be exactly `GRANTED`; revoking an access that was never granted, or revoking twice, is refused with `ERR_MODEL_ACCESS_NOT_ELIGIBLE`."
    PRD §3.3: "Revocation is deliberately non-destructive to history: estimate submissions that analyst has already filed keep their `ACCEPTED` status untouched, but for as long as `model_access_status` remains `REVOKED` those rows fall out of the consensus eligible set described in §3.7 — so revoking access silently changes what the consensus read reports without deleting a single row."

    Design: Corner/calculations/consensus_eligible_set_drops_superseded_and_revoked_rows
    """
    world = _consensus_world_filtered_rows(api)

    first_rows, _meta = validate_paginated(
        api.list_contact_estimates(world["first_analyst"]["id"], IR_ADMIN)
    )
    by_id = {row["id"]: row for row in first_rows}
    assertions.assert_estimate(
        by_id[world["superseded"]["id"]], status=ESTIMATE_SUPERSEDED
    )
    assertions.assert_estimate(by_id[world["accepted"]["id"]], status=ESTIMATE_ACCEPTED)

    assertions.assert_contact(
        fixtures.read_contact(api, world["second_analyst"]["id"]),
        model_access_status=MODEL_ACCESS_REVOKED,
    )
    second_rows, _second_meta = validate_paginated(
        api.list_contact_estimates(world["second_analyst"]["id"], IR_ADMIN)
    )
    dropped = {row["id"]: row for row in second_rows}[world["dropped"]["id"]]
    assertions.assert_estimate(dropped, status=ESTIMATE_ACCEPTED)


# ---------------------------------------------------------------------------
# ownership_pct rounds half up, and the tier test reads the rounded figure
# ---------------------------------------------------------------------------


def test_one_share_of_two_million_rounds_up_into_tier_three(api: ApiClient):
    """PRD §3.2: "On creation, and again on every position update, the system divides the contact's `shares_held` by the issuer's `shares_outstanding` as stored at that moment, multiplies the quotient by 100, and rounds the result half up to 4 decimal places to obtain `ownership_pct`."
    PRD §3.2: "From that rounded figure — never from the raw quotient — it derives the outreach tier stored in `target_tier`, evaluated top to bottom with the first matching clause winning: a percentage of at least 5.0 is `TIER_1`; otherwise a percentage of at least 1.0 is `TIER_2`; otherwise any percentage strictly greater than zero is `TIER_3`; and a percentage of exactly zero is `UNTIERED`."
    PRD §2.9: "Ownership percentages (`ownership_pct`) are carried to 4 decimal places."

    Design: Corner/calculations/ownership_pct_rounds_half_up_and_zero_is_untiered
    """
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api, ticker="TWO", legal_name="Two Million Corp", shares_outstanding=2000000
    )

    contact = validate_success(
        api.create_contact(
            factories.contact_payload(
                company["id"],
                contact_type=CONTACT_RETAIL_HOLDER,
                display_name="One Share Of Two Million",
                email="tiny1@retail.test",
                shares_held=1,
            ),
            IR_ADMIN,
        ),
        201,
    )

    # 1 / 2,000,000 * 100 = 0.00005 exactly, which rounds half up to 0.0001.
    assertions.assert_contact(
        contact,
        shares_held=1,
        ownership_pct=assertions.approx_4dp(0.0001),
        target_tier=TIER_3,
    )


def test_one_share_of_four_million_rounds_down_to_zero_and_is_untiered(api: ApiClient):
    """PRD §3.2: "Both tier boundaries are inclusive on their low side, so exactly 1.0000 is `TIER_2` and exactly 5.0000 is `TIER_1`, while a holder of no shares is `UNTIERED` and never `TIER_3`."
    PRD §2.9: "Every tier comparison and every activist-stake threshold test uses the *rounded* percentage, never the raw quotient."

    Design: Corner/calculations/ownership_pct_rounds_half_up_and_zero_is_untiered
    """
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api, ticker="FOUR", legal_name="Four Million Corp", shares_outstanding=4000000
    )

    contact = validate_success(
        api.create_contact(
            factories.contact_payload(
                company["id"],
                contact_type=CONTACT_RETAIL_HOLDER,
                display_name="One Share Of Four Million",
                email="tiny2@retail.test",
                shares_held=1,
            ),
            IR_ADMIN,
        ),
        201,
    )

    # 1 / 4,000,000 * 100 = 0.000025, which rounds to 0.0000 -- and the tier test
    # reads that rounded zero, so the holder is UNTIERED rather than TIER_3.
    assertions.assert_contact(
        contact,
        shares_held=1,
        ownership_pct=assertions.approx_4dp(0.0000),
        target_tier=UNTIERED,
    )


def test_contact_created_without_shares_is_untiered_at_zero_percent(api: ApiClient):
    """PRD §3.2: "Four inputs are optional: `shares_held` defaults to 0 and may never be negative; `nda_on_file` defaults to false; `coverage_status` defaults to `NOT_COVERING` and may otherwise be `INITIATED` or `SUSPENDED`; and `activist_flag` defaults to false."
    PRD §3.2: "Both tier boundaries are inclusive on their low side, so exactly 1.0000 is `TIER_2` and exactly 5.0000 is `TIER_1`, while a holder of no shares is `UNTIERED` and never `TIER_3`."

    Design: Corner/calculations/ownership_pct_rounds_half_up_and_zero_is_untiered
    """
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api, ticker="TWO", legal_name="Two Million Corp", shares_outstanding=2000000
    )

    contact = validate_success(
        api.create_contact(
            factories.contact_payload(
                company["id"],
                contact_type=CONTACT_RETAIL_HOLDER,
                display_name="No Shares At All",
                email="tiny3@retail.test",
            ),
            IR_ADMIN,
        ),
        201,
    )

    assertions.assert_contact(
        contact,
        shares_held=0,
        ownership_pct=assertions.approx_4dp(0.0000),
        target_tier=UNTIERED,
    )


# ---------------------------------------------------------------------------
# The engagement term is capped at 20, and tier points switch at five percent
# ---------------------------------------------------------------------------


def test_four_percent_holder_scores_an_uncapped_engagement_term(api: ApiClient):
    """PRD §3.8: "Start with tier points read from the contact's `target_tier`: 50 for `TIER_1`, 35 for `TIER_2`, 20 for `TIER_3` and 5 for `UNTIERED`."
    PRD §3.8: "Add 8 when the contact's `nda_on_file` is true, and nothing when it is false."
    PRD §3.8: "Add an engagement term equal to the contact's `ownership_pct` multiplied by 4, rounded half up to 2 decimal places and then capped at 20 — the rounding happening before the term is added, and the cap meaning that any holder above five percent of the register contributes exactly 20."
    PRD §3.8: "Multiply the result by a type multiplier read from the contact's `contact_type`: 1.20 for an `INSTITUTIONAL_HOLDER`, 1.00 for a `SELL_SIDE_ANALYST` and 0.60 for a `RETAIL_HOLDER`."
    PRD §3.8: "The **provisional** variant runs at intake, is written to `provisional_priority_score`, uses the contact as it stands at intake, and its lead-time bonus is always zero."

    Design: Corner/calculations/engagement_term_is_capped_and_tier_points_switch_at_five_percent
    """
    _company, four_percent, _six_percent, event = _engagement_world(api)

    assertions.assert_contact(
        fixtures.read_contact(api, four_percent["id"]),
        ownership_pct=assertions.approx_4dp(4.0000),
        target_tier=TIER_2,
    )

    request = validate_success(
        api.create_meeting_request(
            factories.meeting_request_payload(
                event["id"],
                four_percent["id"],
                requested_slot_start="2026-09-01T13:00:00Z",
                requested_slot_end="2026-09-01T13:30:00Z",
            ),
            IR_ADMIN,
        ),
        201,
    )

    # (35 tier + 8 nda + 16.00 engagement + 0 lead) * 1.20 = 70.80.
    assertions.assert_meeting_request(
        request,
        provisional_priority_score=assertions.approx_2dp(70.80),
        final_priority_score=None,
        status=REQUEST_REQUESTED,
    )


def test_six_percent_holder_is_tier_one_with_the_engagement_term_clamped(api: ApiClient):
    """PRD §3.8: "Add an engagement term equal to the contact's `ownership_pct` multiplied by 4, rounded half up to 2 decimal places and then capped at 20 — the rounding happening before the term is added, and the cap meaning that any holder above five percent of the register contributes exactly 20."
    PRD §3.8: "Start with tier points read from the contact's `target_tier`: 50 for `TIER_1`, 35 for `TIER_2`, 20 for `TIER_3` and 5 for `UNTIERED`."
    PRD §3.8: "A surviving request is born in `REQUESTED` with `final_priority_score` null, `allocated_at` null, `release_reason` null and `promoted_from_waitlist` false, and it increments the parent event's `request_ledger_total` by 1 along with the event's `version`."

    Design: Corner/calculations/engagement_term_is_capped_and_tier_points_switch_at_five_percent
    """
    _company, _four_percent, six_percent, event = _engagement_world(api)

    assertions.assert_contact(
        fixtures.read_contact(api, six_percent["id"]),
        ownership_pct=assertions.approx_4dp(6.0000),
        target_tier=TIER_1,
    )

    request = validate_success(
        api.create_meeting_request(
            factories.meeting_request_payload(
                event["id"],
                six_percent["id"],
                requested_slot_start="2026-09-01T14:00:00Z",
                requested_slot_end="2026-09-01T14:30:00Z",
            ),
            IR_ADMIN,
        ),
        201,
    )

    # (50 tier + 8 nda + 20 engagement, clamped from 24.00) * 1.20 = 93.60.
    assertions.assert_meeting_request(
        request,
        provisional_priority_score=assertions.approx_2dp(93.60),
        final_priority_score=None,
        allocated_at=None,
        release_reason=None,
        promoted_from_waitlist=False,
        status=REQUEST_REQUESTED,
    )
    assertions.assert_roadshow_event(
        fixtures.read_event(api, event["id"]), request_ledger_total=1
    )


# ---------------------------------------------------------------------------
# Activist escalation at exactly five percent is one-way
# ---------------------------------------------------------------------------


def test_crossing_exactly_five_percent_escalates_the_activist_and_restricts_the_issuer(
    api: ApiClient,
):
    """PRD §3.2: "Once the patched contact's `ownership_pct` has been recomputed, if that contact's `activist_flag` is true, its rounded `ownership_pct` is at least 5.0 (the boundary being inclusive), and its current `threat_level` is either `NONE` or `WATCH`, then `threat_level` is raised to `ELEVATED` — and it is that raised value the subsequent posture re-derivation reads, so a stake crossing five percent can move the issuer from `OPEN` to `RESTRICTED` within the same request."
    PRD §2.7: "Otherwise, if any flagged activist carries threat level `ELEVATED`, the posture is `RESTRICTED`."
    PRD §2.7: "Whenever the posture is re-derived, `posture_recomputed_at` is stamped with the logical clock's current instant."

    Design: Corner/calculations/activist_escalation_is_one_way_at_the_five_percent_stake
    """
    company, activist = _activist_stake_world(api)
    assert fixtures.read_company(api, company["id"])["disclosure_posture"] == POSTURE_OPEN

    patched = validate_success(
        api.update_position(
            activist["id"],
            factories.position_payload(50000, fixtures.company_version(api, company["id"])),
            IR_ADMIN,
        ),
        200,
    )

    assertions.assert_contact(
        patched,
        shares_held=50000,
        ownership_pct=assertions.approx_4dp(5.0000),
        target_tier=TIER_1,
        threat_level=THREAT_ELEVATED,
    )

    issuer = fixtures.read_company(api, company["id"])
    assertions.assert_company(issuer, disclosure_posture=POSTURE_RESTRICTED)
    assertions.assert_ts_equals(
        issuer["posture_recomputed_at"],
        "2026-08-01T00:00:00.000Z",
        "posture_recomputed_at",
    )


def test_selling_back_below_five_percent_re_tiers_but_never_de_escalates(api: ApiClient):
    """PRD §3.2: "There is no automatic de-escalation: a position sold back below five percent leaves `threat_level` exactly where the escalation left it, and only an explicit servicing action can lower it again."
    PRD §3.2: "A position write that survives every check re-derives `ownership_pct` and `target_tier`, then re-derives the issuer's `disclosure_posture` and stamps `posture_recomputed_at`, incrementing both the contact's `version` and the issuer's `version` by 1."
    PRD §2.7: "Otherwise, if any flagged activist carries threat level `ELEVATED`, the posture is `RESTRICTED`."

    Design: Corner/calculations/activist_escalation_is_one_way_at_the_five_percent_stake
    """
    company, activist = _activist_stake_world(api)

    escalated = validate_success(
        api.update_position(
            activist["id"],
            factories.position_payload(50000, fixtures.company_version(api, company["id"])),
            IR_ADMIN,
        ),
        200,
    )
    assert escalated["threat_level"] == THREAT_ELEVATED

    sold_down = validate_success(
        api.update_position(
            activist["id"],
            factories.position_payload(10000, fixtures.company_version(api, company["id"])),
            IR_ADMIN,
        ),
        200,
    )

    assertions.assert_contact(
        sold_down,
        shares_held=10000,
        ownership_pct=assertions.approx_4dp(1.0000),
        target_tier=TIER_2,
        threat_level=THREAT_ELEVATED,
    )
    assertions.assert_company(
        fixtures.read_company(api, company["id"]), disclosure_posture=POSTURE_RESTRICTED
    )


# ---------------------------------------------------------------------------
# The blackout window is [start, end)
# ---------------------------------------------------------------------------


def test_blackout_window_start_instant_is_inside_the_window(api: ApiClient):
    """PRD §2.7: "The first is the issuer's scheduled earnings quiet period, delimited by `blackout_window_start` and `blackout_window_end`; the issuer is inside that window when a start instant has been configured, that start instant is at or before the logical clock, and the logical clock is strictly before the end instant."
    PRD §2.7: "If the issuer is inside its blackout window, or if any flagged activist of that issuer carries threat level `CRITICAL`, the posture is `BLACKOUT`."
    PRD §3.1: "The refresh re-derives `disclosure_posture` and recounts `open_inquiry_count`, stamps `posture_recomputed_at` with the logical clock, and increments the issuer's `version` by 1."

    Design: Corner/calculations/blackout_window_is_half_open_at_both_ends
    """
    company = _half_open_window_company(api)

    fixtures.set_clock(api, "2026-08-09T23:59:59Z")
    before_start = fixtures.recompute_posture(api, company["id"])
    assertions.assert_company(before_start, disclosure_posture=POSTURE_OPEN)
    assertions.assert_ts_equals(
        before_start["posture_recomputed_at"],
        "2026-08-09T23:59:59.000Z",
        "posture_recomputed_at",
    )

    fixtures.set_clock(api, "2026-08-10T00:00:00Z")
    at_start = fixtures.recompute_posture(api, company["id"])
    assertions.assert_company(at_start, disclosure_posture=POSTURE_BLACKOUT)
    assertions.assert_ts_equals(
        at_start["posture_recomputed_at"],
        "2026-08-10T00:00:00.000Z",
        "posture_recomputed_at",
    )
    assert at_start["version"] == before_start["version"] + 1


def test_blackout_window_end_instant_is_outside_the_window(api: ApiClient):
    """PRD §2.7: "The window is therefore half-open: the instant equal to `blackout_window_start` is inside it, and the instant equal to `blackout_window_end` is outside it."
    PRD §2.7: "Otherwise the posture is `OPEN`."
    PRD §2.7: "Whenever the posture is re-derived, `posture_recomputed_at` is stamped with the logical clock's current instant."

    Design: Corner/calculations/blackout_window_is_half_open_at_both_ends
    """
    company = _half_open_window_company(api)

    fixtures.set_clock(api, "2026-08-19T23:59:59Z")
    inside = fixtures.recompute_posture(api, company["id"])
    assertions.assert_company(inside, disclosure_posture=POSTURE_BLACKOUT)
    assertions.assert_ts_equals(
        inside["posture_recomputed_at"],
        "2026-08-19T23:59:59.000Z",
        "posture_recomputed_at",
    )

    fixtures.set_clock(api, "2026-08-20T00:00:00Z")
    at_end = fixtures.recompute_posture(api, company["id"])
    assertions.assert_company(at_end, disclosure_posture=POSTURE_OPEN)
    assertions.assert_ts_equals(
        at_end["posture_recomputed_at"],
        "2026-08-20T00:00:00.000Z",
        "posture_recomputed_at",
    )

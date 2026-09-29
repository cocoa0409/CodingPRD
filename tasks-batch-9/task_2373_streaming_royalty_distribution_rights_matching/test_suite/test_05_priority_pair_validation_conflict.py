"""Competing rejection reasons in the royalty distribution API.

Each claim below drives one request that violates two independent checks at
once, and pins which of the two error identifiers comes back: the period-state
check against the holding-account check when a period is closed, the claim-window
check against the routing-eligibility check when an ownership claim is filed, and
the statutory-floor ratchet against exclusive rate-schedule occupancy when a
proposal is promulgated. Each pair is then re-run with only the lower-priority
defect left standing.
"""

from test_helpers import (
    CANONICAL_SCHEDULE,
    TEST_DEFAULTS,
    TEST_USERS,
    ApiErrorId,
    append_line,
    create_batch,
    create_calculated_pool,
    create_effective_schedule,
    create_holder,
    create_period,
    create_recording,
    create_schedule,
    finalize_pool,
    make_rights_holder_user_headers,
    rights_registration_payload,
    seal_and_match_batch,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    work_version,
)

ADMIN_HEADERS = TEST_USERS["royalty_admin_headers"]
ANALYST_HEADERS = TEST_USERS["rights_ops_analyst_headers"]
REGULATOR_HEADERS = TEST_USERS["regulatory_officer_headers"]

PAST_THE_CLAIM_WINDOW = "2026-08-30T00:00:00Z"


# ─────────────────────────────────────────────────────
# Composite preconditions
# ─────────────────────────────────────────────────────

def _setup_usage_sealed_period_holding_unresolved_money(api):
    """A period whose only reported line reached no better than a title-only
    agreement, whose pool is CALCULATED but not frozen.

    Because the pool was calculated while the claim window was still open, the
    ALL_USAGE denominator parks the whole distributable amount on that single
    unattached line, so the period carries 999999 cents of unresolved holding
    while still sitting in USAGE_SEALED. The clock is then moved past the claim
    window so the close call's own temporal precondition cannot mask either
    defect.
    """
    fixture = {"schedule": create_effective_schedule(api, **CANONICAL_SCHEDULE)}
    fixture["period"] = create_period(api)
    fixture["recording_b"] = create_recording(
        api,
        identifier=TEST_DEFAULTS["RECORDING_B_ISRC"],
        title=TEST_DEFAULTS["RECORDING_B_TITLE"],
        artist=TEST_DEFAULTS["RECORDING_B_ARTIST"],
    )
    fixture["batch"] = create_batch(api, fixture["period"]["id"])
    fixture["usage_line"] = append_line(
        api,
        fixture["batch"]["id"],
        reported_title=TEST_DEFAULTS["RECORDING_B_TITLE"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=500000,
    )
    seal_and_match_batch(api, fixture["batch"]["id"])
    fixture["pool"] = create_calculated_pool(api, fixture["period"]["id"])
    set_clock(api, PAST_THE_CLAIM_WINDOW)
    return fixture


def _setup_matched_usage_for_a_holder_without_a_direct_deal_rate(api):
    """A recording that already carries matched usage in the 2026-06 period, owned
    by nobody, plus a LABEL holder registered without a ``direct_deal_rate_bps``
    so that any DIRECT routing is ineligible.
    """
    fixture = {
        "label": create_holder(
            api,
            legal_name="Kestrel Tapes",
            holder_type="LABEL",
            home_territory_code="GB",
        )
    }
    fixture["period"] = create_period(api)
    fixture["recording_a"] = create_recording(
        api,
        identifier=TEST_DEFAULTS["RECORDING_A_ISRC"],
        title=TEST_DEFAULTS["RECORDING_A_TITLE"],
        artist=TEST_DEFAULTS["RECORDING_A_ARTIST"],
    )
    fixture["batch"] = create_batch(api, fixture["period"]["id"])
    fixture["usage_line"] = append_line(
        api,
        fixture["batch"]["id"],
        reported_isrc=TEST_DEFAULTS["RECORDING_A_ISRC"],
        reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=300000,
    )
    seal_and_match_batch(api, fixture["batch"]["id"])
    fixture["observed_work_version"] = work_version(api, fixture["recording_a"]["id"])
    fixture["payload"] = rights_registration_payload(
        fixture["recording_a"]["id"],
        fixture["label"]["id"],
        fixture["observed_work_version"],
        right_type="MASTER",
        routing="DIRECT",
        share_bps=10000,
        territory_set=["WORLD"],
        effective_from=TEST_DEFAULTS["REGISTRATION_EFFECTIVE_FROM"],
        effective_to=TEST_DEFAULTS["REGISTRATION_EFFECTIVE_TO"],
    )
    return fixture


def _setup_incumbent_floor_with_two_replacement_proposals(api):
    """One EFFECTIVE GB/INDIVIDUAL schedule at a floor of 100 millicents per play
    over 2026-01-01..2026-12-31, and two PROPOSED replacements for the same key
    over the intersecting window 2026-07-01..2027-06-30 — one lowering the floor
    to 80, one preserving it at 100.
    """
    fixture = {"incumbent": create_effective_schedule(api, **CANONICAL_SCHEDULE)}
    replacement = dict(CANONICAL_SCHEDULE)
    replacement.update(
        revenue_share_bps=7500,
        effective_from="2026-07-01",
        effective_to="2027-06-30",
    )
    fixture["lowering"] = create_schedule(
        api,
        **dict(
            replacement,
            proceeding_ref="CRB-2026-LOWER",
            statutory_floor_per_play_millicents=80,
        ),
    )
    fixture["preserving"] = create_schedule(
        api,
        **dict(
            replacement,
            proceeding_ref="CRB-2026-KEEP",
            statutory_floor_per_play_millicents=100,
        ),
    )
    return fixture


# ─────────────────────────────────────────────────────
# period_close_state_beats_holding_account_check
# ─────────────────────────────────────────────────────

class TestPeriodCloseStateBeatsHoldingAccountCheck:
    def test_close_with_both_defects_returns_the_period_state_error(self, api):
        """Closing a USAGE_SEALED period that also holds 999999 unresolved cents
        reports the period-state error, never the holding error.

        PRD: "Checks are therefore evaluated in the following fixed order, and the first failure decides the response."

        Design: Difficulty/priority_pair_validation_conflict/period_close_state_beats_holding_account_check
        """
        fixture = _setup_usage_sealed_period_holding_unresolved_money(api)
        before = validate_success(
            api.get_period(fixture["period"]["id"], ADMIN_HEADERS), 200
        )
        assert before["status"] == "USAGE_SEALED"
        assert before["total_holding_cents"] == 999999

        response = api.close_period(fixture["period"]["id"], ADMIN_HEADERS)
        validate_error(response, ApiErrorId.ERR_INVALID_PERIOD_STATE.value, 409)
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_HOLDING_UNRESOLVED.value
        )

        after = validate_success(
            api.get_period(fixture["period"]["id"], ADMIN_HEADERS), 200
        )
        assert after["status"] == "USAGE_SEALED"
        assert after["total_holding_cents"] == 999999
        assert after["version"] == before["version"]

    def test_close_once_only_the_holding_defect_remains_returns_the_holding_error(self, api):
        """With the state defect repaired by finalizing the pool, the same close
        call on the same money reports the holding error.

        PRD: "Checks are therefore evaluated in the following fixed order, and the first failure decides the response."

        Design: Difficulty/priority_pair_validation_conflict/period_close_state_beats_holding_account_check
        """
        fixture = _setup_usage_sealed_period_holding_unresolved_money(api)
        finalize_pool(api, fixture["pool"]["id"])

        before = validate_success(
            api.get_period(fixture["period"]["id"], ADMIN_HEADERS), 200
        )
        assert before["status"] == "DISTRIBUTED"
        assert before["total_holding_cents"] == 999999

        response = api.close_period(fixture["period"]["id"], ADMIN_HEADERS)
        validate_error(response, ApiErrorId.ERR_HOLDING_UNRESOLVED.value, 422)
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_INVALID_PERIOD_STATE.value
        )

        after = validate_success(
            api.get_period(fixture["period"]["id"], ADMIN_HEADERS), 200
        )
        assert after["status"] == "DISTRIBUTED"
        assert after["total_holding_cents"] == 999999
        assert after["version"] == before["version"]


# ─────────────────────────────────────────────────────
# claim_window_temporal_beats_collective_eligibility
# ─────────────────────────────────────────────────────

class TestClaimWindowTemporalBeatsCollectiveEligibility:
    def test_filing_with_both_defects_returns_the_claim_window_error(self, api):
        """A DIRECT claim by a holder with no direct-deal rate, filed a day after
        the window on a work that carries matched usage, reports the claim-window
        error rather than the routing-eligibility error.

        PRD: "Checks are therefore evaluated in the following fixed order, and the first failure decides the response."

        Design: Difficulty/priority_pair_validation_conflict/claim_window_temporal_beats_collective_eligibility
        """
        fixture = _setup_matched_usage_for_a_holder_without_a_direct_deal_rate(api)
        set_clock(api, PAST_THE_CLAIM_WINDOW)

        response = api.create_rights_registration(
            fixture["payload"],
            make_rights_holder_user_headers(fixture["label"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_CLAIM_WINDOW_CLOSED.value, 422)
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_COLLECTIVE_NOT_ELIGIBLE.value
        )
        registrations, meta = validate_paginated(
            api.list_rights_registrations(
                ADMIN_HEADERS, params={"work_id": fixture["recording_a"]["id"]}
            )
        )
        assert registrations == []
        assert meta["total_count"] == 0
        work = validate_success(
            api.get_work(fixture["recording_a"]["id"], ANALYST_HEADERS), 200
        )
        assert work["version"] == fixture["observed_work_version"]

    def test_the_same_filing_inside_the_window_returns_the_eligibility_error(self, api):
        """With the clock at the inclusive claim-window bound the identical
        payload gets past the temporal check and reports the
        routing-eligibility error instead.

        PRD: "Checks are therefore evaluated in the following fixed order, and the first failure decides the response."

        Design: Difficulty/priority_pair_validation_conflict/claim_window_temporal_beats_collective_eligibility
        """
        fixture = _setup_matched_usage_for_a_holder_without_a_direct_deal_rate(api)
        set_clock(api, TEST_DEFAULTS["PERIOD_CLAIM_WINDOW_CLOSES_AT"])

        response = api.create_rights_registration(
            fixture["payload"],
            make_rights_holder_user_headers(fixture["label"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_COLLECTIVE_NOT_ELIGIBLE.value, 422)
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_CLAIM_WINDOW_CLOSED.value
        )
        registrations, meta = validate_paginated(
            api.list_rights_registrations(
                ADMIN_HEADERS, params={"work_id": fixture["recording_a"]["id"]}
            )
        )
        assert registrations == []
        assert meta["total_count"] == 0
        work = validate_success(
            api.get_work(fixture["recording_a"]["id"], ANALYST_HEADERS), 200
        )
        assert work["version"] == fixture["observed_work_version"]


# ─────────────────────────────────────────────────────
# rate_floor_ratchet_beats_schedule_overlap
# ─────────────────────────────────────────────────────

class TestRateFloorRatchetBeatsScheduleOverlap:
    def test_promulgation_with_both_defects_returns_the_floor_error(self, api):
        """A proposal that both lowers the statutory floor and collides with the
        incumbent's window reports the floor breach, not the overlap.

        PRD: "Checks are therefore evaluated in the following fixed order, and the first failure decides the response."

        Design: Difficulty/priority_pair_validation_conflict/rate_floor_ratchet_beats_schedule_overlap
        """
        fixture = _setup_incumbent_floor_with_two_replacement_proposals(api)

        response = api.promulgate_rate_schedule(
            fixture["lowering"]["id"], REGULATOR_HEADERS, {}
        )
        validate_error(response, ApiErrorId.ERR_STATUTORY_RATE_FLOOR_BREACH.value, 422)
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_RATE_SCHEDULE_OVERLAP.value
        )

        lowering = validate_success(
            api.get_rate_schedule(fixture["lowering"]["id"], REGULATOR_HEADERS), 200
        )
        assert lowering["status"] == "PROPOSED"
        assert lowering["promulgated_at"] is None
        incumbent = validate_success(
            api.get_rate_schedule(fixture["incumbent"]["id"], REGULATOR_HEADERS), 200
        )
        assert incumbent["status"] == "EFFECTIVE"

    def test_the_supersede_flag_does_not_cure_the_floor_breach(self, api):
        """Asking to displace the incumbent removes the occupancy defect but
        leaves the ratchet defect, so the floor breach still decides the response.

        PRD: "The schedule's `revenue_share_bps` must be at least 5,000 basis points, the statutory minimum revenue share below which no proceeding may set a rate, and its `statutory_floor_per_play_millicents` must not be strictly below the value carried by the incumbent `EFFECTIVE` schedule for the same territory and tier — regulatory floors ratchet upward only."

        Design: Difficulty/priority_pair_validation_conflict/rate_floor_ratchet_beats_schedule_overlap
        """
        fixture = _setup_incumbent_floor_with_two_replacement_proposals(api)

        response = api.promulgate_rate_schedule(
            fixture["lowering"]["id"], REGULATOR_HEADERS, {"supersede_incumbent": True}
        )
        validate_error(response, ApiErrorId.ERR_STATUTORY_RATE_FLOOR_BREACH.value, 422)
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_RATE_SCHEDULE_OVERLAP.value
        )

        lowering = validate_success(
            api.get_rate_schedule(fixture["lowering"]["id"], REGULATOR_HEADERS), 200
        )
        assert lowering["status"] == "PROPOSED"
        incumbent = validate_success(
            api.get_rate_schedule(fixture["incumbent"]["id"], REGULATOR_HEADERS), 200
        )
        assert incumbent["status"] == "EFFECTIVE"

    def test_promulgation_with_only_the_overlap_defect_returns_the_overlap_error(self, api):
        """Preserving the floor removes the ratchet defect, so the same
        promulgation now reports the occupancy overlap.

        PRD: "Checks are therefore evaluated in the following fixed order, and the first failure decides the response."

        Design: Difficulty/priority_pair_validation_conflict/rate_floor_ratchet_beats_schedule_overlap
        """
        fixture = _setup_incumbent_floor_with_two_replacement_proposals(api)

        response = api.promulgate_rate_schedule(
            fixture["preserving"]["id"], REGULATOR_HEADERS, {}
        )
        validate_error(response, ApiErrorId.ERR_RATE_SCHEDULE_OVERLAP.value, 409)
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_STATUTORY_RATE_FLOOR_BREACH.value
        )

        preserving = validate_success(
            api.get_rate_schedule(fixture["preserving"]["id"], REGULATOR_HEADERS), 200
        )
        assert preserving["status"] == "PROPOSED"
        assert preserving["promulgated_at"] is None

    def test_the_floor_preserving_proposal_displaces_the_incumbent_with_the_flag(self, api):
        """With the floor preserved and the flag supplied, the overlap is cured
        and the proposal takes force while the incumbent is displaced.

        PRD: "And occupancy must be exclusive: promulgation is refused with `ERR_RATE_SCHEDULE_OVERLAP` when another `EFFECTIVE` schedule exists for the same `territory_code` and `subscription_tier` whose closed window overlaps this one's — and touching endpoints do count as an overlap — unless `supersede_incumbent` is true, in which case the incumbent is displaced first and no conflict remains."

        Design: Difficulty/priority_pair_validation_conflict/rate_floor_ratchet_beats_schedule_overlap
        """
        fixture = _setup_incumbent_floor_with_two_replacement_proposals(api)

        promulgated = validate_success(
            api.promulgate_rate_schedule(
                fixture["preserving"]["id"],
                REGULATOR_HEADERS,
                {"supersede_incumbent": True},
            ),
            200,
        )
        assert promulgated["status"] == "EFFECTIVE"
        assert promulgated["promulgated_at"] is not None

        incumbent = validate_success(
            api.get_rate_schedule(fixture["incumbent"]["id"], REGULATOR_HEADERS), 200
        )
        assert incumbent["status"] == "SUPERSEDED"
        lowering = validate_success(
            api.get_rate_schedule(fixture["lowering"]["id"], REGULATOR_HEADERS), 200
        )
        assert lowering["status"] == "PROPOSED"

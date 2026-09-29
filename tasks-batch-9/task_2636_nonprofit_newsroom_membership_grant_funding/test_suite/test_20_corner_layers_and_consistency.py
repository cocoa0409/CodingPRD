"""Cross-cutting layers and same-request consistency: the two optimistic
concurrency guards, the version counter itself, the cumulative major-donor latch
and a settlement whose effects are visible with no second write.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    benefit_payload,
    change_member_tier,
    create_published_tier,
    define_tier,
    enrol_member,
    member_lifecycle,
    open_fiscal_period,
    publish_tier,
    read_coverage_area,
    read_contribution,
    read_funder,
    read_member,
    read_sustainability,
    record_contribution,
    register_coverage_area,
    register_funder,
    rule_on_funder,
    settle_contribution,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import DO_HEADERS, ED_HEADERS, FC_HEADERS
from test_helpers.test_users import USER_IDS

_CLIMATE_TEXT = (
    "Ironwood funds climate coverage; the climate desk retains editorial control."
)


def _setup_climate_beat_and_a_cleared_funder():
    """One beat and one funder whose version is captured both before and after the
    independence clearance that mutates it."""
    area = register_coverage_area(area_code="CLIMATE", name="Climate")
    funder = register_funder(legal_name="Ironwood Trust", funder_type="FOUNDATION")
    pre_clearance_version = funder["version"]
    cleared = rule_on_funder(funder["id"], "CLEAR", "SELF_ATTESTED")
    return {
        "area": area,
        "funder": cleared,
        "pre_clearance_version": pre_clearance_version,
        "post_clearance_version": cleared["version"],
    }


def _file(funder_id, coverage_area_id, expected_funder_version):
    return api_client.create_firewall_disclosure(
        {
            "funder_id": funder_id,
            "coverage_area_id": coverage_area_id,
            "disclosure_text": _CLIMATE_TEXT,
            "expected_funder_version": expected_funder_version,
        },
        ED_HEADERS,
    )


class TestDisclosureCreateGuardsOnTheParentFunderVersion:
    """The version quoted is the funder's, and the clearance already moved it."""

    def test_the_version_captured_at_registration_is_already_stale(self):
        """The clearance advanced the funder, so the registration version is refused
        with 412 and nothing is filed.

        PRD: "`POST /firewall-disclosures` requires a non-optional
        `expected_funder_version` field carrying the client's last observed
        `version` of the target `Funder`. If that value does not equal the funder's
        current `version`, the create is rejected with `ERR_STALE_FUNDER_VERSION`
        (HTTP 412)."

        Design: Corner/Cross-Cutting Complexity Layers/occ_disclosure_create_with_a_stale_funder_version_is_rejected
        """
        ctx = _setup_climate_beat_and_a_cleared_funder()
        assert ctx["post_clearance_version"] == ctx["pre_clearance_version"] + 1

        validate_error(
            _file(
                ctx["funder"]["id"],
                ctx["area"]["id"],
                ctx["pre_clearance_version"],
            ),
            ApiErrorId.ERR_STALE_FUNDER_VERSION,
        )

        _, meta = validate_paginated(api_client.list_firewall_disclosures(ED_HEADERS))
        assert meta["total_count"] == 0
        assert read_coverage_area(ctx["area"]["id"])["disclosed_funder_count"] == 0

    def test_the_post_clearance_version_files_the_same_disclosure(self):
        """Only the quoted version changes, and the identical body is now accepted.

        PRD: "A new disclosure is created in status `ACTIVE`, with
        `attested_by_user_id` stamped with the filing director's `X-User-ID`,
        `attested_at` stamped with the logical clock, and `reattestation_reason`
        null."

        Design: Corner/Cross-Cutting Complexity Layers/occ_disclosure_create_with_a_stale_funder_version_is_rejected
        """
        ctx = _setup_climate_beat_and_a_cleared_funder()
        validate_error(
            _file(ctx["funder"]["id"], ctx["area"]["id"], ctx["pre_clearance_version"]),
            ApiErrorId.ERR_STALE_FUNDER_VERSION,
        )

        created = validate_success(
            _file(
                ctx["funder"]["id"],
                ctx["area"]["id"],
                ctx["post_clearance_version"],
            ),
            expected_status=201,
        )
        assert created["status"] == "ACTIVE"
        assert created["funder_id"] == ctx["funder"]["id"]
        assert created["coverage_area_id"] == ctx["area"]["id"]
        assert created["disclosure_text"] == _CLIMATE_TEXT
        assert created["supersedes_disclosure_id"] is None
        assert created["attested_by_user_id"] == USER_IDS["editorial_director"]
        assert created["attested_at"].startswith("2026-08-01T00:00:00")
        assert created["reattestation_reason"] is None
        assert created["version"] == 1

    def test_the_rejected_attempt_leaves_the_funder_exactly_where_it_was(self):
        """A refused create is not a mutation of the parent row either.

        PRD: "`version`, a system-managed integer that starts at 1 on creation and
        increments by exactly 1 on every mutation of that row - including mutations
        that only touch computed fields, and including mutations produced by a
        cascade the client never asked for directly."

        Design: Corner/Cross-Cutting Complexity Layers/occ_disclosure_create_with_a_stale_funder_version_is_rejected
        """
        ctx = _setup_climate_beat_and_a_cleared_funder()
        validate_error(
            _file(ctx["funder"]["id"], ctx["area"]["id"], ctx["pre_clearance_version"]),
            ApiErrorId.ERR_STALE_FUNDER_VERSION,
        )

        funder = read_funder(ctx["funder"]["id"])
        assert funder["status"] == "CLEARED"
        assert funder["version"] == ctx["post_clearance_version"]
        assert funder["risk_basis"] == "SELF_ATTESTED"


def _setup_renewed_member_on_the_monthly_tier():
    """A member enrolled on SUSTAINER, activated by a settled 2500-cent
    contribution and then renewed, with a second ANNUAL tier standing ready."""
    period = open_fiscal_period()
    sustainer = create_published_tier(
        benefits=[],
        tier_code="SUSTAINER",
        name="Sustainer",
        renewal_cadence="MONTHLY",
        contribution_amount_cents=2500,
    )
    patron = create_published_tier(
        benefits=[benefit_payload("GALA", "EVENT_ACCESS", 6000)],
        tier_code="PATRON",
        name="Patron",
        renewal_cadence="ANNUAL",
        contribution_amount_cents=30000,
    )
    member = enrol_member(
        sustainer["id"], email="ana@example.org", full_name="Ana Ruiz"
    )
    enrolment_version = member["version"]
    contribution = record_contribution(
        period["id"],
        "MEMBERSHIP",
        2500,
        member_id=member["id"],
        received_date="2026-08-01",
    )
    settle_contribution(contribution["id"])
    renewed = member_lifecycle(member["id"], "RENEW")
    return {
        "period": period,
        "sustainer": sustainer,
        "patron": patron,
        "member": renewed,
        "contribution": contribution,
        "enrolment_version": enrolment_version,
    }


def _change_tier(member_id, new_tier_id, expected_member_version):
    return api_client.member_tier_change(
        member_id,
        {
            "new_tier_id": new_tier_id,
            "expected_member_version": expected_member_version,
        },
        DO_HEADERS,
    )


class TestTierChangeGuardsOnTheMemberVersion:
    """Activation and renewal both moved the row the client thinks it is holding."""

    def test_the_enrolment_version_is_stale_two_mutations_later(self):
        """Settlement-driven activation and the renewal each advanced the member, so
        the version captured at enrolment is refused and the tier is untouched.

        PRD: "`POST /members/{id}/tier-change` requires a non-optional
        `expected_member_version` field carrying the client's last observed
        `version` of the target `Member`. If that value does not equal the member's
        current `version`, the request is rejected with `ERR_STALE_MEMBER_VERSION`
        (HTTP 412)."

        Design: Corner/Cross-Cutting Complexity Layers/occ_tier_change_with_a_stale_member_version_is_rejected
        """
        ctx = _setup_renewed_member_on_the_monthly_tier()
        assert ctx["member"]["version"] == ctx["enrolment_version"] + 2

        validate_error(
            _change_tier(
                ctx["member"]["id"], ctx["patron"]["id"], ctx["enrolment_version"]
            ),
            ApiErrorId.ERR_STALE_MEMBER_VERSION,
        )

        unchanged = read_member(ctx["member"]["id"])
        assert unchanged["tier_id"] == ctx["sustainer"]["id"]
        assert unchanged["status"] == "ACTIVE"
        assert unchanged["version"] == ctx["member"]["version"]
        assert unchanged["consecutive_renewals"] == 1

    def test_the_current_version_repoints_the_member_and_advances_it_once(self):
        """Replaying the same call against the version the read just reported
        succeeds and costs exactly one more increment.

        PRD: "On success the member's `tier_id` is repointed at the new tier,
        `next_renewal_date` is re-derived under the new cadence, and - this is the
        cross-entity part that is easy to miss - the quid-pro-quo and deductible
        split is recomputed on **every** contribution of this member whose
        acknowledgment status is still `UNACKNOWLEDGED`."

        Design: Corner/Cross-Cutting Complexity Layers/occ_tier_change_with_a_stale_member_version_is_rejected
        """
        ctx = _setup_renewed_member_on_the_monthly_tier()
        validate_error(
            _change_tier(
                ctx["member"]["id"], ctx["patron"]["id"], ctx["enrolment_version"]
            ),
            ApiErrorId.ERR_STALE_MEMBER_VERSION,
        )

        current = read_member(ctx["member"]["id"])
        changed = change_member_tier(
            ctx["member"]["id"], ctx["patron"]["id"], current["version"]
        )
        assert changed["tier_id"] == ctx["patron"]["id"]
        assert changed["status"] == "ACTIVE"
        assert changed["version"] == current["version"] + 1
        assert changed["cycle_start_date"] == "2026-09-01"
        assert changed["next_renewal_date"] == "2027-09-01"

    def test_the_unacknowledged_contribution_is_re_split_against_the_new_tier(self):
        """The 2500-cent row was worth 2500 deductible under SUSTAINER; PATRON's
        6000-cent gala benefit swallows it whole.

        PRD: "A `MEMBERSHIP` contribution takes `quid_pro_quo_cents` from the
        `quid_pro_quo_per_period_cents` of the tier the member references *at the
        moment of evaluation*, and `deductible_cents` is `amount_cents` minus that
        value floored at 0."

        Design: Corner/Cross-Cutting Complexity Layers/occ_tier_change_with_a_stale_member_version_is_rejected
        """
        ctx = _setup_renewed_member_on_the_monthly_tier()
        assert ctx["patron"]["quid_pro_quo_per_period_cents"] == 6000

        before = read_contribution(ctx["contribution"]["id"])
        assert before["acknowledgment_status"] == "UNACKNOWLEDGED"
        assert before["quid_pro_quo_cents"] == 0
        assert before["deductible_cents"] == 2500

        current = read_member(ctx["member"]["id"])
        change_member_tier(
            ctx["member"]["id"], ctx["patron"]["id"], current["version"]
        )

        after = read_contribution(ctx["contribution"]["id"])
        assert after["acknowledgment_status"] == "UNACKNOWLEDGED"
        assert after["quid_pro_quo_cents"] == 6000
        assert after["deductible_cents"] == 0
        assert after["settlement_status"] == "SETTLED"


def _setup_one_funder_and_one_draft_tier():
    """A freshly registered funder and a freshly defined tier, each about to take
    exactly one write."""
    funder = register_funder(legal_name="Ironwood Trust", funder_type="FOUNDATION")
    tier = define_tier(
        benefits=[],
        tier_code="SUSTAINER",
        name="Sustainer",
        renewal_cadence="MONTHLY",
        contribution_amount_cents=2500,
    )
    return {"funder": funder, "tier": tier}


def _read_tier(tier_id):
    return validate_success(api_client.get_membership_tier(tier_id, DO_HEADERS))


class TestVersionAdvancesOncePerWriteAndNeverOnARead:
    """The counter the two concurrency guards depend on."""

    def test_reads_leave_the_funder_version_where_the_create_left_it(self):
        """Two reads on either side of the clearance report the pre-write value and
        then the post-write value, never a value of their own.

        PRD: "`version`, a system-managed integer that starts at 1 on creation and
        increments by exactly 1 on every mutation of that row - including mutations
        that only touch computed fields, and including mutations produced by a
        cascade the client never asked for directly."

        Design: Corner/Cross-Cutting Complexity Layers/occ_version_increments_by_exactly_one_per_write_and_never_on_a_read
        """
        ctx = _setup_one_funder_and_one_draft_tier()
        created_version = ctx["funder"]["version"]
        assert created_version == 1

        assert read_funder(ctx["funder"]["id"])["version"] == created_version
        assert read_funder(ctx["funder"]["id"])["version"] == created_version

        rule_on_funder(
            ctx["funder"]["id"], "CLEAR", "AUDITED", audited_advocacy_index=4
        )

        assert read_funder(ctx["funder"]["id"])["version"] == created_version + 1
        assert read_funder(ctx["funder"]["id"])["version"] == created_version + 1

    def test_the_clearance_advances_the_funder_by_one_however_much_it_recomputes(self):
        """The ruling rewrites the basis, the stored index and the score, and still
        costs a single increment.

        PRD: "Either decision sets `risk_basis` to the submitted `basis`, stores
        `audited_advocacy_index` when the basis is `AUDITED`, and re-scores the
        funder on that variant before any threshold is examined."

        Design: Corner/Cross-Cutting Complexity Layers/occ_version_increments_by_exactly_one_per_write_and_never_on_a_read
        """
        ctx = _setup_one_funder_and_one_draft_tier()
        created_version = ctx["funder"]["version"]
        assert ctx["funder"]["risk_basis"] == "SELF_ATTESTED"
        assert ctx["funder"]["audited_advocacy_index"] is None
        assert ctx["funder"]["independence_risk_score"] == 10

        cleared = rule_on_funder(
            ctx["funder"]["id"], "CLEAR", "AUDITED", audited_advocacy_index=4
        )
        assert cleared["status"] == "CLEARED"
        assert cleared["risk_basis"] == "AUDITED"
        assert cleared["audited_advocacy_index"] == 4
        assert cleared["independence_risk_score"] == 26
        assert cleared["cleared_by_user_id"] == USER_IDS["editorial_director"]
        assert cleared["version"] == created_version + 1

    def test_publishing_advances_the_tier_by_one_and_reads_do_not(self):
        """The tier's own counter behaves identically under its own single write.

        PRD: "Publishing it is a separate step by a `DevelopmentOfficer` that takes
        the tier `DRAFT -> PUBLISHED` and stamps `published_at` with the logical
        clock."

        Design: Corner/Cross-Cutting Complexity Layers/occ_version_increments_by_exactly_one_per_write_and_never_on_a_read
        """
        ctx = _setup_one_funder_and_one_draft_tier()
        created_version = ctx["tier"]["version"]
        assert ctx["tier"]["status"] == "DRAFT"
        assert _read_tier(ctx["tier"]["id"])["version"] == created_version

        published = publish_tier(ctx["tier"]["id"])
        assert published["status"] == "PUBLISHED"
        assert published["published_at"].startswith("2026-08-01T00:00:00")
        assert published["version"] == created_version + 1
        assert _read_tier(ctx["tier"]["id"])["version"] == created_version + 1


def _setup_member_one_cent_short_of_the_latch():
    """Two settled membership contributions of 494999 and 2500 cents, plus a third
    2501-cent row still sitting unsettled."""
    period = open_fiscal_period()
    tier = create_published_tier(
        benefits=[],
        tier_code="SUSTAINER",
        name="Sustainer",
        renewal_cadence="MONTHLY",
        contribution_amount_cents=2500,
    )
    member = enrol_member(tier["id"], email="ana@example.org", full_name="Ana Ruiz")
    for amount in (494999, 2500):
        settled = record_contribution(
            period["id"],
            "MEMBERSHIP",
            amount,
            member_id=member["id"],
            received_date="2026-08-01",
        )
        settle_contribution(settled["id"])
    third = record_contribution(
        period["id"],
        "MEMBERSHIP",
        2501,
        member_id=member["id"],
        received_date="2026-08-01",
    )
    return {"period": period, "tier": tier, "member": member, "third": third}


class TestMajorDonorLatchTripsExactlyAtTheThreshold:
    """497499 is not a major donor; 500000 is."""

    def test_two_settled_contributions_leave_the_row_one_cent_short(self):
        """The unsettled third row counts for nothing, so the running total is
        497499 and both latches are still open.

        PRD: "`lifetime_giving_cents` is the sum of `amount_cents` over every
        contribution of this member whose settlement status is `SETTLED`, across all
        fiscal periods."

        Design: Corner/Cross-Cutting Complexity Layers/layer_major_donor_latch_trips_exactly_at_the_cumulative_threshold
        """
        ctx = _setup_member_one_cent_short_of_the_latch()

        member = read_member(ctx["member"]["id"])
        assert member["lifetime_giving_cents"] == 497499
        assert member["is_major_donor"] is False
        assert member["cultivation_locked"] is False
        assert member["status"] == "ACTIVE"
        assert read_contribution(ctx["third"]["id"])["settlement_status"] == "INITIATED"

    def test_the_third_settlement_lands_on_the_threshold_itself(self):
        """2501 more cents makes exactly 500000, and the inclusive comparison closes
        both latches on the spot.

        PRD: "A member is a major donor - `is_major_donor` true - once
        `lifetime_giving_cents` reaches **5,000 dollars**; the comparison is
        inclusive, so a member sitting at exactly 500000 cents is a major donor."

        Design: Corner/Cross-Cutting Complexity Layers/layer_major_donor_latch_trips_exactly_at_the_cumulative_threshold
        """
        ctx = _setup_member_one_cent_short_of_the_latch()

        settled = settle_contribution(ctx["third"]["id"])
        assert settled["settlement_status"] == "SETTLED"

        member = read_member(ctx["member"]["id"])
        assert member["lifetime_giving_cents"] == 500000
        assert member["is_major_donor"] is True
        assert member["cultivation_locked"] is True
        assert member["status"] == "ACTIVE"

    def test_the_latched_member_is_findable_through_the_major_donor_filter(self):
        """The recomputed flag is queryable immediately, and it is the only row that
        matches.

        PRD: "A member row may be read individually, and the collection may be
        listed with optional `tier_id`, `linked_funder_id`, `status` and
        `is_major_donor` filters."

        Design: Corner/Cross-Cutting Complexity Layers/layer_major_donor_latch_trips_exactly_at_the_cumulative_threshold
        """
        ctx = _setup_member_one_cent_short_of_the_latch()

        empty, empty_meta = validate_paginated(
            api_client.list_members(DO_HEADERS, params={"is_major_donor": "true"})
        )
        assert empty == []
        assert empty_meta["total_count"] == 0

        settle_contribution(ctx["third"]["id"])

        rows, meta = validate_paginated(
            api_client.list_members(DO_HEADERS, params={"is_major_donor": "true"})
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == ctx["member"]["id"]
        assert rows[0]["is_major_donor"] is True


def _setup_pending_member_with_an_unsettled_annual_contribution():
    """A 100000-cent membership row still in `INITIATED`, against a benefit-free
    ANNUAL tier and a period holding 500000 cents of reserve."""
    period = open_fiscal_period(
        label="FY2027",
        start_date="2026-08-01",
        end_date="2027-07-31",
        monthly_expense_base_cents=200000,
        reserve_balance_cents=500000,
    )
    tier = create_published_tier(
        benefits=[],
        tier_code="PATRON",
        name="Patron",
        renewal_cadence="ANNUAL",
        contribution_amount_cents=100000,
    )
    member = enrol_member(tier["id"], email="ana@example.org", full_name="Ana Ruiz")
    contribution = record_contribution(
        period["id"],
        "MEMBERSHIP",
        100000,
        member_id=member["id"],
        received_date="2026-08-01",
    )
    return {
        "period": period,
        "tier": tier,
        "member": member,
        "contribution": contribution,
    }


class TestSettlementRepricesMemberAndPeriodWithinTheSameRequest:
    """No sweep, no second write: the money lands and everything downstream of it
    is already correct."""

    def test_the_period_reads_empty_while_the_money_is_still_initiated(self):
        """An `INITIATED` contribution recognizes nothing, so the picture is the one
        the period opened with.

        PRD: "A period opens in status `OPEN` with `board_override_active` false,
        `board_override_justification` null and `locked_at` null, and with its full
        sustainability picture derived immediately - over an empty revenue input
        set, so `recognized_revenue_cents`, `concentration_hhi` and
        `top_source_share_bps` all start at 0, `reserve_months_target` starts at the
        base policy figure of three months, and `operating_reserve_target_cents`
        starts at three times the supplied expense base."

        Design: Corner/Consistency Model/cm_settlement_recomputes_member_and_period_state_within_the_same_request
        """
        ctx = _setup_pending_member_with_an_unsettled_annual_contribution()

        picture = read_sustainability(ctx["period"]["id"])
        assert picture["basis"] == "RECOGNIZED"
        assert picture["recognized_revenue_cents"] == 0
        assert picture["membership_share_bps"] == 0
        assert picture["concentration_hhi"] == 0
        assert picture["top_source_share_bps"] == 0
        assert picture["reserve_months_target"] == 3
        assert picture["operating_reserve_target_cents"] == 600000
        assert picture["reserve_months_ratio_bps"] == 25000
        assert picture["sustainability_posture"] == "WATCH"
        assert picture["restricted_release_cap_pct_bps"] == 6000
        assert read_member(ctx["member"]["id"])["status"] == "PENDING"

    def test_the_settlement_response_itself_carries_the_settled_split(self):
        """The split was frozen at creation against a benefit-free tier, and the
        settlement response reports it alongside the new settlement status.

        PRD: "At creation - and for the `MAJOR_GIFT` row the gift-acceptance cascade
        writes - the contribution's `quid_pro_quo_cents` and `deductible_cents` are
        computed from its stream."

        Design: Corner/Consistency Model/cm_settlement_recomputes_member_and_period_state_within_the_same_request
        """
        ctx = _setup_pending_member_with_an_unsettled_annual_contribution()

        settled = validate_success(
            api_client.settle_contribution(
                ctx["contribution"]["id"], {"outcome": "SETTLED"}, FC_HEADERS
            )
        )
        assert settled["settlement_status"] == "SETTLED"
        assert settled["quid_pro_quo_cents"] == 0
        assert settled["deductible_cents"] == 100000
        assert settled["revenue_stream"] == "MEMBERSHIP"
        assert settled["acknowledgment_status"] == "UNACKNOWLEDGED"

    def test_the_member_is_active_on_the_very_next_read(self):
        """Activation is a side effect of the same request: the cycle is anchored on
        the contribution's `received_date` and the annual schedule already runs from
        it.

        PRD: "`SETTLED` requires the fiscal period to be `OPEN` and is where money
        becomes real: a `MEMBERSHIP` settlement recomputes the member's
        `lifetime_giving_cents`, `is_major_donor` and `cultivation_locked` and, for a
        `PENDING` member, sets `cycle_start_date` to the contribution's
        `received_date` and runs the renewal schedule of §3.3 to activate them"

        Design: Corner/Consistency Model/cm_settlement_recomputes_member_and_period_state_within_the_same_request
        """
        ctx = _setup_pending_member_with_an_unsettled_annual_contribution()
        settle_contribution(ctx["contribution"]["id"])

        member = read_member(ctx["member"]["id"])
        assert member["status"] == "ACTIVE"
        assert member["cycle_start_date"] == "2026-08-01"
        assert member["next_renewal_date"] == "2027-08-01"
        assert member["grace_expires_at"] is None
        assert member["consecutive_renewals"] == 0
        assert member["lifetime_giving_cents"] == 100000
        assert member["is_major_donor"] is False
        assert member["cultivation_locked"] is False

    def test_the_reserve_target_is_already_repriced_by_the_concentration(self):
        """One stream carrying everything is an HHI of 10000, which buys a fourth
        month of target reserve - but not a fifth, because a member is not an
        institutional source.

        PRD: "Third, `reserve_months_target` starts at a base of 3 months and gains
        one month if `concentration_hhi` is at least 3000 and one further month if
        `top_source_share_bps` is at least 3500 - so the target is 3, 4 or 5 months.
        Fourth, `operating_reserve_target_cents` is `monthly_expense_base_cents`
        multiplied by `reserve_months_target`."

        Design: Corner/Consistency Model/cm_settlement_recomputes_member_and_period_state_within_the_same_request
        """
        ctx = _setup_pending_member_with_an_unsettled_annual_contribution()
        settle_contribution(ctx["contribution"]["id"])

        picture = read_sustainability(ctx["period"]["id"])
        assert picture["recognized_revenue_cents"] == 100000
        assert picture["membership_share_bps"] == 10000
        assert picture["major_gift_share_bps"] == 0
        assert picture["grants_share_bps"] == 0
        assert picture["concentration_hhi"] == 10000
        assert picture["top_source_share_bps"] == 0
        assert picture["reserve_months_target"] == 4
        assert picture["operating_reserve_target_cents"] == 800000
        assert picture["reserve_months_ratio_bps"] == 25000
        assert picture["sustainability_posture"] == "WATCH"
        assert picture["restricted_release_cap_pct_bps"] == 6000

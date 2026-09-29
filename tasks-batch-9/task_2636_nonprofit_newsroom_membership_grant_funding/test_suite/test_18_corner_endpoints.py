"""Endpoint-shaped behaviour: a computed public read, a warrant-gated board
lever, the three-verb member action endpoint, two-sided link resolution and
filtered pagination over funders.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_published_tier,
    enrol_member,
    open_fiscal_period,
    read_coverage_area,
    read_fiscal_period,
    read_funder,
    read_member,
    read_sustainability,
    read_transparency_report,
    record_contribution,
    register_coverage_area,
    register_funder,
    rule_on_funder,
    settle_contribution,
    setup_awarded_restricted_proposal,
    setup_cleared_funder,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import BO_HEADERS, DO_HEADERS, ED_HEADERS
from test_helpers.test_users import USER_IDS

_UNKNOWN_AREA_ID = "00000000-0000-4000-8000-000000000000"


def _setup_disclosed_beat_with_one_restricted_award():
    """HOUSING carries one ACTIVE disclosure for a CLEARED foundation that holds a
    PROJECT_RESTRICTED 350000-cent award."""
    return setup_awarded_restricted_proposal(
        requested_amount_cents=350000,
        award_date="2026-08-01",
        reporting_cadence="ANNUAL",
        restriction_type="PROJECT_RESTRICTED",
        restriction_start_date="2026-09-01",
        restriction_end_date="2027-07-31",
        area_code="HOUSING",
        legal_name="Ironwood Trust",
        title="Housing accountability project",
    )


class TestTransparencyReportIsAComputedReadOverDisclosuresAndAwards:
    def test_the_public_read_is_assembled_from_the_disclosure_and_the_award(self):
        """Nothing in the response is a column the beat stores: the funder count
        comes from the disclosure, the grant count and the committed total from the
        award.

        PRD: "A transparency read of a coverage area returns its `area_code`, its
        current `publication_gate` and `disclosure_status`, its
        `disclosed_funder_count` and `restricted_grant_count`, the array of distinct
        funder identifiers disclosed against the beat as `disclosed_funder_ids`, and
        `total_committed_cents`, the aggregate committed against the beat."

        Design: Corner/Endpoints/ep_transparency_report_is_a_computed_read_over_disclosures_and_awards
        """
        ctx = _setup_disclosed_beat_with_one_restricted_award()

        report = read_transparency_report(ctx["area"]["id"])
        assert report["area_code"] == "HOUSING"
        assert report["publication_gate"] == "OPEN"
        assert report["disclosure_status"] == "CURRENT"
        assert report["disclosed_funder_count"] == 1
        assert report["restricted_grant_count"] == 1
        assert report["disclosed_funder_ids"] == [ctx["funder"]["id"]]
        assert report["total_committed_cents"] == 350000

    def test_the_committed_total_matches_the_funders_own_lifetime_figure(self):
        """The same award drives the funder's lifetime commitment, so the two
        independently computed figures agree at 350000.

        PRD: "The funder's `lifetime_committed_cents` and the beat's
        `restricted_grant_count` are re-derived, every sustainability field of the
        fiscal period is re-derived on the recognized basis, and the proposal's
        `version` increments by 1."

        Design: Corner/Endpoints/ep_transparency_report_is_a_computed_read_over_disclosures_and_awards
        """
        ctx = _setup_disclosed_beat_with_one_restricted_award()

        funder = read_funder(ctx["funder"]["id"])
        assert funder["lifetime_committed_cents"] == 350000

        report = read_transparency_report(ctx["area"]["id"])
        assert report["total_committed_cents"] == funder["lifetime_committed_cents"]
        assert read_coverage_area(ctx["area"]["id"])["restricted_grant_count"] == 1


def _setup_reserve_rich_empty_period():
    """One empty period with a 1000000-cent reserve against a 200000-cent monthly
    base."""
    return open_fiscal_period(
        monthly_expense_base_cents=200000, reserve_balance_cents=1000000
    )


def _file_override(period_id, justification):
    return api_client.fiscal_period_board_override(
        period_id, {"justification": justification}, BO_HEADERS
    )


class TestBoardOverrideIsRejectedWhenConcentrationIsNotElevated:
    def test_five_months_of_reserve_over_no_revenue_reads_healthy(self):
        """With no revenue the HHI is 0, so the target stays at the base three
        months and a 1000000-cent balance is a fully funded reserve.

        PRD: "Third, `reserve_months_target` starts at a base of 3 months and gains
        one month if `concentration_hhi` is at least 3000 and one further month if
        `top_source_share_bps` is at least 3500 - so the target is 3, 4 or 5
        months."

        Design: Corner/Endpoints/ep_board_override_is_rejected_when_concentration_is_not_elevated
        """
        period = _setup_reserve_rich_empty_period()

        picture = read_sustainability(period["id"])
        assert picture["recognized_revenue_cents"] == 0
        assert picture["concentration_hhi"] == 0
        assert picture["reserve_months_target"] == 3
        assert picture["operating_reserve_target_cents"] == 600000
        assert picture["reserve_months_ratio_bps"] == 50000
        assert picture["sustainability_posture"] == "HEALTHY"
        assert picture["restricted_release_cap_pct_bps"] == 10000

    def test_the_override_is_refused_and_nothing_is_recorded(self):
        """Neither warrant is present - the HHI is 0 and the posture is HEALTHY - so
        the justification text is never stored.

        PRD: "The board may only file an override where one is warranted: either
        `concentration_hhi` has reached 4500 or more, or `sustainability_posture` is
        `CONSTRAINED` or `CRITICAL`."

        Design: Corner/Endpoints/ep_board_override_is_rejected_when_concentration_is_not_elevated
        """
        period = _setup_reserve_rich_empty_period()

        validate_error(
            _file_override(
                period["id"],
                "Pre-emptive override before any revenue is recognized.",
            ),
            ApiErrorId.ERR_BOARD_OVERRIDE_NOT_WARRANTED,
        )

        unchanged = read_fiscal_period(period["id"])
        assert unchanged["board_override_active"] is False
        assert unchanged["board_override_justification"] is None
        assert unchanged["status"] == "OPEN"


def _setup_member_activated_on_the_first_of_august():
    """A member activated on 2026-08-01 by settling a 2500-cent monthly membership
    contribution; the clock is never advanced."""
    period = open_fiscal_period()
    tier = create_published_tier(
        benefits=[],
        tier_code="SUSTAINER",
        name="Sustainer",
        renewal_cadence="MONTHLY",
        contribution_amount_cents=2500,
    )
    member = enrol_member(tier["id"], email="ana@example.org", full_name="Ana Ruiz")
    contribution = record_contribution(
        period["id"],
        "MEMBERSHIP",
        2500,
        member_id=member["id"],
        received_date="2026-08-01",
    )
    settle_contribution(contribution["id"])
    return {"period": period, "tier": tier, "member": read_member(member["id"])}


def _lifecycle(member_id, action):
    return api_client.member_lifecycle_action(
        member_id, {"action": action}, DO_HEADERS
    )


class TestMemberCancelActionClearsTheRenewalScheduleAndLocksTheRow:
    def test_the_settled_contribution_left_a_schedule_to_clear(self):
        """Activation is a side effect of settlement, and the monthly calendar step
        off 2026-08-01 puts the next renewal on 2026-09-01.

        PRD: "A member becomes `ACTIVE` only when their first membership
        contribution actually settles, and that transition is a side effect of
        settlement rather than an action anyone requests on the member."

        Design: Corner/Endpoints/ep_member_cancel_action_clears_the_renewal_schedule_and_locks_the_row
        """
        ctx = _setup_member_activated_on_the_first_of_august()

        member = ctx["member"]
        assert member["status"] == "ACTIVE"
        assert member["cycle_start_date"] == "2026-08-01"
        assert member["next_renewal_date"] == "2026-09-01"
        assert member["grace_expires_at"] is None
        assert member["consecutive_renewals"] == 0

    def test_cancel_lands_the_member_in_cancelled_with_no_schedule_left(self):
        """One of the three verbs on the single action endpoint both moves the row to
        its terminal status and nulls the two scheduling fields.

        PRD: "`CANCEL` is legal from `ACTIVE`, `GRACE` and `LAPSED` with identical
        effects in all three cases: the member lands in the terminal status
        `CANCELLED` and both `next_renewal_date` and `grace_expires_at` are cleared
        to null."

        Design: Corner/Endpoints/ep_member_cancel_action_clears_the_renewal_schedule_and_locks_the_row
        """
        ctx = _setup_member_activated_on_the_first_of_august()

        cancelled = validate_success(_lifecycle(ctx["member"]["id"], "CANCEL"))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["next_renewal_date"] is None
        assert cancelled["grace_expires_at"] is None
        assert cancelled["version"] == ctx["member"]["version"] + 1

    def test_reinstate_on_the_same_endpoint_is_refused_as_terminal(self):
        """The refusal is about the row being terminal rather than about REINSTATE
        being an unknown verb.

        PRD: "Every one of these actions increments the member's `version` by 1, and
        requesting an action that is not a declared transition out of the member's
        current status is `ERR_INVALID_STATE`, while any action against a
        `CANCELLED` member is `ERR_TERMINAL_STATE`."

        Design: Corner/Endpoints/ep_member_cancel_action_clears_the_renewal_schedule_and_locks_the_row
        """
        ctx = _setup_member_activated_on_the_first_of_august()
        validate_success(_lifecycle(ctx["member"]["id"], "CANCEL"))

        validate_error(
            _lifecycle(ctx["member"]["id"], "REINSTATE"),
            ApiErrorId.ERR_TERMINAL_STATE,
        )

        still_cancelled = read_member(ctx["member"]["id"])
        assert still_cancelled["status"] == "CANCELLED"
        assert still_cancelled["next_renewal_date"] is None


def _setup_cleared_funder_and_an_undisclosed_beat():
    """One CLEARED foundation and one coverage area CLIMATE with no
    disclosures."""
    area = register_coverage_area(area_code="CLIMATE", name="Climate")
    funder = setup_cleared_funder(legal_name="Ironwood Trust")
    return {"area": area, "funder": read_funder(funder["id"])}


def _create_disclosure(funder_id, coverage_area_id, expected_funder_version, text):
    return api_client.create_firewall_disclosure(
        {
            "funder_id": funder_id,
            "coverage_area_id": coverage_area_id,
            "disclosure_text": text,
            "expected_funder_version": expected_funder_version,
        },
        ED_HEADERS,
    )


class TestDisclosureLinkRequiresBothTheFunderAndTheCoverageAreaToExist:
    def test_the_unknown_beat_is_reported_with_the_beats_own_code(self):
        """The funder resolves and the beat does not, so the second declared foreign
        key decides the response.

        PRD: "Body foreign-key existence, evaluated after every path id and in the
        order the fields are declared on the endpoint's input list, again returning
        the not-found code of the missing target entity."

        Design: Corner/Endpoints/ep_disclosure_link_requires_both_the_funder_and_the_coverage_area_to_exist
        """
        ctx = _setup_cleared_funder_and_an_undisclosed_beat()

        validate_error(
            _create_disclosure(
                ctx["funder"]["id"],
                _UNKNOWN_AREA_ID,
                ctx["funder"]["version"],
                "Ironwood funds a beat that does not exist in this newsroom.",
            ),
            ApiErrorId.ERR_COVERAGE_AREA_NOT_FOUND,
        )

        _, meta = validate_paginated(api_client.list_firewall_disclosures(ED_HEADERS))
        assert meta["total_count"] == 0
        assert read_coverage_area(ctx["area"]["id"])["disclosed_funder_count"] == 0

    def test_only_the_fully_resolved_pair_raises_the_beats_funder_count(self):
        """The identical body against the real beat is filed, and the consequence
        lands on the coverage area.

        PRD: "A new disclosure is created in status `ACTIVE`, with
        `attested_by_user_id` stamped with the filing director's `X-User-ID`,
        `attested_at` stamped with the logical clock, and `reattestation_reason`
        null."

        Design: Corner/Endpoints/ep_disclosure_link_requires_both_the_funder_and_the_coverage_area_to_exist
        """
        ctx = _setup_cleared_funder_and_an_undisclosed_beat()
        validate_error(
            _create_disclosure(
                ctx["funder"]["id"],
                _UNKNOWN_AREA_ID,
                ctx["funder"]["version"],
                "Ironwood funds a beat that does not exist in this newsroom.",
            ),
            ApiErrorId.ERR_COVERAGE_AREA_NOT_FOUND,
        )

        filed = validate_success(
            _create_disclosure(
                ctx["funder"]["id"],
                ctx["area"]["id"],
                ctx["funder"]["version"],
                "Ironwood funds climate coverage; the climate desk retains "
                "editorial control.",
            ),
            expected_status=201,
        )
        assert filed["status"] == "ACTIVE"
        assert filed["attested_by_user_id"] == USER_IDS["editorial_director"]
        assert filed["reattestation_reason"] is None
        assert filed["attested_at"].startswith("2026-08-01T00:00:00")

        beat = read_coverage_area(ctx["area"]["id"])
        assert beat["disclosed_funder_count"] == 1
        assert beat["disclosure_status"] == "CURRENT"
        assert beat["publication_gate"] == "OPEN"


def _setup_three_funders_one_of_them_cleared():
    """Three funders created in order: a PROSPECT foundation, a PROSPECT corporate
    donor and a foundation that is then CLEARED."""
    first = register_funder(legal_name="Ironwood Trust", funder_type="FOUNDATION")
    second = register_funder(
        legal_name="Meridian Energy Corp", funder_type="CORPORATE"
    )
    third = register_funder(
        legal_name="Delta Family Foundation", funder_type="FOUNDATION"
    )
    rule_on_funder(third["id"], decision="CLEAR", basis="SELF_ATTESTED")
    return {"first": first, "second": second, "third": third}


class TestFunderListCombinesStatusFiltersWithPagination:
    def test_the_status_filter_narrows_the_count_to_the_single_cleared_funder(self):
        """Two of the three funders are still `PROSPECT`, so the filtered
        `total_count` is 1 and no unreturned rows remain.

        PRD: "`total_count` counts every row matching the request's filters, not
        merely the rows on the returned page, and `has_more` is true exactly when
        unreturned matching rows remain beyond the current page."

        Design: Corner/Endpoints/ep_funder_list_combines_status_and_type_filters_with_pagination
        """
        ctx = _setup_three_funders_one_of_them_cleared()

        rows, meta = validate_paginated(
            api_client.list_funders(DO_HEADERS, params={"status": "CLEARED"})
        )
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(rows) == 1
        assert rows[0]["id"] == ctx["third"]["id"]
        assert rows[0]["independence_risk_score"] == 10

    def test_the_offset_window_intersects_the_created_at_ordering(self):
        """`limit=2&offset=1` skips the first-created funder and returns the second
        and third in creation order, while `total_count` still measures all three.

        PRD: "Unless a specific endpoint's description in §4 names a different
        ordering, list endpoints return their rows sorted by `created_at`
        ascending."

        Design: Corner/Endpoints/ep_funder_list_combines_status_and_type_filters_with_pagination
        """
        ctx = _setup_three_funders_one_of_them_cleared()

        rows, meta = validate_paginated(
            api_client.list_funders(DO_HEADERS, params={"limit": 2, "offset": 1})
        )
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert meta["limit"] == 2
        assert meta["offset"] == 1
        assert [row["id"] for row in rows] == [
            ctx["second"]["id"],
            ctx["third"]["id"],
        ]

    def test_the_corporate_funder_carries_the_heavier_type_weight(self):
        """The rows the window returns keep their own scores: 25 for the corporate
        donor against 10 for the foundation.

        PRD: "The first term is the funder-type weight: 10 for a `FOUNDATION`, 5 for
        an `INDIVIDUAL`, 25 for a `CORPORATE` funder and 20 for a `GOVERNMENT` one."

        Design: Corner/Endpoints/ep_funder_list_combines_status_and_type_filters_with_pagination
        """
        ctx = _setup_three_funders_one_of_them_cleared()

        rows, _ = validate_paginated(
            api_client.list_funders(DO_HEADERS, params={"limit": 2, "offset": 1})
        )
        assert rows[0]["funder_type"] == "CORPORATE"
        assert rows[0]["independence_risk_score"] == 25
        assert rows[0]["status"] == "PROSPECT"
        assert rows[1]["funder_type"] == "FOUNDATION"
        assert rows[1]["independence_risk_score"] == 10
        assert rows[1]["status"] == "CLEARED"

        assert read_funder(ctx["first"]["id"])["independence_risk_score"] == 10

"""Collaboration preconditions - a partner, a closed window, three range checks -
and the logical clock's one-way guard.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    add_partner,
    api_client,
    collaboration_action,
    open_collaboration,
    open_fiscal_period,
    read_collaboration,
    read_partner,
    register_coverage_area,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ED_HEADERS, FC_HEADERS


def _activate(collaboration_id):
    """Raw status action so each refusal can be inspected."""
    return api_client.collaboration_status_action(
        collaboration_id, {"action": "ACTIVATE"}, ED_HEADERS
    )


def _add_partner(collaboration_id, credit_share_bps, cost_share_bps):
    """Raw partner POST under the same org name so the clash can be inspected."""
    return api_client.create_collaboration_partner(
        collaboration_id,
        {
            "partner_org_name": "Riverbend Public Media",
            "credit_share_bps": credit_share_bps,
            "cost_share_bps": cost_share_bps,
        },
        ED_HEADERS,
    )


def _setup_partnerless_collaboration():
    """One DRAFT collaboration whose lead holds 6700 bps of both shares, so a
    single 3300-bps partner would close both sums."""
    period = open_fiscal_period()
    area = register_coverage_area(area_code="CLIMATE", name="Climate")
    collaboration = open_collaboration(
        area["id"],
        period["id"],
        title="Heat island investigation",
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-30T00:00:00Z",
        total_cost_cents=100000,
        lead_credit_bps=6700,
        lead_cost_share_bps=6700,
    )
    return {"period": period, "area": area, "collaboration": collaboration}


def _setup_partnerless_collaboration_whose_sums_already_close():
    """One DRAFT collaboration whose lead holds the whole 10000 bps of both
    shares, so the two arithmetic rungs of the activation ladder are already
    satisfied and only the partner requirement can refuse."""
    period = open_fiscal_period()
    area = register_coverage_area(area_code="CLIMATE", name="Climate")
    collaboration = open_collaboration(
        area["id"],
        period["id"],
        title="Heat island investigation",
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-30T00:00:00Z",
        total_cost_cents=100000,
        lead_credit_bps=10000,
        lead_cost_share_bps=10000,
    )
    return {"period": period, "area": area, "collaboration": collaboration}


class TestActivateNeedsAPartnerAndPartnerNamesAreUniquePerCollaboration:
    """The partner rules are the last thing standing between DRAFT and ACTIVE once
    both share sums close at 10000 bps."""

    def test_a_partnerless_collaboration_cannot_activate(self):
        """The lead holds the whole 10000 bps of each sum, so the credit and cost
        rungs both pass and the last rung of the ladder is the one that answers.

        PRD: "and at least one `CONFIRMED` partner must exist, otherwise
        `ERR_NO_CONFIRMED_PARTNER` (HTTP 409)"

        Design: Corner/Validations/val_activate_needs_a_partner_and_partner_names_are_unique_per_collaboration
        """
        ctx = _setup_partnerless_collaboration_whose_sums_already_close()

        validate_error(
            _activate(ctx["collaboration"]["id"]), ApiErrorId.ERR_NO_CONFIRMED_PARTNER
        )

        blocked = read_collaboration(ctx["collaboration"]["id"])
        assert blocked["status"] == "DRAFT"
        assert blocked["partner_count"] == 0

    def test_the_first_partner_joins_a_draft_without_any_allocation(self):
        """Adding a partner to a `DRAFT` collaboration enrols it and nothing more:
        the split waits for activation.

        PRD: "A new partner is `CONFIRMED` with `cost_owed_cents` and
        `remainder_rank` at 0 and `withdrawn_at` null, and the collaboration's
        `partner_count` - the count of `CONFIRMED` partners only - rises by 1 along
        with its `version`."

        Design: Corner/Validations/val_activate_needs_a_partner_and_partner_names_are_unique_per_collaboration
        """
        ctx = _setup_partnerless_collaboration()
        _activate(ctx["collaboration"]["id"])

        partner = validate_success(
            _add_partner(ctx["collaboration"]["id"], 3300, 3300), expected_status=201
        )
        assert partner["status"] == "CONFIRMED"
        assert partner["cost_owed_cents"] == 0
        assert partner["remainder_rank"] == 0
        assert partner["withdrawn_at"] is None

        assert read_collaboration(ctx["collaboration"]["id"])["partner_count"] == 1

    def test_a_second_row_under_the_same_org_name_is_refused(self):
        """The clash is on `partner_org_name` alone, so different share values do
        not save the second row.

        PRD: "The organisation name must be unique among the collaboration's
        **`CONFIRMED`** partners, so a name freed by a withdrawal may be used again;
        a clash is `ERR_PARTNER_DUPLICATE` (HTTP 409)."

        Design: Corner/Validations/val_activate_needs_a_partner_and_partner_names_are_unique_per_collaboration
        """
        ctx = _setup_partnerless_collaboration()
        _add_partner(ctx["collaboration"]["id"], 3300, 3300)

        validate_error(
            _add_partner(ctx["collaboration"]["id"], 1000, 1000),
            ApiErrorId.ERR_PARTNER_DUPLICATE,
        )

        assert read_collaboration(ctx["collaboration"]["id"])["partner_count"] == 1
        rows, meta = validate_paginated(
            api_client.list_collaboration_partners(
                ctx["collaboration"]["id"], ED_HEADERS
            )
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1

    def test_the_identical_activation_succeeds_with_one_partner_enrolled(self):
        """Nothing about the activation request changes; the single 3300-bps
        partner both closes the sums and satisfies the partner requirement.

        PRD: "`allocated_cost_cents` is `lead_cost_cents` plus the sum of the
        `cost_owed_cents` of every `CONFIRMED` partner, and the invariant is that
        this equals `total_cost_cents` exactly, always."

        Design: Corner/Validations/val_activate_needs_a_partner_and_partner_names_are_unique_per_collaboration
        """
        ctx = _setup_partnerless_collaboration()
        _activate(ctx["collaboration"]["id"])
        partner = validate_success(
            _add_partner(ctx["collaboration"]["id"], 3300, 3300), expected_status=201
        )
        _add_partner(ctx["collaboration"]["id"], 1000, 1000)

        activated = validate_success(_activate(ctx["collaboration"]["id"]))
        assert activated["status"] == "ACTIVE"
        assert activated["partner_count"] == 1
        assert activated["lead_cost_cents"] == 67000
        assert activated["allocated_cost_cents"] == 100000
        assert read_partner(partner["id"])["cost_owed_cents"] == 33000


def _settle(collaboration_id):
    """Raw SETTLE so the open-window refusal can be inspected."""
    return api_client.collaboration_status_action(
        collaboration_id, {"action": "SETTLE"}, ED_HEADERS
    )


def _setup_active_september_collaboration():
    """One ACTIVE collaboration over a 2026-09-01..2026-09-30 window with a single
    confirmed partner, with the clock still at its default 2026-08-01."""
    ctx = _setup_partnerless_collaboration()
    ctx["partner"] = add_partner(
        ctx["collaboration"]["id"], "Riverbend Public Media", 3300, 3300
    )
    ctx["collaboration"] = collaboration_action(ctx["collaboration"]["id"], "ACTIVATE")
    return ctx


class TestSettleBeforeTheProductionWindowClosesIsRefused:
    """The comparison is clock at or after `window_end`, not strictly after."""

    def test_settling_while_the_window_is_still_open_is_refused(self):
        """The clock sits a month before `window_start`, so production has not even
        begun, and the collaboration stays ACTIVE.

        PRD: "The production window must have closed, meaning the logical clock is
        at or after `window_end` - a collaboration whose window is still open is
        refused with `ERR_COLLABORATION_WINDOW_OPEN` (HTTP 409) - and
        `allocated_cost_cents` must equal `total_cost_cents`."

        Design: Corner/Validations/val_settle_before_the_production_window_closes_is_refused
        """
        ctx = _setup_active_september_collaboration()

        validate_error(
            _settle(ctx["collaboration"]["id"]),
            ApiErrorId.ERR_COLLABORATION_WINDOW_OPEN,
        )

        unchanged = read_collaboration(ctx["collaboration"]["id"])
        assert unchanged["status"] == "ACTIVE"
        assert unchanged["settled_at"] is None

    def test_the_clock_landing_exactly_on_the_window_end_lets_it_settle(self):
        """`window_end` is excluded from the half-open window, so the instant it
        names is already outside production and the identical call succeeds.

        PRD: "Settlement stamps `settled_at` with the logical clock and recomputes
        `syndication_revenue_cents` as the sum of `amount_cents` over every
        `SETTLED` contribution on the `SYNDICATION` revenue stream pointing at this
        collaboration."

        Design: Corner/Validations/val_settle_before_the_production_window_closes_is_refused
        """
        ctx = _setup_active_september_collaboration()
        _settle(ctx["collaboration"]["id"])

        set_clock("2026-09-30T00:00:00Z")
        settled = validate_success(_settle(ctx["collaboration"]["id"]))
        assert settled["status"] == "SETTLED"
        assert settled["settled_at"].startswith("2026-09-30T00:00:00")
        assert settled["syndication_revenue_cents"] == 0

    def test_settlement_leaves_the_apportionment_exactly_as_activation_wrote_it(self):
        """The whole cost is still allocated across the lead and its one partner
        after the terminal transition.

        PRD: "`allocated_cost_cents` is `lead_cost_cents` plus the sum of the
        `cost_owed_cents` of every `CONFIRMED` partner, and the invariant is that
        this equals `total_cost_cents` exactly, always."

        Design: Corner/Validations/val_settle_before_the_production_window_closes_is_refused
        """
        ctx = _setup_active_september_collaboration()
        set_clock("2026-09-30T00:00:00Z")
        settled = validate_success(_settle(ctx["collaboration"]["id"]))

        assert settled["allocated_cost_cents"] == settled["total_cost_cents"] == 100000
        assert settled["lead_cost_cents"] == 67000
        assert read_partner(ctx["partner"]["id"])["cost_owed_cents"] == 33000


def _create_collaboration(period_id, area_id, **overrides):
    """Raw POST so each range refusal can be inspected."""
    payload = {
        "coverage_area_id": area_id,
        "fiscal_period_id": period_id,
        "title": "Range check",
        "window_start": "2026-10-01T00:00:00Z",
        "window_end": "2026-09-01T00:00:00Z",
        "total_cost_cents": 100000,
        "lead_credit_bps": 6700,
        "lead_cost_share_bps": 6700,
    }
    payload.update(overrides)
    return api_client.create_collaboration(payload, ED_HEADERS)


def _setup_period_and_climate():
    """One period running 2026-08-01..2027-07-31 and one beat to hang the
    collaborations on."""
    period = open_fiscal_period()
    area = register_coverage_area(area_code="CLIMATE", name="Climate")
    return period, area


class TestCollaborationRangeChecksRunBpsFirstThenDatesThenPeriodContainment:
    """Three refusals from one shape of request, in one fixed order."""

    def test_an_out_of_range_lead_share_outranks_the_inverted_window(self):
        """The window is inverted in the same body, and the basis-point rung is
        reached first.

        PRD: "Validation proceeds in a fixed ladder and the **first** violated rule
        decides the response; no later rule is evaluated and no partial mutation is
        ever written."

        Design: Corner/Validations/val_collaboration_range_checks_run_bps_first_then_dates_then_period_containment
        """
        period, area = _setup_period_and_climate()

        validate_error(
            _create_collaboration(
                period["id"], area["id"], title="Bad shares", lead_credit_bps=10001
            ),
            ApiErrorId.ERR_INVALID_BPS_RANGE,
        )

        _, meta = validate_paginated(api_client.list_collaborations(ED_HEADERS))
        assert meta["total_count"] == 0

    def test_the_inverted_window_surfaces_once_the_shares_are_in_range(self):
        """Only the 10001 becomes 6700; the window is still 2026-10-01 to
        2026-09-01 and now it is what offends.

        PRD: "Where a date pair defines a span, the start must be strictly earlier
        than the end - this holds for a fiscal period's `start_date` and `end_date`,
        a grant proposal's `restriction_start_date` and `restriction_end_date`, and
        a collaboration's `window_start` and `window_end` - and a violation is
        reported as `ERR_INVALID_DATE_RANGE` (HTTP 422)."

        Design: Corner/Validations/val_collaboration_range_checks_run_bps_first_then_dates_then_period_containment
        """
        period, area = _setup_period_and_climate()
        _create_collaboration(
            period["id"], area["id"], title="Bad shares", lead_credit_bps=10001
        )

        validate_error(
            _create_collaboration(period["id"], area["id"], title="Inverted window"),
            ApiErrorId.ERR_INVALID_DATE_RANGE,
        )

        _, meta = validate_paginated(api_client.list_collaborations(ED_HEADERS))
        assert meta["total_count"] == 0

    def test_a_window_ending_one_day_past_the_period_is_refused_last(self):
        """The dates are now correctly ordered, so the containment rule is the only
        one left to fire.

        PRD: "The window must lie inside its fiscal period, meaning `window_start`
        on or after the period's `start_date` and `window_end` on or before its
        `end_date`; otherwise `ERR_WINDOW_OUTSIDE_PERIOD` (HTTP 422)."

        Design: Corner/Validations/val_collaboration_range_checks_run_bps_first_then_dates_then_period_containment
        """
        period, area = _setup_period_and_climate()

        validate_error(
            _create_collaboration(
                period["id"],
                area["id"],
                title="Overhanging window",
                window_start="2027-07-01T00:00:00Z",
                window_end="2027-08-01T00:00:00Z",
            ),
            ApiErrorId.ERR_WINDOW_OUTSIDE_PERIOD,
        )

        _, meta = validate_paginated(api_client.list_collaborations(ED_HEADERS))
        assert meta["total_count"] == 0

    def test_the_same_window_pulled_inside_the_period_opens_a_draft(self):
        """A `window_end` on the period's own last day is contained, and the new
        row carries no allocation at all.

        PRD: "A new collaboration opens in `DRAFT` with `partner_count` at 0,
        `lead_cost_cents`, `allocated_cost_cents` and `syndication_revenue_cents` at
        0, `settled_at` null, and `lead_cost_share_bps` seeded from the request."

        Design: Corner/Validations/val_collaboration_range_checks_run_bps_first_then_dates_then_period_containment
        """
        period, area = _setup_period_and_climate()

        created = validate_success(
            _create_collaboration(
                period["id"],
                area["id"],
                title="Valid window",
                window_start="2027-07-01T00:00:00Z",
                window_end="2027-07-31T00:00:00Z",
            ),
            expected_status=201,
        )
        assert created["status"] == "DRAFT"
        assert created["partner_count"] == 0
        assert created["lead_cost_cents"] == 0
        assert created["allocated_cost_cents"] == 0
        assert created["syndication_revenue_cents"] == 0
        assert created["settled_at"] is None
        assert created["lead_cost_share_bps"] == 6700


def _set_clock(current_utc):
    """Raw clock write so a rewind can be inspected."""
    return api_client.set_clock({"current_utc": current_utc}, FC_HEADERS)


class TestLogicalClockNeverMovesBackwardsButMayBeSetToItsOwnValue:
    """The guard admits equality, so only a strictly earlier instant is a rewind."""

    def test_an_instant_one_day_earlier_than_the_clock_is_rejected(self):
        """After moving the clock to 2026-09-01, 2026-08-31 is behind it - even
        though it is still ahead of the server's starting value.

        PRD: "The clock may never move backwards: a `current_utc` earlier than the
        clock's present value is rejected with `ERR_CLOCK_REWIND` (HTTP 422), while
        a value equal to the present value is accepted."

        Design: Corner/Validations/val_logical_clock_never_moves_backwards_but_may_be_set_to_its_own_value
        """
        advanced = set_clock("2026-09-01T00:00:00Z")
        assert advanced["current_utc"].startswith("2026-09-01T00:00:00")
        assert advanced["previous_utc"].startswith("2026-08-01T00:00:00")

        validate_error(_set_clock("2026-08-31T00:00:00Z"), ApiErrorId.ERR_CLOCK_REWIND)

    def test_re_setting_the_clock_to_its_own_value_is_accepted(self):
        """The reply names 2026-09-01 as both the new instant and the one it
        replaced, which is also how the rejected rewind is shown to have moved
        nothing.

        PRD: "Setting the clock returns both the new `current_utc` and the
        `previous_utc` it replaced, and mutates no entity - elapsed time only
        becomes state through the daily sweep described in §3.3 and §3.8."

        Design: Corner/Validations/val_logical_clock_never_moves_backwards_but_may_be_set_to_its_own_value
        """
        set_clock("2026-09-01T00:00:00Z")
        _set_clock("2026-08-31T00:00:00Z")

        idempotent = validate_success(_set_clock("2026-09-01T00:00:00Z"))
        assert idempotent["current_utc"].startswith("2026-09-01T00:00:00")
        assert idempotent["previous_utc"].startswith("2026-09-01T00:00:00")

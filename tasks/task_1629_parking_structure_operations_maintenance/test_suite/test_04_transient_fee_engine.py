"""Transient fee engine: grace boundary, tier/cap composition, cap-mode
variants, lost-ticket rating, and credentialed monthly sessions."""
from test_helpers import (
    TEST_USERS,
    activate_agreement,
    create_active_agreement,
    enter_vehicle,
    enter_vehicle_at,
    get_success_data,
    issue_credential,
    make_gate_device_headers,
    quote_session_at,
    set_clock,
    setup_agreement_with_credential,
    setup_entry_ready_facility,
    validate_success,
)

ATT = TEST_USERS["parking_attendant_headers"]


def _quote_fee(api, session_id, quote_at):
    return quote_session_at(session_id, quote_at)["fee_cents"]


class TestCalendarVsRollingCap:
    """Identical 22.5h stay crossing midnight rated under both cap modes."""

    def _build_pair(self, api):
        fac_a, rs_a, gate_a = setup_entry_ready_facility(
            name="Cal Facility", cap_mode="CALENDAR_DAY")
        fac_b, rs_b, gate_b = setup_entry_ready_facility(
            name="Roll Facility", cap_mode="ROLLING_24H")
        sess_a = enter_vehicle_at(fac_a["id"], gate_a, "TA-1", "2026-08-01T10:00:00Z")
        sess_b = enter_vehicle_at(fac_b["id"], gate_b, "TB-1", "2026-08-01T10:00:00Z")
        return sess_a, sess_b

    def test_calendar_day_cap_bills_two_capped_segments(self, api):
        """PRD: "Under `CALENDAR_DAY`, the interval from entry to the rating
        moment is split at each local midnight into per-date segments; within a
        segment, billed hours are the segment's minutes divided by sixty and
        rounded up — any partial hour bills as a full hour — and the segment
        charge is `first_hour_cents` plus `additional_hour_cents` multiplied by
        the hours beyond the first (never fewer than zero additional hours),
        capped so the segment never exceeds `daily_max_cents`. The fee is the
        sum of segment charges."

        Design: Difficulty/dual_variant_calc/transient_fee_calendar_vs_rolling_cap
        """
        sess_a, sess_b = self._build_pair(api)
        fee_a = _quote_fee(api, sess_a["id"], "2026-08-02T08:30:00Z")
        assert fee_a == 4800, (
            "day1 14h -> 4400 capped 2400; day2 8.5h -> 9h -> 2900 capped 2400")
        fee_b = _quote_fee(api, sess_b["id"], "2026-08-02T08:30:00Z")
        assert fee_a != fee_b, "identical stay, different cap modes, different totals"

    def test_rolling_24h_cap_bills_one_anchored_window(self, api):
        """PRD: "Under `ROLLING_24H`, the identical per-window formula applies,
        but the stay divides into consecutive twenty-four-hour windows anchored
        at the entry instant rather than at calendar midnights."

        Design: Difficulty/dual_variant_calc/transient_fee_calendar_vs_rolling_cap
        """
        sess_a, sess_b = self._build_pair(api)
        fee_b = _quote_fee(api, sess_b["id"], "2026-08-02T08:30:00Z")
        assert fee_b == 2400, (
            "single rolling window: ceil 22.5h = 23h -> 7100 capped 2400")


class TestTierCapGraceComposition:
    """Non-linear min() cap binding with conditional grace on one session."""

    def _build_session(self, api):
        facility, schedule, gate = setup_entry_ready_facility(name="Tier Fac")
        return enter_vehicle_at(facility["id"], gate, "TT-1", "2026-08-01T09:50:00Z")

    def test_two_hour_quote_bills_first_plus_additional(self, api):
        """PRD: "Once grace is exceeded, billing starts from minute zero: the
        grace minutes are not subtracted from the stay."
        PRD: "the segment charge is `first_hour_cents` plus
        `additional_hour_cents` multiplied by the hours beyond the first
        (never fewer than zero additional hours)"

        Design: Difficulty/combinatorial_formula/transient_fee_tier_cap_grace_mode_a
        """
        session = self._build_session(api)
        fee = _quote_fee(api, session["id"], "2026-08-01T11:50:00Z")
        assert fee == 800, "2h elapsed: 500 + 1*300, grace exceeded so billed from minute 0"

    def test_fourteen_hour_quote_capped_at_daily_max(self, api):
        """PRD: "the segment charge is `first_hour_cents` plus
        `additional_hour_cents` multiplied by the hours beyond the first
        (never fewer than zero additional hours), capped so the segment never
        exceeds `daily_max_cents`."
        PRD: "Re-quoting a `QUOTED` session is legal and simply re-rates at
        the new now, refreshing `quoted_fee_cents`."

        Design: Difficulty/combinatorial_formula/transient_fee_tier_cap_grace_mode_a
        """
        session = self._build_session(api)
        _quote_fee(api, session["id"], "2026-08-01T11:50:00Z")
        fee = _quote_fee(api, session["id"], "2026-08-01T23:50:00Z")
        assert fee == 2400, "14h: 500 + 13*300 = 4400, min() cap binds at 2400"
        after = get_success_data(api.get_parking_session(session["id"], ATT))
        assert after["billing_state"] == "QUOTED"
        assert after["quoted_fee_cents"] == 2400


class TestGraceBoundary:
    """Elapsed == grace stays free; one minute past bills from minute zero."""

    def _build_session(self, api):
        facility, schedule, gate = setup_entry_ready_facility(name="Grace Fac")
        return enter_vehicle_at(facility["id"], gate, "GB-1", "2026-08-01T10:00:00Z")

    def test_exactly_at_grace_is_free(self, api):
        """PRD: "When that minute count is no greater than `grace_minutes` the
        fee is zero — a stay of exactly the grace length still exits free."

        Design: Difficulty/boundary_precision_check/grace_boundary_exactly_at_grace_free
        """
        session = self._build_session(api)
        fee = _quote_fee(api, session["id"], "2026-08-01T10:15:00Z")
        assert fee == 0, "elapsed 15 <= grace 15: boundary is inclusive-free"

    def test_one_minute_past_grace_bills_from_minute_zero(self, api):
        """PRD: "Once grace is exceeded, billing starts from minute zero: the
        grace minutes are not subtracted from the stay."
        PRD: "any partial hour bills as a full hour"

        Design: Difficulty/boundary_precision_check/grace_boundary_exactly_at_grace_free
        """
        session = self._build_session(api)
        fee = _quote_fee(api, session["id"], "2026-08-01T10:16:00Z")
        assert fee == 500, "elapsed 16 -> ceil(16/60)=1h -> 500; grace NOT subtracted"


def test_fee_lost_ticket_three_calendar_days(api):
    """PRD: "Under `LOST_TICKET`, the fee is `lost_ticket_daily_cents`
    multiplied by the number of distinct calendar dates the stay touches
    between `entry_at` and the rating moment; even a stay contained within a
    single date counts one date, so the multiplier is at least one."
    PRD: "the session must still be `OPEN` or `QUOTED`, its `fee_mode` flips
    to `LOST_TICKET`, and `quoted_fee_cents` is recomputed at the logical now
    under the per-calendar-day rule of §3.2."

    Design: Corner/calculations/fee_lost_ticket_three_calendar_days
    """
    facility, schedule, gate = setup_entry_ready_facility(name="LT Fac")
    session = enter_vehicle_at(facility["id"], gate, "LT-1", "2026-08-01T10:00:00Z")
    set_clock("2026-08-03T12:00:00Z")
    converted = validate_success(api.lost_ticket_session(session["id"], ATT), 200)
    assert converted["fee_mode"] == "LOST_TICKET"
    quote = get_success_data(api.quote_session(session["id"], ATT))
    assert quote["fee_cents"] == 7200, "3 calendar dates (08-01/02/03) x 2400"


def test_fee_monthly_credential_zero_and_free_exit(api):
    """PRD: "Under `MONTHLY` — a session that entered on a monthly credential —
    the fee is zero regardless of duration."
    PRD: "it may also leave while billing is still `OPEN` or `QUOTED` when the
    fee computed at the exit moment is zero, in which case the exit itself
    auto-settles — billing moves to `SETTLED` with `settled_fee_cents` zero
    and `tender_type` `NONE`."

    Design: Corner/calculations/fee_monthly_credential_zero_and_free_exit
    """
    facility, schedule, gate = setup_entry_ready_facility(name="M0 Fac")
    parker, agreement, credential = setup_agreement_with_credential(facility["id"])
    session = enter_vehicle_at(facility["id"], gate, "M0-1", "2026-08-01T10:00:00Z",
                               credential_id=credential["id"])
    assert session["fee_mode"] == "MONTHLY"

    quote = quote_session_at(session["id"], "2026-08-01T15:00:00Z")
    assert quote["fee_cents"] == 0, "5h MONTHLY stay quotes zero"

    exited = validate_success(api.exit_session(
        session["id"], make_gate_device_headers(gate["id"])), 200)
    assert exited["occupancy_state"] == "EXITED"
    assert exited["billing_state"] == "SETTLED"
    assert exited["settled_fee_cents"] == 0
    assert exited["tender_type"] == "NONE"


def test_fee_grace_not_deducted_from_billable_time(api):
    """PRD: "Once grace is exceeded, billing starts from minute zero: the
    grace minutes are not subtracted from the stay."

    Design: Corner/calculations/fee_grace_not_deducted_from_billable_time
    """
    facility, schedule, gate = setup_entry_ready_facility(name="GD Fac")
    session = enter_vehicle_at(facility["id"], gate, "GD-1", "2026-08-01T10:00:00Z")
    fee = _quote_fee(api, session["id"], "2026-08-01T11:15:00Z")
    assert fee == 800, (
        "75 minutes -> ceil(75/60)=2h -> 500+300=800; "
        "a grace-deducting implementation would return 500")

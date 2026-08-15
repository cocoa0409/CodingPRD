"""Dispute lifecycle, resettlement, and statement close semantics."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, make_trader_headers, make_analyst_headers,
)
from test_helpers.fixtures import (
    ISO, set_clock, create_participant, create_generator, create_operating_day,
    create_offer, submit_offer, run_da_market, close_real_time,
    run_prelim_settlement, run_final_settlement, submit_telemetry,
    uniform_readings_24, setup_final_settled, get_statement_by_day_and_type,
)


def _get_first_line(api, statement_id, charge_type=None):
    params = {"settlement_statement_id": statement_id}
    if charge_type:
        params["charge_type"] = charge_type
    rows, _ = validate_paginated(api.list_lines(ISO, params=params))
    assert rows, "expected at least one line"
    return rows[0]


class TestDisputeCycle:
    def test_statement_dispute_reinstatement_cycle(self, api):
        """PRD §3.7: "the statement itself may be disputed again later within
        its window — the `ISSUED` ↔ `UNDER_DISPUTE` cycle can repeat." and
        "A `REJECTED` outcome returns the statement from `UNDER_DISPUTE` to
        `ISSUED` with its amounts unchanged".

        Design: Difficulty/non_linear_state_machine/statement_dispute_reinstatement_cycle
        """
        p_id, g_id, d_id, s = setup_final_settled()
        analyst = make_analyst_headers(p_id)
        ln = _get_first_line(api, s["id"])

        # file -> withdraw -> refile -> reject
        resp = api.create_dispute(s["id"], {"dispute_reason": "PRICE_ERROR",
                                            "disputed_line_ids": [ln["id"]]}, analyst)
        d1 = validate_success(resp, expected_status=201)
        st = get_success_data(api.get_statement(s["id"], analyst))
        assert st["status"] == "UNDER_DISPUTE"

        api.withdraw_dispute(d1["id"], analyst)
        st = get_success_data(api.get_statement(s["id"], analyst))
        assert st["status"] == "ISSUED"
        d1_after = get_success_data(api.get_dispute(d1["id"], analyst))
        assert d1_after["status"] == "WITHDRAWN"

        resp = api.create_dispute(s["id"], {"dispute_reason": "METER_DATA_ERROR",
                                            "disputed_line_ids": [ln["id"]]}, analyst)
        d2 = validate_success(resp, expected_status=201)
        api.start_review_dispute(d2["id"], ISO)
        api.resolve_dispute(d2["id"], {"outcome": "REJECTED"}, ISO)
        d2_after = get_success_data(api.get_dispute(d2["id"], analyst))
        assert d2_after["status"] == "REJECTED"
        st = get_success_data(api.get_statement(s["id"], analyst))
        assert st["status"] == "ISSUED"
        assert st["net_amount_cents"] == -1128000


class TestDisputeRequiresFinal:
    def test_dispute_requires_final_run_type(self, api):
        """PRD §3.7: "Only statements whose `run_type` is `FINAL` or
        `RESETTLEMENT` may be disputed; filing against a `PRELIMINARY`
        statement is rejected with `ERR_STATEMENT_NOT_FINAL`."

        Design: Difficulty/cross_entity_state_dependency/dispute_requires_final_run_type
        """
        p_id, g_id, d_id, s_pre = __import__("test_helpers.fixtures", fromlist=["setup_preliminary_settled"]).setup_preliminary_settled()
        analyst = make_analyst_headers(p_id)
        ln = _get_first_line(api, s_pre["id"])
        resp = api.create_dispute(s_pre["id"], {"dispute_reason": "PRICE_ERROR",
                                                "disputed_line_ids": [ln["id"]]}, analyst)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_NOT_FINAL)
        st = get_success_data(api.get_statement(s_pre["id"], analyst))
        assert st["status"] == "ISSUED"


class TestDisputeWindowClosed:
    def test_dispute_after_window_rejected(self, api):
        """PRD §3.7: "the filing must land at or before
        `dispute_window_ends_at` — a filing at exactly the window end is
        accepted, a strictly later one rejected with
        `ERR_DISPUTE_WINDOW_CLOSED`."

        Design: Corner/validations/dispute_after_window_rejected
        """
        p_id, g_id, d_id, s = setup_final_settled()
        analyst = make_analyst_headers(p_id)
        ln = _get_first_line(api, s["id"])
        set_clock("2026-08-05T00:00:00Z")
        resp = api.create_dispute(s["id"], {"dispute_reason": "PRICE_ERROR",
                                            "disputed_line_ids": [ln["id"]]}, analyst)
        validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED)
        st = get_success_data(api.get_statement(s["id"], analyst))
        assert st["status"] == "ISSUED"


class TestDisputeAlreadyOpen:
    def test_dispute_second_open_rejected(self, api):
        """PRD §3.7: "a second filing while another dispute of the same
        statement is `FILED` or `UNDER_REVIEW` is rejected with
        `ERR_DISPUTE_ALREADY_OPEN`."

        Design: Corner/validations/dispute_second_open_rejected
        """
        p_id, g_id, d_id, s = setup_final_settled()
        analyst = make_analyst_headers(p_id)
        ln = _get_first_line(api, s["id"])
        api.create_dispute(s["id"], {"dispute_reason": "PRICE_ERROR",
                                     "disputed_line_ids": [ln["id"]]}, analyst)
        resp = api.create_dispute(s["id"], {"dispute_reason": "METER_DATA_ERROR",
                                            "disputed_line_ids": [ln["id"]]}, analyst)
        validate_error(resp, ApiErrorId.ERR_DISPUTE_ALREADY_OPEN)
        st = get_success_data(api.get_statement(s["id"], analyst))
        assert st["status"] == "UNDER_DISPUTE"


class TestDayCloseBlockedByDispute:
    def test_day_close_blocked_by_unresolved_dispute(self, api):
        """PRD §3.5: "Closing the day moves it `FINAL_SETTLED` → `CLOSED` ...
        and requires that no statement of the day remain `UNDER_DISPUTE`;
        while any dispute is open the close is rejected with
        `ERR_UNRESOLVED_DISPUTES`."

        Design: Corner/state_machines/day_close_blocked_by_unresolved_dispute
        """
        p_id, g_id, d_id, s = setup_final_settled()
        analyst = make_analyst_headers(p_id)
        ln = _get_first_line(api, s["id"])
        api.create_dispute(s["id"], {"dispute_reason": "PRICE_ERROR",
                                     "disputed_line_ids": [ln["id"]]}, analyst)
        resp = api.close_operating_day(d_id, ISO)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_DISPUTES)
        day = get_success_data(api.get_operating_day(d_id, ISO))
        assert day["status"] == "FINAL_SETTLED"


class TestStatementClosesOnDayClose:
    def test_statement_closes_on_day_close(self, api):
        """PRD §3.5: "On close, every statement still `ISSUED` moves to
        `CLOSED`, and the day's `version` increments once more."

        Design: Corner/state_machines/statement_closes_on_day_close
        """
        p_id, g_id, d_id, s = setup_final_settled()
        api.close_operating_day(d_id, ISO)
        st = get_success_data(api.get_statement(s["id"], ISO))
        day = get_success_data(api.get_operating_day(d_id, ISO))
        assert day["status"] == "CLOSED"
        assert st["status"] == "CLOSED"


class TestResettlementSingleLineOffset:
    def test_resettlement_offsets_single_disputed_line(self, api):
        """PRD §3.7: "Every component field copies over from the disputed
        statement except that each component containing a disputed line is
        reduced by that line's `amount_cents`, and `net_amount_cents` becomes
        the disputed statement's net minus the sum of the disputed lines'
        amounts".

        Design: Corner/calculations/resettlement_offsets_single_disputed_line
        """
        p_id, g_id, d_id, s = setup_final_settled()
        analyst = make_analyst_headers(p_id)
        ln_cong = _get_first_line(api, s["id"], charge_type="CONGESTION")
        resp = api.create_dispute(s["id"], {"dispute_reason": "PRICE_ERROR",
                                            "disputed_line_ids": [ln_cong["id"]]}, analyst)
        disp = validate_success(resp, expected_status=201)
        api.start_review_dispute(disp["id"], ISO)
        api.resolve_dispute(disp["id"], {"outcome": "UPHELD"}, ISO)
        rows, _ = validate_paginated(api.list_statements(ISO, params={
            "market_participant_id": p_id, "run_type": "RESETTLEMENT"}))
        assert len(rows) == 1
        s_re = rows[0]
        assert s_re["net_amount_cents"] == -1176000
        assert s_re["congestion_charge_cents"] == 0
        assert s_re["supersedes_statement_id"] == s["id"]


class TestForeignLineBeatsWindowClosed:
    def test_dispute_foreign_line_beats_window_closed(self, api):
        """PRD §2.11: item 9 "Structural references inside the payload, such as
        every disputed line belonging to the disputed statement —
        `ERR_LINE_NOT_IN_STATEMENT`" is evaluated before item 10 "Temporal
        gates against the logical clock — ... `ERR_DISPUTE_WINDOW_CLOSED`".

        Design: Difficulty/priority_pair_validation_conflict/dispute_foreign_line_beats_window_closed
        """
        p_id, g_id, d_id, s_fin = setup_final_settled()
        s_pre = get_statement_by_day_and_type(d_id, p_id, "PRELIMINARY")
        ln_foreign = _get_first_line(api, s_pre["id"])
        set_clock("2026-08-05T00:00:00Z")
        resp = api.create_dispute(s_fin["id"], {"dispute_reason": "PRICE_ERROR",
                                                "disputed_line_ids": [ln_foreign["id"]]},
                                  make_analyst_headers(p_id))
        validate_error(resp, ApiErrorId.ERR_LINE_NOT_IN_STATEMENT)
        st = get_success_data(api.get_statement(s_fin["id"], ISO))
        assert st["status"] == "ISSUED"

"""Requests that break two rules at once, and which rule must answer."""

from test_helpers import (
    COURSE_HEADERS,
    TREASURER_HEADERS,
    ApiErrorId,
    validate_error,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

RAINOUT_OUTING = {
    "name": "Rainout Scramble",
    "format": "SCRAMBLE",
    "field_capacity_teams": 4,
    "prize_pool_cents": 0,
    "rain_date": "2026-10-03T12:00:00Z",
}
RAINOUT_CONTRACT = {
    "guaranteed_player_count": 0,
    "rain_date_terms": "PARTIAL_CREDIT",
    "rain_date_credit_pct": 0.5,
}

WAVE_OUTING = {
    "name": "Wave Window Open",
    "format": "SCRAMBLE",
    "field_capacity_teams": 1,
    "prize_pool_cents": 0,
}
WAVE_CONTRACT = {
    "guaranteed_player_count": 4,
    "tee_interval_minutes": 10,
    "cart_allowance_count": 4,
}

REMIT_OUTING = {
    "name": "Premature Remit",
    "format": "STROKE_PLAY",
    "field_capacity_teams": 1,
    "prize_pool_cents": 0,
    "rain_date": "2026-10-03T12:00:00Z",
}


def _postponed_outing_with_a_pending_package(api):
    ctx = fx.open_outing(api, outing=RAINOUT_OUTING, contract=RAINOUT_CONTRACT)
    reg = fx.new_registration(
        api, ctx["outing_id"], ctx["tier_id"], buyer_name="Late Payer LLC", player_count=4
    )
    ctx["registration_id"] = reg["id"]
    ctx["outing"] = fx.drive_play(api, ctx["outing_id"], "POSTPONE")
    return ctx


def _locked_team_without_a_tee_time(api):
    ctx = fx.open_outing(api, outing=WAVE_OUTING, contract=WAVE_CONTRACT)
    reg = fx.confirmed_registration(
        api, ctx, players=(12.0, 18.4, 8.2, 24.0), buyer_name="Late Tee Ltd",
        names=["W1", "W2", "W3", "W4"],
    )
    team = fx.new_team(api, ctx["outing_id"], reg["player_ids"], team_name="Late Tee Ltd")
    fx.lock_field(api, ctx["outing_id"])
    ctx["team_id"] = team["id"]
    ctx["team_version"] = fx.team_version(api, team["id"])
    return ctx


class TestOpenFieldGateOutranksPaymentMatching:
    def test_a_wrong_amount_on_a_postponed_outing_reports_the_closed_field(self, api):
        """The ladder "evaluates a fixed ladder and reports the **first** rule that
        fails; every later rule is left unevaluated", and the "**Open-field
        precondition**" that "requires the owning outing's play dimension to be `OPEN`,
        otherwise `ERR_REGISTRATION_CLOSED` (HTTP 409)" sits above the fiscal sub-tier
        that "holds payment amount matching (`ERR_PAYMENT_AMOUNT_MISMATCH`)".

        Design: Difficulty/priority_pair_validation_conflict/state_registration_closed_outranks_fiscal_payment_mismatch
        """
        ctx = _postponed_outing_with_a_pending_package(api)
        assert fx.read_outing(api, ctx["outing_id"])["play_status"] == "POSTPONED"

        validate_error(
            api.record_registration_payment(
                ctx["registration_id"], f.payment_payload(99999), TREASURER_HEADERS
            ),
            ApiErrorId.REGISTRATION_CLOSED,
            409,
        )

        registration = fx.read_registration(api, ctx["registration_id"])
        assert registration["status"] == "PENDING_PAYMENT"
        assert registration["amount_paid_cents"] == 0

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["play_status"] == "POSTPONED"
        assert outing["gross_revenue_cents"] == 0
        assert outing["confirmed_player_slots"] == 0

    def test_the_same_amount_reports_the_fiscal_error_once_the_field_reopens(self, api):
        """The outranked rule is live on its own: an `amount_cents` "must equal the held
        tier's `price_cents` to the cent, otherwise `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP
        402)".

        Design: Difficulty/priority_pair_validation_conflict/state_registration_closed_outranks_fiscal_payment_mismatch
        """
        ctx = _postponed_outing_with_a_pending_package(api)
        resumed = fx.drive_play(api, ctx["outing_id"], "RESUME")
        assert resumed["play_status"] == "OPEN"

        validate_error(
            api.record_registration_payment(
                ctx["registration_id"], f.payment_payload(99999), TREASURER_HEADERS
            ),
            ApiErrorId.PAYMENT_AMOUNT_MISMATCH,
            402,
        )
        assert fx.read_registration(api, ctx["registration_id"])["status"] == "PENDING_PAYMENT"


class TestWaveWindowOutranksCartAllowance:
    def test_a_late_tee_time_with_an_impossible_cart_reports_the_wave_window(self, api):
        """The endpoint's own order decides: "Four business checks then run, in this
        order, and the order is what determines which error a badly formed assignment
        reports", with the wave window third - "A group's `tee_time` must fall inside
        the window of the wave it was assigned to" - and the cart allowance fourth -
        "The requested `cart_number` may not exceed the contract's
        `cart_allowance_count`".

        Design: Difficulty/priority_pair_validation_conflict/temporal_wave_window_outranks_constraint_cart_allowance
        """
        ctx = _locked_team_without_a_tee_time(api)

        validate_error(
            api.tee_assignment(
                ctx["team_id"],
                f.tee_assignment_payload(
                    ctx["team_version"], wave="A", starting_hole=1,
                    tee_time="2026-09-19T17:00:00Z", cart_number=9,
                ),
                COURSE_HEADERS,
            ),
            ApiErrorId.WAVE_WINDOW_VIOLATION,
            409,
        )

        team = fx.read_team(api, ctx["team_id"])
        assert team["tee_time"] is None
        assert team["wave"] is None
        assert team["cart_number"] is None
        assert team["starting_hole"] is None
        assert team["tee_assignment_count"] == 0
        assert team["version"] == ctx["team_version"]

    def test_an_in_window_tee_time_reports_the_cart_allowance(self, api):
        """The outranked rule is live on its own: "The requested `cart_number` may not
        exceed the contract's `cart_allowance_count`, and the number of distinct
        `cart_number` values assigned within a single wave may not exceed that
        allowance either. Either failure is `ERR_CART_ALLOWANCE_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_wave_window_outranks_constraint_cart_allowance
        """
        ctx = _locked_team_without_a_tee_time(api)

        validate_error(
            api.tee_assignment(
                ctx["team_id"],
                f.tee_assignment_payload(
                    ctx["team_version"], wave="A", starting_hole=1,
                    tee_time="2026-09-19T12:00:00Z", cart_number=9,
                ),
                COURSE_HEADERS,
            ),
            ApiErrorId.CART_ALLOWANCE_EXCEEDED,
            409,
        )
        assert fx.read_team(api, ctx["team_id"])["tee_assignment_count"] == 0


class TestStatePreconditionOutranksVersionGuard:
    def _collecting_outing_three_writes_on(self, api):
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        created = fx.new_outing(api, **REMIT_OUTING)
        contract = fx.new_contract(
            api, created["id"], guaranteed_player_count=0,
            rain_date_terms="PARTIAL_CREDIT", rain_date_credit_pct=0.5,
        )
        fx.sign_contract(api, contract["id"])
        fx.new_tier(api, created["id"])
        fx.drive_play(api, created["id"], "OPEN_REGISTRATION")
        fx.drive_play(api, created["id"], "POSTPONE")
        fx.drive_play(api, created["id"], "RESUME")
        return {"outing_id": created["id"], "stale_version": created["version"]}

    def test_a_premature_remit_with_a_stale_guard_reports_the_state_error(self, api):
        """The PRD pins the ladder at "**Optimistic concurrency**", where "the supplied
        version guard matches the row's current `version`", and "Because this tier sits
        below the state precondition, a request that is both wrongly sequenced and stale
        reports the state error, not the staleness error."  Remitting is only "`RECONCILED →
        DISBURSED`".

        Design: Difficulty/priority_pair_validation_conflict/state_transition_outranks_occ_stale_outing_version
        """
        ctx = self._collecting_outing_three_writes_on(api)

        validate_error(
            api.finance_transition(
                ctx["outing_id"],
                f.remit_payload(ctx["stale_version"], 0, "WIRE-STALE"),
                TREASURER_HEADERS,
            ),
            ApiErrorId.INVALID_STATE_TRANSITION,
            409,
        )

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["finance_status"] == "COLLECTING"
        assert outing["beneficiary_remittance_cents"] == 0
        assert outing["remittance_reference"] is None
        assert outing["version"] == ctx["stale_version"] + 3

    def test_the_state_verdict_survives_a_perfectly_fresh_guard(self, api):
        """A 409 here is a genuine state verdict rather than a mislabelled staleness
        failure, because the state precondition asks only whether "the requested action
        is a declared edge out of the target row's current state in the relevant
        lifecycle, including the parallel dimensions carried by outings and contests".

        Design: Difficulty/priority_pair_validation_conflict/state_transition_outranks_occ_stale_outing_version
        """
        ctx = self._collecting_outing_three_writes_on(api)
        current = fx.outing_version(api, ctx["outing_id"], TREASURER_HEADERS)
        assert current == ctx["stale_version"] + 3

        validate_error(
            api.finance_transition(
                ctx["outing_id"],
                f.remit_payload(current, 0, "WIRE-STALE"),
                TREASURER_HEADERS,
            ),
            ApiErrorId.INVALID_STATE_TRANSITION,
            409,
        )
        assert fx.read_outing(api, ctx["outing_id"])["finance_status"] == "COLLECTING"

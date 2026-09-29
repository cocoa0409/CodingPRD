"""The draw ladder refusing to be short-circuited, and a closure window refusing to be re-run."""

from __future__ import annotations

from decimal import Decimal

import pytest

from test_helpers import (
    ApiErrorId,
    acknowledged_plan,
    activate_phase,
    assert_field_equals,
    consent_draw,
    current_property_version,
    draw_decision_payload,
    locked_budget,
    read_budget,
    read_draw,
    read_phase,
    read_property,
    request_draw,
    schedule_phase,
    set_clock,
    start_item,
    validate_error,
)


@pytest.fixture
def executing_plan_with_a_planned_closure(api):
    """A locked reserve-funded plan under way, one closure window still only planned."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "corridors",
                "category": "GUEST_FACING",
                "standards_reference": "GF-29.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        legal_name="Fernsby Hotels LLC",
        contact_email="ops@fernsbyh.example",
        property_overrides={"name": "Fernsby Corn Exchange"},
    )
    budget = locked_budget(api, scenario, 1182500, financing_source="RESERVE_DRAW")
    start_item(api, scenario, scenario.item_id("corridors"))
    phase = schedule_phase(
        api,
        scenario,
        phase_number=1,
        start_date="2026-09-01",
        end_date="2026-09-10",
        rooms_out_of_service=10,
    )
    return scenario, budget, phase


def _request_a_small_draw(api, scenario, budget):
    return request_draw(
        api, scenario, budget["id"], scenario.item_id("corridors"), 100000
    )


class TestTheDrawLadderCannotBeSkipped:
    def test_the_request_earmarks_the_cash_without_paying_it(
        self, api, executing_plan_with_a_planned_closure
    ):
        """"A draw is created in `REQUESTED`, with `consented_by_user_id` and `disbursed_at` null, and
        increments the property's `version` by one." "A requested or consented draw *encumbers* its
        amount: it is earmarked but not yet paid."

        Design: Corner/errors/draw_and_phase_lifecycle_guards_are_triggerable
        """
        scenario, budget, _phase = executing_plan_with_a_planned_closure
        stale_version = current_property_version(
            api, scenario.property_id, scenario.owner_headers
        )

        draw = _request_a_small_draw(api, scenario, budget)

        assert_field_equals(draw, "status", "REQUESTED", "draw")
        assert draw["consented_by_user_id"] is None, (
            f"a requested draw carries no consenting operator yet, got {draw!r}"
        )
        assert draw["disbursed_at"] is None, (
            f"a requested draw has not been paid, got {draw!r}"
        )
        prop = read_property(api, scenario.property_id)
        assert_field_equals(prop, "version", stale_version + 1, "property")
        assert_field_equals(prop, "reserve_balance_cents", 50000000, "property")

    def test_a_requested_draw_is_neither_disbursable_nor_reversible(
        self, api, executing_plan_with_a_planned_closure
    ):
        """"The disbursement is refused unless the draw is in `BRAND_CONSENTED`
        (`ERR_DRAW_NOT_DISBURSABLE`)". "It is refused unless the draw is in `DISBURSED`
        (`ERR_DRAW_NOT_REVERSIBLE`)".

        Design: Corner/errors/draw_and_phase_lifecycle_guards_are_triggerable
        """
        scenario, budget, _phase = executing_plan_with_a_planned_closure
        draw = _request_a_small_draw(api, scenario, budget)

        validate_error(
            api.disburse_reserve_draw(draw["id"], scenario.owner_headers),
            ApiErrorId.ERR_DRAW_NOT_DISBURSABLE,
            409,
        )
        validate_error(
            api.reverse_reserve_draw(draw["id"], scenario.owner_headers),
            ApiErrorId.ERR_DRAW_NOT_REVERSIBLE,
            409,
        )

        assert_field_equals(read_draw(api, draw["id"]), "status", "REQUESTED", "draw")

    def test_the_brand_decides_once_and_only_once(
        self, api, brand_manager, executing_plan_with_a_planned_closure
    ):
        """"A decision of `CONSENT` moves it `REQUESTED → BRAND_CONSENTED` and stamps
        `consented_by_user_id` with the acting `X-User-ID`; the amount stays encumbered against the
        reserve." "Either decision is refused unless the draw is in `REQUESTED`
        (`ERR_DRAW_NOT_DECIDABLE`)".

        Design: Corner/errors/draw_and_phase_lifecycle_guards_are_triggerable
        """
        scenario, budget, _phase = executing_plan_with_a_planned_closure
        draw = _request_a_small_draw(api, scenario, budget)

        consented = consent_draw(api, draw["id"])
        response = api.consent_reserve_draw(
            draw["id"], draw_decision_payload("REJECT"), brand_manager
        )

        assert_field_equals(consented, "status", "BRAND_CONSENTED", "draw")
        assert_field_equals(consented, "consented_by_user_id", "bm-001", "draw")
        validate_error(response, ApiErrorId.ERR_DRAW_NOT_DECIDABLE, 409)
        assert_field_equals(
            read_draw(api, draw["id"]), "status", "BRAND_CONSENTED", "draw"
        )
        assert_field_equals(read_budget(api, budget["id"]), "committed_cents", 0, "budget")


class TestAClosureWindowOpensOnlyOnce:
    def test_a_planned_phase_cannot_be_closed_out(
        self, api, executing_plan_with_a_planned_closure
    ):
        """"Closing a phase out moves it `ACTIVE → CLOSED_OUT` and is refused unless the phase is
        `ACTIVE` (`ERR_PHASE_NOT_CLOSEABLE`), unless the acting `X-User-ID` is the property's
        `franchisee_id`, and unless no room-impacting item of the phase's plan is still `IN_PROGRESS`
        (`ERR_ROOM_WORK_STILL_IN_PROGRESS`)".

        Design: Corner/errors/draw_and_phase_lifecycle_guards_are_triggerable
        """
        scenario, _budget, phase = executing_plan_with_a_planned_closure

        response = api.close_out_renovation_phase(phase["id"], scenario.owner_headers)

        validate_error(response, ApiErrorId.ERR_PHASE_NOT_CLOSEABLE, 409)
        assert_field_equals(read_phase(api, phase["id"]), "status", "PLANNED", "phase")
        assert_field_equals(
            read_property(api, scenario.property_id),
            "rooms_out_of_service_current",
            0,
            "property",
        )

    def test_activation_takes_the_keys_out_once_and_refuses_a_repeat(
        self, api, executing_plan_with_a_planned_closure
    ):
        """"Activating a phase moves it `PLANNED → ACTIVE` and is refused unless the phase is in
        `PLANNED` (`ERR_PHASE_NOT_ACTIVATABLE`)". "Activation adds the phase's `rooms_out_of_service` to
        the property's `rooms_out_of_service_current` and increments the property's `version` ... and
        writes `ooo_pct_at_activation` as the phase's own out-of-service ratio rounded half up to 4
        decimal places — a field only the activation writes."

        Design: Corner/errors/draw_and_phase_lifecycle_guards_are_triggerable
        """
        scenario, _budget, phase = executing_plan_with_a_planned_closure
        set_clock(api, "2026-09-01T00:00:00Z")

        activated = activate_phase(api, scenario, phase["id"])
        response = api.activate_renovation_phase(phase["id"], scenario.owner_headers)

        assert_field_equals(activated, "status", "ACTIVE", "phase")
        assert Decimal(str(activated["ooo_pct_at_activation"])) == Decimal("0.0500"), (
            "ten keys of two hundred is a 0.0500 out-of-service ratio, got "
            f"{activated['ooo_pct_at_activation']!r}"
        )
        validate_error(response, ApiErrorId.ERR_PHASE_NOT_ACTIVATABLE, 409)
        assert_field_equals(read_phase(api, phase["id"]), "status", "ACTIVE", "phase")
        assert_field_equals(
            read_property(api, scenario.property_id),
            "rooms_out_of_service_current",
            10,
            "property",
        )

    def test_the_whole_probe_sequence_moves_no_cash_at_all(
        self, api, brand_manager, executing_plan_with_a_planned_closure
    ):
        """"Encumbered cash is the sum of `amount_cents` over that property's draws whose `status` is
        `REQUESTED` or `BRAND_CONSENTED`." "On success the draw's `amount_cents` is subtracted from
        `reserve_balance_cents` and the property's `version` increments ... the funding budget's
        `committed_cents` increases by the same amount".

        Design: Corner/errors/draw_and_phase_lifecycle_guards_are_triggerable
        """
        scenario, budget, phase = executing_plan_with_a_planned_closure
        draw = _request_a_small_draw(api, scenario, budget)
        consent_draw(api, draw["id"])
        validate_error(
            api.consent_reserve_draw(
                draw["id"], draw_decision_payload("REJECT"), brand_manager
            ),
            ApiErrorId.ERR_DRAW_NOT_DECIDABLE,
            409,
        )
        set_clock(api, "2026-09-01T00:00:00Z")
        activate_phase(api, scenario, phase["id"])

        prop = read_property(api, scenario.property_id)

        assert_field_equals(prop, "reserve_balance_cents", 50000000, "property")
        assert_field_equals(prop, "rooms_out_of_service_current", 10, "property")
        assert_field_equals(read_budget(api, budget["id"]), "committed_cents", 0, "budget")

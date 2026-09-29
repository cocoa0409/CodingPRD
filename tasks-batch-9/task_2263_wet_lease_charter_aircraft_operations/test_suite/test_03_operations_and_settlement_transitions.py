"""Flight-leg, substitution, invoice and dispute state transitions.

Each test drives the real API from an empty database and asserts the operational and
settlement halves of the state machinery: the dispatch guard on a terminal leg, the
weather diversion of an airborne leg, the two branches a substitution request takes on
the lease's substitution rights, the terminality of a withheld consent and of a voided
invoice, and the fork a dispute resolution takes between upholding and reopening.
"""

from datetime import datetime

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_substitute_candidate,
    cancel_leg_payload,
    close_month,
    consent_payload,
    create_settlement_invoice_payload,
    create_substitution_payload,
    dispatch_leg,
    dispatch_payload,
    dispute_payload,
    fly_leg,
    get_success_data,
    make_billing_admin_headers,
    resolve_dispute_payload,
    schedule_leg,
    setup_active_lease,
    setup_settled_month,
    validate_error,
    validate_paginated,
    validate_success,
    void_invoice_payload,
)

OPS = TEST_USERS["lessor_ops_headers"]
TECH = TEST_USERS["maintenance_controller_headers"]
BILLING = TEST_USERS["billing_admin_headers"]
SECOND_BILLING = TEST_USERS["second_billing_admin_headers"]


def _instant(value):
    """Parse an ISO 8601 UTC timestamp into a comparable datetime."""
    assert isinstance(value, str) and value, (
        f"expected an ISO 8601 UTC timestamp, got {value!r}"
    )
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _lease_version(api, lease_id):
    """The lease's current version, as a superseding writer must re-read it."""
    return get_success_data(api.get_lease(lease_id, OPS))["version"]


# --------------------------------------------------------------------------- #
# Flight legs: the dispatch guard and the weather diversion                     #
# --------------------------------------------------------------------------- #


def test_dispatch_on_a_completed_leg_is_refused_on_leg_state(api):
    """PRD §3.6: Releasing a leg for departure is admissible only from `SCHEDULED`, advances `status` from `SCHEDULED` to `DISPATCHED`, and records the supplied `actual_out` off-blocks instant.

    PRD §2.10: A leg is created `SCHEDULED`; `COMPLETED`, `CANCELLED_LESSEE`, `CANCELLED_LESSOR` and `DIVERTED` are terminal.

    PRD §2.8: 9. **State guards**, in this order: lessee state (`ERR_LESSEE_INVALID_STATE`), period readiness for settlement (`ERR_PERIOD_NOT_READY_FOR_SETTLEMENT`), lease state (`ERR_LEASE_INVALID_STATE`), docket determination state (`ERR_APPROVAL_INVALID_STATE`), leg state (`ERR_LEG_INVALID_STATE`), substitution state (`ERR_SUBSTITUTION_INVALID_STATE`), invoice state (`ERR_INVOICE_INVALID_STATE`), period state (`ERR_PERIOD_INVALID_STATE`), return-condition state (`ERR_RETURN_CONDITION_INVALID_STATE`), and finally airframe availability (`ERR_AIRCRAFT_UNAVAILABLE`).

    PRD §3.6: It advances `status` from `DISPATCHED` to `COMPLETED`, stores `actual_in` and the optionally supplied `technical_delay_minutes` (a non-negative count of departure-delay minutes attributable to a technical defect, defaulting to 0), and writes `block_minutes` as the whole number of minutes between `actual_out` and `actual_in` with the remaining seconds discarded.

    PRD §3.6: Completion also advances the airframe's counters: `block_minutes` divided by 60 is added to both `airframe_hours_total` and `hours_since_last_check`, each rounded to two decimal places, and `cycles_since_last_check` is increased by 1.

    Design: Corner/state_machines/dispatch_on_a_completed_leg_returns_leg_invalid_state
    """
    scenario = setup_active_lease(api)
    leg = fly_leg(
        api,
        scenario,
        scheduled_out="2026-09-08T06:00:00Z",
        scheduled_in="2026-09-08T08:35:30Z",
        actual_out="2026-09-08T06:10:00Z",
        actual_in="2026-09-08T08:35:00Z",
        technical_delay_minutes=10,
    )
    assert leg["status"] == "COMPLETED", (
        f"the leg must be COMPLETED before the replayed dispatch, got {leg['status']}"
    )

    validate_error(
        api.dispatch_flight_leg(
            leg["id"], dispatch_payload("2026-09-08T07:00:00Z"), OPS
        ),
        ApiErrorId.ERR_LEG_INVALID_STATE,
    )

    unchanged = validate_success(api.get_flight_leg(leg["id"], OPS), 200)
    assert unchanged["status"] == "COMPLETED", (
        f"the refused dispatch must leave the leg COMPLETED, got {unchanged['status']}"
    )
    assert _instant(unchanged["actual_out"]) == _instant("2026-09-08T06:10:00Z"), (
        "the refused dispatch must not overwrite the recorded off-blocks instant "
        f"2026-09-08T06:10:00Z, got {unchanged['actual_out']}"
    )
    assert unchanged["block_minutes"] == 145, (
        "06:10 to 08:35 is 145 whole block minutes, got "
        f"{unchanged['block_minutes']}"
    )
    assert unchanged["billable_block_minutes"] == 145, (
        "145 block minutes is above the one-hour minimum, so the billable figure is "
        f"145, got {unchanged['billable_block_minutes']}"
    )
    assert unchanged["technical_delay_minutes"] == 10, (
        "the technical_delay_minutes recorded at completion must survive, got "
        f"{unchanged['technical_delay_minutes']}"
    )

    aircraft = validate_success(api.get_aircraft(scenario["aircraft"]["id"], TECH), 200)
    assert aircraft["cycles_since_last_check"] == 41, (
        "one completion increases cycles_since_last_check from 40 to 41, and the refused "
        f"dispatch adds nothing, got {aircraft['cycles_since_last_check']}"
    )


def test_weather_cancellation_of_a_dispatched_leg_becomes_a_diversion(api):
    """PRD §3.6: A leg already `DISPATCHED` and cancelled with `cancel_reason` `WEATHER` is treated as a diversion instead: `status` becomes `DIVERTED`, `billing_state` becomes `CREDITED`, and `billable_block_minutes` stays 0 because no on-blocks instant was ever recorded.

    PRD §3.6: It is admissible from `SCHEDULED` or from `DISPATCHED`; from any other status the rejection is `ERR_LEG_INVALID_STATE` (HTTP 409).

    Design: Corner/state_machines/weather_cancellation_of_a_dispatched_leg_diverts_instead_of_cancelling_and_is_terminal
    """
    scenario = setup_active_lease(api)
    leg = schedule_leg(
        api,
        scenario,
        scheduled_out="2026-09-08T06:00:00Z",
        scheduled_in="2026-09-08T08:25:00Z",
    )
    dispatch_leg(api, leg["id"], "2026-09-08T06:10:00Z")

    diverted = validate_success(
        api.cancel_flight_leg(leg["id"], cancel_leg_payload("LESSOR", "WEATHER"), OPS),
        200,
    )

    assert diverted["status"] == "DIVERTED", (
        "a weather cancellation of an airborne leg must land in DIVERTED rather than "
        f"CANCELLED_LESSOR, got {diverted['status']}"
    )
    assert diverted["billing_state"] == "CREDITED", (
        f"a diverted leg's billing_state must become CREDITED, got {diverted['billing_state']}"
    )
    assert diverted["billable_block_minutes"] == 0, (
        "no on-blocks instant was ever recorded, so billable_block_minutes stays 0, got "
        f"{diverted['billable_block_minutes']}"
    )
    assert diverted["cancel_reason"] == "WEATHER", (
        f"the supplied cancel_reason WEATHER must be recorded, got {diverted['cancel_reason']}"
    )
    assert diverted["cancelling_party"] == "LESSOR", (
        f"the supplied cancelling_party LESSOR must be recorded, got {diverted['cancelling_party']}"
    )
    assert _instant(diverted["actual_out"]) == _instant("2026-09-08T06:10:00Z"), (
        "the diversion must keep the off-blocks instant recorded at dispatch, got "
        f"{diverted['actual_out']}"
    )
    assert diverted["actual_in"] is None, (
        f"no on-blocks instant was ever recorded, so actual_in stays null, got {diverted['actual_in']}"
    )


def test_a_diverted_leg_is_terminal_and_contributes_nothing_to_the_month(api):
    """PRD §3.6: It is admissible from `SCHEDULED` or from `DISPATCHED`; from any other status the rejection is `ERR_LEG_INVALID_STATE` (HTTP 409).

    PRD §2.10: A leg is created `SCHEDULED`; `COMPLETED`, `CANCELLED_LESSEE`, `CANCELLED_LESSOR` and `DIVERTED` are terminal.

    PRD §3.8: Cancelled and diverted legs contribute nothing at all, so no lessee-cancellation credit ever appears in a provisional figure.

    Design: Corner/state_machines/weather_cancellation_of_a_dispatched_leg_diverts_instead_of_cancelling_and_is_terminal
    """
    scenario = setup_active_lease(api)
    leg = schedule_leg(
        api,
        scenario,
        scheduled_out="2026-09-08T06:00:00Z",
        scheduled_in="2026-09-08T08:25:00Z",
    )
    dispatch_leg(api, leg["id"], "2026-09-08T06:10:00Z")
    get_success_data(
        api.cancel_flight_leg(leg["id"], cancel_leg_payload("LESSOR", "WEATHER"), OPS)
    )

    validate_error(
        api.cancel_flight_leg(
            leg["id"], cancel_leg_payload("LESSEE", "COMMERCIAL"), OPS
        ),
        ApiErrorId.ERR_LEG_INVALID_STATE,
    )

    unchanged = validate_success(api.get_flight_leg(leg["id"], OPS), 200)
    assert unchanged["status"] == "DIVERTED", (
        f"DIVERTED is terminal, so the leg must still read DIVERTED, got {unchanged['status']}"
    )
    assert unchanged["cancel_reason"] == "WEATHER", (
        "the refused second cancellation must not overwrite cancel_reason, got "
        f"{unchanged['cancel_reason']}"
    )
    assert unchanged["cancelling_party"] == "LESSOR", (
        "the refused second cancellation must not overwrite cancelling_party, got "
        f"{unchanged['cancelling_party']}"
    )

    period = validate_success(
        api.get_utilization_period(scenario["period"]["id"], BILLING), 200
    )
    assert float(period["credited_hours"]) == pytest.approx(0.0000, abs=0.0001), (
        "a diverted leg contributes nothing, so credited_hours stays 0.0000, got "
        f"{period['credited_hours']}"
    )
    assert period["provisional_charge_cents"] == 2400000, (
        "with nothing credited the provisional charge is the full 2400000-cent guarantee, "
        f"got {period['provisional_charge_cents']}"
    )

    legs, meta = validate_paginated(
        api.list_flight_legs(
            OPS, params={"lease_id": scenario["lease"]["id"], "status": "DIVERTED"}
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one leg on the lease must be DIVERTED, got {meta['total_count']}"
    )
    assert legs[0]["id"] == leg["id"], (
        f"the DIVERTED listing must return the diverted leg, got {legs[0]['id']}"
    )


# --------------------------------------------------------------------------- #
# Substitutions: the consent fork, the withheld branch and supersession         #
# --------------------------------------------------------------------------- #


def test_substitution_request_on_a_consent_required_lease_awaits_consent(api):
    """PRD §3.7: On a lease whose rights are `LESSEE_CONSENT_REQUIRED` the request lands in `LESSEE_CONSENT_PENDING`, `seat_delta` is written, no airframe is touched yet, and no prior request on the lease is disturbed.

    PRD §3.7: Either way the request records `seat_delta` as the substitute's `seat_count` less the original's `seat_count` — a figure the lessee needs for its consent decision — and `repointed_leg_count` as 0 at creation, and the lease's `version` increments by 1.

    PRD §3.7: When `substitute_aircraft_id` is supplied, `selection_basis` is recorded as `CLIENT_SPECIFIED` and the named airframe must satisfy every eligibility test: its `type_family` must equal the original's `type_family` (the exact `type_designator` may differ, which is what makes the crew-rating cascade reachable), its `seat_count` must be at least the original's `seat_count` less a tolerance of five seats, its `status` must be `AVAILABLE`, its `assigned_lease_id` must be null, and its `hours_since_last_check` must not exceed 400.00 hours.

    Design: Corner/state_machines/substitution_request_on_consent_required_lease_starts_in_consent_pending
    """
    scenario = setup_active_lease(
        api,
        with_first_officer=False,
        lease_overrides={"substitution_rights": "LESSEE_CONSENT_REQUIRED"},
    )
    lease_id = scenario["lease"]["id"]
    original_id = scenario["aircraft"]["id"]
    substitute = add_substitute_candidate(
        api,
        tail_number="G-SUBA",
        type_designator="B737",
        seat_count=186,
        hours_since_last_check=200.00,
    )

    substitution = validate_success(
        api.create_substitution(
            create_substitution_payload(
                lease_id,
                original_id,
                _lease_version(api, lease_id),
                substitute_aircraft_id=substitute["id"],
                effective_from="2026-09-20T00:00:00Z",
            ),
            OPS,
        ),
        201,
    )

    assert substitution["status"] == "LESSEE_CONSENT_PENDING", (
        "a request on a consent-required lease must land in LESSEE_CONSENT_PENDING, got "
        f"{substitution['status']}"
    )
    assert substitution["selection_basis"] == "CLIENT_SPECIFIED", (
        "a named substitute must be recorded as CLIENT_SPECIFIED, got "
        f"{substitution['selection_basis']}"
    )
    assert substitution["seat_delta"] == -3, (
        "seat_delta is the substitute's 186 seats less the original's 189, that is -3, got "
        f"{substitution['seat_delta']}"
    )
    assert substitution["repointed_leg_count"] == 0, (
        f"repointed_leg_count must be 0 at creation, got {substitution['repointed_leg_count']}"
    )

    substitute_now = validate_success(api.get_aircraft(substitute["id"], TECH), 200)
    assert substitute_now["status"] == "AVAILABLE", (
        f"no airframe is touched yet, so the substitute stays AVAILABLE, got {substitute_now['status']}"
    )
    assert substitute_now["assigned_lease_id"] is None, (
        "no airframe is touched yet, so the substitute's assigned_lease_id stays null, got "
        f"{substitute_now['assigned_lease_id']}"
    )

    original_now = validate_success(api.get_aircraft(original_id, TECH), 200)
    assert original_now["status"] == "ASSIGNED", (
        f"the original airframe must remain ASSIGNED, got {original_now['status']}"
    )
    assert original_now["assigned_lease_id"] == lease_id, (
        "the original airframe must keep its assigned_lease_id, got "
        f"{original_now['assigned_lease_id']}"
    )

    lease = validate_success(api.get_lease(lease_id, OPS), 200)
    assert lease["primary_aircraft_id"] == original_id, (
        "the lease's primary_aircraft_id must not move before effectuation, got "
        f"{lease['primary_aircraft_id']}"
    )


def _withheld_request(api):
    """A consent-required lease whose first substitution request was withheld."""
    scenario = setup_active_lease(
        api,
        with_first_officer=False,
        lease_overrides={"substitution_rights": "LESSEE_CONSENT_REQUIRED"},
    )
    lease_id = scenario["lease"]["id"]
    scenario["substitute_a"] = add_substitute_candidate(
        api,
        tail_number="G-SUBA",
        type_designator="B739",
        seat_count=189,
        hours_since_last_check=90.00,
    )
    scenario["substitution"] = get_success_data(
        api.create_substitution(
            create_substitution_payload(
                lease_id,
                scenario["aircraft"]["id"],
                _lease_version(api, lease_id),
                substitute_aircraft_id=scenario["substitute_a"]["id"],
                effective_from="2026-09-20T00:00:00Z",
            ),
            OPS,
        )
    )
    return scenario


def test_withheld_consent_is_terminal_for_the_substitution(api):
    """PRD §3.7: `GRANT` moves the request from `LESSEE_CONSENT_PENDING` to `APPROVED`; `WITHHOLD` moves it to the terminal `REJECTED` and the original airframe stays on the lease.

    PRD §3.7: Both record the note.

    PRD §2.8: An effectuation attempted on a substitution still awaiting lessee consent, on a lease whose substitution rights require that consent, deliberately *passes* the substitution state guard and falls through to the consent gate, so the caller receives `ERR_SUBSTITUTION_CONSENT_REQUIRED` rather than `ERR_SUBSTITUTION_INVALID_STATE`; every other undeclared source state for effectuation — a request still `REQUESTED`, or already `REJECTED`, `EFFECTIVE` or `WITHDRAWN` — and every source state other than awaiting-consent for a consent decision, is reported as `ERR_SUBSTITUTION_INVALID_STATE`.

    Design: Corner/state_machines/withheld_consent_is_terminal_and_survives_a_later_superseding_request
    """
    scenario = _withheld_request(api)
    lease_id = scenario["lease"]["id"]
    substitution_id = scenario["substitution"]["id"]

    rejected = validate_success(
        api.consent_substitution(
            substitution_id,
            consent_payload(
                "WITHHOLD", consent_note="seat map unacceptable for the block"
            ),
            scenario["lessee_headers"],
        ),
        200,
    )
    assert rejected["status"] == "REJECTED", (
        f"WITHHOLD must move the request to the terminal REJECTED, got {rejected['status']}"
    )
    assert rejected["consent_note"] == "seat map unacceptable for the block", (
        f"the consent decision must record the note, got {rejected['consent_note']}"
    )

    validate_error(
        api.effectuate_substitution(substitution_id, OPS),
        ApiErrorId.ERR_SUBSTITUTION_INVALID_STATE,
    )
    validate_error(
        api.consent_substitution(
            substitution_id, consent_payload("GRANT"), scenario["lessee_headers"]
        ),
        ApiErrorId.ERR_SUBSTITUTION_INVALID_STATE,
    )

    still_rejected = validate_success(api.get_substitution(substitution_id, OPS), 200)
    assert still_rejected["status"] == "REJECTED", (
        f"REJECTED is terminal, so the request must still read REJECTED, got {still_rejected['status']}"
    )

    original = validate_success(api.get_aircraft(scenario["aircraft"]["id"], TECH), 200)
    assert original["status"] == "ASSIGNED", (
        f"the original airframe stays on the lease, got {original['status']}"
    )
    lease = validate_success(api.get_lease(lease_id, OPS), 200)
    assert lease["primary_aircraft_id"] == scenario["aircraft"]["id"], (
        "the original airframe stays on the lease, so primary_aircraft_id is unchanged, "
        f"got {lease['primary_aircraft_id']}"
    )


def test_a_later_request_does_not_disturb_the_rejected_one(api):
    """PRD §3.7: On a lease whose rights are `LESSEE_CONSENT_REQUIRED` the request lands in `LESSEE_CONSENT_PENDING`, `seat_delta` is written, no airframe is touched yet, and no prior request on the lease is disturbed.

    PRD §3.7: `GRANT` moves the request from `LESSEE_CONSENT_PENDING` to `APPROVED`; `WITHHOLD` moves it to the terminal `REJECTED` and the original airframe stays on the lease.

    Design: Corner/state_machines/withheld_consent_is_terminal_and_survives_a_later_superseding_request
    """
    scenario = _withheld_request(api)
    lease_id = scenario["lease"]["id"]
    first_id = scenario["substitution"]["id"]
    get_success_data(
        api.consent_substitution(
            first_id,
            consent_payload(
                "WITHHOLD", consent_note="seat map unacceptable for the block"
            ),
            scenario["lessee_headers"],
        )
    )
    substitute_b = add_substitute_candidate(
        api,
        tail_number="G-SUBB",
        type_designator="B738",
        seat_count=189,
        hours_since_last_check=40.00,
    )

    second = validate_success(
        api.create_substitution(
            create_substitution_payload(
                lease_id,
                scenario["aircraft"]["id"],
                _lease_version(api, lease_id),
                substitute_aircraft_id=substitute_b["id"],
                effective_from="2026-09-25T00:00:00Z",
            ),
            OPS,
        ),
        201,
    )
    assert second["status"] == "LESSEE_CONSENT_PENDING", (
        "the later request on a consent-required lease must also land in "
        f"LESSEE_CONSENT_PENDING, got {second['status']}"
    )
    assert second["substitute_aircraft_id"] == substitute_b["id"], (
        f"the later request must name the second substitute, got {second['substitute_aircraft_id']}"
    )
    assert second["seat_delta"] == 0, (
        "the second substitute matches the original's 189 seats, so seat_delta is 0, got "
        f"{second['seat_delta']}"
    )

    first = validate_success(api.get_substitution(first_id, OPS), 200)
    assert first["status"] == "REJECTED", (
        "a later request on a consent-required lease disturbs no prior request, so the "
        f"withheld one stays REJECTED, got {first['status']}"
    )

    withdrawn, meta = validate_paginated(
        api.list_substitutions(OPS, params={"lease_id": lease_id, "status": "WITHDRAWN"})
    )
    assert meta["total_count"] == 0, (
        "consent-required rights withdraw nothing, so no substitution on the lease may "
        f"be WITHDRAWN, got {meta['total_count']}"
    )
    assert withdrawn == [], f"expected no WITHDRAWN substitution rows, got {withdrawn}"

    lease = validate_success(api.get_lease(lease_id, OPS), 200)
    assert lease["primary_aircraft_id"] == scenario["aircraft"]["id"], (
        "no airframe is touched by either request, so primary_aircraft_id is unchanged, "
        f"got {lease['primary_aircraft_id']}"
    )


def _unilateral_supersession(api):
    """A unilateral lease carrying an APPROVED request superseded by a later one."""
    scenario = setup_active_lease(api, with_first_officer=False)
    lease_id = scenario["lease"]["id"]
    scenario["substitute_a"] = add_substitute_candidate(
        api,
        tail_number="G-SUBA",
        type_designator="B739",
        seat_count=189,
        hours_since_last_check=90.00,
    )
    scenario["substitute_b"] = add_substitute_candidate(
        api,
        tail_number="G-SUBB",
        type_designator="B738",
        seat_count=189,
        hours_since_last_check=40.00,
    )
    scenario["first"] = get_success_data(
        api.create_substitution(
            create_substitution_payload(
                lease_id,
                scenario["aircraft"]["id"],
                _lease_version(api, lease_id),
                substitute_aircraft_id=scenario["substitute_a"]["id"],
                effective_from="2026-09-20T00:00:00Z",
            ),
            OPS,
        )
    )
    assert scenario["first"]["status"] == "APPROVED", (
        "a request on a unilateral lease lands directly in APPROVED, got "
        f"{scenario['first']['status']}"
    )
    return scenario


def test_a_later_request_on_a_unilateral_lease_withdraws_the_earlier_open_one(api):
    """PRD §3.7: On a lease whose rights are `LESSOR_UNILATERAL` the request lands directly in `APPROVED`, `seat_delta` is written, no airframe is touched yet, and — this is the branch's extra effect — every other substitution on the same lease whose `status` is `REQUESTED`, `LESSEE_CONSENT_PENDING` or `APPROVED` is moved to the terminal `WITHDRAWN`, without touching any airframe.

    PRD §2.6: A new substitution request legitimately supersedes prior open requests on the same lease and, on a lease whose substitution rights are unilateral, withdraws them outright — so a writer whose view of the lease predates the last airframe re-point, suspension or activation must re-read the lease before it is permitted to supersede anything.

    PRD §2.8: An effectuation attempted on a substitution still awaiting lessee consent, on a lease whose substitution rights require that consent, deliberately *passes* the substitution state guard and falls through to the consent gate, so the caller receives `ERR_SUBSTITUTION_CONSENT_REQUIRED` rather than `ERR_SUBSTITUTION_INVALID_STATE`; every other undeclared source state for effectuation — a request still `REQUESTED`, or already `REJECTED`, `EFFECTIVE` or `WITHDRAWN` — and every source state other than awaiting-consent for a consent decision, is reported as `ERR_SUBSTITUTION_INVALID_STATE`.

    Design: Corner/state_machines/a_later_request_on_a_unilateral_lease_withdraws_the_earlier_open_one
    """
    scenario = _unilateral_supersession(api)
    lease_id = scenario["lease"]["id"]

    second = validate_success(
        api.create_substitution(
            create_substitution_payload(
                lease_id,
                scenario["aircraft"]["id"],
                _lease_version(api, lease_id),
                substitute_aircraft_id=scenario["substitute_b"]["id"],
                effective_from="2026-09-25T00:00:00Z",
            ),
            OPS,
        ),
        201,
    )
    assert second["status"] == "APPROVED", (
        f"the later request must also land directly in APPROVED, got {second['status']}"
    )
    assert second["selection_basis"] == "CLIENT_SPECIFIED", (
        f"a named substitute must be recorded as CLIENT_SPECIFIED, got {second['selection_basis']}"
    )
    assert second["repointed_leg_count"] == 0, (
        f"repointed_leg_count must be 0 at creation, got {second['repointed_leg_count']}"
    )

    first = validate_success(api.get_substitution(scenario["first"]["id"], OPS), 200)
    assert first["status"] == "WITHDRAWN", (
        "the earlier APPROVED request on a unilateral lease must be moved to the "
        f"terminal WITHDRAWN, got {first['status']}"
    )

    validate_error(
        api.effectuate_substitution(scenario["first"]["id"], OPS),
        ApiErrorId.ERR_SUBSTITUTION_INVALID_STATE,
    )

    substitute_a = validate_success(
        api.get_aircraft(scenario["substitute_a"]["id"], TECH), 200
    )
    assert substitute_a["status"] == "AVAILABLE", (
        "the withdrawal must touch no airframe, so the first substitute stays AVAILABLE, "
        f"got {substitute_a['status']}"
    )
    original = validate_success(api.get_aircraft(scenario["aircraft"]["id"], TECH), 200)
    assert original["status"] == "ASSIGNED", (
        f"no airframe is touched by either request, got {original['status']}"
    )


def test_the_superseding_request_effectuates_and_repoints_the_lease(api):
    """PRD §3.7: Operations control effectuates an `APPROVED` substitution.

    PRD §3.7: Level one: the substitute's `status` becomes `ASSIGNED` and its `assigned_lease_id` the lease; the original airframe has `assigned_lease_id` cleared and its `status` moved from `ASSIGNED` to `AVAILABLE`, except that an original already `IN_MAINTENANCE` or `AOG` keeps that status; and the lease's `primary_aircraft_id` is re-pointed to the substitute.

    PRD §3.7: Effectuation moves the request to the terminal `EFFECTIVE` and runs the four-level cascade.

    Design: Corner/state_machines/a_later_request_on_a_unilateral_lease_withdraws_the_earlier_open_one
    """
    scenario = _unilateral_supersession(api)
    lease_id = scenario["lease"]["id"]
    second = get_success_data(
        api.create_substitution(
            create_substitution_payload(
                lease_id,
                scenario["aircraft"]["id"],
                _lease_version(api, lease_id),
                substitute_aircraft_id=scenario["substitute_b"]["id"],
                effective_from="2026-09-25T00:00:00Z",
            ),
            OPS,
        )
    )

    effective = validate_success(api.effectuate_substitution(second["id"], OPS), 200)
    assert effective["status"] == "EFFECTIVE", (
        f"effectuation must move the request to the terminal EFFECTIVE, got {effective['status']}"
    )
    assert effective["repointed_leg_count"] == 0, (
        "no leg lies on or after the effective instant, so repointed_leg_count stays 0, "
        f"got {effective['repointed_leg_count']}"
    )

    lease = validate_success(api.get_lease(lease_id, OPS), 200)
    assert lease["primary_aircraft_id"] == scenario["substitute_b"]["id"], (
        "the lease's primary_aircraft_id must be re-pointed to the effectuated "
        f"substitute, got {lease['primary_aircraft_id']}"
    )

    substitute_b = validate_success(
        api.get_aircraft(scenario["substitute_b"]["id"], TECH), 200
    )
    assert substitute_b["status"] == "ASSIGNED", (
        f"the substitute's status must become ASSIGNED, got {substitute_b['status']}"
    )
    assert substitute_b["assigned_lease_id"] == lease_id, (
        "the substitute's assigned_lease_id must become the lease, got "
        f"{substitute_b['assigned_lease_id']}"
    )

    original = validate_success(api.get_aircraft(scenario["aircraft"]["id"], TECH), 200)
    assert original["status"] == "AVAILABLE", (
        f"the released original must move from ASSIGNED to AVAILABLE, got {original['status']}"
    )
    assert original["assigned_lease_id"] is None, (
        f"the released original must have assigned_lease_id cleared, got {original['assigned_lease_id']}"
    )

    substitute_a = validate_success(
        api.get_aircraft(scenario["substitute_a"]["id"], TECH), 200
    )
    assert substitute_a["status"] == "AVAILABLE", (
        "the withdrawn request's substitute must remain AVAILABLE, got "
        f"{substitute_a['status']}"
    )


# --------------------------------------------------------------------------- #
# Invoices: the void terminal                                                  #
# --------------------------------------------------------------------------- #


def _voided_prepared_invoice(api):
    """A closed month whose FINAL invoice was voided while still PREPARED."""
    scenario = setup_active_lease(api, with_first_officer=False)
    scenario["period"] = close_month(api, scenario["period"]["id"])
    preparer = make_billing_admin_headers("billing-clerk-01")
    scenario["preparer"] = preparer
    invoice = validate_success(
        api.create_settlement_invoice(
            create_settlement_invoice_payload(
                scenario["period"]["id"],
                scenario["period"]["version"],
                "2026-10-15",
                variant="FINAL",
            ),
            preparer,
        ),
        201,
    )
    assert invoice["status"] == "PREPARED", (
        f"a fresh invoice starts PREPARED, got {invoice['status']}"
    )
    assert invoice["amount_cents"] == 2400000, (
        "a FINAL invoice freezes the period's final_charge_cents of 2400000, got "
        f"{invoice['amount_cents']}"
    )
    scenario["invoice"] = get_success_data(
        api.void_settlement_invoice(
            invoice["id"], void_invoice_payload("PREPARED_IN_ERROR"), preparer
        )
    )
    return scenario


def test_issue_on_a_void_invoice_is_refused(api):
    """PRD §3.9: Voiding is admissible from `PREPARED`, from `APPROVED` or from `ISSUED`, always records the supplied `void_reason`, and always lands in the terminal `VOID`.

    PRD §3.9: An invoice transition requested from an undeclared source status is refused with `ERR_INVOICE_INVALID_STATE` (HTTP 409).

    PRD §3.9: Voiding a `PREPARED` or `APPROVED` invoice leaves the lessee receivable untouched.

    Design: Corner/state_machines/issue_on_a_void_invoice_returns_invoice_invalid_state
    """
    scenario = _voided_prepared_invoice(api)
    invoice = scenario["invoice"]
    assert invoice["status"] == "VOID", (
        f"voiding a PREPARED invoice must land in the terminal VOID, got {invoice['status']}"
    )
    assert invoice["void_reason"] == "PREPARED_IN_ERROR", (
        f"the supplied void_reason must be recorded, got {invoice['void_reason']}"
    )

    validate_error(
        api.issue_settlement_invoice(invoice["id"], SECOND_BILLING),
        ApiErrorId.ERR_INVOICE_INVALID_STATE,
    )

    unchanged = validate_success(api.get_settlement_invoice(invoice["id"], BILLING), 200)
    assert unchanged["status"] == "VOID", (
        f"the refused issue must leave the invoice VOID, got {unchanged['status']}"
    )
    assert unchanged["amount_cents"] == 2400000, (
        f"the refused issue must not rewrite amount_cents, got {unchanged['amount_cents']}"
    )

    lessee = validate_success(
        api.get_lessee(scenario["lessee"]["id"], scenario["lessee_headers"]), 200
    )
    assert lessee["outstanding_balance_usd_cents"] == 0, (
        "voiding a PREPARED invoice leaves the receivable untouched, so the balance "
        f"stays 0, got {lessee['outstanding_balance_usd_cents']}"
    )

    period = validate_success(
        api.get_utilization_period(scenario["period"]["id"], BILLING), 200
    )
    assert period["status"] == "PENDING_SETTLEMENT", (
        "the closed month must still await settlement, got "
        f"{period['status']}"
    )


def test_a_second_void_on_a_void_invoice_is_refused(api):
    """PRD §3.9: Voiding is admissible from `PREPARED`, from `APPROVED` or from `ISSUED`, always records the supplied `void_reason`, and always lands in the terminal `VOID`.

    PRD §3.9: An invoice transition requested from an undeclared source status is refused with `ERR_INVOICE_INVALID_STATE` (HTTP 409).

    Design: Corner/state_machines/issue_on_a_void_invoice_returns_invoice_invalid_state
    """
    scenario = _voided_prepared_invoice(api)
    invoice_id = scenario["invoice"]["id"]

    validate_error(
        api.void_settlement_invoice(
            invoice_id, void_invoice_payload("DUPLICATE_VOID"), scenario["preparer"]
        ),
        ApiErrorId.ERR_INVOICE_INVALID_STATE,
    )

    unchanged = validate_success(api.get_settlement_invoice(invoice_id, BILLING), 200)
    assert unchanged["status"] == "VOID", (
        f"VOID is terminal, so the invoice must still read VOID, got {unchanged['status']}"
    )
    assert unchanged["void_reason"] == "PREPARED_IN_ERROR", (
        "the refused second void must not overwrite the recorded void_reason, got "
        f"{unchanged['void_reason']}"
    )


# --------------------------------------------------------------------------- #
# Disputes: the resolution fork                                                #
# --------------------------------------------------------------------------- #


def _disputed_month(api):
    """A settled 2026-09 month with an ISSUED invoice, put into dispute by the lessee."""
    scenario = setup_settled_month(api, leg_plan=[], with_first_officer=False)
    assert scenario["period"]["status"] == "SETTLED", (
        f"the month must be SETTLED before the dispute, got {scenario['period']['status']}"
    )
    scenario["period"] = validate_success(
        api.dispute_utilization_period(
            scenario["period"]["id"],
            dispute_payload(
                dispute_reason="SHORTFALL_ATTRIBUTION_CHALLENGED",
                disputed_amount_cents=1440000,
            ),
            scenario["lessee_headers"],
        ),
        200,
    )
    assert scenario["period"]["status"] == "DISPUTED", (
        f"the dispute must move the month to DISPUTED, got {scenario['period']['status']}"
    )
    return scenario


def test_upholding_the_settlement_returns_the_month_to_settled(api):
    """PRD §3.9: `UPHOLD_SETTLEMENT` returns the period from `DISPUTED` to `SETTLED`, clears `disputed_amount_cents` to 0, and keeps `dispute_reason` on the row for audit.

    PRD §3.9: The settlement desk resolves the dispute by supplying a `resolution` of `REOPEN` or `UPHOLD_SETTLEMENT`, admissible only from `DISPUTED`.

    PRD §3.9: The dispute moves the period from `SETTLED` to `DISPUTED`, records both fields, and increments the period's `version`.

    Design: Corner/state_machines/dispute_resolution_forks_between_upholding_the_settlement_and_reopening_the_month
    """
    scenario = _disputed_month(api)
    period_id = scenario["period"]["id"]

    upheld = validate_success(
        api.resolve_dispute(
            period_id, resolve_dispute_payload("UPHOLD_SETTLEMENT"), BILLING
        ),
        200,
    )
    assert upheld["status"] == "SETTLED", (
        f"UPHOLD_SETTLEMENT must return the month to SETTLED, got {upheld['status']}"
    )
    assert upheld["disputed_amount_cents"] == 0, (
        f"UPHOLD_SETTLEMENT must clear disputed_amount_cents to 0, got {upheld['disputed_amount_cents']}"
    )
    assert upheld["dispute_reason"] == "SHORTFALL_ATTRIBUTION_CHALLENGED", (
        f"UPHOLD_SETTLEMENT keeps dispute_reason for audit, got {upheld['dispute_reason']}"
    )
    assert upheld["final_charge_cents"] == 2400000, (
        "upholding the settlement recomputes nothing, so final_charge_cents stays "
        f"2400000, got {upheld['final_charge_cents']}"
    )

    invoice = validate_success(
        api.get_settlement_invoice(scenario["invoice"]["id"], BILLING), 200
    )
    assert invoice["status"] == "ISSUED", (
        f"upholding the settlement voids no invoice, got {invoice['status']}"
    )
    lessee = validate_success(
        api.get_lessee(scenario["lessee"]["id"], scenario["lessee_headers"]), 200
    )
    assert lessee["outstanding_balance_usd_cents"] == 2400000, (
        "the ISSUED invoice still stands, so the receivable stays at 2400000, got "
        f"{lessee['outstanding_balance_usd_cents']}"
    )

    redisputed = validate_success(
        api.dispute_utilization_period(
            period_id,
            dispute_payload(
                dispute_reason="SHORTFALL_ATTRIBUTION_CHALLENGED_AGAIN",
                disputed_amount_cents=1440000,
            ),
            scenario["lessee_headers"],
        ),
        200,
    )
    assert redisputed["status"] == "DISPUTED", (
        "a month returned to SETTLED may be disputed again, got "
        f"{redisputed['status']}"
    )


def test_reopening_the_month_voids_the_issued_invoice_and_permits_a_reclose(api):
    """PRD §3.9: `REOPEN` moves the period from `DISPUTED` to `REOPENED` and voids every invoice on the period whose `status` is `ISSUED`, each void decrementing the lessee's `outstanding_balance_usd_cents` by that invoice's `amount_cents`.

    PRD §3.9: `REOPENED` is a resting state: a subsequent close recomputes every charge field under the `FINAL` variant, rewrites `final_charge_cents`, returns the period to `PENDING_SETTLEMENT`, and — unlike a first close — creates no following month's period.

    PRD §2.9: `LeaseAgreement.lifetime_credited_block_minutes` accumulates the `credited_block_minutes` of the lease's settled months: a period settling adds its figure, and a settled period returning to await settlement because its invoice was voided subtracts the same figure.

    Design: Corner/state_machines/dispute_resolution_forks_between_upholding_the_settlement_and_reopening_the_month
    """
    scenario = _disputed_month(api)
    period_id = scenario["period"]["id"]
    lease_id = scenario["lease"]["id"]

    reopened = validate_success(
        api.resolve_dispute(period_id, resolve_dispute_payload("REOPEN"), BILLING), 200
    )
    assert reopened["status"] == "REOPENED", (
        f"REOPEN must move the month from DISPUTED to REOPENED, got {reopened['status']}"
    )

    invoice = validate_success(
        api.get_settlement_invoice(scenario["invoice"]["id"], BILLING), 200
    )
    assert invoice["status"] == "VOID", (
        f"REOPEN must void the month's ISSUED invoice, got {invoice['status']}"
    )
    lessee = validate_success(
        api.get_lessee(scenario["lessee"]["id"], scenario["lessee_headers"]), 200
    )
    assert lessee["outstanding_balance_usd_cents"] == 0, (
        "voiding the 2400000-cent ISSUED invoice must decrement the receivable to 0, got "
        f"{lessee['outstanding_balance_usd_cents']}"
    )

    reclosed = validate_success(api.close_utilization_period(period_id, BILLING), 200)
    assert reclosed["status"] == "PENDING_SETTLEMENT", (
        f"a close from REOPENED must return the month to PENDING_SETTLEMENT, got {reclosed['status']}"
    )
    assert reclosed["variant_applied"] == "FINAL", (
        f"the reclose recomputes under the FINAL variant, got {reclosed['variant_applied']}"
    )
    assert reclosed["final_charge_cents"] == 2400000, (
        "the month still carries no credited hours, so final_charge_cents is rewritten "
        f"as 2400000, got {reclosed['final_charge_cents']}"
    )

    periods, meta = validate_paginated(
        api.list_utilization_periods(BILLING, params={"lease_id": lease_id})
    )
    assert meta["total_count"] == 2, (
        "the first close opened 2026-10 and the reclose creates no further month, so the "
        f"lease owns 2 periods, got {meta['total_count']}"
    )
    assert [row["period_month"] for row in periods] == ["2026-09", "2026-10"], (
        "the lease must own only the 2026-09 and 2026-10 windows, got "
        f"{[row['period_month'] for row in periods]}"
    )

    lease = validate_success(api.get_lease(lease_id, OPS), 200)
    assert lease["lifetime_credited_block_minutes"] == 0, (
        "the settled month credited no block minutes and the void subtracted the same "
        f"figure, so the lifetime total is 0, got {lease['lifetime_credited_block_minutes']}"
    )

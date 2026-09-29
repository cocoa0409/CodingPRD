"""Activation: the cross-entity gates, and which refusal wins when several could fire."""
from prd_bench_local_runner.testing import validate_error

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.test_users import media_buyer_headers


def _reserved_flight_on_cleared_posting(api):
    """A funded reservation whose posting is optimized and cleared but never published."""
    program = fx.create_program(api)
    family = fx.create_job_family(api, program["id"], dedicated_budget_cents=500000)
    channel = fx.create_channel(api, program["id"])
    fx.approved_persona(api, family["id"], channel["id"])
    posting = fx.create_posting(api, family["id"])
    fx.optimize_posting(api, posting["id"], posting["version"])
    fx.clear_posting(api, posting["id"])
    flight = fx.reserve_flight(
        api,
        channel["id"],
        family["id"],
        posting["id"],
        fx.program_version(api, program["id"]),
        start_date="2026-08-01",
        end_date="2026-08-08",
        daily_cap_cents=50000,
    )
    return program, family, channel, posting, flight


def test_activation_is_refused_while_the_posting_is_cleared_but_unpublished(api):
    """PRD §3.5: "Three cross-entity gates apply: the flight's posting must have
    `content_status` `PUBLISHED`, refusing otherwise with `ERR_POSTING_NOT_PUBLISHED`; the same
    posting must have `compliance_status` `CLEARED`, refusing otherwise with
    `ERR_POSTING_COMPLIANCE_NOT_CLEARED`; and the funding program's `brand_health_score` must be
    at least `55.00`, refusing otherwise with `ERR_BRAND_HEALTH_GATE`."
    PRD §3.4: "The flight is persisted in state `RESERVED` with `reserved_cents` equal to
    `total_cost_cents`, `spent_cents` 0, `qualified_credit_bp` 0, and `release_reason` and
    `activated_at` both null."

    Design: Difficulty/cross_entity_state_dependency/flight_activation_requires_its_posting_to_be_published
    """
    program, _, channel, _, flight = _reserved_flight_on_cleared_posting(api)

    refused = api.activate_media_flight(flight["id"], media_buyer_headers())

    validate_error(refused, ApiErrorId.POSTING_NOT_PUBLISHED, 409)
    unchanged = fx.read_flight(api, flight["id"])
    assert unchanged["state"] == "RESERVED", unchanged
    assert unchanged["activated_at"] is None, unchanged
    a.assert_cents(unchanged["reserved_cents"], 360500, "reserved_cents")
    assert fx.read_channel(api, channel["id"])["active_flight_count"] == 0
    a.assert_cents(
        fx.read_program(api, program["id"])["committed_budget_cents"],
        360500,
        "committed_budget_cents",
    )


def test_publishing_the_posting_lets_the_reservation_activate_on_an_uncredited_channel(api):
    """PRD §3.5: "Activation sets `activated_at` to the logical clock, increments the channel's
    `active_flight_count` by 1, clears the channel's `idle_since` back to null, and re-runs the
    channel's blended target and cost-per-qualified-applicant calculations, rewriting
    `blended_target_cents`, `cpqa_cents` and `pacing_status`."
    PRD §3.5: "When the channel's `credited_qualified_bp` is zero, `cpqa_cents` is null,
    `blended_target_cents` is null, and `pacing_status` becomes `PACING_UNKNOWN` — note that
    `IDLE` is never produced by this path, only by the flight-departure rule."

    Design: Difficulty/cross_entity_state_dependency/flight_activation_requires_its_posting_to_be_published
    """
    program, _, channel, posting, flight = _reserved_flight_on_cleared_posting(api)
    fx.publish_posting(api, posting["id"])

    activated = fx.activate_flight(api, flight["id"])

    assert activated["state"] == "ACTIVE", activated
    assert activated["activated_at"] is not None, activated
    assert activated["activated_at"].startswith("2026-08-01T00:00:00"), activated
    channel_row = fx.read_channel(api, channel["id"])
    assert channel_row["active_flight_count"] == 1, channel_row
    assert channel_row["idle_since"] is None, channel_row
    assert channel_row["credited_qualified_bp"] == 0, channel_row
    assert channel_row["cpqa_cents"] is None, channel_row
    assert channel_row["blended_target_cents"] is None, channel_row
    assert channel_row["pacing_status"] == "PACING_UNKNOWN", channel_row
    a.assert_cents(
        fx.read_program(api, program["id"])["committed_budget_cents"],
        360500,
        "committed_budget_cents",
    )


def _cancelled_and_reserved_flights_on_a_flagged_posting(api):
    """One cancelled flight and one live reservation, both pointing at a flagged posting."""
    program = fx.create_program(api)
    family = fx.create_job_family(api, program["id"], dedicated_budget_cents=1000000)
    channel = fx.create_channel(api, program["id"])
    posting = fx.published_posting(api, family["id"], channel["id"])
    cancelled = fx.reserve_flight(
        api,
        channel["id"],
        family["id"],
        posting["id"],
        fx.program_version(api, program["id"]),
        start_date="2026-08-01",
        end_date="2026-08-08",
        daily_cap_cents=50000,
    )
    fx.cancel_flight(api, cancelled["id"])
    fx.flag_posting(api, posting["id"])
    reserved = fx.reserve_flight(
        api,
        channel["id"],
        family["id"],
        posting["id"],
        fx.program_version(api, program["id"]),
        start_date="2026-08-01",
        end_date="2026-08-08",
        daily_cap_cents=50000,
    )
    return program, family, channel, posting, cancelled, reserved


def test_a_cancelled_flight_reports_its_own_state_error_not_the_compliance_gate(api):
    """PRD §2.9: "16. A flight's `state` must permit the requested transition — activation
    requires `RESERVED` (`ERR_FLIGHT_NOT_RESERVED`), resumption requires `PAUSED_PACING` or
    `SUSPENDED_CONTENT` (`ERR_FLIGHT_NOT_RESUMABLE`), completion requires `ACTIVE` or
    `PAUSED_PACING` (`ERR_FLIGHT_NOT_COMPLETABLE`), cancellation requires a non-terminal flight
    and spend recording requires `ACTIVE` or `PAUSED_PACING`, both rejecting a `COMPLETED` or
    `CANCELLED` flight with `ERR_FLIGHT_ALREADY_TERMINAL` — all 409."
    PRD §2.9: "The practical consequence worth internalising is that authentication precedes
    authorization, authorization precedes schema validation, schema validation precedes
    existence, existence precedes ownership and two-person rules, those precede uniqueness,
    uniqueness precedes the version guards, the version guards precede state-machine gating, and
    every domain-specific business rule — compliance, quotas, temporal windows, capacity, budget
    — is evaluated only after the target's state has been confirmed to permit the transition at
    all."

    Design: Difficulty/priority_pair_validation_conflict/flight_state_error_outranks_compliance_gate_on_activate
    """
    _, _, _, _, cancelled, _ = _cancelled_and_reserved_flights_on_a_flagged_posting(api)

    refused = api.activate_media_flight(cancelled["id"], media_buyer_headers())

    validate_error(refused, ApiErrorId.FLIGHT_NOT_RESERVED, 409)
    unchanged = fx.read_flight(api, cancelled["id"])
    assert unchanged["state"] == "CANCELLED", unchanged
    assert unchanged["activated_at"] is None, unchanged


def test_a_reserved_flight_on_a_flagged_posting_reports_the_clearance_gate(api):
    """PRD §2.9: "25. `compliance_status` must be `CLEARED` before publishing a posting, before
    activating or resuming a flight pointing at it, and before an application on it is submitted,
    else `ERR_POSTING_COMPLIANCE_NOT_CLEARED` (409)."
    PRD §2.9: "31. A posting's `content_status` must be `PUBLISHED` before a flight on it is
    activated or resumed and before an application on it is submitted, else
    `ERR_POSTING_NOT_PUBLISHED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/flight_state_error_outranks_compliance_gate_on_activate
    """
    program, _, channel, _, _, reserved = _cancelled_and_reserved_flights_on_a_flagged_posting(api)

    refused = api.activate_media_flight(reserved["id"], media_buyer_headers())

    validate_error(refused, ApiErrorId.POSTING_COMPLIANCE_NOT_CLEARED, 409)
    unchanged = fx.read_flight(api, reserved["id"])
    assert unchanged["state"] == "RESERVED", unchanged
    a.assert_cents(unchanged["reserved_cents"], 360500, "reserved_cents")
    assert fx.read_channel(api, channel["id"])["active_flight_count"] == 0
    a.assert_cents(
        fx.read_program(api, program["id"])["committed_budget_cents"],
        360500,
        "committed_budget_cents",
    )

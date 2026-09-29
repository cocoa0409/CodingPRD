"""Closed and half-open time intervals around contacts and policy periods.

Two intervals are exercised at their edges: the closed cooldown buffer that
separates two attempts to the same consumer, and the half-open effective period
that keeps two calling window policies for one state apart.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Tuple

from test_helpers import (
    ApiErrorId,
    AttemptOutcome,
    Channel,
    ComplianceWorld,
    PolicyStatus,
    RecordingConsentRegime,
    STATE_CA,
    assert_attempt_budget_conserved,
    assert_created,
    assert_error,
    assert_fields_equal,
    assert_ok,
    assert_page,
    assert_status,
    assert_total_count,
    factories,
)

# The first attempt goes out when the recipient's local clock reads 08:00,
# exactly the start of the permitted window.
_WINDOW_START_CLOCK = "2026-08-03T15:00:00Z"
_COOLDOWN_BOUNDARY_CLOCK = "2026-08-03T15:30:00Z"
_ONE_SECOND_PAST_BOUNDARY_CLOCK = "2026-08-03T15:30:01Z"

# The published CA period runs from 2026-07-01 up to 2027-01-01.
_POLICY_CLOCK = "2026-08-03T00:00:00Z"
_INCUMBENT_FROM = "2026-07-01T00:00:00Z"
_INCUMBENT_TO = "2027-01-01T00:00:00Z"
_ONE_SECOND_BEFORE_INCUMBENT_TO = "2026-12-31T23:59:59Z"
_LATER_TO = "2027-07-01T00:00:00Z"


def _instant(value: str) -> datetime:
    """Parse a UTC timestamp so two instants compare independently of formatting."""
    assert isinstance(value, str) and value, (
        "expected an ISO 8601 timestamp, got %r" % (value,)
    )
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_instant_equals(actual: str, expected: str) -> None:
    """A derived timestamp lands on exactly the expected instant."""
    assert _instant(actual) == _instant(expected), "expected %s, got %s" % (
        expected,
        actual,
    )


def _running_campaign_with_one_attempt(
    world: ComplianceWorld,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Place the first attempt of the day at the recipient's window start."""
    built = world.build(clock=_WINDOW_START_CLOCK)
    attempt = world.create_attempt(
        built["campaign"]["id"], built["contact"]["id"], channel=Channel.VOICE
    )
    return built, attempt


class TestContactCooldownBuffer:
    """The gap the server insists on between two attempts to one consumer."""

    def test_01_second_attempt_exactly_thirty_minutes_later_is_refused(
        self, world: ComplianceWorld
    ):
        """The instant recorded as cooldown_until is itself still inside the guard.

        PRD §3.8: "If such an attempt exists and the current clock instant falls at or before 30
        minutes after its `requested_at`, the new attempt is refused with
        `ERR_CONTACT_COOLDOWN_ACTIVE`."
        PRD §3.8: "The guard interval is closed at both ends: an attempt exactly 30 minutes after the
        previous one is still refused, one second later is permitted."

        Design: Difficulty/resource_temporal_overlap/contact_cooldown_closed_buffer_rejects_exact_boundary
        """
        built, first = _running_campaign_with_one_attempt(world)
        assert_fields_equal(
            first,
            recipient_local_minutes=480,
            effective_window_start_minutes=480,
        )
        _assert_instant_equals(first["cooldown_until"], _COOLDOWN_BOUNDARY_CLOCK)

        world.set_clock(_COOLDOWN_BOUNDARY_CLOCK)
        response = world.api.create_contact_attempt(
            factories.contact_attempt_payload(
                campaign_id=built["campaign"]["id"],
                contact_id=built["contact"]["id"],
                channel=Channel.VOICE,
            ),
            world.operator,
        )
        assert_error(response, ApiErrorId.CONTACT_COOLDOWN_ACTIVE)

        contact = world.read_contact(built["contact"]["id"])
        assert_fields_equal(contact, attempts_charged=1, attempt_budget_remaining=2)
        assert_attempt_budget_conserved(contact)

    def test_02_second_attempt_one_second_after_the_buffer_is_admitted(
        self, world: ComplianceWorld
    ):
        """One second past the guard the same consumer may be dialled again.

        PRD §3.8: "The guard interval is closed at both ends: an attempt exactly 30 minutes after the
        previous one is still refused, one second later is permitted."
        PRD §3.8: "It records the `consent_record_id` and `calling_window_policy_id` the server
        selected, the four window and local-time fields already described, `cooldown_until` set to 30
        minutes after the current clock instant — the closed interval from `requested_at` through
        `cooldown_until` is what blocks the next attempt to this consumer — and `max_lines_snapshot`,
        the line ceiling as computed from state persisted before this attempt."

        Design: Difficulty/resource_temporal_overlap/contact_cooldown_closed_buffer_rejects_exact_boundary
        """
        built, first = _running_campaign_with_one_attempt(world)
        _assert_instant_equals(first["cooldown_until"], _COOLDOWN_BOUNDARY_CLOCK)

        world.set_clock(_ONE_SECOND_PAST_BOUNDARY_CLOCK)
        second = assert_created(
            world.api.create_contact_attempt(
                factories.contact_attempt_payload(
                    campaign_id=built["campaign"]["id"],
                    contact_id=built["contact"]["id"],
                    channel=Channel.VOICE,
                ),
                world.operator,
            )
        )
        assert_fields_equal(second, outcome=AttemptOutcome.PENDING)
        _assert_instant_equals(second["cooldown_until"], "2026-08-03T16:00:01Z")

        contact = world.read_contact(built["contact"]["id"])
        assert_fields_equal(contact, attempts_charged=2, attempt_budget_remaining=1)
        assert_attempt_budget_conserved(contact)


class TestCallingWindowPolicyPeriods:
    """Two periods for one state may touch, but they may not share an instant."""

    def test_03_period_overlapping_the_incumbent_period_is_rejected(
        self, world: ComplianceWorld
    ):
        """A second CA period that starts inside the standing one collides with it.

        PRD §3.5: "Periods for one state may not collide: the new policy's effective period must not
        overlap that of an `ACTIVE` policy for the same `state_code` unless `supersedes_policy_id`
        names precisely that policy, and `window_start_local` must be strictly before
        `window_end_local`; a violation of either is refused with `ERR_POLICY_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/calling_window_policy_periods_reject_overlap_but_allow_adjacency
        """
        world.set_clock(_POLICY_CLOCK)
        incumbent = world.create_ca_policy()

        response = world.api.create_calling_window_policy(
            factories.calling_window_policy_payload(
                state_code=STATE_CA,
                window_start_local="09:00",
                window_end_local="20:00",
                effective_from="2026-09-01T00:00:00Z",
                effective_to="2027-06-01T00:00:00Z",
            ),
            world.admin,
        )
        assert_error(response, ApiErrorId.POLICY_PERIOD_OVERLAP)

        standing = assert_ok(
            world.api.get_calling_window_policy(incumbent["id"], world.officer)
        )
        assert_status(standing, PolicyStatus.ACTIVE)
        _assert_instant_equals(standing["effective_to"], _INCUMBENT_TO)

    def test_04_period_starting_one_second_before_the_incumbent_ends_is_rejected(
        self, world: ComplianceWorld
    ):
        """Sharing a single second with the standing period is still an overlap.

        PRD §3.5: "Periods for one state may not collide: the new policy's effective period must not
        overlap that of an `ACTIVE` policy for the same `state_code` unless `supersedes_policy_id`
        names precisely that policy, and `window_start_local` must be strictly before
        `window_end_local`; a violation of either is refused with `ERR_POLICY_PERIOD_OVERLAP`."
        PRD §3.5: "The candidates are the policies whose `state_code` equals the relevant state, whose
        `status` is `ACTIVE`, and whose effective period contains the current clock instant on a
        half-open basis — `effective_from` is inside the period, `effective_to` is outside it."

        Design: Difficulty/resource_temporal_overlap/calling_window_policy_periods_reject_overlap_but_allow_adjacency
        """
        world.set_clock(_POLICY_CLOCK)
        world.create_ca_policy()

        response = world.api.create_calling_window_policy(
            factories.calling_window_policy_payload(
                state_code=STATE_CA,
                window_start_local="09:00",
                window_end_local="20:00",
                effective_from=_ONE_SECOND_BEFORE_INCUMBENT_TO,
                effective_to=_LATER_TO,
            ),
            world.admin,
        )
        assert_error(response, ApiErrorId.POLICY_PERIOD_OVERLAP)

    def test_05_period_starting_exactly_when_the_incumbent_ends_is_published(
        self, world: ComplianceWorld
    ):
        """Because periods are half-open, zero-gap adjacency is not an overlap.

        PRD §3.5: "The candidates are the policies whose `state_code` equals the relevant state, whose
        `status` is `ACTIVE`, and whose effective period contains the current clock instant on a
        half-open basis — `effective_from` is inside the period, `effective_to` is outside it."
        PRD §3.5: "On publication the server derives `window_start_minutes` and `window_end_minutes`
        by parsing the two `HH:MM` inputs into minutes after local midnight, sets `status` to `ACTIVE`
        and `emergency_status` to `NONE`, leaves `emergency_declared_at` and `emergency_note` null,
        and returns a 201."

        Design: Difficulty/resource_temporal_overlap/calling_window_policy_periods_reject_overlap_but_allow_adjacency
        """
        world.set_clock(_POLICY_CLOCK)
        incumbent = world.create_ca_policy()

        successor = assert_created(
            world.api.create_calling_window_policy(
                factories.calling_window_policy_payload(
                    state_code=STATE_CA,
                    window_start_local="09:00",
                    window_end_local="20:00",
                    effective_from=_INCUMBENT_TO,
                    effective_to=_LATER_TO,
                ),
                world.admin,
            )
        )
        assert_status(successor, PolicyStatus.ACTIVE)
        _assert_instant_equals(successor["effective_from"], _INCUMBENT_TO)

        standing = assert_ok(
            world.api.get_calling_window_policy(incumbent["id"], world.officer)
        )
        assert_status(standing, PolicyStatus.ACTIVE)
        _assert_instant_equals(standing["effective_to"], _INCUMBENT_TO)

    def test_06_naming_the_incumbent_truncates_it_into_adjacency(
        self, world: ComplianceWorld
    ):
        """An overlapping period is admitted when it supersedes the policy it overlaps.

        PRD §3.5: "When `supersedes_policy_id` is supplied, the named policy must be `ACTIVE`, must
        govern the same `state_code`, and the new policy's `effective_from` must fall at or after the
        named policy's `effective_from`; the named policy then moves `ACTIVE → SUPERSEDED` and its
        `effective_to` is truncated to the new policy's `effective_from`, so that the two periods sit
        exactly adjacent with no gap and no overlap."

        Design: Difficulty/resource_temporal_overlap/calling_window_policy_periods_reject_overlap_but_allow_adjacency
        """
        world.set_clock(_POLICY_CLOCK)
        incumbent = world.create_ca_policy()

        adjacent = world.create_policy(
            state_code=STATE_CA,
            window_start_local="09:00",
            window_end_local="20:00",
            effective_from=_INCUMBENT_TO,
            effective_to=_LATER_TO,
        )

        successor = assert_created(
            world.api.create_calling_window_policy(
                factories.calling_window_policy_payload(
                    state_code=STATE_CA,
                    window_start_local="09:00",
                    window_end_local="20:00",
                    recording_consent_regime=RecordingConsentRegime.ALL_PARTY,
                    effective_from="2026-09-01T00:00:00Z",
                    effective_to=_INCUMBENT_TO,
                    supersedes_policy_id=incumbent["id"],
                ),
                world.admin,
            )
        )
        assert_status(successor, PolicyStatus.ACTIVE)
        assert_fields_equal(
            successor, window_start_minutes=540, window_end_minutes=1200
        )

        superseded = assert_ok(
            world.api.get_calling_window_policy(incumbent["id"], world.officer)
        )
        assert_status(superseded, PolicyStatus.SUPERSEDED)
        _assert_instant_equals(superseded["effective_to"], "2026-09-01T00:00:00Z")

        rows, meta = assert_page(
            world.api.list_calling_window_policies(
                world.officer,
                params={"state_code": STATE_CA, "status": PolicyStatus.ACTIVE},
            )
        )
        assert_total_count(meta, 2)
        assert {row["id"] for row in rows} == {adjacent["id"], successor["id"]}, (
            "the two surviving CA periods should be the adjacent and superseding ones"
        )

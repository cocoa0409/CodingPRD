"""Two interval rules on two resources, with opposite semantics.

A partition's ceremony windows are closed intervals that must stay a positive
hour apart, so touching is a conflict; a profile's CRL windows are half-open
intervals that must overlap, so a gap is the conflict.
"""

from test_helpers import (
    CEREMONY_ABORTED,
    CEREMONY_SCHEDULED,
    ERR_CEREMONY_WINDOW_CONFLICT,
    ERR_CRL_COVERAGE_GAP,
    ERR_CRL_VALIDITY_TOO_LONG,
    ERR_CRL_WINDOW_NOT_ADVANCING,
    ERR_INVALID_CRL_WINDOW,
    PARTITION_OPERATIONAL,
    abort_payload,
    assert_append_only_identity,
    assert_counters,
    assert_instant_equals,
    ceremony_payload,
    create_partition,
    create_profile,
    crl_publication_payload,
    get_success_data,
    profile_version,
    read_ceremony,
    read_partition,
    read_profile,
    schedule_ceremony,
    users,
    validate_error,
)


def _book(client, partition_id, window_start, window_end):
    """One scheduling attempt, returned raw so the caller can judge it."""
    return client.schedule_ceremony(
        partition_id,
        ceremony_payload(window_start, window_end, 60),
        users.ISSUANCE_OPERATOR,
    )


def _accepted(client, partition_id, window_start, window_end):
    ceremony = get_success_data(
        _book(client, partition_id, window_start, window_end), 201
    )
    assert ceremony["state"] == CEREMONY_SCHEDULED, (
        f"a new ceremony starts SCHEDULED, found {ceremony['state']!r}"
    )
    assert_instant_equals(ceremony["window_start"], window_start, "window_start")
    assert_instant_equals(ceremony["window_end"], window_end, "window_end")
    return ceremony


def _publish_attempt(client, profile_id, this_update, next_update, version):
    return client.publish_crl(
        profile_id,
        crl_publication_payload(this_update, next_update, version),
        users.REVOCATION_OFFICER,
    )


class TestCeremonyWindowsAreClosedIntervalsPlusABuffer:
    def test_a_exactly_sixty_minutes_of_clearance_is_still_a_conflict(self, client):
        """One second decides it, on both sides of the existing window.

        PRD 3.6: "The occupation rule treats the windows as closed intervals
        inflated by that buffer: the proposed ceremony conflicts with an existing
        one whenever the proposed `window_start` is at or before the existing
        `window_end` plus 60 minutes **and** the existing `window_start` is at or
        before the proposed `window_end` plus 60 minutes."
        PRD 3.6: "Because both comparisons are inclusive, a gap of exactly 60
        minutes between two windows still conflicts, while a gap of 60 minutes
        and one second does not; adjacency, likewise, is a conflict."

        Design: Difficulty/resource_temporal_overlap/ceremony_windows_are_closed_intervals_with_a_sixty_minute_buffer
        """
        partition = create_partition(client)
        booked = _accepted(
            client, partition["id"], "2026-08-01T10:00:00Z", "2026-08-01T12:00:00Z"
        )

        # Later side: the existing window ends at 12:00, so 13:00 is exactly the
        # buffer away and loses, while 13:00:01 clears it.
        validate_error(
            _book(client, partition["id"], "2026-08-01T13:00:00Z", "2026-08-01T14:00:00Z"),
            ERR_CEREMONY_WINDOW_CONFLICT,
        )
        later = _accepted(
            client, partition["id"], "2026-08-01T13:00:01Z", "2026-08-01T14:00:00Z"
        )

        # Earlier side: the existing window starts at 10:00, so a proposal
        # ending at 09:00 is exactly the buffer away and loses too.
        validate_error(
            _book(client, partition["id"], "2026-08-01T08:00:00Z", "2026-08-01T09:00:00Z"),
            ERR_CEREMONY_WINDOW_CONFLICT,
        )
        earlier = _accepted(
            client, partition["id"], "2026-08-01T08:00:00Z", "2026-08-01T08:59:59Z"
        )

        assert len({booked["id"], later["id"], earlier["id"]}) == 3, (
            "the two accepted bookings must be distinct new ceremonies"
        )
        settled = read_partition(client, partition["id"])
        assert settled["state"] == PARTITION_OPERATIONAL, (
            "scheduling never changes the partition's state"
        )
        assert_counters(settled, attested_ceremony_count=0)
        for ceremony in (booked, later, earlier):
            assert_counters(
                read_ceremony(client, ceremony["id"]),
                witness_count=0,
                issued_certificate_count=0,
                state=CEREMONY_SCHEDULED,
            )
            assert read_ceremony(client, ceremony["id"])["witness_user_ids"] == [], (
                "a scheduled ceremony has no witnesses yet"
            )

    def test_b_an_aborted_ceremony_releases_its_window_immediately(self, client):
        """A window nested inside a live ceremony is refused, then granted.

        PRD 3.6: "Only ceremonies in `SCHEDULED`, `WITNESSED` or `ATTESTED`
        block — an `ABORTED` or `ATTESTATION_REVOKED` ceremony releases its
        window and never blocks again."
        PRD 3.6: "The abort moves the ceremony to the terminal `ABORTED` state,
        increments its `version`, and frees its occupation window so a
        replacement ceremony may be scheduled over it."

        Design: Difficulty/resource_temporal_overlap/ceremony_windows_are_closed_intervals_with_a_sixty_minute_buffer
        """
        partition = create_partition(client)
        first = schedule_ceremony(
            client,
            partition["id"],
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-01T02:00:00Z",
        )

        # Touching the end of a live window is a conflict, and so is nesting.
        validate_error(
            _book(client, partition["id"], "2026-08-01T02:00:00Z", "2026-08-01T03:00:00Z"),
            ERR_CEREMONY_WINDOW_CONFLICT,
        )
        validate_error(
            _book(client, partition["id"], "2026-08-01T00:30:00Z", "2026-08-01T01:00:00Z"),
            ERR_CEREMONY_WINDOW_CONFLICT,
        )

        aborted = get_success_data(
            client.abort_ceremony(
                first["id"], abort_payload(), users.ISSUANCE_OPERATOR
            )
        )
        assert aborted["state"] == CEREMONY_ABORTED, (
            f"the abort is terminal, found state {aborted['state']!r}"
        )
        assert aborted["version"] > first["version"], (
            "aborting increments the ceremony's version"
        )
        assert read_partition(client, partition["id"])["state"] == (
            PARTITION_OPERATIONAL
        ), "an abort is not a quarantine"

        replacement = _accepted(
            client, partition["id"], "2026-08-01T00:30:00Z", "2026-08-01T01:00:00Z"
        )

        # The replacement occupies in its turn: 02:00 is exactly 60 minutes
        # after its 01:00 end, so the buffer rejects it all over again.
        validate_error(
            _book(client, partition["id"], "2026-08-01T02:00:00Z", "2026-08-01T03:00:00Z"),
            ERR_CEREMONY_WINDOW_CONFLICT,
        )
        _accepted(
            client, partition["id"], "2026-08-01T02:00:01Z", "2026-08-01T03:00:00Z"
        )
        assert_counters(
            read_ceremony(client, replacement["id"]), state=CEREMONY_SCHEDULED
        )
        assert_counters(
            read_partition(client, partition["id"]), attested_ceremony_count=0
        )


class TestCrlWindowsAreHalfOpenAndMustOverlap:
    def test_c_a_window_must_overlap_the_previous_one_and_still_advance(self, client):
        """Three ways to get the geometry wrong, then the one that is right.

        PRD 3.8: "Second, when the profile has published before, `this_update`
        must be at or before the previous list's `last_crl_next_update` minus 30
        minutes, so consecutive lists overlap by at least half an hour and status
        service never shows a coverage gap; an overlap of exactly 30 minutes is
        accepted while 29 minutes and 59 seconds is a violation reported as
        `ERR_CRL_COVERAGE_GAP`."
        PRD 3.8: "Third, again only when a previous list exists, `next_update`
        must be strictly after `last_crl_next_update`, so the series genuinely
        advances rather than nesting a new window inside the old one; a
        non-advancing window is `ERR_CRL_WINDOW_NOT_ADVANCING`."
        PRD 3.8: "Fourth, the span from `this_update` to `next_update` must be at
        most the profile's `max_crl_validity_hours` in hours, or
        `ERR_CRL_VALIDITY_TOO_LONG`."

        Design: Difficulty/resource_temporal_overlap/crl_series_windows_are_half_open_and_must_overlap
        """
        profile = create_profile(client)
        first = get_success_data(
            _publish_attempt(
                client,
                profile["id"],
                "2026-08-01T00:00:00Z",
                "2026-08-01T12:00:00Z",
                profile["version"],
            ),
            201,
        )
        assert first["crl_number"] == 1, (
            f"the first list of a profile is number 1, found {first['crl_number']}"
        )

        # One version read serves all three rejections: a refused publication
        # must not touch the profile.
        version = profile_version(client, profile["id"])

        nested = _publish_attempt(
            client,
            profile["id"],
            "2026-08-01T06:00:00Z",
            "2026-08-01T11:00:00Z",
            version,
        )
        validate_error(nested, ERR_CRL_WINDOW_NOT_ADVANCING)

        detached = _publish_attempt(
            client,
            profile["id"],
            "2026-08-01T13:00:00Z",
            "2026-08-02T01:00:00Z",
            version,
        )
        validate_error(detached, ERR_CRL_COVERAGE_GAP)

        too_long = _publish_attempt(
            client,
            profile["id"],
            "2026-08-01T11:00:00Z",
            "2026-08-02T12:00:00Z",
            version,
        )
        validate_error(too_long, ERR_CRL_VALIDITY_TOO_LONG)

        accepted = get_success_data(
            _publish_attempt(
                client,
                profile["id"],
                "2026-08-01T11:00:00Z",
                "2026-08-01T23:00:00Z",
                version,
            ),
            201,
        )
        assert accepted["crl_number"] == 2, (
            "the accepted list advances the series to 2, found "
            f"{accepted['crl_number']}"
        )
        assert_instant_equals(
            accepted["this_update"], "2026-08-01T11:00:00Z", "this_update"
        )
        assert_instant_equals(
            accepted["next_update"], "2026-08-01T23:00:00Z", "next_update"
        )

        settled = read_profile(client, profile["id"])
        assert_instant_equals(
            settled["last_crl_this_update"],
            "2026-08-01T11:00:00Z",
            "last_crl_this_update",
        )
        assert_instant_equals(
            settled["last_crl_next_update"],
            "2026-08-01T23:00:00Z",
            "last_crl_next_update",
        )
        assert_counters(settled, last_crl_number=2)

    def test_d_only_the_newest_publication_constrains_the_next_one(self, client):
        """A window legal against list one is illegal against list two.

        PRD 3.8: "A profile's very first publication is bound only by the
        non-degenerate-window rule and the maximum-span rule, since there is no
        predecessor to overlap."
        PRD 3.8: "First, `next_update` must be strictly after `this_update`, or
        `ERR_INVALID_CRL_WINDOW`."

        Design: Difficulty/resource_temporal_overlap/crl_series_windows_are_half_open_and_must_overlap
        """
        profile = create_profile(client)
        version = profile["version"]

        # With no predecessor the span rule still binds: 25 hours is too long.
        validate_error(
            _publish_attempt(
                client,
                profile["id"],
                "2026-08-01T00:00:00Z",
                "2026-08-02T01:00:00Z",
                version,
            ),
            ERR_CRL_VALIDITY_TOO_LONG,
        )
        # And so does the non-degenerate-window rule.
        validate_error(
            _publish_attempt(
                client,
                profile["id"],
                "2026-08-01T12:00:00Z",
                "2026-08-01T12:00:00Z",
                version,
            ),
            ERR_INVALID_CRL_WINDOW,
        )

        first = get_success_data(
            _publish_attempt(
                client,
                profile["id"],
                "2026-08-01T00:00:00Z",
                "2026-08-01T12:00:00Z",
                version,
            ),
            201,
        )
        assert_counters(first, crl_number=1, entry_count=0)
        assert first["revoked_serials"] == [], (
            "no certificate has been revoked, so the list is empty"
        )
        assert_append_only_identity(first)

        second = get_success_data(
            _publish_attempt(
                client,
                profile["id"],
                "2026-08-01T11:00:00Z",
                "2026-08-01T23:00:00Z",
                profile_version(client, profile["id"]),
            ),
            201,
        )
        assert_counters(second, crl_number=2)

        # [06:00, 12:30) would have been a perfectly legal successor to list
        # one, which ran to 12:00; against list two, which runs to 23:00, it no
        # longer advances the series.
        validate_error(
            _publish_attempt(
                client,
                profile["id"],
                "2026-08-01T06:00:00Z",
                "2026-08-01T12:30:00Z",
                profile_version(client, profile["id"]),
            ),
            ERR_CRL_WINDOW_NOT_ADVANCING,
        )

        # A 24-hour span is exactly at max_crl_validity_hours and is allowed.
        third = get_success_data(
            _publish_attempt(
                client,
                profile["id"],
                "2026-08-01T22:30:00Z",
                "2026-08-02T22:30:00Z",
                profile_version(client, profile["id"]),
            ),
            201,
        )
        assert_counters(third, crl_number=3, entry_count=0)
        settled = read_profile(client, profile["id"])
        assert_counters(settled, last_crl_number=3)
        assert_instant_equals(
            settled["last_crl_next_update"],
            "2026-08-02T22:30:00Z",
            "last_crl_next_update",
        )

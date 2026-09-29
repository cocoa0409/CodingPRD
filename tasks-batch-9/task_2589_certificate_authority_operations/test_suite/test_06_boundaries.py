"""Three inclusive boundaries, each probed one unit short and exactly on.

A deduplicated SCT count, minutes of overlap between two revocation-list
windows, and whole seconds against a disclosure deadline.
"""

from test_helpers import (
    COMM_INCIDENT_DISCLOSURE,
    CT_OUTCOME_ACCEPTED,
    CT_OUTCOME_REJECTED,
    ERR_CRL_COVERAGE_GAP,
    ERR_INSUFFICIENT_SCTS,
    ERR_STALE_PROFILE_VERSION,
    INCIDENT_DISCLOSED,
    INCIDENT_PROCEDURAL,
    LIFECYCLE_ISSUED,
    LIFECYCLE_PREISSUANCE,
    LOG_OPERATOR_CLOUDFLARE_NIMBUS,
    LOG_OPERATOR_GOOGLE_ARGON,
    REVOCATION_STATUS_NONE,
    ROOT_PROGRAM_APPLE,
    advance_clock,
    assert_append_only_identity,
    assert_certificate_dimensions,
    assert_counters,
    assert_instant_equals,
    build_environment,
    create_profile,
    create_subscriber,
    crl_publication_payload,
    ct_submission_payload,
    disclosure_payload,
    get_success_data,
    ids_of,
    issue_certificate,
    open_incident,
    profile_payload,
    profile_version,
    publish_crl,
    read_certificate,
    read_incident,
    read_profile,
    users,
    validate_error,
    validate_paginated,
)


def _submit(client, certificate_id, log_operator, outcome, rejection_reason=None):
    """Record one transparency-log submission against a certificate."""
    return get_success_data(
        client.submit_ct_log(
            certificate_id,
            ct_submission_payload(log_operator, outcome, rejection_reason),
            users.ISSUANCE_OPERATOR_9,
        ),
        201,
    )


def _publish_attempt(client, profile_id, this_update, next_update, version):
    """Try one revocation-list publication with an explicit version guard."""
    return client.publish_crl(
        profile_id,
        crl_publication_payload(this_update, next_update, version),
        users.REVOCATION_OFFICER,
    )


class TestSctCountAtTheThreshold:
    def test_a_only_a_second_distinct_accepting_log_reaches_the_threshold(self, client):
        """Duplicates and rejections leave the count one short of the requirement.

        PRD 3.7: "`counted_toward_sct` on a new submission is true only when its
        `outcome` is `ACCEPTED` and no earlier submission for the same
        certificate and the same `log_operator` was already `ACCEPTED`."
        PRD 3.7: "Finally `sct_count` must be at least the profile's
        `required_sct_count`; the comparison is inclusive, so a count exactly
        equal to the requirement passes, while anything lower is refused with
        `ERR_INSUFFICIENT_SCTS`."

        Design: Difficulty/boundary_precision_check/sct_count_exactly_equal_to_required_threshold_permits_activation
        """
        environment = build_environment(
            client, profile_payload=profile_payload(required_sct_count=2)
        )
        certificate = issue_certificate(client, environment)
        assert_counters(certificate, sct_count=0)

        first = _submit(
            client, certificate["id"], LOG_OPERATOR_GOOGLE_ARGON, CT_OUTCOME_ACCEPTED
        )
        assert first["counted_toward_sct"] is True, (
            "the first acceptance from a log counts"
        )
        duplicate = _submit(
            client, certificate["id"], LOG_OPERATOR_GOOGLE_ARGON, CT_OUTCOME_ACCEPTED
        )
        assert duplicate["counted_toward_sct"] is False, (
            "a second acceptance from a log already represented raises nothing"
        )
        rejected = _submit(
            client,
            certificate["id"],
            LOG_OPERATOR_CLOUDFLARE_NIMBUS,
            CT_OUTCOME_REJECTED,
            "unrecognised issuing root",
        )
        assert rejected["counted_toward_sct"] is False, (
            "a REJECTED submission neither raises nor lowers the count"
        )
        assert_counters(read_certificate(client, certificate["id"]), sct_count=1)

        refused = client.activate_certificate(
            certificate["id"], users.ISSUANCE_OPERATOR_9
        )
        validate_error(refused, ERR_INSUFFICIENT_SCTS, 409)
        assert_certificate_dimensions(
            read_certificate(client, certificate["id"]),
            LIFECYCLE_PREISSUANCE,
            REVOCATION_STATUS_NONE,
        )

        crossing = _submit(
            client,
            certificate["id"],
            LOG_OPERATOR_CLOUDFLARE_NIMBUS,
            CT_OUTCOME_ACCEPTED,
        )
        assert crossing["counted_toward_sct"] is True, (
            "a first acceptance from a second log crosses the boundary"
        )
        assert_counters(read_certificate(client, certificate["id"]), sct_count=2)

        activated = get_success_data(
            client.activate_certificate(certificate["id"], users.ISSUANCE_OPERATOR_9)
        )
        assert activated["lifecycle_status"] == LIFECYCLE_ISSUED, (
            "a count exactly equal to the requirement passes"
        )

        rows, meta = validate_paginated(
            client.list_ct_submissions(
                certificate["id"],
                users.ISSUANCE_OPERATOR,
                {"outcome": CT_OUTCOME_ACCEPTED},
            )
        )
        assert meta["total_count"] == 3, (
            f"three accepted rows were recorded, found {meta['total_count']}"
        )
        assert_counters(read_certificate(client, certificate["id"]), sct_count=2)
        assert len(ids_of(rows)) == len(set(ids_of(rows))), (
            "each submission is its own row"
        )

    def test_b_a_single_required_sct_is_refused_at_zero_and_granted_at_one(
        self, client, dv_environment
    ):
        """The same inclusive comparison at the smallest possible requirement.

        PRD 3.7: "the comparison is inclusive, so a count exactly equal to the
        requirement passes, while anything lower is refused with
        `ERR_INSUFFICIENT_SCTS`."
        PRD 3.7: "the record is immutable thereafter — it carries `id` and
        `created_at` and no `updated_at` or `version` of its own."

        Design: Difficulty/boundary_precision_check/sct_count_exactly_equal_to_required_threshold_permits_activation
        """
        certificate = issue_certificate(client, dv_environment)
        empty = client.activate_certificate(
            certificate["id"], users.ISSUANCE_OPERATOR_9
        )
        validate_error(empty, ERR_INSUFFICIENT_SCTS, 409)

        submission = _submit(
            client, certificate["id"], LOG_OPERATOR_GOOGLE_ARGON, CT_OUTCOME_ACCEPTED
        )
        assert_append_only_identity(submission)
        assert_instant_equals(
            submission["sct_timestamp"], "2026-08-01T00:30:00Z", "sct_timestamp"
        )
        assert submission["certificate_id"] == certificate["id"]

        activated = get_success_data(
            client.activate_certificate(certificate["id"], users.ISSUANCE_OPERATOR_9)
        )
        assert_certificate_dimensions(
            activated, LIFECYCLE_ISSUED, REVOCATION_STATUS_NONE
        )
        assert_counters(activated, sct_count=1)


class TestCrlOverlapAtThirtyMinutes:
    def test_a_one_second_short_of_the_overlap_is_a_gap_and_exactly_thirty_is_not(
        self, client
    ):
        """The mandatory overlap is inclusive at exactly half an hour.

        PRD 3.8: "Second, when the profile has published before, `this_update`
        must be at or before the previous list's `last_crl_next_update` minus 30
        minutes, so consecutive lists overlap by at least half an hour and status
        service never shows a coverage gap; an overlap of exactly 30 minutes is
        accepted while 29 minutes and 59 seconds is a violation reported as
        `ERR_CRL_COVERAGE_GAP`."
        PRD 3.8: "A publication with an empty drain set is perfectly legal:
        `entry_count` is 0, `revoked_serials` is an empty array, and `crl_number`
        still advances by one."

        Design: Difficulty/boundary_precision_check/crl_overlap_exactly_thirty_minutes_is_accepted
        """
        profile = create_profile(client)
        first = publish_crl(
            client, profile["id"], "2026-08-01T00:00:00Z", "2026-08-01T12:00:00Z"
        )
        assert_counters(first, crl_number=1, entry_count=0)
        assert first["revoked_serials"] == [], (
            f"revoked_serials is {first['revoked_serials']!r}, expected an empty array"
        )
        assert_append_only_identity(first)

        captured = profile_version(client, profile["id"])
        short = _publish_attempt(
            client,
            profile["id"],
            "2026-08-01T11:30:01Z",
            "2026-08-01T23:00:00Z",
            captured,
        )
        validate_error(short, ERR_CRL_COVERAGE_GAP, 409)

        # The refused attempt changed nothing, so the same guard value still holds.
        exact = get_success_data(
            _publish_attempt(
                client,
                profile["id"],
                "2026-08-01T11:30:00Z",
                "2026-08-01T23:30:00Z",
                captured,
            ),
            201,
        )
        assert_counters(exact, crl_number=2, entry_count=0)

        reloaded = read_profile(client, profile["id"])
        assert_counters(
            reloaded,
            last_crl_number=2,
            total_crl_entries_published=0,
            pending_crl_entry_count=0,
        )
        assert_instant_equals(
            reloaded["last_crl_this_update"],
            "2026-08-01T11:30:00Z",
            "last_crl_this_update",
        )
        assert_instant_equals(
            reloaded["last_crl_next_update"],
            "2026-08-01T23:30:00Z",
            "last_crl_next_update",
        )

    def test_b_the_boundary_moves_with_the_newest_published_window(self, client):
        """Each list is measured against its immediate predecessor, not the first.

        PRD 3.8: "Third, again only when a previous list exists, `next_update`
        must be strictly after `last_crl_next_update`, so the series genuinely
        advances rather than nesting a new window inside the old one"
        PRD 2.5: "A mismatch against the profile's current `version` is rejected
        with `ERR_STALE_PROFILE_VERSION` (HTTP 412)."

        Design: Difficulty/boundary_precision_check/crl_overlap_exactly_thirty_minutes_is_accepted
        """
        profile = create_profile(client)
        publish_crl(
            client, profile["id"], "2026-08-01T00:00:00Z", "2026-08-01T12:00:00Z"
        )
        stale = profile_version(client, profile["id"])
        publish_crl(
            client, profile["id"], "2026-08-01T11:30:00Z", "2026-08-01T23:30:00Z"
        )

        with_stale_guard = _publish_attempt(
            client,
            profile["id"],
            "2026-08-01T23:00:00Z",
            "2026-08-02T11:00:00Z",
            stale,
        )
        validate_error(with_stale_guard, ERR_STALE_PROFILE_VERSION, 412)

        current = profile_version(client, profile["id"])
        short = _publish_attempt(
            client,
            profile["id"],
            "2026-08-01T23:00:01Z",
            "2026-08-02T11:00:00Z",
            current,
        )
        validate_error(short, ERR_CRL_COVERAGE_GAP, 409)

        third = get_success_data(
            _publish_attempt(
                client,
                profile["id"],
                "2026-08-01T23:00:00Z",
                "2026-08-02T11:00:00Z",
                current,
            ),
            201,
        )
        assert_counters(third, crl_number=3, entry_count=0)
        reloaded = read_profile(client, profile["id"])
        assert_counters(reloaded, last_crl_number=3)
        assert_instant_equals(
            reloaded["last_crl_next_update"],
            "2026-08-02T11:00:00Z",
            "last_crl_next_update",
        )


def _disclosure_communication(client, incident_id):
    """The single INCIDENT_DISCLOSURE record filed for an incident."""
    rows, _meta = validate_paginated(
        client.list_incident_communications(
            incident_id, users.COMPLIANCE_AUDITOR, {"kind": COMM_INCIDENT_DISCLOSURE}
        )
    )
    assert len(rows) == 1, (
        f"exactly one disclosure communication is expected, found {len(rows)}"
    )
    return rows[0]


class TestDisclosureExactlyAtTheDeadline:
    def test_a_the_deadline_instant_is_on_time_and_one_second_later_is_not(
        self, client
    ):
        """Two conventions meet: a strict sweep and an inclusive flag.

        PRD 3.9: "an `OPEN` incident gets `disclosure_breached` set to true only
        when the new clock is strictly after `disclosure_due_at`, so an advance
        landing exactly on `disclosure_due_at` leaves the flag false."
        PRD 3.9: "`within_deadline` true when `sent_at` is at or before
        `disclosure_due_at` — a disclosure landing exactly on the deadline
        instant is on time."

        Design: Difficulty/boundary_precision_check/disclosure_exactly_at_deadline_is_still_on_time
        """
        profile = create_profile(client)
        subscriber = create_subscriber(client)
        first = open_incident(
            client,
            profile["id"],
            category=INCIDENT_PROCEDURAL,
            scope_issued_from="2026-07-01T00:00:00Z",
            scope_issued_to="2026-07-31T00:00:00Z",
            subscriber_id=subscriber["id"],
            title="first incident, disclosed exactly on the deadline",
        )
        second = open_incident(
            client,
            profile["id"],
            category=INCIDENT_PROCEDURAL,
            scope_issued_from="2026-07-01T00:00:00Z",
            scope_issued_to="2026-07-31T00:00:00Z",
            subscriber_id=subscriber["id"],
            title="second incident, disclosed one second late",
        )
        for incident in (first, second):
            assert_instant_equals(
                incident["discovered_at"], "2026-08-01T00:00:00Z", "discovered_at"
            )
            assert_instant_equals(
                incident["disclosure_due_at"],
                "2026-08-02T00:00:00Z",
                "disclosure_due_at",
            )

        advance_clock(client, "2026-08-02T00:00:00Z")
        assert read_incident(client, first["id"])["disclosure_breached"] is False, (
            "landing exactly on the deadline is not strictly after it"
        )
        assert read_incident(client, second["id"])["disclosure_breached"] is False

        get_success_data(
            client.disclose_incident(
                first["id"],
                disclosure_payload(
                    ROOT_PROGRAM_APPLE, "disclosed at the deadline instant"
                ),
                users.COMPLIANCE_AUDITOR,
            )
        )
        on_time = _disclosure_communication(client, first["id"])
        assert on_time["within_deadline"] is True, (
            "a disclosure sent at the deadline instant is on time"
        )
        assert on_time["incident_id"] == first["id"]
        assert on_time["audit_id"] is None
        assert on_time["sent_by_user_id"] == users.USER_COMPLIANCE_AUDITOR
        assert_instant_equals(on_time["sent_at"], "2026-08-02T00:00:00Z", "sent_at")

        advance_clock(client, "2026-08-02T00:00:01Z")
        assert read_incident(client, second["id"])["disclosure_breached"] is True, (
            "one second past the deadline is strictly after it"
        )
        assert read_incident(client, first["id"])["disclosure_breached"] is False, (
            "an incident already DISCLOSED is out of the sweep's reach"
        )

        get_success_data(
            client.disclose_incident(
                second["id"],
                disclosure_payload(
                    ROOT_PROGRAM_APPLE, "disclosed one second after the deadline"
                ),
                users.COMPLIANCE_AUDITOR,
            )
        )
        late = _disclosure_communication(client, second["id"])
        assert late["within_deadline"] is False, (
            "a disclosure one second past the deadline is late"
        )

        for incident in (first, second):
            assert read_incident(client, incident["id"])["state"] == INCIDENT_DISCLOSED

        rows, meta = validate_paginated(
            client.list_incidents(
                users.COMPLIANCE_AUDITOR, {"disclosure_breached": "true"}
            )
        )
        assert ids_of(rows) == [second["id"]], (
            f"only the late incident is breached, found {ids_of(rows)}"
        )
        assert meta["total_count"] == 1

    def test_b_the_flag_is_never_set_on_an_incident_disclosed_in_time(self, client):
        """Sweep three only ever touches an incident still OPEN.

        PRD 3.9: "Once set, `disclosure_breached` is never cleared, not even by a
        later disclosure."
        PRD 3.9: "Creation stamps `discovered_at` with the logical clock and sets
        `disclosure_due_at` to exactly 24 hours later, the root program
        disclosure deadline."

        Design: Difficulty/boundary_precision_check/disclosure_exactly_at_deadline_is_still_on_time
        """
        profile = create_profile(client)
        subscriber = create_subscriber(client)
        incident = open_incident(
            client,
            profile["id"],
            category=INCIDENT_PROCEDURAL,
            scope_issued_from="2026-07-01T00:00:00Z",
            scope_issued_to="2026-07-31T00:00:00Z",
            subscriber_id=subscriber["id"],
        )

        advance_clock(client, "2026-08-01T12:00:00Z")
        get_success_data(
            client.disclose_incident(
                incident["id"],
                disclosure_payload(ROOT_PROGRAM_APPLE),
                users.COMPLIANCE_AUDITOR,
            )
        )
        communication = _disclosure_communication(client, incident["id"])
        assert communication["within_deadline"] is True, (
            "half a day before the deadline is comfortably on time"
        )
        assert_instant_equals(
            communication["sent_at"], "2026-08-01T12:00:00Z", "sent_at"
        )

        advance_clock(client, "2026-08-05T00:00:00Z")
        settled = read_incident(client, incident["id"])
        assert settled["disclosure_breached"] is False, (
            "a disclosed incident can never acquire a breach flag afterwards"
        )
        assert settled["state"] == INCIDENT_DISCLOSED
        assert_instant_equals(
            settled["disclosed_at"], "2026-08-01T12:00:00Z", "disclosed_at"
        )

        rows, _meta = validate_paginated(
            client.list_incidents(
                users.COMPLIANCE_AUDITOR, {"disclosure_breached": "false"}
            )
        )
        assert ids_of(rows) == [incident["id"]], (
            f"the unbreached incident is the only row, found {ids_of(rows)}"
        )

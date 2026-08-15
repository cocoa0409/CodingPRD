"""Scheduling windows (coverage, on-call) and delegation grants."""
from test_helpers import (
    ApiErrorId,
    Scenario,
    assert_delegation_grant,
    assert_same_instant,
    create_coverage_window_payload,
    create_delegation_grant_payload,
    create_on_call_shift_payload,
    staff_headers,
    validate_error,
    validate_success,
)


class TestCoverageWindowOverlap:
    def test_coverage_window_adjacent_accepted(self, api, practice_admin_headers):
        """PRD §2.9: "Two coverage windows for the same `staff_id` may not
        intersect, but adjacency is allowed: a new window whose `start_utc`
        equals an existing window's `end_utc` (or whose `end_utc` equals an
        existing window's `start_utc`) does not conflict; a genuine intersection
        is rejected with `ERR_COVERAGE_WINDOW_OVERLAP`."

        The existing window is [09:00, 12:00); a new window starting exactly at
        12:00 must be accepted under half-open semantics.

        Design: Difficulty/resource_temporal_overlap/coverage_window_half_open_adjacency
        """
        scn = Scenario()
        nurse = scn.add_staff("NURSE", "Nurse S")
        pool = scn.add_pool("NURSE_TRIAGE", "FROM_TRIAGE", name="NurseTriage")
        scn.add_coverage(pool["id"], nurse["id"],
                         "2026-08-03T09:00:00Z", "2026-08-03T12:00:00Z")
        resp = api.create_coverage_window(
            create_coverage_window_payload(pool["id"], nurse["id"],
                                           "2026-08-03T12:00:00Z",
                                           "2026-08-03T15:00:00Z"),
            practice_admin_headers)
        data = validate_success(resp, 201)
        assert data["staff_id"] == nurse["id"]
        assert_same_instant(data["start_utc"], "2026-08-03T12:00:00Z",
                            label="adjacent window start")

    def test_coverage_window_straddling_rejected(self, api, practice_admin_headers):
        """PRD §2.9: "Two coverage windows for the same `staff_id` may not
        intersect, but adjacency is allowed: a new window whose `start_utc`
        equals an existing window's `end_utc` (or whose `end_utc` equals an
        existing window's `start_utc`) does not conflict; a genuine intersection
        is rejected with `ERR_COVERAGE_WINDOW_OVERLAP`."

        The existing window is [09:00, 12:00); [11:00, 13:00) genuinely
        intersects it and must be rejected.

        Design: Difficulty/resource_temporal_overlap/coverage_window_half_open_adjacency
        """
        scn = Scenario()
        nurse = scn.add_staff("NURSE", "Nurse S")
        pool = scn.add_pool("NURSE_TRIAGE", "FROM_TRIAGE", name="NurseTriage")
        scn.add_coverage(pool["id"], nurse["id"],
                         "2026-08-03T09:00:00Z", "2026-08-03T12:00:00Z")
        resp = api.create_coverage_window(
            create_coverage_window_payload(pool["id"], nurse["id"],
                                           "2026-08-03T11:00:00Z",
                                           "2026-08-03T13:00:00Z"),
            practice_admin_headers)
        validate_error(resp, ApiErrorId.ERR_COVERAGE_WINDOW_OVERLAP)


class TestOnCallShiftOverlap:
    def test_oncall_shift_touching_endpoint_rejected(self, api, practice_admin_headers):
        """PRD §2.9: "Two on-call shifts for the same `provider_id` may not
        intersect under closed-interval semantics, and touching endpoints count
        as overlap — a new shift starting exactly when an existing one ends is
        rejected with `ERR_ONCALL_SHIFT_OVERLAP`."

        The existing shift is [17:00, 21:00] (closed); a new shift starting at
        exactly 21:00 touches it and must be rejected.

        Design: Difficulty/resource_temporal_overlap/oncall_shift_closed_touch_conflict
        """
        scn = Scenario()
        provider = scn.add_staff("PROVIDER", "Dr P")
        scn.add_on_call_shift(provider["id"],
                              "2026-08-03T17:00:00Z", "2026-08-03T21:00:00Z")
        resp = api.create_on_call_shift(
            create_on_call_shift_payload(provider["id"],
                                         "2026-08-03T21:00:00Z",
                                         "2026-08-03T23:00:00Z"),
            practice_admin_headers)
        validate_error(resp, ApiErrorId.ERR_ONCALL_SHIFT_OVERLAP)

    def test_oncall_shift_with_gap_accepted(self, api, practice_admin_headers):
        """PRD §2.9: "Two on-call shifts for the same `provider_id` may not
        intersect under closed-interval semantics, and touching endpoints count
        as overlap — a new shift starting exactly when an existing one ends is
        rejected with `ERR_ONCALL_SHIFT_OVERLAP`."

        A strict one-second gap ([21:00:01, 23:00] after [17:00, 21:00]) is not
        an intersection and must be accepted.

        Design: Difficulty/resource_temporal_overlap/oncall_shift_closed_touch_conflict
        """
        scn = Scenario()
        provider = scn.add_staff("PROVIDER", "Dr P")
        scn.add_on_call_shift(provider["id"],
                              "2026-08-03T17:00:00Z", "2026-08-03T21:00:00Z")
        resp = api.create_on_call_shift(
            create_on_call_shift_payload(provider["id"],
                                         "2026-08-03T21:00:01Z",
                                         "2026-08-03T23:00:00Z"),
            practice_admin_headers)
        data = validate_success(resp, 201)
        assert data["provider_id"] == provider["id"]


class TestTimeRangeValidity:
    def test_time_range_must_be_strictly_positive(self, api, practice_admin_headers):
        """PRD §2.9: "For all three kinds, `end_utc` must be strictly later than
        `start_utc`; otherwise creation fails with `ERR_INVALID_TIME_RANGE`."

        A zero-length coverage window (end == start) and an inverted on-call
        shift (end < start) are both rejected.

        Design: Corner/validations/time_range_must_be_strictly_positive
        """
        scn = Scenario()
        nurse = scn.add_staff("NURSE", "Nurse N")
        provider = scn.add_staff("PROVIDER", "Dr P")
        pool = scn.add_pool("NURSE_TRIAGE", "FROM_TRIAGE", name="NurseTriage")

        resp_window = api.create_coverage_window(
            create_coverage_window_payload(pool["id"], nurse["id"],
                                           "2026-08-03T09:00:00Z",
                                           "2026-08-03T09:00:00Z"),
            practice_admin_headers)
        validate_error(resp_window, ApiErrorId.ERR_INVALID_TIME_RANGE)

        resp_shift = api.create_on_call_shift(
            create_on_call_shift_payload(provider["id"],
                                         "2026-08-03T20:00:00Z",
                                         "2026-08-03T08:00:00Z"),
            practice_admin_headers)
        validate_error(resp_shift, ApiErrorId.ERR_INVALID_TIME_RANGE)

    def test_oncall_shift_requires_provider_type(self, api, practice_admin_headers):
        """PRD §3.2: "the referenced staff member must have `staff_type`
        `PROVIDER`, else `ERR_ONCALL_PROVIDER_TYPE`".

        An on-call shift naming a NURSE-typed staff member is rejected.

        Design: Corner/validations/oncall_shift_requires_provider_type
        """
        scn = Scenario()
        nurse = scn.add_staff("NURSE", "Nurse N")
        resp = api.create_on_call_shift(
            create_on_call_shift_payload(nurse["id"],
                                         "2026-08-03T17:00:00Z",
                                         "2026-08-03T21:00:00Z"),
            practice_admin_headers)
        validate_error(resp, ApiErrorId.ERR_ONCALL_PROVIDER_TYPE)


class TestDelegationGrants:
    def test_delegation_window_touch_overlap_and_pair_isolation(
            self, api, practice_admin_headers):
        """PRD §2.9: "Two `ACTIVE` delegation grants for the same
        delegator–delegate pair likewise may not intersect under closed-interval
        semantics, touching endpoints included, else
        `ERR_DELEGATION_WINDOW_OVERLAP`."

        A second grant for the same (delegator, delegate) pair starting exactly
        at the first grant's end conflicts; the identical window for a different
        delegate is a different pair and is accepted.

        Design: Corner/validations/delegation_window_touch_overlap_and_pair_isolation
        """
        scn = Scenario()
        provider = scn.add_staff("PROVIDER", "Dr P")
        nurse_a = scn.add_staff("NURSE", "Nurse A")
        nurse_b = scn.add_staff("NURSE", "Nurse B")
        pool = scn.add_pool("PROVIDER_INBOX", "FROM_TRIAGE", name="ProvInbox")
        scn.add_grant(provider, nurse_a["id"], pool["id"],
                      "2026-08-03T09:00:00Z", "2026-08-05T17:00:00Z")

        resp_touch = api.create_delegation_grant(
            create_delegation_grant_payload(nurse_a["id"], pool["id"],
                                            "2026-08-05T17:00:00Z",
                                            "2026-08-06T09:00:00Z"),
            staff_headers(provider))
        validate_error(resp_touch, ApiErrorId.ERR_DELEGATION_WINDOW_OVERLAP)

        resp_other = api.create_delegation_grant(
            create_delegation_grant_payload(nurse_b["id"], pool["id"],
                                            "2026-08-05T17:00:00Z",
                                            "2026-08-06T09:00:00Z"),
            staff_headers(provider))
        grant_b = validate_success(resp_other, 201)
        assert_delegation_grant(grant_b)
        assert grant_b["delegate_staff_id"] == nurse_b["id"]
        assert grant_b["delegator_provider_id"] == provider["id"]
        assert grant_b["status"] == "ACTIVE"

    def test_delegation_target_validation(self, api):
        """PRD §3.2: "The delegation target must be valid: the delegate must
        differ from the delegator, the delegate must exist, and the named pool
        must exist with `pool_kind` `PROVIDER_INBOX` — any failure is
        `ERR_INVALID_DELEGATION_TARGET`."

        A grant into a NURSE_TRIAGE pool and a self-delegation are both
        rejected.

        Design: Corner/validations/delegation_target_validation
        """
        scn = Scenario()
        provider = scn.add_staff("PROVIDER", "Dr P")
        nurse = scn.add_staff("NURSE", "Nurse N")
        pool = scn.add_pool("NURSE_TRIAGE", "FROM_TRIAGE", name="NurseTriage")

        resp_pool = api.create_delegation_grant(
            create_delegation_grant_payload(nurse["id"], pool["id"],
                                            "2026-08-03T09:00:00Z",
                                            "2026-08-05T17:00:00Z"),
            staff_headers(provider))
        validate_error(resp_pool, ApiErrorId.ERR_INVALID_DELEGATION_TARGET)

        resp_self = api.create_delegation_grant(
            create_delegation_grant_payload(provider["id"], pool["id"],
                                            "2026-08-03T09:00:00Z",
                                            "2026-08-05T17:00:00Z"),
            staff_headers(provider))
        validate_error(resp_self, ApiErrorId.ERR_INVALID_DELEGATION_TARGET)

    def test_revoke_only_by_delegator(self, api):
        """PRD §3.2: "Revocation is permitted only while the grant is `ACTIVE` —
        an already-revoked grant fails with `ERR_GRANT_ALREADY_REVOKED` — and
        only for the grant's own delegator, with anyone else rejected as
        `ERR_NOT_GRANT_OWNER`."

        Design: Corner/validations/revoke_only_by_delegator
        """
        scn = Scenario()
        p1 = scn.add_staff("PROVIDER", "Dr P1")
        p2 = scn.add_staff("PROVIDER", "Dr P2")
        nurse = scn.add_staff("NURSE", "Nurse N")
        pool = scn.add_pool("PROVIDER_INBOX", "FROM_TRIAGE", name="ProvInbox")
        grant = scn.add_grant(p1, nurse["id"], pool["id"],
                              "2026-08-03T09:00:00Z", "2026-08-05T17:00:00Z")

        resp = api.revoke_delegation_grant(grant["id"], staff_headers(p2))
        validate_error(resp, ApiErrorId.ERR_NOT_GRANT_OWNER)

        after = scn.get_grant(grant["id"])
        assert after["status"] == "ACTIVE", (
            f"grant must remain ACTIVE after a rejected revoke, "
            f"got {after['status']}"
        )


class TestDelegationRevokeCascade:
    def _setup_delegated_message(self):
        """Provider P1 delegates the PROVIDER_INBOX pool to nurse N2; a message
        is triaged to the pool, assigned to N2, and claimed via the grant."""
        scn = Scenario()
        nurse_triage = scn.add_staff("NURSE", "Nurse T")
        nurse_delegate = scn.add_staff("NURSE", "Nurse D")
        p1 = scn.add_staff("PROVIDER", "Dr P1")
        pool = scn.add_pool("PROVIDER_INBOX", "FROM_TRIAGE", name="ProvInbox")
        patient = scn.add_patient(full_name="Pat H")
        scn.set_clock("2026-08-03T10:00:00Z")
        grant = scn.add_grant(p1, nurse_delegate["id"], pool["id"],
                              "2026-08-03T00:00:00Z", "2026-08-05T17:00:00Z")
        msg = scn.send_message(patient, subject="Deleg", body="delegated work")
        scn.triage(msg["id"], nurse_triage, "ROUTINE", "ADMINISTRATIVE",
                   pool["id"])
        scn.assign(msg["id"], nurse_triage, staff_id=nurse_delegate["id"])
        scn.start_review(msg["id"], nurse_delegate)
        return scn, grant, msg, nurse_delegate, p1

    def test_grant_revoke_reassigns_delegate_messages(self, api):
        """PRD §3.2: "Revocation stamps `revoked_at`, moves the grant to
        `REVOKED`, and cascades: every portal message currently assigned to the
        delegate within that pool and sitting in `ASSIGNED`, `IN_REVIEW`, or
        `PENDING_COSIGN` is reassigned to the delegator with its status
        retained."

        Design: Difficulty/transitive_cascade/delegation_revoke_reassigns_and_recounts
        """
        scn, grant, msg, nurse_delegate, p1 = self._setup_delegated_message()
        data = validate_success(
            api.revoke_delegation_grant(grant["id"], staff_headers(p1)), 200)
        assert data["status"] == "REVOKED"
        assert_same_instant(data["revoked_at"], "2026-08-03T10:00:00Z",
                            label="revoked_at (logical clock)")

        after = scn.get_message(msg["id"])
        assert after["assignee_id"] == p1["id"], (
            f"revoke cascade must reassign the delegate's in-flight message to "
            f"the delegator {p1['id']}, got assignee {after['assignee_id']}"
        )
        assert after["status"] == "IN_REVIEW", (
            f"status must be retained through the cascade, got {after['status']}"
        )

    def test_grant_revoke_shifts_open_counts_zero_sum(self, api):
        """PRD §3.2: "The delegate's `open_inbox_count` drops by the number of
        reassigned messages and the delegator's rises by the same amount — a
        zero-sum shift per §2.11 — and `inbox_overloaded` is re-evaluated for
        both parties."

        Design: Difficulty/transitive_cascade/delegation_revoke_reassigns_and_recounts
        """
        scn, grant, msg, nurse_delegate, p1 = self._setup_delegated_message()
        assert scn.get_staff(nurse_delegate["id"])["open_inbox_count"] == 1
        assert scn.get_staff(p1["id"])["open_inbox_count"] == 0

        validate_success(
            api.revoke_delegation_grant(grant["id"], staff_headers(p1)), 200)

        delegate_after = scn.get_staff(nurse_delegate["id"])
        delegator_after = scn.get_staff(p1["id"])
        assert delegate_after["open_inbox_count"] == 0, (
            f"delegate count must drop by the number of reassigned messages, "
            f"got {delegate_after['open_inbox_count']}"
        )
        assert delegator_after["open_inbox_count"] == 1, (
            f"delegator count must rise by the same amount (zero-sum), "
            f"got {delegator_after['open_inbox_count']}"
        )

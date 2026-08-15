"""Auditor assignment gates, window geometry, rotation, and workload parity."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_application,
    application_audits,
    assert_instant_equal,
    assign_audit,
    create_assign_payload,
    decide_audit,
    get_audit,
    get_auditor,
    make_application,
    make_auditor,
    make_client,
    make_client_admin_headers,
    make_auditor_headers,
    make_scheme,
    reschedule_audit,
    setup_accepted_chain,
    setup_assigned_chain,
    setup_granted_chain,
    setup_started_chain,
    start_second_audit,
    submit_application,
    submit_report,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["scheme_admin_headers"]
MISSING_AUDIT = "11111111-2222-4333-8444-555555555555"
MISSING_AUDITOR = "99999999-8888-4777-8666-555555555555"


class TestAssignmentGate:
    def test_auditor_cannot_assign_audit(self, api):
        """PRD §2.1: "A caller whose role is not listed among an endpoint's
        authorized roles is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §3.4: "Assignment is the `SchemeAdmin`'s act of naming the auditor
        for a `SCHEDULED` audit by supplying an `auditor_id`."

        Design: Corner/rbac/auditor_cannot_assign_audit
        """
        chain = setup_accepted_chain()
        resp = api.assign_auditor(chain.audit["id"],
                                  create_assign_payload(chain.auditor["id"]),
                                  make_auditor_headers(chain.auditor["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert get_audit(chain.audit["id"])["auditor_id"] is None

    def test_client_admin_cannot_assign_audit_even_when_audit_missing(
            self, api):
        """PRD §2.5: "the server evaluates nine classes of checks in a fixed
        priority order, and a failure in an earlier class masks every later
        class." Role authorization (class 2: "The caller's role must appear
        among the endpoint's authorized roles; otherwise `ERR_UNAUTHORIZED`
        (403).") masks path existence (class 4), so a ClientAdmin calling
        assign gets 403, never a 404.

        Design: Corner/validations/client_admin_cannot_assign_audit_even_when_audit_missing
        """
        client = make_client()
        resp = api.assign_auditor(MISSING_AUDIT,
                                  {"auditor_id": MISSING_AUDITOR},
                                  make_client_admin_headers(client["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_existence_precedes_state_on_assign(self, api):
        """PRD §2.5: "the server evaluates nine classes of checks in a fixed
        priority order, and a failure in an earlier class masks every later
        class." Path existence (class 4: "Path identifiers are validated left
        to right; the first identifier that does not correspond to an existing
        resource produces its specific 404") masks state (class 5), so
        assigning on a nonexistent audit yields `ERR_AUDIT_NOT_FOUND`.

        Design: Corner/validations/existence_precedes_state_on_assign
        """
        auditor = make_auditor()
        resp = api.assign_auditor(MISSING_AUDIT,
                                  create_assign_payload(auditor["id"]),
                                  ADMIN)
        validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_FOUND, 404)

    def test_assign_nonexistent_auditor_reference_returns_422(self, api):
        """PRD §3.4: "A body reference to an auditor that does not exist is
        rejected with `ERR_REFERENCE_NOT_FOUND` (422)."

        Design: Corner/validations/assign_nonexistent_auditor_reference_returns_422
        """
        chain = setup_accepted_chain()
        resp = api.assign_auditor(chain.audit["id"],
                                  create_assign_payload(MISSING_AUDITOR),
                                  ADMIN)
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND, 422)
        assert get_audit(chain.audit["id"])["auditor_id"] is None

    def test_lapsed_auditor_assignment_rejected(self, api):
        """PRD §3.4: "the auditor's calibration must be `CURRENT` at
        assignment time, otherwise `ERR_AUDITOR_NOT_CALIBRATED` (422)"
        PRD §3.2: "it is `CURRENT` exactly when a witness audit with `result`
        `PASS` exists whose `witnessed_on` is no older than the scheme's
        `witness_validity_days`"

        Design: Corner/validations/lapsed_auditor_assignment_rejected
        """
        scheme = make_scheme()
        client = make_client()
        stale = make_auditor(name="Stale Sam",
                             witnessed_on="2025-01-01T00:00:00Z")
        app = submit_application(make_application(client, scheme), client)
        accept_application(app)
        audit = application_audits(app["id"])[0]
        resp = api.assign_auditor(audit["id"],
                                  create_assign_payload(stale["id"]), ADMIN)
        validate_error(resp, ApiErrorId.ERR_AUDITOR_NOT_CALIBRATED, 422)
        assert get_audit(audit["id"])["auditor_id"] is None

    def test_incompetent_auditor_assignment_rejected(self, api):
        """PRD §3.4: "the auditor's `competency_categories` must cover every
        product category in the application's scope, otherwise
        `ERR_AUDITOR_COMPETENCY_GAP` (422)"

        Design: Corner/validations/incompetent_auditor_assignment_rejected
        """
        scheme = make_scheme()
        client = make_client()
        meat_only = make_auditor(name="Meat Mike", competencies=["MEAT"])
        app = submit_application(make_application(client, scheme), client)
        accept_application(app)
        audit = application_audits(app["id"])[0]
        resp = api.assign_auditor(audit["id"],
                                  create_assign_payload(meat_only["id"]), ADMIN)
        validate_error(resp, ApiErrorId.ERR_AUDITOR_COMPETENCY_GAP, 422)

    def test_conflicted_auditor_assignment_rejected(self, api):
        """PRD §2.7: "an auditor whose `conflicted_client_ids` contains the
        client behind an audit may never be assigned to it, and an attempted
        assignment is rejected with `ERR_AUDITOR_CONFLICT_OF_INTEREST` (422)."

        Design: Corner/validations/conflicted_auditor_assignment_rejected
        """
        scheme = make_scheme()
        client = make_client()
        conflicted = make_auditor(name="Conflicted Carl",
                                  conflicts=[client["id"]])
        app = submit_application(make_application(client, scheme), client)
        accept_application(app)
        audit = application_audits(app["id"])[0]
        resp = api.assign_auditor(audit["id"],
                                  create_assign_payload(conflicted["id"]), ADMIN)
        validate_error(resp, ApiErrorId.ERR_AUDITOR_CONFLICT_OF_INTEREST, 422)
        assert get_audit(audit["id"])["auditor_id"] is None

    def test_auditor_calibration_boundary_exactly_at_validity(self, api):
        """PRD §3.2: "it is `CURRENT` exactly when a witness audit with
        `result` `PASS` exists whose `witnessed_on` is no older than the
        scheme's `witness_validity_days` — the boundary is inclusive, so a
        witness audit exactly `witness_validity_days` old still counts — and a
        `FAIL` witness audit never counts toward calibration."

        Design: Corner/calculations/auditor_calibration_boundary_exactly_at_validity
        """
        scheme = make_scheme()  # witness_validity_days 365
        client = make_client()
        # At the default logical clock 2026-08-01T00:00:00Z: Alice's PASS is
        # exactly 365 days old (inclusive boundary -> CURRENT); Bob's is 365
        # days and one second old (-> LAPSED).
        alice = make_auditor(name="Boundary Alice",
                             witnessed_on="2025-08-01T00:00:00Z")
        bob = make_auditor(name="Boundary Bob",
                           witnessed_on="2025-07-31T23:59:59Z")
        assert get_auditor(alice["id"])["calibration_status"] == "CURRENT"
        assert get_auditor(bob["id"])["calibration_status"] == "LAPSED"

        app = submit_application(make_application(client, scheme), client)
        accept_application(app)
        audit = application_audits(app["id"])[0]
        resp = api.assign_auditor(audit["id"], create_assign_payload(bob["id"]),
                                  ADMIN)
        validate_error(resp, ApiErrorId.ERR_AUDITOR_NOT_CALIBRATED, 422)
        data = validate_success(
            api.assign_auditor(audit["id"], create_assign_payload(alice["id"]),
                               ADMIN))
        assert data["auditor_id"] == alice["id"]

    def test_third_consecutive_audit_same_auditor_rejected(self, api):
        """PRD §3.4: "rotation is enforced — an auditor who performed the
        scheme's `rotation_limit` most recent consecutive audits for the same
        client and scheme may not be assigned again, and the attempt is
        rejected with `ERR_AUDITOR_ROTATION_LIMIT` (422)."

        Design: Corner/validations/third_consecutive_audit_same_auditor_rejected
        """
        # rotation_limit 2: the chain auditor performs seq1 and seq2.
        chain = setup_granted_chain()
        auditor2 = make_auditor(name="Second Auditor")
        start_second_audit(chain)
        chain.audit2 = submit_report(chain.audit2["id"], chain.auditor["id"])
        chain.audit2 = decide_audit(chain.audit2["id"], chain.dm["id"], "GRANT")
        audits = application_audits(chain.app["id"])
        assert len(audits) == 3
        audit3 = audits[2]

        resp = api.assign_auditor(audit3["id"],
                                  create_assign_payload(chain.auditor["id"]),
                                  ADMIN)
        validate_error(resp, ApiErrorId.ERR_AUDITOR_ROTATION_LIMIT, 422)
        # The rotation window blocks only the same auditor, not the slot.
        data = validate_success(api.assign_auditor(
            audit3["id"], create_assign_payload(auditor2["id"]), ADMIN))
        assert data["auditor_id"] == auditor2["id"]


class TestWindowGeometry:
    def test_announced_window_over_max_length_rejected(self, api):
        """PRD §2.8: "an announced audit (type `INITIAL` or `SURVEILLANCE`)
        may span at most the scheme's `announced_max_window_days`"
        PRD §2.8: "Each violation is rejected with `ERR_INVALID_AUDIT_WINDOW`
        (422)."

        Design: Corner/validations/announced_window_over_max_length_rejected
        """
        chain = setup_accepted_chain()  # announced_max_window_days 30
        resp = api.reschedule_audit(
            chain.audit["id"],
            {"window_start": "2026-08-16T00:00:00Z",
             "window_end": "2026-09-16T00:00:00Z"},  # 31 days
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_AUDIT_WINDOW, 422)
        # Exactly announced_max_window_days is inside the bound.
        data = validate_success(api.reschedule_audit(
            chain.audit["id"],
            {"window_start": "2026-08-16T00:00:00Z",
             "window_end": "2026-09-15T00:00:00Z"},  # 30 days
            ADMIN))
        assert_instant_equal(data["window_end"], "2026-09-15T00:00:00Z")

    def test_unannounced_window_under_min_length_rejected(self, api):
        """PRD §2.8: "an `UNANNOUNCED` audit must span at least the scheme's
        `unannounced_min_window_days`"
        PRD §2.8: "Each violation is rejected with `ERR_INVALID_AUDIT_WINDOW`
        (422)."

        Design: Corner/validations/unannounced_window_under_min_length_rejected
        """
        # unannounced_every_n 2 makes audit seq2 UNANNOUNCED (2 % 2 == 0).
        chain = setup_granted_chain(scheme_overrides={"unannounced_every_n": 2})
        audits = application_audits(chain.app["id"])
        audit2 = audits[1]
        assert audit2["audit_type"] == "UNANNOUNCED"
        resp = api.reschedule_audit(
            audit2["id"],
            {"window_start": "2026-10-14T00:00:00Z",
             "window_end": "2026-12-12T00:00:00Z"},  # 59 days
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_AUDIT_WINDOW, 422)
        # Exactly unannounced_min_window_days (60) satisfies the minimum.
        data = validate_success(api.reschedule_audit(
            audit2["id"],
            {"window_start": "2026-10-14T00:00:00Z",
             "window_end": "2026-12-13T00:00:00Z"},
            ADMIN))
        assert_instant_equal(data["window_end"], "2026-12-13T00:00:00Z")


class TestAssignPriorityPairs:
    def test_assign_in_progress_audit_state_wins_over_competency(self, api):
        """PRD §2.5: "the server evaluates nine classes of checks in a fixed
        priority order, and a failure in an earlier class masks every later
        class." State (class 5: "The target entity's status must permit the
        requested transition") precedes "Capability and aggregate constraints"
        (class 9), so assigning a competency-gapped auditor to an IN_PROGRESS
        audit reports `ERR_INVALID_AUDIT_STATE`, never
        `ERR_AUDITOR_COMPETENCY_GAP`.

        Design: Difficulty/priority_pair_validation_conflict/assign_in_progress_audit_with_incompetent_auditor_state_wins
        """
        chain = setup_started_chain()
        dairy_only = make_auditor(name="Dairy Specialist",
                                  competencies=["DAIRY"])
        resp = api.assign_auditor(chain.audit["id"],
                                  create_assign_payload(dairy_only["id"]),
                                  ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_AUDIT_STATE, 409)
        assert resp.json()["data"]["error_id"] != "ERR_AUDITOR_COMPETENCY_GAP"

    def test_assign_in_progress_audit_leaves_assignee_unchanged(self, api):
        """PRD §3.4: "Assignment is the `SchemeAdmin`'s act of naming the
        auditor for a `SCHEDULED` audit by supplying an `auditor_id`." The
        rejected reassignment against an IN_PROGRESS audit leaves the original
        assignee in place.

        Design: Difficulty/priority_pair_validation_conflict/assign_in_progress_audit_with_incompetent_auditor_state_wins
        """
        chain = setup_started_chain()
        dairy_only = make_auditor(name="Dairy Specialist",
                                  competencies=["DAIRY"])
        resp = api.assign_auditor(chain.audit["id"],
                                  create_assign_payload(dairy_only["id"]),
                                  ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_AUDIT_STATE, 409)
        assert get_audit(chain.audit["id"])["auditor_id"] == chain.auditor["id"]

    def test_assign_conflicted_auditor_safety_wins_over_overlap(self, api):
        """PRD §2.5: "the server evaluates nine classes of checks in a fixed
        priority order, and a failure in an earlier class masks every later
        class." "Independence and conflicts" (class 7, including
        `ERR_AUDITOR_CONFLICT_OF_INTEREST` (422)) precedes "Temporal rules"
        (class 8, including `ERR_AUDITOR_WINDOW_OVERLAP` (409)), so a
        conflicted auditor whose window would also overlap reports the
        conflict.

        Design: Difficulty/priority_pair_validation_conflict/assign_conflicted_auditor_with_overlapping_window_safety_wins
        """
        scheme = make_scheme()
        client_a = make_client(name="Acme Baking Co")
        client_b = make_client(name="Beta Dairy Ltd",
                               contact_email="ops@beta.test")
        carl = make_auditor(name="Conflicted Carl", conflicts=[client_a["id"]])
        app_a = submit_application(make_application(client_a, scheme), client_a)
        accept_application(app_a)
        audit_a = application_audits(app_a["id"])[0]
        app_b = submit_application(
            make_application(client_b, scheme, site_name="Site B",
                             scope_text="contract baking"), client_b)
        accept_application(app_b)
        audit_b = application_audits(app_b["id"])[0]
        # Identical default windows: committing Carl to audit B first makes
        # the audit A attempt trip both the conflict and the overlap rules.
        assign_audit(audit_b["id"], carl["id"])
        resp = api.assign_auditor(audit_a["id"],
                                  create_assign_payload(carl["id"]), ADMIN)
        validate_error(resp, ApiErrorId.ERR_AUDITOR_CONFLICT_OF_INTEREST, 422)
        assert resp.json()["data"]["error_id"] != "ERR_AUDITOR_WINDOW_OVERLAP"

    def test_assign_conflicted_auditor_overlap_case_leaves_unassigned(self, api):
        """PRD §2.7: "an auditor whose `conflicted_client_ids` contains the
        client behind an audit may never be assigned to it, and an attempted
        assignment is rejected with `ERR_AUDITOR_CONFLICT_OF_INTEREST` (422)."
        The rejected assignment leaves the target audit without an assignee.

        Design: Difficulty/priority_pair_validation_conflict/assign_conflicted_auditor_with_overlapping_window_safety_wins
        """
        scheme = make_scheme()
        client_a = make_client(name="Acme Baking Co")
        client_b = make_client(name="Beta Dairy Ltd",
                               contact_email="ops@beta.test")
        carl = make_auditor(name="Conflicted Carl", conflicts=[client_a["id"]])
        app_a = submit_application(make_application(client_a, scheme), client_a)
        accept_application(app_a)
        audit_a = application_audits(app_a["id"])[0]
        app_b = submit_application(
            make_application(client_b, scheme, site_name="Site B",
                             scope_text="contract baking"), client_b)
        accept_application(app_b)
        audit_b = application_audits(app_b["id"])[0]
        assign_audit(audit_b["id"], carl["id"])
        resp = api.assign_auditor(audit_a["id"],
                                  create_assign_payload(carl["id"]), ADMIN)
        validate_error(resp, ApiErrorId.ERR_AUDITOR_CONFLICT_OF_INTEREST, 422)
        assert get_audit(audit_a["id"])["auditor_id"] is None


class TestAuditorWindowOverlap:
    def test_auditor_window_intersection_rejected(self, api):
        """PRD §2.8: "an auditor's committed windows must not intersect: two
        windows intersect whenever the first starts no later than the second
        ends and, symmetrically, the second starts no later than the first
        ends — boundaries are inclusive, so windows that merely touch still
        count as overlapping — and an offending assignment or reschedule is
        rejected with `ERR_AUDITOR_WINDOW_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/auditor_window_intersection_rejected_adjacency_allowed
        """
        scheme = make_scheme()
        client_a = make_client(name="Acme Baking Co")
        client_b = make_client(name="Beta Dairy Ltd",
                               contact_email="ops@beta.test")
        auditor = make_auditor()
        app_a = submit_application(make_application(client_a, scheme), client_a)
        accept_application(app_a)
        audit_a = application_audits(app_a["id"])[0]
        app_b = submit_application(
            make_application(client_b, scheme, site_name="Site B",
                             scope_text="fluid milk",
                             categories=[{"category_code": "DAIRY",
                                          "risk_tier": "STANDARD"}]),
            client_b)
        accept_application(app_b)
        audit_b = application_audits(app_b["id"])[0]
        assign_audit(audit_a["id"], auditor["id"])
        # audit B's default window [2026-08-15, 2026-09-14] is identical to
        # audit A's, so the inclusive-intersection rule rejects the assign.
        resp = api.assign_auditor(audit_b["id"],
                                  create_assign_payload(auditor["id"]), ADMIN)
        validate_error(resp, ApiErrorId.ERR_AUDITOR_WINDOW_OVERLAP, 409)

    def test_auditor_window_adjacency_allowed(self, api):
        """PRD §2.8: "two windows intersect whenever the first starts no later
        than the second ends and, symmetrically, the second starts no later
        than the first ends — boundaries are inclusive". A window starting
        after the other's end fails the second clause, so adjacency is not
        intersection and the assignment succeeds.
        PRD §3.2: "The `active_audit_count` counts the audits assigned to the
        auditor that are currently in `SCHEDULED` or `IN_PROGRESS` status"

        Design: Difficulty/resource_temporal_overlap/auditor_window_intersection_rejected_adjacency_allowed
        """
        scheme = make_scheme()
        client_a = make_client(name="Acme Baking Co")
        client_b = make_client(name="Beta Dairy Ltd",
                               contact_email="ops@beta.test")
        auditor = make_auditor()
        app_a = submit_application(make_application(client_a, scheme), client_a)
        accept_application(app_a)
        audit_a = application_audits(app_a["id"])[0]
        app_b = submit_application(
            make_application(client_b, scheme, site_name="Site B",
                             scope_text="fluid milk",
                             categories=[{"category_code": "DAIRY",
                                          "risk_tier": "STANDARD"}]),
            client_b)
        accept_application(app_b)
        audit_b = application_audits(app_b["id"])[0]
        assign_audit(audit_a["id"], auditor["id"])
        # Shift audit B to start one day after audit A's window ends; this is
        # a 30-day announced window that does not intersect audit A's.
        reschedule_audit(audit_b["id"], "2026-09-15T00:00:00Z",
                         "2026-10-15T00:00:00Z")
        data = validate_success(api.assign_auditor(
            audit_b["id"], create_assign_payload(auditor["id"]), ADMIN))
        assert data["auditor_id"] == auditor["id"]
        assert get_auditor(auditor["id"])["active_audit_count"] == 2


class TestClientSchemeGapBuffer:
    def test_min_gap_29_days_rejected(self, api):
        """PRD §2.8: "sibling audits of the same client and scheme must
        respect the minimum separation: when one window ends before the other
        begins, the gap from the earlier window's end to the later window's
        start must be at least the scheme's `min_audit_gap_days`; a violation
        is rejected with `ERR_AUDIT_WINDOW_TOO_CLOSE` (409)."

        Design: Difficulty/resource_temporal_overlap/client_scheme_minimum_gap_buffer_enforced
        """
        chain = setup_granted_chain()  # min_audit_gap_days 30
        audits = application_audits(chain.app["id"])
        audit2 = audits[1]
        # Seq1's window ended 2026-09-14T00:00:00Z; a 2026-10-13 start leaves
        # a 29-day gap — one day short of the minimum.
        resp = api.reschedule_audit(
            audit2["id"],
            {"window_start": "2026-10-13T00:00:00Z",
             "window_end": "2026-11-12T00:00:00Z"},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_AUDIT_WINDOW_TOO_CLOSE, 409)

    def test_min_gap_30_days_allowed(self, api):
        """PRD §2.8: "the gap from the earlier window's end to the later
        window's start must be at least the scheme's `min_audit_gap_days`" —
        "at least" makes the boundary inclusive, so exactly 30 days passes.

        Design: Difficulty/resource_temporal_overlap/client_scheme_minimum_gap_buffer_enforced
        """
        chain = setup_granted_chain()
        audits = application_audits(chain.app["id"])
        audit2 = audits[1]
        # Seq1 ended 2026-09-14T00:00:00Z; 2026-10-14T00:00:00Z is exactly
        # min_audit_gap_days later.
        data = validate_success(api.reschedule_audit(
            audit2["id"],
            {"window_start": "2026-10-14T00:00:00Z",
             "window_end": "2026-11-13T00:00:00Z"},
            ADMIN))
        assert_instant_equal(data["window_start"], "2026-10-14T00:00:00Z")


class TestActiveAuditCountConservation:
    def test_active_count_assign_increments(self, api):
        """PRD §3.2: "The `active_audit_count` counts the audits assigned to
        the auditor that are currently in `SCHEDULED` or `IN_PROGRESS` status;
        it rises by one on assignment"

        Design: Difficulty/compensating_invariant/auditor_active_audit_count_assign_cancel_conservation
        """
        chain = setup_accepted_chain()
        assert get_auditor(chain.auditor["id"])["active_audit_count"] == 0
        assign_audit(chain.audit["id"], chain.auditor["id"])
        assert get_auditor(chain.auditor["id"])["active_audit_count"] == 1

    def test_active_count_cancel_compensates(self, api):
        """PRD §3.4: "Cancelling is also restricted to `SCHEDULED` audits
        (`ERR_INVALID_AUDIT_STATE` otherwise) and moves the audit to the
        terminal `CANCELLED` state; when an auditor was assigned, that
        auditor's `active_audit_count` falls by one" — the forward action
        (assign, +1) and its compensating action (cancel, -1) return the
        counter to exactly its origin.

        Design: Difficulty/compensating_invariant/auditor_active_audit_count_assign_cancel_conservation
        """
        chain = setup_assigned_chain()
        assert get_auditor(chain.auditor["id"])["active_audit_count"] == 1
        data = validate_success(api.cancel_audit(chain.audit["id"], ADMIN))
        assert data["status"] == "CANCELLED"
        # CANCELLED is neither SCHEDULED nor IN_PROGRESS, so it drops out of
        # the workload counter defined in PRD §3.2.
        assert get_auditor(chain.auditor["id"])["active_audit_count"] == 0

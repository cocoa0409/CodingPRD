"""Nonconformity CAP cycle, overdue sweep cascade, and reinstatement guard."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equal,
    certificate_listing,
    close_nc,
    get_certificate,
    get_nc,
    make_client,
    make_auditor_headers,
    make_decision_maker_headers,
    make_client_admin_headers,
    make_nonconformity,
    reject_nc,
    reinstate_certificate,
    review_cap,
    set_clock,
    setup_granted_chain,
    setup_started_chain,
    start_second_audit,
    submit_cap,
    validate_error,
)

ADMIN = TEST_USERS["scheme_admin_headers"]


class TestCapCycle:
    def test_cap_rejection_returns_nc_to_open_with_count(self, api):
        """PRD §3.7: "A `REJECT` outcome returns the finding `UNDER_REVIEW →
        OPEN`, increments `rejection_count` by one, and stamps `reviewed_at`"

        Design: Difficulty/non_linear_state_machine/nonconformity_cap_rejection_cycle_loop
        """
        chain = setup_started_chain()
        nc = make_nonconformity(chain.audit["id"], chain.auditor["id"],
                                grade="MINOR", clause_ref="SQF 2.6.1",
                                description="minor finding")
        rejected = reject_nc(nc["id"], chain.client["id"],
                             chain.auditor["id"], cap_text="first plan")
        assert rejected["status"] == "OPEN"
        assert rejected["rejection_count"] == 1

    def test_cap_cycle_loops_twice_then_closes(self, api):
        """PRD §3.7: "A `REJECT` outcome returns the finding `UNDER_REVIEW →
        OPEN`, increments `rejection_count` by one, and stamps `reviewed_at`"
        PRD §3.7: "An `ACCEPT` outcome moves the finding `UNDER_REVIEW →
        CLOSED` and stamps `reviewed_at`."

        Design: Difficulty/non_linear_state_machine/nonconformity_cap_rejection_cycle_loop
        """
        chain = setup_started_chain()
        nc = make_nonconformity(chain.audit["id"], chain.auditor["id"],
                                grade="MINOR", clause_ref="SQF 2.6.1",
                                description="minor finding")
        first = reject_nc(nc["id"], chain.client["id"], chain.auditor["id"],
                          cap_text="first plan")
        assert (first["status"], first["rejection_count"]) == ("OPEN", 1)
        # The machine re-enters OPEN rather than terminal-locking: a second
        # submission and rejection traverse the loop again.
        second = reject_nc(nc["id"], chain.client["id"], chain.auditor["id"],
                           cap_text="second plan")
        assert (second["status"], second["rejection_count"]) == ("OPEN", 2)
        closed = close_nc(nc["id"], chain.client["id"], chain.auditor["id"])
        assert closed["status"] == "CLOSED"
        assert closed["rejection_count"] == 2


class TestCapInvalidTransitions:
    def test_nc_submit_cap_from_under_review_rejected(self, api):
        """PRD §3.7: "the finding must be `OPEN` or `OVERDUE`
        (`ERR_INVALID_NC_STATE`, 409)."

        Design: Corner/state_machines/nc_submit_cap_from_under_review_rejected
        """
        chain = setup_started_chain()
        nc = make_nonconformity(chain.audit["id"], chain.auditor["id"])
        submit_cap(nc["id"], chain.client["id"], cap_text="first plan")
        resp = api.submit_cap(nc["id"], {"cap_text": "duplicate plan"},
                              make_client_admin_headers(chain.client["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_NC_STATE, 409)
        assert get_nc(nc["id"])["status"] == "UNDER_REVIEW"

    def test_nc_review_from_open_rejected(self, api):
        """PRD §3.7: "Reviewing a plan belongs to the auditor of the finding's
        audit (`ERR_FORBIDDEN_OWNERSHIP` for anyone else) and requires the
        finding to be `UNDER_REVIEW` (`ERR_INVALID_NC_STATE`)."

        Design: Corner/state_machines/nc_review_from_open_rejected
        """
        chain = setup_started_chain()
        nc = make_nonconformity(chain.audit["id"], chain.auditor["id"])
        resp = api.review_cap(nc["id"], {"outcome": "ACCEPT"},
                              make_auditor_headers(chain.auditor["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_NC_STATE, 409)
        assert get_nc(nc["id"])["status"] == "OPEN"

    def test_closed_nc_terminal_lockdown(self, api):
        """PRD §3.7: "the finding must be `OPEN` or `OVERDUE`
        (`ERR_INVALID_NC_STATE`, 409)."
        PRD §3.7: "Reviewing a plan ... requires the finding to be
        `UNDER_REVIEW` (`ERR_INVALID_NC_STATE`)."

        Design: Corner/state_machines/closed_nc_terminal_lockdown
        """
        chain = setup_started_chain()
        nc = make_nonconformity(chain.audit["id"], chain.auditor["id"])
        close_nc(nc["id"], chain.client["id"], chain.auditor["id"])
        resp = api.submit_cap(nc["id"], {"cap_text": "another plan"},
                              make_client_admin_headers(chain.client["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_NC_STATE, 409)
        resp = api.review_cap(nc["id"], {"outcome": "REJECT"},
                              make_auditor_headers(chain.auditor["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_NC_STATE, 409)
        assert get_nc(nc["id"])["status"] == "CLOSED"

    def test_client_admin_cannot_submit_cap_for_other_client(self, api):
        """PRD §3.7: "ownership is verified against the client chain behind
        the finding first (`ERR_FORBIDDEN_OWNERSHIP`)"
        PRD §2.1: "for a `ClientAdmin` the resource's client chain must equal
        `X-User-ID`"

        Design: Corner/rbac/client_admin_cannot_submit_cap_for_other_client
        """
        chain = setup_started_chain()
        nc = make_nonconformity(chain.audit["id"], chain.auditor["id"])
        intruder = make_client(name="Beta Dairy Ltd",
                               contact_email="ops@beta.test")
        resp = api.submit_cap(nc["id"], {"cap_text": "intruder plan"},
                              make_client_admin_headers(intruder["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)
        assert get_nc(nc["id"])["status"] == "OPEN"


class TestCapRejectionLimitCascade:
    def test_third_cap_rejection_suspends_certificate(self, api):
        """PRD §3.7: "when the `rejection_count` thereby reaches the scheme's
        `max_cap_rejections`, the rejection-limit cascade fires — a
        certificate for the same client and scheme in `ACTIVE` status
        transitions to `SUSPENDED` with `suspension_reason` `CAP_REJECT_LIMIT`
        and `status_changed_at` set to the current logical time, and per §2.10
        its DirectoryListing transitions to `UNLISTED` with `unlisted_at`
        stamped."

        Design: Corner/cross_cutting_layers/third_cap_rejection_suspends_certificate
        """
        # max_cap_rejections 3. The MINOR finding on the surveillance audit
        # (created 2026-10-14T09:00:00Z, deadline 84 days out) never goes
        # overdue during this test.
        chain = setup_granted_chain()
        audit2 = start_second_audit(chain)
        nc = make_nonconformity(audit2["id"], chain.auditor["id"],
                                grade="MINOR", clause_ref="SQF 2.6.1",
                                description="repeat offender finding")
        reject_nc(nc["id"], chain.client["id"], chain.auditor["id"],
                  cap_text="plan v1")
        reject_nc(nc["id"], chain.client["id"], chain.auditor["id"],
                  cap_text="plan v2")
        # Rejections 1 and 2 leave the certificate ACTIVE.
        assert get_certificate(chain.certificate["id"])["status"] == "ACTIVE"
        third = reject_nc(nc["id"], chain.client["id"], chain.auditor["id"],
                          cap_text="plan v3")
        assert third["rejection_count"] == 3
        assert third["status"] == "OPEN"
        cert = get_certificate(chain.certificate["id"])
        assert cert["status"] == "SUSPENDED"
        assert cert["suspension_reason"] == "CAP_REJECT_LIMIT"
        listing = certificate_listing(cert["id"])
        assert listing["status"] == "UNLISTED"


class TestOverdueSweepCascade:
    def test_overdue_sweep_marks_nc_overdue(self, api):
        """PRD §3.7: "Each finding still `OPEN` whose `deadline` is strictly
        earlier than the current logical time — sitting exactly on the
        deadline is not overdue — transitions `OPEN → OVERDUE`, processed in
        `created_at` ascending order."

        Design: Difficulty/transitive_cascade/overdue_nc_suspends_certificate_unlists_directory
        """
        chain = setup_granted_chain()
        audit2 = start_second_audit(chain)
        # CRITICAL finding created at 2026-10-14T09:00:00Z, critical_nc_days 7.
        nc = make_nonconformity(audit2["id"], chain.auditor["id"],
                                grade="CRITICAL", clause_ref="SQF 2.4.3",
                                description="pest activity in packaging area")
        assert_instant_equal(nc["deadline"], "2026-10-21T09:00:00Z")
        set_clock("2026-10-22T09:00:00Z")  # strictly past the deadline
        assert get_nc(nc["id"])["status"] == "OVERDUE"

    def test_overdue_sweep_cascades_to_certificate_and_listing(self, api):
        """PRD §3.7: "For each such finding, if a certificate for the same
        client and scheme is `ACTIVE`, it transitions to `SUSPENDED` with
        `suspension_reason` `NC_OVERDUE`, `status_changed_at` set, and
        `version` incremented, and its DirectoryListing transitions to
        `UNLISTED`."

        Design: Difficulty/transitive_cascade/overdue_nc_suspends_certificate_unlists_directory
        """
        chain = setup_granted_chain()
        audit2 = start_second_audit(chain)
        make_nonconformity(audit2["id"], chain.auditor["id"],
                           grade="CRITICAL", clause_ref="SQF 2.4.3",
                           description="pest activity in packaging area")
        set_clock("2026-10-22T09:00:00Z")
        cert = get_certificate(chain.certificate["id"])
        assert cert["status"] == "SUSPENDED"
        assert cert["suspension_reason"] == "NC_OVERDUE"
        # The cascade stamps the sweep's logical time.
        assert_instant_equal(cert["status_changed_at"], "2026-10-22T09:00:00Z")
        listing = certificate_listing(cert["id"])
        assert listing["status"] == "UNLISTED"
        assert_instant_equal(listing["unlisted_at"], "2026-10-22T09:00:00Z")


class TestDeadlineBoundary:
    def test_nc_deadline_exact_boundary_stays_open(self, api):
        """PRD §2.6: "Both sweeps compare with strict inequality — a finding
        becomes overdue only when the current logical time is strictly later
        than its `deadline`, and a certificate expires only when the current
        logical time is strictly later than its `valid_to`; sitting exactly on
        the boundary is not overdue and not expired."

        Design: Difficulty/boundary_precision_check/nc_deadline_exact_second_boundary_overdue_sweep
        """
        chain = setup_started_chain()  # INITIAL undecided: no certificate yet
        nc = make_nonconformity(chain.audit["id"], chain.auditor["id"],
                                grade="CRITICAL", clause_ref="SQF 2.4.3",
                                description="glass register incomplete")
        assert_instant_equal(nc["deadline"], "2026-08-22T09:00:00Z")
        set_clock("2026-08-22T09:00:00Z")  # exactly the deadline
        assert get_nc(nc["id"])["status"] == "OPEN"

    def test_nc_deadline_plus_one_second_overdue(self, api):
        """PRD §2.6: "a finding becomes overdue only when the current logical
        time is strictly later than its `deadline`"

        Design: Difficulty/boundary_precision_check/nc_deadline_exact_second_boundary_overdue_sweep
        """
        chain = setup_started_chain()
        nc = make_nonconformity(chain.audit["id"], chain.auditor["id"],
                                grade="CRITICAL", clause_ref="SQF 2.4.3",
                                description="glass register incomplete")
        set_clock("2026-08-22T09:00:00Z")  # boundary: still OPEN
        assert get_nc(nc["id"])["status"] == "OPEN"
        set_clock("2026-08-22T09:00:01Z")  # one second later: OVERDUE
        assert get_nc(nc["id"])["status"] == "OVERDUE"


class TestReinstateGuard:
    def _setup_nc_overdue_suspension(self, api):
        """Certificate suspended by the overdue sweep over one CRITICAL
        finding left OPEN on the surveillance audit."""
        chain = setup_granted_chain()
        audit2 = start_second_audit(chain)
        nc = make_nonconformity(audit2["id"], chain.auditor["id"],
                                grade="CRITICAL", clause_ref="SQF 2.4.3",
                                description="allergen segregation failure")
        set_clock("2026-10-22T09:00:00Z")  # past deadline 2026-10-21T09:00:00Z
        assert get_nc(nc["id"])["status"] == "OVERDUE"
        assert get_certificate(chain.certificate["id"])["status"] == "SUSPENDED"
        return chain, nc

    def test_reinstate_blocked_while_nc_overdue(self, api):
        """PRD §3.8: "When `suspension_reason` is `NC_OVERDUE` or
        `CAP_REJECT_LIMIT`, every nonconformity raised on audits of the same
        client and scheme must be `CLOSED` before reinstatement is allowed,
        otherwise the attempt is rejected with `ERR_OPEN_NCS_REMAIN`"

        Design: Difficulty/cross_entity_state_dependency/certificate_reinstate_requires_all_nonconformities_closed
        """
        chain, nc = self._setup_nc_overdue_suspension(api)
        resp = api.reinstate_certificate(
            chain.certificate["id"],
            make_decision_maker_headers(chain.dm["id"]))
        validate_error(resp, ApiErrorId.ERR_OPEN_NCS_REMAIN, 422)
        assert get_certificate(chain.certificate["id"])["status"] == "SUSPENDED"

    def test_reinstate_allowed_after_nc_closed(self, api):
        """PRD §3.7: "A late submission does not undo anything else: if the
        certificate was already suspended when the finding went overdue, that
        suspension is not automatically reverted, and reinstatement remains
        the separate guarded transition of §3.8."
        PRD §3.8: "Reinstatement clears `suspension_reason` back to null,
        stamps `status_changed_at`, increments `version`, and transitions the
        DirectoryListing back to `LISTED` with a fresh `listed_at`."

        Design: Difficulty/cross_entity_state_dependency/certificate_reinstate_requires_all_nonconformities_closed
        """
        chain, nc = self._setup_nc_overdue_suspension(api)
        # Late CAP from OVERDUE is allowed, then acceptance closes the finding.
        submit_cap(nc["id"], chain.client["id"],
                   cap_text="late but complete corrective plan")
        closed = review_cap(nc["id"], chain.auditor["id"], "ACCEPT")
        assert closed["status"] == "CLOSED"
        # The suspension was not auto-reverted by the late submission.
        assert get_certificate(chain.certificate["id"])["status"] == "SUSPENDED"
        reinstated = reinstate_certificate(chain.certificate["id"],
                                           chain.dm["id"])
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["suspension_reason"] is None
        listing = certificate_listing(chain.certificate["id"])
        assert listing["status"] == "LISTED"

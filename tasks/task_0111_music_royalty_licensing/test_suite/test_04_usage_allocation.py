"""Usage ingest/allocate guards (PRD §3.3) and validation-priority conflicts.

Covers the share-lock precondition, rights-window coverage, open-statement
requirement, the void state guard, and the two validation-priority pairs where
the structurally-earlier check pre-empts a later one.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_recording_payload,
    create_recording_share_payload,
    setup_allocated_performance,
    ingest_mechanical_usage,
    set_clock,
    create_rightsholder,
    create_registered_work,
    create_locked_recording,
    grant_window,
    open_statement,
)

ADMIN = TEST_USERS["administrator_headers"]
OPERATOR = TEST_USERS["operator_headers"]


# =============================================================================
# Difficulty queue A — priority_pair_validation_conflict
# =============================================================================

class TestValidationPriorityConflicts:
    def test_invalid_state_beats_rights_not_available(self, api):
        """PRD §2.8: "for an action endpoint, the target resource must currently be in a
        state from which the requested transition is defined, or the request fails with
        ERR_INVALID_STATE."
        PRD §2.8: "Where multiple of these apply to one endpoint, they are evaluated in
        ascending priority so that the structurally earliest violation is the one reported."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_rights_not_available
        """
        # A VOIDED usage on a locked recording with NO rights window at all:
        # both ERR_INVALID_STATE (state) and ERR_RIGHTS_NOT_AVAILABLE could apply;
        # state (priority 6) is reported.
        set_clock("2026-08-10T00:00:00.000Z")
        holder = create_rightsholder(legal_name="Label P", party_type="LABEL")
        work = create_registered_work(holder["id"], pro_affiliation="NONE",
                                       duration_seconds=200, role="PUBLISHER")
        rec = create_locked_recording(work["id"], holder["id"], release_type="PHYSICAL",
                                       duration_seconds=200)
        ue = ingest_mechanical_usage(rec["id"], "2026-08-10T00:00:00.000Z", quantity=100)
        validate_success(api.void_usage_event(ue["id"], OPERATOR))

        resp = api.allocate_usage_event(ue["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rights_not_available_surfaces_once_state_check_passes(self, api):
        """PRD §3.3: "It requires an ACTIVE rights window on that recording whose
        rights_type matches the usage's licensing class ... absent such a window the
        allocation is rejected with ERR_RIGHTS_NOT_AVAILABLE."
        PRD §2.8: "Where multiple of these apply to one endpoint, they are evaluated in
        ascending priority so that the structurally earliest violation is the one reported."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_rights_not_available
        """
        # Same catalog as the masked case, but the event stays INGESTED (state check
        # passes). With still NO rights window, the lower-ranked ERR_RIGHTS_NOT_AVAILABLE
        # is now the surfaced error — confirming the state check was what pre-empted it.
        set_clock("2026-08-10T00:00:00.000Z")
        holder = create_rightsholder(legal_name="Label P2", party_type="LABEL", minimum_payout_cents=1)
        work = create_registered_work(holder["id"], pro_affiliation="NONE",
                                       duration_seconds=200, role="PUBLISHER")
        rec = create_locked_recording(work["id"], holder["id"], release_type="PHYSICAL",
                                       duration_seconds=200)
        open_statement(holder["id"], "2026-08-01T00:00:00.000Z", "2026-09-01T00:00:00.000Z")
        ue = ingest_mechanical_usage(rec["id"], "2026-08-10T00:00:00.000Z", quantity=100)
        resp = api.allocate_usage_event(ue["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_RIGHTS_NOT_AVAILABLE)

    def test_shares_not_locked_beats_rights_not_available(self, api):
        """PRD §3.3: "It further requires that both the recording's parent Work has
        shares_locked true and the Recording itself has shares_locked true; if either is
        unlocked the allocation is rejected with ERR_SHARES_NOT_LOCKED."
        PRD §2.8: "Where multiple of these apply to one endpoint, they are evaluated in
        ascending priority so that the structurally earliest violation is the one reported."

        Design: Difficulty/priority_pair_validation_conflict/shares_not_locked_beats_rights_not_available
        """
        # INGESTED MECHANICAL usage on an UNLOCKED recording with NO rights window:
        # shares-not-locked (priority 11) beats rights-not-available (priority 12).
        set_clock("2026-08-20T00:00:00.000Z")
        holder = create_rightsholder(legal_name="Label Q", party_type="LABEL")
        work = create_registered_work(holder["id"], pro_affiliation="NONE",
                                       duration_seconds=200, role="PUBLISHER")
        rec = get_success_data(api.create_recording(
            create_recording_payload(work_id=work["id"], release_type="PHYSICAL",
                                    duration_seconds=200), ADMIN))
        get_success_data(api.create_recording_share(
            create_recording_share_payload(recording_id=rec["id"], rightsholder_id=holder["id"],
                                           split_bps=5000), ADMIN))
        # Recording NOT locked.
        ue = ingest_mechanical_usage(rec["id"], "2026-08-20T00:00:00.000Z", quantity=100)
        resp = api.allocate_usage_event(ue["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_SHARES_NOT_LOCKED)

    def test_rights_not_available_surfaces_once_shares_are_locked(self, api):
        """PRD §3.3: "It requires an ACTIVE rights window on that recording whose
        rights_type matches the usage's licensing class ... absent such a window the
        allocation is rejected with ERR_RIGHTS_NOT_AVAILABLE."
        PRD §2.8: "Where multiple of these apply to one endpoint, they are evaluated in
        ascending priority so that the structurally earliest violation is the one reported."

        Design: Difficulty/priority_pair_validation_conflict/shares_not_locked_beats_rights_not_available
        """
        # Lock the recording (shares-not-locked check passes) but still grant NO window,
        # so the lower-ranked ERR_RIGHTS_NOT_AVAILABLE surfaces — confirming the
        # shares-not-locked check was what pre-empted it in the masked case.
        set_clock("2026-08-20T00:00:00.000Z")
        holder = create_rightsholder(legal_name="Label Q2", party_type="LABEL", minimum_payout_cents=1)
        work = create_registered_work(holder["id"], pro_affiliation="NONE",
                                       duration_seconds=200, role="PUBLISHER")
        rec = create_locked_recording(work["id"], holder["id"], release_type="PHYSICAL",
                                       duration_seconds=200)
        open_statement(holder["id"], "2026-08-01T00:00:00.000Z", "2026-09-01T00:00:00.000Z")
        ue = ingest_mechanical_usage(rec["id"], "2026-08-20T00:00:00.000Z", quantity=100)
        resp = api.allocate_usage_event(ue["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_RIGHTS_NOT_AVAILABLE)


# =============================================================================
# Difficulty queue A — cross_entity_state_dependency (allocate -> recording locked)
# =============================================================================

class TestAllocateRequiresSharesLocked:
    def test_allocate_blocked_when_recording_unlocked(self, api):
        """PRD §3.3: "It further requires that both the recording's parent Work has
        shares_locked true and the Recording itself has shares_locked true; if either is
        unlocked the allocation is rejected with ERR_SHARES_NOT_LOCKED."

        Design: Difficulty/cross_entity_state_dependency/usage_allocate_requires_shares_locked
        """
        # Work registered (shares_locked true) but Recording NOT locked; window + open
        # statement present so the ONLY failing precondition is the recording lock.
        set_clock("2026-10-10T00:00:00.000Z")
        holder = create_rightsholder(legal_name="Label T", party_type="LABEL", minimum_payout_cents=1)
        work = create_registered_work(holder["id"], pro_affiliation="NONE",
                                       duration_seconds=200, role="PUBLISHER")
        rec = get_success_data(api.create_recording(
            create_recording_payload(work_id=work["id"], release_type="PHYSICAL",
                                    duration_seconds=200), ADMIN))
        get_success_data(api.create_recording_share(
            create_recording_share_payload(recording_id=rec["id"], rightsholder_id=holder["id"],
                                           split_bps=10000), ADMIN))
        # Recording deliberately left unlocked.
        grant_window(rec["id"], "MECHANICAL", "2026-10-01T00:00:00.000Z", "2026-11-01T00:00:00.000Z")
        open_statement(holder["id"], "2026-10-01T00:00:00.000Z", "2026-11-01T00:00:00.000Z")
        ue = ingest_mechanical_usage(rec["id"], "2026-10-10T00:00:00.000Z", quantity=100)

        resp = api.allocate_usage_event(ue["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_SHARES_NOT_LOCKED)

    def test_allocate_succeeds_when_both_locked(self, api):
        """PRD §3.3: "It further requires that both the recording's parent Work has
        shares_locked true and the Recording itself has shares_locked true; if either is
        unlocked the allocation is rejected with ERR_SHARES_NOT_LOCKED."

        Design: Difficulty/cross_entity_state_dependency/usage_allocate_requires_shares_locked
        """
        # The positive companion: with both Work and Recording locked (plus window and
        # open statement) allocation proceeds to ALLOCATED.
        ctx = setup_allocated_performance()
        assert ctx["usage_event"]["status"] == "ALLOCATED"


# =============================================================================
# Corner queue B — state_machines & validations on allocate/void
# =============================================================================

class TestUsageStateAndCoverageCorners:
    def test_void_on_allocated_usage_rejected(self, api):
        """PRD §3.3: "once an event has been allocated onto a statement it can no longer
        be voided, and a void attempt on a non-INGESTED event is rejected with
        ERR_INVALID_STATE."

        Design: Corner/state_machines/cancel_void_on_allocated_usage_invalid_state
        """
        ctx = setup_allocated_performance()
        resp = api.void_usage_event(ctx["usage_event"]["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_usage_outside_window_term_rejected(self, api):
        """PRD §3.2: "The term is a half-open interval: term_start is the inclusive UTC
        start and term_end is the exclusive UTC end, so an instant exactly at term_end
        falls outside the window."
        PRD §3.3: "whose term covers occurred_at; absent such a window the allocation is
        rejected with ERR_RIGHTS_NOT_AVAILABLE."

        Design: Corner/validations/usage_outside_window_term_rejected
        """
        set_clock("2026-02-01T00:00:00.000Z")
        holder = create_rightsholder(legal_name="LblTerm", party_type="LABEL", minimum_payout_cents=1)
        work = create_registered_work(holder["id"], pro_affiliation="NONE",
                                       duration_seconds=200, role="PUBLISHER")
        rec = create_locked_recording(work["id"], holder["id"], release_type="PHYSICAL",
                                       duration_seconds=200)
        grant_window(rec["id"], "MECHANICAL", "2026-01-01T00:00:00.000Z", "2026-02-01T00:00:00.000Z")
        open_statement(holder["id"], "2026-02-01T00:00:00.000Z", "2026-03-01T00:00:00.000Z")
        # occurred_at == term_end (2026-02-01) is outside the half-open window.
        ue = ingest_mechanical_usage(rec["id"], "2026-02-01T00:00:00.000Z", quantity=100)
        resp = api.allocate_usage_event(ue["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_RIGHTS_NOT_AVAILABLE)

    def test_no_open_statement_blocks_allocate(self, api):
        """PRD §3.3: "every holder who is to receive money must have a DRAFT statement
        whose half-open [period_start, period_end) period contains occurred_at; if any
        target holder lacks such a statement the allocation fails with
        ERR_NO_OPEN_STATEMENT and nothing at all is written."

        Design: Corner/validations/no_open_statement_blocks_allocate
        """
        set_clock("2026-05-10T00:00:00.000Z")
        holder = create_rightsholder(legal_name="LblNoStmt", party_type="LABEL", minimum_payout_cents=1)
        work = create_registered_work(holder["id"], pro_affiliation="NONE",
                                       duration_seconds=200, role="PUBLISHER")
        rec = create_locked_recording(work["id"], holder["id"], release_type="PHYSICAL",
                                       duration_seconds=200)
        grant_window(rec["id"], "MECHANICAL", "2026-05-01T00:00:00.000Z", "2026-06-01T00:00:00.000Z")
        # No statement opened for the holder.
        ue = ingest_mechanical_usage(rec["id"], "2026-05-10T00:00:00.000Z", quantity=100)
        resp = api.allocate_usage_event(ue["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_NO_OPEN_STATEMENT)

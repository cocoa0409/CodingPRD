"""Employee locks: issuance guards, capacity pinning, uniqueness, ownership,
force removal, and the outstanding-lock conserved quantity."""
from test_helpers import (
    ApiErrorId,
    apply_lock,
    assert_employee_lock,
    create_employee_lock_payload,
    get_employee,
    get_lock,
    get_session,
    issue_lock,
    make_authorized_employee_headers,
    make_ehs_manager_headers,
    register_qualified_employee,
    setup_pinned_capacity_scenario,
    setup_session_in_setup,
    setup_session_locked,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestLockLifecycleTransitions:
    def test_remove_from_issued_returns_invalid_state(self, api):
        """PRD §3.6: "Symmetrically, only the owner may remove their lock —
        moving `APPLIED` to `REMOVED` and stamping `removed_at` — and only while
        the session is `LOCKED`, with the same `ERR_FORBIDDEN` and
        `ERR_INVALID_STATE` split."

        Design: Corner/state_machines/lock_remove_from_issued_returns_invalid_state
        """
        ctx = setup_session_in_setup(asset_tag="A-IV4-1")
        lock = issue_lock(ctx["primary"], ctx["session"]["id"],
                          "L-IV4-1", "T-IV4-1")
        assert lock["status"] == "ISSUED"

        resp = api.remove_employee_lock(
            lock["id"], make_authorized_employee_headers(ctx["primary"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_lock(ctx["mgr"], lock["id"])["status"] == "ISSUED"


class TestIssuanceGuards:
    def test_duplicate_lock_no_rejected(self, api):
        """PRD §3.6: "Issuance is guarded: the issuer must be currently qualified
        (`ERR_TRAINING_NOT_CURRENT`); the `lock_no` must be unique among all
        locks currently in `ISSUED` or `APPLIED` (`ERR_DUPLICATE_LOCK_NO`); the
        employee must not already hold a non-terminal lock on the same session
        (`ERR_ALREADY_ON_SESSION`); and the session's lock-point capacity must
        have room."

        Design: Corner/validations/duplicate_lock_no_rejected
        """
        ctx = setup_session_in_setup(asset_tag="A-DL-1", isolation_points=2,
                                     session_type="GROUP")
        member3 = register_qualified_employee(ctx["mgr"], "E-W3-DL", "W3 DL")
        first = issue_lock(ctx["primary"], ctx["session"]["id"],
                           "L-DUP-1", "T-DL-1")
        assert first["status"] == "ISSUED"

        resp = api.create_employee_lock(
            create_employee_lock_payload(ctx["session"]["id"],
                                         lock_no="L-DUP-1", tag_no="T-DL-2"),
            make_authorized_employee_headers(member3["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LOCK_NO)
        _locks, meta = validate_paginated(api.list_employee_locks(
            make_ehs_manager_headers(ctx["mgr"]["id"]),
            params={"session_id": ctx["session"]["id"]}))
        assert meta["total_count"] == 1

    def test_employee_already_on_session_rejected(self, api):
        """PRD §3.6: "Issuance is guarded: the issuer must be currently qualified
        (`ERR_TRAINING_NOT_CURRENT`); the `lock_no` must be unique among all
        locks currently in `ISSUED` or `APPLIED` (`ERR_DUPLICATE_LOCK_NO`); the
        employee must not already hold a non-terminal lock on the same session
        (`ERR_ALREADY_ON_SESSION`); and the session's lock-point capacity must
        have room."

        Design: Corner/validations/employee_already_on_session_rejected
        """
        ctx = setup_session_in_setup(asset_tag="A-AO-1", isolation_points=2,
                                     session_type="GROUP")
        issue_lock(ctx["primary"], ctx["session"]["id"], "L-AO-1", "T-AO-1")

        resp = api.create_employee_lock(
            create_employee_lock_payload(ctx["session"]["id"],
                                         lock_no="L-AO-2", tag_no="T-AO-2"),
            make_authorized_employee_headers(ctx["primary"]["id"]))
        validate_error(resp, ApiErrorId.ERR_ALREADY_ON_SESSION)
        _locks, meta = validate_paginated(api.list_employee_locks(
            make_ehs_manager_headers(ctx["mgr"]["id"]),
            params={"session_id": ctx["session"]["id"]}))
        assert meta["total_count"] == 1


class TestLockOwnership:
    def test_non_owner_cannot_remove_lock(self, api):
        """PRD §3.6: "Symmetrically, only the owner may remove their lock —
        moving `APPLIED` to `REMOVED` and stamping `removed_at` — and only while
        the session is `LOCKED`, with the same `ERR_FORBIDDEN` and
        `ERR_INVALID_STATE` split."

        Design: Corner/validations/non_owner_cannot_remove_lock
        """
        ctx = setup_session_locked(asset_tag="A-OW1-1", isolation_points=2,
                                   session_type="GROUP", lock_no="L-OW1-1",
                                   tag_no="T-OW1-1")
        member3 = register_qualified_employee(ctx["mgr"], "E-W3-OW1", "W3 OW1")

        resp = api.remove_employee_lock(
            ctx["lock"]["id"], make_authorized_employee_headers(member3["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_lock(ctx["mgr"], ctx["lock"]["id"])["status"] == "APPLIED"


class TestForceRemoval:
    def test_owner_cannot_force_remove_own_lock_but_other_manager_can(self, api):
        """PRD §3.6: "An `EHSManager` may force-remove an `APPLIED` lock, but
        never their own — the manager's identity must differ from the lock's
        `employee_id`, failing which the request is rejected with
        `ERR_SELF_APPROVAL_FORBIDDEN` — and only while the owning session is
        `LOCKED` (`ERR_INVALID_STATE`)."
        PRD §3.6: "Force removal moves the lock to `FORCE_REMOVED`, stamps
        `removed_at`, records the supplied reason in `removal_reason` — a field
        that stays null on every ordinarily removed lock — and recomputes both
        counters."

        Design: Corner/validations/owner_cannot_force_remove_own_lock
        """
        ctx = setup_session_locked(asset_tag="A-SD3-1", lock_no="L-SD3-1",
                                   tag_no="T-SD3-1")
        lock_id = ctx["lock"]["id"]

        resp = api.force_remove_employee_lock(
            lock_id, {"reason": "self attempt"},
            make_ehs_manager_headers(ctx["primary"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)
        assert get_lock(ctx["mgr"], lock_id)["status"] == "APPLIED"

        removed = validate_success(api.force_remove_employee_lock(
            lock_id, {"reason": "Employee left site; contact attempted twice"},
            make_ehs_manager_headers(ctx["mgr"]["id"])))
        assert_employee_lock(removed)
        assert removed["status"] == "FORCE_REMOVED"
        assert removed["removal_reason"] == \
            "Employee left site; contact attempted twice"
        assert removed["removed_at"] is not None
        assert get_session(ctx["mgr"], ctx["session"]["id"])["applied_lock_count"] == 0
        assert get_employee(ctx["mgr"], ctx["primary"]["id"])["outstanding_lock_count"] == 0


class TestLockPointCapacityBoundary:
    def _setup_two_point_group_session(self, api, tag_suffix):
        ctx = setup_session_in_setup(asset_tag=f"A-LC-{tag_suffix}",
                                     isolation_points=2, session_type="GROUP")
        member3 = register_qualified_employee(ctx["mgr"], f"E-W3-LC{tag_suffix}",
                                              "W3 LC")
        member4 = register_qualified_employee(ctx["mgr"], f"E-W4-LC{tag_suffix}",
                                              "W4 LC")
        return ctx, member3, member4

    def test_locks_up_to_pinned_max_locks_are_accepted(self, api):
        """PRD §3.6: "Capacity is evaluated in a pinned order: first read the
        session's pinned `max_locks`; then count the session's non-terminal
        locks, those in `ISSUED` or `APPLIED`; if that count already equals
        `max_locks`, issuance is refused with `ERR_LOCK_POINT_CAPACITY`, while a
        count one below `max_locks` still allows it."

        Design: Difficulty/boundary_precision_check/lock_point_capacity_boundary
        """
        ctx, member3, _member4 = self._setup_two_point_group_session(api, "A")
        assert ctx["session"]["max_locks"] == 2

        lock1 = issue_lock(ctx["primary"], ctx["session"]["id"], "L-LC-1", "T-LC-1")
        assert lock1["status"] == "ISSUED"
        lock2 = issue_lock(member3, ctx["session"]["id"], "L-LC-2", "T-LC-2")
        assert lock2["status"] == "ISSUED", \
            "count 1 == max_locks - 1 before insert still allows issuance"

        session = get_session(ctx["mgr"], ctx["session"]["id"])
        assert session["applied_lock_count"] == 0, \
            "issuance alone does not apply locks"

    def test_lock_beyond_pinned_max_locks_rejected(self, api):
        """PRD §3.6: "Capacity is evaluated in a pinned order: first read the
        session's pinned `max_locks`; then count the session's non-terminal
        locks, those in `ISSUED` or `APPLIED`; if that count already equals
        `max_locks`, issuance is refused with `ERR_LOCK_POINT_CAPACITY`, while a
        count one below `max_locks` still allows it."

        Design: Difficulty/boundary_precision_check/lock_point_capacity_boundary
        """
        ctx, member3, member4 = self._setup_two_point_group_session(api, "B")
        issue_lock(ctx["primary"], ctx["session"]["id"], "L-LC-1", "T-LC-1")
        issue_lock(member3, ctx["session"]["id"], "L-LC-2", "T-LC-2")

        resp = api.create_employee_lock(
            create_employee_lock_payload(ctx["session"]["id"],
                                         lock_no="L-LC-3", tag_no="T-LC-3"),
            make_authorized_employee_headers(member4["id"]))
        validate_error(resp, ApiErrorId.ERR_LOCK_POINT_CAPACITY)
        _locks, meta = validate_paginated(api.list_employee_locks(
            make_ehs_manager_headers(ctx["mgr"]["id"]),
            params={"session_id": ctx["session"]["id"]}))
        assert meta["total_count"] == 2, "non-terminal count stays at max_locks"


class TestPinnedCapacitySurvivesSupersede:
    def test_second_lock_accepted_from_pinned_max_locks(self, api):
        """PRD §3.5: "These pins are never refreshed: the capacity check of §3.6
        always reads the session's pinned `max_locks` and never re-reads the
        procedure, so a procedure that later goes `UNDER_REVISION`, or is
        superseded by a revision carrying a different isolation-point count,
        cannot disturb in-flight sessions."
        PRD §3.5: "Creation **pins** two values from the governing procedure:
        `procedure_revision_no`, a copy of the procedure's `revision_no`, and
        `max_locks`, a copy of the procedure's `isolation_point_count`."

        Design: Difficulty/combinatorial_formula/pinned_capacity_survives_procedure_supersede
        """
        ctx = setup_pinned_capacity_scenario()
        assert ctx["p1"]["status"] == "SUPERSEDED", \
            "revision 1 superseded when the successor activated"
        assert ctx["p2"]["status"] == "ACTIVE"
        assert ctx["p2"]["isolation_point_count"] == 1, \
            "the successor carries a different isolation-point count"
        assert ctx["session"]["max_locks"] == 2, \
            "pinned from revision 1 at session creation"
        assert ctx["session"]["procedure_revision_no"] == 1

        lock1 = issue_lock(ctx["primary"], ctx["session"]["id"], "L-PC-1", "T-PC-1")
        assert lock1["status"] == "ISSUED"
        lock2 = issue_lock(ctx["member3"], ctx["session"]["id"], "L-PC-2", "T-PC-2")
        assert lock2["status"] == "ISSUED", \
            "pinned max_locks 2 governs, not the current procedure's count 1"

    def test_third_lock_rejected_at_pinned_capacity(self, api):
        """PRD §3.6: "Capacity is evaluated in a pinned order: first read the
        session's pinned `max_locks`; then count the session's non-terminal
        locks, those in `ISSUED` or `APPLIED`; if that count already equals
        `max_locks`, issuance is refused with `ERR_LOCK_POINT_CAPACITY`, while a
        count one below `max_locks` still allows it."
        PRD §3.5: "These pins are never refreshed: the capacity check of §3.6
        always reads the session's pinned `max_locks` and never re-reads the
        procedure, so a procedure that later goes `UNDER_REVISION`, or is
        superseded by a revision carrying a different isolation-point count,
        cannot disturb in-flight sessions."

        Design: Difficulty/combinatorial_formula/pinned_capacity_survives_procedure_supersede
        """
        ctx = setup_pinned_capacity_scenario()
        issue_lock(ctx["primary"], ctx["session"]["id"], "L-PC-1", "T-PC-1")
        issue_lock(ctx["member3"], ctx["session"]["id"], "L-PC-2", "T-PC-2")

        resp = api.create_employee_lock(
            create_employee_lock_payload(ctx["session"]["id"],
                                         lock_no="L-PC-3", tag_no="T-PC-3"),
            make_authorized_employee_headers(ctx["member4"]["id"]))
        validate_error(resp, ApiErrorId.ERR_LOCK_POINT_CAPACITY)
        session = get_session(ctx["mgr"], ctx["session"]["id"])
        assert session["max_locks"] == 2
        assert session["procedure_revision_no"] == 1


class TestOutstandingLockConservation:
    def test_issue_and_apply_move_outstanding_count(self, api):
        """PRD §3.4: "An employee's `outstanding_lock_count` is the number of
        their locks currently in `ISSUED` or `APPLIED`; it is recomputed whenever
        one of their locks is created or changes state."
        PRD §3.4: "New employees start with `status` `ACTIVE` — employment status
        never leaves `ACTIVE` anywhere in this API surface — with
        `is_currently_qualified` false and an `outstanding_lock_count` of zero."

        Design: Difficulty/compensating_invariant/lock_issue_remove_conserves_outstanding
        """
        ctx = setup_session_in_setup(asset_tag="A-LI-100")
        employee_id = ctx["primary"]["id"]
        assert get_employee(ctx["mgr"], employee_id)["outstanding_lock_count"] == 0

        lock = issue_lock(ctx["primary"], ctx["session"]["id"], "L-LI-1", "T-LI-1")
        apply_lock(ctx["primary"], lock["id"])
        assert get_employee(ctx["mgr"], employee_id)["outstanding_lock_count"] == 1, \
            "ISSUED and APPLIED both count as outstanding"

    def test_remove_returns_outstanding_count_to_zero(self, api):
        """PRD §3.4: "An employee's `outstanding_lock_count` is the number of
        their locks currently in `ISSUED` or `APPLIED`; it is recomputed whenever
        one of their locks is created or changes state."
        PRD §3.6: "Removal recomputes both the session's `applied_lock_count` and
        the owner's `outstanding_lock_count`."

        Design: Difficulty/compensating_invariant/lock_issue_remove_conserves_outstanding
        """
        ctx = setup_session_locked(asset_tag="A-LI-200", lock_no="L-LI-2",
                                   tag_no="T-LI-2")
        employee_id = ctx["primary"]["id"]
        assert get_employee(ctx["mgr"], employee_id)["outstanding_lock_count"] == 1

        removed = validate_success(api.remove_employee_lock(
            ctx["lock"]["id"],
            make_authorized_employee_headers(employee_id)))
        assert removed["status"] == "REMOVED"
        assert removed["removed_at"] is not None
        assert get_employee(ctx["mgr"], employee_id)["outstanding_lock_count"] == 0, \
            "the forward+compensating pair conserves the outstanding count"

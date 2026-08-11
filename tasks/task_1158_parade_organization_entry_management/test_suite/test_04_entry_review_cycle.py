"""Entry review cycle: revision loop, terminal lockdown, and ownership RBAC."""
import test_helpers as th
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, assert_entry,
)

COMMITTEE = th.make_committee_admin_headers()
ENTRANT1 = th.make_entrant_headers("entrant_1")


class TestRevisionLoop:
    """Difficulty: entry_revision_loop_cycle (two full cycles)."""

    def _two_cycles(self, api, parade_id, entry_id):
        for payload in ({"revision_notes": "Fix insurance docs"},
                        {"revision_notes": "Update participant count proof"}):
            get_success_data(api.request_revision(entry_id, payload, COMMITTEE))
            resubmit_payload = ({"estimated_participants": 130}
                                if "insurance" in payload["revision_notes"] else {})
            get_success_data(api.resubmit_entry(entry_id, resubmit_payload, ENTRANT1))
            get_success_data(api.start_review(entry_id, COMMITTEE))

    def test_revision_loop_returns_to_under_review_with_count_two(self, api):
        """PRD §3.3: "A revision request moves the entry to
        `REVISION_REQUESTED`, records the committee's `revision_notes`, and
        increments `revision_count` by one."
        PRD §3.3: "Resubmitting moves the entry from `REVISION_REQUESTED` back
        to `SUBMITTED` and is restricted to the owning entrant — a caller whose
        `X-User-ID` does not match the entry's `applicant_user_id` is refused
        with `ERR_FORBIDDEN` — and to an unfrozen parade."

        Design: Difficulty/non_linear_state_machine/entry_revision_loop_cycle
        """
        parade = th.create_parade(name="Loop Parade")
        entry = th.create_entry(parade["id"], "entrant_1", org_name="Loop Floats",
                                requested_category="FLOAT", estimated_participants=120)
        get_success_data(api.start_review(entry["id"], COMMITTEE))
        self._two_cycles(api, parade["id"], entry["id"])

        after = validate_success(api.get_entry(entry["id"], COMMITTEE))
        assert_entry(after)
        assert after["status"] == "UNDER_REVIEW", (
            f"the cycle must close back to UNDER_REVIEW, got {after['status']}"
        )
        assert after["revision_count"] == 2, (
            f"two revision requests must leave revision_count 2, got {after['revision_count']}"
        )

    def test_revision_resubmit_recomputes_fee(self, api):
        """PRD §3.3: "When the resubmission payload carries a fresh `org_name`
        or `estimated_participants`, those values replace the stored ones, and
        `fee_cents` is recomputed with the current category basis and the
        current logical clock for the late-surcharge branch."

        Design: Difficulty/non_linear_state_machine/entry_revision_loop_cycle
        """
        parade = th.create_parade(name="Loop Fee Parade")
        entry = th.create_entry(parade["id"], "entrant_1", org_name="Loop Floats",
                                requested_category="FLOAT", estimated_participants=120)
        get_success_data(api.start_review(entry["id"], COMMITTEE))
        get_success_data(
            api.request_revision(entry["id"], {"revision_notes": "Fix insurance docs"}, COMMITTEE)
        )
        resubmitted = validate_success(
            api.resubmit_entry(entry["id"], {"estimated_participants": 130}, ENTRANT1)
        )
        # FLOAT base 50000 + 50x300 + 80x200 = 81000; default clock is not late.
        assert resubmitted["fee_cents"] == 81000, (
            f"fee after resubmit at 130 participants must be 81000, got {resubmitted['fee_cents']}"
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["estimated_participants"] == 130


class TestEntryTerminalLockdown:

    def test_reject_before_review_invalid_state(self, api):
        """PRD §3.3: "Rejection moves the entry to `REJECTED`, a terminal
        state, and may carry an optional `reason`."
        PRD §2.10: "Specialized state failures carry their own codes — a frozen
        parade surfaces `ERR_EVENT_FROZEN`, an entry that is not approved
        surfaces `ERR_ENTRY_NOT_APPROVED`, a parade whose lineup is not
        published surfaces `ERR_LINEUP_NOT_PUBLISHED`, a lock attempted without
        a granted permit surfaces `ERR_PERMIT_NOT_GRANTED` — while all other
        from-state mismatches use the generic `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/entry_reject_before_review_rejected_invalid_state
        """
        parade = th.create_parade(name="State Parade")
        entry = th.create_entry(parade["id"], "entrant_1", org_name="Early Reject")
        resp = api.reject_entry(entry["id"], {}, COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_entry(entry["id"], COMMITTEE))
        assert after["status"] == "SUBMITTED"

    def test_withdrawn_entry_approve_rejected(self, api):
        """PRD §3.3: "Withdrawal likewise belongs to the owning entrant and is
        permitted from either `SUBMITTED` or `APPROVED`."
        PRD §3.3: "Either way the entry lands in `WITHDRAWN`, terminal."

        Design: Corner/state_machines/withdrawn_entry_approve_rejected_terminal_lockdown
        """
        parade = th.create_parade(name="Terminal Parade")
        entry = th.create_entry(parade["id"], "entrant_1", org_name="Quitters",
                                requested_category="WALKING_GROUP", estimated_participants=20)
        get_success_data(api.withdraw_entry(entry["id"], ENTRANT1))

        resp = api.approve_entry(entry["id"], {"assigned_category": "WALKING_GROUP"}, COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_entry(entry["id"], COMMITTEE))
        assert after["status"] == "WITHDRAWN"
        assert after["assigned_category"] is None


class TestEntryRbac:

    def test_entrant_cannot_approve_entry(self, api):
        """PRD §3.3: "Committee review begins when a `CommitteeAdmin` starts
        review, moving the entry from `SUBMITTED` to `UNDER_REVIEW`. From there
        the committee has three exits, each requiring the parade's posture to
        be unfrozen (`ERR_EVENT_FROZEN` applies otherwise)."
        PRD §2.1: "Once authenticated, a caller may only exercise the
        operations granted to their role, and certain operations additionally
        demand ownership of the target resource; a role or ownership failure is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/entrant_cannot_approve_entry_forbidden
        """
        parade = th.create_parade(name="RBAC Parade")
        entry = th.create_entry(parade["id"], "entrant_1", org_name="RBAC Band")
        get_success_data(api.start_review(entry["id"], COMMITTEE))

        resp = api.approve_entry(entry["id"], {"assigned_category": "BAND"}, ENTRANT1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        after = validate_success(api.get_entry(entry["id"], COMMITTEE))
        assert after["status"] == "UNDER_REVIEW"

    def test_other_entrant_cannot_resubmit(self, api):
        """PRD §3.3: "Resubmitting moves the entry from `REVISION_REQUESTED`
        back to `SUBMITTED` and is restricted to the owning entrant — a caller
        whose `X-User-ID` does not match the entry's `applicant_user_id` is
        refused with `ERR_FORBIDDEN` — and to an unfrozen parade."

        Design: Corner/rbac/entrant_cannot_touch_other_entrants_entry_forbidden
        """
        parade = th.create_parade(name="Owner Parade")
        entry = th.create_entry(parade["id"], "entrant_1", org_name="Owned Band")
        get_success_data(api.start_review(entry["id"], COMMITTEE))
        get_success_data(
            api.request_revision(entry["id"], {"revision_notes": "Fix roster"}, COMMITTEE)
        )

        resp = api.resubmit_entry(
            entry["id"], {"estimated_participants": 12}, th.make_entrant_headers("entrant_2")
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        after = validate_success(api.get_entry(entry["id"], COMMITTEE))
        assert after["status"] == "REVISION_REQUESTED"
        assert after["estimated_participants"] == 10, "the rejected resubmit must not mutate"


class TestUnauthenticated:

    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the
        operational capacity in which they act. A request missing either
        header, or presenting a role string the system does not declare, is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/request_missing_auth_headers_returns_unauthenticated
        """
        resp = api.create_parade(th.create_parade_payload(name="No Auth Parade"), headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

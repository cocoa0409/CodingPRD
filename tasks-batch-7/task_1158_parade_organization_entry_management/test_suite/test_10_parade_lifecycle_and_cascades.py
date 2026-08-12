"""Parade lifecycle: publish under OCC, completion gate, and the permit-revoke
freeze cascade."""
import test_helpers as th
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, assert_parade, assert_lineup_assignment, assert_script_item,
)

COMMITTEE = th.make_committee_admin_headers()
AGENCY = th.make_agency_reviewer_headers()
ENTRANT1 = th.make_entrant_headers("entrant_1")


class TestPublishLineup:

    def test_publish_with_fresh_version_succeeds_and_locks_scripts(self, api):
        """PRD §3.9: "Publishing the lineup moves the parade from `LOCKED` to
        `LINEUP_PUBLISHED`. The parade must be `OPERATIONAL` — a frozen parade
        is rejected with `ERR_EVENT_FROZEN` — at least one lineup assignment
        must stand in `TENTATIVE`, `CONFIRMED`, or `CHECKED_IN` status
        (`ERR_INVALID_STATE` when the running order is empty), and the request
        must carry `expected_parade_version` matching the parade's current
        `version` under the OCC rule of §2.9, with `ERR_STALE_VERSION`
        (HTTP 412) on a mismatch. Publication has a broadcast side effect:
        every announcer script item of the parade still in `APPROVED` status
        locks to `LOCKED` in the same write."

        Design: Corner/state_machines/publish_lineup_with_fresh_version_succeeds_and_locks_scripts
        """
        ctx = th.setup_locked_parade(name="Publish Parade")
        item = get_success_data(
            api.create_script_item(
                ctx["parade"]["id"],
                th.create_script_item_payload(item_type="SAFETY_ANNOUNCEMENT",
                                              sequence_index=1, duration_minutes=0.5),
                COMMITTEE,
            )
        )
        # Reopen path: item was created AFTER lock; approve it, then publish.
        get_success_data(api.approve_script_item(item["id"], COMMITTEE))
        locked = validate_success(api.get_parade(ctx["parade"]["id"], COMMITTEE))

        published = validate_success(
            api.publish_lineup(ctx["parade"]["id"],
                               {"expected_parade_version": locked["version"]}, COMMITTEE)
        )
        assert_parade(published)
        assert published["status"] == "LINEUP_PUBLISHED"
        assert published["version"] == locked["version"] + 1, (
            "publish increments the parade version by exactly one"
        )
        assert published["posture"] == "OPERATIONAL"

        item_after = validate_success(api.get_script_item(item["id"], COMMITTEE))
        assert item_after["status"] == "LOCKED", "publish locks APPROVED script items"

    def test_publish_with_stale_parade_version_returns_412(self, api):
        """PRD §2.9: "Publishing the lineup of a parade requires the request to
        carry `expected_parade_version`, holding the parade `version` the
        client last observed. If the parade's current `version` has advanced
        past that value — because another committee write has landed since the
        client read the parade — the publish is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from publishing
        over a parade state it never observed."

        Design: Corner/cross_cutting_layers/publish_lineup_with_stale_parade_version_returns_412
        """
        ctx = th.setup_locked_parade(name="OCC Parade")
        stale_version = ctx["lock_version"] - 1
        resp = api.publish_lineup(
            ctx["parade"]["id"], {"expected_parade_version": stale_version}, COMMITTEE
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        parade = validate_success(api.get_parade(ctx["parade"]["id"], COMMITTEE))
        assert parade["status"] == "LOCKED"


class TestCompleteGate:

    def test_complete_with_nonterminal_assignment_rejected(self, api):
        """PRD §3.9: "Completion moves the parade from `LINEUP_PUBLISHED` to
        `COMPLETED` once every lineup assignment of the parade has reached a
        terminal state — `RELEASED`, `PULLED`, or `NO_SHOW` — with
        `ERR_INVALID_STATE` while any assignment remains live."

        Design: Corner/state_machines/complete_with_nonterminal_assignment_rejected
        """
        ctx = th.setup_published_parade(name="Complete Parade")
        # The one assignment is still TENTATIVE — not terminal.
        resp = api.complete_parade(ctx["parade"]["id"], COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        parade = validate_success(api.get_parade(ctx["parade"]["id"], COMMITTEE))
        assert parade["status"] == "LINEUP_PUBLISHED"


class TestPermitRevokeCascade:
    """Difficulty: permit_revoke_freezes_event_pulls_lineup_cancels_scripts."""

    def _setup(self, api, name="Revoke Parade"):
        """OPERATIONAL parade; certified+paid FLOAT entry; CONFIRMED
        assignment in a capacity-3 lot; APPROVED ENTRY_INTRO item."""
        ctx = th.setup_operational_parade(name=name, staging_overrides={"name": "Lot A"})
        entry, _ = th.create_certified_float_entry(
            ctx["parade"]["id"], "entrant_1", inspector_id="insp_1",
            estimated_participants=120, org_name="Revoke Floats",
        )
        assignment = th.create_confirmed_assignment(
            ctx["parade"]["id"], entry["id"], ctx["staging"]["id"]
        )
        item = th.create_approved_intro_item(ctx["parade"]["id"], entry["id"])
        return ctx, entry, assignment, item

    def test_revoke_sets_permit_revoked_and_freezes_posture(self, api):
        """PRD §3.2: "Revocation is the most destructive agency action and
        fires a four-hop cascade. Hop one moves the permit from `GRANTED` to
        `REVOKED`. Hop two forces a posture recompute on the parade, which
        becomes `FROZEN`."

        Design: Difficulty/transitive_cascade/permit_revoke_freezes_event_pulls_lineup_cancels_scripts
        """
        ctx, _, _, _ = self._setup(api)
        permit = validate_success(api.revoke_permit(ctx["permit"]["id"], AGENCY))
        assert permit["status"] == "REVOKED", "hop 1: the permit itself revokes"

        parade = validate_success(api.get_parade(ctx["parade"]["id"], COMMITTEE))
        assert parade["posture"] == "FROZEN", (
            "hop 2: the permit mutation forces the posture recompute"
        )

    def test_revoke_pulls_assignment_releases_slot_cancels_intro(self, api):
        """PRD §3.2: "Hop three pulls every lineup assignment of the parade
        standing in `CONFIRMED` or `CHECKED_IN` to `PULLED`; `TENTATIVE`
        assignments are left in place, though they cannot be confirmed while
        the parade remains frozen. Hop four disposes of each pulled
        assignment's footprint: its staging slot is released (the lot's
        `reserved_slots` is recomputed) and every announcer script item of type
        `ENTRY_INTRO` naming the pulled assignment's entry, still in `APPROVED`
        status, is cancelled."

        Design: Difficulty/transitive_cascade/permit_revoke_freezes_event_pulls_lineup_cancels_scripts
        """
        ctx, _, assignment, item = self._setup(api, "Revoke Parade 2")
        validate_success(api.revoke_permit(ctx["permit"]["id"], AGENCY))

        assignment_after = validate_success(
            api.get_lineup_assignment(assignment["id"], COMMITTEE)
        )
        assert_lineup_assignment(assignment_after)
        assert assignment_after["status"] == "PULLED", (
            "hop 3: the posture flip pulls the CONFIRMED assignment"
        )

        staging_after = validate_success(api.get_staging_area(ctx["staging"]["id"], COMMITTEE))
        assert staging_after["reserved_slots"] == 0, "hop 4: the pull releases the slot"

        item_after = validate_success(api.get_script_item(item["id"], COMMITTEE))
        assert_script_item(item_after)
        assert item_after["status"] == "CANCELLED", (
            "hop 4: the pull cancels the entry's APPROVED ENTRY_INTRO item"
        )

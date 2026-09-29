"""Read-your-writes across a whole cascade, inside the triggering response.

Both tests read the answer out of the body of the call that caused it: the patch
that suspends a plastic license already reports the counter its cascade moved,
and the republication that clears a stale revocation pointer already reports the
cleared pointer. Only the rows the caller could not have seen are re-read.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import assert_field_values, assert_row_count, rows_of
from test_helpers.factories import trust_list_snapshot_payload
from test_helpers.fixtures import (
    create_active_credential,
    profile_version,
    publish_trust_list,
)
from test_helpers.test_users import ADMIN


class TestSuspensionCascadeVisibleImmediately:
    """The patch response carries the counter its own cascade decremented."""

    def test_the_patch_response_already_reports_the_cascaded_counter(self, api):
        """Suspending the plastic license suspends the digital credential it backs,
        appends one ledger entry and stales the published pointer - and the holder's
        active-credential counter is already zero in the patch's own body.

        PRD 3.4: "Setting `physical_credential_status` to `SUSPENDED` drives every
        credential of that holder in `ACTIVE` to `SUSPENDED` with `suspend_reason`
        `PHYSICAL_CREDENTIAL_SUSPENDED`, each appending a ledger entry with status
        `SUSPENDED` and reason `ADMIN_HOLD` and decrementing the holder's
        `active_credential_count` by 1."
        PRD 3.4: "Every ledger entry appended by any of those branches also marks
        the newest trust-list snapshot `revocation_pointer_stale` true, increments
        its `pending_delta_count` by 1 and increments the profile's
        `pending_republish_count` by 1."
        PRD 2.9: "Derived counters ... are maintained to agree at all times with the
        rows they count."

        Design: Corner/consistency_model/physical_credential_suspension_counters_visible_in_the_same_response
        """
        bundle = create_active_credential(api)
        publish_trust_list(api, bundle["profile"]["id"])

        patched = validate_success(
            api.patch_physical_credential(
                bundle["holder"]["id"],
                {"physical_credential_status": "SUSPENDED"},
                ADMIN,
            )
        )
        assert_field_values(
            patched,
            {
                "physical_credential_status": "SUSPENDED",
                "active_credential_count": 0,
            },
        )

        credential = validate_success(
            api.get_credential(bundle["credential"]["id"], ADMIN)
        )
        assert_field_values(
            credential,
            {
                "lifecycle_state": "SUSPENDED",
                "suspend_reason": "PHYSICAL_CREDENTIAL_SUSPENDED",
            },
        )

        entries = assert_row_count(
            api.list_revocation_entries(bundle["credential"]["id"], ADMIN), 1
        )
        assert_field_values(entries[0], {"status": "SUSPENDED", "reason": "ADMIN_HOLD"})

        snapshots = rows_of(
            api.list_profile_trust_list_snapshots(bundle["profile"]["id"], ADMIN)
        )
        assert_field_values(
            snapshots[0],
            {"revocation_pointer_stale": True, "pending_delta_count": 1},
        )

        profile = validate_success(
            api.get_interop_profile(bundle["profile"]["id"], ADMIN)
        )
        assert profile["pending_republish_count"] == 1


class TestRepublicationClearsThePointerImmediately:
    """The publishing response is itself the cleared pointer."""

    def test_the_republication_response_already_reports_a_fresh_pointer(self, api):
        """One revocation stales the first snapshot's pointer; the republication's
        own 201 body carries the next sequence, a fresh pointer, and a pointer
        sequence equal to the single entry that existed when it was published.

        PRD 3.1: "The first snapshot of a profile takes `snapshot_sequence` 1 and
        each later publication takes one more than the highest sequence already
        published under that profile."
        PRD 3.1: "sets `revocation_pointer_sequence` to the total number of
        revocation ledger entries in existence across the whole system at that
        moment - the pointer readers use to detect deltas they have missed. A fresh
        snapshot starts with `revocation_pointer_stale` false and
        `pending_delta_count` at zero. Publication also flips the `published` flag to
        true on every revocation entry appended before this moment, resets the
        profile's `pending_republish_count` to zero, and increments the profile's
        `version` by 1."

        Design: Corner/consistency_model/republication_clears_the_stale_pointer_inside_the_publishing_response
        """
        bundle = create_active_credential(api)
        profile_id = bundle["profile"]["id"]
        publish_trust_list(api, profile_id)

        validate_success(
            api.revoke_credential(
                bundle["credential"]["id"], {"reason": "ADMIN_HOLD"}, ADMIN
            )
        )

        republished = validate_success(
            api.create_trust_list_snapshot(
                trust_list_snapshot_payload(
                    profile_id,
                    profile_version(api, profile_id),
                    "2026-12-01T00:00:00Z",
                    "2027-04-01T00:00:00Z",
                ),
                ADMIN,
            ),
            201,
        )
        assert_field_values(
            republished,
            {
                "snapshot_sequence": 2,
                "revocation_pointer_stale": False,
                "pending_delta_count": 0,
                "revocation_pointer_sequence": 1,
            },
        )

        profile = validate_success(api.get_interop_profile(profile_id, ADMIN))
        assert profile["pending_republish_count"] == 0

        entries = assert_row_count(
            api.list_revocation_entries(bundle["credential"]["id"], ADMIN), 1
        )
        assert entries[0]["published"] is True

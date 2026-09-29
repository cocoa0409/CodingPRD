"""Half-open windows on a shared resource: what overlaps, what merely touches.

Both families here probe the same interval arithmetic from both sides of the
boundary in a single test, so an implementation that collapses "overlaps" into
"is not strictly after" cannot pass.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_CREDENTIAL_VALIDITY_OVERLAP,
    ERR_TRUST_LIST_WINDOW_GAP,
    ERR_TRUST_LIST_WINDOW_OVERLAP,
)
from test_helpers.assertions import (
    assert_field_values,
    assert_instant,
    assert_row_count,
)
from test_helpers.factories import credential_payload, trust_list_snapshot_payload
from test_helpers.fixtures import (
    create_attested_device,
    create_holder,
    create_profile,
    create_verified_session,
    device_version,
    profile_version,
    provision_credential,
    publish_trust_list,
)
from test_helpers.test_users import ADJUDICATOR, ADMIN


class TestCredentialValidityWindowsOnOneHandset:
    """Strict overlap is refused; touching at the endpoint is accepted."""

    @staticmethod
    def _handset_with_one_window(api):
        create_profile(api)
        holder = create_holder(api)
        device = create_attested_device(api, holder["id"])
        first_session = create_verified_session(api, holder["id"])
        incumbent = provision_credential(
            api,
            holder["id"],
            device["id"],
            first_session["id"],
            valid_from="2026-08-01T00:00:00Z",
            valid_until="2027-08-01T00:00:00Z",
        )
        second_session = create_verified_session(api, holder["id"])
        return holder, device, incumbent, second_session

    @staticmethod
    def _attempt(api, holder, device, session, valid_from, valid_until):
        return api.create_credential(
            credential_payload(
                holder["id"],
                device["id"],
                session["id"],
                device_version(api, device["id"]),
                valid_from=valid_from,
                valid_until=valid_until,
            ),
            ADJUDICATOR,
        )

    def test_a_strictly_overlapping_window_is_refused_but_adjacency_is_taken(self, api):
        """A window landing inside the incumbent's is rejected, while a window
        starting exactly at the incumbent's end is provisioned.

        PRD 2.12: "**Credential validity windows are half-open, and adjacency is
        allowed.** A credential's window runs from `valid_from` inclusive to
        `valid_until` exclusive. Two windows on the same handset conflict only if
        they strictly overlap - that is, when the new window's start is earlier
        than the other's end **and** the other's start is earlier than the new
        window's end. Windows that merely touch at an endpoint, where the new
        window's start equals the other's end, are accepted."

        Design: Difficulty/resource_temporal_overlap/credential_validity_windows_per_device_reject_overlap_accept_adjacency
        """
        holder, device, _, session = self._handset_with_one_window(api)

        overlapping = self._attempt(
            api,
            holder,
            device,
            session,
            "2026-12-01T00:00:00Z",
            "2027-02-01T00:00:00Z",
        )
        validate_error(overlapping, ERR_CREDENTIAL_VALIDITY_OVERLAP, 409)

        adjacent = validate_success(
            self._attempt(
                api,
                holder,
                device,
                session,
                "2027-08-01T00:00:00Z",
                "2028-08-01T00:00:00Z",
            ),
            201,
        )
        assert_field_values(
            adjacent,
            {
                "valid_from": "2027-08-01T00:00:00Z",
                "lifecycle_state": "PENDING_PROVISION",
            },
        )

    def test_only_the_accepted_window_became_a_row_and_consumed_its_session(self, api):
        """The refused attempt left no credential behind, and the accepted one
        consumed the proofing session it named.

        PRD 3.4: "The comparison set is every other credential on that same
        `device_id` whose `lifecycle_state` is `PENDING_PROVISION`, `ACTIVE` or
        `SUSPENDED`, **excluding** the credential named by
        `supersedes_credential_id`, which is expected to be displaced."

        Design: Difficulty/resource_temporal_overlap/credential_validity_windows_per_device_reject_overlap_accept_adjacency
        """
        holder, device, _, session = self._handset_with_one_window(api)

        self._attempt(
            api,
            holder,
            device,
            session,
            "2026-12-01T00:00:00Z",
            "2027-02-01T00:00:00Z",
        )
        self._attempt(
            api,
            holder,
            device,
            session,
            "2027-08-01T00:00:00Z",
            "2028-08-01T00:00:00Z",
        )

        assert_row_count(api.list_credentials(ADMIN, {"device_id": device["id"]}), 2)
        consumed = validate_success(api.get_proofing_session(session["id"], ADMIN))
        assert consumed["state"] == "CONSUMED"


class TestTrustListSnapshotsMustTileExactly:
    """Neither an overlap nor a gap is tolerated between consecutive snapshots."""

    @staticmethod
    def _publish_attempt(api, profile_id, effective_from, effective_until):
        return api.create_trust_list_snapshot(
            trust_list_snapshot_payload(
                profile_id,
                profile_version(api, profile_id),
                effective_from,
                effective_until,
            ),
            ADMIN,
        )

    def test_both_sides_of_the_boundary_are_named_distinctly(self, api):
        """Starting early is an overlap, starting late is a gap, and only the
        exact boundary publishes.

        PRD 3.1: "For the second and every later snapshot of the same profile,
        `effective_from` must equal the newest existing snapshot's
        `effective_until` precisely. A start strictly earlier than that boundary
        is an overlap and is rejected with `ERR_TRUST_LIST_WINDOW_OVERLAP`
        (HTTP 409); a start strictly later leaves readers with an uncovered
        stretch of time and is rejected with `ERR_TRUST_LIST_WINDOW_GAP`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/trust_list_snapshots_must_tile_exactly_rejecting_gap_and_overlap
        """
        profile = create_profile(api)
        publish_trust_list(
            api, profile["id"], "2026-08-01T00:00:00Z", "2026-12-01T00:00:00Z"
        )

        early = self._publish_attempt(
            api, profile["id"], "2026-11-01T00:00:00Z", "2027-04-01T00:00:00Z"
        )
        validate_error(early, ERR_TRUST_LIST_WINDOW_OVERLAP, 409)

        late = self._publish_attempt(
            api, profile["id"], "2026-12-02T00:00:00Z", "2027-04-01T00:00:00Z"
        )
        validate_error(late, ERR_TRUST_LIST_WINDOW_GAP, 422)

        exact = validate_success(
            self._publish_attempt(
                api, profile["id"], "2026-12-01T00:00:00Z", "2027-04-01T00:00:00Z"
            ),
            201,
        )
        assert_field_values(
            exact,
            {
                "snapshot_sequence": 2,
                "effective_from": "2026-12-01T00:00:00Z",
            },
        )

    def test_the_published_timeline_is_contiguous_in_sequence_order(self, api):
        """Only two snapshots exist and the first one's end is the second one's
        start, read back in sequence order.

        PRD 3.1: "Snapshots of a profile are listed back in `snapshot_sequence`
        ascending order and may be filtered on `revocation_pointer_stale` to
        find publications whose revocation pointer has since fallen behind."

        Design: Difficulty/resource_temporal_overlap/trust_list_snapshots_must_tile_exactly_rejecting_gap_and_overlap
        """
        profile = create_profile(api)
        publish_trust_list(
            api, profile["id"], "2026-08-01T00:00:00Z", "2026-12-01T00:00:00Z"
        )
        self._publish_attempt(
            api, profile["id"], "2026-11-01T00:00:00Z", "2027-04-01T00:00:00Z"
        )
        self._publish_attempt(
            api, profile["id"], "2026-12-02T00:00:00Z", "2027-04-01T00:00:00Z"
        )
        self._publish_attempt(
            api, profile["id"], "2026-12-01T00:00:00Z", "2027-04-01T00:00:00Z"
        )

        snapshots = assert_row_count(
            api.list_profile_trust_list_snapshots(profile["id"], ADMIN), 2
        )
        assert_instant(
            snapshots[0]["effective_until"], "2026-12-01T00:00:00Z", "effective_until"
        )
        assert_instant(
            snapshots[1]["effective_from"], "2026-12-01T00:00:00Z", "effective_from"
        )

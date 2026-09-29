"""Cascades whose later hops are caused by earlier hops, not by the request.

Each test walks the chain to its far end - a row in an aggregate the triggering
call never names - so an implementation that writes the near hops and stops is
caught at the terminal link.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import assert_field_values, assert_row_count, rows_of
from test_helpers.fixtures import (
    create_active_credential,
    create_presentation_ready_world,
    open_address_change,
    open_presentation_session,
    publish_trust_list,
    read_profile,
)
from test_helpers.test_users import ADMIN, PRIVACY_AUDITOR, make_holder_headers


class TestAddressChangeCascadeReachesTheOpenPresentation:
    """Five hops: order, delivery, sync axis, session abort, verifier counter."""

    @staticmethod
    def _world_with_an_open_presentation(api):
        world = create_presentation_ready_world(
            api,
            verifier_overrides={
                "organization_name": "Prairie Cellars",
                "category": "AGE_RESTRICTED_RETAIL",
                "purpose_scope": ["family_name", "age_over_21"],
                "retention_ceiling_days": 30,
            },
            reader_app_overrides={
                "app_identifier": "till-a",
                "certificate_serial": "SER-A1",
                "requested_elements": ["family_name", "age_over_21"],
                "base_rate_cents": 30,
            },
        )
        world["presentation"] = open_presentation_session(api, world, retention_days=5)
        return world

    def test_the_in_flight_presentation_is_aborted_and_logged(self, api):
        """The address change never mentions the presentation, yet the session is
        aborted, logged unbilled and removed from the verifier's open count.

        PRD 3.5: "4. Caused by hop 3: a credential entering `UPDATE_PENDING`
        aborts every presentation session against that credential whose state is
        `REQUESTED`, `CONSENT_PENDING` or `CONSENT_GRANTED` - each moves to
        `ABORTED` with `abort_reason` `CREDENTIAL_UPDATE_PENDING`."
        PRD 3.5: "5. Caused by hop 4: every aborted session appends a
        pseudonymised log entry with `outcome` `ABORTED`, `billed_amount_cents`
        zero and `billing_state` `UNBILLED`, and decrements the owning verifier's
        `open_session_count` by 1."

        Design: Difficulty/transitive_cascade/address_change_five_hop_cascade_aborts_open_presentation
        """
        world = self._world_with_an_open_presentation(api)
        presentation_id = world["presentation"]["id"]

        open_address_change(api, world["holder"]["id"])

        aborted = validate_success(
            api.get_presentation_session(presentation_id, ADMIN)
        )
        assert_field_values(
            aborted,
            {"state": "ABORTED", "abort_reason": "CREDENTIAL_UPDATE_PENDING"},
        )

        entries = assert_row_count(
            api.list_presentation_log_entries(presentation_id, PRIVACY_AUDITOR), 1
        )
        assert_field_values(
            entries[0],
            {
                "outcome": "ABORTED",
                "billing_state": "UNBILLED",
                "billed_amount_cents": 0,
            },
        )

        verifier = validate_success(api.get_verifier(world["verifier"]["id"], ADMIN))
        assert verifier["open_session_count"] == 0

    def test_the_order_and_its_delivery_stay_open_while_the_credential_desyncs(self, api):
        """Hops 1 to 3: an OPEN order, one PENDING delivery naming the credential,
        and the credential desynced without its lifecycle axis moving.

        PRD 3.5: "2. Caused by hop 1: one delivery is created in `PENDING` for
        **every** digital credential of that holder whose `lifecycle_state` is
        `ACTIVE` or `SUSPENDED`, in ascending `created_at` order of the
        credentials. Each delivery names its `update_order_id` and the
        `credential_id` it refreshes."

        Design: Difficulty/transitive_cascade/address_change_five_hop_cascade_aborts_open_presentation
        """
        world = self._world_with_an_open_presentation(api)

        order = open_address_change(api, world["holder"]["id"])
        assert_field_values(
            order,
            {
                "reason": "ADDRESS_CHANGE",
                "status": "OPEN",
                "delivery_count": 1,
                "delivered_count": 0,
                "target_address_version": 2,
                "closed_at": None,
            },
        )

        deliveries = assert_row_count(
            api.list_order_deliveries(order["id"], ADMIN), 1
        )
        assert_field_values(
            deliveries[0],
            {"status": "PENDING", "credential_id": world["credential"]["id"]},
        )

        credential = validate_success(
            api.get_credential(world["credential"]["id"], ADMIN)
        )
        assert_field_values(
            credential,
            {
                "lifecycle_state": "ACTIVE",
                "sync_state": "UPDATE_PENDING",
                "pending_update_count": 1,
            },
        )

        holder = validate_success(api.get_holder(world["holder"]["id"], ADMIN))
        assert_field_values(
            holder, {"address_version": 2, "address_line1": "402 Birch Lane"}
        )


class TestDeviceLossCascadeStalesTheTrustListPointer:
    """Three hops ending in two aggregates the report never names."""

    @staticmethod
    def _world_with_a_published_trust_list(api):
        bundle = create_active_credential(api)
        bundle["snapshot"] = publish_trust_list(api, bundle["profile"]["id"])
        return bundle

    def test_the_suspension_and_its_ledger_entry_are_written(self, api):
        """Hops 1 and 2: the credential is suspended for the loss, an unpublished
        ledger entry records it, and the holder's active count falls.

        PRD 3.4: "1. Every credential on that handset whose `lifecycle_state` is
        `ACTIVE` moves `ACTIVE` -> `SUSPENDED` with `suspend_reason`
        `DEVICE_LOST`."
        PRD 3.4: "2. Caused by hop 1: each such suspension appends a ledger entry
        with status `SUSPENDED` and reason `DEVICE_LOST`, and decrements the
        holder's `active_credential_count` by 1."

        Design: Difficulty/transitive_cascade/device_loss_three_hop_cascade_stales_trust_list_pointer
        """
        bundle = self._world_with_a_published_trust_list(api)

        lost = validate_success(
            api.report_device_lost(
                bundle["device"]["id"], make_holder_headers(bundle["holder"]["id"])
            )
        )
        assert_field_values(
            lost,
            {"state": "LOST_REPORTED", "lost_reported_at": "2026-08-01T00:00:00Z"},
        )

        credential = validate_success(
            api.get_credential(bundle["credential"]["id"], ADMIN)
        )
        assert_field_values(
            credential,
            {"lifecycle_state": "SUSPENDED", "suspend_reason": "DEVICE_LOST"},
        )

        entries = assert_row_count(
            api.list_revocation_entries(bundle["credential"]["id"], PRIVACY_AUDITOR), 1
        )
        assert_field_values(
            entries[0],
            {
                "sequence": 1,
                "status": "SUSPENDED",
                "reason": "DEVICE_LOST",
                "published": False,
            },
        )

        holder = validate_success(api.get_holder(bundle["holder"]["id"], ADMIN))
        assert holder["active_credential_count"] == 0

    def test_the_published_snapshot_and_its_profile_are_marked_behind(self, api):
        """Hop 3 crosses into the trust list and the profile, neither of which the
        report-lost call mentions.

        PRD 3.4: "3. Caused by hop 2: each appended entry sets the newest
        trust-list snapshot of the active profile to `revocation_pointer_stale`
        true, increments that snapshot's `pending_delta_count` by 1, and
        increments the profile's `pending_republish_count` by 1."

        Design: Difficulty/transitive_cascade/device_loss_three_hop_cascade_stales_trust_list_pointer
        """
        bundle = self._world_with_a_published_trust_list(api)

        api.report_device_lost(
            bundle["device"]["id"], make_holder_headers(bundle["holder"]["id"])
        )

        snapshots = rows_of(
            api.list_profile_trust_list_snapshots(bundle["profile"]["id"], ADMIN)
        )
        assert_field_values(
            snapshots[0],
            {"revocation_pointer_stale": True, "pending_delta_count": 1},
        )

        profile = read_profile(api, bundle["profile"]["id"])
        assert profile["pending_republish_count"] == 1

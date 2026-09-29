"""Outcomes that no single row can explain.

Each test here holds the acting row constant and moves the state of a
*different* row, so the only thing that can account for the change in outcome
is the cross-entity dependency the PRD declares.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_PHYSICAL_CREDENTIAL_INELIGIBLE
from test_helpers.assertions import (
    assert_credential_axes,
    assert_field_values,
    assert_row_count,
)
from test_helpers.fixtures import (
    create_attested_device,
    create_holder,
    create_presentation_ready_world,
    create_profile,
    create_verified_session,
    first_delivery_of,
    open_address_change,
    open_presentation_session,
    provision_credential,
)
from test_helpers.test_users import ADMIN, make_holder_headers


class TestActivationGatedByThePlasticCredentialState:
    """The credential never changes; the holder's plastic status decides."""

    @staticmethod
    def _provisioned(api):
        create_profile(api)
        holder = create_holder(api)
        device = create_attested_device(api, holder["id"])
        session = create_verified_session(api, holder["id"])
        credential = provision_credential(
            api, holder["id"], device["id"], session["id"]
        )
        return holder, credential

    def test_a_suspended_plastic_blocks_activation_and_leaves_no_mark(self, api):
        """Suspending the plastic makes the resident's own activation ineligible
        and the credential stays exactly where it was.

        PRD 3.2: "**Only `VALID` confers eligibility, and eligibility is
        re-checked at four separate points.** The physical-credential gate
        requires both that `physical_credential_status` reads `VALID` and that
        `physical_credential_expires_on` falls strictly later than the current
        logical date, and it is evaluated when a proofing session is opened,
        when a proofing session is submitted for adjudication, when a credential
        is provisioned, and when a credential is activated. In all four the
        rejection is `ERR_PHYSICAL_CREDENTIAL_INELIGIBLE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/credential_activation_gated_by_holder_physical_credential_state
        """
        holder, credential = self._provisioned(api)

        validate_success(
            api.patch_physical_credential(
                holder["id"], {"physical_credential_status": "SUSPENDED"}, ADMIN
            )
        )

        refused = api.activate_credential(
            credential["id"],
            {"device_unlock_proof": "BIOMETRIC"},
            make_holder_headers(holder["id"]),
        )
        validate_error(refused, ERR_PHYSICAL_CREDENTIAL_INELIGIBLE, 422)

        unchanged = validate_success(api.get_credential(credential["id"], ADMIN))
        assert unchanged["lifecycle_state"] == "PENDING_PROVISION"
        assert unchanged["activated_at"] is None

    def test_restoring_the_plastic_lets_the_same_request_through(self, api):
        """The identical activation call succeeds once the plastic reads VALID
        again, and it records the handset's protection method.

        PRD 3.4: "A successful activation records `activated_at` as the current
        logical instant, copies the handset's `protection_method` into
        `protection_method_at_activation` - the value every later consent must
        reproduce - increments the holder's `active_credential_count` by 1, and
        increments the credential's `version` by 1. Notably, activation appends
        **no** revocation ledger entry"

        Design: Difficulty/cross_entity_state_dependency/credential_activation_gated_by_holder_physical_credential_state
        """
        holder, credential = self._provisioned(api)
        holder_headers = make_holder_headers(holder["id"])

        validate_success(
            api.patch_physical_credential(
                holder["id"], {"physical_credential_status": "SUSPENDED"}, ADMIN
            )
        )
        api.activate_credential(
            credential["id"], {"device_unlock_proof": "BIOMETRIC"}, holder_headers
        )

        restored = validate_success(
            api.patch_physical_credential(
                holder["id"], {"physical_credential_status": "VALID"}, ADMIN
            )
        )
        assert restored["physical_credential_status"] == "VALID"

        activated = validate_success(
            api.activate_credential(
                credential["id"], {"device_unlock_proof": "BIOMETRIC"}, holder_headers
            )
        )
        assert_field_values(
            activated,
            {
                "lifecycle_state": "ACTIVE",
                "protection_method_at_activation": "BIOMETRIC",
            },
        )

        refreshed_holder = validate_success(api.get_holder(holder["id"], ADMIN))
        assert refreshed_holder["active_credential_count"] == 1
        assert_row_count(api.list_revocation_entries(credential["id"], ADMIN), 0)


class TestPresentationForkDecidedByTheCredentialSyncAxis:
    """The lifecycle axis stays ACTIVE throughout; only the sync axis forks."""

    @staticmethod
    def _out_of_sync_world(api):
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
        order = open_address_change(api, world["holder"]["id"])
        world["order"] = order
        return world

    def test_an_update_pending_credential_blocks_the_presentation_by_policy(self, api):
        """A credential whose payload is behind forks the session to
        BLOCKED_BY_POLICY with nothing billed and no open session.

        PRD 3.8: "If instead the `sync_state` is anything other than `IN_SYNC`,
        or the staleness exceeds the freshness window, the session instead moves
        `REQUESTED` -> `BLOCKED_BY_POLICY`: a log entry is appended with
        `outcome` `BLOCKED_BY_POLICY`, `disclosed_element_count` zero,
        `billed_amount_cents` zero and `billing_state` `UNBILLED`;
        `open_session_count` is **not** incremented because the session never
        opened; nothing is billed"

        Design: Difficulty/cross_entity_state_dependency/presentation_fork_decided_by_credential_sync_axis
        """
        world = self._out_of_sync_world(api)

        blocked = open_presentation_session(api, world)
        assert_field_values(
            blocked,
            {
                "state": "BLOCKED_BY_POLICY",
                "billing_state": "UNBILLED",
                "billed_amount_cents": 0,
            },
        )

        verifier = validate_success(api.get_verifier(world["verifier"]["id"], ADMIN))
        assert verifier["open_session_count"] == 0

        entries = assert_row_count(
            api.list_presentation_log_entries(blocked["id"], ADMIN), 1
        )
        assert entries[0]["outcome"] == "BLOCKED_BY_POLICY"

    def test_confirming_the_delivery_flips_the_very_same_request_to_consent(self, api):
        """Once the outstanding delivery lands the credential is back IN_SYNC
        and an identical request forks the other way.

        PRD 3.5: "when that leaves no outstanding delivery - that is, when the
        count had been exactly 1 - the credential's sync axis moves
        `UPDATE_PENDING` -> `IN_SYNC`"
        PRD 3.8: "the session moves `REQUESTED` -> `CONSENT_PENDING` when the
        credential's `sync_state` is `IN_SYNC` **and** its replayed revocation
        staleness is at most the profile's `revocation_freshness_seconds`; the
        owning verifier's `open_session_count` increments by 1"

        Design: Difficulty/cross_entity_state_dependency/presentation_fork_decided_by_credential_sync_axis
        """
        world = self._out_of_sync_world(api)
        open_presentation_session(api, world)

        delivery = first_delivery_of(api, world["order"]["id"])
        delivered = validate_success(
            api.deliver_update(
                delivery["id"], {"device_receipt_token": "receipt-a1"}, ADMIN
            )
        )
        assert delivered["status"] == "DELIVERED"

        opened = open_presentation_session(api, world)
        assert opened["state"] == "CONSENT_PENDING"

        verifier = validate_success(api.get_verifier(world["verifier"]["id"], ADMIN))
        assert verifier["open_session_count"] == 1

        credential = validate_success(
            api.get_credential(world["credential"]["id"], ADMIN)
        )
        assert_credential_axes(credential, "ACTIVE", "IN_SYNC")

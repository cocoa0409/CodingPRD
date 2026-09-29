"""What each endpoint returns, and what it fans out to on the way.

A partial patch that touches only what it names, a renewal that both rewrites a
window and raises a propagation order, an address change that fans out one push
per live credential, and a compensating action refused because there is nothing
to compensate.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ERR_BILLING_ALREADY_VOIDED
from test_helpers.assertions import assert_cents, assert_field_values
from test_helpers.fixtures import (
    activate_credential,
    create_active_credential,
    create_attested_device,
    create_holder,
    create_presentation_ready_world,
    create_profile,
    create_verified_session,
    open_address_change,
    open_presentation_session,
    provision_credential,
)
from test_helpers.test_users import (
    ADJUDICATOR,
    ADMIN,
    PRIVACY_AUDITOR,
)

_SECOND_EVIDENCE = [
    {
        "evidence_type": "DOCUMENT_SCAN",
        "quality": "STRONG",
        "captured_at": "2026-07-25T09:00:00Z",
        "source_reference": "doc-2",
    },
    {
        "evidence_type": "BIOMETRIC_MATCH",
        "quality": "STRONG",
        "captured_at": "2026-07-25T09:05:00Z",
        "source_reference": "bio-2",
    },
]


class TestPhysicalCredentialPatch:
    """The patch is a partial update over three independent fields."""

    def test_patching_only_the_expiry_leaves_the_other_two_fields_alone(self, api):
        """Supplying the expiry date alone rewrites that date and bumps the
        holder's version, while the status, the restrictions and the address
        version stay exactly where they were - and because no restriction codes
        were supplied, no propagation order is raised.

        PRD 3.4: "The `SystemAdmin` may supply any combination of
        `physical_credential_status`, `physical_credential_expires_on` and
        `restriction_codes`; the holder's `version` increments by 1 in every
        case."
        PRD 3.4: "Supplying `restriction_codes` opens a propagation order with
        `reason` `RESTRICTION_CHANGE` whose `target_address_version` is the
        holder's unchanged `address_version`, running the identical five-hop
        cascade described in 3.5."

        Design: Corner/endpoints/physical_credential_patch_updates_only_the_supplied_field
        """
        create_profile(api)
        holder = create_holder(api)

        patched = validate_success(
            api.patch_physical_credential(
                holder["id"],
                {"physical_credential_expires_on": "2034-06-30"},
                ADMIN,
            )
        )
        assert_field_values(
            patched,
            {
                "physical_credential_expires_on": "2034-06-30",
                "physical_credential_status": "VALID",
                "restriction_codes": [],
                "address_version": 1,
                "version": 2,
            },
        )

        _, meta = validate_paginated(
            api.list_update_orders(ADMIN, {"holder_id": holder["id"]})
        )
        assert meta["total_count"] == 0


class TestCredentialRenewal:
    """Renewal is one call with two outcomes: a new window and a new order."""

    def test_renewal_rewrites_the_window_and_raises_a_renewal_order(self, api):
        """The extended `valid_until` comes back on the credential, the sync axis
        moves to UPDATE_PENDING, and the RENEWAL order that carries the new
        payload pins the address version it did not change.

        PRD 3.5: "A `CredentialAdjudicator` renewing a credential - which
        requires the credential to be `ACTIVE`, failing with `ERR_INVALID_STATE`
        otherwise - supplies `new_valid_until`, which overwrites the credential's
        `valid_until` and increments the credential's `version` by 1, and opens an
        order with `reason` `RENEWAL`."
        PRD 3.5: "for a renewal and for a restriction change it is the holder's
        `address_version` unchanged, because neither of those events alters the
        address."

        Design: Corner/endpoints/renew_extends_the_window_and_opens_a_renewal_order
        """
        bundle = create_active_credential(api)

        renewed = validate_success(
            api.renew_credential(
                bundle["credential"]["id"],
                {"new_valid_until": "2036-07-01T00:00:00Z"},
                ADJUDICATOR,
            )
        )
        assert_field_values(
            renewed,
            {
                "valid_until": "2036-07-01T00:00:00Z",
                "lifecycle_state": "ACTIVE",
                "sync_state": "UPDATE_PENDING",
                "pending_update_count": 1,
            },
        )

        orders, order_meta = validate_paginated(
            api.list_update_orders(
                ADMIN,
                {"holder_id": bundle["holder"]["id"], "reason": "RENEWAL"},
            )
        )
        assert order_meta["total_count"] == 1
        assert_field_values(
            orders[0],
            {
                "status": "OPEN",
                "delivery_count": 1,
                "target_address_version": 1,
            },
        )

        deliveries, delivery_meta = validate_paginated(
            api.list_credential_deliveries(bundle["credential"]["id"], ADMIN)
        )
        assert delivery_meta["total_count"] == 1
        assert deliveries[0]["status"] == "PENDING"


class TestAddressChangeFanOut:
    """One address change, one delivery per live credential - not one in total."""

    @staticmethod
    def _holder_with_two_active_credentials(api):
        create_profile(api)
        holder = create_holder(api)
        device = create_attested_device(api, holder["id"])

        first_session = create_verified_session(api, holder["id"])
        first = provision_credential(
            api,
            holder["id"],
            device["id"],
            first_session["id"],
            valid_from="2026-08-01T00:00:00Z",
            valid_until="2027-08-01T00:00:00Z",
        )
        activate_credential(api, first["id"], holder["id"])

        second_session = create_verified_session(api, holder["id"], _SECOND_EVIDENCE)
        second = provision_credential(
            api,
            holder["id"],
            device["id"],
            second_session["id"],
            valid_from="2027-08-01T00:00:00Z",
            valid_until="2028-08-01T00:00:00Z",
        )
        activate_credential(api, second["id"], holder["id"])
        return holder, first, second

    def test_two_live_credentials_receive_one_delivery_each(self, api):
        """Both windows are live on the same handset, so the single address change
        opens two deliveries and desyncs both credentials - an implementation that
        pushes only to the newest one reports a delivery count of 1.

        PRD 3.5: "2. Caused by hop 1: one delivery is created in `PENDING` for
        **every** digital credential of that holder whose `lifecycle_state` is
        `ACTIVE` or `SUSPENDED`, in ascending `created_at` order of the
        credentials. Each delivery names its `update_order_id` and the
        `credential_id` it refreshes."
        PRD 3.5: "For an address change it is the holder's `address_version`
        **after** the increment"

        Design: Corner/endpoints/address_change_opens_one_delivery_per_live_credential
        """
        holder, first, second = self._holder_with_two_active_credentials(api)

        order = open_address_change(api, holder["id"], address_line1="18 Cedar Row")
        assert_field_values(
            order,
            {
                "status": "OPEN",
                "reason": "ADDRESS_CHANGE",
                "delivery_count": 2,
                "delivered_count": 0,
                "failed_count": 0,
                "target_address_version": 2,
            },
        )

        deliveries, delivery_meta = validate_paginated(
            api.list_order_deliveries(order["id"], ADMIN)
        )
        assert delivery_meta["total_count"] == 2
        assert {row["credential_id"] for row in deliveries} == {
            first["id"],
            second["id"],
        }
        assert {row["status"] for row in deliveries} == {"PENDING"}

        _, pending_meta = validate_paginated(
            api.list_credentials(
                ADMIN,
                {"holder_id": holder["id"], "sync_state": "UPDATE_PENDING"},
            )
        )
        assert pending_meta["total_count"] == 2


class TestVoidBillingPrecondition:
    """The compensating action refuses when there is nothing to compensate."""

    def test_voiding_a_session_that_was_never_billed_is_refused(self, api):
        """A session still waiting on consent has never been billed, so the void
        is refused and every money field on the verifier stays at zero.

        PRD 3.9: "It is available only when the session's `billing_state` is
        `BILLED`; a session that was never billed or whose billing has already
        been voided is rejected with `ERR_BILLING_ALREADY_VOIDED` (HTTP 409)."

        Design: Corner/endpoints/void_billing_on_an_unbilled_session_is_rejected
        """
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
        session = open_presentation_session(
            api,
            world,
            purpose="age check at till",
            requested_elements=["family_name", "age_over_21"],
            handset_handling="NO_SURRENDER",
            retention_days=7,
        )

        validate_error(
            api.void_presentation_billing(session["id"], PRIVACY_AUDITOR),
            ERR_BILLING_ALREADY_VOIDED,
            409,
        )

        stored = validate_success(
            api.get_presentation_session(session["id"], PRIVACY_AUDITOR)
        )
        assert_field_values(
            stored, {"billing_state": "UNBILLED", "state": "CONSENT_PENDING"}
        )

        verifier = validate_success(api.get_verifier(world["verifier"]["id"], ADMIN))
        assert_cents(verifier, "credited_amount_cents", 0)
        assert_cents(verifier, "billable_query_balance_cents", 0)

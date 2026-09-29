"""The concurrency guards, and a privacy threshold that accumulates.

Two optimistic-concurrency chains refuse a write built on a stale parent read and
then accept the identical body at the current version; a third walks both parent
version counters write by write; and the last shows that the exposure threshold
is cumulative across the log rather than judged one presentation at a time.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_STALE_DEVICE_VERSION,
    ERR_STALE_INTEROP_VERSION,
)
from test_helpers.assertions import assert_cents, assert_field_values
from test_helpers.constants import CORE_ELEMENTS
from test_helpers.factories import (
    credential_payload,
    trust_list_snapshot_payload,
)
from test_helpers.fixtures import (
    attest_device,
    create_attested_device,
    create_holder,
    create_presentation_ready_world,
    create_profile,
    create_verified_session,
    device_version,
    disclose,
    grant_consent,
    open_presentation_session,
    profile_version,
    register_device,
)
from test_helpers.test_users import (
    ADJUDICATOR,
    ADMIN,
    PRIVACY_AUDITOR,
)

_RETAIL_VERIFIER = {
    "organization_name": "Prairie Cellars",
    "category": "AGE_RESTRICTED_RETAIL",
    "purpose_scope": ["family_name", "age_over_21"],
    "retention_ceiling_days": 30,
}


class TestDeviceConcurrencyGuard:
    """Provisioning echoes the handset version it was built on."""

    def test_a_provisioning_on_a_stale_handset_read_is_refused_then_accepted(
        self, api
    ):
        """The guard rejects the version the client held before attestation, writes
        no credential, and then accepts the identical body at the current version -
        after which the handset itself has advanced one more step.

        PRD 2.7: "Provisioning a digital credential requires
        `expected_device_version` as a non-optional field of the request. Its value
        must equal the current `version` of the handset named by `device_id`. If the
        handset's `version` has advanced since the client last read it - because it
        was attested, bound to another credential, reported lost, recovered, or
        wiped in the interim - the provisioning is rejected with
        `ERR_STALE_DEVICE_VERSION` (HTTP 412)."
        PRD 3.4: "the handset moves `ATTESTED -> BOUND` ... while its
        `active_binding_count` increments by 1; and the handset's `version`
        increments by 1."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_device_version_returns_stale_device_version
        """
        create_profile(api)
        holder = create_holder(api)
        device = create_attested_device(api, holder["id"])
        session = create_verified_session(api, holder["id"])

        current = device_version(api, device["id"])
        assert current == 2

        refused = api.create_credential(
            credential_payload(
                holder["id"], device["id"], session["id"], current - 1
            ),
            ADJUDICATOR,
        )
        validate_error(refused, ERR_STALE_DEVICE_VERSION, 412)

        _, meta = validate_paginated(
            api.list_credentials(ADJUDICATOR, {"holder_id": holder["id"]})
        )
        assert meta["total_count"] == 0

        validate_success(
            api.create_credential(
                credential_payload(
                    holder["id"], device["id"], session["id"], current
                ),
                ADJUDICATOR,
            ),
            201,
        )

        stored = validate_success(api.get_device(device["id"], ADMIN))
        assert_field_values(stored, {"state": "BOUND", "version": 3})


class TestInteropProfileConcurrencyGuard:
    """Publication echoes the profile version it was derived from."""

    def test_a_publication_on_a_stale_profile_read_is_refused_then_accepted(
        self, api
    ):
        """A profile at version 1 has no version 0 to publish from, so the stale
        attempt leaves the snapshot list empty; the retry at the current version
        takes sequence 1 and bumps the profile.

        PRD 2.7: "Publishing a trust-list snapshot requires
        `expected_interop_profile_version` as a non-optional field of the request.
        Its value must equal the current `version` of the interoperability profile
        named by `interop_profile_id`. A mismatch is rejected with
        `ERR_STALE_INTEROP_VERSION` (HTTP 412)."
        PRD 3.1: "The first snapshot of a profile takes `snapshot_sequence` 1 ... A
        fresh snapshot starts with `revocation_pointer_stale` false and
        `pending_delta_count` at zero ... and increments the profile's `version` by
        1."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_interop_profile_version_returns_stale_interop_version
        """
        profile = create_profile(api)
        current = profile_version(api, profile["id"])
        assert current == 1

        refused = api.create_trust_list_snapshot(
            trust_list_snapshot_payload(profile["id"], current - 1), ADMIN
        )
        validate_error(refused, ERR_STALE_INTEROP_VERSION, 412)

        _, meta = validate_paginated(
            api.list_profile_trust_list_snapshots(profile["id"], ADMIN)
        )
        assert meta["total_count"] == 0

        published = validate_success(
            api.create_trust_list_snapshot(
                trust_list_snapshot_payload(profile["id"], current), ADMIN
            ),
            201,
        )
        assert_field_values(
            published,
            {"snapshot_sequence": 1, "revocation_pointer_stale": False},
        )

        stored = validate_success(api.get_interop_profile(profile["id"], ADMIN))
        assert stored["version"] == 2


class TestParentVersionChains:
    """Every write on a parent moves its version, cascade writes included."""

    def test_both_parent_version_counters_advance_on_every_write(self, api):
        """The handset reads 1 at registration, 2 after attestation and 3 after a
        provisioning it was never the direct target of; the profile reads 2 after
        the publication that quoted version 1.

        PRD 2.4: "Whenever a row changes, its `updated_at` is refreshed to the
        current logical instant and its `version` increments by 1 - including when
        the row changed only because it was the target of another operation's
        cascade."
        PRD 3.3: "Both branches record `attestation_result` and
        `secure_element_grade` and both increment the handset's `version` by 1"
        PRD 3.4: "What `active_binding_count` counts is the credentials on that
        handset in `PENDING_PROVISION`, `ACTIVE` or `SUSPENDED`."

        Design: Corner/cross_cutting_complexity_layers/parent_version_increments_on_every_write_along_both_occ_chains
        """
        profile = create_profile(api)
        holder = create_holder(api)
        session = create_verified_session(api, holder["id"])

        device = register_device(api, holder["id"])
        assert device["version"] == 1

        attested = attest_device(api, device["id"])
        assert attested["version"] == 2

        validate_success(
            api.create_credential(
                credential_payload(
                    holder["id"], device["id"], session["id"], attested["version"]
                ),
                ADJUDICATOR,
            ),
            201,
        )

        stored_device = validate_success(api.get_device(device["id"], ADMIN))
        assert_field_values(
            stored_device, {"version": 3, "active_binding_count": 1}
        )

        validate_success(
            api.create_trust_list_snapshot(
                trust_list_snapshot_payload(profile["id"], 1), ADMIN
            ),
            201,
        )

        stored_profile = validate_success(
            api.get_interop_profile(profile["id"], ADMIN)
        )
        assert stored_profile["version"] == 2


class TestCumulativeExposureThreshold:
    """The privacy index accumulates over the log, not over one presentation."""

    def test_the_second_over_ask_lands_the_index_on_exactly_sixty(self, api):
        """Nine withheld elements score 54 and leave the organisation approved; one
        more withheld element on a second disclosure puts the index on exactly 60,
        which the inclusive comparison turns into probation and a first strike.

        PRD 3.8: "in the `ROUTINE` context it is the intersection of the reader
        application's own `requested_elements` with the owning verifier's
        `purpose_scope` ... `withheld_elements` contains every requested element
        that is **not** in the allow-list ... `excess_element_count` is the number of
        withheld elements."
        PRD 3.9: "**Excess elements**: the sum of `excess_element_count` across all
        entries in the window, weighted 6 points each."
        PRD 3.9: "Otherwise an index of 60 or more drives an `APPROVED` verifier to
        `PROBATION` and increments `probation_strike_count` by 1. Both comparisons
        are inclusive at the boundary: an index of exactly 60 trips probation while
        59 does not"

        Design: Corner/cross_cutting_complexity_layers/cumulative_exposure_at_exactly_sixty_trips_probation
        """
        world = create_presentation_ready_world(
            api,
            verifier_overrides=dict(_RETAIL_VERIFIER),
            reader_app_overrides={
                "app_identifier": "till-a",
                "certificate_serial": "SER-A1",
                "requested_elements": list(CORE_ELEMENTS),
                "base_rate_cents": 30,
            },
        )
        verifier_id = world["verifier"]["id"]

        first = open_presentation_session(
            api,
            world,
            context="ROUTINE",
            purpose="over-asking till read",
            requested_elements=list(CORE_ELEMENTS),
            handset_handling="NO_SURRENDER",
            retention_days=7,
        )
        assert_field_values(
            first,
            {
                "excess_element_count": 9,
                "minimized_elements": ["family_name", "age_over_21"],
            },
        )
        grant_consent(api, first["id"], world["holder"]["id"])
        disclose(api, first["id"], verifier_id)

        after_first = validate_success(api.get_verifier(verifier_id, ADMIN))
        assert_field_values(
            after_first,
            {
                "exposure_index": 54,
                "trust_status": "APPROVED",
                "probation_strike_count": 0,
            },
        )

        second = open_presentation_session(
            api,
            world,
            context="ROUTINE",
            purpose="one element too many",
            requested_elements=["family_name", "age_over_21", "birth_date"],
            handset_handling="NO_SURRENDER",
            retention_days=7,
        )
        assert second["excess_element_count"] == 1
        grant_consent(api, second["id"], world["holder"]["id"])
        disclose(api, second["id"], verifier_id)

        after_second = validate_success(api.get_verifier(verifier_id, ADMIN))
        assert_field_values(
            after_second,
            {
                "exposure_index": 60,
                "trust_status": "PROBATION",
                "probation_strike_count": 1,
            },
        )
        assert_cents(after_second, "billable_query_balance_cents", 60)

        report = validate_success(api.get_exposure_index(verifier_id, PRIVACY_AUDITOR))
        assert_field_values(
            report,
            {"rolling_window_index": 60, "rolling_window_entry_count": 2},
        )

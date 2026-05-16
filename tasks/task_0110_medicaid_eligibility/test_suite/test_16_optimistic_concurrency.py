"""Optimistic concurrency control on PATCH endpoints — PRD §2.7.

Two PATCH endpoints accept an optional `version` field: PATCH /households
and PATCH /households/{id}/applications/{id}. When version is supplied
and does not match the current row, the patch is rejected with
ERR_VERSION_CONFLICT (HTTP 409).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    create_application,
    create_household,
    create_state_policy,
    patch_application_payload,
    patch_household_payload,
    setup_basic_household,
    validate_error,
    validate_success,
)


class TestHouseholdPatchOCC:

    def test_patch_household_with_matching_version_increments_version(
            self, api, intake_worker_headers):
        """PRD §2.4: "version is incremented by exactly 1 on every
        successful mutation."
        PRD §2.7: "If version is supplied and matches the current
        version of the target resource, the patch is applied and
        version is incremented."

        Claim: a PATCH supplying the current version succeeds and the
        returned resource's version == previous + 1.
        """
        _sp, household, _ = setup_basic_household()
        old_v = household["version"]
        res = api.patch_household(
            household["id"],
            patch_household_payload(
                address_line="456 Other St", version=old_v,
            ),
            intake_worker_headers,
        )
        data = validate_success(res)
        assert data["version"] == old_v + 1, (
            f"PATCH success must bump version by 1 per PRD §2.4; "
            f"got version={data['version']} (was {old_v})"
        )

    def test_patch_household_with_stale_version_conflict(
            self, api, intake_worker_headers):
        """PRD §2.7: "If version is supplied and does not match, the
        patch is rejected with ERR_VERSION_CONFLICT (HTTP 409); the
        client must refetch the resource and retry against the new
        version."

        Claim: PATCH with an old version that no longer matches →
        ERR_VERSION_CONFLICT.
        """
        _sp, household, _ = setup_basic_household()
        old_v = household["version"]
        # First patch — version moves forward.
        api.patch_household(
            household["id"],
            patch_household_payload(
                address_line="456 Other St", version=old_v,
            ),
            intake_worker_headers,
        )
        # Second patch with the old (now-stale) version.
        res = api.patch_household(
            household["id"],
            patch_household_payload(
                address_line="789 Stale St", version=old_v,
            ),
            intake_worker_headers,
        )
        validate_error(res, "ERR_VERSION_CONFLICT")

    def test_patch_household_without_version_does_not_perform_check(
            self, api, intake_worker_headers):
        """PRD §2.7: "If version is omitted from the body, the system
        does not perform a stale-write check and applies the patch
        unconditionally (overwriting whatever the current row holds)."

        Claim: PATCH without `version` field succeeds even when the
        client's snapshot is stale.
        """
        _sp, household, _ = setup_basic_household()
        # Bump version once first.
        api.patch_household(
            household["id"],
            patch_household_payload(
                address_line="456 Other St", version=household["version"],
            ),
            intake_worker_headers,
        )
        # Now PATCH again without version — must succeed.
        res = api.patch_household(
            household["id"],
            patch_household_payload(address_line="789 No-Version St"),
            intake_worker_headers,
        )
        validate_success(res)


class TestApplicationPatchOCC:

    def test_patch_application_with_stale_version_conflict(
            self, api, intake_worker_headers):
        """PRD §2.7: "Two mutating endpoints accept an optimistic
        concurrency control token: the PATCH endpoints on Household
        and on Application."

        Claim: PATCH on the application with a stale version →
        ERR_VERSION_CONFLICT.
        """
        _sp, household, _ = setup_basic_household()
        application = create_application(household=household)
        old_v = application["version"]
        # Mutate once.
        api.patch_application(
            household["id"], application["id"],
            patch_application_payload(program="MAGI_CHILD", version=old_v),
            intake_worker_headers,
        )
        # Stale version on the second.
        res = api.patch_application(
            household["id"], application["id"],
            patch_application_payload(
                program="MAGI_ADULT", version=old_v,
            ),
            intake_worker_headers,
        )
        validate_error(res, "ERR_VERSION_CONFLICT")

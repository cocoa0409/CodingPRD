"""Veteran onboarding, Post-9/11 tier, and dependent rules — PRD §3.1, §3.2."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_dependent,
    assert_veteran,
    assert_version_incremented_by,
    create_dependent,
    create_dependent_payload,
    create_veteran,
    create_veteran_payload,
    current_clock,
    delete_dependent,
    get_veteran,
    iso_utc,
    make_veteran_headers,
    patch_veteran_payload,
    utc_midnight,
    validate_error,
    validate_success,
)
from datetime import timedelta


class TestVeteranCreation:

    def test_create_veteran_defaults(self, api):
        """PRD §3.1: "A successful registration returns a 201 with the
        newly minted record, whose combined_rating defaults to 0 (no
        service-connected claims yet), whose months_entitlement_used
        defaults to 0.00, and whose post_911_eligibility_tier is
        computed immediately from the supplied duty days."
        """
        resp = api.create_veteran(
            create_veteran_payload(
                aggregate_active_duty_days=1100,
                discharge_status="HONORABLE",
            ),
            TEST_USERS["va_clerk_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_veteran(data)
        assert data["combined_rating"] == 0
        assert data["months_entitlement_used"] == 0 or \
            data["months_entitlement_used"] == 0.0
        # 1100 days -> tier 100 (>= 1095) per PRD §3.1.
        assert data["post_911_eligibility_tier"] == 100
        assert data["version"] == 1, (
            f"PRD §2.4: 'version starts at 1 on creation', "
            f"got {data['version']!r}"
        )


class TestPost911Tier:

    @pytest.mark.parametrize("days,expected_tier", [
        (0, 0),
        (89, 0),
        (90, 40),
        (179, 40),
        (180, 50),
        (364, 50),
        (365, 60),
        (546, 60),
        (547, 70),
        (729, 70),
        (730, 80),
        (912, 80),
        (913, 90),
        (1094, 90),
        (1095, 100),
        (5000, 100),
    ])
    def test_post_911_tier_boundaries(self, api, days, expected_tier):
        """PRD §3.1: "Below 90 days the tier is 0; from 90 up to 180
        days the tier is 40; from 180 up to 365 days the tier is 50;
        from 365 up to 547 days (eighteen months) the tier is 60; from
        547 up to 730 days (two years) the tier is 70; from 730 up to
        913 days (thirty months) the tier is 80; from 913 up to 1095
        days (thirty-six months) the tier is 90; and at 1095 days or
        more (three years or more) the tier is 100."

        # difficulty: boundary_precision_check/post_911_tier_boundary_at_90_days
        """
        v = create_veteran(aggregate_active_duty_days=days)
        assert v["post_911_eligibility_tier"] == expected_tier, (
            f"days={days}: expected tier {expected_tier}, "
            f"got {v['post_911_eligibility_tier']}"
        )


class TestPatchVeteranTierRecompute:

    def test_patch_aggregate_active_duty_days_recomputes_tier(self, api):
        """PRD §3.1: "The tier is recomputed whenever a clerk later
        patches aggregate_active_duty_days"

        # difficulty: boundary_precision_check/post_911_tier_boundary_at_90_days
        """
        v = create_veteran(aggregate_active_duty_days=89)
        assert v["post_911_eligibility_tier"] == 0

        resp = api.patch_veteran(
            v["id"],
            patch_veteran_payload(aggregate_active_duty_days=1095),
            TEST_USERS["va_clerk_headers"],
        )
        updated = validate_success(resp)
        assert updated["post_911_eligibility_tier"] == 100
        assert_version_incremented_by(v, updated, delta=1)

    def test_patch_with_matching_version_succeeds(self, api):
        """PRD §2.5: "When the caller supplies version, the server
        compares it against the current version stored on the resource
        ... On a successful PATCH the server increments version by 1
        and refreshes updated_at."
        """
        v = create_veteran(aggregate_active_duty_days=500)
        resp = api.patch_veteran(
            v["id"],
            patch_veteran_payload(
                aggregate_active_duty_days=800,
                version=v["version"],
            ),
            TEST_USERS["va_clerk_headers"],
        )
        updated = validate_success(resp)
        assert updated["aggregate_active_duty_days"] == 800
        assert updated["version"] == v["version"] + 1

    def test_patch_with_stale_version_returns_version_conflict(self, api):
        """PRD §2.5: "a mismatch causes the request to be rejected with
        ERR_VERSION_CONFLICT."
        """
        v = create_veteran(aggregate_active_duty_days=500)
        resp = api.patch_veteran(
            v["id"],
            patch_veteran_payload(
                aggregate_active_duty_days=800,
                version=v["version"] + 999,
            ),
            TEST_USERS["va_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)


class TestDependentCreation:

    def test_create_child_dependent_under_18(self, api):
        """PRD §3.2: "the system enforces that the child is either
        younger than 18 at creation, or between 18 and 23 inclusive
        with school_enrolled set to true"

        Create a CHILD age 10 -> succeeds, status ACTIVE.
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        today = current_clock().date()
        dob = iso_utc(utc_midnight(today - timedelta(days=365 * 10)))
        resp = api.create_dependent(
            create_dependent_payload(
                veteran_id=vet["id"],
                relationship="CHILD",
                date_of_birth=dob,
            ),
            TEST_USERS["va_clerk_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_dependent(data)
        assert data["status"] == "ACTIVE"
        assert data["relationship"] == "CHILD"

    def test_child_age_19_without_school_rejected(self, api):
        """PRD §3.2: "any child outside that envelope is rejected with
        ERR_DEPENDENT_AGE."

        Age 19, school_enrolled=false -> rejected.
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        today = current_clock().date()
        dob = iso_utc(utc_midnight(today - timedelta(days=365 * 19)))
        resp = api.create_dependent(
            create_dependent_payload(
                veteran_id=vet["id"],
                relationship="CHILD",
                date_of_birth=dob,
                school_enrolled=False,
            ),
            TEST_USERS["va_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DEPENDENT_AGE.value)

    def test_child_age_19_with_school_enrolled_accepted(self, api):
        """PRD §3.2: "the child is either younger than 18 at creation,
        or between 18 and 23 inclusive with school_enrolled set to
        true; any child outside that envelope is rejected with
        ERR_DEPENDENT_AGE."
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        today = current_clock().date()
        dob = iso_utc(utc_midnight(today - timedelta(days=365 * 19)))
        resp = api.create_dependent(
            create_dependent_payload(
                veteran_id=vet["id"],
                relationship="CHILD",
                date_of_birth=dob,
                school_enrolled=True,
            ),
            TEST_USERS["va_clerk_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_dependent(data)
        assert data["status"] == "ACTIVE"

    def test_child_age_24_rejected_even_with_school(self, api):
        """PRD §3.2: "between 18 and 23 inclusive with school_enrolled
        set to true; any child outside that envelope is rejected with
        ERR_DEPENDENT_AGE."
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        today = current_clock().date()
        dob = iso_utc(utc_midnight(today - timedelta(days=365 * 24 + 30)))
        resp = api.create_dependent(
            create_dependent_payload(
                veteran_id=vet["id"],
                relationship="CHILD",
                date_of_birth=dob,
                school_enrolled=True,
            ),
            TEST_USERS["va_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DEPENDENT_AGE.value)


class TestSpouseUniqueness:

    def test_second_active_spouse_rejected(self, api):
        """PRD §3.2: "a veteran may have at most one spouse in ACTIVE
        status at any time, and a second active-spouse creation is
        rejected with ERR_DUPLICATE_SPOUSE."
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        spouse_dob = iso_utc(utc_midnight(
            current_clock().date() - timedelta(days=365 * 30),
        ))
        first = create_dependent(
            veteran_id=vet["id"],
            relationship="SPOUSE",
            date_of_birth=spouse_dob,
        )
        assert first["status"] == "ACTIVE"
        resp = api.create_dependent(
            create_dependent_payload(
                veteran_id=vet["id"],
                relationship="SPOUSE",
                date_of_birth=spouse_dob,
            ),
            TEST_USERS["va_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SPOUSE.value)

    def test_spouse_after_removal_is_allowed(self, api):
        """PRD §3.2: "a veteran may have at most one spouse in ACTIVE
        status at any time" — after the prior spouse is REMOVED a new
        ACTIVE spouse is admissible.
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        spouse_dob = iso_utc(utc_midnight(
            current_clock().date() - timedelta(days=365 * 30),
        ))
        first = create_dependent(
            veteran_id=vet["id"], relationship="SPOUSE",
            date_of_birth=spouse_dob,
        )
        delete_dependent(first["id"])
        # Second spouse now permitted.
        second = create_dependent(
            veteran_id=vet["id"], relationship="SPOUSE",
            date_of_birth=spouse_dob,
        )
        assert second["status"] == "ACTIVE"


class TestDependentRemoval:

    def test_delete_dependent_flips_status_and_stamps_removed_at(self, api):
        """PRD §3.2: "Removing a dependent moves it from ACTIVE to
        REMOVED, stamps removed_at with the current server clock"
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        dep = create_dependent(
            veteran_id=vet["id"], relationship="PARENT",
            date_of_birth=iso_utc(utc_midnight(
                current_clock().date() - timedelta(days=365 * 60),
            )),
        )
        resp = api.delete_dependent(
            dep["id"], TEST_USERS["va_clerk_headers"],
        )
        removed = validate_success(resp)
        assert removed["status"] == "REMOVED"
        assert removed.get("removed_at"), (
            "PRD §3.2: removal stamps removed_at with the current "
            "server clock"
        )

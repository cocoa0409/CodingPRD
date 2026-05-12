"""Pet records, soft-delete, and visit history (PRD §3.2)."""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_pet,
    create_pet_payload,
    create_visit_payload,
    setup_owner_and_pet,
    update_pet_payload,
    validate_error,
    validate_success,
)


class TestPetCreation:
    def test_pet_created_with_empty_history(self, api, owner_service_headers):
        """PRD §3.2: 'The medical_history array starts empty and is
        appended to (in chronological order of finalization) every time
        one of the pet's treatment records transitions from DRAFT to
        FINALIZED.'"""
        owner, _ = setup_owner_and_pet()
        payload = create_pet_payload(owner_id=owner["id"])
        res = api.create_pet(payload, owner_service_headers)
        data = validate_success(res, expected_status=201)
        assert_pet(data)
        assert data["medical_history"] == [], (
            "Newly created pet must have empty medical_history"
        )
        assert data["archived"] is False

    @pytest.mark.parametrize(
        "weight",
        [-1.0, 0.0, 0.04, 200.01, 1000.0],
    )
    def test_pet_weight_out_of_range_rejected(self, api, weight, owner_service_headers):
        """PRD §3.2: 'a weight_kg of at least 0.05 kilograms and no more
        than 200 kilograms with up to two decimal places.'"""
        owner, _ = setup_owner_and_pet()
        payload = create_pet_payload(owner_id=owner["id"], weight_kg=weight)
        res = api.create_pet(payload, owner_service_headers)
        validate_error(res, "ERR_VALIDATION_FAILED")


class TestPetSoftDelete:
    def test_archived_pet_blocks_new_visit(self, api, platform_admin_headers,
                                            triage_nurse_headers):
        """PRD §3.2: 'An archived pet cannot start a new visit (any
        attempt is rejected with ERR_PET_ARCHIVED).'"""
        owner, pet = setup_owner_and_pet()
        # Soft-delete the pet (admin-only per §3.2).
        del_res = api.archive_pet(pet["id"], platform_admin_headers)
        validate_success(del_res)
        # Attempting to create a visit on the archived pet must fail.
        res = api.create_visit(
            pet["id"], create_visit_payload(), triage_nurse_headers,
        )
        validate_error(res, "ERR_PET_ARCHIVED")

    def test_archived_pet_remains_queryable_for_history(self, api, platform_admin_headers,
                                                        owner_service_headers):
        """PRD §3.2: 'An archived pet ... remains queryable for read
        endpoints and for visit-history listing.'"""
        owner, pet = setup_owner_and_pet()
        api.archive_pet(pet["id"], platform_admin_headers)
        res = api.list_pet_visits(pet["id"], owner_service_headers)
        validate_success(res)

    def test_archive_role_restriction_owner_service_forbidden(self, api,
                                                               owner_service_headers):
        """PRD §3.2: 'The pet delete action is a soft delete restricted
        to PlatformAdmin.'"""
        owner, pet = setup_owner_and_pet()
        res = api.archive_pet(pet["id"], owner_service_headers)
        validate_error(res, "ERR_FORBIDDEN")


class TestPetUpdateOCC:
    def test_update_pet_with_correct_version_succeeds(self, api):
        """PRD §2.4: 'Mutation endpoints that accept a version field in
        the request body — most prominently PATCH /treatment-records/{tr_id},
        PATCH /pets/{pet_id}, and PATCH /drugs/{drug_id} — compare the
        supplied version to the current entity's version. A mismatch is
        rejected with ERR_STALE_VERSION.'"""
        owner, pet = setup_owner_and_pet()
        res = api.update_pet(
            pet["id"],
            update_pet_payload(weight_kg=15.0, version=pet["version"]),
            TEST_USERS["drafting_vet_headers"],
        )
        data = validate_success(res)
        assert data["weight_kg"] == 15.0
        assert data["version"] == pet["version"] + 1, (
            f"Expected version {pet['version']+1}, got {data['version']}"
        )

    def test_update_pet_with_stale_version_rejected(self, api):
        """PRD §2.4: 'A mismatch is rejected with ERR_STALE_VERSION.'"""
        owner, pet = setup_owner_and_pet()
        res = api.update_pet(
            pet["id"],
            update_pet_payload(weight_kg=15.0, version=pet["version"] + 99),
            TEST_USERS["drafting_vet_headers"],
        )
        validate_error(res, "ERR_STALE_VERSION")

    def test_update_pet_without_version_skips_occ(self, api):
        """PRD §2.4: 'When the request body omits version, the OCC check
        is skipped and the mutation proceeds without it.'"""
        owner, pet = setup_owner_and_pet()
        res = api.update_pet(
            pet["id"],
            update_pet_payload(weight_kg=15.0),  # no version
            TEST_USERS["drafting_vet_headers"],
        )
        data = validate_success(res)
        assert data["weight_kg"] == 15.0


class TestVisitHistoryNewestFirst:
    def test_visit_history_newest_first(self, api, triage_nurse_headers,
                                         owner_service_headers):
        """PRD §3.2: 'The visit-history listing for a pet returns the pet's
        visits newest-first and is paginated by limit and offset.'"""
        owner, pet = setup_owner_and_pet()
        # Create three visits in temporal order.
        v1 = validate_success(
            api.create_visit(pet["id"], create_visit_payload(), triage_nurse_headers),
            expected_status=201,
        )
        v2 = validate_success(
            api.create_visit(pet["id"], create_visit_payload(), triage_nurse_headers),
            expected_status=201,
        )
        v3 = validate_success(
            api.create_visit(pet["id"], create_visit_payload(), triage_nurse_headers),
            expected_status=201,
        )
        res = api.list_pet_visits(pet["id"], owner_service_headers)
        from test_helpers import validate_paginated
        data, meta = validate_paginated(res)
        ids = [v["id"] for v in data]
        # newest first → v3, v2, v1 order at the front
        assert ids[:3] == [v3["id"], v2["id"], v1["id"]], (
            f"Expected newest-first ordering [v3,v2,v1], got {ids}"
        )

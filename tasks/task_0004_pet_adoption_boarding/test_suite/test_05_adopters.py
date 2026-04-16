"""Tests for Adopter CRUD and blacklist cascade.

Covers: PRD Section 3.3 (Adopters), Table 1 (Adopter), Table 4 priority 12.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_adopter,
    create_adopter_payload, create_adoption_application_payload,
    blacklist_adopter_payload,
    create_shelter, create_adopter, create_available_animal,
    create_submitted_application, setup_basic_adoption_scenario,
)

_manager = TEST_USERS["manager_headers"]
_case_worker = TEST_USERS["case_worker_headers"]


class TestAdopterCreation:
    """PRD 3.3: CaseWorker registers a new adopter in ACTIVE status."""

    def test_create_adopter_success(self):
        shelter = create_shelter()
        payload = create_adopter_payload(shelter["id"])
        resp = api_client.create_adopter(payload, _case_worker)
        data = validate_success(resp, 201)
        assert_adopter(data)
        assert data["status"] == "ACTIVE"
        assert data["shelter_id"] == shelter["id"]
        assert data["adoption_history_count"] == 0
        assert data["latest_home_visit_id"] is None
        assert data["latest_home_visit_result"] is None

    def test_create_adopter_shelter_not_found(self):
        payload = create_adopter_payload(NON_EXISTENT_UUID)
        resp = api_client.create_adopter(payload, _case_worker)
        validate_error(resp, ApiErrorId.ERR_SHELTER_NOT_FOUND)

    def test_create_adopter_missing_required_field(self):
        """Missing email returns ERR_INVALID_REQUEST."""
        shelter = create_shelter()
        payload = create_adopter_payload(shelter["id"])
        del payload["email"]
        resp = api_client.create_adopter(payload, _case_worker)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_adopter_invalid_home_type(self):
        shelter = create_shelter()
        payload = create_adopter_payload(shelter["id"], home_type="CASTLE")
        resp = api_client.create_adopter(payload, _case_worker)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestAdopterRetrieval:
    def test_get_adopter(self):
        adopter = create_adopter()
        resp = api_client.get_adopter(adopter["id"], _case_worker)
        data = validate_success(resp)
        assert data["id"] == adopter["id"]

    def test_get_adopter_not_found(self):
        resp = api_client.get_adopter(NON_EXISTENT_UUID, _manager)
        validate_error(resp, ApiErrorId.ERR_ADOPTER_NOT_FOUND)


class TestAdopterUpdate:
    def test_patch_adopter_success(self):
        adopter = create_adopter()
        resp = api_client.update_adopter(
            adopter["id"], {"phone": "+15550001234"}, _case_worker
        )
        data = validate_success(resp)
        assert data["phone"] == "+15550001234"
        assert data["version"] > adopter["version"]

    def test_patch_adopter_version_conflict(self):
        adopter = create_adopter()
        v = adopter["version"]
        get_success_data(api_client.update_adopter(
            adopter["id"], {"phone": "+15551", "version": v}, _case_worker
        ))
        resp = api_client.update_adopter(
            adopter["id"], {"phone": "+15552", "version": v}, _case_worker
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT)


class TestAdopterBlacklist:
    """PRD 3.3: Blacklist cascades to in-flight applications."""

    def test_blacklist_adopter_success(self):
        adopter = create_adopter()
        resp = api_client.blacklist_adopter(
            adopter["id"], blacklist_adopter_payload("policy"), _manager
        )
        data = validate_success(resp)
        assert data["status"] == "BLACKLISTED"

    def test_blacklist_cascades_submitted_application(self):
        """A SUBMITTED application transitions to WITHDRAWN on blacklist."""
        shelter, animal, adopter, app = create_submitted_application()
        get_success_data(api_client.blacklist_adopter(
            adopter["id"], blacklist_adopter_payload(), _manager
        ))
        refreshed = get_success_data(api_client.get_adoption_application(app["id"], _manager))
        assert refreshed["status"] == "WITHDRAWN"

    def test_blacklisted_adopter_blocks_new_application(self):
        """PRD 3.3 + Table 4 priority 12: BLACKLISTED adopter cannot have start-review."""
        shelter, animal, adopter = setup_basic_adoption_scenario(species="CAT", weight_kg=5.0)
        get_success_data(api_client.blacklist_adopter(
            adopter["id"], blacklist_adopter_payload(), _manager
        ))
        app = get_success_data(api_client.create_adoption_application(
            create_adoption_application_payload(animal["id"], adopter["id"]),
            _case_worker,
        ))
        # start-review must fail with ERR_ADOPTER_BLACKLISTED
        resp = api_client.start_review_application(app["id"], _case_worker)
        validate_error(resp, ApiErrorId.ERR_ADOPTER_BLACKLISTED)

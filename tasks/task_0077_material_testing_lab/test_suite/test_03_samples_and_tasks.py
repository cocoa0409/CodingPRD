"""Sample registration, witness-record consistency, task creation, and
method-category coupling (PRD §3.2, §3.3, §2.7)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_sample,
    assert_sample_code_format,
    assert_storage_location_format,
    assert_test_task,
    create_client,
    create_sample,
    create_sample_payload,
    create_task,
    create_test_task_payload,
    create_tester,
    qualification,
    setup_steel_only_testers_concrete_sample,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestSampleRegistration:
    def test_create_sample_returns_envelope_and_computes_ids(
        self, api, lab_clerk_headers,
    ):
        """PRD §3.2: 'On successful registration the server mints two
        server-controlled identifiers and sets the sample's status to
        REGISTERED.'

        Claim: POST /samples returns a 201 row with sample_code,
        storage_location, and status=REGISTERED.
        """
        client = create_client()
        payload = create_sample_payload(
            client_id=client["id"], material_category="CONCRETE",
        )
        resp = api.create_sample(payload, lab_clerk_headers)
        data = validate_success(resp, expected_status=201)
        assert_sample(data)
        assert data["status"] == "REGISTERED"
        assert_sample_code_format(data)
        assert_storage_location_format(data)

    def test_sample_code_prefix_matches_material_category(
        self, api, lab_clerk_headers,
    ):
        """PRD §3.2: 'MATERIAL3 is the first three letters of the
        material category (CON for CONCRETE, STE for STEEL_REBAR, SOI
        for SOIL, ASP for ASPHALT, CEM for CEMENT).'

        Claim: the sample_code's MATERIAL3 prefix maps to its
        material_category.
        """
        client = create_client()
        sample = create_sample(
            client_id=client["id"], material_category="STEEL_REBAR",
        )
        assert sample["sample_code"].startswith("STE-"), (
            f"STEEL_REBAR should yield STE prefix, got {sample['sample_code']}"
        )

    def test_sample_code_is_unique_per_creation(
        self, api, lab_clerk_headers,
    ):
        """PRD §3.2: 'The sample_code is globally unique across the
        laboratory's lifetime.'

        Claim: two samples in the same (material, day) bucket get
        distinct sample_codes.
        """
        client = create_client()
        s1 = create_sample(
            client_id=client["id"], material_category="CONCRETE",
        )
        s2 = create_sample(
            client_id=client["id"], material_category="CONCRETE",
        )
        assert s1["sample_code"] != s2["sample_code"]


class TestWitnessRecordConsistency:
    """PRD §3.2 — witness flag <-> witness_name agreement."""

    def test_witness_true_requires_name(self, api, lab_clerk_headers):
        """PRD §3.2: 'If witness_sampled is true and witness_name is
        missing or empty, registration is rejected with
        ERR_WITNESS_RECORD_INCONSISTENT.'

        Claim: witness_sampled=true with no witness_name → 422
        ERR_WITNESS_RECORD_INCONSISTENT.
        """
        client = create_client()
        payload = create_sample_payload(
            client_id=client["id"], witness_sampled=True,
        )
        payload.pop("witness_name", None)
        resp = api.create_sample(payload, lab_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_WITNESS_RECORD_INCONSISTENT.value)

    def test_witness_false_must_not_supply_name(
        self, api, lab_clerk_headers,
    ):
        """PRD §3.2: 'if witness_sampled is false and a non-null
        witness_name is supplied, registration is rejected with the
        same error.'

        Claim: witness_sampled=false with witness_name set → 422
        ERR_WITNESS_RECORD_INCONSISTENT.
        """
        client = create_client()
        payload = create_sample_payload(
            client_id=client["id"], witness_sampled=False,
            witness_name="Inspector Eve",
        )
        resp = api.create_sample(payload, lab_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_WITNESS_RECORD_INCONSISTENT.value)

    def test_witness_true_with_name_succeeds(
        self, api, lab_clerk_headers,
    ):
        """PRD §3.2: 'witness_sampled is true and witness_name is missing
        or empty, registration is rejected; symmetrically, if
        witness_sampled is false and a non-null witness_name is supplied,
        registration is rejected.'

        Claim: witness_sampled=true with a non-empty witness_name
        succeeds.
        """
        client = create_client()
        payload = create_sample_payload(
            client_id=client["id"], witness_sampled=True,
            witness_name="Inspector Eve",
        )
        resp = api.create_sample(payload, lab_clerk_headers)
        data = validate_success(resp, expected_status=201)
        assert data["witness_sampled"] is True
        assert data["witness_name"] == "Inspector Eve"


class TestTaskCreationMethodCoupling:
    """PRD §3.3 — method ↔ material_category coupling."""

    @pytest.mark.parametrize("method,category", [
        ("COMPRESSION_STRENGTH", "STEEL_REBAR"),
        ("TENSILE_STRENGTH", "CONCRETE"),
        ("COMPACTION_DENSITY", "ASPHALT"),
        ("MARSHALL_STABILITY", "CEMENT"),
        ("SETTING_TIME", "SOIL"),
    ])
    def test_method_not_supported_for_wrong_material(
        self, api, lab_clerk_headers, method, category,
    ):
        """PRD §3.3: 'If the supplied test_method does not match the
        sample's material_category under this coupling, task creation
        is rejected with ERR_TEST_METHOD_NOT_SUPPORTED.'

        Claim: every mismatched (method, category) pair yields
        ERR_TEST_METHOD_NOT_SUPPORTED.
        """
        client = create_client()
        # Ensure a qualified tester exists for `category` so the failure
        # is unambiguously the method/category mismatch and not the
        # "no qualified tester" path.
        create_tester(qualifications=[
            qualification(category, "2024-01-01", "2200-12-31"),
        ])
        sample = create_sample(
            client_id=client["id"], material_category=category,
        )
        resp = api.create_test_task(
            sample["id"],
            create_test_task_payload(test_method=method),
            lab_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TEST_METHOD_NOT_SUPPORTED.value)

    def test_method_supported_succeeds(self, api, lab_clerk_headers):
        """PRD §3.3: 'COMPRESSION_STRENGTH may only be performed on
        CONCRETE samples.'

        Claim: a matching pair (COMPRESSION_STRENGTH + CONCRETE)
        creates the task.
        """
        client = create_client()
        create_tester(qualifications=[
            qualification("CONCRETE", "2024-01-01", "2200-12-31"),
        ])
        sample = create_sample(
            client_id=client["id"], material_category="CONCRETE",
        )
        resp = api.create_test_task(
            sample["id"],
            create_test_task_payload(test_method="COMPRESSION_STRENGTH"),
            lab_clerk_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_test_task(data)
        assert data["test_method"] == "COMPRESSION_STRENGTH"


class TestFirstTaskAdvancesSample:
    def test_first_task_moves_sample_to_in_testing(
        self, api, lab_clerk_headers, lab_manager_headers,
    ):
        """PRD §3.3: 'The first successful task creation under a sample
        also advances the parent sample from REGISTERED to IN_TESTING.'

        Claim: after the first task is created, Sample.status ==
        IN_TESTING.
        """
        client = create_client()
        create_tester(qualifications=[
            qualification("CONCRETE", "2024-01-01", "2200-12-31"),
        ])
        sample = create_sample(
            client_id=client["id"], material_category="CONCRETE",
        )
        assert sample["status"] == "REGISTERED"
        create_task(
            sample_id=sample["id"], test_method="COMPRESSION_STRENGTH",
        )
        refreshed = validate_success(
            api.get_sample(sample["id"], lab_clerk_headers),
        )
        assert refreshed["status"] == "IN_TESTING"


class TestNotFoundOnUnknownSample:
    def test_create_task_unknown_sample(self, api, lab_clerk_headers):
        """PRD §2.6: 'Path segments are resolved strictly left-to-right;
        the first segment whose id does not match an existing resource
        yields ERR_NOT_FOUND (HTTP 404).'

        Claim: POST /samples/{unknown}/tasks → ERR_NOT_FOUND.
        """
        resp = api.create_test_task(
            NON_EXISTENT_UUID,
            create_test_task_payload(test_method="COMPRESSION_STRENGTH"),
            lab_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

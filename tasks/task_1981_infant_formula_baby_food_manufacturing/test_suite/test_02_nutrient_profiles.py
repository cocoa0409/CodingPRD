"""Nutrient profile lifecycle: creation, retrieval, pagination, uniqueness,
and the DRAFT/SUBMITTED/APPROVED review loop (PRD §2.2, §2.3, §3.1, §4)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, create_nutrient_profile_payload, assert_nutrient_profile,
    create_approved_nutrient_profile,
)


def _spec(code="PROTEIN", unit="g", mn=1.80, mx=3.50, tg=2.50):
    return [{
        "nutrient_code": code, "unit": unit,
        "min_per_100kcal": mn, "max_per_100kcal": mx, "target_per_100kcal": tg,
    }]


class TestNutrientProfileCreation:
    def test_create_nutrient_profile_success(self, api, users):
        """PRD §3.1: "A new profile starts in `DRAFT`." PRD §4: "Operations
        that create a new resource — whether a top-level resource or a child
        resource added to a parent's collection — return `201 Created`."
        PRD §2.4: every primary entity carries a server-minted UUID `id`,
        `created_at`, `updated_at`, and an integer `version`.

        Design: Corner/entities/create_nutrient_profile_success
        """
        res = api.create_nutrient_profile(
            create_nutrient_profile_payload(
                profile_code="INF-0-6M", nutrient_specs=_spec()),
            users["ra1"]["headers"])
        data = validate_success(res, 201)
        assert data["profile_code"] == "INF-0-6M"
        assert data["status"] == "DRAFT"
        assert_nutrient_profile(data)

    def test_get_nutrient_profile_by_id(self, api, users):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field." The fetched profile is the same resource that was created
        (PRD §4, GET /api/v1/nutrient-profiles/{id}).

        Design: Corner/entities/get_nutrient_profile_by_id
        """
        created = validate_success(api.create_nutrient_profile(
            create_nutrient_profile_payload(
                profile_code="INF-6-12M",
                nutrient_specs=_spec("IRON", "mg", 1.00, 2.00, 1.50)),
            users["ra1"]["headers"]), 201)
        res = api.get_nutrient_profile(created["id"], users["ra1"]["headers"])
        data = validate_success(res)
        assert data["id"] == created["id"]
        assert data["profile_code"] == "INF-6-12M"
        assert data["nutrient_specs"][0]["nutrient_code"] == "IRON"

    def test_list_nutrient_profiles_pagination(self, api, users):
        """PRD §2.3: "List responses include four pagination fields in the
        `meta` object of the envelope: `limit`, `offset`, `total_count`, and
        `has_more`." With three profiles and limit=2, the first page carries
        two items, total_count 3, and has_more true.

        Design: Corner/entities/list_nutrient_profiles_pagination
        """
        for code, spec in [
            ("INF-0-6M", _spec()),
            ("INF-6-12M", _spec("IRON", "mg", 1.00, 2.00, 1.50)),
            ("TODDLER-12-36M", _spec("CALCIUM", "mg", 60.0, 180.0, 120.0)),
        ]:
            validate_success(api.create_nutrient_profile(
                create_nutrient_profile_payload(
                    profile_code=code, nutrient_specs=spec),
                users["ra1"]["headers"]), 201)
        res = api.list_nutrient_profiles(
            users["ra1"]["headers"], params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(res)
        assert len(data) == 2, f"Expected 2 items, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

    def test_duplicate_profile_code_rejected(self, api, users):
        """PRD §3.1: "The `profile_code` is unique across the system; an
        attempt to create a profile with a `profile_code` already in use is
        rejected with `ERR_DUPLICATE_CODE` (HTTP 409)."

        Design: Corner/validations/duplicate_profile_code_returns_409
        """
        validate_success(api.create_nutrient_profile(
            create_nutrient_profile_payload(
                profile_code="INF-0-6M", nutrient_specs=_spec()),
            users["ra1"]["headers"]), 201)
        res = api.create_nutrient_profile(
            create_nutrient_profile_payload(
                profile_code="INF-0-6M", regulation_ref="EU 2016/127",
                effective_from="2026-06-01T00:00:00Z",
                nutrient_specs=_spec("CALCIUM", "mg", 60.0, 180.0, 120.0)),
            users["ra1"]["headers"])
        validate_error(res, ApiErrorId.ERR_DUPLICATE_CODE)


class TestNutrientProfileReviewLoop:
    def test_submit_transitions_draft_to_submitted(self, api, users):
        """PRD §3.1: "A new profile starts in `DRAFT`. A `REGULATORY_AFFAIRS`
        operator submits it for approval, transitioning `DRAFT → SUBMITTED`"

        Design: Corner/state_machines/nutrient_profile_valid_transition_draft_to_submitted
        """
        profile = validate_success(api.create_nutrient_profile(
            create_nutrient_profile_payload(
                profile_code="INF-0-6M", nutrient_specs=_spec()),
            users["ra1"]["headers"]), 201)
        res = api.submit_nutrient_profile(profile["id"], users["ra1"]["headers"])
        data = validate_success(res)
        assert data["status"] == "SUBMITTED"

    def test_return_for_revision_from_approved_rejected(self, api, users):
        """PRD §3.1: "A submitted profile may instead be returned to `DRAFT`
        via the return-for-revision action with no preconditions." — the action
        is defined from `SUBMITTED` only. PRD §2.7: "When a state-machine
        transition is invoked against a resource that is not in a state from
        which that transition is defined, the request is rejected with
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/nutrient_profile_invalid_transition_approved_to_draft
        """
        profile = create_approved_nutrient_profile(
            users, profile_code="INF-0-6M", nutrient_specs=_spec())
        assert profile["status"] == "APPROVED"
        res = api.return_nutrient_profile_for_revision(
            profile["id"], users["ra1"]["headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestNutrientSpecRetrieval:
    def test_approved_profile_retains_spec_bounds(self, api, users):
        """PRD §3.1: "Each entry in `nutrient_specs` names a `nutrient_code`
        from the recognized codex list, a `unit`, and three numeric bounds:
        `min_per_100kcal`, `max_per_100kcal`, and `target_per_100kcal`." The
        stored bounds are returned verbatim on retrieval.

        Design: Corner/calculations/nutrient_compliance_standard_correct_result
        """
        profile = create_approved_nutrient_profile(
            users, profile_code="TODDLER-12-36M",
            nutrient_specs=_spec("PROTEIN", "g", 1.50, 3.00, 2.20))
        res = api.get_nutrient_profile(profile["id"], users["ra1"]["headers"])
        data = validate_success(res)
        assert data["nutrient_specs"][0]["min_per_100kcal"] == 1.50
        assert data["nutrient_specs"][0]["max_per_100kcal"] == 3.00

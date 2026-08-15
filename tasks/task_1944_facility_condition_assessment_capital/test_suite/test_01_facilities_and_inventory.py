"""Facility baseline, asset inventory shape rules, listing envelope, and the
facility recompute capability."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_asset_system,
    assert_condition_snapshot,
    assert_deficiency,
    assert_facility,
    create_asset_system,
    create_asset_system_payload,
    create_client,
    create_deficiency,
    create_deficiency_payload,
    create_facility,
    create_facility_payload,
    get_facility,
    is_valid_uuid,
    setup_facility_with_system,
    setup_system_with_deficiency,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import CONSULTANT


class TestFacilityCreation:
    def test_facility_create_returns_computed_defaults(self, api):
        """PRD §2.4: "A freshly created Facility starts with all three of these
        fields at 0 and with `assessment_epoch` at 0, meaning its data has not
        yet been ratified against any refresh cycle."
        PRD §2.4: "`version` (integer): starts at 1 and increments by one on
        every mutation of the resource; it is the basis for optimistic
        concurrency control."

        Design: Corner/entities/facility_create_success_returns_computed_defaults
        """
        client = create_client(name="Tau LLC", contact_email="tau@tau.example")
        resp = api.create_facility(
            create_facility_payload(client["id"], name="HQ", address="1 Plaza",
                                    gross_square_feet=100000),
            CONSULTANT,
        )
        facility = validate_success(resp, 201)
        assert_facility(facility)
        assert is_valid_uuid(facility["id"]), "id is a server-minted UUID"
        assert facility["current_replacement_value_cents"] == 0
        assert facility["backlog_cost_cents"] == 0
        assert facility["facility_condition_index"] == 0
        assert facility["assessment_epoch"] == 0
        assert facility["version"] == 1


class TestFacilityNotFound:
    def test_facility_get_not_found_returns_404(self, api):
        """PRD §2.7: "**Path existence** — every identifier embedded in the URL
        path (facility, asset-system, deficiency, capital-plan, funding-scenario,
        project-bundle, refresh-cycle) must exist, validated strictly
        left-to-right so the first missing identifier produces `ERR_NOT_FOUND`."

        Design: Corner/entities/facility_get_not_found_returns_404
        """
        resp = api.get_facility(NON_EXISTENT_UUID, CONSULTANT)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestAssetSystemShapeRules:
    def test_asset_system_invalid_enum_category_rejected(self, api):
        """PRD §3.2: "a `system_category` drawn from the Uniformat-style
        enumeration `HVAC`, `ROOF`, `ENVELOPE`, `ELECTRICAL`, `PLUMBING`,
        `FIRE_PROTECTION`, `CONVEYANCE`, `INTERIOR`, `SITE`, or `STRUCTURE`"
        PRD §3.2: "Violating any of these shapes is an `ERR_INVALID_REQUEST`."

        Design: Corner/entities/asset_system_invalid_enum_category_rejected
        """
        facility = create_facility()
        resp = api.create_asset_system(
            create_asset_system_payload(
                facility["id"], system_category="SOLAR_ARRAY", name="X",
                install_year=2020, design_life_years=10,
                replacement_cost_cents=1000, condition_rating=3),
            CONSULTANT,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    @pytest.mark.parametrize("bad_rating", [0, 6])
    def test_asset_system_condition_rating_out_of_range_rejected(
            self, api, bad_rating):
        """PRD §3.2: "the assessor's `condition_rating` on a scale of 1 (failed)
        to 5 (excellent). Violating any of these shapes is an
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/asset_system_condition_rating_out_of_range_rejected
        """
        facility = create_facility()
        resp = api.create_asset_system(
            create_asset_system_payload(facility["id"],
                                        condition_rating=bad_rating),
            CONSULTANT,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestDeficiencyShapeRules:
    @pytest.mark.parametrize("missing_field", [
        "asset_system_id", "description", "cost_estimate_cents",
        "severity", "urgency", "recommended_year",
    ])
    def test_deficiency_missing_required_field_rejected(self, api, missing_field):
        """PRD §3.4: "A `Consultant` records a finding on a specific system by
        posting its `asset_system_id` along with a free-text `description`, the
        present-day correction `cost_estimate_cents` (a strictly positive
        integer), a `severity` from 1 (minor) to 5 (critical) capturing the
        consequence of not correcting, an `urgency` from 1 (can wait years) to
        5 (immediate), optional `is_code_violation` and
        `is_accessibility_violation` flags (both defaulting to false), and the
        `recommended_year` in which correction should occur."
        PRD §2.7: "**Field shape** — enum membership, integer ranges, and
        required-field presence; otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/deficiency_missing_required_field_rejected
        """
        _facility, system = setup_facility_with_system(
            {"system_category": "ROOF", "name": "R", "install_year": 2010,
             "design_life_years": 25, "replacement_cost_cents": 5000000,
             "condition_rating": 3})
        payload = create_deficiency_payload(system["id"], description="x",
                                            severity=3, urgency=3,
                                            recommended_year=2027)
        del payload[missing_field]
        resp = api.create_deficiency(payload, CONSULTANT)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_deficiency_boolean_defaults_applied(self, api):
        """PRD §3.4: "optional `is_code_violation` and
        `is_accessibility_violation` flags (both defaulting to false)"
        PRD §3.4: "the severity multiplied by a weight of 0.6, plus the urgency
        multiplied by a weight of 0.4, plus a bonus of 10 when the finding is a
        code violation, plus a further bonus of 5 when it is an accessibility
        violation — the total rounded half-up to 2 decimal places."

        Design: Corner/entities/deficiency_boolean_defaults_applied
        """
        _facility, system = setup_facility_with_system(
            {"system_category": "ROOF", "name": "R", "install_year": 2010,
             "design_life_years": 25, "replacement_cost_cents": 5000000,
             "condition_rating": 3})
        resp = api.create_deficiency(
            create_deficiency_payload(system["id"], description="plain",
                                      cost_estimate_cents=1000000, severity=4,
                                      urgency=2, recommended_year=2027),
            CONSULTANT,
        )
        deficiency = validate_success(resp, 201)
        assert_deficiency(deficiency)
        assert deficiency["is_code_violation"] is False, "default false"
        assert deficiency["is_accessibility_violation"] is False, "default false"
        # 0.6*4 + 0.4*2 = 3.20, no flag bonuses.
        assert deficiency["priority_score"] == pytest.approx(3.20, abs=1e-9)


class TestConditionSnapshotShape:
    def test_condition_snapshot_is_append_only_without_version(self, api):
        """PRD §2.4: "A **ConditionSnapshot** is an immutable historical record
        — once written it is never modified — and therefore carries only `id`
        and `created_at`; both `updated_at` and `version` are absent from it."
        PRD §3.3: "a **ConditionSnapshot** is appended capturing the
        `asset_system_id`, the new `condition_rating`, the recomputed
        `remaining_useful_life_years`, the facility's current `epoch`, and the
        `note`"
        PRD §3.2: "a `condition_rating` of 2 caps remaining life at no more
        than 2 years even if the raw arithmetic would allow more."

        Design: Corner/entities/condition_snapshot_immutable_no_update_endpoint
        """
        _facility, system = setup_facility_with_system(
            {"system_category": "ROOF", "name": "R", "install_year": 2010,
             "design_life_years": 25, "replacement_cost_cents": 5000000,
             "condition_rating": 3})
        cycle_resp = api.open_refresh_cycle(_facility["id"], CONSULTANT)
        assert cycle_resp.status_code == 201
        assess = api.assess_asset_system(
            system["id"], {"condition_rating": 2, "note": "worn"}, CONSULTANT)
        validate_success(assess, 200)

        data, meta = validate_paginated(
            api.list_system_snapshots(system["id"], CONSULTANT))
        assert len(data) == 1, f"one assess appends exactly one snapshot: {data}"
        snapshot = data[0]
        assert_condition_snapshot(snapshot)
        assert snapshot["condition_rating"] == 2
        # RUL: raw = 25 - (2026-2010) = 9, rating-2 cap -> min(9, 2) = 2.
        assert snapshot["remaining_useful_life_years"] == 2
        assert snapshot["epoch"] == 1, "snapshot stamped with the open epoch"
        assert snapshot["note"] == "worn"
        assert meta["total_count"] == 1


class TestListingEnvelope:
    def test_list_deficiencies_paginates_with_envelope_fields(self, api):
        """PRD §2.3: "Paginated list responses include four fields in the `meta`
        object of the envelope: `limit`, `offset`, `total_count`, and
        `has_more`, so a client can always reconstruct where it sits in the
        full result set."
        PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10 when omitted, accepts a minimum of 1, and is bounded
        above at 100."

        Design: Corner/entities/list_endpoints_paginate_with_envelope_fields
        """
        _facility, system = setup_facility_with_system(
            {"system_category": "HVAC", "name": "S", "install_year": 2015,
             "design_life_years": 20, "replacement_cost_cents": 50000000,
             "condition_rating": 4})
        for i, cost in enumerate((100000, 200000, 300000), start=1):
            create_deficiency(system["id"], description=f"d{i}",
                              cost_estimate_cents=cost, severity=1, urgency=1,
                              recommended_year=2027)

        page1, meta1 = validate_paginated(api.list_deficiencies(
            CONSULTANT, {"asset_system_id": system["id"], "limit": 2,
                         "offset": 0}))
        assert len(page1) == 2, "limit caps the page at 2 rows"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_deficiencies(
            CONSULTANT, {"asset_system_id": system["id"], "limit": 2,
                         "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestImmediateConsistency:
    def test_new_asset_system_visible_in_facility_list_immediately(self, api):
        """PRD §2.9: "Consistency is immediate, not eventual: whenever a child
        mutation changes an input to a parent's derived field, the parent's
        derived fields are recomputed as part of the same operation, and each
        such reconciliation refreshes the parent's `updated_at` and increments
        its `version`."

        Design: Corner/consistency_model/immediate_visibility_of_create_in_list
        """
        facility = create_facility()
        system = validate_success(api.create_asset_system(
            create_asset_system_payload(
                facility["id"], system_category="SITE", name="Fence",
                install_year=2020, design_life_years=15,
                replacement_cost_cents=2000000, condition_rating=5),
            CONSULTANT), 201)
        assert_asset_system(system)

        data, meta = validate_paginated(
            api.list_facility_asset_systems(facility["id"], CONSULTANT))
        assert [row["id"] for row in data] == [system["id"]], (
            "the just-created system appears in the facility-filtered list "
            "within the same request sequence")
        assert meta["total_count"] == 1


class TestErrorEnvelope:
    def test_error_envelope_shape_on_failure(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error. The `message` provides a human-readable
        explanation of what went wrong."

        Design: Corner/errors/error_envelope_shape_on_failure
        """
        resp = api.get_client(NON_EXISTENT_UUID, CONSULTANT)
        error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert error_data["message"].strip(), "message is a non-empty string"
        body = resp.json()
        assert body["response_type"] == "error"
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str)
        assert meta["api_request_id"], "api_request_id present on errors"
        assert isinstance(meta.get("api_request_timestamp"), str)
        assert meta["api_request_timestamp"]


class TestBodyForeignKeys:
    def test_facility_create_with_unknown_client_id_returns_422(self, api):
        """PRD §2.7: "**Body foreign keys** — every foreign-key identifier
        carried in the request body (`client_id`, `facility_id`,
        `asset_system_id`, `capital_plan_id`, `deficiency_id`,
        `funding_scenario_id`, `project_bundle_id`) must reference an existing
        resource; otherwise `ERR_REFERENCE_NOT_FOUND`."

        Design: Corner/validations/body_fk_not_found_returns_reference_error
        """
        resp = api.create_facility(
            create_facility_payload(NON_EXISTENT_UUID, name="F", address="1 Rd",
                                    gross_square_feet=100),
            CONSULTANT,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


class TestFacilityComputedFields:
    def test_fci_computed_fields_correct_after_create(self, api):
        """PRD §2.4: "`current_replacement_value_cents`, the sum of
        `replacement_cost_cents` over that facility's asset systems whose
        lifecycle status is anything other than `RETIRED`; `backlog_cost_cents`,
        the sum of `cost_estimate_cents` over the facility's deficiencies whose
        `remediation_status` is either `OPEN` or `IN_PROGRESS` (the
        deferred-maintenance backlog); and `facility_condition_index`, the ratio
        of the backlog to the current replacement value."
        PRD §2.5: "The `facility_condition_index` on a Facility is rounded
        half-up to exactly 4 decimal places."

        Design: Corner/calculations/fci_computed_fields_correct_after_create
        """
        facility = create_facility()
        sys1 = create_asset_system(
            facility["id"], system_category="HVAC", name="S1",
            install_year=2010, design_life_years=25,
            replacement_cost_cents=1200000000, condition_rating=3)
        sys2 = create_asset_system(
            facility["id"], system_category="ROOF", name="S2",
            install_year=2012, design_life_years=25,
            replacement_cost_cents=800000000, condition_rating=4)
        create_deficiency(sys1["id"], description="d1",
                          cost_estimate_cents=50000000, severity=3, urgency=3,
                          recommended_year=2027)
        create_deficiency(sys2["id"], description="d2",
                          cost_estimate_cents=30000000, severity=3, urgency=3,
                          recommended_year=2028)

        facility = get_facility(facility["id"])
        assert_facility(facility)
        assert facility["current_replacement_value_cents"] == 2000000000
        assert facility["backlog_cost_cents"] == 80000000
        # 80000000 / 2000000000 = 0.04 exactly -> 0.0400 at 4dp.
        assert facility["facility_condition_index"] == pytest.approx(0.04,
                                                                     abs=1e-9)


class TestRecomputeEndpoint:
    def test_recompute_persists_derived_fields_and_bumps_version(self, api):
        """PRD §3.1: "Should the derived fields ever need to be forced back
        into agreement with the underlying rows, a `Consultant` may invoke the
        facility recompute capability, which re-runs the facility condition
        index calculation over the facility's live systems and open
        deficiencies, persists all three derived fields, and increments the
        facility's `version`."
        PRD §2.4: "`version` (integer): starts at 1 and increments by one on
        every mutation of the resource"

        Design: Corner/endpoints/recompute_endpoint_persists_derived_fields
        """
        _facility, system, _deficiency = setup_system_with_deficiency(
            {"description": "d", "cost_estimate_cents": 10000000,
             "severity": 3, "urgency": 3, "recommended_year": 2027},
            {"system_category": "HVAC", "name": "S", "install_year": 2010,
             "design_life_years": 25, "replacement_cost_cents": 100000000,
             "condition_rating": 3})
        before = get_facility(_facility["id"])
        # 10000000 / 100000000 = 0.10 -> 0.1000 at 4dp.
        assert before["facility_condition_index"] == pytest.approx(0.10,
                                                                   abs=1e-9)

        after = validate_success(
            api.recompute_facility(_facility["id"], CONSULTANT))
        assert_facility(after)
        assert after["facility_condition_index"] == pytest.approx(0.10,
                                                                  abs=1e-9)
        assert after["backlog_cost_cents"] == 10000000
        assert after["current_replacement_value_cents"] == 100000000
        assert after["version"] == before["version"] + 1, (
            "recompute is one mutation of the facility: version increments "
            "by exactly one")

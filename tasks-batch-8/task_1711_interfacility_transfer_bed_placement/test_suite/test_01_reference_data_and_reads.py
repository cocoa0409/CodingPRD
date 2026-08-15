"""Reference data, computed defaults, not-found family, pagination, RBAC reads."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_bed,
    assert_facility,
    assert_physician,
    assert_transfer_case,
    create_facility,
    create_physician,
    get_case,
    list_cases,
    make_bed_manager_headers,
    make_quality_reviewer_headers,
    make_receiving_physician_headers,
    make_sending_physician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import COORD, ANY


class TestFacilityCreateComputedDefaults:
    def test_facility_create_computed_defaults(self, api):
        """PRD: "A newly registered facility, having zero beds, starts with
        `diversion_status` `OPEN`, both bed counts at 0, and `occupancy_pct`
        100.0 — the saturation rule's entry condition is checked against the
        no-active-`ALL_UNITS`-event guard, so occupancy alone never stacks a
        second auto-diversion on an existing one."

        Design: Corner/entities/facility_create_computed_defaults_and_input_ignored
        """
        resp = api.create_facility(
            {
                "name": "Solo Clinic",
                "facility_code": "SOLO",
                "trauma_level": "CRITICAL_ACCESS",
                "capabilities": ["TRAUMA"],
            },
            COORD,
        )
        fac = validate_success(resp, 201)
        assert_facility(fac)
        assert fac["diversion_status"] == "OPEN"
        assert fac["operational_bed_count"] == 0
        assert fac["unavailable_bed_count"] == 0
        assert fac["occupancy_pct"] == pytest.approx(100.0), (
            "zero operational beds must pin occupancy_pct to 100.0"
        )
        events, _meta = validate_paginated(
            api.list_facility_diversion_events(fac["id"], ANY)
        )
        assert events == [], "a fresh facility has no diversion events"


class TestBedAndPhysicianDefaults:
    def test_bed_create_default_status_available(self, api):
        """PRD: "registering a bed takes a facility-local `bed_code` such as
        ICU-04, a `unit_type` of `ICU`, `CVICU`, `NICU`, `PICU`, `TELEMETRY`,
        `MED_SURG`, `BURN`, or `ED_HOLD`, and an optional `isolation_capable`
        flag defaulting to false; the bed starts life `AVAILABLE`."
        PRD: "`occupancy_pct` is the unavailable count divided by the
        operational count, multiplied by 100, and rounded half-up to two
        decimal places; when a facility has no operational beds at all,
        `occupancy_pct` is defined as 100.0."

        Design: Corner/entities/bed_create_default_status_available
        """
        fac = create_facility(name="Receiving Trauma Center", facility_code="RCV",
                              trauma_level="LEVEL_1")
        resp = api.create_bed(fac["id"], {"bed_code": "ICU-01", "unit_type": "ICU"},
                              make_bed_manager_headers(fac["id"]))
        bed = validate_success(resp, 201)
        assert_bed(bed)
        assert bed["status"] == "AVAILABLE"
        assert bed["isolation_capable"] is False, "omitted flag defaults to false"

        beds, _meta = validate_paginated(api.list_facility_beds(fac["id"], ANY))
        assert [b["id"] for b in beds] == [bed["id"]], (
            "facility bed listing must contain exactly the created bed"
        )

        fac_after = validate_success(api.get_facility(fac["id"], ANY))
        assert fac_after["operational_bed_count"] == 1
        assert fac_after["occupancy_pct"] == pytest.approx(0.0)

    def test_physician_create_default_on_call(self, api):
        """PRD: "Physicians are registered the same way with a `full_name`, the
        `facility_id` of their home facility, a `specialty` of `EMERGENCY`,
        `CARDIOLOGY`, `NEUROLOGY`, `SURGERY`, `INTENSIVIST`, `PEDIATRICS`, or
        `GENERAL`, and an `is_on_call` flag that defaults to true."

        Design: Corner/entities/physician_create_default_on_call
        """
        fac = create_facility()
        resp = api.create_physician(
            {"full_name": "Dr Default", "facility_id": fac["id"],
             "specialty": "GENERAL"},
            COORD,
        )
        phys = validate_success(resp, 201)
        assert_physician(phys)
        assert phys["is_on_call"] is True, "omitted is_on_call defaults to true"


class TestCaseCreateDefaults:
    def test_case_create_initial_state_and_defaults(self, api):
        """PRD: "A new case sits in `INTAKE` with `negotiation_round` 0,
        `emtala_obligation` `UNDETERMINED`, `emtala_determined_at` null,
        `active_bed_hold_id` null, both receiving references null, and
        `refusal_count` 0."
        PRD: "A transfer begins when a `TransferCoordinator` opens a case with a
        de-identified `patient_ref` token, the `sending_facility_id`, the
        responsible `sending_physician_id`, an `acuity_level` of `CRITICAL`,
        `EMERGENT`, `URGENT`, or `STABLE`, the `required_unit_type` the
        receiving bed must have, a `requires_isolation` flag defaulting to
        false, and the `required_capability` string the receiving facility
        must list."

        Design: Corner/entities/case_create_initial_state_and_defaults
        """
        fac = create_facility()
        phys = create_physician("Dr Send", fac["id"], "EMERGENCY")
        resp = api.create_transfer_case(
            {
                "patient_ref": "PT-INIT-1",
                "sending_facility_id": fac["id"],
                "sending_physician_id": phys["id"],
                "acuity_level": "STABLE",
                "required_unit_type": "MED_SURG",
                "required_capability": "TRAUMA",
            },
            COORD,
        )
        case = validate_success(resp, 201)
        assert_transfer_case(case)
        assert case["status"] == "INTAKE"
        assert case["negotiation_round"] == 0
        assert case["refusal_count"] == 0
        assert case["emtala_obligation"] == "UNDETERMINED"
        assert case["emtala_determined_at"] is None
        assert case["active_bed_hold_id"] is None
        assert case["receiving_facility_id"] is None
        assert case["receiving_physician_id"] is None
        assert case["requires_isolation"] is False

    def test_case_create_missing_required_returns_invalid_request(self, api):
        """PRD: "**Request-body schema** — required fields present, types
        correct, enum members valid, minimum lengths met (a refusal `narrative`
        of at least 50 characters, review `findings` of at least 30
        characters), `ends_at` strictly after `starts_at`, `distance_miles`
        greater than 0, `required_documents` non-empty, and a diversion
        `unit_type` present exactly when `scope` is `SPECIFIC_UNIT` and
        forbidden otherwise (`ERR_INVALID_REQUEST`, `ERR_NARRATIVE_TOO_SHORT`,
        `ERR_FINDINGS_TOO_SHORT`; all 400)."

        Design: Corner/entities/case_create_missing_required_returns_invalid_request
        """
        fac = create_facility()
        phys = create_physician("Dr Send", fac["id"], "EMERGENCY")
        resp = api.create_transfer_case(
            {
                # patient_ref omitted
                "sending_facility_id": fac["id"],
                "sending_physician_id": phys["id"],
                "acuity_level": "STABLE",
                "required_unit_type": "MED_SURG",
                "required_capability": "TRAUMA",
            },
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
        data, meta = list_cases()
        assert data == [], f"no case may be persisted, got {len(data)} rows"

    def test_bed_create_invalid_enum_returns_invalid_request(self, api):
        """PRD: "**Request-body schema** — required fields present, types
        correct, enum members valid, minimum lengths met (a refusal `narrative`
        of at least 50 characters, review `findings` of at least 30
        characters), `ends_at` strictly after `starts_at`, `distance_miles`
        greater than 0, `required_documents` non-empty, and a diversion
        `unit_type` present exactly when `scope` is `SPECIFIC_UNIT` and
        forbidden otherwise (`ERR_INVALID_REQUEST`, `ERR_NARRATIVE_TOO_SHORT`,
        `ERR_FINDINGS_TOO_SHORT`; all 400)."
        PRD: "registering a bed takes a facility-local `bed_code` such as
        ICU-04, a `unit_type` of `ICU`, `CVICU`, `NICU`, `PICU`, `TELEMETRY`,
        `MED_SURG`, `BURN`, or `ED_HOLD`, and an optional `isolation_capable`
        flag defaulting to false; the bed starts life `AVAILABLE`."

        Design: Corner/entities/bed_create_invalid_enum_returns_invalid_request
        """
        fac = create_facility(name="Receiving Trauma Center", facility_code="RCV",
                              trauma_level="LEVEL_1")
        resp = api.create_bed(
            fac["id"], {"bed_code": "X-01", "unit_type": "PARKING_LOT"},
            make_bed_manager_headers(fac["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestNotFoundFamily:
    def test_case_get_not_found_returns_404(self, api):
        """PRD: "**Existence** — path-template identifiers validated left to
        right, so the first missing id in the path produces its own 404, and
        body foreign keys such as `bed_id`, `receiving_facility_id`,
        `receiving_physician_id`, `sending_physician_id`, and
        `sending_facility_id` must exist (`ERR_FACILITY_NOT_FOUND`,
        `ERR_PHYSICIAN_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_BED_NOT_FOUND`,
        `ERR_SCREENING_NOT_FOUND`, `ERR_COMMUNICATION_NOT_FOUND`,
        `ERR_HOLD_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`,
        `ERR_NOTIFICATION_NOT_FOUND`, `ERR_PACKET_NOT_FOUND`,
        `ERR_REVIEW_NOT_FOUND`, `ERR_DIVERSION_NOT_FOUND`; all 404)."

        Design: Corner/entities/case_get_not_found_returns_404
        """
        resp = api.get_transfer_case(NON_EXISTENT_UUID, ANY)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND, 404)

    def test_resource_get_not_found_across_entities(self, api):
        """PRD: "**Existence** — path-template identifiers validated left to
        right, so the first missing id in the path produces its own 404, and
        body foreign keys such as `bed_id`, `receiving_facility_id`,
        `receiving_physician_id`, `sending_physician_id`, and
        `sending_facility_id` must exist (`ERR_FACILITY_NOT_FOUND`,
        `ERR_PHYSICIAN_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_BED_NOT_FOUND`,
        `ERR_SCREENING_NOT_FOUND`, `ERR_COMMUNICATION_NOT_FOUND`,
        `ERR_HOLD_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`,
        `ERR_NOTIFICATION_NOT_FOUND`, `ERR_PACKET_NOT_FOUND`,
        `ERR_REVIEW_NOT_FOUND`, `ERR_DIVERSION_NOT_FOUND`; all 404)."
        PRD: "reading a single record by an unknown id fails with
        `ERR_REFUSAL_RECORD_NOT_FOUND`."

        Design: Corner/entities/resource_get_not_found_across_entities
        """
        u = lambda n: f"00000000-0000-4000-8000-{n:012d}"
        cases = [
            (api.get_bed_hold(u(1), ANY), ApiErrorId.ERR_HOLD_NOT_FOUND),
            (api.get_communication(u(2), ANY), ApiErrorId.ERR_COMMUNICATION_NOT_FOUND),
            (api.get_refusal_record(u(3), ANY), ApiErrorId.ERR_REFUSAL_RECORD_NOT_FOUND),
            (api.get_quality_review(u(4), ANY), ApiErrorId.ERR_REVIEW_NOT_FOUND),
            (api.get_transport_dispatch(u(5), ANY), ApiErrorId.ERR_DISPATCH_NOT_FOUND),
            (api.get_insurance_notification(u(6), ANY), ApiErrorId.ERR_NOTIFICATION_NOT_FOUND),
            (api.get_clinical_packet(u(7), ANY), ApiErrorId.ERR_PACKET_NOT_FOUND),
        ]
        for resp, err_id in cases:
            validate_error(resp, err_id, 404)

        # Mutation endpoints resolve path existence before identity checks.
        resp = api.lift_diversion_event(u(8), make_bed_manager_headers(u(99)))
        validate_error(resp, ApiErrorId.ERR_DIVERSION_NOT_FOUND, 404)
        resp = api.update_bed(u(9), {"status": "OCCUPIED"},
                              make_bed_manager_headers(u(99)))
        validate_error(resp, ApiErrorId.ERR_BED_NOT_FOUND, 404)
        # Sub-resource collection under a missing parent facility.
        resp = api.list_facility_beds(u(10), ANY)
        validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_FOUND, 404)


class TestCaseListPagination:
    def test_case_list_pagination_envelope(self, api):
        """PRD: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter states how many items to skip and defaults to 0."
        PRD: "Paginated list responses carry `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the envelope."
        PRD: "Cases can be listed and filtered by `status`,
        `sending_facility_id`, `receiving_facility_id`, `sending_physician_id`,
        or `receiving_physician_id`."

        Design: Corner/entities/case_list_pagination_envelope
        """
        fac = create_facility()
        phys = create_physician("Dr Send", fac["id"], "EMERGENCY")
        for i in (1, 2, 3):
            api.create_transfer_case(
                {
                    "patient_ref": f"PT-PG-{i}",
                    "sending_facility_id": fac["id"],
                    "sending_physician_id": phys["id"],
                    "acuity_level": "STABLE" if i < 3 else "URGENT",
                    "required_unit_type": "MED_SURG" if i < 3 else "ICU",
                    "required_capability": "TRAUMA",
                },
                COORD,
            )

        page1, meta1 = validate_paginated(
            api.list_transfer_cases(ANY, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_transfer_cases(ANY, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        filtered, meta3 = validate_paginated(api.list_transfer_cases(
            ANY, params={"status": "INTAKE", "sending_physician_id": phys["id"]}))
        assert len(filtered) == 3
        assert meta3["total_count"] == 3
        assert meta3["has_more"] is False


class TestRbac:
    def test_any_role_read_access_allowed(self, api):
        """PRD: "`Any` is a read marker rather than an operating capacity —
        every declared role may read, and all GET endpoints admit `Any`."

        Design: Corner/rbac/any_role_read_access_allowed
        """
        fac = create_facility()
        phys = create_physician("Dr Send", fac["id"], "EMERGENCY")
        fac_r = create_facility(name="Receiving Trauma Center", facility_code="RCV",
                                trauma_level="LEVEL_1")
        case = validate_success(api.create_transfer_case(
            {
                "patient_ref": "PT-RBAC-R",
                "sending_facility_id": fac["id"],
                "sending_physician_id": phys["id"],
                "acuity_level": "STABLE",
                "required_unit_type": "MED_SURG",
                "requires_isolation": False,
                "required_capability": "TRAUMA",
            },
            COORD,
        ), 201)

        readers = [
            COORD,
            make_sending_physician_headers(phys["id"]),
            make_receiving_physician_headers(phys["id"]),
            make_bed_manager_headers(fac_r["id"]),
            make_quality_reviewer_headers(phys["id"]),
            ANY,
        ]
        for headers in readers:
            data = validate_success(api.get_transfer_case(case["id"], headers))
            assert data["id"] == case["id"]
            assert data["emtala_obligation"] == "UNDETERMINED"
            assert data["refusal_count"] == 0

    def test_request_missing_auth_header(self, api):
        """PRD: "A request missing either header, or carrying a role the system
        does not declare, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/request_missing_auth_header
        """
        resp = api.create_facility(
            {
                "name": "No Auth Clinic",
                "facility_code": "NA1",
                "trauma_level": "COMMUNITY",
                "capabilities": [],
            },
            headers={},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)

    def test_wrong_role_denied_on_protected_endpoints(self, api):
        """PRD: "A request whose role is not permitted on the target endpoint is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD: "A request that fails several rules must fail with the earliest
        rule on a fixed ladder; the ordering is part of the contract."

        Design: Corner/validations/wrong_role_denied_on_protected_endpoints
        """
        fac = create_facility(name="Anchor", facility_code="ANC",
                              trauma_level="COMMUNITY", capabilities=[])
        phys = create_physician("Dr Recv", fac["id"], "GENERAL")

        # ReceivingPhysician may not register facilities.
        resp = api.create_facility(
            {"name": "Rogue Facility", "facility_code": "RGE",
             "trauma_level": "COMMUNITY", "capabilities": []},
            make_receiving_physician_headers(phys["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

        # BedManager may not open a transfer case.
        resp = api.create_transfer_case(
            {"patient_ref": "PT-RBAC-1", "sending_facility_id": fac["id"],
             "sending_physician_id": phys["id"], "acuity_level": "STABLE",
             "required_unit_type": "MED_SURG", "required_capability": "TRAUMA"},
            make_bed_manager_headers(fac["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

        # Role gate fires before existence: dispatch on a nonexistent case as
        # QualityReviewer still yields 403, not 404.
        resp = api.create_dispatch(
            NON_EXISTENT_UUID,
            {"mode": "GROUND_BLS", "crew_capability": "BLS", "distance_miles": 5},
            make_quality_reviewer_headers(phys["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

    def test_bed_manager_wrong_facility_rejected(self, api):
        """PRD: "The caller's `X-User-ID` must equal the facility's `id`, or the
        registration is rejected with `ERR_NOT_FACILITY_MANAGER`."
        PRD: "When `X-User-Role` is `BedManager`, `X-User-ID` is the `id` of the
        managed `Facility`; operations scoped to a facility compare the target
        facility's `id` to `X-User-ID`, and a mismatch is rejected with
        `ERR_NOT_FACILITY_MANAGER`."

        Design: Corner/validations/bed_manager_wrong_facility_rejected
        """
        fac_a = create_facility(name="Facility A", facility_code="FA",
                                trauma_level="LEVEL_2")
        fac_b = create_facility(name="Facility B", facility_code="FB",
                                trauma_level="LEVEL_2")

        resp = api.create_bed(fac_b["id"], {"bed_code": "ICU-01", "unit_type": "ICU"},
                              make_bed_manager_headers(fac_a["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FACILITY_MANAGER, 403)

        resp = api.create_diversion_event(
            fac_b["id"],
            {"scope": "ALL_UNITS", "starts_at": "2026-08-02T00:00:00Z",
             "ends_at": "2026-08-02T04:00:00Z",
             "reason": "Attempted cross-facility diversion"},
            make_bed_manager_headers(fac_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FACILITY_MANAGER, 403)

        beds, _ = validate_paginated(api.list_facility_beds(fac_b["id"], ANY))
        assert beds == [], "no bed may be persisted under another manager's facility"
        events, _ = validate_paginated(
            api.list_facility_diversion_events(fac_b["id"], ANY))
        assert events == [], "no diversion may be persisted under another manager's facility"

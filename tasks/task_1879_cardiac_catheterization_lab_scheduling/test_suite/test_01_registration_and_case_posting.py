"""Resource registration, case posting, defaults, reads, and list behavior."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_cath_case,
    assert_cath_lab_room,
    assert_device_lot,
    assert_device_lot_invariants,
    assert_staff_member,
    create_cardiologist,
    create_case_payload,
    create_device_lot_payload,
    create_room_payload,
    create_staff_payload,
    post_case,
    schedule_case_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

SCHEDULER = TEST_USERS["scheduler_headers"]
TECHNOLOGIST = TEST_USERS["technologist_headers"]
NURSE_MANAGER = TEST_USERS["nurse_manager_headers"]


class TestRoomRegistration:
    def test_create_room_with_defaults_returns_201(self, api):
        """PRD §3.1: "when the profile is omitted it defaults to an empty list.
        New rooms come up `ACTIVE`."
        PRD §4: "Endpoints that create a new resource — registering rooms, staff,
        beds, and lots; posting cases; adding staff assignments, device usages, and
        dose entries; opening registry submissions — return `201 Created`."

        Design: Corner/entities/create_room_with_defaults_returns_201
        """
        resp = api.create_room(create_room_payload(room_name="Lab 1"), SCHEDULER)
        room = validate_success(resp, 201)
        assert_cath_lab_room(room)
        assert room["status"] == "ACTIVE"
        assert room["equipment_profile"] == [], "equipment_profile defaults to []"


class TestStaffRegistration:
    def test_create_staff_applies_field_defaults(self, api):
        """PRD §3.1: "Staff are registered with a `full_name`, a `staff_role` of
        `INTERVENTIONAL_CARDIOLOGIST`, `SCRUB_TECHNOLOGIST`, or `CIRCULATING_NURSE`,
        and an optional list of free-form `credentials` that defaults to empty.
        Every member carries an `is_active` flag, initially true, which governs
        whether they may receive new case assignments."

        Design: Corner/entities/create_staff_applies_field_defaults
        """
        resp = api.create_staff(
            create_staff_payload(full_name="Tech One", staff_role="SCRUB_TECHNOLOGIST"),
            SCHEDULER)
        staff = validate_success(resp, 201)
        assert_staff_member(staff)
        assert staff["credentials"] == [], "credentials defaults to []"
        assert staff["is_active"] is True, "is_active is initially true"


class TestCasePosting:
    def test_case_contrast_limit_cap_and_uncapped_values(self, api):
        """PRD §3.2: "The raw allowance is five times the patient's weight in
        kilograms divided by the serum creatinine, and the ceiling is the lesser of
        that raw allowance and a hard cap of 300.0 mL, rounded half-up to one decimal
        place. A 60 kg patient with a creatinine of 1.5 mg/dL receives a ceiling of
        200.0 mL; an 80 kg patient at 1.0 mg/dL would produce a raw allowance of
        400 mL and is therefore capped at 300.0 mL."

        Design: Corner/entities/case_contrast_limit_cap_and_uncapped_values
        """
        physician = create_cardiologist()
        case1 = post_case(physician["id"], patient_mrn="MRN-1",
                          weight_kg=60, serum_creatinine=1.5)
        case2 = post_case(physician["id"], patient_mrn="MRN-2",
                          weight_kg=80, serum_creatinine=1.0)
        assert case1["contrast_limit_ml"] == pytest.approx(200.0, abs=1e-6), \
            "5.0 * 60 / 1.5 = 200.0, under the cap"
        assert case2["contrast_limit_ml"] == pytest.approx(300.0, abs=1e-6), \
            "raw 400.0 capped at 300.0"

    def test_get_case_returns_stored_fields(self, api):
        """PRD §3.2: "A new case begins with `cumulative_contrast_ml` and
        `cumulative_radiation_mgy` at zero, `radiation_alert` false, and
        `bump_count` at zero."
        PRD §3.2: "The raw allowance is five times the patient's weight in kilograms
        divided by the serum creatinine, and the ceiling is the lesser of that raw
        allowance and a hard cap of 300.0 mL, rounded half-up to one decimal place."
        PRD §4: "| GET | `/cath-lab/cases/{id}` | Get one cath case | All roles |"

        Design: Corner/endpoints/get_case_returns_stored_fields
        """
        physician = create_cardiologist()
        created = post_case(physician["id"], patient_mrn="MRN-1", priority="ELECTIVE",
                            weight_kg=70, serum_creatinine=1.0,
                            equipment_needs=["IVUS"])
        # Any role may read; here the RecoveryNurseManager.
        fetched = validate_success(api.get_case(created["id"], NURSE_MANAGER))
        assert_cath_case(fetched)
        assert fetched["patient_mrn"] == "MRN-1"
        assert fetched["procedure_type"] == "PCI"
        assert fetched["priority"] == "ELECTIVE"
        assert fetched["equipment_needs"] == ["IVUS"]
        assert fetched["contrast_limit_ml"] == pytest.approx(300.0, abs=1e-6), \
            "5.0 * 70 / 1.0 = 350, capped at 300.0"
        assert fetched["cumulative_contrast_ml"] == 0
        assert fetched["cumulative_radiation_mgy"] == 0
        assert fetched["radiation_alert"] is False
        assert fetched["bump_count"] == 0
        assert fetched["auc_status"] == "NOT_DOCUMENTED"


class TestNotFound:
    def test_get_case_not_found_returns_404(self, api):
        """PRD §2.8: "Identifiers embedded in a request path are validated in a
        strict left-to-right order, and the request is rejected with the not-found
        error of the first identifier that fails to resolve: an unknown room yields
        `ERR_ROOM_NOT_FOUND`, a staff member `ERR_STAFF_NOT_FOUND`, a case
        `ERR_CASE_NOT_FOUND`, a device lot `ERR_LOT_NOT_FOUND`, a recovery bed
        `ERR_BED_NOT_FOUND`, a staff assignment `ERR_ASSIGNMENT_NOT_FOUND`, a device
        usage `ERR_USAGE_NOT_FOUND`, a dose record `ERR_DOSE_RECORD_NOT_FOUND`, and
        a registry submission `ERR_SUBMISSION_NOT_FOUND` — all HTTP 404."

        Design: Corner/entities/get_case_not_found_returns_404
        """
        resp = api.get_case(NON_EXISTENT_UUID, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND, expected_status=404)

    def test_get_device_lot_not_found_returns_404(self, api):
        """PRD §2.8: "Identifiers embedded in a request path are validated in a
        strict left-to-right order, and the request is rejected with the not-found
        error of the first identifier that fails to resolve: an unknown room yields
        `ERR_ROOM_NOT_FOUND`, a staff member `ERR_STAFF_NOT_FOUND`, a case
        `ERR_CASE_NOT_FOUND`, a device lot `ERR_LOT_NOT_FOUND`, a recovery bed
        `ERR_BED_NOT_FOUND`, a staff assignment `ERR_ASSIGNMENT_NOT_FOUND`, a device
        usage `ERR_USAGE_NOT_FOUND`, a dose record `ERR_DOSE_RECORD_NOT_FOUND`, and
        a registry submission `ERR_SUBMISSION_NOT_FOUND` — all HTTP 404."

        Design: Corner/entities/get_device_lot_not_found_returns_404
        """
        resp = api.get_device_lot(NON_EXISTENT_UUID, TECHNOLOGIST)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_FOUND, expected_status=404)


class TestCaseShapeValidation:
    def test_create_case_missing_required_patient_mrn_returns_invalid_request(
            self, api):
        """PRD §2.10: "Fourth, on every mutating call, request shape is validated:
        required fields present, types correct, enum values in domain, numeric
        ranges respected (`weight_kg` and `serum_creatinine` greater than zero, a
        reservation or restock `quantity` of at least one, stock counts and
        thresholds at zero or more), and the conditional requirements met — a STEMI
        posting carries `scheduled_start`, a contrast entry carries `contrast_ml`, a
        radiation entry carries `fluoroscopy_mgy` and `cine_mgy`, a rejection
        decision carries `rejection_reason`, and no status is set to the value it
        already holds. Shape failures are `ERR_INVALID_REQUEST`."
        PRD §3.2: "Posting a case captures the patient context: the `patient_mrn`,
        a `procedure_type` of `DIAGNOSTIC_CATHETERIZATION`, `PCI`, `STEMI_PCI`,
        `DEVICE_IMPLANT`, or `EP_STUDY`, a `priority` of `ELECTIVE`, `URGENT`, or
        `STEMI`, the `performing_physician_id`, the patient's `weight_kg`, and the
        `serum_creatinine`."

        Design: Corner/entities/create_case_missing_required_patient_mrn_returns_invalid_request
        """
        physician = create_cardiologist()
        payload = create_case_payload(performing_physician_id=physician["id"])
        del payload["patient_mrn"]
        resp = api.create_case(payload, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_create_case_invalid_procedure_enum_returns_invalid_request(self, api):
        """PRD §3.2: "a `procedure_type` of `DIAGNOSTIC_CATHETERIZATION`, `PCI`,
        `STEMI_PCI`, `DEVICE_IMPLANT`, or `EP_STUDY`"
        PRD §2.10: "Fourth, on every mutating call, request shape is validated:
        required fields present, types correct, enum values in domain, numeric
        ranges respected (`weight_kg` and `serum_creatinine` greater than zero, a
        reservation or restock `quantity` of at least one, stock counts and
        thresholds at zero or more), and the conditional requirements met — a STEMI
        posting carries `scheduled_start`, a contrast entry carries `contrast_ml`,
        a radiation entry carries `fluoroscopy_mgy` and `cine_mgy`, a rejection
        decision carries `rejection_reason`, and no status is set to the value it
        already holds. Shape failures are `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_case_invalid_procedure_enum_returns_invalid_request
        """
        physician = create_cardiologist()
        payload = create_case_payload(performing_physician_id=physician["id"],
                                      procedure_type="ANGIOPLASTY_BAD")
        resp = api.create_case(payload, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_create_case_zero_weight_returns_invalid_request(self, api):
        """PRD §3.2: "Both clinical measurements must be greater than zero."
        PRD §2.10: "Fourth, on every mutating call, request shape is validated:
        required fields present, types correct, enum values in domain, numeric
        ranges respected (`weight_kg` and `serum_creatinine` greater than zero, a
        reservation or restock `quantity` of at least one, stock counts and
        thresholds at zero or more), and the conditional requirements met — a STEMI
        posting carries `scheduled_start`, a contrast entry carries `contrast_ml`,
        a radiation entry carries `fluoroscopy_mgy` and `cine_mgy`, a rejection
        decision carries `rejection_reason`, and no status is set to the value it
        already holds. Shape failures are `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_case_zero_weight_returns_invalid_request
        """
        physician = create_cardiologist()
        payload = create_case_payload(performing_physician_id=physician["id"],
                                      weight_kg=0)
        resp = api.create_case(payload, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_stemi_create_missing_scheduled_start_returns_invalid_request(self, api):
        """PRD §3.2: "A STEMI posting must carry `scheduled_start`; without it the
        request fails shape validation with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/stemi_create_missing_scheduled_start_returns_invalid_request
        """
        physician = create_cardiologist()
        api.create_room(create_room_payload(room_name="Lab 1"), SCHEDULER)
        payload = create_case_payload(
            patient_mrn="MRN-S", procedure_type="STEMI_PCI", priority="STEMI",
            performing_physician_id=physician["id"], weight_kg=80,
            serum_creatinine=1.1)
        assert "scheduled_start" not in payload
        resp = api.create_case(payload, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
        _, meta = validate_paginated(api.list_cases(SCHEDULER))
        assert meta["total_count"] == 0, "a rejected posting persists no case"


class TestListing:
    def test_list_cases_pagination_envelope_and_defaults(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; when omitted it defaults to 10, and it accepts a minimum of 1 and
        a maximum of 100. The `offset` parameter sets how many items are skipped and
        defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_cases_pagination_envelope_and_defaults
        """
        physician = create_cardiologist()
        for i in range(3):
            post_case(physician["id"], patient_mrn=f"MRN-{i + 1}")

        # Default page (limit omitted -> 10): all 3 in one page.
        page0, meta0 = validate_paginated(api.list_cases(SCHEDULER))
        assert meta0["limit"] == 10, "the limit parameter defaults to 10"
        assert meta0["total_count"] == 3
        assert meta0["has_more"] is False

        page1, meta1 = validate_paginated(
            api.list_cases(SCHEDULER, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_cases(SCHEDULER, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        # Envelope shape on a success response (PRD §2.2).
        body = api.list_cases(SCHEDULER).json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["response_type"] == "array"
        assert isinstance(body["data"], list)

    def test_list_device_lots_filter_by_status(self, api):
        """PRD §3.5: "The lot list can be filtered by `device_type`, `status`, or
        `ownership`."
        PRD §3.5: "The lot's `status` is fully derived from those figures after
        every mutation that touches either counter — creation, reservation, release,
        implantation, restock: `DEPLETED` when nothing is available; otherwise
        `LOW_STOCK` when the available figure is below the `reorder_threshold`;
        otherwise `ACTIVE`. The boundary belongs to `ACTIVE` — availability exactly
        equal to the reorder threshold is healthy."

        Design: Corner/entities/list_device_lots_filter_by_status
        """
        lot_a = validate_success(api.create_device_lot(
            create_device_lot_payload(lot_number="LOT-A", quantity_on_hand=3,
                                      reorder_threshold=3),
            TECHNOLOGIST), 201)
        lot_b = validate_success(api.create_device_lot(
            create_device_lot_payload(device_type="STENT_BMS", model_number="BS-1",
                                      lot_number="LOT-B", ownership="CONSIGNMENT",
                                      quantity_on_hand=1, reorder_threshold=2),
            TECHNOLOGIST), 201)
        assert lot_a["status"] == "ACTIVE", "available 3 >= threshold 3 (boundary)"
        assert lot_b["status"] == "LOW_STOCK", "0 < available 1 < threshold 2"
        assert_device_lot_invariants(lot_a)
        assert_device_lot_invariants(lot_b)

        data, meta = validate_paginated(
            api.list_device_lots(TECHNOLOGIST, params={"status": "LOW_STOCK"}))
        assert meta["total_count"] == 1
        assert [lot["id"] for lot in data] == [lot_b["id"]]
        assert_device_lot(data[0])


class TestBodyForeignKeys:
    def test_create_case_with_unknown_performing_physician_returns_not_found(
            self, api):
        """PRD §2.8: "Foreign keys carried in request bodies receive the same
        treatment after the path identifiers pass: `lab_id`, `bed_id`, `staff_id`,
        `lot_id`, `performing_physician_id`, and `ordering_physician_id` each
        resolve against the corresponding resource and fail with that resource's
        not-found error."

        Design: Corner/entities/create_case_with_unknown_performing_physician_returns_not_found
        """
        payload = create_case_payload(performing_physician_id=NON_EXISTENT_UUID)
        resp = api.create_case(payload, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_STAFF_NOT_FOUND, expected_status=404)

    def test_schedule_with_unknown_lab_id_returns_not_found(self, api):
        """PRD §2.8: "Foreign keys carried in request bodies receive the same
        treatment after the path identifiers pass: `lab_id`, `bed_id`, `staff_id`,
        `lot_id`, `performing_physician_id`, and `ordering_physician_id` each
        resolve against the corresponding resource and fail with that resource's
        not-found error. Existence always precedes any business rule."

        Design: Corner/entities/schedule_with_unknown_lab_id_returns_not_found
        """
        physician = create_cardiologist()
        case = post_case(physician["id"])
        resp = api.schedule_case(
            case["id"],
            schedule_case_payload(NON_EXISTENT_UUID, "2026-08-10T09:00:00Z"),
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_FOUND, expected_status=404)
        current = validate_success(api.get_case(case["id"], SCHEDULER))
        assert current["status"] == "POSTED", "a rejected schedule changes nothing"

"""Vendor contracts (buffered closed-interval overlap, cancellation fees,
deliverable gating, vendor ownership) and accessibility accommodations."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_ceremony, import_graduate, create_vendor_contract_payload,
    create_accommodation_request_payload, set_clock, get_ceremony,
    make_graduate_headers, make_coordinator_headers, make_vendor_headers,
    TEST_USERS,
)

CHAIR = TEST_USERS["committee_chair_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
COORD_A = "coord-a"


class TestVendorBufferedClosedOverlap:
    def test_overlapping_same_type_contract_rejected(self, api):
        """PRD §3.8: "two contracts for the same ceremony and the same
        `vendor_type` conflict when their buffered coverage windows overlap,
        where each window is extended by its `setup_buffer_minutes` on
        **both** sides and treated as a closed interval — windows that merely
        touch at a boundary still conflict."
        PRD §3.8: "a genuine overlap is rejected with
        `ERR_VENDOR_COVERAGE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/vendor_buffered_closed_overlap
        """
        ctx = setup_ceremony()
        ceremony_id = ctx["ceremony"]["id"]
        first = validate_success(
            api.create_vendor_contract(
                ceremony_id,
                create_vendor_contract_payload(
                    vendor_user_id="vendor-1",
                    coverage_start_utc="2026-06-01T12:00:00Z",
                    coverage_end_utc="2026-06-01T15:00:00Z",
                    setup_buffer_minutes=30, fee_cents=100000),
                CHAIR), 201)
        assert first["status"] == "DRAFT"

        # buffered windows [11:30, 15:30] and [15:00, 18:30] intersect
        res = api.create_vendor_contract(
            ceremony_id,
            create_vendor_contract_payload(
                vendor_user_id="vendor-2",
                coverage_start_utc="2026-06-01T15:30:00Z",
                coverage_end_utc="2026-06-01T18:00:00Z",
                setup_buffer_minutes=30, fee_cents=80000),
            CHAIR)
        validate_error(res, ApiErrorId.ERR_VENDOR_COVERAGE_OVERLAP)
        assert res.status_code == 409

    def test_other_vendor_type_same_window_allowed(self, api):
        """PRD §3.8: "two contracts for the same ceremony and the same
        `vendor_type` conflict when their buffered coverage windows overlap".

        Design: Difficulty/resource_temporal_overlap/vendor_buffered_closed_overlap
        """
        ctx = setup_ceremony()
        ceremony_id = ctx["ceremony"]["id"]
        validate_success(
            api.create_vendor_contract(
                ceremony_id,
                create_vendor_contract_payload(
                    vendor_type="LIVESTREAM", vendor_user_id="vendor-1",
                    coverage_start_utc="2026-06-01T12:00:00Z",
                    coverage_end_utc="2026-06-01T15:00:00Z",
                    setup_buffer_minutes=30, fee_cents=100000),
                CHAIR), 201)
        third = validate_success(
            api.create_vendor_contract(
                ceremony_id,
                create_vendor_contract_payload(
                    vendor_type="PHOTOGRAPHY", vendor_user_id="vendor-3",
                    coverage_start_utc="2026-06-01T15:30:00Z",
                    coverage_end_utc="2026-06-01T18:00:00Z",
                    setup_buffer_minutes=30, fee_cents=50000),
                CHAIR), 201)
        assert third["vendor_type"] == "PHOTOGRAPHY"
        assert third["status"] == "DRAFT"


class TestVendorCancellationFeeBoundary:
    def test_vendor_cancellation_fee_time_boundary(self, api):
        """PRD §3.8: "cancelling strictly before `coverage_start_utc` costs ten
        percent of `fee_cents` rounded half up to a whole cent, while
        cancelling at or after `coverage_start_utc` costs fifty percent rounded
        half up — the boundary instant itself is charged at the fifty-percent
        rate."

        Design: Corner/calculations/vendor_cancellation_fee_time_boundary
        """
        ctx = setup_ceremony()
        ceremony_id = ctx["ceremony"]["id"]
        c1 = validate_success(
            api.create_vendor_contract(
                ceremony_id,
                create_vendor_contract_payload(
                    vendor_type="LIVESTREAM", vendor_user_id="vendor-1",
                    coverage_start_utc="2026-06-01T12:00:00Z",
                    coverage_end_utc="2026-06-01T15:00:00Z",
                    setup_buffer_minutes=30, fee_cents=10000),
                CHAIR), 201)
        c2 = validate_success(
            api.create_vendor_contract(
                ceremony_id,
                create_vendor_contract_payload(
                    vendor_type="PHOTOGRAPHY", vendor_user_id="vendor-2",
                    coverage_start_utc="2026-06-02T12:00:00Z",
                    coverage_end_utc="2026-06-02T15:00:00Z",
                    setup_buffer_minutes=30, fee_cents=10000),
                CHAIR), 201)

        set_clock("2026-05-20T00:00:00Z")  # strictly before C1 coverage start
        cancelled1 = validate_success(api.cancel_vendor_contract(c1["id"], CHAIR), 200)
        assert cancelled1["cancellation_fee_cents"] == 1000  # 10%
        assert cancelled1["status"] == "CANCELLED"

        set_clock("2026-06-02T12:00:00Z")  # exactly at C2 coverage start (>= boundary)
        cancelled2 = validate_success(api.cancel_vendor_contract(c2["id"], CHAIR), 200)
        assert cancelled2["cancellation_fee_cents"] == 5000  # 50%
        assert cancelled2["status"] == "CANCELLED"


class TestVendorDeliverableAndOwnership:
    def test_vendor_settle_without_deliverable_returns_error(self, api):
        """PRD §3.8: "an `ACTIVE` contract moves to the terminal `SETTLED` only
        when a `deliverable_url` has been submitted; settling before submission
        is rejected with `ERR_VENDOR_DELIVERABLE_MISSING`."

        Design: Corner/validations/vendor_settle_without_deliverable_returns_error
        """
        ctx = setup_ceremony(lock_audit=True)
        contract = validate_success(
            api.create_vendor_contract(
                ctx["ceremony"]["id"],
                create_vendor_contract_payload(vendor_user_id="vendor-1"),
                CHAIR), 201)
        activated = validate_success(api.activate_vendor_contract(contract["id"], CHAIR), 200)
        assert activated["status"] == "ACTIVE"

        res = api.settle_vendor_contract(contract["id"], CHAIR)
        validate_error(res, ApiErrorId.ERR_VENDOR_DELIVERABLE_MISSING)
        assert res.status_code == 409
        after = validate_success(api.get_vendor_contract(contract["id"], CHAIR), 200)
        assert after["status"] == "ACTIVE"

    def test_vendor_cannot_submit_for_other_contract_returns_forbidden(self, api):
        """PRD §2.1: "when a `Vendor` submits a deliverable, the target
        contract's `vendor_user_id` must equal the caller's `X-User-ID`, and a
        mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP`."

        Design: Corner/validations/vendor_cannot_submit_for_other_contract_returns_forbidden
        """
        ctx = setup_ceremony()
        contract = validate_success(
            api.create_vendor_contract(
                ctx["ceremony"]["id"],
                create_vendor_contract_payload(vendor_user_id="vendor-1"),
                CHAIR), 201)
        res = api.submit_deliverable(
            contract["id"], {"deliverable_url": "https://cdn.example.com/stream.mp4"},
            make_vendor_headers("vendor-2"))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
        assert res.status_code == 403


class TestAccommodationRequests:
    def test_sod_accommodation_fulfill_by_approver_returns_segregation_error(self, api):
        """PRD §2.7: "An accommodation request may be fulfilled only by a
        `VenueCoordinator` whose identifier differs from the request's
        `approved_by_user_id`."
        PRD §2.7: "In each pair, the second step is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when the same `X-User-ID`
        performs both".

        Design: Corner/validations/sod_accommodation_fulfill_by_approver_returns_segregation_error
        """
        ctx = setup_ceremony()
        ceremony_id = ctx["ceremony"]["id"]
        graduate = import_graduate(ceremony_id, full_name="Accom Ada", email="ada@x.edu")
        request = validate_success(
            api.create_accommodation_request(
                graduate["id"],
                create_accommodation_request_payload(ceremony_id, "SIGN_INTERPRETER"),
                make_graduate_headers(graduate["id"])), 201)
        approved = validate_success(
            api.approve_accommodation(request["id"], make_coordinator_headers(COORD_A)), 200)
        assert approved["status"] == "APPROVED"

        res = api.fulfill_accommodation(request["id"], make_coordinator_headers(COORD_A))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert res.status_code == 403  # fulfiller == approved_by_user_id

        after = validate_success(api.get_accommodation_request(request["id"], REGISTRAR), 200)
        assert after["status"] == "APPROVED"
        assert after["fulfilled_by_user_id"] is None

    def test_accommodation_invalid_enum_returns_invalid_request(self, api):
        """PRD §3.5: "a `request_type` of `WHEELCHAIR_SEAT`,
        `SIGN_INTERPRETER`, `ASSISTIVE_LISTENING`, or `SERVICE_ANIMAL`".
        PRD §2.11: "Body schema — required fields present, types valid, enum
        values inside their declared domains, and ranges valid (a requested
        ticket count of at least one, an `end_utc` strictly after its
        `start_utc`, capacities of at least one, amounts of at least zero),
        else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/accommodation_invalid_enum_returns_invalid_request
        """
        ctx = setup_ceremony()
        ceremony_id = ctx["ceremony"]["id"]
        graduate = import_graduate(ceremony_id, full_name="Enum Ed", email="ed@x.edu")
        res = api.create_accommodation_request(
            graduate["id"],
            create_accommodation_request_payload(ceremony_id, "VALET_PARKING"),
            make_graduate_headers(graduate["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
        assert res.status_code == 400

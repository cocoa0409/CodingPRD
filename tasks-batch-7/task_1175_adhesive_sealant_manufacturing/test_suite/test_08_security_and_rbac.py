"""RBAC enforcement, segregation of duties, ownership scoping, auth headers,
and the validation pipeline's outer stages."""
from test_helpers import (
    ApiErrorId,
    create_distributor,
    create_formulation_request_payload,
    create_vessel,
    lot_under_review_with_passing_full,
    make_distributor_headers,
    record_test,
    set_clock,
    setup_released_lot,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestUserContext:
    def test_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "A request in which either header is absent, or in which the declared role is not one of the recognized roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        set_clock()
        resp = api.list_formulations(headers=None)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_error_envelope_shape_on_404(self, api, plant_manager_headers):
        """PRD §2.2: "- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "- The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD §2.2: "- The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/errors/error_envelope_shape_on_404
        """
        set_clock()
        resp = api.get_formulation("00000000-0000-4000-8000-000000000000", plant_manager_headers)
        assert resp.status_code == 404
        body = resp.json()
        assert isinstance(body["meta"]["api_request_id"], str) and body["meta"]["api_request_id"]
        assert body["meta"]["api_request_timestamp"]
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]


class TestValidationOrdering:
    def test_schema_error_beats_not_found(self, api, batch_operator_headers, plant_manager_headers):
        """PRD §2.5: "Every write request is screened by an ordered validation pipeline, and the order matters because several failures can co-exist on one request."
        PRD §2.5: "3. **Request-body schema.** Required fields must be present, types and enum members must be valid, `mix_end_at` must be strictly after `mix_start_at`, `planned_end_at` must be at or after `planned_start_at`, integers flagged as positive must be positive, a `QUICK` cure test must carry exactly 1 specimen and a `FULL` cure test exactly 5, and `agreement_id` must be present on a shipment exactly when `shipment_kind` is `CONSIGNMENT` or `CONSIGNMENT_REPLENISHMENT` and must be absent for `SALE`. Violations surface as `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §2.5: "4. **Existence.** Path identifiers are validated left to right, then foreign-key identifiers in the request body; any miss returns `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/schema_error_beats_not_found
        """
        set_clock()
        vessel = create_vessel("V-PRIO", capacity_liters=100)
        resp = api.create_batch(
            {
                "formulation_id": "00000000-0000-4000-8000-000000000000",
                "vessel_id": vessel["id"],
                "mix_start_at": "2026-05-01T09:00:00Z",
                "mix_end_at": "2026-05-01T08:00:00Z",  # schema-invalid window
                "batch_volume_ml": 1000,
            },
            batch_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.json()["data"]["error_id"] != "ERR_NOT_FOUND"

    def test_release_nonexistent_lot_returns_404(self, api, qa_manager_headers):
        """PRD §2.5: "4. **Existence.** Path identifiers are validated left to right, then foreign-key identifiers in the request body; any miss returns `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/release_nonexistent_lot_returns_404
        """
        set_clock()
        resp = api.release_lot("00000000-0000-4000-8000-000000000000", qa_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestRbacDeny:
    def test_batch_operator_cannot_release_lot(self, api, batch_operator_headers, qa_manager_headers):
        """PRD §2.1: "Once the headers are validated, the role is checked against the operation's authorization; an attempt to perform an action outside the role's designated scope is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/batch_operator_cannot_release_lot
        """
        # Build a lot in UNDER_REVIEW directly (mixed batch + accepted passing
        # FULL test, never released), then attempt the release as BatchOperator.
        set_clock()
        from test_helpers import create_formulation, create_mixed_batch
        formulation = create_formulation("EPX-RB1", activate=True)
        vessel = create_vessel("V-RB1", capacity_liters=100)
        batch = create_mixed_batch(formulation["id"], vessel["id"], batch_volume_ml=5000)
        lot_id = batch["production_lot_id"]
        lot_under_review_with_passing_full(lot_id)

        resp = api.release_lot(lot_id, batch_operator_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        lot = validate_success(api.get_production_lot(lot_id, qa_manager_headers))
        assert lot["qa_status"] == "UNDER_REVIEW"

    def test_qa_technician_cannot_accept_test(self, api, qa_technician_headers, qa_manager_headers):
        """PRD §2.1: "Once the headers are validated, the role is checked against the operation's authorization; an attempt to perform an action outside the role's designated scope is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/qa_technician_cannot_accept_test
        """
        set_clock()
        from test_helpers import create_formulation, create_mixed_batch, create_vessel
        formulation = create_formulation("EPX-RB2", activate=True)
        vessel = create_vessel("V-RB2", capacity_liters=100)
        batch = create_mixed_batch(formulation["id"], vessel["id"], batch_volume_ml=5000)
        lot_id = batch["production_lot_id"]
        test = record_test(lot_id, method="QUICK", specimens=[12.4])

        resp = api.accept_cure_test(test["id"], qa_technician_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        after = validate_success(api.get_cure_test(test["id"], qa_manager_headers))
        assert after["status"] == "RECORDED"

    def test_distributor_cannot_respond_for_other_distributor(self, api, tech_service_headers):
        """PRD §2.1: "For the `Distributor` role, `X-User-ID` is the `id` of the acting `Distributor` record; ownership checks on any resource that references a `Distributor` compare the resource's foreign-key field to `X-User-ID`."
        PRD §3.7: "The owning distributor answers an information request by calling respond, which cycles the request from `NEEDS_INFO` back into `TECH_REVIEW` and records the payload's `response_note`; only the distributor whose `distributor_id` owns the request may respond, otherwise `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/distributor_cannot_respond_for_other_distributor
        """
        dist_a = create_distributor(name="Dist A", contact_email="a@x.com")
        dist_b = create_distributor(name="Dist B", contact_email="b@x.com")
        request = validate_success(
            api.create_formulation_request(
                create_formulation_request_payload(
                    dist_a["id"], contact_name="Ana", target_substrate="glass",
                    required_bond_strength_mpa=11.0, application_notes="optically clear",
                ),
                make_distributor_headers(dist_a["id"]),
            ),
            expected_status=201,
        )
        validate_success(api.start_review(request["id"], tech_service_headers))
        validate_success(api.request_info(request["id"], {"info_request_note": "UV stability?"}, tech_service_headers))

        resp = api.respond(
            request["id"], {"response_note": "intruder reply"}, make_distributor_headers(dist_b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        after = validate_success(api.get_formulation_request(request["id"], tech_service_headers))
        assert after["status"] == "NEEDS_INFO"


class TestSegregationOfDuties:
    def test_segregation_of_duties_same_user_release_returns_403(self, api, qa_manager_headers):
        """PRD §3.6: "segregation of duties must hold between the releaser and the recording technician (else `ERR_SEGREGATION_OF_DUTIES`)"

        Design: Corner/rbac/segregation_of_duties_same_user_release_returns_403
        """
        # Lot in UNDER_REVIEW; the ACCEPTED test's technician is tech-1.
        set_clock()
        from test_helpers import create_formulation, create_mixed_batch
        formulation = create_formulation("EPX-SOD", activate=True)
        vessel = create_vessel("V-SOD", capacity_liters=100)
        batch = create_mixed_batch(formulation["id"], vessel["id"], batch_volume_ml=5000)
        lot_id = batch["production_lot_id"]
        lot_under_review_with_passing_full(lot_id, technician_id="tech-1")

        # Releasing with the SAME user id as the recording technician is denied
        # even with the correct QAManager role.
        from test_helpers import make_qa_manager_headers
        resp = api.release_lot(lot_id, make_qa_manager_headers("tech-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        lot = validate_success(api.get_production_lot(lot_id, qa_manager_headers))
        assert lot["qa_status"] == "UNDER_REVIEW"


class TestDistributorListingScope:
    def test_distributor_listing_scoped_to_own_requests(self, api):
        """PRD §3.7: "When listing requests, a `Distributor`-role caller sees only rows whose `distributor_id` matches their own `X-User-ID`; the listing supports `distributor_id` and `resulting_formulation_id` filters."

        Design: Corner/rbac/distributor_listing_scoped_to_own_requests
        """
        dist_a = create_distributor(name="Dist SA", contact_email="sa@x.com")
        dist_b = create_distributor(name="Dist SB", contact_email="sb@x.com")
        validate_success(
            api.create_formulation_request(
                create_formulation_request_payload(
                    dist_a["id"], contact_name="Ana", target_substrate="glass",
                    required_bond_strength_mpa=11.0, application_notes="clear",
                ),
                make_distributor_headers(dist_a["id"]),
            ),
            expected_status=201,
        )
        validate_success(
            api.create_formulation_request(
                create_formulation_request_payload(
                    dist_b["id"], contact_name="Bob", target_substrate="wood",
                    required_bond_strength_mpa=9.0, application_notes="fast set",
                ),
                make_distributor_headers(dist_b["id"]),
            ),
            expected_status=201,
        )

        data, meta = validate_paginated(
            api.list_formulation_requests(make_distributor_headers(dist_a["id"]))
        )
        assert meta["total_count"] == 1
        assert data[0]["distributor_id"] == dist_a["id"]

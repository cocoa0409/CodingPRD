"""Circuit registration, response envelope, pagination, and reverse-FK reads.

Covers circuit creation defaults and guards, the fixed success/error
envelopes, list pagination with filters, and parent->child sub-resource
reads (PRD §2.2, §2.3, §3.1, §4).
"""
import pytest

from test_helpers import (
    api_client,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    assert_circuit,
    create_circuit_payload,
    create_window_payload,
    create_job_payload,
    create_circuit,
    create_window,
    approve_window,
    create_job,
)

ADMIN = TEST_USERS["system_admin_headers"]
PLANNER = TEST_USERS["network_planner_headers"]
ENGINEER = TEST_USERS["asset_engineer_headers"]


class TestCircuitCreation:
    def test_create_returns_system_defaults_and_envelope(self, api):
        """PRD §3.1: "A newly registered circuit begins in `IN_SERVICE` status
        with every counter at zero: `unresolved_fault_count`,
        `resolved_fault_count_24m`, `approved_outage_minutes_total`, and
        `splice_count` all start at 0, while `current_health_index` and
        `current_health_band` remain null until the first health assessment is
        adopted, and `replacement_recommended` starts false."
        PRD §2.5: "Every persisted resource carries an `id` that is a
        server-minted UUID with no type prefix."

        Design: Corner/entities/circuit_create_defaults_and_envelope
        """
        payload = create_circuit_payload(
            circuit_ref="CKT-E1", voltage_class="KV_35", length_m=3200,
            installation_year=2008, calibrated_velocity_factor=0.55,
        )
        resp = api.create_circuit(payload, ADMIN)
        data = validate_success(resp, 201)
        body = resp.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "api_request_id must start with req_ (PRD §2.2)"
        )
        assert_circuit(data)
        assert data["status"] == "IN_SERVICE"
        assert data["unresolved_fault_count"] == 0
        assert data["resolved_fault_count_24m"] == 0
        assert data["splice_count"] == 0
        assert data["approved_outage_minutes_total"] == 0
        assert data["current_health_index"] is None
        assert data["current_health_band"] is None
        assert data["replacement_recommended"] is False
        assert isinstance(data["version"], int) and data["version"] >= 1

    def test_create_missing_required_field_returns_invalid_request(self, api):
        """PRD §3.1: "A `SystemAdmin` registers each cable circuit with a
        contractor-side `circuit_ref`, a `voltage_class`, the circuit's
        `length_m` in metres, its `installation_year`, and optionally a
        site-calibrated `calibrated_velocity_factor`."
        PRD §2.7: "Any violation yields `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/circuit_create_missing_required_returns_invalid_request
        """
        payload = {
            "circuit_ref": "CKT-E3",
            "voltage_class": "KV_15",
            "installation_year": 2015,
        }
        resp = api.create_circuit(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_duplicate_circuit_ref_rejected(self, api):
        """PRD §3.1: "The `circuit_ref` must be unique across all registered
        circuits; a duplicate is rejected with `ERR_DUPLICATE_CIRCUIT_REF`."

        Design: Corner/entities/circuit_create_duplicate_ref_rejected
        """
        first = create_circuit("CKT-E2", "KV_15", 1000, 2015)
        assert first["circuit_ref"] == "CKT-E2"
        resp = api.create_circuit(
            create_circuit_payload(
                circuit_ref="CKT-E2", voltage_class="KV_69",
                length_m=900, installation_year=2022,
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CIRCUIT_REF)
        # The duplicate must not exist: only one circuit lists.
        data, meta = validate_paginated(api.list_circuits(PLANNER))
        assert meta["total_count"] == 1

    def test_create_ignores_client_supplied_system_fields(self, api):
        """PRD §3.1: "A newly registered circuit begins in `IN_SERVICE` status
        with every counter at zero: `unresolved_fault_count`,
        `resolved_fault_count_24m`, `approved_outage_minutes_total`, and
        `splice_count` all start at 0" — registration input is `circuit_ref`,
        `voltage_class`, `length_m`, `installation_year`, and optionally
        `calibrated_velocity_factor`; status and counters are system-managed.

        Design: Corner/entities/circuit_create_system_fields_input_ignored
        """
        payload = create_circuit_payload(
            circuit_ref="CKT-E4", voltage_class="KV_15", length_m=1000,
            installation_year=2015,
        )
        payload["status"] = "RESTORING"
        payload["unresolved_fault_count"] = 99
        resp = api.create_circuit(payload, ADMIN)
        data = validate_success(resp, 201)
        assert data["status"] == "IN_SERVICE", (
            "client-supplied status must never be honored (PRD §3.1: the "
            "circuit's status is never set directly)"
        )
        assert data["unresolved_fault_count"] == 0


class TestReads:
    def test_read_after_create_is_immediately_visible(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field." The very next read of a created circuit returns every
        stored field.

        Design: Corner/consistency_model/immediate_read_after_write
        """
        created = create_circuit("CKT-Z1", "KV_25", 1750, 2003)
        resp = api.get_circuit(created["id"], ENGINEER)
        data = validate_success(resp, 200)
        assert data["circuit_ref"] == "CKT-Z1"
        assert data["length_m"] == 1750
        assert data["voltage_class"] == "KV_25"
        assert data["status"] == "IN_SERVICE"

    def test_unknown_circuit_returns_not_found_envelope(self, api):
        """PRD §2.7: "4. **Existence** — path identifiers are resolved first,
        validated left to right along the URL, and then body foreign-key
        references in their declared input order; the first missing reference
        yields `ERR_NOT_FOUND` (HTTP 404)."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/endpoints/not_found_error_envelope_shape
        """
        resp = api.get_circuit(NON_EXISTENT_UUID, ADMIN)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert err["message"].strip(), "error message must be non-empty"
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)

    def test_list_pagination_limit_offset_and_class_filter(self, api):
        """PRD §2.3: "List responses carry the pagination fields `limit`,
        `offset`, `total_count`, and `has_more` inside the `meta` object."
        PRD §4: "List circuits; filters `status`, `voltage_class`,
        `replacement_recommended`, plus `limit`, `offset`".

        Design: Corner/endpoints/pagination_limit_offset_filter
        """
        create_circuit("CKT-P1", "KV_15", 1000, 2015)
        create_circuit("CKT-P2", "KV_15", 1100, 2016)
        create_circuit("CKT-P3", "KV_25", 1200, 2017)

        page1, meta1 = validate_paginated(api.list_circuits(PLANNER, params={"limit": 2}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_circuits(PLANNER, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        filtered, meta3 = validate_paginated(
            api.list_circuits(PLANNER, params={"voltage_class": "KV_25"})
        )
        assert meta3["total_count"] == 1
        assert filtered[0]["circuit_ref"] == "CKT-P3"

    def test_reverse_fk_subresources_reachable(self, api):
        """PRD §4: "| GET | /cable-diagnostics/circuits/{id}/test-jobs | Jobs of a circuit | All roles |",
        "| GET | /cable-diagnostics/outage-windows/{id}/test-jobs | Jobs referencing a window | All roles |",
        "| GET | /cable-diagnostics/circuits/{id}/outage-windows | Windows of a circuit | All roles |",
        "| GET | /cable-diagnostics/circuits/{id}/health-assessments | Assessments of a circuit, all statuses including `SUPERSEDED` | All roles |".

        Design: Corner/endpoints/fk_reverse_reachability_subresources
        """
        circuit = create_circuit("CKT-P4", "KV_15", 1000, 2015)
        window = create_window(circuit["id"])
        approve_window(window["id"])
        job = create_job(circuit["id"], window["id"], approved_budget_cents=800000)

        jobs_of_circuit = validate_success(
            api.list_circuit_test_jobs(circuit["id"], PLANNER), 200
        )
        assert [j["id"] for j in jobs_of_circuit] == [job["id"]]

        jobs_of_window = validate_success(
            api.list_window_test_jobs(window["id"], PLANNER), 200
        )
        assert [j["id"] for j in jobs_of_window] == [job["id"]]

        windows_of_circuit = validate_success(
            api.list_circuit_outage_windows(circuit["id"], PLANNER), 200
        )
        assert [w["id"] for w in windows_of_circuit] == [window["id"]]

        assessments = validate_success(
            api.list_circuit_health_assessments(circuit["id"], PLANNER), 200
        )
        assert assessments == [], "a circuit with no assessments returns an empty array"

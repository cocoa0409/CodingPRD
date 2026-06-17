"""Entity-level CRUD corners: job creation defaults, required-field and enum
validation, not-found / FK-not-found, estimator immutability, list pagination
envelope, computed line cost, and immediate visibility of contract value.

Queue B (entities section, consistency_model section).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    create_estimator_payload, create_job_payload,
    create_estimate_payload, create_line_item_payload,
    setup_estimated_job,
)

FA = TEST_USERS["field_adjuster_headers"]
EST = TEST_USERS["estimator_headers"]


def _estimator_id(api):
    return get_success_data(api.create_estimator(create_estimator_payload(), EST))["id"]


class TestJobCreation:
    def test_create_job_returns_201_with_defaults(self, api):
        """PRD §3.1: "A freshly created Job lands in `LEAD` status with a
        `version` of 1, its bound-estimate reference empty, and its ledger fields
        zeroed."
        PRD §2.6: "an input supplied at job creation that defaults to 0.10 and
        must lie between 0 and 0.20 inclusive."

        Design: Corner/entities/create_job_returns_201_with_defaults
        """
        est_id = _estimator_id(api)
        data = validate_success(api.create_job(
            create_job_payload(assigned_estimator_id=est_id), FA), expected_status=201)
        assert data["status"] == "LEAD"
        assert data["retainage_pct"] == 0.10
        assert data["version"] == 1
        assert data["contract_value_cents"] == 0

    def test_create_job_missing_required_field(self, api):
        """PRD §2.9: "(5) presence and typing of required body fields, else
        `ERR_MISSING_FIELD`."

        Design: Corner/entities/create_job_missing_required_field
        """
        est_id = _estimator_id(api)
        payload = create_job_payload(assigned_estimator_id=est_id)
        del payload["property_address"]
        validate_error(api.create_job(payload, FA), ApiErrorId.ERR_MISSING_FIELD.value)

    def test_create_job_bad_enum_peril(self, api):
        """PRD §3.1: "The `peril` is one of `HAIL`, `WIND`, `HURRICANE`, or
        `OTHER`."
        PRD §2.9: "(6) enum, numeric-range, and interval validity, else
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_job_bad_enum_peril
        """
        est_id = _estimator_id(api)
        validate_error(api.create_job(
            create_job_payload(assigned_estimator_id=est_id, peril="EARTHQUAKE"), FA),
            ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_job_fk_estimator_not_found(self, api):
        """PRD §2.8: "for create operations and for the contract operation, it
        confirms that every foreign key in the body resolves — `job_id`,
        `crew_id`, `estimate_id`, `permit_id`, `assigned_estimator_id`, and the
        `estimate_id` named when contracting — rejecting with `ERR_FK_NOT_FOUND`
        (HTTP 404) when any referenced record is missing."

        Design: Corner/entities/create_job_fk_estimator_not_found
        """
        validate_error(api.create_job(
            create_job_payload(assigned_estimator_id=NON_EXISTENT_UUID), FA),
            ApiErrorId.ERR_FK_NOT_FOUND.value)


class TestNotFoundAndImmutability:
    def test_get_job_not_found(self, api):
        """PRD §2.8: "First it confirms that any resource named by a path
        identifier exists, rejecting with `ERR_NOT_FOUND` (HTTP 404) if it does
        not."

        Design: Corner/entities/get_job_not_found
        """
        validate_error(api.get_job(NON_EXISTENT_UUID, FA), ApiErrorId.ERR_NOT_FOUND.value)

    def test_estimator_is_immutable_reference_data(self, api):
        """PRD §2.4: "The **Estimator** entity is the exception: it is immutable
        reference data, so an Estimator record carries only `id` and
        `created_at`. It has no `updated_at` and no `version` field at all; those
        fields are simply absent from an Estimator resource."

        Design: Corner/entities/estimator_immutable_no_version
        """
        est = get_success_data(api.create_estimator(
            create_estimator_payload(license_no="TX-1001"), EST))
        data = validate_success(api.get_estimator(est["id"], EST))
        assert data["license_no"] == "TX-1001"
        assert "version" not in data
        assert "updated_at" not in data


class TestListingAndComputedFields:
    def test_list_jobs_pagination_envelope(self, api):
        """PRD §2.3: "List responses include `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the envelope, where `total_count`
        is the count of all matching resources before paging and `has_more`
        indicates whether further items remain past the current page."

        Design: Corner/entities/list_jobs_pagination_envelope
        """
        est_id = _estimator_id(api)
        api.create_job(create_job_payload(assigned_estimator_id=est_id, customer_name="J1"), FA)
        api.create_job(create_job_payload(assigned_estimator_id=est_id, customer_name="J2"), FA)
        data, meta = validate_paginated(api.list_jobs(FA))
        assert meta["total_count"] >= 2
        assert "has_more" in meta

    def test_line_cost_is_computed_server_side(self, api):
        """PRD §3.2: "take the `squares`, multiply by one plus the
        `waste_factor_pct`, multiply by the `unit_price_cents`, and round that
        product half-up to a whole cent."

        Design: Corner/entities/computed_line_cost_ignores_client_input
        """
        est_id = _estimator_id(api)
        job = get_success_data(api.create_job(
            create_job_payload(assigned_estimator_id=est_id), FA))
        est = get_success_data(api.create_estimate(
            create_estimate_payload(job_id=job["id"], source_kind="FIELD"), EST))
        data = validate_success(api.add_line_item(est["id"], create_line_item_payload(
            trade="SHINGLE", squares=10, unit_price_cents=10000, waste_factor_pct=0.10), EST),
            expected_status=201)
        # 10 * 1.10 * 10000 = 110000.
        assert data["line_cost_cents"] == 110000


class TestImmediateConsistency:
    def test_contract_value_visible_in_contract_response(self, api):
        """PRD §3.3: "The job's `contract_value_cents` is set to the bound
        estimate's `final_total_cents`, and `remaining_billable_cents` is set
        equal to that contract value (nothing has been disbursed yet)."
        PRD §3.3: "The job records the chosen estimate as its bound estimate
        (captured in `bound_estimate_id`)."

        Design: Corner/consistency_model/contract_value_visible_in_same_response
        """
        job_id, est = setup_estimated_job()  # single SHINGLE 10sq@10000 -> 110000
        data = validate_success(api.contract_job(job_id, {"estimate_id": est["id"]}, EST))
        assert data["contract_value_cents"] == 110000
        assert data["bound_estimate_id"] == est["id"]

"""Deployment discovery: request shape, confirm/reject lifecycle, temporal gate,
immediate consistency, and role separation (PRD §2.1, §3.3)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_deployment,
    create_deployment,
    create_deployment_payload,
    create_vendor_and_product,
    get_license_position,
    validate_error,
    validate_success,
)


class TestDeploymentShape:
    def test_deployment_create_invalid_environment_enum(self, api, it_analyst_headers):
        """PRD §3.3: "An `ITAnalyst` records each measurement against a `product_id`
        with the `measured_quantity` observed under the product's license metric —
        installations, named users, or cores, always a positive integer — the
        `environment` observed (`PRODUCTION` or `NON_PRODUCTION`), the
        `measurement_method` (`SCAN` or `MANUAL_DECLARATION`), and the `measured_on`
        timestamp of the observation."
        PRD §2.10: "Request shape — required fields are present, types match, enum
        values are valid, `quantity` and `amount_cents` are positive,
        `effective_from` is earlier than `effective_to` when both are present,
        required arrays such as `covered_scope_item_ids` and
        `target_deployment_ids` are non-empty where required, an entitlement
        `source` on manual creation is limited to `MANUAL_IMPORT` or
        `CONTRACT_EXTRACT`, and `future_license_discount_pct` lies within its
        allowed range; violations yield `ERR_INVALID_REQUEST`."

        Design: Corner/entities/deployment_create_invalid_environment_enum
        """
        _vendor, product = create_vendor_and_product()
        resp = api.create_deployment(
            create_deployment_payload(product["id"], measured_quantity=5,
                                      environment="STAGING"),
            it_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestDeploymentLifecycle:
    def test_deployment_confirm_twice_rejected(self, api, sam_manager_headers):
        """PRD §3.3: "Confirmation is allowed only from `REPORTED` — a record in any
        other state fails with `ERR_DEPLOYMENT_INVALID_STATE` — and only when
        `measured_on` is not later than the current logical clock, otherwise the
        request is rejected with `ERR_MEASUREMENT_DATE_IN_FUTURE`."
        PRD §3.4: "Its `deployed_quantity` is the sum of `measured_quantity` over
        the product's deployment records in `CONFIRMED` status whose `environment`
        is `PRODUCTION`, plus the `CONFIRMED` records whose `environment` is
        `NON_PRODUCTION` only when the product's `counts_non_production` flag is
        true; `REPORTED`, `REJECTED`, and `EXCLUDED` records never contribute."

        Design: Corner/state_machines/deployment_confirm_twice_rejected
        """
        _vendor, product = create_vendor_and_product()
        dep = create_deployment(product["id"], measured_quantity=10)

        confirmed = validate_success(
            api.confirm_deployment(dep["id"], sam_manager_headers), 200)
        assert confirmed["status"] == "CONFIRMED"

        resp = api.confirm_deployment(dep["id"], sam_manager_headers)
        validate_error(resp, ApiErrorId.ERR_DEPLOYMENT_INVALID_STATE)

        position = get_license_position(product["id"])
        assert position["deployed_quantity"] == 10, \
            "the rejected second confirm must not double-count the measurement"

    def test_deployment_reject_is_terminal(self, api, sam_manager_headers):
        """PRD §3.3: "Rejection moves the record to `REJECTED`, a terminal state
        with no position effects; an optional `rejection_reason` may be supplied."
        PRD §3.3: "Confirmation is allowed only from `REPORTED` — a record in any
        other state fails with `ERR_DEPLOYMENT_INVALID_STATE` — and only when
        `measured_on` is not later than the current logical clock, otherwise the
        request is rejected with `ERR_MEASUREMENT_DATE_IN_FUTURE`."

        Design: Corner/state_machines/deployment_reject_is_terminal
        """
        _vendor, product = create_vendor_and_product()
        dep = create_deployment(product["id"], measured_quantity=10)

        rejected = validate_success(
            api.reject_deployment(dep["id"], {"rejection_reason": "duplicate scan row"},
                                  sam_manager_headers), 200)
        assert rejected["status"] == "REJECTED"

        resp = api.confirm_deployment(dep["id"], sam_manager_headers)
        validate_error(resp, ApiErrorId.ERR_DEPLOYMENT_INVALID_STATE)

    def test_deployment_not_found_on_confirm(self, api, sam_manager_headers):
        """PRD §3.3: "A product's measurements can be listed with an optional
        `status` filter, and unknown deployment identifiers surface as
        `ERR_DEPLOYMENT_NOT_FOUND`."

        Design: Corner/errors/deployment_not_found_on_confirm
        """
        resp = api.confirm_deployment(NON_EXISTENT_UUID, sam_manager_headers)
        validate_error(resp, ApiErrorId.ERR_DEPLOYMENT_NOT_FOUND)


class TestMeasurementTemporalGate:
    def test_deployment_confirm_future_measurement_rejected(self, api,
                                                            sam_manager_headers):
        """PRD §3.3: "Confirmation is allowed only from `REPORTED` — a record in any
        other state fails with `ERR_DEPLOYMENT_INVALID_STATE` — and only when
        `measured_on` is not later than the current logical clock, otherwise the
        request is rejected with `ERR_MEASUREMENT_DATE_IN_FUTURE`."

        Design: Corner/validations/deployment_confirm_future_measurement_rejected
        """
        _vendor, product = create_vendor_and_product()
        dep = create_deployment(product["id"], measured_quantity=5,
                                measured_on="2026-09-01T00:00:00Z")
        assert dep["status"] == "REPORTED"

        resp = api.confirm_deployment(dep["id"], sam_manager_headers)
        validate_error(resp, ApiErrorId.ERR_MEASUREMENT_DATE_IN_FUTURE)

        rows = validate_success(
            api.list_deployments(product["id"], sam_manager_headers), 200)
        still = next(r for r in rows if r["id"] == dep["id"])
        assert still["status"] == "REPORTED", \
            "a measurement dated after the 2026-08-01 clock cannot be confirmed"


class TestImmediateConsistency:
    def test_mutations_visible_immediately_in_same_response(
            self, api, sam_manager_headers):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.3: "Confirming moves the record to `CONFIRMED` and recomputes the
        product's deployed quantity, gap, severity, and exposures, together with the
        rollups of every non-terminal audit case scoping the product and the
        product's monitoring alerts."

        Design: Corner/consistency_model/mutations_visible_immediately_in_same_response
        """
        _vendor, product = create_vendor_and_product()
        dep = create_deployment(product["id"], measured_quantity=7)

        confirmed = validate_success(
            api.confirm_deployment(dep["id"], sam_manager_headers), 200)
        assert_deployment(confirmed)
        assert confirmed["status"] == "CONFIRMED", \
            "the confirm response itself carries the new status"

        position = get_license_position(product["id"])
        assert position["deployed_quantity"] == 7, \
            "the very next read already reflects the confirmed measurement"


class TestDeploymentRBAC:
    def test_legal_counsel_cannot_record_deployment(self, api, legal_counsel_headers):
        """PRD §2.1: "A request whose role is not permitted for the endpoint it
        targets is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §3.3: "An `ITAnalyst` records each measurement against a `product_id`
        with the `measured_quantity` observed under the product's license metric"

        Design: Corner/rbac/legal_counsel_cannot_record_deployment
        """
        _vendor, product = create_vendor_and_product()
        resp = api.create_deployment(
            create_deployment_payload(product["id"], measured_quantity=5),
            legal_counsel_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_it_analyst_cannot_confirm_deployment(self, api, it_analyst_headers,
                                                  sam_manager_headers):
        """PRD §2.1: "A request whose role is not permitted for the endpoint it
        targets is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §3.3: "A `SAMManager` reviews each reported measurement and either
        confirms or rejects it."

        Design: Corner/rbac/it_analyst_cannot_confirm_deployment
        """
        _vendor, product = create_vendor_and_product()
        dep = create_deployment(product["id"], measured_quantity=5)

        resp = api.confirm_deployment(dep["id"], it_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        rows = validate_success(
            api.list_deployments(product["id"], sam_manager_headers), 200)
        still = next(r for r in rows if r["id"] == dep["id"])
        assert still["status"] == "REPORTED", \
            "the denied confirm leaves the measurement untouched"

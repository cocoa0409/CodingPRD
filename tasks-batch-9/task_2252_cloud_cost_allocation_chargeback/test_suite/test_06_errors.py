"""Error identity, admission order and the ledger's exact-clearing rule."""

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    CONTROLLER_HEADERS,
    NO_AUTH_HEADERS,
    UNKNOWN_ID,
    ApiErrorId,
    assert_cents,
    assert_invoice_dimensions,
    assert_invoice_ledger,
    fixtures,
    make_business_unit_owner_headers,
    validate_error,
    validate_success,
)


def test_a_headerless_request_is_refused_before_the_identifier_is_resolved(api):
    """The missing-identity refusal pre-empts the not-found refusal.

    PRD §2.1: "If either header is absent or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/unauthenticated_request_returns_401_before_the_existence_check
    """
    unit = fixtures.create_business_unit(api)

    anonymous_real = api.get_business_unit(unit["id"], NO_AUTH_HEADERS)
    validate_error(anonymous_real, ApiErrorId.UNAUTHENTICATED.value, 401)

    anonymous_unknown = api.get_business_unit(UNKNOWN_ID, NO_AUTH_HEADERS)
    validate_error(anonymous_unknown, ApiErrorId.UNAUTHENTICATED.value, 401)

    identified_unknown = api.get_business_unit(UNKNOWN_ID, ANALYST_HEADERS)
    validate_error(identified_unknown, ApiErrorId.BUSINESS_UNIT_NOT_FOUND.value, 404)


def test_each_unresolvable_path_id_names_its_own_entity_in_the_404(api):
    """Six families are missed in one pass and none of them share a generic code.

    PRD §2.10: "Each entity has its own 404: `ERR_BUSINESS_UNIT_NOT_FOUND`,
    `ERR_TAGGING_POLICY_NOT_FOUND`, `ERR_PROVISIONING_REQUEST_NOT_FOUND`,
    `ERR_CLOUD_RESOURCE_NOT_FOUND`, `ERR_COST_RECORD_NOT_FOUND`,
    `ERR_SHARED_COST_POOL_NOT_FOUND`, `ERR_ALLOCATION_RUN_NOT_FOUND`,
    `ERR_ALLOCATION_LINE_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`,
    `ERR_DISPUTE_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_REMEDIATION_TASK_NOT_FOUND`, `ERR_ANOMALY_ALERT_NOT_FOUND`,
    `ERR_BUDGET_NOT_FOUND` and `ERR_DRIVER_NOT_FOUND`."

    Design: Corner/errors/every_unknown_path_id_returns_its_own_entity_specific_not_found_id
    """
    probes = (
        (api.get_cloud_resource(UNKNOWN_ID, ANALYST_HEADERS), ApiErrorId.CLOUD_RESOURCE_NOT_FOUND),
        (api.get_allocation_run(UNKNOWN_ID, ANALYST_HEADERS), ApiErrorId.ALLOCATION_RUN_NOT_FOUND),
        (api.get_dispute(UNKNOWN_ID, ANALYST_HEADERS), ApiErrorId.DISPUTE_NOT_FOUND),
        (
            api.get_remediation_task(UNKNOWN_ID, ANALYST_HEADERS),
            ApiErrorId.REMEDIATION_TASK_NOT_FOUND,
        ),
        (api.get_commitment(UNKNOWN_ID, ANALYST_HEADERS), ApiErrorId.COMMITMENT_NOT_FOUND),
        (api.get_anomaly_alert(UNKNOWN_ID, ANALYST_HEADERS), ApiErrorId.ANOMALY_ALERT_NOT_FOUND),
    )

    for response, error_id in probes:
        validate_error(response, error_id.value, 404)


def test_a_payment_must_clear_the_invoice_exactly_and_then_locks_the_run(api):
    """Short and over are the same refusal, and the cleared invoice removes the reopen.

    PRD §3.6: "The owner submits `payment_cents`, and the payment must
    **exactly clear** the invoice: `paid_amount_cents` plus the submitted
    `payment_cents` must equal `gross_amount_cents` less
    `credited_amount_cents`. Anything else — short or over — is rejected with
    `ERR_OVERPAYMENT` at HTTP 422."

    Design: Corner/errors/settlement_must_exactly_clear_the_invoice_and_a_settled_invoice_blocks_reopen
    """
    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    unit = fixtures.create_chargeback_unit(api)
    built = fixtures.issued_chargeback_invoice(api, unit["id"], 5000)
    invoice_id = built["invoice"]["id"]
    owner = make_business_unit_owner_headers(unit["id"])

    short_payment = api.settle_invoice(invoice_id, 4999, owner)
    validate_error(short_payment, ApiErrorId.OVERPAYMENT.value, 422)

    unpaid = validate_success(api.get_chargeback_invoice(invoice_id, CONTROLLER_HEADERS))
    assert_cents(unpaid["paid_amount_cents"], 0, "paid_amount_cents")

    long_payment = api.settle_invoice(invoice_id, 5001, owner)
    validate_error(long_payment, ApiErrorId.OVERPAYMENT.value, 422)

    settled = validate_success(api.settle_invoice(invoice_id, 5000, owner))
    assert_invoice_dimensions(settled, settlement_status="SETTLED", dispute_status="NONE")
    assert_invoice_ledger(settled, 5000, 0, 5000, 0)

    reopen = api.reopen_allocation_run(built["run"]["id"], "late credit memo", CONTROLLER_HEADERS)
    validate_error(reopen, ApiErrorId.RUN_REOPEN_BLOCKED.value, 409)

    run = validate_success(api.get_allocation_run(built["run"]["id"], CONTROLLER_HEADERS))
    assert run["status"] == "PUBLISHED"
    assert run["reopen_count"] == 0

    final_unit = validate_success(api.get_business_unit(unit["id"], ADMIN_HEADERS))
    assert_cents(final_unit["chargeback_balance_cents"], 0, "chargeback_balance_cents")

"""Error corners: one envelope across five status codes, exact settlement, and the
blocking set that lets a DRAFT invoice be re-priced.

The envelope instance labels the inverted date range a 422, but §5's error table maps
`ERR_INVALID_DATE_RANGE` to 400, so that leg is asserted at 400 — still a fifth distinct
status code alongside 401, 403, 404 and 409.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import Instant, assert_error_envelope, assert_facility_money
from test_helpers.test_users import (
    ANALYST_1,
    BILLING_1,
    EMPTY_USER_ID_HEADERS,
    INTAKE_1,
    PLATFORM_ADMIN,
)


# --------------------------------------------------------------------------
# error_envelope_is_uniform_across_status_codes_rejected
# --------------------------------------------------------------------------
def _five_rejected_calls(api):
    """One facility and one patient, then five calls that fail at five different priorities."""
    world = fx.third_party_world(api)
    fx.make_patient(api, world["facility_id"], mrn="MRN-9001", full_name="Kit Alvarez")
    return world, [
        (
            api.create_facility(
                f.facility_payload(world["fee_rule_id"]), EMPTY_USER_ID_HEADERS
            ),
            e.ERR_UNAUTHENTICATED,
            401,
        ),
        (
            api.create_state_fee_rule(f.state_fee_rule_payload(state_code="NY"), ANALYST_1),
            e.ERR_UNAUTHORIZED_ROLE,
            403,
        ),
        (
            api.get_facility(NON_EXISTENT_UUID, PLATFORM_ADMIN),
            e.ERR_FACILITY_NOT_FOUND,
            404,
        ),
        (
            api.create_request(
                f.third_party_request_payload(
                    world["facility_id"],
                    world["patient_id"],
                    world["requester_id"],
                    world["authorization_id"],
                    date_range_start="2025-12-31",
                    date_range_end="2024-01-01",
                ),
                INTAKE_1,
            ),
            e.ERR_INVALID_DATE_RANGE,
            400,
        ),
        (
            api.create_patient(
                f.patient_payload(world["facility_id"], mrn="MRN-9001"),
                world["facility_admin_headers"],
            ),
            e.ERR_DUPLICATE_MRN,
            409,
        ),
    ]


def test_five_status_codes_from_five_priorities_share_one_error_envelope(api):
    """401, 403, 404, 400 and 409 differ only in status and error_id.

    PRD: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/error_envelope_is_uniform_across_status_codes_rejected
    """
    _, attempts = _five_rejected_calls(api)
    assert len({status for _, _, status in attempts}) == 5

    for response, error_id, status in attempts:
        data = assert_error_envelope(response, error_id, status)
        assert set(data) == {"error_id", "message"}
        assert set(response.json()["meta"]) == {"api_request_id", "api_request_timestamp"}
        assert response.json()["response_type"] == "error"
        for leaked in ("id", "version", "created_at", "updated_at", "status"):
            assert leaked not in data


def test_none_of_the_five_rejected_calls_persisted_anything(api):
    """A refusal at any priority is a complete no-op on the collections it addressed.

    PRD: "Validation is a single ordered pipeline, and the **first** violated rule determines the response; later violations are not reported."

    Design: Corner/errors/error_envelope_is_uniform_across_status_codes_rejected
    """
    world, attempts = _five_rejected_calls(api)
    for response, error_id, status in attempts:
        assert_error_envelope(response, error_id, status)

    _, rules = validate_paginated(api.list_state_fee_rules(PLATFORM_ADMIN, {"limit": 10}))
    assert rules["total_count"] == 1
    _, patients = validate_paginated(
        api.list_patients(PLATFORM_ADMIN, {"facility_id": world["facility_id"], "limit": 10})
    )
    assert patients["total_count"] == 2
    _, requests = validate_paginated(
        api.list_requests(INTAKE_1, {"facility_id": world["facility_id"], "limit": 10})
    )
    assert requests["total_count"] == 0
    _, facilities = validate_paginated(api.list_facilities(PLATFORM_ADMIN, {"limit": 10}))
    assert facilities["total_count"] == 1


# --------------------------------------------------------------------------
# payment_must_settle_the_exact_amount_due_rejected
# --------------------------------------------------------------------------
def _issued_invoice_for_2188(api):
    """25 billable pages priced at 1500 + 688 and issued, so 2188 is receivable."""
    world = fx.third_party_world(api)
    scenario = fx.simple_third_party_request_at_release_ready(api, world, 25)
    invoice = fx.create_invoice(api, scenario["request_id"])
    issued = fx.issue_invoice(api, invoice["id"])
    return world, scenario["request_id"], issued


def test_a_payment_one_cent_either_side_of_the_amount_due_is_refused(api):
    """Overpayment is refused as firmly as underpayment, and so is an omitted amount.

    PRD: "`PAY` is permitted only from `ISSUED` and demands exact settlement: `amount_cents` absent, or present but unequal to `amount_due_cents`, is refused with `ERR_PAYMENT_AMOUNT_MISMATCH`, because partial payment is what would otherwise break the facility ledger's clean three-way partition."

    Design: Corner/errors/payment_must_settle_the_exact_amount_due_rejected
    """
    world, request_id, invoice = _issued_invoice_for_2188(api)
    assert invoice["subtotal_cents"] == 2188
    assert invoice["amount_due_cents"] == 2188
    assert invoice["status"] == "ISSUED"
    assert_facility_money(
        fx.read_facility(api, world["facility_id"]), receivable=2188, collected=0, written_off=0
    )

    for body in (f.pay_payload(2187), f.pay_payload(2189), {"action": "PAY"}):
        validate_error(
            api.settle_invoice(invoice["id"], body, BILLING_1),
            e.ERR_PAYMENT_AMOUNT_MISMATCH,
            422,
        )

    unsettled = fx.read_invoice(api, invoice["id"])
    assert unsettled["status"] == "ISSUED"
    assert unsettled["paid_cents"] == 0
    assert fx.read_request(api, request_id)["billing_status"] == "INVOICED"
    assert_facility_money(
        fx.read_facility(api, world["facility_id"]), receivable=2188, collected=0, written_off=0
    )


def test_the_exact_amount_moves_the_whole_sum_from_receivable_to_collected(api):
    """The ledger stays a three-way partition because only exact settlement is allowed.

    PRD: "A successful payment records `paid_cents` as the settled `amount_cents` and `settled_at` as the current logical clock, moves the invoice to `PAID` and the request's `billing_status` to `PAID`, subtracts `amount_due_cents` from the facility's `receivable_cents` and adds it to `collected_cents`."

    Design: Corner/errors/payment_must_settle_the_exact_amount_due_rejected
    """
    world, request_id, invoice = _issued_invoice_for_2188(api)
    validate_error(
        api.settle_invoice(invoice["id"], f.pay_payload(2187), BILLING_1),
        e.ERR_PAYMENT_AMOUNT_MISMATCH,
        422,
    )

    paid = validate_success(
        api.settle_invoice(invoice["id"], f.pay_payload(2188), BILLING_1), 200
    )

    assert paid["status"] == "PAID"
    assert paid["paid_cents"] == 2188
    assert paid["settled_at"] == Instant("2026-08-01T00:00:00Z")
    assert fx.read_request(api, request_id)["billing_status"] == "PAID"
    facility = fx.read_facility(api, world["facility_id"])
    assert_facility_money(facility, receivable=0, collected=2188, written_off=0)
    assert (
        facility["receivable_cents"] + facility["collected_cents"] + facility["written_off_cents"]
    ) == 2188


# --------------------------------------------------------------------------
# draft_invoice_is_superseded_but_settled_invoice_blocks_rejected
# --------------------------------------------------------------------------
def _release_ready_request_with_a_draft_invoice(api):
    """A 25-page request priced once, with the first invoice still sitting in DRAFT."""
    world = fx.third_party_world(api)
    scenario = fx.simple_third_party_request_at_release_ready(api, world, 25)
    first = fx.create_invoice(api, scenario["request_id"])
    return world, scenario["request_id"], first


def test_a_draft_invoice_is_superseded_by_the_re_price_that_follows_it(api):
    """DRAFT is outside the blocking set, so the second pricing call is a legitimate re-price.

    PRD: "A `DRAFT` invoice, by contrast, does **not** block: the new invoice is a legitimate re-price, and the existing `DRAFT` is driven to `VOIDED` with `void_reason` set to `SUPERSEDED_BY_REPRICE`."

    Design: Corner/errors/draft_invoice_is_superseded_but_settled_invoice_blocks_rejected
    """
    world, request_id, first = _release_ready_request_with_a_draft_invoice(api)
    assert first["status"] == "DRAFT"
    assert_facility_money(
        fx.read_facility(api, world["facility_id"]), receivable=0, collected=0, written_off=0
    )

    second = validate_success(
        api.create_invoice(
            f.invoice_payload(request_id, fx.request_version(api, request_id)), BILLING_1
        ),
        201,
    )

    assert second["id"] != first["id"]
    superseded = fx.read_invoice(api, first["id"])
    assert superseded["status"] == "VOIDED"
    assert superseded["void_reason"] == "SUPERSEDED_BY_REPRICE"
    assert second["amount_due_cents"] == first["amount_due_cents"] == 2188
    assert_facility_money(
        fx.read_facility(api, world["facility_id"]), receivable=0, collected=0, written_off=0
    )


def test_an_issued_and_then_a_paid_invoice_both_block_a_further_pricing_call(api):
    """Once the invoice leaves DRAFT a fresh version guard no longer buys a re-price.

    PRD: "An invoice may not be created while another invoice for the same `request_id` holds `status` `ISSUED`, `PAID` or `WAIVED`; that is `ERR_INVOICE_ALREADY_EXISTS`."

    Design: Corner/errors/draft_invoice_is_superseded_but_settled_invoice_blocks_rejected
    """
    world, request_id, first = _release_ready_request_with_a_draft_invoice(api)
    second = validate_success(
        api.create_invoice(
            f.invoice_payload(request_id, fx.request_version(api, request_id)), BILLING_1
        ),
        201,
    )
    fx.issue_invoice(api, second["id"])
    assert fx.read_request(api, request_id)["billing_status"] == "INVOICED"
    assert_facility_money(
        fx.read_facility(api, world["facility_id"]), receivable=2188, collected=0, written_off=0
    )

    validate_error(
        api.create_invoice(
            f.invoice_payload(request_id, fx.request_version(api, request_id)), BILLING_1
        ),
        e.ERR_INVOICE_ALREADY_EXISTS,
        409,
    )

    fx.pay_invoice(api, second["id"], 2188)
    validate_error(
        api.create_invoice(
            f.invoice_payload(request_id, fx.request_version(api, request_id)), BILLING_1
        ),
        e.ERR_INVOICE_ALREADY_EXISTS,
        409,
    )

    rows, meta = fx.list_invoices_for(api, request_id)
    assert meta["total_count"] == 2
    assert sorted(row["status"] for row in rows) == ["PAID", "VOIDED"]
    assert first["id"] in [row["id"] for row in rows]
    assert_facility_money(
        fx.read_facility(api, world["facility_id"]), receivable=0, collected=2188, written_off=0
    )

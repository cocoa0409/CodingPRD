"""Error catalogue: authentication, authorization, ownership and out-of-order triggers."""
from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    calculate_run,
    claim_denial_payload,
    commission_receipt_payload,
    compliance,
    confirm_booking,
    controller,
    create_booking_payload,
    create_client_payload,
    create_supplier_payload,
    file_claim,
    list_client_ledger,
    make_advisor_headers,
    make_supplier_portal_headers,
    mark_traveled,
    new_booking,
    new_client,
    new_split_schedule,
    new_supplier,
    open_run,
    ops,
    pay_statement_payload,
    read_booking,
    read_claim,
    read_client,
    read_run,
    read_statement,
    record_receipt,
    setup_active_advisor,
    statements_for_advisor,
    trust_ledger_entry_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

STANDARD_TIERS = [
    {"tier_level": 1, "min_production_cents": 0, "advisor_pct": 0.70},
    {"tier_level": 2, "min_production_cents": 5_000_000, "advisor_pct": 0.80},
]
FLAT_FEE_TIERS = [{"min_share_cents": 0, "fee_pct": 0.05}]

MERIDIAN = {
    "name": "Meridian Air",
    "accreditation_scheme": "ARC",
    "base_commission_pct": 0.10,
    "preferred_override_commission_pct": 0.12,
    "rate_ceiling_pct": 0.20,
    "max_commission_per_booking_cents": 9_000_000,
    "remit_terms_days": 30,
}


def _standard_schedule():
    return new_split_schedule(
        name="Standard 2026",
        tiers=STANDARD_TIERS,
        platform_fee_tiers=FLAT_FEE_TIERS,
        chargeback_retention_pct=0.10,
    )


def test_the_four_authorization_failures_are_reported_apart():
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the five
    recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If
    the headers are well formed but the declared role is not among the roles authorized for
    the target endpoint in the Section 4 table, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "A violated ownership check yields `ERR_OWNERSHIP_VIOLATION` (HTTP 403). This
    is distinct from `ERR_UNAUTHORIZED`: the role was permitted to call the endpoint, but not
    against that particular row."

    Design: Corner/errors/corner_auth_role_and_ownership_rejections
    """
    supplier = new_supplier(**MERIDIAN)
    schedule = _standard_schedule()
    first = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        schedule=schedule,
        suppliers=[supplier],
        number_prefix="A",
    )["advisor"]
    second = setup_active_advisor(
        state="NY",
        legal_name="Sam Ortiz",
        email="sam.ortiz@example.com",
        schedule=schedule,
        suppliers=[supplier],
        number_prefix="B",
    )["advisor"]

    owned_client = new_client(
        first["id"], full_name="Nadia Okoye", home_state_code="NY"
    )
    opening_version = read_client(owned_client["id"])["version"]
    deposit = validate_success(
        api_client.create_trust_ledger_entry(
            owned_client["id"],
            trust_ledger_entry_payload(
                "DEPOSIT", 100_000, opening_version, memo="Advance for future trip"
            ),
            make_advisor_headers(first["id"]),
        ),
        201,
    )
    assert deposit["balance_after_cents"] == 100_000
    funded_version = read_client(owned_client["id"])["version"]

    validate_error(
        api_client.create_client(
            create_client_payload(first["id"], full_name="Headerless Client"),
            {"X-User-ID": first["id"]},
        ),
        "ERR_UNAUTHENTICATED",
        401,
    )
    validate_error(
        api_client.create_client(
            create_client_payload(first["id"], full_name="Auditor Client"),
            {"X-User-ID": "aud-1", "X-User-Role": "Auditor"},
        ),
        "ERR_UNAUTHENTICATED",
        401,
    )
    _, client_meta = validate_paginated(api_client.list_clients(ops()))
    assert client_meta["total_count"] == 1

    validate_error(
        api_client.create_supplier(
            create_supplier_payload(
                name="Rogue Supplier",
                accreditation_scheme="ARC",
                base_commission_pct=0.30,
                preferred_override_commission_pct=0.35,
                rate_ceiling_pct=0.40,
                max_commission_per_booking_cents=9_000_000,
                remit_terms_days=30,
            ),
            make_advisor_headers(first["id"]),
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    _, supplier_meta = validate_paginated(api_client.list_suppliers(ops()))
    assert supplier_meta["total_count"] == 1

    validate_error(
        api_client.create_booking(
            create_booking_payload(
                first["id"],
                supplier["id"],
                owned_client["id"],
                channel="SUPPLIER_DIRECT",
                payment_method="MERCHANT_DIRECT",
                gross_sale_cents=1_000_000,
                travel_start_date="2026-10-01",
                travel_end_date="2026-10-10",
            ),
            make_advisor_headers(second["id"]),
        ),
        "ERR_OWNERSHIP_VIOLATION",
        403,
    )

    validate_error(
        api_client.create_trust_ledger_entry(
            owned_client["id"],
            trust_ledger_entry_payload(
                "REFUND", 100_000, funded_version, memo="Advisor-initiated refund"
            ),
            make_advisor_headers(first["id"]),
        ),
        "ERR_TRUST_DIRECTION_FORBIDDEN",
        403,
    )

    untouched = read_client(owned_client["id"])
    assert untouched["trust_balance_cents"] == 100_000
    assert untouched["version"] == funded_version
    lines = list_client_ledger(owned_client["id"])
    assert len(lines) == 1
    assert lines[0]["direction"] == "DEPOSIT"


def test_every_remaining_collection_reports_its_own_missing_row():
    """PRD §2.8: "The identifier reported names the missing kind:
    `ERR_ADVISOR_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_CREDENTIAL_NOT_FOUND`,
    `ERR_SUPPLIER_NOT_FOUND`, `ERR_CONSORTIUM_NOT_FOUND`, `ERR_SPLIT_SCHEDULE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
    `ERR_SETTLEMENT_RUN_NOT_FOUND` or `ERR_STATEMENT_NOT_FOUND`."

    Design: Corner/errors/corner_typed_404s_across_the_remaining_collections
    """
    probes = [
        (
            api_client.get_advisor_agreement(NON_EXISTENT_UUID, ops()),
            "ERR_AGREEMENT_NOT_FOUND",
        ),
        (
            api_client.get_compliance_credential(NON_EXISTENT_UUID, compliance()),
            "ERR_CREDENTIAL_NOT_FOUND",
        ),
        (
            api_client.get_commission_claim(NON_EXISTENT_UUID, ops()),
            "ERR_CLAIM_NOT_FOUND",
        ),
        (
            api_client.get_settlement_run(NON_EXISTENT_UUID, controller("ctrl-1")),
            "ERR_SETTLEMENT_RUN_NOT_FOUND",
        ),
        (
            api_client.get_advisor_statement(NON_EXISTENT_UUID, controller("ctrl-1")),
            "ERR_STATEMENT_NOT_FOUND",
        ),
        (api_client.get_client(NON_EXISTENT_UUID, ops()), "ERR_CLIENT_NOT_FOUND"),
    ]

    for response, expected_error_id in probes:
        error = validate_error(response, expected_error_id, 404)
        assert error["error_id"] == expected_error_id
        body = response.json()
        assert body["response_type"] == "error"
        assert body["meta"]["api_request_id"].startswith("req_")


def test_the_money_axis_and_the_claim_cycle_each_guard_their_own_order():
    """PRD §3.7: "The booking's `commission_status` must be `EXPECTED` and its
    `booking_status` must be `CONFIRMED` or `TRAVELED`; anything else reports
    `ERR_INVALID_COMMISSION_STATE`."
    PRD §3.7: "Denying a claim that is not `SUBMITTED`, or resubmitting one that is not
    `DENIED`, or acting at all on an already-resolved claim, reports
    `ERR_INVALID_CLAIM_STATE`."

    Design: Corner/errors/corner_commission_and_claim_state_gates_reject_out_of_order_triggers
    """
    supplier = new_supplier(**MERIDIAN)
    ctx = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        schedule=_standard_schedule(),
        suppliers=[supplier],
    )
    advisor = ctx["advisor"]
    client = new_client(advisor["id"], full_name="Nadia Okoye", home_state_code="NY")
    booking = new_booking(
        advisor["id"],
        supplier["id"],
        client["id"],
        channel="SUPPLIER_DIRECT",
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=1_000_000,
        travel_start_date="2026-05-01",
        travel_end_date="2026-05-10",
    )
    assert booking["commission_status"] == "PENDING"

    validate_error(
        api_client.record_commission_receipt(
            booking["id"],
            commission_receipt_payload(100_000, "2026-08-01"),
            make_supplier_portal_headers(supplier["id"]),
        ),
        "ERR_INVALID_COMMISSION_STATE",
        409,
    )
    assert read_booking(booking["id"])["received_commission_cents"] == 0

    confirm_booking(booking["id"], supplier["id"])
    mark_traveled(booking["id"])

    claim = file_claim(booking["id"], advisor["id"], 100_000)
    assert claim["round_count"] == 1
    assert read_booking(booking["id"])["commission_status"] == "CLAIMED"

    denied = validate_success(
        api_client.deny_commission_claim(
            claim["id"],
            claim_denial_payload("Booking not found in supplier records"),
            make_supplier_portal_headers(supplier["id"]),
        )
    )
    assert denied["status"] == "DENIED"

    validate_error(
        api_client.deny_commission_claim(
            claim["id"],
            claim_denial_payload("Denying again"),
            make_supplier_portal_headers(supplier["id"]),
        ),
        "ERR_INVALID_CLAIM_STATE",
        409,
    )

    still_denied = read_claim(claim["id"])
    assert still_denied["status"] == "DENIED"
    assert still_denied["round_count"] == 1


def test_the_payment_gates_and_the_two_man_rule_each_have_their_own_refusal():
    """PRD §3.8: "the parent run must have reached `POSTED`, failing which
    `ERR_RUN_NOT_POSTED` — this outranks the statement's own status so that an unposted run is
    reported as the run's problem — and only then must the statement itself be `POSTED`, so a
    statement already `PAID`, or one still `DRAFT` beneath a run that has somehow been posted,
    reports `ERR_INVALID_STATEMENT_STATE`."
    PRD §3.8: "it is refused with `ERR_SEGREGATION_OF_DUTIES` when the acting `X-User-ID`
    equals the run's recorded `calculated_by_user_id`"

    Design: Corner/errors/corner_settlement_payment_gates_and_segregation_of_duties
    """
    supplier = new_supplier(**MERIDIAN)
    schedule = _standard_schedule()
    first = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        schedule=schedule,
        suppliers=[supplier],
        number_prefix="A",
    )["advisor"]
    second = setup_active_advisor(
        state="NY",
        legal_name="Sam Ortiz",
        email="sam.ortiz@example.com",
        schedule=schedule,
        suppliers=[supplier],
        number_prefix="B",
    )["advisor"]

    def _remitted(advisor, gross, remitted, client_name, start, end):
        client = new_client(advisor["id"], full_name=client_name, home_state_code="NY")
        booking = new_booking(
            advisor["id"],
            supplier["id"],
            client["id"],
            channel="SUPPLIER_DIRECT",
            payment_method="MERCHANT_DIRECT",
            gross_sale_cents=gross,
            travel_start_date=start,
            travel_end_date=end,
        )
        confirm_booking(booking["id"], supplier["id"])
        return record_receipt(booking["id"], supplier["id"], remitted, "2026-08-01")

    _remitted(first, 1_000_000, 100_000, "Nadia Okoye", "2026-05-01", "2026-05-10")
    _remitted(second, 2_000_000, 200_000, "Marco Vidal", "2026-05-01", "2026-05-10")

    run = calculate_run(open_run("2026-08")["id"], "ctrl-1")
    assert run["statement_count"] == 2
    assert run["advisor_share_total_cents"] == 210_000

    first_statement = statements_for_advisor(first["id"])[0]
    second_statement = statements_for_advisor(second["id"])[0]
    assert first_statement["status"] == "DRAFT"

    validate_error(
        api_client.pay_advisor_statement(
            first_statement["id"],
            pay_statement_payload("ACH-2026-08-0001"),
            controller("ctrl-1"),
        ),
        "ERR_RUN_NOT_POSTED",
        409,
    )

    validate_error(
        api_client.post_settlement_run(run["id"], controller("ctrl-1")),
        "ERR_SEGREGATION_OF_DUTIES",
        409,
    )
    assert read_run(run["id"])["status"] == "CALCULATED"

    posted = validate_success(
        api_client.post_settlement_run(run["id"], controller("ctrl-2"))
    )
    assert posted["status"] == "POSTED"
    assert posted["posted_by_user_id"] == "ctrl-2"
    assert read_statement(first_statement["id"])["status"] == "POSTED"
    assert read_statement(second_statement["id"])["status"] == "POSTED"

    paid = validate_success(
        api_client.pay_advisor_statement(
            first_statement["id"],
            pay_statement_payload("ACH-2026-08-0001"),
            controller("ctrl-1"),
        )
    )
    assert paid["status"] == "PAID"
    assert paid["net_payout_cents"] == 66_500
    assert read_run(run["id"])["status"] == "POSTED"

    validate_error(
        api_client.pay_advisor_statement(
            first_statement["id"],
            pay_statement_payload("ACH-2026-08-0002"),
            controller("ctrl-1"),
        ),
        "ERR_INVALID_STATEMENT_STATE",
        409,
    )
    assert read_statement(first_statement["id"])["paid_at"] == paid["paid_at"]

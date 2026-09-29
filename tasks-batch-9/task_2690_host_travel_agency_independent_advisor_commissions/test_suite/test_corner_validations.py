"""Validation rules: the clean path, money shapes, input coherence and uniqueness."""
import pytest

from test_helpers import (
    advisor_agreements,
    advisor_deposit,
    api_client,
    claim_resolution_payload,
    commission_claim_payload,
    commission_receipt_payload,
    compliance,
    confirm_booking,
    controller_disbursement,
    create_advisor_payload,
    create_booking_payload,
    create_settlement_run_payload,
    declare_departure,
    declare_departure_payload,
    eo_policy_credential_payload,
    make_advisor_headers,
    make_supplier_portal_headers,
    new_advisor,
    new_booking,
    new_client,
    new_split_schedule,
    new_supplier,
    ops,
    open_run,
    read_advisor,
    read_agreement,
    read_booking,
    read_client,
    read_run,
    read_supplier,
    record_receipt,
    seller_of_travel_credential_payload,
    set_clock,
    setup_active_advisor,
    training_cert_credential_payload,
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


def _accredited_advisor(state="NY", **overrides):
    supplier = overrides.pop("supplier", None) or new_supplier(**MERIDIAN)
    ctx = setup_active_advisor(
        state=state,
        schedule=_standard_schedule(),
        suppliers=[supplier],
        **overrides,
    )
    client = new_client(
        ctx["advisor"]["id"],
        full_name="Nadia Okoye",
        home_state_code=state,
        max_concurrent_trips=4,
    )
    ctx["supplier"] = supplier
    ctx["client"] = client
    return ctx


def test_a_booking_that_satisfies_every_rule_is_accepted():
    """PRD §3.5: "Its `agreement_id` is set to the advisor's currently `ACTIVE` agreement and
    is never re-pinned afterwards except by the departure cascade in §3.9; its `statement_id`
    is null until a settlement run claims it."

    Design: Corner/validations/corner_clean_booking_passes_every_gate
    """
    ctx = _accredited_advisor(
        legal_name="Dana Reyes", email="dana.reyes@example.com"
    )
    advisor = ctx["advisor"]

    response = api_client.create_booking(
        create_booking_payload(
            advisor["id"],
            ctx["supplier"]["id"],
            ctx["client"]["id"],
            channel="SUPPLIER_DIRECT",
            payment_method="MERCHANT_DIRECT",
            gross_sale_cents=1_000_000,
            travel_start_date="2026-10-01",
            travel_end_date="2026-10-10",
        ),
        make_advisor_headers(advisor["id"]),
    )
    booking = validate_success(response, 201)
    assert "error_id" not in response.json()

    assert booking["booking_status"] == "SUBMITTED"
    assert booking["commission_status"] == "PENDING"
    assert booking["expected_commission_cents"] == 100_000
    assert booking["applied_commission_rate"] == pytest.approx(0.10)
    assert booking["agreement_id"] == ctx["agreement"]["id"]
    assert booking["statement_id"] is None
    assert read_advisor(advisor["id"])["production_ytd_provisional_cents"] == 100_000


def test_each_money_shape_rule_refuses_only_the_illegal_amount():
    """PRD §3.7: "The remitted `amount_cents` may not exceed the booking's
    `expected_commission_cents` — a supplier cannot pay more than it owes — and an excess is
    refused with `ERR_RECEIPT_EXCEEDS_EXPECTED`."

    Design: Corner/validations/corner_commission_money_rules_reject_bad_amounts
    """
    ctx = _accredited_advisor(
        legal_name="Dana Reyes", email="dana.reyes@example.com"
    )
    advisor, supplier = ctx["advisor"], ctx["supplier"]
    booking = new_booking(
        advisor["id"],
        supplier["id"],
        ctx["client"]["id"],
        channel="SUPPLIER_DIRECT",
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=1_000_000,
        travel_start_date="2026-10-01",
        travel_end_date="2026-10-10",
    )
    confirm_booking(booking["id"], supplier["id"])

    validate_error(
        api_client.record_commission_receipt(
            booking["id"],
            commission_receipt_payload(200_000, "2026-08-01"),
            make_supplier_portal_headers(supplier["id"]),
        ),
        "ERR_RECEIPT_EXCEEDS_EXPECTED",
        422,
    )
    refused = read_booking(booking["id"])
    assert refused["commission_status"] == "EXPECTED"
    assert refused["received_commission_cents"] == 0

    short_paid = record_receipt(booking["id"], supplier["id"], 60_000, "2026-08-01")
    assert short_paid["shortfall_cents"] == 40_000
    assert short_paid["commission_status"] == "RECEIVED"

    validate_error(
        api_client.create_commission_claim(
            booking["id"],
            commission_claim_payload(100_000),
            make_advisor_headers(advisor["id"]),
        ),
        "ERR_CLAIM_AMOUNT_MISMATCH",
        422,
    )

    claim = validate_success(
        api_client.create_commission_claim(
            booking["id"],
            commission_claim_payload(40_000),
            make_advisor_headers(advisor["id"]),
        ),
        201,
    )
    assert claim["claimed_amount_cents"] == 40_000
    assert read_booking(booking["id"])["commission_status"] == "CLAIMED"

    validate_error(
        api_client.resolve_commission_claim(
            claim["id"],
            claim_resolution_payload("PAID", 50_000),
            ops(),
        ),
        "ERR_CLAIM_RESOLUTION_INVALID",
        422,
    )

    resolved = validate_success(
        api_client.resolve_commission_claim(
            claim["id"],
            claim_resolution_payload("PAID", 40_000),
            ops(),
        )
    )
    assert resolved["status"] == "RESOLVED_PAID"

    settled = read_booking(booking["id"])
    assert settled["received_commission_cents"] == 100_000
    assert settled["shortfall_cents"] == 0
    assert settled["commission_status"] == "RECEIVED"


def test_incoherent_shapes_empty_ranges_and_a_backwards_clock_are_all_refused():
    """PRD §3.3: "Any other combination — an E&O row carrying a jurisdiction, a registration
    row with no jurisdiction, an accreditation row with a coverage amount — is rejected with
    `ERR_CREDENTIAL_FIELDS_INCOHERENT`."
    PRD §2.5: "The clock is monotonic: a request naming a `to_iso8601` earlier than the
    current logical clock is rejected with `ERR_CLOCK_REWIND_FORBIDDEN` (HTTP 422)."

    Design: Corner/validations/corner_shape_date_and_clock_rules_reject_incoherent_input
    """
    new_supplier(**MERIDIAN)
    advisor = new_advisor(
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        seller_of_travel_state="NY",
    )
    set_clock("2026-08-15T00:00:00Z")

    incoherent_policy = eo_policy_credential_payload(
        credential_number="EO-77001",
        effective_on="2026-01-01",
        expires_on="2027-01-01",
        coverage_amount_cents=100_000_000,
    )
    incoherent_policy["jurisdiction_state_code"] = "NY"
    validate_error(
        api_client.create_compliance_credential(advisor["id"], incoherent_policy, ops()),
        "ERR_CREDENTIAL_FIELDS_INCOHERENT",
        422,
    )

    stateless_registration = seller_of_travel_credential_payload(
        jurisdiction_state_code="NY",
        credential_number="NY-SOT-77002",
        effective_on="2026-01-01",
        expires_on="2027-01-01",
    )
    stateless_registration["jurisdiction_state_code"] = None
    validate_error(
        api_client.create_compliance_credential(
            advisor["id"], stateless_registration, ops()
        ),
        "ERR_CREDENTIAL_FIELDS_INCOHERENT",
        422,
    )

    validate_error(
        api_client.create_compliance_credential(
            advisor["id"],
            training_cert_credential_payload(
                credential_number="TRN-77003",
                effective_on="2026-06-01",
                expires_on="2026-06-01",
            ),
            ops(),
        ),
        "ERR_INVALID_DATE_RANGE",
        422,
    )

    validate_error(
        api_client.advance_clock_to("2026-08-14T23:59:59Z", ops()),
        "ERR_CLOCK_REWIND_FORBIDDEN",
        422,
    )
    same_instant = validate_success(
        api_client.advance_clock_to("2026-08-15T00:00:00Z", ops())
    )
    assert same_instant["current_utc"].startswith("2026-08-15T00:00:00")

    _, meta = validate_paginated(
        api_client.list_compliance_credentials(ops(), {"advisor_id": advisor["id"]})
    )
    assert meta["total_count"] == 0


def test_the_three_uniqueness_rules_each_report_their_own_conflict():
    """PRD §2.8: "**Uniqueness** — `ERR_ADVISOR_EMAIL_DUPLICATE` on `POST /advisors`,
    `ERR_SETTLEMENT_PERIOD_DUPLICATE` on `POST /settlement-runs`, and
    `ERR_TRANSITION_ADVISOR_INVALID` on `POST /advisors/{id}/departure`, all HTTP 409."

    Design: Corner/validations/corner_uniqueness_rules_return_distinct_409s
    """
    ctx = _accredited_advisor(
        legal_name="Dana Reyes", email="dana.reyes@example.com"
    )
    advisor = ctx["advisor"]
    run = open_run("2026-06")

    validate_error(
        api_client.create_advisor(
            create_advisor_payload(
                legal_name="Dana Reyes II",
                email="dana.reyes@example.com",
                seller_of_travel_state="TX",
            ),
            ops(),
        ),
        "ERR_ADVISOR_EMAIL_DUPLICATE",
        409,
    )
    _, advisor_meta = validate_paginated(api_client.list_advisors(ops()))
    assert advisor_meta["total_count"] == 1

    validate_error(
        api_client.create_settlement_run(create_settlement_run_payload("2026-06"), ops()),
        "ERR_SETTLEMENT_PERIOD_DUPLICATE",
        409,
    )
    survivor = read_run(run["id"])
    assert survivor["period_month"] == "2026-06"
    assert survivor["version"] == run["version"]

    validate_error(
        api_client.declare_departure(
            advisor["id"],
            declare_departure_payload(advisor["id"], effective_date="2026-09-01"),
            ops(),
        ),
        "ERR_TRANSITION_ADVISOR_INVALID",
        409,
    )

    unchanged = read_advisor(advisor["id"])
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["transition_advisor_id"] is None
    assert unchanged["departure_effective_date"] is None
    assert read_run(run["id"])["status"] == "OPEN"


def test_finalization_waits_for_the_trust_account_to_be_emptied():
    """PRD §3.9: "it requires every client owned by that advisor to have a
    `trust_balance_cents` of exactly 0, which is why an unrefunded trust deposit from a
    cancelled `CLIENT_TRUST` booking blocks a departure until the controller has recorded the
    refund"

    Design: Corner/validations/corner_departure_finalize_blocked_by_client_trust_balance
    """
    schedule = _standard_schedule()
    leaver = setup_active_advisor(
        state="CA",
        legal_name="Priya Nair",
        email="priya.nair@example.com",
        schedule=schedule,
        number_prefix="A",
    )["advisor"]
    successor = setup_active_advisor(
        state="CA",
        legal_name="Marco Vidal",
        email="marco.vidal@example.com",
        schedule=schedule,
        number_prefix="B",
    )["advisor"]

    client = new_client(
        leaver["id"],
        full_name="Nadia Okoye",
        home_state_code="CA",
        ownership_mode="HOST_OWNED",
    )
    funded = advisor_deposit(
        client["id"], leaver["id"], 100_000, memo="Client wire held in trust"
    )
    assert funded["balance_after_cents"] == 100_000

    departing = declare_departure(leaver["id"], successor["id"], effective_date="2026-09-01")
    assert departing["status"] == "DEPARTING"
    assert departing["transition_advisor_id"] == successor["id"]

    validate_error(
        api_client.finalize_departure(leaver["id"], compliance()),
        "ERR_DEPARTURE_BLOCKED",
        409,
    )
    blocked = read_advisor(leaver["id"])
    assert blocked["status"] == "DEPARTING"
    assert read_client(client["id"])["owner_advisor_id"] == leaver["id"]

    emptied = controller_disbursement(
        client["id"], 100_000, memo="Trust funds released to the client"
    )
    assert emptied["balance_after_cents"] == 0

    departed = validate_success(
        api_client.finalize_departure(leaver["id"], compliance())
    )
    assert departed["status"] == "DEPARTED"

    rehomed = read_client(client["id"])
    assert rehomed["owner_advisor_id"] == successor["id"]
    assert rehomed["portability_status"] == "RETAINED"
    assert read_agreement(_only_agreement(leaver["id"]))["status"] == "TERMINATED"


def _only_agreement(advisor_id):
    rows = advisor_agreements(advisor_id)
    assert len(rows) == 1
    return rows[0]["id"]


def test_the_trust_regime_rule_binds_only_the_advisors_it_applies_to():
    """PRD §3.5: "when `trust_account_required` is true the `payment_method` must be
    `CLIENT_TRUST` and anything else is refused with `ERR_TRUST_ACCOUNT_REQUIRED`, while when
    `trust_account_required` is false the `payment_method` must be either `MERCHANT_DIRECT` or
    `HOST_MERCHANT` and a `CLIENT_TRUST` booking is refused with
    `ERR_TRUST_ACCOUNT_NOT_PERMITTED`"

    Design: Corner/validations/corner_payment_method_rule_applies_only_per_trust_flag
    """
    supplier = new_supplier(**MERIDIAN)
    schedule = _standard_schedule()
    trust_bound = setup_active_advisor(
        state="CA",
        legal_name="Priya Nair",
        email="priya.nair@example.com",
        schedule=schedule,
        suppliers=[supplier],
        number_prefix="A",
    )["advisor"]
    unbound = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        schedule=schedule,
        suppliers=[supplier],
        number_prefix="B",
    )["advisor"]
    assert trust_bound["trust_account_required"] is True
    assert unbound["trust_account_required"] is False

    trust_client = new_client(
        trust_bound["id"], full_name="Marco Vidal", home_state_code="CA"
    )
    plain_client = new_client(
        unbound["id"], full_name="Nadia Okoye", home_state_code="NY"
    )

    def _submit(advisor, client, payment_method):
        return api_client.create_booking(
            create_booking_payload(
                advisor["id"],
                supplier["id"],
                client["id"],
                channel="SUPPLIER_DIRECT",
                payment_method=payment_method,
                gross_sale_cents=1_000_000,
                deposit_amount_cents=0,
                travel_start_date="2026-10-01",
                travel_end_date="2026-10-10",
            ),
            make_advisor_headers(advisor["id"]),
        )

    validate_error(
        _submit(trust_bound, trust_client, "MERCHANT_DIRECT"),
        "ERR_TRUST_ACCOUNT_REQUIRED",
        422,
    )
    accepted_trust = validate_success(
        _submit(trust_bound, trust_client, "CLIENT_TRUST"), 201
    )
    assert accepted_trust["payment_method"] == "CLIENT_TRUST"
    assert accepted_trust["expected_commission_cents"] == 100_000

    validate_error(
        _submit(unbound, plain_client, "CLIENT_TRUST"),
        "ERR_TRUST_ACCOUNT_NOT_PERMITTED",
        422,
    )
    accepted_plain = validate_success(
        _submit(unbound, plain_client, "HOST_MERCHANT"), 201
    )
    assert accepted_plain["payment_method"] == "HOST_MERCHANT"
    assert accepted_plain["expected_commission_cents"] == 100_000


def test_a_fully_paid_booking_can_claim_no_amount_at_all():
    """PRD §3.7: "From `commission_status` `RECEIVED`, the booking's `shortfall_cents` must be
    strictly greater than zero, its `statement_id` must still be null, and the
    `claimed_amount_cents` must equal that `shortfall_cents` exactly."
    PRD §3.7: "Any amount that does not match the outstanding figure, a booking with no
    shortfall to claim, or a booking already swept into a statement, is refused with
    `ERR_CLAIM_AMOUNT_MISMATCH`"

    Design: Corner/validations/corner_claim_amount_check_reads_the_receipt_derived_shortfall
    """
    ctx = _accredited_advisor(
        legal_name="Dana Reyes", email="dana.reyes@example.com"
    )
    advisor, supplier = ctx["advisor"], ctx["supplier"]
    booking = new_booking(
        advisor["id"],
        supplier["id"],
        ctx["client"]["id"],
        channel="SUPPLIER_DIRECT",
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=1_000_000,
        travel_start_date="2026-10-01",
        travel_end_date="2026-10-10",
    )
    confirm_booking(booking["id"], supplier["id"])

    paid_in_full = record_receipt(booking["id"], supplier["id"], 100_000, "2026-08-01")
    assert paid_in_full["received_commission_cents"] == 100_000
    assert paid_in_full["shortfall_cents"] == 0
    assert paid_in_full["commission_status"] == "RECEIVED"

    validate_error(
        api_client.create_commission_claim(
            booking["id"],
            commission_claim_payload(100_000),
            make_advisor_headers(advisor["id"]),
        ),
        "ERR_CLAIM_AMOUNT_MISMATCH",
        422,
    )
    validate_error(
        api_client.create_commission_claim(
            booking["id"],
            commission_claim_payload(1),
            make_advisor_headers(advisor["id"]),
        ),
        "ERR_CLAIM_AMOUNT_MISMATCH",
        422,
    )

    untouched = read_booking(booking["id"])
    assert untouched["commission_status"] == "RECEIVED"
    assert untouched["shortfall_cents"] == 0

    _, meta = validate_paginated(
        api_client.list_commission_claims(ops(), {"booking_id": booking["id"]})
    )
    assert meta["total_count"] == 0
    assert read_supplier(supplier["id"])["total_outstanding_cents"] == 0

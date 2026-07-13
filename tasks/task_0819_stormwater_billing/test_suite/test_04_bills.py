"""Bill issuance: fee-variant divergence, active-parcel precondition, period
overlap, credit application, account/parcel referential integrity, and listing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_bill_payload,
    create_active_parcel, setup_issued_bill,
)

ASSESSOR = TEST_USERS["assessor_headers"]
BILLING_CLERK = TEST_USERS["billing_clerk_headers"]


def test_bill_marginal_variant_fee_eru6(api):
    """PRD §3.5: "Under the `MARGINAL` variant — the default — each band is
    charged at its own rate."
    PRD §3.5: "The `net_fee_cents` — the total owed — is the assessed fee plus
    any `penalty_cents`."

    Design: Difficulty/dual_variant_calc/fee_marginal_vs_flat_diverge_on_bill
    """
    base = create_active_parcel(api, measured_sqft=18000, land_use="COMMERCIAL")
    bill = validate_success(
        api.create_bill(
            create_bill_payload(base["parcel"]["id"], base["account"]["id"],
                                fee_variant="MARGINAL"), BILLING_CLERK),
        expected_status=201)
    assert bill["base_fee_cents"] == 21000
    assert bill["net_fee_cents"] == 21500


def test_bill_flat_variant_fee_eru6_diverges(api):
    """PRD §3.5: "Under the `FLAT` variant, the entire ERU is charged at the
    single rate of the tier the total ERU falls into: 4,000 cents per ERU when
    the ERU is at most 1.0, 3,500 cents per ERU when the ERU is at most 5.0, and
    3,000 cents per ERU when the ERU exceeds 5.0."
    PRD §3.5: "The flat and marginal figures agree only when ERU is at most 1.0
    and diverge whenever ERU exceeds 1.0."

    Design: Difficulty/dual_variant_calc/fee_marginal_vs_flat_diverge_on_bill
    """
    base = create_active_parcel(api, measured_sqft=18000, land_use="COMMERCIAL")
    bill = validate_success(
        api.create_bill(
            create_bill_payload(base["parcel"]["id"], base["account"]["id"],
                                fee_variant="FLAT",
                                period_start="2026-04-01T00:00:00Z",
                                period_end="2026-06-30T00:00:00Z",
                                due_date="2026-07-31T00:00:00Z"), BILLING_CLERK),
        expected_status=201)
    assert bill["base_fee_cents"] == 18000
    assert bill["net_fee_cents"] == 18500


def test_bill_issue_on_draft_parcel_rejected(api):
    """PRD §3.5: "A bill may be issued only for a parcel that is `ACTIVE` — one
    that has an `ACTIVE` measurement — and issuing against a `DRAFT` parcel is
    rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/bill_issue_requires_active_parcel
    """
    acct = validate_success(api.create_account({"owner_name": "Acme",
                                                "contact_email": "a@x.com"}, ASSESSOR),
                            expected_status=201)
    parcel = validate_success(
        api.create_parcel({"account_id": acct["id"], "parcel_number": "P-CE1",
                           "land_use": "COMMERCIAL"}, ASSESSOR),
        expected_status=201)
    assert parcel["status"] == "DRAFT"
    resp = api.create_bill(create_bill_payload(parcel["id"], acct["id"]), BILLING_CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_bill_issue_on_active_parcel_succeeds(api):
    """PRD §3.5: "A bill may be issued only for a parcel that is `ACTIVE` — one
    that has an `ACTIVE` measurement — and issuing against a `DRAFT` parcel is
    rejected with `ERR_INVALID_STATE`."
    PRD §3.2: "The first measurement a parcel ever receives advances the parcel
    from `DRAFT` to `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/bill_issue_requires_active_parcel
    """
    base = create_active_parcel(api, measured_sqft=9000, land_use="COMMERCIAL")
    assert base["parcel"]["status"] == "ACTIVE"
    bill = validate_success(
        api.create_bill(
            create_bill_payload(base["parcel"]["id"], base["account"]["id"]),
            BILLING_CLERK),
        expected_status=201)
    assert bill["status"] == "ISSUED"


def test_bill_period_shared_endpoint_overlap_rejected(api):
    """PRD §3.5: "The new bill's period may not overlap any non-`VOID` bill
    already on the same parcel; because the bill period is a closed interval, two
    periods that share even a single endpoint day conflict, and the overlap is
    rejected with `ERR_BILL_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/bill_period_closed_shared_endpoint_overlap_rejected
    """
    base = create_active_parcel(api, measured_sqft=18000, land_use="COMMERCIAL")
    validate_success(
        api.create_bill(
            create_bill_payload(base["parcel"]["id"], base["account"]["id"],
                                period_start="2026-01-01T00:00:00Z",
                                period_end="2026-06-30T00:00:00Z",
                                due_date="2026-07-31T00:00:00Z"), BILLING_CLERK),
        expected_status=201)
    resp = api.create_bill(
        create_bill_payload(base["parcel"]["id"], base["account"]["id"],
                            period_start="2026-06-30T00:00:00Z",
                            period_end="2026-12-31T00:00:00Z",
                            due_date="2027-01-31T00:00:00Z"), BILLING_CLERK)
    validate_error(resp, ApiErrorId.ERR_BILL_PERIOD_OVERLAP.value)


def test_bill_period_adjacent_no_shared_day_allowed(api):
    """PRD §3.5: "The new bill's period may not overlap any non-`VOID` bill
    already on the same parcel; because the bill period is a closed interval, two
    periods that share even a single endpoint day conflict, and the overlap is
    rejected with `ERR_BILL_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/bill_period_closed_shared_endpoint_overlap_rejected
    """
    # Adjacent, non-touching periods (no shared day) must NOT conflict.
    base = create_active_parcel(api, measured_sqft=18000, land_use="COMMERCIAL")
    validate_success(
        api.create_bill(
            create_bill_payload(base["parcel"]["id"], base["account"]["id"],
                                period_start="2026-01-01T00:00:00Z",
                                period_end="2026-06-30T00:00:00Z",
                                due_date="2026-07-31T00:00:00Z"), BILLING_CLERK),
        expected_status=201)
    second = validate_success(
        api.create_bill(
            create_bill_payload(base["parcel"]["id"], base["account"]["id"],
                                period_start="2026-07-01T00:00:00Z",
                                period_end="2026-12-31T00:00:00Z",
                                due_date="2027-01-31T00:00:00Z"), BILLING_CLERK),
        expected_status=201)
    assert second["status"] == "ISSUED"


def test_credit_amount_applied_to_creditable_base_on_bill(api):
    """PRD §3.5: "the credit discount applies only to that creditable base and
    never to the fixed administrative charge: `credit_amount_cents` is the base
    fee multiplied by the parcel's active credit fraction, rounded to whole cents,
    and is 0 when the parcel has no `ACTIVE` credit."

    Design: Corner/calculations/credit_amount_applied_to_creditable_base_on_bill
    """
    base = setup_issued_bill(api, measured_sqft=18000, fee_variant="MARGINAL",
                             with_credit=True, self_reported_score=90)
    bill = base["bill"]
    assert bill["credit_amount_cents"] == 10500
    assert bill["net_fee_cents"] == 11000


def test_bill_account_parcel_mismatch_rejected(api):
    """PRD §3.5: "The `account_id` on the bill must equal the parcel's owning
    account; a mismatch is rejected with `ERR_ACCOUNT_PARCEL_MISMATCH`."

    Design: Corner/validations/bill_account_parcel_mismatch_rejected
    """
    base = create_active_parcel(api, measured_sqft=9000, land_use="COMMERCIAL")
    acct_b = validate_success(api.create_account({"owner_name": "B",
                                                  "contact_email": "b@x.com"}, ASSESSOR),
                              expected_status=201)
    resp = api.create_bill(
        create_bill_payload(base["parcel"]["id"], acct_b["id"]), BILLING_CLERK)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_PARCEL_MISMATCH.value)


def test_bill_inverted_period_rejected(api):
    """PRD §3.5: "The `period_start` must not fall after the `period_end`;
    otherwise the request is rejected with `ERR_INVALID_PERIOD`."

    Design: Corner/validations/bill_inverted_period_rejected
    """
    base = create_active_parcel(api, measured_sqft=9000, land_use="COMMERCIAL")
    resp = api.create_bill(
        create_bill_payload(base["parcel"]["id"], base["account"]["id"],
                            period_start="2026-06-30T00:00:00Z",
                            period_end="2026-01-01T00:00:00Z",
                            due_date="2026-07-31T00:00:00Z"), BILLING_CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD.value)


def test_bills_list_filter_by_account(api):
    """PRD §2.3: "Every list response reports `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object."
    PRD §4: "GET | `/bills` | List bills, filterable by parcel or account."

    Design: Corner/endpoints/bills_list_filter_by_account_reverse_reachability
    """
    base = setup_issued_bill(api, measured_sqft=9000, land_use="COMMERCIAL")
    data, meta = validate_paginated(
        api.list_bills(BILLING_CLERK, params={"account_id": base["account"]["id"]}))
    assert any(b["id"] == base["bill"]["id"] for b in data)
    assert "total_count" in meta and "has_more" in meta

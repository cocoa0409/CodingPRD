"""Bill issuance: levy, exemption pre-credit, the installment split, and initial state."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    assert_tax_bill,
    create_tax_year, create_parcel, issue_bill, setup_year_parcel_bill,
    installments_by_bill, get_bill, post_payment,
    submit_relief, review_relief, decide_relief,
    TEST_USERS,
)

TREASURER = TEST_USERS["treasurer_headers"]


# ---- Difficulty: installment_split_remainder_to_last (test 1 of 2) ----
def test_odd_net_tax_first_installment_floors(api):
    """PRD 3.2: "The first installment's `principal_due_cents` is `net_tax_cents` divided
    by two using integer floor division, dropping any fractional cent."

    Design: Difficulty/combinatorial_formula/installment_split_remainder_to_last
    """
    ty, parcel, bill = setup_year_parcel_bill(api, assessed_value_cents=20000050,
                                              property_class="COMMERCIAL")
    assert bill["net_tax_cents"] == 400001
    insts = installments_by_bill(api, bill["id"])
    assert insts[1]["principal_due_cents"] == 200000


# ---- Difficulty: installment_split_remainder_to_last (test 2 of 2) ----
def test_odd_net_tax_last_installment_absorbs_remainder(api):
    """PRD 3.2: "The second installment's `principal_due_cents` is `net_tax_cents` minus
    the first installment's principal, so the last installment absorbs the
    odd remaining cent when the net tax is odd."

    Design: Difficulty/combinatorial_formula/installment_split_remainder_to_last
    """
    ty, parcel, bill = setup_year_parcel_bill(api, assessed_value_cents=20000050,
                                              property_class="COMMERCIAL")
    insts = installments_by_bill(api, bill["id"])
    assert insts[2]["principal_due_cents"] == 200001


# ---- Corner: calculations/bill_levy_applies_approved_exemption ----
def test_bill_levy_applies_approved_exemption(api):
    """PRD 3.2: "The exemption credit `exemption_credit_cents` is the sum of the
    `approved_credit_cents` of every relief application on the same parcel
    and tax year that is both classified `EXEMPTION` and in status
    `APPROVED`, capped so that net tax is never driven below zero."
    PRD 3.2: "The net tax `net_tax_cents` is the greater of zero and `gross_tax_cents`
    minus `exemption_credit_cents`; it is the amount split into
    installments."

    Design: Corner/calculations/bill_levy_applies_approved_exemption
    """
    ty = create_tax_year(api)
    parcel = create_parcel(api, parcel_number="APN-C10", assessed_value_cents=20000000)
    app = submit_relief(api, parcel["id"], ty["id"], "EXEMPTION", "HOMESTEAD",
                        claimed_amount_cents=100000, effective_from="2025-01-01T00:00:00Z")
    review_relief(api, app["id"])
    decide_relief(api, app["id"], "APPROVE")
    bill = issue_bill(api, parcel["id"], ty["id"])
    assert bill["gross_tax_cents"] == 400000
    assert bill["exemption_credit_cents"] == 100000
    assert bill["net_tax_cents"] == 300000
    insts = installments_by_bill(api, bill["id"])
    assert insts[1]["principal_due_cents"] == 150000
    assert insts[2]["principal_due_cents"] == 150000


# ---- Corner: state_machines/new_bill_starts_in_current_none_pending ----
def test_new_bill_starts_current_none_pending(api):
    """PRD 3.2: "The freshly issued bill starts with `collection_status` of `CURRENT` and
    `sale_status` of `NONE`."
    PRD 3.4: "An installment moves from `PENDING` to `PARTIALLY_PAID` when its allocated
    principal is positive but less than its `principal_due_cents`, and to
    `PAID` when its balance reaches zero"

    Design: Corner/state_machines/new_bill_starts_in_current_none_pending
    """
    ty, parcel, bill = setup_year_parcel_bill(api, assessed_value_cents=20000000)
    assert_tax_bill(bill)
    assert bill["collection_status"] == "CURRENT"
    assert bill["sale_status"] == "NONE"
    insts = installments_by_bill(api, bill["id"])
    assert insts[1]["status"] == "PENDING"
    assert insts[2]["status"] == "PENDING"


# ---- Corner: validations/duplicate_bill_for_parcel_year_rejected ----
def test_duplicate_bill_for_parcel_year_rejected(api):
    """PRD 3.2: "At most one bill may exist for any given pairing of `parcel_id` and
    `tax_year_id`; a second issuance for the same pair is rejected with
    `ERR_DUPLICATE_BILL`."

    Design: Corner/validations/duplicate_bill_for_parcel_year_rejected
    """
    ty, parcel, bill = setup_year_parcel_bill(api, assessed_value_cents=20000000)
    resp = api.create_tax_bill({"parcel_id": parcel["id"], "tax_year_id": ty["id"]}, TREASURER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BILL.value)


# ---- Corner: endpoints/list_installments_by_bill_id ----
def test_list_installments_by_bill_id(api):
    """PRD 3.2: "The bill is then divided into exactly two installments
    (`INSTALLMENT_COUNT` is two)."
    PRD 2.10: "installments by `bill_id".

    Design: Corner/endpoints/list_installments_by_bill_id
    """
    ty, parcel, bill = setup_year_parcel_bill(api, assessed_value_cents=20000000)
    resp = api.list_installments(TREASURER, params={"bill_id": bill["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert all(inst["bill_id"] == bill["id"] for inst in data)


# ---- Corner: endpoints/list_ledger_entries_for_bill ----
def test_list_ledger_entries_for_bill(api):
    """PRD 3.2: "For each installment the system posts a `CHARGE` ledger entry equal to
    its principal, so the bill's opening balance equals the net tax."

    Design: Corner/endpoints/list_ledger_entries_for_bill
    """
    ty, parcel, bill = setup_year_parcel_bill(api, assessed_value_cents=20000000)
    resp = api.list_ledger_entries(bill["id"], TREASURER)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert all(e["entry_type"] == "CHARGE" for e in data)


# ---- Corner: consistency_model/immediate_visibility_of_bill_balance ----
def test_immediate_visibility_of_bill_balance(api):
    """PRD 2.11: "a bill's `balance_cents` is exactly the sum of every one of its
    `LedgerEntry` amounts, with none excluded."

    Design: Corner/consistency_model/immediate_visibility_of_bill_balance
    """
    ty, parcel, bill = setup_year_parcel_bill(api, assessed_value_cents=20000000)
    post_payment(api, bill["id"], 200000)
    refreshed = get_bill(api, bill["id"])
    assert refreshed["balance_cents"] == 200000

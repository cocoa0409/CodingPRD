"""Business-rule validation corner cases: TI allowance, capacity, year mismatch,
estoppel balance / dispute note (breadth queue B — validations section).
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_lease_with_ti_allowance, request_ti_draw, approve_ti_draw,
    setup_issued_estoppel,
    create_property, create_tenant, create_active_lease, create_lease, create_pool,
    make_tenant_headers,
    PM_HEADERS, ACCT_HEADERS,
)


def test_ti_allowance_exceeded_on_approve(api):
    """PRD §3.6: "A draw that would push cumulative draws past the allowance is
    rejected with ERR_TI_ALLOWANCE_EXCEEDED."

    Design: Corner/validations/ti_allowance_exceeded_on_approve
    """
    prop, tenant, lease = setup_lease_with_ti_allowance(
        ti_allowance_cents=1000000, activate=True)
    draw1 = request_ti_draw(lease["id"], 500000)
    approve_ti_draw(draw1["id"])
    draw2 = request_ti_draw(lease["id"], 600000)  # 500000 + 600000 > 1000000
    res = api.approve_ti_draw(draw2["id"], ACCT_HEADERS)
    validate_error(res, "ERR_TI_ALLOWANCE_EXCEEDED", expected_status=422)
    after = validate_success(api.get_lease(lease["id"], PM_HEADERS), 200)
    assert after["ti_drawn_cents"] == 500000


def test_ti_allowance_exact_fit_passes(api):
    """PRD §3.6: "the lease's current ti_drawn_cents plus this draw's amount_cents
    does not exceed the lease's ti_allowance_cents"

    Design: Corner/validations/ti_allowance_exact_fit_passes
    """
    prop, tenant, lease = setup_lease_with_ti_allowance(
        ti_allowance_cents=1000000, activate=True)
    draw1 = request_ti_draw(lease["id"], 500000)
    approve_ti_draw(draw1["id"])
    draw2 = request_ti_draw(lease["id"], 500000)  # 500000 + 500000 == 1000000
    approved = validate_success(api.approve_ti_draw(draw2["id"], ACCT_HEADERS), 200)
    assert approved["status"] == "APPROVED"
    after = validate_success(api.get_lease(lease["id"], PM_HEADERS), 200)
    assert after["ti_drawn_cents"] == 1000000


def test_capacity_exceeded_on_activate(api):
    """PRD §3.3: "Activation also checks capacity: the lease's leased_sqft must not
    exceed the property's remaining capacity, which is total_rentable_sqft minus
    occupied_sqft at activation time; a lease that would overflow the building is
    rejected with ERR_CAPACITY_EXCEEDED."

    Design: Corner/validations/capacity_exceeded_on_activate
    """
    prop = create_property(total_rentable_sqft=10000)
    t1 = create_tenant("T1cap", "t1c@x.com")
    t2 = create_tenant("T2cap", "t2c@x.com")
    create_active_lease(prop["id"], t1["id"], leased_sqft=5000, base_rent_cents_annual=0)
    lease2 = create_lease(prop["id"], t2["id"], leased_sqft=6000, base_rent_cents_annual=0)
    res = api.activate_lease(lease2["id"], PM_HEADERS)
    validate_error(res, "ERR_CAPACITY_EXCEEDED", expected_status=422)
    after = validate_success(api.get_lease(lease2["id"], PM_HEADERS), 200)
    assert after["status"] == "DRAFT"


def test_year_mismatch_on_recon_create(api):
    """PRD §3.7: "The reconciliation year must equal the referenced pool's
    pool_year; a mismatch is rejected with ERR_YEAR_MISMATCH, both at creation and
    at submission."

    Design: Corner/validations/year_mismatch_on_recon_create
    """
    prop = create_property(total_rentable_sqft=10000)
    tenant = create_tenant()
    lease = create_active_lease(prop["id"], tenant["id"], leased_sqft=1000,
                                base_rent_cents_annual=0, estimated_cam_cents_monthly=0)
    pool = create_pool(prop["id"], pool_year=2025, admin_fee_pct=0)
    res = api.create_reconciliation(
        {"lease_id": lease["id"], "pool_id": pool["id"], "recon_year": 2024}, PM_HEADERS)
    validate_error(res, "ERR_YEAR_MISMATCH", expected_status=422)


def test_estoppel_confirm_balance_mismatch(api):
    """PRD §3.10: "A CONFIRMED response is accepted only when the certificate's
    asserted_balance_cents equals the referenced lease's live
    outstanding_balance_cents; if the asserted figure no longer matches the live
    ledger, the confirmation is rejected with ERR_ESTOPPEL_BALANCE_MISMATCH."

    Design: Corner/validations/estoppel_confirm_balance_mismatch
    """
    prop, tenant, lease, est = setup_issued_estoppel(asserted_balance_cents=999)
    res = api.respond_estoppel(
        est["id"], {"tenant_response": "CONFIRMED"}, make_tenant_headers(tenant["id"]))
    validate_error(res, "ERR_ESTOPPEL_BALANCE_MISMATCH", expected_status=422)
    after = validate_success(api.get_estoppel(est["id"], PM_HEADERS), 200)
    assert after["status"] == "ISSUED"


def test_estoppel_dispute_without_note_rejected(api):
    """PRD §3.10: "A DISPUTED response requires a non-empty dispute_note; a dispute
    submitted without one is rejected with ERR_DISPUTE_NOTE_REQUIRED."

    Design: Corner/validations/estoppel_dispute_without_note_rejected
    """
    prop, tenant, lease, est = setup_issued_estoppel(asserted_balance_cents=0)
    res = api.respond_estoppel(
        est["id"], {"tenant_response": "DISPUTED"}, make_tenant_headers(tenant["id"]))
    validate_error(res, "ERR_DISPUTE_NOTE_REQUIRED", expected_status=422)
    after = validate_success(api.get_estoppel(est["id"], PM_HEADERS), 200)
    assert after["status"] == "ISSUED"

"""Corner section: endpoints (PRD §3.4, §3.5).

Certify stamps the officer, Form 3922 computed boxes, and single-issuance guard.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_purchase_period_payload,
    create_offering_payload,
    create_plan_payload,
    setup_settled_purchase,
    setup_certified_batch,
    run_batch,
    make_officer_headers,
)


def test_certify_action_stamps_officer(api, admin_headers):
    """PRD §3.4: "Once a batch is OPEN, a ComplianceOfficer certifies it, advancing it
    from OPEN to CERTIFIED. Certification is permitted only when the batch is OPEN, and
    it stamps certified_by_user_id with the certifying officer's X-User-ID."

    Design: Corner/endpoints/certify_action_stamps_officer
    """
    plan = get_success_data(api.create_plan(create_plan_payload(), admin_headers))
    offering = get_success_data(
        api.create_offering_period(create_offering_payload(plan["id"]), admin_headers)
    )
    get_success_data(api.close_enrollment(offering["id"], admin_headers))
    batch = get_success_data(
        api.create_purchase_period(
            offering["id"], create_purchase_period_payload(), admin_headers
        )
    )
    get_success_data(api.open_purchase_period(batch["id"], admin_headers))
    certified = validate_success(
        api.certify_purchase_period(batch["id"], make_officer_headers("officer7"))
    )
    assert certified["status"] == "CERTIFIED", certified
    assert certified["certified_by_user_id"] == "officer7", certified


def _settled_117_share_purchase(api, admin_headers):
    ctx = setup_settled_purchase(
        plan_overrides={"discount_pct": 15, "lookback_enabled": True},
        offering_overrides={
            "grant_date": "2024-01-01T00:00:00.000Z", "grant_date_fmv_cents": 1000,
            "duration_months": 6,
        },
        batch_overrides={
            "purchase_date": "2024-06-30T00:00:00.000Z", "purchase_date_fmv_cents": 1200,
        },
        rate_pct=10, gross_pay_cents=1000000,
    )
    return ctx


def test_form3922_computed_read_boxes(api, admin_headers):
    """PRD §3.5: "populates box3_grant_date_fmv_cents with the grant-date fair market
    value, box4_purchase_date_fmv_cents with the purchase-date fair market value,
    box5_price_paid_cents with the actual price paid per share, and box6_shares with
    the number of shares transferred; sets tax_year to the calendar year of the
    batch's purchase_date".

    grant_fmv 1000, purchase_fmv 1200, price 850, shares 117, purchase 2024-06-30
    => box3=1000, box4=1200, box5=850, box6=117, tax_year=2024.

    Design: Corner/endpoints/form3922_computed_read_boxes
    """
    ctx = _settled_117_share_purchase(api, admin_headers)
    assert ctx["purchase"]["shares_purchased"] == 117, ctx["purchase"]
    # PRD §3.5: "Alongside each purchase, the system creates a ShareLot ... and a
    # Form3922 capturing the tax paperwork." The Form 3922 is created during the run;
    # a second on-demand issuance would be ERR_FORM_ALREADY_ISSUED (PRD §3.5), so we
    # READ the run-created form to verify its computed boxes.
    forms = get_success_data(
        api.list_forms_for_purchase(ctx["purchase"]["id"], make_officer_headers("officer1"))
    )
    assert len(forms) == 1, forms
    form = forms[0]
    assert form["box3_grant_date_fmv_cents"] == 1000, form
    assert form["box4_purchase_date_fmv_cents"] == 1200, form
    assert form["box5_price_paid_cents"] == 850, form
    assert form["box6_shares"] == 117, form
    assert form["tax_year"] == 2024, form


def test_form3922_already_issued_conditional(api, admin_headers):
    """PRD §3.5: "Whether created during the run or issued on demand, a purchase may
    have its Form 3922 issued only once; a second issuance for the same purchase is
    rejected with ERR_FORM_ALREADY_ISSUED (HTTP 409)."

    During run-purchase a Form 3922 is already created for each purchase, so an
    on-demand issuance for the same purchase is the second issuance.

    Design: Corner/endpoints/form3922_already_issued_conditional
    """
    ctx = setup_certified_batch(
        plan_overrides={"discount_pct": 15, "lookback_enabled": True},
        offering_overrides={"grant_date_fmv_cents": 1000, "duration_months": 6},
        batch_overrides={
            "purchase_date": "2024-05-31T00:00:00.000Z", "purchase_date_fmv_cents": 1200,
        },
        rate_pct=10, gross_pay_cents=1000000,
    )
    run_batch(ctx["batch"]["id"], ctx["pp_version"])
    purchases, _ = _list(api, api.list_purchases, admin_headers,
                         {"enrollment_id": ctx["enrollment"]["id"]})
    purchase_id = purchases[0]["id"]
    resp = api.issue_form_3922(purchase_id, make_officer_headers("officer1"))
    validate_error(resp, "ERR_FORM_ALREADY_ISSUED")


def _list(api, list_fn, headers, params):
    resp = list_fn(headers, params=params)
    body = resp.json()
    return body["data"], body["meta"]

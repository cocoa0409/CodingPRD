"""Recertification months-cap boundary.

Translates the queue-A boundary_precision_check months-cap instance on the
recert-decide endpoint.
"""
from test_helpers import (
    validate_success, get_success_data, TEST_USERS,
    make_caseworker_headers,
    build_application, create_cleared_disbursement,
    recertification_payload,
)

ADMIN = TEST_USERS["program_admin_headers"]
CW = TEST_USERS["caseworker_headers"]


def _disbursed_with_16_months(api, approver, issuer):
    """Approved+disbursed application consuming exactly 16 months for a size-1 tenant."""
    ctx = build_application(
        api, approve=True, approver_id=approver,
        household_size=1, income_limits={"1": 500000, "2": 566667},
        per_month_max_cents=250000, unit_rent_cents=100000, app_rent_cents=100000,
        income_sources=(("WAGES", 300000),),
        arrears_start_month=None, arrears_end_month=None,
        prospective_start_date="2026-03-01", prospective_end_date="2027-06-30",
        requested_prospective_months=16, ledger_lines=[],
    )
    create_cleared_disbursement(api, ctx["aid"], amount_cents=1600000, months_covered=16,
                                coverage_kind="PROSPECTIVE", version=ctx["version"],
                                issuer_id=issuer, payment_reference="ACH-12")
    return ctx


def test_recert_exactly_at_months_cap_is_approved(api):
    """PRD §3.8: "Approval requires that the application still be `DISBURSED`, that the
    household still be income-eligible, that the tenant's `months_used` plus
    `requested_additional_months` not exceed the program's `months_cap` (else
    `ERR_MONTHS_CAP_EXCEEDED`), and that `funding_pool_remaining_cents` be at least the
    extension cost — `requested_additional_months` multiplied by the smaller of the
    application's `monthly_rent_cents` and the program's `per_month_max_cents` (else
    `ERR_FUNDING_EXHAUSTED`)."

    Design: Difficulty/boundary_precision_check/months_cap_exactly_at_limit_on_recert
    """
    ctx = _disbursed_with_16_months(api, approver="cw-approver-12", issuer="cw-issuer-12")
    rcertid = get_success_data(api.create_recertification(
        ctx["aid"], recertification_payload(2, new_prospective_start_date="2027-07-01",
                                             new_prospective_end_date="2027-08-31"), CW))["id"]
    data = validate_success(api.decide_recertification(
        rcertid, {"decision": "APPROVE"}, make_caseworker_headers("cw-approver-12b")))
    assert data["status"] == "APPROVED"


def test_recert_at_cap_reserves_up_to_cap_months(api):
    """PRD §2.8: "Any grant that would push a household's `months_used` above the
    program's `months_cap` is rejected with `ERR_MONTHS_CAP_EXCEEDED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/months_cap_exactly_at_limit_on_recert
    """
    ctx = _disbursed_with_16_months(api, approver="cw-approver-12c", issuer="cw-issuer-12c")
    rcertid = get_success_data(api.create_recertification(
        ctx["aid"], recertification_payload(2, new_prospective_start_date="2027-07-01",
                                             new_prospective_end_date="2027-08-31"), CW))["id"]
    get_success_data(api.decide_recertification(
        rcertid, {"decision": "APPROVE"}, make_caseworker_headers("cw-approver-12d")))
    tenant = get_success_data(api.get_tenant(ctx["tid"], ADMIN))
    assert tenant["months_used"] == 18

"""Composite setup helpers for the ERAP co-application lifecycle.

Every test runs against a freshly launched, empty server (the harness restarts the
API and its database before each test). These helpers build the multi-step
co-application state that most claims require, driving only PRD-declared endpoints
through the ApiClient and the pre-built role headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .constants import DEFAULT_CLOCK_UTC, DEFAULT_INCOME_LIMIT_BY_SIZE
from .factories import (
    create_program_payload,
    create_tenant_payload,
    create_landlord_payload,
    submit_w9_payload,
    create_unit_payload,
    create_application_payload,
    income_source_payload,
    ledger_payload,
    disbursement_payload,
    recapture_case_payload,
)
from .test_users import (
    TEST_USERS,
    make_tenant_headers,
    make_landlord_headers,
    make_caseworker_headers,
)


_ADMIN = TEST_USERS["program_admin_headers"]


def set_clock(api, iso=DEFAULT_CLOCK_UTC):
    """Pin the server logical clock (ProgramAdmin only)."""
    return get_success_data(api.set_clock({"to_iso8601": iso}, _ADMIN))


def register_verified_landlord(api, *, tin="12-3456789", banking_last4="0001",
                               mailing_address="1 A St", verify=True):
    """Register a landlord and (optionally) submit + verify its W-9. Returns landlord id."""
    lid = get_success_data(api.create_landlord(create_landlord_payload()))["id"]
    llh = make_landlord_headers(lid)
    submitted = False
    if verify:
        get_success_data(api.submit_w9(
            lid, submit_w9_payload(tin=tin, banking_last4=banking_last4,
                                   mailing_address=mailing_address), llh))
        get_success_data(api.verify_w9(lid, {"decision": "VERIFIED"}, _ADMIN))
    return lid


def build_application(
    api,
    *,
    set_clock_first=True,
    clock=DEFAULT_CLOCK_UTC,
    # program
    funding_pool_total_cents=100_000_000,
    per_month_max_cents=250_000,
    income_limits=None,
    months_cap=18,
    eligibility_ami_pct=None,
    program_name="ERAP-Test",
    # tenant
    household_size=2,
    # landlord / w9
    submit_w9=True,
    verify_w9=True,
    # unit / application
    unit_rent_cents=200_000,
    app_rent_cents=200_000,
    requested_prospective_months=3,
    arrears_start_month="2025-12",
    arrears_end_month="2026-01",
    prospective_start_date="2026-03-01",
    prospective_end_date="2026-05-31",
    # tenant section
    income_sources=(("WAGES", 400_000),),
    do_tenant_section=True,
    hardship_type="JOB_LOSS",
    hardship_attested=True,
    # ledger / landlord section
    add_ledger=True,
    ledger_lines=(),
    verify_ledger=True,
    do_landlord_section=True,
    # progression
    submit=True,
    review=True,
    approve=False,
    approver_id="cw-approver",
):
    """Drive the co-application chain up to the requested stage.

    Every boolean gates one step, so the same builder produces a bare DRAFT
    application, a sections-complete-but-unsubmitted application, an UNDER_REVIEW
    application, or a fully APPROVED (award-pinned) application.

    Returns a context dict with keys: pid, tid, lid, uid, aid, ledger_id (or None),
    application (latest observed application data), version (latest application version).
    """
    if income_limits is None:
        income_limits = dict(DEFAULT_INCOME_LIMIT_BY_SIZE)

    if set_clock_first:
        set_clock(api, clock)

    prog_kwargs = dict(
        name=program_name,
        funding_pool_total_cents=funding_pool_total_cents,
        per_month_max_cents=per_month_max_cents,
        monthly_income_limit_by_size=income_limits,
        months_cap=months_cap,
    )
    if eligibility_ami_pct is not None:
        prog_kwargs["eligibility_ami_pct"] = eligibility_ami_pct
    pid = get_success_data(api.create_program(create_program_payload(**prog_kwargs), _ADMIN))["id"]

    tid = get_success_data(api.create_tenant(create_tenant_payload(household_size=household_size)))["id"]
    th = make_tenant_headers(tid)

    lid = get_success_data(api.create_landlord(create_landlord_payload()))["id"]
    lh = make_landlord_headers(lid)
    if submit_w9:
        get_success_data(api.submit_w9(lid, submit_w9_payload(), lh))
        if verify_w9:
            get_success_data(api.verify_w9(lid, {"decision": "VERIFIED"}, _ADMIN))

    uid = get_success_data(api.create_unit(
        create_unit_payload(lid, monthly_rent_cents=unit_rent_cents), lh))["id"]

    app_kwargs = dict(
        monthly_rent_cents=app_rent_cents,
        requested_prospective_months=requested_prospective_months,
        arrears_start_month=arrears_start_month,
        arrears_end_month=arrears_end_month,
        prospective_start_date=prospective_start_date,
        prospective_end_date=prospective_end_date,
    )
    application = get_success_data(api.create_application(
        create_application_payload(pid, tid, lid, uid, **app_kwargs), th))
    aid = application["id"]

    for src_type, amount in income_sources:
        get_success_data(api.add_income_source(
            aid, income_source_payload(src_type, amount), th))

    if do_tenant_section:
        application = get_success_data(api.complete_tenant_section(
            aid, {"hardship_type": hardship_type, "hardship_attested": hardship_attested}, th))

    ledger_id = None
    if add_ledger:
        ledger = get_success_data(api.create_ledger(aid, ledger_payload(ledger_lines), lh))
        ledger_id = ledger["id"]
        if verify_ledger:
            get_success_data(api.verify_ledger(aid, {"decision": "VERIFIED"}, _ADMIN))

    if do_landlord_section:
        application = get_success_data(api.complete_landlord_section(
            aid, {"ledger_confirmed": True}, lh))

    if submit:
        application = get_success_data(api.submit_application(aid, th))
    if review:
        application = get_success_data(api.review_application(aid, TEST_USERS["caseworker_headers"]))
    if approve:
        application = get_success_data(api.approve_application(
            aid, {"decision_reason": "ok"}, make_caseworker_headers(approver_id)))

    return {
        "pid": pid,
        "tid": tid,
        "lid": lid,
        "uid": uid,
        "aid": aid,
        "ledger_id": ledger_id,
        "application": application,
        "version": application.get("version"),
    }


# ---- Standard ledger lines used by several arrears / award instances ----
STANDARD_ARREARS_LINES = (
    {"month": "2025-11", "line_type": "CHARGE", "charge_cents": 200000},
    {"month": "2025-12", "line_type": "CHARGE", "charge_cents": 200000},
    {"month": "2025-12", "line_type": "PAYMENT", "payment_cents": 100000},
    {"month": "2026-01", "line_type": "CHARGE", "charge_cents": 200000},
)


def build_approved_application(api, *, approver_id="cw-approver", **overrides):
    """Approved application with the standard arrears ledger and an eligible income.

    Yields total_award_cents == 1000000 (arrears 400000 + prospective 600000),
    months_awarded == 5, when defaults are used.
    """
    kwargs = dict(
        ledger_lines=STANDARD_ARREARS_LINES,
        approve=True,
        approver_id=approver_id,
    )
    kwargs.update(overrides)
    return build_application(api, **kwargs)


def create_disbursement(api, aid, *, amount_cents, months_covered, coverage_kind,
                        version, issuer_id="cw-issuer"):
    """Create a disbursement and return the (lenient) success data dict."""
    return get_success_data(api.create_disbursement(
        aid,
        disbursement_payload(amount_cents, months_covered, coverage_kind, version),
        make_caseworker_headers(issuer_id),
    ))


def create_cleared_disbursement(api, aid, *, amount_cents, months_covered, coverage_kind,
                                version, issuer_id="cw-issuer", payment_reference="ACH-1"):
    """Create -> send -> clear a disbursement. Returns the disbursement id."""
    did = create_disbursement(api, aid, amount_cents=amount_cents, months_covered=months_covered,
                              coverage_kind=coverage_kind, version=version, issuer_id=issuer_id)["id"]
    get_success_data(api.send_disbursement(
        did, {"payment_reference": payment_reference}, make_caseworker_headers(issuer_id)))
    get_success_data(api.clear_disbursement(did, _ADMIN))
    return did


def open_substantiated_recapture(api, aid, did, *, reason="OTHER"):
    """Open a recapture case against a disbursement and substantiate it. Returns case id."""
    fraud = TEST_USERS["fraud_headers"]
    rcid = get_success_data(api.create_recapture_case(
        recapture_case_payload(aid, did, reason), fraud))["id"]
    get_success_data(api.substantiate_recapture(rcid, {}, fraud))
    return rcid

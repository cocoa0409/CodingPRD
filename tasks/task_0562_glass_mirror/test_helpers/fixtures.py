"""Composite setup helpers — encapsulate the multi-step preambles most tests need.

Every helper takes the ApiClient `api` as its first argument and builds all of its
preconditions from scratch using only PRD-declared endpoints (the harness restarts
the server before every test, so each starts against an empty database).

Setup calls use get_success_data() (lenient) so setup breakage surfaces as a clear
"Setup failed" error rather than a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data
from .factories import (
    create_contractor_account_payload,
    create_quote_payload,
    create_line_item_payload,
    create_furnace_payload,
    create_tempering_batch_payload,
    create_install_crew_payload,
    create_install_appointment_payload,
    create_claim_report_payload,
)
from .test_users import TEST_USERS, make_contractor_headers


# --------------------------------------------------------------------------
# Canonical line specs (kept here so tests reuse them by name)
# --------------------------------------------------------------------------
# SHOWER_ENCLOSURE TEMPERED 10mm 30x72 x1 -> billable 15.0, unit 31250, line_total 31250
LINE_SHOWER_TEMPERED = {
    "product_type": "SHOWER_ENCLOSURE", "glass_type": "TEMPERED", "thickness_mm": 10,
    "width_in": 30, "height_in": 72, "quantity": 1,
}
# SHOWER_ENCLOSURE ANNEALED 6mm 20x36 POLISHED x1 -> billable 5.0, unit 9750, line_total 9750
LINE_GOLD_ANNEALED = {
    "product_type": "SHOWER_ENCLOSURE", "glass_type": "ANNEALED", "thickness_mm": 6,
    "width_in": 20, "height_in": 36, "quantity": 1, "edge_work": "POLISHED",
}
# TABLETOP ANNEALED 12mm 40x20 x1
LINE_TABLETOP = {
    "product_type": "TABLETOP", "glass_type": "ANNEALED", "thickness_mm": 12,
    "width_in": 40, "height_in": 20, "quantity": 1,
}

# Default scheduling windows (server clock starts 2026-05-01)
BATCH_START = "2026-06-10T09:00:00Z"
BATCH_END = "2026-06-10T11:00:00Z"
APPT_START = "2026-06-12T09:00:00Z"
APPT_END = "2026-06-12T12:00:00Z"


# --------------------------------------------------------------------------
# Low-level single-step helpers
# --------------------------------------------------------------------------
def create_account(api, tier="GOLD", credit_limit_cents=100_000_000, company_name="Acme Glazing"):
    resp = api.create_contractor_account(
        create_contractor_account_payload(company_name=company_name, tier=tier,
                                          credit_limit_cents=credit_limit_cents),
        TEST_USERS["shop_admin_headers"],
    )
    return get_success_data(resp)


def get_account(api, account_id):
    return get_success_data(api.get_contractor_account(account_id, TEST_USERS["shop_admin_headers"]))


def set_account_status(api, account_id, status):
    return get_success_data(
        api.set_account_status(account_id, {"status": status}, TEST_USERS["shop_admin_headers"])
    )


def create_draft_quote(api, account_id):
    return get_success_data(
        api.create_quote(create_quote_payload(contractor_account_id=account_id),
                         TEST_USERS["estimator_headers"])
    )


def add_line(api, quote_id, **overrides):
    return get_success_data(
        api.add_line_item(quote_id, create_line_item_payload(**overrides),
                          TEST_USERS["estimator_headers"])
    )


def send_quote(api, quote_id):
    return get_success_data(api.send_quote(quote_id, TEST_USERS["estimator_headers"]))


def accept_quote(api, quote_id, account_id, expected_account_version):
    return get_success_data(
        api.accept_quote(quote_id, {"expected_account_version": expected_account_version},
                         make_contractor_headers(account_id))
    )


def create_furnace(api, max_batch_sqft=500, cooldown_minutes=60, name="F1"):
    return get_success_data(
        api.create_furnace(create_furnace_payload(name=name, max_batch_sqft=max_batch_sqft,
                                                  cooldown_minutes=cooldown_minutes),
                           TEST_USERS["shop_admin_headers"])
    )


def create_batch(api, job_id, furnace_id, start=BATCH_START, end=BATCH_END):
    return get_success_data(
        api.create_tempering_batch(create_tempering_batch_payload(job_id, furnace_id, start, end),
                                   TEST_USERS["fabricator_headers"])
    )


def complete_batch(api, batch_id):
    return get_success_data(api.complete_tempering_batch(batch_id, TEST_USERS["fabricator_headers"]))


def create_crew(api, certified_products=None, name="Crew1"):
    return get_success_data(
        api.create_install_crew(
            create_install_crew_payload(name=name,
                                        certified_products=certified_products or ["SHOWER_ENCLOSURE"]),
            TEST_USERS["shop_admin_headers"])
    )


def create_appointment(api, job_id, crew_id, start=APPT_START, end=APPT_END):
    return get_success_data(
        api.create_install_appointment(
            create_install_appointment_payload(job_id, crew_id, start, end),
            TEST_USERS["scheduler_headers"])
    )


def complete_appointment(api, appointment_id):
    return get_success_data(
        api.complete_install_appointment(appointment_id, TEST_USERS["scheduler_headers"])
    )


def file_claim(api, job_id, line_item_id, claim_type, billable_to_contractor=False,
               cause="test cause", as_contractor_account_id=None):
    if as_contractor_account_id is not None:
        headers = make_contractor_headers(as_contractor_account_id)
    else:
        headers = TEST_USERS["scheduler_headers"]
    payload = create_claim_report_payload(job_id, line_item_id, claim_type, cause=cause,
                                          billable_to_contractor=billable_to_contractor)
    return get_success_data(api.create_claim_report(payload, headers))


def review_claim(api, claim_id, decision):
    return get_success_data(
        api.review_claim_report(claim_id, {"decision": decision}, TEST_USERS["shop_admin_headers"])
    )


def set_clock(api, to_iso8601):
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, TEST_USERS["shop_admin_headers"]))


# --------------------------------------------------------------------------
# Tier 1-2: Accepted-job scenarios
# --------------------------------------------------------------------------
def setup_accepted_job(api, tier="GOLD", credit_limit_cents=100_000_000, lines=None):
    """Create account -> quote -> line(s) -> send -> accept. Returns a context dict:
        account (dict at creation, version 1), account_id, quote_id, job_id,
        line_ids (in creation order), accepted_quote (the accept response).
    """
    account = create_account(api, tier=tier, credit_limit_cents=credit_limit_cents)
    quote = create_draft_quote(api, account["id"])
    specs = lines if lines is not None else [dict(LINE_SHOWER_TEMPERED)]
    line_ids = []
    for spec in specs:
        li = add_line(api, quote["id"], **spec)
        line_ids.append(li["id"])
    send_quote(api, quote["id"])
    accepted = accept_quote(api, quote["id"], account["id"], account["version"])
    return {
        "account": account,
        "account_id": account["id"],
        "quote_id": quote["id"],
        "job_id": accepted["ordered_job_id"],
        "line_ids": line_ids,
        "accepted_quote": accepted,
    }


def setup_fabricated_job(api, furnace_max_batch_sqft=500, cooldown_minutes=60, **kwargs):
    """setup_accepted_job + furnace + one batch that fabricates all lines
    (fabrication_status COMPLETE, install_status READY). Adds furnace, batch_id."""
    ctx = setup_accepted_job(api, **kwargs)
    furnace = create_furnace(api, max_batch_sqft=furnace_max_batch_sqft, cooldown_minutes=cooldown_minutes)
    batch = create_batch(api, ctx["job_id"], furnace["id"])
    complete_batch(api, batch["id"])
    ctx["furnace"] = furnace
    ctx["furnace_id"] = furnace["id"]
    ctx["batch_id"] = batch["id"]
    return ctx


def setup_installed_job(api, certified_products=None, **kwargs):
    """setup_fabricated_job + crew + appointment completed (lines INSTALLED,
    install_status INSTALLED, job CLOSED). Adds crew, appointment_id."""
    ctx = setup_fabricated_job(api, **kwargs)
    crew = create_crew(api, certified_products=certified_products or ["SHOWER_ENCLOSURE"])
    appt = create_appointment(api, ctx["job_id"], crew["id"])
    complete_appointment(api, appt["id"])
    ctx["crew"] = crew
    ctx["crew_id"] = crew["id"]
    ctx["appointment_id"] = appt["id"]
    return ctx


# --------------------------------------------------------------------------
# GOLD two-line 16576 scenarios (shared by several credit/cascade instances)
# --------------------------------------------------------------------------
def setup_gold_two_line_accepted(api):
    """GOLD account, two identical ANNEALED 20x36 POLISHED shower lines
    (line_total 9750 each; subtotal 19500; total 16576). Accepted -> job with
    credit_hold_cents 16576. Returns context with line_ids [liA, liB]."""
    return setup_accepted_job(api, tier="GOLD",
                              lines=[dict(LINE_GOLD_ANNEALED), dict(LINE_GOLD_ANNEALED)])


def setup_gold_two_line_installed(api):
    """GOLD two-line job fabricated and installed (both lines INSTALLED)."""
    ctx = setup_gold_two_line_accepted(api)
    furnace = create_furnace(api, max_batch_sqft=500)
    batch = create_batch(api, ctx["job_id"], furnace["id"])
    complete_batch(api, batch["id"])
    crew = create_crew(api, certified_products=["SHOWER_ENCLOSURE"])
    appt = create_appointment(api, ctx["job_id"], crew["id"])
    complete_appointment(api, appt["id"])
    ctx["furnace"] = furnace
    ctx["furnace_id"] = furnace["id"]
    ctx["batch_id"] = batch["id"]
    ctx["crew_id"] = crew["id"]
    ctx["appointment_id"] = appt["id"]
    return ctx

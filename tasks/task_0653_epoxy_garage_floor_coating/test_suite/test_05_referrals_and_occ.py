"""Cross-entity dependencies and concurrency: the sales-accepted guard on
booking, referral conversion at build completion, the conserved-credit
invariant under convert-then-claw-back, optimistic-concurrency stale-version
rejection on accept, and the per-mutation version increment.
"""
from test_helpers import (
    api_client, TEST_USERS, get_success_data, validate_success, validate_error,
    make_customer_headers, make_crew_headers, set_clock,
    setup_sent_quote, create_system_with_color, create_customer, create_project,
    record_assessment, create_estimate_quote, send_quote, project_version,
    create_crew, book_install, setup_referral_pair,
)
from test_helpers.factories import complete_install_payload

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
SCHED = TEST_USERS["scheduler_headers"]
AGENT = TEST_USERS["warranty_agent_headers"]


def _build_referred_project_through(stage, referrer, referred):
    """Drive a referred FLAKE project up through a named stage and return
    (project_id, install_job_id). stage in {'completed','cured'}."""
    sys, color = create_system_with_color(family="FLAKE", sku="FLAKE_STANDARD")
    crew = create_crew("Crew Flake A", metallic_certified=False, max_sqft_per_day=1000)
    proj = create_project(referred["id"], referral_code=referrer["referral_code"])
    assess = record_assessment(
        proj["id"], measured_sqft=600, oil_stain_pct=50, crack_density=20,
        crack_linear_ft=15, spalling=True, moisture_pct=30,
    )
    quote = create_estimate_quote(proj["id"], assess["id"], sys["id"], color["id"])
    send_quote(quote["id"])
    pv = project_version(proj["id"])
    get_success_data(api_client.accept_quote(
        quote["id"], {"expected_project_version": pv}, make_customer_headers(referred["id"])
    ))
    job = book_install(proj["id"], crew["id"], install_date="2026-05-10T09:00:00Z")
    set_clock("2026-05-10T09:00:00Z")
    get_success_data(api_client.start_install_job(job["id"], make_crew_headers(crew["id"])))
    get_success_data(api_client.complete_install_job(
        job["id"], complete_install_payload(600, 15), make_crew_headers(crew["id"])
    ))
    if stage == "cured":
        set_clock("2026-05-13T17:00:00Z")
        get_success_data(api_client.mark_cured(job["id"], SCHED))
    return proj["id"], job["id"]


# ===========================================================================
# Difficulty/cross_entity_state_dependency/install_book_requires_project_sales_accepted
# ===========================================================================
def test_install_booking_requires_sales_accepted():
    """PRD §3.6: "The project's sales track must already be at `ACCEPTED`, or the
    booking is refused with `ERR_SALES_NOT_ACCEPTED`."

    Design: Difficulty/cross_entity_state_dependency/install_book_requires_project_sales_accepted
    """
    h = setup_sent_quote(family="FLAKE", sku="FLAKE_STANDARD")  # QUOTED, not ACCEPTED
    crew = create_crew("Crew Flake A", metallic_certified=False, max_sqft_per_day=1000)
    resp = api_client.create_install_job(
        h["project"]["id"], {"crew_id": crew["id"], "install_date": "2026-05-10T09:00:00Z"},
        SCHED,
    )
    validate_error(resp, "ERR_SALES_NOT_ACCEPTED")


def test_quoted_project_build_status_unchanged_by_failed_booking():
    """PRD §2.10: "The build track does not begin advancing until the sales track
    has reached `ACCEPTED`; before that point, any attempt to schedule is refused."

    Design: Difficulty/cross_entity_state_dependency/install_book_requires_project_sales_accepted
    """
    h = setup_sent_quote(family="FLAKE", sku="FLAKE_STANDARD")
    crew = create_crew("Crew Flake A", metallic_certified=False, max_sqft_per_day=1000)
    api_client.create_install_job(
        h["project"]["id"], {"crew_id": crew["id"], "install_date": "2026-05-10T09:00:00Z"},
        SCHED,
    )
    proj = validate_success(api_client.get_project(h["project"]["id"], SALES))
    assert proj["build_status"] == "PRE_BUILD", (
        f"refused booking must leave build PRE_BUILD, got {proj['build_status']}"
    )


# ===========================================================================
# Difficulty/cross_entity_state_dependency/referral_conversion_requires_referred_project_complete
# ===========================================================================
def test_referral_not_converted_while_only_curing():
    """PRD §3.5: "If the project carries a referral that is still `PENDING`, it
    remains `PENDING` at this point - a referral converts only when the install
    completes, not when the quote is accepted."

    Design: Difficulty/cross_entity_state_dependency/referral_conversion_requires_referred_project_complete
    """
    set_clock("2026-05-01T00:00:00Z")
    referrer, referred = setup_referral_pair()
    _build_referred_project_through("completed", referrer, referred)  # build at CURING
    bal = validate_success(api_client.get_customer(referrer["id"], SALES))
    assert bal["account_credit_balance_cents"] == 0, (
        f"balance must stay 0 while project only CURING, got {bal['account_credit_balance_cents']}"
    )


def test_referral_converts_on_mark_cured_complete():
    """PRD §3.8: "When a referred project's build track reaches `COMPLETE` (at
    mark-cured), a referral still in `PENDING` transitions to `CONVERTED`, and the
    referrer customer's `account_credit_balance_cents` rises by the credit amount
    of fifteen thousand cents."

    Design: Difficulty/cross_entity_state_dependency/referral_conversion_requires_referred_project_complete
    """
    set_clock("2026-05-01T00:00:00Z")
    referrer, referred = setup_referral_pair()
    _build_referred_project_through("cured", referrer, referred)  # build COMPLETE
    bal = validate_success(api_client.get_customer(referrer["id"], SALES))
    assert bal["account_credit_balance_cents"] == 15000, (
        f"mark-cured must convert referral and add 15000, got {bal['account_credit_balance_cents']}"
    )


# ===========================================================================
# Difficulty/compensating_invariant/referral_credit_conserved_on_convert_then_clawback
# ===========================================================================
def test_referral_credit_added_on_conversion():
    """PRD §3.2: "At any time the balance equals the referral credit amount of
    fifteen thousand cents multiplied by the number of referrals naming this
    customer as referrer that currently sit in the converted state".

    Design: Difficulty/compensating_invariant/referral_credit_conserved_on_convert_then_clawback
    """
    set_clock("2026-05-01T00:00:00Z")
    referrer, referred = setup_referral_pair()
    _build_referred_project_through("cured", referrer, referred)
    bal = validate_success(api_client.get_customer(referrer["id"], SALES))
    assert bal["account_credit_balance_cents"] == 15000, (
        f"CONVERTED adds one 15000 credit, got {bal['account_credit_balance_cents']}"
    )


# ===========================================================================
# Corner/cross_cutting_complexity_layers/occ_stale_project_version_on_accept_rejected
# ===========================================================================
def test_accept_with_stale_version_rejected_then_current_succeeds():
    """PRD §2.9: "When a homeowner accepts a sent quote, `expected_project_version`
    must equal the project's current `version`; if a newer quote was sent on the
    same project after the client's last read ... the acceptance is rejected with
    `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_project_version_on_accept_rejected
    """
    sys, color = create_system_with_color(family="FLAKE", sku="FLAKE_STANDARD")
    cust = create_customer("Cora Customer", email="cora-occ@example.com")
    proj = create_project(cust["id"])
    assess = record_assessment(proj["id"])
    q1 = create_estimate_quote(proj["id"], assess["id"], sys["id"], color["id"])
    send_quote(q1["id"])
    pv_stale = project_version(proj["id"])
    # A second quote sent bumps the project version, making pv_stale stale.
    q2 = create_estimate_quote(proj["id"], assess["id"], sys["id"], color["id"])
    send_quote(q2["id"])
    pv_current = project_version(proj["id"])
    cust_headers = make_customer_headers(cust["id"])
    stale_resp = api_client.accept_quote(
        q1["id"], {"expected_project_version": pv_stale}, cust_headers
    )
    validate_error(stale_resp, "ERR_STALE_PROJECT_VERSION")
    ok = validate_success(api_client.accept_quote(
        q1["id"], {"expected_project_version": pv_current}, cust_headers
    ))
    assert ok["status"] == "ACCEPTED", f"accept with current version should succeed, got {ok['status']}"


# ===========================================================================
# Corner/cross_cutting_complexity_layers/project_version_increments_on_every_mutation
# ===========================================================================
def test_project_version_increments_per_mutation():
    """PRD §2.4: "it is bumped on assessment recording, on every quote send, on
    quote acceptance, on decline, on install booking, on install completion, on
    the curing milestone, and on cancellation."

    Design: Corner/cross_cutting_complexity_layers/project_version_increments_on_every_mutation
    """
    sys, color = create_system_with_color(family="FLAKE", sku="FLAKE_STANDARD")
    cust = create_customer("Cora Customer", email="cora-ver@example.com")
    proj = create_project(cust["id"])
    assert proj["version"] == 1, f"create -> version 1, got {proj['version']}"
    assess = record_assessment(proj["id"])
    v_assessed = project_version(proj["id"])
    assert v_assessed == 2, f"assessment -> version 2, got {v_assessed}"
    q = create_estimate_quote(proj["id"], assess["id"], sys["id"], color["id"])
    send_quote(q["id"])
    v_sent = project_version(proj["id"])
    assert v_sent == 3, f"first send -> version 3 (quote create does not bump), got {v_sent}"

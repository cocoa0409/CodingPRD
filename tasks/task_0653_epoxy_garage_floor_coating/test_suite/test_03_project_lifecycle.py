"""Project lifecycle: the two parallel status dimensions, the install-complete
cascade (FINAL quote + supersede + repoint), the cancel cascade (warranty void,
claim force-close, referral claw-back), and assorted state-transition guards.
"""
from test_helpers import (
    api_client, TEST_USERS, get_success_data, validate_success, validate_error,
    make_customer_headers, make_crew_headers, set_clock,
    setup_accepted_project, setup_started_install, setup_booked_install,
    setup_completed_install, setup_cured_project, setup_submitted_claim,
    setup_sent_quote, create_system_with_color, create_customer, create_project,
    record_assessment, create_estimate_quote, send_quote, project_version,
    create_crew, book_install, setup_referral_pair,
)
from test_helpers.factories import complete_install_payload

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
SCHED = TEST_USERS["scheduler_headers"]
AGENT = TEST_USERS["warranty_agent_headers"]


# ===========================================================================
# Difficulty/non_linear_state_machine/project_parallel_sales_and_build_dimensions
# ===========================================================================
def test_booking_advances_build_dimension_only():
    """PRD §2.10: "The build track does not begin advancing until the sales track
    has reached `ACCEPTED`".
    PRD §3.6: "This is the move that advances the build track from `PRE_BUILD` to
    `SCHEDULED`".

    Design: Difficulty/non_linear_state_machine/project_parallel_sales_and_build_dimensions
    """
    h = setup_accepted_project(family="FLAKE", sku="FLAKE_STANDARD")
    crew = create_crew("Crew Flake A", metallic_certified=False, max_sqft_per_day=1000)
    book_install(h["project"]["id"], crew["id"], install_date="2026-05-10T09:00:00Z")
    proj = validate_success(api_client.get_project(h["project"]["id"], SALES))
    assert proj["sales_status"] == "ACCEPTED", f"sales unchanged, got {proj['sales_status']}"
    assert proj["build_status"] == "SCHEDULED", f"build advanced, got {proj['build_status']}"


def test_accepted_project_keeps_pre_build_until_scheduled():
    """PRD §2.10: "The `sales_status` dimension tracks the commercial pipeline
    through the values `LEAD`, `ASSESSED`, `QUOTED`, `ACCEPTED`, and `DECLINED`.
    The `build_status` dimension tracks fulfilment through the values `PRE_BUILD`,
    `SCHEDULED`, `INSTALLED`, `CURING`, `COMPLETE`, and `CANCELLED`."

    Design: Difficulty/non_linear_state_machine/project_parallel_sales_and_build_dimensions
    """
    h = setup_accepted_project(family="FLAKE", sku="FLAKE_STANDARD")
    proj = validate_success(api_client.get_project(h["project"]["id"], SALES))
    assert proj["sales_status"] == "ACCEPTED", f"got {proj['sales_status']}"
    assert proj["build_status"] == "PRE_BUILD", (
        f"build stays PRE_BUILD until booking, got {proj['build_status']}"
    )


# ===========================================================================
# Difficulty/transitive_cascade/complete_cascades_finalquote_supersede_repoint_depth2
# ===========================================================================
def test_complete_supersedes_estimate_quote():
    """PRD §3.6: "The previously accepted estimate quote is moved to `SUPERSEDED`,
    and the project's `accepted_quote_id` is repointed to the new final quote."

    Design: Difficulty/transitive_cascade/complete_cascades_finalquote_supersede_repoint_depth2
    """
    h = setup_completed_install(
        family="FLAKE", sku="FLAKE_STANDARD",
        as_measured_sqft=650, as_measured_crack_ft=18,
    )
    est = validate_success(api_client.get_quote(h["quote"]["id"], SALES))
    assert est["status"] == "SUPERSEDED", (
        f"prior ACCEPTED estimate must be SUPERSEDED by FINAL, got {est['status']}"
    )


def test_complete_repoints_accepted_quote_to_final():
    """PRD §3.6: "the project's `accepted_quote_id` is repointed to the new final
    quote."

    Design: Difficulty/transitive_cascade/complete_cascades_finalquote_supersede_repoint_depth2
    """
    h = setup_completed_install(
        family="FLAKE", sku="FLAKE_STANDARD",
        as_measured_sqft=650, as_measured_crack_ft=18,
    )
    proj = validate_success(api_client.get_project(h["project"]["id"], SALES))
    assert proj["accepted_quote_id"] == h["final_quote"]["id"], (
        f"accepted_quote_id must point at FINAL quote {h['final_quote']['id']}, "
        f"got {proj['accepted_quote_id']}"
    )


# ===========================================================================
# Corner/state_machines/accept_already_accepted_quote_returns_invalid_state
# ===========================================================================
def test_accept_already_accepted_quote_invalid_state():
    """PRD §3.5: "Acceptance requires that the project's sales track be at
    `QUOTED`".
    PRD §3.7: "A requested transition attempted from a status that does not define
    it ... is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/accept_already_accepted_quote_returns_invalid_state
    """
    h = setup_accepted_project(family="FLAKE", sku="FLAKE_STANDARD")
    pv = project_version(h["project"]["id"])
    resp = api_client.accept_quote(
        h["quote"]["id"], {"expected_project_version": pv},
        make_customer_headers(h["customer"]["id"]),
    )
    validate_error(resp, "ERR_INVALID_STATE")


# ===========================================================================
# Corner/state_machines/start_install_before_install_date_rejected
# ===========================================================================
def test_start_before_install_date_rejected():
    """PRD §3.6: "A start is allowed only when the logical clock has reached or
    passed the job's `install_date`; an attempt before that instant is rejected
    with `ERR_INSTALL_DATE_NOT_REACHED`."

    Design: Corner/state_machines/start_install_before_install_date_rejected
    """
    h = setup_booked_install(
        family="FLAKE", sku="FLAKE_STANDARD", crew_capacity=1000,
        install_date="2026-05-10T09:00:00Z",
    )
    set_clock("2026-05-09T00:00:00Z")  # before install_date
    resp = api_client.start_install_job(
        h["install_job"]["id"], make_crew_headers(h["crew"]["id"])
    )
    validate_error(resp, "ERR_INSTALL_DATE_NOT_REACHED")


# ===========================================================================
# Corner/state_machines/decline_after_scheduled_rejected
# ===========================================================================
def test_decline_after_scheduled_rejected():
    """PRD §3.5: "once a project has been scheduled, it can no longer be declined,
    and a late decline is rejected with `ERR_DECLINE_AFTER_SCHEDULED`."

    Design: Corner/state_machines/decline_after_scheduled_rejected
    """
    h = setup_booked_install(
        family="FLAKE", sku="FLAKE_STANDARD", crew_capacity=1000,
        install_date="2026-05-10T09:00:00Z",
    )
    resp = api_client.decline_project(
        h["project"]["id"], make_customer_headers(h["customer"]["id"])
    )
    validate_error(resp, "ERR_DECLINE_AFTER_SCHEDULED")


# ===========================================================================
# Corner/state_machines/cancel_completed_project_not_cancellable
# ===========================================================================
def test_cancel_completed_project_not_cancellable():
    """PRD §3.8: "an attempt to cancel a project whose build track is already
    terminal at `COMPLETE` or `CANCELLED` is rejected with
    `ERR_PROJECT_NOT_CANCELLABLE`."

    Design: Corner/state_machines/cancel_completed_project_not_cancellable
    """
    h = setup_cured_project(
        family="FLAKE", sku="FLAKE_STANDARD",
        install_date="2026-05-10T09:00:00Z", cure_instant="2026-05-13T17:00:00Z",
    )
    proj = validate_success(api_client.get_project(h["project"]["id"], ADMIN))
    assert proj["build_status"] == "COMPLETE"
    resp = api_client.cancel_project(
        h["project"]["id"], {"expected_project_version": proj["version"]}, ADMIN
    )
    validate_error(resp, "ERR_PROJECT_NOT_CANCELLABLE")

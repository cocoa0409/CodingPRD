"""State-machine transitions: initial states, invalid transitions, terminal lockdown,
SEP fork, enrollment lifecycle (queue B)."""
from test_helpers import (
    validate_success,
    validate_error,
    create_household,
    create_application,
    create_household_with_primary,
    create_sep_request,
    setup_paid_enrollment,
    setup_active_enrollment,
    make_applicant_headers,
    set_clock,
    TEST_USERS,
)


def test_application_initial_state_is_draft(api):
    """PRD §3.2: "It is created in `DRAFT` status against a `household_id`, and it declares its `enrollment_window`: `OEP` for Open Enrollment or `SEP` for a Special Enrollment Period."
    PRD §3.2: "While `DRAFT`, the application's `submitted_at` is null and its `sep_request_id` is null."

    Design: Corner/state_machines/application_initial_state_is_draft
    """
    hh = create_household("c-9")
    res = api.create_application({"household_id": hh["id"], "enrollment_window": "OEP"},
                                make_applicant_headers("c-9"))
    app = validate_success(res, 201)
    assert app["status"] == "DRAFT"
    assert app["submitted_at"] is None


def test_determine_from_draft_returns_invalid_state(api):
    """PRD §3.3: "Once an application is `SUBMITTED`, a `MarketplaceAdmin` runs the eligibility determination, which advances the application from `SUBMITTED` to `DETERMINED` and creates an **EligibilityDetermination** linked to the `application_id` (one active determination per application)."
    PRD §3.8: "For a state-transition action, the system then confirms the target is in a state from which the transition is defined (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/determine_from_draft_returns_invalid_state
    """
    hh, _ = create_household_with_primary("c-10", income_cents=3_000_000)
    app = create_application(hh["id"], "c-10", enrollment_window="OEP")
    res = api.determine_application(app["id"], TEST_USERS["admin_headers"])
    validate_error(res, "ERR_INVALID_STATE")
    assert res.status_code == 409


def test_cancel_from_cancelled_terminal_lockdown(api):
    """PRD §3.2: "cancellation moves an application that is currently in `DRAFT` or in `SUBMITTED` to the terminal `CANCELLED` state and increments the application's `version`."
    PRD §3.8: "For a state-transition action, the system then confirms the target is in a state from which the transition is defined (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/cancel_from_cancelled_terminal_lockdown
    """
    hh = create_household("c-11")
    app = create_application(hh["id"], "c-11", enrollment_window="OEP")
    h = make_applicant_headers("c-11")
    validate_success(api.cancel_application(app["id"], h), 200)
    res = api.cancel_application(app["id"], h)
    validate_error(res, "ERR_INVALID_STATE")
    assert res.status_code == 409


def test_sep_deny_branch_sets_denied(api):
    """PRD §3.2: "Denial moves a `PENDING` request to `DENIED`; a denied request grants no window, so the linked SEP application can never submit."

    Design: Corner/state_machines/sep_deny_branch_sets_denied
    """
    set_clock("2026-06-18T00:00:00Z")
    hh = create_household("c-12")
    app = create_application(hh["id"], "c-12", enrollment_window="SEP")
    sep = create_sep_request(app["id"], "c-12", qualifying_event_type="BIRTH",
                             event_date="2026-06-16")
    denied = validate_success(api.deny_sep_request(sep["id"], TEST_USERS["admin_headers"]), 200)
    assert denied["status"] == "DENIED"


def test_sep_approve_requires_application_draft(api):
    """PRD §3.2: "Approval moves the request from `PENDING` to `APPROVED` and is permitted only when the request is still `PENDING`, when the linked application is still in `DRAFT` (the SEP must be resolved before the application is submitted), and when the current clock date falls on or before the request's `window_close_date` — that is, the filing window is still open."
    PRD §3.8: "For a state-transition action, the system then confirms the target is in a state from which the transition is defined (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/sep_approve_requires_application_draft
    """
    set_clock("2026-06-18T00:00:00Z")
    hh = create_household("c-13")
    app = create_application(hh["id"], "c-13", enrollment_window="SEP")
    sep = create_sep_request(app["id"], "c-13", qualifying_event_type="BIRTH",
                             event_date="2026-06-16")
    h = make_applicant_headers("c-13")
    validate_success(api.cancel_application(app["id"], h), 200)  # application now CANCELLED
    res = api.approve_sep_request(sep["id"], TEST_USERS["admin_headers"])
    validate_error(res, "ERR_INVALID_STATE")
    assert res.status_code == 409


def test_terminate_enrollment_from_active(api):
    """PRD §3.6: "An applicant may terminate coverage: a `PENDING_EFFECTUATION` enrollment or an `ACTIVE` enrollment may be moved to the terminal `TERMINATED` state."

    Design: Corner/state_machines/terminate_enrollment_from_active
    """
    ctx = setup_active_enrollment("c-14", income_cents=3_000_000,
                                  elected_aptc_monthly_cents=45_000, benchmark_gross=50_000)
    h = make_applicant_headers("c-14")
    terminated = validate_success(api.terminate_enrollment(ctx["enrollment"]["id"], h), 200)
    assert terminated["lifecycle_status"] == "TERMINATED"


def test_effectuate_succeeds_after_binder_paid(api):
    """PRD §3.6: "A `MarketplaceAdmin` effectuates coverage, moving `lifecycle_status` from `PENDING_EFFECTUATION` to `ACTIVE`; effectuation is permitted only when `lifecycle_status` is `PENDING_EFFECTUATION` and is gated on the payment dimension — the binder must already be paid, so `payment_status` must be `PAID` at that moment."

    Design: Corner/state_machines/effectuate_succeeds_after_binder_paid
    """
    ctx = setup_paid_enrollment("c-15", income_cents=3_000_000,
                                elected_aptc_monthly_cents=45_000, benchmark_gross=50_000)
    active = validate_success(api.effectuate(ctx["enrollment"]["id"], TEST_USERS["admin_headers"]), 200)
    assert active["lifecycle_status"] == "ACTIVE"
    assert active["payment_status"] == "PAID"

"""Composite setup helpers (multi-step fixtures).

Every test starts against an empty DB (the runner restarts the server before
each test), so fixtures build their full preconditions from scratch using
only PRD-declared endpoints.

Identity threading: after creating an Organization, every ownership-gated
call in the same fixture uses make_applicant_headers(org["id"]) — never the
shared TEST_USERS["applicant_headers"] constant (PRD §2.1 entity-backed
role rule).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START_ISO
from .factories import (
    create_application_payload,
    create_organization_payload,
    create_recording_grant_payload,
    create_rental_payload,
    create_restriction_payload,
    create_title_payload,
)
from .test_users import TEST_USERS, make_applicant_headers

ADMIN = TEST_USERS["rights_admin_headers"]
OFFICER = TEST_USERS["licensing_officer_headers"]
CLERK = TEST_USERS["materials_clerk_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 1: catalog + organization building blocks
# ---------------------------------------------------------------------------


def reset_clock(to_iso8601: str = CLOCK_START_ISO):
    """Pin the logical clock (PRD §2.5)."""
    get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_title(**overrides):
    """Create a Title; returns the Title dict (status ACTIVE, version 1)."""
    return get_success_data(api_client.create_title(create_title_payload(**overrides), ADMIN))


def create_org(**overrides):
    """Register an Organization; returns the Organization dict (standing GOOD)."""
    return get_success_data(
        api_client.create_organization(create_organization_payload(**overrides), ADMIN)
    )


def create_title_and_org(title_overrides=None, org_overrides=None):
    """Title + Organization. Returns (title, org, applicant_headers)."""
    title = create_title(**(title_overrides or {}))
    org = create_org(**(org_overrides or {}))
    return title, org, make_applicant_headers(org["id"])


# ---------------------------------------------------------------------------
# Tier 1.5: application lifecycle steps
# ---------------------------------------------------------------------------


def create_application(title_id, org_id, applicant_headers, **overrides):
    """Create a DRAFT LicenseApplication. Returns the application dict."""
    return get_success_data(
        api_client.create_application(
            create_application_payload(title_id, org_id, **overrides),
            applicant_headers,
        )
    )


def submit_application(app_id, applicant_headers):
    return get_success_data(api_client.submit_application(app_id, applicant_headers))


def begin_review(app_id):
    return get_success_data(api_client.begin_review_application(app_id, OFFICER))


def current_application_version(app_id):
    return get_success_data(api_client.get_application(app_id, OFFICER))["version"]


def approve_application(app_id, expected_version=None):
    """Approve an UNDER_REVIEW application. Returns the LicenseAgreement."""
    if expected_version is None:
        expected_version = current_application_version(app_id)
    return get_success_data(
        api_client.approve_application(
            app_id, {"expected_application_version": expected_version}, OFFICER
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: approved application -> LicenseAgreement (PENDING_PAYMENT)
# ---------------------------------------------------------------------------


def setup_pending_agreement(
    title_overrides=None,
    org_overrides=None,
    app_overrides=None,
    start_clock=CLOCK_START_ISO,
):
    """Title + Org + application walked DRAFT -> SUBMITTED -> UNDER_REVIEW ->
    APPROVED. Returns dict with title, org, applicant headers, app, agreement.
    """
    reset_clock(start_clock)
    title, org, applicant = create_title_and_org(title_overrides, org_overrides)
    app = create_application(title["id"], org["id"], applicant, **(app_overrides or {}))
    submit_application(app["id"], applicant)
    begin_review(app["id"])
    agreement = approve_application(app["id"])
    return {
        "title": title,
        "org": org,
        "applicant": applicant,
        "application": app,
        "agreement": agreement,
    }


# ---------------------------------------------------------------------------
# Tier 3: ACTIVE agreement
# ---------------------------------------------------------------------------


def fund_agreement_for_activation(agreement_id):
    """Pay just enough to satisfy the PRD §3.4 activation gate: after the
    payment, royalty_balance_cents <= ceil(quoted_royalty_total_cents / 2)
    (the partial-payment activation rule). Returns the amount paid."""
    g = get_success_data(api_client.get_agreement(agreement_id, ADMIN))
    quoted = g["quoted_royalty_total_cents"]
    half_ceiling = -(-quoted // 2)  # ceil(quoted / 2)
    pay = quoted - half_ceiling  # floor(quoted / 2)
    if pay > 0:
        get_success_data(
            api_client.create_payment(agreement_id, {"amount_cents": pay}, FINANCE)
        )
    return pay


def setup_active_agreement(
    title_overrides=None,
    org_overrides=None,
    app_overrides=None,
    start_clock=CLOCK_START_ISO,
):
    """Full path through activation (PENDING_PAYMENT -> ACTIVE). Funds the
    agreement first via the PRD §3.4 partial-payment activation rule
    (pays floor(quoted/2), leaving balance == ceil(quoted/2))."""
    ctx = setup_pending_agreement(
        title_overrides=title_overrides,
        org_overrides=org_overrides,
        app_overrides=app_overrides,
        start_clock=start_clock,
    )
    ctx["activation_payment_cents"] = fund_agreement_for_activation(
        ctx["agreement"]["id"]
    )
    agreement = get_success_data(
        api_client.activate_agreement(ctx["agreement"]["id"], ADMIN)
    )
    ctx["agreement"] = agreement
    return ctx


# ---------------------------------------------------------------------------
# Tier 3.5: ACTIVE agreement + SCHEDULED performance
# ---------------------------------------------------------------------------


def setup_active_agreement_with_performance(
    performance_at=None,
    title_overrides=None,
    org_overrides=None,
    app_overrides=None,
    start_clock=CLOCK_START_ISO,
):
    """ACTIVE agreement plus one SCHEDULED performance."""
    ctx = setup_active_agreement(
        title_overrides=title_overrides,
        org_overrides=org_overrides,
        app_overrides=app_overrides,
        start_clock=start_clock,
    )
    perf_at = performance_at or (ctx["application"]["first_performance_date"])
    performance = get_success_data(
        api_client.create_performance(
            ctx["agreement"]["id"], {"performance_at": perf_at}, ctx["applicant"]
        )
    )
    ctx["performance"] = performance
    return ctx


# ---------------------------------------------------------------------------
# Tier 3.6: ACTIVE agreement + recording grant
# ---------------------------------------------------------------------------


def setup_active_agreement_with_grant(
    grant_overrides=None,
    approve_grant=True,
    title_overrides=None,
    org_overrides=None,
    app_overrides=None,
    start_clock=CLOCK_START_ISO,
):
    """ACTIVE agreement plus a RecordingGrant (APPROVED by default)."""
    ctx = setup_active_agreement(
        title_overrides=title_overrides,
        org_overrides=org_overrides,
        app_overrides=app_overrides,
        start_clock=start_clock,
    )
    grant = get_success_data(
        api_client.create_recording_grant(
            create_recording_grant_payload(
                ctx["agreement"]["id"], **(grant_overrides or {})
            ),
            ctx["applicant"],
        )
    )
    if approve_grant:
        grant = get_success_data(api_client.approve_recording_grant(grant["id"], ADMIN))
    ctx["grant"] = grant
    # re-read agreement: approve_recording_grant debits royalty_balance_cents
    ctx["agreement"] = get_success_data(
        api_client.get_agreement(ctx["agreement"]["id"], ADMIN)
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: rentals
# ---------------------------------------------------------------------------


def create_rental_for(agreement_id, **overrides):
    """Create a MaterialRental (status RESERVED, deposit HELD)."""
    return get_success_data(
        api_client.create_rental(create_rental_payload(agreement_id, **overrides), CLERK)
    )


def ship_rental(rental_id):
    return get_success_data(api_client.ship_rental(rental_id, CLERK))


def setup_rental_in_state(
    target_state,
    rental_overrides=None,
    clock_before_return=None,
    title_overrides=None,
    org_overrides=None,
    app_overrides=None,
    start_clock=CLOCK_START_ISO,
):
    """ACTIVE agreement + rental walked to target_state.

    Supported target_state: RESERVED, SHIPPED, RECEIVED, RETURN_IN_TRANSIT,
    RETURNED, OVERDUE (requires clock_before_return set past due_date so the
    sweep fires).
    Returns ctx dict with title/org/applicant/application/agreement/rental.
    """
    ctx = setup_active_agreement(
        title_overrides=title_overrides,
        org_overrides=org_overrides,
        app_overrides=app_overrides,
        start_clock=start_clock,
    )
    rental = create_rental_for(ctx["agreement"]["id"], **(rental_overrides or {}))
    ctx["rental"] = rental
    if target_state == "RESERVED":
        return ctx
    rental = ship_rental(rental["id"])
    ctx["rental"] = rental
    if target_state == "SHIPPED":
        return ctx
    rental = get_success_data(
        api_client.mark_received_rental(rental["id"], ctx["applicant"])
    )
    ctx["rental"] = rental
    if target_state == "RECEIVED":
        return ctx
    if clock_before_return is not None:
        # advance clock (fires the OVERDUE sweep for past-due rentals)
        reset_clock(clock_before_return)
        ctx["rental"] = get_success_data(api_client.get_rental(rental["id"], CLERK))
    if target_state == "OVERDUE":
        assert ctx["rental"]["status"] == "OVERDUE", (
            f"expected OVERDUE after sweep, got {ctx['rental']['status']}"
        )
        return ctx
    rental = get_success_data(
        api_client.ship_return_rental(rental["id"], ctx["applicant"])
    )
    ctx["rental"] = rental
    if target_state == "RETURN_IN_TRANSIT":
        return ctx
    if target_state == "RETURNED":
        rental = get_success_data(
            api_client.receive_return_rental(rental["id"], {}, CLERK)
        )
        ctx["rental"] = rental
        return ctx
    raise ValueError(f"unsupported target_state {target_state}")


# ---------------------------------------------------------------------------
# Tier 4.5: overdue rental carrying an ASSESSED OVERDUE_MATERIAL fine
# ---------------------------------------------------------------------------


def setup_assessed_overdue_fine(
    due_date="2026-05-20T00:00:00Z",
    return_clock="2026-05-25T00:00:00Z",
    title_overrides=None,
    app_overrides=None,
):
    """Rental returned late -> OVERDUE_MATERIAL Fine ASSESSED on the org.

    Returns ctx with title/org/applicant/agreement/rental/fine.
    """
    app_defaults = {
        "performance_count": 1,
        "first_performance_date": "2026-05-15T19:00:00Z",
        "last_performance_date": "2026-05-15T19:00:00Z",
    }
    app_defaults.update(app_overrides or {})
    ctx = setup_active_agreement(
        title_overrides=title_overrides, app_overrides=app_defaults
    )
    rental = create_rental_for(ctx["agreement"]["id"], due_date=due_date)
    ship_rental(rental["id"])
    get_success_data(api_client.mark_received_rental(rental["id"], ctx["applicant"]))
    # Ship the return while still RECEIVED (ship_return is only valid from
    # RECEIVED per PRD §3.6), then advance the clock past due_date so the
    # sweep flips RETURN_IN_TRANSIT -> OVERDUE with the PROJECTED fee.
    rental = get_success_data(
        api_client.ship_return_rental(rental["id"], ctx["applicant"])
    )
    reset_clock(return_clock)
    rental = get_success_data(
        api_client.receive_return_rental(rental["id"], {}, CLERK)
    )
    ctx["rental"] = rental
    assert rental["accrued_late_fee_cents"] > 0, (
        "expected a late fee to accrue for the overdue fine fixture"
    )
    fines, _meta = _list_fines(
        FINANCE,
        params={"organization_id": ctx["org"]["id"], "status": "ASSESSED"},
    )
    assert len(fines) == 1, "expected exactly one ASSESSED fine for the org"
    ctx["fine"] = fines[0]
    return ctx


def _list_fines(headers, params=None):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(api_client.list_fines(headers, params=params))


# ---------------------------------------------------------------------------
# Tier 5: breach / cancellation terminal states
# ---------------------------------------------------------------------------


def setup_breached_agreement(breach_reason="UNAUTHORIZED_ALTERATION", **kwargs):
    """ACTIVE agreement -> BREACHED via declare_breach. Returns ctx with
    title/org/applicant/agreement/breach fine list."""
    ctx = setup_active_agreement(**kwargs)
    agreement = get_success_data(
        api_client.declare_breach(
            ctx["agreement"]["id"], {"breach_reason": breach_reason}, ADMIN
        )
    )
    ctx["agreement"] = agreement
    ctx["org"] = get_success_data(api_client.get_organization(ctx["org"]["id"], ADMIN))
    return ctx


def setup_cancelled_agreement(cancel_reason="Producer withdrew", **kwargs):
    """ACTIVE agreement -> CANCELLED via cancel. Returns ctx."""
    ctx = setup_active_agreement(**kwargs)
    agreement = get_success_data(
        api_client.cancel_agreement(ctx["agreement"]["id"], {"reason": cancel_reason}, ADMIN)
    )
    ctx["agreement"] = agreement
    return ctx

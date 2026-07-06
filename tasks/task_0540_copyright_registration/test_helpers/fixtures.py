"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness resets the server before every test). Setup calls use the
lenient get_success_data() validator so a broken precondition surfaces as a clear
"Setup failed" rather than an obscure assertion error.

Every RightsHolder action inside a fixture is performed as the single stable
identity rh-user-1 (TEST_USERS["rightsholder_headers"]), so ownership checks on
owner-scoped application actions always pass.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as f

RH = TEST_USERS["rightsholder_headers"]
EX = TEST_USERS["examiner_headers"]
CX = TEST_USERS["complainant_headers"]
ADMIN = TEST_USERS["admin_headers"]


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(iso: str):
    return get_success_data(api_client.set_clock(iso, ADMIN))


# --------------------------------------------------------------------------
# Primitive creators
# --------------------------------------------------------------------------
def create_work(**overrides) -> dict:
    return get_success_data(api_client.create_work(f.create_work_payload(**overrides), RH))


def create_application(work_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_application(f.create_application_payload(work_id, **overrides), RH)
    )


def get_work(work_id) -> dict:
    return get_success_data(api_client.get_work(work_id, RH))


def get_application(app_id) -> dict:
    return get_success_data(api_client.get_application(app_id, RH))


def get_license(license_id) -> dict:
    return get_success_data(api_client.get_license(license_id, RH))


def get_royalty_statement(rs_id) -> dict:
    return get_success_data(api_client.get_royalty_statement(rs_id, RH))


# --------------------------------------------------------------------------
# Application lifecycle
# --------------------------------------------------------------------------
def setup_application_submitted(work_overrides=None, app_overrides=None):
    """Create a work + DRAFT application, then submit it. Returns (work, submitted_app)."""
    work = create_work(**(work_overrides or {}))
    app = create_application(work["id"], **(app_overrides or {}))
    submitted = get_success_data(api_client.submit_application(app["id"], RH))
    return work, submitted


def setup_application_under_examination(work_overrides=None, app_overrides=None):
    """Advance a fresh application all the way to UNDER_EXAMINATION.

    Pays the exact computed fee_due_cents, submits an ELECTRONIC deposit with one
    copy, accepts it, and begins examination. Returns (work, app_in_examination).
    """
    work, submitted = setup_application_submitted(work_overrides, app_overrides)
    app_id = submitted["id"]
    fee = submitted["fee_due_cents"]
    get_success_data(api_client.pay_fee(app_id, f.pay_fee_payload(fee), RH))
    deposit = get_success_data(
        api_client.create_deposit(f.create_deposit_payload(app_id), RH)
    )
    get_success_data(api_client.accept_deposit(deposit["id"], EX))
    app = get_success_data(api_client.begin_examination(app_id, EX))
    return work, app


def setup_registered_work(work_overrides=None, app_overrides=None):
    """Full pipeline to a REGISTERED work. Returns (work_after_registration, app)."""
    work, app = setup_application_under_examination(work_overrides, app_overrides)
    registered_app = get_success_data(api_client.register_application(app["id"], EX))
    work = get_work(work["id"])
    return work, registered_app


def get_certificate_for_application(app_id) -> dict:
    data, _meta = _list(api_client.list_certificates(RH, params={"application_id": app_id}))
    assert data, f"Setup failed: no certificate for application {app_id}"
    return data[0]


# --------------------------------------------------------------------------
# Licensing / royalty
# --------------------------------------------------------------------------
def create_active_license(work_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_license(f.create_license_payload(work_id, **overrides), RH)
    )


def create_draft_statement(license_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_royalty_statement(
            f.create_royalty_statement_payload(license_id, **overrides), RH
        )
    )


def post_statement(rs_id) -> dict:
    return get_success_data(api_client.post_royalty_statement(rs_id, RH))


def setup_registered_work_with_license(work_overrides=None, license_overrides=None):
    """REGISTERED work + one ACTIVE license. Returns (work, license)."""
    work, _app = setup_registered_work(work_overrides)
    lic = create_active_license(work["id"], **(license_overrides or {}))
    return work, lic


def setup_license_with_draft_statement(work_overrides=None, license_overrides=None,
                                       statement_overrides=None):
    """REGISTERED work + ACTIVE license + one DRAFT statement.

    Returns (work, license, statement).
    """
    work, lic = setup_registered_work_with_license(work_overrides, license_overrides)
    rs = create_draft_statement(lic["id"], **(statement_overrides or {}))
    return work, lic, rs


def setup_license_with_posted_statement(work_overrides=None, license_overrides=None,
                                        statement_overrides=None):
    """REGISTERED work + ACTIVE license + one POSTED statement.

    Returns (work, license, statement_after_post).
    """
    work, lic, rs = setup_license_with_draft_statement(
        work_overrides, license_overrides, statement_overrides
    )
    posted = post_statement(rs["id"])
    return work, lic, posted


# --------------------------------------------------------------------------
# DMCA
# --------------------------------------------------------------------------
def setup_effective_takedown(clock="2026-06-01T00:00:00Z", work_overrides=None):
    """Set the clock, create a work + takedown, and process it to EFFECTIVE.

    Returns (work, takedown_effective).
    """
    set_clock(clock)
    wo = {"work_type": "VISUAL_ARTS"}
    wo.update(work_overrides or {})
    work = create_work(**wo)
    td = get_success_data(
        api_client.create_dmca_takedown(f.create_dmca_takedown_payload(work["id"]), CX)
    )
    td = get_success_data(api_client.process_dmca_takedown(td["id"], EX))
    return work, td


def setup_countered_takedown(clock="2026-06-01T00:00:00Z", work_overrides=None):
    """EFFECTIVE takedown + one counter-notice (takedown -> COUNTERED).

    Returns (work, takedown, counter_notice).
    """
    work, td = setup_effective_takedown(clock, work_overrides)
    cn = get_success_data(
        api_client.create_counter_notice(f.create_counter_notice_payload(td["id"]), RH)
    )
    return work, td, cn


# --------------------------------------------------------------------------
# Termination
# --------------------------------------------------------------------------
def setup_license_for_termination(grant_date="1990-06-01T00:00:00Z",
                                  effective_date="2025-06-01T00:00:00Z",
                                  clock="2026-05-02T00:00:00Z",
                                  license_overrides=None,
                                  with_posted_statement=False,
                                  with_draft_statement=False):
    """REGISTERED work + ACTIVE license (old grant_date) + served Termination.

    The license term spans the grant so it is valid; optionally seeds a POSTED
    or DRAFT statement. Returns (work, license, termination).
    """
    set_clock(clock)
    work, _app = setup_registered_work({"year_of_creation": 1988})
    lo = {
        "grant_date": grant_date,
        "start_date": grant_date,
        "end_date": "2035-06-01T00:00:00Z",
        "royalty_rate_bps": 1500,
        "royalty_basis": "GROSS",
    }
    lo.update(license_overrides or {})
    lic = create_active_license(work["id"], **lo)
    if with_posted_statement:
        rs = create_draft_statement(lic["id"])
        post_statement(rs["id"])
    if with_draft_statement:
        create_draft_statement(lic["id"])
    term = get_success_data(
        api_client.create_termination(
            f.create_termination_payload(lic["id"], effective_date=effective_date), RH
        )
    )
    return work, lic, term


# --------------------------------------------------------------------------
# Internal list helper
# --------------------------------------------------------------------------
def _list(response):
    """Return (data_list, meta) from a list response using the lenient path."""
    body = response.json()
    return body["data"], body["meta"]

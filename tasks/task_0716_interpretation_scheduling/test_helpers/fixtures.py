"""Composite setup helpers.

Every test runs against a freshly restarted, empty server, so each fixture builds
its preconditions from scratch using only PRD-declared endpoints. Setup calls use the
lenient get_success_data() validator so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    admin_headers, coordinator_headers, make_client_headers, make_interpreter_headers,
)
from . import factories as f


# --------------------------------------------------------------------------- #
# Low-level building blocks
# --------------------------------------------------------------------------- #
def set_clock(to_iso8601):
    """Advance the logical clock (PlatformAdmin)."""
    return get_success_data(api_client.set_clock(f.clock_payload(to_iso8601), admin_headers()))


def create_client(**overrides):
    return get_success_data(
        api_client.create_client(f.create_client_payload(**overrides), admin_headers())
    )


def create_language_pair(**overrides):
    return get_success_data(
        api_client.create_language_pair(f.create_language_pair_payload(**overrides), admin_headers())
    )


def create_rate_plan(client_id, **overrides):
    payload = f.create_rate_plan_payload(client_id=client_id, **overrides)
    return get_success_data(api_client.create_rate_plan(payload, admin_headers()))


def create_interpreter(**overrides):
    return get_success_data(
        api_client.create_interpreter(f.create_interpreter_payload(**overrides), admin_headers())
    )


def add_certification(interpreter_id, **overrides):
    payload = f.create_certification_payload(**overrides)
    return get_success_data(api_client.create_certification(interpreter_id, payload, admin_headers()))


def add_language_grant(interpreter_id, language_pair_id):
    payload = f.create_language_grant_payload(language_pair_id=language_pair_id)
    return get_success_data(api_client.create_language_grant(interpreter_id, payload, admin_headers()))


def create_request(client_id, language_pair_id, **overrides):
    payload = f.create_request_payload(
        client_id=client_id, language_pair_id=language_pair_id, **overrides
    )
    return get_success_data(api_client.create_request(payload, make_client_headers(client_id)))


def dispatch_request(request_id, expected_version):
    return get_success_data(
        api_client.dispatch_request(request_id, f.dispatch_payload(expected_version), coordinator_headers())
    )


# --------------------------------------------------------------------------- #
# Tier 1 / 2: provisioning a single eligible interpreter + matching rate plan
# --------------------------------------------------------------------------- #
def provision_med_phone(credit_limit_cents=None, max_concurrent_load=None,
                        rate_cents=195, min_block_units=10):
    """Mercy hospital + PER_MINUTE MEDICAL/PHONE rate plan + one en-es interpreter
    holding a valid MEDICAL cert and the pair. Clock left at startup default.

    Returns dict with keys: client, lp, interpreter (each the entity dict).
    """
    client_kwargs = {}
    if credit_limit_cents is not None:
        client_kwargs["credit_limit_cents"] = credit_limit_cents
    client = create_client(**client_kwargs)
    create_rate_plan(
        client["id"], certification_tier="MEDICAL", modality="PHONE",
        billing_mode="PER_MINUTE", rate_cents=rate_cents, min_block_units=min_block_units,
    )
    lp = create_language_pair(source_lang="en", target_lang="es")
    itp_kwargs = {"full_name": "Med I"}
    if max_concurrent_load is not None:
        itp_kwargs["max_concurrent_load"] = max_concurrent_load
    interpreter = create_interpreter(**itp_kwargs)
    add_certification(interpreter["id"], tier="MEDICAL", expires_at="2027-01-01T00:00:00Z")
    add_language_grant(interpreter["id"], lp["id"])
    return {"client": client, "lp": lp, "interpreter": interpreter}


def provision_court_onsite_per_hour(rate_cents=12000, min_block_units=2,
                                    travel_surcharge_cents=4500, max_concurrent_load=None):
    """County Court + PER_HOUR LEGAL/ONSITE rate plan + one en-es interpreter holding a
    valid LEGAL cert and the pair. Clock left at startup default.

    Returns dict with keys: client, lp, interpreter.
    """
    client = create_client(org_name="County Court", org_type="COURT", contact_email="court@x.com")
    create_rate_plan(
        client["id"], certification_tier="LEGAL", modality="ONSITE",
        billing_mode="PER_HOUR", rate_cents=rate_cents, min_block_units=min_block_units,
        travel_surcharge_cents=travel_surcharge_cents,
    )
    lp = create_language_pair(source_lang="en", target_lang="es")
    itp_kwargs = {"full_name": "Lex T"}
    if max_concurrent_load is not None:
        itp_kwargs["max_concurrent_load"] = max_concurrent_load
    interpreter = create_interpreter(**itp_kwargs)
    add_certification(interpreter["id"], tier="LEGAL", expires_at="2027-01-01T00:00:00Z")
    add_language_grant(interpreter["id"], lp["id"])
    return {"client": client, "lp": lp, "interpreter": interpreter}


# --------------------------------------------------------------------------- #
# Tier 3: full lifecycle shortcuts (dispatch -> accept -> start -> connect)
# --------------------------------------------------------------------------- #
def dispatch_accept(client_id, lp_id, interpreter_id, request_overrides=None):
    """Create an ON_DEMAND request, dispatch it, accept the offer.
    Returns (request, assignment) where assignment.lifecycle_status == ACCEPTED.
    """
    request_overrides = request_overrides or {}
    req = create_request(client_id, lp_id, **request_overrides)
    asg = dispatch_request(req["id"], req["version"])
    asg = get_success_data(
        api_client.accept_assignment(asg["id"], make_interpreter_headers(interpreter_id))
    )
    return req, asg


def create_connected_session(client_id, lp_id, interpreter_id, request_overrides=None):
    """Dispatch -> accept -> start-session -> connect. Returns (request, assignment, session)
    with session.status == ACTIVE. Clock is whatever the caller set; connect stamps it.
    """
    req, asg = dispatch_accept(client_id, lp_id, interpreter_id, request_overrides)
    itp_h = make_interpreter_headers(interpreter_id)
    session = get_success_data(api_client.start_session(asg["id"], itp_h))
    session = get_success_data(api_client.connect_session(session["id"], itp_h))
    return req, asg, session


def create_ended_session(client_id, lp_id, interpreter_id, connect_iso, end_iso,
                         request_overrides=None):
    """Full path to an ENDED, billed session for an ON_DEMAND request.

    Sets clock to connect_iso, connects; sets clock to end_iso, ends.
    Returns (request, assignment, session) with session.status == ENDED and
    billed_units/billed_amount_cents populated.
    """
    req, asg = dispatch_accept(client_id, lp_id, interpreter_id, request_overrides)
    itp_h = make_interpreter_headers(interpreter_id)
    session = get_success_data(api_client.start_session(asg["id"], itp_h))
    set_clock(connect_iso)
    get_success_data(api_client.connect_session(session["id"], itp_h))
    set_clock(end_iso)
    session = get_success_data(api_client.end_session(session["id"], itp_h))
    return req, asg, session


def create_billed_med_phone_session(connect_iso="2026-03-10T09:00:00Z",
                                    end_iso="2026-03-10T09:20:00Z"):
    """Provision med-phone + run a 20-minute (default) ON_DEMAND session to ENDED.
    20 min at 195c/min, min-block 10 -> billed_units=20, billed_amount_cents=3900.
    Returns dict: client, lp, interpreter, request, assignment, session.
    """
    env = provision_med_phone()
    set_clock("2026-03-10T09:00:00Z")
    req, asg, session = create_ended_session(
        env["client"]["id"], env["lp"]["id"], env["interpreter"]["id"],
        connect_iso, end_iso,
    )
    env.update({"request": req, "assignment": asg, "session": session})
    return env


# --------------------------------------------------------------------------- #
# Tier 5: invoice / finalization
# --------------------------------------------------------------------------- #
def open_invoice(client_id):
    return get_success_data(api_client.create_invoice(f.invoice_payload(client_id), coordinator_headers()))


def issue_invoice(invoice_id):
    return get_success_data(api_client.issue_invoice(invoice_id, coordinator_headers()))


def create_issued_invoice_for_session():
    """Build a billed med-phone session (3900c), sweep it into an invoice and issue it.
    Returns dict: client, lp, interpreter, request, assignment, session, invoice.
    """
    env = create_billed_med_phone_session()
    inv = open_invoice(env["client"]["id"])
    inv = issue_invoice(inv["id"])
    env["invoice"] = inv
    return env


def create_under_review_complaint(session_id, client_id, category):
    """File a complaint and move it to UNDER_REVIEW. Returns the complaint dict."""
    cmp = get_success_data(
        api_client.create_complaint(f.complaint_payload(session_id, category), make_client_headers(client_id))
    )
    cmp = get_success_data(api_client.review_complaint(cmp["id"], admin_headers()))
    return cmp

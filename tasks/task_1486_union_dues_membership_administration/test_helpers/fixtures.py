"""Composite setup helpers.

Every helper builds state from scratch through the public API (each test runs
against a fresh server), using the lenient get_success_data validator so a
failed setup step reports as a clear setup error. Operator identities follow
the segregation-of-duties pattern: remittances are received by clerk_1 and
posted by st_1; per-capita reports are created by st_1 and approved by
admin_1; Member-role calls always carry the member's own id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_assessment_run_payload,
    create_classification_payload,
    create_election_payload,
    create_employer_payload,
    create_local_payload,
    create_member_payload,
    create_payment_payload,
    create_percapita_report_payload,
    create_remittance_line_payload,
    create_remittance_payload,
    create_resolve_dispute_payload,
    create_set_rate_payload,
    create_transfer_payload,
)
from .test_users import (
    LOCAL_ADMIN_1_HEADERS,
    OFFICE_CLERK_1_HEADERS,
    SECRETARY_TREASURER_1_HEADERS,
    TEST_USERS,
    make_member_headers,
)

PBA = TEST_USERS["parentbody_admin_headers"]
ADMIN = TEST_USERS["local_admin_headers"]
ST = TEST_USERS["secretary_treasurer_headers"]
CLERK = TEST_USERS["office_clerk_headers"]


# --- Clock ---------------------------------------------------------------

def set_clock(iso: str = "2026-08-01T00:00:00Z") -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, PBA))


# --- Simple creators -----------------------------------------------------

def make_local(method: str = "PCT", name=None, **overrides) -> dict:
    payload = create_local_payload(name=name, method=method, **overrides)
    return get_success_data(api_client.create_local(payload, PBA))


def make_classification(local_id, code="JOURNEYMAN", min_monthly_dues_cents=3000, **overrides) -> dict:
    payload = create_classification_payload(code, min_monthly_dues_cents, **overrides)
    return get_success_data(api_client.create_classification(local_id, payload, ADMIN))


def make_employer(name=None) -> dict:
    return get_success_data(api_client.create_employer(create_employer_payload(name), CLERK))


def make_member(local_id, classification_id, employer_id=None, **overrides) -> dict:
    payload = create_member_payload(local_id, classification_id, employer_id=employer_id, **overrides)
    return get_success_data(api_client.create_member(payload, CLERK))


def make_assessment_run(local_id, period) -> dict:
    return get_success_data(
        api_client.create_assessment_run(create_assessment_run_payload(local_id, period), ST)
    )


def run_period(local_id, period) -> dict:
    """Set the clock to the first of the period month, then run assessments."""
    set_clock(f"{period}-01T00:00:00Z")
    return make_assessment_run(local_id, period)


def make_payment(member_id, amount_cents, headers=None) -> dict:
    """Record a direct payment; default caller is the member self-service."""
    hdrs = headers or make_member_headers(member_id)
    return get_success_data(api_client.create_payment(member_id, create_payment_payload(amount_cents), hdrs))


def make_remittance(employer_id, local_id, period, remitted_cents, receiver_headers=None) -> dict:
    hdrs = receiver_headers or OFFICE_CLERK_1_HEADERS
    return get_success_data(
        api_client.create_remittance(
            create_remittance_payload(employer_id, local_id, period, remitted_cents), hdrs
        )
    )


def add_remittance_line(remittance_id, member_id, deducted_cents, gross_wages_cents) -> dict:
    return get_success_data(
        api_client.create_remittance_line(
            remittance_id,
            create_remittance_line_payload(member_id, deducted_cents, gross_wages_cents),
            CLERK,
        )
    )


def reconcile_remittance(remittance_id, headers=None) -> dict:
    return get_success_data(api_client.reconcile_remittance(remittance_id, headers or SECRETARY_TREASURER_1_HEADERS))


def resolve_remittance(remittance_id, note="accept union-assessed amounts", headers=None) -> dict:
    return get_success_data(
        api_client.resolve_remittance_dispute(
            remittance_id, create_resolve_dispute_payload(note), headers or SECRETARY_TREASURER_1_HEADERS
        )
    )


def post_remittance(remittance_id, poster_headers=None) -> dict:
    return get_success_data(api_client.post_remittance(remittance_id, poster_headers or SECRETARY_TREASURER_1_HEADERS))


def void_remittance(remittance_id, headers=None) -> dict:
    return get_success_data(api_client.void_remittance(remittance_id, headers or LOCAL_ADMIN_1_HEADERS))


def list_member_notices(member_id, params=None) -> list:
    return get_success_data(api_client.list_notices(member_id, CLERK, params=params))


def send_notice(member_id, notice_id) -> dict:
    return get_success_data(api_client.send_notice(member_id, notice_id, CLERK))


def sweep_delinquency(local_id) -> dict:
    return get_success_data(api_client.run_delinquency_sweep({"local_id": local_id}, ADMIN))


def get_member(member_id) -> dict:
    return get_success_data(api_client.get_member(member_id, ST))


def get_local(local_id) -> dict:
    return get_success_data(api_client.get_local(local_id, ST))


def get_remittance(remittance_id) -> dict:
    return get_success_data(api_client.get_remittance(remittance_id, ST))


def get_transfer(transfer_id) -> dict:
    return get_success_data(api_client.get_transfer(transfer_id, CLERK))


# --- Transfers / per-capita / objectors / elections ----------------------

def make_transfer(member_id, to_local_id, effective_period, as_member_self=True) -> dict:
    """Initiate a transfer carrying the member's current version (OCC)."""
    member = get_member(member_id)
    payload = create_transfer_payload(to_local_id, effective_period, member["version"])
    headers = make_member_headers(member_id) if as_member_self else CLERK
    return get_success_data(api_client.create_transfer(member_id, payload, headers))


def make_percapita_report(local_id, period, creator_headers=None) -> dict:
    """Create a DRAFT per-capita report carrying the local's current version."""
    local = get_local(local_id)
    payload = create_percapita_report_payload(period, local["version"])
    return get_success_data(
        api_client.create_percapita_report(local_id, payload, creator_headers or SECRETARY_TREASURER_1_HEADERS)
    )


def make_objector_case(member_id) -> dict:
    return get_success_data(api_client.create_objector_case(member_id, make_member_headers(member_id)))


def set_objector_rate(case_id, chargeable_share_pct) -> dict:
    return get_success_data(
        api_client.set_objector_rate(case_id, create_set_rate_payload(chargeable_share_pct), ADMIN)
    )


def make_election(local_id, **overrides) -> dict:
    return get_success_data(api_client.create_election(local_id, create_election_payload(**overrides), ADMIN))


# --- Composite drivers ---------------------------------------------------

def setup_pct_local_with_journeyman(min_dues=3000, local_name=None, **cls_overrides):
    """Canonical PERCENTAGE_OF_GROSS local with one JOURNEYMAN classification."""
    local = make_local("PCT", name=local_name)
    cls = make_classification(local["id"], "JOURNEYMAN", min_dues, **cls_overrides)
    return local, cls


def setup_flat_local_with_journeyman(flat=5000, local_name=None, min_dues=0, **local_overrides):
    """Canonical FLAT_RATE local with one JOURNEYMAN classification (floor 0)."""
    local = make_local("FLAT", name=local_name, default_flat_dues_cents=flat, **local_overrides)
    cls = make_classification(local["id"], "JOURNEYMAN", min_dues)
    return local, cls


def drive_member_delinquent(local_id, member_id,
                            charge_periods=("2026-05", "2026-06"),
                            sweep_at="2026-08-01T00:00:00Z") -> dict:
    """Post flat-rate assessment charges for the given periods, then run the
    delinquency sweep. Returns the member read after the sweep (DELINQUENT
    when arrears meet the aged-and-over predicates)."""
    for period in charge_periods:
        run_period(local_id, period)
    set_clock(sweep_at)
    sweep_delinquency(local_id)
    return get_member(member_id)


def drive_member_suspended(local_id, member_id,
                           charge_periods=("2026-05", "2026-06"),
                           sweep_at="2026-08-01T00:00:00Z",
                           expire_at="2026-08-12T00:00:00Z"):
    """Full enforcement chain: sweep (DELINQUENT + DRAFT notice), send the
    notice, advance the clock past the cure deadline, sweep again. Returns
    (member_after, notice_after) with the member SUSPENDED or EXPELLED
    depending on the local's suspension cap."""
    drive_member_delinquent(local_id, member_id, charge_periods, sweep_at)
    notices = list_member_notices(member_id)
    assert notices, "Setup failed: sweep created no DRAFT notice"
    notice_id = notices[0]["id"]
    send_notice(member_id, notice_id)
    set_clock(expire_at)
    sweep_delinquency(local_id)
    return get_member(member_id), get_success_data(
        api_client.list_notices(member_id, CLERK)
    )[0]


def setup_reconciled_remittance(employer_id, local_id, period, lines, remitted=None):
    """Remittance + lines, reconciled (clean when every line matches)."""
    total = remitted if remitted is not None else sum(d for _, d, _ in lines)
    rem = make_remittance(employer_id, local_id, period, total)
    for member_id, deducted, gross in lines:
        add_remittance_line(rem["id"], member_id, deducted, gross)
    return rem

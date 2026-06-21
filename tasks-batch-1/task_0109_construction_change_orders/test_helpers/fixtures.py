"""Composite setup helpers.

Each helper builds multi-step preconditions from scratch using only PRD-declared
endpoints, using get_success_data() (lenient) so setup failures surface as clear
"Setup failed" errors. The harness restarts the server (empty DB) before every
test, so every helper must construct its full state.

Opaque user ids used throughout:
  owner-1     Owner
  gc-1        Contractor
  arch-1      Architect
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_owner_headers,
    make_contractor_headers,
    make_architect_headers,
)
from . import factories

# Default opaque identities.
OWNER_ID = "owner-1"
GC_ID = "gc-1"
ARCH_ID = "arch-1"

OWNER = make_owner_headers(OWNER_ID)
CONTRACTOR = make_contractor_headers(GC_ID)
ARCHITECT = make_architect_headers(ARCH_ID)

# Standard billing-window dates (non-overlapping monthly windows).
JAN = ("2026-01-01T00:00:00.000Z", "2026-01-31T00:00:00.000Z")
FEB = ("2026-01-31T00:00:00.000Z", "2026-02-28T00:00:00.000Z")


# ---------------------------------------------------------------------------
# Tier 1 — primitive creators
# ---------------------------------------------------------------------------
def create_project(original_contract_sum_cents=1_000_000, default_retainage_pct=0.10,
                   name="Test Project"):
    """Create an ACTIVE project. Returns the project dict (version 1)."""
    payload = factories.create_project_payload(
        name=name,
        original_contract_sum_cents=original_contract_sum_cents,
        default_retainage_pct=default_retainage_pct,
    )
    return get_success_data(api_client.create_project(payload, OWNER))


def create_sov_line(project_id, item_no, scheduled_value_cents, description="Work item"):
    """Create one ACTIVE SOV line. Returns the line dict."""
    payload = factories.create_sov_line_payload(
        project_id, item_no, scheduled_value_cents, description=description
    )
    return get_success_data(api_client.create_sov_line(payload, CONTRACTOR))


def get_project_version(project_id):
    """Read the project's current version (fresh OCC guard value)."""
    proj = get_success_data(api_client.get_project(project_id, OWNER))
    return proj["version"]


# ---------------------------------------------------------------------------
# Tier 2 — project + schedule of values
# ---------------------------------------------------------------------------
def setup_project_with_two_sov_lines(original_contract_sum_cents=1_000_000,
                                     default_retainage_pct=0.10,
                                     sov1_value=600_000, sov2_value=400_000,
                                     name="Test Project"):
    """Active project + two SOV lines (item_no 001, 002).

    Returns (project, sov1, sov2). sov1+sov2 default to the original sum so the
    schedule-of-values invariant holds.
    """
    project = create_project(original_contract_sum_cents, default_retainage_pct, name)
    sov1 = create_sov_line(project["id"], "001", sov1_value, "Foundation")
    sov2 = create_sov_line(project["id"], "002", sov2_value, "Framing")
    return project, sov1, sov2


def setup_project_with_one_sov_line(original_contract_sum_cents=1_000_000,
                                    default_retainage_pct=0.10,
                                    sov1_value=600_000, name="Test Project"):
    """Active project + one SOV line (item_no 001). Returns (project, sov1)."""
    project = create_project(original_contract_sum_cents, default_retainage_pct, name)
    sov1 = create_sov_line(project["id"], "001", sov1_value, "Foundation")
    return project, sov1


# ---------------------------------------------------------------------------
# Tier 3 — pay application lifecycle
# ---------------------------------------------------------------------------
def create_pay_application(project_id, application_number, period, expected_version):
    """Create a DRAFT pay application. period is a (from, to) tuple."""
    payload = factories.create_pay_application_payload(
        project_id, application_number, period[0], period[1], expected_version
    )
    return get_success_data(api_client.create_pay_application(payload, CONTRACTOR))


def add_pay_app_line(pay_app_id, sov_line_id, work_completed_this_period_cents,
                     materials_stored_cents=0):
    """Add one G703 billing line to a draft pay application."""
    payload = factories.create_pay_app_line_payload(
        pay_app_id, sov_line_id, work_completed_this_period_cents,
        materials_stored_cents=materials_stored_cents,
    )
    return get_success_data(api_client.create_pay_app_line(payload, CONTRACTOR))


def submit_pay_application(pay_app_id):
    return get_success_data(api_client.submit_pay_application(pay_app_id, CONTRACTOR))


def certify_pay_application(pay_app_id, architect_headers=None):
    headers = architect_headers if architect_headers is not None else ARCHITECT
    return get_success_data(api_client.certify_pay_application(pay_app_id, headers))


def setup_submitted_pay_app_one_line(sov1_value=600_000, period=JAN,
                                     work_completed_this_period_cents=100_000):
    """Project + 1 SOV + DRAFT pay app 1 with one line, SUBMITTED.

    Returns (project, sov1, pay_app). Useful for certify-gate / segregation tests.
    """
    project, sov1 = setup_project_with_one_sov_line(sov1_value=sov1_value)
    pv = project["version"]
    pay_app = create_pay_application(project["id"], 1, period, pv)
    add_pay_app_line(pay_app["id"], sov1["id"], work_completed_this_period_cents)
    # Return the SUBMITTED response so the pay_app dict reflects the SUBMITTED
    # status and the G702 header totals computed on submission (PRD §3.3),
    # not the stale DRAFT snapshot with zeroed totals.
    pay_app = submit_pay_application(pay_app["id"])
    return project, sov1, pay_app


def setup_certified_two_line_project(period=JAN):
    """The canonical certified-state fixture used by retention / waiver / close
    flows.

    Project (orig 1000000, retainage 0.10) + SOV 001 (600000) and 002 (400000) +
    pay app 1 with lines billing 300000 on 001 and (100000 + 50000 materials) on
    002, SUBMITTED then CERTIFIED. After certify:
      total_completed_and_stored = 450000, retainage_held = 45000
      (001 retainage 30000, 002 retainage 15000); project version 2.

    Returns (project, sov1, sov2, pay_app).
    """
    project, sov1, sov2 = setup_project_with_two_sov_lines()
    pv = project["version"]
    pay_app = create_pay_application(project["id"], 1, period, pv)
    add_pay_app_line(pay_app["id"], sov1["id"], 300_000, 0)
    add_pay_app_line(pay_app["id"], sov2["id"], 100_000, 50_000)
    submit_pay_application(pay_app["id"])
    certify_pay_application(pay_app["id"])
    return project, sov1, sov2, pay_app


# ---------------------------------------------------------------------------
# Tier 4 — change-order lifecycle
# ---------------------------------------------------------------------------
def create_change_order(project_id, co_number, change_order_amount_cents, line_edits):
    payload = factories.create_change_order_payload(
        project_id, co_number, change_order_amount_cents, line_edits
    )
    return get_success_data(api_client.create_change_order(payload, CONTRACTOR))


def submit_change_order(change_order_id):
    return get_success_data(api_client.submit_change_order(change_order_id, CONTRACTOR))


def setup_submitted_change_order(change_order_amount_cents, line_edits,
                                 sov1_value=600_000, sov2_value=400_000,
                                 co_number="CO-1"):
    """Project + SOV 001/002 + a SUBMITTED change order.

    Returns (project, sov1, sov2, change_order).
    """
    project, sov1, sov2 = setup_project_with_two_sov_lines(
        sov1_value=sov1_value, sov2_value=sov2_value
    )
    co = create_change_order(project["id"], co_number, change_order_amount_cents,
                             line_edits)
    submit_change_order(co["id"])
    return project, sov1, sov2, co


# ---------------------------------------------------------------------------
# Tier 5 — retention release / commitment / waiver lifecycle
# ---------------------------------------------------------------------------
def create_retention_release(project_id, amount_cents, expected_version):
    payload = factories.create_retention_release_payload(
        project_id, amount_cents, expected_version
    )
    return get_success_data(api_client.create_retention_release(payload, CONTRACTOR))


def setup_release_requested(amount_cents, period=JAN):
    """Certified two-line project + a REQUESTED retention release for amount_cents.

    Returns (project, sov1, sov2, pay_app, release). The release was created with
    a fresh project version; callers approve with a re-read version.
    """
    project, sov1, sov2, pay_app = setup_certified_two_line_project(period=period)
    pv = get_project_version(project["id"])
    release = create_retention_release(project["id"], amount_cents, pv)
    return project, sov1, sov2, pay_app, release


def create_subcontractor_commitment(project_id, subcontractor_name, committed_amount_cents):
    payload = factories.create_subcontractor_commitment_payload(
        project_id, subcontractor_name, committed_amount_cents
    )
    return get_success_data(
        api_client.create_subcontractor_commitment(payload, CONTRACTOR)
    )


def create_lien_waiver(project_id, pay_app_id, waiver_type, through_date, amount_cents):
    payload = factories.create_lien_waiver_payload(
        project_id, pay_app_id, waiver_type, through_date, amount_cents
    )
    return get_success_data(api_client.create_lien_waiver(payload, CONTRACTOR))


def setup_certified_with_commitment_and_pending_waiver(waiver_type, commitment_amount=500_000,
                                                       waiver_amount=405_000,
                                                       through_date="2026-01-31T00:00:00.000Z"):
    """Certified two-line project (cpd 405000) + one OPEN commitment +
    a PENDING lien waiver of the given type against the certified app.

    Returns (project, sov1, sov2, pay_app, commitment, waiver).
    """
    project, sov1, sov2 = setup_project_with_two_sov_lines()
    commitment = create_subcontractor_commitment(project["id"], "Acme", commitment_amount)
    pv = project["version"]
    pay_app = create_pay_application(project["id"], 1, JAN, pv)
    add_pay_app_line(pay_app["id"], sov1["id"], 300_000, 0)
    add_pay_app_line(pay_app["id"], sov2["id"], 100_000, 50_000)
    submit_pay_application(pay_app["id"])
    certify_pay_application(pay_app["id"])
    waiver = create_lien_waiver(
        project["id"], pay_app["id"], waiver_type, through_date, waiver_amount
    )
    return project, sov1, sov2, pay_app, commitment, waiver


# ---------------------------------------------------------------------------
# Tier 6 — project terminal-state progression
# ---------------------------------------------------------------------------
def advance_project_to_substantially_complete():
    """Certified two-line project → release all retainage → substantial-completion.

    No punch items (precondition satisfied vacuously) and one certified app.
    Returns (project, sov1, sov2, pay_app).
    """
    project, sov1, sov2, pay_app = setup_certified_two_line_project()
    pv = get_project_version(project["id"])
    release = create_retention_release(project["id"], 45_000, pv)
    pv2 = get_project_version(project["id"])
    get_success_data(
        api_client.approve_retention_release(
            release["id"], {"expected_project_version": pv2}, OWNER
        )
    )
    get_success_data(
        api_client.substantial_completion_project(project["id"], ARCHITECT)
    )
    return project, sov1, sov2, pay_app

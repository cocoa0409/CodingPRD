"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database and the logical clock at 2026-08-01T00:00:00Z). Setup calls use
get_success_data so failures surface as clear "Setup failed" errors.

The logical clock only ever moves forward inside these helpers: photo uploads
require captured_at to sit inside [check_in_at, now] while the assignment is
ON_SITE (PRD 3.4), so execute_visit drives the clock to the check-in instant,
uploads the BEFORE photo at that exact instant, advances the clock to the
check-out instant, uploads the AFTER photo, then checks out.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    DEFAULTS,
    create_assignment_payload,
    create_client_payload,
    create_fixture_shipment_payload,
    create_invoice_payload,
    create_mileage_log_payload,
    create_photo_payload,
    create_project_payload,
    create_project_store_payload,
    create_rep_payload,
    create_rework_authorization_payload,
    create_store_payload,
)
from .test_users import TEST_USERS, make_client_headers, make_field_rep_headers

PM = TEST_USERS["pm_headers"]
PA = TEST_USERS["payroll_admin_headers"]
BC = TEST_USERS["billing_clerk_headers"]

_store_seq = itertools.count(1)
_name_seq = itertools.count(1)

DEFAULT_DUE_DATE = DEFAULTS["DUE_DATE"]


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
    )


def _ok(step, resp):
    try:
        return get_success_data(resp)
    except AssertionError:
        _fail(step, resp)


# ---------------------------------------------------------------------------
# Tier 0 — single-entity creators
# ---------------------------------------------------------------------------

def create_client(**overrides):
    resp = api_client.create_client(create_client_payload(**overrides), PM)
    return _ok("create_client", resp)


def create_store(**overrides):
    overrides.setdefault("store_number", f"S{next(_store_seq):04d}")
    resp = api_client.create_store(create_store_payload(**overrides), PM)
    return _ok("create_store", resp)


def create_rep(**overrides):
    overrides.setdefault("full_name", f"Rep {next(_name_seq)}")
    resp = api_client.create_rep(create_rep_payload(**overrides), PA)
    return _ok("create_rep", resp)


def create_project(client_id, **overrides):
    resp = api_client.create_project(create_project_payload(client_id, **overrides), PM)
    return _ok("create_project", resp)


def add_project_store(project_id, store_id, due_date=DEFAULT_DUE_DATE):
    resp = api_client.create_project_store(
        create_project_store_payload(project_id, store_id, due_date=due_date), PM
    )
    return _ok("add_project_store", resp)


def get_project(project_id):
    return _ok("get_project", api_client.get_project(project_id, PM))


def get_project_store(ps_id):
    return _ok("get_project_store", api_client.get_project_store(ps_id, PM))


def get_assignment(assignment_id):
    return _ok("get_assignment", api_client.get_assignment(assignment_id, PM))


def get_store_visit(visit_id):
    return _ok("get_store_visit", api_client.get_store_visit(visit_id, PM))


def set_clock(to_iso8601):
    return _ok("set_clock", api_client.set_clock(to_iso8601, PM))


# ---------------------------------------------------------------------------
# Tier 1 — state progression
# ---------------------------------------------------------------------------

def scope_project(project_id, expected_version=None):
    """Scope a DRAFT project. Re-reads the project to obtain the current
    version (store-list additions increment the parent project's version).
    Pass expected_version explicitly to exercise stale-version rejection."""
    if expected_version is None:
        expected_version = get_project(project_id)["version"]
    resp = api_client.scope_project(
        project_id, {"expected_project_version": expected_version}, PM
    )
    return _ok("scope_project", resp)


def schedule_assignment(project_id, project_store_id, rep_id,
                        scheduled_start=DEFAULTS["SCHEDULED_START"],
                        scheduled_end=DEFAULTS["SCHEDULED_END"],
                        rework_authorization_id=None):
    payload = create_assignment_payload(
        project_id, project_store_id, rep_id,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
    )
    if rework_authorization_id is not None:
        payload["rework_authorization_id"] = rework_authorization_id
    resp = api_client.create_assignment(payload, PM)
    return _ok("schedule_assignment", resp)


def depart_assignment(assignment_id, rep_id):
    resp = api_client.depart_assignment(assignment_id, make_field_rep_headers(rep_id))
    return _ok("depart_assignment", resp)


def check_in_assignment(assignment_id, rep_id):
    """Check in; creates the StoreVisit. Returns the visit."""
    resp = api_client.check_in_assignment(assignment_id, make_field_rep_headers(rep_id))
    return _ok("check_in_assignment", resp)


def check_out_assignment(assignment_id, rep_id):
    """Check out; returns the StoreVisit with check_out_at and on_site_minutes."""
    resp = api_client.check_out_assignment(assignment_id, make_field_rep_headers(rep_id))
    return _ok("check_out_assignment", resp)


def upload_photo(visit_id, rep_id, photo_type, captured_at, image_url=None):
    payload = create_photo_payload(photo_type, captured_at)
    if image_url is not None:
        payload["image_url"] = image_url
    resp = api_client.upload_photo(visit_id, payload, make_field_rep_headers(rep_id))
    return _ok("upload_photo", resp)


def execute_visit(assignment_id, rep_id, check_in_at, check_out_at):
    """Drive a SCHEDULED assignment to SUBMITTED:
    clock -> check_in_at, check in, BEFORE photo captured at check_in_at,
    clock -> check_out_at, AFTER photo captured at check_out_at, check out.
    Returns the SUBMITTED StoreVisit."""
    set_clock(check_in_at)
    visit = check_in_assignment(assignment_id, rep_id)
    upload_photo(visit["id"], rep_id, "BEFORE", check_in_at)
    set_clock(check_out_at)
    upload_photo(visit["id"], rep_id, "AFTER", check_out_at)
    return check_out_assignment(assignment_id, rep_id)


def verify_visit(visit_id):
    return _ok("verify_visit", api_client.verify_store_visit(visit_id, PM))


def reject_visit(visit_id):
    return _ok("reject_visit", api_client.reject_store_visit(visit_id, PM))


# ---------------------------------------------------------------------------
# Tier 2 — entity hierarchy scenario
# ---------------------------------------------------------------------------

def make_scenario(num_stores=1, num_reps=1, scope_type="AUDIT",
                  client_overrides=None, project_overrides=None,
                  rep_overrides_list=None, due_date=DEFAULT_DUE_DATE):
    """Client + project + stores + reps, with the project SCOPED.

    Returns {"client", "project", "stores", "ps_rows", "reps"}.
    The returned project snapshot is taken right after scoping.
    """
    client = create_client(**(client_overrides or {}))
    # scope_type is a scenario-level knob: forward it to project creation
    # unless project_overrides pins an explicit scope_type.
    proj_over = {"scope_type": scope_type, **(project_overrides or {})}
    project = create_project(client["id"], **proj_over)
    stores, ps_rows = [], []
    for _ in range(num_stores):
        store = create_store()
        ps = add_project_store(project["id"], store["id"], due_date=due_date)
        stores.append(store)
        ps_rows.append(ps)
    reps = []
    for i in range(num_reps):
        over = (rep_overrides_list or [{}] * num_reps)[i]
        reps.append(create_rep(**over))
    scoped = scope_project(project["id"])
    return {
        "client": client,
        "project": scoped,
        "stores": stores,
        "ps_rows": ps_rows,
        "reps": reps,
    }


def visit_store(scn, store_idx=0, rep_idx=0,
                window=("2026-08-05T09:00:00Z", "2026-08-05T11:00:00Z"),
                on_site=("2026-08-05T09:30:00Z", "2026-08-05T10:30:00Z"),
                outcome=None, rework_authorization_id=None):
    """Schedule + execute a visit on scenario store row `store_idx`.

    outcome: None (leave SUBMITTED) | "verify" | "reject".
    Returns (assignment, store_visit)."""
    project = scn["project"]
    ps = scn["ps_rows"][store_idx]
    rep = scn["reps"][rep_idx]
    asg = schedule_assignment(
        project["id"], ps["id"], rep["id"],
        scheduled_start=window[0], scheduled_end=window[1],
        rework_authorization_id=rework_authorization_id,
    )
    visit = execute_visit(asg["id"], rep["id"], on_site[0], on_site[1])
    if outcome == "verify":
        visit = verify_visit(visit["id"])
    elif outcome == "reject":
        visit = reject_visit(visit["id"])
    return asg, visit


# ---------------------------------------------------------------------------
# Tier 3 — rework loop helpers
# ---------------------------------------------------------------------------

def find_rework_auth(project_store_id, status=None):
    params = {"project_store_id": project_store_id}
    if status:
        params["status"] = status
    data = _ok(
        "find_rework_auth",
        api_client.list_rework_authorizations(PM, params=params),
    )
    assert isinstance(data, list) and data, (
        f"Setup failed: no rework authorization found for store row {project_store_id}"
    )
    if status:
        data = [row for row in data if row["status"] == status]
        assert data, (
            f"Setup failed: no {status} rework authorization for {project_store_id}"
        )
    return data[0]


def approve_rework_auth(auth_id, client_id):
    resp = api_client.approve_rework_authorization(
        auth_id, make_client_headers(client_id)
    )
    return _ok("approve_rework_auth", resp)


def deny_rework_auth(auth_id, client_id):
    resp = api_client.deny_rework_authorization(auth_id, make_client_headers(client_id))
    return _ok("deny_rework_auth", resp)


def setup_rejected_visit(scn=None, **scenario_kwargs):
    """Rejected visit: scenario + one visit rejected by the ProjectManager.
    Returns (scenario, assignment, visit, requested_auth)."""
    if scn is None:
        scn = make_scenario(**scenario_kwargs)
    asg, visit = visit_store(scn, outcome="reject")
    auth = find_rework_auth(scn["ps_rows"][0]["id"], status="REQUESTED")
    return scn, asg, visit, auth


def complete_rework_loop(scn, store_idx=0, rep_idx=0,
                         window=("2026-08-06T09:00:00Z", "2026-08-06T11:00:00Z"),
                         on_site=("2026-08-06T09:30:00Z", "2026-08-06T10:30:00Z"),
                         outcome=None):
    """Approve the open REQUESTED authorization for the store row (as the
    owning client), consume it via a rework assignment, and execute the rework
    visit. Returns (auth, rework_assignment, rework_visit)."""
    client = scn["client"]
    ps = scn["ps_rows"][store_idx]
    auth = find_rework_auth(ps["id"], status="REQUESTED")
    approve_rework_auth(auth["id"], client["id"])
    asg, visit = visit_store(
        scn, store_idx=store_idx, rep_idx=rep_idx, window=window,
        on_site=on_site, outcome=outcome, rework_authorization_id=auth["id"],
    )
    return auth, asg, visit


# ---------------------------------------------------------------------------
# Tier 4 — fixture shipments
# ---------------------------------------------------------------------------

def create_shipment(project_id, project_store_id, **overrides):
    resp = api_client.create_fixture_shipment(
        create_fixture_shipment_payload(project_id, project_store_id, **overrides), PM
    )
    return _ok("create_shipment", resp)


def scan_shipment(shipment_id, scan_result):
    resp = api_client.scan_fixture_shipment(
        shipment_id, {"scan_result": scan_result}, PM
    )
    return _ok("scan_shipment", resp)


# ---------------------------------------------------------------------------
# Tier 4 — mileage logs
# ---------------------------------------------------------------------------

def submit_mileage_log(rep_id, assignment_id, **overrides):
    resp = api_client.create_mileage_log(
        create_mileage_log_payload(rep_id, assignment_id, **overrides),
        make_field_rep_headers(rep_id),
    )
    return _ok("submit_mileage_log", resp)


def setup_submitted_assignment_for_rep(rep_overrides=None, **scenario_kwargs):
    """One-rep one-store scenario with the visit driven to SUBMITTED so a
    mileage log against the assignment is in the payable input set
    (PRD 3.8: "only logs whose assignment has reached SUBMITTED or VERIFIED
    are payable"). Returns (scenario, assignment, visit)."""
    scn = make_scenario(
        num_stores=1, num_reps=1,
        rep_overrides_list=[rep_overrides or {}],
        **scenario_kwargs,
    )
    asg, visit = visit_store(scn)
    return scn, asg, visit


# ---------------------------------------------------------------------------
# Tier 5 — invoices and finalization
# ---------------------------------------------------------------------------

def get_invoice_for_project(project_id):
    """Exactly one invoice is expected; returns it."""
    data = _ok(
        "get_invoice_for_project",
        api_client.list_invoices(BC, params={"project_id": project_id}),
    )
    assert isinstance(data, list) and len(data) == 1, (
        f"Setup failed: expected exactly 1 invoice for project {project_id}, "
        f"got {len(data) if isinstance(data, list) else data}"
    )
    return data[0]


def create_invoice(client_id, project_id, **overrides):
    resp = api_client.create_invoice(
        create_invoice_payload(client_id, project_id, **overrides), BC
    )
    return _ok("create_invoice", resp)


def finalize_invoice(invoice_id, expected_version=None, adjustment_cents=None):
    if expected_version is None:
        expected_version = _ok(
            "get_invoice", api_client.get_invoice(invoice_id, BC)
        )["version"]
    payload = {"expected_invoice_version": expected_version}
    if adjustment_cents is not None:
        payload["adjustment_cents"] = adjustment_cents
    return _ok("finalize_invoice", api_client.finalize_invoice(invoice_id, payload, BC))


def void_invoice(invoice_id):
    return _ok("void_invoice", api_client.void_invoice(invoice_id, BC))


def setup_reconciling_project(**scenario_kwargs):
    """One-store project driven all the way to RECONCILING (visit verified,
    OPEN invoice auto-created). Returns (scenario, assignment, visit, invoice)."""
    scn = make_scenario(**scenario_kwargs)
    asg, visit = visit_store(scn, outcome="verify")
    invoice = get_invoice_for_project(scn["project"]["id"])
    return scn, asg, visit, invoice


def file_exception(visit_id, as_role="PM", **overrides):
    from .factories import create_exception_payload

    headers = PM if as_role == "PM" else PA
    resp = api_client.create_exception(
        visit_id, create_exception_payload(**overrides), headers
    )
    return _ok("file_exception", resp)

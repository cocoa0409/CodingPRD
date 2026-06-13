"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup failed" errors rather than confusing assertion failures.

Every test runs against a freshly-restarted empty server, so each fixture builds
all of its preconditions from scratch using only PRD-declared endpoints.

Identity threading: a Patron is entity_backed, so any ownership-gated call (renew,
cancel, return, book own resource) uses make_patron_headers(patron["id"]) — never
the shared TEST_USERS["patron_headers"] constant (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_branch_payload, create_patron_payload, create_title_payload,
    create_copy_payload, create_loan_payload, create_hold_payload,
    create_resource_payload, create_reservation_payload, create_ill_request_payload,
    create_license_pool_payload, create_ebook_loan_payload,
)
from .test_users import TEST_USERS, make_patron_headers

LIBRARIAN = TEST_USERS["librarian_headers"]
MANAGER = TEST_USERS["branch_manager_headers"]


# ─── Clock ────────────────────────────────────────────
def set_clock(iso: str):
    """Pin the server clock to an absolute UTC instant (PRD §2.11)."""
    return get_success_data(api_client.set_clock(iso, LIBRARIAN))


# ─── Tier 1: Primitive creators ───────────────────────
def create_branch(**overrides) -> dict:
    return get_success_data(api_client.create_branch(create_branch_payload(**overrides), MANAGER))


def create_patron(branch_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_patron(create_patron_payload(branch_id, **overrides), LIBRARIAN))


def create_title(branch_id: str, isbn: str = "9780000000000", **overrides) -> dict:
    return get_success_data(
        api_client.create_title(create_title_payload(branch_id, isbn, **overrides), LIBRARIAN))


def create_copy(title_id: str, branch_id: str, barcode: str = "BC-TEST",
                acquired_on: str = "2025-06-01T00:00:00Z", **overrides) -> dict:
    return get_success_data(api_client.create_copy(
        create_copy_payload(title_id, branch_id, barcode, acquired_on, **overrides), LIBRARIAN))


def create_resource(branch_id: str, resource_kind: str = "ROOM",
                    label: str = "Test Resource", **overrides) -> dict:
    return get_success_data(api_client.create_resource(
        create_resource_payload(branch_id, resource_kind, label, **overrides), MANAGER))


def create_license_pool(title_id: str, total_licenses: int = 1, **overrides) -> dict:
    return get_success_data(api_client.create_license_pool(
        create_license_pool_payload(title_id, total_licenses, **overrides), LIBRARIAN))


# ─── Tier 2: Entity hierarchy for circulation ─────────
def setup_branch_patron_title_copy(branch_overrides=None, isbn="9780000000000",
                                   title_overrides=None, copy_overrides=None,
                                   patron_overrides=None, barcode="BC-1",
                                   clock=None):
    """Active branch + patron + title + one AVAILABLE copy.
    Returns (branch, patron, title, copy). Optionally pins the clock first.
    """
    branch = create_branch(**(branch_overrides or {}))
    if clock:
        set_clock(clock)
    patron = create_patron(branch["id"], **(patron_overrides or {}))
    title = create_title(branch["id"], isbn, **(title_overrides or {}))
    copy = create_copy(title["id"], branch["id"], barcode,
                       **(copy_overrides or {}))
    return branch, patron, title, copy


def create_loan(copy_id: str, patron_id: str) -> dict:
    """Librarian checkout (PRD §3.3)."""
    return get_success_data(api_client.create_loan(
        create_loan_payload(copy_id, patron_id), LIBRARIAN))


def setup_active_loan(branch_overrides=None, isbn="9780000000000",
                      title_overrides=None, copy_overrides=None,
                      patron_overrides=None, clock="2026-06-01T00:00:00Z",
                      barcode="BC-1"):
    """Branch + patron + title + copy + one ACTIVE loan.
    Returns (branch, patron, title, copy, loan).
    """
    branch, patron, title, copy = setup_branch_patron_title_copy(
        branch_overrides=branch_overrides, isbn=isbn, title_overrides=title_overrides,
        copy_overrides=copy_overrides, patron_overrides=patron_overrides,
        barcode=barcode, clock=clock)
    loan = create_loan(copy["id"], patron["id"])
    return branch, patron, title, copy, loan


# ─── Tier 3: Fine / block setups ──────────────────────
def setup_blocked_patron_via_lost(block_threshold_cents=1000,
                                  default_replacement_cents=2000,
                                  clock="2026-06-01T00:00:00Z",
                                  isbn="9780000000040"):
    """Create a patron BLOCKED by a single flat LOST fine, by declaring a loaned
    copy lost with flat_replacement=true. The flat charge is
    default_replacement_cents + round(default_replacement_cents * 0.10).
    Returns (branch, patron, title, copy, loan_now_lost).
    """
    branch, patron, title, copy, loan = setup_active_loan(
        branch_overrides={"loan_period_days": 7, "block_threshold_cents": block_threshold_cents},
        isbn=isbn,
        title_overrides={"default_replacement_cents": default_replacement_cents},
        copy_overrides={"acquired_on": "2026-06-01T00:00:00Z", "condition_factor": 1.0},
        clock=clock, barcode="BC-BLK")
    get_success_data(api_client.declare_lost(loan["id"], LIBRARIAN, {"flat_replacement": True}))
    return branch, patron, title, copy, loan


def get_only_unpaid_fine(patron_id: str) -> dict:
    """Return the patron's single UNPAID fine (PRD §3.10 list filter)."""
    res = api_client.list_fines(LIBRARIAN, params={"patron_id": patron_id,
                                                   "settlement_status": "UNPAID"})
    data = get_success_data(res)
    rows = data if isinstance(data, list) else data.get("data", data)
    return rows[0]


def list_unpaid_fines(patron_id: str) -> list:
    res = api_client.list_fines(LIBRARIAN, params={"patron_id": patron_id,
                                                  "settlement_status": "UNPAID"})
    data = get_success_data(res)
    return data if isinstance(data, list) else data.get("data", data)


# ─── Tier 4: Hold / promotion setups ──────────────────
def setup_loan_with_waiting_hold(clock="2026-06-01T00:00:00Z", isbn="9780000000041",
                                 hold_patron_overrides=None):
    """Title with one copy ON_LOAN to patron A; patron B holds a WAITING hold
    (queue head). Returns (branch, patron_a, patron_b, title, copy, loan, hold).
    """
    branch = create_branch(loan_period_days=7)
    set_clock(clock)
    patron_a = create_patron(branch["id"], full_name="Patron A")
    patron_b = create_patron(branch["id"], full_name="Patron B", **(hold_patron_overrides or {}))
    title = create_title(branch["id"], isbn, title_text="Hot Book")
    copy = create_copy(title["id"], branch["id"], "BC-HOLD")
    loan = create_loan(copy["id"], patron_a["id"])
    hold = get_success_data(api_client.create_hold(
        create_hold_payload(title["id"], patron_b["id"]), make_patron_headers(patron_b["id"])))
    return branch, patron_a, patron_b, title, copy, loan, hold


# ─── Tier 5: Reservation setups ───────────────────────
def create_reservation(resource_id, patron_id, start_at, end_at,
                       expected_resource_version, patron_headers=None):
    """Patron-owned reservation create (OCC). patron_headers must be the owning
    patron's entity-backed headers (PRD §2.1, §2.9)."""
    headers = patron_headers if patron_headers is not None else TEST_USERS["patron_headers"]
    return get_success_data(api_client.create_reservation(
        create_reservation_payload(resource_id, patron_id, start_at, end_at,
                                   expected_resource_version),
        headers))


def setup_room_with_confirmed_reservation(buffer_minutes=15,
                                          clock_before="2026-06-01T09:00:00Z",
                                          start_at="2026-06-01T10:00:00Z",
                                          end_at="2026-06-01T11:00:00Z"):
    """IN_SERVICE ROOM with one CONFIRMED reservation in [start_at, end_at).
    Returns (branch, patron, resource, reservation).
    """
    branch = create_branch(reservation_buffer_minutes=buffer_minutes)
    patron = create_patron(branch["id"], full_name="Res Pat")
    resource = create_resource(branch["id"], "ROOM", "Study Room A")
    set_clock(clock_before)
    reservation = create_reservation(
        resource["id"], patron["id"], start_at, end_at, resource["version"],
        patron_headers=make_patron_headers(patron["id"]))
    get_success_data(api_client.confirm_reservation(reservation["id"], LIBRARIAN))
    return branch, patron, resource, reservation


def current_resource_version(resource_id: str) -> int:
    """Re-read the resource to get its current version for the next sequential
    OCC write (PRD §2.9)."""
    return get_success_data(api_client.get_resource(resource_id, LIBRARIAN))["version"]


# ─── Tier 6: E-book setups ────────────────────────────
def setup_pool_with_active_ebook_loan(total_licenses=1, clock="2026-06-01T00:00:00Z",
                                      isbn="9780000000042", loan_term_days=14):
    """License pool with one ACTIVE ebook loan consuming a license.
    Returns (branch, patron, title, pool, ebook_loan).
    """
    branch = create_branch(loan_period_days=7)
    set_clock(clock)
    patron = create_patron(branch["id"], full_name="Ebook Pat")
    title = create_title(branch["id"], isbn, title_text="Ebook Title")
    pool = create_license_pool(title["id"], total_licenses, loan_term_days=loan_term_days)
    ebook_loan = get_success_data(api_client.create_ebook_loan(
        create_ebook_loan_payload(pool["id"], patron["id"]), make_patron_headers(patron["id"])))
    return branch, patron, title, pool, ebook_loan

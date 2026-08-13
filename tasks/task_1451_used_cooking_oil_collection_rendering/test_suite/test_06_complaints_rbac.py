"""Complaint workflow, reopen window, lazy auto-close, and RBAC scoping."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_complaint_payload,
    create_customer,
    get_success_data,
    make_customer_contact_headers,
    set_clock,
    setup_reconciled_manifest,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import BILL, DISP, FOPS


# ---------------------------------------------------------------------------
# Corner: CustomerContact files a complaint for its own customer
# ---------------------------------------------------------------------------

def test_customer_contact_files_own_complaint(api, field_ops_headers):
    """PRD §3.8: "New complaints start in `OPEN` status."
    PRD §3.8: "A complaint is filed by a `CustomerContact` or a
    `FieldOpsManager` with a `customer_id`, a `category` of `SPILL`, `ODOR`,
    `NUISANCE`, or `THEFT_ATTEMPT`, a `severity` of `LOW`, `MEDIUM`, or `HIGH`,
    and a free-text `note`."

    Design: Corner/rbac/c_customer_contact_files_own_complaint
    """
    customer = create_customer(name="Voice House", address="45 Fry Way")
    resp = api.create_complaint(
        create_complaint_payload(
            customer_id=customer["id"],
            category="NUISANCE",
            severity="LOW",
            note="pickup truck idles at 5am",
        ),
        make_customer_contact_headers(customer["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "OPEN"
    assert data["customer_id"] == customer["id"]


# ---------------------------------------------------------------------------
# Corner: CustomerContact ownership scoping on reads
# ---------------------------------------------------------------------------

def test_customer_contact_cannot_read_other_customer(api, field_ops_headers):
    """PRD §2.1: "a `CustomerContact` may act only on resources belonging to
    the customer whose `id` equals the caller's `X-User-ID`; filing a complaint
    whose `customer_id` differs from the caller's `X-User-ID`, for instance, is
    rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/c_customer_contact_cannot_read_other_customer
    """
    cust_a = create_customer(name="Own A", address="42 Fry Way")
    cust_b = create_customer(name="Other B", address="43 Fry Way")
    resp = api.get_customer(cust_b["id"], make_customer_contact_headers(cust_a["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
    ok = get_success_data(
        api.get_customer(cust_a["id"], make_customer_contact_headers(cust_a["id"]))
    )
    assert ok["id"] == cust_a["id"]


# ---------------------------------------------------------------------------
# Corner: reopen window expiry + lazy auto-close
# ---------------------------------------------------------------------------

def _resolved_complaint(api, name="Window House", address="51 Fry Way"):
    set_clock("2026-08-02T00:00:00Z")
    customer = create_customer(name=name, address=address)
    complaint = get_success_data(
        api.create_complaint(
            create_complaint_payload(
                customer_id=customer["id"],
                category="ODOR",
                severity="MEDIUM",
                note="weekend smell",
            ),
            make_customer_contact_headers(customer["id"]),
        )
    )
    get_success_data(api.investigate_complaint(complaint["id"], FOPS))
    resolved = get_success_data(
        api.resolve_complaint(
            complaint["id"], {"resolution_note": "lid replaced"}, FOPS
        )
    )
    return customer, complaint, resolved


def test_complaint_reopen_after_window_rejected(api):
    """PRD §3.8: "The customer may reopen a resolved complaint within seven
    days of `resolved_at` — the logical clock must be no later than seven days
    after resolution; a later attempt is rejected with
    `ERR_COMPLAINT_REOPEN_WINDOW_EXPIRED`."
    PRD §3.8: "Complaints close lazily per §2.4: on any read or write once the
    logical clock is strictly more than seven days after `resolved_at`, a
    `RESOLVED` complaint transitions to `CLOSED`, its terminal state."

    Design: Corner/errors/c_complaint_reopen_after_window_rejected
    """
    customer, complaint, _ = _resolved_complaint(api)
    set_clock("2026-08-20T00:00:00Z")
    resp = api.reopen_complaint(
        complaint["id"], {"note": "smell again"},
        make_customer_contact_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COMPLAINT_REOPEN_WINDOW_EXPIRED,
                   expected_status=422)
    listed = get_success_data(api.list_customer_complaints(customer["id"], FOPS))
    assert listed[0]["status"] == "CLOSED", (
        "lazy auto-close applies once the window has fully elapsed"
    )


# ---------------------------------------------------------------------------
# Difficulty: complaint reopen recurrence cycle
# ---------------------------------------------------------------------------

def test_complaint_reopen_increments_reopen_count(api):
    """PRD §3.8: "Reopening records a fresh `note`, moves the complaint
    `RESOLVED` → `REOPENED`, and increments `reopen_count`."

    Design: Difficulty/non_linear_state_machine/complaint_reopen_recurrence_cycle
    """
    customer, complaint, _ = _resolved_complaint(
        api, name="Smelly House", address="7 Fry Way"
    )
    set_clock("2026-08-05T00:00:00Z")  # within 7 days of the 08-02 resolution
    reopened = get_success_data(
        api.reopen_complaint(
            complaint["id"], {"note": "smell returned"},
            make_customer_contact_headers(customer["id"]),
        )
    )
    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 1


def test_complaint_cycle_terminates_in_lazy_closed(api):
    """PRD §3.8: "From `REOPENED` the workflow re-enters investigation, so the
    `RESOLVED` → `REOPENED` → `INVESTIGATING` → `RESOLVED` recurrence loop may
    repeat."
    PRD §3.8: "Complaints close lazily per §2.4: on any read or write once the
    logical clock is strictly more than seven days after `resolved_at`, a
    `RESOLVED` complaint transitions to `CLOSED`, its terminal state."

    Design: Difficulty/non_linear_state_machine/complaint_reopen_recurrence_cycle
    """
    customer, complaint, _ = _resolved_complaint(
        api, name="Smelly House", address="7 Fry Way"
    )
    set_clock("2026-08-05T00:00:00Z")
    get_success_data(
        api.reopen_complaint(
            complaint["id"], {"note": "smell returned"},
            make_customer_contact_headers(customer["id"]),
        )
    )
    get_success_data(api.investigate_complaint(complaint["id"], FOPS))
    get_success_data(
        api.resolve_complaint(
            complaint["id"], {"resolution_note": "replaced lid gasket"}, FOPS
        )
    )
    set_clock("2026-08-20T00:00:00Z")  # > resolved_at (08-05) + 7 days
    listed = get_success_data(api.list_customer_complaints(customer["id"], FOPS))
    assert listed[0]["status"] == "CLOSED"


# ---------------------------------------------------------------------------
# Corner: spill complaint gates processing-batch intake
# ---------------------------------------------------------------------------

def test_spill_complaint_blocks_batch_intake(api, plant_headers):
    """PRD §3.8: "Tipping a reconciled manifest into a processing batch is
    blocked with `ERR_SPILL_COMPLAINT_OPEN` while any `SPILL`-category
    complaint linked to one of the manifest's pickups is `OPEN`,
    `INVESTIGATING`, `ESCALATED`, or `REOPENED`. Spill complaints that have
    reached `RESOLVED` or `CLOSED` do not block intake."

    Batch after resolve: est_yield 100 x (1 - 5.0/100) x 0.92 == 87.40.

    Design: Corner/endpoints/c_spill_complaint_blocks_batch_intake
    """
    ctx = setup_reconciled_manifest(
        name="Spill House", truck_plate="T-C18",
        container_capacity=300, container_fill_rate=100,
        tank_capacity=500,
        pump_gallons=100.00, field_moisture_pct=5.0,
    )
    complaint = get_success_data(
        api.create_complaint(
            create_complaint_payload(
                customer_id=ctx["customer"]["id"],
                category="SPILL",
                severity="HIGH",
                note="oil on loading dock",
                pickup_visit_id=ctx["visit"]["id"],
            ),
            make_customer_contact_headers(ctx["customer"]["id"]),
        )
    )
    resp = api.create_processing_batch(
        {"manifest_id": ctx["manifest"]["id"], "input_gallons": 100},
        plant_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SPILL_COMPLAINT_OPEN, expected_status=422)
    get_success_data(api.investigate_complaint(complaint["id"], FOPS))
    get_success_data(
        api.resolve_complaint(
            complaint["id"], {"resolution_note": "cleanup verified"}, FOPS
        )
    )
    batch = get_success_data(
        api.create_processing_batch(
            {"manifest_id": ctx["manifest"]["id"], "input_gallons": 100},
            plant_headers,
        )
    )
    assert batch["est_yield_gallons"] == pytest.approx(87.40, abs=0.001)

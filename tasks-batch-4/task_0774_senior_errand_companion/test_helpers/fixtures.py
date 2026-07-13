"""Composite setup helpers.

Because the test harness restarts the server (empty DB) before every test, every
helper builds its preconditions from scratch using only PRD-declared endpoints.
Helpers use get_success_data() (lenient) so a setup failure surfaces clearly.

Identity threading: after a Caregiver entity is created, ownership-gated calls
(clock-in/out, escalate, log) use make_caregiver_headers(caregiver["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_caregiver_headers, make_family_contact_headers
from .factories import (
    create_client_payload,
    create_caregiver_payload,
    background_check_decision_payload,
    create_bond_payload,
    create_schedule_payload,
    create_ltc_policy_payload,
    create_visit_payload,
    create_assignment_payload,
    create_addon_payload,
    create_family_contact_payload,
)
from .constants import FAR_FUTURE

COORD = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]


# --------------------------------------------------------------------------
# Primitive building blocks
# --------------------------------------------------------------------------
def set_clock(api, iso: str):
    """Advance the logical clock to the supplied instant."""
    return get_success_data(api.set_clock(iso, COORD))


def create_client(api, **overrides) -> dict:
    return get_success_data(api.create_client(create_client_payload(**overrides), COORD))


def create_caregiver(api, **overrides) -> dict:
    return get_success_data(api.create_caregiver(create_caregiver_payload(**overrides), COORD))


def create_cleared_bonded_caregiver(
    api,
    name="Test Caregiver",
    check_expires_at=FAR_FUTURE,
    bond_effective="2026-01-01T00:00:00Z",
    bond_expiry="2027-01-01T00:00:00Z",
) -> dict:
    """Create a caregiver, open + CLEAR a background check, and record an ACTIVE
    bond. Returns the caregiver dict (with id). The credentials are in force at
    the default clock unless the caller overrides the windows."""
    caregiver = create_caregiver(api, name=name)
    cg_id = caregiver["id"]
    check = get_success_data(api.create_background_check(cg_id, {}, COORD))
    get_success_data(
        api.background_check_decision(
            check["id"],
            background_check_decision_payload(outcome="CLEARED", expires_at=check_expires_at),
            COORD,
        )
    )
    get_success_data(
        api.create_bond(
            cg_id,
            create_bond_payload(effective_date=bond_effective, expiry_date=bond_expiry),
            COORD,
        )
    )
    return caregiver


def create_visit(api, client_id, **overrides) -> dict:
    return get_success_data(api.create_visit(create_visit_payload(client_id, **overrides), COORD))


def assign_caregiver(api, visit_id, caregiver_id, expected_visit_version) -> dict:
    return get_success_data(
        api.create_assignment(
            visit_id,
            create_assignment_payload(caregiver_id, expected_visit_version),
            COORD,
        )
    )


def clock_in_visit(api, visit_id, caregiver_id, actual_start):
    return get_success_data(
        api.clock_in(visit_id, {"actual_start": actual_start}, make_caregiver_headers(caregiver_id))
    )


def clock_out_visit(api, visit_id, caregiver_id, actual_end, mileage_miles):
    return get_success_data(
        api.clock_out(
            visit_id,
            {"actual_end": actual_end, "mileage_miles": mileage_miles},
            make_caregiver_headers(caregiver_id),
        )
    )


def get_invoice_for_visit(api, visit_id) -> dict:
    """Fetch the single DRAFT invoice created for a completed visit."""
    resp = api.list_invoices(BILLING, params={"visit_id": visit_id})
    data = get_success_data(resp)
    assert isinstance(data, list) and len(data) >= 1, f"expected an invoice for visit {visit_id}"
    return data[0]


# --------------------------------------------------------------------------
# Tier: completed-visit lifecycle shortcuts
# --------------------------------------------------------------------------
def setup_completed_visit(
    api,
    client_overrides=None,
    scheduled_start="2026-03-05T09:00:00Z",
    scheduled_end="2026-03-05T12:00:00Z",
    actual_start="2026-03-05T09:00:00Z",
    actual_end="2026-03-05T12:00:00Z",
    mileage_miles=0,
    task_type="COMPANION",
    approved_addons=None,
    requested_addons=None,
) -> dict:
    """Full path: cleared bonded caregiver + client + ad-hoc visit + assignment +
    (optional add-ons) + clock-in + clock-out + fetch DRAFT invoice.

    approved_addons / requested_addons: lists of (addon_type, fee_cents) tuples.
    Approved ones are requested THEN approved; requested ones stay REQUESTED.
    Returns dict with caregiver, client, visit, assignment, invoice, addon ids.
    """
    client_overrides = client_overrides or {}
    caregiver = create_cleared_bonded_caregiver(api)
    client = create_client(api, **client_overrides)
    visit = create_visit(
        api,
        client["id"],
        task_type=task_type,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
    )
    assignment = assign_caregiver(api, visit["id"], caregiver["id"], visit["version"])

    addon_ids = []
    for addon_type, fee in (approved_addons or []):
        addon = get_success_data(
            api.create_addon(visit["id"], create_addon_payload(addon_type=addon_type, fee_cents=fee), COORD)
        )
        get_success_data(api.approve_addon(addon["id"], {"outcome": "APPROVE"}, COORD))
        addon_ids.append(addon["id"])
    for addon_type, fee in (requested_addons or []):
        addon = get_success_data(
            api.create_addon(visit["id"], create_addon_payload(addon_type=addon_type, fee_cents=fee), COORD)
        )
        addon_ids.append(addon["id"])

    clock_in_visit(api, visit["id"], caregiver["id"], actual_start)
    clock_out_visit(api, visit["id"], caregiver["id"], actual_end, mileage_miles)
    invoice = get_invoice_for_visit(api, visit["id"])
    return {
        "caregiver": caregiver,
        "client": client,
        "visit": visit,
        "assignment": assignment,
        "addon_ids": addon_ids,
        "invoice": invoice,
    }


def setup_finalized_invoice(api, **kwargs) -> dict:
    """setup_completed_visit + finalize the invoice. Returns the same dict with
    the invoice refreshed to FINALIZED."""
    ctx = setup_completed_visit(api, **kwargs)
    ctx["invoice"] = get_success_data(api.finalize_invoice(ctx["invoice"]["id"], BILLING))
    return ctx


def attach_ltc_policy(api, client_id, **policy_overrides) -> dict:
    return get_success_data(api.create_ltc_policy(client_id, create_ltc_policy_payload(**policy_overrides), COORD))


def setup_finalized_invoice_with_policy(api, policy_overrides=None, **completed_kwargs) -> dict:
    """Finalized invoice + one LTC policy attached to the same client. Returns the
    setup dict augmented with a `policy` key."""
    ctx = setup_finalized_invoice(api, **completed_kwargs)
    ctx["policy"] = attach_ltc_policy(api, ctx["client"]["id"], **(policy_overrides or {}))
    return ctx


def setup_submitted_claim(api, policy_overrides=None, **completed_kwargs) -> dict:
    """Finalized invoice + policy + a claim opened and submitted. Returns the setup
    dict augmented with `policy` and `claim`."""
    ctx = setup_finalized_invoice_with_policy(api, policy_overrides=policy_overrides, **completed_kwargs)
    claim = get_success_data(api.create_claim(ctx["invoice"]["id"], {"ltc_policy_id": ctx["policy"]["id"]}, BILLING))
    ctx["claim"] = get_success_data(api.submit_claim(claim["id"], BILLING))
    return ctx


# --------------------------------------------------------------------------
# Tier: state-progression shortcuts stopping mid-lifecycle
# --------------------------------------------------------------------------
def setup_in_progress_visit(
    api,
    client_overrides=None,
    scheduled_start="2026-03-05T09:00:00Z",
    scheduled_end="2026-03-05T12:00:00Z",
    actual_start="2026-03-05T09:00:00Z",
) -> dict:
    """Cleared bonded caregiver assigned to a visit, then clocked in (IN_PROGRESS).
    Returns dict with caregiver, client, visit, assignment."""
    client_overrides = client_overrides or {}
    caregiver = create_cleared_bonded_caregiver(api)
    client = create_client(api, **client_overrides)
    visit = create_visit(
        api, client["id"], scheduled_start=scheduled_start, scheduled_end=scheduled_end
    )
    assignment = assign_caregiver(api, visit["id"], caregiver["id"], visit["version"])
    clock_in_visit(api, visit["id"], caregiver["id"], actual_start)
    return {"caregiver": caregiver, "client": client, "visit": visit, "assignment": assignment}


def setup_assigned_visit(
    api,
    client_overrides=None,
    scheduled_start="2026-03-05T09:00:00Z",
    scheduled_end="2026-03-05T12:00:00Z",
    caregiver_check_expires_at=FAR_FUTURE,
) -> dict:
    """Cleared bonded caregiver assigned to a SCHEDULED visit (not clocked in).
    Returns dict with caregiver, client, visit, assignment."""
    client_overrides = client_overrides or {}
    caregiver = create_cleared_bonded_caregiver(api, check_expires_at=caregiver_check_expires_at)
    client = create_client(api, **client_overrides)
    visit = create_visit(
        api, client["id"], scheduled_start=scheduled_start, scheduled_end=scheduled_end
    )
    assignment = assign_caregiver(api, visit["id"], caregiver["id"], visit["version"])
    return {"caregiver": caregiver, "client": client, "visit": visit, "assignment": assignment}


def setup_family_contact(api, client_id, **overrides) -> dict:
    """Register a FamilyContact against a client. Returns the contact dict."""
    return get_success_data(
        api.create_family_contact(client_id, create_family_contact_payload(**overrides), COORD)
    )


def setup_active_schedule(api, client_overrides=None, schedule_overrides=None) -> dict:
    """Active client with an ACTIVE recurring schedule. Returns dict with client
    and schedule."""
    client = create_client(api, **(client_overrides or {}))
    schedule = get_success_data(
        api.create_schedule(client["id"], create_schedule_payload(**(schedule_overrides or {})), COORD)
    )
    return {"client": client, "schedule": schedule}

"""Composite setup helpers.

Every test runs against an empty database (the runner restarts the server
per test), so each helper builds its preconditions from scratch using only
endpoints the PRD declares. Setup calls use the lenient `get_success_data`
validator so a broken precondition surfaces as a clear "Setup step failed"
rather than a confusing assertion later.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_appraiser_payload,
    create_client_payload,
    create_comparable_payload,
    create_complaint_payload,
    create_fee_adjustment_payload,
    create_fee_schedule_payload,
    create_order_payload,
    create_panel_membership_payload,
    create_report_payload,
    create_revision_request_payload,
    create_trainee_payload,
    create_workfile_record_payload,
)
from .test_users import (
    TEST_USERS,
    make_appraiser_headers,
    make_clientuser_headers,
    make_qc_reviewer_headers,
)

ADMIN = TEST_USERS["firm_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

# The canonical three-comparable set used across fixtures: adjusted prices
# 44500000 / 45700000 / 45000000 with distance weights 3 / 2 / 1, giving the
# value conclusion 45000000 after the single final rounding (PRD 3.6).
STANDARD_COMP_ARGS: List[Dict[str, Any]] = [
    {
        "address": "1 Pine St",
        "sale_price_cents": 44000000,
        "sale_date": "2026-06-15",
        "distance_miles": 0.40,
        "site_adjustment_cents": 500000,
        "gla_adjustment_cents": 0,
        "condition_adjustment_cents": 0,
    },
    {
        "address": "2 Pine St",
        "sale_price_cents": 46000000,
        "sale_date": "2026-06-10",
        "distance_miles": 0.80,
        "site_adjustment_cents": 0,
        "gla_adjustment_cents": 0,
        "condition_adjustment_cents": -300000,
    },
    {
        "address": "3 Pine St",
        "sale_price_cents": 45000000,
        "sale_date": "2026-05-20",
        "distance_miles": 1.20,
        "site_adjustment_cents": 0,
        "gla_adjustment_cents": 0,
        "condition_adjustment_cents": 0,
    },
]


# ---------------------------------------------------------------------------
# Tier 0 — primitive steps
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock (FirmAdmin only, PRD 2.4)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_client(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_client(create_client_payload(**overrides), ADMIN))


def get_client(client_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_client(client_id, ADMIN))


def create_appraiser(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_appraiser(create_appraiser_payload(**overrides), ADMIN)
    )


def create_trainee(supervisor_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_appraiser(
            create_trainee_payload(supervisor_id, **overrides), ADMIN
        )
    )


def create_membership(client_id: str, appraiser_id: str) -> Dict[str, Any]:
    payload = create_panel_membership_payload(client_id, appraiser_id)
    return get_success_data(api_client.create_panel_membership(payload, ADMIN))


def create_fee_schedule(client_id: str, **overrides) -> Dict[str, Any]:
    """Create a fee window; the client version is re-read first so the OCC
    field always matches (PRD 2.8)."""
    version = get_client(client_id)["version"]
    payload = create_fee_schedule_payload(client_id, version, **overrides)
    return get_success_data(api_client.create_fee_schedule(payload, ADMIN))


def create_order(client_id: str, **overrides) -> Dict[str, Any]:
    """Place an order as the owning ClientUser (client_id == X-User-ID)."""
    payload = create_order_payload(client_id, **overrides)
    return get_success_data(
        api_client.create_order(payload, make_clientuser_headers(client_id))
    )


def get_order(order_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_order(order_id, ADMIN))


def scope_order(order_id: str, **payload) -> Dict[str, Any]:
    return get_success_data(api_client.determine_scope(order_id, payload, ADMIN))


def accept_order(order_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.accept_order(order_id, {}, ADMIN))


def assign_order(order_id: str, appraiser_id: Optional[str] = None) -> Dict[str, Any]:
    payload = {} if appraiser_id is None else {"appraiser_id": appraiser_id}
    return get_success_data(api_client.assign_order(order_id, payload, ADMIN))


def cancel_order(order_id: str, reason: str = "withdrawn") -> Dict[str, Any]:
    return get_success_data(api_client.cancel_order(order_id, {"reason": reason}, ADMIN))


def start_analysis(order_id: str, appraiser_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.start_analysis(order_id, make_appraiser_headers(appraiser_id))
    )


def create_appointment(
    order_id: str,
    appraiser_id: str,
    window_start: str,
    window_end: str,
    as_admin: bool = False,
) -> Dict[str, Any]:
    payload = {
        "order_id": order_id,
        "appraiser_id": appraiser_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    headers = ADMIN if as_admin else make_appraiser_headers(appraiser_id)
    return get_success_data(api_client.create_appointment(payload, headers))


def confirm_appointment(appointment_id: str, appraiser_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.confirm_appointment(
            appointment_id, make_appraiser_headers(appraiser_id)
        )
    )


def create_comparable(order_id: str, appraiser_id: str, **overrides) -> Dict[str, Any]:
    payload = create_comparable_payload(order_id, **overrides)
    return get_success_data(
        api_client.create_comparable(payload, make_appraiser_headers(appraiser_id))
    )


def verify_comparable(comparable_id: str, appraiser_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.verify_comparable(
            comparable_id, make_appraiser_headers(appraiser_id)
        )
    )


def lock_comparable(comparable_id: str, appraiser_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.lock_comparable(comparable_id, make_appraiser_headers(appraiser_id))
    )


def create_report(order_id: str, appraiser_id: str, **overrides) -> Dict[str, Any]:
    payload = create_report_payload(order_id, **overrides)
    return get_success_data(
        api_client.create_report(payload, make_appraiser_headers(appraiser_id))
    )


def submit_for_qc(report_id: str, appraiser_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_report_for_qc(
            report_id, make_appraiser_headers(appraiser_id)
        )
    )


def qc_pass(report_id: str, reviewer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.qc_pass_report(report_id, make_qc_reviewer_headers(reviewer_id))
    )


def deliver_report(report_id: str, appraiser_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.deliver_report(report_id, make_appraiser_headers(appraiser_id))
    )


def create_revision_request(
    order_id: str, client_id: str, **overrides
) -> Dict[str, Any]:
    """Open a revision request as the owning ClientUser; the order version is
    re-read first so the OCC field matches (PRD 2.8)."""
    version = get_order(order_id)["version"]
    payload = create_revision_request_payload(version, **overrides)
    return get_success_data(
        api_client.create_revision_request(
            order_id, payload, make_clientuser_headers(client_id)
        )
    )


def accept_revision(request_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.accept_revision_request(request_id, ADMIN))


def rebut_revision(request_id: str, rebuttal: str = "Original stands") -> Dict[str, Any]:
    return get_success_data(
        api_client.rebut_revision_request(request_id, {"rebuttal": rebuttal}, ADMIN)
    )


def create_workfile(order_id: str, snapshot_type: str = "COMP_DATA") -> Dict[str, Any]:
    return get_success_data(
        api_client.create_workfile_record(
            create_workfile_record_payload(order_id, snapshot_type), ADMIN
        )
    )


def list_workfiles(order_id: str, snapshot_type: Optional[str] = None) -> List[Dict]:
    params: Dict[str, Any] = {"order_id": order_id}
    if snapshot_type:
        params["snapshot_type"] = snapshot_type
    return get_success_data(api_client.list_workfile_records(COMPLIANCE, params=params))


def first_workfile_of_type(order_id: str, snapshot_type: str) -> Dict[str, Any]:
    records = list_workfiles(order_id, snapshot_type)
    assert records, f"expected at least one {snapshot_type} workfile for {order_id}"
    return records[0]


def create_complaint(order_id: str, respondent_appraiser_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_complaint(
            create_complaint_payload(order_id, respondent_appraiser_id), COMPLIANCE
        )
    )


def draft_complaint(complaint_id: str, text: str = "Response package") -> Dict[str, Any]:
    return get_success_data(
        api_client.draft_complaint_response(
            complaint_id, {"response_text": text}, COMPLIANCE
        )
    )


def submit_complaint(complaint_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.submit_complaint_response(complaint_id, COMPLIANCE))


def close_complaint(complaint_id: str, outcome: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.close_complaint(complaint_id, {"outcome": outcome}, COMPLIANCE)
    )


def get_scorecard(appraiser_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_scorecard(appraiser_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1/2 — order progression composites
# ---------------------------------------------------------------------------


def setup_accepted_order(
    desktop: bool = True,
    with_appraiser: bool = True,
    with_membership: bool = True,
    order_overrides: Optional[Dict[str, Any]] = None,
    schedule_overrides: Optional[Dict[str, Any]] = None,
    appraiser_overrides: Optional[Dict[str, Any]] = None,
    with_reviewer: bool = False,
    clock: str = "2026-08-01T00:00:00Z",
) -> Dict[str, Any]:
    """Client + STANDARD fee window + (optionally) appraiser/membership +
    order scoped (desktop by default) and accepted.

    Returns a context dict with the created entities and the headers to use
    for ownership-gated follow-up calls.
    """
    set_clock(clock)
    client = create_client()
    schedule = create_fee_schedule(client["id"], **(schedule_overrides or {}))
    appraiser = reviewer = membership = None
    if with_appraiser:
        appraiser = create_appraiser(**(appraiser_overrides or {}))
        if with_membership:
            membership = create_membership(client["id"], appraiser["id"])
    if with_reviewer:
        reviewer = create_appraiser(
            full_name="Quinn Reviewer", license_number="CR-7777"
        )
    order = create_order(client["id"], **(order_overrides or {}))
    scope_payload: Dict[str, Any] = {"requires_inspection": False} if desktop else {}
    order = scope_order(order["id"], **scope_payload)
    order = accept_order(order["id"])
    return {
        "client": client,
        "schedule": schedule,
        "appraiser": appraiser,
        "reviewer": reviewer,
        "membership": membership,
        "order": order,
        "client_headers": make_clientuser_headers(client["id"]),
        "appraiser_headers": (
            make_appraiser_headers(appraiser["id"]) if appraiser else None
        ),
        "reviewer_headers": (
            make_qc_reviewer_headers(reviewer["id"]) if reviewer else None
        ),
    }


def setup_assigned_order(**kwargs) -> Dict[str, Any]:
    """Accepted order assigned to the fixture appraiser (ASSIGNED)."""
    ctx = setup_accepted_order(**kwargs)
    ctx["order"] = assign_order(ctx["order"]["id"], ctx["appraiser"]["id"])
    return ctx


def setup_order_in_analysis(**kwargs) -> Dict[str, Any]:
    """Order walked to IN_ANALYSIS (desktop path: ASSIGNED -> IN_ANALYSIS)."""
    ctx = setup_assigned_order(**kwargs)
    ctx["order"] = start_analysis(ctx["order"]["id"], ctx["appraiser"]["id"])
    return ctx


def add_locked_comp(ctx: Dict[str, Any], **comp_overrides) -> Dict[str, Any]:
    comp = create_comparable(
        ctx["order"]["id"], ctx["appraiser"]["id"], **comp_overrides
    )
    verify_comparable(comp["id"], ctx["appraiser"]["id"])
    return lock_comparable(comp["id"], ctx["appraiser"]["id"])


def add_standard_locked_comps(ctx: Dict[str, Any], count: int = 3) -> List[Dict[str, Any]]:
    """Create/verify/lock the first ``count`` comps of the canonical triple."""
    comps = []
    for args in STANDARD_COMP_ARGS[:count]:
        comps.append(add_locked_comp(ctx, **args))
    ctx["comps"] = comps
    return comps


def setup_order_with_report(**kwargs) -> Dict[str, Any]:
    """Order in DRAFTING with its report (order + 3 locked comps + create)."""
    ctx = setup_order_in_analysis(**kwargs)
    ctx["comps"] = add_standard_locked_comps(ctx)
    ctx["report"] = create_report(ctx["order"]["id"], ctx["appraiser"]["id"])
    return ctx


def setup_report_pending_qc(**kwargs) -> Dict[str, Any]:
    """Report PENDING_QC; order QC_REVIEW; a certified reviewer exists."""
    kwargs["with_reviewer"] = True
    ctx = setup_order_with_report(**kwargs)
    ctx["report"] = submit_for_qc(ctx["report"]["id"], ctx["appraiser"]["id"])
    return ctx


def setup_report_qc_passed(**kwargs) -> Dict[str, Any]:
    """Report QC_PASSED by the fixture reviewer."""
    ctx = setup_report_pending_qc(**kwargs)
    ctx["report"] = qc_pass(ctx["report"]["id"], ctx["reviewer"]["id"])
    return ctx


def setup_delivered_order(
    delivery_clock: str = "2026-08-02T00:00:00Z", **kwargs
) -> Dict[str, Any]:
    """Full happy path through first delivery at ``delivery_clock``.

    Order DELIVERED, report DELIVERED, retention pinned, REPORT_PDF and
    CERTIFICATION workfiles filed.
    """
    ctx = setup_report_qc_passed(**kwargs)
    set_clock(delivery_clock)
    ctx["report"] = deliver_report(ctx["report"]["id"], ctx["appraiser"]["id"])
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — revision / complaint lifecycle shortcuts
# ---------------------------------------------------------------------------


def open_revision_on_delivered(
    ctx: Dict[str, Any], kind: str = "CORRECTION", **overrides
) -> Dict[str, Any]:
    """Create a revision request on the context's delivered order."""
    rr = create_revision_request(
        ctx["order"]["id"], ctx["client"]["id"], kind=kind, **overrides
    )
    ctx["order"] = get_order(ctx["order"]["id"])
    return rr


def setup_accepted_revision(ctx: Dict[str, Any], **overrides) -> Dict[str, Any]:
    """Open + accept a revision request; order IN_REVISION, report
    UNDER_REVISION, comps back to VERIFIED."""
    rr = open_revision_on_delivered(ctx, **overrides)
    rr = accept_revision(rr["id"])
    ctx["revision"] = rr
    ctx["order"] = get_order(ctx["order"]["id"])
    ctx["report"] = get_success_data(api_client.get_report(ctx["report"]["id"], ADMIN))
    return rr


def relock_comps(ctx: Dict[str, Any]) -> None:
    """Re-lock the context's comparables after a revision unlocked them."""
    for comp in ctx.get("comps", []):
        lock_comparable(comp["id"], ctx["appraiser"]["id"])


def redeliver_revised_report(
    ctx: Dict[str, Any], delivery_clock: str = "2026-08-06T00:00:00Z"
) -> Dict[str, Any]:
    """From an accepted revision: relock comps, resubmit, qc-pass, deliver."""
    relock_comps(ctx)
    submit_for_qc(ctx["report"]["id"], ctx["appraiser"]["id"])
    qc_pass(ctx["report"]["id"], ctx["reviewer"]["id"])
    set_clock(delivery_clock)
    ctx["report"] = deliver_report(ctx["report"]["id"], ctx["appraiser"]["id"])
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


def setup_submitted_complaint(
    ctx: Dict[str, Any], complaint_clock: Optional[str] = None
) -> Dict[str, Any]:
    """Complaint on the context's order taken RECEIVED -> RESPONSE_SUBMITTED."""
    if complaint_clock:
        set_clock(complaint_clock)
    complaint = create_complaint(ctx["order"]["id"], ctx["appraiser"]["id"])
    draft_complaint(complaint["id"])
    complaint = submit_complaint(complaint["id"])
    ctx["complaint"] = complaint
    ctx["order"] = get_order(ctx["order"]["id"])
    return complaint


# ---------------------------------------------------------------------------
# Tier 4 — scorecard rating fixture
# ---------------------------------------------------------------------------


def deliver_desktop_order_for_appraiser(
    client: Dict[str, Any],
    appraiser: Dict[str, Any],
    reviewer: Dict[str, Any],
    delivery_clock: str,
    address: str,
) -> Dict[str, Any]:
    """Create a desktop STANDARD order for ``appraiser`` and carry it through
    to delivery at ``delivery_clock``. Assumes membership already exists and
    the caller manages the logical clock between deliveries."""
    order = create_order(client["id"], property_address=address)
    order = scope_order(order["id"], requires_inspection=False)
    order = accept_order(order["id"])
    order = assign_order(order["id"], appraiser["id"])
    start_analysis(order["id"], appraiser["id"])
    ctx = {"order": order, "appraiser": appraiser}
    add_standard_locked_comps(ctx)
    report = create_report(order["id"], appraiser["id"])
    submit_for_qc(report["id"], appraiser["id"])
    qc_pass(report["id"], reviewer["id"])
    set_clock(delivery_clock)
    deliver_report(report["id"], appraiser["id"])
    return order

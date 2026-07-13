"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is empty at the start of every test.
Setup calls use get_success_data() (lenient) so a broken precondition surfaces
as a clear "Setup step failed" error rather than a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_reviewer_headers,
    make_inspector_headers,
    make_officer_headers,
)
from . import factories as F

ADMIN = TEST_USERS["admin_headers"]
REVIEWER_1 = TEST_USERS["reviewer_headers"]      # approves (assigned_reviewer_user_id = reviewer-1)
REVIEWER_2 = TEST_USERS["reviewer_2_headers"]    # issues (segregation of duties)
INSPECTOR = TEST_USERS["inspector_headers"]      # inspector-1
OFFICER = TEST_USERS["officer_headers"]          # officer-1


# --------------------------------------------------------------------------
# Primitive builders
# --------------------------------------------------------------------------
def create_applicant(api, **overrides) -> dict:
    return get_success_data(api.create_applicant(F.create_applicant_payload(**overrides), ADMIN))


def create_segment(api, **overrides) -> dict:
    return get_success_data(
        api.create_street_segment(F.create_street_segment_payload(**overrides), ADMIN)
    )


def create_span(api, **overrides) -> dict:
    return get_success_data(
        api.create_sidewalk_span(F.create_sidewalk_span_payload(**overrides), ADMIN)
    )


def set_clock(api, to_iso8601: str) -> dict:
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


def create_draft_permit(api, app_id, seg_id, **overrides) -> dict:
    headers = make_applicant_headers(app_id)
    return get_success_data(
        api.create_permit(F.create_permit_payload(app_id, seg_id, **overrides), headers)
    )


# --------------------------------------------------------------------------
# Tier 1/2: Approved permit (app + segment + permit through APPROVED)
# --------------------------------------------------------------------------
def setup_approved_permit(
    api,
    zone_class="COMMERCIAL",
    last_repaved_date="2020-01-01",
    obstruction_type="LANE",
    requested_start_date="2026-04-01",
    requested_end_date="2026-04-11",
    roadway_lane_count=2,
    block_label="Main 100",
    segment_overrides=None,
    permit_overrides=None,
) -> dict:
    """Create applicant + segment + permit, submit, and approve (reviewer-1).

    Returns dict with app_id, seg_id, permit_id, approved_version.
    """
    seg_kwargs = dict(
        zone_class=zone_class,
        last_repaved_date=last_repaved_date,
        roadway_lane_count=roadway_lane_count,
        block_label=block_label,
    )
    if segment_overrides:
        seg_kwargs.update(segment_overrides)

    permit_kwargs = dict(
        primary_obstruction_type=obstruction_type,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
    )
    if permit_overrides:
        permit_kwargs.update(permit_overrides)

    app = create_applicant(api)
    app_id = app["id"]
    seg = create_segment(api, **seg_kwargs)
    seg_id = seg["id"]
    app_headers = make_applicant_headers(app_id)

    permit = get_success_data(
        api.create_permit(F.create_permit_payload(app_id, seg_id, **permit_kwargs), app_headers)
    )
    permit_id = permit["id"]

    get_success_data(api.submit_permit(permit_id, app_headers))
    approved = get_success_data(
        api.decide_permit(permit_id, {"outcome": "APPROVED"}, REVIEWER_1)
    )
    return {
        "app_id": app_id,
        "seg_id": seg_id,
        "permit_id": permit_id,
        "approved_version": approved["version"],
        "app_headers": app_headers,
    }


def attach_and_approve_tcp(
    api,
    permit_id,
    app_id,
    requires_flaggers=False,
    flagger_count=0,
    device_list=None,
    setback_ft=5,
    approve=True,
) -> dict:
    """Attach a traffic-control plan and optionally approve it. Returns the plan dict."""
    app_headers = make_applicant_headers(app_id)
    tcp_payload = F.create_traffic_control_plan_payload(
        device_list=device_list or ["CONES"],
        requires_flaggers=requires_flaggers,
        setback_ft=setback_ft,
    )
    if requires_flaggers or flagger_count:
        tcp_payload["flagger_count"] = flagger_count
    tcp = get_success_data(api.create_traffic_control_plan(permit_id, tcp_payload, app_headers))
    if approve:
        tcp = get_success_data(
            api.decide_traffic_control_plan(tcp["id"], {"outcome": "APPROVED"}, REVIEWER_1)
        )
    return tcp


def post_bond(api, permit_id, app_id, posted_cents, expected_permit_version) -> dict:
    app_headers = make_applicant_headers(app_id)
    return get_success_data(
        api.post_bond(
            permit_id,
            F.create_bond_payload(posted_cents, expected_permit_version),
            app_headers,
        )
    )


# --------------------------------------------------------------------------
# Tier 3: Issued permit (full prerequisite chain through ISSUED)
# --------------------------------------------------------------------------
def setup_issued_permit(
    api,
    zone_class="COMMERCIAL",
    last_repaved_date="2020-01-01",
    obstruction_type="LANE",
    requested_start_date="2026-04-01",
    requested_end_date="2026-04-11",
    posted_cents=80000,
    roadway_lane_count=2,
    block_label="Main 100",
    tcp_requires_flaggers=False,
    tcp_flagger_count=0,
    tcp_device_list=None,
    tcp_setback_ft=5,
    segment_overrides=None,
) -> dict:
    """Full chain: applicant + segment + permit -> submit -> approve -> TCP
    approved -> bond posted -> issue (reviewer-2, satisfying segregation).

    Returns dict with app_id, seg_id, permit_id, tcp_id, bond_id, permit (issued).
    """
    base = setup_approved_permit(
        api,
        zone_class=zone_class,
        last_repaved_date=last_repaved_date,
        obstruction_type=obstruction_type,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        roadway_lane_count=roadway_lane_count,
        block_label=block_label,
        segment_overrides=segment_overrides,
    )
    app_id = base["app_id"]
    permit_id = base["permit_id"]

    tcp = attach_and_approve_tcp(
        api,
        permit_id,
        app_id,
        requires_flaggers=tcp_requires_flaggers,
        flagger_count=tcp_flagger_count,
        device_list=tcp_device_list,
        setback_ft=tcp_setback_ft,
        approve=True,
    )
    bond = post_bond(api, permit_id, app_id, posted_cents, base["approved_version"])
    issued = get_success_data(api.issue_permit(permit_id, REVIEWER_2))

    base.update(
        {
            "tcp_id": tcp["id"],
            "bond_id": bond["id"],
            "permit": issued,
        }
    )
    return base


# --------------------------------------------------------------------------
# Lane-closure convenience builders
# --------------------------------------------------------------------------
def create_closure(api, permit_id, seg_id, app_id, **overrides) -> dict:
    app_headers = make_applicant_headers(app_id)
    return get_success_data(
        api.create_lane_closure(
            permit_id, F.create_lane_closure_payload(seg_id, **overrides), app_headers
        )
    )


def activate_closure(api, closure_id, app_id) -> dict:
    return get_success_data(api.activate_lane_closure(closure_id, make_applicant_headers(app_id)))


def request_restoration(api, closure_id, app_id, estimated_deficiency_cents=0) -> dict:
    return get_success_data(
        api.request_restoration(
            closure_id,
            {"estimated_deficiency_cents": estimated_deficiency_cents},
            make_applicant_headers(app_id),
        )
    )


def sign_off(api, closure_id, result, assessed_deficiency_cents=0) -> dict:
    return get_success_data(
        api.sign_off(
            closure_id,
            {"result": result, "assessed_deficiency_cents": assessed_deficiency_cents},
            INSPECTOR,
        )
    )


def setup_issued_permit_with_active_closure(
    api,
    zone_class="COMMERCIAL",
    obstruction_type="LANE",
    posted_cents=80000,
    closure_start="2026-04-01",
    closure_end="2026-04-11",
    **issued_overrides,
) -> dict:
    """Issued permit + one lane closure activated. Returns the issued dict plus closure_id."""
    ctx = setup_issued_permit(
        api,
        zone_class=zone_class,
        obstruction_type=obstruction_type,
        posted_cents=posted_cents,
        **issued_overrides,
    )
    closure = create_closure(
        api, ctx["permit_id"], ctx["seg_id"], ctx["app_id"],
        start_date=closure_start, end_date=closure_end,
    )
    activate_closure(api, closure["id"], ctx["app_id"])
    ctx["closure_id"] = closure["id"]
    return ctx


def setup_closure_signed_off_ready_for_release(
    api,
    posted_cents=80000,
    estimated_deficiency_cents=10000,
    assessed_deficiency_cents=25000,
) -> dict:
    """Issued permit -> closure activated -> restoration requested (estimated
    deficiency) -> signed off PASS (assessed deficiency). Closure is RESTORED
    and the bond is POSTED, ready for release. Returns dict with permit_id,
    bond_id, closure_id, seg_id, app_id."""
    ctx = setup_issued_permit_with_active_closure(api, posted_cents=posted_cents)
    request_restoration(api, ctx["closure_id"], ctx["app_id"], estimated_deficiency_cents)
    sign_off(api, ctx["closure_id"], "PASS", assessed_deficiency_cents)
    return ctx


def setup_issued_permit_with_prior_violation(
    api,
    posted_cents=80000,
) -> dict:
    """Issued permit + one activated closure + one prior violation
    (cumulative penalty 15000, still ISSUED). Returns dict with closure_id,
    bond_id, permit_id, seg_id, app_id."""
    ctx = setup_issued_permit_with_active_closure(api, posted_cents=posted_cents)
    get_success_data(
        api.create_violation(ctx["permit_id"], {"violation_type": "TCP_VIOLATION"}, OFFICER)
    )
    return ctx

"""Warranty claims: negotiation cycle, shortfall evaluation, window overlap."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_operational_project, open_period, settle_period,
    create_warranty_claim_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# --- Difficulty: non_linear_state_machine / warranty_claim_info_requested_resubmit_cycle ---

def test_claim_info_requested_then_resubmit_returns_submitted(api):
    """PRD 3.10: "The installer may request information, moving a SUBMITTED claim
    to INFO_REQUESTED; the owning homeowner then resubmits, moving INFO_REQUESTED
    back to SUBMITTED in a cyclic revision loop."

    Design: Difficulty/non_linear_state_machine/warranty_claim_info_requested_resubmit_cycle
    """
    ctx = setup_operational_project()
    claim = get_success_data(api.create_warranty_claim(
        create_warranty_claim_payload(project_id=ctx["project"]["id"],
                                      claim_type="EQUIPMENT_DEFECT"),
        ctx["ho_headers"],
    ))
    get_success_data(api.request_claim_info(claim["id"], ctx["inst_headers"]))
    resp = api.resubmit_claim(claim["id"], ctx["ho_headers"])
    data = validate_success(resp, 200)
    assert data["status"] == "SUBMITTED"


def test_claim_request_info_moves_to_info_requested(api):
    """PRD 3.10: "The installer may request information, moving a SUBMITTED claim
    to INFO_REQUESTED"

    Design: Difficulty/non_linear_state_machine/warranty_claim_info_requested_resubmit_cycle
    """
    ctx = setup_operational_project()
    claim = get_success_data(api.create_warranty_claim(
        create_warranty_claim_payload(project_id=ctx["project"]["id"],
                                      claim_type="EQUIPMENT_DEFECT"),
        ctx["ho_headers"],
    ))
    resp = api.request_claim_info(claim["id"], ctx["inst_headers"])
    data = validate_success(resp, 200)
    assert data["status"] == "INFO_REQUESTED"


# --- Difficulty: resource_temporal_overlap / warranty_claim_window_closed_interval_overlap ---

def test_claim_window_shared_endpoint_collides(api):
    """PRD 3.10: "two windows conflict whenever the first window's start is at or
    before the second window's end and the second window's start is at or before
    the first window's end — so windows that merely share an endpoint do collide,
    unlike the half-open rule for net-meter periods. A colliding window is
    rejected with ERR_CLAIM_WINDOW_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/warranty_claim_window_closed_interval_overlap
    """
    ctx = setup_operational_project()
    get_success_data(api.create_warranty_claim(
        create_warranty_claim_payload(
            project_id=ctx["project"]["id"], claim_type="PRODUCTION_SHORTFALL",
            claimed_window_start="2026-01-01T00:00:00.000Z",
            claimed_window_end="2026-12-01T00:00:00.000Z",
        ),
        ctx["ho_headers"],
    ))
    resp = api.create_warranty_claim(
        create_warranty_claim_payload(
            project_id=ctx["project"]["id"], claim_type="PRODUCTION_SHORTFALL",
            claimed_window_start="2026-12-01T00:00:00.000Z",
            claimed_window_end="2027-06-01T00:00:00.000Z",
        ),
        ctx["ho_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_OVERLAP, 409)


def test_claim_window_overlap_returns_409(api):
    """PRD 3.10: "A colliding window is rejected with ERR_CLAIM_WINDOW_OVERLAP
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/warranty_claim_window_closed_interval_overlap
    """
    ctx = setup_operational_project()
    get_success_data(api.create_warranty_claim(
        create_warranty_claim_payload(
            project_id=ctx["project"]["id"], claim_type="PRODUCTION_SHORTFALL",
            claimed_window_start="2026-01-01T00:00:00.000Z",
            claimed_window_end="2026-12-01T00:00:00.000Z",
        ),
        ctx["ho_headers"],
    ))
    resp = api.create_warranty_claim(
        create_warranty_claim_payload(
            project_id=ctx["project"]["id"], claim_type="PRODUCTION_SHORTFALL",
            claimed_window_start="2026-12-01T00:00:00.000Z",
            claimed_window_end="2027-06-01T00:00:00.000Z",
        ),
        ctx["ho_headers"],
    )
    assert resp.status_code == 409


# --- Corner: state_machines / production shortfall payout ---

def test_approve_production_shortfall_pins_payout(api):
    """PRD 3.10: "The shortfall_kwh is the larger of zero and the guaranteed figure
    minus the measured production. The payout_cents values that shortfall at the
    project's net-metering retail rate — the net_metering_rate_cents_per_kwh of
    the utility on its interconnection — as the shortfall_kwh multiplied by that
    rate, rounded half up."

    Design: Corner/state_machines/warranty_claim_approve_production_shortfall_payout
    """
    ctx = setup_operational_project(net_metering_rate_cents_per_kwh=15.0)
    nm = open_period(ctx, "2026-01-01T00:00:00.000Z", "2026-02-01T00:00:00.000Z", 6000, 100)
    settle_period(ctx, nm["id"])
    claim = get_success_data(api.create_warranty_claim(
        create_warranty_claim_payload(
            project_id=ctx["project"]["id"], claim_type="PRODUCTION_SHORTFALL",
            claimed_window_start="2026-01-01T00:00:00.000Z",
            claimed_window_end="2026-02-01T00:00:00.000Z",
        ),
        ctx["ho_headers"],
    ))
    resp = api.approve_claim(claim["id"], ctx["inst_headers"])
    data = validate_success(resp, 200)
    assert data["status"] == "APPROVED"
    # est 9592, guarantee 0.85 -> floor 8153; measured 6000; shortfall 2153; payout 2153*15
    assert data["measured_production_kwh"] == 6000
    assert data["shortfall_kwh"] == 2153
    assert data["payout_cents"] == 32295


def test_approve_zero_shortfall_rejected(api):
    """PRD 3.10: "for a production-shortfall claim, a positive shortfall after
    evaluation; a zero shortfall cannot be approved and is rejected with
    ERR_NO_SHORTFALL (HTTP 422)."

    Design: Corner/state_machines/warranty_claim_approve_zero_shortfall_rejected
    """
    ctx = setup_operational_project(net_metering_rate_cents_per_kwh=15.0)
    nm = open_period(ctx, "2026-01-01T00:00:00.000Z", "2026-02-01T00:00:00.000Z", 8200, 100)
    settle_period(ctx, nm["id"])
    claim = get_success_data(api.create_warranty_claim(
        create_warranty_claim_payload(
            project_id=ctx["project"]["id"], claim_type="PRODUCTION_SHORTFALL",
            claimed_window_start="2026-01-01T00:00:00.000Z",
            claimed_window_end="2026-02-01T00:00:00.000Z",
        ),
        ctx["ho_headers"],
    ))
    # measured 8200 >= guaranteed 8153 -> shortfall 0
    resp = api.approve_claim(claim["id"], ctx["inst_headers"])
    validate_error(resp, ApiErrorId.ERR_NO_SHORTFALL, 422)

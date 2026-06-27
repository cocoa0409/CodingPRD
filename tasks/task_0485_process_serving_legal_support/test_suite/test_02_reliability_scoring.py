"""Server reliability scoring: realized (persisted) vs projected (dispatch-ranking)
variants, and the fresh-server default.

Score = round_half_up(min(100, 100 * good / max(1, base_pool)), 2), clamped [0,100],
good = served*1.0 + nonest*0.5 (PRD section 3.13).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    make_server_headers,
    setup_reference_data,
    create_submitted_request,
    offer_to_server,
    log_attempt,
    get_server_entity,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _build_reliability_scenario(api):
    """One server over three requests: SR1 served->COMPLETED, SR2 accepted then
    reassigned (walked), SR3 accepted and left ACTIVE. Returns server id.
    """
    county, server, client = setup_reference_data(
        deposit_cents=100_000,
        county_overrides={"name": "Marin", "state_code": "CA", "min_diligent_attempts": 1},
    )
    svr = make_server_headers(server["id"])

    # SR1: serve to COMPLETED-bubble (served=1).
    sr1 = create_submitted_request(client["id"], county["id"], recipient_name="D1")
    asg1 = offer_to_server(sr1["id"], server["id"], sr1["version"])
    get_success_data(api.accept_assignment(asg1["id"], svr))
    log_attempt(asg1["id"], server["id"], "2026-01-01T09:00:00Z", "CONTACT_MADE")
    get_success_data(
        api.record_service(
            sr1["id"],
            {"assignment_id": asg1["id"], "service_type": "PERSONAL", "served_at_utc": "2026-01-01T09:05:00Z"},
            svr,
        )
    )

    # SR2: accept then reassign (walked=1).
    sr2 = create_submitted_request(client["id"], county["id"], recipient_name="D2")
    asg2 = offer_to_server(sr2["id"], server["id"], sr2["version"])
    get_success_data(api.accept_assignment(asg2["id"], svr))
    get_success_data(api.reassign(sr2["id"], DISPATCHER))

    # SR3: accept, leave ACTIVE (active_assignment_count=1).
    sr3 = create_submitted_request(client["id"], county["id"], recipient_name="D3")
    asg3 = offer_to_server(sr3["id"], server["id"], sr3["version"])
    get_success_data(api.accept_assignment(asg3["id"], svr))
    return server["id"]


def test_realized_reliability_persisted_on_server(api):
    """PRD 3.13: "The **realized** variant — the one persisted in the server's
    `reliability_score` — uses a base pool of the served count plus the non-est
    count plus the walked count, counting only resolved, terminal assignments and
    ignoring in-flight `ACTIVE` work."
    PRD 3.13: "The 'good work' total weights a served assignment at 1.0 and a
    non-est assignment at 0.5".

    Design: Difficulty/dual_variant_calc/server_reliability_realized_vs_projected_diverge_on_server
    """
    server_id = _build_reliability_scenario(api)
    server = get_server_entity(server_id)
    # served=1, nonest=0, walked=1; good=1.0; realized pool=2 => 100*1/2 = 50.00.
    assert server["reliability_score"] == 50.0, f"expected 50.0, got {server['reliability_score']}"


def test_projected_reliability_includes_active_and_diverges(api):
    """PRD 3.13: "The **projected** variant ... uses a base pool of the served
    count plus the non-est count plus the walked count plus the server's
    `active_assignment_count`, treating in-flight `ACTIVE` assignments as
    not-yet-good work."
    PRD 3.13: "A computed read returns the server's `realized_score`, its
    `projected_score`, and its current `active_assignment_count` together".

    Design: Difficulty/dual_variant_calc/server_reliability_realized_vs_projected_diverge_on_server
    """
    server_id = _build_reliability_scenario(api)
    proj = validate_success(api.reliability_projection(server_id, DISPATCHER))
    assert proj["realized_score"] == 50.0, f"realized expected 50.0, got {proj['realized_score']}"
    # projected pool = 2 + active 1 = 3 => 100*1/3 = 33.33.
    assert proj["projected_score"] == 33.33, f"projected expected 33.33, got {proj['projected_score']}"
    assert proj["active_assignment_count"] == 1


def test_fresh_server_reliability_defaults_to_100(api):
    """PRD 3.1: "A new server starts `ACTIVE`, with `active_assignment_count` and
    `completed_count` both at 0 and a `reliability_score` of 100."

    Design: Corner/calculations/fresh_server_reliability_default_100_no_terminal_assignments
    """
    server = validate_success(
        api.create_server({"full_name": "Fresh Score", "license_no": "PS-FRS1"}, ADMIN), 201
    )
    assert server["reliability_score"] == 100, f"expected 100, got {server['reliability_score']}"
    assert server["active_assignment_count"] == 0

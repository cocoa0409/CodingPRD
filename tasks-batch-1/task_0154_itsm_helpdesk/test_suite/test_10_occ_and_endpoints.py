"""Corner queue B — cross_cutting_complexity_layers (OCC) and endpoints sections:
stale-version guards on vote and route, a successful route version bump, the
in-window CSAT counts_toward_index flag, and FK reverse-reachability listing.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    fixtures as fx,
    factories as F,
    test_users as U,
    ApiErrorId,
)


# ===========================================================================
# Corner/cross_cutting_complexity_layers/occ_stale_version_on_vote_returns_stale_version
# ===========================================================================
def test_vote_with_stale_change_version_rejected():
    """PRD §2.7: "A vote request must carry expected_change_request_version
    holding the version of the target ChangeRequest that the voter last observed.
    If that value does not equal the change's current version — for example
    because an earlier vote already advanced the tally ... the vote is rejected
    with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_vote_returns_stale_version
    """
    _, _, _, _, change = fx.setup_submitted_change(risk="HIGH", default_priority="P2",
                                                   manager_id="cm-c21")
    cr_id = change["id"]
    stale_version = change["version"]

    # First vote advances the change's version.
    validate_success(
        api_client.cast_vote(
            cr_id,
            {"decision": "APPROVE", "expected_change_request_version": stale_version},
            U.cab_member("cab-a"),
        ),
        expected_status=201,
    )
    # Second vote reuses the now-stale version.
    resp = api_client.cast_vote(
        cr_id,
        {"decision": "APPROVE", "expected_change_request_version": stale_version},
        U.cab_member("cab-b"),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


# ===========================================================================
# Corner/cross_cutting_complexity_layers/occ_stale_version_on_route_returns_stale_version
# ===========================================================================
def test_route_with_stale_ticket_version_rejected():
    """PRD §2.7: "A route request must carry expected_ticket_version holding the
    version of the target Ticket the agent last observed. If another agent has
    since routed, reprioritized, or otherwise advanced that ticket, its current
    version will differ and the route is rejected with ERR_STALE_VERSION (HTTP
    412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_route_returns_stale_version
    """
    policy = validate_success(
        api_client.create_sla_policy(F.create_sla_policy_payload(), U.platform_admin()),
        expected_status=201,
    )
    grp_a = fx.create_group(name="RT-A")
    grp_b = fx.create_group(name="RT-B")
    category = validate_success(
        api_client.create_category(
            F.create_category_payload(policy["id"], grp_a["id"], default_priority="P3"),
            U.platform_admin(),
        ),
        expected_status=201,
    )
    ticket = fx.open_ticket(category["id"], requester_id="req-c22")
    v0 = ticket["version"]

    validate_success(
        api_client.route_ticket(
            ticket["id"],
            {"assignment_group_id": grp_b["id"], "expected_ticket_version": v0},
            U.agent("agent-c22"),
        )
    )
    resp = api_client.route_ticket(
        ticket["id"],
        {"assignment_group_id": grp_a["id"], "expected_ticket_version": v0},
        U.agent("agent-c22"),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


# ===========================================================================
# Corner/cross_cutting_complexity_layers/route_occ_success_increments_ticket_version
# ===========================================================================
def test_route_with_correct_version_moves_group_and_bumps_version():
    """PRD §3.3: "Routing moves the ticket between queues: it writes the supplied
    assignment_group_id, recomputes both the source and the target group's
    queue_depth."
    PRD §2.4: "an integer version that begins at 1 and increments by exactly one
    on every successful mutation of that resource."

    Design: Corner/cross_cutting_complexity_layers/route_occ_success_increments_ticket_version
    """
    policy = validate_success(
        api_client.create_sla_policy(F.create_sla_policy_payload(), U.platform_admin()),
        expected_status=201,
    )
    grp_a = fx.create_group(name="OK-A")
    grp_b = fx.create_group(name="OK-B")
    category = validate_success(
        api_client.create_category(
            F.create_category_payload(policy["id"], grp_a["id"], default_priority="P3"),
            U.platform_admin(),
        ),
        expected_status=201,
    )
    ticket = fx.open_ticket(category["id"], requester_id="req-c23")
    v0 = ticket["version"]

    routed = validate_success(
        api_client.route_ticket(
            ticket["id"],
            {"assignment_group_id": grp_b["id"], "expected_ticket_version": v0},
            U.agent("agent-c23"),
        )
    )
    assert routed["assignment_group_id"] == grp_b["id"]
    assert routed["version"] == v0 + 1


# ===========================================================================
# Corner/endpoints/csat_within_window_counts_toward_index_true
# ===========================================================================
def test_csat_within_window_counts_toward_index_true():
    """PRD §3.7: "A survey submitted past that hard window is rejected outright
    with ERR_CSAT_WINDOW_CLOSED; a survey within the window is stored with
    counts_toward_index set to true."

    Design: Corner/endpoints/csat_within_window_counts_toward_index_true
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    _, _, _, ticket = fx.setup_resolved_ticket(
        default_priority="P3", requester_id="req-c24", agent_id="agent-c24"
    )
    fx.advance_clock(10)  # well inside the 2880-minute window
    data = validate_success(
        api_client.create_csat_survey(
            {"ticket_id": ticket["id"], "score": 5}, U.requester("req-c24")
        ),
        expected_status=201,
    )
    assert data["counts_toward_index"] is True


# ---------------------------------------------------------------------------
# SKIPPED — Corner/endpoints/list_change_requests_filtered_by_ticket_id_reverse_reachability
# Silence pattern: applies_to-scope / endpoint-titular (C2). The instance's claim
# is that GET /change-requests filters by ticket_id, but no verbatim PRD sentence
# names a ticket_id query filter on that endpoint — the §4 table row reads only
# "List change requests", and §2.3 describes only generic limit/offset pagination.
# A faithful PRD-only implementer could ignore an unknown ticket_id param, so the
# filter outcome is not uniquely derivable. Gap left as a gap; no test emitted.
# ---------------------------------------------------------------------------

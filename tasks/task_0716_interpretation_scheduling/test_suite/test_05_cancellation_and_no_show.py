"""Cancellation fee bands (on-demand vs scheduled) and client no-show charging."""
from test_helpers import (
    validate_success,
    provision_court_onsite_per_hour, provision_med_phone,
    create_client, create_language_pair, create_rate_plan,
    create_request, dispatch_request, dispatch_accept, set_clock,
    make_client_headers, make_interpreter_headers, coordinator_headers,
    factories,
)


def test_scheduled_late_cancel_charges_fifty_percent_min_block(api):
    """PRD 3.7: "If the lead time is between zero and the late-cancel window (zero inclusive,
    the two-hour mark exclusive), the cancellation falls in the late band and the fee is the
    estimated minimum charge multiplied by the late-cancel percentage of 0.50 (fifty
    percent), rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/cancellation_fee_ondemand_vs_scheduled_diverge
    """
    env = provision_court_onsite_per_hour()  # min_block 2, rate 12000, travel 4500 ONSITE
    set_clock("2026-03-10T10:00:00Z")
    # SCHEDULED window starts 11:00 -> lead 1h (3600s), inside the 2h late band.
    req = create_request(
        env["client"]["id"], env["lp"]["id"],
        modality="ONSITE", required_tier="LEGAL", scheduling_mode="SCHEDULED",
        window_start="2026-03-10T11:00:00Z", window_end="2026-03-10T12:00:00Z",
    )
    dispatch_request(req["id"], req["version"])  # ASSIGNED, no session connected
    client_h = make_client_headers(env["client"]["id"])
    cancelled = validate_success(api.cancel_request(req["id"], client_h))
    # estimated_min_charge = 2*12000 + 4500 = 28500 ; 50% = 14250.
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_fee_cents"] == 14250, (
        f"expected 14250c late-cancel fee, got {cancelled['cancellation_fee_cents']}"
    )


def test_ondemand_cancel_before_connect_is_free(api):
    """PRD 3.7: "For an ON_DEMAND request the fee is always 0 - on-demand work cancels free,
    and the only thing that closes that free window is a session reaching ACTIVE, not any
    clock arithmetic."

    Design: Difficulty/dual_variant_calc/cancellation_fee_ondemand_vs_scheduled_diverge
    """
    env = provision_med_phone()
    set_clock("2026-03-10T09:00:00Z")
    req = create_request(env["client"]["id"], env["lp"]["id"])  # ON_DEMAND
    dispatch_request(req["id"], req["version"])  # ASSIGNED, no session connected
    client_h = make_client_headers(env["client"]["id"])
    cancelled = validate_success(api.cancel_request(req["id"], client_h))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_fee_cents"] == 0, (
        f"on-demand cancel must be free, got {cancelled['cancellation_fee_cents']}"
    )


def test_client_no_show_charges_fee_and_sets_billable(api):
    """PRD 3.6: "A client no-show moves the session to CLIENT_NO_SHOW, runs the no-show fee
    calculation, writes the result onto the request's cancellation_fee_cents, and sets the
    assignment's billing_status to BILLABLE so the client is charged. The no-show fee is the
    estimated minimum charge multiplied by the no-show percentage of 0.50 (fifty percent),
    rounded half-up to whole cents."

    Design: Corner/state_machines/client_no_show_charges_fee
    """
    env = provision_med_phone()  # min_block 10, rate 195 -> est min charge 1950
    set_clock("2026-03-10T09:00:00Z")
    req, asg = dispatch_accept(env["client"]["id"], env["lp"]["id"], env["interpreter"]["id"])
    itp_h = make_interpreter_headers(env["interpreter"]["id"])
    session = validate_success(api.start_session(asg["id"], itp_h), expected_status=201)  # CONNECTING
    set_clock("2026-03-10T09:15:00Z")  # past the 600s no-show grace from accept (09:00)
    marked = validate_success(
        api.mark_no_show(session["id"], factories.mark_no_show_payload("CLIENT"), coordinator_headers())
    )
    assert marked["status"] == "CLIENT_NO_SHOW"
    request = validate_success(api.get_request(req["id"], coordinator_headers()))
    # est min charge 1950 * 0.50 = 975.
    assert request["cancellation_fee_cents"] == 975, (
        f"expected 975c no-show fee, got {request['cancellation_fee_cents']}"
    )
    asg_after = validate_success(api.get_assignment(asg["id"], coordinator_headers()))
    assert asg_after["billing_status"] == "BILLABLE"

"""Subcontractor suspension/reinstatement cascades, terminal-assignment
lockdown, and the dual reliability-score variants."""
import pytest

from test_helpers import (
    accept_offer,
    add_scope_item,
    api_client,
    check_in_job,
    complete_securing,
    dispatch_job,
    get_assignment,
    get_job,
    get_subcontractor,
    install_scope_item,
    intake_job,
    make_subcontractor_headers,
    set_clock,
    setup_network,
    setup_secured_job,
    submit_assessment,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_subcontractor_suspension_cancels_open_assignments(api, admin_headers, dispatcher_headers):
    """PRD §3.1: "Suspension is deliberately violent: every assignment of that
    subcontractor in `OFFERED`, `ACCEPTED`, or `ARRIVED` status is cancelled, and
    each of those cancellations itself runs the offer cascade of §3.2, which may
    regress the affected job all the way back to `INTAKE`; notably,
    suspension-driven cancellations do not increment `expired_offer_count`."

    Design: Difficulty/transitive_cascade/subcontractor_suspension_two_hop_cascade
    """
    net = setup_network(num_subcontractors=1, covered_count=1, max_concurrent_jobs=2)
    se = net["subs"][0]

    # Job A: offer outstanding (OFFERED). Job B: offer ACCEPTED.
    job_a = intake_job(net["property"]["id"], incident_type="FIRE", priority="P3")
    offer_a = dispatch_job(job_a["id"])
    job_b = intake_job(net["property"]["id"], incident_type="STORM", priority="P3")
    offer_b = dispatch_job(job_b["id"])
    accept_offer(offer_b["id"], se["id"])

    res = api.patch_subcontractor(se["id"], {"status": "SUSPENDED"}, admin_headers)
    suspended = validate_success(res, 200)
    assert suspended["status"] == "SUSPENDED"

    assert get_assignment(offer_a["id"])["status"] == "CANCELLED", "hop 1: OFFERED cancelled"
    assert get_assignment(offer_b["id"])["status"] == "CANCELLED", "hop 1: ACCEPTED cancelled"
    assert get_subcontractor(se["id"])["expired_offer_count"] == 0, (
        "suspension-driven cancellations never count as expired offers")


def test_suspension_regresses_jobs_and_zeroes_active_count(api, admin_headers, dispatcher_headers):
    """PRD §3.1: "each of those cancellations itself runs the offer cascade of
    §3.2, which may regress the affected job all the way back to `INTAKE`"
    PRD §3.2: "an empty pool regresses the job `DISPATCHED` → `INTAKE`."

    Design: Difficulty/transitive_cascade/subcontractor_suspension_two_hop_cascade
    """
    net = setup_network(num_subcontractors=1, covered_count=1, max_concurrent_jobs=2)
    se = net["subs"][0]

    job_a = intake_job(net["property"]["id"], incident_type="FIRE", priority="P3")
    dispatch_job(job_a["id"])
    job_b = intake_job(net["property"]["id"], incident_type="STORM", priority="P3")
    offer_b = dispatch_job(job_b["id"])
    accept_offer(offer_b["id"], se["id"])
    assert get_subcontractor(se["id"])["active_assignment_count"] == 1

    validate_success(api.patch_subcontractor(se["id"], {"status": "SUSPENDED"}, admin_headers), 200)

    assert get_job(job_a["id"])["work_status"] == "INTAKE", (
        "hop 2: empty re-offer pool regresses the job")
    assert get_job(job_b["id"])["work_status"] == "INTAKE"
    assert get_subcontractor(se["id"])["active_assignment_count"] == 0


def test_subcontractor_reinstate_does_not_resurrect(api, admin_headers, dispatcher_headers):
    """PRD §3.1: "Reinstatement flips the coverage rows back to `ACTIVE` but never
    resurrects previously cancelled assignments — the work has already been
    re-offered."

    Design: Corner/state_machines/subcontractor_reinstate_does_not_resurrect
    """
    net = setup_network(num_subcontractors=1, covered_count=1)
    s1 = net["subs"][0]
    job = intake_job(net["property"]["id"], incident_type="FIRE", priority="P3")
    offer = dispatch_job(job["id"])

    validate_success(api.patch_subcontractor(s1["id"], {"status": "SUSPENDED"}, admin_headers), 200)
    res = api.patch_subcontractor(s1["id"], {"status": "ACTIVE"}, admin_headers)
    reinstated = validate_success(res, 200)
    assert reinstated["status"] == "ACTIVE"

    assert get_assignment(offer["id"])["status"] == "CANCELLED", "CANCELLED is terminal"
    assert get_subcontractor(s1["id"])["active_assignment_count"] == 0

    coverages, meta = validate_paginated(
        api.list_coverages(dispatcher_headers, params={"subcontractor_id": s1["id"]}))
    assert meta["total_count"] == 1
    assert coverages[0]["status"] == "ACTIVE", "the coverage mirror is restored"


def test_withdraw_completed_assignment_rejected(api, dispatcher_headers):
    """PRD §2.7: "an action against an entity already in a terminal state is
    always rejected with `ERR_ALREADY_TERMINAL` (HTTP 409)"
    PRD §3.2: "Assignments terminate in `COMPLETED`, `DECLINED`, `EXPIRED`, or
    `CANCELLED`"

    Design: Corner/state_machines/withdraw_completed_assignment_rejected
    """
    ctx = setup_secured_job(priority="P3", incident_type="FIRE")
    assignment = get_assignment(ctx["assignment"]["id"])
    assert assignment["status"] == "COMPLETED"

    res = api.withdraw_assignment(assignment["id"], dispatcher_headers)
    validate_error(res, "ERR_ALREADY_TERMINAL")
    assert get_assignment(assignment["id"])["status"] == "COMPLETED", "no transition fired"


def _setup_reliability_counters():
    """Subcontractor sc: two on-time P3 completions, one P1 completion with an
    SLA breach (arrived 121 minutes after dispatch against a 120-minute SLA), and
    one offer left to lapse. Returns (ctx network dict, expired-respond response)."""
    net = setup_network(num_subcontractors=2, covered_count=1, max_concurrent_jobs=3)
    sc, sd = net["subs"][0], net["subs"][1]
    prop = net["property"]

    def run_job(incident, priority, check_in_clock=None):
        job = intake_job(prop["id"], incident_type=incident, priority=priority)
        offer = dispatch_job(job["id"])
        accept_offer(offer["id"], sc["id"])
        if check_in_clock is not None:
            set_clock(check_in_clock)
        arrived = check_in_job(job["id"], sc["id"])
        submit_assessment(job["id"], sd["id"], ["WATER"])
        item = add_scope_item(job["id"], kind="BOARD", opening_count=1,
                              width_in=48, height_in=36, door_count=0)
        install_scope_item(item["id"], sc["id"], opening_count=1,
                           width_in=48, height_in=36, door_count=0)
        complete_securing(job["id"], sc["id"])
        return job, arrived

    run_job("FIRE", "P3")                                    # on time: completed
    run_job("STORM", "P3")                                   # on time: completed
    _, arrived_c = run_job("STORM", "P1", check_in_clock="2026-05-01T02:01:00Z")
    assert arrived_c["sla_breach"] is True, "121 min > 120 P1 SLA: breach"

    # Job D: offer to sc lapses unanswered (offered at 02:01, expires 02:31).
    job_d = intake_job(prop["id"], incident_type="VANDALISM", priority="P3")
    offer_d = dispatch_job(job_d["id"])
    assert offer_d["subcontractor_id"] == sc["id"]
    set_clock("2026-05-01T02:32:00Z")
    respond_res = api_client.respond_assignment(
        offer_d["id"], {"outcome": "ACCEPT"}, make_subcontractor_headers(sc["id"]))
    net["job_d"] = job_d
    net["offer_d"] = offer_d
    return net, respond_res


def test_reliability_lenient_variant(api, dispatcher_headers):
    """PRD §3.1: "The lenient score, `reliability_score_lenient`, is the ratio of
    `completed_job_count` to the sum of `completed_job_count` and
    `breached_job_count`, and measures only the punctuality of completed work — it
    is the score the dispatch selector ranks by."
    PRD §3.1: "For either variant, an empty denominator yields exactly 1.0000,
    both are rounded half up to four decimal places"

    Design: Difficulty/dual_variant_calc/reliability_lenient_vs_strict_divergence
    """
    net, respond_res = _setup_reliability_counters()
    validate_error(respond_res, "ERR_OFFER_EXPIRED")

    sc_after = get_subcontractor(net["subs"][0]["id"])
    assert sc_after["completed_job_count"] == 2
    assert sc_after["breached_job_count"] == 1
    assert sc_after["expired_offer_count"] == 1
    # 2 / (2 + 1) = 0.66666... -> 0.6667 at 4dp round-half-up; expired excluded.
    assert sc_after["reliability_score_lenient"] == pytest.approx(0.6667, abs=1e-9)


def test_reliability_strict_variant_diverges(api, dispatcher_headers):
    """PRD §3.1: "The strict score, `reliability_score_strict`, divides
    `completed_job_count` by the sum of all three counters, additionally
    penalizing offers that lapsed unanswered; it is surfaced on the
    subcontractor's profile for suspension review."
    PRD §3.1: "the strict variant never exceeds the lenient one whenever the
    subcontractor has at least one expired offer."
    PRD §3.2: "an empty pool regresses the job `DISPATCHED` → `INTAKE`."

    Design: Difficulty/dual_variant_calc/reliability_lenient_vs_strict_divergence
    """
    net, respond_res = _setup_reliability_counters()
    validate_error(respond_res, "ERR_OFFER_EXPIRED")
    assert get_assignment(net["offer_d"]["id"])["status"] == "EXPIRED"
    assert get_job(net["job_d"]["id"])["work_status"] == "INTAKE", (
        "re-offer pool empty after the lapsed offeree is excluded")

    sc_after = get_subcontractor(net["subs"][0]["id"])
    # 2 / (2 + 1 + 1) = 0.5 — identical counters, different variant output.
    assert sc_after["reliability_score_strict"] == pytest.approx(0.5, abs=1e-9)
    assert sc_after["reliability_score_strict"] < sc_after["reliability_score_lenient"]

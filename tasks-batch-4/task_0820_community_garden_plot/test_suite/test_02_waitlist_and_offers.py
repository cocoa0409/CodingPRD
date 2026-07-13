"""Waitlist applications, priority scoring, offers, decline, and expiry."""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_gardener_headers,
    ApiErrorId,
    set_clock, new_garden, new_plot, new_gardener, direct_assign,
    new_application, open_compliance_case,
    setup_offered_application,
    create_gardener_payload, create_application_payload,
)

MANAGER = TEST_USERS["manager_headers"]


# ----------------------------------------------------------------------
# Difficulty: renewal_priority_score snapshot (frozen) vs live (as-of-allocation)
# ----------------------------------------------------------------------

def _build_priority_scenario(api):
    """GA holds a MEDIUM assignment and applies for a LARGE plot; GB also applies for
    LARGE; a compliance strike then drops GA's live score below GB's. Returns ids."""
    set_clock(api, "2026-03-10T00:00:00Z")
    garden = new_garden(api, name="Oak Garden")
    p0 = new_plot(api, garden["id"], size="MEDIUM", label="M-0")
    pL = new_plot(api, garden["id"], size="LARGE", label="L-1")
    ga = new_gardener(api, full_name="Gia Alder")
    gb = new_gardener(api, full_name="Gil Birch")
    direct_assign(api, p0["id"], ga["id"], p0["version"])
    app_a = new_application(api, ga["id"], garden["id"], requested_size="LARGE")
    app_b = new_application(api, gb["id"], garden["id"], requested_size="LARGE")
    open_compliance_case(api, _assignment_of(api, ga["id"]), violation_type="NEGLECT")
    return {"garden": garden, "pL": pL, "app_a": app_a, "app_b": app_b}


def _assignment_of(api, gardener_id):
    data, _ = _list_assignments(api, gardener_id)
    return data[0]["id"]


def _list_assignments(api, gardener_id):
    from test_helpers import validate_paginated
    return validate_paginated(api.list_assignments(MANAGER, params={"gardener_id": gardener_id}))


def test_priority_snapshot_frozen_at_submission(api):
    """PRD §3.2: "At the moment an application is submitted, the system freezes a
    snapshot of the score into `priority_score_at_submission`, using the gardener's
    `tenure_seasons`, `standing`, and `strike_count` as they stood at submission time."
    PRD §3.2: "A gardener's **renewal priority score** is their `tenure_seasons`
    multiplied by a tenure weight of 10, plus a standing bonus that is 5 when their
    `standing` is `GOOD`, 0 when `PROBATION`, and negative 100 when `SUSPENDED`, minus
    their `strike_count` multiplied by a strike weight of 3."

    Design: Difficulty/dual_variant_calc/priority_score_snapshot_vs_live
    """
    ctx = _build_priority_scenario(api)
    app_a = validate_success(api.get_application(ctx["app_a"]["id"], MANAGER), 200)
    assert app_a["priority_score_at_submission"] == 5


def test_live_recompute_flips_offer_winner_after_strike(api):
    """PRD §3.2: "The live recomputation, not the frozen snapshot, is what ranks
    candidates when a plot is offered; the snapshot is retained on the application as
    the value observed at submission."
    PRD §3.3: "It assembles the candidate set of applications that are `WAITLISTED`,
    belong to the plot's garden, and whose `requested_size` equals the plot's `size`,
    then ranks them by renewal priority score computed live (the as-of-allocation
    variant) in descending order, breaking ties by the application's `created_at`
    ascending — never by `id`."

    Design: Difficulty/dual_variant_calc/priority_score_snapshot_vs_live
    """
    ctx = _build_priority_scenario(api)
    validate_success(api.offer_plot(ctx["pL"]["id"], MANAGER), 200)
    app_a = validate_success(api.get_application(ctx["app_a"]["id"], MANAGER), 200)
    app_b = validate_success(api.get_application(ctx["app_b"]["id"], MANAGER), 200)
    assert app_b["status"] == "OFFERED", "GB (live score 5) should win the LARGE offer"
    assert app_a["status"] == "WAITLISTED", "GA (live score -3 after strike) should not be offered"


# ----------------------------------------------------------------------
# Corner: application/offer state machine
# ----------------------------------------------------------------------

def test_accept_waitlisted_application_rejected(api):
    """PRD §3.3: "Both actions require the application to be in `OFFERED`; acting on an
    application in any other status fails with `ERR_OFFER_NOT_PENDING` (HTTP 409)."

    Design: Corner/state_machines/accept_from_waitlisted_returns_invalid_state
    """
    garden = new_garden(api, name="SM Garden")
    g = new_gardener(api, full_name="Wai List")
    app = new_application(api, g["id"], garden["id"], requested_size="SMALL")
    resp = api.accept_application(app["id"], make_gardener_headers(g["id"]))
    validate_error(resp, ApiErrorId.ERR_OFFER_NOT_PENDING.value, 409)


def test_decline_offer_returns_plot_to_available(api):
    """PRD §3.3: "Declining moves the application from `OFFERED` to `DECLINED`, returns
    the plot from `RESERVED` to `AVAILABLE` (incrementing the plot's `version`), and
    clears the application's `offered_plot_id` and `offer_expires_at`."

    Design: Corner/state_machines/decline_offer_releases_plot
    """
    ctx = setup_offered_application(api, size="MEDIUM")
    validate_success(api.decline_application(ctx["application"]["id"], ctx["gardener_headers"]), 200)
    app = validate_success(api.get_application(ctx["application"]["id"], MANAGER), 200)
    plot = validate_success(api.get_plot(ctx["plot"]["id"], MANAGER), 200)
    assert app["status"] == "DECLINED"
    assert plot["status"] == "AVAILABLE"


def test_expire_offers_sweep_moves_offer_to_expired(api):
    """PRD §3.3: "the application moves from `OFFERED` to `EXPIRED`, its held plot
    returns from `RESERVED` to `AVAILABLE` with the plot's `version` incremented, and
    its `offered_plot_id` and `offer_expires_at` are cleared."

    Design: Corner/state_machines/expire_offers_sweep_moves_offer_to_expired
    """
    ctx = setup_offered_application(api, size="SMALL", clock="2026-03-10T00:00:00Z")
    set_clock(api, "2026-03-20T00:00:00Z")
    validate_success(api.expire_offers(ctx["garden"]["id"], MANAGER), 200)
    app = validate_success(api.get_application(ctx["application"]["id"], MANAGER), 200)
    plot = validate_success(api.get_plot(ctx["plot"]["id"], MANAGER), 200)
    assert app["status"] == "EXPIRED"
    assert plot["status"] == "AVAILABLE"


def test_offer_with_empty_waitlist_returns_no_eligible(api):
    """PRD §3.3: "If no candidate exists, the offer is rejected with
    `ERR_NO_ELIGIBLE_APPLICANT` (HTTP 409)."

    Design: Corner/calculations/offer_empty_waitlist_returns_no_eligible
    """
    garden = new_garden(api, name="Empty Garden")
    plot = new_plot(api, garden["id"], size="MEDIUM", label="Q-1")
    resp = api.offer_plot(plot["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_APPLICANT.value, 409)


def test_duplicate_application_rejected(api):
    """PRD §3.2: "if the same gardener already has an application for the identical
    combination of `gardener_id`, `garden_id`, and `requested_size` that is currently
    `WAITLISTED` or `OFFERED`, the new submission is rejected with
    `ERR_DUPLICATE_APPLICATION` (HTTP 409)."

    Design: Corner/validations/duplicate_application_rejected
    """
    garden = new_garden(api, name="Dup Garden")
    g = new_gardener(api, full_name="Dup App")
    headers = make_gardener_headers(g["id"])
    validate_success(
        api.create_application(create_application_payload(g["id"], garden["id"], "MEDIUM"), headers), 201
    )
    resp = api.create_application(create_application_payload(g["id"], garden["id"], "MEDIUM"), headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION.value, 409)

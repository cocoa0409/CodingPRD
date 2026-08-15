"""Quote lifecycle: revision loop, terminal lockdown, expiry, customer gating,
OCC on price, and the logical clock default."""
from test_helpers import (
    EST,
    MGR,
    ApiErrorId,
    accept_quote,
    create_customer,
    create_draft_quote,
    create_full_sheet,
    create_grade,
    create_machine,
    create_priced_quote,
    create_submitted_quote,
    get_order_lines,
    parse_instant,
    price_quote,
    rep_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_DEFAULT = "2026-08-01T00:00:00Z"


def _simple_line():
    return {"bbox_width_mm": 100, "bbox_height_mm": 100, "hole_count": 0,
            "corner_fillet_count": 0, "bend_count": 0, "weld_inches": 0}


# --- revision cycle (Difficulty: quote_submit_revise_resubmit_cycle) --------

def test_revise_returns_quote_to_draft_and_resets_lines(api):
    """PRD §3.4: "Revision increments `revision_count` by one, moves every line
    back to ESTIMATED so stale prices are discarded wholesale, clears
    `submitted_at` and `expires_at`, and appends a QUOTE_REVISED audit event."

    Design: Difficulty/non_linear_state_machine/quote_submit_revise_resubmit_cycle
    """
    grade = create_grade()
    customer = create_customer()
    submitted = create_submitted_quote(customer["id"], grade["id"],
                                       line_overrides=_simple_line())

    revised = validate_success(api.revise_quote(submitted["id"], EST))
    assert revised["status"] == "DRAFT"
    assert revised["revision_count"] == 1
    assert revised["submitted_at"] is None
    assert revised["expires_at"] is None
    for line in get_order_lines(submitted["id"]):
        assert line["status"] == "ESTIMATED", "revision discards stale prices"


def test_revise_cycle_is_repeatable_and_restamps(api):
    """PRD §3.4: "The quote can then be edited and re-priced through the same
    pipeline." PRD §3.4: "The transition stamps `submitted_at` from the
    logical clock, sets `expires_at` to fourteen days after `submitted_at`,
    moves the quote to SUBMITTED ..."

    Design: Difficulty/non_linear_state_machine/quote_submit_revise_resubmit_cycle
    """
    grade = create_grade()
    customer = create_customer()
    submitted = create_submitted_quote(customer["id"], grade["id"],
                                       line_overrides=_simple_line())

    revised = validate_success(api.revise_quote(submitted["id"], EST))
    priced = price_quote(revised["id"], revised["version"])
    resubmitted = validate_success(api.submit_quote(priced["id"], EST))
    assert resubmitted["status"] == "SUBMITTED"
    assert parse_instant(resubmitted["submitted_at"]) == parse_instant(CLOCK_DEFAULT)
    delta = parse_instant(resubmitted["expires_at"]) - parse_instant(
        resubmitted["submitted_at"])
    assert delta.days == 14, "validity window is fourteen days"

    # a DRAFT quote cannot re-enter the loop: revise requires SUBMITTED
    revised_again = validate_success(api.revise_quote(resubmitted["id"], EST))
    err = api.revise_quote(revised_again["id"], EST)
    validate_error(err, ApiErrorId.ERR_QUOTE_NOT_OPEN, 409)


# --- price-state guard (Corner: invalid_transition_price_on_submitted_rejected)

def test_price_on_submitted_quote_rejected(api):
    """PRD §3.3: "Pricing a quote that is not DRAFT fails with
    `ERR_QUOTE_NOT_OPEN` ..."

    Design: Corner/state_machines/invalid_transition_price_on_submitted_rejected
    """
    grade = create_grade()
    customer = create_customer()
    quote = create_draft_quote(customer["id"], grade["id"],
                               line_overrides={"bbox_width_mm": 50,
                                               "bbox_height_mm": 50})
    priced = validate_success(api.price_quote(quote["id"], quote["version"], EST))
    submitted = validate_success(api.submit_quote(priced["id"], EST))

    # Carry the quote's CURRENT version so only the state precondition fails.
    resp = api.price_quote(submitted["id"], submitted["version"], EST)
    validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_OPEN, 409)


# --- terminal lockdown (Corner: terminal_state_lockdown_accepted_quote) -----

def test_accepted_quote_is_terminal(api):
    """PRD §3.4: "ACCEPTED, EXPIRED, and REJECTED are terminal quote states."
    PRD §3.4: "an `Estimator` may return a SUBMITTED quote to DRAFT — any other
    source state is `ERR_QUOTE_NOT_OPEN`."

    Design: Corner/state_machines/terminal_state_lockdown_accepted_quote
    """
    grade = create_grade()
    customer = create_customer()
    create_full_sheet(grade["id"])
    create_machine("LASER")
    # Feature-free line: routing is LASER-only (PRD §3.6), matching the single
    # LASER machine registered above so the accept cascade can succeed.
    quote = create_submitted_quote(customer["id"], grade["id"],
                                   line_overrides={"bbox_width_mm": 50,
                                                   "bbox_height_mm": 50,
                                                   "hole_count": 0,
                                                   "corner_fillet_count": 0,
                                                   "bend_count": 0,
                                                   "weld_inches": 0})
    order = accept_quote(quote["id"], customer["id"])
    assert order["id"]

    current = validate_success(api.get_quote(quote["id"], EST))
    assert current["status"] == "ACCEPTED"

    validate_error(api.revise_quote(quote["id"], EST),
                   ApiErrorId.ERR_QUOTE_NOT_OPEN, 409)
    validate_error(api.reject_quote(quote["id"], rep_headers(customer)),
                   ApiErrorId.ERR_QUOTE_NOT_OPEN, 409)
    validate_error(api.price_quote(quote["id"], current["version"], EST),
                   ApiErrorId.ERR_QUOTE_NOT_OPEN, 409)
    validate_error(api.submit_quote(quote["id"], EST),
                   ApiErrorId.ERR_QUOTE_NOT_PRICED, 409)

    after = validate_success(api.get_quote(quote["id"], EST))
    assert after["status"] == "ACCEPTED"


# --- expiry sweep (Corner: quote_expiry_system_transition) ------------------

def test_quote_expiry_system_transition(api):
    """PRD §3.4: "every quote still SUBMITTED whose `expires_at` is at or
    before the logical clock moves to EXPIRED, its lines move to SUPERSEDED,
    and each expired quote appends a QUOTE_EXPIRED audit event."

    Design: Corner/state_machines/quote_expiry_system_transition
    """
    grade = create_grade()
    customer = create_customer()
    submitted = create_submitted_quote(customer["id"], grade["id"],
                                       line_overrides={"bbox_width_mm": 50,
                                                       "bbox_height_mm": 50})
    assert parse_instant(submitted["expires_at"]).date().isoformat() == "2026-08-15"

    set_clock("2026-08-16T00:00:00Z")
    quote = validate_success(api.get_quote(submitted["id"], EST))
    assert quote["status"] == "EXPIRED"
    for line in get_order_lines(submitted["id"]):
        assert line["status"] == "SUPERSEDED"


# --- customer suspension gating (Difficulty: submit_requires_customer_active)

def test_submit_blocked_when_customer_suspended(api):
    """PRD §3.1: "Suspension flips a customer to SUSPENDED, which blocks new
    quote submission: submitting a quote whose owner is suspended is rejected
    with `ERR_CUSTOMER_SUSPENDED`, and the same guard protects acceptance."

    Design: Difficulty/cross_entity_state_dependency/submit_requires_customer_active
    """
    grade = create_grade()
    customer = create_customer()
    priced = create_priced_quote(customer["id"], grade["id"],
                                 line_overrides=_simple_line())

    validate_success(api.suspend_customer(customer["id"], MGR))
    resp = api.submit_quote(priced["id"], EST)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_SUSPENDED, 409)

    quote = validate_success(api.get_quote(priced["id"], EST))
    assert quote["status"] == "PRICED"


def test_accept_blocked_when_customer_suspended_after_submit(api):
    """PRD §3.1: "submitting a quote whose owner is suspended is rejected with
    `ERR_CUSTOMER_SUSPENDED`, and the same guard protects acceptance."

    Design: Difficulty/cross_entity_state_dependency/submit_requires_customer_active
    """
    grade = create_grade()
    customer = create_customer()
    create_full_sheet(grade["id"])
    create_machine("LASER")
    submitted = create_submitted_quote(customer["id"], grade["id"],
                                       line_overrides=_simple_line())

    validate_success(api.suspend_customer(customer["id"], MGR))
    resp = api.accept_quote(submitted["id"], rep_headers(customer))
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_SUSPENDED, 409)

    quote = validate_success(api.get_quote(submitted["id"], EST))
    assert quote["status"] == "SUBMITTED"


# --- priority: state masks temporal (Difficulty) ----------------------------

def test_expired_and_rejected_accept_reports_state_error(api):
    """PRD §2.9: "Every request passes through a fixed cascade of validation
    tiers, and earlier tiers mask later ones: a caller always observes the
    failure from the earliest tier that applies." PRD §2.9: "Fourth, state:
    the target resource's current status must permit the requested transition
    ... Ninth through eleventh, temporal guards: quote expiry
    (`ERR_QUOTE_EXPIRED`, HTTP 409) ..."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_expired_accept
    """
    grade = create_grade()
    customer = create_customer()
    submitted = create_submitted_quote(customer["id"], grade["id"],
                                       line_overrides=_simple_line())

    validate_success(api.reject_quote(submitted["id"], rep_headers(customer)))
    set_clock("2026-09-01T00:00:00Z")

    resp = api.accept_quote(submitted["id"], rep_headers(customer))
    validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_OPEN, 409)


def test_expired_rejected_accept_leaves_no_trace(api):
    """PRD §3.4: "Acceptance by a `CustomerRep` is the pivotal act that
    converts a SUBMITTED quote into a fabrication order, and its guards run in
    the cascade order of §2.9: the quote must be SUBMITTED
    (`ERR_QUOTE_NOT_OPEN`) ..."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_expired_accept
    """
    grade = create_grade()
    customer = create_customer()
    submitted = create_submitted_quote(customer["id"], grade["id"],
                                       line_overrides=_simple_line())

    validate_success(api.reject_quote(submitted["id"], rep_headers(customer)))
    set_clock("2026-09-01T00:00:00Z")

    validate_error(api.accept_quote(submitted["id"], rep_headers(customer)),
                   ApiErrorId.ERR_QUOTE_NOT_OPEN, 409)

    quote = validate_success(api.get_quote(submitted["id"], EST))
    assert quote["status"] == "REJECTED"
    orders, _meta = validate_paginated(
        api.list_orders(MGR, params={"quote_id": submitted["id"]}))
    assert orders == [], "a rejected acceptance must not create an order"


# --- OCC on price (Corner: occ_stale_version_on_price) ----------------------

def test_occ_stale_version_on_price(api):
    """PRD §2.7: "Re-pricing a quote requires the request to carry
    `expected_quote_version`, the caller's last-observed `version` of the
    quote; if the quote's version has advanced since the client last read it
    — another writer may have revised its lines or its expedite tier — the
    re-price is rejected with `ERR_STALE_VERSION` (HTTP 412) ..."

    Design: Corner/validations/occ_stale_version_on_price
    """
    grade = create_grade()
    customer = create_customer()
    quote = create_draft_quote(customer["id"], grade["id"],
                               line_overrides={"bbox_width_mm": 50,
                                               "bbox_height_mm": 50})

    priced = validate_success(api.price_quote(quote["id"], quote["version"], EST))
    validate_success(api.submit_quote(priced["id"], EST))
    revised = validate_success(api.revise_quote(priced["id"], EST))
    stale_version = revised["version"]

    # A legitimate re-price at the current version succeeds and advances it.
    repriced = validate_success(
        api.price_quote(revised["id"], stale_version, EST))
    validate_success(api.submit_quote(repriced["id"], EST))
    back_to_draft = validate_success(api.revise_quote(repriced["id"], EST))
    assert back_to_draft["status"] == "DRAFT"

    # Replay carrying the superseded version: state-valid DRAFT, OCC rejects.
    resp = api.price_quote(back_to_draft["id"], stale_version, EST)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    after = validate_success(api.get_quote(back_to_draft["id"], EST))
    assert after["status"] == "DRAFT"
    assert after["version"] == back_to_draft["version"], (
        "a rejected guarded write must not mutate the quote"
    )


# --- logical clock default (Corner: clock_default_is_fixed_epoch) -----------

def test_clock_default_is_fixed_epoch(api):
    """PRD §2.4: "At startup the logical clock reads exactly
    2026-08-01T00:00:00Z, and it never falls back to wall-clock time
    afterward."

    Design: Corner/endpoints/clock_default_is_fixed_epoch
    """
    grade = create_grade()
    customer = create_customer()
    submitted = create_submitted_quote(customer["id"], grade["id"],
                                       line_overrides=_simple_line())
    assert parse_instant(submitted["submitted_at"]) == parse_instant(CLOCK_DEFAULT), (
        "a quote submitted before any clock call is stamped with the fixed epoch"
    )

    echoed = set_clock("2026-08-02T00:00:00Z")
    assert parse_instant(echoed["current_utc"]) == parse_instant(
        "2026-08-02T00:00:00Z")

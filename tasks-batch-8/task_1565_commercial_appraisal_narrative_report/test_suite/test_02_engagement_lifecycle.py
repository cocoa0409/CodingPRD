"""Engagement letter lifecycle: initial state, submit/accept/decline,
complexity tiers, turnaround and capacity gates, letter expiry sweep, and
post-accept read consistency (PRD §2.4, §3.1, §3.2)."""
from test_helpers import (
    TEST_USERS,
    assert_timestamp_prefix,
    create_engagement,
    create_in_progress_engagement,
    create_parties,
    create_submitted_engagement,
    validate_error,
    validate_success,
)

EM = TEST_USERS["engagement_manager_headers"]


def test_engagement_initial_state_draft(api):
    """PRD §3.2: "The letter is born in `DRAFT` status." PRD §3.2: the fee is
    only "computes and stores `quoted_fee_cents`" at submission, so before
    submission there is no stored quote.

    Design: Corner/state_machines/engagement_initial_state_draft
    """
    parties = create_parties()
    eng = create_engagement(parties)
    assert eng["status"] == "DRAFT"
    assert eng.get("quoted_fee_cents") is None, (
        f"quoted_fee_cents must be null before submit, got {eng.get('quoted_fee_cents')}")


def test_engagement_submit_twice_returns_409(api):
    """PRD §3.2: "Submitting the letter to the client moves the engagement
    from `DRAFT` to `PENDING_ACCEPTANCE`." PRD §2.9: "The target resource
    must stand in a from-state the transition allows — otherwise
    `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

    Design: Corner/state_machines/engagement_submit_twice_returns_409
    """
    parties = create_parties()
    eng = create_submitted_engagement(parties)
    assert eng["status"] == "PENDING_ACCEPTANCE"
    res = api.submit_engagement(eng["id"], EM)
    validate_error(res, "ERR_INVALID_STATE_TRANSITION", expected_status=409)


def test_engagement_decline_then_accept_returns_409(api):
    """PRD §3.2: "`COMPLETED`, `CANCELLED`, `DECLINED`, and `EXPIRED` are the
    engagement's terminal states." An accept against the terminal DECLINED
    letter fails state validity with `ERR_INVALID_STATE_TRANSITION` (§2.9).

    Design: Corner/state_machines/engagement_decline_then_accept_returns_409
    """
    parties = create_parties()
    eng = create_submitted_engagement(parties)
    declined = validate_success(
        api.decline_engagement(eng["id"], {}, parties["client_headers"]), 200)
    assert declined["status"] == "DECLINED"
    res = api.accept_engagement(eng["id"], parties["client_headers"])
    validate_error(res, "ERR_INVALID_STATE_TRANSITION", expected_status=409)


def test_license_status_noop_returns_409(api):
    """PRD §3.1: "setting the status the license already holds is rejected
    with `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/license_status_noop_returns_409
    """
    parties = create_parties()
    res = api.set_license_status(
        parties["author"]["id"], {"status": "ACTIVE"}, EM)
    validate_error(res, "ERR_INVALID_STATE_TRANSITION", expected_status=409)


def test_engagement_letter_expiry_sweep(api):
    """PRD §2.4: "a letter in `PENDING_ACCEPTANCE` moves to `EXPIRED` when
    the new clock value is strictly later than fourteen days after its
    `submitted_at`; a letter whose fourteenth day has been reached exactly —
    the clock reading precisely fourteen days after `submitted_at` — remains
    `PENDING_ACCEPTANCE` and may still be accepted." PRD §3.2: "the letter
    must still be open — one already swept to `EXPIRED` rejects with
    `ERR_INVALID_STATE_TRANSITION`".

    Design: Corner/calculations/engagement_letter_expiry_sweep
    """
    parties = create_parties()
    eng = create_submitted_engagement(parties)
    assert_timestamp_prefix(eng["submitted_at"], "2026-08-01T00:00:00")

    api.set_clock({"to_iso8601": "2026-08-15T00:00:00Z"}, EM)
    at_14 = validate_success(api.get_engagement(eng["id"], EM), 200)
    assert at_14["status"] == "PENDING_ACCEPTANCE", (
        "exactly fourteen days after submitted_at the letter must remain "
        f"PENDING_ACCEPTANCE, got {at_14['status']}")

    api.set_clock({"to_iso8601": "2026-08-15T00:00:01Z"}, EM)
    past = validate_success(api.get_engagement(eng["id"], EM), 200)
    assert past["status"] == "EXPIRED", (
        f"one second past the validity window the sweep must expire the letter, "
        f"got {past['status']}")

    res = api.accept_engagement(eng["id"], parties["client_headers"])
    validate_error(res, "ERR_INVALID_STATE_TRANSITION", expected_status=409)


def test_immediate_read_after_accept(api):
    """PRD §3.2: "Upon acceptance the letter stamps `accepted_at` from the
    logical clock, computes `due_date` as `accepted_at` plus the requested
    turnaround in days, recomputes the fee and locks it into
    `final_fee_cents`, and bumps the engagement's `version`." PRD §3.2: "the
    subtotal starts from a tier base — 250,000 cents for `LOW`, 450,000 cents
    for `STANDARD`, or 900,000 cents for `HIGH`."

    Design: Corner/consistency_model/immediate_read_after_accept
    """
    bundle = create_in_progress_engagement()
    eng = validate_success(
        api.get_engagement(bundle["engagement"]["id"], EM), 200)
    assert eng["status"] == "IN_PROGRESS"
    assert eng["final_fee_cents"] == 450000
    assert_timestamp_prefix(eng["accepted_at"], "2026-08-01T00:00:00")
    assert_timestamp_prefix(eng["due_date"], "2026-08-31T00:00:00")


def test_complexity_tier_high_boundary(api):
    """PRD §3.2: "The `complexity_tier` is `HIGH` whenever the property is
    `SPECIAL_PURPOSE`, or the intended use is `LITIGATION`, or the building
    is at least 100,000 square feet — a building of exactly 100,000 square
    feet therefore lands in `HIGH`." and "From the tier comes
    `minimum_turnaround_days`: ten calendar days for `LOW`, fifteen for
    `STANDARD`, and twenty-five for `HIGH`."

    Design: Corner/calculations/complexity_tier_high_boundary
    """
    parties = create_parties()
    eng_hi = create_engagement(
        parties, property_address="1 Big Box", building_sf=100000,
        requested_turnaround_days=45)
    eng_md = create_engagement(
        parties, property_address="2 Mid Ave", building_sf=99999,
        requested_turnaround_days=30)
    assert eng_hi["complexity_tier"] == "HIGH"
    assert eng_hi["minimum_turnaround_days"] == 25
    assert eng_md["complexity_tier"] == "STANDARD"
    assert eng_md["minimum_turnaround_days"] == 15


def test_engagement_low_tier_computed(api):
    """PRD §3.2: "Failing all three of those, the tier is `LOW` only when
    every one of three conditions holds together: the building is under
    10,000 square feet (so 9,999 square feet qualifies), the property type is
    `RETAIL` or `INDUSTRIAL`, and the intended use is `FINANCING`." and "From
    the tier comes `minimum_turnaround_days`: ten calendar days for `LOW`,
    fifteen for `STANDARD`, and twenty-five for `HIGH`."

    Design: Corner/entities/engagement_low_tier_computed
    """
    parties = create_parties()
    eng = create_engagement(
        parties, property_address="5 Shop Ln", property_type="RETAIL",
        building_sf=9999, requested_turnaround_days=20)
    assert eng["complexity_tier"] == "LOW"
    assert eng["minimum_turnaround_days"] == 10


def test_turnaround_minimum_exact_boundary_accepts_at_minimum(api):
    """PRD §3.2: "then turnaround feasibility, rejecting with
    `ERR_TURNAROUND_INFEASIBLE` when `requested_turnaround_days` is less than
    `minimum_turnaround_days`" — a STANDARD letter at exactly the fifteen-day
    minimum is not less than the minimum and accepts.

    Design: Difficulty/boundary_precision_check/turnaround_minimum_exact_boundary
    """
    parties = create_parties()
    eng_a = create_submitted_engagement(parties, requested_turnaround_days=15)
    accepted = validate_success(
        api.accept_engagement(eng_a["id"], parties["client_headers"]), 200)
    assert accepted["status"] == "IN_PROGRESS", (
        "requested_turnaround_days == minimum_turnaround_days (15) must accept")


def test_turnaround_minimum_one_day_below_rejected(api):
    """PRD §3.2: "then turnaround feasibility, rejecting with
    `ERR_TURNAROUND_INFEASIBLE` when `requested_turnaround_days` is less than
    `minimum_turnaround_days`" — a STANDARD letter at fourteen days is below
    the fifteen-day minimum and rejects.

    Design: Difficulty/boundary_precision_check/turnaround_minimum_exact_boundary
    """
    parties = create_parties()
    eng_b = create_submitted_engagement(parties, requested_turnaround_days=14)
    res = api.accept_engagement(eng_b["id"], parties["client_headers"])
    validate_error(res, "ERR_TURNAROUND_INFEASIBLE", expected_status=409)


def test_accept_contingent_fee_beats_turnaround_constraint(api):
    """PRD §3.2: "the contingent-fee prohibition fires next
    (`ERR_CONTINGENT_FEE_PROHIBITED`); then turnaround feasibility, rejecting
    with `ERR_TURNAROUND_INFEASIBLE` when `requested_turnaround_days` is less
    than `minimum_turnaround_days`". With both violated on one accept call,
    the contingent-fee error is reported.

    Design: Difficulty/priority_pair_validation_conflict/accept_safety_beats_constraint
    """
    parties = create_parties()
    eng = create_submitted_engagement(
        parties, requested_turnaround_days=1, is_contingent_fee=True)
    res = api.accept_engagement(eng["id"], parties["client_headers"])
    validate_error(res, "ERR_CONTINGENT_FEE_PROHIBITED", expected_status=409)


def test_accept_contingent_fee_leaves_letter_pending(api):
    """PRD §2.8: "an engagement letter carrying `is_contingent_fee` set to
    true can never be accepted, and the acceptance attempt is rejected with
    `ERR_CONTINGENT_FEE_PROHIBITED` (HTTP 409)" — the rejected attempt leaves
    the letter standing in `PENDING_ACCEPTANCE`.

    Design: Difficulty/priority_pair_validation_conflict/accept_safety_beats_constraint
    """
    parties = create_parties()
    eng = create_submitted_engagement(
        parties, requested_turnaround_days=1, is_contingent_fee=True)
    api.accept_engagement(eng["id"], parties["client_headers"])
    after = validate_success(api.get_engagement(eng["id"], EM), 200)
    assert after["status"] == "PENDING_ACCEPTANCE"


def test_appraiser_overcommitted_inside_window(api):
    """PRD §3.2: "if the author already holds another active engagement whose
    assignment window overlaps this one's, acceptance is rejected with
    `ERR_APPRAISER_OVERCOMMITTED`." The first engagement's window runs
    [2026-08-01, 2026-08-21); a second acceptance at 2026-08-20 overlaps.

    Design: Difficulty/resource_temporal_overlap/appraiser_assignment_half_open_window
    """
    parties = create_parties()
    eng_a = create_submitted_engagement(parties, requested_turnaround_days=20)
    accepted_a = validate_success(
        api.accept_engagement(eng_a["id"], parties["client_headers"]), 200)
    assert_timestamp_prefix(accepted_a["due_date"], "2026-08-21T00:00:00")

    api.set_clock({"to_iso8601": "2026-08-20T00:00:00Z"}, EM)
    eng_b = create_submitted_engagement(
        parties, property_address="101 Main St", requested_turnaround_days=15)
    res = api.accept_engagement(eng_b["id"], parties["client_headers"])
    validate_error(res, "ERR_APPRAISER_OVERCOMMITTED", expected_status=409)


def test_appraiser_window_half_open_adjacency_allows_accept(api):
    """PRD §3.2: "An assignment window runs from an engagement's
    `accepted_at` inclusive to its `due_date` exclusive, a half-open
    interval, so one engagement ending exactly when another begins does not
    conflict." PRD §3.2: "Upon acceptance the letter stamps `accepted_at`
    from the logical clock, computes `due_date` as `accepted_at` plus the
    requested turnaround in days, recomputes the fee and locks it into
    `final_fee_cents`, and bumps the engagement's `version`."

    Design: Difficulty/resource_temporal_overlap/appraiser_assignment_half_open_window
    """
    parties = create_parties()
    eng_a = create_submitted_engagement(parties, requested_turnaround_days=20)
    validate_success(
        api.accept_engagement(eng_a["id"], parties["client_headers"]), 200)

    api.set_clock({"to_iso8601": "2026-08-20T00:00:00Z"}, EM)
    eng_b = create_submitted_engagement(
        parties, property_address="101 Main St", requested_turnaround_days=15)

    api.set_clock({"to_iso8601": "2026-08-21T00:00:00Z"}, EM)
    accepted_b = validate_success(
        api.accept_engagement(eng_b["id"], parties["client_headers"]), 200)
    assert accepted_b["status"] == "IN_PROGRESS", (
        "acceptance exactly at the first engagement's due_date must succeed "
        "under half-open window semantics")
    assert_timestamp_prefix(accepted_b["due_date"], "2026-09-05T00:00:00")

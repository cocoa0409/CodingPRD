"""Incentive accrual variants and points_balance arithmetic.

Difficulty queue (A): dual_variant_calc (incentive), combinatorial_formula
(points_balance pinned order), compensating_invariant (points conservation).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_panelist_headers, TEST_USERS,
    setup_started_participation, setup_qualified_participation,
    setup_screened_in_participation, create_fielding_study_with_cell,
    setup_panelist_with_consent, create_screening_participation,
    submit_payload, get_panelist_version,
)

RM = TEST_USERS["research_manager_headers"]
OPS = TEST_USERS["panel_ops_headers"]
FC = TEST_USERS["field_coordinator_headers"]


def _accruals_for_participation(api, panelist_id, participation_id):
    resp = api.list_incentive_accruals(OPS, params={"participation_id": participation_id})
    data, _ = __import__("test_helpers").validate_paginated(resp)
    return data


def test_incentive_provisional_then_finalized_diverge_on_points(api):
    """PRD §3.5: "The length bonus rewards longer surveys in steps: take the
    study's `estimated_minutes`, divide by the bonus step of 5 minutes, round that
    quotient **up** to the next whole number of steps, and multiply by 10 points
    per step."
    PRD §2.8: "When a participation screens in, a provisional accrual is created
    in `HELD` status." "A `HELD` accrual does *not* count toward a panelist's
    spendable balance; only a `CREDITED` accrual does."
    PRD §3.5: "The finalized points are the provisional points multiplied by this
    multiplier, rounded half-up to a whole number." "When finalization runs, the
    held provisional accrual becomes `CREDITED` and its `points` value is replaced
    by this finalized figure."

    Design: Difficulty/dual_variant_calc/incentive_provisional_vs_finalized_diverge_on_points
    """
    study, cell, panelist, participation = setup_started_participation(
        target_n=2, study_overrides={"base_incentive_points": 100, "estimated_minutes": 10})
    # Provisional points are the raw base + length_bonus = 100 + ceil(10/5)*10 = 120.
    assert participation["provisional_points"] == 120, \
        f"provisional_points should be 120, got {participation['provisional_points']}"

    ph = make_panelist_headers(panelist["id"])
    submitted = validate_success(api.submit_participation(
        participation["id"], submit_payload(completion_seconds=600, straightline_run=0), ph))
    assert submitted["quality_score"] == 100, f"expected score 100, got {submitted['quality_score']}"
    assert submitted["quality_status"] == "PASS"
    assert submitted["screening_status"] == "QUALIFIED"

    # The held provisional accrual is finalized: CREDITED with finalized points 150
    # (120 * 1.25, since quality_score 100 >= 90 -> multiplier 1.25).
    accruals = _accruals_for_participation(api, panelist["id"], participation["id"])
    assert len(accruals) >= 1, "expected at least one accrual for the participation"
    credited = [a for a in accruals if a["status"] == "CREDITED"]
    assert len(credited) == 1, f"expected exactly one CREDITED accrual, got {len(credited)}"
    assert credited[0]["points"] == 150, \
        f"finalized credited accrual should read points==150, got {credited[0]['points']}"

    panelist_data = validate_success(api.get_panelist(panelist["id"], OPS))
    assert panelist_data["points_balance"] == 150, \
        f"points_balance should be 150 after finalize, got {panelist_data['points_balance']}"


def test_provisional_hold_excluded_from_balance_before_finalize(api):
    """PRD §2.8: "A `HELD` accrual does *not* count toward a panelist's spendable
    balance; only a `CREDITED` accrual does. When a participation screens in, a
    provisional accrual is created in `HELD` status."

    Design: Difficulty/dual_variant_calc/incentive_provisional_vs_finalized_diverge_on_points
    """
    study, cell, panelist, participation = setup_screened_in_participation(
        target_n=2, study_overrides={"base_incentive_points": 100, "estimated_minutes": 10})
    assert participation["provisional_points"] == 120

    # The provisional accrual is HELD, so the balance is still 0.
    panelist_data = validate_success(api.get_panelist(panelist["id"], OPS))
    assert panelist_data["points_balance"] == 0, \
        f"HELD provisional must not count toward balance, got {panelist_data['points_balance']}"


def test_points_balance_excludes_requested_payout_until_approved(api):
    """PRD §2.8: "A payout request only consumes points once it reaches `APPROVED`
    — a request still in `REQUESTED` status does not yet reduce the balance
    available to a competing request."

    Design: Difficulty/combinatorial_formula/points_balance_pinned_order_requested_excluded
    """
    study, cell, panelist, participation = setup_qualified_participation(
        target_n=2, study_overrides={"base_incentive_points": 100, "estimated_minutes": 10})
    pid = panelist["id"]
    ph = make_panelist_headers(pid)

    # Balance is 150 from the finalized accrual.
    v0 = get_panelist_version(pid)
    bal = validate_success(api.get_panelist(pid, OPS))["points_balance"]
    assert bal == 150, f"expected balance 150, got {bal}"

    # Two REQUESTED payouts of 100 each; neither subtracts yet.
    reqA = validate_success(api.create_payout_request(
        {"panelist_id": pid, "payout_method": "CASH", "points_requested": 100,
         "expected_panelist_version": v0}, ph), expected_status=201)
    v1 = get_panelist_version(pid)
    reqB = validate_success(api.create_payout_request(
        {"panelist_id": pid, "payout_method": "CASH", "points_requested": 100,
         "expected_panelist_version": v1}, ph), expected_status=201)

    bal_after_requests = validate_success(api.get_panelist(pid, OPS))["points_balance"]
    assert bal_after_requests == 150, \
        f"REQUESTED payouts must not reduce balance, got {bal_after_requests}"


def test_points_balance_subtracts_only_on_approval(api):
    """PRD §3.7: "Approval is the moment the points are consumed — once `APPROVED`,
    the `points_requested` are subtracted from the panelist's spendable balance".
    PRD §3.7: "A `PanelOps` operator approves a request, moving it `REQUESTED →
    APPROVED`, but only if the panelist's current `points_balance` is at least the
    `points_requested` at approval time; an underfunded request is rejected with
    `ERR_INSUFFICIENT_POINTS` (HTTP 422)."

    Design: Difficulty/combinatorial_formula/points_balance_pinned_order_requested_excluded
    """
    study, cell, panelist, participation = setup_qualified_participation(
        target_n=2, study_overrides={"base_incentive_points": 100, "estimated_minutes": 10})
    pid = panelist["id"]
    ph = make_panelist_headers(pid)

    v0 = get_panelist_version(pid)
    reqA = validate_success(api.create_payout_request(
        {"panelist_id": pid, "payout_method": "CASH", "points_requested": 100,
         "expected_panelist_version": v0}, ph), expected_status=201)
    v1 = get_panelist_version(pid)
    reqB = validate_success(api.create_payout_request(
        {"panelist_id": pid, "payout_method": "CASH", "points_requested": 100,
         "expected_panelist_version": v1}, ph), expected_status=201)

    # Approving reqA consumes 100; balance falls to 50.
    validate_success(api.approve_payout_request(reqA["id"], OPS))
    bal = validate_success(api.get_panelist(pid, OPS))["points_balance"]
    assert bal == 50, f"expected balance 50 after approving reqA, got {bal}"

    # Approving reqB now fails: balance 50 < 100.
    validate_error(api.approve_payout_request(reqB["id"], OPS),
                   ApiErrorId.ERR_INSUFFICIENT_POINTS.value)


def test_provisional_then_void_conserves_points_balance(api):
    """PRD §2.8: "When instead the participation falls out, the held provisional
    accrual flips to `VOID` and no points are ever credited."
    PRD §3.4: "every participation on that study still in `SCREENING` or
    `SCREENED_IN` is forced to `VOIDED` — this is the study-closure cascade. Each
    such void releases that participation's reserved seat on its quota cell and
    flips its held provisional accrual to `VOID`."

    Design: Difficulty/compensating_invariant/provisional_then_void_conserves_points_balance
    """
    study, cell, panelist, participation = setup_screened_in_participation(
        target_n=2, study_overrides={"base_incentive_points": 100, "estimated_minutes": 10})
    pid = panelist["id"]
    assert participation["provisional_points"] == 120

    # HELD provisional excluded from balance: balance is 0 before close.
    bal_before = validate_success(api.get_panelist(pid, OPS))["points_balance"]
    assert bal_before == 0, f"expected 0 before close, got {bal_before}"

    # Closing the study voids the screened-in participation and its held accrual.
    validate_success(api.close_study(study["id"], RM))
    part_after = validate_success(api.get_participation(participation["id"], OPS))
    assert part_after["screening_status"] == "VOIDED"

    accruals = _accruals_for_participation(api, pid, participation["id"])
    prov = [a for a in accruals if a["accrual_kind"] == "PROVISIONAL"]
    assert len(prov) == 1, f"expected one PROVISIONAL accrual, got {len(prov)}"
    assert prov[0]["status"] == "VOID", \
        f"provisional accrual must be VOID after close, got {prov[0]['status']}"

    # Points conserved at 0 across reserve+void round trip (zero drift).
    bal_after = validate_success(api.get_panelist(pid, OPS))["points_balance"]
    assert bal_after == 0, f"expected balance 0 after void, got {bal_after}"

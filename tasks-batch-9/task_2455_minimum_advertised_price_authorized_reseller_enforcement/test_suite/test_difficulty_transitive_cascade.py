"""Cascades that travel two or three hops from the row the client touched.

A termination notice reaches a reseller, its agreement and the units in that
reseller's warehouse; a chargeback reversal reaches a distributor's standing and
from there the review flag of every reseller sourcing from it.
"""
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import BCM_HEADERS, COUNSEL_2_HEADERS, COUNSEL_HEADERS, api_client
from test_helpers.assertions import assert_same_instant, violation_points
from test_helpers.factories import (
    chargeback_dispute_decision_payload,
    chargeback_dispute_payload,
)
from test_helpers.fixtures import (
    assess_chargeback,
    create_active_agreement,
    create_confirmed_trace,
    create_detected_violation,
    create_distributor,
    create_product,
    create_published_policy,
    create_reseller,
    create_serial_unit,
    issue_notice,
    pin_clock,
    read_agreement,
    read_chargeback,
    read_distributor,
    read_notice,
    read_reseller,
    read_serial_unit,
    ship_unit_downstream,
)
from test_helpers.test_users import make_distributor_headers

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_10 = "2026-08-10T00:00:00Z"
OBSERVED_AUG_05 = "2026-08-05T00:00:00Z"
SUSPENSION_STARTS = "2026-08-15T00:00:00Z"
SUSPENSION_ENDS = "2026-08-25T00:00:00Z"


# --------------------------------------------------------------------------- #
# Instance 1 — a termination notice cascading to the agreement and its units
# --------------------------------------------------------------------------- #
def _setup_ladder_to_termination():
    """Walk one marketplace reseller up all three rungs with a unit in its warehouse."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy()
    product = create_product(
        policy["id"], msrp_cents=15000, standard_map_floor_cents=10000, serialization_enabled=True
    )
    distributor = create_distributor(legal_name="Northwind Cascade Distribution")
    reseller = create_reseller(
        primary_channel="MARKETPLACE", sourcing_distributor_id=distributor["id"]
    )
    agreement = create_active_agreement(
        reseller["id"], policy["id"], permitted_channels=["MARKETPLACE"]
    )
    unit = create_serial_unit(
        product["id"], distributor["id"], serial_number="SN-20", lot_code="LOT-C"
    )
    unit = ship_unit_downstream(unit["id"], distributor["id"], reseller["id"])
    assert unit["status"] == "SHIPPED_TO_RESELLER"

    pin_clock(CLOCK_AUG_10)
    violations = []
    notices = []
    for index in range(3):
        violation, _observation, _evaluation = create_detected_violation(
            product["id"],
            reseller["id"],
            listed_price_cents=8000,
            channel="MARKETPLACE",
            observed_at=OBSERVED_AUG_05,
            listing_url=f"https://marketplace.example/cascade-{index}",
        )
        violations.append(violation)
    notices.append(issue_notice(reseller["id"], violations[0]["id"]))
    notices.append(
        issue_notice(
            reseller["id"],
            violations[1]["id"],
            suspension_starts_at=SUSPENSION_STARTS,
            suspension_ends_at=SUSPENSION_ENDS,
        )
    )
    return {
        "policy": policy,
        "product": product,
        "distributor": distributor,
        "reseller": reseller,
        "agreement": agreement,
        "unit": unit,
        "violations": violations,
        "notices": notices,
    }


def _terminate(world):
    """Issue the third notice, which the ladder computes as TERMINATION."""
    return issue_notice(
        world["reseller"]["id"], world["violations"][2]["id"], headers=COUNSEL_2_HEADERS
    )


def test_the_ladder_advances_one_rung_per_notice_up_to_termination():
    """Points that justify termination outright still only earn the next rung up.

    PRD: "**The ladder therefore advances at most one rung per notice**: a
    first-offence listing so far below the floor that the points justify termination
    still only earns a warning, because a reseller who has never been warned cannot be
    terminated."

    Design: Difficulty/transitive_cascade/termination_notice_cascades_reseller_agreement_serial_units
    """
    world = _setup_ladder_to_termination()
    first, second = world["notices"]

    assert first["rung"] == "WARNING"
    assert first["assessed_points"] == violation_points(10000, 8000, "MARKETPLACE", 0) == 6
    assert first["cumulative_points_at_issue"] == 6

    assert second["rung"] == "SUSPENSION"
    assert second["assessed_points"] == violation_points(10000, 8000, "MARKETPLACE", 1) == 8
    assert second["cumulative_points_at_issue"] == 14

    third = _terminate(world)
    assert third["rung"] == "TERMINATION"
    assert third["assessed_points"] == violation_points(10000, 8000, "MARKETPLACE", 2) == 9
    assert third["cumulative_points_at_issue"] == 23
    assert third["issued_by_user_id"] == "counsel-2"


def test_the_termination_notice_drives_both_reseller_axes_to_their_terminal_pair():
    """Termination is the only act that reaches the CUT_OFF supply state.

    PRD: "A `TERMINATION` notice — legal from `AUTHORIZED` or `SUSPENDED` — drives the
    reseller to `TERMINATED` on the authorization axis, `CUT_OFF` on the supply axis
    and `TERMINATION` as the `hold_reason`, stamps `terminated_at` with the current
    clock and clears `suspension_ends_at` to null."

    Design: Difficulty/transitive_cascade/termination_notice_cascades_reseller_agreement_serial_units
    """
    world = _setup_ladder_to_termination()
    suspended = read_reseller(world["reseller"]["id"])
    assert suspended["authorization_status"] == "SUSPENDED"
    assert suspended["hold_reason"] == "SUSPENSION"

    _terminate(world)

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "TERMINATED"
    assert reseller["supply_status"] == "CUT_OFF"
    assert reseller["hold_reason"] == "TERMINATION"
    assert_same_instant(reseller["terminated_at"], CLOCK_AUG_10, "terminated_at")
    assert reseller["suspension_ends_at"] is None


def test_termination_cascades_through_the_agreement_into_a_stock_recall():
    """The recall is caused by the agreement's termination, one hop further out.

    PRD: "When the reseller's `authorization_status` becomes `TERMINATED`, the
    agreement moves `ACTIVE → TERMINATED` with `closed_reason` recorded as
    `SUPPLY_TERMINATED` and its `version` advanced, and this transition in turn recalls
    stock: every serialized unit whose `downstream_reseller_id` is this agreement's
    reseller and whose custody state is `SHIPPED_TO_RESELLER` moves to `RECALLED`, each
    with its own `version` advanced."

    Design: Difficulty/transitive_cascade/termination_notice_cascades_reseller_agreement_serial_units
    """
    world = _setup_ladder_to_termination()
    _terminate(world)

    agreement = read_agreement(world["agreement"]["id"])
    assert agreement["status"] == "TERMINATED"
    assert agreement["closed_reason"] == "SUPPLY_TERMINATED"

    unit = read_serial_unit(world["unit"]["id"])
    assert unit["status"] == "RECALLED"
    assert unit["downstream_reseller_id"] == world["reseller"]["id"]


def test_a_terminated_resellers_open_violations_close_but_keep_their_points():
    """Closing the history moot does not forgive the points already charged.

    PRD: "Every violation of that reseller whose status is `DETECTED`, `NOTICED` or
    `DISPUTED` moves to `CLOSED_MOOT` with `resolution_reason` recorded as
    `RESELLER_TERMINATED` and its own `version` advanced — and critically, the
    `assessed_points` on those violations are **retained** in the ledger, because a
    terminated reseller's history is not forgiven."

    Design: Difficulty/transitive_cascade/termination_notice_cascades_reseller_agreement_serial_units
    """
    world = _setup_ladder_to_termination()
    _terminate(world)

    rows, meta = validate_paginated(
        api_client.list_violations(
            BCM_HEADERS, params={"reseller_id": world["reseller"]["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 3
    assert sorted(row["assessed_points"] for row in rows) == [6, 8, 9]
    for row in rows:
        assert row["status"] == "CLOSED_MOOT"
        assert row["resolution_reason"] == "RESELLER_TERMINATED"

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["violation_points_total"] == 23

    # The suspension notice is untouched by the termination that followed it.
    suspension_notice = read_notice(world["notices"][1]["id"])
    assert suspension_notice["status"] == "ISSUED"
    assert suspension_notice["rung"] == "SUSPENSION"


# --------------------------------------------------------------------------- #
# Instance 2 — a chargeback reversal cascading to the reseller review flag
# --------------------------------------------------------------------------- #
def _setup_probation_from_diversion():
    """A distributor pushed onto probation with one reseller sourcing from it."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy()
    product = create_product(policy["id"], serialization_enabled=True)
    distributor = create_distributor(
        legal_name="Northwind Review Flag Distribution", annual_chargeback_cap_cents=5_000_000
    )
    reseller = create_reseller(sourcing_distributor_id=distributor["id"])
    assert reseller["review_required"] is False

    pin_clock(CLOCK_AUG_10)
    purchase, unit, _observation = create_confirmed_trace(
        product["id"], distributor["id"], serial_number="SN-30", lot_code="LOT-D"
    )
    chargeback = assess_chargeback(distributor["id"], purchase["id"], diverted_units=4)
    return {
        "product": product,
        "distributor": distributor,
        "reseller": reseller,
        "unit": unit,
        "chargeback": chargeback,
    }


def _reverse(world):
    validate_success(
        api_client.dispute_chargeback(
            world["chargeback"]["id"],
            chargeback_dispute_payload(),
            make_distributor_headers(world["distributor"]["id"]),
        )
    )
    return validate_success(
        api_client.decide_chargeback_dispute(
            world["chargeback"]["id"],
            chargeback_dispute_decision_payload("REVERSE"),
            COUNSEL_HEADERS,
        )
    )


def test_a_chargeback_that_moves_a_distributor_onto_probation_raises_the_review_flag():
    """The sourcing clause of the review predicate fires on the standing change.

    PRD: "A reseller's `review_required` flag is a predicate rather than a sum: it is
    true when either the reseller declares a sourcing distributor whose `standing` is
    `PROBATION` or `SUSPENDED`, or at least one serialized unit whose
    `downstream_reseller_id` is this reseller has been traced to an unauthorized
    seller."

    Design: Difficulty/transitive_cascade/chargeback_reversal_cascades_standing_to_reseller_review_flag
    """
    world = _setup_probation_from_diversion()
    distributor = read_distributor(world["distributor"]["id"])
    assert distributor["standing"] == "PROBATION"
    assert distributor["diversion_score"] == 10.0
    assert distributor["chargeback_balance_cents"] == 10000

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["review_required"] is True


def test_reversal_restores_both_ledgers_and_lets_probation_fall_back_to_good():
    """Standing is re-derived from the restored score rather than latched.

    PRD: "The distributor's `standing` is re-derived from the restored score after a
    reversal, which means `PROBATION` can fall back to `GOOD`."

    Design: Difficulty/transitive_cascade/chargeback_reversal_cascades_standing_to_reseller_review_flag
    """
    world = _setup_probation_from_diversion()
    reversed_row = _reverse(world)
    assert reversed_row["status"] == "REVERSED"

    distributor = read_distributor(world["distributor"]["id"])
    assert distributor["chargeback_balance_cents"] == 0
    assert distributor["diversion_score"] == 0
    assert distributor["standing"] == "GOOD"


def test_the_reversal_lowers_the_review_flag_while_the_trace_itself_survives():
    """Only the money and score reverse; the traced unit stays traced.

    PRD: "A `REVERSED` chargeback keeps its historical `amount_cents` and
    `score_delta_applied` on the row for audit but contributes to neither sum."

    Design: Difficulty/transitive_cascade/chargeback_reversal_cascades_standing_to_reseller_review_flag
    """
    world = _setup_probation_from_diversion()
    _reverse(world)

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["review_required"] is False

    row = read_chargeback(world["chargeback"]["id"])
    assert row["status"] == "REVERSED"
    assert row["amount_cents"] == 10000
    assert row["score_delta_applied"] == 10.0

    unit = read_serial_unit(world["unit"]["id"])
    assert unit["status"] == "TRACED_UNAUTHORIZED"
    assert unit["downstream_reseller_id"] is None

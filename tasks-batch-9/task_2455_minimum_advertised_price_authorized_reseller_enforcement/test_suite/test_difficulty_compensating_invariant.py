"""Compensating actions that must return a derived ledger to exactly the value it
held before the act they reverse — and, next to each, the sibling action that
deliberately conserves nothing.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import COUNSEL_HEADERS, api_client
from test_helpers.assertions import assert_same_instant, violation_points
from test_helpers.factories import (
    chargeback_dispute_decision_payload,
    chargeback_dispute_payload,
)
from test_helpers.fixtures import (
    assess_chargeback,
    bootstrap_authorized_channel,
    create_confirmed_trace,
    create_detected_violation,
    create_distributor,
    create_product,
    create_published_policy,
    issue_notice,
    pin_clock,
    read_chargeback,
    read_compliance_summary,
    read_distributor,
    read_notice,
    read_reseller,
    read_serial_unit,
    read_violation,
    rescind_notice,
)
from test_helpers.test_users import make_distributor_headers

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_10 = "2026-08-10T00:00:00Z"
OBSERVED_AUG_05 = "2026-08-05T00:00:00Z"
SUSPENSION_STARTS = "2026-08-15T00:00:00Z"
SUSPENSION_ENDS = "2026-08-25T00:00:00Z"
RESCIND_REASON = "Suspension notice issued on evidence counsel could not stand behind."


# --------------------------------------------------------------------------- #
# Instance 1 — rescinding a notice restores the reseller's points ledger
# --------------------------------------------------------------------------- #
def _setup_warning_then_suspension():
    """Two marketplace breaches noticed in turn: a warning, then a suspension."""
    pin_clock(CLOCK_AUG_01)
    world = bootstrap_authorized_channel(
        policy_overrides={
            "cure_window_days": 10,
            "suspension_points_threshold": 6,
            "termination_points_threshold": 12,
        },
        product_overrides={"msrp_cents": 15000, "standard_map_floor_cents": 10000},
    )
    pin_clock(CLOCK_AUG_10)
    first_violation, _obs, _eval = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=8000,
        channel="MARKETPLACE",
        observed_at=OBSERVED_AUG_05,
        listing_url="https://marketplace.example/restore-1",
    )
    first_notice = issue_notice(world["reseller"]["id"], first_violation["id"])
    second_violation, _obs2, _eval2 = create_detected_violation(
        world["product"]["id"],
        world["reseller"]["id"],
        listed_price_cents=8000,
        channel="MARKETPLACE",
        observed_at=OBSERVED_AUG_05,
        listing_url="https://marketplace.example/restore-2",
    )
    second_notice = issue_notice(
        world["reseller"]["id"],
        second_violation["id"],
        suspension_starts_at=SUSPENSION_STARTS,
        suspension_ends_at=SUSPENSION_ENDS,
    )
    world.update(
        {
            "first_violation": first_violation,
            "first_notice": first_notice,
            "second_violation": second_violation,
            "second_notice": second_notice,
        }
    )
    return world


def test_the_suspension_notice_lands_the_ledger_on_fourteen_points():
    """Six points then eight, with the repeat weight applied to the second.

    PRD: "A reseller's `violation_points_total` equals the sum of `assessed_points` over
    that reseller's violations whose `assessed_points` is not null and whose `status` is
    one of `NOTICED`, `DISPUTED`, `CURED`, `ESCALATED` or `CLOSED_MOOT`."

    Design: Difficulty/compensating_invariant/notice_rescission_restores_reseller_points_ledger
    """
    world = _setup_warning_then_suspension()
    assert world["first_notice"]["rung"] == "WARNING"
    assert world["first_notice"]["assessed_points"] == violation_points(
        10000, 8000, "MARKETPLACE", 0
    ) == 6
    assert world["second_notice"]["rung"] == "SUSPENSION"
    assert world["second_notice"]["assessed_points"] == violation_points(
        10000, 8000, "MARKETPLACE", 1
    ) == 8
    assert world["second_notice"]["cumulative_points_at_issue"] == 14

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["violation_points_total"] == 14
    assert reseller["authorization_status"] == "SUSPENDED"


def test_rescission_subtracts_exactly_the_points_the_notice_added():
    """The ledger returns to the six points the surviving warning accounts for.

    PRD: "Otherwise the notice moves to `RESCINDED` with `closed_reason` recorded from
    the supplied reason and its `version` advanced, and the reversal reaches back into
    the violation: the cited violation is returned to status `DETECTED` with
    `assessed_points`, `assessed_floor_cents` and `cure_deadline_at` all cleared to null,
    and the notice's `assessed_points` are subtracted from the reseller's
    `violation_points_total`."

    Design: Difficulty/compensating_invariant/notice_rescission_restores_reseller_points_ledger
    """
    world = _setup_warning_then_suspension()
    rescinded = rescind_notice(world["second_notice"]["id"], reason=RESCIND_REASON)
    assert rescinded["status"] == "RESCINDED"
    assert rescinded["closed_reason"] == RESCIND_REASON

    # Returning the violation to DETECTED rather than voiding it is deliberate.
    violation = read_violation(world["second_violation"]["id"])
    assert violation["status"] == "DETECTED"
    assert violation["assessed_points"] is None
    assert violation["assessed_floor_cents"] is None
    assert violation["cure_deadline_at"] is None

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["violation_points_total"] == 6

    # The warning that preceded it is entirely untouched.
    surviving_violation = read_violation(world["first_violation"]["id"])
    assert surviving_violation["status"] == "NOTICED"
    assert surviving_violation["assessed_points"] == 6
    surviving_notice = read_notice(world["first_notice"]["id"])
    assert surviving_notice["status"] == "ISSUED"
    assert surviving_notice["rung"] == "WARNING"


def test_rescinding_a_suspension_reinstates_the_reseller_in_the_same_operation():
    """Both reseller axes come back and the served-suspension stamp is written.

    PRD: "When the rescinded notice's `rung` was `SUSPENSION` and the reseller is
    currently `SUSPENDED`, the reseller is reinstated in the same operation:
    `authorization_status` back to `AUTHORIZED`, `supply_status` to `OPEN`, `hold_reason`
    to `NONE`, `last_suspension_ended_at` stamped with the current clock,
    `suspension_ends_at` cleared to null, and the reseller's `version` advanced."

    Design: Difficulty/compensating_invariant/notice_rescission_restores_reseller_points_ledger
    """
    world = _setup_warning_then_suspension()
    version_before = read_reseller(world["reseller"]["id"])["version"]
    rescind_notice(world["second_notice"]["id"], reason=RESCIND_REASON)

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["authorization_status"] == "AUTHORIZED"
    assert reseller["supply_status"] == "OPEN"
    assert reseller["hold_reason"] == "NONE"
    assert reseller["suspension_ends_at"] is None
    assert_same_instant(
        reseller["last_suspension_ended_at"], CLOCK_AUG_10, "last_suspension_ended_at"
    )
    assert reseller["version"] == version_before + 1


def test_the_reconciliation_read_agrees_with_the_restored_ledger():
    """The rescinded notice drops out of the served-rung scan as well as the sum.

    PRD: "It reports `reseller_id`, the stored `violation_points_total`, the
    `contributing_violation_count` of violations that qualify under the ledger definition
    of §2.11, the `summed_assessed_points` obtained by adding up those violations'
    `assessed_points` — which must equal the stored total, since that is the whole point
    of the read — the `highest_issued_rung` served so far (reported as the empty-history
    case when no non-rescinded notice exists), the `next_rung` the ladder would install
    on the next notice, and the two gaps `points_to_suspension` and
    `points_to_termination`, each being the reseller's own governing thresholds minus the
    current total, floored at zero when the threshold has already been passed."

    Design: Difficulty/compensating_invariant/notice_rescission_restores_reseller_points_ledger
    """
    world = _setup_warning_then_suspension()
    rescind_notice(world["second_notice"]["id"], reason=RESCIND_REASON)

    summary = read_compliance_summary(world["reseller"]["id"])
    assert summary["violation_points_total"] == 6
    assert summary["summed_assessed_points"] == 6
    assert summary["contributing_violation_count"] == 1
    assert summary["highest_issued_rung"] == "WARNING"
    assert summary["next_rung"] == "SUSPENSION"
    assert summary["points_to_suspension"] == 0
    assert summary["points_to_termination"] == 6


# --------------------------------------------------------------------------- #
# Instance 2 — reversal restores both distributor ledgers; upholding conserves them
# --------------------------------------------------------------------------- #
def _setup_two_chargebacks():
    """Two traced units of one lot billed in turn, taking the distributor to probation."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy()
    product = create_product(
        policy["id"],
        sku="SKU-SER-6",
        msrp_cents=36000,
        standard_map_floor_cents=26000,
        serialization_enabled=True,
    )
    distributor = create_distributor(
        legal_name="East Distribution", annual_chargeback_cap_cents=5_000_000
    )
    pin_clock(CLOCK_AUG_10)
    first_purchase, first_unit, _obs = create_confirmed_trace(
        product["id"], distributor["id"], serial_number="SN-60", lot_code="LOT-G"
    )
    second_purchase, second_unit, _obs2 = create_confirmed_trace(
        product["id"], distributor["id"], serial_number="SN-61", lot_code="LOT-G"
    )
    first = assess_chargeback(distributor["id"], first_purchase["id"], diverted_units=4)
    second = assess_chargeback(distributor["id"], second_purchase["id"], diverted_units=2)
    return {
        "product": product,
        "distributor": distributor,
        "first_unit": first_unit,
        "second_unit": second_unit,
        "first": first,
        "second": second,
    }


def _dispute(world, chargeback_id):
    return validate_success(
        api_client.dispute_chargeback(
            chargeback_id,
            chargeback_dispute_payload(),
            make_distributor_headers(world["distributor"]["id"]),
        )
    )


def _decide(chargeback_id, decision):
    return validate_success(
        api_client.decide_chargeback_dispute(
            chargeback_id, chargeback_dispute_decision_payload(decision), COUNSEL_HEADERS
        )
    )


def test_upholding_a_disputed_chargeback_conserves_nothing_and_moves_nothing():
    """The upheld branch is the sibling that deliberately leaves both ledgers alone.

    PRD: "A `decision` of `UPHOLD` moves it `DISPUTED → UPHELD`: `dispute_rounds` is
    increased by one, `decision_reason` is recorded, the chargeback's `version` is
    advanced, and both ledgers are left exactly as they are — the `amount_cents` stays in
    the distributor's balance and the `score_delta_applied` stays in its diversion
    score."

    Design: Difficulty/compensating_invariant/chargeback_reversal_restores_money_and_score_ledgers_uphold_does_not
    """
    world = _setup_two_chargebacks()
    before = read_distributor(world["distributor"]["id"])
    assert before["chargeback_balance_cents"] == 18000
    assert before["diversion_score"] == 15.0
    assert before["standing"] == "PROBATION"

    _dispute(world, world["second"]["id"])
    upheld = _decide(world["second"]["id"], "UPHOLD")
    assert upheld["status"] == "UPHELD"
    assert upheld["dispute_rounds"] == 1

    after = read_distributor(world["distributor"]["id"])
    assert after["chargeback_balance_cents"] == 18000
    assert after["diversion_score"] == 15.0
    assert after["standing"] == "PROBATION"


def test_a_pending_dispute_alone_moves_neither_ledger():
    """DISPUTED still counts toward both sums, so raising a dispute changes nothing.

    PRD: "A distributor's `chargeback_balance_cents` equals the sum of `amount_cents`
    over that distributor's chargebacks whose `status` is `ASSESSED`, `DISPUTED` or
    `UPHELD`, and its `diversion_score` equals the sum of `score_delta_applied` over the
    same filtered set."

    Design: Difficulty/compensating_invariant/chargeback_reversal_restores_money_and_score_ledgers_uphold_does_not
    """
    world = _setup_two_chargebacks()
    _dispute(world, world["second"]["id"])
    _decide(world["second"]["id"], "UPHOLD")

    disputed = _dispute(world, world["first"]["id"])
    assert disputed["status"] == "DISPUTED"

    distributor = read_distributor(world["distributor"]["id"])
    assert distributor["chargeback_balance_cents"] == 18000
    assert distributor["diversion_score"] == 15.0
    assert distributor["standing"] == "PROBATION"


def test_reversal_restores_both_conserved_quantities_to_their_pre_assessment_values():
    """Assess-then-reverse is exact on the money ledger and on the score ledger.

    PRD: "A `decision` of `REVERSE` moves it `DISPUTED → REVERSED`, its single terminal
    state: `decision_reason` is recorded, the chargeback's `version` is advanced,
    `amount_cents` is subtracted from the distributor's `chargeback_balance_cents`,
    `score_delta_applied` is subtracted from its `diversion_score`, `standing` is
    re-derived from the restored score with the distributor's `version` advanced, and —
    because a standing that falls back from `PROBATION` to `GOOD` changes who is under
    review — the `review_required` flag is recomputed for every reseller whose
    `sourcing_distributor_id` names this distributor, with each changed reseller's
    `version` advanced."

    Design: Difficulty/compensating_invariant/chargeback_reversal_restores_money_and_score_ledgers_uphold_does_not
    """
    world = _setup_two_chargebacks()
    _dispute(world, world["second"]["id"])
    _decide(world["second"]["id"], "UPHOLD")
    _dispute(world, world["first"]["id"])

    reversed_row = _decide(world["first"]["id"], "REVERSE")
    assert reversed_row["status"] == "REVERSED"

    distributor = read_distributor(world["distributor"]["id"])
    assert distributor["chargeback_balance_cents"] == 8000
    assert distributor["diversion_score"] == 5.0
    assert distributor["standing"] == "GOOD"


def test_the_reversed_row_keeps_its_figures_and_the_traced_units_stay_traced():
    """Only the sums move; the historical rows and the custody states are preserved.

    PRD: "A `REVERSED` chargeback keeps its historical `amount_cents` and
    `score_delta_applied` on the row for audit but contributes to neither sum."

    Design: Difficulty/compensating_invariant/chargeback_reversal_restores_money_and_score_ledgers_uphold_does_not
    """
    world = _setup_two_chargebacks()
    _dispute(world, world["second"]["id"])
    _decide(world["second"]["id"], "UPHOLD")
    _dispute(world, world["first"]["id"])
    _decide(world["first"]["id"], "REVERSE")

    first = read_chargeback(world["first"]["id"])
    assert first["status"] == "REVERSED"
    assert first["amount_cents"] == 10000
    assert first["score_delta_applied"] == 10.0
    assert first["tier_rate_cents_per_unit"] == 2500

    second = read_chargeback(world["second"]["id"])
    assert second["status"] == "UPHELD"
    assert second["amount_cents"] == 8000
    assert second["tier_rate_cents_per_unit"] == 4000

    distributor = read_distributor(world["distributor"]["id"])
    assert distributor["shipped_units_total"] == 2

    for unit in (world["first_unit"], world["second_unit"]):
        assert read_serial_unit(unit["id"])["status"] == "TRACED_UNAUTHORIZED"

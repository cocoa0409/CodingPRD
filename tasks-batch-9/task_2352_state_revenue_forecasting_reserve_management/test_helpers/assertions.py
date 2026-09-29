"""Domain assertion helpers.

Each helper checks one PRD-defined shape or identity so the test bodies read as
statements about the contract rather than as long chains of dict lookups.
"""

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp


# --------------------------------------------------------------------------- #
# Identity, timestamps, versions (PRD §2.6)
# --------------------------------------------------------------------------- #
def assert_audit_record_shape(record: Dict[str, Any]) -> None:
    """An immutable audit record carries `id` and `created_at` and nothing else
    from the common-field set: no `updated_at`, no `version`."""
    assert "id" in record, f"audit record is missing id: {record}"
    assert "created_at" in record, f"audit record is missing created_at: {record}"
    assert is_iso8601_timestamp(record["created_at"]), (
        f"created_at is not an ISO 8601 UTC timestamp: {record['created_at']!r}"
    )
    assert "updated_at" not in record, f"audit record must not carry updated_at: {record}"
    assert "version" not in record, f"audit record must not carry version: {record}"


def assert_version(entity: Dict[str, Any], expected: int) -> None:
    assert entity.get("version") == expected, (
        f"expected version {expected}, got {entity.get('version')}"
    )


def assert_version_advanced_by(before: Dict[str, Any], after: Dict[str, Any], delta: int) -> None:
    assert after["version"] == before["version"] + delta, (
        f"expected version to advance by {delta} from {before['version']}, "
        f"got {after['version']}"
    )


# --------------------------------------------------------------------------- #
# Forecast cycle
# --------------------------------------------------------------------------- #
def assert_cycle_status(cycle: Dict[str, Any], expected: str) -> None:
    assert cycle["status"] == expected, (
        f"expected cycle status {expected}, got {cycle['status']}"
    )


def assert_certified_aggregates(
    cycle: Dict[str, Any],
    *,
    total_cents: int,
    one_time_cents: int,
    recurring_cents: int,
) -> None:
    assert cycle["certified_total_cents"] == total_cents, (
        f"certified_total_cents {cycle['certified_total_cents']} != {total_cents}"
    )
    assert cycle["certified_one_time_cents"] == one_time_cents, (
        f"certified_one_time_cents {cycle['certified_one_time_cents']} != {one_time_cents}"
    )
    assert cycle["certified_recurring_total_cents"] == recurring_cents, (
        f"certified_recurring_total_cents {cycle['certified_recurring_total_cents']} "
        f"!= {recurring_cents}"
    )
    assert cycle["certified_total_cents"] - cycle["certified_one_time_cents"] == recurring_cents, (
        "the recurring total must be the headline total less the non-recurring sum"
    )


def assert_shortfall(cycle: Dict[str, Any], *, gap_cents: int, pct_bps: int) -> None:
    assert cycle["shortfall_gap_cents"] == gap_cents, (
        f"shortfall_gap_cents {cycle['shortfall_gap_cents']} != {gap_cents}"
    )
    assert cycle["shortfall_pct_bps"] == pct_bps, (
        f"shortfall_pct_bps {cycle['shortfall_pct_bps']} != {pct_bps}"
    )
    assert cycle["shortfall_gap_cents"] >= 0, "the shortfall gap is never negative"


# --------------------------------------------------------------------------- #
# Source estimates and rounds
# --------------------------------------------------------------------------- #
def assert_estimate_components(
    estimate: Dict[str, Any],
    *,
    weighted_scenario_cents: int,
    policy_adjustment_cents: int,
    judgmental_adjustment_cents: int,
    one_time_cents: int,
) -> None:
    """The four components, plus the two sums the PRD derives from them."""
    assert estimate["weighted_scenario_cents"] == weighted_scenario_cents, (
        f"weighted_scenario_cents {estimate['weighted_scenario_cents']} "
        f"!= {weighted_scenario_cents}"
    )
    assert estimate["policy_adjustment_cents"] == policy_adjustment_cents, (
        f"policy_adjustment_cents {estimate['policy_adjustment_cents']} "
        f"!= {policy_adjustment_cents}"
    )
    assert estimate["judgmental_adjustment_cents"] == judgmental_adjustment_cents, (
        f"judgmental_adjustment_cents {estimate['judgmental_adjustment_cents']} "
        f"!= {judgmental_adjustment_cents}"
    )
    assert estimate["one_time_cents"] == one_time_cents, (
        f"one_time_cents {estimate['one_time_cents']} != {one_time_cents}"
    )
    expected_recurring = (
        weighted_scenario_cents + policy_adjustment_cents + judgmental_adjustment_cents
    )
    assert estimate["recurring_component_cents"] == expected_recurring, (
        f"recurring_component_cents {estimate['recurring_component_cents']} "
        f"!= {expected_recurring}"
    )
    assert estimate["estimate_amount_cents"] == expected_recurring + one_time_cents, (
        f"estimate_amount_cents {estimate['estimate_amount_cents']} "
        f"!= {expected_recurring + one_time_cents}"
    )


def assert_round_comparison(
    round_data: Dict[str, Any],
    *,
    status: str,
    exec_total_cents: int,
    leg_total_cents: int,
    variance_bps: int,
    reconciled_total_cents: int,
    open_disagreement_count: int = 0,
) -> None:
    assert round_data["status"] == status, (
        f"expected round status {status}, got {round_data['status']}"
    )
    assert round_data["exec_total_cents"] == exec_total_cents, (
        f"exec_total_cents {round_data['exec_total_cents']} != {exec_total_cents}"
    )
    assert round_data["leg_total_cents"] == leg_total_cents, (
        f"leg_total_cents {round_data['leg_total_cents']} != {leg_total_cents}"
    )
    assert round_data["variance_bps"] == variance_bps, (
        f"variance_bps {round_data['variance_bps']} != {variance_bps}"
    )
    assert round_data["reconciled_total_cents"] == reconciled_total_cents, (
        f"reconciled_total_cents {round_data['reconciled_total_cents']} "
        f"!= {reconciled_total_cents}"
    )
    assert round_data["open_disagreement_count"] == open_disagreement_count, (
        f"open_disagreement_count {round_data['open_disagreement_count']} "
        f"!= {open_disagreement_count}"
    )


def assert_submission_dimensions(
    round_data: Dict[str, Any], *, exec_status: str, leg_status: str
) -> None:
    assert round_data["exec_submission_status"] == exec_status, (
        f"exec_submission_status {round_data['exec_submission_status']} != {exec_status}"
    )
    assert round_data["leg_submission_status"] == leg_status, (
        f"leg_submission_status {round_data['leg_submission_status']} != {leg_status}"
    )


# --------------------------------------------------------------------------- #
# Reserve fund
# --------------------------------------------------------------------------- #
def assert_adequacy_disclosure(
    fund: Dict[str, Any],
    *,
    volatility_index_bps: Optional[int] = None,
    target_pct_bps: Optional[int] = None,
    required_reserve_cents: Optional[int] = None,
    coverage_ratio_bps: Optional[int] = None,
    adequacy_band: Optional[str] = None,
    cushion_credit_bps: Optional[int] = None,
    disclosed_target_pct_bps: Optional[int] = None,
    cap_cents: Optional[int] = None,
) -> None:
    checks = {
        "volatility_index_bps": volatility_index_bps,
        "target_pct_bps": target_pct_bps,
        "required_reserve_cents": required_reserve_cents,
        "coverage_ratio_bps": coverage_ratio_bps,
        "adequacy_band": adequacy_band,
        "cushion_credit_bps": cushion_credit_bps,
        "disclosed_target_pct_bps": disclosed_target_pct_bps,
        "cap_cents": cap_cents,
    }
    for field, expected in checks.items():
        if expected is None:
            continue
        assert fund[field] == expected, f"{field} {fund[field]} != {expected}"


def assert_ledger_identity(
    fund: Dict[str, Any], transactions: Iterable[Dict[str, Any]]
) -> None:
    """`balance_cents` is `opening_balance_cents` plus the summed signed amounts
    of every ledger row of the fund."""
    rows = list(transactions)
    signed_sum = sum(row["signed_amount_cents"] for row in rows)
    expected = fund["opening_balance_cents"] + signed_sum
    assert fund["balance_cents"] == expected, (
        f"balance_cents {fund['balance_cents']} != opening "
        f"{fund['opening_balance_cents']} + ledger sum {signed_sum}"
    )


def assert_transaction_row(
    transaction: Dict[str, Any],
    *,
    origin: str,
    signed_amount_cents: int,
    gross_computed_cents: Optional[int] = None,
    overflow_returned_cents: Optional[int] = None,
    reverses_transaction_id: Optional[str] = None,
    source_cycle_id: Optional[str] = None,
) -> None:
    assert transaction["origin"] == origin, (
        f"expected origin {origin}, got {transaction['origin']}"
    )
    assert transaction["signed_amount_cents"] == signed_amount_cents, (
        f"signed_amount_cents {transaction['signed_amount_cents']} != {signed_amount_cents}"
    )
    if gross_computed_cents is not None:
        assert transaction["gross_computed_cents"] == gross_computed_cents, (
            f"gross_computed_cents {transaction['gross_computed_cents']} "
            f"!= {gross_computed_cents}"
        )
    if overflow_returned_cents is not None:
        assert transaction["overflow_returned_cents"] == overflow_returned_cents, (
            f"overflow_returned_cents {transaction['overflow_returned_cents']} "
            f"!= {overflow_returned_cents}"
        )
    if reverses_transaction_id is not None:
        assert transaction["reverses_transaction_id"] == reverses_transaction_id, (
            f"reverses_transaction_id {transaction['reverses_transaction_id']} "
            f"!= {reverses_transaction_id}"
        )
    if source_cycle_id is not None:
        assert transaction["source_cycle_id"] == source_cycle_id, (
            f"source_cycle_id {transaction['source_cycle_id']} != {source_cycle_id}"
        )


def rows_of_origin(transactions: Iterable[Dict[str, Any]], origin: str) -> List[Dict[str, Any]]:
    return [row for row in transactions if row["origin"] == origin]


# --------------------------------------------------------------------------- #
# Withdrawal requests and ballots
# --------------------------------------------------------------------------- #
def assert_ballot_requirements(
    request: Dict[str, Any], *, votes_required: int, quorum_required: int
) -> None:
    assert request["votes_required"] == votes_required, (
        f"votes_required {request['votes_required']} != {votes_required}"
    )
    assert request["quorum_required"] == quorum_required, (
        f"quorum_required {request['quorum_required']} != {quorum_required}"
    )


def assert_tally(
    request: Dict[str, Any], *, yes: int, no: int, abstain: int
) -> None:
    assert request["yes_votes"] == yes, f"yes_votes {request['yes_votes']} != {yes}"
    assert request["no_votes"] == no, f"no_votes {request['no_votes']} != {no}"
    assert request["abstain_votes"] == abstain, (
        f"abstain_votes {request['abstain_votes']} != {abstain}"
    )


def assert_ballot_untouched(request: Dict[str, Any]) -> None:
    """The shortfall branch leaves every ballot field exactly as drafted."""
    assert request["votes_required"] == 0, (
        f"votes_required must stay 0 on the shortfall branch, got {request['votes_required']}"
    )
    assert request["quorum_required"] == 0, (
        f"quorum_required must stay 0 on the shortfall branch, got {request['quorum_required']}"
    )
    assert request["yes_votes"] == 0, "yes_votes must stay 0 on the shortfall branch"
    assert request["no_votes"] == 0, "no_votes must stay 0 on the shortfall branch"
    assert request["abstain_votes"] == 0, "abstain_votes must stay 0 on the shortfall branch"
    assert request["vote_closes_at"] is None, (
        f"vote_closes_at must stay null on the shortfall branch, got {request['vote_closes_at']}"
    )


# --------------------------------------------------------------------------- #
# Briefings
# --------------------------------------------------------------------------- #
def assert_briefing_snapshot(
    briefing: Dict[str, Any],
    *,
    fund_version: int,
    adequacy_band: str,
    coverage_ratio_bps: int,
) -> None:
    assert briefing["snapshot_fund_version"] == fund_version, (
        f"snapshot_fund_version {briefing['snapshot_fund_version']} != {fund_version}"
    )
    assert briefing["snapshot_adequacy_band"] == adequacy_band, (
        f"snapshot_adequacy_band {briefing['snapshot_adequacy_band']} != {adequacy_band}"
    )
    assert briefing["snapshot_coverage_ratio_bps"] == coverage_ratio_bps, (
        f"snapshot_coverage_ratio_bps {briefing['snapshot_coverage_ratio_bps']} "
        f"!= {coverage_ratio_bps}"
    )


def assert_briefing_stale(briefing: Dict[str, Any], *, stale_reason: str) -> None:
    assert briefing["status"] == "STALE", (
        f"expected briefing status STALE, got {briefing['status']}"
    )
    assert briefing["stale_reason"] == stale_reason, (
        f"stale_reason {briefing['stale_reason']} != {stale_reason}"
    )


# --------------------------------------------------------------------------- #
# Ordering
# --------------------------------------------------------------------------- #
def assert_ids_in_order(items: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    actual = [item["id"] for item in items]
    assert actual == expected_ids, f"expected id order {expected_ids}, got {actual}"

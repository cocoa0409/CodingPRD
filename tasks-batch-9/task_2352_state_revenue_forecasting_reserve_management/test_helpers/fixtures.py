"""Composable setup helpers.

The server is restarted with an empty database before every test, so every
fixture below builds the state it needs from scratch through the public
endpoints. Nothing is seeded behind the API's back.

Two shared chains recur throughout the suite:

* the **short chain** — one revenue source (PIT), no statutory policy change and
  no non-recurring receipt, with both bodies filing the same figure, so the
  round compares at zero variance; and
* the **full chain** — two sources (PIT and a HIGH-volatility capital gains
  source), a prorated decrease on one and a capped tiered increase on the other,
  one non-recurring receipt, and a legislative judgmental overlay on each source
  so the two submissions differ.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import constants as C
from . import factories as F
from .api_client import ApiClient
from .test_users import (
    EXEC_ECONOMIST_USER_ID,
    LEG_ECONOMIST_USER_ID,
    VOTER_USER_IDS,
    make_director_headers,
    make_exec_economist_headers,
    make_leg_economist_headers,
    make_rating_analyst_headers,
    make_treasurer_headers,
    make_voter_headers,
)

CHAIN_STAGES = ["draft", "locked", "round", "filed", "compared", "ratified", "certified"]


def _stage_reaches(stop_at: str, stage: str) -> bool:
    assert stop_at in CHAIN_STAGES, f"unknown chain stage {stop_at!r}"
    return CHAIN_STAGES.index(stop_at) >= CHAIN_STAGES.index(stage)


# --------------------------------------------------------------------------- #
# Logical clock (PRD §2.5)
# --------------------------------------------------------------------------- #
def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    response = api.set_clock(F.clock_payload(current_utc), make_director_headers())
    return validate_success(response, 200)


def shift_iso(base_iso: str, *, days: int = 0, hours: int = 0, minutes: int = 0) -> str:
    """An ISO 8601 UTC instant offset from another one."""
    moment = datetime.strptime(base_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    moved = moment + timedelta(days=days, hours=hours, minutes=minutes)
    return moved.strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Revenue sources and policy adjustments
# --------------------------------------------------------------------------- #
def create_source(api: ApiClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api.create_revenue_source(payload, make_director_headers()))


def create_pit_source(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return create_source(api, F.pit_source_payload(**overrides))


def create_cgt_source(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return create_source(api, F.cgt_source_payload(**overrides))


def create_policy_adjustment(
    api: ApiClient, source_id: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    return get_success_data(
        api.create_policy_adjustment(source_id, payload, make_director_headers())
    )


# --------------------------------------------------------------------------- #
# Forecast cycles and scenarios
# --------------------------------------------------------------------------- #
def create_cycle(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_forecast_cycle(F.cycle_payload(**overrides), make_director_headers()))


def add_scenario(api: ApiClient, cycle_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_scenario(cycle_id, F.scenario_payload(**overrides), make_director_headers())
    )


def add_canonical_scenarios(api: ApiClient, cycle_id: str) -> List[Dict[str, Any]]:
    """The three-scenario set whose weights total exactly 10000 basis points."""
    return [add_scenario(api, cycle_id, **spec) for spec in C.CANONICAL_SCENARIOS]


def read_cycle(api: ApiClient, cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_forecast_cycle(cycle_id, make_director_headers()))


def lock_inputs(api: ApiClient, cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api.lock_inputs(cycle_id, make_director_headers()))


def certify(api: ApiClient, cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api.certify_cycle(cycle_id, make_director_headers()))


# --------------------------------------------------------------------------- #
# Consensus rounds and estimates
# --------------------------------------------------------------------------- #
def open_round(
    api: ApiClient,
    cycle_id: str,
    expected_cycle_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    if expected_cycle_version is None:
        expected_cycle_version = read_cycle(api, cycle_id)["version"]
    payload = F.round_payload(cycle_id, expected_cycle_version, **overrides)
    return get_success_data(api.create_consensus_round(payload, make_director_headers()))


def read_round(api: ApiClient, round_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_consensus_round(round_id, make_director_headers()))


def _body_headers(body: str, user_id: Optional[str] = None) -> Dict[str, str]:
    if body == "EXECUTIVE":
        return make_exec_economist_headers(user_id or EXEC_ECONOMIST_USER_ID)
    if body == "LEGISLATIVE":
        return make_leg_economist_headers(user_id or LEG_ECONOMIST_USER_ID)
    raise AssertionError(f"unknown estimating body {body!r}")


def file_estimate(
    api: ApiClient,
    round_id: str,
    source_id: str,
    body: str,
    judgmental_adjustment_cents: int = 0,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload = F.estimate_payload(
        round_id, source_id, judgmental_adjustment_cents=judgmental_adjustment_cents
    )
    return get_success_data(api.create_source_estimate(payload, _body_headers(body, user_id)))


def submit_body(
    api: ApiClient, round_id: str, body: str, user_id: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(api.submit_round(round_id, _body_headers(body, user_id)))


def ratify(api: ApiClient, round_id: str) -> Dict[str, Any]:
    return get_success_data(api.ratify_round(round_id, make_director_headers()))


def list_disagreements(api: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    response = api.list_disagreement_records(make_director_headers(), params=params or None)
    return validate_success(response, 200)


def resolve_disagreement(
    api: ApiClient,
    record_id: str,
    resolution_method: str,
    resolved_amount_cents: Optional[int] = None,
    rationale: str = C.VALID_RATIONALE,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload = F.resolution_payload(
        resolution_method, resolved_amount_cents=resolved_amount_cents, rationale=rationale
    )
    return get_success_data(
        api.resolve_disagreement(record_id, payload, make_director_headers(user_id) if user_id else make_director_headers())
    )


# --------------------------------------------------------------------------- #
# One-time items
# --------------------------------------------------------------------------- #
def create_one_time_item(
    api: ApiClient, cycle_id: str, source_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = F.one_time_item_payload(cycle_id, source_id, **overrides)
    return get_success_data(api.create_one_time_item(payload, make_director_headers()))


def void_one_time_item(api: ApiClient, item_id: str) -> Dict[str, Any]:
    return get_success_data(api.void_one_time_item(item_id, make_director_headers()))


# --------------------------------------------------------------------------- #
# Reserve funds
# --------------------------------------------------------------------------- #
def create_fund(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_reserve_fund(F.fund_payload(**overrides), make_director_headers()))


def read_fund(api: ApiClient, fund_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_reserve_fund(fund_id, make_director_headers()))


def read_adequacy(api: ApiClient, fund_id: str) -> Dict[str, Any]:
    return validate_success(api.get_fund_adequacy(fund_id, make_director_headers()), 200)


def deposit(api: ApiClient, fund_id: str, amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    payload = F.deposit_payload(amount_cents, **overrides)
    return get_success_data(api.create_deposit(fund_id, payload, make_treasurer_headers()))


def reverse(api: ApiClient, transaction_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = F.reversal_payload(**overrides)
    return get_success_data(api.reverse_transaction(transaction_id, payload, make_treasurer_headers()))


def list_transactions(api: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    response = api.list_reserve_transactions(make_director_headers(), params=params or None)
    return validate_success(response, 200)


def recompute_adequacy(api: ApiClient, fund_id: str) -> Dict[str, Any]:
    return get_success_data(api.recompute_adequacy(fund_id, make_director_headers()))


# --------------------------------------------------------------------------- #
# Withdrawal requests and ballots
# --------------------------------------------------------------------------- #
def draft_withdrawal(
    api: ApiClient,
    fund_id: str,
    cycle_id: str,
    expected_fund_version: Optional[int] = None,
    requester_user_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    if expected_fund_version is None:
        expected_fund_version = read_fund(api, fund_id)["version"]
    payload = F.withdrawal_request_payload(
        fund_id, cycle_id, expected_fund_version, **overrides
    )
    headers = make_treasurer_headers(requester_user_id) if requester_user_id else make_treasurer_headers()
    return get_success_data(api.create_withdrawal_request(payload, headers))


def read_request(api: ApiClient, request_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_withdrawal_request(request_id, make_director_headers()))


def verify_shortfall(api: ApiClient, request_id: str) -> Dict[str, Any]:
    return get_success_data(api.verify_shortfall(request_id, make_treasurer_headers()))


def open_vote(api: ApiClient, request_id: str) -> Dict[str, Any]:
    return get_success_data(api.open_vote(request_id, make_director_headers()))


def cast_ballots(
    api: ApiClient,
    request_id: str,
    yes: int = 0,
    no: int = 0,
    abstain: int = 0,
) -> List[Dict[str, Any]]:
    """Cast one ballot per distinct voter, filling YES then NO then ABSTAIN."""
    assert yes + no + abstain <= len(VOTER_USER_IDS), "not enough distinct voters"
    ballots: List[Dict[str, Any]] = []
    voters = iter(VOTER_USER_IDS)
    for choice, count in (("YES", yes), ("NO", no), ("ABSTAIN", abstain)):
        for _ in range(count):
            voter_id = next(voters)
            ballots.append(
                get_success_data(
                    api.cast_vote(
                        request_id, F.vote_payload(choice), make_voter_headers(voter_id)
                    )
                )
            )
    return ballots


def close_vote(api: ApiClient, request_id: str) -> Dict[str, Any]:
    return get_success_data(api.close_vote(request_id, make_director_headers()))


def execute_withdrawal(
    api: ApiClient, request_id: str, executor_user_id: Optional[str] = None
) -> Dict[str, Any]:
    headers = make_treasurer_headers(executor_user_id) if executor_user_id else make_treasurer_headers()
    return get_success_data(api.execute_withdrawal(request_id, headers))


# --------------------------------------------------------------------------- #
# Actual collections
# --------------------------------------------------------------------------- #
def post_actual(
    api: ApiClient, source_id: str, fiscal_year: int, actual_amount_cents: int
) -> Dict[str, Any]:
    payload = F.actual_collection_payload(source_id, fiscal_year, actual_amount_cents)
    return get_success_data(api.create_actual_collection(payload, make_director_headers()))


# --------------------------------------------------------------------------- #
# Rating agency briefings
# --------------------------------------------------------------------------- #
def draft_briefing(api: ApiClient, fund_id: str, cycle_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = F.briefing_payload(fund_id, cycle_id, **overrides)
    return get_success_data(api.create_rating_briefing(payload, make_rating_analyst_headers()))


def read_briefing(api: ApiClient, briefing_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_rating_briefing(briefing_id, make_director_headers()))


def publish_briefing(
    api: ApiClient, briefing_id: str, refresh_snapshot: Optional[bool] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.publish_briefing(
            briefing_id, make_director_headers(), F.publish_payload(refresh_snapshot)
        )
    )


# --------------------------------------------------------------------------- #
# The short chain
# --------------------------------------------------------------------------- #
def short_chain(
    api: ApiClient,
    stop_at: str = "compared",
    *,
    clock: str = C.DEFAULT_CLOCK,
    fund_overrides: Optional[Dict[str, Any]] = None,
    **cycle_overrides: Any,
) -> Dict[str, Any]:
    """One PIT source, three canonical scenarios, both bodies filing the same
    figure. Every stage from `draft` through `certified` is reachable."""
    set_clock(api, clock)
    ctx: Dict[str, Any] = {}

    pit = create_pit_source(api)
    ctx["pit_source"] = pit
    ctx["pit_source_id"] = pit["id"]
    ctx["source_id"] = pit["id"]

    if fund_overrides is not None:
        fund = create_fund(api, **fund_overrides)
        ctx["fund"] = fund
        ctx["fund_id"] = fund["id"]

    cycle = create_cycle(api, **cycle_overrides)
    ctx["cycle"] = cycle
    ctx["cycle_id"] = cycle["id"]
    ctx["scenarios"] = add_canonical_scenarios(api, cycle["id"])

    if not _stage_reaches(stop_at, "locked"):
        return ctx
    ctx["cycle"] = lock_inputs(api, cycle["id"])

    if not _stage_reaches(stop_at, "round"):
        return ctx
    round_data = open_round(api, cycle["id"])
    ctx["round"] = round_data
    ctx["round_id"] = round_data["id"]

    if not _stage_reaches(stop_at, "filed"):
        return ctx
    ctx["exec_estimate"] = file_estimate(api, round_data["id"], pit["id"], "EXECUTIVE")
    ctx["leg_estimate"] = file_estimate(api, round_data["id"], pit["id"], "LEGISLATIVE")

    if not _stage_reaches(stop_at, "compared"):
        return ctx
    submit_body(api, round_data["id"], "EXECUTIVE")
    ctx["round"] = submit_body(api, round_data["id"], "LEGISLATIVE")

    if not _stage_reaches(stop_at, "ratified"):
        return ctx
    ctx["round"] = ratify(api, round_data["id"])

    if not _stage_reaches(stop_at, "certified"):
        return ctx
    ctx["cycle"] = certify(api, cycle["id"])
    if "fund_id" in ctx:
        ctx["fund"] = read_fund(api, ctx["fund_id"])
    return ctx


# --------------------------------------------------------------------------- #
# The full chain
# --------------------------------------------------------------------------- #
def full_chain(
    api: ApiClient,
    stop_at: str = "compared",
    *,
    reconciliation_policy: str = "MIDPOINT_AVERAGE",
    dispute: bool = False,
    with_one_time: bool = True,
    with_policy_adjustments: bool = True,
    clock: str = C.DEFAULT_CLOCK,
    fund_overrides: Optional[Dict[str, Any]] = None,
    variance_tolerance_bps: int = C.VARIANCE_TOLERANCE_BPS,
    per_source_tolerance_bps: int = C.PER_SOURCE_TOLERANCE_BPS,
    **cycle_overrides: Any,
) -> Dict[str, Any]:
    """Two sources, both statutory policy changes, one non-recurring receipt and
    a legislative overlay on each source.

    With `dispute=False` the two submissions differ by 69 basis points overall
    and by 64 and 87 basis points per source, so the round compares. With
    `dispute=True` the legislative capital-gains figure is pushed far enough out
    that the capital-gains source alone breaches its tolerance.
    """
    set_clock(api, clock)
    ctx: Dict[str, Any] = {}

    pit = create_pit_source(api)
    cgt = create_cgt_source(api)
    ctx["pit_source"] = pit
    ctx["cgt_source"] = cgt
    ctx["pit_source_id"] = pit["id"]
    ctx["cgt_source_id"] = cgt["id"]

    if with_policy_adjustments:
        ctx["pit_adjustment"] = create_policy_adjustment(
            api, pit["id"], F.pit_policy_adjustment_payload()
        )
        ctx["cgt_adjustment"] = create_policy_adjustment(
            api, cgt["id"], F.cgt_policy_adjustment_payload()
        )

    if fund_overrides is not None:
        fund = create_fund(api, **fund_overrides)
        ctx["fund"] = fund
        ctx["fund_id"] = fund["id"]

    cycle = create_cycle(api, reconciliation_policy=reconciliation_policy, **cycle_overrides)
    ctx["cycle"] = cycle
    ctx["cycle_id"] = cycle["id"]
    ctx["scenarios"] = add_canonical_scenarios(api, cycle["id"])

    if with_one_time:
        item = create_one_time_item(api, cycle["id"], cgt["id"])
        ctx["one_time_item"] = item
        ctx["one_time_item_id"] = item["id"]

    if not _stage_reaches(stop_at, "locked"):
        return ctx
    ctx["cycle"] = lock_inputs(api, cycle["id"])

    if not _stage_reaches(stop_at, "round"):
        return ctx
    round_data = open_round(
        api,
        cycle["id"],
        variance_tolerance_bps=variance_tolerance_bps,
        per_source_tolerance_bps=per_source_tolerance_bps,
    )
    ctx["round"] = round_data
    ctx["round_id"] = round_data["id"]

    if not _stage_reaches(stop_at, "filed"):
        return ctx
    ctx["exec_pit_estimate"] = file_estimate(api, round_data["id"], pit["id"], "EXECUTIVE")
    ctx["exec_cgt_estimate"] = file_estimate(api, round_data["id"], cgt["id"], "EXECUTIVE")
    ctx["leg_pit_estimate"] = file_estimate(
        api,
        round_data["id"],
        pit["id"],
        "LEGISLATIVE",
        judgmental_adjustment_cents=C.LEG_PIT_JUDGMENTAL_CENTS,
    )
    cgt_overlay = (
        C.DISPUTE_LEG_CGT_JUDGMENTAL_CENTS if dispute else C.LEG_CGT_JUDGMENTAL_CENTS
    )
    ctx["leg_cgt_estimate"] = file_estimate(
        api,
        round_data["id"],
        cgt["id"],
        "LEGISLATIVE",
        judgmental_adjustment_cents=cgt_overlay,
    )

    if not _stage_reaches(stop_at, "compared"):
        return ctx
    submit_body(api, round_data["id"], "EXECUTIVE")
    ctx["round"] = submit_body(api, round_data["id"], "LEGISLATIVE")

    if not _stage_reaches(stop_at, "ratified"):
        return ctx
    if dispute:
        records = list_disagreements(api, round_id=round_data["id"], status="OPEN")
        ctx["disagreement_records"] = records
        for record in records:
            resolve_disagreement(api, record["id"], "MIDPOINT")
        ctx["round"] = read_round(api, round_data["id"])
    ctx["round"] = ratify(api, round_data["id"])

    if not _stage_reaches(stop_at, "certified"):
        return ctx
    ctx["cycle"] = certify(api, cycle["id"])
    if "fund_id" in ctx:
        ctx["fund"] = read_fund(api, ctx["fund_id"])
    return ctx


# --------------------------------------------------------------------------- #
# Certified cycle plus a funded reserve — the base of the reserve-side tests
# --------------------------------------------------------------------------- #
def certified_full_chain_with_fund(
    api: ApiClient,
    *,
    fund_overrides: Optional[Dict[str, Any]] = None,
    **chain_kwargs: Any,
) -> Dict[str, Any]:
    """The full chain certified with one reserve fund present, so the deposit
    cascade has somewhere to land."""
    overrides = dict(fund_overrides or {})
    return full_chain(api, "certified", fund_overrides=overrides, **chain_kwargs)


def certified_short_chain_with_fund(
    api: ApiClient,
    *,
    fund_overrides: Optional[Dict[str, Any]] = None,
    **chain_kwargs: Any,
) -> Dict[str, Any]:
    overrides = dict(fund_overrides or {})
    return short_chain(api, "certified", fund_overrides=overrides, **chain_kwargs)

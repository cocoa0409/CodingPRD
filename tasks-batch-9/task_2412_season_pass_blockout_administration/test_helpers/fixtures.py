"""Setup builders and pytest fixtures.

Every test runs against an empty database, so all preconditions are built from
scratch through the API endpoints the PRD declares. The module is organised in
tiers: primitive single-call helpers, entity builders, composite scenario
builders, whole-world scenarios, and finally the pytest fixtures that wrap the
most frequently reused scenarios.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient, api_client
from .constants import DEFAULT_CLOCK_UTC
from .test_users import (
    clerk_headers,
    compliance_officer_headers,
    gate_agent_headers,
    make_compliance_officer_headers,
    make_gate_agent_headers,
    make_passholder_headers,
    program_admin_headers,
)
from .types import (
    CreditMode,
    GateCode,
    PaymentMode,
    PhotoMatch,
    ProgramStatus,
    TierStatus,
)

# ===========================================================================
# Tier 1 - primitive single-call helpers
# ===========================================================================


def set_clock(api: ApiClient, to_iso8601: str) -> str:
    """Move the logical clock and return the value the server reports."""
    data = get_success_data(api.set_clock(to_iso8601, headers=program_admin_headers()))
    return data.get("current_utc", to_iso8601)


def create_program(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    payload = f.pass_program_payload(**overrides)
    return get_success_data(api.create_pass_program(payload, headers=program_admin_headers()))


def advance_program(api: ApiClient, program_id: str, target_status: str) -> Dict[str, Any]:
    return get_success_data(
        api.advance_program_status(
            program_id, f.advance_status_payload(target_status), headers=program_admin_headers()
        )
    )


#: The single legal forward path through the programme lifecycle.
_PROGRAM_PATH = [
    ProgramStatus.DESIGN.value,
    ProgramStatus.SALES_OPEN.value,
    ProgramStatus.SEASON_ACTIVE.value,
    ProgramStatus.RENEWAL_OPEN.value,
    ProgramStatus.CLOSED.value,
]


#: A date used only to satisfy the "gates need a calendar" precondition when a
#: scenario advances a programme into SEASON_ACTIVE without caring about days.
_OPENING_DAY_DATE = "2026-12-01"


def _ensure_operating_day(api: ApiClient, program_id: str) -> None:
    """Give the programme a calendar if it has none, so its gates may open."""
    listing = get_success_data(
        api.list_park_days(headers=program_admin_headers(), params={"program_id": program_id})
    )
    if not listing:
        create_park_day(api, program_id, _OPENING_DAY_DATE)


def advance_program_to(api: ApiClient, program_id: str, target_status: str) -> Dict[str, Any]:
    """Walk the programme forward one legal step at a time until it reaches the target.

    Opening the gates requires at least one operating day, so a programme that is
    being pushed to `SEASON_ACTIVE` or beyond is given one when it has none.
    """
    current = get_success_data(api.get_pass_program(program_id, headers=program_admin_headers()))
    row = current
    start = _PROGRAM_PATH.index(current["status"])
    stop = _PROGRAM_PATH.index(target_status)
    for step in _PROGRAM_PATH[start + 1 : stop + 1]:
        if step == ProgramStatus.SEASON_ACTIVE.value:
            _ensure_operating_day(api, program_id)
        row = advance_program(api, program_id, step)
    return row


def create_tier(api: ApiClient, program_id: str, publish: bool = True, **overrides: Any) -> Dict[str, Any]:
    tier = get_success_data(
        api.create_pass_tier(f.pass_tier_payload(program_id, **overrides), headers=program_admin_headers())
    )
    if publish:
        tier = publish_tier(api, tier["id"])
    return tier


def publish_tier(api: ApiClient, tier_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.set_tier_status(
            tier_id, f.tier_status_payload(TierStatus.PUBLISHED.value), headers=program_admin_headers()
        )
    )


def retire_tier(api: ApiClient, tier_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.set_tier_status(
            tier_id, f.tier_status_payload(TierStatus.RETIRED.value), headers=program_admin_headers()
        )
    )


def create_park_day(
    api: ApiClient,
    program_id: str,
    calendar_date: str,
    capacity_total: int = 1000,
    forecast_attendance: int = 100,
) -> Dict[str, Any]:
    payload = f.park_day_payload(
        program_id,
        calendar_date,
        capacity_total=capacity_total,
        forecast_attendance=forecast_attendance,
    )
    return get_success_data(api.create_park_day(payload, headers=program_admin_headers()))


def forecast_park_day(api: ApiClient, park_day_id: str, forecast_attendance: int) -> Dict[str, Any]:
    return get_success_data(
        api.forecast_park_day(
            park_day_id, f.forecast_payload(forecast_attendance), headers=program_admin_headers()
        )
    )


def get_park_day(api: ApiClient, park_day_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_park_day(park_day_id, headers=program_admin_headers()))


def create_blockout(api: ApiClient, tier_id: str, park_day_id: str) -> Dict[str, Any]:
    """Assign a blockout, reading the park day's current version for the stale-read guard."""
    day = get_park_day(api, park_day_id)
    payload = f.blockout_payload(tier_id, park_day_id, day["version"])
    return get_success_data(api.create_blockout_assignment(payload, headers=program_admin_headers()))


def lift_blockout(api: ApiClient, assignment_id: str, reason: str = "Promo weekend opened up") -> Dict[str, Any]:
    return get_success_data(
        api.lift_blockout_assignment(assignment_id, f.lift_payload(reason), headers=program_admin_headers())
    )


def create_passholder(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_passholder(f.passholder_payload(**overrides), headers=clerk_headers()))


def get_passholder(api: ApiClient, passholder_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_passholder(passholder_id, headers=clerk_headers()))


def sell_pass(
    api: ApiClient,
    program_id: str,
    tier_id: str,
    passholder_id: str,
    payment_mode: str = PaymentMode.PAY_IN_FULL.value,
) -> Dict[str, Any]:
    payload = f.season_pass_payload(program_id, tier_id, passholder_id, payment_mode)
    return get_success_data(api.create_season_pass(payload, headers=clerk_headers()))


def process_pass(api: ApiClient, pass_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.process_season_pass(pass_id, f.process_payload(**overrides), headers=clerk_headers())
    )


def get_pass(api: ApiClient, pass_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_season_pass(pass_id, headers=clerk_headers()))


def enroll_plan(
    api: ApiClient,
    pass_id: str,
    down_payment_cents: int,
    installment_count: int,
    first_due_date: str,
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Enrol the pass in a plan, reading its current version for the stale-read guard."""
    if expected_version is None:
        expected_version = get_pass(api, pass_id)["version"]
    payload = f.payment_plan_payload(
        down_payment_cents, installment_count, first_due_date, expected_version
    )
    return get_success_data(api.create_payment_plan(pass_id, payload, headers=clerk_headers()))


def get_plan(api: ApiClient, plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_payment_plan(plan_id, headers=clerk_headers()))


def plan_installments(api: ApiClient, plan_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Every installment of the plan, in the due-date order the PRD pins."""
    response = api.list_installments(
        headers=clerk_headers(), params={"payment_plan_id": plan_id, "limit": limit}
    )
    return get_success_data(response)


def settle_installment(
    api: ApiClient, installment_id: str, amount_cents: int, paid_at: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.settle_installment(installment_id, f.settle_payload(amount_cents, paid_at), headers=clerk_headers())
    )


def reinstate_pass(
    api: ApiClient, pass_id: str, cure_amount_cents: int, waive_installment_id: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.reinstate_season_pass(
            pass_id, f.reinstate_payload(cure_amount_cents, waive_installment_id), headers=clerk_headers()
        )
    )


def run_billing(api: ApiClient, program_id: str, as_of_date: str) -> Dict[str, Any]:
    return get_success_data(
        api.run_billing(program_id, f.billing_run_payload(as_of_date), headers=program_admin_headers())
    )


def book_reservation(
    api: ApiClient,
    season_pass_id: str,
    park_day_id: str,
    arrival_window_start: str = "10:00",
    arrival_window_end: str = "13:00",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = f.reservation_payload(
        season_pass_id, park_day_id, arrival_window_start, arrival_window_end
    )
    return get_success_data(
        api.create_reservation(payload, headers=headers if headers is not None else clerk_headers())
    )


def cancel_reservation(
    api: ApiClient, reservation_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.cancel_reservation(
            reservation_id, headers=headers if headers is not None else clerk_headers()
        )
    )


def record_visit(
    api: ApiClient,
    season_pass_id: str,
    park_day_id: str,
    entry_at: str,
    gate_code: str = GateCode.NORTH.value,
    photo_match: Optional[str] = PhotoMatch.MATCH.value,
) -> Dict[str, Any]:
    payload = f.visit_payload(season_pass_id, park_day_id, entry_at, gate_code, photo_match)
    return get_success_data(api.create_visit(payload, headers=gate_agent_headers()))


def close_visit(api: ApiClient, visit_id: str, spend_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api.close_visit(visit_id, f.close_visit_payload(spend_cents), headers=gate_agent_headers())
    )


def open_case(
    api: ApiClient,
    season_pass_id: str,
    evidence_visit_ids: Sequence[str],
    note: str = "Photo mismatch",
    agent_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    headers = (
        make_gate_agent_headers(agent_user_id) if agent_user_id is not None else gate_agent_headers()
    )
    payload = f.sharing_case_payload(season_pass_id, list(evidence_visit_ids), note)
    return get_success_data(api.create_sharing_case(payload, headers=headers))


def review_case(api: ApiClient, case_id: str, officer_user_id: Optional[str] = None) -> Dict[str, Any]:
    headers = (
        make_compliance_officer_headers(officer_user_id)
        if officer_user_id is not None
        else compliance_officer_headers()
    )
    return get_success_data(api.review_sharing_case(case_id, headers=headers))


def decide_case(
    api: ApiClient,
    case_id: str,
    decision: str,
    rationale: str = "Evidence stands",
    officer_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    headers = (
        make_compliance_officer_headers(officer_user_id)
        if officer_user_id is not None
        else compliance_officer_headers()
    )
    return get_success_data(api.decide_sharing_case(case_id, f.decide_payload(decision, rationale), headers=headers))


def appeal_case(
    api: ApiClient, case_id: str, passholder_id: str, statement: str = "The gate camera was obstructed"
) -> Dict[str, Any]:
    return get_success_data(
        api.appeal_sharing_case(
            case_id, f.appeal_payload(statement), headers=make_passholder_headers(passholder_id)
        )
    )


def quote_upgrade(
    api: ApiClient,
    season_pass_id: str,
    source_tier_id: str,
    target_tier_id: str,
    credit_mode: str = CreditMode.PAID_TO_DATE.value,
) -> Dict[str, Any]:
    payload = f.upgrade_order_payload(season_pass_id, source_tier_id, target_tier_id, credit_mode)
    return get_success_data(api.create_upgrade_order(payload, headers=clerk_headers()))


def apply_upgrade(api: ApiClient, upgrade_order_id: str, payment_amount_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api.apply_upgrade_order(
            upgrade_order_id, f.apply_upgrade_payload(payment_amount_cents), headers=clerk_headers()
        )
    )


def reverse_upgrade(
    api: ApiClient,
    upgrade_order_id: str,
    reason: str = "Charged in error",
    officer_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    headers = (
        make_compliance_officer_headers(officer_user_id)
        if officer_user_id is not None
        else compliance_officer_headers()
    )
    return get_success_data(
        api.reverse_upgrade_order(upgrade_order_id, f.reverse_upgrade_payload(reason), headers=headers)
    )


def renewal_quote(
    api: ApiClient, pass_id: str, target_tier_id: Optional[str] = None
) -> Dict[str, Any]:
    params = {"target_tier_id": target_tier_id} if target_tier_id is not None else None
    return get_success_data(api.get_renewal_quote(pass_id, headers=clerk_headers(), params=params))


def renew_pass(
    api: ApiClient,
    pass_id: str,
    target_program_id: str,
    target_tier_id: str,
    payment_mode: str = PaymentMode.PAY_IN_FULL.value,
) -> Dict[str, Any]:
    return get_success_data(
        api.renew_season_pass(
            pass_id, f.renew_payload(target_program_id, target_tier_id, payment_mode), headers=clerk_headers()
        )
    )


def revenue_summary(api: ApiClient, program_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_revenue_summary(program_id, headers=program_admin_headers()))


# ===========================================================================
# Tier 2 - entity builders with named tier catalogues
# ===========================================================================


@dataclass
class TierSpec:
    """A tier to design when a programme is built."""

    name: str
    tier_rank: int
    base_price_cents: int
    in_park_discount_pct: float = 0.05
    reservation_required_on_peak: bool = True
    peak_reservation_quota: int = 2
    parking_benefit: str = "NONE"
    publish: bool = True


BRONZE = TierSpec(name="BRONZE", tier_rank=1, base_price_cents=12000, in_park_discount_pct=0.05)
SILVER = TierSpec(
    name="SILVER",
    tier_rank=2,
    base_price_cents=18000,
    in_park_discount_pct=0.10,
    peak_reservation_quota=3,
    parking_benefit="DISCOUNT",
)
GOLD = TierSpec(
    name="GOLD",
    tier_rank=3,
    base_price_cents=30000,
    in_park_discount_pct=0.15,
    reservation_required_on_peak=False,
    peak_reservation_quota=5,
    parking_benefit="INCLUDED",
)


@dataclass
class ProgramContext:
    """A programme together with the tiers designed inside it."""

    row: Dict[str, Any]
    tiers: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.row["id"]

    def tier(self, name: str) -> Dict[str, Any]:
        return self.tiers[name]

    def tier_id(self, name: str) -> str:
        return self.tiers[name]["id"]


def build_program(
    api: ApiClient,
    tiers: Sequence[TierSpec] = (BRONZE,),
    status: str = ProgramStatus.SALES_OPEN.value,
    **program_overrides: Any,
) -> ProgramContext:
    """Create a programme, design and publish its tiers, then advance it.

    Tiers are designed while the programme is still in `DESIGN` or `SALES_OPEN`
    because publishing requires the owning programme to be in one of those two.
    """
    program = create_program(api, **program_overrides)
    context = ProgramContext(row=program)
    for spec in tiers:
        tier = create_tier(
            api,
            program["id"],
            publish=spec.publish,
            name=spec.name,
            tier_rank=spec.tier_rank,
            base_price_cents=spec.base_price_cents,
            in_park_discount_pct=spec.in_park_discount_pct,
            reservation_required_on_peak=spec.reservation_required_on_peak,
            peak_reservation_quota=spec.peak_reservation_quota,
            parking_benefit=spec.parking_benefit,
        )
        context.tiers[spec.name] = tier
    if status != ProgramStatus.DESIGN.value:
        context.row = advance_program_to(api, program["id"], status)
    return context


# ===========================================================================
# Tier 3 - composite scenario builders
# ===========================================================================


@dataclass
class PassContext:
    """A sold (and usually processed) pass with everything around it."""

    program: ProgramContext
    holder: Dict[str, Any]
    row: Dict[str, Any]

    @property
    def id(self) -> str:
        return self.row["id"]

    @property
    def program_id(self) -> str:
        return self.program.id

    @property
    def holder_id(self) -> str:
        return self.holder["id"]

    @property
    def headers(self) -> Dict[str, str]:
        """Headers for the guest who owns this pass."""
        return make_passholder_headers(self.holder["id"])


def build_active_pass(
    api: ApiClient,
    program: ProgramContext,
    tier_name: str = "BRONZE",
    payment_mode: str = PaymentMode.PAY_IN_FULL.value,
    holder: Optional[Dict[str, Any]] = None,
    holder_overrides: Optional[Dict[str, Any]] = None,
) -> PassContext:
    """Register a holder, sell a pass on the named tier and process it to ACTIVE."""
    if holder is None:
        holder = create_passholder(api, **(holder_overrides or {}))
    sold = sell_pass(api, program.id, program.tier_id(tier_name), holder["id"], payment_mode)
    processed = process_pass(api, sold["id"])
    return PassContext(program=program, holder=holder, row=processed)


def build_pending_pass(
    api: ApiClient,
    program: ProgramContext,
    tier_name: str = "BRONZE",
    payment_mode: str = PaymentMode.PAY_IN_FULL.value,
    holder: Optional[Dict[str, Any]] = None,
    holder_overrides: Optional[Dict[str, Any]] = None,
) -> PassContext:
    """Sell a pass and deliberately leave it in PENDING_PROCESSING."""
    if holder is None:
        holder = create_passholder(api, **(holder_overrides or {}))
    sold = sell_pass(api, program.id, program.tier_id(tier_name), holder["id"], payment_mode)
    return PassContext(program=program, holder=holder, row=sold)


@dataclass
class PlanContext:
    """A payment plan with its installment schedule already read back."""

    plan: Dict[str, Any]
    installments: List[Dict[str, Any]]

    @property
    def id(self) -> str:
        return self.plan["id"]

    def installment(self, sequence_no: int) -> Dict[str, Any]:
        for row in self.installments:
            if row["sequence_no"] == sequence_no:
                return row
        raise AssertionError(f"the plan has no installment with sequence_no {sequence_no}")


def build_plan(
    api: ApiClient,
    pass_id: str,
    down_payment_cents: int,
    installment_count: int,
    first_due_date: str,
) -> PlanContext:
    plan = enroll_plan(api, pass_id, down_payment_cents, installment_count, first_due_date)
    return PlanContext(plan=plan, installments=plan_installments(api, plan["id"]))


def build_peak_day(
    api: ApiClient, program_id: str, calendar_date: str
) -> Dict[str, Any]:
    """An operating day at 40/36 - utilisation 0.9000, PEAK, 4 slots, window 2."""
    return create_park_day(api, program_id, calendar_date, capacity_total=40, forecast_attendance=36)


def build_standard_day(
    api: ApiClient, program_id: str, calendar_date: str
) -> Dict[str, Any]:
    """An operating day at 1000/100 - utilisation 0.1000, STANDARD, 100 slots, window 50."""
    return create_park_day(api, program_id, calendar_date, capacity_total=1000, forecast_attendance=100)


def build_capacity_locked_day(
    api: ApiClient, program_id: str, calendar_date: str
) -> Dict[str, Any]:
    """A 1000-capacity day re-forecast to 975, which is 0.9750 and therefore locked."""
    day = create_park_day(api, program_id, calendar_date, capacity_total=1000, forecast_attendance=100)
    return forecast_park_day(api, day["id"], 975)


def build_confirmed_reservation(
    api: ApiClient,
    pass_ctx: PassContext,
    park_day_id: str,
    arrival_window_start: str = "10:00",
    arrival_window_end: str = "13:00",
    as_holder: bool = False,
) -> Dict[str, Any]:
    headers = pass_ctx.headers if as_holder else clerk_headers()
    return book_reservation(
        api, pass_ctx.id, park_day_id, arrival_window_start, arrival_window_end, headers=headers
    )


def build_case_under_review(
    api: ApiClient,
    pass_ctx: PassContext,
    park_day_id: str,
    entry_at: str,
    agent_user_id: str = "gate-user-g1",
    officer_user_id: str = "officer-o1",
) -> Dict[str, Any]:
    """Record one gate entry, open a case on it and take the case under review."""
    visit = record_visit(api, pass_ctx.id, park_day_id, entry_at)
    case = open_case(api, pass_ctx.id, [visit["id"]], agent_user_id=agent_user_id)
    return review_case(api, case["id"], officer_user_id=officer_user_id)


# ===========================================================================
# Tier 4 - whole-world scenarios
# ===========================================================================


@dataclass
class SeasonWorld:
    """A season in progress: a SEASON_ACTIVE programme, tiers, a day and a pass."""

    program: ProgramContext
    pass_ctx: PassContext
    day: Dict[str, Any]


def build_season_world(
    api: ApiClient,
    tiers: Sequence[TierSpec] = (BRONZE, GOLD),
    calendar_date: str = "2026-09-01",
    day_capacity: int = 1000,
    day_forecast: int = 100,
    tier_name: str = "BRONZE",
    payment_mode: str = PaymentMode.PAY_IN_FULL.value,
) -> SeasonWorld:
    """A programme in SEASON_ACTIVE with one operating day and one ACTIVE pass.

    Tiers are designed first because designing a tier requires the programme to
    be in `DESIGN` or `SALES_OPEN`; the day, the sale and the processing all
    tolerate `SEASON_ACTIVE`, so they run after the programme has advanced.
    """
    program = build_program(api, tiers=tiers, status=ProgramStatus.SEASON_ACTIVE.value)
    day = create_park_day(
        api, program.id, calendar_date, capacity_total=day_capacity, forecast_attendance=day_forecast
    )
    pass_ctx = build_active_pass(api, program, tier_name=tier_name, payment_mode=payment_mode)
    return SeasonWorld(program=program, pass_ctx=pass_ctx, day=day)


# ===========================================================================
# Tier 5 - pytest fixtures
# ===========================================================================


@pytest.fixture
def default_clock(api: ApiClient) -> str:
    """Pin the logical clock to the value it reads before anyone sets it."""
    return set_clock(api, DEFAULT_CLOCK_UTC)


@pytest.fixture
def design_program(api: ApiClient) -> ProgramContext:
    """A programme still in DESIGN with no tiers."""
    return ProgramContext(row=create_program(api))


@pytest.fixture
def sales_open_program(api: ApiClient) -> ProgramContext:
    """A SALES_OPEN programme with a PUBLISHED BRONZE tier."""
    return build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)


@pytest.fixture
def three_tier_program(api: ApiClient) -> ProgramContext:
    """A SALES_OPEN programme with PUBLISHED BRONZE, SILVER and GOLD tiers."""
    return build_program(api, tiers=(BRONZE, SILVER, GOLD), status=ProgramStatus.SALES_OPEN.value)


@pytest.fixture
def season_world(api: ApiClient) -> SeasonWorld:
    """A SEASON_ACTIVE programme with a STANDARD day and one ACTIVE BRONZE pass."""
    return build_season_world(api)

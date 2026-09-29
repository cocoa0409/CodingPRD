"""Composite setup helpers.

Every test runs against an empty database, so each fixture builds the state it
needs from scratch through the declared endpoints. The ``BonusPlanScenario``
class walks the workflow one step at a time and remembers the identifiers it
minted, so a test can reach any point of the chain — scorecard certified,
plan certified, pool funded, money allocated, plan calibrated, plan locked,
payout executed, year settled — with one call.

Identity is threaded explicitly: manager calls use the acting business unit's
own id and employee calls use the acting participant's own id.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    PAYMENT_DATE_CLOCK,
    PLAN_PERIOD_END,
    PLAN_PERIOD_START,
    TEST_DEFAULTS,
)
from .factories import (
    accrual_period_payload,
    accrual_post_payload,
    accrual_reverse_payload,
    adjustment_decision_payload,
    adjustment_reverse_payload,
    bonus_plan_payload,
    bu_pool_payload,
    business_unit_payload,
    clock_payload,
    company_metric_payload,
    decision_payload,
    discretionary_adjustment_payload,
    dispute_payload,
    dispute_resolution_payload,
    dispute_review_payload,
    job_level_target_payload,
    leave_event_payload,
    metric_actual_payload,
    participant_payload,
    payout_run_payload,
    propose_allocation_payload,
    retract_allocation_payload,
    settle_payload,
    submit_scorecard_payload,
    termination_event_payload,
    transfer_event_payload,
    unique_unit_code,
)
from .test_users import (
    CC_ADJUDICATOR,
    CC_CERTIFIER,
    CC_LOCKER,
    CC_REVERSER,
    CC_SCORECARD,
    TEST_USERS,
    make_committee_headers,
    make_employee_headers,
    make_manager_headers,
)

PA = TEST_USERS["plan_admin_headers"]
HR = TEST_USERS["hr_headers"]
FC = TEST_USERS["finance_headers"]

# ─── Default scenario shape ───────────────────────────────────────────────
DEFAULT_TARGETS = ({"job_level": "L5", "target_bonus_pct": 20.00},)
DEFAULT_METRICS = ({"metric_code": "REVENUE", "weight_pct": 100.00},)
DEFAULT_PARTICIPANTS = (
    {
        "label": "ada",
        "full_name": "Ada Long",
        "job_level": "L5",
        "base_salary_cents": TEST_DEFAULTS["L5_BASE_SALARY_CENTS"],
        "hire_date": TEST_DEFAULTS["FULL_YEAR_HIRE_DATE"],
    },
)


class BonusPlanScenario:
    """Stateful walker over the bonus-plan workflow."""

    def __init__(self, client=None):
        self.api = client or api_client
        self.units = {}  # unit_code -> BusinessUnit
        self.plan = None
        self.targets = {}  # job_level -> JobLevelTarget
        self.metrics = {}  # metric_code -> CompanyMetric
        self.pools = {}  # unit_code -> BusinessUnitPool
        self.participants = {}  # label -> Participant
        self.awards = {}  # label -> ParticipantAward
        self.events = []
        self.adjustments = {}  # label -> list of DiscretionaryAdjustment
        self.accrual_periods = []
        self.payout_run = None
        self.disputes = []

    # ─── identity helpers ─────────────────────────────────────────────────
    @property
    def plan_id(self):
        return self.plan["id"]

    def unit_id(self, unit_code):
        return self.units[unit_code]["id"]

    def pool_id(self, unit_code):
        return self.pools[unit_code]["id"]

    def participant_id(self, label):
        return self.participants[label]["id"]

    def award_id(self, label):
        return self.awards[label]["id"]

    def manager_headers(self, unit_code):
        """A business unit manager acts as the id of their own business unit."""
        return make_manager_headers(self.unit_id(unit_code))

    def employee_headers(self, label):
        """An employee acts as the id of their own participant row."""
        return make_employee_headers(self.participant_id(label))

    # ─── setup phase ──────────────────────────────────────────────────────
    def add_unit(self, label=None, name=None):
        """Register a business unit under a scenario-local ``label``.

        PRD §3.1: "**Business units** are registered independently of any plan,
        each with a globally unique `unit_code`".  The label a test uses to refer
        to a unit is therefore NOT the stored `unit_code`: a single test may build
        two scenarios that both speak of unit "U1", and both registrations must
        still carry distinct codes.  The label indexes ``self.units``; the code
        the server stores is always freshly minted.
        """
        label = label or unique_unit_code()
        payload = business_unit_payload(unit_code=unique_unit_code())
        if name:
            payload["name"] = name
        unit = get_success_data(self.api.create_business_unit(payload, PA))
        self.units[label] = unit
        return unit

    def create_plan(self, **overrides):
        self.plan = get_success_data(
            self.api.create_bonus_plan(bonus_plan_payload(**overrides), PA)
        )
        return self.plan

    def add_target(self, job_level="L5", **overrides):
        target = get_success_data(
            self.api.create_job_level_target(
                job_level_target_payload(self.plan_id, job_level=job_level, **overrides),
                PA,
            )
        )
        self.targets[job_level] = target
        return target

    def add_metric(self, metric_code="REVENUE", **overrides):
        metric = get_success_data(
            self.api.create_company_metric(
                company_metric_payload(
                    self.plan_id, metric_code=metric_code, **overrides
                ),
                PA,
            )
        )
        self.metrics[metric_code] = metric
        return metric

    def add_pool(self, unit_code, **overrides):
        pool = get_success_data(
            self.api.create_bu_pool(
                bu_pool_payload(self.plan_id, self.unit_id(unit_code), **overrides), PA
            )
        )
        self.pools[unit_code] = pool
        return pool

    def add_participant(self, label, unit_code, **overrides):
        participant = get_success_data(
            self.api.create_participant(
                participant_payload(self.plan_id, self.unit_id(unit_code), **overrides),
                PA,
            )
        )
        self.participants[label] = participant
        return participant

    def file_actual(self, metric_code, actual_value, **overrides):
        metric = get_success_data(
            self.api.file_metric_actual(
                self.metrics[metric_code]["id"],
                metric_actual_payload(actual_value, **overrides),
                PA,
            )
        )
        self.metrics[metric_code] = metric
        return metric

    def submit_scorecard(self, unit_code, bu_metric_achievement_pct, **overrides):
        pool = get_success_data(
            self.api.submit_scorecard(
                self.pool_id(unit_code),
                submit_scorecard_payload(bu_metric_achievement_pct, **overrides),
                self.manager_headers(unit_code),
            )
        )
        self.pools[unit_code] = pool
        return pool

    def decide_scorecard(self, unit_code, decision="CERTIFY", user_id=CC_SCORECARD, **kw):
        pool = get_success_data(
            self.api.decide_scorecard(
                self.pool_id(unit_code),
                decision_payload(decision, **kw),
                make_committee_headers(user_id),
            )
        )
        self.pools[unit_code] = pool
        return pool

    # ─── eligibility events ───────────────────────────────────────────────
    def add_transfer(
        self,
        label,
        effective_date,
        new_job_level,
        new_base_salary_cents,
        new_unit_code,
        **overrides,
    ):
        event = get_success_data(
            self.api.create_eligibility_event(
                transfer_event_payload(
                    self.participant_id(label),
                    effective_date,
                    new_job_level,
                    new_base_salary_cents,
                    self.unit_id(new_unit_code),
                    **overrides,
                ),
                HR,
            )
        )
        self.events.append(event)
        return event

    def add_leave(
        self, label, effective_date, leave_end_date, paid_leave=False, **overrides
    ):
        event = get_success_data(
            self.api.create_eligibility_event(
                leave_event_payload(
                    self.participant_id(label),
                    effective_date,
                    leave_end_date,
                    paid_leave,
                    **overrides,
                ),
                HR,
            )
        )
        self.events.append(event)
        return event

    def add_termination(self, label, effective_date, termination_reason, **overrides):
        event = get_success_data(
            self.api.create_eligibility_event(
                termination_event_payload(
                    self.participant_id(label),
                    effective_date,
                    termination_reason,
                    **overrides,
                ),
                HR,
            )
        )
        self.events.append(event)
        return event

    # ─── plan progression ─────────────────────────────────────────────────
    def assign_targets(self):
        self.plan = get_success_data(self.api.run_target_assignments(self.plan_id, PA))
        self.load_awards()
        return self.plan

    def submit_for_certification(self):
        self.plan = get_success_data(
            self.api.submit_plan_for_certification(self.plan_id, PA)
        )
        return self.plan

    def decide_certification(self, decision="CERTIFY", user_id=CC_CERTIFIER, **kw):
        self.plan = get_success_data(
            self.api.decide_plan_certification(
                self.plan_id,
                decision_payload(decision, **kw),
                make_committee_headers(user_id),
            )
        )
        return self.plan

    def fund(self, user_id=CC_CERTIFIER):
        self.plan = get_success_data(
            self.api.fund_pool(self.plan_id, make_committee_headers(user_id))
        )
        self.refresh_pools()
        self.load_awards()
        return self.plan

    def open_calibration(self):
        self.plan = get_success_data(self.api.open_calibration(self.plan_id, PA))
        return self.plan

    def lock(self, user_id=CC_LOCKER):
        self.plan = get_success_data(
            self.api.lock_plan(self.plan_id, make_committee_headers(user_id))
        )
        self.refresh_pools()
        self.load_awards()
        return self.plan

    # ─── reads and refreshes ──────────────────────────────────────────────
    def refresh_plan(self):
        self.plan = get_success_data(self.api.get_bonus_plan(self.plan_id, PA))
        return self.plan

    def refresh_pool(self, unit_code):
        pool = get_success_data(self.api.get_bu_pool(self.pool_id(unit_code), PA))
        self.pools[unit_code] = pool
        return pool

    def refresh_pools(self):
        for unit_code in list(self.pools):
            self.refresh_pool(unit_code)
        return self.pools

    def load_awards(self):
        """Map every participant label onto its award row."""
        body = get_success_data(
            self.api.list_participant_awards(
                PA, params={"plan_id": self.plan_id, "limit": 100}
            )
        )
        by_participant = {row["participant_id"]: row for row in body}
        for label, participant in self.participants.items():
            if participant["id"] in by_participant:
                self.awards[label] = by_participant[participant["id"]]
        return self.awards

    def refresh_award(self, label):
        award = get_success_data(
            self.api.get_participant_award(self.award_id(label), PA)
        )
        self.awards[label] = award
        return award

    def plan_version(self):
        return self.refresh_plan()["version"]

    def pool_version(self, unit_code):
        return self.refresh_pool(unit_code)["version"]

    def award_version(self, label):
        return self.refresh_award(label)["version"]

    # ─── allocation ───────────────────────────────────────────────────────
    def unit_code_of_award(self, label):
        award_unit_id = self.awards[label]["business_unit_id"]
        for unit_code, unit in self.units.items():
            if unit["id"] == award_unit_id:
                return unit_code
        raise AssertionError(f"award {label} references an unregistered business unit")

    def propose(self, label, cents, expected_pool_version=None, **overrides):
        unit_code = self.unit_code_of_award(label)
        version = (
            expected_pool_version
            if expected_pool_version is not None
            else self.pool_version(unit_code)
        )
        award = get_success_data(
            self.api.propose_allocation(
                self.award_id(label),
                propose_allocation_payload(cents, version, **overrides),
                self.manager_headers(unit_code),
            )
        )
        self.awards[label] = award
        self.refresh_pool(unit_code)
        return award

    def retract(self, label, expected_pool_version=None, **overrides):
        unit_code = self.unit_code_of_award(label)
        version = (
            expected_pool_version
            if expected_pool_version is not None
            else self.pool_version(unit_code)
        )
        award = get_success_data(
            self.api.retract_allocation(
                self.award_id(label),
                retract_allocation_payload(version, **overrides),
                self.manager_headers(unit_code),
            )
        )
        self.awards[label] = award
        self.refresh_pool(unit_code)
        return award

    def submit_calibration(self, unit_code, **kw):
        pool = get_success_data(
            self.api.submit_calibration(
                self.pool_id(unit_code), self.manager_headers(unit_code), kw or {}
            )
        )
        self.pools[unit_code] = pool
        return pool

    def decide_calibration(self, unit_code, decision="CERTIFY", **kw):
        pool = get_success_data(
            self.api.decide_calibration(
                self.pool_id(unit_code), decision_payload(decision, **kw), PA
            )
        )
        self.pools[unit_code] = pool
        return pool

    # ─── discretionary adjustments ────────────────────────────────────────
    def file_adjustment(
        self, label, adjustment_cents, expected_plan_version=None, headers=None, **overrides
    ):
        version = (
            expected_plan_version
            if expected_plan_version is not None
            else self.plan_version()
        )
        adjustment = get_success_data(
            self.api.create_discretionary_adjustment(
                discretionary_adjustment_payload(
                    self.plan_id, self.award_id(label), adjustment_cents, version,
                    **overrides,
                ),
                headers or HR,
            )
        )
        self.adjustments.setdefault(label, []).append(adjustment)
        return adjustment

    def decide_adjustment(
        self, adjustment_id, decision="APPROVE", user_id=CC_ADJUDICATOR, **kw
    ):
        return get_success_data(
            self.api.decide_discretionary_adjustment(
                adjustment_id,
                adjustment_decision_payload(decision, **kw),
                make_committee_headers(user_id),
            )
        )

    def reverse_adjustment(self, adjustment_id, user_id=CC_REVERSER, **kw):
        return get_success_data(
            self.api.reverse_discretionary_adjustment(
                adjustment_id,
                adjustment_reverse_payload(**kw),
                make_committee_headers(user_id),
            )
        )

    # ─── accrual ──────────────────────────────────────────────────────────
    def open_accrual_period(
        self, period_start, period_end, forecast_company_achievement_pct, **overrides
    ):
        period = get_success_data(
            self.api.create_accrual_period(
                accrual_period_payload(
                    self.plan_id,
                    period_start,
                    period_end,
                    forecast_company_achievement_pct,
                    **overrides,
                ),
                FC,
            )
        )
        self.accrual_periods.append(period)
        return period

    def post_accrual_period(self, period_id, **kw):
        period = get_success_data(
            self.api.post_accrual_period(period_id, FC, accrual_post_payload(**kw))
        )
        self._replace_period(period)
        return period

    def reverse_accrual_period(self, period_id, **kw):
        period = get_success_data(
            self.api.reverse_accrual_period(period_id, accrual_reverse_payload(**kw), FC)
        )
        self._replace_period(period)
        return period

    def _replace_period(self, period):
        for index, existing in enumerate(self.accrual_periods):
            if existing["id"] == period["id"]:
                self.accrual_periods[index] = period
                return
        self.accrual_periods.append(period)

    def refresh_accrual_periods(self):
        body = get_success_data(
            self.api.list_accrual_periods(
                FC, params={"plan_id": self.plan_id, "limit": 100}
            )
        )
        self.accrual_periods = list(body)
        return self.accrual_periods

    # ─── clock, payout, disputes ──────────────────────────────────────────
    def set_clock(self, current_utc, headers=None):
        return get_success_data(
            self.api.set_clock(clock_payload(current_utc), headers or PA)
        )

    def open_payout_run(self, **overrides):
        self.payout_run = get_success_data(
            self.api.create_payout_run(payout_run_payload(self.plan_id, **overrides), FC)
        )
        return self.payout_run

    def execute_payout(self):
        self.payout_run = get_success_data(
            self.api.execute_payout_run(self.payout_run["id"], FC)
        )
        self.refresh_plan()
        self.load_awards()
        return self.payout_run

    def settle(self, **kw):
        self.payout_run = get_success_data(
            self.api.settle_true_up(self.payout_run["id"], FC, settle_payload(**kw))
        )
        self.refresh_plan()
        return self.payout_run

    def file_dispute(self, label, **overrides):
        dispute = get_success_data(
            self.api.create_dispute(
                dispute_payload(
                    self.plan_id, self.award_id(label), self.participant_id(label),
                    **overrides,
                ),
                self.employee_headers(label),
            )
        )
        self.disputes.append(dispute)
        return dispute

    def assign_dispute_review(self, dispute_id, **kw):
        return get_success_data(
            self.api.assign_dispute_review(dispute_id, HR, dispute_review_payload(**kw))
        )

    def resolve_dispute(self, dispute_id, resolution="UPHOLD", **kw):
        return get_success_data(
            self.api.resolve_dispute(
                dispute_id, dispute_resolution_payload(resolution, **kw), HR
            )
        )


# ─── Tier 1: setup-phase scenarios ────────────────────────────────────────
def build_setup_scenario(
    units=("U1",),
    plan_overrides=None,
    targets=DEFAULT_TARGETS,
    metrics=DEFAULT_METRICS,
    participants=DEFAULT_PARTICIPANTS,
    pooled_units=None,
    hook=None,
) -> BonusPlanScenario:
    """Units, plan, target grid, metric set, pools and the participant roster.

    Nothing has been actualized or certified yet: the plan is still in DRAFT.
    ``hook`` is a callable invoked with the scenario once the roster exists, for
    appending eligibility events before targets are assigned.
    """
    scenario = BonusPlanScenario()
    for unit_code in units:
        scenario.add_unit(unit_code)
    scenario.create_plan(**(plan_overrides or {}))
    for target in targets:
        scenario.add_target(**target)
    for metric in metrics:
        scenario.add_metric(**metric)
    for unit_code in pooled_units if pooled_units is not None else units:
        scenario.add_pool(unit_code)
    for participant in participants:
        spec = dict(participant)
        label = spec.pop("label")
        unit_code = spec.pop("unit_code", units[0])
        scenario.add_participant(label, unit_code, **spec)
    if hook is not None:
        hook(scenario)
    return scenario


def build_scorecard_certified_scenario(
    metric_actuals=None,
    scorecards=None,
    scorecard_certifier=CC_SCORECARD,
    **kwargs,
) -> BonusPlanScenario:
    """Setup scenario plus filed metric actuals and certified unit scorecards.

    ``metric_actuals`` maps metric_code to its audited actual (default: the
    target value, which scores 100.00). ``scorecards`` maps unit_code to the
    unit's scorecard achievement (default 100.00 for every pooled unit).
    """
    scenario = build_setup_scenario(**kwargs)
    actuals = metric_actuals or {
        code: TEST_DEFAULTS["METRIC_TARGET_VALUE"] for code in scenario.metrics
    }
    for metric_code, actual_value in actuals.items():
        scenario.file_actual(metric_code, actual_value)
    cards = scorecards or {unit_code: 100.00 for unit_code in scenario.pools}
    for unit_code, pct in cards.items():
        scenario.submit_scorecard(unit_code, pct)
        scenario.decide_scorecard(unit_code, "CERTIFY", user_id=scorecard_certifier)
    return scenario


def build_targets_set_scenario(**kwargs) -> BonusPlanScenario:
    """Scorecards certified and target assignment run: awards exist, plan TARGETS_SET."""
    scenario = build_scorecard_certified_scenario(**kwargs)
    scenario.assign_targets()
    return scenario


# ─── Tier 2: certified and funded scenarios ───────────────────────────────
def build_certified_scenario(certifier=CC_CERTIFIER, **kwargs) -> BonusPlanScenario:
    """Plan CERTIFIED with the achievement chain and the funding multiplier computed."""
    scenario = build_targets_set_scenario(**kwargs)
    scenario.submit_for_certification()
    scenario.decide_certification("CERTIFY", user_id=certifier)
    scenario.refresh_pools()
    return scenario


def build_funded_scenario(certifier=CC_CERTIFIER, **kwargs) -> BonusPlanScenario:
    """Plan ALLOCATION_OPEN with every pool funded and nothing allocated yet."""
    scenario = build_certified_scenario(certifier=certifier, **kwargs)
    scenario.fund(user_id=certifier)
    return scenario


# ─── Tier 3: allocated scenarios ──────────────────────────────────────────
def build_allocated_scenario(
    allocations=None, certifier=CC_CERTIFIER, **kwargs
) -> BonusPlanScenario:
    """Funded scenario with money proposed onto awards.

    ``allocations`` maps a participant label to its proposed cents; the default
    allocates the single default participant at exactly their prorated target.
    """
    scenario = build_funded_scenario(certifier=certifier, **kwargs)
    if allocations is None:
        allocations = {
            label: scenario.awards[label]["prorated_target_cents"]
            for label in scenario.awards
        }
    for label, cents in allocations.items():
        scenario.propose(label, cents, allocation_rationale="at target")
    return scenario


def build_calibration_review_scenario(
    allocations=None, certifier=CC_CERTIFIER, **kwargs
) -> BonusPlanScenario:
    """Every pool submitted and certified for calibration; plan CALIBRATION_REVIEW."""
    scenario = build_allocated_scenario(
        allocations=allocations, certifier=certifier, **kwargs
    )
    for unit_code in scenario.pools:
        scenario.submit_calibration(unit_code)
    scenario.open_calibration()
    for unit_code in scenario.pools:
        scenario.decide_calibration(unit_code, "CERTIFY")
    scenario.refresh_plan()
    return scenario


# ─── Tier 4: locked, paid out and settled scenarios ───────────────────────
def build_locked_scenario(
    allocations=None, certifier=CC_CERTIFIER, locker=CC_LOCKER, **kwargs
) -> BonusPlanScenario:
    """Plan LOCKED with every pool and award frozen and locked_total_cents summed."""
    scenario = build_calibration_review_scenario(
        allocations=allocations, certifier=certifier, **kwargs
    )
    scenario.lock(user_id=locker)
    return scenario


def build_paid_out_scenario(
    payment_clock=PAYMENT_DATE_CLOCK,
    allocations=None,
    certifier=CC_CERTIFIER,
    locker=CC_LOCKER,
    **kwargs,
) -> BonusPlanScenario:
    """Plan PAID_OUT: the clock has reached the payment date and the run executed."""
    scenario = build_locked_scenario(
        allocations=allocations, certifier=certifier, locker=locker, **kwargs
    )
    scenario.set_clock(payment_clock)
    scenario.open_payout_run()
    scenario.execute_payout()
    return scenario


def build_settled_scenario(**kwargs) -> BonusPlanScenario:
    """Plan SETTLED with the employer burden recomputed and the true-up booked."""
    scenario = build_paid_out_scenario(**kwargs)
    scenario.settle()
    return scenario


# ─── Tier 5: accrual scenarios ────────────────────────────────────────────
def build_accrual_scenario(
    periods=(
        (PLAN_PERIOD_START, "2026-06-30", 60.00),
        ("2026-07-01", "2026-12-31", 60.00),
    ),
    post_all=True,
    **kwargs,
) -> BonusPlanScenario:
    """A plan with a tiling set of accrual periods, posted in ascending order.

    Each entry of ``periods`` is ``(period_start, period_end, forecast_pct)``.
    """
    scenario = build_targets_set_scenario(**kwargs)
    for period_start, period_end, forecast in periods:
        period = scenario.open_accrual_period(period_start, period_end, forecast)
        if post_all:
            scenario.post_accrual_period(period["id"])
    scenario.refresh_plan()
    return scenario


__all__ = [
    "BonusPlanScenario",
    "PA",
    "HR",
    "FC",
    "DEFAULT_TARGETS",
    "DEFAULT_METRICS",
    "DEFAULT_PARTICIPANTS",
    "build_setup_scenario",
    "build_scorecard_certified_scenario",
    "build_targets_set_scenario",
    "build_certified_scenario",
    "build_funded_scenario",
    "build_allocated_scenario",
    "build_calibration_review_scenario",
    "build_locked_scenario",
    "build_paid_out_scenario",
    "build_settled_scenario",
    "build_accrual_scenario",
    "PLAN_PERIOD_START",
    "PLAN_PERIOD_END",
]

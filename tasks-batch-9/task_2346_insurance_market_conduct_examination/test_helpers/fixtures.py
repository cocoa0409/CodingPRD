"""Composite setup helpers.

Every helper builds its preconditions from scratch through the API the PRD
declares — each test starts against an empty database.  Setup calls use the
lenient ``get_success_data`` validator so a broken precondition reports itself
as a setup failure rather than as a confusing assertion failure.

Naming follows the PRD's own vocabulary: carriers are registered, examinations
are opened, scope is locked, data calls are issued / produced / dispositioned,
sampled files are reviewed, criticisms are issued / answered / rebutted /
finalized, plans are proposed and reviewed, consent orders are drafted and
executed, collaborations are opened and their restitution allocated.
"""

from typing import Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import STANDARD_PARTICIPATING_STATES, TEST_DEFAULTS
from .factories import (
    abort_payload,
    analysis_cycle_payload,
    clock_payload,
    collaboration_payload,
    company_response_payload,
    consent_order_payload,
    corrective_action_plan_payload,
    criticism_finalize_payload,
    criticism_payload,
    data_call_payload,
    data_call_response_payload,
    disposition_payload,
    examination_payload,
    fieldwork_activity_payload,
    file_review_payload,
    insurer_payload,
    order_execution_payload,
    plan_review_payload,
    publish_report_payload,
    rebuttal_payload,
    scope_area_payload,
    systematic_file_references,
)
from .test_users import (
    ANALYST,
    COORDINATOR,
    EIC,
    SUPERVISOR,
    SUPERVISOR_B,
    make_insurer_respondent_headers,
)

api = api_client

# The harm figures reused across the standard claims sample: three MATERIAL
# files quantifying 25000, 18000 and 7333 cents of consumer harm.
DEFAULT_HARM_CENTS: Tuple[int, ...] = (25_000, 18_000, 7_333)
DEFAULT_DAYS_TO_PAY: Tuple[int, ...] = (61, 47, 39)


# ─── Logical clock ────────────────────────────────────────────────────────


def set_clock(to_iso8601: str, headers: Optional[dict] = None) -> dict:
    """Move the logical clock and sweep overdue data calls."""
    return get_success_data(
        api.set_clock(clock_payload(to_iso8601), headers if headers is not None else ANALYST)
    )


# ─── Carriers ─────────────────────────────────────────────────────────────


def register_insurer(headers: Optional[dict] = None, **overrides) -> dict:
    """Register a regulated carrier.  Returns the created carrier."""
    return get_success_data(
        api.register_insurer(insurer_payload(**overrides), headers or ANALYST)
    )


def refresh_market_data(insurer_id: str, headers: Optional[dict] = None, **fields) -> dict:
    return get_success_data(
        api.refresh_market_data(insurer_id, dict(fields), headers or ANALYST)
    )


def read_insurer(insurer_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_insurer(insurer_id, headers or ANALYST))


# ─── Analysis cycles ──────────────────────────────────────────────────────


def create_analysis_cycle(headers: Optional[dict] = None, **overrides) -> dict:
    return get_success_data(
        api.create_analysis_cycle(analysis_cycle_payload(**overrides), headers or ANALYST)
    )


def score_cycle(cycle_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.score_analysis_cycle(cycle_id, headers or ANALYST))


def select_targets(
    cycle_id: str, min_composite_score: Optional[float] = None, headers: Optional[dict] = None
) -> dict:
    payload = None if min_composite_score is None else {"min_composite_score": min_composite_score}
    return get_success_data(api.select_targets(cycle_id, headers or ANALYST, payload))


def read_cycle(cycle_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_analysis_cycle(cycle_id, headers or ANALYST))


def read_cycle_scores(
    cycle_id: str, params: Optional[dict] = None, headers: Optional[dict] = None
) -> List[dict]:
    return get_success_data(api.list_cycle_scores(cycle_id, headers or ANALYST, params))


# ─── Examinations ─────────────────────────────────────────────────────────


def open_examination(insurer_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    return get_success_data(
        api.open_examination(examination_payload(insurer_id, **overrides), headers or SUPERVISOR)
    )


def read_examination(exam_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_examination(exam_id, headers or SUPERVISOR))


def add_scope_area(
    exam_id: str, area: str = "CLAIMS", headers: Optional[dict] = None, **overrides
) -> dict:
    return get_success_data(
        api.create_scope_area(exam_id, scope_area_payload(area, **overrides), headers or EIC)
    )


def lock_scope(exam_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.lock_scope(exam_id, headers or SUPERVISOR))


def read_scope_area(scope_area_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_scope_area(scope_area_id, headers or EIC))


def abort_examination(exam_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    return get_success_data(
        api.abort_examination(exam_id, abort_payload(**overrides), headers or SUPERVISOR)
    )


def publish_report(exam_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    return get_success_data(
        api.publish_report(exam_id, publish_report_payload(**overrides), headers or SUPERVISOR_B)
    )


# ─── Data calls ───────────────────────────────────────────────────────────


def issue_data_call(
    scope_area_id: str, headers: Optional[dict] = None, **overrides
) -> dict:
    return get_success_data(
        api.create_data_call(scope_area_id, data_call_payload(**overrides), headers or EIC)
    )


def respond_to_data_call(
    data_call_id: str, insurer_id: str, headers: Optional[dict] = None, **overrides
) -> dict:
    """The carrier produces records.  ``insurer_id`` threads the carrier identity."""
    return get_success_data(
        api.respond_to_data_call(
            data_call_id,
            data_call_response_payload(**overrides),
            headers or make_insurer_respondent_headers(insurer_id),
        )
    )


def disposition_data_call(
    data_call_id: str,
    disposition: str = "ACCEPTED",
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    return get_success_data(
        api.disposition_data_call(
            data_call_id, disposition_payload(disposition, **overrides), headers or EIC
        )
    )


def read_data_call(data_call_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_data_call(data_call_id, headers or EIC))


def read_file_samples(
    data_call_id: str, params: Optional[dict] = None, headers: Optional[dict] = None
) -> List[dict]:
    return get_success_data(api.list_file_samples(data_call_id, headers or EIC, params))


# ─── File review ──────────────────────────────────────────────────────────


def review_file_sample(
    file_sample_id: str,
    error_severity: str = "NONE",
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    return get_success_data(
        api.review_file_sample(
            file_sample_id, file_review_payload(error_severity, **overrides), headers or EIC
        )
    )


def bulk_review(data_call_id: str, reviews: List[dict], headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api.bulk_review(data_call_id, {"reviews": list(reviews)}, headers or EIC)
    )


def build_reviews(
    file_references: Sequence[str],
    harm_cents: Sequence[int] = DEFAULT_HARM_CENTS,
    severity: str = "MATERIAL",
    days_to_pay: Sequence[int] = DEFAULT_DAYS_TO_PAY,
    leave_unreviewed: int = 0,
) -> List[dict]:
    """Build a bulk-review array over deterministic file references.

    The first ``len(harm_cents)`` references are reviewed at ``severity`` with the
    quantified harm supplied; the remainder are reviewed clean.  ``leave_unreviewed``
    trims that many references off the end so a caller can leave the closing
    reviews for a later single-file review.
    """
    refs = list(file_references)
    if leave_unreviewed:
        refs = refs[:-leave_unreviewed]
    reviews: List[dict] = []
    for index, reference in enumerate(refs):
        if index < len(harm_cents):
            entry = {
                "file_reference": reference,
                "error_severity": severity,
                "underpaid_amount_cents": harm_cents[index],
            }
            if index < len(days_to_pay):
                entry["days_to_pay"] = days_to_pay[index]
            reviews.append(entry)
        else:
            reviews.append({"file_reference": reference, "error_severity": "NONE"})
    return reviews


# ─── Fieldwork workpapers ─────────────────────────────────────────────────


def record_fieldwork_activity(
    exam_id: str,
    activity_type: str = "SYSTEM_WALKTHROUGH",
    area: str = "CLAIMS",
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    return get_success_data(
        api.create_fieldwork_activity(
            exam_id,
            fieldwork_activity_payload(activity_type, area, **overrides),
            headers or EIC,
        )
    )


def record_standard_workpapers(exam_id: str, area: str = "CLAIMS") -> List[dict]:
    """One system walkthrough plus one interview, both documented.

    An ON_SITE examination needs both before a criticism may be issued; a DESK
    examination needs the walkthrough alone.
    """
    walkthrough = record_fieldwork_activity(
        exam_id,
        "SYSTEM_WALKTHROUGH",
        area,
        participant_name="R. Vance",
        participant_title="VP Claims Operations",
        summary="Walked the claims adjudication platform end to end with the carrier.",
        evidence_ref="WP-CLM-01",
    )
    interview = record_fieldwork_activity(
        exam_id,
        "INTERVIEW",
        area,
        participant_name="L. Ortiz",
        participant_title="Claims Manager",
        summary="Interviewed the claims manager on prompt-pay handling and denials.",
        evidence_ref="WP-CLM-02",
    )
    return [walkthrough, interview]


# ─── Criticisms ───────────────────────────────────────────────────────────


def issue_criticism(
    exam_id: str,
    scope_area_id: str,
    severity: str = "MATERIAL",
    affected_file_count: int = 3,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    return get_success_data(
        api.issue_criticism(
            criticism_payload(
                exam_id, scope_area_id, severity, affected_file_count, **overrides
            ),
            headers or EIC,
        )
    )


def respond_to_criticism(
    criticism_id: str,
    insurer_id: str,
    position: str = "DISPUTE",
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    return get_success_data(
        api.create_company_response(
            criticism_id,
            company_response_payload(position, **overrides),
            headers or make_insurer_respondent_headers(insurer_id),
        )
    )


def rebut_criticism(criticism_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    return get_success_data(
        api.rebut_criticism(criticism_id, rebuttal_payload(**overrides), headers or EIC)
    )


def finalize_criticism(
    criticism_id: str,
    disposition: str = "SUSTAINED",
    penalty_units: Optional[int] = 20,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    """Finalize a responded criticism.

    Defaults to the second supervising examiner because the acting user must
    differ from the criticism's issuer.
    """
    return get_success_data(
        api.finalize_criticism(
            criticism_id,
            criticism_finalize_payload(disposition, penalty_units, **overrides),
            headers or SUPERVISOR_B,
        )
    )


def read_criticism(criticism_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_criticism(criticism_id, headers or EIC))


# ─── Corrective action plans and consent orders ───────────────────────────


def propose_plan(
    exam_id: str,
    insurer_id: str,
    expected_examination_version: Optional[int] = None,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    """Propose a corrective action plan, pinning the examination version."""
    if expected_examination_version is None:
        expected_examination_version = read_examination(exam_id)["version"]
    return get_success_data(
        api.propose_corrective_action_plan(
            exam_id,
            corrective_action_plan_payload(expected_examination_version, **overrides),
            headers or make_insurer_respondent_headers(insurer_id),
        )
    )


def review_plan(
    plan_id: str, decision: str = "APPROVE", headers: Optional[dict] = None, **overrides
) -> dict:
    return get_success_data(
        api.review_corrective_action_plan(
            plan_id, plan_review_payload(decision, **overrides), headers or SUPERVISOR
        )
    )


def draft_consent_order(
    exam_id: str,
    expected_examination_version: Optional[int] = None,
    order_number: str = "MC-2026-0001",
    penalty_variant: str = "TIERED_AGGREGATE",
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    if expected_examination_version is None:
        expected_examination_version = read_examination(exam_id)["version"]
    return get_success_data(
        api.draft_consent_order(
            exam_id,
            consent_order_payload(
                expected_examination_version, order_number, penalty_variant, **overrides
            ),
            headers or SUPERVISOR,
        )
    )


def execute_consent_order(
    order_id: str, insurer_id: str, headers: Optional[dict] = None, **overrides
) -> dict:
    return get_success_data(
        api.execute_consent_order(
            order_id,
            order_execution_payload(**overrides),
            headers or make_insurer_respondent_headers(insurer_id),
        )
    )


def read_exposure_summary(exam_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_exposure_summary(exam_id, headers or SUPERVISOR))


# ─── Multistate collaboration ─────────────────────────────────────────────


def open_collaboration(
    exam_id: str,
    states: Optional[List[dict]] = None,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    return get_success_data(
        api.open_collaboration(
            exam_id, collaboration_payload(states, **overrides), headers or COORDINATOR
        )
    )


def allocate_restitution(collaboration_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api.allocate_restitution(collaboration_id, headers or COORDINATOR)
    )


def read_collaboration(collaboration_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_collaboration(collaboration_id, headers or COORDINATOR))


# ─── Composite scenarios ──────────────────────────────────────────────────
#
# Every composite returns a dict carrying at least:
#   insurer, insurer_id, respondent_headers, examination, exam_id
# and, as the chain deepens:
#   scope_areas (dict keyed by area), scope_area, scope_area_id,
#   data_call, data_call_id, file_samples, file_references, bulk_result,
#   criticism, criticism_id, plan, plan_id, consent_order, consent_order_id,
#   collaboration, collaboration_id, cycle, cycle_id


def setup_examination_in_scoping(
    insurer_overrides: Optional[dict] = None, **exam_overrides
) -> Dict:
    """A registered carrier with one examination in SCOPING."""
    insurer = register_insurer(**(insurer_overrides or {}))
    examination = open_examination(insurer["id"], **exam_overrides)
    return {
        "insurer": insurer,
        "insurer_id": insurer["id"],
        "respondent_headers": make_insurer_respondent_headers(insurer["id"]),
        "examination": examination,
        "exam_id": examination["id"],
    }


def setup_locked_examination(
    areas: Sequence[Tuple] = (("CLAIMS", 4000, 10),),
    insurer_overrides: Optional[dict] = None,
    area_overrides: Optional[Dict[str, dict]] = None,
    **exam_overrides,
) -> Dict:
    """Carrier + examination + scope areas + locked scope (examination in DATA_CALL).

    ``areas`` is a sequence of ``(area, population_size, sample_size)`` triples.
    ``area_overrides`` supplies extra per-area payload fields, e.g. a tolerance
    override: ``{"UNDERWRITING": {"error_tolerance_pct": 40.00}}``.
    """
    scenario = setup_examination_in_scoping(insurer_overrides, **exam_overrides)
    scope_areas: Dict[str, dict] = {}
    for area, population_size, sample_size in areas:
        extra = (area_overrides or {}).get(area, {})
        scope_areas[area] = add_scope_area(
            scenario["exam_id"],
            area,
            population_size=population_size,
            sample_size=sample_size,
            **extra,
        )
    lock_scope(scenario["exam_id"])
    scenario["scope_areas"] = scope_areas
    first = areas[0][0]
    scenario["scope_area"] = scope_areas[first]
    scenario["scope_area_id"] = scope_areas[first]["id"]
    scenario["examination"] = read_examination(scenario["exam_id"])
    return scenario


def setup_area_in_fieldwork(
    area: str = "CLAIMS",
    population_size: int = 4000,
    sample_size: int = 10,
    records_requested: Optional[int] = None,
    response_due_date: str = TEST_DEFAULTS["RESPONSE_DUE_DATE"],
    insurer_overrides: Optional[dict] = None,
    area_overrides: Optional[Dict[str, dict]] = None,
    **exam_overrides,
) -> Dict:
    """One scope area carried to FIELDWORK with its file samples drawn.

    Issues a data call over the whole population, has the carrier produce every
    record, accepts the production, and returns the drawn samples.
    """
    scenario = setup_locked_examination(
        areas=((area, population_size, sample_size),),
        insurer_overrides=insurer_overrides,
        area_overrides=area_overrides,
        **exam_overrides,
    )
    requested = population_size if records_requested is None else records_requested
    data_call = issue_data_call(
        scenario["scope_area_id"],
        records_requested=requested,
        response_due_date=response_due_date,
    )
    respond_to_data_call(
        data_call["id"], scenario["insurer_id"], records_received=requested
    )
    data_call = disposition_data_call(data_call["id"], "ACCEPTED")
    scenario["data_call"] = data_call
    scenario["data_call_id"] = data_call["id"]
    scenario["file_samples"] = read_file_samples(data_call["id"])
    scenario["file_references"] = systematic_file_references(
        area, population_size, sample_size
    )
    scenario["scope_area"] = read_scope_area(scenario["scope_area_id"])
    scenario["examination"] = read_examination(scenario["exam_id"])
    return scenario


def setup_examination_in_criticism(
    area: str = "CLAIMS",
    population_size: int = 4000,
    sample_size: int = 10,
    harm_cents: Sequence[int] = DEFAULT_HARM_CENTS,
    severity: str = "MATERIAL",
    with_collaboration: bool = False,
    participating_states: Optional[List[dict]] = None,
    insurer_overrides: Optional[dict] = None,
    area_overrides: Optional[Dict[str, dict]] = None,
    **exam_overrides,
) -> Dict:
    """The canonical fieldwork chain: examination in CRITICISM, area TESTED.

    Carrier registered, examination opened, one scope area added and the scope
    locked, one data call issued / produced / accepted, both fieldwork
    workpapers recorded, and every drawn sample reviewed in bulk — the closing
    review drives the area to TESTED and the examination to CRITICISM.
    """
    scenario = setup_area_in_fieldwork(
        area=area,
        population_size=population_size,
        sample_size=sample_size,
        insurer_overrides=insurer_overrides,
        area_overrides=area_overrides,
        **exam_overrides,
    )
    if with_collaboration:
        collaboration = open_collaboration(
            scenario["exam_id"],
            participating_states or STANDARD_PARTICIPATING_STATES,
        )
        scenario["collaboration"] = collaboration
        scenario["collaboration_id"] = collaboration["id"]
    record_standard_workpapers(scenario["exam_id"], area)
    reviews = build_reviews(scenario["file_references"], harm_cents, severity)
    scenario["bulk_result"] = bulk_review(scenario["data_call_id"], reviews)
    scenario["reviews"] = reviews
    scenario["scope_area"] = read_scope_area(scenario["scope_area_id"])
    scenario["data_call"] = read_data_call(scenario["data_call_id"])
    scenario["examination"] = read_examination(scenario["exam_id"])
    return scenario


def setup_examination_in_negotiation(
    criticism_severity: str = "MATERIAL",
    affected_file_count: int = 3,
    penalty_units: int = 20,
    **criticism_scenario_kwargs,
) -> Dict:
    """One criticism issued, answered and sustained — examination in NEGOTIATION."""
    scenario = setup_examination_in_criticism(**criticism_scenario_kwargs)
    criticism = issue_criticism(
        scenario["exam_id"],
        scenario["scope_area_id"],
        criticism_severity,
        affected_file_count,
    )
    respond_to_criticism(criticism["id"], scenario["insurer_id"], "DISPUTE")
    criticism = finalize_criticism(criticism["id"], "SUSTAINED", penalty_units)
    scenario["criticism"] = criticism
    scenario["criticism_id"] = criticism["id"]
    scenario["examination"] = read_examination(scenario["exam_id"])
    return scenario


def setup_examination_in_order_pending(**negotiation_kwargs) -> Dict:
    """A corrective action plan proposed and approved — examination in ORDER_PENDING."""
    scenario = setup_examination_in_negotiation(**negotiation_kwargs)
    plan = propose_plan(scenario["exam_id"], scenario["insurer_id"])
    plan = review_plan(plan["id"], "APPROVE")
    scenario["plan"] = plan
    scenario["plan_id"] = plan["id"]
    scenario["examination"] = read_examination(scenario["exam_id"])
    return scenario


def setup_examination_with_drafted_order(
    penalty_variant: str = "TIERED_AGGREGATE",
    order_number: str = "MC-2026-0001",
    **order_pending_kwargs,
) -> Dict:
    """An approved plan plus one consent order in DRAFT."""
    scenario = setup_examination_in_order_pending(**order_pending_kwargs)
    order = draft_consent_order(
        scenario["exam_id"],
        order_number=order_number,
        penalty_variant=penalty_variant,
    )
    scenario["consent_order"] = order
    scenario["consent_order_id"] = order["id"]
    scenario["examination"] = read_examination(scenario["exam_id"])
    return scenario


def setup_examination_with_executed_order(**drafted_order_kwargs) -> Dict:
    """A consent order executed by the carrier — examination still ORDER_PENDING."""
    scenario = setup_examination_with_drafted_order(**drafted_order_kwargs)
    order = execute_consent_order(scenario["consent_order_id"], scenario["insurer_id"])
    scenario["consent_order"] = order
    scenario["examination"] = read_examination(scenario["exam_id"])
    return scenario


def setup_settled_collaboration(**executed_order_kwargs) -> Dict:
    """An executed order plus an allocated multistate collaboration."""
    executed_order_kwargs.setdefault("with_collaboration", True)
    scenario = setup_examination_with_executed_order(**executed_order_kwargs)
    collaboration = allocate_restitution(scenario["collaboration_id"])
    scenario["collaboration"] = collaboration
    scenario["examination"] = read_examination(scenario["exam_id"])
    return scenario


# ─── Analysis cycle scenarios ─────────────────────────────────────────────


def setup_scored_cycle(
    carriers: Optional[Sequence[dict]] = None, **cycle_overrides
) -> Dict:
    """Register the supplied carriers, open a cycle and run the scoring pass.

    ``carriers`` is a sequence of payload override dicts, one per carrier.
    """
    if carriers is None:
        carriers = [{}]
    registered = [register_insurer(**overrides) for overrides in carriers]
    cycle = create_analysis_cycle(**cycle_overrides)
    cycle = score_cycle(cycle["id"])
    return {
        "insurers": registered,
        "insurer": registered[0],
        "insurer_id": registered[0]["id"],
        "respondent_headers": make_insurer_respondent_headers(registered[0]["id"]),
        "cycle": cycle,
        "cycle_id": cycle["id"],
        "scores": read_cycle_scores(cycle["id"]),
    }


def setup_cycle_with_selected_targets(
    carriers: Optional[Sequence[dict]] = None,
    min_composite_score: Optional[float] = None,
    **cycle_overrides,
) -> Dict:
    """A scored cycle whose targets have been selected, with the examinations it spawned."""
    scenario = setup_scored_cycle(carriers, **cycle_overrides)
    scenario["cycle"] = select_targets(scenario["cycle_id"], min_composite_score)
    scenario["scores"] = read_cycle_scores(scenario["cycle_id"])
    examinations = get_success_data(
        api.list_examinations(SUPERVISOR, {"cycle_id": scenario["cycle_id"], "limit": 100})
    )
    scenario["examinations"] = examinations
    if examinations:
        scenario["examination"] = examinations[0]
        scenario["exam_id"] = examinations[0]["id"]
    return scenario

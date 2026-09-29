"""Composite setup helpers.

The API server is restarted before every test, so each test begins against an
empty database.  Everything a test needs must therefore be built from scratch
through the PRD-declared endpoints; these helpers are the shared, layered way of
doing that.

Layers, cheapest first:

* reference data      -- clock, carriers, drivers, violation codes, thresholds
* state progression   -- report intake -> RECEIVED -> VALIDATED -> SCORED
* entity hierarchy    -- a scored report with its violations and BASIC scores
* full lifecycles     -- challenges through review, CAPs through the fork-join
* terminal states     -- resolved challenges, accepted plans, expired windows

Every helper accepts `**overrides` that are merged into the request body, so a
caller can retarget a single field without copying the whole chain.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import CLOCK_DEFAULT_UTC, TEST_DEFAULTS
from .test_users import (
    AUDITOR_ALICE,
    AUDITOR_BOB,
    AUDITOR_CAROL,
    REVIEW_OFFICER_ID,
    STATE_OFFICER_ID,
    make_auditor_headers,
    make_carrier_analyst_headers,
    make_carrier_safety_manager_headers,
    make_review_officer_headers,
    make_state_officer_headers,
)
from .types import (
    BasicCategory,
    CapItemAction,
    CapReviewBranch,
    CapReviewOutcome,
    ChallengeType,
    CourtStatus,
    EvidenceType,
    ReviewAction,
    SafetyFitnessStatus,
    UnitType,
)

AUDITOR = make_auditor_headers(AUDITOR_ALICE)
OFFICER = make_state_officer_headers(STATE_OFFICER_ID)
REVIEWER = make_review_officer_headers(REVIEW_OFFICER_ID)


# ---------------------------------------------------------------------------
# Layer 0 -- the logical clock
# ---------------------------------------------------------------------------
def set_clock(api: ApiClient, to_iso8601: str = CLOCK_DEFAULT_UTC) -> Dict[str, Any]:
    """Move the logical clock; every age, deadline and window rule reads it."""
    return get_success_data(api.set_clock(to_iso8601, AUDITOR))


# ---------------------------------------------------------------------------
# Layer 1 -- reference data
# ---------------------------------------------------------------------------
def create_carrier(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a carrier.  Defaults to 20 power units / 1,600,000 VMT (MEDIUM,
    utilization factor 1.5, power-unit exposure 30.0)."""
    return get_success_data(
        api.create_carrier(f.create_carrier_payload(**overrides), AUDITOR)
    )


def create_small_carrier(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A 10-power-unit / 1,200,000 VMT carrier: SMALL, factor 1.8, exposure 18.0."""
    payload = {
        "average_power_units": TEST_DEFAULTS["small_carrier_power_units"],
        "annual_vmt": TEST_DEFAULTS["small_carrier_annual_vmt"],
        "legal_name": "Cascade Hauling Inc",
    }
    payload.update(overrides)
    return create_carrier(api, **payload)


def create_driver(api: ApiClient, carrier_id: str, **overrides: Any) -> Dict[str, Any]:
    """Register a driver under `carrier_id` (the safety manager acts for that carrier)."""
    return get_success_data(
        api.create_driver(
            f.create_driver_payload(carrier_id, **overrides),
            make_carrier_safety_manager_headers(carrier_id),
        )
    )


def create_violation_code(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_violation_code(f.create_violation_code_payload(**overrides), AUDITOR)
    )


def create_threshold(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_intervention_threshold(
            f.create_intervention_threshold_payload(**overrides), AUDITOR
        )
    )


def create_thresholds_for_all_categories(
    api: ApiClient,
    carrier_segment: str = "MEDIUM",
    measures: Tuple[float, float, float] = (1.0, 2.0, 4.0),
    **overrides: Any,
) -> Dict[str, Dict[str, Any]]:
    """Publish one threshold row per BASIC category for a single segment."""
    rows: Dict[str, Dict[str, Any]] = {}
    for category in (
        BasicCategory.UNSAFE_DRIVING,
        BasicCategory.HOURS_OF_SERVICE,
        BasicCategory.VEHICLE_MAINTENANCE,
        BasicCategory.DRIVER_FITNESS,
    ):
        rows[category] = create_threshold(
            api,
            basic_category=category,
            carrier_segment=carrier_segment,
            measure_at_p50=measures[0],
            measure_at_p65=measures[1],
            measure_at_p80=measures[2],
            **overrides,
        )
    return rows


# ---------------------------------------------------------------------------
# Layer 2 -- report intake and state progression
# ---------------------------------------------------------------------------
def create_report(
    api: ApiClient,
    carrier_id: str,
    officer_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Ingest a roadside inspection report against `carrier_id`."""
    return get_success_data(
        api.create_inspection_report(
            f.create_inspection_report_payload(carrier_id, **overrides),
            officer_headers or OFFICER,
        )
    )


def add_violation(
    api: ApiClient,
    report_id: str,
    violation_code_id: str,
    officer_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Append a violation to a report that is still RECEIVED."""
    return get_success_data(
        api.add_violation(
            report_id,
            f.create_violation_payload(violation_code_id, **overrides),
            officer_headers or OFFICER,
        )
    )


def validate_report(
    api: ApiClient, report_id: str, officer_headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(api.validate_report(report_id, officer_headers or OFFICER))


def score_report(
    api: ApiClient, report_id: str, officer_headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(api.score_report(report_id, officer_headers or OFFICER))


def build_validated_report(
    api: ApiClient,
    carrier_id: str,
    violations: Sequence[Dict[str, Any]],
    officer_headers: Optional[Dict[str, str]] = None,
    **report_overrides: Any,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Ingest a report, append `violations`, then move it to VALIDATED.

    `violations` is a sequence of dicts; each must carry `violation_code_id` and
    may carry `unit_type`, `driver_id` or `out_of_service`.
    """
    headers = officer_headers or OFFICER
    report = create_report(api, carrier_id, headers, **report_overrides)
    rows = [
        add_violation(
            api,
            report["id"],
            spec["violation_code_id"],
            headers,
            **{k: v for k, v in spec.items() if k != "violation_code_id"},
        )
        for spec in violations
    ]
    validate_report(api, report["id"], headers)
    return report, rows


def build_scored_report(
    api: ApiClient,
    carrier_id: str,
    violations: Sequence[Dict[str, Any]],
    officer_headers: Optional[Dict[str, str]] = None,
    **report_overrides: Any,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Ingest, populate, validate and score a report in one call.

    Returns the report as it stands after scoring together with its violations,
    each re-read so the pinned weights and time-weighted severities are current.
    """
    headers = officer_headers or OFFICER
    report, rows = build_validated_report(
        api, carrier_id, violations, headers, **report_overrides
    )
    score_report(api, report["id"], headers)
    fresh_report = get_success_data(api.get_inspection_report(report["id"], headers))
    fresh_rows = [
        get_success_data(api.get_violation(row["id"], headers)) for row in rows
    ]
    return fresh_report, fresh_rows


def build_single_violation_scored_report(
    api: ApiClient,
    severity_weight: int = 5,
    basic_category: str = BasicCategory.UNSAFE_DRIVING,
    measures: Tuple[float, float, float] = (0.5, 1.0, 2.0),
    carrier_overrides: Optional[Dict[str, Any]] = None,
    **report_overrides: Any,
) -> Dict[str, Any]:
    """The smallest complete scoring scenario: one carrier, one code, one
    threshold, one violation, report SCORED.

    Returns a dict with keys `carrier`, `code`, `threshold`, `report`,
    `violations`.
    """
    set_clock(api)
    carrier = create_carrier(api, **(carrier_overrides or {}))
    code = create_violation_code(
        api, basic_category=basic_category, severity_weight=severity_weight
    )
    threshold = create_threshold(
        api,
        basic_category=basic_category,
        carrier_segment=carrier["carrier_segment"],
        measure_at_p50=measures[0],
        measure_at_p65=measures[1],
        measure_at_p80=measures[2],
    )
    report, rows = build_scored_report(
        api,
        carrier["id"],
        [{"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE}],
        **report_overrides,
    )
    return {
        "carrier": carrier,
        "code": code,
        "threshold": threshold,
        "report": report,
        "violations": rows,
    }


def read_carrier(api: ApiClient, carrier_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_carrier(carrier_id, AUDITOR))


def read_violation(api: ApiClient, violation_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_violation(violation_id, AUDITOR))


def read_report(api: ApiClient, report_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_inspection_report(report_id, AUDITOR))


def read_driver(api: ApiClient, driver_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_driver(driver_id, AUDITOR))


def read_screening_risk(api: ApiClient, carrier_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_screening_risk(carrier_id, AUDITOR))


def read_basic_scores(api: ApiClient, carrier_id: str) -> List[Dict[str, Any]]:
    body = api.list_basic_scores(AUDITOR, {"carrier_id": carrier_id, "limit": 100})
    return get_success_data(body)


def read_basic_score(
    api: ApiClient, carrier_id: str, basic_category: str
) -> Dict[str, Any]:
    rows = get_success_data(
        api.list_basic_scores(
            AUDITOR, {"carrier_id": carrier_id, "basic_category": basic_category}
        )
    )
    assert len(rows) == 1, (
        f"expected exactly one {basic_category} score row for the carrier, got {len(rows)}"
    )
    return rows[0]


def current_version(api: ApiClient, kind: str, resource_id: str) -> int:
    """Read the live version of a carrier, report or violation for an OCC guard."""
    readers = {
        "carrier": api.get_carrier,
        "report": api.get_inspection_report,
        "violation": api.get_violation,
    }
    assert kind in readers, f"unsupported OCC parent kind: {kind}"
    return get_success_data(readers[kind](resource_id, AUDITOR))["version"]


# ---------------------------------------------------------------------------
# Layer 3 -- driver attribution and coaching
# ---------------------------------------------------------------------------
def attribute_driver(
    api: ApiClient, carrier_id: str, violation_id: str, driver_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.attribute_driver(
            violation_id,
            {"driver_id": driver_id},
            make_carrier_safety_manager_headers(carrier_id),
        )
    )


def build_driver_with_attributed_violations(
    api: ApiClient,
    severity_weight: int = 8,
    violation_count: int = 2,
    measures: Tuple[float, float, float] = (0.5, 1.0, 2.0),
) -> Dict[str, Any]:
    """A carrier with one driver holding `violation_count` DRIVER-unit violations
    on a SCORED report, so the driver's attribution scores are populated."""
    set_clock(api)
    carrier = create_carrier(api)
    driver = create_driver(api, carrier["id"])
    code = create_violation_code(
        api,
        basic_category=BasicCategory.UNSAFE_DRIVING,
        severity_weight=severity_weight,
    )
    create_threshold(
        api,
        basic_category=BasicCategory.UNSAFE_DRIVING,
        carrier_segment=carrier["carrier_segment"],
        measure_at_p50=measures[0],
        measure_at_p65=measures[1],
        measure_at_p80=measures[2],
    )
    report, rows = build_scored_report(
        api,
        carrier["id"],
        [
            {
                "violation_code_id": code["id"],
                "unit_type": UnitType.DRIVER,
                "driver_id": driver["id"],
            }
            for _ in range(violation_count)
        ],
        driver_id=driver["id"],
    )
    return {
        "carrier": carrier,
        "driver": driver,
        "code": code,
        "report": report,
        "violations": rows,
    }


def create_coaching_assignment(
    api: ApiClient, carrier_id: str, driver_id: str, violation_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_coaching_assignment(
            f.create_coaching_assignment_payload(driver_id, violation_id, **overrides),
            make_carrier_safety_manager_headers(carrier_id),
        )
    )


# ---------------------------------------------------------------------------
# Layer 4 -- data challenges
# ---------------------------------------------------------------------------
def create_draft_challenge(
    api: ApiClient, carrier_id: str, report_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_data_challenge(
            f.create_data_challenge_payload(report_id, **overrides),
            make_carrier_analyst_headers(carrier_id),
        )
    )


def add_evidence(
    api: ApiClient, carrier_id: str, challenge_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.add_evidence(
            challenge_id,
            f.create_evidence_payload(**overrides),
            make_carrier_analyst_headers(carrier_id),
        )
    )


def submit_challenge(api: ApiClient, carrier_id: str, challenge_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.submit_challenge(challenge_id, make_carrier_analyst_headers(carrier_id))
    )


def review_challenge(
    api: ApiClient, challenge_id: str, action: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.review_challenge(challenge_id, f.review_payload(action, **overrides), REVIEWER)
    )


def build_submitted_challenge(
    api: ApiClient,
    carrier_id: str,
    report_id: str,
    evidence_type: str = EvidenceType.ELD_RECORD,
    **overrides: Any,
) -> Dict[str, Any]:
    """Draft a challenge, attach one evidence row and submit it."""
    challenge = create_draft_challenge(api, carrier_id, report_id, **overrides)
    add_evidence(api, carrier_id, challenge["id"], evidence_type=evidence_type)
    submit_challenge(api, carrier_id, challenge["id"])
    return get_success_data(
        api.get_data_challenge(challenge["id"], make_carrier_analyst_headers(carrier_id))
    )


def build_challenge_under_review(
    api: ApiClient,
    carrier_id: str,
    report_id: str,
    evidence_type: str = EvidenceType.ELD_RECORD,
    **overrides: Any,
) -> Dict[str, Any]:
    """Submit a challenge and let the review officer ASSIGN it."""
    challenge = build_submitted_challenge(
        api, carrier_id, report_id, evidence_type, **overrides
    )
    review_challenge(api, challenge["id"], ReviewAction.ASSIGN)
    return get_success_data(api.get_data_challenge(challenge["id"], REVIEWER))


def cycle_information_request(
    api: ApiClient,
    carrier_id: str,
    challenge_id: str,
    evidence_type: str = EvidenceType.ELD_RECORD,
) -> None:
    """One full REQUEST_INFO / resubmit / ASSIGN round trip on an UNDER_REVIEW
    challenge, leaving it UNDER_REVIEW again with the round counter advanced."""
    review_challenge(api, challenge_id, ReviewAction.REQUEST_INFO)
    add_evidence(api, carrier_id, challenge_id, evidence_type=evidence_type)
    submit_challenge(api, carrier_id, challenge_id)
    review_challenge(api, challenge_id, ReviewAction.ASSIGN)


# ---------------------------------------------------------------------------
# Layer 5 -- citation adjudications
# ---------------------------------------------------------------------------
def create_adjudication(
    api: ApiClient,
    violation_id: str,
    officer_headers: Optional[Dict[str, str]] = None,
    expected_violation_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Record a citation against a violation, reading the live version for the
    OCC guard unless the caller pins one deliberately."""
    version = (
        expected_violation_version
        if expected_violation_version is not None
        else current_version(api, "violation", violation_id)
    )
    return get_success_data(
        api.create_citation_adjudication(
            f.create_citation_adjudication_payload(violation_id, version, **overrides),
            officer_headers or OFFICER,
        )
    )


def record_court_result(
    api: ApiClient, adjudication_id: str, court_status: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.record_court_result(
            adjudication_id, f.court_result_payload(court_status, **overrides), OFFICER
        )
    )


def apply_adjudication(api: ApiClient, adjudication_id: str) -> Dict[str, Any]:
    return get_success_data(api.apply_to_record(adjudication_id, REVIEWER))


def build_adjudicated_violation(
    api: ApiClient,
    court_status: str = CourtStatus.DISMISSED,
    severity_weight: int = 5,
    measures: Tuple[float, float, float] = (0.5, 1.0, 2.0),
) -> Dict[str, Any]:
    """A scored single-violation report whose violation carries a citation with
    `court_status` already recorded but not yet applied to the record."""
    scenario = build_single_violation_scored_report(
        api, severity_weight=severity_weight, measures=measures
    )
    violation = scenario["violations"][0]
    adjudication = create_adjudication(api, violation["id"])
    record_court_result(api, adjudication["id"], court_status)
    scenario["adjudication"] = get_success_data(
        api.get_citation_adjudication(adjudication["id"], OFFICER)
    )
    return scenario


# ---------------------------------------------------------------------------
# Layer 6 -- fitness determinations and corrective action plans
# ---------------------------------------------------------------------------
def issue_fitness_determination(
    api: ApiClient,
    carrier_id: str,
    determination: str = SafetyFitnessStatus.CONDITIONAL,
    auditor_id: str = AUDITOR_ALICE,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "determination": determination,
        "basis_note": "Compliance review found acute violations.",
    }
    payload.update(overrides)
    return get_success_data(
        api.issue_fitness_determination(
            carrier_id, payload, make_auditor_headers(auditor_id)
        )
    )


def create_cap(
    api: ApiClient, carrier_id: str, expected_carrier_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    version = (
        expected_carrier_version
        if expected_carrier_version is not None
        else current_version(api, "carrier", carrier_id)
    )
    return get_success_data(
        api.create_corrective_action_plan(
            f.create_cap_payload(carrier_id, version, **overrides),
            make_carrier_analyst_headers(carrier_id),
        )
    )


def add_cap_item(
    api: ApiClient, carrier_id: str, cap_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.add_action_item(
            cap_id,
            f.create_cap_action_item_payload(**overrides),
            make_carrier_analyst_headers(carrier_id),
        )
    )


def set_item_status(
    api: ApiClient, item_id: str, action: str, headers: Dict[str, str], **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.set_action_item_status(
            item_id, f.cap_item_status_payload(action, **overrides), headers
        )
    )


def build_cap_with_committed_items(
    api: ApiClient,
    item_count: int = 3,
    determination: str = SafetyFitnessStatus.CONDITIONAL,
    determining_auditor: str = AUDITOR_ALICE,
) -> Dict[str, Any]:
    """A CONDITIONAL (or UNSATISFACTORY) carrier with a DRAFT plan whose items are
    all COMMITTED, i.e. ready to submit."""
    set_clock(api)
    carrier = create_carrier(api)
    issue_fitness_determination(
        api, carrier["id"], determination, auditor_id=determining_auditor
    )
    cap = create_cap(api, carrier["id"])
    analyst = make_carrier_analyst_headers(carrier["id"])
    categories = [
        BasicCategory.HOURS_OF_SERVICE,
        BasicCategory.VEHICLE_MAINTENANCE,
        BasicCategory.UNSAFE_DRIVING,
        BasicCategory.DRIVER_FITNESS,
    ]
    items = []
    for index in range(item_count):
        item = add_cap_item(
            api,
            carrier["id"],
            cap["id"],
            basic_category=categories[index % len(categories)],
            description=f"Remediation step {index + 1}.",
        )
        set_item_status(api, item["id"], CapItemAction.COMMIT, analyst)
        items.append(item)
    return {"carrier": carrier, "cap": cap, "items": items}


def build_cap_in_review(
    api: ApiClient,
    item_count: int = 3,
    safety_auditor: str = AUDITOR_BOB,
    data_auditor: str = AUDITOR_CAROL,
    implement_items: bool = True,
) -> Dict[str, Any]:
    """A submitted plan with both review branches CLEARED, so the plan sits in
    IN_REVIEW waiting on full item verification to reach the join."""
    scenario = build_cap_with_committed_items(api, item_count=item_count)
    carrier_id = scenario["carrier"]["id"]
    manager = make_carrier_safety_manager_headers(carrier_id)
    get_success_data(api.submit_cap(scenario["cap"]["id"], manager))
    get_success_data(
        api.review_cap(
            scenario["cap"]["id"],
            {
                "branch": CapReviewBranch.SAFETY,
                "outcome": CapReviewOutcome.CLEARED,
                "note": "Safety branch satisfied.",
            },
            make_auditor_headers(safety_auditor),
        )
    )
    get_success_data(
        api.review_cap(
            scenario["cap"]["id"],
            {
                "branch": CapReviewBranch.DATA,
                "outcome": CapReviewOutcome.CLEARED,
                "note": "Data branch satisfied.",
            },
            make_auditor_headers(data_auditor),
        )
    )
    if implement_items:
        for item in scenario["items"]:
            set_item_status(api, item["id"], CapItemAction.IMPLEMENT, manager)
    scenario["cap"] = get_success_data(
        api.get_corrective_action_plan(scenario["cap"]["id"], AUDITOR)
    )
    return scenario


def read_cap(api: ApiClient, cap_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_corrective_action_plan(cap_id, AUDITOR))


# ---------------------------------------------------------------------------
# Layer 7 -- scoring runs
# ---------------------------------------------------------------------------
def run_scoring(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Checkpoint every carrier at the current logical clock reading."""
    return get_success_data(
        api.create_scoring_run(f.create_scoring_run_payload(**overrides), AUDITOR)
    )

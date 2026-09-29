"""Composite setup helpers.

The harness restarts the server and empties the store before every single test,
so nothing here may assume prior state: each helper rebuilds what it needs
through the public endpoints of PRD section 4, in the order the specification
allows.

The layering is deliberate. The thin wrappers at the top do one call each and
unwrap the success envelope, so a test that wants to watch one transition can
drive the API a step at a time. `build_program` above them walks the whole
manufacturing chain — suite qualification, project intake and technology
transfer, component release, scheduling, reservation, setup, filling,
in-process control, batch record review and Qualified-Person release — and stops
at whichever stage the caller names, so a test about the last step does not have
to restate the first thirty.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .assertions import expected_line_demand
from .constants import COMPONENT_LINES, SCENARIO_CLOCK
from .test_users import (
    MICROBIOLOGY_ANALYST,
    PRODUCTION_SUPERVISOR,
    PROGRAM_MANAGER,
    QA_REVIEWER,
    QA_REVIEWER_SECOND,
    QUALIFIED_PERSON,
)

Json = Dict[str, Any]
Headers = Dict[str, str]


def _data(response: Any, expected_status: Optional[int] = None) -> Json:
    """Unwrap a success envelope, failing loudly on an unexpected status."""
    return get_success_data(response, expected_status)


# ---------------------------------------------------------------------------
# Tier 1: one call each
# ---------------------------------------------------------------------------
def set_clock(api: Any, to_iso8601: str, headers: Optional[Headers] = None) -> Json:
    """Move the logical clock of PRD 2.4."""
    response = api.set_clock(
        factories.clock_payload(to_iso8601), headers or PROGRAM_MANAGER
    )
    return _data(response, 200)


def create_suite(api: Any, headers: Optional[Headers] = None, **kwargs: Any) -> Json:
    """Commission a filling suite."""
    response = api.create_filling_suite(
        factories.filling_suite_payload(**kwargs), headers or PROGRAM_MANAGER
    )
    return _data(response, 201)


def read_suite(api: Any, suite_id: str, headers: Optional[Headers] = None) -> Json:
    """Read a filling suite, including its derived posture."""
    response = api.get_filling_suite(suite_id, headers or PROGRAM_MANAGER)
    return _data(response, 200)


def suite_version(api: Any, suite_id: str, headers: Optional[Headers] = None) -> int:
    """The suite `version` a batch order must echo, per PRD 2.7."""
    return int(read_suite(api, suite_id, headers)["version"])


def record_cleaning_validation(
    api: Any, suite_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Record a cleaning-validation swab result."""
    response = api.record_cleaning_validation(
        suite_id,
        factories.cleaning_validation_payload(**kwargs),
        headers or MICROBIOLOGY_ANALYST,
    )
    return _data(response, 200)


def create_media_fill(
    api: Any, suite_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Schedule an aseptic process simulation."""
    response = api.create_media_fill(
        factories.media_fill_payload(suite_id, **kwargs),
        headers or MICROBIOLOGY_ANALYST,
    )
    return _data(response, 201)


def execute_media_fill(
    api: Any, media_fill_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Run a scheduled simulation and start its incubation."""
    response = api.execute_media_fill(
        media_fill_id,
        factories.media_fill_execute_payload(**kwargs),
        headers or MICROBIOLOGY_ANALYST,
    )
    return _data(response, 200)


def read_media_fill_out(
    api: Any,
    media_fill_id: str,
    contaminated_units: int = 0,
    headers: Optional[Headers] = None,
) -> Json:
    """Take the incubation read-out of PRD 3.2."""
    response = api.read_media_fill(
        media_fill_id,
        factories.media_fill_read_payload(contaminated_units),
        headers or MICROBIOLOGY_ANALYST,
    )
    return _data(response, 200)


def adjudicate_media_fill(
    api: Any, media_fill_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Adjudicate a simulation that forked to investigation."""
    response = api.adjudicate_media_fill(
        media_fill_id,
        factories.media_fill_adjudicate_payload(**kwargs),
        headers or QA_REVIEWER,
    )
    return _data(response, 200)


def read_media_fill(
    api: Any, media_fill_id: str, headers: Optional[Headers] = None
) -> Json:
    """Read a simulation record."""
    response = api.get_media_fill(
        media_fill_id, headers or MICROBIOLOGY_ANALYST
    )
    return _data(response, 200)


def create_qualification(
    api: Any,
    operator_name: str,
    suite_id: str,
    headers: Optional[Headers] = None,
    **kwargs: Any,
) -> Json:
    """Raise an operator qualification record."""
    response = api.create_qualification(
        factories.qualification_payload(operator_name, suite_id, **kwargs),
        headers or MICROBIOLOGY_ANALYST,
    )
    return _data(response, 201)


def qualify(
    api: Any, qualification_id: str, headers: Optional[Headers] = None
) -> Json:
    """Grant a pending operator qualification."""
    response = api.qualify(
        qualification_id, headers or MICROBIOLOGY_ANALYST
    )
    return _data(response, 200)


def read_qualification(
    api: Any, qualification_id: str, headers: Optional[Headers] = None
) -> Json:
    """Read an operator qualification record."""
    response = api.get_qualification(
        qualification_id, headers or MICROBIOLOGY_ANALYST
    )
    return _data(response, 200)


def create_project(
    api: Any, primary_suite_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Intake a client project."""
    response = api.create_client_project(
        factories.client_project_payload(primary_suite_id, **kwargs),
        headers or PROGRAM_MANAGER,
    )
    return _data(response, 201)


def read_project(api: Any, project_id: str, headers: Optional[Headers] = None) -> Json:
    """Read a client project, including its three ledgers."""
    response = api.get_client_project(
        project_id, headers or PROGRAM_MANAGER
    )
    return _data(response, 200)


def advance_tech_transfer(
    api: Any,
    project_id: str,
    to_stage: str,
    analytical_method_transfer_status: str,
    headers: Optional[Headers] = None,
) -> Json:
    """Take one technology-transfer hop."""
    response = api.advance_tech_transfer(
        project_id,
        factories.advance_tech_transfer_payload(
            to_stage, analytical_method_transfer_status
        ),
        headers or PROGRAM_MANAGER,
    )
    return _data(response, 200)


def activate_project(
    api: Any, project_id: str, headers: Optional[Headers] = None
) -> Json:
    """Walk all three technology-transfer hops, which activates the project."""
    advance_tech_transfer(api, project_id, "GAP_ASSESSMENT", "IN_TRANSFER", headers)
    advance_tech_transfer(api, project_id, "ENGINEERING_RUN", "IN_TRANSFER", headers)
    return advance_tech_transfer(api, project_id, "COMPLETE", "VALIDATED", headers)


def release_hold(
    api: Any, project_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Release a project hold."""
    response = api.release_hold(
        project_id, factories.release_hold_payload(**kwargs), headers or QA_REVIEWER
    )
    return _data(response, 200)


def readiness(
    api: Any, project_id: str, variant: str, headers: Optional[Headers] = None
) -> Json:
    """Read one variant of the readiness assessment of PRD 3.9."""
    response = api.get_readiness_assessment(
        project_id, headers or PROGRAM_MANAGER, {"variant": variant}
    )
    return _data(response, 200)


def create_lot(
    api: Any, client_project_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Book in a component lot, which lands in quarantine."""
    response = api.create_component_lot(
        factories.component_lot_payload(client_project_id, **kwargs),
        headers or PROGRAM_MANAGER,
    )
    return _data(response, 201)


def validate_sterilization(
    api: Any, lot_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Record the sterilisation-validation verdict on a lot."""
    response = api.record_sterilization_validation(
        lot_id,
        factories.sterilization_validation_payload(**kwargs),
        headers or MICROBIOLOGY_ANALYST,
    )
    return _data(response, 200)


def release_lot(
    api: Any, client_project_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Book in a lot and release it, opening its full received quantity."""
    lot = create_lot(api, client_project_id, headers, **kwargs)
    return validate_sterilization(api, lot["id"], headers)


def read_lot(api: Any, lot_id: str, headers: Optional[Headers] = None) -> Json:
    """Read a component lot, including its available quantity."""
    response = api.get_component_lot(lot_id, headers or PROGRAM_MANAGER)
    return _data(response, 200)


def lot_version(api: Any, lot_id: str, headers: Optional[Headers] = None) -> int:
    """The lot `version` a reservation must echo, per PRD 2.7."""
    return int(read_lot(api, lot_id, headers)["version"])


def create_batch(
    api: Any,
    client_project_id: str,
    suite_id: str,
    lead_operator_qualification_id: str,
    expected_suite_version: Optional[int] = None,
    headers: Optional[Headers] = None,
    **kwargs: Any,
) -> Json:
    """Schedule a batch order, echoing the suite version of PRD 2.7."""
    if expected_suite_version is None:
        expected_suite_version = suite_version(api, suite_id)
    response = api.create_batch_order(
        factories.batch_order_payload(
            client_project_id,
            suite_id,
            lead_operator_qualification_id,
            expected_suite_version,
            **kwargs,
        ),
        headers or PROGRAM_MANAGER,
    )
    return _data(response, 201)


def read_batch(api: Any, batch_id: str, headers: Optional[Headers] = None) -> Json:
    """Read a batch order, including both of its status axes."""
    response = api.get_batch_order(batch_id, headers or PROGRAM_MANAGER)
    return _data(response, 200)


def unit_accounting(
    api: Any, batch_id: str, headers: Optional[Headers] = None
) -> Json:
    """Read the two releasable-unit variants side by side."""
    response = api.get_unit_accounting(batch_id, headers or QA_REVIEWER)
    return _data(response, 200)


def reserve(
    api: Any,
    batch_order_id: str,
    component_lot_id: str,
    quantity_reserved: int,
    expected_component_lot_version: Optional[int] = None,
    headers: Optional[Headers] = None,
) -> Json:
    """Reserve units from a released lot against a batch."""
    if expected_component_lot_version is None:
        expected_component_lot_version = lot_version(api, component_lot_id)
    response = api.create_component_reservation(
        factories.component_reservation_payload(
            batch_order_id,
            component_lot_id,
            quantity_reserved,
            expected_component_lot_version,
        ),
        headers or PROGRAM_MANAGER,
    )
    return _data(response, 201)


def setup_batch(api: Any, batch_id: str, headers: Optional[Headers] = None) -> Json:
    """Move a batch onto the line."""
    response = api.setup_batch(
        batch_id, headers or PRODUCTION_SUPERVISOR
    )
    return _data(response, 200)


def start_fill(api: Any, batch_id: str, headers: Optional[Headers] = None) -> Json:
    """Start the aseptic fill."""
    response = api.start_fill(batch_id, headers or PRODUCTION_SUPERVISOR)
    return _data(response, 200)


def complete_fill(
    api: Any,
    batch_id: str,
    filled_unit_count: int = 8500,
    headers: Optional[Headers] = None,
) -> Json:
    """Close the fill and stamp the provisional releasable figure."""
    response = api.complete_fill(
        batch_id,
        factories.complete_fill_payload(filled_unit_count),
        headers or PRODUCTION_SUPERVISOR,
    )
    return _data(response, 200)


def cancel_batch(
    api: Any, batch_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Cancel a batch, unwinding exactly what scheduling added."""
    response = api.cancel_batch(
        batch_id, factories.cancel_payload(**kwargs), headers or PROGRAM_MANAGER
    )
    return _data(response, 200)


def record_fill_weight_check(
    api: Any, batch_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Record a fill-weight in-process control."""
    response = api.create_in_process_check(
        factories.fill_weight_check_payload(batch_id, **kwargs),
        headers or PRODUCTION_SUPERVISOR,
    )
    return _data(response, 201)


def record_cci_check(
    api: Any, batch_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Record a container-closure-integrity in-process control."""
    response = api.create_in_process_check(
        factories.cci_check_payload(batch_id, **kwargs),
        headers or PRODUCTION_SUPERVISOR,
    )
    return _data(response, 201)


def record_visual_check(
    api: Any, batch_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Record a visual-inspection in-process control."""
    response = api.create_in_process_check(
        factories.visual_check_payload(batch_id, **kwargs),
        headers or PRODUCTION_SUPERVISOR,
    )
    return _data(response, 201)


def record_em_sample(
    api: Any, suite_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Record an environmental monitoring sample."""
    response = api.create_em_sample(
        factories.em_sample_payload(suite_id, **kwargs),
        headers or MICROBIOLOGY_ANALYST,
    )
    return _data(response, 201)


def investigate_em(
    api: Any, sample_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Open the formal investigation on an excursion."""
    response = api.investigate_em_sample(
        sample_id, factories.investigate_payload(**kwargs), headers or MICROBIOLOGY_ANALYST
    )
    return _data(response, 200)


def close_em_investigation(
    api: Any, sample_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Close an excursion investigation with a root cause."""
    response = api.close_em_investigation(
        sample_id,
        factories.close_investigation_payload(**kwargs),
        headers or MICROBIOLOGY_ANALYST,
    )
    return _data(response, 200)


def read_em_sample(api: Any, sample_id: str, headers: Optional[Headers] = None) -> Json:
    """Read an environmental sample, including its derived risk index."""
    response = api.get_em_sample(
        sample_id, headers or MICROBIOLOGY_ANALYST
    )
    return _data(response, 200)


def raise_deviation(
    api: Any, batch_order_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Raise a deviation against a batch."""
    response = api.create_deviation(
        factories.deviation_payload(batch_order_id, **kwargs), headers or QA_REVIEWER
    )
    return _data(response, 201)


def classify_deviation(
    api: Any, deviation_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Classify a deviation, which scores it."""
    response = api.classify_deviation(
        deviation_id, factories.classify_payload(**kwargs), headers or QA_REVIEWER
    )
    return _data(response, 200)


def submit_capa(
    api: Any, deviation_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Submit the corrective action for a deviation."""
    response = api.submit_capa(
        deviation_id, factories.submit_capa_payload(**kwargs), headers or QA_REVIEWER
    )
    return _data(response, 200)


def decide_capa(
    api: Any, deviation_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Decide a submitted corrective action, under segregation of duties."""
    response = api.decide_capa(
        deviation_id,
        factories.decide_capa_payload(**kwargs),
        headers or QA_REVIEWER_SECOND,
    )
    return _data(response, 200)


def read_deviation(api: Any, deviation_id: str, headers: Optional[Headers] = None) -> Json:
    """Read a deviation, including its risk score."""
    response = api.get_deviation(deviation_id, headers or QA_REVIEWER)
    return _data(response, 200)


def open_review(
    api: Any, batch_order_id: str, headers: Optional[Headers] = None
) -> Json:
    """Open the batch record review, advancing the quality axis."""
    response = api.create_batch_record_review(
        factories.batch_record_review_payload(batch_order_id), headers or QA_REVIEWER
    )
    return _data(response, 201)


def record_findings(
    api: Any,
    review_id: str,
    open_findings_count: int,
    headers: Optional[Headers] = None,
    **kwargs: Any,
) -> Json:
    """Overwrite the review's outstanding finding count."""
    response = api.record_findings(
        review_id,
        factories.record_findings_payload(open_findings_count, **kwargs),
        headers or QA_REVIEWER,
    )
    return _data(response, 200)


def close_review(api: Any, review_id: str, headers: Optional[Headers] = None) -> Json:
    """Close a clean review, which stamps the final releasable figure."""
    response = api.close_batch_record_review(
        review_id, headers or QA_REVIEWER
    )
    return _data(response, 200)


def read_review(api: Any, review_id: str, headers: Optional[Headers] = None) -> Json:
    """Read a batch record review."""
    response = api.get_batch_record_review(review_id, headers or QA_REVIEWER)
    return _data(response, 200)


def qp_release(
    api: Any, batch_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Sign the Qualified-Person disposition, appending a decision record."""
    response = api.qp_release(
        batch_id, factories.qp_release_payload(**kwargs), headers or QUALIFIED_PERSON
    )
    return _data(response, 201)


def request_audit(
    api: Any, client_project_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Raise an audit engagement against a project."""
    response = api.create_audit_engagement(
        factories.audit_engagement_payload(client_project_id, **kwargs),
        headers or PROGRAM_MANAGER,
    )
    return _data(response, 201)


def host_audit(
    api: Any, engagement_id: str, headers: Optional[Headers] = None, **kwargs: Any
) -> Json:
    """Resolve an audit engagement as hosted or deferred."""
    response = api.host_audit_engagement(
        engagement_id, factories.host_audit_payload(**kwargs), headers or PROGRAM_MANAGER
    )
    return _data(response, 200)


# ---------------------------------------------------------------------------
# Tier 2: the suite qualification ladder (PRD 3.2, 3.3)
# ---------------------------------------------------------------------------
LOT_CODES: Dict[str, str] = {
    "VIAL": "VL-1",
    "STOPPER": "ST-1",
    "SYRINGE": "SY-1",
    "PLUNGER": "PL-1",
}


def qualify_suite(
    api: Any,
    suite_id: str,
    operators: Sequence[str] = ("OP-A", "OP-B"),
    units_filled: int = 6000,
    contaminated_units: int = 0,
    scheduled_run_date: str = "2026-09-02T08:00:00Z",
    expires_on: str = "2027-06-01T00:00:00Z",
    qualification_type: str = "ASEPTIC_INTERVENTION",
    qualify_operators: bool = True,
) -> Tuple[Json, List[Json]]:
    """Run a simulation, read it out, and grant the participants' records.

    Returns the simulation and one qualification record per named operator, in
    the order the operators were named.
    """
    media_fill = create_media_fill(
        api, suite_id, scheduled_run_date=scheduled_run_date
    )
    execute_media_fill(
        api,
        media_fill["id"],
        units_filled=units_filled,
        participating_operator_names=list(operators),
    )
    media_fill = read_media_fill_out(api, media_fill["id"], contaminated_units)

    qualifications: List[Json] = []
    for operator_name in operators:
        record = create_qualification(
            api,
            operator_name,
            suite_id,
            qualification_type=qualification_type,
            expires_on=expires_on,
            media_fill_id=media_fill["id"],
        )
        if qualify_operators:
            record = qualify(api, record["id"])
        qualifications.append(record)
    return media_fill, qualifications


def build_qualified_suite(
    api: Any,
    clock: Optional[str] = SCENARIO_CLOCK,
    suite_code: str = "FS-1",
    grade: str = "B",
    changeover_minutes_same_product: int = 60,
    changeover_minutes_product_change: int = 240,
    max_committed_minutes: int = 20000,
    operators: Sequence[str] = ("OP-A", "OP-B"),
    media_fill_units: int = 6000,
    contaminated_units: int = 0,
    media_fill_scheduled: str = "2026-09-02T08:00:00Z",
    qualification_expires_on: str = "2027-06-01T00:00:00Z",
    cleaning_molecule: Optional[str] = "MOL-A",
    residue_ug_per_swab: int = 12,
) -> Json:
    """A suite carried all the way to a working posture.

    With the defaults the suite ends aseptically qualified, cleaned down from
    `MOL-A` and carrying two effective operators, which is exactly the input set
    PRD 2.5 needs before a posture of `OPEN` is possible.
    """
    if clock is not None:
        set_clock(api, clock)
    suite = create_suite(
        api,
        suite_code=suite_code,
        grade=grade,
        changeover_minutes_same_product=changeover_minutes_same_product,
        changeover_minutes_product_change=changeover_minutes_product_change,
        max_committed_minutes=max_committed_minutes,
    )
    media_fill, qualifications = qualify_suite(
        api,
        suite["id"],
        operators=operators,
        units_filled=media_fill_units,
        contaminated_units=contaminated_units,
        scheduled_run_date=media_fill_scheduled,
        expires_on=qualification_expires_on,
    )
    if cleaning_molecule is not None:
        record_cleaning_validation(
            api,
            suite["id"],
            molecule_name=cleaning_molecule,
            residue_ug_per_swab=residue_ug_per_swab,
        )
    return {
        "suite": read_suite(api, suite["id"]),
        "suite_id": suite["id"],
        "media_fill": media_fill,
        "media_fill_id": media_fill["id"],
        "qualifications": qualifications,
        "qualification_ids": [record["id"] for record in qualifications],
    }


# ---------------------------------------------------------------------------
# Tier 3: the whole manufacturing chain (PRD 3.1 - 3.8)
# ---------------------------------------------------------------------------
STAGE_SUITE = "SUITE"
STAGE_PROJECT = "PROJECT"
STAGE_LOTS = "LOTS"
STAGE_SCHEDULED = "SCHEDULED"
STAGE_RESERVED = "RESERVED"
STAGE_SETUP = "SETUP"
STAGE_FILLING = "FILLING"
STAGE_FILLED = "FILLED"
STAGE_BR_REVIEW = "BR_REVIEW"
STAGE_QP_REVIEW = "QP_REVIEW"
STAGE_RELEASED = "RELEASED"

STAGE_ORDER: Tuple[str, ...] = (
    STAGE_SUITE,
    STAGE_PROJECT,
    STAGE_LOTS,
    STAGE_SCHEDULED,
    STAGE_RESERVED,
    STAGE_SETUP,
    STAGE_FILLING,
    STAGE_FILLED,
    STAGE_BR_REVIEW,
    STAGE_QP_REVIEW,
    STAGE_RELEASED,
)


def _reached(stage: str, target: str) -> bool:
    return STAGE_ORDER.index(stage) <= STAGE_ORDER.index(target)


def line_demands(dosage_form: str, target_fill_units: int) -> List[Tuple[str, int]]:
    """Per-line component demand for a dosage form, in PRD 3.5 line order."""
    return [
        (component_type, expected_line_demand(target_fill_units, overage, pack_size))
        for component_type, overage, pack_size in COMPONENT_LINES[dosage_form]
    ]


def build_program(
    api: Any,
    stage: str = STAGE_RELEASED,
    clock: Optional[str] = SCENARIO_CLOCK,
    suite_code: str = "FS-1",
    grade: str = "B",
    changeover_minutes_same_product: int = 60,
    changeover_minutes_product_change: int = 240,
    max_committed_minutes: int = 20000,
    operators: Sequence[str] = ("OP-A", "OP-B"),
    media_fill_units: int = 6000,
    contaminated_units: int = 0,
    media_fill_scheduled: str = "2026-09-02T08:00:00Z",
    qualification_expires_on: str = "2027-06-01T00:00:00Z",
    cleaning_molecule: Optional[str] = None,
    residue_ug_per_swab: int = 12,
    client_name: str = "Sponsor A",
    molecule_name: str = "MOL-A",
    dosage_form: str = "VIAL",
    target_fill_weight_mg: int = 1000,
    historical_reject_rate_ppm: int = 2500,
    reserved_unit_budget: int = 30000,
    lot_quantity_received: int = 30000,
    lot_quantities: Optional[Dict[str, int]] = None,
    lot_expiry: str = "2027-01-01T00:00:00Z",
    batch_number: str = "B-001",
    planned_start: str = "2026-09-10T08:00:00Z",
    planned_end: str = "2026-09-10T16:00:00Z",
    target_fill_units: int = 10000,
    reservation_quantities: Optional[Dict[str, int]] = None,
    fill_weights: Optional[List[float]] = None,
    fill_weight_sample_size: int = 40,
    fill_weight_destructive_units: int = 40,
    cci_sample_size: int = 20,
    cci_reject_unit_count: int = 0,
    cci_destructive_units: int = 20,
    visual_sample_size: Optional[int] = None,
    visual_reject_count: int = 166,
    filled_unit_count: int = 8500,
    qp_decision: str = "RELEASE",
    existing_suite_id: Optional[str] = None,
    existing_project_id: Optional[str] = None,
) -> Json:
    """Walk the manufacturing chain and stop at `stage`.

    Every stage is reached only through the endpoints PRD section 4 publishes,
    in the order the state machines of PRD 3.1 to 3.8 permit: a suite is
    qualified before a project is intaken against it, a project is activated
    before its batches are scheduled, lots are released before they are
    reserved, and the two status axes of a batch are advanced one legal
    transition at a time.

    With the defaults, `stage=STAGE_QP_REVIEW` reproduces the worked example of
    PRD 3.8 exactly: a 10000-container VIAL batch that filled 8500 units with 60
    destructively sampled units and 166 visual rejects.
    """
    assert stage in STAGE_ORDER, f"unknown stage {stage!r}"
    program: Json = {"stage": stage, "dosage_form": dosage_form}

    if existing_suite_id is None:
        suite_bundle = build_qualified_suite(
            api,
            clock=clock,
            suite_code=suite_code,
            grade=grade,
            changeover_minutes_same_product=changeover_minutes_same_product,
            changeover_minutes_product_change=changeover_minutes_product_change,
            max_committed_minutes=max_committed_minutes,
            operators=operators,
            media_fill_units=media_fill_units,
            contaminated_units=contaminated_units,
            media_fill_scheduled=media_fill_scheduled,
            qualification_expires_on=qualification_expires_on,
            cleaning_molecule=(
                molecule_name if cleaning_molecule is None else cleaning_molecule
            ),
            residue_ug_per_swab=residue_ug_per_swab,
        )
        program.update(suite_bundle)
    else:
        program["suite_id"] = existing_suite_id
        program["suite"] = read_suite(api, existing_suite_id)
        program["qualifications"] = []
        program["qualification_ids"] = []
    if not _reached(STAGE_PROJECT, stage):
        return program

    if existing_project_id is None:
        project = create_project(
            api,
            program["suite_id"],
            client_name=client_name,
            molecule_name=molecule_name,
            dosage_form=dosage_form,
            target_fill_weight_mg=target_fill_weight_mg,
            historical_reject_rate_ppm=historical_reject_rate_ppm,
            reserved_unit_budget=reserved_unit_budget,
        )
        activate_project(api, project["id"])
    else:
        project = read_project(api, existing_project_id)
    program["project_id"] = project["id"]
    program["project"] = read_project(api, project["id"])
    if not _reached(STAGE_LOTS, stage):
        return program

    quantities = dict(lot_quantities or {})
    lots: Dict[str, Json] = {}
    for component_type, _demand in line_demands(dosage_form, target_fill_units):
        lot = release_lot(
            api,
            project["id"],
            component_type=component_type,
            lot_code=LOT_CODES[component_type],
            quantity_received=quantities.get(component_type, lot_quantity_received),
            sterilization_expiry=lot_expiry,
        )
        lots[component_type] = lot
    program["lots"] = lots
    program["lot_ids"] = {key: value["id"] for key, value in lots.items()}
    if not _reached(STAGE_SCHEDULED, stage):
        return program

    lead_qualification_id = (
        program["qualification_ids"][0] if program["qualification_ids"] else None
    )
    batch = create_batch(
        api,
        project["id"],
        program["suite_id"],
        lead_qualification_id,
        batch_number=batch_number,
        planned_start=planned_start,
        planned_end=planned_end,
        target_fill_units=target_fill_units,
    )
    program["batch"] = batch
    program["batch_id"] = batch["id"]
    program["lead_operator_qualification_id"] = lead_qualification_id
    if not _reached(STAGE_RESERVED, stage):
        return program

    reservation_overrides = dict(reservation_quantities or {})
    reservations: List[Json] = []
    for component_type, demand in line_demands(dosage_form, target_fill_units):
        reservations.append(
            reserve(
                api,
                batch["id"],
                lots[component_type]["id"],
                reservation_overrides.get(component_type, demand),
            )
        )
    program["reservations"] = reservations
    program["reservation_ids"] = [row["id"] for row in reservations]
    if not _reached(STAGE_SETUP, stage):
        return program

    setup_batch(api, batch["id"])
    if not _reached(STAGE_FILLING, stage):
        program["batch"] = read_batch(api, batch["id"])
        return program

    start_fill(api, batch["id"])
    if not _reached(STAGE_FILLED, stage):
        program["batch"] = read_batch(api, batch["id"])
        return program

    checks: List[Json] = []
    checks.append(
        record_fill_weight_check(
            api,
            batch["id"],
            measured_fill_weights_mg=(
                list(fill_weights)
                if fill_weights is not None
                else [
                    target_fill_weight_mg,
                    target_fill_weight_mg * 1.02,
                    target_fill_weight_mg * 0.985,
                    target_fill_weight_mg * 1.028,
                    target_fill_weight_mg * 1.012,
                ]
            ),
            sample_size=fill_weight_sample_size,
            destructive_sample_units=fill_weight_destructive_units,
        )
    )
    checks.append(
        record_cci_check(
            api,
            batch["id"],
            sample_size=cci_sample_size,
            reject_unit_count=cci_reject_unit_count,
            destructive_sample_units=cci_destructive_units,
        )
    )
    checks.append(
        record_visual_check(
            api,
            batch["id"],
            sample_size=(
                filled_unit_count if visual_sample_size is None else visual_sample_size
            ),
            reject_unit_count=visual_reject_count,
            destructive_sample_units=0,
        )
    )
    program["checks"] = checks
    program["check_ids"] = [row["id"] for row in checks]
    complete_fill(api, batch["id"], filled_unit_count)
    program["batch"] = read_batch(api, batch["id"])
    if not _reached(STAGE_BR_REVIEW, stage):
        return program

    review = open_review(api, batch["id"])
    program["review"] = review
    program["review_id"] = review["id"]
    program["batch"] = read_batch(api, batch["id"])
    if not _reached(STAGE_QP_REVIEW, stage):
        return program

    program["review"] = close_review(api, review["id"])
    program["batch"] = read_batch(api, batch["id"])
    if not _reached(STAGE_RELEASED, stage):
        return program

    program["decision"] = qp_release(api, batch["id"], decision=qp_decision)
    program["batch"] = read_batch(api, batch["id"])
    return program

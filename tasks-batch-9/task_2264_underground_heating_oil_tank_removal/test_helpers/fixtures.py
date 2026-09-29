"""Composite setup builders.

The harness restarts the service with an empty database before every single test,
so nothing here may assume a previously seeded row.  Each builder drives the real
endpoints in the order the PRD requires and returns the rows it created, so a
test can start from whatever depth of the workflow it needs.  They are plain
functions rather than pytest fixtures precisely because most tests need to call
them more than once with different arguments.

The five tiers are: clock and single-row creators; parent-child pairs; whole
lifecycle shortcuts that land a project in a named state; accumulation helpers
that drive a project toward a threshold; and finalisation helpers that close a
project out or walk a closure backwards.
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_STARTUP_INSTANT
from .factories import (
    billing_event_payload,
    change_order_decision_payload,
    change_order_payload,
    claim_decision_payload,
    crew_payload,
    custody_event_payload,
    disclosure_payload,
    disclosure_response_payload,
    field_complete_payload,
    field_event_payload,
    insurance_notification_payload,
    laboratory_payload,
    nfa_letter_payload,
    permit_decision_payload,
    permit_payload,
    property_payload,
    rescind_payload,
    result_payload,
    retract_result_payload,
    soil_sample_payload,
    sweep_survey_payload,
    tank_project_payload,
    trust_fund_claim_payload,
    work_order_payload,
)
from .test_users import (
    COMPLIANCE_OFFICER,
    FIELD_TECHNICIAN,
    LSP_DRAFTER,
    LSP_SIGNER,
    PROJECT_COORDINATOR,
    make_homeowner_headers,
    make_lab_analyst_headers,
)

# --------------------------------------------------------------------------- #
# Standing instants the builders default to
# --------------------------------------------------------------------------- #
#: The instant the builders position the clock at before intake.
DEFAULT_INTAKE_INSTANT = "2026-08-03T08:00:00Z"
#: The booked window for the canonical work order.
DEFAULT_WORK_START = "2026-08-06T13:00:00Z"
DEFAULT_WORK_END = "2026-08-06T21:00:00Z"
#: The instant the crew arrives on site, inside the booked window.
DEFAULT_FIELD_INSTANT = "2026-08-06T13:00:00Z"

#: Result payloads whose classification is pinned by the action and gross levels.
CLEAN_RESULT = {"tph_mg_kg": 120.0, "benzene_mg_kg": 0.05}
ELEVATED_RESULT = {"tph_mg_kg": 900.0, "benzene_mg_kg": 0.2}
GROSS_RESULT = {"tph_mg_kg": 6200.0, "benzene_mg_kg": 1.2}


# =========================================================================== #
# Tier 1 — the logical clock and one builder per row
# =========================================================================== #
def set_clock(to_iso8601: str, headers=COMPLIANCE_OFFICER) -> dict:
    """Reposition the logical clock and return the reported ``current_utc``."""
    return get_success_data(api_client.set_current_utc(to_iso8601, headers))


def reset_clock(headers=COMPLIANCE_OFFICER) -> dict:
    """Return the clock to the instant it reads at server startup."""
    return set_clock(CLOCK_STARTUP_INSTANT, headers)


def create_property(**overrides) -> dict:
    return get_success_data(
        api_client.create_property(property_payload(**overrides), PROJECT_COORDINATOR)
    )


def read_property(property_id: str, headers=PROJECT_COORDINATOR) -> dict:
    return get_success_data(api_client.get_property(property_id, headers))


def create_project(property_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_tank_project(
            tank_project_payload(property_id, **overrides), PROJECT_COORDINATOR
        )
    )


def read_project(project_id: str, headers=PROJECT_COORDINATOR) -> dict:
    return get_success_data(api_client.get_tank_project(project_id, headers))


def read_summary(project_id: str, headers=PROJECT_COORDINATOR) -> dict:
    return get_success_data(api_client.get_tank_project_summary(project_id, headers))


def project_version(project_id: str, headers=PROJECT_COORDINATOR) -> int:
    """The project's current ``version``, for echoing back on an authoring call."""
    return read_project(project_id, headers)["version"]


def record_sweep_survey(project_id: str, headers=FIELD_TECHNICIAN, **overrides) -> dict:
    return get_success_data(
        api_client.record_sweep_survey(
            project_id, sweep_survey_payload(**overrides), headers
        )
    )


def create_disclosure(project_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_disclosure(
            disclosure_payload(project_id, **overrides), PROJECT_COORDINATOR
        )
    )


def respond_to_disclosure(disclosure_id: str, property_id: str, **overrides) -> dict:
    """Respond as the owning homeowner, whose identity is the property's own id."""
    return get_success_data(
        api_client.respond_to_disclosure(
            disclosure_id,
            disclosure_response_payload(**overrides),
            make_homeowner_headers(property_id),
        )
    )


def read_disclosure(disclosure_id: str, headers=PROJECT_COORDINATOR) -> dict:
    return get_success_data(api_client.get_disclosure(disclosure_id, headers))


def create_permit(project_id: str, permit_type: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_permit(
            permit_payload(project_id, permit_type=permit_type, **overrides),
            PROJECT_COORDINATOR,
        )
    )


def decide_permit(permit_id: str, decision: str, **overrides) -> dict:
    return get_success_data(
        api_client.decide_permit(
            permit_id,
            permit_decision_payload(decision, **overrides),
            COMPLIANCE_OFFICER,
        )
    )


def read_permit(permit_id: str, headers=PROJECT_COORDINATOR) -> dict:
    return get_success_data(api_client.get_permit(permit_id, headers))


def create_crew(**overrides) -> dict:
    return get_success_data(
        api_client.create_crew(crew_payload(**overrides), PROJECT_COORDINATOR)
    )


def create_work_order(project_id: str, crew_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_work_order(
            work_order_payload(project_id, crew_id, **overrides), PROJECT_COORDINATOR
        )
    )


def read_work_order(work_order_id: str, headers=PROJECT_COORDINATOR) -> dict:
    return get_success_data(api_client.get_work_order(work_order_id, headers))


def field_event(work_order_id: str, event: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_field_event(
            work_order_id, field_event_payload(event, **overrides), FIELD_TECHNICIAN
        )
    )


def complete_field_work(
    work_order_id: str,
    actual_excavated_cubic_yards: float = 9.5,
    hauled_tons: float = 12.4,
) -> dict:
    return get_success_data(
        api_client.create_field_event(
            work_order_id,
            field_complete_payload(actual_excavated_cubic_yards, hauled_tons),
            FIELD_TECHNICIAN,
        )
    )


def billing_event(work_order_id: str, event: str) -> dict:
    return get_success_data(
        api_client.create_billing_event(
            work_order_id, billing_event_payload(event), PROJECT_COORDINATOR
        )
    )


def create_laboratory(**overrides) -> dict:
    return get_success_data(
        api_client.create_laboratory(laboratory_payload(**overrides), COMPLIANCE_OFFICER)
    )


def read_laboratory(laboratory_id: str, headers=COMPLIANCE_OFFICER) -> dict:
    return get_success_data(api_client.get_laboratory(laboratory_id, headers))


def create_sample(
    project_id: str, work_order_id: str, laboratory_id: str, **overrides
) -> dict:
    return get_success_data(
        api_client.create_soil_sample(
            soil_sample_payload(project_id, work_order_id, laboratory_id, **overrides),
            FIELD_TECHNICIAN,
        )
    )


def read_sample(sample_id: str, headers=FIELD_TECHNICIAN) -> dict:
    return get_success_data(api_client.get_soil_sample(sample_id, headers))


def dispatch_sample(sample_id: str) -> dict:
    """DISPATCH is a technician act."""
    return get_success_data(
        api_client.create_custody_event(
            sample_id, custody_event_payload("DISPATCH"), FIELD_TECHNICIAN
        )
    )


def void_sample(sample_id: str) -> dict:
    """VOID is a technician act."""
    return get_success_data(
        api_client.create_custody_event(
            sample_id, custody_event_payload("VOID"), FIELD_TECHNICIAN
        )
    )


def receive_sample(sample_id: str, laboratory_id: str) -> dict:
    """RECEIVE is permitted only to the lab named as the sample's laboratory_id."""
    return get_success_data(
        api_client.create_custody_event(
            sample_id,
            custody_event_payload("RECEIVE"),
            make_lab_analyst_headers(laboratory_id),
        )
    )


def report_result(
    sample_id: str,
    laboratory_id: str,
    tph_mg_kg: float = 120.0,
    benzene_mg_kg: float = 0.05,
) -> dict:
    """The owning laboratory posts the analysis."""
    return get_success_data(
        api_client.report_result(
            sample_id,
            result_payload(tph_mg_kg, benzene_mg_kg),
            make_lab_analyst_headers(laboratory_id),
        )
    )


def retract_result(sample_id: str, laboratory_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.retract_result(
            sample_id,
            retract_result_payload(**overrides),
            make_lab_analyst_headers(laboratory_id),
        )
    )


def create_change_order(
    project_id: str, expected_project_version: Optional[int] = None, **overrides
) -> dict:
    """Draft a change order, reading the project's current version if not supplied."""
    if expected_project_version is None:
        expected_project_version = project_version(project_id)
    return get_success_data(
        api_client.create_change_order(
            change_order_payload(project_id, expected_project_version, **overrides),
            LSP_DRAFTER,
        )
    )


def submit_change_order(change_order_id: str, headers=LSP_DRAFTER) -> dict:
    """Submission is the author's own act."""
    return get_success_data(api_client.submit_change_order(change_order_id, headers))


def decide_change_order(change_order_id: str, decision: str, **overrides) -> dict:
    return get_success_data(
        api_client.decide_change_order(
            change_order_id,
            change_order_decision_payload(decision, **overrides),
            COMPLIANCE_OFFICER,
        )
    )


def read_change_order(change_order_id: str, headers=COMPLIANCE_OFFICER) -> dict:
    return get_success_data(api_client.get_change_order(change_order_id, headers))


def create_claim(
    project_id: str, expected_project_version: Optional[int] = None, **overrides
) -> dict:
    if expected_project_version is None:
        expected_project_version = project_version(project_id)
    return get_success_data(
        api_client.create_trust_fund_claim(
            trust_fund_claim_payload(project_id, expected_project_version, **overrides),
            COMPLIANCE_OFFICER,
        )
    )


def submit_claim(claim_id: str) -> dict:
    return get_success_data(
        api_client.submit_trust_fund_claim(claim_id, COMPLIANCE_OFFICER)
    )


def decide_claim(claim_id: str, decision: str, **overrides) -> dict:
    return get_success_data(
        api_client.decide_trust_fund_claim(
            claim_id, claim_decision_payload(decision, **overrides), COMPLIANCE_OFFICER
        )
    )


def read_claim(claim_id: str, headers=COMPLIANCE_OFFICER) -> dict:
    return get_success_data(api_client.get_trust_fund_claim(claim_id, headers))


def draft_nfa_letter(project_id: str, headers=LSP_DRAFTER, **overrides) -> dict:
    return get_success_data(
        api_client.create_nfa_letter(nfa_letter_payload(project_id, **overrides), headers)
    )


def issue_nfa_letter(letter_id: str, headers=LSP_SIGNER) -> dict:
    """Issuance is a second licensed site professional's act."""
    return get_success_data(api_client.issue_nfa_letter(letter_id, headers))


def rescind_nfa_letter(letter_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.rescind_nfa_letter(
            letter_id, rescind_payload(**overrides), COMPLIANCE_OFFICER
        )
    )


def read_nfa_letter(letter_id: str, headers=LSP_DRAFTER) -> dict:
    return get_success_data(api_client.get_nfa_letter(letter_id, headers))


def create_notification(
    project_id: str, notification_kind: str = "FIRST_PARTY", **overrides
) -> dict:
    return get_success_data(
        api_client.create_insurance_notification(
            insurance_notification_payload(
                project_id, notification_kind, **overrides
            ),
            COMPLIANCE_OFFICER,
        )
    )


def read_notification(notification_id: str, headers=COMPLIANCE_OFFICER) -> dict:
    return get_success_data(
        api_client.get_insurance_notification(notification_id, headers)
    )


# =========================================================================== #
# Tier 2 — parent and child together
# =========================================================================== #
def property_with_project(
    property_overrides=None, project_overrides=None, clock: Optional[str] = None
):
    """A registered site plus one project opened on it.

    Positions the clock first when an instant is supplied, so every stamped
    timestamp on both rows is predictable.
    """
    if clock is not None:
        set_clock(clock)
    prop = create_property(**(property_overrides or {}))
    project = create_project(prop["id"], **(project_overrides or {}))
    return prop, project


def project_at_intake(
    property_overrides=None, project_overrides=None, clock: str = DEFAULT_INTAKE_INSTANT
) -> dict:
    """A fresh project, still in INTAKE with nothing surveyed."""
    prop, project = property_with_project(
        property_overrides, project_overrides, clock=clock
    )
    return {"property": prop, "project": project}


def project_at_surveyed(
    property_overrides=None,
    project_overrides=None,
    survey_overrides=None,
    clock: str = DEFAULT_INTAKE_INSTANT,
) -> dict:
    """A project whose sweep survey has been recorded, so it sits in SURVEYED."""
    ctx = project_at_intake(property_overrides, project_overrides, clock=clock)
    ctx["project"] = record_sweep_survey(
        ctx["project"]["id"], **(survey_overrides or {})
    )
    return ctx


def project_at_disclosed(
    property_overrides=None,
    project_overrides=None,
    survey_overrides=None,
    clock: str = DEFAULT_INTAKE_INSTANT,
) -> dict:
    """A surveyed project whose sweep-findings notice has been acknowledged."""
    ctx = project_at_surveyed(
        property_overrides, project_overrides, survey_overrides, clock=clock
    )
    ctx["sweep_disclosure"] = create_disclosure(
        ctx["project"]["id"], disclosure_kind="SWEEP_FINDINGS"
    )
    ctx["sweep_disclosure"] = respond_to_disclosure(
        ctx["sweep_disclosure"]["id"],
        ctx["property"]["id"],
        response="ACKNOWLEDGED",
        response_channel="PORTAL",
    )
    ctx["project"] = read_project(ctx["project"]["id"])
    return ctx


def project_at_permitted(
    property_overrides=None,
    project_overrides=None,
    survey_overrides=None,
    clock: str = DEFAULT_INTAKE_INSTANT,
    issue_fire_marshal: bool = True,
) -> dict:
    """A disclosed project holding both authorisations in ISSUED.

    The municipal permit is what advances the project to PERMITTED; the
    fire-marshal notification advances no project state but is what a later
    mobilization needs.
    """
    ctx = project_at_disclosed(
        property_overrides, project_overrides, survey_overrides, clock=clock
    )
    ctx["municipal_permit"] = create_permit(
        ctx["project"]["id"], "MUNICIPAL_DECOMMISSION"
    )
    ctx["municipal_permit"] = decide_permit(ctx["municipal_permit"]["id"], "ISSUED")
    ctx["fire_permit"] = create_permit(
        ctx["project"]["id"], "FIRE_MARSHAL_NOTIFICATION"
    )
    if issue_fire_marshal:
        ctx["fire_permit"] = decide_permit(ctx["fire_permit"]["id"], "ISSUED")
    ctx["project"] = read_project(ctx["project"]["id"])
    return ctx


def project_with_booked_work_order(
    property_overrides=None,
    project_overrides=None,
    survey_overrides=None,
    crew_overrides=None,
    work_order_overrides=None,
    clock: str = DEFAULT_INTAKE_INSTANT,
) -> dict:
    """A permitted project with a crew registered and the field work booked."""
    ctx = project_at_permitted(
        property_overrides, project_overrides, survey_overrides, clock=clock
    )
    ctx["crew"] = create_crew(**(crew_overrides or {}))
    ctx["work_order"] = create_work_order(
        ctx["project"]["id"], ctx["crew"]["id"], **(work_order_overrides or {})
    )
    return ctx


# =========================================================================== #
# Tier 3 — whole-lifecycle shortcuts
# =========================================================================== #
def project_at_sampling(
    property_overrides=None,
    project_overrides=None,
    survey_overrides=None,
    crew_overrides=None,
    work_order_overrides=None,
    laboratory_overrides=None,
    clock: str = DEFAULT_INTAKE_INSTANT,
    field_instant: str = DEFAULT_FIELD_INSTANT,
    actual_excavated_cubic_yards: float = 9.5,
    hauled_tons: float = 12.4,
) -> dict:
    """Field work driven to completion, so the project stands in SAMPLING.

    Completion is what opens confirmation sampling: it moves the billing dimension
    from UNBILLED to BILLABLE, takes ``sampling_round`` from 0 to 1 and advances
    the project out of DECOMMISSIONING.  A laboratory is registered as well, since
    every sample must name one.
    """
    ctx = project_with_booked_work_order(
        property_overrides,
        project_overrides,
        survey_overrides,
        crew_overrides,
        work_order_overrides,
        clock=clock,
    )
    set_clock(field_instant)
    field_event(ctx["work_order"]["id"], "MOBILIZE")
    field_event(ctx["work_order"]["id"], "START")
    ctx["work_order"] = complete_field_work(
        ctx["work_order"]["id"], actual_excavated_cubic_yards, hauled_tons
    )
    ctx["laboratory"] = create_laboratory(**(laboratory_overrides or {}))
    ctx["project"] = read_project(ctx["project"]["id"])
    return ctx


def collect_sample_at_lab(
    ctx: dict, sample_point: str = "TANK_BOTTOM", depth_inches: int = 96, **overrides
) -> dict:
    """Log an aliquot, dispatch it and have the owning laboratory receive it."""
    sample = create_sample(
        ctx["project"]["id"],
        ctx["work_order"]["id"],
        ctx["laboratory"]["id"],
        sample_point=sample_point,
        depth_inches=depth_inches,
        **overrides,
    )
    dispatch_sample(sample["id"])
    return receive_sample(sample["id"], ctx["laboratory"]["id"])


def collect_sample_with_result(
    ctx: dict,
    tph_mg_kg: float,
    benzene_mg_kg: float,
    sample_point: str = "TANK_BOTTOM",
    depth_inches: int = 96,
    **overrides,
) -> dict:
    """Take one aliquot all the way to a posted result."""
    sample = collect_sample_at_lab(ctx, sample_point, depth_inches, **overrides)
    return report_result(
        sample["id"], ctx["laboratory"]["id"], tph_mg_kg, benzene_mg_kg
    )


def project_cleared(
    property_overrides=None,
    project_overrides=None,
    laboratory_overrides=None,
    clock: str = DEFAULT_INTAKE_INSTANT,
    field_instant: str = DEFAULT_FIELD_INSTANT,
    sample_point: str = "CONFIRMATION_FLOOR",
    depth_inches: int = 84,
    **sampling_kwargs,
) -> dict:
    """A project whose only confirmation result classifies CLEAN, so it is CLEARED.

    Both figures sit below their action levels, so the round closes, the project
    passes through ASSESSED and lands in CLEARED with nothing else changed.
    """
    ctx = project_at_sampling(
        property_overrides=property_overrides,
        project_overrides=project_overrides,
        laboratory_overrides=laboratory_overrides,
        clock=clock,
        field_instant=field_instant,
        **sampling_kwargs,
    )
    ctx["sample"] = collect_sample_with_result(
        ctx,
        CLEAN_RESULT["tph_mg_kg"],
        CLEAN_RESULT["benzene_mg_kg"],
        sample_point=sample_point,
        depth_inches=depth_inches,
    )
    ctx["project"] = read_project(ctx["project"]["id"])
    return ctx


def project_remediation_active(
    result: Optional[dict] = None,
    property_overrides=None,
    project_overrides=None,
    laboratory_overrides=None,
    clock: str = DEFAULT_INTAKE_INSTANT,
    field_instant: str = DEFAULT_FIELD_INSTANT,
    sample_point: str = "TANK_BOTTOM",
    depth_inches: int = 96,
    **sampling_kwargs,
) -> dict:
    """A project whose confirmation result exceeds an action level.

    The five-part cascade fires on the way in: both latches are set, a provisional
    grid volume and a remediation cost are written, and the waterfall re-runs over
    the project's non-closed notifications.
    """
    result = result or GROSS_RESULT
    ctx = project_at_sampling(
        property_overrides=property_overrides,
        project_overrides=project_overrides,
        laboratory_overrides=laboratory_overrides,
        clock=clock,
        field_instant=field_instant,
        **sampling_kwargs,
    )
    ctx["sample"] = collect_sample_with_result(
        ctx,
        result["tph_mg_kg"],
        result["benzene_mg_kg"],
        sample_point=sample_point,
        depth_inches=depth_inches,
    )
    ctx["project"] = read_project(ctx["project"]["id"])
    return ctx


def project_remediation_active_elevated(**kwargs) -> dict:
    """The ELEVATED band: above the action levels but not above the gross levels."""
    kwargs.setdefault("sample_point", "CONFIRMATION_FLOOR")
    kwargs.setdefault("depth_inches", 84)
    return project_remediation_active(result=ELEVATED_RESULT, **kwargs)


def project_remediation_active_gross(**kwargs) -> dict:
    """The GROSS band: above the gross levels."""
    return project_remediation_active(result=GROSS_RESULT, **kwargs)


# =========================================================================== #
# Tier 4 — accumulation and threshold targeting
# =========================================================================== #
def approved_change_order(
    ctx: dict,
    additional_cubic_yards: float,
    unit_rate_cents: int,
    disposal_class: str = "NON_HAZARDOUS",
    supersedes_change_order_id: Optional[str] = None,
    expected_project_version: Optional[int] = None,
) -> dict:
    """Draft, submit and approve one change order in a single step."""
    kwargs = {
        "additional_cubic_yards": additional_cubic_yards,
        "unit_rate_cents": unit_rate_cents,
        "disposal_class": disposal_class,
    }
    if supersedes_change_order_id is not None:
        kwargs["supersedes_change_order_id"] = supersedes_change_order_id
    order = create_change_order(
        ctx["project"]["id"], expected_project_version, **kwargs
    )
    submit_change_order(order["id"])
    return decide_change_order(order["id"], "APPROVED")


def submitted_change_order(
    ctx: dict,
    additional_cubic_yards: float,
    unit_rate_cents: int,
    disposal_class: str = "NON_HAZARDOUS",
    supersedes_change_order_id: Optional[str] = None,
    expected_project_version: Optional[int] = None,
) -> dict:
    """Draft and submit one change order, leaving it awaiting a decision."""
    kwargs = {
        "additional_cubic_yards": additional_cubic_yards,
        "unit_rate_cents": unit_rate_cents,
        "disposal_class": disposal_class,
    }
    if supersedes_change_order_id is not None:
        kwargs["supersedes_change_order_id"] = supersedes_change_order_id
    order = create_change_order(
        ctx["project"]["id"], expected_project_version, **kwargs
    )
    return submit_change_order(order["id"])


def acknowledged_contamination_disclosure(ctx: dict) -> dict:
    """Send the contamination notice and have the owning homeowner acknowledge it."""
    notice = create_disclosure(
        ctx["project"]["id"], disclosure_kind="CONTAMINATION_FINDINGS"
    )
    return respond_to_disclosure(
        notice["id"],
        ctx["property"]["id"],
        response="ACKNOWLEDGED",
        response_channel="EMAIL",
    )


def claim_under_review(ctx: dict, claimed_costs_cents: int, **overrides) -> dict:
    """A claim carried from DRAFT through SUBMITTED to UNDER_REVIEW."""
    claim = create_claim(
        ctx["project"]["id"], claimed_costs_cents=claimed_costs_cents, **overrides
    )
    submit_claim(claim["id"])
    return decide_claim(claim["id"], "UNDER_REVIEW")


def approved_claim(ctx: dict, claimed_costs_cents: int, **overrides) -> dict:
    """A claim carried all the way to APPROVED, ready for payment at closure."""
    claim = claim_under_review(ctx, claimed_costs_cents, **overrides)
    return decide_claim(claim["id"], "APPROVED")


def invoiced_work_order(ctx: dict) -> dict:
    """Drive the billing dimension to INVOICED, leaving field progress untouched."""
    return billing_event(ctx["work_order"]["id"], "INVOICE")


# =========================================================================== #
# Tier 5 — closure, settlement and walking a closure backwards
# =========================================================================== #
def project_closed_nfa(
    property_overrides=None,
    project_overrides=None,
    closing_date: str = "2026-09-15T00:00:00Z",
    clock: str = DEFAULT_INTAKE_INSTANT,
    field_instant: str = DEFAULT_FIELD_INSTANT,
    **cleared_kwargs,
) -> dict:
    """A cleared project closed out by a letter one professional drafted and another signed."""
    ctx = project_cleared(
        property_overrides=property_overrides,
        project_overrides=project_overrides,
        clock=clock,
        field_instant=field_instant,
        **cleared_kwargs,
    )
    ctx["nfa_letter"] = draft_nfa_letter(
        ctx["project"]["id"], LSP_DRAFTER, closing_date=closing_date
    )
    ctx["nfa_letter"] = issue_nfa_letter(ctx["nfa_letter"]["id"], LSP_SIGNER)
    ctx["project"] = read_project(ctx["project"]["id"])
    return ctx


def project_cleared_after_remediation(
    property_overrides=None,
    project_overrides=None,
    first_result: Optional[dict] = None,
    clock: str = DEFAULT_INTAKE_INSTANT,
    field_instant: str = DEFAULT_FIELD_INSTANT,
    **sampling_kwargs,
) -> dict:
    """A project that went through remediation and then cleared on a second round.

    The first confirmation round classifies above an action level, which latches
    both project flags and writes a remediation cost.  The contamination notice is
    then acknowledged and a second round returns figures below both action levels,
    so the project reaches CLEARED with the latches still set, the cost still
    standing and an empty blocker list.
    """
    ctx = project_remediation_active(
        result=first_result or GROSS_RESULT,
        property_overrides=property_overrides,
        project_overrides=project_overrides,
        clock=clock,
        field_instant=field_instant,
        **sampling_kwargs,
    )
    ctx["contamination_disclosure"] = acknowledged_contamination_disclosure(ctx)
    ctx["second_sample"] = collect_sample_with_result(
        ctx,
        CLEAN_RESULT["tph_mg_kg"],
        CLEAN_RESULT["benzene_mg_kg"],
        sample_point="CONFIRMATION_FLOOR",
        depth_inches=84,
    )
    ctx["project"] = read_project(ctx["project"]["id"])
    return ctx


def project_closed_after_remediation(
    claimed_costs_cents: int = 900000,
    notification_kinds=("FIRST_PARTY",),
    closing_date: str = "2026-09-15T00:00:00Z",
    **cleared_kwargs,
) -> dict:
    """A remediated project closed out with an approved claim and a carrier file.

    Everything the rescission cascade walks backwards is in place: the project sits
    at CLOSED_NFA behind an issued letter, one claim stands at APPROVED, and the
    named notifications carry the reserve the remediation cost produced.
    """
    ctx = project_cleared_after_remediation(**cleared_kwargs)
    ctx["notifications"] = [
        create_notification(ctx["project"]["id"], kind) for kind in notification_kinds
    ]
    if ctx["notifications"]:
        ctx["notification"] = ctx["notifications"][0]
    ctx["claim"] = approved_claim(ctx, claimed_costs_cents)
    ctx["nfa_letter"] = draft_nfa_letter(
        ctx["project"]["id"], LSP_DRAFTER, closing_date=closing_date
    )
    ctx["nfa_letter"] = issue_nfa_letter(ctx["nfa_letter"]["id"], LSP_SIGNER)
    ctx["project"] = read_project(ctx["project"]["id"])
    return ctx


def project_closed_nfa_with_approved_claim(
    claimed_costs_cents: int = 900000,
    notification_kind: Optional[str] = "FIRST_PARTY",
    **closure_kwargs,
) -> dict:
    """A closed-out project holding one APPROVED claim, and optionally a carrier file.

    The claim is approved while the project is still CLEARED, because approval
    requires only a positive eligible amount, and the letter is then issued.
    """
    ctx = project_cleared(
        **{
            k: v
            for k, v in closure_kwargs.items()
            if k not in ("closing_date",)
        }
    )
    if notification_kind is not None:
        ctx["notification"] = create_notification(
            ctx["project"]["id"], notification_kind
        )
    ctx["claim"] = approved_claim(ctx, claimed_costs_cents)
    ctx["nfa_letter"] = draft_nfa_letter(
        ctx["project"]["id"],
        LSP_DRAFTER,
        closing_date=closure_kwargs.get("closing_date", "2026-09-15T00:00:00Z"),
    )
    ctx["nfa_letter"] = issue_nfa_letter(ctx["nfa_letter"]["id"], LSP_SIGNER)
    ctx["project"] = read_project(ctx["project"]["id"])
    return ctx

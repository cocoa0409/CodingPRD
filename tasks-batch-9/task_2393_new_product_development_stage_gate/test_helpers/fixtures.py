"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints and
uses the lenient success validator, so a broken preamble surfaces as a setup failure
rather than as a confusing assertion error deep inside a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import READINESS_DELIVERABLE_TYPES
from . import factories as f
from .test_users import (
    TEST_USERS,
    make_functional_reviewer_headers,
    make_gate_chair_headers,
    make_innovation_lead_headers,
)

ADMIN = TEST_USERS["portfolio_admin_headers"]
LEAD = TEST_USERS["innovation_lead_headers"]
CHAIR = TEST_USERS["gate_chair_headers"]
REVIEWER = TEST_USERS["functional_reviewer_headers"]
REGULATORY = TEST_USERS["regulatory_approver_headers"]
RND = TEST_USERS["rnd_lead_headers"]
SALES = TEST_USERS["sales_account_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-call wrappers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock every temporal rule is evaluated against."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def register_stage_gate(**overrides) -> dict:
    return get_success_data(
        api_client.create_stage_gate(f.stage_gate_payload(**overrides), ADMIN)
    )


def register_retailer(**overrides) -> dict:
    return get_success_data(api_client.create_retailer(f.retailer_payload(**overrides), ADMIN))


def open_reset_window(retailer_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_shelf_reset_window(
            retailer_id, f.shelf_reset_window_payload(**overrides), ADMIN
        )
    )


def register_pilot_line(**overrides) -> dict:
    return get_success_data(
        api_client.create_pilot_line(f.pilot_line_payload(**overrides), ADMIN)
    )


def intake_project(owner_user_id="lead-owner", **overrides) -> dict:
    """Intake an idea; the acting lead's opaque identifier becomes owner_user_id."""
    headers = make_innovation_lead_headers(owner_user_id)
    return get_success_data(
        api_client.create_project(f.project_payload(**overrides), headers)
    )


def read_project(project_id) -> dict:
    return get_success_data(api_client.get_project(project_id, ADMIN))


def project_version(project_id) -> int:
    return read_project(project_id)["version"]


def read_formulation(formulation_id) -> dict:
    return get_success_data(api_client.get_formulation(formulation_id, ADMIN))


def formulation_version(formulation_id) -> int:
    return read_formulation(formulation_id)["version"]


def screen_project(project_id, chair_user_id="chair-screen", **payload) -> dict:
    return get_success_data(
        api_client.screen_project(project_id, payload, make_gate_chair_headers(chair_user_id))
    )


def record_concept_test(project_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_concept_test(project_id, f.concept_test_payload(**overrides), LEAD)
    )


def open_business_case(project_id, expected_project_version=None, **overrides) -> dict:
    """Open a business case, declaring the last observed project version."""
    if expected_project_version is None:
        expected_project_version = project_version(project_id)
    return get_success_data(
        api_client.create_business_case(
            project_id, f.business_case_payload(expected_project_version, **overrides), LEAD
        )
    )


def add_forecast_line(business_case_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_forecast_line(
            business_case_id, f.forecast_line_payload(**overrides), LEAD
        )
    )


def open_case_with_line(project_id, case_overrides=None, line_overrides=None):
    """Open a case and add one channel line, taking it DRAFT -> COMPUTED."""
    case = open_business_case(project_id, **(case_overrides or {}))
    line = add_forecast_line(case["id"], **(line_overrides or {}))
    return case, line


def create_formulation(project_id, expected_project_version=None, **overrides) -> dict:
    if expected_project_version is None:
        expected_project_version = project_version(project_id)
    return get_success_data(
        api_client.create_formulation(
            project_id, f.formulation_payload(expected_project_version, **overrides), RND
        )
    )


def book_pilot_run(formulation_id, pilot_line_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_pilot_run(
            formulation_id, f.pilot_run_payload(pilot_line_id, **overrides), RND
        )
    )


def start_pilot_run(pilot_run_id) -> dict:
    return get_success_data(api_client.start_pilot_run(pilot_run_id, {}, RND))


def complete_pilot_run(pilot_run_id, actual_units) -> dict:
    return get_success_data(
        api_client.complete_pilot_run(pilot_run_id, {"actual_units": actual_units}, RND)
    )


def cancel_pilot_run(pilot_run_id, reason="Line released for a customer trial") -> dict:
    return get_success_data(api_client.cancel_pilot_run(pilot_run_id, {"reason": reason}, RND))


def open_shelf_life_study(formulation_id, expected_formulation_version=None, **overrides):
    """Open a stability study, declaring the last observed formulation version."""
    if expected_formulation_version is None:
        expected_formulation_version = formulation_version(formulation_id)
    return get_success_data(
        api_client.create_shelf_life_study(
            formulation_id,
            f.shelf_life_study_payload(expected_formulation_version, **overrides),
            RND,
        )
    )


def add_timepoint(study_id, day_index, quality_score) -> dict:
    return get_success_data(
        api_client.add_timepoint(
            study_id, {"day_index": day_index, "quality_score": quality_score}, RND
        )
    )


def draft_label(project_id, formulation_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_label_approval(
            project_id, f.label_approval_payload(formulation_id, **overrides), LEAD
        )
    )


def submit_label(label_id) -> dict:
    return get_success_data(api_client.submit_label_approval(label_id, {}, LEAD))


def decide_label(label_id, decision="APPROVE", **payload) -> dict:
    body = {"decision": decision}
    body.update(payload)
    return get_success_data(api_client.decide_label_approval(label_id, body, REGULATORY))


def schedule_gate_review(project_id, gate_id, chair_user_id="chair-1", **overrides) -> dict:
    return get_success_data(
        api_client.create_gate_review(
            project_id,
            f.gate_review_payload(gate_id, **overrides),
            make_gate_chair_headers(chair_user_id),
        )
    )


def open_gate_review(review_id, chair_user_id="chair-1") -> dict:
    return get_success_data(
        api_client.open_gate_review(review_id, {}, make_gate_chair_headers(chair_user_id))
    )


def cast_vote(review_id, function="OPERATIONS", vote="APPROVE", voter_user_id="rev-ops",
              **overrides) -> dict:
    payload = f.gate_vote_payload(function=function, vote=vote, **overrides)
    return get_success_data(
        api_client.cast_gate_vote(
            review_id, payload, make_functional_reviewer_headers(voter_user_id)
        )
    )


def close_gate_review(review_id, chair_user_id="chair-1", **payload) -> dict:
    return get_success_data(
        api_client.close_gate_review(
            review_id, payload, make_gate_chair_headers(chair_user_id)
        )
    )


def submit_deliverable(deliverable_id, evidence_url="https://evidence.example/doc",
                       submitter_user_id="lead-submit") -> dict:
    return get_success_data(
        api_client.submit_deliverable(
            deliverable_id,
            {"evidence_url": evidence_url},
            make_innovation_lead_headers(submitter_user_id),
        )
    )


def decide_deliverable(deliverable_id, decision="APPROVE", decider_user_id="rev-decide",
                       **payload) -> dict:
    body = {"decision": decision}
    body.update(payload)
    return get_success_data(
        api_client.decide_deliverable(
            deliverable_id, body, make_functional_reviewer_headers(decider_user_id)
        )
    )


def waive_deliverable(deliverable_id, reason="Waived by the chair",
                      chair_user_id="chair-1") -> dict:
    return get_success_data(
        api_client.waive_deliverable(
            deliverable_id, {"reason": reason}, make_gate_chair_headers(chair_user_id)
        )
    )


def list_deliverables(**params) -> list:
    data = get_success_data(api_client.list_deliverables(ADMIN, params=params or None))
    return data


def project_deliverables(project_id, gate_id=None) -> list:
    params = {"project_id": project_id, "limit": 100}
    if gate_id is not None:
        params["gate_id"] = gate_id
    response = api_client.list_deliverables(ADMIN, params=params)
    return get_success_data(response)


def deliverable_by_type(project_id, deliverable_type, gate_id=None):
    for item in project_deliverables(project_id, gate_id=gate_id):
        if item["deliverable_type"] == deliverable_type:
            return item
    return None


def book_presentation(project_id, retailer_id, window_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_sell_in_presentation(
            project_id,
            f.sell_in_presentation_payload(retailer_id, window_id, **overrides),
            SALES,
        )
    )


def present_presentation(presentation_id) -> dict:
    return get_success_data(
        api_client.present_sell_in_presentation(presentation_id, {}, SALES)
    )


def record_outcome(presentation_id, outcome="ACCEPTED", **payload) -> dict:
    body = {"outcome": outcome}
    body.update(payload)
    return get_success_data(api_client.record_sell_in_outcome(presentation_id, body, SALES))


def withdraw_presentation(presentation_id, reason="Buyer meeting moved") -> dict:
    return get_success_data(
        api_client.withdraw_sell_in_presentation(presentation_id, {"reason": reason}, SALES)
    )


def read_window(window_id) -> dict:
    return get_success_data(api_client.get_shelf_reset_window(window_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: gate sessions
# ---------------------------------------------------------------------------

def run_gate_session(project_id, gate_id, votes=(("OPERATIONS", "APPROVE", "rev-ops"),),
                     chair_user_id="chair-1", close_payload=None, scheduled_at=None):
    """Schedule, open, ballot and close one gate review. Returns the closed review."""
    schedule_kwargs = {} if scheduled_at is None else {"scheduled_at": scheduled_at}
    review = schedule_gate_review(project_id, gate_id, chair_user_id, **schedule_kwargs)
    open_gate_review(review["id"], chair_user_id)
    for function, vote, voter in votes:
        cast_vote(review["id"], function=function, vote=vote, voter_user_id=voter)
    closed = close_gate_review(review["id"], chair_user_id, **(close_payload or {}))
    return closed


def approve_readiness_deliverables(project_id, gate_id, types=None):
    """Submit and approve the readiness checklist items so readiness reaches 100.00."""
    approved = []
    for deliverable_type in types or READINESS_DELIVERABLE_TYPES:
        item = deliverable_by_type(project_id, deliverable_type, gate_id=gate_id)
        if item is None:
            continue
        submit_deliverable(item["id"])
        approved.append(decide_deliverable(item["id"], "APPROVE"))
    return approved


# ---------------------------------------------------------------------------
# Tier 2: project skeletons
# ---------------------------------------------------------------------------

def setup_screened_project(category="BEVERAGE", project_type="LINE_EXTENSION",
                           gate_overrides=None, project_overrides=None,
                           clock="2026-08-03T00:00:00Z", owner_user_id="lead-owner",
                           chair_user_id="chair-1"):
    """Clock, a gate 2 configuration and a project screened into SCREENED."""
    if clock:
        set_clock(clock)
    gate_kwargs = {"gate_number": 2, "category": category, "stage_from": "SCREENED",
                   "stage_to": "PILOT_QUALIFIED"}
    gate_kwargs.update(gate_overrides or {})
    gate2 = register_stage_gate(**gate_kwargs)
    project_kwargs = {"category": category, "project_type": project_type}
    project_kwargs.update(project_overrides or {})
    project = intake_project(owner_user_id=owner_user_id, **project_kwargs)
    screened = screen_project(project["id"], chair_user_id=chair_user_id)
    return {"gate2": gate2, "project": screened}


def setup_pilot_qualified_project(category="BEVERAGE", project_type="LINE_EXTENSION",
                                  gate_overrides=None, project_overrides=None,
                                  case_overrides=None, line_overrides=None,
                                  clock="2026-08-03T00:00:00Z", owner_user_id="lead-owner",
                                  chair_user_id="chair-1"):
    """A project carried through gate 2 into dev_status PILOT_QUALIFIED.

    Includes a computed business case with one channel forecast line, which is what
    trade-presentation booking later needs.
    """
    base = setup_screened_project(
        category=category, project_type=project_type, gate_overrides=gate_overrides,
        project_overrides=project_overrides, clock=clock, owner_user_id=owner_user_id,
        chair_user_id=chair_user_id,
    )
    project_id = base["project"]["id"]
    case, line = open_case_with_line(project_id, case_overrides, line_overrides)
    review = run_gate_session(project_id, base["gate2"]["id"], chair_user_id=chair_user_id)
    return {
        "gate2": base["gate2"],
        "project": read_project(project_id),
        "business_case": case,
        "forecast_line": line,
        "gate2_review": review,
    }


def setup_cleared_formulation(project_id, pilot_line=None, allergen_regime="NONE",
                              actual_units=8500, planned_units=10000,
                              run_window_start="2026-08-06T08:00:00Z",
                              run_window_end="2026-08-06T16:00:00Z",
                              study_start="2026-08-06T17:00:00Z",
                              duration_days=30, timepoint=(30, 88.00),
                              committed_cost_usd=20000.00, study_cost_usd=30000.00,
                              line_code="AKR-1", **formulation_overrides):
    """Walk one formulation from DRAFT to SHELF_LIFE_CLEARED.

    Books a pilot run, starts and completes it above the yield floor, then opens a
    stability study and appends the closing timepoint.
    """
    line = pilot_line or register_pilot_line(
        line_code=line_code, allergen_regime=allergen_regime
    )
    formulation = create_formulation(
        project_id, allergen_regime=allergen_regime, **formulation_overrides
    )
    run = book_pilot_run(
        formulation["id"], line["id"], window_start=run_window_start,
        window_end=run_window_end, planned_units=planned_units,
        committed_cost_usd=committed_cost_usd,
    )
    set_clock(run_window_start)
    start_pilot_run(run["id"])
    run = complete_pilot_run(run["id"], actual_units)
    study = open_shelf_life_study(
        formulation["id"], duration_days=duration_days,
        committed_cost_usd=study_cost_usd, start_at=study_start,
    )
    study = add_timepoint(study["id"], timepoint[0], timepoint[1])
    return {
        "pilot_line": line,
        "formulation": read_formulation(formulation["id"]),
        "pilot_run": run,
        "shelf_life_study": study,
    }


def clear_label(project_id, formulation_id, decision="APPROVE", **overrides):
    """Draft, submit and clear pack artwork against a shelf-life-cleared formulation."""
    label = draft_label(project_id, formulation_id, **overrides)
    submit_label(label["id"])
    extra = {}
    if decision == "APPROVE_WITH_CHANGES":
        extra["unsupported_claims"] = ["Sparkling yuzu, no added sugar"]
    return decide_label(label["id"], decision, **extra)


def setup_launch_ready_project(category="BEVERAGE", project_type="LINE_EXTENSION",
                               readiness_types=None, gate3_overrides=None,
                               owner_user_id="lead-owner", chair_user_id="chair-1",
                               clock="2026-08-03T00:00:00Z", **kwargs):
    """A project carried through gate 2 and gate 3 into dev_status LAUNCH_READY.

    Gate 3 demands the readiness checklist types, which are submitted and approved so
    that launch_readiness_pct reaches 100.00. The current formulation is
    SHELF_LIFE_CLEARED and carries an APPROVED label approval.
    """
    readiness_types = list(readiness_types or READINESS_DELIVERABLE_TYPES)
    if clock:
        set_clock(clock)

    gate2_kwargs = {"gate_number": 2, "category": category, "stage_from": "SCREENED",
                    "stage_to": "PILOT_QUALIFIED"}
    gate2_kwargs.update(kwargs.pop("gate_overrides", None) or {})
    gate2 = register_stage_gate(**gate2_kwargs)

    gate3_kwargs = {
        "gate_number": 3, "category": category, "stage_from": "PILOT_QUALIFIED",
        "stage_to": "LAUNCH_READY", "required_deliverable_types": readiness_types,
    }
    gate3_kwargs.update(gate3_overrides or {})
    gate3 = register_stage_gate(**gate3_kwargs)

    project_kwargs = {"category": category, "project_type": project_type}
    project_kwargs.update(kwargs.pop("project_overrides", None) or {})
    project = intake_project(owner_user_id=owner_user_id, **project_kwargs)
    project_id = project["id"]
    screen_project(project_id, chair_user_id=chair_user_id)
    case, line = open_case_with_line(
        project_id, kwargs.pop("case_overrides", None), kwargs.pop("line_overrides", None)
    )
    formulation_ctx = setup_cleared_formulation(project_id)
    label = clear_label(project_id, formulation_ctx["formulation"]["id"])

    gate2_review = run_gate_session(project_id, gate2["id"], chair_user_id=chair_user_id)
    approve_readiness_deliverables(project_id, gate3["id"], readiness_types)
    gate3_review = run_gate_session(project_id, gate3["id"], chair_user_id=chair_user_id)

    ctx = {
        "gate2": gate2,
        "gate3": gate3,
        "gate2_review": gate2_review,
        "gate3_review": gate3_review,
        "business_case": case,
        "forecast_line": line,
        "label_approval": label,
        "project": read_project(project_id),
    }
    ctx.update(formulation_ctx)
    return ctx


def setup_retailer_with_window(category="BEVERAGE", channel="GROCERY",
                               window_overrides=None, retailer_overrides=None):
    retailer = register_retailer(channel=channel, **(retailer_overrides or {}))
    window = open_reset_window(
        retailer["id"], category=category, **(window_overrides or {})
    )
    return retailer, window


def setup_authorized_project(category="BEVERAGE", channel="GROCERY",
                             present_at="2026-09-14T10:00:00Z", **kwargs):
    """A LAUNCH_READY project whose retailer accepted its trade presentation."""
    ctx = setup_launch_ready_project(category=category, **kwargs)
    retailer, window = setup_retailer_with_window(category=category, channel=channel)
    presentation = book_presentation(
        ctx["project"]["id"], retailer["id"], window["id"], scheduled_at=present_at
    )
    set_clock(present_at)
    present_presentation(presentation["id"])
    presentation = record_outcome(presentation["id"], "ACCEPTED", accepted_sku_count=3)
    ctx.update({
        "retailer": retailer,
        "window": window,
        "presentation": presentation,
        "project": read_project(ctx["project"]["id"]),
    })
    return ctx


def setup_launch_locked_project(launch_date="2026-11-05T00:00:00Z", **kwargs):
    """An AUTHORIZED project whose launch date has been locked inside its window."""
    ctx = setup_authorized_project(**kwargs)
    locked = get_success_data(
        api_client.lock_launch_date(
            ctx["project"]["id"],
            f.launch_lock_payload(launch_date, ctx["window"]["id"]),
            CHAIR,
        )
    )
    ctx["project"] = locked
    ctx["launch_date"] = launch_date
    return ctx


def setup_launched_project(launch_date="2026-11-05T00:00:00Z", **kwargs):
    """A shipped project: dev_status LAUNCHED and commercial_status SHIPPED."""
    ctx = setup_launch_locked_project(launch_date=launch_date, **kwargs)
    set_clock(launch_date)
    launched = get_success_data(api_client.launch_project(ctx["project"]["id"], {}, CHAIR))
    ctx["project"] = launched
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: ledger and capacity targeting
# ---------------------------------------------------------------------------

def setup_launch_locked_with_regulatory_clearance(
        category="HOUSEHOLD", project_type="LINE_EXTENSION",
        clock="2026-08-03T00:00:00Z",
        readiness_types=("MANUFACTURING_READINESS", "SALES_SELL_IN_PLAN"),
        present_at="2026-09-10T15:00:00Z", launch_date="2026-10-26T00:00:00Z",
        chair_user_id="chair-cs"):
    """A launch-locked project whose regulatory clearance rests on its cleared label.

    The commercialisation gate demands only manufacturing and sales readiness, and a
    hand-added `REGULATORY_CLEARANCE` item is auto-approved by the label decision, so the
    lock genuinely depends on the label that describes the current formulation.
    """
    readiness_types = list(readiness_types)
    set_clock(clock)
    gate2 = register_stage_gate(
        gate_number=2, category=category, stage_from="SCREENED",
        stage_to="PILOT_QUALIFIED", required_deliverable_types=["PRELIM_BUSINESS_CASE"],
    )
    gate3 = register_stage_gate(
        gate_number=3, category=category, stage_from="PILOT_QUALIFIED",
        stage_to="LAUNCH_READY", required_deliverable_types=readiness_types,
    )
    retailer = register_retailer(
        name="HomeMart", channel="GROCERY", acv_contribution_pct=32.50,
        presentation_lead_days=21,
    )
    window = open_reset_window(
        retailer["id"], category=category, window_start="2026-10-05T00:00:00Z",
        window_end="2026-10-30T23:59:59Z", max_presentations=3,
    )
    project = intake_project(
        owner_user_id="lead-cs", name="Citrus Surface Wipes", brand="PureHome",
        category=category, project_type=project_type, strategic_fit_score=8,
        consumer_need_score=7, target_gross_margin_pct=36,
        category_attractiveness_score=7, development_budget_cap_usd=200000.00,
    )
    project_id = project["id"]
    screen_project(project_id, chair_user_id=chair_user_id)
    case, line = open_case_with_line(project_id)
    formulation_ctx = setup_cleared_formulation(
        project_id, line_code="TOL-1", committed_cost_usd=60000.00,
        study_cost_usd=40000.00, timepoint=(30, 92.00),
        spec_summary="Citrus wipe substrate rev A", unit_cost_usd=3.2000,
    )
    regulatory_item = get_success_data(
        api_client.create_deliverable(
            project_id,
            {"gate_id": gate2["id"], "deliverable_type": "REGULATORY_CLEARANCE",
             "owner_function": "REGULATORY"},
            LEAD,
        )
    )
    label = clear_label(project_id, formulation_ctx["formulation"]["id"],
                        label_version="CS-v1", claims=["Streak-free shine"])
    gate2_review = run_gate_session(
        project_id, gate2["id"], chair_user_id=chair_user_id,
        scheduled_at="2026-08-07T09:00:00Z",
    )
    approve_readiness_deliverables(project_id, gate3["id"], readiness_types)
    gate3_review = run_gate_session(
        project_id, gate3["id"], chair_user_id=chair_user_id,
        scheduled_at="2026-08-20T09:00:00Z",
    )
    presentation = book_presentation(
        project_id, retailer["id"], window["id"], scheduled_at=present_at,
        proposed_sku_count=4,
    )
    set_clock(present_at)
    present_presentation(presentation["id"])
    presentation = record_outcome(presentation["id"], "ACCEPTED", accepted_sku_count=4)
    locked = get_success_data(
        api_client.lock_launch_date(
            project_id, f.launch_lock_payload(launch_date, window["id"]),
            make_gate_chair_headers(chair_user_id),
        )
    )
    ctx = {
        "gate2": gate2,
        "gate3": gate3,
        "gate2_review": gate2_review,
        "gate3_review": gate3_review,
        "retailer": retailer,
        "window": window,
        "business_case": case,
        "forecast_line": line,
        "regulatory_deliverable": regulatory_item,
        "label_approval": label,
        "presentation": presentation,
        "launch_date": launch_date,
        "project": locked,
    }
    ctx.update(formulation_ctx)
    return ctx


def setup_project_at_budget_cap(cap_usd=200000.00, qualifying_run_cost=20000.00,
                                run_cost=100000.00, study_cost=80000.00,
                                clock="2026-08-03T00:00:00Z", line_code="TOL-2"):
    """A project whose committed development spend sits exactly on its cap.

    A completed qualifying run clears the formulation for stability testing; a second
    SCHEDULED run on a free line plus the ACTIVE study then fill the cap to the cent, which
    is the state a further commitment of a single cent must be refused from. The SCHEDULED
    run is the cancellable one.
    """
    if clock:
        set_clock(clock)
    line = register_pilot_line(
        plant_name="Toledo Pilot", line_code=line_code, hourly_cost_usd=850.00
    )
    spare_line = register_pilot_line(
        plant_name="Toledo Pilot", line_code=f"{line_code}-B", hourly_cost_usd=850.00
    )
    project = intake_project(
        name="Ledger Probe", category="BEVERAGE", project_type="NEW_BRAND",
        strategic_fit_score=7, consumer_need_score=8, target_gross_margin_pct=32,
        category_attractiveness_score=6, development_budget_cap_usd=cap_usd,
    )
    formulation = create_formulation(project["id"])
    qualifying_run = book_pilot_run(
        formulation["id"], line["id"], committed_cost_usd=qualifying_run_cost
    )
    set_clock("2026-08-06T08:00:00Z")
    start_pilot_run(qualifying_run["id"])
    complete_pilot_run(qualifying_run["id"], 8500)
    run = book_pilot_run(
        formulation["id"], spare_line["id"], window_start="2026-08-07T08:00:00Z",
        window_end="2026-08-07T16:00:00Z", committed_cost_usd=run_cost,
    )
    study = open_shelf_life_study(
        formulation["id"], duration_days=30, committed_cost_usd=study_cost,
        start_at="2026-08-08T09:00:00Z",
    )
    return {
        "pilot_line": spare_line,
        "qualifying_pilot_line": line,
        "project": read_project(project["id"]),
        "formulation": read_formulation(formulation["id"]),
        "qualifying_pilot_run": qualifying_run,
        "pilot_run": run,
        "shelf_life_study": study,
    }

"""Composite setup helpers.

Every helper builds state from scratch through the public API, because each test
runs against a freshly started server with an empty database.  A helper returns
a ``scenario`` dictionary that accumulates the identifiers, the role headers and
the entity bodies produced along the way, so a test can pick out whatever it
needs:

    scenario = setup_five_center_report_with_single_run(api)
    scenario["report_id"], scenario["cc_ancillary"], scenario["run"]

All setup calls go through ``get_success_data`` so that a broken preamble fails
loudly and distinguishably from the assertion under test.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as make
from .constants import CANONICAL_OCC_MIX, DEFAULT_CLOCK
from .test_users import (
    AUDITOR_ONE_ID,
    AUDITOR_TWO_ID,
    SYSTEM_ADMIN_HEADERS,
    make_mac_auditor_headers,
    make_reimbursement_analyst_headers,
    make_reimbursement_manager_headers,
    make_review_board_clerk_headers,
)

# ---------------------------------------------------------------------------
# Canonical cost center definitions reused by the report builders
# ---------------------------------------------------------------------------

CENTER_AG = {
    "code": "00100",
    "name": "Administrative and General",
    "center_type": "GENERAL_SERVICE",
    "allocation_basis": "SQUARE_FEET",
    "stepdown_order": 1,
    "statistics": {"SQUARE_FEET": 0, "POUNDS_LAUNDRY": 500},
}

CENTER_LAUNDRY = {
    "code": "00200",
    "name": "Laundry and Linen",
    "center_type": "GENERAL_SERVICE",
    "allocation_basis": "POUNDS_LAUNDRY",
    "stepdown_order": 2,
    "statistics": {"SQUARE_FEET": 1000, "POUNDS_LAUNDRY": 0},
}

CENTER_ROUTINE = {
    "code": "03000",
    "name": "Adults and Pediatrics",
    "center_type": "ROUTINE",
    "statistics": {"SQUARE_FEET": 3000, "POUNDS_LAUNDRY": 6000},
}

CENTER_ANCILLARY = {
    "code": "05000",
    "name": "Operating Room",
    "center_type": "ANCILLARY",
    "statistics": {"SQUARE_FEET": 2000, "POUNDS_LAUNDRY": 2000},
}

CENTER_NONREIMB = {
    "code": "09000",
    "name": "Gift Shop",
    "center_type": "NONREIMBURSABLE",
    "statistics": {"SQUARE_FEET": 0, "POUNDS_LAUNDRY": 2000},
}


# ---------------------------------------------------------------------------
# Tier 0: primitives
# ---------------------------------------------------------------------------


def set_clock(api, instant=DEFAULT_CLOCK):
    """Move the logical clock. Only a SystemAdmin may do this."""
    return get_success_data(api.set_clock(make.clock_payload(instant), SYSTEM_ADMIN_HEADERS))


def create_provider(api, **overrides):
    return get_success_data(
        api.create_provider(make.provider_payload(**overrides), SYSTEM_ADMIN_HEADERS)
    )


def create_other_provider(api, **overrides):
    return get_success_data(
        api.create_provider(make.other_provider_payload(**overrides), SYSTEM_ADMIN_HEADERS)
    )


def create_cost_report(api, provider_id, **overrides):
    return get_success_data(
        api.create_cost_report(
            make.cost_report_payload(provider_id, **overrides), SYSTEM_ADMIN_HEADERS
        )
    )


def read_cost_report(api, scenario):
    return get_success_data(api.get_cost_report(scenario["report_id"], scenario["analyst"]))


def read_provider(api, scenario):
    return get_success_data(api.get_provider(scenario["provider_id"], scenario["manager"]))


def read_cost_center(api, scenario, cost_center_id):
    return get_success_data(api.get_cost_center(cost_center_id, scenario["analyst"]))


def role_headers_for(provider_id):
    """The five role header sets a scenario carries, scoped where it matters."""
    return {
        "admin": SYSTEM_ADMIN_HEADERS,
        "analyst": make_reimbursement_analyst_headers(provider_id),
        "manager": make_reimbursement_manager_headers(provider_id),
        "auditor": make_mac_auditor_headers(AUDITOR_ONE_ID),
        "auditor_two": make_mac_auditor_headers(AUDITOR_TWO_ID),
        "clerk": make_review_board_clerk_headers(),
    }


def new_scenario(api, clock=DEFAULT_CLOCK, provider_overrides=None, report_overrides=None):
    """Clock + Provider + DRAFT CostReport. The root of every other helper."""
    set_clock(api, clock)
    provider = create_provider(api, **(provider_overrides or {}))
    report = create_cost_report(api, provider["id"], **(report_overrides or {}))

    scenario = {
        "provider": provider,
        "provider_id": provider["id"],
        "report": report,
        "report_id": report["id"],
        "centers": {},
        "trial_balance_lines": [],
        "runs": [],
    }
    scenario.update(role_headers_for(provider["id"]))
    return scenario


def add_cost_center(api, scenario, key, definition):
    """Create one cost center and file it under ``key`` in the scenario."""
    center = get_success_data(
        api.create_cost_center(scenario["report_id"], dict(definition), scenario["analyst"])
    )
    scenario["centers"][definition["code"]] = center
    scenario[key] = center["id"]
    scenario[key + "_center"] = center
    return center


def add_mapped_tb_line(api, scenario, gl_account, description, amount_cents, cost_center_key):
    payload = make.trial_balance_line_payload(
        gl_account=gl_account,
        description=description,
        amount_cents=amount_cents,
        mapped_cost_center_id=scenario[cost_center_key],
    )
    line = get_success_data(
        api.create_trial_balance_line(scenario["report_id"], payload, scenario["analyst"])
    )
    scenario["trial_balance_lines"].append(line)
    return line


def add_unmapped_tb_line(api, scenario, gl_account="6900", description="Suspense account", amount_cents=1000000):
    payload = make.trial_balance_line_payload(
        gl_account=gl_account, description=description, amount_cents=amount_cents
    )
    line = get_success_data(
        api.create_trial_balance_line(scenario["report_id"], payload, scenario["analyst"])
    )
    scenario["trial_balance_lines"].append(line)
    scenario["unmapped_line"] = line
    return line


# ---------------------------------------------------------------------------
# Tier 1: cost center structures
# ---------------------------------------------------------------------------


def setup_two_center_report(api, **kwargs):
    """One general service center and one routine center, both funded.

    Mapped direct cost is 100000000 on A&G and 200000000 on the routine center.
    """
    scenario = new_scenario(api, **kwargs)
    add_cost_center(
        api,
        scenario,
        "cc_ag",
        {**CENTER_AG, "statistics": {"SQUARE_FEET": 0}},
    )
    add_cost_center(
        api,
        scenario,
        "cc_routine",
        {**CENTER_ROUTINE, "statistics": {"SQUARE_FEET": 3000}},
    )
    add_mapped_tb_line(api, scenario, "6000", "Administration salaries", 100000000, "cc_ag")
    add_mapped_tb_line(api, scenario, "6200", "Nursing salaries", 200000000, "cc_routine")
    return scenario


def setup_three_center_report(api, **kwargs):
    """A&G plus a routine and an ancillary receiver; mapped total 420000000."""
    scenario = new_scenario(api, **kwargs)
    add_cost_center(
        api, scenario, "cc_ag", {**CENTER_AG, "statistics": {"SQUARE_FEET": 0}}
    )
    add_cost_center(
        api,
        scenario,
        "cc_routine",
        {**CENTER_ROUTINE, "statistics": {"SQUARE_FEET": 3000}},
    )
    add_cost_center(
        api,
        scenario,
        "cc_ancillary",
        {**CENTER_ANCILLARY, "statistics": {"SQUARE_FEET": 2000}},
    )
    add_mapped_tb_line(api, scenario, "6000", "Administration salaries", 100000000, "cc_ag")
    add_mapped_tb_line(api, scenario, "6200", "Nursing salaries", 200000000, "cc_routine")
    add_mapped_tb_line(
        api, scenario, "6300", "Operating room supplies", 120000000, "cc_ancillary"
    )
    return scenario


def setup_five_center_report(api, **kwargs):
    """The canonical structure: two allocators and three receivers.

    Direct cost lands as 100000000 / 40000000 / 200000000 / 120000000 /
    10000000 for a mapped total of 470000000 with nothing unmapped.
    """
    scenario = new_scenario(api, **kwargs)
    add_cost_center(api, scenario, "cc_ag", CENTER_AG)
    add_cost_center(api, scenario, "cc_laundry", CENTER_LAUNDRY)
    add_cost_center(api, scenario, "cc_routine", CENTER_ROUTINE)
    add_cost_center(api, scenario, "cc_ancillary", CENTER_ANCILLARY)
    add_cost_center(api, scenario, "cc_nonreimb", CENTER_NONREIMB)
    add_mapped_tb_line(api, scenario, "6000", "Administration salaries", 100000000, "cc_ag")
    add_mapped_tb_line(api, scenario, "6100", "Laundry salaries", 40000000, "cc_laundry")
    add_mapped_tb_line(api, scenario, "6200", "Nursing salaries", 200000000, "cc_routine")
    add_mapped_tb_line(
        api, scenario, "6300", "Operating room supplies", 120000000, "cc_ancillary"
    )
    add_mapped_tb_line(
        api, scenario, "6400", "Gift shop operating cost", 10000000, "cc_nonreimb"
    )
    return scenario


def setup_dietary_zero_statistic_report(api, **kwargs):
    """A dietary allocator whose statistic key is absent from every receiver."""
    scenario = new_scenario(api, **kwargs)
    add_cost_center(
        api,
        scenario,
        "cc_dietary",
        {
            "code": "00300",
            "name": "Dietary",
            "center_type": "GENERAL_SERVICE",
            "allocation_basis": "MEALS_SERVED",
            "stepdown_order": 1,
            "statistics": {},
        },
    )
    add_cost_center(
        api,
        scenario,
        "cc_routine",
        {**CENTER_ROUTINE, "statistics": {"SQUARE_FEET": 3000}},
    )
    add_cost_center(
        api,
        scenario,
        "cc_ancillary",
        {**CENTER_ANCILLARY, "statistics": {"SQUARE_FEET": 2000}},
    )
    add_mapped_tb_line(api, scenario, "6500", "Dietary salaries", 60000000, "cc_dietary")
    add_mapped_tb_line(api, scenario, "6200", "Nursing salaries", 200000000, "cc_routine")
    add_mapped_tb_line(
        api, scenario, "6300", "Operating room supplies", 120000000, "cc_ancillary"
    )
    return scenario


# ---------------------------------------------------------------------------
# Tier 2: stepdown runs
# ---------------------------------------------------------------------------


def current_report_version(api, scenario):
    report = read_cost_report(api, scenario)
    scenario["report"] = report
    return report["version"]


def run_stepdown(api, scenario, method="SINGLE_APPORTIONMENT", headers=None):
    """Read the current report version, then launch a stepdown run with it."""
    version = current_report_version(api, scenario)
    run = get_success_data(
        api.create_stepdown_run(
            scenario["report_id"],
            make.stepdown_run_payload(version, method=method),
            headers or scenario["analyst"],
        )
    )
    scenario["runs"].append(run)
    scenario["run"] = run
    scenario["run_id"] = run["id"]
    if method == "SINGLE_APPORTIONMENT":
        scenario["single_run"] = run
    else:
        scenario["double_run"] = run
    return run


def setup_five_center_report_with_single_run(api, **kwargs):
    """Canonical structure with a COMPLETED single apportionment run."""
    scenario = setup_five_center_report(api, **kwargs)
    run_stepdown(api, scenario, "SINGLE_APPORTIONMENT")
    return scenario


def setup_five_center_report_with_double_run(api, **kwargs):
    """Canonical structure with a COMPLETED double apportionment run."""
    overrides = dict(kwargs.pop("report_overrides", None) or {})
    overrides.setdefault("apportionment_method", "DOUBLE_APPORTIONMENT")
    scenario = setup_five_center_report(api, report_overrides=overrides, **kwargs)
    run_stepdown(api, scenario, "DOUBLE_APPORTIONMENT")
    return scenario


# ---------------------------------------------------------------------------
# Tier 3: wage index submission and its review cycle
# ---------------------------------------------------------------------------


def add_wage_submission(api, scenario, occ_mix=None, **overrides):
    submission = get_success_data(
        api.create_wage_index_submission(
            scenario["report_id"],
            make.wage_index_submission_payload(**overrides),
            scenario["analyst"],
        )
    )
    scenario["submission"] = submission
    scenario["submission_id"] = submission["id"]
    scenario["occ_mix_responses"] = []
    for entry in CANONICAL_OCC_MIX if occ_mix is None else occ_mix:
        response = get_success_data(
            api.create_occ_mix_response(submission["id"], dict(entry), scenario["analyst"])
        )
        scenario["occ_mix_responses"].append(response)
    return submission


def submit_wage_submission(api, scenario):
    submission = get_success_data(
        api.submit_wage_index_submission(scenario["submission_id"], scenario["manager"])
    )
    scenario["submission"] = submission
    return submission


def start_wage_review(api, scenario):
    submission = get_success_data(
        api.start_wage_index_review(scenario["submission_id"], scenario["auditor"])
    )
    scenario["submission"] = submission
    return submission


def record_wage_review_decision(api, scenario, decision="ACCEPT", review_note=None):
    payload = (
        make.review_decision_payload(decision=decision)
        if review_note is None
        else make.review_decision_payload(decision=decision, review_note=review_note)
    )
    submission = get_success_data(
        api.record_wage_index_review_decision(
            scenario["submission_id"], payload, scenario["auditor"]
        )
    )
    scenario["submission"] = submission
    return submission


def accept_wage_submission(api, scenario, occ_mix=None, **overrides):
    """Draft the survey, submit it, open review and accept it."""
    if "submission_id" not in scenario:
        add_wage_submission(api, scenario, occ_mix=occ_mix, **overrides)
    submit_wage_submission(api, scenario)
    start_wage_review(api, scenario)
    return record_wage_review_decision(
        api,
        scenario,
        "ACCEPT",
        "Hours and salaries verified against payroll registers",
    )


def setup_submitted_wage_submission(api, **kwargs):
    scenario = setup_five_center_report(api, **kwargs)
    add_wage_submission(api, scenario)
    submit_wage_submission(api, scenario)
    return scenario


def setup_accepted_wage_submission(api, **kwargs):
    scenario = setup_five_center_report(api, **kwargs)
    accept_wage_submission(api, scenario)
    return scenario


# ---------------------------------------------------------------------------
# Tier 4: uncompensated care data
# ---------------------------------------------------------------------------


def add_ucc_data_set(api, scenario, **overrides):
    data_set = get_success_data(
        api.create_ucc_data_set(
            scenario["report_id"], make.ucc_data_set_payload(**overrides), scenario["analyst"]
        )
    )
    scenario["ucc_data_set"] = data_set
    scenario["ucc_data_set_id"] = data_set["id"]
    return data_set


def recompute_ucc_data_set(api, scenario, headers=None):
    data_set = get_success_data(
        api.recompute_ucc_data_set(
            scenario["ucc_data_set_id"], headers or scenario["analyst"]
        )
    )
    scenario["ucc_data_set"] = data_set
    return data_set


# ---------------------------------------------------------------------------
# Tier 5: filing and settlement lifecycle
# ---------------------------------------------------------------------------


def setup_filing_ready_report(api, **kwargs):
    """Everything the filing gate demands: mapped ledger, a current allocation,
    an accepted wage submission and an uncompensated care data set."""
    scenario = setup_five_center_report_with_single_run(api, **kwargs)
    accept_wage_submission(api, scenario)
    add_ucc_data_set(api, scenario)
    return scenario


def file_report(api, scenario):
    report = get_success_data(
        api.file_cost_report(scenario["report_id"], scenario["manager"])
    )
    scenario["report"] = report
    return report


def setup_filed_report(api, **kwargs):
    scenario = setup_filing_ready_report(api, **kwargs)
    file_report(api, scenario)
    return scenario


def create_settlement(api, scenario, stage="TENTATIVE"):
    settlement = get_success_data(
        api.create_settlement(
            scenario["report_id"], make.settlement_payload(stage), scenario["auditor"]
        )
    )
    key = "tentative_settlement" if stage == "TENTATIVE" else "final_settlement"
    scenario[key] = settlement
    scenario[key + "_id"] = settlement["id"]
    scenario["settlement"] = settlement
    scenario["settlement_id"] = settlement["id"]
    return settlement


def setup_tentative_settlement(api, **kwargs):
    """Filed report plus the tentative settlement issued off the single run."""
    scenario = setup_filed_report(api, **kwargs)
    create_settlement(api, scenario, "TENTATIVE")
    return scenario


def setup_final_settlement(api, **kwargs):
    """Tentative settlement, then a double apportionment run, then the final."""
    scenario = setup_tentative_settlement(api, **kwargs)
    run_stepdown(api, scenario, "DOUBLE_APPORTIONMENT")
    create_settlement(api, scenario, "FINAL")
    return scenario


# ---------------------------------------------------------------------------
# Tier 6: audit exceptions
# ---------------------------------------------------------------------------


def propose_audit_adjustment(api, scenario, target_key="cc_ancillary", **overrides):
    adjustment = get_success_data(
        api.create_audit_adjustment(
            scenario["settlement_id"],
            make.audit_adjustment_payload(scenario[target_key], **overrides),
            make_mac_auditor_headers(AUDITOR_ONE_ID),
        )
    )
    scenario["adjustment"] = adjustment
    scenario["adjustment_id"] = adjustment["id"]
    return adjustment


def setup_proposed_audit_adjustment(api, **kwargs):
    """A tentative settlement carrying one PROPOSED audit exception."""
    scenario = setup_tentative_settlement(api, **kwargs)
    propose_audit_adjustment(api, scenario)
    return scenario


def respond_to_audit_adjustment(api, scenario, response="PROTEST", note=None):
    payload = (
        make.audit_response_payload(response=response)
        if note is None
        else make.audit_response_payload(response=response, provider_response_note=note)
    )
    adjustment = get_success_data(
        api.respond_to_audit_adjustment(
            scenario["adjustment_id"], payload, scenario["manager"]
        )
    )
    scenario["adjustment"] = adjustment
    return adjustment


def resolve_audit_adjustment(api, scenario, outcome="INCORPORATE"):
    """Resolved by a second auditor, since the resolver may not be the proposer."""
    adjustment = get_success_data(
        api.resolve_audit_adjustment(
            scenario["adjustment_id"],
            make.audit_resolution_payload(outcome),
            make_mac_auditor_headers(AUDITOR_TWO_ID),
        )
    )
    scenario["adjustment"] = adjustment
    return adjustment


def setup_incorporated_audit_adjustment(api, **kwargs):
    scenario = setup_proposed_audit_adjustment(api, **kwargs)
    resolve_audit_adjustment(api, scenario, "INCORPORATE")
    return scenario


# ---------------------------------------------------------------------------
# Tier 7: workpaper entries
# ---------------------------------------------------------------------------


def create_reclassification(api, scenario, legs, **overrides):
    entry = get_success_data(
        api.create_workpaper_entry(
            scenario["report_id"],
            make.reclassification_payload(legs, **overrides),
            scenario["analyst"],
        )
    )
    scenario["workpaper_entry"] = entry
    scenario["workpaper_entry_id"] = entry["id"]
    return entry


def reverse_workpaper_entry(api, scenario):
    entry = get_success_data(
        api.reverse_workpaper_entry(scenario["workpaper_entry_id"], scenario["analyst"])
    )
    scenario["workpaper_entry"] = entry
    return entry


# ---------------------------------------------------------------------------
# Tier 8: residents and rotations
# ---------------------------------------------------------------------------


def create_resident(api, scenario, **overrides):
    resident = get_success_data(
        api.create_resident(
            scenario["provider_id"], make.resident_payload(**overrides), scenario["analyst"]
        )
    )
    scenario["resident"] = resident
    scenario["resident_id"] = resident["id"]
    return resident


def create_rotation(api, scenario, cost_center_key="cc_routine", **overrides):
    rotation = get_success_data(
        api.create_rotation_assignment(
            scenario["resident_id"],
            make.rotation_assignment_payload(scenario[cost_center_key], **overrides),
            scenario["analyst"],
        )
    )
    scenario.setdefault("rotations", []).append(rotation)
    scenario["rotation"] = rotation
    scenario["rotation_id"] = rotation["id"]
    return rotation


def setup_resident_with_rotation(api, **kwargs):
    """A teaching provider, a resident and one half-year rotation at 0.6000 FTE."""
    scenario = setup_two_center_report(api, **kwargs)
    create_resident(api, scenario)
    rotation = create_rotation(api, scenario)
    scenario["base_rotation"] = rotation
    scenario["base_rotation_id"] = rotation["id"]
    return scenario


def void_rotation(api, scenario, rotation_id=None):
    rotation = get_success_data(
        api.void_rotation_assignment(
            rotation_id or scenario["rotation_id"], scenario["analyst"]
        )
    )
    scenario["rotation"] = rotation
    return rotation


def read_gme_summary(api, scenario):
    return get_success_data(api.get_gme_summary(scenario["report_id"], scenario["analyst"]))


# ---------------------------------------------------------------------------
# Tier 9: appeals and reopening
# ---------------------------------------------------------------------------


def create_appeal_case(api, scenario, settlement_id=None, **overrides):
    case = get_success_data(
        api.create_appeal_case(
            scenario["report_id"],
            make.appeal_case_payload(
                settlement_id or scenario["settlement_id"], **overrides
            ),
            scenario["manager"],
        )
    )
    scenario["appeal_case"] = case
    scenario["appeal_case_id"] = case["id"]
    return case


def decide_appeal_case(api, scenario, outcome="HEAR", headers=None, decision_note=None):
    payload = (
        make.appeal_decision_payload(outcome=outcome)
        if decision_note is None
        else make.appeal_decision_payload(outcome=outcome, decision_note=decision_note)
    )
    case = get_success_data(
        api.decide_appeal_case(
            scenario["appeal_case_id"], payload, headers or scenario["clerk"]
        )
    )
    scenario["appeal_case"] = case
    return case


def setup_prrb_appeal(api, **kwargs):
    """A final settlement with a board appeal pending against it."""
    scenario = setup_final_settlement(api, **kwargs)
    create_appeal_case(
        api,
        scenario,
        settlement_id=scenario["final_settlement_id"],
        kind="PRRB_APPEAL",
    )
    return scenario


def setup_reopened_report(api, **kwargs):
    """A final settlement reopened by a granted reopening request."""
    scenario = setup_final_settlement(api, **kwargs)
    create_appeal_case(
        api,
        scenario,
        settlement_id=scenario["final_settlement_id"],
        kind="REOPENING",
        issue_description="New invoice evidence for the operating room supplies",
    )
    decide_appeal_case(api, scenario, "GRANT", headers=scenario["auditor"])
    scenario["report"] = read_cost_report(api, scenario)
    return scenario


# ---------------------------------------------------------------------------
# Tier 10: interim rate requests
# ---------------------------------------------------------------------------


def setup_interim_rate_basis(api, **kwargs):
    """A final settled report that can serve as an interim rate basis."""
    scenario = setup_final_settlement(api, **kwargs)
    scenario["provider"] = read_provider(api, scenario)
    scenario["provider_version"] = scenario["provider"]["version"]
    return scenario


def create_interim_rate_request(api, scenario, **overrides):
    provider = read_provider(api, scenario)
    scenario["provider"] = provider
    request = get_success_data(
        api.create_interim_rate_request(
            make.interim_rate_request_payload(
                scenario["provider_id"],
                scenario["report_id"],
                provider["version"],
                **overrides,
            ),
            scenario["manager"],
        )
    )
    scenario.setdefault("interim_requests", []).append(request)
    scenario["interim_request"] = request
    scenario["interim_request_id"] = request["id"]
    return request


def decide_interim_rate_request(api, scenario, decision="APPROVE", decision_note=None):
    payload = (
        make.interim_rate_decision_payload(decision=decision)
        if decision_note is None
        else make.interim_rate_decision_payload(
            decision=decision, decision_note=decision_note
        )
    )
    request = get_success_data(
        api.decide_interim_rate_request(
            scenario["interim_request_id"], payload, scenario["auditor"]
        )
    )
    scenario["interim_request"] = request
    return request

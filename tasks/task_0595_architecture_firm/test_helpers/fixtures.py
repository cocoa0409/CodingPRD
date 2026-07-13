"""Composite setup helpers.

The harness restarts the API server before every test, so every helper here builds its
preconditions from scratch through the public endpoints only. Setup calls use the lenient
`get_success_data()` validator so that a broken precondition surfaces as a setup failure
rather than as a confusing assertion inside the test body.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import STANDARD_WEIGHTS, TEST_DEFAULTS
from .factories import (
    create_architect_payload, create_change_order_payload, create_consultant_payload,
    create_contract_payload, create_drawing_payload, create_expense_payload,
    create_field_report_payload, create_hourly_contract_payload, create_invoice_payload,
    create_permit_review_payload, create_phase_payload, create_project_payload,
    create_rfi_payload, create_staff_payload, create_submittal_payload,
    create_time_entry_payload, state_payload, DEFAULT_MILESTONE_DUE,
)
from .test_users import (
    make_client_rep_headers, make_consultant_rep_headers, make_principal_headers,
    make_project_manager_headers, make_staff_architect_headers,
    PRINCIPAL_A_USER_ID, PRINCIPAL_B_USER_ID, CLIENT_REP_USER_ID,
)

PRINCIPAL = make_principal_headers(PRINCIPAL_A_USER_ID)
PRINCIPAL_B = make_principal_headers(PRINCIPAL_B_USER_ID)
CLIENT_REP = make_client_rep_headers(CLIENT_REP_USER_ID)


# --------------------------------------------------------------------------- #
# Tier 0 — master data and the logical clock
# --------------------------------------------------------------------------- #
def set_clock(to_iso8601: str) -> dict:
    """Reposition the server's logical clock."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, PRINCIPAL))


def register_staff(**overrides) -> dict:
    """Register a PROJECT_MANAGER-titled staff member. Their id is a ProjectManager's X-User-ID."""
    return get_success_data(api_client.create_staff(create_staff_payload(**overrides), PRINCIPAL))


def register_architect(**overrides) -> dict:
    """Register an ARCHITECT-titled staff member. Their id is a StaffArchitect's X-User-ID."""
    return get_success_data(
        api_client.create_staff(create_architect_payload(**overrides), PRINCIPAL)
    )


def register_consultant(**overrides) -> dict:
    """Register a consultant firm. Its id is a ConsultantRep's X-User-ID."""
    return get_success_data(
        api_client.create_consultant(create_consultant_payload(**overrides), PRINCIPAL)
    )


# --------------------------------------------------------------------------- #
# Tier 1 — project / contract / phase skeleton
# --------------------------------------------------------------------------- #
def setup_project(
    project_number="P-001",
    labor_budget_cents=TEST_DEFAULTS["LABOR_BUDGET_CENTS"],
    client_rep_user_id=CLIENT_REP_USER_ID,
    pm_overrides=None,
    with_architect=True,
    arch_overrides=None,
    **project_overrides,
) -> dict:
    """A ProjectManager, an optional architect, and one DRAFT project owned by that manager.

    Returns a bundle carrying the ids and — crucially — the ownership-threaded headers:
    `pm_headers` is built from the real StaffMember id named in project_manager_staff_id.
    """
    pm = register_staff(**(pm_overrides or {}))
    arch = register_architect(**(arch_overrides or {})) if with_architect else None

    project = get_success_data(
        api_client.create_project(
            create_project_payload(
                pm["id"],
                project_number=project_number,
                labor_budget_cents=labor_budget_cents,
                client_rep_user_id=client_rep_user_id,
                **project_overrides,
            ),
            PRINCIPAL,
        )
    )
    return {
        "pm": pm,
        "pm_id": pm["id"],
        "pm_headers": make_project_manager_headers(pm["id"]),
        "arch": arch,
        "arch_id": arch["id"] if arch else None,
        "arch_headers": make_staff_architect_headers(arch["id"]) if arch else None,
        "project": project,
        "project_id": project["id"],
        "principal_headers": PRINCIPAL,
        "principal_b_headers": PRINCIPAL_B,
        "client_headers": make_client_rep_headers(client_rep_user_id),
    }


def add_contract(bundle: dict, **contract_overrides) -> dict:
    """Attach a DRAFT PERCENT_OF_CONSTRUCTION contract to the bundle's project."""
    contract = get_success_data(
        api_client.create_contract(
            create_contract_payload(bundle["project_id"], **contract_overrides), PRINCIPAL
        )
    )
    bundle["contract"] = contract
    bundle["contract_id"] = contract["id"]
    return contract


def add_hourly_contract(bundle: dict, not_to_exceed_cents: int, **contract_overrides) -> dict:
    """Attach a DRAFT HOURLY contract to the bundle's project."""
    contract = get_success_data(
        api_client.create_contract(
            create_hourly_contract_payload(
                bundle["project_id"], not_to_exceed_cents, **contract_overrides
            ),
            PRINCIPAL,
        )
    )
    bundle["contract"] = contract
    bundle["contract_id"] = contract["id"]
    return contract


def add_four_phases(bundle: dict, weights=STANDARD_WEIGHTS, milestone_due=None,
                    is_billing_milestone=None) -> dict:
    """Create SD / DD / CD / CA on the bundle's project. Returns {phase_code: phase}."""
    codes = ("SD", "DD", "CD", "CA")
    phases = {}
    for index, code in enumerate(codes):
        extra = {}
        if milestone_due and code in milestone_due:
            extra["milestone_due_at"] = milestone_due[code]
        if is_billing_milestone is not None and code in is_billing_milestone:
            extra["is_billing_milestone"] = is_billing_milestone[code]
        phases[code] = get_success_data(
            api_client.create_phase(
                create_phase_payload(bundle["project_id"], code, weights[index], **extra),
                bundle["pm_headers"],
            )
        )
    bundle["phases"] = phases
    bundle["phase_ids"] = {code: phase["id"] for code, phase in phases.items()}
    return phases


def execute_contract(bundle: dict) -> dict:
    """Drive the bundle's contract DRAFT -> EXECUTED (which cascades the project to ACTIVE)."""
    contract = get_success_data(
        api_client.set_contract_state(
            bundle["contract_id"], state_payload("EXECUTED"), PRINCIPAL
        )
    )
    bundle["contract"] = contract
    return contract


def setup_executed_project(
    project_number="P-001",
    weights=STANDARD_WEIGHTS,
    labor_budget_cents=TEST_DEFAULTS["LABOR_BUDGET_CENTS"],
    contract_overrides=None,
    hourly_not_to_exceed_cents=None,
    milestone_due=None,
    is_billing_milestone=None,
    pm_overrides=None,
    arch_overrides=None,
    with_architect=True,
    client_rep_user_id=CLIENT_REP_USER_ID,
    **project_overrides,
) -> dict:
    """Staff + project + contract + four phases + contract EXECUTED.

    This is the backbone of nearly every scenario in the suite: after it returns, the
    project is ACTIVE, the fee is allocated across the four phases, and the SD phase is
    eligible for activation.
    """
    bundle = setup_project(
        project_number=project_number,
        labor_budget_cents=labor_budget_cents,
        client_rep_user_id=client_rep_user_id,
        pm_overrides=pm_overrides,
        arch_overrides=arch_overrides,
        with_architect=with_architect,
        **project_overrides,
    )
    if hourly_not_to_exceed_cents is not None:
        add_hourly_contract(bundle, hourly_not_to_exceed_cents, **(contract_overrides or {}))
    else:
        add_contract(bundle, **(contract_overrides or {}))
    add_four_phases(
        bundle,
        weights=weights,
        milestone_due=milestone_due,
        is_billing_milestone=is_billing_milestone,
    )
    execute_contract(bundle)
    return bundle


def setup_draft_contract_project(
    project_number="P-001",
    weights=STANDARD_WEIGHTS,
    contract_overrides=None,
    **project_overrides,
) -> dict:
    """Project + DRAFT contract + four phases, with the contract deliberately NOT executed."""
    bundle = setup_project(project_number=project_number, **project_overrides)
    add_contract(bundle, **(contract_overrides or {}))
    add_four_phases(bundle, weights=weights)
    return bundle


# --------------------------------------------------------------------------- #
# Tier 2 — phase progression
# --------------------------------------------------------------------------- #
def activate_phase(bundle: dict, code: str) -> dict:
    phase = get_success_data(
        api_client.set_phase_state(
            bundle["phase_ids"][code], state_payload("ACTIVE"), bundle["pm_headers"]
        )
    )
    bundle["phases"][code] = phase
    return phase


def complete_phase(bundle: dict, code: str) -> dict:
    phase = get_success_data(
        api_client.set_phase_state(
            bundle["phase_ids"][code], state_payload("COMPLETED"), bundle["pm_headers"]
        )
    )
    bundle["phases"][code] = phase
    return phase


def set_phase_percent(bundle: dict, code: str, percent_complete: int) -> dict:
    phase = get_success_data(
        api_client.update_phase(
            bundle["phase_ids"][code],
            {"percent_complete": percent_complete},
            bundle["pm_headers"],
        )
    )
    bundle["phases"][code] = phase
    return phase


def activate_and_complete_phase(bundle: dict, code: str) -> dict:
    activate_phase(bundle, code)
    return complete_phase(bundle, code)


def activate_and_advance_phase(bundle: dict, code: str, percent_complete: int) -> dict:
    activate_phase(bundle, code)
    return set_phase_percent(bundle, code, percent_complete)


def setup_project_with_sd_completed(project_number="SDC-001", **kwargs) -> dict:
    """Executed project whose SD phase is COMPLETED (earned_cents == its full allocation)."""
    bundle = setup_executed_project(project_number=project_number, **kwargs)
    activate_and_complete_phase(bundle, "SD")
    return bundle


def setup_project_ready_for_ca(project_number="CAR-001", **kwargs) -> dict:
    """Executed project with SD/DD/CD COMPLETED, an APPROVED PermitReview on CD, CA ACTIVE.

    This is the deepest precondition in the PRD: construction administration can only begin
    once the permit is approved and every preceding phase has closed.
    """
    bundle = setup_executed_project(project_number=project_number, **kwargs)
    activate_and_complete_phase(bundle, "SD")
    activate_and_complete_phase(bundle, "DD")
    activate_and_complete_phase(bundle, "CD")
    permit = approve_permit_review(bundle)
    bundle["permit_review"] = permit
    activate_phase(bundle, "CA")
    return bundle


# --------------------------------------------------------------------------- #
# Tier 3 — permit review
# --------------------------------------------------------------------------- #
def create_permit_review(bundle: dict, **overrides) -> dict:
    permit = get_success_data(
        api_client.create_permit_review(
            create_permit_review_payload(bundle["phase_ids"]["CD"], **overrides),
            bundle["pm_headers"],
        )
    )
    bundle["permit_review_id"] = permit["id"]
    return permit


def approve_permit_review(bundle: dict, **overrides) -> dict:
    """Create a permit package on the (COMPLETED) CD phase, submit it and approve it."""
    permit = create_permit_review(bundle, **overrides)
    get_success_data(
        api_client.set_permit_review_state(
            permit["id"], state_payload("SUBMITTED"), bundle["pm_headers"]
        )
    )
    approved = get_success_data(
        api_client.set_permit_review_state(
            permit["id"], state_payload("APPROVED"), bundle["pm_headers"]
        )
    )
    bundle["permit_review"] = approved
    return approved


# --------------------------------------------------------------------------- #
# Tier 4 — time, expense, drawings, RFIs
# --------------------------------------------------------------------------- #
def create_time_entry(bundle: dict, phase_code="SD", staff_member_id=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_time_entry(
            create_time_entry_payload(
                bundle["phase_ids"][phase_code],
                staff_member_id or bundle["arch_id"],
                **overrides,
            ),
            bundle["pm_headers"],
        )
    )


def submit_time_entry(time_entry_id: str, bundle: dict) -> dict:
    return get_success_data(
        api_client.set_time_entry_state(
            time_entry_id, state_payload("SUBMITTED"), bundle["pm_headers"]
        )
    )


def approve_time_entry(time_entry_id: str, bundle: dict, headers=None) -> dict:
    return get_success_data(
        api_client.set_time_entry_state(
            time_entry_id, state_payload("APPROVED"), headers or bundle["pm_headers"]
        )
    )


def create_approved_time_entry(bundle: dict, phase_code="SD", staff_member_id=None,
                               **overrides) -> dict:
    """Create -> SUBMITTED -> APPROVED in one step. Fires the whole labour rollup cascade."""
    entry = create_time_entry(bundle, phase_code, staff_member_id, **overrides)
    submit_time_entry(entry["id"], bundle)
    return approve_time_entry(entry["id"], bundle)


def create_expense(bundle: dict, staff_member_id=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_expense(
            create_expense_payload(
                bundle["project_id"], staff_member_id or bundle["arch_id"], **overrides
            ),
            bundle["pm_headers"],
        )
    )


def create_approved_expense(bundle: dict, staff_member_id=None, **overrides) -> dict:
    """An APPROVED reimbursable expense joins the unbilled pool the next invoice sweeps."""
    expense = create_expense(bundle, staff_member_id, **overrides)
    return get_success_data(
        api_client.set_expense_state(
            expense["id"], state_payload("APPROVED"), bundle["pm_headers"]
        )
    )


def create_drawing(bundle: dict, phase_code="SD", **overrides) -> dict:
    return get_success_data(
        api_client.create_drawing(
            create_drawing_payload(bundle["phase_ids"][phase_code], **overrides),
            bundle["pm_headers"],
        )
    )


def create_issued_drawing(bundle: dict, phase_code="SD", **overrides) -> dict:
    drawing = create_drawing(bundle, phase_code, **overrides)
    return get_success_data(
        api_client.set_drawing_state(
            drawing["id"], state_payload("ISSUED"), bundle["pm_headers"]
        )
    )


def create_rfi(bundle: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_rfi(
            create_rfi_payload(bundle["project_id"], **overrides), bundle["pm_headers"]
        )
    )


def answer_rfi(rfi_id: str, bundle: dict, answer_text="Mullions at 1500 mm on centre.") -> dict:
    return get_success_data(
        api_client.set_rfi_state(
            rfi_id, state_payload("ANSWERED", answer_text=answer_text), bundle["pm_headers"]
        )
    )


# --------------------------------------------------------------------------- #
# Tier 5 — consultant submittals
# --------------------------------------------------------------------------- #
def setup_project_with_consultant(
    project_number="CON-001",
    capacity=1,
    review_clock_basis="CALENDAR_DAYS",
    submittal_review_period_days=14,
    consultant_overrides=None,
    **kwargs,
) -> dict:
    """Executed project plus a consultant firm, ready to lodge submittals."""
    contract_overrides = dict(kwargs.pop("contract_overrides", None) or {})
    contract_overrides.setdefault("review_clock_basis", review_clock_basis)
    contract_overrides.setdefault("submittal_review_period_days", submittal_review_period_days)

    bundle = setup_executed_project(
        project_number=project_number, contract_overrides=contract_overrides, **kwargs
    )
    firm_kwargs = dict(consultant_overrides or {})
    firm_kwargs.setdefault("concurrent_review_capacity", capacity)
    firm = register_consultant(**firm_kwargs)
    bundle["firm"] = firm
    bundle["firm_id"] = firm["id"]
    bundle["firm_headers"] = make_consultant_rep_headers(firm["id"])
    return bundle


def lodge_submittal(bundle: dict, **overrides) -> dict:
    """A ConsultantRep lodges a submittal for their own firm (ownership-threaded headers)."""
    return get_success_data(
        api_client.create_submittal(
            create_submittal_payload(bundle["project_id"], bundle["firm_id"], **overrides),
            bundle["firm_headers"],
        )
    )


def start_submittal_review(submittal_id: str, bundle: dict) -> dict:
    return get_success_data(
        api_client.set_submittal_state(
            submittal_id, state_payload("UNDER_REVIEW"), bundle["pm_headers"]
        )
    )


def setup_submittal_under_review(bundle: dict, start_at="2026-06-01T09:00:00Z", **overrides) -> dict:
    """Lodge a submittal, set the clock, then start its review so its window is stamped."""
    submittal = lodge_submittal(bundle, **overrides)
    set_clock(start_at)
    return start_submittal_review(submittal["id"], bundle)


# --------------------------------------------------------------------------- #
# Tier 6 — change orders
# --------------------------------------------------------------------------- #
def get_contract_version(bundle: dict) -> int:
    """Re-read the contract to obtain the version the OCC-guarded writes require (PRD §2.5)."""
    contract = get_success_data(api_client.get_contract(bundle["contract_id"], PRINCIPAL))
    bundle["contract"] = contract
    return contract["version"]


def create_change_order(bundle: dict, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_change_order(
            create_change_order_payload(bundle["contract_id"], **overrides),
            headers or bundle["pm_headers"],
        )
    )


def create_submitted_change_order(bundle: dict, headers=None, **overrides) -> dict:
    order = create_change_order(bundle, headers=headers, **overrides)
    return get_success_data(
        api_client.set_change_order_state(
            order["id"], state_payload("SUBMITTED"), headers or bundle["pm_headers"]
        )
    )


def create_client_approved_change_order(bundle: dict, headers=None, **overrides) -> dict:
    order = create_submitted_change_order(bundle, headers=headers, **overrides)
    return get_success_data(
        api_client.set_change_order_state(
            order["id"], state_payload("CLIENT_APPROVED"), bundle["client_headers"]
        )
    )


def create_executed_change_order(bundle: dict, submitter_headers=None,
                                 executor_headers=None, **overrides) -> dict:
    """Draft -> SUBMITTED -> CLIENT_APPROVED -> EXECUTED, honouring segregation of duties."""
    order = create_client_approved_change_order(bundle, headers=submitter_headers, **overrides)
    version = get_contract_version(bundle)
    return get_success_data(
        api_client.execute_change_order(
            order["id"],
            {"expected_contract_version": version},
            executor_headers or PRINCIPAL_B,
        )
    )


# --------------------------------------------------------------------------- #
# Tier 7 — invoicing and settlement
# --------------------------------------------------------------------------- #
def draft_invoice(bundle: dict, period_end="2026-06-30T00:00:00Z", headers=None) -> dict:
    """Re-read the contract for a fresh version, then draft the invoice (PRD §2.5)."""
    version = get_contract_version(bundle)
    return get_success_data(
        api_client.create_invoice(
            create_invoice_payload(bundle["contract_id"], version, period_end=period_end),
            headers or bundle["pm_headers"],
        )
    )


def issue_invoice(invoice_id: str, bundle: dict, headers=None) -> dict:
    return get_success_data(
        api_client.set_invoice_state(
            invoice_id, state_payload("ISSUED"), headers or bundle["pm_headers"]
        )
    )


def draft_and_issue_invoice(bundle: dict, period_end="2026-06-30T00:00:00Z") -> dict:
    invoice = draft_invoice(bundle, period_end=period_end)
    return issue_invoice(invoice["id"], bundle)


def setup_issued_invoice_on_sd_completed(project_number="ISS-001", **kwargs) -> dict:
    """Executed contract, SD COMPLETED, one ISSUED invoice billing the SD fee."""
    bundle = setup_project_with_sd_completed(project_number=project_number, **kwargs)
    bundle["invoice"] = draft_and_issue_invoice(bundle)
    bundle["invoice_id"] = bundle["invoice"]["id"]
    return bundle


def record_payment(invoice_id: str, amount_cents: int) -> dict:
    return get_success_data(
        api_client.record_payment(invoice_id, {"amount_cents": amount_cents}, PRINCIPAL)
    )


# --------------------------------------------------------------------------- #
# Tier 8 — field reports
# --------------------------------------------------------------------------- #
def file_field_report(bundle: dict, deficiency_count=0, **overrides) -> dict:
    """A StaffArchitect files a report for themselves (ownership-threaded headers)."""
    return get_success_data(
        api_client.create_field_report(
            create_field_report_payload(
                bundle["project_id"],
                bundle["arch_id"],
                deficiency_count=deficiency_count,
                **overrides,
            ),
            bundle["arch_headers"],
        )
    )


# --------------------------------------------------------------------------- #
# Read-back helpers
# --------------------------------------------------------------------------- #
def read_project(bundle: dict) -> dict:
    return get_success_data(api_client.get_project(bundle["project_id"], bundle["pm_headers"]))


def read_contract(bundle: dict) -> dict:
    return get_success_data(api_client.get_contract(bundle["contract_id"], bundle["pm_headers"]))


def read_phase(bundle: dict, code: str) -> dict:
    return get_success_data(api_client.get_phase(bundle["phase_ids"][code], bundle["pm_headers"]))


def read_all_phases(bundle: dict) -> list:
    return [read_phase(bundle, code) for code in ("SD", "DD", "CD", "CA")]


def read_time_entry(bundle: dict, time_entry_id: str) -> dict:
    return get_success_data(api_client.get_time_entry(time_entry_id, bundle["pm_headers"]))


def read_expense(bundle: dict, expense_id: str) -> dict:
    return get_success_data(api_client.get_expense(expense_id, bundle["pm_headers"]))


def read_rfi(bundle: dict, rfi_id: str) -> dict:
    return get_success_data(api_client.get_rfi(rfi_id, bundle["pm_headers"]))


def read_submittal(bundle: dict, submittal_id: str) -> dict:
    return get_success_data(api_client.get_submittal(submittal_id, bundle["pm_headers"]))

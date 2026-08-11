"""Non-linear state machine cycles (PRD §3.2, §3.3)."""
from test_helpers import (
    api_client, get_success_data,
    create_active_program, create_contract, begin_negotiation, counter_contract,
    execute_contract, create_change_order, submit_change_order,
    recommend_change_order, decide_change_order,
    pm_headers, owner_headers,
)


def _request_revision(co_id, revision_note, pm_id="pm-1"):
    return get_success_data(api_client.request_revision_change_order(
        co_id, {"revision_note": revision_note}, pm_headers(pm_id)))


def _void(co_id, void_reason, owner_id="owner-1"):
    return get_success_data(api_client.void_change_order(
        co_id, {"void_reason": void_reason}, owner_headers(owner_id)))


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / change_order_revision_cycle_and_override_fork
# ---------------------------------------------------------------------------

def _setup_co_override_scenario():
    prog = create_active_program(
        total_budget_cents=10_000_000, contingency_total_cents=1_000_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 10_000_000}],
        name="P-CO",
    )
    pid = prog["id"]
    ct1 = create_contract(pid, solicitation_estimate_cents=4_500_000,
                           vendor_name="V1", contract_type="CONTRACTOR")
    begin_negotiation(ct1["id"])
    execute_contract(ct1["id"], 4_500_000)
    co1 = create_change_order(ct1["id"], amount_cents=100_000, title="CO1", reason="rev")
    submit_change_order(co1["id"])
    return pid, ct1, co1


def test_co_revision_loop_returns_to_draft_then_under_review(api):
    """PRD §3.3: "Under review, an OwnerRepPM may send the change order back
    UNDER_REVIEW → DRAFT with a request-revision whose payload revision_note is
    recorded on the change order, supporting a reject-rework loop before any
    recommendation exists."

    Design: Difficulty/non_linear_state_machine/change_order_revision_cycle_and_override_fork
    """
    _, _, co1 = _setup_co_override_scenario()
    st1 = _request_revision(co1["id"], "fix scope")
    assert st1["status"] == "DRAFT", f"Expected DRAFT after request-revision, got {st1['status']}"
    assert st1["revision_note"] == "fix scope"
    st2 = submit_change_order(co1["id"])
    assert st2["status"] == "UNDER_REVIEW"


def test_co_owner_override_from_recommend_rejection_runs_cascade_then_void(api):
    """PRD §3.3: "A decision to APPROVE — whether from RECOMMEND_APPROVAL →
    APPROVED or as an owner override from RECOMMEND_REJECTION → APPROVED —
    additionally requires amount_cents to fit within contingency_available_cents
    (else ERR_CONTINGENCY_EXCEEDED, 402), and then runs a four-link approval
    cascade". PRD §3.3: "Voiding runs the mirror-image compensation cascade:
    the contract's current_commitment_cents decreases by the amount".

    Design: Difficulty/non_linear_state_machine/change_order_revision_cycle_and_override_fork
    """
    pid, ct1, co1 = _setup_co_override_scenario()
    recommend_change_order(co1["id"], recommendation="REJECT", analysis_note="too costly")
    # Owner override: APPROVE despite REJECT recommendation
    st = decide_change_order(co1["id"], decision="APPROVE")
    assert st["status"] == "APPROVED", f"Expected APPROVED, got {st['status']}"
    # Cascade link 1: commitment 4_500_000 + 100_000 = 4_600_000
    ct = get_success_data(api_client.get_contract(ct1["id"], pm_headers()))
    assert ct["current_commitment_cents"] == 4_600_000
    # Void runs compensation cascade
    vst = _void(co1["id"], "owner reversed")
    assert vst["status"] == "VOID"
    ct2 = get_success_data(api_client.get_contract(ct1["id"], pm_headers()))
    assert ct2["current_commitment_cents"] == 4_500_000


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / contract_negotiation_counter_cycle
# ---------------------------------------------------------------------------

def _setup_negotiation_scenario():
    prog = create_active_program(
        total_budget_cents=10_000_000, contingency_total_cents=1_000_000,
        lines=[{"cost_code": "CC-100", "amount_cents": 10_000_000}],
        name="P-NEG",
    )
    pid = prog["id"]
    ct1 = create_contract(pid, solicitation_estimate_cents=5_000_000,
                           vendor_name="V1", contract_type="CONTRACTOR")
    begin_negotiation(ct1["id"])
    return pid, ct1


def test_contract_counter_cycle_tracks_rounds_and_latest_amount(api):
    """PRD §3.2: "Each counter move records a round: from UNDER_NEGOTIATION →
    COUNTERED or from COUNTERED → UNDER_NEGOTIATION, with the payload's
    counter_amount_cents replacing latest_counter_amount_cents (null until the
    first counter) and negotiation_rounds (starting at 0) incrementing by 1 on
    every counter."

    Design: Difficulty/non_linear_state_machine/contract_negotiation_counter_cycle
    """
    _, ct1 = _setup_negotiation_scenario()
    s1 = counter_contract(ct1["id"], 4_800_000)
    assert s1["status"] == "COUNTERED" and s1["negotiation_rounds"] == 1
    s2 = counter_contract(ct1["id"], 4_600_000)
    assert s2["status"] == "UNDER_NEGOTIATION" and s2["negotiation_rounds"] == 2
    s3 = counter_contract(ct1["id"], 4_500_000)
    assert s3["status"] == "COUNTERED" and s3["negotiation_rounds"] == 3
    assert s3["latest_counter_amount_cents"] == 4_500_000


def test_contract_execute_from_countered_loop_state(api):
    """PRD §3.2: "An OwnerRepExecutive executes a contract from either
    UNDER_NEGOTIATION → EXECUTED or COUNTERED → EXECUTED, supplying the
    awarded_amount_cents."

    Design: Difficulty/non_linear_state_machine/contract_negotiation_counter_cycle
    """
    _, ct1 = _setup_negotiation_scenario()
    counter_contract(ct1["id"], 4_800_000)
    counter_contract(ct1["id"], 4_600_000)
    counter_contract(ct1["id"], 4_500_000)
    s4 = execute_contract(ct1["id"], 4_500_000)
    assert s4["status"] == "EXECUTED"
    assert s4["awarded_amount_cents"] == 4_500_000
    assert s4["current_commitment_cents"] == 4_500_000
    assert s4["latest_counter_amount_cents"] == 4_500_000

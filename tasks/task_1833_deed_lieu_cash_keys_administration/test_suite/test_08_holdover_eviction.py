"""Holdover escalation and the eviction docket: grace window, filing cascade,
writ/execution, and the dismissal safety valves (PRD §3.5, §3.9)."""
from test_helpers import (
    ApiErrorId,
    assert_eviction_case,
    create_agreement_payload,
    get_agreement,
    get_case,
    get_eviction_case,
    get_loan,
    set_clock,
    setup_case_at_agreement_active,
    setup_escalated_holdover,
    setup_filed_eviction,
    validate_error,
    validate_success,
)


def test_holdover_grace_not_elapsed(api, workout_manager_headers):
    """Escalation is strict-greater than the grace window: on the last grace day
    it is refused; one day later it succeeds.

    PRD §3.9: "Escalation is available while the case is in `AGREEMENT_ACTIVE`, `VACATE_PENDING`, `HANDOVER_INSPECTION`, or `DISBURSEMENT_PENDING`, and only once the current logical date has passed the third day after the accepted agreement's `vacate_date` — the grace window is the vacate date itself plus the three days following it, and escalating before that window has fully elapsed is rejected with `ERR_HOLDOVER_GRACE_NOT_ELAPSED`."

    Design: Corner/validations/holdover_grace_not_elapsed_rejected
    """
    bundle = setup_case_at_agreement_active(loan_number="LN-V12", vacate_date="2026-09-01")
    case_id = bundle["case"]["id"]

    set_clock("2026-09-04T00:00:00Z")  # last grace day (vacate + 3)
    resp = api.escalate_holdover(case_id, workout_manager_headers)
    validate_error(resp, ApiErrorId.ERR_HOLDOVER_GRACE_NOT_ELAPSED.value)
    assert get_case(case_id)["status"] == "AGREEMENT_ACTIVE"

    set_clock("2026-09-05T00:00:00Z")  # grace window fully elapsed
    eviction = validate_success(api.escalate_holdover(case_id, workout_manager_headers), 201)
    assert_eviction_case(eviction)
    assert eviction["status"] == "ESCALATED"
    assert get_case(case_id)["status"] == "HOLDOVER_ESCALATED"


def test_escalate_holdover_creates_eviction_case(api, workout_manager_headers):
    """A valid escalation materializes the EvictionCase (201, ESCALATED, reason
    HOLDOVER) and moves the case.

    PRD §3.9: "Escalation creates an EvictionCase for the case — born `ESCALATED`, its `reason` fixed at `HOLDOVER` — moves the case to `HOLDOVER_ESCALATED`, increments the case's `version`, and answers 201 with the new eviction case."

    Design: Corner/endpoints/escalate_holdover_creates_eviction_case
    """
    bundle = setup_case_at_agreement_active(
        loan_number="LN-P3", program_type="CASH_FOR_KEYS", vacate_date="2026-09-01",
        property_overrides={"occupancy_type": "TENANT_OCCUPIED"},
    )
    case_id = bundle["case"]["id"]
    set_clock("2026-09-05T00:00:00Z")

    eviction = validate_success(api.escalate_holdover(case_id, workout_manager_headers), 201)
    assert_eviction_case(eviction)
    assert eviction["status"] == "ESCALATED"
    assert eviction["reason"] == "HOLDOVER"
    assert eviction["case_id"] == case_id
    assert get_case(case_id)["status"] == "HOLDOVER_ESCALATED"


def test_dismiss_escalated_returns_vacate_pending(api, legal_counsel_headers):
    """Dismissing an ESCALATED (unfiled) docket with OCCUPANT_VACATED loops the
    case back to VACATE_PENDING; the accepted agreement survives.

    PRD §3.9: "Dismissing an `ESCALATED` docket with `OCCUPANT_VACATED` returns the case from `HOLDOVER_ESCALATED` to `VACATE_PENDING` so the handover can proceed; dismissing it with `OTHER` leaves the case in `HOLDOVER_ESCALATED`."

    Design: Corner/state_machines/eviction_dismiss_from_escalated_returns_vacate_pending
    """
    bundle = setup_escalated_holdover(loan_number="LN-S9")
    assert bundle["case"]["status"] == "HOLDOVER_ESCALATED"

    dismissed = validate_success(
        api.dismiss_eviction(bundle["eviction_case"]["id"], {"dismissal_reason": "OCCUPANT_VACATED"},
                             legal_counsel_headers)
    )
    assert dismissed["status"] == "DISMISSED"
    assert get_case(bundle["case"]["id"])["status"] == "VACATE_PENDING"
    assert get_agreement(bundle["agreement"]["id"])["status"] == "ACCEPTED", (
        "pre-filing dismissal must not terminate the agreement"
    )


def test_eviction_full_docket_to_closed_evicted(api, legal_counsel_headers):
    """The full docket: filing is the point of no return (agreement terminated,
    DIL loan to foreclosure), and execution closes the case as CLOSED_EVICTED.

    PRD §3.9: "Filing is the point of no return for the workout: the case moves from `HOLDOVER_ESCALATED` to `EVICTION_IN_PROGRESS`, the accepted agreement is terminated (`ACCEPTED` to `TERMINATED`), every disbursement of the case still `PENDING` or `APPROVED` is voided, and for deed-in-lieu cases the loan moves from `WORKOUT_IN_PROGRESS` to `FORECLOSURE_PROCEEDING`."
    PRD §3.9: "Recording the writ moves the docket from `FILED` to `WRIT_ISSUED`, and recording the execution moves it from `WRIT_ISSUED` to `EVICTED`, closing the case as `CLOSED_EVICTED`."

    Design: Corner/state_machines_workflow_completion/eviction_full_docket_to_closed_evicted
    """
    bundle = setup_escalated_holdover(loan_number="LN-W2")
    eviction_id = bundle["eviction_case"]["id"]

    filed = validate_success(
        api.file_eviction(eviction_id, {"court_reference": "CV-2026-101"}, legal_counsel_headers)
    )
    assert filed["status"] == "FILED"
    assert filed["court_reference"] == "CV-2026-101"
    assert filed["filed_at"] is not None
    # Filing cascade: agreement terminated, loan to foreclosure, case in eviction.
    assert get_agreement(bundle["agreement"]["id"])["status"] == "TERMINATED"
    assert get_loan(bundle["loan"]["id"])["status"] == "FORECLOSURE_PROCEEDING"
    assert get_case(bundle["case"]["id"])["status"] == "EVICTION_IN_PROGRESS"

    writ = validate_success(api.issue_writ(eviction_id, legal_counsel_headers))
    assert writ["status"] == "WRIT_ISSUED"

    evicted = validate_success(api.record_evicted(eviction_id, legal_counsel_headers))
    assert evicted["status"] == "EVICTED"
    assert get_case(bundle["case"]["id"])["status"] == "CLOSED_EVICTED"


def test_eviction_filed_dismiss_cycles_to_terms_negotiation(api, legal_counsel_headers,
                                                            specialist_headers):
    """Dismissing a FILED docket with OCCUPANT_VACATED opens the renegotiation
    cycle: case back to TERMS_NEGOTIATION, DIL loan back to workout, prior
    agreement stays TERMINATED, and a fresh agreement can be drafted.

    PRD §3.9: "Dismissing a `FILED` docket with `OCCUPANT_VACATED` opens the renegotiation cycle: the case moves from `EVICTION_IN_PROGRESS` back to `TERMS_NEGOTIATION`, the prior agreement stays `TERMINATED`, and for deed-in-lieu cases the loan returns from `FORECLOSURE_PROCEEDING` to `WORKOUT_IN_PROGRESS`."

    Design: Corner/state_machines_workflow_completion/eviction_filed_dismiss_cycles_to_terms_negotiation
    """
    bundle = setup_filed_eviction(loan_number="LN-W3", court_reference="CV-2026-102")
    case_id = bundle["case"]["id"]

    dismissed = validate_success(
        api.dismiss_eviction(bundle["eviction_case"]["id"], {"dismissal_reason": "OCCUPANT_VACATED"},
                             legal_counsel_headers)
    )
    assert dismissed["status"] == "DISMISSED"
    case = get_case(case_id)
    assert case["status"] == "TERMS_NEGOTIATION"
    assert get_loan(bundle["loan"]["id"])["status"] == "WORKOUT_IN_PROGRESS"
    assert get_agreement(bundle["agreement"]["id"])["status"] == "TERMINATED", (
        "the terminated agreement is not resurrected"
    )

    # The negotiation cycle restarts: a fresh agreement drafts against the case.
    fresh = validate_success(
        api.create_agreement(
            case_id, create_agreement_payload(case["version"], vacate_date="2026-09-20"), specialist_headers
        ),
        201,
    )
    assert fresh["status"] == "DRAFT"
    assert fresh["vacate_date"] == "2026-09-20"
    assert fresh["round_number"] == 0

"""State-machine behaviours: parallel case axes, the enhancement revision loop,
invalid transitions, terminal lockdown, and cross-entity state dependencies.

Translates queue-A difficulty instances under non_linear_state_machine and
cross_entity_state_dependency, plus queue-B state_machines corner instances.
"""
from test_helpers import (
    validate_success, validate_error, TEST_USERS,
    make_optometrist_headers, make_surgeon_headers, make_patient_headers,
    ApiErrorId,
)
from test_helpers import fixtures as fx

COORD = TEST_USERS["coordinator_headers"]


# ---------------------------------------------------------------------------
# non_linear_state_machine
# ---------------------------------------------------------------------------
def test_case_axes_advance_independently(api):
    """PRD §3.3: "These two axes advance independently: the clinical axis runs
    `PLANNED → SCHEDULED → CONSENTED → OPERATED → HEALED`, while the financial
    axis runs from `UNFUNDED` toward `DEPOSIT_PAID`, `PAID_IN_FULL`, or
    `REFUNDED`."
    PRD §3.4: "an `OPEN` plan is created ... and the case moves to `DEPOSIT_PAID`."
    PRD §3.5: "A successful booking is created with status `ACTIVE`, the case
    advances to `SCHEDULED`".

    Design: Difficulty/non_linear_state_machine/surgery_case_parallel_clinical_financial_axes
    """
    cfg = fx.setup_config()
    case, _ = fx.create_planned_case(cfg["package"]["id"], cfg["optometrist"]["id"], cfg["surgeon"]["id"])
    # Financing flips financial axis, clinical stays PLANNED.
    fx.fund_case_deposit(case["id"], 100000)
    after_fin = validate_success(api.get_case(case["id"], COORD))
    assert after_fin["financial_status"] == "DEPOSIT_PAID"
    assert after_fin["clinical_status"] == "PLANNED"
    # Booking flips clinical axis, financial unchanged.
    fx.create_booking(case["id"], cfg["suite"]["id"], cfg["surgeon"]["id"], after_fin["version"])
    after_book = validate_success(api.get_case(case["id"], COORD))
    assert after_book["financial_status"] == "DEPOSIT_PAID"
    assert after_book["clinical_status"] == "SCHEDULED"


def test_case_scheduled_after_deposit_and_booking(api):
    """PRD §3.5: "Scheduling advances the clinical axis from `PLANNED` to
    `SCHEDULED` by creating an active **suite booking** ... The case must be in
    `PLANNED`, it must be funded — that is, its financial status must be
    `DEPOSIT_PAID` or `PAID_IN_FULL`".

    Design: Difficulty/non_linear_state_machine/surgery_case_parallel_clinical_financial_axes
    """
    ctx = fx.setup_scheduled_case(pay_in_full=False, down_payment_cents=100000)
    assert ctx["case"]["financial_status"] == "DEPOSIT_PAID"
    assert ctx["case"]["clinical_status"] == "SCHEDULED"


def test_enhancement_revision_loop_clears_rescreening(api):
    """PRD §3.8: "From `RE_SCREENING` a `Surgeon` may return the request for
    revision, which clears `re_screening_id` back to null and returns the status
    to `REQUESTED` — this is the cyclic revision loop `RE_SCREENING → REQUESTED
    → RE_SCREENING`."

    Design: Difficulty/non_linear_state_machine/enhancement_request_cyclic_rescreen_revision_loop
    """
    ctx = fx.setup_healed_with_requested_enhancement()
    enh_id = ctx["enhancement"]["id"]
    od = ctx["optometrist"]["id"]
    surg = ctx["surgeon"]["id"]
    validate_success(api.rescreen_enhancement(
        enh_id, {"re_screening_id": ctx["rescreening"]["id"]}, make_optometrist_headers(od),
    ))
    returned = validate_success(api.return_enhancement_for_revision(enh_id, make_surgeon_headers(surg)))
    assert returned["status"] == "REQUESTED"
    assert returned.get("re_screening_id") is None


def test_enhancement_reenters_rescreening_after_revision(api):
    """PRD §3.8: "An `Optometrist` attaches a re-screening, moving the request
    from `REQUESTED` to `RE_SCREENING`: the request must be in `REQUESTED`, it
    must still be within window, and the supplied `re_screening_id` must reference
    an existing candidacy screening belonging to the request's patient; on
    success `re_screening_id` is stored and the status becomes `RE_SCREENING`."

    Design: Difficulty/non_linear_state_machine/enhancement_request_cyclic_rescreen_revision_loop
    """
    ctx = fx.setup_healed_with_requested_enhancement()
    enh_id = ctx["enhancement"]["id"]
    od = ctx["optometrist"]["id"]
    surg = ctx["surgeon"]["id"]
    validate_success(api.rescreen_enhancement(
        enh_id, {"re_screening_id": ctx["rescreening"]["id"]}, make_optometrist_headers(od),
    ))
    validate_success(api.return_enhancement_for_revision(enh_id, make_surgeon_headers(surg)))
    second = validate_success(api.rescreen_enhancement(
        enh_id, {"re_screening_id": ctx["rescreening"]["id"]}, make_optometrist_headers(od),
    ))
    assert second["status"] == "RE_SCREENING"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency
# ---------------------------------------------------------------------------
def test_operate_from_scheduled_without_consent_invalid_state(api):
    """PRD §3.6: "Performing the procedure advances the case from `CONSENTED` to
    `OPERATED` and is a `Surgeon` action. The case must be in `CONSENTED`".
    PRD §2.9: "a transition attempted from a state in which it is not defined is
    rejected with `ERR_INVALID_STATE` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/operate_requires_signed_consent
    """
    ctx = fx.setup_scheduled_case(pay_in_full=True)
    resp = api.operate_case(ctx["case"]["id"], make_surgeon_headers(ctx["surgeon"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    unchanged = validate_success(api.get_case(ctx["case"]["id"], COORD))
    assert unchanged["clinical_status"] == "SCHEDULED"


def test_operate_scheduled_case_does_not_advance(api):
    """PRD §3.6: "Performing the procedure advances the case from `CONSENTED` to
    `OPERATED` and is a `Surgeon` action. The case must be in `CONSENTED`, it
    must have an active suite booking whose `slot_start` is at or before the
    current logical-clock instant, and it must have a signed (not revoked)
    consent form."

    Design: Difficulty/cross_entity_state_dependency/operate_requires_signed_consent
    """
    ctx = fx.setup_scheduled_case(pay_in_full=True)
    api.operate_case(ctx["case"]["id"], make_surgeon_headers(ctx["surgeon"]["id"]))
    still = validate_success(api.get_case(ctx["case"]["id"], COORD))
    assert still["clinical_status"] == "SCHEDULED"
    assert still["surgery_completed_at"] is None


def test_refund_pay_blocked_by_fulfilled_enhancement(api):
    """PRD §3.9: "no fulfilled enhancement request may exist for the origin case
    — because if the center already honored the guarantee through an enhancement,
    it will not also pay cash, so a pay attempt in that situation is refused with
    `ERR_ENHANCEMENT_ALREADY_FULFILLED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/refund_pay_blocked_by_fulfilled_enhancement
    """
    ctx = fx.setup_healed_with_fulfilled_enhancement_and_pending_refund()
    resp = api.adjudicate_refund_claim(ctx["claim"]["id"], {"decision": "PAY"}, COORD)
    validate_error(resp, ApiErrorId.ERR_ENHANCEMENT_ALREADY_FULFILLED)


def test_refund_claim_remains_pending_after_blocked_pay(api):
    """PRD §3.9: "On a successful pay decision the payout is computed and stored
    in `refund_amount_cents`, the claim moves to `PAID`, and the origin case's
    financial status is set to `REFUNDED`."
    PRD §3.9: "a pay attempt in that situation is refused with
    `ERR_ENHANCEMENT_ALREADY_FULFILLED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/refund_pay_blocked_by_fulfilled_enhancement
    """
    ctx = fx.setup_healed_with_fulfilled_enhancement_and_pending_refund()
    api.adjudicate_refund_claim(ctx["claim"]["id"], {"decision": "PAY"}, COORD)
    claim = validate_success(api.get_refund_claim(ctx["claim"]["id"], COORD))
    assert claim["status"] == "PENDING"


# ---------------------------------------------------------------------------
# queue-B state_machines corner instances
# ---------------------------------------------------------------------------
def test_submit_already_submitted_screening_invalid_state(api):
    """PRD §3.2: "**Submitting** a screening moves it from `DRAFT` to
    `SUBMITTED` ... and the screening must currently be in `DRAFT`."
    PRD §2.9: "a transition attempted from a state in which it is not defined is
    rejected with `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/submit_screening_from_submitted_invalid_state
    """
    od = fx.create_optometrist()
    pat = fx.create_patient()
    scr = fx.create_submitted_screening(od["id"], pat["id"])
    resp = api.submit_screening(scr["id"], make_optometrist_headers(od["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_readjudicate_approved_screening_invalid_state(api):
    """PRD §3.3: "**Adjudication** moves a `SUBMITTED` screening to a terminal
    `APPROVED` or `REJECTED` ... The screening must be in `SUBMITTED`."
    PRD §2.9: "a transition attempted from a state in which it is not defined is
    rejected with `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/adjudicate_screening_from_terminal_approved
    """
    od = fx.create_optometrist()
    surg = fx.create_surgeon()
    pat = fx.create_patient()
    scr = fx.create_approved_screening(od["id"], surg["id"], pat["id"])
    resp = api.adjudicate_screening(scr["id"], {"decision": "REJECT"}, make_surgeon_headers(surg["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_reject_screening_marks_patient_ineligible(api):
    """PRD §3.3: "A reject decision moves the screening to `REJECTED` ...
    Additionally, if the patient still has no approved screening, the patient's
    `status` is set to `INELIGIBLE`."

    Design: Corner/state_machines/reject_screening_sets_reason_and_patient_ineligible
    """
    od = fx.create_optometrist()
    surg = fx.create_surgeon()
    pat = fx.create_patient()
    scr = fx.create_submitted_screening(od["id"], pat["id"])
    rejected = validate_success(api.adjudicate_screening(
        scr["id"], {"decision": "REJECT"}, make_surgeon_headers(surg["id"]),
    ))
    assert rejected["status"] == "REJECTED"
    patient = validate_success(api.get_patient(pat["id"], COORD))
    assert patient["status"] == "INELIGIBLE"


def test_return_for_revision_from_requested_invalid_state(api):
    """PRD §3.8: "From `RE_SCREENING` a `Surgeon` may return the request for
    revision, which clears `re_screening_id` back to null and returns the status
    to `REQUESTED`".
    PRD §2.9: "a transition attempted from a state in which it is not defined is
    rejected with `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/enhancement_return_for_revision_from_requested_invalid
    """
    ctx = fx.setup_healed_with_requested_enhancement()
    resp = api.return_enhancement_for_revision(
        ctx["enhancement"]["id"], make_surgeon_headers(ctx["surgeon"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

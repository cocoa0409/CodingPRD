"""Rule-evaluation precedence: which of two simultaneously violated rules answers.

The PRD fixes one strict ascending priority ladder for the whole system, so a
request that breaks several rules at once has exactly one legal answer.  The two
pairs exercised here sit at opposite ends of that ladder: a candidate-state gate
against the case-budget rung that is deliberately last, and the two-physician
segregation-of-duties rule against the donor-consent safety rule.
"""
from test_helpers import (
    ApiErrorId,
    PHYSICIAN_USER_ID,
    SECOND_PHYSICIAN_USER_ID,
    constants as C,
    factories as f,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

BUDGET_TOO_SMALL_CENTS = 1_000_000


def _setup_case_with_physical_cleared_by_first_physician():
    """A workup case for a PBSC-only donor whose PHYSICAL_EXAM passed under md-1.

    The clock is moved onto the canonical clearance instant first, exactly as the
    clinical timeline requires, and only the first clearance item is resulted, so
    the case's clearance dimension is IN_PROGRESS and its method is still
    undecided when the collection-method decision is attempted.
    """
    ctx = fixtures.setup_pipeline(
        "workup_open", donor_overrides={"consented_methods": ["PBSC"]}
    )
    fixtures.set_clock(C.TIMELINE["CLEARANCE_AT"])
    fixtures.result_clearance_item(ctx, "PHYSICAL_EXAM", "PASS")
    return ctx


def test_deferred_candidate_state_pre_empts_patient_budget_on_workup_open(api):
    """PRD §2.9: "Rules are therefore evaluated in a strict ascending priority order, and the **first** violated rule alone decides the response; no later rule can mask or override it."
    PRD §2.9: "Rungs eleven through thirty-two are the state-machine gates, in exactly this order: search not terminal and not stalled (`ERR_SEARCH_ALREADY_TERMINAL`); candidate status admits the operation (`ERR_INVALID_CANDIDATE_STATE`); candidate is the primary (`ERR_CANDIDATE_NOT_PRIMARY`); typing request still open (`ERR_TYPING_REQUEST_NOT_OPEN`); donor available for a passing screening (`ERR_DONOR_NOT_AVAILABLE`); workup case still open (`ERR_WORKUP_CASE_NOT_OPEN`); clearance item not yet resulted (`ERR_CLEARANCE_ITEM_ALREADY_RESULTED`); clearance items resulted in their pinned order (`ERR_CLEARANCE_ORDER_VIOLATION`); method not yet decided (`ERR_METHOD_ALREADY_DECIDED`); method already decided (`ERR_METHOD_NOT_DECIDED`); clearance complete (`ERR_CLEARANCE_NOT_COMPLETE`); booking held (`ERR_BOOKING_NOT_HELD`); booking cancellable (`ERR_BOOKING_NOT_CANCELLABLE`); booking confirmed and unharvested (`ERR_BOOKING_NOT_CONFIRMED`); conditioning already started (`ERR_CONDITIONING_NOT_STARTED`); conditioning action legal from the current conditioning state (`ERR_INVALID_CONDITIONING_ACTION`); conditioning cross-entity precondition met (`ERR_CONDITIONING_PRECONDITION_UNMET`); product delivered (`ERR_PRODUCT_NOT_DELIVERED`); shipment event legal from the shipment's status (`ERR_SHIPMENT_EVENT_NOT_ALLOWED`); claim still provisional (`ERR_CLAIM_NOT_PROVISIONAL`); claim finalizable (`ERR_CLAIM_NOT_FINALIZABLE`); and calendar window manually releasable (`ERR_WINDOW_NOT_RELEASABLE`)."
    PRD §2.9: "And on opening a workup, the budget check is the very last rung, which is why a candidate that is not the primary, or that already has an open case, is reported as such rather than as a budget failure."
    PRD §2.9: "Every other candidate status outside the permitted sets is rejected at the candidate-status rung."
    PRD §3.6: "A provisional reimbursement claim is created in the same breath, raising the patient's `committed_cost_cents` by its total."

    Design: Difficulty/priority_pair_validation_conflict/candidate_state_error_outranks_patient_budget_error_on_workup_open
    """
    ctx = fixtures.setup_pipeline(
        "typing_responded",
        patient_overrides={"case_budget_cents": BUDGET_TOO_SMALL_CENTS},
    )
    # The screening defers the primary, so the candidate rests in DEFERRED while
    # the patient's budget remains far too small to absorb a provisional claim.
    fixtures.advance_to_screening_passed(
        ctx, outcome="DEFER", deferral_type="TEMPORARY", deferral_until="2026-09-30"
    )
    candidate = fixtures.read_candidate(ctx["candidate_id"])
    assert candidate["status"] == "DEFERRED", (
        f"Setup failed: candidate should be DEFERRED, got {candidate['status']}"
    )
    assert candidate["candidate_role"] == "PRIMARY", (
        "Setup failed: with no promotable backup the deferred candidate keeps "
        f"candidate_role PRIMARY, got {candidate['candidate_role']}"
    )

    response = api.open_workup_case(ctx["candidate_id"], ctx["coordinator_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_CANDIDATE_STATE.value)

    after = fixtures.read_candidate(ctx["candidate_id"])
    assert after["status"] == "DEFERRED", (
        f"the rejected open must not move the candidate, got {after['status']}"
    )
    assert after["candidate_role"] == "PRIMARY", (
        f"the rejected open must not re-role the candidate, got {after['candidate_role']}"
    )

    cases, cases_meta = validate_paginated(
        api.list_workup_cases(ctx["candidate_id"], ctx["coordinator_headers"])
    )
    assert cases == [] and cases_meta["total_count"] == 0, (
        f"the rejected open must write no workup case, got {cases_meta['total_count']}"
    )

    patient = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])
    assert patient["committed_cost_cents"] == 0, (
        "no provisional claim exists, so committed_cost_cents must still be 0, got "
        f"{patient['committed_cost_cents']}"
    )


def test_patient_budget_error_fires_once_the_candidate_state_is_clean(api):
    """PRD §3.6: "And the money must be there: the patient's current `committed_cost_cents` plus the total of the provisional claim about to be created must not exceed the patient's `case_budget_cents`, or the open is refused with `ERR_PATIENT_BUDGET_EXCEEDED` (HTTP 402)."
    PRD §3.6: "A provisional reimbursement claim is created in the same breath, raising the patient's `committed_cost_cents` by its total."

    Design: Difficulty/priority_pair_validation_conflict/candidate_state_error_outranks_patient_budget_error_on_workup_open
    """
    # The identical budget, this time against a SCREENING_PASSED primary whose
    # only defect is fiscal: the last rung of the ladder must now answer.
    ctx = fixtures.setup_pipeline(
        "screening_passed",
        patient_overrides={"case_budget_cents": BUDGET_TOO_SMALL_CENTS},
    )
    candidate = fixtures.read_candidate(ctx["candidate_id"])
    assert candidate["status"] == "SCREENING_PASSED", (
        f"Setup failed: candidate should be SCREENING_PASSED, got {candidate['status']}"
    )
    assert candidate["candidate_role"] == "PRIMARY", (
        f"Setup failed: candidate should be PRIMARY, got {candidate['candidate_role']}"
    )

    response = api.open_workup_case(ctx["candidate_id"], ctx["coordinator_headers"])
    validate_error(response, ApiErrorId.ERR_PATIENT_BUDGET_EXCEEDED.value)

    cases, cases_meta = validate_paginated(
        api.list_workup_cases(ctx["candidate_id"], ctx["coordinator_headers"])
    )
    assert cases == [] and cases_meta["total_count"] == 0, (
        f"the refused open must write no workup case, got {cases_meta['total_count']}"
    )

    claims, claims_meta = validate_paginated(
        api.list_reimbursement_claims(
            ctx["operations_headers"], params={"patient_id": ctx["patient_id"]}
        )
    )
    assert claims == [] and claims_meta["total_count"] == 0, (
        f"the refused open must write no claim, got {claims_meta['total_count']}"
    )

    patient = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])
    assert patient["committed_cost_cents"] == 0, (
        "a refused workup open commits no money, got "
        f"{patient['committed_cost_cents']}"
    )
    assert patient["case_budget_cents"] == BUDGET_TOO_SMALL_CENTS, (
        f"the case budget itself is untouched, got {patient['case_budget_cents']}"
    )


def test_segregation_of_duties_pre_empts_the_unconsented_method_error(api):
    """PRD §2.11: "The system enforces that separation mechanically: the `X-User-ID` recorded as `physical_cleared_by_user_id` when a workup case's physical examination passed is barred from authorising that same case's collection method."
    PRD §2.11: "An attempt by that operator is refused with `ERR_SEGREGATION_OF_DUTIES`, regardless of how much else about the request is valid."
    PRD §2.9: "Because segregation of duties sits above every state and safety rule, a physician who tries to authorise the method on a case they personally cleared is told so even when the case would also have failed a later check."
    PRD §3.6: "A passing `PHYSICAL_EXAM` stamps the case's `physical_cleared_by_user_id` with the acting `X-User-ID`, which is the comparand the two-physician rule uses later."
    PRD §3.6: "The first passing result moves the case `PENDING → IN_PROGRESS`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_error_outranks_unconsented_method_error
    """
    ctx = _setup_case_with_physical_cleared_by_first_physician()
    case = fixtures.read_workup_case(ctx["workup_case_id"])
    assert case["physical_cleared_by_user_id"] == PHYSICIAN_USER_ID, (
        "the passing physical examination must stamp the acting physician, got "
        f"{case['physical_cleared_by_user_id']}"
    )
    assert case["clearance_status"] == "IN_PROGRESS", (
        f"one passing item leaves clearance IN_PROGRESS, got {case['clearance_status']}"
    )

    # MARROW is absent from this donor's consented_methods, so the 422 consent
    # rule is armed too — the 403 duty rule sits above it and must answer.
    response = api.decide_collection_method(
        ctx["workup_case_id"],
        f.collection_method_payload(
            method="MARROW", rationale="Marrow harvest preferred by the transplant team"
        ),
        ctx["physician_headers"],
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    after = fixtures.read_workup_case(ctx["workup_case_id"])
    assert after["collection_method"] is None, (
        f"the refused decision stores no method, got {after['collection_method']}"
    )
    assert after["method_decided_by_user_id"] is None, (
        "the refused decision stamps no decider, got "
        f"{after['method_decided_by_user_id']}"
    )
    assert after["logistics_status"] == "UNSCHEDULED", (
        f"the refused decision leaves logistics UNSCHEDULED, got {after['logistics_status']}"
    )
    assert after["clearance_status"] == "IN_PROGRESS", (
        "the method decision never touches the clearance dimension, got "
        f"{after['clearance_status']}"
    )


def test_unconsented_method_is_refused_for_a_second_physician(api):
    """PRD §3.6: "The requested method must be contained in the donor's `consented_methods`, and a method the volunteer never consented to is refused with `ERR_DONOR_METHOD_NOT_CONSENTED`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_error_outranks_unconsented_method_error
    """
    ctx = _setup_case_with_physical_cleared_by_first_physician()
    donor = fixtures.read_donor(ctx["donor_id"])
    assert donor["consented_methods"] == ["PBSC"], (
        f"Setup failed: donor must have consented to PBSC only, got {donor['consented_methods']}"
    )

    # A physician who did not clear the physical passes the duty rule, so the
    # consent rule is now the first violated rung.
    response = api.decide_collection_method(
        ctx["workup_case_id"],
        f.collection_method_payload(
            method="MARROW", rationale="Marrow harvest preferred by the transplant team"
        ),
        ctx["second_physician_headers"],
    )
    validate_error(response, ApiErrorId.ERR_DONOR_METHOD_NOT_CONSENTED.value)

    after = fixtures.read_workup_case(ctx["workup_case_id"])
    assert after["collection_method"] is None, (
        f"the refused decision stores no method, got {after['collection_method']}"
    )
    assert after["method_decided_by_user_id"] is None, (
        "the refused decision stamps no decider, got "
        f"{after['method_decided_by_user_id']}"
    )
    assert after["logistics_status"] == "UNSCHEDULED", (
        f"the refused decision leaves logistics UNSCHEDULED, got {after['logistics_status']}"
    )


def test_consented_method_authorised_by_the_second_physician_succeeds(api):
    """PRD §3.6: "The decision stores `collection_method` and stamps `method_decided_by_user_id` from `X-User-ID`, moves the case `UNSCHEDULED → METHOD_SET` on its logistics dimension, sets `planned_window_days` to 6 for `PBSC` or 8 for `MARROW`, and increments the case's `version` by one — which matters immediately, because that version is what the next booking attempt must quote."
    PRD §3.6: "The two dimensions evolve independently of one another until booking creation couples them by demanding that clearance be complete; a `MedicalDirector` can perfectly well decide the method while clearance is still `IN_PROGRESS`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_error_outranks_unconsented_method_error
    """
    ctx = _setup_case_with_physical_cleared_by_first_physician()
    before = fixtures.read_workup_case(ctx["workup_case_id"])

    response = api.decide_collection_method(
        ctx["workup_case_id"],
        f.collection_method_payload(
            method="PBSC", rationale="Falling back to the consented apheresis method"
        ),
        ctx["second_physician_headers"],
    )
    case = validate_success(response)

    assert case["collection_method"] == "PBSC", (
        f"the consented method must be stored, got {case['collection_method']}"
    )
    assert case["method_decided_by_user_id"] == SECOND_PHYSICIAN_USER_ID, (
        "method_decided_by_user_id must be the deciding physician, got "
        f"{case['method_decided_by_user_id']}"
    )
    assert case["logistics_status"] == "METHOD_SET", (
        f"the decision moves logistics to METHOD_SET, got {case['logistics_status']}"
    )
    assert case["planned_window_days"] == 6, (
        f"PBSC pins planned_window_days at 6, got {case['planned_window_days']}"
    )
    assert case["version"] == before["version"] + 1, (
        f"the decision increments the case version once: expected "
        f"{before['version'] + 1}, got {case['version']}"
    )
    assert case["clearance_status"] == "IN_PROGRESS", (
        "the method may be decided while clearance is still IN_PROGRESS, got "
        f"{case['clearance_status']}"
    )

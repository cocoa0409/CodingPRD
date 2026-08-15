"""Relocation-assistance disbursement: segregation of duties, the remaining-
assistance ceiling, key-delivery gating, release/clawback conservation, and the
program fork at zero remaining (PRD §2.10, §2.11, §3.5, §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    assert_assistance_conservation,
    assert_disbursement,
    assert_same_instant,
    create_disbursement,
    create_disbursement_payload,
    get_agreement,
    get_case,
    get_disbursement,
    get_loan,
    make_disbursement_officer_headers,
    make_specialist_headers,
    setup_case_at_agreement_active,
    setup_case_at_disbursement_pending,
    validate_error,
    validate_paginated,
    validate_success,
)

TWO_MATERIAL_LINES = [
    {"item_code": "CLEANLINESS_FAIL", "severity": "MATERIAL"},
    {"item_code": "DEBRIS_REMOVAL", "severity": "MATERIAL"},
]


def _pending_disbursement(api, loan_number="LN-V4", amount=550000, **kwargs):
    """Case at DISBURSEMENT_PENDING with a fresh PENDING disbursement."""
    bundle = setup_case_at_disbursement_pending(loan_number=loan_number, **kwargs)
    disb = create_disbursement(bundle["case"]["id"], bundle["agreement"]["id"], amount)
    return bundle, disb


def test_sod_approver_equals_requester(api):
    """The officer approving must not be the requester — even wearing the officer
    hat, the same X-User-ID is refused.

    PRD §2.11: "The `DisbursementOfficer` approving a disbursement must not be the person recorded as its requester; a match is rejected with `ERR_SOD_APPROVER_EQUALS_REQUESTER` (HTTP 422)."

    Design: Corner/validations/sod_approver_equals_requester_rejected
    """
    bundle, disb = _pending_disbursement(api, "LN-V4")
    assert disb["requested_by_user_id"] == "spec_1"

    resp = api.approve_disbursement(disb["id"], make_disbursement_officer_headers("spec_1"))
    validate_error(resp, ApiErrorId.ERR_SOD_APPROVER_EQUALS_REQUESTER.value)
    assert get_disbursement(disb["id"])["status"] == "PENDING"


def test_sod_releaser_equals_approver(api):
    """The releasing officer must differ from the approving officer; a third
    party release succeeds.

    PRD §2.11: "The officer releasing an approved disbursement must not be the officer who approved it; a match is rejected with `ERR_SOD_RELEASER_EQUALS_APPROVER` (HTTP 422)."

    Design: Corner/validations/sod_releaser_equals_approver_rejected
    """
    bundle, disb = _pending_disbursement(api, "LN-V5")
    approved = validate_success(api.approve_disbursement(disb["id"], make_disbursement_officer_headers("do_1")))
    assert approved["approved_by_user_id"] == "do_1"

    resp = api.release_disbursement(disb["id"], make_disbursement_officer_headers("do_1"))
    validate_error(resp, ApiErrorId.ERR_SOD_RELEASER_EQUALS_APPROVER.value)
    assert get_disbursement(disb["id"])["status"] == "APPROVED"

    released = validate_success(api.release_disbursement(disb["id"], make_disbursement_officer_headers("do_2")))
    assert released["status"] == "RELEASED"
    assert released["released_by_user_id"] == "do_2"


def test_disbursement_exceeds_remaining_boundary(api, specialist_headers):
    """Fiscal boundary: one cent over remaining fails, zero fails positivity, and
    exactly remaining succeeds.

    PRD §3.7: "The amount must be strictly greater than zero (`ERR_DISBURSEMENT_NOT_POSITIVE`) and must not exceed the case's `remaining_assistance_cents` (`ERR_DISBURSEMENT_EXCEEDS_REMAINING`), the ceiling evaluated last, after the state and positivity checks."

    Design: Corner/validations/disbursement_exceeds_remaining_boundary
    """
    bundle = setup_case_at_disbursement_pending(loan_number="LN-V6")
    case_id = bundle["case"]["id"]
    agreement_id = bundle["agreement"]["id"]
    assert bundle["case"]["remaining_assistance_cents"] == 550000

    resp_over = api.create_disbursement(case_id, create_disbursement_payload(agreement_id, 550001), specialist_headers)
    validate_error(resp_over, ApiErrorId.ERR_DISBURSEMENT_EXCEEDS_REMAINING.value)

    resp_zero = api.create_disbursement(case_id, create_disbursement_payload(agreement_id, 0), specialist_headers)
    validate_error(resp_zero, ApiErrorId.ERR_DISBURSEMENT_NOT_POSITIVE.value)

    exact = validate_success(
        api.create_disbursement(case_id, create_disbursement_payload(agreement_id, 550000), specialist_headers), 201
    )
    assert_disbursement(exact)
    assert exact["status"] == "PENDING" and exact["amount_cents"] == 550000


def test_state_beats_fiscal_error(api, specialist_headers):
    """A disbursement request in AGREEMENT_ACTIVE with an over-ceiling amount
    reports the state error, not the fiscal one — state outranks fiscal.

    PRD §3.7: "Once the case reaches `DISBURSEMENT_PENDING`, the specialist requests a disbursement against it — from any other case state the request is refused with `ERR_CASE_INVALID_STATE`."
    PRD §2.10: "On disbursement creation, the remaining-assistance ceiling is evaluated last, after the state check and the positivity check."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_disbursement_create
    """
    bundle = setup_case_at_agreement_active(loan_number="LN-PP1")
    assert bundle["case"]["status"] == "AGREEMENT_ACTIVE"

    resp = api.create_disbursement(
        bundle["case"]["id"],
        create_disbursement_payload(bundle["agreement"]["id"], 99999999),
        specialist_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE.value)


def test_state_beats_fiscal_no_disbursement_created(api, specialist_headers):
    """The doubly-invalid request leaves no disbursement behind and the case
    stays in AGREEMENT_ACTIVE.

    PRD §3.7: "Once the case reaches `DISBURSEMENT_PENDING`, the specialist requests a disbursement against it — from any other case state the request is refused with `ERR_CASE_INVALID_STATE`."
    PRD §2.10: "On disbursement creation, the remaining-assistance ceiling is evaluated last, after the state check and the positivity check."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_disbursement_create
    """
    bundle = setup_case_at_agreement_active(loan_number="LN-PP1")
    case_id = bundle["case"]["id"]

    resp = api.create_disbursement(
        case_id, create_disbursement_payload(bundle["agreement"]["id"], 99999999), specialist_headers
    )
    validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE.value)

    disbursements = validate_paginated(api.list_case_disbursements(case_id, specialist_headers))[0]
    assert disbursements == [], "no disbursement may persist from the rejected request"
    assert get_case(case_id)["status"] == "AGREEMENT_ACTIVE"


def _keys_zero_bundle(api, loan_number):
    """Case at DISBURSEMENT_PENDING whose passing handover returned zero keys."""
    return setup_case_at_disbursement_pending(
        loan_number=loan_number,
        report_overrides={"broom_clean_verified": True, "keys_returned_count": 0, "line_items": []},
    )


def test_release_requires_keys_returned_error(api):
    """Release is keyed to the physical handover: a passing report with zero keys
    still blocks the release.

    PRD §3.7: "Releasing moves an `APPROVED` disbursement to `RELEASED`, records `released_by_user_id` and the `released_at` logical timestamp, requires a releaser distinct from the approver (`ERR_SOD_RELEASER_EQUALS_APPROVER`), and — keyed to the physical handover — requires the case's `keys_returned` to be true (`ERR_KEYS_NOT_RETURNED`)."
    PRD §3.6: "First, the appointment moves from `SCHEDULED` to `COMPLETED`, and the case moves from `VACATE_PENDING` to `HANDOVER_INSPECTION`, stamping `handover_date` with the logical date at submit and setting `keys_returned` — true exactly when the latest submitted handover report's `keys_returned_count` is greater than zero."

    Design: Difficulty/cross_entity_state_dependency/release_requires_keys_returned
    """
    bundle = _keys_zero_bundle(api, "LN-CS4")
    disb = create_disbursement(bundle["case"]["id"], bundle["agreement"]["id"], 550000)
    validate_success(api.approve_disbursement(disb["id"], make_disbursement_officer_headers("do_1")))

    resp = api.release_disbursement(disb["id"], make_disbursement_officer_headers("do_2"))
    validate_error(resp, ApiErrorId.ERR_KEYS_NOT_RETURNED.value)
    assert get_disbursement(disb["id"])["status"] == "APPROVED", "rejected release must not move the disbursement"


def test_release_requires_keys_case_unchanged(api):
    """After the blocked release the case shows keys_returned false and nothing
    disbursed.

    PRD §3.7: "Releasing moves an `APPROVED` disbursement to `RELEASED`, records `released_by_user_id` and the `released_at` logical timestamp, requires a releaser distinct from the approver (`ERR_SOD_RELEASER_EQUALS_APPROVER`), and — keyed to the physical handover — requires the case's `keys_returned` to be true (`ERR_KEYS_NOT_RETURNED`)."
    PRD §3.7: "A release adds the disbursement's `amount_cents` to the case's `total_disbursed_cents` — the running sum of `amount_cents` over the case's `RELEASED` disbursements — and recomputes `remaining_assistance_cents`."

    Design: Difficulty/cross_entity_state_dependency/release_requires_keys_returned
    """
    bundle = _keys_zero_bundle(api, "LN-CS4")
    case_id = bundle["case"]["id"]
    assert bundle["case"]["keys_returned"] is False

    disb = create_disbursement(case_id, bundle["agreement"]["id"], 550000)
    validate_success(api.approve_disbursement(disb["id"], make_disbursement_officer_headers("do_1")))
    validate_error(api.release_disbursement(disb["id"], make_disbursement_officer_headers("do_2")),
                   ApiErrorId.ERR_KEYS_NOT_RETURNED.value)

    case = get_case(case_id)
    assert case["keys_returned"] is False
    assert case["total_disbursed_cents"] == 0
    assert case["remaining_assistance_cents"] == 550000


def _late_handover_bundle(api, loan_number):
    """Final assistance 475002 after a one-day-late handover with deductions."""
    return setup_case_at_disbursement_pending(
        loan_number=loan_number,
        handover_start="2026-09-05T10:00:00Z",
        handover_end="2026-09-05T11:00:00Z",
        submit_clock="2026-09-05T10:30:00Z",
        report_overrides={"broom_clean_verified": True, "keys_returned_count": 2,
                          "line_items": TWO_MATERIAL_LINES},
    )


def test_release_moves_totals(api, workout_manager_headers):
    """A partial release moves exactly its amount from remaining to disbursed,
    conserving the 475,002 total.

    PRD §3.7: "A release adds the disbursement's `amount_cents` to the case's `total_disbursed_cents` — the running sum of `amount_cents` over the case's `RELEASED` disbursements — and recomputes `remaining_assistance_cents`."

    Design: Difficulty/compensating_invariant/disburse_release_clawback_conserves_assistance
    """
    bundle = _late_handover_bundle(api, "LN-CI1")
    assert bundle["agreement"]["final_assistance_cents"] == 475002

    disb = create_disbursement(bundle["case"]["id"], bundle["agreement"]["id"], 200000)
    validate_success(api.approve_disbursement(disb["id"], make_disbursement_officer_headers("do_1")))
    validate_success(api.release_disbursement(disb["id"], make_disbursement_officer_headers("do_2")))

    case = get_case(bundle["case"]["id"])
    assert case["total_disbursed_cents"] == 200000
    assert case["remaining_assistance_cents"] == 275002
    assert_assistance_conservation(case, 475002)
    assert case["status"] == "DISBURSEMENT_PENDING", "remaining != 0: no fork yet"


def test_clawback_restores_totals(api, workout_manager_headers):
    """The clawback is the compensating action of release: totals return to zero
    disbursed and full remaining.

    PRD §3.7: "A `WorkoutManager` may claw back a `RELEASED` disbursement, moving it to `CLAWED_BACK` and subtracting its `amount_cents` from the case's `total_disbursed_cents`, with `remaining_assistance_cents` recomputed — the compensating action of release under the assistance-conservation invariant (INV-ASSISTANCE)."

    Design: Difficulty/compensating_invariant/disburse_release_clawback_conserves_assistance
    """
    bundle = _late_handover_bundle(api, "LN-CI1")
    disb = create_disbursement(bundle["case"]["id"], bundle["agreement"]["id"], 200000)
    validate_success(api.approve_disbursement(disb["id"], make_disbursement_officer_headers("do_1")))
    validate_success(api.release_disbursement(disb["id"], make_disbursement_officer_headers("do_2")))

    clawed = validate_success(api.clawback_disbursement(disb["id"], workout_manager_headers))
    assert clawed["status"] == "CLAWED_BACK"

    case = get_case(bundle["case"]["id"])
    assert case["total_disbursed_cents"] == 0
    assert case["remaining_assistance_cents"] == 475002
    assert_assistance_conservation(case, 475002)
    assert case["status"] == "DISBURSEMENT_PENDING"


def test_immediate_consistency_on_release(api, specialist_headers):
    """The release response itself carries RELEASED with its logical timestamp,
    and a same-instant read of the case already shows the completed CFK fork.

    PRD §3.7: "Releasing moves an `APPROVED` disbursement to `RELEASED`, records `released_by_user_id` and the `released_at` logical timestamp, requires a releaser distinct from the approver (`ERR_SOD_RELEASER_EQUALS_APPROVER`), and — keyed to the physical handover — requires the case's `keys_returned` to be true (`ERR_KEYS_NOT_RETURNED`)."
    PRD §3.7: "When a release brings `remaining_assistance_cents` to zero and keys have been returned, a deed-in-lieu case advances automatically from `DISBURSEMENT_PENDING` to `RECORDING_PENDING`, while a cash-for-keys case completes outright: the case moves to `COMPLETED`, its agreement moves from `ACCEPTED` to `COMPLETED`, the loan moves from `WORKOUT_IN_PROGRESS` to `DEED_IN_LIEU_COMPLETED` with `servicing_system_synced` set to true, and the versions of case and loan increment."

    Design: Corner/consistency_model/immediate_consistency_on_release
    """
    bundle = setup_case_at_disbursement_pending(loan_number="LN-M1", program_type="CASH_FOR_KEYS")
    disb = create_disbursement(bundle["case"]["id"], bundle["agreement"]["id"], 550000)
    validate_success(api.approve_disbursement(disb["id"], make_disbursement_officer_headers("do_1")))

    released = validate_success(api.release_disbursement(disb["id"], make_disbursement_officer_headers("do_2")))
    assert released["status"] == "RELEASED"
    assert_same_instant(released["released_at"], "2026-09-01T10:30:00Z", "released_at")

    case = get_case(bundle["case"]["id"])
    assert case["total_disbursed_cents"] == 550000, "immediate read must reflect the release"
    assert case["status"] == "COMPLETED", "CFK zero-remaining fork fires within the release request"


def test_dil_branch_routes_to_recording(api):
    """At zero remaining with keys returned, the DEED_IN_LIEU fork routes the case
    to RECORDING_PENDING and the loan keeps working out.

    PRD §3.7: "When a release brings `remaining_assistance_cents` to zero and keys have been returned, a deed-in-lieu case advances automatically from `DISBURSEMENT_PENDING` to `RECORDING_PENDING`, while a cash-for-keys case completes outright: the case moves to `COMPLETED`, its agreement moves from `ACCEPTED` to `COMPLETED`, the loan moves from `WORKOUT_IN_PROGRESS` to `DEED_IN_LIEU_COMPLETED` with `servicing_system_synced` set to true, and the versions of case and loan increment."

    Design: Difficulty/non_linear_state_machine/case_program_branch_divergence
    """
    bundle = setup_case_at_disbursement_pending(loan_number="LN-BR1", program_type="DEED_IN_LIEU")
    disb = create_disbursement(bundle["case"]["id"], bundle["agreement"]["id"], 550000)
    validate_success(api.approve_disbursement(disb["id"], make_disbursement_officer_headers("do_1")))
    validate_success(api.release_disbursement(disb["id"], make_disbursement_officer_headers("do_2")))

    assert get_case(bundle["case"]["id"])["status"] == "RECORDING_PENDING"
    assert get_loan(bundle["loan"]["id"])["status"] == "WORKOUT_IN_PROGRESS", (
        "the DIL loan awaits deed recordation"
    )


def test_cfk_branch_completes_outright(api, specialist_headers):
    """The same trigger completes a CASH_FOR_KEYS case outright: case, agreement,
    and loan all land in their completed states and no waiver ever existed.

    PRD §3.7: "When a release brings `remaining_assistance_cents` to zero and keys have been returned, a deed-in-lieu case advances automatically from `DISBURSEMENT_PENDING` to `RECORDING_PENDING`, while a cash-for-keys case completes outright: the case moves to `COMPLETED`, its agreement moves from `ACCEPTED` to `COMPLETED`, the loan moves from `WORKOUT_IN_PROGRESS` to `DEED_IN_LIEU_COMPLETED` with `servicing_system_synced` set to true, and the versions of case and loan increment."
    PRD §3.8: "Deed-in-lieu cases carry a deficiency waiver, created in `DRAFT` status at the moment the agreement is accepted (§3.5)."

    Design: Difficulty/non_linear_state_machine/case_program_branch_divergence
    """
    bundle = setup_case_at_disbursement_pending(loan_number="LN-BR2", program_type="CASH_FOR_KEYS")
    disb = create_disbursement(bundle["case"]["id"], bundle["agreement"]["id"], 550000)
    validate_success(api.approve_disbursement(disb["id"], make_disbursement_officer_headers("do_1")))
    validate_success(api.release_disbursement(disb["id"], make_disbursement_officer_headers("do_2")))

    assert get_case(bundle["case"]["id"])["status"] == "COMPLETED"
    assert get_agreement(bundle["agreement"]["id"])["status"] == "COMPLETED"
    loan = get_loan(bundle["loan"]["id"])
    assert loan["status"] == "DEED_IN_LIEU_COMPLETED"
    assert loan["servicing_system_synced"] is True
    waivers = validate_paginated(api.list_case_deficiency_waivers(bundle["case"]["id"], specialist_headers))[0]
    assert waivers == [], "no deficiency waiver exists for cash-for-keys"


def test_specialist_cannot_approve_disbursement(api, specialist_2_headers):
    """Approve is exclusive to the DisbursementOfficer role; a specialist is
    refused at the authorization rung.

    PRD §2.1: "A request whose role is not among the roles authorized for the endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.7: "Approval and release belong to the `DisbursementOfficer` under the segregation-of-duties rules of §2.11."

    Design: Corner/rbac/specialist_cannot_approve_disbursement
    """
    bundle, disb = _pending_disbursement(api, "LN-RB2")
    resp = api.approve_disbursement(disb["id"], specialist_2_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
    assert get_disbursement(disb["id"])["status"] == "PENDING"

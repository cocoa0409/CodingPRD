"""Treatment-plan and evaluation workflow: the revision loop, the
approve-bubbles-client cascade, the finalized-evaluation gate on plan submit,
ownership gating, and invalid-state review."""
from test_helpers import (
    get_success_data,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_bcba_headers,
    create_payer,
    create_bcba,
    create_client,
    create_finalized_evaluation,
    factories,
)


def _submitted_plan(api, assessment_score=70):
    """Reach a SUBMITTED plan: full chain through plan submit (not yet reviewed)."""
    payer = create_payer(api)
    bcba = create_bcba(api)
    client = create_client(api, insurance_payer_id=payer["id"])
    ev = create_finalized_evaluation(api, client["id"], bcba["id"], assessment_score)
    bcba_h = make_bcba_headers(bcba["id"])
    plan = get_success_data(
        api.create_plan(
            factories.create_plan_payload(client["id"], ev["id"], bcba["id"]),
            bcba_h,
        )
    )
    get_success_data(api.submit_plan(plan["id"], bcba_h))
    return {"payer": payer, "bcba": bcba, "client": client, "plan": plan,
            "bcba_h": bcba_h}


# ─── Difficulty: revision loop SUBMITTED -> REVISION_REQUESTED -> SUBMITTED ───

def test_plan_review_request_revision_sets_revision_requested(api):
    """PRD §3.3: "A decision of `REQUEST_REVISION` moves the plan from
    `SUBMITTED` to `REVISION_REQUESTED`."

    Design: Difficulty/non_linear_state_machine/treatment_plan_revision_cycle_submitted_revision_submitted
    """
    sc = _submitted_plan(api)
    data = get_success_data(
        api.review_plan(sc["plan"]["id"], "REQUEST_REVISION",
                        TEST_USERS["intake_headers"])
    )
    assert data["status"] == "REVISION_REQUESTED", data["status"]


def test_plan_resubmit_after_revision_returns_to_submitted(api):
    """PRD §3.3: "The revision loop lets a plan recover from a revision request: a
    plan in `REVISION_REQUESTED` may be resubmitted by its author, returning it to
    `SUBMITTED`, where it can again be approved or sent back for revision."

    Design: Difficulty/non_linear_state_machine/treatment_plan_revision_cycle_submitted_revision_submitted
    """
    sc = _submitted_plan(api)
    get_success_data(
        api.review_plan(sc["plan"]["id"], "REQUEST_REVISION",
                        TEST_USERS["intake_headers"])
    )
    data = get_success_data(api.submit_plan(sc["plan"]["id"], sc["bcba_h"]))
    assert data["status"] == "SUBMITTED", (
        f"expected loop back into SUBMITTED, got {data['status']}"
    )


# ─── Difficulty: approve bubbles client INTAKE -> ACTIVE (depth 2) ────────────

def test_plan_approve_transitions_plan_to_approved(api):
    """PRD §3.3: "A decision of `APPROVE` moves the plan from `SUBMITTED` to
    `APPROVED`".

    Design: Difficulty/transitive_cascade/approve_plan_bubbles_client_active_depth2
    """
    sc = _submitted_plan(api)
    data = get_success_data(
        api.review_plan(sc["plan"]["id"], "APPROVE", TEST_USERS["intake_headers"])
    )
    assert data["status"] == "APPROVED", data["status"]


def test_plan_approve_bubbles_client_to_active(api):
    """PRD §3.3: "as a side effect, if the covered client is still in `INTAKE`, the
    client's status bubbles up to `ACTIVE`, and any prior `APPROVED` plan for the
    same client is retired."

    Design: Difficulty/transitive_cascade/approve_plan_bubbles_client_active_depth2
    """
    sc = _submitted_plan(api)
    assert sc["client"]["status"] == "INTAKE"
    get_success_data(
        api.review_plan(sc["plan"]["id"], "APPROVE", TEST_USERS["intake_headers"])
    )
    client = get_success_data(
        api.get_client(sc["client"]["id"], TEST_USERS["intake_headers"])
    )
    assert client["status"] == "ACTIVE", (
        f"expected client bubbled to ACTIVE, got {client['status']}"
    )


# ─── Difficulty: plan submit requires FINALIZED backing evaluation ───────────

def test_plan_submit_with_submitted_evaluation_rejected(api):
    """PRD §3.3: "the backing evaluation must already be `FINALIZED`; if it is in
    any other state the submission is rejected with `ERR_EVALUATION_NOT_FINALIZED`."

    Design: Difficulty/cross_entity_state_dependency/plan_submit_requires_finalized_evaluation
    """
    payer = create_payer(api)
    bcba = create_bcba(api)
    client = create_client(api, insurance_payer_id=payer["id"])
    bcba_h = make_bcba_headers(bcba["id"])
    ev = get_success_data(
        api.create_evaluation(
            factories.create_evaluation_payload(client["id"], bcba["id"], 70), bcba_h
        )
    )
    get_success_data(api.submit_evaluation(ev["id"], bcba_h))  # SUBMITTED, not FINALIZED
    plan = get_success_data(
        api.create_plan(
            factories.create_plan_payload(client["id"], ev["id"], bcba["id"]), bcba_h
        )
    )
    resp = api.submit_plan(plan["id"], bcba_h)
    validate_error(resp, ApiErrorId.ERR_EVALUATION_NOT_FINALIZED.value, 409)


def test_evaluation_stays_submitted_blocks_plan_submit(api):
    """PRD §3.3: "the backing evaluation must already be `FINALIZED`; if it is in
    any other state the submission is rejected with `ERR_EVALUATION_NOT_FINALIZED`."

    Design: Difficulty/cross_entity_state_dependency/plan_submit_requires_finalized_evaluation
    """
    payer = create_payer(api)
    bcba = create_bcba(api)
    client = create_client(api, insurance_payer_id=payer["id"])
    bcba_h = make_bcba_headers(bcba["id"])
    ev = get_success_data(
        api.create_evaluation(
            factories.create_evaluation_payload(client["id"], bcba["id"], 70), bcba_h
        )
    )
    get_success_data(api.submit_evaluation(ev["id"], bcba_h))
    fetched = get_success_data(api.get_evaluation(ev["id"], bcba_h))
    assert fetched["status"] == "SUBMITTED", fetched["status"]
    plan = get_success_data(
        api.create_plan(
            factories.create_plan_payload(client["id"], ev["id"], bcba["id"]), bcba_h
        )
    )
    resp = api.submit_plan(plan["id"], bcba_h)
    validate_error(resp, ApiErrorId.ERR_EVALUATION_NOT_FINALIZED.value, 409)


# ─── Corner: ownership and invalid-state ─────────────────────────────────────

def test_non_owner_bcba_cannot_submit_evaluation(api):
    """PRD §3.2: "only the provider identified as the `evaluator_bcba_id` may do
    so; an attempt by anyone else is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/validations/not_resource_owner_on_evaluation_submit
    """
    payer = create_payer(api)
    bcba_a = create_bcba(api, full_name="Owner BCBA A")
    bcba_b = create_bcba(api, full_name="Other BCBA B")
    client = create_client(api, insurance_payer_id=payer["id"])
    ev = get_success_data(
        api.create_evaluation(
            factories.create_evaluation_payload(client["id"], bcba_a["id"], 70),
            make_bcba_headers(bcba_a["id"]),
        )
    )
    resp = api.submit_evaluation(ev["id"], make_bcba_headers(bcba_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)


def test_review_draft_evaluation_rejected_as_invalid_state(api):
    """PRD §3.10: "a request to drive a transition that the resource's current
    state does not permit is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/review_evaluation_from_draft_returns_invalid_state
    """
    payer = create_payer(api)
    bcba = create_bcba(api)
    client = create_client(api, insurance_payer_id=payer["id"])
    ev = get_success_data(
        api.create_evaluation(
            factories.create_evaluation_payload(client["id"], bcba["id"], 70),
            make_bcba_headers(bcba["id"]),
        )
    )
    resp = api.review_evaluation(ev["id"], "FINALIZE", TEST_USERS["intake_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

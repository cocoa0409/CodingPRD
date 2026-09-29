"""Lien waivers: the second state axis, and what actually releases the money."""

from test_helpers import (
    ApiErrorId,
    assert_lien_waiver,
    assert_money_equals,
    assert_project_ledger_invariants,
    only_lien_waiver,
    read_cost_entry,
    read_draw_request,
    read_lien_waiver,
    read_project,
    receive_waiver,
    setup_single_trade_draw_awaiting_verification,
    setup_submitted_draw,
    setup_two_trade_draw_conditionally_approved,
    validate_error,
    validate_success,
)


def test_draw_axes_hold_different_values_after_a_single_verification(api):
    """PRD §3.7: "A draw request carries two independent state dimensions. The funding axis —
    the draw's `status` — tracks what the lender has decided. The waiver axis — the draw's
    `waiver_compliance` — tracks whether the trades have signed their releases, and it evolves
    entirely without regard to the funding axis."
    PRD §3.7: "The edge `PENDING → PARTIAL` fires when the count of verified waivers is strictly
    greater than zero and strictly less than `required_waiver_count`; this edge sets
    `verified_waiver_count` and pointedly does not touch the draw's `status`."

    Design: Difficulty/non_linear_state_machine/draw_status_and_waiver_compliance_advance_independently
    """
    ctx = setup_two_trade_draw_conditionally_approved()
    receive_waiver(
        ctx,
        ctx["waiver_frame"]["id"],
        ctx["sub_frame_headers"],
        waiver_type="CONDITIONAL_PROGRESS",
        amount_covered=10000.10,
        signed_document_ref="waiver-frame-001",
    )

    verified = validate_success(
        api.review_lien_waiver(
            ctx["waiver_frame"]["id"], {"decision": "VERIFY"}, ctx["controller_a_headers"]
        ),
        200,
    )

    assert verified["status"] == "VERIFIED"
    draw = read_draw_request(ctx["draw"]["id"])
    assert draw["status"] == "CONDITIONALLY_APPROVED"
    assert draw["waiver_compliance"] == "PARTIAL"
    assert draw["required_waiver_count"] == 2
    assert draw["verified_waiver_count"] == 1


def test_partially_released_draw_does_not_fund(api):
    """PRD §3.7: "A draw can be `CONDITIONALLY_APPROVED` with `waiver_compliance` still
    `PENDING`, and it can sit in `LENDER_REVIEW` with `waiver_compliance` already `COMPLETE`.
    Money moves only when both axes agree."
    PRD §3.6: "When a draw reaches `FUNDED`, `funded_at` is stamped with the logical clock now,
    the project's `funded_to_date` and `retainage_held` are recomputed, every cost entry the
    draw holds advances `INCLUDED_IN_DRAW → PAID`, and the project's `pending_draw_amount` and
    `eligible_cost_pool` are recomputed."

    Design: Difficulty/non_linear_state_machine/draw_status_and_waiver_compliance_advance_independently
    """
    ctx = setup_two_trade_draw_conditionally_approved()
    receive_waiver(
        ctx,
        ctx["waiver_frame"]["id"],
        ctx["sub_frame_headers"],
        waiver_type="CONDITIONAL_PROGRESS",
        amount_covered=10000.10,
        signed_document_ref="waiver-frame-001",
    )
    validate_success(
        api.review_lien_waiver(
            ctx["waiver_frame"]["id"], {"decision": "VERIFY"}, ctx["controller_a_headers"]
        ),
        200,
    )

    draw = read_draw_request(ctx["draw"]["id"])
    assert draw["funded_at"] is None

    project = read_project(ctx["project"]["id"])
    assert_money_equals(project["funded_to_date"], 0.00, "funded_to_date")
    assert_money_equals(project["pending_draw_amount"], 45000.30, "pending_draw_amount")
    assert_project_ledger_invariants(project)


def test_final_waiver_verification_funds_the_draw(api):
    """PRD §3.7: "A successful verification stamps `verified_at` with the logical clock now and
    sets off a four-link cascade that is the single most consequential chain in the system:
    because this waiver became `VERIFIED`, the parent draw recomputes `verified_waiver_count`
    and advances its `waiver_compliance`; because `waiver_compliance` reached `COMPLETE` while
    the draw's `status` was `CONDITIONALLY_APPROVED`, the draw auto-advances to `FUNDED` and the
    project's `funded_to_date`, `retainage_held`, and `pending_draw_amount` are recomputed; and
    because the draw reached `FUNDED`, every cost entry it holds advances `INCLUDED_IN_DRAW →
    PAID` and leaves the project's `eligible_cost_pool`."

    Design: Difficulty/transitive_cascade/waiver_verification_cascades_to_draw_funding_and_cost_payment
    """
    ctx = setup_single_trade_draw_awaiting_verification()

    verified = validate_success(
        api.review_lien_waiver(
            ctx["waiver"]["id"], {"decision": "VERIFY"}, ctx["controller_a_headers"]
        ),
        200,
    )

    assert verified["status"] == "VERIFIED"
    draw = read_draw_request(ctx["draw"]["id"])
    assert draw["waiver_compliance"] == "COMPLETE"
    assert draw["status"] == "FUNDED"

    project = read_project(ctx["project"]["id"])
    assert_money_equals(project["funded_to_date"], 42750.27, "funded_to_date")
    assert_money_equals(project["retainage_held"], 2250.03, "retainage_held")
    assert_money_equals(project["pending_draw_amount"], 0.00, "pending_draw_amount")


def test_funding_pays_every_cost_entry_the_draw_holds(api):
    """PRD §3.5: "Only when the draw actually funds does an entry advance `INCLUDED_IN_DRAW →
    PAID`, stamping `paid_at` with the logical clock now; that is the single moment the amount
    leaves `eligible_cost_pool`, while `cost_to_date` is deliberately left unchanged because the
    money was spent regardless of who has reimbursed it."
    PRD §2.6: "`cost_to_date` is the sum of `amount` across the project's cost entries whose
    status is `APPROVED`, `INCLUDED_IN_DRAW`, or `PAID`, rounded half up to two decimal places;
    `PENDING` and `REJECTED` entries never contribute."

    Design: Difficulty/transitive_cascade/waiver_verification_cascades_to_draw_funding_and_cost_payment
    """
    ctx = setup_single_trade_draw_awaiting_verification()

    validate_success(
        api.review_lien_waiver(
            ctx["waiver"]["id"], {"decision": "VERIFY"}, ctx["controller_a_headers"]
        ),
        200,
    )

    for entry in ctx["cost_entries"]:
        assert read_cost_entry(entry["id"])["status"] == "PAID"

    project = read_project(ctx["project"]["id"])
    assert_money_equals(project["eligible_cost_pool"], 0.00, "eligible_cost_pool")
    assert_money_equals(project["cost_to_date"], 45000.30, "cost_to_date")
    assert_project_ledger_invariants(project)


def test_rejected_release_can_be_re_signed_and_counts_the_resubmission(api):
    """PRD §3.7: "The same operation is how a trade answers a rejection: it also advances
    `REJECTED → RECEIVED`, overwriting `waiver_type`, `through_date`, `amount_covered`, and
    `signed_document_ref` with the new submission, re-stamping `received_at`, and incrementing
    `resubmit_count` by one."
    PRD §3.7: "Rejecting instead advances `RECEIVED → REJECTED`, stamps `rejected_at` with the
    logical clock now, and deliberately leaves the parent draw's `waiver_compliance` exactly
    where it was."

    Design: Corner/state_machines/lien_waiver_rejection_then_resubmission_increments_resubmit_count
    """
    ctx = setup_submitted_draw(
        lines=[{"amount": 10000.10, "incurred_at": "2026-08-10T00:00:00.000Z"}]
    )
    waiver = only_lien_waiver(ctx["draw"]["id"])
    receive_waiver(
        ctx,
        waiver["id"],
        ctx["sub_frame_headers"],
        amount_covered=10000.10,
        signed_document_ref="waiver-001",
    )
    validate_success(
        api.review_lien_waiver(
            waiver["id"], {"decision": "REJECT"}, ctx["controller_a_headers"]
        ),
        200,
    )

    resubmitted = validate_success(
        api.receive_lien_waiver(
            waiver["id"],
            {
                "waiver_type": "CONDITIONAL_PROGRESS",
                "through_date": "2026-08-31T00:00:00.000Z",
                "amount_covered": 10000.10,
                "signed_document_ref": "waiver-001-rev-b",
            },
            ctx["sub_frame_headers"],
        ),
        200,
    )

    assert_lien_waiver(resubmitted)
    assert resubmitted["status"] == "RECEIVED"
    assert resubmitted["resubmit_count"] == 1
    assert resubmitted["signed_document_ref"] == "waiver-001-rev-b"
    assert resubmitted["required_waiver_type"] == "CONDITIONAL_PROGRESS"
    assert_money_equals(resubmitted["required_amount"], 10000.10, "required_amount")

    draw = read_draw_request(ctx["draw"]["id"])
    assert draw["waiver_compliance"] == "PENDING"
    assert draw["verified_waiver_count"] == 0
    assert_money_equals(draw["requested_amount"], 10000.10, "requested_amount")
    assert_money_equals(draw["retainage_amount"], 500.01, "retainage_amount")
    assert_money_equals(draw["net_funding_amount"], 9500.09, "net_funding_amount")


def test_waiver_signed_on_the_wrong_form_is_refused(api):
    """PRD §3.7: "Verifying advances `RECEIVED → VERIFIED` and demands two things of the
    paperwork: the signed `waiver_type` must equal the `required_waiver_type` the draw demanded
    of that trade, failing which the verification is refused with `ERR_WAIVER_TYPE_MISMATCH`;
    and the signed `amount_covered` must be at least the waiver's `required_amount`, failing
    which it is refused with `ERR_WAIVER_AMOUNT_INSUFFICIENT`."
    PRD §3.6: "For every distinct `subcontractor_id` among the included entries whose trade
    record has `waiver_required` set to true, the server creates one lien waiver in `REQUESTED`,
    with its `required_waiver_type` set to `CONDITIONAL_PROGRESS` when the project is
    `UNDER_CONSTRUCTION` and to `UNCONDITIONAL_FINAL` when the project has reached
    `SUBSTANTIAL_COMPLETION`, and its `required_amount` set to that trade's included total;
    `required_waiver_count` records how many were created."

    Design: Corner/errors/waiver_signed_with_wrong_form_returns_type_mismatch
    """
    ctx = setup_submitted_draw(
        lines=[{"amount": 10000.10, "incurred_at": "2026-08-10T00:00:00.000Z"}]
    )
    waiver = only_lien_waiver(ctx["draw"]["id"])
    receive_waiver(
        ctx,
        waiver["id"],
        ctx["sub_frame_headers"],
        waiver_type="UNCONDITIONAL_FINAL",
        amount_covered=10000.10,
        signed_document_ref="waiver-wrong-form",
    )

    response = api.review_lien_waiver(
        waiver["id"], {"decision": "VERIFY"}, ctx["controller_a_headers"]
    )
    validate_error(response, ApiErrorId.ERR_WAIVER_TYPE_MISMATCH, 422)

    stored = read_lien_waiver(waiver["id"])
    assert stored["required_waiver_type"] == "CONDITIONAL_PROGRESS"
    assert stored["status"] == "RECEIVED"

    draw = read_draw_request(ctx["draw"]["id"])
    assert draw["waiver_compliance"] == "PENDING"
    assert draw["status"] == "LENDER_REVIEW"


def test_waiver_covering_less_than_the_required_amount_is_refused(api):
    """PRD §3.7: "Verifying advances `RECEIVED → VERIFIED` and demands two things of the
    paperwork: the signed `waiver_type` must equal the `required_waiver_type` the draw demanded
    of that trade, failing which the verification is refused with `ERR_WAIVER_TYPE_MISMATCH`;
    and the signed `amount_covered` must be at least the waiver's `required_amount`, failing
    which it is refused with `ERR_WAIVER_AMOUNT_INSUFFICIENT`."

    Design: Corner/errors/waiver_covering_less_than_required_returns_amount_insufficient
    """
    ctx = setup_submitted_draw(
        lines=[{"amount": 10000.10, "incurred_at": "2026-08-10T00:00:00.000Z"}]
    )
    waiver = only_lien_waiver(ctx["draw"]["id"])
    receive_waiver(
        ctx,
        waiver["id"],
        ctx["sub_frame_headers"],
        waiver_type="CONDITIONAL_PROGRESS",
        amount_covered=9000.00,
        signed_document_ref="waiver-short",
    )

    response = api.review_lien_waiver(
        waiver["id"], {"decision": "VERIFY"}, ctx["controller_a_headers"]
    )
    validate_error(response, ApiErrorId.ERR_WAIVER_AMOUNT_INSUFFICIENT, 422)

    stored = read_lien_waiver(waiver["id"])
    assert_money_equals(stored["required_amount"], 10000.10, "required_amount")
    assert stored["status"] == "RECEIVED"
    assert read_draw_request(ctx["draw"]["id"])["verified_waiver_count"] == 0

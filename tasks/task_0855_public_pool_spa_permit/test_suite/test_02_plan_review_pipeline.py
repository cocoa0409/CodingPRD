"""Plan review submission, correction rounds, revisions and issuance gating."""

from test_helpers import (
    ADMIN,
    PLAN_REVIEWER,
    PLAN_REVIEWER_ONE_ID,
    ApiErrorId,
    advance_permit_to_under_review,
    apply_for_permit,
    approve_plan_review,
    drive_plan_review_to_corrections_required,
    fee_balance,
    file_plan_revision,
    pay_operator_balance,
    read_operator,
    read_permit,
    read_plan_review,
    setup_operator_and_pool,
    setup_plan_review_chain,
    start_plan_review,
    submit_plan_review,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_plan_review_disapproval_denies_the_dependent_permit_application(api):
    """PRD 3.2: **Disapproving** advances `UNDER_REVIEW → DISAPPROVED` and
    likewise sets `decided_at` and `decided_by_user_id` — but it also cascades:
    every permit application that relies on this review and is currently in
    `DRAFT`, `SUBMITTED` or `UNDER_REVIEW` is moved to `DENIED`.
    PRD 3.2: Submission is not free: it immediately posts a ledger entry of
    `entry_type` `PLAN_REVIEW_FEE` for a positive 25000 cents — two hundred and
    fifty dollars — against the owning operator with a null `permit_id`, and
    refreshes that operator's `fee_balance_cents`.

    Design: Corner/state_machines/plan_review_disapproval_denies_dependent_permit_application
    """
    ctx = setup_operator_and_pool()
    review = submit_plan_review(
        ctx["facility_id"], ctx["op_headers"], project_type="ALTERATION",
        drawing_reference="DR-2026-021",
    )
    permit = apply_for_permit(
        ctx["facility_id"], ctx["op_headers"], plan_review_id=review["id"]
    )
    validate_success(
        api.transition_permit(permit["id"], {"action": "SUBMIT"}, ctx["op_headers"])
    )
    start_plan_review(review["id"])

    decided = validate_success(
        api.transition_plan_review(
            review["id"], {"action": "DISAPPROVE"}, PLAN_REVIEWER
        )
    )

    assert decided["status"] == "DISAPPROVED"
    assert decided["decided_by_user_id"] == PLAN_REVIEWER_ONE_ID
    assert decided["decided_at"] == "2026-05-01T00:00:00.000Z"
    assert read_permit(permit["id"])["status"] == "DENIED"

    rows, meta = validate_paginated(
        api.list_permits(ADMIN, params={"plan_review_id": review["id"]})
    )
    assert meta["total_count"] == 1 and rows[0]["id"] == permit["id"]
    assert fee_balance(ctx["operator_id"]) == 25000


def test_plan_revision_supersedes_its_predecessor_and_increments_the_round(api):
    """PRD 3.2: The superseded review moves `CORRECTIONS_REQUIRED → SUPERSEDED`
    and its `version` increments by 1, while a brand-new review is created in
    `SUBMITTED` carrying the same `facility_id` and `project_type`, a
    `supersedes_plan_review_id` pointing at the review it replaces, and a
    `revision_round` one greater than that review's.
    PRD 3.2: A second `PLAN_REVIEW_FEE` posting of a positive 25000 cents is
    charged for the new row and the operator's balance refreshed.

    Design: Corner/state_machines/plan_review_revision_supersedes_predecessor_and_increments_round
    """
    ctx = setup_operator_and_pool()
    review = submit_plan_review(
        ctx["facility_id"], ctx["op_headers"], drawing_reference="DR-A"
    )
    corrected = drive_plan_review_to_corrections_required(
        review["id"], "Add depth markers to sheet A3"
    )

    successor = validate_success(
        api.create_plan_review_revision(
            review["id"],
            {
                "expected_plan_review_version": corrected["version"],
                "drawing_reference": "DR-A-rev1",
            },
            ctx["op_headers"],
        ),
        201,
    )

    assert successor["status"] == "SUBMITTED"
    assert successor["revision_round"] == 1
    assert successor["supersedes_plan_review_id"] == review["id"]

    predecessor = read_plan_review(review["id"])
    assert predecessor["status"] == "SUPERSEDED"
    assert predecessor["version"] == corrected["version"] + 1

    rows, meta = validate_paginated(
        api.list_plan_reviews(
            ADMIN, params={"supersedes_plan_review_id": review["id"]}
        )
    )
    assert meta["total_count"] == 1 and rows[0]["id"] == successor["id"]
    assert fee_balance(ctx["operator_id"]) == 50000


def test_request_corrections_on_a_third_round_review_is_exhausted(api):
    """PRD 3.2: It is permitted only while the review's `revision_round` is
    strictly below 3; a review already sitting at round 3 has exhausted its
    correction rounds and the request is rejected with
    `ERR_PLAN_REVIEW_ROUNDS_EXHAUSTED`, leaving the reviewer with only the two
    terminal decisions.

    Design: Corner/state_machines/plan_review_request_corrections_after_third_round_exhausted
    """
    ctx = setup_operator_and_pool()
    reviews = setup_plan_review_chain(3, ctx["facility_id"], ctx["op_headers"])
    final_review = reviews[-1]
    start_plan_review(final_review["id"])

    response = api.transition_plan_review(
        final_review["id"],
        {"action": "REQUEST_CORRECTIONS", "correction_notes": "Round 4 comments"},
        PLAN_REVIEWER,
    )

    validate_error(
        response, ApiErrorId.ERR_PLAN_REVIEW_ROUNDS_EXHAUSTED.value, 409
    )

    live = read_plan_review(final_review["id"])
    assert live["revision_round"] == 3
    assert live["status"] == "UNDER_REVIEW"
    for superseded in reviews[:-1]:
        assert read_plan_review(superseded["id"])["status"] == "SUPERSEDED"
    assert fee_balance(ctx["operator_id"]) == 100000


def test_approving_a_review_that_was_never_started_is_rejected(api):
    """PRD 3.2: **Approving** advances `UNDER_REVIEW → APPROVED`, sets
    `decided_at` to the logical clock, records the approving `X-User-ID` as
    `decided_by_user_id`, and clears `correction_notes` back to null.
    PRD 2.6: **Plan-review state precondition**; a revision additionally requires
    `CORRECTIONS_REQUIRED` → `ERR_INVALID_PLAN_REVIEW_STATE` (409), on
    `POST /plan-reviews/{id}/transition` and `POST /plan-reviews/{id}/revisions`.

    Design: Corner/errors/plan_review_approve_without_starting_review_rejected
    """
    ctx = setup_operator_and_pool()
    review = submit_plan_review(
        ctx["facility_id"], ctx["op_headers"], project_type="ALTERATION",
        drawing_reference="DR-7",
    )

    validate_error(
        api.transition_plan_review(review["id"], {"action": "APPROVE"}, PLAN_REVIEWER),
        ApiErrorId.ERR_INVALID_PLAN_REVIEW_STATE.value, 409,
    )

    untouched = read_plan_review(review["id"])
    assert untouched["status"] == "SUBMITTED"
    assert untouched["decided_at"] is None
    assert untouched["decided_by_user_id"] is None

    # The supplied version is current, so the optimistic-concurrency check passes
    # and the state precondition is what rejects the revision.
    validate_error(
        api.create_plan_review_revision(
            review["id"],
            {
                "expected_plan_review_version": review["version"],
                "drawing_reference": "DR-7-rev",
            },
            ctx["op_headers"],
        ),
        ApiErrorId.ERR_INVALID_PLAN_REVIEW_STATE.value, 409,
    )

    rows, meta = validate_paginated(
        api.list_plan_reviews(
            ADMIN, params={"supersedes_plan_review_id": review["id"]}
        )
    )
    assert meta["total_count"] == 0 and rows == []


def test_revision_with_a_stale_expected_version_rejected(api):
    """PRD 2.7: Filing a plan revision requires `expected_plan_review_version` as
    a non-optional field in the request body of
    `POST /plan-reviews/{id}/revisions`, carrying the client's last observed
    `version` of the review named in the path. If it does not equal that review's
    current `version`, the request is rejected with
    `ERR_STALE_PLAN_REVIEW_VERSION` and HTTP 412.

    Design: Corner/cross_cutting_layers/occ_stale_plan_review_version_rejected_on_revision
    """
    ctx = setup_operator_and_pool()
    review = submit_plan_review(
        ctx["facility_id"], ctx["op_headers"], drawing_reference="DR-A"
    )
    at_start_review = start_plan_review(review["id"])
    after_corrections = validate_success(
        api.transition_plan_review(
            review["id"],
            {"action": "REQUEST_CORRECTIONS", "correction_notes": "Add depth markers"},
            PLAN_REVIEWER,
        )
    )

    stale = api.create_plan_review_revision(
        review["id"],
        {
            "expected_plan_review_version": at_start_review["version"],
            "drawing_reference": "DR-A-rev1",
        },
        ctx["op_headers"],
    )
    validate_error(stale, ApiErrorId.ERR_STALE_PLAN_REVIEW_VERSION.value, 412)

    assert read_plan_review(review["id"])["status"] == "CORRECTIONS_REQUIRED"
    rows, meta = validate_paginated(
        api.list_plan_reviews(
            ADMIN, params={"supersedes_plan_review_id": review["id"]}
        )
    )
    assert meta["total_count"] == 0 and rows == []

    successor = file_plan_revision(
        review["id"], after_corrections["version"], ctx["op_headers"],
        drawing_reference="DR-A-rev1",
    )
    assert successor["revision_round"] == 1
    assert read_plan_review(review["id"])["status"] == "SUPERSEDED"
    assert fee_balance(ctx["operator_id"]) == 50000


def test_payment_posts_a_negative_entry_and_lowers_the_balance(api):
    """PRD 3.1: It posts a ledger entry with `entry_type` of `PAYMENT`, a null
    `permit_id`, and an `amount_cents` equal to the negation of the amount paid,
    then refreshes the operator's `fee_balance_cents`.
    PRD 2.8: An operator's `fee_balance_cents` is the sum of `amount_cents` over
    every ledger posting whose `operator_id` is that operator, with no status
    filter and no time filter — the whole append-only history is always in scope.

    Design: Corner/calculations/operator_payment_reduces_the_fee_balance
    """
    ctx = setup_operator_and_pool()
    submit_plan_review(
        ctx["facility_id"], ctx["op_headers"], project_type="EQUIPMENT_REPLACEMENT",
        drawing_reference="DR-EQ-1",
    )

    payment = validate_success(
        api.create_payment(
            ctx["operator_id"],
            {"amount_cents": 10000, "reference_note": "Partial payment"},
            ctx["op_headers"],
        ),
        201,
    )

    assert payment["entry_type"] == "PAYMENT"
    assert payment["amount_cents"] == -10000
    assert payment["permit_id"] is None
    assert fee_balance(ctx["operator_id"]) == 15000

    rows, meta = validate_paginated(
        api.list_fee_ledger_entries(ADMIN, params={"operator_id": ctx["operator_id"]})
    )
    assert meta["total_count"] == 2
    assert sum(row["amount_cents"] for row in rows) == 15000


class TestIssuanceGatedOnPlanReviewApproval:
    """The Permit issue edge is legal only while the referenced review is APPROVED."""

    @staticmethod
    def _setup():
        ctx = setup_operator_and_pool(
            operator_overrides={
                "legal_name": "Civic Aquatic Center",
                "contact_email": "permits@civic.example",
            },
            name="Civic Competition Pool",
            max_depth_feet=12,
            requires_plan_review=True,
        )
        review = submit_plan_review(
            ctx["facility_id"], ctx["op_headers"], drawing_reference="DR-2026-014"
        )
        permit = apply_for_permit(
            ctx["facility_id"], ctx["op_headers"], plan_review_id=review["id"]
        )
        advance_permit_to_under_review(permit["id"], ctx["op_headers"])
        pay_operator_balance(
            ctx["operator_id"], ctx["op_headers"], 25000, "Plan review fee"
        )
        ctx["review"] = review
        ctx["permit"] = permit
        return ctx

    def test_issue_rejected_while_the_review_is_still_submitted(self, api):
        """PRD 3.3: when the facility's `requires_plan_review` is true the
        referenced review's `status` must be `APPROVED`, or
        `ERR_PLAN_REVIEW_NOT_APPROVED`
        PRD 3.3: The permit is created in `DRAFT` with `assessed_fee_cents` of 0
        and `fee_variant` of null; neither is populated before issuance.

        Design: Difficulty/cross_entity_state_dependency/permit_issuance_gated_on_plan_review_approved_state
        """
        ctx = self._setup()

        validate_error(
            api.transition_permit(
                ctx["permit"]["id"], {"action": "ISSUE"}, ADMIN
            ),
            ApiErrorId.ERR_PLAN_REVIEW_NOT_APPROVED.value, 409,
        )

        refused = read_permit(ctx["permit"]["id"])
        assert refused["status"] == "UNDER_REVIEW"
        assert refused["assessed_fee_cents"] == 0
        assert read_plan_review(ctx["review"]["id"])["status"] == "SUBMITTED"

    def test_issue_succeeds_once_the_reviewer_approves(self, api):
        """PRD 3.2: **Approving** advances `UNDER_REVIEW → APPROVED`, sets
        `decided_at` to the logical clock, records the approving `X-User-ID` as
        `decided_by_user_id`, and clears `correction_notes` back to null.
        PRD 3.3: Issuance then writes `issued_at` from the logical clock and
        `issued_by_user_id` from the acting `X-User-ID`, posts a ledger entry of
        `entry_type` `PERMIT_FEE` against this permit for the positive subtotal

        Design: Difficulty/cross_entity_state_dependency/permit_issuance_gated_on_plan_review_approved_state
        """
        ctx = self._setup()
        validate_error(
            api.transition_permit(ctx["permit"]["id"], {"action": "ISSUE"}, ADMIN),
            ApiErrorId.ERR_PLAN_REVIEW_NOT_APPROVED.value, 409,
        )

        approved = approve_plan_review(ctx["review"]["id"])
        assert approved["status"] == "APPROVED"
        assert approved["decided_by_user_id"] == PLAN_REVIEWER_ONE_ID

        issued = validate_success(
            api.transition_permit(ctx["permit"]["id"], {"action": "ISSUE"}, ADMIN)
        )
        assert issued["status"] == "ISSUED"
        assert issued["assessed_fee_cents"] == 40000
        assert read_operator(ctx["operator_id"])["fee_balance_cents"] == 40000

        rows, meta = validate_paginated(
            api.list_fee_ledger_entries(
                ADMIN, params={"operator_id": ctx["operator_id"]}
            )
        )
        assert meta["total_count"] == 3
        assert [(row["entry_type"], row["amount_cents"]) for row in rows] == [
            ("PLAN_REVIEW_FEE", 25000),
            ("PAYMENT", -25000),
            ("PERMIT_FEE", 40000),
        ]

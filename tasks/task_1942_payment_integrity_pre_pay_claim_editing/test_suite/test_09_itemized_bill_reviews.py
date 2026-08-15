"""Itemized bill reviews: per-line repricing, occupancy buffer boundaries,
expiry gating, and out-of-state completion."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    complete_ibr_review,
    create_claim_with_lines,
    create_manual_ibr,
    create_provider,
    get_claim,
    get_claim_ibr,
    get_success_data,
    run_claim_edits,
    screen_one_line_claim,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["plan_admin_headers"]
SENIOR = TEST_USERS["senior_reviewer_headers"]


def test_itemized_reprice_per_line_rounding(api):
    """PRD §3.7: "the server reprices the claim line by line — each line's
    repriced amount is its `billed_cents` reduced by the 6.5 percent contract
    discount, rounded half-up to whole cents per line first, and
    `repriced_total_cents` is the sum of those per-line results. The rounding
    order is pinned per-line-then-sum because summing first and rounding once
    can differ by cents; the per-line order is authoritative."

    Design: Difficulty/combinatorial_formula/itemized_reprice_per_line_rounding
    """
    provider = create_provider(npi="NPI-R1", name="Reprice Prov")
    claim = create_claim_with_lines(
        provider["id"],
        lines=((1, "A0001", 101), (2, "A0002", 101), (3, "A0003", 101)),
        claim_number="R1", member_id="M-R1")
    screened = run_claim_edits(claim["id"])
    assert screened["status"] == "READY_TO_PAY"

    ibr = create_manual_ibr(claim["id"])
    completed = complete_ibr_review(ibr["id"], provider["id"], findings_cents=0)
    # round_half_up(101 * 0.935) = 94 per line; 94 + 94 + 94 = 282.
    # (Sum-then-round would give round(303 * 0.935) = 283.)
    assert completed["repriced_total_cents"] == 282
    assert completed["status"] == "COMPLETED"


def test_itemized_reprice_rebalances_claim(api):
    """PRD §3.7: "The claim's `allowed_amount_cents` is then set to the lesser
    of its current value and `repriced_total_cents`, never below zero, and
    `denied_amount_cents` is reset so the ledger invariant of Section 2.10
    holds."
    PRD §3.7: "Completion stamps `completed_at`, records the auditor in
    `auditor_user_id`, subtracts one from the provider's `open_ibr_count`,
    re-evaluates the claim's bubble-up, and increments the claim's `version`
    by one."

    Design: Difficulty/combinatorial_formula/itemized_reprice_per_line_rounding
    """
    provider = create_provider(npi="NPI-R2", name="Reprice Prov 2")
    claim = create_claim_with_lines(
        provider["id"],
        lines=((1, "A0001", 101), (2, "A0002", 101), (3, "A0003", 101)),
        claim_number="R2", member_id="M-R2")
    run_claim_edits(claim["id"])
    ibr = create_manual_ibr(claim["id"])
    assert get_claim(claim["id"])["status"] == "PENDED", (
        "manual creation reopens a READY_TO_PAY claim to PENDED"
    )

    completed = complete_ibr_review(ibr["id"], provider["id"], findings_cents=0)
    assert completed["repriced_total_cents"] == 282

    final = get_claim(claim["id"])
    assert final["allowed_amount_cents"] == 282
    assert final["denied_amount_cents"] == 21, "303 - 282 rebalanced to denied"
    assert final["initial_allowed_cents"] == 303
    assert final["allowed_amount_cents"] + final["denied_amount_cents"] == \
        final["initial_allowed_cents"]
    assert final["status"] == "READY_TO_PAY", "gates closed at completion"


def test_ibr_occupancy_buffer_collision(api):
    """PRD §3.7: "the provider must have no other itemized bill review whose
    occupancy interval contains the current instant. That interval runs from
    the review's `requested_at` through its `completed_at` plus a 14-day
    buffer, both ends inclusive; a review still open — one in `REQUESTED`,
    `DOCUMENTS_RECEIVED`, or `IN_AUDIT` — is treated as ending now. A
    collision is rejected with `ERR_PROVIDER_AUDIT_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/ibr_provider_occupancy_buffer
    """
    provider = create_provider(npi="NPI-F8", name="Occupied Prov")
    claim_x = screen_one_line_claim(provider["id"], billed=100000,
                                    claim_number="F8X", member_id="M-F8X")
    assert claim_x["status"] == "READY_TO_PAY"
    ibr1 = create_manual_ibr(claim_x["id"])
    complete_ibr_review(ibr1["id"], provider["id"], findings_cents=0)

    # Completed at the default clock 2026-08-01: occupancy runs through
    # completed_at + 14 days = 2026-08-15 inclusive. +10 days is inside.
    set_clock("2026-08-11T00:00:00Z")
    claim_y = screen_one_line_claim(provider["id"], billed=50000,
                                    claim_number="F8Y", member_id="M-F8Y")
    resp = api.create_ibr(claim_y["id"], SENIOR)
    validate_error(resp, ApiErrorId.ERR_PROVIDER_AUDIT_OVERLAP,
                   expected_status=409)


def test_ibr_occupancy_buffer_expired_allows_new(api):
    """PRD §3.7: "That interval runs from the review's `requested_at` through
    its `completed_at` plus a 14-day buffer, both ends inclusive"
    PRD §3.7: "a manual creation on a `READY_TO_PAY` claim also reopens the
    claim to `PENDED`, since a new gate has appeared."

    Design: Difficulty/resource_temporal_overlap/ibr_provider_occupancy_buffer
    """
    provider = create_provider(npi="NPI-F8B", name="Freed Prov")
    claim_x = screen_one_line_claim(provider["id"], billed=100000,
                                    claim_number="F8X2", member_id="M-F8X2")
    ibr1 = create_manual_ibr(claim_x["id"])
    complete_ibr_review(ibr1["id"], provider["id"], findings_cents=0)

    # completed_at 2026-08-01 + 14 days = 2026-08-15 inclusive; +15 days
    # (2026-08-16) is outside the buffered interval.
    set_clock("2026-08-16T00:00:00Z")
    claim_y = screen_one_line_claim(provider["id"], billed=50000,
                                    claim_number="F8Y2", member_id="M-F8Y2")
    assert claim_y["status"] == "READY_TO_PAY"
    ibr2 = validate_success(api.create_ibr(claim_y["id"], SENIOR),
                            expected_status=201)
    assert ibr2["status"] == "REQUESTED"
    assert get_claim(claim_y["id"])["status"] == "PENDED", (
        "the new manual review reopens the claim"
    )


def test_ibr_expire_before_due_rejected_then_expires(api):
    """PRD §3.7: "Once the logical clock passes `due_at`, a `PlanAdmin` may
    expire a `REQUESTED` review; expiring at or before the due instant is
    rejected with `ERR_IBR_NOT_YET_EXPIRABLE` (HTTP 422), so the boundary is
    strict — the review must be past due, not merely at its due instant."
    PRD §3.7: "Expiration moves the review to `EXPIRED`, subtracts one from
    the provider's `open_ibr_count`, and re-evaluates the claim's bubble-up."

    Design: Corner/state_machines/ibr_expire_before_due_rejected_then_expires
    """
    provider = create_provider(npi="NPI-SM8", name="Exp Prov")
    claim = screen_one_line_claim(provider["id"], billed=10000000,
                                  claim_number="EX1", member_id="M-EX1")
    assert claim["status"] == "PENDED"
    ibr = get_claim_ibr(claim["id"])
    assert ibr["status"] == "REQUESTED"
    assert ibr["due_at"].startswith("2026-08-31T00:00:00")

    resp = api.expire_ibr(ibr["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_IBR_NOT_YET_EXPIRABLE,
                   expected_status=422)

    set_clock("2026-09-01T00:00:00Z")
    expired = validate_success(api.expire_ibr(ibr["id"], ADMIN))
    assert expired["status"] == "EXPIRED"

    final = get_claim(claim["id"])
    assert final["status"] == "READY_TO_PAY"
    assert final["allowed_amount_cents"] == 10000000


def test_ibr_complete_from_requested_rejected(api):
    """PRD §3.7: "Every itemized-bill action is state-guarded — documents only
    against `REQUESTED`, audit only against `DOCUMENTS_RECEIVED`, completion
    only against `IN_AUDIT`, expiration only against `REQUESTED` — and an
    out-of-state attempt is rejected with `ERR_IBR_NOT_COMPLETABLE`
    (HTTP 409)."

    Design: Corner/validations/ibr_complete_from_requested_rejected
    """
    provider = create_provider(npi="NPI-IC", name="Ibr Prov")
    claim = screen_one_line_claim(provider["id"], billed=10000000,
                                  claim_number="IC1", member_id="M-IC1")
    ibr = get_claim_ibr(claim["id"])
    assert ibr["status"] == "REQUESTED"

    resp = api.complete_ibr(ibr["id"], {"findings_cents": 0}, SENIOR)
    validate_error(resp, ApiErrorId.ERR_IBR_NOT_COMPLETABLE, expected_status=409)
    still = get_success_data(api.get_ibr(ibr["id"], ADMIN))
    assert still["status"] == "REQUESTED"

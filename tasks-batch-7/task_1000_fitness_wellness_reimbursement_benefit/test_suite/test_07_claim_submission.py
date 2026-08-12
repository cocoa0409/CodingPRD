"""Claim submission gates: shape, enums, receipts, deadlines, line rounding."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_claim,
    create_claim_payload,
    get_success_data,
    line_item,
    make_member_headers,
    member_headers,
    set_clock,
    standard_world,
    submit_claim,
    review_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["benefits_admin_headers"]
REVIEWER = TEST_USERS["claims_reviewer_headers"]


def test_create_claim_invalid_enum_rejected(api):
    """PRD §2.9: "Shape checks then follow: required fields present and
    well-typed (`ERR_INVALID_REQUEST`), enum fields carrying a declared member
    (`ERR_INVALID_ENUM`)"
    PRD §3.7: "Claims come in two routings, fixed by `claim_type`"

    Design: Corner/validations/create_claim_invalid_enum_rejected
    """
    world = standard_world()
    payload = create_claim_payload(world["enrollment"]["id"], "R-E", claim_type="CASH")
    resp = api.create_claim(payload, member_headers(world))
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)


def test_claim_create_missing_required_line_items(api):
    """PRD §2.9: "required fields present and well-typed
    (`ERR_INVALID_REQUEST`)"
    PRD §3.7: "Every submission names the `enrollment_id` to debit, the
    `service_date`, an external `receipt_ref`, and a `line_items` array"

    Design: Corner/validations/claim_create_missing_required_line_items
    """
    world = standard_world()
    payload = {
        "enrollment_id": world["enrollment"]["id"],
        "claim_type": "REIMBURSEMENT",
        "service_date": "2026-05-02T10:00:00Z",
        "receipt_ref": "R-M",
    }
    resp = api.create_claim(payload, member_headers(world))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_claim_with_unknown_visit_returns_not_found(api):
    """PRD §2.9: "Body foreign keys — `employer_id`, `plan_id`, `member_id`,
    `enrollment_id`, and every element of `visit_ids` — resolve the same way,
    and an unresolvable id inside `visit_ids` yields `ERR_VISIT_NOT_FOUND`."

    Design: Corner/validations/claim_with_unknown_visit_returns_not_found
    """
    world = standard_world()
    payload = create_claim_payload(
        world["enrollment"]["id"], "R-NF",
        visit_ids=["9b4f2c1d-3e5a-4b82-8d9c-23f8c7b1e2a3"],
    )
    resp = api.create_claim(payload, member_headers(world))
    validate_error(resp, ApiErrorId.ERR_VISIT_NOT_FOUND)


def test_duplicate_receipt_rejected(api):
    """PRD §3.7: "The `receipt_ref` must be unique per member across all of
    that member's claims that are not `REJECTED` (`ERR_DUPLICATE_RECEIPT`)."

    Design: Corner/validations/duplicate_receipt_rejected
    """
    world = standard_world()
    submit_claim(world, 1000, "R-DUP2")
    payload = create_claim_payload(world["enrollment"]["id"], "R-DUP2",
                                   service_date="2026-05-03T10:00:00Z")
    resp = api.create_claim(payload, member_headers(world))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RECEIPT)


class TestCreateFilingDeadlineBeatsDuplicateReceipt:
    """New claim is BOTH 106 days late (temporal) AND a duplicate receipt
    (business constraint); the temporal error must win."""

    def test_temporal_error_wins(self, api):
        """PRD §2.9: "7. **Temporal windows** — filing deadline, contract
        window, and plan period checks."
        PRD §2.9: "8. **Business constraints** — overlaps, duplicates, caps,
        tier definedness, and dependent age."
        PRD §3.7: "Four filing rules gate submission, evaluated within the
        pipeline order of §2.9."

        Design: Difficulty/priority_pair_validation_conflict/create_filing_deadline_beats_duplicate_receipt
        """
        world = standard_world()
        submit_claim(world, 1000, "R-DUP", service_date="2026-04-20T10:00:00Z")
        payload = create_claim_payload(world["enrollment"]["id"], "R-DUP",
                                       service_date="2026-01-15T10:00:00Z")
        resp = api.create_claim(payload, member_headers(world))
        err = validate_error(resp, ApiErrorId.ERR_CLAIM_FILING_DEADLINE)
        assert err["error_id"] != "ERR_DUPLICATE_RECEIPT", (
            "temporal window check (priority 7) must beat the duplicate constraint (priority 8)"
        )

    def test_no_claim_created_on_temporal_rejection(self, api, admin_headers):
        """PRD §3.7: "may be no more than ninety days behind the logical
        clock — a claim exactly ninety days old is accepted, while one
        ninety-one days old is refused with `ERR_CLAIM_FILING_DEADLINE`."

        Design: Difficulty/priority_pair_validation_conflict/create_filing_deadline_beats_duplicate_receipt
        """
        world = standard_world()
        submit_claim(world, 1000, "R-DUP", service_date="2026-04-20T10:00:00Z")
        payload = create_claim_payload(world["enrollment"]["id"], "R-DUP",
                                       service_date="2026-01-15T10:00:00Z")
        resp = api.create_claim(payload, member_headers(world))
        assert resp.status_code == 422, f"stale claim must be refused with 422, got {resp.status_code}"
        data, meta = validate_paginated(api.list_claims(admin_headers))
        assert meta["total_count"] == 1, f"rejected submission must not persist, got {meta['total_count']} claims"


class TestFilingDeadlineDay90:
    """Clock advanced to 2026-05-10; 2026-02-09 is exactly 90 days old."""

    def test_exactly_90_days_accepted(self, api):
        """PRD §3.7: "may be no more than ninety days behind the logical
        clock — a claim exactly ninety days old is accepted, while one
        ninety-one days old is refused with `ERR_CLAIM_FILING_DEADLINE`."

        Design: Difficulty/boundary_precision_check/filing_deadline_day_90
        """
        world = standard_world()
        set_clock("2026-05-10T00:00:00Z")
        resp = api.create_claim(
            create_claim_payload(world["enrollment"]["id"], "R-90",
                                 service_date="2026-02-09T00:00:00Z"),
            member_headers(world),
        )
        claim = validate_success(resp, expected_status=201)
        assert_claim(claim)

    def test_91_days_rejected(self, api):
        """PRD §3.7: "may be no more than ninety days behind the logical
        clock — a claim exactly ninety days old is accepted, while one
        ninety-one days old is refused with `ERR_CLAIM_FILING_DEADLINE`."

        Design: Difficulty/boundary_precision_check/filing_deadline_day_90
        """
        world = standard_world()
        set_clock("2026-05-10T00:00:00Z")
        resp = api.create_claim(
            create_claim_payload(world["enrollment"]["id"], "R-91",
                                 service_date="2026-02-08T00:00:00Z"),
            member_headers(world),
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_FILING_DEADLINE)


def test_claim_service_outside_plan_period_rejected(api):
    """PRD §3.7: "The `service_date` must fall inside the enrollment plan's
    coverage window, closed on both ends (`ERR_SERVICE_OUTSIDE_PLAN_PERIOD`)"

    Design: Corner/validations/claim_service_outside_plan_period_rejected
    """
    world = standard_world(plan_overrides={
        "name": "2026 Q2on",
        "period_start": "2026-03-01T00:00:00Z",
        "period_end": "2026-12-31T23:59:59Z",
    })
    # 2026-02-15 is 75 days before the 2026-05-01 clock: inside the filing
    # window, but before period_start — isolates the plan-period rule.
    resp = api.create_claim(
        create_claim_payload(world["enrollment"]["id"], "R-PP",
                             service_date="2026-02-15T10:00:00Z"),
        member_headers(world),
    )
    err = validate_error(resp, ApiErrorId.ERR_SERVICE_OUTSIDE_PLAN_PERIOD)
    assert err["error_id"] != "ERR_CLAIM_FILING_DEADLINE"


class TestClaimLineRoundingPerLineThenSum:
    def test_per_line_rounding_yields_1050(self, api):
        """PRD §3.7: "Rounding per line before summing is mandatory — summing
        the raw line totals and rounding once is forbidden because it produces
        a different figure: three lines of 333 cents at quantity 1 with a five
        percent tax yield 350 + 350 + 350 = 1050 cents under the per-line
        rule, while the forbidden sum-then-round order yields 1049."

        Design: Difficulty/combinatorial_formula/claim_line_rounding_per_line_then_sum
        """
        world = standard_world()
        items = [line_item(333, tax_pct=0.05, description=c) for c in ("a", "b", "c")]
        resp = api.create_claim(
            create_claim_payload(world["enrollment"]["id"], "R-TAX", line_items=items),
            member_headers(world),
        )
        claim = validate_success(resp, expected_status=201)
        assert claim["claimed_amount_cents"] == 1050, (
            f"per-line round-half-up must give 350+350+350 = 1050 (not 1049), got {claim['claimed_amount_cents']}"
        )

    def test_reservation_matches_per_line_total(self, api, admin_headers):
        """PRD §3.7: "for each line, multiply `unit_amount_cents` by
        `quantity` by one plus `tax_pct`, round that line total half up to a
        whole cent, and then sum the rounded line totals into
        `claimed_amount_cents`."
        PRD §3.7: "On successful submission the claim reserves against the
        allowance: the enrollment's `reserved_cents` increases by
        `claimed_amount_cents`."

        Design: Difficulty/combinatorial_formula/claim_line_rounding_per_line_then_sum
        """
        world = standard_world()
        items = [line_item(333, tax_pct=0.05, description=c) for c in ("a", "b", "c")]
        claim = get_success_data(api.create_claim(
            create_claim_payload(world["enrollment"]["id"], "R-TAX", line_items=items),
            member_headers(world),
        ))
        assert claim["claimed_amount_cents"] == 1050
        allowance = get_success_data(api.get_enrollment_allowance(world["enrollment"]["id"], admin_headers))
        assert allowance["reserved_cents"] == 1050, (
            f"reservation must equal the per-line total 1050, got {allowance['reserved_cents']}"
        )


def test_member_cannot_approve_claim(api):
    """PRD §2.1: "A caller whose role is not listed for the endpoint is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.8: "A `ClaimsReviewer` may approve only a claim sitting in
    `UNDER_REVIEW`"

    Design: Corner/rbac/member_cannot_approve_claim
    """
    world = standard_world()
    claim = submit_claim(world, 1000, "R-R1")
    review_claim(claim["id"])
    resp = api.approve_claim(claim["id"], member_headers(world))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

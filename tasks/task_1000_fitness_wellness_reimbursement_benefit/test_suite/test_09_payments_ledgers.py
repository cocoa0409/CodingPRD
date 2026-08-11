"""Payments, reversals, funding ledger, allowance ledger, exhaustion cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_claim,
    assert_funding_entry,
    create_employer,
    create_funding_account,
    get_success_data,
    pay_claim,
    review_claim,
    set_clock,
    standard_world,
    submit_approved_claim,
    submit_claim,
    submit_paid_claim,
    submit_reviewed_claim,
    tier_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["benefits_admin_headers"]
REVIEWER = TEST_USERS["claims_reviewer_headers"]


def test_funding_entry_append_only_ledger(api, admin_headers):
    """PRD §3.9: "Creation takes `employer_id`, `benefit_year`, and an
    `initial_deposit_cents` that becomes the opening `DEPOSIT` entry."
    PRD §2.10: "Each `FundingEntry` records its owning `funding_account_id`,
    the originating `claim_id` (null for deposits), an `entry_type` of
    `DEPOSIT`, `HOLD`, `RELEASE`, `DEBIT`, or `CLAWBACK_CREDIT`, an
    `amount_cents` that is always stored positive — the sign is implied by the
    entry type at application time — and `running_available_cents`, the
    account's `available_cents` immediately after that entry is applied in
    chronological replay."

    Design: Corner/entities/funding_entry_append_only_ledger
    """
    employer = create_employer()
    account = create_funding_account(employer["id"], initial_deposit_cents=50000)
    entries, meta = validate_paginated(api.list_funding_entries(account["id"], admin_headers))
    assert len(entries) == 1, f"exactly the opening DEPOSIT must exist, got {len(entries)}"
    assert_funding_entry(entries[0])
    assert entries[0]["entry_type"] == "DEPOSIT"
    assert entries[0]["amount_cents"] == 50000
    assert entries[0]["running_available_cents"] == 50000


class TestFundingConservationAcrossPayAndClawback:
    """Claim 4000 against a 100000 account; counters checked after approve,
    pay, and clawback."""

    def _setup(self, api):
        world = standard_world()
        return world, submit_reviewed_claim(world, 4000, "R-INV")

    def test_hold_and_debit_steps_conserve(self, api, admin_headers):
        """PRD §2.10: "The compensating invariant holds after every payment
        and its reversal: `funded_cents` plus clawback credits equals
        `available_cents` plus `reserved_cents` plus `disbursed_cents`."
        PRD §3.8: "Payment converts the hold into a `DEBIT` entry: the
        account's `reserved_cents` falls and its `disbursed_cents` rises by
        the approved amount"

        Design: Difficulty/compensating_invariant/funding_conservation_across_pay_and_clawback
        """
        world, claim = self._setup(api)
        fid = world["funding"]["id"]

        approve_claim(claim["id"])
        acct = get_success_data(api.get_funding_account(fid, admin_headers))
        assert (acct["available_cents"], acct["reserved_cents"], acct["disbursed_cents"]) == (96000, 4000, 0)
        assert acct["available_cents"] + acct["reserved_cents"] + acct["disbursed_cents"] == acct["funded_cents"]

        pay_claim(claim["id"])
        acct = get_success_data(api.get_funding_account(fid, admin_headers))
        assert (acct["available_cents"], acct["reserved_cents"], acct["disbursed_cents"]) == (96000, 0, 4000)
        assert acct["available_cents"] + acct["reserved_cents"] + acct["disbursed_cents"] == acct["funded_cents"]

    def test_clawback_restores_with_zero_drift(self, api, admin_headers):
        """PRD §3.8: "Reversing a `PAID` claim moves payment to `CLAWED_BACK`:
        a `CLAWBACK_CREDIT` entry is appended, `disbursed_cents` falls and
        `available_cents` rises by the approved amount"

        Design: Difficulty/compensating_invariant/funding_conservation_across_pay_and_clawback
        """
        world, claim = self._setup(api)
        fid = world["funding"]["id"]
        approve_claim(claim["id"])
        pay_claim(claim["id"])
        reversed_claim = validate_success(api.reverse_claim(claim["id"], ADMIN, {"reason": "clawback"}))
        assert reversed_claim["payment_status"] == "CLAWED_BACK"

        acct = get_success_data(api.get_funding_account(fid, admin_headers))
        assert (acct["available_cents"], acct["reserved_cents"], acct["disbursed_cents"]) == (100000, 0, 0), (
            f"clawback must restore available to 100000 with zero drift, got {acct}"
        )


class TestEnrollmentAllowanceConservation:
    def test_create_and_pay_steps(self, api, admin_headers):
        """PRD §2.10: "The compensating invariant holds after every forward
        action (create, approve, pay) and every compensating action (reject,
        reverse, clawback): used plus reserved plus remaining always equals
        `annual_allowance_cents`."

        Design: Difficulty/compensating_invariant/enrollment_allowance_conservation
        """
        world = standard_world()
        eid = world["enrollment"]["id"]
        claim = submit_reviewed_claim(world, 3000, "R-AL")

        allowance = get_success_data(api.get_enrollment_allowance(eid, admin_headers))
        assert (allowance["used_cents"], allowance["reserved_cents"], allowance["remaining_cents"]) == (0, 3000, 27000)
        assert allowance["used_cents"] + allowance["reserved_cents"] + allowance["remaining_cents"] == 30000

        approve_claim(claim["id"])
        pay_claim(claim["id"])
        allowance = get_success_data(api.get_enrollment_allowance(eid, admin_headers))
        assert (allowance["used_cents"], allowance["reserved_cents"], allowance["remaining_cents"]) == (3000, 0, 27000)

    def test_clawback_restores_full_allowance(self, api, admin_headers):
        """PRD §3.8: "the enrollment's `used_cents` falls by the same, and
        `quarter_used_cents` falls as well when the quarter of the original
        payment is still the current quarter"
        PRD §2.10: "used plus reserved plus remaining always equals
        `annual_allowance_cents`."

        Design: Difficulty/compensating_invariant/enrollment_allowance_conservation
        """
        world = standard_world()
        eid = world["enrollment"]["id"]
        claim = submit_paid_claim(world, 3000, "R-AL")
        validate_success(api.reverse_claim(claim["id"], ADMIN, {"reason": "clawback"}))

        allowance = get_success_data(api.get_enrollment_allowance(eid, admin_headers))
        assert (allowance["used_cents"], allowance["reserved_cents"], allowance["remaining_cents"]) == (0, 0, 30000), (
            f"clawback must restore the full 30000 with zero drift, got {allowance}"
        )


class TestClaimPayRequiresFundingActive:
    def _setup(self, api):
        world = standard_world()
        claim = submit_approved_claim(world, 3000, "R-P")  # HOLD placed
        validate_success(api.suspend_funding_account(world["funding"]["id"], ADMIN))
        return world, claim

    def test_pay_blocked_while_funding_suspended(self, api):
        """PRD §3.8: "Paying requires `payment_status` to be `UNPAID` and the
        funding account to be `FUNDED` (anything else yields
        `ERR_FUNDING_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/claim_pay_requires_funding_active
        """
        world, claim = self._setup(api)
        resp = api.pay_claim(claim["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_FUNDING_NOT_ACTIVE)

    def test_payment_status_unchanged_after_blocked_pay(self, api, admin_headers):
        """PRD §3.8: "Paying requires `payment_status` to be `UNPAID` and the
        funding account to be `FUNDED` (anything else yields
        `ERR_FUNDING_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/claim_pay_requires_funding_active
        """
        world, claim = self._setup(api)
        validate_error(api.pay_claim(claim["id"], ADMIN), ApiErrorId.ERR_FUNDING_NOT_ACTIVE)
        after = get_success_data(api.get_claim(claim["id"], admin_headers))
        assert after["payment_status"] == "UNPAID", (
            f"blocked pay must leave payment_status UNPAID, got {after['payment_status']}"
        )


class TestClaimPayExhaustionCascade:
    """Tiny tier (annual 4000): A1 3000 PAID, A2 1000 APPROVED, B 1000
    SUBMITTED; paying A2 lands used exactly on the allowance."""

    def _setup(self, api):
        tiers = [tier_payload(annual_allowance_cents=4000, quarterly_cap_cents=10000,
                              per_claim_cap_cents=5000)]
        world = standard_world(tiers=tiers, plan_overrides={"name": "2026 Tiny"})
        submit_paid_claim(world, 3000, "R-A1")
        submit_approved_claim(world, 1000, "R-A2", service_date="2026-05-03T10:00:00Z")
        claim_b = submit_claim(world, 1000, "R-B", service_date="2026-05-04T10:00:00Z")
        return world, claim_b

    def test_exact_allowance_landing_flips_exhausted(self, api, admin_headers):
        """PRD §3.8: "If the payment pushes `used_cents` to at least
        `annual_allowance_cents`, the enrollment flips to `EXHAUSTED`"
        PRD §3.4: "When a payment pushes `used_cents` to at least
        `annual_allowance_cents`, the enrollment flips `ACTIVE → EXHAUSTED`"

        Design: Difficulty/transitive_cascade/claim_pay_exhaustion_cascade
        """
        world, _ = self._setup(api)
        # Find the APPROVED&UNPAID claim (A2) and pay it.
        claims, _ = validate_paginated(api.list_claims(admin_headers,
                                                       params={"enrollment_id": world["enrollment"]["id"]}))
        a2 = next(c for c in claims if c["review_status"] == "APPROVED" and c["payment_status"] == "UNPAID")
        paid = pay_claim(a2["id"])
        assert paid["approved_amount_cents"] == 1000

        enrollment = get_success_data(api.get_enrollment(world["enrollment"]["id"], admin_headers))
        assert enrollment["used_cents"] == 4000, f"3000 + 1000 must equal the 4000 allowance, got {enrollment['used_cents']}"
        assert enrollment["status"] == "EXHAUSTED", (
            f"used == annual allowance must flip to EXHAUSTED (boundary-inclusive), got {enrollment['status']}"
        )

    def test_open_claim_auto_rejected_and_reservation_released(self, api, admin_headers):
        """PRD §3.8: "every other claim on it still in `SUBMITTED`,
        `UNDER_REVIEW`, or `NEEDS_INFO` is auto-rejected, each releasing its
        enrollment reservation and any funding hold."

        Design: Difficulty/transitive_cascade/claim_pay_exhaustion_cascade
        """
        world, claim_b = self._setup(api)
        claims, _ = validate_paginated(api.list_claims(admin_headers,
                                                       params={"enrollment_id": world["enrollment"]["id"]}))
        a2 = next(c for c in claims if c["review_status"] == "APPROVED" and c["payment_status"] == "UNPAID")
        pay_claim(a2["id"])

        b_after = get_success_data(api.get_claim(claim_b["id"], admin_headers))
        assert b_after["review_status"] == "REJECTED", (
            f"exhaustion must cascade-reject the open claim, got {b_after['review_status']}"
        )
        enrollment = get_success_data(api.get_enrollment(world["enrollment"]["id"], admin_headers))
        assert enrollment["reserved_cents"] == 0, (
            f"the cascade rejection must release the 1000 reservation, got {enrollment['reserved_cents']}"
        )


def test_quarter_rollover_resets_usage(api, admin_headers):
    """PRD §2.5: "Second, crossing a calendar-quarter boundary rolls every
    enrollment's quarter window forward: the enrollment's `quarter_key` is
    updated to the new quarter (for example from 2026-Q1 to 2026-Q2) and its
    `quarter_used_cents` is reset to zero."

    Design: Corner/cross_cutting_complexity_layers/quarter_rollover_resets_usage
    """
    world = standard_world()
    submit_paid_claim(world, 3000, "R-Q")  # paid in 2026-Q2 (default clock 2026-05-01)

    set_clock("2026-07-01T00:00:00Z")
    allowance = get_success_data(api.get_enrollment_allowance(world["enrollment"]["id"], admin_headers))
    assert allowance["quarter_key"] == "2026-Q3", f"clock in July must roll to Q3, got {allowance['quarter_key']}"
    assert allowance["quarter_used_cents"] == 0, f"quarter usage must reset, got {allowance['quarter_used_cents']}"
    assert allowance["used_cents"] == 3000, f"annual ledger is unaffected, got {allowance['used_cents']}"


def test_close_enrollment_with_open_claim_rejected(api, admin_headers):
    """PRD §3.4: "A `BenefitsAdmin` may close an enrollment in `ACTIVE` or
    `EXHAUSTED`, but only while no claims sit in `SUBMITTED`, `UNDER_REVIEW`,
    or `NEEDS_INFO` — open claims block the close with
    `ERR_OPEN_CLAIMS_EXIST`, a guard bypassed solely by the member-termination
    cascade."

    Design: Corner/validations/close_enrollment_with_open_claim_rejected
    """
    world = standard_world()
    submit_claim(world, 1000, "R-OC")
    resp = api.close_enrollment(world["enrollment"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_OPEN_CLAIMS_EXIST)
    after = get_success_data(api.get_enrollment(world["enrollment"]["id"], admin_headers))
    assert after["status"] == "ACTIVE"

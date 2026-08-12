"""State machine behavior: the registration's cyclic renewal/suspension loops
and the PermitHolder's two independent standing dimensions (PRD §3.2, §3.6).
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    make_permit_holder_headers,
    create_community, create_eligible_holder, create_violation_payload,
    get_holder,
    setup_active_registration,
    set_clock,
    assert_instant_equal,
    COMMUNITY_ADMIN, OFFICER,
)


def _setup_sm1():
    """ACTIVE registration in the renewal window (clock 2027-03-15), wallet
    81000, no violations, ACTIVE insurance to 2027-12-31."""
    ctx = setup_active_registration(
        community_name="C-SM1", fleet_program_enabled=True, deposit_cents=100000,
        insurance_overrides={"policy_number": "N-SM1"})
    set_clock("2027-03-15T00:00:00Z")
    return ctx


class TestRegistrationCyclicRenewalAndSuspension:
    def test_renewal_loop_active_pending_active_with_expiry_extension(self):
        """PRD §3.6: "When the audited score is at least 70, the registration moves
        `RENEWAL_PENDING` → `ACTIVE`: the wallet is debited the recomputed total
        due (a shortfall is rejected with `ERR_INSUFFICIENT_FUNDS`), `paid_cents`
        accumulates the debit, `expiry_date` extends by 365 days from the previous
        expiry, and both the registration's and the holder's `version` increment."
        PRD §3.6: "A renewal opened while the registration is `ACTIVE` requires the
        current instant to fall within the renewal window: from
        `renewal_window_days` days before `expiry_date` through `expiry_date`
        itself, both bounds inclusive."

        Design: Difficulty/non_linear_state_machine/registration_cyclic_renewal_and_suspension
        """
        ctx = _setup_sm1()
        holder = ctx["holder"]
        reg = ctx["registration"]
        hh = make_permit_holder_headers(holder["id"])
        renewed = validate_success(api_client.renew_registration(reg["id"], hh), 200)
        assert renewed["status"] == "RENEWAL_PENDING"
        finalized = validate_success(
            api_client.finalize_renewal(reg["id"], COMMUNITY_ADMIN), 200)
        assert finalized["status"] == "ACTIVE"
        # PRD §3.6: "expiry_date extends by 365 days from the previous expiry".
        # Previous expiry 2027-05-01 + 365 days = 2028-04-30 (2028-02-29 falls
        # inside the span). Instant comparison: PRD pins the instant, not the
        # serialization.
        assert_instant_equal(finalized["expiry_date"], "2028-04-30T00:00:00Z")
        # Wallet: 100000 - 19000 (activation) - 19000 (renewal) = 62000
        assert get_holder(holder["id"])["wallet_balance_cents"] == 62000

    def test_suspension_loop_active_suspended_active(self):
        """PRD §3.6: "Outside the renewal flow, a `CommunityAdmin` may suspend an
        `ACTIVE` registration (`ACTIVE` → `SUSPENDED`), which revokes its `ACTIVE`
        route passes per §2.11. Reinstatement (`SUSPENDED` → `ACTIVE`) requires the
        holder not to be `BARRED`, the most recently finalized inspection to be
        `PASSED`, and — when the community requires insurance — an `ACTIVE` policy
        covering the vehicle; passes revoked earlier stay `REVOKED`."

        Design: Difficulty/non_linear_state_machine/registration_cyclic_renewal_and_suspension
        """
        ctx = _setup_sm1()
        reg = ctx["registration"]
        suspended = validate_success(
            api_client.suspend_registration(reg["id"], COMMUNITY_ADMIN), 200)
        assert suspended["status"] == "SUSPENDED"
        reinstated = validate_success(
            api_client.reinstate_registration(reg["id"], COMMUNITY_ADMIN), 200)
        assert reinstated["status"] == "ACTIVE"


def _setup_sm2():
    """ELIGIBLE holder with one UPHELD 4-point violation -> PROBATION."""
    community = create_community(name="C-SM2")
    holder = create_eligible_holder(community["id"], full_name="H SM2",
                                    birth_date="2010-05-01")
    vio = get_success_data(api_client.create_violation(
        create_violation_payload(holder["id"], violation_code="PARKING_VIOLATION",
                                 points_assessed=4, fine_cents=3000,
                                 occurred_at="2026-04-15T00:00:00Z"), OFFICER))
    get_success_data(api_client.uphold_violation(vio["id"], OFFICER))
    return community, holder, vio


class TestPermitHolderIndependentDimensions:
    def test_eligibility_suspension_leaves_compliance_untouched(self):
        """PRD §3.2: "An action gated on one dimension says nothing about the
        other: suspending a holder's eligibility leaves their compliance standing
        untouched."
        PRD §3.9: "Standing follows fixed thresholds — `BARRED` at 12 points or
        more (exactly 12 is `BARRED`), `PROBATION` at 4 through 11 points, and
        `GOOD_STANDING` at 3 or fewer — and the holder's `compliance_status` is
        rewritten accordingly."

        Design: Difficulty/non_linear_state_machine/permit_holder_independent_dimensions
        """
        _, holder, _ = _setup_sm2()
        before = get_holder(holder["id"])
        assert before["points_balance"] == 4
        assert before["compliance_status"] == "PROBATION"
        assert before["eligibility_status"] == "ELIGIBLE"
        suspended = validate_success(
            api_client.suspend_permit_holder(holder["id"], COMMUNITY_ADMIN), 200)
        assert suspended["eligibility_status"] == "SUSPENDED"
        assert suspended["compliance_status"] == "PROBATION", (
            "eligibility suspension must not move the compliance dimension")

    def test_compliance_recompute_leaves_eligibility_untouched(self):
        """PRD §3.9: "Dismissing moves a violation from either `FILED` or `UPHELD`
        to `DISMISSED` — dismissing an `UPHELD` violation is the appeal path — and
        when the dismissed violation had been `UPHELD`, the holder's
        `points_balance` and `compliance_status` are recomputed downward."
        PRD §3.2: "The second, `compliance_status`, moves through `GOOD_STANDING`,
        `PROBATION`, and `BARRED`; it is never written directly and is instead
        recomputed from the holder's `points_balance` whenever violation
        adjudication changes that balance."

        Design: Difficulty/non_linear_state_machine/permit_holder_independent_dimensions
        """
        _, holder, vio = _setup_sm2()
        validate_success(
            api_client.suspend_permit_holder(holder["id"], COMMUNITY_ADMIN), 200)
        validate_success(api_client.dismiss_violation(vio["id"], OFFICER), 200)
        after = get_holder(holder["id"])
        assert after["compliance_status"] == "GOOD_STANDING"
        assert after["points_balance"] == 0
        assert after["eligibility_status"] == "SUSPENDED", (
            "compliance recomputation must not move the eligibility dimension")

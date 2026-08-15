"""State registrations, insurance coverage, and the compliance posture."""
import test_helpers as th
from test_helpers import fixtures as fx

ADMIN = th.TEST_USERS["governance_admin_headers"]
OFFICER = th.TEST_USERS["compliance_officer_headers"]


class TestRegistrationBasics:
    def test_state_registration_duplicate_jurisdiction_rejected(self, api):
        """PRD §3.9: "A `ComplianceOfficer` creates a registration with
        `nonprofit_id`, a two-letter `state_code` unique within the nonprofit
        (`ERR_DUPLICATE_REGISTRATION`), an optional `renewal_cycle_months`
        defaulting to 12, the `current_period_end` at which the current authority
        expires, and an optional `contributions_in_state_cents` recording the most
        recent actual in-state contributions — leaving it null forces the estimated
        fee variant described below."

        Design: Corner/entities/state_registration_duplicate_jurisdiction_rejected
        """
        org = fx.create_nonprofit(name="O", ein="EIN-SR-1", receipts=1_000_000)
        fx.create_registration(org["id"], "CA", "2027-06-01T00:00:00Z")

        resp = api.create_registration(
            th.create_registration_payload(org["id"], "CA", "2028-01-01T00:00:00Z"),
            OFFICER)
        th.validate_error(resp, th.ApiErrorId.ERR_DUPLICATE_REGISTRATION)

    def test_renewal_too_early_rejected(self, api):
        """PRD §3.9: "From `REGISTERED` the window opens ninety days before the
        period end — submitting earlier is rejected with `ERR_RENEWAL_TOO_EARLY` —
        and from `RENEWAL_DUE` submission is already timely; a submission from any
        other state is rejected with `ERR_INVALID_STATE`."

        Design: Corner/validations/renewal_too_early_rejected
        """
        org = fx.create_nonprofit(name="O", ein="EIN-RE-1", receipts=1_000_000)
        # default clock 2026-08-01: 122 days before 2026-12-01 -> too early
        reg_ca = fx.create_registration(org["id"], "CA", "2026-12-01T00:00:00Z")
        # exactly 90 days out (2026-08-01 + 90d == 2026-10-30): window inclusive
        reg_ny = fx.create_registration(org["id"], "NY", "2026-10-30T00:00:00Z")

        resp = api.submit_renewal(
            reg_ca["id"], {"contributions_in_state_cents": 1_000_000,
                           "paid_fee_cents": 5_000}, OFFICER)
        th.validate_error(resp, th.ApiErrorId.ERR_RENEWAL_TOO_EARLY)

        submitted = th.validate_success(api.submit_renewal(
            reg_ny["id"], {"contributions_in_state_cents": 1_000_000,
                           "paid_fee_cents": 5_000}, OFFICER))
        assert submitted["status"] == "RENEWAL_SUBMITTED"

    def test_renewal_fee_mismatch_rejected(self, api):
        """PRD §3.9: "The payload's `paid_fee_cents` must equal the fee the system
        computes for the registration (`ERR_RENEWAL_FEE_MISMATCH`)."
        PRD §3.9: "The base then maps into a four-rung ladder whose boundaries
        belong to the lower rung: at most $25,000 (2,500,000 cents) pays a $50 base;
        above that and at most $100,000 pays $150; above that and at most $500,000
        pays $300; and above $500,000 pays a $500 base plus an overage surcharge of
        $10 for every started $1,000 increment by which the base exceeds $500,000 —
        the surcharge ceiled to whole increments before any other rounding, per the
        pinned order of §2.9."

        Design: Corner/calculations/renewal_fee_mismatch_rejected
        """
        org = fx.create_nonprofit(name="O", ein="EIN-FM-1", receipts=1_000_000)
        reg = fx.create_registration(org["id"], "CA", "2026-10-01T00:00:00Z")

        # contributions 5,000,000 -> tier 2 -> 15,000; one cent short fails
        resp = api.submit_renewal(
            reg["id"], {"contributions_in_state_cents": 5_000_000,
                        "paid_fee_cents": 14_999}, OFFICER)
        th.validate_error(resp, th.ApiErrorId.ERR_RENEWAL_FEE_MISMATCH)
        after_fail = th.validate_success(api.get_registration(reg["id"], OFFICER))
        assert after_fail["status"] == "REGISTERED", (
            "the failed submission must not mutate the registration")

        submitted = th.validate_success(api.submit_renewal(
            reg["id"], {"contributions_in_state_cents": 5_000_000,
                        "paid_fee_cents": 15_000}, OFFICER))
        assert submitted["status"] == "RENEWAL_SUBMITTED"
        assert submitted["renewal_fee_cents"] == 15_000


class TestRenewalFeeVariants:
    """Difficulty: dual_variant_calc / registration_fee_actual_vs_estimated_variant."""

    def test_estimated_variant_uses_ten_percent_of_receipts(self, api):
        """PRD §3.9: "The payload's `paid_fee_cents` must equal the fee the system
        computes for the registration (`ERR_RENEWAL_FEE_MISMATCH`). That fee prices
        off an effective contribution base in cents: when the submission supplies
        `contributions_in_state_cents` the **actual** variant prices from that
        figure — and the payload value is persisted on the registration — while an
        omitted figure falls back to the **estimated** variant, ten percent of the
        nonprofit's `annual_gross_receipts_cents` rounded half-up to whole cents,
        the same variant used for pre-submission previews of registrations whose
        contributions are null."
        PRD §3.9: "The base then maps into a four-rung ladder whose boundaries
        belong to the lower rung: at most $25,000 (2,500,000 cents) pays a $50 base;
        above that and at most $100,000 pays $150; above that and at most $500,000
        pays $300; and above $500,000 pays a $500 base plus an overage surcharge of
        $10 for every started $1,000 increment by which the base exceeds $500,000 —
        the surcharge ceiled to whole increments before any other rounding, per the
        pinned order of §2.9."

        Design: Difficulty/dual_variant_calc/registration_fee_actual_vs_estimated_variant
        """
        org = fx.create_nonprofit(name="Fee Org", ein="EIN-FEE-1",
                                  receipts=3_000_000_000)
        reg = fx.create_registration(org["id"], "CA", "2026-10-01T00:00:00Z")
        # ESTIMATED: E = 300,000,000 -> tier 4: 50,000 + ceil(250,000,000/100,000)*1,000
        submitted = th.validate_success(api.submit_renewal(
            reg["id"], {"paid_fee_cents": 2_550_000}, OFFICER))
        assert submitted["status"] == "RENEWAL_SUBMITTED"
        assert submitted["renewal_fee_cents"] == 2_550_000, (
            f"estimated base 300,000,000 lands in tier 4: 50,000 + 2,500,000 surcharge, got {submitted['renewal_fee_cents']}")

    def test_actual_variant_prices_from_payload_contributions(self, api):
        """PRD §3.9: "That fee prices off an effective contribution base in cents:
        when the submission supplies `contributions_in_state_cents` the **actual**
        variant prices from that figure — and the payload value is persisted on the
        registration — while an omitted figure falls back to the **estimated**
        variant, ten percent of the nonprofit's `annual_gross_receipts_cents`
        rounded half-up to whole cents, the same variant used for pre-submission
        previews of registrations whose contributions are null."
        PRD §3.9: "The base then maps into a four-rung ladder whose boundaries
        belong to the lower rung: at most $25,000 (2,500,000 cents) pays a $50 base;
        above that and at most $100,000 pays $150; above that and at most $500,000
        pays $300; and above $500,000 pays a $500 base plus an overage surcharge of
        $10 for every started $1,000 increment by which the base exceeds $500,000 —
        the surcharge ceiled to whole increments before any other rounding, per the
        pinned order of §2.9."

        Design: Difficulty/dual_variant_calc/registration_fee_actual_vs_estimated_variant
        """
        org = fx.create_nonprofit(name="Fee Org", ein="EIN-FEE-2",
                                  receipts=3_000_000_000)
        reg = fx.create_registration(org["id"], "NY", "2026-10-01T00:00:00Z")
        # ACTUAL: E = 20,000,000 -> tier 3 -> 30,000 (a different fee than ESTIMATED)
        submitted = th.validate_success(api.submit_renewal(
            reg["id"], {"contributions_in_state_cents": 20_000_000,
                        "paid_fee_cents": 30_000}, OFFICER))
        assert submitted["status"] == "RENEWAL_SUBMITTED"
        assert submitted["renewal_fee_cents"] == 30_000, (
            f"actual base 20,000,000 lands in tier 3, got {submitted['renewal_fee_cents']}")
        assert submitted["contributions_in_state_cents"] == 20_000_000


class TestRenewalFeeTierBoundary:
    """Difficulty: boundary_precision_check / renewal_fee_tier_floor_belongs_to_lower_tier."""

    def test_fee_tier1_at_exact_floor(self, api):
        """PRD §3.9: "The base then maps into a four-rung ladder whose boundaries
        belong to the lower rung: at most $25,000 (2,500,000 cents) pays a $50 base;
        above that and at most $100,000 pays $150; above that and at most $500,000
        pays $300; and above $500,000 pays a $500 base plus an overage surcharge of
        $10 for every started $1,000 increment by which the base exceeds $500,000 —
        the surcharge ceiled to whole increments before any other rounding, per the
        pinned order of §2.9."

        Design: Difficulty/boundary_precision_check/renewal_fee_tier_floor_belongs_to_lower_tier
        """
        org = fx.create_nonprofit(name="Tier Org", ein="EIN-TIER-1")
        reg = fx.create_registration(org["id"], "CA", "2026-10-01T00:00:00Z")
        submitted = th.validate_success(api.submit_renewal(
            reg["id"], {"contributions_in_state_cents": 2_500_000,
                        "paid_fee_cents": 5_000}, OFFICER))
        assert submitted["renewal_fee_cents"] == 5_000, (
            "E == 2,500,000 stays in tier 1 (floors belong to the lower rung)")

    def test_fee_tier2_one_cent_above_floor(self, api):
        """PRD §3.9: "The base then maps into a four-rung ladder whose boundaries
        belong to the lower rung: at most $25,000 (2,500,000 cents) pays a $50 base;
        above that and at most $100,000 pays $150; above that and at most $500,000
        pays $300; and above $500,000 pays a $500 base plus an overage surcharge of
        $10 for every started $1,000 increment by which the base exceeds $500,000 —
        the surcharge ceiled to whole increments before any other rounding, per the
        pinned order of §2.9."

        Design: Difficulty/boundary_precision_check/renewal_fee_tier_floor_belongs_to_lower_tier
        """
        org = fx.create_nonprofit(name="Tier Org", ein="EIN-TIER-2")
        reg = fx.create_registration(org["id"], "NY", "2026-10-01T00:00:00Z")
        submitted = th.validate_success(api.submit_renewal(
            reg["id"], {"contributions_in_state_cents": 2_500_001,
                        "paid_fee_cents": 15_000}, OFFICER))
        assert submitted["renewal_fee_cents"] == 15_000, (
            "one cent above the floor jumps to tier 2")


class TestReinstateRoundingOrder:
    """Difficulty: combinatorial_formula / renewal_fee_nested_rounding_order."""

    def _setup_lapsed(self, api):
        org = fx.create_nonprofit(name="Late Org", ein="EIN-LATE-1")
        # period already past at the default clock 2026-08-01
        reg = fx.create_registration(org["id"], "CA", "2026-07-01T00:00:00Z")
        fx.sweep(org["id"], as_officer=True)
        lapsed = th.validate_success(api.get_registration(reg["id"], OFFICER))
        assert lapsed["status"] == "LAPSED"
        return org, reg

    def test_reinstate_fee_pinned_rounding_order_accepted(self, api):
        """PRD §2.9: "The registration renewal fee has a pinned rounding order that
        must not be rearranged: the tier-4 overage surcharge is ceiled to a whole
        increment first, then the ten percent late fee — when it applies — is
        computed on the sum of base and surcharge and rounded half-up to whole
        cents, and only then are the components summed; computing the late fee on
        raw unrounded components would produce different cents."
        PRD §3.9: "Reinstatement from `LAPSED` follows the same fee machinery with a
        late fee of ten percent of the base-plus-surcharge subtotal, rounded half-up
        to whole cents, added on top; it resets `current_period_end` to the clock
        date plus `renewal_cycle_months`, persists the fee including the late
        component, and recomputes the posture, which may lift the organization out
        of `NON_COMPLIANT`."

        Design: Difficulty/combinatorial_formula/renewal_fee_nested_rounding_order
        """
        org, reg = self._setup_lapsed(api)
        # E = 50,123,456 -> tier 4: surcharge ceil(123,456/100,000)*1,000 == 2,000 FIRST,
        # subtotal 52,000, late fee round_half_up(5,200.0) == 5,200 -> total 57,200
        reinstated = th.validate_success(api.reinstate_registration(
            reg["id"], {"contributions_in_state_cents": 50_123_456,
                        "paid_fee_cents": 57_200}, OFFICER))
        assert reinstated["status"] == "REGISTERED"
        assert reinstated["renewal_fee_cents"] == 57_200, (
            f"only the pinned order's 57,200 is accepted, got {reinstated['renewal_fee_cents']}")
        th.assert_instant_eq(reinstated["current_period_end"], "2027-08-01T00:00:00Z",
            "reinstatement resets the period to the clock date + renewal_cycle_months")

    def test_reinstate_alternative_rounding_orders_rejected(self, api):
        """PRD §2.9: "The registration renewal fee has a pinned rounding order that
        must not be rearranged: the tier-4 overage surcharge is ceiled to a whole
        increment first, then the ten percent late fee — when it applies — is
        computed on the sum of base and surcharge and rounded half-up to whole
        cents, and only then are the components summed; computing the late fee on
        raw unrounded components would produce different cents."
        PRD §3.9: "The payload's `paid_fee_cents` must equal the fee the system
        computes for the registration (`ERR_RENEWAL_FEE_MISMATCH`)."

        Design: Difficulty/combinatorial_formula/renewal_fee_nested_rounding_order
        """
        org, reg = self._setup_lapsed(api)
        for wrong_fee in (56_100, 57_193):
            resp = api.reinstate_registration(
                reg["id"], {"contributions_in_state_cents": 50_123_456,
                            "paid_fee_cents": wrong_fee}, OFFICER)
            th.validate_error(resp, th.ApiErrorId.ERR_RENEWAL_FEE_MISMATCH)
        after = th.validate_success(api.get_registration(reg["id"], OFFICER))
        assert after["status"] == "LAPSED", "rejected payments leave the registration LAPSED"


class TestRenewalCycle:
    """Difficulty: non_linear_state_machine / registration_renewal_cycle_rolls_period."""

    def test_sweep_marks_registration_renewal_due(self, api):
        """PRD §3.9: "The sweep drives the calendar edges: a registration within
        sixty days of its period end — clock at or after sixty days before the end
        but still before it — becomes `RENEWAL_DUE`; one whose period end has passed
        becomes `LAPSED`, including a submitted-but-unconfirmed renewal whose period
        expired anyway."

        Design: Difficulty/non_linear_state_machine/registration_renewal_cycle_rolls_period
        """
        org = fx.create_nonprofit(name="Renew Org", ein="EIN-REN-1")
        reg = fx.create_registration(org["id"], "CA", "2026-09-15T00:00:00Z")
        fx.set_clock("2026-07-20T00:00:00Z")  # inside [2026-07-17, 2026-09-15)
        fx.sweep(org["id"], as_officer=True)
        due = th.validate_success(api.get_registration(reg["id"], OFFICER))
        assert due["status"] == "RENEWAL_DUE", (
            f"period end - 60d == 2026-07-17 <= clock < 2026-09-15, got {due['status']}")

    def test_submit_and_confirm_rolls_period_forward(self, api):
        """PRD §3.9: "Confirmation that the jurisdiction accepted the renewal rolls
        `current_period_end` forward by `renewal_cycle_months`, returns the
        registration to `REGISTERED`, and recomputes the posture, closing the
        renewal loop."
        PRD §3.9: "and from `RENEWAL_DUE` submission is already timely; a submission
        from any other state is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/registration_renewal_cycle_rolls_period
        """
        org = fx.create_nonprofit(name="Renew Org", ein="EIN-REN-2")
        reg = fx.create_registration(org["id"], "CA", "2026-09-15T00:00:00Z")
        fx.set_clock("2026-07-20T00:00:00Z")
        fx.sweep(org["id"], as_officer=True)

        submitted = th.validate_success(api.submit_renewal(
            reg["id"], {"contributions_in_state_cents": 5_000_000,
                        "paid_fee_cents": 15_000}, OFFICER))
        assert submitted["status"] == "RENEWAL_SUBMITTED"
        assert submitted["renewal_fee_cents"] == 15_000, (
            "tier 2: 5,000,000 in (2,500,000, 10,000,000]")

        confirmed = th.validate_success(api.confirm_renewal(reg["id"], OFFICER))
        assert confirmed["status"] == "REGISTERED"
        th.assert_instant_eq(confirmed["current_period_end"], "2027-09-15T00:00:00Z",
            "the loop closes with the period rolled forward exactly 12 months")


class TestInsuranceCoverage:
    def test_coverage_floor_exact_boundary(self, api):
        """PRD §3.9: "Binding enforces the coverage floor and the interval rules:
        the limit must be at least the ceiling of one quarter of the nonprofit's
        `annual_gross_receipts_cents` (`ERR_COVERAGE_BELOW_FLOOR`); a renewal with a
        negative gap is an overlap (`ERR_POLICY_OVERLAP`), and one with a positive
        gap requires `acknowledge_gap` to be true (`ERR_COVERAGE_GAP`); and the
        interval must not overlap any non-terminal policy of the same organization
        and type (`ERR_POLICY_OVERLAP`)."

        Design: Corner/validations/coverage_floor_exact_boundary
        """
        org = fx.create_nonprofit(name="O", ein="EIN-CF-1", receipts=100_000_000)
        # floor == ceil(0.25 * 100,000,000) == 25,000,000
        p1 = fx.create_policy(org["id"], coverage=24_999_999)
        resp = api.bind_policy(p1["id"], OFFICER)
        th.validate_error(resp, th.ApiErrorId.ERR_COVERAGE_BELOW_FLOOR)
        # retire the rejected quote so it no longer counts as a non-terminal policy
        fx.cancel_policy(p1["id"])

        p2 = fx.create_policy(org["id"], coverage=25_000_000, carrier="C2")
        bound = th.validate_success(api.bind_policy(p2["id"], OFFICER))
        assert bound["status"] == "BOUND", "exactly at the floor binds on >="

    def test_policy_activate_before_start_rejected(self, api):
        """PRD §3.9: "Activation is allowed only once the clock has reached the
        `policy_start_date` (`ERR_POLICY_NOT_YET_EFFECTIVE`) and moves the policy to
        `ACTIVE` with a posture recompute."

        Design: Corner/validations/policy_activate_before_start_rejected
        """
        org = fx.create_nonprofit(name="O", ein="EIN-PA-1", receipts=100_000_000)
        policy = fx.create_policy(org["id"], coverage=25_000_000,
                                  start="2027-01-01T00:00:00Z",
                                  end="2028-01-01T00:00:00Z")
        fx.bind_policy(policy["id"])

        resp = api.activate_policy(policy["id"], OFFICER)
        th.validate_error(resp, th.ApiErrorId.ERR_POLICY_NOT_YET_EFFECTIVE)

        fx.set_clock("2027-01-01T00:00:00Z")
        activated = th.validate_success(api.activate_policy(policy["id"], OFFICER))
        assert activated["status"] == "ACTIVE", (
            "activation succeeds once the clock reaches policy_start_date (>= boundary)")


class TestInsuranceRenewalIntervals:
    """Difficulty: resource_temporal_overlap / insurance_renewal_gap_and_overlap_detection."""

    def _setup_active_dno_chain(self, api):
        org = fx.create_nonprofit(name="Ins Org", ein="EIN-INS-1")
        p1 = fx.setup_active_dno(org["id"], coverage=2_000_000_000,
                                 start="2026-01-01T00:00:00Z",
                                 end="2027-01-01T00:00:00Z")
        return org, p1

    def test_renewal_gap_unacknowledged_and_overlap_rejected(self, api):
        """PRD §2.8: "A negative gap means the new policy starts before the prior
        ended, an overlap rejected with `ERR_POLICY_OVERLAP`; a zero gap is
        continuous coverage; a positive gap is a coverage lapse that must be
        explicitly acknowledged via `acknowledge_gap`, else `ERR_COVERAGE_GAP`."

        Design: Difficulty/resource_temporal_overlap/insurance_renewal_gap_and_overlap_detection
        """
        org, p1 = self._setup_active_dno_chain(api)
        # 1-day gap after the prior end, no acknowledgement
        p_gap = fx.create_policy(org["id"], coverage=2_000_000_000, premium=520_000,
                                 start="2027-01-02T00:00:00Z",
                                 end="2028-01-02T00:00:00Z", prior_policy_id=p1["id"])
        resp_gap = api.bind_policy(p_gap["id"], OFFICER)
        th.validate_error(resp_gap, th.ApiErrorId.ERR_COVERAGE_GAP)

        # starts before the prior policy's end -> negative gap
        p_ovl = fx.create_policy(org["id"], coverage=2_000_000_000, premium=520_000,
                                 start="2026-12-01T00:00:00Z",
                                 end="2027-12-01T00:00:00Z", prior_policy_id=p1["id"])
        resp_ovl = api.bind_policy(p_ovl["id"], OFFICER)
        th.validate_error(resp_ovl, th.ApiErrorId.ERR_POLICY_OVERLAP)

    def test_renewal_exact_abutment_binds(self, api):
        """PRD §2.8: "A negative gap means the new policy starts before the prior
        ended, an overlap rejected with `ERR_POLICY_OVERLAP`; a zero gap is
        continuous coverage; a positive gap is a coverage lapse that must be
        explicitly acknowledged via `acknowledge_gap`, else `ERR_COVERAGE_GAP`."
        PRD §2.8: "Independently of the renewal chain, a policy's half-open coverage
        interval must not overlap any other non-terminal policy — one in `QUOTED`,
        `BOUND`, or `ACTIVE` — of the same organization and the same `policy_type`:
        two intervals overlap when the new policy's start falls before the other's
        end and the other's start falls before the new policy's end, so abutting
        intervals are allowed."

        Design: Difficulty/resource_temporal_overlap/insurance_renewal_gap_and_overlap_detection
        """
        org, p1 = self._setup_active_dno_chain(api)
        p_ok = fx.create_policy(org["id"], coverage=2_000_000_000, premium=520_000,
                                start="2027-01-01T00:00:00Z",
                                end="2028-01-01T00:00:00Z", prior_policy_id=p1["id"])
        bound = th.validate_success(api.bind_policy(p_ok["id"], OFFICER))
        assert bound["status"] == "BOUND"
        assert bound["gap_days"] == 0, (
            f"start == prior end is continuous coverage, got gap_days {bound.get('gap_days')}")


class TestPostureAndLapseCascade:
    def test_registration_lapse_cascade_blocks_fundraising(self, api):
        """PRD §3.9: "The lapse fires the lapse chain of §2.10: the organization's
        posture is driven to `NON_COMPLIANT` while any registration is `LAPSED`
        (link 1), and that posture change withdraws every fundraising motion of the
        nonprofit still `INTRODUCED`, `VOTING_OPEN`, or `TABLED` (link 2)."
        PRD §3.9: "The posture is not merely informational: while it is
        `NON_COMPLIANT`, introducing a `FUNDRAISING` motion is rejected with
        `ERR_NONCOMPLIANT_POSTURE_BLOCKS`, and the lapse cascade of §2.10 withdraws
        the ones already in flight."

        Design: Corner/cross_cutting_layers/registration_lapse_cascade_blocks_fundraising
        """
        sc = fx.setup_org_with_board(num_directors=1, officers=("CHAIR", "TREASURER"),
                                     ein="EIN-LP-1", receipts=4_000_000_000)
        np_id = sc["nonprofit"]["id"]
        chair, treasurer, d1 = sc["chair"], sc["treasurer"], sc["members"][2]
        chair_headers = th.make_board_chair_headers(chair["id"])
        fx.setup_active_dno(np_id, coverage=1_000_000_000)
        fx.setup_filing_filed(np_id, treasurer, chair, [d1, treasurer], 2025,
                              preparer="staff-1")
        # period already in the past; LAPSED only once a sweep runs
        reg = fx.create_registration(np_id, "CA", "2026-07-01T00:00:00Z")

        member_ids = [m["id"] for m in sc["members"]]
        meeting = fx.setup_meeting_in_session(np_id, chair, member_ids,
                                              duration=90)
        motion = fx.setup_open_motion(np_id, meeting["id"], chair,
                                      title="Gala", category="FUNDRAISING")
        assert motion["status"] == "VOTING_OPEN", (
            "AT_RISK (delinquent COI filings) does not block introduction")

        swept = fx.sweep(np_id, as_officer=True)
        assert swept["compliance_posture"] == "NON_COMPLIANT"
        reg_after = th.validate_success(api.get_registration(reg["id"], OFFICER))
        assert reg_after["status"] == "LAPSED", "link 1: the expired registration lapses"
        motion_after = th.validate_success(api.get_motion(motion["id"], ADMIN))
        assert motion_after["status"] == "WITHDRAWN", (
            f"link 2: the in-flight FUNDRAISING motion is withdrawn, got {motion_after['status']}")

        resp = api.create_motion(
            th.create_motion_payload(np_id, meeting["id"], title="Raffle",
                                     category="FUNDRAISING"),
            chair_headers)
        th.validate_error(resp, th.ApiErrorId.ERR_NONCOMPLIANT_POSTURE_BLOCKS)

        ok = th.validate_success(api.create_motion(
            th.create_motion_payload(np_id, meeting["id"], title="Minutes approval",
                                     category="GOVERNANCE"),
            chair_headers), 201)
        assert ok["status"] == "INTRODUCED", (
            "the posture gate blocks only the FUNDRAISING category")

    def test_posture_ladder_to_compliant_then_fundraising_allowed(self, api):
        """PRD §3.9: "The posture is `NON_COMPLIANT` when any of the following
        holds: a registration stands `LAPSED`; the prior fiscal year's Form 990
        obligation is past due, meaning the fiscal year before the
        `current_fiscal_year` has no filing in `FILED`, `PUBLIC_DISCLOSED`, or
        `SUPERSEDED` while the clock has passed that filing's `filing_due_date`; or
        no `ACTIVE` `DNO` policy covers the clock date. Failing that, the posture is
        `AT_RISK` when any of the following holds: a registration stands
        `RENEWAL_DUE` or `RENEWAL_SUBMITTED`; a filing's `disclosure_overdue` is
        true; the active D&O policy's `policy_end_date` falls within thirty days of
        the clock with no `BOUND` or `ACTIVE` successor whose `policy_start_date`
        falls on or before the current policy's end; or at least one `ACTIVE`
        member's current-fiscal-year disclosure is missing or still `FILED` or
        `UNDER_REVIEW` more than ninety days into the fiscal year. Otherwise the
        posture is `COMPLIANT`."
        PRD §3.9: "The posture is not merely informational: while it is
        `NON_COMPLIANT`, introducing a `FUNDRAISING` motion is rejected with
        `ERR_NONCOMPLIANT_POSTURE_BLOCKS`, and the lapse cascade of §2.10 withdraws
        the ones already in flight."

        Design: Corner/cross_cutting_layers/posture_ladder_to_compliant_then_fundraising_allowed
        """
        sc = fx.setup_org_with_board(num_directors=0, officers=("CHAIR", "TREASURER"),
                                     ein="EIN-PL-1", receipts=4_000_000_000)
        np_id = sc["nonprofit"]["id"]
        chair, treasurer = sc["chair"], sc["treasurer"]

        p0 = th.validate_success(api.get_nonprofit(np_id, ADMIN))
        assert p0["compliance_posture"] == "NON_COMPLIANT", (
            "no D&O coverage alone is sufficient for NON_COMPLIANT")

        fx.setup_active_dno(np_id, coverage=1_000_000_000,
                            start="2026-01-01T00:00:00Z", end="2027-06-01T00:00:00Z")
        p1 = th.validate_success(api.get_nonprofit(np_id, ADMIN))
        assert p1["compliance_posture"] == "NON_COMPLIANT", (
            "the FY2025 990 obligation is still past due")

        # one review suffices: ceil(0.5 * 2 ACTIVE) == 1
        fx.setup_filing_filed(np_id, treasurer, chair, [treasurer], 2025,
                              preparer="staff-1")
        p2 = th.validate_success(api.get_nonprofit(np_id, ADMIN))
        assert p2["compliance_posture"] == "AT_RISK", (
            "both directors are COI-delinquent past FY-start + 90 days")

        fx.clear_coi_for_all(np_id, [chair, treasurer], fiscal_year=2026)
        p3 = th.validate_success(api.get_nonprofit(np_id, ADMIN))
        assert p3["compliance_posture"] == "COMPLIANT", (
            "all four inputs remediated: D&O active, 990 filed, disclosures cleared")

        meeting = fx.create_meeting(np_id, start="2026-08-20T10:00:00Z")
        motion = th.validate_success(api.create_motion(
            th.create_motion_payload(np_id, meeting["id"], title="Annual gala",
                                     category="FUNDRAISING"),
            th.make_board_chair_headers(chair["id"])), 201)
        assert motion["status"] == "INTRODUCED"


class TestListPagination:
    def test_list_pagination_limit_offset_interaction(self, api):
        """PRD §2.3: "For endpoints that return lists of resources, pagination is
        controlled via query parameters. The `limit` parameter specifies the maximum
        number of items to return; if not provided, it defaults to 10, with a
        minimum of 1 and a maximum of 100. The `offset` parameter specifies the
        number of items to skip and defaults to 0. Unless otherwise specified, all
        list endpoints return resources sorted by their creation timestamp in
        ascending order. Paginated list responses include `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Corner/endpoints/list_pagination_limit_offset_interaction
        """
        org = fx.create_nonprofit(name="O", ein="EIN-PG-1", receipts=1_000_000)
        for state in ("CA", "NY", "TX"):
            fx.create_registration(org["id"], state, "2027-01-01T00:00:00Z")

        data_all, meta_all = th.validate_paginated(api.list_registrations(
            OFFICER, params={"nonprofit_id": org["id"]}))
        assert meta_all["total_count"] == 3
        assert meta_all["has_more"] is False
        assert len(data_all) == 3

        page1, meta1 = th.validate_paginated(api.list_registrations(
            OFFICER, params={"nonprofit_id": org["id"], "limit": 2}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2

        page2, meta2 = th.validate_paginated(api.list_registrations(
            OFFICER, params={"nonprofit_id": org["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert meta2["offset"] == 2

        paged_ids = [r["id"] for r in page1] + [r["id"] for r in page2]
        assert len(set(paged_ids)) == 3, (
            "the two pages must cover the same 3 registrations with no duplicates")
        assert set(paged_ids) == {r["id"] for r in data_all}

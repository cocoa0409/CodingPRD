"""Cancellation approval gates and statutory notice dispatch: scheduling
boundaries, segregation of duties, notice-set completeness, mailing windows,
and the notice lifecycle.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_cancellation,
    attach_interest,
    create_active_profile,
    create_cancellation_case_payload,
    create_holder,
    dispatch_cancellation_notices,
    dispatch_payload,
    issue_policy,
    make_compliance_officer_headers,
    make_underwriter_headers,
    notice_entry,
    open_cancellation_case,
    setup_active_policy,
    get_policy,
    api_client,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx

OFFICER = TEST_USERS["compliance_officer_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]


def _pending_case(state_code, clock="2026-08-01T00:00:00Z", **profile_over):
    """ACTIVE policy with a PENDING_APPROVAL NONPAYMENT case."""
    profile, holder, policy = setup_active_policy(state_code, clock=clock, profile_over=profile_over)
    case = open_cancellation_case(policy, ground_code="NONPAYMENT")
    return profile, holder, policy, case


class TestApprovalGates:
    def test_second_approve_on_approved_case_rejected(self, api):
        """PRD §3.4: "Approval moves the case `PENDING_APPROVAL → APPROVED`,
        stores the scheduled date on the case, moves the policy `ACTIVE →
        CANCEL_PENDING`, and bumps the policy's `version`." An `APPROVED` case
        does not admit approval again: "the target resource must be in a state
        that admits the requested transition (`ERR_INVALID_STATE`)" (§2.11).

        Design: Corner/state_machines/cancel_case_approve_from_draft_wrong_state_rejected
        """
        _p, _h, _pol, case = _pending_case("KY")
        approve_cancellation(case["id"], "2026-08-20")

        resp = api.approve_cancellation_case(
            case["id"], {"scheduled_effective_date": "2026-08-21"}, OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        current = fx.get_cancellation_case(case["id"])
        assert current["status"] == "APPROVED"
        assert current["scheduled_effective_date"] == "2026-08-20", (
            "a rejected re-approval must not move the stored scheduled date"
        )

    def test_effective_date_equal_to_earliest_is_permitted(self, api):
        """PRD §3.4: "The approval payload then supplies the
        `scheduled_effective_date`, which must be the same as or later than the
        case's `earliest_effective_date` — an earlier date is rejected with
        `ERR_EFFECTIVE_DATE_TOO_EARLY`, while scheduling exactly on the
        earliest date is permitted."

        Design: Corner/validations/effective_date_equal_to_earliest_is_permitted
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        profile = create_active_profile("VA")
        holder1 = create_holder(full_name="Va One", email="va1@x.com")
        holder2 = create_holder(full_name="Va Two", email="va2@x.com")
        policy1 = issue_policy(profile["id"], holder1["id"], "P-VA-1", total_premium_cents=10000)
        policy2 = issue_policy(profile["id"], holder2["id"], "P-VA-2", total_premium_cents=10000)
        case1 = open_cancellation_case(policy1, ground_code="NONPAYMENT")
        case2 = open_cancellation_case(policy2, ground_code="NONPAYMENT")
        # NONPAYMENT floor: requested 2026-08-01 + 10 days = 2026-08-11.
        assert case1["earliest_effective_date"] == "2026-08-11"
        assert case2["earliest_effective_date"] == "2026-08-11"

        approved = validate_success(
            api.approve_cancellation_case(
                case1["id"], {"scheduled_effective_date": "2026-08-11"}, OFFICER
            )
        )
        assert approved["status"] == "APPROVED"

        too_early = api.approve_cancellation_case(
            case2["id"], {"scheduled_effective_date": "2026-08-10"}, OFFICER
        )
        validate_error(too_early, ApiErrorId.ERR_EFFECTIVE_DATE_TOO_EARLY)

    def test_segregation_of_duties_same_operator_approve_rejected(self, api):
        """PRD §3.4: "Segregation of duties comes first: the approving
        officer's `X-User-ID` must differ from the `X-User-ID` that created
        the case, or approval is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/segregation_of_duties_same_officer_approve_rejected
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        profile = create_active_profile("TN")
        holder = create_holder(full_name="Tn Insured", email="tn@x.com")
        policy = issue_policy(profile["id"], holder["id"], "P-TN-1", total_premium_cents=10000)
        case = open_cancellation_case(
            policy, ground_code="NONPAYMENT", creator_headers=make_underwriter_headers("shared-op-1")
        )

        resp = api.approve_cancellation_case(
            case["id"],
            {"scheduled_effective_date": "2026-08-20"},
            make_compliance_officer_headers("shared-op-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        current = fx.get_cancellation_case(case["id"])
        assert current["status"] == "PENDING_APPROVAL"

    def test_state_check_masks_temporal_check_on_approve(self, api):
        """PRD §2.11: "Every request passes through the same ordered gauntlet,
        and a failure at any tier masks every later tier." State admissibility
        (tier 4, `ERR_INVALID_STATE`) precedes temporal boundaries (tier 8,
        `ERR_EFFECTIVE_DATE_TOO_EARLY`), so approving a `WITHDRAWN` case
        reports the state failure even when the supplied date is also too
        early.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_approve
        """
        _p, _h, _pol, case = _pending_case("ID")
        assert case["earliest_effective_date"] == "2026-08-11"
        withdrawn = validate_success(api.withdraw_cancellation_case(case["id"], UNDERWRITER))
        assert withdrawn["status"] == "WITHDRAWN"

        resp = api.approve_cancellation_case(
            case["id"], {"scheduled_effective_date": "2026-08-05"}, OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_withdrawn_case_unchanged_and_temporal_rule_live(self, api):
        """PRD §2.11: "Every request passes through the same ordered gauntlet,
        and a failure at any tier masks every later tier."
        PRD §3.4: "The approval payload then supplies the
        `scheduled_effective_date`, which must be the same as or later than the
        case's `earliest_effective_date` — an earlier date is rejected with
        `ERR_EFFECTIVE_DATE_TOO_EARLY`, while scheduling exactly on the
        earliest date is permitted."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_approve
        """
        profile, holder, policy, case = _pending_case("ID")
        validate_success(api.withdraw_cancellation_case(case["id"], UNDERWRITER))

        resp = api.approve_cancellation_case(
            case["id"], {"scheduled_effective_date": "2026-08-05"}, OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert fx.get_cancellation_case(case["id"])["status"] == "WITHDRAWN"

        # Isolated temporal failure on a still-pending case confirms the
        # masked tier-8 rule exists and fires when state admissibility passes.
        policy2 = issue_policy(profile["id"], holder["id"], "P-ID-2", total_premium_cents=30000)
        case2 = open_cancellation_case(policy2, ground_code="NONPAYMENT")
        early = api.approve_cancellation_case(
            case2["id"], {"scheduled_effective_date": "2026-08-05"}, OFFICER
        )
        validate_error(early, ApiErrorId.ERR_EFFECTIVE_DATE_TOO_EARLY)


class TestNoticeDispatch:
    def test_interest_policy_mismatch_on_dispatch_rejected(self, api):
        """PRD §3.4: "Every interest-addressed notice must name its
        `insured_interest_id`, and that interest must belong to the same
        policy as the case: a reference to another policy's interest fails
        with `ERR_INTEREST_POLICY_MISMATCH`."

        Design: Corner/validations/interest_policy_mismatch_on_dispatch_rejected
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        profile = create_active_profile("WV")
        holder = create_holder(full_name="Wv Insured", email="wv@x.com")
        policy_a = issue_policy(profile["id"], holder["id"], "P-WV-A", total_premium_cents=10000)
        policy_b = issue_policy(profile["id"], holder["id"], "P-WV-B", total_premium_cents=10000)
        interest_b = attach_interest(
            policy_b["id"], interest_type="MORTGAGEE", institution_name="Bank B"
        )
        case = open_cancellation_case(policy_a, ground_code="NONPAYMENT")
        approve_cancellation(case["id"], "2026-08-20")

        notices = [
            notice_entry("POLICYHOLDER", "2026-08-01", "T-WV-1"),
            notice_entry("MORTGAGEE", "2026-08-01", "T-WV-2", insured_interest_id=interest_b["id"]),
        ]
        resp = api.dispatch_cancellation_notices(case["id"], dispatch_payload(notices), UNDERWRITER)
        validate_error(resp, ApiErrorId.ERR_INTEREST_POLICY_MISMATCH)

        current = fx.get_cancellation_case(case["id"])
        assert current["status"] == "APPROVED", "a rejected dispatch must not advance the case"
        created = get_success_data(api.list_notices(OFFICER, params={"cancellation_case_id": case["id"]}))
        assert created == [], "a rejected dispatch must not create any NoticeRecords"

    def test_mailing_date_in_future_rejected(self, api):
        """PRD §3.4: "No `mailed_on_date` may lie later than the current clock
        date (`ERR_MAILING_DATE_IN_FUTURE`)."

        Design: Corner/errors/mailing_date_in_future_rejected
        """
        _p, _h, _pol, case = _pending_case("MA")
        approve_cancellation(case["id"], "2026-09-01")

        notices = [notice_entry("POLICYHOLDER", "2026-08-15", "T-MA-1")]
        resp = api.dispatch_cancellation_notices(case["id"], dispatch_payload(notices), UNDERWRITER)
        validate_error(resp, ApiErrorId.ERR_MAILING_DATE_IN_FUTURE)

    def test_notice_period_shortfall_for_mortgagee_rejected(self, api):
        """PRD §3.4: "And each notice must leave enough statutory runway: the
        interval from a notice's `mailed_on_date` to the
        `scheduled_effective_date` must be at least the days owed to that
        recipient — the applicable base tier for the policyholder notice,
        `mortgagee_notice_days` for each interest notice — or the dispatch
        fails with `ERR_NOTICE_PERIOD_SHORTFALL`."

        Design: Corner/errors/notice_period_shortfall_for_mortgagee_rejected
        """
        fx.set_clock("2026-08-05T00:00:00Z")
        profile = create_active_profile("GU")
        holder = create_holder(full_name="Gu Insured", email="gu@x.com")
        policy = issue_policy(profile["id"], holder["id"], "P-GU-1", total_premium_cents=10000)
        interest = attach_interest(policy["id"], interest_type="MORTGAGEE", institution_name="Bank G")
        case = open_cancellation_case(policy, ground_code="NONPAYMENT")
        # max(10, 45) = 45 days from 2026-08-05 -> floor 2026-09-19.
        assert case["earliest_effective_date"] == "2026-09-19"
        approve_cancellation(case["id"], "2026-09-19")

        # Advance clock to 2026-08-06 so a mortgagee notice mailed "today" is not
        # in the future, but 2026-08-06 + 45 = 2026-09-20 > scheduled 2026-09-19,
        # so the mortgagee shortfall rule fires.
        fx.set_clock("2026-08-06T00:00:00Z")
        notices = [
            notice_entry("POLICYHOLDER", "2026-08-05", "T-GU-1"),
            notice_entry("MORTGAGEE", "2026-08-06", "T-GU-2", insured_interest_id=interest["id"]),
        ]
        resp = api.dispatch_cancellation_notices(case["id"], dispatch_payload(notices), UNDERWRITER)
        validate_error(resp, ApiErrorId.ERR_NOTICE_PERIOD_SHORTFALL)

        current = fx.get_cancellation_case(case["id"])
        assert current["status"] == "APPROVED"

    def test_dispatch_creates_one_record_per_recipient(self, api):
        """PRD §3.4: "The set must contain exactly one notice addressed to the
        `POLICYHOLDER` plus exactly one notice per insured interest on the
        policy, each interest notice bearing a `recipient_kind` that matches
        that interest's `interest_type` — `MORTGAGEE`, `LIENHOLDER`, or
        `ADDITIONAL_INTEREST`" and "A successful dispatch creates one
        NoticeRecord per payload entry, each born `MAILED`, each serving
        exactly one case — a cancellation notice sets `cancellation_case_id`
        and leaves `nonrenewal_case_id` unset — and moves the case `APPROVED →
        NOTICE_SENT`."

        Design: Corner/endpoints/dispatch_notices_creates_one_record_per_recipient
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        profile = create_active_profile("MS")
        holder = create_holder(full_name="Ms Insured", email="ms@x.com")
        policy = issue_policy(profile["id"], holder["id"], "P-MS-1", total_premium_cents=10000)
        mortgagee = attach_interest(policy["id"], interest_type="MORTGAGEE", institution_name="Bank M")
        additional = attach_interest(
            policy["id"], interest_type="ADDITIONAL_INTEREST", institution_name="HOA",
            mailing_address="3 Hoa Ct",
        )
        case = open_cancellation_case(policy, ground_code="NONPAYMENT")
        approve_cancellation(case["id"], "2026-09-19")

        notices = dispatch_cancellation_notices(
            case["id"], "2026-08-01", interests=[mortgagee, additional], tracking_prefix="T-MS"
        )
        assert len(notices) == 3, f"one record per recipient, got {len(notices)}"
        for record in notices:
            assert record["status"] == "MAILED"
            assert record["cancellation_case_id"] == case["id"]
            assert record.get("nonrenewal_case_id") is None

        by_kind = {n["recipient_kind"]: n for n in notices}
        assert by_kind["POLICYHOLDER"].get("insured_interest_id") is None
        assert by_kind["MORTGAGEE"]["insured_interest_id"] == mortgagee["id"]
        assert by_kind["ADDITIONAL_INTEREST"]["insured_interest_id"] == additional["id"]

        current = fx.get_cancellation_case(case["id"])
        assert current["status"] == "NOTICE_SENT"


class TestNoticeLifecycle:
    def test_confirm_delivery_from_terminal_undeliverable_rejected(self, api):
        """PRD §3.4: "From `MAILED`, an `Underwriter` can confirm delivery,
        moving the record to `DELIVERY_CONFIRMED`, or mark the piece
        `RETURNED_UNDELIVERABLE`; both outcomes are terminal."

        Design: Corner/state_machines/notice_confirm_delivery_from_terminal_rejected
        """
        _p, _h, _pol, case = _pending_case("ME")
        approve_cancellation(case["id"], "2026-08-20")
        notices = dispatch_cancellation_notices(case["id"], "2026-08-01", tracking_prefix="T-ME")
        notice_id = notices[0]["id"]

        returned = validate_success(api.mark_undeliverable(notice_id, UNDERWRITER))
        assert returned["status"] == "RETURNED_UNDELIVERABLE"

        resp = api.confirm_delivery(notice_id, UNDERWRITER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        current = get_success_data(api.get_notice(notice_id, OFFICER))
        assert current["status"] == "RETURNED_UNDELIVERABLE"

    def test_undeliverable_notice_blocks_effectiveness_sweep(self, api):
        """PRD §3.4: "An undeliverable notice is not a clerical footnote:
        while any notice for a case is `QUEUED` or `RETURNED_UNDELIVERABLE`,
        the effectiveness sweep refuses to let the cancellation take effect,
        the blocked case is surfaced with `ERR_NOTICE_NOT_MAILED`, and the
        policy remains `CANCEL_PENDING` until a replacement notice has been
        dispatched and mailed."

        Design: Corner/state_machines/undeliverable_notice_blocks_effectiveness_sweep
        """
        _p, _h, policy, case = _pending_case("NH")
        approve_cancellation(case["id"], "2026-08-20")
        notices = dispatch_cancellation_notices(case["id"], "2026-08-01", tracking_prefix="T-NH")

        fx.set_clock("2026-08-05T00:00:00Z")
        validate_success(api.mark_undeliverable(notices[0]["id"], UNDERWRITER))

        fx.set_clock("2026-08-21T00:00:00Z")
        policy_now = get_policy(policy["id"])
        case_now = fx.get_cancellation_case(case["id"])
        assert policy_now["status"] == "CANCEL_PENDING", (
            "the sweep must refuse effectiveness while a notice is undeliverable"
        )
        assert case_now["status"] == "NOTICE_SENT"

        ledger = fx.policy_ledger(policy["id"])
        from test_helpers import assert_no_return_entries

        assert_no_return_entries(ledger)

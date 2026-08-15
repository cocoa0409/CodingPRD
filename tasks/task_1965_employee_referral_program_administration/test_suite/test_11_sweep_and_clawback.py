"""Ops-sweep transitions: retention, departure, clawback, expiry, campaign end
(PRD §3.5, §3.2, §3.4)."""
from test_helpers import (
    validate_success,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_employee_headers,
    make_recruiter_headers,
    create_employee,
    create_open_requisition,
    create_active_policy,
    create_active_campaign,
    submit_referral,
    setup_program,
    setup_verified_tax_profile,
    advance_referral_to_offer,
    hire_referral,
    get_referral,
    get_campaign,
    get_employee,
    get_milestone,
    get_hire_milestone,
    get_retention_milestone,
    create_open_batch,
    add_milestone_to_batch,
    set_clock,
    ops_evaluate,
    create_referral_payload,
    api_client,
)


def _hire_one(api, program, emp, candidate_email="c1@x.com", hire_date="2026-08-01T00:00:00Z"):
    ref = submit_referral(emp["id"], program["req"]["id"], candidate_email=candidate_email,
                          candidate_full_name="C One")
    advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
    hire_referral(ref["id"], program["hm"]["id"], hire_date=hire_date)
    return ref


class TestRetentionFailedKeepsHire:
    def test_retention_failed_forfeits_retention_but_keeps_hire(self, api):
        """PRD §3.5: "any referral still `HIRED` whose candidate is `DEPARTED` with a
        `departed_at` earlier than `retention_due_at` moves to `RETENTION_FAILED`: the
        `RETENTION` milestone transitions from `PENDING` to `FORFEITED`, the remaining
        campaign reservation is released, the `HIRE` milestone is explicitly *not*
        clawed back (the hire bonus was earned at hire), and a `RETENTION_FAILED` event
        is appended."
        PRD §3.5: "Departures enter the system when a `Recruiter` (or `TalentAdmin`)
        records that a hired candidate left the company, supplying `terminated_at`".

        Departure effective 2026-09-01 (before retention due 2027-01-28): the sweep flips
        the referral to RETENTION_FAILED, forfeits only the RETENTION milestone.

        Design: Corner/state_machines/retention_failed_forfeits_retention_but_keeps_hire
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=program["req"]["id"],
                candidate_email="c1@x.com", candidate_full_name="C One",
            ),
            make_employee_headers(emp["id"]),
        )
        ref = validate_success(resp, 201)
        cand_id = ref["candidate_id"]
        advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
        hire_referral(ref["id"], program["hm"]["id"])

        rec_h = make_recruiter_headers(program["rec"]["id"])
        get_success_data(
            api.record_departure(cand_id, {"terminated_at": "2026-09-01T00:00:00Z"}, rec_h)
        )
        set_clock("2026-09-02T00:00:00Z")

        sweep = ops_evaluate()
        assert sweep["retention_failed"] == 1
        assert sweep["retention_earned"] == 0

        ref_now = get_referral(ref["id"])
        assert ref_now["status"] == "RETENTION_FAILED"

        pp = TEST_USERS["payroll_processor_headers"]
        milestones = get_success_data(api.list_referral_milestones(ref["id"], pp))
        by_kind = {m["kind"]: m for m in milestones}
        assert by_kind["RETENTION"]["status"] == "FORFEITED"
        assert by_kind["HIRE"]["status"] == "EARNED", (
            "the HIRE milestone is explicitly not clawed back"
        )

        cand_now = get_success_data(api.get_candidate(cand_id, rec_h))
        assert cand_now["global_status"] == "DEPARTED"


class TestClawbackOfPaidRetention:
    def test_clawback_of_paid_retention_after_late_departure(self, api):
        """PRD §3.5: "When a candidate is `DEPARTED` with `departed_at` earlier than the
        referral's `clawback_until`, and the referral's `RETENTION` milestone is `PAID`,
        that milestone transitions to `CLAWED_BACK`: its `recovery_status` is set to
        `PENDING` (money is owed back), the retention uplift share is released from the
        campaign's `spent_cents` (which, on an `EXHAUSTED` campaign, may flip it back to
        `ACTIVE`), and the referrer's annual accumulators subtract the milestone's
        `amount_cents` for the current calendar year."
        PRD §3.5: "The `annual_provisional_cents` accumulator sums the `amount_cents` of
        milestones in `EARNED`, `APPROVED`, `BATCHED`, or `PAID` status, then subtracts
        the `amount_cents` of milestones in `CLAWED_BACK`."

        Retention earned+paid in 2027 (210000 on SENIOR gross 300000 -> 30/70 split:
        HIRE 90000, RET 210000); departure 2027-02-15 < clawback_until 2027-04-28 claws
        it back. (Post-clawback accumulator *values* are not asserted: PRD §3.5's
        status-set formula and its clawback sentence "the accumulators subtract the
        milestone's amount_cents" diverge for a PAID -> CLAWED_BACK milestone, so no
        single value is uniquely derivable.)

        Design: Corner/state_machines/clawback_of_paid_retention_after_late_departure
        """
        program = setup_program(
            req_overrides={"level": "SENIOR", "req_number": "REQ-SR-1", "title": "Sr Engineer"},
        )
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        setup_verified_tax_profile(emp["id"])
        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=program["req"]["id"],
                candidate_email="c1@x.com", candidate_full_name="C One",
            ),
            make_employee_headers(emp["id"]),
        )
        ref = validate_success(resp, 201)
        cand_id = ref["candidate_id"]
        advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
        hire_referral(ref["id"], program["hm"]["id"])

        # Earn retention at 2027-01-28 and push it through payroll to PAID
        set_clock("2027-01-28T00:00:00Z")
        ops_evaluate()
        ms_ret = get_retention_milestone(ref["id"])
        assert ms_ret["status"] == "EARNED"

        pp = TEST_USERS["payroll_processor_headers"]
        ta = TEST_USERS["talent_admin_headers"]
        get_success_data(api.approve_milestone(ms_ret["id"], pp))
        batch = create_open_batch(period_label="2027-01B")
        add_milestone_to_batch(batch["id"], ms_ret["id"], batch["version"])
        get_success_data(api.seal_payroll_batch(batch["id"], pp))
        get_success_data(api.export_payroll_batch(batch["id"], pp))
        get_success_data(api.confirm_paid_payroll_batch(batch["id"], ta))
        ms_paid = get_milestone(ms_ret["id"])
        assert ms_paid["status"] == "PAID"

        # Depart inside the clawback window and sweep
        rec_h = make_recruiter_headers(program["rec"]["id"])
        get_success_data(
            api.record_departure(cand_id, {"terminated_at": "2027-02-15T00:00:00Z"}, rec_h)
        )
        set_clock("2027-02-20T00:00:00Z")
        sweep = ops_evaluate()
        assert sweep["clawed_back"] == 1

        ms_now = get_milestone(ms_ret["id"])
        assert ms_now["status"] == "CLAWED_BACK"
        assert ms_now["recovery_status"] == "PENDING"

        ref_now = get_referral(ref["id"])
        assert ref_now["status"] == "COMPLETED", "clawback does not rewrite the referral outcome"


class TestCampaignAutoEndBySweep:
    def test_campaign_auto_end_by_sweep_releases_reservation(self, api):
        """PRD §3.2: "the operations sweep of §3.5 ends any `ACTIVE` or `PAUSED`
        campaign whose `window_end` has passed, moving it to `ENDED`. A `TalentAdmin` may
        also end a campaign outright from any non-terminal state — `DRAFT`, `ACTIVE`,
        `PAUSED`, or `EXHAUSTED` — moving it to `CANCELLED`. Ending, in either form,
        releases outstanding reservations: every attached non-terminal referral keeps its
        `campaign_id` for audit purposes, but the unpaid share of its uplift is released
        from the campaign's `reserved_cents`, while uplift already earned stays in
        `spent_cents`."
        PRD §3.2: "A pinned invariant holds at all times: reserved plus spent plus
        remaining always equals `budget_cents`".

        After the clock passes window_end the sweep ends the campaign, restores
        remaining to the full budget, and leaves the referral SUBMITTED with campaign_id.

        Design: Corner/state_machines/campaign_auto_end_by_sweep_releases_reservation
        """
        create_active_policy()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        req = create_open_requisition(
            req_number="REQ-SR-1", title="Sr Engineer", level="SENIOR", hard_to_fill=True,
        )
        camp = create_active_campaign(
            req["id"], budget_cents=500000, name="short",
            window_start="2026-07-01T00:00:00Z", window_end="2026-08-15T00:00:00Z",
        )
        ref = submit_referral(emp["id"], req["id"], candidate_email="c1@x.com",
                              candidate_full_name="C One")

        set_clock("2026-08-16T00:00:00Z")
        sweep = ops_evaluate()
        assert sweep["campaigns_ended"] == 1

        camp_now = get_campaign(camp["id"])
        assert camp_now["status"] == "ENDED"
        assert camp_now["reserved_cents"] == 0
        assert camp_now["spent_cents"] == 0
        assert camp_now["remaining_cents"] == 500000

        ref_now = get_referral(ref["id"])
        assert ref_now["status"] == "SUBMITTED", "campaign end does not terminate the referral"
        assert ref_now["campaign_id"] == camp["id"]


class TestReferralExpiryBySweep:
    def test_referral_expiry_by_sweep(self, api):
        """PRD §3.4: "The operations sweep (§3.5) expires any referral still in
        `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_INFO` once the logical now is strictly
        later than `submitted_at` plus the pinned policy's `referral_expiry_days`,
        moving it to `EXPIRED`".
        PRD §3.2: "`referral_expiry_days` 45".

        Submitted at the default clock 2026-08-01; at 2026-09-16 (46 days later, strictly
        later than 2026-09-15) the sweep expires it.

        Design: Corner/state_machines/referral_expiry_by_sweep
        """
        create_active_policy()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        req = create_open_requisition()
        ref = submit_referral(emp["id"], req["id"], candidate_email="c1@x.com",
                              candidate_full_name="C One")

        set_clock("2026-09-16T00:00:00Z")
        sweep = ops_evaluate()
        assert sweep["expired"] == 1

        ref_now = get_referral(ref["id"])
        assert ref_now["status"] == "EXPIRED"

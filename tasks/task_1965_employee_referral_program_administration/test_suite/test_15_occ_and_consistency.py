"""Optimistic-concurrency and immediate-consistency tests (PRD §2.7, §3.3)."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_employee_headers,
    create_employee,
    create_open_requisition,
    create_active_policy,
    create_active_campaign,
    submit_referral,
    setup_program,
    setup_verified_tax_profile,
    advance_referral_to_offer,
    hire_referral,
    get_campaign,
    get_hire_milestone,
    get_milestone,
    create_open_batch,
    add_milestone_to_batch,
    remove_milestone_from_batch,
    create_campaign_payload,
    create_referral_payload,
    api_client,
    assert_instant_eq,
)


class TestOccCampaignPatch:
    def test_occ_campaign_patch_stale_version(self, api):
        """PRD §2.7: "Editing a campaign requires the request to carry
        `expected_campaign_version`, holding the campaign `version` the client last
        observed. In all three cases the field is non-optional. If the supplied value does
        not match the parent resource's current `version` — meaning another writer has
        legitimately advanced that resource (for example by editing campaign budgets or
        windows, or by adding and removing milestones, both of which recompute batch
        totals and increment the batch version) since the client's last read — the
        request is rejected with `ERR_STALE_VERSION` (HTTP 412)".
        PRD §3.2: "a successful edit increments the campaign's `version` by one."

        A PATCH carrying the pre-edit version after a successful PATCH is rejected; the
        surviving edit's name stands.

        Design: Corner/cross_cutting_layers/occ_campaign_patch_stale_version
        """
        ta = TEST_USERS["talent_admin_headers"]
        req = create_open_requisition(
            req_number="REQ-SR-1", title="Sr Engineer", level="SENIOR"
        )
        camp = get_success_data(
            api.create_campaign(
                create_campaign_payload(
                    name="occ", job_requisition_id=req["id"], budget_cents=500000,
                ),
                ta,
            )
        )
        v1 = camp["version"]

        first = get_success_data(
            api.patch_campaign(camp["id"], {"expected_campaign_version": v1, "name": "occ v2"}, ta)
        )
        assert first["version"] == v1 + 1

        resp = api.patch_campaign(
            camp["id"], {"expected_campaign_version": v1, "name": "stale write"}, ta
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        now = get_campaign(camp["id"])
        assert now["name"] == "occ v2"


class TestOccBatchAddMilestone:
    def test_occ_batch_add_milestone_stale_version(self, api):
        """PRD §2.7: "Attaching a milestone to a payroll batch requires
        `expected_payroll_batch_version`, holding the batch `version` the client last
        observed. If the supplied value does not match the parent resource's current
        `version` — meaning another writer has legitimately advanced that resource (for
        example by editing campaign budgets or windows, or by adding and removing
        milestones, both of which recompute batch totals and increment the batch version)
        since the client's last read — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412), and the client must re-read the resource before re-issuing its
        change."
        PRD §3.6: "Either way the batch totals recompute and the batch `version`
        increments."

        After one successful add advances the batch version, a second add carrying the
        pre-add version is rejected 412.

        Design: Corner/cross_cutting_layers/occ_batch_add_milestone_stale_version
        """
        program = setup_program(req_overrides={"openings": 5})
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        setup_verified_tax_profile(emp["id"])
        refs = []
        for email, name in (("c1@x.com", "C One"), ("c2@x.com", "C Two")):
            ref = submit_referral(emp["id"], program["req"]["id"], candidate_email=email,
                                  candidate_full_name=name)
            advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
            hire_referral(ref["id"], program["hm"]["id"])
            refs.append(ref)
        pp = TEST_USERS["payroll_processor_headers"]
        ms1 = get_hire_milestone(refs[0]["id"])
        ms2 = get_hire_milestone(refs[1]["id"])
        get_success_data(api.approve_milestone(ms1["id"], pp))
        get_success_data(api.approve_milestone(ms2["id"], pp))
        batch = create_open_batch()
        v1 = batch["version"]

        first = add_milestone_to_batch(batch["id"], ms1["id"], v1)
        assert first["version"] == v1 + 1
        assert first["total_gross_cents"] == 45000

        resp = api.add_milestone_to_batch(
            batch["id"],
            {"milestone_id": ms2["id"], "expected_payroll_batch_version": v1},
            pp,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        ms2_now = get_milestone(ms2["id"])
        assert ms2_now["status"] == "APPROVED"


class TestOccBatchRemoveMilestone:
    def test_occ_batch_remove_milestone_stale_version(self, api):
        """PRD §2.7: "Removing a milestone from a payroll batch likewise requires
        `expected_payroll_batch_version`." and "If the supplied value does not match the
        parent resource's current `version` — meaning another writer has legitimately
        advanced that resource (for example by editing campaign budgets or windows, or by
        adding and removing milestones, both of which recompute batch totals and increment
        the batch version) since the client's last read — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the resource before
        re-issuing its change."

        A remove carrying the version observed before the second add is rejected;
        re-issuing with the fresh version succeeds.

        Design: Corner/cross_cutting_layers/occ_batch_remove_milestone_stale_version
        """
        program = setup_program(req_overrides={"openings": 5})
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        setup_verified_tax_profile(emp["id"])
        refs = []
        for email, name in (("c1@x.com", "C One"), ("c2@x.com", "C Two")):
            ref = submit_referral(emp["id"], program["req"]["id"], candidate_email=email,
                                  candidate_full_name=name)
            advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
            hire_referral(ref["id"], program["hm"]["id"])
            refs.append(ref)
        pp = TEST_USERS["payroll_processor_headers"]
        ms1 = get_hire_milestone(refs[0]["id"])
        ms2 = get_hire_milestone(refs[1]["id"])
        get_success_data(api.approve_milestone(ms1["id"], pp))
        get_success_data(api.approve_milestone(ms2["id"], pp))
        batch = create_open_batch()
        b2 = add_milestone_to_batch(batch["id"], ms1["id"], batch["version"])
        b3 = add_milestone_to_batch(batch["id"], ms2["id"], b2["version"])

        # stale: version observed after the FIRST add
        resp = api.remove_milestone_from_batch(
            batch["id"], ms1["id"],
            {"expected_payroll_batch_version": b2["version"]},
            pp,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        # fresh: current version after the second add
        ok = remove_milestone_from_batch(batch["id"], ms1["id"], b3["version"])
        assert ok["total_gross_cents"] == 45000

        ms1_now = get_milestone(ms1["id"])
        assert ms1_now["status"] == "APPROVED"


class TestImmediateConsistency:
    def test_immediate_consistency_on_referral_create(self, api):
        """PRD §3.3: "When every check passes, the server stamps `submitted_at` with
        the logical clock, pins the active policy as `policy_version_id`, and computes
        the bonus quote in a pinned evaluation order" — and "**Step 1 — tier base.** The
        `bonus_base_cents` is the tier amount for the requisition's `level`, read from
        the pinned policy"; "If the set is empty, the uplift is zero and `campaign_id`
        is null."
        PRD §2.8: "When a referral is submitted, the system pins the currently active
        policy onto the referral as its `policy_version_id`".
        PRD §2.4: "At startup the logical clock reads exactly `2026-08-01T00:00:00Z`".
        PRD §3.2: "`tier_ic_cents` 150000".

        The 201 create response already carries every computed field — no re-read.

        Design: Corner/consistency_model/immediate_consistency_on_referral_create
        """
        policy = create_active_policy()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        req = create_open_requisition()

        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=req["id"],
                candidate_email="c1@x.com", candidate_full_name="C One",
            ),
            make_employee_headers(emp["id"]),
        )
        data = validate_success(resp, 201)
        assert data["bonus_base_cents"] == 150000
        assert data["campaign_uplift_cents"] == 0
        assert data["bonus_total_cents"] == 150000
        assert data["policy_version_id"] == policy["id"]
        assert data["status"] == "SUBMITTED"
        assert_instant_eq(data["submitted_at"], "2026-08-01T00:00:00Z")

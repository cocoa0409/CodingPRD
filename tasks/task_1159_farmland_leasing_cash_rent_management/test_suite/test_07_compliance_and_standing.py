"""Conservation compliance: the evidence resubmission cycle, the
cure-deadline sweep, score arithmetic and its suspension threshold, the
waiver remedy, and the depth-3 suspension cascade into bidding."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_compliance_record,
    assert_iso_instant_equal,
    get_bid,
    get_offering,
    get_tenant,
    list_lease_compliance_records,
    make_tenant_headers,
    setup_lease_with_practices_scenario,
    setup_noncompliance_cascade_scenario,
    setup_noncompliant_tenant_scenario,
    validate_success,
)

MGR = TEST_USERS["farm_manager_headers"]
MGR_1 = TEST_USERS["mgr_1_headers"]


class TestEvidenceCycle:
    def test_compliance_evidence_resubmission_cycle(self, api):
        """PRD §3.7: "The tenant fulfills an obligation by submitting an `evidence_note` describing the work; submission is allowed from `PENDING` and also from `REJECTED`, so evidence rejected once may be replaced before the cure deadline, and the caller must be the lease's tenant, else `ERR_NOT_RESOURCE_OWNER`. Submission moves the record to `EVIDENCE_SUBMITTED`. A manager then verifies the evidence — moving the record to the terminal `VERIFIED` state and recording their `X-User-ID` in `verified_by` — or rejects it with a `reason`, returning the record to `REJECTED`."

        Design: Difficulty/non_linear_state_machine/compliance_evidence_resubmission_cycle
        """
        ctx = setup_lease_with_practices_scenario(
            [{"practice_type": "COVER_CROP", "due_date": "2027-06-01T00:00:00Z"}]
        )
        record = ctx["records"][0]
        assert record["status"] == "PENDING", "activation creates PENDING records"
        assert_compliance_record(record)

        tenant_headers = make_tenant_headers(ctx["tenant"]["id"])
        submitted = validate_success(
            api.submit_evidence(
                record["id"], {"evidence_note": "cover crop planted 2027-05-20"},
                tenant_headers,
            )
        )
        assert submitted["status"] == "EVIDENCE_SUBMITTED"

        rejected = validate_success(
            api.reject_evidence(record["id"], {"reason": "photo illegible"}, MGR)
        )
        assert rejected["status"] == "REJECTED"

        resubmitted = validate_success(
            api.submit_evidence(
                record["id"], {"evidence_note": "new photo attached"}, tenant_headers
            )
        )
        assert resubmitted["status"] == "EVIDENCE_SUBMITTED", (
            "REJECTED evidence may be replaced before the cure deadline"
        )

    def test_evidence_cycle_closes_verified_with_verifier_recorded(self, api):
        """PRD §3.7: "A manager then verifies the evidence — moving the record to the terminal `VERIFIED` state and recording their `X-User-ID` in `verified_by`"
        PRD §3.7: "Each record's `cure_deadline` is its `due_date` plus thirty days — the grace window in which a missed practice can still be evidenced."

        Design: Difficulty/non_linear_state_machine/compliance_evidence_resubmission_cycle
        """
        ctx = setup_lease_with_practices_scenario(
            [{"practice_type": "COVER_CROP", "due_date": "2027-06-01T00:00:00Z"}]
        )
        record = ctx["records"][0]
        # cure_deadline = due_date + 30 days = 2027-06-01 + 30d = 2027-07-01.
        assert_iso_instant_equal(record["cure_deadline"], "2027-07-01T00:00:00Z")

        tenant_headers = make_tenant_headers(ctx["tenant"]["id"])
        validate_success(
            api.submit_evidence(
                record["id"], {"evidence_note": "cover crop planted"}, tenant_headers
            )
        )
        validate_success(
            api.reject_evidence(record["id"], {"reason": "photo illegible"}, MGR)
        )
        validate_success(
            api.submit_evidence(
                record["id"], {"evidence_note": "new photo attached"}, tenant_headers
            )
        )
        verified = validate_success(api.verify_compliance_record(record["id"], MGR_1))
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by"] == "mgr-1"


class TestNonComplianceSweep:
    def test_compliance_score_threshold_boundary_no_suspension(self, api):
        """PRD §3.7: "The tenant's `compliance_score` then drops by fifteen points, never falling below a floor of zero. If that drop leaves the score strictly below 50 while the tenant is `APPROVED` — a score of exactly 50 does not suspend — the tenant is moved to `SUSPENDED`"

        Design: Corner/calculations/compliance_score_threshold_boundary_no_suspension
        """
        ctx = setup_noncompliant_tenant_scenario(num_practices=3)
        tenant = get_tenant(ctx["tenant"]["id"])
        assert tenant["compliance_score"] == 55, "100 - 3*15"
        assert tenant["status"] == "APPROVED", (
            "55 >= 50: suspension is strictly below the threshold"
        )
        assert all(r["status"] == "NON_COMPLIANT" for r in ctx["records"])

    def test_noncompliance_cascade_drops_score_and_suspends(self, api):
        """PRD §3.7: "The tenant's `compliance_score` then drops by fifteen points, never falling below a floor of zero. If that drop leaves the score strictly below 50 while the tenant is `APPROVED` — a score of exactly 50 does not suspend — the tenant is moved to `SUSPENDED`, and that suspension cascades exactly as a manual one does"
        PRD §3.7: "When the clock passes a record's `cure_deadline` with the record still unresolved — still `PENDING`, `EVIDENCE_SUBMITTED`, or `REJECTED` — the sweep moves it to `NON_COMPLIANT` and stamps `noncompliant_at` from the clock."

        Design: Difficulty/transitive_cascade/noncompliance_cascade_suspends_tenant_and_withdraws_bids
        """
        ctx = setup_noncompliance_cascade_scenario()
        assert all(r["status"] == "NON_COMPLIANT" for r in ctx["records"]), (
            "all four cure deadlines passed at the 2027-07-02 sweep"
        )
        tenant = ctx["tenant"]
        assert tenant["compliance_score"] == 40, "100 - 4*15 (floor 0 not reached)"
        assert tenant["status"] == "SUSPENDED", "40 < 50 suspends the APPROVED tenant"

    def test_noncompliance_cascade_withdraws_live_bids_and_recounts(self, api):
        """PRD §3.1: "Suspension — by a manager's explicit action, or automatically by the compliance cascade described in §3.6 — moves an `APPROVED` tenant to `SUSPENDED` and ripples outward: every bid of that tenant still in `SUBMITTED` or `SHORTLISTED` status transitions to `WITHDRAWN`, and each affected offering recomputes its `eligible_bid_count` and re-runs evaluation scoring over its remaining eligible bids."
        PRD §3.2: "the same withdrawal happens automatically to all of a tenant's live bids when the tenant is suspended, and that system cascade is exempt from the ownership check"

        Design: Difficulty/transitive_cascade/noncompliance_cascade_suspends_tenant_and_withdraws_bids
        """
        ctx = setup_noncompliance_cascade_scenario()
        assert ctx["bid_b"]["status"] == "WITHDRAWN", (
            "suspension cascade withdraws the tenant's live bid on the second offering"
        )
        assert ctx["offering_b"]["eligible_bid_count"] == 0, (
            "the affected offering recomputes its eligible count"
        )


class TestWaiverRemedy:
    def test_waiving_noncompliant_record_restores_score(self, api):
        """PRD §3.7: "Waiving a `NON_COMPLIANT` record is the remedy, but only a partial one: the tenant's `compliance_score` rises by fifteen points, never exceeding the cap of 100, yet the tenant's status does not change back."
        PRD §3.7: "A manager may also waive the requirement outright with a `reason` from any of `PENDING`, `EVIDENCE_SUBMITTED`, `REJECTED`, or `NON_COMPLIANT`, moving the record to the terminal `WAIVED` state."

        Design: Corner/state_machines/waiving_noncompliant_record_restores_score
        """
        ctx = setup_noncompliant_tenant_scenario(num_practices=1)
        record = ctx["records"][0]
        assert record["status"] == "NON_COMPLIANT"
        before = get_tenant(ctx["tenant"]["id"])
        assert before["compliance_score"] == 85
        assert before["status"] == "APPROVED"

        waived = validate_success(
            api.waive_compliance_record(
                record["id"],
                {"reason": "variance granted by conservation board"},
                MGR,
            )
        )
        assert waived["status"] == "WAIVED"

        after = get_tenant(ctx["tenant"]["id"])
        assert after["compliance_score"] == 100, "min(100, 85 + 15)"
        assert after["status"] == "APPROVED", "waiving does not change tenant status"

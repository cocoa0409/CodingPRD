"""Credit approval: headroom boundary precision, the credit-hold state gate,
lien-waiver linkage, and the state-beats-fiscal priority ordering."""
from test_helpers import (
    CREDIT_MGR,
    ApiErrorId,
    api_client,
    assert_release,
    create_awarded_quote,
    create_contractor,
    create_ea_item,
    create_job_account,
    create_release,
    credit_approve_release,
    file_lien_waiver,
    get_contractor,
    get_job_account,
    get_release,
    record_payment,
    setup_credit_hold_scenario,
    setup_requested_release,
    validate_error,
    validate_success,
)


class TestCreditHeadroomBoundary:

    def test_credit_approve_exact_headroom_passes(self):
        """PRD section 3.6: "Last comes the credit-headroom check: the
        release's `estimated_total_cents` must not exceed the contractor's
        `credit_limit_cents` minus `invoiced_balance_cents` minus
        `committed_balance_cents`; an estimate exactly equal to the remaining
        headroom passes, and only a strictly greater estimate is rejected with
        `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

        Design: Difficulty/boundary_precision_check/credit_approve_exact_headroom_passes
        """
        ctx = setup_requested_release(line_qty=2, line_price=25_000,
                                      stock_qty=5, credit_limit_cents=50_000)
        release = ctx["release"]
        assert release["estimated_total_cents"] == 50_000, (
            f"estimate must be 2 x 25000 = 50000, got "
            f"{release['estimated_total_cents']}")

        resp = api_client.credit_approve_release(release["id"], CREDIT_MGR)
        data = validate_success(resp, expected_status=200)
        assert_release(data)
        assert data["status"] == "CREDIT_APPROVED", (
            "an estimate exactly equal to the remaining headroom passes")

    def test_approval_commits_estimate_to_committed_balance(self):
        """PRD section 3.6: "Approval commits the estimate: the contractor's
        `committed_balance_cents` increases by the release's
        `estimated_total_cents`."

        Design: Difficulty/boundary_precision_check/credit_approve_exact_headroom_passes
        """
        ctx = setup_requested_release(line_qty=2, line_price=25_000,
                                      stock_qty=5, credit_limit_cents=50_000)
        credit_approve_release(ctx["release"]["id"])
        contractor = get_contractor(ctx["contractor"]["id"])
        assert contractor["committed_balance_cents"] == 50_000, (
            f"approval must commit the estimate, got committed "
            f"{contractor['committed_balance_cents']}")
        assert contractor["credit_used_cents"] == 50_000

    def test_credit_approve_over_headroom_rejected(self):
        """PRD section 3.6: "an estimate exactly equal to the remaining
        headroom passes, and only a strictly greater estimate is rejected with
        `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

        Design: Corner/validations/credit_approve_over_headroom_rejected
        """
        ctx = setup_requested_release(line_qty=1, line_price=50_001,
                                      stock_qty=None,
                                      credit_limit_cents=50_000)
        assert ctx["release"]["estimated_total_cents"] == 50_001
        resp = api_client.credit_approve_release(ctx["release"]["id"],
                                                 CREDIT_MGR)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        assert get_release(ctx["release"]["id"])["status"] == "REQUESTED"


class TestLienWaiverLinkage:

    def _setup_lien_job(self, waiver_expires_on):
        """Requested release on a lien-waiver-required job; files a waiver
        with the given expiry when waiver_expires_on is not None."""
        contractor = create_contractor("Lien Electric", 100_000)
        item = create_ea_item()
        job = create_job_account(contractor["id"], "Lien Job",
                                 jobsite_address="35 Site Rd",
                                 lien_waiver_required=True)
        job_version = job["version"]
        if waiver_expires_on is not None:
            job_version = file_lien_waiver(job["id"],
                                           waiver_expires_on)["version"]
        quote = create_awarded_quote(job["id"], [(item["id"], 1, 5000)])
        release = create_release(job["id"], quote["id"], [(item["id"], 1)],
                                 expected_job_account_version=job_version)
        return release

    def test_lien_waiver_missing_blocks_credit_approve_rejected(self):
        """PRD section 3.6: "When the job's `lien_waiver_required` is true, a
        current lien waiver must be on file — `lien_waiver_expires_on` set and
        falling on or after the logical clock's date — else
        `ERR_LIEN_WAIVER_REQUIRED`."

        Design: Corner/state_machines/lien_waiver_missing_blocks_credit_approve_rejected
        """
        release = self._setup_lien_job(waiver_expires_on=None)
        resp = api_client.credit_approve_release(release["id"], CREDIT_MGR)
        validate_error(resp, ApiErrorId.ERR_LIEN_WAIVER_REQUIRED)
        assert get_release(release["id"])["status"] == "REQUESTED"

    def test_lien_waiver_expiring_today_allows_credit_approve(self):
        """PRD section 3.3: "A waiver is current only while its expiry falls
        on or after the logical clock's date; an expired waiver is no waiver
        at all for the purposes of §3.6."
        PRD section 2.5: "At startup, before any adjustment, the logical clock
        reads exactly `2026-08-01T00:00:00Z`".

        Design: Corner/state_machines/lien_waiver_expiring_today_allows_credit_approve
        """
        release = self._setup_lien_job(waiver_expires_on="2026-08-01")
        resp = api_client.credit_approve_release(release["id"], CREDIT_MGR)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CREDIT_APPROVED", (
            "a waiver expiring on the clock's date is still current")

    def test_lien_waiver_expired_blocks_credit_approve_rejected(self):
        """PRD section 3.3: "A waiver is current only while its expiry falls
        on or after the logical clock's date; an expired waiver is no waiver
        at all for the purposes of §3.6."

        Design: Corner/state_machines/lien_waiver_expired_blocks_credit_approve_rejected
        """
        release = self._setup_lien_job(waiver_expires_on="2026-07-31")
        resp = api_client.credit_approve_release(release["id"], CREDIT_MGR)
        validate_error(resp, ApiErrorId.ERR_LIEN_WAIVER_REQUIRED)
        assert get_release(release["id"])["status"] == "REQUESTED"


class TestCreditHoldGate:

    def test_credit_approve_rejected_while_job_on_hold(self):
        """PRD section 3.6: "The job account must not be sitting in
        `CREDIT_HOLD` (`ERR_JOB_ON_CREDIT_HOLD`)."

        Design: Difficulty/cross_entity_state_dependency/credit_approve_blocked_by_job_hold_then_cured
        """
        world = setup_credit_hold_scenario(pending_release_on="j1")
        pending = world["pending_release"]
        assert get_job_account(world["j1"]["id"])["status"] == "CREDIT_HOLD"

        resp = api_client.credit_approve_release(pending["id"], CREDIT_MGR)
        validate_error(resp, ApiErrorId.ERR_JOB_ON_CREDIT_HOLD)
        assert get_release(pending["id"])["status"] == "REQUESTED"

    def test_credit_approve_succeeds_after_payment_cure(self):
        """PRD section 3.1: "If the posting brings `invoiced_balance_cents`
        back to at or below `credit_limit_cents`, every `CREDIT_HOLD` job
        account belonging to that contractor automatically returns to `OPEN` —
        the mirror image of the credit contagion described in §3.8."
        PRD section 3.6: "Approval commits the estimate: the contractor's
        `committed_balance_cents` increases by the release's
        `estimated_total_cents`."

        Design: Difficulty/cross_entity_state_dependency/credit_approve_blocked_by_job_hold_then_cured
        """
        world = setup_credit_hold_scenario(pending_release_on="j1")
        contractor = world["contractor"]
        pending = world["pending_release"]

        record_payment(contractor["id"], 10_000)
        cured = get_contractor(contractor["id"])
        assert cured["invoiced_balance_cents"] == 18_650, (
            f"28650 - 10000 = 18650 expected, got "
            f"{cured['invoiced_balance_cents']}")
        assert get_job_account(world["j1"]["id"])["status"] == "OPEN", (
            "the payment restores headroom, so held jobs return to OPEN")

        resp = api_client.credit_approve_release(pending["id"], CREDIT_MGR)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CREDIT_APPROVED", (
            "estimate 1000 fits the post-cure headroom of 20000 - 18650 = "
            "1350")


class TestStateBeatsFiscalPriority:

    def test_hold_state_error_returned_when_fiscal_also_fails(self):
        """PRD section 2.10: "Credit-approving a release whose job sits on
        credit hold surfaces `ERR_JOB_ON_CREDIT_HOLD` long before
        `ERR_CREDIT_LIMIT_EXCEEDED` would ever be considered."

        Design: Difficulty/priority_pair_validation_conflict/credit_approve_hold_state_beats_fiscal_rejected
        """
        world = setup_credit_hold_scenario(second_job=True,
                                           pending_release_on="j2")
        pending = world["pending_release"]
        contractor = get_contractor(world["contractor"]["id"])
        # Headroom is negative, so the fiscal check would also fail.
        assert contractor["invoiced_balance_cents"] == 28_650
        assert get_job_account(world["j2"]["id"])["status"] == "CREDIT_HOLD"

        resp = api_client.credit_approve_release(pending["id"], CREDIT_MGR)
        validate_error(resp, ApiErrorId.ERR_JOB_ON_CREDIT_HOLD)
        assert get_release(pending["id"])["status"] == "REQUESTED", (
            "the rejected approve must leave the release REQUESTED")

    def test_after_cure_the_masked_fiscal_error_surfaces(self):
        """PRD section 2.10: "Credit-approving a release whose job sits on
        credit hold surfaces `ERR_JOB_ON_CREDIT_HOLD` long before
        `ERR_CREDIT_LIMIT_EXCEEDED` would ever be considered."
        PRD section 3.6: "an estimate exactly equal to the remaining headroom
        passes, and only a strictly greater estimate is rejected with
        `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/credit_approve_hold_state_beats_fiscal_rejected
        """
        world = setup_credit_hold_scenario(second_job=True,
                                           pending_release_on="j2")
        pending = world["pending_release"]
        record_payment(world["contractor"]["id"], 10_000)
        assert get_job_account(world["j2"]["id"])["status"] == "OPEN"

        # Headroom is now 20000 - 18650 = 1350; the 5000 estimate exceeds it.
        resp = api_client.credit_approve_release(pending["id"], CREDIT_MGR)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        assert get_release(pending["id"])["status"] == "REQUESTED"

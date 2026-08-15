"""Endpoint replacement campaigns: enrollment gates, cascades, auto-complete.

Covers PRD section 3.8 plus the evidence-preservation interaction of
section 3.6.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_field_technician_payload,
    create_meter,
    create_replacement_campaign_payload,
    dispatch_order_to,
    enroll_payload,
    get_campaign,
    get_enrollment,
    get_meter,
    get_work_order,
    install_meter_at_account,
    open_investigation,
    run_ops_snapshot,
    set_logical_clock,
    setup_account_with_installed_meter,
    setup_failed_meter_in_open_campaign,
    start_order_as,
    validate_error,
    validate_paginated,
    validate_success,
    make_field_technician_headers,
)

ADMIN = TEST_USERS["meter_ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]

# Five-snapshot drive to FAILED: misses on days 1-3 move the meter to
# NON_COMMUNICATING; the 08-18 snapshot is exactly 14 days later (inclusive).
FAILED_DRIVE = [
    "2026-08-02T00:00:00Z",
    "2026-08-03T00:00:00Z",
    "2026-08-04T00:00:00Z",
    "2026-08-18T00:00:00Z",
]


class TestCampaignCompletion:
    def test_campaign_auto_completes_when_last_enrollment_replaced(self, api):
        """PRD section 3.7: "Completing an `ENDPOINT_SWAP` order needs no
        payload. The meter's `endpoint_comms_status` returns to
        `COMMUNICATING` with `consecutive_missed_days` reset to zero and
        `non_communicating_since` cleared to null; the CampaignEnrollment
        owning the order transitions from `WORK_ORDER_CREATED` to `REPLACED`;
        and the campaign recomputes its counts with the auto-complete check."
        PRD section 3.8: "After any enrollment status change, the campaign
        checks for completion: when at least one enrollment exists and every
        enrollment is in `REPLACED` or `WITHDRAWN`, the campaign moves itself
        from `OPEN` to the terminal `COMPLETED`."

        Design: Corner/state_machines/campaign_auto_completes_when_last_enrollment_replaced
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        tech = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Swap Tech"), ADMIN
            ),
            201,
        )
        _account, meter, campaign, enrollment = setup_failed_meter_in_open_campaign(
            "C-0040",
            "C40",
            [
                "2026-08-02T00:00:00Z",
                "2026-08-03T00:00:00Z",
                "2026-08-04T00:00:00Z",
                "2026-08-17T00:00:00Z",
                "2026-08-18T00:00:00Z",
            ],
            campaign_name="Single Swap",
            quota=1,
        )
        swap_wo_id = enrollment["work_order_id"]
        dispatch_order_to(swap_wo_id, tech["id"])
        start_order_as(swap_wo_id, tech["id"])
        validate_success(
            api.complete_work_order(
                swap_wo_id, {}, make_field_technician_headers(tech["id"])
            ),
            200,
        )

        assert get_enrollment(enrollment["id"])["enrollment_status"] == "REPLACED"
        meter_after = get_meter(meter["id"])
        assert meter_after["endpoint_comms_status"] == "COMMUNICATING"
        assert meter_after["consecutive_missed_days"] == 0
        assert meter_after["non_communicating_since"] is None

        campaign_after = get_campaign(campaign["id"])
        assert campaign_after["campaign_status"] == "COMPLETED"
        assert campaign_after["replaced_count"] == 1

    def test_campaign_close_withdraws_enrollment_and_cancels_order(self, api):
        """PRD section 3.8: "An administrator may instead close an `OPEN`
        campaign outright: closing moves it to the terminal `CLOSED` state and
        cascades down — enrollments in `ENROLLED` or `WORK_ORDER_CREATED`
        transition to `WITHDRAWN`, and their work orders in `OPEN`,
        `DISPATCHED`, or `REWORK` transition to `CANCELLED`."

        Design: Corner/state_machines/campaign_close_withdraws_enrollment_and_cancels_order
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        _account, _meter, campaign, enrollment = setup_failed_meter_in_open_campaign(
            "C-0041", "C41", FAILED_DRIVE, campaign_name="Close Out", quota=3
        )
        closed = validate_success(api.close_campaign(campaign["id"], ADMIN), 200)
        assert closed["campaign_status"] == "CLOSED"

        campaign_after = get_campaign(campaign["id"])
        assert campaign_after["withdrawn_count"] == 1
        assert get_enrollment(enrollment["id"])["enrollment_status"] == "WITHDRAWN"
        assert (
            get_work_order(enrollment["work_order_id"])["work_order_status"] == "CANCELLED"
        )


class TestEnrollmentQuota:
    def _three_failed_meters(self, api, account_prefix, cycle_code):
        accounts, meters = [], []
        for suffix in ("A", "B", "C"):
            account, meter = setup_account_with_installed_meter(
                f"{account_prefix}{suffix}",
                cycle_code,
                meter_type="AMI",
                service_address=f"{account_prefix}{suffix} Quota Rd",
            )
            accounts.append(account)
            meters.append(meter)
        for at in FAILED_DRIVE:
            run_ops_snapshot(at)
        for meter in meters:
            assert get_meter(meter["id"])["endpoint_comms_status"] == "FAILED"
        return accounts, meters

    def test_enrollment_quota_boundary_exact_fit_then_overflow(self, api):
        """PRD section 3.8: "Three checks run in pinned order: first the batch
        quota — if the batch size exceeds the campaign's remaining capacity
        (`quota` less the current `enrolled_count`), the entire batch is
        rejected with `ERR_CAMPAIGN_QUOTA_EXCEEDED` (HTTP 409) and nothing is
        enrolled; then each meter's eligibility — only meters whose
        `endpoint_comms_status` has reached `FAILED` qualify, others failing
        with `ERR_METER_NOT_ELIGIBLE_FOR_CAMPAIGN` (HTTP 409); then duplicate
        membership — a meter already enrolled in an `OPEN` campaign fails with
        `ERR_METER_ALREADY_ENROLLED` (HTTP 409)."

        Design: Corner/validations/enrollment_quota_boundary_exact_fit_then_overflow
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        _accounts, meters = self._three_failed_meters(api, "C-0096", "C96")
        campaign = validate_success(
            api.create_replacement_campaign(
                create_replacement_campaign_payload(campaign_name="Quota Two", quota=2), ADMIN
            ),
            201,
        )
        validate_success(api.open_campaign(campaign["id"], ADMIN), 200)

        # A batch of exactly the remaining quota succeeds.
        enrollments = validate_success(
            api.enroll_meters(
                campaign["id"], enroll_payload([meters[0]["id"], meters[1]["id"]]), ADMIN
            ),
            201,
        )
        assert len(enrollments) == 2
        assert enrollments[0]["enrollment_status"] == "WORK_ORDER_CREATED"
        assert get_campaign(campaign["id"])["enrolled_count"] == 2

        # One more exceeds the remaining capacity of zero.
        res = api.enroll_meters(campaign["id"], enroll_payload([meters[2]["id"]]), ADMIN)
        validate_error(res, ApiErrorId.ERR_CAMPAIGN_QUOTA_EXCEEDED.value, 409)

    def test_enrollment_batch_atomic_on_quota_overflow(self, api):
        """PRD section 3.8: "Three checks run in pinned order: first the batch
        quota — if the batch size exceeds the campaign's remaining capacity
        (`quota` less the current `enrolled_count`), the entire batch is
        rejected with `ERR_CAMPAIGN_QUOTA_EXCEEDED` (HTTP 409) and nothing is
        enrolled; then each meter's eligibility — only meters whose
        `endpoint_comms_status` has reached `FAILED` qualify, others failing
        with `ERR_METER_NOT_ELIGIBLE_FOR_CAMPAIGN` (HTTP 409); then duplicate
        membership — a meter already enrolled in an `OPEN` campaign fails with
        `ERR_METER_ALREADY_ENROLLED` (HTTP 409)."

        Design: Corner/validations/enrollment_batch_atomic_on_quota_overflow
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        account, m1 = setup_account_with_installed_meter(
            "C-0097A", "C97", meter_type="AMI", service_address="97A Atom Rd"
        )
        m2 = create_meter("SN-AT-2", "AMI")
        m3 = create_meter("SN-AT-3", "AMI")
        # Second install on the occupied account is refused (setup sanity).
        occupied = api.install_meter(m2["id"], {"service_account_id": account["id"]}, ADMIN)
        validate_error(occupied, ApiErrorId.ERR_ACCOUNT_HAS_INSTALLED_METER.value, 409)

        for at in FAILED_DRIVE:
            run_ops_snapshot(at)
        campaign = validate_success(
            api.create_replacement_campaign(
                create_replacement_campaign_payload(campaign_name="Atomic Two", quota=2), ADMIN
            ),
            201,
        )
        validate_success(api.open_campaign(campaign["id"], ADMIN), 200)

        # Batch of 3 against remaining quota 2: rejected whole, atomically.
        res = api.enroll_meters(
            campaign["id"],
            enroll_payload([m1["id"], m2["id"], m3["id"]]),
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_CAMPAIGN_QUOTA_EXCEEDED.value, 409)

        data, meta = validate_paginated(
            api.list_campaign_enrollments(ADMIN, params={"campaign_id": campaign["id"]})
        )
        assert meta["total_count"] == 0
        assert data == []
        assert get_campaign(campaign["id"])["enrolled_count"] == 0


class TestEnrollmentEligibility:
    def test_enrollment_ineligible_non_failed_meter_rejected(self, api):
        """PRD section 3.8: "then each meter's eligibility — only meters whose
        `endpoint_comms_status` has reached `FAILED` qualify, others failing
        with `ERR_METER_NOT_ELIGIBLE_FOR_CAMPAIGN` (HTTP 409)"

        Design: Corner/validations/enrollment_ineligible_non_failed_meter_rejected
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        account, m1 = setup_account_with_installed_meter(
            "C-0098", "C98", meter_type="AMI", service_address="98 Elig Rd"
        )
        # Three misses -> NON_COMMUNICATING, but no fourteen-day wait.
        for at in [
            "2026-08-02T00:00:00Z",
            "2026-08-03T00:00:00Z",
            "2026-08-04T00:00:00Z",
        ]:
            run_ops_snapshot(at)
        assert get_meter(m1["id"])["endpoint_comms_status"] == "NON_COMMUNICATING"

        campaign = validate_success(
            api.create_replacement_campaign(
                create_replacement_campaign_payload(campaign_name="Eligibility", quota=5),
                ADMIN,
            ),
            201,
        )
        validate_success(api.open_campaign(campaign["id"], ADMIN), 200)
        res = api.enroll_meters(campaign["id"], enroll_payload([m1["id"]]), ADMIN)
        validate_error(res, ApiErrorId.ERR_METER_NOT_ELIGIBLE_FOR_CAMPAIGN.value, 409)

    def test_enrollment_duplicate_across_open_campaigns_rejected(self, api):
        """PRD section 3.8: "then duplicate membership — a meter already
        enrolled in an `OPEN` campaign fails with
        `ERR_METER_ALREADY_ENROLLED` (HTTP 409)."

        Design: Corner/validations/enrollment_duplicate_across_open_campaigns_rejected
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        _account, meter, campaign_1, _enr = setup_failed_meter_in_open_campaign(
            "C-0099", "C99", FAILED_DRIVE, campaign_name="First", quota=5
        )
        campaign_2 = validate_success(
            api.create_replacement_campaign(
                create_replacement_campaign_payload(campaign_name="Second", quota=5), ADMIN
            ),
            201,
        )
        validate_success(api.open_campaign(campaign_2["id"], ADMIN), 200)

        res = api.enroll_meters(campaign_2["id"], enroll_payload([meter["id"]]), ADMIN)
        validate_error(res, ApiErrorId.ERR_METER_ALREADY_ENROLLED.value, 409)
        assert get_campaign(campaign_2["id"])["enrolled_count"] == 0

    def test_evidence_preservation_hold_beats_enrollment_eligibility(self, api):
        """PRD section 3.8: "The evidence-preservation hold applies here too:
        enrolling a suspected meter under a non-terminal investigation is
        rejected with `ERR_EVIDENCE_PRESERVATION_HOLD`."
        PRD section 2.6: "Safety screens come next: the active-hazard block on
        read capture (`ERR_ACTIVE_HAZARD_BLOCKS_READ`, HTTP 422), the
        active-flag requirement for hazard skips (`ERR_SKIP_REQUIRES_ACTIVE_HAZARD`,
        HTTP 409), and the evidence-preservation hold on meters under
        investigation (`ERR_EVIDENCE_PRESERVATION_HOLD`, HTTP 409)."
        PRD section 2.6: "Three terminal groups apply last, each with its own
        pinned intra-group order. Campaign enrollment checks run the batch
        quota first — the entire batch is rejected atomically when it would
        exceed remaining capacity (`ERR_CAMPAIGN_QUOTA_EXCEEDED`, HTTP 409) —
        then per-meter eligibility (`ERR_METER_NOT_ELIGIBLE_FOR_CAMPAIGN`,
        HTTP 409), then duplicate enrollment (`ERR_METER_ALREADY_ENROLLED`,
        HTTP 409)."

        Design: Corner/validations/evidence_preservation_hold_beats_enrollment_eligibility
        """
        account, m1 = setup_account_with_installed_meter(
            "C-0072", "C72", meter_type="AMI", service_address="72 Hold Rd"
        )
        open_investigation(account["id"], m1["id"], opened_by="inv-301")
        assert get_meter(m1["id"])["tamper_status"] == "SUSPECTED"
        # the meter is COMMUNICATING (never failed) — eligibility would also
        # fail, but the safety hold is pinned earlier in the ladder.
        assert get_meter(m1["id"])["endpoint_comms_status"] == "COMMUNICATING"

        campaign = validate_success(
            api.create_replacement_campaign(
                create_replacement_campaign_payload(campaign_name="Hold Test", quota=5), ADMIN
            ),
            201,
        )
        validate_success(api.open_campaign(campaign["id"], ADMIN), 200)
        res = api.enroll_meters(campaign["id"], enroll_payload([m1["id"]]), ADMIN)
        validate_error(res, ApiErrorId.ERR_EVIDENCE_PRESERVATION_HOLD.value, 409)
        assert get_campaign(campaign["id"])["enrolled_count"] == 0


class TestEnrollmentDiscovery:
    def test_enrollment_list_reverse_reachable_from_campaign(self, api, dispatcher_headers):
        """PRD section 3.8: "A CampaignEnrollment is born `ENROLLED` with its
        `campaign_id` and `meter_id` recorded, and the system instantly
        auto-creates an `ENDPOINT_SWAP` work order for it — `scheduled_date`
        set to the enrollment date plus seven days, `work_shift` `FULL` —
        advancing the enrollment to `WORK_ORDER_CREATED` with `work_order_id`
        set."
        PRD section 3.8: "The enrollment list filters by `campaign_id`,
        `meter_id`, `enrollment_status`, or `work_order_id`."

        Design: Corner/endpoints/enrollment_list_reverse_reachable_from_campaign
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        _account, meter, campaign, enrollment = setup_failed_meter_in_open_campaign(
            "C-0112", "CC3", FAILED_DRIVE, campaign_name="Reverse", quota=5
        )
        data, meta = validate_paginated(
            api.list_campaign_enrollments(
                dispatcher_headers, params={"campaign_id": campaign["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == enrollment["id"]
        assert data[0]["enrollment_status"] == "WORK_ORDER_CREATED"
        assert data[0]["work_order_id"] is not None

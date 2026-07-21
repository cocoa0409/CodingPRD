"""Chasing loose ends, the operations checkpoint, and who may act."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    make_donor_headers,
    new_charity,
    new_donation,
    new_donor,
    read_charity,
    read_donation,
    read_donor,
    read_lot,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    accept,
    donation_tasks,
    donation_version,
    new_title,
    set_clock,
    setup_abandoned_title_task,
    setup_listed_lot,
)

UNSTORED_UUID = "33333333-3333-4333-8333-333333333333"


class TestOperationsCheckpoint:
    def test_sweep_escalates_an_overdue_task_exactly_once(self, api, program_admin_headers):
        """PRD §3.10: "First, every task that is still `OPEN` and whose `due_utc` is at or
        before the current logical clock moves `OPEN → ESCALATED`."
        PRD §3.10: "The checkpoint answers with `escalated_task_count`, the number of tasks
        it escalated, and `stale_title_task_count`, the number of stale-title tasks it
        created."

        Design: Corner/endpoints/corner_ops_sweep_escalates_an_overdue_follow_up_task
        """
        bundle = setup_abandoned_title_task(clock="2026-07-05T00:00:00Z")
        assert bundle["task"]["due_utc"].startswith("2026-07-20T00:00:00")

        set_clock("2026-07-20T00:00:00Z")
        first = validate_success(api.run_sweep(program_admin_headers), 200)
        assert first["escalated_task_count"] == 1

        tasks = donation_tasks(bundle["donation"]["id"])
        assert len(tasks) == 1
        assert tasks[0]["status"] == "ESCALATED"
        assert tasks[0]["due_utc"].startswith("2026-07-20T00:00:00")

        second = validate_success(api.run_sweep(program_admin_headers), 200)
        assert second["escalated_task_count"] == 0

    def test_sweep_raises_one_stale_title_task_per_lingering_submission(
        self, api, program_admin_headers, title_clerk_headers
    ):
        """PRD §3.10: "Second, every title record still sitting in `SUBMITTED` whose
        `submitted_at_utc` is more than forty-five days before the current logical clock,
        and which has no `TITLE_STALE` task already `OPEN` or `ESCALATED`, gets one raised."
        PRD §3.10: "The checkpoint answers with `escalated_task_count`, the number of tasks
        it escalated, and `stale_title_task_count`, the number of stale-title tasks it
        created."

        Design: Corner/endpoints/corner_ops_sweep_raises_a_stale_title_task_after_45_days
        """
        charity = new_charity(name="Stale Trust")
        donor = new_donor(full_name="Sta Le")
        donation = new_donation(
            donor["id"], charity["id"], declared_condition="FAIR", pickup_required=False
        )
        accept(donation["id"])
        title = new_title(donation["id"], owner_name="Sta Le")
        submitted = validate_success(api.submit_title_to_dmv(title["id"], title_clerk_headers), 200)
        assert submitted["submitted_at_utc"].startswith("2026-07-01T00:00:00")

        # 2026-08-16 sits more than forty-five days after the 2026-07-01 submission.
        set_clock("2026-08-16T00:00:00Z")
        first = validate_success(api.run_sweep(program_admin_headers), 200)
        assert first["stale_title_task_count"] == 1

        tasks = donation_tasks(donation["id"])
        assert len(tasks) == 1
        assert tasks[0]["task_type"] == "TITLE_STALE"
        assert tasks[0]["assigned_role"] == "TitleClerk"

        second = validate_success(api.run_sweep(program_admin_headers), 200)
        assert second["stale_title_task_count"] == 0
        assert len(donation_tasks(donation["id"])) == 1

    def test_a_task_closed_by_hand_cannot_be_closed_again(self, api, program_admin_headers):
        """PRD §3.10: "A program administrator may close one **by hand**, supplying a
        `resolution_note`; this is permitted from either `OPEN` or `ESCALATED` and moves
        the task to `DONE`, its terminal state. Closing an already-`DONE` task is refused
        with `ERR_INVALID_TASK_STATE`."

        Design: Corner/endpoints/corner_follow_up_task_can_be_completed_by_hand
        """
        bundle = setup_abandoned_title_task(clock="2026-07-05T00:00:00Z")
        task_id = bundle["task"]["id"]

        done = validate_success(
            api.complete_follow_up_task(
                task_id,
                {"resolution_note": "donor supplied a duplicate title"},
                program_admin_headers,
            ),
            200,
        )
        assert done["status"] == "DONE"
        assert done["resolution_note"] == "donor supplied a duplicate title"

        again = api.complete_follow_up_task(
            task_id, {"resolution_note": "again"}, program_admin_headers
        )
        validate_error(again, ApiErrorId.ERR_INVALID_TASK_STATE.value)


class TestAccessControl:
    def test_an_intake_agent_may_not_record_a_sale(self, api, intake_agent_headers):
        """PRD §2.1: "When the headers are well-formed but the named role is not among the
        roles authorised for the requested operation (see the endpoint table in §4), the
        request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/corner_intake_agent_cannot_record_a_sale
        """
        bundle = setup_listed_lot(reserve_price_cents=1_000)

        response = api.record_sale(
            bundle["lot"]["id"],
            {
                "sale_price_cents": 60_000,
                "expected_donation_version": donation_version(bundle["donation"]["id"]),
            },
            intake_agent_headers,
        )

        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
        lot = read_lot(bundle["lot"]["id"])
        assert lot["status"] == "LISTED"
        assert lot["sale_price_cents"] is None
        assert read_donation(bundle["donation"]["id"])["payout_status"] == "PENDING"
        assert read_charity(bundle["charity"]["id"])["pledged_balance_cents"] == 0

    def test_a_donor_may_not_cancel_another_donors_donation(self, api):
        """PRD §2.1: "When `X-User-Role` is `Donor`, `X-User-ID` is the `id` of the acting
        donor record; ownership checks on any resource that references a donor compare that
        resource's `donor_id` to `X-User-ID`."
        PRD §2.1: "Ownership violations by an entity-backed role are reported as
        `ERR_FORBIDDEN_OWNER` (HTTP 403). This check guards exactly four operations: a donor
        cancelling a donation (the donation's `donor_id` must equal `X-User-ID`), a donor or
        charity administrator listing donations under a `donor_id` or `charity_id` filter, a
        charity administrator disputing a closed remittance batch (the batch's `charity_id`
        must equal `X-User-ID`), and a charity administrator reading the charity-summary
        report (the `charity_id` requested must equal `X-User-ID`)."

        Design: Corner/rbac/corner_donor_cannot_cancel_another_donors_donation
        """
        charity = new_charity(name="Owner Trust")
        owner = new_donor(full_name="Own A")
        stranger = new_donor(full_name="Own B")
        donation = new_donation(owner["id"], charity["id"], pickup_required=False)

        response = api.cancel_donation(
            donation["id"],
            {"reason": "not my car but I tried"},
            make_donor_headers(stranger["id"]),
        )

        validate_error(response, ApiErrorId.ERR_FORBIDDEN_OWNER.value)
        assert read_donation(donation["id"])["status"] == "PENDING_REVIEW"
        assert read_donor(owner["id"])["donation_count"] == 1
        assert read_donor(stranger["id"])["donation_count"] == 0

    @pytest.mark.parametrize(
        "headers",
        [
            {"Content-Type": "application/json"},
            build_user_headers("someone", "NotARole"),
        ],
        ids=["no_identity_headers", "unknown_role"],
    )
    def test_requests_without_a_declared_role_are_unauthenticated(self, api, headers):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the
        caller, and `X-User-Role`, naming the capacity in which the caller acts. If either
        header is absent, or if `X-User-Role` is not one of the seven role names defined
        below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/corner_request_without_role_header_is_unauthenticated
        """
        charity = new_charity(name="Auth Trust")
        donor = new_donor()
        donation = new_donation(donor["id"], charity["id"], pickup_required=False)

        response = api.get_donation(donation["id"], headers)

        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
        assert read_donation(donation["id"])["status"] == "PENDING_REVIEW"

    def test_each_collection_answers_with_its_own_not_found_code(self, api):
        """PRD §2.8: "Every identifier embedded in the URL path resolves to a stored row,
        validated left to right. Applies to every path-parameterised endpoint. The rejection
        names the entity that failed to resolve: `ERR_DONOR_NOT_FOUND`,
        `ERR_CHARITY_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`,
        `ERR_TITLE_RECORD_NOT_FOUND`, `ERR_TOW_VENDOR_NOT_FOUND`,
        `ERR_PICKUP_ORDER_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_AUCTION_LOT_NOT_FOUND`,
        `ERR_TAX_RECEIPT_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, or `ERR_TASK_NOT_FOUND`, each
        HTTP 404."

        Design: Corner/errors/corner_not_found_is_raised_per_collection_with_its_own_error_id
        """
        new_charity(name="NF Trust")
        intake = TEST_USERS["intake_agent_headers"]
        clerk = TEST_USERS["title_clerk_headers"]
        auction = TEST_USERS["auction_manager_headers"]
        finance = TEST_USERS["finance_officer_headers"]
        admin = TEST_USERS["program_admin_headers"]

        cases = [
            (api.get_donor(UNSTORED_UUID, intake), ApiErrorId.ERR_DONOR_NOT_FOUND),
            (api.get_charity(UNSTORED_UUID, admin), ApiErrorId.ERR_CHARITY_NOT_FOUND),
            (api.get_vehicle(UNSTORED_UUID, intake), ApiErrorId.ERR_VEHICLE_NOT_FOUND),
            (api.get_title_record(UNSTORED_UUID, clerk), ApiErrorId.ERR_TITLE_RECORD_NOT_FOUND),
            (api.get_tow_vendor(UNSTORED_UUID, intake), ApiErrorId.ERR_TOW_VENDOR_NOT_FOUND),
            (api.get_pickup_order(UNSTORED_UUID, intake), ApiErrorId.ERR_PICKUP_ORDER_NOT_FOUND),
            (api.get_venue(UNSTORED_UUID, auction), ApiErrorId.ERR_VENUE_NOT_FOUND),
            (api.get_auction_lot(UNSTORED_UUID, auction), ApiErrorId.ERR_AUCTION_LOT_NOT_FOUND),
            (api.get_tax_receipt(UNSTORED_UUID, finance), ApiErrorId.ERR_TAX_RECEIPT_NOT_FOUND),
            (api.get_remittance_batch(UNSTORED_UUID, finance), ApiErrorId.ERR_BATCH_NOT_FOUND),
            (api.get_follow_up_task(UNSTORED_UUID, admin), ApiErrorId.ERR_TASK_NOT_FOUND),
        ]

        for response, expected in cases:
            validate_error(response, expected.value)
            assert response.json()["response_type"] == "error"

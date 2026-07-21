"""Clearing title at the DMV."""
from test_helpers import (
    ApiErrorId,
    assert_follow_up_task,
    assert_title_record,
    create_charity_payload,
    create_donor_payload,
    create_title_record_payload,
    new_charity,
    new_donation,
    new_donor,
    new_title,
    read_title,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    accept,
    donation_tasks,
    read_donation,
    setup_abandoned_title_task,
)


def _rejected_once(title_clerk_headers, api):
    """A title record on an ACCEPTED donation, rejected by the DMV once."""
    charity = new_charity()
    donor = new_donor()
    donation = new_donation(
        donor["id"], charity["id"], declared_condition="FAIR", pickup_required=False
    )
    accept(donation["id"])
    title = new_title(donation["id"], owner_name="Tia Tel")
    validate_success(api.submit_title_to_dmv(title["id"], title_clerk_headers), 200)
    rejected = validate_success(
        api.record_dmv_decision(
            title["id"], {"outcome": "REJECTED", "rejection_reason": "signature mismatch"},
            title_clerk_headers,
        ),
        200,
    )
    return donation, rejected


class TestTitleRejectResubmitCycle:
    def test_two_dmv_rejections_may_both_be_refiled(self, api, title_clerk_headers):
        """PRD §3.4: "A rejected outcome moves it `SUBMITTED → REJECTED`, raises
        `rejection_count` by one, and stores the supplied `rejection_reason`."
        PRD §3.4: "The program tolerates two DMV rejections: a resubmission is accepted
        while `rejection_count` is no greater than two, so the first and second rejections
        may both be refiled, but a third rejection leaves the count at three and the next
        resubmission is refused with `ERR_TITLE_RESUBMIT_LIMIT`."

        Design: Difficulty/non_linear_state_machine/title_record_reject_resubmit_cycle_hits_resubmit_limit
        """
        _, title = _rejected_once(title_clerk_headers, api)
        assert_title_record(title)
        assert title["state"] == "REJECTED"
        assert title["rejection_count"] == 1

        first_refile = validate_success(
            api.resubmit_title(title["id"], {"owner_name": "Tia Tel"}, title_clerk_headers), 200
        )
        assert first_refile["state"] == "SUBMITTED"
        assert first_refile["rejection_count"] == 1

        validate_success(
            api.record_dmv_decision(
                title["id"],
                {"outcome": "REJECTED", "rejection_reason": "odometer statement missing"},
                title_clerk_headers,
            ),
            200,
        )
        second_refile = validate_success(
            api.resubmit_title(title["id"], {"owner_name": "Tia Tel"}, title_clerk_headers), 200
        )
        assert second_refile["state"] == "SUBMITTED"
        assert second_refile["rejection_count"] == 2

    def test_third_rejection_closes_the_refiling_loop(self, api, title_clerk_headers):
        """PRD §3.4: "The program tolerates two DMV rejections: a resubmission is accepted
        while `rejection_count` is no greater than two, so the first and second rejections
        may both be refiled, but a third rejection leaves the count at three and the next
        resubmission is refused with `ERR_TITLE_RESUBMIT_LIMIT`."
        PRD §3.4: "Resubmission moves the record `REJECTED → SUBMITTED`, re-mints
        `dmv_filing_reference`, restamps `submitted_at_utc`, and may optionally correct
        the `title_number` or the `owner_name` in the same call."

        Design: Difficulty/non_linear_state_machine/title_record_reject_resubmit_cycle_hits_resubmit_limit
        """
        _, title = _rejected_once(title_clerk_headers, api)
        for reason in ["odometer statement missing", "lien release absent"]:
            validate_success(
                api.resubmit_title(title["id"], {"owner_name": "Tia Tel"}, title_clerk_headers), 200
            )
            validate_success(
                api.record_dmv_decision(
                    title["id"], {"outcome": "REJECTED", "rejection_reason": reason},
                    title_clerk_headers,
                ),
                200,
            )

        third = read_title(title["id"])
        assert third["state"] == "REJECTED"
        assert third["rejection_count"] == 3

        refused = api.resubmit_title(title["id"], {"owner_name": "Tia Tel"}, title_clerk_headers)
        validate_error(refused, ApiErrorId.ERR_TITLE_RESUBMIT_LIMIT.value)

        after = read_title(title["id"])
        assert after["state"] == "REJECTED", "the refused refile leaves the record where it was"
        assert after["rejection_reason"] == "lien release absent"


class TestTitleAbandonment:
    def test_abandoning_a_rejected_title_raises_a_stale_title_obligation(self, api):
        """PRD §3.4: "When refiling is hopeless, the clerk abandons the title with a
        `reason`, moving it `REJECTED → ABANDONED` — the other terminal state. Abandoning
        raises a follow-up obligation of type `TITLE_STALE`, opened for that donation,
        assigned to `TitleClerk`, and due fifteen days after the current logical clock."

        Design: Corner/state_machines/corner_title_abandon_creates_a_stale_title_follow_up_task
        """
        bundle = setup_abandoned_title_task(clock="2026-07-05T00:00:00Z")

        assert bundle["title"]["state"] == "ABANDONED"
        tasks = donation_tasks(bundle["donation"]["id"])
        assert len(tasks) == 1
        task = tasks[0]
        assert_follow_up_task(task)
        assert task["task_type"] == "TITLE_STALE"
        assert task["status"] == "OPEN"
        assert task["assigned_role"] == "TitleClerk"
        assert task["due_utc"].startswith("2026-07-20T00:00:00")
        assert read_donation(bundle["donation"]["id"])["status"] == "ACCEPTED"


class TestRegistryUniqueness:
    def test_duplicate_title_record_email_and_ein_are_each_refused(
        self, api, title_clerk_headers, intake_agent_headers, program_admin_headers
    ):
        """PRD §3.4: "A second title record for the same donation is refused with
        `ERR_DUPLICATE_TITLE_RECORD`."
        PRD §3.1: "Email addresses are unique across donors; a collision reports
        `ERR_DUPLICATE_EMAIL`."
        PRD §3.1: "Both `name` and `ein` are required, and `ein` must be unique across all
        affiliates — a repeat registration is refused with `ERR_DUPLICATE_EIN`."

        Design: Corner/errors/corner_duplicate_title_record_and_duplicate_natural_keys_are_refused
        """
        charity = new_charity(name="Unique Trust", ein="80-0000046")
        donor = new_donor(email="dupe@example.com", full_name="Dup Key")
        donation = new_donation(donor["id"], charity["id"], pickup_required=False)
        accept(donation["id"])
        new_title(donation["id"], title_number="CA-TTL-D1", owner_name="Dup Key")

        duplicate_title = api.create_title_record(
            create_title_record_payload(
                donation["id"], title_number="CA-TTL-D2", owner_name="Dup Key"
            ),
            title_clerk_headers,
        )
        validate_error(duplicate_title, ApiErrorId.ERR_DUPLICATE_TITLE_RECORD.value)

        duplicate_email = api.create_donor(
            create_donor_payload(
                email="dupe@example.com", full_name="Other Person", state_code="NV"
            ),
            intake_agent_headers,
        )
        validate_error(duplicate_email, ApiErrorId.ERR_DUPLICATE_EMAIL.value)

        duplicate_ein = api.create_charity(
            create_charity_payload(name="Copycat Trust", ein="80-0000046", state_code="NV"),
            program_admin_headers,
        )
        validate_error(duplicate_ein, ApiErrorId.ERR_DUPLICATE_EIN.value)

        rows, _ = validate_paginated(
            api.list_title_records(title_clerk_headers, params={"donation_id": donation["id"]})
        )
        assert len(rows) == 1
        assert rows[0]["state"] == "DRAFT"

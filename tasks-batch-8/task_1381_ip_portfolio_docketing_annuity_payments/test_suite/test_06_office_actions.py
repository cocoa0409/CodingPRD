"""Office actions: auto-created response entries, informational close branch,
FK reverse reachability (PRD §3.3)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_us_rule,
    create_client,
    create_family,
    create_pending_application,
    create_granted_application,
    create_docket_entry_payload,
    create_office_action_payload,
    list_obligations,
)

ANY = TEST_USERS["any_headers"]
CLERK = TEST_USERS["clerk_headers"]


class TestOfficeActionAutoEntryDates:
    def test_month_arithmetic_preserves_day_of_month(self):
        """PRD §3.3: "the system auto-creates a response-tracking docket entry
        of type `OFFICE_ACTION_RESPONSE` whose `base_due_date` is the action's
        `mail_date` shifted forward by the jurisdiction rule's
        `oa_response_months` — month arithmetic preserves the day of month,
        clamping to the last day of the target month when that month is
        shorter — increments the application's `open_docket_count` by one, and
        stores the new entry's identifier in the action's `docket_entry_id`"

        Design: Corner/calculations/oa_due_date_month_arithmetic_and_clamp
        """
        create_us_rule()
        client = create_client("DueCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-DUE")
        action = validate_success(api_client.create_office_action(
            app["id"], create_office_action_payload(action_type="NON_FINAL_REJECTION",
                                                    mail_date="2026-05-31"), CLERK), 201)
        entry = validate_success(api_client.get_docket_entry(action["docket_entry_id"], ANY), 200)
        # 2026-05-31 + 3 months -> 2026-08-31 (August has 31 days).
        assert entry["base_due_date"] == "2026-08-31"
        assert entry["entry_type"] == "OFFICE_ACTION_RESPONSE"

    def test_month_arithmetic_clamps_to_short_month_last_day(self):
        """PRD §3.3: "month arithmetic preserves the day of month, clamping to
        the last day of the target month when that month is shorter"

        Design: Corner/calculations/oa_due_date_month_arithmetic_and_clamp
        """
        create_us_rule()
        client = create_client("DueCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-DUE")
        action = validate_success(api_client.create_office_action(
            app["id"], create_office_action_payload(action_type="FINAL_REJECTION",
                                                    mail_date="2026-11-30"), CLERK), 201)
        entry = validate_success(api_client.get_docket_entry(action["docket_entry_id"], ANY), 200)
        # 2026-11-30 + 3 months -> 2027-02-28 (2027 is not a leap year).
        assert entry["base_due_date"] == "2027-02-28"


class TestOfficeActionInformationalCloseBranch:
    def test_informational_closes_directly_and_carries_no_entry(self):
        """PRD §3.3: "for `NOTICE_OF_ALLOWANCE` and `INFORMATIONAL` actions the
        `docket_entry_id` remains null. A clerk may close an `INFORMATIONAL` or
        `NOTICE_OF_ALLOWANCE` action directly (`RECEIVED → CLOSED`); attempting
        that closure on a rejection type is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/office_action_informational_close_branch
        """
        create_us_rule()
        client = create_client("OACo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-OA")
        action = validate_success(api_client.create_office_action(
            app["id"], create_office_action_payload(action_type="INFORMATIONAL",
                                                    mail_date="2026-05-01"), CLERK), 201)
        assert action["docket_entry_id"] is None
        data = validate_success(api_client.close_informational_office_action(action["id"], CLERK), 200)
        assert data["status"] == "CLOSED"

    def test_close_informational_on_rejection_type_rejected(self):
        """PRD §3.3: "attempting that closure on a rejection type is rejected
        with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/office_action_informational_close_branch
        """
        create_us_rule()
        client = create_client("OACo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-OA")
        action = validate_success(api_client.create_office_action(
            app["id"], create_office_action_payload(action_type="NON_FINAL_REJECTION",
                                                    mail_date="2026-05-20"), CLERK), 201)
        validate_error(api_client.close_informational_office_action(action["id"], CLERK),
                       ApiErrorId.ERR_INVALID_STATE)


class TestFkReverseReachability:
    def test_entry_office_actions_and_obligation_listing(self):
        """PRD §3.3: "Office actions are listed per application, per tracking
        entry (at most one action references an entry)"; PRD §3.5: "Obligations
        are listed per application — ordered by `period_year` ascending,
        optionally filtered by `status` — or across the portfolio filtered
        by `application_id` or `status`."

        Design: Corner/entities/fk_reverse_reachability_returns_arrays
        """
        create_us_rule()
        client = create_client("FKCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-FK")
        action = validate_success(api_client.create_office_action(
            app["id"], create_office_action_payload(mail_date="2026-05-20"), CLERK), 201)
        manual = validate_success(api_client.create_docket_entry(
            app["id"], create_docket_entry_payload(entry_type="RECORDATION", title="M",
                                                   base_due_date="2026-09-01"), CLERK), 201)
        validate_success(api_client.grant_application(app["id"], {"grant_date": "2026-03-01"}, CLERK), 200)

        linked = validate_success(
            api_client.list_office_actions_of_entry(action["docket_entry_id"], ANY), 200)
        assert isinstance(linked, list) and len(linked) == 1
        assert linked[0]["id"] == action["id"]

        unlinked = validate_success(api_client.list_office_actions_of_entry(manual["id"], ANY), 200)
        assert isinstance(unlinked, list) and len(unlinked) == 0

        obligations = list_obligations(app["id"])
        assert [o["period_year"] for o in obligations] == [3, 4, 5]

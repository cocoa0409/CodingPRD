"""Exercise-notice lifecycle: delivery, rejection, redelivery, duplicate-open
prevention, acknowledgment gating, and the acknowledge cascade to option,
ledger, and reminders."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_exercise_notice,
    create_notice_payload,
    create_option_payload,
    get_success_data,
    reject_notice_payload,
    set_clock,
    setup_active_lease,
    setup_notice_delivered,
    setup_notice_sent,
    setup_option_on_active_lease,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestNoticeStateMachine:
    def test_acknowledge_before_delivery_returns_invalid_state(self, api):
        """PRD §3.5: "Receipt is acknowledged by `LandlordCounsel`, moving the
        notice `DELIVERED` → `ACKNOWLEDGED`"

        Design: Corner/state_machines/acknowledge_before_delivery_returns_invalid_state
        """
        ws = setup_notice_sent(name="SM1", region="WEST", with_lc=True)
        # The notice is still SENT (never delivered).
        resp = api.acknowledge_notice(
            ws["pid"], ws["lid"], ws["oid"], ws["nid"], ws["lc_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        notice = validate_success(api.get_notice(
            ws["pid"], ws["lid"], ws["oid"], ws["nid"], ADMIN))
        assert notice["status"] == "SENT"
        opt = validate_success(api.get_option(ws["pid"], ws["lid"], ws["oid"], ADMIN))
        assert opt["status"] == "NOTICE_SENT"

    def test_redelivery_after_rejection_creates_fresh_notice(self, api):
        """PRD §3.5: "While the clock date remains on or before the
        `notice_window_close_date` and every prior notice on the option sits in
        `VOID` or `REJECTED`, the `AssetManager` may deliver a fresh notice under
        the same lease-version guard; the previously rejected notice becomes
        `VOID`, a new notice is created in `SENT`, and the lease's `version`
        increments again."

        Design: Corner/state_machines/redelivery_after_rejection_creates_fresh_notice
        """
        ws = setup_notice_sent(name="SM2", region="EAST", delivery_method="CERTIFIED_MAIL")
        # Reject the first notice.
        get_success_data(api.reject_notice(
            ws["pid"], ws["lid"], ws["oid"], ws["nid"],
            reject_notice_payload("bad address"), ws["bk_headers"]))
        # Read the current lease version (bumped by the first notice create).
        lease = get_success_data(api.get_lease(ws["pid"], ws["lid"], ws["am_headers"]))
        # Re-deliver with the up-to-date version.
        payload = create_notice_payload(lease["version"],
                                        delivery_method="PERSONAL_DELIVERY")
        resp = api.create_notice(ws["pid"], ws["lid"], ws["oid"], payload,
                                 ws["am_headers"])
        notice2 = validate_success(resp, 201)
        assert notice2["id"] != ws["nid"], "A fresh notice id is minted on re-delivery"
        assert notice2["status"] == "SENT"

        old = validate_success(api.get_notice(
            ws["pid"], ws["lid"], ws["oid"], ws["nid"], ADMIN))
        assert old["status"] == "VOID", "The previously rejected notice becomes VOID"
        opt = validate_success(api.get_option(ws["pid"], ws["lid"], ws["oid"], ADMIN))
        assert opt["status"] == "NOTICE_SENT"

    def test_second_notice_while_open_returns_notice_already_open(self, api):
        """PRD §3.5: "no other notice on the option may be open in `SENT` or
        `DELIVERED` (else `ERR_NOTICE_ALREADY_OPEN`)"

        Design: Corner/state_machines/second_notice_while_open_returns_notice_already_open
        """
        ws = setup_notice_sent(name="SM3", region="WEST")
        lease = get_success_data(api.get_lease(ws["pid"], ws["lid"], ws["am_headers"]))
        payload = create_notice_payload(lease["version"], delivery_method="COURIER")
        resp = api.create_notice(ws["pid"], ws["lid"], ws["oid"], payload,
                                 ws["am_headers"])
        validate_error(resp, ApiErrorId.ERR_NOTICE_ALREADY_OPEN)
        notice = validate_success(api.get_notice(
            ws["pid"], ws["lid"], ws["oid"], ws["nid"], ADMIN))
        assert notice["status"] == "SENT", "The open notice survives the duplicate attempt"


class TestWithdrawalAndTerminalStates:
    def test_terminal_option_rejects_withdraw(self, api):
        """PRD §3.8: "an `AssetManager` may withdraw an unexercised option — from
        `AVAILABLE`, `WINDOW_OPEN`, or `NOTICE_SENT`"
        PRD §3.8: lapse moves the option to `LAPSED` (terminal), which is not in
        the withdrawable set.

        Design: Corner/state_machines/terminal_option_rejects_withdraw
        """
        ws = setup_option_on_active_lease(
            name="SM4", region="WEST",
            option_overrides={
                "option_type": "ROFR",
                "notice_window_open_date": "2026-08-10T00:00:00Z",
                "notice_window_close_date": "2026-09-10T00:00:00Z",
                "target_commencement_date": "2027-06-01T00:00:00Z",
                "rate_determination": "FIXED",
                "fixed_rent_cents_per_rsf_year": 4000,
            })
        set_clock("2026-09-11T00:00:00Z")  # past the close; option lapses
        lease = get_success_data(api.get_lease(ws["pid"], ws["lid"], ws["am_headers"]))
        resp = api.withdraw_option(
            ws["pid"], ws["lid"], ws["oid"],
            {"expected_lease_version": lease["version"]}, ws["am_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        opt = validate_success(api.get_option(ws["pid"], ws["lid"], ws["oid"], ADMIN))
        assert opt["status"] == "LAPSED", "LAPSED is terminal; withdraw must not move it"


class TestInitialStates:
    def test_initial_states_on_creation(self, api):
        """PRD §3.2: "A new lease starts in `DRAFT`"
        PRD §3.3: "A new option starts `AVAILABLE`."
        PRD §3.7: "A new amendment starts in `DRAFT`"

        Design: Corner/state_machines/initial_states_on_creation
        """
        from test_helpers import (
            create_amendment,
            create_lease,
            create_option,
            setup_portfolio_with_contacts,
        )
        ws = setup_portfolio_with_contacts(name="SM5", region="WEST")
        lease = create_lease(ws["pid"], ws["am_headers"], premises_label="S5")
        assert lease["status"] == "DRAFT", "Lease initial state is DRAFT"

        lease = get_success_data(api.activate_lease(
            ws["pid"], lease["id"], {}, ws["am_headers"]))
        ws["lease"] = lease
        ws["lid"] = lease["id"]
        option = create_option(ws["pid"], ws["lid"], ws["am_headers"],
                               option_type="RENEWAL", extension_years=5)
        assert option["status"] == "AVAILABLE", "Option initial state is AVAILABLE"
        ws["oid"] = option["id"]

        amendment = create_amendment(ws)
        assert amendment["status"] == "DRAFT", "Amendment initial state is DRAFT"

        # Assessments are covered by test_05 (assessment lifecycle); their
        # initial state PROVISIONAL is asserted there.

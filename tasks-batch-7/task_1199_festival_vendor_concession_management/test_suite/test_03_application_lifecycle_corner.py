"""Corner: vendor application lifecycle — initial state, decide gate, withdraw rules."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_application,
    api_client,
    create_vendor,
    get_application,
    make_vendor_headers,
    setup_accepted_application,
    setup_open_festival,
    setup_submitted_application,
    start_review,
    submit_application,
    validate_error,
    validate_success,
)

VM = TEST_USERS["vendor_manager_headers"]


class TestApplicationInitialState:
    def test_application_initial_state_submitted(self, api):
        """PRD §3.2: "A fresh application enters `SUBMITTED` with `review_round`
        zero."

        Design: Corner/state_machines/application_initial_state_submitted
        """
        scen = setup_open_festival(name="Init Fest")
        vendor = create_vendor(legal_name="Init LLC")
        resp = api.create_application(
            {
                "vendor_id": vendor["id"], "festival_id": scen["festival"]["id"],
                "category": "DESSERT", "fee_model": "FLAT_FEE",
                "proposed_flat_fee_cents": 30000, "power_needed_amps": 10,
                "requires_water": False,
            },
            make_vendor_headers(vendor["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SUBMITTED"
        assert data["review_round"] == 0


class TestDecideGate:
    def test_application_decide_before_review_rejected(self, api):
        """PRD §3.2: "The curation decision moves an `UNDER_REVIEW` application to
        `ACCEPTED`, `REJECTED`, or `WAITLISTED` according to the submitted
        `decision`."
        PRD §2.10: "Eighth, state-machine legality of the requested transition,
        including terminal-state lockdown, together with request-shape validity —
        missing required fields, malformed values, and enum violations surface as
        `ERR_INVALID_REQUEST` (HTTP 400), while an illegal transition surfaces as
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409) (8)."

        Design: Corner/state_machines/application_decide_before_review_rejected
        """
        scen = setup_submitted_application(name="Early Decide Fest")
        resp = api.decide_application(
            scen["app"]["id"],
            {"decision": "ACCEPTED", "curated_fee_model": "FLAT_FEE", "curated_flat_fee_cents": 50000},
            VM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestWithdraw:
    def test_application_withdraw_success_for_owner(self, api):
        """PRD §3.2: "A vendor may withdraw its own application from any of
        `SUBMITTED`, `UNDER_REVIEW`, `CHANGES_REQUESTED`, or `WAITLISTED`, moving
        it to `WITHDRAWN`".

        Design: Corner/state_machines/application_withdraw_success_for_owner
        """
        scen = setup_submitted_application(name="Withdraw Fest")
        resp = api.withdraw_application(scen["app"]["id"], make_vendor_headers(scen["vendor"]["id"]))
        data = validate_success(resp)
        assert data["status"] == "WITHDRAWN"

    def test_application_withdraw_from_accepted_rejected(self, api):
        """PRD §2.10: "Eighth, state-machine legality of the requested transition,
        including terminal-state lockdown, together with request-shape validity —
        missing required fields, malformed values, and enum violations surface as
        `ERR_INVALID_REQUEST` (HTTP 400), while an illegal transition surfaces as
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409) (8)."

        Design: Corner/state_machines/application_withdraw_from_accepted_rejected
        """
        scen = setup_accepted_application(name="Lock Fest")
        assert scen["app"]["status"] == "ACCEPTED"
        resp = api.withdraw_application(scen["app"]["id"], make_vendor_headers(scen["vendor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_application(scen["app"]["id"])
        assert after["status"] == "ACCEPTED", "terminal lockdown: rejected withdraw changed nothing"

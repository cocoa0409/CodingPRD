"""State-machine corner cases: initial states, invalid transitions, idempotency,
terminal-state lockdown, side-effect execution, and guarded transitions.

Corner queue: state_machines section.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    create_open_campaign, create_campaign, create_donor,
    setup_open_campaign_with_donor, create_pledge, record_gift,
    create_planned_gift,
)

CM = TEST_USERS["campaign_manager_headers"]
GA = TEST_USERS["gift_admin_headers"]
DR = TEST_USERS["donor_relations_headers"]


class TestStateMachineCorners:
    def test_gift_initial_state_recorded(self, api):
        """PRD §3.3: "A freshly recorded gift starts in `RECORDED` with no ledger
        postings yet; postings happen only at acknowledgement."

        Design: Corner/state_machines/gift_initial_state_recorded
        """
        camp, donor = setup_open_campaign_with_donor()
        gift = record_gift(camp["id"], donor["id"], amount_cents=5000)
        assert gift["status"] == "RECORDED"

    def test_receipt_from_recorded_returns_invalid_state(self, api):
        """PRD §3.9: "It is permitted only while the gift is `ACKNOWLEDGED`". PRD §2.6:
        "an operation requested against a resource not in a valid state for the
        requested transition yields `ERR_INVALID_STATE` (HTTP 409)."

        Receipting a RECORDED (not yet ACKNOWLEDGED) gift -> ERR_INVALID_STATE.

        Design: Corner/state_machines/receipt_from_recorded_returns_invalid_state
        """
        camp, donor = setup_open_campaign_with_donor()
        gift = record_gift(camp["id"], donor["id"], amount_cents=5000)
        validate_error(api.receipt_gift(gift["id"], DR), ApiErrorId.ERR_INVALID_STATE.value)

    def test_acknowledge_twice_returns_invalid_state(self, api):
        """PRD §3.3: "it requires the gift to be in `RECORDED` and its donor's
        `lifecycle_status` to be anything other than `ARCHIVED`". PRD §2.6: "an
        operation requested against a resource not in a valid state for the requested
        transition yields `ERR_INVALID_STATE` (HTTP 409)."

        A second acknowledge on an ACKNOWLEDGED gift -> ERR_INVALID_STATE.

        Design: Corner/state_machines/acknowledge_twice_returns_invalid_state
        """
        camp, donor = setup_open_campaign_with_donor()
        gift = record_gift(camp["id"], donor["id"], amount_cents=5000)
        validate_success(api.acknowledge_gift(gift["id"], DR))
        validate_error(api.acknowledge_gift(gift["id"], DR), ApiErrorId.ERR_INVALID_STATE.value)

    def test_cancel_terminal_pledge_returns_invalid_state(self, api):
        """PRD §3.5: "Cancelling a pledge is a `GiftAdmin` action permitted only while
        the pledge is `ACTIVE` or `DELINQUENT`". PRD §3.5: "`CANCELLED` and `FULFILLED`
        are the pledge's terminal states." PRD §2.6: state is checked before business
        rules, yielding `ERR_INVALID_STATE`.

        Cancelling a CANCELLED pledge -> ERR_INVALID_STATE (state precedes OCC).

        Design: Corner/state_machines/cancel_terminal_pledge_returns_invalid_state
        """
        camp, donor = setup_open_campaign_with_donor()
        pledge = create_pledge(camp["id"], donor["id"], total_amount_cents=10000,
                               installment_count=2, frequency="MONTHLY")
        cancelled = validate_success(
            api.cancel_pledge(pledge["id"], {"expected_pledge_version": pledge["version"]}, GA)
        )
        assert cancelled["status"] == "CANCELLED"
        validate_error(
            api.cancel_pledge(pledge["id"], {"expected_pledge_version": cancelled["version"]}, GA),
            ApiErrorId.ERR_INVALID_STATE.value,
        )

    def test_planned_gift_confirm_then_realize_mints_gift(self, api):
        """PRD §3.8: "the system creates a gift for the planned gift's donor against
        that campaign for the realized amount with `payment_method` of `STOCK`, starting
        in `RECORDED`, and records that new gift's id in the planned gift's
        `realized_gift_id` while moving the planned gift to `REALIZED`."

        Design: Corner/state_machines/planned_gift_confirm_then_realize_mints_gift
        """
        camp = create_open_campaign(goal_cents=1000000)
        donor = create_donor()
        pg = create_planned_gift(donor["id"], vehicle="BEQUEST", expected_amount_cents=500000)
        get_success_data(api.confirm_planned_gift(pg["id"], DR))
        realized = validate_success(
            api.realize_planned_gift(pg["id"], {"campaign_id": camp["id"], "realized_amount_cents": 500000}, DR)
        )
        assert realized["status"] == "REALIZED"
        assert realized["realized_gift_id"] is not None
        new_gift = validate_success(api.get_gift(realized["realized_gift_id"], GA))
        assert new_gift["status"] == "RECORDED"
        assert new_gift["amount_cents"] == 500000

    def test_planned_gift_realize_into_draft_campaign_rejected(self, api):
        """PRD §3.8: "`DonorRelations` supplies the `campaign_id` of the realizing
        campaign (which must be `OPEN`)". PRD §2.8: "Attempting to attach any of these to
        a campaign that is `DRAFT` or `CLOSED` is rejected with `ERR_CAMPAIGN_NOT_OPEN`
        (HTTP 409)."

        Design: Corner/state_machines/planned_gift_realize_into_draft_campaign_rejected
        """
        camp = create_campaign(goal_cents=1000000)  # left DRAFT
        donor = create_donor()
        pg = create_planned_gift(donor["id"], vehicle="IRA_ROLLOVER", expected_amount_cents=200000)
        get_success_data(api.confirm_planned_gift(pg["id"], DR))
        validate_error(
            api.realize_planned_gift(pg["id"], {"campaign_id": camp["id"], "realized_amount_cents": 200000}, DR),
            ApiErrorId.ERR_CAMPAIGN_NOT_OPEN.value,
        )

    def test_campaign_open_then_close_transition(self, api):
        """PRD §3.1: "A campaign accepts no financial activity until the manager advances
        it from `DRAFT` to `OPEN`; that transition is permitted only from `DRAFT`. When
        the campaign is finished, the manager advances it from `OPEN` to `CLOSED`,
        permitted only from `OPEN`, after which `CLOSED` is terminal."

        Design: Corner/endpoints/campaign_open_then_close_transition
        """
        camp = create_campaign(goal_cents=1000000)
        assert camp["status"] == "DRAFT"
        opened = validate_success(api.open_campaign(camp["id"], CM))
        assert opened["status"] == "OPEN"
        closed = validate_success(api.close_campaign(camp["id"], CM))
        assert closed["status"] == "CLOSED"

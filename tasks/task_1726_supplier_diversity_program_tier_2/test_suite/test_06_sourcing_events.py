"""Sourcing events: inclusion quorum boundary, award guard ordering,
invitation state gating, award cap, cancel cascade, and invalid transitions."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    award_event_payload,
    create_business_unit,
    create_invitation_payload,
    create_open_event_with_bidder,
    create_sourcing_event,
    create_supplier,
    create_supplier_with_verified_cert,
    get_success_data,
    invite_supplier,
    open_sourcing_event,
    respond_invitation,
    respond_invitation_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN1 = TEST_USERS["admin_1_headers"]
LEAD1 = TEST_USERS["lead_1_headers"]


class TestInvalidTransitions:
    def test_award_draft_event_rejected(self, api):
        """PRD §3.7: "Awarding an `OPEN` event takes `award_supplier_id`,
        `award_amount_cents`, and optionally `inclusion_waiver_reason`."
        PRD §2.8: "Fourth, whether the target resource is in a state from
        which the requested transition is defined."

        Design: Corner/state_machines/award_draft_event_rejected
        """
        bu = create_business_unit()
        supplier = create_supplier(legal_name="Bidder Co", tax_id="T-BID")
        event = create_sourcing_event(bu["id"], title="Draft event",
                                      required_diverse_bidders=0)
        resp = api.award_sourcing_event(
            event["id"], award_event_payload(supplier["id"], 90000), LEAD1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_respond_after_award_rejected(self, api):
        """PRD §3.7: "Recording a bid response takes `response` equal to
        `BID_SUBMITTED` or `DECLINED`; it is defined only for an invitation
        currently `INVITED` whose owning event is `OPEN` — if the event is
        not `OPEN` the caller sees `ERR_INVALID_STATE`."
        PRD §3.7: "The invitation cascade then runs: the winning invitation
        becomes `WON`, every other invitation in `BID_SUBMITTED` becomes
        `LOST`, every invitation still `INVITED` becomes `NO_RESPONSE`, and
        invitations in `DECLINED` or `WITHDRAWN` are unchanged."

        Design: Corner/state_machines/respond_after_award_rejected
        """
        bu = create_business_unit()
        winner, _cert = create_supplier_with_verified_cert(
            legal_name="Winner Co", tax_id="T-WIN", certificate_number="M-W")
        silent = create_supplier(legal_name="Silent Co", tax_id="T-SIL")
        event, _inv_w = create_open_event_with_bidder(
            bu["id"], winner["id"], title="Fasteners",
            required_diverse_bidders=0)
        inv_x = invite_supplier(event["id"], silent["id"])
        awarded = validate_success(api.award_sourcing_event(
            event["id"], award_event_payload(winner["id"], 90000), LEAD1))
        assert awarded["status"] == "AWARDED"
        # The non-responsive invitation left INVITED for NO_RESPONSE, and the
        # event is AWARDED: respond is undefined.
        resp = api.respond_invitation(
            inv_x["id"], respond_invitation_payload("BID_SUBMITTED"), LEAD1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_cancel_open_event_withdraws_pending_invitations(self, api):
        """PRD §3.7: "Cancelling is available from `DRAFT` or `OPEN` and moves
        the event to `CANCELLED`; cancelling an `OPEN` event additionally
        moves its invitations that are still `INVITED` to `WITHDRAWN`, while
        invitations already in `BID_SUBMITTED` or `DECLINED` are unchanged."

        Design: Corner/state_machines/cancel_open_event_withdraws_pending_invitations
        """
        bu = create_business_unit()
        supplier_a, _cert = create_supplier_with_verified_cert(
            legal_name="Diverse A", tax_id="T-DA", certificate_number="M-A")
        supplier_b = create_supplier(legal_name="Bidder B", tax_id="T-BB")
        event, inv_a = create_open_event_with_bidder(
            bu["id"], supplier_a["id"], title="Paint shop",
            estimated_value_cents=200000, required_diverse_bidders=1)
        inv_b = invite_supplier(event["id"], supplier_b["id"])
        cancelled = validate_success(
            api.cancel_sourcing_event(event["id"], LEAD1))
        assert cancelled["status"] == "CANCELLED"
        invs_b, _meta = validate_paginated(
            api.list_supplier_invitations(supplier_b["id"], ADMIN1))
        assert invs_b[0]["status"] == "WITHDRAWN", (
            "The still-INVITED invitation is withdrawn"
        )
        invs_a, _meta = validate_paginated(
            api.list_supplier_invitations(supplier_a["id"], ADMIN1))
        assert invs_a[0]["status"] == "BID_SUBMITTED", (
            "The BID_SUBMITTED invitation is unchanged by the cancel"
        )


class TestInvitationConstraints:
    def test_duplicate_invitation_rejected(self, api):
        """PRD §3.7: "an event may hold at most one invitation per supplier —
        a second invitation for the same `(sourcing_event, supplier)` pair is
        `ERR_DUPLICATE_INVITATION`."

        Design: Corner/validations/duplicate_invitation_rejected
        """
        bu = create_business_unit()
        supplier = create_supplier(legal_name="Bidder Co", tax_id="T-BID")
        event = create_sourcing_event(bu["id"], title="Rivets",
                                      estimated_value_cents=50000,
                                      required_diverse_bidders=0)
        open_sourcing_event(event["id"])
        invite_supplier(event["id"], supplier["id"])
        resp = api.create_invitation(
            event["id"], create_invitation_payload(supplier["id"]), LEAD1)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_INVITATION)


class TestAwardCap:
    def test_award_amount_equal_estimate_boundary(self, api):
        """PRD §3.7: "At the fiscal tier, `award_amount_cents` must not exceed
        `estimated_value_cents`; an overage is `ERR_AWARD_ABOVE_LIMIT`."

        Design: Corner/validations/award_amount_equal_estimate_boundary
        """
        bu = create_business_unit()
        winner, _cert = create_supplier_with_verified_cert(
            legal_name="Winner Co", tax_id="T-WIN", certificate_number="M-W")
        event, _inv = create_open_event_with_bidder(
            bu["id"], winner["id"], title="Cap test",
            estimated_value_cents=100000, required_diverse_bidders=0)
        resp = api.award_sourcing_event(
            event["id"], award_event_payload(winner["id"], 100001), LEAD1)
        validate_error(resp, ApiErrorId.ERR_AWARD_ABOVE_LIMIT)
        awarded = validate_success(api.award_sourcing_event(
            event["id"], award_event_payload(winner["id"], 100000), LEAD1))
        assert awarded["status"] == "AWARDED", (
            "An award equal to the estimate passes the inclusive cap"
        )


class TestInclusionBoundary:
    def _setup_two_diverse_bidders(self, api):
        """Two ACTIVE diverse suppliers, each holding a VERIFIED MBE cert."""
        bu = create_business_unit()
        supplier_a, _ = create_supplier_with_verified_cert(
            legal_name="Diverse A", tax_id="T-DA", certificate_number="M-A")
        supplier_b, _ = create_supplier_with_verified_cert(
            legal_name="Diverse B", tax_id="T-DB", certificate_number="M-B")
        return bu, supplier_a, supplier_b

    def test_inclusion_exact_minimum_awards(self, api):
        """PRD §3.7: "At the quota tier, the event's current
        `diverse_bid_count` must be at least `required_diverse_bidders` —
        exactly equal passes — unless an `inclusion_waiver_reason` was
        supplied; an unwaived shortfall is `ERR_INCLUSION_SHORTFALL`."
        PRD §3.7: "The invitation cascade then runs: the winning invitation
        becomes `WON`, every other invitation in `BID_SUBMITTED` becomes
        `LOST`, every invitation still `INVITED` becomes `NO_RESPONSE`, and
        invitations in `DECLINED` or `WITHDRAWN` are unchanged."

        Design: Difficulty/boundary_precision_check/inclusion_count_exact_minimum_boundary
        """
        bu, supplier_a, supplier_b = self._setup_two_diverse_bidders(api)
        event, inv_a = create_open_event_with_bidder(
            bu["id"], supplier_a["id"], title="E1 brackets",
            estimated_value_cents=500000, required_diverse_bidders=2)
        inv_b = invite_supplier(event["id"], supplier_b["id"])
        respond_invitation(inv_b["id"], "BID_SUBMITTED")
        pre = validate_success(api.get_sourcing_event(event["id"], LEAD1))
        assert pre["diverse_bid_count"] == 2
        awarded = validate_success(api.award_sourcing_event(
            event["id"], award_event_payload(supplier_a["id"], 400000), LEAD1))
        assert awarded["status"] == "AWARDED", (
            "diverse_bid_count == 2 == required_diverse_bidders passes at "
            "equality"
        )
        invs, _meta = validate_paginated(
            api.list_event_invitations(event["id"], LEAD1))
        by_supplier = {i["supplier_id"]: i["status"] for i in invs}
        assert by_supplier[supplier_a["id"]] == "WON"
        assert by_supplier[supplier_b["id"]] == "LOST"

    def test_inclusion_one_below_minimum_shortfall(self, api):
        """PRD §3.7: "At the quota tier, the event's current
        `diverse_bid_count` must be at least `required_diverse_bidders` —
        exactly equal passes — unless an `inclusion_waiver_reason` was
        supplied; an unwaived shortfall is `ERR_INCLUSION_SHORTFALL`."

        Design: Difficulty/boundary_precision_check/inclusion_count_exact_minimum_boundary
        """
        bu, supplier_a, supplier_b = self._setup_two_diverse_bidders(api)
        event, _inv_a = create_open_event_with_bidder(
            bu["id"], supplier_a["id"], title="E2 fasteners",
            estimated_value_cents=100000, required_diverse_bidders=2)
        inv_b = invite_supplier(event["id"], supplier_b["id"])
        respond_invitation(inv_b["id"], "DECLINED")
        pre = validate_success(api.get_sourcing_event(event["id"], LEAD1))
        assert pre["diverse_bid_count"] == 1, (
            "A DECLINED invitation does not count toward the quorum"
        )
        resp = api.award_sourcing_event(
            event["id"], award_event_payload(supplier_a["id"], 100000), LEAD1)
        validate_error(resp, ApiErrorId.ERR_INCLUSION_SHORTFALL)
        stored = validate_success(api.get_sourcing_event(event["id"], LEAD1))
        assert stored["status"] == "OPEN", (
            "The shortfall-rejected award leaves the event OPEN"
        )


class TestAwardGuardOrdering:
    def _setup_registered_bidder_event(self, api):
        """OPEN event (required_diverse_bidders 0, so the quota tier passes)
        with a REGISTERED supplier — never activated, holding no
        certification — in BID_SUBMITTED."""
        bu = create_business_unit()
        supplier = create_supplier(legal_name="Unproven LLC", tax_id="T-UNP")
        event, _inv = create_open_event_with_bidder(
            bu["id"], supplier["id"], title="Cable harnesses",
            estimated_value_cents=100000, required_diverse_bidders=0)
        return event, supplier

    def test_award_ineligible_supplier_safety_beats_fiscal(self, api):
        """PRD §3.7: "Several guards compose here, and their priority follows
        §2.8."
        PRD §3.7: "At the eligibility tier, the `award_supplier_id` must hold
        an invitation on this event currently in `BID_SUBMITTED` and that
        supplier must currently be `ACTIVE`, otherwise
        `ERR_SUPPLIER_NOT_ELIGIBLE`."
        PRD §3.7: "At the fiscal tier, `award_amount_cents` must not exceed
        `estimated_value_cents`; an overage is `ERR_AWARD_ABOVE_LIMIT`."

        Design: Difficulty/priority_pair_validation_conflict/award_ineligible_supplier_safety_beats_fiscal
        """
        event, supplier = self._setup_registered_bidder_event(api)
        # Both failures hold: winner not ACTIVE (eligibility) and 200000 >
        # 100000 estimated cap (fiscal). The eligibility error wins.
        resp = api.award_sourcing_event(
            event["id"], award_event_payload(supplier["id"], 200000), LEAD1)
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_ELIGIBLE)
        stored = validate_success(api.get_sourcing_event(event["id"], LEAD1))
        assert stored["status"] == "OPEN", (
            "The rejected award leaves the event OPEN"
        )

    def test_award_ineligible_supplier_within_cap_still_rejected(self, api):
        """PRD §3.7: "At the eligibility tier, the `award_supplier_id` must
        hold an invitation on this event currently in `BID_SUBMITTED` and that
        supplier must currently be `ACTIVE`, otherwise
        `ERR_SUPPLIER_NOT_ELIGIBLE`."

        Design: Difficulty/priority_pair_validation_conflict/award_ineligible_supplier_safety_beats_fiscal
        """
        event, supplier = self._setup_registered_bidder_event(api)
        # Amount inside the cap: the eligibility failure stands alone.
        resp = api.award_sourcing_event(
            event["id"], award_event_payload(supplier["id"], 50000), LEAD1)
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_ELIGIBLE)
        stored = validate_success(api.get_sourcing_event(event["id"], LEAD1))
        assert stored["status"] == "OPEN"


class TestAwardInvitationStateGate:
    def _setup_invited_not_bidder(self, api):
        """OPEN event (required 0) with an ACTIVE diverse supplier invited but
        not yet responded."""
        bu = create_business_unit()
        supplier, _cert = create_supplier_with_verified_cert(
            legal_name="Gate Co", tax_id="T-GTE", certificate_number="M-G")
        event = create_sourcing_event(bu["id"], title="Gate valves",
                                      estimated_value_cents=100000,
                                      required_diverse_bidders=0)
        open_sourcing_event(event["id"])
        invitation = invite_supplier(event["id"], supplier["id"])
        return event, supplier, invitation

    def test_award_rejected_while_invitation_pending(self, api):
        """PRD §3.7: "At the eligibility tier, the `award_supplier_id` must
        hold an invitation on this event currently in `BID_SUBMITTED` and
        that supplier must currently be `ACTIVE`, otherwise
        `ERR_SUPPLIER_NOT_ELIGIBLE`."

        Design: Difficulty/cross_entity_state_dependency/sourcing_award_depends_on_invitation_state
        """
        event, supplier, _inv = self._setup_invited_not_bidder(api)
        resp = api.award_sourcing_event(
            event["id"], award_event_payload(supplier["id"], 90000), LEAD1)
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_ELIGIBLE)
        stored = validate_success(api.get_sourcing_event(event["id"], LEAD1))
        assert stored["status"] == "OPEN"

    def test_award_succeeds_after_bid_submitted(self, api):
        """PRD §3.7: "At the eligibility tier, the `award_supplier_id` must
        hold an invitation on this event currently in `BID_SUBMITTED` and
        that supplier must currently be `ACTIVE`, otherwise
        `ERR_SUPPLIER_NOT_ELIGIBLE`."
        PRD §3.7: "The invitation cascade then runs: the winning invitation
        becomes `WON`, every other invitation in `BID_SUBMITTED` becomes
        `LOST`, every invitation still `INVITED` becomes `NO_RESPONSE`, and
        invitations in `DECLINED` or `WITHDRAWN` are unchanged."

        Design: Difficulty/cross_entity_state_dependency/sourcing_award_depends_on_invitation_state
        """
        event, supplier, invitation = self._setup_invited_not_bidder(api)
        respond_invitation(invitation["id"], "BID_SUBMITTED")
        awarded = validate_success(api.award_sourcing_event(
            event["id"], award_event_payload(supplier["id"], 90000), LEAD1))
        assert awarded["status"] == "AWARDED", (
            "Once the invitation flips to BID_SUBMITTED, the identical award "
            "succeeds"
        )
        invs, _meta = validate_paginated(
            api.list_event_invitations(event["id"], LEAD1))
        assert invs[0]["status"] == "WON"

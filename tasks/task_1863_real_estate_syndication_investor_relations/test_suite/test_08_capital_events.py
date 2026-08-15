"""Capital events: strict proceeds boundary, net-distributable subtraction,
single-active-event occupancy, and the Offering->Property open gate."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_capital_event_payload,
    get_capital_event,
    get_property,
    make_active_syndication,
    make_capital_event,
    make_executed_capital_event,
    make_offering,
    make_property,
    validate_error,
    validate_success,
)

SPONSOR = TEST_USERS["sponsor_operator_headers"]


class TestProceedsStrictlyGreaterBoundary:
    def test_execute_equal_proceeds_rejected(self, api):
        """PRD §3.6: "the gross must strictly exceed the debt payoff, since an
        event whose `gross_proceeds_cents` does not exceed its
        `debt_payoff_cents` is rejected with `ERR_INSUFFICIENT_PROCEEDS`."
        Equal proceeds and payoff do not strictly exceed, so execution is
        rejected.

        Design: Difficulty/boundary_precision_check/capital_event_proceeds_strictly_greater
        """
        syn = make_active_syndication(syndication_name="BpSyn")
        prop = make_property(property_legal_name="P1")
        event = make_capital_event(syn["id"], prop["id"], event_kind="REFINANCE",
                                   gross_proceeds_cents=1_000_000,
                                   debt_payoff_cents=1_000_000)
        resp = api.execute_capital_event(syn["id"], prop["id"], event["id"],
                                         SPONSOR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PROCEEDS, 422)
        assert get_capital_event(syn["id"], prop["id"],
                                 event["id"])["status"] == "ANNOUNCED"

    def test_execute_one_cent_above_succeeds(self, api):
        """PRD §3.6: "the gross must strictly exceed the debt payoff" and "A
        successful execution computes `net_distributable_cents` as
        `gross_proceeds_cents` minus `debt_payoff_cents`, an exact integer
        subtraction with no rounding". Gross one cent above the debt payoff
        executes and locks net_distributable_cents at 1.

        Design: Difficulty/boundary_precision_check/capital_event_proceeds_strictly_greater
        """
        syn = make_active_syndication(syndication_name="BpSyn2")
        prop = make_property(property_legal_name="P2")
        event = make_capital_event(syn["id"], prop["id"], event_kind="REFINANCE",
                                   gross_proceeds_cents=1_000_001,
                                   debt_payoff_cents=1_000_000)
        executed = validate_success(api.execute_capital_event(
            syn["id"], prop["id"], event["id"], SPONSOR))
        assert executed["status"] == "EXECUTED"
        assert executed["net_distributable_cents"] == 1
        assert executed["executed_at"], "executed_at must be stamped"

    def test_execute_below_debt_rejected(self, api):
        """PRD §3.6: "an event whose `gross_proceeds_cents` does not exceed its
        `debt_payoff_cents` is rejected with `ERR_INSUFFICIENT_PROCEEDS`."
        Gross one cent below the debt payoff is rejected.

        Design: Difficulty/boundary_precision_check/capital_event_proceeds_strictly_greater
        """
        syn = make_active_syndication(syndication_name="BpSyn3")
        prop = make_property(property_legal_name="P3")
        event = make_capital_event(syn["id"], prop["id"], event_kind="REFINANCE",
                                   gross_proceeds_cents=999_999,
                                   debt_payoff_cents=1_000_000)
        resp = api.execute_capital_event(syn["id"], prop["id"], event["id"],
                                         SPONSOR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PROCEEDS, 422)


class TestNetDistributable:
    def test_capital_event_net_distributable_subtraction(self, api):
        """PRD §3.6: "A successful execution computes `net_distributable_cents`
        as `gross_proceeds_cents` minus `debt_payoff_cents`, an exact integer
        subtraction with no rounding, stamps `executed_at`".
        8,500,000 - 2,300,000 = 6,200,000.

        Design: Corner/calculations/capital_event_net_distributable_subtraction
        """
        syn = make_active_syndication(syndication_name="NdSyn")
        prop = make_property(property_legal_name="Nd Prop")
        event = make_capital_event(syn["id"], prop["id"], event_kind="REFINANCE",
                                   gross_proceeds_cents=8_500_000,
                                   debt_payoff_cents=2_300_000)
        executed = validate_success(api.execute_capital_event(
            syn["id"], prop["id"], event["id"], SPONSOR))
        assert executed["status"] == "EXECUTED"
        assert executed["net_distributable_cents"] == 6_200_000


class TestSingleActiveEventPerProperty:
    def test_second_active_capital_event_rejected(self, api):
        """PRD §3.6: "a property may host at most one active event at a time —
        announcing a second while one is still `ANNOUNCED` or `EXECUTED` is
        rejected with `ERR_PROPERTY_HAS_ACTIVE_CAPITAL_EVENT`."

        Design: Difficulty/resource_temporal_overlap/capital_event_single_active_per_property
        """
        syn = make_active_syndication(syndication_name="OvSyn")
        prop = make_property(property_legal_name="Ov Prop")
        first = make_capital_event(syn["id"], prop["id"], event_kind="REFINANCE",
                                   gross_proceeds_cents=50_000_000,
                                   debt_payoff_cents=10_000_000)
        assert first["status"] == "ANNOUNCED"
        resp = api.create_capital_event(
            syn["id"], prop["id"],
            create_capital_event_payload(event_kind="SALE",
                                         gross_proceeds_cents=60_000_000,
                                         debt_payoff_cents=20_000_000),
            SPONSOR)
        validate_error(resp, ApiErrorId.ERR_PROPERTY_HAS_ACTIVE_CAPITAL_EVENT, 409)

    def test_new_capital_event_after_cancel_allowed(self, api):
        """PRD §3.6: "An event still merely `ANNOUNCED` can be cancelled,
        moving it to `CANCELLED`." The single-active occupancy covers only
        events "still `ANNOUNCED` or `EXECUTED`", so once the first event is
        cancelled the property accepts a new announcement.

        Design: Difficulty/resource_temporal_overlap/capital_event_single_active_per_property
        """
        syn = make_active_syndication(syndication_name="OvSyn2")
        prop = make_property(property_legal_name="Ov Prop 2")
        first = make_capital_event(syn["id"], prop["id"], event_kind="REFINANCE",
                                   gross_proceeds_cents=50_000_000,
                                   debt_payoff_cents=10_000_000)
        cancelled = validate_success(api.cancel_capital_event(
            syn["id"], prop["id"], first["id"], SPONSOR))
        assert cancelled["status"] == "CANCELLED"
        second = validate_success(api.create_capital_event(
            syn["id"], prop["id"],
            create_capital_event_payload(event_kind="SALE",
                                         gross_proceeds_cents=60_000_000,
                                         debt_payoff_cents=20_000_000),
            SPONSOR), 201)
        assert second["status"] == "ANNOUNCED"


class TestOfferingOpenPropertyGate:
    def test_open_offering_on_owned_property_succeeds(self, api):
        """PRD §3.2: "Opening an offering is gated on two things: the parent
        syndication must be `ACTIVE` — otherwise `ERR_SYNDICATION_NOT_ACTIVE` —
        and the linked property must still be `OWNED`, since an offering cannot
        fund a property already under contract to someone else
        (`ERR_PROPERTY_NOT_OWNED`)." With an ACTIVE syndication and an OWNED
        property, the offering opens.

        Design: Difficulty/cross_entity_state_dependency/offering_open_requires_property_owned
        """
        syn = make_active_syndication(syndication_name="XSyn")
        prop = make_property(property_legal_name="P1")
        assert prop["status"] == "OWNED"
        offering = make_offering(syn["id"], prop["id"], offering_name="OffA")
        opened = validate_success(api.open_offering(syn["id"], offering["id"],
                                                    SPONSOR))
        assert opened["status"] == "OPEN"

    def test_open_offering_on_sold_property_rejected(self, api):
        """PRD §3.2: "Opening an offering is gated on two things: the parent
        syndication must be `ACTIVE` — otherwise `ERR_SYNDICATION_NOT_ACTIVE` —
        and the linked property must still be `OWNED`, since an offering cannot
        fund a property already under contract to someone else
        (`ERR_PROPERTY_NOT_OWNED`)." PRD §3.6: "A successful execution computes
        `net_distributable_cents` as `gross_proceeds_cents` minus
        `debt_payoff_cents`, an exact integer subtraction with no rounding,
        stamps `executed_at`, and — when the event is a `SALE` — moves the
        property's `status` to `SOLD`." An offering linked to a SOLD property
        cannot open.

        Design: Difficulty/cross_entity_state_dependency/offering_open_requires_property_owned
        """
        syn = make_active_syndication(syndication_name="XSyn2")
        prop = make_property(property_legal_name="P2")
        make_executed_capital_event(syn["id"], prop["id"], event_kind="SALE",
                                    gross_proceeds_cents=50_000_000,
                                    debt_payoff_cents=10_000_000)
        assert get_property(prop["id"])["status"] == "SOLD"
        offering = make_offering(syn["id"], prop["id"], offering_name="OffB")
        resp = api.open_offering(syn["id"], offering["id"], SPONSOR)
        validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_OWNED, 409)

"""Two priorities whose whole content is discrimination between near-identical cases.

Five uniqueness scopes share one rung: the SCAC is global, a lane code is scoped
to its event, an invitation to a pairing of event and carrier, a lane bid to a
triple of round, lane and carrier, and a load reference to its own rate record.
One rung below, three separate unfitness reasons share the carrier-standing gate
and must never be conflated — a suspension, a lapsed certificate measured against
the logical clock, and a carrier that never reached a qualified standing.
"""

from test_helpers import (
    ANALYST,
    CATEGORY_MANAGER,
    COMPLIANCE,
    DEFAULT_CLOCK,
    TEST_DEFAULTS,
    add_lane,
    api_client,
    assert_same_instant,
    carrier_status_change_payload,
    create_bid_event,
    create_carrier,
    create_event_with_locked_lanes,
    create_qualified_carrier,
    get_success_data,
    carrier_payload,
    invitation_payload,
    lane_bid_payload,
    lane_payload,
    make_carrier_rep_headers,
    read_allocation,
    read_carrier,
    read_event,
    read_lane,
    read_rate_record,
    second_carrier_overrides,
    set_clock,
    setup_live_rate_record,
    setup_open_round_with_bidder,
    setup_published_routing_guide,
    submit_bid,
    tender_event_payload,
    validate_error,
    validate_success,
)

# The registered carrier's own SCAC, re-used under a different legal name.
SHARED_SCAC = TEST_DEFAULTS["CARRIER_A_SCAC"]
IMPOSTOR_LEGAL_NAME = "Atlantic Freight Lines Duplicate"

# One lane code, used in two events and then twice in the same event.
SHARED_LANE_CODE = "L-SHARED"
SECOND_LANE_CODE = "L-SECOND"

# The tender log entry that is appended once and then replayed.
FIRST_LOAD_REFERENCE = "LD-0001"

# One instant after the carrier's certificate lapses, and the reinstatement clock.
LAPSED_CLOCK = "2027-07-01T00:00:00Z"
CARRIER_EXPIRY = TEST_DEFAULTS["CARRIER_A_INSURANCE_EXPIRY"]


def _register(**overrides):
    """Attempts a carrier registration without asserting the outcome."""
    return api_client.create_carrier(carrier_payload(**overrides), ANALYST)


def _create_lane(event_id, **overrides):
    return api_client.create_lane(event_id, lane_payload(**overrides), ANALYST)


def _invite(event_id, carrier_id, **overrides):
    return api_client.create_invitation(
        event_id, invitation_payload(carrier_id, **overrides), ANALYST
    )


def _attempt_bid(round_id, lane_id, carrier_id, **overrides):
    return api_client.create_lane_bid(
        round_id,
        lane_bid_payload(lane_id, carrier_id, **overrides),
        make_carrier_rep_headers(carrier_id),
    )


def _append_tender(rate_record_id, load_reference, **overrides):
    return api_client.create_tender_event(
        rate_record_id, tender_event_payload(load_reference, **overrides), ANALYST
    )


def _approve(allocation_id):
    """Attempts an allocation approval without asserting the outcome."""
    return api_client.approve_award_allocation(allocation_id, CATEGORY_MANAGER)


def _set_carrier_status(carrier_id, to_status, reason):
    return validate_success(
        api_client.change_carrier_status(
            carrier_id,
            carrier_status_change_payload(to_status=to_status, reason=reason),
            COMPLIANCE,
        )
    )


def _count_tenders(rate_record_id):
    body = get_success_data(api_client.list_tender_events(rate_record_id, ANALYST))
    rows = body["data"] if isinstance(body, dict) and "data" in body else body
    return len(rows)


class TestEachUniquenessScopeReportsItsOwnDuplicate:
    """Five scopes at one priority, each rejecting only its own collision."""

    def test_the_scac_is_global_while_a_lane_code_is_scoped_to_its_event(self):
        """The same code is legal in a second event; the same SCAC never is.

        PRD §2.9: "**Uniqueness.** `scac_code` is unique across all carriers
        (`ERR_DUPLICATE_SCAC`); `lane_code` is unique within its bid event
        (`ERR_DUPLICATE_LANE_CODE`); at most one non-`REVOKED` invitation may exist per
        pairing of event and carrier (`ERR_DUPLICATE_INVITATION`); at most one
        non-`WITHDRAWN` lane bid may exist per combination of round, lane and carrier
        (`ERR_DUPLICATE_LANE_BID`); and `load_reference` is unique within its rate record
        (`ERR_DUPLICATE_LOAD_REFERENCE`)."
        PRD §3.3: "Each lane carries a `lane_code` of 1 to 32 characters, unique within
        its bid event — a repeat inside the same event is rejected with
        `ERR_DUPLICATE_LANE_CODE`, while the same code in a different event is perfectly
        legal"

        Design: Corner/errors/each_uniqueness_scope_reports_its_own_duplicate_error
        """
        set_clock(DEFAULT_CLOCK)
        create_carrier()

        validate_error(
            _register(legal_name=IMPOSTOR_LEGAL_NAME, scac_code=SHARED_SCAC),
            "ERR_DUPLICATE_SCAC",
            409,
        )
        validate_success(_register(**second_carrier_overrides()), 201)

        event_a = create_bid_event()
        add_lane(event_a["id"], lane_code=SHARED_LANE_CODE)
        event_b = create_bid_event()
        validate_success(_create_lane(event_b["id"], lane_code=SHARED_LANE_CODE), 201)
        validate_error(
            _create_lane(event_a["id"], lane_code=SHARED_LANE_CODE),
            "ERR_DUPLICATE_LANE_CODE",
            409,
        )
        assert read_event(event_a["id"])["lane_count"] == 1
        assert read_event(event_b["id"])["lane_count"] == 1

    def test_the_invitation_and_lane_bid_scopes_are_composite_keys(self):
        """One pairing and one triple: change any member and the write is legal.

        PRD §3.4: "At most one invitation that is not `REVOKED` may exist for a given
        pairing of event and carrier; a duplicate is rejected with
        `ERR_DUPLICATE_INVITATION` (409), while re-inviting a carrier whose earlier
        invitation was revoked is permitted."
        PRD §3.5: "At most one bid that is not `WITHDRAWN` may exist for a given
        combination of round, lane and carrier; a second is rejected with
        `ERR_DUPLICATE_LANE_BID` (409), while re-bidding after a withdrawal within the
        same open round is permitted."
        PRD §2.12: "`BidEvent.invited_carrier_count` counts invitations whose status is
        `SENT`, `ACCEPTED` or `DECLINED`, so a revoked invitation drops out of it."

        Design: Corner/errors/each_uniqueness_scope_reports_its_own_duplicate_error
        """
        ctx = setup_open_round_with_bidder(
            lane_overrides=[{}, {"lane_code": SECOND_LANE_CODE}]
        )
        carrier_id = ctx["carrier"]["id"]

        validate_error(
            _invite(ctx["event"]["id"], carrier_id), "ERR_DUPLICATE_INVITATION", 409
        )
        other_event, _lanes = create_event_with_locked_lanes()
        validate_success(_invite(other_event["id"], carrier_id), 201)
        assert read_event(ctx["event"]["id"])["invited_carrier_count"] == 1
        assert read_event(other_event["id"])["invited_carrier_count"] == 1

        submit_bid(ctx["bid_round"]["id"], ctx["lanes"][0]["id"], carrier_id)
        validate_error(
            _attempt_bid(ctx["bid_round"]["id"], ctx["lanes"][0]["id"], carrier_id),
            "ERR_DUPLICATE_LANE_BID",
            409,
        )
        second_lane_bid = validate_success(
            _attempt_bid(ctx["bid_round"]["id"], ctx["lanes"][1]["id"], carrier_id), 201
        )
        assert second_lane_bid["lane_id"] == ctx["lanes"][1]["id"]

    def test_a_load_reference_is_unique_within_its_rate_record(self):
        """The replayed reference is refused and the metrics never move.

        PRD §3.9: "`load_reference` is unique within its rate record
        (`ERR_DUPLICATE_LOAD_REFERENCE`)"
        PRD §2.12: "`RateRecord.tender_count` counts every tender event on the record
        regardless of outcome."
        PRD §3.9: "`rejection_pct` is `0.00` when `tender_count` is zero; otherwise
        multiply `rejection_count` by `100.00`, divide by `tender_count`, and round to 2
        decimal places."

        Design: Corner/errors/each_uniqueness_scope_reports_its_own_duplicate_error
        """
        ctx = setup_live_rate_record()
        record_id = ctx["rate_record"]["id"]

        validate_success(_append_tender(record_id, FIRST_LOAD_REFERENCE), 201)
        validate_error(
            _append_tender(record_id, FIRST_LOAD_REFERENCE),
            "ERR_DUPLICATE_LOAD_REFERENCE",
            409,
        )

        assert _count_tenders(record_id) == 1
        after = read_rate_record(record_id)
        assert after["tender_count"] == 1
        assert float(after["acceptance_pct"]) == 100.00
        assert float(after["rejection_pct"]) == 0.00
        assert after["status"] == "LIVE"


class TestUnfitCarriersAreBlockedByTheirOwnReason:
    """One gate, three identifiers, and no debit taken by any of the refusals."""

    def test_a_suspension_blocks_the_approval_and_reinstatement_unblocks_it(self):
        """`ERR_CARRIER_SUSPENDED` while frozen, then 200 once reinstated.

        PRD §2.10: "A carrier whose `status` is `SUSPENDED` or `DISQUALIFIED` is
        rejected with `ERR_CARRIER_SUSPENDED`."
        PRD §3.1: "**Suspension.** A carrier whose `status` is `REGISTERED`,
        `SCREENING`, `QUALIFIED`, `WATCHLIST` or `CONDITIONALLY_QUALIFIED` may be moved
        to `SUSPENDED`. Suspension is a commercial freeze rather than a termination: it
        blocks every new binding described in §2.10 while leaving existing rows intact."
        PRD §3.1: "**Reinstatement.** A carrier whose `status` is `SUSPENDED` may be
        moved to `QUALIFIED`, but only when its `insurance_expiry_date` is strictly
        after the logical clock — a carrier cannot be reinstated on a lapsed
        certificate. Reinstatement sets `qualified_at` to the clock."
        PRD §2.12: "A `PROPOSED` allocation reserves nothing at all: the debit against
        `unallocated_volume_loads` is taken when the allocation is approved and credited
        back exactly when it is rejected or superseded."

        Design: Corner/errors/unfit_carriers_are_blocked_by_the_specific_fitness_reason
        """
        ctx = setup_published_routing_guide()
        allocation_id = ctx["allocation"]["id"]
        planned_loads = ctx["lane"]["annual_volume_loads"]
        assert ctx["allocation"]["status"] == "PROPOSED"
        assert read_lane(ctx["lane"]["id"])["unallocated_volume_loads"] == planned_loads

        frozen = _set_carrier_status(
            ctx["carrier"]["id"], "SUSPENDED", "Federal authority under review"
        )
        assert frozen["status"] == "SUSPENDED"

        validate_error(_approve(allocation_id), "ERR_CARRIER_SUSPENDED", 409)
        assert read_allocation(allocation_id)["status"] == "PROPOSED"
        assert read_lane(ctx["lane"]["id"])["unallocated_volume_loads"] == planned_loads, (
            "a refused approval takes no debit against the lane"
        )

        reinstated = _set_carrier_status(
            ctx["carrier"]["id"], "QUALIFIED", "Authority restored"
        )
        assert reinstated["status"] == "QUALIFIED"
        assert_same_instant(reinstated["qualified_at"], DEFAULT_CLOCK, "qualified_at")

        approved = validate_success(_approve(allocation_id))
        assert approved["status"] == "APPROVED"

    def test_a_lapsed_certificate_answers_with_a_different_identifier(self):
        """The same carrier, the same allocation — only the clock has moved.

        PRD §2.10: "A carrier whose `insurance_expiry_date` is at or before the logical
        clock is rejected with `ERR_CARRIER_INSURANCE_EXPIRED` — note the strictness:
        the certificate must expire strictly after the current instant, so a certificate
        expiring exactly now is expired."
        PRD §3.7: "The carrier must be fit: its `status` must be `QUALIFIED` or
        `CONDITIONALLY_QUALIFIED`, and its `insurance_expiry_date` must be strictly
        after the logical clock — a carrier that was eligible when the scenario ran but
        has since been suspended, watchlisted into an ineligible position or allowed its
        certificate to lapse cannot be approved without re-running the scenario."

        Design: Corner/errors/unfit_carriers_are_blocked_by_the_specific_fitness_reason
        """
        ctx = setup_published_routing_guide()
        allocation_id = ctx["allocation"]["id"]
        carrier = read_carrier(ctx["carrier"]["id"])
        assert carrier["status"] == "QUALIFIED"
        assert_same_instant(
            carrier["insurance_expiry_date"], CARRIER_EXPIRY, "insurance_expiry_date"
        )

        set_clock(LAPSED_CLOCK)
        lapsed = _approve(allocation_id)
        validate_error(lapsed, "ERR_CARRIER_INSURANCE_EXPIRED", 409)
        assert lapsed.json()["data"]["error_id"] != "ERR_CARRIER_SUSPENDED", (
            "a lapsed certificate is not a suspension"
        )
        assert read_allocation(allocation_id)["status"] == "PROPOSED"

        set_clock(DEFAULT_CLOCK)
        approved = validate_success(_approve(allocation_id))
        assert approved["status"] == "APPROVED"
        assert_same_instant(approved["approved_at"], DEFAULT_CLOCK, "approved_at")

    def test_a_carrier_that_never_qualified_cannot_be_invited_at_all(self):
        """`REGISTERED` is a standing failure, not a suspension or a lapse.

        PRD §2.10: "A carrier that has not reached `QUALIFIED`,
        `CONDITIONALLY_QUALIFIED` or `WATCHLIST` standing where the operation requires
        standing is rejected with `ERR_CARRIER_NOT_QUALIFIED`."
        PRD §3.4: "The carrier must be fit in the sense of §2.10 — not suspended or
        disqualified, insurance not expired, and standing at `QUALIFIED`,
        `CONDITIONALLY_QUALIFIED` or `WATCHLIST`."
        PRD §3.4: "The event's `invited_carrier_count` is recomputed, and on the first
        invitation the event moves from `LANES_LOCKED` to `INVITING`."

        Design: Corner/errors/unfit_carriers_are_blocked_by_the_specific_fitness_reason
        """
        set_clock(DEFAULT_CLOCK)
        never_qualified = create_carrier()
        assert never_qualified["status"] == "REGISTERED"
        event, _lanes = create_event_with_locked_lanes()

        refusal = _invite(event["id"], never_qualified["id"])
        validate_error(refusal, "ERR_CARRIER_NOT_QUALIFIED", 409)
        assert refusal.json()["data"]["error_id"] != "ERR_CARRIER_SUSPENDED"

        blocked = read_event(event["id"])
        assert blocked["invited_carrier_count"] == 0
        assert blocked["status"] == "LANES_LOCKED", (
            "the refused invitation must not open the event for invitations"
        )

        fit = create_qualified_carrier(carrier_overrides=second_carrier_overrides())
        validate_success(_invite(event["id"], fit["id"]), 201)
        opened = read_event(event["id"])
        assert opened["invited_carrier_count"] == 1
        assert opened["status"] == "INVITING"

"""The five roles are peers, so no role is a superset of any other.

Every owner-exclusive write is attempted by a neighbouring role at the exact
moment the operation is legitimately available to its owner, so the only thing
that differs between the refusal and the success is the role header. The second
half covers the deliberately shared endpoints: tender logging is open to the
analyst and the contract admin but closed to the commercial roles, and the carrier
list and the single-carrier read carry different role sets on purpose.
"""

from test_helpers import (
    ANALYST,
    TEST_USERS,
    add_validated_lane,
    create_bid_event,
    CATEGORY_MANAGER,
    COMPLIANCE,
    CONTRACT_ADMIN,
    DEFAULT_CLOCK,
    api_client,
    approve_allocation,
    create_qualified_carrier,
    create_screened_review,
    decision_payload,
    get_success_data,
    make_analyst_headers,
    make_carrier_rep_headers,
    mini_bid_apply_payload,
    read_allocation,
    read_carrier,
    read_event,
    read_lane,
    read_rate_record,
    set_clock,
    setup_live_rate_record,
    setup_published_routing_guide,
    setup_staged_rate_record,
    setup_open_mini_bid,
    tender_event_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# A second opaque analyst identity: a different human, the same barred role.
OTHER_ANALYST = make_analyst_headers("pa-999")

# The fallback carrier-rep identity, for calls that are refused on the role alone.
UNOWNED_CARRIER_REP = TEST_USERS["carrier_rep_headers"]

SHARED_LOAD_REFERENCES = ("LD-SHARED-1", "LD-SHARED-2")
REFUSED_LOAD_REFERENCE = "LD-SHARED-3"
CARRIER_LIST_LIMIT = 5


def _lock_lanes(event_id, headers):
    return api_client.lock_lanes(event_id, headers)


def _decide(review_id, headers):
    return api_client.decide_qualification_review(
        review_id, decision_payload(outcome="APPROVE"), headers
    )


def _approve(allocation_id, headers):
    return api_client.approve_award_allocation(allocation_id, headers)


def _load(rate_record_id, headers):
    return api_client.load_rate_record(rate_record_id, headers)


def _award(event_id, headers):
    return api_client.award_bid_event(event_id, headers)


def _apply_mini_bid(mini_bid_id, contract_version, headers):
    return api_client.apply_mini_bid(
        mini_bid_id, mini_bid_apply_payload(contract_version), headers
    )


def _append_tender(rate_record_id, load_reference, headers):
    return api_client.create_tender_event(
        rate_record_id, tender_event_payload(load_reference), headers
    )


def _list_tender_log(rate_record_id, headers):
    body = get_success_data(api_client.list_tender_events(rate_record_id, headers))
    return body["data"] if isinstance(body, dict) and "data" in body else body


def _draft_event_with_a_validated_lane():
    """An event whose lane scope is ready to be locked by its owner."""
    set_clock(DEFAULT_CLOCK)
    event = create_bid_event()
    lane = add_validated_lane(event["id"])
    return event, lane


class TestOwnerExclusiveWritesRejectEveryOtherRole:
    """Each write is attempted at the moment its owner could legitimately make it."""

    def test_scope_and_qualification_writes_are_closed_to_the_commercial_roles(self):
        """The category manager may award, but may neither freeze scope nor qualify.

        PRD §2.1: "If the headers are well formed but the acting role is not among the
        roles authorised for the endpoint being called, the rejection is
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.2: "**Role authorisation.** The acting role appears in the endpoint's
        authorised list, otherwise `ERR_FORBIDDEN_ROLE` (403). This applies to every
        endpoint."
        PRD §1: "Procurement analysts build events but never award them; compliance
        officers qualify carriers but never price lanes"

        Design: Corner/rbac/each_role_exclusive_operation_is_closed_to_the_other_four_roles
        """
        event, lane = _draft_event_with_a_validated_lane()
        before = read_event(event["id"])

        validate_error(
            _lock_lanes(event["id"], CATEGORY_MANAGER), "ERR_FORBIDDEN_ROLE", 403
        )
        refused = read_event(event["id"])
        assert refused["status"] == "DRAFT"
        assert refused["version"] == before["version"]
        assert read_lane(lane["id"])["status"] == "VALIDATED"

        locked = validate_success(_lock_lanes(event["id"], ANALYST))
        assert locked["status"] == "LANES_LOCKED"

        carrier, review = create_screened_review()
        assert review["status"] == "SCREENED"
        validate_error(_decide(review["id"], CATEGORY_MANAGER), "ERR_FORBIDDEN_ROLE", 403)
        assert read_carrier(carrier["id"])["status"] == "SCREENING", (
            "the refused decision must not qualify the carrier"
        )

        decided = validate_success(_decide(review["id"], COMPLIANCE))
        assert decided["status"] == "APPROVED"
        assert read_carrier(carrier["id"])["status"] == "QUALIFIED"

    def test_the_award_writes_are_closed_to_the_analyst_and_the_contract_admin(self):
        """The analyst who built the event still cannot approve or award it.

        PRD §2.1: "The system recognises exactly five roles, spelled precisely as
        follows: `ProcurementAnalyst`, `ComplianceOfficer`, `CategoryManager`,
        `ContractAdmin`, and `CarrierRep`."
        PRD §3.7: "**Approving an allocation.** The category manager approves an
        allocation whose `status` is `PROPOSED`; an attempt against any other status is
        rejected with `ERR_ALLOCATION_NOT_PROPOSED` (409)."
        PRD §2.12: "A `PROPOSED` allocation reserves nothing at all: the debit against
        `unallocated_volume_loads` is taken when the allocation is approved and credited
        back exactly when it is rejected or superseded."

        Design: Corner/rbac/each_role_exclusive_operation_is_closed_to_the_other_four_roles
        """
        ctx = setup_published_routing_guide()
        allocation_id = ctx["allocation"]["id"]
        planned_loads = read_lane(ctx["lane"]["id"])["unallocated_volume_loads"]

        for headers in (ANALYST, OTHER_ANALYST, CONTRACT_ADMIN, UNOWNED_CARRIER_REP):
            validate_error(_approve(allocation_id, headers), "ERR_FORBIDDEN_ROLE", 403)
        assert read_allocation(allocation_id)["status"] == "PROPOSED"
        assert read_lane(ctx["lane"]["id"])["unallocated_volume_loads"] == planned_loads

        assert approve_allocation(allocation_id)["status"] == "APPROVED"

        validate_error(
            _award(ctx["event"]["id"], CONTRACT_ADMIN), "ERR_FORBIDDEN_ROLE", 403
        )
        assert read_event(ctx["event"]["id"])["status"] == "AWARDING"

        awarded = validate_success(_award(ctx["event"]["id"], CATEGORY_MANAGER))
        assert awarded["status"] == "AWARDED"

    def test_loading_a_rate_is_closed_to_the_category_manager_that_awarded_it(self):
        """The commercial role stops at the award; the rate desk owns the load.

        PRD §3.8: "**Loading a rate.** A contract administrator loads a rate record
        whose `status` is `STAGED`; against any other status the attempt is rejected with
        `ERR_RATE_RECORD_NOT_LOADED` (409)."
        PRD §2.2: "**Role authorisation.** The acting role appears in the endpoint's
        authorised list, otherwise `ERR_FORBIDDEN_ROLE` (403). This applies to every
        endpoint."

        Design: Corner/rbac/each_role_exclusive_operation_is_closed_to_the_other_four_roles
        """
        ctx = setup_staged_rate_record()
        record_id = ctx["rate_record"]["id"]
        assert ctx["rate_record"]["status"] == "STAGED"

        for headers in (CATEGORY_MANAGER, COMPLIANCE, UNOWNED_CARRIER_REP):
            validate_error(_load(record_id, headers), "ERR_FORBIDDEN_ROLE", 403)
        assert read_rate_record(record_id)["status"] == "STAGED"
        assert read_rate_record(record_id)["loaded_at"] is None

        loaded = validate_success(_load(record_id, CONTRACT_ADMIN))
        assert loaded["status"] == "LOADED"

    def test_applying_a_mini_bid_is_closed_to_the_carrier_that_proposed_it(self):
        """The carrier may propose a rate but may never apply it to the contract.

        PRD §3.10: "**Applying a mini-bid.** A contract administrator applies a mini-bid
        whose `status` is `OPEN`; against any other status the attempt is rejected with
        `ERR_MINI_BID_NOT_OPEN` (409)."
        PRD §2.1: "`CarrierRep` is different: it is **entity-backed**. When
        `X-User-Role` is `CarrierRep`, `X-User-ID` is the `id` of the acting `Carrier`"

        Design: Corner/rbac/each_role_exclusive_operation_is_closed_to_the_other_four_roles
        """
        ctx = setup_open_mini_bid()
        mini_bid_id = ctx["mini_bid"]["id"]
        contract_version = ctx["contract"]["version"]

        validate_error(
            _apply_mini_bid(
                mini_bid_id,
                contract_version,
                make_carrier_rep_headers(ctx["carrier"]["id"]),
            ),
            "ERR_FORBIDDEN_ROLE",
            403,
        )
        validate_error(
            _apply_mini_bid(mini_bid_id, contract_version, CATEGORY_MANAGER),
            "ERR_FORBIDDEN_ROLE",
            403,
        )
        targeted = read_rate_record(ctx["rate_record"]["id"])
        assert targeted["status"] == "LIVE"

        applied = validate_success(
            _apply_mini_bid(mini_bid_id, contract_version, CONTRACT_ADMIN)
        )
        assert applied["status"] == "APPLIED"


class TestSharedOperationsAdmitExactlyTheirListedRoles:
    """Shared does not mean open: the list on the endpoint is exhaustive."""

    def test_tender_logging_is_shared_by_the_analyst_and_the_contract_admin(self):
        """Two roles append, the commercial role cannot, and all four may read.

        PRD §3.9: "`acceptance_pct` is `100.00` minus `rejection_pct`, rounded to 2
        decimal places, so the two always sum to exactly `100.00`."
        PRD §2.2: "**Role authorisation.** The acting role appears in the endpoint's
        authorised list, otherwise `ERR_FORBIDDEN_ROLE` (403). This applies to every
        endpoint."
        PRD §2.12: "`RateRecord.tender_count` counts every tender event on the record
        regardless of outcome."

        Design: Corner/rbac/shared_operations_work_for_every_listed_role_and_only_those
        """
        ctx = setup_live_rate_record()
        record_id = ctx["rate_record"]["id"]
        assert ctx["rate_record"]["tender_count"] == 0

        validate_success(
            _append_tender(record_id, SHARED_LOAD_REFERENCES[0], ANALYST), 201
        )
        validate_success(
            _append_tender(record_id, SHARED_LOAD_REFERENCES[1], CONTRACT_ADMIN), 201
        )
        validate_error(
            _append_tender(record_id, REFUSED_LOAD_REFERENCE, CATEGORY_MANAGER),
            "ERR_FORBIDDEN_ROLE",
            403,
        )

        logged = read_rate_record(record_id)
        assert logged["tender_count"] == 2, "the refused append leaves nothing behind"
        assert float(logged["acceptance_pct"]) == 100.00

        rep_headers = make_carrier_rep_headers(ctx["carrier"]["id"])
        for headers in (ANALYST, CATEGORY_MANAGER, CONTRACT_ADMIN, rep_headers):
            log = _list_tender_log(record_id, headers)
            assert [row["load_reference"] for row in log] == list(
                SHARED_LOAD_REFERENCES
            ), "the tender log is readable by every listed role"

    def test_the_carrier_list_and_the_single_carrier_read_differ_by_one_role(self):
        """A carrier may read itself but may not browse the carrier base.

        PRD §2.1: "Every request other than the logical-clock endpoint must present two
        headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`,
        declaring the capacity in which it acts."
        PRD §2.4: "Carriers may be filtered by `status` and by
        `diversity_classification`, and are ordered by `created_at` ascending."
        PRD §2.2: "**Role authorisation.** The acting role appears in the endpoint's
        authorised list, otherwise `ERR_FORBIDDEN_ROLE` (403). This applies to every
        endpoint."

        Design: Corner/rbac/shared_operations_work_for_every_listed_role_and_only_those
        """
        set_clock(DEFAULT_CLOCK)
        carrier = create_qualified_carrier()
        rep_headers = make_carrier_rep_headers(carrier["id"])

        validate_error(
            api_client.list_carriers(rep_headers, {"limit": CARRIER_LIST_LIMIT}),
            "ERR_FORBIDDEN_ROLE",
            403,
        )
        for headers in (ANALYST, COMPLIANCE, CATEGORY_MANAGER, CONTRACT_ADMIN):
            rows, meta = validate_paginated(
                api_client.list_carriers(headers, {"limit": CARRIER_LIST_LIMIT})
            )
            assert meta["limit"] == CARRIER_LIST_LIMIT
            assert carrier["id"] in [row["id"] for row in rows]

        own = validate_success(api_client.get_carrier(carrier["id"], rep_headers))
        assert own["id"] == carrier["id"], (
            "the single read lists CarrierRep even though the collection does not"
        )

        # The logical clock is the one endpoint every role may call, including the rep.
        validate_success(api_client.set_clock(DEFAULT_CLOCK, rep_headers))
        assert float(read_carrier(carrier["id"])["composite_score"]) > 0.00

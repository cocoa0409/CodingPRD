"""Endpoints: the read surface, the action endpoints, and one bulk call that applies partially."""
from test_helpers import (
    ADMIN_HEADERS,
    APPROVER_HEADERS,
    CLOCK_PLUS_180,
    CLOCK_PLUS_181,
    DEFAULT_CLOCK,
    ApiErrorId,
    api_client,
    assert_pct,
    assert_sweep_report,
    attest_readiness,
    create_eligible_carrier,
    create_licensed_carrier,
    create_port_request_payload,
    create_submitted_filing,
    list_orders,
    load_block,
    load_held_blocks,
    load_pool_blocks,
    make_carrier_representative_headers,
    publish_routing_record,
    read_block,
    read_carrier,
    read_npa,
    register_carrier,
    run_sweep,
    set_clock,
    setup_npa_with_rate_center,
    validate_error,
    validate_paginated,
    validate_success,
)

LATE_LOAD_CLOCK = "2026-09-01T00:00:00Z"
LATE_LOAD_DEADLINE = "2027-02-28T00:00:00Z"
VERIFY_NOTE = "CLLI verified against the LERG and interconnection trunks tested"
PORTED_NUMBER = "6145583000"
PORT_DESIRED_DUE_AT = "2026-09-01T00:00:00Z"


class TestTheCarrierSurfaceIsCreateReadAndListOnly:
    """The same row is reachable by id and through an OCN filter."""

    def test_the_filtered_listing_and_the_single_read_agree_field_for_field(self):
        """Two carriers are on file, the filter returns exactly one of them, and the excluded
        row is still readable by id.

        `total_count` giving the number of rows matching the filter before pagination was applied, and `has_more` indicating whether any further rows exist beyond this page

        Carrier listings can be narrowed by `ocn`, by `license_status`, by `eligibility_status` and by `home_state_code`.

        A freshly registered carrier has `license_status` of `NONE`, `facilities_readiness_status` of `NOT_SUBMITTED`

        Design: Corner/endpoints/carrier_create_read_and_filtered_list_round_trip
        """
        set_clock()
        acme = register_carrier("A")
        buckeye = register_carrier("B")

        rows, meta = validate_paginated(
            api_client.list_carriers(APPROVER_HEADERS, params={"ocn": "1234"})
        )

        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(rows) == 1
        listed = rows[0]
        assert listed["id"] == acme["id"]

        read_back = read_carrier(acme["id"])
        for field in ("legal_name", "carrier_type", "license_status",
                      "eligibility_status", "blocks_held_count", "version"):
            assert listed[field] == read_back[field], field
        assert read_back["legal_name"] == "Acme Telecom LLC"
        assert read_back["carrier_type"] == "CLEC"
        assert read_back["license_status"] == "NONE"
        assert read_back["eligibility_status"] == "INELIGIBLE"
        assert read_back["blocks_held_count"] == 0
        assert read_back["version"] == 1

        # Buckeye is filtered out of the listing yet still addressable by id.
        assert buckeye["id"] not in [row["id"] for row in rows]
        assert read_carrier(buckeye["id"])["ocn"] == "5678"


class TestTheReadinessEndpointRecomputesEligibility:
    """One event on the facilities axis flips the derived eligibility."""

    def test_verify_turns_an_ineligible_licensed_carrier_eligible(self):
        """Attestation alone left the carrier ineligible; the verification that follows is
        what makes it eligible, and it never touches the licence.

        `ATTEST` sets `facilities_readiness_status` to `ATTESTED`, copies `switch_clli` and `interconnection_ready` from the payload

        `VERIFY` moves `ATTESTED → VERIFIED`, and is accepted only when `interconnection_ready` reads true; it recomputes `eligibility_status`, which becomes `ELIGIBLE` when the licensing axis reads `GRANTED` and the licence has not expired

        An endpoint that brings a new resource into existence answers with 201; every endpoint that modifies, transitions or reads an existing resource answers with 200, including the action endpoints that drive a state machine and the sweep endpoint that returns a summary rather than a resource.

        Design: Corner/endpoints/readiness_event_action_endpoint_recomputes_eligibility
        """
        set_clock()
        carrier = create_licensed_carrier("A")
        attested = attest_readiness(carrier)
        assert attested["facilities_readiness_status"] == "ATTESTED"
        assert attested["eligibility_status"] == "INELIGIBLE"

        verified = validate_success(
            api_client.create_readiness_event(
                carrier["id"], {"event": "VERIFY", "note": VERIFY_NOTE}, ADMIN_HEADERS
            ),
            200,
        )

        assert verified["facilities_readiness_status"] == "VERIFIED"
        assert verified["eligibility_status"] == "ELIGIBLE"
        assert verified["switch_clli"] == "CLMBOH01DS0"
        assert verified["interconnection_ready"] is True
        assert verified["license_status"] == "GRANTED"


class TestOneSweepAppliesToTheDueBlocksOnly:
    """Three reserved blocks, two of them overdue, and one call that sorts them out."""

    def test_the_sweep_reclaims_the_two_overdue_blocks_and_leaves_the_third(self):
        """The third block was loaded a month later, so its own deadline is still a month
        away, and the bulk call reclaims around it instead of failing.

        The response reports `orders_issued`, `blocks_released` and `routing_activated` as counts of what each pass did, plus `swept_at` recording the instant the sweep ran.

        Because each pass filters on a different status, a block can be touched by at most one pass in a single sweep.

        a sweep run at exactly `2027-01-28T00:00:00Z` does not reclaim it, and a sweep run at `2027-01-29T00:00:00Z` does

        Design: Corner/endpoints/reclamation_sweep_processes_every_due_block_and_skips_the_rest
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa, rate_center = setup_npa_with_rate_center()
        early = load_held_blocks(
            npa, rate_center, carrier, 2, nxx_code="554", mark_activated=False
        )
        assert [block["activation_due_at"] for block in early] == [CLOCK_PLUS_180] * 2

        set_clock(LATE_LOAD_CLOCK)
        late = load_block(
            npa, rate_center, nxx_code="554", thousands_digit=2,
            holder_carrier_id=carrier["id"],
        )
        assert late["activation_due_at"] == LATE_LOAD_DEADLINE

        set_clock(CLOCK_PLUS_181)
        sweep = run_sweep(rate_center_id=rate_center["id"])

        assert_sweep_report(sweep, 2, 0, 0, CLOCK_PLUS_181)
        for block in early:
            assert read_block(block["id"])["allocation_status"] == "RECLAMATION_PENDING"

        untouched = read_block(late["id"])
        assert untouched["allocation_status"] == "RESERVED"
        assert untouched["activation_due_at"] == LATE_LOAD_DEADLINE

        orders = list_orders(carrier_id=carrier["id"])
        assert len(orders) == 2
        assert {order["reason"] for order in orders} == {"ACTIVATION_DEADLINE_MISSED"}
        assert {order["number_block_id"] for order in orders} == {
            early[0]["id"], early[1]["id"]
        }


class TestAPortRequestLinksOneBlockToTwoCarriers:
    """Three referents must exist and agree before the link stands up."""

    def test_the_new_request_is_reachable_through_each_of_its_three_keys(self):
        """The gaining carrier files it, the losing carrier is the block's actual holder, and
        the block itself is left exactly as it was.

        so on creation the acting `CarrierRepresentative`'s `X-User-ID` must equal `to_carrier_id`

        A new request opens at `status` `SUBMITTED` with `concurred_at`, `activated_at`, `closed_at`, `reject_reason`, `npac_db_version_at_activation` and `supersedes_port_request_id` all null, and no routing data is written until activation.

        Port listings can be narrowed by `number_block_id`, `from_carrier_id`, `to_carrier_id`, `supersedes_port_request_id` and `status`.

        Design: Corner/endpoints/port_request_links_one_block_to_two_carriers
        """
        set_clock()
        losing = create_eligible_carrier("A")
        gaining = create_eligible_carrier("B")
        npa, rate_center = setup_npa_with_rate_center()
        block = load_block(
            npa, rate_center, nxx_code="558", thousands_digit=3,
            holder_carrier_id=losing["id"], mark_activated=True,
        )
        publish_routing_record(block, lrn="6145580000", effective_at=DEFAULT_CLOCK)
        assert read_block(block["id"])["routing_status"] == "LERG_PUBLISHED"

        port_request = validate_success(
            api_client.create_port_request(
                create_port_request_payload(
                    PORTED_NUMBER, block["id"], losing["id"], gaining["id"],
                    requested_lrn="6145570000", desired_due_at=PORT_DESIRED_DUE_AT,
                ),
                make_carrier_representative_headers(gaining["id"]),
            ),
            201,
        )

        assert port_request["status"] == "SUBMITTED"
        assert port_request["number_block_id"] == block["id"]
        assert port_request["from_carrier_id"] == losing["id"]
        assert port_request["to_carrier_id"] == gaining["id"]
        assert port_request["supersedes_port_request_id"] is None
        assert port_request["concurred_at"] is None

        for key, value in (("number_block_id", block["id"]),
                           ("from_carrier_id", losing["id"]),
                           ("to_carrier_id", gaining["id"])):
            rows, meta = validate_paginated(
                api_client.list_port_requests(ADMIN_HEADERS, params={key: value})
            )
            assert meta["total_count"] == 1, key
            assert rows[0]["id"] == port_request["id"], key

        unchanged = read_block(block["id"])
        assert unchanged["routing_status"] == "LERG_PUBLISHED"
        assert unchanged["current_lrn"] == "6145580000"
        assert unchanged["npac_db_version"] == 1


class TestOneRateCenterReadReconcilesFourDerivedNumbers:
    """Two counters from the inventory, one from a filing, one from the area code's posture."""

    def test_the_read_reports_three_available_two_assigned_and_the_pooled_percentage(self):
        """The five blocks split three to two, the holder's own filing pools to 68.89, and the
        code has slipped into jeopardy at three available blocks.

        a rate center's `available_block_count` is the number of its blocks in `POOL_AVAILABLE` and its `assigned_block_count` is the number of its blocks in `RESERVED`, `ASSIGNED` or `RECLAMATION_PENDING`

        For each carrier holding at least one `RESERVED` or `ASSIGNED` block in the rate center, take that carrier's effective filing — one filing per holder — and accumulate two running totals

        A code with at most four available blocks becomes `JEOPARDY` — the comparison is inclusive, so exactly four available blocks is `JEOPARDY` while five is not.

        Design: Corner/endpoints/rate_center_read_exposes_every_derived_counter
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa, rate_center = setup_npa_with_rate_center()
        load_pool_blocks(npa, rate_center, 3, nxx_code="554")
        load_held_blocks(
            npa, rate_center, carrier, 2, nxx_code="554", first_thousands_digit=3,
            mark_activated=True,
        )
        create_submitted_filing(
            carrier, rate_center,
            numbers_assigned=2500, numbers_intermediate=400, numbers_reserved=200,
            numbers_aging=200, numbers_administrative=300,
            blocks_held_at_period_end=5, forecast_quarters=[1800, 1800, 1800, 1800],
        )

        reported = validate_success(
            api_client.get_rate_center(rate_center["id"], APPROVER_HEADERS), 200
        )

        assert reported["available_block_count"] == 3
        assert reported["assigned_block_count"] == 2
        assert_pct(reported["aggregate_utilization_pct"], 68.89, "aggregate_utilization_pct")
        assert reported["jeopardy_flag"] is True
        assert reported["accepts_initial_requests"] is False
        assert reported["pooling_status"] == "NON_POOLED"
        assert reported["pending_request_count"] == 0
        assert reported["last_donation_block_count"] == 0
        assert read_npa(npa["id"])["status"] == "JEOPARDY"


class TestTheActivationConfirmationIsConditionalOnItsWindow:
    """One day past the deadline the same call that would have worked is refused."""

    def test_a_confirmation_after_the_deadline_is_refused_and_issues_no_order(self):
        """No sweep has run, so nothing has reclaimed the block; the window alone closes the
        confirmation off.

        The block's `allocation_status` must be `RESERVED`, and the logical clock must be at or before `activation_due_at`; a confirmation that arrives after the deadline is refused with `ERR_ACTIVATION_WINDOW_EXPIRED`.

        Pass one issues reclamation orders, for two distinct reasons.

        Design: Corner/endpoints/activation_confirmation_is_conditional_on_the_open_window
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa, rate_center = setup_npa_with_rate_center()
        block = load_held_blocks(
            npa, rate_center, carrier, 1, nxx_code="554", mark_activated=False
        )[0]
        assert block["allocation_status"] == "RESERVED"
        assert block["activation_due_at"] == CLOCK_PLUS_180

        set_clock(CLOCK_PLUS_181)
        validate_error(
            api_client.create_activation_confirmation(
                block["id"], {"activated_number_count": 40},
                make_carrier_representative_headers(carrier["id"]),
            ),
            ApiErrorId.ERR_ACTIVATION_WINDOW_EXPIRED,
            409,
        )

        stalled = read_block(block["id"])
        assert stalled["allocation_status"] == "RESERVED"
        assert stalled["activated_at"] is None
        assert stalled["activation_due_at"] == CLOCK_PLUS_180

        # The expiry alone issues nothing: only a sweep writes a reclamation order.
        assert list_orders(number_block_id=block["id"]) == []

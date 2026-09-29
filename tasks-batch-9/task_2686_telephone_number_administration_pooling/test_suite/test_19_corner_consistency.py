"""Consistency: every derived figure two and three entities away is settled inside the write."""
from test_helpers import (
    ADMIN_HEADERS,
    APPROVER_HEADERS,
    APPROVER_USER_ID,
    CLOCK_PLUS_180,
    DEFAULT_CLOCK,
    api_client,
    assert_pct,
    create_block_payload,
    create_eligible_carrier,
    create_filing,
    create_npa,
    create_rate_center,
    create_submitted_filing,
    file_allocation_request,
    load_held_blocks,
    load_pool_blocks,
    make_carrier_representative_headers,
    open_audit_finding,
    read_carrier,
    read_filing,
    read_npa,
    read_rate_center,
    read_request,
    set_clock,
    setup_npa_with_rate_center,
    validate_paginated,
    validate_success,
)

SIBLING_NAME = "DUBLIN"
DISPOSITION_NOTE = "finding stands"

# 1200 assigned and 100 intermediate over two blocks: a claimed 65.00 against a
# strict 60.00, both drawn from the one row.
DIVERGING_PERIOD = dict(
    numbers_assigned=1200,
    numbers_intermediate=100,
    numbers_reserved=0,
    numbers_aging=0,
    numbers_administrative=0,
    blocks_held_at_period_end=2,
    forecast_quarters=[3000, 3000, 0, 0],
)

# 1600 assigned over two blocks claims 80.00; the auditor's 1500 reads 75.00.
OVERSTATED_PERIOD = dict(
    numbers_assigned=1600,
    numbers_intermediate=0,
    numbers_reserved=0,
    numbers_aging=0,
    numbers_administrative=0,
    blocks_held_at_period_end=2,
    forecast_quarters=[3000, 3000, 0, 0],
)


class TestOneSubmissionSettlesBothTheFilingAndItsRateCenter:
    """Two percentages on the row and a third one level up, all in the one call."""

    def test_the_submission_response_and_the_reads_after_it_agree_exactly(self):
        """The write's own body already carries the two divergent percentages, and the parent's
        pooled figure is there on the very next read with nothing asked to refresh it.

        Submission stamps `submitted_at` at the current logical clock, recomputes both `claimed_utilization_pct` and `strict_utilization_pct`, recomputes the rate center's `aggregate_utilization_pct` from the newly effective filing, and increments the filing's `version` and the rate center's `version` by 1 each.

        Both share one denominator: take `blocks_held_at_period_end`, multiply by the one thousand numbers in a block, then subtract `numbers_administrative` and subtract `numbers_aging`, because administrative and aging numbers are not assignable inventory.

        stored in `claimed_utilization_pct`, takes as its numerator the sum of `numbers_assigned`, `numbers_intermediate` and `numbers_reserved`

        stored in `strict_utilization_pct`, takes `numbers_assigned` alone as its numerator, excluding intermediate and reserved numbers

        add `numbers_assigned` plus `numbers_intermediate` plus `numbers_reserved` to the pooled numerator, and add that filing's `blocks_held_at_period_end` multiplied by one thousand, less its `numbers_administrative` and less its `numbers_aging`, to the pooled denominator

        The field stays null while no carrier has an effective filing for the rate center at all.

        A newly created filing sits at `DRAFT` with `submitted_at` null, `amendment_count` at 0 and `audited_utilization_pct` null.

        Filing listings can be narrowed by `carrier_id`, `rate_center_id`, `reporting_period` and `status`.

        Design: Corner/consistency model/filing_submission_recomputes_the_rate_center_aggregate_in_the_same_write
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa, rate_center = setup_npa_with_rate_center()
        load_held_blocks(
            npa, rate_center, carrier, 2, nxx_code="554", mark_activated=True
        )
        draft = create_filing(carrier, rate_center, **DIVERGING_PERIOD)
        assert draft["status"] == "DRAFT"
        assert read_rate_center(rate_center["id"])["aggregate_utilization_pct"] is None

        submitted = validate_success(
            api_client.create_filing_submission(
                draft["id"], {}, make_carrier_representative_headers(carrier["id"])
            ),
            200,
        )

        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_at"] == DEFAULT_CLOCK
        assert_pct(submitted["claimed_utilization_pct"], 65.00, "claimed_utilization_pct")
        assert_pct(submitted["strict_utilization_pct"], 60.00, "strict_utilization_pct")
        assert submitted["audited_utilization_pct"] is None

        settled = read_rate_center(rate_center["id"])
        assert_pct(
            settled["aggregate_utilization_pct"], 65.00, "aggregate_utilization_pct"
        )
        assert settled["assigned_block_count"] == 2
        assert settled["available_block_count"] == 0

        # The read of the filing itself reports the same figures the write returned.
        read_back = read_filing(draft["id"])
        for field in ("status", "submitted_at", "claimed_utilization_pct",
                      "strict_utilization_pct", "audited_utilization_pct"):
            assert read_back[field] == submitted[field], field

        _rows, meta = validate_paginated(
            api_client.list_utilization_filings(
                ADMIN_HEADERS,
                params={"carrier_id": carrier["id"], "status": "SUBMITTED"},
            )
        )
        assert meta["total_count"] == 1


class TestOneDispositionSettlesFourEntities:
    """The finding, its filing, the carrier and the carrier's open request, in one call."""

    def test_the_acceptance_reaches_the_open_request_without_moving_the_queue(self):
        """The penalty is computed rather than supplied, and the request it pushes back to the
        carrier is still an open one, so the rate center's queue count must not move.

        Either way, `disposed_by_user_id` is set to the acting `X-User-ID`, the finding's `status` becomes `ACCEPTED` or `REJECTED`, and the finding's `version` increments by 1.

        Its `adjusted_utilization_pct` is the strict assigned-only basis recomputed over the adjusted inputs

        A difference of 20.00 points or more yields `RECLAMATION_REFERRAL`, a difference of 5.00 points or more yields `PROBATION`, and anything smaller yields `NONE`.

        Accepting a finding whose `penalty_action` is anything other than `NONE` moves the filing `UNDER_AUDIT → REJECTED` and stamps `audited_utilization_pct` with the finding's `adjusted_utilization_pct`, and then cascades into the carrier.

        In both penalty cases `probation_until` is stamped 180 days after the current logical clock, which makes the carrier's computed `eligibility_status` read `PROBATION`

        Because the carrier has entered probation, a second cascade step follows: every allocation request of that carrier sitting in `PENDING_REVIEW` whose `request_type` is `GROWTH` or `POOL_REPLENISH` moves to `INFO_REQUESTED` with `info_request_count` incremented by 1, walked in `created_at` ascending order

        That system-driven push consumes one of the two cycles exactly as an operator's request would, but it leaves `reviewer_user_id` untouched

        Completion requires that no allocation request for the rate center is sitting in `PENDING_REVIEW` or `INFO_REQUESTED`, which is exactly the condition that `pending_request_count` is zero; an administrator who tries to complete pooling over an open queue is refused with `ERR_INVALID_STATE_TRANSITION`.

        Design: Corner/consistency model/audit_acceptance_settles_filing_carrier_and_request_in_one_response
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa, rate_center = setup_npa_with_rate_center()
        load_pool_blocks(npa, rate_center, 5, nxx_code="554")
        filing = create_submitted_filing(carrier, rate_center, **OVERSTATED_PERIOD)
        assert_pct(filing["claimed_utilization_pct"], 80.00, "claimed_utilization_pct")
        request = file_allocation_request(
            carrier, rate_center, request_type="GROWTH", requested_block_count=1,
            justification="growth filed before the audit lands",
        )
        assert request["info_request_count"] == 0
        assert read_rate_center(rate_center["id"])["pending_request_count"] == 1
        finding = open_audit_finding(
            filing, finding_type="OVERSTATED_UTILIZATION",
            adjusted_numbers_assigned=1500, adjusted_numbers_administrative=0,
        )

        disposed = validate_success(
            api_client.create_disposition(
                finding["id"],
                {"disposition": "ACCEPT", "disposition_note": DISPOSITION_NOTE},
                APPROVER_HEADERS,
            ),
            200,
        )

        assert disposed["status"] == "ACCEPTED"
        assert disposed["penalty_action"] == "PROBATION"
        assert_pct(disposed["adjusted_utilization_pct"], 75.00, "adjusted_utilization_pct")
        assert disposed["disposed_by_user_id"] == APPROVER_USER_ID

        rejected = read_filing(filing["id"])
        assert rejected["status"] == "REJECTED"
        assert_pct(rejected["audited_utilization_pct"], 75.00, "audited_utilization_pct")
        assert_pct(rejected["claimed_utilization_pct"], 80.00, "claimed_utilization_pct")

        penalised = read_carrier(carrier["id"])
        assert penalised["eligibility_status"] == "PROBATION"
        assert penalised["probation_until"] == CLOCK_PLUS_180
        assert penalised["reclamation_strike_count"] == 0

        pushed_back = read_request(request["id"])
        assert pushed_back["status"] == "INFO_REQUESTED"
        assert pushed_back["info_request_count"] == 1
        assert pushed_back["reviewer_user_id"] is None

        unmoved = read_rate_center(rate_center["id"])
        assert unmoved["pending_request_count"] == 1
        assert unmoved["available_block_count"] == 5


class TestTwoBlockLoadsRewriteThePostureTwoLevelsUp:
    """Nobody declares anything; the second load alone puts the code into jeopardy."""

    def test_the_loads_settle_both_rate_centers_and_the_area_code(self):
        """One available block is already inside the jeopardy band, and the sibling rate center
        that holds nothing is closed to initial demand on the very next read.

        A block loaded without a holder opens at `POOL_AVAILABLE` and `UNROUTED`, with `holder_carrier_id`, `assigned_at`, `activation_due_at`, `activated_at`, `aging_release_at` and `current_lrn` all null, and `npac_db_version` at 0.

        the block is then created already holding, with `holder_carrier_id` set, `assigned_at` stamped at the current logical clock, `activation_due_at` stamped 180 days later, and `allocation_status` at `RESERVED`

        Supplying the optional `mark_activated` as true carries the block one step further to `ASSIGNED` with `activated_at` also stamped at the current logical clock

        Every load recomputes the rate center's `available_block_count` and `assigned_block_count`, the area code's `available_block_count` and `total_block_count`, and — when a holder was named — the carrier's `blocks_held_count`, and then recomputes the area code's exhaust posture.

        Every change to any block's `allocation_status` anywhere inside an area code triggers a recomputation of that code's posture

        Moving `ACTIVE → JEOPARDY` — which happens when the available count lands strictly above zero and at or below four — sets `status` to `JEOPARDY`, stamps `jeopardy_declared_at` at the current logical clock, and cascades: every rate center under the code has `jeopardy_flag` set to true, which flips each one's computed `accepts_initial_requests` to false.

        A rate center's `accepts_initial_requests` is false whenever its `jeopardy_flag` is true or its `pooling_status` is `TRANSITIONAL`, and true otherwise.

        the platform computes `block_label` as the concatenation NPA-NXX-D, which must be unique across every block on file

        A block's `is_pooling_eligible` is true when its `contaminated_count` is at most 100

        Design: Corner/consistency model/block_load_recomputes_rate_center_and_npa_posture_before_responding
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa = create_npa(npa_type="GEOGRAPHIC")
        columbus = create_rate_center(npa)
        dublin = create_rate_center(npa, name=SIBLING_NAME)
        assert read_npa(npa["id"])["status"] == "ACTIVE"
        assert read_rate_center(dublin["id"])["accepts_initial_requests"] is True

        unheld = validate_success(
            api_client.create_block(
                create_block_payload(
                    npa["id"], columbus["id"], nxx_code="554", thousands_digit=0,
                    contaminated_count=0,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        held = validate_success(
            api_client.create_block(
                create_block_payload(
                    npa["id"], columbus["id"], nxx_code="554", thousands_digit=1,
                    contaminated_count=0, holder_carrier_id=carrier["id"],
                    mark_activated=True,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

        assert unheld["block_label"] == "614-554-0"
        assert unheld["allocation_status"] == "POOL_AVAILABLE"
        assert unheld["routing_status"] == "UNROUTED"
        assert unheld["is_pooling_eligible"] is True
        assert unheld["holder_carrier_id"] is None

        assert held["allocation_status"] == "ASSIGNED"
        assert held["holder_carrier_id"] == carrier["id"]
        assert held["assigned_at"] == DEFAULT_CLOCK
        assert held["activation_due_at"] == CLOCK_PLUS_180
        assert held["activated_at"] == DEFAULT_CLOCK

        posture = read_npa(npa["id"])
        assert posture["total_block_count"] == 2
        assert posture["available_block_count"] == 1
        assert posture["status"] == "JEOPARDY"
        assert posture["jeopardy_declared_at"] == DEFAULT_CLOCK

        loaded = read_rate_center(columbus["id"])
        assert loaded["available_block_count"] == 1
        assert loaded["assigned_block_count"] == 1
        assert loaded["jeopardy_flag"] is True
        assert loaded["accepts_initial_requests"] is False

        # The sibling holds nothing and is closed all the same.
        empty_sibling = read_rate_center(dublin["id"])
        assert empty_sibling["available_block_count"] == 0
        assert empty_sibling["assigned_block_count"] == 0
        assert empty_sibling["jeopardy_flag"] is True
        assert empty_sibling["accepts_initial_requests"] is False

        assert read_carrier(carrier["id"])["blocks_held_count"] == 1

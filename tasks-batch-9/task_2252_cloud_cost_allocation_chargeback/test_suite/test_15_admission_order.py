"""Admission order: which of two applicable refusals the request actually earns."""

from test_helpers import (
    ANALYST_HEADERS,
    CONTROLLER_ALT_HEADERS,
    CONTROLLER_HEADERS,
    ApiErrorId,
    assert_allocation_line,
    assert_cents,
    assert_invoice_dimensions,
    factories,
    fixtures,
    find_by,
    make_business_unit_owner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    AUGUST_END,
    AUGUST_FIFTH_UTC,
    AUGUST_START,
    JULY_END,
    JULY_START,
    JUNE_START,
)

WRITE_OFF_MEMO = "Uncollectable: unit reorganised."
CLAIM_ABOVE_THE_GROSS = 99999


def _written_off_invoice(api):
    """An Ops BU invoice issued for 10000 cents and then written off in full."""
    fixtures.set_clock(api, AUGUST_FIFTH_UTC)
    built = fixtures.direct_chargeback_invoice(api)
    built["invoice"] = validate_success(
        api.write_off_invoice(built["invoice"]["id"], WRITE_OFF_MEMO, CONTROLLER_HEADERS)
    )
    assert_invoice_dimensions(
        built["invoice"], settlement_status="WRITTEN_OFF", dispute_status="NONE"
    )
    assert_cents(built["invoice"]["net_due_cents"], 0, "net_due_cents")
    return built


def test_a_written_off_invoice_is_undisputable_whatever_the_claim_is_worth(api):
    """An impossible claim and a modest one earn the same refusal on this invoice.

    PRD §3.7: "Filing is admissible only while the invoice's `settlement_status`
    is `ISSUED` or `PARTIALLY_CREDITED` and its `dispute_status` is `NONE`;
    otherwise the request is `ERR_INVOICE_NOT_DISPUTABLE` at HTTP 409."

    Design: Difficulty/priority_pair_validation_conflict/written_off_invoice_state_check_precedes_credit_ceiling_check
    """
    built = _written_off_invoice(api)
    owner = make_business_unit_owner_headers(built["unit"]["id"])

    oversized = api.create_dispute(
        factories.dispute_payload(
            built["invoice"]["id"],
            reason_code="SHARED_METHODOLOGY",
            claimed_credit_cents=CLAIM_ABOVE_THE_GROSS,
            narrative="not our storage",
        ),
        owner,
    )
    validate_error(oversized, ApiErrorId.INVOICE_NOT_DISPUTABLE.value, 409)

    modest = api.create_dispute(
        factories.dispute_payload(
            built["invoice"]["id"],
            reason_code="SHARED_METHODOLOGY",
            claimed_credit_cents=500,
            narrative="not our storage",
        ),
        owner,
    )
    validate_error(modest, ApiErrorId.INVOICE_NOT_DISPUTABLE.value, 409)

    _, disputes = validate_paginated(
        api.list_disputes(CONTROLLER_HEADERS, {"chargeback_invoice_id": built["invoice"]["id"]})
    )
    assert disputes["total_count"] == 0

    unchanged = validate_success(
        api.get_chargeback_invoice(built["invoice"]["id"], CONTROLLER_HEADERS)
    )
    assert_invoice_dimensions(unchanged, settlement_status="WRITTEN_OFF", dispute_status="NONE")
    assert unchanged["version"] == built["invoice"]["version"]


def test_the_credit_ceiling_is_only_reached_once_the_invoice_is_disputable(api):
    """The same 99999-cent claim earns 422 while issued and 409 once written off.

    PRD §2.10: "**Dispute filing admissibility**, immediately after generic state
    admissibility: an invoice is disputable only while its `settlement_status` is
    `ISSUED` or `PARTIALLY_CREDITED` and its `dispute_status` is `NONE`, else
    `ERR_INVOICE_NOT_DISPUTABLE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/written_off_invoice_state_check_precedes_credit_ceiling_check
    """
    fixtures.set_clock(api, AUGUST_FIFTH_UTC)
    built = fixtures.direct_chargeback_invoice(api)
    owner = make_business_unit_owner_headers(built["unit"]["id"])
    invoice_id = built["invoice"]["id"]

    def file_the_oversized_claim():
        return api.create_dispute(
            factories.dispute_payload(
                invoice_id,
                reason_code="SHARED_METHODOLOGY",
                claimed_credit_cents=CLAIM_ABOVE_THE_GROSS,
                narrative="not our storage",
            ),
            owner,
        )

    validate_error(file_the_oversized_claim(), ApiErrorId.CREDIT_EXCEEDS_INVOICE.value, 422)

    written_off = validate_success(
        api.write_off_invoice(invoice_id, WRITE_OFF_MEMO, CONTROLLER_HEADERS)
    )
    assert written_off["settlement_status"] == "WRITTEN_OFF"

    validate_error(file_the_oversized_claim(), ApiErrorId.INVOICE_NOT_DISPUTABLE.value, 409)

    _, disputes = validate_paginated(
        api.list_disputes(CONTROLLER_HEADERS, {"chargeback_invoice_id": invoice_id})
    )
    assert disputes["total_count"] == 0


def _run_opened_by_the_controller_with_an_open_pool(api):
    """A computed CHARGEBACK run whose author is controller-1 and whose pool is OPEN."""
    fixtures.set_clock(api, AUGUST_FIFTH_UTC)
    built = fixtures.direct_cost_unit(api)

    run = validate_success(
        api.create_allocation_run(
            factories.allocation_run_payload(mode="CHARGEBACK"), CONTROLLER_HEADERS
        ),
        201,
    )
    assert run["created_by_user_id"] == "controller-1"

    pool = fixtures.create_pool(
        api, run["id"], [built["unit"]["id"]], name="network-egress", methodology="EVEN_SPLIT"
    )
    assert pool["status"] == "OPEN"
    assert_cents(pool["pooled_cost_cents"], 0, "pooled_cost_cents")

    computed = fixtures.compute(api, run["id"], "FINAL")
    assert computed["status"] == "COMPUTED_FINAL"
    assert_cents(computed["total_allocated_cents"], 10000, "total_allocated_cents")
    assert computed["line_count"] == 2

    built.update({"run": computed, "pool": pool})
    return built


def test_the_author_of_a_run_is_refused_publication_before_the_pool_is_even_checked(api):
    """The controller who opened the run is stopped on duties, not on the open pool.

    PRD §3.6: "Moving `COMPUTED_FINAL → PUBLISHED` requires four things at once:
    `variant_applied` must be `FINAL`; the publishing user's `X-User-ID` must
    differ from the run's `created_by_user_id`, or the request fails with
    `ERR_SEGREGATION_OF_DUTIES`; every shared cost pool attached to the run must
    be `SEALED`, or the request fails with `ERR_POOL_NOT_SEALED` at HTTP 409;
    and, when the run's `mode` is `CHARGEBACK`, every business unit appearing on
    a line must have `chargeback_enabled` set to true, or the request fails with
    `ERR_BU_NOT_CHARGEBACK_ENABLED` at HTTP 422."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_precedes_unsealed_pool_check_on_publish
    """
    built = _run_opened_by_the_controller_with_an_open_pool(api)
    run_id = built["run"]["id"]

    self_publication = api.publish_allocation_run(run_id, CONTROLLER_HEADERS)
    validate_error(self_publication, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)

    unpublished = validate_success(api.get_allocation_run(run_id, CONTROLLER_HEADERS))
    assert unpublished["status"] == "COMPUTED_FINAL"
    assert unpublished["published_by_user_id"] is None

    _, invoices = validate_paginated(
        api.list_chargeback_invoices(CONTROLLER_HEADERS, {"allocation_run_id": run_id})
    )
    assert invoices["total_count"] == 0

    still_open = validate_success(api.get_shared_cost_pool(built["pool"]["id"], ANALYST_HEADERS))
    assert still_open["status"] == "OPEN"


def test_a_second_controller_then_earns_the_unsealed_pool_refusal(api):
    """With the duties satisfied, the pool gate fires — and sealing clears it.

    PRD §3.5: "Sealing moves a pool `OPEN → SEALED`, after which no further
    record may be absorbed, and increments the pool's `version`; absorbing into
    or re-sealing an already-`SEALED` pool is `ERR_POOL_STATE_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_precedes_unsealed_pool_check_on_publish
    """
    built = _run_opened_by_the_controller_with_an_open_pool(api)
    run_id = built["run"]["id"]

    validate_error(
        api.publish_allocation_run(run_id, CONTROLLER_HEADERS),
        ApiErrorId.SEGREGATION_OF_DUTIES.value,
        403,
    )
    validate_error(
        api.publish_allocation_run(run_id, CONTROLLER_ALT_HEADERS),
        ApiErrorId.POOL_NOT_SEALED.value,
        409,
    )

    blocked = validate_success(api.get_allocation_run(run_id, CONTROLLER_HEADERS))
    assert blocked["status"] == "COMPUTED_FINAL"
    assert blocked["published_by_user_id"] is None

    sealed = fixtures.seal(api, built["pool"]["id"])
    assert sealed["status"] == "SEALED"

    published = validate_success(api.publish_allocation_run(run_id, CONTROLLER_ALT_HEADERS))
    assert published["status"] == "PUBLISHED"
    assert published["published_by_user_id"] == "controller-2"

    lines, meta = validate_paginated(
        api.list_allocation_lines(ANALYST_HEADERS, {"allocation_run_id": run_id})
    )
    assert meta["total_count"] == 2
    assert_allocation_line(find_by(lines, line_kind="DIRECT"), "DIRECT", "EFFECTIVE_BASIS", 10000)
    assert_allocation_line(find_by(lines, line_kind="SHARED"), "SHARED", "EVEN_SPLIT", 0)

    invoices, invoice_meta = validate_paginated(
        api.list_chargeback_invoices(CONTROLLER_HEADERS, {"allocation_run_id": run_id})
    )
    assert invoice_meta["total_count"] == 1
    assert_cents(invoices[0]["gross_amount_cents"], 10000, "gross_amount_cents")


def test_a_run_cannot_close_while_one_of_its_invoices_is_still_outstanding(api):
    """The same closure call is refused while issued and accepted once settled.

    PRD §3.6: "A `FinOpsController` moves `PUBLISHED → CLOSED` only when either
    the run's `mode` is `SHOWBACK`, or every chargeback invoice of the run has
    `settlement_status` of `SETTLED` or `WRITTEN_OFF`; and, additionally, no
    dispute on any invoice of the run remains in `OPEN`, `UNDER_REVIEW` or
    `INFO_REQUESTED`."

    Design: Difficulty/cross_entity_state_dependency/run_close_gated_by_every_invoice_reaching_a_settled_state
    """
    fixtures.set_clock(api, AUGUST_FIFTH_UTC)
    built = fixtures.direct_chargeback_invoice(api)
    run_id = built["run"]["id"]

    blocked = api.close_allocation_run(run_id, CONTROLLER_HEADERS)
    validate_error(blocked, ApiErrorId.RUN_NOT_FULLY_SETTLED.value, 409)

    still_published = validate_success(api.get_allocation_run(run_id, CONTROLLER_HEADERS))
    assert still_published["status"] == "PUBLISHED"

    settled = validate_success(
        api.settle_invoice(
            built["invoice"]["id"], 10000, make_business_unit_owner_headers(built["unit"]["id"])
        )
    )
    assert settled["settlement_status"] == "SETTLED"
    assert_cents(settled["paid_amount_cents"], 10000, "paid_amount_cents")
    assert_cents(settled["net_due_cents"], 0, "net_due_cents")

    closed = validate_success(api.close_allocation_run(run_id, CONTROLLER_HEADERS))
    assert closed["status"] == "CLOSED"


def test_closure_is_terminal_so_the_settled_run_can_never_be_reopened(api):
    """A closed run refuses the reopen that a published run would have allowed.

    PRD §3.6: "Closure freezes the run: no further compute, publication,
    reopening or manual adjustment is permitted, and the run's `version`
    increments one last time."

    Design: Difficulty/cross_entity_state_dependency/run_close_gated_by_every_invoice_reaching_a_settled_state
    """
    fixtures.set_clock(api, AUGUST_FIFTH_UTC)
    built = fixtures.direct_chargeback_invoice(api)
    run_id = built["run"]["id"]

    validate_success(
        api.settle_invoice(
            built["invoice"]["id"], 10000, make_business_unit_owner_headers(built["unit"]["id"])
        )
    )
    closed = validate_success(api.close_allocation_run(run_id, CONTROLLER_HEADERS))
    assert closed["status"] == "CLOSED"

    refused = api.reopen_allocation_run(
        run_id, "Late July storage bill arrived after publication.", CONTROLLER_HEADERS
    )
    validate_error(refused, ApiErrorId.RUN_STATE_INVALID.value, 409)

    frozen = validate_success(api.get_allocation_run(run_id, CONTROLLER_HEADERS))
    assert frozen["status"] == "CLOSED"
    assert frozen["reopen_count"] == 0
    assert_cents(frozen["total_allocated_cents"], 10000, "total_allocated_cents")

    record = validate_success(api.get_cost_record(built["record"]["id"], CONTROLLER_HEADERS))
    assert record["allocation_state"] == "ALLOCATED"
    assert record["allocated_by_run_id"] == run_id


def test_abutting_run_periods_are_allowed_while_a_one_second_overlap_is_not(api):
    """July's neighbours on both sides are accepted; anything that shares an instant is not.

    PRD §2.5: "Because the interval is half-open, abutting periods — where one
    run's `period_end` is exactly the next run's `period_start` — are permitted."

    Design: Difficulty/resource_temporal_overlap/allocation_run_periods_half_open_adjacency_allowed
    """
    fixtures.set_clock(api, AUGUST_FIFTH_UTC)
    fixtures.create_chargeback_unit(api)
    july = fixtures.create_run(api, mode="CHARGEBACK")
    assert july["status"] == "DRAFT"

    def open_chargeback(period_start, period_end):
        return api.create_allocation_run(
            factories.allocation_run_payload(
                mode="CHARGEBACK", period_start=period_start, period_end=period_end
            ),
            ANALYST_HEADERS,
        )

    august = validate_success(open_chargeback(AUGUST_START, AUGUST_END), 201)
    assert august["status"] == "DRAFT"

    validate_error(
        open_chargeback("2026-07-15T00:00:00Z", "2026-08-15T00:00:00Z"),
        ApiErrorId.ALLOCATION_PERIOD_OVERLAP.value,
        409,
    )

    june = validate_success(open_chargeback(JUNE_START, JULY_START), 201)
    assert june["status"] == "DRAFT"

    validate_error(
        open_chargeback("2026-07-31T23:59:59Z", JULY_END),
        ApiErrorId.ALLOCATION_PERIOD_OVERLAP.value,
        409,
    )

    _, meta = validate_paginated(
        api.list_allocation_runs(ANALYST_HEADERS, {"mode": "CHARGEBACK"})
    )
    assert meta["total_count"] == 3


def test_the_period_conflict_is_keyed_on_the_runs_mode(api):
    """A showback run takes the very period a chargeback run was refused.

    PRD §2.5: "Two runs of the same `mode` and the same `scope_business_unit_id`
    may not have overlapping periods unless the earlier one is already `CLOSED`."

    Design: Difficulty/resource_temporal_overlap/allocation_run_periods_half_open_adjacency_allowed
    """
    fixtures.set_clock(api, AUGUST_FIFTH_UTC)
    fixtures.create_chargeback_unit(api)
    fixtures.create_run(api, mode="CHARGEBACK")

    overlapping_period = ("2026-07-15T00:00:00Z", "2026-08-15T00:00:00Z")
    validate_error(
        api.create_allocation_run(
            factories.allocation_run_payload(
                mode="CHARGEBACK",
                period_start=overlapping_period[0],
                period_end=overlapping_period[1],
            ),
            ANALYST_HEADERS,
        ),
        ApiErrorId.ALLOCATION_PERIOD_OVERLAP.value,
        409,
    )

    showback = validate_success(
        api.create_allocation_run(
            factories.allocation_run_payload(
                mode="SHOWBACK",
                period_start=overlapping_period[0],
                period_end=overlapping_period[1],
            ),
            ANALYST_HEADERS,
        ),
        201,
    )
    assert showback["mode"] == "SHOWBACK"
    assert showback["status"] == "DRAFT"

    _, chargeback_meta = validate_paginated(
        api.list_allocation_runs(ANALYST_HEADERS, {"mode": "CHARGEBACK"})
    )
    assert chargeback_meta["total_count"] == 1

    _, showback_meta = validate_paginated(
        api.list_allocation_runs(ANALYST_HEADERS, {"mode": "SHOWBACK"})
    )
    assert showback_meta["total_count"] == 1

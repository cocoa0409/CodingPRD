"""Fiscal period lifecycle: overlap rules, reopen cycle, soft-close sweep, gates."""

from test_helpers import (
    ApiErrorId,
    api_client,
    create_accrual,
    create_counsel,
    create_department,
    create_firm,
    create_fiscal_period,
    create_invoice,
    create_matter,
    get_success_data,
    hard_close_period,
    reopen_period,
    setup_matter_graph,
    setup_reopened_period,
    soft_close_period,
    validate_success,
    validate_error,
    validate_paginated,
    ANALYST,
    MANAGER,
)


class TestPeriodOverlap:
    def test_adjacent_period_accepted_overlaps_rejected(self, api):
        """PRD §3.2: "The end date must fall strictly after the start date, and the
        new period's inclusive date range may not overlap any existing period's
        range — though periods may touch: one period ending the day before another
        begins is permitted. A violation is rejected with `ERR_PERIOD_OVERLAP`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/fiscal_period_overlap_half_open_adjacency
        """
        create_department()
        create_fiscal_period(label="FY2026", start_date="2026-01-01", end_date="2026-12-31")

        # Adjacent: starts exactly one day after the existing period ends.
        ok = api.create_fiscal_period(
            {"label": "FY2027", "start_date": "2027-01-01", "end_date": "2027-12-31"}, MANAGER
        )
        validate_success(ok, 201)

        # Same-day touch of the inclusive end is an overlap.
        res = api.create_fiscal_period(
            {"label": "FY2026-OVERLAP", "start_date": "2026-12-31", "end_date": "2027-06-30"},
            MANAGER,
        )
        validate_error(res, ApiErrorId.ERR_PERIOD_OVERLAP)

        # Strictly inside the existing range is an overlap.
        res = api.create_fiscal_period(
            {"label": "FY2026-INSIDE", "start_date": "2026-06-01", "end_date": "2026-06-30"},
            MANAGER,
        )
        validate_error(res, ApiErrorId.ERR_PERIOD_OVERLAP)

    def test_adjacency_before_existing_and_inverted_range(self, api):
        """PRD §3.2: "The end date must fall strictly after the start date, and the
        new period's inclusive date range may not overlap any existing period's
        range — though periods may touch: one period ending the day before another
        begins is permitted. A violation is rejected with `ERR_PERIOD_OVERLAP`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/fiscal_period_overlap_half_open_adjacency
        """
        create_department()
        create_fiscal_period(label="FY2026", start_date="2026-01-01", end_date="2026-12-31")

        # Period ending the day before the existing one begins — permitted.
        ok = api.create_fiscal_period(
            {"label": "FY2025", "start_date": "2025-01-01", "end_date": "2025-12-31"}, MANAGER
        )
        validate_success(ok, 201)

        # end_date not strictly after start_date is a violation.
        res = api.create_fiscal_period(
            {"label": "FY-BAD", "start_date": "2028-06-30", "end_date": "2028-06-30"}, MANAGER
        )
        validate_error(res, ApiErrorId.ERR_PERIOD_OVERLAP)


class TestPeriodReopenCycle:
    def test_reopen_cycle_terminates_at_limit(self, api):
        """PRD §3.7: "A manager may reopen it — `HARD_CLOSED` → `REOPENED` — at
        most twice: the period's `reopen_count`, starting at zero, increments on
        each reopen, and a third attempt is rejected with `ERR_REOPEN_LIMIT`
        (HTTP 422)."
        PRD §3.7: "A reopened period must pass through soft close again, with its
        sweep, before it can hard-close a second time."

        Design: Difficulty/non_linear_state_machine/fiscal_period_open_softclose_reopen_cycle
        """
        create_department()
        fp = create_fiscal_period()

        soft_close_period(fp["id"])
        hard_close_period(fp["id"])

        first = reopen_period(fp["id"])
        assert first["status"] == "REOPENED"
        assert first["reopen_count"] == 1

        second_soft = soft_close_period(fp["id"])
        assert second_soft["status"] == "SOFT_CLOSED"
        hard_close_period(fp["id"])

        second = reopen_period(fp["id"])
        assert second["status"] == "REOPENED"
        assert second["reopen_count"] == 2

        soft_close_period(fp["id"])
        hard_close_period(fp["id"])

        res = api_client.reopen_fiscal_period(fp["id"], MANAGER)
        validate_error(res, ApiErrorId.ERR_REOPEN_LIMIT)

    def test_reopened_period_accepts_operational_writes(self, api):
        """PRD §3.7: "While `REOPENED`, the period once again accepts operational
        writes per §2.5, and matters within it may resume, close, or be reopened
        themselves; activation of new matters remains the exception noted in
        §3.3."

        Design: Difficulty/non_linear_state_machine/fiscal_period_open_softclose_reopen_cycle
        """
        graph = setup_reopened_period()
        assert graph["fiscal_period"]["status"] == "REOPENED"

        firm = create_firm()
        counsel = create_counsel()
        pa = graph["practice_area"]
        mt = graph["matter_type"]

        matter = create_matter(pa["id"], mt["id"], graph["fiscal_period"]["id"], counsel["id"],
                               primary_firm_id=firm["id"])
        assert matter["status"] == "INTAKE"

        accrual = create_accrual(matter["id"], graph["fiscal_period"]["id"], firm["id"], 50000)
        assert accrual["status"] == "OUTSTANDING"


class TestSoftCloseSweep:
    def test_soft_close_sweeps_outstanding_accruals(self, api):
        """PRD §3.7: "Either way, soft close triggers the accrual expiry sweep:
        every accrual still `OUTSTANDING` in the period transitions to `EXPIRED`,
        each affected matter's `accrual_outstanding_cents` is recomputed — to
        zero, since only outstanding accruals contribute — and the period's
        `total_accrual_cents` recomputes to zero alongside."

        Design: Difficulty/transitive_cascade/period_soft_close_cascades_through_accrual_to_matter
        """
        graph = setup_matter_graph()
        fp_id = graph["fiscal_period"]["id"]
        firm_id = graph["firm"]["id"]
        m1 = graph["matter"]
        m2 = create_matter(
            graph["practice_area"]["id"], graph["matter_type"]["id"], fp_id,
            graph["counsel"]["id"], primary_firm_id=firm_id,
        )
        get_success_data(
            api_client.create_assignment(
                m2["id"], {"counsel_id": graph["counsel"]["id"], "allocated_hours": 5}, ANALYST
            )
        )
        get_success_data(api_client.activate_matter(m2["id"], ANALYST))

        a1 = create_accrual(m1["id"], fp_id, firm_id, 200000)
        a2 = create_accrual(m2["id"], fp_id, firm_id, 300000)

        closed = soft_close_period(fp_id)
        assert closed["status"] == "SOFT_CLOSED"
        assert closed["total_accrual_cents"] == 0

        m1_after = get_success_data(api_client.get_matter(m1["id"], ANALYST))
        m2_after = get_success_data(api_client.get_matter(m2["id"], ANALYST))
        assert m1_after["accrual_outstanding_cents"] == 0
        assert m2_after["accrual_outstanding_cents"] == 0

        expired, meta = validate_paginated(
            api_client.list_accruals(ANALYST, params={"fiscal_period_id": fp_id, "status": "EXPIRED"})
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in expired} == {a1["id"], a2["id"]}
        assert all(row["status"] == "EXPIRED" for row in expired)

    def test_sweep_leaves_non_outstanding_accruals_untouched(self, api):
        """PRD §3.7: "Either way, soft close triggers the accrual expiry sweep:
        every accrual still `OUTSTANDING` in the period transitions to `EXPIRED`"
        PRD §3.5: "While its period remains `OPEN` or `REOPENED`, an analyst may
        release an outstanding accrual; release moves it from `OUTSTANDING` to
        `RELEASED`, subtracts its amount from both aggregates, and bumps the
        accrual's `version`."

        Design: Difficulty/transitive_cascade/period_soft_close_cascades_through_accrual_to_matter
        """
        graph = setup_matter_graph()
        fp_id = graph["fiscal_period"]["id"]
        firm_id = graph["firm"]["id"]
        m_id = graph["matter"]["id"]

        released = create_accrual(m_id, fp_id, firm_id, 700000)
        outstanding = create_accrual(m_id, fp_id, firm_id, 300000)
        validate_success(api_client.release_accrual(released["id"], ANALYST), 200)

        closed = soft_close_period(fp_id)
        assert closed["total_accrual_cents"] == 0

        a1_after = get_success_data(api_client.get_accrual(released["id"], ANALYST))
        a2_after = get_success_data(api_client.get_accrual(outstanding["id"], ANALYST))
        assert a1_after["status"] == "RELEASED"
        assert a2_after["status"] == "EXPIRED"


def test_invoice_into_soft_closed_period_rejected(api):
    """PRD §3.5: "Submission is guarded, in order, by the calendar gate
    (`ERR_PERIOD_CLOSED`), by firm activity (`ERR_ENTITY_INACTIVE` when the firm
    is not `ACTIVE`), and by the per-firm uniqueness of `invoice_number`
    (`ERR_DUPLICATE` when the same firm already carries that number)."
    PRD §2.5: "Against a period in any other state, these writes fail with
    `ERR_PERIOD_CLOSED` (HTTP 409)."

    Design: Corner/validations/invoice_into_closed_period_rejected
    """
    graph = setup_matter_graph()
    soft_close_period(graph["fiscal_period"]["id"])
    res = api_client.create_invoice(
        {
            "matter_id": graph["matter"]["id"],
            "firm_id": graph["firm"]["id"],
            "fiscal_period_id": graph["fiscal_period"]["id"],
            "invoice_number": "I-CLOSED-1",
            "amount_cents": 1000,
        },
        ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_PERIOD_CLOSED)


def test_hard_close_blocked_by_submitted_invoice(api):
    """PRD §3.7: "Hard close is a manager action from `SOFT_CLOSED`, blocked when
    any invoice in the period is still `SUBMITTED` or any dashboard for the
    period is still `DRAFT`; the rejection is `ERR_PERIOD_NOT_CLOSABLE`
    (HTTP 422)."

    Design: Corner/validations/hard_close_blocked_by_submitted_invoice
    """
    graph = setup_matter_graph()
    create_invoice(
        graph["matter"]["id"], graph["firm"]["id"], graph["fiscal_period"]["id"], 1000
    )
    soft_close_period(graph["fiscal_period"]["id"])
    res = api_client.hard_close_fiscal_period(graph["fiscal_period"]["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_PERIOD_NOT_CLOSABLE)

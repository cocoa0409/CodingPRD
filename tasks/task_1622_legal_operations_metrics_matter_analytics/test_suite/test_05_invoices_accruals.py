"""Invoice pipeline: parallel status dimensions, accrual matching, SOD, releases."""

from test_helpers import (
    ApiErrorId,
    SOD_THRESHOLD_CENTS,
    api_client,
    approve_invoice,
    create_accrual,
    create_invoice,
    get_success_data,
    make_analyst_headers,
    pay_invoice,
    setup_matter_graph,
    validate_success,
    validate_error,
    ANALYST,
    MANAGER,
)


class TestParallelStateDimensions:
    def test_payment_and_match_axes_evolve_independently(self, api):
        """PRD §3.5: "An invoice is born `SUBMITTED` on its `payment_status`
        dimension and `UNMATCHED` on its `accrual_match_status` dimension — two
        parallel status dimensions that evolve independently — with
        `matched_accrual_id` null until a match is found."
        PRD §3.5: "equal amounts classify `FULLY_MATCHED`; an accrual larger than
        the invoice classifies `PARTIALLY_MATCHED`; an accrual smaller than the
        invoice classifies `OVER_BILLED`."

        Design: Difficulty/non_linear_state_machine/invoice_parallel_state_dimensions
        """
        graph = setup_matter_graph()
        fp_id = graph["fiscal_period"]["id"]
        firm_id = graph["firm"]["id"]
        m_id = graph["matter"]["id"]

        create_accrual(m_id, fp_id, firm_id, 500000)
        inv = create_invoice(m_id, firm_id, fp_id, 300000)
        assert inv["payment_status"] == "SUBMITTED"
        assert inv["accrual_match_status"] == "UNMATCHED"
        assert inv["matched_accrual_id"] is None

        approved = approve_invoice(inv["id"])
        assert approved["payment_status"] == "APPROVED"
        assert approved["accrual_match_status"] == "PARTIALLY_MATCHED"  # 500000 > 300000

        paid = pay_invoice(inv["id"])
        assert paid["payment_status"] == "PAID"
        # The match axis is set at approval time and preserved across payment.
        assert paid["accrual_match_status"] == "PARTIALLY_MATCHED"

    def test_no_qualifying_accrual_stays_unmatched_through_payment(self, api):
        """PRD §3.5: "When no outstanding accrual qualifies, `accrual_match_status`
        simply stays `UNMATCHED`."

        Design: Difficulty/non_linear_state_machine/invoice_parallel_state_dimensions
        """
        graph = setup_matter_graph()
        fp_id = graph["fiscal_period"]["id"]
        firm_id = graph["firm"]["id"]
        m_id = graph["matter"]["id"]

        inv = create_invoice(m_id, firm_id, fp_id, 50000)
        approved = approve_invoice(inv["id"])
        assert approved["payment_status"] == "APPROVED"
        assert approved["accrual_match_status"] == "UNMATCHED"
        assert approved["matched_accrual_id"] is None

        paid = pay_invoice(inv["id"])
        assert paid["payment_status"] == "PAID"
        assert paid["accrual_match_status"] == "UNMATCHED"


class TestSegregationOfDuties:
    def test_self_approval_rejected_even_when_firm_suspended(self, api):
        """PRD §3.5: "Then — before the calendar gate runs — the duty check fires:
        when `amount_cents` is at least 100000 (one thousand dollars), the
        approver's `X-User-ID` must differ from the identifier recorded at
        submission, and a self-approval is rejected with `ERR_SOD_VIOLATION`
        (HTTP 403)."
        PRD §2.1: "when an analyst submits an invoice, the server records the
        submitter's `X-User-ID` as the invoice's creator, and the
        segregation-of-duties check at approval time compares the approver's
        `X-User-ID` against that recorded creator (see §3.5)."

        Design: Difficulty/priority_pair_validation_conflict/sod_vs_referential_conflict_on_invoice_approve
        """
        graph = setup_matter_graph()
        creator = make_analyst_headers("analyst-1")
        inv = create_invoice(
            graph["matter"]["id"], graph["firm"]["id"], graph["fiscal_period"]["id"],
            200000, creator_headers=creator,
        )
        # Firm suspended after submission — the duty check still owns the verdict.
        get_success_data(api_client.suspend_firm(graph["firm"]["id"], MANAGER))
        res = api_client.approve_invoice(inv["id"], creator)
        validate_error(res, ApiErrorId.ERR_SOD_VIOLATION)

    def test_sod_threshold_at_and_below_100000(self, api):
        """PRD §3.5: "when `amount_cents` is at least 100000 (one thousand
        dollars), the approver's `X-User-ID` must differ from the identifier
        recorded at submission, and a self-approval is rejected with
        `ERR_SOD_VIOLATION` (HTTP 403). Invoices below that threshold may be
        self-approved."

        Design: Difficulty/priority_pair_validation_conflict/sod_vs_referential_conflict_on_invoice_approve
        """
        graph = setup_matter_graph()
        creator = make_analyst_headers("analyst-1")
        fp_id = graph["fiscal_period"]["id"]
        firm_id = graph["firm"]["id"]
        m_id = graph["matter"]["id"]

        at_threshold = create_invoice(m_id, firm_id, fp_id, SOD_THRESHOLD_CENTS,
                                      creator_headers=creator)
        res = api_client.approve_invoice(at_threshold["id"], creator)
        validate_error(res, ApiErrorId.ERR_SOD_VIOLATION)

        below_threshold = create_invoice(m_id, firm_id, fp_id, SOD_THRESHOLD_CENTS - 1,
                                         creator_headers=creator)
        approved = validate_success(
            api_client.approve_invoice(below_threshold["id"], creator), 200
        )
        assert approved["payment_status"] == "APPROVED"


class TestAccrualConservation:
    def test_release_restores_matter_and_period_totals(self, api):
        """PRD §3.5: "A new accrual is `OUTSTANDING`, and its amount immediately
        raises both the matter's `accrual_outstanding_cents` and the period's
        `total_accrual_cents`."
        PRD §3.5: "While its period remains `OPEN` or `REOPENED`, an analyst may
        release an outstanding accrual; release moves it from `OUTSTANDING` to
        `RELEASED`, subtracts its amount from both aggregates, and bumps the
        accrual's `version`."

        Design: Difficulty/compensating_invariant/accrual_release_conserves_period_total
        """
        graph = setup_matter_graph()
        fp_id = graph["fiscal_period"]["id"]
        firm_id = graph["firm"]["id"]
        m_id = graph["matter"]["id"]

        m_pre = get_success_data(api_client.get_matter(m_id, ANALYST))
        fp_pre = get_success_data(api_client.get_fiscal_period(fp_id, ANALYST))
        assert m_pre["accrual_outstanding_cents"] == 0
        assert fp_pre["total_accrual_cents"] == 0

        accrual = create_accrual(m_id, fp_id, firm_id, 700000)
        m_mid = get_success_data(api_client.get_matter(m_id, ANALYST))
        fp_mid = get_success_data(api_client.get_fiscal_period(fp_id, ANALYST))
        assert m_mid["accrual_outstanding_cents"] == 700000
        assert fp_mid["total_accrual_cents"] == 700000

        released = validate_success(api_client.release_accrual(accrual["id"], ANALYST), 200)
        assert released["status"] == "RELEASED"
        m_post = get_success_data(api_client.get_matter(m_id, ANALYST))
        fp_post = get_success_data(api_client.get_fiscal_period(fp_id, ANALYST))
        assert m_post["accrual_outstanding_cents"] == 0
        assert fp_post["total_accrual_cents"] == 0

    def test_partial_release_leaves_remainder_on_both_aggregates(self, api):
        """PRD §3.5: "While its period remains `OPEN` or `REOPENED`, an analyst
        may release an outstanding accrual; release moves it from `OUTSTANDING` to
        `RELEASED`, subtracts its amount from both aggregates, and bumps the
        accrual's `version`."

        Design: Difficulty/compensating_invariant/accrual_release_conserves_period_total
        """
        graph = setup_matter_graph()
        fp_id = graph["fiscal_period"]["id"]
        firm_id = graph["firm"]["id"]
        m_id = graph["matter"]["id"]

        a1 = create_accrual(m_id, fp_id, firm_id, 700000)
        create_accrual(m_id, fp_id, firm_id, 300000)
        validate_success(api_client.release_accrual(a1["id"], ANALYST), 200)

        m_after = get_success_data(api_client.get_matter(m_id, ANALYST))
        fp_after = get_success_data(api_client.get_fiscal_period(fp_id, ANALYST))
        assert m_after["accrual_outstanding_cents"] == 300000
        assert fp_after["total_accrual_cents"] == 300000


def test_accrual_match_exact_amount_fully_matched(api):
    """PRD §3.5: "When a candidate is found, its `id` is recorded in
    `matched_accrual_id` and the match is classified by exact integer-cent
    comparison of the accrual's amount against the invoice's: equal amounts
    classify `FULLY_MATCHED`; an accrual larger than the invoice classifies
    `PARTIALLY_MATCHED`; an accrual smaller than the invoice classifies
    `OVER_BILLED`."

    Design: Corner/calculations/accrual_match_fully_matched_boundary
    """
    graph = setup_matter_graph()
    fp_id = graph["fiscal_period"]["id"]
    firm_id = graph["firm"]["id"]
    m_id = graph["matter"]["id"]

    accrual = create_accrual(m_id, fp_id, firm_id, 500000)
    inv = create_invoice(m_id, firm_id, fp_id, 500000)
    approved = approve_invoice(inv["id"])
    assert approved["accrual_match_status"] == "FULLY_MATCHED"
    assert approved["matched_accrual_id"] == accrual["id"]


def test_accrual_smaller_than_invoice_is_over_billed(api):
    """PRD §3.5: "equal amounts classify `FULLY_MATCHED`; an accrual larger than
    the invoice classifies `PARTIALLY_MATCHED`; an accrual smaller than the
    invoice classifies `OVER_BILLED`."

    Design: Corner/calculations/accrual_match_over_billed
    """
    graph = setup_matter_graph()
    fp_id = graph["fiscal_period"]["id"]
    firm_id = graph["firm"]["id"]
    m_id = graph["matter"]["id"]

    create_accrual(m_id, fp_id, firm_id, 100000)
    inv = create_invoice(m_id, firm_id, fp_id, 150000)
    approved = approve_invoice(inv["id"])
    assert approved["accrual_match_status"] == "OVER_BILLED"


def test_second_approve_of_approved_invoice_rejected(api):
    """PRD §3.5: "The invoice must still be `SUBMITTED`, else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/invoice_idempotent_second_approve_rejected
    """
    graph = setup_matter_graph()
    inv = create_invoice(
        graph["matter"]["id"], graph["firm"]["id"], graph["fiscal_period"]["id"], 50000
    )
    approve_invoice(inv["id"])
    res = api_client.approve_invoice(inv["id"], make_analyst_headers("analyst-9"))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_invoice_against_suspended_firm_rejected(api):
    """PRD §3.5: "Submission is guarded, in order, by the calendar gate
    (`ERR_PERIOD_CLOSED`), by firm activity (`ERR_ENTITY_INACTIVE` when the firm
    is not `ACTIVE`), and by the per-firm uniqueness of `invoice_number`
    (`ERR_DUPLICATE` when the same firm already carries that number)."
    PRD §3.1: "Firms start `ACTIVE`; suspending one moves it to `SUSPENDED`, and
    a suspended firm can no longer receive new invoices."

    Design: Corner/validations/invoice_create_against_suspended_firm_rejected
    """
    graph = setup_matter_graph()
    get_success_data(api_client.suspend_firm(graph["firm"]["id"], MANAGER))
    res = api_client.create_invoice(
        {
            "matter_id": graph["matter"]["id"],
            "firm_id": graph["firm"]["id"],
            "fiscal_period_id": graph["fiscal_period"]["id"],
            "invoice_number": "I-SUSP-1",
            "amount_cents": 1000,
        },
        ANALYST,
    )
    validate_error(res, ApiErrorId.ERR_ENTITY_INACTIVE)


def test_sod_enforced_for_creator_other_analyst_allowed(api):
    """PRD §3.5: "Then — before the calendar gate runs — the duty check fires:
    when `amount_cents` is at least 100000 (one thousand dollars), the approver's
    `X-User-ID` must differ from the identifier recorded at submission, and a
    self-approval is rejected with `ERR_SOD_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/sod_segregation_of_duties_enforced
    """
    graph = setup_matter_graph()
    creator = make_analyst_headers("analyst-1")
    other = make_analyst_headers("analyst-2")
    inv = create_invoice(
        graph["matter"]["id"], graph["firm"]["id"], graph["fiscal_period"]["id"],
        200000, creator_headers=creator,
    )
    res = api_client.approve_invoice(inv["id"], creator)
    validate_error(res, ApiErrorId.ERR_SOD_VIOLATION)

    approved = validate_success(api_client.approve_invoice(inv["id"], other), 200)
    assert approved["payment_status"] == "APPROVED"

"""Proposing plans and generating the installment schedule at approval.

PRD §3.6 splits the plan lifecycle in two: proposal checks the count and the
down payment, while approval generates the schedule behind two guards that are
evaluated before any installment row is written.
"""

from test_helpers import (
    ADMIN_HEADERS,
    CANONICAL_DOWN_PAYMENT_CENTS,
    CANONICAL_INSTALLMENT_COUNT,
    MIN_INSTALLMENT_CENTS,
    OFFICER_ALPHA_HEADERS,
    ApiErrorId,
    assert_error_data_shape,
    assert_fields,
    assert_list_total,
    assert_response_envelope,
    close_window,
    installments_of,
    payment_plan_payload,
    propose_payment_plan,
    read_agreement,
    read_plan,
    remit_payment,
    rows_by_seq_index,
    set_clock,
    setup_agreement_with_down_payment,
    setup_filed_return,
    validate_error,
    validate_success,
)

UNKNOWN_INSTALLMENT_ID = "00000000-0000-4000-8000-00000000dead"


class TestDownPaymentMinimum:
    """Ten percent of `total_due_cents`, inclusive at the floor."""

    def test_one_cent_below_the_ten_percent_floor_is_refused(self, api):
        """The floor is a minimum, so 104,999 against 1,050,000 due is short.

        PRD §3.6: "And the commitment must be serious: `down_payment_cents` must
        be at least ten percent of the agreement's `total_due_cents`, that
        minimum itself being rounded half up to whole cents, otherwise
        `ERR_DOWN_PAYMENT_BELOW_MINIMUM`."

        Design: Difficulty/boundary_precision_check/down_payment_minimum_is_inclusive_at_ten_percent
        """
        ctx = setup_filed_return(
            api,
            program_overrides={"installment_max_count": 12},
            taxpayer_overrides={
                "legal_name": "Bramble Hill Nursery LLC",
                "tin_last4": "1276",
            },
        )
        agreement_version = read_agreement(api, ctx["agreement"]["id"])["version"]

        validate_error(
            api.create_payment_plan(
                payment_plan_payload(
                    ctx["agreement"]["id"],
                    agreement_version,
                    CANONICAL_INSTALLMENT_COUNT,
                    104999,
                ),
                ctx["taxpayer_headers"],
            ),
            ApiErrorId.DOWN_PAYMENT_BELOW_MINIMUM,
        )

        assert_list_total(
            api.list_agreement_payment_plans(
                ctx["agreement"]["id"], ADMIN_HEADERS, {"limit": 100}
            ),
            0,
        )
        assert_fields(
            read_agreement(api, ctx["agreement"]["id"]), version=agreement_version
        )

    def test_exactly_ten_percent_is_accepted(self, api):
        """At the floor itself the proposal stands, with no schedule yet.

        PRD §3.6: "The plan is created in `PROPOSED` with `proposed_by_user_id`
        set from the proposer, `scheduled_total_cents` at 0, and `approved_at`,
        `rejection_reason` and `default_reason` null"

        Design: Difficulty/boundary_precision_check/down_payment_minimum_is_inclusive_at_ten_percent
        """
        ctx = setup_filed_return(
            api,
            program_overrides={"installment_max_count": 12},
            taxpayer_overrides={
                "legal_name": "Bramble Hill Nursery LLC",
                "tin_last4": "1276",
            },
        )

        plan = propose_payment_plan(
            api,
            ctx,
            installment_count=CANONICAL_INSTALLMENT_COUNT,
            down_payment_cents=CANONICAL_DOWN_PAYMENT_CENTS,
        )
        assert_fields(
            plan,
            status="PROPOSED",
            down_payment_cents=CANONICAL_DOWN_PAYMENT_CENTS,
            scheduled_total_cents=0,
            approved_at=None,
        )
        assert_list_total(
            api.list_agreement_payment_plans(
                ctx["agreement"]["id"], ADMIN_HEADERS, {"limit": 100}
            ),
            1,
        )


class TestApprovalRequiresAnOpenProgram:
    """Approval is a participation act, so the window must still be live."""

    def test_approval_after_the_window_shuts_writes_no_schedule(self, api):
        """The plan stays `PROPOSED` and no installment row exists.

        PRD §3.6: "Approval requires the plan to be `PROPOSED`, the agreement to
        be `EXECUTED`, and the program to be `OPEN` with the current instant
        strictly before `window_close_at` — a plan cannot be blessed after the
        window shuts."

        PRD §2.6: "The governing `AmnestyProgram` must be in the state the
        operation requires — `DRAFT` to add tax type terms or to open, `OPEN` to
        participate, `CLOSED` to reconcile or to issue post-program actions —
        otherwise `ERR_PROGRAM_NOT_DRAFT`, `ERR_PROGRAM_NOT_OPEN` or
        `ERR_PROGRAM_NOT_CLOSED` (409)."

        Design: Difficulty/cross_entity_state_dependency/closed_program_gates_plan_approval_and_writes_nothing
        """
        ctx = setup_agreement_with_down_payment(
            api,
            program_overrides={"installment_max_count": 12},
            taxpayer_overrides={
                "legal_name": "Hollow Creek Roasters LLC",
                "tin_last4": "3364",
            },
        )
        plan = propose_payment_plan(api, ctx)
        close_window(api, ctx["program"]["id"])

        validate_error(
            api.approve_payment_plan(plan["id"], OFFICER_ALPHA_HEADERS),
            ApiErrorId.PROGRAM_NOT_OPEN,
        )

        assert_fields(
            read_plan(api, plan["id"]),
            status="PROPOSED",
            approved_at=None,
            scheduled_total_cents=0,
        )
        assert_list_total(
            api.list_plan_installments(plan["id"], ADMIN_HEADERS, {"limit": 100}), 0
        )

    def test_the_down_payment_stays_in_float_when_approval_is_refused(self, api):
        """Only approval moves cash out of float into commitment.

        PRD §3.6: "the down payment is moved out of float and into commitment —
        the agreement's `unapplied_credit_cents` decreases by
        `down_payment_cents` and its `down_payment_applied_cents` increases by
        the same amount"

        PRD §3.6: "when the agreement has no `ACTIVE` plan at all, the whole
        payment becomes unapplied credit, which is precisely what a
        pre-approval down payment is."

        Design: Difficulty/cross_entity_state_dependency/closed_program_gates_plan_approval_and_writes_nothing
        """
        ctx = setup_agreement_with_down_payment(
            api,
            program_overrides={"installment_max_count": 12},
            taxpayer_overrides={
                "legal_name": "Hollow Creek Roasters LLC",
                "tin_last4": "3364",
            },
        )
        plan = propose_payment_plan(api, ctx)
        close_window(api, ctx["program"]["id"])
        validate_error(
            api.approve_payment_plan(plan["id"], OFFICER_ALPHA_HEADERS),
            ApiErrorId.PROGRAM_NOT_OPEN,
        )

        assert_fields(
            read_agreement(api, ctx["agreement"]["id"]),
            status="EXECUTED",
            payment_status="PARTIAL",
            unapplied_credit_cents=CANONICAL_DOWN_PAYMENT_CENTS,
            down_payment_applied_cents=0,
        )


class TestScheduleGuards:
    """Both guards run before any installment row is written."""

    def test_a_schedule_whose_installments_fall_below_the_floor_is_refused(self, api):
        """Fourteen ways to split 18,900 cents leaves 1,350 per installment.

        PRD §3.6: "The floor guard requires the smallest generated installment
        amount to be at least 2,500 cents, otherwise
        `ERR_INSTALLMENT_BELOW_MINIMUM`."

        PRD §3.6: "Two guards are evaluated **before any installment row is
        written**, so a rejected approval leaves no partial schedule behind."

        PRD §3.6: "any other plan of the same agreement still sitting in
        `PROPOSED` is moved to `SUPERSEDED` at that moment"

        Design: Corner/Table 4 Validations/installment_floor_guard_blocks_a_schedule_below_the_minimum
        """
        ctx = setup_agreement_with_down_payment(
            api,
            down_payment_cents=2100,
            program_overrides={"installment_max_count": 14},
            term_overrides={"min_liability_cents": 1000},
            taxpayer_overrides={
                "legal_name": "Cobble Hollow Cidery LLC",
                "tin_last4": "8890",
            },
            return_overrides={"reported_tax_cents": 20000},
        )
        assert_fields(
            read_agreement(api, ctx["agreement"]["id"]), total_due_cents=21000
        )

        wide_plan = propose_payment_plan(
            api, ctx, installment_count=14, down_payment_cents=2100
        )
        validate_error(
            api.approve_payment_plan(wide_plan["id"], OFFICER_ALPHA_HEADERS),
            ApiErrorId.INSTALLMENT_BELOW_MINIMUM,
        )
        assert_fields(
            read_plan(api, wide_plan["id"]),
            status="PROPOSED",
            scheduled_total_cents=0,
        )
        assert_list_total(
            api.list_plan_installments(wide_plan["id"], ADMIN_HEADERS, {"limit": 100}),
            0,
        )

        narrow_plan = propose_payment_plan(
            api, ctx, installment_count=7, down_payment_cents=2100
        )
        assert_fields(read_plan(api, wide_plan["id"]), status="SUPERSEDED")

        approved = validate_success(
            api.approve_payment_plan(narrow_plan["id"], OFFICER_ALPHA_HEADERS)
        )
        assert_fields(approved, status="ACTIVE", scheduled_total_cents=18900)

        rows = assert_list_total(
            api.list_plan_installments(
                narrow_plan["id"], ADMIN_HEADERS, {"limit": 100}
            ),
            7,
        )
        assert all(row["amount_cents"] == 2700 for row in rows)
        assert all(row["amount_cents"] >= MIN_INSTALLMENT_CENTS for row in rows)
        assert_fields(
            read_agreement(api, ctx["agreement"]["id"]),
            down_payment_applied_cents=2100,
            unapplied_credit_cents=0,
        )

    def test_the_horizon_is_measured_from_the_approval_instant(self, api):
        """A 24-month schedule overruns the horizon; a 12-month one fits.

        PRD §3.6: "The horizon guard requires the last installment's `due_date`
        to fall no later than the calendar date of `window_close_at` plus one
        full year of 365 days, otherwise `ERR_INSTALLMENT_HORIZON_EXCEEDED`."

        PRD §3.6: "a `due_date` computed as the calendar date of `approved_at`
        advanced by 30 days multiplied by that installment's `seq_index` — so the
        first installment falls due 30 days after approval, not on the approval
        date itself."

        Design: Corner/Table 4 Validations/installment_horizon_is_measured_from_the_approval_instant
        """
        ctx = setup_agreement_with_down_payment(
            api,
            down_payment_cents=104238,
            program_overrides={
                "name": "FY27 Short Window Amnesty",
                "window_close_at": "2026-10-01T00:00:00Z",
                "installment_max_count": 24,
            },
            taxpayer_overrides={
                "legal_name": "Bittern Reach Foods LLC",
                "tin_last4": "3345",
            },
        )
        assert_fields(
            read_agreement(api, ctx["agreement"]["id"]), total_due_cents=1042375
        )

        long_plan = propose_payment_plan(
            api, ctx, installment_count=24, down_payment_cents=104238
        )
        validate_error(
            api.approve_payment_plan(long_plan["id"], OFFICER_ALPHA_HEADERS),
            ApiErrorId.INSTALLMENT_HORIZON_EXCEEDED,
        )
        assert_list_total(
            api.list_plan_installments(long_plan["id"], ADMIN_HEADERS, {"limit": 100}),
            0,
        )

        short_plan = propose_payment_plan(
            api, ctx, installment_count=12, down_payment_cents=104238
        )
        assert_fields(read_plan(api, long_plan["id"]), status="SUPERSEDED")

        approved = validate_success(
            api.approve_payment_plan(short_plan["id"], OFFICER_ALPHA_HEADERS)
        )
        assert_fields(
            approved,
            status="ACTIVE",
            approved_at="2026-09-15T00:00:00.000Z",
            scheduled_total_cents=938137,
        )

        rows = rows_by_seq_index(installments_of(api, short_plan["id"]))
        assert len(rows) == 12
        assert_fields(rows[1], amount_cents=78178, due_date="2026-10-15")
        assert_fields(rows[12], amount_cents=78179, due_date="2027-09-10")


class TestPlanStaleness:
    """The plan payload declares the agreement version it was written against."""

    def test_a_plan_proposed_from_a_stale_agreement_view_is_refused(self, api):
        """The down payment moved the agreement on before the plan arrived.

        PRD §2.8: "Proposing a payment plan (`POST /amnesty/payment-plans`)
        requires `expected_agreement_version` as a non-optional field of the
        request body, carrying the client's last observed `version` of the target
        `VoluntaryDisclosureAgreement`. If it does not equal that agreement's
        current `version`, the request is rejected with
        `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."

        Design: Corner/Cross-Cutting Complexity Layers/stale_expected_agreement_version_is_refused_on_plan_creation
        """
        ctx = setup_filed_return(
            api,
            program_overrides={"installment_max_count": 12},
            taxpayer_overrides={
                "legal_name": "Hollow Reed Basketry LLC",
                "tin_last4": "5519",
            },
        )
        stale_version = read_agreement(api, ctx["agreement"]["id"])["version"]
        remit_payment(
            api, ctx, CANONICAL_DOWN_PAYMENT_CENTS, payment_reference="DOWN-1"
        )

        payload = payment_plan_payload(
            ctx["agreement"]["id"],
            stale_version,
            CANONICAL_INSTALLMENT_COUNT,
            CANONICAL_DOWN_PAYMENT_CENTS,
        )
        validate_error(
            api.create_payment_plan(payload, ctx["taxpayer_headers"]),
            ApiErrorId.STALE_AGREEMENT_VERSION,
        )
        assert_list_total(
            api.list_agreement_payment_plans(
                ctx["agreement"]["id"], ADMIN_HEADERS, {"limit": 100}
            ),
            0,
        )

        fresh_version = read_agreement(api, ctx["agreement"]["id"])["version"]
        assert fresh_version == stale_version + 1

        payload["expected_agreement_version"] = fresh_version
        plan = validate_success(
            api.create_payment_plan(payload, ctx["taxpayer_headers"]), 201
        )
        assert_fields(
            plan, status="PROPOSED", installment_count=CANONICAL_INSTALLMENT_COUNT
        )
        assert (
            read_agreement(api, ctx["agreement"]["id"])["version"] == fresh_version + 1
        )


def test_an_unknown_installment_id_reports_not_found(api):
    """A well-formed id that names no installment row.

    PRD §2.5: "Identifiers embedded in a URL path are resolved strictly left to
    right, and the leftmost identifier that fails to resolve decides the error."

    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/Table 6 Errors/unknown_installment_id_returns_not_found
    """
    set_clock(api, "2026-09-15T00:00:00Z")

    response = api.get_installment(UNKNOWN_INSTALLMENT_ID, ADMIN_HEADERS)
    validate_error(response, ApiErrorId.INSTALLMENT_NOT_FOUND)

    body = response.json()
    assert_response_envelope(body, "error")
    assert_error_data_shape(body["data"])
    assert body["data"]["message"]

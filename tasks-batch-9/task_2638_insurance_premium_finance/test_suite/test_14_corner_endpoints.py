"""Endpoint-shape corners: the read side of the ledger pages and filters over a
book parked in three different statuses, the servicing run reports aggregate
counts while skipping the notes it may not touch, policy attachment resolves two
independent parents and stays navigable from both, the payoff quote is a pure
function of the ledger, and endorsement financing is gated on a population
rather than on a status.
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_on_finance_charge_cents,
    assert_installments_sum,
    factories,
    fixtures,
    is_iso8601_timestamp,
    is_valid_uuid,
    late_fee_cents,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import ANALYST_ORIGIN, COMPLIANCE


def _tx_regime_context(api):
    """Clock at 2026-08-15, the canonical TX regime with an effective licence
    and the three counterparties."""
    fixtures.set_clock(api, "2026-08-15T00:00:00Z")
    ctx = fixtures.create_state_regime(
        api,
        rule_payload=factories.tx_state_rate_rule(),
        license_payload=factories.license_payload(license_number="PFC-TX-001"),
    )
    ctx.update(
        fixtures.create_parties(
            api,
            insured_payload=factories.insured(
                legal_name="Cascade Logistics Inc", email="ap@cascade.example"
            ),
        )
    )
    return ctx


class TestAgreementCreateReadAndFilteredPagination:
    """Three notes for one borrower, deliberately parked in three statuses, so
    that no filter can be satisfied by returning the whole collection."""

    def _terms(self, ctx):
        return factories.agreement(ctx["insured_id"], ctx["agent_id"], ctx["rule_id"])

    def _three_notes(self, api):
        """A1 stays DRAFT with no policies, A2 is submitted, A3 is voided."""
        ctx = _tx_regime_context(api)
        ctx["a1"] = validate_success(
            api.create_agreement(self._terms(ctx), ANALYST_ORIGIN), 201
        )
        ctx["a2"] = validate_success(
            api.create_agreement(self._terms(ctx), ANALYST_ORIGIN), 201
        )
        ctx["a3"] = validate_success(
            api.create_agreement(self._terms(ctx), ANALYST_ORIGIN), 201
        )
        validate_success(
            api.attach_policy(
                ctx["a2"]["id"],
                factories.financed_policy(
                    ctx["insurer_id"], policy_number="MC-CR-A2"
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )
        ctx["a2_submitted"] = validate_success(
            api.submit_agreement(ctx["a2"]["id"], ANALYST_ORIGIN), 200
        )
        ctx["a3_voided"] = validate_success(
            api.void_agreement(
                ctx["a3"]["id"],
                ANALYST_ORIGIN,
                {"reason": "insured withdrew the application"},
            ),
            200,
        )
        return ctx

    def test_creation_echoes_every_commercial_term_it_was_given(self, api):
        """The 201 body carries back the four terms and the opening version.

        The PRD states: "A `FinanceAnalyst` opens a note by naming the borrower
        through `insured_id`, the producing agency through `producer_agent_id` and
        the governing regime through `state_rule_id`, and by supplying the
        commercial terms: `down_payment_cents` collected in cash before financing,
        a `service_fee_cents` added to the amount financed, an `installment_count`
        of at least 2, and the `first_installment_due_date` on which installment
        number 1 falls."

        Design: Corner/endpoints/standard_crud_agreement_create_read_and_filtered_pagination
        """
        ctx = _tx_regime_context(api)

        created = validate_success(
            api.create_agreement(self._terms(ctx), ANALYST_ORIGIN), 201
        )

        assert created["down_payment_cents"] == 100000
        assert created["service_fee_cents"] == 2000
        assert created["installment_count"] == 6
        assert created["first_installment_due_date"] == "2026-10-01"
        assert created["insured_id"] == ctx["insured_id"]
        assert created["producer_agent_id"] == ctx["agent_id"]
        assert created["state_rule_id"] == ctx["rule_id"]
        assert created["status"] == "DRAFT"
        assert created["delinquency_stage"] == "CURRENT"
        assert created["version"] == 1
        assert is_valid_uuid(created["id"])
        assert is_iso8601_timestamp(created["created_at"])
        assert is_iso8601_timestamp(created["updated_at"])

    def test_the_single_read_returns_exactly_what_was_stored(self, api):
        """Reading the untouched draft back changes nothing and invents nothing.

        The PRD states: "The new note is stamped `DRAFT` in its financing `status`
        and `CURRENT` in its `delinquency_stage`, its `originated_by_user_id` is
        frozen from `X-User-ID` for the later two-person control, and every
        balance, derived money field and counter is zeroed — including
        `total_premium_cents`, `amount_financed_cents`, `effective_annual_rate_bps`,
        `finance_charge_cents`, `total_of_payments_cents`, `principal_balance_cents`,
        `unpaid_finance_charge_cents`, `late_fee_balance_cents`, `late_fee_count`,
        `unapplied_credit_cents`, `unearned_premium_received_cents`,
        `deficiency_balance_cents`, `refund_due_cents`, `agent_chargeback_cents`,
        `policy_count`, `verified_policy_count` and `carried_over_balance_cents` —
        while `quote_basis`, `activated_at`, `restructured_from_agreement_id`,
        `approved_service_fee_cap_cents` and `approved_annual_rate_bps` are all
        null and `rate_exception_approved` is false."

        Design: Corner/endpoints/standard_crud_agreement_create_read_and_filtered_pagination
        """
        ctx = self._three_notes(api)

        read = fixtures.read_agreement(api, ctx["a1"]["id"])

        assert read["id"] == ctx["a1"]["id"]
        assert read["down_payment_cents"] == 100000
        assert read["service_fee_cents"] == 2000
        assert read["installment_count"] == 6
        assert read["first_installment_due_date"] == "2026-10-01"
        assert read["status"] == "DRAFT"
        assert read["version"] == 1
        assert read["insured_id"] == ctx["insured_id"]
        assert read["quote_basis"] is None, "no quote has been struck on this note"
        assert read["total_premium_cents"] == 0, (
            "creation zeroes the premium basis rather than leaving it unset, so a "
            "note that has never been priced reads back a hard zero"
        )
        assert read["policy_count"] == 0
        assert read["created_at"] == ctx["a1"]["created_at"]

    def test_the_three_notes_sit_in_three_distinct_statuses(self, api):
        """One draft, one submitted, one voided — the fixture the filters need.

        The PRD states: "Voiding is permitted only from `DRAFT` or
        `PENDING_VERIFICATION`, and only while no `Payment` row exists against the
        note; the financing status moves to `VOID`, and every policy of the note
        moves to `CANCELLED` with its `cancellation_effective_date` left null,
        because coverage was never pulled — it was never funded."

        Design: Corner/endpoints/standard_crud_agreement_create_read_and_filtered_pagination
        """
        ctx = self._three_notes(api)

        assert ctx["a1"]["status"] == "DRAFT"
        assert ctx["a2_submitted"]["status"] == "PENDING_VERIFICATION"
        assert ctx["a3_voided"]["status"] == "VOID", (
            "the terminal status a void produces is VOID"
        )
        assert fixtures.read_agreement(api, ctx["a1"]["id"])["status"] == "DRAFT"

    def test_the_first_page_reports_the_whole_unfiltered_population(self, api):
        """Two of three rows, with the total and the applied window echoed back.

        The PRD states: "List responses populate four pagination fields inside
        `meta`: the `limit` and `offset` actually applied, `total_count` giving the
        number of rows matching the filters before paging, and `has_more`, which is
        true when rows remain beyond the current page."

        Design: Corner/endpoints/standard_crud_agreement_create_read_and_filtered_pagination
        """
        self._three_notes(api)

        rows, meta = validate_paginated(
            api.list_agreements(COMPLIANCE, {"limit": 2, "offset": 0})
        )

        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

    def test_the_second_page_closes_the_collection(self, api):
        """The remaining row, a false has_more, and a different leading id.

        The PRD states: "Unless a list operation states otherwise, results are
        ordered by `created_at` ascending, so the oldest row appears first and
        paging through the collection is stable."

        Design: Corner/endpoints/standard_crud_agreement_create_read_and_filtered_pagination
        """
        ctx = self._three_notes(api)

        page1, _ = validate_paginated(
            api.list_agreements(COMPLIANCE, {"limit": 2, "offset": 0})
        )
        page2, meta2 = validate_paginated(
            api.list_agreements(COMPLIANCE, {"limit": 2, "offset": 2})
        )

        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert page2[0]["id"] != page1[0]["id"]
        assert {row["id"] for row in page1} | {page2[0]["id"]} == {
            ctx["a1"]["id"],
            ctx["a2"]["id"],
            ctx["a3"]["id"],
        }, "the two pages partition the collection with no row lost or repeated"

    def test_a_status_filter_narrows_the_total_count_not_only_the_page(self, api):
        """total_count counts the filtered population, not the whole book.

        The PRD states: "Every foreign key in the model is reverse-reachable: an
        agreement can be listed by borrower, agency, state regime, restructure
        predecessor, financing status or collection stage; policies by agreement,
        carrier or status; carrier cancellation requests by agreement, policy or
        status; chargebacks by agency, agreement or status."

        Design: Corner/endpoints/standard_crud_agreement_create_read_and_filtered_pagination
        """
        ctx = self._three_notes(api)

        rows, meta = validate_paginated(
            api.list_agreements(COMPLIANCE, {"status": "DRAFT", "limit": 50})
        )

        assert meta["total_count"] == 1, (
            "one of the three notes is still DRAFT, and the page size of 50 could "
            "have returned all three had the filter been ignored"
        )
        assert len(rows) == 1
        assert rows[0]["id"] == ctx["a1"]["id"]
        assert rows[0]["status"] == "DRAFT"

    def test_two_filters_compose_on_the_same_request(self, api):
        """The borrower filter keeps all three; borrower plus status keeps one.

        The PRD states: "Filter parameters on individual list operations are
        documented with the workflows that produce the rows being filtered."

        Design: Corner/endpoints/standard_crud_agreement_create_read_and_filtered_pagination
        """
        ctx = self._three_notes(api)

        _, all_meta = validate_paginated(
            api.list_agreements(
                COMPLIANCE, {"insured_id": ctx["insured_id"], "limit": 50}
            )
        )
        rows, void_meta = validate_paginated(
            api.list_agreements(
                COMPLIANCE,
                {
                    "producer_agent_id": ctx["agent_id"],
                    "status": "VOID",
                    "limit": 50,
                },
            )
        )

        assert all_meta["total_count"] == 3, "all three notes name the same borrower"
        assert void_meta["total_count"] == 1
        assert rows[0]["id"] == ctx["a3"]["id"]
        assert rows[0]["status"] == "VOID"

    def test_a_page_window_outside_its_declared_range_is_a_shape_failure(self, api):
        """limit 0, limit 101 and a negative offset are all request-shape errors.

        The PRD states: "A `limit` outside the closed range from 1 to 100, or a
        negative `offset`, is a request-shape failure and is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/endpoints/standard_crud_agreement_create_read_and_filtered_pagination
        """
        self._three_notes(api)

        validate_error(
            api.list_agreements(COMPLIANCE, {"limit": 0}),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )
        validate_error(
            api.list_agreements(COMPLIANCE, {"limit": 101}),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )
        validate_error(
            api.list_agreements(COMPLIANCE, {"offset": -1}),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

    def test_reading_a_note_that_does_not_exist_is_a_not_found(self, api):
        """A well-formed id that resolves to nothing is a 404, not an empty body.

        The PRD states: "an unknown `agreement_id` yields
        `ERR_AGREEMENT_NOT_FOUND`"

        Design: Corner/endpoints/standard_crud_agreement_create_read_and_filtered_pagination
        """
        self._three_notes(api)

        validate_error(
            api.get_agreement(NON_EXISTENT_UUID, ANALYST_ORIGIN),
            ApiErrorId.AGREEMENT_NOT_FOUND.value,
            404,
        )

    def test_the_note_is_mutated_only_through_named_action_endpoints(self, api):
        """Every post-creation change arrived through a named act and bumped version.

        The PRD states: "`version` starts at 1 when the row is created and
        increases by exactly 1 on every mutation of that row; `updated_at` is
        refreshed to the logical-clock instant on the same mutation."

        Design: Corner/endpoints/standard_crud_agreement_create_read_and_filtered_pagination
        """
        ctx = self._three_notes(api)

        assert fixtures.read_agreement(api, ctx["a1"]["id"])["version"] == 1, (
            "nothing was done to A1 after creation, so its version never moved"
        )
        assert ctx["a2_submitted"]["version"] == 3, (
            "A2 took exactly two named acts after creation: one policy attachment "
            "and one submission"
        )
        assert ctx["a3_voided"]["version"] == 2, (
            "A3 took exactly one named act after creation"
        )
        assert ctx["a3_voided"]["updated_at"] is not None

    def test_the_borrower_row_reads_back_under_the_same_envelope(self, api):
        """The second entity in the fixture answers with the same shape.

        The PRD states: "Borrowers are registered by a `FinanceAnalyst` with a
        non-empty `legal_name`, a `mailing_state_code` of exactly two uppercase
        letters used for addressing statutory notices, and an `email` that must
        contain an at-sign."

        Design: Corner/endpoints/standard_crud_agreement_create_read_and_filtered_pagination
        """
        ctx = self._three_notes(api)

        assert ctx["insured"]["legal_name"] == "Cascade Logistics Inc"
        assert ctx["insured"]["mailing_state_code"] == "TX"
        assert ctx["insured"]["email"] == "ap@cascade.example"
        assert ctx["insured"]["version"] == 1
        assert is_valid_uuid(ctx["insured"]["id"])


class TestServicingRunReportsAggregateCountsAndSkips:
    """Three notes, one eligible: the pass commits the work it may do and steps
    over the rest instead of failing the whole call."""

    def _book(self, api):
        """Note P delinquent-to-be, note Q one installment ahead, note R voided."""
        ctx = _tx_regime_context(api)
        bundle = {"ctx": ctx}
        bundle["p"] = fixtures.active_agreement(
            api,
            ctx=ctx,
            policies=[
                factories.financed_policy(
                    ctx["insurer_id"], policy_number="MC-BK-P"
                )
            ],
        )
        bundle["q"] = fixtures.active_agreement(
            api,
            ctx=ctx,
            policies=[
                factories.financed_policy(
                    ctx["insurer_id"], policy_number="MC-BK-Q"
                )
            ],
        )
        bundle["q_payment"] = validate_success(
            api.create_payment(
                bundle["q"]["agreement_id"],
                factories.payment(89941, "2026-08-15"),
                ANALYST_ORIGIN,
            ),
            201,
        )
        bundle["r"] = validate_success(
            api.create_agreement(
                factories.agreement(
                    ctx["insured_id"], ctx["agent_id"], ctx["rule_id"]
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )
        bundle["r_voided"] = validate_success(
            api.void_agreement(
                bundle["r"]["id"], ANALYST_ORIGIN, {"reason": "duplicate application"}
            ),
            200,
        )
        return bundle

    def _swept(self, api):
        """The book after one pass at 2026-10-12 and a second at the same clock."""
        bundle = self._book(api)
        fixtures.set_clock(api, "2026-10-12T00:00:00Z")
        bundle["run1"] = validate_success(api.run_servicing(COMPLIANCE), 200)
        bundle["run2"] = validate_success(api.run_servicing(COMPLIANCE), 200)
        return bundle

    def test_the_pre_sweep_payment_cleared_one_installment_of_the_second_note(
        self, api
    ):
        """Note Q retires installment 1 exactly, which is what makes it ineligible.

        The PRD states: "Bucket three does the same for `SCHEDULED` installments
        while any money remains, always taking the lowest `installment_number`
        first and retiring finance charge before principal within each."

        Design: Corner/endpoints/bulk_action_servicing_run_reports_aggregate_counts_and_skips_rather_than_rolls_back
        """
        bundle = self._book(api)

        assert bundle["q_payment"]["allocation_variant"] == "STANDARD"
        assert bundle["q_payment"]["applied_finance_charge_cents"] == 6275
        assert bundle["q_payment"]["applied_principal_cents"] == 83666
        assert (
            bundle["q_payment"]["applied_finance_charge_cents"]
            + bundle["q_payment"]["applied_principal_cents"]
            == 89941
        )
        assert bundle["r_voided"]["status"] == "VOID"

    def test_the_aggregate_counters_cover_only_the_note_that_moved(self, api):
        """Three notes in the book, one line of work in the report.

        The PRD states: "The pass reports three counts: `past_due_marked`,
        `late_fees_assessed` and `agreements_advanced_to_late`."

        Design: Corner/endpoints/bulk_action_servicing_run_reports_aggregate_counts_and_skips_rather_than_rolls_back
        """
        self._book(api)
        fixtures.set_clock(api, "2026-10-12T00:00:00Z")

        report = validate_success(api.run_servicing(COMPLIANCE), 200)

        assert report["past_due_marked"] == 1
        assert report["late_fees_assessed"] == 1
        assert report["agreements_advanced_to_late"] == 1

    def test_the_delinquent_note_absorbed_all_of_the_work(self, api):
        """Note P alone takes the stage change, the fee and the counter.

        The PRD states: "The note's `late_fee_count` increases by 1, its
        `late_fee_balance_cents` increases by the fee, and its `version` advances."

        Design: Corner/endpoints/bulk_action_servicing_run_reports_aggregate_counts_and_skips_rather_than_rolls_back
        """
        bundle = self._swept(api)

        note = fixtures.read_agreement(api, bundle["p"]["agreement_id"])
        assert note["delinquency_stage"] == "LATE"
        assert note["late_fee_balance_cents"] == late_fee_cents(89941, 500, 500, 10000)
        assert note["late_fee_balance_cents"] == 4497
        assert note["late_fee_count"] == 1

        rows, meta = validate_paginated(
            api.list_installments(
                bundle["p"]["agreement_id"],
                COMPLIANCE,
                {"status": "PAST_DUE", "limit": 50},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["installment_number"] == 1

    def test_the_paid_ahead_note_was_skipped_and_not_failed(self, api):
        """Note Q's only due installment is PAID, so the pass has nothing to do.

        The PRD states: "Only notes whose financing status is `ACTIVE` are
        considered, and only those whose `delinquency_stage` is `CURRENT`, `LATE` or
        `NOIC_ISSUED`; drafts, pending notes and terminal notes are skipped
        entirely, as are installments already `PAID` or `VOIDED`."

        Design: Corner/endpoints/bulk_action_servicing_run_reports_aggregate_counts_and_skips_rather_than_rolls_back
        """
        bundle = self._swept(api)

        note = fixtures.read_agreement(api, bundle["q"]["agreement_id"])
        assert note["status"] == "ACTIVE"
        assert note["delinquency_stage"] == "CURRENT"
        assert note["late_fee_balance_cents"] == 0
        assert note["late_fee_count"] == 0

        _, fee_meta = validate_paginated(
            api.list_late_fees(
                bundle["q"]["agreement_id"], COMPLIANCE, {"limit": 50}
            )
        )
        assert fee_meta["total_count"] == 0

        rows, paid_meta = validate_paginated(
            api.list_installments(
                bundle["q"]["agreement_id"],
                COMPLIANCE,
                {"status": "PAID", "limit": 50},
            )
        )
        assert paid_meta["total_count"] == 1
        assert rows[0]["installment_number"] == 1
        assert rows[0]["paid_cents"] == 89941

    def test_the_voided_note_was_skipped_because_it_never_became_active(self, api):
        """A terminal note contributes nothing and is left exactly as it was.

        The PRD states: "and `VOID`, `RESTRUCTURED`, `CANCELLED_DEFICIENT` and
        `CLOSED_ZERO` are terminal and accept nothing."

        Design: Corner/endpoints/bulk_action_servicing_run_reports_aggregate_counts_and_skips_rather_than_rolls_back
        """
        bundle = self._swept(api)

        note = fixtures.read_agreement(api, bundle["r"]["id"])
        assert note["status"] == "VOID"
        assert note["delinquency_stage"] == "CURRENT", (
            "the stage is the one creation stamped; a void never touched it"
        )
        assert note["version"] == bundle["r_voided"]["version"], (
            "two passes ran over the book and neither wrote to this row"
        )

        _, meta = validate_paginated(
            api.list_installments(bundle["r"]["id"], COMPLIANCE, {"limit": 50})
        )
        assert meta["total_count"] == 0

    def test_the_ineligible_notes_did_not_roll_back_the_committed_fee(self, api):
        """The one fee the pass could assess survives the two notes it skipped.

        The PRD states: "The new assessment is written with that `amount_cents`, a
        `status` of `OUTSTANDING`, an `assessed_date` equal to the clock date, and
        the `installment_number` of the installment that triggered it — a plain
        integer identifying the position in the schedule, not a reference to the
        installment row."

        Design: Corner/endpoints/bulk_action_servicing_run_reports_aggregate_counts_and_skips_rather_than_rolls_back
        """
        bundle = self._swept(api)

        rows, meta = validate_paginated(
            api.list_late_fees(
                bundle["p"]["agreement_id"], COMPLIANCE, {"limit": 50}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["amount_cents"] == 4497
        assert rows[0]["status"] == "OUTSTANDING"
        assert rows[0]["assessed_date"] == "2026-10-12"
        assert rows[0]["installment_number"] == 1

        _, book_meta = validate_paginated(
            api.list_agreements(COMPLIANCE, {"limit": 50})
        )
        assert book_meta["total_count"] == 3, (
            "all three notes are still in the book; the skipped ones were not "
            "removed and the run was not aborted"
        )

    def test_a_second_pass_at_the_same_clock_is_a_no_op(self, api):
        """Eligibility is judged against row state, not against the calendar.

        The PRD states: "And no late fee may already exist for that agreement and
        that `installment_number` unless the existing one is `REVERSED`, so a single
        installment is charged once no matter how many passes run over it, while a
        fee reversed by a restructure does not block a fresh assessment on the
        successor note."

        Design: Corner/endpoints/bulk_action_servicing_run_reports_aggregate_counts_and_skips_rather_than_rolls_back
        """
        bundle = self._swept(api)

        assert bundle["run2"]["past_due_marked"] == 0
        assert bundle["run2"]["late_fees_assessed"] == 0
        assert bundle["run2"]["agreements_advanced_to_late"] == 0

        note = fixtures.read_agreement(api, bundle["p"]["agreement_id"])
        assert note["late_fee_count"] == 1
        assert note["late_fee_balance_cents"] == 4497
        assert note["delinquency_stage"] == "LATE"


class TestPolicyAttachmentBindsANoteAndACarrierOnBothSides:
    """The one call that names two independent parents: a dangling path id and a
    dangling body id answer with different codes, and the surviving link is
    navigable from either end."""

    def _two_notes(self, api):
        """Two DRAFT notes and two carriers, so both filters have something to
        discriminate against."""
        ctx = _tx_regime_context(api)
        ctx["insurer_b"] = validate_success(
            api.create_insurer(
                factories.insurer(carrier_name="Cordillera Mutual", naic_code="10456"),
                COMPLIANCE,
            ),
            201,
        )
        ctx["insurer_b_id"] = ctx["insurer_b"]["id"]
        ctx["note"] = validate_success(
            api.create_agreement(
                factories.agreement(
                    ctx["insured_id"],
                    ctx["agent_id"],
                    ctx["rule_id"],
                    down_payment_cents=200000,
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )
        ctx["other"] = validate_success(
            api.create_agreement(
                factories.agreement(
                    ctx["insured_id"], ctx["agent_id"], ctx["rule_id"]
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )
        return ctx

    def _three_policies(self, api):
        """MC-XR-1 and CM-XR-2 on the first note, MC-XR-3 on the second."""
        ctx = self._two_notes(api)
        ctx["policy_a"] = validate_success(
            api.attach_policy(
                ctx["note"]["id"],
                factories.financed_policy(
                    ctx["insurer_id"], policy_number="MC-XR-1"
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )
        ctx["policy_b"] = validate_success(
            api.attach_policy(
                ctx["note"]["id"],
                factories.financed_policy(
                    ctx["insurer_b_id"],
                    policy_number="CM-XR-2",
                    gross_premium_cents=400000,
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )
        ctx["policy_c"] = validate_success(
            api.attach_policy(
                ctx["other"]["id"],
                factories.financed_policy(
                    ctx["insurer_id"],
                    policy_number="MC-XR-3",
                    gross_premium_cents=300000,
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )
        return ctx

    def test_a_dangling_path_parent_is_reported_before_the_body_is_inspected(
        self, api
    ):
        """The note in the path decides the error even though the body is perfect.

        The PRD states: "Identifiers in a request path are resolved strictly left to
        right, and the leftmost segment that fails to resolve decides the error."

        Design: Corner/endpoints/cross_reference_link_policy_binds_an_agreement_and_a_carrier_on_both_sides
        """
        ctx = self._two_notes(api)

        validate_error(
            api.attach_policy(
                NON_EXISTENT_UUID,
                factories.financed_policy(
                    ctx["insurer_id"], policy_number="MC-XR-GHOST"
                ),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.AGREEMENT_NOT_FOUND.value,
            404,
        )

    def test_a_dangling_body_parent_reports_the_carrier_instead(self, api):
        """The same call with a real note and a ghost carrier names the carrier.

        The PRD states: "An unresolvable borrower yields `ERR_INSURED_NOT_FOUND`,
        an unresolvable agency `ERR_AGENT_NOT_FOUND`, an unresolvable state regime
        `ERR_STATE_RULE_NOT_FOUND` and an unresolvable carrier
        `ERR_INSURER_NOT_FOUND`, all HTTP 404."

        Design: Corner/endpoints/cross_reference_link_policy_binds_an_agreement_and_a_carrier_on_both_sides
        """
        ctx = self._two_notes(api)

        validate_error(
            api.attach_policy(
                ctx["note"]["id"],
                factories.financed_policy(
                    NON_EXISTENT_UUID, policy_number="MC-XR-GHOST2"
                ),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.INSURER_NOT_FOUND.value,
            404,
        )

    def test_the_link_is_written_on_both_ends_at_once(self, api):
        """One attachment records the note and the carrier on the same row.

        The PRD states: "A successful attachment stamps the policy
        `PENDING_VERIFICATION`, sets `carried_over` to false, provisionally sets
        `financed_premium_cents` equal to `gross_premium_cents`, increments the
        agreement's `policy_count` and advances the agreement's `version`."

        Design: Corner/endpoints/cross_reference_link_policy_binds_an_agreement_and_a_carrier_on_both_sides
        """
        ctx = self._three_policies(api)

        assert ctx["policy_a"]["agreement_id"] == ctx["note"]["id"]
        assert ctx["policy_a"]["insurer_id"] == ctx["insurer_id"]
        assert ctx["policy_a"]["status"] == "PENDING_VERIFICATION"
        assert ctx["policy_a"]["carried_over"] is False
        assert ctx["policy_a"]["financed_premium_cents"] == 600000

    def test_the_single_read_agrees_with_the_attachment(self, api):
        """Reading the policy back returns both parents and the quoted premium.

        The PRD states: "Each attachment names the issuing carrier through
        `insurer_id` and supplies the carrier's `policy_number`, the agency-quoted
        `gross_premium_cents` (which must be strictly positive), the quoted
        `effective_date` and `expiration_date`, an optional `min_earned_days`
        defaulting to 0, and an optional `fully_earned` flag defaulting to false."

        Design: Corner/endpoints/cross_reference_link_policy_binds_an_agreement_and_a_carrier_on_both_sides
        """
        ctx = self._three_policies(api)

        read = fixtures.read_policy(api, ctx["policy_a"]["id"])

        assert read["agreement_id"] == ctx["note"]["id"]
        assert read["insurer_id"] == ctx["insurer_id"]
        assert read["gross_premium_cents"] == 600000
        assert read["policy_number"] == "MC-XR-1"
        assert read["effective_date"] == "2026-09-01"
        assert read["expiration_date"] == "2027-09-01"

    def test_the_link_is_navigable_from_the_note(self, api):
        """Filtering by note returns its two policies and excludes the other note's.

        The PRD states: "policies by agreement, carrier or status"

        Design: Corner/endpoints/cross_reference_link_policy_binds_an_agreement_and_a_carrier_on_both_sides
        """
        ctx = self._three_policies(api)

        rows, meta = validate_paginated(
            api.list_policies(
                ANALYST_ORIGIN, {"agreement_id": ctx["note"]["id"], "limit": 50}
            )
        )

        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {
            ctx["policy_a"]["id"],
            ctx["policy_b"]["id"],
        }
        assert ctx["policy_c"]["id"] not in {row["id"] for row in rows}, (
            "the third policy hangs off the other note"
        )

    def test_the_link_is_navigable_from_the_carrier(self, api):
        """Filtering by carrier crosses note boundaries and excludes the rival.

        The PRD states: "Every foreign key in the model is reverse-reachable: an
        agreement can be listed by borrower, agency, state regime, restructure
        predecessor, financing status or collection stage; policies by agreement,
        carrier or status; carrier cancellation requests by agreement, policy or
        status; chargebacks by agency, agreement or status."

        Design: Corner/endpoints/cross_reference_link_policy_binds_an_agreement_and_a_carrier_on_both_sides
        """
        ctx = self._three_policies(api)

        rows, meta = validate_paginated(
            api.list_policies(
                ANALYST_ORIGIN, {"insurer_id": ctx["insurer_id"], "limit": 50}
            )
        )

        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {
            ctx["policy_a"]["id"],
            ctx["policy_c"]["id"],
        }
        assert ctx["policy_b"]["id"] not in {row["id"] for row in rows}, (
            "the second policy names the other carrier"
        )

    def test_the_two_filters_intersect_rather_than_union(self, api):
        """Note plus carrier picks out the single row that satisfies both.

        The PRD states: "Filter parameters on individual list operations are
        documented with the workflows that produce the rows being filtered."

        Design: Corner/endpoints/cross_reference_link_policy_binds_an_agreement_and_a_carrier_on_both_sides
        """
        ctx = self._three_policies(api)

        rows, meta = validate_paginated(
            api.list_policies(
                ANALYST_ORIGIN,
                {
                    "agreement_id": ctx["note"]["id"],
                    "insurer_id": ctx["insurer_b_id"],
                    "limit": 50,
                },
            )
        )

        assert meta["total_count"] == 1
        assert rows[0]["id"] == ctx["policy_b"]["id"]
        assert rows[0]["insurer_id"] == ctx["insurer_b_id"]
        assert rows[0]["gross_premium_cents"] == 400000

    def test_the_derived_counter_followed_the_link(self, api):
        """policy_count walks 0 to 2 while nothing has been attested yet.

        The PRD states: "In that case the agreed figures are stamped as
        `verified_premium_cents` and `verified_effective_date`,
        `financed_premium_cents` is recomputed as `verified_premium_cents` plus
        `endorsed_premium_cents`, the agreement's `verified_policy_count` increases
        by 1, and the policy's `version` advances."

        Design: Corner/endpoints/cross_reference_link_policy_binds_an_agreement_and_a_carrier_on_both_sides
        """
        ctx = self._three_policies(api)

        assert ctx["note"]["policy_count"] == 0, "the counter was zero at creation"

        note = fixtures.read_agreement(api, ctx["note"]["id"])
        assert note["policy_count"] == 2
        assert note["verified_policy_count"] == 0

    def test_the_third_party_named_on_the_note_was_not_disturbed(self, api):
        """Linking policies leaves the producing agency exactly as onboarded.

        The PRD states: "On creation, `chargeback_reserve_balance_cents` is set to
        the supplied initial reserve, `outstanding_chargeback_cents` is set to 0,
        and `status` is set to `ACTIVE`."

        Design: Corner/endpoints/cross_reference_link_policy_binds_an_agreement_and_a_carrier_on_both_sides
        """
        ctx = self._three_policies(api)

        agent = validate_success(api.get_agent(ctx["agent_id"], ANALYST_ORIGIN), 200)

        assert agent["status"] == "ACTIVE"
        assert agent["outstanding_chargeback_cents"] == 0
        assert agent["chargeback_reserve_balance_cents"] == 100000


class TestPayoffQuoteRecomputesFromTheLedgerWithoutTouchingIt:
    """Seven fields, every one of them derivable by hand from the note, and not
    one write on the row that produced them."""

    def _active(self, api):
        """The 600k note ACTIVE at 2026-08-15 with nothing yet paid."""
        return fixtures.canonical_600k_note(api, policy_number="MC-PQ-1")

    def _paid(self, api):
        """The same note after one 179882 tender retired installments 1 and 2."""
        bundle = self._active(api)
        bundle["quote_untouched"] = validate_success(
            api.get_payoff_quote(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )
        bundle["payment"] = validate_success(
            api.create_payment(
                bundle["agreement_id"],
                factories.payment(179882, "2026-08-15"),
                ANALYST_ORIGIN,
            ),
            201,
        )
        return bundle

    def _swept(self, api):
        """The note carried to 2026-12-12, where installment 3 earns one fee."""
        bundle = self._paid(api)
        fixtures.set_clock(api, "2026-12-12T00:00:00Z")
        bundle["run"] = validate_success(api.run_servicing(COMPLIANCE), 200)
        return bundle

    def test_the_quote_on_an_untouched_note_is_degenerate(self, api):
        """With no installment retired the whole finance charge is rebated back.

        The PRD states: "Under the `RULE_OF_78` method, the rebate is
        `finance_charge_cents` multiplied by *r*, multiplied by *r* plus one,
        divided by the product of `installment_count` and `installment_count` plus
        one, rounded half up — the sum-of-digits curve, which front-loads finance
        charge and therefore rebates *less* than a straight-line schedule actually
        allocated to the unpaid tail."

        Design: Corner/endpoints/computed_read_payoff_quote_recomputes_from_the_ledger_without_touching_it
        """
        bundle = self._paid(api)

        assert bundle["activated"]["finance_charge_cents"] == 37650
        assert bundle["activated"]["total_of_payments_cents"] == 539650

        quote = bundle["quote_untouched"]
        assert quote["gross_balance_cents"] == 539650
        assert quote["unearned_finance_charge_rebate_cents"] == 37650, (
            "r equals the installment count, so the sum-of-digits factor is 1 and "
            "the rebate is the entire finance charge"
        )
        assert quote["net_payoff_cents"] == 502000, (
            "closing an untouched note out costs exactly the amount financed"
        )

    def test_the_setup_payment_used_the_ordinary_waterfall(self, api):
        """179882 is below the net payoff, so no rebate is granted.

        The PRD states: "Allocation begins by choosing a variant, and the choice is
        made *before* any money moves: the payment runs as the `PAYOFF` variant when
        the tendered `amount_cents` is greater than or equal to the net payoff
        computed as of `received_date`, and as the `STANDARD` variant otherwise."

        Design: Corner/endpoints/computed_read_payoff_quote_recomputes_from_the_ledger_without_touching_it
        """
        bundle = self._paid(api)

        assert bundle["payment"]["allocation_variant"] == "STANDARD", (
            "179882 falls short of the 502000 net payoff"
        )
        assert bundle["payment"]["applied_finance_charge_cents"] == 12550 == 6275 * 2
        assert bundle["payment"]["applied_principal_cents"] == 167332 == 83666 * 2
        assert bundle["payment"]["rebate_applied_cents"] == 0

    def test_the_ledger_after_the_payment_is_the_quotes_only_input(self, api):
        """Two installments PAID, and the two balances the quote will consume.

        The PRD states: "Let *r* be the number of installments not yet retired:
        `installment_count` minus the count of the note's installments whose
        `status` is `PAID`."

        Design: Corner/endpoints/computed_read_payoff_quote_recomputes_from_the_ledger_without_touching_it
        """
        bundle = self._paid(api)

        note = fixtures.read_agreement(api, bundle["agreement_id"])
        assert note["principal_balance_cents"] == 334668 == 502000 - 167332
        assert note["unpaid_finance_charge_cents"] == 25100 == 37650 - 12550

        rows, meta = validate_paginated(
            api.list_installments(
                bundle["agreement_id"],
                ANALYST_ORIGIN,
                {"status": "PAID", "limit": 50},
            )
        )
        assert meta["total_count"] == 2
        assert min(row["installment_number"] for row in rows) == 1

    def test_every_quote_field_derives_by_hand_from_the_note(self, api):
        """Gross, rebate, fees, credit and net all reconcile to the ledger.

        The PRD states: "This computed read accepts an optional `as_of_date`,
        defaulting to the clock date, and returns that `as_of_date`, the
        `gross_balance_cents` (the note's `principal_balance_cents` plus its
        `unpaid_finance_charge_cents`), the `unearned_finance_charge_rebate_cents`
        the borrower would be granted, the `outstanding_late_fee_cents` still owed,
        the `unapplied_credit_cents` sitting in suspense, the resulting
        `net_payoff_cents`, and the `rebate_method` under which the figure was
        computed."

        Design: Corner/endpoints/computed_read_payoff_quote_recomputes_from_the_ledger_without_touching_it
        """
        bundle = self._paid(api)

        quote = validate_success(
            api.get_payoff_quote(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )

        assert quote["gross_balance_cents"] == 359768 == 334668 + 25100
        assert quote["unearned_finance_charge_rebate_cents"] == 17929, (
            "r is 6 minus 2, so 37650 * 4 * 5 / 42 is 17928.571 and rounds half up"
        )
        assert quote["outstanding_late_fee_cents"] == 0
        assert quote["unapplied_credit_cents"] == 0
        assert quote["net_payoff_cents"] == 341839 == 359768 - 17929
        assert quote["as_of_date"] == "2026-08-15", "the default is the clock date"
        assert quote["rebate_method"] == "RULE_OF_78"
        assert quote["rebate_method"] == bundle["rule"]["rebate_method"]

    def test_the_as_of_date_is_echoed_and_not_consumed(self, api):
        """A month of calendar drift moves the echoed date and not one cent.

        The PRD states: "The net payoff is then `principal_balance_cents` plus
        `unpaid_finance_charge_cents`, minus the rebate, plus
        `late_fee_balance_cents`, minus `unapplied_credit_cents`."

        Design: Corner/endpoints/computed_read_payoff_quote_recomputes_from_the_ledger_without_touching_it
        """
        bundle = self._paid(api)

        today = validate_success(
            api.get_payoff_quote(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )
        later = validate_success(
            api.get_payoff_quote(
                bundle["agreement_id"], COMPLIANCE, {"as_of_date": "2026-09-15"}
            ),
            200,
        )

        assert later["as_of_date"] == "2026-09-15"
        assert later["gross_balance_cents"] == today["gross_balance_cents"] == 359768
        assert (
            later["unearned_finance_charge_rebate_cents"]
            == today["unearned_finance_charge_rebate_cents"]
            == 17929
        ), "under this method the rebate counts paid installments, not months"
        assert later["net_payoff_cents"] == today["net_payoff_cents"] == 341839

    def test_the_quote_is_read_only_even_though_it_runs_a_calculation(self, api):
        """Three quotes in a row leave version, balances and status untouched.

        The PRD states: "Every other operation, including every read, every state
        transition on an existing resource, the servicing run and the clock control,
        returns `200 OK`."

        Design: Corner/endpoints/computed_read_payoff_quote_recomputes_from_the_ledger_without_touching_it
        """
        bundle = self._paid(api)
        before = fixtures.read_agreement(api, bundle["agreement_id"])

        for _ in range(3):
            validate_success(
                api.get_payoff_quote(bundle["agreement_id"], ANALYST_ORIGIN), 200
            )

        after = fixtures.read_agreement(api, bundle["agreement_id"])
        assert after["version"] == before["version"]
        assert after["principal_balance_cents"] == 334668
        assert after["unpaid_finance_charge_cents"] == 25100
        assert after["status"] == "ACTIVE"
        assert after["updated_at"] == before["updated_at"]

    def test_the_sweep_assesses_one_fee_past_the_grace_period(self, api):
        """Installment 3 is one day past its ten-day grace on 2026-12-12.

        The PRD states: "Then, if an installment is `PAST_DUE` and the clock date is
        *strictly after* its `due_date` advanced by the regime's
        `grace_period_days`, a late fee may be assessed against it."

        Design: Corner/endpoints/computed_read_payoff_quote_recomputes_from_the_ledger_without_touching_it
        """
        bundle = self._swept(api)

        assert bundle["run"]["late_fees_assessed"] == 1

        rows, meta = validate_paginated(
            api.list_late_fees(bundle["agreement_id"], COMPLIANCE, {"limit": 50})
        )
        assert meta["total_count"] == 1
        assert rows[0]["installment_number"] == 3, (
            "installments 1 and 2 are PAID, so the third one is the first that can "
            "fall past due"
        )
        assert rows[0]["amount_cents"] == 4497

    def test_the_fee_flows_into_its_own_quote_line_not_into_the_rebate(self, api):
        """Delinquency raises the net payoff without unexpiring the term.

        The PRD states: "Whichever method applies, the rebate is finally capped at
        the note's `unpaid_finance_charge_cents`, so a rebate can never create
        finance charge that was never owed."

        Design: Corner/endpoints/computed_read_payoff_quote_recomputes_from_the_ledger_without_touching_it
        """
        bundle = self._swept(api)

        quote = validate_success(
            api.get_payoff_quote(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )

        assert quote["outstanding_late_fee_cents"] == 4497
        assert quote["gross_balance_cents"] == 359768, "no balance moved"
        assert quote["unearned_finance_charge_rebate_cents"] == 17929, (
            "two installments are still PAID and none was added, so r is still 4"
        )
        assert quote["net_payoff_cents"] == 346336 == 359768 - 17929 + 4497
        assert quote["as_of_date"] == "2026-12-12", "the default tracks the clock"


class TestEndorsementFinancingRequiresAPendingEndorsement:
    """The gate on this action is a population, not a status: the same call is
    refused, refused again, and then accepted against a note that never left
    ACTIVE."""

    def _active(self, api):
        """The 600k note ACTIVE and CURRENT with one VERIFIED policy."""
        bundle = fixtures.canonical_600k_note(api, policy_number="MC-CA-1")
        bundle["version_before"] = bundle["activated"]["version"]
        return bundle

    def _finance(self, api, bundle, version):
        return api.finance_endorsements(
            bundle["agreement_id"],
            {"expected_agreement_version": version},
            ANALYST_ORIGIN,
        )

    def _declined(self, api):
        """One amendment filed and immediately killed, so a dead row exists."""
        bundle = self._active(api)
        bundle["first"] = validate_success(
            api.create_endorsement(
                bundle["policy_id"],
                factories.endorsement(60000, effective_date="2026-09-15"),
                ANALYST_ORIGIN,
            ),
            201,
        )
        bundle["first_declined"] = validate_success(
            api.decline_endorsement(
                bundle["first"]["id"],
                ANALYST_ORIGIN,
                factories.decline_reason(reason="carrier withdrew the amendment"),
            ),
            200,
        )
        return bundle

    def _financed(self, api):
        """A second amendment, still PENDING, folded into the note."""
        bundle = self._declined(api)
        bundle["version_after_refusals"] = fixtures.agreement_version(
            api, bundle["agreement_id"]
        )
        bundle["second"] = validate_success(
            api.create_endorsement(
                bundle["policy_id"],
                factories.endorsement(60000, effective_date="2026-09-15"),
                ANALYST_ORIGIN,
            ),
            201,
        )
        bundle["financed"] = validate_success(
            self._finance(api, bundle, bundle["version_after_refusals"]), 200
        )
        return bundle

    def test_the_population_gate_is_checked_before_the_concurrency_token(self, api):
        """A correct expected version does not help when no amendment exists.

        The PRD states: "42. At least one pending endorsement exists to finance —
        otherwise `ERR_NO_PENDING_ENDORSEMENTS`, on endorsement financing."

        Design: Corner/endpoints/conditional_action_endorsement_financing_requires_a_pending_endorsement
        """
        bundle = self._active(api)

        validate_error(
            self._finance(api, bundle, bundle["version_before"]),
            ApiErrorId.NO_PENDING_ENDORSEMENTS.value,
            422,
        )

    def test_the_amendment_is_born_pending_with_a_signed_amount(self, api):
        """An additional premium carries its own amount, positive, and waits.

        The PRD states: "The endorsement lands in `PENDING` status with a derived
        `signed_amount_cents` that carries the direction of the change: the amount
        itself for an `ADDITIONAL_PREMIUM`, and the amount negated for a
        `RETURN_PREMIUM`."

        Design: Corner/endpoints/conditional_action_endorsement_financing_requires_a_pending_endorsement
        """
        bundle = self._declined(api)

        assert bundle["first"]["status"] == "PENDING"
        assert bundle["first"]["signed_amount_cents"] == 60000
        assert bundle["first"]["endorsement_type"] == "ADDITIONAL_PREMIUM"
        assert bundle["first"]["policy_id"] == bundle["policy_id"]

    def test_an_endorsement_that_exists_but_is_dead_does_not_satisfy_the_gate(
        self, api
    ):
        """Existence is not eligibility: the DECLINED row leaves the gate shut.

        The PRD states: "A `DECLINED` endorsement never enters the financed
        premium."

        Design: Corner/endpoints/conditional_action_endorsement_financing_requires_a_pending_endorsement
        """
        bundle = self._declined(api)

        assert bundle["first_declined"]["status"] == "DECLINED"
        version = fixtures.agreement_version(api, bundle["agreement_id"])

        validate_error(
            self._finance(api, bundle, version),
            ApiErrorId.NO_PENDING_ENDORSEMENTS.value,
            422,
        )

    def test_the_two_refusals_left_the_note_exactly_as_it_was(self, api):
        """No version movement, no balance movement, no status movement.

        The PRD states: "Folding the pending endorsements into the note is a
        separate, deliberate act by a `FinanceAnalyst`, permitted only while the
        note's financing status is `ACTIVE` and its `delinquency_stage` is `CURRENT`
        — a delinquent account is not re-financed, it is restructured."

        Design: Corner/endpoints/conditional_action_endorsement_financing_requires_a_pending_endorsement
        """
        bundle = self._declined(api)
        validate_error(
            self._finance(api, bundle, bundle["version_before"]),
            ApiErrorId.NO_PENDING_ENDORSEMENTS.value,
            422,
        )

        note = fixtures.read_agreement(api, bundle["agreement_id"])
        assert note["version"] == bundle["version_before"], (
            "filing and declining an amendment writes only the endorsement row"
        )
        assert note["status"] == "ACTIVE"
        assert note["delinquency_stage"] == "CURRENT"
        assert note["principal_balance_cents"] == 502000
        assert note["unpaid_finance_charge_cents"] == 37650

    def test_a_single_pending_amendment_unblocks_the_same_call(self, api):
        """The third attempt differs only in the population behind it.

        The PRD states: "Every qualifying endorsement then moves `PENDING` →
        `FINANCED` and has its `financed_at` stamped from the logical clock."

        Design: Corner/endpoints/conditional_action_endorsement_financing_requires_a_pending_endorsement
        """
        bundle = self._financed(api)

        assert bundle["second"]["status"] == "PENDING"
        assert bundle["financed"]["status"] == "ACTIVE", (
            "the note never left ACTIVE across the three attempts"
        )

    def test_the_reprice_over_the_new_basis_is_exact(self, api):
        """The whole quote is rebuilt from a premium basis 60000 higher.

        The PRD states: "The note is then repriced in the pricing engine's final
        variant over that new basis, which can move `total_premium_cents`,
        `amount_financed_cents`, the volume tier, `effective_annual_rate_bps`,
        `finance_charge_cents` and `total_of_payments_cents`, and the schedule is
        rebuilt over the unpaid tail only."

        Design: Corner/endpoints/conditional_action_endorsement_financing_requires_a_pending_endorsement
        """
        bundle = self._financed(api)
        financed = bundle["financed"]

        assert financed["total_premium_cents"] == 660000 == 600000 + 60000
        assert financed["amount_financed_cents"] == 562000 == 660000 - 100000 + 2000
        assert financed["effective_annual_rate_bps"] == 1500, (
            "562000 still sits in the second volume tier, and 1500 is inside the "
            "1800 statutory ceiling"
        )
        assert financed["finance_charge_cents"] == add_on_finance_charge_cents(
            562000, 1500, 6
        ) == 42150
        assert financed["total_of_payments_cents"] == 604150 == 562000 + 42150
        assert financed["principal_balance_cents"] == 562000
        assert financed["unpaid_finance_charge_cents"] == 42150

    def test_the_schedule_was_rebuilt_over_the_six_untouched_installments(self, api):
        """Nothing was paid, so the whole schedule is the tail and it absorbs it.

        The PRD states: "Installments whose `status` is `PAID` or `VOIDED` are frozen
        and are not recomputed; the new `total_of_payments_cents` less the amounts
        already paid is redistributed across the installments whose `status` is
        `SCHEDULED` or `PAST_DUE`, taken in ascending `installment_number` order,
        applying the same discipline as a fresh schedule to that tail — truncate the
        per-installment share for every installment of the tail except the last one,
        and give the last installment of the tail the exact arithmetic remainder, so
        the tail sums to the redistributed total with no drift."

        Design: Corner/endpoints/conditional_action_endorsement_financing_requires_a_pending_endorsement
        """
        bundle = self._financed(api)

        rows, meta = validate_paginated(
            api.list_installments(
                bundle["agreement_id"], ANALYST_ORIGIN, {"limit": 50}
            )
        )
        assert meta["total_count"] == 6, "the tail is rebuilt, never lengthened"
        rows.sort(key=lambda row: row["installment_number"])

        for row in rows[:5]:
            assert row["amount_cents"] == 100691
            assert row["finance_charge_component_cents"] == 7025
            assert row["principal_component_cents"] == 93666
            assert row["status"] == "SCHEDULED"
        assert rows[5]["amount_cents"] == 100695, (
            "the last installment of the tail takes the four-cent remainder"
        )
        assert rows[5]["finance_charge_component_cents"] == 7025
        assert rows[5]["principal_component_cents"] == 93670
        assert_installments_sum(rows, 604150, 42150)

    def test_only_the_pending_amendment_moved(self, api):
        """One row is FINANCED and stamped, the other stays DECLINED and unstamped.

        The PRD states: "Endorsements of a policy may be listed and filtered by
        `status`."

        Design: Corner/endpoints/conditional_action_endorsement_financing_requires_a_pending_endorsement
        """
        bundle = self._financed(api)

        financed_rows, financed_meta = validate_paginated(
            api.list_endorsements(
                bundle["policy_id"], ANALYST_ORIGIN, {"status": "FINANCED", "limit": 50}
            )
        )
        declined_rows, declined_meta = validate_paginated(
            api.list_endorsements(
                bundle["policy_id"], ANALYST_ORIGIN, {"status": "DECLINED", "limit": 50}
            )
        )

        assert financed_meta["total_count"] == 1
        assert financed_rows[0]["id"] == bundle["second"]["id"]
        assert financed_rows[0]["financed_at"] is not None
        assert declined_meta["total_count"] == 1
        assert declined_rows[0]["id"] == bundle["first"]["id"]
        assert declined_rows[0]["financed_at"] is None

    def test_the_policy_accumulated_the_signed_amount_without_leaving_verified(
        self, api
    ):
        """The premium the note now finances is the attested figure plus the amendment.

        The PRD states: "Each affected policy's `endorsed_premium_cents` becomes the
        sum of `signed_amount_cents` over its `FINANCED` endorsements — so a return
        premium reduces it — and its `financed_premium_cents` is re-derived as
        `verified_premium_cents` plus `endorsed_premium_cents`."

        Design: Corner/endpoints/conditional_action_endorsement_financing_requires_a_pending_endorsement
        """
        bundle = self._financed(api)

        policy = fixtures.read_policy(api, bundle["policy_id"])
        assert policy["endorsed_premium_cents"] == 60000, (
            "only the FINANCED amendment counts; the DECLINED one contributes nothing"
        )
        assert policy["financed_premium_cents"] == 660000 == 600000 + 60000
        assert policy["status"] == "VERIFIED"

    def test_exactly_one_write_landed_across_the_three_attempts(self, api):
        """Two refusals wrote nothing and the acceptance advanced the note once.

        The PRD states: "The note's `principal_balance_cents` and
        `unpaid_finance_charge_cents` are adjusted by the deltas the repricing
        produced, and its `version` advances."

        Design: Corner/endpoints/conditional_action_endorsement_financing_requires_a_pending_endorsement
        """
        bundle = self._financed(api)

        assert bundle["version_after_refusals"] == bundle["version_before"]
        assert bundle["financed"]["version"] == bundle["version_before"] + 1
        assert (
            fixtures.agreement_version(api, bundle["agreement_id"])
            == bundle["version_before"] + 1
        )

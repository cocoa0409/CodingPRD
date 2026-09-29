"""Drafting, executing, amending and certifying the disclosure agreement.

PRD §3.4 gates the agreement at four separate moments — the eligibility
screens at drafting, the segregation and window checks at execution, the
staleness check at amendment, and the three ordered gates at certification.
"""

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_ONE_HEADERS,
    CANONICAL_AGREEMENT_LOOKBACK_END,
    CANONICAL_CLOCK,
    CANONICAL_CLOCK_RENDERED,
    CANONICAL_LAST_INSTANT_INSIDE_WINDOW,
    CANONICAL_TOTAL_DUE_CENTS,
    CANONICAL_WINDOW_CLOSE_AT,
    DEFAULT_PROSPECTIVE_COMPLIANCE_MONTHS,
    OFFICER_ALPHA_HEADERS,
    OFFICER_BETA_HEADERS,
    OFFICER_BETA_USER_ID,
    OFFICER_GAMMA_HEADERS,
    ApiErrorId,
    add_taxpayer,
    agreement_payload,
    amend_payload,
    assert_fields,
    assert_list_total,
    draft_agreement,
    draft_return,
    file_return,
    open_enforcement_case,
    read_agreement,
    read_program,
    read_taxpayer,
    remit_payment,
    rescind_breach_payload,
    set_clock,
    setup_accepted_pre_clearance,
    setup_executed_agreement,
    setup_program_with_taxpayer,
    validate_error,
    validate_success,
)

UNKNOWN_PROGRAM_ID = "00000000-0000-4000-8000-000000000002"
UNKNOWN_TAXPAYER_ID = "00000000-0000-4000-8000-000000000003"
NEGOTIATED_OFFER = {
    "offered_lookback_months": 36,
    "offered_penalty_waiver_pct": 1.00,
    "offered_interest_waiver_pct": 0.50,
}


class TestDraftingForeignKeys:
    """Body foreign keys resolve in declared order (PRD §2.5)."""

    def test_the_first_unresolvable_body_key_decides_the_not_found(self, api):
        """`program_id` is declared before `taxpayer_id`, so it reports first.

        PRD §2.5: "Foreign keys supplied inside a request body are resolved
        after path identifiers, in the order the fields are declared for that
        operation, and an unresolvable one produces the corresponding 404 from
        the same family."

        Design: Corner/Table 1 Entities/agreement_body_foreign_keys_are_checked_in_declared_order_not_found
        """
        set_clock(api, CANONICAL_CLOCK)

        validate_error(
            api.create_agreement(
                agreement_payload(UNKNOWN_PROGRAM_ID, UNKNOWN_TAXPAYER_ID),
                OFFICER_ALPHA_HEADERS,
            ),
            ApiErrorId.PROGRAM_NOT_FOUND,
        )
        assert_list_total(api.list_agreements(ADMIN_HEADERS), 0)


class TestLookbackLimit:
    """The program's limitation bounds every agreement's lookback (PRD §3.4)."""

    def test_the_earliest_admissible_lookback_start_is_accepted(self, api):
        """The limit is inclusive at `window_open_at` shifted back 36 months.

        PRD §3.4: "The lookback bounds must respect the program's limitation:
        `lookback_start_date` may not precede the calendar date of
        `window_open_at` shifted back by `lookback_months` whole months, and
        `lookback_end_date` may not precede `lookback_start_date`; a violation
        of either is `ERR_LOOKBACK_EXCEEDS_PROGRAM_LIMIT`."

        PRD §3.4: "`prospective_compliance_months` overrides the commitment
        length, and when omitted it is copied from the program's
        `prospective_compliance_months`."

        Design: Corner/Table 4 Validations/lookback_limit_is_inclusive_at_the_thirty_six_month_boundary
        """
        ctx = setup_program_with_taxpayer(
            api,
            taxpayer_overrides={
                "legal_name": "Pennyroyal Botanicals LLC",
                "tin_last4": "7714",
            },
        )

        validate_error(
            api.create_agreement(
                agreement_payload(
                    ctx["program"]["id"],
                    ctx["taxpayer"]["id"],
                    lookback_start_date="2023-08-31",
                ),
                OFFICER_ALPHA_HEADERS,
            ),
            ApiErrorId.LOOKBACK_EXCEEDS_PROGRAM_LIMIT,
        )

        agreement = draft_agreement(api, ctx, lookback_start_date="2023-09-01")
        assert_fields(
            agreement,
            lookback_start_date="2023-09-01",
            prospective_compliance_months=DEFAULT_PROSPECTIVE_COMPLIANCE_MONTHS,
        )
        assert_list_total(
            api.list_agreements(ADMIN_HEADERS, {"program_id": ctx["program"]["id"]}), 1
        )

    def test_an_end_date_before_the_start_date_is_refused(self, api):
        """The same error covers inverted bounds.

        PRD §3.4: "`lookback_end_date` may not precede `lookback_start_date`; a
        violation of either is `ERR_LOOKBACK_EXCEEDS_PROGRAM_LIMIT`."

        Design: Corner/Table 4 Validations/lookback_limit_is_inclusive_at_the_thirty_six_month_boundary
        """
        ctx = setup_program_with_taxpayer(
            api,
            taxpayer_overrides={
                "legal_name": "Pennyroyal Botanicals LLC",
                "tin_last4": "7714",
            },
        )

        validate_error(
            api.create_agreement(
                agreement_payload(
                    ctx["program"]["id"],
                    ctx["taxpayer"]["id"],
                    lookback_start_date="2024-01-01",
                    lookback_end_date="2023-12-31",
                ),
                OFFICER_ALPHA_HEADERS,
            ),
            ApiErrorId.LOOKBACK_EXCEEDS_PROGRAM_LIMIT,
        )
        assert_list_total(
            api.list_agreements(ADMIN_HEADERS, {"program_id": ctx["program"]["id"]}), 0
        )


class TestEligibilityScreensAtDrafting:
    """Two exclusions and one identity match, in the PRD's declared order."""

    def test_the_criminal_screen_reports_before_the_pre_clearance_identity_match(
        self, api
    ):
        """Both rules are violated at once and the earlier one answers.

        PRD §2.6: "When more than one rule would reject a request, the rules are
        evaluated in strictly ascending precedence order and the **first**
        violation decides the response."

        PRD §3.4: "a taxpayer with an `OPEN` `CRIMINAL_INVESTIGATION` case is
        excluded outright with `ERR_TAXPAYER_UNDER_CRIMINAL_INVESTIGATION`"

        PRD §3.4: "its `disclosed_taxpayer_id` must equal the agreement's
        `taxpayer_id` (`ERR_PRECLEARANCE_TAXPAYER_MISMATCH`)"

        Design: Difficulty/priority_pair_validation_conflict/criminal_investigation_screen_precedes_preclearance_identity_match
        """
        ctx = setup_program_with_taxpayer(
            api,
            taxpayer_overrides={
                "legal_name": "Redstone Aggregate Inc",
                "tin_last4": "3318",
            },
        )
        redstone_id = ctx["taxpayer"]["id"]
        lakeview = add_taxpayer(
            api, ctx, legal_name="Lakeview Provisioning LLC", tin_last4="7745"
        )
        open_enforcement_case(
            api,
            redstone_id,
            case_type="CRIMINAL_INVESTIGATION",
            tax_type="SALES_USE",
            opened_at="2026-02-11",
        )
        pre_clearance = setup_accepted_pre_clearance(
            api,
            ctx,
            taxpayer_id=lakeview["id"],
            pre_clearance_overrides={
                "anonymous_alias": "CLIENT-64",
                "estimated_liability_cents": 700000,
                "earliest_unfiled_period_start": "2024-07-01",
            },
            offer_overrides=NEGOTIATED_OFFER,
        )

        response = api.create_agreement(
            agreement_payload(
                ctx["program"]["id"],
                redstone_id,
                pre_clearance_id=pre_clearance["id"],
            ),
            OFFICER_ALPHA_HEADERS,
        )
        validate_error(response, ApiErrorId.TAXPAYER_UNDER_CRIMINAL_INVESTIGATION)
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.PRECLEARANCE_TAXPAYER_MISMATCH
        )

        assert_list_total(
            api.list_agreements(ADMIN_HEADERS, {"taxpayer_id": redstone_id}), 0
        )
        assert_fields(
            pre_clearance, status="ACCEPTED", disclosed_taxpayer_id=lakeview["id"]
        )

    def test_the_identity_match_answers_once_the_criminal_screen_is_clear(self, api):
        """With no blocking case the masked rule is the one that fires.

        PRD §3.4: "When a `pre_clearance_id` is supplied, that request's `status`
        must be `ACCEPTED` (`ERR_PRECLEARANCE_NOT_ACCEPTED`) and its
        `disclosed_taxpayer_id` must equal the agreement's `taxpayer_id`
        (`ERR_PRECLEARANCE_TAXPAYER_MISMATCH`) — the department will not let a
        representative's accepted terms be transplanted onto a different
        taxpayer."

        Design: Difficulty/priority_pair_validation_conflict/criminal_investigation_screen_precedes_preclearance_identity_match
        """
        ctx = setup_program_with_taxpayer(
            api,
            taxpayer_overrides={
                "legal_name": "Redstone Aggregate Inc",
                "tin_last4": "3318",
            },
        )
        redstone_id = ctx["taxpayer"]["id"]
        lakeview = add_taxpayer(
            api, ctx, legal_name="Lakeview Provisioning LLC", tin_last4="7745"
        )
        pre_clearance = setup_accepted_pre_clearance(
            api,
            ctx,
            taxpayer_id=lakeview["id"],
            pre_clearance_overrides={
                "anonymous_alias": "CLIENT-64",
                "estimated_liability_cents": 700000,
                "earliest_unfiled_period_start": "2024-07-01",
            },
            offer_overrides=NEGOTIATED_OFFER,
        )

        validate_error(
            api.create_agreement(
                agreement_payload(
                    ctx["program"]["id"],
                    redstone_id,
                    pre_clearance_id=pre_clearance["id"],
                ),
                OFFICER_ALPHA_HEADERS,
            ),
            ApiErrorId.PRECLEARANCE_TAXPAYER_MISMATCH,
        )
        assert_list_total(
            api.list_agreements(ADMIN_HEADERS, {"taxpayer_id": redstone_id}), 0
        )

    def test_an_open_criminal_case_blocks_drafting_while_it_stands(self, api):
        """The exclusion is evaluated against live case state, not history.

        PRD §3.4: "a taxpayer with an `OPEN` `CRIMINAL_INVESTIGATION` case is
        excluded outright with `ERR_TAXPAYER_UNDER_CRIMINAL_INVESTIGATION`"

        PRD §3.2: "It starts from a base of 100 and then subtracts 20 points for
        each enforcement case of that taxpayer whose status is `OPEN`"

        Design: Difficulty/cross_entity_state_dependency/open_criminal_case_gates_agreement_drafting_until_closed
        """
        ctx = setup_program_with_taxpayer(
            api,
            taxpayer_overrides={
                "legal_name": "Granite Fork Quarry LLC",
                "tin_last4": "5590",
            },
        )
        open_enforcement_case(
            api,
            ctx["taxpayer"]["id"],
            case_type="CRIMINAL_INVESTIGATION",
            tax_type="SALES_USE",
            opened_at="2026-03-02",
        )

        validate_error(
            api.create_agreement(
                agreement_payload(ctx["program"]["id"], ctx["taxpayer"]["id"]),
                OFFICER_ALPHA_HEADERS,
            ),
            ApiErrorId.TAXPAYER_UNDER_CRIMINAL_INVESTIGATION,
        )
        assert_fields(
            read_taxpayer(api, ctx["taxpayer"]["id"]),
            open_case_count=1,
            compliance_behavior_score=80,
        )

    def test_closing_the_criminal_case_reopens_the_door_to_drafting(self, api):
        """Closing the case clears both the gate and the score penalty.

        PRD §3.2: "Closing it moves the case `OPEN → CLOSED`, stamps `closed_at`
        with the current instant, and recomputes the taxpayer's
        `open_case_count`, `escalation_tier` and `compliance_behavior_score` — a
        closed case no longer blocks program eligibility and no longer carries
        the open-case penalty."

        PRD §3.4: "An agreement with no `pre_clearance_id` is
        `AMNESTY_STATUTORY`; an agreement with one is `VDA_NEGOTIATED`."

        Design: Difficulty/cross_entity_state_dependency/open_criminal_case_gates_agreement_drafting_until_closed
        """
        ctx = setup_program_with_taxpayer(
            api,
            taxpayer_overrides={
                "legal_name": "Granite Fork Quarry LLC",
                "tin_last4": "5590",
            },
        )
        case = open_enforcement_case(
            api,
            ctx["taxpayer"]["id"],
            case_type="CRIMINAL_INVESTIGATION",
            tax_type="SALES_USE",
            opened_at="2026-03-02",
        )
        validate_error(
            api.create_agreement(
                agreement_payload(ctx["program"]["id"], ctx["taxpayer"]["id"]),
                OFFICER_ALPHA_HEADERS,
            ),
            ApiErrorId.TAXPAYER_UNDER_CRIMINAL_INVESTIGATION,
        )

        closed = validate_success(
            api.close_enforcement_case(case["id"], AUDITOR_ONE_HEADERS)
        )
        assert_fields(closed, status="CLOSED")

        agreement = draft_agreement(api, ctx)
        assert_fields(
            agreement, status="DRAFTED", liability_variant="AMNESTY_STATUTORY"
        )
        assert_fields(
            read_taxpayer(api, ctx["taxpayer"]["id"]),
            open_case_count=0,
            compliance_behavior_score=100,
            escalation_tier="T0",
        )


class TestParticipationWindow:
    """Participation is admitted up to, but not at, `window_close_at`."""

    def test_the_last_instant_inside_the_window_still_admits_a_draft(self, api):
        """Strictly-before means one second early is still inside.

        PRD §2.6: "Participation requires the current instant to be strictly
        before `window_close_at` and at or after `window_open_at`"

        Design: Difficulty/boundary_precision_check/participation_window_closes_at_the_exact_instant
        """
        ctx = setup_program_with_taxpayer(
            api,
            taxpayer_overrides={
                "legal_name": "Kestrel Logistics LLC",
                "tin_last4": "2044",
            },
        )
        set_clock(api, CANONICAL_LAST_INSTANT_INSIDE_WINDOW)

        agreement = draft_agreement(api, ctx)
        assert_fields(agreement, status="DRAFTED")

    def test_the_close_instant_itself_refuses_further_participation(self, api):
        """At exactly `window_close_at` the window is shut.

        PRD §2.6: "Participation requires the current instant to be strictly
        before `window_close_at` and at or after `window_open_at`; closing
        requires the current instant to be at or after `window_close_at` —
        otherwise `ERR_PROGRAM_WINDOW_CLOSED`, `ERR_PROGRAM_WINDOW_NOT_OPEN` or
        `ERR_PROGRAM_WINDOW_NOT_ELAPSED` (422)."

        PRD §3.1: "The program's later transitions, `OPEN → CLOSED` and
        `CLOSED → RECONCILED`, are described in §3.8"

        Design: Difficulty/boundary_precision_check/participation_window_closes_at_the_exact_instant
        """
        ctx = setup_program_with_taxpayer(
            api,
            taxpayer_overrides={
                "legal_name": "Kestrel Logistics LLC",
                "tin_last4": "2044",
            },
        )
        set_clock(api, CANONICAL_LAST_INSTANT_INSIDE_WINDOW)
        draft_agreement(api, ctx)

        set_clock(api, CANONICAL_WINDOW_CLOSE_AT)
        validate_error(
            api.create_agreement(
                agreement_payload(ctx["program"]["id"], ctx["taxpayer"]["id"]),
                OFFICER_ALPHA_HEADERS,
            ),
            ApiErrorId.PROGRAM_WINDOW_CLOSED,
        )

        assert_fields(read_program(api, ctx["program"]["id"]), status="OPEN")
        assert_list_total(
            api.list_agreements(ADMIN_HEADERS, {"program_id": ctx["program"]["id"]}), 1
        )


class TestExecution:
    """Execution happens once and only from `DRAFTED`."""

    def test_an_executed_agreement_admits_neither_signature_nor_rescission(self, api):
        """The state gate answers both re-execution and a stray rescission.

        PRD §3.4: "It requires the agreement to be `DRAFTED` (otherwise
        `ERR_AGREEMENT_NOT_DRAFTED`)"

        PRD §3.7: "Rescinding an agreement that is not `BREACHED` yields
        `ERR_AGREEMENT_NOT_BREACHED`."

        PRD §3.4: "computes `compliance_due_at` as `executed_at` advanced by
        `prospective_compliance_months` whole months"

        Design: Corner/Table 2 State Machines/an_executed_agreement_cannot_be_executed_again
        """
        ctx = setup_executed_agreement(
            api,
            taxpayer_overrides={
                "legal_name": "Alder Field Dairy LLC",
                "tin_last4": "4402",
            },
        )
        agreement_id = ctx["agreement"]["id"]
        executed_version = ctx["agreement"]["version"]
        set_clock(api, "2026-09-20T00:00:00Z")

        validate_error(
            api.execute_agreement(agreement_id, OFFICER_GAMMA_HEADERS),
            ApiErrorId.AGREEMENT_NOT_DRAFTED,
        )
        validate_error(
            api.rescind_breach(
                agreement_id,
                rescind_breach_payload(rescind_reason="NOT_ACTUALLY_BREACHED"),
                AUDITOR_ONE_HEADERS,
            ),
            ApiErrorId.AGREEMENT_NOT_BREACHED,
        )

        assert_fields(
            read_agreement(api, agreement_id),
            status="EXECUTED",
            executed_at=CANONICAL_CLOCK_RENDERED,
            executed_by_user_id=OFFICER_BETA_USER_ID,
            compliance_due_at="2029-09-15T00:00:00.000Z",
            version=executed_version,
        )


class TestAmendment:
    """Amendment supersedes the original and clones a fresh draft (PRD §3.4)."""

    def test_amending_returns_a_new_draft_pointing_back_at_the_original(self, api):
        """Two rows change: the original terminates and a clone is born.

        PRD §3.4: "It advances the addressed agreement `EXECUTED → SUPERSEDED`
        and simultaneously creates a **new** agreement in `DRAFTED` whose
        `amends_agreement_id` points back at the superseded one, carrying the
        same `program_id`, `taxpayer_id`, `pre_clearance_id` and `tax_types`,
        taking `lookback_start_date` and `lookback_end_date` from the amendment
        payload, taking `prospective_compliance_months` from the payload when
        supplied, and recording the amending officer in `drafted_by_user_id`."

        PRD §3.4: "The program's `participant_count` is recomputed, though
        because it counts distinct taxpayers an amendment never changes it."

        Design: Corner/Table 5 Endpoints/amend_supersedes_the_original_and_clones_a_new_draft
        """
        ctx = setup_executed_agreement(
            api,
            taxpayer_overrides={
                "legal_name": "Alderbrook Timber LLC",
                "tin_last4": "6641",
            },
        )
        original_id = ctx["agreement"]["id"]
        original_version = read_agreement(api, original_id)["version"]

        amended = validate_success(
            api.amend_agreement(
                original_id,
                amend_payload(
                    original_version,
                    lookback_start_date="2024-01-01",
                    lookback_end_date=CANONICAL_AGREEMENT_LOOKBACK_END,
                    prospective_compliance_months=48,
                ),
                OFFICER_BETA_HEADERS,
            ),
            201,
        )

        assert amended["id"] != original_id
        assert_fields(
            amended,
            status="DRAFTED",
            version=1,
            amends_agreement_id=original_id,
            lookback_start_date="2024-01-01",
            prospective_compliance_months=48,
            executed_at=None,
            compliance_due_at=None,
        )
        assert_fields(
            read_agreement(api, original_id),
            status="SUPERSEDED",
            version=original_version + 1,
        )
        assert_list_total(
            api.list_agreements(ADMIN_HEADERS, {"amends_agreement_id": original_id}), 1
        )
        assert_list_total(
            api.list_agreements(ADMIN_HEADERS, {"program_id": ctx["program"]["id"]}), 2
        )
        assert_fields(read_program(api, ctx["program"]["id"]), participant_count=1)

    def test_amending_from_a_stale_view_of_the_agreement_is_refused(self, api):
        """A payment moved the version on, so the held value no longer matches.

        PRD §2.8: "Amending an agreement (`POST
        /amnesty/agreements/{id}/amend`) likewise requires
        `expected_agreement_version` as a non-optional field carrying the
        client's last observed `version` of the addressed agreement, and a
        mismatch with the current `version` is rejected with
        `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."

        Design: Corner/Cross-Cutting Complexity Layers/stale_expected_agreement_version_is_refused_on_amendment
        """
        ctx = setup_executed_agreement(
            api,
            taxpayer_overrides={
                "legal_name": "Brackenridge Metals Inc",
                "tin_last4": "2255",
            },
        )
        original_id = ctx["agreement"]["id"]
        stale_version = read_agreement(api, original_id)["version"]
        remit_payment(api, ctx, 60000, payment_reference="GOODFAITH-1")

        validate_error(
            api.amend_agreement(
                original_id, amend_payload(stale_version), OFFICER_BETA_HEADERS
            ),
            ApiErrorId.STALE_AGREEMENT_VERSION,
        )
        assert_fields(read_agreement(api, original_id), status="EXECUTED")
        assert_list_total(
            api.list_agreements(ADMIN_HEADERS, {"program_id": ctx["program"]["id"]}), 1
        )

        fresh_version = read_agreement(api, original_id)["version"]
        assert fresh_version == stale_version + 1

        amended = validate_success(
            api.amend_agreement(
                original_id, amend_payload(fresh_version), OFFICER_BETA_HEADERS
            ),
            201,
        )
        assert_fields(amended, amends_agreement_id=original_id, version=1)
        assert_fields(read_agreement(api, original_id), status="SUPERSEDED")
        assert_list_total(
            api.list_agreements(ADMIN_HEADERS, {"program_id": ctx["program"]["id"]}), 2
        )


class TestCertification:
    """Certification's three gates fire in the PRD's declared order."""

    def test_certification_reports_returns_then_settlement_then_the_clock(self, api):
        """Each gate is cleared in turn and the next one answers.

        PRD §3.4: "It requires the agreement to be `EXECUTED`, requires at least
        one return to exist on the agreement — an agreement with none is refused
        with `ERR_NO_DISCLOSURE_RETURNS` — requires every return that is not
        `VOIDED` to be `SETTLED`, otherwise `ERR_RETURNS_NOT_SETTLED`, and
        requires the current instant to be at or after `compliance_due_at`,
        otherwise `ERR_COMPLIANCE_PERIOD_NOT_ELAPSED`. Those three checks are
        evaluated in that order."

        PRD §3.4: "Fulfilment recomputes the taxpayer's
        `compliance_behavior_score`, which now earns the fulfilled-agreement
        credit, and advances the agreement's `version` by one."

        Design: Corner/Table 5 Endpoints/certify_compliance_gates_on_returns_then_settlement_then_the_clock
        """
        ctx = setup_executed_agreement(
            api,
            taxpayer_overrides={
                "legal_name": "Marlstone Aggregates Inc",
                "tin_last4": "2276",
            },
        )
        agreement_id = ctx["agreement"]["id"]

        validate_error(
            api.certify_compliance(agreement_id, AUDITOR_ONE_HEADERS),
            ApiErrorId.NO_DISCLOSURE_RETURNS,
        )

        disclosure_return = draft_return(api, ctx)
        file_return(api, ctx, disclosure_return["id"])
        validate_error(
            api.certify_compliance(agreement_id, AUDITOR_ONE_HEADERS),
            ApiErrorId.RETURNS_NOT_SETTLED,
        )

        validate_success(
            api.assess_return(disclosure_return["id"], OFFICER_BETA_HEADERS)
        )
        remit_payment(
            api, ctx, CANONICAL_TOTAL_DUE_CENTS, payment_reference="FULL-1"
        )
        settled = validate_success(
            api.get_return(disclosure_return["id"], ADMIN_HEADERS)
        )
        assert_fields(settled, status="SETTLED")
        assert_fields(
            read_agreement(api, agreement_id),
            payment_status="PAID_IN_FULL",
            compliance_due_at="2029-09-15T00:00:00.000Z",
        )

        validate_error(
            api.certify_compliance(agreement_id, AUDITOR_ONE_HEADERS),
            ApiErrorId.COMPLIANCE_PERIOD_NOT_ELAPSED,
        )

        set_clock(api, "2029-09-15T00:00:00Z")
        fulfilled = validate_success(
            api.certify_compliance(agreement_id, AUDITOR_ONE_HEADERS)
        )
        assert_fields(fulfilled, status="FULFILLED")
        assert_fields(
            read_taxpayer(api, ctx["taxpayer"]["id"]), compliance_behavior_score=100
        )
        assert_list_total(
            api.list_agreements(ADMIN_HEADERS, {"status": "FULFILLED"}), 1
        )
        assert_fields(
            read_program(api, ctx["program"]["id"]),
            collected_cents=CANONICAL_TOTAL_DUE_CENTS,
        )

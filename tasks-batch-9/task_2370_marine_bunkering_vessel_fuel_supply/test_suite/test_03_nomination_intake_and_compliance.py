"""Nomination intake, emission-control review and the two status dimensions.

A stem's regulatory standing and its logistics progress live on one record but
advance on separate state machines, and the regulatory one is cyclic: a rejected
stem may be reopened, reviewed afresh and only then approved.
"""

import pytest

from test_helpers import (
    COMPLIANCE,
    COMPLIANCE_USER_ID,
    COMPLIANCE_USER_ID_ALT,
    EARLY_QUOTE,
    NON_EXISTENT_UUID,
    OPS,
    add_nomination,
    api_client,
    ApiErrorId,
    assert_nomination,
    assert_nomination_state,
    build_approved_nomination,
    build_confirmed_nomination,
    build_draft_nomination,
    build_reference_data,
    compliance_review_payload,
    confirm_stem,
    create_nomination_payload,
    make_compliance_officer_headers,
    read_credit_exposure,
    read_nomination,
    submit_compliance_decision,
    validate_error,
    validate_paginated,
    validate_success,
)

REVIEWING_OFFICER = "co-007"

FUTURE_QUOTE = {"quote_date": "2026-08-20T00:00:00Z", "price_usd_per_mt": 705.00}

SHORT_WINDOW_START = "2026-08-10T06:00:00Z"
SHORT_WINDOW_END = "2026-08-10T11:00:00Z"
EXACT_WINDOW_END = "2026-08-10T12:00:00Z"


class TestParallelStatusDimensions:
    """The compliance cycle and the fulfilment dimension move independently."""

    def test_compliance_cycle_runs_while_fulfilment_stays_draft(self):
        """PRD §2.6: "A `Nomination` carries `compliance_status`, its regulatory
        dimension, alongside `fulfillment_status`, its logistics dimension; the
        two advance independently, so a nomination may legitimately sit in
        `DRAFT` fulfilment while already `APPROVED` for compliance."
        PRD §3.3: "Rejecting a stem is the mirror action with a single
        precondition — the nomination must currently be in `PENDING_REVIEW` — and
        it moves `compliance_status` to `REJECTED`."
        PRD §3.3: "Reopening clears `compliance_reviewer_user_id` back to null
        and increments `version` by one, so the officer who eventually approves
        the reopened stem is recorded afresh and remains eligible or ineligible
        to issue the later delivery note on that basis."
        PRD §3.3: "A successful approval records the reviewing officer's
        `X-User-ID` as `compliance_reviewer_user_id` and increments the
        nomination's `version` by one."

        Design: Difficulty/non_linear_state_machine/nomination_parallel_compliance_and_fulfillment_dimensions
        """
        ctx = build_draft_nomination(quotes=[EARLY_QUOTE])
        assert_nomination_state(ctx["nomination"], "PENDING_REVIEW", "DRAFT")

        rejected = submit_compliance_decision(ctx, "REJECT", reviewer=COMPLIANCE_USER_ID)
        assert_nomination_state(rejected, "REJECTED", "DRAFT")
        assert rejected["compliance_reviewer_user_id"] == COMPLIANCE_USER_ID, (
            "The deciding officer must be recorded on a rejection, got "
            f"{rejected['compliance_reviewer_user_id']}"
        )

        reopened = submit_compliance_decision(ctx, "REOPEN", reviewer=COMPLIANCE_USER_ID)
        assert_nomination_state(reopened, "PENDING_REVIEW", "DRAFT")
        assert reopened["compliance_reviewer_user_id"] is None, (
            "Reopening must clear the reviewer back to null, got "
            f"{reopened['compliance_reviewer_user_id']}"
        )

        approved = submit_compliance_decision(
            ctx, "APPROVE", reviewer=COMPLIANCE_USER_ID_ALT
        )
        assert_nomination_state(approved, "APPROVED", "DRAFT")
        assert approved["compliance_reviewer_user_id"] == COMPLIANCE_USER_ID_ALT, (
            "The officer who approved the reopened stem must be recorded afresh, "
            f"got {approved['compliance_reviewer_user_id']}"
        )

    def test_confirmation_advances_fulfilment_without_touching_compliance(self):
        """PRD §3.4: "Confirmation increments the nomination's `version` by one
        and brings the stem into the open-commitment set that inflates the
        customer's conservative exposure."
        PRD §2.5: "All resources except index quotes additionally carry
        `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and
        `version`, an integer that starts at 1 on creation and increments by one
        on every mutation of the record."

        Design: Difficulty/non_linear_state_machine/nomination_parallel_compliance_and_fulfillment_dimensions
        """
        ctx = build_draft_nomination(quotes=[EARLY_QUOTE])
        submit_compliance_decision(ctx, "REJECT", reviewer=COMPLIANCE_USER_ID)
        submit_compliance_decision(ctx, "REOPEN", reviewer=COMPLIANCE_USER_ID)
        submit_compliance_decision(ctx, "APPROVE", reviewer=COMPLIANCE_USER_ID_ALT)

        confirmed = confirm_stem(ctx)

        assert_nomination_state(confirmed, "APPROVED", "CONFIRMED")
        assert confirmed["version"] == 5, (
            "Creation plus four mutating calls must leave version at 5, got "
            f"{confirmed['version']}"
        )


class TestIntakeInitialState:
    """What a nomination looks like the instant it is accepted."""

    def test_intake_seeds_both_dimensions_at_their_initial_states(self):
        """PRD §3.3: "On intake the nomination's two dimensions are initialised
        independently: `fulfillment_status` to `DRAFT` and `compliance_status` to
        `PENDING_REVIEW`, with `compliance_reviewer_user_id` null."
        PRD §3.3: "It describes the receiving vessel through `vessel_imo`, which must
        be exactly seven digits, and `vessel_name`, and declares whether the vessel has
        an approved exhaust gas cleaning system through `scrubber_fitted`, which
        defaults to false."
        PRD §2.5: "All resources except index quotes additionally carry `updated_at`,
        an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an
        integer that starts at 1 on creation and increments by one on every mutation of
        the record."

        `scrubber_fitted` is omitted from the payload so its declared default is what
        is under test.

        Design: Corner/state_machines/nomination_starts_in_draft_and_pending_review
        """
        ctx = build_reference_data(quotes=[])
        payload = create_nomination_payload(
            ctx["customer"]["id"], ctx["port"]["id"], ctx["grade"]["id"]
        )
        del payload["scrubber_fitted"]

        nomination = validate_success(api_client.create_nomination(payload, OPS), 201)

        assert_nomination(nomination)
        assert_nomination_state(nomination, "PENDING_REVIEW", "DRAFT")
        assert nomination["compliance_reviewer_user_id"] is None, (
            "No officer has reviewed the stem yet, got "
            f"{nomination['compliance_reviewer_user_id']}"
        )
        assert nomination["version"] == 1, (
            f"A freshly created record is at version 1, got {nomination['version']}"
        )
        assert nomination["scrubber_fitted"] is False, (
            "An omitted `scrubber_fitted` must default to false, got "
            f"{nomination['scrubber_fitted']}"
        )

    def test_an_unknown_nomination_id_is_a_not_found_never_an_empty_body(self):
        """PRD §2.7: "The corresponding rejections are `ERR_PORT_NOT_FOUND`,
        `ERR_FUEL_GRADE_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`,
        `ERR_NOMINATION_NOT_FOUND`, `ERR_DELIVERY_ORDER_NOT_FOUND`,
        `ERR_BDN_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_LAB_ANALYSIS_NOT_FOUND`,
        `ERR_INVOICE_NOT_FOUND` and `ERR_SPILL_INCIDENT_NOT_FOUND`, each carrying HTTP
        404."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
        the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went
        wrong."

        Design: Corner/entities/nomination_not_found_returns_404
        """
        build_reference_data(quotes=[])

        response = api_client.get_nomination(NON_EXISTENT_UUID, OPS)

        validate_error(response, ApiErrorId.ERR_NOMINATION_NOT_FOUND)

    def test_an_omitted_vessel_imo_is_a_payload_violation(self):
        """PRD §2.8: "Payload shape: required fields present, declared types
        respected, enum members valid, declared decimal scales respected, quantities
        strictly positive where declared so, and pagination parameters in range —
        `ERR_INVALID_REQUEST`."
        PRD §3.3: "It describes the receiving vessel through `vessel_imo`, which must
        be exactly seven digits, and `vessel_name`, and declares whether the vessel has
        an approved exhaust gas cleaning system through `scrubber_fitted`, which
        defaults to false."

        `vessel_imo` carries no declared default, so its absence is a shape failure and
        no row may be written.

        Design: Corner/entities/nomination_missing_required_vessel_imo_rejected
        """
        ctx = build_reference_data(quotes=[])
        payload = create_nomination_payload(
            ctx["customer"]["id"], ctx["port"]["id"], ctx["grade"]["id"]
        )
        del payload["vessel_imo"]

        response = api_client.create_nomination(payload, OPS)

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
        _rows, meta = validate_paginated(api_client.list_nominations(OPS))
        assert meta["total_count"] == 0, (
            f"A refused intake must persist nothing, got {meta['total_count']} rows"
        )

    def test_an_unknown_buyer_is_caught_by_the_existence_tier(self):
        """PRD §2.7: "Requests that name several records — in the path, in the body, or
        both — are validated for existence in a fixed left-to-right, outer-to-inner
        order, and the first identifier that fails to resolve determines the error
        returned."
        PRD §2.7: "The order of resolution across the system is: `port_id`, then
        `grade_id`, then `customer_id`, then `asset_id`, then `nomination_id`, then
        `delivery_order_id`, then `bdn_id`, then `claim_id`, then
        `retest_of_analysis_id`, then an invoice `id`, then a spill incident `id`."

        The port and the grade both resolve, so the buyer is the first identifier that
        can fail.

        Design: Corner/entities/nomination_rejects_unknown_customer_parent
        """
        ctx = build_reference_data(quotes=[])
        payload = create_nomination_payload(
            NON_EXISTENT_UUID, ctx["port"]["id"], ctx["grade"]["id"]
        )

        response = api_client.create_nomination(payload, OPS)

        validate_error(response, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)
        _rows, meta = validate_paginated(api_client.list_nominations(OPS))
        assert meta["total_count"] == 0, (
            f"A refused intake must persist nothing, got {meta['total_count']} rows"
        )


class TestComplianceDecisionGuards:
    """Which decisions each compliance state admits, and what they record."""

    def test_approval_persists_the_acting_officer_on_the_stem(self):
        """PRD §3.3: "A successful approval records the reviewing officer's
        `X-User-ID` as `compliance_reviewer_user_id` and increments the nomination's
        `version` by one."
        PRD §2.6: "A `Nomination` carries `compliance_status`, its regulatory
        dimension, alongside `fulfillment_status`, its logistics dimension; the two
        advance independently, so a nomination may legitimately sit in `DRAFT`
        fulfilment while already `APPROVED` for compliance."

        The persisted identity is what the later segregation check on note issuance
        reads, so it must survive the call rather than be merely accepted.

        Design: Corner/state_machines/compliance_approve_records_reviewer_identity
        """
        ctx = build_draft_nomination(quotes=[])
        before_version = ctx["nomination"]["version"]

        reviewed = validate_success(
            api_client.compliance_review(
                ctx["nomination"]["id"],
                compliance_review_payload("APPROVE"),
                make_compliance_officer_headers(REVIEWING_OFFICER),
            )
        )

        assert_nomination_state(reviewed, "APPROVED", "DRAFT")
        assert reviewed["compliance_reviewer_user_id"] == REVIEWING_OFFICER, (
            f"Expected {REVIEWING_OFFICER} recorded as reviewer, got "
            f"{reviewed['compliance_reviewer_user_id']}"
        )
        assert reviewed["version"] == before_version + 1, (
            f"Approval increments the version once, expected {before_version + 1}, got "
            f"{reviewed['version']}"
        )
        assert read_nomination(ctx)["compliance_reviewer_user_id"] == REVIEWING_OFFICER, (
            "The reviewer must be persisted, not merely echoed"
        )

    def test_an_approved_stem_cannot_be_reopened(self):
        """PRD §3.3: "Reopening runs the cycle backwards: a nomination in `REJECTED`
        returns to `PENDING_REVIEW` once the customer has amended the stem
        documentation, but only while `fulfillment_status` is still `DRAFT` — a stem
        that has already progressed is rejected with `ERR_INVALID_NOMINATION_STATE`."
        PRD §3.3: "Attempting any of the three decisions from a state that does not
        permit it is rejected with `ERR_INVALID_NOMINATION_STATE` (HTTP 409)."
        PRD §3.3: "Reopening clears `compliance_reviewer_user_id` back to null and
        increments `version` by one, so the officer who eventually approves the reopened
        stem is recorded afresh and remains eligible or ineligible to issue the later
        delivery note on that basis."

        `REOPEN` is defined only out of `REJECTED`, so from `APPROVED` the refusal must
        also leave the recorded reviewer intact.

        Design: Corner/state_machines/approved_compliance_cannot_be_reopened
        """
        ctx = build_approved_nomination(quotes=[])
        approved_version = ctx["nomination"]["version"]

        response = api_client.compliance_review(
            ctx["nomination"]["id"],
            compliance_review_payload("REOPEN"),
            make_compliance_officer_headers(COMPLIANCE_USER_ID),
        )

        validate_error(response, ApiErrorId.ERR_INVALID_NOMINATION_STATE)
        after = read_nomination(ctx)
        assert_nomination_state(after, "APPROVED", "DRAFT")
        assert after["compliance_reviewer_user_id"] == COMPLIANCE_USER_ID, (
            "The refused reopening must not clear the reviewer, got "
            f"{after['compliance_reviewer_user_id']}"
        )
        assert after["version"] == approved_version, (
            f"A refused decision must not move the version, expected "
            f"{approved_version}, got {after['version']}"
        )


class TestConfirmationGuards:
    """The commercial commitment is gated on the other dimension and is once-only."""

    def test_confirming_an_unreviewed_stem_is_refused(self):
        """PRD §3.4: "It moves `fulfillment_status` from `DRAFT` to `CONFIRMED` and is
        gated by three conditions in addition to the state check: the nomination's
        `compliance_status` must already be `APPROVED`, or the request is rejected with
        `ERR_COMPLIANCE_NOT_APPROVED`; the customer's `credit_status` must not be
        `HOLD`, or the request is rejected with `ERR_CUSTOMER_CREDIT_HOLD`; and the
        conservative credit check must pass, or the request is rejected with
        `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

        The buyer has a five-million limit and a priced grade, so the compliance gate is
        the only defect in the request.

        Design: Corner/state_machines/confirm_without_compliance_approval_rejected
        """
        ctx = build_draft_nomination(quotes=[EARLY_QUOTE])
        draft_version = ctx["nomination"]["version"]
        assert ctx["nomination"]["compliance_status"] == "PENDING_REVIEW", (
            "No review call has been made, got "
            f"{ctx['nomination']['compliance_status']}"
        )

        response = api_client.confirm_nomination(ctx["nomination"]["id"], OPS)

        validate_error(response, ApiErrorId.ERR_COMPLIANCE_NOT_APPROVED)
        after = read_nomination(ctx)
        assert_nomination_state(after, "PENDING_REVIEW", "DRAFT")
        assert after["version"] == draft_version, (
            f"A refused confirmation must not move the version, expected "
            f"{draft_version}, got {after['version']}"
        )

    def test_confirmation_is_not_idempotent_and_books_no_second_commitment(self):
        """PRD §3.4: "It moves `fulfillment_status` from `DRAFT` to `CONFIRMED` and is
        gated by three conditions in addition to the state check: the nomination's
        `compliance_status` must already be `APPROVED`, or the request is rejected with
        `ERR_COMPLIANCE_NOT_APPROVED`; the customer's `credit_status` must not be
        `HOLD`, or the request is rejected with `ERR_CUSTOMER_CREDIT_HOLD`; and the
        conservative credit check must pass, or the request is rejected with
        `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."
        PRD §2.8: "State legality, in this internal order: nomination state, compliance
        approval, order logistics state, measurement agreement, measurement state
        legality, an already-issued delivery note, a not-yet-issued delivery note, an
        already-existing invoice, invoice state legality, invoice issuance for a claim,
        claim state legality, sample release, retest limit, off-spec finding,
        measurement discrepancy, asset quarantine, asset state legality, open spill
        incident, and spill incident state."
        PRD §3.4: "Confirmation increments the nomination's `version` by one and brings
        the stem into the open-commitment set that inflates the customer's conservative
        exposure."
        PRD §3.2: "`open_commitment_count` reports how many nominations entered that
        set, and defaults to 0."

        Repeating the call must not book the same stem twice, so the count stays at one.

        Design: Corner/state_machines/second_confirm_on_same_nomination_rejected
        """
        ctx = build_confirmed_nomination(quotes=[EARLY_QUOTE])
        confirmed_version = ctx["nomination"]["version"]
        assert read_credit_exposure(ctx)["open_commitment_count"] == 1, (
            "The single confirmed stem must be the only open commitment"
        )

        response = api_client.confirm_nomination(ctx["nomination"]["id"], OPS)

        validate_error(response, ApiErrorId.ERR_INVALID_NOMINATION_STATE)
        after = read_nomination(ctx)
        assert_nomination_state(after, "APPROVED", "CONFIRMED")
        assert after["version"] == confirmed_version, (
            f"A refused second confirmation must not move the version, expected "
            f"{confirmed_version}, got {after['version']}"
        )
        exposure = read_credit_exposure(ctx)
        assert exposure["open_commitment_count"] == 1, (
            "The stem must be counted once, not twice, got "
            f"{exposure['open_commitment_count']}"
        )
        assert exposure["conservative_exposure_usd"] == pytest.approx(
            846000.00, abs=0.01
        ), (
            "1200.000 mt at the 705.00 quote is 846000.00 booked exactly once, got "
            f"{exposure['conservative_exposure_usd']}"
        )


    def test_a_stem_whose_grade_has_no_effective_quote_cannot_be_confirmed(self):
        """PRD §2.12: "Whenever the system needs the governing price of a grade at a
        given instant, it selects the quote for that grade whose `quote_date` is the
        greatest value at or before that instant."
        PRD §2.12: "If no quote for that grade exists at or before the instant, the
        operation is rejected with `ERR_INDEX_QUOTE_UNAVAILABLE` (HTTP 422); this can
        surface when raising an invoice, when confirming a stem, and when reading a
        customer's credit exposure."
        PRD §3.4: "The prospective commitment of the addressed nomination is its
        `nominated_quantity_mt` multiplied by the governing index price of its grade at
        the current logical clock, rounded to two decimal places."

        The grade's only quote is dated 2026-08-20 while the clock reads 2026-08-05, so
        there is no quote at or before the instant and the commitment cannot be valued.

        Design: Corner/validations/confirm_without_any_index_quote_rejected
        """
        ctx = build_approved_nomination(quotes=[FUTURE_QUOTE])
        approved = ctx["nomination"]

        response = api_client.confirm_nomination(approved["id"], OPS)

        validate_error(response, ApiErrorId.ERR_INDEX_QUOTE_UNAVAILABLE)
        after = read_nomination(ctx)
        assert_nomination_state(after, "APPROVED", "DRAFT")
        assert after["version"] == approved["version"], (
            f"A refused confirmation must not move the version, expected "
            f"{approved['version']}, got {after['version']}"
        )


class TestEmissionControlReviewGates:
    """The three substantive checks that stand between a stem and approval."""

    def test_a_declared_ceiling_above_the_grade_ceiling_fails_review(self):
        """PRD §3.3: "Independently of the port, and in all cases, the customer's
        `declared_sulfur_pct` must be no greater than the grade's `max_sulfur_pct`, and a
        stem that declares a tighter requirement than the grade can meet is also rejected
        with `ERR_ECA_SULFUR_VIOLATION`."
        PRD §3.3: "On intake the nomination's two dimensions are initialised
        independently: `fulfillment_status` to `DRAFT` and `compliance_status` to
        `PENDING_REVIEW`, with `compliance_reviewer_user_id` null."

        Intake itself never compares the two figures, so the stem is accepted at 201 and
        only the review call refuses it.

        Design: Corner/validations/eca_sulfur_violation_on_compliance_review_rejected
        """
        ctx = build_draft_nomination(
            nomination={"declared_sulfur_pct": 0.150}, quotes=[]
        )
        assert ctx["grade"]["max_sulfur_pct"] == pytest.approx(0.100, abs=0.0005), (
            f"The grade must cap at 0.100, got {ctx['grade']['max_sulfur_pct']}"
        )
        intake_version = ctx["nomination"]["version"]

        response = api_client.compliance_review(
            ctx["nomination"]["id"], compliance_review_payload("APPROVE"), COMPLIANCE
        )

        validate_error(response, ApiErrorId.ERR_ECA_SULFUR_VIOLATION)
        after = read_nomination(ctx)
        assert_nomination_state(after, "PENDING_REVIEW", "DRAFT")
        assert after["compliance_reviewer_user_id"] is None, (
            "A refused review records no officer, got "
            f"{after['compliance_reviewer_user_id']}"
        )
        assert after["version"] == intake_version, (
            f"A refused review must not move the version, expected {intake_version}, "
            f"got {after['version']}"
        )

    def test_a_scrubberless_stem_without_changeover_documentation_fails_review(self):
        """PRD §3.3: "In that same circumstance the nomination's
        `eca_documentation_ref` must not be null, or the review is rejected with
        `ERR_ECA_DOCUMENTATION_MISSING`."
        PRD §3.3: "Finally `eca_documentation_ref` carries the fuel-changeover and
        bunker-documentation reference; it defaults to null and is only mandatory in the
        circumstance described below."

        The port is inside an Emission Control Area and the vessel carries no scrubber,
        so the documentation reference is mandatory here.

        Design: Corner/validations/eca_documentation_required_only_without_scrubber
        """
        ctx = build_draft_nomination(
            nomination={"scrubber_fitted": False, "eca_documentation_ref": None},
            quotes=[],
        )
        assert ctx["port"]["eca_zone"] is True, (
            f"The port must lie inside an ECA, got {ctx['port']['eca_zone']}"
        )
        assert ctx["nomination"]["eca_documentation_ref"] is None, (
            "The stem must carry no changeover reference, got "
            f"{ctx['nomination']['eca_documentation_ref']}"
        )

        response = api_client.compliance_review(
            ctx["nomination"]["id"], compliance_review_payload("APPROVE"), COMPLIANCE
        )

        validate_error(response, ApiErrorId.ERR_ECA_DOCUMENTATION_MISSING)
        assert_nomination_state(read_nomination(ctx), "PENDING_REVIEW", "DRAFT")

    def test_a_scrubber_fitted_stem_needs_no_changeover_documentation(self):
        """PRD §3.3: "When the delivery port lies inside an Emission Control Area and
        the vessel has no scrubber fitted, the nominated grade must be flagged as
        permitted inside such an area and its contractual sulfur ceiling must be no
        greater than the port's enforced limit; otherwise the review is rejected with
        `ERR_ECA_SULFUR_VIOLATION`."
        PRD §3.3: "In that same circumstance the nomination's `eca_documentation_ref`
        must not be null, or the review is rejected with
        `ERR_ECA_DOCUMENTATION_MISSING`."
        PRD §3.3: "A successful approval records the reviewing officer's `X-User-ID` as
        `compliance_reviewer_user_id` and increments the nomination's `version` by one."

        The documentation rule is scoped to the scrubberless circumstance, so an
        approved exhaust gas cleaning system lifts it even in the same port.

        Design: Corner/validations/eca_documentation_required_only_without_scrubber
        """
        ctx = build_reference_data(quotes=[])
        add_nomination(
            ctx,
            vessel_imo="9667788",
            vessel_name="MV Scrubbed",
            scrubber_fitted=True,
            eca_documentation_ref=None,
        )

        reviewed = validate_success(
            api_client.compliance_review(
                ctx["nomination"]["id"], compliance_review_payload("APPROVE"), COMPLIANCE
            )
        )

        assert_nomination_state(reviewed, "APPROVED", "DRAFT")
        assert reviewed["eca_documentation_ref"] is None, (
            "The approval must not invent a reference, got "
            f"{reviewed['eca_documentation_ref']}"
        )
        assert reviewed["compliance_reviewer_user_id"] == COMPLIANCE_USER_ID, (
            f"Expected {COMPLIANCE_USER_ID} recorded as reviewer, got "
            f"{reviewed['compliance_reviewer_user_id']}"
        )


class TestDeliveryWindowLength:
    """`window_end` must stand at least six hours after `window_start`."""

    def test_a_five_hour_window_is_refused_at_intake(self):
        """PRD §3.3: "The window must be at least six hours wide: `window_end` must be
        no earlier than `window_start` plus six hours, and a shorter window is rejected
        with `ERR_WINDOW_TOO_SHORT`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
        the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went
        wrong."

        Design: Corner/validations/window_shorter_than_minimum_rejected
        """
        ctx = build_reference_data(quotes=[])
        payload = create_nomination_payload(
            ctx["customer"]["id"],
            ctx["port"]["id"],
            ctx["grade"]["id"],
            window_start=SHORT_WINDOW_START,
            window_end=SHORT_WINDOW_END,
        )

        response = api_client.create_nomination(payload, OPS)

        validate_error(response, ApiErrorId.ERR_WINDOW_TOO_SHORT)
        _rows, meta = validate_paginated(api_client.list_nominations(OPS))
        assert meta["total_count"] == 0, (
            f"A refused window must persist nothing, got {meta['total_count']} rows"
        )

    def test_a_window_of_exactly_six_hours_is_accepted(self):
        """PRD §3.3: "The window must be at least six hours wide: `window_end` must be
        no earlier than `window_start` plus six hours, and a shorter window is rejected
        with `ERR_WINDOW_TOO_SHORT`."
        PRD §3.3: "On intake the nomination's two dimensions are initialised
        independently: `fulfillment_status` to `DRAFT` and `compliance_status` to
        `PENDING_REVIEW`, with `compliance_reviewer_user_id` null."

        "No earlier than" makes the six-hour mark inclusive, so the boundary itself must
        pass.

        Design: Corner/validations/window_shorter_than_minimum_rejected
        """
        ctx = build_reference_data(quotes=[])
        payload = create_nomination_payload(
            ctx["customer"]["id"],
            ctx["port"]["id"],
            ctx["grade"]["id"],
            window_start=SHORT_WINDOW_START,
            window_end=EXACT_WINDOW_END,
        )

        nomination = validate_success(api_client.create_nomination(payload, OPS), 201)

        assert_nomination(nomination)
        assert_nomination_state(nomination, "PENDING_REVIEW", "DRAFT")
        _rows, meta = validate_paginated(api_client.list_nominations(OPS))
        assert meta["total_count"] == 1, (
            f"The accepted stem must be the only row, got {meta['total_count']}"
        )

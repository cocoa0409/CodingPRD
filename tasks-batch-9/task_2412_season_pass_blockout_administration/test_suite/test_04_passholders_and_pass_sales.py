"""Registering guests and selling passes: identifiers, ledgers and opening states."""

from test_helpers import (
    BRONZE,
    GOLD,
    UNKNOWN_UUID,
    ApiErrorId,
    BillingStatus,
    PassholderStatus,
    PassStatus,
    PaymentMode,
    ProgramStatus,
    assert_ledger,
    assert_pass_dimensions,
    assert_version,
    build_program,
    clerk_headers,
    create_passholder,
    drop_fields,
    passholder_payload,
    program_admin_headers,
    season_pass_payload,
    sell_pass,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPassholderRegistration:
    """A guest record needs its three identity fields and starts clean."""

    def test_a_registration_without_an_email_is_rejected(self, api):
        """The unique email is a required field, so omitting it is a schema failure.

        PRD: "A `PassOfficeClerk` registers a **passholder** with a `full_name` — the
        legal name printed on the pass — an `email` which must be globally unique across
        all passholders, and a `date_of_birth` as an ISO `YYYY-MM-DD` value."

        Design: Corner/entities/passholder_creation_without_email_is_rejected
        """
        response = api.create_passholder(
            drop_fields(passholder_payload(), "email"), headers=clerk_headers()
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        accepted = validate_success(
            api.create_passholder(passholder_payload(), headers=clerk_headers()), 201
        )
        assert accepted["status"] == PassholderStatus.ACTIVE.value, (
            f"a new passholder starts ACTIVE, got {accepted['status']!r}"
        )
        assert accepted["sharing_risk_score"] == 0, (
            f"a new passholder starts with a zero risk score, got {accepted['sharing_risk_score']!r}"
        )
        assert accepted["photo_mismatch_count"] == 0, (
            f"a new passholder has no mismatches, got {accepted['photo_mismatch_count']!r}"
        )


class TestSeasonPassIdentifiers:
    """Media numbers are human-facing and allocated in creation order."""

    def test_media_numbers_are_minted_sequentially_from_sp_000001(self, api, sales_open_program):
        """The first pass ever sold is SP-000001 and the second SP-000002.

        PRD: "Media numbers are minted sequentially in creation order — the first pass
        ever created is `SP-000001`, the second `SP-000002`, and so on, always six digits
        zero-padded after the `SP-` prefix, allocated by ascending `created_at`."

        Design: Corner/entities/season_pass_media_number_minted_in_creation_order
        """
        first_holder = create_passholder(api, email="first@example.com")
        second_holder = create_passholder(api, email="second@example.com")

        first = sell_pass(
            api,
            sales_open_program.id,
            sales_open_program.tier_id("BRONZE"),
            first_holder["id"],
            PaymentMode.PAYMENT_PLAN.value,
        )
        second = sell_pass(
            api,
            sales_open_program.id,
            sales_open_program.tier_id("BRONZE"),
            second_holder["id"],
            PaymentMode.PAY_IN_FULL.value,
        )

        assert first["media_number"] == "SP-000001", (
            f"the first pass should carry SP-000001, got {first['media_number']!r}"
        )
        assert second["media_number"] == "SP-000002", (
            f"the second pass should carry SP-000002, got {second['media_number']!r}"
        )
        assert_pass_dimensions(
            first,
            pass_status=PassStatus.PENDING_PROCESSING.value,
            billing_status=BillingStatus.UNBILLED.value,
        )
        assert_ledger(first, contract=12000, billed=12000, paid=0, credited=0, outstanding=12000)
        assert_pass_dimensions(second, billing_status=BillingStatus.PAID_IN_FULL.value)
        assert_ledger(second, billed=12000, paid=12000, outstanding=0)

    def test_reading_a_pass_that_does_not_exist_is_a_not_found(self, api):
        """A well-formed but unknown identifier resolves to nothing.

        PRD: "Within the existence band, identifiers resolve in this order: pass programme
        (`ERR_PROGRAM_NOT_FOUND`), pass tier (`ERR_TIER_NOT_FOUND`), park day
        (`ERR_PARK_DAY_NOT_FOUND`), passholder (`ERR_PASSHOLDER_NOT_FOUND`), season pass
        (`ERR_PASS_NOT_FOUND`), payment plan (`ERR_PLAN_NOT_FOUND`), installment
        (`ERR_INSTALLMENT_NOT_FOUND`), reservation (`ERR_RESERVATION_NOT_FOUND`), visit
        (`ERR_VISIT_NOT_FOUND`), sharing case (`ERR_CASE_NOT_FOUND`), upgrade order
        (`ERR_UPGRADE_ORDER_NOT_FOUND`), blockout assignment (`ERR_ASSIGNMENT_NOT_FOUND`)."

        Design: Corner/entities/season_pass_read_with_unknown_id_returns_not_found
        """
        response = api.get_season_pass(UNKNOWN_UUID, headers=clerk_headers())

        validate_error(response, ApiErrorId.ERR_PASS_NOT_FOUND.value, 404)


class TestSaleReferenceResolution:
    """A sale resolves both of its foreign references before anything else."""

    def test_an_unknown_programme_or_holder_reference_is_a_not_found(
        self, api, sales_open_program
    ):
        """Each dangling reference answers with the missing entity's own code.

        PRD: "The rule covers both path variables and body-borne references, so a body
        `program_id` that names nothing yields `ERR_PROGRAM_NOT_FOUND`; a `tier_id`,
        `source_tier_id` or `target_tier_id` that names nothing yields
        `ERR_TIER_NOT_FOUND`; a body `park_day_id` yields `ERR_PARK_DAY_NOT_FOUND`; a body
        `passholder_id` yields `ERR_PASSHOLDER_NOT_FOUND`; a body `season_pass_id` or
        `renewed_from_pass_id` yields `ERR_PASS_NOT_FOUND`; a body `waive_installment_id`
        yields `ERR_INSTALLMENT_NOT_FOUND`, as does an installment that exists but does not
        belong to the pass's active plan; and any element of a submitted
        `evidence_visit_ids` array that names nothing yields `ERR_VISIT_NOT_FOUND`."

        Design: Corner/entities/season_pass_creation_with_unknown_program_returns_not_found
        """
        holder = create_passholder(api)

        unknown_program = api.create_season_pass(
            season_pass_payload(UNKNOWN_UUID, sales_open_program.tier_id("BRONZE"), holder["id"]),
            headers=clerk_headers(),
        )
        validate_error(unknown_program, ApiErrorId.ERR_PROGRAM_NOT_FOUND.value, 404)

        unknown_holder = api.create_season_pass(
            season_pass_payload(
                sales_open_program.id, sales_open_program.tier_id("BRONZE"), UNKNOWN_UUID
            ),
            headers=clerk_headers(),
        )
        validate_error(unknown_holder, ApiErrorId.ERR_PASSHOLDER_NOT_FOUND.value, 404)


class TestOpeningStatesOnBothDimensions:
    """The two status dimensions each start in their own opening value."""

    def test_a_plan_sale_opens_pending_processing_and_unbilled(self, api):
        """The access dimension and the billing dimension start independently.

        PRD: "a `PAYMENT_PLAN` sale leaves `billing_status` at `UNBILLED` until a plan is
        enrolled, with the whole contract value outstanding."

        Design: Corner/state_machines/season_pass_initial_states_on_both_dimensions
        """
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SALES_OPEN.value)
        holder = create_passholder(api)

        sold = sell_pass(
            api,
            program.id,
            program.tier_id("BRONZE"),
            holder["id"],
            PaymentMode.PAYMENT_PLAN.value,
        )

        assert_pass_dimensions(
            sold,
            pass_status=PassStatus.PENDING_PROCESSING.value,
            billing_status=BillingStatus.UNBILLED.value,
        )
        for field in ("credited_amount_cents", "visit_count", "in_park_spend_cents", "suspension_count"):
            assert sold[field] == 0, f"{field} should start at 0, got {sold[field]!r}"
        assert sold["renewed_from_pass_id"] is None, (
            f"a new sale has no predecessor, got {sold['renewed_from_pass_id']!r}"
        )
        assert sold["photo_captured"] is False, "an unprocessed pass has no photograph"
        assert sold["identity_bound"] is False, "an unprocessed pass has no identity binding"
        assert sold["photo_hash"] is None, f"photo_hash should start null, got {sold['photo_hash']!r}"
        assert sold["government_id_last4"] is None, (
            f"government_id_last4 should start null, got {sold['government_id_last4']!r}"
        )
        assert_version(sold, 1, "season pass")
        program_row = validate_success(
            api.get_pass_program(program.id, headers=program_admin_headers())
        )
        assert program_row["active_pass_count"] == 0, (
            "an unprocessed pass is not yet active, got "
            f"{program_row['active_pass_count']!r} active passes"
        )


class TestOneLivePassPerHolderPerProgramme:
    """The uniqueness scope is the holder, the programme and the live status set."""

    def _holder_with_a_pending_pass(self, api):
        first = build_program(api, tiers=(BRONZE, GOLD), status=ProgramStatus.SALES_OPEN.value)
        holder = create_passholder(api)
        sell_pass(
            api,
            first.id,
            first.tier_id("BRONZE"),
            holder["id"],
            PaymentMode.PAY_IN_FULL.value,
        )
        return first, holder

    def test_a_second_sale_in_the_same_programme_is_refused_even_on_another_tier(
        self, api, default_clock
    ):
        """A pass still awaiting processing already counts as live.

        PRD: "Four guards apply beyond the programme-status and tier-published checks
        already stated: the tier's programme must match the programme being sold under, else
        `ERR_TIER_PROGRAM_MISMATCH`; and the holder must not already own a pass in this
        programme whose `pass_status` is `PENDING_PROCESSING`, `ACTIVE` or `SUSPENDED`, else
        `ERR_DUPLICATE_ACTIVE_PASS` (HTTP 422)."

        Design: Corner/validations/second_live_pass_for_the_same_passholder_in_one_program_is_rejected
        """
        first, holder = self._holder_with_a_pending_pass(api)

        response = api.create_season_pass(
            season_pass_payload(first.id, first.tier_id("GOLD"), holder["id"]),
            headers=clerk_headers(),
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_ACTIVE_PASS.value, 422)

    def test_the_same_guest_may_hold_a_pass_in_a_second_programme(self, api, default_clock):
        """A different programme is a different uniqueness scope.

        PRD: "One human, one live pass, per programme."

        Design: Corner/validations/second_live_pass_for_the_same_passholder_in_one_program_is_rejected
        """
        _, holder = self._holder_with_a_pending_pass(api)
        second = build_program(
            api,
            tiers=(BRONZE,),
            status=ProgramStatus.SALES_OPEN.value,
            season_year=2027,
            park_name="Harbor Bay",
        )

        sold = sell_pass(
            api,
            second.id,
            second.tier_id("BRONZE"),
            holder["id"],
            PaymentMode.PAY_IN_FULL.value,
        )

        assert sold["media_number"] == "SP-000002", (
            f"the second pass minted should be SP-000002, got {sold['media_number']!r}"
        )
        _, meta = validate_paginated(
            api.list_season_passes(
                headers=clerk_headers(), params={"passholder_id": holder["id"]}
            )
        )
        assert meta["total_count"] == 2, (
            f"the guest should now hold two passes across two programmes, got {meta['total_count']!r}"
        )

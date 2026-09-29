"""Optimistic concurrency, the confirming-bank selector policy, and sweep idempotence.

Three cross-cutting layers meet here. The two optimistic-concurrency rules are exercised on
their own declared write endpoints, each against a different parent entity and a different
version field, and each proved to be a comparison against the live version rather than a fixed
rejection. The selector policy is exercised in both directions: once with the choice handed to
the server, and once with the eligible pool deliberately emptied. The sweep is exercised as a
checkpoint — a dry run that reports without mutating, a real run that moves the rows, and a
third run at the same logical clock that must report nothing at all.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    TRADE_FINANCE_OFFICER_2,
    api_client,
    assert_all_sweep_counters_zero,
    assert_end_of_day_instant,
    assert_facility_ledger,
    assert_fields_equal,
    assert_sweep_counters,
    compliance_officer_headers,
    conclude_examination,
    create_applicant,
    create_bank,
    create_beneficiary,
    create_facility,
    credit_officer_headers,
    draft_amendment,
    factories,
    issued_credit,
    list_amendment_rows,
    list_discrepancy_rows,
    list_waiver_request_rows,
    Parties,
    post_collateral,
    raise_discrepancy,
    request_confirmation,
    request_waiver,
    run_sweep,
    set_clock,
    setup_parties,
    submitted_presentation,
    trade_finance_officer_headers,
)

THE_CLOCK_INSTANT = "2026-08-10T09:00:00.000Z"
THE_CLOCK_DATE = "2026-08-10"
PAST_BOTH_DEADLINES = "2026-08-18T09:00:00Z"

SWEEP_COUNTERS = (
    "credits_expired",
    "presentations_precluded",
    "waiver_requests_expired",
    "amendments_lapsed",
    "allocations_released",
    "facilities_reactivated",
)

_APPLICANT = {"legal_name": "Baltic Timber Imports AS", "country_code": "NO"}
_BANK = {
    "bank_name": "Nordkyst Bank",
    "swift_bic": "NDKBNOKK",
    "country_code": "NO",
    "country_risk_score": 12,
    "credit_rating": "AA",
    "confirmation_appetite_cents": 90000000,
}
_BENEFICIARY = {"beneficiary_name": "Riga Sawmill SIA", "country_code": "LV"}


def _parties(**facility_overrides):
    """The standard four counterparties: a NO applicant, a NO bank and an LV beneficiary."""
    facility = {"limit_cents": 50000000, "collateral_required_pct": 0}
    facility.update(facility_overrides)
    return setup_parties(
        applicant=dict(_APPLICANT),
        facility=facility,
        bank=dict(_BANK),
        beneficiary=dict(_BENEFICIARY),
    )


class TestAStaleCreditVersionOnAnAmendmentDraftIsRefused:
    """The amendment create endpoint compares `expected_credit_version` to the live version.

    Drafting is itself a write on the credit, so the very act of drafting invalidates the
    version the drafter quoted. That is the whole point of the guard: a second writer holding
    the older view would otherwise silently supersede an amendment it never saw.
    """

    @staticmethod
    def _an_issued_credit():
        return issued_credit(_parties())

    def test_the_first_draft_advances_the_credit_and_the_stale_second_draft_is_412(self, clock):
        """A rejected write creates no row and moves no version.

        PRD 2.8: "A `POST /credits/{id}/amendments` request must carry `expected_credit_version`
        as a required, non-optional field holding the `version` of the `DocumentaryCredit` the
        client last observed."
        PRD 2.8: "If that value does not equal the credit's current `version`, the create is
        rejected with `ERR_STALE_CREDIT_VERSION` (HTTP 412)."
        PRD 3.5: "Because drafting is itself a write on the credit, the credit's own `version`
        increments — which is exactly why a second draft attempted from the same captured
        version is rejected."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_expected_credit_version_on_amendment_create_returns_412
        """
        ctx = self._an_issued_credit()
        v1 = ctx.refresh()["version"]

        first = draft_amendment(ctx, {"amount_cents": 9000000}, expected_credit_version=v1)
        assert_fields_equal(first, status="DRAFT", seq=1, requires_beneficiary_consent=True)

        v2 = ctx.refresh()["version"]
        assert v2 == v1 + 1, "drafting an amendment advances the parent credit's version"

        stale = api_client.create_amendment(
            ctx.credit_id,
            factories.amendment_payload({"amount_cents": 9000000}, v1),
            trade_finance_officer_headers(TRADE_FINANCE_OFFICER_2),
        )
        validate_error(stale, "ERR_STALE_CREDIT_VERSION", 412)

        rows, meta = validate_paginated(
            api_client.list_credit_amendments(ctx.credit_id, trade_finance_officer_headers())
        )
        assert meta["total_count"] == 1, "the stale write created nothing"
        assert [row["id"] for row in rows] == [first["id"]]
        assert ctx.refresh()["version"] == v2, "a rejected write does not increment the version"

    def test_re_reading_the_live_version_admits_the_identical_payload_and_supersedes(self, clock):
        """The guard is a live comparison, not a one-shot refusal — and it protects a real row.

        PRD 3.5: "When a newer amendment is created for a credit while an earlier one is still
        `DRAFT`, the earlier one moves `DRAFT → SUPERSEDED` as a system event, taking
        `resolved_at` at the clock instant and `window_end_effective` at the clock date, and
        incrementing its own `version`."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_expected_credit_version_on_amendment_create_returns_412
        """
        ctx = self._an_issued_credit()
        v1 = ctx.refresh()["version"]
        first = draft_amendment(ctx, {"amount_cents": 9000000}, expected_credit_version=v1)
        v2 = ctx.refresh()["version"]
        assert v2 == v1 + 1

        second = draft_amendment(
            ctx,
            {"amount_cents": 9000000},
            expected_credit_version=v2,
            user_id=TRADE_FINANCE_OFFICER_2,
        )
        assert_fields_equal(second, status="DRAFT", seq=2)
        v3 = ctx.refresh()["version"]
        assert v3 == v2 + 1

        rows = list_amendment_rows(ctx.credit_id)
        assert [row["seq"] for row in rows] == [1, 2]
        superseded = next(row for row in rows if row["id"] == first["id"])
        assert_fields_equal(
            superseded,
            status="SUPERSEDED",
            resolved_at=THE_CLOCK_INSTANT,
            window_end_effective=THE_CLOCK_DATE,
        )
        assert superseded["version"] == first["version"] + 1

        _, meta = validate_paginated(
            api_client.list_credit_amendments(ctx.credit_id, trade_finance_officer_headers())
        )
        assert meta["total_count"] == 2


class TestAStaleFacilityVersionOnACollateralPostingIsRefused:
    """The second concurrency rule, on a different parent entity and a different version field.

    Collateral postings stack additively, so a repeated posting would succeed on its own merits
    and no other precondition in the service could refuse it. Only the stale version can, which
    is what makes the rule load-bearing: an implementation that ignored the field would end this
    recipe holding three million rather than two.
    """

    @staticmethod
    def _a_facility():
        applicant = create_applicant(**dict(_APPLICANT))
        return create_facility(
            applicant["id"], limit_cents=50000000, collateral_required_pct=40
        )

    @staticmethod
    def _read(facility_id):
        return validate_success(api_client.get_facility(facility_id, credit_officer_headers()))

    def test_the_accepted_posting_advances_the_version_and_the_repeat_is_412(self, clock):
        """The refused posting moves neither the collateral ledger nor the version.

        PRD 2.8: "A `POST /facilities/{id}/collateral-postings` request must carry
        `expected_facility_version` as a required, non-optional field holding the `version` of
        the `CreditFacility` the client last observed."
        PRD 2.8: "If that value does not equal the facility's current `version`, the posting is
        rejected with `ERR_STALE_FACILITY_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_expected_facility_version_on_collateral_posting_returns_412
        """
        facility = self._a_facility()
        assert facility["collateral_posted_cents"] == 0
        fv1 = facility["version"]

        post_collateral(facility["id"], 1000000, fv1)
        after_first = self._read(facility["id"])
        assert after_first["collateral_posted_cents"] == 1000000
        fv2 = after_first["version"]
        assert fv2 == fv1 + 1

        stale = api_client.create_collateral_posting(
            facility["id"],
            factories.collateral_posting_payload(1000000, fv1),
            credit_officer_headers(),
        )
        validate_error(stale, "ERR_STALE_FACILITY_VERSION", 412)

        unmoved = self._read(facility["id"])
        assert unmoved["collateral_posted_cents"] == 1000000
        assert unmoved["version"] == fv2

    def test_quoting_the_fresh_version_stacks_the_second_posting_additively(self, clock):
        """Two accepted postings and one refused one leave exactly two million on the ledger.

        PRD 3.1: "The facility's `collateral_posted_cents` becomes its previous value plus the
        supplied `amount_cents`, postings being applied in arrival order, and the facility's
        `version` increments."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_expected_facility_version_on_collateral_posting_returns_412
        """
        facility = self._a_facility()
        fv1 = facility["version"]

        post_collateral(facility["id"], 1000000, fv1)
        fv2 = self._read(facility["id"])["version"]

        refused = api_client.create_collateral_posting(
            facility["id"],
            factories.collateral_posting_payload(1000000, fv1),
            credit_officer_headers(),
        )
        validate_error(refused, "ERR_STALE_FACILITY_VERSION", 412)

        post_collateral(facility["id"], 1000000, fv2)
        final = self._read(facility["id"])
        assert final["collateral_posted_cents"] == 2000000
        assert final["version"] == fv2 + 1
        assert_facility_ledger(final, allocated_cents=0, available_cents=50000000)


class TestTheConfirmingBankSelectorAppliesTheWholePolicy:
    """Both halves of the selector must hold: it ranks a live pool, and it refuses an empty one.

    With `confirming_bank_id` omitted the server owns the whole decision. It must not fall back
    to the beneficiary's nominated bank, and it must not take the first row registered; it must
    rank the surviving candidates and take the highest weighted score. When nothing survives the
    filters the answer is a named 422, not a null confirming bank.
    """

    @staticmethod
    def _network():
        """A NO advising bank, an SE candidate scoring 940 and a DK candidate scoring 750."""
        parties = _parties()
        sydbanken = create_bank(
            bank_name="Sydbanken",
            swift_bic="SYDBSESS",
            country_code="SE",
            country_risk_score=10,
            credit_rating="AA",
            confirmation_appetite_cents=90000000,
        )
        oresund = create_bank(
            bank_name="Oresund Handelsbank",
            swift_bic="ORHBDKKK",
            country_code="DK",
            country_risk_score=25,
            credit_rating="A",
            confirmation_appetite_cents=90000000,
        )
        return parties, sydbanken, oresund

    def test_the_omitted_confirming_bank_is_chosen_by_weighted_score(self, clock):
        """Sydbanken at 940 beats both the nominated advising bank at 928 and Oresund at 750.

        PRD 3.4: "The candidate pool is every registered bank whose `status` is `ACTIVE`, whose
        `sanctions_flag` is false, whose `country_risk_score` is at most 60, whose `country_code`
        differs from the beneficiary's `country_code`, which has not already returned a decline
        on this very credit, and whose peak concurrent occupancy including this candidate credit
        is at most its own `confirmation_appetite_cents`."
        PRD 3.4: "Each surviving candidate is ranked by its `eligibility_score`: 100 minus its
        `country_risk_score`, multiplied by 6, plus its rating points multiplied by 4, where the
        rating points are 100 for `AA`, 75 for `A`, 50 for `BBB` and 25 for `BB`."
        PRD 3.4: "Confirming moves `confirmation_status` `CONFIRMATION_REQUESTED → CONFIRMED` and
        finally prices the confirmation charge."

        Design: Corner/cross_cutting_complexity_layers/selector_policy_confirming_bank_auto_selection_then_an_empty_eligible_pool
        """
        parties, sydbanken, oresund = self._network()
        assert sydbanken["eligibility_score"] == 940
        assert oresund["eligibility_score"] == 750
        assert parties.advising_bank["eligibility_score"] == 928

        ctx = issued_credit(parties)
        credit = request_confirmation(ctx.credit_id)

        assert credit["confirming_bank_id"] == sydbanken["id"]
        assert credit["confirming_bank_id"] != parties.advising_bank_id, (
            "the nominated advising bank is not automatically the confirming bank"
        )
        assert credit["confirming_bank_id"] != oresund["id"], (
            "the lower weighted score loses even from a third country"
        )
        assert_fields_equal(
            credit, confirmation_status="CONFIRMATION_REQUESTED", confirmation_charge_cents=0
        )
        assert ctx.refresh()["confirming_bank_id"] == sydbanken["id"]

    def test_an_empty_candidate_pool_is_refused_and_leaves_the_credit_unconfirmed(self, clock):
        """An SE beneficiary excludes the SE candidate, and the other two are suspended.

        PRD 3.4: "If the candidate pool is empty the request is refused with
        `ERR_NO_ELIGIBLE_CONFIRMING_BANK` (422); there is no deferred queue and no retry
        scheduling, and the credit simply stays `UNCONFIRMED` or `CONFIRMATION_DECLINED` as it
        was."
        PRD 3.1: "A bank that becomes ineligible simply stops being a candidate for new
        confirmation requests."

        Design: Corner/cross_cutting_complexity_layers/selector_policy_confirming_bank_auto_selection_then_an_empty_eligible_pool
        """
        parties, sydbanken, oresund = self._network()
        malmo = create_beneficiary(
            parties.advising_bank_id, beneficiary_name="Malmo Timber AB", country_code="SE"
        )
        ctx = issued_credit(
            Parties(
                applicant=parties.applicant,
                facility=parties.facility,
                advising_bank=parties.advising_bank,
                beneficiary=malmo,
            )
        )

        for bank_id in (oresund["id"], parties.advising_bank_id):
            suspended = validate_success(
                api_client.patch_bank(
                    bank_id, {"status": "SUSPENDED"}, compliance_officer_headers()
                )
            )
            assert suspended["status"] == "SUSPENDED"

        response = api_client.create_confirmation_request(
            ctx.credit_id,
            factories.confirmation_request_payload(),
            trade_finance_officer_headers(),
        )
        validate_error(response, "ERR_NO_ELIGIBLE_CONFIRMING_BANK", 422)

        credit = ctx.refresh()
        assert credit["confirming_bank_id"] is None
        assert_fields_equal(credit, status="ISSUED", confirmation_status="UNCONFIRMED")
        assert sydbanken["country_code"] == malmo["country_code"], (
            "the one bank left ACTIVE is domiciled in the beneficiary's own country"
        )


class TestTheExpirySweepIsACheckpointRatherThanAReplayableMutation:
    """The sweep must be a checkpoint: it reports what it moved, then has nothing left to move.

    Two properties are proved against the same fixture. A dry run reports exactly the counters
    the real run will produce and yet mutates nothing, so a reader cannot tell the two apart by
    the counters alone — only by the state. And a second real run at the same logical clock finds
    the rows it would have moved outside the eligible set, so every counter comes back zero.
    """

    @staticmethod
    def _a_file_awaiting_a_waiver():
        """A 4,000,000 drawing presented on Monday, found discrepant, with a waiver pending."""
        ctx = issued_credit(_parties())
        pctx = submitted_presentation(ctx, invoice_amounts=(4000000,))
        assert_end_of_day_instant(
            pctx.presentation["examination_deadline"], "2026-08-17", "the examination period"
        )
        raise_discrepancy(pctx, "GOODS_DESCRIPTION_MISMATCH", severity="MINOR")
        conclude_examination(pctx)
        assert pctx.refresh()["examination_status"] == "DISCREPANT"

        waiver = request_waiver(pctx, ["GOODS_DESCRIPTION_MISMATCH"])
        assert waiver["status"] == "PENDING"
        assert_end_of_day_instant(waiver["deadline_at"], "2026-08-12", "the waiver window")
        assert pctx.refresh()["examination_status"] == "WAIVER_REQUESTED"
        return pctx, waiver

    @staticmethod
    def _waiver_status(pctx, waiver):
        row = next(
            r for r in list_waiver_request_rows(pctx.presentation_id) if r["id"] == waiver["id"]
        )
        return row["status"]

    def test_the_dry_run_reports_the_counters_it_refuses_to_apply(self, clock):
        """Identical counters, opposite effect: the presentation and the waiver do not move.

        PRD 3.9: "When `dry_run` is true the counts are reported and nothing is mutated."
        PRD 3.9: "Pass one precludes presentations: every presentation whose
        `examination_deadline` has passed while its `examination_status` is `UNDER_EXAMINATION`,
        `DISCREPANT` or `WAIVER_REQUESTED` moves to `PRECLUDED`, and because the bank lost its
        right to refuse and must honour, the drawing stays reserved."
        PRD 3.9: "Pass two expires waiver requests: every request past its `deadline_at` while
        `PENDING` moves to `EXPIRED` and its cited discrepancies move `IDENTIFIED → UPHELD`."

        Design: Corner/cross_cutting_complexity_layers/ops_run_checkpoint_second_sweep_at_the_same_clock_reports_all_zeros
        """
        pctx, waiver = self._a_file_awaiting_a_waiver()
        set_clock(PAST_BOTH_DEADLINES)

        dry = run_sweep(dry_run=True)
        assert_sweep_counters(
            dry, presentations_precluded=1, waiver_requests_expired=1, credits_expired=0
        )
        assert pctx.refresh()["examination_status"] == "WAIVER_REQUESTED"
        assert self._waiver_status(pctx, waiver) == "PENDING"
        assert [row["status"] for row in list_discrepancy_rows(pctx.presentation_id)] == [
            "IDENTIFIED"
        ]

        real = run_sweep()
        assert_sweep_counters(
            real,
            presentations_precluded=1,
            waiver_requests_expired=1,
            credits_expired=0,
            allocations_released=0,
        )
        presentation = pctx.refresh()
        assert_fields_equal(
            presentation, examination_status="PRECLUDED", settlement_status="UNSETTLED"
        )
        assert self._waiver_status(pctx, waiver) == "EXPIRED"
        assert [row["status"] for row in list_discrepancy_rows(pctx.presentation_id)] == ["UPHELD"]
        assert pctx.refresh_credit()["reserved_cents"] == 4000000, (
            "a precluded drawing stays reserved because the bank is bound to honour it"
        )

    def test_a_second_sweep_at_the_same_clock_reports_every_counter_as_zero(self, clock):
        """The rows the first run moved are no longer in any pass's eligible set.

        PRD 3.9: "The sweep runs five passes in a fixed order, and each pass processes its rows in
        `created_at` ascending order, which makes the whole sweep deterministic and idempotent — a
        second sweep at the same clock returns all zeros."
        PRD 3.9: "Pass four expires credits: every credit whose `presentation_deadline_date` is
        strictly before the clock date, whose `status` is `ISSUED`, and whose `reserved_cents` is
        zero moves to `EXPIRED`, which is terminal, releasing its `OPEN` FacilityAllocation and
        any confirmation occupation it held."

        Design: Corner/cross_cutting_complexity_layers/ops_run_checkpoint_second_sweep_at_the_same_clock_reports_all_zeros
        """
        pctx, waiver = self._a_file_awaiting_a_waiver()
        set_clock(PAST_BOTH_DEADLINES)

        first = run_sweep()
        assert_sweep_counters(first, presentations_precluded=1, waiver_requests_expired=1)
        assert pctx.refresh()["examination_status"] == "PRECLUDED"

        second = run_sweep()
        assert_all_sweep_counters_zero(second, SWEEP_COUNTERS)

        assert pctx.refresh()["examination_status"] == "PRECLUDED"
        assert self._waiver_status(pctx, waiver) == "EXPIRED"
        assert [row["status"] for row in list_discrepancy_rows(pctx.presentation_id)] == ["UPHELD"]
        credit = pctx.refresh_credit()
        assert_fields_equal(credit, status="ISSUED", reserved_cents=4000000)
        assert_facility_ledger(
            pctx.parties.refresh_facility(), allocated_cents=10025000, available_cents=39975000
        )

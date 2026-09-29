"""Endpoint shapes: envelopes, action endpoints, nested scoping, computed reads and PATCH.

The create-read-listing trio and its two envelope shapes, the discrepancy and waiver actions
that each return their own row while the side effects land on the parent presentation, the
operational sweep's six independent counters and its writeless dry run, the amendment listing
scoped to one credit, the facility ledger that a read must never rewrite, the approve endpoint
that forks on its decision enum, and the partial bank update that re-derives eligibility
without unwinding a live confirmation.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    api_client,
    approve_credit,
    assert_end_of_day_instant,
    assert_facility_ledger,
    assert_fields_equal,
    assert_sweep_counters,
    compliance_officer_headers,
    conclude_examination,
    create_bank,
    create_facility,
    credit_officer_headers,
    draft_amendment,
    draft_credit,
    factories,
    issued_credit,
    list_amendment_rows,
    list_discrepancy_rows,
    list_facility_allocation_rows,
    raise_discrepancy,
    request_confirmation,
    request_waiver,
    respond_to_confirmation,
    respond_to_waiver,
    run_sweep,
    set_clock,
    setup_parties,
    submit_credit_for_approval,
    submitted_presentation,
    trade_finance_officer_headers,
)

MONDAY_14 = "2026-09-14T09:00:00Z"
AFTER_THE_DEADLINE = "2026-11-22T09:00:00Z"

_APPLICANT = {"country_code": "NO"}
_BANK = {"country_code": "NO", "country_risk_score": 12, "credit_rating": "AA"}
_BENEFICIARY = {"country_code": "LV"}

SWEEP_COUNTERS = (
    "credits_expired",
    "presentations_precluded",
    "waiver_requests_expired",
    "amendments_lapsed",
    "allocations_released",
    "facilities_reactivated",
)


def _parties(limit_cents=50000000, **facility_overrides):
    facility = {"limit_cents": limit_cents, "collateral_required_pct": 0}
    facility.update(facility_overrides)
    return setup_parties(
        applicant=dict(_APPLICANT),
        facility=facility,
        bank=dict(_BANK),
        beneficiary=dict(_BENEFICIARY),
    )


def _read_facility(facility_id, headers=None):
    return api_client.get_facility(facility_id, headers or credit_officer_headers())


class TestApplicantCreateReadAndChildListing:
    """One envelope shape for the single read, another for the child collection."""

    def test_the_read_round_trips_the_row_and_the_child_listing_paginates(self, clock):
        """Every stored field survives the round trip; only the listing carries pagination.

        PRD 2.4: "`created_at` and `updated_at` are ISO 8601 UTC timestamps with exactly three
        fractional digits, and `version` is an integer that starts at 1 when the row is created
        and increases by exactly 1 on every mutation of that row."

        PRD 2.3: "List responses report all four pagination fields in `meta`: the effective
        `limit`, the effective `offset`, the `total_count` of rows matching the filter before
        the page window is applied, and `has_more`, which is true exactly when rows remain
        beyond the current window."

        PRD 2.2: "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`,
        `has_more`) are included for list endpoints."

        Design: Corner/endpoints/standard_crud_applicant_create_read_and_child_listing
        """
        created = validate_success(
            api_client.create_applicant(
                factories.applicant_payload(
                    legal_name="Baltic Timber Imports AS",
                    country_code="NO",
                    industry_code="4669",
                    internal_risk_grade="A",
                ),
                credit_officer_headers(),
            ),
            201,
        )
        first = create_facility(created["id"], limit_cents=50000000, collateral_required_pct=0)
        set_clock("2026-08-10T09:05:00Z")
        second = create_facility(created["id"], limit_cents=20000000, collateral_required_pct=25)

        read = api_client.get_applicant(created["id"], trade_finance_officer_headers())
        applicant = validate_success(read)

        assert_fields_equal(
            applicant,
            id=created["id"],
            legal_name="Baltic Timber Imports AS",
            country_code="NO",
            industry_code="4669",
            internal_risk_grade="A",
            kyc_status="CLEARED",
            status="ACTIVE",
            version=created["version"],
        )
        assert applicant["sanctions_flag"] is False
        assert applicant["created_at"] == "2026-08-10T09:00:00.000Z"
        object_body = read.json()
        assert object_body["response_type"] == "object"
        assert object_body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(object_body["meta"]["api_request_timestamp"], str)
        for pagination_field in ("limit", "offset", "total_count", "has_more"):
            assert pagination_field not in object_body["meta"]

        listing = api_client.list_applicant_facilities(created["id"], credit_officer_headers())
        rows, meta = validate_paginated(listing)

        assert listing.json()["response_type"] == "array"
        assert_fields_equal(meta, limit=10, offset=0, total_count=2)
        assert meta["has_more"] is False
        assert [row["id"] for row in rows] == [first["id"], second["id"]]
        assert rows[0]["created_at"] < rows[1]["created_at"]
        assert rows[0]["currency"] == "USD"
        assert rows[0]["limit_cents"] == 50000000
        assert rows[1]["limit_cents"] == 20000000


class TestTheApproveEndpointForksOnItsDecisionEnum:
    """One endpoint, two outcomes, and no facility debit on either branch."""

    def test_approve_grants_permission_while_return_to_draft_reopens_the_terms(self, clock):
        """Q1 lands `APPROVED`, Q2 walks back to `DRAFT` and is submittable again.

        Neither branch touches the facility: the whole 50,000,000 is still free and no
        allocation row exists, because the limit is only consumed at issuance.

        PRD 3.3: "Returning the credit takes it `PENDING_CREDIT_APPROVAL → DRAFT` and
        increments its `version`; that is the whole of that branch's effect, and it is what
        makes the drafting loop cyclic."

        PRD 3.3: "Approval grants permission and nothing more — **no facility debit happens
        here**. The limit is consumed at issuance."

        PRD 3.2: "A returned draft may be resubmitted, so the `DRAFT → PENDING_CREDIT_APPROVAL
        → DRAFT` loop can repeat without limit."

        Design: Corner/endpoints/conditional_action_approve_endpoint_forks_on_the_decision_enum
        """
        parties = _parties()
        first = draft_credit(parties)
        second = draft_credit(parties)
        submit_credit_for_approval(first.credit_id)
        pending_second = submit_credit_for_approval(second.credit_id)

        approved = approve_credit(first.credit_id)
        returned = approve_credit(second.credit_id, decision="RETURN_TO_DRAFT")
        resubmitted = submit_credit_for_approval(second.credit_id)

        assert_fields_equal(
            approved, status="APPROVED", committed_allocation_cents=0, total_charge_cents=0
        )
        assert approved["issue_date"] is None
        assert_fields_equal(returned, status="DRAFT")
        assert returned["version"] == pending_second["version"] + 1
        assert resubmitted["status"] == "PENDING_CREDIT_APPROVAL"
        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=0,
            available_cents=50000000,
            status="ACTIVE",
            utilisation_posture="OPEN",
        )
        assert list_facility_allocation_rows(parties.facility_id) == []


class TestTheDiscrepancyAndWaiverActionsReturnTheirOwnRows:
    """Each action returns the row its own contract names; the parent absorbs the effects."""

    @staticmethod
    def _under_examination():
        """An issued credit with a 4,000,000 file submitted on Monday 2026-09-14."""
        parties = _parties()
        ctx = issued_credit(parties)
        set_clock(MONDAY_14)
        pctx = submitted_presentation(ctx, invoice_amounts=(4000000,))
        return ctx, pctx

    def test_the_discrepancy_and_waiver_posts_each_return_their_own_row(self, clock):
        """A Discrepancy comes back from one endpoint and a WaiverRequest from the other.

        The waiver window closes two days after the request while the five banking days keep
        running underneath it, so `deadline_at` is the earlier 2026-09-16 end-of-day and not the
        2026-09-21 examination deadline.

        PRD 3.7: "Each new row takes `status` `IDENTIFIED`, records `raised_by_user_id` as the
        acting `X-User-ID`, sets the presentation's `examined_by_user_id` to the same value, and
        increments the presentation's `discrepancy_count`."

        PRD 3.7: "The request takes `status` `PENDING`, `requested_at` at the clock instant and
        `requested_by_user_id` as the acting examiner, and moves the presentation `DISCREPANT →
        WAIVER_REQUESTED`."

        PRD 3.7: "Its own `deadline_at` is the **earlier** of two instants: the date part of
        `requested_at` plus two days at `23:59:59.999Z`, and the presentation's
        `examination_deadline`."

        Design: Corner/endpoints/action_endpoint_discrepancy_waiver_flow_returns_the_parent_row
        """
        _ctx, pctx = self._under_examination()
        assert_end_of_day_instant(
            pctx.refresh()["examination_deadline"], "2026-09-21", "examination_deadline"
        )

        discrepancy = raise_discrepancy(pctx, "GOODS_DESCRIPTION_MISMATCH", severity="MINOR")
        concluded = conclude_examination(pctx)
        waiver = request_waiver(pctx, ["GOODS_DESCRIPTION_MISMATCH"])

        assert_fields_equal(
            discrepancy,
            presentation_id=pctx.presentation_id,
            code="GOODS_DESCRIPTION_MISMATCH",
            severity="MINOR",
            status="IDENTIFIED",
        )
        assert "examination_status" not in discrepancy
        assert_fields_equal(concluded, examination_status="DISCREPANT", discrepancy_count=1)
        assert_fields_equal(
            waiver,
            presentation_id=pctx.presentation_id,
            status="PENDING",
            discrepancy_codes=["GOODS_DESCRIPTION_MISMATCH"],
        )
        assert "discrepancy_count" not in waiver
        assert waiver["requested_at"] == "2026-09-14T09:00:00.000Z"
        assert_end_of_day_instant(waiver["deadline_at"], "2026-09-16", "deadline_at")
        assert waiver["deadline_at"] != pctx.refresh()["examination_deadline"]
        assert pctx.refresh()["examination_status"] == "WAIVER_REQUESTED"

    def test_the_grant_waives_the_named_defect_and_the_parent_turns_complying(self, clock):
        """The respond endpoint returns the WaiverRequest; the Discrepancy and file both move.

        PRD 3.7: "`GRANT` moves the request `PENDING → GRANTED` and every cited Discrepancy
        `IDENTIFIED → WAIVED`, which lowers `discrepancy_count`."

        PRD 3.7: "Where the presentation lands then depends on whether the waiver was total: if
        `discrepancy_count` reaches zero the presentation moves `WAIVER_REQUESTED → COMPLYING`
        and may be settled, but if at least one `IDENTIFIED` discrepancy remains uncited and
        therefore unwaived, the presentation returns `WAIVER_REQUESTED → DISCREPANT` instead."

        PRD 3.7: "Either answer sets `responded_at` to the clock instant."

        Design: Corner/endpoints/action_endpoint_discrepancy_waiver_flow_returns_the_parent_row
        """
        ctx, pctx = self._under_examination()
        raise_discrepancy(pctx, "GOODS_DESCRIPTION_MISMATCH", severity="MINOR")
        conclude_examination(pctx)
        waiver = request_waiver(pctx, ["GOODS_DESCRIPTION_MISMATCH"])

        answered = respond_to_waiver(waiver["id"], ctx.parties.applicant_id, "GRANT")

        assert_fields_equal(answered, id=waiver["id"], status="GRANTED")
        assert answered["responded_at"] == "2026-09-14T09:00:00.000Z"
        assert [row["status"] for row in list_discrepancy_rows(pctx.presentation_id)] == ["WAIVED"]
        assert_fields_equal(
            pctx.refresh(),
            examination_status="COMPLYING",
            settlement_status="UNSETTLED",
            discrepancy_count=0,
        )
        assert ctx.refresh()["reserved_cents"] == 4000000


class TestTheAmendmentListingIsScopedToItsParentCredit:
    """Two siblings on one facility, each with its own amendment and its own counter."""

    def test_each_credits_listing_returns_only_its_own_amendment_at_seq_one(self, clock):
        """`seq` is per credit, so both amendments are 1 and neither listing sees the other.

        PRD 3.5: "A successful draft sets `status` to `DRAFT`, records `drafted_by_user_id` as
        the acting `X-User-ID`, and assigns `seq` as one plus the number of Amendment rows that
        already exist for this credit."

        PRD 2.3: "Two endpoints deviate deliberately and their ordering is part of their
        contract: the bank directory is ordered by `eligibility_score` descending, then by
        `country_risk_score` ascending, then by `created_at` ascending; and the amendment list
        of one credit is ordered by `seq` ascending."

        Design: Corner/endpoints/cross_reference_link_amendment_listing_is_scoped_to_its_parent_credit
        """
        parties = _parties()
        first = issued_credit(parties)
        second = issued_credit(parties)

        first_amendment = draft_amendment(first, {"amount_cents": 12000000})
        second_amendment = draft_amendment(second, {"amount_cents": 12000000})

        assert first_amendment["seq"] == 1
        assert second_amendment["seq"] == 1
        for credit, amendment in ((first, first_amendment), (second, second_amendment)):
            rows, meta = validate_paginated(
                api_client.list_credit_amendments(
                    credit.credit_id, compliance_officer_headers()
                )
            )
            assert meta["total_count"] == 1
            assert meta["has_more"] is False
            assert_fields_equal(
                rows[0],
                id=amendment["id"],
                credit_id=credit.credit_id,
                seq=1,
                status="DRAFT",
            )
        assert [row["id"] for row in list_amendment_rows(first.credit_id, status="DRAFT")] == [
            first_amendment["id"]
        ]
        assert_fields_equal(first.refresh(), status="ISSUED", amount_cents=10000000)
        assert_fields_equal(second.refresh(), status="ISSUED", amount_cents=10000000)


class TestTheExpirySweepReportsSixCountersAndItsDryRunWritesNothing:
    """One credit falls due, one sibling never leaves `DRAFT`, and the dry run is inert."""

    @staticmethod
    def _one_expiring_credit():
        """S1 is issued with a 2026-11-21 deadline and never presented against; S2 stays DRAFT."""
        parties = _parties()
        live = issued_credit(parties)
        drafted = draft_credit(parties)
        return parties, live, drafted

    def test_the_dry_run_reports_the_same_counters_and_mutates_nothing(self, clock):
        """credits_expired 1 and allocations_released 1 are reported while the credit stays put.

        PRD 3.10: "Every clock-driven transition is then applied by a single operational sweep,
        which a `SystemOperator` runs with an optional `dry_run` flag and which reports the
        counters `credits_expired`, `presentations_precluded`, `waiver_requests_expired`,
        `amendments_lapsed`, `allocations_released` and `facilities_reactivated`. When `dry_run`
        is true the counts are reported and nothing is mutated."

        Design: Corner/endpoints/bulk_action_expiry_sweep_reports_per_pass_counters_and_dry_run_writes_nothing
        """
        parties, live, drafted = self._one_expiring_credit()
        assert live.refresh()["presentation_deadline_date"] == "2026-11-21"
        set_clock(AFTER_THE_DEADLINE)

        report = run_sweep(dry_run=True)

        assert sorted(field for field in SWEEP_COUNTERS if field in report) == sorted(
            SWEEP_COUNTERS
        )
        assert_sweep_counters(
            report,
            credits_expired=1,
            allocations_released=1,
            presentations_precluded=0,
            waiver_requests_expired=0,
            amendments_lapsed=0,
            facilities_reactivated=0,
        )
        assert live.refresh()["status"] == "ISSUED"
        assert drafted.refresh()["status"] == "DRAFT"
        assert_facility_ledger(
            parties.refresh_facility(), allocated_cents=10025000, available_cents=39975000
        )
        assert [row["status"] for row in list_facility_allocation_rows(parties.facility_id)] == [
            "OPEN"
        ]

    def test_the_real_run_expires_the_credit_and_releases_its_allocation(self, clock):
        """The same counters now come with the writes: `EXPIRED`, `RELEASED` and a free line.

        PRD 3.10: "Pass four expires credits: every credit whose `presentation_deadline_date` is
        strictly before the clock date, whose `status` is `ISSUED`, and whose `reserved_cents` is
        zero moves to `EXPIRED`, which is terminal, releasing its `OPEN` FacilityAllocation and
        any confirmation occupation it held."

        PRD 3.3: "Every `OPEN` allocation row of the credit flips to `RELEASED` with
        `released_cents` set to that row's own `allocated_cents` plus its `charge_cents` and
        `released_at` set to the clock instant, and the row's `version` increments."

        Design: Corner/endpoints/bulk_action_expiry_sweep_reports_per_pass_counters_and_dry_run_writes_nothing
        """
        parties, live, drafted = self._one_expiring_credit()
        set_clock(AFTER_THE_DEADLINE)

        report = run_sweep()

        assert_sweep_counters(
            report,
            credits_expired=1,
            allocations_released=1,
            presentations_precluded=0,
            waiver_requests_expired=0,
            amendments_lapsed=0,
            facilities_reactivated=0,
        )
        assert live.refresh()["status"] == "EXPIRED"
        assert drafted.refresh()["status"] == "DRAFT"
        rows = list_facility_allocation_rows(parties.facility_id)
        assert len(rows) == 1
        assert_fields_equal(
            rows[0], credit_id=live.credit_id, status="RELEASED", released_cents=10025000
        )
        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=0,
            available_cents=50000000,
            status="ACTIVE",
            utilisation_posture="OPEN",
        )


class TestTheFacilityLedgerIsDerivedAndAReadNeverWrites:
    """Two identical reads separated by nothing must agree and must not bump `version`."""

    def test_two_reads_of_the_same_ledger_agree_and_leave_the_version_alone(self, clock):
        """20,050,000 occupied and 29,950,000 free, reported twice at one unchanged `version`.

        PRD 3.1: "`allocated_cents` is recomputed as the sum, over every allocation row on this
        facility whose `status` is `OPEN`, of that row's `allocated_cents` plus its
        `charge_cents`; released rows are excluded from the sum entirely"

        PRD 2.4: "`created_at` and `updated_at` are ISO 8601 UTC timestamps with exactly three
        fractional digits, and `version` is an integer that starts at 1 when the row is created
        and increases by exactly 1 on every mutation of that row."

        Design: Corner/endpoints/computed_read_facility_ledger_is_derived_and_the_read_writes_nothing
        """
        parties = _parties()
        issued_credit(parties)
        issued_credit(parties)

        first = validate_success(_read_facility(parties.facility_id))
        second = validate_success(
            _read_facility(parties.facility_id, compliance_officer_headers())
        )

        assert_facility_ledger(
            first,
            allocated_cents=20050000,
            available_cents=29950000,
            restrict_threshold_cents=47500000,
            utilisation_posture="OPEN",
            status="ACTIVE",
        )
        assert_fields_equal(
            second,
            allocated_cents=first["allocated_cents"],
            available_cents=first["available_cents"],
            restrict_threshold_cents=first["restrict_threshold_cents"],
            utilisation_posture=first["utilisation_posture"],
            version=first["version"],
            updated_at=first["updated_at"],
        )
        rows, meta = validate_paginated(
            api_client.list_facility_allocations(parties.facility_id, credit_officer_headers())
        )
        assert meta["total_count"] == 2
        for row in rows:
            assert_fields_equal(
                row, status="OPEN", allocated_cents=10000000, charge_cents=25000
            )


class TestABankPatchIsPartialAndForwardLooking:
    """Only `country_risk_score` is named, and the live confirmation survives untouched."""

    @staticmethod
    def _confirmed_and_pending_credits():
        """Helvetia confirms P1 at an `eligibility_score` of 810; P2 is issued and unconfirmed."""
        parties = _parties()
        helvetia = create_bank(
            bank_name="Helvetia Trade Bank",
            swift_bic="HVTBCHZZ",
            country_code="CH",
            country_risk_score=15,
            credit_rating="A",
            confirmation_appetite_cents=40000000,
        )
        confirmed = issued_credit(parties)
        request_confirmation(confirmed.credit_id, helvetia["id"])
        respond_to_confirmation(confirmed.credit_id, helvetia["id"], "CONFIRM")
        unconfirmed = issued_credit(parties)
        return helvetia, confirmed, unconfirmed

    def test_the_patch_keeps_every_unnamed_field_and_re_derives_the_score(self, clock):
        """The score falls 810 to 510 while name, BIC, country, rating and appetite survive.

        PRD 3.1: "Either a `CreditOfficer` or a `ComplianceOfficer` may revise its `status`,
        `sanctions_flag`, `country_risk_score`, `confirmation_appetite_cents` or
        `credit_rating`, and `eligibility_score` is re-derived from the new `country_risk_score`
        and `credit_rating` on the spot."

        PRD 3.1: "Such a revision is forward-looking as well: it does **not** unwind
        confirmations the bank has already given."

        Design: Corner/endpoints/bank_patch_applies_a_partial_update_and_rederives_eligibility
        """
        helvetia, confirmed, _unconfirmed = self._confirmed_and_pending_credits()
        assert helvetia["eligibility_score"] == 810

        patched = validate_success(
            api_client.patch_bank(
                helvetia["id"], {"country_risk_score": 65}, compliance_officer_headers()
            )
        )

        assert_fields_equal(
            patched,
            id=helvetia["id"],
            country_risk_score=65,
            eligibility_score=510,
            bank_name="Helvetia Trade Bank",
            swift_bic="HVTBCHZZ",
            country_code="CH",
            credit_rating="A",
            confirmation_appetite_cents=40000000,
            status="ACTIVE",
            confirming_line_used_cents=10000000,
        )
        assert patched["eligibility_score"] != 810
        assert patched["sanctions_flag"] is False
        assert_fields_equal(
            confirmed.refresh(),
            confirmation_status="CONFIRMED",
            confirming_bank_id=helvetia["id"],
        )

    def test_the_next_request_naming_the_downgraded_bank_is_refused(self, clock):
        """65 breaches the ceiling of 60, so P2 may not name Helvetia at all.

        PRD 3.4: "Whichever bank ends up resolved must be eligible: its `status` must be
        `ACTIVE`, its `sanctions_flag` must be false, its `country_risk_score` must be at most
        60, and it must not be domiciled in the beneficiary's own country — that is, its
        `country_code` must differ from the beneficiary's `country_code`, since a confirmation
        from within the exporter's own jurisdiction adds no country-risk cover."

        PRD 3.4: "A named bank failing any of these is refused with
        `ERR_CONFIRMING_BANK_INELIGIBLE` (422)."

        Design: Corner/endpoints/bank_patch_applies_a_partial_update_and_rederives_eligibility
        """
        helvetia, confirmed, unconfirmed = self._confirmed_and_pending_credits()
        validate_success(
            api_client.patch_bank(
                helvetia["id"], {"country_risk_score": 65}, compliance_officer_headers()
            )
        )

        response = api_client.create_confirmation_request(
            unconfirmed.credit_id,
            factories.confirmation_request_payload(helvetia["id"]),
            trade_finance_officer_headers(),
        )

        validate_error(response, "ERR_CONFIRMING_BANK_INELIGIBLE", 422)
        assert_fields_equal(unconfirmed.refresh(), confirmation_status="UNCONFIRMED")
        assert unconfirmed.refresh()["confirming_bank_id"] is None
        assert confirmed.refresh()["confirmation_status"] == "CONFIRMED"

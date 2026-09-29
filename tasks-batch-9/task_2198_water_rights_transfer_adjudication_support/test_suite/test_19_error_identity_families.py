"""Error identity: which rule fires, and which one deliberately does not.

PRD §2.11: "The first violated rule wins, its error is returned, and no later
rule is evaluated — so a request that breaks three rules at once produces exactly
one, fully determined error code."
"""
import pytest
from test_helpers import (
    assert_same_instant,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import (
    create_adjudication_claim_payload,
    create_deposit_payload,
    create_beneficial_use_record_payload,
    create_decree_docket_payload,
    create_protest_payload,
    create_transfer_application_payload,
    resolve_protest_payload,
    create_water_right_payload,
)
from test_helpers.fixtures import (
    ADJUDICATOR,
    ANALYST,
    HEARING_OFFICER,
    activate_right,
    add_injury_analysis,
    add_use_record,
    add_use_records_from_spec,
    certify_study,
    create_claimant,
    create_study,
    create_water_right,
    deposit,
    file_claim,
    file_protest,
    open_account,
    open_docket,
    publish_application,
    read_account,
    read_application,
    read_claim,
    read_docket,
    read_right,
    route_protest,
    set_clock,
    setup_certified_right,
    setup_docket_in_objection_period,
    setup_published_application,
    setup_submitted_application,
)
from test_helpers.test_users import make_claimant_headers, make_headers

CLOCK = "2026-03-01T00:00:00Z"
FILING_DEADLINE = "2026-04-01T00:00:00Z"
RECORDED_PRIORITY = "1901-05-01T00:00:00Z"


def _records_of(right_id):
    data, meta = validate_paginated(api_client.list_beneficial_use_records(right_id, ANALYST))
    return data, meta


class TestFourUniquenessKeysOnOneFixture:
    """PRD §3.1, §3.2 and §3.10 — two global keys and two composite ones.

    `right_number` and `docket_number` are unique service-wide; the use-year key
    is unique per right and the claim key per docket-and-right pair. The
    composite keys are only proven composite by re-using the same value under a
    different parent and watching it succeed.
    """

    def _fixture(self):
        set_clock(CLOCK)
        claimant = create_claimant(
            "Vega Ditch Company",
            contact_email="ops@vega.example",
            entity_type="IRRIGATION_DISTRICT",
        )
        first = create_water_right(claimant["id"], right_number="WR-2198-001")
        second = create_water_right(claimant["id"], right_number="WR-2198-002")
        add_use_record(
            first["id"],
            2025,
            reported_diversion_af=300.000,
            irrigated_acres=100.00,
            verification_source="METER",
        )
        docket = open_docket(FILING_DEADLINE, docket_number="SNK-ADJ-08")
        claim = file_claim(docket["id"], first["id"], RECORDED_PRIORITY, 100.00)
        return {
            "claimant": claimant,
            "first": first,
            "second": second,
            "docket": docket,
            "claim": claim,
        }

    def test_the_right_number_is_unique_service_wide(self):
        """PRD §3.2: "a `right_number` of 1 to 40 characters that must be unique
        across every right in the service — a collision is
        `ERR_DUPLICATE_RIGHT_NUMBER` (HTTP 409)".

        Every other field of the rejected body differs from the incumbent's, and
        the claimant reference is perfectly valid, so the number alone is what
        collides. No third right comes into existence.

        Design: Corner/errors/err_uniqueness_family_four_distinct_duplicate_keys
        """
        fixture = self._fixture()
        before = read_right(fixture["first"]["id"])

        response = api_client.create_water_right(
            create_water_right_payload(
                fixture["claimant"]["id"],
                right_number="WR-2198-001",
                priority_date="1902-06-01T00:00:00Z",
                source_stream_code="SNK-15",
                purpose_of_use="MUNICIPAL",
                place_of_use_acres=40.00,
                authorized_diversion_af=100.00,
                authorized_rate_cfs=2.000,
            ),
            ANALYST,
        )

        validate_error(
            response, ApiErrorId.ERR_DUPLICATE_RIGHT_NUMBER.value, expected_status=409
        )
        _, meta = validate_paginated(api_client.list_water_rights(ANALYST))
        assert meta["total_count"] == 2
        incumbent = read_right(fixture["first"]["id"])
        assert incumbent["right_number"] == "WR-2198-001"
        assert incumbent["purpose_of_use"] == "IRRIGATION"
        assert incumbent["version"] == before["version"]

    def test_the_docket_number_is_unique_service_wide(self):
        """PRD §3.10: "a `docket_number` unique across all dockets — a collision is
        `ERR_DUPLICATE_DOCKET_NUMBER` (409)".

        A different `claim_filing_deadline` on the second docket makes no
        difference: the deadline is not part of the key.

        Design: Corner/errors/err_uniqueness_family_four_distinct_duplicate_keys
        """
        fixture = self._fixture()

        response = api_client.create_decree_docket(
            create_decree_docket_payload(
                "2026-05-01T00:00:00Z", docket_number="SNK-ADJ-08"
            ),
            ADJUDICATOR,
        )

        validate_error(
            response, ApiErrorId.ERR_DUPLICATE_DOCKET_NUMBER.value, expected_status=409
        )
        docket = read_docket(fixture["docket"]["id"])
        assert docket["docket_number"] == "SNK-ADJ-08"
        assert_same_instant(docket["claim_filing_deadline"], FILING_DEADLINE, "claim_filing_deadline")

    def test_the_use_year_key_is_scoped_to_its_right(self):
        """PRD §3.2: "Only one record may exist per right per calendar year; a
        second attempt at the same year is `ERR_DUPLICATE_USE_YEAR` (HTTP 409)."

        The rejected body carries a different volume and a different verification
        source, and the stored record is left exactly as it was: the collision is
        not an upsert. The very same 2025 on the sibling right is accepted, which
        is what makes the key composite rather than global.

        Design: Corner/errors/err_uniqueness_family_four_distinct_duplicate_keys
        """
        fixture = self._fixture()
        payload = create_beneficial_use_record_payload(
            2025,
            reported_diversion_af=250.000,
            irrigated_acres=90.00,
            verification_source="AERIAL_IMAGERY",
        )

        rejected = api_client.create_beneficial_use_record(
            fixture["first"]["id"], payload, ANALYST
        )
        accepted = api_client.create_beneficial_use_record(
            fixture["second"]["id"], payload, ANALYST
        )

        validate_error(
            rejected, ApiErrorId.ERR_DUPLICATE_USE_YEAR.value, expected_status=409
        )
        assert accepted.status_code == 201
        assert get_success_data(accepted)["use_year"] == 2025
        stored, meta = _records_of(fixture["first"]["id"])
        assert meta["total_count"] == 1
        assert stored[0]["reported_diversion_af"] == pytest.approx(300.000, abs=0.0005)
        assert stored[0]["verification_source"] == "METER"

    def test_the_claim_key_is_scoped_to_its_docket_and_right(self):
        """PRD §3.10: "First, only one claim may exist for a given
        docket-and-right pair, a second attempt yielding `ERR_DUPLICATE_CLAIM`
        (409)."

        The repeat carries half the volume and is still a repeat, and PRD §3.10's
        "Filing recomputes the docket's `claim_count` and bumps the docket's
        `version`" does not happen on a rejection. Filing the same right's twin
        into the same docket is accepted, so the pair is the key.

        Design: Corner/errors/err_uniqueness_family_four_distinct_duplicate_keys
        """
        fixture = self._fixture()
        before = read_docket(fixture["docket"]["id"])

        response = api_client.create_adjudication_claim(
            create_adjudication_claim_payload(
                fixture["docket"]["id"], fixture["first"]["id"], RECORDED_PRIORITY, 50.00
            ),
            ADJUDICATOR,
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_CLAIM.value, expected_status=409)
        after = read_docket(fixture["docket"]["id"])
        assert after["claim_count"] == 1
        assert after["version"] == before["version"]
        assert read_claim(fixture["claim"]["id"])["claimed_af"] == pytest.approx(
            100.00, abs=0.01
        )
        sibling = file_claim(
            fixture["docket"]["id"], fixture["second"]["id"], RECORDED_PRIORITY, 50.00
        )
        assert sibling["filing_status"] == "FILED"
        assert read_docket(fixture["docket"]["id"])["claim_count"] == 2


class TestTheHolderCannotProtestTheirOwnTransfer:
    """PRD §3.6 — the caller is the named protestant, so ownership is satisfied.

    The self-dealing rule has to be its own implementation: an ownership check
    alone would wave this call straight through, since the `X-User-ID` and the
    `protestant_claimant_id` agree perfectly.
    """

    def _published(self):
        bundle = setup_published_application(requested_af=100.00, clock=CLOCK)
        bundle["stranger"] = create_claimant(
            "Bell Cattle Trust",
            contact_email="b@bell.example",
            entity_type="INDIVIDUAL",
        )
        return bundle

    def test_the_self_filing_is_a_self_dealing_failure_not_an_ownership_failure(self):
        """PRD §3.6: "The `protestant_claimant_id` must differ from the
        `claimant_id` of the right behind the protested application, since a
        claimant cannot protest their own transfer, and a self-filing is
        `ERR_SELF_PROTEST_FORBIDDEN` (HTTP 422)."

        PRD §2.1: "protest filing and withdrawal compare against the protest's
        `protestant_claimant_id`" — and the caller is that protestant, so the
        ownership check of §2.1 is satisfied and its `ERR_NOT_RESOURCE_OWNER`
        (HTTP 403) has nothing to fire on.

        Design: Corner/errors/err_self_protest_forbidden_owner_cannot_protest_own_application
        """
        bundle = self._published()
        holder = bundle["claimant"]["id"]

        response = api_client.create_protest(
            create_protest_payload(bundle["application"]["id"], holder, 10.00),
            make_claimant_headers(holder),
        )

        validate_error(
            response, ApiErrorId.ERR_SELF_PROTEST_FORBIDDEN.value, expected_status=422
        )
        _, meta = validate_paginated(api_client.list_protests(ANALYST))
        assert meta["total_count"] == 0
        application = read_application(bundle["application"]["id"])
        assert application["status"] == "PROTEST_PERIOD"
        assert application["unresolved_protest_count"] == 0

    def test_a_strangers_identical_filing_is_accepted(self):
        """PRD §3.6: "A new protest lands in `FILED` with `track` unset and
        `stipulated_offset_af` at 0.00. The filing itself drives the application:
        the first protest moves it `PROTEST_PERIOD → UNDER_PROTEST`, and each
        additional protestant leaves it at `UNDER_PROTEST → UNDER_PROTEST` while
        raising `unresolved_protest_count`".

        Every field of the body but the protestant is the one the holder was
        refused, so the protestant identity is the whole difference.

        Design: Corner/errors/err_self_protest_forbidden_owner_cannot_protest_own_application
        """
        bundle = self._published()

        protest = file_protest(
            bundle["application"]["id"], bundle["stranger"]["id"], 10.00
        )

        assert protest["status"] == "FILED"
        assert protest["track"] is None
        assert protest["stipulated_offset_af"] == pytest.approx(0.00, abs=0.01)
        application = read_application(bundle["application"]["id"])
        assert application["status"] == "UNDER_PROTEST"
        assert application["unresolved_protest_count"] == 1


class TestTheClaimantBehindAClaimCannotObjectToIt:
    """PRD §2.1 — the one endpoint where holding the resource is disqualifying:
    "an objector must *not* own the objected claim, and that inverse check
    carries its own error code."

    Both calls are identical but for the operator identifier, and the identifier
    that owns the claimed right is the one that is refused.
    """

    DEADLINE_REACHED = "2026-04-02T00:00:00Z"

    def _objection_period(self):
        bundle = setup_docket_in_objection_period(
            clock=CLOCK,
            examiner_recommended_af=90.00,
            claim_filing_deadline=FILING_DEADLINE,
            deadline_reached_at=self.DEADLINE_REACHED,
            claimed_af=100.00,
            use_years=(2025,),
        )
        bundle["stranger"] = create_claimant(
            "Bell Cattle Trust",
            contact_email="b@bell.example",
            entity_type="INDIVIDUAL",
        )
        return bundle

    def _object(self, claim_id, headers, note):
        return api_client.object_to_adjudication_claim(
            claim_id, "QUANTITY", note, headers
        )

    def test_the_owning_claimant_is_refused(self):
        """PRD §3.10: "The operator identifier must differ from the `claimant_id`
        of the water right named by the claim, otherwise
        `ERR_SELF_OBJECTION_FORBIDDEN` (422)."

        Nothing on the claim moves: PRD §3.10 has "The first objection moves the
        claim `EXAMINED → OBJECTED`", and no objection was recorded here.

        Design: Corner/errors/err_self_objection_forbidden_claimant_cannot_object_to_own_claim
        """
        bundle = self._objection_period()
        before = read_claim(bundle["claim"]["id"])

        response = self._object(
            bundle["claim"]["id"],
            make_claimant_headers(bundle["claimant"]["id"]),
            "Owner objecting to their own examined claim.",
        )

        validate_error(
            response, ApiErrorId.ERR_SELF_OBJECTION_FORBIDDEN.value, expected_status=422
        )
        after = read_claim(bundle["claim"]["id"])
        assert after["filing_status"] == "EXAMINED"
        assert after["objection_count"] == 0
        assert after["version"] == before["version"]

    def test_an_unrelated_claimants_identical_objection_lands(self):
        """PRD §3.10: "Objecting is available to any claimant other than the one
        behind the claim, and to the adjudicator, while the docket reads
        `OBJECTION_PERIOD`."

        The stranger holds no right on this docket at all, and is welcome
        precisely for that reason: the objection is recorded and the claim's
        procedural axis advances while its evidentiary axis stays where the field
        verification left it.

        Design: Corner/errors/err_self_objection_forbidden_claimant_cannot_object_to_own_claim
        """
        bundle = self._objection_period()

        objected = get_success_data(
            self._object(
                bundle["claim"]["id"],
                make_claimant_headers(bundle["stranger"]["id"]),
                "Downstream senior disputes the quantity.",
            )
        )

        assert objected["filing_status"] == "OBJECTED"
        assert objected["objection_count"] == 1
        assert objected["verification_status"] == "FIELD_VERIFIED"
        assert read_docket(bundle["docket"]["id"])["phase"] == "OBJECTION_PERIOD"


class TestEnrolmentIsCheckedBeforeVolume:
    """PRD §3.9 — two sibling rights certified at 195.00 AF, one enrolled.

    The deposit asks for 10.00 acre-feet, which is well inside either right's
    transferable volume, so the volume gate has nothing to say and the enrolment
    flag is the only thing that separates the refusal from the acceptance.
    """

    STUDY_YEARS = (2023, 2024, 2025)

    def _two_certified_rights(self):
        bundle = setup_certified_right(clock=CLOCK)
        enrolled = create_water_right(
            bundle["claimant"]["id"], right_number="WR-2198-002", bank_enrolled=True
        )
        add_use_records_from_spec(
            enrolled["id"],
            [(year, 300.000, 100.00, "METER") for year in self.STUDY_YEARS],
        )
        activate_right(enrolled["id"])
        study = get_success_data(
            create_study(enrolled["id"], 2023, 2025, "DIVERSION_BASED")
        )
        certify_study(study["id"], enrolled["id"])
        bundle["enrolled"] = read_right(enrolled["id"])
        bundle["account"] = open_account(bundle["claimant"]["id"])
        return bundle

    def test_an_unenrolled_right_cannot_fund_a_deposit(self):
        """PRD §3.9: "the right's `bank_enrolled` flag must be set, otherwise
        `ERR_RIGHT_NOT_BANK_ENROLLED` (422); and `deposit_af` must be no greater
        than the right's `transferable_af` as the ledger stands at the moment of
        the call, with equality accepted, otherwise
        `ERR_TRANSFERABLE_VOLUME_EXCEEDED`."

        PRD §3.2 makes the flag opt-in: "an optional `bank_enrolled` flag that
        defaults to false", so a fully certified, fully transferable right is
        still not bankable. Neither ledger moves on the refusal.

        Design: Corner/errors/err_right_not_bank_enrolled_blocks_the_deposit
        """
        bundle = self._two_certified_rights()
        account_before = bundle["account"]

        response = api_client.create_deposit(
            account_before["id"],
            create_deposit_payload(bundle["right"]["id"], 10.00, account_before["version"]),
            ANALYST,
        )

        validate_error(
            response, ApiErrorId.ERR_RIGHT_NOT_BANK_ENROLLED.value, expected_status=422
        )
        right = read_right(bundle["right"]["id"])
        assert right["transferable_af"] == pytest.approx(195.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(0.00, abs=0.01)
        assert right["status"] == "ACTIVE"
        account = read_account(account_before["id"])
        assert account["deposited_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert account["leased_out_af"] == pytest.approx(0.00, abs=0.01)
        assert account["version"] == account_before["version"]

    def test_the_enrolled_sibling_takes_the_identical_deposit(self):
        """PRD §3.9: "On success `deposited_credit_af` and `available_credit_af`
        both increase by `deposit_af`, which conserves the credit identity because
        the deposit lands in the unencumbered bucket; the posture is recomputed,
        so a deposit can lift an account off the low-credit `RESTRICTED` trigger;
        and on the source right the volume moves out of `transferable_af` and into
        `encumbered_af`, conserving the right identity and re-deriving the status
        from `ACTIVE` to `ENCUMBERED`."

        Same account, same 10.00 acre-feet, same operator — only the source right
        differs, and it differs in exactly one field.

        Design: Corner/errors/err_right_not_bank_enrolled_blocks_the_deposit
        """
        bundle = self._two_certified_rights()

        deposit(bundle["account"]["id"], bundle["enrolled"]["id"], 10.00)

        account = read_account(bundle["account"]["id"])
        assert account["deposited_credit_af"] == pytest.approx(10.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(10.00, abs=0.01)
        assert account["posture"] == "OPEN"
        source = read_right(bundle["enrolled"]["id"])
        assert source["transferable_af"] == pytest.approx(185.00, abs=0.01)
        assert source["encumbered_af"] == pytest.approx(10.00, abs=0.01)
        assert source["status"] == "ENCUMBERED"
        untouched = read_right(bundle["right"]["id"])
        assert untouched["transferable_af"] == pytest.approx(195.00, abs=0.01)


class TestTheStipulatedOffsetBoundIsTwoSided:
    """PRD §3.6 — one 10.00 AF claim, three stipulations, one error id.

    A protest claiming 10.00 acre-feet of injury is routed to negotiation, and
    the offset offered against it is walked from just above the claim, to zero, to
    the claim itself.
    """

    def _negotiating_protest(self):
        bundle = setup_published_application(requested_af=100.00, clock=CLOCK)
        bundle["protestant"] = create_claimant(
            "Bell Cattle Trust",
            contact_email="b@bell.example",
            entity_type="INDIVIDUAL",
        )
        protest = file_protest(
            bundle["application"]["id"], bundle["protestant"]["id"], 10.00
        )
        bundle["protest"] = route_protest(protest["id"], "NEGOTIATION")
        return bundle

    def _stipulate(self, protest_id, stipulated_offset_af, note):
        return api_client.resolve_protest(
            protest_id,
            resolve_protest_payload(
                "STIPULATE",
                resolution_note=note,
                stipulated_offset_af=stipulated_offset_af,
            ),
            HEARING_OFFICER,
        )

    def test_one_hundredth_above_the_claim_is_refused(self):
        """PRD §3.6: "A `NEGOTIATION` protest with `outcome` `STIPULATE` requires
        `stipulated_offset_af`, which must be strictly greater than 0.00 and no
        greater than the protest's `claimed_injury_af`, with equality accepted; a
        value at or below zero or above the claim is `ERR_OFFSET_EXCEEDS_CLAIM`
        (HTTP 422)."

        The protest stays exactly where routing left it, so the refusal is not a
        partial resolution.

        Design: Corner/errors/err_offset_exceeds_claim_bounds_the_negotiated_stipulation_on_both_ends
        """
        bundle = self._negotiating_protest()

        response = self._stipulate(
            bundle["protest"]["id"], 10.01, "One hundredth over the claim."
        )

        validate_error(
            response, ApiErrorId.ERR_OFFSET_EXCEEDS_CLAIM.value, expected_status=422
        )
        protest = get_success_data(
            api_client.get_protest(bundle["protest"]["id"], ANALYST)
        )
        assert protest["status"] == "IN_NEGOTIATION"
        assert protest["stipulated_offset_af"] == pytest.approx(0.00, abs=0.01)
        application = read_application(bundle["application"]["id"])
        assert application["status"] == "UNDER_PROTEST"
        assert application["unresolved_protest_count"] == 1

    def test_a_zero_value_stipulation_is_refused_under_the_same_error_id(self):
        """PRD §3.6: "a value at or below zero or above the claim is
        `ERR_OFFSET_EXCEEDS_CLAIM` (HTTP 422)."

        Both ends of the bound carry the same identity, so a zero-value
        stipulation cannot buy a cheap clearance; the claim itself then resolves
        the protest at exact equality, and PRD §3.6's clearance cascade follows:
        "The application auto-transitions `UNDER_PROTEST → READY_FOR_DECISION`;
        its `DRAFT` injury analysis moves to the terminal `FINALIZED`, freezing
        `gross_depletion_af`, `offset_af` and `net_injury_af`".

        Design: Corner/errors/err_offset_exceeds_claim_bounds_the_negotiated_stipulation_on_both_ends
        """
        bundle = self._negotiating_protest()

        refused = self._stipulate(
            bundle["protest"]["id"], 0.00, "Zero-value stipulation."
        )
        accepted = get_success_data(
            self._stipulate(bundle["protest"]["id"], 10.00, "Full claim stipulated.")
        )

        validate_error(
            refused, ApiErrorId.ERR_OFFSET_EXCEEDS_CLAIM.value, expected_status=422
        )
        assert accepted["status"] == "RESOLVED_STIPULATED"
        assert accepted["stipulated_offset_af"] == pytest.approx(10.00, abs=0.01)
        analysis = get_success_data(
            api_client.get_injury_analysis(bundle["analysis"]["id"], ANALYST)
        )
        assert analysis["status"] == "FINALIZED"
        assert analysis["gross_depletion_af"] == pytest.approx(78.00, abs=0.01)
        assert analysis["offset_af"] == pytest.approx(10.00, abs=0.01)
        assert analysis["net_injury_af"] == pytest.approx(68.00, abs=0.01)
        application = read_application(bundle["application"]["id"])
        assert application["status"] == "READY_FOR_DECISION"
        assert application["unresolved_protest_count"] == 0


class TestBothForeignKeysResolveButDisagreeWithEachOther:
    """PRD §3.4 — a per-field foreign-key check would wave this body through.

    The study exists, the right exists, and they belong to the same claimant;
    what fails is the relationship between the two references, which is a check no
    amount of per-field validation performs.
    """

    def test_a_cross_wired_body_is_a_coherence_failure(self):
        """PRD §3.4: "Separately, the referenced study must belong to the same
        right the application names, and a proposed headgate, when supplied, must
        belong to that same right; either mismatch is `ERR_STUDY_RIGHT_MISMATCH`
        (HTTP 422)."

        The named right is still `UNADJUDICATED` with nothing transferable, so a
        state-flavoured refusal is also available on these facts — but PRD §2.11
        orders "body foreign-key existence; then the domain-specific referential,
        uniqueness, concurrency, state, safety, temporal, constraint and fiscal
        families in that sequence", which puts the referential mismatch first.

        Design: Corner/errors/err_study_right_mismatch_when_the_cited_study_belongs_to_another_right
        """
        bundle = setup_certified_right(clock=CLOCK)
        bare = create_water_right(bundle["claimant"]["id"], right_number="WR-2198-002")

        response = api_client.create_transfer_application(
            create_transfer_application_payload(bare["id"], bundle["study"]["id"], 50.00),
            ANALYST,
        )

        validate_error(
            response, ApiErrorId.ERR_STUDY_RIGHT_MISMATCH.value, expected_status=422
        )
        _, meta = validate_paginated(api_client.list_transfer_applications(ANALYST))
        assert meta["total_count"] == 0
        assert read_right(bare["id"])["pending_review_count"] == 0
        assert read_right(bare["id"])["status"] == "UNADJUDICATED"

    def test_the_same_body_aimed_at_the_studys_own_right_is_accepted(self):
        """PRD §3.4: "A drafted application sits in `DRAFT`. No volume is
        escrowed, `escrowed_af` reads 0.00, and no bucket on the right has moved."

        Only the `water_right_id` changes between the refused body and this one,
        so the coherence rule is the whole of the difference.

        Design: Corner/errors/err_study_right_mismatch_when_the_cited_study_belongs_to_another_right
        """
        bundle = setup_certified_right(clock=CLOCK)

        response = api_client.create_transfer_application(
            create_transfer_application_payload(
                bundle["right"]["id"], bundle["study"]["id"], 50.00
            ),
            ANALYST,
        )

        application = get_success_data(response, expected_status=201)
        assert application["status"] == "DRAFT"
        assert application["escrowed_af"] == pytest.approx(0.00, abs=0.01)
        right = read_right(bundle["right"]["id"])
        assert right["encumbered_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(195.00, abs=0.01)


class TestPublicationNeedsAnAnalysisOnRecord:
    """PRD §3.5 — the escrow and the analysis are independent steps.

    An application can sit `SUBMITTED` with its whole requested volume already
    out of the right's transferable bucket and still have nothing for protestants
    to read, and that is precisely the state publication refuses.
    """

    def _submitted_without_analysis(self):
        return setup_submitted_application(requested_af=100.00, clock=CLOCK)

    def test_publishing_an_unanalysed_application_is_refused(self):
        """PRD §3.5: "It requires an injury analysis to already exist so that
        protestants have something to respond to; an application with neither a
        `DRAFT` nor a `FINALIZED` analysis is rejected with
        `ERR_INJURY_ANALYSIS_MISSING` (HTTP 422)."

        The escrow taken at submission is untouched by the refusal, which is what
        makes the two steps independent. PRD §3.4: "A successful submission moves
        the application `DRAFT → SUBMITTED` and sets `escrowed_af` to
        `requested_af`."

        Design: Corner/errors/err_injury_analysis_missing_blocks_publication_of_an_unanalyzed_application
        """
        bundle = self._submitted_without_analysis()

        response = api_client.publish_transfer_application(
            bundle["application"]["id"], ANALYST
        )

        validate_error(
            response, ApiErrorId.ERR_INJURY_ANALYSIS_MISSING.value, expected_status=422
        )
        application = read_application(bundle["application"]["id"])
        assert application["status"] == "SUBMITTED"
        assert application["protest_deadline"] is None
        assert application["version"] == bundle["application"]["version"]
        assert application["escrowed_af"] == pytest.approx(100.00, abs=0.01)
        right = read_right(bundle["right"]["id"])
        assert right["transferable_af"] == pytest.approx(95.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(100.00, abs=0.01)
        assert right["status"] == "ENCUMBERED"

    def test_analysing_the_application_unblocks_the_identical_publication(self):
        """PRD §3.5: "`protest_deadline` is stamped from the logical clock at
        thirty days out on a first publication, when `revision_round` is 0, and at
        fifteen days out on every republication after a revision, when
        `revision_round` is 1 or more".

        The analysis is a child row rather than a field on the application, and
        creating it is all that stood between the same call and a 200.

        Design: Corner/errors/err_injury_analysis_missing_blocks_publication_of_an_unanalyzed_application
        """
        bundle = self._submitted_without_analysis()

        analysis = add_injury_analysis(
            bundle["application"]["id"], "SEASONAL_AVERAGE", 0.00
        )
        published = publish_application(bundle["application"]["id"])

        assert analysis["status"] == "DRAFT"
        assert analysis["gross_depletion_af"] == pytest.approx(78.00, abs=0.01)
        assert analysis["offset_af"] == pytest.approx(0.00, abs=0.01)
        assert analysis["net_injury_af"] == pytest.approx(78.00, abs=0.01)
        assert read_right(bundle["right"]["id"])["pending_review_count"] == 1
        assert published["status"] == "PROTEST_PERIOD"
        assert_same_instant(published["protest_deadline"], "2026-03-31T00:00:00Z", "protest_deadline")


class TestAuthenticationRunsAheadOfEverythingElse:
    """PRD §2.1 — three header defects, one error identity.

    None of these calls should reach the resource layer at all, so the fixture is
    a single claimant and nothing else: whatever the body says and whatever the
    path points at, the answer is the same.
    """

    UNDECLARED_ROLE = "Auditor"

    def _claimant_only(self):
        set_clock(CLOCK)
        return create_claimant(
            "Vega Ditch Company",
            contact_email="ops@vega.example",
            entity_type="IRRIGATION_DISTRICT",
        )

    def test_missing_headers_and_an_undeclared_role_share_one_identity(self):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming the role that user
        is acting in. If either header is absent or blank, or if `X-User-Role`
        carries a value outside the five declared roles, the request is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401)."

        An unknown role is an authentication failure, not an authorization one:
        PRD §2.1 reserves `ERR_ROLE_NOT_PERMITTED` for the case where "the headers
        are well formed but the named role is not authorized for the endpoint
        being called".

        Design: Corner/errors/err_unauthenticated_header_family_precedes_every_other_check
        """
        claimant = self._claimant_only()

        bare = api_client.list_water_rights({})
        undeclared = api_client.create_water_right(
            create_water_right_payload(claimant["id"], right_number="WR-2198-900"),
            make_headers("u-auditor-1", self.UNDECLARED_ROLE),
        )

        validate_error(bare, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)
        validate_error(
            undeclared, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401
        )
        _, meta = validate_paginated(api_client.list_water_rights(ANALYST))
        assert meta["total_count"] == 0

    def test_the_header_check_pre_empts_the_body_and_the_path(self):
        """PRD §2.1: "These two checks are the first and second things this service
        ever evaluates, in that order."

        PRD §2.11 puts "header presence and role membership" above both
        "path-parameter existence" and "request-body well-formedness", so a body
        missing every required field still reads 401 rather than
        `ERR_INVALID_REQUEST`, and an id matching no row still reads 401 rather
        than `ERR_WATER_RIGHT_NOT_FOUND`.

        Design: Corner/errors/err_unauthenticated_header_family_precedes_every_other_check
        """
        self._claimant_only()
        headers = make_headers("u-auditor-1", self.UNDECLARED_ROLE)

        bad_body = api_client.create_water_right({"right_number": "WR-2198-901"}, headers)
        bad_path = api_client.get_water_right(NON_EXISTENT_UUID, headers)

        validate_error(
            bad_body, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401
        )
        validate_error(
            bad_path, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401
        )
        _, meta = validate_paginated(api_client.list_water_rights(ANALYST))
        assert meta["total_count"] == 0

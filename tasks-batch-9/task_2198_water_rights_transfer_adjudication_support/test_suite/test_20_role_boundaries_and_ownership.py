"""Who may act, whose rows they may act on, and who is disqualified by history.

PRD §2.12: "an analyst can neither adjudicate a protest nor decide an
application, a hearing officer never renders a final disposition, a decision
authority is barred from every preparatory step, and the basin adjudicator —
despite being the department's administrative backstop for documentation, banking
and leasing — cannot adjudicate protests, cannot decide transfers and cannot file
a protest."
"""
import pytest
from test_helpers import (
    ApiErrorId,
    api_client,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import (
    create_adjudication_claim_payload,
    create_beneficial_use_record_payload,
    create_deposit_payload,
    create_decree_docket_payload,
    create_hcu_study_payload,
    create_protest_payload,
    decide_payload,
    resolve_protest_payload,
)
from test_helpers.fixtures import (
    ADJUDICATOR,
    ANALYST,
    DECIDER,
    HEARING_OFFICER,
    activate_right,
    add_injury_analysis,
    certify_study,
    create_claimant,
    create_study,
    draft_application,
    file_protest,
    open_account,
    open_docket,
    publish_application,
    read_account,
    read_application,
    read_claimant,
    read_right,
    route_protest,
    setup_base_right,
    setup_documented_right,
    setup_draft_application,
    setup_published_application,
    submit_application,
)
from test_helpers.constants import TEST_DEFAULTS
from test_helpers.test_users import (
    make_analyst_headers,
    make_claimant_headers,
    make_decision_authority_headers,
    make_hearing_officer_headers,
)

CLOCK = "2026-03-01T00:00:00Z"
FILING_DEADLINE = "2026-04-01T00:00:00Z"
PRIORITY_DATE = TEST_DEFAULTS["PRIORITY_DATE"]


class TestEachExclusiveOperationRefusesEveryPeerRole:
    """PRD §4 — the role model is peer-to-peer, not a hierarchy.

    Every refusal below is aimed at a role that is powerful elsewhere in the very
    same workflow, which is what makes the refusals informative: the analyst
    prepared the file, the hearing officer resolved its protests, and the
    adjudicator administers everything else about it.
    """

    def _fixture(self):
        bundle = setup_published_application(requested_af=100.00, clock=CLOCK)
        bundle["protestant"] = create_claimant(
            "Bell Cattle Trust",
            contact_email="b@bell.example",
            entity_type="INDIVIDUAL",
        )
        bundle["protest"] = file_protest(
            bundle["application"]["id"], bundle["protestant"]["id"], 10.00
        )
        bundle["docket"] = open_docket(FILING_DEADLINE, docket_number="SNK-ADJ-10")
        return bundle

    def test_the_disposition_belongs_to_one_role_and_three_are_refused(self):
        """PRD §3.7: "Only a `DecisionAuthority` may render a disposition, and it
        is that role's sole mutating capability — no other role may approve,
        condition, or deny a transfer."

        The application is `UNDER_PROTEST`, so a permitted role would fail on
        state instead — but PRD §2.11 puts "header presence and role membership"
        above everything, so all three refusals are the 403.

        Design: Corner/rbac/rbac_exclusive_operation_matrix_five_roles_five_owners
        """
        bundle = self._fixture()
        payload = decide_payload("DENY", decision_note="Attempting a disposition.")

        for headers in (ANALYST, HEARING_OFFICER, ADJUDICATOR):
            response = api_client.decide_transfer_application(
                bundle["application"]["id"], payload, headers
            )
            validate_error(
                response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, expected_status=403
            )

        application = read_application(bundle["application"]["id"])
        assert application["status"] == "UNDER_PROTEST"
        assert application["decided_by_user_id"] is None
        assert application["escrowed_af"] == pytest.approx(100.00, abs=0.01)

    def test_the_adjudicator_is_not_a_superuser(self):
        """PRD §2.12: "the basin adjudicator — despite being the department's
        administrative backstop for documentation, banking and leasing — cannot
        adjudicate protests, cannot decide transfers and cannot file a protest."

        Routing belongs to the hearing officer and opening a study belongs to the
        analyst, and the broadest role in the service holds neither.

        Design: Corner/rbac/rbac_exclusive_operation_matrix_five_roles_five_owners
        """
        bundle = self._fixture()

        routing = api_client.route_protest(
            bundle["protest"]["id"], "NEGOTIATION", ADJUDICATOR
        )
        study = api_client.create_hcu_study(
            bundle["right"]["id"], create_hcu_study_payload(2023, 2025), ADJUDICATOR
        )

        validate_error(
            routing, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, expected_status=403
        )
        validate_error(
            study, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, expected_status=403
        )
        protest = get_success_data(
            api_client.get_protest(bundle["protest"]["id"], ANALYST)
        )
        assert protest["status"] == "FILED"
        assert protest["track"] is None
        assert protest["version"] == bundle["protest"]["version"]

    def test_the_docket_is_the_adjudicators_alone_and_the_403_precedes_the_404(self):
        """PRD §3.10: "General stream adjudication is the `BasinAdjudicator`'s
        exclusive province at the docket level."

        The examine call deliberately names a docket identifier where a claim
        identifier belongs, and the answer is still the role error: PRD §2.11
        orders "header presence and role membership (`ERR_UNAUTHENTICATED`, then
        `ERR_ROLE_NOT_PERMITTED`); path-parameter existence".

        Design: Corner/rbac/rbac_exclusive_operation_matrix_five_roles_five_owners
        """
        bundle = self._fixture()

        docket = api_client.create_decree_docket(
            create_decree_docket_payload(FILING_DEADLINE, docket_number="SNK-ADJ-11"),
            ANALYST,
        )
        examine = api_client.examine_adjudication_claim(
            bundle["docket"]["id"], 10.00, "Wrong role.", HEARING_OFFICER
        )

        validate_error(
            docket, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, expected_status=403
        )
        validate_error(
            examine, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, expected_status=403
        )

    def test_only_a_claimant_may_file_a_protest(self):
        """PRD §3.6: "Filing a protest is the one operation reserved exclusively to
        the `Claimant` role — agency staff cannot file one on a claimant's behalf."

        The analyst supplies a perfectly well-formed body naming a genuine
        third-party protestant and is still refused, so the exclusivity is about
        the caller rather than about the protestant.

        Design: Corner/rbac/rbac_exclusive_operation_matrix_five_roles_five_owners
        """
        bundle = self._fixture()

        response = api_client.create_protest(
            create_protest_payload(
                bundle["application"]["id"], bundle["protestant"]["id"], 5.00
            ),
            ANALYST,
        )

        validate_error(
            response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, expected_status=403
        )
        _, meta = validate_paginated(api_client.list_protests(ANALYST))
        assert meta["total_count"] == 1
        application = read_application(bundle["application"]["id"])
        assert application["unresolved_protest_count"] == 1


class TestThreeWritersOnTheEvidenceLedgerAndFiveReaders:
    """PRD §3.2 — the evidence ledger is shared, and its rows are anonymous to
    every calculation that consumes them.

    Three roles each append one year, and the resulting three rows are
    interchangeable: the same volume, the same acreage and the same verification
    source, differing only in the year they report.
    """

    YEARS = ((2023, "claimant"), (2024, "analyst"), (2025, "adjudicator"))
    ASSESSMENT_FIELDS = (
        "forfeiture_risk_score",
        "forfeiture_risk_band",
        "nonuse_year_count",
        "consecutive_nonuse_years",
        "forfeiture_eligible",
    )

    def _writers(self, claimant_id):
        return {
            "claimant": make_claimant_headers(claimant_id),
            "analyst": ANALYST,
            "adjudicator": ADJUDICATOR,
        }

    def test_the_holder_the_analyst_and_the_adjudicator_all_write(self):
        """PRD §3.2: "Annual beneficial use is reported into an append-only
        evidence ledger, and claimants may file their own reports alongside
        analysts and the adjudicator."

        All three rows count as evidence, so PRD §3.2's perfection gate is
        satisfied whichever role supplied which year: "The single precondition is
        evidentiary: at least one beneficial-use record on the right must carry a
        `verification_source` of `METER` or `AERIAL_IMAGERY`."

        Design: Corner/rbac/rbac_shared_operations_three_writers_on_one_evidence_ledger_and_five_readers
        """
        bundle = setup_documented_right(CLOCK)
        writers = self._writers(bundle["claimant"]["id"])

        rows = []
        for year, writer in self.YEARS:
            response = api_client.create_beneficial_use_record(
                bundle["right"]["id"],
                create_beneficial_use_record_payload(
                    year,
                    reported_diversion_af=300.000,
                    irrigated_acres=100.00,
                    verification_source="METER",
                ),
                writers[writer],
            )
            assert response.status_code == 201
            rows.append(get_success_data(response))

        assert [row["use_year"] for row in rows] == [2023, 2024, 2025]
        for row in rows:
            assert row["reported_diversion_af"] == pytest.approx(300.000, abs=0.0005)
            assert row["irrigated_acres"] == pytest.approx(100.00, abs=0.01)
            assert row["verification_source"] == "METER"
        assert activate_right(bundle["right"]["id"])["status"] == "ACTIVE"

    def test_all_five_roles_read_the_same_assessment(self):
        """PRD §3.2: "Abandonment risk is scored on demand and after every event
        that could move it — appending a beneficial-use record, perfecting a right,
        reinstating a right, and any movement of the right into or out of
        `SUSPENDED`."

        The derived assessment is an unscoped read, so no role sees a different
        number from any other.

        Design: Corner/rbac/rbac_shared_operations_three_writers_on_one_evidence_ledger_and_five_readers
        """
        bundle = setup_documented_right(CLOCK)
        writers = self._writers(bundle["claimant"]["id"])
        for year, writer in self.YEARS:
            api_client.create_beneficial_use_record(
                bundle["right"]["id"],
                create_beneficial_use_record_payload(
                    year,
                    reported_diversion_af=300.000,
                    irrigated_acres=100.00,
                    verification_source="METER",
                ),
                writers[writer],
            )
        activate_right(bundle["right"]["id"])

        readers = [
            make_claimant_headers(bundle["claimant"]["id"]),
            ANALYST,
            HEARING_OFFICER,
            DECIDER,
            ADJUDICATOR,
        ]
        assessments = [
            get_success_data(
                api_client.get_forfeiture_assessment(bundle["right"]["id"], headers)
            )
            for headers in readers
        ]

        first = assessments[0]
        for other in assessments[1:]:
            for field in self.ASSESSMENT_FIELDS:
                assert other[field] == first[field], f"{field} differs by reader role"
        assert read_right(bundle["right"]["id"])["forfeiture_risk_score"] == pytest.approx(
            first["forfeiture_risk_score"], abs=0.01
        )


class TestOneOwnershipRuleWithFourDifferentDerivations:
    """PRD §2.1 — the same stranger is refused four different ways.

    Claimant A holds a certified, bank-enrolled right, a `DRAFT` application on it
    and a bank account; claimant B holds nothing at all, and every refusal below
    traces the ownership of the target back to a different column.
    """

    def _fixture(self):
        bundle = setup_draft_application(
            requested_af=50.00, clock=CLOCK, bank_enrolled=True
        )
        bundle["account"] = open_account(bundle["claimant"]["id"])
        bundle["docket"] = open_docket(FILING_DEADLINE)
        bundle["stranger"] = create_claimant(
            "Bell Cattle Trust",
            contact_email="b@bell.example",
            entity_type="INDIVIDUAL",
        )
        return bundle

    def test_the_rights_holder_column_governs_evidence_and_applications(self):
        """PRD §2.1: "right, application and approval-condition operations compare
        against the `claimant_id` of the governing `WaterRight`" — and "A mismatch
        is `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        The application's own row carries no claimant reference at all, so its
        ownership is inherited through the right it names.

        Design: Corner/rbac/rbac_claimant_ownership_scoping_across_four_resource_families
        """
        bundle = self._fixture()
        outsider = make_claimant_headers(bundle["stranger"]["id"])

        evidence = api_client.create_beneficial_use_record(
            bundle["right"]["id"],
            create_beneficial_use_record_payload(
                2022,
                reported_diversion_af=10.000,
                irrigated_acres=5.00,
                verification_source="AFFIDAVIT",
            ),
            outsider,
        )
        withdrawal = api_client.withdraw_transfer_application(
            bundle["application"]["id"], "Stranger attempting to withdraw.", outsider
        )

        validate_error(
            evidence, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, expected_status=403
        )
        validate_error(
            withdrawal, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, expected_status=403
        )
        _, meta = validate_paginated(
            api_client.list_beneficial_use_records(bundle["right"]["id"], ANALYST)
        )
        assert meta["total_count"] == 3
        assert read_application(bundle["application"]["id"])["status"] == "DRAFT"

    def test_the_accounts_own_holder_column_governs_deposits(self):
        """PRD §2.1: "water-bank-account and lease operations compare against the
        `claimant_id` of the `WaterBankAccount`".

        The source right is bank-enrolled, so PRD §3.9's enrolment gate has nothing
        to catch and the ownership rule is the only rule that can fire. Neither
        ledger moves and the account's `version` stands still.

        Design: Corner/rbac/rbac_claimant_ownership_scoping_across_four_resource_families
        """
        bundle = self._fixture()

        response = api_client.create_deposit(
            bundle["account"]["id"],
            create_deposit_payload(
                bundle["right"]["id"], 10.00, bundle["account"]["version"]
            ),
            make_claimant_headers(bundle["stranger"]["id"]),
        )

        validate_error(
            response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, expected_status=403
        )
        account = read_account(bundle["account"]["id"])
        assert account["deposited_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert account["version"] == bundle["account"]["version"]
        assert read_right(bundle["right"]["id"])["bank_enrolled"] is True

    def test_claims_read_the_claimed_right_and_protests_read_the_protestant(self):
        """PRD §2.1: "protest filing and withdrawal compare against the protest's
        `protestant_claimant_id`; and adjudication-claim filing compares against
        the `claimant_id` of the claimed right."

        The protest body names claimant A as the protestant while claimant B does
        the calling, which breaks the ownership rule and would also break the
        self-dealing rule; PRD §2.11 settles it: "Body well-formedness outranks
        every business rule but is itself outranked by ownership". The same claim
        body that the stranger cannot file is accepted from the holder, so the rule
        scopes by identity rather than by role.

        Design: Corner/rbac/rbac_claimant_ownership_scoping_across_four_resource_families
        """
        bundle = self._fixture()
        holder = bundle["claimant"]["id"]
        outsider = make_claimant_headers(bundle["stranger"]["id"])

        refused_claim = api_client.create_adjudication_claim(
            create_adjudication_claim_payload(
                bundle["docket"]["id"], bundle["right"]["id"], PRIORITY_DATE, 100.00
            ),
            outsider,
        )
        refused_protest = api_client.create_protest(
            create_protest_payload(bundle["application"]["id"], holder, 5.00), outsider
        )
        accepted = api_client.create_adjudication_claim(
            create_adjudication_claim_payload(
                bundle["docket"]["id"], bundle["right"]["id"], PRIORITY_DATE, 100.00
            ),
            make_claimant_headers(holder),
        )

        validate_error(
            refused_claim, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, expected_status=403
        )
        validate_error(
            refused_protest, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, expected_status=403
        )
        claim = get_success_data(accepted, expected_status=201)
        assert claim["filing_status"] == "FILED"
        _, meta = validate_paginated(api_client.list_protests(ANALYST))
        assert meta["total_count"] == 0


class TestTheCertifierAndTheResolverAreBothBarredFromDeciding:
    """PRD §2.12 — two recorded identities disqualify a would-be decider.

    One operator certified the study the application relies on and another
    resolved its only protest; both then present a `DecisionAuthority` header, and
    both are refused on identity. A third, uninvolved operator signs the same
    disposition.
    """

    CERTIFIER = "u-101"
    RESOLVER = "u-202"
    UNINVOLVED = "u-303"
    CLAIMED_INJURY = 78.00

    def _ready_for_decision(self):
        bundle = setup_base_right(CLOCK)
        study = get_success_data(create_study(bundle["right"]["id"], 2023, 2025))
        certify_study(
            study["id"],
            bundle["right"]["id"],
            headers=make_analyst_headers(self.CERTIFIER),
        )
        bundle["study"] = get_success_data(api_client.get_hcu_study(study["id"], ANALYST))
        application = draft_application(bundle["right"]["id"], study["id"], 100.00)
        bundle["analysis"] = add_injury_analysis(
            application["id"], "SEASONAL_AVERAGE", 0.00
        )
        submit_application(application["id"], bundle["right"]["id"])
        publish_application(application["id"])
        bundle["protestant"] = create_claimant(
            "Bell Cattle Trust",
            contact_email="b@bell.example",
            entity_type="INDIVIDUAL",
        )
        protest = file_protest(
            application["id"], bundle["protestant"]["id"], self.CLAIMED_INJURY
        )
        route_protest(protest["id"], "NEGOTIATION")
        bundle["protest"] = get_success_data(
            api_client.resolve_protest(
                protest["id"],
                resolve_protest_payload(
                    "STIPULATE",
                    resolution_note="Full claimed injury stipulated.",
                    stipulated_offset_af=self.CLAIMED_INJURY,
                ),
                make_hearing_officer_headers(self.RESOLVER),
            )
        )
        bundle["application"] = read_application(application["id"])
        return bundle

    def _decide_as(self, application_id, user_id):
        return api_client.decide_transfer_application(
            application_id,
            decide_payload("APPROVE", decision_note="Disposition attempt."),
            make_decision_authority_headers(user_id),
        )

    def test_the_study_certifier_cannot_decide(self):
        """PRD §2.12: "The operator identifier issuing a transfer disposition must
        differ from the `certified_by_user_id` recorded on the consumptive-use
        study the application relies on, and must differ from the
        `resolved_by_user_id` recorded on every protest filed against that
        application. Either collision is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        The disposition is otherwise impeccable — PRD §3.6's clearance cascade has
        already carried the application to `READY_FOR_DECISION` and finalized the
        analysis at no residual injury — so identity is the only objection.

        Design: Corner/rbac/rbac_segregation_of_duties_certifier_and_resolver_are_both_barred_from_deciding
        """
        bundle = self._ready_for_decision()
        assert bundle["protest"]["status"] == "RESOLVED_STIPULATED"
        assert bundle["application"]["status"] == "READY_FOR_DECISION"
        assert bundle["application"]["unresolved_protest_count"] == 0
        analysis = get_success_data(
            api_client.get_injury_analysis(bundle["analysis"]["id"], ANALYST)
        )
        assert analysis["status"] == "FINALIZED"
        assert analysis["offset_af"] == pytest.approx(78.00, abs=0.01)
        assert analysis["net_injury_af"] == pytest.approx(0.00, abs=0.01)

        response = self._decide_as(bundle["application"]["id"], self.CERTIFIER)

        validate_error(
            response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403
        )
        application = read_application(bundle["application"]["id"])
        assert application["status"] == "READY_FOR_DECISION"
        assert application["escrowed_af"] == pytest.approx(100.00, abs=0.01)
        assert application["decided_by_user_id"] is None
        assert application["version"] == bundle["application"]["version"]

    def test_the_protest_resolver_cannot_decide_either(self):
        """PRD §2.12: "Because these identifiers are opaque, the same human acting
        first as an analyst and later as a decision authority is caught by the
        identifier comparison even though the role changed."

        The rule reaches every protest resolver on the application and not merely
        the study's certifier, so the two disqualifications are independent.

        Design: Corner/rbac/rbac_segregation_of_duties_certifier_and_resolver_are_both_barred_from_deciding
        """
        bundle = self._ready_for_decision()

        response = self._decide_as(bundle["application"]["id"], self.RESOLVER)

        validate_error(
            response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403
        )
        right = read_right(bundle["right"]["id"])
        assert right["encumbered_af"] == pytest.approx(100.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(0.00, abs=0.01)
        assert read_application(bundle["application"]["id"])["decided_by_user_id"] is None

    def test_an_uninvolved_authority_signs_the_same_disposition(self):
        """PRD §3.7: "On success the application moves `READY_FOR_DECISION →
        APPROVED`, `escrowed_af` is set to 0.00, and on the right the escrowed
        volume moves out of `encumbered_af` and into `transferred_away_af` so that
        the conserved identity holds across the move."

        Nothing about the request changes but the operator identifier, which is the
        whole of the segregation rule.

        Design: Corner/rbac/rbac_segregation_of_duties_certifier_and_resolver_are_both_barred_from_deciding
        """
        bundle = self._ready_for_decision()

        approved = get_success_data(
            self._decide_as(bundle["application"]["id"], self.UNINVOLVED)
        )

        assert approved["status"] == "APPROVED"
        assert approved["escrowed_af"] == pytest.approx(0.00, abs=0.01)
        assert approved["decided_by_user_id"] == self.UNINVOLVED
        right = read_right(bundle["right"]["id"])
        assert right["transferable_af"] == pytest.approx(95.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(100.00, abs=0.01)
        assert right["status"] == "PARTIALLY_TRANSFERRED"


class TestStandingIsTheAdjudicatorsAloneAndBindsTheSanctioned:
    """PRD §3.1 — the one field a claimant can never touch on itself.

    The sanction is refused to the analyst who administers the file and to the
    claimant who would suffer it, and once the adjudicator writes it the sanction
    immediately bites that claimant's own protest filing.
    """

    def _fixture(self):
        bundle = setup_published_application(requested_af=100.00, clock=CLOCK)
        bundle["outsider"] = create_claimant(
            "Bell Cattle Trust",
            contact_email="b@bell.example",
            entity_type="INDIVIDUAL",
        )
        return bundle

    def test_neither_the_analyst_nor_the_claimant_may_set_standing(self):
        """PRD §3.1: "Standing is otherwise administrative. Only the basin
        adjudicator may set `standing_status` directly, supplying one of
        `IN_GOOD_STANDING`, `DELINQUENT` or `BARRED`."

        The claimant's own attempt asks for the value it already holds and is
        still refused, so the endpoint is closed to the role rather than to the
        change.

        Design: Corner/rbac/rbac_standing_sanction_is_adjudicator_exclusive_and_binds_the_sanctioned_holder
        """
        bundle = self._fixture()
        outsider = bundle["outsider"]

        by_analyst = api_client.set_claimant_standing(outsider["id"], "BARRED", ANALYST)
        by_self = api_client.set_claimant_standing(
            outsider["id"],
            "IN_GOOD_STANDING",
            make_claimant_headers(outsider["id"]),
        )

        validate_error(
            by_analyst, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, expected_status=403
        )
        validate_error(
            by_self, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, expected_status=403
        )
        stored = read_claimant(outsider["id"])
        assert stored["standing_status"] == "IN_GOOD_STANDING"
        assert stored["version"] == outsider["version"]

    def test_the_adjudicators_sanction_then_bars_the_protest(self):
        """PRD §3.1: "`BARRED` is a sanction that blocks protest filing and fee
        payment outright" and "Setting standing bumps the claimant's `version`".

        PRD §3.6 gives the refusal its identity: "The protestant's
        `standing_status` must not be `BARRED`, though a merely `DELINQUENT`
        protestant may still file; a barred protestant is
        `ERR_CLAIMANT_NOT_IN_GOOD_STANDING`."

        Design: Corner/rbac/rbac_standing_sanction_is_adjudicator_exclusive_and_binds_the_sanctioned_holder
        """
        bundle = self._fixture()
        outsider = bundle["outsider"]

        sanctioned = get_success_data(
            api_client.set_claimant_standing(outsider["id"], "BARRED", ADJUDICATOR)
        )
        response = api_client.create_protest(
            create_protest_payload(
                bundle["application"]["id"],
                outsider["id"],
                5.00,
                basis="PUBLIC_INTEREST",
            ),
            make_claimant_headers(outsider["id"]),
        )

        assert sanctioned["standing_status"] == "BARRED"
        assert sanctioned["version"] == outsider["version"] + 1
        validate_error(
            response,
            ApiErrorId.ERR_CLAIMANT_NOT_IN_GOOD_STANDING.value,
            expected_status=403,
        )
        _, meta = validate_paginated(api_client.list_protests(ANALYST))
        assert meta["total_count"] == 0
        application = read_application(bundle["application"]["id"])
        assert application["status"] == "PROTEST_PERIOD"
        assert application["unresolved_protest_count"] == 0

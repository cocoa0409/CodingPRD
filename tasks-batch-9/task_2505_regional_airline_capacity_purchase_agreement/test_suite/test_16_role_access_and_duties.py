"""Who may act, and who may not act twice on the same decision.

The read surface is shared by all five roles; the write surface is partitioned. Two of
the partitions are not role-static at all: the chief pilot's authority is bounded by the
base it commands, and the two adjudications are bounded by the identity that authored
the thing being adjudicated.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import (
    ERR_BASE_NOT_OWNED,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import (
    assert_is_null,
    assert_money,
    assert_page_meta,
    assert_status,
    ids_of,
)
from test_helpers.factories import (
    make_advance_payload,
    make_agreement_payload,
    make_extension_offer_payload,
    make_reconcile_payload,
)
from test_helpers.fixtures import (
    agreement_version,
    build_active_agreement,
    create_agreement,
    create_crew_base,
    create_brand_audit,
    create_cycle,
    file_pass_through_actual,
    hire_pilot,
    open_cycle,
    open_pass_through,
    read_agreement,
    read_brand_audit,
    read_crew_base,
    read_cycle,
    read_negotiation,
    read_pilot,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    OPS_HEADERS,
    SCHEDULER_HEADERS,
    SECOND_ADMIN_HEADERS,
    make_base_chief_pilot_headers,
)


class TestSharedReadSurface:
    """Reading is the one thing no role is excluded from."""

    def test_the_same_two_collections_read_identically_for_four_different_roles(self, api):
        """Each read returns the default window over the one record that exists.

        PRD 2.1: "All five roles may read every collection."

        PRD 2.3: "`limit` caps the number of records returned; when it is omitted it defaults
        to 10, its minimum accepted value is 1 and its maximum accepted value is 100."

        PRD 2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside
        the `meta` object of the envelope, where `total_count` is the size of the filtered set
        before pagination is applied and `has_more` states whether records remain beyond the
        returned window."

        Design: Corner/rbac/every_role_can_read_the_shared_get_surface
        """
        agreement = create_agreement(api, make_agreement_payload())
        base = create_crew_base(
            api,
            agreement["id"],
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )

        for headers in (SCHEDULER_HEADERS, OPS_HEADERS):
            agreements, meta = validate_paginated(api.list_agreements(headers=headers))
            assert ids_of(agreements) == [agreement["id"]]
            assert_page_meta(meta, limit=10, offset=0, total_count=1, has_more=False)

        for headers in (make_base_chief_pilot_headers(base["id"]), AUDITOR_HEADERS):
            bases, meta = validate_paginated(api.list_crew_bases(headers=headers))
            assert ids_of(bases) == [base["id"]]
            assert_page_meta(meta, limit=10, offset=0, total_count=1, has_more=False)


class TestAgreementFormationIsAdministrativeOnly:
    """The mainline desk transacts under an agreement but cannot author one."""

    def test_the_scheduler_is_refused_the_creation_and_no_agreement_is_written(self, api):
        """The refused creation leaves the collection empty for the role that may read it.

        PRD 2.1: "When the headers are well-formed but the acting role is not among the roles
        authorised for the requested operation, the rejection is `ERR_FORBIDDEN_ROLE` (HTTP
        403)."

        PRD 3.1: "A `CPAAdministrator` registers one by naming the two parties —
        `mainline_partner_name` for the partner whose brand the flights carry and
        `regional_carrier_name` for the operator selling the capacity — and by declaring the
        five money terms and the term expiry."

        Design: Corner/rbac/mainline_scheduler_cannot_create_agreements
        """
        validate_error(
            api.create_agreement(make_agreement_payload(), headers=SCHEDULER_HEADERS),
            ERR_FORBIDDEN_ROLE,
            403,
        )

        agreements, meta = validate_paginated(api.list_agreements(headers=ADMIN_HEADERS))
        assert agreements == []
        assert meta["total_count"] == 0


class TestAdjudicationIsClosedToTheFilingSide:
    """The role check refuses the regional carrier before identities are compared at all."""

    def test_the_ops_controller_cannot_reconcile_the_claim_it_filed(self, api):
        """The refusal is the role, not the identity, and the claim keeps its accrual.

        PRD 2.1: "When the headers are well-formed but the acting role is not among the roles
        authorised for the requested operation, the rejection is `ERR_FORBIDDEN_ROLE` (HTTP
        403)."

        PRD 3.6: "Adjudication is a `CPAAdministrator` act, admissible only from
        `ACTUAL_SUBMITTED`, carrying a `decision` of either `APPROVE` or `REJECT`, and refused
        with `ERR_SEGREGATION_OF_DUTIES` when the acting `X-User-ID` is the same identifier
        already recorded in `actual_submitted_by_user_id`."

        Design: Corner/rbac/regional_ops_controller_cannot_reconcile_passthrough
        """
        scenario = build_active_agreement(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )
        cycle = create_cycle(
            api, scenario.agreement_id, cycle_month="2026-09", published_departures=0
        )
        cycle = open_cycle(api, cycle["id"])
        claim = open_pass_through(
            api, cycle["id"], category="AIRPORT_FEES", estimated_amount_usd=8000.00
        )
        file_pass_through_actual(
            api, claim["id"], actual_amount_usd=8100.00, supporting_doc_ref="DOC-C1"
        )

        error = validate_error(
            api.reconcile_pass_through(
                claim["id"], make_reconcile_payload("APPROVE"), headers=OPS_HEADERS
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        assert error["error_id"] != ERR_SEGREGATION_OF_DUTIES, (
            "the identity comparison presupposes a role that may adjudicate at all"
        )

        standing = validate_success(api.get_pass_through_claim(claim["id"], headers=ADMIN_HEADERS))
        assert_status(standing, "ACTUAL_SUBMITTED")
        assert_is_null(standing, "allowed_amount_usd", "reconciled_by_user_id")

        assert_money(
            read_cycle(api, cycle["id"])["passthrough_settlement_usd"],
            0.00,
            "the month's pass-through settlement",
        )


class TestAuditorCannotManufactureAClosableFinding:
    """The auditor owns both ends of the finding dimension but not its middle."""

    def test_the_auditor_may_neither_acknowledge_its_finding_nor_close_it_unacknowledged(
        self, api
    ):
        """Two refusals with two different codes leave both dimensions where they opened.

        PRD 3.7: "A `RegionalOpsController` acknowledges the finding, moving `finding_status`
        from `OPEN` to `ACKNOWLEDGED` and leaving `remediation_status` untouched."

        PRD 3.7: "Closing the finding belongs to the `BrandAuditor`: `finding_status` moves
        `ACKNOWLEDGED → CLOSED`, but only if `remediation_status` has already reached
        `VERIFIED`."

        PRD 2.12: "9. Whether the target's current state declares the requested transition at
        all — `ERR_INVALID_STATE`."

        Design: Corner/rbac/brand_auditor_cannot_acknowledge_its_own_finding
        """
        scenario = build_active_agreement(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )
        audit = create_brand_audit(
            api,
            scenario.crew_base_id,
            audit_scope="SERVICE_SCRIPT",
            findings_count=1,
            severity="MAJOR",
        )

        validate_error(
            api.acknowledge_brand_audit(audit["id"], headers=AUDITOR_HEADERS),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            api.close_brand_audit(audit["id"], headers=AUDITOR_HEADERS),
            ERR_INVALID_STATE,
            409,
        )

        untouched = read_brand_audit(api, audit["id"])
        assert_status(untouched, "OPEN", field="finding_status")
        assert_status(untouched, "NOT_STARTED", field="remediation_status")


class TestChiefPilotAuthorityIsBoundedByItsBase:
    """The identical advance turns on which base the acting chief pilot commands."""

    def test_the_other_base_s_chief_pilot_cannot_advance_the_pilot(self, api):
        """The pilot moves only for the chief pilot of its own base, and only that base counts.

        PRD 2.1: "A chief pilot acting on a pilot who belongs to a different base is rejected
        with `ERR_BASE_NOT_OWNED` (HTTP 403); this check guards both the pilot-advancement and
        the pilot-attrition actions."

        PRD 3.2: "The first step, `PIPELINE → IN_TRAINING`, requires that the pilot is in
        `PIPELINE`, that the acting chief pilot owns the base per §2.1, and that the base's
        `lifecycle_status` is still `ACTIVE`; a base already closed refuses the advance with
        `ERR_INVALID_STATE`."

        Design: Corner/rbac/base_chief_pilot_cannot_advance_a_pilot_at_another_base
        """
        scenario = build_active_agreement(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )
        other_base = create_crew_base(
            api,
            scenario.agreement_id,
            station_code="IND",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )
        pilot = hire_pilot(
            api, scenario.crew_base_id, "EMP-5601", hire_class_date="2026-05-01"
        )

        validate_error(
            api.advance_pilot(
                pilot["id"],
                make_advance_payload("IN_TRAINING"),
                headers=make_base_chief_pilot_headers(other_base["id"]),
            ),
            ERR_BASE_NOT_OWNED,
            403,
        )
        assert_status(read_pilot(api, pilot["id"]), "PIPELINE")

        advanced = validate_success(
            api.advance_pilot(
                pilot["id"],
                make_advance_payload("IN_TRAINING"),
                headers=make_base_chief_pilot_headers(scenario.crew_base_id),
            )
        )
        assert_status(advanced, "IN_TRAINING")

        assert read_crew_base(api, scenario.crew_base_id)["in_training_pilot_count"] == 1
        assert read_crew_base(api, other_base["id"])["in_training_pilot_count"] == 0


class TestFilerMayNotAdjudicateItsOwnFiling:
    """Same endpoint, same role, two identities: one refused and one allowed."""

    def test_the_second_administrator_approves_what_the_first_one_filed(self, api):
        """The refusal turns on the recorded filer, and approval runs the waterfall.

        PRD 2.11: "The identifier recorded in `actual_submitted_by_user_id` when the invoiced
        actual was filed may not be the `X-User-ID` that later adjudicates the claim, even
        though both act as `CPAAdministrator`; an attempt is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        PRD 3.6: "Every other category is capped at a tolerance above the accrual: for
        `AIRPORT_FEES` the ceiling is the estimate increased by one tenth, and for `INSURANCE`
        it is the estimate increased by one twentieth, each ceiling rounded half-up to two
        decimals, and `allowed_amount_usd` is whichever is smaller, the actual or that
        ceiling."

        PRD 3.6: "Step three selects the administrative fee rate from a tier keyed on that
        base total: three percent when the base total is no more than 100,000.00; two percent
        when it is more than 100,000.00 but no more than 500,000.00; and one and a half
        percent when it exceeds 500,000.00."

        Design: Corner/rbac/same_user_cannot_reconcile_the_actual_it_filed
        """
        scenario = build_active_agreement(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )
        cycle = create_cycle(
            api, scenario.agreement_id, cycle_month="2026-09", published_departures=0
        )
        cycle = open_cycle(api, cycle["id"])
        claim = open_pass_through(
            api, cycle["id"], category="INSURANCE", estimated_amount_usd=20000.00
        )
        filed = file_pass_through_actual(
            api,
            claim["id"],
            actual_amount_usd=20500.00,
            supporting_doc_ref="DOC-INS-1",
            headers=ADMIN_HEADERS,
        )
        assert filed["actual_submitted_by_user_id"] == "admin-1"

        validate_error(
            api.reconcile_pass_through(
                claim["id"], make_reconcile_payload("APPROVE"), headers=ADMIN_HEADERS
            ),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        assert_status(
            validate_success(api.get_pass_through_claim(claim["id"], headers=ADMIN_HEADERS)),
            "ACTUAL_SUBMITTED",
        )

        reconciled = validate_success(
            api.reconcile_pass_through(
                claim["id"], make_reconcile_payload("APPROVE"), headers=SECOND_ADMIN_HEADERS
            )
        )
        assert_status(reconciled, "RECONCILED")
        assert reconciled["reconciled_by_user_id"] == "admin-2"
        assert reconciled["actual_submitted_by_user_id"] == "admin-1"
        assert_money(
            reconciled["allowed_amount_usd"], 20500.00, "the actual under the 5% ceiling"
        )
        assert_money(reconciled["variance_usd"], 500.00, "the actual less the estimate")

        assert_money(
            read_cycle(api, cycle["id"])["passthrough_settlement_usd"],
            21115.00,
            "the base total plus a three percent administrative fee",
        )


class TestOfferingSideMayNotAcceptItsOwnRound:
    """The endpoint admits both negotiating roles; the standing round picks one of them."""

    def test_only_the_regional_carrier_may_accept_a_round_the_mainline_offered(self, api):
        """The refused acceptance rewrites nothing; the allowed one rewrites the contract.

        PRD 2.11: "A round standing in `OFFERED` was authored by the mainline partner, so only
        `RegionalOpsController` may accept it; a round standing in `COUNTERED` was authored by
        the regional carrier, so only `MainlineScheduler` may accept it."

        PRD 3.9: "Accepting an `OFFERED` round writes the agreement's `term_end_date` from
        `proposed_term_end_date` and its `block_hour_rate_usd` from
        `proposed_block_hour_rate_usd`; accepting a `COUNTERED` round writes them from
        `counter_term_end_date` and `counter_block_hour_rate_usd` instead."

        PRD 3.9: "Either way the round moves to the terminal `ACCEPTED` status, the agreement
        returns `EXTENSION_PENDING → ACTIVE`, and both `version` counters increment."

        Design: Corner/rbac/offering_party_cannot_accept_its_own_standing_offer
        """
        scenario = build_active_agreement(
            api,
            agreement_payload=make_agreement_payload(term_end_date="2029-12-31"),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )
        offer = validate_success(
            api.create_extension_negotiation(
                scenario.agreement_id,
                make_extension_offer_payload(
                    agreement_version(api, scenario.agreement_id),
                    proposed_term_end_date="2031-12-31",
                    proposed_block_hour_rate_usd=1500.00,
                ),
                headers=SCHEDULER_HEADERS,
            ),
            201,
        )
        assert_status(offer, "OFFERED")

        validate_error(
            api.accept_negotiation(offer["id"], headers=SCHEDULER_HEADERS),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        assert_status(read_negotiation(api, offer["id"]), "OFFERED")
        assert read_agreement(api, scenario.agreement_id)["term_end_date"] == "2029-12-31"

        accepted = validate_success(
            api.accept_negotiation(offer["id"], headers=OPS_HEADERS)
        )
        assert_status(accepted, "ACCEPTED")

        agreement = read_agreement(api, scenario.agreement_id)
        assert_status(agreement, "ACTIVE")
        assert agreement["term_end_date"] == "2031-12-31"
        assert_money(agreement["block_hour_rate_usd"], 1500.00, "the accepted block-hour rate")
        assert agreement["extension_round_count"] == 1

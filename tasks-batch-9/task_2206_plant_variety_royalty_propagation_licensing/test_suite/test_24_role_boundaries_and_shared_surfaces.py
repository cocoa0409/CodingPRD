"""Which capacity may do what: the exclusive writes and the two shared surfaces."""

from test_helpers import (
    AUDITOR,
    BREEDER,
    COORDINATOR,
    OFFICER,
    ApiErrorId,
    active_agreement,
    add_line_item,
    advance_clock,
    assert_decimal_equals,
    assert_instant_equals,
    create_production_quota_payload,
    create_propagator,
    create_propagator_agreement_payload,
    create_sublicense_grant_payload,
    create_tag_order_payload,
    create_trial_site,
    create_variety,
    create_variety_payload,
    create_variety_trial_payload,
    draft_report,
    evaluate_trial_payload,
    licensed_quota,
    make_licensing_officer_headers,
    make_propagator_headers,
    planted_trial,
    read_version,
    set_clock_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTheBreedingOfficeHoldsNoBillingAuthority:
    """A submitted report that any officer could accept, offered to the wrong desk."""

    def _submitted_report(self, api):
        chain = licensed_quota(
            api, quality_tier="TIER_B", territory_class="DOMESTIC",
            allocated_units=5000, season_code="2026S1", basis="PER_PLANT",
            variety_overrides={
                "denomination": "Brackenmoor Bramble",
                "species": "Rubus idaeus",
                "breeder_code": "BM",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"], propagator_name="Brackenmoor Nursery",
            home_territory_code="US-WA",
        )
        report = draft_report(
            api, chain, period_code="2026Q3",
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-11-01T00:00:00Z",
            due_at="2026-11-15T00:00:00Z",
        )
        add_line_item(api, chain, report["id"], 100)
        chain["report_id"] = report["id"]
        validate_success(
            api.submit_royalty_report(report["id"], chain["propagator_headers"])
        )
        return chain

    def test_the_breeding_office_may_not_accept_a_report(self, api):
        """Acceptance is the licensing desk's own act, so the rights office is
        refused on its role and the report waits where it was.

        PRD 2.1: "It holds no billing authority at all and can never accept or settle a royalty report."

        Design: Corner/rbac/breeder_admin_cannot_accept_or_settle_a_royalty_report
        """
        chain = self._submitted_report(api)

        validate_error(
            api.accept_royalty_report(chain["report_id"], BREEDER),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )
        assert validate_success(api.get_royalty_report(chain["report_id"], OFFICER))[
            "review_status"
        ] == "SUBMITTED"

    def test_the_whole_licensing_surface_is_closed_to_it(self, api):
        """Onboarding, allocation and sublicensing all belong to the licensing desk,
        so the rights office is refused on each of them in turn.

        PRD 2.1: "The `LicensingOfficer` is the licensing and billing desk: propagator onboarding, agreements and their suspension lifecycle, quota allocation, tag issuance and voiding, royalty acceptance, dispute, settlement and reversal, and sublicensing."

        Design: Corner/rbac/breeder_admin_cannot_accept_or_settle_a_royalty_report
        """
        chain = self._submitted_report(api)
        agreement_version = read_version(api, api.get_propagator_agreement,
                                         chain["agreement_id"], OFFICER)

        validate_error(
            api.create_propagator_agreement(
                create_propagator_agreement_payload(chain["propagator_id"]), BREEDER
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )
        validate_error(
            api.create_production_quota(
                create_production_quota_payload(chain["agreement_id"],
                                                chain["variety_id"],
                                                season_code="2026S2"),
                BREEDER,
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )
        validate_error(
            api.create_sublicense_grant(
                create_sublicense_grant_payload(chain["agreement_id"],
                                                chain["variety_id"],
                                                agreement_version),
                BREEDER,
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )

    def test_the_read_surface_is_open_to_it_all_the_same(self, api):
        """Only the writes are partitioned, so the rights office reads the very
        report it may not act on.

        PRD 2.1: "The five roles are `BreederAdmin`, `LicensingOfficer`, `Propagator`, `TrialCoordinator` and `ComplianceAuditor`."

        Design: Corner/rbac/breeder_admin_cannot_accept_or_settle_a_royalty_report
        """
        chain = self._submitted_report(api)

        seen = validate_success(api.get_royalty_report(chain["report_id"], BREEDER))
        assert seen["id"] == chain["report_id"]


class TestTheNurseryRequestsTagsButNeverAuthorizesThem:
    """A 400-unit order the propagator legitimately created itself."""

    def _requested_tag_order(self, api):
        chain = licensed_quota(
            api, quality_tier="TIER_B", territory_class="DOMESTIC",
            allocated_units=5000, season_code="2026S1", basis="PER_PLANT",
            variety_overrides={
                "denomination": "Coppice Bramble",
                "species": "Rubus idaeus",
                "breeder_code": "CP",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"], propagator_name="Coppice Nursery",
            home_territory_code="US-WA",
        )
        quota_version = read_version(api, api.get_production_quota,
                                     chain["quota_id"], OFFICER)
        chain["order"] = validate_success(
            api.create_tag_order(
                create_tag_order_payload(chain["quota_id"], quota_version,
                                         requested_units=400),
                chain["propagator_headers"],
            ),
            201,
        )
        chain["order_id"] = chain["order"]["id"]
        return chain

    def test_issuing_its_own_order_is_refused_on_the_role_not_on_ownership(self, api):
        """The role gate is judged before ownership, so the propagator that owns the
        order is told about its capacity, and no units are committed.

        PRD 2.1: "It can neither issue nor void tags, and it can never accept, dispute, settle or reverse a report."

        Design: Corner/rbac/propagator_cannot_issue_or_void_its_own_tag_orders
        """
        chain = self._requested_tag_order(api)

        validate_error(
            api.issue_tag_order(chain["order_id"], chain["propagator_headers"]),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )

        assert validate_success(api.get_tag_order(chain["order_id"], OFFICER))[
            "status"
        ] == "REQUESTED"
        assert validate_success(api.get_production_quota(chain["quota_id"], OFFICER))[
            "tags_committed_units"
        ] == 0

    def test_voiding_is_closed_to_it_too_while_the_officer_issues_freely(self, api):
        """Both authorizing acts sit on the licensing desk, and the identical issue
        call from that desk succeeds.

        PRD 3.6: "A `LicensingOfficer` voids an order that is either `REQUESTED` or `ISSUED`, moving it to `VOIDED` and setting `voided_units` to the order's `requested_units` — the compensating quantity captured at the moment of voiding."

        Design: Corner/rbac/propagator_cannot_issue_or_void_its_own_tag_orders
        """
        chain = self._requested_tag_order(api)

        validate_error(
            api.void_tag_order(chain["order_id"], chain["propagator_headers"]),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )

        issued = validate_success(api.issue_tag_order(chain["order_id"], OFFICER))
        assert issued["status"] == "ISSUED"


class TestTheAuditFunctionFindsRatherThanTransacts:
    """An active licence with no allocation on it yet."""

    def _agreement_without_a_quota(self, api):
        variety = create_variety(
            api, denomination="Dunmere Bramble", species="Rubus idaeus",
            breeder_code="DM", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        chain = active_agreement(
            api, quality_tier="TIER_B", territory_codes=["US-WA"],
            propagator_name="Dunmere Nursery", home_territory_code="US-WA",
        )
        chain["variety_id"] = variety["id"]
        return chain

    def test_the_auditor_may_not_allocate_production(self, api):
        """Quota allocation belongs to the licensing desk, so the audit function is
        refused and nothing is allocated.

        PRD 2.1: "The `ComplianceAuditor` is the enforcement and audit function: market-survey surveillance cases, genetic testing, case resolution with damages allocation, and royalty audit engagements."

        Design: Corner/rbac/compliance_auditor_cannot_settle_or_open_a_production_quota
        """
        chain = self._agreement_without_a_quota(api)

        validate_error(
            api.create_production_quota(
                create_production_quota_payload(chain["agreement_id"],
                                                chain["variety_id"]),
                AUDITOR,
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )

        _rows, meta = validate_paginated(api.list_production_quotas(AUDITOR))
        assert meta["total_count"] == 0

    def test_it_may_neither_suspend_a_licence_nor_register_a_variety(self, api):
        """The suspension lifecycle and the variety record belong to two other roles,
        yet the audit function reads both surfaces without hindrance.

        PRD 2.1: "It can issue findings that dispute an accepted report and suspend an agreement, but it can never accept, settle or reverse a report, nor issue tags."

        Design: Corner/rbac/compliance_auditor_cannot_settle_or_open_a_production_quota
        """
        chain = self._agreement_without_a_quota(api)

        validate_error(
            api.suspend_agreement(chain["agreement_id"], AUDITOR),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )
        validate_error(
            api.create_variety(create_variety_payload(denomination="Dunmere Second",
                                                      breeder_code="DM2"), AUDITOR),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )

        assert validate_success(
            api.get_propagator_agreement(chain["agreement_id"], AUDITOR)
        )["status"] == "ACTIVE"


class TestScoringAndRatifyingATrialAreSeparateOffices:
    """One evaluated trial indexing at 82.00, awaiting ratification."""

    def _evaluated_trial(self, api):
        variety = create_variety(
            api, denomination="Elmsford Bramble", species="Rubus idaeus",
            breeder_code="EF", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        site = create_trial_site(api, site_name="Elmsford North", region_code="PNW",
                                 plot_capacity=60)
        trial = planted_trial(api, variety["id"], site["id"], plot_count=10)
        advance_clock(api, "2026-09-20T00:00:00Z", COORDINATOR)
        evaluated = validate_success(
            api.evaluate_variety_trial(
                trial["id"],
                evaluate_trial_payload(yield_index=85.00, vigor_score=80.00,
                                       uniformity_score=80.00,
                                       disease_resistance_score=80.00,
                                       propagation_pass_rate=1.0000),
                COORDINATOR,
            )
        )
        return {"variety_id": variety["id"], "site": site, "trial_id": trial["id"],
                "evaluated": evaluated}

    def test_the_coordinator_that_scored_the_trial_may_not_certify_it(self, api):
        """Certification is the decision that a trial counts toward release, and it
        is reserved to the rights office, so the scores stand unratified.

        PRD 2.1: "Certification, the decision that a trial counts toward release, is reserved to `BreederAdmin`, so scoring and certifying are deliberately separated."

        Design: Corner/rbac/trial_coordinator_cannot_certify_the_trial_it_evaluated
        """
        setup = self._evaluated_trial(api)

        validate_error(
            api.certify_variety_trial(setup["trial_id"], COORDINATOR),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )

        trial = validate_success(api.get_variety_trial(setup["trial_id"], COORDINATOR))
        assert trial["status"] == "EVALUATED"
        assert_decimal_equals(trial["performance_index"], "82.00", "performance_index")
        assert validate_success(api.get_variety(setup["variety_id"], BREEDER))[
            "passed_trial_region_count"
        ] == 0

    def test_the_rights_office_ratifies_it_but_cannot_run_the_network(self, api):
        """The same certification from the rights office passes the trial and counts
        its region, while the trialing network's own writes are closed to that
        office in return.

        PRD 2.1: "The `TrialCoordinator` runs the regional trialing network — trial sites, the trial calendar, planting and evaluation scoring."

        Design: Corner/rbac/trial_coordinator_cannot_certify_the_trial_it_evaluated
        """
        setup = self._evaluated_trial(api)

        certified = validate_success(
            api.certify_variety_trial(setup["trial_id"], BREEDER)
        )
        assert certified["status"] == "PASSED"
        assert validate_success(api.get_variety(setup["variety_id"], BREEDER))[
            "passed_trial_region_count"
        ] == 1

        validate_error(
            api.create_variety_trial(
                create_variety_trial_payload(setup["variety_id"], setup["site"]["id"],
                                             plot_count=10),
                BREEDER,
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )

    def test_releasing_a_variety_is_closed_to_the_coordinator(self, api):
        """Commercial release belongs to the rights office as well, so the network's
        coordinator cannot promote the variety it trialled.

        PRD 2.1: "It owns the variety record itself, the whole protection portfolio, the trademark dimension, trial certification, and commercial release and retirement."

        Design: Corner/rbac/trial_coordinator_cannot_certify_the_trial_it_evaluated
        """
        setup = self._evaluated_trial(api)

        validate_error(
            api.release_variety(setup["variety_id"], COORDINATOR),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )


class TestTheTwoSurfacesEveryRoleShares:
    """Reads, and the logical clock."""

    def _licensed_chain(self, api):
        return licensed_quota(
            api, quality_tier="TIER_B", territory_class="DOMESTIC",
            allocated_units=5000, season_code="2026S1", basis="PER_PLANT",
            variety_overrides={
                "denomination": "Fernhaven Bramble",
                "species": "Rubus idaeus",
                "breeder_code": "FH",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"], propagator_name="Fernhaven Nursery",
            home_territory_code="US-WA",
        )

    def test_any_role_may_move_the_clock(self, api):
        """The clock capability is not partitioned by role, so the trialing
        coordinator advances it and is told where it landed.

        PRD 2.5: "The clock is advanced only by an administrative test-driving capability that accepts a `current_utc` instant."

        Design: Corner/rbac/every_role_shares_the_read_surface_and_the_clock_endpoint
        """
        body = validate_success(
            api.set_current_utc(set_clock_payload("2026-08-10T00:00:00Z"), COORDINATOR)
        )
        assert_instant_equals(body["current_utc"], "2026-08-10T00:00:00Z",
                              "current_utc")

    def test_one_quota_row_is_legible_to_all_five_capacities(self, api):
        """Reads are shared, which is what makes every refusal above attributable to
        the specific write rather than to blanket invisibility.

        PRD 2.1: "This check runs before the request body is parsed, so an unauthorized caller never learns whether its payload was well formed."

        Design: Corner/rbac/every_role_shares_the_read_surface_and_the_clock_endpoint
        """
        chain = self._licensed_chain(api)

        for headers in (BREEDER, OFFICER, chain["propagator_headers"], COORDINATOR,
                        AUDITOR):
            assert validate_success(
                api.get_production_quota(chain["quota_id"], headers)
            )["id"] == chain["quota_id"]
            assert validate_success(
                api.get_propagator_agreement(chain["agreement_id"], headers)
            )["id"] == chain["agreement_id"]

    def test_the_clock_advances_once_under_each_capacity_in_turn(self, api):
        """Every role may move it, and each move must still be strictly later than
        the last, so five successive instants are accepted in five capacities.

        PRD 2.5: "That instant must be strictly later than the clock's present value; an equal or earlier instant is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422), which guarantees that a sweep already performed is never replayed."

        Design: Corner/rbac/every_role_shares_the_read_surface_and_the_clock_endpoint
        """
        chain = self._licensed_chain(api)

        instants = ("2026-08-11T00:00:00Z", "2026-08-12T00:00:00Z",
                    "2026-08-13T00:00:00Z", "2026-08-14T00:00:00Z",
                    "2026-08-15T00:00:00Z")
        capacities = (BREEDER, OFFICER, chain["propagator_headers"], COORDINATOR,
                      AUDITOR)
        for instant, headers in zip(instants, capacities):
            body = validate_success(
                api.set_current_utc(set_clock_payload(instant), headers)
            )
            assert_instant_equals(body["current_utc"], instant, "current_utc")


class TestDutySeparationIsScopedToOneAgreementChain:
    """Two licences countersigned by two different officers."""

    def _two_chains_countersigned_apart(self, api):
        variety = create_variety(
            api, denomination="Glenholm Bramble", species="Rubus idaeus",
            breeder_code="GH", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        officer_nine = make_licensing_officer_headers("officer-9")
        first = active_agreement(
            api, quality_tier="TIER_B", territory_codes=["US-WA"],
            propagator_name="Glenholm One", home_territory_code="US-WA",
        )
        second_propagator = create_propagator(api, legal_name="Glenholm Two",
                                              home_territory_code="US-OR")
        second_agreement = validate_success(
            api.create_propagator_agreement(
                create_propagator_agreement_payload(
                    second_propagator["id"], quality_tier="TIER_B",
                    territory_codes=["US-OR"],
                ),
                officer_nine,
            ),
            201,
        )
        validate_success(api.countersign_agreement(second_agreement["id"],
                                                   officer_nine))
        second = {
            "propagator_id": second_propagator["id"],
            "propagator_headers": make_propagator_headers(second_propagator["id"]),
            "agreement_id": second_agreement["id"],
        }
        second["quota"] = validate_success(
            api.create_production_quota(
                create_production_quota_payload(
                    second["agreement_id"], variety["id"], season_code="2026S1",
                    basis="PER_PLANT", territory_code="US-OR",
                    territory_class="DOMESTIC", allocated_units=5000,
                ),
                officer_nine,
            ),
            201,
        )
        second["quota_id"] = second["quota"]["id"]
        report = draft_report(
            api, second, period_code="2026Q3",
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-11-01T00:00:00Z",
            due_at="2026-11-15T00:00:00Z",
        )
        add_line_item(api, second, report["id"], 100)
        second["report_id"] = report["id"]
        validate_success(
            api.submit_royalty_report(report["id"], second["propagator_headers"])
        )
        return {"first": first, "second": second, "officer_nine": officer_nine}

    def test_an_officer_may_accept_a_report_under_a_licence_it_did_not_countersign(self, api):
        """The barrier compares the acting identifier against that report's own
        agreement, so the officer barred on one chain acts freely on the other.

        PRD 2.10: "Two barriers enforce this, and both compare the acting `X-User-ID` against a user id the system recorded earlier:"

        Design: Corner/rbac/countersigner_of_one_agreement_may_accept_another_agreements_report
        """
        setup = self._two_chains_countersigned_apart(api)

        accepted = validate_success(
            api.accept_royalty_report(setup["second"]["report_id"], OFFICER)
        )
        assert accepted["review_status"] == "ACCEPTED"
        assert accepted["accepted_by_user_id"] == "officer-1"
        assert accepted["booked_amount_cents"] == 3500

    def test_the_two_licences_record_their_own_countersigners(self, api):
        """Each agreement carries the identifier of the officer who activated it,
        which is the datum the barrier reads.

        PRD 3.5: "The transition records the acting `X-User-ID` in `countersigned_by_user_id`, stamps `countersigned_at` with the present instant, and increments the agreement's `version`."

        Design: Corner/rbac/countersigner_of_one_agreement_may_accept_another_agreements_report
        """
        setup = self._two_chains_countersigned_apart(api)

        assert validate_success(
            api.get_propagator_agreement(setup["first"]["agreement_id"], OFFICER)
        )["countersigned_by_user_id"] == "officer-1"
        assert validate_success(
            api.get_propagator_agreement(setup["second"]["agreement_id"], OFFICER)
        )["countersigned_by_user_id"] == "officer-9"

    def test_accepting_is_what_bars_an_officer_from_settling(self, api):
        """Having accepted, the same officer is barred from paying it out, while the
        countersigner of that licence is free to settle.

        PRD 2.10: "Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/countersigner_of_one_agreement_may_accept_another_agreements_report
        """
        setup = self._two_chains_countersigned_apart(api)
        validate_success(
            api.accept_royalty_report(setup["second"]["report_id"], OFFICER)
        )

        validate_error(
            api.settle_royalty_report(setup["second"]["report_id"], OFFICER),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            403,
        )

        settled = validate_success(
            api.settle_royalty_report(setup["second"]["report_id"],
                                      setup["officer_nine"])
        )
        assert settled["settlement_status"] == "SETTLED"
        assert settled["settled_by_user_id"] == "officer-9"

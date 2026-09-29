"""Field, cross-entity and aggregate validation, with the refusals proved inert.

Scoped uniqueness and its positive counterpart, the conditional category lock, interval
geometry, the conserved departure ledger, captain qualification, evidence on the
verification step, and the precedence of the role check over path resolution.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import (
    ERR_DEPARTURE_LEDGER_OVERFLOW,
    ERR_DUPLICATE_PASSTHROUGH_CATEGORY,
    ERR_DUPLICATE_RESOURCE,
    ERR_EVIDENCE_REQUIRED,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_INTERVAL,
    ERR_INVOICE_NOT_FOUND,
    ERR_PILOT_NOT_QUALIFIED,
)
from test_helpers.assertions import assert_is_null, assert_money, assert_status
from test_helpers.factories import (
    make_agreement_payload,
    make_aircraft_payload,
    make_cancel_payload,
    make_crew_base_payload,
    make_flight_leg_payload,
    make_pass_through_payload,
    make_reconcile_payload,
    make_remediation_payload,
    make_second_agreement_payload,
    make_submit_actual_payload,
)
from test_helpers.fixtures import (
    add_leg,
    advance_pilot_to,
    build_active_agreement,
    build_open_cycle,
    cancel_leg,
    create_agreement,
    create_brand_audit,
    create_crew_base,
    create_cycle,
    hire_pilot,
    open_cycle,
    open_pass_through,
    read_brand_audit,
    read_cycle,
    read_leg,
    register_aircraft,
)
from test_helpers.test_users import ADMIN_HEADERS, OPS_HEADERS, SCHEDULER_HEADERS

UNKNOWN_INVOICE_ID = "00000000-0000-4000-8000-0000000004ff"


class TestScopedTailUniqueness:
    """The natural key is the pair of agreement and registration, not the registration."""

    def test_a_second_registration_of_the_same_tail_is_refused_and_changes_nothing(self, api):
        """The refused registration leaves the incumbent tail's seat count alone.

        PRD 3.3: "`tail_number` must be unique among the tails of the same `agreement_id`,
        and `seat_count` must be at least 1."

        PRD 2.12: "12. Referential business rules, in this internal order: cross-agreement
        consistency (`ERR_CROSS_AGREEMENT_REFERENCE`), then duplicate pass-through category
        (`ERR_DUPLICATE_PASSTHROUGH_CATEGORY`), then scoped natural-key uniqueness
        (`ERR_DUPLICATE_RESOURCE`)."

        Design: Corner/validations/duplicate_tail_number_in_same_agreement_rejected
        """
        agreement = create_agreement(api, make_agreement_payload())
        base = create_crew_base(
            api,
            agreement["id"],
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=2,
        )
        register_aircraft(api, agreement["id"], base["id"], tail_number="N4001RG")

        validate_error(
            api.create_aircraft(
                make_aircraft_payload(
                    agreement["id"],
                    base["id"],
                    tail_number="N4001RG",
                    seat_count=50,
                    ownership="MAINLINE_OWNED",
                ),
                headers=OPS_HEADERS,
            ),
            ERR_DUPLICATE_RESOURCE,
            409,
        )

        fleet, meta = validate_paginated(
            api.list_aircraft(headers=OPS_HEADERS, params={"agreement_id": agreement["id"]})
        )
        assert meta["total_count"] == 1
        assert fleet[0]["seat_count"] == 76
        assert fleet[0]["ownership"] == "REGIONAL_OWNED"


class TestUniquenessScopeIsPerAgreement:
    """The same station may host a base under each of two agreements."""

    def test_a_second_agreement_may_open_its_own_base_at_the_same_station(self, api):
        """The two bases are separate rows carrying their own contractual ratios.

        PRD 3.2: "The ratio and the cap must each be at least 1, and `station_code` must be
        unique among the bases of the same `agreement_id`; a repeat is
        `ERR_DUPLICATE_RESOURCE` (HTTP 409)."

        Design: Corner/validations/same_station_code_allowed_under_a_second_agreement
        """
        first = create_agreement(api, make_agreement_payload())
        second = create_agreement(api, make_second_agreement_payload())
        first_base = create_crew_base(
            api,
            first["id"],
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=2,
        )

        second_base = validate_success(
            api.create_crew_base(
                make_crew_base_payload(
                    second["id"],
                    station_code="MKE",
                    pilots_required_per_aircraft=2,
                    aircraft_allocation_cap=3,
                ),
                headers=OPS_HEADERS,
            ),
            201,
        )

        assert second_base["station_code"] == "MKE"
        assert second_base["agreement_id"] == second["id"]
        assert_status(second_base, "ACTIVE", field="lifecycle_status")

        assert second_base["id"] != first_base["id"]
        assert first_base["pilots_required_per_aircraft"] == 1
        assert second_base["pilots_required_per_aircraft"] == 2

        _first_bases, first_meta = validate_paginated(
            api.list_crew_bases(headers=OPS_HEADERS, params={"agreement_id": first["id"]})
        )
        _second_bases, second_meta = validate_paginated(
            api.list_crew_bases(headers=OPS_HEADERS, params={"agreement_id": second["id"]})
        )
        assert first_meta["total_count"] == 1
        assert second_meta["total_count"] == 1


class TestPassThroughCategoryLockIsConditional:
    """A live claim holds the category; a rejected one hands it back."""

    def test_the_category_reopens_only_once_the_incumbent_claim_has_been_rejected(self, api):
        """The identical create is a conflict before the rejection and a creation after it.

        PRD 3.6: "At most one live claim may exist per category per month: if another claim
        for the same `cycle_id` and `category` exists in any status other than `REJECTED`,
        the request is refused with `ERR_DUPLICATE_PASSTHROUGH_CATEGORY` (HTTP 409). A
        rejected claim, by contrast, frees the category, so a mis-filed category can be
        re-opened after rejection."

        PRD 3.6: "That running total is the sum of `estimated_amount_usd` over the month's
        claims whose status is `SUBMITTED`, `ACTUAL_SUBMITTED` or `RECONCILED` — a rejected
        claim contributes nothing to it."

        Design: Corner/validations/duplicate_passthrough_category_rejected_unless_prior_claim_was_rejected
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
        incumbent = open_pass_through(
            api, cycle["id"], category="AIRPORT_FEES", estimated_amount_usd=4000.00
        )

        validate_error(
            api.create_pass_through_claim(
                make_pass_through_payload(
                    cycle["id"], category="AIRPORT_FEES", estimated_amount_usd=4500.00
                ),
                headers=OPS_HEADERS,
            ),
            ERR_DUPLICATE_PASSTHROUGH_CATEGORY,
            409,
        )

        validate_success(
            api.submit_actual(
                incumbent["id"],
                make_submit_actual_payload(actual_amount_usd=9000.00, supporting_doc_ref="DOC-C1"),
                headers=OPS_HEADERS,
            )
        )
        rejected = validate_success(
            api.reconcile_pass_through(
                incumbent["id"], make_reconcile_payload("REJECT"), headers=ADMIN_HEADERS
            )
        )
        assert_status(rejected, "REJECTED")

        replacement = validate_success(
            api.create_pass_through_claim(
                make_pass_through_payload(
                    cycle["id"], category="AIRPORT_FEES", estimated_amount_usd=4500.00
                ),
                headers=OPS_HEADERS,
            ),
            201,
        )
        assert replacement["category"] == "AIRPORT_FEES"
        assert_status(replacement, "SUBMITTED")

        claims, meta = validate_paginated(
            api.list_pass_through_claims(headers=OPS_HEADERS, params={"cycle_id": cycle["id"]})
        )
        assert meta["total_count"] == 2
        assert {claim["status"] for claim in claims} == {"REJECTED", "SUBMITTED"}

        month = read_cycle(api, cycle["id"])
        assert_money(
            month["estimated_passthrough_total_usd"],
            4500.00,
            "only the live claim's estimate counts",
        )


class TestLegIntervalGeometry:
    """An arrival earlier than its departure is unprocessable, not merely malformed."""

    def test_a_leg_that_lands_before_it_leaves_is_refused_and_publishes_nothing(self, api):
        """The interval check is decided on the two instants alone.

        PRD 3.4: "`scheduled_arrival_utc` must be strictly later than
        `scheduled_departure_utc`, and a non-positive interval is `ERR_INVALID_INTERVAL`
        (HTTP 422)."

        Design: Corner/validations/flight_leg_arrival_before_departure_rejected
        """
        scenario = build_open_cycle(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
            line_qualified_pilots=1,
            tail_numbers=["N4201RG"],
            cycle_month="2026-09",
            published_departures=5,
        )

        validate_error(
            api.create_flight_leg(
                make_flight_leg_payload(
                    scenario.cycle_id,
                    scenario.aircraft_id,
                    scenario.captain_pilot_id,
                    flight_number="SM7201",
                    origin="MKE",
                    destination="ORD",
                    scheduled_departure_utc="2026-09-02T12:00:00Z",
                    scheduled_arrival_utc="2026-09-02T11:00:00Z",
                    planned_block_hours=1.000,
                ),
                headers=SCHEDULER_HEADERS,
            ),
            ERR_INVALID_INTERVAL,
            422,
        )

        legs, meta = validate_paginated(
            api.list_flight_legs(headers=SCHEDULER_HEADERS, params={"cycle_id": scenario.cycle_id})
        )
        assert legs == []
        assert meta["total_count"] == 0
        assert read_cycle(api, scenario.cycle_id)["open_leg_count"] == 0


class TestDepartureLedgerOverflow:
    """Each cancellation is legal on its own; the ledger refuses the pair."""

    def test_the_second_cancellation_would_exceed_the_bought_departures_and_is_refused(
        self, api
    ):
        """The month bought one departure, so it can absorb only one cancellation.

        PRD 2.8: "Because the ledger may never go negative, a cancellation that would push
        the combined cancellation counts past `published_departures` is refused outright
        with `ERR_DEPARTURE_LEDGER_OVERFLOW` (HTTP 422)."

        Design: Corner/validations/second_cancellation_overflows_departure_ledger_rejected
        """
        scenario = build_open_cycle(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
            line_qualified_pilots=1,
            tail_numbers=["N4301RG"],
            cycle_month="2026-09",
            published_departures=1,
        )
        first = add_leg(
            api,
            scenario,
            flight_number="SM7301",
            origin="MKE",
            destination="ORD",
            scheduled_departure_utc="2026-09-02T08:00:00Z",
            scheduled_arrival_utc="2026-09-02T09:00:00Z",
            planned_block_hours=1.000,
        )
        second = add_leg(
            api,
            scenario,
            flight_number="SM7302",
            origin="ORD",
            destination="MKE",
            scheduled_departure_utc="2026-09-04T08:00:00Z",
            scheduled_arrival_utc="2026-09-04T09:00:00Z",
            planned_block_hours=1.000,
        )
        cancel_leg(api, first["id"], cause_code="WEATHER")

        validate_error(
            api.cancel_flight_leg(
                second["id"], make_cancel_payload("MAINTENANCE"), headers=OPS_HEADERS
            ),
            ERR_DEPARTURE_LEDGER_OVERFLOW,
            422,
        )

        untouched = read_leg(api, second["id"])
        assert_status(untouched, "SCHEDULED")
        assert_is_null(untouched, "cancel_cause_code")

        month = read_cycle(api, scenario.cycle_id)
        assert month["cancelled_controllable_count"] == 1
        assert month["metric_completed_departures"] == 0
        assert month["departure_ledger_total"] == 1

        _claims, meta = validate_paginated(
            api.list_cancellation_claims(
                headers=ADMIN_HEADERS, params={"cycle_id": scenario.cycle_id}
            )
        )
        assert meta["total_count"] == 1


class TestCaptainQualification:
    """The very same leg is refused for one captain and published for another."""

    def test_a_captain_still_in_training_cannot_be_given_the_leg(self, api):
        """Admissibility is read off the nominated captain's own status.

        PRD 3.4: "The nominated captain must be `LINE_QUALIFIED`; anyone else earns
        `ERR_PILOT_NOT_QUALIFIED` (HTTP 409)."

        Design: Corner/validations/flight_leg_with_in_training_captain_rejected
        """
        scenario = build_open_cycle(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
            line_qualified_pilots=1,
            tail_numbers=["N4401RG"],
            cycle_month="2026-09",
            published_departures=5,
        )
        trainee = hire_pilot(
            api, scenario.crew_base_id, "EMP-4402", seat="CAPTAIN", hire_class_date="2026-08-01"
        )
        trainee = advance_pilot_to(api, trainee["id"], scenario.crew_base_id, "IN_TRAINING")
        assert_status(trainee, "IN_TRAINING")

        def leg_payload(captain_pilot_id):
            return make_flight_leg_payload(
                scenario.cycle_id,
                scenario.aircraft_id,
                captain_pilot_id,
                flight_number="SM7401",
                origin="MKE",
                destination="ORD",
                scheduled_departure_utc="2026-09-02T08:00:00Z",
                scheduled_arrival_utc="2026-09-02T09:00:00Z",
                planned_block_hours=1.000,
            )

        validate_error(
            api.create_flight_leg(leg_payload(trainee["id"]), headers=SCHEDULER_HEADERS),
            ERR_PILOT_NOT_QUALIFIED,
            409,
        )

        published = validate_success(
            api.create_flight_leg(
                leg_payload(scenario.captain_pilot_id), headers=SCHEDULER_HEADERS
            ),
            201,
        )
        assert_status(published, "SCHEDULED")
        assert published["captain_pilot_id"] == scenario.captain_pilot_id

        legs, meta = validate_paginated(
            api.list_flight_legs(
                headers=SCHEDULER_HEADERS, params={"captain_pilot_id": trainee["id"]}
            )
        )
        assert legs == []
        assert meta["total_count"] == 0
        assert read_cycle(api, scenario.cycle_id)["open_leg_count"] == 1


class TestEvidenceOnVerification:
    """Evidence is optional on the endpoint and mandatory for one destination."""

    def test_verification_without_evidence_is_refused_and_succeeds_once_supplied(self, api):
        """The step into progress needed no evidence; the step into verification does.

        PRD 3.7: "Reaching `VERIFIED` additionally requires an `evidence_ref` in the
        request, and its absence is refused with `ERR_EVIDENCE_REQUIRED` (HTTP 422); the
        supplied value is stored on the audit."

        Design: Corner/validations/remediation_verified_without_evidence_rejected
        """
        scenario = build_active_agreement(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )
        audit = create_brand_audit(
            api, scenario.crew_base_id, audit_scope="UNIFORM", findings_count=2, severity="MINOR"
        )
        validate_success(
            api.advance_remediation(
                audit["id"], make_remediation_payload("IN_PROGRESS"), headers=OPS_HEADERS
            )
        )

        validate_error(
            api.advance_remediation(
                audit["id"], make_remediation_payload("VERIFIED"), headers=OPS_HEADERS
            ),
            ERR_EVIDENCE_REQUIRED,
            422,
        )

        blocked = read_brand_audit(api, audit["id"])
        assert_status(blocked, "IN_PROGRESS", field="remediation_status")
        assert_is_null(blocked, "evidence_ref")

        verified = validate_success(
            api.advance_remediation(
                audit["id"],
                make_remediation_payload("VERIFIED", evidence_ref="EV-4501"),
                headers=OPS_HEADERS,
            )
        )
        assert_status(verified, "VERIFIED", field="remediation_status")
        assert verified["evidence_ref"] == "EV-4501"
        assert_status(verified, "OPEN", field="finding_status")


class TestRoleCheckOutranksPathResolution:
    """A forbidden role learns nothing about whether the invoice exists."""

    def test_the_wrong_role_on_an_unknown_invoice_is_a_role_refusal(self, api):
        """The same unknown id yields the 404 only once the role is right.

        PRD 2.12: "2. Role authorisation for the endpoint — `ERR_FORBIDDEN_ROLE`.
        3. Existence of every identifier in the path, left to right — the resource-specific
        404 codes of §2.10."

        PRD 3.8: "An explicit void by a `CPAAdministrator` records `void_reason` as
        `MANUAL`; the two automatic causes record `AUTO_SUPERSEDED` when a newer invoice
        displaced a draft and `AUTO_SCORECARD_STALE` when the scorecard cascade of §3.7
        invalidated the bill."

        Design: Corner/validations/role_check_precedes_not_found_on_invoice_void
        """
        build_active_agreement(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )

        forbidden = validate_error(
            api.void_invoice(UNKNOWN_INVOICE_ID, headers=SCHEDULER_HEADERS),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        assert forbidden["error_id"] != ERR_INVOICE_NOT_FOUND

        validate_error(
            api.void_invoice(UNKNOWN_INVOICE_ID, headers=ADMIN_HEADERS),
            ERR_INVOICE_NOT_FOUND,
            404,
        )

        invoices, meta = validate_paginated(api.list_invoices(headers=ADMIN_HEADERS))
        assert invoices == []
        assert meta["total_count"] == 0

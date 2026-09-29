"""Authentication, role partitioning, the four-eyes rules and airline-scoped ownership."""

from test_helpers import (
    ACTION_ACCEPT,
    ACTION_WITHDRAW,
    ADMIN,
    CLOCK_COMPLETE,
    CLOCK_MANIFEST,
    CLOCK_PRODUCTION,
    CLOCK_QA,
    COMPLIANCE,
    FEED,
    LM_ALICE,
    LM_BOB,
    NON_EXISTENT_UUID,
    QA,
    SEAL_PRIMARY,
    SPEC_AN_Y,
    SUPERVISOR,
    SUPERVISOR_2,
    ApiErrorId,
    add_flight,
    assert_total_count,
    complete_batch,
    factories as f,
    issue_manifest,
    make_airline_rep_headers,
    open_manifest,
    raise_finding,
    read_flight,
    record_passing_checks,
    register_airline,
    resolve_finding,
    set_clock,
    start_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

NO_HEADERS = {}


class TestAuthenticationAndRolePartitioning:
    """Priority 10 and priority 20, and the one endpoint exempt from the first."""

    def test_only_the_clock_call_may_be_made_without_an_actor(self, api):
        """Authentication precedes path existence, so a missing row still answers 401.

        PRD §2.4: "The call mutates no entity, is permitted for every role, and is the one operation in the service exempt from the authentication check — a request without `X-User-ID` still sets the clock."

        PRD §2.1: "A request whose `X-User-ID` is absent or does not resolve to a known user is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/a_request_without_an_actor_header_is_unauthenticated_except_on_the_clock
        """
        clock = validate_success(
            api.set_clock("2026-09-12T09:00:00Z", NO_HEADERS), 200
        )
        assert clock["current_utc"].startswith("2026-09-12T09:00:00")

        validate_error(
            api.list_airlines(NO_HEADERS),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )
        # Not a 404: the authentication band short-circuits the path check.
        validate_error(
            api.get_flight(NON_EXISTENT_UUID, NO_HEADERS),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )
        validate_error(
            api.create_flight(f.flight_payload(NON_EXISTENT_UUID), NO_HEADERS),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )
        _, meta = validate_paginated(api.list_flights(FEED))
        assert_total_count(meta, 0)

    def test_reference_data_ownership_and_schedule_ingestion_do_not_overlap(
        self, base_env
    ):
        """Neither role can borrow the other's write, and the body is never reached.

        PRD §2.1: "`PlatformAdmin` owns reference data only — airline contracts, meal specifications, high-lift trucks and aircraft stands — and is deliberately barred from ingesting flights, planning production, building carts, delivering or reconciling."

        Design: Corner/rbac/platform_admin_cannot_ingest_flights_and_the_schedule_operator_cannot_create_airlines
        """
        env = base_env
        api = env.api
        validate_error(
            api.create_flight(
                f.flight_payload(env.airline_id, pax_economy=180), ADMIN
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )
        validate_error(
            api.create_airline(
                f.airline_payload(
                    name="Interloper Air",
                    iata_code="IL",
                    waste_regime="DOMESTIC",
                    cost_cap_per_pax_cents=5000,
                ),
                FEED,
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )

        _, flight_meta = validate_paginated(
            api.list_flights(FEED, {"airline_id": env.airline_id})
        )
        assert_total_count(flight_meta, 0)
        _, airline_meta = validate_paginated(api.list_airlines(ADMIN))
        assert_total_count(airline_meta, 1)

    def test_the_officer_who_measures_may_not_certify_and_the_reverse(
        self, planned_env
    ):
        """The food-safety split is by role, so both crossings are plain 403s.

        PRD §2.1: "`QaOfficer` is the only role permitted to record HACCP temperature measurements, and is deliberately not permitted to release the batch those measurements gate."

        Design: Corner/rbac/the_qa_officer_cannot_release_the_batch_it_certified
        """
        env = planned_env
        api = env.api
        batch_id = env.batch["id"]
        set_clock(api, CLOCK_PRODUCTION)
        start_batch(api, batch_id)
        set_clock(api, CLOCK_QA)
        record_passing_checks(api, batch_id, list(SPEC_AN_Y["required_haccp_steps"]))
        set_clock(api, CLOCK_COMPLETE)
        complete_batch(api, batch_id, 180)

        validate_error(
            api.release_batch(batch_id, {}, QA),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )
        held = validate_success(api.get_production_batch(batch_id, SUPERVISOR), 200)
        assert held["production_status"] == "COMPLETED"
        assert held["released_at"] is None

        validate_error(
            api.record_haccp_check(
                batch_id, f.haccp_payload("HOLD_TEMP", 4.0), SUPERVISOR
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )
        _, meta = validate_paginated(
            api.list_haccp_checks(QA, {"production_batch_id": batch_id})
        )
        assert_total_count(meta, 2)

        released = validate_success(api.release_batch(batch_id, {}, SUPERVISOR_2), 200)
        assert released["production_status"] == "RELEASED"
        assert released["released_by_user_id"] == "ps_carol"


class TestFourEyesAndOwnership:
    """One split by user id, one split by the airline the row resolves to."""

    def test_the_load_master_who_sealed_a_cart_may_not_issue_its_manifest(
        self, sealed_env
    ):
        """Both actors clear the role band; the refusal compares two recorded ids.

        PRD §3.6: "The acting `X-User-ID` must differ from the `sealed_by_user_id` of every cart entering the snapshot, or the issue is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/the_load_master_who_sealed_a_cart_cannot_issue_its_manifest
        """
        env = sealed_env
        api = env.api
        assert env.cart["sealed_by_user_id"] == "lm_alice"
        set_clock(api, CLOCK_MANIFEST)
        manifest = open_manifest(api, env.flight_id, headers=LM_BOB)

        validate_error(
            api.issue_loading_manifest(manifest["id"], {}, LM_ALICE),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            422,
        )
        draft = validate_success(
            api.get_loading_manifest(manifest["id"], LM_BOB), 200
        )
        assert draft["status"] == "DRAFT"
        assert draft["issued_at"] is None
        assert read_flight(api, env.flight_id)["status"] == "PLANNED"

        issued = issue_manifest(api, manifest["id"], headers=LM_BOB)
        assert issued["status"] == "ISSUED"
        assert issued["issued_by_user_id"] == "lm_bob"
        assert issued["total_units"] == 180
        assert [entry["seal_number"] for entry in issued["cart_seal_snapshot"]] == [
            SEAL_PRIMARY
        ]
        assert read_flight(api, env.flight_id)["status"] == "LOADED"

    def test_a_representative_of_another_airline_is_refused_on_scope_not_existence(
        self, base_env
    ):
        """The same path answers 403 for the wrong airline and 200 for the owner.

        PRD §2.1: "When `X-User-Role` is `AirlineRep`, `X-User-ID` is the `id` of the acting `Airline`; ownership checks on any resource that references an `Airline` compare the resource's airline identifier — resolved through the owning `Flight` or `MealSpecification` when the row carries no direct `airline_id` — against `X-User-ID`, and a mismatch is rejected with `ERR_AIRLINE_SCOPE_VIOLATION`."

        Design: Corner/rbac/an_airline_rep_reading_another_airlines_flight_gets_an_airline_scope_violation
        """
        env = base_env
        api = env.api
        add_flight(env)
        stranger = register_airline(
            api,
            name="Sunbridge",
            iata_code="SB",
            waste_regime="DOMESTIC",
            cost_cap_per_pax_cents=6000,
        )
        stranger_headers = make_airline_rep_headers(stranger["id"])

        validate_error(
            api.get_flight(env.flight_id, stranger_headers),
            ApiErrorId.ERR_AIRLINE_SCOPE_VIOLATION.value,
            403,
        )
        validate_error(
            api.get_cost_report(env.flight_id, stranger_headers),
            ApiErrorId.ERR_AIRLINE_SCOPE_VIOLATION.value,
            403,
        )

        owned = validate_success(api.get_flight(env.flight_id, env.rep_headers), 200)
        assert owned["id"] == env.flight_id
        assert owned["airline_id"] == env.airline_id


class TestTheSharedAuditWrite:
    """The one write two roles share, and the action-level partition above it."""

    def test_both_audit_roles_may_open_a_finding_and_the_row_records_which_did(
        self, base_env
    ):
        """`source` is derived from the raiser, and only the airline may withdraw.

        PRD §3.10: "`source` is recorded as `AIRLINE` when the raiser is an `AirlineRep` and as `SYSTEM` otherwise."

        PRD §3.10: "Withdrawal subtracts the finding's `penalty_cents` from `penalty_accrued_cents` only when the prior status was `ACCEPTED`, and decrements `open_finding_count` only when the prior status was `OPEN`."

        Design: Corner/rbac/both_audit_roles_may_open_findings_and_only_the_airline_may_withdraw_its_own
        """
        env = base_env
        api = env.api
        add_flight(env)

        by_airline = raise_finding(
            api,
            env.airline_id,
            env.flight_id,
            "LATE_DELIVERY",
            "MINOR",
            headers=env.rep_headers,
            evidence_ref="AIRLINE-TICKET-9",
        )
        assert by_airline["source"] == "AIRLINE"
        # 80,000 cents base at the MINOR multiplier of one.
        assert by_airline["penalty_cents"] == 80000

        by_service = raise_finding(
            api, env.airline_id, env.flight_id, "SPEC_DEVIATION", "MINOR"
        )
        assert by_service["source"] == "SYSTEM"
        assert by_service["penalty_cents"] == 120000

        airline = env.reload_airline()
        assert airline["open_finding_count"] == 2
        assert airline["penalty_accrued_cents"] == 0

        withdrawn = resolve_finding(
            api,
            by_airline["id"],
            ACTION_WITHDRAW,
            headers=env.rep_headers,
            note="raised in error",
        )
        assert withdrawn["status"] == "WITHDRAWN"
        after = env.reload_airline()
        assert after["open_finding_count"] == 1
        # Nothing had been accepted, so there was no penalty to give back.
        assert after["penalty_accrued_cents"] == 0

        rows, meta = validate_paginated(
            api.list_audit_findings(
                COMPLIANCE, {"airline_id": env.airline_id, "source": "SYSTEM"}
            )
        )
        assert_total_count(meta, 1)
        assert rows[0]["id"] == by_service["id"]

    def test_the_resolution_endpoint_partitions_its_actions_by_role(self, base_env):
        """Same endpoint, same role, and the action string decides the answer.

        PRD §3.10: "**Withdrawing** is the `AirlineRep`'s, permitted only when the acting `X-User-ID` is the finding's own airline, and applies from `OPEN`, `DISPUTED` or `ACCEPTED`, moving the finding `OPEN → WITHDRAWN`, `DISPUTED → WITHDRAWN` or `ACCEPTED → WITHDRAWN` respectively."

        Design: Corner/rbac/the_compliance_officer_cannot_withdraw_a_finding_it_does_not_own
        """
        env = base_env
        api = env.api
        add_flight(env)
        finding = raise_finding(
            api, env.airline_id, env.flight_id, "SPEC_DEVIATION", "MINOR"
        )
        assert finding["status"] == "OPEN"

        validate_error(
            api.resolve_audit_finding(
                finding["id"],
                f.resolution_payload(ACTION_WITHDRAW, note="not our fault"),
                COMPLIANCE,
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            403,
        )
        assert (
            validate_success(api.get_audit_finding(finding["id"], COMPLIANCE), 200)[
                "status"
            ]
            == "OPEN"
        )

        accepted = resolve_finding(
            api, finding["id"], ACTION_ACCEPT, note="conceded"
        )
        assert accepted["status"] == "ACCEPTED"
        airline = env.reload_airline()
        assert airline["open_finding_count"] == 0
        assert airline["penalty_accrued_cents"] == 120000

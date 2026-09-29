"""Three error families in isolation: the blank identity that outranks every
other rule, the facility scope check that sits just behind the role check, and
the four ways a retest reference to a predecessor audit can be refused."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_rata_test,
    assert_unit,
    make_facility_operator_headers,
    make_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import (
    control_outage_payload,
    facility_payload,
    rata_test_payload,
)

CLOCK_AUGUST = "2026-08-01T00:00:00Z"
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"
ANONYMOUS = make_headers("", "RegulatoryReviewer")


def _unit(unit_id):
    return validate_success(api_client.get_unit(unit_id, fx.REVIEWER))


def _rata(rata_test_id):
    return validate_success(api_client.get_rata_test(rata_test_id, fx.QA))


class TestBlankCallerIdentity:
    """A blank X-User-ID is refused on reads, on unknown ids and on writes."""

    def test_an_anonymous_caller_learns_nothing_about_existence_or_duplicates(self):
        """401 in place of the 200, the 404 and the 409 the same calls earn.

        PRD: "(1) `X-User-ID` present and non-empty, else `ERR_UNAUTHENTICATED`."

        PRD: "The server evaluates them in a **single fixed global order** and
        returns the first violation it finds; it never reports a later violation in
        place of an earlier one."

        Design: Corner/errors/err_missing_caller_identity_is_rejected_everywhere
        """
        fx.set_clock(CLOCK_AUGUST)
        facility = fx.create_facility()

        validate_error(
            api_client.get_facility(facility["id"], ANONYMOUS),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
        )
        validate_error(
            api_client.get_facility(UNKNOWN_ID, ANONYMOUS),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
        )
        duplicate_orispl = facility_payload(
            name="Harrier Energy Center",
            state_code="IN",
            operator_org="op_beta",
            true_up_deadline_utc="2027-03-01T00:00:00Z",
        )
        validate_error(
            api_client.create_facility(duplicate_orispl, ANONYMOUS),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
        )

        identified_read = validate_success(
            api_client.get_facility(facility["id"], fx.REVIEWER)
        )
        assert identified_read["id"] == facility["id"], (
            "the identical read succeeds once an identity is supplied"
        )
        validate_error(
            api_client.get_facility(UNKNOWN_ID, fx.REVIEWER),
            ApiErrorId.ERR_FACILITY_NOT_FOUND.value,
        )
        validate_error(
            api_client.create_facility(duplicate_orispl, fx.REVIEWER),
            ApiErrorId.ERR_DUPLICATE_ORISPL_CODE.value,
        )

        _, meta = validate_paginated(api_client.list_facilities(fx.REVIEWER))
        assert meta["total_count"] == 1, (
            "neither the anonymous write nor the duplicate write created a row, got "
            f"{meta['total_count']} facilities"
        )


class TestFacilityScopeAgainstAnotherOperator:
    """op_beta is refused where op_alpha succeeds, and a wrong role loses earlier."""

    def test_a_foreign_operator_is_scoped_out_while_a_wrong_role_is_unauthorized(self):
        """Two scope violations, one authorization failure, then the real move.

        PRD: "When `X-User-Role` is `FacilityOperator`, `X-User-ID` is the identity of
        the acting facility: ownership checks compare the `operator_org` of the
        facility reached through the request path or body against `X-User-ID`, and a
        mismatch is rejected with `ERR_FACILITY_SCOPE_VIOLATION` (HTTP 403)."

        PRD: "Ten write operations are subject to the `FacilityOperator` scope check:
        adding a unit to a facility, installing a monitoring system on a unit,
        recording a daily calibration, appending a single operating hour, appending
        operating hours in bulk, running a missing-data substitution over a unit,
        recording a fuel sample, planning a control outage window, transitioning a
        control outage window, and changing a unit's dispatch position."

        PRD: "(3) The role is permitted on this endpoint, else `ERR_UNAUTHORIZED` —
        evaluated before any existence lookup. (4) A `FacilityOperator` is acting
        within its own facility, else `ERR_FACILITY_SCOPE_VIOLATION`."

        Design: Corner/errors/err_operator_cannot_reach_another_operators_unit
        """
        station = fx.setup_facility_and_unit(clock=CLOCK_AUGUST)
        unit_id = station["unit"]["id"]
        foreign_operator = make_facility_operator_headers("op_beta")

        validate_error(
            api_client.set_unit_dispatch(
                unit_id, {"dispatch_state": "ONLINE"}, foreign_operator
            ),
            ApiErrorId.ERR_FACILITY_SCOPE_VIOLATION.value,
        )
        assert _unit(unit_id)["dispatch_state"] == "OFFLINE"

        validate_error(
            api_client.plan_control_outage(
                unit_id,
                control_outage_payload(
                    start_utc="2026-08-10T00:00:00Z", end_utc="2026-08-12T00:00:00Z"
                ),
                foreign_operator,
            ),
            ApiErrorId.ERR_FACILITY_SCOPE_VIOLATION.value,
        )
        _, outage_meta = validate_paginated(
            api_client.list_control_outages(fx.REVIEWER, {"unit_id": unit_id})
        )
        assert outage_meta["total_count"] == 0, (
            "the scoped-out plan created no window"
        )

        validate_error(
            api_client.set_unit_dispatch(unit_id, {"dispatch_state": "ONLINE"}, fx.QA),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )

        moved = validate_success(
            api_client.set_unit_dispatch(
                unit_id,
                {"dispatch_state": "ONLINE"},
                make_facility_operator_headers(station["facility"]["operator_org"]),
            )
        )
        assert_unit(moved)
        assert moved["dispatch_state"] == "ONLINE"
        assert moved["version"] == 2, (
            f"one dispatch move advances the unit to version 2, got {moved['version']}"
        )


class TestRetestReferenceNotFoundCases:
    """An unknown predecessor and another system's audit both read as absent."""

    def _two_system_station(self):
        station = fx.setup_facility_and_unit(clock=CLOCK_AUGUST, online=True)
        unit_id = station["unit"]["id"]
        station["so2_system"] = fx.install_monitoring_system(
            unit_id, parameter="SO2", span_value=400.0
        )
        station["co2_system"] = fx.install_monitoring_system(
            unit_id, parameter="CO2", span_value=20.0
        )
        station["foreign_audit"] = validate_success(
            api_client.schedule_rata_test(
                station["co2_system"]["id"],
                rata_test_payload(
                    window_start_utc="2026-08-06T00:00:00Z",
                    window_end_utc="2026-08-07T00:00:00Z",
                ),
                fx.QA,
            ),
            201,
        )
        return station

    def test_an_unknown_id_and_another_systems_audit_are_both_reported_absent(self):
        """The cross-parent reference is 404, never a scope or state error.

        PRD: "(9) Every foreign key supplied in the request **body** resolves, checked
        in the order the fields are declared for that endpoint; this covers
        `allowance_account_id` and then `counterparty_account_id` on a transaction
        proposal, `fuel_sample_id` on a single or bulk operating-hour append, and
        `retest_of_rata_test_id` on scheduling an audit."

        PRD: "(10) A referenced child actually belongs to the parent named in the
        path — a `fuel_sample_id` must belong to the unit in the path, a
        `retest_of_rata_test_id` must belong to the monitoring system in the path, and
        a certification named for revocation must belong to its report. A
        cross-parent reference is reported as the relevant *not found* error rather
        than as a scope violation, so the caller learns nothing about another parent's
        data."

        Design: Corner/errors/err_retest_must_cite_a_failed_unclaimed_audit_of_the_same_system
        """
        station = self._two_system_station()
        so2_system_id = station["so2_system"]["id"]

        for predecessor in (UNKNOWN_ID, station["foreign_audit"]["id"]):
            validate_error(
                api_client.schedule_rata_test(
                    so2_system_id,
                    rata_test_payload(
                        window_start_utc="2026-08-10T00:00:00Z",
                        window_end_utc="2026-08-11T00:00:00Z",
                        retest_of_rata_test_id=predecessor,
                    ),
                    fx.QA,
                ),
                ApiErrorId.ERR_RATA_TEST_NOT_FOUND.value,
            )

        _, meta = validate_paginated(
            api_client.list_rata_tests(fx.QA, {"monitoring_system_id": so2_system_id})
        )
        assert meta["total_count"] == 0, (
            "neither refused schedule created an audit on the SO2 system, got "
            f"{meta['total_count']}"
        )
        assert _rata(station["foreign_audit"]["id"])["status"] == "SCHEDULED", (
            "the CO2 system's audit is untouched by the refusals"
        )


class TestRetestClaimsOneFailureOnce:
    """Only a FAILED audit may be retested, and only one retest may claim it."""

    def test_a_passed_predecessor_and_a_second_claim_are_both_refused(self):
        """The failure is voided by its one retest; a second attempt is 409.

        PRD: "When a predecessor is named, it must be sitting in `FAILED` and must
        not already be referenced by another audit, else `ERR_RETEST_ALREADY_EXISTS`;
        the predecessor then moves from `FAILED` to `VOIDED` with its `version`
        incremented, and the new row starts `SCHEDULED` with `attempt_number` one
        higher than the predecessor's."

        PRD: "The audit `PASSED` when that percentage is **at or below** 10.0 — the
        pass threshold is 10.0 for every monitored parameter, and equality passes —
        and `FAILED` when it is strictly above."

        Design: Corner/errors/err_retest_must_cite_a_failed_unclaimed_audit_of_the_same_system
        """
        station = fx.setup_facility_and_unit(clock=CLOCK_AUGUST, online=True)
        unit_id = station["unit"]["id"]
        system = fx.install_monitoring_system(unit_id, parameter="SO2", span_value=400.0)

        failed = validate_success(
            api_client.schedule_rata_test(
                system["id"],
                rata_test_payload(
                    window_start_utc="2026-08-02T00:00:00Z",
                    window_end_utc="2026-08-03T00:00:00Z",
                ),
                fx.QA,
            ),
            201,
        )
        fx.record_rata_runs(failed["id"], fx.RATA_RUNS_FAILING)
        evaluated_failed = fx.evaluate_rata_test(failed["id"])
        assert evaluated_failed["relative_accuracy_pct"] == 10.7
        assert evaluated_failed["status"] == "FAILED"
        assert evaluated_failed["attempt_number"] == 1

        passed = validate_success(
            api_client.schedule_rata_test(
                system["id"],
                rata_test_payload(
                    window_start_utc="2026-08-04T00:00:00Z",
                    window_end_utc="2026-08-05T00:00:00Z",
                ),
                fx.QA,
            ),
            201,
        )
        fx.record_rata_runs(passed["id"], fx.RATA_RUNS_PASSING)
        evaluated_passed = fx.evaluate_rata_test(passed["id"])
        assert evaluated_passed["relative_accuracy_pct"] == 10.0
        assert evaluated_passed["status"] == "PASSED", "10.0 exactly is a pass"

        validate_error(
            api_client.schedule_rata_test(
                system["id"],
                rata_test_payload(
                    window_start_utc="2026-08-10T00:00:00Z",
                    window_end_utc="2026-08-11T00:00:00Z",
                    retest_of_rata_test_id=passed["id"],
                ),
                fx.QA,
            ),
            ApiErrorId.ERR_RETEST_ALREADY_EXISTS.value,
        )

        retest = validate_success(
            api_client.schedule_rata_test(
                system["id"],
                rata_test_payload(
                    window_start_utc="2026-08-10T00:00:00Z",
                    window_end_utc="2026-08-11T00:00:00Z",
                    retest_of_rata_test_id=failed["id"],
                ),
                fx.QA,
            ),
            201,
        )
        assert_rata_test(retest)
        assert retest["status"] == "SCHEDULED"
        assert retest["retest_of_rata_test_id"] == failed["id"]
        assert retest["attempt_number"] == 2, (
            f"one higher than the predecessor's 1, got {retest['attempt_number']}"
        )
        voided = _rata(failed["id"])
        assert voided["status"] == "VOIDED", (
            "naming a failure as predecessor retires it"
        )
        assert voided["version"] == evaluated_failed["version"] + 1

        validate_error(
            api_client.schedule_rata_test(
                system["id"],
                rata_test_payload(
                    window_start_utc="2026-08-12T00:00:00Z",
                    window_end_utc="2026-08-13T00:00:00Z",
                    retest_of_rata_test_id=failed["id"],
                ),
                fx.QA,
            ),
            ApiErrorId.ERR_RETEST_ALREADY_EXISTS.value,
        )

        _, meta = validate_paginated(
            api_client.list_rata_tests(fx.QA, {"monitoring_system_id": system["id"]})
        )
        assert meta["total_count"] == 3, (
            "the failure, the pass and the single retest, got "
            f"{meta['total_count']} audits"
        )

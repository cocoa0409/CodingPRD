"""The six-role partition seen from three sides: one quarter driven end to end
with every role doing only its own work, ten exclusive writes refused to the
wrong role, and the shared reads that stay open to everyone."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_compliance_certification,
    assert_quarterly_report,
    make_facility_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import (
    allowance_transaction_payload,
    cems_hour_payload,
    certification_payload,
    daily_calibration_payload,
    facility_payload,
    fuel_analysis_payload,
    fuel_sample_payload,
    monitoring_system_payload,
    permit_limit_payload,
    quarterly_report_payload,
    single_hour_payload,
    unit_payload,
)

CLOCK_APRIL = "2026-04-02T00:00:00Z"
CLOCK_AUGUST = "2026-08-01T00:00:00Z"
OPERATOR_ORG = "op_alpha"


def _report(report_id):
    return validate_success(api_client.get_quarterly_report(report_id, fx.PREPARER))


def _account(account_id):
    return validate_success(api_client.get_allowance_account(account_id, fx.TRADER))


class TestEveryRoleDrivesItsOwnStep:
    """One quarter from registration to a recorded surrender, six roles deep."""

    def test_a_whole_compliance_quarter_completes_with_each_role_in_its_lane(self):
        """Sixteen calls, every one made by the only role that may make it.

        PRD: "**`EmissionsReportPreparer`** — prepares, validates and electronically
        submits the quarterly report, applies missing data substitution, and files
        excess emission reports. Cannot certify what it submitted."

        PRD: "**`DesignatedRepresentative`** — the legally accountable signatory for
        the source. Signs and revokes compliance certifications, and records, settles
        or reverses allowance transactions. Never proposes a transaction and never
        submits a report."

        PRD: "**`AllowanceTrader`** — the market-facing role. Proposes allowance
        purchases, transfers and voluntary surrenders, and has no authority to record
        or settle what it proposed."

        PRD: "**Submission** advances `VALIDATED` to `SUBMITTED`. The preparer supplies
        the electronic `submission_format`, either `XML_ECMPS` or `JSON_ECMPS`, and the
        server records `submitted_by_user_id` from the caller's `X-User-ID`, stamps
        `submitted_utc` from the logical clock, and increments the report's `version`."

        PRD: "A successful signature creates a **Compliance Certification** in
        `SIGNED`, recording `certifier_user_id` from `X-User-ID`, `signed_utc` from the
        logical clock, `revoked_utc` and `revocation_reason` null, and
        `certified_so2_lbs_snapshot` captured from the report's `total_so2_lbs` at the
        moment of signing."

        Design: Corner/rbac/rbac_every_role_performs_its_own_exclusive_operations
        """
        fx.set_clock(CLOCK_APRIL)
        operator = make_facility_operator_headers(OPERATOR_ORG)

        facility = validate_success(
            api_client.create_facility(
                facility_payload(true_up_deadline_utc="2027-03-01T00:00:00Z"),
                fx.REVIEWER,
            ),
            201,
        )
        unit = validate_success(
            api_client.create_unit(facility["id"], unit_payload(), operator), 201
        )
        system = validate_success(
            api_client.install_monitoring_system(
                unit["id"], monitoring_system_payload(span_value=400.0), fx.QA
            ),
            201,
        )
        calibration = validate_success(
            api_client.record_daily_calibration(
                system["id"], daily_calibration_payload(system["version"]), operator
            ),
            201,
        )
        assert calibration["result"] == "PASSED"
        certified = validate_success(
            api_client.drive_qa_status(system["id"], {"action": "CERTIFY"}, fx.QA)
        )
        assert certified["qa_status"] == "CERTIFIED"

        sample = validate_success(
            api_client.record_fuel_sample(
                unit["id"], fuel_sample_payload(lot_identifier="LOT-4471"), operator
            ),
            201,
        )
        analysed = validate_success(
            api_client.record_fuel_analysis(
                sample["id"],
                fuel_analysis_payload(gcv_btu_per_lb=12500.0, sulfur_content_pct=0.85),
                fx.QA,
            )
        )
        assert analysed["status"] == "ANALYZED"

        report = validate_success(
            api_client.open_quarterly_report(
                unit["id"], quarterly_report_payload(2026, 2), fx.PREPARER
            ),
            201,
        )
        hour = validate_success(
            api_client.append_operating_hour(
                unit["id"],
                single_hour_payload(
                    report["version"], cems_hour_payload("2026-04-01T00:00:00Z")
                ),
                operator,
            ),
            201,
        )
        assert hour["data_quality"] == "MEASURED"

        validated = validate_success(
            api_client.validate_quarterly_report(report["id"], {}, fx.PREPARER)
        )
        assert validated["status"] == "VALIDATED"
        submitted = validate_success(
            api_client.submit_quarterly_report(
                report["id"], {"submission_format": "JSON_ECMPS"}, fx.PREPARER
            )
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_by_user_id"] == "prep_1"
        assert submitted["submission_format"] == "JSON_ECMPS"

        certification = validate_success(
            api_client.sign_certification(
                report["id"],
                certification_payload(submitted["version"]),
                fx.REPRESENTATIVE,
            ),
            201,
        )
        assert_compliance_certification(certification)
        assert certification["status"] == "SIGNED"
        assert certification["certifier_user_id"] == "dr_1"

        accepted = validate_success(
            api_client.disposition_quarterly_report(
                report["id"], {"decision": "ACCEPT"}, fx.REVIEWER
            )
        )
        assert_quarterly_report(accepted)
        assert accepted["status"] == "ACCEPTED"

        account = validate_success(
            api_client.open_allowance_account(
                facility["id"],
                {
                    "program": "ARP_SO2",
                    "compliance_year": 2026,
                    "holdings_current_vintage_tons": 5.000,
                    "holdings_prior_vintage_tons": 0.000,
                    "holdings_next_vintage_tons": 0.000,
                },
                fx.REVIEWER,
            ),
            201,
        )
        proposed = validate_success(
            api_client.propose_allowance_transaction(
                allowance_transaction_payload(
                    account["version"],
                    account["id"],
                    transaction_type="SURRENDER",
                    quantity_tons=1.000,
                ),
                fx.TRADER,
            ),
            201,
        )
        assert proposed["status"] == "PROPOSED"
        recorded = validate_success(
            api_client.transition_allowance_transaction(
                proposed["id"], {"action": "RECORD"}, fx.REPRESENTATIVE
            )
        )
        assert recorded["status"] == "RECORDED"
        assert _account(account["id"])["holdings_current_vintage_tons"] == 5.000, (
            "recording moves no allowances; only settlement does"
        )


class TestReviewerAndOperatorWritesAreClosedToOthers:
    """Five station-level writes attempted by five roles that do not own them."""

    def test_five_wrong_role_station_writes_are_refused_and_nothing_moves(self):
        """Registration, revision, dispatch, QA status and a permit limit.

        PRD: "(3) The role is permitted on this endpoint, else `ERR_UNAUTHORIZED` —
        evaluated before any existence lookup."

        PRD: "A new system starts with `qa_status` of `RECERTIFICATION_PENDING`,
        `cal_status` of `CAL_EXPIRED`, `bias_adjustment_factor` of 1.0 and
        `consecutive_failed_calibrations` of 0."

        Design: Corner/rbac/rbac_exclusive_operations_are_closed_to_every_other_role
        """
        station = fx.setup_facility_and_unit(clock=CLOCK_AUGUST)
        facility_id = station["facility"]["id"]
        unit_id = station["unit"]["id"]
        system = fx.install_monitoring_system(unit_id, parameter="SO2", span_value=400.0)
        operator = make_facility_operator_headers(OPERATOR_ORG)

        refusals = [
            api_client.create_facility(
                facility_payload(
                    name="Harrier Energy Center",
                    orispl_code="7102",
                    state_code="IN",
                    operator_org="op_beta",
                    true_up_deadline_utc="2027-03-01T00:00:00Z",
                ),
                operator,
            ),
            api_client.update_facility(
                facility_id, {"max_concurrent_control_outages": 5}, fx.REPRESENTATIVE
            ),
            api_client.set_unit_dispatch(unit_id, {"dispatch_state": "ONLINE"}, fx.QA),
            api_client.drive_qa_status(system["id"], {"action": "CERTIFY"}, operator),
            api_client.create_permit_limit(
                unit_id,
                permit_limit_payload(effective_from_utc="2026-07-01T00:00:00Z"),
                fx.TRADER,
            ),
        ]
        assert len(refusals) == 5
        for response in refusals:
            validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

        facility = validate_success(api_client.get_facility(facility_id, fx.REVIEWER))
        assert facility["version"] == 1, (
            f"the refused revision spent no version, got {facility['version']}"
        )
        assert facility["max_concurrent_control_outages"] == 2
        unit = validate_success(api_client.get_unit(unit_id, fx.REVIEWER))
        assert unit["dispatch_state"] == "OFFLINE"
        after_system = validate_success(
            api_client.get_monitoring_system(system["id"], fx.QA)
        )
        assert after_system["qa_status"] == "RECERTIFICATION_PENDING", (
            "the operator's certification attempt never reached the QA axis"
        )
        _, facility_meta = validate_paginated(api_client.list_facilities(fx.REVIEWER))
        assert facility_meta["total_count"] == 1, (
            "the operator's registration attempt created nothing"
        )
        _, limit_meta = validate_paginated(
            api_client.list_permit_limits(fx.REVIEWER, {"unit_id": unit_id})
        )
        assert limit_meta["total_count"] == 0


class TestReportAndAllowanceWritesAreClosedToOthers:
    """Five report and allowance writes refused ahead of every later check."""

    def test_the_role_check_outranks_a_free_period_a_stale_version_and_the_deadline(
        self,
    ):
        """403 where a duplicate, a 412 or a deadline error would otherwise sit.

        PRD: "(3) The role is permitted on this endpoint, else `ERR_UNAUTHORIZED` —
        evaluated before any existence lookup."

        PRD: "The order is banded — authentication and authorization first, then
        request shape and existence, then state, then operational safety, then fiscal
        rules — and within a band the sequence below is exact."

        PRD: "Two preconditions gate it, in this order: the logical clock must be **at
        or after** the facility's `true_up_deadline_utc`, else
        `ERR_TRUE_UP_BEFORE_DEADLINE`; and every quarterly report of every unit of that
        facility for the account's `compliance_year` must stand at `ACCEPTED`, so a
        single report left at `DRAFT` or `REJECTED` blocks the year, else
        `ERR_REPORTS_NOT_ALL_ACCEPTED`."

        Design: Corner/rbac/rbac_exclusive_operations_are_closed_to_every_other_role
        """
        station = fx.setup_facility_and_unit(clock=CLOCK_AUGUST)
        facility_id = station["facility"]["id"]
        unit_id = station["unit"]["id"]
        report = fx.open_quarterly_report(unit_id, 2026, 3)
        account = fx.open_allowance_account(
            facility_id,
            holdings_current_vintage_tons=5.000,
            holdings_prior_vintage_tons=0.000,
            holdings_next_vintage_tons=0.000,
        )
        transaction = fx.propose_transaction(
            account["id"],
            account["version"],
            transaction_type="SURRENDER",
            quantity_tons=1.000,
        )

        refusals = [
            api_client.open_quarterly_report(
                unit_id, quarterly_report_payload(2026, 4), fx.REPRESENTATIVE
            ),
            api_client.sign_certification(
                report["id"], certification_payload(report["version"]), fx.PREPARER
            ),
            api_client.propose_allowance_transaction(
                allowance_transaction_payload(
                    account["version"],
                    account["id"],
                    transaction_type="PURCHASE",
                    quantity_tons=1.000,
                ),
                fx.REPRESENTATIVE,
            ),
            api_client.transition_allowance_transaction(
                transaction["id"], {"action": "RECORD"}, fx.TRADER
            ),
            api_client.run_true_up(account["id"], {}, fx.REPRESENTATIVE),
        ]
        assert len(refusals) == 5
        for response in refusals:
            validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

        after_report = _report(report["id"])
        assert after_report["version"] == report["version"], (
            "the preparer's certification attempt was refused on the role, so the "
            "report never saw the stale version"
        )
        assert after_report["status"] == "DRAFT"
        _, report_meta = validate_paginated(
            api_client.list_quarterly_reports(fx.PREPARER, {"unit_id": unit_id})
        )
        assert report_meta["total_count"] == 1, (
            "the free 2026 Q4 period is still free; the role check refused the open"
        )

        after_account = _account(account["id"])
        assert after_account["version"] == account["version"], (
            "the refused true-up never reached the deadline precondition"
        )
        assert after_account["status"] == "OPEN"
        assert after_account["obligation_tons"] == 0
        after_transaction = validate_success(
            api_client.get_allowance_transaction(transaction["id"], fx.TRADER)
        )
        assert after_transaction["status"] == "PROPOSED", (
            "the trader may propose but never record"
        )
        _, transaction_meta = validate_paginated(
            api_client.list_allowance_transactions(
                fx.TRADER, {"allowance_account_id": account["id"]}
            )
        )
        assert transaction_meta["total_count"] == 1


class TestSharedReadsAreOpenToEveryRole:
    """Six identities, two collections, the same rows every time."""

    def test_all_six_roles_read_the_facility_list_and_the_hour_list(self):
        """Even a foreign operator and a trader see the row unchanged.

        PRD: "| GET | `/emissions/facilities` | Lists facilities | Any |"

        PRD: "| GET | `/emissions/operating-hours` | Lists operating hours | Any |"

        PRD: "Those five roles are unscoped: they may address any facility."

        PRD: "Operating hours: `unit_id`, `quarterly_report_id`, `fuel_sample_id`,
        `data_quality`, `substitution_method`, `heat_input_method`, plus
        `from_hour_utc` and `to_hour_utc`, which bound `hour_begin_utc` as a half-open
        interval — inclusive of `from_hour_utc`, exclusive of `to_hour_utc`."

        Design: Corner/rbac/rbac_shared_reads_are_open_to_all_six_roles
        """
        station = fx.setup_draft_report_with_cems_hours(hour_count=1, clock=CLOCK_APRIL)
        unit_id = station["unit"]["id"]
        report_id = station["report"]["id"]
        before = _report(report_id)
        assert before["version"] == 2

        readers = (
            fx.REVIEWER,
            make_facility_operator_headers("op_beta"),
            fx.QA,
            fx.SECOND_PREPARER,
            fx.SECOND_REPRESENTATIVE,
            fx.TRADER,
        )
        assert len(readers) == 6

        for headers in readers:
            rows, meta = validate_paginated(
                api_client.list_facilities(headers, {"operator_org": OPERATOR_ORG})
            )
            assert meta["total_count"] == 1, (
                "every role reads the same facility list, including an operator of "
                "another station"
            )
            assert rows[0]["operator_org"] == OPERATOR_ORG

        bodies = []
        for headers in readers:
            rows, meta = validate_paginated(
                api_client.list_operating_hours(
                    headers, {"unit_id": unit_id, "data_quality": "MEASURED"}
                )
            )
            assert meta["total_count"] == 1
            bodies.append(rows[0])

        first = bodies[0]
        assert first["heat_input_mmbtu"] == 555.556
        assert first["so2_mass_lbs"] == 292.2
        for body in bodies[1:]:
            assert body == first, "every role receives an identical row"

        assert _report(report_id)["version"] == 2, (
            "twelve reads advanced nothing"
        )

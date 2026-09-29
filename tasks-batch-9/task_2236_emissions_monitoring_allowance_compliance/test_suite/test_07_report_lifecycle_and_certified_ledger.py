"""The rejection loop on one report row, the fuel sample a report depends on
through its hours, and the certified-SO2 ledger the signatures move."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_compliance_certification,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import appendix_d_hour_payload, single_hour_payload

REVOCATION_REASON = "flow monitor bias adjustment discovered after signing"
REJECTION_REASON = "hourly flow values inconsistent with the certified span"
INVALIDATION_REASON = (
    "chain of custody broken; laboratory duplicate outside repeatability"
)


def _report(report_id):
    return validate_success(api_client.get_quarterly_report(report_id, fx.PREPARER))


def _unit(unit_id):
    return validate_success(api_client.get_unit(unit_id, fx.REVIEWER))


def _certification(certification_id):
    return validate_success(
        api_client.get_certification(certification_id, fx.REPRESENTATIVE)
    )


def _hour(hour_id):
    return validate_success(api_client.get_operating_hour(hour_id, fx.PREPARER))


class TestRejectionLoop:
    """`CERTIFIED` -> `REJECTED` -> `DRAFT` is a loop back onto the same row."""

    def _certified_station(self):
        station = fx.setup_draft_report_with_cems_hours(hour_count=3)
        report_id = station["report"]["id"]

        validated = fx.validate_report(report_id)
        assert validated["status"] == "VALIDATED"
        assert validated["total_so2_lbs"] == 876.6
        assert validated["total_heat_input_mmbtu"] == 1666.668
        assert validated["total_nox_lbs"] == 300.0
        assert validated["total_co2_tons"] == 179.100
        assert validated["total_so2_tons"] == 0.438

        submitted = fx.submit_report(report_id, headers=fx.PREPARER)
        assert submitted["status"] == "SUBMITTED"
        station["certification"] = fx.sign_certification(
            report_id, submitted["version"], headers=fx.REPRESENTATIVE
        )
        return station

    def test_a_rejected_report_reopens_to_draft_and_clears_its_submission_fields(self):
        """The totals survive the reopen; the submission metadata does not.

        PRD: "Reopening raises `resubmission_count` by one, clears
        `submission_format`, `submitted_by_user_id`, `submitted_utc` and
        `rejection_reason` back to null, and increments the report's `version`."

        Design: Difficulty/non_linear_state_machine/non_linear_quarterly_report_cycles_rejected_back_to_draft_and_resubmits
        """
        station = self._certified_station()
        report_id = station["report"]["id"]
        unit_id = station["unit"]["id"]

        certified = _report(report_id)
        assert certified["status"] == "CERTIFIED"
        assert _unit(unit_id)["certified_so2_lbs_ytd"] == 876.6

        rejected = fx.reject_report(report_id, REJECTION_REASON)
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == REJECTION_REASON
        assert (
            _certification(station["certification"]["id"])["status"] == "REVOKED"
        )
        assert _unit(unit_id)["certified_so2_lbs_ytd"] == 0.0

        reopened = validate_success(
            api_client.reopen_quarterly_report(report_id, {}, fx.PREPARER)
        )
        assert reopened["status"] == "DRAFT"
        assert reopened["resubmission_count"] == 1
        assert reopened["submission_format"] is None
        assert reopened["submitted_by_user_id"] is None
        assert reopened["submitted_utc"] is None
        assert reopened["rejection_reason"] is None
        assert reopened["total_so2_lbs"] == 876.6, (
            "reopening does not discard the computed emissions"
        )
        assert reopened["operating_hour_count"] == 3

    def test_the_reopened_report_is_certified_by_the_same_representative_again(self):
        """The duties check reads whoever submitted this time, so dr_1 may sign.

        PRD: "The preparer then re-validates, re-submits, and a representative
        re-certifies — potentially a different representative, since the duties
        check reads whoever submitted this time."

        Design: Difficulty/non_linear_state_machine/non_linear_quarterly_report_cycles_rejected_back_to_draft_and_resubmits
        """
        station = self._certified_station()
        report_id = station["report"]["id"]
        unit_id = station["unit"]["id"]

        fx.reject_report(report_id, REJECTION_REASON)
        validate_success(api_client.reopen_quarterly_report(report_id, {}, fx.PREPARER))

        fx.validate_report(report_id, headers=fx.SECOND_PREPARER)
        resubmitted = fx.submit_report(
            report_id, submission_format="JSON_ECMPS", headers=fx.SECOND_PREPARER
        )
        assert resubmitted["submission_format"] == "JSON_ECMPS"

        second = validate_success(
            api_client.sign_certification(
                report_id,
                {
                    "expected_quarterly_report_version": resubmitted["version"],
                    "statement_text": (
                        "I certify under penalty of law that this submission was "
                        "prepared under my direction."
                    ),
                },
                fx.REPRESENTATIVE,
            ),
            201,
        )
        assert_compliance_certification(second)
        assert second["status"] == "SIGNED"
        assert second["certified_so2_lbs_snapshot"] == 876.6
        assert _report(report_id)["status"] == "CERTIFIED"
        assert _unit(unit_id)["certified_so2_lbs_ytd"] == 876.6

        accepted = fx.accept_report(report_id)
        assert accepted["status"] == "ACCEPTED"

        rows, meta = validate_paginated(
            api_client.list_report_certifications(report_id, fx.PREPARER)
        )
        assert meta["total_count"] == 2, (
            f"the loop leaves two certification rows, got {meta['total_count']}"
        )
        signed = [row for row in rows if row["status"] == "SIGNED"]
        assert len(signed) == 1, (
            "exactly one certification of the accepted report is still SIGNED"
        )


class TestReportDependsOnFuelSample:
    """The dependency runs report -> hour -> fuel sample."""

    def _appendix_d_station(self):
        station = fx.setup_facility_and_unit()
        unit_id = station["unit"]["id"]
        operator_org = station["facility"]["operator_org"]
        station["appendix_d_system"] = fx.setup_appendix_d_system(unit_id)
        station["analyzed_sample"] = fx.setup_analyzed_fuel_sample(
            unit_id,
            operator_org,
            analysis_overrides={
                "gcv_btu_per_lb": 12500.0,
                "sulfur_content_pct": 0.85,
            },
        )
        station["pending_sample"] = validate_success(
            api_client.record_fuel_sample(
                unit_id,
                {
                    "sample_utc": "2026-04-01T06:00:00Z",
                    "fuel_type": "COAL",
                    "lot_identifier": "LOT-B",
                },
                fx.make_facility_operator_headers(operator_org),
            ),
            201,
        )
        station["report"] = fx.open_quarterly_report(unit_id)
        station["hours"] = fx.append_hours_bulk(
            unit_id,
            station["report"]["version"],
            [
                appendix_d_hour_payload(
                    f"2026-04-01T{hour:02d}:00:00Z",
                    station["analyzed_sample"]["id"],
                )
                for hour in range(3)
            ],
        )
        return station

    def test_an_hour_cannot_reference_a_sample_that_is_still_pending(self):
        """The pending sample is refused and no fourth hour appears.

        PRD: "An `APPENDIX_D_FUEL` hour additionally requires its referenced
        sample to be standing at `ANALYZED`, since `gcv_btu_per_lb` and
        `sulfur_content_pct` only exist once the lab has reported; a sample in any
        other status is `ERR_FUEL_SAMPLE_NOT_ANALYZED`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_report_validate_blocked_by_invalidated_fuel_sample
        """
        station = self._appendix_d_station()
        unit_id = station["unit"]["id"]

        first = station["hours"][0]
        assert first["heat_input_mmbtu"] == 562.500
        assert first["so2_mass_lbs"] == 765.0

        refused = api_client.append_operating_hour(
            unit_id,
            single_hour_payload(
                first["quarterly_report_version_after"],
                appendix_d_hour_payload(
                    "2026-04-01T03:00:00Z", station["pending_sample"]["id"]
                ),
            ),
            fx.PREPARER,
        )
        validate_error(refused, ApiErrorId.ERR_FUEL_SAMPLE_NOT_ANALYZED.value)

        _, meta = validate_paginated(
            api_client.list_operating_hours(fx.PREPARER, {"unit_id": unit_id})
        )
        assert meta["total_count"] == 3, (
            f"the refused append created nothing, found {meta['total_count']} hours"
        )

    def test_invalidating_a_consumed_sample_blocks_validation_until_reanalysis(self):
        """The stored hours are never rewritten by the sample's status change.

        PRD: "no hour of the report may reference a fuel sample standing at
        `INVALIDATED` (`ERR_FUEL_ANALYSIS_INVALIDATED`)"

        Design: Difficulty/cross_entity_state_dependency/cross_entity_report_validate_blocked_by_invalidated_fuel_sample
        """
        station = self._appendix_d_station()
        report_id = station["report"]["id"]
        sample_id = station["analyzed_sample"]["id"]
        first_hour_id = station["hours"][0]["id"]

        invalidated = validate_success(
            api_client.record_fuel_analysis(
                sample_id,
                {
                    "outcome": "INVALIDATE",
                    "invalidation_reason": INVALIDATION_REASON,
                },
                fx.QA,
            )
        )
        assert invalidated["status"] == "INVALIDATED"
        assert invalidated["invalidation_reason"] == INVALIDATION_REASON
        assert _hour(first_hour_id)["heat_input_mmbtu"] == 562.500, (
            "invalidation does not retroactively recompute stored hours"
        )

        blocked = api_client.validate_quarterly_report(report_id, {}, fx.PREPARER)
        validate_error(blocked, ApiErrorId.ERR_FUEL_ANALYSIS_INVALIDATED.value)
        assert _report(report_id)["status"] == "DRAFT"

        reanalyzed = validate_success(
            api_client.record_fuel_analysis(
                sample_id,
                {
                    "outcome": "ANALYZED",
                    "gcv_btu_per_lb": 12500.0,
                    "sulfur_content_pct": 0.85,
                    "analysis_method": "ASTM_D4239",
                },
                fx.QA,
            )
        )
        assert reanalyzed["status"] == "ANALYZED"
        assert reanalyzed["invalidation_reason"] is None
        assert reanalyzed["analysis_method"] == "ASTM_D4239"

        validated = fx.validate_report(report_id)
        assert validated["status"] == "VALIDATED"
        assert validated["total_heat_input_mmbtu"] == 1687.500
        assert validated["total_so2_lbs"] == 2295.0
        assert validated["total_nox_lbs"] == 303.9
        assert validated["total_co2_tons"] == 173.223
        assert validated["total_so2_tons"] == 1.148
        assert validated["monitor_data_availability_pct"] == 100.0
        assert validated["operating_hour_count"] == 3


class TestCertifiedSo2Ledger:
    """`certified_so2_lbs_ytd` returns to exactly where it started."""

    def _submitted_station(self):
        station = fx.setup_draft_report_with_cems_hours(hour_count=3)
        report_id = station["report"]["id"]
        fx.validate_report(report_id)
        station["submitted"] = fx.submit_report(report_id, headers=fx.PREPARER)
        return station

    def test_an_explicit_revocation_returns_the_ledger_to_zero(self):
        """876.6 is credited at signing and the same 876.6 is debited at revocation.

        PRD: "the unit's `certified_so2_lbs_ytd` is debited by **exactly**
        `certified_so2_lbs_snapshot` — precisely the amount credited at signing, so
        the ledger returns to its pre-certification value rather than to a
        re-derived one"

        Design: Difficulty/compensating_invariant/invariant_certified_so2_ledger_returns_to_zero_across_certify_and_revoke
        """
        station = self._submitted_station()
        report_id = station["report"]["id"]
        unit_id = station["unit"]["id"]

        assert _report(report_id)["total_so2_lbs"] == 876.6
        assert _unit(unit_id)["certified_so2_lbs_ytd"] == 0.0

        certification = fx.sign_certification(
            report_id, station["submitted"]["version"], headers=fx.REPRESENTATIVE
        )
        assert certification["status"] == "SIGNED"
        assert certification["certified_so2_lbs_snapshot"] == 876.6
        assert certification["certifier_user_id"] == "dr_1"
        # Server-stamped timestamps carry three fractional digits (PRD 2.5).
        assert certification["signed_utc"] == "2026-04-02T00:00:00.000Z"
        assert _unit(unit_id)["certified_so2_lbs_ytd"] == 876.6
        assert _report(report_id)["status"] == "CERTIFIED"

        revoked = validate_success(
            api_client.revoke_certification(
                certification["id"],
                {"revocation_reason": REVOCATION_REASON},
                fx.REPRESENTATIVE,
            )
        )
        assert revoked["status"] == "REVOKED"
        assert revoked["revoked_utc"] is not None
        assert revoked["revocation_reason"] == REVOCATION_REASON

        assert _unit(unit_id)["certified_so2_lbs_ytd"] == 0.0
        after = _report(report_id)
        assert after["status"] == "SUBMITTED", (
            "an explicit revocation returns the report to SUBMITTED"
        )
        assert after["total_so2_lbs"] == 876.6
        assert after["resubmission_count"] == 0, (
            "revoking neither reopens nor recomputes the report"
        )

    def test_a_rejection_debits_the_snapshot_of_the_second_certification(self):
        """The ledger walks 0.0 to 876.6 to 0.0 to 876.6 to 0.0, never to 1753.2.

        PRD: "The unit's `certified_so2_lbs_ytd` is thus a conserved ledger that
        always equals the sum of `total_so2_lbs` across that unit's reports
        standing at `CERTIFIED` or `ACCEPTED`."

        Design: Difficulty/compensating_invariant/invariant_certified_so2_ledger_returns_to_zero_across_certify_and_revoke
        """
        station = self._submitted_station()
        report_id = station["report"]["id"]
        unit_id = station["unit"]["id"]
        first_hour_id = station["hours"][0]["id"]

        first = fx.sign_certification(
            report_id, station["submitted"]["version"], headers=fx.REPRESENTATIVE
        )
        validate_success(
            api_client.revoke_certification(
                first["id"],
                {"revocation_reason": REVOCATION_REASON},
                fx.REPRESENTATIVE,
            )
        )

        second = fx.sign_certification(
            report_id,
            _report(report_id)["version"],
            headers=fx.SECOND_REPRESENTATIVE,
        )
        assert second["certified_so2_lbs_snapshot"] == 876.6
        assert second["certifier_user_id"] == "dr_2"
        assert _unit(unit_id)["certified_so2_lbs_ytd"] == 876.6, (
            "the ledger returned to exactly the same value, not to 1753.2"
        )

        rejected = fx.reject_report(report_id, REJECTION_REASON)
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == REJECTION_REASON
        assert _unit(unit_id)["certified_so2_lbs_ytd"] == 0.0
        assert _certification(second["id"])["status"] == "REVOKED"

        rows, meta = validate_paginated(
            api_client.list_report_certifications(report_id, fx.PREPARER)
        )
        assert meta["total_count"] == 2
        assert [row["status"] for row in rows] == ["REVOKED", "REVOKED"]
        assert [row["certified_so2_lbs_snapshot"] for row in rows] == [876.6, 876.6]

        assert _hour(first_hour_id)["so2_mass_lbs"] == 292.2, (
            "the ledger never rewrites the source hours"
        )

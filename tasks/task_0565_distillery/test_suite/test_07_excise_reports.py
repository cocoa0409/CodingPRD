"""Excise report filing: OCC on the distillery version and supersession."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_distillery,
    create_excise_report_payload,
)

_OC = TEST_USERS["compliance_headers"]


class TestExciseReportConcurrency:
    def test_stale_distillery_version_conflict(self, api):
        """PRD 2.9: "If `expected_distillery_version` does not match the distillery's
        current `version` — because another removal or another filing has advanced the
        ledger since the client read it — the filing is rejected with
        `ERR_STALE_VERSION` (HTTP 412)." PRD 3.7: "A successful filing increments the
        distillery's `version`."

        Design: Corner/cross_cutting/excise_report_stale_distillery_version_conflict
        """
        dist = create_distillery(api, dsp_permit_number="DSP-ER-1")
        v1 = dist["version"]
        get_success_data(
            api.create_excise_report(create_excise_report_payload(dist["id"], v1, period_month="2026-05"), _OC)
        )
        resp = api.create_excise_report(
            create_excise_report_payload(dist["id"], v1, period_month="2026-05"), _OC
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    def test_supersede_prior_filed_report(self, api):
        """PRD 3.7: "Filing supersedes any earlier report for the same distillery and
        `period_month`: the prior `FILED` report for that period transitions to
        `SUPERSEDED`, and the new report records that prior report's id in its own
        `supersedes_report_id`".

        Design: Corner/cross_cutting/excise_report_supersede_prior_filed_report
        """
        dist = create_distillery(api, dsp_permit_number="DSP-ER-2")
        r1 = get_success_data(
            api.create_excise_report(
                create_excise_report_payload(dist["id"], dist["version"], period_month="2026-05"), _OC
            )
        )
        v2 = validate_success(api.get_distillery(dist["id"], _OC))["version"]
        r2 = validate_success(
            api.create_excise_report(create_excise_report_payload(dist["id"], v2, period_month="2026-05"), _OC),
            expected_status=201,
        )
        assert r2["status"] == "FILED"
        assert r2["supersedes_report_id"] == r1["id"]
        r1_refreshed = validate_success(api.get_excise_report(r1["id"], _OC))
        assert r1_refreshed["status"] == "SUPERSEDED"

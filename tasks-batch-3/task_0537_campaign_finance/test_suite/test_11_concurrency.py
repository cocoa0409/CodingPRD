"""Optimistic-concurrency control on report creation (guarded on the committee version)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_treasurer_headers,
    create_active_committee, create_reporting_period, committee_version,
)

REGULATOR = TEST_USERS["regulator_headers"]


def test_report_create_with_matching_version_succeeds(api):
    """PRD §2.8: "The create request must carry expected_committee_version, a non-optional
    field carrying the client's last observed version of the target Committee."

    Design: Corner/cross_cutting_complexity_layers/occ_report_create_correct_version_succeeds
    """
    committee = create_active_committee(api, name="OccOk", committee_type="CANDIDATE")
    cid = committee["id"]
    period = create_reporting_period(api)
    version = committee_version(api, cid)
    report = validate_success(
        api.create_report(cid, {"period_id": period["id"], "expected_committee_version": version},
                          make_treasurer_headers(cid)),
        expected_status=201,
    )
    assert report["status"] == "DRAFT"


def test_report_create_with_stale_version_rejected(api):
    """PRD §2.8: "If that value does not equal the committee's current version — because
    another writer has advanced the committee since the client last read it — the create is
    rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_report_create_stale_version_rejected
    """
    committee = create_active_committee(api, name="OccStale", committee_type="CANDIDATE")
    cid = committee["id"]
    period = create_reporting_period(api)
    version = committee_version(api, cid)
    # First create succeeds and advances the committee version.
    validate_success(
        api.create_report(cid, {"period_id": period["id"], "expected_committee_version": version},
                          make_treasurer_headers(cid)),
        expected_status=201,
    )
    # Reusing the now-stale version is rejected.
    resp = api.create_report(cid, {"period_id": period["id"], "expected_committee_version": version},
                             make_treasurer_headers(cid))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

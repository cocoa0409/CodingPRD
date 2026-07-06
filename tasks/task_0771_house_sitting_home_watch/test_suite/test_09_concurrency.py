"""Optimistic concurrency on coverage-policy creation and sitter version advancement."""
from test_helpers import validate_success, validate_error, ApiErrorId, make_coordinator_headers
from test_helpers import factories as f
from test_helpers import fixtures as fx

COORD = make_coordinator_headers()


def test_coverage_policy_create_with_stale_sitter_version_rejected(api):
    """PRD 2.6: "If expected_sitter_version does not match the sitter's current version, the request
    is rejected with ERR_STALE_SITTER_VERSION (HTTP 412)."
    PRD 2.6: "When a policy is issued successfully, the sitter's version is incremented by one, so
    any concurrently held stale version is thereby invalidated."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_sitter_version_supersede_returns_412
    """
    sitter = fx.create_sitter(api)
    stale_version = fx.get_sitter(api, sitter["id"])["version"]
    # First issuance succeeds and bumps the sitter version, making `stale_version` stale.
    fx.get_success_data(api.create_coverage_policy(
        f.create_coverage_policy_payload(sitter["id"], stale_version, policy_type="BOND",
                                         coverage_amount_cents=1000000), COORD))
    resp = api.create_coverage_policy(
        f.create_coverage_policy_payload(sitter["id"], stale_version, policy_type="BOND",
                                         coverage_amount_cents=500000), COORD)
    validate_error(resp, ApiErrorId.ERR_STALE_SITTER_VERSION.value, expected_status=412)


def test_sitter_version_advances_on_background_check_submit(api):
    """PRD 2.4: "on every mutation that changes the resource, updated_at is refreshed to the current
    clock instant and version is incremented by one."
    PRD 3.2: "A submitted check starts in SUBMITTED, and the sitter's mirrored background_check_status
    is set to SUBMITTED."

    Design: Corner/cross_cutting_complexity_layers/sitter_version_increments_on_background_submit
    """
    sitter = fx.create_sitter(api)
    assert sitter["version"] == 1, sitter
    fx.submit_background_check(api, sitter["id"])
    updated = fx.get_sitter(api, sitter["id"])
    assert updated["version"] == 2, updated
    assert updated["background_check_status"] == "SUBMITTED", updated

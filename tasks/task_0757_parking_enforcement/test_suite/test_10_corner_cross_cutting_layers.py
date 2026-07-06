"""Corner section: cross_cutting_complexity_layers (optimistic concurrency)."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_issuing_context,
    issue_in_context,
)

SUPERVISOR = TEST_USERS["supervisor_headers"]


def test_reassess_with_current_version_succeeds(api):
    """PRD §3.7: "On success the citation's `fine_amount_cents` is set to the clamped
    new value, its `amount_due_cents` is recomputed, and the vehicle balance and
    scofflaw tier are recomputed as well; the citation's `version` increments."
    PRD §2.4: "`version` — an integer that starts at creation and increments by one
    on every mutation."

    Design: Corner/cross_cutting_complexity_layers/occ_citation_reassess_correct_version_succeeds
    """
    ctx = setup_issuing_context(base_fine_cents=5000, code="EXP_METER")
    cit = issue_in_context(ctx)
    assert cit["version"] == 1
    updated = validate_success(api.reassess_citation(
        cit["id"],
        {"new_fine_amount_cents": 8000, "expected_citation_version": cit["version"]},
        SUPERVISOR))
    assert updated["fine_amount_cents"] == 8000
    assert updated["version"] == 2, f"version must increment to 2, got {updated['version']}"


def test_reassess_with_stale_version_rejected(api):
    """PRD §2.7: "If the citation's `version` has advanced since the client observed
    it — because an intervening reassessment, waiver, payment settlement, or contest
    filing bumped it — the supplied `expected_citation_version` no longer matches the
    citation's current `version`, and the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_citation_reassess_stale_version_rejected
    """
    ctx = setup_issuing_context(base_fine_cents=5000, code="EXP_METER")
    cit = issue_in_context(ctx)
    original_version = cit["version"]
    # First reassess advances the version to 2.
    validate_success(api.reassess_citation(
        cit["id"],
        {"new_fine_amount_cents": 8000, "expected_citation_version": original_version},
        SUPERVISOR))
    # Second reassess still carrying the original (now stale) version is rejected.
    validate_error(
        api.reassess_citation(
            cit["id"],
            {"new_fine_amount_cents": 9000, "expected_citation_version": original_version},
            SUPERVISOR),
        ApiErrorId.ERR_STALE_VERSION.value)


def test_vehicle_adjustment_with_stale_version_rejected(api):
    """PRD §2.7: "If another writer — a settle, a refund, a void, or a prior waiver —
    has advanced the vehicle's `version` since it was observed, the supplied
    `expected_vehicle_version` is stale and the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_vehicle_adjustment_stale_version_rejected
    """
    ctx = setup_issuing_context(base_fine_cents=5000, code="EXP_METER")
    cit = issue_in_context(ctx)
    vid = ctx["vehicle"]["id"]
    observed = validate_success(api.get_vehicle(vid, SUPERVISOR))["version"]
    # First waiver advances the vehicle version.
    validate_success(api.create_adjustment(
        vid,
        {"citation_id": cit["id"], "waive_amount_cents": 1000,
         "expected_vehicle_version": observed}, SUPERVISOR))
    # Second waiver still carrying the originally observed (now stale) version fails.
    validate_error(
        api.create_adjustment(
            vid,
            {"citation_id": cit["id"], "waive_amount_cents": 1000,
             "expected_vehicle_version": observed}, SUPERVISOR),
        ApiErrorId.ERR_STALE_VERSION.value)

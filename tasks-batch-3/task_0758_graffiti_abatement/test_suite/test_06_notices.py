"""Property-owner notices: issuance OCC, the assessed-recovery precondition, the
dispute cascade, and expiry escalation to a lien.

Queue A (Difficulty): transitive_cascade (notice expiry -> lien), cross_entity_state_dependency
(notice requires ASSESSED recovery).
Queue B (Corner): validations (cure window), cross_cutting (OCC, version increment, dispute cascade).
"""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    setup_dispatched, setup_completed, setup_assessed_notice,
    set_clock, create_notice_payload,
)

COORD = TEST_USERS["coordinator_headers"]


# --------------------------------------------------------------------------
# transitive_cascade / notice_expire_cascade_costrecovery_site_lien
# --------------------------------------------------------------------------
def test_expire_escalates_recovery_to_lien(api):
    """PRD §3.6: "Expiry advances the notice `SENT → EXPIRED`, clears the site's `active_notice_id` if
    it pointed here, and — when the notice carries a `cost_recovery_id` whose recovery is `ASSESSED` —
    escalates that recovery `ASSESSED → LIEN_PENDING`."

    Design: Difficulty/transitive_cascade/notice_expire_cascade_costrecovery_site_lien
    """
    scn = setup_assessed_notice(api, cure_days=30)
    set_clock(api, "2026-04-01T00:00:00Z")
    notice = validate_success(api.expire_notice(scn["notice_id"], COORD), 200)
    assert notice["status"] == "EXPIRED"
    cr = validate_success(api.get_cost_recovery(scn["cost_recovery_id"], COORD), 200)
    assert cr["status"] == "LIEN_PENDING"


def test_expire_increments_site_lien_count(api):
    """PRD §3.6: "That escalation is itself a two-step cascade: reaching `LIEN_PENDING` keeps the
    recovery in the outstanding pool (no ledger change) and increments the site's `lien_count` by one."

    Design: Difficulty/transitive_cascade/notice_expire_cascade_costrecovery_site_lien
    """
    scn = setup_assessed_notice(api, cure_days=30)
    set_clock(api, "2026-04-01T00:00:00Z")
    validate_success(api.expire_notice(scn["notice_id"], COORD), 200)
    site = validate_success(api.get_site(scn["site_id"], COORD), 200)
    assert site["lien_count"] == 1


# --------------------------------------------------------------------------
# cross_entity_state_dependency / notice_requires_costrecovery_assessed
# --------------------------------------------------------------------------
def test_cost_recovery_notice_rejected_when_recovery_pending(api):
    """PRD §3.6: "a `COST_RECOVERY_NOTICE` may be issued only while its linked cost recovery is
    `ASSESSED`; issuing against a recovery in any other state is rejected with
    `ERR_RECOVERY_NOT_ASSESSED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/notice_requires_costrecovery_assessed
    """
    scn = setup_dispatched(api, ownership_type="PRIVATE", est_labor=2.0, reserve_qty=2.0)
    site = validate_success(api.get_site(scn["site_id"], COORD), 200)
    payload = create_notice_payload(notice_type="COST_RECOVERY_NOTICE", cure_days=30,
                                    expected_site_version=site["version"],
                                    cost_recovery_id=scn["cost_recovery_id"])
    resp = api.issue_notice(scn["site_id"], payload, COORD)
    validate_error(resp, ApiErrorId.ERR_RECOVERY_NOT_ASSESSED)


def test_cost_recovery_notice_accepted_once_assessed(api):
    """PRD §3.6: "a `COST_RECOVERY_NOTICE` may be issued only while its linked cost recovery is
    `ASSESSED`; issuing against a recovery in any other state is rejected with
    `ERR_RECOVERY_NOT_ASSESSED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/notice_requires_costrecovery_assessed
    """
    scn = setup_completed(api, ownership_type="PRIVATE", est_labor=2.5, reserve_qty=3.0,
                          actual_labor=3.0)
    site = validate_success(api.get_site(scn["site_id"], COORD), 200)
    payload = create_notice_payload(notice_type="COST_RECOVERY_NOTICE", cure_days=30,
                                    expected_site_version=site["version"],
                                    cost_recovery_id=scn["cost_recovery_id"])
    notice = validate_success(api.issue_notice(scn["site_id"], payload, COORD), 201)
    assert notice["status"] == "SENT"


# --------------------------------------------------------------------------
# Corner: validations / expire_before_cure_deadline_returns_cure_window_not_elapsed
# --------------------------------------------------------------------------
def test_expire_before_cure_deadline_rejected(api):
    """PRD §3.6: "Expiry is defined only from `SENT` and only when the current clock instant is at or
    after the notice's `cure_deadline`; an attempt before that instant is rejected with
    `ERR_CURE_WINDOW_NOT_ELAPSED` (HTTP 409)."

    Design: Corner/validations/expire_before_cure_deadline_returns_cure_window_not_elapsed
    """
    # Notice issued at the default clock 2026-03-01 with cure_days=30 -> cure_deadline 2026-03-31.
    # The clock is left at the default, well before the deadline.
    scn = setup_assessed_notice(api, cure_days=30)
    resp = api.expire_notice(scn["notice_id"], COORD)
    validate_error(resp, ApiErrorId.ERR_CURE_WINDOW_NOT_ELAPSED)


# --------------------------------------------------------------------------
# Corner: cross_cutting / occ_stale_site_version_on_notice_returns_412
# --------------------------------------------------------------------------
def test_notice_issue_with_stale_site_version_rejected(api):
    """PRD §2.9: "A notice-issuance request must carry `expected_site_version`, and its value must
    equal the target site's current `version`. If the site's `version` has advanced since the client
    last read it ... the request is rejected with `ERR_STALE_SITE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_site_version_on_notice_returns_412
    """
    scn = setup_assessed_notice(api, cure_days=30)
    # scn['site_version'] was the version consumed by the first issuance; the site has since advanced.
    payload = create_notice_payload(notice_type="COST_RECOVERY_NOTICE", cure_days=30,
                                    expected_site_version=scn["site_version"],
                                    cost_recovery_id=scn["cost_recovery_id"])
    resp = api.issue_notice(scn["site_id"], payload, COORD)
    validate_error(resp, ApiErrorId.ERR_STALE_SITE_VERSION)


# --------------------------------------------------------------------------
# Corner: cross_cutting / site_version_increments_on_notice_issue
# --------------------------------------------------------------------------
def test_notice_issue_advances_site_version_by_one(api):
    """PRD §3.6: "any prior `SENT` notice for the same site is driven `SENT → WITHDRAWN`, the site's
    `active_notice_id` is repointed to the new notice, and the site's `version` is incremented by one".

    Design: Corner/cross_cutting_complexity_layers/site_version_increments_on_notice_issue
    """
    scn = setup_completed(api, ownership_type="PRIVATE", est_labor=2.5, reserve_qty=3.0,
                          actual_labor=3.0)
    before = validate_success(api.get_site(scn["site_id"], COORD), 200)
    payload = create_notice_payload(notice_type="COST_RECOVERY_NOTICE", cure_days=30,
                                    expected_site_version=before["version"],
                                    cost_recovery_id=scn["cost_recovery_id"])
    notice = validate_success(api.issue_notice(scn["site_id"], payload, COORD), 201)
    after = validate_success(api.get_site(scn["site_id"], COORD), 200)
    assert after["active_notice_id"] == notice["id"]
    assert after["version"] == before["version"] + 1


# --------------------------------------------------------------------------
# Corner: cross_cutting / notice_dispute_cascades_costrecovery_disputed
# --------------------------------------------------------------------------
def test_notice_dispute_cascades_recovery_disputed_ledger_unchanged(api):
    """PRD §3.6: "**Dispute** advances the notice `SENT → DISPUTED`, also requires ownership, sets
    `response_at`, and — when the notice carries a `cost_recovery_id` whose recovery is `ASSESSED` —
    cascades that recovery `ASSESSED → DISPUTED` (a status change that keeps the recovery in the
    outstanding pool, so the site ledger is unchanged)."

    Design: Corner/cross_cutting_complexity_layers/notice_dispute_cascades_costrecovery_disputed
    """
    scn = setup_assessed_notice(api, cure_days=30)
    notice = validate_success(api.dispute_notice(scn["notice_id"], {"reason": "not my tag"},
                                                 scn["owner_headers"]), 200)
    assert notice["status"] == "DISPUTED"
    cr = validate_success(api.get_cost_recovery(scn["cost_recovery_id"], COORD), 200)
    assert cr["status"] == "DISPUTED"
    site = validate_success(api.get_site(scn["site_id"], COORD), 200)
    assert site["outstanding_recovery_cents"] == 26565

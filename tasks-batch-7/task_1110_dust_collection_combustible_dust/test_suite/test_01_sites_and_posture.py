"""Site bootstrap, derived counters, pagination, and posture derivation."""
from test_helpers import (
    ApiErrorId,
    assert_site,
    create_site,
    create_site_payload,
    setup_site_in_stop_work,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    TEST_USERS,
)
from test_helpers.fixtures import create_collector, create_dust_sample

ADMIN = TEST_USERS["platform_admin_headers"]
ENGINEER = TEST_USERS["compliance_engineer_headers"]


def test_site_creation_initializes_posture_and_counters(api):
    """PRD §3.1: "The new Site is born in `CONDITIONAL` posture with all three
    derived counters at zero: `open_critical_findings` counts `InspectionFinding`
    rows at the site with status `OPEN` and severity `CRITICAL`;
    `open_overdue_housekeeping` counts `HousekeepingAudit` rows at the site with
    status `OVERDUE`; `hot_work_in_progress` counts `HotWorkPermit` rows at the
    site with status `IN_PROGRESS`."

    Design: Corner/entities/site_creation_required_fields_and_defaults
    """
    res = api.create_site(create_site_payload(
        name="A", address="x", ahj_authority="j", insurer_id="FM-1"), ADMIN)
    created = validate_success(res, 201)
    assert_site(created)

    site = validate_success(api.get_site(created["id"], ENGINEER), 200)
    assert site["posture"] == "CONDITIONAL"
    assert site["open_critical_findings"] == 0
    assert site["open_overdue_housekeeping"] == 0
    assert site["hot_work_in_progress"] == 0


def test_get_site_non_existent_returns_not_found(api):
    """PRD §2.9: "The Site `id` is resolved first; if it does not exist the
    request is rejected with `ERR_NOT_FOUND` (HTTP 404) before any child segment
    is examined."

    Design: Corner/entities/site_get_non_existent_returns_not_found
    """
    res = api.get_site("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", ENGINEER)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_list_sites_pagination_defaults(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return; it defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_pagination_default_limit_offset
    """
    for i in range(12):
        create_site(name=f"S{i + 1:02d}")

    data, meta = validate_paginated(api.list_sites(ENGINEER))
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 12
    assert meta["has_more"] is True
    assert len(data) == 10


def test_recompute_posture_fresh_site_is_compliant(api):
    """PRD §2.4: "a `posture_score` of at least 85 yields `COMPLIANT`".
    PRD §3.1: "An administrative `recompute_posture` action (restricted to
    `PlatformAdmin` and `ComplianceManager`) forces the site-posture derivation
    to run against the current counters; it refreshes `posture` and
    `posture_score`, refreshes `updated_at`, and increments the site's `version`
    by 1."

    Design: Corner/consistency_model/immediate_consistency_collector_commission_reflects_in_site_posture
    """
    site = create_site(insurer_id="FM-1")
    validate_success(api.recompute_posture(site["id"], ADMIN), 200)

    after = validate_success(api.get_site(site["id"], ENGINEER), 200)
    assert after["posture"] == "COMPLIANT"
    assert after["posture_score"] == 100


def test_two_critical_findings_force_stop_work(api):
    """PRD §2.4: "There is one override that ignores the score entirely: if the
    site carries 2 or more open critical findings, posture is forced to
    `STOP_WORK` regardless of what the numeric score would have produced."
    PRD §3.7: "When a finding of severity `CRITICAL` is created, the owning
    Site's `open_critical_findings` counter increments by 1 and the site's
    `version` increments by 1; posture is recomputed."

    Design: Corner/calculations/site_posture_stop_work_overrides_high_score
    """
    site, _inspection, _findings = setup_site_in_stop_work(insurer_id="FM-1")

    after = validate_success(api.get_site(site["id"], ENGINEER), 200)
    assert after["open_critical_findings"] == 2
    assert after["posture"] == "STOP_WORK"


def test_commission_blocked_by_stop_work_before_vent_check(api):
    """PRD §2.5: "A site in `STOP_WORK` posture is barred from four operations:
    commissioning a collector, returning a collector to service, starting a
    hot-work permit, and starting execution on a retrofit project. In all four
    cases the rejection carries `ERR_POSTURE_STOP_WORK` (HTTP 409)."
    PRD §2.5: "Posture checks run before any business-rule evaluation for the
    endpoint."

    Design: Difficulty/priority_pair_validation_conflict/posture_stop_work_state_vs_business_safety_vent_undersized
    """
    site, _insp, _findings = setup_site_in_stop_work()
    sample = create_dust_sample(site["id"], kst_bar_m_per_s=200, pmax_bar_g=9)
    # installed vent area 1 m² is far below the requirement -> vent_adequate false
    collector = create_collector(site["id"], sample["id"],
                                 internal_volume_m3=10, installed_vent_area_m2=1)
    assert collector["vent_adequate"] is False

    res = api.commission_collector(site["id"], collector["id"], ENGINEER)
    validate_error(res, ApiErrorId.ERR_POSTURE_STOP_WORK)
    assert res.status_code == 409


def test_commission_in_stop_work_leaves_collector_draft(api):
    """PRD §2.5: "Posture checks run before any business-rule evaluation for the
    endpoint."
    PRD §3.3: "Commissioning it — a `ComplianceEngineer` action — moves it to
    `IN_SERVICE`."

    The blocked commission must not transition the collector and must not
    surface the lower-priority vent-adequacy error.

    Design: Difficulty/priority_pair_validation_conflict/posture_stop_work_state_vs_business_safety_vent_undersized
    """
    site, _insp, _findings = setup_site_in_stop_work()
    sample = create_dust_sample(site["id"], kst_bar_m_per_s=200, pmax_bar_g=9)
    collector = create_collector(site["id"], sample["id"],
                                 internal_volume_m3=10, installed_vent_area_m2=1)

    res = api.commission_collector(site["id"], collector["id"], ENGINEER)
    body = res.json()
    assert body["data"]["error_id"] == "ERR_POSTURE_STOP_WORK"
    assert body["data"]["error_id"] != "ERR_VENT_UNDERSIZED"

    after = validate_success(api.get_collector(site["id"], collector["id"],
                                               ENGINEER), 200)
    assert after["status"] == "DRAFT"

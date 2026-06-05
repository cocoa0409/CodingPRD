"""Computed reads, list filtering, RBAC denials, OCC, scheduled actions, and
immediate consistency.

Queue B — corner sections: endpoints, rbac, cross_cutting, consistency_model.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated,
    setup_workers, open_case_with_child, create_licensed_home, place_child,
    setup_placed_child, set_clock, make_admin_headers,
)


# =========================================================================
# endpoints
# =========================================================================
def test_clearances_complete_true_after_only_screening_cleared(api):
    """PRD §3.4: "The home's `clearances_complete` is true only when every one of its `CaregiverScreening` rows is `CLEARED`; while any screening remains `PENDING` or `FLAGGED`, it is false."

    Design: Corner/endpoints/foster_home_clearances_complete_computed_true_after_resolve
    """
    w = setup_workers()
    home = get_success_data(api.create_foster_home(
        {"licensing_worker_id": w.licensing_id, "home_name": "Home CC",
         "bed_capacity": 1, "max_age_years": 18, "accepts_maltreatment": ["NEGLECT"]}, w.licensing))
    scr = get_success_data(api.create_screening(
        {"foster_home_id": home["id"], "member_name": "Clean Member"}, w.licensing))
    get_success_data(api.resolve_screening(scr["id"], w.licensing))
    fetched = validate_success(api.get_foster_home(home["id"], w.licensing))
    assert fetched["clearances_complete"] is True
    assert fetched["active_placement_count"] == 0


def test_list_placements_filtered_by_foster_home_id(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`, `total_count` (the number of records matching the filter before pagination), and `has_more` (true when records remain beyond the returned page)."

    Design: Corner/endpoints/list_placements_filtered_by_foster_home_id
    """
    w = setup_workers()
    set_clock("2026-01-01T00:00:00Z")
    case, child, home, placement = setup_placed_child(w, bed_capacity=2)
    resp = api.list_placements(w.caseworker, params={"foster_home_id": home["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["foster_home_id"] == home["id"]
    assert meta["has_more"] is False
    assert meta["total_count"] == 1


# =========================================================================
# rbac
# =========================================================================
def test_caseworker_cannot_screen_referral(api):
    """PRD §4: the screen endpoint is authorized for IntakeScreener only.
    PRD §2.1: "If the headers are well-formed but the named role is not permitted to invoke the requested operation (per the authorization matrix in Section 4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/caseworker_cannot_screen_referral
    """
    w = setup_workers(need_licensing=False)
    set_clock("2026-01-01T00:00:00Z")
    ref = get_success_data(api.create_referral(
        {"reporter_type": "MANDATED", "child_name": "Child RB",
         "alleged_maltreatment": "PHYSICAL_ABUSE",
         "priority_factors": ["INJURY_VISIBLE", "PRIOR_REPORT"]}, w.screener))
    resp = api.screen_referral(ref["id"], w.caseworker)
    validate_error(resp, "ERR_UNAUTHORIZED")


def test_licensing_worker_cannot_create_placement(api):
    """PRD §4: POST /placements is authorized for Caseworker only.
    PRD §2.1: "the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/licensing_worker_cannot_create_placement
    """
    w = setup_workers()
    set_clock("2026-01-01T00:00:00Z")
    case, child = open_case_with_child(w)
    home = create_licensed_home(w, bed_capacity=1, max_age_years=18)
    resp = api.create_placement(
        {"child_id": child["id"], "foster_home_id": home["id"],
         "expected_foster_home_version": home["version"]}, w.licensing)
    validate_error(resp, "ERR_UNAUTHORIZED")


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request to the API must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api.create_referral(
        {"reporter_type": "MANDATED", "child_name": "Child NH",
         "alleged_maltreatment": "NEGLECT"}, {"Content-Type": "application/json"})
    validate_error(resp, "ERR_UNAUTHENTICATED")


# =========================================================================
# cross_cutting
# =========================================================================
def test_occ_stale_version_on_full_license(api):
    """PRD §2.8: "If another writer has added or cleared a `CaregiverScreening` since the client last read the home (which bumps the home's `version`), the licensing decision would rest on a stale clearance picture, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    Client holds the create-time version; a provisional license bumped it since.

    Design: Corner/cross_cutting/occ_stale_version_on_full_license
    """
    w = setup_workers()
    home = get_success_data(api.create_foster_home(
        {"licensing_worker_id": w.licensing_id, "home_name": "Home OL",
         "bed_capacity": 1, "max_age_years": 18, "accepts_maltreatment": ["NEGLECT"]}, w.licensing))
    stale_version = home["version"]
    scr = get_success_data(api.create_screening(
        {"foster_home_id": home["id"], "member_name": "Clean Member OL"}, w.licensing))
    # Provisional license issued (bumps home version), then the screening cleared.
    get_success_data(api.license_provisional(home["id"], w.licensing))
    get_success_data(api.resolve_screening(scr["id"], w.licensing))
    resp = api.license_home(home["id"], {"expected_foster_home_version": stale_version}, w.licensing)
    validate_error(resp, "ERR_STALE_VERSION")


def test_occ_stale_version_on_placement(api):
    """PRD §2.8: "If another writer has already consumed the home's last open bed (a prior placement that legitimately advanced the home's `version` and filled capacity), the requesting client's view of the home's remaining beds is stale, and the create is rejected with `ERR_STALE_VERSION` (HTTP 412)".
    A cap-2 home; first placement bumped the version; the client reuses the pre-bump value.

    Design: Corner/cross_cutting/occ_stale_version_on_placement
    """
    w = setup_workers()
    set_clock("2026-01-01T00:00:00Z")
    case, child1, home, placement = setup_placed_child(w, bed_capacity=2)
    stale_version = home["version"]  # the value used to create the FIRST placement
    child2 = get_success_data(api.create_child(
        {"case_id": case["id"], "full_name": "Child OC2",
         "date_of_birth": "2016-01-01T00:00:00Z"}, w.caseworker))
    resp = api.create_placement(
        {"child_id": child2["id"], "foster_home_id": home["id"],
         "expected_foster_home_version": stale_version}, w.caseworker)
    validate_error(resp, "ERR_STALE_VERSION")


def test_expire_check_disrupts_active_placement(api):
    """PRD §3.7: "When a home's license **lapses** — a system sweep finds the current clock has passed the home's `license_expires_at` while the home is `LICENSED` or `PROVISIONAL` — the home moves to the terminal `EXPIRED` state and the identical placement-disruption cascade fires (every active placement disrupted, every child removed, the count zeroed, the `version` bumped)."
    Licensed at 2026-01-01 (full term 365 days -> expires 2027-01-01); clock 2027-02-01.

    Design: Corner/cross_cutting/expire_check_disrupts_active_placement
    """
    w = setup_workers()
    set_clock("2026-01-01T00:00:00Z")
    case, child, home, placement = setup_placed_child(w, bed_capacity=1)
    set_clock("2027-02-01T00:00:00Z")
    expired = validate_success(api.expire_check(home["id"], make_admin_headers()))
    assert expired["license_status"] == "EXPIRED"
    assert expired["active_placement_count"] == 0
    plc_after = validate_success(api.get_placement(placement["id"], w.caseworker))
    assert plc_after["status"] == "DISRUPTED"
    child_after = validate_success(api.get_child(child["id"], w.caseworker))
    assert child_after["status"] == "REMOVED"


# =========================================================================
# consistency_model
# =========================================================================
def test_first_placement_cascade_immediately_visible(api):
    """PRD §2.5: "these cascades are synchronous and complete within the single request that triggers them; a reader must never observe a half-applied cascade."
    PRD §3.5: "the case transitions from `OPEN` to `IN_PLACEMENT`, the case's `removal_date` is set to the current clock".
    After placement, an immediate GET /cases shows IN_PLACEMENT + removal_date + child PLACED.

    Design: Corner/consistency_model/placement_side_effects_visible_in_same_response_immediate
    """
    w = setup_workers()
    set_clock("2026-04-04T00:00:00Z")
    case, child = open_case_with_child(w)
    home = create_licensed_home(w, bed_capacity=1, max_age_years=18)
    place_child(w, child["id"], home["id"], home["version"])

    case_after = validate_success(api.get_case(case["id"], w.caseworker))
    assert case_after["status"] == "IN_PLACEMENT"
    assert case_after["removal_date"] == "2026-04-04T00:00:00.000Z"
    child_after = validate_success(api.get_child(child["id"], w.caseworker))
    assert child_after["status"] == "PLACED"

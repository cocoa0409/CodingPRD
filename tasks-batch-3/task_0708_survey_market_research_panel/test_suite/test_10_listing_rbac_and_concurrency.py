"""Filtered listing, RBAC, optimistic concurrency, rate thresholds, consistency.

Corner queue (B): sections endpoints, errors, rbac, cross_cutting_complexity_layers,
consistency_model.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, build_user_headers, TEST_USERS,
    create_study, create_quota_cell, create_panelist, create_consent,
    create_fielding_study_with_cell, setup_panelist_with_consent,
    create_screening_participation, setup_qualified_participation,
    create_facility, create_focus_group_payload, create_focus_group_booking_payload,
    setup_panelist_health_window, submit_payload, get_panelist_version,
    make_panelist_headers,
)

RM = TEST_USERS["research_manager_headers"]
OPS = TEST_USERS["panel_ops_headers"]
FC = TEST_USERS["field_coordinator_headers"]


# ----------------------- endpoints / listing -----------------------
def test_list_participations_filtered_by_panelist(api):
    """PRD §4 (endpoint table): "GET /participations | List participations
    (filterable)". The participations list is filterable by panelist_id.
    PRD §2.2: "The response_type is ... 'array' for a list of resources."

    Design: Corner/endpoints/list_participations_filtered_by_panelist
    """
    study, cell = create_fielding_study_with_cell(target_n=2, segment_key="SEG_RR")
    panelist = create_panelist(segment_key="SEG_RR")
    part = create_screening_participation(study["id"], panelist["id"], cell["id"])

    data, meta = validate_paginated(
        api.list_participations(FC, params={"panelist_id": panelist["id"]}))
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert data[0]["id"] == part["id"]
    assert data[0]["panelist_id"] == panelist["id"]


def test_list_attention_checks_for_participation(api):
    """PRD §3.3: "a FieldCoordinator records an AttentionCheck naming the
    check_kind ... and whether the panelist passed".
    PRD §4 (endpoint table): "GET /participations/{id}/attention-checks | List a
    participation's attention checks".

    Design: Corner/endpoints/list_attention_checks_for_participation
    """
    study, cell = create_fielding_study_with_cell(target_n=2, segment_key="SEG_AC")
    panelist = create_panelist(segment_key="SEG_AC")
    part = create_screening_participation(study["id"], panelist["id"], cell["id"])
    get_success_data(api.create_attention_check(
        part["id"], {"check_kind": "TIMING", "passed": True}, FC))

    data, meta = validate_paginated(api.list_attention_checks(part["id"], FC))
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert data[0]["participation_id"] == part["id"]
    assert data[0]["check_kind"] == "TIMING"


def test_panelist_health_read_returns_both_variants(api):
    """PRD §3.6: "A read of a panelist's health returns this rolling figure as
    health_score and also returns a lifetime_health_score computed identically but
    over all of the panelist's participations ... plus the panelist's status."
    PRD §3.6: "the base score is the fraction of windowed participations whose
    completion_status is COMPLETED, times 100 — or 100 if the window is empty."

    Design: Corner/endpoints/panelist_health_read_returns_both_variants
    """
    panelist = create_panelist(segment_key="SEG_HR")
    health = validate_success(api.get_panelist_health(panelist["id"], OPS))
    assert health["health_score"] == 100, \
        f"empty window -> base 100, got {health['health_score']}"
    assert health["lifetime_health_score"] == 100, \
        f"no participations -> lifetime 100, got {health['lifetime_health_score']}"
    assert health["status"] == "ACTIVE"


# ----------------------- errors -----------------------
def test_payout_request_nonexistent_panelist_returns_not_found(api):
    """PRD §2.5: "Foreign-key references inside request bodies (a study_id, a
    panelist_id ...) are subject to the same existence check." "If any referenced
    id ... does not resolve to an existing entity, the request is rejected with
    ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/errors/payout_request_nonexistent_panelist_returns_not_found
    """
    real = create_panelist(segment_key="SEG_NF")
    v0 = get_panelist_version(real["id"])
    validate_error(api.create_payout_request(
        {"panelist_id": NON_EXISTENT_UUID, "payout_method": "CASH", "points_requested": 100,
         "expected_panelist_version": v0}, OPS), ApiErrorId.ERR_NOT_FOUND.value)


# ----------------------- rbac -----------------------
def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers identifying the caller:
    X-User-ID and X-User-Role. If either header is missing, or if X-User-Role is
    not one of the four known roles, the request is rejected with
    ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    validate_error(api.list_studies({"Content-Type": "application/json"}),
                   ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_panelist_cannot_create_study_returns_forbidden(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not
    permitted to perform the requested operation (per the role authorizations
    summarized in §4), the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."
    PRD §4 (endpoint table): "POST /studies | Create a study (DRAFT) |
    ResearchManager".

    Design: Corner/rbac/panelist_cannot_create_study_returns_forbidden
    """
    panelist = create_panelist(segment_key="SEG_FR")
    validate_error(api.create_study(
        {"title": "Nope", "irb_protocol_number": "IRB-FR", "estimated_minutes": 10,
         "base_incentive_points": 50, "screener_min_age": 0},
        make_panelist_headers(panelist["id"])), ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_field_coordinator_cannot_approve_payout_forbidden(api):
    """PRD §2.1: "the named role is not permitted to perform the requested
    operation ... is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."
    PRD §4 (endpoint table): "POST /payout-requests/{id}/approve | Approve
    (REQUESTED -> APPROVED) | PanelOps".

    Design: Corner/rbac/field_coordinator_cannot_approve_payout_forbidden
    """
    panelist = create_panelist(segment_key="SEG_FC")
    v0 = get_panelist_version(panelist["id"])
    req = validate_success(api.create_payout_request(
        {"panelist_id": panelist["id"], "payout_method": "CASH", "points_requested": 100,
         "expected_panelist_version": v0}, OPS), expected_status=201)

    validate_error(api.approve_payout_request(req["id"], FC), ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_panelist_cannot_start_other_participation_not_owner(api):
    """PRD §2.1: "A Panelist may only start, submit, or abandon a participation
    whose panelist_id equals X-User-ID ... When a panelist attempts to act on a
    resource owned by someone else, the request is rejected with
    ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Design: Corner/rbac/panelist_cannot_start_other_participation_not_owner
    """
    study, cell = create_fielding_study_with_cell(target_n=2, segment_key="SEG_OW")
    pA = setup_panelist_with_consent(study["id"], panelist_overrides={"email": "owa@x.com"},
                                     segment_key="SEG_OW")
    pB = create_panelist(email="owb@x.com", segment_key="SEG_OW")
    part = create_screening_participation(study["id"], pA["id"], cell["id"])
    get_success_data(api.screen_participation(part["id"], "IN", FC))

    # Panelist B (non-owner) attempts to start A's participation.
    validate_error(api.start_participation(part["id"], make_panelist_headers(pB["id"])),
                   ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# ----------------------- cross-cutting: OCC -----------------------
def test_payout_correct_version_succeeds(api):
    """PRD §2.10: "When creating a payout request, the request body must include
    expected_panelist_version carrying the version of the target Panelist that the
    client last observed." "If expected_panelist_version does not equal the
    panelist's current version, the create is rejected" — so a matching version is
    accepted.

    Design: Corner/cross_cutting_complexity_layers/payout_correct_version_succeeds_and_bumps_version
    """
    study, cell, panelist, participation = setup_qualified_participation(
        target_n=2, study_overrides={"base_incentive_points": 100, "estimated_minutes": 10},
        segment_key="SEG_OCC1")
    pid = panelist["id"]
    ph = make_panelist_headers(pid)
    v_fresh = get_panelist_version(pid)
    req = validate_success(api.create_payout_request(
        {"panelist_id": pid, "payout_method": "GIFT_CARD", "points_requested": 100,
         "expected_panelist_version": v_fresh}, ph), expected_status=201)
    assert req["status"] == "REQUESTED"


def test_payout_stale_version_rejected(api):
    """PRD §2.10: "If expected_panelist_version does not equal the panelist's
    current version, the create is rejected with ERR_STALE_PANELIST_VERSION
    (HTTP 412), so the client cannot redeem points the panelist no longer has."

    Design: Corner/cross_cutting_complexity_layers/payout_stale_version_rejected_returns_stale_panelist_version
    """
    study, cell, panelist, participation = setup_qualified_participation(
        target_n=2, study_overrides={"base_incentive_points": 100, "estimated_minutes": 10},
        segment_key="SEG_OCC2")
    pid = panelist["id"]
    ph = make_panelist_headers(pid)
    v_fresh = get_panelist_version(pid)
    validate_error(api.create_payout_request(
        {"panelist_id": pid, "payout_method": "CASH", "points_requested": 100,
         "expected_panelist_version": v_fresh - 1}, ph),
        ApiErrorId.ERR_STALE_PANELIST_VERSION.value)


def test_booking_stale_focus_group_version_rejected(api):
    """PRD §2.10: "If expected_focus_group_version does not equal the focus group's
    current version, the booking create is rejected with
    ERR_STALE_FOCUS_GROUP_VERSION (HTTP 412), so the session is not oversold."

    Design: Corner/cross_cutting_complexity_layers/booking_stale_focus_group_version_rejected
    """
    study = create_study(base_incentive_points=50, estimated_minutes=10, screener_min_age=0)
    facility = create_facility(capacity=10)
    fg = get_success_data(api.create_focus_group(
        create_focus_group_payload(study["id"], facility["id"],
                                   starts_at="2026-05-04T10:00:00Z",
                                   ends_at="2026-05-04T11:00:00Z", seats=5), FC))
    pA = create_panelist(email="occ3a@x.com", segment_key="SEG_OCC3")
    pB = create_panelist(email="occ3b@x.com", segment_key="SEG_OCC3")
    # First booking bumps the session version.
    get_success_data(api.create_focus_group_booking(
        create_focus_group_booking_payload(fg["id"], pA["id"], fg["version"]), FC))
    fg_fresh = validate_success(api.get_focus_group(fg["id"], FC))

    validate_error(api.create_focus_group_booking(
        create_focus_group_booking_payload(fg["id"], pB["id"], fg_fresh["version"] - 1), FC),
        ApiErrorId.ERR_STALE_FOCUS_GROUP_VERSION.value)


def test_mark_churned_requires_health_below_floor(api):
    """PRD §3.6: "An AT_RISK panelist may be explicitly marked churned by a
    PanelOps operator, moving AT_RISK -> CHURNED, but only when health_score is
    below the churn floor of 30".
    PRD §2.6: a transition whose precondition/source state is not met is rejected
    with ERR_INVALID_STATE (HTTP 409).

    Design: Corner/cross_cutting_complexity_layers/mark_churned_requires_health_below_floor
    """
    # 2 completed + 3 incomplete -> rolling health 40: AT_RISK but above the floor 30.
    study, cell, panelist = setup_panelist_health_window(
        completed_recent=2, extra_incomplete=3, target_n=10, segment_key="SEG_CHN")
    data = validate_success(api.get_panelist(panelist["id"], OPS))
    assert data["health_score"] == 40 and data["status"] == "AT_RISK"

    validate_error(api.mark_churned_panelist(panelist["id"], OPS),
                   ApiErrorId.ERR_INVALID_STATE.value)


# ----------------------- consistency model -----------------------
def test_screen_in_provisional_visible_immediately(api):
    """PRD §3.2: "When a participation screens in, the system computes its
    provisional_points and writes a provisional incentive accrual in HELD status".
    PRD §3.5: "a 5-minute study earns one step (10 bonus points), an 11-minute
    study earns three steps (30 bonus points ...)".

    With base 100 and estimated_minutes 10, provisional = 100 + ceil(10/5)*10 = 120,
    returned in the same screen response (immediate consistency).

    Design: Corner/consistency_model/screen_in_provisional_visible_immediately
    """
    study, cell = create_fielding_study_with_cell(
        target_n=2, study_overrides={"base_incentive_points": 100, "estimated_minutes": 10},
        segment_key="SEG_IMM")
    panelist = setup_panelist_with_consent(study["id"], segment_key="SEG_IMM")
    part = create_screening_participation(study["id"], panelist["id"], cell["id"])

    screened = validate_success(api.screen_participation(part["id"], "IN", FC))
    assert screened["screening_status"] == "SCREENED_IN"
    assert screened["provisional_points"] == 120, \
        f"provisional_points 120 must be visible in the same response, got {screened['provisional_points']}"

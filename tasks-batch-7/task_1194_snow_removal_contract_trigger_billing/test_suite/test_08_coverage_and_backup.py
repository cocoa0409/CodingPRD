"""Subcontractor coverage: activation gate, capability, overlap, fail cascade, backup."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    create_coverage_payload, create_subcontractor_payload,
    setup_client, setup_site, setup_contract, link_site, activate_contract,
    setup_active_per_push, setup_storm_event, schedule_visit, set_clock,
    setup_subcontractor, setup_coverage, setup_closed_event_coverage,
    verify_event_with_two_sources, make_subcontractor_headers,
)

DISPATCH = TEST_USERS["ops_dispatcher_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency /
#             coverage_activation_gated_on_subcontractor_approved
# ---------------------------------------------------------------------------

def _setup_pending_sub_coverage(api):
    """PENDING subcontractor with a CREATED coverage row on a REPORTED event."""
    ctx = setup_active_per_push(client_name="Approval Testers",
                                per_push_rate_cents=40_000,
                                require_photo_verification=False)
    sub = setup_subcontractor(legal_name="PendingPlow Co",
                              contact_email="ops@pendingplow.example",
                              approve=False)
    set_clock("2026-12-10T00:30:00Z")
    event = setup_storm_event()
    coverage = setup_coverage(event["id"], ctx["contract"]["id"], sub["id"],
                              activate=False)
    return ctx, sub, event, coverage


def test_coverage_activation_gated_while_subcontractor_pending(api):
    """PRD §3.4: "the subcontractor itself moves `CREATED` to `ACTIVE`, which requires its `X-User-ID` to equal the assignment's `subcontractor_id` (failing as `ERR_FORBIDDEN_OWNERSHIP`), its own status to be `APPROVED`, and the overlap check above to pass."
    PRD §3.4: "Suspension leaves already-`ACTIVE` coverage assignments untouched but blocks any new activation with `ERR_SUBCONTRACTOR_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/coverage_activation_gated_on_subcontractor_approved
    """
    _, sub, _, coverage = _setup_pending_sub_coverage(api)
    assert coverage["status"] == "CREATED", (
        "coverage creation itself succeeds while the sub is PENDING")

    validate_error(
        api.activate_coverage_assignment(
            coverage["id"], make_subcontractor_headers(sub["id"])),
        ApiErrorId.ERR_SUBCONTRACTOR_NOT_APPROVED)


def test_coverage_activation_succeeds_after_approval(api):
    """PRD §3.4: "A `PlatformAdmin` approves `PENDING` to `APPROVED`"
    PRD §3.4: "Activation adds one to `active_assignment_count`."

    Design: Difficulty/cross_entity_state_dependency/coverage_activation_gated_on_subcontractor_approved
    """
    _, sub, _, coverage = _setup_pending_sub_coverage(api)
    get_success_data(api.approve_subcontractor(sub["id"], ADMIN))

    activated = validate_success(
        api.activate_coverage_assignment(
            coverage["id"], make_subcontractor_headers(sub["id"])), 200)
    assert activated["status"] == "ACTIVE"

    sub_after = validate_success(api.get_subcontractor(sub["id"], DISPATCH), 200)
    assert sub_after["active_assignment_count"] == 1


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict /
#             coverage_capability_vs_temporal_overlap_priority
# ---------------------------------------------------------------------------

def _setup_capability_overlap_scenario(api):
    """subC APPROVED without a loader; kN covers a non-loader site with caC
    ACTIVE [06:00,14:00); kL covers a loader-requiring site."""
    ctx = setup_active_per_push(client_name="Dual Site Group",
                                per_push_rate_cents=40_000,
                                site_name="North Pad",
                                requires_loader=False)
    site_l = setup_site(ctx["client"]["id"], name="South Ramp",
                        address="2 South Rd", requires_loader=True)
    contract_l = setup_contract(ctx["client"]["id"], contract_type="PER_PUSH",
                                per_push_rate_cents=52_000,
                                require_photo_verification=False)
    link_site(contract_l["id"], site_l["id"])
    activate_contract(contract_l["id"])
    sub = setup_subcontractor(legal_name="NoLoader Inc",
                              contact_email="ops@noloader.example",
                              has_loader=False, has_brine_truck=True)
    set_clock("2027-01-10T00:30:00Z")
    # PRD §3.4: a coverage window "must overlap the event's window" — the event
    # window spans the full day so the tested windows [10:00,18:00) and
    # [14:00,18:00) overlap it and only the capability/overlap rules are in play.
    event = setup_storm_event(window_start="2027-01-10T00:00:00Z",
                              window_end="2027-01-10T23:00:00Z",
                              reported_accumulation_inches=3.0)
    coverage = setup_coverage(event["id"], ctx["contract"]["id"], sub["id"],
                              coverage_start="2027-01-10T06:00:00Z",
                              coverage_end="2027-01-10T14:00:00Z", activate=True)
    return {"event": event, "sub": sub, "contract_l": contract_l,
            "coverage": coverage}


def test_capability_mismatch_wins_over_overlap_on_dual_failure(api):
    """PRD §2.8: "Every request is checked against the following tiers in the order listed, and when several checks would fail at once, the earliest tier in this order produces the returned error."
    PRD §2.8: "Eleventh, subcontractor capability must cover the equipment the work requires, failing as `ERR_CAPABILITY_MISMATCH`."
    PRD §2.8: "Fifteenth through nineteenth are the temporal rules in order: season-window overlap per site (`ERR_SEASON_WINDOW_OVERLAP`), coverage-window overlap per subcontractor (`ERR_COVERAGE_OVERLAP`)"
    PRD §3.4: "The subcontractor's capabilities must cover every loader-requiring site of the contract, failing as `ERR_CAPABILITY_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/coverage_capability_vs_temporal_overlap_priority
    """
    sc = _setup_capability_overlap_scenario(api)
    # Dual failure: kL has a loader-requiring site (capability fails) AND
    # [10:00,18:00) overlaps caC's [06:00,14:00) half-open window.
    validate_error(api.create_coverage_assignment(
        create_coverage_payload(sc["event"]["id"], sc["contract_l"]["id"],
                                sc["sub"]["id"],
                                "2027-01-10T10:00:00Z", "2027-01-10T18:00:00Z"),
        DISPATCH), ApiErrorId.ERR_CAPABILITY_MISMATCH)


def test_capability_mismatch_isolated_without_overlap(api):
    """PRD §3.4: "The subcontractor's capabilities must cover every loader-requiring site of the contract, failing as `ERR_CAPABILITY_MISMATCH`."
    PRD §3.4: "back-to-back adjacency, where one window ends exactly as another begins, is legal" — [14:00,18:00) is adjacent to caC's [06:00,14:00), so only the capability rule can fail.

    Design: Difficulty/priority_pair_validation_conflict/coverage_capability_vs_temporal_overlap_priority
    """
    sc = _setup_capability_overlap_scenario(api)
    validate_error(api.create_coverage_assignment(
        create_coverage_payload(sc["event"]["id"], sc["contract_l"]["id"],
                                sc["sub"]["id"],
                                "2027-01-10T14:00:00Z", "2027-01-10T18:00:00Z"),
        DISPATCH), ApiErrorId.ERR_CAPABILITY_MISMATCH)


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / coverage_overlap_half_open_adjacency
# ---------------------------------------------------------------------------

def _half_open_ctx(api):
    """Three ACTIVE contracts (one site each); subH APPROVED with caH1 ACTIVE
    covering [06:00,14:00) on the shared event."""
    client = setup_client(name="Overlap Holdings")
    sites = [setup_site(client["id"], name=f"Pad {i}", address=f"{i} Pad Row",
                        pavement_area_sqft=8_000)
             for i in (1, 2, 3)]
    contracts = []
    for site in sites:
        contract = setup_contract(client["id"], contract_type="PER_PUSH",
                                  per_push_rate_cents=40_000,
                                  require_photo_verification=False)
        link_site(contract["id"], site["id"])
        contracts.append(activate_contract(contract["id"]))
    sub = setup_subcontractor(legal_name="Shiftwork Snow",
                              contact_email="ops@shiftwork.example",
                              has_loader=True)
    set_clock("2027-01-09T12:00:00Z")
    event = setup_storm_event(window_start="2027-01-10T00:00:00Z",
                              window_end="2027-01-10T23:00:00Z",
                              reported_accumulation_inches=4.0)
    coverage = setup_coverage(event["id"], contracts[0]["id"], sub["id"],
                              coverage_start="2027-01-10T06:00:00Z",
                              coverage_end="2027-01-10T14:00:00Z", activate=True)
    return {"contracts": contracts, "sub": sub, "event": event,
            "coverage": coverage}


def test_coverage_half_open_adjacency_is_legal(api):
    """PRD §3.4: "And no two `CREATED` or `ACTIVE` assignments of the same subcontractor may overlap in time under half-open semantics — back-to-back adjacency, where one window ends exactly as another begins, is legal — failing as `ERR_COVERAGE_OVERLAP`"

    Design: Difficulty/resource_temporal_overlap/coverage_overlap_half_open_adjacency
    """
    sc = _half_open_ctx(api)
    adjacent = validate_success(api.create_coverage_assignment(
        create_coverage_payload(sc["event"]["id"], sc["contracts"][1]["id"],
                                sc["sub"]["id"],
                                "2027-01-10T14:00:00Z", "2027-01-10T20:00:00Z"),
        DISPATCH), 201)
    assert adjacent["status"] == "CREATED", (
        "starting at 14:00 exactly when caH1 ends is legal adjacency")


def test_coverage_one_minute_overlap_rejected(api):
    """PRD §3.4: "no two `CREATED` or `ACTIVE` assignments of the same subcontractor may overlap in time under half-open semantics — back-to-back adjacency, where one window ends exactly as another begins, is legal — failing as `ERR_COVERAGE_OVERLAP`; this overlap check runs both at creation and again at activation."

    Design: Difficulty/resource_temporal_overlap/coverage_overlap_half_open_adjacency
    """
    sc = _half_open_ctx(api)
    validate_error(api.create_coverage_assignment(
        create_coverage_payload(sc["event"]["id"], sc["contracts"][2]["id"],
                                sc["sub"]["id"],
                                "2027-01-10T13:59:00Z", "2027-01-10T20:00:00Z"),
        DISPATCH), ApiErrorId.ERR_COVERAGE_OVERLAP)


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / equipment_failure_cascade_to_auto_suspension
# ---------------------------------------------------------------------------

def _setup_fail_cascade_scenario(api):
    """sub1 APPROVED with two prior RELEASED coverages; event e9 with ACTIVE
    coverage ca9 by sub1 and one SCHEDULED visit assigned to sub1."""
    ctx = setup_active_per_push(client_name="MedCenter Props",
                                per_push_rate_cents=45_000,
                                require_photo_verification=False,
                                pavement_area_sqft=25_000)
    sub = setup_subcontractor(legal_name="PlowRight LLC",
                              contact_email="dispatch@plowright.example",
                              has_loader=True, has_brine_truck=True)
    setup_closed_event_coverage(ctx, sub["id"], "2026-12-01")
    setup_closed_event_coverage(ctx, sub["id"], "2026-12-02")

    set_clock("2026-12-10T00:30:00Z")
    event = setup_storm_event(reported_accumulation_inches=2.5)
    coverage = setup_coverage(event["id"], ctx["contract"]["id"], sub["id"],
                              activate=True)
    visit = schedule_visit(event["id"], ctx["contract_site"]["id"],
                           scheduled_start="2026-12-10T09:00:00Z",
                           scheduled_end="2026-12-10T10:00:00Z",
                           assigned_subcontractor_id=sub["id"])
    return ctx, sub, event, coverage, visit


def test_coverage_failure_cascades_visits_to_awaiting_backup(api):
    """PRD §3.4: "First, every `SCHEDULED` visit assigned to this subcontractor under this event drops its `assigned_subcontractor_id` to null and moves to `AWAITING_BACKUP`, awaiting the reassign flow of §3.5."
    PRD §3.4: "An equipment failure — reported by the subcontractor itself or by an `OpsDispatcher`, recording a `failure_reason` — moves an `ACTIVE` assignment to `FAILED`"

    Design: Difficulty/transitive_cascade/equipment_failure_cascade_to_auto_suspension
    """
    _, sub, _, coverage, visit = _setup_fail_cascade_scenario(api)
    failed = validate_success(api.fail_coverage_assignment(
        coverage["id"], {"failure_reason": "Plow hydraulics failure"},
        make_subcontractor_headers(sub["id"])), 200)
    assert failed["status"] == "FAILED"

    visit_after = validate_success(api.get_visit(visit["id"], DISPATCH), 200)
    assert visit_after["execution_status"] == "AWAITING_BACKUP"
    assert visit_after.get("assigned_subcontractor_id") is None


def test_coverage_failure_recomputes_reliability_and_auto_suspends(api):
    """PRD §3.4: "Second, `active_assignment_count` drops by one, `assignments_failed_count` rises by one, and `reliability_score` recomputes as one hundred times the released count divided by the sum of released and failed — with the denominator guarded so that zero counts as one — rounded down to a whole number between 0 and 100. Third, once the subcontractor's released plus failed assignments reach at least 3, a `reliability_score` below 70 automatically moves the subcontractor to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/equipment_failure_cascade_to_auto_suspension
    """
    _, sub, _, coverage, _ = _setup_fail_cascade_scenario(api)
    get_success_data(api.fail_coverage_assignment(
        coverage["id"], {"failure_reason": "Plow hydraulics failure"},
        make_subcontractor_headers(sub["id"])))

    sub_after = validate_success(api.get_subcontractor(sub["id"], DISPATCH), 200)
    assert sub_after["assignments_failed_count"] == 1
    assert sub_after["assignments_released_count"] == 2
    assert sub_after["reliability_score"] == 66, "floor(100 * 2 / 3)"
    assert sub_after["status"] == "SUSPENDED", (
        "66 < 70 with 3 total assignments -> automatic suspension")


# ---------------------------------------------------------------------------
# Corner: selector policy — backup ranking/tiebreak and empty pool
# ---------------------------------------------------------------------------

def _setup_backup_pool_scenario(api):
    """Primary subP with ACTIVE coverage + assigned visit; backups subB1
    (created 00:01) and subB2 (created 00:02); primary's coverage then fails."""
    ctx = setup_active_per_push(client_name="Backup Co", require_photo_verification=False)
    sub_p = setup_subcontractor(legal_name="Primary Plow",
                                contact_email="p@sub.example", approve=False)
    set_clock("2026-05-01T00:01:00Z")
    sub_b1 = setup_subcontractor(legal_name="Backup One",
                                 contact_email="b1@sub.example", approve=False)
    set_clock("2026-05-01T00:02:00Z")
    sub_b2 = setup_subcontractor(legal_name="Backup Two",
                                 contact_email="b2@sub.example", approve=False)
    for sub in (sub_p, sub_b1, sub_b2):
        get_success_data(api.approve_subcontractor(sub["id"], ADMIN))

    set_clock("2026-12-10T00:30:00Z")
    event = setup_storm_event()
    coverage = setup_coverage(event["id"], ctx["contract"]["id"], sub_p["id"],
                              activate=True)
    visit = schedule_visit(event["id"], ctx["contract_site"]["id"],
                           scheduled_start="2026-12-10T09:00:00Z",
                           scheduled_end="2026-12-10T10:00:00Z",
                           assigned_subcontractor_id=sub_p["id"])
    assert visit["sla_deadline_at"] == "2026-12-10T14:00:00.000Z"
    get_success_data(api.fail_coverage_assignment(
        coverage["id"], {"failure_reason": "Transmission failure"},
        make_subcontractor_headers(sub_p["id"])))
    return {"ctx": ctx, "event": event, "visit": visit, "sub_p": sub_p,
            "sub_b1": sub_b1, "sub_b2": sub_b2}


def test_backup_selector_ranking_tiebreak_and_grace_extension(api):
    """PRD §3.5: "The pool is ranked by fewest `CREATED`-or-`ACTIVE` assignments for this event, ties broken by earliest subcontractor `created_at`; the selector is deterministic and never ordered by id."
    PRD §3.5: "On success the visit's `assigned_subcontractor_id` becomes the backup, `grace_extended` flips to true, `sla_deadline_at` is extended by two hours, and a fresh CoverageAssignment for the event, contract, and backup is created directly in `ACTIVE` status spanning the event window."
    PRD §3.5: "that has no `FAILED` coverage for this storm event — a failed subcontractor is never retried on the same event."

    Design: Corner/cross_cutting_layers/backup_selector_ranking_tiebreak_and_grace_extension
    """
    sc = _setup_backup_pool_scenario(api)
    reassigned = validate_success(
        api.reassign_visit(sc["visit"]["id"], {}, DISPATCH), 200)
    assert reassigned["assigned_subcontractor_id"] == sc["sub_b1"]["id"], (
        "both backups tie at 0 active assignments for the event; the earlier "
        "created_at (00:01 vs 00:02) wins, and the failed primary is excluded")
    assert reassigned["execution_status"] == "SCHEDULED"
    assert reassigned["grace_extended"] is True
    assert reassigned["sla_deadline_at"] == "2026-12-10T16:00:00.000Z", (
        "14:00 deadline + 120-minute backup grace")

    rows, _ = validate_paginated(api.list_coverage_assignments(
        DISPATCH, params={"subcontractor_id": sc["sub_b1"]["id"],
                          "storm_event_id": sc["event"]["id"]}))
    assert len(rows) == 1
    assert rows[0]["status"] == "ACTIVE"


def test_backup_selector_empty_pool_returns_409(api):
    """PRD §3.5: "An empty pool fails the reassignment with `ERR_NO_BACKUP_AVAILABLE` and the visit stays `AWAITING_BACKUP`."
    PRD §3.5: "that has no `FAILED` coverage for this storm event — a failed subcontractor is never retried on the same event."

    Design: Corner/cross_cutting_layers/backup_selector_empty_pool_returns_409
    """
    ctx = setup_active_per_push(client_name="No Backup Co",
                                require_photo_verification=False)
    sub = setup_subcontractor(legal_name="Only Plow",
                              contact_email="only@sub.example")
    set_clock("2026-12-10T00:30:00Z")
    event = setup_storm_event()
    coverage = setup_coverage(event["id"], ctx["contract"]["id"], sub["id"],
                              activate=True)
    visit = schedule_visit(event["id"], ctx["contract_site"]["id"],
                           scheduled_start="2026-12-10T09:00:00Z",
                           scheduled_end="2026-12-10T10:00:00Z",
                           assigned_subcontractor_id=sub["id"])
    get_success_data(api.fail_coverage_assignment(
        coverage["id"], {"failure_reason": "Engine seized"},
        make_subcontractor_headers(sub["id"])))

    validate_error(api.reassign_visit(visit["id"], {}, DISPATCH),
                   ApiErrorId.ERR_NO_BACKUP_AVAILABLE)

    after = validate_success(api.get_visit(visit["id"], DISPATCH), 200)
    assert after["execution_status"] == "AWAITING_BACKUP"
    assert after.get("assigned_subcontractor_id") is None


# ---------------------------------------------------------------------------
# Corner: validations + RBAC + listing
# ---------------------------------------------------------------------------

def test_duplicate_coverage_triple_rejected(api):
    """PRD §3.4: "At most one non-terminal coverage may exist for the same subcontractor, event, and contract triple, failing as `ERR_DUPLICATE_COVERAGE`."

    Design: Corner/validations/duplicate_coverage_triple_rejected
    """
    ctx = setup_active_per_push(client_name="Dup Cov Co",
                                require_photo_verification=False)
    sub = setup_subcontractor(legal_name="Dup Sub", contact_email="d@sub.example")
    set_clock("2026-12-10T00:30:00Z")
    # PRD §3.4: a coverage window "must overlap the event's window" — span the
    # day so both [00:00,12:00) and the non-overlapping [12:00,18:00) qualify,
    # isolating the duplicate-triple rule.
    event = setup_storm_event(window_start="2026-12-10T00:00:00Z",
                              window_end="2026-12-10T23:00:00Z")
    setup_coverage(event["id"], ctx["contract"]["id"], sub["id"], activate=False)

    # Non-overlapping times do not rescue the duplicate (sub, event, contract).
    validate_error(api.create_coverage_assignment(
        create_coverage_payload(event["id"], ctx["contract"]["id"], sub["id"],
                                "2026-12-10T12:00:00Z", "2026-12-10T18:00:00Z"),
        DISPATCH), ApiErrorId.ERR_DUPLICATE_COVERAGE)


def test_subcontractor_cannot_activate_foreign_coverage(api):
    """PRD §3.4: "the subcontractor itself moves `CREATED` to `ACTIVE`, which requires its `X-User-ID` to equal the assignment's `subcontractor_id` (failing as `ERR_FORBIDDEN_OWNERSHIP`)"

    Design: Corner/roles/subcontractor_cannot_activate_foreign_coverage
    """
    ctx = setup_active_per_push(client_name="Own Co", require_photo_verification=False)
    sub1 = setup_subcontractor(legal_name="Sub One", contact_email="1@sub.example")
    sub2 = setup_subcontractor(legal_name="Sub Two", contact_email="2@sub.example")
    set_clock("2026-12-10T00:30:00Z")
    event = setup_storm_event()
    coverage = setup_coverage(event["id"], ctx["contract"]["id"], sub1["id"],
                              activate=False)

    validate_error(
        api.activate_coverage_assignment(
            coverage["id"], make_subcontractor_headers(sub2["id"])),
        ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)

    after = validate_success(api.get_coverage_assignment(coverage["id"], DISPATCH), 200)
    assert after["status"] == "CREATED"


def test_list_pagination_envelope_and_status_filter(api):
    """PRD §2.3: "Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.3: "The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100."

    Design: Corner/endpoints/list_pagination_envelope_and_status_filter
    """
    sub_a = setup_subcontractor(legal_name="Alpha Plow",
                                contact_email="a@sub.example", approve=False)
    sub_b = setup_subcontractor(legal_name="Beta Plow",
                                contact_email="b@sub.example", approve=False)
    sub_c = setup_subcontractor(legal_name="Gamma Plow",
                                contact_email="g@sub.example", approve=False)
    get_success_data(api.approve_subcontractor(sub_a["id"], ADMIN))
    get_success_data(api.approve_subcontractor(sub_b["id"], ADMIN))

    page1, meta1 = validate_paginated(
        api.list_subcontractors(DISPATCH, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_subcontractors(DISPATCH, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["has_more"] is False

    pending, meta3 = validate_paginated(
        api.list_subcontractors(DISPATCH, params={"status": "PENDING"}))
    assert meta3["total_count"] == 1
    assert pending[0]["id"] == sub_c["id"]

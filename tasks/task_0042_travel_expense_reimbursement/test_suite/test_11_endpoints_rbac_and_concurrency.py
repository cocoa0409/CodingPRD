"""Endpoint behaviors, RBAC, optimistic concurrency, and immediate consistency.

Queue B (Corner) — sections endpoints, rbac, cross_cutting_complexity_layers,
consistency_model.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId,
    setup_base_env,
    create_approved_trip,
    create_report,
    add_flight_line,
    add_flight_line_with_receipt,
    add_mileage_line,
    submit_report,
    issue_card,
    create_approver,
    create_traveler,
    create_active_policy,
    create_per_diem_rate,
    make_traveler_headers,
    make_approver_headers,
    make_finance_admin_headers,
    issue_virtual_card_payload,
)

ADMIN = make_finance_admin_headers()


# --------------------------------------------------------------------------
# section: endpoints
# --------------------------------------------------------------------------
def test_delete_line_releases_hold(api):
    """PRD §3.4: "A traveler may remove a line from a DRAFT report; deleting a line that
    holds a provisional reservation releases that hold back to its card."

    Design: Corner/endpoints/delete_line_releases_hold
    """
    env = setup_base_env()
    trip = create_approved_trip(env, budget_total_cents=100000)
    card = issue_card(env, trip, load_limit_cents=100000)
    report = create_report(env, trip, title="Del Rpt")
    line = add_flight_line(env, report, claimed_amount_cents=30000,
                           cabin_class="ECONOMY", scheduled_hours=4, advance_days=20,
                           virtual_card_id=card["id"])
    resp = api.delete_expense_line(line["id"], env["traveler_headers"])
    # PRD §4: "a successful line deletion returns 204 No Content." A 204 carries no
    # body, so assert the status code directly rather than parsing a JSON envelope.
    assert resp.status_code == 204, (
        f"line deletion must return 204 No Content, got {resp.status_code}: {resp.text}"
    )
    refreshed = get_success_data(api.get_virtual_card(card["id"], env["admin_headers"]))
    assert refreshed["authorized_holds_cents"] == 0, "hold released on delete"
    assert refreshed["available_balance_cents"] == 100000, "funds returned to availability"


def test_card_freeze_unfreeze_roundtrip(api):
    """PRD §3.3: "Freezing moves a card from ACTIVE to FROZEN; while frozen, any attempt
    to charge a new expense line to the card is refused with ERR_CARD_NOT_ACTIVE.
    Unfreezing returns it from FROZEN to ACTIVE."

    Design: Corner/endpoints/card_freeze_unfreeze_roundtrip
    """
    env = setup_base_env()
    trip = create_approved_trip(env, budget_total_cents=100000)
    card = issue_card(env, trip, load_limit_cents=100000)
    get_success_data(api.freeze_virtual_card(card["id"], env["admin_headers"]))
    data = validate_success(
        api.unfreeze_virtual_card(card["id"], env["admin_headers"]), expected_status=200
    )
    assert data["status"] == "ACTIVE"


def test_list_pagination_limit_below_min_rejected(api):
    """PRD §2.3: "The limit parameter caps the number of items returned; it defaults to
    10 when omitted, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "A limit or offset outside its permitted range is rejected with
    ERR_VALIDATION."

    Design: Corner/endpoints/list_pagination_limit_out_of_range
    """
    create_per_diem_rate(state_code="TX", lodging_cap_cents=15000, mie_cents=6000)
    resp = api.list_per_diem_rates(ADMIN, params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# --------------------------------------------------------------------------
# section: rbac
# --------------------------------------------------------------------------
def test_traveler_cannot_decide_report(api):
    """PRD §2.1: "A syntactically valid request whose role lacks permission for the
    targeted operation is rejected with ERR_UNAUTHORIZED."

    Design: Corner/rbac/traveler_cannot_decide_report
    """
    env = setup_base_env()
    trip = create_approved_trip(env, budget_total_cents=100000)
    report = create_report(env, trip, title="RBAC Rpt")
    add_mileage_line(env, report, miles=100)
    submit_report(env, report)
    resp = api.decide_expense_report(report["id"], {"decision": "APPROVE"}, env["traveler_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_wrong_manager_cannot_decide_report(api):
    """PRD §2.1: "an approver may act on a traveler's resources only when that approver
    is the traveler's recorded manager_id, and may decide an out-of-policy approval step
    only when that approver is the step's approver_id. An ownership failure on any of
    these checks is reported as ERR_NOT_OWNER."

    Design: Corner/rbac/wrong_manager_cannot_decide_report
    """
    mgr_a = create_approver(approval_limit_cents=500000)
    mgr_b = create_approver(approval_limit_cents=500000)
    traveler = create_traveler(manager_id=mgr_a["id"])
    create_active_policy()
    create_per_diem_rate(state_code="CA", lodging_cap_cents=20000, mie_cents=8000)
    trav_headers = make_traveler_headers(traveler["id"])
    trip = get_success_data(api.create_trip_request(
        {"traveler_id": traveler["id"], "destination_state": "CA",
         "start_date": "2026-06-01", "end_date": "2026-06-03", "budget_total_cents": 100000},
        trav_headers,
    ))
    get_success_data(api.submit_trip_request(trip["id"], trav_headers))
    report = get_success_data(api.create_expense_report(
        {"trip_request_id": trip["id"], "title": "Owner Rpt"}, trav_headers))
    get_success_data(api.create_expense_line(
        {"report_id": report["id"], "line_type": "MILEAGE", "claimed_amount_cents": 0, "miles": 100},
        trav_headers))
    get_success_data(api.submit_expense_report(report["id"], trav_headers))
    # mgr_b is NOT the traveler's manager_id -> ERR_NOT_OWNER.
    resp = api.decide_expense_report(
        report["id"], {"decision": "APPROVE"}, make_approver_headers(mgr_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value)


def test_traveler_cannot_create_trip_for_other_traveler(api):
    """PRD §2.1: "Concretely, a trip is owned by the traveler named in its traveler_id,
    and an expense report is owned by the traveler of the trip it reconciles."
    PRD §2.1: "An ownership failure on any of these checks is reported as ERR_NOT_OWNER."

    Design: Corner/rbac/traveler_cannot_create_for_other_traveler
    """
    approver = create_approver(approval_limit_cents=500000)
    trav_a = create_traveler(manager_id=approver["id"])
    trav_b = create_traveler(manager_id=approver["id"])
    create_active_policy()
    create_per_diem_rate(state_code="CA", lodging_cap_cents=20000, mie_cents=8000)
    # trav_a acting, but creating a trip for trav_b -> ownership failure.
    resp = api.create_trip_request(
        {"traveler_id": trav_b["id"], "destination_state": "CA",
         "start_date": "2026-06-01", "end_date": "2026-06-03", "budget_total_cents": 50000},
        make_traveler_headers(trav_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value)


def test_missing_headers_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or that carries an X-User-Role
    value outside this set, is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_headers_unauthenticated
    """
    resp = api.create_traveler(
        {"email": "x@x.com", "full_name": "X", "home_office_state": "CA",
         "manager_id": NON_EXISTENT_UUID},
        {},  # no X-User-ID / X-User-Role headers
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# --------------------------------------------------------------------------
# section: cross_cutting_complexity_layers (OCC on card issuance)
# --------------------------------------------------------------------------
def test_stale_trip_version_on_second_card_rejected(api):
    """PRD §2.7: "If expected_trip_request_version does not equal the trip's current
    version, the request is rejected with ERR_STALE_VERSION (HTTP 412)."
    PRD §3.3: "advances the funding trip's version by one — which is exactly why a
    second concurrent issuance carrying the now-stale version is rejected."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_trip_version_on_second_card
    """
    env = setup_base_env()
    trip = create_approved_trip(env, budget_total_cents=100000)
    stale_version = trip["version"]
    get_success_data(api.issue_virtual_card(
        trip["id"], issue_virtual_card_payload(stale_version, load_limit_cents=50000),
        env["admin_headers"]))
    # Reusing the pre-first-issuance version is now stale (first issuance bumped version).
    resp = api.issue_virtual_card(
        trip["id"], issue_virtual_card_payload(stale_version, load_limit_cents=50000),
        env["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_card_issue_increments_trip_version(api):
    """PRD §3.3: "advances the funding trip's version by one — which is exactly why a
    second concurrent issuance carrying the now-stale version is rejected."
    PRD §2.7: "The card-issuance request must carry expected_trip_request_version as a
    required field, holding the version of the target TripRequest that the client last
    observed."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_card_issue
    """
    env = setup_base_env()
    trip = create_approved_trip(env, budget_total_cents=100000)
    v_before = trip["version"]
    get_success_data(api.issue_virtual_card(
        trip["id"], issue_virtual_card_payload(v_before, load_limit_cents=50000),
        env["admin_headers"]))
    fresh = get_success_data(api.get_trip_request(trip["id"], env["admin_headers"]))
    assert fresh["version"] == v_before + 1, "issuance bumps trip version by exactly one"
    # The fresh version succeeds on a second issuance.
    card2 = validate_success(
        api.issue_virtual_card(
            trip["id"], issue_virtual_card_payload(fresh["version"], load_limit_cents=50000),
            env["admin_headers"]),
        expected_status=201,
    )
    assert card2["available_balance_cents"] == 50000


# --------------------------------------------------------------------------
# section: consistency_model
# --------------------------------------------------------------------------
def test_approve_cascade_visible_immediately(api):
    """PRD §2.8: "The system settles all consequences of an operation atomically within
    the request that triggers them — there is no deferred or eventual reconciliation."
    PRD §3.8: "finally the trip's committed_amount_cents is increased by the report's
    total_reimbursable_cents and its remaining_budget_cents is recomputed."

    Design: Corner/consistency_model/approve_cascade_visible_in_same_response
    """
    env = setup_base_env(max_economy_fare_cents=50000)
    trip = create_approved_trip(env, budget_total_cents=100000)
    # ITEMIZED with no meal line -> meal_reimbursable_cents = min(0, per-diem) = 0
    # (PRD §3.6), so total_reimbursable_cents is exactly the single flight line.
    report = create_report(env, trip, per_diem_method="ITEMIZED", title="Immediate Rpt")
    add_flight_line_with_receipt(env, report, claimed_amount_cents=30000,
                                 cabin_class="ECONOMY", scheduled_hours=4, advance_days=20)
    submit_report(env, report)
    decided = validate_success(
        api.decide_expense_report(report["id"], {"decision": "APPROVE"}, env["approver_headers"]),
        expected_status=200,
    )
    assert decided["status"] == "APPROVED"
    assert decided["total_reimbursable_cents"] == 30000
    # Trip ledger update readable immediately after the same operation.
    trip_after = get_success_data(api.get_trip_request(trip["id"], env["admin_headers"]))
    assert trip_after["committed_amount_cents"] == 30000

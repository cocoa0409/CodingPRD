"""Client standing (exit/suspend cascades) and the access-control envelope:
confidentiality wall, ownership scoping, identity mismatch, role gating."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    checkin_visit_with_line,
    create_active_client,
    create_agency,
    create_assessment_payload,
    create_bed,
    create_coordinator,
    create_draft_assessment,
    create_item,
    create_open_event,
    create_pantry_staff,
    create_referral_payload,
    create_reserved_stay,
    create_shelter_coordinator,
    create_staff_payload,
    get_success_data,
    register_client,
    register_client_for_event,
    setup_pantry_scenario,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    make_client_headers,
    make_intake_coordinator_headers,
    make_partner_agency_rep_headers,
)

ANON = TEST_USERS["anonymous_headers"]
ADMIN = TEST_USERS["hub_admin_headers"]


def test_exit_unwinds_stays_referrals_registrations_and_open_visit(api):
    """PRD §3.1: "Exiting, available to an `IntakeCoordinator` or `HubAdmin`
    from either `ACTIVE` or `SUSPENDED` (otherwise `ERR_CLIENT_NOT_ACTIVE`),
    moves the client to the terminal `EXITED` state and unwinds every open
    engagement in one atomic event: all future shelter stays still `RESERVED`
    are cancelled, freeing their bed intervals; all referrals in `INITIATED`
    or `SENT` are withdrawn, and withdrawing a `SENT` referral decrements the
    receiving agency's `active_referral_count`; every registration still
    `REGISTERED` for an event whose `event_date` lies in the future is
    cancelled, each cancellation recomputing its event's `registered_count`
    and possibly flipping the event from `FULL` back to `OPEN`; the client's
    checked-in pantry visit, if any, is voided; and any of the client's
    assessments still in `DRAFT` are moved to `DISCARDED`."

    Design: Corner/complexity_layers/exit_unwinds_stays_referrals_registrations_and_open_visit
    """
    _, coord = create_coordinator()
    _, pantry = create_pantry_staff()
    _, shelter = create_shelter_coordinator()
    client, a1, client_headers = create_active_client(
        coord,
        assessment_overrides=dict(
            household_size=1, monthly_income_cents=0, housing_status="HOMELESS",
            dependents_under_18=0, receives_snap=False,
            receives_childcare_subsidy=False, food_insecurity_score=6,
            consent_confidential=True,
        ),
        client_overrides={"alias_name": "ex"},
    )
    # A second assessment left in DRAFT.
    a2 = create_draft_assessment(
        client["id"], coord,
        household_size=1, monthly_income_cents=0, housing_status="HOMELESS",
        dependents_under_18=0, receives_snap=False, receives_childcare_subsidy=False,
        food_insecurity_score=6, consent_confidential=True,
    )

    bed = create_bed(shelter, site="Haven", label="E1")
    create_reserved_stay(client["id"], bed["id"], shelter,
                         check_in_date="2026-08-10", planned_nights=2)

    agency = create_agency("Exit Agency", service_categories=["HOUSING_PLACEMENT"],
                           weekly_capacity=5)
    referral = get_success_data(
        api.create_referral(
            client["id"],
            create_referral_payload(agency["id"], service_category="HOUSING_PLACEMENT"),
            coord,
        )
    )
    validate_success(api.send_referral(referral["id"], coord), 200)

    event = create_open_event("Tiny Event", event_date="2026-08-20T10:00:00Z",
                              capacity=1, stigma_theme="NORMALIZATION")
    reg = register_client_for_event(event["id"], client["id"], client_headers)
    full_event = validate_success(
        api.list_outreach_events(ADMIN, params={"status": "FULL"}), 200
    )
    assert full_event[0]["id"] == event["id"]

    item = create_item("ExitItem", category="HYGIENE", point_cost=5,
                       quantity_on_hand=5, reorder_threshold=0, per_visit_limit=2)
    visit, _ = checkin_visit_with_line(pantry, client["id"], item["id"], 1)

    exited = validate_success(api.exit_client(client["id"], coord), 200)
    assert exited["status"] == "EXITED"

    stays = validate_success(
        api.list_shelter_stays(shelter, params={"client_id": client["id"]}), 200
    )
    assert stays[0]["status"] == "CANCELLED"

    referrals = validate_success(
        api.list_referrals(coord, params={"client_id": client["id"]}), 200
    )
    assert referrals[0]["status"] == "WITHDRAWN"
    agencies = validate_success(api.list_partner_agencies(ADMIN), 200)
    assert agencies[0]["active_referral_count"] == 0, (
        "withdrawing the SENT referral decremented the counter"
    )

    events = validate_success(api.list_outreach_events(ADMIN), 200)
    assert events[0]["status"] == "OPEN", "the cancellation flipped FULL back to OPEN"
    assert events[0]["registered_count"] == 0
    reg_after = validate_success(api.get_event_registration(reg["id"], ADMIN), 200)
    assert reg_after["status"] == "CANCELLED"

    visits = validate_success(
        api.list_pantry_visits(pantry, params={"client_id": client["id"]}), 200
    )
    assert visits[0]["status"] == "VOIDED"
    items = validate_success(api.list_pantry_items(pantry), 200)
    assert items[0]["quantity_on_hand"] == 5, (
        "the open visit was never checked out — stock untouched"
    )

    discarded = validate_success(
        api.list_assessments(coord, params={"client_id": client["id"],
                                            "status": "DISCARDED"}),
        200,
    )
    assert [a["id"] for a in discarded] == [a2["id"]]
    a1_after = validate_success(api.get_assessment(a1["id"], coord), 200)
    assert a1_after["status"] == "VERIFIED"


def test_suspend_auto_voids_open_visit_and_blocks_checkin(api):
    """PRD §3.1: "Suspension by a `HubAdmin` moves an `ACTIVE` client to
    `SUSPENDED` — a client in any other state is rejected with
    `ERR_CLIENT_NOT_ACTIVE` — and as a protective side effect the client's
    open pantry visit, if one is checked in at that moment, is auto-voided:
    its provisional lines are discarded and its frequency slot is freed.
    Reinstatement by a `HubAdmin` moves a `SUSPENDED` client back to
    `ACTIVE`."
    PRD §3.3: "Check-in requires the client to be `ACTIVE` (else
    `ERR_CLIENT_NOT_ACTIVE`) ..."

    Design: Corner/state_machines/suspend_auto_voids_open_visit_and_blocks_checkin
    """
    sc = setup_pantry_scenario(
        client_alias="sv",
        item_name="Soup",
        item_overrides={"point_cost": 10, "quantity_on_hand": 10,
                        "reorder_threshold": 0, "per_visit_limit": 5},
    )
    visit, _ = checkin_visit_with_line(
        sc["pantry_headers"], sc["client"]["id"], sc["item"]["id"], 1
    )

    suspended = validate_success(api.suspend_client(sc["client"]["id"], ADMIN), 200)
    assert suspended["status"] == "SUSPENDED"
    visits = validate_success(
        api.list_pantry_visits(sc["pantry_headers"],
                               params={"client_id": sc["client"]["id"]}),
        200,
    )
    assert visits[0]["status"] == "VOIDED", "the open visit is auto-voided"

    res = api.check_in_pantry_visit(sc["client"]["id"], sc["pantry_headers"])
    validate_error(res, ApiErrorId.ERR_CLIENT_NOT_ACTIVE, expected_status=409)

    reinstated = validate_success(api.reinstate_client(sc["client"]["id"], ADMIN), 200)
    assert reinstated["status"] == "ACTIVE"
    v2 = validate_success(
        api.check_in_pantry_visit(sc["client"]["id"], sc["pantry_headers"]), 201
    )
    assert v2["status"] == "CHECKED_IN", (
        "the voided visit holds no frequency slot"
    )
    items = validate_success(api.list_pantry_items(sc["pantry_headers"]), 200)
    assert items[0]["quantity_on_hand"] == 10, "stock untouched throughout"


def test_pantry_staff_cannot_read_assessments(api):
    """PRD §2.9: "`PantryStaff`, `ShelterCoordinator`, and `PartnerAgencyRep`
    callers never read either family: any attempt by one of those roles to
    read assessment or screening data, whether listing the collections or
    reading a single record, is rejected with `ERR_CONFIDENTIAL`."

    Design: Corner/rbac/pantry_staff_cannot_read_assessments
    """
    _, coord = create_coordinator()
    _, pantry = create_pantry_staff()
    client = register_client(alias_name="cf")
    assessment = get_success_data(
        api.create_assessment(client["id"], create_assessment_payload(), coord)
    )
    get_success_data(api.submit_assessment(client["id"], assessment["id"], coord))

    res = api.list_assessments(pantry, params={"client_id": client["id"]})
    validate_error(res, ApiErrorId.ERR_CONFIDENTIAL, expected_status=403)

    listing = validate_success(
        api.list_assessments(coord, params={"client_id": client["id"]}), 200
    )
    assert len(listing) == 1, "the wall is role-scoped, not data-scoped"


def test_client_cannot_read_other_clients_record(api):
    """PRD §2.1: "Ownership checks on any resource that references a client
    compare the resource's owning `client_id` to `X-User-ID`; a `Client`-role
    caller touching another client's resource is rejected with
    `ERR_FORBIDDEN_OWNERSHIP`."

    Design: Corner/rbac/client_cannot_read_other_clients_record
    """
    c1 = register_client(alias_name="c1")
    c2 = register_client(alias_name="c2")

    res = api.get_client(c2["id"], make_client_headers(c1["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, expected_status=403)

    own = validate_success(api.get_client(c2["id"], make_client_headers(c2["id"])), 200)
    assert own["alias_name"] == "c2"


def test_partner_rep_cannot_acknowledge_other_agencys_referral(api):
    """PRD §3.7: "Everything after the send happens on the agency's side,
    driven by a `PartnerAgencyRep` whose `X-User-ID` must equal the referral's
    `agency_id` (else `ERR_FORBIDDEN_OWNERSHIP`)."

    Design: Corner/rbac/partner_rep_cannot_acknowledge_other_agencys_referral
    """
    _, coord = create_coordinator()
    client, _, _ = create_active_client(coord, client_overrides={"alias_name": "pr"})
    agency_a = create_agency("Agency A", service_categories=["SNAP_APPLICATION"],
                             weekly_capacity=5)
    agency_b = create_agency("Agency B", service_categories=["SNAP_APPLICATION"],
                             weekly_capacity=5)
    referral = get_success_data(
        api.create_referral(client["id"], create_referral_payload(agency_a["id"]), coord)
    )
    validate_success(api.send_referral(referral["id"], coord), 200)

    res = api.acknowledge_referral(
        referral["id"], make_partner_agency_rep_headers(agency_b["id"])
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, expected_status=403)

    acked = validate_success(
        api.acknowledge_referral(
            referral["id"], make_partner_agency_rep_headers(agency_a["id"])
        ),
        200,
    )
    assert acked["status"] == "ACKNOWLEDGED"


def test_staff_role_mismatch_is_unauthenticated(api):
    """PRD §2.1: "The referenced staff member must exist, must be `ACTIVE`,
    and its `staff_role` must match the claimed role ..."
    PRD §2.1: "... an entity-backed identity that fails to resolve (no such
    client, staff member, or agency; an `INACTIVE` staff member; an `EXITED`
    client; or a `staff_role` that contradicts the claimed role) is rejected
    with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/staff_role_mismatch_is_unauthenticated
    """
    pantry_staff = get_success_data(
        api.create_staff(
            create_staff_payload(full_name="P Pa", email="pantry@hub.test",
                                 staff_role="PANTRY_STAFF"),
            ADMIN,
        )
    )
    client = register_client(alias_name="mm")
    res = api.create_assessment(
        client["id"],
        create_assessment_payload(),
        # A PANTRY_STAFF member presenting the IntakeCoordinator role claim.
        make_intake_coordinator_headers(pantry_staff["id"]),
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_pantry_staff_cannot_create_grant_fund(api):
    """PRD §2.1: "Once authenticated, a caller whose role does not appear in
    the endpoint's authorized role list is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/pantry_staff_cannot_create_grant_fund_returns_403
    """
    _, pantry = create_pantry_staff()
    res = api.create_grant_fund(
        {"fund_name": "Nope", "fiscal_year": 2026, "allocated_cents": 1000}, pantry
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

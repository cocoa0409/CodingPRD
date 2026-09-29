"""The authentication ladder, entity-backed ownership and the peer role lanes."""

from test_helpers import (
    CLOCK_T0,
    CREW_COORDINATOR,
    DIRECTOR,
    INTAKE_ADVISOR,
    MISSING_UUID,
    NO_HEADERS,
    PERMIT_OFFICER,
    SECOND_INSURER,
    SHOP_ESTIMATOR,
    assert_money_chain,
    assert_supplement_state,
    billing_payload,
    bring_vehicle_to,
    create_facility,
    create_insurer,
    create_storm_event,
    create_technician,
    decide_permit,
    file_permit,
    file_supplement,
    headers_without_user_id,
    make_insurer_adjuster_headers,
    make_pdr_technician_headers,
    make_quality_inspector_headers,
    make_undeclared_role_headers,
    permit_decision_payload,
    permit_payload,
    read_event,
    read_facility,
    read_insurer,
    read_supplement,
    read_technician,
    read_vehicle,
    read_vehicle_version,
    set_clock,
    setup_operational_facility,
    start_repair,
    storm_event_decision_payload,
    supplement_review_payload,
    target_storm_event,
    tech_id,
    technician_payload,
    validate_error,
    validate_paginated,
    validate_success,
    work_ticket_payload,
)


def test_the_auth_ladder_answers_before_any_shape_or_existence_check(api):
    """PRD §2.1: "Every request to the service must carry two headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, naming that principal's
    role. If either header is absent, or if `X-User-Role` is not one of the nine
    declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If
    the headers are well-formed but the named role is not authorized for the endpoint
    being called, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    PRD §2.11: "When a single request violates several rules at once, the response
    reports the violation with the lowest ordinal in the list below. The ordering is
    contractual: a mid-flight lifecycle problem must not be masked by a later fiscal
    check, and a fiscal check must not be reported for a request that was never
    authorized in the first place."

    PRD §2.11: "**Endpoint role authorization** — the acting role appears on the
    endpoint's authorized list: `ERR_ROLE_NOT_PERMITTED` (403), on every endpoint."

    PRD §3.1: "A `TARGET` decision moves `EVALUATING` → `TARGETED`; a `DECLINE`
    decision moves `EVALUATING` → `DECLINED`, which is terminal. Either way the
    event's `version` increments by one."

    Design: Corner/rbac/unauthenticated_and_missing_header_calls_die_before_role_and_state_checks
    """
    set_clock(api, CLOCK_T0)
    event = create_storm_event(api)
    event_id = event["id"]
    assert event["status"] == "EVALUATING"
    assert event["targeting_score"] >= 60
    undecided_version = event["version"]

    decision = storm_event_decision_payload("TARGET")

    nothing_sent = api.decide_storm_event(event_id, decision, NO_HEADERS)
    validate_error(nothing_sent, "ERR_UNAUTHENTICATED", 401)

    # A well-formed role is not enough; the principal must be named too.
    no_principal = api.decide_storm_event(
        event_id, decision, headers_without_user_id("CatastropheDirector")
    )
    validate_error(no_principal, "ERR_UNAUTHENTICATED", 401)

    # An undeclared role string fails the first rung, so it is 401 and not 403.
    invented_role = api.decide_storm_event(
        event_id, decision, make_undeclared_role_headers()
    )
    validate_error(invented_role, "ERR_UNAUTHENTICATED", 401)

    wrong_role = api.decide_storm_event(event_id, decision, PERMIT_OFFICER)
    validate_error(wrong_role, "ERR_ROLE_NOT_PERMITTED", 403)

    # Bad enum (ordinal 3) and unknown event (ordinal 4) both lose to ordinal 2.
    role_wins = api.decide_storm_event(
        MISSING_UUID, storm_event_decision_payload("TARGETTED"), PERMIT_OFFICER
    )
    validate_error(role_wins, "ERR_ROLE_NOT_PERMITTED", 403)

    still_undecided = read_event(api, event_id)
    assert still_undecided["status"] == "EVALUATING"
    assert still_undecided["version"] == undecided_version

    targeted = target_storm_event(api, event_id)
    assert targeted["status"] == "TARGETED"
    assert targeted["version"] == undecided_version + 1


def test_ownership_is_read_off_a_different_entity_for_each_backed_role(api):
    """PRD §2.1: "When `X-User-Role` is `InsurerAdjuster`, `X-User-ID` is the `id` of
    the acting `Insurer`; billing actions and supplement reviews are permitted only
    when the target vehicle's `insurer_id` equals `X-User-ID`. Any of these three
    mismatches is rejected with `ERR_IDENTITY_MISMATCH` (HTTP 403)."

    PRD §3.7: "Because the role is entity-backed, the ticket's `technician_id` must
    equal the acting `X-User-ID`, and a mismatch is `ERR_IDENTITY_MISMATCH`."

    PRD §3.8: "`APPROVE` moves `UNDER_REVIEW` → `APPROVED`, terminal, sets
    `approved_amount_cents` to `requested_amount_cents`, stamps `decided_at`,
    increments the supplement's `version`, and runs exactly the same three-hop
    cascade as an auto-approval: vehicle money chain first, then the facility's
    `billable_accrued_cents` when the vehicle's `billing_status` is `AUTHORIZED`,
    `BILLED` or `PAID`, then the carrier's `outstanding_direct_bill_cents`."

    Design: Corner/rbac/an_adjuster_cannot_act_for_another_carrier_and_a_tech_cannot_file_for_a_peer
    """
    scenario = setup_operational_facility(api, technicians=("TA", "TI"))
    bystander = create_insurer(api, **SECOND_INSURER)
    car = bring_vehicle_to(
        api,
        scenario,
        "TRIAGED",
        damage_profile="single_panel_conventional",
        rental_required=False,
    )
    vehicle_id = car["vehicle_id"]
    owner_id = scenario["insurer_id"]
    assert car["vehicle"]["approved_repair_cents"] == 77000

    intruder = make_insurer_adjuster_headers(bystander["id"])
    poached = api.vehicle_billing(vehicle_id, billing_payload("AUTHORIZE"), intruder)
    validate_error(poached, "ERR_IDENTITY_MISMATCH", 403)
    assert read_vehicle(api, vehicle_id)["billing_status"] == "UNBILLED"

    authorized = validate_success(
        api.vehicle_billing(
            vehicle_id,
            billing_payload("AUTHORIZE"),
            make_insurer_adjuster_headers(owner_id),
        )
    )
    assert authorized["billing_status"] == "AUTHORIZED"
    assert read_facility(api, scenario["facility_id"])["billable_accrued_cents"] == 80850
    assert read_insurer(api, owner_id)["outstanding_direct_bill_cents"] == 80850

    start_repair(api, vehicle_id)

    # The inspector is a real technician on site, but not the one being paid.
    worker = tech_id(scenario, "TA")
    impostor = tech_id(scenario, "TI")
    ghost_written = api.create_work_ticket(
        work_ticket_payload(vehicle_id, worker),
        make_pdr_technician_headers(impostor),
    )
    validate_error(ghost_written, "ERR_IDENTITY_MISMATCH", 403)
    _, no_tickets = validate_paginated(
        api.list_work_tickets(SHOP_ESTIMATOR, {"vehicle_id": vehicle_id})
    )
    assert no_tickets["total_count"] == 0

    # 30,000 clears the 15,000 auto-approve floor, so the carrier must rule on it.
    supplement = file_supplement(
        api, vehicle_id, 30000, expected_vehicle_version=read_vehicle_version(api, vehicle_id)
    )
    assert_supplement_state(supplement, status="UNDER_REVIEW", round_index=1)

    poached_review = api.review_supplement(
        supplement["id"], supplement_review_payload("APPROVE"), intruder
    )
    validate_error(poached_review, "ERR_IDENTITY_MISMATCH", 403)
    assert read_supplement(api, supplement["id"])["status"] == "UNDER_REVIEW"

    approved = validate_success(
        api.review_supplement(
            supplement["id"],
            supplement_review_payload("APPROVE"),
            make_insurer_adjuster_headers(owner_id),
        )
    )
    assert_supplement_state(approved, status="APPROVED", approved_amount_cents=30000)

    vehicle = read_vehicle(api, vehicle_id)
    assert vehicle["approved_supplement_cents"] == 30000
    assert_money_chain(
        vehicle,
        admin_fee_cents=5350,
        gross_billable_cents=112350,
        discount_cents=0,
        net_billable_cents=112350,
    )
    assert read_insurer(api, owner_id)["outstanding_direct_bill_cents"] == 112350

    # Nothing in the three-hop cascade ever reaches a carrier that was not named.
    untouched = read_insurer(api, bystander["id"])
    assert untouched["outstanding_direct_bill_cents"] == 0
    assert untouched["settled_cents"] == 0


def _a_setup_lot_with_zoning_still_pending(api):
    """A `SETUP` lot whose licence is approved, zoning pending, and `TA` on the roster."""
    set_clock(api, CLOCK_T0)
    event = create_storm_event(api)
    target_storm_event(api, event["id"])
    facility = create_facility(api, event["id"])

    licence = file_permit(api, facility["id"], "TEMP_BUSINESS_LICENSE")
    decide_permit(api, licence["id"], "APPROVE", "2026-08-01", "2026-09-30")
    zoning = file_permit(api, facility["id"], "ZONING_USE")

    technician = create_technician(api, "TA")
    return facility["id"], zoning, technician


def test_no_role_is_a_superset_of_a_peer_while_shared_reads_stay_shared(api):
    """PRD §3.2: "A `PermitOfficer` — and nobody else, since the party that applies
    for a permit can never be the party that decides it — records a `decision` of
    `APPROVE` or `DENY` on a permit that is still `PENDING`; a decision on any other
    status is rejected with `ERR_PERMIT_ALREADY_DECIDED`."

    PRD §4: "| POST | `/hail-ops/technicians` | Add a traveling technician to the
    roster | CrewCoordinator |"

    PRD §4: "| GET | `/hail-ops/facilities/{id}/throughput-summary` | Computed
    staging and throughput read for the facility | CatastropheDirector,
    ShopEstimator, IntakeAdvisor |"

    PRD §4: "| GET | `/hail-ops/technicians/{id}` | Read one technician with accrued
    pay | CatastropheDirector, CrewCoordinator, ShopEstimator, IntakeAdvisor,
    PdrTechnician, QualityInspector |"

    PRD §2.3: "Every list endpoint returns its rows sorted by `created_at` in
    ascending order, so a page boundary is stable as long as no new rows are
    inserted."

    Design: Corner/rbac/peer_lanes_stay_separate_while_shared_reads_stay_open
    """
    facility_id, zoning, technician = _a_setup_lot_with_zoning_still_pending(api)
    approval = permit_decision_payload("APPROVE", "2026-08-01", "2026-09-30")

    # The director filed this application and may not also rule on it.
    self_dealt = api.decide_permit(zoning["id"], approval, DIRECTOR)
    validate_error(self_dealt, "ERR_ROLE_NOT_PERMITTED", 403)

    hired_by_the_wrong_desk = api.create_technician(
        technician_payload(
            "Sly Ortega",
            home_state_code="KS",
            license_expires_at="2027-09-30",
            skill_tier="JOURNEYMAN",
            flat_split_pct=0.4,
        ),
        INTAKE_ADVISOR,
    )
    validate_error(hired_by_the_wrong_desk, "ERR_ROLE_NOT_PERMITTED", 403)

    # The officer rules on applications; the officer never files them.
    filed_by_the_judge = api.create_permit(
        permit_payload(facility_id, "SIGNAGE"), PERMIT_OFFICER
    )
    validate_error(filed_by_the_judge, "ERR_ROLE_NOT_PERMITTED", 403)

    # The crew coordinator runs the roster, not the yard's throughput read.
    coordinator_peeks = api.get_throughput_summary(facility_id, CREW_COORDINATOR)
    validate_error(coordinator_peeks, "ERR_ROLE_NOT_PERMITTED", 403)

    # The officer's one shared read does work, and it is ordered oldest first.
    rows, meta = validate_paginated(api.list_facility_permits(facility_id, PERMIT_OFFICER))
    assert meta["total_count"] == 2
    assert rows[0]["permit_type"] == "TEMP_BUSINESS_LICENSE"

    inspector_reads = validate_success(
        api.get_technician(technician["id"], make_quality_inspector_headers(technician["id"]))
    )
    assert inspector_reads["full_name"] == "Tara Alvarez"

    # Only the role was wrong the first time; the identical payload now lands.
    approved = validate_success(api.decide_permit(zoning["id"], approval, PERMIT_OFFICER))
    assert approved["status"] == "APPROVED"

    assert read_facility(api, facility_id)["status"] == "SETUP"
    assert read_technician(api, technician["id"])["accrued_pay_cents"] == 0

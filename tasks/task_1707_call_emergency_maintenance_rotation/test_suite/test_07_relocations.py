"""Relocation cases: cost variants, approval cascade, overlaps, SoD, gates."""
from test_helpers import (
    ApiErrorId,
    activate_relocation,
    api_client,
    approve_relocation,
    arrive_ticket,
    create_relocation_case_payload,
    create_ticket,
    create_work_order_payload,
    end_relocation,
    get_relocation_case,
    get_unit,
    get_vendor_authorization,
    get_work_order,
    list_ticket_work_orders,
    make_supervisor,
    make_supervisor_headers,
    make_technician,
    make_technician_headers,
    make_unit,
    make_vendor,
    mitigate_ticket,
    mitigated_ticket_with_work_order,
    propose_relocation,
    propose_vendor_authorization,
    publish_shift,
    set_clock,
    setup_uninhabitable_incident,
    start_shift,
    validate_error,
    validate_success,
)


class TestEstimateVsActualOverstay:
    def _setup_active_case(self):
        """5-night case (20000/night) APPROVED and ACTIVE; follow-up cancelled."""
        cast = setup_uninhabitable_incident(unit_number="U-101")
        tech, sup, unit, ticket = (
            cast["technician"], cast["supervisor"], cast["unit"], cast["ticket"],
        )
        sup_headers = make_supervisor_headers(sup["id"])
        orders, _meta = list_ticket_work_orders(ticket["id"])
        for order in orders:
            validate_success(api_client.cancel_work_order(order["id"], sup_headers),
                             200)
        case = propose_relocation(unit["id"], ticket["id"],
                                  "2026-08-03T00:00:00Z", "2026-08-08T00:00:00Z",
                                  20000, tech["id"])
        approve_relocation(case["id"], sup_headers)
        set_clock("2026-08-03T12:00:00Z")
        activate_relocation(case["id"], sup)
        return cast, case

    def test_relocation_estimate_uses_planned_nights_flat_rate(self, api):
        """PRD §3.7: "The estimated cost is computed at proposal as
        `planned_nights` times `nightly_rate_cents` plus a flat administrative
        fee of 15000 cents ($150.00), stored as `est_cost_cents`."
        PRD §3.7: "The stay must span at least one night — `end_date` strictly
        after `start_date`, with the whole-day difference stored as
        `planned_nights`..."

        Design: Difficulty/dual_variant_calc/relocation_estimate_vs_actual_overstay
        """
        _cast, case = self._setup_active_case()
        current = get_relocation_case(case["id"])
        assert current["planned_nights"] == 5
        assert current["est_cost_cents"] == 115000, "5 x 20000 + 15000 fee"

    def test_relocation_actual_bills_overage_nights_at_125(self, api):
        """PRD §3.7: "Ending computes `actual_cost_cents`: the actual nights
        run from `start_date` to `actual_end_date` (at least one); nights
        beyond `planned_nights` are overage nights, billed each at the nightly
        rate multiplied by 1.25 with that overage nightly rate rounded half-up
        once before multiplication; the total is the normal nights times
        `nightly_rate_cents`, plus the overage nights times the rounded overage
        rate, plus the same 15000-cent administrative fee."
        PRD §3.7: "Ending also restores the unit's `habitability_status` to
        `HABITABLE`..."

        Design: Difficulty/dual_variant_calc/relocation_estimate_vs_actual_overstay
        """
        cast, case = self._setup_active_case()
        ended = end_relocation(case["id"], "2026-08-10T00:00:00Z",
                               cast["supervisor"])
        assert ended["status"] == "ENDED"
        assert ended["actual_cost_cents"] == 165000, (
            "5 normal nights x 20000 + 2 overage nights x 25000 + 15000 fee"
        )
        assert ended["actual_cost_cents"] != ended["est_cost_cents"]
        assert get_unit(cast["unit"]["id"])["habitability_status"] == "HABITABLE"


class TestApprovalCascade:
    def _setup_cascade(self):
        """Uninhabitable ticket; STANDARD order with a PROPOSED VA; case ready."""
        cast = setup_uninhabitable_incident(unit_number="U-501")
        tech, sup, unit, ticket = (
            cast["technician"], cast["supervisor"], cast["unit"], cast["ticket"],
        )
        sup_headers = make_supervisor_headers(sup["id"])
        orders, _meta = list_ticket_work_orders(ticket["id"], status="OPEN")
        emergency_wo = orders[0]
        standard_wo = validate_success(
            api_client.create_work_order(
                create_work_order_payload(
                    call_ticket_id=ticket["id"], title="Baseboard replacement",
                    description="Replace swollen baseboards",
                ),
                sup_headers,
            ),
            201,
        )
        vendor = make_vendor(name="DryFast", trade="RESTORATION",
                             per_incident_limit_cents=500000)
        va = propose_vendor_authorization(ticket["id"], standard_wo["id"],
                                          vendor["id"], 30000, tech["id"])
        case = propose_relocation(unit["id"], ticket["id"],
                                  "2026-08-03T00:00:00Z", "2026-08-06T00:00:00Z",
                                  15000, tech["id"])
        return cast, emergency_wo, standard_wo, va, case

    def test_relocation_approval_flips_unit_and_holds_standard_orders(self, api):
        """PRD §3.7: "the unit's `habitability_status` flips to `UNINHABITABLE`;
        every work order on that unit in `OPEN` or `ASSIGNED` whose `priority`
        is not `EMERGENCY_FOLLOWUP` is placed `ON_HOLD` (emergency follow-ups
        keep moving); and each such held order's still-`PROPOSED` vendor
        authorizations are moved to `VOIDED`."

        Design: Difficulty/transitive_cascade/relocation_approval_three_hop_cascade
        """
        cast, _em, standard_wo, _va, case = self._setup_cascade()
        sup = cast["supervisor"]
        approved = approve_relocation(case["id"], make_supervisor_headers(sup["id"]))
        assert approved["status"] == "APPROVED"
        assert get_unit(cast["unit"]["id"])["habitability_status"] == "UNINHABITABLE"
        assert get_work_order(standard_wo["id"])["status"] == "ON_HOLD"

    def test_relocation_approval_voids_proposed_va_and_exempts_emergency(
        self, api
    ):
        """PRD §3.7: "every work order on that unit in `OPEN` or `ASSIGNED`
        whose `priority` is not `EMERGENCY_FOLLOWUP` is placed `ON_HOLD`
        (emergency follow-ups keep moving); and each such held order's
        still-`PROPOSED` vendor authorizations are moved to `VOIDED`."
        PRD §3.4: "Mitigation also automatically creates a follow-up work order
        with `priority` `EMERGENCY_FOLLOWUP` in `OPEN`, its `unit_id` copied
        from the ticket — this order represents the permanent repair and is
        deliberately exempt from the relocation hold cascade described in
        §3.7."

        Design: Difficulty/transitive_cascade/relocation_approval_three_hop_cascade
        """
        cast, emergency_wo, _standard_wo, va, case = self._setup_cascade()
        sup = cast["supervisor"]
        approve_relocation(case["id"], make_supervisor_headers(sup["id"]))
        assert get_vendor_authorization(va["id"])["status"] == "VOIDED", (
            "the hold voids the order's still-PROPOSED authorizations"
        )
        assert get_work_order(emergency_wo["id"])["status"] == "OPEN", (
            "EMERGENCY_FOLLOWUP is exempt from the hold"
        )


class TestClosedIntervalOverlap:
    def _setup(self):
        cast = setup_uninhabitable_incident(unit_number="U-901")
        tech, sup, unit, ticket = (
            cast["technician"], cast["supervisor"], cast["unit"], cast["ticket"],
        )
        case_a = propose_relocation(unit["id"], ticket["id"],
                                    "2026-08-05T00:00:00Z",
                                    "2026-08-10T00:00:00Z",
                                    20000, tech["id"])
        approve_relocation(case_a["id"], make_supervisor_headers(sup["id"]))
        return cast, case_a

    def test_relocation_shared_boundary_date_conflicts(self, api):
        """PRD §3.7: "the closed interval must not collide with any other
        `APPROVED` or `ACTIVE` case for the same unit: because both boundaries
        are inclusive, even a shared boundary date is a conflict, rejected with
        `ERR_RELOCATION_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/relocation_closed_interval_shared_boundary_conflicts
        """
        cast, case_a = self._setup()
        resp = api_client.create_relocation_case(
            create_relocation_case_payload(
                unit_id=cast["unit"]["id"],
                call_ticket_id=cast["ticket"]["id"],
                start_date="2026-08-10T00:00:00Z",
                end_date="2026-08-12T00:00:00Z",
                nightly_rate_cents=20000,
            ),
            make_technician_headers(cast["technician"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RELOCATION_OVERLAP)
        assert get_relocation_case(case_a["id"])["status"] == "APPROVED", (
            "the existing case is unaffected"
        )

    def test_relocation_starting_day_after_end_is_free(self, api):
        """PRD §2.10: "**Relocation stays**, by contrast, occupy a closed
        interval: both `start_date` and `end_date` are nights of displacement,
        and a second approved stay for the same unit that merely shares a
        boundary date with an existing one is already a conflict."
        PRD §3.7: "The estimated cost is computed at proposal as
        `planned_nights` times `nightly_rate_cents` plus a flat administrative
        fee of 15000 cents ($150.00), stored as `est_cost_cents`."

        Design: Difficulty/resource_temporal_overlap/relocation_closed_interval_shared_boundary_conflicts
        """
        cast, _case_a = self._setup()
        created = validate_success(
            api_client.create_relocation_case(
                create_relocation_case_payload(
                    unit_id=cast["unit"]["id"],
                    call_ticket_id=cast["ticket"]["id"],
                    start_date="2026-08-11T00:00:00Z",
                    end_date="2026-08-13T00:00:00Z",
                    nightly_rate_cents=20000,
                ),
                make_technician_headers(cast["technician"]["id"]),
            ),
            201,
        )
        assert created["status"] == "PROPOSED"
        assert created["planned_nights"] == 2
        assert created["est_cost_cents"] == 55000, "2 x 20000 + 15000 fee"


class TestEndBlockedByOpenWorkOrder:
    def _setup_active_case_with_open_followup(self):
        """ACTIVE case; the EMERGENCY_FOLLOWUP order (exempt from the hold)
        is still OPEN and therefore blocks the end."""
        cast = setup_uninhabitable_incident(unit_number="U-802")
        tech, sup = cast["technician"], cast["supervisor"]
        sup_headers = make_supervisor_headers(sup["id"])
        case = propose_relocation(cast["unit"]["id"], cast["ticket"]["id"],
                                  "2026-08-03T00:00:00Z", "2026-08-05T00:00:00Z",
                                  10000, tech["id"])
        approve_relocation(case["id"], sup_headers)
        set_clock("2026-08-03T09:00:00Z")
        activate_relocation(case["id"], sup)
        orders, _meta = list_ticket_work_orders(cast["ticket"]["id"])
        emergency_wo = orders[0]
        return cast, case, emergency_wo

    def test_relocation_end_blocked_by_open_emergency_followup(self, api):
        """PRD §3.7: "End is blocked while any work order on the unit remains
        in `OPEN`, `ASSIGNED`, `IN_PROGRESS`, or `REOPENED` — orders sitting
        `ON_HOLD` are excluded from this check and do not block (else
        `ERR_WORK_ORDER_INVALID_STATE`)."

        Design: Difficulty/cross_entity_state_dependency/relocation_end_blocked_by_open_unit_work_order
        """
        cast, case, _wo = self._setup_active_case_with_open_followup()
        resp = api_client.end_relocation_case(
            case["id"], {"actual_end_date": "2026-08-05T00:00:00Z"},
            make_supervisor_headers(cast["supervisor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WORK_ORDER_INVALID_STATE)
        assert get_relocation_case(case["id"])["status"] == "ACTIVE"
        assert get_unit(cast["unit"]["id"])["habitability_status"] == "UNINHABITABLE"

    def test_relocation_end_unblocked_after_cancelling_blocking_order(self, api):
        """PRD §3.7: "Ending computes `actual_cost_cents`: the actual nights
        run from `start_date` to `actual_end_date` (at least one); nights
        beyond `planned_nights` are overage nights, billed each at the nightly
        rate multiplied by 1.25 with that overage nightly rate rounded half-up
        once before multiplication; the total is the normal nights times
        `nightly_rate_cents`, plus the overage nights times the rounded overage
        rate, plus the same 15000-cent administrative fee. Ending also restores
        the unit's `habitability_status` to `HABITABLE`..."

        Design: Difficulty/cross_entity_state_dependency/relocation_end_blocked_by_open_unit_work_order
        """
        cast, case, wo = self._setup_active_case_with_open_followup()
        sup_headers = make_supervisor_headers(cast["supervisor"]["id"])
        validate_error(
            api_client.end_relocation_case(
                case["id"], {"actual_end_date": "2026-08-05T00:00:00Z"},
                sup_headers,
            ),
            ApiErrorId.ERR_WORK_ORDER_INVALID_STATE,
        )
        validate_success(
            api_client.cancel_work_order(
                wo["id"], sup_headers
            ),
            200,
        )
        ended = end_relocation(case["id"], "2026-08-05T00:00:00Z",
                               cast["supervisor"])
        assert ended["status"] == "ENDED"
        assert ended["actual_cost_cents"] == 35000, (
            "2 nights x 10000 + 15000 fee, no overstay"
        )
        assert get_unit(cast["unit"]["id"])["habitability_status"] == "HABITABLE"


def test_relocation_reject_resubmit_cycle(api):
    """PRD §3.7: "A rejected case is not dead: resubmission by an
    `OnCallTechnician` or `MaintenanceSupervisor` moves `REJECTED → PROPOSED`,
    replaces the stay's dates and `nightly_rate_cents`, re-records
    `proposed_by_technician_id` as the resubmitting actor, recomputes
    `est_cost_cents`, re-runs the closed-interval overlap check, and increments
    `version` — while the earlier `reject_reason` is preserved through the
    cycle."

    Design: Corner/state_machines/relocation_reject_resubmit_cycle
    """
    cast = setup_uninhabitable_incident(unit_number="S-4")
    tech, sup = cast["technician"], cast["supervisor"]
    sup_headers = make_supervisor_headers(sup["id"])
    case = propose_relocation(cast["unit"]["id"], cast["ticket"]["id"],
                              "2026-08-03T00:00:00Z", "2026-08-06T00:00:00Z",
                              15000, tech["id"])
    rejected = validate_success(
        api_client.reject_relocation_case(
            case["id"], {"reason": "Rate not negotiated"}, sup_headers
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"

    resubmitted = validate_success(
        api_client.resubmit_relocation_case(
            case["id"],
            {"start_date": "2026-08-04T00:00:00Z",
             "end_date": "2026-08-06T00:00:00Z", "nightly_rate_cents": 18000},
            make_technician_headers(tech["id"]),
        ),
        200,
    )
    assert resubmitted["status"] == "PROPOSED"
    assert resubmitted["est_cost_cents"] == 51000, "2 nights x 18000 + 15000"
    assert resubmitted["reject_reason"] == "Rate not negotiated", (
        "reject reason is preserved through the resubmit cycle"
    )

    approved = approve_relocation(case["id"], sup_headers)
    assert approved["status"] == "APPROVED", "second review round succeeds"


def test_relocation_activate_from_proposed_rejected(api):
    """PRD §3.7: "Once approved, activation moves `APPROVED → ACTIVE` but not
    before the stay's `start_date` has been reached (else
    `ERR_BEFORE_START_DATE`); activation is a `MaintenanceSupervisor` duty."
    PRD §2.9: "5. **State and stale version** — the target resource must be in
    a state that permits the requested transition (the per-entity
    invalid-state errors, HTTP 409)..."

    Design: Corner/state_machines/relocation_activate_from_proposed_rejected
    """
    cast = setup_uninhabitable_incident(unit_number="S-6")
    tech, sup = cast["technician"], cast["supervisor"]
    case = propose_relocation(cast["unit"]["id"], cast["ticket"]["id"],
                              "2026-08-03T00:00:00Z", "2026-08-05T00:00:00Z",
                              10000, tech["id"])
    resp = api_client.activate_relocation_case(
        case["id"], make_supervisor_headers(sup["id"])
    )
    validate_error(resp, ApiErrorId.ERR_RELOCATION_CASE_INVALID_STATE)
    assert get_relocation_case(case["id"])["status"] == "PROPOSED"


def test_relocation_activate_before_start_date_rejected(api):
    """PRD §3.7: "Once approved, activation moves `APPROVED → ACTIVE` but not
    before the stay's `start_date` has been reached (else
    `ERR_BEFORE_START_DATE`); activation is a `MaintenanceSupervisor` duty."

    Design: Corner/errors/relocation_activate_before_start_date_rejected
    """
    cast = setup_uninhabitable_incident(unit_number="E-1")
    tech, sup = cast["technician"], cast["supervisor"]
    sup_headers = make_supervisor_headers(sup["id"])
    case = propose_relocation(cast["unit"]["id"], cast["ticket"]["id"],
                              "2026-08-05T00:00:00Z", "2026-08-07T00:00:00Z",
                              10000, tech["id"])
    approve_relocation(case["id"], sup_headers)
    # The clock still reads 2026-08-01: ahead of the 2026-08-05 start date.
    resp = api_client.activate_relocation_case(
        case["id"], sup_headers
    )
    validate_error(resp, ApiErrorId.ERR_BEFORE_START_DATE)
    assert get_relocation_case(case["id"])["status"] == "APPROVED"


def test_relocation_requires_uninhabitable_declaration(api):
    """PRD §3.7: "The proposal is only meaningful for a genuinely uninhabitable
    unit: the referenced ticket must have been mitigated with
    `unit_uninhabitable` true (else `ERR_UNIT_NOT_UNINHABITABLE`)..."

    Design: Corner/validations/relocation_requires_uninhabitable_declaration
    """
    set_clock("2026-08-03T00:00:00Z")
    tech = make_technician()
    unit = make_unit(unit_number="M-3", building_code="BM")
    shift = publish_shift(tech["id"], "2026-08-03T00:00:00Z",
                          "2026-08-03T08:00:00Z")
    start_shift(shift["id"])
    ticket, _wo = mitigated_ticket_with_work_order(
        unit["id"], tech["id"], "LEAK_MINOR",
        dispatch_at="2026-08-03T00:00:00Z",
        mitigate_at="2026-08-03T01:00:00Z",
        unit_uninhabitable=False,
    )
    resp = api_client.create_relocation_case(
        create_relocation_case_payload(
            unit_id=unit["id"], call_ticket_id=ticket["id"],
            start_date="2026-08-04T00:00:00Z",
            end_date="2026-08-06T00:00:00Z", nightly_rate_cents=10000,
        ),
        make_technician_headers(tech["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_UNINHABITABLE)


def test_relocation_window_invalid_returns_invalid_request(api):
    """PRD §3.7: "The stay must span at least one night — `end_date` strictly
    after `start_date`, with the whole-day difference stored as
    `planned_nights`..."
    PRD §2.9: "4. **Request body shape** — required fields present, enum values
    valid, datetimes and integers well-formed, window ends strictly after their
    starts, amounts strictly positive (`ERR_INVALID_REQUEST`, HTTP 400)."

    Design: Corner/validations/relocation_window_invalid_returns_invalid_request
    """
    tech = make_technician()
    unit = make_unit(unit_number="M-8", building_code="BM")
    ticket = create_ticket(unit["id"], "FLOOD", description="flood")
    resp = api_client.create_relocation_case(
        create_relocation_case_payload(
            unit_id=unit["id"], call_ticket_id=ticket["id"],
            start_date="2026-08-05T00:00:00Z",
            end_date="2026-08-05T00:00:00Z", nightly_rate_cents=10000,
        ),
        make_technician_headers(tech["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_relocation_approve_same_person_rejected(api, property_admin_headers):
    """PRD §3.7: "Approval belongs to a `MaintenanceSupervisor` or
    `PropertyAdmin` who is not the proposer (`ERR_SEGREGATION_OF_DUTIES`),
    acting on a `PROPOSED` case (else `ERR_RELOCATION_CASE_INVALID_STATE`).
    Approval records `approved_by_technician_id` — null when the approver is a
    `PropertyAdmin` — recomputes `est_cost_cents`, increments `version`, and
    fires a three-link cascade..."

    Design: Corner/rbac/relocation_approve_same_person_rejected
    """
    cast = setup_uninhabitable_incident(unit_number="R-3")
    sup = cast["supervisor"]
    sup_headers = make_supervisor_headers(sup["id"])
    # The supervisor proposes the case themself.
    case = propose_relocation(
        cast["unit"]["id"], cast["ticket"]["id"],
        "2026-08-02T00:00:00Z", "2026-08-04T00:00:00Z", 10000,
        sup["id"], proposer_headers=sup_headers,
    )
    resp = api_client.approve_relocation_case(
        case["id"], sup_headers
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert get_relocation_case(case["id"])["status"] == "PROPOSED"

    approved = validate_success(
        api_client.approve_relocation_case(
            case["id"], property_admin_headers
        ),
        200,
    )
    assert approved["status"] == "APPROVED"
    assert approved.get("approved_by_technician_id") is None, (
        "an opaque PropertyAdmin approver leaves the field null"
    )


def test_technician_cannot_approve_relocation(api):
    """PRD §3.7: "Approval belongs to a `MaintenanceSupervisor` or
    `PropertyAdmin` who is not the proposer (`ERR_SEGREGATION_OF_DUTIES`)..."
    PRD §2.1: "A request whose role is not in the endpoint's allowed set is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/technician_cannot_approve_relocation
    """
    cast = setup_uninhabitable_incident(unit_number="R-2")
    tech = cast["technician"]
    case = propose_relocation(cast["unit"]["id"], cast["ticket"]["id"],
                              "2026-08-02T00:00:00Z", "2026-08-04T00:00:00Z",
                              10000, tech["id"])
    resp = api_client.approve_relocation_case(
        case["id"], make_technician_headers(tech["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_relocation_case(case["id"])["status"] == "PROPOSED"

"""Role authorisation, identity resolution and dealer-scope separation.

The programme's five roles divide along a segregation-of-duties line: the
administrator owns the rulebook and adjudication, the auditor draws samples and
rules on them, the dealer opens inspections and certifies cars, the technician
records checklist outcomes, and the advocate logs consumer complaints. This
module walks the positive half of that model — every role performing the writes
its own charter gives it — and then the negative half: an operation refused to
each role that does not own it, a resolution refused to the wrong one of the two
roles that share an endpoint, a repair refused to the technician whose own work
it cures, and one dealership refused the records of another. It also pins the
order in which those refusals are decided, because a single request can be
unauthorised, unrecognised, out of scope and in the wrong state all at once
while only one identifier may come back.
"""

from test_helpers import (
    ADMIN,
    ADMIN_USER_ID,
    ADVOCATE,
    AUDITOR,
    CLOCK_EPOCH,
    UNRESOLVABLE_ENTITY_ID,
    ApiErrorId,
    adjudication_payload,
    assert_audit_run_summary,
    assert_certification_number,
    assert_checklist_template,
    assert_complaint,
    assert_dealer,
    assert_instant_equals,
    assert_program_config,
    assert_reconditioning_item,
    assert_vehicle,
    bootstrap_program,
    claim_adjudication_payload,
    clean_attempt_rows,
    complete_reconditioning_payload,
    create_certification_payload,
    create_complaint_payload,
    create_inspection_payload,
    create_technician,
    create_vehicle,
    create_vehicle_payload,
    get_success_data,
    item_b1_payload,
    item_p1_payload,
    item_t1_payload,
    iso_shift,
    make_dealer_principal_headers,
    make_inspection_technician_headers,
    open_inspection_for,
    program_config_payload,
    read_certification,
    read_config,
    read_dealer,
    read_inspection,
    reconditioning_item_for,
    reconditioning_items,
    record_results,
    reimbursable_for,
    result_row,
    results_payload,
    submit_inspection,
    unique_vin,
    validate_error,
    validate_paginated,
    validate_success,
    vehicle_version,
    waive_reconditioning_payload,
)

# Syntactically valid identifiers that name no row at all. The server mints
# random UUIDs, so none of these can ever collide with a real resource.
FABRICATED_CERTIFICATION_ID = "00000000-0000-4000-8000-000000000051"
FABRICATED_VEHICLE_ID = "00000000-0000-4000-8000-000000000052"
FABRICATED_TECHNICIAN_ID = "00000000-0000-4000-8000-000000000053"
FABRICATED_TEMPLATE_ID = "00000000-0000-4000-8000-000000000054"
FABRICATED_INSPECTION_ID = "00000000-0000-4000-8000-000000000055"
FABRICATED_CLAIM_ID = "00000000-0000-4000-8000-000000000056"
FABRICATED_DEALER_ID = "00000000-0000-4000-8000-000000000058"


def _repairs_pending(api, items, rows):
    """Drive one inspection to `RECONDITIONING_REQUIRED` with its repairs generated."""
    program = bootstrap_program(api, items=items)
    walk = open_inspection_for(api, program)
    record_results(api, walk.inspection_id, program.technician_headers, rows)
    walk.inspection = submit_inspection(api, walk.inspection_id, program.dealer_headers)
    return program, walk


def _two_repairable_failures(api):
    """A brake point and a tire point both failed, so two repairs are outstanding."""
    items = [item_p1_payload(), item_b1_payload(), item_t1_payload()]
    rows = [
        result_row("P1", "PASS"),
        result_row("B1", "FAIL", 2.0),
        result_row("T1", "FAIL"),
    ]
    return _repairs_pending(api, items, rows)


def _one_repairable_failure(api):
    """A single failed brake point, curable by repair."""
    items = [item_p1_payload(), item_b1_payload()]
    rows = [result_row("P1", "PASS"), result_row("B1", "FAIL", 2.0)]
    return _repairs_pending(api, items, rows)


def test_each_role_performs_the_write_its_own_charter_gives_it(api, program):
    """The whole spine walks through once, each hop written by the role that owns it.

    PRD §3.2: "Vehicles are registered by a `ProgramAdministrator` or a `DealerPrincipal`"
    PRD §3.3: "Only a `DealerPrincipal` may open an inspection"
    PRD §3.4: "any other technician is turned away with `ERR_DEALER_SCOPE_VIOLATION`"
    PRD §3.5: "every repair is closed, the inspection reaches `PASSED`"
    PRD §3.6: "A successful submission creates the certification in `SUBMITTED`"
    PRD §3.7: "moves `SUBMITTED → ACTIVE`; and sets `activated_at` to the logical clock."
    PRD §3.10: "returns a summary object rather than an entity"
    PRD §3.10: "so the first run is `AR-1`"
    PRD §3.10: "The certification itself moves `ACTIVE → UNDER_AUDIT`"
    PRD §3.11: "A new complaint is created in `OPEN` with `filed_at` set to the logical clock"
    PRD §3.4: "that stamped technician identifier always equals the inspection's `technician_id`"
    PRD §2.6: "A `ProgramAdministrator` retunes the programme"
    PRD §2.4: "increments by exactly 1 on every mutation of the row"

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations
    """
    vehicle = get_success_data(
        api.create_vehicle(
            create_vehicle_payload(vin=unique_vin()), program.dealer_headers
        ),
        expected_status=201,
    )

    inspection = get_success_data(
        api.create_inspection(
            create_inspection_payload(
                vehicle["id"],
                program.technician_id,
                program.template_id,
                started_at=program.next_start(),
            ),
            program.dealer_headers,
        ),
        expected_status=201,
    )
    assert inspection["dealer_id"] == program.dealer_id
    assert inspection["technician_id"] == program.technician_id
    assert inspection["status"] == "DRAFT"

    validate_success(
        api.record_results(
            inspection["id"],
            results_payload(clean_attempt_rows()),
            program.technician_headers,
        )
    )
    rows, meta = validate_paginated(api.list_results(inspection["id"], ADMIN))
    assert meta["total_count"] == 3
    assert {row["attempt_index"] for row in rows} == {1}
    assert {row["recorded_by_technician_id"] for row in rows} == {
        program.technician_id
    }

    closed = validate_success(api.submit_inspection(inspection["id"], program.dealer_headers))
    assert closed["status"] == "PASSED"
    assert closed["recorded_item_count"] == 3

    certification = get_success_data(
        api.create_certification(
            create_certification_payload(
                vehicle["id"],
                inspection["id"],
                vehicle_version(api, vehicle["id"], program.dealer_headers),
            ),
            program.dealer_headers,
        ),
        expected_status=201,
    )
    assert certification["status"] == "SUBMITTED"
    assert certification["dealer_id"] == program.dealer_id
    assert_certification_number(
        certification["certification_number"], program.dealer["franchise_code"], 1
    )

    approved = validate_success(
        api.adjudicate_certification(
            certification["id"], adjudication_payload("APPROVE"), ADMIN
        )
    )
    assert approved["status"] == "ACTIVE"
    assert_instant_equals(approved["activated_at"], CLOCK_EPOCH, "activated_at")

    complaint = get_success_data(
        api.create_complaint(create_complaint_payload(certification["id"]), ADVOCATE),
        expected_status=201,
    )
    assert_complaint(complaint)
    assert complaint["status"] == "OPEN"
    assert complaint["certification_id"] == certification["id"]
    assert_instant_equals(complaint["filed_at"], CLOCK_EPOCH, "filed_at")
    assert_instant_equals(
        complaint["reinspection_deadline_at"],
        iso_shift(CLOCK_EPOCH, days=5),
        "reinspection_deadline_at",
    )

    run = get_success_data(api.create_audit_run(AUDITOR), expected_status=201)
    assert_audit_run_summary(run)
    assert run["audit_run_id"] == "AR-1"
    assert run["pool_size"] == 1
    assert run["selected_count"] == 1
    assert run["selected_certification_ids"] == [certification["id"]]
    audited = read_certification(api, certification["id"], ADMIN)
    assert audited["status"] == "UNDER_AUDIT"
    assert audited["audit_sampled"] is True

    before = read_config(api, ADMIN)
    retuned = validate_success(
        api.update_program_config(
            program_config_payload(audit_sample_min_per_run=1), ADMIN
        )
    )
    assert_program_config(retuned)
    assert retuned["audit_sample_min_per_run"] == 1
    assert retuned["version"] == before["version"] + 1


def test_each_role_is_refused_the_operation_another_role_owns(api):
    """Seven writes, seven wrong roles, and the role gate answers before existence does.

    PRD §2.1: "the rejection is `ERR_ROLE_FORBIDDEN` (HTTP 403)"
    PRD §2.1: "it deliberately cannot draw audit samples or rule on them"
    PRD §2.1: "it deliberately cannot approve the certifications it audits"
    PRD §2.1: "it can neither open, submit, nor certify"
    PRD §2.1: "it can neither inspect, certify, adjudicate, nor audit"
    PRD §2.10: "Role authorisation, including the variant-scoped exclusivity"
    PRD §2.10: "Identity resolution for entity-backed roles"
    PRD §2.10: "Existence of every resource named by a path segment, checked left to right"

    Design: Corner/rbac/no_role_can_perform_another_roles_exclusive_operation_forbidden
    """
    before = read_config(api, ADMIN)

    validate_error(
        api.update_program_config(program_config_payload(base_fee_cents=1), ADVOCATE),
        ApiErrorId.ERR_ROLE_FORBIDDEN,
    )
    validate_error(api.create_audit_run(ADMIN), ApiErrorId.ERR_ROLE_FORBIDDEN)
    validate_error(
        api.adjudicate_certification(
            FABRICATED_CERTIFICATION_ID, adjudication_payload("APPROVE"), AUDITOR
        ),
        ApiErrorId.ERR_ROLE_FORBIDDEN,
    )
    validate_error(
        api.create_inspection(
            create_inspection_payload(
                FABRICATED_VEHICLE_ID,
                FABRICATED_TECHNICIAN_ID,
                FABRICATED_TEMPLATE_ID,
                odometer_at_inspection=1000,
            ),
            make_inspection_technician_headers(FABRICATED_TECHNICIAN_ID),
        ),
        ApiErrorId.ERR_ROLE_FORBIDDEN,
    )
    validate_error(
        api.record_results(
            FABRICATED_INSPECTION_ID,
            results_payload([result_row("P1", "PASS")]),
            ADMIN,
        ),
        ApiErrorId.ERR_ROLE_FORBIDDEN,
    )
    validate_error(
        api.create_complaint(
            create_complaint_payload(
                FABRICATED_CERTIFICATION_ID, category="WARRANTY_DENIAL"
            ),
            AUDITOR,
        ),
        ApiErrorId.ERR_ROLE_FORBIDDEN,
    )
    validate_error(
        api.adjudicate_warranty_claim(
            FABRICATED_CLAIM_ID,
            claim_adjudication_payload("APPROVE"),
            make_dealer_principal_headers(FABRICATED_DEALER_ID),
        ),
        ApiErrorId.ERR_ROLE_FORBIDDEN,
    )

    after = read_config(api, ADMIN)
    assert after == before, (
        "a refused retune publishes no generation and moves no tunable"
    )
    validate_error(
        api.get_inspection(FABRICATED_INSPECTION_ID, ADMIN),
        ApiErrorId.ERR_INSPECTION_NOT_FOUND,
    )


def test_a_role_refused_a_write_keeps_the_read_it_declares(api):
    """The advocate that cannot retune the programme still reads the live generation.

    PRD §2.6: "All five roles may read the live configuration, including its `version`"
    PRD §2.6: "A `ProgramAdministrator` retunes the programme"

    Design: Corner/rbac/no_role_can_perform_another_roles_exclusive_operation_forbidden
    """
    validate_error(
        api.update_program_config(program_config_payload(base_fee_cents=1), ADVOCATE),
        ApiErrorId.ERR_ROLE_FORBIDDEN,
    )
    advocate_view = validate_success(api.get_program_config(ADVOCATE))
    assert_program_config(advocate_view)
    assert advocate_view == validate_success(api.get_program_config(ADMIN)), (
        "the configuration read is not degraded for the role that cannot write it"
    )


def test_a_technician_may_not_waive_and_an_administrator_may_not_complete(api):
    """Both roles are on the endpoint, and each is refused the other's resolution.

    PRD §2.1: "a `resolution` of `WAIVED` is `ProgramAdministrator`-exclusive"
    PRD §3.5: "A `resolution` of `COMPLETED` is performed by an `InspectionTechnician`"
    PRD §3.5: "a `resolution` of `WAIVED` is performed by a `ProgramAdministrator`"
    PRD §2.4: "increments by exactly 1 on every mutation of the row"

    Design: Corner/rbac/variant_scoped_exclusive_resolution_on_reconditioning_close_forbidden
    """
    program, walk = _two_repairable_failures(api)
    assert walk.inspection["status"] == "RECONDITIONING_REQUIRED"
    brake_repair = reconditioning_item_for(api, walk.inspection_id, "B1")

    validate_error(
        api.complete_reconditioning_item(
            brake_repair["id"],
            waive_reconditioning_payload("brake wear acceptable for the region"),
            program.other_technician_headers,
        ),
        ApiErrorId.ERR_ROLE_FORBIDDEN,
    )
    validate_error(
        api.complete_reconditioning_item(
            brake_repair["id"], complete_reconditioning_payload(50000), ADMIN
        ),
        ApiErrorId.ERR_ROLE_FORBIDDEN,
    )

    reread = reconditioning_item_for(api, walk.inspection_id, "B1")
    assert_reconditioning_item(reread)
    assert reread["status"] == "REQUIRED"
    assert reread["actual_cost_cents"] is None
    assert reread["waiver_reason"] is None
    assert reread["completed_at"] is None
    assert reread["closed_by_user_id"] is None
    assert reread["version"] == brake_repair["version"], (
        "neither refusal mutates the row it targeted"
    )
    assert read_inspection(api, walk.inspection_id)["total_reimbursable_cents"] == 0


def test_the_two_resolutions_land_when_each_is_asked_by_its_owning_role(api):
    """One repair completed by a technician, one waived by the administrator.

    PRD §3.5: "round that product half up to whole cents"
    PRD §3.5: "A waived item keeps `actual_cost_cents` null and `reimbursable_cents` 0."
    PRD §3.5: "Waived repairs contribute nothing and never enter the sum"
    PRD §2.1: "the `closed_by_user_id` stamped on a reconditioning item excused by waiver"

    Design: Corner/rbac/variant_scoped_exclusive_resolution_on_reconditioning_close_forbidden
    """
    program, walk = _two_repairable_failures(api)
    brake_repair = reconditioning_item_for(api, walk.inspection_id, "B1")
    tire_repair = reconditioning_item_for(api, walk.inspection_id, "T1")

    completed = validate_success(
        api.complete_reconditioning_item(
            brake_repair["id"],
            complete_reconditioning_payload(50000),
            program.other_technician_headers,
        )
    )
    assert completed["status"] == "COMPLETED"
    assert completed["actual_cost_cents"] == 50000
    assert completed["reimbursable_cents"] == reimbursable_for(50000, 100000) == 30000
    assert completed["closed_by_user_id"] == program.other_technician_id
    assert_instant_equals(completed["completed_at"], CLOCK_EPOCH, "completed_at")

    waived = validate_success(
        api.complete_reconditioning_item(
            tire_repair["id"],
            waive_reconditioning_payload("tire wear within regional tolerance"),
            ADMIN,
        )
    )
    assert waived["status"] == "WAIVED"
    assert waived["actual_cost_cents"] is None
    assert waived["reimbursable_cents"] == 0
    assert waived["waiver_reason"] == "tire wear within regional tolerance"
    assert waived["closed_by_user_id"] == ADMIN_USER_ID

    rows = {row["item_code"]: row for row in reconditioning_items(api, walk.inspection_id)}
    assert rows["B1"]["status"] == "COMPLETED"
    assert rows["T1"]["status"] == "WAIVED"
    assert rows["B1"]["closed_by_user_id"] != rows["T1"]["closed_by_user_id"]

    inspection = read_inspection(api, walk.inspection_id)
    assert inspection["total_recon_cost_cents"] == 50000
    assert inspection["total_reimbursable_cents"] == 30000


def test_the_inspections_own_technician_cannot_sign_off_its_own_repair(api):
    """Same role, same endpoint, same resolution — only the acting identity differs.

    PRD §3.5: "A self-signoff is rejected with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §2.10: "Segregation of duties — otherwise `ERR_SEGREGATION_OF_DUTIES`."
    PRD §2.4: "increments by exactly 1 on every mutation of the row"

    Design: Corner/rbac/segregation_of_duties_blocks_the_inspections_own_technician_forbidden
    """
    program, walk = _one_repairable_failure(api)
    assert walk.inspection["status"] == "RECONDITIONING_REQUIRED"
    repair = reconditioning_item_for(api, walk.inspection_id, "B1")

    validate_error(
        api.complete_reconditioning_item(
            repair["id"],
            complete_reconditioning_payload(40000),
            program.technician_headers,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )

    reread = reconditioning_item_for(api, walk.inspection_id, "B1")
    assert reread["status"] == "REQUIRED"
    assert reread["actual_cost_cents"] is None
    assert reread["completed_at"] is None
    assert reread["closed_by_user_id"] is None
    assert reread["version"] == repair["version"]
    assert read_inspection(api, walk.inspection_id)["status"] == "RECONDITIONING_REQUIRED"


def test_an_outstanding_repair_holds_the_inspection_open_until_a_peer_closes_it(api):
    """The blocked repair keeps a clean attempt from passing, and closes only once.

    PRD §3.5: "closing is rejected with `ERR_RECONDITIONING_INCOMPLETE`"
    PRD §3.5: "closing an item already `COMPLETED` or `WAIVED` is `ERR_RECONDITIONING_ITEM_CLOSED`"
    PRD §3.5: "every repair is closed, the inspection reaches `PASSED`"
    PRD §2.10: "the target resource is in a state from which the requested transition is declared"

    Design: Corner/rbac/segregation_of_duties_blocks_the_inspections_own_technician_forbidden
    """
    program, walk = _one_repairable_failure(api)
    repair = reconditioning_item_for(api, walk.inspection_id, "B1")

    repaired_rows = [result_row("P1", "PASS"), result_row("B1", "PASS", 8.0)]
    record_results(api, walk.inspection_id, program.technician_headers, repaired_rows)
    assert read_inspection(api, walk.inspection_id)["status"] == "IN_PROGRESS"

    validate_error(
        api.submit_inspection(walk.inspection_id, program.dealer_headers),
        ApiErrorId.ERR_RECONDITIONING_INCOMPLETE,
    )
    assert read_inspection(api, walk.inspection_id)["status"] == "IN_PROGRESS"

    completed = validate_success(
        api.complete_reconditioning_item(
            repair["id"],
            complete_reconditioning_payload(40000),
            program.other_technician_headers,
        )
    )
    assert completed["status"] == "COMPLETED"
    assert completed["reimbursable_cents"] == reimbursable_for(40000, 100000) == 24000
    assert completed["closed_by_user_id"] == program.other_technician_id

    validate_error(
        api.complete_reconditioning_item(
            repair["id"],
            complete_reconditioning_payload(40000),
            program.other_technician_headers,
        ),
        ApiErrorId.ERR_RECONDITIONING_ITEM_CLOSED,
    )

    passed = validate_success(
        api.submit_inspection(walk.inspection_id, program.dealer_headers)
    )
    assert passed["status"] == "PASSED"
    assert passed["total_recon_cost_cents"] == 40000
    assert passed["total_reimbursable_cents"] == 24000


def test_a_peer_dealer_is_refused_every_record_of_another_dealership(api, program, peer_program):
    """Two dealerships hold the identical role, so only the acting identity separates them.

    PRD §2.1: "the rejection is `ERR_DEALER_SCOPE_VIOLATION`"
    PRD §2.1: "every one of its writes is scoped to its own dealership"
    PRD §2.1: "the request is rejected with `ERR_IDENTITY_NOT_RECOGNIZED` (HTTP 403)"
    PRD §3.4: "any other technician is turned away with `ERR_DEALER_SCOPE_VIOLATION`"
    PRD §2.10: "Identity resolution for entity-backed roles"
    PRD §2.10: "Dealer-scope ownership — otherwise `ERR_DEALER_SCOPE_VIOLATION`."
    PRD §2.6: "All five roles may read the live configuration, including its `version`"

    Design: Corner/rbac/peer_dealers_cannot_touch_each_others_records_forbidden
    """
    walk = open_inspection_for(api, program)
    peer_vehicle = create_vehicle(api)

    validate_error(
        api.create_inspection(
            create_inspection_payload(
                peer_vehicle["id"],
                program.technician_id,
                program.template_id,
                started_at=program.next_start(),
            ),
            peer_program.dealer_headers,
        ),
        ApiErrorId.ERR_DEALER_SCOPE_VIOLATION,
    )
    validate_error(
        api.record_results(
            walk.inspection_id,
            results_payload(clean_attempt_rows()),
            peer_program.technician_headers,
        ),
        ApiErrorId.ERR_DEALER_SCOPE_VIOLATION,
    )
    validate_error(
        api.get_inspection(walk.inspection_id, peer_program.dealer_headers),
        ApiErrorId.ERR_DEALER_SCOPE_VIOLATION,
    )
    validate_error(
        api.submit_inspection(walk.inspection_id, peer_program.dealer_headers),
        ApiErrorId.ERR_DEALER_SCOPE_VIOLATION,
    )
    validate_error(
        api.record_results(
            walk.inspection_id,
            results_payload(clean_attempt_rows()),
            make_inspection_technician_headers(UNRESOLVABLE_ENTITY_ID),
        ),
        ApiErrorId.ERR_IDENTITY_NOT_RECOGNIZED,
    )

    peer_config = validate_success(api.get_program_config(peer_program.dealer_headers))
    assert peer_config == validate_success(api.get_program_config(ADMIN)), (
        "the shared configuration read reaches the peer dealer unchanged"
    )

    validate_success(
        api.record_results(
            walk.inspection_id,
            results_payload(clean_attempt_rows()),
            program.technician_headers,
        )
    )
    owner_view = validate_success(
        api.get_inspection(walk.inspection_id, program.dealer_headers)
    )
    assert owner_view["status"] == "IN_PROGRESS"
    assert owner_view["recorded_item_count"] == 3
    assert owner_view["attempt_count"] == 1
    assert owner_view["dealer_id"] == program.dealer_id


def test_credential_uniqueness_is_scoped_to_the_employing_dealer(api, program, peer_program):
    """Two dealerships may issue the same credential number to their own inspectors.

    PRD §3.2: "must be unique within the employing dealer"
    PRD §3.2: "A technician's `dealer_id` is taken from the path segment naming the employer"

    Design: Corner/rbac/peer_dealers_cannot_touch_each_others_records_forbidden
    """
    shared_credential = program.technician["credential_id"]
    twin = create_technician(
        api,
        peer_program.dealer_id,
        name="Ben Tech",
        credential_id=shared_credential,
    )
    assert twin["credential_id"] == shared_credential
    assert twin["dealer_id"] == peer_program.dealer_id
    assert twin["id"] != program.technician_id
    assert twin["completed_inspection_count"] == 0


def test_shared_reads_return_the_same_resource_to_every_role_that_declares_them(
    api, program, vehicle
):
    """The shared surface is not uniform, and no role on it gets a degraded view.

    PRD §2.6: "All five roles may read the live configuration, including its `version`"
    PRD §3.1: "the single-template read and the point listing are open to a `ProgramAdministrator`"
    PRD §3.1: "a `DealerPrincipal`, and an `InspectionTechnician`"
    PRD §4: "ProgramAdministrator, ProgramAuditor, DealerPrincipal, CustomerAdvocate |"
    PRD §4: "ProgramAdministrator, ProgramAuditor, DealerPrincipal |"
    PRD §3.2: "A newly enrolled dealer begins with `privilege_status` of `ACTIVE`"

    Design: Corner/rbac/shared_reads_are_available_to_every_role_that_declares_them
    """
    admin_config = validate_success(api.get_program_config(ADMIN))
    for headers in (program.technician_headers, ADVOCATE):
        view = validate_success(api.get_program_config(headers))
        assert_program_config(view)
        assert view == admin_config

    admin_vehicle = validate_success(api.get_vehicle(vehicle["id"], ADMIN))
    for headers in (ADVOCATE, AUDITOR, program.dealer_headers):
        view = validate_success(api.get_vehicle(vehicle["id"], headers))
        assert_vehicle(view)
        assert view == admin_vehicle

    admin_items, admin_meta = validate_paginated(
        api.list_checklist_items(program.template_id, ADMIN)
    )
    technician_items, technician_meta = validate_paginated(
        api.list_checklist_items(program.template_id, program.technician_headers)
    )
    assert technician_items == admin_items
    assert technician_meta["total_count"] == admin_meta["total_count"] == 3

    auditor_template = validate_success(
        api.get_checklist_template(program.template_id, AUDITOR)
    )
    assert_checklist_template(auditor_template)
    assert auditor_template == validate_success(
        api.get_checklist_template(program.template_id, ADMIN)
    )

    auditor_roster, roster_meta = validate_paginated(
        api.list_technicians(program.dealer_id, AUDITOR)
    )
    admin_roster, _ = validate_paginated(api.list_technicians(program.dealer_id, ADMIN))
    assert auditor_roster == admin_roster
    assert roster_meta["total_count"] == 2
    assert {row["id"] for row in auditor_roster} == {
        program.technician_id,
        program.other_technician_id,
    }

    own_row = validate_success(api.get_dealer(program.dealer_id, program.dealer_headers))
    assert_dealer(own_row)
    assert own_row["privilege_status"] == "ACTIVE"
    assert own_row["privilege_reason"] is None
    assert own_row["lifetime_activated_count"] == 0
    assert own_row == read_dealer(api, program.dealer_id, ADMIN)


def test_a_shared_read_stays_closed_to_a_role_outside_its_list(api, program, vehicle):
    """Shared does not mean open to everyone: each read keeps its own declared list.

    PRD §2.1: "the rejection is `ERR_ROLE_FORBIDDEN` (HTTP 403)"
    PRD §3.1: "a `DealerPrincipal`, and an `InspectionTechnician`"
    PRD §4: "ProgramAdministrator, ProgramAuditor, DealerPrincipal, CustomerAdvocate |"
    PRD §4: "ProgramAdministrator, ProgramAuditor, DealerPrincipal |"

    Design: Corner/rbac/shared_reads_are_available_to_every_role_that_declares_them
    """
    validate_error(
        api.get_vehicle(vehicle["id"], program.technician_headers),
        ApiErrorId.ERR_ROLE_FORBIDDEN,
    )
    validate_error(
        api.get_checklist_template(program.template_id, ADVOCATE),
        ApiErrorId.ERR_ROLE_FORBIDDEN,
    )
    validate_error(
        api.list_checklist_items(program.template_id, ADVOCATE),
        ApiErrorId.ERR_ROLE_FORBIDDEN,
    )
    validate_error(
        api.get_dealer(program.dealer_id, ADVOCATE), ApiErrorId.ERR_ROLE_FORBIDDEN
    )
    validate_error(
        api.list_technicians(program.dealer_id, ADVOCATE),
        ApiErrorId.ERR_ROLE_FORBIDDEN,
    )
    assert_vehicle(validate_success(api.get_vehicle(vehicle["id"], ADVOCATE)))
    assert_checklist_template(
        validate_success(
            api.get_checklist_template(program.template_id, program.technician_headers)
        )
    )

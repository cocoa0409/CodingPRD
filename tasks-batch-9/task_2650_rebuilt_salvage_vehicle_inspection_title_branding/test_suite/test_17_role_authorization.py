"""Role authority over the program's writes, and the segregation-of-duties pairs.

Every request names the role it acts in, and each of the seven roles owns a
specific slice of the program's writes: the administrator stands the registry up
and polices licences, the title clerk registers vehicles and mints instruments,
the carrier's adjuster files the total-loss evaluation, the rebuilder assembles
its own application, the inspector adjudicates evidence and the attempt, and the
fraud unit takes referrals up. These tests prove each role's own writes are
admitted, that a role outside an endpoint's declared audience is refused before
anything else about the request is examined, and that two review chains refuse
the principal who already took the incompatible earlier step.
"""

import pytest

from test_helpers import (
    ADMIN_USER_ID,
    CLERK_USER_ID,
    FRAUD_INVESTIGATOR_USER_ID,
    NON_EXISTENT_UUID,
    SECOND_ADMIN_USER_ID,
    create_damage_report_payload,
    create_deposit_payload,
    create_fraud_referral_payload,
    create_inspection_station_payload,
    create_inspector_payload,
    create_license_action_payload,
    create_parts_document_payload,
    create_rebuilder_payload,
    create_title_record_payload,
    create_vehicle_payload,
    decide_appeal_payload,
    get_success_data,
    headers_for_role,
    investigate_referral_payload,
    make_fraud_investigator_headers,
    make_inspector_headers,
    make_program_admin_headers,
    make_rebuilder_headers,
    make_state_title_clerk_headers,
    resolve_referral_payload,
    schedule_inspection_payload,
    set_clock_payload,
    start_inspection_payload,
    submit_application_payload,
    validate_error,
    validate_paginated,
    validate_success,
    verify_parts_document_payload,
)
from test_helpers import api_client as api
from test_helpers import create_appeal_payload, create_application_payload
from test_helpers.fixtures import (
    commission_inspector,
    file_damage_report,
    license_rebuilder,
    read_application,
    read_fee_quote,
    read_inspector,
    read_rebuilder,
    read_vehicle,
    register_vehicle,
    setup_draft_application,
    setup_failed_application,
    setup_program_actors,
    setup_salvage_titled_vehicle,
    take_license_action,
)

# ---------------------------------------------------------------------------
# the administrator's own exclusive writes
# ---------------------------------------------------------------------------


def _license_a_rebuilder(headers):
    return api.create_rebuilder(create_rebuilder_payload(), headers)


def _commission_an_inspector(headers):
    return api.create_inspector(create_inspector_payload(), headers)


def _open_an_inspection_station(headers):
    return api.create_inspection_station(create_inspection_station_payload(), headers)


def _credit_a_fee_deposit(headers):
    rebuilder = license_rebuilder()
    return api.create_deposit(rebuilder["id"], create_deposit_payload(), headers)


def _take_a_licence_action(headers):
    rebuilder = license_rebuilder()
    return api.create_license_action(
        rebuilder["id"], create_license_action_payload("PROBATION"), headers
    )


def _drive_the_logical_clock(headers):
    return api.set_clock(set_clock_payload("2026-08-05T00:00:00Z"), headers)


ADMIN_EXCLUSIVE_WRITES = [
    ("license_a_rebuilder", _license_a_rebuilder),
    ("commission_an_inspector", _commission_an_inspector),
    ("open_an_inspection_station", _open_an_inspection_station),
    ("credit_a_fee_deposit", _credit_a_fee_deposit),
    ("take_a_licence_action", _take_a_licence_action),
    ("drive_the_logical_clock", _drive_the_logical_clock),
]


@pytest.mark.parametrize(
    "label,perform",
    ADMIN_EXCLUSIVE_WRITES,
    ids=[label for label, _ in ADMIN_EXCLUSIVE_WRITES],
)
def test_program_administrator_performs_each_of_its_own_writes(label, perform):
    """Each write the program administrator owns is admitted for the ProgramAdmin role.

    PRD: "Administrators license rebuilders and commission inspectors, open inspection stations, credit fee deposits, take licence actions, decide interstate recognition requests, and drive the logical clock."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_write
    """
    response = perform(make_program_admin_headers(ADMIN_USER_ID))
    assert response.status_code in (200, 201), (
        f"the administrator's own write {label} must be admitted, "
        f"got HTTP {response.status_code}: {response.text}"
    )
    data = get_success_data(response)
    assert isinstance(data, dict), f"{label} must answer with a resource object"


def test_title_clerk_registers_the_vehicle_and_mints_its_branded_title():
    """The title clerk registers a vehicle and mints the instrument the carrier's evaluation brands.

    PRD: "A `StateTitleClerk` staffs the title office: clerks register vehicles, issue and surrender titles, review documentation packages, schedule and cancel inspection attempts, record conveyances, submit titles for interstate recognition, and may file fraud referrals."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_write
    """
    clerk = make_state_title_clerk_headers(CLERK_USER_ID)

    vehicle = validate_success(api.create_vehicle(create_vehicle_payload(), clerk), 201)
    report = file_damage_report(vehicle["id"])

    title = validate_success(
        api.create_title_record(
            create_title_record_payload(
                vehicle["id"], source_damage_report_id=report["id"]
            ),
            clerk,
        ),
        201,
    )
    assert title["vehicle_id"] == vehicle["id"], (
        f"the minted title must cover {vehicle['id']}, got {title['vehicle_id']}"
    )
    assert title["brand_code"] == report["recommended_brand_code"], (
        f"expected brand {report['recommended_brand_code']}, got {title['brand_code']}"
    )


def test_insurer_adjuster_files_the_total_loss_evaluation():
    """The carrier's adjuster files the evaluation whose damage ratio triggers the brand.

    PRD: "An `InsurerAdjuster` files the total-loss damage evaluation whose damage ratio triggers the salvage brand, and does nothing else."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_write
    """
    vehicle = register_vehicle()

    report = validate_success(
        api.create_damage_report(
            create_damage_report_payload(
                vehicle["id"], acv_cents=1_000_000, repair_estimate_cents=800_000
            ),
            headers_for_role("InsurerAdjuster"),
        ),
        201,
    )
    assert report["recommended_brand_code"] == "SALVAGE", (
        "a ratio of 0.8000 sits at or above the salvage threshold, "
        f"got recommendation {report['recommended_brand_code']}"
    )


def test_rebuilder_opens_its_own_application_and_files_the_parts_record():
    """The rebuilder opens an application on its own behalf and files its parts paperwork.

    PRD: "A `Rebuilder` is a licensed repair business: rebuilders open applications, file parts documentation and photographs, submit for inspection, withdraw, and appeal failures, and may act only on their own applications."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_write
    """
    actors = setup_program_actors()
    branded = setup_salvage_titled_vehicle(body_class="TRAILER")
    rebuilder_headers = make_rebuilder_headers(actors["rebuilder_id"])

    application = validate_success(
        api.create_application(
            create_application_payload(
                branded["vehicle_id"],
                actors["rebuilder_id"],
                branded["salvage_title_id"],
                declared_repair_cost_cents=320_000,
            ),
            rebuilder_headers,
        ),
        201,
    )
    assert application["rebuilder_id"] == actors["rebuilder_id"], (
        f"expected the acting rebuilder {actors['rebuilder_id']}, "
        f"got {application['rebuilder_id']}"
    )
    assert application["status"] == "DRAFT", (
        f"a newly opened application begins in DRAFT, got {application['status']}"
    )

    document = validate_success(
        api.create_parts_document(
            application["id"],
            create_parts_document_payload(part_class="LIGHTING", amount_cents=20_000),
            rebuilder_headers,
        ),
        201,
    )
    assert document["application_id"] == application["id"], (
        f"the filed document must attach to {application['id']}, "
        f"got {document['application_id']}"
    )


def test_inspector_verifies_the_parts_document_it_adjudicates():
    """The inspector accepts a filed parts document and is stamped on it as the verifier.

    PRD: "A successful verification records `verified_by_inspector_id` as the acting inspector's `X-User-ID`, adds the document's `amount_cents` to the application's `documented_parts_cost_cents`, and recomputes the application's `documentation_completeness_pct` and — once the application has been submitted — its `assessed_fee_cents`."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_write
    """
    env = setup_draft_application()
    document = get_success_data(
        api.create_parts_document(
            env["application_id"],
            create_parts_document_payload(part_class="STRUCTURAL", amount_cents=200_000),
            make_rebuilder_headers(env["rebuilder_id"]),
        )
    )

    verified = get_success_data(
        api.verify_parts_document(
            document["id"],
            verify_parts_document_payload(),
            make_inspector_headers(env["inspector_id"]),
        )
    )
    assert verified["status"] == "VERIFIED", (
        f"expected VERIFIED after the inspector accepted it, got {verified['status']}"
    )
    assert verified["verified_by_inspector_id"] == env["inspector_id"], (
        f"expected verifier {env['inspector_id']}, "
        f"got {verified['verified_by_inspector_id']}"
    )


def test_fraud_investigator_takes_up_the_referral_the_clerk_filed():
    """The fraud unit takes up an open referral and is recorded as its investigator.

    PRD: "That move is admissible only from `OPEN` and lands the referral in `INVESTIGATING`, recording the investigator's `X-User-ID` as `investigator_user_id`."

    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_write
    """
    vehicle = register_vehicle()
    referral = validate_success(
        api.create_fraud_referral(
            create_fraud_referral_payload(vehicle["id"], referral_type="DOCUMENT_FORGERY"),
            make_state_title_clerk_headers(CLERK_USER_ID),
        ),
        201,
    )

    investigating = get_success_data(
        api.investigate_fraud_referral(
            referral["id"],
            investigate_referral_payload(),
            make_fraud_investigator_headers(FRAUD_INVESTIGATOR_USER_ID),
        )
    )
    assert investigating["status"] == "INVESTIGATING", (
        f"expected INVESTIGATING after take-up, got {investigating['status']}"
    )
    assert investigating["investigator_user_id"] == FRAUD_INVESTIGATOR_USER_ID, (
        f"expected investigator {FRAUD_INVESTIGATOR_USER_ID}, "
        f"got {investigating['investigator_user_id']}"
    )
    assert investigating["opened_by_user_id"] == CLERK_USER_ID, (
        "the referral keeps the clerk who raised it as its opener, "
        f"got {investigating['opened_by_user_id']}"
    )


# ---------------------------------------------------------------------------
# a role outside the endpoint's declared audience
# ---------------------------------------------------------------------------

FORBIDDEN_WRITES = [
    (
        "hearing_officer_registers_a_vehicle",
        lambda: api.create_vehicle(
            create_vehicle_payload(), headers_for_role("HearingOfficer")
        ),
    ),
    (
        "title_clerk_files_the_carrier_evaluation",
        lambda: api.create_damage_report(
            create_damage_report_payload(NON_EXISTENT_UUID),
            headers_for_role("StateTitleClerk"),
        ),
    ),
    (
        "title_clerk_submits_an_application",
        lambda: api.submit_application(
            NON_EXISTENT_UUID,
            submit_application_payload(),
            headers_for_role("StateTitleClerk"),
        ),
    ),
    (
        "administrator_starts_an_attempt",
        lambda: api.start_inspection(
            NON_EXISTENT_UUID,
            start_inspection_payload(),
            headers_for_role("ProgramAdmin"),
        ),
    ),
    (
        "administrator_decides_an_appeal",
        lambda: api.decide_appeal(
            NON_EXISTENT_UUID,
            decide_appeal_payload("GRANT"),
            headers_for_role("ProgramAdmin"),
        ),
    ),
    (
        "hearing_officer_resolves_a_referral",
        lambda: api.resolve_fraud_referral(
            NON_EXISTENT_UUID,
            resolve_referral_payload("SUBSTANTIATED"),
            headers_for_role("HearingOfficer"),
        ),
    ),
]


@pytest.mark.parametrize(
    "label,attempt",
    FORBIDDEN_WRITES,
    ids=[label for label, _ in FORBIDDEN_WRITES],
)
def test_role_outside_the_endpoints_audience_is_refused(label, attempt):
    """A write attempted by a role the endpoint does not authorise is refused outright.

    PRD: "When both headers are well formed but the named role is not among the roles authorised for the endpoint being called (see the endpoint table in §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/every_role_outside_the_declared_list_is_forbidden
    """
    response = attempt()
    validate_error(response, "ERR_ROLE_NOT_PERMITTED")
    assert response.status_code == 403, (
        f"{label} must be refused with HTTP 403, got {response.status_code}"
    )


def test_role_refusal_precedes_the_unresolvable_path_segment():
    """An unauthorised role hears about its role, not about the unknown resource in the path.

    PRD: "When both headers are well formed but the named role is not among the roles authorised for the endpoint being called (see the endpoint table in §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/every_role_outside_the_declared_list_is_forbidden
    """
    refusals = {
        "submit_an_application": api.submit_application(
            NON_EXISTENT_UUID,
            submit_application_payload(),
            headers_for_role("StateTitleClerk"),
        ),
        "start_an_attempt": api.start_inspection(
            NON_EXISTENT_UUID,
            start_inspection_payload(),
            headers_for_role("ProgramAdmin"),
        ),
        "resolve_a_referral": api.resolve_fraud_referral(
            NON_EXISTENT_UUID,
            resolve_referral_payload("SUBSTANTIATED"),
            headers_for_role("HearingOfficer"),
        ),
    }
    for label, response in refusals.items():
        validate_error(response, "ERR_ROLE_NOT_PERMITTED")
        assert response.status_code != 404, (
            f"{label} must not report the unresolvable path segment ahead of the role"
        )


def test_forbidden_write_leaves_no_row_behind():
    """A write refused for the acting role creates nothing the program can later read back.

    PRD: "When both headers are well formed but the named role is not among the roles authorised for the endpoint being called (see the endpoint table in §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/every_role_outside_the_declared_list_is_forbidden
    """
    vehicle = register_vehicle()
    admin = make_program_admin_headers(ADMIN_USER_ID)

    validate_error(
        api.create_damage_report(
            create_damage_report_payload(vehicle["id"]),
            headers_for_role("StateTitleClerk"),
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )
    validate_error(
        api.create_appeal(
            create_appeal_payload(NON_EXISTENT_UUID), headers_for_role("Inspector")
        ),
        "ERR_ROLE_NOT_PERMITTED",
    )

    reports, reports_meta = validate_paginated(api.list_damage_reports(admin))
    assert reports_meta["total_count"] == 0, (
        f"the refused evaluation must not have been filed, got {reports_meta['total_count']} rows"
    )
    assert reports == [], f"expected no damage report rows, got {reports}"

    appeals, appeals_meta = validate_paginated(api.list_appeals(admin))
    assert appeals_meta["total_count"] == 0, (
        f"the refused appeal must not have been created, got {appeals_meta['total_count']} rows"
    )


# ---------------------------------------------------------------------------
# who may originate a fraud referral
# ---------------------------------------------------------------------------


def test_fraud_investigator_may_not_open_the_referral_it_would_investigate():
    """The fraud unit cannot originate the case it is the only role allowed to close.

    PRD: "Either an `Inspector` or a `StateTitleClerk` may file a fraud referral, naming the `vehicle_id` whose identity or odometer is impeached, a `referral_type` drawn from `ODOMETER`, `IDENTITY_TAMPERING` and `DOCUMENT_FORGERY`, and an `evidence_summary` describing what supports the allegation."

    Design: Corner/rbac/fraud_investigator_cannot_open_the_referral_it_would_investigate
    """
    vehicle = register_vehicle()

    response = api.create_fraud_referral(
        create_fraud_referral_payload(vehicle["id"], referral_type="ODOMETER"),
        make_fraud_investigator_headers(FRAUD_INVESTIGATOR_USER_ID),
    )
    validate_error(response, "ERR_ROLE_NOT_PERMITTED")

    referrals, meta = validate_paginated(
        api.list_fraud_referrals(
            make_program_admin_headers(ADMIN_USER_ID), {"vehicle_id": vehicle["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"no referral may exist against {vehicle['id']}, got {meta['total_count']}"
    )
    assert referrals == [], f"expected no referral rows, got {referrals}"

    assert read_vehicle(vehicle["id"])["fraud_hold"] == "NONE", (
        "a refused filing must leave the vehicle's fraud posture at NONE"
    )


def test_inspector_and_title_clerk_each_open_a_referral_on_the_same_vehicle():
    """Both roles that may originate a referral do so on one vehicle, each keeping its own opener.

    PRD: "A manually filed referral gets `origin` of `MANUAL` and `status` of `OPEN`, records the acting `X-User-ID` as `opened_by_user_id`, and drives the vehicle's `fraud_hold` from `NONE` to `UNDER_REFERRAL`."

    Design: Corner/rbac/both_inspector_and_clerk_may_open_a_fraud_referral
    """
    vehicle = register_vehicle()
    inspector = commission_inspector()

    clerk_referral = validate_success(
        api.create_fraud_referral(
            create_fraud_referral_payload(vehicle["id"], referral_type="ODOMETER"),
            make_state_title_clerk_headers(CLERK_USER_ID),
        ),
        201,
    )
    inspector_referral = validate_success(
        api.create_fraud_referral(
            create_fraud_referral_payload(
                vehicle["id"], referral_type="IDENTITY_TAMPERING"
            ),
            make_inspector_headers(inspector["id"]),
        ),
        201,
    )

    assert clerk_referral["opened_by_user_id"] == CLERK_USER_ID, (
        f"expected opener {CLERK_USER_ID}, got {clerk_referral['opened_by_user_id']}"
    )
    assert clerk_referral["referral_type"] == "ODOMETER", (
        f"expected ODOMETER, got {clerk_referral['referral_type']}"
    )
    assert clerk_referral["status"] == "OPEN", (
        f"a manually filed referral starts OPEN, got {clerk_referral['status']}"
    )
    assert clerk_referral["origin"] == "MANUAL", (
        f"a manually filed referral has origin MANUAL, got {clerk_referral['origin']}"
    )

    assert inspector_referral["opened_by_user_id"] == inspector["id"], (
        f"expected opener {inspector['id']}, "
        f"got {inspector_referral['opened_by_user_id']}"
    )
    assert inspector_referral["referral_type"] == "IDENTITY_TAMPERING", (
        f"expected IDENTITY_TAMPERING, got {inspector_referral['referral_type']}"
    )
    assert inspector_referral["status"] == "OPEN", (
        f"a manually filed referral starts OPEN, got {inspector_referral['status']}"
    )

    _, meta = validate_paginated(
        api.list_fraud_referrals(
            make_program_admin_headers(ADMIN_USER_ID), {"vehicle_id": vehicle["id"]}
        )
    )
    assert meta["total_count"] == 2, (
        "the duplicate guard is keyed on the vehicle and the referral type together, "
        f"so both cases coexist; got {meta['total_count']} rows"
    )
    assert read_vehicle(vehicle["id"])["fraud_hold"] == "UNDER_REFERRAL", (
        "an open referral drives the vehicle's fraud posture to UNDER_REFERRAL"
    )


# ---------------------------------------------------------------------------
# segregation of duties: the licence chain and the re-inspection chain
# ---------------------------------------------------------------------------


def test_suspending_administrator_may_not_reinstate_the_licence():
    """The administrator who suspended a rebuilder's licence cannot lift its own suspension.

    PRD: "Second, a licence reinstatement may not be performed by the administrator recorded in the rebuilder's `suspended_by_user_id`; whoever suspended the licence may not lift the suspension."

    Design: Corner/rbac/reinstating_a_licence_by_the_suspending_admin_is_forbidden
    """
    rebuilder = license_rebuilder()
    suspended = take_license_action(
        rebuilder["id"], "SUSPEND", make_program_admin_headers(ADMIN_USER_ID)
    )
    assert suspended["license_status"] == "SUSPENDED", (
        f"expected SUSPENDED after the action, got {suspended['license_status']}"
    )
    assert suspended["suspended_by_user_id"] == ADMIN_USER_ID, (
        f"expected {ADMIN_USER_ID} recorded as the suspending administrator, "
        f"got {suspended['suspended_by_user_id']}"
    )

    response = api.create_license_action(
        rebuilder["id"],
        create_license_action_payload("REINSTATE"),
        make_program_admin_headers(ADMIN_USER_ID),
    )
    validate_error(response, "ERR_SEGREGATION_OF_DUTIES")

    after = read_rebuilder(rebuilder["id"])
    assert after["license_status"] == "SUSPENDED", (
        f"the refused reinstatement must leave the licence SUSPENDED, "
        f"got {after['license_status']}"
    )
    assert after["suspended_by_user_id"] == ADMIN_USER_ID, (
        f"expected {ADMIN_USER_ID} still recorded, got {after['suspended_by_user_id']}"
    )
    assert after["recordkeeping_score_rolling"] == pytest.approx(100.00, abs=0.01), (
        "a rebuilder with no parts documents on file scores the vacuous 100.00, "
        f"so the score was never the obstacle; got {after['recordkeeping_score_rolling']}"
    )


def test_a_second_administrator_reinstates_the_suspended_licence():
    """A different administrator clears the suspension the first one imposed.

    PRD: "An action of `REINSTATE` moves the licence `SUSPENDED → ACTIVE` and is doubly gated: the acting `X-User-ID` must differ from `suspended_by_user_id`, and the rebuilder's `recordkeeping_score_rolling` must be at least 60.00, or the request is refused with `ERR_RECORDKEEPING_SCORE_BLOCKS_ACTION` (HTTP 422)."

    Design: Corner/rbac/reinstating_a_licence_by_the_suspending_admin_is_forbidden
    """
    rebuilder = license_rebuilder()
    take_license_action(
        rebuilder["id"], "SUSPEND", make_program_admin_headers(ADMIN_USER_ID)
    )

    reinstated = get_success_data(
        api.create_license_action(
            rebuilder["id"],
            create_license_action_payload("REINSTATE"),
            make_program_admin_headers(SECOND_ADMIN_USER_ID),
        )
    )
    assert reinstated["license_status"] == "ACTIVE", (
        f"expected ACTIVE after a second administrator reinstated, "
        f"got {reinstated['license_status']}"
    )
    assert reinstated["suspended_by_user_id"] is None, (
        "a successful reinstatement clears the suspending administrator, "
        f"got {reinstated['suspended_by_user_id']}"
    )
    assert reinstated["last_license_action_by_user_id"] == SECOND_ADMIN_USER_ID, (
        f"expected {SECOND_ADMIN_USER_ID} as the acting administrator, "
        f"got {reinstated['last_license_action_by_user_id']}"
    )


def test_rescheduling_with_the_inspector_who_failed_the_vehicle_is_refused():
    """The inspector who failed the vehicle may not be booked for its re-inspection.

    PRD: "First, when a re-inspection is scheduled, the `inspector_id` in the body must differ from the `inspector_id` of the application's most recent `COMPLETED_FAIL` inspection — the inspector who failed a vehicle may not be the one who re-inspects it."

    Design: Corner/rbac/rescheduling_with_the_same_failing_inspector_is_forbidden
    """
    env = setup_failed_application(body_class="TRAILER")
    application = read_application(env["application_id"])
    assert application["status"] == "FAILED", (
        f"the setup must leave the application FAILED, got {application['status']}"
    )

    response = api.schedule_inspection(
        env["application_id"],
        schedule_inspection_payload(
            env["inspector_id"],
            env["station_id"],
            application["version"],
            "2026-08-20T09:00:00Z",
            "2026-08-20T11:00:00Z",
        ),
        make_state_title_clerk_headers(CLERK_USER_ID),
    )
    validate_error(response, "ERR_SEGREGATION_OF_DUTIES")

    unchanged = read_application(env["application_id"])
    assert unchanged["status"] == "FAILED", (
        f"the refused booking must leave the application FAILED, got {unchanged['status']}"
    )
    assert unchanged["attempts_completed"] == 1, (
        f"expected 1 completed attempt, got {unchanged['attempts_completed']}"
    )
    assert read_inspector(env["inspector_id"])["scheduled_inspection_count"] == 0, (
        "the refused booking must not occupy the failing inspector's calendar"
    )


def test_a_different_inspector_books_the_second_attempt():
    """A second commissioned inspector takes the re-inspection the failing one may not.

    PRD: "First, when a re-inspection is scheduled, the `inspector_id` in the body must differ from the `inspector_id` of the application's most recent `COMPLETED_FAIL` inspection — the inspector who failed a vehicle may not be the one who re-inspects it."

    Design: Corner/rbac/rescheduling_with_the_same_failing_inspector_is_forbidden
    """
    env = setup_failed_application(body_class="TRAILER")
    replacement = commission_inspector()
    application = read_application(env["application_id"])

    attempt = validate_success(
        api.schedule_inspection(
            env["application_id"],
            schedule_inspection_payload(
                replacement["id"],
                env["station_id"],
                application["version"],
                "2026-08-20T09:00:00Z",
                "2026-08-20T11:00:00Z",
            ),
            make_state_title_clerk_headers(CLERK_USER_ID),
        ),
        201,
    )
    assert attempt["inspector_id"] == replacement["id"], (
        f"expected the replacement inspector {replacement['id']}, "
        f"got {attempt['inspector_id']}"
    )
    assert attempt["status"] == "SCHEDULED", (
        f"a fresh booking lands in SCHEDULED, got {attempt['status']}"
    )
    assert attempt["attempt_no"] == 2, (
        f"the re-inspection is attempt 2, got {attempt['attempt_no']}"
    )

    rescheduled = read_application(env["application_id"])
    assert rescheduled["status"] == "SCHEDULED", (
        f"expected SCHEDULED after the booking, got {rescheduled['status']}"
    )
    assert rescheduled["attempts_completed"] == 1, (
        f"expected 1 completed attempt, got {rescheduled['attempts_completed']}"
    )

    quote = read_fee_quote(env["application_id"])
    assert quote["assessed_fee_cents"] == 7500, (
        f"expected the base application fee of 7500, got {quote['assessed_fee_cents']}"
    )
    assert quote["subtotal_cents"] == 11500, (
        "the subtotal carries one re-inspection fee of 4000 cents, "
        f"got {quote['subtotal_cents']}"
    )
    assert quote["expedite_fee_cents"] == 0, (
        f"no expedite was requested, got {quote['expedite_fee_cents']}"
    )
    assert quote["discount_cents"] == 0, (
        f"the rebuilder has titled no applications yet, got {quote['discount_cents']}"
    )
    assert quote["total_program_charge_cents"] == 11500, (
        f"expected 11500, got {quote['total_program_charge_cents']}"
    )

    assert read_inspector(env["inspector_id"])["scheduled_inspection_count"] == 0, (
        "the inspector who failed the vehicle holds no live booking"
    )
    assert read_inspector(replacement["id"])["scheduled_inspection_count"] == 1, (
        "the replacement inspector holds the new booking"
    )

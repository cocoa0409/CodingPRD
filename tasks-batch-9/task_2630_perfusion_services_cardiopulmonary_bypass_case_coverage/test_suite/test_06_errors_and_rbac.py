"""The identity ladder, the envelope shape, role exclusivity, ownership and segregation of duties."""
from test_helpers import (
    ADMIN_HEADERS,
    INITIAL_CLOCK,
    NON_EXISTENT_UUID,
    NO_AUTH_HEADERS,
    add_perfusionist,
    api_client,
    assert_case_dimensions,
    assert_cents,
    assert_error_envelope,
    assert_pagination_meta,
    assert_readiness_score,
    assert_single_resource_meta,
    assert_success_envelope,
    build_bypass_case,
    build_clock,
    build_hospital_contract,
    build_incident_close,
    build_incident_report,
    build_incident_review,
    build_pack_decision,
    build_pack_line_item,
    build_preference_card,
    build_service_completion,
    build_substitution,
    configure_pack,
    create_contract,
    create_device,
    create_perfusionist,
    create_surgeon,
    make_chief_perfusionist_headers,
    make_headers,
    make_perfusionist_headers,
    make_surgeon_headers,
    off_bypass_setup,
    open_checklist,
    read_case,
    read_incident_report,
    read_pack,
    staffed_setup,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_auth_ladder_rejects_missing_headers_bad_role_unknown_actor_and_non_chief():
    """The first four identity checks answer in a strict order, and a real chief is then admitted.

    PRD 2.1: If either header is absent or empty, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401) before any other processing occurs.
    PRD 2.1: If `X-User-Role` is present but is not one of the five role names below, the rejection is `ERR_INVALID_ROLE`, also HTTP 401.
    PRD 2.1: For all three of these entity-backed roles, an `X-User-ID` that does not resolve to an existing row of the backing entity is rejected with `ERR_ACTOR_NOT_FOUND` (HTTP 403).
    PRD 2.1: Additionally, a caller presenting `ChiefPerfusionist` whose resolved `Perfusionist` row has `is_chief` set to false is rejected with `ERR_NOT_CHIEF_PERFUSIONIST` (HTTP 403) — the chief capacity is a property of the person, not a claim the header can make on its own.

    Design: Corner/errors/auth_ladder_rejects_missing_headers_bad_role_unknown_actor_and_non_chief
    """
    contract = create_contract()
    p1 = create_perfusionist()
    chief = create_perfusionist(
        full_name="Dr Yusra Halabi",
        employee_code="EMP-1002",
        is_chief=True,
        ecmo_privileged=None,
        career_case_count=200,
    )

    # Rung 1: neither auth header is sent at all.
    missing = api_client.list_bypass_cases(NO_AUTH_HEADERS)
    validate_error(missing, "ERR_MISSING_AUTH_HEADERS", 401)
    assert_error_envelope(missing, "ERR_MISSING_AUTH_HEADERS")

    # Rung 2: a role string outside the five declared names, even for a real actor.
    bad_role = api_client.list_bypass_cases(make_headers("PerfusionAssistant", p1["id"]))
    validate_error(bad_role, "ERR_INVALID_ROLE", 401)
    assert_error_envelope(bad_role, "ERR_INVALID_ROLE")

    # Rung 4: an entity-backed role whose identifier resolves to no row.
    unknown_actor = api_client.list_bypass_cases(make_perfusionist_headers(NON_EXISTENT_UUID))
    validate_error(unknown_actor, "ERR_ACTOR_NOT_FOUND", 403)
    assert_error_envelope(unknown_actor, "ERR_ACTOR_NOT_FOUND")

    # Rung 5: the row resolves but carries is_chief false, so the claim is refused.
    not_chief = api_client.get_hospital_contract(
        contract["id"], make_chief_perfusionist_headers(p1["id"])
    )
    validate_error(not_chief, "ERR_NOT_CHIEF_PERFUSIONIST", 403)
    assert_error_envelope(not_chief, "ERR_NOT_CHIEF_PERFUSIONIST")

    admitted = api_client.get_hospital_contract(
        contract["id"], make_chief_perfusionist_headers(chief["id"])
    )
    body = validate_success(admitted, 200)
    assert body["id"] == contract["id"]
    assert body["hospital_name"] == "St Aldate Cardiac Center"


def test_error_and_success_envelopes_carry_the_declared_shape_and_status_codes():
    """A 404, a 400 and a 409 all wear the error envelope, and the success reads wear theirs.

    PRD 2.2: The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
    PRD 2.2: The `response_type` is either "object" for a single resource or "array" for a list of resources.
    PRD 2.8: Rung 6 requires that every field an endpoint marks as required be present and non-null on all creating and updating operations, else `ERR_INVALID_REQUEST` (HTTP 400).
    PRD 2.8: Rung 9 covers the hospital contract named either by a path identifier or by a `contract_id` in the body — it guards reading a contract, updating a contract, executing a settlement run, commissioning a device, creating a call rotation slot and scheduling a case — raising `ERR_CONTRACT_NOT_FOUND`.
    PRD 3.6: The case must be `SETUP_VERIFIED`, else `ERR_CASE_NOT_SETUP_VERIFIED`; its `readiness_flag` must read `NONE`, else `ERR_DEVICE_FALLBACK_REQUIRED`; its primary machine must be `RESERVED`; and its standby machine must be `RESERVED` or `AVAILABLE`.
    PRD 2.3: Single-resource endpoints omit those four fields from `meta`.

    Design: Corner/errors/error_and_success_envelopes_carry_the_declared_shape_and_status_codes
    """
    env = staffed_setup()
    case_id = env["case"]["id"]

    # Rung 9: the contract named by the path identifier does not exist.
    absent = api_client.get_hospital_contract(NON_EXISTENT_UUID, ADMIN_HEADERS)
    validate_error(absent, "ERR_CONTRACT_NOT_FOUND", 404)
    assert_error_envelope(absent, "ERR_CONTRACT_NOT_FOUND")

    # Rung 6: the two scheduling instants are required inputs and both are omitted.
    shapeless = api_client.create_bypass_case(
        build_bypass_case(
            env["contract"]["id"],
            env["surgeon"]["id"],
            scheduled_start=None,
            scheduled_end=None,
        ),
        env["chief_headers"],
    )
    validate_error(shapeless, "ERR_INVALID_REQUEST", 400)
    assert_error_envelope(shapeless, "ERR_INVALID_REQUEST")

    # A state gate reached only because the assigned perfusionist passed rung 22.
    too_early = api_client.start_bypass(case_id, env["p1_headers"])
    validate_error(too_early, "ERR_CASE_NOT_SETUP_VERIFIED", 409)
    assert_error_envelope(too_early, "ERR_CASE_NOT_SETUP_VERIFIED")

    # None of the three refusals leaked a partially built case into the error body.
    for refused in (absent, shapeless, too_early):
        leaked = refused.json()["data"]
        assert "id" not in leaked, "an error body must not carry a resource id"
        assert "version" not in leaked, "an error body must not carry a version"
        assert "bypass_status" not in leaked, "an error body must not carry case fields"

    single = api_client.get_bypass_case(case_id, env["p1_headers"])
    read = validate_success(single, 200)
    assert_success_envelope(single, "object")
    assert_single_resource_meta(single)
    assert read["id"] == case_id
    assert isinstance(read["version"], int)
    assert read["bypass_status"] == "STAFFED"

    listing = api_client.list_bypass_cases(env["chief_headers"])
    cases, meta = validate_paginated(listing)
    assert_success_envelope(listing, "array")
    assert_pagination_meta(meta, total_count=1, has_more=False)
    assert [row["id"] for row in cases] == [case_id]


def test_each_role_is_denied_the_other_roles_exclusive_operations():
    """Four exclusive operations are refused to the wrong role, and a shared read still answers.

    PRD 2.1: If the role is well-formed but is not among the roles the called endpoint admits, the rejection is `ERR_UNAUTHORIZED` (HTTP 403).
    PRD 2.1: It registers hospital contracts and their rates, updates commercial terms, executes monthly settlement runs, registers surgeons and onboards perfusionists, records certification cycles, adjudicates continuing-education claims, and drives the logical clock.
    PRD 2.1: A `BiomedTech` is a biomedical engineering technician who commissions devices, captures device event logs and completes preventive service.
    PRD 2.1: A `Surgeon` publishes preference cards for their own procedures and adjudicates disposable-pack substitutions on their own cases.
    PRD 2.8: Rungs 1 through 5 are the authentication and authorization ladder described in §2.1, and they apply to every endpoint: (1) both auth headers present and non-empty, else `ERR_MISSING_AUTH_HEADERS`; (2) `X-User-Role` is one of the five declared roles, else `ERR_INVALID_ROLE`; (3) the supplied role is admitted by the called endpoint, else `ERR_UNAUTHORIZED`; (4) for the entity-backed roles `ChiefPerfusionist`, `Perfusionist` and `Surgeon`, `X-User-ID` resolves to a row of the backing entity — this rung guards every endpoint that admits any of those three roles — else `ERR_ACTOR_NOT_FOUND`; (5) a caller acting as `ChiefPerfusionist` resolves to a perfusionist with `is_chief` true, on every endpoint that admits `ChiefPerfusionist`, else `ERR_NOT_CHIEF_PERFUSIONIST`.

    Design: Corner/rbac/each_role_is_denied_the_other_roles_exclusive_operations
    """
    contract = create_contract()
    p1 = create_perfusionist()
    chief = create_perfusionist(
        full_name="Dr Yusra Halabi",
        employee_code="EMP-1002",
        is_chief=True,
        ecmo_privileged=None,
        career_case_count=200,
    )
    surgeon = create_surgeon()
    device = create_device(contract["id"])
    chief_headers = make_chief_perfusionist_headers(chief["id"])

    # Registering a contract is back-office work, and the role check answers before
    # the unresolvable identifier could have raised ERR_ACTOR_NOT_FOUND.
    pirate = api_client.create_hospital_contract(
        build_hospital_contract(
            hospital_name="Pirate Hospital",
            staffing_model="PER_CASE",
            per_case_fee_cents=1,
            ecmo_hourly_fee_cents=1,
            monthly_case_cap=1,
            monthly_coverage_fee_cents=None,
            prolonged_surcharge_pct=None,
            prolonged_pump_threshold_minutes=None,
            disposable_markup_pct=None,
            disposable_discount_pct=None,
        ),
        make_perfusionist_headers(NON_EXISTENT_UUID),
    )
    validate_error(pirate, "ERR_UNAUTHORIZED", 403)
    assert_error_envelope(pirate, "ERR_UNAUTHORIZED")

    # A chief holds no override on the time source.
    chief_clock = api_client.set_clock(build_clock("2026-08-02T00:00:00Z"), chief_headers)
    validate_error(chief_clock, "ERR_UNAUTHORIZED", 403)

    # Preventive service belongs to the technician.
    surgeon_service = api_client.create_service_completion(
        device["id"], build_service_completion(), make_surgeon_headers(surgeon["id"])
    )
    validate_error(surgeon_service, "ERR_UNAUTHORIZED", 403)

    # Surgeon master data belongs to the back office.
    chief_surgeon = api_client.create_surgeon(
        {"full_name": "Dr Nobody", "npi_code": "NPI-9999999", "specialty": "TRANSPLANT"},
        chief_headers,
    )
    validate_error(chief_surgeon, "ERR_UNAUTHORIZED", 403)

    # No denied call had an effect: the clock never moved and no second surgeon exists.
    validate_success(api_client.set_clock(build_clock(INITIAL_CLOCK), ADMIN_HEADERS), 200)
    still_there = validate_success(api_client.get_surgeon(surgeon["id"], ADMIN_HEADERS), 200)
    assert still_there["npi_code"] == "NPI-3300110"

    shared = api_client.list_perfusion_devices(make_perfusionist_headers(p1["id"]))
    devices, meta = validate_paginated(shared)
    assert_pagination_meta(meta, total_count=1, has_more=False)
    assert [row["asset_tag"] for row in devices] == ["HLM-001"]


def test_card_ownership_and_case_assignment_are_enforced_against_the_actor_id():
    """Same-role peers are locked out of each other's card, pack and case, then the owners succeed.

    PRD 2.1: Publishing a preference card as a `Surgeon`, or adjudicating a pack substitution as a `Surgeon`, requires that `X-User-ID` equal the `surgeon_id` of the card being published or the `surgeon_id` of the case the pack belongs to; otherwise `ERR_NOT_CARD_OWNER` (HTTP 403).
    PRD 2.1: Verifying a pre-bypass checklist, going on pump, coming off pump, and opening an ECMO run all require that `X-User-ID` equal the case's `assigned_perfusionist_id`, and decannulating an ECMO run requires that it equal the run's `primary_perfusionist_id`; otherwise `ERR_NOT_ASSIGNED_PERFUSIONIST` (HTTP 403).
    PRD 2.8: Rungs 21 through 23 are the ownership and segregation-of-duties checks of §2.1: (21) `ERR_NOT_CARD_OWNER` on publishing a preference card and on adjudicating a pack; (22) `ERR_NOT_ASSIGNED_PERFUSIONIST` on verifying a checklist, going on pump, coming off pump, opening an ECMO run and decannulating a run; (23) `ERR_SEGREGATION_OF_DUTIES` on submitting, reviewing and closing an incident report.
    PRD 3.5: The owning surgeon adjudicates a pending pack with a `decision` of `APPROVED` or `REJECTED` and an optional `note`, moving `approval_status` from `PENDING` to the decided value and advancing the pack's `version`; a pack that is not `PENDING` cannot be adjudicated at all, which is `ERR_PACK_APPROVAL_STATE_INVALID`.
    PRD 3.6: On success the checklist moves `DRAFT → VERIFIED` with `blood_mgmt_signoff` set true, `verified_by_perfusionist_id` set to the acting perfusionist and `verified_at` set to the logical clock, while the case moves `PACK_CONFIGURED → SETUP_VERIFIED` with `setup_verified_at` set to the same instant.

    Design: Corner/rbac/card_ownership_and_case_assignment_are_enforced_against_the_actor_id
    """
    env = staffed_setup()
    case_id = env["case"]["id"]
    s1_id = env["surgeon"]["id"]
    s2 = create_surgeon(full_name="Dr Halima Rossi", npi_code="NPI-3300440")
    p2 = add_perfusionist(
        env,
        "p2",
        full_name="Tomas Aleksy",
        employee_code="EMP-1012",
        ecmo_privileged=None,
        career_case_count=90,
    )
    pack = configure_pack(
        case_id,
        env["d1"]["id"],
        env["p1"]["id"],
        substitutions=[build_substitution("A_OXYGENATOR", "A_OXY_ALT", 1200, "lot recall")],
    )
    assert pack["approval_status"] == "PENDING"
    checklist = open_checklist(case_id, env["p1"]["id"], hematocrit_pct=26)

    # A surgeon may only publish cards that name themselves.
    foreign_card = api_client.create_preference_card(
        build_preference_card(
            s1_id,
            procedure_type="VALVE",
            standard_pump_minutes=140,
            prime_volume_ml=1400,
            pack_line_items=[build_pack_line_item("A_OXYGENATOR", 1, 1055)],
            required_safety_check_codes=["ACT_BASELINE"],
        ),
        make_surgeon_headers(s2["id"]),
    )
    validate_error(foreign_card, "ERR_NOT_CARD_OWNER", 403)
    assert_error_envelope(foreign_card, "ERR_NOT_CARD_OWNER")

    # Adjudication belongs to the surgeon of the pack's own case.
    foreign_approval = api_client.approve_disposable_pack(
        pack["id"], build_pack_decision("APPROVED", note="not my case"), make_surgeon_headers(s2["id"])
    )
    validate_error(foreign_approval, "ERR_NOT_CARD_OWNER", 403)
    assert read_pack(pack["id"])["approval_status"] == "PENDING"

    # The ownership rung outranks the pending-approval gate that would otherwise answer.
    foreign_verify = api_client.verify_pump_checklist(
        checklist["id"], make_perfusionist_headers(p2["id"])
    )
    validate_error(foreign_verify, "ERR_NOT_ASSIGNED_PERFUSIONIST", 403)

    foreign_start = api_client.start_bypass(case_id, make_perfusionist_headers(p2["id"]))
    validate_error(foreign_start, "ERR_NOT_ASSIGNED_PERFUSIONIST", 403)
    assert read_case(case_id)["bypass_status"] == "PACK_CONFIGURED"

    # The refused card was never written.
    _cards, meta = validate_paginated(api_client.list_preference_cards(ADMIN_HEADERS))
    assert_pagination_meta(meta, total_count=1, has_more=False)

    approved = validate_success(
        api_client.approve_disposable_pack(
            pack["id"],
            build_pack_decision("APPROVED", note="alt oxygenator accepted"),
            make_surgeon_headers(s1_id),
        ),
        200,
    )
    assert approved["approval_status"] == "APPROVED"
    assert_cents(approved["pack_cost_cents"], 3898, "pack_cost_cents")

    verified = validate_success(
        api_client.verify_pump_checklist(checklist["id"], env["p1_headers"]), 200
    )
    assert verified["status"] == "VERIFIED"
    assert verified["verified_by_perfusionist_id"] == env["p1"]["id"]
    assert read_case(case_id)["bypass_status"] == "SETUP_VERIFIED"


def test_incident_submit_review_and_close_require_three_distinct_actors():
    """Submission belongs to the filer while review and close belong to a chief who is neither party.

    PRD 2.1: Incident-report handling enforces segregation of duties: the actor submitting a report must be the perfusionist recorded as `filed_by_perfusionist_id`, and the actor reviewing or closing a report must differ from both `filed_by_perfusionist_id` and `involved_perfusionist_id`.
    PRD 2.1: A violation of either half is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
    PRD 3.9: Only the filer may submit — the acting identity is compared against `filed_by_perfusionist_id` — and the report must be in `DRAFT` or in `RETURNED_FOR_INFO`, any other state drawing `ERR_INCIDENT_STATE_INVALID`.
    PRD 3.9: Whichever decision is taken, the report must be `SUBMITTED`, and the reviewing chief may be neither the involved perfusionist nor the filer — a violation of either is `ERR_SEGREGATION_OF_DUTIES`.
    PRD 3.9: Accepting for review moves the report `SUBMITTED → UNDER_REVIEW` and, crucially, **freezes** the audit variant of the involved perfusionist's readiness score onto the report as `reviewed_readiness_score`.
    PRD 3.2: The **audit** variant counts verified credits only.
    PRD 3.9: Only a chief may close, the report must be `UNDER_REVIEW`, and the closer may be neither the involved perfusionist nor the filer — the same segregation-of-duties test as at review, now with a second purpose, since the closer's identity is recorded in `closed_by_perfusionist_id`.
    PRD 3.9: An `ISOLATED` close moves the report `UNDER_REVIEW → CLOSED_NO_ACTION`, sets `finding` to `ISOLATED`, leaves `corrective_action_required` false, records `closed_by_perfusionist_id`, advances the report's `version` — and does nothing else whatsoever.

    Design: Corner/rbac/incident_submit_review_and_close_require_three_distinct_actors
    """
    env = off_bypass_setup(end_bypass_overrides={"adverse_event_count": 1})
    case_id = env["case"]["id"]
    p1_id = env["p1"]["id"]
    chief_id = env["chief"]["id"]
    chief2 = add_perfusionist(
        env,
        "chief2",
        full_name="Dr Aurelio Banda",
        employee_code="EMP-1003",
        is_chief=True,
        ecmo_privileged=None,
        career_case_count=180,
    )
    p2 = add_perfusionist(
        env,
        "p2",
        full_name="Tomas Aleksy",
        employee_code="EMP-1012",
        ecmo_privileged=None,
        career_case_count=90,
    )
    chief2_headers = make_chief_perfusionist_headers(chief2["id"])

    report = validate_success(
        api_client.create_incident_report(
            build_incident_report(
                case_id,
                p1_id,
                severity="MAJOR",
                category="ANTICOAGULATION",
                narrative="ACT drifted below protocol for eleven minutes",
            ),
            env["chief_headers"],
        ),
        201,
    )
    report_id = report["id"]
    assert report["filed_by_perfusionist_id"] == chief_id
    assert report["status"] == "DRAFT"

    # Only the filer may submit, so an uninvolved perfusionist cannot push it into review.
    wrong_submitter = api_client.submit_incident_report(
        report_id, make_perfusionist_headers(p2["id"])
    )
    validate_error(wrong_submitter, "ERR_SEGREGATION_OF_DUTIES", 403)
    assert_error_envelope(wrong_submitter, "ERR_SEGREGATION_OF_DUTIES")
    assert read_incident_report(report_id)["status"] == "DRAFT"

    submitted = validate_success(
        api_client.submit_incident_report(report_id, env["chief_headers"]), 200
    )
    assert submitted["status"] == "SUBMITTED"

    # The filer holds the right role for review and is still refused.
    filer_review = api_client.review_incident_report(
        report_id,
        build_incident_review("ACCEPT_FOR_REVIEW", review_note="filer trying to audit their own report"),
        env["chief_headers"],
    )
    validate_error(filer_review, "ERR_SEGREGATION_OF_DUTIES", 403)
    still_submitted = read_incident_report(report_id)
    assert still_submitted["status"] == "SUBMITTED"
    assert still_submitted["reviewed_readiness_score"] is None

    reviewed = validate_success(
        api_client.review_incident_report(
            report_id,
            build_incident_review("ACCEPT_FOR_REVIEW", review_note="independent chief accepts"),
            chief2_headers,
        ),
        200,
    )
    assert reviewed["status"] == "UNDER_REVIEW"
    assert reviewed["return_count"] == 0
    # The audit variant ignores p1's twenty still-SUBMITTED hours, leaving the
    # experience term alone: 0.45 * (150 / 150) with no fatigue, because the
    # fatigue window stops short of the clock the case went on pump at.
    assert_readiness_score(reviewed["reviewed_readiness_score"], 0.45)

    filer_close = api_client.close_incident_report(
        report_id,
        build_incident_close("ISOLATED", credit_case_fee=False, closing_note="filer trying to close"),
        env["chief_headers"],
    )
    validate_error(filer_close, "ERR_SEGREGATION_OF_DUTIES", 403)
    still_under_review = read_incident_report(report_id)
    assert still_under_review["status"] == "UNDER_REVIEW"
    assert still_under_review["closed_by_perfusionist_id"] is None

    closed = validate_success(
        api_client.close_incident_report(
            report_id,
            build_incident_close(
                "ISOLATED", credit_case_fee=False, closing_note="single-event lapse, coached"
            ),
            chief2_headers,
        ),
        200,
    )
    assert closed["status"] == "CLOSED_NO_ACTION"
    assert closed["finding"] == "ISOLATED"
    assert closed["corrective_action_required"] is False
    assert closed["closed_by_perfusionist_id"] == chief2["id"]

    # The empty branch fires no certification, slot or billing side effect.
    certs, _meta = validate_paginated(api_client.list_certifications(p1_id, ADMIN_HEADERS))
    assert [row["status"] for row in certs] == ["ACTIVE"]
    assert_case_dimensions(read_case(case_id), "OFF_BYPASS", "PROVISIONAL_ACCRUED")

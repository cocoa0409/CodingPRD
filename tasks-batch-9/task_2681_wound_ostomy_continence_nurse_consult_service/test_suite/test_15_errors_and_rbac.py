"""The error surface and the role surface: thirteen dedicated not-found codes, the
declared order in which references are resolved, and the four ladders that put
authentication before authorisation and authorisation before everything else."""
from test_helpers import (
    as_instant,
    assign_consult_payload,
    create_candidate_nurse,
    create_consult,
    create_consult_request_payload,
    create_dressing_protocol_payload,
    create_order,
    create_patient,
    create_patient_payload,
    create_product,
    create_round,
    create_skin_assessment_payload,
    create_surface,
    create_survey_observation_payload,
    create_trainee_nurse,
    create_unit,
    file_observation,
    find_case_for_assessment,
    get_success_data,
    open_round,
    read_patient_version,
    read_unit_version,
    set_clock_payload,
    setup_assessed_consult,
    triage_consult,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    NO_HEADERS,
    make_director_headers,
    make_materials_headers,
    make_nurse_headers,
    make_system_operator_headers,
    make_unit_charge_headers,
    make_unknown_role_headers,
)


DIRECTOR = make_director_headers()
MATERIALS = make_materials_headers()
SYSOP = make_system_operator_headers()

UNKNOWN_PATIENT = "11111111-1111-4111-8111-111111111111"
UNKNOWN_NURSE = "22222222-2222-4222-8222-222222222222"
UNKNOWN_CONSULT = "33333333-3333-4333-8333-333333333333"
UNKNOWN_ASSESSMENT = "44444444-4444-4444-8444-444444444444"
UNKNOWN_CASE = "55555555-5555-4555-8555-555555555555"
UNKNOWN_ROUND = "66666666-6666-4666-8666-666666666666"
UNKNOWN_OBSERVATION = "77777777-7777-4777-8777-777777777777"
UNKNOWN_ORDER = "88888888-8888-4888-8888-888888888888"
UNKNOWN_PRODUCT = "99999999-9999-4999-8999-999999999999"
UNKNOWN_PROTOCOL = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
UNKNOWN_PLAN = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
UNKNOWN_BODY_ROUND = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
UNKNOWN_BODY_PATIENT = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
UNKNOWN_BODY_NURSE = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
UNKNOWN_BODY_CONSULT = "ffffffff-ffff-4fff-8fff-ffffffffffff"
UNKNOWN_BODY_PRODUCT = "12121212-1212-4212-8212-121212121212"


def _assert_bare_error_envelope(response):
    """The failure envelope carries an explanation and no entity payload."""
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["error_id"], str) and body["data"]["error_id"]
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert "id" not in body["data"], "an error envelope carries no resource fields"
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}


def test_each_clinical_spine_read_answers_with_its_own_not_found_code(api):
    """Five populated tables, five unknown ids, five different codes.

    PRD §2.5: "Each identifier has its own dedicated not-found code, all at HTTP
    404: `ERR_UNIT_NOT_FOUND` for a `unit_id` path segment,
    `ERR_PATIENT_NOT_FOUND` for `patient_id`, `ERR_NURSE_NOT_FOUND` for
    `nurse_id`, `ERR_CONSULT_NOT_FOUND` for `consult_id`,
    `ERR_ASSESSMENT_NOT_FOUND` for `assessment_id`, `ERR_CASE_NOT_FOUND` for
    `case_id`, `ERR_SURVEY_ROUND_NOT_FOUND` for `round_id`,
    `ERR_OBSERVATION_NOT_FOUND` for `observation_id`, `ERR_SURFACE_NOT_FOUND` for
    `surface_id`, `ERR_ORDER_NOT_FOUND` for `order_id`, `ERR_PRODUCT_NOT_FOUND`
    for `product_id`, `ERR_PROTOCOL_NOT_FOUND` for `protocol_id` and
    `ERR_PLAN_NOT_FOUND` for `plan_id`."
    PRD §2.10 rung 4: "Every identifier in the URL path resolves, left to right —
    the per-type 404 codes listed in §2.5, on every path-parameterised endpoint."
    PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format:"
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."
    PRD §3.5: "And it versions the patient row, which is precisely why a client's
    `expected_patient_version` goes stale after each filing."
    PRD §3.5: "A new assessment begins with `validation_status`
    `PENDING_VALIDATION`, with `poa_determination`, `confirmed_stage`,
    `validated_by_user_id` and `dispute_reason` all null and `restage_count` at 0."
    PRD §3.5: "It opens a case file: a pressure injury case is created with
    `classification` `UNDETERMINED`, `status` `OPEN`, its `skin_assessment_id`
    pointing at the new assessment, its `patient_id` copied from the assessment and
    its `unit_id` copied from the patient's `unit_id`."
    PRD §3.2: "A patient's `status` begins at `ADMITTED`."

    Design: Corner/errors/unknown_path_ids_on_the_clinical_spine_return_not_found
    """
    scenario = setup_assessed_consult(
        api=api,
        unit_overrides={
            "unit_code": "ERRP-U1",
            "name": "Error Probe Med-Surg",
            "bed_count": 24,
            "rental_budget_cap_cents": 100000,
        },
        patient_overrides={
            "mrn": "ERRPMRN01",
            "admitted_at": "2026-07-31T12:00:00Z",
            "comorbidity_count": 2,
        },
        consult_overrides={
            "clinical_note": "Sacral wound noted on the night shift turn."
        },
        assessment_overrides={"measured_area_cm2": 6.0},
    )
    case = find_case_for_assessment(scenario["assessment"]["id"], api=api)

    probes = (
        (api.get_patient(UNKNOWN_PATIENT, DIRECTOR), "ERR_PATIENT_NOT_FOUND"),
        (api.get_woc_nurse(UNKNOWN_NURSE, DIRECTOR), "ERR_NURSE_NOT_FOUND"),
        (api.get_consult_request(UNKNOWN_CONSULT, DIRECTOR), "ERR_CONSULT_NOT_FOUND"),
        (
            api.get_skin_assessment(UNKNOWN_ASSESSMENT, DIRECTOR),
            "ERR_ASSESSMENT_NOT_FOUND",
        ),
        (api.get_pressure_injury_case(UNKNOWN_CASE, DIRECTOR), "ERR_CASE_NOT_FOUND"),
    )
    for response, expected_error_id in probes:
        validate_error(response, expected_error_id, expected_status=404)
        _assert_bare_error_envelope(response)

    control = get_success_data(api.get_patient(scenario["patient"]["id"], DIRECTOR))
    assert control["id"] == scenario["patient"]["id"], (
        "the 404s are id-specific, not table-wide"
    )
    assert control["status"] == "ADMITTED"
    assert control["version"] == 2, (
        "1 at admission and 1 more from the single accepted assessment, which "
        "versions the patient row"
    )

    assert (
        get_success_data(
            api.get_skin_assessment(scenario["assessment"]["id"], DIRECTOR)
        )["validation_status"]
        == "PENDING_VALIDATION"
    ), "no probe mutated the assessment"
    reread_case = get_success_data(api.get_pressure_injury_case(case["id"], DIRECTOR))
    assert reread_case["status"] == "OPEN"
    assert reread_case["classification"] == "UNDETERMINED"


def test_each_programme_and_materials_read_answers_with_its_own_not_found_code(api):
    """Six more codes, two of them from tables that are legitimately empty.

    PRD §2.5: "Each identifier has its own dedicated not-found code, all at HTTP
    404: `ERR_UNIT_NOT_FOUND` for a `unit_id` path segment,
    `ERR_PATIENT_NOT_FOUND` for `patient_id`, `ERR_NURSE_NOT_FOUND` for
    `nurse_id`, `ERR_CONSULT_NOT_FOUND` for `consult_id`,
    `ERR_ASSESSMENT_NOT_FOUND` for `assessment_id`, `ERR_CASE_NOT_FOUND` for
    `case_id`, `ERR_SURVEY_ROUND_NOT_FOUND` for `round_id`,
    `ERR_OBSERVATION_NOT_FOUND` for `observation_id`, `ERR_SURFACE_NOT_FOUND` for
    `surface_id`, `ERR_ORDER_NOT_FOUND` for `order_id`, `ERR_PRODUCT_NOT_FOUND`
    for `product_id`, `ERR_PROTOCOL_NOT_FOUND` for `protocol_id` and
    `ERR_PLAN_NOT_FOUND` for `plan_id`."
    PRD §2.10 rung 4: "Every identifier in the URL path resolves, left to right —
    the per-type 404 codes listed in §2.5, on every path-parameterised endpoint."
    PRD §3.7: "A computed per-unit report is also readable for any round, and it is
    the diagnostic surface for that divergence: it answers with the round's
    `round_id`, its `round_type`, an `observation_total` across the whole round,
    and a `unit_rows` array."
    PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format:"
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."
    PRD §3.7: "Filing an observation raises the round's `observation_count` by 1 and
    versions the round."
    PRD §3.8: "The order starts with `fulfillment_status` `REQUESTED` and
    `billing_status` `UNBILLED`, and no money moves at creation — creation is a
    costing exercise, not a ledger event."
    PRD §3.9: "A product starts `ACTIVE` and may be archived by the director with a
    `reason`, moving it `ACTIVE → ARCHIVED`."
    PRD §3.7: "The director opens a planned round, moving it `PLANNED → OPEN`, and
    this is the only point at which window contention is checked."

    Design: Corner/errors/unknown_path_ids_on_the_programme_and_materials_surface_return_not_found
    """
    unit = create_unit(
        api=api,
        unit_code="ERRP-U2",
        name="Error Probe Step-Down",
        bed_count=18,
        rental_budget_cap_cents=400000,
    )
    patient = create_patient(
        unit, api=api, mrn="ERRPMRN02", admitted_at="2026-07-31T00:00:00Z"
    )
    observer = create_candidate_nurse(unit, api=api, full_name="Owen Probe")
    survey_round = open_round(
        create_round(
            [unit["id"]],
            api=api,
            round_type="PREVALENCE",
            window_start="2026-07-31T00:00:00Z",
            window_end="2026-08-02T00:00:00Z",
        ),
        api=api,
    )
    observation = file_observation(
        survey_round,
        unit,
        patient,
        observer,
        api=api,
        injury_present=True,
        classification="POA",
        observed_stage="STAGE_2",
        at_risk=True,
    )
    surface = create_surface(
        api=api,
        asset_tag="ERRP-S1",
        surface_class="LOW_AIR_LOSS",
        daily_rate_cents=10000,
        vendor_name="Probe Rentals",
    )
    order = create_order(
        unit,
        patient,
        surface,
        api=api,
        rental_start="2026-08-02T00:00:00Z",
        rental_end="2026-08-05T00:00:00Z",
        authorized_days=3,
    )
    product = create_product(
        api=api,
        sku="ERRP-FOAM-01",
        name="Probe Foam 10x10",
        category="FOAM",
        unit_cost_cents=500,
        formulary_tier="PREFERRED",
    )

    probes = (
        (api.get_survey_round(UNKNOWN_ROUND, DIRECTOR), "ERR_SURVEY_ROUND_NOT_FOUND"),
        (
            api.get_survey_round_unit_report(UNKNOWN_ROUND, DIRECTOR),
            "ERR_SURVEY_ROUND_NOT_FOUND",
        ),
        (
            api.get_survey_observation(UNKNOWN_OBSERVATION, DIRECTOR),
            "ERR_OBSERVATION_NOT_FOUND",
        ),
        (
            api.get_support_surface_order(UNKNOWN_ORDER, DIRECTOR),
            "ERR_ORDER_NOT_FOUND",
        ),
        (api.get_formulary_product(UNKNOWN_PRODUCT, DIRECTOR), "ERR_PRODUCT_NOT_FOUND"),
        (
            api.get_dressing_protocol(UNKNOWN_PROTOCOL, DIRECTOR),
            "ERR_PROTOCOL_NOT_FOUND",
        ),
        (
            api.get_ostomy_education_plan(UNKNOWN_PLAN, DIRECTOR),
            "ERR_PLAN_NOT_FOUND",
        ),
    )
    for response, expected_error_id in probes:
        validate_error(response, expected_error_id, expected_status=404)
        _assert_bare_error_envelope(response)

    report = get_success_data(
        api.get_survey_round_unit_report(survey_round["id"], DIRECTOR)
    )
    assert report["round_id"] == survey_round["id"]
    assert report["round_type"] == "PREVALENCE"
    assert report["observation_total"] == 1, (
        "the computed sub-resource read answers for the round that exists"
    )

    reread_round = get_success_data(api.get_survey_round(survey_round["id"], DIRECTOR))
    assert reread_round["status"] == "OPEN"
    assert reread_round["observation_count"] == 1
    assert (
        get_success_data(api.get_survey_observation(observation["id"], DIRECTOR))["id"]
        == observation["id"]
    )
    assert (
        get_success_data(api.get_support_surface_order(order["id"], DIRECTOR))[
            "fulfillment_status"
        ]
        == "REQUESTED"
    )
    assert (
        get_success_data(api.get_formulary_product(product["id"], DIRECTOR))["status"]
        == "ACTIVE"
    )


def test_the_first_declared_unknown_reference_is_the_one_reported(api):
    """Two unknown references in one body, and the declaration order picks the code.

    PRD §2.5: "Foreign-key identifiers supplied inside a request body are resolved
    after every path identifier has resolved, and they are resolved in the order in
    which the endpoint declares them."
    PRD §2.5: "Identifiers embedded in a URL path are resolved strictly left to
    right, and the first one that fails to resolve determines the error."
    PRD §2.10 rung 5: "Every foreign-key identifier in the request body resolves,
    in the endpoint's declared field order — the per-type 404 codes, on
    `POST /patients`, `POST /woc-nurses`, `POST /consult-requests`,
    `POST /consult-requests/{consult_id}/assign`, `POST /skin-assessments`,
    `POST /pressure-injury-cases/{case_id}/rca-start`, `POST /survey-rounds`,
    `POST /survey-observations`, `POST /support-surface-orders`,
    `POST /dressing-protocols` and `POST /ostomy-education-plans`."
    PRD §2.10 rung 10: "The consult request's `status` is a legal starting state
    for the requested transition — `ERR_CONSULT_INVALID_STATE` (409), on
    `POST /consult-requests/{consult_id}/triage`, `/return`, `/resubmit`,
    `/assign`, `/escalate`, `/close` and `/cancel`, and also on
    `POST /skin-assessments`, `POST /dressing-protocols` and
    `POST /ostomy-education-plans`, each of which requires its referenced consult
    to be in a permitted state."
    PRD §3.4: "A new consult starts with `status` `REQUESTED`, `revision_count` 0,
    `escalation_count` 0 and `protocol_hold` false; `acuity_score`,
    `acuity_variant`, `priority_band`, `triaged_at`, `sla_due_at`,
    `assigned_nurse_id` and `closing_summary` are all null."
    PRD §3.4: "On success the nominated nurse's `active_consult_load` rises by 1 and
    that nurse's row is versioned."
    PRD §3.7: "Filing an observation raises the round's `observation_count` by 1 and
    versions the round."

    Design: Corner/errors/body_fk_probe_rejects_with_the_first_declared_unknown_foreign_key
    """
    unit = create_unit(
        api=api,
        unit_code="ERRP-U3",
        name="Error Probe ICU",
        bed_count=12,
        rental_budget_cap_cents=100000,
    )
    patient = create_patient(
        unit,
        api=api,
        mrn="ERRPMRN03",
        admitted_at="2026-07-31T00:00:00Z",
        device_related_risk=True,
    )
    nurse = create_candidate_nurse(unit, api=api, full_name="Pia Probe")
    nurse_headers = make_nurse_headers(nurse["id"])
    survey_round = open_round(
        create_round(
            [unit["id"]],
            api=api,
            round_type="PREVALENCE",
            window_start="2026-07-31T00:00:00Z",
            window_end="2026-08-02T00:00:00Z",
        ),
        api=api,
    )
    consult = create_consult(
        unit,
        patient,
        api=api,
        reported_stage="STAGE_1",
        clinical_note="Blanchable erythema over the right heel.",
    )
    assert consult["status"] == "REQUESTED", (
        "never triaged, so an assign call would violate the state gate if it got "
        "that far"
    )

    round_before_patient = api.create_survey_observation(
        create_survey_observation_payload(
            UNKNOWN_BODY_ROUND, unit["id"], UNKNOWN_BODY_PATIENT, nurse["id"]
        ),
        nurse_headers,
    )
    validate_error(
        round_before_patient, "ERR_SURVEY_ROUND_NOT_FOUND", expected_status=404
    )

    patient_before_observer = api.create_survey_observation(
        create_survey_observation_payload(
            survey_round["id"], unit["id"], UNKNOWN_BODY_PATIENT, UNKNOWN_BODY_NURSE
        ),
        nurse_headers,
    )
    validate_error(patient_before_observer, "ERR_PATIENT_NOT_FOUND", expected_status=404)

    consult_before_product = api.create_dressing_protocol(
        create_dressing_protocol_payload(
            UNKNOWN_BODY_CONSULT,
            UNKNOWN_BODY_PRODUCT,
            change_frequency_hours=24,
            units_per_change=1,
        ),
        nurse_headers,
    )
    validate_error(consult_before_product, "ERR_CONSULT_NOT_FOUND", expected_status=404)

    path_before_body = api.assign_consult_request(
        UNKNOWN_CONSULT, assign_consult_payload(UNKNOWN_BODY_NURSE), DIRECTOR
    )
    validate_error(path_before_body, "ERR_CONSULT_NOT_FOUND", expected_status=404)

    body_before_state = api.assign_consult_request(
        consult["id"], assign_consult_payload(UNKNOWN_BODY_NURSE), DIRECTOR
    )
    validate_error(body_before_state, "ERR_NURSE_NOT_FOUND", expected_status=404)

    _rows, observation_meta = validate_paginated(
        api.list_survey_observations(DIRECTOR, {"survey_round_id": survey_round["id"]})
    )
    assert observation_meta["total_count"] == 0
    assert (
        get_success_data(api.get_survey_round(survey_round["id"], DIRECTOR))[
            "observation_count"
        ]
        == 0
    )
    _protocols, protocol_meta = validate_paginated(
        api.list_dressing_protocols(DIRECTOR)
    )
    assert protocol_meta["total_count"] == 0

    untouched = get_success_data(api.get_consult_request(consult["id"], DIRECTOR))
    assert untouched["status"] == "REQUESTED"
    assert untouched["assigned_nurse_id"] is None
    assert untouched["version"] == 1
    assert (
        get_success_data(api.get_woc_nurse(nurse["id"], DIRECTOR))[
            "active_consult_load"
        ]
        == 0
    )


def test_no_headers_and_an_undeclared_role_both_fail_authentication(api):
    """A missing role and an invented role take the same 401, on reads and writes.

    PRD §2.1: "Every request to this API must carry two headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, naming the role that
    principal is acting in."
    PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the
    five role names below, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401) before any other processing occurs."
    PRD §2.10 rung 1: "Headers present and `X-User-Role` one of the five declared
    roles — `ERR_UNAUTHENTICATED` (401), on every endpoint."

    Design: Corner/errors/missing_or_unknown_role_header_rejected_unauthenticated
    """
    unit = create_unit(
        api=api,
        unit_code="AUTH-U1",
        name="Auth Probe Unit",
        bed_count=10,
        rental_budget_cap_cents=50000,
    )

    anonymous_write = api.create_unit(
        {
            "unit_code": "AUTH-U2",
            "name": "Header-less Unit",
            "bed_count": 10,
        },
        NO_HEADERS,
    )
    validate_error(anonymous_write, "ERR_UNAUTHENTICATED", expected_status=401)

    invented_role_write = api.create_unit(
        {
            "unit_code": "AUTH-U3",
            "name": "Unknown Role Unit",
            "bed_count": 10,
        },
        make_unknown_role_headers(),
    )
    validate_error(invented_role_write, "ERR_UNAUTHENTICATED", expected_status=401)
    assert invented_role_write.status_code != 403, (
        "an undeclared role never reaches the authorisation check"
    )

    anonymous_read = api.list_units(NO_HEADERS)
    validate_error(anonymous_read, "ERR_UNAUTHENTICATED", expected_status=401)

    rows, meta = validate_paginated(api.list_units(MATERIALS))
    assert meta["total_count"] == 1, "neither refused create left a row behind"
    assert rows[0]["id"] == unit["id"]


def test_the_charge_nurse_is_refused_on_every_other_roles_exclusive_write(api):
    """Four denials and two acceptances for one principal in one run.

    PRD §2.1: "If both headers are well-formed but the named role is not among the
    roles authorized for the target operation (see the table in §4), the request is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.10 rung 2: "The caller's role appears in the target endpoint's
    authorized-role list — `ERR_UNAUTHORIZED` (403), on every endpoint."
    PRD §2.1: "This role admits and discharges patients, raises consult requests for
    the patients on its own unit, resubmits consults that were returned for more
    information, and reads unit-level survey reporting."
    PRD §3.4: "Triage sets `triaged_at` to the logical clock and derives
    `sla_due_at` as `triaged_at` plus the band's response allowance — 4 hours for
    `P1`, a full day for `P2`, and three days for `P3`."
    PRD §3.4: "A new consult starts with `status` `REQUESTED`, `revision_count` 0,
    `escalation_count` 0 and `protocol_hold` false; `acuity_score`,
    `acuity_variant`, `priority_band`, `triaged_at`, `sla_due_at`,
    `assigned_nurse_id` and `closing_summary` are all null."
    PRD §3.2: "A patient's `status` begins at `ADMITTED`."

    Design: Corner/rbac/unit_charge_cannot_perform_other_roles_exclusive_operations
    """
    unit = create_unit(
        api=api,
        unit_code="RBAC-U1",
        name="RBAC Probe Med-Surg",
        bed_count=20,
        rental_budget_cap_cents=100000,
    )
    charge = make_unit_charge_headers(unit["id"])
    patient = create_patient(
        unit, api=api, mrn="RBACMRN01", admitted_at="2026-07-31T00:00:00Z"
    )
    consult = create_consult(
        unit,
        patient,
        api=api,
        clinical_note="Sacral redness that does not blanch.",
    )

    denied_triage = api.triage_consult_request(consult["id"], charge)
    validate_error(denied_triage, "ERR_UNAUTHORIZED", expected_status=403)
    assert denied_triage.status_code != 409, (
        "the role check precedes the consult-state check, so a REQUESTED consult "
        "never reports an invalid state here"
    )

    denied_unit = api.create_unit(
        {
            "unit_code": "RBAC-U9",
            "name": "Unit The Charge Nurse Should Not Create",
            "bed_count": 8,
        },
        charge,
    )
    validate_error(denied_unit, "ERR_UNAUTHORIZED", expected_status=403)

    denied_surface = api.create_support_surface(
        {
            "asset_tag": "RBAC-S9",
            "surface_class": "FOAM_OVERLAY",
            "daily_rate_cents": 4000,
            "vendor_name": "Probe Rentals",
        },
        charge,
    )
    validate_error(denied_surface, "ERR_UNAUTHORIZED", expected_status=403)

    denied_clock = api.set_clock(set_clock_payload("2026-08-09T00:00:00Z"), charge)
    validate_error(denied_clock, "ERR_UNAUTHORIZED", expected_status=403)

    own_write = validate_success(
        api.create_patient(
            create_patient_payload(
                unit["id"], mrn="RBACMRN02", admitted_at="2026-07-31T00:00:00Z"
            ),
            charge,
        ),
        expected_status=201,
    )
    assert own_write["status"] == "ADMITTED", "admitting is this role's own operation"

    shared_read, meta = validate_paginated(
        api.list_consult_requests(charge, {"requesting_unit_id": unit["id"]})
    )
    assert meta["total_count"] == 1, "every listing is shared with the charge nurse"
    assert shared_read[0]["id"] == consult["id"]

    untouched = get_success_data(api.get_consult_request(consult["id"], DIRECTOR))
    assert untouched["status"] == "REQUESTED"
    assert untouched["acuity_score"] is None
    assert untouched["priority_band"] is None
    assert untouched["version"] == 1
    _units, unit_meta = validate_paginated(api.list_units(DIRECTOR))
    assert unit_meta["total_count"] == 1, "the refused unit create wrote nothing"
    _surfaces, surface_meta = validate_paginated(api.list_support_surfaces(DIRECTOR))
    assert surface_meta["total_count"] == 0, "the refused fleet create wrote nothing"

    nurse = create_trainee_nurse(unit, api=api, full_name="Tara Clock")
    second_consult = create_consult(
        unit,
        own_write,
        api=api,
        clinical_note="Second consult, raised only to read the clock.",
    )
    triaged = triage_consult(second_consult, nurse, api=api)
    assert as_instant(triaged["triaged_at"]) == as_instant("2026-08-01T00:00:00Z"), (
        "the refused clock call never moved the logical clock off its default"
    )


def test_order_creation_is_shared_but_approval_is_the_coordinators_alone(api):
    """The one write two roles share, and the approval only one of them may make.

    PRD §3.8: "Either a `MaterialsCoordinator` or a `WocNurse` may raise a rental
    order, naming the `patient_id`, the `unit_id` whose ledger will be charged, the
    `support_surface_id` of the physical asset, a `rental_start`, a `rental_end`
    and an `authorized_days` figure; a `consult_request_id` may optionally be
    supplied to tie the rental to the consult that justifies it."
    PRD §3.8: "A `MaterialsCoordinator` approves a `REQUESTED` order, supplying the
    `expected_unit_version` of §2.6 and optionally a `director_override` boolean."
    PRD §2.10 rung 2: "The caller's role appears in the target endpoint's
    authorized-role list — `ERR_UNAUTHORIZED` (403), on every endpoint."
    PRD §3.8: "Approval moves `fulfillment_status` `REQUESTED → APPROVED` and, in
    the same breath, `billing_status` `UNBILLED → ENCUMBERED`. The unit's
    `rental_encumbered_cents` rises by the order's `authorized_cost_cents`,
    `rental_available_cents` is recomputed and the unit is versioned."
    PRD §3.8: "The asset moves to `IN_USE` with its `occupied_until` and
    `available_from` written as described above and is versioned."
    PRD §3.8: "A new asset starts with `status` `AVAILABLE` and with
    `occupied_until` and `available_from` both null."
    PRD §3.8: "First, `billable_days`: the whole hours between `rental_start` and
    `rental_end` divided by 24, with any partial day rounded **up**, so a 25-hour
    rental is 2 billable days."
    PRD §3.8: "Each billable day is numbered from 1, and the rate for a day is the
    asset's `daily_rate_cents` at full price for days 1 through 7, at 90 percent of
    it for days 8 through 21, and at 75 percent of it for every day from 22 onward."
    PRD §3.8: "The fee percentage is keyed on the **pre-fee**
    `projected_cost_cents`, never on the post-fee total: the percentage is 8 percent
    when `projected_cost_cents` is below 50000 cents, 5 percent when it is at least
    50000 and below 200000, and 3 percent when it is 200000 or more."
    PRD §3.8: "`authorized_cost_cents` is then exactly `projected_cost_cents` plus
    `vendor_service_fee_cents`, by integer addition."
    PRD §3.8: "The order starts with `fulfillment_status` `REQUESTED` and
    `billing_status` `UNBILLED`, and no money moves at creation — creation is a
    costing exercise, not a ledger event."

    Design: Corner/rbac/materials_coordinator_cannot_write_clinical_rows_while_order_creation_stays_shared
    """
    unit = create_unit(
        api=api,
        unit_code="RBAC-U2",
        name="RBAC Probe Surgical",
        bed_count=22,
        rental_budget_cap_cents=400000,
    )
    patient = create_patient(
        unit,
        api=api,
        mrn="RBACMRN03",
        admitted_at="2026-07-31T00:00:00Z",
        comorbidity_count=1,
    )
    nurse = create_trainee_nurse(unit, api=api, full_name="Rita Shared")
    nurse_headers = make_nurse_headers(nurse["id"])
    first_surface = create_surface(
        api=api,
        asset_tag="RBAC-S1",
        surface_class="LOW_AIR_LOSS",
        daily_rate_cents=10000,
        vendor_name="Probe Rentals",
    )
    second_surface = create_surface(
        api=api,
        asset_tag="RBAC-S2",
        surface_class="LOW_AIR_LOSS",
        daily_rate_cents=10000,
        vendor_name="Probe Rentals",
    )
    unit_version = read_unit_version(unit["id"], api=api)
    patient_version = read_patient_version(patient["id"], api=api)

    denied_staging = api.create_skin_assessment(
        create_skin_assessment_payload(
            UNKNOWN_BODY_CONSULT,
            patient["id"],
            patient_version,
            measured_area_cm2=4.0,
        ),
        MATERIALS,
    )
    validate_error(denied_staging, "ERR_UNAUTHORIZED", expected_status=403)
    assert denied_staging.status_code != 404, (
        "the role check fires before the unknown consult reference is looked up"
    )

    denied_consult = api.create_consult_request(
        create_consult_request_payload(
            patient["id"],
            unit["id"],
            clinical_note="Materials should not be able to open a consult.",
        ),
        MATERIALS,
    )
    validate_error(denied_consult, "ERR_UNAUTHORIZED", expected_status=403)

    coordinator_order = create_order(
        unit,
        patient,
        first_surface,
        api=api,
        rental_start="2026-08-02T00:00:00Z",
        rental_end="2026-08-05T00:00:00Z",
        authorized_days=3,
    )
    nurse_order = create_order(
        unit,
        patient,
        second_surface,
        api=api,
        headers=nurse_headers,
        rental_start="2026-08-02T00:00:00Z",
        rental_end="2026-08-05T00:00:00Z",
        authorized_days=3,
    )
    for order in (coordinator_order, nurse_order):
        assert order["billable_days"] == 3
        assert order["projected_cost_cents"] == 30000
        assert order["vendor_service_fee_cents"] == 2400
        assert order["authorized_cost_cents"] == 32400, (
            "the shared endpoint costs the rental identically for either role"
        )

    denied_approval = api.approve_support_surface_order(
        nurse_order["id"], {"expected_unit_version": unit_version}, nurse_headers
    )
    validate_error(denied_approval, "ERR_UNAUTHORIZED", expected_status=403)

    approved = validate_success(
        api.approve_support_surface_order(
            coordinator_order["id"],
            {"expected_unit_version": unit_version},
            MATERIALS,
        )
    )
    assert approved["fulfillment_status"] == "APPROVED"
    assert approved["billing_status"] == "ENCUMBERED"

    charged = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert charged["rental_encumbered_cents"] == 32400
    assert charged["rental_committed_cents"] == 0
    assert charged["rental_available_cents"] == 367600, "400000 cap less 32400"
    assert charged["version"] == unit_version + 1, "one approval, one unit version"

    stalled = get_success_data(
        api.get_support_surface_order(nurse_order["id"], DIRECTOR)
    )
    assert stalled["fulfillment_status"] == "REQUESTED"
    assert stalled["billing_status"] == "UNBILLED"
    assert (
        get_success_data(api.get_support_surface(second_surface["id"], MATERIALS))[
            "status"
        ]
        == "AVAILABLE"
    ), "the refused approval never occupied the asset"
    assert (
        get_success_data(api.get_support_surface(first_surface["id"], MATERIALS))[
            "status"
        ]
        == "IN_USE"
    )

    _assessments, assessment_meta = validate_paginated(
        api.list_skin_assessments(DIRECTOR)
    )
    assert assessment_meta["total_count"] == 0
    _consults, consult_meta = validate_paginated(api.list_consult_requests(DIRECTOR))
    assert consult_meta["total_count"] == 0


def test_the_operator_owns_only_the_clock_and_nothing_else(api):
    """One endpoint for one role, and the clock stays where that role put it.

    PRD §2.1: "When `X-User-Role` is `SystemOperator`, `X-User-ID` is an opaque
    operator identifier as well; this principal exists solely to position the
    server's logical clock and holds neither clinical nor fiscal authority."
    PRD §2.4: "A `SystemOperator`-only administrative capability repositions the
    clock to a supplied instant, taking a single `to_iso8601` field in its payload
    and answering with an object whose sole member is `current_utc`, the instant
    the clock now reads."
    PRD §3.2: "The `admitted_at` value is an ISO 8601 UTC instant at second
    precision (fractional seconds are accepted but not required) and must not be
    later than the logical clock at the moment of admission; it anchors the
    present-on-admission documentation window that §3.6 depends on."
    PRD §3.4: "Triage sets `triaged_at` to the logical clock and derives
    `sla_due_at` as `triaged_at` plus the band's response allowance — 4 hours for
    `P1`, a full day for `P2`, and three days for `P3`."
    PRD §3.2: "A patient's `status` begins at `ADMITTED`."
    PRD §2.10 rung 2: "The caller's role appears in the target endpoint's
    authorized-role list — `ERR_UNAUTHORIZED` (403), on every endpoint."

    Design: Corner/rbac/system_operator_cannot_read_or_write_business_rows_and_owns_the_clock
    """
    unit = create_unit(
        api=api,
        unit_code="RBAC-U3",
        name="RBAC Probe Rehab",
        bed_count=14,
        rental_budget_cap_cents=100000,
    )
    charge = make_unit_charge_headers(unit["id"])
    patient = create_patient(
        unit, api=api, mrn="RBACMRN04", admitted_at="2026-07-31T00:00:00Z"
    )

    denied_unit = api.create_unit(
        {
            "unit_code": "RBAC-U8",
            "name": "Unit The Operator Should Not Create",
            "bed_count": 6,
        },
        SYSOP,
    )
    validate_error(denied_unit, "ERR_UNAUTHORIZED", expected_status=403)

    denied_consult = api.create_consult_request(
        create_consult_request_payload(
            patient["id"],
            unit["id"],
            reported_stage="STAGE_1",
            clinical_note="The operator has no clinical authority.",
        ),
        SYSOP,
    )
    validate_error(denied_consult, "ERR_UNAUTHORIZED", expected_status=403)

    denied_read = api.list_units(SYSOP)
    validate_error(denied_read, "ERR_UNAUTHORIZED", expected_status=403)

    moved = validate_success(
        api.set_clock(set_clock_payload("2026-08-03T00:00:00Z"), SYSOP)
    )
    assert as_instant(moved["current_utc"]) == as_instant("2026-08-03T00:00:00Z")

    denied_director_clock = api.set_clock(
        set_clock_payload("2026-08-10T00:00:00Z"), DIRECTOR
    )
    validate_error(denied_director_clock, "ERR_UNAUTHORIZED", expected_status=403)

    later_admission = validate_success(
        api.create_patient(
            create_patient_payload(
                unit["id"], mrn="RBACMRN05", admitted_at="2026-08-02T00:00:00Z"
            ),
            charge,
        ),
        expected_status=201,
    )
    assert later_admission["status"] == "ADMITTED", (
        "an admission on 2026-08-02 is only legal once the clock has passed it, so "
        "the operator's reposition landed"
    )

    _units, unit_meta = validate_paginated(api.list_units(DIRECTOR))
    assert unit_meta["total_count"] == 1, "the refused unit create wrote nothing"
    _consults, consult_meta = validate_paginated(api.list_consult_requests(DIRECTOR))
    assert consult_meta["total_count"] == 0, "the refused consult wrote nothing"
    _patients, patient_meta = validate_paginated(api.list_patients(DIRECTOR))
    assert patient_meta["total_count"] == 2, "exactly the two accepted admissions"

    nurse = create_trainee_nurse(unit, api=api, full_name="Tara Clock")
    consult = create_consult(
        unit,
        patient,
        api=api,
        clinical_note="Raised only to read the logical clock back.",
    )
    triaged = triage_consult(consult, nurse, api=api)
    assert as_instant(triaged["triaged_at"]) == as_instant("2026-08-03T00:00:00Z"), (
        "the clock is where the operator left it, not where the director asked"
    )

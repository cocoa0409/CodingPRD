"""The declared entity surface: echoed inputs, computed fields, system-minted
identity, the list envelope, and the shape/FK rejection ladder."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_candidate,
    add_proctor,
    assign_code,
    factories as f,
    get_success_data,
    is_valid_uuid,
    make_provider_admin_headers,
    purchase_batch,
    schedule_session,
    setup_landscape,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["platform_admin_headers"]


def test_jurisdiction_creation_echoes_every_declared_lever_it_was_given(api):
    """All ten inputs come back unchanged on the 201, wrapped in the object
    envelope, with the four common fields added on top.

    PRD: "`id` is a server-minted UUID with no type prefix; clients never supply
    it."

    PRD: "`version` is an integer that starts at 1 when the resource is created and
    increments by exactly 1 on every mutation of that resource; `updated_at` is
    refreshed to the current logical clock on the same mutation."

    Design: Corner/entities/jurisdiction_creation_returns_declared_config_in_object_envelope
    """
    payload = f.create_jurisdiction_payload(
        name="Travis County Health TX", jurisdiction_code="TX-TRAVIS",
        accepted_accreditation_bodies=["ANAB_CFP"], accepted_languages=["EN", "ES"],
        accepts_remote_proctoring=True, min_passing_score_override=None,
        requires_local_registration=True, posting_deadline_days=30,
        recert_cycle_months=60, exam_fee_surcharge_pct=0.045)

    response = api.create_jurisdiction(payload, _ADMIN)

    data = validate_success(response, 201)
    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"]
    assert data["jurisdiction_code"] == "TX-TRAVIS"
    assert data["accepted_accreditation_bodies"] == ["ANAB_CFP"]
    assert data["accepted_languages"] == ["EN", "ES"]
    assert data["posting_deadline_days"] == 30
    assert data["recert_cycle_months"] == 60
    assert float(data["exam_fee_surcharge_pct"]) == 0.045
    assert data["min_passing_score_override"] is None
    assert is_valid_uuid(data["id"]) and "_" not in data["id"]
    assert data["version"] == 1
    assert data["created_at"] == data["updated_at"]


def test_reading_a_provider_returns_the_stored_ledger_triple(api):
    """The read reports what two postings left behind and does not recompute or
    mutate anything.

    PRD: "`credit_balance_cents` is never written directly by any endpoint; it is
    recomputed from the two lifetime counters, and no entity other than the provider
    itself may write any of the three fields."

    PRD: "Registration opens the prepayment ledger described in §2.7 with
    `lifetime_credited_cents`, `lifetime_charged_cents` and `credit_balance_cents`
    all at zero."

    Design: Corner/entities/get_training_provider_returns_stored_ledger_triple
    """
    env = setup_landscape(provider={"legal_name": "Lone Star Food Safety"})
    purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 1}])
    headers = env["provider_headers"]

    data = get_success_data(api.get_training_provider(env["provider"]["id"], headers))

    assert data["lifetime_credited_cents"] == 500000
    assert data["lifetime_charged_cents"] == 3762
    assert data["credit_balance_cents"] == 496238
    assert data["legal_name"] == "Lone Star Food Safety"
    assert data["jurisdiction_id"] == env["jurisdiction"]["id"]
    again = get_success_data(api.get_training_provider(env["provider"]["id"], headers))
    assert again["version"] == data["version"]


def test_candidate_listing_windows_report_the_filtered_total_and_has_more(api):
    """total_count counts the filtered population, not the page, and the two
    windows partition the three rows.

    PRD: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`; `total_count` is the number of rows matching the
    filters before the window is applied, and `has_more` is true when rows remain
    beyond the current window."

    Design: Corner/entities/list_candidates_pagination_reports_total_count_and_has_more
    """
    env = setup_landscape(with_site=False)
    minted = {add_candidate(env)["id"] for _ in range(3)}
    params = {"training_provider_id": env["provider"]["id"], "limit": 2}

    first_response = api.list_candidates(env["provider_headers"],
                                         params=dict(params, offset=0))
    second_response = api.list_candidates(env["provider_headers"],
                                          params=dict(params, offset=2))

    first, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array"
    assert len(first) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert (first_meta["limit"], first_meta["offset"]) == (2, 0)

    second, second_meta = validate_paginated(second_response)
    assert len(second) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2

    paged = [row["id"] for row in first] + [row["id"] for row in second]
    assert len(set(paged)) == 3
    assert set(paged) == minted


def test_a_well_formed_unknown_session_id_answers_the_entity_specific_404(api):
    """The path identifier is resolved against ExamSession specifically, so the
    answer names that entity rather than a generic request error.

    PRD: "6. Path identifiers resolve, validated strictly left to right, so that on
    a nested path the leftmost unresolvable identifier is the one reported — the
    matching `ERR_..._NOT_FOUND`."

    PRD: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/get_exam_session_with_unknown_id_returns_exam_session_not_found
    """
    response = api.get_exam_session(NON_EXISTENT_UUID, _ADMIN)

    error = validate_error(response, "ERR_EXAM_SESSION_NOT_FOUND", 404)
    assert error["message"].strip()
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["data"].keys()) == {"error_id", "message"}


def test_a_candidate_without_a_preferred_language_is_a_shape_violation(api):
    """preferred_language has no default, so omitting it is rejected on shape and
    the otherwise-valid foreign keys are never reached.

    PRD: "4. Request shape: the body parses, every required field is present, every
    enumerated value is a declared member, numeric fields fall in range, datetimes
    are ISO 8601 UTC, `id_document_expires_on` is a `YYYY-MM-DD` date, and the
    entries of `line_items` carry distinct `bundle_type` values —
    `ERR_INVALID_REQUEST`."

    PRD: "A `ProviderAdmin` enrols a candidate under its own provider by supplying
    a `full_name` — the legal name that will be printed on the certificate — an
    `email` that must contain an `@` and must be unique across all candidates, a
    `preferred_language`, the `training_provider_id` of the enrolling provider, and
    the `jurisdiction_id` whose acceptance rules will govern this candidate for the
    whole lifecycle."

    Design: Corner/entities/create_candidate_with_missing_required_field_is_rejected
    """
    env = setup_landscape(with_site=False)

    response = api.create_candidate({
        "full_name": "Ana Ruiz",
        "email": "ana@x.test",
        "training_provider_id": env["provider"]["id"],
        "jurisdiction_id": env["jurisdiction"]["id"],
    }, env["provider_headers"])

    validate_error(response, "ERR_INVALID_REQUEST", 400)
    _, meta = validate_paginated(api.list_candidates(
        env["provider_headers"], params={"training_provider_id": env["provider"]["id"]}))
    assert meta["total_count"] == 0


def test_the_omitted_jurisdiction_levers_take_their_documented_defaults(api):
    """Only the four mandatory fields are supplied, and the defaulted 0.0 surcharge
    is then load-bearing on a real purchase.

    PRD: "`accepts_remote_proctoring` defaults to true and decides whether remotely
    proctored sittings may be scheduled for candidates governed here."

    PRD: "`exam_fee_surcharge_pct` defaults to 0.0, must lie between 0.0 and 0.25
    inclusive with at most three decimals, and is the per-line surcharge applied to
    access-code purchases made by providers whose home jurisdiction this is."

    PRD: "`pretest_item_count` defaults to 0, may be at most 40, and counts
    unscored trial items that never enter any scaled score in either numerator or
    denominator."

    Design: Corner/entities/jurisdiction_optional_config_defaults_applied_when_omitted
    """
    jurisdiction = get_success_data(api.create_jurisdiction({
        "name": "Bare County Health", "jurisdiction_code": "BARE-01",
        "accepted_accreditation_bodies": ["ANAB_CFP"],
        "accepted_languages": ["EN"]}, _ADMIN), 201)

    assert jurisdiction["accepts_remote_proctoring"] is True
    assert jurisdiction["requires_local_registration"] is True
    assert jurisdiction["posting_deadline_days"] == 30
    assert jurisdiction["recert_cycle_months"] == 60
    assert float(jurisdiction["exam_fee_surcharge_pct"]) == 0.0
    assert jurisdiction["min_passing_score_override"] is None

    provider = get_success_data(api.create_training_provider({
        "legal_name": "Bare Provider", "jurisdiction_id": jurisdiction["id"],
        "contact_email": "ops@bare.test"}, _ADMIN), 201)
    get_success_data(api.create_credit_adjustment(
        provider["id"], {"amount_cents": 10000, "memo": "seed"}, _ADMIN))
    form = get_success_data(api.create_exam_form({
        "form_code": "FM-EN-01", "version_label": "2026.1", "language": "EN",
        "accreditation_body": "ANAB_CFP", "scored_item_count": 80,
        "national_cut_score": 70, "base_minutes": 120}, _ADMIN), 201)
    assert form["pretest_item_count"] == 0
    assert form["translated_extra_minutes"] == 0
    assert form["status"] == "ACTIVE"

    batch = get_success_data(api.create_access_code_batch({
        "training_provider_id": provider["id"], "exam_form_id": form["id"],
        "line_items": [{"bundle_type": "EXAM_ONLY", "quantity": 1}],
        "expires_at": "2027-06-30T00:00:00Z"},
        make_provider_admin_headers(provider["id"])), 201)

    assert batch["total_price_cents"] == 3600
    assert get_success_data(api.get_training_provider(
        provider["id"], _ADMIN))["credit_balance_cents"] == 6400


def test_batch_counters_and_price_are_computed_server_side(api):
    """The request carries only line_items and expires_at; every counter, the price
    and the three void fields are the server's own.

    PRD: "The batch opens with `available_count` equal to `quantity_purchased`,
    `assigned_count`, `consumed_count` and `voided_count` all at zero, `status`
    `ACTIVE`, and `void_gross_credit_cents`, `void_restock_fee_cents` and
    `void_net_credit_cents` all null."

    PRD: "The batch's `quantity_purchased` is the plain sum of the `quantity`
    values across all lines."

    Design: Corner/entities/batch_counters_and_price_are_computed_not_supplied
    """
    env = setup_landscape(with_site=False)

    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 3}])

    assert batch["quantity_purchased"] == 3
    assert batch["total_price_cents"] == 11286
    assert batch["available_count"] == 3
    assert (batch["assigned_count"], batch["consumed_count"], batch["voided_count"]) == (0, 0, 0)
    assert batch["status"] == "ACTIVE"
    assert batch["void_gross_credit_cents"] is None
    assert batch["void_restock_fee_cents"] is None
    assert batch["void_net_credit_cents"] is None
    assert get_success_data(api.get_training_provider(
        env["provider"]["id"], env["admin_headers"]))["credit_balance_cents"] == 488714

    codes, meta = validate_paginated(api.list_access_codes(
        env["provider_headers"], params={"batch_id": batch["id"]}))
    assert meta["total_count"] == 3
    assert {code["status"] for code in codes} == {"AVAILABLE"}
    assert all(code["candidate_id"] is None for code in codes)


def test_proctor_status_and_the_minted_code_are_never_client_supplied(api):
    """A provider cannot open a proctor in REGISTERED, and the code string it
    receives on assignment is minted by the server.

    PRD: "The registration opens with `registration_status` `PENDING`, `risk_score`
    at 0.00, `reserved_minutes` at zero, `substantiated_incident_weight_total` at
    zero, `proctored_session_count` at zero, `risk_variant_applied`
    `ROLLING_WINDOW` and `suspended_reason` null."

    PRD: "The winning code moves `AVAILABLE → ASSIGNED` with its `candidate_id` set
    and `assigned_at` set to the logical clock; the batch's `available_count` falls
    by one, its `assigned_count` rises by one, and its `version` increments by
    one."

    Design: Corner/entities/proctor_identity_status_and_timestamps_are_system_minted
    """
    env = setup_landscape(with_site=False)
    candidate = add_candidate(env)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 2}])
    assert batch["total_price_cents"] == 7524

    proctor = get_success_data(api.create_proctor(
        f.create_proctor_payload(env["provider"]["id"], full_name="Ivan Cole",
                                 roles_held=["PROCTOR"], languages_certified=["EN"],
                                 remote_certified=False),
        env["provider_headers"]), 201)

    assert proctor["registration_status"] == "PENDING"
    assert proctor["suspended_reason"] is None
    assert proctor["proctored_session_count"] == 0
    assert proctor["substantiated_incident_weight_total"] == 0
    assert float(proctor["risk_score"]) == 0.00
    assert proctor["risk_variant_applied"] == "ROLLING_WINDOW"
    assert proctor["reserved_minutes"] == 0
    assert is_valid_uuid(proctor["id"]) and "_" not in proctor["id"]
    assert proctor["version"] == 1
    assert proctor["created_at"] == proctor["updated_at"]

    code = get_success_data(api.assign_access_code(
        batch["id"], f.create_assignment_payload(candidate["id"], batch["version"]),
        env["provider_headers"]))

    assert isinstance(code["code"], str) and code["code"].strip()
    assert code["bundle_type"] == "EXAM_ONLY"
    assert code["assigned_at"] == "2026-08-01T00:00:00Z"
    assert code["status"] == "ASSIGNED"
    assert code["assignment_release_count"] == 0
    codes, _ = validate_paginated(api.list_access_codes(
        env["provider_headers"], params={"batch_id": batch["id"]}))
    assert len({row["code"] for row in codes}) == 2


def test_out_of_range_numbers_and_unknown_enum_members_are_shape_violations(api):
    """Three separate constraint families — two numeric bands and one enum — all
    answer the request-shape error and persist nothing.

    PRD: "A multiplier outside the 1.00-to-2.00 band is a shape violation and
    answers `ERR_INVALID_REQUEST` (HTTP 400)."

    PRD: "`scored_item_count` — between 10 and 200 — is the number of scored items
    and becomes the denominator of every scaled score computed from this form."

    PRD: "A language is one of `EN`, `ES`, `ZH` or `VI`."

    Design: Corner/entities/out_of_range_numbers_and_unknown_enum_values_are_rejected
    """
    jurisdiction = get_success_data(api.create_jurisdiction(
        f.create_jurisdiction_payload(), _ADMIN), 201)
    provider = get_success_data(api.create_training_provider(
        f.create_training_provider_payload(jurisdiction["id"]), _ADMIN), 201)
    provider_headers = make_provider_admin_headers(provider["id"])
    candidate = get_success_data(api.create_candidate(
        f.create_candidate_payload(provider["id"], jurisdiction["id"]),
        provider_headers), 201)

    too_generous = api.create_accommodation_request(
        f.create_accommodation_request_payload(candidate["id"],
                                               requested_multiplier=2.5),
        provider_headers)
    too_few_items = api.create_exam_form(
        f.create_exam_form_payload(form_code="FM-TINY", scored_item_count=5), _ADMIN)
    unknown_language = api.create_exam_form(
        f.create_exam_form_payload(form_code="FM-FR-01", language="FR"), _ADMIN)

    validate_error(too_generous, "ERR_INVALID_REQUEST", 400)
    validate_error(too_few_items, "ERR_INVALID_REQUEST", 400)
    validate_error(unknown_language, "ERR_INVALID_REQUEST", 400)

    _, requests_meta = validate_paginated(api.list_accommodation_requests(
        provider_headers, params={"candidate_id": candidate["id"]}))
    assert requests_meta["total_count"] == 0
    _, forms_meta = validate_paginated(api.list_exam_forms(_ADMIN))
    assert forms_meta["total_count"] == 0


def test_body_foreign_keys_resolve_in_the_order_the_input_list_declares(api):
    """With both body FKs unknown the earlier field decides the 404, and the answer
    is unchanged when only that earlier field is unknown.

    PRD: "7. Body foreign keys resolve, validated in the order the fields appear in
    that endpoint's input list — the matching `ERR_..._NOT_FOUND`."

    PRD: "Nothing later in the list may mask anything earlier in it."

    Design: Corner/entities/candidate_body_foreign_keys_are_validated_left_to_right_not_found
    """
    jurisdiction = get_success_data(api.create_jurisdiction(
        f.create_jurisdiction_payload(), _ADMIN), 201)
    ghost_provider = "11111111-1111-4111-8111-111111111111"
    ghost_jurisdiction = "22222222-2222-4222-8222-222222222222"
    headers = make_provider_admin_headers(ghost_provider)

    both_unknown = api.create_candidate(
        f.create_candidate_payload(ghost_provider, ghost_jurisdiction), headers)
    only_provider_unknown = api.create_candidate(
        f.create_candidate_payload(ghost_provider, jurisdiction["id"]), headers)

    validate_error(both_unknown, "ERR_TRAINING_PROVIDER_NOT_FOUND", 404)
    validate_error(only_provider_unknown, "ERR_TRAINING_PROVIDER_NOT_FOUND", 404)
    _, meta = validate_paginated(api.list_candidates(_ADMIN))
    assert meta["total_count"] == 0


def test_the_sitting_junction_is_reverse_queryable_from_every_link(api):
    """Each of the sitting's six references is reachable through a declared filter,
    and two filters together intersect rather than union.

    PRD: "Sittings may be listed with optional `candidate_id`, `exam_form_id`,
    `access_code_id`, `testing_site_id`, `proctor_id`, `accommodation_request_id`,
    `session_status` and `proctoring_status` filters."

    PRD: "Filters on a list endpoint compose conjunctively: a request supplying both
    `training_provider_id` and `status` returns only rows matching both."

    Design: Corner/entities/exam_session_graph_links_are_reverse_queryable_from_every_filter
    """
    env = setup_landscape(testing_site={"seat_count": 2})
    candidate = add_candidate(env)
    proctor = add_proctor(env)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 1}])
    code, batch = assign_code(env, batch, candidate)
    session = schedule_session(env, candidate, code, "2026-09-10T09:00:00Z",
                               proctor=proctor)
    provider_headers = env["provider_headers"]

    by_proctor, proctor_meta = validate_paginated(api.list_exam_sessions(
        provider_headers, params={"proctor_id": proctor["id"]}))
    assert proctor_meta["total_count"] == 1
    assert by_proctor[0]["id"] == session["id"]

    intersected, intersected_meta = validate_paginated(api.list_exam_sessions(
        provider_headers, params={"access_code_id": code["id"],
                                  "testing_site_id": env["testing_site"]["id"]}))
    assert intersected_meta["total_count"] == 1
    assert intersected[0]["id"] == session["id"]

    codes, codes_meta = validate_paginated(api.list_access_codes(
        provider_headers, params={"candidate_id": candidate["id"]}))
    assert codes_meta["total_count"] == 1
    assert codes[0]["id"] == code["id"]
    assert codes[0]["status"] == "ASSIGNED"

    echoed = get_success_data(api.get_exam_session(session["id"], provider_headers))
    assert echoed["candidate_id"] == candidate["id"]
    assert echoed["exam_form_id"] == env["exam_form"]["id"]
    assert echoed["access_code_id"] == code["id"]
    assert echoed["testing_site_id"] == env["testing_site"]["id"]
    assert echoed["proctor_id"] == proctor["id"]
    assert echoed["accommodation_request_id"] is None

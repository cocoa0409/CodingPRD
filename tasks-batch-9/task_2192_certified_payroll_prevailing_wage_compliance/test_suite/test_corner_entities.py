"""Entity-shape corners: stored fields, defaults, computed fields and topology."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_timestamp_format,
    build_assignment,
    build_contractor,
    build_line,
    build_staff,
    build_submission,
    build_worker,
    finalize,
    fringe_plan_payload,
    get_success_data,
    is_valid_uuid,
    make_preparer_headers,
    setup_env,
    validate_error,
    validate_paginated,
    validate_success,
    wage_determination_payload,
    wage_rate_payload,
)


def test_creating_a_reporting_portal_echoes_every_declared_field(api, portal_admin_headers):
    """A 201 carries back the portal's own settings plus a minted id and created_at.

    PRD 3.4: "A `PortalAdmin` registers a portal with a `portal_code` — a short code such as
    `LCPTRACKER_CA`, unique across all portals and between 3 and 40 characters — and a
    `submission_format` describing the wire format the portal accepts for a weekly certified
    payroll, which is one of `WH347_PDF`, `XML_LCP` or `CSV_FLAT`." PRD 3.7: "a portal declares
    a `cutoff_offset_days` ... and a `grace_hours` value ... A portal also declares
    `requires_notarized_statement`, a flag defaulting to false".

    Design: Corner/entities/create_reporting_portal_returns_201_with_stored_fields
    """
    resp = api.create_reporting_portal(
        {
            "portal_code": "LCPTRACKER_CA",
            "submission_format": "XML_LCP",
            "cutoff_offset_days": 10,
            "grace_hours": 0,
            "requires_notarized_statement": False,
        },
        portal_admin_headers,
    )
    portal = get_success_data(resp, expected_status=201)
    validate_success(resp, expected_status=201)
    assert portal["portal_code"] == "LCPTRACKER_CA"
    assert portal["submission_format"] == "XML_LCP"
    assert portal["cutoff_offset_days"] == 10
    assert portal["grace_hours"] == 0
    assert portal["requires_notarized_statement"] is False
    assert is_valid_uuid(portal["id"])
    assert_timestamp_format(portal["created_at"])


def test_reading_a_fresh_contractor_shows_its_zeroed_compliance_counters(
    api, officer_headers, portal_admin_headers
):
    """The stored inputs read back intact and every derived counter is at its initial value.

    PRD 3.2: "A newly registered contractor always starts with `debarment_status` `CLEAR`, a
    `debarment_risk_score` of 0, a null `last_finding_at`, and zeroed
    `open_critical_finding_count` and `outstanding_restitution_cents`." PRD 2.4: "`version`
    starts at 1 when the row is created".

    Design: Corner/entities/get_contractor_by_id_returns_stored_row
    """
    created = get_success_data(
        api.create_contractor(
            {"legal_name": "Acme Electric", "dir_registration_number": "PW-1001"},
            portal_admin_headers,
        ),
        expected_status=201,
    )
    resp = api.get_contractor(created["id"], officer_headers)
    contractor = get_success_data(resp)
    validate_success(resp, expected_status=200)
    assert contractor["legal_name"] == "Acme Electric"
    assert contractor["dir_registration_number"] == "PW-1001"
    assert contractor["debarment_status"] == "CLEAR"
    assert contractor["debarment_risk_score"] == 0
    assert contractor["outstanding_restitution_cents"] == 0
    assert contractor["last_finding_at"] is None
    assert contractor["open_critical_finding_count"] == 0
    assert contractor["version"] == 1


def test_listing_contractors_windows_the_rows_and_counts_the_whole_set(api, portal_admin_headers):
    """limit 2 over three rows returns two rows, total_count 3 and has_more true.

    PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside
    `meta`. `total_count` reports the number of rows matching the request's filters before the
    window is applied, and `has_more` is true when rows remain beyond the current window."

    Design: Corner/entities/list_contractors_honours_limit_offset_and_pagination_counters
    """
    for name, dir_number in (
        ("Acme Electric", "PW-1001"),
        ("Bay Conduit", "PW-1002"),
        ("Central Wiring", "PW-1003"),
    ):
        build_contractor(api, legal_name=name, dir_registration_number=dir_number)

    resp = api.list_contractors(portal_admin_headers, params={"limit": 2, "offset": 0})
    rows, meta = validate_paginated(resp)
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0


def test_an_unstored_contractor_uuid_answers_the_contractor_specific_404(
    api, portal_admin_headers
):
    """A well-formed but unknown id yields ERR_CONTRACTOR_NOT_FOUND, not a generic failure.

    PRD 2.8 rung 4: "Path resource existence, resolved outermost-first ... a missing contractor
    is `ERR_CONTRACTOR_NOT_FOUND`".

    Design: Corner/entities/get_contractor_with_unknown_id_returns_not_found
    """
    build_contractor(api, legal_name="Acme Electric", dir_registration_number="PW-1001")
    resp = api.get_contractor(NON_EXISTENT_UUID, portal_admin_headers)
    validate_error(resp, ApiErrorId.ERR_CONTRACTOR_NOT_FOUND.value, expected_status=404)


def test_a_determination_without_a_locality_code_is_a_body_shape_failure(
    api, portal_admin_headers
):
    """locality_code has no default, so omitting it is ERR_VALIDATION and stores nothing.

    PRD 3.1: "A `PortalAdmin` records one by supplying its `decision_number` ... together with
    a `modification_number` giving the modification sequence of that decision, a
    `locality_code` naming the county the decision governs, an `effective_date`, and optionally
    an `expiry_date`." PRD 2.8 rung 7: "Body shape and field-level constraints — types, ranges,
    string lengths, enum membership, array bounds, decimal scale and required-field presence —
    reported as `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/create_wage_determination_without_locality_code_is_rejected
    """
    payload = wage_determination_payload()
    del payload["locality_code"]
    resp = api.create_wage_determination(payload, portal_admin_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)

    listed = get_success_data(api.list_wage_determinations(portal_admin_headers))
    assert listed == []


def test_omitting_the_modification_number_stores_the_zero_default(api, portal_admin_headers):
    """The determination lands with modification_number 0, DRAFT, rate_count 0 and null links.

    PRD 3.1: "The `modification_number` defaults to 0 when omitted and may not be negative ...
    The new determination begins life with `status` `DRAFT`, a `rate_count` of 0, and a
    `version` of 1."

    Design: Corner/entities/omitting_modification_number_applies_zero_default
    """
    payload = wage_determination_payload()
    del payload["modification_number"]
    determination = get_success_data(
        api.create_wage_determination(payload, portal_admin_headers), expected_status=201
    )
    assert determination["modification_number"] == 0
    assert determination["status"] == "DRAFT"
    assert determination["rate_count"] == 0
    assert determination["expiry_date"] is None
    assert determination["superseded_by_id"] is None
    assert determination["version"] == 1


def test_both_fringe_credits_are_computed_at_declaration_not_supplied(api):
    """420000 over 2100.00 hours on both denominators gives 200 cents, PENDING_APPROVAL.

    PRD 3.3: "Declaring a plan computes and stores **both** defensible hourly credits at once,
    from identical inputs. The **annualized-all-hours** figure is stored in
    `annualized_credit_cents` and is obtained by dividing the plan's `annual_contribution_cents`
    by its `annual_total_hours` and rounding the quotient half up to a whole cent. The
    **covered-hours-only** figure is stored in `claimed_credit_cents` and is obtained by
    dividing the same `annual_contribution_cents` by `annual_public_works_hours` alone, again
    rounded half up to a whole cent." PRD 3.3: "A newly declared plan starts with
    `approval_status` `PENDING_APPROVAL`."

    Design: Corner/entities/fringe_plan_annualized_credit_is_computed_not_accepted_from_input
    """
    contractor = build_contractor(api)
    preparer = build_staff(api, contractor["id"], full_name="Pat Prep", capability="PREPARER")
    resp = api.create_fringe_plan(
        contractor["id"],
        fringe_plan_payload(
            plan_name="IBEW Trust B",
            plan_type="BONA_FIDE_TRUST",
            annual_contribution_cents=420000,
            annual_total_hours=2100.00,
            annual_public_works_hours=2100.00,
        ),
        make_preparer_headers(preparer["id"]),
    )
    plan = get_success_data(resp, expected_status=201)
    validate_success(resp, expected_status=201)
    assert plan["annualized_credit_cents"] == 200
    assert plan["claimed_credit_cents"] == 200
    assert plan["approval_status"] == "PENDING_APPROVAL"


def test_a_new_worker_receives_its_identity_and_version_from_the_server(api):
    """Neither id, created_at nor version appear in the request, yet all three come back.

    PRD 2.4: "Every persisted resource carries a server-minted `id` — a UUID string with no
    type prefix — and a `created_at` timestamp in ISO 8601 UTC form with three fractional
    digits. Clients never supply either value." PRD 2.4: "`version` starts at 1 when the row is
    created". PRD 3.2: "A newly registered worker starts with an `interview_count` of 0."

    Design: Corner/entities/worker_id_and_created_at_are_system_minted
    """
    contractor = build_contractor(api)
    preparer = build_staff(api, contractor["id"], full_name="Pat Prep", capability="PREPARER")
    worker = build_worker(
        api, contractor["id"], make_preparer_headers(preparer["id"]),
        worker_number="W-001", full_name="Jo Journey",
    )
    assert is_valid_uuid(worker["id"])
    assert_timestamp_format(worker["created_at"])
    assert worker["version"] == 1
    assert worker["employer_contractor_id"] == contractor["id"]
    assert worker["worker_number"] == "W-001"
    assert worker["interview_count"] == 0


def test_a_staff_capability_outside_the_enum_is_refused(api, portal_admin_headers):
    """SIGNER is not one of the three declared capabilities, so the roster write is a 422.

    PRD 3.2: "A `PortalAdmin` adds a staff member by supplying a `full_name` — the name that
    will be printed on the statement of compliance — and a `capability` of `PREPARER`,
    `CERTIFIER` or `BOTH`". PRD 2.8 rung 7: "Body shape and field-level constraints — types,
    ranges, string lengths, enum membership, array bounds, decimal scale and required-field
    presence — reported as `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/staff_capability_outside_enum_is_rejected
    """
    contractor = build_contractor(api)
    resp = api.add_staff(
        contractor["id"], {"full_name": "Sid Signer", "capability": "SIGNER"}, portal_admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)

    roster = get_success_data(api.list_staff(contractor["id"], portal_admin_headers))
    assert roster == []


def test_a_payroll_line_carries_no_version_and_no_updated_at(api, portal_admin_headers):
    """The lightweight line exposes id and created_at plus its own computed fields only.

    PRD 2.4: "Four resource kinds are deliberately lighter: the reporting portal, the wage rate
    row, the contractor staff row and the payroll line carry only `id` and `created_at`. They
    have no `updated_at` field and no `version` field at all, and nothing in this specification
    increments a version on them — when a payroll line's computed fields are rewritten by the
    wage engine, it is the owning payroll submission's `version` that advances, not the line's."

    Design: Corner/entities/payroll_line_is_immutable_and_carries_no_version_field
    """
    env = setup_env(api, rates=[{"fringe_hourly_rate_cents": 2000}])
    worker = build_worker(api, env["contractor"]["id"], env["preparer_headers"])
    submission = build_submission(api, env, week_ending_date="2026-08-01T00:00:00.000Z")
    line = build_line(
        api, env, submission["id"], worker["id"],
        straight_hours=40.00, overtime_hours=0.00,
        base_rate_paid_cents=5000, overtime_rate_paid_cents=0, fringe_cash_paid_cents=2000,
    )
    # PRD 3.5: every computed field on a fresh line stays at 0 until finalization.
    assert line["required_base_cents"] == 0
    assert line["required_fringe_cents"] == 0
    assert line["line_underpayment_cents"] == 0
    assert "version" not in line
    assert "updated_at" not in line

    # The wage engine rewrites the line's computed fields; the line still carries no
    # version and no updated_at, because it is the submission's version that advances.
    finalize(api, env, submission["id"])
    read_back = get_success_data(api.get_payroll_line(line["id"], portal_admin_headers))
    assert read_back["required_base_cents"] == 5000
    assert read_back["required_fringe_cents"] == 2000
    assert read_back["line_underpayment_cents"] == 0
    assert "version" not in read_back
    assert "updated_at" not in read_back


def test_a_rate_row_under_an_unstored_determination_is_the_parents_404(
    api, portal_admin_headers
):
    """The rate row is a child, so an unknown parent id answers ERR_DETERMINATION_NOT_FOUND.

    PRD 2.8 rung 4: "Path resource existence, resolved outermost-first: for a nested path the
    outer resource is looked up before the inner one ... a missing wage determination is
    `ERR_DETERMINATION_NOT_FOUND`".

    Design: Corner/entities/wage_rate_creation_requires_an_existing_parent_determination
    """
    get_success_data(
        api.create_wage_determination(wage_determination_payload(), portal_admin_headers),
        expected_status=201,
    )
    resp = api.add_wage_rate(NON_EXISTENT_UUID, wage_rate_payload(), portal_admin_headers)
    validate_error(resp, ApiErrorId.ERR_DETERMINATION_NOT_FOUND.value, expected_status=404)


def test_the_subcontract_tier_graph_is_navigable_in_both_directions(api, portal_admin_headers):
    """A second tier derives tier 1 from its prime and is found by filtering the self edge.

    PRD 3.4: "The prime contractor's tier omits `upper_tier_assignment_id` entirely and
    receives a computed `tier` of 0; a subcontract names the assignment that awarded it through
    `upper_tier_assignment_id` and receives a `tier` one greater than that upper tier's, up to a
    maximum depth of 4. The lower tiers awarded by a given tier are found by filtering on that
    same upper-tier field." PRD 3.4: "A newly created tier sits at `status` `INVITED` with
    `version` 1 and all its ledgers at zero."

    Design: Corner/entities/self_referential_subcontract_tier_graph_is_navigable_both_ways
    """
    env = setup_env(api, activate_project=False)
    sub = build_contractor(api, legal_name="Bay Conduit")
    lower = build_assignment(
        api, env["project"]["id"], sub["id"],
        upper_tier_assignment_id=env["assignment"]["id"], subcontract_amount_cents=25000000,
    )
    assert lower["tier"] == 1
    assert lower["upper_tier_assignment_id"] == env["assignment"]["id"]
    assert lower["status"] == "INVITED"
    assert lower["version"] == 1

    resp = api.list_contract_assignments(
        portal_admin_headers, params={"upper_tier_assignment_id": env["assignment"]["id"]}
    )
    rows = get_success_data(resp)
    assert len(rows) == 1
    assert rows[0]["id"] == lower["id"]

    prime = get_success_data(
        api.get_contract_assignment(env["assignment"]["id"], portal_admin_headers)
    )
    assert prime["tier"] == 0

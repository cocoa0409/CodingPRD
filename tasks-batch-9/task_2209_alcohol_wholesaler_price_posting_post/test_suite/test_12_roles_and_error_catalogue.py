"""Role partitioning, licensee capacity checks and the not-found error catalogue.

Every test starts from an empty database and builds all of its own preconditions
through PRD-declared endpoints only.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    make_certifying_officer_headers,
    make_filing_agent_headers,
    new_brand,
    new_dual_role_user,
    new_certifying_officer,
    new_filing_agent,
    new_licensee_user,
    new_schedule,
    new_state_program,
    new_wholesaler,
    read_brand,
    read_schedule,
    read_wholesaler,
    regulator_headers,
    set_clock,
    setup_draft_schedule,
    setup_licensee_base,
    setup_submitted_schedule,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00Z"


def _item_payload(schedule_id, brand_id, **overrides):
    payload = {
        "schedule_id": schedule_id,
        "brand_id": brand_id,
        "size_ml": 750,
        "bottles_per_case": 12,
        "case_price_cents": 120000,
        "unit_price_cents": 11000,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Role partitioning of the write endpoints
# ---------------------------------------------------------------------------

def test_01_filing_agent_cannot_certify_and_certifying_officer_cannot_file(api):
    """PRD §2.1: "Write endpoints are partitioned: `FilingAgent` exclusively performs
    brand registration filing, schedule creation, schedule item creation, schedule
    submission, schedule withdrawal, discount tier creation, combination sale declaration,
    hold amendment filing, error correction filing, retailer invoice creation, invoice line
    creation and invoice validation."
    PRD §2.1: "`CertifyingOfficer` exclusively performs schedule certification."
    PRD §2.1: "When the role authenticates but is not permitted to invoke the endpoint, the
    request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/filing_agent_cannot_certify_and_certifying_officer_cannot_file_or_submit
    """
    scene = setup_submitted_schedule()
    schedule_id = scene["schedule"]["id"]

    validate_error(
        api.certify_price_schedule(schedule_id, scene["agent_headers"]),
        "ERR_UNAUTHORIZED",
    )
    validate_error(
        api.create_price_schedule(
            {
                "wholesaler_id": scene["wholesaler"]["id"],
                "state_program_id": scene["program"]["id"],
                "posting_month": "2026-10",
            },
            scene["certifier_headers"],
        ),
        "ERR_UNAUTHORIZED",
    )
    validate_error(
        api.create_price_schedule_item(
            _item_payload(schedule_id, scene["brand"]["id"], size_ml=375),
            scene["certifier_headers"],
        ),
        "ERR_UNAUTHORIZED",
    )
    validate_error(
        api.submit_price_schedule(schedule_id, scene["certifier_headers"]),
        "ERR_UNAUTHORIZED",
    )

    stored = read_schedule(schedule_id)
    assert stored["status"] == "SUBMITTED", (
        "a refused certification must leave the schedule SUBMITTED"
    )
    assert stored.get("certified_at") is None, "a refused certification stamps no certified_at"
    assert stored.get("certified_by_user_id") is None, (
        "a refused certification records no certifying user"
    )

    _schedules, schedule_meta = validate_paginated(
        api.list_price_schedules(
            regulator_headers(), params={"wholesaler_id": scene["wholesaler"]["id"]}
        )
    )
    assert schedule_meta["total_count"] == 1, (
        "the CertifyingOfficer's refused create must not persist a second schedule"
    )

    _items, item_meta = validate_paginated(
        api.list_price_schedule_items(
            regulator_headers(), params={"schedule_id": schedule_id}
        )
    )
    assert item_meta["total_count"] == 1, (
        "the CertifyingOfficer's refused create must not persist a second item"
    )


def test_02_compliance_officer_cannot_act_in_either_licensee_capacity(api):
    """PRD §2.1: "Write endpoints are partitioned: `FilingAgent` exclusively performs
    brand registration filing, schedule creation, schedule item creation, schedule
    submission, schedule withdrawal, discount tier creation, combination sale declaration,
    hold amendment filing, error correction filing, retailer invoice creation, invoice line
    creation and invoice validation."
    PRD §2.1: "`CertifyingOfficer` exclusively performs schedule certification."
    PRD §2.1: "When the role authenticates but is not permitted to invoke the endpoint, the
    request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/compliance_officer_cannot_perform_either_licensee_filing_capacity
    """
    scene = setup_submitted_schedule()
    schedule_id = scene["schedule"]["id"]
    version_before = read_schedule(schedule_id)["version"]

    validate_error(
        api.create_price_schedule(
            {
                "wholesaler_id": scene["wholesaler"]["id"],
                "state_program_id": scene["program"]["id"],
                "posting_month": "2026-10",
            },
            regulator_headers(),
        ),
        "ERR_UNAUTHORIZED",
    )
    validate_error(
        api.create_price_schedule_item(
            _item_payload(schedule_id, scene["brand"]["id"], size_ml=375),
            regulator_headers(),
        ),
        "ERR_UNAUTHORIZED",
    )
    validate_error(
        api.submit_price_schedule(schedule_id, regulator_headers()),
        "ERR_UNAUTHORIZED",
    )
    validate_error(
        api.certify_price_schedule(schedule_id, regulator_headers()),
        "ERR_UNAUTHORIZED",
    )
    validate_error(
        api.withdraw_price_schedule(schedule_id, regulator_headers()),
        "ERR_UNAUTHORIZED",
    )

    stored = read_schedule(schedule_id)
    assert stored["status"] == "SUBMITTED", (
        "none of the refused licensee-capacity writes may move the schedule"
    )
    assert stored["version"] == version_before, (
        "a refused request must not advance the schedule's version"
    )

    _schedules, meta = validate_paginated(
        api.list_price_schedules(
            regulator_headers(), params={"state_program_id": scene["program"]["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        "the regulator's refused create must not persist a second schedule"
    )


def test_03_filing_agent_cannot_exercise_the_regulator_write_endpoints(api):
    """PRD §2.1: "`ComplianceOfficer` exclusively performs logical clock control, state
    program registration, wholesaler registration, licence status changes, licensee user
    registration, brand approval and rejection, returning a schedule for correction, hold
    amendment acceptance, rejection and revocation, error correction approval and denial,
    audit creation, collection, assessment, closure and voiding, and the posting run."
    PRD §2.1: "When the role authenticates but is not permitted to invoke the endpoint, the
    request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.2: "The new registration begins in `PENDING` with `rejection_reason` unset."

    Design: Corner/rbac/filing_agent_cannot_exercise_the_regulator_approval_and_run_operations
    """
    scene = setup_licensee_base(approve_brand_registration=False)
    agent_headers = scene["agent_headers"]
    brand_id = scene["brand"]["id"]
    wholesaler_id = scene["wholesaler"]["id"]

    validate_error(api.approve_brand(brand_id, agent_headers), "ERR_UNAUTHORIZED")
    validate_error(
        api.reject_brand(
            brand_id, {"rejection_reason": "Filed by the wrong party."}, agent_headers
        ),
        "ERR_UNAUTHORIZED",
    )
    validate_error(
        api.set_wholesaler_license_status(
            wholesaler_id, {"license_status": "SUSPENDED"}, agent_headers
        ),
        "ERR_UNAUTHORIZED",
    )
    validate_error(
        api.create_licensee_user(
            {
                "wholesaler_id": wholesaler_id,
                "full_name": "Self Appointed",
                "user_role": "FILING_AGENT",
            },
            agent_headers,
        ),
        "ERR_UNAUTHORIZED",
    )
    validate_error(
        api.create_posting_run({"state_program_id": scene["program"]["id"]}, agent_headers),
        "ERR_UNAUTHORIZED",
    )

    brand = read_brand(brand_id)
    assert brand["registration_status"] == "PENDING", (
        "a refused approval leaves the registration in PENDING"
    )
    assert brand.get("rejection_reason") is None, (
        "a refused rejection must not write a rejection_reason"
    )

    wholesaler = read_wholesaler(wholesaler_id)
    assert wholesaler["license_status"] == "ACTIVE", (
        "a refused licence status change leaves license_status ACTIVE"
    )
    assert wholesaler["version"] == 1, (
        "a refused licence status change must not advance the wholesaler's version"
    )

    _users, meta = validate_paginated(
        api.list_licensee_users(regulator_headers(), params={"wholesaler_id": wholesaler_id})
    )
    assert meta["total_count"] == 2, (
        "the refused licensee user registration must not persist a third user"
    )


def test_04_dual_role_user_satisfies_both_the_filing_and_the_certifying_claim(api):
    """PRD §2.1: "A `user_role` of `DUAL_ROLE` therefore satisfies both `FilingAgent` and
    `CertifyingOfficer` claims."
    PRD §3.4: "Certification stamps `certified_at` with the current server time, records the
    acting user in `certified_by_user_id`, and computes `hold_window_ends_at` as
    `certified_at` advanced by the program's `hold_window_days` multiplied by 86,400
    seconds."
    PRD §3.4: "Every item of the schedule that is in `DRAFT` moves to `POSTED`, and for each
    such item the system snapshots the prices as filed: `case_price_cents` is copied into
    `certified_case_price_cents` and `unit_price_cents` into `certified_unit_price_cents`."

    Design: Corner/rbac/dual_role_user_satisfies_both_the_filing_and_the_certifying_role_check
    """
    set_clock(CLOCK_START)
    program = new_state_program(state_code="TX", program_name="Texas Price Posting Program")
    wholesaler = new_wholesaler(
        program["id"], license_number="W-1001", legal_name="Lone Star Distributing"
    )
    filer = new_dual_role_user(wholesaler["id"], "Dana Dual")
    certifier = new_dual_role_user(wholesaler["id"], "Devin Dual")
    filer_headers = make_filing_agent_headers(filer["id"])
    certifier_headers = make_certifying_officer_headers(certifier["id"])

    brand = new_brand(wholesaler["id"], filer_headers, approve=True)

    schedule = validate_success(
        api.create_price_schedule(
            {
                "wholesaler_id": wholesaler["id"],
                "state_program_id": program["id"],
                "posting_month": "2026-09",
            },
            filer_headers,
        ),
        201,
    )
    item = validate_success(
        api.create_price_schedule_item(
            _item_payload(schedule["id"], brand["id"]), filer_headers
        ),
        201,
    )

    submitted = validate_success(
        api.submit_price_schedule(schedule["id"], filer_headers), 200
    )
    assert submitted["status"] == "SUBMITTED", "a DUAL_ROLE user may file and submit"
    assert submitted["filed_by_user_id"] == filer["id"], (
        "filing records the acting DUAL_ROLE user"
    )

    certified = validate_success(
        api.certify_price_schedule(schedule["id"], certifier_headers), 200
    )
    assert certified["status"] == "POSTED", "a DUAL_ROLE user may certify"
    assert certified["certified_by_user_id"] == certifier["id"], (
        "certification records the acting DUAL_ROLE user"
    )
    assert certified["certified_at"] == "2026-08-01T00:00:00.000Z", (
        "certified_at is stamped from the logical clock"
    )
    assert certified["hold_window_ends_at"] == "2026-08-04T00:00:00.000Z", (
        "hold_window_ends_at is certified_at advanced by 3 days of 86,400 seconds"
    )

    posted_item = validate_success(
        api.get_price_schedule_item(item["id"], filer_headers), 200
    )
    assert posted_item["status"] == "POSTED", "certification moves each DRAFT item to POSTED"
    assert posted_item["certified_case_price_cents"] == 120000, (
        "case_price_cents is snapshotted into certified_case_price_cents"
    )
    assert posted_item["certified_unit_price_cents"] == 11000, (
        "unit_price_cents is snapshotted into certified_unit_price_cents"
    )


def test_05_inactive_licensee_user_is_never_authorised_in_its_own_capacity(api):
    """PRD §2.1: "A `LicenseeUser` whose `is_active` is `false` is never authorised for
    anything, whatever its `user_role`."
    PRD §2.1: "The same code and status are used when an entity-backed role's `X-User-ID`
    fails to resolve to an active `LicenseeUser` whose `user_role` matches the claimed
    role."

    Design: Corner/rbac/an_inactive_licensee_user_is_never_authorized_for_any_endpoint_of_its_own_capacity
    """
    scene = setup_licensee_base()
    setup_draft_schedule(scene)
    wholesaler_id = scene["wholesaler"]["id"]
    schedule_id = scene["schedule"]["id"]

    dormant = new_licensee_user(
        wholesaler_id, "FILING_AGENT", full_name="Dormant Agent", is_active=False
    )
    assert dormant["is_active"] is False, "the dormant user must be registered as inactive"
    dormant_headers = make_filing_agent_headers(dormant["id"])

    validate_error(
        api.create_price_schedule(
            {
                "wholesaler_id": wholesaler_id,
                "state_program_id": scene["program"]["id"],
                "posting_month": "2026-10",
            },
            dormant_headers,
        ),
        "ERR_UNAUTHORIZED",
    )
    validate_error(
        api.create_price_schedule_item(
            _item_payload(schedule_id, scene["brand"]["id"], size_ml=375), dormant_headers
        ),
        "ERR_UNAUTHORIZED",
    )
    validate_error(
        api.submit_price_schedule(schedule_id, dormant_headers), "ERR_UNAUTHORIZED"
    )
    validate_error(
        api.get_price_schedule(schedule_id, dormant_headers), "ERR_UNAUTHORIZED"
    )

    still_draft = validate_success(
        api.get_price_schedule(schedule_id, scene["agent_headers"]), 200
    )
    assert still_draft["status"] == "DRAFT", (
        "the inactive user's refused submission leaves the schedule in DRAFT"
    )

    stored_user = validate_success(
        api.get_licensee_user(dormant["id"], regulator_headers()), 200
    )
    assert stored_user["is_active"] is False, "the dormant user is still stored as inactive"
    assert stored_user["user_role"] == "FILING_AGENT", (
        "the dormant user's user_role is unchanged by the refusals"
    )

    _schedules, meta = validate_paginated(
        api.list_price_schedules(regulator_headers(), params={"wholesaler_id": wholesaler_id})
    )
    assert meta["total_count"] == 1, (
        "the inactive user's refused create must not persist a second schedule"
    )


def test_06_reads_are_shared_by_all_roles_while_writes_stay_inside_the_wholesaler(api):
    """PRD §2.1: "Every read endpoint listed in §4 is available to all three roles."
    PRD §2.1: "When the role is permitted for the endpoint but the specific resource belongs
    to a different wholesaler, the rejection is the distinct
    `ERR_FORBIDDEN_WHOLESALER_SCOPE` (HTTP 403) — see §2.11."
    PRD §2.11: "On `POST /price-schedule-items`, `POST /combination-sales`,
    `POST /price-schedules/{id}/submit`, `POST /price-schedules/{id}/certify` and
    `POST /price-schedules/{id}/withdraw` the owner is the wholesaler of the target
    schedule."

    Design: Corner/rbac/every_get_is_shared_by_all_three_roles_including_a_filing_agent_of_another_wholesaler
    """
    set_clock(CLOCK_START)
    program = new_state_program(state_code="TX", program_name="Texas Price Posting Program")
    wholesaler_a = new_wholesaler(
        program["id"], license_number="W-1001", legal_name="Lone Star Distributing"
    )
    _agent_a, agent_a_headers = new_filing_agent(wholesaler_a["id"], "Fay Filer")
    brand_a = new_brand(wholesaler_a["id"], agent_a_headers, approve=True)
    schedule_a = new_schedule(
        wholesaler_a["id"], program["id"], agent_a_headers, posting_month="2026-09"
    )
    item_a = validate_success(
        api.create_price_schedule_item(
            _item_payload(schedule_a["id"], brand_a["id"]), agent_a_headers
        ),
        201,
    )

    wholesaler_b = new_wholesaler(
        program["id"], license_number="W-2002", legal_name="Gulf Coast Wholesale"
    )
    _agent_b, agent_b_headers = new_filing_agent(wholesaler_b["id"], "Blake Filer")
    _certifier_b, certifier_b_headers = new_certifying_officer(
        wholesaler_b["id"], "Bea Certifier"
    )

    foreign_schedule_read = validate_success(
        api.get_price_schedule(schedule_a["id"], agent_b_headers), 200
    )
    assert foreign_schedule_read["wholesaler_id"] == wholesaler_a["id"], (
        "a FilingAgent of another wholesaler may still read the schedule"
    )
    foreign_item_read = validate_success(
        api.get_price_schedule_item(item_a["id"], certifier_b_headers), 200
    )
    assert foreign_item_read["id"] == item_a["id"], (
        "a CertifyingOfficer of another wholesaler may still read the item"
    )
    foreign_wholesaler_read = validate_success(
        api.get_wholesaler(wholesaler_a["id"], agent_b_headers), 200
    )
    assert foreign_wholesaler_read["id"] == wholesaler_a["id"], (
        "a FilingAgent of another wholesaler may still read the wholesaler record"
    )
    regulator_read = validate_success(
        api.get_price_schedule(schedule_a["id"], regulator_headers()), 200
    )
    assert regulator_read["id"] == schedule_a["id"], "the regulator shares every read endpoint"

    validate_error(
        api.submit_price_schedule(schedule_a["id"], agent_b_headers),
        "ERR_FORBIDDEN_WHOLESALER_SCOPE",
    )
    validate_error(
        api.create_price_schedule_item(
            _item_payload(schedule_a["id"], brand_a["id"], size_ml=375), agent_b_headers
        ),
        "ERR_FORBIDDEN_WHOLESALER_SCOPE",
    )

    stored = read_schedule(schedule_a["id"])
    assert stored["status"] == "DRAFT", (
        "the out-of-scope submission must leave the schedule in DRAFT"
    )
    assert stored["item_count"] == 1, (
        "the out-of-scope item creation must not touch the schedule's item_count"
    )


def test_07_segregation_is_scoped_per_schedule_so_two_dual_role_users_may_cross_certify(api):
    """PRD §3.4: "the acting licensee user must not be the user recorded in the schedule's
    `filed_by_user_id`, or the request is refused with `ERR_SEGREGATION_OF_DUTIES`"
    PRD §3.4: "Note that a person holding `DUAL_ROLE` can legitimately file and certify —
    but not the same schedule, because the segregation test compares licensee user
    identities, not capacities."

    Design: Corner/rbac/segregation_is_scoped_per_schedule_so_two_dual_role_users_may_cross_certify
    """
    set_clock(CLOCK_START)
    program = new_state_program(state_code="TX", program_name="Texas Price Posting Program")
    wholesaler = new_wholesaler(
        program["id"], license_number="W-1001", legal_name="Lone Star Distributing"
    )
    user_one = new_dual_role_user(wholesaler["id"], "Dana Dual")
    user_two = new_dual_role_user(wholesaler["id"], "Devin Dual")
    one_filing = make_filing_agent_headers(user_one["id"])
    one_certifying = make_certifying_officer_headers(user_one["id"])
    two_filing = make_filing_agent_headers(user_two["id"])
    two_certifying = make_certifying_officer_headers(user_two["id"])

    brand = new_brand(wholesaler["id"], one_filing, approve=True)

    schedule_one = new_schedule(
        wholesaler["id"], program["id"], one_filing, posting_month="2026-09"
    )
    validate_success(
        api.create_price_schedule_item(
            _item_payload(schedule_one["id"], brand["id"]), one_filing
        ),
        201,
    )
    filed_one = validate_success(api.submit_price_schedule(schedule_one["id"], one_filing), 200)
    assert filed_one["filed_by_user_id"] == user_one["id"], (
        "the first schedule is filed by the first DUAL_ROLE user"
    )

    schedule_two = new_schedule(
        wholesaler["id"], program["id"], two_filing, posting_month="2026-10"
    )
    validate_success(
        api.create_price_schedule_item(
            _item_payload(schedule_two["id"], brand["id"]), two_filing
        ),
        201,
    )
    filed_two = validate_success(api.submit_price_schedule(schedule_two["id"], two_filing), 200)
    assert filed_two["filed_by_user_id"] == user_two["id"], (
        "the second schedule is filed by the second DUAL_ROLE user"
    )

    validate_error(
        api.certify_price_schedule(schedule_one["id"], one_certifying),
        "ERR_SEGREGATION_OF_DUTIES",
    )

    certified_one = validate_success(
        api.certify_price_schedule(schedule_one["id"], two_certifying), 200
    )
    assert certified_one["status"] == "POSTED", (
        "the second user may certify the schedule the first user filed"
    )
    assert certified_one["certified_by_user_id"] == user_two["id"], (
        "certification records the cross-certifying user"
    )

    certified_two = validate_success(
        api.certify_price_schedule(schedule_two["id"], one_certifying), 200
    )
    assert certified_two["status"] == "POSTED", (
        "the first user may certify the schedule the second user filed"
    )
    assert certified_two["certified_by_user_id"] == user_one["id"], (
        "segregation compares identities per schedule, not capacities"
    )
    assert certified_two["hold_window_ends_at"] == "2026-08-04T00:00:00.000Z", (
        "the hold window still runs three days from certification"
    )


# ---------------------------------------------------------------------------
# The not-found catalogue
# ---------------------------------------------------------------------------

def test_08_each_administrative_entity_returns_its_own_not_found_code(api):
    """PRD §2.10: "Every identifier appearing in the URL path exists, checked left to
    right, and the first identifier that does not resolve determines the error. The error
    is the not-found code of that identifier's entity type (404)."
    PRD §2.11: "That identifier is resolved before the body is parsed, and the not-found
    code that is returned identifies the entity type of the segment:
    `ERR_STATE_PROGRAM_NOT_FOUND`, `ERR_WHOLESALER_NOT_FOUND`,
    `ERR_LICENSEE_USER_NOT_FOUND`, `ERR_BRAND_NOT_FOUND`, `ERR_PRICE_SCHEDULE_NOT_FOUND`,
    `ERR_PRICE_SCHEDULE_ITEM_NOT_FOUND`, `ERR_QUANTITY_DISCOUNT_TIER_NOT_FOUND`,
    `ERR_COMBINATION_SALE_NOT_FOUND`, `ERR_HOLD_AMENDMENT_NOT_FOUND`,
    `ERR_ERROR_CORRECTION_NOT_FOUND`, `ERR_RETAILER_INVOICE_NOT_FOUND`,
    `ERR_INVOICE_LINE_NOT_FOUND`, `ERR_COMPLIANCE_AUDIT_NOT_FOUND` or
    `ERR_AUDIT_FINDING_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/every_administrative_entity_reports_its_own_not_found_code_on_an_unknown_path_id
    """
    scene = setup_licensee_base()
    setup_draft_schedule(scene)
    headers = regulator_headers()

    validate_error(
        api.get_state_program(NON_EXISTENT_UUID, headers), "ERR_STATE_PROGRAM_NOT_FOUND"
    )
    validate_error(
        api.get_wholesaler(NON_EXISTENT_UUID, headers), "ERR_WHOLESALER_NOT_FOUND"
    )
    validate_error(
        api.get_licensee_user(NON_EXISTENT_UUID, headers), "ERR_LICENSEE_USER_NOT_FOUND"
    )
    validate_error(api.get_brand(NON_EXISTENT_UUID, headers), "ERR_BRAND_NOT_FOUND")
    validate_error(
        api.get_price_schedule(NON_EXISTENT_UUID, headers), "ERR_PRICE_SCHEDULE_NOT_FOUND"
    )

    assert (
        validate_success(api.get_state_program(scene["program"]["id"], headers), 200)["id"]
        == scene["program"]["id"]
    ), "the real program must still resolve"
    assert (
        validate_success(api.get_wholesaler(scene["wholesaler"]["id"], headers), 200)["id"]
        == scene["wholesaler"]["id"]
    ), "the real wholesaler must still resolve"
    assert (
        validate_success(api.get_licensee_user(scene["agent"]["id"], headers), 200)["id"]
        == scene["agent"]["id"]
    ), "the real licensee user must still resolve"
    assert (
        validate_success(api.get_brand(scene["brand"]["id"], headers), 200)["id"]
        == scene["brand"]["id"]
    ), "the real brand must still resolve"
    assert (
        validate_success(api.get_price_schedule(scene["schedule"]["id"], headers), 200)["id"]
        == scene["schedule"]["id"]
    ), "the real schedule must still resolve"


def test_09_each_pricing_and_audit_entity_returns_its_own_not_found_code(api):
    """PRD §2.10: "Every identifier appearing in the URL path exists, checked left to
    right, and the first identifier that does not resolve determines the error. The error
    is the not-found code of that identifier's entity type (404)."
    PRD §2.11: "That identifier is resolved before the body is parsed, and the not-found
    code that is returned identifies the entity type of the segment:
    `ERR_STATE_PROGRAM_NOT_FOUND`, `ERR_WHOLESALER_NOT_FOUND`,
    `ERR_LICENSEE_USER_NOT_FOUND`, `ERR_BRAND_NOT_FOUND`, `ERR_PRICE_SCHEDULE_NOT_FOUND`,
    `ERR_PRICE_SCHEDULE_ITEM_NOT_FOUND`, `ERR_QUANTITY_DISCOUNT_TIER_NOT_FOUND`,
    `ERR_COMBINATION_SALE_NOT_FOUND`, `ERR_HOLD_AMENDMENT_NOT_FOUND`,
    `ERR_ERROR_CORRECTION_NOT_FOUND`, `ERR_RETAILER_INVOICE_NOT_FOUND`,
    `ERR_INVOICE_LINE_NOT_FOUND`, `ERR_COMPLIANCE_AUDIT_NOT_FOUND` or
    `ERR_AUDIT_FINDING_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/every_pricing_and_audit_entity_reports_its_own_not_found_code_on_an_unknown_path_id
    """
    set_clock(CLOCK_START)
    headers = regulator_headers()

    validate_error(
        api.get_price_schedule_item(NON_EXISTENT_UUID, headers),
        "ERR_PRICE_SCHEDULE_ITEM_NOT_FOUND",
    )
    validate_error(
        api.get_quantity_discount_tier(NON_EXISTENT_UUID, headers),
        "ERR_QUANTITY_DISCOUNT_TIER_NOT_FOUND",
    )
    validate_error(
        api.get_combination_sale(NON_EXISTENT_UUID, headers),
        "ERR_COMBINATION_SALE_NOT_FOUND",
    )
    validate_error(
        api.get_hold_amendment(NON_EXISTENT_UUID, headers), "ERR_HOLD_AMENDMENT_NOT_FOUND"
    )
    validate_error(
        api.get_error_correction(NON_EXISTENT_UUID, headers),
        "ERR_ERROR_CORRECTION_NOT_FOUND",
    )
    validate_error(
        api.get_retailer_invoice(NON_EXISTENT_UUID, headers),
        "ERR_RETAILER_INVOICE_NOT_FOUND",
    )
    validate_error(
        api.get_invoice_line(NON_EXISTENT_UUID, headers), "ERR_INVOICE_LINE_NOT_FOUND"
    )
    validate_error(
        api.get_compliance_audit(NON_EXISTENT_UUID, headers),
        "ERR_COMPLIANCE_AUDIT_NOT_FOUND",
    )
    validate_error(
        api.get_audit_finding(NON_EXISTENT_UUID, headers), "ERR_AUDIT_FINDING_NOT_FOUND"
    )

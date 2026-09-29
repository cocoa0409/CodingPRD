"""The Order of Rejection: when several rules are violated, only the highest answers.

Every test in this module puts two (or three) rules of PRD §2.10 in conflict inside a
single request and pins the response to the numerically lowest priority that was
violated. PRD §2.10 numbers all twenty-two priorities explicitly, so each ordering
asserted here is read straight off the contract.
"""

from typing import Any, Dict

from test_helpers import (
    NON_EXISTENT_UUID,
    create_hold_amendment_payload,
    create_price_schedule_item_payload,
    new_schedule,
    read_item,
    read_schedule,
    regulator_headers,
    run_posting,
    schedule_version,
    set_clock,
    set_license_status,
    setup_certified_schedule,
    setup_licensee_base,
    setup_two_wholesalers_certified,
    validate_error,
    validate_paginated,
)


# --------------------------------------------------------------------------
# Local scene helpers
# --------------------------------------------------------------------------

def _two_wholesalers_effective() -> Dict[str, Any]:
    """Two wholesalers certified for 2026-09, then a posting run at 2026-10-01.

    Both schedules leave the run `EFFECTIVE`, so every item is `EFFECTIVE` and both
    post-and-hold windows shut on 2026-08-04T00:00:00.000Z.
    """
    scene = setup_two_wholesalers_certified()
    set_clock("2026-10-01T00:00:00Z")
    scene["posting_run"] = run_posting(scene["program"]["id"])
    scene["schedule_a"] = read_schedule(scene["schedule_a"]["id"])
    scene["items_a"] = [read_item(item["id"]) for item in scene["items_a"]]
    scene["item_b"] = read_item(scene["item_b"]["id"])
    return scene


# --------------------------------------------------------------------------
# Priorities 1 through 8
# --------------------------------------------------------------------------

def test_01_missing_user_id_header_outranks_the_role_not_being_authorized(api):
    """PRD §2.1: "The same rejection applies when the named role is entity-backed and
    `X-User-ID` is absent."
    PRD §2.10: "`X-User-Role` is present and names one of the three known roles, and
    for an entity-backed role `X-User-ID` is present. Otherwise `ERR_UNAUTHENTICATED`
    (401). Applies to every endpoint."

    Design: Corner/validations/missing_x_user_id_outranks_the_role_not_being_authorized_for_the_endpoint
    """
    set_clock("2026-08-01T00:00:00Z")

    # FilingAgent is not authorised for POST /state-programs at all, so priority 1 and
    # priority 2 are violated by the same request. Authentication must answer first.
    headers_without_user_id = {
        "X-User-Role": "FilingAgent",
        "Content-Type": "application/json",
    }
    resp = api.create_state_program(
        {"state_code": "TX", "program_name": "Texas Price Posting Program"},
        headers_without_user_id,
    )
    validate_error(resp, "ERR_UNAUTHENTICATED", 401)

    body = resp.json()
    assert body["response_type"] == "error", (
        f"an error response must carry response_type 'error', got {body['response_type']!r}"
    )
    assert isinstance(body["meta"].get("api_request_id"), str), (
        "meta.api_request_id must be present on an error envelope"
    )

    _, meta = validate_paginated(api.list_state_programs(regulator_headers()))
    assert meta["total_count"] == 0, (
        f"the rejected request must not have created a state program, "
        f"found {meta['total_count']}"
    )


def test_02_role_authorization_outranks_path_existence_on_certify(api):
    """PRD §2.10: "The named role is authorised for this endpoint, and for an
    entity-backed role `X-User-ID` resolves to a `LicenseeUser` whose `is_active` is
    `true` and whose `user_role` matches the claimed role (`DUAL_ROLE` matching both).
    Otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."
    PRD §2.10: "Every identifier appearing in the URL path exists, checked left to
    right, and the first identifier that does not resolve determines the error. The
    error is the not-found code of that identifier's entity type (404). Applies to
    every endpoint with a path parameter. Path existence is resolved before the request
    body is examined at all."
    PRD §2.1: "`CertifyingOfficer` exclusively performs schedule certification."

    Design: Corner/validations/role_authorization_outranks_path_existence_and_returns_unauthorized_for_an_unknown_schedule
    """
    scene = setup_licensee_base()

    resp = api.certify_price_schedule(NON_EXISTENT_UUID, scene["agent_headers"])
    validate_error(resp, "ERR_UNAUTHORIZED", 403)
    assert resp.status_code != 404, (
        "role authorisation sits at priority 2 and must pre-empt the priority 3 "
        "path-existence 404"
    )


def test_03_path_existence_outranks_body_shape_on_correction_denial(api):
    """PRD §2.10: "Every identifier appearing in the URL path exists, checked left to
    right, and the first identifier that does not resolve determines the error. The
    error is the not-found code of that identifier's entity type (404). Applies to
    every endpoint with a path parameter. Path existence is resolved before the request
    body is examined at all."
    PRD §2.10: "Otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint with a
    request body."

    Design: Corner/validations/path_existence_outranks_body_shape_and_reports_the_error_correction_not_found
    """
    set_clock("2026-08-01T00:00:00Z")
    setup_licensee_base(clock=None, with_certifier=False, with_brand=False)

    # No ErrorCorrection has ever been created, and the body omits denial_reason.
    resp = api.deny_error_correction(NON_EXISTENT_UUID, {}, regulator_headers())
    validate_error(resp, "ERR_ERROR_CORRECTION_NOT_FOUND", 404)
    assert resp.status_code != 400, (
        "path existence sits at priority 3 and must pre-empt the priority 4 body-shape 400"
    )


def test_04_body_shape_outranks_body_foreign_keys_on_invoice_lines(api):
    """PRD §2.10: "Otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint with
    a request body."
    PRD §2.10: "Every foreign key supplied in the request body references an existing
    record; the error is the not-found code of the referenced entity type (404).
    Applies to every endpoint whose body carries a foreign key. Body foreign keys are
    resolved after body shape and before ownership."

    Design: Corner/validations/body_shape_outranks_body_foreign_keys_and_returns_invalid_request
    """
    scene = setup_licensee_base()

    resp = api.create_invoice_line(
        {
            "invoice_id": NON_EXISTENT_UUID,
            "item_id": NON_EXISTENT_UUID,
            "cases_quantity": "two",
            "case_price_charged_cents": 120_000,
            "unit_price_charged_cents": 11_000,
        },
        scene["agent_headers"],
    )
    validate_error(resp, "ERR_INVALID_REQUEST", 400)

    error_id = resp.json()["data"]["error_id"]
    assert error_id not in ("ERR_RETAILER_INVOICE_NOT_FOUND", "ERR_PRICE_SCHEDULE_ITEM_NOT_FOUND"), (
        f"body shape sits at priority 4 and must run before either foreign-key lookup, "
        f"got {error_id}"
    )


def test_05_body_foreign_keys_outrank_wholesaler_scope_on_schedule_items(api):
    """PRD §2.10: "Every foreign key supplied in the request body references an existing
    record; the error is the not-found code of the referenced entity type (404).
    Applies to every endpoint whose body carries a foreign key. Body foreign keys are
    resolved after body shape and before ownership."
    PRD §2.11: "The same codes are reused when a foreign key inside a request body fails
    to resolve at priority 5 — for instance a `state_program_id` that names nothing
    yields `ERR_STATE_PROGRAM_NOT_FOUND`, a `brand_id` that names nothing yields
    `ERR_BRAND_NOT_FOUND`, and a member of `member_item_ids` that names nothing yields
    `ERR_PRICE_SCHEDULE_ITEM_NOT_FOUND`."

    Design: Corner/validations/body_foreign_keys_outrank_wholesaler_scope_and_report_the_brand_not_found
    """
    scene = setup_two_wholesalers_certified()

    # Wholesaler A's agent posts onto wholesaler B's schedule with a nonexistent brand.
    resp = api.create_price_schedule_item(
        create_price_schedule_item_payload(
            scene["schedule_b"]["id"],
            NON_EXISTENT_UUID,
            size_ml=375,
            bottles_per_case=6,
            case_price_cents=30_000,
            unit_price_cents=5_500,
        ),
        scene["agent_a_headers"],
    )
    validate_error(resp, "ERR_BRAND_NOT_FOUND", 404)

    error_id = resp.json()["data"]["error_id"]
    assert error_id != "ERR_FORBIDDEN_WHOLESALER_SCOPE", (
        "the priority 5 foreign-key sweep must complete before the priority 6 "
        "ownership check is considered"
    )

    _, meta = validate_paginated(
        api.list_price_schedule_items(
            regulator_headers(), params={"schedule_id": scene["schedule_b"]["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"no item may be added by the refused request, found {meta['total_count']}"
    )


def test_06_wholesaler_scope_outranks_optimistic_concurrency_on_hold_amendments(api):
    """PRD §2.10: "For an entity-backed role, the target resource belongs to the acting
    `LicenseeUser`'s wholesaler. Otherwise `ERR_FORBIDDEN_WHOLESALER_SCOPE` (403).
    Applies to the thirteen write endpoints enumerated in §2.11."
    PRD §2.10: "Concurrency is checked after ownership and before state."
    PRD §2.11: "On `POST /quantity-discount-tiers`, `POST /hold-amendments` and
    `POST /error-corrections` the owner is the wholesaler of the schedule that owns the
    referenced item — for a hold amendment, specifically the schedule of the **amending**
    item, never the reference item."

    Design: Corner/validations/wholesaler_scope_outranks_optimistic_concurrency_and_returns_forbidden_wholesaler_scope
    """
    scene = setup_two_wholesalers_certified()
    item_a = scene["items_a"][0]

    # The version A's schedule carried before certification is now stale.
    stale_version = schedule_version(scene["schedule_a"]["id"]) - 1

    resp = api.create_hold_amendment(
        create_hold_amendment_payload(
            item_a["id"], scene["item_b"]["id"], 115_000, 10_500, stale_version
        ),
        scene["agent_b_headers"],
    )
    validate_error(resp, "ERR_FORBIDDEN_WHOLESALER_SCOPE", 403)

    _, meta = validate_paginated(
        api.list_hold_amendments(regulator_headers(), params={"amending_item_id": item_a["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the refused amendment must not be persisted, found {meta['total_count']}"
    )

    item_a_after = read_item(item_a["id"])
    assert item_a_after["case_price_cents"] == 120_000, (
        f"the amending item's price must be untouched, got {item_a_after['case_price_cents']}"
    )
    assert item_a_after["amendment_count"] == 0, (
        f"amendment_count must stay 0, got {item_a_after['amendment_count']}"
    )


def test_07_optimistic_concurrency_outranks_item_state_on_hold_amendments(api):
    """PRD §2.12: "If that value does not equal the schedule's currently stored
    `version`, the request is rejected with `ERR_STALE_SCHEDULE_VERSION` (HTTP 412) and
    no `HoldAmendment` is created."
    PRD §2.12: "Both checks sit at priority 7 of §2.10: after path existence, body
    shape, body foreign keys and ownership, and before any state or business rule."

    Design: Corner/validations/optimistic_concurrency_outranks_item_state_and_returns_stale_schedule_version
    """
    scene = _two_wholesalers_effective()
    item_a = scene["items_a"][0]
    assert item_a["status"] == "EFFECTIVE", (
        f"setup must leave the amending item EFFECTIVE, got {item_a['status']}"
    )

    stale_version = schedule_version(scene["schedule_a"]["id"]) - 1

    resp = api.create_hold_amendment(
        create_hold_amendment_payload(
            item_a["id"], scene["item_b"]["id"], 115_000, 10_500, stale_version
        ),
        scene["agent_a_headers"],
    )
    validate_error(resp, "ERR_STALE_SCHEDULE_VERSION", 412)

    error_id = resp.json()["data"]["error_id"]
    assert error_id not in ("ERR_INVALID_STATE", "ERR_HOLD_WINDOW_CLOSED"), (
        f"priority 7 must pre-empt both the priority 8 state check and the priority 12 "
        f"hold-window check, got {error_id}"
    )

    item_a_after = read_item(item_a["id"])
    assert item_a_after["status"] == "EFFECTIVE", (
        f"the item must stay EFFECTIVE, got {item_a_after['status']}"
    )
    assert item_a_after["case_price_cents"] == 120_000, (
        f"the item price must be untouched, got {item_a_after['case_price_cents']}"
    )


def test_08_item_state_outranks_the_hold_window_for_an_effective_item(api):
    """PRD §2.10: "State admissibility outranks every business rule below it — an
    amendment filed against an item that has already gone `EFFECTIVE` is reported as
    `ERR_INVALID_STATE` even though its post-and-hold window has also closed, because
    priority 8 is reached before priority 12."

    Design: Corner/validations/item_state_outranks_the_hold_window_and_returns_invalid_state_for_an_effective_item
    """
    scene = _two_wholesalers_effective()
    item_a = scene["items_a"][0]

    # A current version, so the priority 7 concurrency gate passes cleanly.
    current_version = schedule_version(scene["schedule_a"]["id"])

    resp = api.create_hold_amendment(
        create_hold_amendment_payload(
            item_a["id"], scene["item_b"]["id"], 115_000, 10_500, current_version
        ),
        scene["agent_a_headers"],
    )
    validate_error(resp, "ERR_INVALID_STATE", 409)

    error_id = resp.json()["data"]["error_id"]
    assert error_id != "ERR_HOLD_WINDOW_CLOSED", (
        "priority 8 must answer before the priority 12 hold-window rule is evaluated"
    )

    _, meta = validate_paginated(
        api.list_hold_amendments(regulator_headers(), params={"amending_item_id": item_a["id"]})
    )
    assert meta["total_count"] == 0, (
        f"no amendment may be created, found {meta['total_count']}"
    )

    schedule_after = read_schedule(scene["schedule_a"]["id"])
    assert schedule_after["hold_window_ends_at"] == "2026-08-04T00:00:00.000Z", (
        f"the window shut three days after the 2026-08-01 certification, got "
        f"{schedule_after['hold_window_ends_at']}"
    )
    assert schedule_after["version"] == current_version, (
        f"a refused amendment must not advance the schedule's version, got "
        f"{schedule_after['version']} against {current_version}"
    )


# --------------------------------------------------------------------------
# Further precedence pairings inside the business band
# --------------------------------------------------------------------------

def test_09_self_reference_outranks_the_amendment_below_reference_test(api):
    """PRD §2.10: "The reference item of a hold amendment belongs to a wholesaler other
    than the amending item's wholesaler. Otherwise `ERR_SELF_REFERENCE_NOT_ALLOWED`
    (409). Applies to `POST /hold-amendments`."
    PRD §2.10: "Fiscal relations are checked after every structural and state rule above
    them."
    PRD §3.6: "Because the mechanism exists to match a *competitor*, the reference item
    must belong to a different wholesaler than the amending item; a wholesaler naming
    its own item is refused with `ERR_SELF_REFERENCE_NOT_ALLOWED`."

    Design: Corner/validations/hold_amendment_referencing_the_wholesaler_own_other_item_returns_self_reference_not_allowed
    """
    scene = setup_certified_schedule(
        item_specs=[
            {
                "size_ml": 750, "bottles_per_case": 12,
                "case_price_cents": 120_000, "unit_price_cents": 11_000,
            },
            {
                "size_ml": 375, "bottles_per_case": 6,
                "case_price_cents": 30_000, "unit_price_cents": 5_500,
            },
        ]
    )
    amending_item, own_other_item = scene["items"][0], scene["items"][1]
    version_before = schedule_version(scene["schedule"]["id"])

    # 25000 is a genuine reduction from 120000 but falls below the 30000 reference, so
    # priority 17's ERR_AMENDMENT_BELOW_REFERENCE is also live.
    resp = api.create_hold_amendment(
        create_hold_amendment_payload(
            amending_item["id"], own_other_item["id"], 25_000, 5_000, version_before
        ),
        scene["agent_headers"],
    )
    validate_error(resp, "ERR_SELF_REFERENCE_NOT_ALLOWED", 409)

    error_id = resp.json()["data"]["error_id"]
    assert error_id != "ERR_AMENDMENT_BELOW_REFERENCE", (
        "priority 11 must answer before the priority 17 fiscal-relation test"
    )

    _, meta = validate_paginated(
        api.list_hold_amendments(
            regulator_headers(), params={"amending_item_id": amending_item["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"no amendment may be created, found {meta['total_count']}"
    )

    item_after = read_item(amending_item["id"])
    assert item_after["case_price_cents"] == 120_000, (
        f"the amending item's price must be untouched, got {item_after['case_price_cents']}"
    )
    assert item_after["version"] == amending_item["version"], (
        f"the amending item's version must be untouched, got {item_after['version']} "
        f"against {amending_item['version']}"
    )


def test_10_suspended_licence_outranks_the_empty_schedule_cardinality_rule(api):
    """PRD §2.10: "A worked consequence of this table: submitting a schedule that has no
    items, whose wholesaler is `SUSPENDED`, is rejected with `ERR_LICENSE_NOT_ACTIVE`,
    not `ERR_SCHEDULE_HAS_NO_ITEMS`, because licence standing sits at priority 9 and
    cardinality at priority 19."

    Design: Corner/validations/suspended_license_outranks_the_empty_schedule_cardinality_rule
    """
    scene = setup_licensee_base()
    schedule = new_schedule(
        scene["wholesaler"]["id"], scene["program"]["id"], scene["agent_headers"]
    )
    set_license_status(scene["wholesaler"]["id"], "SUSPENDED")

    resp = api.submit_price_schedule(schedule["id"], scene["agent_headers"])
    validate_error(resp, "ERR_LICENSE_NOT_ACTIVE", 409)
    assert resp.status_code == 409, (
        f"licence standing is a 409, not the 422 of the cardinality rule, got "
        f"{resp.status_code}"
    )

    error_id = resp.json()["data"]["error_id"]
    assert error_id != "ERR_SCHEDULE_HAS_NO_ITEMS", (
        "priority 9 must answer before priority 19 is reached"
    )

    schedule_after = read_schedule(schedule["id"])
    assert schedule_after["status"] == "DRAFT", (
        f"the refused schedule stays DRAFT, got {schedule_after['status']}"
    )
    assert schedule_after["item_count"] == 0, (
        f"the schedule is still empty, got item_count {schedule_after['item_count']}"
    )

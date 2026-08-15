"""Publishing, the public searchable inventory, and inquiries (PRD §3.2, §3.3)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    advance_clock_and_sweep,
    assert_instant_equals,
    assert_version_bumped_once,
    create_inquiry,
    create_item,
    create_item_payload,
    create_location,
    create_policy,
    create_program,
    get_item,
    publish_item,
    set_clock,
    setup_program_policy_location,
    setup_stored_item,
    validate_error,
    validate_paginated,
    validate_success,
    make_intake_officer_headers,
    make_police_liaison_headers,
    create_referral_payload,
)

INTAKE = TEST_USERS["intake_officer_headers"]
PUBLIC = TEST_USERS["public_user_headers"]


def test_item_publish_transitions_to_listed(api):
    """PRD §3.2: "publishing transitions `STORED` to `LISTED`" and "Both
    transitions increment the item's version."

    Design: Corner/state_machines/item_publish_valid_transition
    """
    ctx = setup_stored_item(declared_value_cents=5000)
    before = ctx.item["version"]
    res = api.publish_item(ctx.item["id"], INTAKE)
    item = validate_success(res, 200)
    assert item["status"] == "LISTED"
    assert_version_bumped_once(before, item["version"], "Item")


def test_item_unpublish_returns_to_stored(api):
    """PRD §3.2: "publishing transitions `STORED` to `LISTED`, and unpublishing
    returns `LISTED` to `STORED`."

    Design: Corner/state_machines/item_unpublish_revert
    """
    ctx = setup_stored_item(declared_value_cents=5000)
    publish_item(ctx.item["id"])
    res = api.unpublish_item(ctx.item["id"], INTAKE)
    assert validate_success(res, 200)["status"] == "STORED"


def test_item_publish_from_listed_rejected(api):
    """PRD §3.2: "Publishing enforces its checks in order — the item must
    currently be `STORED` (`ERR_INVALID_STATE` otherwise)".

    Design: Corner/state_machines/item_publish_from_listed_returns_invalid_state
    """
    ctx = setup_stored_item(declared_value_cents=5000)
    publish_item(ctx.item["id"])
    res = api.publish_item(ctx.item["id"], INTAKE)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    assert get_item(ctx.item["id"])["status"] == "LISTED", (
        "a rejected second publish leaves the item LISTED")


def test_publish_nonexistent_item_not_found(api):
    """PRD §2.8: "The request is rejected immediately with `ERR_NOT_FOUND`
    (HTTP 404) at the first identifier that does not correspond to an existing
    resource".

    Design: Corner/validations/item_publish_not_found_returns_404
    """
    res = api.publish_item(NON_EXISTENT_UUID, INTAKE)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_publish_identification_item_rejected(api):
    """PRD §3.2: "`is_identification` is true exactly when the category is
    `ID_DOCUMENT`; identification items can never appear in the public
    inventory." PRD §3.2: "it must not be an identification item
    (`ERR_IDENTIFICATION_NOT_LISTABLE`, HTTP 422)".

    Design: Corner/errors/err_identification_not_listable_rejected
    """
    ctx = setup_stored_item(item_category="ID_DOCUMENT", declared_value_cents=100,
                            retention_days=30, disposal_method="DESTRUCTION")
    assert ctx.item["is_identification"] is True
    res = api.publish_item(ctx.item["id"], INTAKE)
    validate_error(res, ApiErrorId.ERR_IDENTIFICATION_NOT_LISTABLE, expected_status=422)
    assert get_item(ctx.item["id"])["status"] == "STORED"


def test_disposed_item_rejects_publish_and_referral(api, property_custodian_headers):
    """PRD §3.2: "`RELEASED`, `EVIDENCE`, `SOLD`, `DISPOSED`, and `DONATED` are
    terminal." PRD §3.2: "the item must currently be `STORED`
    (`ERR_INVALID_STATE` otherwise)". PRD §3.6: "A `PoliceLiaison` refers an
    item in `STORED` or `LISTED` to law enforcement".

    Design: Corner/state_machines/item_terminal_lockdown_disposed
    """
    ctx = setup_stored_item(declared_value_cents=5000, retention_days=10,
                            disposal_method="DESTRUCTION")
    advance_clock_and_sweep("2026-08-11T09:00:00Z")
    disposed = validate_success(
        api.dispose_item(ctx.item["id"], "DESTRUCTION", property_custodian_headers), 200)
    assert disposed["status"] == "DISPOSED"

    res_publish = api.publish_item(ctx.item["id"], INTAKE)
    validate_error(res_publish, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    res_refer = api.refer_item_to_law_enforcement(
        ctx.item["id"], create_referral_payload(),
        make_police_liaison_headers("liaison-1"))
    validate_error(res_refer, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    assert get_item(ctx.item["id"])["status"] == "DISPOSED", (
        "DISPOSED is terminal: neither publish nor referral may leave it")


def test_publish_response_matches_subsequent_read(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/immediate_consistency_after_publish
    """
    ctx = setup_stored_item(declared_value_cents=5000)
    published = validate_success(api.publish_item(ctx.item["id"], INTAKE), 200)
    assert published["status"] == "LISTED", (
        "the mutation is visible in the publish response itself")
    assert_version_bumped_once(ctx.item["version"], published["version"], "Item")

    reread = validate_success(api.get_item(ctx.item["id"], INTAKE), 200)
    assert reread["status"] == published["status"], (
        "the subsequent read agrees with the mutation response")
    assert reread["version"] == published["version"]


def test_public_inventory_excludes_non_listed_and_identification(api):
    """PRD §3.3: "The public inventory exposes only items that are currently
    `LISTED` and whose `is_identification` is false." PRD §3.3: "each result
    carries only `id`, `category`, `description`, `found_at`, `found_location`,
    and `program_id` — never the storage location, the declared value, or any
    claimant data."

    Design: Corner/endpoints/public_search_excludes_non_listed_and_identification
    """
    program = create_program("TRANSIT")
    create_policy(program["id"], item_category="ELECTRONICS", value_tier="LOW",
                  retention_days=10)
    create_policy(program["id"], item_category="ID_DOCUMENT", value_tier="LOW",
                  retention_days=30, disposal_method="DESTRUCTION")
    location = create_location(program["id"])
    listed = create_item(program["id"], location["id"], category="ELECTRONICS",
                         declared_value_cents=5000, description="earbuds")
    id_doc = create_item(program["id"], location["id"], category="ID_DOCUMENT",
                         declared_value_cents=100, description="driver license")
    publish_item(listed["id"])

    data, meta = validate_paginated(api.list_public_items(PUBLIC))
    ids = [entry["id"] for entry in data]
    assert listed["id"] in ids, "the LISTED electronics item is publicly visible"
    assert id_doc["id"] not in ids, (
        "identification items can never appear in the public inventory")
    for entry in data:
        assert set(entry.keys()) == {
            "id", "category", "description", "found_at", "found_location",
            "program_id",
        }, f"public projection is deliberately narrow, got {sorted(entry.keys())}"

    filtered, _ = validate_paginated(
        api.list_public_items(PUBLIC, params={"category": "ID_DOCUMENT"}))
    assert filtered == [], (
        "filtering the public inventory by ID_DOCUMENT returns an empty list")


def test_inquiry_sla_transit_program_24h(api):
    """PRD §3.3: "A `TRANSIT` program sets the deadline 24 hours after
    creation". PRD §2.5: "The logical clock drives every server-stamped
    timestamp — `created_at`, `updated_at`, and `released_at`".

    Design: Difficulty/dual_variant_calc/inquiry_sla_transit_vs_facility
    """
    set_clock("2026-08-01T09:00:00Z")
    program = create_program("TRANSIT")
    inquiry = create_inquiry(program_id=program["id"],
                             contact_email="a@x.com", subject="lost wallet",
                             message="brown wallet on route 9")
    assert inquiry["status"] == "OPEN"
    assert_instant_equals(inquiry["sla_deadline"], "2026-08-02T09:00:00Z")


def test_inquiry_sla_facility_program_72h(api):
    """PRD §3.3: "a `FACILITY` program — or no program context at all — sets it
    72 hours after creation."

    Design: Difficulty/dual_variant_calc/inquiry_sla_transit_vs_facility
    """
    set_clock("2026-08-01T09:00:00Z")
    program = create_program("FACILITY")
    inquiry = create_inquiry(program_id=program["id"],
                             contact_email="b@x.com", subject="lost keys",
                             message="keys at city hall")
    assert inquiry["status"] == "OPEN"
    assert_instant_equals(inquiry["sla_deadline"], "2026-08-04T09:00:00Z")


def test_inquiry_answer_then_close(api):
    """PRD §3.3: "An `IntakeOfficer` answers an `OPEN` inquiry, which
    transitions it to `ANSWERED`, stores the response in `answer_text`, and
    records the officer's `X-User-ID` as `answered_by`. Closing is permitted
    from either `OPEN` or `ANSWERED` and moves the inquiry to `CLOSED`, its
    terminal state." PRD §3.3: "a `FACILITY` program — or no program context at
    all — sets it 72 hours after creation."

    Design: Corner/state_machines/inquiry_answer_and_close
    """
    set_clock("2026-08-01T09:00:00Z")
    inquiry = create_inquiry(contact_email="a@x.com", subject="lost wallet",
                             message="brown wallet")
    # No item_id and no program_id: the 72-hour variant applies.
    assert_instant_equals(inquiry["sla_deadline"], "2026-08-04T09:00:00Z")

    answered = validate_success(
        api.answer_inquiry(inquiry["id"], "We have it.",
                           make_intake_officer_headers("officer-intake-1")), 200)
    assert answered["status"] == "ANSWERED"
    assert answered["answered_by"] == "officer-intake-1"

    closed = validate_success(
        api.close_inquiry(inquiry["id"],
                          make_intake_officer_headers("officer-intake-1")), 200)
    assert closed["status"] == "CLOSED"
    assert closed["answer_text"] == "We have it."

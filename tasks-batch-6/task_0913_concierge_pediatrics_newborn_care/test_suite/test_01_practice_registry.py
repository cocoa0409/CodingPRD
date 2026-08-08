"""Setting up the practice: plan tiers, panels, households and charts."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_child,
    assert_created_at_ascending,
    assert_date_equals,
    assert_envelope_object,
    assert_family,
    assert_insurance_policy,
    assert_membership_plan,
    create_child,
    create_child_payload,
    create_family,
    create_family_payload,
    create_insurance_policy_payload,
    create_membership_payload,
    is_valid_uuid,
    premier_plan_payload,
    plus_plan_payload,
    set_clock,
    setup_practice,
    setup_household,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]

UNKNOWN_MEMBERSHIP_ID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_FAMILY_ID = "22222222-2222-4222-8222-222222222222"
CLIENT_SUPPLIED_ID = "11111111-1111-4111-8111-111111111111"


def test_create_plan_tier_echoes_every_declared_field(api):
    """PRD §3.1: "It carries `included_lactation_consults` and `included_sleep_consults`,
    both at least 0, which decide how many of each benefit a membership on this tier
    receives per membership year."
    PRD §2.5: "`version` (integer): a counter that begins at 1 and increments by 1 on
    every mutation of the row."
    PRD §2.11: "Operations that bring a new resource into existence return `201 Created`."

    Design: Corner/entities/corner_create_membership_plan_echoes_every_declared_field
    """
    set_clock("2026-05-01T00:00:00Z")

    payload = premier_plan_payload()
    resp = api.create_membership_plan(payload, ADMIN)
    plan = validate_success(resp, 201)

    assert_membership_plan(plan)
    assert plan["tier"] == "PREMIER"
    assert plan["monthly_rate_cents"] == 60000
    assert plan["included_lactation_consults"] == 6
    assert plan["included_sleep_consults"] == 4
    assert plan["form_sla_hours"] == 24
    assert plan["after_hours_surcharge_waived"] is True
    assert plan["overage_consult_fee_cents"] == 12000
    assert plan["version"] == 1, "a freshly created row begins at version 1"
    assert is_valid_uuid(plan["id"]), "identifiers carry no type prefix"

    assert_envelope_object(resp.json())


def test_child_read_recomputes_age_days_and_slot_weight_from_the_clock(api):
    """PRD §3.1: "Three values are computed on every read of a child and never stored:
    `age_days`, the whole-day difference between today and `date_of_birth`;
    `current_slot_weight`, the panel weight the child consumes today under the
    2.0 / 1.5 / 1.0 bands just described; and `immunization_complete_for_age`, the
    boolean gate described in §3.5."
    PRD §3.1: "a child under one year of age — that is, whose age in whole days is
    strictly less than 365 — consumes 2.0 units of panel weight; a child of at least
    365 days but strictly under 1095 days consumes 1.5; and a child of 1095 days or
    more consumes 1.0."

    Design: Corner/entities/corner_get_child_returns_computed_age_days_and_slot_weight
    """
    set_clock("2026-06-01T00:00:00Z")
    family = create_family(household_name="Adeyemi")
    child = create_child(family["id"], first_name="Femi", date_of_birth="2026-03-01")

    first = validate_success(api.get_child(child["id"], COORDINATOR))
    assert_child(first)
    assert first["age_days"] == 92, "2026-03-01 to 2026-06-01 is 92 whole days"
    assert float(first["current_slot_weight"]) == 2.0
    assert first["family_id"] == family["id"]
    assert_date_equals(first["date_of_birth"], "2026-03-01", "Child.date_of_birth")

    set_clock("2027-04-01T00:00:00Z")

    later = validate_success(api.get_child(child["id"], COORDINATOR))
    assert later["age_days"] == 396, "the same child re-reads its age against the new clock"
    assert float(later["current_slot_weight"]) == 1.5, "396 days sits in the 365-1095 band"
    assert_date_equals(later["date_of_birth"], "2026-03-01", "Child.date_of_birth")


def test_list_children_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "`limit` caps how many rows the page returns; it defaults to 10, may be
    no smaller than 1 and no larger than 100."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` in
    the envelope's `meta` object, where `total_count` counts every row matching the
    supplied filters — not the rows on the returned page — and `has_more` is true when
    rows remain beyond the current page."
    PRD §2.3: "List results are ordered by the row's creation timestamp, ascending, in
    every collection"

    Design: Corner/entities/corner_list_children_paginates_with_total_count_and_has_more
    """
    set_clock("2026-06-01T00:00:00Z")
    family = create_family(household_name="Barros")
    c1 = create_child(family["id"], first_name="Uno", date_of_birth="2026-01-01")
    c2 = create_child(family["id"], first_name="Dos", date_of_birth="2026-02-01")
    c3 = create_child(family["id"], first_name="Tres", date_of_birth="2026-03-01")

    resp = api.list_children(COORDINATOR, params={"family_id": family["id"], "limit": 2, "offset": 0})
    page1, meta1 = validate_paginated(resp)
    assert [row["id"] for row in page1] == [c1["id"], c2["id"]]
    assert_created_at_ascending(page1)
    assert meta1["total_count"] == 3
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0
    assert meta1["has_more"] is True
    assert resp.json()["response_type"] == "array"

    resp2 = api.list_children(COORDINATOR, params={"family_id": family["id"], "limit": 2, "offset": 2})
    page2, meta2 = validate_paginated(resp2)
    assert [row["id"] for row in page2] == [c3["id"]]
    assert meta2["total_count"] == 3
    assert meta2["limit"] == 2
    assert meta2["offset"] == 2
    assert meta2["has_more"] is False
    assert resp2.json()["response_type"] == "array"


def test_get_membership_with_unknown_id_returns_membership_not_found(api):
    """PRD §2.6: "A membership yields `ERR_MEMBERSHIP_NOT_FOUND`."
    PRD §2.6: "Everything else — an insurance policy, panel waitlist entry, entitlement
    grant, consult booking, well visit, immunization dose, encounter, service line,
    invoice or form request — yields the generic `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/entities/corner_get_membership_with_unknown_id_returns_not_found
    """
    set_clock("2026-05-01T00:00:00Z")

    resp = api.get_membership(UNKNOWN_MEMBERSHIP_ID, ADMIN)
    error = validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_FOUND)

    assert resp.status_code == 404
    body = resp.json()
    assert body["response_type"] == "error"
    assert "error_id" in error and "message" in error


def test_register_child_without_date_of_birth_is_rejected(api):
    """PRD §2.7: "On every POST endpoint, each field the endpoint declares as required
    must be present and carry its declared JSON type, failing which the response is
    `ERR_VALIDATION` (400)."
    PRD §3.1: "**Children** are registered by a `PracticeAdmin` or a `CareCoordinator`
    into an existing household, naming the `family_id`, the child's `first_name` and a
    `date_of_birth`."

    Design: Corner/entities/corner_create_child_missing_required_date_of_birth_returns_invalid_request
    """
    set_clock("2026-06-01T00:00:00Z")
    family = create_family(household_name="Costa")

    resp = api.create_child({"family_id": family["id"], "first_name": "Nia"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    assert resp.status_code == 400

    rows, meta = validate_paginated(api.list_children(COORDINATOR, params={"family_id": family["id"]}))
    assert rows == [] and meta["total_count"] == 0, "the rejected create persisted nothing"


def test_insurance_policy_created_without_status_opens_active(api):
    """PRD §3.1: "The optional `status` defaults to `ACTIVE` and may be supplied as
    `TERMINATED` at creation for a policy that is being recorded historically."
    PRD §3.1: "The running counter `deductible_met_cents` starts at 0 and thereafter
    tracks the deductible conservation identity of §2.10."

    Design: Corner/entities/corner_create_insurance_policy_omitting_status_defaults_to_active
    """
    set_clock("2026-06-01T00:00:00Z")
    family = create_family(household_name="Dumont")

    payload = create_insurance_policy_payload(
        family["id"], carrier_name="Lakeside", deductible_cents=30000, coinsurance_rate=0.25
    )
    payload.pop("status", None)
    resp = api.create_insurance_policy(payload, BILLING)
    policy = validate_success(resp, 201)

    assert_insurance_policy(policy)
    assert policy["status"] == "ACTIVE"
    assert policy["deductible_met_cents"] == 0
    assert policy["version"] == 1

    rows, meta = validate_paginated(
        api.list_insurance_policies(BILLING, params={"family_id": family["id"]})
    )
    assert meta["total_count"] == 1 and len(rows) == 1


def test_family_id_and_version_are_server_minted_not_client_supplied(api):
    """PRD §2.5: "`id` (string): a server-minted UUID. Identifiers carry no type prefix
    and are never supplied by the client."
    PRD §2.5: "`version` (integer): a counter that begins at 1 and increments by 1 on
    every mutation of the row."
    PRD §3.1: "It also exposes a computed `active_membership_count`: how many of its
    memberships currently hold status `PENDING_ACTIVATION`, `ACTIVE` or `SUSPENDED`."

    Design: Corner/entities/corner_create_family_with_client_supplied_id_input_ignored
    """
    set_clock("2026-05-01T00:00:00Z")

    payload = create_family_payload(
        household_name="Erikson", family_monthly_cap_cents=90000
    )
    payload["id"] = CLIENT_SUPPLIED_ID
    payload["version"] = 99

    family = validate_success(api.create_family(payload, ADMIN), 201)

    assert_family(family)
    assert family["id"] != CLIENT_SUPPLIED_ID, "the id is minted by the server"
    assert family["version"] == 1, "version begins at 1 regardless of any supplied value"
    assert family["household_name"] == "Erikson"
    assert family["family_monthly_cap_cents"] == 90000
    assert family["active_membership_count"] == 0


def test_create_plan_with_undeclared_tier_returns_invalid_enum(api):
    """PRD §2.7: "Each enum-typed body field must carry a declared member value — this
    covers `tier`, `form_type`, `consult_type`, `modality`, `encounter_type`,
    `vaccine_code`, `benefit_type`, `status`, `route`, `validity`, `clinical_status`,
    `billing_status` and `milestone_code`, whether supplied in a body or as a list
    filter — failing which the response is `ERR_INVALID_ENUM` (400)."
    PRD §3.1: "Each plan row declares a `tier` of `ESSENTIAL`, `PLUS` or `PREMIER`"

    Design: Corner/entities/corner_create_plan_with_invalid_enum_tier_returns_invalid_enum
    """
    set_clock("2026-05-01T00:00:00Z")

    resp = api.create_membership_plan(plus_plan_payload(tier="GOLD"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)
    assert resp.status_code == 400


def test_register_child_into_unknown_household_returns_family_not_found(api):
    """PRD §2.7: "`family_id` is checked on child creation, insurance-policy creation and
    invoice creation (`ERR_FAMILY_NOT_FOUND`)."
    PRD §2.6: "A household that does not resolve yields `ERR_FAMILY_NOT_FOUND`."

    Design: Corner/entities/corner_create_child_with_unknown_family_id_returns_family_not_found
    """
    set_clock("2026-06-01T00:00:00Z")

    payload = create_child_payload(
        UNKNOWN_FAMILY_ID, first_name="Ghost", date_of_birth="2026-01-01"
    )
    resp = api.create_child(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_FAMILY_NOT_FOUND)
    assert resp.status_code == 404


def test_membership_denormalizes_family_id_from_the_child(api):
    """PRD §3.2: "Its `family_id` is denormalised from the child at creation and never
    changes afterwards."
    PRD §2.3: "Memberships filter on `family_id`, `child_id`, `plan_id`, `physician_id`
    and `status`."
    PRD §3.1: "It also exposes a computed `active_membership_count`: how many of its
    memberships currently hold status `PENDING_ACTIVATION`, `ACTIVE` or `SUSPENDED`."

    Design: Corner/entities/corner_membership_denormalizes_family_id_from_child
    """
    practice = setup_practice(clock="2026-06-01T00:00:00Z")
    household = setup_household(household_name="Fontaine", child_first_name="Lior")
    family, child = household["family"], household["child"]

    payload = create_membership_payload(
        child["id"],
        practice["plan"]["id"],
        practice["physician"]["id"],
        "2026-06-01",
        family["version"],
    )
    membership = validate_success(api.create_membership(payload, COORDINATOR), 201)

    assert membership["family_id"] == family["id"], (
        "family_id is never supplied in the request body; it is copied from the child"
    )

    for field, value in (
        ("family_id", family["id"]),
        ("child_id", child["id"]),
        ("physician_id", practice["physician"]["id"]),
        ("plan_id", practice["plan"]["id"]),
    ):
        rows, meta = validate_paginated(api.list_memberships(ADMIN, params={field: value}))
        assert meta["total_count"] == 1, f"filter on {field} must find exactly one row"
        assert rows[0]["id"] == membership["id"]

    refreshed = validate_success(api.get_family(family["id"], ADMIN))
    assert refreshed["active_membership_count"] == 1

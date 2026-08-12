"""Drafting monitored profiles, the identifiers that define them, activation
and pausing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    assert_identifier, assert_monitored_profile, fixtures as fx,
)


def test_drafting_a_profile_without_the_primary_address_is_rejected(api):
    """PRD §2.6: "6. Every field the endpoint declares as required is present in the
    request body — otherwise `ERR_VALIDATION` (422). Applies to every POST, PUT and PATCH
    endpoint."
    PRD §3.3: "Drafting one is available to the `AccountOwner` and to a `Member`, and the
    payload names the `member_id` whose identity is being monitored, the `full_name` as it
    should be matched at brokers, a `date_of_birth` as an ISO 8601 calendar date, and a
    `primary_address` street address."

    Design: Corner/entities/monitored_profile_missing_required_field_returns_validation
    """
    household = fx.open_household()

    response = api.create_monitored_profile(
        {"member_id": household["owner_id"], "full_name": "Dana Owner",
         "date_of_birth": "1984-03-02"},
        household["owner"])

    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)
    _, meta = validate_paginated(api.list_member_profiles(household["owner_id"], fx.ADMIN))
    assert meta["total_count"] == 0


def test_omitted_optional_profile_inputs_take_their_declared_defaults(api):
    """PRD §3.3: "Two further inputs are optional at draft time: `rescan_cadence_days`, the
    requested interval between recurring scans, which defaults to 30 and must be at least 7
    and at most 180; and `two_factor_attested`, defaulting to false, which records whether
    the member has attested that every credential behind this identity sits behind a second
    factor."
    PRD §3.3: "A profile is born in `DRAFT` and consumes nothing."

    Design: Corner/entities/monitored_profile_defaults_applied_when_optional_fields_omitted
    """
    household = fx.open_household()

    data = validate_success(api.create_monitored_profile(
        {"member_id": household["owner_id"], "full_name": "Dana Owner",
         "date_of_birth": "1984-03-02",
         "primary_address": "12 Elm St, Springfield"},
        household["owner"]), 201)

    assert_monitored_profile(data)
    assert data["rescan_cadence_days"] == 30
    assert data["two_factor_attested"] is False
    assert data["status"] == "DRAFT"
    assert data["activated_at"] is None
    assert data["last_completed_scan_at"] is None
    # No findings at all: raw 0, capped 0, multiplier 1.00, so 100 - 0.00 = 100.00.
    assert float(data["hygiene_score"]) == 100.00
    assert data["hygiene_band"] == "STRONG"


def test_drafting_a_profile_for_an_unknown_member_is_not_found(api):
    """PRD §2.6: "11. Every foreign key supplied in the request body resolves to an
    existing row — otherwise the body-specific 404 code from §2.5. The rung guards account
    opening, plan changes, profile drafting, scan queuing, finding recording, removal
    drafting, credential-finding recording and seat binding, over the identifiers
    `plan_id`, `new_plan_id`, `member_id`, `profile_id`, `broker_id`, `exposure_id` and
    `addon_id`."
    PRD §2.5: "a `member_id` yields `ERR_MEMBER_NOT_FOUND`"

    Design: Corner/entities/monitored_profile_create_with_unknown_member_id_returns_not_found
    """
    household = fx.open_household()

    response = api.create_monitored_profile(
        {"member_id": "00000000-0000-4000-8000-000000000000", "full_name": "Ghost",
         "date_of_birth": "1990-01-01", "primary_address": "nowhere"},
        household["owner"])

    validate_error(response, ApiErrorId.ERR_MEMBER_NOT_FOUND.value, 404)


def test_an_identifier_is_immutable_and_carries_no_version(api):
    """PRD §2.4: "A monitored **identifier** is immutable once written and carries only
    `id` and `created_at` — it has no `updated_at` and no `version`."
    PRD §3.3: "Because two clients can each legitimately add an identifier without either
    colliding with the cap, the addition is guarded by `expected_profile_version` as §2.8
    describes, and a successful addition bumps the profile's `version`."

    Design: Corner/entities/identifier_is_immutable_and_carries_no_version_field
    """
    household = fx.open_household()
    profile = fx.draft_profile(household)

    data = validate_success(api.add_identifier(
        profile["id"],
        {"identifier_type": "SSN_LAST4", "identifier_value": "4417",
         "expected_profile_version": profile["version"]},
        household["owner"]), 201)

    assert_identifier(data)
    assert data["identifier_type"] == "SSN_LAST4"
    assert data["identifier_value"] == "4417"

    _, meta = validate_paginated(api.list_identifiers(profile["id"], household["owner"]))
    assert meta["total_count"] == 1
    assert fx.read_profile(profile["id"])["version"] == 2, \
        "the addition bumps the parent profile, not the immutable child"


def test_the_ninth_identifier_on_a_profile_is_rejected(api):
    """PRD §3.3: "Two constraints guard the addition: the profile must not already carry a
    row with the same `identifier_type` and `identifier_value` pair
    (`ERR_DUPLICATE_IDENTIFIER`), and the profile must hold fewer than eight identifiers, a
    **strict** boundary — the eighth identifier is admitted, taking the count from 7 to 8,
    and the ninth is rejected with `ERR_IDENTIFIER_CAP_EXCEEDED`."

    Design: Corner/validations/ninth_identifier_on_a_profile_is_rejected_by_the_cap
    """
    household = fx.open_household()
    profile = fx.draft_profile(household)
    plan = [("EMAIL", "id1@example.com"), ("EMAIL", "id2@example.com"),
            ("EMAIL", "id3@example.com"), ("EMAIL", "id4@example.com"),
            ("PHONE", "+15550001"), ("PHONE", "+15550002"),
            ("USERNAME", "dana_o"), ("SSN_LAST4", "4417")]
    for identifier_type, value in plan:
        fx.add_identifier(profile["id"], household["owner"],
                          identifier_type=identifier_type, identifier_value=value)

    version_before = fx.profile_version(profile["id"], household["owner"])
    response = api.add_identifier(
        profile["id"],
        {"identifier_type": "ADDRESS", "identifier_value": "12 Elm St",
         "expected_profile_version": version_before},
        household["owner"])

    validate_error(response, ApiErrorId.ERR_IDENTIFIER_CAP_EXCEEDED.value, 409)
    _, meta = validate_paginated(api.list_identifiers(profile["id"], household["owner"]))
    assert meta["total_count"] == 8, "the eighth was admitted, the ninth was not"
    # Version 1 at creation plus one bump per accepted add; the refusal moves nothing.
    assert version_before == 9
    assert fx.profile_version(profile["id"], household["owner"]) == 9


def test_re_adding_the_same_identifier_type_and_value_pair_is_rejected(api):
    """PRD §3.3: "Two constraints guard the addition: the profile must not already carry a
    row with the same `identifier_type` and `identifier_value` pair
    (`ERR_DUPLICATE_IDENTIFIER`), and the profile must hold fewer than eight identifiers, a
    **strict** boundary — the eighth identifier is admitted, taking the count from 7 to 8,
    and the ninth is rejected with `ERR_IDENTIFIER_CAP_EXCEEDED`."

    Design: Corner/validations/duplicate_identifier_pair_on_the_same_profile_is_rejected
    """
    household = fx.open_household()
    profile = fx.draft_profile(household)
    fx.add_identifier(profile["id"], household["owner"],
                      identifier_type="EMAIL", identifier_value="dana@example.com")
    version = fx.profile_version(profile["id"], household["owner"])

    response = api.add_identifier(
        profile["id"],
        {"identifier_type": "EMAIL", "identifier_value": "dana@example.com",
         "expected_profile_version": version},
        household["owner"])

    validate_error(response, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value, 409)
    _, meta = validate_paginated(api.list_identifiers(profile["id"], household["owner"]))
    assert meta["total_count"] == 1

    # Only the full pair is unique: the same value under a different type lands.
    validate_success(api.add_identifier(
        profile["id"],
        {"identifier_type": "PHONE", "identifier_value": "dana@example.com",
         "expected_profile_version": version},
        household["owner"]), 201)


def test_activating_a_profile_with_no_identifier_is_rejected(api):
    """PRD §3.3: "A profile with no identifiers is rejected with
    `ERR_PROFILE_HAS_NO_IDENTIFIER`; an exhausted pool with `ERR_PROFILE_QUOTA_EXCEEDED`."
    PRD §3.3: "From `DRAFT`, activation requires the profile to be in `DRAFT`, at least one
    identifier row to exist on it, the owning member to be `ACTIVE`, the account to be
    `ACTIVE`, and `profile_units_remaining` to be at least 1."

    Design: Corner/validations/activating_a_profile_with_no_identifier_is_rejected
    """
    household = fx.open_household()
    profile = fx.draft_profile(household)

    response = api.activate_profile(profile["id"], household["owner"])

    validate_error(response, ApiErrorId.ERR_PROFILE_HAS_NO_IDENTIFIER.value, 409)
    row = fx.read_profile(profile["id"])
    assert row["status"] == "DRAFT"
    assert row["activated_at"] is None
    account = fx.read_account(household)
    assert account["profile_units_consumed"] == 0
    assert account["profile_units_remaining"] == 4


def test_the_second_activation_on_a_one_profile_plan_is_rejected(api):
    """PRD §2.6: "43. The account's `profile_units_remaining` is at least 1, otherwise
    `ERR_PROFILE_QUOTA_EXCEEDED` (409). Applies to profile activation."
    PRD §3.3: "`ACTIVE → RETIRED` additionally cancels every `QUEUED` scan on the profile
    and appends a `PROFILE` `RELEASE` entry of `amount` 1 with `reason_code`
    `PROFILE_RETIRED`; `PAUSED → RETIRED` appends the same release entry (the queued scans
    were already cancelled by the pause); `DRAFT → RETIRED` releases nothing, because
    nothing was ever consumed."

    Design: Corner/validations/second_profile_activation_rejected_by_profile_quota
    """
    household = fx.open_household(tier="SOLO", name="Solo Micro",
                                  monthly_fee_cents=900, max_members=2,
                                  profile_quota_per_cycle=1, scan_quota_per_cycle=4,
                                  removal_quota_per_cycle=5,
                                  per_member_removal_subcap=5)
    first = fx.setup_active_profile(household, identifier_value="dana@example.com")
    second = fx.draft_profile(household, full_name="Dana Owner Alias",
                              primary_address="9 Oak Ave, Springfield")
    fx.add_identifier(second["id"], household["owner"],
                      identifier_value="dana.alias@example.com")

    response = api.activate_profile(second["id"], household["owner"])

    validate_error(response, ApiErrorId.ERR_PROFILE_QUOTA_EXCEEDED.value, 409)
    assert fx.read_profile(second["id"])["status"] == "DRAFT"

    validate_success(api.retire_profile(first["id"], household["owner"]))
    freed = fx.read_account(household)
    assert freed["profile_units_released"] == 1
    assert freed["profile_units_remaining"] == 1

    data = validate_success(api.activate_profile(second["id"], household["owner"]))
    assert data["status"] == "ACTIVE"
    account = fx.read_account(household)
    assert account["profile_units_granted"] == 1
    assert account["profile_units_consumed"] == 2
    assert account["profile_units_released"] == 1
    assert account["profile_units_remaining"] == 0


def test_pausing_a_profile_cancels_its_queued_scan_and_refunds_the_unit(api):
    """PRD §3.3: "Pausing moves `ACTIVE → PAUSED` and cancels every scan run on the profile
    sitting in `QUEUED`. The profile's entitlement unit stays held throughout the pause;
    only retirement gives it back."
    PRD §3.4: "The two cancellation edges, `QUEUED → CANCELLED` and `FAILED → CANCELLED`,
    both set `entitlement_units_held` to 0, append a `SCAN` `RELEASE` entry of `amount` 1,
    and raise `scan_units_released` and `scan_units_remaining` by one — but they differ in
    one field: `QUEUED → CANCELLED` carries `reason_code` `SCAN_CANCELLED`, while
    `FAILED → CANCELLED` carries `reason_code` `SCAN_ABANDONED`."

    Design: Corner/state_machines/profile_pause_cancels_queued_scan_and_refunds_the_unit
    """
    household = fx.open_household()
    profile = fx.setup_active_profile(household)
    running = fx.queue_scan(profile["id"], kind="INITIAL")
    fx.start_scan(running["id"])
    queued = fx.queue_scan(profile["id"], kind="RECURRING")

    data = validate_success(api.pause_profile(profile["id"], household["owner"]))

    assert data["status"] == "PAUSED"
    cancelled = validate_success(api.get_scan_run(queued["id"], fx.ADMIN))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["entitlement_units_held"] == 0
    survivor = validate_success(api.get_scan_run(running["id"], fx.ADMIN))
    assert survivor["status"] == "RUNNING", "a running scan is not cancelled by a pause"
    assert survivor["entitlement_units_held"] == 1

    account = fx.read_account(household)
    assert account["scan_units_consumed"] == 2
    assert account["scan_units_released"] == 1
    assert account["scan_units_remaining"] == 11
    assert account["profile_units_released"] == 0, \
        "pausing never releases the profile unit"

    rows, meta = fx.ledger_entries(household["account_id"],
                                   resource_type="SCAN", entry_type="RELEASE")
    assert meta["total_count"] == 1
    assert rows[0]["reason_code"] == "SCAN_CANCELLED"

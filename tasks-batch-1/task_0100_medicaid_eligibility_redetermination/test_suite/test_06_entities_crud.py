"""Entity creation, computed-field derivation, system-field assignment, and the
universal not-found / required-field / enum-validation behaviors.
"""
from test_helpers import (
    api_client as api,
    TEST_USERS,
    get_success_data, validate_success, validate_error, ApiErrorId,
    setup_config, setup_household,
)

CW = TEST_USERS["caseworker_headers"]
APP = TEST_USERS["applicant_headers"]


# ===========================================================================
# Queue B — entities corner
# ===========================================================================
def test_create_household_returns_201_and_ledger_defaults():
    """PRD §3.2: "A freshly created household starts with `household_size` at
    zero, `covered_member_months` at zero, and `active_enrollment_count` at zero."
    PRD §2.4: "the `version` field is an integer that begins at its initial value
    and increments by one with every mutation of the resource."

    Design: Corner/entities/create_household_returns_201_and_ledger_defaults
    """
    setup_config(state="CA")
    hh = validate_success(api.create_household(
        {"state_code": "CA", "fpl_year": 2026, "primary_applicant_name": "Hannah H"}, APP), 201)
    assert hh["covered_member_months"] == 0
    assert hh["active_enrollment_count"] == 0
    assert hh["household_size"] == 0
    assert hh["version"] == 1


def test_get_household_not_found_returns_404():
    """PRD §2.9: "rejecting the request with `ERR_NOT_FOUND` at the first
    identifier that does not resolve to an existing resource."

    Design: Corner/entities/get_household_not_found_returns_404
    """
    resp = api.get_household("00000000-0000-4000-8000-000000000001", CW)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_household_missing_required_state_code_returns_422():
    """PRD §2.9: "a body missing a required field, carrying an invalid enum
    member, or supplying a negative integer where a non-negative value is required
    yields `ERR_INVALID_REQUEST` at HTTP 422."

    Design: Corner/entities/create_household_missing_required_state_code_returns_422
    """
    get_success_data(api.create_fpl_schedule(
        {"year": 2026, "base_annual_cents": 1500000, "per_member_increment_cents": 520000}, CW))
    resp = api.create_household({"fpl_year": 2026, "primary_applicant_name": "No State"}, CW)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_member_invalid_relationship_enum_returns_422():
    """PRD §2.9: "a body missing a required field, carrying an invalid enum
    member ... yields `ERR_INVALID_REQUEST` at HTTP 422."
    PRD §3.2: "a `relationship` drawn from `SELF`, `SPOUSE`, `CHILD`,
    `DEPENDENT`, or `OTHER`."

    Design: Corner/entities/create_member_invalid_relationship_enum_returns_422
    """
    hh = setup_household(state="CA", name="Enum E")
    resp = api.add_member(hh["id"], {"full_name": "Bad Rel", "age": 30, "relationship": "COUSIN"}, CW)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_income_source_magi_countable_computed_from_type():
    """PRD §3.2: "Whether the source counts toward MAGI is not supplied by the
    client; the server derives the `is_magi_countable` flag from the `income_type`,
    treating `CHILD_SUPPORT`, `TANF`, and `GIFT` as non-countable and every other
    type as countable."

    Design: Corner/entities/income_source_magi_countable_computed_from_type
    """
    hh = setup_household(state="CA", name="Comp C")
    mem = get_success_data(api.add_member(
        hh["id"], {"full_name": "Comp C", "age": 30, "relationship": "SELF"}, CW))
    wage = validate_success(api.add_income_source(
        mem["id"], {"income_type": "WAGES", "monthly_amount_cents": 100000}, CW), 201)
    cs = validate_success(api.add_income_source(
        mem["id"], {"income_type": "CHILD_SUPPORT", "monthly_amount_cents": 50000}, CW), 201)
    assert wage["is_magi_countable"] is True
    assert cs["is_magi_countable"] is False


def test_asset_exempt_and_countable_value_computed():
    """PRD §3.2: "a `HOME` is fully exempt, one `VEHICLE` is exempt, and a
    `BURIAL_FUND` is exempt up to a cap with any excess counting; everything else
    counts in full."
    PRD §3.6: "A `BURIAL_FUND` contributes its `value_cents` reduced by the burial
    exemption cap of $1,500 (150000 cents), but never below zero".

    Design: Corner/entities/asset_exempt_and_countable_value_computed
    """
    hh = setup_household(state="CA", name="Asset A")
    home = validate_success(api.add_asset(
        hh["id"], {"asset_type": "HOME", "value_cents": 5000000}, CW), 201)
    burial = validate_success(api.add_asset(
        hh["id"], {"asset_type": "BURIAL_FUND", "value_cents": 200000}, CW), 201)
    assert home["is_exempt"] is True
    assert home["countable_value_cents"] == 0
    assert burial["countable_value_cents"] == 50000  # 200000 - 150000 cap


def test_member_id_system_field_input_ignored():
    """PRD §3.2: "The `household_id` that ties a member to its household is set by
    the server from the path, never supplied in the body."

    Design: Corner/entities/member_id_system_field_input_ignored
    """
    hh = setup_household(state="CA", name="Sys S")
    mem = validate_success(api.add_member(
        hh["id"], {"full_name": "Sys S", "age": 30, "relationship": "SELF"}, CW), 201)
    assert mem["household_id"] == hh["id"]


def test_household_size_recomputed_on_member_exclude():
    """PRD §3.2: "A `CaseWorker` may later exclude a member; doing so sets that
    member's `member_status` to `EXCLUDED` and recomputes `household_size`. An
    excluded member contributes neither to `household_size` nor to the household's
    MAGI."

    Design: Corner/entities/household_size_recomputed_on_member_exclude
    """
    hh = setup_household(state="CA", name="Size S")
    api.add_member(hh["id"], {"full_name": "Size S", "age": 30, "relationship": "SELF"}, CW)
    mem_b = get_success_data(api.add_member(
        hh["id"], {"full_name": "Sib S", "age": 25, "relationship": "OTHER"}, CW))
    excluded = validate_success(api.exclude_member(mem_b["id"], CW))
    assert excluded["member_status"] == "EXCLUDED"
    hh_after = validate_success(api.get_household(hh["id"], CW))
    assert hh_after["household_size"] == 1

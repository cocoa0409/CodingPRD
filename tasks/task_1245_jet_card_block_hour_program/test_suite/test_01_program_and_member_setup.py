"""Program onboarding, member registration, and card purchase defaults."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_card_program,
    assert_jet_card,
    assert_member,
    create_card_payload,
    create_member_payload,
    create_program_payload,
    get_success_data,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["ops_headers"]


def test_card_program_creation_required_fields(api):
    """PRD §4: "Endpoints that create a new resource return 201 on success; endpoints that
    modify an existing resource or perform an action return 200."
    PRD §2.4: "Most resources additionally carry `updated_at` (same timestamp format,
    refreshed on every mutation) and an integer `version` that starts at 1 on creation
    and increments by 1 on every mutation of that resource."
    PRD §2.11: "A malformed payload that fails schema validation surfaces as
    `ERR_INVALID_REQUEST` (HTTP 400) before any of the above."

    Design: Corner/entities/card_program_creation_required_fields
    """
    payload = create_program_payload(
        program_code="CORNER_P1",
        aircraft_category="MIDSIZE",
        hours_purchased=50,
        purchase_price_cents=30_000_000,
        swap_ratio_to_lower=0.85,
        swap_ratio_to_higher=1.30,
        expiry_months=24,
    )
    resp = api.create_program(payload, OPS)
    data = validate_success(resp, expected_status=201)
    assert_card_program(data)
    assert data["program_code"] == "CORNER_P1"
    assert data["version"] == 1, f"new resource version must start at 1, got {data['version']}"

    # Missing required fields fail schema validation with ERR_INVALID_REQUEST.
    bad = api.create_program({"program_code": "INCOMPLETE", "aircraft_category": "LIGHT"}, OPS)
    validate_error(bad, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_member_creation_and_default_status(api):
    """PRD §3.2: "A new member starts with `member_status` set to `ACTIVE`."

    Design: Corner/entities/member_creation_and_default_status
    """
    resp = api.create_member(create_member_payload(), OPS)
    data = validate_success(resp, expected_status=201)
    assert_member(data)
    assert data["member_status"] == "ACTIVE", (
        f"new member must start ACTIVE, got {data['member_status']}"
    )


def test_jet_card_expires_at_computed(api):
    """PRD §3.3: "When `Ops` activates the card — which requires only that the referenced
    program still exists — the card moves from `PENDING_PAYMENT` to `ACTIVE`,
    `purchased_at` is stamped with the current logical time, and `expires_at` is computed
    as `purchased_at` plus the program's `expiry_months`."

    Design: Corner/entities/jet_card_expires_at_computed
    """
    from test_helpers import activate_card, create_member, create_program, purchase_card, set_clock

    set_clock("2026-06-15T00:00:00Z")
    program = create_program(program_code="CORNER_EXP", expiry_months=18)
    member = create_member()
    card = purchase_card(member["id"], program["id"])
    activated = activate_card(card["id"])
    assert_jet_card(activated)
    expires = activated["expires_at"]
    # Tolerate optional fractional-second rendering of the same instant.
    assert expires.replace(".000Z", "Z").startswith("2027-12-15T00:00:00"), (
        f"expires_at must be purchased_at (2026-06-15) + 18 months = 2027-12-15, got {expires}"
    )
    purchased = activated["purchased_at"]
    assert purchased.replace(".000Z", "Z").startswith("2026-06-15T00:00:00"), (
        f"purchased_at must be stamped with the current logical time, got {purchased}"
    )


def test_card_initial_state_pending_payment(api):
    """PRD §3.3: "The card is born in `PENDING_PAYMENT` status with its `member_id` bound
    to the purchasing member and `hours_total` mirroring the program's `hours_purchased`."

    Design: Corner/state_machines/card_initial_state_pending_payment
    """
    from test_helpers import create_member, create_program, purchase_card, set_clock

    set_clock()
    program = create_program(program_code="SM3", hours_purchased=25)
    member = create_member()
    resp = api.create_card(member["id"], create_card_payload(program["id"]), OPS)
    data = validate_success(resp, expected_status=201)
    assert_jet_card(data)
    assert data["card_status"] == "PENDING_PAYMENT", (
        f"new card must start PENDING_PAYMENT, got {data['card_status']}"
    )
    assert data["hours_total"] == 25
    assert data["member_id"] == member["id"]

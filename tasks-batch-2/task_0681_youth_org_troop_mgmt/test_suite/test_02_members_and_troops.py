"""Member registration, the dues-driven lifecycle, troop creation, and derived counts."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_council,
    create_troop,
    create_member,
    create_council_and_troop,
    create_registered_youth,
    create_cleared_trained_leader,
    create_council_payload,
    create_troop_payload,
    create_member_payload,
    create_dues_invoice_payload,
)

REG = TEST_USERS["registrar_headers"]
LEAD = TEST_USERS["leader_headers"]


def test_create_council_returns_201_with_zero_balances(api):
    """PRD §3.1: "A council begins life with fund_cash_cents and fund_liability_cents
    both at zero, and those two balances thereafter are always recomputed from the
    ledger as described in §2.9."

    Design: Corner/entities/create_council_returns_201_with_defaults
    """
    data = validate_success(api.create_council(create_council_payload(name="C1"), REG), 201)
    assert data["fund_cash_cents"] == 0
    assert data["fund_liability_cents"] == 0


def test_get_member_not_found_returns_404(api):
    """PRD §2.7: "the system validates them strictly left to right and rejects the
    request with ERR_NOT_FOUND (HTTP 404) at the first identifier in the path that
    does not name an existing resource."

    Design: Corner/entities/get_member_not_found_returns_404
    """
    resp = api.get_member("00000000-0000-4000-8000-000000000000", REG)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_troop_missing_unit_number_rejected(api):
    """PRD §3.9: "General body well-formedness — required fields present and
    well-typed, valid enums, ends_at after starts_at, units at least one,
    amount_cents greater than zero, and unique troop unit number within the council
    — is reported as ERR_INVALID_REQUEST."

    Design: Corner/entities/create_troop_missing_unit_number_returns_invalid_request
    """
    council = create_council(name="C2")
    resp = api.create_troop(council["id"], {"program_type": "SCOUTS"}, REG)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_duplicate_unit_number_within_council_rejected(api):
    """PRD §3.1: "A duplicate unit number within the same council is rejected with
    ERR_DUPLICATE_UNIT_NUMBER."

    Design: Corner/entities/duplicate_unit_number_within_council_rejected
    """
    council = create_council(name="C3")
    create_troop(council["id"], unit_number="U-A", program_type="SCOUTS")
    resp = api.create_troop(council["id"], create_troop_payload(unit_number="U-A", program_type="CUB"), REG)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_UNIT_NUMBER.value)


def test_invalid_member_type_enum_rejected(api):
    """PRD §3.9: "General body well-formedness — required fields present and
    well-typed, valid enums ... — is reported as ERR_INVALID_REQUEST."

    Design: Corner/entities/invalid_member_type_enum_rejected
    """
    council, troop = create_council_and_troop(
        council_overrides={"name": "C4"}, troop_overrides={"unit_number": "U-B"}
    )
    resp = api.create_member(
        troop["id"], {"member_type": "GROWNUP", "full_name": "X", "birthdate": "2010-01-01"}, LEAD
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_new_member_starts_pending_scout_regardless_of_input(api):
    """PRD §3.2: "A new member is stamped with the parent's troop_id, opens in
    registration_status PENDING, and — when a youth — begins at rank SCOUT."

    Design: Corner/entities/member_id_and_system_fields_ignored_on_input
    """
    council, troop = create_council_and_troop(
        council_overrides={"name": "C5"}, troop_overrides={"unit_number": "U-C"}
    )
    member = validate_success(
        api.create_member(troop["id"], create_member_payload(member_type="YOUTH", full_name="Newbie"), LEAD), 201
    )
    assert member["registration_status"] == "PENDING"
    assert member["rank"] == "SCOUT"


def test_list_members_returns_paginated_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the meta
    object of the response envelope: limit, offset, total_count, and has_more."

    Design: Corner/entities/list_members_paginated_envelope
    """
    council, troop = create_council_and_troop(
        council_overrides={"name": "C7"}, troop_overrides={"unit_number": "U-E"}
    )
    create_member(troop["id"], member_type="YOUTH", full_name="L Youth")

    resp = api.list_members(REG, params={"troop_id": troop["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_suspend_dropped_member_is_invalid_state(api):
    """PRD §3.2: "Suspending a member is permitted only while registration_status is
    REGISTERED and moves it to SUSPENDED."
    PRD §3.2: "Any member transition attempted from a state where it is not defined
    is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/suspend_already_dropped_member_invalid_state
    """
    council, troop = create_council_and_troop(
        council_overrides={"name": "S1"}, troop_overrides={"unit_number": "S-1"}
    )
    member = create_member(troop["id"], member_type="YOUTH", full_name="D Youth")
    get_success_data(api.drop_member(member["id"], LEAD))

    resp = api.suspend_member(member["id"], LEAD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    member_after = validate_success(api.get_member(member["id"], REG), 200)
    assert member_after["registration_status"] == "DROPPED"


def test_drop_member_voids_open_invoices(api):
    """PRD §3.2: "Dropping a member is the terminal exit: from the REGISTERED,
    SUSPENDED, or PENDING states a drop moves the member to DROPPED, voids every
    OPEN DuesInvoice belonging to that member (each such invoice's status becomes
    VOID)."

    Design: Corner/state_machines/drop_member_voids_open_invoices
    """
    council, troop = create_council_and_troop(
        council_overrides={"name": "S2"}, troop_overrides={"unit_number": "S-2"}
    )
    member = create_member(troop["id"], member_type="YOUTH", full_name="V Youth")
    inv = get_success_data(
        api.create_dues_invoice(member["id"], create_dues_invoice_payload(issued_on="2026-01-01"), REG)
    )

    get_success_data(api.drop_member(member["id"], LEAD))

    member_after = validate_success(api.get_member(member["id"], REG), 200)
    inv_after = validate_success(api.get_dues_invoice(inv["id"], REG), 200)
    assert member_after["registration_status"] == "DROPPED"
    assert inv_after["status"] == "VOID"


def test_derived_troop_counts_reconcile_on_suspend(api):
    """PRD §2.5: "The registered_youth_count is the number of members in the troop
    whose member_type is YOUTH and whose registration_status is REGISTERED."
    PRD §2.5: "The cleared_leader_count is the number of adult members in the troop
    ... who hold a LeaderCredential whose bgcheck_status is CLEARED and whose
    training_status is TRAINED — both dimensions must be satisfied for a leader to
    count."

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_troop_counts
    """
    council, troop = create_council_and_troop(
        council_overrides={"name": "DR1"}, troop_overrides={"unit_number": "DR-1"}
    )
    youth = create_registered_youth(troop["id"], full_name="DY")
    create_cleared_trained_leader(troop["id"], full_name="DL")

    before = validate_success(api.get_troop(troop["id"], REG), 200)
    assert before["registered_youth_count"] == 1
    assert before["cleared_leader_count"] == 1

    get_success_data(api.suspend_member(youth["id"], LEAD))

    after = validate_success(api.get_troop(troop["id"], REG), 200)
    assert after["cleared_leader_count"] == 1
    assert after["registered_youth_count"] == 0, "suspended youth no longer counted"

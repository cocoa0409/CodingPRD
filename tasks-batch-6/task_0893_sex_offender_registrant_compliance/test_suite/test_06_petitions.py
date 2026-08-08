"""Petitions to deregister: grant cascade, eligibility gating, duplicates, and
terminal-state lockdown."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_jurisdiction, create_registrant, add_offense, activate, add_address,
    get_registrant, set_clock, open_flag, file_petition, get_petition,
    setup_active_registrant, TEST_USERS,
)

OFFICER = TEST_USERS["registration_officer_headers"]
REVIEWER = TEST_USERS["compliance_reviewer_headers"]


def _eligible_registrant_with_residence_and_petition():
    """TIER_1 registrant registered at 2026-05-01 with a VERIFIED residence and a
    PENDING DEREGISTER petition; clock advanced to 2036-05-01 (>=10y, clean)."""
    jur = create_jurisdiction()
    reg = create_registrant(jur["id"], full_name="Free F", date_of_birth="1970-01-01T00:00:00Z")
    add_offense(reg["id"], conviction_date="2016-01-01T00:00:00Z")  # CLASS_B -> TIER_1
    reg = activate(reg["id"])
    addr = add_address(reg["id"], reg["version"], address_type="RESIDENCE",
                       line1="9 Home Rd", grid_x=5000, grid_y=5000)
    pet = file_petition(reg["id"], petition_type="DEREGISTER")
    set_clock("2036-05-01T00:00:00Z")
    return jur, reg, addr, pet


def test_grant_petition_deregisters_registrant(api):
    """PRD 3.8: "On a successful grant the petition moves `PENDING → GRANTED` with
    `decided_date` set to the clock, and the registrant cascades
    `ACTIVE → DEREGISTERED`: every `VERIFIED` address of that registrant transitions
    to `HISTORICAL` and its `current_residence_address_id` is cleared to null."

    Design: Difficulty/transitive_cascade/petition_grant_cascades_addresses_historical
    """
    jur, reg, addr, pet = _eligible_registrant_with_residence_and_petition()
    resp = api.decide_petition(pet["id"], {"decision": "GRANT", "reviewer_ref": "rev-7"}, REVIEWER)
    data = validate_success(resp, expected_status=200)
    assert data["decision"] == "GRANTED"
    reg_after = get_registrant(reg["id"])
    assert reg_after["status"] == "DEREGISTERED"


def test_grant_petition_marks_addresses_historical(api):
    """PRD 3.8: "the registrant cascades `ACTIVE → DEREGISTERED`: every `VERIFIED`
    address of that registrant transitions to `HISTORICAL` and its
    `current_residence_address_id` is cleared to null."

    Design: Difficulty/transitive_cascade/petition_grant_cascades_addresses_historical
    """
    jur, reg, addr, pet = _eligible_registrant_with_residence_and_petition()
    api.decide_petition(pet["id"], {"decision": "GRANT", "reviewer_ref": "rev-7"}, REVIEWER)
    addrs = get_success_data(api.list_addresses(reg["id"], OFFICER))
    listed = {a["id"]: a for a in addrs}
    assert listed[addr["id"]]["status"] == "HISTORICAL"


def _dirty_eligible_registrant_with_petition():
    """TIER_1 registrant, 10y met, but carrying one OPEN MINOR flag (not clean)."""
    jur = create_jurisdiction()
    reg = create_registrant(jur["id"], full_name="Dirty D", date_of_birth="1970-01-01T00:00:00Z")
    add_offense(reg["id"], conviction_date="2016-01-01T00:00:00Z")
    reg = activate(reg["id"])
    set_clock("2036-05-01T00:00:00Z")
    open_flag(reg["id"], flag_type="TRAVEL_VIOLATION")  # OPEN MINOR, risk 5 -> stays ACTIVE
    pet = file_petition(reg["id"], petition_type="DEREGISTER")
    return jur, reg, pet


def test_grant_rejected_when_registrant_has_open_flag(api):
    """PRD 3.8: "A grant decision re-checks eligibility at decision time: it
    requires the petition to be a `PENDING` `DEREGISTER`, the registrant to be
    `ACTIVE` with zero `OPEN` flags, and deregistration eligibility to still hold;
    if any of these fails, the grant is rejected with `ERR_PETITION_NOT_ELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/petition_grant_requires_registrant_clean
    """
    jur, reg, pet = _dirty_eligible_registrant_with_petition()
    resp = api.decide_petition(pet["id"], {"decision": "GRANT", "reviewer_ref": "rev-1"}, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_PETITION_NOT_ELIGIBLE)


def test_grant_rejection_leaves_petition_pending(api):
    """PRD 3.8: "if any of these fails, the grant is rejected with
    `ERR_PETITION_NOT_ELIGIBLE`."
    PRD 3.8: "Deciding a petition that is not `PENDING` is rejected with
    `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/petition_grant_requires_registrant_clean
    """
    jur, reg, pet = _dirty_eligible_registrant_with_petition()
    api.decide_petition(pet["id"], {"decision": "GRANT", "reviewer_ref": "rev-1"}, REVIEWER)
    after = get_petition(pet["id"])
    assert after["decision"] == "PENDING", "a rejected grant must leave the petition PENDING"


def test_second_pending_petition_rejected(api):
    """PRD 3.8: "Only one open petition is allowed at a time: filing while a
    `PENDING` petition already exists is rejected with
    `ERR_DUPLICATE_ACTIVE_PETITION`."

    Design: Corner/validations/duplicate_pending_petition_rejected
    """
    jur, reg = setup_active_registrant(full_name="Dup D")
    file_petition(reg["id"], petition_type="DEREGISTER")
    resp = api.create_petition(reg["id"], {"petition_type": "TIER_REDUCTION"}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_PETITION)


def test_deciding_already_denied_petition_rejected(api):
    """PRD 3.8: "Deciding a petition that is not `PENDING` is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/decide_terminal_petition_returns_invalid_state
    """
    jur, reg = setup_active_registrant(full_name="Term T")
    pet = file_petition(reg["id"], petition_type="DEREGISTER")
    api.decide_petition(pet["id"], {"decision": "DENY", "reviewer_ref": "rev-2"}, REVIEWER)
    resp = api.decide_petition(pet["id"], {"decision": "GRANT", "reviewer_ref": "rev-2"}, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

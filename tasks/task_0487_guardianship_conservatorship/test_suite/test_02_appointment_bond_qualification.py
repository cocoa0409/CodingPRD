"""Appointment creation, bond sizing/posting/approval, and qualification.

Difficulty: combinatorial bond sizing, qualify-depends-on-bond cross-entity,
fiduciary open-appointment-count conservation under qualify/remove.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
)
from test_helpers import factories as F
from test_helpers import fixtures as fx


def _bond_for(api, appointment_id):
    body = api.list_bonds(fx.JUDGE, params={"appointment_id": appointment_id}).json()
    return body["data"][0]


# ===========================================================================
# Difficulty: combinatorial bond sizing (3 inputs, nested min/max, PLENARY reserve)
# ===========================================================================
def test_bond_required_amount_plenary_tiered(api):
    """PRD 3.3: "buffer the first 10,000,000 cents of that exposure at a multiplier
    of one and any exposure above 10,000,000 cents at a multiplier of
    one-and-one-tenth; add the two buffered slices to obtain a raw figure. If the
    case is PLENARY, add a reserve of 1,000,000 cents to the raw figure."

    Design: Difficulty/combinatorial_formula/cf_bond_tiered_nested_minmax
    """
    ctx = fx.case_to_awaiting_appointment(
        case_type="PLENARY",
        requested_authority="BOTH",
        recommended_scope="BOTH",
        person_overrides={"annual_income_cents": 3_000_000, "liquid_estate_cents": 12_000_000},
        fiduciary_overrides={"fiduciary_kind": "FAMILY"},
    )
    appt = fx.create_appointment(ctx["case_id"], ctx["fiduciary_id"])
    bond = _bond_for(api, appt["id"])
    # exposure 15,000,000 -> core 10,000,000*1.0 + excess 5,000,000*1.1 = 15,500,000
    # + PLENARY reserve 1,000,000 = 16,500,000
    assert bond["required_amount_cents"] == 16_500_000


def test_bond_required_amount_conservatorship_excess_band(api):
    """PRD 3.3: "buffer the first 10,000,000 cents of that exposure at a multiplier
    of one and any exposure above 10,000,000 cents at a multiplier of
    one-and-one-tenth; add the two buffered slices to obtain a raw figure."

    Design: Difficulty/combinatorial_formula/cf_bond_tiered_nested_minmax
    """
    # CONSERVATORSHIP (no PLENARY reserve), exposure 12,000,000 exercises the
    # excess band: core 10,000,000*1.0 + excess 2,000,000*1.1 = 12,200,000.
    ctx = fx.case_to_awaiting_appointment(
        case_type="CONSERVATORSHIP",
        requested_authority="ESTATE",
        recommended_scope="ESTATE",
        person_overrides={"annual_income_cents": 4_000_000, "liquid_estate_cents": 8_000_000},
    )
    appt = fx.create_appointment(ctx["case_id"], ctx["fiduciary_id"])
    bond = _bond_for(api, appt["id"])
    assert bond["required_amount_cents"] == 12_200_000


def test_bond_floor_pins_small_estate(api):
    """PRD 3.3: "then take the greater of that rounded figure and a floor of
    500,000 cents — the floor wins whenever the buffered exposure would otherwise
    fall below it."

    Design: Corner/calculations/bond_floor_applies_for_small_estate
    """
    ctx = fx.case_to_awaiting_appointment(
        case_type="CONSERVATORSHIP",
        requested_authority="ESTATE",
        recommended_scope="ESTATE",
        person_overrides={"annual_income_cents": 50_000, "liquid_estate_cents": 100_000},
    )
    appt = fx.create_appointment(ctx["case_id"], ctx["fiduciary_id"])
    bond = _bond_for(api, appt["id"])
    # exposure 150,000 -> raw 150,000 < floor 500,000 -> floor wins
    assert bond["required_amount_cents"] == 500_000


# ===========================================================================
# Bond posting validations
# ===========================================================================
def test_bond_insufficient_amount_rejected_on_post(api):
    """PRD 3.3: "posting advances the bond from REQUIRED to POSTED and requires
    that the posted amount be at least the required_amount_cents (else
    ERR_BOND_INSUFFICIENT)".

    Design: Corner/validations/bond_insufficient_amount_rejected_on_post
    """
    ctx = fx.case_to_awaiting_appointment(
        case_type="CONSERVATORSHIP",
        requested_authority="ESTATE",
        recommended_scope="ESTATE",
        person_overrides={"annual_income_cents": 2_000_000, "liquid_estate_cents": 8_000_000},
    )
    appt = fx.create_appointment(ctx["case_id"], ctx["fiduciary_id"])
    bond = _bond_for(api, appt["id"])
    # required = exposure 10,000,000 -> core 10,000,000*1.0 = 10,000,000
    resp = api.post_bond(
        bond["id"],
        F.post_bond_payload(posted_amount_cents=9_999_999),
        fx.make_fiduciary_headers(ctx["fiduciary_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BOND_INSUFFICIENT)


def test_judge_cannot_post_bond(api):
    """PRD 2.1: "A Fiduciary is the appointed (or candidate) guardian or
    conservator who submits operational artifacts but cannot approve them."

    Design: Corner/rbac/rbac_judge_cannot_post_bond
    """
    ctx = fx.case_to_awaiting_appointment(
        case_type="CONSERVATORSHIP",
        requested_authority="ESTATE",
        recommended_scope="ESTATE",
        person_overrides={"annual_income_cents": 2_000_000, "liquid_estate_cents": 8_000_000},
    )
    appt = fx.create_appointment(ctx["case_id"], ctx["fiduciary_id"])
    bond = _bond_for(api, appt["id"])
    validate_error(
        api.post_bond(bond["id"], F.post_bond_payload(), fx.JUDGE),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
    )


# ===========================================================================
# Appointment guards
# ===========================================================================
def test_appointment_create_disqualified_fiduciary_rejected(api):
    """PRD 3.3: "The nominated fiduciary must not be disqualified at creation: if
    the Fiduciary's is_disqualified flag is true, the create is rejected with
    ERR_FIDUCIARY_DISQUALIFIED."

    Design: Corner/validations/appointment_create_disqualified_fiduciary_rejected
    """
    # First case: qualify the fiduciary, then remove for cause to disqualify.
    ctx1 = fx.active_case(case_type="GUARDIANSHIP", fiduciary_kind="PROFESSIONAL")
    api.remove_appointment(
        ctx1["appointment_id"], F.remove_appointment_payload(for_cause=True), fx.JUDGE
    )
    fid = get_success_data(api.get_fiduciary(ctx1["fiduciary_id"], fx.JUDGE))
    assert fid["is_disqualified"] is True

    # Second case names the now-disqualified fiduciary.
    person2 = fx.create_person()
    case2 = fx.create_case(person2["id"], case_type="GUARDIANSHIP")
    petition2 = fx.file_petition(
        case2["id"], ctx1["fiduciary_id"], petitioner_id="pet-2"
    )
    api.find_probable_cause(petition2["id"], fx.JUDGE)
    api.order_evaluation(petition2["id"], fx.JUDGE)
    ev2 = get_success_data(
        api.create_evaluation(F.create_evaluation_payload(petition2["id"]), fx.EXAMINER)
    )
    api.file_evaluation(ev2["id"], fx.EXAMINER)
    api.grant_petition(petition2["id"], fx.JUDGE)
    resp = api.create_appointment(
        F.create_appointment_payload(case2["id"], ctx1["fiduciary_id"]), fx.JUDGE
    )
    validate_error(resp, ApiErrorId.ERR_FIDUCIARY_DISQUALIFIED)


# ===========================================================================
# Difficulty: qualify depends on bond being APPROVED (cross-entity)
# ===========================================================================
def test_qualify_rejected_while_bond_only_posted(api):
    """PRD 3.3: "if the case requires_bond, the appointment's bond must be in
    APPROVED (else ERR_BOND_NOT_APPROVED)."

    Design: Difficulty/cross_entity_state_dependency/cesd_qualify_requires_bond_approved
    """
    ctx = fx.case_to_awaiting_appointment(
        case_type="CONSERVATORSHIP",
        requested_authority="ESTATE",
        recommended_scope="ESTATE",
        person_overrides={"liquid_estate_cents": 8_000_000},
    )
    appt = fx.create_appointment(ctx["case_id"], ctx["fiduciary_id"])
    bond = _bond_for(api, appt["id"])
    api.post_bond(
        bond["id"],
        F.post_bond_payload(posted_amount_cents=10_000_000),
        fx.make_fiduciary_headers(ctx["fiduciary_id"]),
    )
    validate_error(
        api.qualify_appointment(appt["id"], fx.JUDGE),
        ApiErrorId.ERR_BOND_NOT_APPROVED,
    )


def test_qualify_succeeds_after_bond_approved(api):
    """PRD 3.3: "Qualification stamps letters_issued_iso with the current clock
    instant, moves the appointment to ACTIVE, increments the fiduciary's
    open_appointment_count by one, and bubbles the case up from
    AWAITING_APPOINTMENT to ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/cesd_qualify_requires_bond_approved
    """
    ctx = fx.case_to_awaiting_appointment(
        case_type="CONSERVATORSHIP",
        requested_authority="ESTATE",
        recommended_scope="ESTATE",
        person_overrides={"liquid_estate_cents": 8_000_000},
    )
    appt = fx.create_appointment(ctx["case_id"], ctx["fiduciary_id"])
    bond = _bond_for(api, appt["id"])
    api.post_bond(
        bond["id"],
        F.post_bond_payload(posted_amount_cents=10_000_000),
        fx.make_fiduciary_headers(ctx["fiduciary_id"]),
    )
    api.approve_bond(bond["id"], fx.JUDGE)
    result = validate_success(api.qualify_appointment(appt["id"], fx.JUDGE))
    assert result["status"] == "ACTIVE"


# ===========================================================================
# Difficulty: fiduciary open_appointment_count conserved by qualify/remove
# ===========================================================================
def test_fiduciary_count_raised_by_qualify(api):
    """PRD 3.3: "Qualification stamps letters_issued_iso with the current clock
    instant, moves the appointment to ACTIVE, increments the fiduciary's
    open_appointment_count by one, and bubbles the case up from
    AWAITING_APPOINTMENT to ACTIVE."

    Design: Difficulty/compensating_invariant/ci_fiduciary_count_conserved_by_remove
    """
    ctx = fx.active_case(case_type="GUARDIANSHIP", fiduciary_kind="FAMILY")
    fid = get_success_data(api.get_fiduciary(ctx["fiduciary_id"], fx.JUDGE))
    assert fid["open_appointment_count"] == 1


def test_fiduciary_count_restored_by_remove(api):
    """PRD 3.3: "Removal moves the appointment to REVOKED, decrements the
    fiduciary's open_appointment_count by one (a suspended appointment still
    counts as open, so the decrement applies whether it was removed from ACTIVE or
    SUSPENDED), and, if the appointment's bond was APPROVED, exonerates it to
    EXONERATED."

    Design: Difficulty/compensating_invariant/ci_fiduciary_count_conserved_by_remove
    """
    ctx = fx.active_case(case_type="GUARDIANSHIP", fiduciary_kind="FAMILY")
    api.remove_appointment(
        ctx["appointment_id"], F.remove_appointment_payload(for_cause=False), fx.JUDGE
    )
    fid = get_success_data(api.get_fiduciary(ctx["fiduciary_id"], fx.JUDGE))
    assert fid["open_appointment_count"] == 0
    assert fid["is_disqualified"] is False


# ===========================================================================
# Immediate consistency
# ===========================================================================
def test_qualify_changes_visible_immediately(api):
    """PRD 3.3: "Qualification stamps letters_issued_iso with the current clock
    instant, moves the appointment to ACTIVE, increments the fiduciary's
    open_appointment_count by one, and bubbles the case up from
    AWAITING_APPOINTMENT to ACTIVE."

    Design: Corner/consistency_model/immediate_consistency_qualify_visible_in_response
    """
    ctx = fx.case_to_awaiting_appointment(
        case_type="CONSERVATORSHIP",
        requested_authority="ESTATE",
        recommended_scope="ESTATE",
        person_overrides={"annual_income_cents": 2_000_000, "liquid_estate_cents": 8_000_000},
    )
    appt = fx.create_appointment(ctx["case_id"], ctx["fiduciary_id"])
    fx.post_and_approve_bond(appt["id"], ctx["fiduciary_id"])
    qualify_result = validate_success(api.qualify_appointment(appt["id"], fx.JUDGE))
    assert qualify_result["status"] == "ACTIVE"
    case = get_success_data(api.get_case(ctx["case_id"], fx.JUDGE))
    assert case["status"] == "ACTIVE"

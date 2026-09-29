"""Lifecycles that loop, run in parallel, or fork on the way out.

A member contract cycles between issuance and negotiation under a hard round cap;
a member's health posture advances on its own dimension and only gates one act;
a facility agreement loops through counter-offers before forking on signature.
"""

from test_helpers import (
    ApiErrorId,
    CORPS_DIRECTOR_HEADERS,
    MEMBERSHIP_COORDINATOR_HEADERS,
    TOUR_MANAGER_HEADERS,
    assert_facility_agreement,
    assert_member,
    assert_member_contract,
    factories as f,
    fixtures as fx,
    make_member_headers,
    validate_error,
)


def _contract_at_the_revision_cap(api, season_id):
    """Three closed rounds leaving the contract ISSUED at round three."""
    member = fx.offered_member(api, season_id)
    contract = fx.issue_contract(api, member["id"], tuition_amount_cents=399900,
                                payment_plan_type="STANDARD_3")
    fx.request_revision(api, contract["id"], member["id"])
    fx.reissue_contract(api, contract["id"], tuition_amount_cents=389900)
    fx.request_revision(api, contract["id"], member["id"])
    fx.reissue_contract(api, contract["id"], payment_plan_type="EXTENDED_6")
    fx.request_revision(api, contract["id"], member["id"])
    contract = fx.reissue_contract(api, contract["id"], tuition_amount_cents=379900)
    assert_member_contract(
        contract,
        status="ISSUED",
        revision_round=3,
        tuition_amount_cents=379900,
        payment_plan_type="EXTENDED_6",
    )
    return member, contract


def test_a_fourth_revision_request_is_still_accepted_out_of_issued(api):
    """The cap sits on the reissue, so the request itself never trips it.

    PRD: "Note the asymmetry, which is intentional: a revision may always be
    requested out of `ISSUED` regardless of how many rounds have already closed, so
    a member who has exhausted the cap can still send a contract into
    `REVISION_REQUESTED` and strand it there permanently."

    Design: Difficulty/non_linear_state_machine/member_contract_revision_loop_caps_at_three_completed_rounds
    """
    season = fx.create_season(api)
    member, contract = _contract_at_the_revision_cap(api, season["id"])

    fourth = fx.request_revision(api, contract["id"], member["id"])

    assert_member_contract(
        fourth,
        status="REVISION_REQUESTED",
        revision_round=3,
        tuition_amount_cents=379900,
        payment_plan_type="EXTENDED_6",
    )
    assert fx.get_member(api, member["id"])["membership_status"] == "OFFERED"


def test_a_fourth_reissue_is_refused_and_strands_the_contract(api):
    """The fourth close is refused and the terms of round three survive intact.

    PRD: "The cap is enforced on the reissue rather than on the request, so a
    reissue is permitted only while `revision_round` is strictly less than 3; a
    fourth attempt is refused with `ERR_MAX_REVISION_ROUNDS_EXCEEDED` and the
    contract is left sitting in `REVISION_REQUESTED`."

    Design: Difficulty/non_linear_state_machine/member_contract_revision_loop_caps_at_three_completed_rounds
    """
    season = fx.create_season(api)
    member, contract = _contract_at_the_revision_cap(api, season["id"])
    fx.request_revision(api, contract["id"], member["id"])

    response = api.reissue_member_contract(
        contract["id"], f.reissue_payload(tuition_amount_cents=369900),
        MEMBERSHIP_COORDINATOR_HEADERS,
    )
    validate_error(response, ApiErrorId.MAX_REVISION_ROUNDS_EXCEEDED, 409)

    stranded = fx.get_contract(api, contract["id"])
    assert_member_contract(
        stranded,
        status="REVISION_REQUESTED",
        revision_round=3,
        tuition_amount_cents=379900,
        payment_plan_type="EXTENDED_6",
    )


def test_a_stranded_contract_cannot_be_signed_out_of_revision_requested(api):
    """The strand is permanent: signature demands ISSUED.

    PRD: "Signing moves the contract `ISSUED → SIGNED_BY_MEMBER`, stores the typed
    `signature_name`, and stamps `signed_at` with the current logical-clock
    instant."

    Design: Difficulty/non_linear_state_machine/member_contract_revision_loop_caps_at_three_completed_rounds
    """
    season = fx.create_season(api)
    member, contract = _contract_at_the_revision_cap(api, season["id"])
    fx.request_revision(api, contract["id"], member["id"])

    response = api.sign_member_contract(
        contract["id"], f.signature_payload("Stranded Member"),
        make_member_headers(member["id"]),
    )
    validate_error(response, ApiErrorId.INVALID_CONTRACT_STATE, 409)

    assert fx.get_contract(api, contract["id"])["status"] == "REVISION_REQUESTED"
    assert fx.get_member(api, member["id"])["membership_status"] == "OFFERED"


# ------------------------------------------------- the parallel medical dimension
def _signed_but_unexecuted_contract(api, season_id):
    member = fx.offered_member(api, season_id)
    contract = fx.issue_contract(api, member["id"], tuition_amount_cents=399900)
    fx.sign_contract(api, contract["id"], member["id"])
    return member, fx.get_contract(api, contract["id"])


def test_a_sidelined_member_may_hold_a_signed_contract_but_not_execute_it(api):
    """Sidelining blocks the countersignature without touching the contract.

    PRD: "the member's `medical_status` must be `CLEARED` — a `RESTRICTED` or
    `SIDELINED` member may hold a signed contract but may not be executed onto the
    roster, and the attempt reports `ERR_MEDICAL_NOT_CLEARED`"

    Design: Difficulty/non_linear_state_machine/member_parallel_medical_dimension_gates_contract_execution
    """
    season = fx.create_season(api)
    member, contract = _signed_but_unexecuted_contract(api, season["id"])

    fx.set_medical(api, member["id"], "SIDELINED", note="Stress fracture")
    response = api.execute_member_contract(contract["id"], CORPS_DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.MEDICAL_NOT_CLEARED, 409)

    assert fx.get_contract(api, contract["id"])["status"] == "SIGNED_BY_MEMBER"
    assert_member(
        fx.get_member(api, member["id"]),
        membership_status="OFFERED",
        medical_status="SIDELINED",
        tuition_charged_cents=0,
    )
    assert fx.get_season(api, season["id"])["tuition_charged_cents"] == 0


def test_a_restricted_member_is_refused_on_the_same_ground(api):
    """The intermediate rung blocks execution exactly as sidelining does.

    PRD: "Only one rule couples the dimensions, and it points in a single
    direction: contract execution reads `medical_status` and refuses to proceed
    unless it is `CLEARED`."

    Design: Difficulty/non_linear_state_machine/member_parallel_medical_dimension_gates_contract_execution
    """
    season = fx.create_season(api)
    member, contract = _signed_but_unexecuted_contract(api, season["id"])

    fx.set_medical(api, member["id"], "SIDELINED")
    fx.set_medical(api, member["id"], "RESTRICTED")
    response = api.execute_member_contract(contract["id"], CORPS_DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.MEDICAL_NOT_CLEARED, 409)

    assert fx.get_contract(api, contract["id"])["status"] == "SIGNED_BY_MEMBER"
    assert fx.get_member(api, member["id"])["membership_status"] == "OFFERED"


def test_returning_to_cleared_releases_the_same_signed_contract(api):
    """A round trip through both restricted rungs leaves execution available.

    PRD: "On success the member moves `OFFERED → CONTRACTED`, the member's
    `tuition_charged_cents` is set to the contract's `tuition_amount_cents`, the
    member's `tuition_balance_cents` is recomputed as the charged amount less the
    paid amount but never below 0, the season's `tuition_charged_cents` rollup is
    recomputed, and both the contract's and the member's `version` advance by one."

    Design: Difficulty/non_linear_state_machine/member_parallel_medical_dimension_gates_contract_execution
    """
    season = fx.create_season(api)
    member, contract = _signed_but_unexecuted_contract(api, season["id"])

    fx.set_medical(api, member["id"], "SIDELINED")
    fx.set_medical(api, member["id"], "RESTRICTED")
    fx.set_medical(api, member["id"], "CLEARED")
    executed = fx.execute_contract(api, contract["id"])

    assert_member_contract(executed, status="EXECUTED")
    assert executed["executed_at"] is not None
    assert_member(
        fx.get_member(api, member["id"]),
        membership_status="CONTRACTED",
        medical_status="CLEARED",
        tuition_charged_cents=399900,
        tuition_balance_cents=399900,
    )
    assert fx.get_season(api, season["id"])["tuition_charged_cents"] == 399900


def test_medical_moves_never_disturb_membership_standing(api):
    """Health posture travels on its own axis in both directions.

    PRD: "each such call advances the member's `version` by one and leaves
    `membership_status` completely untouched. The converse also holds — a
    `SIDELINED` member keeps their membership standing, their contract and their
    sleeping arrangement."

    Design: Difficulty/non_linear_state_machine/member_parallel_medical_dimension_gates_contract_execution
    """
    season = fx.create_season(api)
    member, contract = _signed_but_unexecuted_contract(api, season["id"])

    for status in ("RESTRICTED", "SIDELINED", "RESTRICTED", "CLEARED"):
        moved = fx.set_medical(api, member["id"], status)
        assert moved["medical_status"] == status
        assert moved["membership_status"] == "OFFERED"
        assert fx.get_contract(api, contract["id"])["status"] == "SIGNED_BY_MEMBER"


# ------------------------------------- the counter loop and the signature fork
def _agreement_at_the_counter_cap(api, season_id):
    """Two recorded counters, awaiting the school's signature at 500 cents."""
    school = fx.create_school(api, name="Rockford High School", city="Rockford",
                              state_code="IL")
    agreement = fx.draft_agreement(api, school["id"], season_id,
                                   nightly_rate_cents=700, minimum_billable_beds=100,
                                   start_date="2027-05-10", end_date="2027-06-05")
    fx.submit_agreement(api, agreement["id"])
    fx.counter_agreement(api, agreement["id"], 600)
    fx.submit_agreement(api, agreement["id"])
    fx.counter_agreement(api, agreement["id"], 500)
    agreement = fx.submit_agreement(api, agreement["id"])
    assert_facility_agreement(
        agreement,
        status="SUBMITTED",
        counter_round=2,
        nightly_rate_cents=700,
        countered_nightly_rate_cents=500,
        effective_nightly_rate_cents=None,
        billable_cents=0,
    )
    return school, agreement


def test_a_third_counter_is_refused_and_the_second_offer_stands(api):
    """The loop closes after two rounds and the agreement stays submitted.

    PRD: "At most two counter rounds may be recorded, so a counter is permitted
    only while `counter_round` is strictly less than 2; a third attempt is refused
    with `ERR_MAX_COUNTER_ROUNDS_EXCEEDED` and leaves the agreement sitting in
    `SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/facility_agreement_counter_loop_then_signed_branch_pins_countered_rate
    """
    season = fx.create_season(api)
    _school, agreement = _agreement_at_the_counter_cap(api, season["id"])

    response = api.counter_facility_agreement(
        agreement["id"], f.counter_payload(400), TOUR_MANAGER_HEADERS
    )
    validate_error(response, ApiErrorId.MAX_COUNTER_ROUNDS_EXCEEDED, 409)

    unchanged = fx.get_agreement(api, agreement["id"])
    assert_facility_agreement(
        unchanged,
        status="SUBMITTED",
        counter_round=2,
        countered_nightly_rate_cents=500,
        effective_nightly_rate_cents=None,
    )


def test_the_signature_branch_pins_the_countered_rate_and_bills_the_floor(api):
    """Signing after two counters bills 100 beds for 26 nights at 500 cents.

    PRD: "`effective_nightly_rate_cents` is pinned at signing to the
    `countered_nightly_rate_cents` whenever `counter_round` is greater than 0, and
    to the originally proposed `nightly_rate_cents` otherwise; it stays null until
    the agreement is signed."

    Design: Difficulty/non_linear_state_machine/facility_agreement_counter_loop_then_signed_branch_pins_countered_rate
    """
    season = fx.create_season(api)
    _school, agreement = _agreement_at_the_counter_cap(api, season["id"])

    signed = fx.sign_agreement(api, agreement["id"])

    assert_facility_agreement(
        signed,
        status="SIGNED",
        counter_round=2,
        nightly_rate_cents=700,
        countered_nightly_rate_cents=500,
        effective_nightly_rate_cents=500,
        minimum_billable_beds=100,
        occupied_bed_nights=0,
        billable_bed_nights=2600,
        billable_cents=1300000,
    )
    assert fx.get_season(api, season["id"])["housing_cost_cents"] == 1300000

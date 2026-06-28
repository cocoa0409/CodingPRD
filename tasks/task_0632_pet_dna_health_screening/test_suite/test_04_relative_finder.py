"""Relative-finder kinship variants, the finalized-report confirm precondition,
opt-out cascade, and confirm terminal-state lockdown.

Covers queue A (dual_variant_calc kinship, cross_entity_state_dependency confirm)
and queue B (state_machines opt-out cascade & confirm-already-confirmed,
validations opt-in).
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    setup_two_pets_both_finalized,
    setup_estimated_match_two_pets,
    create_account,
    create_pet,
)
from test_helpers.factories import create_relative_match_payload
from test_helpers.test_users import make_account_headers

LAB = TEST_USERS["lab_technician_headers"]


# =========================================================================
# dual_variant_calc: kinship estimated vs confirmed (queue A)
# =========================================================================

def test_kinship_estimated_variant_raw_shared_cm(api):
    """PRD §3.6: "At creation, the estimated variant is used: `relationship_pct`
    is `shared_cm` divided by the total autosomal length of 2500.0, multiplied by
    100, rounded half-up to two decimals."

    Design: Difficulty/dual_variant_calc/kinship_estimated_vs_confirmed_on_relative_match
    """
    base = setup_two_pets_both_finalized(shared_cm=600)
    match = validate_success(api.get_relative_match(base["match"]["id"], LAB))
    assert match["relationship_pct"] == 24.00, \
        f"estimated 600/2500*100 must be 24.00, got {match['relationship_pct']}"
    assert match["status"] == "ESTIMATED", f"expected ESTIMATED, got {match['status']}"


def test_kinship_confirmed_variant_applies_phase_factor(api):
    """PRD §3.6: "When a match is later confirmed, the confirmed variant applies a
    phasing correction: `relationship_pct` is `shared_cm` multiplied by the phasing
    factor of 0.98, divided by 2500.0, multiplied by 100, and rounded half-up to
    two decimals."

    Design: Difficulty/dual_variant_calc/kinship_estimated_vs_confirmed_on_relative_match
    """
    base = setup_two_pets_both_finalized(shared_cm=600)
    resp = api.confirm_relative_match(base["match"]["id"], LAB)
    match = validate_success(resp)
    assert match["relationship_pct"] == 23.52, \
        f"confirmed 600*0.98/2500*100 must be 23.52, got {match['relationship_pct']}"
    assert match["status"] == "CONFIRMED", f"expected CONFIRMED, got {match['status']}"


# =========================================================================
# cross_entity_state_dependency: confirm requires both pets finalized (queue A)
# =========================================================================

def test_confirm_with_one_pet_not_finalized_rejected(api):
    """PRD §3.6: "Confirmation is permitted only when the match is `ESTIMATED` and
    both referenced pets have a finalized report — that is, both pets'
    `finalized_report_id` are non-null. A confirm attempted before both pets are
    finalized is rejected with `ERR_REPORTS_NOT_FINALIZED`."

    Design: Difficulty/cross_entity_state_dependency/match_confirm_requires_both_pets_finalized_report
    """
    # pet1 finalized; pet2 only registered (no report). Build manually.
    from test_helpers.fixtures import _finalize_pet_report
    account = create_account(relative_finder_opt_in=True)
    pet1 = create_pet(account["id"], name="P1", relative_finder_opt_in=True)
    pet2 = create_pet(account["id"], name="P2", relative_finder_opt_in=True)
    _finalize_pet_report(account["id"], pet1["id"], breed="LABRADOR")

    match = get_success_data(
        api.create_relative_match(
            create_relative_match_payload(pet1["id"], pet2["id"], shared_cm=1250), LAB
        )
    )
    resp = api.confirm_relative_match(match["id"], LAB)
    validate_error(resp, ApiErrorId.ERR_REPORTS_NOT_FINALIZED.value)


def test_confirm_with_one_pet_not_finalized_leaves_match_estimated(api):
    """PRD §3.6: "A confirm attempted before both pets are finalized is rejected
    with `ERR_REPORTS_NOT_FINALIZED`."
    PRD §3.6: "A new match is created in the `ESTIMATED` state"

    Design: Difficulty/cross_entity_state_dependency/match_confirm_requires_both_pets_finalized_report
    """
    from test_helpers.fixtures import _finalize_pet_report
    account = create_account(relative_finder_opt_in=True)
    pet1 = create_pet(account["id"], name="P1", relative_finder_opt_in=True)
    pet2 = create_pet(account["id"], name="P2", relative_finder_opt_in=True)
    _finalize_pet_report(account["id"], pet1["id"], breed="LABRADOR")

    match = get_success_data(
        api.create_relative_match(
            create_relative_match_payload(pet1["id"], pet2["id"], shared_cm=1250), LAB
        )
    )
    api.confirm_relative_match(match["id"], LAB)
    fetched = validate_success(api.get_relative_match(match["id"], LAB))
    assert fetched["status"] == "ESTIMATED", f"match must stay ESTIMATED, got {fetched['status']}"


# =========================================================================
# Corner: pet opt-out cascades estimated match withdrawal (state_machines)
# =========================================================================

def test_pet_optout_withdraws_estimated_match(api):
    """PRD §3.1: "Turning the per-pet switch off has a consequence: every
    `ESTIMATED` relative match that references that pet is automatically
    withdrawn, moving each such match from `ESTIMATED` to `WITHDRAWN` and
    incrementing its `version`."

    Design: Corner/state_machines/pet_optout_cascades_estimated_match_withdrawal
    """
    base = setup_estimated_match_two_pets(shared_cm=625)
    acct_h = make_account_headers(base["account"]["id"])

    pet = validate_success(
        api.update_pet(base["pet1"]["id"], {"relative_finder_opt_in": False}, acct_h)
    )
    assert pet["relative_finder_opt_in"] is False

    match = validate_success(api.get_relative_match(base["match"]["id"], LAB))
    assert match["status"] == "WITHDRAWN", \
        f"match must cascade to WITHDRAWN, got {match['status']}"


# =========================================================================
# Corner: confirm already-confirmed match rejected (state_machines)
# =========================================================================

def test_confirm_already_confirmed_match_rejected(api):
    """PRD §3.6: "Confirming a match is a lab operator's act that moves it from
    `ESTIMATED` to `CONFIRMED` and recomputes `relationship_pct` under the
    confirmed variant. Confirmation is permitted only when the match is
    `ESTIMATED`"
    PRD §2.8: "fifth, that the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/confirm_already_confirmed_match_returns_invalid_state
    """
    base = setup_two_pets_both_finalized(shared_cm=1250)
    first = validate_success(api.confirm_relative_match(base["match"]["id"], LAB))
    assert first["relationship_pct"] == 49.00, \
        f"confirmed 1250*0.98/2500*100 must be 49.00, got {first['relationship_pct']}"

    resp = api.confirm_relative_match(base["match"]["id"], LAB)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    again = validate_success(api.get_relative_match(base["match"]["id"], LAB))
    assert again["relationship_pct"] == 49.00, \
        f"relationship_pct must be unchanged at 49.00, got {again['relationship_pct']}"


# =========================================================================
# Corner: relative-finder opt-in required (validations)
# =========================================================================

def test_create_match_with_opted_out_pet_rejected(api):
    """PRD §3.6: "Both pets must satisfy the two-level relative-finder opt-in
    described in §3.1, or the create is rejected with
    `ERR_RELATIVE_FINDER_NOT_OPTED_IN`."

    Design: Corner/validations/confirm_relative_finder_not_opted_in_returns_error
    """
    account = create_account(relative_finder_opt_in=True)
    pet1 = create_pet(account["id"], name="P1", relative_finder_opt_in=True)
    pet2 = create_pet(account["id"], name="P2", relative_finder_opt_in=False)

    resp = api.create_relative_match(
        create_relative_match_payload(pet1["id"], pet2["id"], shared_cm=625), LAB
    )
    validate_error(resp, ApiErrorId.ERR_RELATIVE_FINDER_NOT_OPTED_IN.value)

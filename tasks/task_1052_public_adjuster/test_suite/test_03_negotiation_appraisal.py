"""Negotiation cycle and the appraisal/umpire branching state machine."""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    name_appraisers_payload, create_appraisal_payload,
    make_public_adjuster_headers,
)
from test_helpers.fixtures import (
    setup_filed_claim, setup_offer_received_claim, setup_claim_in_appraisal,
    setup_appraisers_named,
)

FIRM = TEST_USERS["firm_principal_headers"]
CARRIER = TEST_USERS["carrier_headers"]


# ------------------------------------------------- negotiation cycle (difficulty)
def test_negotiation_cycle_returns_to_offer_received_round_three(api):
    """PRD §3.4: "From `NEGOTIATING` the carrier may record a fresh offer, returning the
    claim to `OFFER_RECEIVED` and incrementing the round once more; the pair
    `OFFER_RECEIVED` and `NEGOTIATING` may cycle across as many rounds as the parties need."

    Design: Difficulty/non_linear_state_machine/claim_offer_counter_offer_negotiation_cycle
    """
    ctx = setup_filed_claim(api)
    pa = make_public_adjuster_headers(ctx["adj"])
    validate_success(api.record_offer(ctx["clm"], {"offer_cents": 5_000_000}, CARRIER))
    validate_success(api.counter_claim(ctx["clm"], {"counter_cents": 6_000_000}, pa))
    data = validate_success(api.record_offer(ctx["clm"], {"offer_cents": 5_500_000}, CARRIER))
    assert data["status"] == "OFFER_RECEIVED"
    assert data["negotiation_round"] == 3
    assert data["carrier_offer_cents"] == 5_500_000
    assert data["pa_counter_cents"] == 6_000_000


def test_negotiation_round_increments_per_exchange(api):
    """PRD §3.4: "The carrier records a settlement offer by supplying `offer_cents`; this
    drives the claim to `OFFER_RECEIVED`, stores the amount in `carrier_offer_cents`, and
    increments `negotiation_round` by one."
    PRD §3.4: "From `OFFER_RECEIVED` the public adjuster may counter by supplying
    `counter_cents`, which drives the claim to `NEGOTIATING`, stores the amount in
    `pa_counter_cents`, and again increments `negotiation_round`."

    Design: Difficulty/non_linear_state_machine/claim_offer_counter_offer_negotiation_cycle
    """
    ctx = setup_filed_claim(api)
    pa = make_public_adjuster_headers(ctx["adj"])
    after_offer = validate_success(api.record_offer(ctx["clm"], {"offer_cents": 5_000_000}, CARRIER))
    assert after_offer["status"] == "OFFER_RECEIVED"
    assert after_offer["negotiation_round"] == 1
    after_counter = validate_success(api.counter_claim(ctx["clm"], {"counter_cents": 6_000_000}, pa))
    assert after_counter["status"] == "NEGOTIATING"
    assert after_counter["negotiation_round"] == 2


# --------------------------------------------- appraisal umpire branch (difficulty)
def test_appraisal_disagree_umpire_branch_to_award(api):
    """PRD §3.5: "From there the award is rendered with a supplied `award_cents`, which must
    lie within the inclusive range bounded by the smaller and the larger of the two
    appraiser valuations; an award below the minimum or above the maximum of
    `pa_appraiser_amount_cents` and `carrier_appraiser_amount_cents` is rejected with
    `ERR_AWARD_OUT_OF_RANGE`. A valid umpire-branch render drives the appraisal to
    `AWARDED`, records the supplied `award_cents`, and cascades the parent claim from
    `IN_APPRAISAL` to `SETTLED`."

    Design: Difficulty/non_linear_state_machine/appraisal_disagree_umpire_branch_to_award
    """
    ctx = setup_appraisers_named(api, pa_amount=8_000_000, carrier_amount=6_000_000)
    pa = make_public_adjuster_headers(ctx["adj"])
    validate_success(api.select_umpire(ctx["app"], {"umpire_name": "Uma"}, pa))
    app = validate_success(api.render_award(ctx["app"], {"award_cents": 7_000_000}, pa))
    assert app["status"] == "AWARDED"
    assert app["award_cents"] == 7_000_000
    assert app["umpire_name"] == "Uma"
    claim = get_success_data(api.get_claim(ctx["clm"], FIRM))
    assert claim["status"] == "SETTLED"
    assert claim["settlement_amount_cents"] == 7_000_000


def test_appraisal_select_umpire_moves_to_umpire_selected(api):
    """PRD §3.5: "selection is rejected with `ERR_UMPIRE_NOT_NEEDED` if the two appraiser
    amounts are in fact equal, and with `ERR_APPRAISER_CONFLICT` if the proposed
    `umpire_name` duplicates either appraiser's name. Selecting an umpire moves the
    appraisal to `UMPIRE_SELECTED`."

    Design: Difficulty/non_linear_state_machine/appraisal_disagree_umpire_branch_to_award
    """
    ctx = setup_appraisers_named(api, pa_amount=8_000_000, carrier_amount=6_000_000)
    pa = make_public_adjuster_headers(ctx["adj"])
    app = validate_success(api.select_umpire(ctx["app"], {"umpire_name": "Uma"}, pa))
    assert app["status"] == "UMPIRE_SELECTED"
    assert app["umpire_name"] == "Uma"


# --------------------------------------------- appraisal agree branch (corner)
def test_appraisal_agree_branch_awards_without_umpire(api):
    """PRD §3.5: "When the two amounts are equal, the award may be rendered directly:
    rendering drives the appraisal to the terminal `AWARDED`, sets `award_cents` equal to
    `pa_appraiser_amount_cents`, and cascades the parent claim from `IN_APPRAISAL` to
    `SETTLED` with no umpire involved."

    Design: Corner/state_machines/appraisal_agree_branch_awards_without_umpire
    """
    ctx = setup_appraisers_named(api, pa_amount=7_000_000, carrier_amount=7_000_000)
    pa = make_public_adjuster_headers(ctx["adj"])
    app = validate_success(api.render_award(ctx["app"], {}, pa))
    assert app["status"] == "AWARDED"
    assert app["award_cents"] == 7_000_000
    claim = get_success_data(api.get_claim(ctx["clm"], FIRM))
    assert claim["status"] == "SETTLED"
    assert claim["settlement_amount_cents"] == 7_000_000


# -------------------------------------------------- appraiser conflict (corner)
def test_name_appraisers_same_name_rejected(api):
    """PRD §3.5: "The two appraisers must be distinct people: if `pa_appraiser_name` equals
    `carrier_appraiser_name`, the request is rejected with `ERR_APPRAISER_CONFLICT`."

    Design: Corner/validations/appraiser_conflict_same_name_rejected
    """
    ctx = setup_claim_in_appraisal(api)
    pa = make_public_adjuster_headers(ctx["adj"])
    resp = api.name_appraisers(
        ctx["app"],
        name_appraisers_payload(pa_appraiser_name="Sam", pa_appraiser_amount_cents=8_000_000,
                                carrier_appraiser_name="Sam", carrier_appraiser_amount_cents=6_000_000),
        pa,
    )
    validate_error(resp, ApiErrorId.ERR_APPRAISER_CONFLICT.value)


# ------------------------------------------------ umpire not needed (corner)
def test_select_umpire_when_amounts_equal_rejected(api):
    """PRD §3.5: "selection is rejected with `ERR_UMPIRE_NOT_NEEDED` if the two appraiser
    amounts are in fact equal, and with `ERR_APPRAISER_CONFLICT` if the proposed
    `umpire_name` duplicates either appraiser's name."

    Design: Corner/validations/umpire_selection_when_amounts_equal_rejected
    """
    ctx = setup_appraisers_named(api, pa_amount=7_000_000, carrier_amount=7_000_000)
    pa = make_public_adjuster_headers(ctx["adj"])
    resp = api.select_umpire(ctx["app"], {"umpire_name": "Uma"}, pa)
    validate_error(resp, ApiErrorId.ERR_UMPIRE_NOT_NEEDED.value)


# ------------------------------------------------ award out of range (corner)
def test_umpire_award_above_max_rejected(api):
    """PRD §3.5: "an award below the minimum or above the maximum of
    `pa_appraiser_amount_cents` and `carrier_appraiser_amount_cents` is rejected with
    `ERR_AWARD_OUT_OF_RANGE`."

    Design: Corner/validations/umpire_award_out_of_range_rejected
    """
    ctx = setup_appraisers_named(api, pa_amount=8_000_000, carrier_amount=6_000_000)
    pa = make_public_adjuster_headers(ctx["adj"])
    validate_success(api.select_umpire(ctx["app"], {"umpire_name": "Uma"}, pa))
    resp = api.render_award(ctx["app"], {"award_cents": 9_000_000}, pa)
    validate_error(resp, ApiErrorId.ERR_AWARD_OUT_OF_RANGE.value)

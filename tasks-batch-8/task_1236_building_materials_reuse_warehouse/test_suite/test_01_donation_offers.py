"""Donation offer pipeline: review cycle, acceptance gates, guidance valuation (PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    create_accepted_offer,
    create_category,
    create_donor,
    create_offer,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

INTAKE = TEST_USERS["intake_staff_headers"]
MANAGER = TEST_USERS["store_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / offer_review_info_cycle
# ---------------------------------------------------------------------------

class TestOfferReviewInfoCycle:
    def test_offer_review_info_cycle_state_sequence(self, api):
        """PRD §3.2: "The donor — or staff on their behalf, with donor callers
        again bound to their own `donor_id` — resubmits from `NEEDS_INFO` back to
        `UNDER_REVIEW`, optionally revising `description_text`, `estimated_quantity`,
        or `condition_grade`; this review-and-revision loop is unbounded."
        PRD §2.5: "version (integer): a system-managed counter that starts at
        creation and increments by one on every mutation, including mutations the
        server performs as cascade side effects."

        Design: Difficulty/non_linear_state_machine/offer_review_info_cycle
        """
        category = create_category(
            code="TRIM", display_name="Trim", pricing_model="PER_LINEAR_FT",
            base_rate_cents=150,
        )
        donor = create_donor(full_name="D Two", donor_type="BUSINESS")
        offer = create_offer(donor["id"], category["id"],
                             description_text="oak trim", estimated_quantity=40,
                             quantity_unit="LINEAR_FT", condition_grade="A")
        assert offer["status"] == "OFFERED"
        assert offer["version"] == 1

        offer = validate_success(api.review_offer(offer["id"], INTAKE))
        assert offer["status"] == "UNDER_REVIEW"
        offer = validate_success(api.request_info_offer(offer["id"], {"review_notes": "need photos"}, INTAKE))
        assert offer["status"] == "NEEDS_INFO"
        offer = validate_success(api.resubmit_offer(
            offer["id"], {"description_text": "oak trim, photos attached"}, INTAKE))
        assert offer["status"] == "UNDER_REVIEW"
        offer = validate_success(api.accept_offer(offer["id"], INTAKE))
        assert offer["status"] == "ACCEPTED", (
            "cycle OFFERED -> UNDER_REVIEW -> NEEDS_INFO -> UNDER_REVIEW -> ACCEPTED")
        assert offer["version"] == 5, (
            f"expected version 5 after create + 4 transitions, got {offer['version']}")

    def test_offer_review_info_cycle_guidance_valuation(self, api):
        """PRD §3.2: "On acceptance the system computes the donor's provisional
        guidance figure, `estimated_value_cents`: the category's `base_rate_cents`
        — verbatim for a `FLAT` category, otherwise multiplied by the offer's
        `estimated_quantity` — is multiplied by a condition factor of 1.00 for
        grade `A`, 0.75 for `B`, 0.50 for `C`, or 0.25 for `D`, then by a thirty
        percent thrift-value rate, and the product is rounded half-up to integer
        cents."

        Design: Difficulty/non_linear_state_machine/offer_review_info_cycle
        """
        category = create_category(
            code="TRIM", display_name="Trim", pricing_model="PER_LINEAR_FT",
            base_rate_cents=150,
        )
        donor = create_donor(full_name="D Two", donor_type="BUSINESS")
        offer = create_offer(donor["id"], category["id"],
                             description_text="oak trim", estimated_quantity=40,
                             quantity_unit="LINEAR_FT", condition_grade="A")
        offer = validate_success(api.review_offer(offer["id"], INTAKE))
        offer = validate_success(api.request_info_offer(offer["id"], {"review_notes": "need photos"}, INTAKE))
        offer = validate_success(api.resubmit_offer(
            offer["id"], {"description_text": "oak trim, photos attached"}, INTAKE))
        offer = validate_success(api.accept_offer(offer["id"], INTAKE))
        assert offer["estimated_value_cents"] == 1800, (
            f"expected round(150*40*1.00*0.30) = 1800, got {offer['estimated_value_cents']}")


# ---------------------------------------------------------------------------
# Corner: state_machines / offer_initial_state_offered
# ---------------------------------------------------------------------------

def test_offer_initial_state_offered(api):
    """PRD §3.2: "New offers stand in `OFFERED`."
    PRD §2.5: "version (integer): a system-managed counter that starts at
    creation and increments by one on every mutation, including mutations the
    server performs as cascade side effects."

    Design: Corner/state_machines/offer_initial_state_offered
    """
    category = create_category(code="INITC", display_name="Init Cat")
    donor = create_donor(full_name="D I")
    offer = validate_success(api.create_donation_offer(
        {
            "donor_id": donor["id"], "source_type": "DROPOFF",
            "category_id": category["id"], "description_text": "init",
            "estimated_quantity": 2, "quantity_unit": "UNIT",
            "condition_grade": "B", "pre_1978_flag": False,
        },
        INTAKE,
    ), expected_status=201)
    assert offer["status"] == "OFFERED"
    assert offer["version"] == 1


# ---------------------------------------------------------------------------
# Corner: state_machines / receive_offered_offer_rejected
# ---------------------------------------------------------------------------

def test_receive_offered_offer_rejected(api):
    """PRD §3.3: "Receiving demands the offer stand in `ACCEPTED`
    (`ERR_OFFER_NOT_ACCEPTED`) and then enforces provenance: a `PICKUP` offer is
    receivable only once a pickup appointment naming the offer as its
    `DONATION_OFFER` subject has reached `COMPLETED`; a `DECONSTRUCTION` offer
    only once its linked deconstruction job stands `COMPLETED`; a `DROPOFF` offer
    carries no such gate."

    Design: Corner/state_machines/receive_offered_offer_rejected
    """
    category = create_category(code="ROFF", display_name="R Off")
    donor = create_donor(full_name="D R")
    offer = create_offer(donor["id"], category["id"], description_text="x",
                         estimated_quantity=1)
    response = api.receive_offer(offer["id"], INTAKE)
    validate_error(response, ApiErrorId.ERR_OFFER_NOT_ACCEPTED)
    after = validate_success(api.get_donation_offer(offer["id"], INTAKE))
    assert after["status"] == "OFFERED", "rejected receive must not move the offer"


# ---------------------------------------------------------------------------
# Corner: validations / category_paused_blocks_offer_accept
# ---------------------------------------------------------------------------

def test_category_paused_blocks_offer_accept(api):
    """PRD §3.2: "The offer must stand in `UNDER_REVIEW`
    (`ERR_INVALID_OFFER_STATE`), its category must be `ACCEPTING`
    (`ERR_CATEGORY_NOT_ACCEPTING`), and its `condition_grade` must be `A`, `B`,
    or `C` — grade `D` material is below acceptance criteria and fails with
    `ERR_CONDITION_BELOW_ACCEPTANCE`."
    PRD §3.2: "Categories are born `ACCEPTING`, can be paused to `PAUSED` and
    resumed, and can be retired from either `ACCEPTING` or `PAUSED` to terminal
    `RETIRED`"

    Design: Corner/validations/category_paused_blocks_offer_accept
    """
    category = create_category(code="PAUCAT", display_name="Paused Cat")
    donor = create_donor(full_name="D P")
    offer = create_offer(donor["id"], category["id"], description_text="paused test")
    offer = validate_success(api.review_offer(offer["id"], INTAKE))

    validate_success(api.update_category(category["id"], {"acceptance_status": "PAUSED"}, MANAGER))
    response = api.accept_offer(offer["id"], INTAKE)
    validate_error(response, ApiErrorId.ERR_CATEGORY_NOT_ACCEPTING)

    validate_success(api.update_category(category["id"], {"acceptance_status": "ACCEPTING"}, MANAGER))
    offer = validate_success(api.accept_offer(offer["id"], INTAKE))
    assert offer["status"] == "ACCEPTED"


# ---------------------------------------------------------------------------
# Corner: validations / grade_d_offer_fails_acceptance_criteria
# ---------------------------------------------------------------------------

def test_grade_d_offer_fails_acceptance_criteria(api):
    """PRD §3.2: "The offer must stand in `UNDER_REVIEW`
    (`ERR_INVALID_OFFER_STATE`), its category must be `ACCEPTING`
    (`ERR_CATEGORY_NOT_ACCEPTING`), and its `condition_grade` must be `A`, `B`,
    or `C` — grade `D` material is below acceptance criteria and fails with
    `ERR_CONDITION_BELOW_ACCEPTANCE`."

    Design: Corner/validations/grade_d_offer_fails_acceptance_criteria
    """
    category = create_category(code="GRDCAT", display_name="Grade Cat")
    donor = create_donor(full_name="D G")
    offer = create_offer(donor["id"], category["id"], description_text="scrap",
                         condition_grade="D")
    offer = validate_success(api.review_offer(offer["id"], INTAKE))
    response = api.accept_offer(offer["id"], INTAKE)
    validate_error(response, ApiErrorId.ERR_CONDITION_BELOW_ACCEPTANCE)
    after = validate_success(api.get_donation_offer(offer["id"], INTAKE))
    assert after["status"] == "UNDER_REVIEW", "rejected accept must not move the offer"


# ---------------------------------------------------------------------------
# Corner: consistency_model / accept_immediately_visible_on_read
# ---------------------------------------------------------------------------

def test_accept_immediately_visible_on_read(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data field."
    PRD §3.2: "On acceptance the system computes the donor's provisional guidance
    figure, `estimated_value_cents`: the category's `base_rate_cents` — verbatim
    for a `FLAT` category, otherwise multiplied by the offer's `estimated_quantity`
    — is multiplied by a condition factor of 1.00 for grade `A`, 0.75 for `B`,
    0.50 for `C`, or 0.25 for `D`, then by a thirty percent thrift-value rate, and
    the product is rounded half-up to integer cents."

    Design: Corner/consistency_model/accept_immediately_visible_on_read
    """
    category = create_category(
        code="CONSCAT", display_name="Cons Cat", pricing_model="PER_LINEAR_FT",
        base_rate_cents=150,
    )
    donor = create_donor(full_name="D C")
    offer = create_offer(donor["id"], category["id"], description_text="cons",
                         estimated_quantity=40, quantity_unit="LINEAR_FT",
                         condition_grade="A")
    validate_success(api.review_offer(offer["id"], INTAKE))
    accepted = validate_success(api.accept_offer(offer["id"], INTAKE))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["estimated_value_cents"] == 1800

    read = validate_success(api.get_donation_offer(offer["id"], INTAKE))
    assert read["status"] == "ACCEPTED", "immediate read must reflect the accept"
    assert read["estimated_value_cents"] == 1800, (
        "immediate read must show the same computed guidance value (no lag)")

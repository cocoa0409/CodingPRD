"""Lifecycle transitions, terminal states and the cascades they fire."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_instant_equals
from test_helpers.constants import INITIAL_CLOCK
from test_helpers.factories import (
    brief_clarification_payload,
    brief_decision_payload,
    close_brief_payload,
)
from test_helpers.fixtures import (
    build_approved_formula,
    build_released_lot,
    compound_lot,
    create_accepted_brief,
    create_brief,
    create_formula,
    create_material,
    create_shipment,
    create_submitted_brief,
    create_verified_certificate,
    publish_forecast,
    read_brief,
    read_forecast,
    read_formula,
    read_lot,
    read_material,
    read_shipment,
    read_substantiation_record,
    revoke_certificate,
)
from test_helpers.test_users import (
    ACCOUNT_MANAGER,
    LAB_COMPOUNDER,
    REGULATORY_AFFAIRS,
    TECHNICAL_DIRECTOR,
)


def test_brief_submit_moves_draft_to_submitted(api):
    """The first submission advances the state and the version together.

    Section 3.1: "A brief in `DRAFT` goes `DRAFT → SUBMITTED`", "Either path
    increments the brief's `version` by 1", and on the clarification path
    "`clarification_round_count` is deliberately left untouched".

    Design: Corner/state_machines/brief_submit_moves_draft_to_submitted
    """
    brief = create_brief(api, brief_code="BRF-0001")

    submitted = get_success_data(
        api.submit_customer_brief(brief["id"], ACCOUNT_MANAGER), 200)

    assert submitted["status"] == "SUBMITTED"
    assert submitted["version"] == 2
    assert submitted["clarification_round_count"] == 0


def test_brief_second_submit_rejected(api):
    """SUBMITTED is not in the from-set of the submit transition.

    Section 3.1: "Submission from any other state is rejected with
    `ERR_BRIEF_STATE_INVALID`", and §2.11 step 9 reports the target resource's
    own state with HTTP 409.

    Design: Corner/state_machines/brief_second_submit_rejected
    """
    brief = create_submitted_brief(api, brief_code="BRF-0001")

    response = api.submit_customer_brief(brief["id"], ACCOUNT_MANAGER)
    validate_error(response, ApiErrorId.ERR_BRIEF_STATE_INVALID.value, 409)

    unchanged = read_brief(api, brief["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["version"] == 2


def test_new_formula_starts_in_draft(api):
    """A fresh formula is empty, uncosted and tier-inherited at iteration 1.

    Section 3.3: "A new formula lands in `DRAFT` with `component_count` at 0
    and `total_weight_pct` at 0, with every cost and claim field null ... with
    `cost_stale` false", "Its `iteration_no` is derived at creation as one more
    than the number of formulas already recorded against the same brief", and
    "when it is omitted the formula inherits the `confidentiality_tier`
    recorded on its brief".

    Design: Corner/state_machines/new_formula_starts_in_draft
    """
    brief = create_accepted_brief(api, brief_code="BRF-0001")

    formula = create_formula(api, brief["id"], name="Vanilla Cream F1")

    assert formula["status"] == "DRAFT"
    assert formula["iteration_no"] == 1
    assert formula["component_count"] == 0
    assert float(formula["total_weight_pct"]) == 0.0
    assert formula["bench_cost_per_kg_cents"] is None
    assert formula["cost_stale"] is False
    assert formula["confidentiality_tier"] == "TIER_1_STANDARD"
    assert formula["version"] == 1


def test_rejected_brief_is_terminal_for_every_trigger(api):
    """Submit, clarify and close all bounce off a REJECTED brief.

    Section 3.1 lists `REJECTED` among the states of which "the last three are
    terminal and admit no further transition", pins the rejection note, and
    §3.9 says closure "is accepted only from `ACCEPTED`; from anywhere else it
    is `ERR_BRIEF_STATE_INVALID`".

    Design: Corner/state_machines/rejected_brief_is_terminal_for_every_trigger
    """
    brief = create_submitted_brief(api, brief_code="BRF-0001")
    rejected = get_success_data(
        api.decide_customer_brief(
            brief["id"],
            brief_decision_payload("REJECTED", decision_note="profile out of scope"),
            TECHNICAL_DIRECTOR),
        200)
    version_after_rejection = rejected["version"]

    validate_error(api.submit_customer_brief(brief["id"], ACCOUNT_MANAGER),
                   ApiErrorId.ERR_BRIEF_STATE_INVALID.value, 409)
    validate_error(
        api.request_brief_clarification(
            brief["id"],
            brief_clarification_payload("please restate the target"),
            TECHNICAL_DIRECTOR),
        ApiErrorId.ERR_BRIEF_STATE_INVALID.value, 409)
    validate_error(
        api.close_customer_brief(brief["id"],
                                 close_brief_payload("LOST", "PERFORMANCE"),
                                 ACCOUNT_MANAGER),
        ApiErrorId.ERR_BRIEF_STATE_INVALID.value, 409)

    unchanged = read_brief(api, brief["id"])
    assert unchanged["status"] == "REJECTED"
    assert unchanged["decision_note"] == "profile out of scope"
    assert unchanged["outcome"] is None
    assert unchanged["version"] == version_after_rejection


def test_verify_an_already_verified_certificate_rejected(api):
    """A second verification of the same certificate is a state error.

    Section 3.2: "Verification attempted on a certificate that is already
    `VERIFIED` is rejected with `ERR_SUBSTANTIATION_STATE_INVALID`", and the
    first verification "set `verified_at` to the current logical clock and
    increment the certificate's `version` by 1".

    Design: Corner/state_machines/verify_an_already_verified_certificate_rejected
    """
    material = create_material(api, material_code="GUM-BASE")
    certificate = create_verified_certificate(
        api, material["id"], "KOSHER", issuing_body="OU Kosher",
        document_ref="K-11", valid_until="2027-06-30T00:00:00Z")

    response = api.verify_substantiation_record(certificate["id"], REGULATORY_AFFAIRS)
    validate_error(response, ApiErrorId.ERR_SUBSTANTIATION_STATE_INVALID.value, 409)

    unchanged = read_substantiation_record(api, certificate["id"])
    assert unchanged["status"] == "VERIFIED"
    assert_instant_equals(unchanged["verified_at"], INITIAL_CLOCK, "verified_at")
    assert unchanged["version"] == certificate["version"]


def test_certificate_reverification_after_revocation_restores_material_claim_status(api):
    """The REVOKED to VERIFIED path returns the material to CLEAR.

    Section 3.2: "a certificate that was revoked and has since been remediated
    goes `REVOKED → VERIFIED`, closing the certificate revision loop", and "The
    re-verification path additionally recomputes the material's `claim_status`,
    returning it to `CLEAR` when no other certificate of that material remains
    `REVOKED`", while `verified_claim_types` "lists exactly those claim types
    for which the material holds a substantiation record in status `VERIFIED`".

    Design: Corner/state_machines/certificate_reverification_after_revocation_restores_material_claim_status
    """
    material = create_material(api, material_code="GUM-BASE")
    certificate = create_verified_certificate(
        api, material["id"], "KOSHER", issuing_body="OU Kosher",
        document_ref="K-11", valid_until="2027-06-30T00:00:00Z")
    revoke_certificate(api, certificate["id"], "audit finding")

    restricted = read_material(api, material["id"])
    assert restricted["claim_status"] == "RESTRICTED"

    reverified = get_success_data(
        api.verify_substantiation_record(certificate["id"], REGULATORY_AFFAIRS), 200)

    assert reverified["status"] == "VERIFIED"
    restored = read_material(api, material["id"])
    assert restored["claim_status"] == "CLEAR"
    assert restored["verified_claim_types"] == ["KOSHER"]


def test_fourth_clarification_request_terminates_the_brief_instead_of_looping(api):
    """The fourth round rejects the brief and archives its children.

    Section 3.1: "when `clarification_round_count` already stands at 3, the
    request does not loop, it terminates the engagement.  The brief goes
    `SUBMITTED → REJECTED`, `decision_note` is set to the literal string
    `CLARIFICATION_EXHAUSTED`, the supplied text is still stored into
    `clarification_note`, and `clarification_round_count` is not incremented
    past 3", with the cascade moving formulas in `DRAFT` "to `ARCHIVED`, and
    every commercialization forecast of this brief in `ACTIVE` or `AT_RISK` ...
    to `LAPSED`".  The forecast is valued while the brief is `SUBMITTED`
    (0.20) with no approved formula (0.55): 500 x 10000 x 0.20 x 0.55 = 550000.

    Design: Corner/state_machines/fourth_clarification_request_terminates_the_brief_instead_of_looping
    """
    brief = create_submitted_brief(api, brief_code="BRF-0001")
    for note in ("round one: confirm the dairy matrix",
                 "round two: confirm the dosage",
                 "round three: confirm the cost cap"):
        get_success_data(
            api.request_brief_clarification(brief["id"],
                                            brief_clarification_payload(note),
                                            TECHNICAL_DIRECTOR), 200)
        get_success_data(api.submit_customer_brief(brief["id"], ACCOUNT_MANAGER), 200)

    formula = create_formula(api, brief["id"], name="Vanilla Cream F1")
    looped = read_brief(api, brief["id"])
    assert looped["clarification_round_count"] == 3
    assert looped["version"] == 8

    forecast = publish_forecast(api, brief["id"], looped["version"],
                                annual_volume_kg=500,
                                unit_price_cents_per_kg=10000)
    assert forecast["weighted_annual_value_cents"] == 550000

    terminated = get_success_data(
        api.request_brief_clarification(
            brief["id"], brief_clarification_payload("round four: still unclear"),
            TECHNICAL_DIRECTOR), 200)

    assert terminated["status"] == "REJECTED"
    assert terminated["decision_note"] == "CLARIFICATION_EXHAUSTED"
    assert terminated["clarification_note"] == "round four: still unclear"
    assert terminated["clarification_round_count"] == 3
    assert terminated["version"] == 9
    assert read_formula(api, formula["id"])["status"] == "ARCHIVED"

    lapsed = read_forecast(api, forecast["id"])
    assert lapsed["status"] == "LAPSED"
    assert lapsed["weighted_annual_value_cents"] == 550000


def test_close_lost_cascades_only_to_non_terminal_children(api):
    """A loss archives the draft formula and cancels the shipment, sparing the rest.

    Section 3.9: "A loss drives `ACCEPTED → CLOSED_LOST`, sets `outcome` to
    `LOST`, records the `loss_reason` and stamps `closed_at`; it moves the
    brief's forecasts in `ACTIVE` or `AT_RISK` to `LAPSED` with their computed
    values frozen at their pre-close numbers; it archives the same set of
    formulas" — those "still sitting in `DRAFT`, `COSTED`, `SUBMITTED` or
    `REWORK_REQUIRED`" — "and it cancels every shipment of the brief in
    `DRAFT`, `PACKET_ASSEMBLED` or `BLOCKED` ... returning each shipment's
    `shipped_g` to its sample lot through the gram ledger of §3.6".  The
    forecast is 500 x 10000 x 0.45 x 0.80 = 1800000.

    Design: Corner/state_machines/close_lost_cascades_only_to_non_terminal_children
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    approved = build_approved_formula(api, brief["id"], material["id"], 100.0)
    lot = build_released_lot(api, approved["id"], batch_size_g=500)
    draft = create_formula(api, brief["id"], name="Vanilla Cream F2")
    shipment = create_shipment(api, lot["id"], shipped_g=120)

    allocated = read_lot(api, lot["id"])
    assert allocated["available_g"] == 380
    forecast = publish_forecast(api, brief["id"], read_brief(api, brief["id"])["version"],
                               annual_volume_kg=500, unit_price_cents_per_kg=10000)
    assert forecast["weighted_annual_value_cents"] == 1800000

    closed = get_success_data(
        api.close_customer_brief(brief["id"], close_brief_payload("LOST", "PRICE"),
                                 ACCOUNT_MANAGER), 200)

    assert closed["status"] == "CLOSED_LOST"
    assert closed["outcome"] == "LOST"
    assert closed["loss_reason"] == "PRICE"
    assert_instant_equals(closed["closed_at"], INITIAL_CLOCK, "closed_at")

    assert read_formula(api, approved["id"])["status"] == "APPROVED"
    assert read_formula(api, draft["id"])["status"] == "ARCHIVED"
    assert read_shipment(api, shipment["id"])["status"] == "CANCELLED"

    restored = read_lot(api, lot["id"])
    assert restored["allocated_g"] == 0
    assert restored["available_g"] == 500
    assert restored["disposition_status"] == "RELEASED"

    lapsed = read_forecast(api, forecast["id"])
    assert lapsed["status"] == "LAPSED"
    assert lapsed["weighted_annual_value_cents"] == 1800000


def test_release_before_qc_pass_rejected(api):
    """The cross-dimension guard blocks release while QC is still PENDING.

    Section 3.6 lists release's three preconditions, the second being that
    "its `qc_status` must be `PASSED`, else `ERR_LOT_NOT_QC_PASSED`, which is
    the cross-dimension guard that makes QC meaningful", while a new lot "starts
    with `qc_status` at `PENDING`, `disposition_status` at `HELD`" and takes the
    minted `lot_number` shape.

    Design: Corner/state_machines/release_before_qc_pass_rejected
    """
    material = create_material(api, material_code="GUM-BASE")
    brief = create_accepted_brief(api, brief_code="BRF-0001")
    formula = build_approved_formula(api, brief["id"], material["id"], 100.0)
    lot = compound_lot(api, formula["id"], batch_size_g=500)
    assert lot["lot_number"] == "BRF-0001-I01-L001"

    response = api.release_sample_lot(lot["id"], LAB_COMPOUNDER)
    validate_error(response, ApiErrorId.ERR_LOT_NOT_QC_PASSED.value, 409)

    unchanged = read_lot(api, lot["id"])
    assert unchanged["qc_status"] == "PENDING"
    assert unchanged["disposition_status"] == "HELD"

"""Temporal windows, validation-priority conflicts, and copay-card edges
(PRD §3.3, §3.4, §2.7).

Covers Difficulty queue: resource_temporal_overlap (refill-too-soon, PA validity
window exclusive upper bound), priority_pair_validation_conflict (segregation beats
stale-version, inactive beats pa-required), boundary_precision_check (exhausted card
zero-remaining draw).
"""
from test_helpers import fixtures as fx, validate_error, ApiErrorId
from test_helpers.api_client import api_client
from test_helpers import make_director_headers


# ─── resource_temporal_overlap / refill_too_soon_supply_window_overlap ──────
def test_refill_too_soon_inside_supply_window_rejected(api):
    """PRD §3.4: "a new fill whose `fill_date` lands strictly inside an existing window is an overlap and is rejected with `ERR_REFILL_TOO_SOON`, while a new fill stamped exactly at a prior window's `supply_end_date` is adjacent (not overlapping) and is allowed."

    Design: Difficulty/resource_temporal_overlap/refill_too_soon_supply_window_overlap
    """
    fx.set_clock("2026-01-01T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="Z", drug_name="Z", tier="TIER_1",
                          ingredient_cost_cents=10000)
    m = fx.create_member(plan["id"])
    first = fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="RETAIL")
    assert first["adjudication_status"] == "PAID"

    fx.set_clock("2026-01-15T00:00:00.000Z")  # inside [2026-01-01, 2026-01-31)
    resp = api_client.create_claim(
        {"member_id": m["id"], "formulary_drug_id": drug["id"], "days_supply": 30,
         "pharmacy_type": "RETAIL"},
        fx.PROVIDER,
    )
    validate_error(resp, ApiErrorId.ERR_REFILL_TOO_SOON.value)


# ─── resource_temporal_overlap / pa_validity_window_exclusive_upper_bound ───
def test_pa_window_expired_at_exact_valid_through_date(api):
    """PRD §3.4: "the claim's `fill_date` must fall strictly before the authorization's `valid_through_date`. The window is half-open — open at the decided instant and exclusive at the upper bound — so a fill stamped exactly at `valid_through_date` is rejected with `ERR_PA_WINDOW_EXPIRED`, as is any later fill."

    Design: Difficulty/resource_temporal_overlap/pa_validity_window_exclusive_upper_bound
    """
    fx.set_clock("2026-02-01T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="PAW", drug_name="PA W", tier="TIER_2",
                          ingredient_cost_cents=30000, pa_required=True)
    m = fx.create_member(plan["id"])
    pa = fx.submit_and_approve_pa(m["id"], drug["id"], submitter_id="U_REV",
                                  decider_id="U_DIR", authorized_fills=1,
                                  valid_through_date="2026-03-01T00:00:00.000Z")
    fx.set_clock("2026-03-01T00:00:00.000Z")  # exactly the upper bound
    resp = api_client.create_claim(
        {"member_id": m["id"], "formulary_drug_id": drug["id"], "days_supply": 30,
         "pharmacy_type": "RETAIL", "prior_auth_id": pa["id"]},
        fx.PROVIDER,
    )
    validate_error(resp, ApiErrorId.ERR_PA_WINDOW_EXPIRED.value)


# ─── Corner / validations.refill_adjacent_at_supply_end_allowed ─────────────
def test_refill_adjacent_at_supply_end_allowed(api):
    """PRD §3.4: "a new fill stamped exactly at a prior window's `supply_end_date` is adjacent (not overlapping) and is allowed."

    Design: Corner/validations/refill_adjacent_at_supply_end_allowed
    """
    fx.set_clock("2026-01-01T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="Z", drug_name="Z", tier="TIER_1",
                          ingredient_cost_cents=10000)
    m = fx.create_member(plan["id"])
    fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="RETAIL")
    fx.set_clock("2026-01-31T00:00:00.000Z")  # exactly supply_end_date of the first fill
    claim = fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="RETAIL")
    assert claim["adjudication_status"] == "PAID", claim["adjudication_status"]


# ─── priority_pair / segregation_beats_stale_version_on_pa_decide ───────────
def test_segregation_of_duties_beats_stale_version(api):
    """PRD §3.3: "On the decide endpoint these checks evaluate in the §2.7 priority
    order — first the legality of the current state, then the segregation-of-duties
    check, then the version match — so that an authorization in an undecidable state
    surfaces `ERR_INVALID_STATE` before any segregation or version concern is examined,
    and a self-decision surfaces `ERR_SEGREGATION_OF_DUTIES` before the version is
    compared."
    PRD §3.3: "When the deciding user equals the submitter, the request is rejected
    with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_stale_version_on_pa_decide
    """
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="X", drug_name="X", tier="TIER_2",
                          ingredient_cost_cents=30000, pa_required=True)
    m = fx.create_member(plan["id"])
    pa = fx.submit_pa(m["id"], drug["id"], submitter_id="U_SELF", authorized_fills=1)
    # Same user U_SELF decides, with a deliberately stale version (v-1).
    resp = api_client.decide_prior_authorization(
        pa["id"],
        {"decision": "APPROVE", "expected_prior_authorization_version": pa["version"] - 1},
        make_director_headers("U_SELF"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    pa_after = fx.get_pa(pa["id"])
    assert pa_after["status"] == "PENDING_REVIEW"


# ─── priority_pair / inactive_resource_beats_pa_required_on_claim ───────────
def test_inactive_resource_beats_pa_required(api):
    """PRD §3.4: "all three referenced lifecycle resources must be live: the member must
    be `ACTIVE`, the drug must be `ACTIVE`, and the plan must be `ACTIVE`; a claim
    touching a terminated member, an inactive drug, or an archived plan is rejected with
    `ERR_INACTIVE_RESOURCE`."
    PRD §2.7: "earlier, structural problems mask later, business-specific ones."

    Design: Difficulty/priority_pair_validation_conflict/inactive_resource_beats_pa_required_on_claim
    """
    fx.set_clock("2026-08-01T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="PAX", drug_name="PA X", tier="TIER_2",
                          ingredient_cost_cents=30000, pa_required=True)
    m = fx.create_member(plan["id"])
    fx.terminate_member(m["id"])
    # No prior_auth_id -> would also violate ERR_PA_REQUIRED, but inactive member wins.
    resp = api_client.create_claim(
        {"member_id": m["id"], "formulary_drug_id": drug["id"], "days_supply": 30,
         "pharmacy_type": "RETAIL"},
        fx.PROVIDER,
    )
    validate_error(resp, ApiErrorId.ERR_INACTIVE_RESOURCE.value)


# ─── boundary_precision_check / copay_card_exhausted_zero_remaining_draw ─────
def test_exhausted_copay_card_named_again_rejected(api):
    """PRD §3.4: "if the claim carries a `copay_card_id`, that card must belong to the same member and the same drug as the claim and must be `ACTIVE`; a card that does not match the claim's member and drug, or one that is `EXHAUSTED`, is rejected with `ERR_COPAY_CARD_INVALID`."
    PRD §3.5: "when it equals the card's `max_benefit_cents` the card's `status` becomes `EXHAUSTED`."

    Design: Difficulty/boundary_precision_check/copay_card_exhausted_zero_remaining_draw
    """
    fx.set_clock("2026-10-01T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=500000)
    drug = fx.create_drug(plan["id"], ndc="SP", drug_name="Spec", tier="SPECIALTY",
                          ingredient_cost_cents=200000, is_specialty=True)
    m = fx.create_member(plan["id"])
    card = fx.create_copay_card(m["id"], drug["id"], max_benefit_cents=20000)
    first = fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="SPECIALTY",
                            copay_card_id=card["id"])
    assert first["adjudication_status"] == "PAID"
    card_mid = fx.get_copay_card(card["id"])
    assert card_mid["status"] == "EXHAUSTED"
    assert card_mid["benefit_used_cents"] == 20000

    # A second specialty fill is adjacent (same drug) — set clock past the supply window
    # so refill-too-soon does not preempt the copay-card check.
    fx.set_clock("2026-11-01T00:00:00.000Z")
    resp = api_client.create_claim(
        {"member_id": m["id"], "formulary_drug_id": drug["id"], "days_supply": 30,
         "pharmacy_type": "SPECIALTY", "copay_card_id": card["id"]},
        fx.PROVIDER,
    )
    validate_error(resp, ApiErrorId.ERR_COPAY_CARD_INVALID.value)

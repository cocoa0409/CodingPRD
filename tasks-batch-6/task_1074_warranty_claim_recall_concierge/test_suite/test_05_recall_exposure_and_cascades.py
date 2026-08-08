"""Recall exposure scoring (weighted vs count), the match fork, the publish and
resolution-complete cascades, the inclusive serial-range boundary, and the
compensating exposure invariant.
"""
from test_helpers import (
    validate_success, make_concierge_headers, make_household_owner_headers,
    setup_recall_published,
    new_manufacturer, new_household, new_owner, new_subscription, new_product,
    new_recall_notice, publish_recall, match_for_product, acknowledge_match,
    new_claim, add_document, submit_claim, review_claim, approve_claim,
    resolution_for_claim,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Difficulty: exposure WEIGHTED sum (risk domain) ──────────────────────────
def test_publish_weighted_matches_two_products(api):
    """PRD 3.4: "The notice's `matched_product_count` is then set to the number of
    matches created. Second, each matched product's `recall_status` is set to
    `RECALLED`."

    Design: Difficulty/dual_variant_calc/exposure_weighted_vs_count_risk_domain
    """
    ctx = setup_recall_published(exposure_scoring_mode="WEIGHTED", severity="CRITICAL",
                                 serials=(100, 101), serial_range_start=100,
                                 serial_range_end=200, model_number="TV-9",
                                 remedy_type="REPLACE")
    rn = validate_success(api.get_recall_notice(ctx["rn"]["id"], ADMIN), 200)
    assert rn["matched_product_count"] == 2
    p1 = validate_success(api.get_product(ctx["products"][0]["id"], ADMIN), 200)
    assert p1["recall_status"] == "RECALLED"


def test_publish_weighted_exposure_sums_severity(api):
    """PRD 3.1: "Under the `WEIGHTED` mode, the score is the sum of the
    `severity_weight` of those open matches, where a `LOW` recall weighs 1, a `HIGH`
    recall weighs 3, and a `CRITICAL` recall weighs 5."

    Design: Difficulty/dual_variant_calc/exposure_weighted_vs_count_risk_domain
    """
    ctx = setup_recall_published(exposure_scoring_mode="WEIGHTED", severity="CRITICAL",
                                 serials=(100, 101), serial_range_start=100,
                                 serial_range_end=200, model_number="TV-9",
                                 remedy_type="REPLACE")
    hh = validate_success(api.get_household(ctx["hh"]["id"], ADMIN), 200)
    assert hh["recall_exposure_score"] == 10


# ─── Difficulty: recall-match fork with divergent side effects ────────────────
def test_match_fork_acknowledge_and_dismiss_statuses(api):
    """PRD 3.5: "The first fork branch is dismissal. Only the `HouseholdOwner` may
    dismiss a match, moving it from `MATCHED` to the terminal `DISMISSED` state."

    Design: Difficulty/non_linear_state_machine/recall_match_fork_divergent_side_effects
    """
    ctx = setup_recall_published(exposure_scoring_mode="WEIGHTED", severity="HIGH",
                                 serials=(10, 11), serial_range_start=1,
                                 serial_range_end=100, model_number="AB-2",
                                 remedy_type="REPAIR")
    owner = ctx["owner"]
    m1 = match_for_product(ctx["products"][0]["id"])
    m2 = match_for_product(ctx["products"][1]["id"])
    ack = validate_success(api.acknowledge_recall_match(m1["id"], make_household_owner_headers(owner["id"])), 200)
    dis = validate_success(api.dismiss_recall_match(m2["id"], make_household_owner_headers(owner["id"])), 200)
    assert ack["status"] == "ACKNOWLEDGED"
    assert dis["status"] == "DISMISSED"


def test_match_fork_dismiss_lowers_exposure_acknowledge_does_not(api):
    """PRD 3.5: "Acknowledging does **not** change the household's
    `recall_exposure_score`, because an `ACKNOWLEDGED` match is still part of the open
    set that feeds the score."
    PRD 3.5: "Dismissal removes the match from the open set, so it carries a side effect
    the acknowledge path does not: the household's `recall_exposure_score` is
    recomputed, dropping this match's contribution."

    Design: Difficulty/non_linear_state_machine/recall_match_fork_divergent_side_effects
    """
    ctx = setup_recall_published(exposure_scoring_mode="WEIGHTED", severity="HIGH",
                                 serials=(10, 11), serial_range_start=1,
                                 serial_range_end=100, model_number="AB-2",
                                 remedy_type="REPAIR")
    owner = ctx["owner"]
    m1 = match_for_product(ctx["products"][0]["id"])
    m2 = match_for_product(ctx["products"][1]["id"])
    acknowledge_match(m1["id"], owner["id"])
    api.dismiss_recall_match(m2["id"], make_household_owner_headers(owner["id"]))
    hh = validate_success(api.get_household(ctx["hh"]["id"], ADMIN), 200)
    assert hh["recall_exposure_score"] == 3


# ─── Difficulty: publish cascade depth 3 ──────────────────────────────────────
def test_publish_cascade_creates_matched_match(api):
    """PRD 3.4: "the system creates a `RecallMatch` with `status` of `MATCHED` and a
    `severity_weight` snapshotting the recall's severity — 1 for `LOW`, 3 for `HIGH`, 5
    for `CRITICAL`."

    Design: Difficulty/transitive_cascade/publish_recall_cascade_depth3
    """
    ctx = setup_recall_published(exposure_scoring_mode="WEIGHTED", severity="CRITICAL",
                                 serials=(50,), serial_range_start=1, serial_range_end=100,
                                 model_number="GR-1", remedy_type="REPLACE")
    m = match_for_product(ctx["products"][0]["id"])
    assert m["status"] == "MATCHED"
    assert m["severity_weight"] == 5


def test_publish_cascade_flips_product_and_household(api):
    """PRD 3.4: "Second, each matched product's `recall_status` is set to `RECALLED`.
    Third, each affected household's `recall_exposure_score` is recomputed over its
    open matches as described in Section 3.1."

    Design: Difficulty/transitive_cascade/publish_recall_cascade_depth3
    """
    ctx = setup_recall_published(exposure_scoring_mode="WEIGHTED", severity="CRITICAL",
                                 serials=(50,), serial_range_start=1, serial_range_end=100,
                                 model_number="GR-1", remedy_type="REPLACE")
    prod = validate_success(api.get_product(ctx["products"][0]["id"], ADMIN), 200)
    hh = validate_success(api.get_household(ctx["hh"]["id"], ADMIN), 200)
    assert prod["recall_status"] == "RECALLED"
    assert hh["recall_exposure_score"] == 5


# ─── Difficulty: resolution-complete cascade depth 3 ──────────────────────────
def _recall_refund_dispatched(api):
    """RECALL REFUND claim taken all the way to a DISPATCHED resolution.
    Returns dict(hh, prod, m, claim, res)."""
    mfr = new_manufacturer()
    hh = new_household(exposure_scoring_mode="WEIGHTED")
    owner = new_owner(hh["id"])
    new_subscription(hh["id"], owner["id"], tier="BASIC")
    prod = new_product(hh["id"], owner["id"], mfr["id"], model_number="HT-4",
                       serial_number=7, purchase_price_cents=40000, warranty_months=24)
    rn = new_recall_notice(mfr["id"], affected_model_number="HT-4", serial_range_start=1,
                           serial_range_end=50, severity="CRITICAL", remedy_type="REFUND",
                           effective_from="2025-06-01T00:00:00Z",
                           effective_to="2026-12-01T00:00:00Z")
    publish_recall(rn["id"], mfr["id"])
    m = match_for_product(prod["id"])
    acknowledge_match(m["id"], owner["id"])
    claim = new_claim(prod["id"], owner["id"], claim_type="RECALL",
                      resolution_preference="REFUND", recall_match_id=m["id"],
                      issue_description="fire hazard")
    add_document(claim["id"], owner["id"], doc_type="SERIAL_PROOF")
    submit_claim(claim["id"], owner["id"])
    review_claim(claim["id"], "cx-reviewer")
    approve_claim(claim["id"], "cx-approver")
    res = resolution_for_claim(claim["id"])
    validate_success(api.dispatch_resolution(res["id"], {}, make_concierge_headers("cx-approver")), 200)
    return {"hh": hh, "prod": prod, "m": m, "claim": claim, "res": res}


def test_complete_cascade_resolves_claim_and_remedies_match(api):
    """PRD 3.8: "This sets the linked claim's `status` to `RESOLVED` and mirrors the
    resolution's `settlement_total_cents` onto the claim's own `settlement_total_cents`.
    If the claim is a `RECALL` claim, completion cascades further: the linked
    `RecallMatch` is set to `REMEDIED`, that match's product has its `recall_status` set
    to `REMEDIED`, and the household's `recall_exposure_score` is recomputed to drop the
    now-closed match."

    Design: Difficulty/transitive_cascade/resolution_complete_cascade_depth3
    """
    ctx = _recall_refund_dispatched(api)
    validate_success(api.complete_resolution(ctx["res"]["id"], make_concierge_headers("cx-approver")), 200)
    claim = validate_success(api.get_claim(ctx["claim"]["id"], ADMIN), 200)
    match = validate_success(api.get_recall_match(ctx["m"]["id"], ADMIN), 200)
    assert claim["status"] == "RESOLVED"
    assert match["status"] == "REMEDIED"


def test_complete_cascade_remedies_product_and_zeroes_exposure(api):
    """PRD 3.8: "that match's product has its `recall_status` set to `REMEDIED`, and the
    household's `recall_exposure_score` is recomputed to drop the now-closed match."

    Design: Difficulty/transitive_cascade/resolution_complete_cascade_depth3
    """
    ctx = _recall_refund_dispatched(api)
    validate_success(api.complete_resolution(ctx["res"]["id"], make_concierge_headers("cx-approver")), 200)
    prod = validate_success(api.get_product(ctx["prod"]["id"], ADMIN), 200)
    hh = validate_success(api.get_household(ctx["hh"]["id"], ADMIN), 200)
    assert prod["recall_status"] == "REMEDIED"
    assert hh["recall_exposure_score"] == 0


# ─── Difficulty: inclusive serial-range boundary on publish ───────────────────
def test_serial_range_boundary_matches_only_endpoint(api):
    """PRD 3.4: "whose `serial_number` falls within the inclusive serial range (at least
    `serial_range_start` and at most `serial_range_end`), the system creates a
    `RecallMatch`."

    Design: Difficulty/boundary_precision_check/recall_serial_range_inclusive_boundary_on_publish
    """
    ctx = setup_recall_published(exposure_scoring_mode="WEIGHTED", severity="HIGH",
                                 serials=(2000, 2001), serial_range_start=1000,
                                 serial_range_end=2000, model_number="SR-5",
                                 remedy_type="REPAIR")
    rn = validate_success(api.get_recall_notice(ctx["rn"]["id"], ADMIN), 200)
    p_in = validate_success(api.get_product(ctx["products"][0]["id"], ADMIN), 200)
    p_out = validate_success(api.get_product(ctx["products"][1]["id"], ADMIN), 200)
    assert rn["matched_product_count"] == 1
    assert p_in["recall_status"] == "RECALLED"
    assert p_out["recall_status"] == "NONE"


def test_serial_range_boundary_exposure_counts_one_match(api):
    """PRD 3.1: "Under the `WEIGHTED` mode, the score is the sum of the `severity_weight`
    of those open matches, where a `LOW` recall weighs 1, a `HIGH` recall weighs 3, and
    a `CRITICAL` recall weighs 5."

    Design: Difficulty/boundary_precision_check/recall_serial_range_inclusive_boundary_on_publish
    """
    ctx = setup_recall_published(exposure_scoring_mode="WEIGHTED", severity="HIGH",
                                 serials=(2000, 2001), serial_range_start=1000,
                                 serial_range_end=2000, model_number="SR-5",
                                 remedy_type="REPAIR")
    hh = validate_success(api.get_household(ctx["hh"]["id"], ADMIN), 200)
    assert hh["recall_exposure_score"] == 3


# ─── Difficulty: compensating exposure invariant (publish then remedy) ────────
def test_remedy_closes_match_and_product(api):
    """PRD 3.5: "A `ManufacturerAgent` or a `ConciergeAgent` may remedy a match that is
    `ACKNOWLEDGED`, moving it to `REMEDIED`. Remedying carries two side effects beyond
    the status change: the matched product's `recall_status` is set to `REMEDIED`, and
    the household's `recall_exposure_score` is recomputed."

    Design: Difficulty/compensating_invariant/exposure_score_conserved_by_publish_then_remedy
    """
    ctx = setup_recall_published(exposure_scoring_mode="WEIGHTED", severity="CRITICAL",
                                 serials=(9,), serial_range_start=1, serial_range_end=100,
                                 model_number="RK-9", remedy_type="REPLACE")
    owner = ctx["owner"]
    m = match_for_product(ctx["products"][0]["id"])
    acknowledge_match(m["id"], owner["id"])
    validate_success(api.remedy_recall_match(m["id"], make_concierge_headers("cx-remedy")), 200)
    match = validate_success(api.get_recall_match(m["id"], ADMIN), 200)
    prod = validate_success(api.get_product(ctx["products"][0]["id"], ADMIN), 200)
    assert match["status"] == "REMEDIED"
    assert prod["recall_status"] == "REMEDIED"


def test_remedy_restores_exposure_to_zero(api):
    """PRD 3.5: "the household's `recall_exposure_score` is recomputed — a compensating
    adjustment that removes the severity weight this match added when it was created."

    Design: Difficulty/compensating_invariant/exposure_score_conserved_by_publish_then_remedy
    """
    ctx = setup_recall_published(exposure_scoring_mode="WEIGHTED", severity="CRITICAL",
                                 serials=(9,), serial_range_start=1, serial_range_end=100,
                                 model_number="RK-9", remedy_type="REPLACE")
    owner = ctx["owner"]
    m = match_for_product(ctx["products"][0]["id"])
    acknowledge_match(m["id"], owner["id"])
    api.remedy_recall_match(m["id"], make_concierge_headers("cx-remedy"))
    hh = validate_success(api.get_household(ctx["hh"]["id"], ADMIN), 200)
    assert hh["recall_exposure_score"] == 0


# ─── Corner: exposure COUNT variant ───────────────────────────────────────────
def test_exposure_count_mode_variant_selection(api):
    """PRD 3.1: "Under the `COUNT` mode, the score is simply the number of open matches,
    ignoring severity entirely."

    Design: Corner/calculations/exposure_count_mode_variant_selection
    """
    ctx = setup_recall_published(exposure_scoring_mode="COUNT", severity="CRITICAL",
                                 serials=(100, 101), serial_range_start=1,
                                 serial_range_end=200, model_number="CT-9",
                                 remedy_type="REPLACE")
    hh = validate_success(api.get_household(ctx["hh"]["id"], ADMIN), 200)
    assert hh["recall_exposure_score"] == 2

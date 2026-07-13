"""Citation issuance, overweight fine calculation, the contest fork, and fiscal guards.

Difficulty translations: assessed-vs-final overweight fine divergence, gross-vs-axle max
selection, the issuance registration-hold cascade, the contest branch fork, the
unpaid-fines issue/dismiss invariant, and safety-beats-fiscal precedence. Corner
translations: fine cap, settlement success and mismatch, carrier mismatch, overweight
basis missing, and contest-from-terminal.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    api_client,
    setup_domain,
    setup_referred_overweight_screening,
    setup_inspection_finalized_oos,
    setup_overweight_citation_assessed,
    setup_overweight_citation_contested,
    create_carrier,
    create_screening,
    create_inspection,
    add_violation,
    finalize,
    issue_citation,
    contest_citation,
    adjudicate_citation,
    make_carrier_rep_headers,
    make_officer_headers,
)

ADMIN = TEST_USERS["compliance_admin_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
OFFICER_1 = make_officer_headers("officer-1")


def _get_carrier(carrier_id):
    return validate_success(api_client.get_carrier(carrier_id, ADMIN))


# --- Difficulty: assessed-vs-final overweight fine divergence ---

def test_overweight_assessed_fine_from_wim_weights(api):
    """PRD §3.7: "For an `OVERWEIGHT` citation, the fine is computed from the screening's
    weigh-in-motion weights by a marginal, bracketed schedule. First determine two
    excess amounts: the gross excess is the screening's `gross_weight_lbs` minus the
    station's `gross_weight_limit_lbs`, floored at zero, and the axle excess is the
    screening's `heaviest_axle_lbs` minus the station's `single_axle_limit_lbs`, floored
    at zero. Convert an excess amount to cents by charging its first 2000 pounds at 10
    cents per pound, the next 3000 pounds (that is, pounds 2001 through 5000) at 25 cents
    per pound, and every pound beyond 5000 at 50 cents per pound. Compute this bracketed
    charge separately for the gross excess and for the axle excess, and the
    `assessed_fine_cents` is the greater of the two."

    Design: Difficulty/dual_variant_calc/overweight_fine_provisional_vs_final_diverges
    """
    d = setup_overweight_citation_assessed(
        carrier_overrides={"usdot_number": "DOT-844-A", "legal_name": "Acme Freight"},
        station_overrides={"name": "I-5 Northbound", "state_code": "CA"})
    # gross excess 6000 -> 145000; axle excess 1000 -> 10000; max = 145000.
    assert d["citation"]["assessed_fine_cents"] == 145000


def test_overweight_final_fine_from_certified_weights_diverges(api):
    """PRD §3.8: "On `UPHOLD`, the officer records the certified static-scale weights
    `certified_gross_lbs` and `certified_axle_lbs`, and the `final_fine_cents` is
    recomputed: for an `OVERWEIGHT` citation it is the same bracketed overweight schedule
    of §3.7 applied to the certified weights (which, being from a static certified scale,
    are typically lower than the WIM weights and yield a smaller fine), and for any other
    kind it equals the already-assessed `assessed_fine_cents`. The carrier's
    `unpaid_fines_cents` is then reconciled by adding the difference between the new
    `final_fine_cents` and the original `assessed_fine_cents` (a negative difference
    lowers the balance), and the citation moves `CONTESTED → UPHELD`."

    Design: Difficulty/dual_variant_calc/overweight_fine_provisional_vs_final_diverges
    """
    d = setup_overweight_citation_contested(
        carrier_overrides={"usdot_number": "DOT-844-A2", "legal_name": "Acme Freight"},
        station_overrides={"name": "I-5 Northbound", "state_code": "CA"})
    upheld = adjudicate_citation(d["citation"]["id"], "UPHOLD", officer_id="officer-2",
                                 certified_gross_lbs=83000, certified_axle_lbs=21000)
    # certified gross excess 3000 -> 45000; axle excess 1000 -> 10000; max = 45000.
    assert upheld["assessed_fine_cents"] == 145000
    assert upheld["final_fine_cents"] == 45000
    assert upheld["assessed_fine_cents"] != upheld["final_fine_cents"]
    assert _get_carrier(d["carrier"]["id"])["unpaid_fines_cents"] == 45000


# --- Difficulty: gross-vs-axle max selection ---

def test_overweight_fine_axle_branch_dominates(api):
    """PRD §3.7: "Compute this bracketed charge separately for the gross excess and for
    the axle excess, and the `assessed_fine_cents` is the greater of the two."

    Design: Difficulty/combinatorial_formula/overweight_fine_gross_vs_axle_max_selection
    """
    d = setup_overweight_citation_assessed(
        carrier_overrides={"usdot_number": "DOT-844-C", "legal_name": "Cargo Co"},
        station_overrides={"name": "SR-99", "state_code": "CA"},
        screening_overrides={"gross_weight_lbs": 81000, "heaviest_axle_lbs": 26000})
    # gross excess 1000 -> 10000; axle excess 6000 -> 145000; max = 145000.
    assert d["citation"]["assessed_fine_cents"] == 145000


def test_overweight_fine_is_max_not_gross_branch(api):
    """PRD §3.7: "Compute this bracketed charge separately for the gross excess and for
    the axle excess, and the `assessed_fine_cents` is the greater of the two."

    Design: Difficulty/combinatorial_formula/overweight_fine_gross_vs_axle_max_selection
    """
    d = setup_overweight_citation_assessed(
        carrier_overrides={"usdot_number": "DOT-844-C2", "legal_name": "Cargo Co"},
        station_overrides={"name": "SR-99", "state_code": "CA"},
        screening_overrides={"gross_weight_lbs": 81000, "heaviest_axle_lbs": 26000})
    # The selected fine is the axle branch (145000), strictly greater than the gross
    # branch (tiered(1000) = 10000) — proving max(), not the gross branch alone.
    assert d["citation"]["assessed_fine_cents"] == 145000
    assert d["citation"]["assessed_fine_cents"] > 10000


# --- Difficulty: issuance registration-hold cascade ---

def test_issue_citation_debits_carrier_unpaid_fines(api):
    """PRD §2.7: "Issuing a citation adds its `assessed_fine_cents` to this balance;
    settling, dismissing, or reconciling a citation reduces or adjusts it as described in
    §3.7 and §3.8."

    Design: Difficulty/transitive_cascade/citation_issue_cascade_to_registration_hold
    """
    d = setup_overweight_citation_assessed(
        carrier_overrides={"usdot_number": "DOT-844-H", "legal_name": "Hotel Haulage"},
        station_overrides={"name": "I-40", "state_code": "CA"})
    assert _get_carrier(d["carrier"]["id"])["unpaid_fines_cents"] == 145000


def test_issue_citation_sets_registration_hold(api):
    """PRD §3.7: "On success the citation is created in `status` `ASSESSED`, its
    `issued_by_user_id` is set to the issuing officer's `X-User-ID`, its
    `final_fine_cents`, `certified_gross_lbs`, `certified_axle_lbs` all start at zero and
    its `adjudicated_by_user_id` and `contest_reason` empty, and the carrier's
    `unpaid_fines_cents` is increased by the `assessed_fine_cents`. If that increase
    crosses `100000` cents upward, the carrier's `registration_hold` becomes true."

    Design: Difficulty/transitive_cascade/citation_issue_cascade_to_registration_hold
    """
    d = setup_overweight_citation_assessed(
        carrier_overrides={"usdot_number": "DOT-844-H2", "legal_name": "Hotel Haulage"},
        station_overrides={"name": "I-40", "state_code": "CA"})
    assert _get_carrier(d["carrier"]["id"])["registration_hold"] is True


# --- Difficulty: contest branch fork ---

def test_contest_then_dismiss_zeroes_final_fine(api):
    """PRD §3.8: "On `DISMISS`, the `final_fine_cents` is set to zero, the carrier's
    `unpaid_fines_cents` is reduced by the original `assessed_fine_cents` as
    compensation, and the citation moves `CONTESTED → DISMISSED`. `DISMISSED` is
    terminal."

    Design: Difficulty/non_linear_state_machine/citation_contest_branch_fork
    """
    d = setup_overweight_citation_contested(
        carrier_overrides={"usdot_number": "DOT-844-F", "legal_name": "Foxtrot Cartage"},
        station_overrides={"name": "US-50", "state_code": "CA"})
    dismissed = adjudicate_citation(d["citation"]["id"], "DISMISS", officer_id="officer-2")
    assert dismissed["status"] == "DISMISSED"
    assert dismissed["final_fine_cents"] == 0
    assert _get_carrier(d["carrier"]["id"])["unpaid_fines_cents"] == 0


def test_contest_then_uphold_reconciles_to_upheld(api):
    """PRD §3.8: "The carrier's `unpaid_fines_cents` is then reconciled by adding the
    difference between the new `final_fine_cents` and the original `assessed_fine_cents`
    (a negative difference lowers the balance), and the citation moves
    `CONTESTED → UPHELD`."

    Design: Difficulty/non_linear_state_machine/citation_contest_branch_fork
    """
    d = setup_overweight_citation_contested(
        carrier_overrides={"usdot_number": "DOT-844-F2", "legal_name": "Foxtrot Cartage"},
        station_overrides={"name": "US-50", "state_code": "CA"})
    upheld = adjudicate_citation(d["citation"]["id"], "UPHOLD", officer_id="officer-2",
                                 certified_gross_lbs=83000, certified_axle_lbs=21000)
    assert upheld["status"] == "UPHELD"
    assert upheld["final_fine_cents"] == 45000


# --- Difficulty: unpaid-fines issue/dismiss invariant ---

def test_issue_then_dismiss_restores_unpaid_to_zero(api):
    """PRD §3.8: "On `DISMISS`, the `final_fine_cents` is set to zero, the carrier's
    `unpaid_fines_cents` is reduced by the original `assessed_fine_cents` as
    compensation, and the citation moves `CONTESTED → DISMISSED`. `DISMISSED` is
    terminal."

    Design: Difficulty/compensating_invariant/carrier_unpaid_fines_issue_dismiss
    """
    d = setup_overweight_citation_contested(
        carrier_overrides={"usdot_number": "DOT-844-R", "legal_name": "Romeo Rigs"},
        station_overrides={"name": "I-20", "state_code": "GA"})
    assert d["citation"]["assessed_fine_cents"] == 145000
    adjudicate_citation(d["citation"]["id"], "DISMISS", officer_id="officer-2")
    assert _get_carrier(d["carrier"]["id"])["unpaid_fines_cents"] == 0


def test_unpaid_balance_conserved_across_issue_and_dismiss(api):
    """PRD §2.7: "A carrier's `unpaid_fines_cents` is the running total of
    assessed-but-unsettled citation fines, in integer cents. Issuing a citation adds its
    `assessed_fine_cents` to this balance; settling, dismissing, or reconciling a
    citation reduces or adjusts it as described in §3.7 and §3.8."

    Design: Difficulty/compensating_invariant/carrier_unpaid_fines_issue_dismiss
    """
    d = setup_overweight_citation_assessed(
        carrier_overrides={"usdot_number": "DOT-844-R2", "legal_name": "Romeo Rigs"},
        station_overrides={"name": "I-20", "state_code": "GA"})
    assert _get_carrier(d["carrier"]["id"])["unpaid_fines_cents"] == 145000
    contest_citation(d["citation"]["id"], d["carrier"]["id"], reason="disputed axle reading")
    adjudicate_citation(d["citation"]["id"], "DISMISS", officer_id="officer-2")
    assert _get_carrier(d["carrier"]["id"])["unpaid_fines_cents"] == 0


# --- Difficulty: safety-basis precedence over fiscal cap ---

def _setup_safety_vs_fiscal(usdot):
    """Carrier holds an OVERWEIGHT citation (unpaid 145000); a second inspection is
    finalized OOS carrying only a VEHICLE OOS violation (no HAZMAT). Returns
    (carrier_id, inspection2_id)."""
    d = setup_inspection_finalized_oos(
        severity_weight=5, carrier_overrides={"usdot_number": usdot, "legal_name": "Juliet Transport"},
        station_overrides={"name": "I-90", "state_code": "WA"},
        scheduled_start="2026-03-02T08:00:00Z", scheduled_end="2026-03-02T09:00:00Z")
    issue_citation(d["inspection"]["id"], d["carrier"]["id"], kind="OVERWEIGHT", officer_id="officer-1")
    s2 = create_screening(d["station"]["id"], d["carrier"]["id"], d["driver"]["id"],
                          vehicle_plate="PLT-10", gross_weight_lbs=87000, heaviest_axle_lbs=21000)
    i2 = create_inspection(s2["id"], d["bay"]["id"],
                           scheduled_start="2026-03-02T10:00:00Z", scheduled_end="2026-03-02T11:00:00Z")
    add_violation(i2["id"], code="396.3", category="VEHICLE", severity_weight=5, oos=True)
    finalize(i2["id"], "OOS")
    return d["carrier"]["id"], i2["id"]


def test_hazmat_basis_missing_preempts_fine_cap(api):
    """PRD §2.6: "When more than one rule could reject a request, the checks run in a
    fixed order, and the first failing check determines the error returned."
    PRD §3.7: "a `HAZMAT` citation requires that the inspection carry at least one
    violation of `category` `HAZMAT`, else `ERR_HAZMAT_BASIS_MISSING`."

    Design: Difficulty/priority_pair_validation_conflict/citation_safety_beats_fiscal
    """
    carrier_id, inspection2_id = _setup_safety_vs_fiscal("DOT-844-J")
    resp = api.create_citation(
        {"inspection_id": inspection2_id, "carrier_id": carrier_id, "kind": "HAZMAT"}, OFFICER_1)
    validate_error(resp, ApiErrorId.ERR_HAZMAT_BASIS_MISSING)


def test_safety_basis_wins_over_fiscal_ceiling(api):
    """PRD §2.6: "A rule that sits lower in this list never masks a rule above it: for
    example, a request that would both fail the state check and the fiscal check surfaces
    the state error, because state precedes fiscal."
    PRD §3.7: "a `HAZMAT` citation requires that the inspection carry at least one
    violation of `category` `HAZMAT`, else `ERR_HAZMAT_BASIS_MISSING`."

    Design: Difficulty/priority_pair_validation_conflict/citation_safety_beats_fiscal
    """
    # unpaid already 145000, so a 100000 HAZMAT fine would also breach the 200000 cap;
    # the compliance-basis error (priority 7) must win over the fiscal error (priority 11).
    carrier_id, inspection2_id = _setup_safety_vs_fiscal("DOT-844-J2")
    assert _get_carrier(carrier_id)["unpaid_fines_cents"] == 145000
    resp = api.create_citation(
        {"inspection_id": inspection2_id, "carrier_id": carrier_id, "kind": "HAZMAT"}, OFFICER_1)
    validate_error(resp, ApiErrorId.ERR_HAZMAT_BASIS_MISSING)


# --- Corner: fiscal cap ---

def test_second_citation_exceeding_fine_cap_rejected(api):
    """PRD §3.7: "Before the citation is created, the fine ceiling is checked: the
    carrier's current `unpaid_fines_cents` plus the new `assessed_fine_cents` must be
    strictly below `200000` cents (two thousand dollars). If that sum would reach or
    exceed the cap, issuance is rejected with `ERR_FINE_CAP_EXCEEDED`."

    Design: Corner/endpoints/fine_cap_exceeded_returns_422
    """
    d = setup_inspection_finalized_oos(
        severity_weight=5, carrier_overrides={"usdot_number": "DOT-C15", "legal_name": "Corner Fifteen"},
        station_overrides={"name": "S15", "state_code": "CA"},
        scheduled_start="2026-03-02T08:00:00Z", scheduled_end="2026-03-02T09:00:00Z")
    issue_citation(d["inspection"]["id"], d["carrier"]["id"], kind="OVERWEIGHT", officer_id="officer-1")
    s2 = create_screening(d["station"]["id"], d["carrier"]["id"], d["driver"]["id"],
                          vehicle_plate="PLT-C15B", gross_weight_lbs=86000, heaviest_axle_lbs=21000)
    i2 = create_inspection(s2["id"], d["bay"]["id"],
                           scheduled_start="2026-03-02T10:00:00Z", scheduled_end="2026-03-02T11:00:00Z")
    add_violation(i2["id"], code="393.75", category="WEIGHT", severity_weight=5, oos=True)
    finalize(i2["id"], "OOS")
    resp = api.create_citation(
        {"inspection_id": i2["id"], "carrier_id": d["carrier"]["id"], "kind": "OVERWEIGHT"}, OFFICER_1)
    validate_error(resp, ApiErrorId.ERR_FINE_CAP_EXCEEDED)


# --- Corner: settlement success and mismatch ---

def test_settle_assessed_citation_zeroes_unpaid(api):
    """PRD §3.8: "For an `ASSESSED` citation the `payment_cents` must equal its
    `assessed_fine_cents`, and settlement records `final_fine_cents` equal to
    `assessed_fine_cents` and reduces the carrier's `unpaid_fines_cents` by that amount."

    Design: Corner/endpoints/citation_settle_success_zeroes_unpaid
    """
    d = setup_overweight_citation_assessed(
        carrier_overrides={"usdot_number": "DOT-C14", "legal_name": "Corner Fourteen"},
        station_overrides={"name": "S14", "state_code": "CA"})
    settled = validate_success(api.settle_citation(
        d["citation"]["id"], {"payment_cents": 145000}, make_carrier_rep_headers(d["carrier"]["id"])))
    assert settled["status"] == "SETTLED"
    assert _get_carrier(d["carrier"]["id"])["unpaid_fines_cents"] == 0


def test_settle_wrong_amount_rejected(api):
    """PRD §3.8: "A payment that does not equal the outstanding fine is rejected with
    `ERR_SETTLEMENT_AMOUNT_MISMATCH`."

    Design: Corner/validations/settle_amount_mismatch_rejected
    """
    d = setup_overweight_citation_assessed(
        carrier_overrides={"usdot_number": "DOT-C12", "legal_name": "Corner Twelve"},
        station_overrides={"name": "S12", "state_code": "CA"})
    resp = api.settle_citation(
        d["citation"]["id"], {"payment_cents": 100000}, make_carrier_rep_headers(d["carrier"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_AMOUNT_MISMATCH)


# --- Corner: carrier mismatch and overweight basis missing ---

def test_citation_carrier_mismatch_rejected(api):
    """PRD §3.7: "The cited `carrier_id` must equal the carrier of the citation's
    inspection's screening; a mismatch is rejected with `ERR_CARRIER_MISMATCH`."

    Design: Corner/validations/citation_carrier_mismatch_rejected
    """
    d = setup_inspection_finalized_oos(
        severity_weight=5, carrier_overrides={"usdot_number": "DOT-C8A", "legal_name": "Corner 8A"},
        station_overrides={"name": "S8", "state_code": "WY"})
    carrier_b = create_carrier(usdot_number="DOT-C8B", legal_name="Corner 8B")
    resp = api.create_citation(
        {"inspection_id": d["inspection"]["id"], "carrier_id": carrier_b["id"], "kind": "OVERWEIGHT"},
        OFFICER_1)
    validate_error(resp, ApiErrorId.ERR_CARRIER_MISMATCH)


def test_overweight_citation_without_overweight_screening_rejected(api):
    """PRD §3.7: "an `OVERWEIGHT` citation requires that the inspection's screening was
    itself overweight, else `ERR_OVERWEIGHT_BASIS_MISSING`; a `HAZMAT` citation requires
    that the inspection carry at least one violation of `category` `HAZMAT`, else
    `ERR_HAZMAT_BASIS_MISSING`."

    Design: Corner/validations/citation_overweight_basis_missing_rejected
    """
    d = setup_domain(carrier_overrides={"usdot_number": "DOT-C9", "legal_name": "Corner Nine"},
                     station_overrides={"name": "S9", "state_code": "CA"})
    # Legal weight but HAZMAT-placarded -> REFERRED for HAZMAT (not overweight).
    screening = create_screening(d["station"]["id"], d["carrier"]["id"], d["driver"]["id"],
                                 vehicle_plate="PLT-C9", gross_weight_lbs=79000,
                                 heaviest_axle_lbs=19000, hazmat_placarded=True)
    assert screening["overweight"] is False
    inspection = create_inspection(screening["id"], d["bay"]["id"])
    add_violation(inspection["id"], code="397.5", category="HAZMAT", severity_weight=5, oos=True)
    finalize(inspection["id"], "OOS")
    resp = api.create_citation(
        {"inspection_id": inspection["id"], "carrier_id": d["carrier"]["id"], "kind": "OVERWEIGHT"},
        OFFICER_1)
    validate_error(resp, ApiErrorId.ERR_OVERWEIGHT_BASIS_MISSING)


# --- Corner: contest from terminal state ---

def test_contest_dismissed_citation_rejected(api):
    """PRD §3.8: "A contest attempt against a citation that is not `ASSESSED` is rejected
    with `ERR_CITATION_INVALID_STATE`."

    Design: Corner/state_machines/citation_contest_from_dismissed_returns_invalid_state
    """
    d = setup_overweight_citation_contested(
        carrier_overrides={"usdot_number": "DOT-C6", "legal_name": "Corner Six"},
        station_overrides={"name": "S6", "state_code": "UT"})
    adjudicate_citation(d["citation"]["id"], "DISMISS", officer_id="officer-2")
    resp = api.contest_citation(
        d["citation"]["id"], {"contest_reason": "again"}, make_carrier_rep_headers(d["carrier"]["id"]))
    validate_error(resp, ApiErrorId.ERR_CITATION_INVALID_STATE)

"""Error-precedence ordering and optimistic-concurrency on final-judgment entry.

Translates queue A (Difficulty) rule priority_pair_validation_conflict (the
derivable instance only) and the queue B (Corner) optimistic-concurrency instance.

NOTE on a skipped difficulty instance:
  priority_pair_validation_conflict / invalid_state_beats_segregation_of_duties is
  NOT translated. Its asserted loser is ERR_INVALID_STATE for a FINAL_JUDGMENT entry
  while the case is not AWAITING_JUDGMENT, but the PRD never names the error_id raised
  when a final judgment is entered against a case in the wrong status (§3.7 states the
  precondition "may be entered only while the case is in `AWAITING_JUDGMENT`" without
  binding it to ERR_INVALID_STATE rather than the generic ERR_REFERENCED_STATE_INVALID).
  The outcome is therefore not uniquely derivable from PRD prose, so the instance is
  skipped per the PRD-first Core rule.
"""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers import fixtures as FX
from test_helpers import make_judge_headers

CLERK = TEST_USERS["clerk_headers"]


# =========================================================================
# Rule: priority_pair_validation_conflict
# instance referenced_support_not_calculated_beats_stale_version
#
# PRD §2.5 lays out the precedence ladder: after the five gates, Section-3 business
# rules are evaluated "in which referential-state checks ... and optimistic-concurrency
# checks each have their own dedicated identifiers" — referential first, OCC last. PRD
# §3.7 textually presents the support-order-CALCULATED referential check before the
# three final-judgment gates (the third of which is the version check). So the
# referential failure (ERR_SUPPORT_ORDER_NOT_CALCULATED) pre-empts the OCC failure
# (ERR_STALE_CASE_VERSION) — uniquely derivable.
# =========================================================================
def _setup_active_order_with_stale_final_judgment():
    """DEFAULT path AWAITING_JUDGMENT; a CHILD SupportOrder already ACTIVE (activated by
    an entered TEMPORARY order); a DRAFT FINAL_JUDGMENT referencing that ACTIVE order and
    superseding the temporary one. Returns dict with case, final_order, stale_version."""
    ctx = FX.setup_default_pending(pet_gross=800000, res_gross=400000, children=1)
    case, pet, res = ctx["case"], ctx["pet"], ctx["res"]
    plan = FX.propose_plan(case["id"], pet["id"], "u-pet", "PETITIONER", 110, 255)
    child_so = FX.create_support_order(case["id"], "CHILD", pet["id"], res["id"], "TEMPORARY")
    temp_order = FX.draft_court_order(case["id"], "TEMPORARY", [child_so["id"]])
    FX.enter_temporary_order(temp_order["id"])  # child_so -> ACTIVE
    FX.verified_disclosure(pet["id"], case["id"], "u-pet", "PETITIONER",
                          gross_monthly_income_cents=720000, tax_withholding_cents=120000,
                          mandatory_retirement_cents=0, health_insurance_cents=0)
    FX.advance_case(case["id"], "AWAITING_JUDGMENT")
    # FINAL_JUDGMENT references the already-ACTIVE child order (not CALCULATED).
    final_order = FX.draft_court_order(case["id"], "FINAL_JUDGMENT", [child_so["id"]],
                                       parenting_plan_id=plan["id"],
                                       supersedes_order_id=temp_order["id"])
    version = FX.current_case_version(case["id"])
    return {"case": case, "final_order": final_order, "stale_version": version - 1}


def test_referenced_support_not_calculated_beats_stale_version(api):
    """PRD §3.7: "At entry time, every referenced support order must be in `CALCULATED`
    status; if any referenced support order is not `CALCULATED`, entry is rejected with
    `ERR_SUPPORT_ORDER_NOT_CALCULATED`."
    PRD §2.5: "Only after these five gates pass does the system evaluate the
    operation-specific business rules described in Section 3, in which referential-state
    checks, segregation-of-duties checks, temporal-overlap checks, and
    optimistic-concurrency checks each have their own dedicated identifiers."

    The ACTIVE (not CALCULATED) referenced order triggers the referential failure, which
    is evaluated before the stale-version OCC check.

    Design: Difficulty/priority_pair_validation_conflict/referenced_support_not_calculated_beats_stale_version
    """
    ctx = _setup_active_order_with_stale_final_judgment()
    resp = api.enter_court_order(
        ctx["final_order"]["id"], {"expected_case_version": ctx["stale_version"]},
        make_judge_headers("u-judge"))
    validate_error(resp, ApiErrorId.ERR_SUPPORT_ORDER_NOT_CALCULATED.value)


def test_referenced_support_not_calculated_leaves_case_awaiting_judgment(api):
    """PRD §3.7: "if any referenced support order is not `CALCULATED`, entry is rejected
    with `ERR_SUPPORT_ORDER_NOT_CALCULATED`."

    The rejected entry leaves the case un-mutated (still AWAITING_JUDGMENT).

    Design: Difficulty/priority_pair_validation_conflict/referenced_support_not_calculated_beats_stale_version
    """
    ctx = _setup_active_order_with_stale_final_judgment()
    resp = api.enter_court_order(
        ctx["final_order"]["id"], {"expected_case_version": ctx["stale_version"]},
        make_judge_headers("u-judge"))
    validate_error(resp, ApiErrorId.ERR_SUPPORT_ORDER_NOT_CALCULATED.value)
    fetched = validate_success(api.get_case(ctx["case"]["id"], CLERK), 200)
    assert fetched["status"] == "AWAITING_JUDGMENT"


# =========================================================================
# Queue B (Corner) — cross_cutting_complexity_layers (optimistic concurrency)
# =========================================================================
def test_occ_stale_case_version_on_final_judgment_returns_412(api):
    """PRD §2.6: "If `expected_case_version` does not equal the case's current `version`,
    the entry is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412)."

    A DRAFT FINAL_JUDGMENT referencing a CALCULATED order (so no referential failure
    pre-empts) entered with expected_case_version one less than current -> 412; the case
    stays AWAITING_JUDGMENT.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_case_version_on_final_judgment_returns_412
    """
    ctx = FX.setup_default_awaiting_judgment_final_only()
    case, final_order = ctx["case"], ctx["final_order"]
    stale = FX.current_case_version(case["id"]) - 1
    resp = api.enter_court_order(
        final_order["id"], {"expected_case_version": stale}, make_judge_headers("u-judge"))
    validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION.value)
    fetched = validate_success(api.get_case(case["id"], CLERK), 200)
    assert fetched["status"] == "AWAITING_JUDGMENT"

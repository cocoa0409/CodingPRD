"""Citation issuance, the tiered fine calculation, the conserved outstanding
balance, and the cyclic contest loop."""
import test_helpers as th
from test_helpers import ApiErrorId


# --------------------------------------------------------------------------
# Difficulty: combinatorial_formula / citation_fine_tiered_nonlinear_mode_a
# --------------------------------------------------------------------------
def test_citation_fine_combines_severity_risk_and_repeat(api):
    """PRD §3.6: "The base fine is set by the deficiency's severity: 5000 cents for
    MINOR, 20000 cents for MAJOR, and 50000 cents for CRITICAL. That base is
    risk-adjusted by multiplying by the device's risk factor — 1.5 when the
    device's risk_class is HIGH ... with the product rounded half up. A
    repeat-offense surcharge is then added: count the citations already existing
    on the same device whose status is ISSUED, CONTESTED, or PAID that were
    created before this one, cap that count at 3, and multiply the capped count by
    10000 cents. The fine_amount_cents is the risk-adjusted base plus the repeat
    surcharge, but never more than a ceiling of 100000 cents."

    Design: Difficulty/combinatorial_formula/citation_fine_tiered_nonlinear_mode_a
    """
    owner = th.new_owner(api)
    inspector = th.new_inspector(api, categories=["ESCALATOR"])
    device = th.new_device(api, owner["id"], category="ESCALATOR")
    _, def_prior = th.conditional_with_deficiency(api, device["id"], inspector["id"],
                                                  severity="MINOR", code="D-MIN", start=1, end=2)
    th.issue_citation(api, def_prior["id"])
    _, def_target = th.conditional_with_deficiency(api, device["id"], inspector["id"],
                                                  severity="MAJOR", code="D-MAJ", start=5, end=6)
    resp = api.create_citation(th.create_citation_payload(def_target["id"]), th.REG)
    citation = th.validate_success(resp, expected_status=201)
    assert citation["fine_amount_cents"] == 40000, \
        "round(20000*1.5)=30000 + min(1,3)*10000=10000"


def test_citation_issuance_moves_deficiency_to_cited(api):
    """PRD §3.6: "Issuance creates a Citation in ISSUED status, copies the device_id
    from the deficiency onto the citation, and moves the deficiency from OPEN to
    CITED."

    Design: Difficulty/combinatorial_formula/citation_fine_tiered_nonlinear_mode_a
    """
    owner = th.new_owner(api)
    inspector = th.new_inspector(api, categories=["ESCALATOR"])
    device = th.new_device(api, owner["id"], category="ESCALATOR")
    _, def_prior = th.conditional_with_deficiency(api, device["id"], inspector["id"],
                                                  severity="MINOR", code="D-MIN", start=1, end=2)
    th.issue_citation(api, def_prior["id"])
    _, def_target = th.conditional_with_deficiency(api, device["id"], inspector["id"],
                                                  severity="MAJOR", code="D-MAJ", start=5, end=6)
    citation = th.validate_success(api.create_citation(th.create_citation_payload(def_target["id"]), th.REG),
                                   expected_status=201)
    assert citation["status"] == "ISSUED"
    reloaded = th.validate_success(api.get_deficiency(def_target["id"], th.REG))
    assert reloaded["status"] == "CITED"


# --------------------------------------------------------------------------
# Difficulty: combinatorial_formula / outstanding_balance_round_then_sum_mode_b
# --------------------------------------------------------------------------
def test_second_citation_fine_and_surcharge_dumbwaiter(api):
    """PRD §3.6: "That base is risk-adjusted by multiplying by the device's risk
    factor — ... 1.0 when LOW ... A repeat-offense surcharge is then added ... the
    surcharged_amount_cents ... is the fine_amount_cents multiplied by one plus the
    outstanding index rate of 0.0725, rounded half up."

    Design: Difficulty/combinatorial_formula/outstanding_balance_round_then_sum_mode_b
    """
    ctx = th.setup_device_fee_paid(api, category="DUMBWAITER")
    inspector = th.new_inspector(api, categories=["DUMBWAITER"])
    _, def1 = th.conditional_with_deficiency(api, ctx["device"]["id"], inspector["id"],
                                             severity="MINOR", code="M1", start=1, end=2)
    th.issue_citation(api, def1["id"])
    _, def2 = th.conditional_with_deficiency(api, ctx["device"]["id"], inspector["id"],
                                             severity="MINOR", code="M2", start=5, end=6)
    citation2 = th.validate_success(api.create_citation(th.create_citation_payload(def2["id"]), th.REG),
                                    expected_status=201)
    assert citation2["fine_amount_cents"] == 15000, "5000 base LOW*1.0 + 1 prior*10000"
    assert citation2["surcharged_amount_cents"] == 16088, "round_half_up(15000*1.0725)"


def test_outstanding_balance_rounds_each_surcharge_before_summing(api):
    """PRD §2.6: "The rounding order is pinned: each citation's surcharge is rounded
    to whole cents and persisted per citation as its surcharged_amount_cents first,
    and only then are the per-citation amounts summed. Rounding the summed total
    instead is explicitly not permitted, as it can yield a different figure."

    Design: Difficulty/combinatorial_formula/outstanding_balance_round_then_sum_mode_b
    """
    ctx = th.setup_device_fee_paid(api, category="DUMBWAITER")
    inspector = th.new_inspector(api, categories=["DUMBWAITER"])
    _, def1 = th.conditional_with_deficiency(api, ctx["device"]["id"], inspector["id"],
                                             severity="MINOR", code="M1", start=1, end=2)
    th.issue_citation(api, def1["id"])
    _, def2 = th.conditional_with_deficiency(api, ctx["device"]["id"], inspector["id"],
                                             severity="MINOR", code="M2", start=5, end=6)
    th.issue_citation(api, def2["id"])
    dev = th.get_device(api, ctx["device"]["id"])
    assert dev["outstanding_balance_cents"] == 21451, "5363 + 16088 (round-then-sum, not 21450)"


# --------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / citation_cyclic_contest_loop
# --------------------------------------------------------------------------
def test_contest_loop_returns_to_contested(api):
    """PRD §3.6: "An outcome of UPHELD returns the citation from CONTESTED back to
    ISSUED, from which the owner may pay it or contest it once more — this is the
    loop, and each fresh contest again advances contest_count."

    Design: Difficulty/non_linear_state_machine/citation_cyclic_contest_loop
    """
    ctx = th.setup_issued_citation(api, category="PASSENGER_ELEVATOR", severity="MINOR")
    owner_h = th.make_building_owner_headers(ctx["owner"]["id"])
    cit_id = ctx["citation"]["id"]
    th.validate_success(api.contest_citation(cit_id, owner_h))
    th.validate_success(api.resolve_contest(cit_id, th.resolve_contest_payload("UPHELD"), th.SAFETY))
    resp = api.contest_citation(cit_id, owner_h)
    contested = th.validate_success(resp)
    assert contested["status"] == "CONTESTED"


def test_contest_loop_increments_contest_count_twice(api):
    """PRD §3.6: "Contesting moves the citation to `CONTESTED` and increments its
    `contest_count` by 1."
    PRD §3.6: "from which the owner may pay it or contest it once more — this is the
    loop, and each fresh contest again advances `contest_count`."

    Design: Difficulty/non_linear_state_machine/citation_cyclic_contest_loop
    """
    ctx = th.setup_issued_citation(api, category="PASSENGER_ELEVATOR", severity="MINOR")
    owner_h = th.make_building_owner_headers(ctx["owner"]["id"])
    cit_id = ctx["citation"]["id"]
    th.validate_success(api.contest_citation(cit_id, owner_h))
    th.validate_success(api.resolve_contest(cit_id, th.resolve_contest_payload("UPHELD"), th.SAFETY))
    final = th.validate_success(api.contest_citation(cit_id, owner_h))
    assert final["contest_count"] == 2, "loop traversed twice"


# --------------------------------------------------------------------------
# Difficulty: compensating_invariant / outstanding_balance_conserved_on_dismiss
# --------------------------------------------------------------------------
def test_dismissed_contest_restores_outstanding_balance(api):
    """PRD §3.6: "the surcharged_amount_cents — the exact figure that enters and
    later leaves the device's ledger — is the fine_amount_cents multiplied by one
    plus the outstanding index rate of 0.0725, rounded half up. Upon issuance,
    surcharged_amount_cents is added to the device's outstanding_balance_cents."
    PRD §3.6: "An outcome of DISMISSED moves the citation to the terminal DISMISSED
    state, removes its surcharged_amount_cents from the device's
    outstanding_balance_cents (exactly reversing the debit taken at issuance)".

    Design: Difficulty/compensating_invariant/outstanding_balance_conserved_on_dismiss
    """
    ctx = th.setup_issued_citation(api, category="PASSENGER_ELEVATOR", severity="MINOR")
    assert ctx["citation"]["surcharged_amount_cents"] == 8044, "round_half_up(7500*1.0725)"
    owner_h = th.make_building_owner_headers(ctx["owner"]["id"])
    cit_id = ctx["citation"]["id"]
    th.validate_success(api.contest_citation(cit_id, owner_h))
    th.validate_success(api.resolve_contest(cit_id, th.resolve_contest_payload("DISMISSED"), th.SAFETY))
    dev = th.get_device(api, ctx["device"]["id"])
    assert dev["outstanding_balance_cents"] == 0, "balance restored to pre-issuance value"


def test_dismissed_contest_waives_linked_deficiency(api):
    """PRD §3.6: "An outcome of DISMISSED moves the citation to the terminal
    DISMISSED state ... and moves the linked deficiency from CITED to the terminal
    WAIVED state."

    Design: Difficulty/compensating_invariant/outstanding_balance_conserved_on_dismiss
    """
    ctx = th.setup_issued_citation(api, category="PASSENGER_ELEVATOR", severity="MINOR")
    owner_h = th.make_building_owner_headers(ctx["owner"]["id"])
    cit_id = ctx["citation"]["id"]
    th.validate_success(api.contest_citation(cit_id, owner_h))
    dismissed = th.validate_success(api.resolve_contest(cit_id, th.resolve_contest_payload("DISMISSED"), th.SAFETY))
    assert dismissed["status"] == "DISMISSED"
    deficiency = th.validate_success(api.get_deficiency(ctx["deficiency"]["id"], th.REG))
    assert deficiency["status"] == "WAIVED"


# --------------------------------------------------------------------------
# Corner instances
# --------------------------------------------------------------------------
def test_cite_already_cited_deficiency_returns_not_open(api):
    """PRD §3.6: "The deficiency must be `OPEN`, or the request is rejected with
    `ERR_DEFICIENCY_NOT_OPEN`."

    Design: Corner/errors/cite_already_cited_deficiency_returns_not_open
    """
    ctx = th.setup_issued_citation(api, category="PASSENGER_ELEVATOR", severity="MAJOR")
    resp = api.create_citation(th.create_citation_payload(ctx["deficiency"]["id"]), th.REG)
    th.validate_error(resp, ApiErrorId.ERR_DEFICIENCY_NOT_OPEN.value)


def test_nonowner_cannot_pay_citation(api):
    """PRD §3.6: "The owning BuildingOwner may pay the citation while it is ISSUED
    ... and a caller who does not own the device is rejected with
    ERR_NOT_RESOURCE_OWNER."

    Design: Corner/rbac/nonowner_cannot_pay_citation
    """
    ctx = th.setup_issued_citation(api, category="PASSENGER_ELEVATOR", severity="MINOR")
    other_owner = th.new_owner(api)
    resp = api.pay_citation(ctx["citation"]["id"], th.make_building_owner_headers(other_owner["id"]))
    th.validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_citation_pay_reduces_outstanding_balance(api):
    """PRD §3.6: "Payment moves the citation to the terminal `PAID` state and
    removes its `surcharged_amount_cents` from the device's
    `outstanding_balance_cents`."

    Design: Corner/cross_cutting/citation_pay_reduces_outstanding_balance
    """
    ctx = th.setup_issued_citation(api, category="PASSENGER_ELEVATOR", severity="MINOR", fee_paid=True)
    resp = api.pay_citation(ctx["citation"]["id"], th.make_building_owner_headers(ctx["owner"]["id"]))
    paid = th.validate_success(resp)
    assert paid["status"] == "PAID"
    dev = th.get_device(api, ctx["device"]["id"])
    assert dev["outstanding_balance_cents"] == 0


def test_outstanding_balance_visible_immediately_after_citation(api):
    """PRD §2.6: "every citation or fee-invoice status change that adds a charge to,
    or removes one from, those unpaid sets adjusts outstanding_balance_cents by
    exactly the amount that entered or left the set, so the running balance always
    agrees with the aggregation just described."

    Design: Corner/consistency_model/outstanding_balance_visible_immediately_after_citation
    """
    ctx = th.setup_issued_citation(api, category="PASSENGER_ELEVATOR", severity="MINOR", fee_paid=False)
    dev = th.get_device(api, ctx["device"]["id"])
    assert dev["outstanding_balance_cents"] == 18044, "10000 registration + 8044 citation surcharge"

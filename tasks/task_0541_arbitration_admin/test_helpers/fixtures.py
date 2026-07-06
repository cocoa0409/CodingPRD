"""Composite setup helpers.

Each helper builds its preconditions from scratch through PRD-declared endpoints
(the server starts against an empty database before every test). Setup calls use
the lenient get_success_data() so failures surface as clear "Setup failed"
errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .test_users import make_admin_headers, make_party_headers, make_neutral_headers
from .factories import (
    create_case_payload, create_party_payload, create_neutral_payload,
    add_candidate_payload, create_ranking_payload, create_deposit_payload,
    create_fee_charge_payload, create_award_payload, create_appeal_payload,
    create_hearing_payload,
)

ADMIN = make_admin_headers()


# --- Low-level building blocks -------------------------------------------

def set_clock(api, iso: str) -> dict:
    return get_success_data(api.set_clock({"to_iso8601": iso}, ADMIN))


def create_neutral(api, *, full_name="Neutral", neutral_type="ARBITRATOR",
                   hourly_rate_cents=50_000) -> dict:
    return get_success_data(api.create_neutral(create_neutral_payload(
        full_name=full_name, neutral_type=neutral_type,
        hourly_rate_cents=hourly_rate_cents), ADMIN))


def create_case(api, *, case_type="ARBITRATION", title="Case",
                claim_amount_cents=2_000_000, panel_size=1,
                strikes_per_party=None) -> dict:
    payload = create_case_payload(case_type=case_type, title=title,
                                  claim_amount_cents=claim_amount_cents,
                                  panel_size=panel_size)
    if strikes_per_party is not None:
        payload["strikes_per_party"] = strikes_per_party
    return get_success_data(api.create_case(payload, ADMIN))


def add_party(api, case_id, role, display_name, share_pct) -> dict:
    return get_success_data(api.create_party(create_party_payload(
        case_id=case_id, role=role, display_name=display_name,
        share_pct=share_pct), ADMIN))


def add_two_parties(api, case_id):
    pA = add_party(api, case_id, "CLAIMANT", "A", 50)
    pB = add_party(api, case_id, "RESPONDENT", "B", 50)
    return pA, pB


def get_case(api, case_id) -> dict:
    return get_success_data(api.get_case(case_id, ADMIN))


def case_version(api, case_id) -> int:
    return get_case(api, case_id)["version"]


def open_selection(api, case_id) -> dict:
    return get_success_data(api.transition_case(case_id, {"to_status": "SELECTION"}, ADMIN))


def add_candidate(api, case_id, neutral_id, expected_version) -> dict:
    return get_success_data(api.add_candidate(case_id, add_candidate_payload(
        neutral_id=neutral_id, expected_case_version=expected_version), ADMIN))


def disclose(api, candidate_id, neutral_id, *, disclosure_text="none",
             has_conflict=False) -> dict:
    return get_success_data(api.disclose_candidate(
        candidate_id, {"disclosure_text": disclosure_text, "has_conflict": has_conflict},
        make_neutral_headers(neutral_id)))


def clear_candidate(api, candidate_id) -> dict:
    return get_success_data(api.transition_candidate(candidate_id, {"to_status": "CLEARED"}, ADMIN))


def appoint(api, case_id) -> dict:
    v = case_version(api, case_id)
    return get_success_data(api.appoint_case(case_id, {"expected_case_version": v}, ADMIN))


def to_hearing(api, case_id) -> dict:
    return get_success_data(api.transition_case(case_id, {"to_status": "HEARING"}, ADMIN))


def find_party(api, case_id, party_id) -> dict:
    parties = get_success_data(api.list_case_parties(case_id, ADMIN))
    for p in parties:
        if p["id"] == party_id:
            return p
    raise AssertionError(f"Setup failed: party {party_id} not found on case {case_id}")


def post_fee_charge(api, case_id, neutral_id, hours) -> dict:
    v = case_version(api, case_id)
    return get_success_data(api.create_fee_charge(case_id, create_fee_charge_payload(
        neutral_id=neutral_id, hours=hours, expected_case_version=v), ADMIN))


# --- Tier 1/2: Selection-phase scenarios ---------------------------------

def setup_selection_with_candidate(api, *, has_conflict=False, disclose_it=True,
                                   clear_it=False, neutral_type="ARBITRATOR",
                                   claim_amount_cents=500_000, strikes_per_party=None):
    """SELECTION-phase ARBITRATION case with one candidate. By default the
    candidate is DISCLOSED (no conflict). Returns dict of case/neutral/parties/
    candidate."""
    neutral = create_neutral(api, neutral_type=neutral_type)
    case = create_case(api, claim_amount_cents=claim_amount_cents,
                       strikes_per_party=strikes_per_party)
    pA, pB = add_two_parties(api, case["id"])
    open_selection(api, case["id"])
    v = case_version(api, case["id"])
    cand = add_candidate(api, case["id"], neutral["id"], v)
    if disclose_it:
        disclose(api, cand["id"], neutral["id"], has_conflict=has_conflict)
    if clear_it:
        clear_candidate(api, cand["id"])
    return {"case": get_case(api, case["id"]), "neutral": neutral,
            "pA": pA, "pB": pB, "candidate": cand}


def setup_selection_two_cleared_candidates(api, *, rank_first=False,
                                           claim_amount_cents=500_000):
    """SELECTION case with two CLEARED candidates (neutrals n1, n2, both created
    before any ranking). Optionally party A ranks candidate 1 with 5 points."""
    n1 = create_neutral(api, full_name="N1")
    n2 = create_neutral(api, full_name="N2")
    case = create_case(api, claim_amount_cents=claim_amount_cents)
    pA, pB = add_two_parties(api, case["id"])
    open_selection(api, case["id"])
    v = case_version(api, case["id"])
    cand1 = add_candidate(api, case["id"], n1["id"], v)
    v2 = case_version(api, case["id"])
    cand2 = add_candidate(api, case["id"], n2["id"], v2)
    disclose(api, cand1["id"], n1["id"])
    clear_candidate(api, cand1["id"])
    disclose(api, cand2["id"], n2["id"])
    clear_candidate(api, cand2["id"])
    if rank_first:
        get_success_data(api.create_ranking(create_ranking_payload(
            candidate_id=cand1["id"], party_id=pA["id"], action="RANK",
            rank_value=5), make_party_headers(pA["id"])))
    return {"case": get_case(api, case["id"]), "n1": n1, "n2": n2,
            "pA": pA, "pB": pB, "cand1": cand1, "cand2": cand2}


def setup_selection_two_proposed_candidates(api, *, strikes_per_party=2):
    """SELECTION case with two PROPOSED candidates (neutrals n1, n2), no
    disclosure. Used for strike-budget / withdraw tests."""
    n1 = create_neutral(api, full_name="N1")
    n2 = create_neutral(api, full_name="N2")
    case = create_case(api, claim_amount_cents=500_000, strikes_per_party=strikes_per_party)
    pA, pB = add_two_parties(api, case["id"])
    open_selection(api, case["id"])
    v = case_version(api, case["id"])
    cand1 = add_candidate(api, case["id"], n1["id"], v)
    v2 = case_version(api, case["id"])
    cand2 = add_candidate(api, case["id"], n2["id"], v2)
    return {"case": get_case(api, case["id"]), "n1": n1, "n2": n2,
            "pA": pA, "pB": pB, "cand1": cand1, "cand2": cand2}


# --- Tier 3: Full lifecycle to HEARING -----------------------------------

def setup_hearing_case(api, *, neutral=None, claim_amount_cents=2_000_000,
                       hourly_rate_cents=50_000, panel_size=1,
                       case_type="ARBITRATION", clock=None):
    """Appointed ARBITRATION case advanced to HEARING with one appointed neutral.
    Returns dict of case/neutral/parties/candidate."""
    if clock is not None:
        set_clock(api, clock)
    if neutral is None:
        neutral = create_neutral(api, hourly_rate_cents=hourly_rate_cents)
    case = create_case(api, case_type=case_type, claim_amount_cents=claim_amount_cents,
                       panel_size=panel_size)
    pA, pB = add_two_parties(api, case["id"])
    open_selection(api, case["id"])
    v = case_version(api, case["id"])
    cand = add_candidate(api, case["id"], neutral["id"], v)
    disclose(api, cand["id"], neutral["id"])
    clear_candidate(api, cand["id"])
    appoint(api, case["id"])
    to_hearing(api, case["id"])
    return {"case": get_case(api, case["id"]), "neutral": neutral,
            "pA": pA, "pB": pB, "candidate": cand}


def setup_hearing_case_with_paid_deposit(api, *, deposit_cents=500_000,
                                         hourly_rate_cents=50_000,
                                         claim_amount_cents=2_000_000, clock=None):
    """HEARING case plus one PAID deposit crediting the case's deposit balance."""
    ctx = setup_hearing_case(api, hourly_rate_cents=hourly_rate_cents,
                             claim_amount_cents=claim_amount_cents, clock=clock)
    dep = get_success_data(api.create_deposit(create_deposit_payload(
        case_id=ctx["case"]["id"], amount_cents=deposit_cents), ADMIN))
    get_success_data(api.pay_deposit(dep["id"], make_party_headers(ctx["pA"]["id"])))
    ctx["deposit"] = dep
    ctx["case"] = get_case(api, ctx["case"]["id"])
    return ctx


def setup_hearing_case_with_hearing(api, *, clock="2026-06-01T00:00:00Z",
                                    start_at="2026-06-20T09:00:00Z",
                                    end_at="2026-06-20T11:00:00Z"):
    """HEARING case with one SCHEDULED hearing already in place."""
    ctx = setup_hearing_case(api, clock=clock)
    h = get_success_data(api.create_hearing(ctx["case"]["id"], create_hearing_payload(
        hearing_type="EVIDENTIARY", start_at=start_at, end_at=end_at,
        location="Room A"), ADMIN))
    ctx["hearing"] = h
    return ctx


def setup_two_hearing_cases_same_neutral(api, *, clock="2026-06-01T00:00:00Z"):
    """Two HEARING cases sharing one appointed neutral; case 1 has a SCHEDULED
    hearing 09:00-11:00. Returns neutral + both cases + h1."""
    set_clock(api, clock)
    neutral = create_neutral(api, full_name="Shared")
    c1 = setup_hearing_case(api, neutral=neutral)
    h1 = get_success_data(api.create_hearing(c1["case"]["id"], create_hearing_payload(
        hearing_type="EVIDENTIARY", start_at="2026-06-20T09:00:00Z",
        end_at="2026-06-20T11:00:00Z", location="Room A"), ADMIN))
    c2 = setup_hearing_case(api, neutral=neutral)
    return {"neutral": neutral, "c1": c1["case"], "c2": c2["case"], "h1": h1}


# --- Tier 5: Awards / appeals --------------------------------------------

def setup_issued_award(api, *, claim_amount_cents=10_000_000, award_amount_cents=500_000,
                       deposit_cents=None, hourly_rate_cents=50_000, clock=None):
    """HEARING case with a MONETARY award drafted and ISSUED (case now
    AWARD_ISSUED). Returns dict incl. award."""
    if deposit_cents:
        ctx = setup_hearing_case_with_paid_deposit(
            api, deposit_cents=deposit_cents, hourly_rate_cents=hourly_rate_cents,
            claim_amount_cents=claim_amount_cents, clock=clock)
    else:
        ctx = setup_hearing_case(api, claim_amount_cents=claim_amount_cents,
                                 hourly_rate_cents=hourly_rate_cents, clock=clock)
    aw = get_success_data(api.create_award(ctx["case"]["id"], create_award_payload(
        award_type="MONETARY", award_amount_cents=award_amount_cents), ADMIN))
    issued = get_success_data(api.transition_award(aw["id"], {"to_status": "ISSUED"}, ADMIN))
    ctx["award"] = issued
    ctx["case"] = get_case(api, ctx["case"]["id"])
    return ctx


def setup_appeal_under_review(api, *, claim_amount_cents=10_000_000,
                              award_amount_cents=500_000, deposit_cents=500_000,
                              ground="EXCEEDED_POWERS", clock="2026-06-01T00:00:00Z"):
    """Case with an ISSUED award and an appeal advanced to UNDER_REVIEW."""
    ctx = setup_issued_award(api, claim_amount_cents=claim_amount_cents,
                             award_amount_cents=award_amount_cents,
                             deposit_cents=deposit_cents, clock=clock)
    appeal = get_success_data(api.create_appeal(create_appeal_payload(
        award_id=ctx["award"]["id"], ground=ground),
        make_party_headers(ctx["pA"]["id"])))
    ur = get_success_data(api.transition_appeal(appeal["id"], {"to_status": "UNDER_REVIEW"}, ADMIN))
    ctx["appeal"] = ur
    return ctx


# --- Deposit / exchange scenarios ----------------------------------------

def setup_filed_case_with_party(api, *, clock=None, share_pct=100):
    """A FILED case with one CLAIMANT party (no selection opened)."""
    if clock is not None:
        set_clock(api, clock)
    case = create_case(api, claim_amount_cents=500_000)
    pA = add_party(api, case["id"], "CLAIMANT", "A", share_pct)
    return {"case": case, "pA": pA}


def setup_paid_deposit_on_filed_case(api, *, amount_cents=100_000, clock=None):
    """FILED case + party + one PAID deposit."""
    ctx = setup_filed_case_with_party(api, clock=clock)
    dep = get_success_data(api.create_deposit(create_deposit_payload(
        case_id=ctx["case"]["id"], amount_cents=amount_cents), ADMIN))
    get_success_data(api.pay_deposit(dep["id"], make_party_headers(ctx["pA"]["id"])))
    ctx["deposit"] = dep
    return ctx

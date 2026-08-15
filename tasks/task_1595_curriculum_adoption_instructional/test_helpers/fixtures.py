"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. Setup calls use get_success_data() so a failed
precondition reports as a clear "Setup failed" error.

All nine roles are opaque identities; ownership- and segregation-sensitive
calls (teacher reviews, supplemental approvals, challenge filings, votes,
appeals) take an explicit user id and build per-instance headers.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_alignment_payload,
    create_challenge_payload,
    create_cycle_payload,
    create_distribution_order_payload,
    create_framework_payload,
    create_material_payload,
    create_pilot_payload,
    create_purchase_order_payload,
    create_quote_payload,
    create_review_payload,
    create_supplemental_request_payload,
    create_vote_payload,
)
from .test_users import (
    TEST_USERS,
    make_committee_member_headers,
    make_community_member_headers,
    make_curriculum_director_headers,
    make_instructional_specialist_headers,
    make_teacher_headers,
)

ADMIN = TEST_USERS["district_admin_headers"]
DIRECTOR = TEST_USERS["curriculum_director_headers"]
SPECIALIST = TEST_USERS["instructional_specialist_headers"]
SECRETARY = TEST_USERS["board_secretary_headers"]
PROCUREMENT = TEST_USERS["procurement_officer_headers"]
WAREHOUSE = TEST_USERS["warehouse_manager_headers"]

# Clock position used to close a 30-day public review window opened at the
# default clock (2026-08-01 + 30 days = 2026-08-31, so 09-01 is past it).
DEFAULT_BOARD_CLOCK = "2026-09-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: single-call primitives (parsed payloads, lenient validation)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_framework(**overrides) -> dict:
    resp = api_client.create_framework(create_framework_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_cycle(framework_id, **overrides) -> dict:
    payload = create_cycle_payload(framework_id=framework_id, **overrides)
    resp = api_client.create_cycle(payload, DIRECTOR)
    return get_success_data(resp)


def create_material(cycle_id, **overrides) -> dict:
    resp = api_client.create_material(cycle_id, create_material_payload(**overrides),
                                      DIRECTOR)
    return get_success_data(resp)


def transition_material(material_id, to_state) -> dict:
    resp = api_client.transition_material(material_id, {"to_state": to_state},
                                          SPECIALIST)
    return get_success_data(resp)


def vet_material(material_id) -> dict:
    return transition_material(material_id, "VETTED")


def upsert_alignment(material_id, standard_code="S1", coverage_rating="FULL") -> dict:
    payload = create_alignment_payload(standard_code=standard_code,
                                       coverage_rating=coverage_rating)
    resp = api_client.upsert_alignment(material_id, payload, SPECIALIST)
    return get_success_data(resp)


def transition_cycle(cycle_id, to_state, headers=None) -> dict:
    """Success-path cycle transition. The caller passes the role headers that
    own the target state (specialist for ALIGNMENT_REVIEW/PILOT_OPEN, director
    for SCORING/ACTIVE/SUNSET/DRAFT, secretary for PUBLIC_REVIEW/BOARD_PENDING).
    """
    if headers is None:
        headers = {
            "ALIGNMENT_REVIEW": SPECIALIST,
            "PILOT_OPEN": SPECIALIST,
            "DRAFT": DIRECTOR,
            "SCORING": DIRECTOR,
            "ACTIVE": DIRECTOR,
            "SUNSET": DIRECTOR,
            "PUBLIC_REVIEW": SECRETARY,
            "BOARD_PENDING": SECRETARY,
        }[to_state]
    resp = api_client.transition_cycle(cycle_id, {"to_state": to_state}, headers)
    return get_success_data(resp)


def create_pilot(cycle_id, material_id, **overrides) -> dict:
    payload = create_pilot_payload(material_id=material_id, **overrides)
    resp = api_client.create_pilot(cycle_id, payload, DIRECTOR)
    return get_success_data(resp)


def transition_pilot(pilot_id, to_state) -> dict:
    resp = api_client.transition_pilot(pilot_id, {"to_state": to_state}, DIRECTOR)
    return get_success_data(resp)


def submit_review(pilot_id, teacher_id, scores=(4, 4, 4, 4)) -> dict:
    pedagogy, alignment, usability, equity = scores
    payload = create_review_payload(
        pedagogy_score=pedagogy, alignment_score=alignment,
        usability_score=usability, equity_score=equity,
    )
    resp = api_client.create_review(pilot_id, payload,
                                    make_teacher_headers(teacher_id))
    return get_success_data(resp)


def create_quote(cycle_id, material_id, **overrides) -> dict:
    payload = create_quote_payload(material_id=material_id, **overrides)
    resp = api_client.create_quote(cycle_id, payload, PROCUREMENT)
    return get_success_data(resp)


def transition_quote(quote_id, to_state, **field_updates) -> dict:
    payload = {"to_state": to_state}
    payload.update(field_updates)
    resp = api_client.transition_quote(quote_id, payload, PROCUREMENT)
    return get_success_data(resp)


def evaluate_quote(quote_id) -> dict:
    return transition_quote(quote_id, "UNDER_EVALUATION")


def get_cycle(cycle_id) -> dict:
    return get_success_data(api_client.get_cycle(cycle_id, DIRECTOR))


def get_cycle_version(cycle_id) -> int:
    return get_cycle(cycle_id)["version"]


def get_material(material_id) -> dict:
    return get_success_data(api_client.get_material(material_id, DIRECTOR))


def get_pilot(pilot_id) -> dict:
    return get_success_data(api_client.get_pilot(pilot_id, DIRECTOR))


def get_quote(quote_id) -> dict:
    return get_success_data(api_client.get_quote(quote_id, PROCUREMENT))


def get_purchase_order(po_id) -> dict:
    return get_success_data(api_client.get_purchase_order(po_id, PROCUREMENT))


def get_challenge(challenge_id) -> dict:
    return get_success_data(api_client.get_challenge(challenge_id, DIRECTOR))


def award_quote(cycle_id, quote_id, expected_cycle_version=None):
    """Post an award. Returns the raw response. When expected_cycle_version is
    None the current version is fetched first (the OCC-happy path)."""
    if expected_cycle_version is None:
        expected_cycle_version = get_cycle_version(cycle_id)
    payload = {"quote_id": quote_id,
               "expected_cycle_version": expected_cycle_version}
    return api_client.award(cycle_id, payload, PROCUREMENT)


def award_quote_fresh(cycle_id, quote_id) -> dict:
    return get_success_data(award_quote(cycle_id, quote_id))


def post_appropriation(cycle_id, amount) -> dict:
    resp = api_client.post_appropriation(cycle_id, {"amount": amount}, ADMIN)
    return get_success_data(resp)


def create_purchase_order(cycle_id, quote_id, print_quantity,
                          digital_seat_count=0, expected_cycle_version=None):
    """Create a PO. Returns the raw response. When expected_cycle_version is
    None the current version is fetched first (the OCC-happy path)."""
    if expected_cycle_version is None:
        expected_cycle_version = get_cycle_version(cycle_id)
    payload = create_purchase_order_payload(
        quote_id=quote_id, print_quantity=print_quantity,
        digital_seat_count=digital_seat_count,
        expected_cycle_version=expected_cycle_version,
    )
    return api_client.create_purchase_order(cycle_id, payload, PROCUREMENT)


def create_po_fresh(cycle_id, quote_id, print_quantity, digital_seat_count=0) -> dict:
    return get_success_data(create_purchase_order(
        cycle_id, quote_id, print_quantity, digital_seat_count))


def issue_po(po_id) -> dict:
    return get_success_data(api_client.issue_purchase_order(po_id, PROCUREMENT))


def receive_po(po_id, qty_received) -> dict:
    resp = api_client.receive_purchase_order(po_id, {"qty_received": qty_received},
                                             WAREHOUSE)
    return get_success_data(resp)


def pay_po(po_id, amount) -> dict:
    resp = api_client.pay_purchase_order(po_id, {"amount": amount}, PROCUREMENT)
    return get_success_data(resp)


def cancel_po(po_id) -> dict:
    return get_success_data(api_client.cancel_purchase_order(po_id, PROCUREMENT))


def close_po(po_id) -> dict:
    resp = api_client.transition_purchase_order(po_id, {"to_state": "CLOSED"},
                                                PROCUREMENT)
    return get_success_data(resp)


def get_ledger(cycle_id) -> dict:
    """The cycle's budget ledger (endpoint returns an array of length 0 or 1)."""
    data = get_success_data(api_client.get_budget_ledger(cycle_id, PROCUREMENT))
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one ledger row for cycle {cycle_id}, got {data!r}"
    )
    return data[0]


def get_lot(material_id) -> dict:
    """The material's inventory lot (endpoint returns an array of length 0/1)."""
    data = get_success_data(api_client.get_inventory_lots(material_id, WAREHOUSE))
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one lot for material {material_id}, got {data!r}"
    )
    return data[0]


def create_distribution_order(material_id, **overrides) -> dict:
    payload = create_distribution_order_payload(material_id=material_id, **overrides)
    resp = api_client.create_distribution_order(payload, WAREHOUSE)
    return get_success_data(resp)


def transition_distribution_order(do_id, to_state) -> dict:
    resp = api_client.transition_distribution_order(do_id, {"to_state": to_state},
                                                    WAREHOUSE)
    return get_success_data(resp)


def list_material_distribution_orders(material_id) -> list:
    """All distribution orders targeting the material (paginated read)."""
    data, _ = validate_paginated(
        api_client.list_material_distribution_orders(material_id, WAREHOUSE))
    return data


def get_distribution_order(do_id, material_id) -> dict:
    """Read one distribution order via the material-scoped list endpoint."""
    for order in list_material_distribution_orders(material_id):
        if order["id"] == do_id:
            return order
    raise AssertionError(f"distribution order {do_id} not found for material "
                         f"{material_id}")


def create_supplemental_request(cycle_id, requester_id, **overrides) -> dict:
    payload = create_supplemental_request_payload(cycle_id=cycle_id, **overrides)
    resp = api_client.create_supplemental_request(
        payload, make_teacher_headers(requester_id))
    return get_success_data(resp)


def transition_supplemental_request(sr_id, to_state, specialist_id="spec1") -> dict:
    resp = api_client.transition_supplemental_request(
        sr_id, {"to_state": to_state},
        make_instructional_specialist_headers(specialist_id))
    return get_success_data(resp)


def create_challenge(target_type, target_id, grounds="CONTENT_OBJECTION",
                     filer_id="cm1") -> dict:
    payload = create_challenge_payload(target_type=target_type, target_id=target_id,
                                       grounds=grounds)
    resp = api_client.create_challenge(
        payload, make_community_member_headers(filer_id))
    return get_success_data(resp)


def transition_challenge(challenge_id, to_state, headers=None) -> dict:
    if headers is None:
        headers = DIRECTOR
    resp = api_client.transition_challenge(challenge_id, {"to_state": to_state},
                                           headers)
    return get_success_data(resp)


def cast_vote(challenge_id, voter_id, vote) -> dict:
    resp = api_client.cast_vote(challenge_id, create_vote_payload(vote=vote),
                                make_committee_member_headers(voter_id))
    return get_success_data(resp)


def decide_challenge(challenge_id, decider_id="v1") -> dict:
    return transition_challenge(
        challenge_id, "DECIDED", make_committee_member_headers(decider_id))


# ---------------------------------------------------------------------------
# Tier 1-3: state progression and entity hierarchy composites
# ---------------------------------------------------------------------------

def setup_cycle_in_pilot_open(*, enrollment=100, award_method=None,
                              subject_area="MATHEMATICS", grade_band="K_5",
                              school_year_start=2027, standards_required_count=1,
                              mappings=(("S1", "FULL"),),
                              framework_code="FW-MATH-K5",
                              title="Math Text", publisher_name="PubA") -> dict:
    """Framework + cycle + one VETTED material carrying the given alignment
    mappings + cycle driven DRAFT -> ALIGNMENT_REVIEW -> PILOT_OPEN."""
    framework = create_framework(
        code=framework_code, subject_area=subject_area, grade_band=grade_band,
        standards_required_count=standards_required_count)
    cycle_overrides = {}
    if award_method is not None:
        cycle_overrides["award_method"] = award_method
    cycle = create_cycle(framework["id"], subject_area=subject_area,
                         grade_band=grade_band,
                         school_year_start=school_year_start,
                         district_enrollment=enrollment, **cycle_overrides)
    material = create_material(cycle["id"], title=title,
                               publisher_name=publisher_name)
    vet_material(material["id"])
    for standard_code, rating in mappings:
        upsert_alignment(material["id"], standard_code=standard_code,
                         coverage_rating=rating)
    transition_cycle(cycle["id"], "ALIGNMENT_REVIEW")
    cycle = transition_cycle(cycle["id"], "PILOT_OPEN")
    return {"framework": framework, "cycle": cycle, "material": material}


def setup_active_pilot(*, reviews=((4, 4, 4, 4),), teacher_count=1,
                       school_code="SCH-A", starts_on="2026-08-01",
                       ends_on="2026-08-15", **kwargs) -> dict:
    """setup_cycle_in_pilot_open + one ACTIVE pilot + the given SUBMITTED
    reviews (submitted by teachers t1, t2, ... in order)."""
    ctx = setup_cycle_in_pilot_open(**kwargs)
    pilot = create_pilot(ctx["cycle"]["id"], ctx["material"]["id"],
                         school_code=school_code, starts_on=starts_on,
                         ends_on=ends_on, teacher_count=teacher_count)
    transition_pilot(pilot["id"], "ACTIVE")
    submitted = [submit_review(pilot["id"], f"t{i + 1}", scores)
                 for i, scores in enumerate(reviews)]
    ctx.update({"pilot": get_pilot(pilot["id"]), "reviews": submitted})
    return ctx


def setup_cycle_in_scoring(**kwargs) -> dict:
    """Active pilot + reviews, then the pilot CLOSED and the cycle moved
    PILOT_OPEN -> SCORING (computes official_composite / participation_rate)."""
    ctx = setup_active_pilot(**kwargs)
    transition_pilot(ctx["pilot"]["id"], "CLOSED")
    ctx["cycle"] = transition_cycle(ctx["cycle"]["id"], "SCORING")
    return ctx


def setup_cycle_board_pending(*, close_clock=DEFAULT_BOARD_CLOCK, **kwargs) -> dict:
    """Cycle through SCORING and PUBLIC_REVIEW into BOARD_PENDING (the clock
    is advanced past the 30-day review window before closing it)."""
    ctx = setup_cycle_in_scoring(**kwargs)
    transition_cycle(ctx["cycle"]["id"], "PUBLIC_REVIEW")
    set_clock(close_clock)
    ctx["cycle"] = transition_cycle(ctx["cycle"]["id"], "BOARD_PENDING")
    return ctx


def setup_cycle_adopted(**kwargs) -> dict:
    """Cycle in BOARD_PENDING, then a board ADOPT decision on the material
    (cycle ADOPTED, material ADOPTED)."""
    ctx = setup_cycle_board_pending(**kwargs)
    resp = api_client.board_decision(
        ctx["cycle"]["id"],
        {"material_id": ctx["material"]["id"], "decision": "ADOPT"}, SECRETARY)
    ctx["cycle"] = get_success_data(resp)
    ctx["material"] = get_material(ctx["material"]["id"])
    return ctx


def setup_cycle_procuring(*, quote_specs=(
        {"publisher_name": "PubA", "print_unit_price": 10.00, "print_quantity": 10,
         "digital_seat_rate": 0, "digital_seat_count": 0, "training_sessions": 0,
         "license_years": 0},
        {"publisher_name": "PubB", "print_unit_price": 12.00, "print_quantity": 10,
         "digital_seat_rate": 0, "digital_seat_count": 0, "training_sessions": 0,
         "license_years": 0},
), winner_index=0, appropriation=1000, **kwargs) -> dict:
    """ADOPTED cycle + the given quotes evaluated to UNDER_EVALUATION + an
    award posted for quote_specs[winner_index] + one appropriation posted.
    Returns the context with quotes, selected_quote, and ledger keys."""
    ctx = setup_cycle_adopted(**kwargs)
    quotes = [create_quote(ctx["cycle"]["id"], ctx["material"]["id"], **spec)
              for spec in quote_specs]
    for quote in quotes:
        evaluate_quote(quote["id"])
    award_quote_fresh(ctx["cycle"]["id"], quotes[winner_index]["id"])
    ledger = post_appropriation(ctx["cycle"]["id"], appropriation)
    ctx.update({
        "quotes": [get_quote(q["id"]) for q in quotes],
        "selected_quote": get_quote(quotes[winner_index]["id"]),
        "ledger": ledger,
        "cycle": get_cycle(ctx["cycle"]["id"]),
    })
    return ctx


def setup_cycle_distributing(*, po_print_quantity=10, po_digital_seat_count=0,
                             receive_qty=None, **kwargs) -> dict:
    """PROCURING + one PO created, issued, and (by default fully) received —
    the first receipt auto-advances the cycle to DISTRIBUTING and creates the
    material's inventory lot."""
    ctx = setup_cycle_procuring(**kwargs)
    po = create_po_fresh(ctx["cycle"]["id"], ctx["selected_quote"]["id"],
                         po_print_quantity, po_digital_seat_count)
    issue_po(po["id"])
    if receive_qty is None:
        receive_qty = po_print_quantity
    receive_po(po["id"], receive_qty)
    ctx.update({"po": get_purchase_order(po["id"]),
                "lot": get_lot(ctx["material"]["id"]),
                "cycle": get_cycle(ctx["cycle"]["id"])})
    return ctx


# ---------------------------------------------------------------------------
# Tier 3.5: two-candidate slate (two VETTED materials, one pilot each)
# ---------------------------------------------------------------------------

def setup_two_candidate_cycle(*, m1_reviews=((4, 4, 4, 4),),
                              m2_reviews=((4, 4, 4, 4),),
                              teacher_count=1,
                              close_clock=DEFAULT_BOARD_CLOCK) -> dict:
    """One cycle holding two VETTED, fully aligned materials, each with its
    own pilot (SCH-A / SCH-B) carrying the given reviews; both pilots CLOSED;
    cycle in BOARD_PENDING. Returns m1, m2, p1, p2 plus framework/cycle.

    Both materials must be submitted (and vetted and mapped) while the cycle
    is still DRAFT/ALIGNMENT_REVIEW — PRD §3.2 restricts material submission
    to those two statuses — so the slate is assembled BEFORE the cycle is
    driven to PILOT_OPEN."""
    framework = create_framework()
    cycle = create_cycle(framework["id"])
    cycle_id = cycle["id"]
    m1 = create_material(cycle_id, title="Math Text", publisher_name="PubA")
    vet_material(m1["id"])
    upsert_alignment(m1["id"], standard_code="S1", coverage_rating="FULL")
    m2 = create_material(cycle_id, title="Math Text 2", publisher_name="PubB")
    vet_material(m2["id"])
    upsert_alignment(m2["id"], standard_code="S1", coverage_rating="FULL")
    transition_cycle(cycle_id, "ALIGNMENT_REVIEW")
    transition_cycle(cycle_id, "PILOT_OPEN")
    p1 = create_pilot(cycle_id, m1["id"], school_code="SCH-A",
                      teacher_count=teacher_count)
    p2 = create_pilot(cycle_id, m2["id"], school_code="SCH-B",
                      teacher_count=teacher_count)
    transition_pilot(p1["id"], "ACTIVE")
    transition_pilot(p2["id"], "ACTIVE")
    for i, scores in enumerate(m1_reviews):
        submit_review(p1["id"], f"t1-{i}", scores)
    for i, scores in enumerate(m2_reviews):
        submit_review(p2["id"], f"t2-{i}", scores)
    transition_pilot(p1["id"], "CLOSED")
    transition_pilot(p2["id"], "CLOSED")
    transition_cycle(cycle_id, "SCORING")
    transition_cycle(cycle_id, "PUBLIC_REVIEW")
    set_clock(close_clock)
    transition_cycle(cycle_id, "BOARD_PENDING")
    return {"framework": framework, "cycle": get_cycle(cycle_id),
            "material": get_material(m1["id"]),
            "m1": get_material(m1["id"]), "m2": get_material(m2["id"]),
            "p1": p1, "p2": p2}


# ---------------------------------------------------------------------------
# Tier 4: challenge pipeline composites
# ---------------------------------------------------------------------------

def file_material_challenge(material_id, filer_id="cm1",
                            grounds="CONTENT_OBJECTION") -> dict:
    return create_challenge("MATERIAL", material_id, grounds=grounds,
                            filer_id=filer_id)


def advance_challenge_to_committee_review(challenge_id) -> dict:
    transition_challenge(challenge_id, "SCREENING")
    return transition_challenge(challenge_id, "COMMITTEE_REVIEW")


def cast_votes(challenge_id, votes) -> list:
    """votes: iterable of (voter_id, vote) pairs cast in order."""
    return [cast_vote(challenge_id, voter, vote) for voter, vote in votes]


def setup_decided_material_challenge(*, votes=(("v1", "UPHOLD"),
                                               ("v2", "UPHOLD"),
                                               ("v3", "REMOVE")),
                                     filer_id="cm1",
                                     grounds="CONTENT_OBJECTION",
                                     **kwargs) -> dict:
    """ADOPTED material + a challenge filed against it, advanced to
    COMMITTEE_REVIEW, voted on, and DECIDED. Returns the adoption context
    plus the challenge."""
    ctx = setup_cycle_adopted(**kwargs)
    challenge = file_material_challenge(ctx["material"]["id"], filer_id=filer_id,
                                        grounds=grounds)
    advance_challenge_to_committee_review(challenge["id"])
    cast_votes(challenge["id"], votes)
    challenge = decide_challenge(challenge["id"])
    ctx["challenge"] = challenge
    ctx["material"] = get_material(ctx["material"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: full-lifecycle terminal-state composite
# ---------------------------------------------------------------------------

def setup_cycle_active(*, appropriation=2000, quote_unit_price=10.00,
                       po_print_quantity=100, **kwargs) -> dict:
    """Full lifecycle: adopted -> awarded -> appropriated -> PO issued,
    fully received, fully paid, CLOSED -> cycle DISTRIBUTING -> ACTIVE.
    The ledger's expended_total equals the PO total afterwards."""
    quote_specs = (
        {"publisher_name": "PubA", "print_unit_price": quote_unit_price,
         "print_quantity": po_print_quantity, "digital_seat_rate": 0,
         "digital_seat_count": 0, "training_sessions": 0, "license_years": 0},
        {"publisher_name": "PubB", "print_unit_price": quote_unit_price + 2.00,
         "print_quantity": po_print_quantity, "digital_seat_rate": 0,
         "digital_seat_count": 0, "training_sessions": 0, "license_years": 0},
    )
    ctx = setup_cycle_procuring(quote_specs=quote_specs, winner_index=0,
                                appropriation=appropriation, **kwargs)
    po = create_po_fresh(ctx["cycle"]["id"], ctx["selected_quote"]["id"],
                         po_print_quantity)
    issue_po(po["id"])
    receive_po(po["id"], po_print_quantity)
    pay_po(po["id"], po["total_amount"])
    close_po(po["id"])
    ctx["cycle"] = transition_cycle(ctx["cycle"]["id"], "ACTIVE")
    ctx.update({"po": get_purchase_order(po["id"]),
                "ledger": get_ledger(ctx["cycle"]["id"])})
    return ctx

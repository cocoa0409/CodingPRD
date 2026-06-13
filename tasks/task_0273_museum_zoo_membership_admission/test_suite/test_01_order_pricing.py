"""Order pricing: provisional-vs-final divergence, nested per-ticket pricing,
per-component rounding, reciprocal pricing, and member surcharge waiver.

All expected totals are integer cents and copied verbatim from the design index.
"""
from test_helpers import (
    validate_success,
    fixtures as fx,
    make_patron_headers,
)


def test_provisional_and_final_total_agree_when_member_active_at_confirm(api):
    """PRD §3.5: "A MEMBER ticket is quoted at the plan's member_admission_cents
    even when the linked membership is not yet ACTIVE - the quote optimistically
    assumes the membership will be active by confirmation."
    PRD §3.6: "a MEMBER ticket is priced at the plan's member_admission_cents."

    With the membership already ACTIVE at confirm, the provisional quote and the
    final total agree: 1 MEMBER @1500 + 1 NON_MEMBER @2500 == 4000.

    Design: Difficulty/dual_variant_calc/order_total_provisional_vs_final_diverge_on_member_pricing
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, _ = fx.setup_active_membership_simple(
        plan_overrides={"tier": "HOUSEHOLD", "member_admission_cents": 1500},
    )
    membership_id = _membership_id_of(api, patron["id"])
    slot = fx.create_slot(non_member_admission_cents=2500)
    order = fx.create_draft_order(patron["id"], slot["id"], membership_id=membership_id)
    fx.add_ticket(order["id"], patron["id"], "MEMBER", "P One")
    fx.add_ticket(order["id"], patron["id"], "NON_MEMBER", "Guest A")

    draft = fx.get_order(order["id"], patron["id"])
    assert draft["quoted_total_cents"] == 4000, \
        f"provisional quote should be 4000, got {draft['quoted_total_cents']}"

    confirmed = fx.confirm_order(order["id"], patron["id"])
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["final_total_cents"] == 4000, \
        f"final total should be 4000, got {confirmed['final_total_cents']}"


def test_final_total_locked_at_confirm_equals_quote_member_plus_nonmember(api):
    """PRD §3.6: "final_total_cents is that subtotal plus the order's
    donation_cents." PRD §3.6: "a MEMBER ticket is priced at the plan's
    member_admission_cents" and "a NON_MEMBER ticket is priced at the slot's
    non_member_admission_cents."

    Second test of the dual-variant order: confirm locks final_total_cents at
    1500 + 2500 == 4000 and the order becomes CONFIRMED.

    Design: Difficulty/dual_variant_calc/order_total_provisional_vs_final_diverge_on_member_pricing
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, _ = fx.setup_active_membership_simple(
        plan_overrides={"tier": "HOUSEHOLD", "member_admission_cents": 1500},
    )
    membership_id = _membership_id_of(api, patron["id"])
    slot = fx.create_slot(non_member_admission_cents=2500)
    order = fx.build_confirmed_order(
        patron["id"], slot["id"],
        [{"ticket_type": "MEMBER", "person_name": "P One"},
         {"ticket_type": "NON_MEMBER", "person_name": "Guest A"}],
        order_overrides={"membership_id": membership_id},
    )
    assert order["status"] == "CONFIRMED"
    assert order["final_total_cents"] == 4000, \
        f"final total should be 4000, got {order['final_total_cents']}"


def test_nested_member_nonmember_reciprocal_with_surcharge_and_donation(api):
    """PRD §3.6: "For a GUEST, NON_MEMBER, or RECIPROCAL ticket the surcharge is
    the exhibit's full surcharge_cents. For a MEMBER ticket the surcharge depends
    on the plan: ... otherwise it is the exhibit's surcharge_cents multiplied by
    one minus the exhibit's member_surcharge_discount_pct, rounded half-up to
    whole cents."
    PRD §3.6: "a RECIPROCAL ticket is priced at ... the slot's
    non_member_admission_cents times one minus the partner's discount_pct,
    rounded half-up to whole cents, when the partner's benefit_type is DISCOUNT."

    MEMBER 1500 + round_half_up(1000*0.75)=750 -> 2250; NON_MEMBER 2500 + 1000
    -> 3500; RECIPROCAL round_half_up(2500*0.5)=1250 + 1000 -> 2250; subtotal
    8000 + donation 500 == 8500.

    Design: Difficulty/combinatorial_formula/order_total_nested_branch_member_nonmember_reciprocal_with_surcharge
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, _ = fx.setup_active_membership_simple(
        plan_overrides={"tier": "HOUSEHOLD", "member_admission_cents": 1500,
                        "exhibit_surcharge_waived": False},
    )
    membership_id = _membership_id_of(api, patron["id"])
    slot = fx.create_slot(non_member_admission_cents=2500)
    exhibit = fx.create_exhibit(name="Dinosaurs", surcharge_cents=1000,
                                member_surcharge_discount_pct=0.25, buffer_minutes=0)
    session = fx.create_session(exhibit["id"])
    partner = fx.create_partner(org_name="Sister Museum", benefit_type="DISCOUNT", discount_pct=0.5)

    order = fx.build_confirmed_order(
        patron["id"], slot["id"],
        [{"ticket_type": "MEMBER", "person_name": "P Three"},
         {"ticket_type": "NON_MEMBER", "person_name": "Guest B"},
         {"ticket_type": "RECIPROCAL", "person_name": "Guest C",
          "reciprocal_partner_id": partner["id"]}],
        order_overrides={"membership_id": membership_id,
                         "exhibit_session_id": session["id"],
                         "donation_cents": 500},
    )
    assert order["status"] == "CONFIRMED"
    assert order["final_total_cents"] == 8500, \
        f"final total should be 8500, got {order['final_total_cents']}"


def test_surcharge_rounded_per_ticket_then_summed_yields_odd_cent(api):
    """PRD §2.6: "this rounding is applied at each such per-component
    multiplication, never deferred to the final sum. Per-ticket prices are
    therefore whole-cent values before they are summed, and the order's admission
    subtotal is the plain sum of those already-rounded per-ticket prices."

    surcharge 1000, member_surcharge_discount_pct 0.3333: per MEMBER ticket
    base 1500 + round_half_up(1000*0.6667)=667 -> 2167; 3 tickets -> 6501.
    (sum-then-discount would give 6500; per-ticket rounding pins 6501.)

    Design: Difficulty/combinatorial_formula/surcharge_rounding_per_ticket_then_sum_not_sum_then_discount
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, _ = fx.setup_active_membership_simple(
        plan_overrides={"tier": "HOUSEHOLD", "member_admission_cents": 1500,
                        "exhibit_surcharge_waived": False},
    )
    membership_id = _membership_id_of(api, patron["id"])
    slot = fx.create_slot(non_member_admission_cents=2500)
    exhibit = fx.create_exhibit(name="Frogs", surcharge_cents=1000,
                                member_surcharge_discount_pct=0.3333, buffer_minutes=0)
    session = fx.create_session(exhibit["id"])

    order = fx.build_confirmed_order(
        patron["id"], slot["id"],
        [{"ticket_type": "MEMBER", "person_name": "A"},
         {"ticket_type": "MEMBER", "person_name": "B"},
         {"ticket_type": "MEMBER", "person_name": "C"}],
        order_overrides={"membership_id": membership_id,
                         "exhibit_session_id": session["id"]},
    )
    assert order["final_total_cents"] == 6501, \
        f"final total should be 6501 (per-ticket rounding), got {order['final_total_cents']}"


def test_per_component_rounding_is_observable_at_quote_too(api):
    """PRD §3.5: "To each ticket's base the system adds the special-exhibit
    surcharge as described in Section 3.6, sums the per-ticket prices after their
    individual rounding, and adds donation_cents to reach the quote."

    Second test of per-ticket-then-sum rounding: the same 3-MEMBER scenario shows
    the provisional quote already carries the odd-cent 6501.

    Design: Difficulty/combinatorial_formula/surcharge_rounding_per_ticket_then_sum_not_sum_then_discount
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, _ = fx.setup_active_membership_simple(
        plan_overrides={"tier": "HOUSEHOLD", "member_admission_cents": 1500,
                        "exhibit_surcharge_waived": False},
    )
    membership_id = _membership_id_of(api, patron["id"])
    slot = fx.create_slot(non_member_admission_cents=2500)
    exhibit = fx.create_exhibit(name="Frogs2", surcharge_cents=1000,
                                member_surcharge_discount_pct=0.3333, buffer_minutes=0)
    session = fx.create_session(exhibit["id"])

    draft = fx.build_draft_order_with_tickets(
        patron["id"], slot["id"],
        [{"ticket_type": "MEMBER", "person_name": "A"},
         {"ticket_type": "MEMBER", "person_name": "B"},
         {"ticket_type": "MEMBER", "person_name": "C"}],
        order_overrides={"membership_id": membership_id,
                         "exhibit_session_id": session["id"]},
    )
    assert draft["quoted_total_cents"] == 6501, \
        f"provisional quote should be 6501, got {draft['quoted_total_cents']}"


def test_nested_branch_second_reading_via_confirmed_status(api):
    """PRD §3.6: "The order's admission subtotal is the sum of the per-ticket
    price_cents after that per-ticket rounding, and final_total_cents is that
    subtotal plus the order's donation_cents."

    Second test of the combinatorial-formula order: re-asserts the 8500 final
    total and that the order reaches CONFIRMED.

    Design: Difficulty/combinatorial_formula/order_total_nested_branch_member_nonmember_reciprocal_with_surcharge
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, _ = fx.setup_active_membership_simple(
        plan_overrides={"tier": "HOUSEHOLD", "member_admission_cents": 1500,
                        "exhibit_surcharge_waived": False},
    )
    membership_id = _membership_id_of(api, patron["id"])
    slot = fx.create_slot(non_member_admission_cents=2500)
    exhibit = fx.create_exhibit(name="Dinos2", surcharge_cents=1000,
                                member_surcharge_discount_pct=0.25, buffer_minutes=0)
    session = fx.create_session(exhibit["id"])
    partner = fx.create_partner(org_name="Sister2", benefit_type="DISCOUNT", discount_pct=0.5)

    draft = fx.build_draft_order_with_tickets(
        patron["id"], slot["id"],
        [{"ticket_type": "MEMBER", "person_name": "P"},
         {"ticket_type": "NON_MEMBER", "person_name": "N"},
         {"ticket_type": "RECIPROCAL", "person_name": "R",
          "reciprocal_partner_id": partner["id"]}],
        order_overrides={"membership_id": membership_id,
                         "exhibit_session_id": session["id"],
                         "donation_cents": 500},
    )
    confirmed = fx.confirm_order(draft["id"], patron["id"])
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["final_total_cents"] == 8500


def test_reciprocal_free_ticket_priced_zero(api):
    """PRD §3.6: "a RECIPROCAL ticket is priced at 0 when its partner's
    benefit_type is FREE."

    A single FREE-partner RECIPROCAL ticket with no donation yields
    final_total_cents == 0.

    Design: Corner/calculations/reciprocal_free_ticket_priced_zero
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    patron = fx.create_patron()
    partner = fx.create_partner(org_name="Free Partner", benefit_type="FREE")
    slot = fx.create_slot(non_member_admission_cents=2500)
    order = fx.build_confirmed_order(
        patron["id"], slot["id"],
        [{"ticket_type": "RECIPROCAL", "person_name": "Recip",
          "reciprocal_partner_id": partner["id"]}],
    )
    assert order["final_total_cents"] == 0, \
        f"FREE reciprocal ticket should price the order at 0, got {order['final_total_cents']}"


def test_member_exhibit_surcharge_fully_waived_when_plan_flag_set(api):
    """PRD §3.6: "For a MEMBER ticket the surcharge depends on the plan: if the
    plan's exhibit_surcharge_waived is true the surcharge is 0."

    With exhibit_surcharge_waived=true, a MEMBER ticket on an exhibit session
    pays only member_admission_cents (1500); final_total_cents == 1500.

    Design: Corner/calculations/member_exhibit_surcharge_fully_waived_when_plan_flag_set
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan, patron, _ = fx.setup_active_membership_simple(
        plan_overrides={"tier": "PATRON_CIRCLE", "member_admission_cents": 1500,
                        "exhibit_surcharge_waived": True},
    )
    membership_id = _membership_id_of(api, patron["id"])
    slot = fx.create_slot(non_member_admission_cents=2500)
    exhibit = fx.create_exhibit(name="Reptiles", surcharge_cents=1000,
                                member_surcharge_discount_pct=0.25, buffer_minutes=0)
    session = fx.create_session(exhibit["id"])
    order = fx.build_confirmed_order(
        patron["id"], slot["id"],
        [{"ticket_type": "MEMBER", "person_name": "WV"}],
        order_overrides={"membership_id": membership_id, "exhibit_session_id": session["id"]},
    )
    assert order["final_total_cents"] == 1500, \
        f"waived surcharge should leave 1500, got {order['final_total_cents']}"


# ─── local helper ─────────────────────────────────────────────────────

def _membership_id_of(api, patron_id):
    """Find the (single) membership of a patron via the admin list endpoint."""
    data = validate_success(
        api.list_memberships(fx.ADMIN, {"primary_patron_id": patron_id})
    )
    assert len(data) >= 1, "expected at least one membership for patron"
    return data[0]["id"]

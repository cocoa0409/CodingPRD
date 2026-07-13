"""The offer cycle: creation guards, the accept occupancy cascade, and refusal."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_applicant_headers,
)
from test_helpers.fixtures import (
    create_applicant, add_member, create_waitlist, enroll, draw, create_unit,
    create_offer, setup_drawn_active_entry, setup_active_tenancy,
)

IC = TEST_USERS["intake_clerk_headers"]
HS = TEST_USERS["housing_specialist_headers"]
PM = TEST_USERS["property_manager_headers"]


def _entry(api, waitlist_id, entry_id):
    data, _meta = validate_paginated(api.list_entries(waitlist_id, IC))
    return next(e for e in data if e["id"] == entry_id)


# ---------------------------------------------------------------------------
# transitive_cascade / offer_accept_occupancy_chain
# ---------------------------------------------------------------------------
def _setup_two_waitlist_applicant(api):
    app = create_applicant(api, "Chain")
    add_member(api, app["id"], full_name="Head C", relationship="HEAD", annual_income_cents=2400000)
    wl1 = create_waitlist(api, bedroom_size=2, site_name="Site A")
    wl2 = create_waitlist(api, bedroom_size=2, site_name="Site B")
    e1 = enroll(api, wl1["id"], app["id"])
    e2 = enroll(api, wl2["id"], app["id"])
    draw(api, wl1["id"])
    draw(api, wl2["id"])
    unit = create_unit(api, bedroom_size=2)
    offer = create_offer(api, e1["id"], unit["id"])
    return app, wl1, wl2, e1, e2, unit, offer


def test_accept_creates_tenancy_and_occupies_unit(api):
    """PRD §3.4: "a new Tenancy is created in ACTIVE for the entry's applicant and
    the offered unit, with lease_start_date set from the logical clock; ... the unit
    moves from OFFERED to OCCUPIED".

    Design: Difficulty/transitive_cascade/offer_accept_occupancy_chain
    """
    app, wl1, wl2, e1, e2, unit, offer = _setup_two_waitlist_applicant(api)
    tenancy = validate_success(api.accept_offer(offer["id"], make_applicant_headers(app["id"])),
                               expected_status=201)
    assert tenancy["status"] == "ACTIVE"
    assert tenancy["unit_id"] == unit["id"]
    accepted = get_success_data(api.get_offer(offer["id"], HS))
    assert accepted["status"] == "ACCEPTED"
    unit_after = get_success_data(api.get_unit(unit["id"], HS))
    assert unit_after["status"] == "OCCUPIED", "the accepted unit must become OCCUPIED"


def test_accept_houses_entry_applicant_and_withdraws_sibling(api):
    """PRD §3.4: "the accepting waitlist entry moves from OFFERED to HOUSED; the
    applicant moves from WAITLISTED to HOUSED; and that applicant's other still-in-play
    entries are withdrawn as described in §3.3."

    Design: Difficulty/transitive_cascade/offer_accept_occupancy_chain
    """
    app, wl1, wl2, e1, e2, unit, offer = _setup_two_waitlist_applicant(api)
    get_success_data(api.accept_offer(offer["id"], make_applicant_headers(app["id"])))
    assert _entry(api, wl1["id"], e1["id"])["status"] == "HOUSED"
    assert get_success_data(api.get_applicant(app["id"], IC))["status"] == "HOUSED"
    assert _entry(api, wl2["id"], e2["id"])["status"] == "WITHDRAWN", \
        "the applicant's competing entry must be withdrawn once housed"


# ---------------------------------------------------------------------------
# compensating_invariant / offer_refuse_conserves_unit_availability
# ---------------------------------------------------------------------------
def test_refuse_releases_unit_and_returns_entry_active(api):
    """PRD §3.4: "Refusing sets the offer to REFUSED, releases the reserved unit from
    OFFERED back to AVAILABLE, and resolves the waitlist entry by the refusal-limit
    rule: the entry's refusal_count is incremented by one, and ... otherwise the entry
    returns to ACTIVE".

    Design: Difficulty/compensating_invariant/offer_refuse_conserves_unit_availability
    """
    ctx = setup_drawn_active_entry(api, applicant_name="Cons1")
    unit = create_unit(api, bedroom_size=2)
    offer = create_offer(api, ctx["entry_id"], unit["id"])
    get_success_data(api.refuse_offer(offer["id"], make_applicant_headers(ctx["applicant"]["id"])))
    assert get_success_data(api.get_unit(unit["id"], HS))["status"] == "AVAILABLE"
    entry = _entry(api, ctx["waitlist"]["id"], ctx["entry_id"])
    assert entry["status"] == "ACTIVE"
    assert entry["refusal_count"] == 1


def test_refuse_creates_no_tenancy(api):
    """PRD §3.4: "Refusing sets the offer to REFUSED, releases the reserved unit from
    OFFERED back to AVAILABLE" (no tenancy is created by a refusal).

    Design: Difficulty/compensating_invariant/offer_refuse_conserves_unit_availability
    """
    ctx = setup_drawn_active_entry(api, applicant_name="Cons1b")
    unit = create_unit(api, bedroom_size=2)
    offer = create_offer(api, ctx["entry_id"], unit["id"])
    get_success_data(api.refuse_offer(offer["id"], make_applicant_headers(ctx["applicant"]["id"])))
    data, meta = validate_paginated(api.list_tenancies(HS, params={"unit_id": unit["id"]}))
    assert meta["total_count"] == 0, "a refusal must not create a tenancy on the released unit"


# ---------------------------------------------------------------------------
# boundary_precision_check / refusal_limit_third_refusal_purges
# ---------------------------------------------------------------------------
def test_second_refusal_keeps_entry_active(api):
    """PRD §3.4: "if the incremented count reaches 3 or more the entry is PURGED and
    removed from ranking, otherwise the entry returns to ACTIVE ... In other words the
    third refusal purges the entry while the second does not."

    Design: Difficulty/boundary_precision_check/refusal_limit_third_refusal_purges
    """
    ctx = setup_drawn_active_entry(api, applicant_name="Refuser")
    unit = create_unit(api, bedroom_size=2)
    app_headers = make_applicant_headers(ctx["applicant"]["id"])
    for _ in range(2):
        offer = create_offer(api, ctx["entry_id"], unit["id"])
        get_success_data(api.refuse_offer(offer["id"], app_headers))
    entry = _entry(api, ctx["waitlist"]["id"], ctx["entry_id"])
    assert entry["refusal_count"] == 2
    assert entry["status"] == "ACTIVE", "the second refusal must not purge the entry"


def test_third_refusal_purges_entry(api):
    """PRD §3.4: "the entry's refusal_count is incremented by one, and if the
    incremented count reaches 3 or more the entry is PURGED and removed from ranking".

    Design: Difficulty/boundary_precision_check/refusal_limit_third_refusal_purges
    """
    ctx = setup_drawn_active_entry(api, applicant_name="Refuser3")
    unit = create_unit(api, bedroom_size=2)
    app_headers = make_applicant_headers(ctx["applicant"]["id"])
    for _ in range(3):
        offer = create_offer(api, ctx["entry_id"], unit["id"])
        get_success_data(api.refuse_offer(offer["id"], app_headers))
    entry = _entry(api, ctx["waitlist"]["id"], ctx["entry_id"])
    assert entry["refusal_count"] == 3
    assert entry["status"] == "PURGED", "the third refusal must purge the entry"
    assert get_success_data(api.get_unit(unit["id"], HS))["status"] == "AVAILABLE"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / offer_requires_unit_available
# ---------------------------------------------------------------------------
def test_offer_of_already_offered_unit_rejected(api):
    """PRD §3.4: "the unit must currently be AVAILABLE, or the offer is rejected with
    ERR_UNIT_NOT_AVAILABLE".

    Design: Difficulty/cross_entity_state_dependency/offer_requires_unit_available
    """
    app_a = create_applicant(api, "CE-A")
    app_b = create_applicant(api, "CE-B")
    wl = create_waitlist(api, bedroom_size=2)
    entry_a = enroll(api, wl["id"], app_a["id"])
    entry_b = enroll(api, wl["id"], app_b["id"])
    draw(api, wl["id"])
    unit = create_unit(api, bedroom_size=2)
    create_offer(api, entry_a["id"], unit["id"])
    resp = api.create_offer(
        {"waitlist_entry_id": entry_b["id"], "unit_id": unit["id"], "expires_at": "2026-12-31T00:00:00Z"}, HS)
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_AVAILABLE)


def test_offer_of_already_offered_unit_leaves_unit_offered(api):
    """PRD §3.4: "creating it moves the unit from AVAILABLE to OFFERED" — a rejected
    second offer must not disturb the unit already reserved for the first entry.

    Design: Difficulty/cross_entity_state_dependency/offer_requires_unit_available
    """
    app_a = create_applicant(api, "CE-A2")
    app_b = create_applicant(api, "CE-B2")
    wl = create_waitlist(api, bedroom_size=2)
    entry_a = enroll(api, wl["id"], app_a["id"])
    entry_b = enroll(api, wl["id"], app_b["id"])
    draw(api, wl["id"])
    unit = create_unit(api, bedroom_size=2)
    create_offer(api, entry_a["id"], unit["id"])
    api.create_offer(
        {"waitlist_entry_id": entry_b["id"], "unit_id": unit["id"], "expires_at": "2026-12-31T00:00:00Z"}, HS)
    assert get_success_data(api.get_unit(unit["id"], HS))["status"] == "OFFERED", \
        "the unit stays reserved for the first entry"


# ---------------------------------------------------------------------------
# Corner instances
# ---------------------------------------------------------------------------
def test_accept_cascade_immediately_visible(api):
    """PRD §2.8: "every such cascade settles atomically inside the triggering request.
    The clearest example is offer acceptance, which in a single transaction accepts the
    offer, creates a tenancy and its initial draft certification, occupies the unit".

    Design: Corner/consistency_model/accept_immediate_cascade_visible_in_response
    """
    ctx = setup_drawn_active_entry(api, applicant_name="Imm")
    unit = create_unit(api, bedroom_size=2)
    offer = create_offer(api, ctx["entry_id"], unit["id"])
    tenancy = validate_success(api.accept_offer(offer["id"], make_applicant_headers(ctx["applicant"]["id"])),
                               expected_status=201)
    assert tenancy["status"] == "ACTIVE"
    assert tenancy["unit_id"] == unit["id"]
    assert get_success_data(api.get_unit(unit["id"], HS))["status"] == "OCCUPIED"


def test_refuse_accepted_offer_rejected(api):
    """PRD §3.4: "Refusal is likewise the owning Applicant's decision and is permitted
    only on a PENDING offer." (an ACCEPTED offer is terminal).

    Design: Corner/state_machines/refuse_accepted_offer_rejected
    """
    ctx = setup_active_tenancy(api, applicant_name="SM3")
    resp = api.refuse_offer(ctx["offer"]["id"], make_applicant_headers(ctx["applicant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

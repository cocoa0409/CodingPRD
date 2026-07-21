"""CITES permit lifecycle, revoke cascade, and listing compliance gates."""
from test_helpers import (
    validate_success, validate_error,
    setup_listed_bird, new_species, new_housing_cage, new_bird,
    approved_permit_for_species, qr_id_for_bird,
    create_permit_payload, TEST_USERS,
)

SM = TEST_USERS["store_manager_headers"]
STAFF = TEST_USERS["aviary_staff_headers"]
CO = TEST_USERS["compliance_officer_headers"]


def _cleared_bird_of_restricted_species(api):
    """Species II with an APPROVED-then-REVOKED permit (now RESTRICTED); one bird taken
    to CLEARED (but never listed). Returns (bird_id, species_id, permit_id)."""
    validate_success(api.set_clock("2026-07-01T00:00:00Z", SM), 200)
    sp = new_species("II")
    permit = approved_permit_for_species(sp["id"])
    cage = new_housing_cage(capacity=1)
    bird = new_bird(sp["id"])
    validate_success(api.start_quarantine(bird["id"], {"cage_id": cage["id"]}, STAFF), 200)
    qr_id = qr_id_for_bird(bird["id"])
    validate_success(api.set_clock("2026-07-16T00:00:00Z", SM), 200)
    validate_success(api.clear_quarantine(qr_id, STAFF), 200)
    validate_success(api.revoke_permit(permit["id"], CO), 200)  # species -> RESTRICTED
    return bird["id"], sp["id"], permit["id"]


# ── transitive_cascade: permit revoke depth-2 cascade ────────────────────────

def test_revoke_restricts_species_and_suspends_bird(api):
    """PRD 3.2: "An APPROVED permit can be revoked, moving it to the terminal REVOKED
    state and triggering the compliance cascade of Section 2.10: the owning Species
    becomes RESTRICTED, every LISTED bird of that species is moved to SUSPENDED, and
    listed_bird_count is recomputed downward."

    Design: Difficulty/transitive_cascade/permit_revoke_cascade_depth2
    """
    ctx = setup_listed_bird(cites_appendix="II")
    permit = validate_success(api.revoke_permit(ctx["permit"]["id"], CO), 200)
    assert permit["status"] == "REVOKED"
    sp = validate_success(api.get_species(ctx["species"]["id"], CO), 200)
    assert sp["status"] == "RESTRICTED"
    bird = validate_success(api.get_bird(ctx["bird"]["id"], STAFF), 200)
    assert bird["status"] == "SUSPENDED"


def test_revoke_decrements_listed_bird_count(api):
    """PRD 2.10: "the Species moves to RESTRICTED, every Bird of that species whose status
    is LISTED is moved to SUSPENDED, and the species' derived listed_bird_count is
    recomputed to reflect the birds that just left the listed population."

    Design: Difficulty/transitive_cascade/permit_revoke_cascade_depth2
    """
    ctx = setup_listed_bird(cites_appendix="II")
    before = validate_success(api.get_species(ctx["species"]["id"], CO), 200)
    assert before["listed_bird_count"] == 1
    validate_success(api.revoke_permit(ctx["permit"]["id"], CO), 200)
    after = validate_success(api.get_species(ctx["species"]["id"], CO), 200)
    assert after["listed_bird_count"] == 0


# ── cross_entity_state_dependency: listing vs species status ─────────────────

def test_list_cleared_bird_restricted_species_rejected(api):
    """PRD 3.4: "Listing is a compliance-gated action: the owning Species.status must be
    ACTIVE, else the request is rejected with ERR_SPECIES_RESTRICTED".

    Design: Difficulty/cross_entity_state_dependency/bird_listing_depends_on_species_status
    """
    bird_id, _sp_id, _p_id = _cleared_bird_of_restricted_species(api)
    res = api.list_bird_for_sale(bird_id, STAFF)
    validate_error(res, "ERR_SPECIES_RESTRICTED", expected_status=409)


def test_list_rejected_leaves_bird_cleared(api):
    """PRD 3.4: "the owning Species.status must be ACTIVE, else the request is rejected
    with ERR_SPECIES_RESTRICTED".

    Design: Difficulty/cross_entity_state_dependency/bird_listing_depends_on_species_status
    """
    bird_id, _sp_id, _p_id = _cleared_bird_of_restricted_species(api)
    validate_error(api.list_bird_for_sale(bird_id, STAFF), "ERR_SPECIES_RESTRICTED", expected_status=409)
    bird = validate_success(api.get_bird(bird_id, STAFF), 200)
    assert bird["status"] == "CLEARED"


# ── priority_pair_validation_conflict: state beats referential ───────────────

def test_list_intake_bird_returns_state_error_not_referential(api):
    """PRD 2.1: "When several checks could reject the same request, they are evaluated in
    a fixed priority sequence, and the first failing check determines the error returned."
    PRD 2.1: "(6) state-machine legality of the requested transition (ERR_INVALID_STATE and
    its domain-specific variants, HTTP 409)"
    PRD 3.4: "Once a bird is CLEARED, an AviaryStaff member can list it for sale, moving it
    from CLEARED to LISTED."

    Design: Difficulty/priority_pair_validation_conflict/list_state_beats_species_referential
    """
    validate_success(api.set_clock("2026-07-01T00:00:00Z", SM), 200)
    sp = new_species("II")
    permit = approved_permit_for_species(sp["id"])
    validate_success(api.revoke_permit(permit["id"], CO), 200)  # species RESTRICTED
    bird = new_bird(sp["id"])  # still INTAKE, never quarantined
    res = api.list_bird_for_sale(bird["id"], STAFF)
    # INTAKE is an illegal source state for list-for-sale -> state check (6) fires before
    # the referential species-restricted check (8).
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_list_intake_bird_unchanged(api):
    """PRD 2.1: "the first failing check determines the error returned."
    PRD 2.1: "(6) state-machine legality of the requested transition (ERR_INVALID_STATE and
    its domain-specific variants, HTTP 409)"

    Design: Difficulty/priority_pair_validation_conflict/list_state_beats_species_referential
    """
    validate_success(api.set_clock("2026-07-01T00:00:00Z", SM), 200)
    sp = new_species("II")
    permit = approved_permit_for_species(sp["id"])
    validate_success(api.revoke_permit(permit["id"], CO), 200)
    bird = new_bird(sp["id"])
    validate_error(api.list_bird_for_sale(bird["id"], STAFF), "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_bird(bird["id"], STAFF), 200)
    assert after["status"] == "INTAKE"


# ── corner: approving a lapsed permit ────────────────────────────────────────

def test_permit_approve_with_expired_valid_until_rejected(api):
    """PRD 3.2: "Approval requires the permit to be SUBMITTED and requires its valid_until
    to be strictly after the current logical clock; approving an already-lapsed permit is
    rejected with ERR_PERMIT_EXPIRED_INPUT (HTTP 400)."

    Design: Corner/state_machines/permit_approve_with_expired_valid_until_rejected
    """
    sp = new_species("III")
    permit = validate_success(api.create_permit(
        create_permit_payload(sp["id"], permit_number="CITES-400",
                              valid_until="2026-06-01T00:00:00Z"), CO), 201)
    validate_success(api.submit_permit(permit["id"], CO), 200)
    # clock is at the startup default 2026-07-01, already past valid_until 2026-06-01.
    res = api.approve_permit(permit["id"], CO)
    validate_error(res, "ERR_PERMIT_EXPIRED_INPUT", expected_status=400)
    after = validate_success(api.get_permit(permit["id"], CO), 200)
    assert after["status"] == "SUBMITTED"

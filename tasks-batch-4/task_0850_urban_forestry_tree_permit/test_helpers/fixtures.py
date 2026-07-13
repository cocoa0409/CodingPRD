"""Composite setup helpers for multi-step test prerequisites.

Every test runs against a fresh, empty database (the runner restarts the server before each
test), so every helper here builds its preconditions from scratch using only PRD-declared
endpoints. Helpers use get_success_data() (lenient) so setup failures surface as clear
"setup failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_zone_payload, create_species_payload, create_tree_payload,
    create_inspection_payload, create_permit_payload, create_contractor_payload,
    create_storm_event_payload, create_work_order_payload, create_dig_ticket_payload,
    review_payload, pay_fee_payload,
)
from .test_users import (
    TEST_USERS, APPLICANT_1, make_applicant_headers, make_contractor_headers,
)

ADMIN = TEST_USERS["forestry_admin_headers"]
STAFF = TEST_USERS["forestry_staff_headers"]
ARBORIST = TEST_USERS["arborist_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


# ─── Single-endpoint wrappers (return the data payload) ──────────────────
def set_clock(iso: str) -> None:
    get_success_data(api_client.set_clock({"to_iso8601": iso}, ADMIN))


def new_zone(**overrides) -> dict:
    return get_success_data(api_client.create_zone(create_zone_payload(**overrides), ADMIN))


def new_species(**overrides) -> dict:
    return get_success_data(api_client.create_species(create_species_payload(**overrides), ADMIN))


def new_tree(zone_id: str, species_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_tree(create_tree_payload(zone_id, species_id, **overrides), STAFF))


def new_inspection(tree_id: str, expected_tree_version: int, **overrides) -> dict:
    return get_success_data(api_client.create_inspection(
        tree_id, create_inspection_payload(expected_tree_version, **overrides), INSPECTOR))


def finalize(inspection_id: str) -> dict:
    return get_success_data(api_client.finalize_inspection(inspection_id, INSPECTOR))


def dispute(inspection_id: str) -> dict:
    return get_success_data(api_client.dispute_inspection(inspection_id, ADMIN))


def new_permit(tree_id: str, permit_type: str = "REMOVAL", reason: str = "decay",
               user_id: str = APPLICANT_1) -> dict:
    return get_success_data(api_client.create_permit(
        create_permit_payload(tree_id, permit_type=permit_type, reason=reason),
        make_applicant_headers(user_id)))


def submit(permit_id: str, user_id: str = APPLICANT_1) -> dict:
    return get_success_data(api_client.submit_permit(permit_id, make_applicant_headers(user_id)))


def review(permit_id: str, decision: str, mitigation_method: str = None,
           review_notes: str = "ok") -> dict:
    return get_success_data(api_client.review_permit(
        permit_id, review_payload(decision, mitigation_method, review_notes), ARBORIST))


def pay_fee(permit_id: str, amount_cents: int, user_id: str = APPLICANT_1) -> dict:
    return get_success_data(api_client.pay_fee(
        permit_id, pay_fee_payload(amount_cents), make_applicant_headers(user_id)))


def issue(permit_id: str) -> dict:
    return get_success_data(api_client.issue_permit(permit_id, ARBORIST))


def new_contractor(**overrides) -> dict:
    return get_success_data(api_client.create_contractor(create_contractor_payload(**overrides), ADMIN))


def new_storm(zone_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_storm_event(
        create_storm_event_payload(zone_id, **overrides), ADMIN))


def new_work_order(tree_id: str, contractor_id: str, work_type: str,
                   scheduled_start: str, scheduled_end: str, permit_id: str = None) -> dict:
    return get_success_data(api_client.create_work_order(
        create_work_order_payload(tree_id, contractor_id, work_type,
                                  scheduled_start, scheduled_end, permit_id=permit_id), STAFF))


def new_dig_ticket(work_order_id: str, contractor_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_dig_ticket(
        work_order_id, create_dig_ticket_payload(**overrides),
        make_contractor_headers(contractor_id)))


def mark_valid(dig_ticket_id: str) -> dict:
    return get_success_data(api_client.mark_valid_dig_ticket(dig_ticket_id, ADMIN))


def start_wo(work_order_id: str, contractor_id: str) -> dict:
    return get_success_data(
        api_client.start_work_order(work_order_id, make_contractor_headers(contractor_id)))


def complete_wo(work_order_id: str, contractor_id: str) -> dict:
    return get_success_data(
        api_client.complete_work_order(work_order_id, make_contractor_headers(contractor_id)))


# ─── Tier 1/2: base inventory scenarios ──────────────────────────────────
def setup_zone_species(zone_overrides=None, species_overrides=None):
    """Create a zone and a species. Returns (zone, species)."""
    zone = new_zone(**(zone_overrides or {}))
    species = new_species(**(species_overrides or {}))
    return zone, species


def setup_tree(dbh=20.0, condition_class="GOOD",
               zone_overrides=None, species_overrides=None, tree_overrides=None):
    """Zone + species + one tree. Returns (zone, species, tree)."""
    zone, species = setup_zone_species(zone_overrides, species_overrides)
    overrides = {"dbh_inches": dbh, "condition_class": condition_class}
    overrides.update(tree_overrides or {})
    tree = new_tree(zone["id"], species["id"], **overrides)
    return zone, species, tree


# ─── Tier 3: inspection lifecycle ────────────────────────────────────────
def setup_finalized_inspection_tree(dbh=20.0, condition_class="GOOD",
                                    likelihood=1, consequence=1, target=1,
                                    inspection_type="RISK",
                                    zone_overrides=None, species_overrides=None,
                                    tree_overrides=None):
    """Zone + species + tree + one FINALIZED inspection (benign by default). Returns
    (zone, species, tree, inspection). The tree's current_inspection_id points to a
    FINALIZED inspection, satisfying the REMOVAL-approve precondition."""
    zone, species, tree = setup_tree(dbh, condition_class, zone_overrides,
                                     species_overrides, tree_overrides)
    insp = new_inspection(tree["id"], tree["version"],
                          inspection_type=inspection_type,
                          likelihood_score=likelihood, consequence_score=consequence,
                          target_rating=target)
    finalize(insp["id"])
    return zone, species, tree, insp


# ─── Tier 3: permit lifecycle shortcuts ──────────────────────────────────
def setup_submitted_removal_permit(dbh=20.0, condition_class="GOOD", reason="decay",
                                   user_id=APPLICANT_1,
                                   zone_overrides=None, species_overrides=None):
    """Tree with FINALIZED inspection + a REMOVAL permit submitted (UNDER_REVIEW).
    Returns dict(zone, species, tree, inspection, permit)."""
    zone, species, tree, insp = setup_finalized_inspection_tree(
        dbh=dbh, condition_class=condition_class,
        zone_overrides=zone_overrides, species_overrides=species_overrides)
    permit = new_permit(tree["id"], permit_type="REMOVAL", reason=reason, user_id=user_id)
    submit(permit["id"], user_id=user_id)
    return {"zone": zone, "species": species, "tree": tree,
            "inspection": insp, "permit": permit}


def setup_approved_removal_permit(mitigation_method="REPLACEMENT_COST", dbh=20.0,
                                  condition_class="GOOD", user_id=APPLICANT_1,
                                  zone_overrides=None, species_overrides=None):
    """Full path to an APPROVED REMOVAL permit (fee computed, plantings created).
    Returns dict(zone, species, tree, inspection, permit) with permit reflecting APPROVE."""
    ctx = setup_submitted_removal_permit(
        dbh=dbh, condition_class=condition_class, user_id=user_id,
        zone_overrides=zone_overrides, species_overrides=species_overrides)
    ctx["permit"] = review(ctx["permit"]["id"], "APPROVE",
                           mitigation_method=mitigation_method)
    return ctx


def setup_issued_removal_permit(mitigation_method="REPLACEMENT_COST", dbh=20.0,
                                condition_class="GOOD", user_id=APPLICANT_1,
                                zone_overrides=None, species_overrides=None):
    """APPROVED REMOVAL permit -> fee paid -> ISSUED. Returns dict as above with
    permit in ISSUED and the computed mitigation_fee_cents already settled."""
    ctx = setup_approved_removal_permit(
        mitigation_method=mitigation_method, dbh=dbh, condition_class=condition_class,
        user_id=user_id, zone_overrides=zone_overrides, species_overrides=species_overrides)
    fee = ctx["permit"]["mitigation_fee_cents"]
    pay_fee(ctx["permit"]["id"], fee, user_id=user_id)
    ctx["permit"] = issue(ctx["permit"]["id"])
    return ctx


# ─── Tier 3: work-order / emergency scenarios ────────────────────────────
def setup_emergency_context(storm_overrides=None, contractor_overrides=None):
    """Zone + species + tree + one ACTIVE storm over the zone + one contractor.
    The default storm window (2026-02-15 .. 2026-04-15) covers the default clock.
    Returns dict(zone, species, tree, storm, contractor)."""
    zone, species, tree = setup_tree()
    storm = new_storm(zone["id"], **(storm_overrides or {}))
    contractor = new_contractor(**(contractor_overrides or {}))
    return {"zone": zone, "species": species, "tree": tree,
            "storm": storm, "contractor": contractor}


def setup_emergency_work_order(storm_overrides=None, contractor_overrides=None,
                               scheduled_start="2026-03-01T08:00:00Z",
                               scheduled_end="2026-03-01T10:00:00Z"):
    """Emergency context + an EMERGENCY_REMOVAL work order in CREATED (no dig ticket yet).
    Returns dict(zone, species, tree, storm, contractor, work_order)."""
    ctx = setup_emergency_context(storm_overrides, contractor_overrides)
    wo = new_work_order(ctx["tree"]["id"], ctx["contractor"]["id"], "EMERGENCY_REMOVAL",
                        scheduled_start, scheduled_end)
    ctx["work_order"] = wo
    return ctx


def setup_started_removal_work_order():
    """Full normal-removal path to an IN_PROGRESS work order.

    Zone (area 100, target 30) + Oak (mature 50) + tree dbh 20 -> zone at 50% MEETS ->
    REMOVAL permit approved (REPLACEMENT_COST, fee 40312) + paid + ISSUED ->
    contractor + REMOVAL work order + valid in-window 811 dig ticket + clock advanced into
    the dig window + work order started.
    Returns dict(zone, species, tree, permit, contractor, work_order, dig_ticket).
    """
    ctx = setup_issued_removal_permit(mitigation_method="REPLACEMENT_COST", dbh=20.0)
    contractor = new_contractor()
    wo = new_work_order(ctx["tree"]["id"], contractor["id"], "REMOVAL",
                        "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z",
                        permit_id=ctx["permit"]["id"])
    dt = new_dig_ticket(wo["id"], contractor["id"], ticket_number="811-1",
                        valid_from="2026-06-01T00:00:00Z", valid_to="2026-06-02T00:00:00Z")
    mark_valid(dt["id"])
    set_clock("2026-06-01T09:00:00Z")
    start_wo(wo["id"], contractor["id"])
    return {"zone": ctx["zone"], "species": ctx["species"], "tree": ctx["tree"],
            "permit": ctx["permit"], "contractor": contractor,
            "work_order": wo, "dig_ticket": dt}


# ─── Tier 4: conserved-quantity reconstruction ───────────────────────────
def outstanding_mitigation_cents() -> int:
    """Reconstruct the system-wide outstanding mitigation total (§2.9): the sum of
    mitigation_fee_cents over permits currently live (status APPROVED or ISSUED).
    Closed/revoked permits no longer contribute."""
    permits = get_success_data(api_client.list_permits(ADMIN, params={"limit": 100, "offset": 0}))
    return sum(p.get("mitigation_fee_cents", 0)
               for p in permits if p.get("status") in ("APPROVED", "ISSUED"))

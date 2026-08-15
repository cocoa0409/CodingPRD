"""Budget revisions, the tier-upgrade cascade, and the bond ledger (PRD §3.2-§3.3, §3.8)."""
import test_helpers as th
from test_helpers import ApiErrorId as E


def _staffing_bundle(name="Juniper Films LLC", fein="66-5555555"):
    return th.create_staffing_production(name, fein)


def test_budget_revision_upgrades_tier(api):
    """PRD §3.3: "A revision updates `budget_cents` and then re-evaluates the
    tier. If the current tier's cap covers the new budget, the tier is
    unchanged; a lower budget never downgrades the tier. Otherwise the tier
    upgrades to the smallest tier, in the declaration order of §2.7, whose cap
    covers the new budget."
    A revision 20,000,000 -> 40,000,000 crosses the ULB cap (30,000,000) but
    fits the MODIFIED_LOW_BUDGET cap (75,000,000).

    Design: Difficulty/transitive_cascade/budget_revision_tier_upgrade_cascade
    """
    bundle = _staffing_bundle()
    company, production = bundle["company"], bundle["production"]

    updated = th.revise_budget(production, company, 40_000_000)
    assert updated["budget_cents"] == 40_000_000
    assert updated["agreement_tier"] == "MODIFIED_LOW_BUDGET"


def test_tier_upgrade_flips_bond_underfunded_and_restricts_posture(api):
    """PRD §3.3: "An upgrade cascades: the bond's `amount_required_cents` is
    recomputed from the new tier's flat requirement, and if the bond's
    `amount_held_cents` now falls short of the new requirement, the bond
    transitions from `POSTED` to `UNDERFUNDED` on its own — and that bond
    transition in turn recomputes the production's posture, forcing
    `RESTRICTED` unless the production is `FROZEN`."
    PRD §2.7: "5,000,000 cents for `MODIFIED_LOW_BUDGET`". Holding 2,500,000
    against the new 5,000,000 requirement flips the bond and the posture.

    Design: Difficulty/transitive_cascade/budget_revision_tier_upgrade_cascade
    """
    bundle = _staffing_bundle()
    company, production, bond = bundle["company"], bundle["production"], bundle["bond"]

    th.revise_budget(production, company, 40_000_000)

    bonds, _ = th.validate_paginated(
        api.list_production_bonds(production["id"], th.owner_headers(company))
    )
    bond_after = bonds[0]
    th.assert_bond(bond_after)
    assert bond_after["id"] == bond["id"]
    assert bond_after["amount_required_cents"] == 5_000_000
    assert bond_after["status"] == "UNDERFUNDED"
    th.assert_bond_ledger_conservation(bond_after)

    production_after = th.get_production(production["id"], company)
    assert production_after["compliance_posture"] == "RESTRICTED"


def test_revision_to_exact_cap_keeps_tier(api):
    """PRD §2.7: "The cap boundary is inclusive — a budget exactly equal to a
    tier's cap is covered by that tier." PRD §3.3: "If the current tier's cap
    covers the new budget, the tier is unchanged".
    A revision to exactly 30,000,000 keeps ULTRA_LOW_BUDGET; the bond stays
    POSTED.

    Design: Difficulty/boundary_precision_check/budget_revision_tier_cap_inclusive_boundary
    """
    bundle = _staffing_bundle("Noble Birch LLC", "11-9999999")
    company, production, bond = bundle["company"], bundle["production"], bundle["bond"]

    updated = th.revise_budget(production, company, 30_000_000)
    assert updated["budget_cents"] == 30_000_000
    assert updated["agreement_tier"] == "ULTRA_LOW_BUDGET"

    bonds, _ = th.validate_paginated(
        api.list_production_bonds(production["id"], th.owner_headers(company))
    )
    assert bonds[0]["status"] == "POSTED"


def test_revision_one_cent_over_cap_upgrades_tier(api):
    """PRD §3.3: "Otherwise the tier upgrades to the smallest tier, in the
    declaration order of §2.7, whose cap covers the new budget." One cent over
    the inclusive 30,000,000 ULB cap (30,000,100) upgrades to
    MODIFIED_LOW_BUDGET, and the underfunded-bond cascade of PRD §3.3 fires:
    "the bond transitions from `POSTED` to `UNDERFUNDED` on its own".

    Design: Difficulty/boundary_precision_check/budget_revision_tier_cap_inclusive_boundary
    """
    bundle = _staffing_bundle("Noble Birch LLC", "11-9999999")
    company, production = bundle["company"], bundle["production"]

    th.revise_budget(production, company, 30_000_000)
    updated = th.revise_budget(th.get_production(production["id"], company),
                               company, 30_000_100)
    assert updated["agreement_tier"] == "MODIFIED_LOW_BUDGET"
    assert updated["budget_cents"] == 30_000_100

    bonds, _ = th.validate_paginated(
        api.list_production_bonds(production["id"], th.owner_headers(company))
    )
    assert bonds[0]["status"] == "UNDERFUNDED"
    assert bonds[0]["amount_required_cents"] == 5_000_000


def test_budget_decrease_never_downgrades_tier(api):
    """PRD §3.3: "If the current tier's cap covers the new budget, the tier is
    unchanged; a lower budget never downgrades the tier."
    After upgrading to MODIFIED_LOW_BUDGET at 40,000,000, revising back down to
    10,000,000 keeps the tier and the 5,000,000 bond requirement.

    Design: Corner/calculations/tier_never_downgrades_on_budget_decrease
    """
    bundle = _staffing_bundle("Cinquefoil LLC", "20-0000028")
    company, production = bundle["company"], bundle["production"]

    th.revise_budget(production, company, 40_000_000)
    updated = th.revise_budget(th.get_production(production["id"], company),
                               company, 10_000_000)
    assert updated["budget_cents"] == 10_000_000
    assert updated["agreement_tier"] == "MODIFIED_LOW_BUDGET", (
        "a lower budget never downgrades the tier"
    )

    bonds, _ = th.validate_paginated(
        api.list_production_bonds(production["id"], th.owner_headers(company))
    )
    assert bonds[0]["amount_required_cents"] == 5_000_000
    assert bonds[0]["status"] == "UNDERFUNDED", "held 2,500,000 < required 5,000,000"


def test_stale_version_revision_rejected(api):
    """PRD §2.9: "Applying a budget revision to a production requires the
    request to carry `expected_production_version` holding the production's
    `version` as the client last observed it." and "if the supplied value does
    not equal the entity's current `version` — because another writer has
    advanced the entity since the client last read it — the request is rejected
    with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_layers/occ_stale_version_on_budget_revision_rejected
    """
    bundle = _staffing_bundle("Whorl LLC", "20-0000050")
    company, production = bundle["company"], bundle["production"]
    observed = th.get_production(production["id"], company)

    first = th.get_success_data(api.create_budget_revision(
        production["id"],
        {"new_budget_cents": 21_000_000,
         "expected_production_version": observed["version"]},
        th.owner_headers(company),
    ))
    assert first["budget_cents"] == 21_000_000

    resp = api.create_budget_revision(
        production["id"],
        {"new_budget_cents": 22_000_000,
         "expected_production_version": observed["version"]},
        th.owner_headers(company),
    )
    th.validate_error(resp, E.ERR_STALE_VERSION)

    current = th.get_production(production["id"], company)
    assert current["budget_cents"] == 21_000_000, "stale revision must not apply"


def test_bond_post_below_requirement_rejected(api):
    """PRD §3.2: "A `ProducerRep` posts an `amount_cents` that must be at least
    `amount_required_cents`; anything less is rejected with
    `ERR_BOND_AMOUNT_INSUFFICIENT` (HTTP 422)."
    One cent below the 2,500,000 ULB requirement fails; exactly 2,500,000 posts.

    Design: Corner/validations/bond_post_below_requirement_rejected
    """
    company, _ = th.create_signatory_company("Knotgrass LLC", "20-0000038")
    production = th.create_production(company, "Knot Grass")
    bond = th.get_production_bond(production, company)

    resp = api.post_bond(bond["id"], {"amount_cents": 2_499_999},
                         th.owner_headers(company))
    th.validate_error(resp, E.ERR_BOND_AMOUNT_INSUFFICIENT)

    posted = th.post_bond(bond, company, 2_500_000)
    assert posted["status"] == "POSTED"
    assert th.get_production(production["id"], company)["status"] == "STAFFING"


def test_bond_topup_shortfall_rejected_exact_succeeds(api):
    """PRD §3.3: "On an `UNDERFUNDED` bond, a `ProducerRep` tops up an
    `amount_cents` that must be at least the requirement minus the currently
    held amount; shortfalls are `ERR_BOND_AMOUNT_INSUFFICIENT`. A successful
    top-up increases the posted total, recomputes the held amount, returns the
    bond to `POSTED`, and recomputes posture — which may return to `CLEAR` once
    the underfunding condition lifts."
    Shortfall is 5,000,000 - 2,500,000 = 2,500,000.

    Design: Corner/validations/bond_topup_shortfall_rejected_exact_succeeds
    """
    bundle = _staffing_bundle("Lousewort LLC", "20-0000039")
    company, production, bond = bundle["company"], bundle["production"], bundle["bond"]
    th.revise_budget(production, company, 40_000_000)

    resp = api.top_up_bond(bond["id"], {"amount_cents": 2_499_999},
                           th.owner_headers(company))
    th.validate_error(resp, E.ERR_BOND_AMOUNT_INSUFFICIENT)

    topped = th.get_success_data(api.top_up_bond(
        bond["id"], {"amount_cents": 2_500_000}, th.owner_headers(company),
    ))
    th.assert_bond(topped)
    assert topped["status"] == "POSTED"
    assert topped["total_posted_cents"] == 5_000_000
    assert topped["amount_held_cents"] == 5_000_000
    th.assert_bond_ledger_conservation(topped)

    production_after = th.get_production(production["id"], company)
    assert production_after["compliance_posture"] == "CLEAR"


def test_bond_release_before_close_rejected(api, fund_trustee_headers):
    """PRD §3.8: "a `FundTrustee` may release a `POSTED` bond (any other bond
    state, or a production not yet `CLOSED`, is `ERR_BOND_STATE`)."

    Design: Corner/state_machines/bond_release_before_close_rejected
    """
    bundle = _staffing_bundle("Ironbark LLC", "20-0000009")
    company, production, bond = bundle["company"], bundle["production"], bundle["bond"]

    resp = api.release_bond(bond["id"], fund_trustee_headers)
    th.validate_error(resp, E.ERR_BOND_STATE)

    bonds, _ = th.validate_paginated(
        api.list_production_bonds(production["id"], th.owner_headers(company))
    )
    assert bonds[0]["status"] == "POSTED"
    assert bonds[0]["total_released_cents"] == 0, "no ledger movement on rejection"


def test_bond_post_flips_production_to_staffing(api):
    """PRD §3.2: "On success the posted total increases by `amount_cents`, the
    held amount is recomputed, the bond moves from `PENDING` to `POSTED`, the
    production moves from `REGISTERED` to `STAFFING`, and the production's
    posture is recomputed."
    PRD §2.4: "`version` is an integer that starts at 1 on creation and
    increments by exactly one on every mutation of the resource — and every
    state transition described anywhere in §3 is a mutation".

    Design: Corner/state_machines/bond_post_flips_production_to_staffing
    """
    company, _ = th.create_signatory_company("Nettlebrook LLC", "20-0000014")
    production = th.create_production(company, "Nettle Run")
    assert production["version"] == 1
    assert production["status"] == "REGISTERED"
    bond = th.get_production_bond(production, company)

    posted = th.post_bond(bond, company, 2_500_000)
    assert posted["status"] == "POSTED"
    assert posted["amount_held_cents"] == 2_500_000

    production_after = th.get_production(production["id"], company)
    assert production_after["status"] == "STAFFING"
    assert production_after["version"] == 2, "exactly one production mutation"


def test_closed_production_bond_release_full(api, fund_trustee_headers):
    """PRD §3.8: "Release is always full: the entire `amount_held_cents` moves
    into `total_released_cents`, the held amount is zeroed, and the bond lands
    in `RELEASED`, its terminal state."

    Design: Difficulty/compensating_invariant/bond_post_release_ledger_conservation
    """
    bundle = th.setup_closed_production(legal_name="Tamarack Bay LLC",
                                        fein="17-0000006")
    company, production, bond = bundle["company"], bundle["production"], bundle["bond"]
    assert production["status"] == "CLOSED"

    released = th.get_success_data(api.release_bond(bond["id"], fund_trustee_headers))
    th.assert_bond(released)
    assert released["status"] == "RELEASED"
    assert released["amount_held_cents"] == 0
    assert released["total_released_cents"] == 2_500_000


def test_bond_ledger_conservation_after_release(api, fund_trustee_headers):
    """PRD §3.2: "its `amount_held_cents` is always the posted total minus the
    released total minus the forfeited total." Posting 2,500,000 followed by a
    full release at production close leaves posted == released == 2,500,000,
    forfeited == 0, held == 0 — forward plus compensating action, no drift.

    Design: Difficulty/compensating_invariant/bond_post_release_ledger_conservation
    """
    bundle = th.setup_closed_production(legal_name="Tamarack Bay LLC",
                                        fein="17-0000006")
    company, bond = bundle["company"], bundle["bond"]

    released = th.get_success_data(api.release_bond(bond["id"], fund_trustee_headers))
    assert released["total_posted_cents"] == 2_500_000
    assert released["total_released_cents"] == 2_500_000
    assert released["total_forfeited_cents"] == 0
    assert released["amount_held_cents"] == 0
    th.assert_bond_ledger_conservation(released)


def test_cross_company_bond_post_rejected(api):
    """PRD §2.1: "ownership checks on any resource that belongs to a company
    (directly, or via the `production_id` chain from a production down to its
    bond, crew assignments, work day logs, grievances, contribution reports,
    audits, and force majeure events) compare the resource's owning company
    `id` to `X-User-ID`. A `ProducerRep` whose `X-User-ID` does not match the
    company that owns the target resource is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)".

    Design: Corner/validations/cross_company_bond_post_rejected
    """
    company_a, _ = th.create_signatory_company("Eglantine A LLC", "20-0000031")
    production_a = th.create_production(company_a, "Eglantine A1")
    bond_a = th.get_production_bond(production_a, company_a)
    company_b = th.register_company("Eglantine B LLC", "20-0000032")

    resp = api.post_bond(bond_a["id"], {"amount_cents": 2_500_000},
                         th.owner_headers(company_b))
    th.validate_error(resp, E.ERR_NOT_RESOURCE_OWNER)

    bonds, _ = th.validate_paginated(
        api.list_production_bonds(production_a["id"], th.owner_headers(company_a))
    )
    assert bonds[0]["status"] == "PENDING", "rejected post must not move the bond"

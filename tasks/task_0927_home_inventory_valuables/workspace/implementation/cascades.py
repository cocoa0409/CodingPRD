"""Cross-entity cascades shared by more than one endpoint."""

import derive
import store


def maybe_auto_deny(claim):
    """UNDER_REVIEW -> DENIED once every line of the claim is denied."""
    if claim["status"] != "UNDER_REVIEW":
        return False
    if claim["line_count"] == 0 or claim["denied_line_count"] != claim["line_count"]:
        return False
    claim["status"] = "DENIED"
    claim["total_settlement_cents"] = 0
    store.touch(claim)
    derive.unfreeze_items_of_claim(claim, bump=True)
    household = store.households.get(claim["household_id"])
    if household is not None:
        derive.recompute_household(household, bump=True)
    return True


def evidence_downgrade_cascade(item):
    """Hops 3 and 4 of PRD 3.3: pending lines on an item that has dropped below
    the claim minimum are denied, and a claim whose lines are now all denied
    follows."""
    affected = []
    for line in store.all_of(store.claim_lines):
        if line["item_id"] != item["id"] or line["status"] != "PENDING":
            continue
        line["status"] = "DENIED"
        line["denial_reason"] = "EVIDENCE_INSUFFICIENT"
        line["net_settlement_cents"] = 0
        store.touch(line)
        claim = store.claims.get(line["claim_id"])
        if claim is not None and claim not in affected:
            affected.append(claim)
    for claim in affected:
        derive.recompute_claim_counts(claim, bump=True)
        maybe_auto_deny(claim)
    return affected


def appraisal_void_cascade(appraisal, item):
    """Hops 3-5 of PRD 3.4's deepest cascade."""
    household_id = item["household_id"] if item is not None else None
    if household_id is None:
        return
    # hop 3: every policy of the household is recomputed
    policies = derive.household_policies(household_id)
    for policy in policies:
        derive.recompute_policy(policy, bump=True)
        store.touch(policy)
    policy_ids = {p["id"] for p in policies}

    # hop 4: GENERATED packages on those policies expire unconditionally, and
    # every package line referencing the item goes stale.
    expired_packages = []
    for package in store.all_of(store.packages):
        if package["policy_id"] in policy_ids and package["status"] == "GENERATED":
            package["status"] = "EXPIRED"
            store.touch(package)
            expired_packages.append(package)
    derive.refresh_stale_flags(item, force=True, bump=True)

    # hop 5: pending lines whose claim rests on a package hop 4 expired go on
    # settlement hold.
    expired_ids = {p["id"] for p in expired_packages}
    touched_claims = []
    for line in store.all_of(store.claim_lines):
        if line["status"] != "PENDING" or line["settlement_hold"]:
            continue
        claim = store.claims.get(line["claim_id"])
        if claim is None or claim["package_id"] not in expired_ids:
            continue
        line["settlement_hold"] = True
        store.touch(line)
        if claim not in touched_claims:
            touched_claims.append(claim)
    for claim in touched_claims:
        derive.recompute_claim_counts(claim, bump=True)

    # the same package-expiry consequences that PRD 3.6 attaches to any expiry
    for package in expired_packages:
        derive.void_grants(derive.grants_scoped_to_package(package["id"]), "SCOPE_SUPERSEDED")
    household = store.households.get(household_id)
    if household is not None:
        derive.recompute_household(household, bump=False)

"""Composite setup helpers.

Every helper builds its preconditions from scratch (the server database is empty at
the start of each test) using only PRD-declared endpoints. All helpers use the
lenient get_success_data() so a broken setup surfaces as a clear "Setup failed".

Identity threading: Owner calls use make_owner_headers(plan_id); Deputy calls use
make_deputy_headers(deputy_id); PlatformAdmin uses the opaque ADMIN_HEADERS.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import ADMIN_HEADERS, make_owner_headers, make_deputy_headers


# --------------------------------------------------------------------------- #
# Primitive building blocks
# --------------------------------------------------------------------------- #
def set_clock(api, iso: str):
    return get_success_data(api.set_clock({"to_iso8601": iso}, ADMIN_HEADERS))


def create_plan(api, owner_full_name="Ada Owner", owner_email="ada@x.com") -> dict:
    return get_success_data(api.create_plan(
        {"owner_full_name": owner_full_name, "owner_email": owner_email}, ADMIN_HEADERS))


def create_subscription(api, plan_id, tier="PLUS", refund_policy=None) -> dict:
    payload = {"plan_id": plan_id, "tier": tier}
    if refund_policy is not None:
        payload["refund_policy"] = refund_policy
    return get_success_data(api.create_subscription(payload, make_owner_headers(plan_id)))


def activate_subscription(api, plan_id, sub_id) -> dict:
    """Drive TRIALING -> ACTIVE via a SUCCEEDED payment."""
    return get_success_data(api.record_payment(sub_id, {"outcome": "SUCCEEDED"}, ADMIN_HEADERS))


def fail_payment(api, sub_id) -> dict:
    return get_success_data(api.record_payment(sub_id, {"outcome": "FAILED"}, ADMIN_HEADERS))


def create_deputy(api, plan_id, deputy_role="EXECUTOR", access_scope=("ASSET",),
                  full_name="Dee One", email="d1@x.com", release_trigger="ON_DEATH",
                  authority_start_at="2026-06-01T00:00:00Z",
                  authority_end_at="2027-06-01T00:00:00Z", consumes_seat=None) -> dict:
    payload = {
        "plan_id": plan_id,
        "full_name": full_name,
        "email": email,
        "deputy_role": deputy_role,
        "access_scope": list(access_scope),
        "release_trigger": release_trigger,
        "authority_start_at": authority_start_at,
        "authority_end_at": authority_end_at,
    }
    if consumes_seat is not None:
        payload["consumes_seat"] = consumes_seat
    return get_success_data(api.create_deputy(payload, make_owner_headers(plan_id)))


def accept_deputy(api, deputy_id) -> dict:
    return get_success_data(api.accept_deputy(deputy_id, make_deputy_headers(deputy_id)))


def create_and_accept_deputy(api, plan_id, **kwargs) -> dict:
    dep = create_deputy(api, plan_id, **kwargs)
    return accept_deputy(api, dep["id"])


def create_vault_item(api, plan_id, kind="DOCUMENT", category="will", title="Will",
                      secret_ref="vault://will", **extra) -> dict:
    payload = {"plan_id": plan_id, "kind": kind, "category": category,
               "title": title, "secret_ref": secret_ref}
    payload.update(extra)
    return get_success_data(api.create_vault_item(payload, make_owner_headers(plan_id)))


def seal_vault_item(api, plan_id, item_id) -> dict:
    return get_success_data(api.seal_vault_item(item_id, make_owner_headers(plan_id)))


def create_beneficiary(api, plan_id, full_name="Ben One", relationship="child", **extra) -> dict:
    payload = {"plan_id": plan_id, "full_name": full_name, "relationship": relationship}
    payload.update(extra)
    return get_success_data(api.create_beneficiary(payload, make_owner_headers(plan_id)))


def create_directive(api, plan_id, directive_type="MEDICAL", content="wishes") -> dict:
    return get_success_data(api.create_directive(
        {"plan_id": plan_id, "directive_type": directive_type, "content": content},
        make_owner_headers(plan_id)))


def activate_directive(api, plan_id, directive_id, expected_plan_version) -> dict:
    return get_success_data(api.activate_directive(
        directive_id, {"expected_plan_version": expected_plan_version},
        make_owner_headers(plan_id)))


def get_plan(api, plan_id) -> dict:
    return get_success_data(api.get_plan(plan_id, make_owner_headers(plan_id)))


def mark_life_status(api, plan_id, new_status, evidence_ref="cert-001") -> dict:
    return get_success_data(api.set_life_status(
        plan_id, {"new_status": new_status, "evidence_ref": evidence_ref}, ADMIN_HEADERS))


def create_release_request(api, plan_id, deputy_id, trigger_type="ON_DEATH",
                           scope_kinds=("ASSET",)) -> dict:
    return get_success_data(api.create_release_request(
        {"plan_id": plan_id, "trigger_type": trigger_type, "scope_kinds": list(scope_kinds)},
        make_deputy_headers(deputy_id)))


def verify_release_request(api, rr_id) -> dict:
    return get_success_data(api.verify_release_request(rr_id, ADMIN_HEADERS))


def approve_release_request(api, deputy_id, rr_id, decision="APPROVE") -> dict:
    return get_success_data(api.approve_release_request(
        rr_id, {"decision": decision}, make_deputy_headers(deputy_id)))


def grant_release_request(api, rr_id) -> dict:
    return get_success_data(api.grant_release_request(rr_id, ADMIN_HEADERS))


def create_review_reminder(api, plan_id, subject_kind="VAULT", interval_days=180,
                           last_reviewed_at="2026-06-01T00:00:00Z") -> dict:
    return get_success_data(api.create_review_reminder(
        {"plan_id": plan_id, "subject_kind": subject_kind, "interval_days": interval_days,
         "last_reviewed_at": last_reviewed_at}, make_owner_headers(plan_id)))


def create_active_share(api, plan_id, item_id, shared_with_email="bob@x.com",
                        effective_at="2026-06-01T00:00:00Z",
                        expires_at="2026-07-01T00:00:00Z") -> dict:
    return get_success_data(api.create_share(
        {"plan_id": plan_id, "vault_item_id": item_id, "shared_with_email": shared_with_email,
         "scope": "ITEM", "effective_at": effective_at, "expires_at": expires_at},
        make_owner_headers(plan_id)))


# --------------------------------------------------------------------------- #
# Composite scenarios
# --------------------------------------------------------------------------- #
def setup_release_approved(api, *, base_clock="2026-06-01T00:00:00Z", tier="PLUS",
                           create_asset=True, gross_value_cents=10000, liability_cents=1,
                           distribution_basis="NET", allocations=(100,),
                           scope_kinds=("ASSET",), deputy_scope=("ASSET",)):
    """Build a DECEASED plan with one ACCEPTED deputy and an APPROVED release request,
    ready for the admin to GRANT.

    When create_asset is True: creates one SEALED ASSET vault item and one linked
    NOMINATED beneficiary per entry in `allocations` (created in list order).

    Steps: clock -> plan -> subscription -> deputy(+accept) -> [asset + beneficiaries
    + seal] -> life-status DECEASED -> release-request -> verify -> approve(x1).
    required_approvals is 1 (one accepted deputy), so a single APPROVE reaches quorum.

    Returns a dict of ids and the entity snapshots.
    """
    set_clock(api, base_clock)
    plan = create_plan(api)
    plan_id = plan["id"]
    sub = create_subscription(api, plan_id, tier=tier)
    deputy = create_and_accept_deputy(api, plan_id, deputy_role="EXECUTOR",
                                      access_scope=list(deputy_scope))
    deputy_id = deputy["id"]

    item = None
    beneficiaries = []
    if create_asset:
        item = create_vault_item(api, plan_id, kind="ASSET", category="estate", title="House",
                                 secret_ref="vault://house", gross_value_cents=gross_value_cents,
                                 liability_cents=liability_cents,
                                 distribution_basis=distribution_basis)
        for idx, pct in enumerate(allocations):
            ben = create_beneficiary(api, plan_id, full_name=f"Ben {idx + 1}",
                                     relationship="child", allocation_pct=pct,
                                     asset_vault_item_id=item["id"])
            beneficiaries.append(ben)
        seal_vault_item(api, plan_id, item["id"])

    mark_life_status(api, plan_id, "DECEASED")
    rr = create_release_request(api, plan_id, deputy_id, trigger_type="ON_DEATH",
                                scope_kinds=list(scope_kinds))
    rr_id = rr["id"]
    verify_release_request(api, rr_id)
    approve_release_request(api, deputy_id, rr_id, decision="APPROVE")

    return {
        "plan_id": plan_id,
        "sub_id": sub["id"],
        "deputy_id": deputy_id,
        "item_id": item["id"] if item else None,
        "beneficiary_ids": [b["id"] for b in beneficiaries],
        "rr_id": rr_id,
    }


def setup_released_asset(api, **kwargs):
    """setup_release_approved + GRANT. The asset is RELEASED and beneficiaries VESTED."""
    ctx = setup_release_approved(api, **kwargs)
    grant_release_request(api, ctx["rr_id"])
    return ctx


def setup_release_verified_multi_deputy(api, *, base_clock="2026-06-01T00:00:00Z",
                                        num_deputies=3):
    """DECEASED plan with `num_deputies` ACCEPTED deputies and a VERIFIED release request
    (no votes yet). With 3 accepted deputies required_approvals is ceil(3*0.5)=2.

    Returns {plan_id, deputy_ids, rr_id}.
    """
    set_clock(api, base_clock)
    plan = create_plan(api)
    plan_id = plan["id"]
    create_subscription(api, plan_id, tier="PLUS")
    roles = ["EXECUTOR", "HEALTHCARE_PROXY", "GUARDIAN", "VIEWER"]
    deputy_ids = []
    for i in range(num_deputies):
        dep = create_and_accept_deputy(
            api, plan_id, deputy_role=roles[i % len(roles)],
            access_scope=["ASSET"], full_name=f"D {i}", email=f"d{i}@x.com")
        deputy_ids.append(dep["id"])
    mark_life_status(api, plan_id, "DECEASED")
    rr = create_release_request(api, plan_id, deputy_ids[0], trigger_type="ON_DEATH",
                                scope_kinds=["ASSET"])
    rr_id = rr["id"]
    verify_release_request(api, rr_id)
    return {"plan_id": plan_id, "deputy_ids": deputy_ids, "rr_id": rr_id}


def setup_plan_pending_release(api, *, base_clock="2026-06-01T00:00:00Z",
                               life_status=None, tier="PLUS"):
    """Plan + ACCEPTED deputy + PENDING (unverified) release request.

    If life_status is given (e.g. "DECEASED") the plan is moved there before filing.
    Returns {plan_id, sub_id, deputy_id, rr_id}.
    """
    set_clock(api, base_clock)
    plan = create_plan(api)
    plan_id = plan["id"]
    sub = create_subscription(api, plan_id, tier=tier)
    deputy = create_and_accept_deputy(api, plan_id, deputy_role="EXECUTOR", access_scope=["ASSET"])
    deputy_id = deputy["id"]
    if life_status is not None:
        mark_life_status(api, plan_id, life_status)
    rr = create_release_request(api, plan_id, deputy_id, trigger_type="ON_DEATH",
                                scope_kinds=["ASSET"])
    return {"plan_id": plan_id, "sub_id": sub["id"], "deputy_id": deputy_id, "rr_id": rr["id"]}


def setup_active_paid_plan(api, *, base_clock="2026-06-01T00:00:00Z", tier="PLUS"):
    """Plan with a paid subscription driven to ACTIVE (ready for share creation).

    Returns {plan_id, sub_id}.
    """
    set_clock(api, base_clock)
    plan = create_plan(api)
    plan_id = plan["id"]
    sub = create_subscription(api, plan_id, tier=tier)
    activate_subscription(api, plan_id, sub["id"])
    return {"plan_id": plan_id, "sub_id": sub["id"]}


def setup_plus_plan_completeness_66(api, *, base_clock="2026-06-01T00:00:00Z"):
    """PLUS plan with 2 SEALED DOCUMENT items, 1 ACTIVE directive, 1 ACCEPTED deputy,
    and 3 NOMINATED beneficiaries; life_status ACTIVE.

    Yields completeness_pct == 66 under PLUS weights (40,20,20,20).
    Returns {plan_id}.
    """
    set_clock(api, base_clock)
    plan = create_plan(api)
    plan_id = plan["id"]
    create_subscription(api, plan_id, tier="PLUS")
    for i, (title, secret) in enumerate([("Will", "vault://will"), ("Letters", "vault://letters")]):
        it = create_vault_item(api, plan_id, kind="DOCUMENT", category="doc", title=title,
                               secret_ref=secret)
        seal_vault_item(api, plan_id, it["id"])
    directive = create_directive(api, plan_id, directive_type="MEDICAL", content="wishes")
    plan_now = get_plan(api, plan_id)
    activate_directive(api, plan_id, directive["id"], plan_now["version"])
    create_and_accept_deputy(api, plan_id, deputy_role="EXECUTOR", access_scope=["ACCOUNT"])
    for i in range(3):
        create_beneficiary(api, plan_id, full_name=f"Ben {i}", relationship="child")
    return {"plan_id": plan_id}


def setup_activated_directive(api, *, base_clock="2026-06-01T00:00:00Z",
                              directive_type="MEDICAL"):
    """Plan with one directive activated (ACTIVE, plan version advanced).

    Returns {plan_id, directive_id, plan_version_after_activate}.
    """
    set_clock(api, base_clock)
    plan = create_plan(api)
    plan_id = plan["id"]
    directive = create_directive(api, plan_id, directive_type=directive_type, content="v1")
    activate_directive(api, plan_id, directive["id"], plan["version"])
    plan_after = get_plan(api, plan_id)
    return {"plan_id": plan_id, "directive_id": directive["id"],
            "plan_version_after_activate": plan_after["version"]}

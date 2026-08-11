"""Documentation packages: generation, delivery and the frozen snapshot
(PRD 3.6)."""

import calc
import derive
import serializers
import store
from constants import PACKAGE_VALIDITY_DAYS, SUBSCRIPTION_TIERS
from errors import ApiError
from money import round_half_up
from registry import endpoint
from routes.common import field, list_response, one
from timeutil import add_days, clock


def _package(ctx):
    return ctx.row("package_id")


def _package_household(ctx):
    return _package(ctx)["household_id"]


@endpoint(
    "POST",
    "/vault/packages",
    roles=["Homeowner"],
    code=201,
    mutating=True,
    owner_only=True,
    body={"household_id": ("string", True), "policy_id": ("string", True)},
    fks=("household_id", "policy_id"),
    household=lambda ctx: ctx.body.get("household_id"),
)
def create_package(ctx):
    row = store.new_row(
        store.packages,
        household_id=ctx.body["household_id"],
        policy_id=ctx.body["policy_id"],
        status="DRAFT",
        recipient_ref=None,
        line_count=0,
        snapshot_total_effective_cents=0,
        snapshot_total_covered_cents=0,
        snapshot_coverage_gap_cents=0,
        stale_line_count=0,
        superseded_by_package_id=None,
    )
    derive.stamp(row, "generated_at", None)
    derive.stamp(row, "delivered_at", None)
    derive.stamp(row, "expires_at", None)
    return one(serializers.package(row), 201)


@endpoint(
    "GET",
    "/vault/packages/{package_id}",
    roles=["Homeowner", "InsuranceAgent", "ClaimsAdjuster", "PlatformAdmin"],
    scope_household=_package_household,
)
def read_package(ctx):
    return one(serializers.package(_package(ctx)))


@endpoint(
    "GET",
    "/vault/packages",
    roles=["Homeowner", "InsuranceAgent", "ClaimsAdjuster", "PlatformAdmin"],
)
def list_packages(ctx):
    return list_response(
        store.all_of(store.packages),
        ctx.args,
        serializers.package,
        {
            "household_id": field("household_id"),
            "policy_id": field("policy_id"),
            "superseded_by_package_id": field("superseded_by_package_id"),
            "status": field("status"),
        },
    )


# ------------------------------------------------------------- generation
def _generate_rung13(ctx):
    if _package(ctx)["status"] in ("SUPERSEDED", "EXPIRED"):
        raise ApiError("ERR_ALREADY_TERMINAL")


def _generate_rung14(ctx):
    if _package(ctx)["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")


def _generate_rung31(ctx):
    # PRD 3.6: before anything else the service expires any certified appraisal
    # whose valid_until_at the clock has reached.
    derive.expire_due_appraisals(bump=False)
    package = _package(ctx)
    if not calc.package_eligible_items(package["household_id"]):
        raise ApiError("ERR_PACKAGE_EMPTY")


def _generate_rung35(ctx):
    package = _package(ctx)
    sub = derive.subscription_of(package["household_id"])
    if sub is None:
        return
    allowance = SUBSCRIPTION_TIERS[sub["tier"]]["included_packages_per_period"]
    if sub["packages_used_this_period"] >= allowance:
        raise ApiError("ERR_PACKAGE_QUOTA_EXCEEDED")


@endpoint(
    "POST",
    "/vault/packages/{package_id}/generate",
    roles=["Homeowner"],
    mutating=True,
    owner_only=True,
    body={"expected_household_version": ("integer", True)},
    household=_package_household,
    scope_household=_package_household,
    rungs={13: _generate_rung13, 14: _generate_rung14, 31: _generate_rung31, 35: _generate_rung35},
    occ=(
        "expected_household_version",
        "ERR_STALE_HOUSEHOLD_VERSION",
        lambda ctx: store.households.get(ctx.row("package_id")["household_id"]),
    ),
)
def generate_package(ctx):
    package = _package(ctx)
    household = store.households.get(package["household_id"])
    policy = store.policies.get(package["policy_id"])
    generated_at = clock.now
    derive.stamp(package, "generated_at", generated_at)
    derive.stamp(package, "expires_at", add_days(generated_at, PACKAGE_VALIDITY_DAYS))

    eligible = calc.package_eligible_items(package["household_id"])
    covered = (
        calc.coverage_waterfall(policy, eligible, "SCHEDULED_FIRST")
        if policy is not None
        else {i["id"]: 0 for i in eligible}
    )

    total_effective = 0
    total_covered = 0
    for item in eligible:
        # Pinned rounding order: round every line first, then sum the lines.
        exact = calc.snapshot_exact_value(item, generated_at)
        snapshot_value = round_half_up(exact)
        snapshot_covered = covered.get(item["id"], 0)
        store.new_row(
            store.package_lines,
            common_fields=False,
            package_id=package["id"],
            item_id=item["id"],
            snapshot_name=item["name"],
            snapshot_category=item["category"],
            snapshot_evidence_tier=item["evidence_tier"],
            snapshot_effective_value_cents=snapshot_value,
            snapshot_effective_value_basis=item["effective_value_basis"],
            snapshot_covered_cents=snapshot_covered,
            snapshot_coverage_mode=item["coverage_mode"],
            stale=False,
        )
        total_effective += snapshot_value
        total_covered += snapshot_covered

    package["status"] = "GENERATED"
    package["line_count"] = len(eligible)
    package["snapshot_total_effective_cents"] = total_effective
    package["snapshot_total_covered_cents"] = total_covered
    package["snapshot_coverage_gap_cents"] = total_effective - total_covered
    store.touch(package)

    # hop 2: a prior DELIVERED package for the same policy is superseded.
    for prior in store.all_of(store.packages):
        if prior["id"] == package["id"] or prior["policy_id"] != package["policy_id"]:
            continue
        if prior["status"] != "DELIVERED":
            continue
        prior["status"] = "SUPERSEDED"
        prior["superseded_by_package_id"] = package["id"]
        store.touch(prior)
        # hop 3
        derive.void_grants(derive.grants_scoped_to_package(prior["id"]), "SCOPE_SUPERSEDED")

    sub = derive.subscription_of(package["household_id"])
    if sub is not None:
        sub["packages_used_this_period"] += 1
        store.touch(sub)
    if household is not None:
        # hop 4 plus the OCC parent's own bump
        derive.recompute_household(household, bump=True)
        store.touch(household)
    return one(serializers.package(package))


# --------------------------------------------------------------- delivery
def _deliver_rung13(ctx):
    if _package(ctx)["status"] in ("SUPERSEDED", "EXPIRED"):
        raise ApiError("ERR_ALREADY_TERMINAL")


def _deliver_rung14(ctx):
    package = _package(ctx)
    if package["status"] != "GENERATED":
        raise ApiError("ERR_INVALID_STATE")
    expires = package.get("_expires_at_dt")
    if expires is not None and clock.now >= expires:
        raise ApiError("ERR_INVALID_STATE")


@endpoint(
    "POST",
    "/vault/packages/{package_id}/deliver",
    roles=["Homeowner", "InsuranceAgent"],
    mutating=True,
    body={"recipient_ref": ("string", True)},
    household=_package_household,
    scope_household=_package_household,
    rungs={13: _deliver_rung13, 14: _deliver_rung14},
)
def deliver_package(ctx):
    package = _package(ctx)
    package["status"] = "DELIVERED"
    package["recipient_ref"] = ctx.body["recipient_ref"]
    derive.stamp(package, "delivered_at", clock.now)
    store.touch(package)
    return one(serializers.package(package))


# ----------------------------------------------------------- package lines
@endpoint(
    "GET",
    "/vault/package-lines/{package_line_id}",
    roles=["Homeowner", "InsuranceAgent", "ClaimsAdjuster", "PlatformAdmin"],
    scope_household=lambda ctx: (
        store.packages.get(ctx.row("package_line_id")["package_id"]) or {}
    ).get("household_id"),
)
def read_package_line(ctx):
    return one(serializers.package_line(ctx.row("package_line_id")))


@endpoint(
    "GET",
    "/vault/package-lines",
    roles=["Homeowner", "InsuranceAgent", "ClaimsAdjuster", "PlatformAdmin"],
)
def list_package_lines(ctx):
    return list_response(
        store.all_of(store.package_lines),
        ctx.args,
        serializers.package_line,
        {
            "package_id": field("package_id"),
            "item_id": field("item_id"),
            "stale": field("stale"),
        },
    )

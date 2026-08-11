"""Members and households (PRD 3.1)."""

import derive
import serializers
import store
from constants import MEMBER_ROLES
from errors import ApiError
from registry import endpoint
from routes.common import field, list_response, one


def _duplicate_email(ctx):
    email = ctx.body.get("email")
    for member in store.members.values():
        if member["email"] == email:
            raise ApiError("ERR_INVALID_REQUEST", "A member with this email already exists.")


@endpoint(
    "POST",
    "/vault/members",
    roles=["Anonymous", "Homeowner"],
    code=201,
    mutating=True,
    body={
        "email": ("string", True),
        "full_name": ("string", True),
        "member_role": ("string", False),
        "household_id": ("string", False),
    },
    enums={"member_role": MEMBER_ROLES},
    fks=("household_id",),
    rung3_extra=_duplicate_email,
    household=lambda ctx: ctx.body.get("household_id"),
)
def register_member(ctx):
    household_id = ctx.body.get("household_id")
    supplied_role = ctx.body.get("member_role")
    if supplied_role is not None:
        member_role = supplied_role
    elif household_id is None:
        member_role = "OWNER"
    else:
        member_role = "LIMITED"
    row = store.new_row(
        store.members,
        email=ctx.body["email"],
        full_name=ctx.body["full_name"],
        member_role=member_role,
        household_id=household_id,
    )
    return one(serializers.member(row), 201)


@endpoint(
    "GET",
    "/vault/members/{member_id}",
    roles=["Homeowner", "HouseholdMember", "EstateExecutor", "PlatformAdmin"],
    scope_household=lambda ctx: ctx.row("member_id").get("household_id"),
)
def read_member(ctx):
    return one(serializers.member(ctx.row("member_id")))


@endpoint(
    "GET",
    "/vault/members",
    roles=["Homeowner", "HouseholdMember", "EstateExecutor", "PlatformAdmin"],
)
def list_members(ctx):
    return list_response(
        store.all_of(store.members),
        ctx.args,
        serializers.member,
        {"household_id": field("household_id"), "member_role": field("member_role")},
    )


@endpoint(
    "POST",
    "/vault/households",
    roles=["Homeowner"],
    code=201,
    mutating=True,
    owner_only=True,
    body={"name": ("string", True), "address_label": ("string", True)},
)
def create_household(ctx):
    row = store.new_row(
        store.households,
        name=ctx.body["name"],
        address_label=ctx.body["address_label"],
        write_gate_state="OPEN",
        records_freeze_active=False,
        item_count=0,
        asset_count=0,
        asset_bytes_used=0,
        frozen_item_count=0,
        active_share_count=0,
        total_effective_value_cents=0,
    )
    member = store.members.get(ctx.user_id)
    member["household_id"] = row["id"]
    member["member_role"] = "OWNER"
    store.touch(member)
    return one(serializers.household(row), 201)


@endpoint(
    "GET",
    "/vault/households/{household_id}",
    roles=[
        "Homeowner",
        "HouseholdMember",
        "EstateExecutor",
        "InsuranceAgent",
        "ClaimsAdjuster",
        "PlatformAdmin",
    ],
    scope_household=lambda ctx: ctx.row("household_id")["id"],
)
def read_household(ctx):
    return one(serializers.household(ctx.row("household_id")))


@endpoint("GET", "/vault/households", roles=["PlatformAdmin"])
def list_households(ctx):
    return list_response(
        store.all_of(store.households),
        ctx.args,
        serializers.household,
        {"write_gate_state": field("write_gate_state")},
    )

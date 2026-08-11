"""Rooms (PRD 3.3)."""

import serializers
import store
from registry import endpoint
from routes.common import field, list_response, one


@endpoint(
    "POST",
    "/vault/rooms",
    roles=["Homeowner", "HouseholdMember"],
    code=201,
    mutating=True,
    body={
        "household_id": ("string", True),
        "name": ("string", True),
        "floor_label": ("string", True),
    },
    fks=("household_id",),
    household=lambda ctx: ctx.body.get("household_id"),
)
def create_room(ctx):
    row = store.new_row(
        store.rooms,
        household_id=ctx.body["household_id"],
        name=ctx.body["name"],
        floor_label=ctx.body["floor_label"],
        item_count=0,
    )
    return one(serializers.room(row), 201)


@endpoint(
    "GET",
    "/vault/rooms/{room_id}",
    roles=["Homeowner", "HouseholdMember", "EstateExecutor", "PlatformAdmin"],
    scope_household=lambda ctx: ctx.row("room_id")["household_id"],
)
def read_room(ctx):
    return one(serializers.room(ctx.row("room_id")))


@endpoint(
    "GET",
    "/vault/rooms",
    roles=["Homeowner", "HouseholdMember", "EstateExecutor", "PlatformAdmin"],
)
def list_rooms(ctx):
    return list_response(
        store.all_of(store.rooms),
        ctx.args,
        serializers.room,
        {"household_id": field("household_id")},
    )

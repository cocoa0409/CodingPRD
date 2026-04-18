import uuid
import clock


restaurants = {}
menu_items = {}
customers = {}
riders = {}
orders = {}
assignments = {}
route_groups = {}
fines = {}
returns = {}
work_orders = {}


def new_id():
    return str(uuid.uuid4())


def make_timestamps():
    ts = clock.format_timestamp(clock.now())
    return ts, ts


def versioned_resource_base():
    created, updated = make_timestamps()
    return {
        "id": new_id(),
        "created_at": created,
        "updated_at": updated,
        "version": 1,
    }


def operational_resource_base():
    created = clock.format_timestamp(clock.now())
    return {
        "id": new_id(),
        "created_at": created,
    }


def touch(resource):
    resource["updated_at"] = clock.format_timestamp(clock.now())
    resource["version"] = resource.get("version", 0) + 1


def check_version(resource, supplied_version):
    from errors import APIError
    if supplied_version is not None:
        if supplied_version != resource["version"]:
            raise APIError("ERR_VERSION_CONFLICT", "Version conflict")

"""Path-param resolution (left-to-right existence) and ownership checks."""
from db import store
from errors import err


def get_shop(shop_id):
    s = store.shops.get(shop_id)
    if s is None:
        raise err("ERR_NOT_FOUND", "Shop not found")
    return s


def get_project_in_shop(shop_id, project_id):
    """Shop existence checked first, then project, then project belongs to shop."""
    get_shop(shop_id)
    p = store.projects.get(project_id)
    if p is None or p["shop_id"] != shop_id:
        raise err("ERR_NOT_FOUND", "Project not found")
    return p


def get_customer_in_shop(shop_id, customer_id):
    get_shop(shop_id)
    c = store.customers.get(customer_id)
    if c is None or c["shop_id"] != shop_id:
        raise err("ERR_NOT_FOUND", "Customer not found")
    return c


def get_material_in_shop(shop_id, material_id):
    get_shop(shop_id)
    m = store.materials.get(material_id)
    if m is None or m["shop_id"] != shop_id:
        raise err("ERR_NOT_FOUND", "Material not found")
    return m


def get_machine_in_shop(shop_id, machine_id):
    get_shop(shop_id)
    m = store.machines.get(machine_id)
    if m is None or m["shop_id"] != shop_id:
        raise err("ERR_NOT_FOUND", "Machine not found")
    return m


def get_spec_in_project(shop_id, project_id, spec_id):
    get_project_in_shop(shop_id, project_id)
    s = store.specs.get(spec_id)
    if s is None or s["project_id"] != project_id:
        raise err("ERR_NOT_FOUND", "Cabinet spec not found")
    return s


def get_finish_in_project(shop_id, project_id, finish_id):
    get_project_in_shop(shop_id, project_id)
    f = store.finish_selections.get(finish_id)
    if f is None or f["project_id"] != project_id:
        raise err("ERR_NOT_FOUND", "Finish selection not found")
    return f


def get_reservation_in_project(shop_id, project_id, reservation_id):
    get_project_in_shop(shop_id, project_id)
    r = store.reservations.get(reservation_id)
    if r is None or r["project_id"] != project_id:
        raise err("ERR_NOT_FOUND", "Material reservation not found")
    return r


def get_build_job_in_project(shop_id, project_id, build_job_id):
    get_project_in_shop(shop_id, project_id)
    b = store.build_jobs.get(build_job_id)
    if b is None or b["project_id"] != project_id:
        raise err("ERR_NOT_FOUND", "Build job not found")
    return b


def get_change_order_in_project(shop_id, project_id, co_id):
    get_project_in_shop(shop_id, project_id)
    c = store.change_orders.get(co_id)
    if c is None or c["project_id"] != project_id:
        raise err("ERR_NOT_FOUND", "Change order not found")
    return c


def get_draw_in_project(shop_id, project_id, draw_id):
    get_project_in_shop(shop_id, project_id)
    d = store.draws.get(draw_id)
    if d is None or d["project_id"] != project_id:
        raise err("ERR_NOT_FOUND", "Draw not found")
    return d


def get_installation_in_project(shop_id, project_id, installation_id):
    get_project_in_shop(shop_id, project_id)
    i = store.installations.get(installation_id)
    if i is None or i["project_id"] != project_id:
        raise err("ERR_NOT_FOUND", "Installation not found")
    return i


def get_punch_in_installation(shop_id, project_id, installation_id, punch_id):
    get_installation_in_project(shop_id, project_id, installation_id)
    p = store.punch_items.get(punch_id)
    if p is None or p["installation_id"] != installation_id:
        raise err("ERR_NOT_FOUND", "Punch item not found")
    return p


# --------------------------------------------------------------------------
# Ownership (PRD §2.1): entity-backed Customer must own the project.
# --------------------------------------------------------------------------
def require_project_owner(project, user_id, role):
    """For Customer-actor endpoints: X-User-ID must equal the owning customer id."""
    if role == "Customer":
        if project["customer_id"] != user_id:
            raise err("ERR_NOT_RESOURCE_OWNER",
                      "Customer does not own this project")

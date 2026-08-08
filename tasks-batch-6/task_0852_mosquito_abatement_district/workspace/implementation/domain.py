"""Cross-aggregate domain operations shared by several endpoints."""
import calc
import store
from common import ApiError, D, get_body, logical_now, validation


# --------------------------------------------------------------------------
# Assessment staleness
# --------------------------------------------------------------------------


def mark_open_assessments_stale(area_id, reason):
    for assessment in store.RISK_ASSESSMENTS.values():
        if assessment["service_area_id"] != area_id:
            continue
        if assessment["status"] != "OPEN":
            continue
        assessment["is_stale"] = True
        assessment["stale_reason"] = reason
        store.touch(assessment)


def area_of_trap_site(trap_site):
    return store.SERVICE_AREAS.get(trap_site["service_area_id"])


def area_of_collection(collection):
    site = store.TRAP_SITES.get(collection["trap_site_id"])
    if site is None:
        return None
    return store.SERVICE_AREAS.get(site["service_area_id"])


def area_of_pool(pool):
    collection = store.TRAP_COLLECTIONS.get(pool["trap_collection_id"])
    if collection is None:
        return None
    return area_of_collection(collection)


# --------------------------------------------------------------------------
# Posture recomputation + complaint escalation fan-out
# --------------------------------------------------------------------------


def escalate_requests(area):
    """Raise the priority floor across the area's open complaints."""
    floor = calc.POSTURE_FLOOR[area["risk_posture"]]
    rows = [r for r in store.SERVICE_REQUESTS.values()
            if r["service_area_id"] == area["id"]
            and r["handling_status"] in calc.OPEN_HANDLING_STATUSES]
    for request_row in store.ordered(rows):
        current = request_row["priority"]
        if calc.PRIORITY_RANK[floor] > calc.PRIORITY_RANK[current]:
            request_row["priority"] = floor
            if request_row.get("triaged_at") is not None:
                request_row["due_at"] = calc.service_request_due_at(
                    request_row["triaged_at"], floor)
            store.touch(request_row)


def recompute_posture(area):
    """Re-derive posture/posture_source; fan out on a strict escalation."""
    previous = area["risk_posture"]
    posture, source = calc.derive_posture(area)
    changed = (posture != area["risk_posture"] or source != area["posture_source"])
    area["risk_posture"] = posture
    area["posture_source"] = source
    if changed:
        store.touch(area)
    if calc.POSTURE_RANK[posture] > calc.POSTURE_RANK[previous]:
        escalate_requests(area)
    return posture


# --------------------------------------------------------------------------
# Plan / route helpers
# --------------------------------------------------------------------------


def routes_of_plan(plan_id):
    return store.ordered([r for r in store.TREATMENT_ROUTES.values()
                          if r["treatment_plan_id"] == plan_id])


def notifications_of_plan(plan_id):
    return store.ordered([n for n in store.NOTIFICATIONS.values()
                          if n["treatment_plan_id"] == plan_id])


def sensitive_sites_of_area(area_id):
    return store.ordered([s for s in store.SENSITIVE_SITES.values()
                          if s["service_area_id"] == area_id])


def recompute_plan_estimated_total(plan):
    plan["estimated_total_ml"] = calc.plan_estimated_total_ml(plan["id"])
    store.touch(plan)


# --------------------------------------------------------------------------
# Pesticide ledger movements (each advances the product version)
# --------------------------------------------------------------------------


def ledger_commit(product, estimated):
    product["on_hand_ml"] = D(product["on_hand_ml"]) - D(estimated)
    product["committed_ml"] = D(product["committed_ml"]) + D(estimated)
    store.touch(product)


def ledger_execute(product, estimated, actual):
    product["committed_ml"] = D(product["committed_ml"]) - D(estimated)
    product["applied_ml"] = D(product["applied_ml"]) + D(actual)
    product["on_hand_ml"] = D(product["on_hand_ml"]) + (D(estimated) - D(actual))
    store.touch(product)


def ledger_void(product, actual):
    product["applied_ml"] = D(product["applied_ml"]) - D(actual)
    product["on_hand_ml"] = D(product["on_hand_ml"]) + D(actual)
    store.touch(product)


def ledger_release(product, estimated):
    product["committed_ml"] = D(product["committed_ml"]) - D(estimated)
    product["on_hand_ml"] = D(product["on_hand_ml"]) + D(estimated)
    store.touch(product)


# --------------------------------------------------------------------------
# Transition endpoint scaffolding
# --------------------------------------------------------------------------


def read_action(body, actor_map):
    """Return (action, known) after enforcing step-2 actor authorization.

    An action that is not declared for the entity is left for step 7
    (ERR_INVALID_ACTION); a missing action is left for step 6 (ERR_VALIDATION).
    """
    action = body.get("action")
    if isinstance(action, str) and action in actor_map:
        return action, True
    return action, False


def enforce_actor(action, known, actor_map, actor):
    if known and actor_map[action] != actor.role:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "Role %s is not the actor of action %s." % (actor.role, action))


def require_action_supplied(action):
    if not isinstance(action, str) or not action:
        raise validation("Field 'action' is required.")


def require_known_action(action, known):
    if not known:
        raise ApiError("ERR_INVALID_ACTION", 422,
                       "Action '%s' is not declared for this resource." % action)


def invalid_transition(message="The requested transition is not available."):
    return ApiError("ERR_INVALID_TRANSITION", 409, message)


def transition_body():
    return get_body()


# --------------------------------------------------------------------------
# ServiceArea complaint counters (conserved partition)
# --------------------------------------------------------------------------


def counters_move(area, minus, plus):
    if minus:
        area[minus] = area[minus] - 1
    if plus:
        area[plus] = area[plus] + 1
    store.touch(area)


def now():
    return logical_now()

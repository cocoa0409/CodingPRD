"""Small shared helpers for the route modules."""
from errors import ApiError


def find(store, entity_id, error_id):
    """Existence check: resolve an id in a store or raise the catalogued 404."""
    entity = store.get(entity_id) if isinstance(entity_id, str) else None
    if entity is None:
        raise ApiError(error_id, "%s does not identify an existing resource" % entity_id)
    return entity


def maybe(store, entity_id):
    return store.get(entity_id) if isinstance(entity_id, str) else None


def filter_by(items, field, value):
    if value is None:
        return items
    return [item for item in items if item.get(field) == value]


def require_reason(payload, field):
    """Conditionally required free-text reason -> check 5 (ERR_INVALID_REQUEST)."""
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ApiError("ERR_INVALID_REQUEST", "'%s' is required and must be non-empty" % field)
    return value


def unique_code(store, error_id="ERR_DUPLICATE_RESOURCE_CODE", **scope):
    """Duplicate business-code check inside the declared uniqueness scope."""
    for entity in store.values():
        if all(entity.get(field) == value for field, value in scope.items()):
            raise ApiError(error_id, "business code already used in its uniqueness scope")

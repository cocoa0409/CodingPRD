"""Small shared lookup helpers used by every route module."""
import store
from errors import fail


def path_lookup(collection, rid):
    """Path-templated resource existence (precedence step 5)."""
    rec = store.get(collection, rid)
    if rec is None:
        fail("ERR_RESOURCE_NOT_FOUND", "%s %s does not exist" % (collection[:-1], rid))
    return rec


def fk_lookup(collection, rid):
    """Request-body foreign-key existence (precedence step 6)."""
    rec = store.get(collection, rid)
    if rec is None:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND",
             "Referenced %s %s does not exist" % (collection[:-1], rid))
    return rec


def unique_or_fail(collection, field, value, case_insensitive=False):
    needle = value.lower() if case_insensitive else value
    for rec in store.all_of(collection):
        current = rec[field]
        if case_insensitive:
            current = current.lower()
        if current == needle:
            fail("ERR_DUPLICATE_RESOURCE", "%s '%s' already exists" % (field, value))

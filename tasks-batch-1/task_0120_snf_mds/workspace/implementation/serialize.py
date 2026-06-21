"""Serialization: present stored records as API resources.

Strips internal bookkeeping fields (those prefixed with '_'). The stored dicts
already hold exactly the PRD-declared fields plus system fields, so a generic
strip is sufficient and keeps field names verbatim from the scaffold.
"""


def public(obj):
    if obj is None:
        return None
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def public_list(objs):
    return [public(o) for o in objs]

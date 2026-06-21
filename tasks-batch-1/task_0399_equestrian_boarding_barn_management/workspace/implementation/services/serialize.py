"""Public serialization of entities — drops internal '_'-prefixed keys.

Entities are stored as plain dicts already carrying their declared field names
(per scaffold §1.1), so serialization is just stripping internal bookkeeping keys.
"""


def view(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def view_list(entities):
    return [view(e) for e in entities]

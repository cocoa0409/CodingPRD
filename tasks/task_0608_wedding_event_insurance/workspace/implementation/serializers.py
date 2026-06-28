"""Public serialization of entities into response `data` payloads.

Entities are stored as plain dicts whose keys already match the public field
names; serialization is a shallow copy that drops any internal bookkeeping keys
(prefixed with an underscore).
"""


def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}

"""Entity serializers — produce the exact public JSON view of each entity.

Internal bookkeeping keys (those starting with "_") are stripped. Field order
follows the entity tables in SCAFFOLD.yaml §1.1.
"""

_INTERNAL_PREFIX = "_"


def _public(entity):
    return {k: v for k, v in entity.items() if not k.startswith(_INTERNAL_PREFIX)}


# Each entity is stored already containing only its public fields plus optional
# "_seq" bookkeeping. A simple strip is therefore sufficient for all entities.
def serialize(entity):
    return _public(entity)


def serialize_list(entities):
    return [_public(e) for e in entities]

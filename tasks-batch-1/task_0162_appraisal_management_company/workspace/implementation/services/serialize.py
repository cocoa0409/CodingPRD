"""Public serialization: strip internal keys (those starting with '_')."""


def public(obj):
    if obj is None:
        return None
    return {k: v for k, v in obj.items() if not k.startswith("_")}

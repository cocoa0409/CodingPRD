"""Entity -> public JSON view. Strips internal-only keys (leading underscore)."""


def view(obj):
    if obj is None:
        return None
    return {k: v for k, v in obj.items() if not k.startswith("_")}

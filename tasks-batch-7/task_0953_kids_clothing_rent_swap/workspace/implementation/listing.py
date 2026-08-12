"""List-endpoint helpers: member scoping and filter conjunction."""


def scope_to_member(caller, rows, owner_of):
    """PRD 4 / roles table: a Member's GET reads are scoped to its own resources."""
    if not caller.is_member:
        return rows
    return [r for r in rows if owner_of(r) == caller.user_id]


def eq(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]

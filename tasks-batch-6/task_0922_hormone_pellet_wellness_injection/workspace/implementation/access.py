"""Validation rungs 6, 7 and 8 -- existence and ownership (PRD 2.9)."""
import config
import store
from errors import ApiError, NOT_FOUND

# Rung 7's fixed resolution order, so a payload carrying two bad references
# always reports the same one.
FK_ORDER = (
    ("patient_id", "Patient"),
    ("provider_id", "Provider"),
    ("physician_id", "Provider"),
    ("published_by_provider_id", "Provider"),
    ("reported_by_provider_id", "Provider"),
    ("ordered_by_provider_id", "Provider"),
    ("consult_id", "Consult"),
    ("standing_order_id", "StandingOrder"),
    ("consent_record_id", "ConsentRecord"),
    ("lab_panel_id", "LabPanel"),
    ("lot_id", "PelletLot"),
    ("procedure_id", "Procedure"),
    ("injection_visit_id", "InjectionVisit"),
    ("series_pack_id", "SeriesPack"),
    ("membership_id", "Membership"),
)

# The three positions that must name a PHYSICIAN-class provider (PRD 2.1).
PHYSICIAN_ONLY_FK = ("physician_id", "published_by_provider_id")


def path_row(table, row_id):
    """Rung 6 -- a path-segment resource id resolves."""
    row = store.get(table, row_id)
    if row is None:
        raise ApiError(NOT_FOUND[table])
    return row


def resolve_fks(ctx, names):
    """Rung 7 -- every supplied foreign key resolves, in the fixed order."""
    resolved = {}
    for key, table in FK_ORDER:
        if key not in names:
            continue
        if not ctx.has(key):
            continue
        value = ctx.get(key)
        if value is None:
            continue
        row = store.get(table, value)
        if row is None:
            raise ApiError(NOT_FOUND[table])
        resolved[key] = row
    return resolved


def require_physician_class(resolved, keys=PHYSICIAN_ONLY_FK):
    """Only a PHYSICIAN may author a protocol, a consult or a standing order.

    PRD 2.1 routes a wrong licensure class here as a request-shape violation.
    """
    for key in keys:
        row = resolved.get(key)
        if row is not None and row.get("provider_type") != "PHYSICIAN":
            raise ApiError(
                "ERR_VALIDATION",
                "%s must name a provider whose provider_type is PHYSICIAN." % key,
            )


def acting_provider(ctx):
    """Rung 8 -- a Physician or NurseInjector must supply a Provider id."""
    if ctx.role not in config.PROVIDER_BACKED_ROLES:
        return None
    row = store.get("Provider", ctx.user_id)
    if row is None:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    return row


def patient_scope(ctx, patient_id):
    """Rung 8 -- a Patient may only address rows whose patient_id is theirs."""
    if ctx.role != config.ROLE_PATIENT:
        return
    if patient_id != ctx.user_id:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")


def ownership(ctx, patient_id=None):
    """The full rung-8 sweep for an endpoint addressing at most one patient."""
    acting_provider(ctx)
    if patient_id is not None:
        patient_scope(ctx, patient_id)


def standing_order_author(ctx, order):
    """Rung 8 -- revoke and reinstate require the authoring physician."""
    if ctx.user_id != order["physician_id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")

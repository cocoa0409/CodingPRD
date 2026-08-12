"""The compliance calendar (PRD 3.4, 3.5, 3.6)."""

import envelope
import listing
import lookup
import serializers
import timeutil
from constants import OBLIGATION_TYPES
from dispatch import endpoint, query_filter
from errors import ApiError
from services import obligations as obligation_service
from services import rollups, rules
from store import DB, new_row, touch

READ_ROLES = ["PlatformAdmin", "ComplianceOfficer", "FilingAgent", "ClientContact"]


@endpoint(
    "POST",
    "/registrations/{id}/compliance-obligations",
    roles=["ComplianceOfficer"],
    success_code=201,
)
def create_obligation(context):
    registration = context.row
    body = context.body
    obligation_type = body.enum("obligation_type", OBLIGATION_TYPES, required=True)
    period_year = body.integer("period_year", required=True, minimum=2020, maximum=2039)
    body.check_enums()  # rung 14

    entity = lookup.entity_of_registration(registration)
    client = lookup.client_of_entity(entity)
    clock_date = timeutil.today()

    # Declared gate order (PRD 2.9.1): 18, then 21, then 22.  Rung 15 does not
    # apply here at all -- the operation takes no version field.
    rule = rules.select(registration["state_code"], clock_date)  # rung 18
    for existing in lookup.obligations_of_registration(registration["id"]):  # rung 21
        if (
            existing["obligation_type"] == obligation_type
            and existing["period_year"] == period_year
            and existing["status"] != "VOIDED"
        ):
            raise ApiError("ERR_DUPLICATE_OBLIGATION")
    if obligation_type in ("BOI_INITIAL", "BOI_UPDATE") and registration[
        "registration_kind"
    ] != "HOME":  # rung 22
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Beneficial-ownership obligations require a HOME registration.",
        )

    due_date, grace_end_date, delinquency_date = obligation_service.derive_all_dates(
        entity, rule, period_year
    )
    state_fee = obligation_service.state_fee_for(obligation_type, rule)
    franchise_tax = obligation_service.franchise_tax_for(obligation_type, entity, rule)
    late_fee = obligation_service.late_fee_for(
        state_fee, franchise_tax, grace_end_date, rule, clock_date
    )
    # measured BEFORE the new row is inserted
    service_fee = obligation_service.service_fee_for(client["id"])

    row = new_row(
        DB.obligations,
        {
            "registration_id": registration["id"],
            "governing_rule_id": rule["id"],
            "obligation_type": obligation_type,
            "period_year": period_year,
            "rule_determination_date": clock_date,
            "due_date": due_date,
            "grace_end_date": grace_end_date,
            "delinquency_date": delinquency_date,
            "status": "SCHEDULED",
            "state_fee_cents": state_fee,
            "franchise_tax_cents": franchise_tax,
            "late_fee_cents": late_fee,
            "service_fee_cents": service_fee,
            "total_due_cents": 0,
            "satisfied_on": None,
        },
    )
    obligation_service.recompute_total(row)
    obligation_service.mint_reminder_ladder(row)
    rollups.cascade_from_obligation(row)
    return envelope.object_response(serializers.obligation(row), 201)


@endpoint("GET", "/compliance-obligations", roles=READ_ROLES, success_code=200)
def list_obligations(context):
    rows = list(DB.obligations.values())
    if context.is_client_contact:
        allowed = {r["id"] for r in lookup.registrations_of_client(context.user_id)}
        rows = [o for o in rows if o["registration_id"] in allowed]
    rows = listing.apply_filters(
        rows,
        [
            ("registration_id", "registration_id"),
            ("governing_rule_id", "governing_rule_id"),
            ("obligation_type", "obligation_type"),
            ("status", "status"),
        ],
    )
    return listing.respond(rows, serializers.obligation)


@endpoint("GET", "/compliance-obligations/{id}", roles=READ_ROLES, success_code=200)
def read_obligation(context):
    return envelope.object_response(serializers.obligation(context.row))


@endpoint(
    "POST", "/compliance-obligations/{id}/waive", roles=["PlatformAdmin"], success_code=200
)
def waive_obligation(context):
    obligation = context.row
    context.body.string("waiver_reason", required=True, non_empty=False)
    if obligation["status"] not in ("DUE_SOON", "IN_GRACE", "DELINQUENT"):  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    obligation_service.to_terminal(obligation, "WAIVED", zero_total=True)
    obligation_service.cure_registration(DB.registrations.get(obligation["registration_id"]))
    rollups.cascade_from_obligation(obligation)
    return envelope.object_response(serializers.obligation(obligation))


@endpoint(
    "GET",
    "/compliance-obligations/{id}/reminders",
    roles=["PlatformAdmin", "ComplianceOfficer", "ClientContact"],
    success_code=200,
)
def list_reminders(context):
    rows = lookup.reminders_of_obligation(context.row["id"])
    status = query_filter("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return listing.respond(rows, serializers.reminder)


@endpoint(
    "POST", "/registrations/{id}/calendar-rebuild", roles=["ComplianceOfficer"], success_code=200
)
def calendar_rebuild(context):
    registration = context.row
    rebuild_types = context.body.string_list(
        "rebuild_types", required=True, allowed=OBLIGATION_TYPES
    )
    entity = lookup.entity_of_registration(registration)

    rebuilt = 0
    preserved = 0
    rearmed = 0
    for obligation in lookup.obligations_of_registration(registration["id"]):
        eligible = (
            obligation["obligation_type"] in rebuild_types and obligation["status"] == "SCHEDULED"
        )
        if not eligible:
            preserved += 1
            continue
        # re-derived under the obligation's OWN pinned rule version; the
        # entity's CURRENT formation_date and fiscal-year-end fields are read.
        rule = DB.state_rules.get(obligation["governing_rule_id"])
        if rule is None:  # pragma: no cover - defensive
            preserved += 1
            continue
        due, grace_end, delinquency = obligation_service.derive_all_dates(
            entity, rule, obligation["period_year"]
        )
        if due == obligation["due_date"]:
            preserved += 1
            continue
        obligation["due_date"] = due
        obligation["grace_end_date"] = grace_end
        obligation["delinquency_date"] = delinquency
        touch(obligation)
        rebuilt += 1
        for notice in lookup.reminders_of_obligation(obligation["id"]):
            if notice["status"] in ("PENDING", "SENT") and notice["due_date_snapshot"] != due:
                notice["status"] = "REARMED"
                touch(notice)
                rearmed += 1
        obligation_service.mint_reminder_ladder(obligation)

    rollups.cascade_from_registration(registration)
    return envelope.object_response(
        {
            "registration_id": registration["id"],
            "rebuilt_count": rebuilt,
            "preserved_count": preserved,
            "reminders_rearmed": rearmed,
        }
    )

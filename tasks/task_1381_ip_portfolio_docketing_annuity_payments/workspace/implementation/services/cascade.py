"""Cascading state changes (PRD §2.10, §3.5, §3.6, §3.9) and the docket sweep.

Every cascade touch is an ordinary mutation: it refreshes updated_at and
increments version on each affected resource, and reconciles the derived
counters (application.open_docket_count, family.committed_forecast_cents) in
the same write.
"""

import db as dbmod
from services.common import bump

ENTRY_OPEN = {"PENDING", "IN_PROGRESS"}                    # counted in open_docket_count
ENTRY_NONTERMINAL = {"PENDING", "IN_PROGRESS", "RESPONSE_FILED"}
OBLIGATION_NONTERMINAL = {
    "SCHEDULED", "PENDING_AUTHORIZATION", "AUTHORIZED",
    "PAYMENT_INSTRUCTED", "CONFIRMATION_QUERY",
}
OBLIGATION_COMMITTED = {"AUTHORIZED", "PAYMENT_INSTRUCTED", "CONFIRMATION_QUERY"}
INSTRUCTION_NONTERMINAL = {"DRAFT", "SENT", "ACKNOWLEDGED", "CONFIRMED"}


def current_authorization(obligation_id):
    """The obligation's live authorization (REQUESTED / APPROVED / RELEASED), if any."""
    for auth in dbmod.DB["authorizations"].values():
        if auth["annuity_obligation_id"] == obligation_id and auth["status"] in (
            "REQUESTED", "APPROVED", "RELEASED",
        ):
            return auth
    return None


def instructions_of_entry(entry_id):
    return [
        ins for ins in dbmod.DB["instructions"].values()
        if ins.get("docket_entry_id") == entry_id
    ]


def office_action_of_entry(entry_id):
    for oa in dbmod.DB["office_actions"].values():
        if oa.get("docket_entry_id") == entry_id:
            return oa
    return None


def cancel_instruction(instruction):
    instruction["status"] = "CANCELLED"
    bump(instruction)


def cancel_entry(entry, cascade_linked):
    """Entry -> CANCELLED. Decrements open_docket_count when the entry was
    counted (PENDING / IN_PROGRESS). cascade_linked=True applies the
    entry-cancellation cascade (linked instructions cancelled, referencing
    office action closed) used by application abandonment/lapse."""
    was_counted = entry["status"] in ENTRY_OPEN
    entry["status"] = "CANCELLED"
    bump(entry)
    if was_counted:
        app = dbmod.DB["applications"][entry["application_id"]]
        app["open_docket_count"] -= 1
        bump(app)
    if cascade_linked:
        for ins in instructions_of_entry(entry["id"]):
            if ins["status"] in INSTRUCTION_NONTERMINAL:
                cancel_instruction(ins)
        oa = office_action_of_entry(entry["id"])
        if oa is not None and oa["status"] in ("RECEIVED", "UNDER_RESPONSE"):
            oa["status"] = "CLOSED"
            bump(oa)


def cancel_obligation(obligation):
    """Obligation -> CANCELLED. Committed states compensate the family rollup
    and supersede the current authorization."""
    if obligation["status"] in OBLIGATION_COMMITTED:
        family = dbmod.DB["families"][
            dbmod.DB["applications"][obligation["application_id"]]["family_id"]
        ]
        family["committed_forecast_cents"] -= obligation["authorized_amount_cents"]
        bump(family)
        auth = current_authorization(obligation["id"])
        if auth is not None:
            auth["status"] = "SUPERSEDED"
            bump(auth)
        obligation["authorized_amount_cents"] = None
    obligation["status"] = "CANCELLED"
    bump(obligation)


def application_terminal_cascade(app, target_status):
    """Application -> ABANDONED | LAPSED with the full hop-2/hop-3 cascade
    (PRD §3.6 / §3.9): entries cancelled (each firing its linked-instruction
    and office-action cascade), obligations cancelled with rollup
    compensation, and unlinked non-terminal instructions cancelled."""
    app["status"] = target_status
    bump(app)

    entries = [
        e for e in dbmod.DB["docket_entries"].values()
        if e["application_id"] == app["id"] and e["status"] in ENTRY_NONTERMINAL
    ]
    for entry in entries:
        cancel_entry(entry, cascade_linked=True)

    obligations = [
        o for o in dbmod.DB["obligations"].values()
        if o["application_id"] == app["id"] and o["status"] in OBLIGATION_NONTERMINAL
    ]
    for ob in obligations:
        cancel_obligation(ob)

    unlinked = [
        ins for ins in dbmod.DB["instructions"].values()
        if ins["application_id"] == app["id"]
        and ins["status"] in INSTRUCTION_NONTERMINAL
        and not ins.get("docket_entry_id")
    ]
    for ins in unlinked:
        cancel_instruction(ins)


def run_sweep():
    """The operator-run docket sweep (PRD §3.9) against the logical clock.

    Entries first, in ascending (current_due_date, created_at) order, with
    cascade mutations effective immediately (an entry cancelled before its
    turn is skipped and counted as cancelled, not lapsed). Then overdue
    obligations lapse (superseding REQUESTED authorizations); finally every
    GRANTED application that had an obligation lapse in this run lapses with
    the full application-lapse cascade.
    """
    today = dbmod.current_date()
    entries_lapsed = 0
    obligations_lapsed = 0
    applications_lapsed = 0
    superseded = 0

    entry_candidates = sorted(
        (
            e for e in dbmod.DB["docket_entries"].values()
            if e["status"] in ENTRY_OPEN and e["current_due_date"] < today
        ),
        key=lambda e: (e["current_due_date"], e["created_at"]),
    )
    for entry in entry_candidates:
        if entry["status"] not in ENTRY_OPEN:
            continue  # cancelled by an application-lapse cascade before its turn
        entry["status"] = "LAPSED"
        bump(entry)
        entries_lapsed += 1
        app = dbmod.DB["applications"][entry["application_id"]]
        app["open_docket_count"] -= 1
        bump(app)
        if entry["entry_type"] == "STATUTORY" and app["status"] in ("PENDING", "GRANTED"):
            application_terminal_cascade(app, "LAPSED")
            applications_lapsed += 1

    obligation_candidates = sorted(
        (
            o for o in dbmod.DB["obligations"].values()
            if o["status"] in ("SCHEDULED", "PENDING_AUTHORIZATION")
            and o["surcharge_window_end"] < today
        ),
        key=lambda o: (o["surcharge_window_end"], o["created_at"]),
    )
    lapsed_app_ids = []
    for ob in obligation_candidates:
        if ob["status"] not in ("SCHEDULED", "PENDING_AUTHORIZATION"):
            continue  # cancelled by an application-lapse cascade before its turn
        was_pending_authorization = ob["status"] == "PENDING_AUTHORIZATION"
        ob["status"] = "LAPSED"
        bump(ob)
        obligations_lapsed += 1
        if was_pending_authorization:
            auth = current_authorization(ob["id"])
            if auth is not None and auth["status"] == "REQUESTED":
                auth["status"] = "SUPERSEDED"
                bump(auth)
                superseded += 1
        app = dbmod.DB["applications"][ob["application_id"]]
        if app["status"] == "GRANTED" and app["id"] not in lapsed_app_ids:
            lapsed_app_ids.append(app["id"])

    for app_id in lapsed_app_ids:
        app = dbmod.DB["applications"][app_id]
        if app["status"] == "GRANTED":
            application_terminal_cascade(app, "LAPSED")
            applications_lapsed += 1

    return {
        "entries_lapsed": entries_lapsed,
        "obligations_lapsed": obligations_lapsed,
        "applications_lapsed": applications_lapsed,
        "obligations_superseded_authorizations": superseded,
    }

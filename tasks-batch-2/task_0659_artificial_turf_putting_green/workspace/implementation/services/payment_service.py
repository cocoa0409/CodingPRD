"""Payment settlement driver (PRD 3.7, 3.12 / SCAFFOLD §1.2 Payment machine).

Only SETTLED payments count in the ledger. Settlement drives the project ledger
and may advance both status dimensions:
  - DEPOSIT settle  -> finance DEPOSIT_DUE -> DEPOSIT_SETTLED,
                       workflow QUOTED -> DEPOSIT_PAID (copies contract_total).
  - BALANCE settle  -> finance BALANCE_DUE -> PAID_IN_FULL.
  - REFUND settle   -> finance -> REFUNDED.
"""

from common import touch
from errors import err
from services.project_service import (
    accepted_quote,
    compute_ledger,
    recompute_rollups,
)


def settle_payment(payment, project):
    """Settle a PENDING payment and apply the resulting project-status advances.

    Pre-validates the deposit-sufficiency rule (priority 18) for DEPOSIT kind so
    that an under-deposit settle is rejected with ERR_DEPOSIT_INSUFFICIENT before
    any mutation. All other kinds always settle.
    """
    kind = payment["kind"]

    if kind == "DEPOSIT":
        aq = accepted_quote(project["id"])
        # Cumulative settled deposit including the row about to settle.
        prior = compute_ledger(project, include_pending=False)["deposit_paid_cents"]
        prospective = prior + payment["amount_cents"]
        required = aq["deposit_amount_cents"] if aq is not None else 0
        if prospective < required:
            # Under-deposit: the settled deposit total stays below the required
            # amount (priority 18). Reject before mutating anything.
            raise err(
                "ERR_DEPOSIT_INSUFFICIENT",
                "Settled deposit total is below the required deposit amount.",
            )

    # Commit the settlement.
    payment["status"] = "SETTLED"

    # Recompute project rollups against the new settled set.
    recompute_rollups(project)
    project_mutated = False

    if kind == "DEPOSIT":
        aq = accepted_quote(project["id"])
        required = aq["deposit_amount_cents"] if aq is not None else 0
        deposit_paid = project["deposit_paid_cents"]
        if (
            aq is not None
            and deposit_paid >= required
            and project["finance_status"] == "DEPOSIT_DUE"
        ):
            project["finance_status"] = "DEPOSIT_SETTLED"
            if project["workflow_status"] == "QUOTED":
                project["workflow_status"] = "DEPOSIT_PAID"
            # contract_total copied from the accepted quote at the crossing.
            project["contract_total_cents"] = aq["total_cents"]
            recompute_rollups(project)
            project_mutated = True

    elif kind == "BALANCE":
        if project["finance_status"] == "BALANCE_DUE":
            if (
                project["deposit_paid_cents"] + project["balance_paid_cents"]
                >= project["contract_total_cents"]
            ):
                project["finance_status"] = "PAID_IN_FULL"
                project_mutated = True

    elif kind == "REFUND":
        if project["finance_status"] in ("DEPOSIT_DUE", "DEPOSIT_SETTLED", "BALANCE_DUE"):
            project["finance_status"] = "REFUNDED"
            project_mutated = True

    if project_mutated:
        touch(project)

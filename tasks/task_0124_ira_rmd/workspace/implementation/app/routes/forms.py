"""Form 1099-R list + lifecycle endpoints."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_AUDITOR, ROLE_COMPLIANCE, ROLE_CUSTODIAN, ROLE_PARTICIPANT, require_roles
from ..clock import current_year
from ..errors import (
    err_invalid_state,
    err_not_found,
    err_participant_deceased,
    err_validation,
)
from ..helpers import parse_pagination, paginate, query_int, require_json_object
from ..responses import listing, ok
from ..services.lookups import (
    get_account_or_404,
    get_distribution_or_404,
    get_form_or_404,
    get_participant_or_404,
)
from ..services.serialize import serialize_form_1099r
from ..store import store

bp = Blueprint("forms", __name__)


# ---------------------------------------------------------------------------
# List by participant
# ---------------------------------------------------------------------------

@bp.get("/participants/<participant_id>/forms-1099r")
@require_roles(ROLE_PARTICIPANT, ROLE_CUSTODIAN, ROLE_COMPLIANCE, ROLE_AUDITOR)
def list_forms(participant_id: str, **kw):
    role = kw.get("_caller_role")
    caller = kw.get("_caller_id")
    get_participant_or_404(participant_id)
    if role == ROLE_PARTICIPANT and caller != participant_id:
        raise err_not_found(f"Participant {participant_id} not found")
    tax_year = query_int("tax_year", required=True)
    limit, offset = parse_pagination()

    # Filter: recipient + tax_year + status != VOIDED
    matching = [
        f
        for f in store().forms_1099r.values()
        if f["recipient_participant_id"] == participant_id
        and f["tax_year"] == tax_year
        and f["status"] != "VOIDED"
    ]
    # Sort by source_event_id ascending (per scaffold tax_year_aggregate_for_form1099r)
    matching.sort(key=lambda f: f["source_event_id"])
    total = len(matching)
    page = paginate(matching, limit, offset)
    return listing([serialize_form_1099r(f) for f in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Correct / Void
# ---------------------------------------------------------------------------

@bp.post("/forms-1099r/<form_id>/correct")
@require_roles(ROLE_COMPLIANCE)
def correct_form(form_id: str, **_kw):
    require_json_object()
    with store().lock:
        form = get_form_or_404(form_id)
        if form["status"] != "ISSUED":
            raise err_invalid_state(f"Form is {form['status']}; must be ISSUED to correct")
        participant = get_participant_or_404(form["recipient_participant_id"])
        if participant["is_deceased"]:
            raise err_participant_deceased()

        # Recompute box2a_taxable_amount_cents from latest snapshot of source event
        _recompute_box2a(form)
        form["status"] = "CORRECTED"
        # Note: Form1099R is an event-style entity (no version/updated_at).
        return ok(serialize_form_1099r(form))


@bp.post("/forms-1099r/<form_id>/void")
@require_roles(ROLE_COMPLIANCE)
def void_form(form_id: str, **_kw):
    require_json_object()
    with store().lock:
        form = get_form_or_404(form_id)
        if form["status"] not in ("ISSUED", "CORRECTED"):
            raise err_invalid_state(f"Form is {form['status']}; cannot void")

        # Decease cascade override: current-year ISSUED forms on deceased
        # participant's accounts cannot be voided.
        participant = store().participants.get(form["recipient_participant_id"])
        if (
            participant is not None
            and participant.get("is_deceased")
            and form["status"] == "ISSUED"
            and form["tax_year"] == current_year()
        ):
            raise err_invalid_state(
                "Form is current-year ISSUED for a deceased participant — void blocked"
            )

        # Only possible when source event is REVERSED (which only happens for
        # EXCESS_PENALTY tied to a reversed ContributionEvent — but the
        # scaffold's penalty isn't directly tied to a contribution. We accept
        # any EXCESS_PENALTY form whose underlying ContributionEvent backing
        # the excess (if any) is REVERSED. Practical implementation: the
        # ExcessPenalty entity has no source_contribution_id pointer in the
        # scaffold, so we infer "reversed source" by: source event type is
        # EXCESS_PENALTY AND the account's contributions for that tax_year all
        # have status REVERSED or zero.)
        if form["source_event_type"] != "EXCESS_PENALTY":
            raise err_invalid_state(
                "Only EXCESS_PENALTY forms backed by a reversed contribution may be voided"
            )

        penalty = store().excess_penalties.get(form["source_event_id"])
        if penalty is None:
            raise err_invalid_state("Excess penalty source not found")
        # Heuristic: there must exist at least one REVERSED ContributionEvent
        # on the account for the form's tax_year (the contribution-reversal
        # endpoint sets status=REVERSED).
        any_reversed = any(
            c["account_id"] == penalty["account_id"]
            and c["tax_year"] == form["tax_year"]
            and c["status"] == "REVERSED"
            for c in store().contributions.values()
        )
        if not any_reversed:
            raise err_invalid_state(
                "Underlying source event has not been reversed"
            )

        form["status"] = "VOIDED"
        return ok(serialize_form_1099r(form))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _recompute_box2a(form: dict) -> None:
    """Per scaffold §1.3.tax_year_aggregate_for_form1099r — refresh from source."""
    set_t = form["source_event_type"]
    if set_t == "EXCESS_PENALTY":
        penalty = store().excess_penalties.get(form["source_event_id"])
        if penalty is None:
            return
        form["box1_gross_distribution_cents"] = penalty["excess_amount_cents"]
        form["box2a_taxable_amount_cents"] = penalty["excess_amount_cents"]
        form["box4_federal_withholding_cents"] = 0
        form["box7_distribution_code"] = "8"
    elif set_t == "DISTRIBUTION":
        d = store().distributions.get(form["source_event_id"])
        if d is None:
            return
        account = store().accounts.get(d["account_id"])
        if account is None:
            return
        form["box1_gross_distribution_cents"] = d["gross_amount_cents"]
        form["box4_federal_withholding_cents"] = d["federal_withholding_cents"]
        reason = d["distribution_reason"]
        if reason == "EARLY":
            form["box7_distribution_code"] = "1"
        elif reason == "NORMAL":
            form["box7_distribution_code"] = "7"
        elif reason == "DEATH":
            form["box7_distribution_code"] = "4"
        elif reason == "RMD":
            form["box7_distribution_code"] = "7"
        form["box2a_taxable_amount_cents"] = (
            d["gross_amount_cents"] if account["account_type"] == "TRADITIONAL" else 0
        )
    elif set_t == "CONVERSION":
        # Find conversion request whose completed_distribution_id matches
        # form.source_event_id (form.source_event_id stores conversion id per
        # issue_form_for_conversion).
        cr = store().conversions.get(form["source_event_id"])
        if cr is None:
            return
        form["box1_gross_distribution_cents"] = cr["amount_cents"]
        form["box7_distribution_code"] = "G"
        form["box4_federal_withholding_cents"] = 0
        form["box2a_taxable_amount_cents"] = 0 if cr["backdoor_flag"] else cr["amount_cents"]

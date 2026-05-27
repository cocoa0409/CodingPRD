"""Fee payments ledger."""

from flask import Blueprint, request

from db import db, new_id
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from services.body import (
    get_json_body,
    require_string,
    require_int,
    require_enum,
    optional_string,
)
from services.calc import (
    filing_fee,
    excess_claims_fee,
    issue_fee,
    extension_fee,
    maintenance_base_fee,
    maintenance_surcharge,
    micro_eligible,
)
from services.pagination import parse_pagination, slice_sorted
from services.serialize import fee_payment_to_wire
from services.application_svc import (
    APP_TERMINAL_STATES,
    bump_application,
    bump_maintenance_fee,
    recompute_total_fees,
)


bp = Blueprint("fee_payments", __name__)


PAYMENT_CATEGORIES = {
    "FILING",
    "EXCESS_CLAIMS",
    "EXTENSION",
    "ISSUE",
    "MAINTENANCE_W1",
    "MAINTENANCE_W2",
    "MAINTENANCE_W3",
    "PCT_NATIONAL_PHASE",
}
MAINTENANCE_CATEGORIES = {"MAINTENANCE_W1", "MAINTENANCE_W2", "MAINTENANCE_W3"}


def _window_from_category(cat: str) -> int:
    return int(cat[-1])


def _expected_amount(
    category: str,
    application: dict,
    applicant: dict,
    maintenance_fee,
) -> int:
    """Compute server-expected fee for the given category and context."""
    if category == "FILING":
        return filing_fee(application["application_type"], applicant["entity_size"])
    if category == "EXCESS_CLAIMS":
        return excess_claims_fee(
            application["claim_count"],
            application["independent_claim_count"],
            applicant["entity_size"],
        )
    if category == "ISSUE":
        return issue_fee(application["application_type"], applicant["entity_size"])
    if category == "EXTENSION":
        # The expected EXTENSION fee depends on the response's extension_months_requested.
        # The PRD §3.5 wires extension fees to the office-action-response; a standalone
        # EXTENSION fee_payment refers to whatever the most recent OA response on this
        # application requested. If no such response is present, we cannot compute the
        # expected amount and reject as fee-mismatch.
        # Find most recent OAResponse whose office_action's application_id matches.
        candidate_extension_months = None
        latest_created = None
        for resp in db.office_action_responses.values():
            oa = db.office_actions.get(resp["office_action_id"])
            if oa is None:
                continue
            if oa["application_id"] != application["id"]:
                continue
            if latest_created is None or resp["created_at"] > latest_created:
                latest_created = resp["created_at"]
                candidate_extension_months = resp["extension_months_requested"]
        if candidate_extension_months is None:
            # No response — cannot match any extension fee.
            raise_api(
                "ERR_FEE_AMOUNT_MISMATCH",
                "No OfficeActionResponse with extension months found for this application",
            )
        return extension_fee(candidate_extension_months, applicant["entity_size"])
    if category in MAINTENANCE_CATEGORIES:
        assert maintenance_fee is not None
        base = maintenance_fee["base_fee_cents"]
        # Add surcharge iff current_utc > window_due_date
        if db.current_utc_dt() > maintenance_fee["window_due_date"]:
            return int(base) + maintenance_surcharge(applicant["entity_size"])
        return int(base)
    if category == "PCT_NATIONAL_PHASE":
        # Per PRD §3.10 the PCT phase entry endpoint records the entry; there is no
        # PCT national-phase fee defined in §1.3. Reject if a payment with this
        # category is attempted — there is no expected amount the client could match.
        # (Reserved for future expansion; the scaffold lists it but defines no rate.)
        return filing_fee(application["application_type"], applicant["entity_size"])
    raise_api("ERR_INVALID_REQUEST", f"Unknown payment_category: {category}")


@bp.route("/fee-payments", methods=["POST"])
@require_roles("Applicant")
def create_fee_payment(_user_id, _role):
    body = get_json_body()
    application_id = require_string(body, "application_id")
    payment_category = require_enum(body, "payment_category", PAYMENT_CATEGORIES)
    amount_cents = require_int(body, "amount_cents")
    maintenance_fee_id = optional_string(body, "maintenance_fee_id")

    # Priority 5: FK existence (application, then maintenance_fee_id if applicable)
    app = db.applications.get(application_id)
    if app is None:
        raise_api(
            "ERR_APPLICATION_NOT_FOUND",
            f"Application {application_id} not found",
        )

    # FK coherence — maintenance_fee_id required iff MAINTENANCE_W*
    if payment_category in MAINTENANCE_CATEGORIES:
        if not maintenance_fee_id:
            raise_api(
                "ERR_INVALID_REQUEST",
                "maintenance_fee_id is required for MAINTENANCE_W* payments",
            )
        mf = db.maintenance_fees.get(maintenance_fee_id)
        if mf is None:
            raise_api(
                "ERR_APPLICATION_NOT_FOUND",
                f"MaintenanceFee {maintenance_fee_id} not found",
            )
        # The referenced MF must belong to the named application
        if mf["application_id"] != application_id:
            raise_api(
                "ERR_APPLICATION_NOT_FOUND",
                "maintenance_fee_id does not belong to application_id",
            )
        # Window must match category
        expected_window = _window_from_category(payment_category)
        if int(mf["window_number"]) != expected_window:
            raise_api(
                "ERR_INVALID_REQUEST",
                f"maintenance_fee_id is for window {mf['window_number']}, "
                f"payment_category is {payment_category}",
            )
    else:
        if maintenance_fee_id:
            raise_api(
                "ERR_INVALID_REQUEST",
                "maintenance_fee_id must be null for non-maintenance payments",
            )
        mf = None

    applicant = db.applicants.get(app["applicant_id"])
    if applicant is None:
        raise_api(
            "ERR_APPLICATION_NOT_FOUND", "Applicant for this application was not found"
        )

    # Priority 10: VAL-FEE-MICRO-INCOME re-check
    if applicant["entity_size"] == "MICRO" and not micro_eligible(applicant):
        raise_api(
            "ERR_MICRO_INELIGIBLE", "MICRO entity eligibility predicate failed"
        )

    # --- Branch on category for state + extra validations ---------------
    if payment_category in MAINTENANCE_CATEGORIES:
        # Priority 7: terminal lockdown — parent must still be ISSUED
        if app["status"] != "ISSUED":
            if app["status"] in APP_TERMINAL_STATES:
                raise_api(
                    "ERR_TERMINAL_STATE",
                    f"Application status {app['status']} is terminal",
                )
            raise_api(
                "ERR_INVALID_STATE",
                f"Maintenance payment requires ISSUED application (current: {app['status']})",
            )

        # MaintenanceFee lifecycle: PENDING only
        if mf["fee_status"] != "PENDING":
            raise_api(
                "ERR_TERMINAL_STATE",
                f"MaintenanceFee status {mf['fee_status']} is terminal",
            )

        # Priority 14: VAL-MAINT-WINDOW — within [open, grace]
        now = db.current_utc_dt()
        if now < mf["window_open_date"] or now > mf["window_grace_date"]:
            raise_api(
                "ERR_MAINTENANCE_WINDOW_CLOSED",
                "MaintenanceFee payment outside [window_open_date, window_grace_date]",
            )

        # Priority 17: VAL-MAINT-WINDOW-ORDER — earlier windows must be PAID
        target_window = int(mf["window_number"])
        for other_mf in db.maintenance_fees.values():
            if other_mf["application_id"] != application_id:
                continue
            if int(other_mf["window_number"]) < target_window:
                if other_mf["fee_status"] != "PAID":
                    raise_api(
                        "ERR_MAINTENANCE_OUT_OF_ORDER",
                        f"Earlier window {other_mf['window_number']} is not PAID",
                    )

        # Priority 15: VAL-FEE-AMOUNT-EXACT
        expected = _expected_amount(payment_category, app, applicant, mf)
        if amount_cents != expected:
            raise_api(
                "ERR_FEE_AMOUNT_MISMATCH",
                f"Expected {expected} cents, got {amount_cents}",
            )
    else:
        # Non-maintenance payments are accepted only on non-terminal applications.
        if app["status"] in APP_TERMINAL_STATES:
            raise_api(
                "ERR_TERMINAL_STATE",
                f"Application status {app['status']} is terminal",
            )
        # ISSUE category needs status ALLOWED; ISSUE payments should go through
        # /applications/{id}/pay-issue-fee, but if posted here we still treat it
        # as a ledger insert iff status==ALLOWED (state-machine guard).
        if payment_category == "ISSUE" and app["status"] != "ALLOWED":
            raise_api(
                "ERR_INVALID_STATE",
                f"ISSUE payment requires status=ALLOWED (current: {app['status']})",
            )

        # Priority 15: VAL-FEE-AMOUNT-EXACT
        expected = _expected_amount(payment_category, app, applicant, None)
        if amount_cents != expected:
            raise_api(
                "ERR_FEE_AMOUNT_MISMATCH",
                f"Expected {expected} cents, got {amount_cents}",
            )

    # ---- Side effects ----
    now = db.current_utc_dt()
    fp_id = new_id()
    fp = {
        "id": fp_id,
        "application_id": application_id,
        "payment_category": payment_category,
        "amount_cents": amount_cents,
        "maintenance_fee_id": maintenance_fee_id,
        "payment_status": "POSTED",
        "created_at": now,
    }
    db.fee_payments[fp_id] = fp

    # Update parent application's running total + version
    app["total_fees_paid_cents"] = recompute_total_fees(application_id)
    bump_application(app)

    # Maintenance lifecycle update
    if payment_category in MAINTENANCE_CATEGORIES:
        mf["fee_status"] = "PAID"
        mf["paid_at"] = now
        bump_maintenance_fee(mf)

    return success(fee_payment_to_wire(fp), http_status=201)


@bp.route("/fee-payments/<fid>", methods=["GET"])
@require_roles("Applicant", "USPTOAdmin")
def get_fee_payment(fid, **_):
    fp = db.fee_payments.get(fid)
    if fp is None:
        raise_api("ERR_APPLICATION_NOT_FOUND", f"FeePayment {fid} not found")
    return success(fee_payment_to_wire(fp))


@bp.route("/fee-payments", methods=["GET"])
@require_roles("Applicant", "USPTOAdmin")
def list_fee_payments(**_):
    limit, offset = parse_pagination()
    app_filter = request.args.get("application_id")
    mf_filter = request.args.get("maintenance_fee_id")
    items = []
    for fp in db.fee_payments.values():
        if app_filter and fp["application_id"] != app_filter:
            continue
        if mf_filter and fp.get("maintenance_fee_id") != mf_filter:
            continue
        items.append(fp)
    # FeePayment has no updated_at/version; sort by created_at/id which both exist.
    page, total = slice_sorted(items, limit, offset)
    return list_success(
        [fee_payment_to_wire(f) for f in page], limit, offset, total
    )

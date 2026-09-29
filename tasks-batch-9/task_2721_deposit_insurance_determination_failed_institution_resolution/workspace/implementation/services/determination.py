"""Preparation, the five-level certify cascade and the four-level supersession
compensation -- PRD sections 3.4, 3.5 and 3.6.

Cascades are applied in full within the request or not at all: every resource a
cascade touches has its own ``updated_at`` refreshed and its own ``version``
incremented, and a read issued immediately afterwards observes every
consequence.
"""

import db as dbmod
import lookup
from db import db, new_row, touch
from services import insurance

ACTIVE_DETERMINATION_STATUSES = ("DRAFT", "PREPARED", "UNDER_REVIEW", "REVISION_REQUESTED")

PREPARABLE_STATUSES = ("DRAFT", "REVISION_REQUESTED")

METHOD_VARIANTS = ("AGGREGATE_BY_CATEGORY", "PER_ACCOUNT_PROVISIONAL")


def active_determination_of(depositor_id):
    for determination in dbmod.ordered(lookup.determinations_of_depositor(depositor_id)):
        if determination["status"] in ACTIVE_DETERMINATION_STATUSES:
            return determination
    return None


def certified_determination_of(depositor_id):
    for determination in dbmod.ordered(lookup.determinations_of_depositor(depositor_id)):
        if determination["status"] == "CERTIFIED":
            return determination
    return None


def certificate_of(determination_id):
    """The live certificate a determination produced, if it still has one."""
    for certificate in dbmod.ordered(
        lookup.certificates_of_determination(determination_id)
    ):
        if certificate["status"] != "CANCELLED":
            return certificate
    return None


def prepare(determination, depositor, method_variant, user_id):
    """Fill the document in from the ownership-category analysis of PRD 3.5.

    Preparation deliberately does *not* touch any account's ``insurance_status``:
    accounts stay at FROZEN_FOR_DETERMINATION and only reach DETERMINED at
    certification.
    """
    result = insurance.compute(depositor, method_variant)

    determination["method_variant"] = method_variant
    determination["prepared_by_user_id"] = user_id
    determination["prepared_at"] = db.now_iso()
    determination["insured_amount_cents"] = result["insured_amount_cents"]
    determination["uninsured_amount_cents"] = result["uninsured_amount_cents"]
    determination["attributed_total_cents"] = result["attributed_total_cents"]
    determination["category_breakdown"] = result["category_breakdown"]
    determination["_account_attribution"] = result["account_attribution"]
    determination["status"] = "PREPARED"
    touch(determination)

    for account_id, attributed in result["account_attribution"].items():
        account = db.accounts.get(account_id)
        if account is None:
            continue
        if account["attributed_amount_cents"] != attributed:
            account["attributed_amount_cents"] = attributed
            touch(account)

    depositor["attributed_total_cents"] = result["attributed_total_cents"]
    touch(depositor)
    return determination


def certify(determination, depositor, institution, user_id):
    """The five-level certify cascade of PRD section 3.6."""
    attribution = determination.get("_account_attribution") or {}

    # --- level 1: the determination becomes a legal position ------------
    determination["status"] = "CERTIFIED"
    determination["certified_by_user_id"] = user_id
    determination["certified_at"] = db.now_iso()
    touch(determination)

    depositor["certified_insured_cents"] = determination["insured_amount_cents"]
    depositor["certified_uninsured_cents"] = determination["uninsured_amount_cents"]
    touch(depositor)

    # aggregate_insured_cents is recomputed from scratch on every read; the
    # institution row still records the mutation.
    touch(institution)

    # --- level 2: contributing accounts become DETERMINED ---------------
    contributing = []
    for account_id, attributed in attribution.items():
        if attributed <= 0:
            continue
        account = db.accounts.get(account_id)
        if account is None:
            continue
        contributing.append(account)
        if account["insurance_status"] == "FROZEN_FOR_DETERMINATION":
            account["insurance_status"] = "DETERMINED"
            touch(account)

    uninsured = determination["uninsured_amount_cents"]
    held_account_ids = []

    if uninsured > 0:
        # --- level 3: the uninsured hold allocation ---------------------
        for account, hold in insurance.allocate_uninsured_hold(uninsured, attribution):
            if hold > 0:
                account["held_amount_cents"] = hold
                account["hold_status"] = "HELD"
                held_account_ids.append(account["id"])
                touch(account)
            else:
                # An account allocated exactly zero cents stays at NONE.
                if account["held_amount_cents"] != 0:
                    account["held_amount_cents"] = 0
                    touch(account)

        # --- level 4: the receivership certificate ----------------------
        certificate = new_row(
            {
                "insurance_determination_id": determination["id"],
                "depositor_record_id": depositor["id"],
                "institution_id": institution["id"],
                "face_amount_cents": uninsured,
                "cumulative_dividends_cents": 0,
                "last_dividend_amount_cents": 0,
                "last_dividend_round": 0,
                "status": "ISSUED",
                "issued_at": db.now_iso(),
            }
        )
        db.certificates[certificate["id"]] = certificate

    determination["_held_account_ids"] = held_account_ids

    # --- level 5: the depositor notice ----------------------------------
    depositor["notice_status"] = "SENT"
    depositor["notice_template_code"] = (
        "PARTIALLY_UNINSURED" if uninsured > 0 else "FULLY_INSURED"
    )
    depositor["notice_sent_at"] = db.now_iso()
    touch(depositor)
    return determination


def supersede(prior, depositor, institution):
    """The compensating counterpart of the certify cascade (PRD section 3.6).

    Four levels unwind in mirror image, and because the institution's aggregates
    are recomputed from scratch rather than adjusted, they return exactly to
    their pre-certification values.
    """
    # --- level 1 --------------------------------------------------------
    prior["status"] = "SUPERSEDED"
    touch(prior)
    depositor["certified_insured_cents"] = 0
    depositor["certified_uninsured_cents"] = 0
    touch(depositor)
    touch(institution)

    # --- level 2: the certificate it issued is cancelled ----------------
    certificate = certificate_of(prior["id"])
    if certificate is not None:
        certificate["status"] = "CANCELLED"
        touch(certificate)

    # --- level 3: every hold that determination allocated is released ---
    for account_id in prior.get("_held_account_ids") or []:
        account = db.accounts.get(account_id)
        if account is None:
            continue
        if account["hold_status"] == "HELD":
            account["hold_status"] = "RELEASED"
            account["held_amount_cents"] = 0
            touch(account)

    # --- level 4: the notice resets ------------------------------------
    depositor["notice_status"] = "PENDING"
    depositor["notice_template_code"] = None
    depositor["notice_sent_at"] = None
    depositor["acknowledged_at"] = None
    touch(depositor)
    return prior

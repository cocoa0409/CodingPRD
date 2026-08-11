"""Composite setup helpers.

Every test starts against an empty database, so each fixture builds its
preconditions from scratch using only PRD-declared endpoints.  Setup calls use
the lenient `get_success_data` so a broken precondition surfaces as a clear
"Setup failed" rather than as a confusing assertion inside the test body.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    box_payload,
    carrier_rule_payload,
    check_payload,
    disposition_payload,
    flat_payload,
    forward_shipment_payload,
    form_1583_payload,
    id_document_payload,
    letter_payload,
    package_payload,
    plan_tier_payload,
    recipient_payload,
    registered_agent_payload,
    scan_job_payload,
    sop_payload,
)
from .test_users import (
    CMRA_OPERATOR,
    PLATFORM_ADMIN,
    make_box_holder_headers,
    make_compliance_officer_headers,
    make_notary_headers,
)


# ==========================================================================
# Tier 0 — single-call primitives
# ==========================================================================
def set_clock(to_iso8601: str) -> None:
    """Move the logical clock (PlatformAdmin only)."""
    get_success_data(api_client.set_clock(to_iso8601, PLATFORM_ADMIN))


def create_plan_tier(**overrides) -> dict:
    return get_success_data(
        api_client.create_plan_tier(plan_tier_payload(**overrides), PLATFORM_ADMIN)
    )


def create_carrier_rule(**overrides) -> dict:
    return get_success_data(
        api_client.create_carrier_rule(carrier_rule_payload(**overrides), PLATFORM_ADMIN)
    )


def create_box(box_number: str, plan_tier_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_box(
            box_payload(box_number, plan_tier_id, **overrides), CMRA_OPERATOR
        )
    )


def activate_box(box_id: str) -> dict:
    return get_success_data(api_client.activate_box(box_id, CMRA_OPERATOR))


def add_recipient(box_id: str, legal_name: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_recipient(
            box_id, recipient_payload(legal_name, **overrides), CMRA_OPERATOR
        )
    )


def file_id_document(recipient_id: str, doc_class: str, doc_type: str, expires_on: str) -> dict:
    return get_success_data(
        api_client.create_id_document(
            recipient_id, id_document_payload(doc_class, doc_type, expires_on), CMRA_OPERATOR
        )
    )


def verify_id_document(document_id: str) -> dict:
    return get_success_data(api_client.verify_id_document(document_id, CMRA_OPERATOR))


def file_and_verify_id_document(
    recipient_id: str, doc_class: str, doc_type: str, expires_on: str
) -> dict:
    document = file_id_document(recipient_id, doc_class, doc_type, expires_on)
    verify_id_document(document["id"])
    return document


def file_form_1583(recipient_id: str, home_address_line: str = None) -> dict:
    return get_success_data(
        api_client.create_form_1583(
            recipient_id, form_1583_payload(home_address_line), CMRA_OPERATOR
        )
    )


def notarize_form_1583(form_id: str, notary_user_id: str = None) -> dict:
    notary_user_id = notary_user_id or TEST_DEFAULTS["NOTARY_USER_ID"]
    return get_success_data(
        api_client.notarize_form(form_id, make_notary_headers(notary_user_id))
    )


def accept_form_1583(form_id: str, officer_user_id: str = None) -> dict:
    officer_user_id = officer_user_id or TEST_DEFAULTS["OFFICER_USER_ID"]
    return get_success_data(
        api_client.accept_form(form_id, make_compliance_officer_headers(officer_user_id))
    )


def log_mail_item(box_id: str, payload: dict) -> dict:
    return get_success_data(api_client.create_mail_item(box_id, payload, CMRA_OPERATOR))


def match_mail_item(mail_item_id: str, recipient_id: str) -> dict:
    return get_success_data(
        api_client.match_mail_item(
            mail_item_id, {"recipient_id": recipient_id}, CMRA_OPERATOR
        )
    )


def read_box(box_id: str) -> dict:
    return get_success_data(api_client.get_box(box_id, CMRA_OPERATOR))


def read_mail_item(mail_item_id: str) -> dict:
    return get_success_data(api_client.get_mail_item(mail_item_id, CMRA_OPERATOR))


def read_recipient(recipient_id: str) -> dict:
    return get_success_data(api_client.get_recipient(recipient_id, CMRA_OPERATOR))


def read_deposit_batch(batch_id: str) -> dict:
    return get_success_data(api_client.get_deposit_batch(batch_id, CMRA_OPERATOR))


def read_scan_job_list(mail_item_id: str) -> list:
    return get_success_data(api_client.list_scan_jobs(mail_item_id, CMRA_OPERATOR))


def box_version(box_id: str) -> int:
    return read_box(box_id)["version"]


def mail_item_version(mail_item_id: str) -> int:
    return read_mail_item(mail_item_id)["version"]


def deposit_batch_version(batch_id: str) -> int:
    return read_deposit_batch(batch_id)["version"]


def open_billing_cycle(box_id: str) -> dict:
    """The mailbox's first billing cycle (created at activation)."""
    cycles = get_success_data(api_client.list_billing_cycles(box_id, CMRA_OPERATOR))
    assert cycles, f"Setup failed: mailbox {box_id} has no billing cycle"
    return cycles[0]


def open_deposit_batch(box_id: str, business_date: str) -> dict:
    return get_success_data(
        api_client.create_deposit_batch(
            box_id, {"business_date": business_date}, CMRA_OPERATOR
        )
    )


def log_check(
    batch_id: str,
    mail_item_id: str,
    payee_name_on_check: str,
    amount_cents: int,
    endorsed: bool = True,
) -> dict:
    """Log a cheque, re-reading the batch version so the OCC rung passes."""
    version = deposit_batch_version(batch_id)
    return get_success_data(
        api_client.create_check_deposit(
            batch_id,
            check_payload(
                mail_item_id, payee_name_on_check, amount_cents, version, endorsed
            ),
            CMRA_OPERATOR,
        )
    )


def attach_registered_agent(box_id: str, jurisdiction_code: str, retention_days: int = None) -> dict:
    return get_success_data(
        api_client.create_registered_agent(
            box_id, registered_agent_payload(jurisdiction_code, retention_days), PLATFORM_ADMIN
        )
    )


def open_compliance_review(box_id: str, reason: str, officer_user_id: str = None) -> dict:
    officer_user_id = officer_user_id or TEST_DEFAULTS["OFFICER_USER_ID"]
    return get_success_data(
        api_client.create_compliance_review(
            box_id, {"reason": reason}, make_compliance_officer_headers(officer_user_id)
        )
    )


def suspend_compliance_review(review_id: str, officer_user_id: str = None) -> dict:
    officer_user_id = officer_user_id or TEST_DEFAULTS["OFFICER_USER_ID"]
    return get_success_data(
        api_client.suspend_compliance_review(
            review_id, make_compliance_officer_headers(officer_user_id)
        )
    )


def resolve_compliance_review(review_id: str, resolution: str, officer_user_id: str = None) -> dict:
    officer_user_id = officer_user_id or TEST_DEFAULTS["SECOND_OFFICER_USER_ID"]
    return get_success_data(
        api_client.resolve_compliance_review(
            review_id,
            {"resolution": resolution},
            make_compliance_officer_headers(officer_user_id),
        )
    )


# ==========================================================================
# Tier 1 — a mailbox in service with one cleared roster member
# ==========================================================================
def setup_releasable_box(
    box_number: str,
    legal_name: str,
    holder_name: str = None,
    holder_email: str = None,
    plan_id: str = None,
    plan_overrides: dict = None,
    box_overrides: dict = None,
    recipient_overrides: dict = None,
    photo_doc_type: str = "PASSPORT",
    photo_expires_on: str = None,
    address_doc_type: str = "UTILITY_BILL",
    address_expires_on: str = None,
    file_address_document: bool = True,
    home_address_line: str = None,
    notary_user_id: str = None,
    officer_user_id: str = None,
    accept_form: bool = True,
) -> dict:
    """Open a mailbox, put it into service and clear one roster member.

    With the defaults the member ends `AUTHORIZED` and `RELEASABLE`.  Set
    `file_address_document=False` to stop at `ID_SET_INCOMPLETE`, or
    `accept_form=False` to stop at `NO_ACCEPTED_1583`.

    Returns a context dict carrying every id and the holder's headers.
    """
    plan_overrides = dict(plan_overrides or {})
    box_overrides = dict(box_overrides or {})
    recipient_overrides = dict(recipient_overrides or {})

    if plan_id is None:
        plan = create_plan_tier(**plan_overrides)
        plan_id = plan["id"]
    else:
        plan = None

    box_overrides.setdefault("holder_name", holder_name or legal_name)
    box_overrides.setdefault("holder_email", holder_email or "holder@example.com")
    box = create_box(box_number, plan_id, **box_overrides)
    activate_box(box["id"])

    recipient = add_recipient(box["id"], legal_name, **recipient_overrides)

    photo = file_and_verify_id_document(
        recipient["id"],
        "PHOTO",
        photo_doc_type,
        photo_expires_on or TEST_DEFAULTS["PHOTO_EXPIRES_ON"],
    )
    address = None
    if file_address_document:
        address = file_and_verify_id_document(
            recipient["id"],
            "ADDRESS",
            address_doc_type,
            address_expires_on or TEST_DEFAULTS["ADDRESS_EXPIRES_ON"],
        )

    form = file_form_1583(recipient["id"], home_address_line)
    notarize_form_1583(form["id"], notary_user_id)
    if accept_form:
        accept_form_1583(form["id"], officer_user_id)

    return {
        "plan": plan,
        "plan_id": plan_id,
        "box": box,
        "box_id": box["id"],
        "holder_headers": make_box_holder_headers(box["id"]),
        "recipient": recipient,
        "recipient_id": recipient["id"],
        "photo_document": photo,
        "photo_document_id": photo["id"],
        "address_document": address,
        "address_document_id": address["id"] if address else None,
        "form": form,
        "form_id": form["id"],
    }


def clear_additional_recipient(
    box_id: str,
    legal_name: str,
    recipient_overrides: dict = None,
    photo_doc_type: str = "STATE_ID",
    address_doc_type: str = "LEASE",
    photo_expires_on: str = None,
    address_expires_on: str = None,
    home_address_line: str = None,
    notary_user_id: str = None,
    officer_user_id: str = None,
    accept_form: bool = True,
    file_address_document: bool = True,
) -> dict:
    """Add a second roster member to an existing mailbox and clear it."""
    recipient = add_recipient(box_id, legal_name, **(recipient_overrides or {}))
    photo = file_and_verify_id_document(
        recipient["id"],
        "PHOTO",
        photo_doc_type,
        photo_expires_on or TEST_DEFAULTS["PHOTO_EXPIRES_ON"],
    )
    address = None
    if file_address_document:
        address = file_and_verify_id_document(
            recipient["id"],
            "ADDRESS",
            address_doc_type,
            address_expires_on or TEST_DEFAULTS["ADDRESS_EXPIRES_ON"],
        )
    form = file_form_1583(recipient["id"], home_address_line)
    notarize_form_1583(form["id"], notary_user_id)
    if accept_form:
        accept_form_1583(form["id"], officer_user_id)
    return {
        "recipient": recipient,
        "recipient_id": recipient["id"],
        "photo_document": photo,
        "address_document": address,
        "form": form,
        "form_id": form["id"],
    }


# ==========================================================================
# Tier 2 — pieces in custody
# ==========================================================================
def log_and_match_letter(ctx: dict, addressee_name: str = None, **overrides) -> dict:
    item = log_mail_item(
        ctx["box_id"], letter_payload(addressee_name or ctx["recipient"]["legal_name"], **overrides)
    )
    return match_mail_item(item["id"], ctx["recipient_id"])


def log_and_match_flat(ctx: dict, addressee_name: str = None, **overrides) -> dict:
    item = log_mail_item(
        ctx["box_id"], flat_payload(addressee_name or ctx["recipient"]["legal_name"], **overrides)
    )
    return match_mail_item(item["id"], ctx["recipient_id"])


def log_and_match_package(ctx: dict, carrier_rule_id: str, addressee_name: str = None, **overrides) -> dict:
    item = log_mail_item(
        ctx["box_id"],
        package_payload(
            addressee_name or ctx["recipient"]["legal_name"], carrier_rule_id, **overrides
        ),
    )
    return match_mail_item(item["id"], ctx["recipient_id"])


def log_and_match_sop(ctx: dict, carrier_rule_id: str, addressee_name: str = None, **overrides) -> dict:
    item = log_mail_item(
        ctx["box_id"],
        sop_payload(
            addressee_name or ctx["recipient"]["legal_name"], carrier_rule_id, **overrides
        ),
    )
    return match_mail_item(item["id"], ctx["recipient_id"])


def lodge_disposition(ctx: dict, mail_item_id: str, disposition_type: str) -> dict:
    """Lodge a disposition request, re-reading the piece's current version."""
    version = mail_item_version(mail_item_id)
    return get_success_data(
        api_client.create_disposition(
            mail_item_id,
            disposition_payload(disposition_type, version),
            ctx["holder_headers"],
        )
    )


def create_forward_shipment(
    ctx: dict, service_level: str, destination_address: str, mail_item_ids: list
) -> dict:
    """Create a consolidation, re-reading the mailbox's current version."""
    version = box_version(ctx["box_id"])
    return get_success_data(
        api_client.create_forward_shipment(
            ctx["box_id"],
            forward_shipment_payload(
                service_level, destination_address, mail_item_ids, version
            ),
            ctx["holder_headers"],
        )
    )


def request_scan(ctx: dict, mail_item_id: str, scan_tier: str, requested_pages: int) -> dict:
    return get_success_data(
        api_client.create_scan_job(
            mail_item_id, scan_job_payload(scan_tier, requested_pages), ctx["holder_headers"]
        )
    )


def start_and_complete_scan_job(scan_job_id: str) -> dict:
    get_success_data(api_client.start_scan_job(scan_job_id, CMRA_OPERATOR))
    return get_success_data(api_client.complete_scan_job(scan_job_id, CMRA_OPERATOR))


# ==========================================================================
# Tier 3 — composite scenarios reused by several tests
# ==========================================================================
def setup_box_with_forwardable_flats(
    box_number: str,
    legal_name: str,
    count: int,
    weights: list = None,
    plan_overrides: dict = None,
    lodge_forward_on: int = None,
    holder_email: str = None,
) -> dict:
    """A mailbox with `count` matched FLAT pieces, each carrying a PENDING FORWARD.

    `weights` overrides each piece's `actual_weight_lb`; `lodge_forward_on`
    limits how many of the pieces receive a FORWARD disposition (the remainder
    stay in HELD and therefore fail consolidation eligibility).
    """
    ctx = setup_releasable_box(
        box_number, legal_name, holder_email=holder_email, plan_overrides=plan_overrides
    )
    weights = weights or [3.0] * count
    lodge_forward_on = count if lodge_forward_on is None else lodge_forward_on
    items = []
    for index in range(count):
        item = log_and_match_flat(ctx, actual_weight_lb=weights[index])
        if index < lodge_forward_on:
            lodge_disposition(ctx, item["id"], "FORWARD")
        items.append(item)
    ctx["items"] = items
    ctx["item_ids"] = [item["id"] for item in items]
    return ctx


def setup_suspended_box_with_held_letter(box_number: str, legal_name: str, reason: str) -> dict:
    """A mailbox suspended under a compliance review, with one matched LETTER."""
    ctx = setup_releasable_box(box_number, legal_name)
    item = log_and_match_letter(ctx)
    review = open_compliance_review(ctx["box_id"], reason)
    suspend_compliance_review(review["id"])
    ctx["item"] = item
    ctx["item_id"] = item["id"]
    ctx["review"] = review
    ctx["review_id"] = review["id"]
    return ctx


def setup_accepted_package(
    box_number: str,
    legal_name: str,
    carrier_overrides: dict = None,
    package_overrides: dict = None,
    recipient_overrides: dict = None,
) -> dict:
    """A mailbox with one matched PACKAGE already accepted from the carrier."""
    ctx = setup_releasable_box(
        box_number, legal_name, recipient_overrides=recipient_overrides
    )
    rule = create_carrier_rule(**(carrier_overrides or {}))
    item = log_and_match_package(ctx, rule["id"], **(package_overrides or {}))
    accepted = get_success_data(api_client.accept_package(item["id"], CMRA_OPERATOR))
    ctx["carrier_rule"] = rule
    ctx["carrier_rule_id"] = rule["id"]
    ctx["item"] = accepted
    ctx["item_id"] = accepted["id"]
    return ctx

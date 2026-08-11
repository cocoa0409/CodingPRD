"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, and uses the lenient success validator so that a broken preamble
surfaces as a setup failure rather than as a confusing assertion failure.
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_agency_form_payload,
    create_applicant_payload,
    create_catalog_item_payload,
    create_consulate_payload,
    create_courier_leg_payload,
    create_document_requirement_payload,
    create_order_payload,
    create_shipment_payload,
    create_slot_payload,
    strip_omitted,
    submit_document_payload,
    upload_photo_payload,
)
from .test_users import (
    AGENCY_USER_ID,
    COURIER_USER_ID,
    QUOTING_USER_ID,
    REVIEWING_USER_ID,
    SUBMITTING_USER_ID,
    TEST_USERS,
    make_case_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CASE_MANAGER = TEST_USERS["case_manager_quote_headers"]
REVIEWER = TEST_USERS["case_manager_review_headers"]
SUBMITTER = TEST_USERS["case_manager_submit_headers"]
COURIER = TEST_USERS["courier_ops_headers"]
AGENCY = TEST_USERS["agency_liaison_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

DEFAULT_CLOCK = TEST_DEFAULTS["CLOCK"]


# ==========================================================================
# Tier 0 — primitives
# ==========================================================================
def set_clock(to_iso8601: str = DEFAULT_CLOCK) -> str:
    """Move the logical clock. Returns the reported current_utc."""
    data = get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))
    return data["current_utc"]


def new_catalog_item(**overrides) -> dict:
    return get_success_data(
        api_client.create_catalog_item(create_catalog_item_payload(**overrides), ADMIN)
    )


def new_document_requirement(catalog_item_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_document_requirement(
            catalog_item_id, create_document_requirement_payload(**overrides), ADMIN
        )
    )


def new_agency_form(**overrides) -> dict:
    return get_success_data(
        api_client.create_agency_form(create_agency_form_payload(**overrides), ADMIN)
    )


def publish_form(agency_form_id: str) -> dict:
    return get_success_data(api_client.publish_agency_form(agency_form_id, ADMIN))


def new_active_form(**overrides) -> dict:
    """Register a revision and publish it, so it holds status ACTIVE."""
    form = new_agency_form(**overrides)
    return publish_form(form["id"])


def new_consulate(**overrides) -> dict:
    return get_success_data(
        api_client.create_consulate(create_consulate_payload(**overrides), ADMIN)
    )


def add_closure(consulate_id: str, closure_date: str) -> dict:
    return get_success_data(
        api_client.add_consulate_closure(consulate_id, {"closure_date": closure_date}, ADMIN)
    )


def new_slot(consulate_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_slot(consulate_id, create_slot_payload(**overrides), ADMIN)
    )


def read_slot(slot_id: str) -> dict:
    return get_success_data(api_client.get_slot(slot_id, ADMIN))


def new_order(catalog_item_id: str, user_id: str = QUOTING_USER_ID, **overrides) -> dict:
    return get_success_data(
        api_client.create_order(
            create_order_payload(catalog_item_id, **overrides), make_case_manager_headers(user_id)
        )
    )


def read_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, CASE_MANAGER))


def order_version(order_id: str) -> int:
    return read_order(order_id)["version"]


def new_applicant(order_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_applicant(order_id, create_applicant_payload(**overrides), CASE_MANAGER)
    )


def read_applicant(applicant_id: str) -> dict:
    return get_success_data(api_client.get_applicant(applicant_id, CASE_MANAGER))


def applicant_version(applicant_id: str) -> int:
    return read_applicant(applicant_id)["version"]


def submit_doc(applicant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.submit_document(applicant_id, submit_document_payload(**overrides), CASE_MANAGER)
    )


def review_doc(document_id: str, decision: str = "ACCEPT", rejection_reason: Optional[str] = None) -> dict:
    payload: Dict[str, object] = {"decision": decision}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return get_success_data(api_client.review_document(document_id, payload, REVIEWER))


def resubmit_doc(document_id: str, **overrides) -> dict:
    payload = {"issue_date": "2020-01-15", "expiry_date": "2030-01-15"}
    payload.update(overrides)
    return get_success_data(
        api_client.resubmit_document(document_id, strip_omitted(payload), CASE_MANAGER)
    )


def read_document(document_id: str) -> dict:
    return get_success_data(api_client.get_document(document_id, CASE_MANAGER))


def add_photo(applicant_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.upload_photo(applicant_id, upload_photo_payload(**overrides), CASE_MANAGER)
    )


def check_photo(photo_id: str) -> dict:
    return get_success_data(api_client.run_compliance_check(photo_id, REVIEWER))


def retake_photo(photo_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.retake_photo(photo_id, upload_photo_payload(**overrides), CASE_MANAGER)
    )


def prepare_form(applicant_id: str, agency_form_id: str, filled_field_count: int = 12) -> dict:
    """Prepare a form, always quoting the applicant's freshly observed version."""
    payload = {
        "agency_form_id": agency_form_id,
        "filled_field_count": filled_field_count,
        "expected_applicant_version": applicant_version(applicant_id),
    }
    return get_success_data(api_client.create_prepared_form(applicant_id, payload, CASE_MANAGER))


def book_appointment(applicant_id: str, slot_id: str) -> dict:
    """Book an interview, always quoting the slot's freshly observed version."""
    payload = {
        "applicant_id": applicant_id,
        "slot_id": slot_id,
        "expected_slot_version": read_slot(slot_id)["version"],
    }
    return get_success_data(api_client.create_appointment(payload, CASE_MANAGER))


def read_appointment(appointment_id: str) -> dict:
    return get_success_data(api_client.get_appointment(appointment_id, CASE_MANAGER))


def quote(order_id: str, promo_discount_pct: Optional[float] = None,
          user_id: str = QUOTING_USER_ID) -> dict:
    payload: Dict[str, object] = {}
    if promo_discount_pct is not None:
        payload["promo_discount_pct"] = promo_discount_pct
    return get_success_data(
        api_client.quote_order(order_id, payload, make_case_manager_headers(user_id))
    )


def pay(order_id: str, amount_cents: int, stream_override: Optional[str] = None) -> dict:
    payload: Dict[str, object] = {"amount_cents": amount_cents}
    if stream_override is not None:
        payload["stream_override"] = stream_override
    return get_success_data(api_client.create_payment(order_id, payload, CASE_MANAGER))


def accept_quote(order_id: str) -> dict:
    return get_success_data(api_client.accept_quote(order_id, CASE_MANAGER))


def change_service_level(order_id: str, service_level: str) -> dict:
    payload = {
        "service_level": service_level,
        "expected_order_version": order_version(order_id),
    }
    return get_success_data(api_client.change_service_level(order_id, payload, CASE_MANAGER))


def new_leg(order_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_courier_leg(order_id, create_courier_leg_payload(**overrides), COURIER)
    )


def dispatch_leg(courier_leg_id: str) -> dict:
    return get_success_data(api_client.dispatch_courier_leg(courier_leg_id, COURIER))


def complete_leg(courier_leg_id: str, outcome: str = "DELIVERED") -> dict:
    return get_success_data(
        api_client.complete_courier_leg(courier_leg_id, {"outcome": outcome}, COURIER)
    )


def run_leg(order_id: str, **overrides) -> dict:
    """Create, dispatch and deliver one hop. Returns the delivered leg."""
    leg = new_leg(order_id, **overrides)
    dispatch_leg(leg["id"])
    return complete_leg(leg["id"], "DELIVERED")


def list_legs(order_id: str) -> List[dict]:
    data, _meta = _paginated(api_client.list_courier_legs(order_id, COURIER, {"limit": 100}))
    return data


def submit_order(order_id: str, user_id: str = SUBMITTING_USER_ID) -> dict:
    return get_success_data(
        api_client.submit_order(order_id, make_case_manager_headers(user_id))
    )


def tender_order(order_id: str) -> dict:
    return get_success_data(api_client.tender_order(order_id, AGENCY))


def issue_rfe(order_id: str, requested_doc_type: str = "BANK_STATEMENT") -> dict:
    return get_success_data(
        api_client.create_rfe(order_id, {"requested_doc_type": requested_doc_type}, AGENCY)
    )


def respond_rfe(rfe_id: str) -> dict:
    return get_success_data(api_client.respond_to_rfe(rfe_id, CASE_MANAGER))


def adjudicate_rfe(rfe_id: str, outcome: str) -> dict:
    return get_success_data(api_client.adjudicate_rfe(rfe_id, {"outcome": outcome}, AGENCY))


def list_rfes(order_id: str) -> List[dict]:
    data, _meta = _paginated(api_client.list_rfes(order_id, AGENCY, {"limit": 100}))
    return data


def agency_decision(order_id: str, decision: str) -> dict:
    return get_success_data(
        api_client.record_agency_decision(order_id, {"decision": decision}, AGENCY)
    )


def new_shipment(order_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_shipment(order_id, create_shipment_payload(**overrides), COURIER)
    )


def read_shipment(shipment_id: str) -> dict:
    return get_success_data(api_client.get_shipment(shipment_id, COURIER))


def list_custody_events(order_id: str) -> List[dict]:
    data, _meta = _paginated(api_client.list_custody_events(order_id, COURIER, {"limit": 100}))
    return data


def list_ledger_entries(order_id: str) -> List[dict]:
    data, _meta = _paginated(
        api_client.list_ledger_entries(order_id, COMPLIANCE, {"limit": 100})
    )
    return data


def list_sla_segments(order_id: str) -> List[dict]:
    data, _meta = _paginated(api_client.list_sla_segments(order_id, COMPLIANCE, {"limit": 100}))
    return data


def list_applicant_documents(applicant_id: str) -> List[dict]:
    data, _meta = _paginated(
        api_client.list_applicant_documents(applicant_id, CASE_MANAGER, {"limit": 100})
    )
    return data


def list_applicant_photos(applicant_id: str) -> List[dict]:
    data, _meta = _paginated(
        api_client.list_applicant_photos(applicant_id, CASE_MANAGER, {"limit": 100})
    )
    return data


def list_prepared_forms(applicant_id: str) -> List[dict]:
    data, _meta = _paginated(
        api_client.list_applicant_prepared_forms(applicant_id, CASE_MANAGER, {"limit": 100})
    )
    return data


def order_summary(order_id: str) -> dict:
    return get_success_data(api_client.get_order_summary(order_id, COMPLIANCE))


def feasibility(order_id: str) -> dict:
    return get_success_data(api_client.get_feasibility(order_id, CASE_MANAGER))


def _paginated(response):
    """Lenient list reader: returns (rows, meta) from a 2xx list response."""
    body = response.json()
    assert response.status_code < 300, (
        f"Setup failed: list call returned {response.status_code} {body}"
    )
    return body.get("data", []), body.get("meta", {})


# ==========================================================================
# Tier 1-5 — composite scenarios
#
# `build_scenario` walks one order from an empty database to a named stage,
# doing exactly the work each stage needs and nothing more.
#
#   draft      catalogue + order + travellers
#   quoted     + quote
#   intake     + readiness work + quote + full payment + accept-quote
#   ready      + hop 1 (APPLICANT -> SERVICE) delivered
#   submitted  + submission (by an operator other than the one who quoted)
#   at_agency  + hop 2 (SERVICE -> AGENCY) delivered + tender
# ==========================================================================
STAGES = ("draft", "quoted", "intake", "ready", "submitted", "at_agency")

APPLICANT_NAMES = ("Traveller One", "Traveller Two", "Traveller Three", "Traveller Four")
APPLICANT_BIRTHDAYS = ("1990-03-04", "1991-04-05", "1992-05-06", "1993-06-07")


def build_scenario(
    stage: str = "ready",
    *,
    clock: str = DEFAULT_CLOCK,
    service_level: str = "STANDARD",
    travel_date: str = TEST_DEFAULTS["TRAVEL_DATE"],
    return_date: str = TEST_DEFAULTS["RETURN_DATE"],
    applicant_count: int = 1,
    make_complete: bool = True,
    require_passport_doc: bool = False,
    visa_type: str = "PASSPORT_RENEWAL",
    destination_country: str = TEST_DEFAULTS["DESTINATION_COUNTRY"],
    requires_appointment: bool = False,
    with_consulate: bool = False,
    catalog_overrides: Optional[dict] = None,
    order_overrides: Optional[dict] = None,
    payment_cents: Optional[int] = None,
    promo_discount_pct: Optional[float] = None,
    leg1_scheduled_date: str = "2026-06-01",
    leg2_scheduled_date: str = "2026-06-01",
    quote_user: str = QUOTING_USER_ID,
    submit_user: str = SUBMITTING_USER_ID,
) -> dict:
    """Drive one order to `stage`. Returns every id the tests need."""
    assert stage in STAGES, f"unknown stage {stage!r}"
    set_clock(clock)

    form = new_active_form()

    consulate = None
    if with_consulate or requires_appointment:
        consulate = new_consulate(destination_country=destination_country)

    catalog_kwargs = {
        "visa_type": visa_type,
        "destination_country": destination_country,
        "requires_appointment": requires_appointment,
    }
    if catalog_overrides:
        catalog_kwargs.update(catalog_overrides)
    catalog = new_catalog_item(**catalog_kwargs)

    if require_passport_doc:
        new_document_requirement(catalog["id"])

    order_kwargs = {
        "travel_date": travel_date,
        "return_date": return_date,
        "service_level": service_level,
    }
    if consulate is not None:
        order_kwargs["consulate_id"] = consulate["id"]
    if order_overrides:
        order_kwargs.update(order_overrides)
    order = new_order(catalog["id"], user_id=quote_user, **order_kwargs)

    applicants = [
        new_applicant(
            order["id"],
            full_name=APPLICANT_NAMES[i],
            date_of_birth=APPLICANT_BIRTHDAYS[i],
        )
        for i in range(applicant_count)
    ]

    documents: Dict[str, List[dict]] = {a["id"]: [] for a in applicants}
    photos: Dict[str, dict] = {}
    prepared_forms: Dict[str, dict] = {}

    if make_complete and stage != "draft":
        for applicant in applicants:
            if require_passport_doc:
                doc = submit_doc(applicant["id"])
                documents[applicant["id"]].append(review_doc(doc["id"], "ACCEPT"))
            photo = add_photo(applicant["id"])
            photos[applicant["id"]] = check_photo(photo["id"])
            prepared_forms[applicant["id"]] = prepare_form(applicant["id"], form["id"])

    result = {
        "clock": clock,
        "form": form,
        "catalog": catalog,
        "consulate": consulate,
        "order_id": order["id"],
        "order": order,
        "applicants": applicants,
        "applicant_ids": [a["id"] for a in applicants],
        "documents": documents,
        "photos": photos,
        "prepared_forms": prepared_forms,
        "legs": [],
    }
    if stage == "draft":
        result["order"] = read_order(order["id"])
        return result

    result["order"] = quote(order["id"], promo_discount_pct, user_id=quote_user)
    if stage == "quoted":
        return result

    total = result["order"]["total_quoted_cents"] if payment_cents is None else payment_cents
    if total > 0:
        pay(order["id"], total)
    accept_quote(order["id"])
    result["order"] = read_order(order["id"])
    if stage == "intake":
        return result

    result["legs"].append(
        run_leg(
            order["id"],
            leg_index=1,
            from_holder="APPLICANT",
            to_holder="SERVICE",
            scheduled_date=leg1_scheduled_date,
        )
    )
    result["order"] = read_order(order["id"])
    if stage == "ready":
        return result

    result["order"] = submit_order(order["id"], user_id=submit_user)
    if stage == "submitted":
        return result

    result["legs"].append(
        run_leg(
            order["id"],
            leg_index=2,
            from_holder="SERVICE",
            to_holder="AGENCY",
            scheduled_date=leg2_scheduled_date,
        )
    )
    result["order"] = tender_order(order["id"])
    return result

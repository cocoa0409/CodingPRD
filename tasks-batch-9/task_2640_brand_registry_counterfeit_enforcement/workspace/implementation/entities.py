"""Row constructors.  Field order here is the field order clients observe."""

from decimal import Decimal

import db
from versioning import register_created


def _stamp(row):
    now = db.now()
    row["created_at"] = now
    row["updated_at"] = now
    row["version"] = 1
    return row


def _persist(table_name, row):
    _stamp(row)
    db.insert(table_name, row)
    register_created(row)
    return row


def new_brand(name, owner_legal_entity, home_jurisdiction,
              authorized_msrp_cents, enforcement_budget_cents):
    return _persist("brands", {
        "id": db.new_id(),
        "name": name,
        "owner_legal_entity": owner_legal_entity,
        "home_jurisdiction": home_jurisdiction,
        "authorized_msrp_cents": authorized_msrp_cents,
        "enforcement_budget_cents": enforcement_budget_cents,
        "enforcement_spend_cents": 0,
        "status": "DRAFT",
    })


def new_registration(brand_id, registration_number, jurisdiction, nice_class,
                     registration_date, expiry_date, principal_register,
                     status):
    return _persist("registrations", {
        "id": db.new_id(),
        "brand_id": brand_id,
        "registration_number": registration_number,
        "jurisdiction": jurisdiction,
        "nice_class": nice_class,
        "registration_date": registration_date,
        "expiry_date": expiry_date,
        "principal_register": principal_register,
        "status": status,
    })


def new_enrollment(brand_id, asserted_registration_id, marketplace_code,
                   requested_nice_class):
    return _persist("enrollments", {
        "id": db.new_id(),
        "brand_id": brand_id,
        "asserted_registration_id": asserted_registration_id,
        "marketplace_code": marketplace_code,
        "requested_nice_class": requested_nice_class,
        "enrollment_status": "SUBMITTED",
        "activated_at": None,
        "suspension_reason_code": None,
        "superseded_by_enrollment_id": None,
    })


def new_representative(enrollment_id, authority_scope, effective_from,
                       effective_to, power_of_attorney_ref):
    return _persist("representatives", {
        "id": db.new_id(),
        "enrollment_id": enrollment_id,
        "authority_scope": authority_scope,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "power_of_attorney_ref": power_of_attorney_ref,
        "designation_status": "DESIGNATED",
        "revoked_at": None,
    })


def new_seller(marketplace_code, seller_ref, legal_name, jurisdiction):
    return _persist("sellers", {
        "id": db.new_id(),
        "marketplace_code": marketplace_code,
        "seller_ref": seller_ref,
        "legal_name": legal_name,
        "jurisdiction": jurisdiction,
        "canonical_seller_id": None,
        "standalone_strike_points": Decimal("0.00"),
        "cluster_strike_points": Decimal("0.00"),
        "status": "ACTIVE",
    })


def new_listing(brand_id, seller_id, marketplace_code, listing_ref, title_text,
                image_hash, price_cents, nice_class):
    return _persist("listings", {
        "id": db.new_id(),
        "brand_id": brand_id,
        "seller_id": seller_id,
        "marketplace_code": marketplace_code,
        "listing_ref": listing_ref,
        "title_text": title_text,
        "image_hash": image_hash,
        "price_cents": price_cents,
        "nice_class": nice_class,
        "image_match_score": None,
        "text_match_score": None,
        "price_deviation_factor": None,
        "match_score": None,
        "violation_type": "NONE",
        "monitor_status": "NEW",
        "enforcement_status": "NONE",
    })


def new_claim(brand_id, listing_id, asserted_registration_id,
              claimed_violation_type, registration_strength,
              preliminary_score):
    return _persist("claims", {
        "id": db.new_id(),
        "brand_id": brand_id,
        "listing_id": listing_id,
        "asserted_registration_id": asserted_registration_id,
        "claimed_violation_type": claimed_violation_type,
        "registration_strength": registration_strength,
        "preliminary_score": preliminary_score,
        "substantiation_score": Decimal("0.00"),
        "dismissal_reason_code": None,
        "status": "DRAFT",
    })


def new_test_buy(claim_id, seller_id, order_ref, purchase_price_cents,
                 shipping_cents, lab_fee_cents, pricing, ordered_at):
    return _persist("test_buys", {
        "id": db.new_id(),
        "claim_id": claim_id,
        "seller_id": seller_id,
        "order_ref": order_ref,
        "purchase_price_cents": purchase_price_cents,
        "shipping_cents": shipping_cents,
        "lab_fee_cents": lab_fee_cents,
        "subtotal_cents": pricing["subtotal_cents"],
        "service_fee_rate": pricing["service_fee_rate"],
        "service_fee_cents": pricing["service_fee_cents"],
        "billable_total_cents": pricing["billable_total_cents"],
        "ordered_at": ordered_at,
        "received_at": None,
        "lot_code": None,
        "chain_of_custody_ref": None,
        "authentication_result": None,
        "lab_ref": None,
        "status": "ORDERED",
    })


def new_package(claim_id, package_ref):
    return _persist("packages", {
        "id": db.new_id(),
        "claim_id": claim_id,
        "package_ref": package_ref,
        "items": [],
        "item_count": 0,
        "required_type_coverage": 0,
        "completeness_score": Decimal("0.0000"),
        "sealed_at": None,
        "status": "ASSEMBLING",
    })


def new_takedown(enrollment_id, claim_id, evidence_package_id):
    return _persist("takedowns", {
        "id": db.new_id(),
        "enrollment_id": enrollment_id,
        "claim_id": claim_id,
        "evidence_package_id": evidence_package_id,
        "submitted_by_rep_id": None,
        "round_number": 0,
        "submitted_at": None,
        "decision_due_at": None,
        "decided_at": None,
        "counter_notice_deadline_at": None,
        "marketplace_case_ref": None,
        "status": "DRAFT",
    })


def new_counter_notice(takedown_id, seller_id, sworn_statement_ref, filed_at,
                       response_due_at):
    return _persist("counter_notices", {
        "id": db.new_id(),
        "takedown_id": takedown_id,
        "seller_id": seller_id,
        "sworn_statement_ref": sworn_statement_ref,
        "filed_at": filed_at,
        "response_due_at": response_due_at,
        "rebuttal_ref": None,
        "resolved_at": None,
        "status": "FILED",
    })


def new_recordation(brand_id, registration_id, customs_authority_code,
                    nice_class, recorded_on, expires_on):
    return _persist("recordations", {
        "id": db.new_id(),
        "brand_id": brand_id,
        "registration_id": registration_id,
        "customs_authority_code": customs_authority_code,
        "nice_class": nice_class,
        "recorded_on": recorded_on,
        "expires_on": expires_on,
        "recordation_number": None,
        "status": "DRAFT",
    })


def new_investigation(brand_id, recordation_id, source_test_buy_id, seller_id,
                      source_kind, lot_code, seizure_ref, port_code,
                      seized_qty, declared_value_cents, detention_notice_at,
                      response_due_at):
    return _persist("investigations", {
        "id": db.new_id(),
        "brand_id": brand_id,
        "recordation_id": recordation_id,
        "source_test_buy_id": source_test_buy_id,
        "seller_id": seller_id,
        "source_kind": source_kind,
        "lot_code": lot_code,
        "seizure_ref": seizure_ref,
        "port_code": port_code,
        "seized_qty": seized_qty,
        "declared_value_cents": declared_value_cents,
        "detention_notice_at": detention_notice_at,
        "response_due_at": response_due_at,
        "evidence_ref": None,
        "suspected_distributor_ref": None,
        "findings_ref": None,
        "concluded_at": None,
        "status": "OPEN",
    })

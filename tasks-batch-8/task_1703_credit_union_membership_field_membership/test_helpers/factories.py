"""Payload factories — one per entity, input fields only."""
from .constants import (
    DEFAULT_PAR_VALUE_CENTS,
    DOC_GOVERNMENT_ID,
    STANDARD_SEGMENT_DOCS,
)


def segment_spec(segment_type="OCCUPATIONAL", descriptor="ACME Corp employees",
                 required_documents=None):
    """One element of the charter creation segments array."""
    return {
        "segment_type": segment_type,
        "descriptor": descriptor,
        "required_documents": (
            list(required_documents) if required_documents is not None
            else list(STANDARD_SEGMENT_DOCS)
        ),
    }


def create_charter_payload(bond_type="MULTIPLE_COMMON_BOND",
                           par_value_cents=DEFAULT_PAR_VALUE_CENTS,
                           segments=None, **overrides):
    payload = {
        "bond_type": bond_type,
        "par_value_cents": par_value_cents,
        "segments": segments if segments is not None else [segment_spec()],
    }
    payload.update(overrides)
    return payload


def create_amendment_payload(charter_id, amendment_type, effective_date,
                             expected_charter_version,
                             proposed_segment_type=None,
                             proposed_segment_descriptor=None,
                             proposed_segment_required_documents=None,
                             retire_segment_ids=None, **overrides):
    payload = {
        "charter_id": charter_id,
        "amendment_type": amendment_type,
        "effective_date": effective_date,
        "expected_charter_version": expected_charter_version,
    }
    if proposed_segment_type is not None:
        payload["proposed_segment_type"] = proposed_segment_type
    if proposed_segment_descriptor is not None:
        payload["proposed_segment_descriptor"] = proposed_segment_descriptor
    if proposed_segment_required_documents is not None:
        payload["proposed_segment_required_documents"] = (
            proposed_segment_required_documents)
    if retire_segment_ids is not None:
        payload["retire_segment_ids"] = retire_segment_ids
    payload.update(overrides)
    return payload


def add_segment_amendment_payload(charter_id, expected_charter_version,
                                  effective_date="2026-09-01",
                                  proposed_segment_type="COMMUNITY",
                                  proposed_segment_descriptor="Riverside County residents",
                                  proposed_segment_required_documents=None):
    return create_amendment_payload(
        charter_id, "ADD_SEGMENT", effective_date, expected_charter_version,
        proposed_segment_type=proposed_segment_type,
        proposed_segment_descriptor=proposed_segment_descriptor,
        proposed_segment_required_documents=(
            proposed_segment_required_documents
            if proposed_segment_required_documents is not None
            else [DOC_GOVERNMENT_ID, "ADDRESS_PROOF"]
        ),
    )


def retire_segment_amendment_payload(charter_id, retire_segment_ids,
                                     expected_charter_version,
                                     effective_date="2026-09-01"):
    return create_amendment_payload(
        charter_id, "RETIRE_SEGMENT", effective_date, expected_charter_version,
        retire_segment_ids=retire_segment_ids,
    )


def create_membership_application_payload(
        applicant_full_name="Test Applicant", date_of_birth="1990-01-01",
        basis="SEGMENT_MATCH", segment_id=None, sponsor_member_id=None,
        relationship_to_sponsor=None, documents_provided=None, **overrides):
    payload = {
        "applicant_full_name": applicant_full_name,
        "date_of_birth": date_of_birth,
        "basis": basis,
        "documents_provided": (
            list(documents_provided) if documents_provided is not None
            else list(STANDARD_SEGMENT_DOCS)
        ),
    }
    if segment_id is not None:
        payload["segment_id"] = segment_id
    if sponsor_member_id is not None:
        payload["sponsor_member_id"] = sponsor_member_id
    if relationship_to_sponsor is not None:
        payload["relationship_to_sponsor"] = relationship_to_sponsor
    payload.update(overrides)
    return payload


def request_documents_payload(codes):
    return {"requested_document_codes": list(codes)}


def submit_documents_payload(codes):
    return {"documents_provided": list(codes)}


def deny_application_payload(reason="insufficient documentation"):
    return {"denial_reason": reason}


def patch_member_payload(expected_member_version, mailing_address=None,
                         email=None, phone=None, **overrides):
    payload = {"expected_member_version": expected_member_version}
    if mailing_address is not None:
        payload["mailing_address"] = mailing_address
    if email is not None:
        payload["email"] = email
    if phone is not None:
        payload["phone"] = phone
    payload.update(overrides)
    return payload


def create_share_account_payload(member_id, account_type="PRIMARY",
                                 initial_deposit_cents=100_000, **overrides):
    payload = {
        "member_id": member_id,
        "account_type": account_type,
        "initial_deposit_cents": initial_deposit_cents,
    }
    payload.update(overrides)
    return payload


def create_transaction_payload(kind="DEPOSIT", amount_cents=1_000,
                               posted_date="2026-08-01", **overrides):
    payload = {
        "kind": kind,
        "amount_cents": amount_cents,
        "posted_date": posted_date,
    }
    payload.update(overrides)
    return payload


def create_enrollment_payload(member_id, funding_share_account_id,
                              product_code="MONEY_MARKET", **overrides):
    payload = {
        "member_id": member_id,
        "product_code": product_code,
        "funding_share_account_id": funding_share_account_id,
    }
    payload.update(overrides)
    return payload


def create_declaration_payload(period_start="2026-07-01",
                               period_end="2026-07-31", rate_bps=600,
                               method="AVERAGE_DAILY_BALANCE",
                               payable_date="2026-08-10", **overrides):
    payload = {
        "period_start": period_start,
        "period_end": period_end,
        "rate_bps": rate_bps,
        "method": method,
        "payable_date": payable_date,
    }
    payload.update(overrides)
    return payload


def create_meeting_payload(meeting_date="2026-07-20", record_date="2026-07-05",
                           voting_open_date="2026-07-10", quorum_threshold=1,
                           **overrides):
    payload = {
        "meeting_date": meeting_date,
        "record_date": record_date,
        "voting_open_date": voting_open_date,
        "quorum_threshold": quorum_threshold,
    }
    payload.update(overrides)
    return payload


def reconvene_payload(meeting_date="2026-07-25", voting_open_date="2026-07-16",
                      **overrides):
    payload = {
        "meeting_date": meeting_date,
        "voting_open_date": voting_open_date,
    }
    payload.update(overrides)
    return payload


def create_ballot_payload(meeting_id, choice="FOR_SLATE_A", **overrides):
    payload = {"meeting_id": meeting_id, "choice": choice}
    payload.update(overrides)
    return payload


def create_review_payload(reason="MANUAL_FLAG", **overrides):
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


def cure_review_payload(resolution_note=None, **overrides):
    payload = {}
    if resolution_note is not None:
        payload["resolution_note"] = resolution_note
    payload.update(overrides)
    return payload

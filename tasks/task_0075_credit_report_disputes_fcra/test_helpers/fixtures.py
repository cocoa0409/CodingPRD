"""Composite setup helpers.

Every helper builds its preconditions from scratch (empty DB) using only
PRD-declared endpoints, and uses get_success_data() so setup failures surface
as clear "Setup step failed" errors. Entity-backed roles thread the real entity
id through make_*_headers().

A standard clock anchor of 2026-01-05T00:00:00.000Z (a Monday) is used so that
deadline arithmetic is deterministic across helpers.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_consumer_headers,
    make_furnisher_headers,
    make_bureau_headers,
    make_regulator_headers,
)
from .factories import (
    create_consumer_payload,
    create_furnisher_payload,
    create_credit_file_payload,
    create_tradeline_payload,
    create_dispute_payload,
    create_reverification_payload,
    respond_reverification_payload,
    create_security_freeze_payload,
    create_complaint_payload,
)

CLOCK_ANCHOR = "2026-01-05T00:00:00.000Z"

_BUREAU = make_bureau_headers()
_REGULATOR = make_regulator_headers()


# --- Tier 0: primitive creators -------------------------------------------------

def create_consumer(**overrides) -> dict:
    resp = api_client.create_consumer(create_consumer_payload(**overrides))
    return get_success_data(resp)


def create_furnisher(**overrides) -> dict:
    resp = api_client.create_furnisher(create_furnisher_payload(**overrides))
    return get_success_data(resp)


def create_credit_file(consumer_id, **overrides) -> dict:
    resp = api_client.create_credit_file(
        create_credit_file_payload(consumer_id, **overrides), _BUREAU
    )
    return get_success_data(resp)


def set_clock(to_iso8601=CLOCK_ANCHOR) -> None:
    get_success_data(api_client.clock_set(to_iso8601, _BUREAU))


def advance_clock(to_iso8601) -> None:
    get_success_data(api_client.clock_advance(to_iso8601, _BUREAU))


def create_tradeline(credit_file_id, furnisher_id, **overrides) -> dict:
    resp = api_client.create_tradeline(
        create_tradeline_payload(credit_file_id, furnisher_id, **overrides),
        make_furnisher_headers(furnisher_id),
    )
    return get_success_data(resp)


def get_file_version(credit_file_id) -> int:
    data = get_success_data(api_client.get_credit_file(credit_file_id, _BUREAU))
    return data["version"]


# --- Tier 1: scenario foundations -----------------------------------------------

def setup_consumer_furnisher_file(set_clock_anchor=True, bureau_code="EQUIFAX"):
    """Create a consumer, a furnisher, and an OPEN credit file; optionally pin the
    clock to the standard anchor. Returns (consumer, furnisher, file)."""
    consumer = create_consumer()
    furnisher = create_furnisher()
    cfile = create_credit_file(consumer["id"], bureau_code=bureau_code)
    if set_clock_anchor:
        set_clock(CLOCK_ANCHOR)
    return consumer, furnisher, cfile


def setup_file_with_tradeline(set_clock_anchor=True, tradeline_overrides=None):
    """consumer + furnisher + OPEN file + one REPORTING tradeline.
    Returns (consumer, furnisher, file, tradeline)."""
    consumer, furnisher, cfile = setup_consumer_furnisher_file(set_clock_anchor=set_clock_anchor)
    tl = create_tradeline(cfile["id"], furnisher["id"], **(tradeline_overrides or {}))
    return consumer, furnisher, cfile, tl


def file_dispute(consumer_id, credit_file_id, tradeline_id, expected_version, **overrides) -> dict:
    resp = api_client.create_dispute(
        create_dispute_payload(credit_file_id, tradeline_id, expected_version, **overrides),
        make_consumer_headers(consumer_id),
    )
    return get_success_data(resp)


def place_freeze(consumer_id, credit_file_id, expected_version, **overrides) -> dict:
    resp = api_client.create_security_freeze(
        create_security_freeze_payload(credit_file_id, expected_version, **overrides),
        make_consumer_headers(consumer_id),
    )
    return get_success_data(resp)


# --- Tier 2/3: dispute lifecycle shortcuts --------------------------------------

def setup_filed_dispute(dispute_overrides=None, tradeline_overrides=None):
    """A FILED dispute (clock at anchor). Returns
    (consumer, furnisher, file, tradeline, dispute)."""
    consumer, furnisher, cfile, tl = setup_file_with_tradeline(
        tradeline_overrides=tradeline_overrides
    )
    v = get_file_version(cfile["id"])
    dispute = file_dispute(
        consumer["id"], cfile["id"], tl["id"], v, **(dispute_overrides or {})
    )
    return consumer, furnisher, cfile, tl, dispute


def setup_investigating_dispute(dispute_overrides=None, tradeline_overrides=None):
    """A dispute advanced to INVESTIGATING. Returns
    (consumer, furnisher, file, tradeline, dispute)."""
    consumer, furnisher, cfile, tl, dispute = setup_filed_dispute(
        dispute_overrides=dispute_overrides, tradeline_overrides=tradeline_overrides
    )
    get_success_data(api_client.open_investigation(dispute["id"], _BUREAU))
    dispute = get_success_data(api_client.get_dispute(dispute["id"], _BUREAU))
    return consumer, furnisher, cfile, tl, dispute


def setup_reverifying_dispute(dispute_overrides=None, tradeline_overrides=None):
    """A dispute at REVERIFYING with one PENDING reverification on the furnisher.
    Returns (consumer, furnisher, file, tradeline, dispute, reverification)."""
    consumer, furnisher, cfile, tl, dispute = setup_investigating_dispute(
        dispute_overrides=dispute_overrides, tradeline_overrides=tradeline_overrides
    )
    rv = get_success_data(
        api_client.create_reverification(
            create_reverification_payload(dispute["id"], furnisher["id"]), _BUREAU
        )
    )
    dispute = get_success_data(api_client.get_dispute(dispute["id"], _BUREAU))
    return consumer, furnisher, cfile, tl, dispute, rv


def respond(reverification_id, furnisher_id, response_type, **payload_overrides) -> dict:
    resp = api_client.respond_reverification(
        reverification_id,
        respond_reverification_payload(response_type, **payload_overrides),
        make_furnisher_headers(furnisher_id),
    )
    return get_success_data(resp)


def setup_resolved_verify_dispute():
    """A dispute resolved to RESOLVED_VERIFY (tradeline VERIFIED) and a RESPONDED
    reverification. Returns (consumer, furnisher, file, tradeline, dispute, reverification)."""
    consumer, furnisher, cfile, tl, dispute, rv = setup_reverifying_dispute()
    respond(rv["id"], furnisher["id"], "VERIFY")
    dispute = get_success_data(api_client.get_dispute(dispute["id"], _BUREAU))
    rv = get_success_data(api_client.get_reverification(rv["id"], _BUREAU))
    return consumer, furnisher, cfile, tl, dispute, rv


def setup_corrected_tradeline(corrected_balance_cents=30000):
    """A tradeline corrected by a furnisher MODIFY (status CORRECTED, no open dispute).
    Returns (consumer, furnisher, file, tradeline, dispute)."""
    consumer, furnisher, cfile, tl, dispute, rv = setup_reverifying_dispute(
        dispute_overrides={"dispute_reason": "INACCURATE_BALANCE"}
    )
    respond(rv["id"], furnisher["id"], "MODIFY", corrected_balance_cents=corrected_balance_cents)
    tl = get_success_data(api_client.get_tradeline(tl["id"], _BUREAU))
    return consumer, furnisher, cfile, tl, dispute


def setup_deleted_tradeline():
    """A tradeline DELETED by a furnisher DELETE response. Returns
    (consumer, furnisher, file, tradeline, dispute)."""
    consumer, furnisher, cfile, tl, dispute, rv = setup_reverifying_dispute()
    respond(rv["id"], furnisher["id"], "DELETE")
    tl = get_success_data(api_client.get_tradeline(tl["id"], _BUREAU))
    return consumer, furnisher, cfile, tl, dispute


def reopen(dispute_id, consumer_id) -> dict:
    return get_success_data(
        api_client.reopen_dispute(dispute_id, make_consumer_headers(consumer_id))
    )


def setup_dispute_reopened_twice():
    """A dispute cycled through 2 reopens (reopen_count==2), currently at REVERIFYING.
    Returns (consumer, furnisher, file, tradeline, dispute)."""
    consumer, furnisher, cfile, tl, dispute, rv = setup_reverifying_dispute()
    # First reopen, then re-dispatch -> REVERIFYING
    reopen(dispute["id"], consumer["id"])
    get_success_data(
        api_client.create_reverification(
            create_reverification_payload(dispute["id"], furnisher["id"]), _BUREAU
        )
    )
    # Second reopen, then re-dispatch -> REVERIFYING
    reopen(dispute["id"], consumer["id"])
    get_success_data(
        api_client.create_reverification(
            create_reverification_payload(dispute["id"], furnisher["id"]), _BUREAU
        )
    )
    dispute = get_success_data(api_client.get_dispute(dispute["id"], _BUREAU))
    return consumer, furnisher, cfile, tl, dispute


# --- Freeze / posture setups ----------------------------------------------------

def setup_frozen_file_with_tradeline():
    """A FROZEN file (one ACTIVE FREEZE covering the clock) with one REPORTING tradeline.
    Returns (consumer, furnisher, file, tradeline)."""
    consumer, furnisher, cfile, tl = setup_file_with_tradeline()
    v = get_file_version(cfile["id"])
    place_freeze(consumer["id"], cfile["id"], v, freeze_type="FREEZE", effective_at=CLOCK_ANCHOR)
    cfile = get_success_data(api_client.get_credit_file(cfile["id"], _BUREAU))
    return consumer, furnisher, cfile, tl


def setup_active_freeze(freeze_type="FREEZE", effective_at=CLOCK_ANCHOR, expires_at=None):
    """A file with one ACTIVE freeze of the given type. Returns
    (consumer, file, freeze) with the file re-fetched (so its version is current)."""
    consumer, _furnisher, cfile = setup_consumer_furnisher_file()
    v = get_file_version(cfile["id"])
    overrides = {"freeze_type": freeze_type, "effective_at": effective_at}
    if expires_at is not None:
        overrides["expires_at"] = expires_at
    freeze = place_freeze(consumer["id"], cfile["id"], v, **overrides)
    cfile = get_success_data(api_client.get_credit_file(cfile["id"], _BUREAU))
    return consumer, cfile, freeze


# --- Complaint setups -----------------------------------------------------------

def file_complaint(consumer_id, dispute_id, **overrides) -> dict:
    resp = api_client.create_complaint(
        create_complaint_payload(dispute_id, **overrides),
        make_consumer_headers(consumer_id),
    )
    return get_success_data(resp)


def setup_complaint_under_review():
    """A complaint UNDER_REVIEW whose dispute is at INVESTIGATING.
    Returns (consumer, furnisher, file, tradeline, dispute, complaint)."""
    consumer, furnisher, cfile, tl, dispute = setup_investigating_dispute()
    complaint = file_complaint(consumer["id"], dispute["id"])
    get_success_data(api_client.review_complaint(complaint["id"], _REGULATOR))
    complaint = get_success_data(api_client.get_complaint(complaint["id"], _REGULATOR))
    return consumer, furnisher, cfile, tl, dispute, complaint

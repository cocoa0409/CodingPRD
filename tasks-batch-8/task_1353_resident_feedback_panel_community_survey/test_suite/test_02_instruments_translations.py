"""Instrument revision loop, translation certification lifecycle, duplicate
translation and stale-revision guards."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_instrument_payload, create_translation_payload,
)

SD = TEST_USERS["survey_designer"]


def test_instrument_revision_cycle_stales_certified_translations(api):
    """PRD §3.3: "Revision loops back to `DRAFT`: from `IN_REVIEW` the `revision` is
    unchanged, while from `APPROVED` the `revision` increments by one and every
    `CERTIFIED` translation whose `instrument_revision` now trails the instrument's
    `revision` flips to `STALE`." and "Any instrument transition that is not valid
    from its current status — including everything attempted from `LOCKED` — is
    rejected with `ERR_INSTRUMENT_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/instrument_revision_cycle_stales_certified_translations
    """
    instr = validate_success(api.create_instrument(
        create_instrument_payload(title="Cyclic", question_count=8), SD), 201)

    validate_success(api.submit_instrument_review(instr["id"], SD), 200)
    back = validate_success(api.revise_instrument(instr["id"], SD), 200)
    assert back["revision"] == 1  # revise from IN_REVIEW: revision unchanged

    validate_success(api.submit_instrument_review(instr["id"], SD), 200)
    tr = validate_success(api.create_translation(
        create_translation_payload(instr["id"], locale="en"), SD), 201)
    validate_success(api.certify_translation(tr["id"], SD), 200)
    validate_success(api.approve_instrument(instr["id"], SD), 200)

    revised = validate_success(api.revise_instrument(instr["id"], SD), 200)
    assert revised["revision"] == 2

    tr_after = validate_success(api.get_translation(tr["id"], SD), 200)
    assert tr_after["status"] == "STALE"

    resubmitted = validate_success(api.resubmit_translation(tr["id"], SD), 200)
    assert resubmitted["instrument_revision"] == 2

    validate_success(api.submit_instrument_review(instr["id"], SD), 200)
    validate_success(api.certify_translation(tr["id"], SD), 200)
    validate_success(api.approve_instrument(instr["id"], SD), 200)
    locked = validate_success(api.lock_instrument(instr["id"], SD), 200)
    assert locked["status"] == "LOCKED"

    err = validate_error(api.revise_instrument(instr["id"], SD),
                         ApiErrorId.ERR_INSTRUMENT_INVALID_STATE)
    assert err["error_id"] == "ERR_INSTRUMENT_INVALID_STATE"


def test_locked_instrument_rejects_all_transitions(api):
    """PRD §3.3: "Locking moves `APPROVED` → `LOCKED`; a locked instrument is
    immutable and waves may arm against it. Any instrument transition that is not
    valid from its current status — including everything attempted from `LOCKED` —
    is rejected with `ERR_INSTRUMENT_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/instrument_revision_cycle_stales_certified_translations
    """
    instr = validate_success(api.create_instrument(create_instrument_payload(), SD), 201)
    validate_success(api.submit_instrument_review(instr["id"], SD), 200)
    tr = validate_success(api.create_translation(
        create_translation_payload(instr["id"], locale="en"), SD), 201)
    validate_success(api.certify_translation(tr["id"], SD), 200)
    validate_success(api.approve_instrument(instr["id"], SD), 200)
    locked = validate_success(api.lock_instrument(instr["id"], SD), 200)
    assert locked["status"] == "LOCKED"

    # Every instrument transition attempted from LOCKED is rejected.
    for call in (api.submit_instrument_review, api.approve_instrument,
                 api.revise_instrument, api.lock_instrument):
        err = validate_error(call(instr["id"], SD),
                             ApiErrorId.ERR_INSTRUMENT_INVALID_STATE)
        assert err["error_id"] == "ERR_INSTRUMENT_INVALID_STATE"


def test_translation_reject_resubmit_cycle(api):
    """PRD §3.3: "At most one non-`REJECTED` translation may exist per instrument and
    locale — a second live one fails with `ERR_DUPLICATE_TRANSLATION`" and
    "Resubmission moves `REJECTED` or `STALE` back to `SUBMITTED` and re-pins
    `instrument_revision` to the instrument's current `revision`."

    Design: Corner/state_machines/corner_translation_reject_resubmit_cycle
    """
    instr = validate_success(api.create_instrument(
        create_instrument_payload(required_locales=["en", "es"]), SD), 201)
    validate_success(api.submit_instrument_review(instr["id"], SD), 200)

    tr = validate_success(api.create_translation(
        create_translation_payload(instr["id"], locale="es", translator_ref="tr-1"),
        SD), 201)
    assert tr["status"] == "SUBMITTED"
    rejected = validate_success(api.reject_translation(tr["id"], SD), 200)
    assert rejected["status"] == "REJECTED"
    resubmitted = validate_success(api.resubmit_translation(tr["id"], SD), 200)
    assert resubmitted["status"] == "SUBMITTED"

    # A second live (non-REJECTED) translation for the same instrument+locale.
    err = validate_error(api.create_translation(
        create_translation_payload(instr["id"], locale="es", translator_ref="tr-2"),
        SD), ApiErrorId.ERR_DUPLICATE_TRANSLATION)
    assert err["error_id"] == "ERR_DUPLICATE_TRANSLATION"


def test_approve_without_required_locale_returns_409(api):
    """PRD §3.3: "Approval moves `IN_REVIEW` → `APPROVED` and requires that every
    locale in `required_locales` holds a translation in `CERTIFIED` status
    certifying the instrument's current `revision`; if any required locale lacks
    one, approval fails with `ERR_TRANSLATION_NOT_CERTIFIED`."

    Design: Corner/errors/corner_approve_without_required_locale_returns_409
    """
    instr = validate_success(api.create_instrument(
        create_instrument_payload(required_locales=["en", "es"]), SD), 201)
    validate_success(api.submit_instrument_review(instr["id"], SD), 200)
    tr_en = validate_success(api.create_translation(
        create_translation_payload(instr["id"], locale="en"), SD), 201)
    validate_success(api.certify_translation(tr_en["id"], SD), 200)

    err = validate_error(api.approve_instrument(instr["id"], SD),
                         ApiErrorId.ERR_TRANSLATION_NOT_CERTIFIED)
    assert err["error_id"] == "ERR_TRANSLATION_NOT_CERTIFIED"
    after = validate_success(api.get_instrument(instr["id"], SD), 200)
    assert after["status"] == "IN_REVIEW"


def test_translation_stale_revision_returns_409(api):
    """PRD §3.3: "Certification moves `SUBMITTED` → `CERTIFIED` and is guarded by two
    checks in this order: the instrument must be `IN_REVIEW` or `APPROVED`
    (otherwise `ERR_INSTRUMENT_NOT_IN_REVIEW`), and the translation's
    `instrument_revision` must equal the instrument's current `revision`
    (otherwise `ERR_TRANSLATION_STALE_REVISION`)."

    Design: Corner/errors/corner_translation_stale_revision_returns_409
    """
    instr = validate_success(api.create_instrument(
        create_instrument_payload(required_locales=["en"]), SD), 201)
    validate_success(api.submit_instrument_review(instr["id"], SD), 200)
    tr_en = validate_success(api.create_translation(
        create_translation_payload(instr["id"], locale="en"), SD), 201)
    validate_success(api.certify_translation(tr_en["id"], SD), 200)
    validate_success(api.approve_instrument(instr["id"], SD), 200)
    # 'de' translation pinned at revision 1, left SUBMITTED.
    tr_de = validate_success(api.create_translation(
        create_translation_payload(instr["id"], locale="de", translator_ref="tr-2"),
        SD), 201)
    # Revise from APPROVED bumps the instrument to revision 2.
    validate_success(api.revise_instrument(instr["id"], SD), 200)
    validate_success(api.submit_instrument_review(instr["id"], SD), 200)

    err = validate_error(api.certify_translation(tr_de["id"], SD),
                         ApiErrorId.ERR_TRANSLATION_STALE_REVISION)
    assert err["error_id"] == "ERR_TRANSLATION_STALE_REVISION"

"""Label versions, translations, publication and withdrawal (PRD §3.5, §3.6)."""

from flask import Blueprint, request

import db
import errors
import lookup
import response
import serializers
import validators
from errors import fail
from middleware import (ALL_ROLES, COMPLIANCE_OFFICER, LOCALIZATION_SPECIALIST,
                        authorize)
from services import calculations as calc
from services import reconcile

bp = Blueprint("labels", __name__)

CONFORMANCE_LEVELS = ("NONE", "WCAG_AA")
COMPLAINT_TERMINAL_FOR_GAP = ("UPHELD", "DISMISSED", "WITHDRAWN")


def _plan_labels(plan_id):
    return db.ordered([label for label in db.store.label_versions.values()
                       if label["plan_id"] == plan_id])


# ---------------------------------------------------------------------------
# drafting
# ---------------------------------------------------------------------------

@bp.route("/label-versions", methods=["POST"])
def create_label_version():
    authorize(COMPLIANCE_OFFICER)
    body = validators.json_body()

    plan_ref = validators.get_id_ref(body, "plan_id")
    effective_from_raw = validators.get_datetime(body, "effective_from")
    conformance = validators.get_enum(body, "accessibility_conformance",
                                      CONFORMANCE_LEVELS)
    expected = validators.get_int(body, "expected_plan_version")
    effective_until_raw = validators.get_datetime(body, "effective_until",
                                                  required=False, default=None,
                                                  nullable=True)
    discount = validators.get_bool(body, "discount_program_applied",
                                   required=False, default=None)

    effective_from = db.parse_iso(effective_from_raw)
    effective_until = db.parse_iso(effective_until_raw) \
        if effective_until_raw is not None else None
    if effective_until is not None and not effective_until > effective_from:
        validators.bad("Field 'effective_until' must be after "
                       "'effective_from'.")

    plan = lookup.service_plan(plan_ref)

    if expected != plan["version"]:
        fail(errors.ERR_STALE_PLAN_VERSION)

    # Step 11 — temporal admissibility against the plan's published label.
    published = calc.published_label(plan["id"])
    if published is not None:
        published_from = db.dt_of(published, "effective_from")
        if published_from is not None and not effective_from > published_from:
            fail(errors.ERR_LABEL_EFFECTIVE_NOT_AFTER_PUBLISHED)

    # Step 13 — half-open interval geometry against sibling drafts.
    for other in _plan_labels(plan["id"]):
        if other["publication_state"] != "DRAFT":
            continue
        other_from = db.dt_of(other, "effective_from")
        other_until = db.dt_of(other, "effective_until")
        starts_before_other_end = (other_until is None
                                   or effective_from < other_until)
        other_starts_before_end = (effective_until is None
                                   or other_from < effective_until)
        if starts_before_other_end and other_starts_before_end:
            fail(errors.ERR_LABEL_WINDOW_OVERLAP)

    if discount is None:
        discount = plan["discount_program_eligible"]

    highest = 0
    for other in _plan_labels(plan["id"]):
        if other["version_seq"] > highest:
            highest = other["version_seq"]

    label = db.new_record()
    label.update({
        "plan_id": plan["id"],
        "version_seq": highest + 1,
        "publication_state": "DRAFT",
        "substantiation_status": "PENDING_EVIDENCE",
        "effective_from": effective_from_raw,
        "effective_until": effective_until_raw,
        "accessibility_conformance": conformance,
        "discount_program_applied": discount,
        "attestation_id": None,
        "typical_download_mbps": None,
        "typical_upload_mbps": None,
        "typical_latency_ms": None,
        "methodology_url_snapshot": None,
        "price_disclosure_drift": False,
        "verified_locale_count": 0,
        "created_by_user_id": request.headers.get("X-User-ID"),
        "published_by_user_id": None,
        "published_at": None,
        "archived_at": None,
        "withdrawn_at": None,
    })
    reconcile.apply_label_figures(plan, label)
    db.store.label_versions[label["id"]] = label

    db.touch(plan)
    return response.success(serializers.label_version(label), 201)


@bp.route("/label-versions/<label_id>", methods=["GET"])
def read_label_version(label_id):
    authorize(*ALL_ROLES)
    label = lookup.label_version(label_id)
    return response.success(serializers.label_version(label), 200)


@bp.route("/label-versions", methods=["GET"])
def list_label_versions():
    authorize(*ALL_ROLES)
    validators.pagination_params()
    plan_id = request.args.get("plan_id")
    attestation_id = request.args.get("attestation_id")
    state = request.args.get("publication_state")
    effective_on_raw = request.args.get("effective_on")
    effective_on = db.parse_iso(effective_on_raw) \
        if effective_on_raw is not None else None

    rows = []
    for label in db.store.label_versions.values():
        if plan_id is not None and label["plan_id"] != plan_id:
            continue
        if attestation_id is not None and label["attestation_id"] != attestation_id:
            continue
        if state is not None and label["publication_state"] != state:
            continue
        if effective_on_raw is not None:
            if effective_on is None:
                continue
            label_from = db.dt_of(label, "effective_from")
            label_until = db.dt_of(label, "effective_until")
            if label_from is None or label_from > effective_on:
                continue
            if label_until is not None and not effective_on < label_until:
                continue
        rows.append(label)
    items, meta = validators.paginate(db.ordered(rows),
                                      serializers.label_version)
    return response.success_list(items, meta, 200)


# ---------------------------------------------------------------------------
# publication / withdrawal
# ---------------------------------------------------------------------------

@bp.route("/label-versions/<label_id>/publish", methods=["POST"])
def publish_label_version(label_id):
    authorize(COMPLIANCE_OFFICER)
    label = lookup.label_version(label_id)

    if label["publication_state"] != "DRAFT":
        fail(errors.ERR_LABEL_INVALID_STATE)

    actor = request.headers.get("X-User-ID")
    if actor == label["created_by_user_id"]:
        fail(errors.ERR_SOD_SELF_PUBLISH)

    if label["accessibility_conformance"] != "WCAG_AA":
        fail(errors.ERR_ACCESSIBILITY_FORMAT_UNSUPPORTED)

    plan = lookup.service_plan(label["plan_id"])

    candidates = [a for a in db.ordered(db.store.attestations.values())
                  if a["plan_id"] == plan["id"] and a["status"] == "CERTIFIED"]
    if not candidates:
        fail(errors.ERR_ATTESTATION_NOT_CERTIFIED)
    candidates.sort(key=lambda a: (a["certified_at"] or "", -a["_seq"]),
                    reverse=True)
    attestation = candidates[0]

    verified_locales = set()
    for translation in db.store.label_translations.values():
        if (translation["label_version_id"] == label["id"]
                and translation["status"] == "VERIFIED"):
            verified_locales.add(translation["locale"])
    for locale in plan["required_locales"]:
        if locale not in verified_locales:
            fail(errors.ERR_TRANSLATION_COVERAGE_INCOMPLETE)

    itemised_codes = {entry["fee_code"] for entry in label["fee_itemization"]}
    for line in calc.plan_fee_lines(plan["id"]):
        if line["label_category"] != "MONTHLY_RECURRING":
            continue
        if line["fee_code"] not in itemised_codes:
            fail(errors.ERR_FEE_ITEMIZATION_INCOMPLETE)

    # ---- the transition ---------------------------------------------------
    label["attestation_id"] = attestation["id"]
    label["typical_download_mbps"] = attestation["typical_download_mbps"]
    label["typical_upload_mbps"] = attestation["typical_upload_mbps"]
    label["typical_latency_ms"] = attestation["typical_latency_ms"]
    label["methodology_url_snapshot"] = \
        attestation["methodology_snapshot"]["methodology_url"]
    label["substantiation_status"] = "SUBSTANTIATED"
    label["publication_state"] = "PUBLISHED"
    label["published_at"] = db.now_iso()
    label["published_by_user_id"] = actor
    label["price_disclosure_drift"] = False

    predecessor = None
    for other in _plan_labels(plan["id"]):
        if other["id"] == label["id"]:
            continue
        if other["publication_state"] == "PUBLISHED":
            predecessor = other
    if predecessor is not None:
        predecessor["publication_state"] = "ARCHIVED"
        predecessor["archived_at"] = db.now_iso()
        predecessor["_pre_truncation_effective_until"] = \
            predecessor["effective_until"]
        current_until = db.dt_of(predecessor, "effective_until")
        new_from = db.dt_of(label, "effective_from")
        if current_until is None or (new_from is not None
                                     and current_until > new_from):
            predecessor["effective_until"] = label["effective_from"]
        db.touch(predecessor)

    db.touch(label)

    plan["active_label_version_id"] = label["id"]
    plan["price_disclosure_drift"] = False

    for complaint in db.ordered(db.store.complaints.values()):
        disputed = db.store.label_versions.get(
            complaint["disputed_label_version_id"])
        if disputed is None or disputed["plan_id"] != plan["id"]:
            continue
        if complaint["state"] in COMPLAINT_TERMINAL_FOR_GAP:
            continue
        if complaint["evidence_gap"]:
            complaint["evidence_gap"] = False
            db.touch(complaint)

    calc.recompute_plan_posture(plan)
    db.touch(plan)
    return response.success(serializers.label_version(label), 200)


@bp.route("/label-versions/<label_id>/withdraw", methods=["POST"])
def withdraw_label_version(label_id):
    authorize(COMPLIANCE_OFFICER)
    body = validators.json_body()
    validators.get_str(body, "reason", 1, None)

    label = lookup.label_version(label_id)
    if label["publication_state"] != "PUBLISHED":
        fail(errors.ERR_LABEL_INVALID_STATE)

    label["publication_state"] = "WITHDRAWN"
    label["withdrawn_at"] = db.now_iso()
    db.touch(label)

    plan = db.store.service_plans.get(label["plan_id"])

    restored = None
    if plan is not None:
        archived = [other for other in _plan_labels(plan["id"])
                    if other["publication_state"] == "ARCHIVED"]
        if archived:
            archived.sort(key=lambda r: (-r["version_seq"], r["_seq"]))
            restored = archived[0]
            restored["publication_state"] = "PUBLISHED"
            restored["archived_at"] = None
            if "_pre_truncation_effective_until" in restored:
                restored["effective_until"] = \
                    restored.pop("_pre_truncation_effective_until")
            db.touch(restored)

        plan["active_label_version_id"] = \
            restored["id"] if restored is not None else None
        calc.recompute_plan_posture(plan)
        db.touch(plan)

    return response.success(serializers.label_version(label), 200)


# ---------------------------------------------------------------------------
# translations
# ---------------------------------------------------------------------------

@bp.route("/label-versions/<label_id>/translations", methods=["POST"])
def create_translation(label_id):
    authorize(LOCALIZATION_SPECIALIST)
    body = validators.json_body()
    locale = validators.get_str(body, "locale", 2, 16)
    summary = validators.get_str(body, "translated_summary", 1, 2000)
    machine = validators.get_bool(body, "machine_translated", required=False,
                                 default=False)

    label = lookup.label_version(label_id)
    if label["publication_state"] != "DRAFT":
        fail(errors.ERR_LABEL_INVALID_STATE)

    for existing in db.store.label_translations.values():
        if (existing["label_version_id"] == label["id"]
                and existing["locale"] == locale):
            validators.bad("Field 'locale' already has a translation on this "
                           "label.")

    translation = db.new_record()
    translation.update({
        "label_version_id": label["id"],
        "locale": locale,
        "translated_summary": summary,
        "machine_translated": machine,
        "status": "DRAFT",
        "created_by_user_id": request.headers.get("X-User-ID"),
        "verified_by_user_id": None,
        "verified_at": None,
    })
    db.store.label_translations[translation["id"]] = translation

    db.touch(label)
    return response.success(serializers.label_translation(translation), 201)


@bp.route("/label-versions/<label_id>/translations", methods=["GET"])
def list_translations(label_id):
    authorize(*ALL_ROLES)
    validators.pagination_params()
    label = lookup.label_version(label_id)

    locale = request.args.get("locale")
    status = request.args.get("status")
    rows = [t for t in db.store.label_translations.values()
            if t["label_version_id"] == label["id"]
            and (locale is None or t["locale"] == locale)
            and (status is None or t["status"] == status)]
    items, meta = validators.paginate(db.ordered(rows),
                                      serializers.label_translation)
    return response.success_list(items, meta, 200)


@bp.route("/label-versions/<label_id>/translations/<translation_id>/verify",
          methods=["POST"])
def verify_translation(label_id, translation_id):
    authorize(LOCALIZATION_SPECIALIST)
    label = lookup.label_version(label_id)
    translation = lookup.translation_of_label(label, translation_id)

    if translation["status"] != "DRAFT":
        fail(errors.ERR_TRANSLATION_INVALID_STATE)
    if label["publication_state"] != "DRAFT":
        fail(errors.ERR_LABEL_INVALID_STATE)

    actor = request.headers.get("X-User-ID")
    if actor == translation["created_by_user_id"]:
        fail(errors.ERR_SOD_SELF_REVIEW)

    translation["status"] = "VERIFIED"
    translation["verified_by_user_id"] = actor
    translation["verified_at"] = db.now_iso()
    db.touch(translation)

    reconcile.recompute_verified_locale_count(label)
    db.touch(label)
    return response.success(serializers.label_translation(translation), 200)


# ---------------------------------------------------------------------------
# archival disclosure reads
# ---------------------------------------------------------------------------

@bp.route("/label-versions/<label_id>/disclosures", methods=["GET"])
def list_label_disclosures(label_id):
    authorize(*ALL_ROLES)
    validators.pagination_params()
    label = lookup.label_version(label_id)

    channel = request.args.get("channel")
    rows = [d for d in db.store.label_disclosures.values()
            if d["label_version_id"] == label["id"]
            and (channel is None or d["channel"] == channel)]
    items, meta = validators.paginate(db.ordered(rows),
                                      serializers.label_disclosure)
    return response.success_list(items, meta, 200)

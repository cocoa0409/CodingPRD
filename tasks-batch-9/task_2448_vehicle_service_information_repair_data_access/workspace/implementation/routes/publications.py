"""The publication pipeline: ingestion, validation and distribution -- PRD 3.6."""

from flask import Blueprint

from auth import authenticate
from calc import stamp_coverage_for_cell
from envelope import object_response
from errors import err
from serialize import project
from services import append_audit, cascade_versions_departure, find, sorted_rows
from store import store
from validate import body_object, check_allowed, get_enum, get_int, get_ref, get_str, pagination, q_enum, q_str

from routes.common import (
    DISTRIBUTION_STATUSES,
    PUBLICATION_TYPES,
    REVIEW_STATUSES,
    paged,
)

bp = Blueprint("publications", __name__)

PUBLICATION_READERS = ("PlatformAdmin", "ContentPublisher", "ComplianceOfficer", "ShopManager")


def _recompute_cell_coverage(version):
    publication = store.publications.get(version["publication_id"])
    if publication is not None:
        stamp_coverage_for_cell(publication["vehicle_model_id"], publication["system_area_id"])


@bp.post("/publications")
def open_publication():
    authenticate(("ContentPublisher",))
    body = body_object()
    check_allowed(body, ("vehicle_model_id", "system_area_id", "publication_type"))
    vehicle_model_id = get_ref(body, "vehicle_model_id")
    system_area_id = get_ref(body, "system_area_id")
    publication_type = get_enum(body, "publication_type", PUBLICATION_TYPES)
    if vehicle_model_id not in store.vehicle_models:
        raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND", "vehicle_model_id does not resolve.")
    if system_area_id not in store.system_areas:
        raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND", "system_area_id does not resolve.")

    row = store.base_row()
    row["vehicle_model_id"] = vehicle_model_id
    row["system_area_id"] = system_area_id
    row["publication_type"] = publication_type
    row["current_version_no"] = 0
    row["published_version_id"] = None
    store.publications[row["id"]] = row
    return object_response(project("publication", row), 201)


@bp.get("/publications/<publication_id>")
def read_publication(publication_id):
    authenticate(PUBLICATION_READERS)
    row = find(store.publications, publication_id, "ERR_PUBLICATION_NOT_FOUND")
    return object_response(project("publication", row))


@bp.get("/publications")
def list_publications():
    authenticate(PUBLICATION_READERS)
    vehicle_model_id = q_str("vehicle_model_id")
    system_area_id = q_str("system_area_id")
    publication_type = q_enum("publication_type", PUBLICATION_TYPES)
    limit, offset = pagination()

    rows = [
        row
        for row in store.publications.values()
        if (vehicle_model_id is None or row["vehicle_model_id"] == vehicle_model_id)
        and (system_area_id is None or row["system_area_id"] == system_area_id)
        and (publication_type is None or row["publication_type"] == publication_type)
    ]
    return paged("publication", rows, limit, offset)


@bp.post("/publications/<publication_id>/versions")
def ingest_version(publication_id):
    authenticate(("ContentPublisher",))
    # PRD 2.6: the leading path segment is resolved first, "regardless of what
    # the rest of the request contains".
    publication = find(store.publications, publication_id, "ERR_PUBLICATION_NOT_FOUND")
    body = body_object()
    check_allowed(
        body, ("source_tsb_ref", "calibration_procedure_ref", "expected_publication_version")
    )
    source_tsb_ref = get_str(body, "source_tsb_ref", min_len=1, max_len=40)
    calibration_procedure_ref = get_str(
        body,
        "calibration_procedure_ref",
        min_len=1,
        required=publication["publication_type"] == "CALIBRATION_DOC",
    )
    expected_version = get_int(body, "expected_publication_version", minimum=1)

    if expected_version != publication["version"]:
        raise err(
            "ERR_STALE_PUBLICATION_PARENT_VERSION",
            "expected_publication_version does not match the publication's current version.",
        )

    row = store.base_row()
    row["publication_id"] = publication["id"]
    row["version_no"] = publication["current_version_no"] + 1
    row["source_tsb_ref"] = source_tsb_ref
    row["calibration_procedure_ref"] = calibration_procedure_ref
    row["review_status"] = "DRAFT"
    row["distribution_status"] = "WITHHELD"
    row["validated_by_user_id"] = None
    row["published_by_user_id"] = None
    row["active_pin_count"] = 0
    store.publication_versions[row["id"]] = row

    publication["current_version_no"] = row["version_no"]
    store.touch(publication)
    return object_response(project("publication_version", row), 201)


@bp.get("/publications/<publication_id>/versions")
def list_versions(publication_id):
    authenticate(PUBLICATION_READERS)
    publication = find(store.publications, publication_id, "ERR_PUBLICATION_NOT_FOUND")
    review_status = q_enum("review_status", REVIEW_STATUSES)
    distribution_status = q_enum("distribution_status", DISTRIBUTION_STATUSES)
    limit, offset = pagination()

    rows = [
        row
        for row in store.publication_versions.values()
        if row["publication_id"] == publication["id"]
        and (review_status is None or row["review_status"] == review_status)
        and (distribution_status is None or row["distribution_status"] == distribution_status)
    ]
    # PRD 2.3: the versions of a single publication are ordered by version_no ASC.
    rows.sort(key=lambda item: item["version_no"])
    return paged("publication_version", rows, limit, offset, presorted=True)


@bp.post("/publication-versions/<version_id>/validate")
def validate_version(version_id):
    user_id, role = authenticate(("ContentPublisher",))
    body = body_object()
    check_allowed(body, ("reviewer_notes",))
    get_str(body, "reviewer_notes", min_len=1)
    version = find(store.publication_versions, version_id, "ERR_PUBLICATION_VERSION_NOT_FOUND")

    if version["review_status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT version may be validated.")
    if version["distribution_status"] == "RECALLED":
        raise err("ERR_INVALID_STATE", "A RECALLED version is not re-reviewed.")

    version["review_status"] = "VALIDATED"
    version["validated_by_user_id"] = user_id
    store.touch(version)
    _recompute_cell_coverage(version)
    return object_response(project("publication_version", version))


@bp.post("/publication-versions/<version_id>/publish")
def publish_version(version_id):
    user_id, role = authenticate(("ContentPublisher",))
    version = find(store.publication_versions, version_id, "ERR_PUBLICATION_VERSION_NOT_FOUND")
    # Ladder rung 5 outranks request shape and state.
    if version["validated_by_user_id"] is not None and version["validated_by_user_id"] == user_id:
        raise err(
            "ERR_SEGREGATION_OF_DUTIES",
            "The operator who validated this version may not publish it.",
        )
    check_allowed(body_object(), ())

    if version["distribution_status"] != "WITHHELD":
        raise err("ERR_INVALID_STATE", "Only a WITHHELD version may be published.")

    publication = store.publications.get(version["publication_id"])
    prior = None
    if publication is not None:
        siblings = sorted_rows(
            [
                row
                for row in store.publication_versions.values()
                if row["publication_id"] == publication["id"]
                and row["id"] != version["id"]
                and row["distribution_status"] == "PUBLISHED"
            ]
        )
        prior = siblings[0] if siblings else None

    version["distribution_status"] = "PUBLISHED"
    version["published_by_user_id"] = user_id
    store.touch(version)
    if publication is not None:
        publication["published_version_id"] = version["id"]
    append_audit(role, user_id, "PublicationVersion", version["id"], "VERSION_PUBLISHED")

    if prior is not None:
        prior["distribution_status"] = "SUPERSEDED"
        store.touch(prior)
        cascade_versions_departure(prior, "PINNED_VERSION_SUPERSEDED", "SYSTEM", None)

    _recompute_cell_coverage(version)
    return object_response(project("publication_version", version))


@bp.post("/publication-versions/<version_id>/recall")
def recall_version(version_id):
    user_id, role = authenticate(("ContentPublisher",))
    body = body_object()
    check_allowed(body, ("reason",))
    reason = get_str(body, "reason", min_len=1)
    version = find(store.publication_versions, version_id, "ERR_PUBLICATION_VERSION_NOT_FOUND")

    if version["distribution_status"] != "PUBLISHED":
        raise err("ERR_INVALID_STATE", "Only a PUBLISHED version may be recalled.")

    version["distribution_status"] = "RECALLED"
    store.touch(version)
    publication = store.publications.get(version["publication_id"])
    if publication is not None and publication.get("published_version_id") == version["id"]:
        publication["published_version_id"] = None
    append_audit(
        role,
        user_id,
        "PublicationVersion",
        version["id"],
        "VERSION_RECALLED",
        "reason=%s" % reason,
    )

    cascade_versions_departure(version, "PINNED_VERSION_RECALLED", "SYSTEM", None)
    _recompute_cell_coverage(version)
    return object_response(project("publication_version", version))

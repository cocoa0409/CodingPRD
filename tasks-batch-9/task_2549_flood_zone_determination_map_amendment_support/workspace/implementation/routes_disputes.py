"""Disputes, elevation certificates and map amendment packages (PRD 3.8, 3.9)."""
from datetime import timedelta

from flask import Blueprint

import calc
import enums
from authz import (
    ROLE_AGENCY_OFFICER,
    ROLE_BORROWER,
    ROLE_PROVIDER_ANALYST,
    ROLE_PROVIDER_REVIEWER,
    authorize,
)
from db import all_rows, db, new_row, touch
from errors import fail
from response import created, ok
from services import (
    dispute_sustained_cascade,
    must,
    store,
    structure_property,
    touch_folio,
)
from shape import Field, no_body, read_body

bp = Blueprint("disputes", __name__)

BORROWER = [ROLE_BORROWER]
REVIEWER = [ROLE_PROVIDER_REVIEWER]
AGENCY = [ROLE_AGENCY_OFFICER]
ANALYST = [ROLE_PROVIDER_ANALYST]
FILERS = [ROLE_BORROWER, ROLE_PROVIDER_ANALYST]


def _folio_of(determination):
    return db.loan_folios[determination["loan_folio_id"]]


# --- disputes --------------------------------------------------------------
def _basis_admissible(basis, determination, structure, prop, asserted):
    """Ladder priority 28: each basis carries its own evidentiary precondition."""
    if basis == "ELEVATION_ABOVE_BFE":
        validated = [
            c
            for c in all_rows("elevation_certificates")
            if c["structure_id"] == structure["id"] and c["status"] == "VALIDATED"
        ]
        if not validated:
            return False
    elif basis == "MAP_PANEL_STALE":
        panel = db.map_panels[determination["map_panel_id"]]
        later = [
            p
            for p in all_rows("map_panels")
            if p["community_id"] == panel["community_id"]
            and p["map_panel_number"] == panel["map_panel_number"]
            and p["revision_sequence"] > panel["revision_sequence"]
            and p["revision_status"] in ("PRELIMINARY", "APPEAL_OPEN", "LFD_ISSUED")
        ]
        if not later:
            return False
    elif basis == "GEOCODE_ERROR":
        if prop["geocode_method"] == "ROOFTOP":
            return False

    # a second round must be a genuinely new argument
    for prior in all_rows("disputes"):
        if prior["determination_id"] != determination["id"]:
            continue
        if calc.dec(prior["asserted_sfha_offset_ft"]) == calc.dec(asserted):
            return False
    return True


@bp.post("/disputes")
def file_dispute():
    actor = authorize(BORROWER)
    body = read_body(
        [
            Field("determination_id"),
            Field("basis", "enum", enum=enums.DISPUTE_BASES),
            Field("borrower_statement"),
            Field("asserted_sfha_offset_ft", "number"),
        ]
    )
    determination = must("determinations", body["determination_id"])
    folio = _folio_of(determination)

    # priority 8: only the borrower of record may dispute
    if actor.user_id != folio["borrower_user_id"]:
        fail(
            "ERR_BORROWER_NOT_ON_LOAN",
            "The acting borrower is not the borrower of record on this loan.",
        )

    # priority 11: only a live determination may be challenged
    if determination["status"] != "ISSUED":
        fail(
            "ERR_INVALID_DETERMINATION_STATE",
            "Only an ISSUED determination may be disputed (status is %s)."
            % determination["status"],
        )

    structure = db.structures[determination["structure_id"]]
    prop = structure_property(structure)
    if not _basis_admissible(
        body["basis"], determination, structure, prop, body["asserted_sfha_offset_ft"]
    ):
        fail(
            "ERR_DISPUTE_BASIS_UNSUPPORTED",
            "The asserted basis '%s' is not admissible on this determination."
            % body["basis"],
        )

    now = db.now()
    dispute = new_row(
        determination_id=determination["id"],
        basis=body["basis"],
        borrower_statement=body["borrower_statement"],
        asserted_sfha_offset_ft=body["asserted_sfha_offset_ft"],
        status="SUBMITTED",
        round_number=1,
        provider_recommendation=None,
        provider_reviewed_by_user_id=None,
        agency_concurrence=None,
        agency_reviewed_by_user_id=None,
        resolution=None,
        revised_determination_id=None,
        filed_at=now,
        decision_due_at=now + timedelta(days=calc.DISPUTE_DECISION_DAYS),
        resolved_at=None,
    )
    store("disputes", dispute)

    determination["status"] = "UNDER_DISPUTE"
    touch(determination)
    touch_folio(folio)
    return created(dispute)


@bp.post("/disputes/<dispute_id>/provider-review")
def provider_review(dispute_id):
    actor = authorize(REVIEWER)
    body = read_body(
        [Field("provider_recommendation", "enum", enum=enums.PROVIDER_RECOMMENDATIONS)]
    )
    dispute = must("disputes", dispute_id)
    determination = db.determinations[dispute["determination_id"]]

    # priority 9: the reviewer may not bless their own determination
    if actor.user_id == determination["issued_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The reviewer may not be the issuer of the disputed determination.",
        )

    if dispute["status"] != "SUBMITTED":
        fail(
            "ERR_INVALID_DISPUTE_STATE",
            "A provider recommendation requires a dispute in SUBMITTED (status is %s)."
            % dispute["status"],
        )

    dispute["provider_recommendation"] = body["provider_recommendation"]
    dispute["provider_reviewed_by_user_id"] = actor.user_id
    dispute["status"] = "JOINT_AGENCY_REVIEW"
    touch(dispute)
    return ok(dispute)


@bp.post("/disputes/<dispute_id>/agency-review")
def agency_review(dispute_id):
    actor = authorize(AGENCY)
    body = read_body(
        [Field("agency_concurrence", "enum", enum=enums.AGENCY_CONCURRENCES)]
    )
    dispute = must("disputes", dispute_id)

    # priority 9: the agency officer may not be the provider reviewer
    if (
        dispute["provider_reviewed_by_user_id"] is not None
        and actor.user_id == dispute["provider_reviewed_by_user_id"]
    ):
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The agency officer may not be the provider reviewer of record.",
        )

    if (
        dispute["status"] != "JOINT_AGENCY_REVIEW"
        or dispute["provider_recommendation"] is None
    ):
        fail(
            "ERR_INVALID_DISPUTE_STATE",
            "The joint review can only be closed on a dispute in JOINT_AGENCY_REVIEW.",
        )

    determination = db.determinations[dispute["determination_id"]]
    folio = _folio_of(determination)
    concurrence = body["agency_concurrence"]
    recommendation = dispute["provider_recommendation"]
    final_round = dispute["round_number"] >= calc.MAX_DISPUTE_ROUNDS
    now = db.now()

    dispute["agency_concurrence"] = concurrence
    dispute["agency_reviewed_by_user_id"] = actor.user_id

    if concurrence == "NON_CONCUR" and not final_round:
        # remand for a second provider look; the determination stays locked
        dispute["status"] = "SUBMITTED"
        dispute["round_number"] = dispute["round_number"] + 1
        dispute["provider_recommendation"] = None
        dispute["provider_reviewed_by_user_id"] = None
        dispute["filed_at"] = now
        dispute["decision_due_at"] = now + timedelta(days=calc.DISPUTE_DECISION_DAYS)
        touch(dispute)
        return ok(dispute)

    sustain = (concurrence == "CONCUR" and recommendation == "REVISE") or (
        concurrence == "NON_CONCUR" and recommendation == "UPHOLD"
    )
    if sustain:
        resolution = (
            "REVISED_BY_CONCURRENCE"
            if concurrence == "CONCUR"
            else "REVISED_BY_AGENCY_OVERRIDE"
        )
        dispute_sustained_cascade(dispute, determination, resolution)
        touch(dispute)
        return ok(dispute)

    resolution = (
        "UPHELD_BY_CONCURRENCE"
        if concurrence == "CONCUR"
        else "UPHELD_BY_AGENCY_OVERRIDE"
    )
    dispute["status"] = "DENIED"
    dispute["resolution"] = resolution
    dispute["resolved_at"] = now
    touch(dispute)
    determination["status"] = "ISSUED"
    touch(determination)
    touch_folio(folio)
    return ok(dispute)


# --- elevation certificates ------------------------------------------------
def _candidate_folios(structure, dispute):
    if dispute is not None:
        determination = db.determinations.get(dispute["determination_id"])
        if determination is not None:
            return [db.loan_folios[determination["loan_folio_id"]]]
        return []
    return [
        f
        for f in all_rows("loan_folios")
        if f["property_id"] == structure["property_id"]
    ]


@bp.post("/elevation-certificates")
def file_certificate():
    actor = authorize(FILERS)
    body = read_body(
        [
            Field("structure_id"),
            Field("surveyor_license_number"),
            Field("survey_date", "datetime"),
            Field("datum", "enum", enum=enums.DATUMS),
            Field("raw_lowest_floor_elevation_ft", "number", scale=2),
            Field("raw_lowest_adjacent_grade_ft", "number", scale=2),
            Field(
                "machinery_elevation_ft", "number", required=False, default=None,
                scale=2, nullable=True,
            ),
            Field("dispute_id", "string", required=False, default=None, nullable=True),
        ]
    )
    structure = must("structures", body["structure_id"])
    dispute = None
    if body["dispute_id"] is not None:
        dispute = must("disputes", body["dispute_id"])

    # priority 8: a borrower may only file against their own loan
    if actor.is_borrower:
        candidates = _candidate_folios(structure, dispute)
        if candidates and not any(
            f["borrower_user_id"] == actor.user_id for f in candidates
        ):
            fail(
                "ERR_BORROWER_NOT_ON_LOAN",
                "The acting borrower is not the borrower of record on this loan.",
            )

    # priority 17: dispute evidence must concern the disputed structure
    if dispute is not None:
        disputed = db.determinations[dispute["determination_id"]]
        if disputed["structure_id"] != structure["id"]:
            fail(
                "ERR_STRUCTURE_FOLIO_MISMATCH",
                "The certificate's structure is not the disputed determination's "
                "structure.",
            )

    prop = structure_property(structure)
    if prop["geocode_status"] != "GEOCODED":
        fail("ERR_PROPERTY_NOT_GEOCODED", "The property's geocode is unresolved.")

    panel = calc.effective_panel(prop)
    if panel is None:
        fail("ERR_NO_EFFECTIVE_PANEL", "No EFFECTIVE map panel governs this property.")

    community = db.communities[prop["community_id"]]
    floor_ft, lag_ft, freeboard, lag_freeboard = calc.cert_conversion(
        body["raw_lowest_floor_elevation_ft"],
        body["raw_lowest_adjacent_grade_ft"],
        body["datum"],
        community["state_code"],
        panel["base_flood_elevation_ft"],
    )
    row = new_row(
        structure_id=structure["id"],
        dispute_id=body["dispute_id"],
        reference_panel_id=panel["id"],
        surveyor_license_number=body["surveyor_license_number"],
        survey_date=body["survey_date"],
        datum=body["datum"],
        raw_lowest_floor_elevation_ft=body["raw_lowest_floor_elevation_ft"],
        raw_lowest_adjacent_grade_ft=body["raw_lowest_adjacent_grade_ft"],
        machinery_elevation_ft=body["machinery_elevation_ft"],
        converted_lowest_floor_ft=floor_ft,
        converted_lag_ft=lag_ft,
        freeboard_ft=freeboard,
        lag_freeboard_ft=lag_freeboard,
        status="SUBMITTED",
        rejection_reason=None,
        submitted_by_user_id=actor.user_id,
        reviewed_by_user_id=None,
    )
    return created(store("elevation_certificates", row))


@bp.post("/elevation-certificates/<elevation_certificate_id>/review")
def review_certificate(elevation_certificate_id):
    actor = authorize(REVIEWER)
    body = read_body(
        [
            Field("decision", "enum", enum=enums.CERTIFICATE_DECISIONS),
            Field(
                "rejection_reason", "enum", required=False, default=None,
                enum=enums.REJECTION_REASONS, nullable=True,
            ),
        ]
    )
    if body["decision"] == "REJECTED" and body["rejection_reason"] is None:
        fail(
            "ERR_INVALID_REQUEST",
            "Field 'rejection_reason' is required when the decision is REJECTED.",
        )
    certificate = must("elevation_certificates", elevation_certificate_id)

    # priority 9: the filer may not review their own certificate
    if actor.user_id == certificate["submitted_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The reviewer may not be the filer of the certificate.",
        )

    if certificate["status"] != "SUBMITTED":
        fail(
            "ERR_INVALID_CERTIFICATE_STATE",
            "Only a SUBMITTED certificate may be reviewed (status is %s)."
            % certificate["status"],
        )

    now = db.now()
    certificate["reviewed_by_user_id"] = actor.user_id
    if body["decision"] == "REJECTED":
        certificate["status"] = "REJECTED"
        certificate["rejection_reason"] = body["rejection_reason"]
        touch(certificate)
        return ok(certificate)

    # priority 21: a stale survey may not be validated
    if now > certificate["survey_date"] + timedelta(days=calc.CERTIFICATE_VALIDITY_DAYS):
        fail(
            "ERR_CERTIFICATE_EXPIRED",
            "The survey is more than %d days old." % calc.CERTIFICATE_VALIDITY_DAYS,
        )

    certificate["status"] = "VALIDATED"
    touch(certificate)

    structure = db.structures[certificate["structure_id"]]
    structure["lowest_floor_elevation_ft"] = certificate["converted_lowest_floor_ft"]
    structure["lowest_adjacent_grade_ft"] = certificate["converted_lag_ft"]
    structure["elevation_source_certificate_id"] = certificate["id"]
    touch(structure)

    # a survey says how high the building is, not where it sits: only the
    # freeboard of the governing determination is recomputed.
    for folio in all_rows("loan_folios"):
        determination = db.determinations.get(folio["current_determination_id"])
        if determination is None or determination["structure_id"] != structure["id"]:
            continue
        bfe = determination["base_flood_elevation_ft"]
        if bfe is None:
            determination["freeboard_ft"] = None
        else:
            determination["freeboard_ft"] = calc.round_half_up(
                calc.dec(structure["lowest_floor_elevation_ft"]) - calc.dec(bfe), 1
            )
        touch(determination)
    return ok(certificate)


# --- map amendment requests ------------------------------------------------
def _quote_fee(package):
    base, tier, surcharge, total = calc.amendment_fee(
        package["request_type"], package["resubmission_count"], package["expedite_flag"]
    )
    package["base_review_fee_cents"] = base
    package["fee_tier"] = tier
    package["expedite_surcharge_cents"] = surcharge
    package["total_fee_cents"] = total
    return package


@bp.post("/map-amendment-requests")
def prepare_amendment():
    actor = authorize(ANALYST)
    body = read_body(
        [
            Field("determination_id"),
            Field("elevation_certificate_id"),
            Field("request_type", "enum", enum=enums.REQUEST_TYPES),
            Field("expedite_flag", "bool", required=False, default=False),
        ]
    )
    determination = must("determinations", body["determination_id"])
    certificate = must("elevation_certificates", body["elevation_certificate_id"])

    # priority 16: only validated survey evidence supports an amendment
    if certificate["status"] != "VALIDATED":
        fail(
            "ERR_CERTIFICATE_NOT_VALIDATED",
            "The referenced elevation certificate is not VALIDATED.",
        )

    # priority 17: the certificate must describe the determination's structure
    if certificate["structure_id"] != determination["structure_id"]:
        fail(
            "ERR_STRUCTURE_FOLIO_MISMATCH",
            "The certificate's structure is not the determination's structure.",
        )

    # priority 18: the request type must match the structure's fill history
    structure = db.structures[determination["structure_id"]]
    fill = bool(structure["fill_placed_flag"])
    if (body["request_type"] == "LOMA" and fill) or (
        body["request_type"] == "LOMR_F" and not fill
    ):
        fail(
            "ERR_AMENDMENT_TYPE_MISMATCH",
            "A %s request does not match fill_placed_flag %s."
            % (body["request_type"], fill),
        )

    row = new_row(
        determination_id=determination["id"],
        elevation_certificate_id=certificate["id"],
        request_type=body["request_type"],
        expedite_flag=body["expedite_flag"],
        status="DRAFT",
        resubmission_count=0,
        base_review_fee_cents=0,
        fee_tier="TIER_1",
        expedite_surcharge_cents=0,
        total_fee_cents=0,
        agency_case_number=None,
        additional_data_note=None,
        prepared_by_user_id=actor.user_id,
        submitted_at=None,
        decided_at=None,
    )
    _quote_fee(row)
    return created(store("map_amendment_requests", row))


@bp.post("/map-amendment-requests/<map_amendment_request_id>/submission")
def submit_amendment(map_amendment_request_id):
    authorize(ANALYST)
    no_body()
    package = must("map_amendment_requests", map_amendment_request_id)

    if package["status"] not in ("DRAFT", "ADDITIONAL_DATA_REQUESTED"):
        fail(
            "ERR_INVALID_AMENDMENT_STATE",
            "A package in %s may not be submitted." % package["status"],
        )

    determination = db.determinations[package["determination_id"]]
    if determination["status"] not in ("ISSUED", "FLAGGED_FOR_REVIEW"):
        fail(
            "ERR_INVALID_DETERMINATION_STATE",
            "The determination under amendment is %s." % determination["status"],
        )

    certificate = db.elevation_certificates[package["elevation_certificate_id"]]
    # priority 16
    if certificate["status"] != "VALIDATED":
        fail(
            "ERR_CERTIFICATE_NOT_VALIDATED",
            "The referenced elevation certificate is no longer VALIDATED.",
        )

    now = db.now()
    # priority 21
    if now > certificate["survey_date"] + timedelta(days=calc.CERTIFICATE_VALIDITY_DAYS):
        fail(
            "ERR_CERTIFICATE_EXPIRED",
            "The survey is more than %d days old." % calc.CERTIFICATE_VALIDITY_DAYS,
        )

    resubmitting = package["status"] == "ADDITIONAL_DATA_REQUESTED"
    # priority 26
    if resubmitting and package["resubmission_count"] >= calc.MAX_RESUBMISSIONS:
        fail(
            "ERR_RESUBMISSION_LIMIT",
            "The package has already been resubmitted %d times."
            % package["resubmission_count"],
        )

    # priority 27: the structure must actually stand above the base flood elevation
    if package["request_type"] == "LOMA":
        margin = certificate["freeboard_ft"]
    else:
        margin = certificate["lag_freeboard_ft"]
    if margin is None or calc.dec(margin) <= 0:
        fail(
            "ERR_STRUCTURE_NOT_ABOVE_BFE",
            "The certificate does not place the structure above the base flood "
            "elevation.",
        )

    if resubmitting:
        package["resubmission_count"] = package["resubmission_count"] + 1
    package["status"] = "SUBMITTED_TO_AGENCY"
    package["submitted_at"] = now
    _quote_fee(package)
    touch(package)
    return ok(package)


@bp.post("/map-amendment-requests/<map_amendment_request_id>/agency-decision")
def decide_amendment(map_amendment_request_id):
    authorize(AGENCY)
    body = read_body(
        [
            Field("decision", "enum", enum=enums.AMENDMENT_DECISIONS),
            Field(
                "agency_case_number", "string", required=False, default=None,
                nullable=True,
            ),
            Field(
                "additional_data_note", "string", required=False, default=None,
                nullable=True,
            ),
        ]
    )
    package = must("map_amendment_requests", map_amendment_request_id)

    if package["status"] != "SUBMITTED_TO_AGENCY":
        fail(
            "ERR_INVALID_AMENDMENT_STATE",
            "Only a package in SUBMITTED_TO_AGENCY may be decided (status is %s)."
            % package["status"],
        )

    decision = body["decision"]
    if decision == "ADDITIONAL_DATA_REQUESTED":
        # priority 26: the agency must grant or deny once the cycle is exhausted
        if package["resubmission_count"] >= calc.MAX_RESUBMISSIONS:
            fail(
                "ERR_RESUBMISSION_LIMIT",
                "The package has already been resubmitted %d times."
                % package["resubmission_count"],
            )
        package["status"] = "ADDITIONAL_DATA_REQUESTED"
        package["additional_data_note"] = body["additional_data_note"]
    else:
        package["status"] = decision
        package["agency_case_number"] = body["agency_case_number"]
        package["decided_at"] = db.now()
    touch(package)
    return ok(package)

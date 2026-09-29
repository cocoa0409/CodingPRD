"""Bag lots, seal qualification, packout and compliance dossiers (PRD §3.9-§3.10)."""

from flask import Blueprint, g

import config as C
from auth import ANY_ROLE, endpoint
from errors import ApiError
from num import D, ZERO, f, r
from response import object_response
from services import calc, cascade, refs
from store import serialize, store
from validation import (
    fetch,
    get_bool,
    get_enum,
    get_int,
    get_num,
    get_str,
    list_endpoint,
    parse_body,
    require_unique,
    resolve_fks,
)

bp = Blueprint("converting", __name__)


def ok(entity):
    return object_response(serialize(entity), 200)


def created(entity):
    return object_response(serialize(entity), 201)


def _lot_pool(lot):
    """The regrind pool eligible for this lot's polymer family / food-contact status."""
    job, roll, run, line, recipe, plate = refs.lot_chain(lot)
    product = refs.product_of_lot(lot)
    return refs.eligible_pool(
        recipe["dominant_polymer_family"] if recipe else None,
        bool(product["food_contact_required"]) if product else False,
    )


# ================================================================= bag lots ==
@bp.post("/bag-lots")
@endpoint(["ConvertingOperator"])
def create_bag_lot():
    body = parse_body(required=True)
    lot_code = get_str(body, "lot_code")
    print_job_id = get_str(body, "print_job_id")
    product_id = get_str(body, "product_id")
    bag_count_produced = get_int(body, "bag_count_produced", gt=0)
    bag_count_scrapped = get_int(body, "bag_count_scrapped", required=False, default=0, ge=0)
    perforation_verified = get_bool(body, "perforation_verified", default=False)
    gusset_verified = get_bool(body, "gusset_verified", default=False)

    resolved = resolve_fks({"product_id": product_id, "print_job_id": print_job_id})
    product = resolved["product_id"]
    job = resolved["print_job_id"]
    require_unique(store.bag_lots, "lot_code", lot_code)

    if job["status"] != "COMPLETED":
        raise ApiError(
            "ERR_PRINT_JOB_STATE_INVALID", "A lot may only be opened from a COMPLETED print job."
        )

    plate = refs.plate_of_job(job)
    if plate is None or plate["product_id"] != product["id"]:
        raise ApiError(
            "ERR_PRODUCT_MISMATCH",
            "product_id must equal the product of the print job's plate set.",
        )

    roll = refs.roll_of_job(job)

    lot = store.new_common()
    lot.update(
        {
            "lot_code": lot_code,
            "print_job_id": job["id"],
            "product_id": product["id"],
            "bag_count_produced": bag_count_produced,
            "bag_count_scrapped": bag_count_scrapped,
            "bag_count_unpacked": bag_count_produced - bag_count_scrapped,
            "packed_bag_count": 0,
            "packed_case_count": 0,
            "partial_case_bag_count": 0,
            "pallet_count": 0,
            "bag_unit_weight_kg": 0.0,
            "bag_count_theoretical": 0,
            "count_accuracy_pct": None,
            "count_accuracy_conforming": False,
            "seal_specimens": [],
            "seal_provisional_mean_n": None,
            "seal_provisional_verdict": "PENDING",
            "seal_final_min_n": None,
            "seal_final_mean_n": None,
            "seal_final_verdict": "PENDING",
            "perforation_verified": perforation_verified,
            "gusset_verified": gusset_verified,
            "actual_recycled_content_pct": (
                roll.get("actual_recycled_content_pct") if roll else None
            ),
            "status": "CONVERTING",
            "quarantine_reason": None,
        }
    )
    store.bag_lots[lot["id"]] = lot
    calc.recompute_bag_counts(lot)
    return created(lot)


@bp.get("/bag-lots/<lot_id>")
@endpoint(ANY_ROLE)
def read_bag_lot(lot_id):
    return ok(fetch("bag_lot", lot_id))


@bp.get("/bag-lots")
@endpoint(ANY_ROLE)
def list_bag_lots():
    return list_endpoint(store.bag_lots, ("print_job_id", "product_id", "status"))


@bp.post("/bag-lots/<lot_id>/seal-tests")
@endpoint(["ConvertingOperator", "QualityManager"])
def append_seal_test(lot_id):
    body = parse_body(required=True)
    specimen_index = get_int(body, "specimen_index", ge=1)
    measured = get_num(body, "measured_n_per_15mm", ge=0)
    test_kind = get_enum(body, "test_kind", C.TEST_KINDS, required=False, default="BOTTOM_SEAL")

    lot = fetch("bag_lot", lot_id)
    if lot["status"] not in ("CONVERTING", "TESTING"):
        raise ApiError(
            "ERR_BAG_LOT_STATE_INVALID",
            "Seal specimens may only be appended to a CONVERTING or TESTING lot.",
        )

    product = refs.product_of_lot(lot)
    if product["perforation_required"] and not lot["perforation_verified"]:
        raise ApiError(
            "ERR_CONVERTING_FEATURE_NOT_VERIFIED",
            "This product requires perforation_verified before seal testing.",
        )
    if product["bag_style"] == "GUSSETED" and not lot["gusset_verified"]:
        raise ApiError(
            "ERR_CONVERTING_FEATURE_NOT_VERIFIED",
            "A GUSSETED product requires gusset_verified before seal testing.",
        )

    attempt = 1 + sum(
        1 for s in lot["seal_specimens"] if s["specimen_index"] == specimen_index
    )
    lot["seal_specimens"].append(
        {
            "specimen_index": specimen_index,
            "attempt": attempt,
            "test_kind": test_kind,
            "measured_n_per_15mm": measured,
            "is_retest": attempt > 1,
            "entered_by_user_id": g.user_id,
            "recorded_at": store.clock_iso(),
        }
    )
    if lot["status"] == "CONVERTING":
        lot["status"] = "TESTING"
    calc.recompute_seal_provisional(lot)
    store.touch(lot)
    return created(lot)


@bp.post("/bag-lots/<lot_id>/finalize-tests")
@endpoint(["QualityManager"])
def finalize_seal_tests(lot_id):
    parse_body(required=False)
    lot = fetch("bag_lot", lot_id)
    if lot["status"] != "TESTING":
        raise ApiError("ERR_BAG_LOT_STATE_INVALID", "Only a TESTING lot may be finalized.")

    panel = calc.superseding_panel(lot)
    if len(panel) < C.MIN_SEAL_SPECIMENS:
        raise ApiError(
            "ERR_INSUFFICIENT_SEAL_PANEL",
            "The superseding panel holds %d distinct specimen indices; %d are required."
            % (len(panel), C.MIN_SEAL_SPECIMENS),
        )

    verdict, min_n, mean_n = calc.final_seal_verdict(lot)

    pool = None
    if verdict == "FAIL":
        pool = _lot_pool(lot)
        if pool is None:
            raise ApiError(
                "ERR_NO_ELIGIBLE_REGRIND_POOL",
                "No regrind pool matches this lot's polymer family and food-contact status.",
            )

    lot["seal_final_min_n"] = f(min_n)
    lot["seal_final_mean_n"] = f(mean_n)
    lot["seal_final_verdict"] = verdict

    if verdict == "PASS":
        lot["status"] = "QUALIFIED"
    elif verdict == "CONDITIONAL":
        lot["status"] = "CONDITIONAL"
    else:
        lot["status"] = "FAILED"
        lot["bag_count_scrapped"] = lot["bag_count_produced"]
        lot["bag_count_unpacked"] = 0
    store.touch(lot)

    if verdict == "FAIL":
        content = lot.get("actual_recycled_content_pct")
        kg = r(D(lot["bag_count_produced"]) * D(lot["bag_unit_weight_kg"]), 3)
        pcr_kg = r(kg * D(content) / D(100), 3) if content is not None else ZERO
        cascade.book_transaction(
            pool,
            direction="IN",
            origin_kind="LOT_SCRAP",
            kg=kg,
            pcr_kg=pcr_kg,
            origin_ref_id=lot["id"],
        )
    return ok(lot)


@bp.post("/bag-lots/<lot_id>/packout")
@endpoint(["ConvertingOperator"])
def packout(lot_id):
    body = parse_body(required=True)
    requested_bags = get_int(body, "requested_bags", gt=0)
    expected_version = get_int(body, "expected_bag_lot_version")

    lot = fetch("bag_lot", lot_id)
    if expected_version != lot["version"]:
        raise ApiError(
            "ERR_STALE_BAG_LOT_VERSION",
            "expected_bag_lot_version %s does not match the lot's current version %s."
            % (expected_version, lot["version"]),
        )
    if lot["status"] not in ("QUALIFIED", "CONDITIONAL", "PACKED"):
        raise ApiError(
            "ERR_BAG_LOT_STATE_INVALID",
            "Packout requires a QUALIFIED, CONDITIONAL or PACKED lot.",
        )
    if requested_bags > int(lot["bag_count_unpacked"]):
        raise ApiError(
            "ERR_PACKOUT_EXCEEDS_UNPACKED",
            "requested_bags %d exceeds the lot's unpacked count of %s."
            % (requested_bags, lot["bag_count_unpacked"]),
        )

    product = refs.product_of_lot(lot)
    calc.case_packout_allocation(lot, product, requested_bags)
    calc.recompute_bag_counts(lot)
    lot["status"] = "PACKED"
    store.touch(lot)
    return ok(lot)


def _issued_dossier_for_release(lot, product):
    issued = [d for d in refs.dossiers_of_lot(lot) if d["status"] == "ISSUED"]
    if not issued:
        raise ApiError(
            "ERR_DOSSIER_NOT_ISSUED", "This lot has no compliance dossier in ISSUED status."
        )
    if lot["seal_final_verdict"] == "CONDITIONAL":
        conforming = [d for d in issued if d["claim_conformance"] == "CONFORMING"]
        if not conforming:
            raise ApiError(
                "ERR_DOSSIER_NOT_ISSUED",
                "A CONDITIONAL lot requires an ISSUED dossier whose claim_conformance is CONFORMING.",
            )
        issued = conforming
    if product["food_contact_required"]:
        declared = [d for d in issued if d["food_contact_declared"]]
        if not declared:
            raise ApiError(
                "ERR_FOOD_CONTACT_DECLARATION_INVALID",
                "A food-contact product requires an ISSUED dossier declaring food contact.",
            )
        issued = declared
    return issued[0]


@bp.post("/bag-lots/<lot_id>/release")
@endpoint(["QualityManager"])
def release_bag_lot(lot_id):
    parse_body(required=False)
    lot = fetch("bag_lot", lot_id)
    if lot["status"] != "PACKED":
        raise ApiError("ERR_BAG_LOT_STATE_INVALID", "Only a PACKED lot may be released.")

    product = refs.product_of_lot(lot)
    _issued_dossier_for_release(lot, product)

    if not lot["count_accuracy_conforming"]:
        raise ApiError(
            "ERR_COUNT_ACCURACY_OUT_OF_SPEC",
            "count_accuracy_pct %s is outside the product's tolerance."
            % lot["count_accuracy_pct"],
        )

    lot["status"] = "RELEASED"
    store.touch(lot)
    return ok(lot)


@bp.post("/bag-lots/<lot_id>/ship")
@endpoint(["PlantAdmin"])
def ship_bag_lot(lot_id):
    parse_body(required=False)
    lot = fetch("bag_lot", lot_id)
    if lot["status"] != "RELEASED":
        raise ApiError("ERR_BAG_LOT_STATE_INVALID", "Only a RELEASED lot may be shipped.")
    if int(lot["packed_case_count"]) <= 0:
        raise ApiError(
            "ERR_BAG_LOT_STATE_INVALID", "A lot with no packed cases cannot be shipped."
        )
    lot["status"] = "SHIPPED"
    store.touch(lot)
    return ok(lot)


# ===================================================== compliance dossiers ==
@bp.post("/compliance-dossiers")
@endpoint(["QualityManager"])
def create_dossier():
    body = parse_body(required=True)
    dossier_code = get_str(body, "dossier_code")
    bag_lot_id = get_str(body, "bag_lot_id")
    food_contact_declared = get_bool(body, "food_contact_declared", required=True, default=False)
    claim_pct = get_num(body, "recycled_content_claim_pct", ge=0, le=100)

    lot = resolve_fks({"bag_lot_id": bag_lot_id})["bag_lot_id"]
    require_unique(store.compliance_dossiers, "dossier_code", dossier_code)

    if lot["status"] not in ("QUALIFIED", "CONDITIONAL", "PACKED"):
        raise ApiError(
            "ERR_DOSSIER_STATE_INVALID",
            "A dossier may only be drafted for a QUALIFIED, CONDITIONAL or PACKED lot.",
        )

    dossier = store.new_common()
    dossier.update(
        {
            "dossier_code": dossier_code,
            "bag_lot_id": lot["id"],
            "food_contact_declared": food_contact_declared,
            "recycled_content_claim_pct": claim_pct,
            "as_built_recycled_content_pct": None,
            "claim_variance_pct": None,
            "claim_conformance": "PENDING",
            "status": "DRAFT",
            "issued_by_user_id": None,
            "issued_at": None,
            "revoked_at": None,
            "revocation_reason": None,
        }
    )
    store.compliance_dossiers[dossier["id"]] = dossier
    return created(dossier)


@bp.get("/compliance-dossiers/<dossier_id>")
@endpoint(ANY_ROLE)
def read_dossier(dossier_id):
    return ok(fetch("compliance_dossier", dossier_id))


@bp.get("/compliance-dossiers")
@endpoint(ANY_ROLE)
def list_dossiers():
    return list_endpoint(store.compliance_dossiers, ("bag_lot_id", "status", "claim_conformance"))


@bp.post("/compliance-dossiers/<dossier_id>/issue")
@endpoint(["QualityManager"])
def issue_dossier(dossier_id):
    parse_body(required=False)
    dossier = fetch("compliance_dossier", dossier_id)
    if dossier["status"] != "DRAFT":
        raise ApiError("ERR_DOSSIER_STATE_INVALID", "Only a DRAFT dossier may be issued.")

    lot = store.bag_lots.get(dossier["bag_lot_id"])
    if lot is None or lot["status"] not in ("QUALIFIED", "CONDITIONAL", "PACKED"):
        raise ApiError(
            "ERR_BAG_LOT_STATE_INVALID",
            "The documented lot must be QUALIFIED, CONDITIONAL or PACKED.",
        )
    if lot.get("actual_recycled_content_pct") is None:
        raise ApiError(
            "ERR_BAG_LOT_STATE_INVALID",
            "The lot has no as-built recycled-content figure to certify against.",
        )

    if any(s["entered_by_user_id"] == g.user_id for s in lot["seal_specimens"]):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "An operator who entered a seal specimen may not issue this lot's dossier.",
        )

    if dossier["food_contact_declared"]:
        job, roll, run, line, recipe, plate = refs.lot_chain(lot)
        recipe_ok = recipe is not None and bool(recipe["food_contact_eligible"])
        line_ok = line is not None and bool(line["food_contact_certified"])
        if not (recipe_ok and line_ok):
            raise ApiError(
                "ERR_FOOD_CONTACT_DECLARATION_INVALID",
                "A food-contact declaration requires a food-contact-eligible recipe and a certified line.",
            )

    as_built = D(lot["actual_recycled_content_pct"])
    variance = r(D(dossier["recycled_content_claim_pct"]) - as_built, 3)
    if variance > C.CLAIM_TOLERANCE_PCT:
        raise ApiError(
            "ERR_CLAIM_OVERSTATED",
            "The claim exceeds the as-built recycled content by %s points." % f(variance),
        )
    if abs(variance) <= C.CLAIM_TOLERANCE_PCT:
        conformance = "CONFORMING"
    else:
        conformance = "UNDERSTATED"

    dossier["as_built_recycled_content_pct"] = f(as_built)
    dossier["claim_variance_pct"] = f(variance)
    dossier["claim_conformance"] = conformance
    dossier["status"] = "ISSUED"
    dossier["issued_by_user_id"] = g.user_id
    dossier["issued_at"] = store.clock_iso()
    store.touch(dossier)
    return ok(dossier)


@bp.post("/compliance-dossiers/<dossier_id>/revoke")
@endpoint(["QualityManager"])
def revoke_dossier(dossier_id):
    body = parse_body(required=True)
    reason = get_str(body, "revocation_reason")
    dossier = fetch("compliance_dossier", dossier_id)
    if dossier["status"] != "ISSUED":
        raise ApiError("ERR_DOSSIER_STATE_INVALID", "Only an ISSUED dossier may be revoked.")

    dossier["status"] = "REVOKED"
    dossier["revocation_reason"] = reason
    dossier["revoked_at"] = store.clock_iso()
    store.touch(dossier)

    lot = store.bag_lots.get(dossier["bag_lot_id"])
    cascade.revoke_dossier_cascade(dossier, lot)
    return ok(dossier)

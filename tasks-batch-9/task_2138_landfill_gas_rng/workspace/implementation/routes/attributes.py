"""AttributeBatch endpoints: RIN / LCFS generation, stewardship and reversal."""

from decimal import Decimal

from flask import Blueprint

import calc
import derived
import store
from auth import authenticate, require_role
from common import month_in_quarter
from envelope import object_response, paginate, pagination
from errors import fail
from helpers import arg, filter_equal, must_find
from serializers import attribute_out
from validation import Field, MONTH_PATTERN, parse_body, validate

bp = Blueprint("attributes", __name__)

ZERO = Decimal("0")

ATTRIBUTE_FIELDS = [
    Field("injection_batch_id", "string", required=True),
    Field("program", "enum", required=True, values=("RIN_D3", "LCFS")),
    Field("generation_period", "string", required=True, max_len=7, pattern=MONTH_PATTERN),
    Field(
        "basis",
        "enum",
        values=("PROVISIONAL_NOMINATED", "SETTLED_METERED"),
        default="PROVISIONAL_NOMINATED",
    ),
]

REPORT_TYPE_FOR_PROGRAM = {
    "RIN_D3": "QUARTERLY_RIN_QAP",
    "LCFS": "LCFS_QUARTERLY",
}


@bp.post("/attribute-batches")
def create_attribute():
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "ComplianceOfficer"])
    body = parse_body()
    data = validate(body, ATTRIBUTE_FIELDS)

    batch = must_find("batch", data["injection_batch_id"])

    # Priority 80 - the source batch must have reached the pipeline.
    if batch["status"] != "INJECTED":
        fail("ERR_BATCH_NOT_INJECTED", "Attributes may only be generated from an INJECTED batch.")

    # Priority 100 - a settled basis needs the pipeline meter true-up first.
    if data["basis"] == "SETTLED_METERED" and batch["metered_mmbtu"] is None:
        fail(
            "ERR_METERED_VOLUME_REQUIRED",
            "The settled basis requires a metered volume on the source batch.",
        )

    # Priority 120 - one non-reversed batch per (injection batch, program).
    for other in store.attribute_batches.values():
        if (
            other["injection_batch_id"] == batch["id"]
            and other["program"] == data["program"]
            and other["status"] != "REVERSED"
        ):
            fail(
                "ERR_ATTRIBUTE_DUPLICATE_PROGRAM",
                "A live attribute batch already exists for this injection batch and program.",
            )

    plant = store.plants.get(batch["plant_id"])
    site = derived.site_of_batch(batch)

    if data["basis"] == "SETTLED_METERED":
        energy_basis = batch["metered_mmbtu"]
    else:
        energy_basis = batch["gross_mmbtu"]

    factor = calc.eligibility_factor(
        plant["availability_factor_pct"] if plant is not None else Decimal("100")
    )

    rin_count = 0
    lcfs_credits = ZERO
    ci_project = None

    if data["program"] == "RIN_D3":
        rin_count = calc.rin_d3(energy_basis, factor)
    else:
        injected = site["energy_injected_mmbtu"] if site is not None else ZERO
        flared = site["energy_flared_mmbtu"] if site is not None else ZERO
        ci_project, lcfs_credits = calc.lcfs(energy_basis, injected, flared)

    row = store.new_row(
        injection_batch_id=batch["id"],
        program=data["program"],
        basis=data["basis"],
        generation_period=data["generation_period"],
        energy_basis_mmbtu=energy_basis,
        eligibility_factor=factor,
        rin_count=rin_count,
        ci_project_gco2e_per_mj=ci_project,
        lcfs_credits=lcfs_credits,
        status="GENERATED",
        reversal_reason=None,
    )
    store.attribute_batches[row["id"]] = row

    if site is not None and data["program"] == "RIN_D3":
        derived.move_rins(site, generated=rin_count, available=rin_count)

    return object_response(attribute_out(row), 201)


@bp.get("/attribute-batches/<attribute_id>")
def read_attribute(attribute_id):
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "ComplianceOfficer", "CommercialScheduler"])
    row = must_find("attribute", attribute_id)
    return object_response(attribute_out(row))


@bp.get("/attribute-batches")
def list_attributes():
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "ComplianceOfficer", "CommercialScheduler"])
    limit, offset = pagination()
    rows = store.ordered(store.attribute_batches.values())
    rows = filter_equal(rows, "injection_batch_id", arg("injection_batch_id"))
    rows = filter_equal(rows, "program", arg("program"))
    rows = filter_equal(rows, "status", arg("status"))
    rows = filter_equal(rows, "generation_period", arg("generation_period"))
    return paginate(rows, limit, offset, attribute_out)


ATTRIBUTE_STATUS_FIELDS = [
    Field(
        "to_status",
        "enum",
        required=True,
        values=("PENDING", "GENERATED", "QA_HOLD", "SEPARATED", "RETIRED", "REVERSED"),
    ),
    Field(
        "reason",
        "enum",
        values=("UPSTREAM_BATCH_DIVERTED", "BASIS_RESTATEMENT", "QA_FAILURE", "REPORT_REJECTED"),
    ),
]

ATTRIBUTE_TRANSITIONS = {
    ("GENERATED", "QA_HOLD"),
    ("QA_HOLD", "GENERATED"),
    ("GENERATED", "SEPARATED"),
    ("SEPARATED", "RETIRED"),
    ("PENDING", "REVERSED"),
    ("GENERATED", "REVERSED"),
    ("QA_HOLD", "REVERSED"),
    ("SEPARATED", "REVERSED"),
}


@bp.post("/attribute-batches/<attribute_id>/status")
def attribute_status(attribute_id):
    caller = authenticate()
    require_role(caller, ["ComplianceOfficer"])
    attribute = must_find("attribute", attribute_id)
    body = parse_body()
    data = validate(body, ATTRIBUTE_STATUS_FIELDS)

    target = data["to_status"]
    current = attribute["status"]

    # Priority 80 - state legality.
    if (current, target) not in ATTRIBUTE_TRANSITIONS:
        fail("ERR_INVALID_TRANSITION", "%s -> %s is not a declared transition." % (current, target))

    # Priority 100 - separation needs an accepted filing covering the period.
    if target == "SEPARATED":
        site = derived.site_of_attribute(attribute)
        wanted_type = REPORT_TYPE_FOR_PROGRAM[attribute["program"]]
        found = False
        if site is not None:
            for report in store.compliance_reports.values():
                if (
                    report["site_id"] == site["id"]
                    and report["status"] == "ACCEPTED"
                    and report["report_type"] == wanted_type
                    and month_in_quarter(attribute["generation_period"], report["period"])
                ):
                    found = True
                    break
        if not found:
            fail(
                "ERR_REPORT_NOT_ACCEPTED",
                "No accepted compliance filing of the matching type covers this period.",
            )

    if target == "RETIRED":
        site = derived.site_of_attribute(attribute)
        derived.apply_changes(attribute, {"status": "RETIRED"})
        if site is not None and attribute["program"] == "RIN_D3":
            derived.move_rins(
                site, available=-attribute["rin_count"], retired=attribute["rin_count"]
            )
    elif target == "REVERSED":
        derived.reverse_attribute(attribute, data["reason"])
    else:
        derived.apply_changes(attribute, {"status": target})

    return object_response(attribute_out(attribute))

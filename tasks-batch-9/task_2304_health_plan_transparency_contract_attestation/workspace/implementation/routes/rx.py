"""RxDataSubmission and VendorDataPackage endpoints (PRD 3.6)."""

from flask import Blueprint

import calc
import clock
import db
import domain
import guards
import response

bp = Blueprint("rx", __name__)

READ_ROLES = ("PlanSponsorAdmin", "ComplianceOfficer", "ExternalAuditor")
DATA_SECTIONS = ("D2_SPENDING", "D6_RX_TOTALS", "D7_RX_REBATES", "D8_PREMIUM_IMPACT")


# ---------------------------------------------------------------------------
# RxDataSubmission
# ---------------------------------------------------------------------------


@bp.route("/compliance/rx-data-submissions", methods=["POST"])
def create_submission():
    guards.authorize("PlanSponsorAdmin", "ComplianceOfficer")
    body = guards.read_body()
    plan_year_id = guards.field(body, "plan_year_id", "string")
    reference_year = guards.field(body, "reference_year", "integer")
    plan_year = guards.fetch("plan_year", plan_year_id)
    guards.not_frozen(plan_year)
    guards.require(
        plan_year["lifecycle_status"] == "ACTIVE",
        "ERR_INVALID_STATE_TRANSITION",
        "The plan year must be ACTIVE to open a prescription-drug submission.",
    )
    # Ladder step 44 — reference year aligned with the plan year.
    start_year = int(plan_year["start_date"][0:4])
    guards.require(
        reference_year >= 2020 and reference_year in (start_year, start_year - 1),
        "ERR_RX_REFERENCE_YEAR_INVALID",
        "reference_year must be %d or %d." % (start_year - 1, start_year),
    )
    record = db.common_fields()
    record.update({
        "plan_year_id": plan_year_id,
        "reference_year": reference_year,
        "status": "OPEN",
        "assembled_record_count": 0,
        "gross_spend_cents": None,
        "rebate_reported_cents": None,
        "rebate_cap_pct": None,
        "rebate_credit_cents": None,
        "net_plan_spend_cents": None,
        "reconciled_at": None,
        "submitted_at": None,
    })
    db.rx_submissions[record["id"]] = record
    return response.created_response(response.public(record))


@bp.route("/compliance/rx-data-submissions/<row_id>", methods=["GET"])
def get_submission(row_id):
    guards.authorize(*READ_ROLES)
    return response.object_response(
        response.public(guards.fetch("rx_submission", row_id))
    )


@bp.route("/compliance/rx-data-submissions", methods=["GET"])
def list_submissions():
    guards.authorize(*READ_ROLES)
    limit, offset = guards.pagination()
    guards.filter_fk("plan_year", "plan_year_id")
    rows = guards.apply_filters(db.ordered(db.rx_submissions), [
        ("plan_year_id", "plan_year_id", None),
        ("status", "status", None),
        ("reference_year", "reference_year", int),
    ])
    page, total = guards.paginate(rows, limit, offset)
    return response.array_response(
        [response.public(r) for r in page], limit, offset, total
    )


def _all_validated(submission_id):
    packages = db.packages_of_submission(submission_id)
    return bool(packages) and all(p["status"] == "VALIDATED" for p in packages)


@bp.route("/compliance/rx-data-submissions/<row_id>/reconcile", methods=["POST"])
def reconcile_submission(row_id):
    guards.authorize("ComplianceOfficer")
    submission = guards.fetch("rx_submission", row_id)
    guards.read_body()
    plan_year = db.plan_years.get(submission["plan_year_id"])
    guards.not_frozen(plan_year)
    guards.state_is(submission["status"], "ASSEMBLING")
    # Ladder step 17 — every package validated, and at least one package.
    guards.require(
        _all_validated(submission["id"]),
        "ERR_PACKAGES_NOT_VALIDATED",
        "Every vendor data package must be VALIDATED before reconciliation.",
    )
    validated = [
        p for p in db.packages_of_submission(submission["id"])
        if p["status"] == "VALIDATED"
    ]
    totals = calc.rxdc_totals(validated)
    with db.txn(submission):
        submission["status"] = "RECONCILED"
        submission["gross_spend_cents"] = totals["gross_spend_cents"]
        submission["rebate_reported_cents"] = totals["rebate_reported_cents"]
        submission["rebate_cap_pct"] = totals["rebate_cap_pct"]
        submission["rebate_credit_cents"] = totals["rebate_credit_cents"]
        submission["net_plan_spend_cents"] = totals["net_plan_spend_cents"]
        submission["reconciled_at"] = clock.now_iso()
    return response.object_response(response.public(submission))


@bp.route("/compliance/rx-data-submissions/<row_id>/submit", methods=["POST"])
def submit_submission(row_id):
    guards.authorize("ComplianceOfficer")
    submission = guards.fetch("rx_submission", row_id)
    guards.read_body()
    plan_year = db.plan_years.get(submission["plan_year_id"])
    guards.not_frozen(plan_year)
    guards.state_is(submission["status"], "RECONCILED")
    guards.require(
        plan_year is not None and plan_year["lifecycle_status"] == "ACTIVE",
        "ERR_INVALID_STATE_TRANSITION",
        "The plan year must be ACTIVE to file a prescription-drug submission.",
    )
    # Ladder step 17 — re-checked at filing time.
    guards.require(
        _all_validated(submission["id"]),
        "ERR_PACKAGES_NOT_VALIDATED",
        "Every vendor data package must still be VALIDATED at filing time.",
    )
    with db.txn(submission):
        submission["status"] = "SUBMITTED"
        submission["submitted_at"] = clock.now_iso()
    if plan_year is not None:
        with db.txn(plan_year):
            domain.recompute_posture(plan_year)
    return response.object_response(response.public(submission))


# ---------------------------------------------------------------------------
# VendorDataPackage
# ---------------------------------------------------------------------------


@bp.route("/compliance/vendor-data-packages", methods=["POST"])
def create_package():
    guards.authorize("PlanSponsorAdmin", "ComplianceOfficer")
    body = guards.read_body()
    submission_id = guards.field(body, "rx_submission_id", "string")
    vendor_id = guards.field(body, "vendor_id", "string")
    data_section = guards.field(body, "data_section", "enum", enum=DATA_SECTIONS)
    expected = guards.field(body, "expected_record_count", "integer")
    guards.require(
        expected >= 0,
        "ERR_INVALID_REQUEST",
        "expected_record_count must be at least 0.",
    )
    submission = guards.fetch("rx_submission", submission_id)
    guards.fetch("vendor", vendor_id)
    plan_year = db.plan_years.get(submission["plan_year_id"])
    guards.not_frozen(plan_year)
    # Ladder step 42 — one package per (submission, vendor, section).
    for existing in db.packages_of_submission(submission_id):
        if existing["vendor_id"] == vendor_id and existing["data_section"] == data_section:
            guards.require(
                False,
                "ERR_DUPLICATE_DATA_SECTION",
                "A package for %s / %s already exists on this submission."
                % (vendor_id, data_section),
            )
    record = db.common_fields()
    record.update({
        "rx_submission_id": submission_id,
        "vendor_id": vendor_id,
        "data_section": data_section,
        "expected_record_count": expected,
        "status": "EXPECTED",
        "record_count": None,
        "plan_paid_cents": None,
        "member_paid_cents": None,
        "rebate_cents": None,
        "delivery_round": 0,
        "rejection_reason": None,
        "validated_at": None,
    })
    db.packages[record["id"]] = record
    return response.created_response(response.public(record))


@bp.route("/compliance/vendor-data-packages/<row_id>", methods=["GET"])
def get_package(row_id):
    role = guards.authorize(
        "PlanSponsorAdmin", "ComplianceOfficer", "ExternalAuditor", "VendorContact"
    )[1]
    package = guards.fetch("package", row_id)
    guards.vendor_identity(role, guards.caller_id())
    return response.object_response(response.public(package))


@bp.route("/compliance/vendor-data-packages", methods=["GET"])
def list_packages():
    role = guards.authorize(
        "PlanSponsorAdmin", "ComplianceOfficer", "ExternalAuditor", "VendorContact"
    )[1]
    limit, offset = guards.pagination()
    guards.filter_fk("rx_submission", "rx_submission_id")
    guards.filter_fk("vendor", "vendor_id")
    guards.vendor_identity(role, guards.caller_id())
    rows = guards.apply_filters(db.ordered(db.packages), [
        ("rx_submission_id", "rx_submission_id", None),
        ("vendor_id", "vendor_id", None),
        ("data_section", "data_section", None),
        ("status", "status", None),
    ])
    page, total = guards.paginate(rows, limit, offset)
    return response.array_response(
        [response.public(r) for r in page], limit, offset, total
    )


def _data_rights_secured(submission, vendor_id):
    if submission is None:
        return False
    for contract in db.contracts_of_plan_year(submission["plan_year_id"]):
        if contract["vendor_id"] == vendor_id and contract["data_rights_status"] == "SECURED":
            return True
    return False


def _delivery_payload(body):
    record_count = guards.field(body, "record_count", "integer")
    plan_paid = guards.field(body, "plan_paid_cents", "integer")
    member_paid = guards.field(body, "member_paid_cents", "integer")
    rebate = guards.field(body, "rebate_cents", "integer")
    return record_count, plan_paid, member_paid, rebate


def _deliver(user_id, role, package, from_state, clear_rejection):
    body = guards.read_body()
    record_count, plan_paid, member_paid, rebate = _delivery_payload(body)
    # Ladder step 7 — vendor scope.
    guards.vendor_scope(role, user_id, package["vendor_id"])
    submission = db.rx_submissions.get(package["rx_submission_id"])
    plan_year = db.plan_year_of_package(package)
    guards.not_frozen(plan_year)
    guards.state_is(package["status"], from_state)
    # Ladder step 16 — secured data rights for this vendor and plan year.
    guards.require(
        _data_rights_secured(submission, package["vendor_id"]),
        "ERR_DATA_RIGHTS_NOT_SECURED",
        "No contract with SECURED data rights joins this vendor to the plan year.",
    )
    # Ladder step 33 — package totals.
    guards.require(
        record_count >= 1 and plan_paid >= 0 and member_paid >= 0 and rebate >= 0,
        "ERR_INVALID_PACKAGE_TOTALS",
        "record_count must be >= 1 and the monetary totals must be >= 0.",
    )
    # Ladder step 40 — vendor identity resolves.
    guards.vendor_identity(role, user_id)
    with db.txn(package):
        package["status"] = "RECEIVED"
        package["record_count"] = record_count
        package["plan_paid_cents"] = plan_paid
        package["member_paid_cents"] = member_paid
        package["rebate_cents"] = rebate
        package["delivery_round"] = package["delivery_round"] + 1
        if clear_rejection:
            package["rejection_reason"] = None
    # Bubble-up: the first delivery advances the submission OPEN -> ASSEMBLING.
    if submission is not None and submission["status"] == "OPEN":
        with db.txn(submission):
            submission["status"] = "ASSEMBLING"
    return response.object_response(response.public(package))


@bp.route("/compliance/vendor-data-packages/<row_id>/deliver", methods=["POST"])
def deliver_package(row_id):
    user_id, role = guards.authorize("VendorContact")
    package = guards.fetch("package", row_id)
    return _deliver(user_id, role, package, "EXPECTED", clear_rejection=False)


@bp.route("/compliance/vendor-data-packages/<row_id>/resubmit", methods=["POST"])
def resubmit_package(row_id):
    user_id, role = guards.authorize("VendorContact")
    package = guards.fetch("package", row_id)
    return _deliver(user_id, role, package, "REJECTED", clear_rejection=True)


@bp.route("/compliance/vendor-data-packages/<row_id>/validate", methods=["POST"])
def validate_package(row_id):
    guards.authorize("ComplianceOfficer")
    package = guards.fetch("package", row_id)
    guards.read_body()
    submission = db.rx_submissions.get(package["rx_submission_id"])
    plan_year = db.plan_year_of_package(package)
    guards.not_frozen(plan_year)
    guards.state_is(package["status"], "RECEIVED")
    # Ladder step 33 — validation re-checks the delivered record count.
    guards.require(
        (package["record_count"] or 0) >= 1,
        "ERR_INVALID_PACKAGE_TOTALS",
        "record_count must be >= 1 to validate a package.",
    )
    with db.txn(package):
        package["status"] = "VALIDATED"
        package["validated_at"] = clock.now_iso()
    if submission is not None:
        with db.txn(submission):
            submission["assembled_record_count"] = (
                submission["assembled_record_count"] + package["record_count"]
            )
    return response.object_response(response.public(package))


@bp.route("/compliance/vendor-data-packages/<row_id>/reject", methods=["POST"])
def reject_package(row_id):
    user_id, _role = guards.authorize("ComplianceOfficer")
    package = guards.fetch("package", row_id)
    body = guards.read_body()
    reason = guards.field(body, "rejection_reason", "string")
    submission = db.rx_submissions.get(package["rx_submission_id"])
    plan_year = db.plan_year_of_package(package)
    guards.not_frozen(plan_year)
    guards.state_is(package["status"], "RECEIVED", "VALIDATED")
    was_validated = package["status"] == "VALIDATED"
    # CASCADE-B link 1.
    with db.txn(package):
        package["status"] = "REJECTED"
        package["rejection_reason"] = reason
    if was_validated and submission is not None:
        demoted = submission["status"] == "RECONCILED"
        # CASCADE-B links 2 and 3.
        with db.txn(submission):
            submission["assembled_record_count"] = (
                submission["assembled_record_count"] - (package["record_count"] or 0)
            )
            if demoted:
                submission["status"] = "ASSEMBLING"
                submission["gross_spend_cents"] = None
                submission["rebate_reported_cents"] = None
                submission["rebate_cap_pct"] = None
                submission["rebate_credit_cents"] = None
                submission["net_plan_spend_cents"] = None
                submission["reconciled_at"] = None
        # CASCADE-B link 4.
        if demoted and plan_year is not None:
            deadline = plan_year["rxdc_deadline_date"]
            if clock.today_iso() > deadline and not domain.has_unreversed_accrual(
                plan_year["id"], "RXDC_LATE"
            ):
                onset = clock.plus_days(clock.parse_date(deadline), 1).isoformat()
                with db.txn(plan_year):
                    domain.post_accrual(
                        plan_year,
                        "RXDC_LATE",
                        onset,
                        "Reconciliation demoted after package %s was rejected."
                        % package["id"],
                        user_id,
                    )
                    domain.recompute_exposure(plan_year)
                    domain.recompute_posture(plan_year)
    return response.object_response(response.public(package))

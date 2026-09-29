"""Licensee lifecycle and brokerage lifecycle write endpoints."""
from datetime import timedelta

from flask import Blueprint

import cascades
import computed
import envelope
import serialize
import shape
import store
from authz import guard
from errors import fail, invalid

bp = Blueprint("licensing", __name__)


# ------------------------------------------------------------------ licensees
@bp.post("/commission/licensees")
def create_licensee():
    guard(["LicensingAnalyst"])
    data = shape.body()
    person_type = shape.req_enum(data, "person_type", computed.PERSON_TYPES)
    full_name = shape.req_str(data, "full_name")
    prelicense_hours = shape.req_int(data, "prelicense_hours", minimum=0)
    row = store.insert("licensee", {
        "license_number": store.next_license_number(person_type),
        "person_type": person_type,
        "full_name": full_name,
        "prelicense_hours": prelicense_hours,
        "license_status": "APPLICANT",
        "discipline_status": "NONE",
        "exam_attempt_count": 0,
        "exam_best_score": 0,
        "exam_passed_at": None,
        "sponsoring_brokerage_id": None,
        "supervising_broker_id": None,
        "license_issued_at": None,
        "license_expires_at": None,
        "inactive_since": None,
        "ce_period_start_on": None,
        "suspension_ends_at": None,
        "_suspension_order_id": None,
    })
    return envelope.created(serialize.licensee(row))


@bp.post("/commission/licensees/<lid>/exam-results")
def record_exam_result(lid):
    guard(["LicensingAnalyst"])
    data = shape.body()
    score = shape.req_int(data, "score")
    shape.req_date(data, "taken_on")
    licensee = computed.must("licensee", lid)

    status = licensee["license_status"]
    if status not in ("APPLICANT", "DENIED"):
        fail("ERR_INVALID_STATE",
             "Exam results may only be recorded for an APPLICANT.")
    if licensee["exam_attempt_count"] >= computed.EXAM_MAX_ATTEMPTS:
        fail("ERR_EXAM_ATTEMPTS_EXHAUSTED", "All three exam attempts are used up.")
    needed = (computed.PRELICENSE_HOURS_BROKER if licensee["person_type"] == "BROKER"
              else computed.PRELICENSE_HOURS_SALESPERSON)
    if licensee["prelicense_hours"] < needed:
        fail("ERR_PRELICENSE_HOURS_INSUFFICIENT",
             "%d pre-licence hours are required." % needed)

    prior_attempts = licensee["exam_attempt_count"]
    licensee["exam_attempt_count"] = prior_attempts + 1
    if score > licensee["exam_best_score"]:
        licensee["exam_best_score"] = score
    if score >= computed.EXAM_PASS_SCORE:
        licensee["license_status"] = "EXAM_PASSED"
        licensee["exam_passed_at"] = store.fmt_dt(store.now())
    elif prior_attempts == computed.EXAM_MAX_ATTEMPTS - 1:
        licensee["license_status"] = "DENIED"
    store.touch(licensee)
    return envelope.ok(serialize.licensee(licensee))


def _check_supervising_broker(supervisor, brokerage, bootstrap):
    if supervisor["person_type"] != "BROKER":
        fail("ERR_SUPERVISING_BROKER_INELIGIBLE",
             "The supervising broker must hold a BROKER licence.")
    if bootstrap:
        return
    if supervisor["license_status"] != "ACTIVE":
        fail("ERR_SUPERVISING_BROKER_INELIGIBLE",
             "The supervising broker must be ACTIVE.")
    if supervisor.get("sponsoring_brokerage_id") != brokerage["id"]:
        fail("ERR_SUPERVISING_BROKER_INELIGIBLE",
             "The supervising broker must be sponsored by the same brokerage.")


@bp.post("/commission/licensees/<lid>/affiliations")
def create_affiliation(lid):
    guard(["LicensingAnalyst"])
    data = shape.body()
    brokerage_id = shape.req_id(data, "brokerage_id")
    supervising_broker_id = shape.req_id(data, "supervising_broker_id")
    expected_version = shape.req_int(data, "expected_brokerage_version")

    licensee = computed.must("licensee", lid)
    brokerage = computed.must("brokerage", brokerage_id)
    supervisor = computed.must("licensee", supervising_broker_id)

    status = licensee["license_status"]
    if status not in ("EXAM_PASSED", "ACTIVE"):
        fail("ERR_INVALID_STATE",
             "Only an EXAM_PASSED or ACTIVE licensee may be affiliated.")
    transfer = status == "ACTIVE"
    if transfer and licensee.get("sponsoring_brokerage_id") == brokerage["id"]:
        fail("ERR_INVALID_STATE",
             "The licensee is already affiliated with that brokerage.")
    if brokerage["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "The receiving brokerage is not ACTIVE.")

    if brokerage["version"] != expected_version:
        fail("ERR_BROKERAGE_VERSION_CONFLICT",
             "Brokerage version is %d." % brokerage["version"])

    posture = computed.supervision_posture(brokerage)
    if posture in ("RESTRICTED", "FROZEN"):
        fail("ERR_BROKERAGE_POSTURE_BLOCKED",
             "The receiving brokerage posture is %s." % posture)
    if transfer and licensee["discipline_status"] in ("PENDING_HEARING", "SANCTIONED"):
        fail("ERR_DISCIPLINE_HOLD",
             "Discipline status %s blocks a transfer." % licensee["discipline_status"])

    bootstrap = (supervising_broker_id == licensee["id"]
                 and brokerage.get("designated_broker_id") == licensee["id"])
    _check_supervising_broker(supervisor, brokerage, bootstrap)

    if computed.affiliated_licensee_count(brokerage["id"]) >= computed.SUPERVISION_RATIO_MAX:
        fail("ERR_SUPERVISION_RATIO_EXCEEDED",
             "The brokerage already sponsors %d active licensees."
             % computed.SUPERVISION_RATIO_MAX)
    if transfer and computed.ce_deficient(licensee):
        fail("ERR_CE_HOURS_INSUFFICIENT",
             "Continuing-education hours are insufficient for a transfer.")

    # PRD 3.3: "The receiving firm's `version` advances by one, and
    # `affiliated_licensee_count` and `supervision_posture` are recomputed on
    # **both** the firm being left and the firm being joined" — only the
    # receiving firm's row moves; the departed firm's two figures are derived
    # on read, so nothing is written to it.
    snap = cascades.posture_snapshot(brokerage["id"])
    moment = store.now()
    licensee["sponsoring_brokerage_id"] = brokerage["id"]
    licensee["supervising_broker_id"] = supervising_broker_id
    if not transfer:
        licensee["license_status"] = "ACTIVE"
        licensee["license_issued_at"] = store.fmt_dt(moment)
        licensee["license_expires_at"] = store.fmt_dt(
            moment + timedelta(seconds=computed.LICENSE_TERM_DAYS * 86400))
        licensee["ce_period_start_on"] = store.fmt_date(moment.date())
    else:
        cascades.revoke_team_names(licensee["id"])
    store.touch(licensee)
    cascades.settle(snap)
    return envelope.ok(serialize.licensee(licensee))


@bp.post("/commission/licensees/<lid>/status-changes")
def change_status(lid):
    user_id, role = guard(["Salesperson", "Broker", "LicensingAnalyst"])
    data = shape.body()
    action = shape.req_enum(data, "action", {"GO_INACTIVE", "REACTIVATE"})
    brokerage_id = None
    supervising_broker_id = None
    fee_paid = None
    if action == "REACTIVATE":
        brokerage_id = shape.req_id(data, "brokerage_id")
        supervising_broker_id = shape.req_id(data, "supervising_broker_id")
        fee_paid = shape.req_int(data, "reinstatement_fee_paid_cents", minimum=0)

    licensee = computed.must("licensee", lid)
    brokerage = computed.must("brokerage", brokerage_id) if brokerage_id else None
    supervisor = (computed.must("licensee", supervising_broker_id)
                  if supervising_broker_id else None)

    if role in ("Salesperson", "Broker") and user_id != licensee["id"]:
        fail("ERR_NOT_RESOURCE_OWNER",
             "A licensee may only change their own standing.")

    if action == "GO_INACTIVE":
        return _go_inactive(licensee)
    return _reactivate(licensee, brokerage, supervisor, fee_paid)


def _go_inactive(licensee):
    if licensee["license_status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE licence may be parked.")
    if licensee["person_type"] == "BROKER":
        for firm in computed.rows_where("brokerage", designated_broker_id=licensee["id"]):
            if firm["status"] == "ACTIVE":
                fail("ERR_INVALID_STATE",
                     "The designated broker of an ACTIVE brokerage may not go inactive.")
    if licensee["discipline_status"] == "PENDING_HEARING":
        fail("ERR_DISCIPLINE_HOLD", "A pending hearing blocks going inactive.")

    prior_brokerage_id = licensee.get("sponsoring_brokerage_id")
    snap = cascades.posture_snapshot(prior_brokerage_id)
    licensee["license_status"] = "INACTIVE"
    licensee["inactive_since"] = store.fmt_dt(store.now())
    licensee["sponsoring_brokerage_id"] = None
    licensee["supervising_broker_id"] = None
    store.touch(licensee)
    cascades.revoke_team_names(licensee["id"])
    for other in store.all_rows("licensee"):
        if other["id"] == licensee["id"]:
            continue
        if other.get("supervising_broker_id") != licensee["id"]:
            continue
        home = store.get("brokerage", other.get("sponsoring_brokerage_id")) \
            or store.get("brokerage", prior_brokerage_id)
        other["supervising_broker_id"] = home.get("designated_broker_id") if home else None
        store.touch(other)
    cascades.settle(snap)
    return envelope.ok(serialize.licensee(licensee))


def _reactivate(licensee, brokerage, supervisor, fee_paid):
    if licensee["license_status"] not in ("INACTIVE", "EXPIRED"):
        fail("ERR_INVALID_STATE",
             "Only an INACTIVE or EXPIRED licence may be reactivated.")
    if brokerage["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "The receiving brokerage is not ACTIVE.")

    posture = computed.supervision_posture(brokerage)
    if posture in ("RESTRICTED", "FROZEN"):
        fail("ERR_BROKERAGE_POSTURE_BLOCKED",
             "The receiving brokerage posture is %s." % posture)

    bootstrap = (supervisor["id"] == licensee["id"]
                 and brokerage.get("designated_broker_id") == licensee["id"])
    _check_supervising_broker(supervisor, brokerage, bootstrap)

    if computed.affiliated_licensee_count(brokerage["id"]) >= computed.SUPERVISION_RATIO_MAX:
        fail("ERR_SUPERVISION_RATIO_EXCEEDED",
             "The brokerage already sponsors %d active licensees."
             % computed.SUPERVISION_RATIO_MAX)
    if computed.ce_deficient(licensee):
        fail("ERR_CE_HOURS_INSUFFICIENT",
             "Continuing-education hours are insufficient for reinstatement.")
    expected_fee = computed.reinstatement_fee_cents(licensee)
    if fee_paid != expected_fee:
        fail("ERR_REINSTATEMENT_FEE_MISMATCH",
             "The reinstatement fee is %d cents." % expected_fee)

    snap = cascades.posture_snapshot(brokerage["id"])
    moment = store.now()
    licensee["license_status"] = "ACTIVE"
    licensee["sponsoring_brokerage_id"] = brokerage["id"]
    licensee["supervising_broker_id"] = supervisor["id"]
    licensee["inactive_since"] = None
    licensee["license_expires_at"] = store.fmt_dt(
        moment + timedelta(seconds=computed.LICENSE_TERM_DAYS * 86400))
    licensee["ce_period_start_on"] = store.fmt_date(moment.date())
    store.touch(licensee)
    cascades.settle(snap)
    return envelope.ok(serialize.licensee(licensee))


# ----------------------------------------------------------------- brokerages
def _check_designated_broker(broker, allowed_statuses):
    if broker["person_type"] != "BROKER" or broker["license_status"] not in allowed_statuses:
        fail("ERR_DESIGNATED_BROKER_NOT_BROKER",
             "The designated broker must be a BROKER in %s."
             % " or ".join(sorted(allowed_statuses)))


@bp.post("/commission/brokerages")
def create_brokerage():
    guard(["LicensingAnalyst"])
    data = shape.body()
    name = shape.req_str(data, "name")
    designated_broker_id = shape.req_id(data, "designated_broker_id")
    trust_account_required = shape.opt_bool(data, "trust_account_required", True)
    retention = shape.opt_int(data, "record_retention_years", 5, minimum=3, maximum=10)

    broker = computed.must("licensee", designated_broker_id)
    _check_designated_broker(broker, ("EXAM_PASSED", "ACTIVE"))

    row = store.insert("brokerage", {
        "name": name,
        "designated_broker_id": designated_broker_id,
        "status": "PENDING",
        "trust_account_required": trust_account_required,
        "record_retention_years": retention,
    })
    return envelope.created(serialize.brokerage(row))


@bp.post("/commission/brokerages/<bid>/activation")
def activate_brokerage(bid):
    guard(["LicensingAnalyst"])
    shape.body()
    brokerage = computed.must("brokerage", bid)
    status = brokerage["status"]
    if status not in ("PENDING", "SUSPENDED"):
        fail("ERR_INVALID_STATE", "A %s brokerage may not be activated." % status)
    if status == "SUSPENDED" and computed.open_shortage_cents(brokerage["id"]) != 0:
        fail("ERR_INVALID_STATE",
             "An outstanding trust shortage blocks re-activation.")

    broker = store.get("licensee", brokerage.get("designated_broker_id"))
    if broker is None:
        fail("ERR_DESIGNATED_BROKER_NOT_BROKER", "The designated broker is missing.")
    if status == "PENDING":
        if not (broker["person_type"] == "BROKER"
                and broker["license_status"] in ("ACTIVE", "EXAM_PASSED")):
            fail("ERR_DESIGNATED_BROKER_NOT_BROKER",
                 "The designated broker must be an ACTIVE or EXAM_PASSED BROKER.")
    else:
        _check_designated_broker(broker, ("ACTIVE",))

    if status == "PENDING" and brokerage["trust_account_required"]:
        has_escrow = any(a["account_type"] == "ESCROW" and a["status"] == "OPEN"
                         for a in computed.rows_where("trust_account",
                                                      brokerage_id=brokerage["id"]))
        if not has_escrow:
            fail("ERR_TRUST_ACCOUNT_REQUIRED",
                 "An OPEN ESCROW trust account is required before activation.")

    snap = cascades.posture_snapshot(brokerage["id"])
    brokerage["status"] = "ACTIVE"
    store.touch(brokerage)
    cascades.settle(snap)
    return envelope.ok(serialize.brokerage(brokerage))


@bp.post("/commission/brokerages/<bid>/trust-accounts")
def open_trust_account(bid):
    guard(["LicensingAnalyst", "Broker"])
    data = shape.body()
    bank_name = shape.req_str(data, "bank_name")
    account_type = shape.req_enum(data, "account_type", computed.ACCOUNT_TYPES)
    brokerage = computed.must("brokerage", bid)
    row = store.insert("trust_account", {
        "brokerage_id": brokerage["id"],
        "bank_name": bank_name,
        "account_type": account_type,
        "status": "OPEN",
        "last_audited_at": None,
    })
    return envelope.created(serialize.trust_account(row))

"""Clock, club members, boats, certificates, regattas and race documents."""
from flask import Blueprint

import calc
import services
import store
from errors import fail
from pipeline import Ctx, F, list_read, must, no_body, ok, ok_row, validate
from util import fmt_dt, parse_dt

bp = Blueprint("core", __name__)

ALL_ROLES = ["ClubAdmin", "RegattaChair", "Measurer", "RaceOfficer", "JuryChair", "Competitor"]


# --------------------------------------------------------------------------
# the logical clock
# --------------------------------------------------------------------------


@bp.post("/regatta-ops/_clock/set_current_utc")
def clock_set():
    ctx = Ctx(["ClubAdmin"])
    data = validate(ctx, [F("to_iso8601", "datetime")])
    store.set_clock(parse_dt(data["to_iso8601"]))
    return ok({"current_utc": fmt_dt(store.now())})


# --------------------------------------------------------------------------
# ClubMember
# --------------------------------------------------------------------------

CERT_LEVELS = ("NONE", "CLUB", "REGIONAL", "NATIONAL", "INTERNATIONAL")


@bp.post("/regatta-ops/club-members")
def member_create():
    # member enrolment is the one endpoint exempt from the actor-resolution step
    ctx = Ctx(["ClubAdmin"], actor_exempt=True)
    data = validate(
        ctx,
        [
            F("full_name", "string", nonblank=True),
            F("email", "string", contains="@", nonblank=True),
            F("measurer_license_id", "string", required=False),
            F("judge_certification_level", "enum", required=False, default="NONE", enum=CERT_LEVELS),
            F("safety_course_expiry_utc", "datetime", required=False),
        ],
    )
    email = data["email"].strip().lower()
    for other in store.rows("club_members"):
        if other["email"].strip().lower() == email:
            fail("ERR_DUPLICATE_RECORD", "email is already enrolled")
    row = store.insert(
        "club_members",
        {
            "full_name": data["full_name"],
            "email": data["email"],
            "measurer_license_id": data["measurer_license_id"],
            "judge_certification_level": data["judge_certification_level"],
            "safety_course_expiry_utc": data["safety_course_expiry_utc"],
            "assigned_duty_minutes": 0,
        },
    )
    return ok_row(row, 201)


@bp.patch("/regatta-ops/club-members/<rid>")
def member_patch(rid):
    ctx = Ctx(["ClubAdmin"])
    data = validate(
        ctx,
        [
            F("measurer_license_id", "string", required=False),
            F("judge_certification_level", "enum", required=False, enum=CERT_LEVELS),
            F("safety_course_expiry_utc", "datetime", required=False),
        ],
    )
    member = must("club_members", rid)
    changes = {}
    for field in ("measurer_license_id", "safety_course_expiry_utc"):
        if ctx.has(field):
            changes[field] = data[field]
    if ctx.has("judge_certification_level") and data["judge_certification_level"] is not None:
        changes["judge_certification_level"] = data["judge_certification_level"]
    if changes:
        for key, value in changes.items():
            member[key] = value
        store.touch(member)
    return ok_row(member)


@bp.get("/regatta-ops/club-members/<rid>")
def member_read(rid):
    Ctx(ALL_ROLES)
    return ok_row(must("club_members", rid))


@bp.get("/regatta-ops/club-members")
def member_list():
    Ctx(["ClubAdmin", "RegattaChair", "JuryChair"])
    return list_read("club_members", ["judge_certification_level"])


# --------------------------------------------------------------------------
# Boat
# --------------------------------------------------------------------------

BOAT_TYPES = ("MONOHULL", "MULTIHULL", "KEELBOAT_SPORT")


@bp.post("/regatta-ops/boats")
def boat_create():
    ctx = Ctx(["ClubAdmin", "Competitor"])
    # step 5: a Competitor registers only its own boat
    if ctx.role == "Competitor":
        owner = ctx.raw_value("owner_member_id")
        if isinstance(owner, str) and owner != ctx.user_id:
            fail("ERR_NOT_ACTING_PARTY", "a competitor registers only its own boat")
    data = validate(
        ctx,
        [
            F("sail_number", "string", min_len=3, max_len=12, nonblank=True),
            F("boat_name", "string", nonblank=True),
            F("owner_member_id", "string"),
            F("boat_type", "enum", enum=BOAT_TYPES),
            F("loa_meters", "number", gt=0, le=40),
        ],
    )
    must("club_members", data["owner_member_id"])
    sail = data["sail_number"].strip().lower()
    for other in store.rows("boats"):
        if other["sail_number"].strip().lower() == sail:
            fail("ERR_DUPLICATE_RECORD", "sail_number is already registered")
    row = store.insert(
        "boats",
        {
            "sail_number": data["sail_number"],
            "boat_name": data["boat_name"],
            "owner_member_id": data["owner_member_id"],
            "boat_type": data["boat_type"],
            "loa_meters": data["loa_meters"],
        },
    )
    return ok_row(row, 201)


@bp.get("/regatta-ops/boats/<rid>")
def boat_read(rid):
    Ctx(["ClubAdmin", "RegattaChair", "Measurer", "RaceOfficer", "Competitor"])
    return ok_row(must("boats", rid))


@bp.get("/regatta-ops/boats")
def boat_list():
    Ctx(["ClubAdmin", "RegattaChair", "Measurer", "RaceOfficer", "Competitor"])
    return list_read("boats", ["owner_member_id", "boat_type"])


# --------------------------------------------------------------------------
# RatingCertificate
# --------------------------------------------------------------------------

RULE_CODES = ("TOD_PHRF", "TOT_ORC")

MEASUREMENT_RANGES = (
    ("sail_area_m2", 400.0),
    ("hull_length_m", 40.0),
    ("displacement_kg", 100000.0),
    ("draft_m", 6.0),
)


@bp.post("/regatta-ops/rating-certificates")
def cert_create():
    ctx = Ctx(["Measurer"])
    ctx.require_license()
    data = validate(
        ctx,
        [
            F("boat_id", "string"),
            F("rule_code", "enum", enum=RULE_CODES),
            F("sail_area_m2", "number", defer=True),
            F("hull_length_m", "number", defer=True),
            F("displacement_kg", "number", defer=True),
            F("draft_m", "number", defer=True),
            F("valid_from", "datetime"),
            F("valid_until", "datetime"),
            F("expected_boat_version", "integer"),
        ],
    )
    boat = must("boats", data["boat_id"])
    # step 9
    if int(data["expected_boat_version"]) != int(boat["version"]):
        fail("ERR_STALE_BOAT_VERSION", "expected_boat_version does not match the boat")
    # step 48
    for field, upper in MEASUREMENT_RANGES:
        value = float(data[field])
        if not (value > 0 and value <= upper):
            fail("ERR_MEASUREMENT_OUT_OF_RANGE", "%s is outside its declared range" % field)
    if not parse_dt(data["valid_until"]) > parse_dt(data["valid_from"]):
        fail("ERR_MEASUREMENT_OUT_OF_RANGE", "valid_until must be strictly after valid_from")
    raw, rating, band = calc.certificate_rating_value(
        data["rule_code"],
        data["sail_area_m2"],
        data["hull_length_m"],
        data["displacement_kg"],
        data["draft_m"],
        boat["boat_type"],
    )
    row = store.insert(
        "rating_certificates",
        {
            "boat_id": boat["id"],
            "rule_code": data["rule_code"],
            "sail_area_m2": data["sail_area_m2"],
            "hull_length_m": data["hull_length_m"],
            "displacement_kg": data["displacement_kg"],
            "draft_m": data["draft_m"],
            "measured_by_member_id": ctx.user_id,
            "raw_speed_index": raw,
            "rating_value": rating,
            "band_key_spm": band,
            "valid_from": data["valid_from"],
            "valid_until": data["valid_until"],
            "status": "DRAFT",
            "suspension_reason_code": None,
            "supersedes_certificate_id": None,
        },
    )
    store.touch(boat)
    return ok_row(row, 201)


def _clock_inside(cert):
    now = store.now()
    return store.D(cert, "valid_from") <= now <= store.D(cert, "valid_until")


@bp.post("/regatta-ops/rating-certificates/<rid>/issue")
def cert_issue(rid):
    ctx = Ctx(["Measurer"])
    ctx.require_license()
    no_body(ctx)
    cert = must("rating_certificates", rid)
    if cert["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "only a DRAFT certificate may be issued")
    if cert["measured_by_member_id"] != ctx.user_id:
        fail("ERR_NOT_ACTING_PARTY", "only the filing measurer may issue this certificate")
    if not _clock_inside(cert):
        fail("ERR_CERTIFICATE_EXPIRED", "the clock is outside the certificate validity window")
    superseded = None
    for other in store.find("rating_certificates", boat_id=cert["boat_id"], status="ISSUED"):
        if other["id"] != cert["id"]:
            superseded = other
            break
    store.apply_changes(cert, {"status": "ISSUED"})
    if superseded is not None:
        # hop 2: the displaced certificate becomes terminal, entries stay pinned to it
        store.apply_changes(superseded, {"status": "SUPERSEDED"})
        store.apply_changes(cert, {"supersedes_certificate_id": superseded["id"]})
    store.touch(store.get("boats", cert["boat_id"]))
    return ok_row(cert)


def _pinned_entries(cert, statuses):
    return [
        e
        for e in store.find("entries", certificate_id=cert["id"])
        if e.get("registration_status") in statuses
    ]


@bp.post("/regatta-ops/rating-certificates/<rid>/suspend")
def cert_suspend(rid):
    ctx = Ctx(["Measurer"])
    ctx.require_license()
    data = validate(ctx, [F("suspension_reason_code", "string", nonblank=True)])
    cert = must("rating_certificates", rid)
    if cert["status"] != "ISSUED":
        fail("ERR_INVALID_STATE", "only an ISSUED certificate may be suspended")
    # hop 1
    store.apply_changes(
        cert, {"status": "SUSPENDED", "suspension_reason_code": data["suspension_reason_code"]}
    )
    # hop 2: no edge leads from SUBMITTED into RATING_INVALID, so only ACCEPTED moves
    touched = _pinned_entries(cert, ("ACCEPTED",))
    for entry in touched:
        store.apply_changes(entry, {"registration_status": "RATING_INVALID"})
    # hops 3 and 4
    _refresh_entry_divisions(touched)
    store.touch(store.get("boats", cert["boat_id"]))
    return ok_row(cert)


def _refresh_entry_divisions(entries):
    seen = set()
    for entry in entries:
        division = store.get("divisions", entry.get("division_id"))
        if division is None or division["id"] in seen:
            continue
        seen.add(division["id"])
        services.refresh_division(division)


@bp.post("/regatta-ops/rating-certificates/<rid>/reinstate")
def cert_reinstate(rid):
    ctx = Ctx(["Measurer"])
    ctx.require_license()
    no_body(ctx)
    cert = must("rating_certificates", rid)
    if cert["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE", "only a SUSPENDED certificate may be reinstated")
    if not _clock_inside(cert):
        fail("ERR_CERTIFICATE_EXPIRED", "the clock is outside the certificate validity window")
    # hop 1
    store.apply_changes(cert, {"status": "ISSUED", "suspension_reason_code": None})
    # hop 2: deliberately back to SUBMITTED, so the chair must admit each entry again
    touched = _pinned_entries(cert, ("RATING_INVALID",))
    for entry in touched:
        store.apply_changes(entry, {"registration_status": "SUBMITTED"})
    # hop 3: counts only; a division that regains its floor is NOT auto-confirmed
    _refresh_entry_divisions(touched)
    for regatta in _regattas_of(touched):
        services.clear_blocked_races(regatta)
    store.touch(store.get("boats", cert["boat_id"]))
    return ok_row(cert)


def _regattas_of(entries):
    out = []
    seen = set()
    for entry in entries:
        regatta = store.get("regattas", entry.get("regatta_id"))
        if regatta is not None and regatta["id"] not in seen:
            seen.add(regatta["id"])
            out.append(regatta)
    return out


@bp.get("/regatta-ops/rating-certificates/<rid>")
def cert_read(rid):
    Ctx(ALL_ROLES)
    return ok_row(must("rating_certificates", rid))


@bp.get("/regatta-ops/rating-certificates")
def cert_list():
    Ctx(ALL_ROLES)
    return list_read(
        "rating_certificates",
        ["boat_id", "measured_by_member_id", "supersedes_certificate_id", "status", "rule_code"],
    )


# --------------------------------------------------------------------------
# Regatta
# --------------------------------------------------------------------------


@bp.post("/regatta-ops/regattas")
def regatta_create():
    ctx = Ctx(["ClubAdmin", "RegattaChair"])
    data = validate(
        ctx,
        [
            F("name", "string", min_len=1, max_len=120, nonblank=True),
            F("host_club_name", "string", nonblank=True),
            F("scoring_system", "enum", enum=("LOW_POINT", "BONUS_POINT")),
            F(
                "discard_policy",
                "enum",
                required=False,
                default="NONE",
                enum=("NONE", "ONE_PER_FIVE", "ONE_PER_FOUR"),
            ),
            F(
                "handicap_basis",
                "enum",
                required=False,
                default="PER_CERTIFICATE",
                enum=("PER_CERTIFICATE", "UNIFIED_TOD"),
            ),
            F("planned_race_count", "integer", ge=1, le=20),
            F("fleet_minimum", "integer", required=False, default=3, ge=2, le=20),
            F("protest_time_limit_minutes", "integer", required=False, default=90, ge=15, le=480),
            F("jury_quorum_required", "integer", required=False, default=3, ge=2, le=7),
            F("safety_category", "enum", enum=("CAT_4", "CAT_3", "CAT_2")),
            F("series_start_utc", "datetime"),
        ],
    )
    row = store.insert(
        "regattas",
        {
            "name": data["name"],
            "host_club_name": data["host_club_name"],
            "scoring_system": data["scoring_system"],
            "discard_policy": data["discard_policy"],
            "handicap_basis": data["handicap_basis"],
            "planned_race_count": data["planned_race_count"],
            "fleet_minimum": data["fleet_minimum"],
            "protest_time_limit_minutes": data["protest_time_limit_minutes"],
            "jury_quorum_required": data["jury_quorum_required"],
            "safety_category": data["safety_category"],
            "series_start_utc": data["series_start_utc"],
            "status": "DRAFT",
            "nor_revision": 0,
            "si_revision": 0,
            "confirmed_division_count": 0,
            "final_race_count": 0,
        },
    )
    return ok_row(row, 201)


@bp.post("/regatta-ops/regattas/<rid>/open-racing")
def regatta_open_racing(rid):
    ctx = Ctx(["RegattaChair"])
    no_body(ctx)
    regatta = must("regattas", rid)
    if regatta["status"] != "SI_PUBLISHED":
        fail("ERR_INVALID_STATE", "racing opens only from SI_PUBLISHED")
    if int(regatta["si_revision"]) < 1:
        fail("ERR_INVALID_STATE", "the sailing instructions have not been published")
    if int(regatta["confirmed_division_count"]) < 1:
        fail("ERR_INVALID_STATE", "no division of the regatta is CONFIRMED")
    if services.provisional_with_entries_exists(regatta):
        fail("ERR_INVALID_STATE", "a PROVISIONAL division still holds assigned entries")
    seated = [p for p in store.find("jury_panels", regatta_id=regatta["id"]) if p["status"] == "SEATED"]
    if not seated:
        fail("ERR_INVALID_STATE", "no jury panel of the regatta has reached SEATED")
    store.apply_changes(regatta, {"status": "RACING"})
    return ok_row(regatta)


@bp.get("/regatta-ops/regattas/<rid>")
def regatta_read(rid):
    Ctx(ALL_ROLES)
    return ok_row(must("regattas", rid))


@bp.get("/regatta-ops/regattas")
def regatta_list():
    Ctx(ALL_ROLES)
    return list_read("regattas", ["status"])


# --------------------------------------------------------------------------
# RaceDocument
# --------------------------------------------------------------------------


def _published_doc(regatta_id, doc_type):
    for doc in store.find(
        "race_documents", regatta_id=regatta_id, doc_type=doc_type, status="PUBLISHED"
    ):
        return doc
    return None


@bp.post("/regatta-ops/race-documents")
def document_create():
    ctx = Ctx(["RegattaChair"])
    data = validate(
        ctx,
        [
            F("regatta_id", "string"),
            F("doc_type", "enum", enum=("NOR", "SI")),
            F("body_summary", "string", nonblank=True),
            F("effective_utc", "datetime"),
            F("amends_document_id", "string", required=False),
            F("expected_regatta_version", "integer"),
        ],
    )
    # step 8: path ids first (there are none), then body FKs in declaration order
    regatta = must("regattas", data["regatta_id"])
    amended = None
    if data["amends_document_id"] is not None:
        amended = must("race_documents", data["amends_document_id"])
    # step 10
    if int(data["expected_regatta_version"]) != int(regatta["version"]):
        fail("ERR_STALE_REGATTA_VERSION", "expected_regatta_version does not match the regatta")
    doc_type = data["doc_type"]
    current = _published_doc(regatta["id"], doc_type)
    # step 11: the first sailing instructions need a notice of race first
    if doc_type == "SI" and current is None and int(regatta["nor_revision"]) < 1:
        fail("ERR_INVALID_STATE", "the notice of race must be published before the SI")
    # step 24
    if amended is None:
        if current is not None:
            fail(
                "ERR_AMENDMENT_TARGET_INVALID",
                "a published %s already exists, so amends_document_id is required" % doc_type,
            )
    else:
        if (
            amended["regatta_id"] != regatta["id"]
            or amended["doc_type"] != doc_type
            or amended["status"] != "PUBLISHED"
        ):
            fail("ERR_AMENDMENT_TARGET_INVALID", "amends_document_id is not the current revision")
        if current is None:
            fail("ERR_AMENDMENT_TARGET_INVALID", "no published %s exists to amend" % doc_type)
    # step 47
    if amended is not None:
        if not parse_dt(data["effective_utc"]) > parse_dt(amended["effective_utc"]):
            fail("ERR_AMENDMENT_NOT_LATER", "effective_utc must be later than the amended revision")
    revision = 1 if amended is None else int(amended["revision"]) + 1
    row = store.insert(
        "race_documents",
        {
            "regatta_id": regatta["id"],
            "doc_type": doc_type,
            "revision": revision,
            "body_summary": data["body_summary"],
            "effective_utc": data["effective_utc"],
            "amends_document_id": None if amended is None else amended["id"],
            "status": "PUBLISHED",
        },
    )
    if amended is not None:
        store.apply_changes(amended, {"status": "SUPERSEDED"})
    changes = {"nor_revision" if doc_type == "NOR" else "si_revision": revision}
    if doc_type == "NOR" and regatta["status"] == "DRAFT":
        changes["status"] = "NOR_PUBLISHED"
    elif doc_type == "SI" and regatta["status"] == "NOR_PUBLISHED":
        changes["status"] = "SI_PUBLISHED"
    # one mutation of the regatta row, so version advances by exactly 1
    for key, value in changes.items():
        regatta[key] = value
    store.touch(regatta)
    return ok_row(row, 201)


@bp.get("/regatta-ops/race-documents/<rid>")
def document_read(rid):
    Ctx(ALL_ROLES)
    return ok_row(must("race_documents", rid))


@bp.get("/regatta-ops/race-documents")
def document_list():
    Ctx(ALL_ROLES)
    return list_read("race_documents", ["regatta_id", "amends_document_id", "doc_type", "status"])

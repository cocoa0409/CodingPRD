"""Licence applications and credentials."""
from flask import Blueprint

import calc
import domain
import guards as G
import store
from envelope import created, listing, mark_new, ok, touch
from errors import fail
from timeutil import add_months, parse_dt

bp = Blueprint("licensing", __name__)

PATHWAYS = ("EXAMINATION", "ENDORSEMENT")
CREDENTIAL_TYPES = ("RN", "LPN", "APRN", "NURSE_AIDE")
APRN_ROLES = ("NP", "CRNA", "CNS", "CNM")
NCLEX_RESULTS = ("PASS", "FAIL", "NOT_TAKEN")
BOARD_DECISIONS = ("APPROVED_UNCONDITIONAL", "APPROVED_WITH_MONITORING", "DENIED")
LICENSE_STATUSES = ("ACTIVE", "INACTIVE", "EXPIRED", "LAPSED", "SURRENDERED")
PRIVILEGE_VARIANTS = ("RESIDENCY_DECLARED", "RESIDENCY_EVIDENCED")


# ---------------------------------------------------------------------------
# LicenseApplication
# ---------------------------------------------------------------------------
@bp.post("/license-applications")
def create_application():
    user_id, role = G.auth("Applicant", "LicensureAnalyst")
    b = G.body()
    nurse = G.find_opt("nurse", b.get("nurse_id"))
    board = G.find_opt("board", b.get("board_config_id"))
    program = G.find_opt("program", b.get("education_program_id"))
    base_license = G.find_opt("license", b.get("base_license_id"))

    if nurse is None:
        G.req_string(b, "nurse_id")
    G.own_nurse(role, user_id, nurse["id"])
    if board is None:
        G.req_string(b, "board_config_id")

    pathway = G.req_enum(b, "pathway", PATHWAYS)
    credential_type = G.req_enum(b, "credential_type", CREDENTIAL_TYPES)
    aprn_role = G.opt_enum(b, "aprn_role", APRN_ROLES)
    nclex_result = G.opt_enum(b, "nclex_result", NCLEX_RESULTS, "NOT_TAKEN")
    prior_state = G.opt_string(b, "prior_license_state")
    if prior_state is not None:
        G.state_code(prior_state, "prior_license_state")
    prior_number = G.opt_string(b, "prior_license_number")
    if credential_type == "APRN" and aprn_role is None:
        fail("ERR_INVALID_REQUEST", "aprn_role is required when credential_type is APRN.")

    if board["status"] == "ARCHIVED":
        fail("ERR_INVALID_STATE", "The board configuration is ARCHIVED.")

    rec = store.base_fields()
    rec.update({
        "nurse_id": nurse["id"],
        "board_config_id": board["id"],
        "education_program_id": program["id"] if program else None,
        "pathway": pathway,
        "credential_type": credential_type,
        "aprn_role": aprn_role,
        "nclex_result": nclex_result,
        "prior_license_state": prior_state,
        "prior_license_number": prior_number,
        "prior_license_verified": G.opt_bool(b, "prior_license_verified", False),
        "base_license_id": base_license["id"] if base_license else None,
        "status": "DRAFT",
        "deficiency_cycle_count": 0,
        "screening_status": "NOT_ORDERED",
        "screening_offense_records": [],
        "board_decision": "NONE",
        "submitted_at": None,
        "decided_at": None,
    })
    store.STORE.applications[rec["id"]] = rec
    mark_new(rec)
    return created(rec)


@bp.get("/license-applications")
def list_applications():
    G.auth("SystemAdmin", "LicensureAnalyst", "Investigator", "BoardMember")
    limit, offset = G.pagination()
    rows = G.filter_rows(store.STORE.applications.values(), {
        "nurse_id": "nurse_id",
        "board_config_id": "board_config_id",
        "education_program_id": "education_program_id",
        "base_license_id": "base_license_id",
        "pathway": "pathway",
        "credential_type": "credential_type",
        "status": "status",
    })
    page, total = G.paginate(rows, limit, offset)
    return listing(page, limit, offset, total)


@bp.get("/license-applications/<aid>")
def get_application(aid):
    user_id, role = G.auth("SystemAdmin", "LicensureAnalyst", "Investigator", "BoardMember", "Applicant")
    app = G.find("application", aid)
    G.own_nurse(role, user_id, app["nurse_id"])
    return ok(app)


def _base_license_ok(app):
    base = store.STORE.licenses.get(app.get("base_license_id")) if app.get("base_license_id") else None
    if base is None:
        return False
    return (base["credential_type"] in ("RN", "LPN")
            and base["license_status"] == "ACTIVE"
            and base["encumbrance_status"] == "CLEAR"
            and base["nurse_id"] == app["nurse_id"])


@bp.post("/license-applications/<aid>/submit")
def submit_application(aid):
    user_id, role = G.auth("Applicant", "LicensureAnalyst")
    app = G.find("application", aid)
    G.own_nurse(role, user_id, app["nurse_id"])

    if app["status"] not in ("DRAFT", "DEFICIENT"):
        fail("ERR_INVALID_STATE")
    board = store.STORE.boards.get(app["board_config_id"])
    if board is None or board["status"] == "ARCHIVED":
        fail("ERR_INVALID_STATE", "The board configuration is ARCHIVED.")
    if app["pathway"] == "EXAMINATION" and not app.get("education_program_id"):
        fail("ERR_INVALID_STATE", "An examination-pathway application must carry an education_program_id.")
    if app["credential_type"] == "APRN" and not app.get("base_license_id"):
        fail("ERR_BASE_LICENSE_REQUIRED")
    if app["status"] == "DEFICIENT" and int(app["deficiency_cycle_count"]) >= 3:
        fail("ERR_DEFICIENCY_LIMIT_REACHED")

    app["status"] = "SUBMITTED"
    app["submitted_at"] = store.STORE.clock
    touch(app)
    return ok(app)


@bp.post("/license-applications/<aid>/deficiency")
def deficiency_application(aid):
    G.auth("LicensureAnalyst")
    app = G.find("application", aid)
    b = G.body()
    G.req_string(b, "reason_note")
    # PRD 3.2: once the count reaches 3 the application freezes in DEFICIENT and
    # "a further return and a resubmission are *both* refused with
    # ERR_DEFICIENCY_LIMIT_REACHED" -- the frozen state reports the budget, not
    # the generic state check.
    if app["status"] == "DEFICIENT" and int(app["deficiency_cycle_count"]) >= 3:
        fail("ERR_DEFICIENCY_LIMIT_REACHED")
    if app["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE")
    if int(app["deficiency_cycle_count"]) >= 3:
        fail("ERR_DEFICIENCY_LIMIT_REACHED")
    app["status"] = "DEFICIENT"
    app["deficiency_cycle_count"] = int(app["deficiency_cycle_count"]) + 1
    touch(app)
    return ok(app)


@bp.post("/license-applications/<aid>/qualification-verification")
def verify_application(aid):
    G.auth("LicensureAnalyst")
    app = G.find("application", aid)
    b = G.body()
    prior_verified = G.opt_bool(b, "prior_license_verified")

    if app["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE")

    if prior_verified is not None:
        app["prior_license_verified"] = prior_verified

    if app["pathway"] == "EXAMINATION":
        program = store.STORE.programs.get(app.get("education_program_id"))
        if program is None:
            fail("ERR_PROGRAM_NOT_APPROVED")
        if program["approval_status"] not in ("APPROVED", "PROVISIONAL", "PROBATION"):
            fail("ERR_PROGRAM_NOT_APPROVED")
        if not (program["approval_expires_on"] > store.STORE.clock):
            fail("ERR_PROGRAM_NOT_APPROVED")
        if app["nclex_result"] != "PASS":
            fail("ERR_NCLEX_NOT_PASSED")
    else:
        state = app.get("prior_license_state")
        if not app.get("prior_license_verified") or state is None or len(str(state)) != 2:
            fail("ERR_PRIOR_LICENSE_UNVERIFIED")

    if app["credential_type"] == "APRN" and not _base_license_ok(app):
        fail("ERR_BASE_LICENSE_REQUIRED")

    app["status"] = "SCREENING_IN_PROGRESS"
    app["screening_status"] = "REQUESTED"
    touch(app)

    if app["pathway"] == "ENDORSEMENT":
        domain.queue_report(
            app["nurse_id"], "LICENSE_APPLICATION", app["id"], "INTERSTATE_COMPACT",
            "ENDORSEMENT_VERIFICATION",
            "Interstate verification notice for endorsement application %s." % app["id"])
    return ok(app)


@bp.post("/license-applications/<aid>/screening-result")
def screening_result(aid):
    G.auth("LicensureAnalyst")
    app = G.find("application", aid)
    b = G.body()
    raw = G.req_obj_array(b, "screening_offense_records")
    records = []
    disposed_at = []
    for entry in raw:
        code = entry.get("offense_code")
        if not isinstance(code, str) or not code:
            fail("ERR_INVALID_REQUEST", "screening_offense_records.offense_code must be a string.")
        try:
            disposed = parse_dt(entry.get("disposition_date"))
        except Exception:
            fail("ERR_INVALID_REQUEST",
                 "screening_offense_records.disposition_date must be an ISO 8601 instant.")
        # The vendor's answer is echoed verbatim; only the comparison uses the
        # parsed instant.
        records.append({"offense_code": code,
                        "disposition_date": entry.get("disposition_date")})
        disposed_at.append(disposed)

    if app["status"] != "SCREENING_IN_PROGRESS":
        fail("ERR_INVALID_STATE")

    board = store.STORE.boards.get(app["board_config_id"])
    lookback_start = add_months(store.STORE.clock, -12 * int(board["criminal_lookback_years"]))
    codes = set(board.get("disqualifying_offense_codes") or [])
    disqualifying = any(
        r["offense_code"] in codes and d >= lookback_start
        for r, d in zip(records, disposed_at))

    app["screening_offense_records"] = records
    if disqualifying:
        app["screening_status"] = "DISQUALIFYING"
        app["status"] = "BOARD_REVIEW"
        touch(app)
        domain.queue_report(
            app["nurse_id"], "LICENSE_APPLICATION", app["id"], "NPDB", "SCREENING_FLAG",
            "Criminal-history screening flag on application %s." % app["id"])
    else:
        app["screening_status"] = "CLEARED"
        app["status"] = "APPROVED"
        app["board_decision"] = "APPROVED_UNCONDITIONAL"
        app["decided_at"] = store.STORE.clock
        touch(app)
    return ok(app)


@bp.post("/license-applications/<aid>/board-decision")
def board_decision(aid):
    G.auth("BoardMember")
    app = G.find("application", aid)
    b = G.body()
    decision = G.req_enum(b, "decision", BOARD_DECISIONS)

    if app["status"] != "BOARD_REVIEW":
        fail("ERR_INVALID_STATE")
    if decision == "APPROVED_UNCONDITIONAL" and app["screening_status"] == "DISQUALIFYING":
        fail("ERR_DISQUALIFYING_OFFENSE")

    app["board_decision"] = decision
    app["decided_at"] = store.STORE.clock
    app["status"] = "DENIED" if decision == "DENIED" else "APPROVED"
    touch(app)

    if decision == "DENIED":
        domain.queue_report(
            app["nurse_id"], "LICENSE_APPLICATION", app["id"], "INTERSTATE_COMPACT",
            "APPLICATION_DENIED", "Licence application %s denied by the board." % app["id"])
    return ok(app)


@bp.post("/license-applications/<aid>/withdrawal")
def withdraw_application(aid):
    user_id, role = G.auth("Applicant", "LicensureAnalyst")
    app = G.find("application", aid)
    G.own_nurse(role, user_id, app["nurse_id"])
    if app["status"] not in ("DRAFT", "SUBMITTED", "DEFICIENT"):
        fail("ERR_INVALID_STATE")
    app["status"] = "WITHDRAWN"
    app["decided_at"] = store.STORE.clock
    touch(app)
    return ok(app)


# ---------------------------------------------------------------------------
# License
# ---------------------------------------------------------------------------
@bp.post("/licenses")
def create_license():
    G.auth("LicensureAnalyst")
    b = G.body()
    app = G.find_opt("application", b.get("source_application_id"))
    if app is None:
        G.req_string(b, "source_application_id")

    if app["status"] != "APPROVED":
        fail("ERR_INVALID_STATE")

    st = store.STORE
    for existing in st.licenses.values():
        if existing.get("source_application_id") == app["id"]:
            fail("ERR_LICENSE_ALREADY_ISSUED")
    for existing in st.licenses.values():
        if (existing["nurse_id"] == app["nurse_id"]
                and existing["credential_type"] == app["credential_type"]
                and existing["issuing_board_config_id"] == app["board_config_id"]
                and existing["license_status"] not in ("LAPSED", "SURRENDERED")):
            fail("ERR_LICENSE_ALREADY_ISSUED")

    board = st.boards.get(app["board_config_id"])
    now = st.clock
    rec = store.base_fields()
    rec.update({
        "nurse_id": app["nurse_id"],
        "issuing_board_config_id": app["board_config_id"],
        "source_application_id": app["id"],
        "base_license_id": app.get("base_license_id"),
        "credential_type": app["credential_type"],
        "aprn_role": app.get("aprn_role"),
        "license_number": st.next_license_number(board["state_code"], app["credential_type"]),
        "license_status": "ACTIVE",
        "encumbrance_status": "CLEAR",
        "multistate_privilege_status": "NOT_ELIGIBLE",
        "privilege_variant": None,
        "privilege_basis_state": None,
        "practice_restriction_codes": [],
        "open_encumbrance_count": 0,
        "issued_on": now,
        "expires_on": add_months(now, int(board["renewal_period_months"])),
    })
    st.licenses[rec["id"]] = rec
    mark_new(rec)

    app["status"] = "ISSUED"
    app["decided_at"] = now
    touch(app)

    domain.run_privilege(rec, "RESIDENCY_DECLARED")

    if rec["credential_type"] == "NURSE_AIDE":
        domain.queue_report(rec["nurse_id"], "LICENSE", rec["id"], "NURSE_AIDE_REGISTRY",
                            "REGISTRY_ENTRY",
                            "Nurse aide registry entry %s." % rec["license_number"])
    nurse = st.nurses.get(rec["nurse_id"])
    if nurse is not None:
        domain.recompute_nurse_status(nurse)
    return created(rec)


@bp.get("/licenses")
def list_licenses():
    G.auth(*G.ALL_STAFF)
    limit, offset = G.pagination()
    rows = G.filter_rows(store.STORE.licenses.values(), {
        "nurse_id": "nurse_id",
        "issuing_board_config_id": "issuing_board_config_id",
        "source_application_id": "source_application_id",
        "base_license_id": "base_license_id",
        "credential_type": "credential_type",
        "license_status": "license_status",
        "encumbrance_status": "encumbrance_status",
        "multistate_privilege_status": "multistate_privilege_status",
    })
    page, total = G.paginate(rows, limit, offset)
    return listing(page, limit, offset, total)


@bp.get("/licenses/<lid>")
def get_license(lid):
    user_id, role = G.auth(*G.ROLES)
    lic = G.find("license", lid)
    G.own_nurse(role, user_id, lic["nurse_id"])
    return ok(lic)


@bp.post("/licenses/<lid>/status-change")
def license_status_change(lid):
    G.auth("LicensureAnalyst")
    lic = G.find("license", lid)
    b = G.body()
    to_status = G.req_enum(b, "to_status", LICENSE_STATUSES)

    if to_status == "INACTIVE":
        if lic["license_status"] != "ACTIVE" or \
                lic["encumbrance_status"] not in ("CLEAR", "INVESTIGATION_PENDING"):
            fail("ERR_INVALID_STATE")
        lic["license_status"] = "INACTIVE"
        touch(lic)
        domain.run_privilege(lic, "RESIDENCY_DECLARED")
    elif to_status == "ACTIVE":
        if lic["license_status"] != "INACTIVE" or lic["encumbrance_status"] == "REVOKED":
            fail("ERR_INVALID_STATE")
        lic["license_status"] = "ACTIVE"
        touch(lic)
        domain.run_privilege(lic, "RESIDENCY_DECLARED")
    elif to_status == "SURRENDERED":
        if lic["license_status"] not in ("ACTIVE", "INACTIVE", "EXPIRED"):
            fail("ERR_INVALID_STATE")
        lic["license_status"] = "SURRENDERED"
        lic["multistate_privilege_status"] = "NOT_ELIGIBLE"
        touch(lic)
        domain.queue_report(lic["nurse_id"], "LICENSE", lic["id"], "INTERSTATE_COMPACT",
                            "SURRENDER",
                            "Voluntary surrender of credential %s." % lic["license_number"])
    else:
        fail("ERR_INVALID_STATE", "%s is not a client-drivable registration transition." % to_status)

    nurse = store.STORE.nurses.get(lic["nurse_id"])
    if nurse is not None:
        domain.recompute_nurse_status(nurse)
    return ok(lic)


@bp.post("/licenses/<lid>/privilege-determination")
def privilege_determination(lid):
    G.auth("LicensureAnalyst")
    lic = G.find("license", lid)
    b = G.body()
    variant = G.req_enum(b, "variant", PRIVILEGE_VARIANTS)
    result = domain.run_privilege(lic, variant)
    if result == "MULTISTATE":
        domain.queue_report(lic["nurse_id"], "LICENSE", lic["id"], "INTERSTATE_COMPACT",
                            "PRIVILEGE_GRANT",
                            "Multistate privilege granted on credential %s." % lic["license_number"])
    return ok(lic)


@bp.get("/licenses/<lid>/privilege-summary")
def privilege_summary(lid):
    G.auth(*G.ALL_STAFF)
    lic = G.find("license", lid)
    board = domain.board_of_license(lic)
    nurse = domain.nurse_of_license(lic)
    return ok({
        "license_id": lic["id"],
        "credential_type": lic["credential_type"],
        "license_status": lic["license_status"],
        "encumbrance_status": lic["encumbrance_status"],
        "multistate_privilege_status": lic["multistate_privilege_status"],
        "privilege_variant": lic.get("privilege_variant"),
        "privilege_basis_state": lic.get("privilege_basis_state"),
        "board_state_code": board["state_code"] if board else None,
        "board_compact_member": board["compact_member"] if board else None,
        "declared_primary_state": nurse.get("declared_primary_state") if nurse else None,
        "evidenced_primary_state": calc.evidenced_primary_state(nurse, store.STORE.clock) if nurse else None,
    })


@bp.get("/licenses/<lid>/renewal-applications")
def list_license_renewals(lid):
    G.auth("SystemAdmin", "LicensureAnalyst", "Investigator", "BoardMember")
    lic = G.find("license", lid)
    limit, offset = G.pagination()
    rows = [r for r in store.STORE.renewals.values() if r["license_id"] == lic["id"]]
    rows = G.filter_rows(rows, {"renewal_status": "renewal_status", "audit_status": "audit_status"})
    page, total = G.paginate(rows, limit, offset)
    return listing(page, limit, offset, total)

"""Expansion applications (with the rating gate and staged branches) and the logical clock."""

from core import (
    ALL_ROLES,
    APPLICATION_TYPES,
    STORE,
    TRACT_INCOME_LEVELS,
    api_err,
    application_out,
    authenticate,
    branch_out,
    get_application_or_404,
    get_area_or_404,
    json_body,
    list_response,
    new_entity,
    ok,
    optional,
    parse_date_str,
    parse_datetime_str,
    require,
    touch,
    v_enum,
    v_str,
    app,
)

EXECUTIVE_ROLES = ("BankExecutive",)
EXAMINER_ROLES = ("BankExaminer",)
ADMIN_ROLES = ("PlatformAdmin",)


@app.route("/cra/expansion-applications", methods=["POST"])
def create_application():
    authenticate(EXECUTIVE_ROLES)
    b = json_body()
    app_type = v_enum(require(b, "application_type"), "application_type", APPLICATION_TYPES)
    target_area_id = v_str(require(b, "target_assessment_area_id"), "target_assessment_area_id")

    branch_code = optional(b, "branch_code")
    branch_tract = optional(b, "branch_census_tract")
    branch_level = optional(b, "branch_tract_income_level")
    if app_type == "BRANCH_OPENING":
        branch_code = v_str(require(b, "branch_code"), "branch_code")
        branch_tract = v_str(require(b, "branch_census_tract"), "branch_census_tract")
        branch_level = v_enum(
            require(b, "branch_tract_income_level"), "branch_tract_income_level", TRACT_INCOME_LEVELS
        )
    else:
        if branch_code is not None:
            branch_code = v_str(branch_code, "branch_code")
        if branch_tract is not None:
            branch_tract = v_str(branch_tract, "branch_census_tract")
        if branch_level is not None:
            branch_level = v_enum(branch_level, "branch_tract_income_level", TRACT_INCOME_LEVELS)

    # Referenced area must exist.
    get_area_or_404(target_area_id)

    a = new_entity()
    a.update(
        {
            "application_type": app_type,
            "target_assessment_area_id": target_area_id,
            "branch_code": branch_code,
            "branch_census_tract": branch_tract,
            "branch_tract_income_level": branch_level,
            "linked_branch_id": None,
            "decision_reason": None,
            "status": "DRAFT",
        }
    )
    STORE["expansion_applications"][a["id"]] = a
    return ok(application_out(a), status=201)


@app.route("/cra/expansion-applications/<app_id>", methods=["GET"])
def get_application(app_id):
    authenticate(ALL_ROLES)
    return ok(application_out(get_application_or_404(app_id)))


@app.route("/cra/expansion-applications/<app_id>/submit", methods=["POST"])
def submit_application(app_id):
    authenticate(EXECUTIVE_ROLES)
    appl = get_application_or_404(app_id)
    if appl["status"] != "DRAFT":
        api_err("ERR_INVALID_STATE", "Only a DRAFT application can be submitted.", 409)

    # Business safety: the latest FINALIZED exam must be OUTSTANDING or SATISFACTORY.
    finalized = [e for e in STORE["exam_cycles"].values() if e["status"] == "FINALIZED"]
    if finalized:
        latest = max(
            finalized,
            key=lambda e: (parse_date_str(e["evaluation_window_end"]), e["created_at"], e["_seq"]),
        )
        if latest["composite_rating"] not in ("OUTSTANDING", "SATISFACTORY"):
            api_err(
                "ERR_RATING_BLOCKS_EXPANSION",
                "The latest finalized exam's composite rating blocks expansion.",
                422,
            )

    if appl["application_type"] == "BRANCH_OPENING":
        # Stage the PROPOSED branch. branch_code must remain unique.
        for other in STORE["branches"].values():
            if other["branch_code"] == appl["branch_code"]:
                api_err("ERR_VALIDATION", "branch_code already exists.", 400)
        br = new_entity()
        br.update(
            {
                "branch_code": appl["branch_code"],
                "assessment_area_id": appl["target_assessment_area_id"],
                "census_tract": appl["branch_census_tract"],
                "tract_income_level": appl["branch_tract_income_level"],
                "expansion_application_id": appl["id"],
                "opened_date": None,
                "closed_date": None,
                "notice_posted_date": None,
                "status": "PROPOSED",
            }
        )
        STORE["branches"][br["id"]] = br
        appl["linked_branch_id"] = br["id"]

    appl["status"] = "SUBMITTED"
    touch(appl)
    return ok(application_out(appl))


@app.route("/cra/expansion-applications/<app_id>/decide", methods=["POST"])
def decide_application(app_id):
    authenticate(EXAMINER_ROLES)
    appl = get_application_or_404(app_id)
    b = json_body()
    decision = v_enum(require(b, "decision"), "decision", ("APPROVE", "DENY"))
    reason = optional(b, "decision_reason")
    if reason is not None:
        reason = v_str(reason, "decision_reason")
    if appl["status"] != "SUBMITTED":
        api_err("ERR_INVALID_STATE", "Only a SUBMITTED application can be decided.", 409)

    appl["status"] = "APPROVED" if decision == "APPROVE" else "DENIED"
    appl["decision_reason"] = reason
    touch(appl)

    if decision == "DENY" and appl["linked_branch_id"] is not None:
        br = STORE["branches"].get(appl["linked_branch_id"])
        if br is not None and br["status"] == "PROPOSED":
            br["status"] = "WITHDRAWN"
            touch(br)
    return ok(application_out(appl))


@app.route("/cra/expansion-applications/<app_id>/branches", methods=["GET"])
def list_application_branches(app_id):
    authenticate(ALL_ROLES)
    appl = get_application_or_404(app_id)
    records = [
        b for b in STORE["branches"].values() if b["expansion_application_id"] == appl["id"]
    ]
    return list_response(records, branch_out)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
from core import CLOCK  # noqa: E402


@app.route("/cra/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate(ADMIN_ROLES)
    b = json_body()
    to_iso8601 = v_str(require(b, "to_iso8601"), "to_iso8601")
    dt = parse_datetime_str(to_iso8601)
    if dt is None:
        api_err("ERR_VALIDATION", "to_iso8601 must be a valid ISO 8601 timestamp.", 400)
    CLOCK.set(dt)
    return ok({"current_utc": to_iso8601})

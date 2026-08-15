"""Branches, public comments, and the singleton public file."""

from core import (
    ALL_ROLES,
    COMMENT_CHANNELS,
    COMMENT_SUBJECTS,
    STORE,
    TRACT_INCOME_LEVELS,
    api_err,
    authenticate,
    branch_out,
    cascade_public_file_comments,
    cascade_public_file_stale,
    clock_today,
    comment_out,
    fmt_date,
    fmt_ts,
    get_area_or_404,
    get_branch_or_404,
    get_comment_or_404,
    get_public_file,
    get_public_file_or_404,
    json_body,
    new_entity,
    now_dt,
    ok,
    optional,
    parse_date_str,
    public_file_out,
    require,
    touch,
    v_enum,
    v_str,
    app,
)

EXECUTIVE_ROLES = ("BankExecutive",)
OFFICER_ROLES = ("CRAOfficer",)
COMMENT_CREATE_ROLES = ("CRAOfficer", "ComplianceAnalyst")


# ---------------------------------------------------------------------------
# Branches
# ---------------------------------------------------------------------------
@app.route("/cra/branches", methods=["POST"])
def create_branch():
    authenticate(EXECUTIVE_ROLES)
    b = json_body()
    branch_code = v_str(require(b, "branch_code"), "branch_code")
    area_id = v_str(require(b, "assessment_area_id"), "assessment_area_id")
    tract = v_str(require(b, "census_tract"), "census_tract")
    level = v_enum(require(b, "tract_income_level"), "tract_income_level", TRACT_INCOME_LEVELS)

    # Referenced area must exist.
    get_area_or_404(area_id)

    # branch_code is unique across all branches.
    for other in STORE["branches"].values():
        if other["branch_code"] == branch_code:
            api_err("ERR_VALIDATION", "branch_code already exists.", 400)

    br = new_entity()
    br.update(
        {
            "branch_code": branch_code,
            "assessment_area_id": area_id,
            "census_tract": tract,
            "tract_income_level": level,
            "expansion_application_id": None,
            "opened_date": None,
            "closed_date": None,
            "notice_posted_date": None,
            "status": "PROPOSED",
        }
    )
    STORE["branches"][br["id"]] = br
    return ok(branch_out(br), status=201)


@app.route("/cra/branches/<branch_id>", methods=["GET"])
def get_branch(branch_id):
    authenticate(ALL_ROLES)
    return ok(branch_out(get_branch_or_404(branch_id)))


@app.route("/cra/branches/<branch_id>/open", methods=["POST"])
def open_branch(branch_id):
    authenticate(EXECUTIVE_ROLES)
    br = get_branch_or_404(branch_id)
    if br["status"] != "PROPOSED":
        api_err("ERR_INVALID_STATE", "Only a PROPOSED branch can be opened.", 409)
    if br["expansion_application_id"] is not None:
        appl = STORE["expansion_applications"].get(br["expansion_application_id"])
        if appl is None or appl["status"] != "APPROVED":
            api_err(
                "ERR_APPLICATION_NOT_APPROVED",
                "The linked expansion application is not APPROVED.",
                422,
            )
    br["status"] = "OPEN"
    br["opened_date"] = fmt_date(clock_today())
    touch(br)
    cascade_public_file_stale("branch_list_current")
    return ok(branch_out(br))


@app.route("/cra/branches/<branch_id>/close", methods=["POST"])
def close_branch(branch_id):
    authenticate(EXECUTIVE_ROLES)
    br = get_branch_or_404(branch_id)
    b = json_body()
    notice = require(b, "notice_posted_date")
    if parse_date_str(notice) is None:
        api_err("ERR_VALIDATION", "Field notice_posted_date must be an ISO date (YYYY-MM-DD).", 400)
    if br["status"] != "OPEN":
        api_err("ERR_INVALID_STATE", "Only an OPEN branch can be closed.", 409)
    days = (clock_today() - parse_date_str(notice)).days
    if days < 90:
        api_err(
            "ERR_CLOSURE_NOTICE_SHORT",
            "Public closure notice must be posted at least 90 days before closure.",
            422,
        )
    br["status"] = "CLOSED"
    br["closed_date"] = fmt_date(clock_today())
    br["notice_posted_date"] = notice
    touch(br)
    cascade_public_file_stale("branch_list_current")
    return ok(branch_out(br))


# ---------------------------------------------------------------------------
# Public comments
# ---------------------------------------------------------------------------
@app.route("/cra/public-comments", methods=["POST"])
def create_comment():
    authenticate(COMMENT_CREATE_ROLES)
    b = json_body()
    name = v_str(require(b, "commenter_name"), "commenter_name")
    channel = v_enum(require(b, "channel"), "channel", COMMENT_CHANNELS)
    subject = v_enum(require(b, "subject_area"), "subject_area", COMMENT_SUBJECTS)
    content = v_str(require(b, "content"), "content")

    c = new_entity()
    c.update(
        {
            "commenter_name": name,
            "channel": channel,
            "subject_area": subject,
            "content": content,
            "received_at": fmt_ts(now_dt()),
            "response_text": None,
            "status": "RECEIVED",
        }
    )
    STORE["public_comments"][c["id"]] = c
    cascade_public_file_comments()
    return ok(comment_out(c), status=201)


@app.route("/cra/public-comments/<comment_id>/publish", methods=["POST"])
def publish_comment(comment_id):
    authenticate(OFFICER_ROLES)
    c = get_comment_or_404(comment_id)
    if c["status"] != "RECEIVED":
        api_err("ERR_INVALID_STATE", "Only a RECEIVED comment can be published.", 409)
    c["status"] = "PUBLISHED"
    touch(c)
    cascade_public_file_comments()
    return ok(comment_out(c))


@app.route("/cra/public-comments/<comment_id>/respond", methods=["POST"])
def respond_comment(comment_id):
    authenticate(OFFICER_ROLES)
    c = get_comment_or_404(comment_id)
    b = json_body()
    response_text = v_str(require(b, "response_text"), "response_text")
    if c["status"] != "PUBLISHED":
        api_err("ERR_INVALID_STATE", "Only a PUBLISHED comment can be responded to.", 409)
    c["status"] = "RESPONDED"
    c["response_text"] = response_text
    touch(c)
    return ok(comment_out(c))


# ---------------------------------------------------------------------------
# Public file (singleton)
# ---------------------------------------------------------------------------
@app.route("/cra/public-files", methods=["POST"])
def create_public_file():
    authenticate(OFFICER_ROLES)
    b = json_body()
    bank_name = v_str(require(b, "bank_name"), "bank_name")
    if get_public_file() is not None:
        api_err("ERR_PUBLIC_FILE_EXISTS", "A public file already exists (singleton).", 409)
    pf = new_entity()
    pf.update(
        {
            "bank_name": bank_name,
            "branch_list_current": True,
            "aa_list_current": True,
            "disclosure_statement_present": False,
        }
    )
    STORE["public_files"][pf["id"]] = pf
    return ok(public_file_out(pf), status=201)


@app.route("/cra/public-files/<file_id>", methods=["GET"])
def get_public_file_route(file_id):
    authenticate(ALL_ROLES)
    return ok(public_file_out(get_public_file_or_404(file_id)))


@app.route("/cra/public-files/<file_id>/refresh-items", methods=["POST"])
def refresh_public_file(file_id):
    authenticate(OFFICER_ROLES)
    pf = get_public_file_or_404(file_id)
    b = json_body()
    changed = False
    # Only an explicit true takes effect; omitted or false leaves the flag unchanged.
    if optional(b, "branch_list") is True and not pf["branch_list_current"]:
        pf["branch_list_current"] = True
        changed = True
    if optional(b, "aa_list") is True and not pf["aa_list_current"]:
        pf["aa_list_current"] = True
        changed = True
    if optional(b, "disclosure_statement") is True and not pf["disclosure_statement_present"]:
        pf["disclosure_statement_present"] = True
        changed = True
    if changed:
        touch(pf)
    return ok(public_file_out(pf))

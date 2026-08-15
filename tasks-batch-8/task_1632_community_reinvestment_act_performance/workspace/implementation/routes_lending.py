"""Loan records and community development activities."""

from decimal import Decimal

from core import (
    ALL_ROLES,
    FULL_COUNT_LMI_THRESHOLD,
    LOAN_TYPES,
    PURPOSE_CATEGORIES,
    ACTIVITY_TYPES,
    SMALL_REVENUE_THRESHOLD_CENTS,
    STORE,
    TRACT_INCOME_LEVELS,
    activity_out,
    api_err,
    authenticate,
    get_activity_or_404,
    get_area_or_404,
    get_loan_or_404,
    json_body,
    loan_out,
    new_entity,
    ok,
    parse_date_str,
    recompute_confirmed_loan_count,
    recompute_qualified_cd_total,
    require,
    round_cents,
    touch,
    v_date,
    v_enum,
    v_int,
    v_num,
    v_str,
    app,
)

ANALYST_ROLES = ("ComplianceAnalyst",)
REVIEWER_ROLES = ("QualificationReviewer",)


# ---------------------------------------------------------------------------
# Loan records
# ---------------------------------------------------------------------------
@app.route("/cra/loan-records", methods=["POST"])
def create_loan_record():
    authenticate(ANALYST_ROLES)
    b = json_body()
    area_id = v_str(require(b, "assessment_area_id"), "assessment_area_id")
    loan_type = v_enum(require(b, "loan_type"), "loan_type", LOAN_TYPES)
    amount = v_int(require(b, "loan_amount_cents"), "loan_amount_cents", minimum=1)
    revenue = v_int(
        require(b, "borrower_gross_annual_revenue_cents"),
        "borrower_gross_annual_revenue_cents",
        minimum=0,
    )
    action_date = v_date(require(b, "action_date"), "action_date")
    tract = v_str(require(b, "census_tract"), "census_tract")
    level = v_enum(require(b, "tract_income_level"), "tract_income_level", TRACT_INCOME_LEVELS)

    # Referenced area must exist.
    get_area_or_404(area_id)

    ln = new_entity()
    ln.update(
        {
            "assessment_area_id": area_id,
            "loan_type": loan_type,
            "loan_amount_cents": amount,
            "borrower_gross_annual_revenue_cents": revenue,
            "action_date": action_date,
            "census_tract": tract,
            "tract_income_level": level,
            "small_revenue_flag": revenue <= SMALL_REVENUE_THRESHOLD_CENTS,
            "lmi_geography_flag": level in ("LOW", "MODERATE"),
            "reporting_year": parse_date_str(action_date).year,
            "status": "DRAFT",
        }
    )
    STORE["loan_records"][ln["id"]] = ln
    return ok(loan_out(ln), status=201)


@app.route("/cra/loan-records/<loan_id>", methods=["GET"])
def get_loan_record(loan_id):
    authenticate(ALL_ROLES)
    return ok(loan_out(get_loan_or_404(loan_id)))


@app.route("/cra/loan-records/<loan_id>/confirm", methods=["POST"])
def confirm_loan(loan_id):
    authenticate(ANALYST_ROLES)
    ln = get_loan_or_404(loan_id)
    if ln["status"] != "DRAFT":
        api_err("ERR_INVALID_STATE", "Only a DRAFT loan record can be confirmed.", 409)
    area = STORE["assessment_areas"][ln["assessment_area_id"]]
    if area["status"] != "ACTIVE":
        api_err("ERR_AREA_NOT_ACTIVE", "Referenced assessment area is not ACTIVE.", 422)
    if ln["census_tract"] not in area["census_tracts"]:
        api_err(
            "ERR_TRACT_NOT_IN_AREA",
            "Loan record census_tract is not an element of the referenced area's census_tracts.",
            422,
        )
    ln["status"] = "CONFIRMED"
    touch(ln)
    recompute_confirmed_loan_count(area)
    return ok(loan_out(ln))


@app.route("/cra/loan-records/<loan_id>/return-to-draft", methods=["POST"])
def return_loan_to_draft(loan_id):
    authenticate(ANALYST_ROLES)
    ln = get_loan_or_404(loan_id)
    if ln["status"] != "CONFIRMED":
        api_err("ERR_INVALID_STATE", "Only a CONFIRMED loan record can be returned to draft.", 409)
    ln["status"] = "DRAFT"
    touch(ln)
    area = STORE["assessment_areas"][ln["assessment_area_id"]]
    recompute_confirmed_loan_count(area)
    return ok(loan_out(ln))


@app.route("/cra/loan-records/<loan_id>/mark-reported", methods=["POST"])
def mark_loan_reported(loan_id):
    authenticate(ANALYST_ROLES)
    ln = get_loan_or_404(loan_id)
    if ln["status"] != "CONFIRMED":
        api_err("ERR_INVALID_STATE", "Only a CONFIRMED loan record can be marked reported.", 409)
    ln["status"] = "REPORTED"
    touch(ln)
    # REPORTED loans still count; the recompute is a no-op for the area counter.
    area = STORE["assessment_areas"][ln["assessment_area_id"]]
    recompute_confirmed_loan_count(area)
    return ok(loan_out(ln))


# ---------------------------------------------------------------------------
# Community development activities
# ---------------------------------------------------------------------------
@app.route("/cra/community-development-activities", methods=["POST"])
def create_activity():
    uid = authenticate(ANALYST_ROLES)
    b = json_body()
    area_id = v_str(require(b, "assessment_area_id"), "assessment_area_id")
    activity_type = v_enum(require(b, "activity_type"), "activity_type", ACTIVITY_TYPES)
    amount = v_int(require(b, "amount_cents"), "amount_cents", minimum=1)
    purpose = v_enum(
        require(b, "primary_purpose_category"), "primary_purpose_category", PURPOSE_CATEGORIES
    )
    pct = v_num(require(b, "lmi_benefit_pct"), "lmi_benefit_pct")
    if float(pct) < 0 or float(pct) > 1:
        api_err("ERR_VALIDATION", "lmi_benefit_pct must be within 0..1 inclusive.", 400)
    activity_date = v_date(require(b, "activity_date"), "activity_date")

    get_area_or_404(area_id)

    a = new_entity()
    a.update(
        {
            "assessment_area_id": area_id,
            "activity_type": activity_type,
            "amount_cents": amount,
            "primary_purpose_category": purpose,
            "lmi_benefit_pct": pct,
            "activity_date": activity_date,
            "submitted_by_user_id": uid,
            "reviewed_by_user_id": None,
            "disqualify_reason": None,
            "allocation_method": None,
            "qualified_amount_cents": 0,
            "status": "SUBMITTED",
        }
    )
    STORE["cd_activities"][a["id"]] = a
    return ok(activity_out(a), status=201)


@app.route("/cra/community-development-activities/<act_id>/review-decision", methods=["POST"])
def review_decision(act_id):
    uid = authenticate(REVIEWER_ROLES)
    act = get_activity_or_404(act_id)
    b = json_body()
    decision = v_enum(require(b, "decision"), "decision", ("QUALIFY", "DISQUALIFY"))
    allocation_method = None
    disqualify_reason = None
    if decision == "QUALIFY":
        allocation_method = v_enum(
            require(b, "allocation_method"), "allocation_method", ("FULL_COUNT", "PRO_RATA")
        )
    else:
        disqualify_reason = v_str(require(b, "disqualify_reason"), "disqualify_reason")

    if act["status"] != "SUBMITTED":
        api_err(
            "ERR_INVALID_STATE",
            "Only a SUBMITTED activity can receive a review decision.",
            409,
        )

    # Business safety: segregation of duties.
    if uid == act["submitted_by_user_id"]:
        api_err(
            "ERR_SEGREGATION_OF_DUTIES",
            "The reviewer may not be the operator who submitted the activity.",
            422,
        )

    if decision == "QUALIFY":
        # Business constraint: full-count LMI threshold.
        pct = Decimal(str(act["lmi_benefit_pct"]))
        if allocation_method == "FULL_COUNT" and pct < FULL_COUNT_LMI_THRESHOLD:
            api_err(
                "ERR_LMI_THRESHOLD_NOT_MET",
                "allocation_method=FULL_COUNT requires lmi_benefit_pct >= 0.51.",
                422,
            )
        # Business referential: area must be ACTIVE.
        area = STORE["assessment_areas"][act["assessment_area_id"]]
        if area["status"] != "ACTIVE":
            api_err("ERR_AREA_NOT_ACTIVE", "Referenced assessment area is not ACTIVE.", 422)
        # Qualified amount per calculation activity_qualified_amount.
        if allocation_method == "FULL_COUNT":
            qualified = act["amount_cents"]
        else:
            qualified = round_cents(Decimal(act["amount_cents"]) * pct)
        # Business fiscal: same-area same-calendar-year budget cap.
        year = parse_date_str(act["activity_date"]).year
        used = 0
        for other in STORE["cd_activities"].values():
            if (
                other["assessment_area_id"] == area["id"]
                and other["status"] == "QUALIFIED"
                and other["id"] != act["id"]
                and parse_date_str(other["activity_date"]).year == year
            ):
                used += other["qualified_amount_cents"]
        if used + qualified > area["annual_cd_budget_cents"]:
            api_err(
                "ERR_CD_BUDGET_EXCEEDED",
                "Qualification would exceed the area's annual CD budget for the activity's calendar year.",
                422,
            )
        act["status"] = "QUALIFIED"
        act["reviewed_by_user_id"] = uid
        act["allocation_method"] = allocation_method
        act["qualified_amount_cents"] = qualified
        touch(act)
        recompute_qualified_cd_total(area)
    else:
        act["status"] = "DISQUALIFIED"
        act["reviewed_by_user_id"] = uid
        act["disqualify_reason"] = disqualify_reason
        touch(act)

    return ok(activity_out(act))


@app.route("/cra/community-development-activities/<act_id>/resubmit", methods=["POST"])
def resubmit_activity(act_id):
    authenticate(ANALYST_ROLES)
    act = get_activity_or_404(act_id)
    if act["status"] != "DISQUALIFIED":
        api_err("ERR_INVALID_STATE", "Only a DISQUALIFIED activity can be resubmitted.", 409)
    area = STORE["assessment_areas"][act["assessment_area_id"]]
    if area["status"] != "ACTIVE":
        api_err("ERR_AREA_NOT_ACTIVE", "Referenced assessment area is not ACTIVE.", 422)
    act["status"] = "SUBMITTED"
    act["disqualify_reason"] = None
    act["reviewed_by_user_id"] = None
    act["allocation_method"] = None
    act["qualified_amount_cents"] = 0
    touch(act)
    return ok(activity_out(act))

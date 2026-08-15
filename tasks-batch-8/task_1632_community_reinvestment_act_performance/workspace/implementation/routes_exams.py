"""Exam cycles, their lifecycle, and the computed lending-metrics read."""

from decimal import Decimal

from core import (
    ALL_ROLES,
    CRA_REPORTABLE_CAP_CENTS,
    EXAM_TYPES,
    REGISTER_ROUND_UNIT_CENTS,
    STORE,
    TEST_RATINGS,
    api_err,
    authenticate,
    branch_out,
    exam_out,
    get_exam_or_404,
    get_public_file,
    json_body,
    list_response,
    loan_out,
    new_entity,
    ok,
    optional,
    parse_date_str,
    public_file_posture,
    q_enum,
    require,
    ratio4,
    round2,
    touch,
    v_enum,
    v_str,
    app,
)

EXAMINER_ROLES = ("BankExaminer",)
OFFICER_ROLES = ("CRAOfficer",)

RATING_POINTS = {
    "OUTSTANDING": 10,
    "SATISFACTORY": 6,
    "NEEDS_TO_IMPROVE": 2,
    "SUBSTANTIAL_NONCOMPLIANCE": 0,
}


def compute_composite(lending, investment, service):
    points = (
        Decimal("0.5") * RATING_POINTS[lending]
        + Decimal("0.25") * RATING_POINTS[investment]
        + Decimal("0.25") * RATING_POINTS[service]
    )
    composite_points = round2(points)
    if composite_points >= Decimal("8.50"):
        rating = "OUTSTANDING"
    elif composite_points >= Decimal("5.00"):
        rating = "SATISFACTORY"
    elif composite_points >= Decimal("2.50"):
        rating = "NEEDS_TO_IMPROVE"
    else:
        rating = "SUBSTANTIAL_NONCOMPLIANCE"
    return composite_points, rating


@app.route("/cra/exam-cycles", methods=["POST"])
def create_exam_cycle():
    authenticate(EXAMINER_ROLES)
    b = json_body()
    exam_type = v_enum(require(b, "exam_type"), "exam_type", EXAM_TYPES)
    start = require(b, "evaluation_window_start")
    end = require(b, "evaluation_window_end")
    if parse_date_str(start) is None:
        api_err("ERR_VALIDATION", "Field evaluation_window_start must be an ISO date.", 400)
    if parse_date_str(end) is None:
        api_err("ERR_VALIDATION", "Field evaluation_window_end must be an ISO date.", 400)
    narrative = optional(b, "performance_context_narrative")
    if narrative is None:
        narrative = ""
    else:
        narrative = v_str(narrative, "performance_context_narrative")

    new_start, new_end = parse_date_str(start), parse_date_str(end)

    # Business constraint (tier 6): closed windows may not share any calendar date.
    for other in STORE["exam_cycles"].values():
        o_start = parse_date_str(other["evaluation_window_start"])
        o_end = parse_date_str(other["evaluation_window_end"])
        if new_start <= o_end and o_start <= new_end:
            api_err(
                "ERR_EXAM_WINDOW_OVERLAP",
                "Evaluation window shares at least one calendar date with an existing exam.",
                409,
            )

    # Business temporal (tier 7): window ordering.
    if new_end < new_start:
        api_err(
            "ERR_INVALID_WINDOW",
            "evaluation_window_end must be on or after evaluation_window_start.",
            400,
        )

    e = new_entity()
    e.update(
        {
            "exam_type": exam_type,
            "evaluation_window_start": start,
            "evaluation_window_end": end,
            "performance_context_narrative": narrative,
            "lending_test_rating": None,
            "investment_test_rating": None,
            "service_test_rating": None,
            "composite_points": None,
            "composite_rating": None,
            "appeal_reason": None,
            "status": "SCHEDULED",
        }
    )
    STORE["exam_cycles"][e["id"]] = e
    return ok(exam_out(e), status=201)


@app.route("/cra/exam-cycles/<exam_id>", methods=["GET"])
def get_exam_cycle(exam_id):
    authenticate(ALL_ROLES)
    return ok(exam_out(get_exam_or_404(exam_id)))


@app.route("/cra/exam-cycles/<exam_id>/performance-context", methods=["PATCH"])
def patch_performance_context(exam_id):
    authenticate(OFFICER_ROLES)
    exam = get_exam_or_404(exam_id)
    b = json_body()
    narrative = v_str(require(b, "performance_context_narrative"), "performance_context_narrative")
    if exam["status"] not in ("SCHEDULED", "DATA_COLLECTION", "FIELDWORK"):
        api_err(
            "ERR_INVALID_STATE",
            "The performance context narrative is editable only while SCHEDULED, DATA_COLLECTION, or FIELDWORK.",
            409,
        )
    exam["performance_context_narrative"] = narrative
    touch(exam)
    return ok(exam_out(exam))


@app.route("/cra/exam-cycles/<exam_id>/begin-data-collection", methods=["POST"])
def begin_data_collection(exam_id):
    authenticate(EXAMINER_ROLES)
    exam = get_exam_or_404(exam_id)
    if exam["status"] != "SCHEDULED":
        api_err("ERR_INVALID_STATE", "Only a SCHEDULED exam can begin data collection.", 409)
    exam["status"] = "DATA_COLLECTION"
    touch(exam)
    return ok(exam_out(exam))


@app.route("/cra/exam-cycles/<exam_id>/begin-fieldwork", methods=["POST"])
def begin_fieldwork(exam_id):
    authenticate(EXAMINER_ROLES)
    exam = get_exam_or_404(exam_id)
    if exam["status"] != "DATA_COLLECTION":
        api_err("ERR_INVALID_STATE", "Only an exam in DATA_COLLECTION can begin fieldwork.", 409)
    pf = get_public_file()
    if pf is None or public_file_posture(pf) != "COMPLETE":
        api_err(
            "ERR_PUBLIC_FILE_INCOMPLETE",
            "Fieldwork requires the public file to exist with posture COMPLETE.",
            422,
        )
    exam["status"] = "FIELDWORK"
    touch(exam)
    return ok(exam_out(exam))


@app.route("/cra/exam-cycles/<exam_id>/assign-preliminary-rating", methods=["POST"])
def assign_preliminary_rating(exam_id):
    authenticate(EXAMINER_ROLES)
    exam = get_exam_or_404(exam_id)
    b = json_body()
    lending = v_enum(require(b, "lending_test_rating"), "lending_test_rating", TEST_RATINGS)
    investment = v_enum(
        require(b, "investment_test_rating"), "investment_test_rating", TEST_RATINGS
    )
    service = v_enum(require(b, "service_test_rating"), "service_test_rating", TEST_RATINGS)
    if exam["status"] != "FIELDWORK":
        api_err(
            "ERR_INVALID_STATE",
            "Only an exam in FIELDWORK can be assigned a preliminary rating.",
            409,
        )
    composite_points, composite_rating = compute_composite(lending, investment, service)
    exam["lending_test_rating"] = lending
    exam["investment_test_rating"] = investment
    exam["service_test_rating"] = service
    exam["composite_points"] = float(composite_points)
    exam["composite_rating"] = composite_rating
    exam["status"] = "PRELIMINARY_RATING"
    touch(exam)
    return ok(exam_out(exam))


@app.route("/cra/exam-cycles/<exam_id>/appeal", methods=["POST"])
def appeal_exam(exam_id):
    authenticate(OFFICER_ROLES)
    exam = get_exam_or_404(exam_id)
    b = json_body()
    reason = v_str(require(b, "appeal_reason"), "appeal_reason")
    if exam["status"] != "PRELIMINARY_RATING":
        api_err("ERR_INVALID_STATE", "Only a PRELIMINARY_RATING exam can be appealed.", 409)
    exam["status"] = "APPEALED"
    exam["appeal_reason"] = reason
    touch(exam)
    return ok(exam_out(exam))


@app.route("/cra/exam-cycles/<exam_id>/reopen-fieldwork", methods=["POST"])
def reopen_fieldwork(exam_id):
    authenticate(EXAMINER_ROLES)
    exam = get_exam_or_404(exam_id)
    if exam["status"] != "APPEALED":
        api_err("ERR_INVALID_STATE", "Only an APPEALED exam can reopen fieldwork.", 409)
    exam["status"] = "FIELDWORK"
    touch(exam)
    return ok(exam_out(exam))


@app.route("/cra/exam-cycles/<exam_id>/finalize", methods=["POST"])
def finalize_exam(exam_id):
    authenticate(EXAMINER_ROLES)
    exam = get_exam_or_404(exam_id)
    if exam["status"] != "PRELIMINARY_RATING":
        api_err("ERR_INVALID_STATE", "Only a PRELIMINARY_RATING exam can be finalized.", 409)
    exam["status"] = "FINALIZED"
    touch(exam)

    # Adverse composite cascades: SUBMITTED applications -> DENIED (RATING_BLOCK),
    # and each such application's PROPOSED staged branch -> WITHDRAWN.
    if exam["composite_rating"] in ("NEEDS_TO_IMPROVE", "SUBSTANTIAL_NONCOMPLIANCE"):
        for appl in STORE["expansion_applications"].values():
            if appl["status"] != "SUBMITTED":
                continue
            appl["status"] = "DENIED"
            appl["decision_reason"] = "RATING_BLOCK"
            touch(appl)
            if appl["linked_branch_id"] is not None:
                br = STORE["branches"].get(appl["linked_branch_id"])
                if br is not None and br["status"] == "PROPOSED":
                    br["status"] = "WITHDRAWN"
                    touch(br)
    return ok(exam_out(exam))


@app.route("/cra/exam-cycles/<exam_id>/lending-metrics", methods=["GET"])
def lending_metrics(exam_id):
    authenticate(ALL_ROLES)
    exam = get_exam_or_404(exam_id)
    basis = q_enum("basis", ("CURRENT", "SNAPSHOT")) or "CURRENT"

    start = parse_date_str(exam["evaluation_window_start"])
    end = parse_date_str(exam["evaluation_window_end"])

    def in_window(ln):
        d = parse_date_str(ln["action_date"])
        return d is not None and start <= d <= end

    if basis == "SNAPSHOT":
        loans = [
            ln for ln in STORE["loan_records"].values() if in_window(ln) and ln["status"] == "REPORTED"
        ]
    else:
        loans = [
            ln
            for ln in STORE["loan_records"].values()
            if in_window(ln) and ln["status"] in ("CONFIRMED", "REPORTED")
        ]

    loan_count = len(loans)
    inside_count = 0
    lmi_geo_count = 0
    lmi_borrower_count = 0
    for ln in loans:
        area = STORE["assessment_areas"].get(ln["assessment_area_id"])
        if area is not None and ln["census_tract"] in area["census_tracts"]:
            inside_count += 1
        if ln["lmi_geography_flag"]:
            lmi_geo_count += 1
        if ln["small_revenue_flag"]:
            lmi_borrower_count += 1

    # CRA register totals: REPORTED loans in window, per-loan cap + round FIRST, then sum.
    register = {"SMALL_BUSINESS": 0, "SMALL_FARM": 0}
    for ln in STORE["loan_records"].values():
        if ln["status"] != "REPORTED" or not in_window(ln):
            continue
        capped = min(ln["loan_amount_cents"], CRA_REPORTABLE_CAP_CENTS)
        rounded_units = (Decimal(capped) / Decimal(REGISTER_ROUND_UNIT_CENTS)).quantize(
            Decimal("1"), rounding="ROUND_HALF_UP"
        )
        register[ln["loan_type"]] += int(rounded_units) * REGISTER_ROUND_UNIT_CENTS

    return ok(
        {
            "loan_count": loan_count,
            "inside_aa_pct": float(ratio4(inside_count, loan_count)),
            "lmi_geography_pct": float(ratio4(lmi_geo_count, loan_count)),
            "lmi_borrower_pct": float(ratio4(lmi_borrower_count, loan_count)),
            "small_business_register_total_cents": register["SMALL_BUSINESS"],
            "small_farm_register_total_cents": register["SMALL_FARM"],
        }
    )

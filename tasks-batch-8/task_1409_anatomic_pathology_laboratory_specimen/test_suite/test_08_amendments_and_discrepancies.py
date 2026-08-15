"""Amendment cycle (FINAL -> AMENDING -> FINAL), the one-SIGNED-report
invariant, segregation of duties, discrepancy resolution tiers, and the two
discrepancy-rate variants."""
import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    acknowledge_discrepancy,
    amend_case,
    amend_sign,
    amend_cancel,
    assert_instant_equal,
    assign_case,
    create_discrepancy,
    create_pathologist,
    get_case,
    get_discrepancy,
    get_pathologist,
    get_report,
    get_signed_report_id,
    list_reports,
    make_pathologist_headers,
    resolve_discrepancy,
    set_clock,
    setup_final_case,
    setup_pending_signout_case,
    setup_qc_passed_case,
    setup_workup_case,
    sign_out_case,
    submit_for_signout,
    validate_error,
    validate_success,
)


def test_case_final_amending_final_cycle(api):
    """PRD §3.6: "Signing moves the case `AMENDING → FINAL`, stamps the draft's
    `signed_by_pathologist_id` and `signed_at` as it becomes `SIGNED`, and
    moves the previously signed report named by `supersedes_report_id` to
    `SUPERSEDED`, with `current_signed_report_id` updated and
    `amender_pathologist_id` cleared."
    PRD §3.6: "Amending moves the case `FINAL → AMENDING`, records the caller
    in `amender_pathologist_id`, and creates a new `Report` in `DRAFT` with
    `report_class` `AMENDED`, `version_number` one greater than the prior
    report's, `supersedes_report_id` set to the current signed report"

    Design: Difficulty/non_linear_state_machine/case_final_amending_final_cycle
    """
    ctx = setup_final_case(mrn="MRN-400")
    case_id = ctx["case"]["id"]
    p1 = ctx["pathologist"]["id"]
    rep1 = ctx["report_id"]

    resp = api.amend_case(
        case_id,
        {"diagnosis_text": "Focal dysplasia", "amendment_reason": "deeper levels reviewed"},
        make_pathologist_headers(p1),
    )
    draft = validate_success(resp, expected_status=201)
    assert draft["status"] == "DRAFT"
    assert draft["report_class"] == "AMENDED"
    assert draft["version_number"] == 2
    assert draft["supersedes_report_id"] == rep1

    resp = api.amend_sign(case_id, make_pathologist_headers(p1))
    rep2 = validate_success(resp, expected_status=200)
    assert rep2["id"] == draft["id"], "the DRAFT created by amend is the report that got signed"
    assert rep2["status"] == "SIGNED"
    assert rep2["signed_by_pathologist_id"] == p1
    assert rep2["signed_at"] is not None

    case_after = get_case(case_id)
    assert case_after["status"] == "FINAL", "the cycle completed"
    assert case_after["current_signed_report_id"] == rep2["id"]
    assert case_after["amender_pathologist_id"] is None
    assert get_report(rep1)["status"] == "SUPERSEDED"


def test_case_final_amending_final_cycle_report_links(api):
    """PRD §3.6: "Across all of these flows one invariant holds: exactly one
    `SIGNED` report exists per case at any time, and the very first report of
    a case is created directly in `SIGNED` by sign-out; `DRAFT` is entered
    only through the amend flow."
    PRD §3.6: "Signing moves the case `AMENDING → FINAL`, stamps the draft's
    `signed_by_pathologist_id` and `signed_at` as it becomes `SIGNED`, and
    moves the previously signed report named by `supersedes_report_id` to
    `SUPERSEDED`, with `current_signed_report_id` updated and
    `amender_pathologist_id` cleared."

    Design: Difficulty/non_linear_state_machine/case_final_amending_final_cycle
    """
    ctx = setup_final_case(mrn="MRN-400")
    case_id = ctx["case"]["id"]
    p1 = ctx["pathologist"]["id"]
    rep1 = ctx["report_id"]

    draft = amend_case(case_id, p1, "Focal dysplasia", "deeper levels reviewed")
    # While AMENDING the case still shows the first report as current.
    mid = get_case(case_id)
    assert mid["status"] == "AMENDING"
    assert mid["amender_pathologist_id"] == p1

    rep2 = amend_sign(case_id, p1)
    assert rep2["supersedes_report_id"] == rep1
    assert rep2["version_number"] == 2
    assert rep2["report_class"] == "AMENDED"

    signed = [r for r in list_reports(case_id=case_id) if r["status"] == "SIGNED"]
    assert len(signed) == 1 and signed[0]["id"] == rep2["id"], (
        "exactly one SIGNED report survives the amendment"
    )
    assert get_report(rep1)["status"] == "SUPERSEDED"


def test_signed_report_count_invariant_after_amend_cancel(api):
    """PRD §3.6: "Cancelling the amendment instead moves the case back to
    `FINAL`, discards the draft as `CANCELLED`, and leaves the previously
    signed report `SIGNED` and `current_signed_report_id` untouched — a full
    compensation with no drift."
    PRD §3.6: "Across all of these flows one invariant holds: exactly one
    `SIGNED` report exists per case at any time"

    Design: Difficulty/compensating_invariant/signed_report_count_invariant
    """
    ctx = setup_final_case(mrn="MRN-950")
    case_id = ctx["case"]["id"]
    p1 = ctx["pathologist"]["id"]
    rep1 = ctx["report_id"]
    assert len([r for r in list_reports(case_id=case_id) if r["status"] == "SIGNED"]) == 1

    draft = amend_case(case_id, p1, "draft revision", "typo pass")
    amend_cancel(case_id, p1)

    case_after = get_case(case_id)
    assert case_after["status"] == "FINAL"
    assert case_after["current_signed_report_id"] == rep1
    assert case_after["amender_pathologist_id"] is None
    assert get_report(rep1)["status"] == "SIGNED", "the original report never left SIGNED"
    assert get_report(draft["id"])["status"] == "CANCELLED"
    signed = [r for r in list_reports(case_id=case_id) if r["status"] == "SIGNED"]
    assert len(signed) == 1 and signed[0]["id"] == rep1, (
        "the amend/cancel round trip leaves the SIGNED count at 1"
    )


def test_signed_report_count_invariant_current_report_unchanged(api):
    """PRD §3.6: "Cancelling the amendment instead moves the case back to
    `FINAL`, discards the draft as `CANCELLED`, and leaves the previously
    signed report `SIGNED` and `current_signed_report_id` untouched — a full
    compensation with no drift."

    Design: Difficulty/compensating_invariant/signed_report_count_invariant
    """
    ctx = setup_final_case(mrn="MRN-950")
    case_id = ctx["case"]["id"]
    p1 = ctx["pathologist"]["id"]
    rep1 = ctx["report_id"]
    before = get_report(rep1)

    draft = amend_case(case_id, p1, "draft revision", "typo pass")
    assert get_case(case_id)["status"] == "AMENDING"
    amend_cancel(case_id, p1)

    after = get_report(rep1)
    assert after["status"] == "SIGNED"
    assert after["signed_by_pathologist_id"] == before["signed_by_pathologist_id"]
    assert after["signed_at"] == before["signed_at"]
    case_after = get_case(case_id)
    assert case_after["current_signed_report_id"] == rep1
    assert get_report(draft["id"])["status"] == "CANCELLED"


def test_finalized_at_immutable_across_amendment(api):
    """PRD §3.6: "the case's `finalized_at` is stamped once and never
    rewritten by later amendments"
    PRD §3.1: "for a case in `FINAL` or `AMENDING` the reference is
    `finalized_at`"

    Design: Corner/calculations/finalized_at_immutable_across_amendment
    """
    ctx = setup_pending_signout_case(mrn="MRN-C6")
    case_id = ctx["case"]["id"]
    p1 = ctx["pathologist"]["id"]
    # SIMPLE CALENDAR deadline: 2026-08-05T10:00:00Z; signing at 2026-08-03T12:00Z.
    set_clock("2026-08-03T12:00:00Z")
    sign_out_case(case_id, p1)
    assert_instant_equal(
        get_case(case_id)["finalized_at"], "2026-08-03T12:00:00Z", "first finalization"
    )

    set_clock("2026-08-04T12:00:00Z")
    amend_case(case_id, p1, "benign, clarified", "clarification")
    amend_sign(case_id, p1)

    case_after = get_case(case_id)
    assert_instant_equal(
        case_after["finalized_at"], "2026-08-03T12:00:00Z",
        "the later amendment must not rewrite finalized_at",
    )
    assert case_after["status"] == "FINAL"
    assert case_after["tat_breached"] is False


def test_sod_amendment_by_original_signer_forbidden(api):
    """PRD §3.6: "when any discrepancy of severity `LEVEL_2` or `LEVEL_3` — in
    any status — references the case's `current_signed_report_id`, the caller
    must differ from that report's `signed_by_pathologist_id`, or the request
    is rejected with `ERR_SOD_AMENDMENT_FORBIDDEN` (HTTP 422)."

    Design: Corner/validations/sod_amendment_by_original_signer_forbidden
    """
    ctx = setup_final_case(mrn="MRN-V6")
    case_id = ctx["case"]["id"]
    p1 = ctx["pathologist"]["id"]
    rep1 = ctx["report_id"]
    peer = create_pathologist(full_name="Dr Peer")
    create_discrepancy(case_id, "LEVEL_2", "grading issue", report_id=rep1)

    resp = api.amend_case(
        case_id,
        {"diagnosis_text": "self fix", "amendment_reason": "qa"},
        make_pathologist_headers(p1),
    )
    validate_error(resp, ApiErrorId.ERR_SOD_AMENDMENT_FORBIDDEN)

    resp = api.amend_case(
        case_id,
        {"diagnosis_text": "peer fix", "amendment_reason": "qa"},
        make_pathologist_headers(peer["id"]),
    )
    draft = validate_success(resp, expected_status=201)
    assert draft["status"] == "DRAFT"
    assert draft["report_class"] == "AMENDED"
    assert draft["supersedes_report_id"] == rep1


def test_amend_sign_by_non_amender_forbidden(api):
    """PRD §2.1: "signing or cancelling an amendment requires equality with
    the case's `amender_pathologist_id`."
    PRD §2.1: "A request whose role is not on the endpoint's authorized list —
    or that fails an entity-backed ownership check — is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/amend_sign_by_non_amender_forbidden
    """
    ctx = setup_final_case(mrn="MRN-RB3")
    case_id = ctx["case"]["id"]
    p1 = ctx["pathologist"]["id"]
    other = create_pathologist(full_name="Dr Am2")
    draft = amend_case(case_id, p1, "rev", "r")
    assert get_case(case_id)["status"] == "AMENDING"

    resp = api.amend_sign(case_id, make_pathologist_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_report(draft["id"])["status"] == "DRAFT", "the DRAFT survives"
    assert get_case(case_id)["status"] == "AMENDING"


def _setup_two_signed_cases_with_discrepancies(api):
    """p1 signs out two GI cases; case 1 carries a LEVEL_1 discrepancy resolved
    directly from OPEN; case 2 carries a LEVEL_2 discrepancy (linked to its
    signed report) that is acknowledged, amended by a different pathologist,
    and resolved with an amendment. Returns the signer pathologist dict."""
    p1 = create_pathologist(full_name="Dr Signer")
    p2 = create_pathologist(full_name="Dr Amender")

    # Case 1: signed out, LEVEL_1 discrepancy resolved directly from OPEN.
    ctx1 = setup_qc_passed_case(mrn="MRN-200A", pathologist_name="Dr BenchOne")
    assign_case(ctx1["case"]["id"], p1["id"])
    submit_for_signout(ctx1["case"]["id"], p1["id"])
    sign_out_case(ctx1["case"]["id"], p1["id"], diagnosis_text="Benign mucosa")
    d1 = create_discrepancy(ctx1["case"]["id"], "LEVEL_1", "minor wording")
    resolve_discrepancy(d1["id"])

    # Case 2: signed out, LEVEL_2 discrepancy acknowledged, amended by p2,
    # then resolved with resolved_with_amendment true.
    ctx2 = setup_qc_passed_case(mrn="MRN-200B", pathologist_name="Dr BenchTwo")
    assign_case(ctx2["case"]["id"], p1["id"])
    submit_for_signout(ctx2["case"]["id"], p1["id"])
    sign_out_case(ctx2["case"]["id"], p1["id"], diagnosis_text="Gastritis")
    rep2 = get_signed_report_id(ctx2["case"]["id"])
    d2 = create_discrepancy(
        ctx2["case"]["id"], "LEVEL_2", "grading discordance", report_id=rep2
    )
    acknowledge_discrepancy(d2["id"], p1["id"])
    # Advance the clock so the amendment's signed_at is strictly after the
    # discrepancy's created_at.
    set_clock("2026-08-02T00:00:00Z")
    amend_case(ctx2["case"]["id"], p2["id"], "Severe gastritis", "QA discrepancy")
    amend_sign(ctx2["case"]["id"], p2["id"])
    resolve_discrepancy(d2["id"], resolved_with_amendment=True)
    return p1


def test_discrepancy_rate_simple(api):
    """PRD §3.6: "`discrepancy_rate_simple` is the plain ratio of resolved
    discrepancies to signed finals, so a `LEVEL_1` and a `LEVEL_3` contribute
    identically"
    PRD §3.6: "The denominator counts `FINAL`-class reports signed by the
    pathologist with `signed_at` inside the window — a superseded final report
    still counts. The numerator set is the `RESOLVED` discrepancies attributed
    to the pathologist with `resolved_at` inside the window."

    Design: Difficulty/dual_variant_calc/discrepancy_rate_simple_vs_severity_weighted
    """
    p1 = _setup_two_signed_cases_with_discrepancies(api)
    fetched = get_pathologist(p1["id"])
    assert fetched["discrepancy_rate_simple"] == pytest.approx(1.0, abs=0.0001), (
        "2 resolved / 2 signed FINAL-class reports"
    )


def test_discrepancy_rate_weighted(api):
    """PRD §3.6: "`discrepancy_rate_weighted` instead weights the numerator by
    severity — 1 for `LEVEL_1`, 3 for `LEVEL_2`, 5 for `LEVEL_3` — so
    identical data yields a strictly larger weighted rate whenever any
    `LEVEL_2` or `LEVEL_3` discrepancy is present."
    PRD §2.7: "Discrepancy rates (`discrepancy_rate_simple`,
    `discrepancy_rate_weighted`) are rounded half-up to 4 decimal places."

    Design: Difficulty/dual_variant_calc/discrepancy_rate_simple_vs_severity_weighted
    """
    p1 = _setup_two_signed_cases_with_discrepancies(api)
    fetched = get_pathologist(p1["id"])
    # (1 x LEVEL_1 + 3 x LEVEL_2) / 2 signed FINAL-class reports = 2.0.
    assert fetched["discrepancy_rate_weighted"] == pytest.approx(2.0, abs=0.0001)
    assert fetched["discrepancy_rate_weighted"] > fetched["discrepancy_rate_simple"], (
        "any LEVEL_2+ discrepancy makes the weighted rate strictly larger"
    )


def test_level1_discrepancy_resolves_directly_from_open(api):
    """PRD §3.6: "Resolution is severity-tiered: a `LEVEL_1` discrepancy may
    be resolved directly from `OPEN` with `resolved_with_amendment` false
    permitted"
    PRD §3.6: "Resolution stamps `resolved_at` and records
    `resolved_with_amendment`."
    PRD §2.5: "At startup the logical clock reads exactly
    `2026-08-01T00:00:00Z`, and it never silently falls back to wall time."

    Design: Corner/state_machines/level1_discrepancy_resolves_directly_from_open
    """
    ctx = setup_workup_case(mrn="MRN-S9", num_blocks=0)
    d1 = create_discrepancy(ctx["case"]["id"], "LEVEL_1", "typo")
    assert d1["status"] == "OPEN"

    resp = api.resolve_discrepancy(d1["id"], {"resolved_with_amendment": False}, ADMIN_HEADERS)
    resolved = validate_success(resp, expected_status=200)
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolved_with_amendment"] is False
    assert_instant_equal(resolved["resolved_at"], "2026-08-01T00:00:00Z", "resolved_at")


def test_level2_resolve_requires_acknowledge_then_amendment(api):
    """PRD §3.6: "Resolution is severity-tiered: a `LEVEL_1` discrepancy may
    be resolved directly from `OPEN` with `resolved_with_amendment` false
    permitted, while resolution from `ACKNOWLEDGED` accepts any severity;
    acting from any other state is rejected with `ERR_DISCREPANCY_WRONG_STATE`
    (HTTP 409)."
    PRD §3.6: "Resolving a `LEVEL_2` or `LEVEL_3` row additionally demands
    that the payload's `resolved_with_amendment` be true and that the case
    hold an `AMENDED` report in `SIGNED` status whose `signed_at` is strictly
    after the discrepancy's `created_at` — failing either condition yields
    `ERR_AMENDMENT_REQUIRED` (HTTP 422)."

    Design: Corner/validations/level2_resolve_requires_acknowledge_then_amendment
    """
    ctx = setup_final_case(mrn="MRN-VA")
    case_id = ctx["case"]["id"]
    p1 = ctx["pathologist"]["id"]
    d1 = create_discrepancy(case_id, "LEVEL_2", "major discordance")

    # From OPEN a LEVEL_2 resolve is a wrong-state error.
    resp = api.resolve_discrepancy(
        d1["id"], {"resolved_with_amendment": True}, ADMIN_HEADERS
    )
    validate_error(resp, ApiErrorId.ERR_DISCREPANCY_WRONG_STATE)

    acknowledge_discrepancy(d1["id"], p1)
    # From ACKNOWLEDGED but with no later signed amendment on the case.
    resp = api.resolve_discrepancy(
        d1["id"], {"resolved_with_amendment": True}, ADMIN_HEADERS
    )
    validate_error(resp, ApiErrorId.ERR_AMENDMENT_REQUIRED)
    assert get_discrepancy(d1["id"])["status"] == "ACKNOWLEDGED"

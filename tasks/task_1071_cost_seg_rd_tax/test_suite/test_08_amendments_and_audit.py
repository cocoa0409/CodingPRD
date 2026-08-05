"""Look-back amendments: §481(a) cascade, statute window, OCC stale version; audit-case gating.

Translates queue A (transitive amend cascade, cross_entity audit gating) and queue B
(amend-window expiry, OCC stale study version) instances.
"""
from test_helpers import validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS, fixtures
import test_helpers.factories as f

SM = TEST_USERS["study_manager_headers"]

AMEND_COMPS = [
    ("5yr", "FIVE_YEAR", 10000000),
    ("15yr", "FIFTEEN_YEAR", 20000000),
    ("39yr", "THIRTY_NINE_YEAR", 70000000),
]


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/amend_file_study_report_supersede_chain
# ---------------------------------------------------------------------------
def test_file_amended_return_computes_481a_and_supersedes_report(api):
    """PRD §3.6: "the as-filed first-year figure is the property's depreciable_basis_cents
    multiplied by the 39-year first-year MACRS rate of 2.564 percent, rounded to whole cents,
    and the catch-up is the study's first_year_depreciation_cents minus that as-filed figure.
    Filing then stamps filed_at from the logical clock, copies the computed catch-up onto the
    parent study's section_481a_cents, and supersedes the study's issued report, moving it from
    ISSUED to SUPERSEDED."

    first_year_depreciation_cents=20994800; as_filed=round(100000000*0.02564)=2564000;
    catch-up = 20994800 - 2564000 = 18430800.

    Design: Difficulty/transitive_cascade/amend_file_study_report_supersede_chain
    """
    ctx = fixtures.setup_cost_seg_delivered_lookback(api, comps=AMEND_COMPS, tax_year=2024)
    am = get_success_data(api.create_amended_return(
        ctx["study_id"], f.amended_return_payload(2024, ctx["delivered_version"]), SM))
    filed = validate_success(api.file_amended_return(am["id"], SM), 200)
    assert filed["section_481a_cents"] == 18430800

    report = fixtures.only_report(api, ctx)
    assert report["status"] == "SUPERSEDED"


def test_file_amended_return_stamps_study_section_481a(api):
    """PRD §3.6: "Filing then stamps filed_at from the logical clock, copies the computed
    catch-up onto the parent study's section_481a_cents, and supersedes the study's issued
    report."

    Isolates cascade link 1: the parent study's section_481a_cents equals the computed 18430800.

    Design: Difficulty/transitive_cascade/amend_file_study_report_supersede_chain
    """
    ctx = fixtures.setup_cost_seg_delivered_lookback(api, comps=AMEND_COMPS, tax_year=2024)
    am = get_success_data(api.create_amended_return(
        ctx["study_id"], f.amended_return_payload(2024, ctx["delivered_version"]), SM))
    get_success_data(api.file_amended_return(am["id"], SM))
    study = validate_success(api.get_study(ctx["study_id"], SM), 200)
    assert study["section_481a_cents"] == 18430800


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/audit_case_requires_delivered_study
# ---------------------------------------------------------------------------
def test_open_audit_case_on_finalized_not_delivered_rejected(api):
    """PRD §3.6: "A StudyManager may open an AuditSupportCase on a study only after it is
    DELIVERED; opening a case on a study in any other state is rejected with ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/audit_case_requires_delivered_study
    """
    ctx = fixtures.setup_cost_seg_finalized(
        api, scope_overrides={"fee_type": "FIXED", "fee_fixed_amount_cents": 100000},
        comps=[("5yr", "FIVE_YEAR", 10000000)])
    resp = api.create_audit_case(ctx["study_id"], {"irs_notice_ref": "CP2000"}, SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_open_audit_case_on_delivered_study_succeeds(api):
    """PRD §3.6: "A case is created with an irs_notice_ref identifying the IRS notice or
    examination and starts in status OPEN."

    Once the study is DELIVERED the audit case opens.

    Design: Difficulty/cross_entity_state_dependency/audit_case_requires_delivered_study
    """
    ctx = fixtures.setup_cost_seg_finalized(
        api, scope_overrides={"fee_type": "FIXED", "fee_fixed_amount_cents": 100000},
        comps=[("5yr", "FIVE_YEAR", 10000000)])
    fixtures.deliver(api, ctx)
    resp = api.create_audit_case(ctx["study_id"], {"irs_notice_ref": "CP2000"}, SM)
    data = validate_success(resp, 201)
    assert data["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Corner/validations/amend_window_expired_rejected
# ---------------------------------------------------------------------------
def test_amend_window_expired_rejected(api):
    """PRD §3.6: "Filing an amended return moves it from DRAFT to FILED but is allowed only
    while the amendment window is open: the current logical-clock year must be at most the
    amended_tax_year plus the three-year amendment statute, and a filing attempted after that
    year has passed is rejected with ERR_AMEND_WINDOW_EXPIRED."

    amended_tax_year 2020 + 3 = 2023; the default clock year is 2026 > 2023 → expired.

    Design: Corner/validations/amend_window_expired_rejected
    """
    ctx = fixtures.setup_cost_seg_delivered_lookback(
        api, comps=[("5yr", "FIVE_YEAR", 10000000)], tax_year=2020,
        placed_in_service_date="2019-03-01T00:00:00.000Z")
    am = get_success_data(api.create_amended_return(
        ctx["study_id"], f.amended_return_payload(2020, ctx["delivered_version"]), SM))
    resp = api.file_amended_return(am["id"], SM)
    validate_error(resp, ApiErrorId.ERR_AMEND_WINDOW_EXPIRED.value)


# ---------------------------------------------------------------------------
# Corner/cross_cutting_complexity_layers/amended_return_stale_study_version_conflict
# ---------------------------------------------------------------------------
def test_second_amended_return_with_stale_version_rejected(api):
    """PRD §2.9: "If expected_study_version does not equal the study's current version, the
    create is rejected with ERR_STALE_STUDY_VERSION at HTTP 412. ... A successful
    amended-return create itself advances the study's version by one."

    The first create advances the version; a second create still carrying the pre-advance
    version is stale.

    Design: Corner/cross_cutting_complexity_layers/amended_return_stale_study_version_conflict
    """
    ctx = fixtures.setup_cost_seg_delivered_lookback(
        api, comps=[("5yr", "FIVE_YEAR", 10000000)], tax_year=2024)
    sv = ctx["delivered_version"]
    get_success_data(api.create_amended_return(
        ctx["study_id"], f.amended_return_payload(2024, sv), SM))
    resp = api.create_amended_return(ctx["study_id"], f.amended_return_payload(2024, sv), SM)
    validate_error(resp, ApiErrorId.ERR_STALE_STUDY_VERSION.value)

"""Vendor application lifecycle: submission window, jury scoring loop, quorum
and category-cap boundaries, and role/ownership checks."""
import pytest

from test_helpers import (
    TEST_USERS, validate_error, validate_success,
    make_vendor_headers, make_juror_headers,
    create_market, create_vendor_entity, create_draft_application,
    create_submitted_application, create_under_jury_application,
    create_accepted_application, submit_application, score_application_n,
    decide_application, get_application, get_market,
)

OPERATOR = TEST_USERS["market_operator_headers"]
JURY_CHAIR = TEST_USERS["jury_chair_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


def test_application_submit_within_window_succeeds(api):
    """PRD §3.2: "Submission is only accepted while the market is in `SETUP`
    posture and the current UTC instant is between `application_opens_at` and
    `application_closes_at` inclusive; otherwise it is rejected with
    `ERR_APPLICATION_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/validations/satisfaction_pass_valid_application_submit
    """
    market = create_market({"name": "VM3", "season_code": "VM3-1"},
                           clock="2026-09-15T00:00:00Z")
    vendor = create_vendor_entity(legal_name="VV3")
    app = create_draft_application(market["id"], vendor["id"])
    submitted = validate_success(
        api.submit_application(market["id"], app["id"],
                               make_vendor_headers(vendor["id"])), 200)
    assert submitted["status"] == "SUBMITTED"


def test_application_submit_after_window_closed_rejected(api):
    """PRD §3.2: "Submission is only accepted while the market is in `SETUP`
    posture and the current UTC instant is between `application_opens_at` and
    `application_closes_at` inclusive; otherwise it is rejected with
    `ERR_APPLICATION_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/validations/application_window_closed_returns_409
    """
    # Clock is 2026-11-15, past the default application_closes_at of 2026-11-01.
    market = create_market({"name": "VM", "season_code": "VM-1"},
                           clock="2026-11-15T00:00:00Z")
    vendor = create_vendor_entity(legal_name="VV")
    app = create_draft_application(market["id"], vendor["id"])
    res = api.submit_application(market["id"], app["id"],
                                 make_vendor_headers(vendor["id"]))
    validate_error(res, "ERR_APPLICATION_WINDOW_CLOSED", expected_status=409)


def test_application_create_ignores_computed_jury_average(api):
    """PRD §3.2: "The application starts with `jury_scores` empty and
    `jury_average` null."

    Design: Corner/entities/application_computed_jury_average_ignored_on_input
    """
    market = create_market({"name": "CM", "season_code": "CM-1"},
                           clock="2026-09-15T00:00:00Z")
    vendor = create_vendor_entity(legal_name="CV")
    payload = {"vendor_id": vendor["id"], "requested_booth_type": "STANDARD",
               "jury_average": 99}
    app = validate_success(
        api.create_application(market["id"], payload,
                               make_vendor_headers(vendor["id"])), 201)
    assert app["jury_average"] is None, "computed jury_average must start null"
    assert app["jury_scores"] == []
    assert app["status"] == "DRAFT"


def test_first_score_moves_application_to_under_jury(api):
    """PRD §3.3: "The first score transitions the application from `SUBMITTED`
    to `UNDER_JURY`, appends `{juror_id, score_0_100}` to `jury_scores`, and
    recomputes `jury_average` as the mean of all scores."

    Design: Difficulty/non_linear_state_machine/vendor_application_cyclic_jury_loop
    """
    market = create_market({"name": "M5", "season_code": "W26E", "jury_quorum": 3},
                           clock="2026-09-15T00:00:00Z")
    vendor = create_vendor_entity(legal_name="V5", category="EXPERIENCE")
    app = create_submitted_application(market["id"], vendor["id"])
    scored = validate_success(
        api.score_application(market["id"], app["id"], {"score_0_100": 60},
                              make_juror_headers("juror-m5-0")), 200)
    assert scored["status"] == "UNDER_JURY"
    assert len(scored["jury_scores"]) == 1
    assert scored["jury_average"] == pytest.approx(60.0), \
        "mean of a single score of 60 must be 60"


def test_application_stays_under_jury_through_five_scores(api):
    """PRD §3.3: "Subsequent scores by other jury members keep the application
    in `UNDER_JURY`, append to `jury_scores`, and recompute `jury_average`."
    PRD §3.3: "The system enforces two constraints on scoring: an application may
    hold at most 5 scores, and a juror who has already scored a given application
    cannot score it again — a duplicate-juror attempt is rejected with
    `ERR_JURY_QUORUM_NOT_MET` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/vendor_application_cyclic_jury_loop
    """
    market = create_market({"name": "M5B", "season_code": "W26E2", "jury_quorum": 3},
                           clock="2026-09-15T00:00:00Z")
    vendor = create_vendor_entity(legal_name="V5B", category="EXPERIENCE")
    app = create_submitted_application(market["id"], vendor["id"])
    app = score_application_n(market["id"], app["id"], [60, 70, 80, 90, 100],
                              juror_prefix="juror-m5b")
    assert app["status"] == "UNDER_JURY", "self-loop: still UNDER_JURY after 5 scores"
    assert len(app["jury_scores"]) == 5
    assert app["jury_average"] == pytest.approx(80.0), \
        "mean of 60/70/80/90/100 must be 80"


def test_decide_below_quorum_rejected(api):
    """PRD §3.3: "If fewer than `jury_quorum` scores exist, any decide attempt
    is rejected with `ERR_JURY_QUORUM_NOT_MET` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/jury_quorum_exact_boundary
    """
    market = create_market({"name": "M12", "season_code": "W26L", "jury_quorum": 3},
                           clock="2026-09-15T00:00:00Z")
    vendor = create_vendor_entity(legal_name="V12", category="HOME_GOODS")
    # Exactly quorum - 1 = 2 scores: one below the boundary.
    app = create_under_jury_application(market["id"], vendor["id"],
                                        scores=[70, 70], juror_prefix="juror-m12")
    res = decide_application(market["id"], app["id"], "ACCEPTED")
    validate_error(res, "ERR_JURY_QUORUM_NOT_MET", expected_status=409)


def test_decide_at_exact_quorum_succeeds(api):
    """PRD §3.3: "When at least `jury_quorum` scores have been recorded, a
    `JuryChair` may decide the application by providing `decision` (one of
    `ACCEPTED`, `REJECTED`, or `WAITLISTED`) and `expected_application_version`."
    PRD §3.3: "On `ACCEPTED`, the market's `total_accepted_vendors` increments by
    1, and if the vendor's `status` is currently `PROSPECT`, it transitions to
    `APPROVED`."

    Design: Difficulty/boundary_precision_check/jury_quorum_exact_boundary
    """
    market = create_market({"name": "M12B", "season_code": "W26L2", "jury_quorum": 3},
                           clock="2026-09-15T00:00:00Z")
    vendor = create_vendor_entity(legal_name="V12B", category="HOME_GOODS")
    # Exactly quorum = 3 scores: at the boundary, decide must succeed.
    app = create_under_jury_application(market["id"], vendor["id"],
                                        scores=[70, 70, 70], juror_prefix="juror-m12b")
    decided = validate_success(decide_application(market["id"], app["id"], "ACCEPTED"), 200)
    assert decided["status"] == "ACCEPTED"
    market_after = get_market(market["id"])
    assert market_after["total_accepted_vendors"] == 1


def _setup_category_at_cap(api):
    """Market with category_caps.CRAFT = 2, two CRAFT applications already
    ACCEPTED, and a third CRAFT application UNDER_JURY with average 80."""
    caps = {"FOOD_BEVERAGE": 5, "CRAFT": 2, "APPAREL": 5, "HOME_GOODS": 5,
            "EXPERIENCE": 5}
    market = create_market({"name": "M11", "season_code": "W26K", "jury_quorum": 3,
                            "category_caps": caps}, clock="2026-09-15T00:00:00Z")
    for i, name in enumerate(["V11A", "V11B"]):
        vendor = create_vendor_entity(legal_name=name, category="CRAFT")
        create_accepted_application(market["id"], vendor["id"],
                                    scores=[80, 80, 80],
                                    juror_prefix=f"juror-m11-{i}")
    vendor_c = create_vendor_entity(legal_name="V11C", category="CRAFT")
    app_c = create_under_jury_application(market["id"], vendor_c["id"],
                                          scores=[80, 80, 80],
                                          juror_prefix="juror-m11-c")
    return market, vendor_c, app_c


def test_decide_accepted_at_category_cap_rejected(api):
    """PRD §3.3: "An `ACCEPTED` decision requires that `jury_average` is at
    least 60, and that the number of already-accepted applications in the
    vendor's `category` is strictly below `category_caps[category]`; if the cap
    is reached, the attempt is rejected with `ERR_CATEGORY_CAP_REACHED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/category_cap_exact_boundary
    """
    market, _vendor_c, app_c = _setup_category_at_cap(api)
    # Boundary is >=: 2 already accepted >= cap 2, so a third ACCEPTED fails.
    res = decide_application(market["id"], app_c["id"], "ACCEPTED")
    validate_error(res, "ERR_CATEGORY_CAP_REACHED", expected_status=409)


def test_decide_waitlisted_at_category_cap_succeeds(api):
    """PRD §3.3: "A `WAITLISTED` decision requires that `jury_average` is at
    least 60 but the category cap has been reached."
    PRD §3.3: "On any decide, `decided_at` is set to the current UTC instant."

    Design: Difficulty/boundary_precision_check/category_cap_exact_boundary
    """
    market, _vendor_c, app_c = _setup_category_at_cap(api)
    decided = validate_success(decide_application(market["id"], app_c["id"], "WAITLISTED"),
                               200)
    assert decided["status"] == "WAITLISTED"
    assert decided.get("decided_at"), "decided_at must be set on decide"


def test_vendor_cannot_read_other_vendors_application(api):
    """PRD §2.1: "When `X-User-Role` is `VendorRole`, `X-User-ID` is the `id` of
    the acting `Vendor`; ownership checks on any resource that references a
    `Vendor` compare the resource's `vendor_id` foreign-key field to `X-User-ID`."

    Design: Corner/rbac/vendor_cannot_access_other_vendor_data
    """
    market = create_market({"name": "RM", "season_code": "RM-1"},
                           clock="2026-09-15T00:00:00Z")
    vendor_a = create_vendor_entity(legal_name="RVA")
    vendor_b = create_vendor_entity(legal_name="RVB")
    app_b = create_draft_application(market["id"], vendor_b["id"])

    res = api.get_application(market["id"], app_b["id"],
                              make_vendor_headers(vendor_a["id"]))
    # PRD does not pin whether an ownership failure surfaces as 403 or 404.
    from test_helpers import validate_error_is_one_of
    validate_error_is_one_of(res, ["ERR_UNAUTHORIZED", "ERR_NOT_FOUND"])


def test_finance_officer_cannot_score_applications(api):
    """PRD §2.1: "A request whose role is not permitted for the target endpoint
    is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: POST /markets/{marketId}/applications/{applicationId}/score is
    authorized for `JuryMember` only.

    Design: Corner/rbac/finance_officer_cannot_score_applications
    """
    market = create_market({"name": "RM2", "season_code": "RM2-1"},
                           clock="2026-09-15T00:00:00Z")
    vendor = create_vendor_entity(legal_name="RV2")
    app = create_submitted_application(market["id"], vendor["id"])
    res = api.score_application(market["id"], app["id"], {"score_0_100": 80}, FINANCE)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)

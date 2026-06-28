"""Catalog governance (programs, items, plans, CE bundles) and CE credit accrual.

Covers difficulty queue (A): compensating_invariant (CE credit conservation),
and corner queue (B): entity creation/defaults/computed/system fields, program
publish/retire transitions and preconditions, CE filtering, CE regression.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_active_enrollment,
    create_program, create_published_program, create_plan, create_bundle,
    create_learner, create_enrollment, activate, add_item, publish_program,
    create_license_program_payload, create_subscription_plan_payload,
    create_question_item_payload, create_ce_bundle_payload, create_ce_award_payload,
    make_learner_headers,
)

ADMIN = TEST_USERS["content_admin_headers"]


# ==========================================================================
# compensating_invariant / ce_credit_accrual_conserves_bundle_total
# ==========================================================================
def test_ce_credit_accrual_conserves_bundle_total(api):
    """Three cumulative CE awards (modules 1,2,5 of a 5-module/24-credit bundle) conserve to 24.

    PRD §3.7: "The `cumulative_credits` for an award is the bundle's `ce_credits_total`
    multiplied by the award's `modules_completed`, divided by the bundle's `modules_total`,
    rounded half up to a whole credit."
    PRD §3.7: "The `credits_awarded` by this particular award is its cumulative credits minus
    the cumulative credits of the most recent prior award (ordered by `modules_completed`),
    or minus zero when there is no prior award."
    PRD §3.7: "when `modules_completed` finally reaches `modules_total` the sum of all
    `credits_awarded` equals the bundle's `ce_credits_total` exactly."

    Design: Difficulty/compensating_invariant/ce_credit_accrual_conserves_bundle_total
    """
    prog = create_published_program("CE-PROG", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    bundle = create_bundle(prog["id"], ce_credits_total=24, modules_total=5)
    plan = create_plan(tier="PLUS", total_price_cents=50000, included_mock_credits=5, includes_ce=True)
    learner = create_learner(email="ce@x.com", full_name="CE Learner")
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=False, ce_bundle_id=bundle["id"])
    activate(enr["id"], learner["id"])
    lh = make_learner_headers(learner["id"])

    a1 = validate_success(api.create_ce_award(enr["id"], create_ce_award_payload(modules_completed=1), lh), 201)
    a2 = validate_success(api.create_ce_award(enr["id"], create_ce_award_payload(modules_completed=2), lh), 201)
    a3 = validate_success(api.create_ce_award(enr["id"], create_ce_award_payload(modules_completed=5), lh), 201)

    # cumulative: round(24*1/5)=5, round(24*2/5)=10, round(24*5/5)=24
    assert a1["credits_awarded"] == 5, f"award1 expected 5, got {a1['credits_awarded']}"
    assert a2["credits_awarded"] == 5, f"award2 expected delta 5, got {a2['credits_awarded']}"
    assert a3["cumulative_credits"] == 24
    assert a3["credits_awarded"] == 14, f"award3 expected delta 14, got {a3['credits_awarded']}"
    assert a1["credits_awarded"] + a2["credits_awarded"] + a3["credits_awarded"] == 24


def test_ce_award_cumulative_credits_round_half_up(api):
    """Each CE award's cumulative_credits is the rounded-half-up proportional total.

    PRD §3.7: "The `cumulative_credits` for an award is the bundle's `ce_credits_total`
    multiplied by the award's `modules_completed`, divided by the bundle's `modules_total`,
    rounded half up to a whole credit."

    Design: Difficulty/compensating_invariant/ce_credit_accrual_conserves_bundle_total
    """
    prog = create_published_program("CE-PROG2", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    bundle = create_bundle(prog["id"], ce_credits_total=24, modules_total=5)
    plan = create_plan(tier="PLUS", total_price_cents=50000, included_mock_credits=5, includes_ce=True)
    learner = create_learner(email="ce2@x.com", full_name="CE2")
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=False, ce_bundle_id=bundle["id"])
    activate(enr["id"], learner["id"])
    lh = make_learner_headers(learner["id"])
    a1 = validate_success(api.create_ce_award(enr["id"], create_ce_award_payload(modules_completed=1), lh), 201)
    # round(24*1/5) = round(4.8) = 5
    assert a1["cumulative_credits"] == 5, f"cumulative expected 5, got {a1['cumulative_credits']}"
    a2 = validate_success(api.create_ce_award(enr["id"], create_ce_award_payload(modules_completed=2), lh), 201)
    # round(24*2/5) = round(9.6) = 10
    assert a2["cumulative_credits"] == 10


# ==========================================================================
# Corner / entities
# ==========================================================================
def test_create_license_program_returns_201_draft(api):
    """Creating a license program returns 201 with status DRAFT and the supplied fields.

    PRD §3.1: "A freshly created program is in `DRAFT` status."

    Design: Corner/entities/create_license_program_returns_201_with_fields
    """
    data = validate_success(
        api.create_license_program(
            create_license_program_payload(license_code="C-CREATE", title="Create",
                                           passing_scaled_score=75,
                                           domain_weights=[{"domain_code": "A", "weight": 1.00}]),
            ADMIN), 201)
    assert data["status"] == "DRAFT"
    assert data["license_code"] == "C-CREATE"
    assert data["passing_scaled_score"] == 75


def test_create_plan_defaults_to_active(api):
    """A subscription plan created without an explicit status defaults to ACTIVE.

    PRD §3.1: "A new plan is `ACTIVE`; archiving it moves it to `ARCHIVED`, after which it
    rejects new enrollments."

    Design: Corner/entities/plan_default_status_active
    """
    data = validate_success(api.create_subscription_plan(create_subscription_plan_payload(), ADMIN), 201)
    assert data["status"] == "ACTIVE"


def test_enrollment_system_fields_minted(api):
    """The server mints version=1, status=DRAFT, and created_at on enrollment create.

    PRD §3.2: "A new enrollment begins in `DRAFT` status with `exam_outcome` of `PENDING`."
    PRD §2.4: "an integer `version` that begins at 1 on creation and increments by one on
    each subsequent mutation."

    Design: Corner/entities/enrollment_system_fields_generated
    """
    prog = create_program("SF", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    plan = create_plan(tier="BASIC", total_price_cents=30000)
    learner = create_learner(email="sf@x.com", full_name="SF")
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=False)
    assert enr["version"] == 1
    assert enr["status"] == "DRAFT"
    assert enr["created_at"]


def test_create_plan_missing_required_field_invalid_request(api):
    """Omitting required total_price_cents on plan create returns ERR_INVALID_REQUEST.

    PRD §2.5: "fifth, well-formedness of the request body — required fields present, enum
    values legal, numeric ranges respected (`ERR_INVALID_REQUEST`)"

    Design: Corner/entities/create_plan_missing_required_field_returns_invalid_request
    """
    payload = create_subscription_plan_payload()
    payload.pop("total_price_cents")
    resp = api.create_subscription_plan(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_plan_invalid_tier_enum_rejected(api):
    """A plan with tier=GOLD (not BASIC|PLUS|PRO) returns ERR_INVALID_REQUEST.

    PRD §2.5: "fifth, well-formedness of the request body — required fields present, enum
    values legal, numeric ranges respected (`ERR_INVALID_REQUEST`)"

    Design: Corner/entities/create_plan_invalid_tier_enum_rejected
    """
    resp = api.create_subscription_plan(create_subscription_plan_payload(tier="GOLD"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_nonexistent_enrollment_not_found(api):
    """Fetching a random enrollment id returns ERR_NOT_FOUND.

    PRD §2.5: "third, existence of every resource named in the path or body, validated
    left-to-right along the path (`ERR_NOT_FOUND`)"

    Design: Corner/entities/get_nonexistent_enrollment_returns_not_found
    """
    resp = api.get_enrollment("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_get_enrollment_by_id_returns_stored_entity(api):
    """Fetching a created enrollment returns it with status DRAFT.

    PRD §3.2: "A new enrollment begins in `DRAFT` status with `exam_outcome` of `PENDING`."

    Design: Corner/entities/get_enrollment_by_id_returns_stored_entity
    """
    prog = create_program("C-GET", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    plan = create_plan(tier="BASIC", total_price_cents=30000)
    learner = create_learner(email="g@x.com", full_name="G")
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=False)
    data = validate_success(api.get_enrollment(enr["id"], make_learner_headers(learner["id"])))
    assert data["id"] == enr["id"]
    assert data["status"] == "DRAFT"


def test_list_license_programs_paginated_envelope(api):
    """Listing license programs returns an array envelope with pagination fields.

    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and `has_more`
    in the `meta` object of the envelope."

    Design: Corner/entities/list_license_programs_paginated_envelope
    """
    create_program("L-1", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    create_program("L-2", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    data, meta = validate_paginated(api.list_license_programs(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] >= 2
    assert len(data) == 1
    assert meta["has_more"] is True


def test_question_item_immutable_no_version(api):
    """A created question item carries no version field and is read back via the items list.

    PRD §2.4: "A question item has no `updated_at` and no `version` — its `correct_choice`
    and other content fields are fixed once written, so there is nothing to re-version."

    Design: Corner/entities/question_item_immutable_no_version
    """
    prog = create_program("QI", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    item = validate_success(api.add_question_item(prog["id"], create_question_item_payload(), ADMIN), 201)
    data, _ = validate_paginated(api.list_question_items(prog["id"], ADMIN))
    ids = [i["id"] for i in data]
    assert item["id"] in ids
    listed = next(i for i in data if i["id"] == item["id"])
    assert "version" not in listed, "QuestionItem must not carry a version field"


def test_item_domain_not_in_blueprint_rejected(api):
    """Adding an item whose domain_code is outside the blueprint returns ERR_REFERENCE_INCOMPATIBLE.

    PRD §3.1: "A question item's `domain_code` that is not among the program's blueprint
    codes is a referential mismatch and is rejected with `ERR_REFERENCE_INCOMPATIBLE`."

    Design: Corner/entities/item_domain_not_in_blueprint_rejected
    """
    prog = create_program("ITDOM", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    resp = api.add_question_item(prog["id"], create_question_item_payload(domain_code="Z"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_REFERENCE_INCOMPATIBLE.value)


def test_ce_bundle_filtered_list_by_program(api):
    """Listing CE bundles by license_program_id returns only that program's bundles.

    PRD §3.1: "Bundles can be listed and filtered by `license_program_id`, which is the
    reverse path from a program to its bundles"

    Design: Corner/entities/ce_bundle_fk_filtered_list_reverse_reachable
    """
    prog = create_program("CEB", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    bundle = create_bundle(prog["id"], ce_credits_total=12, modules_total=4)
    data, _ = validate_paginated(api.list_ce_bundles(ADMIN, params={"license_program_id": prog["id"]}))
    assert all(b["license_program_id"] == prog["id"] for b in data)
    assert bundle["id"] in [b["id"] for b in data]


# ==========================================================================
# Corner / state_machines (program lifecycle)
# ==========================================================================
def test_publish_program_draft_to_published(api):
    """Publishing a DRAFT program with one item and valid weights advances to PUBLISHED, version 2.

    PRD §3.1: "Publishing a `DRAFT` program advances it to `PUBLISHED` and increments the
    program's `version`."

    Design: Corner/state_machines/publish_program_initial_to_published
    """
    prog = create_program("PUB", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    add_item(prog["id"], domain_code="A")
    published = validate_success(api.publish_license_program(prog["id"], ADMIN))
    assert published["status"] == "PUBLISHED"
    assert published["version"] == 2


def test_publish_program_with_no_items_rejected(api):
    """Publishing a program with zero items returns ERR_PROGRAM_HAS_NO_ITEMS.

    PRD §3.1: "at least one question item must exist for the program; a program with an
    empty bank is rejected with `ERR_PROGRAM_HAS_NO_ITEMS`."

    Design: Corner/state_machines/publish_program_with_no_items_rejected
    """
    prog = create_program("NOITEM", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    resp = api.publish_license_program(prog["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_HAS_NO_ITEMS.value)
    refetched = validate_success(api.get_license_program(prog["id"], ADMIN))
    assert refetched["status"] == "DRAFT"


def test_activate_materializes_study_plan_domains(api):
    """Activating a 3-domain enrollment materializes 3 domains each at mastery 50 with the weights.

    PRD §3.3: "It materializes one **study-plan domain** for each entry in the program's
    `domain_weights`, copying the `domain_code` and `weight` onto each `StudyPlanDomain` and
    setting its initial `mastery` to 50."

    Design: Corner/state_machines/activate_enrollment_materializes_study_plan_domains
    """
    ctx = setup_active_enrollment(
        license_code="SPD",
        domain_weights=[{"domain_code": "A", "weight": 0.50},
                        {"domain_code": "B", "weight": 0.30},
                        {"domain_code": "C", "weight": 0.20}],
        learner_email="spd@x.com",
    )
    enr, learner = ctx["enrollment"], ctx["learner"]
    assert enr["status"] == "ACTIVE"
    data, meta = validate_paginated(api.list_domains(enr["id"], make_learner_headers(learner["id"])))
    assert meta["total_count"] == 3
    by_code = {d["domain_code"]: d for d in data}
    assert all(d["mastery"] == 50 for d in data)
    assert abs(by_code["A"]["weight"] - 0.50) < 1e-9
    assert abs(by_code["B"]["weight"] - 0.30) < 1e-9
    assert abs(by_code["C"]["weight"] - 0.20) < 1e-9


def test_retire_program_with_active_enrollment_blocked(api):
    """Retiring a program with an ACTIVE enrollment returns ERR_PROGRAM_HAS_ACTIVE_ENROLLMENTS.

    PRD §3.1: "Retiring a program moves it from `PUBLISHED` to `RETIRED` and increments its
    `version`, but only when no enrollment that references the program is currently in
    `ACTIVE` status; if any active enrollment still depends on it, the retire is rejected
    with `ERR_PROGRAM_HAS_ACTIVE_ENROLLMENTS`."

    Design: Corner/state_machines/retire_program_with_active_enrollment_blocked
    """
    ctx = setup_active_enrollment(license_code="RET", learner_email="ret@x.com")
    prog = ctx["program"]
    resp = api.retire_license_program(prog["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_HAS_ACTIVE_ENROLLMENTS.value)
    refetched = validate_success(api.get_license_program(prog["id"], ADMIN))
    assert refetched["status"] == "PUBLISHED"


# ==========================================================================
# Corner / validations (CE / cross-entity)
# ==========================================================================
def test_ce_award_module_regression_rejected(api):
    """A CE award whose modules_completed does not strictly increase returns ERR_CE_MODULE_REGRESSION.

    PRD §3.7: "must be strictly greater than the `modules_completed` of the prior award for
    the enrollment; an award whose module count does not strictly increase, or that exceeds
    the bundle total, is rejected with `ERR_CE_MODULE_REGRESSION`."

    Design: Corner/validations/ce_award_module_regression_rejected
    """
    prog = create_published_program("CER", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    bundle = create_bundle(prog["id"], ce_credits_total=20, modules_total=5)
    plan = create_plan(tier="PLUS", total_price_cents=50000, included_mock_credits=5, includes_ce=True)
    learner = create_learner(email="cer@x.com", full_name="CER")
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=False, ce_bundle_id=bundle["id"])
    activate(enr["id"], learner["id"])
    lh = make_learner_headers(learner["id"])
    validate_success(api.create_ce_award(enr["id"], create_ce_award_payload(modules_completed=2), lh), 201)
    resp = api.create_ce_award(enr["id"], create_ce_award_payload(modules_completed=2), lh)
    validate_error(resp, ApiErrorId.ERR_CE_MODULE_REGRESSION.value)


def test_enrollment_ce_bundle_program_mismatch_rejected(api):
    """An enrollment whose ce_bundle belongs to another program returns ERR_REFERENCE_INCOMPATIBLE.

    PRD §3.2: "if the plan bundles CE the supplied `ce_bundle_id`'s `license_program_id`
    must match the enrollment's program, and any CE bundle whose program differs from the
    enrollment's program is rejected with `ERR_REFERENCE_INCOMPATIBLE`."

    Design: Corner/validations/enrollment_create_ce_bundle_program_mismatch_rejected
    """
    p1 = create_program("M-P1", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    p2 = create_program("M-P2", [{"domain_code": "A", "weight": 1.00}], passing_scaled_score=70)
    bundle = create_bundle(p2["id"], ce_credits_total=12, modules_total=4)
    plan = create_plan(tier="PLUS", total_price_cents=50000, included_mock_credits=5, includes_ce=True)
    learner = create_learner(email="mm@x.com", full_name="MM")
    resp = api.create_enrollment(
        {"learner_id": learner["id"], "license_program_id": p1["id"], "subscription_plan_id": plan["id"],
         "financed": False, "ce_bundle_id": bundle["id"]},
        make_learner_headers(learner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_INCOMPATIBLE.value)

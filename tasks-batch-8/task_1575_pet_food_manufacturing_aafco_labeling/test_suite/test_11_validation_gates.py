"""Validation gates: auth, existence ordering, business-rule errors, uniqueness
(PRD §2.1, §2.10, §3)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    brand_owner_payload,
    build_user_headers,
    create_brand_owner,
    create_formula,
    create_ingredient,
    create_pairing,
    create_production_batch,
    create_supplier,
    formula_payload,
    get_batch,
    get_brand,
    get_formula,
    get_registration,
    ingredient_payload,
    lot_payload,
    nutrient_profile_payload,
    setup_batch_in_state,
    setup_draft_formula,
    setup_locked_formula,
    setup_registration,
    trial_protocol_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_undeclared_role_fails_unauthenticated(api):
    """PRD §2.1: "A request that is missing either header, presents malformed
    headers, or names a role outside this declared set is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/undeclared_role_fails_unauthenticated
    """
    resp = api.create_brand_owner(
        brand_owner_payload(), build_user_headers("some-user", "UndeclaredRole")
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_authorization_checked_before_existence(api, line_operator_headers, qa_approver_headers):
    """PRD §2.10: "First, authentication: both identity headers must be present
    and the role must be one of the nine declared roles, else
    `ERR_UNAUTHENTICATED`. Second, authorization: the role must be permitted for
    the endpoint, else `ERR_UNAUTHORIZED_ROLE`. Third, existence: every path
    identifier and foreign-key body field must resolve, checked left to right,
    else `ERR_NOT_FOUND`."

    Design: Corner/validations/authorization_checked_before_existence
    """
    forbidden = api.lock_formula(NON_EXISTENT_UUID, line_operator_headers)
    validate_error(forbidden, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)
    missing = api.lock_formula(NON_EXISTENT_UUID, qa_approver_headers)
    validate_error(missing, ApiErrorId.ERR_NOT_FOUND.value)


def test_batch_release_blocked_after_pairing_revocation(
    api, qa_approver_headers, production_planner_headers
):
    """PRD §3.5: "Third, sourcing coverage: for every ingredient line there must
    exist at least one `APPROVED` pairing whose supplier is itself currently
    `APPROVED`. When no approved pairing exists for an ingredient the rejection
    is `ERR_UNAPPROVED_INGREDIENT_SOURCE`"
    PRD §3.2: the revoke cascade pushes back "every formula sitting in
    `NUTRIENT_REVIEW` that includes the revoked ingredient and is now left
    without any `APPROVED` pairing covering that ingredient" — a LOCKED formula
    is not in NUTRIENT_REVIEW.

    Design: Corner/validations/batch_release_blocked_after_pairing_revocation
    """
    ctx = setup_locked_formula()
    validate_success(api.revoke_pairing(ctx["pairing"]["id"], qa_approver_headers))
    assert get_formula(ctx["formula"]["id"])["status"] == "LOCKED"

    batch = create_production_batch(ctx["formula"]["id"], line_id="LINE-V1")
    resp = api.release_batch(batch["id"], production_planner_headers)
    validate_error(resp, ApiErrorId.ERR_UNAPPROVED_INGREDIENT_SOURCE.value)
    assert get_batch(batch["id"])["status"] == "SCHEDULED"


def test_substantiation_fails_with_deficient_profile(
    api, qa_approver_headers, formulation_scientist_headers
):
    """PRD §3.3: "Second, the adequacy-basis gate, whose failure is
    `ERR_SUBSTANTIATION_UNMET` (HTTP 422): a `FORMULATION`-basis formula must
    have a nutrient profile whose `aafco_compliance` is `COMPLIANT`, while a
    `FEEDING_TRIAL`-basis formula must have a trial protocol whose status is
    `PASSED`."
    PRD §3.3: "For an adult dog the floors are 18.0 percent protein, 5.5 percent
    fat, 0.6 percent calcium, and 0.5 percent phosphorus"

    Design: Corner/validations/substantiation_fails_with_deficient_profile
    """
    # Full APPROVED pairing coverage, but protein 10.0 is below the 18.0 floor.
    ctx = setup_draft_formula(with_line=True)
    supplier = create_supplier(approve=True)
    create_pairing(supplier["id"], ctx["ingredient"]["id"], approve=True)
    profile = validate_success(
        api.create_nutrient_profile(
            ctx["formula"]["id"],
            nutrient_profile_payload(crude_protein_min_pct=10.0),
            formulation_scientist_headers,
        ),
        expected_status=201,
    )
    assert profile["aafco_compliance"] == "DEFICIENT"

    submitted = validate_success(
        api.submit_nutrient_review(ctx["formula"]["id"], formulation_scientist_headers)
    )
    assert submitted["status"] == "NUTRIENT_REVIEW"
    resp = api.substantiate_formula(ctx["formula"]["id"], qa_approver_headers)
    validate_error(resp, ApiErrorId.ERR_SUBSTANTIATION_UNMET.value)
    assert get_formula(ctx["formula"]["id"])["status"] == "NUTRIENT_REVIEW"


def test_lot_best_by_must_postdate_production_date(api, line_operator_headers):
    """PRD §3.5: "The best-by date must fall strictly after the batch's
    production date; a best-by date equal to the production date — or earlier —
    is rejected with `ERR_BEST_BY_INVALID` (HTTP 422)."

    Design: Corner/validations/lot_best_by_must_postdate_production_date
    """
    ctx = setup_batch_in_state(
        "COMPLETED", planned_kg=300.0, line_id="LINE-B1",
        scheduled_start="2026-08-27T08:00:00Z",
    )
    batch_id = ctx["batch"]["id"]

    equal_day = api.create_lot(
        batch_id, lot_payload(best_by_date="2026-08-27T00:00:00Z"), line_operator_headers
    )
    validate_error(equal_day, ApiErrorId.ERR_BEST_BY_INVALID.value)

    ok = validate_success(
        api.create_lot(
            batch_id, lot_payload(best_by_date="2027-08-27T00:00:00Z"), line_operator_headers
        ),
        expected_status=201,
    )
    assert ok["status"] == "ACTIVE"


def test_registration_approve_blocked_by_stale_label_revision(api, state_regulator_headers):
    """PRD §3.7: "the `label_revision_ref` under review must still equal the
    formula's current `revision_number`, else `ERR_LABEL_REVISION_STALE`
    (HTTP 422), because an approval issued against a superseded label revision
    would pin the wrong baseline"

    Design: Corner/validations/registration_approve_blocked_by_stale_label_revision
    """
    ctx = setup_registration(target_state="UNDER_REVIEW", state_code="GA", label_revision_ref=99)
    version = get_formula(ctx["formula"]["id"])["version"]
    resp = api.approve_registration(
        ctx["registration"]["id"], {"expected_formula_version": version}, state_regulator_headers
    )
    validate_error(resp, ApiErrorId.ERR_LABEL_REVISION_STALE.value)
    assert get_registration(ctx["registration"]["id"])["status"] == "UNDER_REVIEW"


def test_duplicate_fein_fails(api, platform_admin_headers):
    """PRD §3.1: "Uniqueness is enforced platform-wide with `ERR_DUPLICATE_KEY`
    (HTTP 409): the `fein` across brand owners, the `fsma_facility_id` across
    suppliers, the `aafco_name` across ingredients, the `protocol_code` across
    feeding-trial protocols, the `formula_code` within each brand owner, and the
    `state_code` within each formula's registrations."

    Design: Corner/validations/duplicate_fein_fails
    """
    create_brand_owner(legal_name="Dup Co One", fein="553000060")
    resp = api.create_brand_owner(
        brand_owner_payload(legal_name="Dup Co Two", fein="553000060"), platform_admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY.value)


def test_duplicate_aafco_name_fails(api, formulation_scientist_headers):
    """PRD §3.1: "Uniqueness is enforced platform-wide with `ERR_DUPLICATE_KEY`
    (HTTP 409): the `fein` across brand owners, the `fsma_facility_id` across
    suppliers, the `aafco_name` across ingredients, the `protocol_code` across
    feeding-trial protocols, the `formula_code` within each brand owner, and the
    `state_code` within each formula's registrations."

    Design: Corner/validations/duplicate_aafco_name_fails
    """
    create_ingredient(aafco_name="Chicken Meal")
    resp = api.create_ingredient(
        ingredient_payload(aafco_name="Chicken Meal"), formulation_scientist_headers
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY.value)


def test_formula_code_unique_within_brand_only(api, formulation_scientist_headers):
    """PRD §3.1: "Uniqueness is enforced platform-wide with `ERR_DUPLICATE_KEY`
    (HTTP 409): the `fein` across brand owners, the `fsma_facility_id` across
    suppliers, the `aafco_name` across ingredients, the `protocol_code` across
    feeding-trial protocols, the `formula_code` within each brand owner, and the
    `state_code` within each formula's registrations."
    PRD §3.3: "a brand-scoped `formula_code` (unique within that brand)"

    Design: Corner/validations/formula_code_unique_within_brand_only
    """
    brand_a = create_brand_owner(legal_name="Scope A")
    brand_b = create_brand_owner(legal_name="Scope B")
    create_formula(brand_a["id"], formula_code="SC-001")

    dup = api.create_formula(
        brand_a["id"], formula_payload(formula_code="SC-001"), formulation_scientist_headers
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_KEY.value)

    other = validate_success(
        api.create_formula(
            brand_b["id"], formula_payload(formula_code="SC-001"), formulation_scientist_headers
        ),
        expected_status=201,
    )
    assert other["formula_code"] == "SC-001"


def test_duplicate_protocol_code_fails(api, trial_coordinator_headers):
    """PRD §3.1: "Uniqueness is enforced platform-wide with `ERR_DUPLICATE_KEY`
    (HTTP 409): the `fein` across brand owners, the `fsma_facility_id` across
    suppliers, the `aafco_name` across ingredients, the `protocol_code` across
    feeding-trial protocols, the `formula_code` within each brand owner, and the
    `state_code` within each formula's registrations."
    PRD §3.4: "Each protocol carries a `protocol_code` (the AAFCO protocol
    identifier, unique across all protocols)"

    Design: Corner/validations/duplicate_protocol_code_fails
    """
    brand = create_brand_owner()
    f1 = create_formula(brand["id"], adequacy_basis="FEEDING_TRIAL")
    f2 = create_formula(brand["id"], adequacy_basis="FEEDING_TRIAL")
    validate_success(
        api.create_trial_protocol(
            f1["id"], trial_protocol_payload(protocol_code="AAFCO-DP-001"),
            trial_coordinator_headers,
        ),
        expected_status=201,
    )
    resp = api.create_trial_protocol(
        f2["id"], trial_protocol_payload(protocol_code="AAFCO-DP-001"),
        trial_coordinator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY.value)


def test_basis_mismatch_profile_and_protocol_fail(
    api, formulation_scientist_headers, trial_coordinator_headers
):
    """PRD §3.3: "A profile may only exist for a formula whose `adequacy_basis`
    is `FORMULATION`; posting one for a `FEEDING_TRIAL`-basis formula is rejected
    with `ERR_PROFILE_BASIS_MISMATCH` (HTTP 422)."
    PRD §3.4: "Creation is permitted only for a formula whose `adequacy_basis` is
    `FEEDING_TRIAL`; attempting to create a protocol for a `FORMULATION`-basis
    formula is rejected with `ERR_PROFILE_BASIS_MISMATCH`."

    Design: Corner/validations/basis_mismatch_profile_and_protocol_fail
    """
    brand = create_brand_owner()
    f_form = create_formula(brand["id"], adequacy_basis="FORMULATION")
    f_trial = create_formula(brand["id"], adequacy_basis="FEEDING_TRIAL")

    protocol_on_formulation = api.create_trial_protocol(
        f_form["id"], trial_protocol_payload(), trial_coordinator_headers
    )
    validate_error(protocol_on_formulation, ApiErrorId.ERR_PROFILE_BASIS_MISMATCH.value)

    profile_on_trial = api.create_nutrient_profile(
        f_trial["id"], nutrient_profile_payload(), formulation_scientist_headers
    )
    validate_error(profile_on_trial, ApiErrorId.ERR_PROFILE_BASIS_MISMATCH.value)


def test_recall_with_empty_scope_fails(api, qa_approver_headers):
    """PRD §3.8: "an empty array places every non-terminal batch of the formula
    in scope. An initiation that finds no in-scope batches or lots at all is
    rejected with `ERR_RECALL_SCOPE_EMPTY` (HTTP 422)."

    Design: Corner/validations/recall_with_empty_scope_fails
    """
    ctx = setup_locked_formula()  # LOCKED formula, zero batches
    resp = api.create_recall_action(
        {
            "formula_id": ctx["formula"]["id"],
            "scope_batch_ids": [],
            "recall_class": "CLASS_III",
            "reason": "No production yet",
        },
        qa_approver_headers,
    )
    validate_error(resp, ApiErrorId.ERR_RECALL_SCOPE_EMPTY.value)
    assert get_formula(ctx["formula"]["id"])["open_recall_flag"] is False
    assert get_brand(ctx["brand"]["id"])["open_recall_count"] == 0


def test_ga_report_without_samples_fails(api, quality_analyst_headers):
    """PRD §3.6: "A `QualityAnalyst` generates the report; generation requires at
    least one recorded sample whose verdict is not `PENDING`, else
    `ERR_SAMPLE_PENDING` (HTTP 422)."

    Design: Corner/validations/ga_report_without_samples_fails
    """
    ctx = setup_batch_in_state("COMPLETED", planned_kg=350.0, line_id="LINE-N1")
    resp = api.create_ga_report(ctx["batch"]["id"], quality_analyst_headers)
    validate_error(resp, ApiErrorId.ERR_SAMPLE_PENDING.value)

    reports, meta = validate_paginated(
        api.list_ga_reports(ctx["batch"]["id"], quality_analyst_headers)
    )
    assert reports == []
    assert meta["total_count"] == 0

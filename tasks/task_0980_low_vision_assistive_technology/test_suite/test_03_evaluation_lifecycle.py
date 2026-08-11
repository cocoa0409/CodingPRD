"""Evaluations: revision cycle, OCC guard, supersede cascade, gating rules."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_client_payload, create_referral_payload, create_evaluation_payload,
    create_device_model_payload, create_device_unit_payload, create_device_order_payload,
    create_client, create_client_with_accepted_referral, create_evaluation,
    create_device_model, create_device_unit,
    TEST_USERS,
)

INTAKE = TEST_USERS["intake_coordinator_headers"]
SPECIALIST = TEST_USERS["vision_specialist_headers"]
ADMIN = TEST_USERS["clinic_admin_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]


def _setup_active_client_with_referral(api, name="Eve Pol", dob="1955-02-11"):
    c = get_success_data(api.create_client(create_client_payload(full_name=name, date_of_birth=dob), INTAKE))
    r = get_success_data(api.create_referral(
        create_referral_payload(c["id"], source_type="PHYSICIAN", referring_party="Dr. Noor"), INTAKE))
    get_success_data(api.decide_referral(r["id"], {"decision": "ACCEPT"}, INTAKE))
    return c, r


def test_evaluation_revision_cycle_reopens_and_refinalizes(api):
    """PRD §3.2: "Finalizing — allowed from `DRAFT` or `REVISED` — moves the
    evaluation to `FINALIZED`".
    PRD §3.2: "A `FINALIZED` evaluation can be reopened by the specialist's
    revise action, moving it `FINALIZED → REVISED` and optionally updating any of
    the four clinical fields in the same call."
    PRD §2.4: "`version` — an integer starting at 1 at creation and incremented
    by exactly 1 on every mutation".

    Design: Difficulty/non_linear_state_machine/nsm_evaluation_revision_cycle
    """
    c, r = _setup_active_client_with_referral(api)
    model = create_device_model(name="Magna 5x", category="MAGNIFIER", list_price_cents=25000)
    c_v = get_success_data(api.get_client(c["id"], SPECIALIST))["version"]
    ev = get_success_data(api.create_evaluation(create_evaluation_payload(
        c["id"], r["id"], c_v, acuity_score=45, contrast_score=50,
        field_loss_pct=35, recommended_category="MAGNIFIER"), SPECIALIST))
    assert ev["status"] == "DRAFT"
    fin = get_success_data(api.finalize_evaluation(ev["id"], SPECIALIST))
    assert fin["status"] == "FINALIZED"
    rev = get_success_data(api.revise_evaluation(ev["id"], {"acuity_score": 48}, SPECIALIST))
    assert rev["status"] == "REVISED"
    fin2 = get_success_data(api.finalize_evaluation(ev["id"], SPECIALIST))
    assert fin2["status"] == "FINALIZED"
    assert fin2["version"] == 4, f"one mutation per call: create/finalize/revise/finalize, got {fin2['version']}"


def test_evaluation_usable_for_orders_after_revision_cycle(api):
    """PRD §3.2: "From `REVISED` the evaluation can be finalized again, and the
    cycle may repeat until a newer evaluation for the client supersedes it."
    PRD §3.4: "The referenced evaluation must be `FINALIZED` — otherwise
    `ERR_EVALUATION_NOT_FINAL`".

    Design: Difficulty/non_linear_state_machine/nsm_evaluation_revision_cycle
    """
    c, r = _setup_active_client_with_referral(api)
    model = create_device_model(name="Magna 5x", category="MAGNIFIER", list_price_cents=25000)
    ev = create_evaluation(c["id"], r["id"], acuity_score=45, contrast_score=50,
                           field_loss_pct=35, recommended_category="MAGNIFIER")
    get_success_data(api.finalize_evaluation(ev["id"], SPECIALIST))
    get_success_data(api.revise_evaluation(ev["id"], {"acuity_score": 48}, SPECIALIST))
    get_success_data(api.finalize_evaluation(ev["id"], SPECIALIST))
    order = get_success_data(api.create_device_order(create_device_order_payload(
        c["id"], ev["id"], model["id"], fulfillment_type="PURCHASE"), SPECIALIST))
    assert order["status"] == "PLACED", "order accepted once the cycle closes back at FINALIZED"


def test_order_create_rejected_while_evaluation_draft(api):
    """PRD §3.4: "The referenced evaluation must be `FINALIZED` — otherwise
    `ERR_EVALUATION_NOT_FINAL`".

    Design: Difficulty/cross_entity_state_dependency/ce_order_requires_final_evaluation
    """
    c, r = _setup_active_client_with_referral(api, name="Kip Aldo", dob="1966-03-27")
    model = create_device_model(name="Magna 5x", category="MAGNIFIER", list_price_cents=25000)
    c_v = get_success_data(api.get_client(c["id"], SPECIALIST))["version"]
    ev = get_success_data(api.create_evaluation(create_evaluation_payload(
        c["id"], r["id"], c_v, acuity_score=60, contrast_score=60,
        field_loss_pct=20, recommended_category="MAGNIFIER"), SPECIALIST))
    resp = api.create_device_order(create_device_order_payload(
        c["id"], ev["id"], model["id"], fulfillment_type="PURCHASE"), SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_EVALUATION_NOT_FINAL)


def test_order_create_succeeds_once_evaluation_finalized(api):
    """PRD §3.4: "The referenced evaluation must be `FINALIZED` — otherwise
    `ERR_EVALUATION_NOT_FINAL`".
    PRD §3.4: "A new order is `PLACED`".

    Design: Difficulty/cross_entity_state_dependency/ce_order_requires_final_evaluation
    """
    c, r = _setup_active_client_with_referral(api, name="Kip Aldo", dob="1966-03-27")
    model = create_device_model(name="Magna 5x", category="MAGNIFIER", list_price_cents=25000)
    ev = create_evaluation(c["id"], r["id"], acuity_score=60, contrast_score=60,
                           field_loss_pct=20, recommended_category="MAGNIFIER")
    get_success_data(api.finalize_evaluation(ev["id"], SPECIALIST))
    order = get_success_data(api.create_device_order(create_device_order_payload(
        c["id"], ev["id"], model["id"], fulfillment_type="PURCHASE"), SPECIALIST))
    assert order["status"] == "PLACED"


def test_occ_stale_client_version_rejected(api):
    """PRD §2.9: "If the client's current `version` differs from
    `expected_client_version`, the creation is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."
    PRD §3.2: "creating an evaluation retires every existing draft-or-revised
    evaluation of the same client and increments the client's `version`".

    Design: Corner/complexity_layers/layer_occ_stale_version_rejected
    """
    c, r = _setup_active_client_with_referral(api, name="OCC Test", dob="1960-01-01")
    c_v = get_success_data(api.get_client(c["id"], SPECIALIST))["version"]
    assert c_v == 2
    e1 = get_success_data(api.create_evaluation(create_evaluation_payload(
        c["id"], r["id"], c_v, acuity_score=60, contrast_score=60,
        field_loss_pct=20, recommended_category="MAGNIFIER"), SPECIALIST))
    # Second create with the previously observed version: client version is now 3.
    resp = api.create_evaluation(create_evaluation_payload(
        c["id"], r["id"], c_v), SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    c_v2 = get_success_data(api.get_client(c["id"], SPECIALIST))["version"]
    assert c_v2 == 3
    e2 = get_success_data(api.create_evaluation(create_evaluation_payload(
        c["id"], r["id"], c_v2), SPECIALIST))
    assert e2["status"] == "DRAFT"
    e1_after = get_success_data(api.get_evaluation(e1["id"], SPECIALIST))
    assert e1_after["status"] == "SUPERSEDED", "fresh create supersedes the prior DRAFT"


def test_evaluation_starts_in_draft_version_one(api):
    """PRD §3.2: "A new evaluation starts in `DRAFT`."
    PRD §2.4: "`version` — an integer starting at 1 at creation".

    Design: Corner/state_machines/sm_evaluation_initial_state_draft
    """
    c, r = _setup_active_client_with_referral(api, name="Init State", dob="1960-01-01")
    c_v = get_success_data(api.get_client(c["id"], SPECIALIST))["version"]
    ev = get_success_data(api.create_evaluation(
        {"client_id": c["id"], "referral_id": r["id"], "expected_client_version": c_v},
        SPECIALIST))
    assert ev["status"] == "DRAFT"
    assert ev["version"] == 1


def test_evaluation_finalize_twice_rejected(api):
    """PRD §3.2: "Finalizing — allowed from `DRAFT` or `REVISED` — moves the
    evaluation to `FINALIZED`".
    PRD §2.7: "the target entity is in a state from which the requested
    transition exists; terminal states reject everything (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/sm_evaluation_finalize_twice_rejected
    """
    c, r = _setup_active_client_with_referral(api, name="Fin Twice", dob="1960-01-01")
    ev = create_evaluation(c["id"], r["id"], acuity_score=60, contrast_score=60,
                           field_loss_pct=20, recommended_category="MAGNIFIER")
    get_success_data(api.finalize_evaluation(ev["id"], SPECIALIST))
    resp = api.finalize_evaluation(ev["id"], SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_finalize_with_missing_category_rejected(api):
    """PRD §3.2: "attempting to finalize with any of `acuity_score`,
    `contrast_score`, `field_loss_pct`, or `recommended_category` still null is
    rejected with `ERR_ASSESSMENT_INCOMPLETE` (HTTP 422)."

    Design: Corner/validations/val_assessment_incomplete_eval_finalize
    """
    c, r = _setup_active_client_with_referral(api, name="Incomplete", dob="1960-01-01")
    # recommended_category must stay null: the factory default would otherwise
    # fill it with "MAGNIFIER", defeating the PRD §3.2 completeness check.
    ev = create_evaluation(c["id"], r["id"], acuity_score=60, contrast_score=60,
                           field_loss_pct=20, recommended_category=None)
    assert ev["recommended_category"] is None
    resp = api.finalize_evaluation(ev["id"], SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_INCOMPLETE)


def test_evaluation_against_undecided_referral_rejected(api):
    """PRD §3.2: "The referral must already be `ACCEPTED`, or creation fails
    with `ERR_REFERRAL_NOT_ACCEPTED`".

    Design: Corner/validations/val_referral_not_accepted_blocks_evaluation
    """
    c = get_success_data(api.create_client(
        create_client_payload(full_name="Ref Gate", date_of_birth="1960-01-01"), INTAKE))
    r = get_success_data(api.create_referral(
        create_referral_payload(c["id"], source_type="SELF", referring_party="self"), INTAKE))
    resp = api.create_evaluation(
        {"client_id": c["id"], "referral_id": r["id"], "expected_client_version": c["version"]},
        SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_ACCEPTED)

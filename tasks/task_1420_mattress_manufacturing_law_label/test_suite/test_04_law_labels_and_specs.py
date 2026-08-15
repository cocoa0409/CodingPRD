"""Law-label specs, label generation/approval/activation, pinning (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    assert_law_label,
    create_law_label_spec_payload,
    setup_certified_model,
    publish_spec,
    generate_label,
)

PM = TEST_USERS["plant_manager_headers"]
CO1 = TEST_USERS["compliance_creator_headers"]
CO2 = TEST_USERS["compliance_approver_headers"]


def test_label_activate_requires_approved_status(api):
    """PRD §3.4: "Activation moves `APPROVED` → `ACTIVE` under two regulatory
    preconditions, evaluated after the state check (`ERR_LABEL_NOT_APPROVED`
    for a label not in `APPROVED`): the pinned spec must still be `PUBLISHED`
    — a label pinned to a since-superseded spec is rejected with
    `ERR_SPEC_SUPERSEDED` — and the model must be `CERTIFIED` or `ACTIVE`
    (`ERR_MODEL_NOT_CERTIFIED`)."

    Design: Corner/state_machines/label_activate_from_generated_rejected
    """
    ctx = setup_certified_model()
    publish_spec(state_code="CA")
    label = generate_label(ctx["model"]["id"], "CA")
    assert label["status"] == "GENERATED"

    resp = api.activate_law_label(ctx["model"]["id"], label["id"], CO2)
    validate_error(resp, ApiErrorId.ERR_LABEL_NOT_APPROVED)


def test_label_generation_requires_published_spec(api):
    """PRD §3.4: "There must be a `PUBLISHED` spec for that state, otherwise
    the generation fails with `ERR_SPEC_NOT_PUBLISHED` (409)."

    Design: Corner/validations/label_generate_without_published_spec_rejected
    """
    ctx = setup_certified_model()
    # Spec exists only in DRAFT — a DRAFT spec is not PUBLISHED.
    get_success_data(api.create_law_label_spec(
        create_law_label_spec_payload(state_code="CA"), CO1
    ))
    model = get_success_data(api.get_model(ctx["model"]["id"], PM))
    resp = api.create_law_label(
        ctx["model"]["id"],
        {"state_code": "CA", "expected_model_version": model["version"]},
        CO1,
    )
    validate_error(resp, ApiErrorId.ERR_SPEC_NOT_PUBLISHED)


def test_label_activation_rejected_when_pinned_spec_superseded(api):
    """PRD §3.4: "the pinned spec must still be `PUBLISHED` — a label pinned
    to a since-superseded spec is rejected with `ERR_SPEC_SUPERSEDED`"
    PRD §3.4: "Publishing a spec moves `DRAFT` → `PUBLISHED` (a spec not in
    `DRAFT` answers `ERR_SPEC_NOT_DRAFT`) and simultaneously moves any other
    `PUBLISHED` spec for the same `state_code` to `SUPERSEDED`, so at most one
    spec per state is ever published."

    Design: Corner/validations/label_activate_with_superseded_spec_rejected
    """
    ctx = setup_certified_model()
    spec1 = publish_spec(state_code="CA", required_phrases=["PHRASE V1"])
    label = generate_label(ctx["model"]["id"], "CA")
    assert label["spec_id"] == spec1["id"]
    get_success_data(api.approve_law_label(ctx["model"]["id"], label["id"], CO2))

    # A second spec for CA supersedes the first at publish time.
    spec2 = publish_spec(state_code="CA", required_phrases=["PHRASE V2"],
                         prop65_warning_required=True)
    spec1_after = get_success_data(api.get_law_label_spec(spec1["id"], PM))
    assert spec1_after["status"] == "SUPERSEDED"

    resp = api.activate_law_label(ctx["model"]["id"], label["id"], CO2)
    validate_error(resp, ApiErrorId.ERR_SPEC_SUPERSEDED)

    reloaded = get_success_data(api.get_law_label(label["id"], PM))
    assert reloaded["spec_id"] == spec1["id"]
    assert reloaded["spec_id"] != spec2["id"]


def test_label_pin_retains_original_spec_after_republish(api):
    """PRD §3.4: "On success the label pins `spec_id` to that published spec
    and `spec_version` to the spec's version at generation time — a pin that
    never changes afterward — and renders `content_text` as the spec's
    `required_phrases` joined in order, followed by the intersection of the
    spec's `filling_content_codes` with the model BOM's `filling_content_code`
    values in BOM line creation order (`created_at` ascending), followed by
    the Prop 65 warning block if and only if the spec's
    `prop65_warning_required` is true."

    Design: Corner/complexity_layers/version_pinning_label_retains_original_spec
    """
    ctx = setup_certified_model()
    spec1 = publish_spec(state_code="CA", required_phrases=["PHRASE V1"])
    label = generate_label(ctx["model"]["id"], "CA")

    publish_spec(state_code="CA", required_phrases=["PHRASE V2"],
                 prop65_warning_required=True)

    reloaded = get_success_data(api.get_law_label(label["id"], CO1))
    assert_law_label(reloaded)
    assert reloaded["spec_id"] == spec1["id"], (
        "The pinned spec_id must keep referencing the spec published at generation"
    )
    assert "PHRASE V1" in reloaded["content_text"]
    assert "PHRASE V2" not in reloaded["content_text"]


def test_label_generation_rejected_on_stale_model_version(api):
    """PRD §2.7: "Generating a law label against a model requires
    `expected_model_version` matching the model's current `version`. Label
    generation itself bumps the model's version — the label's content derives
    from the BOM, so the model is the coherence boundary — and a generator
    holding a stale version has an out-of-date view of the BOM the label would
    be rendered from."
    PRD §2.7: "If that value does not equal the parent entity's current
    `version` at write time, the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)"

    Design: Corner/complexity_layers/occ_law_label_create_stale_model_version
    """
    ctx = setup_certified_model()
    publish_spec(state_code="CA")
    model = get_success_data(api.get_model(ctx["model"]["id"], PM))
    observed_version = model["version"]

    first = validate_success(api.create_law_label(
        ctx["model"]["id"],
        {"state_code": "CA", "expected_model_version": observed_version},
        CO1,
    ), expected_status=201)
    assert first["status"] == "GENERATED"

    stale = api.create_law_label(
        ctx["model"]["id"],
        {"state_code": "CA", "expected_model_version": observed_version},
        CO1,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)


def test_label_approval_by_creator_rejected_segregation(api):
    """PRD §2.9: "A law label may not be approved or rejected by the
    `X-User-ID` recorded as its `created_by_user_id`."
    PRD §2.9: "Each violation is rejected with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403); on success, the approver or certifier identity is stamped onto
    the resource (`approved_by_user_id` on certificates and labels,
    `certified_by_user_id` on batches)."

    Design: Corner/validations/label_approve_by_creator_segregation_rejected
    """
    ctx = setup_certified_model()
    publish_spec(state_code="CA")
    label = generate_label(ctx["model"]["id"], "CA")  # generated by co-1
    assert label["created_by_user_id"] == "co-1"

    own = api.approve_law_label(ctx["model"]["id"], label["id"], CO1)
    validate_error(own, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    other = validate_success(api.approve_law_label(ctx["model"]["id"], label["id"], CO2))
    assert other["status"] == "APPROVED"
    assert other["approved_by_user_id"] == "co-2"

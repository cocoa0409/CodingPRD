"""Provider templates, macros, and optimistic concurrency control."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_clinic, setup_provider,
    create_provider_template_payload, create_macro_payload,
    create_dictation_job_payload, add_sla_policy,
    make_provider_headers, TEST_USERS,
)

VENDOR = TEST_USERS["vendor_admin_headers"]


def test_template_create_occ_stale_then_fresh_supersedes(api):
    """PRD §2.7: "Creating a new template version for a provider requires the
    request to carry `expected_provider_version`, holding the `version` of that
    Provider as the client last observed it. If the provider's current
    `version` has advanced since that observation — for instance because
    another writer has just created a template for the same provider and work
    type, legitimately superseding the prior active one — the create is
    rejected with `ERR_STALE_PROVIDER_VERSION` (HTTP 412), preventing the
    client from acting on a stale view of the provider."
    PRD §3.2: "Exactly one template per provider-and-work-type pair is active
    at a time: creating a new template for a pair that already has an active
    one flips the prior template's `is_active` to false, and this supersession
    is a mutation of the provider itself — the provider's `version` increments
    by one."

    Design: Corner/cross_cutting_layers/template_create_occ_stale_then_fresh_supersedes
    """
    clinic = setup_clinic()
    provider = setup_provider(clinic["id"])
    v0 = provider["version"]
    headers = make_provider_headers(provider["id"])

    t1 = validate_success(api.create_provider_template(
        create_provider_template_payload(provider["id"], v0, name="T1",
                                         body_text="v1 body"),
        headers), 201)
    assert t1["is_active"] is True
    after_t1 = validate_success(api.get_provider(provider["id"], VENDOR))
    assert after_t1["version"] == v0 + 1, "each create increments version once"

    stale = api.create_provider_template(
        create_provider_template_payload(provider["id"], v0, name="T2",
                                         body_text="v2 body"),
        headers)
    validate_error(stale, ApiErrorId.ERR_STALE_PROVIDER_VERSION)
    templates = validate_success(api.list_provider_templates(provider["id"], VENDOR))
    assert len(templates) == 1, "the stale create created nothing"

    t2 = validate_success(api.create_provider_template(
        create_provider_template_payload(provider["id"], after_t1["version"],
                                         name="T2", body_text="v2 body"),
        headers), 201)
    assert t2["is_active"] is True
    after_t2 = validate_success(api.get_provider(provider["id"], VENDOR))
    assert after_t2["version"] == v0 + 2
    templates = validate_success(api.list_provider_templates(provider["id"], VENDOR))
    by_id = {t["id"]: t for t in templates}
    assert by_id[t1["id"]]["is_active"] is False, "T1 superseded by T2"
    assert by_id[t2["id"]]["is_active"] is True


def test_template_update_occ_version_increments(api):
    """PRD §2.7: "Updating an existing template's name or body likewise
    requires `expected_template_version`, holding the `version` of the
    ProviderTemplate as last observed. A mismatch with the template's current
    `version` is rejected with `ERR_STALE_TEMPLATE_VERSION` (HTTP 412)."
    PRD §3.2: "An existing template's `name` or `body_text` may be revised by
    its owning provider; either field may be omitted from the update, the
    template's `version` increments by one on success, and the update is
    OCC-guarded through `expected_template_version`."

    Design: Corner/cross_cutting_layers/template_update_occ_version_increments
    """
    clinic = setup_clinic()
    provider = setup_provider(clinic["id"])
    headers = make_provider_headers(provider["id"])
    t1 = validate_success(api.create_provider_template(
        create_provider_template_payload(provider["id"], provider["version"],
                                         name="T1", body_text="body"),
        headers), 201)
    v1 = t1["version"]

    updated = validate_success(api.update_provider_template(
        t1["id"], {"name": "T1-renamed", "expected_template_version": v1},
        headers))
    assert updated["version"] == v1 + 1
    assert updated["name"] == "T1-renamed"

    stale = api.update_provider_template(
        t1["id"], {"name": "T1-again", "expected_template_version": v1},
        headers)
    validate_error(stale, ApiErrorId.ERR_STALE_TEMPLATE_VERSION)
    templates = validate_success(api.list_provider_templates(provider["id"], VENDOR))
    assert templates[0]["name"] == "T1-renamed", "the stale update changed nothing"


def test_macro_duplicate_shortcut_conflict_then_reuse_after_archive(api):
    """PRD §3.2: "Among a provider's `ACTIVE` macros the `shortcut` must be
    unique — a duplicate create is rejected with
    `ERR_DUPLICATE_MACRO_SHORTCUT`. Archiving is a soft delete: the macro moves
    to `ARCHIVED`, disappears from default listings unless the caller passes
    `include_archived`, and its shortcut is freed for reuse in a new active
    macro."

    Design: Corner/validations/macro_duplicate_shortcut_conflict_then_reuse_after_archive
    """
    clinic = setup_clinic()
    provider = setup_provider(clinic["id"])
    headers = make_provider_headers(provider["id"])
    m1 = validate_success(api.create_macro(
        create_macro_payload(provider["id"], shortcut="sig",
                             expansion_text="Regards, Dr. P"),
        headers), 201)
    dup = api.create_macro(
        create_macro_payload(provider["id"], shortcut="sig",
                             expansion_text="other"),
        headers)
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_MACRO_SHORTCUT)
    validate_success(api.archive_macro(m1["id"], headers))
    m2 = validate_success(api.create_macro(
        create_macro_payload(provider["id"], shortcut="sig",
                             expansion_text="other"),
        headers), 201)
    assert m2["id"] != m1["id"], "the freed shortcut mints a new macro"
    assert m2["status"] == "ACTIVE"


def test_macro_soft_delete_filter_semantics(api):
    """PRD §3.2: "Archiving is a soft delete: the macro moves to `ARCHIVED`,
    disappears from default listings unless the caller passes
    `include_archived`, and its shortcut is freed for reuse in a new active
    macro."
    PRD §2.10: "a provider's templates and macros from the provider (macros
    defaulting to active ones only, with an `include_archived` query flag to
    include archived ones)"

    Design: Corner/cross_cutting_layers/macro_soft_delete_filter_semantics
    """
    clinic = setup_clinic()
    provider = setup_provider(clinic["id"])
    headers = make_provider_headers(provider["id"])
    m1 = validate_success(api.create_macro(
        create_macro_payload(provider["id"], shortcut="sig-a",
                             expansion_text="A"),
        headers), 201)
    m2 = validate_success(api.create_macro(
        create_macro_payload(provider["id"], shortcut="sig-b",
                             expansion_text="B"),
        headers), 201)

    archived = validate_success(api.archive_macro(m1["id"], headers))
    assert archived["status"] == "ARCHIVED"

    default_list = validate_success(api.list_provider_macros(provider["id"], VENDOR))
    assert [m["id"] for m in default_list] == [m2["id"]], (
        "archived macros vanish from the default list")

    full_list = validate_success(api.list_provider_macros(
        provider["id"], VENDOR, params={"include_archived": "true"}))
    assert len(full_list) == 2
    by_id = {m["id"]: m for m in full_list}
    assert by_id[m1["id"]]["status"] == "ARCHIVED"


def test_template_reference_mismatches_return_referential_errors(api):
    """PRD §3.3: "When a `template_id` is supplied, it must belong to the same
    provider as the job — otherwise `ERR_TEMPLATE_PROVIDER_MISMATCH` — and its
    work type must equal the job's `work_type`, otherwise
    `ERR_TEMPLATE_WORK_TYPE_MISMATCH`."

    Design: Corner/validations/template_reference_mismatches_return_referential_errors
    """
    clinic = setup_clinic()
    add_sla_policy(clinic["id"])
    p1 = setup_provider(clinic["id"], full_name="P One")
    p2 = setup_provider(clinic["id"], full_name="P Two")
    t1 = validate_success(api.create_provider_template(
        create_provider_template_payload(p1["id"], p1["version"], name="T1",
                                         body_text="body"),
        make_provider_headers(p1["id"])), 201)

    other_provider = api.create_dictation_job(
        create_dictation_job_payload(p2["id"], template_id=t1["id"]),
        make_provider_headers(p2["id"]))
    validate_error(other_provider, ApiErrorId.ERR_TEMPLATE_PROVIDER_MISMATCH)

    wrong_work_type = api.create_dictation_job(
        create_dictation_job_payload(p1["id"], work_type="OP_NOTE",
                                     template_id=t1["id"]),
        make_provider_headers(p1["id"]))
    validate_error(wrong_work_type, ApiErrorId.ERR_TEMPLATE_WORK_TYPE_MISMATCH)

    ok = api.create_dictation_job(
        create_dictation_job_payload(p1["id"], template_id=t1["id"]),
        make_provider_headers(p1["id"]))
    job = validate_success(ok, 201)
    assert job["template_id"] == t1["id"]

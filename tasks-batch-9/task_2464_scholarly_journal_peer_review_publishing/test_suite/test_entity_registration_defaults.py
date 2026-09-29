"""Registration surfaces: the configuration a journal is born with, and its editorial community."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import SYSTEM_ADMIN_HEADERS, api_client


def _create_journal_request(**overrides):
    payload = f.journal_payload(**overrides)
    return payload, api_client.create_journal(payload, SYSTEM_ADMIN_HEADERS)


def _patch_journal_request(journal_id, **overrides):
    return api_client.update_journal(
        journal_id, f.journal_update_payload(**overrides), SYSTEM_ADMIN_HEADERS
    )


def test_journal_creation_materialises_the_peer_review_defaults():
    """A journal registered with only a name and subject areas still carries the review policy.

    PRD: "Peer review is governed by `min_completed_reviews_for_decision`, the number of reviews that must be submitted in the current round before a decision may be issued, defaulting to 2 and never below 1; by `max_revision_rounds`, defaulting to 2 and never below 0; by `review_target_days`, the number of days from invitation to deadline, defaulting to 21 and never below 1; by `reminder_cadence_days`, the gap between chase-up reminders, defaulting to 7 and never below 1; by `max_reminders_per_invitation`, defaulting to 2 and never below 0; and by `reviewer_concurrent_window_limit`, defaulting to 3 and never below 1."

    Design: Corner/entities/journal_creation_returns_declared_config_defaults
    """
    journal = fx.create_journal()

    a.assert_fields(
        journal,
        min_completed_reviews_for_decision=2,
        max_revision_rounds=2,
        review_target_days=21,
        reminder_cadence_days=7,
        max_reminders_per_invitation=2,
        reviewer_concurrent_window_limit=3,
    )


def test_journal_creation_materialises_the_formatting_defaults():
    """The formatting policy a submission is screened against is defaulted at registration.

    PRD: "Formatting policy is set by `max_page_count`, defaulting to 30 and never below 1, by `max_figure_count`, defaulting to 10 and never below 0, and by `requires_data_availability_statement`, defaulting to true."

    Design: Corner/entities/journal_creation_returns_declared_config_defaults
    """
    journal = fx.create_journal()

    a.assert_fields(
        journal,
        max_page_count=30,
        max_figure_count=10,
        requires_data_availability_statement=True,
    )


def test_journal_creation_materialises_the_fee_defaults():
    """Every fee input of the invoice waterfall is present on a freshly registered journal.

    PRD: "Fee policy is set by `apc_base_cents`, the list article processing charge before any licence multiplier, defaulting to 180000 cents — one thousand eight hundred currency units — by `page_charge_cents_per_page`, defaulting to 4000 cents per charged page, and by `color_figure_charge_cents`, defaulting to 25000 cents per colour figure, each of the three never below 0."

    Design: Corner/entities/journal_creation_returns_declared_config_defaults
    """
    journal = fx.create_journal()

    a.assert_integer_cents(journal["apc_base_cents"], "apc_base_cents")
    a.assert_fields(
        journal,
        apc_base_cents=180000,
        page_charge_cents_per_page=4000,
        color_figure_charge_cents=25000,
    )


def test_journal_creation_materialises_the_production_defaults():
    """Embargo, changeover and proof policy are all defaulted at registration.

    PRD: "Production policy is set by `embargo_months`, defaulting to 12 and never below 0, by `typeset_changeover_buffer_days`, defaulting to 2 and never below 0, and by `max_proof_rounds`, defaulting to 2 and never below 1."

    Design: Corner/entities/journal_creation_returns_declared_config_defaults
    """
    journal = fx.create_journal()

    a.assert_fields(
        journal,
        embargo_months=12,
        typeset_changeover_buffer_days=2,
        max_proof_rounds=2,
    )


def test_journal_creation_starts_every_derived_quantity_at_zero():
    """Intake, publication and fee counters all begin empty on the first version of the row.

    PRD: "A newly registered journal starts every derived quantity at zero: `manuscript_intake_count`, `published_article_count`, `retracted_article_count`, `apc_receivable_cents` and `apc_waived_cents`."

    Design: Corner/entities/journal_creation_returns_declared_config_defaults
    """
    journal = fx.create_journal()

    a.assert_fields(
        journal,
        manuscript_intake_count=0,
        published_article_count=0,
        retracted_article_count=0,
    )
    a.assert_journal_ledgers(journal, apc_receivable_cents=0, apc_waived_cents=0)
    a.assert_mutable_record_fields(journal, expected_version=1)


def test_author_registration_defaults_to_high_band_and_no_institutional_agreement():
    """An author registered without fee attributes lands on the zero-discount branch.

    PRD: "An author is registered with a unique `email`, a `full_name`, an `affiliation`, a `country_income_band` defaulting to `HIGH` and drawn from `HIGH`, `UPPER_MIDDLE`, `LOWER_MIDDLE` and `LOW`, and an `institutional_agreement` boolean defaulting to false."

    Design: Corner/entities/author_defaults_income_band_high_and_no_institutional_agreement
    """
    author, _headers = fx.create_author()

    a.assert_fields(
        author, country_income_band="HIGH", institutional_agreement=False
    )
    a.assert_mutable_record_fields(author, expected_version=1)


def test_editor_registration_mints_its_own_identity_at_version_one():
    """The editor row's identifier, timestamps and version are all server-written.

    PRD: "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row — including mutations produced as a side effect of an operation addressed at some other resource."

    Design: Corner/entities/editor_system_id_timestamps_and_version_generated_input_ignored
    """
    journal = fx.create_journal()

    editor = fx.create_editor(journal["id"], role_level="HANDLING")

    a.assert_mutable_record_fields(editor, expected_version=1)
    a.assert_timestamp_with_millis(editor["created_at"])
    a.assert_timestamp_with_millis(editor["updated_at"])


def test_editor_registration_starts_active_with_no_assignments():
    """A handling editor is immediately assignable and carries an empty workload.

    PRD: "An editor's `status` defaults to `ACTIVE` and may be `ON_LEAVE`, which excludes them from assignment entirely, and their `max_concurrent_assignments` defaults to 3 and is never below 1."

    Design: Corner/entities/editor_system_id_timestamps_and_version_generated_input_ignored
    """
    journal = fx.create_journal()

    editor = fx.create_editor(journal["id"], role_level="HANDLING")

    a.assert_fields(
        editor,
        status="ACTIVE",
        max_concurrent_assignments=3,
        active_assignment_count=0,
        journal_id=journal["id"],
        role_level="HANDLING",
    )


def test_journal_create_read_and_list_agree_on_the_same_row():
    """The created representation, the single read and the collection all describe one journal.

    PRD: "Every endpoint that creates a new resource returns HTTP 201 with the created resource in the `data` field."

    Design: Corner/endpoints/journal_standard_crud_create_read_list_and_patch
    """
    payload, response = _create_journal_request(
        subject_areas=["ONCOLOGY", "CARDIOLOGY"], max_page_count=24
    )
    created = validate_success(response, expected_status=201)

    read = validate_success(api_client.get_journal(created["id"], SYSTEM_ADMIN_HEADERS))
    rows, meta = validate_paginated(api_client.list_journals(SYSTEM_ADMIN_HEADERS))

    a.assert_fields(
        read,
        id=created["id"],
        name=payload["name"],
        subject_areas=["ONCOLOGY", "CARDIOLOGY"],
        max_page_count=24,
        doi_prefix=created["doi_prefix"],
        min_completed_reviews_for_decision=created["min_completed_reviews_for_decision"],
        manuscript_intake_count=0,
        apc_receivable_cents=0,
    )
    assert meta["total_count"] == 1, f"Expected 1 journal, got {meta['total_count']}"
    assert [row["id"] for row in rows] == [created["id"]]
    assert rows[0]["name"] == payload["name"]


def test_journal_patch_changes_only_the_supplied_configuration_fields():
    """Two patched fields move; every other configuration field and counter stands still.

    PRD: "Configuration can be revised later, and only the fields supplied in the revision change; the others keep their stored values, and the journal's `version` advances by 1."

    Design: Corner/endpoints/journal_standard_crud_create_read_list_and_patch
    """
    payload, response = _create_journal_request(
        subject_areas=["ONCOLOGY", "CARDIOLOGY"], max_page_count=24
    )
    created = validate_success(response, expected_status=201)
    before = validate_success(api_client.get_journal(created["id"], SYSTEM_ADMIN_HEADERS))
    a.assert_fields(before, max_page_count=24, reminder_cadence_days=7)

    validate_success(
        _patch_journal_request(created["id"], max_page_count=18, reminder_cadence_days=5)
    )

    after = validate_success(api_client.get_journal(created["id"], SYSTEM_ADMIN_HEADERS))
    a.assert_fields(after, max_page_count=18, reminder_cadence_days=5, version=2)
    for untouched in (
        "name",
        "subject_areas",
        "doi_prefix",
        "consensus_mode",
        "min_completed_reviews_for_decision",
        "max_revision_rounds",
        "review_target_days",
        "max_figure_count",
        "requires_data_availability_statement",
        "apc_base_cents",
        "page_charge_cents_per_page",
        "color_figure_charge_cents",
        "embargo_months",
        "manuscript_intake_count",
        "apc_receivable_cents",
    ):
        assert after[untouched] == before[untouched], (
            f"Expected {untouched} to keep its stored value "
            f"{before[untouched]!r}, got {after[untouched]!r}"
        )
    assert after["name"] == payload["name"]

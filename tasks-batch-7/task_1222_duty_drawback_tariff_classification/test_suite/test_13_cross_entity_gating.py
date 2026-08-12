"""Cross-entity state dependencies: entry registration gated on CERTIFIED
classification; claim filing gated on ACTIVE client engagement."""
from test_helpers import ApiErrorId, add_classification, onboard_client, setup_draft_claim_with_line, submit_classification, certify_classification, TEST_USERS, validate_error, validate_success
from test_helpers.factories import create_import_entry_payload

ADMIN = TEST_USERS["firm_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
BROKER = TEST_USERS["broker_headers"]


def test_entry_registration_rejected_while_classification_is_draft(api):
    """PRD 3.3: "An `ImportEntry` is created with `client_id`, the
    `classification_id` it was entered under — which must reference a
    `CERTIFIED` classification belonging to the same client, otherwise
    `ERR_CLASSIFICATION_NOT_CERTIFIED` or `ERR_CROSS_CLIENT_REFERENCE`
    respectively — the CBP `entry_number`, which must be unique within the
    client (`ERR_DUPLICATE_ENTRY_NUMBER` on collision), the `entry_date` that
    anchors the five-year statutory filing clock, the `port_code`, the
    `line_quantity` of units (which must be positive), the
    `entered_value_cents`, and the `duty_paid_cents` actually paid including
    any trade-remedy surcharges."

    Design: Difficulty/cross_entity_state_dependency/entry_requires_certified_classification
    """
    client = onboard_client()
    cls = add_classification(client["id"])  # stays DRAFT

    res = api.create_import_entry(
        create_import_entry_payload(client["id"], cls["id"]), ANALYST
    )
    validate_error(res, ApiErrorId.ERR_CLASSIFICATION_NOT_CERTIFIED)


def test_entry_registration_succeeds_after_certification(api):
    """PRD 3.3: "An `ImportEntry` is created with `client_id`, the
    `classification_id` it was entered under — which must reference a
    `CERTIFIED` classification belonging to the same client, otherwise
    `ERR_CLASSIFICATION_NOT_CERTIFIED` or `ERR_CROSS_CLIENT_REFERENCE`
    respectively — the CBP `entry_number`, which must be unique within the
    client (`ERR_DUPLICATE_ENTRY_NUMBER` on collision), the `entry_date` that
    anchors the five-year statutory filing clock, the `port_code`, the
    `line_quantity` of units (which must be positive), the
    `entered_value_cents`, and the `duty_paid_cents` actually paid including
    any trade-remedy surcharges."

    Design: Difficulty/cross_entity_state_dependency/entry_requires_certified_classification
    """
    client = onboard_client()
    cls = add_classification(client["id"])

    res = api.create_import_entry(
        create_import_entry_payload(client["id"], cls["id"]), ANALYST
    )
    validate_error(res, ApiErrorId.ERR_CLASSIFICATION_NOT_CERTIFIED)

    submit_classification(cls["id"])
    certify_classification(cls["id"])

    entry = validate_success(
        api.create_import_entry(
            create_import_entry_payload(client["id"], cls["id"]), ANALYST
        ),
        201,
    )
    assert entry["status"] == "UNMATCHED"
    assert entry["drawback_eligible_duty_cents"] == 82500
    assert entry["unclaimed_duty_cents"] == 82500


def test_filing_blocked_while_client_is_suspended(api):
    """PRD 3.1: "While a client is in `SUSPENDED` or `TERMINATED`, two
    operations against that client are blocked with `ERR_CLIENT_NOT_ACTIVE`:
    creating a new drawback claim, and filing an existing one."

    Design: Difficulty/cross_entity_state_dependency/claim_filing_requires_active_client
    """
    ctx = setup_draft_claim_with_line(matched_quantity=40)

    validate_success(
        api.patch_client(ctx["client"]["id"], {"engagement_status": "SUSPENDED"}, ADMIN)
    )
    res = api.file_claim(ctx["claim"]["id"], BROKER)
    validate_error(res, ApiErrorId.ERR_CLIENT_NOT_ACTIVE)

    claim = validate_success(api.get_claim(ctx["claim"]["id"], ANALYST))
    assert claim["status"] == "DRAFT", "the blocked filing must leave the claim DRAFT"


def test_filing_unblocked_after_client_reactivation(api):
    """PRD 3.1: "From `ACTIVE`, a client may be placed into `SUSPENDED`, and
    from `SUSPENDED` it may be reactivated to `ACTIVE`."
    PRD 3.1: "While a client is in `SUSPENDED` or `TERMINATED`, two operations
    against that client are blocked with `ERR_CLIENT_NOT_ACTIVE`: creating a new
    drawback claim, and filing an existing one."

    Design: Difficulty/cross_entity_state_dependency/claim_filing_requires_active_client
    """
    ctx = setup_draft_claim_with_line(matched_quantity=40)

    validate_success(
        api.patch_client(ctx["client"]["id"], {"engagement_status": "SUSPENDED"}, ADMIN)
    )
    res = api.file_claim(ctx["claim"]["id"], BROKER)
    validate_error(res, ApiErrorId.ERR_CLIENT_NOT_ACTIVE)

    validate_success(
        api.patch_client(ctx["client"]["id"], {"engagement_status": "ACTIVE"}, ADMIN)
    )
    filed = validate_success(api.file_claim(ctx["claim"]["id"], BROKER))
    assert filed["status"] == "FILED"
    assert filed["claimed_duty_cents"] == 32670

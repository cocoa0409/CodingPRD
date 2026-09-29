"""The entity surface: creation shapes, reads, defaults and rejected inputs."""

from datetime import datetime

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures as fx
from test_helpers.api_errors import NOT_FOUND_ERRORS
from test_helpers.assertions import (
    assert_common_fields,
    assert_created_at_ascending,
    assert_decimal_equals,
    assert_field_values,
    assert_fields_null,
    assert_ids_equal,
    assert_millisecond_timestamp,
    assert_pagination_meta,
    assert_single_resource_meta,
    assert_success_envelope,
    assert_unchanged,
    assert_unit_ledger_conserved,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    INTAKE_HEADERS,
    OFFICER_HEADERS,
)

# The logical clock reads this before any client sets it, so a row written by a
# test that never touches the clock is stamped here.
STARTUP_CLOCK = "2026-08-01T00:00:00Z"
INTAKE_CLOCK = "2026-03-01T00:00:00Z"
ANALYSIS_CLOCK = "2026-03-02T00:00:00Z"

REGISTRY_ENTRY = {
    "model_code": "TOAST-X1",
    "brand": "Hearthline",
    "category": "KITCHEN_APPLIANCE",
    "units_distributed": 100,
    "units_registered": 60,
}

# One report per intake channel, so the same injury class can be sent through two
# different credibility multipliers.
RETAILER_REPORT = {
    "report_channel": "RETAILER",
    "incident_date": "2026-01-20T00:00:00Z",
    "narrative": "Retailer-channel report of a burn treated at urgent care.",
}

HOTLINE_REPORT = {
    "report_channel": "CONSUMER_HOTLINE",
    "incident_date": "2026-01-21T00:00:00Z",
    "narrative": "Hotline report of a burn treated at urgent care.",
}

UNTRIAGED_REPORT = {
    "report_channel": "WEB_FORM",
    "incident_date": "2026-02-10T00:00:00Z",
    "narrative": "Fresh web submission with no triage yet.",
}

TREATED_BURN = {
    "injury_class": "MEDICAL_TREATMENT",
    "hazard_code": "BURN",
    "injury_verified": True,
}

ANALYSIS_WINDOW = {
    "window_start": "2026-01-01T00:00:00Z",
    "window_end": "2026-02-28T00:00:00Z",
}

# The thirteen single-resource reads, in the order the not-found catalogue names
# their owning entities.
SINGLE_RESOURCE_GETTERS = (
    "get_product_model",
    "get_incident",
    "get_hazard_pattern",
    "get_evaluation",
    "get_section_report",
    "get_recall",
    "get_retailer",
    "get_retailer_notification",
    "get_audit_visit",
    "get_consumer_notice",
    "get_remedy_claim",
    "get_progress_report",
    "get_penalty_case",
)

UNKNOWN_ID_PROBES = tuple(zip(SINGLE_RESOURCE_GETTERS, NOT_FOUND_ERRORS))

DOCKET_SPINE_PROBES = UNKNOWN_ID_PROBES[:6]
RETAILER_CHANNEL_PROBES = UNKNOWN_ID_PROBES[6:9]
REMEDY_AND_PENALTY_PROBES = UNKNOWN_ID_PROBES[9:]


def _instant(value):
    """One ISO 8601 UTC instant, whatever fractional precision it carries."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _assert_same_instant(actual, expected):
    """A stored instant denotes exactly the expected moment."""
    assert _instant(actual) == _instant(expected), (
        f"expected the instant {expected}, got {actual}"
    )


def _assert_distinct_error_ids(seen):
    """No two entities may answer an unresolvable id with the same code."""
    assert len(set(seen)) == len(seen), f"error codes are not per entity: {seen}"


def _probe_unknown_ids(api, probes):
    """Read every named entity by an id that resolves to nothing."""
    seen = []
    for getter, expected_error_id in probes:
        response = getattr(api, getter)(NON_EXISTENT_UUID, headers=ADMIN_HEADERS)
        validate_error(response, expected_error_id, 404)
        seen.append(response.json()["data"]["error_id"])
    _assert_distinct_error_ids(seen)
    return seen


class TestProductModelRegistrationResponse:
    """The first call in the docket must answer with the whole row."""

    def test_registration_returns_the_five_inputs_and_both_computed_postures(
        self, api
    ):
        """A registered model echoes every declared input and its containment gate.

        The contract states: "A `ProgramAdmin` registers a product model by
        supplying a `model_code` of between 1 and 40 characters, a `brand` of
        between 1 and 80 characters printed on the product, a `category` drawn
        from `KITCHEN_APPLIANCE`, `JUVENILE_PRODUCT`, `POWER_TOOL`,
        `SPORTING_GOODS` and `HOME_ELECTRONICS` (the product family the office
        uses for docket routing), a `units_distributed` count of at least 1
        recording how many units were placed into commerce, and a
        `units_registered` count of at least 0 recording how many consumers are
        reachable through registration-card data." It adds: "A newly registered
        model always starts with `hazard_posture` at `MONITORED` and
        `open_escalation_count` at 0, and neither may be supplied by the client."

        Design: Corner/entities/product_model_creation_returns_every_declared_field
        """
        model = validate_success(
            api.create_product_model(dict(REGISTRY_ENTRY), headers=ADMIN_HEADERS), 201
        )

        assert_field_values(
            model,
            model_code="TOAST-X1",
            brand="Hearthline",
            category="KITCHEN_APPLIANCE",
            units_distributed=100,
            units_registered=60,
            hazard_posture="MONITORED",
            open_escalation_count=0,
        )

    def test_registration_stamps_its_own_identifiers_at_the_startup_clock(self, api):
        """The four common fields are server-owned and read the logical clock.

        The contract states: "`id` is a server-minted UUID with no type prefix
        and is never supplied by the client. `created_at` is an ISO 8601 UTC
        timestamp with three fractional digits, stamped when the row is first
        written. `updated_at` is an ISO 8601 UTC timestamp in the same format,
        initially equal to `created_at` and refreshed on every mutation of the
        row. `version` is an integer that starts at 1 on creation." It adds:
        "Before any client sets it, the logical clock reads exactly
        `2026-08-01T00:00:00Z`; it must not fall back to real wall-clock time."
        And of single-resource responses: "Single-resource responses omit all
        four."

        Design: Corner/entities/product_model_creation_returns_every_declared_field
        """
        response = api.create_product_model(dict(REGISTRY_ENTRY), headers=ADMIN_HEADERS)
        model = validate_success(response, 201)

        assert_common_fields(model, expected_version=1)
        assert_millisecond_timestamp(model["created_at"])
        assert_millisecond_timestamp(model["updated_at"])
        _assert_same_instant(model["created_at"], STARTUP_CLOCK)
        _assert_same_instant(model["updated_at"], STARTUP_CLOCK)
        assert model["updated_at"] == model["created_at"], (
            "updated_at must start out equal to created_at"
        )

        body = response.json()
        assert_success_envelope(body, "object")
        assert_single_resource_meta(body)


class TestIncidentRetrievalRoundTrip:
    """The stored incident, read back through its own single-resource fetch."""

    def test_the_single_incident_read_returns_every_value_the_writes_stored(
        self, api
    ):
        """A classified incident reads back exactly as intake and triage left it.

        The contract states: "Classification is where an intake report acquires
        analytical weight. Classifying an incident records an `injury_class` from
        `NO_INJURY`, `FIRST_AID`, `MEDICAL_TREATMENT`, `HOSPITALIZATION` and
        `FATALITY`, a `hazard_code` from `LACERATION`, `BURN`, `CHOKING`,
        `ELECTRIC_SHOCK`, `FALL` and `ENTRAPMENT`, and an `injury_verified`
        boolean stating whether the injury claim was corroborated by medical or
        retailer records. The operation stamps `classified_at` with the logical
        clock and recomputes the incident's `severity_weight`." The weight itself
        follows from "20 for `HOSPITALIZATION`" and "one arriving from a
        `MEDICAL_EXAMINER` by 1.50".

        Design: Corner/entities/incident_get_by_id_round_trips_every_stored_value
        """
        fx.set_clock(api, INTAKE_CLOCK)
        model = fx.create_product_model(api, **REGISTRY_ENTRY)
        written = fx.classified_incident(
            api,
            model["id"],
            report_channel="MEDICAL_EXAMINER",
            incident_date="2026-01-12T00:00:00Z",
            narrative=(
                "Base plate weld failed; second-degree burn, consumer hospitalised "
                "overnight."
            ),
            injury_class="HOSPITALIZATION",
            hazard_code="BURN",
            injury_verified=True,
        )

        response = api.get_incident(written["id"], headers=OFFICER_HEADERS)
        incident = validate_success(response)

        assert_field_values(
            incident,
            id=written["id"],
            product_model_id=model["id"],
            report_channel="MEDICAL_EXAMINER",
            injury_class="HOSPITALIZATION",
            hazard_code="BURN",
            injury_verified=True,
            status="CLASSIFIED",
        )
        assert_decimal_equals(incident["severity_weight"], "30.00")
        _assert_same_instant(incident["incident_date"], "2026-01-12T00:00:00Z")
        _assert_same_instant(incident["classified_at"], INTAKE_CLOCK)
        assert_fields_null(
            incident,
            "hazard_pattern_id",
            "duplicate_of_incident_id",
            "escalation_deadline_at",
        )
        assert_single_resource_meta(response.json())


class TestIncidentCollectionFilterAndPagination:
    """One status filter and a two-row page, composed on the same collection."""

    def _three_classified_and_one_untriaged(self, api):
        """Four reports on one model, only the first three of them classified."""
        fx.set_clock(api, INTAKE_CLOCK)
        model = fx.create_product_model(api, **REGISTRY_ENTRY)
        classified = [
            fx.classified_incident(api, model["id"], **spec)
            for spec in fx.CANONICAL_INCIDENTS
        ]
        untriaged = fx.create_incident(api, model["id"], **UNTRIAGED_REPORT)
        return model, classified, untriaged

    def test_the_status_filter_and_a_two_row_page_split_the_classified_rows(
        self, api
    ):
        """status=CLASSIFIED shrinks the set to three, which limit=2 then splits.

        The contract states: "Collection results are always ordered by
        `created_at` ascending — never by `id` — so that pagination is stable and
        so that a caller walking pages sees rows in the order the office recorded
        them." It adds: "For list responses the `meta` object carries `limit` and
        `offset` as applied, `total_count` giving the number of rows matching the
        filters before pagination, and `has_more` indicating whether rows remain
        beyond the current page."

        Design: Corner/entities/incident_list_filters_by_status_and_paginates_independently
        """
        model, classified, untriaged = self._three_classified_and_one_untriaged(api)
        query = {"product_model_id": model["id"], "status": "CLASSIFIED"}

        first_rows, first_meta = validate_paginated(
            api.list_incidents(dict(query, limit=2, offset=0), headers=OFFICER_HEADERS)
        )
        assert_pagination_meta(
            first_meta, limit=2, offset=0, total_count=3, has_more=True
        )
        assert_ids_equal(first_rows, [classified[0]["id"], classified[1]["id"]])
        assert_created_at_ascending(first_rows)

        second_rows, second_meta = validate_paginated(
            api.list_incidents(dict(query, limit=2, offset=2), headers=OFFICER_HEADERS)
        )
        assert_pagination_meta(
            second_meta, limit=2, offset=2, total_count=3, has_more=False
        )
        assert_ids_equal(second_rows, [classified[2]["id"]])

        walked = [row["id"] for row in first_rows + second_rows]
        assert untriaged["id"] not in walked, (
            "the INTAKE row must not leak into a CLASSIFIED window"
        )

    def test_the_untriaged_row_is_reachable_only_through_its_own_status_filter(
        self, api
    ):
        """The row the CLASSIFIED windows excluded is exactly the INTAKE row.

        The contract states: "The incident collection filters on
        `product_model_id`, `hazard_pattern_id`, `duplicate_of_incident_id`,
        `status`, `injury_class` and `hazard_code` — which is how an operator
        discovers which incidents a pattern clustered, and which merged reports
        fold into a surviving primary." It adds: "All filters are optional, all
        are combined conjunctively, and each accepts `limit` and `offset`."

        Design: Corner/entities/incident_list_filters_by_status_and_paginates_independently
        """
        model, _classified, untriaged = self._three_classified_and_one_untriaged(api)

        rows, meta = validate_paginated(
            api.list_incidents(
                {"product_model_id": model["id"], "status": "INTAKE"},
                headers=OFFICER_HEADERS,
            )
        )

        assert_pagination_meta(meta, total_count=1, has_more=False)
        assert_ids_equal(rows, [untriaged["id"]])
        assert_field_values(rows[0], status="INTAKE")


class TestUnknownIdNotFoundCodes:
    """Thirteen entities, thirteen distinct not-found codes."""

    def test_the_docket_spine_reads_report_their_own_not_found_codes(self, api):
        """Model, incident, pattern, evaluation, report and recall answer distinctly.

        The contract states: "Path identifiers are validated left to right in path
        order, and the first segment that does not resolve to a live row decides
        the response: the not-found error belongs to the entity that owns the
        failing segment, drawn from `ERR_PRODUCT_MODEL_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, `ERR_HAZARD_PATTERN_NOT_FOUND`,
        `ERR_EVALUATION_NOT_FOUND`, `ERR_SECTION_REPORT_NOT_FOUND`,
        `ERR_RECALL_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND`,
        `ERR_RETAILER_NOTIFICATION_NOT_FOUND`, `ERR_AUDIT_VISIT_NOT_FOUND`,
        `ERR_CONSUMER_NOTICE_NOT_FOUND`, `ERR_REMEDY_CLAIM_NOT_FOUND`,
        `ERR_PROGRESS_REPORT_NOT_FOUND` and `ERR_PENALTY_CASE_NOT_FOUND`, each
        answered with HTTP 404."

        Design: Corner/entities/every_entity_get_by_unknown_id_returns_its_own_not_found_code
        """
        _probe_unknown_ids(api, DOCKET_SPINE_PROBES)

    def test_the_retailer_channel_reads_report_their_own_not_found_codes(self, api):
        """Retailer, notification and audit visit do not share one 404 code.

        The contract states: "the not-found error belongs to the entity that owns
        the failing segment, drawn from `ERR_PRODUCT_MODEL_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, `ERR_HAZARD_PATTERN_NOT_FOUND`,
        `ERR_EVALUATION_NOT_FOUND`, `ERR_SECTION_REPORT_NOT_FOUND`,
        `ERR_RECALL_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND`,
        `ERR_RETAILER_NOTIFICATION_NOT_FOUND`, `ERR_AUDIT_VISIT_NOT_FOUND`,
        `ERR_CONSUMER_NOTICE_NOT_FOUND`, `ERR_REMEDY_CLAIM_NOT_FOUND`,
        `ERR_PROGRESS_REPORT_NOT_FOUND` and `ERR_PENALTY_CASE_NOT_FOUND`, each
        answered with HTTP 404."

        Design: Corner/entities/every_entity_get_by_unknown_id_returns_its_own_not_found_code
        """
        _probe_unknown_ids(api, RETAILER_CHANNEL_PROBES)

    def test_the_notice_remedy_and_penalty_reads_report_their_own_codes(self, api):
        """Notice, claim, progress report and penalty case each own their 404.

        The contract states: "the not-found error belongs to the entity that owns
        the failing segment, drawn from `ERR_PRODUCT_MODEL_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, `ERR_HAZARD_PATTERN_NOT_FOUND`,
        `ERR_EVALUATION_NOT_FOUND`, `ERR_SECTION_REPORT_NOT_FOUND`,
        `ERR_RECALL_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND`,
        `ERR_RETAILER_NOTIFICATION_NOT_FOUND`, `ERR_AUDIT_VISIT_NOT_FOUND`,
        `ERR_CONSUMER_NOTICE_NOT_FOUND`, `ERR_REMEDY_CLAIM_NOT_FOUND`,
        `ERR_PROGRESS_REPORT_NOT_FOUND` and `ERR_PENALTY_CASE_NOT_FOUND`, each
        answered with HTTP 404."

        Design: Corner/entities/every_entity_get_by_unknown_id_returns_its_own_not_found_code
        """
        _probe_unknown_ids(api, REMEDY_AND_PENALTY_PROBES)


class TestRequiredInputFields:
    """A body missing a non-optional field is refused before anything is written."""

    def test_a_registration_without_its_model_code_is_refused(self, api):
        """The registry refuses an entry that names no model code.

        The contract states: "The request-shape check at step 4 has a defined
        scope. It requires every non-optional field to be present and non-null."
        The check itself is: "**Request shape** — the body conforms to the
        endpoint's input contract, else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/missing_required_input_fields_rejected_before_any_row_is_written
        """
        payload = {
            key: value for key, value in REGISTRY_ENTRY.items() if key != "model_code"
        }

        validate_error(
            api.create_product_model(payload, headers=ADMIN_HEADERS),
            "ERR_INVALID_REQUEST",
            400,
        )

    def test_an_incident_without_its_narrative_is_refused_and_writes_no_row(self, api):
        """A report with no narrative is rejected and leaves the queue empty.

        The contract states: "An `IntakeSpecialist` (or a `ComplianceOfficer`)
        records a consumer complaint or injury report by submitting the
        `product_model_id` of the model it concerns, a `report_channel` of
        `CONSUMER_HOTLINE`, `WEB_FORM`, `RETAILER` or `MEDICAL_EXAMINER` naming
        the intake channel, an `incident_date` giving the ISO 8601 UTC instant at
        which the harm or malfunction occurred, and a free-text `narrative` of
        between 1 and 2000 characters describing the complaint." The shape check
        "requires every non-optional field to be present and non-null".

        Design: Corner/entities/missing_required_input_fields_rejected_before_any_row_is_written
        """
        fx.set_clock(api, INTAKE_CLOCK)
        model = fx.create_product_model(api, **REGISTRY_ENTRY)

        validate_error(
            api.create_incident(
                {
                    "product_model_id": model["id"],
                    "report_channel": "WEB_FORM",
                    "incident_date": "2026-02-10T00:00:00Z",
                },
                headers=INTAKE_HEADERS,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        rows, meta = validate_paginated(
            api.list_incidents(
                {"product_model_id": model["id"]}, headers=OFFICER_HEADERS
            )
        )
        assert rows == [], f"the rejected create wrote a row: {rows}"
        assert_pagination_meta(meta, total_count=0, has_more=False)

    def test_a_classification_without_its_injury_class_is_refused(self, api):
        """Triage cannot classify an incident without naming the injury class.

        The contract states: "Classifying an incident records an `injury_class`
        from `NO_INJURY`, `FIRST_AID`, `MEDICAL_TREATMENT`, `HOSPITALIZATION` and
        `FATALITY`, a `hazard_code` from `LACERATION`, `BURN`, `CHOKING`,
        `ELECTRIC_SHOCK`, `FALL` and `ENTRAPMENT`, and an `injury_verified`
        boolean." The shape check "requires every non-optional field to be
        present and non-null", else `ERR_INVALID_REQUEST`.

        Design: Corner/entities/missing_required_input_fields_rejected_before_any_row_is_written
        """
        fx.set_clock(api, INTAKE_CLOCK)
        model = fx.create_product_model(api, **REGISTRY_ENTRY)
        incident = fx.create_incident(api, model["id"], **UNTRIAGED_REPORT)

        validate_error(
            api.classify_incident(
                incident["id"],
                {"hazard_code": "BURN", "injury_verified": True},
                headers=INTAKE_HEADERS,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        after = fx.get_incident(api, incident["id"])
        assert_field_values(after, status="INTAKE", version=1)
        assert_fields_null(after, "injury_class", "hazard_code", "classified_at")


class TestCreationDefaultsAcrossEntities:
    """Each entity's initial state is its own, and not every default is zero."""

    def test_a_new_report_lands_in_intake_with_no_classification_at_all(self, api):
        """An untriaged report carries null triage fields and a zero weight.

        The contract states: "A new report lands in `INTAKE` status with no injury
        classification at all: `injury_class` and `hazard_code` are both null,
        `injury_verified` is false, `severity_weight` is 0.00, `classified_at` and
        `escalation_deadline_at` are null, and both `hazard_pattern_id` and
        `duplicate_of_incident_id` are null."

        Design: Corner/entities/computed_field_defaults_applied_across_entities_on_creation
        """
        fx.set_clock(api, INTAKE_CLOCK)
        model = fx.create_product_model(api, **REGISTRY_ENTRY)

        incident = fx.create_incident(api, model["id"], **UNTRIAGED_REPORT)

        assert_common_fields(incident, expected_version=1)
        assert_field_values(incident, status="INTAKE", injury_verified=False)
        assert_decimal_equals(incident["severity_weight"], "0.00")
        assert_fields_null(
            incident,
            "injury_class",
            "hazard_code",
            "classified_at",
            "escalation_deadline_at",
            "hazard_pattern_id",
            "duplicate_of_incident_id",
        )

    def test_a_new_recall_seeds_units_outstanding_from_the_units_in_commerce(
        self, api
    ):
        """The unit ledger is conserved from the moment the plan is drafted.

        The contract states: "A new recall is created with `plan_status` at
        `DRAFT`, `notification_status` at `NOT_STARTED`, `units_corrected` at 0,
        `units_outstanding` initialised to `units_in_commerce`,
        `effectiveness_flag` at `PENDING`, and `stop_sale_effective_at`,
        `submitted_by_user_id` and `last_accepted_period_end` all null."

        Design: Corner/entities/computed_field_defaults_applied_across_entities_on_creation
        """
        env = fx.draft_recall_env(api, enroll_retailer=False, schedule_notice=False)
        recall = env["recall"]

        assert_common_fields(recall, expected_version=1)
        assert_field_values(
            recall,
            plan_status="DRAFT",
            notification_status="NOT_STARTED",
            units_in_commerce=100,
            units_corrected=0,
            units_outstanding=100,
            effectiveness_flag="PENDING",
        )
        assert_fields_null(
            recall,
            "stop_sale_effective_at",
            "submitted_by_user_id",
            "last_accepted_period_end",
        )
        assert_unit_ledger_conserved(recall)

    def test_a_new_notification_starts_pending_with_no_stop_sale_required(self, api):
        """Enrollment cannot arm the stop-sale, even when the client asks for it.

        The contract states: "The enrollment body also tolerates a
        `stop_sale_required` key, but that field is server-owned and any supplied
        value is silently ignored: a new notification is always created in
        `PENDING` with `stop_sale_required` false and with `issued_at`,
        `ack_due_at`, `acknowledged_at`, `verified_at` and
        `units_on_shelf_reported` all null."

        Design: Corner/entities/computed_field_defaults_applied_across_entities_on_creation
        """
        env = fx.draft_recall_env(api, enroll_retailer=False, schedule_notice=False)
        retailer = fx.create_retailer(api, name="MegaMart")

        notification = validate_success(
            api.create_retailer_notification(
                {
                    "recall_id": env["recall_id"],
                    "retailer_id": retailer["id"],
                    "stop_sale_required": True,
                },
                headers=OFFICER_HEADERS,
            ),
            201,
        )

        assert_common_fields(notification, expected_version=1)
        assert_field_values(
            notification,
            recall_id=env["recall_id"],
            retailer_id=retailer["id"],
            status="PENDING",
            stop_sale_required=False,
        )
        assert_fields_null(
            notification,
            "issued_at",
            "ack_due_at",
            "acknowledged_at",
            "verified_at",
            "units_on_shelf_reported",
        )

    def test_a_new_audit_visit_starts_scheduled_with_a_pending_verdict(self, api):
        """A scheduled inspection has recorded no verdict and no shelf count yet.

        The contract states: "A new visit is created with `status` `SCHEDULED`,
        `verdict` `PENDING`, and `shelf_units_found` and `completed_at` both null;
        `status` runs `SCHEDULED → COMPLETED` and `verdict` is one of `PENDING`,
        `PASS` and `FAIL`."

        Design: Corner/entities/computed_field_defaults_applied_across_entities_on_creation
        """
        env = fx.approved_recall_env(api)

        visit = fx.create_audit_visit(api, env["notification_id"])

        assert_common_fields(visit, expected_version=1)
        assert_field_values(
            visit,
            retailer_notification_id=env["notification_id"],
            status="SCHEDULED",
            verdict="PENDING",
        )
        assert_fields_null(visit, "shelf_units_found", "completed_at")


class TestSeverityWeightIsServerComputed:
    """The weight follows from the incident's own three inputs and nothing else."""

    def _two_untriaged_reports(self, api):
        """The same product reported once by a retailer and once by the hotline."""
        fx.set_clock(api, INTAKE_CLOCK)
        model = fx.create_product_model(api, **REGISTRY_ENTRY)
        retailer_report = fx.create_incident(api, model["id"], **RETAILER_REPORT)
        hotline_report = fx.create_incident(api, model["id"], **HOTLINE_REPORT)
        return model, retailer_report, hotline_report

    def test_the_channel_multiplier_alone_separates_two_identical_injuries(self, api):
        """One injury class through two channels yields 9.60 and 8.00.

        The contract states: "Each injury class carries an injury base weight: 1
        for `NO_INJURY`, 3 for `FIRST_AID`, 8 for `MEDICAL_TREATMENT`, 20 for
        `HOSPITALIZATION` and 50 for `FATALITY`. Each intake channel carries a
        credibility multiplier reflecting how much the office trusts the source: a
        report arriving through `CONSUMER_HOTLINE` or `WEB_FORM` is multiplied by
        1.00, one arriving through a `RETAILER` by 1.20, and one arriving from a
        `MEDICAL_EXAMINER` by 1.50." It adds: "Only the incident's own
        `injury_class`, `report_channel` and `injury_verified` participate; there
        is no aggregation over sibling reports."

        Design: Corner/entities/severity_weight_is_computed_at_classification_and_not_client_settable
        """
        _model, retailer_report, hotline_report = self._two_untriaged_reports(api)

        from_retailer = fx.classify_incident(api, retailer_report["id"], **TREATED_BURN)
        from_hotline = fx.classify_incident(api, hotline_report["id"], **TREATED_BURN)

        assert_decimal_equals(from_retailer["severity_weight"], "9.60")
        assert_decimal_equals(from_hotline["severity_weight"], "8.00")
        for row in (from_retailer, from_hotline):
            assert_field_values(
                row, injury_class="MEDICAL_TREATMENT", status="CLASSIFIED"
            )
            _assert_same_instant(row["classified_at"], INTAKE_CLOCK)

    def test_a_client_supplied_weight_and_stamp_are_dropped_from_the_body(self, api):
        """A posted severity_weight is ignored, not honoured and not rejected.

        The contract states: "Conversely, unknown body keys and any attempt to
        supply a server-computed field are **ignored silently** rather than
        rejected — a client that posts `stop_sale_required`, `severity_weight` or
        `assessed_penalty_cents` in a creation body simply has those keys
        dropped." The weight that survives is the computed one, because "the
        injury base weight is multiplied by the credibility multiplier of the
        channel fixed at intake".

        Design: Corner/entities/severity_weight_is_computed_at_classification_and_not_client_settable
        """
        _model, retailer_report, _hotline_report = self._two_untriaged_reports(api)

        classified = validate_success(
            api.classify_incident(
                retailer_report["id"],
                dict(
                    TREATED_BURN,
                    severity_weight=99.99,
                    classified_at="2020-01-01T00:00:00Z",
                ),
                headers=INTAKE_HEADERS,
            )
        )

        assert_decimal_equals(classified["severity_weight"], "9.60")
        _assert_same_instant(classified["classified_at"], INTAKE_CLOCK)
        assert_field_values(classified, status="CLASSIFIED")


class TestSystemFieldsAndVersionAdvance:
    """Identifiers, stamps and versions belong to the server on every write."""

    def _model_with_a_classified_cluster(self, api):
        """A model whose three classified burns are ready for an analysis run."""
        fx.set_clock(api, INTAKE_CLOCK)
        model = fx.create_product_model(api, **REGISTRY_ENTRY)
        fx.canonical_incident_set(api, model["id"])
        fx.set_clock(api, ANALYSIS_CLOCK)
        return fx.get_product_model(api, model["id"])

    def test_the_analysis_mints_its_own_id_and_stamps_the_logical_clock(self, api):
        """A new pattern carries a fresh UUID and a first version of 1.

        The contract states: "`id` is a server-minted UUID with no type prefix and
        is never supplied by the client. `created_at` is an ISO 8601 UTC timestamp
        with three fractional digits, stamped when the row is first written." It
        adds: "`analyzed_at` is stamped with the logical clock on every analysis
        run."

        Design: Corner/entities/system_fields_are_server_generated_and_version_advances_on_write
        """
        model = self._model_with_a_classified_cluster(api)

        pattern = fx.create_pattern(
            api, model["id"], model["version"], **ANALYSIS_WINDOW
        )

        assert_common_fields(pattern, expected_version=1)
        assert pattern["id"] != model["id"], (
            "the pattern must not borrow the model's identifier"
        )
        assert_millisecond_timestamp(pattern["created_at"])
        _assert_same_instant(pattern["created_at"], ANALYSIS_CLOCK)
        _assert_same_instant(pattern["updated_at"], ANALYSIS_CLOCK)
        _assert_same_instant(pattern["analyzed_at"], ANALYSIS_CLOCK)

    def test_the_analysis_advances_the_model_version_and_freezes_its_created_at(
        self, api
    ):
        """The model is bumped from 1 to 2 by a write that never names it directly.

        The contract states: "`version` is an integer that starts at 1 on creation
        and increments by exactly 1 on every mutation of the row, including
        mutations that reach the row as the second or third link of a cascade
        rather than as the direct target of the request." Of this write in
        particular: "The product model's `version` is incremented by 1 — which is
        why the next analysis of the same model needs a fresh
        `expected_product_model_version`."

        Design: Corner/entities/system_fields_are_server_generated_and_version_advances_on_write
        """
        model = self._model_with_a_classified_cluster(api)
        assert model["version"] == 1, "the registry entry starts at version 1"

        fx.create_pattern(api, model["id"], model["version"], **ANALYSIS_WINDOW)

        after = fx.get_product_model(api, model["id"])
        assert_field_values(after, version=2)
        assert_unchanged(model, after, "created_at")
        _assert_same_instant(after["created_at"], INTAKE_CLOCK)
        _assert_same_instant(after["updated_at"], ANALYSIS_CLOCK)

    def test_a_client_supplied_id_created_at_and_version_are_dropped(self, api):
        """The four common fields cannot be dictated by the creation body.

        The contract states: "`id` is a server-minted UUID with no type prefix and
        is never supplied by the client." And: "unknown body keys and any attempt
        to supply a server-computed field are **ignored silently** rather than
        rejected."

        Design: Corner/entities/system_fields_are_server_generated_and_version_advances_on_write
        """
        model = self._model_with_a_classified_cluster(api)

        pattern = validate_success(
            api.create_hazard_pattern(
                {
                    "product_model_id": model["id"],
                    "analysis_basis": "PRELIMINARY",
                    "expected_product_model_version": model["version"],
                    "id": NON_EXISTENT_UUID,
                    "created_at": "2020-01-01T00:00:00Z",
                    "version": 41,
                    **ANALYSIS_WINDOW,
                },
                headers=OFFICER_HEADERS,
            ),
            201,
        )

        assert_common_fields(pattern, expected_version=1)
        assert pattern["id"] != NON_EXISTENT_UUID, (
            "the id must be minted by the server, not taken from the body"
        )
        _assert_same_instant(pattern["created_at"], ANALYSIS_CLOCK)


class TestEnumAndRangeConstraints:
    """A value the contract cannot even interpret is a malformed request."""

    def test_an_undeclared_injury_class_is_refused_and_writes_nothing(self, api):
        """An out-of-vocabulary enum member never reaches the domain rules.

        The contract states: "The request-shape check at step 4 has a defined
        scope. It requires every non-optional field to be present and non-null;
        every enum-valued field to carry a declared member." The declared members
        are "an `injury_class` from `NO_INJURY`, `FIRST_AID`,
        `MEDICAL_TREATMENT`, `HOSPITALIZATION` and `FATALITY`", and a body that
        fails the check draws `ERR_INVALID_REQUEST`.

        Design: Corner/entities/enum_and_range_type_constraints_are_rejected_as_invalid_request
        """
        fx.set_clock(api, INTAKE_CLOCK)
        model = fx.create_product_model(api, **REGISTRY_ENTRY)
        incident = fx.create_incident(api, model["id"], **UNTRIAGED_REPORT)

        validate_error(
            api.classify_incident(
                incident["id"],
                {
                    "injury_class": "SPRAINED_ANKLE",
                    "hazard_code": "BURN",
                    "injury_verified": True,
                },
                headers=INTAKE_HEADERS,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        after = fx.get_incident(api, incident["id"])
        assert_field_values(after, status="INTAKE", version=1)
        assert_fields_null(after, "injury_class", "classified_at")

    def test_an_inverted_analysis_window_is_refused_without_touching_the_model(
        self, api
    ):
        """A window whose end precedes its start writes no pattern and no version.

        The contract states: "The request-shape check at step 4 has a defined
        scope. It requires ... every interval to be well ordered, meaning a hazard
        pattern's `window_start` strictly before its `window_end`, an audit
        visit's `window_start` strictly before its `window_end`, and a progress
        report's `period_start` strictly before its `period_end`." A rejected
        write leaves the model untouched, because `version` "increments by exactly
        1 on every mutation of the row".

        Design: Corner/entities/enum_and_range_type_constraints_are_rejected_as_invalid_request
        """
        fx.set_clock(api, INTAKE_CLOCK)
        model = fx.create_product_model(api, **REGISTRY_ENTRY)

        validate_error(
            api.create_hazard_pattern(
                {
                    "product_model_id": model["id"],
                    "window_start": "2026-02-28T00:00:00Z",
                    "window_end": "2026-01-01T00:00:00Z",
                    "analysis_basis": "PRELIMINARY",
                    "expected_product_model_version": model["version"],
                },
                headers=OFFICER_HEADERS,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        rows, meta = validate_paginated(
            api.list_hazard_patterns(
                {"product_model_id": model["id"]}, headers=OFFICER_HEADERS
            )
        )
        assert rows == [], f"the rejected analysis wrote a pattern: {rows}"
        assert_pagination_meta(meta, total_count=0)
        assert_field_values(fx.get_product_model(api, model["id"]), version=1)

    def test_a_negative_units_distributed_count_is_refused(self, api):
        """A distribution figure below the declared floor is malformed.

        The contract states: "The request-shape check at step 4 has a defined
        scope. It requires ... every integer field to be an integer inside its
        declared range." The declared range is "a `units_distributed` count of at
        least 1 recording how many units were placed into commerce".

        Design: Corner/entities/enum_and_range_type_constraints_are_rejected_as_invalid_request
        """
        fx.set_clock(api, INTAKE_CLOCK)

        validate_error(
            api.create_product_model(
                dict(REGISTRY_ENTRY, model_code="TOAST-X2", units_distributed=-5),
                headers=ADMIN_HEADERS,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )


class TestBodyForeignKeyResolution:
    """On a flat topology every parent is a body key, resolved at priority 5."""

    def test_a_report_against_an_unknown_model_reports_the_model_code(self, api):
        """The dangling `product_model_id` answers with the model's own 404.

        The contract states: "**Body foreign-key existence** — every foreign-key
        identifier in the body resolves to a live row, else that entity's
        not-found error." The catalogue that serves it is the same one the path
        check uses, drawn from `ERR_PRODUCT_MODEL_NOT_FOUND` onwards.

        Design: Corner/entities/body_foreign_keys_must_reference_existing_rows_on_a_flat_topology
        """
        fx.set_clock(api, INTAKE_CLOCK)

        validate_error(
            api.create_incident(
                {
                    "product_model_id": NON_EXISTENT_UUID,
                    "report_channel": "WEB_FORM",
                    "incident_date": "2026-02-10T00:00:00Z",
                    "narrative": "Report against a model that does not exist.",
                },
                headers=INTAKE_HEADERS,
            ),
            "ERR_PRODUCT_MODEL_NOT_FOUND",
            404,
        )

    def test_an_enrollment_reports_the_dangling_recall_not_the_valid_retailer(
        self, api
    ):
        """The failing key decides the code, and the enrolled retailer is untouched.

        The contract states: "**Body foreign-key existence** — every foreign-key
        identifier in the body resolves to a live row, else that entity's
        not-found error." The retailer it names is live, and "A new retailer starts
        `CLEAR` in its `compliance_posture` with all three of
        `open_stop_sale_count`, `verified_removal_count` and `delinquent_count` at
        0".

        Design: Corner/entities/body_foreign_keys_must_reference_existing_rows_on_a_flat_topology
        """
        fx.set_clock(api, INTAKE_CLOCK)
        retailer = fx.create_retailer(api, name="MegaMart")

        validate_error(
            api.create_retailer_notification(
                {"recall_id": NON_EXISTENT_UUID, "retailer_id": retailer["id"]},
                headers=OFFICER_HEADERS,
            ),
            "ERR_RECALL_NOT_FOUND",
            404,
        )

        after = fx.get_retailer(api, retailer["id"])
        assert_field_values(
            after,
            version=1,
            compliance_posture="CLEAR",
            open_stop_sale_count=0,
            verified_removal_count=0,
            delinquent_count=0,
        )

    def test_an_audit_visit_against_an_unknown_notification_reports_its_code(
        self, api
    ):
        """The visit's only parent is its notification, so that code is reported.

        The contract states: "**Body foreign-key existence** — every foreign-key
        identifier in the body resolves to a live row, else that entity's
        not-found error." The visit names "the `retailer_notification_id` whose
        stop-sale instruction the visit verifies", whose catalogue entry is
        `ERR_RETAILER_NOTIFICATION_NOT_FOUND`.

        Design: Corner/entities/body_foreign_keys_must_reference_existing_rows_on_a_flat_topology
        """
        fx.set_clock(api, INTAKE_CLOCK)

        validate_error(
            api.create_audit_visit(
                {
                    "retailer_notification_id": NON_EXISTENT_UUID,
                    "window_start": "2026-03-17T09:00:00Z",
                    "window_end": "2026-03-17T17:00:00Z",
                },
                headers=AUDITOR_HEADERS,
            ),
            "ERR_RETAILER_NOTIFICATION_NOT_FOUND",
            404,
        )

    def test_a_malformed_enrollment_never_leaks_the_missing_recall(self, api):
        """The shape check runs first, so the dangling key is never resolved.

        The contract states: "The same catalogue serves foreign keys supplied in a
        request body, but body foreign keys are only resolved *after* the body has
        passed its shape check, so a malformed payload never leaks the existence of
        a referenced row."

        Design: Corner/entities/body_foreign_keys_must_reference_existing_rows_on_a_flat_topology
        """
        fx.set_clock(api, INTAKE_CLOCK)

        validate_error(
            api.create_retailer_notification(
                {"recall_id": NON_EXISTENT_UUID},
                headers=OFFICER_HEADERS,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

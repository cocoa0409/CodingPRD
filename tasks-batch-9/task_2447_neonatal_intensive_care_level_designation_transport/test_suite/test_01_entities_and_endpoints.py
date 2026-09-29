"""Entity shape and endpoint contract conformance for the Neonatal Network API.

Covers PRD §2.2 (response envelope), §2.3 (pagination and filters), §2.4 (resource
identity, versioning and the logical clock), §2.5 (derived asset status), §2.7
(capability and effective level), §2.8 (the bed ledger, waterfall allocation,
census posture and the nursing requirement), §2.10 (rejection precedence and
per-identifier not-found codes), §3.1 (unit registration, capacity edits,
designation standards, credentials and assets), §3.3 (referral intake and the
level and triage derivations), §3.4 (acceptance and bed holds), §3.6 (transport
activation and the dispatch fork) and §3.8 (the capability cascade).
"""

from datetime import datetime

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_timestamp_format,
    assertions,
    factories,
    fixtures,
    is_valid_uuid,
    make_network_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_START

FOUR_LEVELS = ("LEVEL_I", "LEVEL_II", "LEVEL_III", "LEVEL_IV")


def _assert_instant(actual, expected):
    """Compare two ISO-8601 instants by value, whatever fractional digits are used."""
    assert_timestamp_format(actual)
    assert datetime.fromisoformat(actual.replace("Z", "+00:00")) == datetime.fromisoformat(
        expected.replace("Z", "+00:00")
    ), f"expected the instant {expected}, got {actual}"


def _register_regional_and_community(api, headers):
    regional = validate_success(api.create_nicu_unit(factories.nicu_unit_payload(), headers), 201)
    community = validate_success(
        api.create_nicu_unit(factories.community_unit_payload(), headers), 201
    )
    return regional, community


def _create_case_d1(api, env):
    """Refer CASE-D1 without supplying either optional referral input."""
    payload = factories.referral_payload(
        env["unit_b_id"],
        env["unit_a_id"],
        case_reference="CASE-D1",
        gestational_age_weeks=36.0,
        birth_weight_grams=2600,
        support_modality="CPAP",
    )
    payload.pop("diagnoses")
    payload.pop("planned_surgery")
    return validate_success(api.create_referral(payload, env["ref_b"]), 201)


# ---------------------------------------------------------------------------
# Unit registration: system fields, derived capability, ledger and posture
# ---------------------------------------------------------------------------


def test_unit_registration_stamps_system_fields_and_opening_statuses(api):
    """PRD §2.4: "Alongside `id`, resources carry `created_at` and `updated_at` — ISO 8601 UTC timestamps rendered with exactly three fractional-second digits — and `version`, an integer that begins at 1 when the resource is created and increases by one on every mutation of that resource."

    PRD §3.1: "A newly registered unit begins at `designation_status` `PROVISIONAL` and at `quality_flag` `WITHIN_BENCHMARK`, the latter being replaced only when the network accepts a surveillance report as described in §3.9."

    Design: Corner/entities/unit_creation_applies_declared_defaults_and_system_fields
    """
    admin = make_network_admin_headers()
    fixtures.set_clock()
    fixtures.declare_standards(FOUR_LEVELS, admin)

    regional, community = _register_regional_and_community(api, admin)

    for unit in (regional, community):
        assertions.assert_common_fields(unit)
        assert is_valid_uuid(unit["id"])
        assert unit["version"] == 1
        _assert_instant(unit["created_at"], CLOCK_START)
        _assert_instant(unit["updated_at"], CLOCK_START)
        assert unit["designation_status"] == "PROVISIONAL"
        assert unit["quality_flag"] == "WITHIN_BENCHMARK"


def test_unit_without_credentials_or_assets_falls_back_to_level_i(api):
    """PRD §2.7: "`capability_level` is what the unit can currently prove — the highest-ranking level among the declared standards that the unit satisfies, falling back to `LEVEL_I` when it satisfies none of them, because a newborn nursery baseline is statutory and a unit is never rated below `LEVEL_I`."

    PRD §2.7: "`effective_level` is the lower-ranking of `designated_level` and `capability_level`, and it — not the designated level — gates every referral acceptance."

    PRD §2.7: "Two booleans expose the halves of the satisfaction test against the standard for the unit's own `designated_level`: `staffing_compliant` is true when every required credential code of that standard is held with derived `status` `VALID` and `fte` at least 0.5, and `equipment_compliant` is true when every required equipment code of that standard is held with derived `status` `IN_SERVICE`."

    Design: Corner/entities/unit_creation_applies_declared_defaults_and_system_fields
    """
    admin = make_network_admin_headers()
    fixtures.set_clock()
    fixtures.declare_standards(FOUR_LEVELS, admin)

    regional, _ = _register_regional_and_community(api, admin)

    assert regional["designated_level"] == "LEVEL_III"
    assert regional["capability_level"] == "LEVEL_I"
    assert regional["effective_level"] == "LEVEL_I"
    assertions.assert_effective_level_consistent(regional)
    assert regional["staffing_compliant"] is False
    assert regional["equipment_compliant"] is False


def test_new_unit_bed_ledger_opens_empty(api):
    """PRD §2.8: "And `available_bed_count` is the base staffed bed target plus the escalation bed count, minus the occupied bed count, minus the held bed count."

    PRD §2.8: "The invariant that must hold after every single operation is that `staffed_bed_target` plus `escalation_bed_count` equals `occupied_bed_count` plus `held_bed_count` plus `available_bed_count`."

    PRD §2.8: "`deferral_queue_depth` is itself the count of referrals whose `receiving_unit_id` is this unit and whose status is `DEFERRED`."

    Design: Corner/entities/unit_creation_applies_declared_defaults_and_system_fields
    """
    admin = make_network_admin_headers()
    fixtures.set_clock()
    fixtures.declare_standards(FOUR_LEVELS, admin)

    regional, _ = _register_regional_and_community(api, admin)

    assert regional["staffed_bed_target"] == 4
    assertions.assert_unit_counts(regional, occupied=0, held=0, available=4, escalation=0)
    assert regional["deferral_queue_depth"] == 0


def test_new_unit_posture_is_open_and_requires_no_nurses(api):
    """PRD §2.8: "Otherwise, when `available_bed_count` is at or below the `staffed_bed_target` multiplied by 0.20 and rounded down to a whole bed, the posture is `CONSTRAINED`."

    PRD §2.8: "Otherwise it is `OPEN`."

    PRD §2.8: "An empty census requires zero nurses."

    Design: Corner/entities/unit_creation_applies_declared_defaults_and_system_fields
    """
    admin = make_network_admin_headers()
    fixtures.set_clock()
    fixtures.declare_standards(FOUR_LEVELS, admin)

    regional, _ = _register_regional_and_community(api, admin)

    assert regional["census_posture"] == "OPEN"
    assertions.assert_census_posture_consistent(regional)
    assert regional["required_nurse_count"] == 0


def test_community_unit_satisfies_the_level_i_standard_that_demands_nothing(api):
    """PRD §3.1: "An empty `required_credential_codes` array scores full marks for credential coverage, and an empty `required_equipment_codes` array scores full marks for equipment coverage — this is how `LEVEL_I`, which demands nothing, is satisfied by every unit."

    PRD §2.7: "A unit **satisfies** a standard when every code listed in that standard's `required_credential_codes` is held by a credential of that unit whose derived `status` is `VALID` and whose `fte` is at least 0.5, and every code in that standard's `required_equipment_codes` is held by an asset of that unit whose derived `status` is `IN_SERVICE`."

    Design: Corner/entities/unit_creation_applies_declared_defaults_and_system_fields
    """
    admin = make_network_admin_headers()
    fixtures.set_clock()
    fixtures.declare_standards(FOUR_LEVELS, admin)

    _, community = _register_regional_and_community(api, admin)

    assert community["designated_level"] == "LEVEL_I"
    assert community["capability_level"] == "LEVEL_I"
    assert community["staffing_compliant"] is True
    assert community["equipment_compliant"] is True
    assertions.assert_unit_counts(community, available=6, posture="OPEN")


# ---------------------------------------------------------------------------
# Optional inputs and their declared defaults
# ---------------------------------------------------------------------------


def test_unit_optional_inputs_take_their_declared_defaults(api):
    """PRD §3.1: "Four further inputs are optional at registration and default in the caller's absence: `designated_level` defaults to `LEVEL_I`; `transport_capable`, which declares that the unit operates its own neonatal transport team, defaults to false; `annual_admission_volume`, the rolling annual admission volume the unit declares for designation scoring, defaults to 0; and `followup_clinic_daily_capacity`, the number of high-risk follow-up clinic slots the unit can fill per calendar day, defaults to 0."

    PRD §3.1: "A newly registered unit begins at `designation_status` `PROVISIONAL` and at `quality_flag` `WITHIN_BENCHMARK`, the latter being replaced only when the network accepts a surveillance report as described in §3.9."

    Design: Corner/entities/optional_fields_fall_back_to_declared_defaults
    """
    env = fixtures.setup_network(with_isolette=True)

    payload = factories.nicu_unit_payload(
        name="Bare Nursery C", hospital_type="COMMUNITY", staffed_bed_target=3
    )
    for optional_field in (
        "designated_level",
        "transport_capable",
        "annual_admission_volume",
        "followup_clinic_daily_capacity",
    ):
        payload.pop(optional_field)

    unit_c = validate_success(api.create_nicu_unit(payload, env["admin"]), 201)

    assert unit_c["designated_level"] == "LEVEL_I"
    assert unit_c["transport_capable"] is False
    assert unit_c["annual_admission_volume"] == 0
    assert unit_c["followup_clinic_daily_capacity"] == 0
    assert unit_c["designation_status"] == "PROVISIONAL"
    assertions.assert_unit_counts(unit_c, available=3, posture="OPEN")


def test_referral_optional_inputs_default_and_the_case_opens_pending(api):
    """PRD §3.3: "Two inputs are optional: `diagnoses`, an array drawn from `RDS_SEVERE`, `HIE_MODERATE`, `PROM`, `CHD_DUCTAL` and `SURGICAL_NEC`, defaulting to an empty array; and `planned_surgery`, a boolean defaulting to false."

    PRD §3.3: "The new referral starts at status `PENDING` with `info_request_rounds` at 0 and `decision_reason`, `requested_items`, `source_admission_id`, `superseded_by_referral_id` and `reservation_id` all null."

    Design: Corner/entities/optional_fields_fall_back_to_declared_defaults
    """
    env = fixtures.setup_network(with_isolette=True)

    referral = _create_case_d1(api, env)

    assert referral["diagnoses"] == []
    assert referral["planned_surgery"] is False
    assert referral["status"] == "PENDING"
    assert referral["info_request_rounds"] == 0
    assert referral["requested_items"] is None
    assert referral["decision_reason"] is None
    assert referral["source_admission_id"] is None
    assert referral["superseded_by_referral_id"] is None
    assert referral["reservation_id"] is None


def test_referral_weight_basis_drives_both_level_variants(api):
    """PRD §3.3: "The weight the level calculation actually consults is `weight_basis_grams`: it is the source admission's `current_weight_grams` when `referral_kind` is `BACK_TRANSFER`, and the referral's own `birth_weight_grams` otherwise."

    PRD §3.3: "`current_support_level` — the level demanded by findings that already exist — is the higher-ranking of the support term and the weight term, except that for a `MATERNAL_ANTENATAL` referral the weight contribution is forced to `LEVEL_I`, because an unborn infant has no current weight-driven support need and its estimated fetal weight belongs to the anticipated variant only."

    PRD §3.3: "`required_level` is always `anticipated_need_level`."

    Design: Corner/entities/optional_fields_fall_back_to_declared_defaults
    """
    env = fixtures.setup_network(with_isolette=True)

    referral = _create_case_d1(api, env)

    assert referral["weight_basis_grams"] == 2600
    assert referral["current_support_level"] == "LEVEL_II"
    assert referral["anticipated_need_level"] == "LEVEL_II"
    assert referral["required_level"] == "LEVEL_II"


def test_referral_level_basis_and_maternal_preference_when_variants_tie(api):
    """PRD §3.3: "`level_basis` records which variant drove the answer: it is `ANTICIPATED_NEED` when `anticipated_need_level` outranks `current_support_level`, and `CURRENT_SUPPORT` otherwise — including when the two are equal."

    PRD §3.3: "`maternal_transfer_preferred` is true exactly when `referral_kind` is `MATERNAL_ANTENATAL` and `required_level` ranks at `LEVEL_III` or above."

    Design: Corner/entities/optional_fields_fall_back_to_declared_defaults
    """
    env = fixtures.setup_network(with_isolette=True)

    referral = _create_case_d1(api, env)

    assert referral["level_basis"] == "CURRENT_SUPPORT"
    assert referral["maternal_transfer_preferred"] is False


def test_referral_triage_priority_is_the_weighted_sum_of_the_four_terms(api):
    """PRD §3.3: "The priority is 0.40 of the level points plus 0.25 of the prematurity points plus 0.20 of the weight points plus 0.15 of the kind points, rounded half up to two decimals."

    Design: Corner/entities/optional_fields_fall_back_to_declared_defaults
    """
    env = fixtures.setup_network(with_isolette=True)

    referral = _create_case_d1(api, env)

    # LEVEL_II is 50 level points, 36.0 weeks is 25 prematurity points, 2600 grams is
    # 25 weight points and INBOUND_NEONATAL is 50 kind points.
    assertions.assert_close(referral["triage_priority"], 38.75)
    assertions.assert_decimal_places(referral["triage_priority"], 2)


# ---------------------------------------------------------------------------
# Unit reads, filters and pagination
# ---------------------------------------------------------------------------


def test_units_can_be_filtered_by_hospital_type(api):
    """PRD §3.1: "Units may be listed and filtered by `hospital_type`, by `designation_status` and by `census_posture`, and reading a single unit recomputes every derived capability and bed figure described in §2.7 and §2.8 before responding."

    PRD §2.3: "Filter query parameters, where an endpoint offers them, combine conjunctively — a row must match every supplied filter to appear."

    Design: Corner/entities/unit_retrieval_and_filtered_pagination
    """
    env = fixtures.setup_network(credentials=(), equipment=())

    rows, meta = validate_paginated(
        api.list_nicu_units(env["admin"], {"hospital_type": "COMMUNITY"})
    )

    assert len(rows) == 1
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert rows[0]["id"] == env["unit_b_id"]


def test_unit_list_pages_report_total_count_and_has_more(api):
    """PRD §2.3: "For list responses the `meta` object carries `limit` and `offset` echoing the effective values used, `total_count` giving the number of rows matching the filters before pagination is applied, and `has_more` indicating whether any rows remain beyond the current page."

    PRD §2.3: "`limit` controls page size: it defaults to 10 when omitted, may not be below 1, and may not exceed 100."

    Design: Corner/entities/unit_retrieval_and_filtered_pagination
    """
    env = fixtures.setup_network(credentials=(), equipment=())

    first_rows, first_meta = validate_paginated(
        api.list_nicu_units(env["admin"], {"limit": 1, "offset": 0})
    )
    assert len(first_rows) == 1
    assert first_meta["limit"] == 1
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 2
    assert first_meta["has_more"] is True

    second_rows, second_meta = validate_paginated(
        api.list_nicu_units(env["admin"], {"limit": 1, "offset": 1})
    )
    assert len(second_rows) == 1
    assert second_meta["offset"] == 1
    assert second_meta["total_count"] == 2
    assert second_meta["has_more"] is False


def test_reading_one_unit_returns_the_stored_row_in_the_standard_envelope(api):
    """PRD §3.1: "Units may be listed and filtered by `hospital_type`, by `designation_status` and by `census_posture`, and reading a single unit recomputes every derived capability and bed figure described in §2.7 and §2.8 before responding."

    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/entities/unit_retrieval_and_filtered_pagination
    """
    env = fixtures.setup_network(credentials=(), equipment=())

    response = api.get_nicu_unit(env["unit_a_id"], env["dir_a"])
    unit = validate_success(response)

    assert unit["name"] == "Regional NICU A"
    assert unit["staffed_bed_target"] == 4
    assert unit["designated_level"] == "LEVEL_III"
    assert unit["version"] == 1
    assertions.assert_nicu_unit(unit)

    meta = response.json()["meta"]
    assert meta["api_request_id"].startswith("req_")
    assert_timestamp_format(meta["api_request_timestamp"])


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def test_each_unresolvable_path_id_returns_its_own_not_found_code(api):
    """PRD §2.10: "Path existence: every `id` appearing in the URL path must resolve to a stored row, resolved strictly left to right, else the matching not-found code for that entity (404)."

    PRD §2.10: "Each identifier the API accepts has exactly one not-found code, and the same code is used whether the identifier arrived in the path or in the body."

    Design: Corner/entities/every_path_id_not_found_returns_its_entity_code
    """
    fixtures.set_clock()
    admin = make_network_admin_headers()

    reads = (
        (api.get_nicu_unit, ApiErrorId.UNIT_NOT_FOUND),
        (api.get_designation_standard, ApiErrorId.STANDARD_NOT_FOUND),
        (api.get_staff_credential, ApiErrorId.CREDENTIAL_NOT_FOUND),
        (api.get_equipment_asset, ApiErrorId.ASSET_NOT_FOUND),
        (api.get_designation_review, ApiErrorId.REVIEW_NOT_FOUND),
        (api.get_referral, ApiErrorId.REFERRAL_NOT_FOUND),
        (api.get_bed_reservation, ApiErrorId.RESERVATION_NOT_FOUND),
        (api.get_transport_run, ApiErrorId.RUN_NOT_FOUND),
        (api.get_admission, ApiErrorId.ADMISSION_NOT_FOUND),
        (api.get_milk_batch, ApiErrorId.MILK_BATCH_NOT_FOUND),
        (api.get_surge_escalation, ApiErrorId.ESCALATION_NOT_FOUND),
        (api.get_surveillance_report, ApiErrorId.REPORT_NOT_FOUND),
        (api.get_follow_up_enrollment, ApiErrorId.ENROLLMENT_NOT_FOUND),
    )

    for read, expected_error in reads:
        validate_error(read(NON_EXISTENT_UUID, admin), expected_error)


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------


def test_unit_registration_without_a_staffed_bed_target_is_refused(api):
    """PRD §2.10: "Request schema: required fields present, types correct, enum values in range, numbers inside their declared bounds, `period_end` strictly after `period_start`, `planned_return_at` strictly after `depart_at`, `effective_to` strictly after `effective_from`, `limit` between 1 and 100 inclusive and `offset` at least 0 — else `ERR_INVALID_REQUEST` (400)."

    PRD §3.1: "A `NetworkAdmin` registers each participating hospital's neonatal unit, supplying a display `name`, a `hospital_type` of either `REGIONAL_CENTER` or `COMMUNITY`, and a `staffed_bed_target` of at least one bed."

    Design: Corner/entities/missing_required_fields_return_invalid_request
    """
    env = fixtures.setup_network(credentials=(), equipment=())

    payload = factories.nicu_unit_payload(
        name="No Beds Declared", hospital_type="COMMUNITY", staffed_bed_target=1
    )
    payload.pop("staffed_bed_target")

    validate_error(api.create_nicu_unit(payload, env["admin"]), ApiErrorId.INVALID_REQUEST)

    _, meta = validate_paginated(api.list_nicu_units(env["admin"]))
    assert meta["total_count"] == 2


def test_referral_without_a_support_modality_is_refused(api):
    """PRD §2.10: "Request schema: required fields present, types correct, enum values in range, numbers inside their declared bounds, `period_end` strictly after `period_start`, `planned_return_at` strictly after `depart_at`, `effective_to` strictly after `effective_from`, `limit` between 1 and 100 inclusive and `offset` at least 0 — else `ERR_INVALID_REQUEST` (400)."

    PRD §3.3: "A `ReferringClinician` opens a case by naming the `referring_unit_id` it acts for and the `receiving_unit_id` it is asking to accept, a `referral_kind` of `INBOUND_NEONATAL`, `MATERNAL_ANTENATAL` or `BACK_TRANSFER`, a de-identified `case_reference`, a `gestational_age_weeks` decimal between 20.0 and 44.0 inclusive, a `birth_weight_grams` of at least 300 (for an antenatal case this is the estimated fetal weight), and a `support_modality` of `ROOM_AIR`, `CPAP`, `CONVENTIONAL_VENT`, `HFOV`, `INHALED_NO` or `ECMO_CONSULT`."

    Design: Corner/entities/missing_required_fields_return_invalid_request
    """
    env = fixtures.setup_network(credentials=(), equipment=())

    payload = factories.referral_payload(
        env["unit_b_id"],
        env["unit_a_id"],
        case_reference="CASE-R0",
        gestational_age_weeks=30.0,
        birth_weight_grams=1300,
    )
    payload.pop("support_modality")

    validate_error(api.create_referral(payload, env["ref_b"]), ApiErrorId.INVALID_REQUEST)

    _, meta = validate_paginated(api.list_referrals(env["admin"]))
    assert meta["total_count"] == 0


def test_credential_without_an_expiry_instant_is_refused(api):
    """PRD §2.10: "Request schema: required fields present, types correct, enum values in range, numbers inside their declared bounds, `period_end` strictly after `period_start`, `planned_return_at` strictly after `depart_at`, `effective_to` strictly after `effective_from`, `limit` between 1 and 100 inclusive and `offset` at least 0 — else `ERR_INVALID_REQUEST` (400)."

    PRD §3.1: "A credential is recorded with the `unit_id` that holds it, a `credential_code` drawn from `NEO_BOARD`, `NNP`, `RN_NICU_CORE`, `RT_NEO`, `TRANSPORT_RN`, `LACTATION_IBCLC` or `DEV_CARE_CERT`, a de-identified `holder_reference`, an `fte` strictly greater than zero giving the full-time-equivalent that holder contributes, and an `expires_on` expiry instant."

    Design: Corner/entities/missing_required_fields_return_invalid_request
    """
    env = fixtures.setup_network(credentials=(), equipment=())

    payload = factories.staff_credential_payload(
        env["unit_a_id"], credential_code="RN_NICU_CORE", holder_reference="rn-x", fte=1.0
    )
    payload.pop("expires_on")

    validate_error(api.create_staff_credential(payload, env["dir_a"]), ApiErrorId.INVALID_REQUEST)

    _, meta = validate_paginated(api.list_staff_credentials(env["admin"]))
    assert meta["total_count"] == 0


def test_surveillance_report_without_the_device_denominator_is_refused(api):
    """PRD §2.10: "Request schema: required fields present, types correct, enum values in range, numbers inside their declared bounds, `period_end` strictly after `period_start`, `planned_return_at` strictly after `depart_at`, `effective_to` strictly after `effective_from`, `limit` between 1 and 100 inclusive and `offset` at least 0 — else `ERR_INVALID_REQUEST` (400)."

    PRD §3.9: "A `UnitDirector` opens a surveillance report for its unit by naming the `unit_id`, a `period_start` (inclusive) and a `period_end` (inclusive and strictly after the start), and the two denominators the unit has counted itself: `reported_patient_days` and `reported_central_line_days`, each at least zero."

    Design: Corner/entities/missing_required_fields_return_invalid_request
    """
    env = fixtures.setup_network(credentials=(), equipment=())

    payload = factories.surveillance_report_payload(
        env["unit_a_id"],
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-31T00:00:00Z",
        reported_patient_days=10,
    )
    payload.pop("reported_central_line_days")

    validate_error(
        api.create_surveillance_report(payload, env["dir_a"]), ApiErrorId.INVALID_REQUEST
    )

    _, meta = validate_paginated(api.list_surveillance_reports(env["admin"]))
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Server-owned and derived fields cannot be supplied
# ---------------------------------------------------------------------------


def test_supplied_identity_and_version_are_replaced_by_server_values(api):
    """PRD §2.4: "Every stored resource is identified by `id`, a server-minted UUID with no type prefix — no `unit_` or `ref_` decoration, just the UUID."

    PRD §2.4: "Alongside `id`, resources carry `created_at` and `updated_at` — ISO 8601 UTC timestamps rendered with exactly three fractional-second digits — and `version`, an integer that begins at 1 when the resource is created and increases by one on every mutation of that resource."

    Design: Corner/entities/computed_and_system_field_input_ignored
    """
    admin = make_network_admin_headers()
    fixtures.set_clock()
    fixtures.declare_standards(headers=admin)

    payload = factories.nicu_unit_payload(
        name="Injection Attempt",
        hospital_type="REGIONAL_CENTER",
        staffed_bed_target=4,
        designated_level="LEVEL_III",
        id=NON_EXISTENT_UUID,
        version=99,
        designation_status="DESIGNATED",
        capability_level="LEVEL_IV",
        available_bed_count=99,
        census_posture="CLOSED",
    )

    unit = validate_success(api.create_nicu_unit(payload, admin), 201)

    assert unit["id"] != NON_EXISTENT_UUID
    assert is_valid_uuid(unit["id"])
    assert unit["version"] == 1
    _assert_instant(unit["created_at"], CLOCK_START)


def test_supplied_status_and_counter_values_are_recomputed_by_the_server(api):
    """PRD §3.1: "A newly registered unit begins at `designation_status` `PROVISIONAL` and at `quality_flag` `WITHIN_BENCHMARK`, the latter being replaced only when the network accepts a surveillance report as described in §3.9."

    PRD §3.1: "Nothing else about a unit is editable — `designated_level` moves only by certification, and every counter and posture field is derived rather than stored input."

    PRD §2.7: "`capability_level` is what the unit can currently prove — the highest-ranking level among the declared standards that the unit satisfies, falling back to `LEVEL_I` when it satisfies none of them, because a newborn nursery baseline is statutory and a unit is never rated below `LEVEL_I`."

    Design: Corner/entities/computed_and_system_field_input_ignored
    """
    admin = make_network_admin_headers()
    fixtures.set_clock()
    fixtures.declare_standards(headers=admin)

    payload = factories.nicu_unit_payload(
        name="Injection Attempt",
        hospital_type="REGIONAL_CENTER",
        staffed_bed_target=4,
        designated_level="LEVEL_III",
        id=NON_EXISTENT_UUID,
        version=99,
        designation_status="DESIGNATED",
        capability_level="LEVEL_IV",
        available_bed_count=99,
        census_posture="CLOSED",
    )

    unit = validate_success(api.create_nicu_unit(payload, admin), 201)

    assert unit["designation_status"] == "PROVISIONAL"
    assert unit["capability_level"] == "LEVEL_I"
    assert unit["effective_level"] == "LEVEL_I"
    assertions.assert_unit_counts(unit, available=4, posture="OPEN")


# ---------------------------------------------------------------------------
# Designation standards
# ---------------------------------------------------------------------------


def test_designation_standard_carries_no_version_and_no_updated_at(api):
    """PRD §2.4: "One entity is deliberately exempt: a designation standard is immutable once declared, so it carries only `id` and `created_at`."

    PRD §2.4: "It has no `updated_at` and no `version` field at all, there is no edit endpoint for it, and it never participates in optimistic concurrency control."

    Design: Corner/entities/designation_standard_is_immutable_and_unique_per_level
    """
    admin = make_network_admin_headers()
    fixtures.set_clock()
    standards = fixtures.declare_standards(FOUR_LEVELS, admin)

    standard = validate_success(
        api.get_designation_standard(standards["LEVEL_III"]["id"], admin)
    )

    assertions.assert_immutable_resource_fields(standard)
    assertions.assert_designation_standard(standard)
    assert standard["level"] == "LEVEL_III"
    _assert_instant(standard["created_at"], CLOCK_START)


def test_second_standard_for_a_level_is_refused_and_leaves_the_first_intact(api):
    """PRD §3.1: "Only one standard may exist per level; a second declaration for the same `level` is refused with `ERR_DUPLICATE_STANDARD`."

    Design: Corner/entities/designation_standard_is_immutable_and_unique_per_level
    """
    admin = make_network_admin_headers()
    fixtures.set_clock()
    fixtures.declare_standards(FOUR_LEVELS, admin)

    duplicate = factories.designation_standard_payload(
        "LEVEL_III",
        required_credential_codes=["NEO_BOARD"],
        required_equipment_codes=["HFOV"],
        nurse_patient_ratio_denominator=2.5,
        min_annual_volume=400,
        min_compliance_score=80.00,
        conditional_floor_score=60.00,
    )
    validate_error(
        api.create_designation_standard(duplicate, admin), ApiErrorId.DUPLICATE_STANDARD
    )

    rows, meta = validate_paginated(
        api.list_designation_standards(admin, {"level": "LEVEL_III"})
    )
    assert meta["total_count"] == 1
    survivor = rows[0]
    assertions.assert_close(survivor["nurse_patient_ratio_denominator"], 2.0)
    assertions.assert_close(survivor["min_compliance_score"], 85.00)
    assertions.assert_close(survivor["conditional_floor_score"], 70.00)


# ---------------------------------------------------------------------------
# Type, enum, bound and interval constraints
# ---------------------------------------------------------------------------


def test_enum_value_outside_the_support_modality_range_is_refused(api):
    """PRD §2.10: "Request schema: required fields present, types correct, enum values in range, numbers inside their declared bounds, `period_end` strictly after `period_start`, `planned_return_at` strictly after `depart_at`, `effective_to` strictly after `effective_from`, `limit` between 1 and 100 inclusive and `offset` at least 0 — else `ERR_INVALID_REQUEST` (400)."

    PRD §3.3: "A `ReferringClinician` opens a case by naming the `referring_unit_id` it acts for and the `receiving_unit_id` it is asking to accept, a `referral_kind` of `INBOUND_NEONATAL`, `MATERNAL_ANTENATAL` or `BACK_TRANSFER`, a de-identified `case_reference`, a `gestational_age_weeks` decimal between 20.0 and 44.0 inclusive, a `birth_weight_grams` of at least 300 (for an antenatal case this is the estimated fetal weight), and a `support_modality` of `ROOM_AIR`, `CPAP`, `CONVENTIONAL_VENT`, `HFOV`, `INHALED_NO` or `ECMO_CONSULT`."

    Design: Corner/entities/type_constraint_violations_return_invalid_request
    """
    env = fixtures.setup_network(credentials=(), equipment=())

    payload = factories.referral_payload(
        env["unit_b_id"],
        env["unit_a_id"],
        case_reference="CASE-T1",
        gestational_age_weeks=30.0,
        birth_weight_grams=1300,
        support_modality="MOON_AIR",
    )

    validate_error(api.create_referral(payload, env["ref_b"]), ApiErrorId.INVALID_REQUEST)

    _, meta = validate_paginated(api.list_referrals(env["admin"]))
    assert meta["total_count"] == 0


def test_staffed_bed_target_below_its_declared_bound_is_refused(api):
    """PRD §2.10: "Request schema: required fields present, types correct, enum values in range, numbers inside their declared bounds, `period_end` strictly after `period_start`, `planned_return_at` strictly after `depart_at`, `effective_to` strictly after `effective_from`, `limit` between 1 and 100 inclusive and `offset` at least 0 — else `ERR_INVALID_REQUEST` (400)."

    PRD §3.1: "A `NetworkAdmin` registers each participating hospital's neonatal unit, supplying a display `name`, a `hospital_type` of either `REGIONAL_CENTER` or `COMMUNITY`, and a `staffed_bed_target` of at least one bed."

    Design: Corner/entities/type_constraint_violations_return_invalid_request
    """
    env = fixtures.setup_network(credentials=(), equipment=())

    payload = factories.nicu_unit_payload(
        name="Zero Beds", hospital_type="COMMUNITY", staffed_bed_target=0
    )

    validate_error(api.create_nicu_unit(payload, env["admin"]), ApiErrorId.INVALID_REQUEST)

    _, meta = validate_paginated(api.list_nicu_units(env["admin"]))
    assert meta["total_count"] == 2


def test_surge_window_that_ends_before_it_starts_is_refused_as_malformed(api):
    """PRD §2.10: "Request schema: required fields present, types correct, enum values in range, numbers inside their declared bounds, `period_end` strictly after `period_start`, `planned_return_at` strictly after `depart_at`, `effective_to` strictly after `effective_from`, `limit` between 1 and 100 inclusive and `offset` at least 0 — else `ERR_INVALID_REQUEST` (400)."

    PRD §2.10: "Checks are evaluated in the following fixed order, and the first failure is returned immediately."

    Design: Corner/entities/type_constraint_violations_return_invalid_request
    """
    env = fixtures.setup_network(credentials=(), equipment=())

    payload = factories.surge_escalation_payload(
        env["unit_a_id"],
        requested_beds=2,
        effective_from="2026-08-02T00:00:00Z",
        effective_to="2026-08-01T00:00:00Z",
    )

    validate_error(api.create_surge_escalation(payload, env["dir_a"]), ApiErrorId.INVALID_REQUEST)

    _, meta = validate_paginated(api.list_surge_escalations(env["admin"]))
    assert meta["total_count"] == 0


def test_page_size_above_one_hundred_is_refused(api):
    """PRD §2.3: "`limit` controls page size: it defaults to 10 when omitted, may not be below 1, and may not exceed 100."

    PRD §2.3: "A `limit` outside the range of 1 to 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/type_constraint_violations_return_invalid_request
    """
    env = fixtures.setup_network(credentials=(), equipment=())

    validate_error(
        api.list_nicu_units(env["admin"], {"limit": 101}), ApiErrorId.INVALID_REQUEST
    )


# ---------------------------------------------------------------------------
# Foreign keys carried in the request body
# ---------------------------------------------------------------------------


def test_unresolvable_body_foreign_keys_are_refused_with_their_own_codes(api):
    """PRD §2.10: "Body existence: every `id` supplied in the request body must resolve — `unit_id`, `referral_id`, `admission_id`, `isolette_asset_id`, `clinic_unit_id`, `reservation_id` — else the matching not-found code (404)."

    PRD §2.10: "Each identifier the API accepts has exactly one not-found code, and the same code is used whether the identifier arrived in the path or in the body."

    Design: Corner/entities/body_foreign_keys_must_resolve_before_use
    """
    env = fixtures.setup_network(with_isolette=True)
    isolette_id = env["assets"]["TRANSPORT_ISOLETTE"]["id"]

    validate_error(
        api.create_staff_credential(
            factories.staff_credential_payload(
                NON_EXISTENT_UUID,
                credential_code="RN_NICU_CORE",
                holder_reference="rn-y",
                fte=1.0,
            ),
            env["admin"],
        ),
        ApiErrorId.UNIT_NOT_FOUND,
    )

    validate_error(
        api.create_admission(factories.admission_payload(NON_EXISTENT_UUID), env["intake_a"]),
        ApiErrorId.REFERRAL_NOT_FOUND,
    )

    validate_error(
        api.create_transport_run(
            factories.transport_run_payload(
                NON_EXISTENT_UUID, isolette_id, crew_composition=["TRANSPORT_RN"]
            ),
            env["coord"],
        ),
        ApiErrorId.RESERVATION_NOT_FOUND,
    )

    validate_error(
        api.create_milk_batch(
            factories.milk_batch_payload(NON_EXISTENT_UUID, label_code="LBL-Z"), env["nurse"]
        ),
        ApiErrorId.ADMISSION_NOT_FOUND,
    )

    validate_error(
        api.create_follow_up_enrollment(
            factories.follow_up_enrollment_payload(
                NON_EXISTENT_UUID,
                env["unit_a_id"],
                target_appointment_date="2026-09-01T09:00:00Z",
            ),
            env["fu"],
        ),
        ApiErrorId.ADMISSION_NOT_FOUND,
    )

    # The two credentials the unit already holds are the only rows any of these calls
    # could have added to, and no run, admission, batch or enrollment was written.
    _, credential_meta = validate_paginated(api.list_staff_credentials(env["admin"]))
    assert credential_meta["total_count"] == 2
    for listing in (
        api.list_admissions(env["admin"]),
        api.list_transport_runs(env["admin"]),
        api.list_milk_batches(env["admin"]),
        api.list_follow_up_enrollments(env["admin"]),
    ):
        _, meta = validate_paginated(listing)
        assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# A hold is reachable from both sides
# ---------------------------------------------------------------------------


def test_hold_is_listed_by_its_referral_and_by_its_unit(api):
    """PRD §3.4: "A permitted acceptance moves the referral `PENDING → ACCEPTED` and creates a bed reservation for it, carrying the receiving unit as `unit_id` and the referral as `referral_id`, starting at status `HELD`, taking its `bed_class` from the waterfall rule of §2.8, stamping `held_at` with the current clock instant, and computing `expires_at` from the referral's kind: an antenatal hold lasts 720 minutes — twelve hours — from `held_at`, because a mother in labour needs a bed that will still be there tomorrow morning, while every other kind of hold lasts 240 minutes, four hours."

    PRD §3.4: "Reservations themselves are read-only through the API and may be listed filtered by `unit_id`, `referral_id`, `status` and `bed_class`; a reservation's `status` is one of `HELD`, `OCCUPIED`, `RELEASED` or `EXPIRED`, and its `released_reason` — null while the hold is live — takes one of `ADMITTED`, `REVOKED`, `REFERRAL_WITHDRAWN`, `CAPABILITY_LOST`, `TRANSPORT_ABORTED` or `HOLD_EXPIRED`."

    PRD §2.8: "First, allocation is a **waterfall**: a new hold takes `bed_class` `STAFFED` while the pre-operation sum of `occupied_bed_count` and `held_bed_count` is strictly below `staffed_bed_target`, and `ESCALATION` otherwise."

    Design: Corner/entities/reservation_is_reachable_from_its_referral_and_its_unit
    """
    env = fixtures.setup_network()
    referral, accepted = fixtures.hold_bed(env)
    reservation_id = accepted["reservation_id"]

    by_referral, by_referral_meta = validate_paginated(
        api.list_bed_reservations(env["intake_a"], {"referral_id": referral["id"]})
    )
    assert by_referral_meta["total_count"] == 1
    assert len(by_referral) == 1
    assert by_referral[0]["id"] == reservation_id

    reservation = validate_success(api.get_bed_reservation(reservation_id, env["admin"]))
    assertions.assert_bed_reservation(reservation)
    assert reservation["unit_id"] == env["unit_a_id"]
    assert reservation["referral_id"] == referral["id"]
    assert reservation["status"] == "HELD"
    assert reservation["bed_class"] == "STAFFED"
    _assert_instant(reservation["held_at"], CLOCK_START)
    _assert_instant(reservation["expires_at"], "2026-08-01T04:00:00Z")

    _, by_unit_meta = validate_paginated(
        api.list_bed_reservations(env["admin"], {"unit_id": env["unit_a_id"], "status": "HELD"})
    )
    assert by_unit_meta["total_count"] == 1


def test_accepted_referral_points_back_at_its_live_hold(api):
    """PRD §3.3: "The referral's `reservation_id` is a read-only pointer, derived from the reservations that name the referral rather than stored as a foreign key: it names the referral's current `HELD` or `OCCUPIED` reservation, or the most recently released one when none is live, and stays null while the referral has never been accepted."

    PRD §2.8: "Its `held_bed_count` is the number of the unit's bed reservations in status `HELD`."

    PRD §2.8: "And `available_bed_count` is the base staffed bed target plus the escalation bed count, minus the occupied bed count, minus the held bed count."

    Design: Corner/entities/reservation_is_reachable_from_its_referral_and_its_unit
    """
    env = fixtures.setup_network()
    _, accepted = fixtures.hold_bed(env)
    reservation_id = accepted["reservation_id"]

    rows, meta = validate_paginated(
        api.list_referrals(
            env["admin"], {"receiving_unit_id": env["unit_a_id"], "status": "ACCEPTED"}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["reservation_id"] == reservation_id

    unit = validate_success(api.get_nicu_unit(env["unit_a_id"], env["admin"]))
    assertions.assert_unit_counts(unit, occupied=0, held=1, available=3)


# ---------------------------------------------------------------------------
# The narrow capacity edit
# ---------------------------------------------------------------------------


def test_capacity_edit_writes_only_the_supplied_field_and_re_derives_the_rest(api):
    """PRD §3.1: "A `NetworkAdmin` or the unit's own `UnitDirector` may revise `staffed_bed_target`, `followup_clinic_daily_capacity`, `annual_admission_volume` and `transport_capable`, each optionally, but the request must carry `expected_unit_version` as described in §2.6."

    PRD §3.1: "Nothing else about a unit is editable — `designated_level` moves only by certification, and every counter and posture field is derived rather than stored input."

    Design: Corner/endpoints/patch_unit_writes_only_the_supplied_capacity_fields
    """
    env = fixtures.setup_network()
    fixtures.hold_bed(env)

    current_version = fixtures.read_unit_version(env)
    unit = validate_success(
        api.patch_nicu_unit(
            env["unit_a_id"],
            factories.unit_patch_payload(current_version, followup_clinic_daily_capacity=5),
            env["dir_a"],
        )
    )

    assert unit["followup_clinic_daily_capacity"] == 5
    assert unit["staffed_bed_target"] == 4
    assert unit["annual_admission_volume"] == 400
    assert unit["transport_capable"] is True
    assert unit["designated_level"] == "LEVEL_III"
    assertions.assert_unit_counts(unit, occupied=0, held=1, available=3, posture="OPEN")


def test_capacity_edit_advances_the_version_and_refreshes_updated_at(api):
    """PRD §2.4: "Alongside `id`, resources carry `created_at` and `updated_at` — ISO 8601 UTC timestamps rendered with exactly three fractional-second digits — and `version`, an integer that begins at 1 when the resource is created and increases by one on every mutation of that resource."

    PRD §2.4: "`updated_at` is refreshed to the current clock instant by the same mutation that advances `version`."

    Design: Corner/endpoints/patch_unit_writes_only_the_supplied_capacity_fields
    """
    env = fixtures.setup_network()
    fixtures.hold_bed(env)

    current_version = fixtures.read_unit_version(env)
    assert current_version == 2

    unit = validate_success(
        api.patch_nicu_unit(
            env["unit_a_id"],
            factories.unit_patch_payload(current_version, followup_clinic_daily_capacity=5),
            env["dir_a"],
        )
    )

    assert unit["version"] == 3
    _assert_instant(unit["updated_at"], CLOCK_START)
    _assert_instant(unit["created_at"], env["unit_a"]["created_at"])


# ---------------------------------------------------------------------------
# Transport activation against a held bed
# ---------------------------------------------------------------------------


def test_activation_refuses_an_asset_that_is_not_a_transport_isolette(api):
    """PRD §3.6: "The asset must be a `TRANSPORT_ISOLETTE` whose derived `status` is `IN_SERVICE` — an asset that is `OUT_OF_SERVICE` or `SERVICE_DUE`, or one whose `equipment_code` is something other than a transport isolette, is refused with `ERR_ISOLETTE_NOT_SERVICEABLE`."

    Design: Corner/endpoints/transport_run_creation_links_a_reservation_to_an_isolette
    """
    env = fixtures.setup_network(with_isolette=True)
    _, accepted = fixtures.hold_bed(env)

    validate_error(
        api.create_transport_run(
            factories.transport_run_payload(
                accepted["reservation_id"],
                env["assets"]["CONVENTIONAL_VENT"]["id"],
                crew_composition=["TRANSPORT_RN"],
            ),
            env["coord"],
        ),
        ApiErrorId.ISOLETTE_NOT_SERVICEABLE,
    )

    _, meta = validate_paginated(api.list_transport_runs(env["admin"]))
    assert meta["total_count"] == 0


def test_activation_refuses_an_isolette_belonging_to_another_unit(api):
    """PRD §3.6: "The asset must belong to the same unit as the run's receiving unit, or the activation is refused with `ERR_ISOLETTE_UNIT_MISMATCH`."

    Design: Corner/endpoints/transport_run_creation_links_a_reservation_to_an_isolette
    """
    env = fixtures.setup_network(with_isolette=True)
    isolette_b = fixtures.add_equipment(
        env["unit_b_id"],
        equipment_code="TRANSPORT_ISOLETTE",
        asset_tag="ISO-B",
        headers=env["dir_b"],
    )
    _, accepted = fixtures.hold_bed(env)

    validate_error(
        api.create_transport_run(
            factories.transport_run_payload(
                accepted["reservation_id"], isolette_b["id"], crew_composition=["TRANSPORT_RN"]
            ),
            env["coord"],
        ),
        ApiErrorId.ISOLETTE_UNIT_MISMATCH,
    )

    _, meta = validate_paginated(api.list_transport_runs(env["admin"]))
    assert meta["total_count"] == 0


def test_activation_copies_the_receiving_unit_and_derives_the_decontamination_time(api):
    """PRD §3.6: "The run's `receiving_unit_id` is copied from the reservation rather than supplied, and the run opens at status `ACTIVATED`."

    PRD §3.6: "Its `decontamination_minutes` is derived from the mode: 45 minutes for a `GROUND` run, and 90 minutes — an hour and a half — for both `ROTOR_WING` and `FIXED_WING`, because an aircraft cabin takes longer to turn round than an ambulance."

    PRD §3.6: "Runs may be listed filtered by `reservation_id`, `receiving_unit_id`, `isolette_asset_id`, `status` and `mode`."

    Design: Corner/endpoints/transport_run_creation_links_a_reservation_to_an_isolette
    """
    env = fixtures.setup_network(with_isolette=True)
    _, accepted = fixtures.hold_bed(env)
    reservation_id = accepted["reservation_id"]

    run = validate_success(
        api.create_transport_run(
            factories.transport_run_payload(
                reservation_id, env["assets"]["TRANSPORT_ISOLETTE"]["id"], mode="GROUND"
            ),
            env["coord"],
        ),
        201,
    )

    assertions.assert_transport_run(run)
    assert run["status"] == "ACTIVATED"
    assert run["receiving_unit_id"] == env["unit_a_id"]
    assert run["reservation_id"] == reservation_id
    assert run["mode"] == "GROUND"
    assert run["decontamination_minutes"] == 45

    _, meta = validate_paginated(
        api.list_transport_runs(env["admin"], {"reservation_id": reservation_id})
    )
    assert meta["total_count"] == 1


def test_ground_dispatch_rolls_the_run_and_stamps_the_isolette(api):
    """PRD §3.6: "A ground dispatch moves the run `ACTIVATED → GROUND_ROLLING`; it requires `mode` to be `GROUND`, requires `crew_composition` to contain `TRANSPORT_RN`, and requires the assigned isolette's derived `status` to be `IN_SERVICE`; it then sets that isolette's `decontamination_ready_at` to `planned_return_at` advanced by 45 minutes."

    Design: Corner/endpoints/transport_run_creation_links_a_reservation_to_an_isolette
    """
    env = fixtures.setup_network(with_isolette=True)
    isolette_id = env["assets"]["TRANSPORT_ISOLETTE"]["id"]
    _, accepted = fixtures.hold_bed(env)
    run = fixtures.create_run(env, accepted["reservation_id"], mode="GROUND")

    dispatched = validate_success(api.dispatch_transport_run(run["id"], {}, env["coord"]))
    assert dispatched["status"] == "GROUND_ROLLING"

    asset = validate_success(api.get_equipment_asset(isolette_id, env["coord"]))
    _assert_instant(asset["decontamination_ready_at"], "2026-08-01T05:45:00Z")


# ---------------------------------------------------------------------------
# The dispatch gates
# ---------------------------------------------------------------------------


def test_air_dispatch_without_attested_weather_minimums_is_refused(api):
    """PRD §3.6: "An air dispatch moves the run `ACTIVATED → AIR_LAUNCHED`; it requires `mode` to be either `ROTOR_WING` or `FIXED_WING`, requires `weather_minimums_met` to be true, requires `crew_composition` to contain `TRANSPORT_RN`, and requires the isolette's derived `status` to be `IN_SERVICE`; it then sets that isolette's `decontamination_ready_at` to `planned_return_at` advanced by 90 minutes."

    PRD §3.6: "A crew missing `TRANSPORT_RN` is refused with `ERR_CREW_COMPOSITION_INVALID`, an unserviceable isolette with `ERR_ISOLETTE_NOT_SERVICEABLE`, and an air dispatch attempted with `weather_minimums_met` false with `ERR_WEATHER_MINIMUMS_NOT_MET`."

    Design: Corner/endpoints/dispatch_gates_weather_crew_and_isolette_status
    """
    env = fixtures.setup_network(with_isolette=True)
    _, accepted = fixtures.hold_bed(env)
    run = fixtures.create_run(
        env,
        accepted["reservation_id"],
        mode="ROTOR_WING",
        weather_minimums_met=False,
    )

    validate_error(
        api.dispatch_transport_run(run["id"], {}, env["coord"]),
        ApiErrorId.WEATHER_MINIMUMS_NOT_MET,
    )


def test_dispatch_without_a_transport_rn_on_the_crew_is_refused(api):
    """PRD §3.6: "A ground dispatch moves the run `ACTIVATED → GROUND_ROLLING`; it requires `mode` to be `GROUND`, requires `crew_composition` to contain `TRANSPORT_RN`, and requires the assigned isolette's derived `status` to be `IN_SERVICE`; it then sets that isolette's `decontamination_ready_at` to `planned_return_at` advanced by 45 minutes."

    PRD §3.6: "A crew missing `TRANSPORT_RN` is refused with `ERR_CREW_COMPOSITION_INVALID`, an unserviceable isolette with `ERR_ISOLETTE_NOT_SERVICEABLE`, and an air dispatch attempted with `weather_minimums_met` false with `ERR_WEATHER_MINIMUMS_NOT_MET`."

    Design: Corner/endpoints/dispatch_gates_weather_crew_and_isolette_status
    """
    env = fixtures.setup_network(with_isolette=True)
    _, accepted = fixtures.hold_bed(env)
    run = fixtures.create_run(
        env,
        accepted["reservation_id"],
        mode="GROUND",
        crew_composition=["TRANSPORT_RT"],
        depart_at="2026-08-01T07:00:00Z",
        planned_return_at="2026-08-01T08:00:00Z",
    )

    validate_error(
        api.dispatch_transport_run(run["id"], {}, env["coord"]),
        ApiErrorId.CREW_COMPOSITION_INVALID,
    )


def test_dispatch_re_derives_the_isolette_status_rather_than_freezing_it(api):
    """PRD §2.5: "An equipment asset's `status` is `OUT_OF_SERVICE` when its `out_of_service_at` is non-null; otherwise it is `SERVICE_DUE` when its `next_service_due_at` is at or before the current clock instant; otherwise it is `IN_SERVICE`."

    PRD §3.6: "A ground dispatch moves the run `ACTIVATED → GROUND_ROLLING`; it requires `mode` to be `GROUND`, requires `crew_composition` to contain `TRANSPORT_RN`, and requires the assigned isolette's derived `status` to be `IN_SERVICE`; it then sets that isolette's `decontamination_ready_at` to `planned_return_at` advanced by 45 minutes."

    Design: Corner/endpoints/dispatch_gates_weather_crew_and_isolette_status
    """
    env = fixtures.setup_network(with_isolette=True)
    isolette_id = env["assets"]["TRANSPORT_ISOLETTE"]["id"]
    _, accepted = fixtures.hold_bed(env)
    run = fixtures.create_run(
        env,
        accepted["reservation_id"],
        mode="GROUND",
        crew_composition=["TRANSPORT_RN"],
        depart_at="2026-08-01T09:00:00Z",
        planned_return_at="2026-08-01T10:00:00Z",
    )

    validate_success(
        api.take_equipment_asset_out_of_service(
            isolette_id, factories.out_of_service_payload("BIOMED_FAULT"), env["dir_a"]
        )
    )

    validate_error(
        api.dispatch_transport_run(run["id"], {}, env["coord"]),
        ApiErrorId.ISOLETTE_NOT_SERVICEABLE,
    )


def test_losing_the_isolette_leaves_level_iii_commitments_untouched(api):
    """PRD §3.8: "In one operation, the asset's `out_of_service_at` is stamped at the current clock instant, making its derived `status` `OUT_OF_SERVICE`; the unit's `equipment_compliant`, `capability_level` and `effective_level` are re-derived; a `designation_status` of `PROVISIONAL` or `DESIGNATED` becomes `CONDITIONAL` when the asset was required for the unit's `designated_level`; every referral at that unit whose status is `PENDING`, `INFO_REQUESTED`, `DEFERRED` or `ACCEPTED` and whose `required_level` now outranks the new `effective_level` is moved to `DIVERTED` with `decision_reason` `CAPABILITY_LOST`, with its `HELD` reservation moved to `RELEASED` with `released_reason` `CAPABILITY_LOST` and any non-terminal transport run against that reservation moved to `ABORTED` with `abort_reason` `CAPABILITY_LOST`; every admission at that unit whose `care_status` is `ADMITTED` or `STABILIZED` and whose `current_care_level` now outranks the new `effective_level` is moved to `BACK_TRANSFER_REQUIRED`; and the unit's `version` advances by one."

    Design: Corner/endpoints/dispatch_gates_weather_crew_and_isolette_status
    """
    env = fixtures.setup_network(with_isolette=True)
    isolette_id = env["assets"]["TRANSPORT_ISOLETTE"]["id"]

    _, accepted_air = fixtures.hold_bed(env, case_reference="CASE-N1")
    _, accepted_crew = fixtures.hold_bed(env, case_reference="CASE-N2")
    _, accepted_iso = fixtures.hold_bed(env, case_reference="CASE-D3")

    run_air = fixtures.create_run(
        env,
        accepted_air["reservation_id"],
        mode="ROTOR_WING",
        weather_minimums_met=False,
    )
    run_crew = fixtures.create_run(
        env,
        accepted_crew["reservation_id"],
        mode="GROUND",
        crew_composition=["TRANSPORT_RT"],
        depart_at="2026-08-01T07:00:00Z",
        planned_return_at="2026-08-01T08:00:00Z",
    )
    run_iso = fixtures.create_run(
        env,
        accepted_iso["reservation_id"],
        mode="GROUND",
        crew_composition=["TRANSPORT_RN"],
        depart_at="2026-08-01T09:00:00Z",
        planned_return_at="2026-08-01T10:00:00Z",
    )

    validate_error(
        api.dispatch_transport_run(run_air["id"], {}, env["coord"]),
        ApiErrorId.WEATHER_MINIMUMS_NOT_MET,
    )
    validate_error(
        api.dispatch_transport_run(run_crew["id"], {}, env["coord"]),
        ApiErrorId.CREW_COMPOSITION_INVALID,
    )
    validate_success(
        api.take_equipment_asset_out_of_service(
            isolette_id, factories.out_of_service_payload("BIOMED_FAULT"), env["dir_a"]
        )
    )
    validate_error(
        api.dispatch_transport_run(run_iso["id"], {}, env["coord"]),
        ApiErrorId.ISOLETTE_NOT_SERVICEABLE,
    )

    unit = validate_success(api.get_nicu_unit(env["unit_a_id"], env["admin"]))
    assert unit["effective_level"] == "LEVEL_III"
    assert unit["equipment_compliant"] is True
    assertions.assert_unit_counts(unit, occupied=0, held=3, available=1)

    for run in (run_air, run_crew, run_iso):
        current = validate_success(api.get_transport_run(run["id"], env["coord"]))
        assert current["status"] == "ACTIVATED"

    referral_rows, referral_meta = validate_paginated(
        api.list_referrals(
            env["admin"], {"receiving_unit_id": env["unit_a_id"], "status": "ACCEPTED"}
        )
    )
    assert referral_meta["total_count"] == 3
    for referral in referral_rows:
        reservation = validate_success(
            api.get_bed_reservation(referral["reservation_id"], env["admin"])
        )
        assert reservation["status"] == "HELD"

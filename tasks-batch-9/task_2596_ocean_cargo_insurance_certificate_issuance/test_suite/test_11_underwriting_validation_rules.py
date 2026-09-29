"""
Underwriting refusals: voyage coherence, valuation inputs, natural keys,
the policy period and the capacity tower.

Every scenario here drives one refusal that a schema validator cannot express —
a reversed voyage, a valuation basis without its inputs, a natural key already
taken, an attachment instant outside the cover, or a line that overflows one of
the nested monetary limits — and pairs it with the neighbouring case that must
still be accepted.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    CERTIFICATE_CIF_SHIPMENT,
    CERTIFICATE_DECLARED_SHIPMENT,
    COMMODITY_CLASS_ELECTRONICS,
    COMPLIANCE_OFFICER,
    ERR_ANNUAL_AGGREGATE_EXCEEDED,
    ERR_CERTIFICATE_LIMIT_EXCEEDED,
    ERR_COMMODITY_SHARE_EXCEEDED,
    ERR_CONVEYANCE_LIMIT_EXCEEDED,
    ERR_DECLARATION_PERIOD_OVERLAP,
    ERR_DUPLICATE_REFERENCE,
    ERR_OUTSIDE_POLICY_PERIOD,
    ERR_VALUATION_INPUT_MISSING,
    ERR_VOYAGE_DATES_INVALID,
    EXPECTED_INSURED_VALUE_CIF,
    PORT_NLRTM,
    PORT_SGSIN,
    PREMIUM_AUDITOR,
    UNDERWRITER,
    VESSEL_KITE,
    ApiClient,
    JsonDict,
    assert_instant,
    assert_money,
    assert_total_count,
    build_canonical_environment,
    build_draft_certificate,
    collect_ids,
    create_commodity_class,
    create_declaration,
    create_open_policy,
    create_port,
    create_vessel,
    issue_certificate,
    make_assured_headers,
    policy_version,
    read_certificate,
    read_policy,
)

# The two ports and the hull carry limits far above every line written below, so
# that only the limit under test can ever be the one that refuses.
WIDE_LIMIT = 8000000

# The half-open cover that expires at the start of September: the boundary the
# attachment instant is tested against.
EXPIRY_SOON = "2026-09-01T00:00:00Z"


def _wide_environment(api: ApiClient, **overrides: object) -> JsonDict:
    """
    The canonical book of business with the vessel and port buckets widened to
    8000000.00 so they cannot interfere with the rule under test.
    """
    return build_canonical_environment(
        api,
        loading_port=dict(PORT_SGSIN, port_accumulation_limit_amount=WIDE_LIMIT),
        discharge_port=dict(PORT_NLRTM, port_accumulation_limit_amount=WIDE_LIMIT),
        vessel=dict(VESSEL_KITE, vessel_accumulation_limit_amount=WIDE_LIMIT),
        **overrides,
    )


def _declaration_payload(env: JsonDict, drop: tuple = (),
                         base: dict = CERTIFICATE_CIF_SHIPMENT,
                         **overrides: object) -> JsonDict:
    """
    A shipment declaration body against `env`, with `drop` naming the money
    fields to leave out entirely so a valuation basis can be starved of inputs.
    """
    payload = dict(base)
    payload.update({
        "open_policy_id": env["policy_id"],
        "commodity_class_id": env["commodity_class_id"],
        "vessel_id": env["vessel_id"],
        "loading_port_id": env["loading_port_id"],
        "discharge_port_id": env["discharge_port_id"],
    })
    payload.update(overrides)
    for field_name in drop:
        payload.pop(field_name, None)
    return payload


def _assert_certificate_rows(api: ApiClient, policy_id: str,
                             expected: int) -> None:
    """Assert the open cover holds exactly `expected` certificate rows."""
    assert_total_count(
        api.list_certificates(UNDERWRITER, {"open_policy_id": policy_id}),
        expected, "certificates of the open cover")


# ---------------------------------------------------------------------------
# Voyage coherence and the valuation inputs, checked when a shipment is declared
# ---------------------------------------------------------------------------
def test_declaration_rejects_a_discharge_earlier_than_the_sailing(api: ApiClient):
    """A voyage discharging before it sails is refused at declaration.

    Fourth, voyage coherence: the sailing instant must be strictly earlier than the discharge instant, so a voyage must span at least one whole day, and both must be whole calendar dates at `00:00:00Z`; a violation is `ERR_VOYAGE_DATES_INVALID` (HTTP 422).

    Design: Corner/validations/certificate_creation_rejects_reversed_dates_and_missing_valuation_inputs
    """
    env = _wide_environment(api)

    response = api.create_certificate(
        _declaration_payload(env, certificate_number="CERT-REV",
                             sailing_date="2026-09-06T00:00:00Z",
                             discharge_date="2026-09-05T00:00:00Z"),
        env["assured"])

    validate_error(response, ERR_VOYAGE_DATES_INVALID)
    _assert_certificate_rows(api, env["policy_id"], 0)


def test_declaration_rejects_a_same_day_voyage(api: ApiClient):
    """A sailing and a discharge on the same calendar date is refused.

    Fourth, voyage coherence: the sailing instant must be strictly earlier than the discharge instant, so a voyage must span at least one whole day, and both must be whole calendar dates at `00:00:00Z`; a violation is `ERR_VOYAGE_DATES_INVALID` (HTTP 422).

    Design: Corner/validations/certificate_creation_rejects_reversed_dates_and_missing_valuation_inputs
    """
    env = _wide_environment(api)

    response = api.create_certificate(
        _declaration_payload(env, certificate_number="CERT-SAMEDAY",
                             sailing_date="2026-09-05T00:00:00Z",
                             discharge_date="2026-09-05T00:00:00Z"),
        env["assured"])

    validate_error(response, ERR_VOYAGE_DATES_INVALID)
    _assert_certificate_rows(api, env["policy_id"], 0)


def test_declared_value_basis_without_a_declared_value_is_refused(api: ApiClient):
    """A declared-value shipment that states no agreed figure is refused.

    Supplying the wrong set is a refusal, not a silent default: `DECLARED_VALUE` without a `declared_value` greater than zero, or `CIF_PLUS_MARKUP` without an `invoice_value` greater than zero, is rejected with `ERR_VALUATION_INPUT_MISSING` (HTTP 422).

    Design: Corner/validations/certificate_creation_rejects_reversed_dates_and_missing_valuation_inputs
    """
    env = _wide_environment(api)

    response = api.create_certificate(
        _declaration_payload(
            env,
            drop=("invoice_value", "freight_amount", "duty_amount"),
            certificate_number="CERT-NODECL",
            valuation_basis="DECLARED_VALUE"),
        env["assured"])

    validate_error(response, ERR_VALUATION_INPUT_MISSING)
    _assert_certificate_rows(api, env["policy_id"], 0)


def test_cif_basis_without_an_invoice_value_is_refused(api: ApiClient):
    """A CIF-plus-markup shipment that states no invoice value is refused.

    Supplying the wrong set is a refusal, not a silent default: `DECLARED_VALUE` without a `declared_value` greater than zero, or `CIF_PLUS_MARKUP` without an `invoice_value` greater than zero, is rejected with `ERR_VALUATION_INPUT_MISSING` (HTTP 422).

    Design: Corner/validations/certificate_creation_rejects_reversed_dates_and_missing_valuation_inputs
    """
    env = _wide_environment(api)

    response = api.create_certificate(
        _declaration_payload(env, drop=("invoice_value",),
                             certificate_number="CERT-NOINV",
                             valuation_basis="CIF_PLUS_MARKUP"),
        env["assured"])

    validate_error(response, ERR_VALUATION_INPUT_MISSING)
    _assert_certificate_rows(api, env["policy_id"], 0)


def test_a_coherent_declaration_previews_its_insured_value(api: ApiClient):
    """The same fixture accepts the shipment once dates and inputs are coherent.

    The insured value is then the CIF base multiplied by one plus the policy's `markup_pct`, and that product is rounded half up to 2 decimals — one rounding, at the very end, never a rounding of the base first.

    Design: Corner/validations/certificate_creation_rejects_reversed_dates_and_missing_valuation_inputs
    """
    env = _wide_environment(api)

    certificate = validate_success(
        api.create_certificate(
            _declaration_payload(env, certificate_number="CERT-OK"),
            env["assured"]),
        201)

    assert_money(certificate["insured_value"], EXPECTED_INSURED_VALUE_CIF,
                 "certificate.insured_value")
    assert certificate["status"] == "DRAFT", (
        f"a declared shipment must land in DRAFT, got {certificate['status']}"
    )
    policy = read_policy(api, env["policy_id"])
    assert policy["certificates_issued_count"] == 0, (
        "declaring a shipment must not touch the issued-certificate counter"
    )


# ---------------------------------------------------------------------------
# One refusal code guards six natural keys, each unique across its whole
# collection rather than within a parent
# ---------------------------------------------------------------------------
def test_a_second_policy_number_is_refused(api: ApiClient):
    """A policy number already on the book cannot be written again.

    Natural-key uniqueness sits at the same band for every collection that has one, and every violation reports the same code, `ERR_DUPLICATE_REFERENCE` (HTTP 409): a policy's `policy_number`, a certificate's `certificate_number`, a vessel's `imo_number`, a port's `unlocode`, a surveyor's `panel_code` and a commodity class's `code` are each unique across all rows of their collection.

    Design: Corner/validations/duplicate_natural_keys_are_rejected_across_five_entities
    """
    create_open_policy(api, activate=True, policy_number="OP-DUP-1")

    response = api.create_open_policy({
        "policy_number": "OP-DUP-1",
        "assured_name": "Copycat Ltd",
        "inception_at": "2026-02-01T00:00:00Z",
        "expiry_at": "2027-02-01T00:00:00Z",
        "freight_basis": "COLLECT",
        "per_certificate_limit_amount": 1000000,
        "conveyance_limit_amount": 1000000,
        "annual_aggregate_limit_amount": 1000000,
        "premium_rate_per_mille": 4.000,
        "war_rate_per_mille": 0.500,
        "strikes_rate_per_mille": 0.200,
    }, UNDERWRITER)

    validate_error(response, ERR_DUPLICATE_REFERENCE)


def test_a_second_port_unlocode_is_refused(api: ApiClient):
    """A UN/LOCODE collides even when the name and the country differ.

    Natural-key uniqueness sits at the same band for every collection that has one, and every violation reports the same code, `ERR_DUPLICATE_REFERENCE` (HTTP 409): a policy's `policy_number`, a certificate's `certificate_number`, a vessel's `imo_number`, a port's `unlocode`, a surveyor's `panel_code` and a commodity class's `code` are each unique across all rows of their collection.

    Design: Corner/validations/duplicate_natural_keys_are_rejected_across_five_entities
    """
    create_port(api, PORT_SGSIN)

    response = api.create_port({
        "unlocode": "SGSIN",
        "name": "Singapore Anchorage",
        "country_code": "ID",
        "port_accumulation_limit_amount": 1000000,
    }, COMPLIANCE_OFFICER)

    validate_error(response, ERR_DUPLICATE_REFERENCE)
    assert_total_count(api.list_ports(UNDERWRITER), 1, "ports")


def test_a_second_vessel_imo_number_is_refused(api: ApiClient):
    """An IMO number already registered cannot be registered on another hull.

    Natural-key uniqueness sits at the same band for every collection that has one, and every violation reports the same code, `ERR_DUPLICATE_REFERENCE` (HTTP 409): a policy's `policy_number`, a certificate's `certificate_number`, a vessel's `imo_number`, a port's `unlocode`, a surveyor's `panel_code` and a commodity class's `code` are each unique across all rows of their collection.

    Design: Corner/validations/duplicate_natural_keys_are_rejected_across_five_entities
    """
    create_vessel(api, VESSEL_KITE, review=False)

    response = api.create_vessel({
        "name": "MV Impostor",
        "imo_number": "9100001",
        "year_built": 2020,
        "classification_society": "ABS",
        "flag_code": "PA",
        "vessel_accumulation_limit_amount": 1000000,
    }, UNDERWRITER)

    validate_error(response, ERR_DUPLICATE_REFERENCE)


def test_a_second_commodity_class_code_is_refused(api: ApiClient):
    """A commodity class code is unique across the whole register.

    Natural-key uniqueness sits at the same band for every collection that has one, and every violation reports the same code, `ERR_DUPLICATE_REFERENCE` (HTTP 409): a policy's `policy_number`, a certificate's `certificate_number`, a vessel's `imo_number`, a port's `unlocode`, a surveyor's `panel_code` and a commodity class's `code` are each unique across all rows of their collection.

    Design: Corner/validations/duplicate_natural_keys_are_rejected_across_five_entities
    """
    create_commodity_class(api)

    response = api.create_commodity_class({
        "code": COMMODITY_CLASS_ELECTRONICS["code"],
        "description": "Duplicate code",
        "susceptibility_rating": "S1",
        "required_packaging_code": "STD",
        "rate_loading_pct": 0.00,
        "max_conveyance_share_pct": 1.00,
        "survey_required_above_amount": 0,
    }, UNDERWRITER)

    validate_error(response, ERR_DUPLICATE_REFERENCE)
    assert_total_count(api.list_commodity_classes(UNDERWRITER), 1,
                       "commodity classes")


def test_a_certificate_number_is_unique_across_every_open_cover(api: ApiClient):
    """A certificate number taken on one cover cannot be reused on another.

    Natural-key uniqueness sits at the same band for every collection that has one, and every violation reports the same code, `ERR_DUPLICATE_REFERENCE` (HTTP 409): a policy's `policy_number`, a certificate's `certificate_number`, a vessel's `imo_number`, a port's `unlocode`, a surveyor's `panel_code` and a commodity class's `code` are each unique across all rows of their collection.

    Design: Corner/validations/duplicate_natural_keys_are_rejected_across_five_entities
    """
    env = _wide_environment(api, policy_overrides={"policy_number": "OP-DUP-1"})
    other_policy = create_open_policy(api, policy_number="OP-DUP-2",
                                      assured_name="Other Assured Ltd")
    first = build_draft_certificate(
        api, env, base=CERTIFICATE_DECLARED_SHIPMENT,
        certificate_number="CERT-A", declared_value=400000,
        package_count=40, gross_weight_kg=6000)

    response = api.create_certificate({
        "open_policy_id": other_policy["id"],
        "commodity_class_id": env["commodity_class_id"],
        "vessel_id": env["vessel_id"],
        "loading_port_id": env["loading_port_id"],
        "discharge_port_id": env["discharge_port_id"],
        "certificate_number": "CERT-A",
        "valuation_basis": "DECLARED_VALUE",
        "packaging_code": "EXPORT_CRATE",
        "package_count": 40,
        "gross_weight_kg": 6000,
        "sailing_date": "2026-08-10T00:00:00Z",
        "discharge_date": "2026-09-05T00:00:00Z",
        "declared_value": 400000,
    }, make_assured_headers(other_policy["id"]))

    validate_error(response, ERR_DUPLICATE_REFERENCE)
    rows = assert_total_count(api.list_certificates(UNDERWRITER), 1,
                              "certificates")
    assert collect_ids(rows) == [first["id"]], (
        "the refused declaration must not have left a certificate row behind"
    )


# ---------------------------------------------------------------------------
# The attachment instant against the half-open policy period
# ---------------------------------------------------------------------------
def _expiring_cover(api: ApiClient) -> JsonDict:
    """A cover running from 2026-01-01 up to but excluding 2026-09-01."""
    return _wide_environment(api, policy_overrides={
        "policy_number": "OP-EXPSOON", "expiry_at": EXPIRY_SOON})


def _declared_draft(api: ApiClient, env: JsonDict, number: str,
                    sailing_date: str, discharge_date: str) -> JsonDict:
    """A 400000.00 declared-value draft with no war or strikes cover bought."""
    return build_draft_certificate(
        api, env, base=CERTIFICATE_DECLARED_SHIPMENT,
        certificate_number=number, declared_value=400000,
        package_count=40, gross_weight_kg=6000,
        sailing_date=sailing_date, discharge_date=discharge_date,
        war_cover_requested=False, strikes_cover_requested=False)


def test_a_voyage_sailing_exactly_at_expiry_cannot_be_issued(api: ApiClient):
    """Attachment exactly at the expiry instant falls outside the cover.

    Then the policy period: the certificate's attachment instant must lie inside the half-open period that starts at `inception_at` and ends immediately before `expiry_at`, so a voyage sailing exactly at `expiry_at` is outside cover and gives `ERR_OUTSIDE_POLICY_PERIOD` (HTTP 422).

    Design: Corner/validations/voyage_sailing_exactly_at_policy_expiry_is_outside_cover
    """
    env = _expiring_cover(api)
    draft = _declared_draft(api, env, "CERT-ATEXPIRY", EXPIRY_SOON,
                            "2026-09-20T00:00:00Z")
    version_before = policy_version(api, env["policy_id"])

    response = api.issue_certificate(
        draft["id"], {"expected_open_policy_version": version_before},
        UNDERWRITER)

    validate_error(response, ERR_OUTSIDE_POLICY_PERIOD)
    refused = read_certificate(api, draft["id"])
    assert refused["status"] == "DRAFT", (
        f"a refused issue must leave the row DRAFT, got {refused['status']}"
    )
    policy = read_policy(api, env["policy_id"])
    assert policy["version"] == version_before, (
        "a refused issue must not consume the open cover's version"
    )


def test_a_voyage_sailing_before_inception_cannot_be_issued(api: ApiClient):
    """Attachment one day before inception falls outside the cover.

    Then the policy period: the certificate's attachment instant must lie inside the half-open period that starts at `inception_at` and ends immediately before `expiry_at`, so a voyage sailing exactly at `expiry_at` is outside cover and gives `ERR_OUTSIDE_POLICY_PERIOD` (HTTP 422).

    Design: Corner/validations/voyage_sailing_exactly_at_policy_expiry_is_outside_cover
    """
    env = _expiring_cover(api)
    draft = _declared_draft(api, env, "CERT-PREINCEPTION",
                            "2025-12-31T00:00:00Z", "2026-01-20T00:00:00Z")

    response = api.issue_certificate(
        draft["id"],
        {"expected_open_policy_version": policy_version(api, env["policy_id"])},
        UNDERWRITER)

    validate_error(response, ERR_OUTSIDE_POLICY_PERIOD)
    refused = read_certificate(api, draft["id"])
    assert refused["status"] == "DRAFT", (
        f"a refused issue must leave the row DRAFT, got {refused['status']}"
    )


def test_a_voyage_sailing_the_day_before_expiry_is_issued(api: ApiClient):
    """The last day inside the period still attaches and books its exposure.

    Then the policy period: the certificate's attachment instant must lie inside the half-open period that starts at `inception_at` and ends immediately before `expiry_at`, so a voyage sailing exactly at `expiry_at` is outside cover and gives `ERR_OUTSIDE_POLICY_PERIOD` (HTTP 422).

    Design: Corner/validations/voyage_sailing_exactly_at_policy_expiry_is_outside_cover
    """
    env = _expiring_cover(api)
    draft = _declared_draft(api, env, "CERT-LASTDAY", "2026-08-31T00:00:00Z",
                            "2026-09-20T00:00:00Z")

    issued = issue_certificate(api, draft["id"], env["policy_id"])

    assert issued["status"] == "ISSUED", (
        f"a voyage inside the period must issue, got {issued['status']}"
    )
    assert_instant(issued["attachment_at"], "2026-08-31T00:00:00Z", (
        f"attachment must pin to the sailing date, got {issued['attachment_at']}"
    ))
    policy = read_policy(api, env["policy_id"])
    assert policy["certificates_issued_count"] == 1
    assert_money(policy["aggregate_insured_value_booked"], 400000.00,
                 "policy.aggregate_insured_value_booked")


def test_expiry_truncates_the_storage_window_of_an_issued_voyage(api: ApiClient):
    """The cover's expiry, not the port's free storage, ends this transit.

    When it is true, the termination instant is the earliest of three candidates: the discharge instant plus the discharge port's `storage_free_days` days, the discharge instant plus the sixty-day warehouse-to-warehouse ceiling, and the policy's `expiry_at`.

    Design: Corner/validations/voyage_sailing_exactly_at_policy_expiry_is_outside_cover
    """
    env = _expiring_cover(api)
    draft = _declared_draft(api, env, "CERT-LASTDAY", "2026-08-31T00:00:00Z",
                            "2026-09-20T00:00:00Z")

    issued = issue_certificate(api, draft["id"], env["policy_id"])

    assert_instant(issued["transit_termination_at"], EXPIRY_SOON, (
        "the cover's expiry is the earliest of the three candidates, got "
        f"{issued['transit_termination_at']}"
    ))


# ---------------------------------------------------------------------------
# Reporting periods of the same open cover
# ---------------------------------------------------------------------------
AUGUST_START = "2026-08-01T00:00:00Z"
AUGUST_END = "2026-09-01T00:00:00Z"


def _cover_with_august_declaration(api: ApiClient) -> JsonDict:
    """An active cover whose August reporting period is already open."""
    env = build_canonical_environment(api)
    env["august"] = create_declaration(api, env["policy_id"], AUGUST_START,
                                       AUGUST_END)
    return env


def _declare_period(api: ApiClient, env: JsonDict, period_start: str,
                    period_end: str):
    """Ask the cover's assured for a further reporting period."""
    return api.create_premium_declaration(
        {"open_policy_id": env["policy_id"], "period_start": period_start,
         "period_end": period_end},
        make_assured_headers(env["policy_id"]))


def _assert_single_declaration(api: ApiClient) -> None:
    assert_total_count(api.list_premium_declarations(PREMIUM_AUDITOR), 1,
                       "premium declarations after a refused period")


def test_a_period_straddling_the_end_of_an_open_one_is_refused(api: ApiClient):
    """A period starting inside August and running past its end overlaps.

    Two declarations of the same policy may not overlap, and half-open semantics mean a period beginning at exactly another's `period_end` is perfectly acceptable; a genuine overlap is refused with `ERR_DECLARATION_PERIOD_OVERLAP` (HTTP 409).

    Design: Corner/validations/overlapping_declaration_periods_are_rejected_but_adjacent_ones_are_not
    """
    env = _cover_with_august_declaration(api)

    response = _declare_period(api, env, "2026-08-15T00:00:00Z",
                               "2026-09-15T00:00:00Z")

    validate_error(response, ERR_DECLARATION_PERIOD_OVERLAP)
    _assert_single_declaration(api)


def test_a_period_contained_inside_an_open_one_is_refused(api: ApiClient):
    """A short period wholly inside August overlaps it just as much.

    Two declarations of the same policy may not overlap, and half-open semantics mean a period beginning at exactly another's `period_end` is perfectly acceptable; a genuine overlap is refused with `ERR_DECLARATION_PERIOD_OVERLAP` (HTTP 409).

    Design: Corner/validations/overlapping_declaration_periods_are_rejected_but_adjacent_ones_are_not
    """
    env = _cover_with_august_declaration(api)

    response = _declare_period(api, env, "2026-08-10T00:00:00Z",
                               "2026-08-20T00:00:00Z")

    validate_error(response, ERR_DECLARATION_PERIOD_OVERLAP)
    _assert_single_declaration(api)


def test_a_period_straddling_the_start_of_an_open_one_is_refused(api: ApiClient):
    """A July period reaching into August overlaps from the left.

    Two declarations of the same policy may not overlap, and half-open semantics mean a period beginning at exactly another's `period_end` is perfectly acceptable; a genuine overlap is refused with `ERR_DECLARATION_PERIOD_OVERLAP` (HTTP 409).

    Design: Corner/validations/overlapping_declaration_periods_are_rejected_but_adjacent_ones_are_not
    """
    env = _cover_with_august_declaration(api)

    response = _declare_period(api, env, "2026-07-15T00:00:00Z",
                               "2026-08-10T00:00:00Z")

    validate_error(response, ERR_DECLARATION_PERIOD_OVERLAP)
    _assert_single_declaration(api)


def test_a_period_beginning_exactly_where_another_ends_is_accepted(
        api: ApiClient):
    """September may start at the instant August stops, and both stay on file.

    Two declarations of the same policy may not overlap, and half-open semantics mean a period beginning at exactly another's `period_end` is perfectly acceptable; a genuine overlap is refused with `ERR_DECLARATION_PERIOD_OVERLAP` (HTTP 409).

    Design: Corner/validations/overlapping_declaration_periods_are_rejected_but_adjacent_ones_are_not
    """
    env = _cover_with_august_declaration(api)

    adjacent = validate_success(
        _declare_period(api, env, AUGUST_END, "2026-10-01T00:00:00Z"), 201)

    assert_instant(adjacent["period_start"], AUGUST_END, (
        "the adjacent period must start where August ended, got "
        f"{adjacent['period_start']}"
    ))
    assert adjacent["status"] == "OPEN", (
        f"a fresh reporting period opens OPEN, got {adjacent['status']}"
    )
    rows = assert_total_count(api.list_premium_declarations(PREMIUM_AUDITOR), 2,
                              "premium declarations of the cover")
    assert set(collect_ids(rows)) == {env["august"]["id"], adjacent["id"]}


# ---------------------------------------------------------------------------
# The two single-certificate ceilings, and the moment each one bites
# ---------------------------------------------------------------------------
TOWER_LIMITS = {
    "per_certificate_limit_amount": 2000000,
    "conveyance_limit_amount": 3000000,
    "annual_aggregate_limit_amount": 10000000,
}


def _tower_environment(api: ApiClient, share_pct: float,
                       policy_number: str) -> JsonDict:
    """A cover with the 2m/3m/10m tower and a class of the given share cap."""
    return _wide_environment(
        api,
        commodity_class_overrides={"max_conveyance_share_pct": share_pct},
        policy_overrides=dict(TOWER_LIMITS, policy_number=policy_number),
    )


def test_the_per_certificate_limit_refuses_the_line_only_at_issue(
        api: ApiClient):
    """A 2200000.00 line clears a full-conveyance share cap yet breaks the
    per-certificate limit, so it is declared and only then refused.

    The insured value must not exceed the policy's `per_certificate_limit_amount`.

    Design: Corner/validations/per_certificate_limit_and_commodity_share_reject_at_different_moments
    """
    env = _tower_environment(api, 1.00, "OP-PERCERT")
    draft = build_draft_certificate(
        api, env, base=CERTIFICATE_DECLARED_SHIPMENT,
        certificate_number="CERT-OVERLINE", declared_value=2200000)
    assert_money(draft["insured_value"], 2200000.00, "declared insured_value")
    version_before = policy_version(api, env["policy_id"])

    response = api.issue_certificate(
        draft["id"], {"expected_open_policy_version": version_before},
        UNDERWRITER)

    validate_error(response, ERR_CERTIFICATE_LIMIT_EXCEEDED)
    refused = read_certificate(api, draft["id"])
    assert refused["status"] == "DRAFT", (
        f"the over-line row must stay DRAFT, got {refused['status']}"
    )
    policy = read_policy(api, env["policy_id"])
    assert policy["version"] == version_before, (
        "a refused issue must not consume the open cover's version"
    )
    assert policy["certificates_issued_count"] == 0
    assert_money(policy["aggregate_insured_value_booked"], 0.00,
                 "policy.aggregate_insured_value_booked")


def test_the_commodity_share_ceiling_refuses_the_line_at_declaration(
        api: ApiClient):
    """A 1650000.00 line is under the 2000000.00 per-certificate limit but over
    the 1500000.00 half-conveyance share, so it never becomes a row.

    The insured value must not exceed the policy's `conveyance_limit_amount` multiplied by the commodity class's `max_conveyance_share_pct`, that product being rounded half up to 2 decimals before the comparison.

    Design: Corner/validations/per_certificate_limit_and_commodity_share_reject_at_different_moments
    """
    env = _tower_environment(api, 0.50, "OP-SHARE")

    response = api.create_certificate(
        _declaration_payload(env, base=CERTIFICATE_DECLARED_SHIPMENT,
                             certificate_number="CERT-OVERSHARE",
                             declared_value=1650000),
        env["assured"])

    validate_error(response, ERR_COMMODITY_SHARE_EXCEEDED)
    _assert_certificate_rows(api, env["policy_id"], 0)
    policy = read_policy(api, env["policy_id"])
    assert_money(policy["aggregate_insured_value_booked"], 0.00,
                 "policy.aggregate_insured_value_booked")


def test_a_line_exactly_at_the_per_certificate_limit_is_booked(api: ApiClient):
    """An exposure landing exactly on the 2000000.00 limit is accepted and booked.

    Every comparison is strictly greater than: an exposure exactly equal to its limit is accepted, and one cent over it is rejected.

    Design: Corner/validations/per_certificate_limit_and_commodity_share_reject_at_different_moments
    """
    env = _tower_environment(api, 1.00, "OP-EXACT")
    draft = build_draft_certificate(
        api, env, base=CERTIFICATE_DECLARED_SHIPMENT,
        certificate_number="CERT-ONLIMIT", declared_value=2000000)

    issued = issue_certificate(api, draft["id"], env["policy_id"])

    assert issued["status"] == "ISSUED", (
        f"an exposure on the limit must issue, got {issued['status']}"
    )
    assert_money(issued["insured_value"], 2000000.00, "insured_value")
    policy = read_policy(api, env["policy_id"])
    assert policy["certificates_issued_count"] == 1
    assert_money(policy["aggregate_insured_value_booked"], 2000000.00,
                 "policy.aggregate_insured_value_booked")


# ---------------------------------------------------------------------------
# Accumulation across certificates: one conveyance, then the whole cover year
# ---------------------------------------------------------------------------
LINE_VALUE = 1600000
FIRST_SAILING = "2026-08-10T00:00:00Z"
SECOND_SAILING = "2026-08-20T00:00:00Z"
THIRD_SAILING = "2026-08-25T00:00:00Z"


def _accumulating_cover(api: ApiClient) -> JsonDict:
    """A 2m/3m/3.6m tower with a class free to take 80% of a conveyance."""
    return _wide_environment(
        api,
        commodity_class_overrides={"max_conveyance_share_pct": 0.80},
        policy_overrides={
            "policy_number": "OP-ACCUM",
            "per_certificate_limit_amount": 2000000,
            "conveyance_limit_amount": 3000000,
            "annual_aggregate_limit_amount": 3600000,
        },
    )


def _line_payload(env: JsonDict, number: str, sailing_date: str,
                  discharge_date: str = "2026-09-05T00:00:00Z") -> JsonDict:
    """A 1600000.00 declared-value line on the given sailing."""
    return _declaration_payload(
        env, base=CERTIFICATE_DECLARED_SHIPMENT, certificate_number=number,
        declared_value=LINE_VALUE, package_count=60, gross_weight_kg=9000,
        sailing_date=sailing_date, discharge_date=discharge_date)


def _issue_line(api: ApiClient, env: JsonDict, number: str,
                sailing_date: str,
                discharge_date: str = "2026-09-05T00:00:00Z") -> JsonDict:
    draft = validate_success(
        api.create_certificate(
            _line_payload(env, number, sailing_date, discharge_date),
            env["assured"]),
        201)
    return issue_certificate(api, draft["id"], env["policy_id"])


def test_a_second_line_on_the_same_conveyance_breaks_the_conveyance_limit(
        api: ApiClient):
    """Two 1600000.00 lines on one hull and one sailing date come to 3200000.00
    against a 3000000.00 conveyance limit, so the second is refused.

    The system sums the insured values of every certificate sharing this certificate's `vessel_id` and `sailing_date` whose `status` is `ISSUED`, `CLAIMED` or `TRANSIT_ENDED`, and the sum plus this insured value must not exceed the policy's `conveyance_limit_amount`.

    Design: Corner/validations/conveyance_and_annual_aggregate_limits_accumulate_across_certificates
    """
    env = _accumulating_cover(api)
    first = _issue_line(api, env, "CERT-L1", FIRST_SAILING)
    second = validate_success(
        api.create_certificate(_line_payload(env, "CERT-L2", FIRST_SAILING),
                               env["assured"]),
        201)

    response = api.issue_certificate(
        second["id"],
        {"expected_open_policy_version": policy_version(api, env["policy_id"])},
        UNDERWRITER)

    validate_error(response, ERR_CONVEYANCE_LIMIT_EXCEEDED)
    assert read_certificate(api, first["id"])["status"] == "ISSUED"
    assert read_certificate(api, second["id"])["status"] == "DRAFT"
    policy = read_policy(api, env["policy_id"])
    assert policy["certificates_issued_count"] == 1
    assert_money(policy["aggregate_insured_value_booked"], float(LINE_VALUE),
                 "policy.aggregate_insured_value_booked")


def test_a_later_sailing_date_opens_a_fresh_conveyance_bucket(api: ApiClient):
    """The very line the same sailing date refused is accepted ten days later,
    because the bucket is vessel and sailing date together.

    A conveyance is one vessel and one sailing date taken together.

    Design: Corner/validations/conveyance_and_annual_aggregate_limits_accumulate_across_certificates
    """
    env = _accumulating_cover(api)
    _issue_line(api, env, "CERT-L1", FIRST_SAILING)

    later = _issue_line(api, env, "CERT-L3", SECOND_SAILING)

    assert later["status"] == "ISSUED", (
        f"a fresh conveyance must accept the line, got {later['status']}"
    )
    assert_instant(later["sailing_date"], SECOND_SAILING, "sailing_date")
    policy = read_policy(api, env["policy_id"])
    assert policy["certificates_issued_count"] == 2
    assert_money(policy["aggregate_insured_value_booked"],
                 float(2 * LINE_VALUE),
                 "policy.aggregate_insured_value_booked")


def test_the_annual_aggregate_stops_a_third_conveyance(api: ApiClient):
    """Two conveyances have booked 3200000.00 of the cover's 3600000.00 year, so
    a third 1600000.00 line is refused even on an empty sailing date.

    The policy's `aggregate_insured_value_booked` plus this insured value must not exceed its `annual_aggregate_limit_amount`.

    Design: Corner/validations/conveyance_and_annual_aggregate_limits_accumulate_across_certificates
    """
    env = _accumulating_cover(api)
    _issue_line(api, env, "CERT-L1", FIRST_SAILING)
    _issue_line(api, env, "CERT-L3", SECOND_SAILING)
    third = validate_success(
        api.create_certificate(
            _line_payload(env, "CERT-L4", THIRD_SAILING,
                          "2026-09-10T00:00:00Z"),
            env["assured"]),
        201)

    response = api.issue_certificate(
        third["id"],
        {"expected_open_policy_version": policy_version(api, env["policy_id"])},
        UNDERWRITER)

    validate_error(response, ERR_ANNUAL_AGGREGATE_EXCEEDED)
    assert read_certificate(api, third["id"])["status"] == "DRAFT"
    policy = read_policy(api, env["policy_id"])
    assert policy["certificates_issued_count"] == 2
    assert_money(policy["aggregate_insured_value_booked"],
                 float(2 * LINE_VALUE),
                 "policy.aggregate_insured_value_booked")

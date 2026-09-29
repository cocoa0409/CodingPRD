"""Composite setup helpers that build API state through PRD-declared endpoints.

Every helper drives the public surface only, so the state it leaves behind is
exactly the state a real caller would have produced.  Setup calls go through
``get_success_data`` so that a broken precondition fails loudly and early
instead of surfacing later as a confusing assertion mismatch.

Identity threading matters here.  A ``TerminalOperator``'s ``X-User-ID`` is the
acting terminal's own ``id`` and a ``Shipper``'s ``X-User-ID`` is the acting
shipper account's own ``id``, so every ownership-gated call below is made with a
per-instance header built from the real entity id.
"""

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import api_client
from .constants import TEST_DEFAULTS
from .test_users import (
    TEST_USERS,
    make_classification_auditor_headers,
    make_dispute_reviewer_headers,
    make_freight_inspector_headers,
    make_shipper_headers,
    make_terminal_operator_headers,
)

ANALYST_HEADERS = TEST_USERS["pricing_analyst_headers"]
AUDITOR_HEADERS = TEST_USERS["classification_auditor_headers"]
INSPECTOR_HEADERS = TEST_USERS["freight_inspector_headers"]
REVIEWER_HEADERS = TEST_USERS["dispute_reviewer_headers"]


# ==========================================================================
# Tier 1 -- the logical clock
# ==========================================================================


def set_clock(to_iso8601: str, headers: dict = None) -> str:
    """Move the logical clock and answer with the new `current_utc`."""
    data = get_success_data(
        api_client.set_current_utc(f.clock_payload(to_iso8601), headers or ANALYST_HEADERS)
    )
    return data["current_utc"]


# ==========================================================================
# Tier 1 -- single-resource creators and readers
# ==========================================================================


def create_terminal(**overrides) -> dict:
    return get_success_data(
        api_client.create_terminal(f.create_terminal_payload(**overrides), ANALYST_HEADERS)
    )


def get_terminal(terminal_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_terminal(terminal_id, headers or ANALYST_HEADERS))


def create_customer(**overrides) -> dict:
    return get_success_data(
        api_client.create_customer(f.create_customer_payload(**overrides), ANALYST_HEADERS)
    )


def get_customer(customer_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_customer(customer_id, headers or ANALYST_HEADERS))


def change_posture(customer_id: str, billing_posture: str, expected_customer_version: int = None) -> dict:
    """Move the shipper's credit posture, reading the live version when none is given."""
    if expected_customer_version is None:
        expected_customer_version = get_customer(customer_id)["version"]
    return get_success_data(
        api_client.change_customer_posture(
            customer_id,
            f.posture_payload(billing_posture, expected_customer_version),
            ANALYST_HEADERS,
        )
    )


def complete_education(customer_id: str) -> dict:
    return get_success_data(
        api_client.complete_customer_education(customer_id, {}, ANALYST_HEADERS)
    )


def create_draft_tariff_version(**overrides) -> dict:
    return get_success_data(
        api_client.create_tariff_version(
            f.create_tariff_version_payload(**overrides), ANALYST_HEADERS
        )
    )


def create_commodity_profile(tariff_version_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_commodity_profile(
            f.create_commodity_profile_payload(tariff_version_id, **overrides), ANALYST_HEADERS
        )
    )


def publish_tariff_version(tariff_version_id: str) -> dict:
    return get_success_data(
        api_client.publish_tariff_version(tariff_version_id, {}, ANALYST_HEADERS)
    )


def get_tariff_version(tariff_version_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_tariff_version(tariff_version_id, headers or ANALYST_HEADERS)
    )


def create_published_standard(profile_overrides: dict = None, **tariff_overrides) -> dict:
    """Draft a standard release, give it one commodity item, then publish it.

    Publication requires the release to carry at least one commodity profile, so
    the profile is always created before the publish call.
    """
    draft = create_draft_tariff_version(**tariff_overrides)
    profile = create_commodity_profile(draft["id"], **(profile_overrides or {}))
    published = publish_tariff_version(draft["id"])
    return {
        "tariff_version": published,
        "tariff_version_id": published["id"],
        "commodity_profile": profile,
        "commodity_profile_id": profile["id"],
    }


# ==========================================================================
# Tier 2 -- pricing programs
# ==========================================================================


def create_rate_program(customer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_rate_program(
            f.create_rate_program_payload(customer_id, **overrides), ANALYST_HEADERS
        )
    )


def approve_rate_program(rate_program_id: str) -> dict:
    return get_success_data(
        api_client.approve_rate_program(rate_program_id, {}, ANALYST_HEADERS)
    )


def activate_rate_program(
    rate_program_id: str, customer_id: str, expected_customer_version: int = None
) -> dict:
    """Activate an approved program, reading the live customer version when none is given."""
    if expected_customer_version is None:
        expected_customer_version = get_customer(customer_id)["version"]
    return get_success_data(
        api_client.activate_rate_program(
            rate_program_id,
            f.activate_rate_program_payload(expected_customer_version),
            ANALYST_HEADERS,
        )
    )


def create_approved_rate_program(customer_id: str, **overrides) -> dict:
    """Draft a program and approve it, which pins the newest published release."""
    program = create_rate_program(customer_id, **overrides)
    return approve_rate_program(program["id"])


def create_active_rate_program(customer_id: str, **overrides) -> dict:
    """Draft, approve and activate a program in one step."""
    approved = create_approved_rate_program(customer_id, **overrides)
    return activate_rate_program(approved["id"], customer_id)


def get_rate_program(rate_program_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_rate_program(rate_program_id, headers or ANALYST_HEADERS)
    )


# ==========================================================================
# Tier 2 -- exception agreements
# ==========================================================================


def create_exception_agreement(
    customer_id: str,
    commodity_profile_id: str,
    effective_from: str,
    effective_to: str,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_exception_agreement(
            f.create_exception_agreement_payload(
                customer_id, commodity_profile_id, effective_from, effective_to, **overrides
            ),
            ANALYST_HEADERS,
        )
    )


def approve_exception_agreement(agreement_id: str) -> dict:
    return get_success_data(
        api_client.approve_exception_agreement(agreement_id, {}, ANALYST_HEADERS)
    )


def create_active_exception_agreement(
    customer_id: str,
    commodity_profile_id: str,
    effective_from: str,
    effective_to: str,
    **overrides,
) -> dict:
    agreement = create_exception_agreement(
        customer_id, commodity_profile_id, effective_from, effective_to, **overrides
    )
    return approve_exception_agreement(agreement["id"])


# ==========================================================================
# Tier 2 -- the shared pricing environment
# ==========================================================================


def setup_pricing_environment(
    clock: str = TEST_DEFAULTS["WORKING_CLOCK"],
    terminal_overrides: dict = None,
    customer_overrides: dict = None,
    tariff_overrides: dict = None,
    profile_overrides: dict = None,
    program_overrides: dict = None,
) -> dict:
    """Terminal, shipper account, published standard with one commodity item, and
    one `ACTIVE` pricing program for that shipper.

    This is the minimum state a bill of lading can be tendered against: tender
    pins the shipper's `ACTIVE` program and the newest release effective at or
    before `pickup_at`.
    """
    if clock is not None:
        set_clock(clock)
    terminal = create_terminal(**(terminal_overrides or {}))
    customer = create_customer(**(customer_overrides or {}))
    standard = create_published_standard(
        profile_overrides=profile_overrides, **(tariff_overrides or {})
    )
    program = create_active_rate_program(customer["id"], **(program_overrides or {}))
    return {
        "terminal": terminal,
        "terminal_id": terminal["id"],
        "customer": get_customer(customer["id"]),
        "customer_id": customer["id"],
        "tariff_version": standard["tariff_version"],
        "tariff_version_id": standard["tariff_version_id"],
        "commodity_profile": standard["commodity_profile"],
        "commodity_profile_id": standard["commodity_profile_id"],
        "rate_program": program,
        "rate_program_id": program["id"],
        "shipper_headers": make_shipper_headers(customer["id"]),
        "operator_headers": make_terminal_operator_headers(terminal["id"]),
    }


# ==========================================================================
# Tier 3 -- shipments and lines
# ==========================================================================


def tender_shipment(customer_id: str, origin_terminal_id: str, pro_number: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_shipment(
            f.create_shipment_payload(customer_id, origin_terminal_id, pro_number, **overrides),
            make_shipper_headers(customer_id),
        )
    )


def add_shipment_line(
    shipment_id: str, customer_id: str, commodity_profile_id: str, **overrides
) -> dict:
    return get_success_data(
        api_client.create_shipment_line(
            shipment_id,
            f.create_shipment_line_payload(commodity_profile_id, **overrides),
            make_shipper_headers(customer_id),
        )
    )


def bill_shipment(shipment_id: str) -> dict:
    return get_success_data(api_client.bill_shipment(shipment_id, {}, ANALYST_HEADERS))


def close_shipment(shipment_id: str) -> dict:
    return get_success_data(api_client.close_shipment(shipment_id, {}, ANALYST_HEADERS))


def get_shipment(shipment_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_shipment(shipment_id, headers or ANALYST_HEADERS))


def get_shipment_line(shipment_line_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_shipment_line(shipment_line_id, headers or ANALYST_HEADERS)
    )


def list_shipment_lines_for(shipment_id: str, headers: dict = None) -> list:
    response = api_client.list_shipment_lines(
        headers or ANALYST_HEADERS, params={"shipment_id": shipment_id, "limit": 100}
    )
    rows, _meta = validate_paginated(response)
    return rows


def setup_shipment_with_lines(
    env: dict, pro_number: str, line_specs: list = None, **shipment_overrides
) -> dict:
    """Tender one bill of lading and add its lines, leaving it `UNBILLED`."""
    shipment = tender_shipment(
        env["customer_id"], env["terminal_id"], pro_number, **shipment_overrides
    )
    specs = [{}] if line_specs is None else line_specs
    lines = []
    for index, spec in enumerate(specs):
        spec = dict(spec)
        profile_id = spec.pop("commodity_profile_id", env["commodity_profile_id"])
        spec.setdefault("line_no", index + 1)
        lines.append(
            add_shipment_line(shipment["id"], env["customer_id"], profile_id, **spec)
        )
    return {
        "shipment": get_shipment(shipment["id"]),
        "shipment_id": shipment["id"],
        "lines": lines,
        "line_ids": [line["id"] for line in lines],
    }


def setup_billed_shipment(
    env: dict = None,
    pro_number: str = "PRO001",
    line_specs: list = None,
    shipment_overrides: dict = None,
    **env_kwargs,
) -> dict:
    """A shipper, a program, a standard, one bill of lading with lines, billed.

    Billing on the declared basis moves `billing_status` `UNBILLED → BILLED`,
    stores `original_charge_cents`, sets `assessed_total_cents` equal to it and
    leaves `class_status` alone.
    """
    env = env or setup_pricing_environment(**env_kwargs)
    tendered = setup_shipment_with_lines(
        env, pro_number, line_specs, **(shipment_overrides or {})
    )
    billed = bill_shipment(tendered["shipment_id"])
    result = dict(env)
    result.update(tendered)
    result["shipment"] = billed
    return result


def setup_single_line_billed_shipment(
    env: dict = None, pro_number: str = "PRO001", **kwargs
) -> dict:
    """One 400-pound, four-piece, class 70 line on a 48.0 x 40.0 x 48.0 unit."""
    return setup_billed_shipment(env=env, pro_number=pro_number, line_specs=[{}], **kwargs)


def setup_two_line_billed_shipment(
    env: dict = None, pro_number: str = "PRO001", **kwargs
) -> dict:
    """A 400-pound class 70 line plus a 700-pound class 100 line."""
    return setup_billed_shipment(
        env=env,
        pro_number=pro_number,
        line_specs=[
            {"line_no": 1},
            {
                "line_no": 2,
                "declared_class_code": 100,
                "declared_weight_lb": 700,
                "pieces": 2,
                "declared_length_in": 40.0,
                "declared_width_in": 40.0,
                "declared_height_in": 40.0,
            },
        ],
        **kwargs,
    )


# ==========================================================================
# Tier 4 -- dock capture
# ==========================================================================


def record_capture(
    shipment_id: str,
    terminal_id: str,
    measured_total_weight_lb: int,
    line_measurements: list,
    device_type: str = "COMBINED",
    **overrides,
) -> dict:
    """Record a capture as the operator whose `X-User-ID` is the origin terminal."""
    return get_success_data(
        api_client.create_capture_event(
            f.create_capture_event_payload(
                shipment_id,
                measured_total_weight_lb,
                line_measurements,
                device_type=device_type,
                **overrides,
            ),
            make_terminal_operator_headers(terminal_id),
        )
    )


def single_line_measurement(
    measured_weight_lb: int,
    line_no: int = 1,
    measured_length_in: float = 48.0,
    measured_width_in: float = 40.0,
    measured_height_in: float = 48.0,
) -> list:
    """A one-element `line_measurements` array keeping the declared dimensions."""
    return [
        f.line_measurement(
            line_no,
            measured_weight_lb,
            measured_length_in,
            measured_width_in,
            measured_height_in,
        )
    ]


def exhaust_terminal_calibration(terminal_id: str, env: dict, captures_needed: int) -> None:
    """Drive a terminal to `OUT_OF_CALIBRATION` by recording captures until its
    `captures_since_calibration` reaches its `calibration_interval_captures`."""
    scenario = setup_single_line_billed_shipment(env=env, pro_number="PROCAL1")
    for _ in range(captures_needed):
        record_capture(
            scenario["shipment_id"],
            terminal_id,
            400,
            single_line_measurement(400),
            device_type="SCALE",
        )


# ==========================================================================
# Tier 4 -- inspection findings
# ==========================================================================


def record_finding(
    shipment_line_id: str, inspector_user_id: str = "insp-1", **overrides
) -> dict:
    return get_success_data(
        api_client.create_inspection_finding(
            f.create_inspection_finding_payload(shipment_line_id, **overrides),
            make_freight_inspector_headers(inspector_user_id),
        )
    )


def accept_finding(finding_id: str, auditor_user_id: str = "aud-1") -> dict:
    """Accept a finding as an auditor who is not the recording inspector."""
    return get_success_data(
        api_client.accept_inspection_finding(
            finding_id, {}, make_classification_auditor_headers(auditor_user_id)
        )
    )


def record_and_accept_finding(
    shipment_line_id: str,
    inspector_user_id: str = "insp-1",
    auditor_user_id: str = "aud-1",
    **overrides,
) -> dict:
    finding = record_finding(shipment_line_id, inspector_user_id, **overrides)
    return accept_finding(finding["id"], auditor_user_id)


# ==========================================================================
# Tier 4 -- correction notices
# ==========================================================================


def list_notices_for(shipment_id: str, headers: dict = None) -> list:
    response = api_client.list_correction_notices(
        headers or AUDITOR_HEADERS, params={"shipment_id": shipment_id, "limit": 100}
    )
    rows, _meta = validate_paginated(response)
    return rows


def find_draft_notice(shipment_id: str) -> dict:
    """The one `DRAFT` notice a capture raised for this shipment."""
    drafts = [row for row in list_notices_for(shipment_id) if row["status"] == "DRAFT"]
    assert len(drafts) == 1, (
        f"expected exactly one DRAFT notice on shipment {shipment_id}, found {len(drafts)}"
    )
    return drafts[0]


def draft_manual_notice(
    shipment_id: str, expected_shipment_version: int = None, **overrides
) -> dict:
    """Draft a notice by hand, reading the live shipment version when none is given."""
    if expected_shipment_version is None:
        expected_shipment_version = get_shipment(shipment_id)["version"]
    return get_success_data(
        api_client.create_correction_notice(
            f.create_correction_notice_payload(
                shipment_id, expected_shipment_version, **overrides
            ),
            AUDITOR_HEADERS,
        )
    )


def issue_notice(notice_id: str, auditor_user_id: str = "aud-1") -> dict:
    return get_success_data(
        api_client.issue_correction_notice(
            notice_id, {}, make_classification_auditor_headers(auditor_user_id)
        )
    )


def get_notice(notice_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_correction_notice(notice_id, headers or AUDITOR_HEADERS)
    )


def sweep_notices() -> dict:
    return get_success_data(api_client.create_notice_sweep({}, ANALYST_HEADERS))


def setup_captured_shipment_with_draft_notice(
    env: dict = None,
    pro_number: str = "PRO001",
    measured_total_weight_lb: int = 520,
    line_measurements: list = None,
    device_type: str = "COMBINED",
    **kwargs,
) -> dict:
    """A billed single-line shipment plus one capture large enough to raise an
    automated `DRAFT` correction notice."""
    scenario = setup_single_line_billed_shipment(env=env, pro_number=pro_number, **kwargs)
    capture = record_capture(
        scenario["shipment_id"],
        scenario["terminal_id"],
        measured_total_weight_lb,
        line_measurements or single_line_measurement(measured_total_weight_lb),
        device_type=device_type,
    )
    notice = find_draft_notice(scenario["shipment_id"])
    scenario["capture_event"] = capture
    scenario["notice"] = notice
    scenario["notice_id"] = notice["id"]
    scenario["shipment"] = get_shipment(scenario["shipment_id"])
    return scenario


def setup_issued_notice_scenario(
    env: dict = None,
    pro_number: str = "PRO001",
    measured_total_weight_lb: int = 520,
    **kwargs,
) -> dict:
    """A captured shipment whose automated notice has been issued, which freezes
    `applied_delta_cents`, stamps the inspection fee and opens the dispute window."""
    scenario = setup_captured_shipment_with_draft_notice(
        env=env,
        pro_number=pro_number,
        measured_total_weight_lb=measured_total_weight_lb,
        **kwargs,
    )
    issued = issue_notice(scenario["notice_id"])
    scenario["notice"] = issued
    scenario["shipment"] = get_shipment(scenario["shipment_id"])
    scenario["customer"] = get_customer(scenario["customer_id"])
    return scenario


# ==========================================================================
# Tier 5 -- disputes and credit memos
# ==========================================================================


def file_dispute(correction_notice_id: str, customer_id: str, **overrides) -> dict:
    """File as the shipper whose `X-User-ID` is that shipper account's own id."""
    return get_success_data(
        api_client.create_dispute(
            f.create_dispute_payload(correction_notice_id, **overrides),
            make_shipper_headers(customer_id),
        )
    )


def request_supplement(dispute_id: str, reviewer_user_id: str = "rev-1") -> dict:
    return get_success_data(
        api_client.request_dispute_supplement(
            dispute_id, {}, make_dispute_reviewer_headers(reviewer_user_id)
        )
    )


def supplement_dispute(dispute_id: str, customer_id: str, additional_doc_count: int = 2) -> dict:
    return get_success_data(
        api_client.supplement_dispute(
            dispute_id,
            f.supplement_dispute_payload(additional_doc_count),
            make_shipper_headers(customer_id),
        )
    )


def resolve_dispute(
    dispute_id: str, outcome: str, reviewer_user_id: str = "rev-1", **overrides
) -> dict:
    return get_success_data(
        api_client.resolve_dispute(
            dispute_id,
            f.resolve_dispute_payload(outcome, **overrides),
            make_dispute_reviewer_headers(reviewer_user_id),
        )
    )


def get_dispute(dispute_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_dispute(dispute_id, headers or REVIEWER_HEADERS))


def list_credit_memos_for(customer_id: str, headers: dict = None) -> list:
    response = api_client.list_credit_memos(
        headers or ANALYST_HEADERS, params={"customer_id": customer_id, "limit": 100}
    )
    rows, _meta = validate_paginated(response)
    return rows


def setup_disputed_notice_scenario(
    env: dict = None,
    pro_number: str = "PRO001",
    measured_total_weight_lb: int = 520,
    dispute_overrides: dict = None,
    **kwargs,
) -> dict:
    """An issued notice with one `OPEN` dispute filed against it inside its window."""
    scenario = setup_issued_notice_scenario(
        env=env,
        pro_number=pro_number,
        measured_total_weight_lb=measured_total_weight_lb,
        **kwargs,
    )
    dispute = file_dispute(
        scenario["notice_id"], scenario["customer_id"], **(dispute_overrides or {})
    )
    scenario["dispute"] = dispute
    scenario["dispute_id"] = dispute["id"]
    scenario["notice"] = get_notice(scenario["notice_id"])
    return scenario


def setup_resolved_dispute_scenario(
    outcome: str,
    env: dict = None,
    pro_number: str = "PRO001",
    measured_total_weight_lb: int = 520,
    resolve_overrides: dict = None,
    **kwargs,
) -> dict:
    """A disputed notice resolved one of the three ways, with the cascade applied."""
    scenario = setup_disputed_notice_scenario(
        env=env,
        pro_number=pro_number,
        measured_total_weight_lb=measured_total_weight_lb,
        **kwargs,
    )
    resolved = resolve_dispute(
        scenario["dispute_id"], outcome, **(resolve_overrides or {})
    )
    scenario["dispute"] = resolved
    scenario["notice"] = get_notice(scenario["notice_id"])
    scenario["shipment"] = get_shipment(scenario["shipment_id"])
    scenario["customer"] = get_customer(scenario["customer_id"])
    scenario["credit_memos"] = list_credit_memos_for(scenario["customer_id"])
    return scenario


# ==========================================================================
# Tier 5 -- repricing runs
# ==========================================================================


def create_repricing_run(
    new_tariff_version_id: str,
    sample_window_start_at: str,
    sample_window_end_at: str,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_repricing_run(
            f.create_repricing_run_payload(
                new_tariff_version_id,
                sample_window_start_at,
                sample_window_end_at,
                **overrides,
            ),
            ANALYST_HEADERS,
        )
    )


def model_repricing_run(repricing_run_id: str) -> dict:
    return get_success_data(
        api_client.model_repricing_run(repricing_run_id, {}, ANALYST_HEADERS)
    )


def commit_repricing_run(repricing_run_id: str) -> dict:
    return get_success_data(
        api_client.commit_repricing_run(repricing_run_id, {}, ANALYST_HEADERS)
    )


def get_repricing_run(repricing_run_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_repricing_run(repricing_run_id, headers or ANALYST_HEADERS)
    )

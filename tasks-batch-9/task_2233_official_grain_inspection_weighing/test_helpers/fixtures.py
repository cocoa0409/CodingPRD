"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only the endpoints the PRD declares. Setup
calls use the lenient validator so a broken precondition surfaces as a clear
"Setup step failed" message rather than an opaque assertion.
"""

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ALL_ENDORSEMENTS,
    BUSINESS_HOURS_CLOCK,
    CORN_NO_1_FACTORS,
    DEFAULT_CERTIFIED_UNTIL,
    SIX_CORN_DRAFTS,
    SIX_CORN_DRAFTS_DOCKAGE_PCT,
    SOYBEANS_NO_2_FACTORS,
    TEST_DEFAULTS,
)
from .factories import (
    appeal_payload,
    appeal_vote_payload,
    applicant_payload,
    assign_sample_payload,
    break_seal_payload,
    certificate_payload,
    certify_payload,
    clock_payload,
    close_watch_payload,
    comparison_check_payload,
    delegated_area_payload,
    designated_area_payload,
    dismiss_payload,
    equipment_payload,
    fee_schedule_payload,
    grading_result_payload,
    inspection_request_payload,
    inspector_payload,
    payment_payload,
    protein_analysis_payload,
    sample_payload,
    service_area_payload,
    supervise_payload,
    suspension_payload,
    training_record_payload,
    vessel_watch_payload,
    weighing_record_payload,
)
from .test_users import ADMIN, APPLICANT, INSPECTOR, SUPERVISOR


# --------------------------------------------------------------------------- #
# Tier 0 — single-call primitives
# --------------------------------------------------------------------------- #

def set_clock(current_utc: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api_client.set_current_utc(clock_payload(current_utc), headers or ADMIN)
    )


def create_area(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_service_area(service_area_payload(**overrides), ADMIN)
    )


def create_designated_area(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_service_area(designated_area_payload(**overrides), ADMIN)
    )


def create_delegated_area(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_service_area(delegated_area_payload(**overrides), ADMIN)
    )


def draft_schedule(service_area_id: str, service_class: str, **overrides):
    return get_success_data(
        api_client.create_fee_schedule(
            fee_schedule_payload(service_area_id, service_class, **overrides), ADMIN
        )
    )


def activate_schedule(fee_schedule_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.activate_fee_schedule(fee_schedule_id, ADMIN))


def create_active_schedule(service_area_id: str, service_class: str, **overrides):
    drafted = draft_schedule(service_area_id, service_class, **overrides)
    return activate_schedule(drafted["id"])


def create_applicant_account(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_applicant(applicant_payload(**overrides), ADMIN)
    )


def create_inspector_row(
    service_area_id: str,
    license_number: str = "L-1001",
    endorsements: Optional[Iterable[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_inspector(
            inspector_payload(
                service_area_id,
                license_number=license_number,
                endorsements=list(endorsements) if endorsements else list(ALL_ENDORSEMENTS),
                **overrides,
            ),
            ADMIN,
        )
    )


def file_training_hours(inspector_id: str, hours: int = 24) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_training_record(
            inspector_id, training_record_payload(hours=hours), ADMIN
        )
    )


def activate_licence(inspector_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.activate_inspector(inspector_id, ADMIN))


def create_active_inspector(
    service_area_id: str,
    license_number: str = "L-1001",
    endorsements: Optional[Iterable[str]] = None,
    hours: int = 24,
    **overrides,
) -> Dict[str, Any]:
    """Licence an inspector and walk PROBATIONARY to ACTIVE, which requires at
    least 24 completed training hours and a performance score of at least 80."""
    inspector = create_inspector_row(
        service_area_id, license_number, endorsements, **overrides
    )
    file_training_hours(inspector["id"], hours)
    return activate_licence(inspector["id"])


def suspend_licence(inspector_id: str, reason: str = "Under investigation"):
    return get_success_data(
        api_client.suspend_inspector(inspector_id, suspension_payload(reason), ADMIN)
    )


def create_equipment_row(service_area_id: str, equipment_kind: str, **overrides):
    return get_success_data(
        api_client.create_equipment(
            equipment_payload(service_area_id, equipment_kind, **overrides), ADMIN
        )
    )


def certify(
    equipment_id: str,
    certified_until: str = DEFAULT_CERTIFIED_UNTIL,
    test_error_lbs: Optional[float] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"certified_until": certified_until}
    if test_error_lbs is not None:
        payload["test_error_lbs"] = test_error_lbs
    return get_success_data(api_client.certify_equipment(equipment_id, payload, ADMIN))


def create_certified_sampling_device(
    service_area_id: str, asset_code: str = "PROBE-1", **overrides
) -> Dict[str, Any]:
    device = create_equipment_row(
        service_area_id, "SAMPLING_DEVICE", asset_code=asset_code, **overrides
    )
    return certify(device["id"])


def create_certified_scale(
    service_area_id: str,
    asset_code: str = "SCALE-1",
    capacity_lbs: float = TEST_DEFAULTS["SCALE_CAPACITY_LBS"],
    tolerance_lbs: float = TEST_DEFAULTS["SCALE_TOLERANCE_LBS"],
    test_error_lbs: float = TEST_DEFAULTS["SCALE_TEST_ERROR_LBS"],
    **overrides,
) -> Dict[str, Any]:
    scale = create_equipment_row(
        service_area_id,
        "SCALE",
        asset_code=asset_code,
        capacity_lbs=capacity_lbs,
        tolerance_lbs=tolerance_lbs,
        **overrides,
    )
    return certify(scale["id"], test_error_lbs=test_error_lbs)


def create_certified_instrument(
    service_area_id: str,
    asset_code: str = "NIR-1",
    certified_until: str = DEFAULT_CERTIFIED_UNTIL,
    **overrides,
) -> Dict[str, Any]:
    instrument = create_equipment_row(
        service_area_id, "PROTEIN_INSTRUMENT", asset_code=asset_code, **overrides
    )
    return certify(instrument["id"], certified_until=certified_until)


def create_request(
    applicant_id: str, service_area_id: str, headers=None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_inspection_request(
            inspection_request_payload(applicant_id, service_area_id, **overrides),
            headers or ADMIN,
        )
    )


def draw_sample(
    inspection_request_id: str,
    sampling_device_id: str,
    inspector_id: str,
    headers=None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_sample(
            sample_payload(
                inspection_request_id, sampling_device_id, inspector_id, **overrides
            ),
            headers or INSPECTOR,
        )
    )


def break_sample_seal(sample_id: str, reason: str = "seal found cut on arrival"):
    return get_success_data(
        api_client.break_seal(sample_id, SUPERVISOR, break_seal_payload(reason))
    )


def record_grading(
    inspection_request_id: str,
    sample_id: str,
    inspector_id: str,
    factors: Optional[Dict[str, float]] = None,
    headers=None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_grading_result(
            grading_result_payload(
                inspection_request_id, sample_id, inspector_id, factors, **overrides
            ),
            headers or INSPECTOR,
        )
    )


def record_analysis(
    inspection_request_id: str,
    sample_id: str,
    instrument_id: str,
    inspector_id: str,
    protein_pct_as_is: float = 34.60,
    instrument_moisture_pct: float = 11.20,
    headers=None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_protein_analysis(
            protein_analysis_payload(
                inspection_request_id,
                sample_id,
                instrument_id,
                inspector_id,
                protein_pct_as_is,
                instrument_moisture_pct,
                **overrides,
            ),
            headers or INSPECTOR,
        )
    )


def record_weighing(
    inspection_request_id: str,
    scale_id: str,
    weigher_inspector_id: str,
    drafts: Optional[List[Dict[str, int]]] = None,
    headers=None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_weighing_record(
            weighing_record_payload(
                inspection_request_id,
                scale_id,
                weigher_inspector_id,
                drafts if drafts is not None else list(SIX_CORN_DRAFTS),
                **overrides,
            ),
            headers or INSPECTOR,
        )
    )


def countersign(weighing_record_id: str, supervisor_inspector_id: str):
    return get_success_data(
        api_client.supervise_weighing_record(
            weighing_record_id, supervise_payload(supervisor_inspector_id), SUPERVISOR
        )
    )


def issue_certificate(
    inspection_request_id: str,
    issuing_inspector_id: str,
    certificate_type: str = "GRADE",
    headers=None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_certificate(
            certificate_payload(
                inspection_request_id, issuing_inspector_id, certificate_type
            ),
            headers or INSPECTOR,
        )
    )


def file_appeal(
    certificate_id: str,
    applicant_id: str,
    expected_certificate_version: int,
    appeal_type: str = "APPEAL",
    headers=None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_appeal(
            appeal_payload(
                certificate_id, applicant_id, expected_certificate_version, appeal_type
            ),
            headers or ADMIN,
        )
    )


def assign_appeal_sample(appeal_id: str, sample_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.assign_appeal_sample(appeal_id, assign_sample_payload(sample_id), ADMIN)
    )


def cast_vote(
    appeal_id: str,
    inspector_id: str,
    vote: str,
    expected_appeal_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Cast one panel vote, re-reading the appeal first so the version echo is
    the version this member last observed."""
    if expected_appeal_version is None:
        expected_appeal_version = read_appeal(appeal_id)["version"]
    return get_success_data(
        api_client.create_appeal_vote(
            appeal_vote_payload(appeal_id, inspector_id, vote, expected_appeal_version),
            SUPERVISOR,
        )
    )


def decide(appeal_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.decide_appeal(appeal_id, ADMIN))


def dismiss(appeal_id: str, reason: str = "withdrawn by the applicant"):
    return get_success_data(
        api_client.dismiss_appeal(appeal_id, ADMIN, dismiss_payload(reason))
    )


def pay(applicant_id: str, amount_cents: int) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_payment(applicant_id, payment_payload(amount_cents), ADMIN)
    )


def file_check(
    instrument_id: str,
    inspector_id: str,
    reference_value_pct: float,
    instrument_reading_pct: float,
    headers=None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_comparison_check(
            comparison_check_payload(
                instrument_id, inspector_id, reference_value_pct, instrument_reading_pct
            ),
            headers or ADMIN,
        )
    )


def schedule_watch(
    inspection_request_id: str,
    supervisor_inspector_id: str,
    window_start_at: str,
    window_end_at: str,
    holds_declared: int = 3,
    headers=None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_vessel_watch(
            vessel_watch_payload(
                inspection_request_id,
                supervisor_inspector_id,
                window_start_at,
                window_end_at,
                holds_declared,
                **overrides,
            ),
            headers or ADMIN,
        )
    )


def start_watch(vessel_watch_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.start_vessel_watch(vessel_watch_id, SUPERVISOR))


def close_watch(
    vessel_watch_id: str, holds_supervised: int, stowage_certified: bool = True
) -> Dict[str, Any]:
    return get_success_data(
        api_client.close_vessel_watch(
            vessel_watch_id,
            close_watch_payload(holds_supervised, stowage_certified),
            SUPERVISOR,
        )
    )


def abort_watch(vessel_watch_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.abort_vessel_watch(vessel_watch_id, ADMIN))


# --------------------------------------------------------------------------- #
# Read-back helpers
# --------------------------------------------------------------------------- #

def read_area(service_area_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_service_area(service_area_id, ADMIN))


def read_schedule(fee_schedule_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_fee_schedule(fee_schedule_id, ADMIN))


def read_applicant(applicant_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_applicant(applicant_id, ADMIN))


def read_inspector(inspector_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_inspector(inspector_id, ADMIN))


def read_equipment(equipment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_equipment(equipment_id, ADMIN))


def read_request(inspection_request_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_inspection_request(inspection_request_id, ADMIN)
    )


def read_sample(sample_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_sample(sample_id, ADMIN))


def read_grading(grading_result_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_grading_result(grading_result_id, ADMIN))


def read_analysis(analysis_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_protein_analysis(analysis_id, ADMIN))


def read_weighing(weighing_record_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_weighing_record(weighing_record_id, ADMIN))


def read_certificate(certificate_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_certificate(certificate_id, ADMIN))


def read_appeal(appeal_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_appeal(appeal_id, ADMIN))


def read_watch(vessel_watch_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_vessel_watch(vessel_watch_id, ADMIN))


# --------------------------------------------------------------------------- #
# Tier 2 — the field office
# --------------------------------------------------------------------------- #

def setup_office(
    authority_type: str = "DESIGNATED",
    clock: Optional[str] = BUSINESS_HOURS_CLOCK,
    area_overrides: Optional[Dict[str, Any]] = None,
    fee_schedules: Iterable[Dict[str, Any]] = (),
    applicant_overrides: Optional[Dict[str, Any]] = None,
    with_equipment: bool = True,
    second_supervisor: bool = False,
) -> Dict[str, Any]:
    """A standing field office: the logical clock inside standard hours, one
    service area, its ACTIVE fee schedules, one applicant account, two fully
    endorsed ACTIVE inspectors and a certified sampling device, scale and
    protein instrument.

    ``fee_schedules`` is an iterable of dicts, each carrying a
    ``service_class`` plus any of ``base_fee_cents``,
    ``per_thousand_bushel_rate_cents``, ``overtime_multiplier_bp``,
    ``minimum_fee_cents``, ``effective_from`` and ``effective_to``.
    """
    if clock is not None:
        set_clock(clock)

    overrides = dict(area_overrides or {})
    if authority_type == "DESIGNATED":
        area = create_designated_area(**overrides)
    else:
        area = create_delegated_area(**overrides)

    schedules: Dict[str, Dict[str, Any]] = {}
    for spec in fee_schedules:
        spec = dict(spec)
        service_class = spec.pop("service_class")
        schedules[service_class] = create_active_schedule(
            area["id"], service_class, **spec
        )

    applicant = create_applicant_account(**(applicant_overrides or {}))

    inspector = create_active_inspector(area["id"], "L-1001")
    supervisor = create_active_inspector(area["id"], "L-1002")
    office: Dict[str, Any] = {
        "area": area,
        "schedules": schedules,
        "applicant": applicant,
        "inspector": inspector,
        "supervisor": supervisor,
    }
    if second_supervisor:
        office["supervisor_2"] = create_active_inspector(area["id"], "L-1003")

    if with_equipment:
        office["probe"] = create_certified_sampling_device(area["id"], "PROBE-1")
        office["scale"] = create_certified_scale(area["id"], "SCALE-1")
        office["instrument"] = create_certified_instrument(area["id"], "NIR-1")

    return office


# --------------------------------------------------------------------------- #
# Tier 3 — request lifecycle shortcuts
# --------------------------------------------------------------------------- #

def setup_sampled_request(
    office: Dict[str, Any],
    commodity: str = "CORN",
    declared_quantity_bushels: float = 500,
    requested_services: Iterable[str] = ("GRADING",),
    portions_count: int = 2,
    lot_identifier: str = "LOT-A1",
    seal_number: str = "SEAL-A1",
    inspector_id: Optional[str] = None,
) -> Dict[str, Any]:
    """An inspection request advanced OPEN to SAMPLED by one sealed original
    sample."""
    request = create_request(
        office["applicant"]["id"],
        office["area"]["id"],
        commodity=commodity,
        declared_quantity_bushels=declared_quantity_bushels,
        requested_services=list(requested_services),
        lot_identifier=lot_identifier,
    )
    sample = draw_sample(
        request["id"],
        office["probe"]["id"],
        inspector_id or office["inspector"]["id"],
        portions_count=portions_count,
        seal_number=seal_number,
    )
    return {"request": request, "sample": sample}


def setup_graded_request(
    office: Dict[str, Any],
    commodity: str = "CORN",
    factors: Optional[Dict[str, float]] = None,
    grader_id: Optional[str] = None,
    **sample_kwargs,
) -> Dict[str, Any]:
    """A request advanced through to GRADED with one FINAL determination."""
    staged = setup_sampled_request(office, commodity=commodity, **sample_kwargs)
    if factors is None:
        factors = CORN_NO_1_FACTORS if commodity == "CORN" else SOYBEANS_NO_2_FACTORS
    grading = record_grading(
        staged["request"]["id"],
        staged["sample"]["id"],
        grader_id or office["inspector"]["id"],
        factors=factors,
    )
    staged["grading"] = grading
    return staged


def setup_certificated_request(
    office: Dict[str, Any],
    certificate_type: str = "GRADE",
    issuer_id: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """A graded request carrying one ISSUED certificate of the given type."""
    staged = setup_graded_request(office, **kwargs)
    staged["certificate"] = issue_certificate(
        staged["request"]["id"],
        issuer_id or office["inspector"]["id"],
        certificate_type,
    )
    return staged


def setup_weighed_request(
    office: Dict[str, Any],
    drafts: Optional[List[Dict[str, int]]] = None,
    dockage_pct: Optional[float] = SIX_CORN_DRAFTS_DOCKAGE_PCT,
    commodity: str = "CORN",
    declared_quantity_bushels: float = 3500,
    requested_services: Iterable[str] = ("GRADING", "WEIGHING"),
    lot_identifier: str = "LOT-W1",
    weigher_id: Optional[str] = None,
) -> Dict[str, Any]:
    """An inspection request whose weighing dimension has advanced PENDING to
    WEIGHED on a certified scale."""
    request = create_request(
        office["applicant"]["id"],
        office["area"]["id"],
        commodity=commodity,
        declared_quantity_bushels=declared_quantity_bushels,
        requested_services=list(requested_services),
        lot_identifier=lot_identifier,
    )
    extra: Dict[str, Any] = {}
    if dockage_pct is not None:
        extra["dockage_pct"] = dockage_pct
    record = record_weighing(
        request["id"],
        office["scale"]["id"],
        weigher_id or office["inspector"]["id"],
        drafts,
        **extra,
    )
    return {"request": request, "weighing": record}


def setup_graded_and_weighed_request(
    office: Dict[str, Any],
    factors: Optional[Dict[str, float]] = None,
    drafts: Optional[List[Dict[str, int]]] = None,
    dockage_pct: Optional[float] = SIX_CORN_DRAFTS_DOCKAGE_PCT,
    requested_services: Iterable[str] = ("GRADING", "WEIGHING"),
    portions_count: int = 2,
    countersigned: bool = False,
    weigher_id: Optional[str] = None,
    supervisor_id: Optional[str] = None,
    **request_kwargs,
) -> Dict[str, Any]:
    """A request whose grading dimension is GRADED and whose weighing dimension
    is WEIGHED (optionally countersigned to SUPERVISED)."""
    staged = setup_weighed_request(
        office,
        drafts=drafts,
        dockage_pct=dockage_pct,
        requested_services=requested_services,
        weigher_id=weigher_id,
        **request_kwargs,
    )
    sample = draw_sample(
        staged["request"]["id"],
        office["probe"]["id"],
        office["inspector"]["id"],
        portions_count=portions_count,
        seal_number="SEAL-GW1",
    )
    grading = record_grading(
        staged["request"]["id"],
        sample["id"],
        office["inspector"]["id"],
        factors=factors if factors is not None else CORN_NO_1_FACTORS,
    )
    staged["sample"] = sample
    staged["grading"] = grading
    if countersigned:
        staged["weighing"] = countersign(
            staged["weighing"]["id"], supervisor_id or office["supervisor"]["id"]
        )
    return staged


# --------------------------------------------------------------------------- #
# Tier 4 — appeal panels
# --------------------------------------------------------------------------- #

def setup_appeal_panel(
    office: Dict[str, Any], size: int, first_license_index: int = 4001
) -> List[Dict[str, Any]]:
    """N further ACTIVE inspectors in the office's area, available to sit on a
    panel."""
    return [
        create_active_inspector(office["area"]["id"], f"L-{first_license_index + n}")
        for n in range(size)
    ]


def setup_filed_appeal(
    office: Dict[str, Any],
    appeal_type: str = "APPEAL",
    factors: Optional[Dict[str, float]] = None,
    portions_count: int = 4,
    **kwargs,
) -> Dict[str, Any]:
    """A graded request with an ISSUED GRADE certificate that has been
    challenged, so the appeal sits in FILED."""
    staged = setup_certificated_request(
        office, "GRADE", factors=factors, portions_count=portions_count, **kwargs
    )
    certificate = read_certificate(staged["certificate"]["id"])
    staged["appeal"] = file_appeal(
        certificate["id"],
        office["applicant"]["id"],
        certificate["version"],
        appeal_type,
    )
    return staged


def setup_appeal_under_review(
    office: Dict[str, Any],
    appeal_type: str = "APPEAL",
    factors: Optional[Dict[str, float]] = None,
    regrade_factors: Optional[Dict[str, float]] = None,
    panel_size: int = 3,
    portions_count: int = 4,
    **kwargs,
) -> Dict[str, Any]:
    """A challenged certificate whose appeal has a retained sample and a
    regrade, so the appeal sits in UNDER_REVIEW with a panel standing by."""
    staged = setup_filed_appeal(
        office,
        appeal_type=appeal_type,
        factors=factors,
        portions_count=portions_count,
        **kwargs,
    )
    # One further inspector performs the regrade; the rest form the voting panel.
    panel = setup_appeal_panel(office, panel_size + 1)
    assign_appeal_sample(staged["appeal"]["id"], staged["sample"]["id"])
    staged["regrade"] = record_grading(
        staged["request"]["id"],
        staged["sample"]["id"],
        panel[0]["id"],
        factors=regrade_factors,
        appeal_id=staged["appeal"]["id"],
    )
    staged["regrader"] = panel[0]
    staged["panel"] = panel
    staged["voters"] = panel[1:]
    staged["appeal"] = read_appeal(staged["appeal"]["id"])
    return staged

"""Composite setup builders.

Every test starts against an empty database, so all preconditions have to be
built through the public API. The builders below are layered: each one takes the
context dictionary produced by the previous layer, performs its own calls and
returns the same dictionary enriched with the new records. A context holds

    clock            the instant the logical clock was last set to (or None)
    areas            system area code -> record
    manufacturer     the OEM record (kept fresh after a pricing restatement)
    vehicle_models   model code -> record
    vehicle_model    the first registered model, for single-model scenarios
    license          the license record
    shop             the shop record (kept fresh after funding)
    manager_headers  headers for the manager of ``shop``
    entitlement      the entitlement record, re-read whenever its version moves
    technicians      technician key -> record
    tech_headers     technician key -> headers for that technician
    seats            technician key -> seat assignment record
    tools            tool key -> record
    publications     publication key -> record
    versions         version key -> record
    sessions         session key -> record
    jobs             job key -> record

Keys default to ``"main"`` so that a single-object scenario reads naturally,
while multi-object scenarios name each object explicitly.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .constants import (
    DEFAULT_FUNDING_CENTS,
    INITIAL_CLOCK,
    VIN_PRIMARY,
)
from .test_users import (
    COMPLIANCE_OFFICER_1_USER_ID,
    CONTENT_PUBLISHER_1_USER_ID,
    CONTENT_PUBLISHER_2_USER_ID,
    make_compliance_officer_headers,
    make_content_publisher_headers,
    make_platform_admin_headers,
    make_shop_manager_headers,
    make_technician_headers,
)
from .types import (
    EntitlementModel,
    JobType,
    PublicationType,
    ShopTier,
)

Context = Dict[str, Any]

DEFAULT_AREA_CODES = ("POWERTRAIN", "ADAS", "BODY_ELECTRICAL")


def new_context() -> Context:
    return {
        "clock": None,
        "areas": {},
        "manufacturer": None,
        "vehicle_models": {},
        "vehicle_model": None,
        "license": None,
        "shop": None,
        "manager_headers": None,
        "entitlement": None,
        "technicians": {},
        "tech_headers": {},
        "seats": {},
        "tools": {},
        "publications": {},
        "versions": {},
        "sessions": {},
        "jobs": {},
    }


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, ctx: Context, instant: str) -> Context:
    """Move the logical clock and remember where it is."""
    get_success_data(api.set_clock(instant, make_platform_admin_headers()))
    ctx["clock"] = instant
    return ctx


# ---------------------------------------------------------------------------
# Tier 1 — catalogue
# ---------------------------------------------------------------------------


def build_catalogue(
    api: ApiClient,
    *,
    clock: Optional[str] = INITIAL_CLOCK,
    area_codes: Sequence[str] = DEFAULT_AREA_CODES,
    manufacturer_overrides: Optional[Dict[str, Any]] = None,
    model_codes: Sequence[str] = ("AX7",),
) -> Context:
    """System areas, one OEM and its vehicle models.

    Pass ``clock=None`` to leave the logical clock untouched.
    """
    ctx = new_context()
    admin = make_platform_admin_headers()
    if clock is not None:
        set_clock(api, ctx, clock)

    for code in area_codes:
        ctx["areas"][code] = get_success_data(
            api.create_system_area(factories.system_area_payload(code), admin)
        )

    ctx["manufacturer"] = get_success_data(
        api.create_manufacturer(
            factories.manufacturer_payload(**(manufacturer_overrides or {})), admin
        )
    )

    for code in model_codes:
        ctx["vehicle_models"][code] = get_success_data(
            api.create_vehicle_model(
                factories.vehicle_model_payload(
                    ctx["manufacturer"]["id"], model_code=code
                ),
                admin,
            )
        )
    if model_codes:
        ctx["vehicle_model"] = ctx["vehicle_models"][model_codes[0]]
    return ctx


def area_ids(ctx: Context, codes: Optional[Sequence[str]] = None) -> List[str]:
    codes = codes if codes is not None else list(ctx["areas"].keys())
    return [ctx["areas"][code]["id"] for code in codes]


def restate_pricing(api: ApiClient, ctx: Context, **fields) -> Context:
    """Restate one or more parity pricing inputs and refresh the stored OEM."""
    ctx["manufacturer"] = get_success_data(
        api.restate_manufacturer_pricing(
            ctx["manufacturer"]["id"], dict(fields), make_platform_admin_headers()
        )
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 1 — license
# ---------------------------------------------------------------------------


def add_license(
    api: ApiClient,
    ctx: Context,
    *,
    activate: bool = True,
    covered_area_codes: Optional[Sequence[str]] = None,
    **overrides,
) -> Context:
    """Draft a license over the named system areas and optionally activate it."""
    ctx["license"] = get_success_data(
        api.create_license(
            factories.license_payload(
                ctx["manufacturer"]["id"],
                area_ids(ctx, covered_area_codes),
                **overrides,
            ),
            make_platform_admin_headers(),
        )
    )
    if activate:
        ctx["license"] = get_success_data(
            api.activate_license(ctx["license"]["id"], make_platform_admin_headers())
        )
    return ctx


# ---------------------------------------------------------------------------
# Tier 2 — shop and data credit
# ---------------------------------------------------------------------------


def add_shop(
    api: ApiClient,
    ctx: Context,
    *,
    funding_cents: Optional[int] = DEFAULT_FUNDING_CENTS,
    tier: str = ShopTier.PRO,
    name: str = "Bay Auto",
    funding_ref: str = "FUND-1",
) -> Context:
    """Register a shop and fund its data credit."""
    admin = make_platform_admin_headers()
    ctx["shop"] = get_success_data(
        api.create_shop(factories.shop_payload(name=name, tier=tier), admin)
    )
    ctx["manager_headers"] = make_shop_manager_headers(ctx["shop"]["id"])
    if funding_cents:
        ctx["shop"] = get_success_data(
            api.fund_shop_credit(
                ctx["shop"]["id"],
                factories.credit_funding_payload(funding_cents, funding_ref=funding_ref),
                admin,
            )
        )
    return ctx


def refresh_shop(api: ApiClient, ctx: Context) -> Dict[str, Any]:
    """Re-read the shop and store it back on the context."""
    ctx["shop"] = get_success_data(
        api.get_shop(ctx["shop"]["id"], make_platform_admin_headers())
    )
    return ctx["shop"]


# ---------------------------------------------------------------------------
# Tier 2 — entitlement
# ---------------------------------------------------------------------------


def add_entitlement(
    api: ApiClient,
    ctx: Context,
    *,
    activate: bool = True,
    entitlement_model: str = EntitlementModel.SUBSCRIPTION,
    seats_total: int = 3,
    vin_quota: Optional[int] = None,
    **overrides,
) -> Context:
    """Buy an entitlement for the shop under the license and optionally activate it."""
    payload = factories.entitlement_payload(
        ctx["shop"]["id"],
        ctx["license"]["id"],
        entitlement_model=entitlement_model,
        seats_total=seats_total,
        **overrides,
    )
    if vin_quota is not None:
        payload["vin_quota"] = vin_quota
    ctx["entitlement"] = get_success_data(
        api.create_entitlement(payload, ctx["manager_headers"])
    )
    if activate:
        ctx["entitlement"] = get_success_data(
            api.activate_entitlement(ctx["entitlement"]["id"], ctx["manager_headers"])
        )
    refresh_shop(api, ctx)
    return ctx


def refresh_entitlement(api: ApiClient, ctx: Context) -> Dict[str, Any]:
    """Re-read the entitlement so its version is current before an OCC-guarded call."""
    ctx["entitlement"] = get_success_data(
        api.get_entitlement(ctx["entitlement"]["id"], ctx["manager_headers"])
    )
    return ctx["entitlement"]


# ---------------------------------------------------------------------------
# Tier 2 — technicians, seats and tools
# ---------------------------------------------------------------------------


def add_technician(
    api: ApiClient,
    ctx: Context,
    *,
    key: str = "main",
    verify: bool = True,
    full_name: str = "Tina Tech",
    credential_expires_at: Optional[str] = None,
    identity_document_ref: str = "DL-77123",
    verifier_user_id: str = COMPLIANCE_OFFICER_1_USER_ID,
) -> Context:
    """Enrol a technician at the shop and optionally carry it through verification."""
    payload = factories.technician_payload(ctx["shop"]["id"], full_name=full_name)
    if credential_expires_at is not None:
        payload["credential_expires_at"] = credential_expires_at
    technician = get_success_data(
        api.create_technician(payload, ctx["manager_headers"])
    )
    if verify:
        verify_body = factories.verify_technician_payload(
            identity_document_ref=identity_document_ref
        )
        if credential_expires_at is not None:
            verify_body["credential_expires_at"] = credential_expires_at
        technician = get_success_data(
            api.verify_technician(
                technician["id"],
                verify_body,
                make_compliance_officer_headers(verifier_user_id),
            )
        )
    ctx["technicians"][key] = technician
    ctx["tech_headers"][key] = make_technician_headers(technician["id"])
    return ctx


def add_seat(api: ApiClient, ctx: Context, *, key: str = "main") -> Context:
    """Seat the named technician on the entitlement, guarding on its current version."""
    entitlement = refresh_entitlement(api, ctx)
    ctx["seats"][key] = get_success_data(
        api.create_seat_assignment(
            factories.seat_assignment_payload(
                entitlement["id"],
                ctx["technicians"][key]["id"],
                entitlement["version"],
            ),
            ctx["manager_headers"],
        )
    )
    refresh_entitlement(api, ctx)
    return ctx


def add_tool(
    api: ApiClient,
    ctx: Context,
    *,
    key: str = "main",
    serial_no: str = "SN-0001",
    oem_attestation_expires_at: Optional[str] = None,
    shop_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Context:
    """Register a scan tool, by default at the context's own shop."""
    payload = factories.diagnostic_tool_payload(
        shop_id or ctx["shop"]["id"], serial_no=serial_no
    )
    if oem_attestation_expires_at is not None:
        payload["oem_attestation_expires_at"] = oem_attestation_expires_at
    ctx["tools"][key] = get_success_data(
        api.create_diagnostic_tool(payload, headers or ctx["manager_headers"])
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — publications and versions
# ---------------------------------------------------------------------------


def add_publication_version(
    api: ApiClient,
    ctx: Context,
    *,
    key: str = "main",
    system_area_code: str = "POWERTRAIN",
    model_code: Optional[str] = None,
    publication_type: str = PublicationType.REPAIR_PROCEDURE,
    source_tsb_ref: str = "TSB-0001",
    calibration_procedure_ref: Optional[str] = None,
    validate: bool = True,
    publish: bool = True,
    author_user_id: str = CONTENT_PUBLISHER_1_USER_ID,
    publisher_user_id: str = CONTENT_PUBLISHER_2_USER_ID,
    publication_key: Optional[str] = None,
) -> Context:
    """Open a publication, mint its first version and walk the two axes as asked.

    Validation and publication are recorded under different publisher
    identifiers, because a version may not be published by the publisher who
    validated it.
    """
    publication_key = publication_key or key
    author = make_content_publisher_headers(author_user_id)
    model = (
        ctx["vehicle_models"][model_code] if model_code else ctx["vehicle_model"]
    )
    publication = get_success_data(
        api.create_publication(
            factories.publication_payload(
                model["id"],
                ctx["areas"][system_area_code]["id"],
                publication_type=publication_type,
            ),
            author,
        )
    )
    ctx["publications"][publication_key] = publication

    version = mint_version(
        api,
        ctx,
        publication_key=publication_key,
        key=key,
        source_tsb_ref=source_tsb_ref,
        calibration_procedure_ref=calibration_procedure_ref,
        author_user_id=author_user_id,
    )
    if validate:
        version = validate_version(api, ctx, key=key, reviewer_user_id=author_user_id)
    if publish:
        version = publish_version(api, ctx, key=key, publisher_user_id=publisher_user_id)
    ctx["versions"][key] = version
    return ctx


def mint_version(
    api: ApiClient,
    ctx: Context,
    *,
    publication_key: str = "main",
    key: str = "main",
    source_tsb_ref: str = "TSB-0001",
    calibration_procedure_ref: Optional[str] = None,
    author_user_id: str = CONTENT_PUBLISHER_1_USER_ID,
) -> Dict[str, Any]:
    """Ingest another version of an existing publication, guarding on its version."""
    author = make_content_publisher_headers(author_user_id)
    publication = get_success_data(
        api.get_publication(ctx["publications"][publication_key]["id"], author)
    )
    ctx["publications"][publication_key] = publication
    version = get_success_data(
        api.create_publication_version(
            publication["id"],
            factories.publication_version_payload(
                publication["version"],
                source_tsb_ref=source_tsb_ref,
                calibration_procedure_ref=calibration_procedure_ref,
            ),
            author,
        )
    )
    ctx["versions"][key] = version
    return version


def validate_version(
    api: ApiClient,
    ctx: Context,
    *,
    key: str = "main",
    reviewer_user_id: str = CONTENT_PUBLISHER_1_USER_ID,
) -> Dict[str, Any]:
    version = get_success_data(
        api.validate_publication_version(
            ctx["versions"][key]["id"],
            factories.validate_version_payload(),
            make_content_publisher_headers(reviewer_user_id),
        )
    )
    ctx["versions"][key] = version
    return version


def publish_version(
    api: ApiClient,
    ctx: Context,
    *,
    key: str = "main",
    publisher_user_id: str = CONTENT_PUBLISHER_2_USER_ID,
) -> Dict[str, Any]:
    version = get_success_data(
        api.publish_publication_version(
            ctx["versions"][key]["id"],
            make_content_publisher_headers(publisher_user_id),
        )
    )
    ctx["versions"][key] = version
    return version


def recall_version(
    api: ApiClient,
    ctx: Context,
    *,
    key: str = "main",
    reason: str = "OEM withdrew the procedure",
    publisher_user_id: str = CONTENT_PUBLISHER_2_USER_ID,
) -> Dict[str, Any]:
    version = get_success_data(
        api.recall_publication_version(
            ctx["versions"][key]["id"],
            factories.reason_payload(reason),
            make_content_publisher_headers(publisher_user_id),
        )
    )
    ctx["versions"][key] = version
    return version


def refresh_version(
    api: ApiClient, ctx: Context, *, key: str = "main"
) -> Dict[str, Any]:
    """Re-read one version through its publication's version listing."""
    version_id = ctx["versions"][key]["id"]
    publication_id = ctx["versions"][key]["publication_id"]
    admin = make_platform_admin_headers()
    body = api.list_publication_versions(publication_id, admin, {"limit": 100})
    rows = get_success_data(body)
    if isinstance(rows, dict):
        rows = rows.get("data", [])
    for row in rows:
        if row["id"] == version_id:
            ctx["versions"][key] = row
            return row
    raise AssertionError(f"version {version_id} not present in its publication listing")


# ---------------------------------------------------------------------------
# Tier 3 — sessions and jobs
# ---------------------------------------------------------------------------


def add_session(
    api: ApiClient,
    ctx: Context,
    *,
    key: str = "main",
    technician_key: str = "main",
    tool_key: str = "main",
    activate: bool = True,
    vin: str = VIN_PRIMARY,
    **overrides,
) -> Context:
    """Request a gateway session for a seated technician and optionally activate it."""
    headers = ctx["tech_headers"][technician_key]
    ctx["sessions"][key] = get_success_data(
        api.create_gateway_session(
            factories.gateway_session_payload(
                ctx["seats"][technician_key]["id"],
                ctx["tools"][tool_key]["id"],
                vin=vin,
                **overrides,
            ),
            headers,
        )
    )
    if activate:
        ctx["sessions"][key] = get_success_data(
            api.activate_gateway_session(ctx["sessions"][key]["id"], headers)
        )
    return ctx


def refresh_session(
    api: ApiClient, ctx: Context, *, key: str = "main", technician_key: str = "main"
) -> Dict[str, Any]:
    ctx["sessions"][key] = get_success_data(
        api.get_gateway_session(
            ctx["sessions"][key]["id"], ctx["tech_headers"][technician_key]
        )
    )
    return ctx["sessions"][key]


def add_job(
    api: ApiClient,
    ctx: Context,
    *,
    key: str = "main",
    session_key: str = "main",
    version_key: str = "main",
    technician_key: str = "main",
    job_type: str = JobType.MODULE_FLASH,
    start: bool = True,
    complete: bool = False,
) -> Context:
    """Queue a programming job pinned to a published version, then start/complete it."""
    headers = ctx["tech_headers"][technician_key]
    job = get_success_data(
        api.create_programming_job(
            factories.programming_job_payload(
                ctx["sessions"][session_key]["id"],
                ctx["versions"][version_key]["id"],
                job_type=job_type,
            ),
            headers,
        )
    )
    if start or complete:
        job = get_success_data(api.start_programming_job(job["id"], headers))
    if complete:
        job = get_success_data(api.complete_programming_job(job["id"], headers))
    ctx["jobs"][key] = job
    return ctx


def refresh_job(
    api: ApiClient, ctx: Context, *, key: str = "main", technician_key: str = "main"
) -> Dict[str, Any]:
    ctx["jobs"][key] = get_success_data(
        api.get_programming_job(
            ctx["jobs"][key]["id"], ctx["tech_headers"][technician_key]
        )
    )
    return ctx["jobs"][key]


# ---------------------------------------------------------------------------
# Tier 3 — end-to-end shortcuts
# ---------------------------------------------------------------------------


def build_licensed_catalogue(
    api: ApiClient,
    *,
    clock: Optional[str] = INITIAL_CLOCK,
    area_codes: Sequence[str] = DEFAULT_AREA_CODES,
    covered_area_codes: Optional[Sequence[str]] = None,
    manufacturer_overrides: Optional[Dict[str, Any]] = None,
    model_codes: Sequence[str] = ("AX7",),
    activate_license: bool = True,
    **license_overrides,
) -> Context:
    """Catalogue plus one license over the covered system areas."""
    ctx = build_catalogue(
        api,
        clock=clock,
        area_codes=area_codes,
        manufacturer_overrides=manufacturer_overrides,
        model_codes=model_codes,
    )
    add_license(
        api,
        ctx,
        activate=activate_license,
        covered_area_codes=covered_area_codes,
        **license_overrides,
    )
    return ctx


def build_funded_shop(
    api: ApiClient,
    *,
    funding_cents: Optional[int] = DEFAULT_FUNDING_CENTS,
    tier: str = ShopTier.PRO,
    shop_name: str = "Bay Auto",
    **catalogue_kwargs,
) -> Context:
    """Licensed catalogue plus a funded shop, before any entitlement is bought."""
    ctx = build_licensed_catalogue(api, **catalogue_kwargs)
    add_shop(api, ctx, funding_cents=funding_cents, tier=tier, name=shop_name)
    return ctx


def build_entitled_shop(
    api: ApiClient,
    *,
    funding_cents: Optional[int] = DEFAULT_FUNDING_CENTS,
    tier: str = ShopTier.PRO,
    shop_name: str = "Bay Auto",
    activate_entitlement: bool = True,
    entitlement_model: str = EntitlementModel.SUBSCRIPTION,
    seats_total: int = 3,
    vin_quota: Optional[int] = None,
    entitlement_overrides: Optional[Dict[str, Any]] = None,
    **catalogue_kwargs,
) -> Context:
    """Funded shop that holds an entitlement under the license."""
    ctx = build_funded_shop(
        api,
        funding_cents=funding_cents,
        tier=tier,
        shop_name=shop_name,
        **catalogue_kwargs,
    )
    add_entitlement(
        api,
        ctx,
        activate=activate_entitlement,
        entitlement_model=entitlement_model,
        seats_total=seats_total,
        vin_quota=vin_quota,
        **(entitlement_overrides or {}),
    )
    return ctx


def build_seated_technician(
    api: ApiClient,
    *,
    full_name: str = "Tina Tech",
    credential_expires_at: Optional[str] = None,
    tool_serial_no: str = "SN-0001",
    oem_attestation_expires_at: Optional[str] = None,
    **entitlement_kwargs,
) -> Context:
    """Entitled shop with one verified, seated technician and one registered tool."""
    ctx = build_entitled_shop(api, **entitlement_kwargs)
    add_technician(
        api,
        ctx,
        full_name=full_name,
        credential_expires_at=credential_expires_at,
    )
    add_seat(api, ctx)
    add_tool(
        api,
        ctx,
        serial_no=tool_serial_no,
        oem_attestation_expires_at=oem_attestation_expires_at,
    )
    return ctx


def build_published_procedure(
    api: ApiClient,
    *,
    system_area_code: str = "POWERTRAIN",
    publication_type: str = PublicationType.REPAIR_PROCEDURE,
    validate: bool = True,
    publish: bool = True,
    calibration_procedure_ref: Optional[str] = None,
    **seat_kwargs,
) -> Context:
    """Seated technician plus a published procedure version to pin jobs to."""
    ctx = build_seated_technician(api, **seat_kwargs)
    add_publication_version(
        api,
        ctx,
        system_area_code=system_area_code,
        publication_type=publication_type,
        validate=validate,
        publish=publish,
        calibration_procedure_ref=calibration_procedure_ref,
    )
    return ctx


def build_active_session(
    api: ApiClient,
    *,
    vin: str = VIN_PRIMARY,
    session_overrides: Optional[Dict[str, Any]] = None,
    **procedure_kwargs,
) -> Context:
    """Everything up to and including one ACTIVE gateway session holding the tool."""
    ctx = build_published_procedure(api, **procedure_kwargs)
    add_session(api, ctx, vin=vin, **(session_overrides or {}))
    return ctx


def build_session_with_started_job(
    api: ApiClient,
    *,
    job_type: str = JobType.MODULE_FLASH,
    **session_kwargs,
) -> Context:
    """Active session with one IN_PROGRESS job pinned to the published version."""
    ctx = build_active_session(api, **session_kwargs)
    add_job(api, ctx, job_type=job_type, start=True)
    return ctx


def build_session_with_completed_jobs(
    api: ApiClient,
    *,
    job_types: Sequence[str] = (JobType.IMMOBILIZER_KEY, JobType.MODULE_FLASH),
    **session_kwargs,
) -> Context:
    """Active session whose named jobs have all been started and completed."""
    ctx = build_active_session(api, **session_kwargs)
    for index, job_type in enumerate(job_types, start=1):
        add_job(api, ctx, key=f"job_{index}", job_type=job_type, complete=True)
    return ctx


def build_revalidation_required_job(
    api: ApiClient,
    *,
    job_type: str = JobType.MODULE_FLASH,
    recall_reason: str = "OEM withdrew the procedure",
    **session_kwargs,
) -> Context:
    """Started job whose pinned version has been recalled, forcing revalidation."""
    ctx = build_session_with_started_job(api, job_type=job_type, **session_kwargs)
    recall_version(api, ctx, reason=recall_reason)
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — multi-actor and multi-resource scenarios
# ---------------------------------------------------------------------------


def add_second_shop(
    api: ApiClient,
    ctx: Context,
    *,
    name: str = "Harbor Motors",
    tier: str = ShopTier.PRO,
    funding_cents: int = DEFAULT_FUNDING_CENTS,
) -> Dict[str, Any]:
    """Register an unrelated second shop and return {shop, headers}."""
    admin = make_platform_admin_headers()
    shop = get_success_data(
        api.create_shop(factories.shop_payload(name=name, tier=tier), admin)
    )
    if funding_cents:
        shop = get_success_data(
            api.fund_shop_credit(
                shop["id"],
                factories.credit_funding_payload(funding_cents, funding_ref="FUND-2"),
                admin,
            )
        )
    other = {"shop": shop, "headers": make_shop_manager_headers(shop["id"])}
    ctx["other_shop"] = other
    return other


def build_two_seated_technicians(
    api: ApiClient,
    *,
    second_name: str = "Uri Tech",
    verify_second: bool = True,
    seats_total: int = 3,
    **entitlement_kwargs,
) -> Context:
    """One entitlement carrying two seated technicians and one shared tool.

    The seat ledger moves on every assignment, so the entitlement is re-read
    between the two calls and the second assignment guards on the fresh version.
    """
    ctx = build_entitled_shop(api, seats_total=seats_total, **entitlement_kwargs)
    add_technician(api, ctx, key="main", full_name="Tina Tech")
    add_seat(api, ctx, key="main")
    add_technician(api, ctx, key="second", full_name=second_name, verify=verify_second)
    add_seat(api, ctx, key="second")
    add_tool(api, ctx)
    return ctx


def build_two_session_tool_contention(
    api: ApiClient,
    *,
    first_window: Sequence[str] = ("2026-08-03T09:00:00Z", "2026-08-03T12:00:00Z"),
    **procedure_kwargs,
) -> Context:
    """One ACTIVE session holding the shared tool, ready for a second request.

    The second technician is seated and verified so that only the tool's own
    occupancy window stands between a further request and activation.
    """
    ctx = build_published_procedure(api, **procedure_kwargs)
    add_technician(api, ctx, key="second", full_name="Uri Tech")
    add_seat(api, ctx, key="second")
    add_session(
        api,
        ctx,
        key="session_a",
        technician_key="main",
        activate=True,
        window_start=first_window[0],
        window_end=first_window[1],
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 5 — settlement and terminal states
# ---------------------------------------------------------------------------


def build_settled_entitlement(
    api: ApiClient,
    *,
    settle_at: str = "2026-08-11T00:00:00Z",
    cancel_reason: str = "shop closed the bay",
    **entitlement_kwargs,
) -> Context:
    """Active entitlement carried to a FINAL settlement through cancellation."""
    ctx = build_entitled_shop(api, **entitlement_kwargs)
    set_clock(api, ctx, settle_at)
    ctx["entitlement"] = get_success_data(
        api.cancel_entitlement(
            ctx["entitlement"]["id"],
            factories.reason_payload(cancel_reason),
            ctx["manager_headers"],
        )
    )
    refresh_shop(api, ctx)
    return ctx


def build_terminated_license_scenario(
    api: ApiClient,
    *,
    terminate_at: Optional[str] = "2026-08-11T00:00:00Z",
    reason: str = "OEM withdrew the independent offer",
    session_window: Sequence[str] = ("2026-08-12T09:00:00Z", "2026-08-12T12:00:00Z"),
    **seat_kwargs,
) -> Context:
    """Seat, tool and one ACTIVE session carrying no billable job, then terminate.

    The session window sits ahead of the termination instant so that the cascade
    reaches a session that has not yet been closed.
    """
    ctx = build_seated_technician(api, **seat_kwargs)
    add_session(
        api,
        ctx,
        activate=True,
        window_start=session_window[0],
        window_end=session_window[1],
    )
    if terminate_at is not None:
        set_clock(api, ctx, terminate_at)
    ctx["license"] = get_success_data(
        api.terminate_license(
            ctx["license"]["id"],
            factories.reason_payload(reason),
            make_platform_admin_headers(),
        )
    )
    refresh_shop(api, ctx)
    return ctx

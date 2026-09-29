"""Composite setup helpers.

The harness restarts the API server before every individual test, so each test
begins against an empty database. Every helper here therefore builds its
preconditions from scratch, in the order the contract requires, and validates
each setup call leniently so a broken precondition fails loudly rather than
silently skewing an assertion.

Helpers are layered:

* single-step builders — register one entity or advance one lifecycle step;
* file builders — lodge a file, attach records and walk it to ACCEPTED;
* pipeline builders — carry a job from composition all the way to closure,
  returning every id and row the caller may need to assert on.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import ApiClient
from .constants import DEFAULT_CLOCK_UTC, SCAN_STAGE_ORDER
from .test_users import (
    ADMIN_USER_ID_2,
    BUREAU_ADMIN,
    CLIENT_LIAISON,
    COMPOSITION_OPERATOR,
    INTEGRITY_AUDITOR,
    OPERATOR_USER_ID,
    POSTAGE_CONTROLLER,
    POSTAGE_USER_ID,
    POSTAGE_USER_ID_2,
    PRODUCTION_SCHEDULER,
    headers_for,
)
from .types import Role

# Default production instants, chosen so every window sits ahead of the clock.
DEFAULT_WINDOW_START = "2026-08-05T09:00:00Z"
DEFAULT_RUN_START_CLOCK = "2026-08-05T09:00:00Z"
DEFAULT_RUN_COMPLETE_CLOCK = "2026-08-05T10:00:00Z"
DEFAULT_INDUCTION_START = "2026-08-06T08:00:00Z"
DEFAULT_INDUCTION_END = "2026-08-06T12:00:00Z"


# --------------------------------------------------------------------------
# Record specifications
# --------------------------------------------------------------------------


def record_spec(
    account_ref: str,
    sequence_no: int,
    statement_amount_cents: int = 4000,
    address_line1: Optional[str] = None,
    city: str = "Atlanta",
    region_code: str = "GA",
    postal_code: str = "30301",
    postal_code_plus4: Optional[str] = "3001",
    **extra: Any,
) -> Dict[str, Any]:
    """One statement record's fields, without the owning file reference."""
    spec: Dict[str, Any] = {
        "account_ref": account_ref,
        "sequence_no": sequence_no,
        "statement_amount_cents": statement_amount_cents,
        "address_line1": address_line1 or f"{100 + sequence_no} Baseline Boulevard",
        "city": city,
        "region_code": region_code,
        "postal_code": postal_code,
        "postal_code_plus4": postal_code_plus4,
    }
    spec.update(extra)
    return spec


def record_specs(
    count: int,
    *,
    prefix: str = "ABC",
    first_number: int = 1001,
    statement_amount_cents: int = 4000,
    postal_code: str = "30301",
) -> List[Dict[str, Any]]:
    """A run of ``count`` well-formed records with consecutive account
    references and sequence numbers."""
    return [
        record_spec(
            f"{prefix}{first_number + i}",
            i + 1,
            statement_amount_cents=statement_amount_cents,
            postal_code=postal_code,
            postal_code_plus4=f"{4000 + i:04d}",
        )
        for i in range(count)
    ]


# --------------------------------------------------------------------------
# Single-step builders
# --------------------------------------------------------------------------


def set_clock(api: ApiClient, instant: str = DEFAULT_CLOCK_UTC) -> Dict[str, Any]:
    """Move the logical clock."""
    return get_success_data(api.set_clock(instant, BUREAU_ADMIN))


def register_client(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_client(f.client_payload(**overrides), BUREAU_ADMIN))


def fund_client(
    api: ApiClient, client_id: str, amount_cents: int = 100000, reference: str = "wire"
) -> Dict[str, Any]:
    """Deposit into the client's postage escrow; returns the updated client."""
    return get_success_data(
        api.create_postage_deposit(
            client_id,
            f.postage_deposit_payload(amount_cents=amount_cents, reference=reference),
            POSTAGE_CONTROLLER,
        )
    )


def register_insert_stock(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_insert_stock(f.insert_stock_payload(**overrides), BUREAU_ADMIN)
    )


def register_press_line(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_press_line(f.press_line_payload(**overrides), BUREAU_ADMIN)
    )


def register_entry_facility(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_entry_facility(f.entry_facility_payload(**overrides), BUREAU_ADMIN)
    )


def register_dr_site(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_dr_site(f.dr_site_payload(**overrides), BUREAU_ADMIN)
    )


def record_drill(api: ApiClient, site_id: str, result: str = "PASS") -> Dict[str, Any]:
    return get_success_data(
        api.create_drill(site_id, f.drill_payload(result=result), BUREAU_ADMIN)
    )


def ready_dr_site(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """The singleton disaster-recovery site with one passing drill on record."""
    site = register_dr_site(api, **overrides)
    return record_drill(api, site["id"], "PASS")


def create_draft_template(
    api: ApiClient, client_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_template(f.template_payload(client_id, **overrides), BUREAU_ADMIN)
    )


def activate_template(api: ApiClient, template_id: str) -> Dict[str, Any]:
    return get_success_data(api.activate_template(template_id, BUREAU_ADMIN))


def create_active_template(
    api: ApiClient, client_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A template version created and immediately activated."""
    draft = create_draft_template(api, client_id, **overrides)
    return activate_template(api, draft["id"])


def enroll_account(
    api: ApiClient, client_id: str, account_ref: str, channel: str = "EMAIL"
) -> Dict[str, Any]:
    return get_success_data(
        api.create_enrollment(
            f.enrollment_payload(client_id, account_ref=account_ref, channel=channel),
            CLIENT_LIAISON,
        )
    )


def confirm_enrollments(
    api: ApiClient, client_id: str, account_refs: Sequence[str]
) -> Dict[str, Any]:
    """Run a suppression-file synchronisation over the named accounts."""
    return get_success_data(
        api.paperless_sync(
            client_id,
            f.paperless_sync_payload(list(account_refs)),
            CLIENT_LIAISON,
        )
    )


def suppress_account(
    api: ApiClient, client_id: str, account_ref: str, channel: str = "EMAIL"
) -> Dict[str, Any]:
    """Enroll one account and confirm it, so its next piece composes
    suppressed."""
    enrollment = enroll_account(api, client_id, account_ref, channel)
    confirm_enrollments(api, client_id, [account_ref])
    return get_success_data(api.get_enrollment(enrollment["id"], CLIENT_LIAISON))


# --------------------------------------------------------------------------
# Data file builders
# --------------------------------------------------------------------------


def lodge_data_file(api: ApiClient, client_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_data_file(f.data_file_payload(client_id, **overrides), CLIENT_LIAISON)
    )


def attach_records(
    api: ApiClient, file_id: str, specs: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    return [
        get_success_data(
            api.create_statement_record(
                f.statement_record_payload(file_id, **spec), CLIENT_LIAISON
            )
        )
        for spec in specs
    ]


def validate_file_format(api: ApiClient, file_id: str) -> Dict[str, Any]:
    return get_success_data(api.validate_format(file_id, COMPOSITION_OPERATOR))


def run_control_check(api: ApiClient, file_id: str) -> Dict[str, Any]:
    return get_success_data(api.control_check(file_id, COMPOSITION_OPERATOR))


@dataclass
class FileBundle:
    """A data file together with the records attached to it."""

    data_file: Dict[str, Any]
    records: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.data_file["id"]

    @property
    def status(self) -> str:
        return self.data_file["status"]


def lodged_file(
    api: ApiClient,
    client_id: str,
    specs: Sequence[Dict[str, Any]],
    **file_overrides: Any,
) -> FileBundle:
    """A RECEIVED file with its records attached."""
    specs = list(specs)
    file_overrides.setdefault("declared_record_count", len(specs))
    file_overrides.setdefault(
        "declared_control_total_cents",
        sum(s.get("statement_amount_cents", 4000) for s in specs),
    )
    data_file = lodge_data_file(api, client_id, **file_overrides)
    records = attach_records(api, data_file["id"], specs)
    return FileBundle(data_file=data_file, records=records)


def accepted_file(
    api: ApiClient,
    client_id: str,
    specs: Sequence[Dict[str, Any]],
    **file_overrides: Any,
) -> FileBundle:
    """A file walked through format validation and control reconciliation, so
    it is ACCEPTED and ready for composition."""
    bundle = lodged_file(api, client_id, specs, **file_overrides)
    validate_file_format(api, bundle.id)
    bundle.data_file = run_control_check(api, bundle.id)
    return bundle


# --------------------------------------------------------------------------
# Job lifecycle steps
# --------------------------------------------------------------------------


def compose_job(
    api: ApiClient,
    data_file_id: str,
    template_id: str,
    rush_requested: bool = False,
    user_id: str = OPERATOR_USER_ID,
) -> Dict[str, Any]:
    headers = headers_for(Role.COMPOSITION_OPERATOR.value, user_id)
    return get_success_data(
        api.create_composition_job(
            f.composition_job_payload(data_file_id, template_id, rush_requested),
            headers,
        )
    )


def list_pieces(api: ApiClient, job_id: str, **params: Any) -> List[Dict[str, Any]]:
    """Every mail piece of a job, in piece sequence order."""
    query: Dict[str, Any] = {"composition_job_id": job_id, "limit": 100}
    query.update(params)
    data, _meta = validate_paginated(api.list_mail_pieces(INTEGRITY_AUDITOR, query))
    return data


def presort_job(
    api: ApiClient, job_id: str, user_id: str = OPERATOR_USER_ID
) -> Dict[str, Any]:
    headers = headers_for(Role.COMPOSITION_OPERATOR.value, user_id)
    return get_success_data(api.presort_job(job_id, headers))


def list_batches(api: ApiClient, job_id: str) -> List[Dict[str, Any]]:
    """Every presort batch of a job, in creation order."""
    data, _meta = validate_paginated(
        api.list_presort_batches(
            POSTAGE_CONTROLLER, {"composition_job_id": job_id, "limit": 100}
        )
    )
    return data


def schedule_job(
    api: ApiClient,
    job_id: str,
    window_start: str = DEFAULT_WINDOW_START,
    press_line_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Schedule the job; returns the created print run."""
    return get_success_data(
        api.schedule_job(
            job_id,
            f.schedule_payload(window_start, press_line_id),
            PRODUCTION_SCHEDULER,
        )
    )


def start_run(api: ApiClient, run_id: str) -> Dict[str, Any]:
    return get_success_data(api.start_run(run_id, PRODUCTION_SCHEDULER))


def complete_run(api: ApiClient, run_id: str) -> Dict[str, Any]:
    return get_success_data(api.complete_run(run_id, PRODUCTION_SCHEDULER))


def abort_run(
    api: ApiClient, run_id: str, abort_reason: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.abort_run(run_id, PRODUCTION_SCHEDULER, f.abort_payload(abort_reason))
    )


def scan_stage(
    api: ApiClient,
    piece_id: str,
    stage: str,
    barcode: str,
    device_code: str = "SCN-1",
) -> Dict[str, Any]:
    return get_success_data(
        api.create_scan(
            piece_id, f.scan_payload(stage, barcode, device_code), INTEGRITY_AUDITOR
        )
    )


def scan_piece_fully(
    api: ApiClient, piece: Dict[str, Any], device_code: str = "SCN-1"
) -> List[Dict[str, Any]]:
    """Read one piece cleanly at all three production stages, in order."""
    return [
        scan_stage(api, piece["id"], stage, piece["imb_barcode"], device_code)
        for stage in SCAN_STAGE_ORDER
    ]


def reconcile(api: ApiClient, job_id: str) -> Dict[str, Any]:
    return get_success_data(api.reconcile_integrity(job_id, INTEGRITY_AUDITOR))


def seal_batch(
    api: ApiClient,
    batch_id: str,
    expected_client_version: int,
    user_id: str = POSTAGE_USER_ID,
) -> Dict[str, Any]:
    headers = headers_for(Role.POSTAGE_CONTROLLER.value, user_id)
    return get_success_data(
        api.seal_batch(batch_id, f.seal_payload(expected_client_version), headers)
    )


def unseal_batch(
    api: ApiClient, batch_id: str, user_id: str = POSTAGE_USER_ID
) -> Dict[str, Any]:
    headers = headers_for(Role.POSTAGE_CONTROLLER.value, user_id)
    return get_success_data(api.unseal_batch(batch_id, headers))


def manifest_batch(
    api: ApiClient,
    batch_id: str,
    entry_facility_id: str,
    induction_window_start: str = DEFAULT_INDUCTION_START,
    induction_window_end: str = DEFAULT_INDUCTION_END,
    user_id: str = POSTAGE_USER_ID_2,
) -> Dict[str, Any]:
    headers = headers_for(Role.POSTAGE_CONTROLLER.value, user_id)
    return get_success_data(
        api.manifest_batch(
            batch_id,
            f.manifest_payload(
                entry_facility_id, induction_window_start, induction_window_end
            ),
            headers,
        )
    )


def close_job(
    api: ApiClient, job_id: str, user_id: str = ADMIN_USER_ID_2
) -> Dict[str, Any]:
    headers = headers_for(Role.BUREAU_ADMIN.value, user_id)
    return get_success_data(api.close_job(job_id, headers))


def read_client(api: ApiClient, client_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_client(client_id, BUREAU_ADMIN))


def read_job(api: ApiClient, job_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_composition_job(job_id, COMPOSITION_OPERATOR))


def read_piece(api: ApiClient, piece_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_mail_piece(piece_id, INTEGRITY_AUDITOR))


def read_batch(api: ApiClient, batch_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_presort_batch(batch_id, POSTAGE_CONTROLLER))


def read_press_line(api: ApiClient, line_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_press_line(line_id, PRODUCTION_SCHEDULER))


def read_run(api: ApiClient, run_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_print_run(run_id, PRODUCTION_SCHEDULER))


def read_insert_stock(api: ApiClient, insert_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_insert_stock(insert_id, BUREAU_ADMIN))


def read_facility(api: ApiClient, facility_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_entry_facility(facility_id, POSTAGE_CONTROLLER))


def read_data_file(api: ApiClient, file_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_data_file(file_id, CLIENT_LIAISON))


def read_record(api: ApiClient, record_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_statement_record(record_id, CLIENT_LIAISON))


def read_return(api: ApiClient, return_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_return(return_id, INTEGRITY_AUDITOR))


def read_dr_site(api: ApiClient, site_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_dr_site(site_id, BUREAU_ADMIN))


# --------------------------------------------------------------------------
# Pipeline builders
# --------------------------------------------------------------------------

#: The ordered lifecycle checkpoints a pipeline can be built up to.
PIPELINE_STAGES = [
    "composed",
    "presorted",
    "scheduled",
    "printing",
    "printed",
    "reconciled",
    "sealed",
    "manifested",
    "closed",
]


@dataclass
class Pipeline:
    """Everything a lifecycle build produced, so a test can assert on any link
    of the chain without re-deriving it."""

    api: ApiClient
    client: Dict[str, Any]
    template: Dict[str, Any]
    file: FileBundle
    job: Dict[str, Any]
    press_line: Optional[Dict[str, Any]] = None
    facility: Optional[Dict[str, Any]] = None
    pieces: List[Dict[str, Any]] = field(default_factory=list)
    batches: List[Dict[str, Any]] = field(default_factory=list)
    run: Optional[Dict[str, Any]] = None

    # -- convenience accessors ------------------------------------------
    @property
    def client_id(self) -> str:
        return self.client["id"]

    @property
    def template_id(self) -> str:
        return self.template["id"]

    @property
    def file_id(self) -> str:
        return self.file.id

    @property
    def job_id(self) -> str:
        return self.job["id"]

    @property
    def run_id(self) -> str:
        assert self.run is not None, "this pipeline was not scheduled"
        return self.run["id"]

    @property
    def batch(self) -> Dict[str, Any]:
        assert len(self.batches) == 1, (
            f"expected exactly one presort batch, found {len(self.batches)}"
        )
        return self.batches[0]

    @property
    def piece(self) -> Dict[str, Any]:
        assert len(self.pieces) == 1, (
            f"expected exactly one mail piece, found {len(self.pieces)}"
        )
        return self.pieces[0]

    @property
    def printable_pieces(self) -> List[Dict[str, Any]]:
        """Pieces that are actually put on the press, i.e. not suppressed."""
        return [p for p in self.pieces if p["piece_status"] != "SUPPRESSED"]

    # -- refreshers -----------------------------------------------------
    def refresh_client(self) -> Dict[str, Any]:
        self.client = read_client(self.api, self.client_id)
        return self.client

    def refresh_job(self) -> Dict[str, Any]:
        self.job = read_job(self.api, self.job_id)
        return self.job

    def refresh_pieces(self) -> List[Dict[str, Any]]:
        self.pieces = list_pieces(self.api, self.job_id)
        return self.pieces

    def refresh_batches(self) -> List[Dict[str, Any]]:
        self.batches = list_batches(self.api, self.job_id)
        return self.batches

    def refresh_run(self) -> Dict[str, Any]:
        self.run = read_run(self.api, self.run_id)
        return self.run

    def refresh_press_line(self) -> Dict[str, Any]:
        assert self.press_line is not None, "this pipeline has no press line"
        self.press_line = read_press_line(self.api, self.press_line["id"])
        return self.press_line

    def refresh_facility(self) -> Dict[str, Any]:
        assert self.facility is not None, "this pipeline has no entry facility"
        self.facility = read_facility(self.api, self.facility["id"])
        return self.facility


def build_pipeline(
    api: ApiClient,
    *,
    stage: str = "composed",
    clock: Optional[str] = DEFAULT_CLOCK_UTC,
    client_code: str = "CLP1",
    client_overrides: Optional[Dict[str, Any]] = None,
    fund_cents: Optional[int] = None,
    template_code: str = "T-P1",
    template_overrides: Optional[Dict[str, Any]] = None,
    press_line_code: str = "PL-P1",
    press_line_overrides: Optional[Dict[str, Any]] = None,
    with_press_line: Optional[bool] = None,
    facility_code: str = "EF-P1",
    facility_overrides: Optional[Dict[str, Any]] = None,
    with_facility: Optional[bool] = None,
    file_name: str = "p1.csv",
    file_overrides: Optional[Dict[str, Any]] = None,
    specs: Optional[Sequence[Dict[str, Any]]] = None,
    rush_requested: bool = False,
    compose_user_id: str = OPERATOR_USER_ID,
    window_start: str = DEFAULT_WINDOW_START,
    run_start_clock: Optional[str] = DEFAULT_RUN_START_CLOCK,
    run_complete_clock: Optional[str] = DEFAULT_RUN_COMPLETE_CLOCK,
    unscanned_piece_indexes: Sequence[int] = (),
    seal_user_id: str = POSTAGE_USER_ID,
    manifest_user_id: str = POSTAGE_USER_ID_2,
    induction_window_start: str = DEFAULT_INDUCTION_START,
    induction_window_end: str = DEFAULT_INDUCTION_END,
    close_user_id: str = ADMIN_USER_ID_2,
) -> Pipeline:
    """Carry one job from composition to the requested lifecycle checkpoint.

    ``unscanned_piece_indexes`` names printable pieces to leave unread, which is
    how a reconciliation is steered into the integrity-hold branch rather than
    the verified one.
    """
    assert stage in PIPELINE_STAGES, f"unknown pipeline stage {stage!r}"
    target = PIPELINE_STAGES.index(stage)

    if clock is not None:
        set_clock(api, clock)

    client = register_client(api, client_code=client_code, **(client_overrides or {}))
    if fund_cents is not None:
        client = fund_client(api, client["id"], amount_cents=fund_cents)

    template = create_active_template(
        api, client["id"], template_code=template_code, **(template_overrides or {})
    )

    needs_press = with_press_line if with_press_line is not None else target >= 2
    press_line = (
        register_press_line(
            api, line_code=press_line_code, **(press_line_overrides or {})
        )
        if needs_press
        else None
    )

    needs_facility = with_facility if with_facility is not None else target >= 7
    facility = (
        register_entry_facility(
            api, facility_code=facility_code, **(facility_overrides or {})
        )
        if needs_facility
        else None
    )

    bundle = accepted_file(
        api,
        client["id"],
        list(specs) if specs is not None else record_specs(1),
        file_name=file_name,
        **(file_overrides or {}),
    )

    job = compose_job(
        api, bundle.id, template["id"], rush_requested, user_id=compose_user_id
    )
    pipeline = Pipeline(
        api=api,
        client=client,
        template=template,
        file=bundle,
        job=job,
        press_line=press_line,
        facility=facility,
        pieces=list_pieces(api, job["id"]),
    )
    if target == 0:
        return pipeline

    pipeline.job = presort_job(api, pipeline.job_id, user_id=compose_user_id)
    pipeline.refresh_pieces()
    pipeline.refresh_batches()
    if target == 1:
        return pipeline

    assert press_line is not None, "scheduling needs a press line"
    pipeline.run = schedule_job(
        api, pipeline.job_id, window_start, press_line["id"]
    )
    pipeline.refresh_job()
    if target == 2:
        return pipeline

    if run_start_clock is not None:
        set_clock(api, run_start_clock)
    pipeline.run = start_run(api, pipeline.run_id)
    pipeline.refresh_job()
    pipeline.refresh_pieces()
    if target == 3:
        return pipeline

    skip = {
        i % len(pipeline.printable_pieces) for i in unscanned_piece_indexes
    } if unscanned_piece_indexes else set()
    for index, piece in enumerate(pipeline.printable_pieces):
        if index in skip:
            continue
        scan_piece_fully(api, piece)
    if run_complete_clock is not None:
        set_clock(api, run_complete_clock)
    pipeline.run = complete_run(api, pipeline.run_id)
    pipeline.refresh_job()
    pipeline.refresh_pieces()
    if target == 4:
        return pipeline

    pipeline.job = reconcile(api, pipeline.job_id)
    pipeline.refresh_pieces()
    if target == 5:
        return pipeline

    sealed: List[Dict[str, Any]] = []
    for batch in pipeline.refresh_batches():
        # Each seal moves the client's escrow, so the pin is re-read per batch.
        client_version = pipeline.refresh_client()["version"]
        sealed.append(
            seal_batch(api, batch["id"], client_version, user_id=seal_user_id)
        )
    pipeline.batches = sealed
    pipeline.refresh_client()
    if target == 6:
        return pipeline

    assert facility is not None, "manifesting needs an entry facility"
    pipeline.batches = [
        manifest_batch(
            api,
            batch["id"],
            facility["id"],
            induction_window_start,
            induction_window_end,
            user_id=manifest_user_id,
        )
        for batch in pipeline.batches
    ]
    pipeline.refresh_job()
    pipeline.refresh_pieces()
    if target == 7:
        return pipeline

    pipeline.job = close_job(api, pipeline.job_id, user_id=close_user_id)
    return pipeline


# --------------------------------------------------------------------------
# Named lifecycle shortcuts
# --------------------------------------------------------------------------


def composed_job(api: ApiClient, **kwargs: Any) -> Pipeline:
    """A freshly composed job with its mail pieces minted."""
    return build_pipeline(api, stage="composed", **kwargs)


def presorted_job(api: ApiClient, **kwargs: Any) -> Pipeline:
    """A presorted job with its batches materialised."""
    return build_pipeline(api, stage="presorted", **kwargs)


def scheduled_job(api: ApiClient, **kwargs: Any) -> Pipeline:
    """A job with a PLANNED print run on a press line."""
    return build_pipeline(api, stage="scheduled", **kwargs)


def printing_job(api: ApiClient, **kwargs: Any) -> Pipeline:
    """A job whose run has been started, so its pieces are scannable."""
    return build_pipeline(api, stage="printing", **kwargs)


def printed_job(api: ApiClient, **kwargs: Any) -> Pipeline:
    """A job scanned through production with its run completed, awaiting
    reconciliation."""
    return build_pipeline(api, stage="printed", **kwargs)


def verified_job(api: ApiClient, **kwargs: Any) -> Pipeline:
    """A cleanly scanned job reconciled to the verified branch."""
    return build_pipeline(api, stage="reconciled", **kwargs)


def integrity_held_job(
    api: ApiClient, unscanned_piece_indexes: Sequence[int] = (-1,), **kwargs: Any
) -> Pipeline:
    """A job reconciled with at least one unread piece, so it sits in the
    integrity-hold branch."""
    return build_pipeline(
        api,
        stage="reconciled",
        unscanned_piece_indexes=unscanned_piece_indexes,
        **kwargs,
    )


def sealed_batches(api: ApiClient, **kwargs: Any) -> Pipeline:
    """A verified job whose batches are sealed against the client's escrow."""
    kwargs.setdefault("fund_cents", 100000)
    return build_pipeline(api, stage="sealed", **kwargs)


def manifested_job(api: ApiClient, **kwargs: Any) -> Pipeline:
    """A job whose batches are all manifested into an induction window."""
    kwargs.setdefault("fund_cents", 100000)
    return build_pipeline(api, stage="manifested", **kwargs)


def closed_job(api: ApiClient, **kwargs: Any) -> Pipeline:
    """A fully manifested job closed, with its penalty assessed and invoice
    computed."""
    kwargs.setdefault("fund_cents", 100000)
    return build_pipeline(api, stage="closed", **kwargs)


# --------------------------------------------------------------------------
# Integrity, reprint and return helpers
# --------------------------------------------------------------------------


def reprint_piece(
    api: ApiClient,
    piece_id: str,
    expected_job_version: int,
    reason: str = "integrity failure",
) -> Dict[str, Any]:
    """Queue a replacement for a failed piece; returns the replacement piece."""
    return get_success_data(
        api.create_reprint(
            piece_id, f.reprint_payload(expected_job_version, reason), INTEGRITY_AUDITOR
        )
    )


def read_integrity_summary(
    api: ApiClient, job_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.get_integrity_summary(job_id, headers or INTEGRITY_AUDITOR)
    )


def scan_events(api: ApiClient, piece_id: str, **params: Any) -> List[Dict[str, Any]]:
    """A piece's scan log, oldest read first."""
    query: Dict[str, Any] = {"limit": 100}
    query.update(params)
    data, _meta = validate_paginated(
        api.list_scan_events(piece_id, INTEGRITY_AUDITOR, query)
    )
    return data


def intake_return(
    api: ApiClient, piece_id: str, reason_code: str = "VACANT"
) -> Dict[str, Any]:
    """Scan a returned envelope into the undeliverable queue."""
    return get_success_data(
        api.create_return(f.return_payload(piece_id, reason_code), INTEGRITY_AUDITOR)
    )


def classify_return(
    api: ApiClient,
    return_id: str,
    corrected_address_line1: Optional[str] = None,
    corrected_postal_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Classify a scanned return, with or without a forwarding address."""
    return get_success_data(
        api.classify_return(
            return_id,
            INTEGRITY_AUDITOR,
            f.classify_payload(corrected_address_line1, corrected_postal_code),
        )
    )


def release_feedback(
    api: ApiClient, client_id: str, note: str = "Address correction release"
) -> Dict[str, Any]:
    """Release the client's address-update feedback batch."""
    return get_success_data(
        api.release_address_feedback(
            client_id, f.address_feedback_payload(note), CLIENT_LIAISON
        )
    )


def file_records(api: ApiClient, file_id: str, **params: Any) -> List[Dict[str, Any]]:
    """A data file's statement records, in ascending sequence order."""
    query: Dict[str, Any] = {"limit": 100}
    query.update(params)
    data, _meta = validate_paginated(
        api.list_file_records(file_id, CLIENT_LIAISON, query)
    )
    return data


def amend_declared_totals(
    api: ApiClient,
    file_id: str,
    declared_record_count: Optional[int] = None,
    declared_control_total_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """Amend a held file's declared trailer figures."""
    return get_success_data(
        api.amend_control_totals(
            file_id,
            f.amend_control_totals_payload(
                declared_record_count, declared_control_total_cents
            ),
            CLIENT_LIAISON,
        )
    )


def patch_client(api: ApiClient, client_id: str, **fields: Any) -> Dict[str, Any]:
    """Amend a client's mutable terms; returns the updated client."""
    return get_success_data(api.patch_client(client_id, fields, BUREAU_ADMIN))


def patch_dr_site(api: ApiClient, site_id: str, **fields: Any) -> Dict[str, Any]:
    """Amend the disaster-recovery site's observed posture."""
    return get_success_data(api.patch_dr_site(site_id, fields, BUREAU_ADMIN))


def list_runs(api: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    """Print runs, filtered by whatever the caller supplies."""
    query: Dict[str, Any] = {"limit": 100}
    query.update(params)
    data, _meta = validate_paginated(api.list_print_runs(PRODUCTION_SCHEDULER, query))
    return data
